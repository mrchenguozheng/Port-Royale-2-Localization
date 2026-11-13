use std::ffi::c_void;
use std::fs;
use std::path::Path;
use std::ptr;

use pr2_common::{
    exe_dir, fonts_dir, bundled_fonts_complete, pack_runtime_ok, read_locale_language,
    valid_lang_code, FONT_NAMES, RUNTIME_VERSION,
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
    CREATE_SUSPENDED, INFINITE, LPTHREAD_START_ROUTINE, PROCESS_INFORMATION, STARTUPINFOA,
};

const ORIG_FONT_SIZES: [u64; 4] = [296712, 65680, 52876, 53120];
const ORIG_FONT_HASHES: [&str; 4] = [
    "1906a771ed879a5de75a3ff552fbad533827fe7b39e18319ce9d9ae134c346c7",
    "f3715e59051796963fc6569d85c16b9abfd6eaf949bcc8a9578c1fe0a423acf9",
    "267f1a2de1c1e738202ca31008c587e045d25268c93662d8fd80b79615d314e7",
    "fd10e52dd5040de4fc00e09919b5e5e360039360deff5bfc2219ffa61061c465",
];

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

    for arg in std::env::args().skip(1) {
        if let Some(v) = arg.strip_prefix("--lang=") {
            lang = Some(v.to_string());
        } else if arg == "--vanilla" {
            vanilla = true;
        } else if arg == "--help" || arg == "-h" {
            println!("[PR2Loc] 用法: PR2Localization.exe [--lang=<代码>] [--vanilla]");
            println!("[PR2Loc]   --lang     这一次启动用哪个语言包，");
            println!("[PR2Loc]              优先于 PR2Localization\\packs\\locale.ini 的 language=，不写文件。");
            println!("[PR2Loc]   --vanilla  恢复原版字体后直接启动 PR2.exe，不注入。");
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

    let exe_path = root.join("PR2.exe");
    if !exe_path.is_file() {
        eprintln!("[PR2Loc] 同目录下找不到 PR2.exe: {}", exe_path.display());
        return Err(1);
    }

    backup_original_fonts(&root);

    if vanilla {
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
        println!("[PR2Loc] 已恢复原版字体，启动原版 PR2.exe（未注入）");
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

    let font_dir = font_lang
        .as_ref()
        .filter(|code| valid_lang_code(code))
        .and_then(|code| {
            let dir = fonts_dir(&root).join(code);
            if dir.is_dir() && bundled_fonts_complete(&root, code) {
                Some(dir)
            } else {
                None
            }
        });

    if let Some(code) = font_lang.as_ref() {
        if valid_lang_code(code) && fonts_dir(&root).join(code).is_dir() && font_dir.is_none()
            && !pr2_common::language_fonts_complete(&root, code)
        {
            eprintln!(
                "[PR2Loc] PR2Localization\\fonts\\{} 字体不完整，回退到原版根目录字体",
                code
            );
        }
    }

    match &font_dir {
        Some(_) => {
            if let Some(code) = font_lang.as_ref() {
                std::env::set_var("PR2_FONT_DIR", code);
                println!("[PR2Loc] 字体使用 PR2Localization\\fonts\\{code}\\（不覆盖原版）");
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
