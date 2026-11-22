use std::ffi::c_void;
use std::fs;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::ptr;

use pr2_common::{
    bundled_fonts_complete, detect_edition, exe_dir, fonts_dir, host_script_path, host_state,
    log_dir, pack_runtime_ok, read_locale_language, valid_lang_code, Edition, HostState, FONT_NAMES,
    HOST_DLL, HOST_MOUNT_SCRIPT, HOST_ORIG, RUNTIME_VERSION,
};
use sha2::{Digest, Sha256};
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError};
use windows_sys::Win32::System::Console::{SetConsoleCP, SetConsoleOutputCP};
use windows_sys::Win32::System::Diagnostics::Debug::WriteProcessMemory;
use windows_sys::Win32::System::LibraryLoader::{
    GetModuleHandleA, GetProcAddress,
};
use windows_sys::Win32::System::Memory::{
    VirtualAllocEx, MEM_COMMIT, PAGE_READWRITE,
};
use windows_sys::Win32::System::Threading::{
    CreateProcessA, CreateRemoteThread, GetExitCodeThread, ResumeThread, WaitForSingleObject,
    CREATE_NO_WINDOW, CREATE_SUSPENDED, INFINITE, LPTHREAD_START_ROUTINE, PROCESS_INFORMATION,
    STARTUPINFOA,
};

const ORIG_FONT_SIZES: [u64; 4] = [296712, 65680, 52876, 53120];const ORIG_FONT_HASHES: [&str; 4] = [
    "1906a771ed879a5de75a3ff552fbad533827fe7b39e18319ce9d9ae134c346c7",
    "f3715e59051796963fc6569d85c16b9abfd6eaf949bcc8a9578c1fe0a423acf9",
    "267f1a2de1c1e738202ca31008c587e045d25268c93662d8fd80b79615d314e7",
    "fd10e52dd5040de4fc00e09919b5e5e360039360deff5bfc2219ffa61061c465",
];

/// 宿主动作（挂载/还原）的落盘日志，GUI 读它来显示失败原因。
const HOST_LOG_FILE: &str = "host.log";

fn main() {
    unsafe {
        let _ = SetConsoleOutputCP(65001);
        let _ = SetConsoleCP(65001);
    }
    if let Err(code) = run() {
        std::process::exit(code);
    }
}

fn run() -> Result<(), i32> {
    let root = exe_dir();
    let mut lang: Option<String> = None;
    let mut vanilla = false;
    let mut restore = false;

    for arg in std::env::args().skip(1) {
        if let Some(v) = arg.strip_prefix("--lang=") {
            lang = Some(v.to_string());
        } else if arg == "--vanilla" {
            vanilla = true;
        } else if arg == "--restore" {
            restore = true;
        } else if arg == "--help" || arg == "-h" {
            println!("[PR2Loc] 用法: PR2Localization.exe [--lang=<代码>] [--vanilla] [--restore]");
            println!("[PR2Loc]   不给参数时按版本自动选路：GOG 注入启动，Steam 先挂载宿主 DLL 再启动。");
            println!("[PR2Loc]   --lang     这一次启动用哪个语言包，");
            println!("[PR2Loc]              优先于 PR2Localization\\packs\\locale.ini（或 locale.default.ini）的 language=，不写文件。");
            println!("[PR2Loc]   --vanilla  恢复原版字体（Steam 还会先还原宿主 DLL），启动 PR2.exe，不注入。");
            println!("[PR2Loc]   --restore  只还原：Steam 还原 Ascaron.Logging-2.6.dll，两版都恢复原版字体，不启动游戏。");
            return Ok(());
        }
    }
    if let Some(code) = &lang {
        if !valid_lang_code(code) {
            eprintln!("[PR2Loc] --lang 的值不合法: {code}");
            eprintln!("[PR2Loc] 只允许字母、数字、连字符和下划线，例如 --lang=zh 或 --lang=zh-TW。");
            return Err(1);
        }
    }
    if restore && vanilla {
        eprintln!("[PR2Loc] --restore 与 --vanilla 不能同时使用。");
        return Err(1);
    }

    let exe_path = root.join("PR2.exe");
    if !exe_path.is_file() {
        eprintln!("[PR2Loc] 同目录下找不到 PR2.exe: {}", exe_path.display());
        return Err(1);
    }

    if restore {
        return restore_all(&root);
    }

    let edition = detect_edition(&root);
    backup_original_fonts(&root);

    if vanilla {
        if edition == Edition::Steam {
            restore_steam_host(&root)?;
        }
        restore_original_fonts(&root);
        match create_process(&exe_path, &root, 0) {
            Ok(pi) => {
                unsafe {
                    CloseHandle(pi.hThread);
                    CloseHandle(pi.hProcess);
                }
            }
            Err(_) => {
                eprintln!(
                    "[PR2Loc] 启动原版 PR2.exe 失败 (错误 {})",
                    unsafe { GetLastError() }
                );
                return Err(1);
            }
        }
        println!("[PR2Loc] 已恢复原版状态，启动原版 PR2.exe（未注入）");
        return Ok(());
    }

    let dll_path = root.join("PR2LocalizationCore.dll");
    if !dll_path.is_file() {
        eprintln!(
            "[PR2Loc] 同目录下找不到 PR2LocalizationCore.dll: {}",
            dll_path.display()
        );
        return Err(1);
    }

    if edition == Edition::Steam {
        ensure_steam_host(&root)?;
    }

    let font_lang = match &lang {
        Some(v) => Some(v.clone()),
        None => read_locale_language(&root),
    };
    if let Some(code) = &font_lang {
        if valid_lang_code(code) && !pack_runtime_ok(&root, code) {
            eprintln!(
                "[PR2Loc] 语言包 {} 需要运行时 v{}，当前 v{}，拒绝启动",
                code,
                pr2_common::pack_min_runtime(&root, code),
                RUNTIME_VERSION
            );
            return Err(1);
        }
    }

    let font_dir = font_lang
        .as_ref()
        .filter(|code| valid_lang_code(code))
        .and_then(|code| {
            if fonts_dir(&root).is_dir() && bundled_fonts_complete(&root, code) {
                Some(fonts_dir(&root))
            } else {
                None
            }
        });

    if let Some(code) = font_lang.as_ref() {
        if valid_lang_code(code) && fonts_dir(&root).is_dir() && font_dir.is_none()
            && !pr2_common::language_fonts_complete(&root, code)
        {
            eprintln!(
                "[PR2Loc] PR2Localization\\fonts 字体不完整，回退到原版根目录字体"
            );
        }
    }

    match &font_dir {
        Some(_) => {
            if let Some(code) = font_lang.as_ref() {
                std::env::set_var("PR2_FONT_DIR", code);
                println!("[PR2Loc] 字体使用 PR2Localization\\fonts（不覆盖原版）");
            }
        }
        None => {
            std::env::remove_var("PR2_FONT_DIR");
        }
    }

    if let Some(code) = &lang {
        std::env::set_var("PR2_PACK_LANG", code);
        println!("[PR2Loc] 本次使用语言包: {code}.txt (优先于 locale.ini，本次启动生效)");
    }

    if edition == Edition::Steam {
        // Steam 不注入：根目录的宿主代理由 PR2.exe 静态导入，自己会加载同一个 Core。
        let pi = match create_process(&exe_path, &root, 0) {
            Ok(v) => v,
            Err(_) => {
                eprintln!(
                    "[PR2Loc] 启动 PR2.exe 失败 (错误 {})",
                    unsafe { GetLastError() }
                );
                return Err(1);
            }
        };
        unsafe {
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
        }
        println!("[PR2Loc] Steam 版：宿主代理已就位，PR2.exe 启动中...");
        return Ok(());
    }

    let pi = match create_process(&exe_path, &root, CREATE_SUSPENDED) {
        Ok(v) => v,
        Err(_) => {
            eprintln!(
                "[PR2Loc] 启动 PR2.exe 失败 (错误 {})",
                unsafe { GetLastError() }
            );
            return Err(1);
        }
    };

    let result = inject_dll(&pi, &dll_path);
    unsafe {
        ResumeThread(pi.hThread);
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    match result {
        Ok(()) => {
            println!("[PR2Loc] 语言包已注入, PR2.exe 启动中...");
            Ok(())
        }
        Err(code) => Err(code),
    }
}

/// Steam：根目录是原版就调脚本挂载，已经挂载就跳过。
fn ensure_steam_host(root: &Path) -> Result<(), i32> {
    match host_state(root) {
        HostState::Mounted => {
            println!("[PR2Loc] Steam 宿主代理已在位，跳过挂载");
            host_log_line(root, "宿主代理已在位，跳过挂载");
            Ok(())
        }
        HostState::Original => {
            println!("[PR2Loc] Steam 版：校验原版宿主 DLL、建立备份并挂载代理…");
            host_log_line(root, "校验原版宿主 DLL、建立备份并挂载代理");
            run_host_script(root, "Mount").map(|_| ())
        }
        HostState::Missing => {
            host_log(
                root,
                &format!("同目录下找不到 {HOST_DLL}，这不像是 Steam 版；请确认游戏目录。"),
            );
            Err(1)
        }
        HostState::Unknown => {
            host_log(
                root,
                &format!("根目录 {HOST_DLL} 不是已知原版，也没有可验证的 {HOST_ORIG}。"),
            );
            host_log(root, "为避免覆盖其他 mod 或损坏的文件，已停止。");
            host_log(
                root,
                "可以先用 Steam 的「验证游戏文件完整性」把原版 DLL 恢复，再重试。",
            );
            Err(1)
        }
    }
}

/// `--vanilla` 在 Steam 版下先还原宿主，再启动原版。
fn restore_steam_host(root: &Path) -> Result<(), i32> {
    match host_state(root) {
        HostState::Original => Ok(()),
        HostState::Mounted => run_host_script(root, "Restore").map(|_| ()),
        HostState::Missing => {
            host_log(root, &format!("同目录下找不到 {HOST_DLL}，不需要还原。"));
            Err(1)
        }
        HostState::Unknown => {
            host_log(
                root,
                &format!("根目录 {HOST_DLL} 不是本工具挂上去的代理，拒绝覆盖未知文件。"),
            );
            Err(1)
        }
    }
}

/// `--restore`：Steam 还原宿主 DLL，两版都恢复原版字体，不启动游戏。
fn restore_all(root: &Path) -> Result<(), i32> {
    // 本次还原的过程单独记一份，GUI 用 CREATE_NO_WINDOW 调起时看不到控制台，
    // 失败后就读这份日志给玩家看。
    clear_host_log(root);
    let edition = detect_edition(root);
    if edition == Edition::Steam {
        if host_state(root) == HostState::Original {
            println!("[PR2Loc] Steam 宿主 DLL 已经是原版，不需要还原");
            host_log_line(root, "宿主 DLL 已经是原版，不需要还原");
        } else {
            restore_steam_host(root)?;
            println!("[PR2Loc] 已把 {HOST_DLL} 换回 Steam 原版");
            host_log_line(root, &format!("已把 {HOST_DLL} 换回 Steam 原版"));
        }
    } else {
        println!("[PR2Loc] 这是 GOG 版，没有需要还原的宿主 DLL");
        host_log_line(root, "这是 GOG 版，没有需要还原的宿主 DLL");
    }
    restore_original_fonts(root);
    println!("[PR2Loc] 还原完成（本地化文件仍在，只是不再挂载/注入）");
    host_log_line(root, "还原完成（本地化文件仍在，只是不再挂载/注入）");
    Ok(())
}

/// 控制台和 `PR2Localization\logs\host.log` 各写一份，给只有 stderr 的失败路径用。
///
/// STEAM 版的所有宿主动作都由 GUI 以 `CREATE_NO_WINDOW` 拉起，玩家看不到控制台，
/// 所以失败原因必须落盘，GUI 才能把它显示出来。
fn host_log(root: &Path, message: &str) {
    eprintln!("[PR2Loc] {message}");
    host_log_line(root, message);
}

/// 只写日志文件；调用方已经自己 `println!` 过的时候用它，避免同一句话打印两遍。
fn host_log_line(root: &Path, message: &str) {
    use std::io::Write;
    let path = log_dir(root).join(HOST_LOG_FILE);
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(&path) {
        let _ = writeln!(file, "[PR2Loc] {message}");
    }
}

fn clear_host_log(root: &Path) {
    let _ = fs::write(log_dir(root).join(HOST_LOG_FILE), "");
}

/// 调发行包里的 PR2HostMount.ps1。替换动作只有那一份实现，这里只管传参。
fn run_host_script(root: &Path, action: &str) -> Result<String, i32> {
    let script = host_script_path(root);
    if !script.is_file() {
        host_log(
            root,
            &format!("同目录下找不到 {HOST_MOUNT_SCRIPT}，无法处理 Steam 宿主 DLL。"),
        );
        return Err(1);
    }
    let system_root = std::env::var("SystemRoot").unwrap_or_else(|_| "C:\\Windows".into());
    let powershell = PathBuf::from(&system_root)
        .join("System32")
        .join("WindowsPowerShell")
        .join("v1.0")
        .join("powershell.exe");
    let program = if powershell.is_file() {
        powershell.into_os_string()
    } else {
        "powershell.exe".into()
    };

    // 用 -Command 而不是 -File：脚本要在子进程里先把输出编码设成 UTF-8，
    // 否则 Windows PowerShell 5.1 用 OEM 代码页写 stdout，读回来是乱码。
    let quote = |s: &str| format!("'{}'", s.replace('\'', "''"));
    let command = format!(
        "try {{ [Console]::OutputEncoding=[System.Text.Encoding]::UTF8 }} catch {{}}; & {} -Action {} -Target {}",
        quote(&script.to_string_lossy()),
        quote(action),
        quote(&root.to_string_lossy())
    );

    let output = Command::new(program)
        .arg("-NoProfile")
        .arg("-ExecutionPolicy")
        .arg("Bypass")
        .arg("-Command")
        .arg(&command)
        .current_dir(root)
        // 从 PowerShell 7 的终端启动时，继承来的 PSModulePath 会让 5.1 找不到
        // 自己的模块（Get-FileHash、Copy-Item 都会报未知命令），这里清掉。
        .env_remove("PSModulePath")
        .creation_flags(CREATE_NO_WINDOW)
        .output()
        .map_err(|exc| {
            host_log(root, &format!("调用 PowerShell 失败：{exc}"));
            1
        })?;

    let stdout = String::from_utf8_lossy(&output.stdout).into_owned();
    let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
    if !output.status.success() {
        let code = output
            .status
            .code()
            .map(|c| c.to_string())
            .unwrap_or_else(|| "未知".into());
        host_log(root, &format!("{action} 失败（脚本退出码 {code}）："));
        for line in stderr.lines().chain(stdout.lines()) {
            let line = line.trim();
            if !line.is_empty() {
                host_log(root, line);
            }
        }
        return Err(2);
    }
    for line in stdout.lines() {
        let line = line.trim();
        if !line.is_empty() {
            println!("[PR2Loc] {line}");
            host_log_line(root, line);
        }
    }
    Ok(stdout)
}

fn create_process(exe: &Path, root: &Path, flags: u32) -> Result<PROCESS_INFORMATION, ()> {
    let exe_c = path_cstr(exe);
    let root_c = path_cstr(root);
    let mut si: STARTUPINFOA = unsafe { std::mem::zeroed() };
    si.cb = std::mem::size_of::<STARTUPINFOA>() as u32;
    let mut pi: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    let ok = unsafe {
        CreateProcessA(
            exe_c.as_ptr(),
            ptr::null_mut(),
            ptr::null(),
            ptr::null(),
            0,
            flags,
            ptr::null(),
            root_c.as_ptr(),
            &si,
            &mut pi,
        )
    };
    if ok == 0 {
        Err(())
    } else {
        Ok(pi)
    }
}

fn inject_dll(pi: &PROCESS_INFORMATION, dll: &Path) -> Result<(), i32> {
    let bytes = path_cstr(dll);
    let size = bytes.len();
    let remote = unsafe {
        VirtualAllocEx(
            pi.hProcess,
            ptr::null(),
            size,
            MEM_COMMIT,
            PAGE_READWRITE,
        )
    };
    if remote.is_null() {
        eprintln!(
            "[PR2Loc] VirtualAllocEx 失败 {}",
            unsafe { GetLastError() }
        );
        return Err(1);
    }
    let wrote = unsafe {
        WriteProcessMemory(
            pi.hProcess,
            remote,
            bytes.as_ptr() as *const c_void,
            size,
            ptr::null_mut(),
        )
    };
    if wrote == 0 {
        eprintln!(
            "[PR2Loc] WriteProcessMemory 失败 {}",
            unsafe { GetLastError() }
        );
        return Err(1);
    }
    let k32 = unsafe { GetModuleHandleA(b"kernel32.dll\0".as_ptr()) };
    let load_lib = unsafe { GetProcAddress(k32, b"LoadLibraryA\0".as_ptr()) };
    let load_lib = match load_lib {
        Some(f) => f,
        None => {
            eprintln!("[PR2Loc] 找不到 LoadLibraryA");
            return Err(1);
        }
    };
    let start: LPTHREAD_START_ROUTINE = unsafe { std::mem::transmute(load_lib as usize) };
    let th = unsafe {
        CreateRemoteThread(
            pi.hProcess,
            ptr::null(),
            0,
            start,
            remote,
            0,
            ptr::null_mut(),
        )
    };
    if th == 0 {
        eprintln!(
            "[PR2Loc] CreateRemoteThread 失败 {}",
            unsafe { GetLastError() }
        );
        return Err(1);
    }
    unsafe {
        WaitForSingleObject(th, INFINITE);
    }
    let mut exit = 0u32;
    unsafe {
        GetExitCodeThread(th, &mut exit);
        CloseHandle(th);
    }
    if exit == 0 {
        eprintln!("[PR2Loc] PR2LocalizationCore.dll 注入失败 (LoadLibrary 返回 NULL)");
        eprintln!("[PR2Loc] 提示: 游戏可能因缺少 VC 运行库或 DLL 缺失而未能加载补丁。");
        return Err(1);
    }
    Ok(())
}

fn path_cstr(path: &Path) -> Vec<u8> {
    let s = path.to_string_lossy();
    let mut bytes: Vec<u8> = s.as_bytes().to_vec();
    bytes.push(0);
    bytes
}

fn backup_original_fonts(root: &Path) {
    let bak = fonts_dir(root).join("_original");
    if bak.exists() {
        return;
    }
    if !looks_like_original_fonts(root) {
        println!("[PR2Loc] 根目录 fonts 不是原版字体，跳过原版备份");
        return;
    }
    let _ = fs::create_dir_all(&bak);
    let mut n = 0;
    for name in FONT_NAMES {
        let src = root.join("fonts").join(name);
        let dst = bak.join(name);
        if fs::copy(src, dst).is_ok() {
            n += 1;
        }
    }
    if n == 4 {
        println!("[PR2Loc] 已备份原版字体: PR2Localization\\fonts\\_original\\");
    } else {
        println!("[PR2Loc] 原版字体备份不完整（{n}/4）");
    }
}

fn restore_original_fonts(root: &Path) {
    let bak = fonts_dir(root).join("_original");
    if !bak.is_dir() {
        return;
    }
    let mut n = 0;
    for (i, name) in FONT_NAMES.iter().enumerate() {
        let src = bak.join(name);
        let dst = root.join("fonts").join(name);
        if let Some(hex) = file_sha256(&src) {
            if hex.eq_ignore_ascii_case(ORIG_FONT_HASHES[i]) && fs::copy(src, dst).is_ok() {
                n += 1;
            } else {
                println!("[PR2Loc] 原版备份哈希不匹配，拒绝恢复: {name}");
            }
        }
    }
    if n > 0 {
        println!("[PR2Loc] 已恢复原版字体 ({n}/4)");
    }
}

fn looks_like_original_fonts(root: &Path) -> bool {
    for (i, name) in FONT_NAMES.iter().enumerate() {
        let path = root.join("fonts").join(name);
        if file_size(&path) != ORIG_FONT_SIZES[i] {
            return false;
        }
        if let Some(hex) = file_sha256(&path) {
            if !hex.eq_ignore_ascii_case(ORIG_FONT_HASHES[i]) {
                println!("[PR2Loc] 字体大小像原版但 SHA-256 不匹配，跳过备份: {name}");
                return false;
            }
        } else {
            return false;
        }
    }
    true
}

fn file_size(path: &Path) -> u64 {
    fs::metadata(path)
        .map(|m| if m.is_dir() { u64::MAX } else { m.len() })
        .unwrap_or(u64::MAX)
}

fn file_sha256(path: &Path) -> Option<String> {
    let data = fs::read(path).ok()?;
    let digest = Sha256::digest(&data);
    let mut out = String::with_capacity(64);
    for b in digest {
        out.push_str(&format!("{b:02x}"));
    }
    Some(out)
}
