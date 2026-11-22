use std::ffi::c_void;
use std::fs;
use std::path::Path;
use std::ptr;

use pr2_common::{
    bundled_fonts_complete, detect_edition, exe_dir, fonts_dir, has_host_dll, host_state,
    launch_mode, log_dir, mount_host, pack_runtime_ok, proxy_loaded_after, proxy_log_len,
    read_locale_language, restore_host as restore_host_dll, steam_run_url, valid_lang_code,
    Edition, HostState, LaunchMode, LaunchModeError, FONT_NAMES, HOST_DLL, HOST_ORIG,
    RUNTIME_VERSION,
};
use sha2::{Digest, Sha256};
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE};
use windows_sys::Win32::System::Console::{SetConsoleCP, SetConsoleOutputCP};
use windows_sys::Win32::System::Diagnostics::Debug::WriteProcessMemory;
use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleA, GetProcAddress};
use windows_sys::Win32::System::Memory::{VirtualAllocEx, MEM_COMMIT, PAGE_READWRITE};
use windows_sys::Win32::System::Threading::{
    CreateProcessA, CreateRemoteThread, GetExitCodeThread, ResumeThread, WaitForSingleObject,
    CREATE_SUSPENDED, INFINITE, LPTHREAD_START_ROUTINE, PROCESS_INFORMATION, STARTUPINFOA,
};
use windows_sys::Win32::UI::Shell::ShellExecuteW;

const ORIG_FONT_SIZES: [u64; 4] = [296712, 65680, 52876, 53120];
const ORIG_FONT_HASHES: [&str; 4] = [
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
    let mut mount_only = false;
    let mut force_inject = false;

    for arg in std::env::args().skip(1) {
        if let Some(v) = arg.strip_prefix("--lang=") {
            lang = Some(v.to_string());
        } else if arg == "--vanilla" {
            vanilla = true;
        } else if arg == "--restore" {
            restore = true;
        } else if arg == "--mount" {
            mount_only = true;
        } else if arg == "--inject" {
            force_inject = true;
        } else if arg == "--version" {
            // 发行版本与 commit 由构建脚本注入（src\build_injector.ps1）；
            // 开发构建显示 dev，不谎报一个发行版本号。
            println!(
                "[PR2Loc] PR2Localization {} · 运行时 v{}",
                pr2_common::build_label(),
                RUNTIME_VERSION
            );
            return Ok(());
        } else if arg == "--help" || arg == "-h" {
            println!("[PR2Loc] 用法: PR2Localization.exe [--lang=<代码>] [--vanilla] [--restore] [--mount] [--inject]");
            println!("[PR2Loc]   不给参数时先挂载宿主代理，再由对应版本的方式拉起游戏：");
            println!(
                "[PR2Loc]   GOG 版直启 PR2.exe；Steam 版交给客户端（steam://rungameid/12470）。"
            );
            println!("[PR2Loc]   --lang     这一次启动用哪个语言包，");
            println!("[PR2Loc]              优先于 PR2Localization\\packs\\locale.ini 的 language=，不写文件。");
            println!("[PR2Loc]              只有 GOG 版支持：Steam 拉起的进程不是本进程的子进程，");
            println!("[PR2Loc]              环境变量传不过去，换语言要改 locale.ini。");
            println!(
                "[PR2Loc]   --vanilla  先还原宿主 DLL 与原版字体，再以对应版本的方式启动原版游戏。"
            );
            println!("[PR2Loc]   --restore  只还原：把 Ascaron.Logging-2.6.dll 换回原版，恢复原版字体，不启动游戏。");
            println!(
                "[PR2Loc]   --mount    只挂载：校验原版、建立两份备份、换入代理，不启动游戏。"
            );
            println!(
                "[PR2Loc]   --inject   不挂载宿主，退回远程注入启动（只给排查用，需管理员权限）。"
            );
            println!("[PR2Loc]   --version  打印发行版本、构建 commit 与运行时版本，不启动游戏。");
            return Ok(());
        }
    }
    if let Some(code) = &lang {
        if !valid_lang_code(code) {
            eprintln!("[PR2Loc] --lang 的值不合法: {code}");
            eprintln!(
                "[PR2Loc] 只允许字母、数字、连字符和下划线，例如 --lang=zh 或 --lang=zh-TW。"
            );
            return Err(1);
        }
    }
    if restore && vanilla {
        eprintln!("[PR2Loc] --restore 与 --vanilla 不能同时使用。");
        return Err(1);
    }
    if mount_only && (restore || vanilla) {
        eprintln!("[PR2Loc] --mount 不能与 --restore / --vanilla 同时使用。");
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
    if mount_only {
        return mount_host_only(&root);
    }

    let edition = detect_edition(&root);
    let edition_label = if edition == Edition::Steam {
        "Steam"
    } else {
        "GOG"
    };
    let mode = match launch_mode(edition, lang.is_some(), force_inject) {
        Ok(mode) => mode,
        Err(LaunchModeError::SteamLangUnsupported) => {
            eprintln!("[PR2Loc] Steam 版不接受 --lang：游戏由 Steam 客户端拉起，");
            eprintln!("[PR2Loc] 启动器的环境变量传不进那个进程。换语言请改");
            eprintln!("[PR2Loc]   PR2Localization\\packs\\locale.ini 里的 language=");
            host_log_line(&root, "Steam 版拒绝 --lang：换语言要改 locale.ini。");
            return Err(1);
        }
    };
    backup_original_fonts(&root);

    if vanilla {
        // 两版都可能挂过宿主代理，--vanilla 一律先还原再启动。
        restore_host(&root)?;
        restore_original_fonts(&root);
        if mode == LaunchMode::Steam {
            println!("[PR2Loc] 已恢复原版状态，交给 Steam 启动原版游戏");
            return launch_by_steam(&root, "已恢复原版状态");
        }
        match create_process(&exe_path, &root, 0) {
            Ok(pi) => unsafe {
                CloseHandle(pi.hThread);
                CloseHandle(pi.hProcess);
            },
            Err(_) => {
                eprintln!("[PR2Loc] 启动原版 PR2.exe 失败 (错误 {})", unsafe {
                    GetLastError()
                });
                return Err(1);
            }
        }
        println!("[PR2Loc] 已恢复原版状态，启动原版 PR2.exe（未加载语言包）");
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

    if mode == LaunchMode::Steam {
        // Steam 版：字体与语言包都由代理在进程内按 locale.ini 决定。
        // 启动器这边没有环境变量可传 —— Steam 拉起的 PR2.exe 不是它的子进程。
        if !has_host_dll(&root) {
            host_log(
                &root,
                &format!(
                    "根目录没有 {HOST_DLL}（{edition_label} 版），Steam 版没有可接管的导入点。"
                ),
            );
            return Err(1);
        }
        println!("[PR2Loc] Steam 版交给客户端启动：{}", steam_run_url());
        ensure_host(&root)?;
        return launch_by_steam(&root, "Steam 版交给客户端启动");
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
        if valid_lang_code(code)
            && fonts_dir(&root).is_dir()
            && font_dir.is_none()
            && !pr2_common::language_fonts_complete(&root, code)
        {
            eprintln!("[PR2Loc] PR2Localization\\fonts 字体不完整，回退到原版根目录字体");
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

    if force_inject {
        println!("[PR2Loc] --inject：跳过宿主挂载，走远程注入");
        host_log_line(&root, "--inject：跳过宿主挂载，走远程注入");
        return launch_by_inject(&root, &exe_path, &dll_path);
    }

    if !has_host_dll(&root) {
        // 没有宿主 DLL 就只剩注入一条路。这不是失败降级，是这个版本本来就没有
        // 可供代理接管的导入；写清楚理由，别让玩家以为宿主路径静默跳过了。
        host_log(
            &root,
            &format!("根目录没有 {HOST_DLL}（{edition_label} 版），这一版只能走远程注入。"),
        );
        return launch_by_inject(&root, &exe_path, &dll_path);
    }

    ensure_host(&root)?;
    launch_by_host(&root, &exe_path)
}

/// 两版共用的挂载入口：原版就挂载，已挂载就跳过。
///
/// 替换动作在 `pr2_common::host` 里，进程内直接做，不再拉 PowerShell。
fn ensure_host(root: &Path) -> Result<(), i32> {
    match host_state(root) {
        HostState::Mounted => {
            println!("[PR2Loc] 宿主代理已在位，跳过挂载");
            host_log_line(root, "宿主代理已在位，跳过挂载");
            Ok(())
        }
        HostState::Original => {
            println!("[PR2Loc] 校验原版宿主 DLL、建立备份并挂载代理…");
            host_log_line(root, "校验原版宿主 DLL、建立备份并挂载代理");
            mount_host(root).map_err(|e| {
                host_log(root, &format!("挂载失败：{e}"));
                1
            })
        }
        HostState::Missing => {
            // 调用方已经用 has_host_dll 判过一遍，走到这里说明文件在检查之后消失。
            host_log(
                root,
                &format!("同目录下找不到 {HOST_DLL}；请确认游戏目录。"),
            );
            Err(1)
        }
        HostState::ProxyNoBackup => {
            host_log(
                root,
                &format!("根目录 {HOST_DLL} 已是本地化代理，但找不到有效的原版备份（{HOST_ORIG} / PR2Localization\\host-backup）。"),
            );
            host_log(
                root,
                "没有原版就无法回滚；请用平台的「验证游戏文件完整性」把原版 DLL 恢复，再重新启动。",
            );
            Err(1)
        }
        HostState::Unknown => {
            host_log(
                root,
                &format!("根目录 {HOST_DLL} 不是已知原版，也不是本工具挂上去的代理。"),
            );
            host_log(root, "为避免覆盖其他 mod 或损坏的文件，已停止。");
            host_log(
                root,
                "可以先用平台的「验证游戏文件完整性」把原版 DLL 恢复，再重试。",
            );
            Err(1)
        }
    }
}

/// `--vanilla` / `--restore`：把宿主 DLL 换回原版。两版同一套判断。
fn restore_host(root: &Path) -> Result<(), i32> {
    match host_state(root) {
        HostState::Original => Ok(()),
        HostState::Mounted => restore_host_dll(root).map_err(|e| {
            host_log(root, &format!("还原失败：{e}"));
            1
        }),
        // 没有这个文件就没有可还原的东西：GOG 某些版本不带宿主 DLL，不该判失败。
        HostState::Missing => {
            println!("[PR2Loc] 同目录下没有 {HOST_DLL}，不需要还原");
            host_log_line(root, &format!("同目录下没有 {HOST_DLL}，不需要还原"));
            Ok(())
        }
        HostState::ProxyNoBackup => {
            host_log(
                root,
                &format!(
                    "根目录 {HOST_DLL} 是本地化代理，但原版备份缺失或不可验证；没有可还原的文件。"
                ),
            );
            host_log(
                root,
                "请用平台的「验证游戏文件完整性」把原版 DLL 恢复（这会把该 DLL 换回官方版本）。",
            );
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

/// 宿主路径：先记 proxy.log 的基线，再直启 PR2.exe，最后确认代理真的进了进程。
fn launch_by_host(root: &Path, exe_path: &Path) -> Result<(), i32> {
    // 基线必须在启动前取：判定只看「这一次新写进来的那几行」。
    let log_offset = proxy_log_len(root);
    let pi = match create_process(exe_path, root, 0) {
        Ok(v) => v,
        Err(_) => {
            eprintln!("[PR2Loc] 启动 PR2.exe 失败 (错误 {})", unsafe {
                GetLastError()
            });
            return Err(1);
        }
    };
    println!("[PR2Loc] 宿主代理已就位，PR2.exe 启动中...");
    let loaded = watch_proxy(root, log_offset, pi.hProcess);
    unsafe {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    if loaded {
        println!("[PR2Loc] 宿主代理已进入 PR2.exe 进程");
        host_log_line(root, "宿主代理已进入 PR2.exe 进程");
    } else {
        // 不杀进程、不自动重来：游戏已经在跑，杀掉重开只会更糟。
        // 只把事实写进日志，并给出可用的下一步。
        host_log(
            root,
            "启动后没看到宿主代理进入 PR2.exe 进程（logs\\proxy.log 没有新的加载标记）。",
        );
        host_log(
            root,
            "说明这个 PR2.exe 没有加载根目录的宿主 DLL；可用 --inject 走远程注入。",
        );
    }
    Ok(())
}

/// 等代理在进程里写下加载标记，最多 15 秒；进程提前退出就立刻结束等待。
fn watch_proxy(root: &Path, offset: u64, process: HANDLE) -> bool {
    for _ in 0..30 {
        // 先等 500ms 再看日志，避免抢在代理写盘之前判空。
        let exited = unsafe { WaitForSingleObject(process, 500) } == 0;
        if proxy_loaded_after(root, offset) {
            return true;
        }
        if exited {
            return false;
        }
    }
    false
}

/// Steam 版：把游戏交给客户端拉起，而不是自己 CreateProcess。
///
/// `Program Files` 下的 `PR2.exe` 直接建进程会拿到错误 740（需要提升权限），
/// 而 Steam 客户端本来就在自己的环境里启动它，顺便把 DRM 也处理掉。
///
/// 这里只确认「已把请求交给 Steam」就返回：Steam 拉起的进程不是本进程的
/// 子进程，启动器既看不到它的句柄，也无法判断代理有没有加载。等 15 秒去
/// 轮询 `proxy.log` 只能得到「可能还没起来」的猜测，不能当成验证结果。
fn launch_by_steam(root: &Path, reason: &str) -> Result<(), i32> {
    let url = steam_run_url();
    let url_w = pr2_common::wide(&url);
    let open_w = pr2_common::wide("open");
    let shown = unsafe {
        ShellExecuteW(
            0, // 没有父窗口
            open_w.as_ptr(),
            url_w.as_ptr(),
            ptr::null(),
            ptr::null(),
            1, // SW_SHOWNORMAL
        )
    };
    // ShellExecute 的老约定：返回值大于 32 才算成功，其余是错误码。
    if (shown as isize) <= 32 {
        host_log(
            root,
            &format!(
                "请求 Steam 启动失败：{url}（ShellExecute 返回 {}）",
                shown as isize
            ),
        );
        return Err(1);
    }
    println!("[PR2Loc] 已请求 Steam 启动：{url}");
    host_log_line(root, &format!("{reason}（{url}）"));
    Ok(())
}

/// 注入路径：挂起进程 → 远程 LoadLibrary → 恢复。只有 `--inject` 和
/// 「根目录没有宿主 DLL」会走到这里。
fn launch_by_inject(root: &Path, exe_path: &Path, dll: &Path) -> Result<(), i32> {
    let pi = match create_process(exe_path, root, CREATE_SUSPENDED) {
        Ok(v) => v,
        Err(_) => {
            eprintln!("[PR2Loc] 启动 PR2.exe 失败 (错误 {})", unsafe {
                GetLastError()
            });
            return Err(1);
        }
    };

    let result = inject_dll(&pi, dll);
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

/// `--mount`：只挂载宿主代理，不启动游戏。部署与排查用。
fn mount_host_only(root: &Path) -> Result<(), i32> {
    clear_host_log(root);
    mount_host(root).map_err(|e| {
        host_log(root, &format!("挂载失败：{e}"));
        1
    })?;
    match host_state(root) {
        HostState::Mounted => {
            println!("[PR2Loc] 宿主代理已挂载（{HOST_DLL} 已换成本地化代理）");
            host_log_line(root, "宿主代理已挂载");
            Ok(())
        }
        other => {
            host_log(root, &format!("挂载后状态异常：{other:?}"));
            Err(1)
        }
    }
}

/// `--restore`：把宿主 DLL 换回原版、恢复原版字体，不启动游戏。
fn restore_all(root: &Path) -> Result<(), i32> {
    // 本次还原的过程单独记一份，GUI 用 CREATE_NO_WINDOW 调起时看不到控制台，
    // 失败后就读这份日志给玩家看。
    clear_host_log(root);
    match host_state(root) {
        HostState::Original => {
            println!("[PR2Loc] 宿主 DLL 已经是原版，不需要还原");
            host_log_line(root, "宿主 DLL 已经是原版，不需要还原");
        }
        HostState::Missing => {
            println!("[PR2Loc] 同目录下没有 {HOST_DLL}，不需要还原");
            host_log_line(root, &format!("同目录下没有 {HOST_DLL}，不需要还原"));
        }
        _ => {
            restore_host(root)?;
            println!("[PR2Loc] 已把 {HOST_DLL} 换回原版");
            host_log_line(root, &format!("已把 {HOST_DLL} 换回原版"));
        }
    }
    restore_original_fonts(root);
    println!("[PR2Loc] 还原完成（本地化文件仍在，只是不再挂载/注入）");
    host_log_line(root, "还原完成（本地化文件仍在，只是不再挂载/注入）");
    Ok(())
}

/// 控制台和 `PR2Localization\logs\host.log` 各写一份，给只有 stderr 的失败路径用。
///
/// 宿主动作都由 GUI 以 `CREATE_NO_WINDOW` 拉起，玩家看不到控制台，
/// 所以失败原因必须落盘，GUI 才能把它显示出来。
fn host_log(root: &Path, message: &str) {
    eprintln!("[PR2Loc] {message}");
    host_log_line(root, message);
}

/// 只写日志文件；调用方已经自己 `println!` 过的时候用它，避免同一句话打印两遍。
fn host_log_line(root: &Path, message: &str) {
    use std::io::Write;
    // 宿主动作开始前会清空这份日志，正常只有一次动作的几十行；上限只防失败路径
    // 反复重试时把文件写爆（超过 1 MiB 就把旧档滚成 `host.log.1`）。
    let path = log_dir(root).join(HOST_LOG_FILE);
    if let Some(mut file) = pr2_common::open_append_capped(&path, pr2_common::DEFAULT_MAX_BYTES) {
        let _ = writeln!(file, "[PR2Loc] {message}");
    }
}

fn clear_host_log(root: &Path) {
    let _ = fs::write(log_dir(root).join(HOST_LOG_FILE), "");
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
    let remote =
        unsafe { VirtualAllocEx(pi.hProcess, ptr::null(), size, MEM_COMMIT, PAGE_READWRITE) };
    if remote.is_null() {
        eprintln!("[PR2Loc] VirtualAllocEx 失败 {}", unsafe {
            GetLastError()
        });
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
        eprintln!("[PR2Loc] WriteProcessMemory 失败 {}", unsafe {
            GetLastError()
        });
        return Err(1);
    }
    let k32 = unsafe { GetModuleHandleA(c"kernel32.dll".as_ptr() as *const u8) };
    let load_lib = unsafe { GetProcAddress(k32, c"LoadLibraryA".as_ptr() as *const u8) };
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
        eprintln!("[PR2Loc] CreateRemoteThread 失败 {}", unsafe {
            GetLastError()
        });
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
