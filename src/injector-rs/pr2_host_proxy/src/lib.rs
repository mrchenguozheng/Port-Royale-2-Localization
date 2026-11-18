//! Steam host DLL proxy: replaces `Ascaron.Logging-2.6.dll`.
//!
//! `PR2.exe` statically imports this DLL and only uses the `Log` export. The
//! original DLL is renamed to `Ascaron.Logging-2.6.orig.dll`; `Log` forwards
//! to it. A bootstrap thread waits for `A2dLib-2.20A.dll` and then loads the
//! sibling `PR2LocalizationCore.dll`, so Core initialization never blocks the
//! host loader.
//!
//! The `Log` export is written in x86 assembly: it must preserve all registers
//! and tail-jump to the original function without knowing its signature.

#![allow(non_snake_case)]

use std::ffi::{c_void, OsString};
use std::fs::OpenOptions;
use std::io::Write;
use std::os::windows::ffi::OsStringExt;
use std::path::{Path, PathBuf};
use std::ptr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::OnceLock;

use pr2_common::log_dir;
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, HMODULE};
use windows_sys::Win32::System::LibraryLoader::{
    DisableThreadLibraryCalls, GetModuleFileNameW, GetModuleHandleW, GetProcAddress,
    LoadLibraryW,
};
use windows_sys::Win32::System::Threading::{CreateThread, Sleep};

const HOST_ORIG: &str = "Ascaron.Logging-2.6.orig.dll";
const CORE_DLL: &str = "PR2LocalizationCore.dll";
const A2D_DLL: &str = "A2dLib-2.20A.dll";

#[no_mangle]
pub static ORIGINAL_LOG: AtomicUsize = AtomicUsize::new(0);
static SELF_DIR: OnceLock<PathBuf> = OnceLock::new();

core::arch::global_asm!(
    ".text",
    ".globl _Log",
    "_Log:",
    "pushfd",
    "pushad",
    "call _ensure_original",
    "popad",
    "popfd",
    "jmp dword ptr [_ORIGINAL_LOG]",
    ".section .drectve,\"yn\"",
    ".ascii \" /EXPORT:Log=_Log\"",
);

fn wide(s: &str) -> Vec<u16> {
    let mut v: Vec<u16> = s.encode_utf16().collect();
    v.push(0);
    v
}

fn module_dir(hinst: HMODULE) -> PathBuf {
    let mut buf = [0u16; 260];
    let n = unsafe { GetModuleFileNameW(hinst, buf.as_mut_ptr(), buf.len() as u32) };
    if n == 0 {
        return PathBuf::from(".");
    }
    PathBuf::from(OsString::from_wide(&buf[..n as usize]))
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn log_line(dir: &Path, msg: &str) {
    let logdir = log_dir(dir);
    if let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(logdir.join("proxy.log"))
    {
        let _ = writeln!(file, "{msg}");
    }
}

/// Resolve the original `Log` export on first use. Called from the assembly
/// shim while all registers are saved; it must be a plain cdecl function.
#[no_mangle]
pub extern "C" fn ensure_original() {
    if ORIGINAL_LOG.load(Ordering::Acquire) != 0 {
        return;
    }

    let dir = SELF_DIR.get().cloned().unwrap_or_else(|| PathBuf::from("."));
    let path = dir.join(HOST_ORIG);
    let h = unsafe { LoadLibraryW(wide(path.to_string_lossy().as_ref()).as_ptr()) };
    if h == 0 {
        log_line(&dir, &format!("[host] original Log load failed: {}", unsafe {
            GetLastError()
        }));
        return;
    }

    match unsafe { GetProcAddress(h, b"Log\0".as_ptr()) } {
        Some(f) => {
            ORIGINAL_LOG.store(f as usize, Ordering::Release);
            log_line(&dir, "[host] original Log resolved");
        }
        None => {
            log_line(&dir, "[host] original Log missing");
        }
    }
}

unsafe extern "system" fn bootstrap_thread(param: *mut c_void) -> u32 {
    let hinst = param as HMODULE;
    // Do not call the loader while DllMain still holds the loader lock.
    Sleep(50);
    let dir = module_dir(hinst);
    log_line(&dir, "[host] bootstrap thread start");

    for _ in 0..100 {
        if unsafe { GetModuleHandleW(wide(A2D_DLL).as_ptr()) } != 0 {
            break;
        }
        Sleep(100);
    }
    log_line(&dir, "[host] wait for A2dLib done");
    Sleep(50);

    let core = dir.join(CORE_DLL);
    let h = unsafe { LoadLibraryW(wide(core.to_string_lossy().as_ref()).as_ptr()) };
    if h == 0 {
        log_line(
            &dir,
            &format!("[host] core load failed: {}", unsafe { GetLastError() }),
        );
    } else {
        log_line(&dir, "[host] loaded PR2LocalizationCore.dll");
    }
    0
}

fn start_bootstrap(hinst: HMODULE) {
    let thread = unsafe {
        CreateThread(
            ptr::null(),
            0,
            Some(bootstrap_thread),
            hinst as *mut c_void,
            0,
            ptr::null_mut(),
        )
    };
    if thread != 0 {
        unsafe { CloseHandle(thread as HANDLE) };
    }
}

#[no_mangle]
pub extern "system" fn DllMain(hinst: HANDLE, reason: u32, _reserved: *mut c_void) -> i32 {
    if reason == 1 {
        let module = hinst as HMODULE;
        unsafe { DisableThreadLibraryCalls(module) };
        let dir = module_dir(module);
        let _ = SELF_DIR.set(dir.clone());
        log_line(&dir, "[host] DllMain loaded");
        start_bootstrap(module);
    }
    1
}
