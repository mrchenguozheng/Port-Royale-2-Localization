//! Minimal `VERSION.dll` proxy.
//!
//! PR2.exe imports `VERSION.dll`; Windows resolves that import from the game
//! directory first. This proxy forwards the version APIs to the real system
//! DLL and, on a worker thread, loads the sibling `PR2LocalizationCore.dll`.
//!
//! The worker is created from `DllMain`, but the actual `LoadLibraryW` happens
//! after `DllMain` returns, so it never calls the loader while the process
//! loader lock is held.

#![allow(non_snake_case)]

use std::ffi::{c_void, OsString};
use std::io::Write;
use std::os::windows::ffi::OsStringExt;
use std::path::{Path, PathBuf};
use std::ptr;
use std::sync::OnceLock;

use pr2_common::log_dir;
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, HMODULE};
use windows_sys::Win32::System::LibraryLoader::{
    DisableThreadLibraryCalls, GetModuleFileNameW, GetProcAddress, LoadLibraryW,
};
use windows_sys::Win32::System::SystemInformation::GetSystemDirectoryW;
use windows_sys::Win32::System::Threading::{CreateThread, Sleep};

const TEXT_SOURCE: &str = "PR2LocalizationCore.dll";

type GetFileVersionInfoAFn =
    unsafe extern "system" fn(*const u8, u32, u32, *mut c_void) -> i32;
type GetFileVersionInfoWFn =
    unsafe extern "system" fn(*const u16, u32, u32, *mut c_void) -> i32;
type GetFileVersionInfoSizeAFn = unsafe extern "system" fn(*const u8, *mut u32) -> u32;
type GetFileVersionInfoSizeWFn = unsafe extern "system" fn(*const u16, *mut u32) -> u32;
type GetFileVersionInfoExAFn =
    unsafe extern "system" fn(u32, *const u8, u32, u32, *mut c_void) -> i32;
type GetFileVersionInfoExWFn =
    unsafe extern "system" fn(u32, *const u16, u32, u32, *mut c_void) -> i32;
type GetFileVersionInfoSizeExAFn = unsafe extern "system" fn(u32, *const u8, *mut u32) -> u32;
type GetFileVersionInfoSizeExWFn = unsafe extern "system" fn(u32, *const u16, *mut u32) -> u32;
type VerQueryValueAFn =
    unsafe extern "system" fn(*const c_void, *const u8, *mut *mut c_void, *mut u32) -> i32;
type VerQueryValueWFn =
    unsafe extern "system" fn(*const c_void, *const u16, *mut *mut c_void, *mut u32) -> i32;

struct Api {
    gfvi_a: usize,
    gfvi_w: usize,
    gfvi_size_a: usize,
    gfvi_size_w: usize,
    gfvi_ex_a: usize,
    gfvi_ex_w: usize,
    gfvi_size_ex_a: usize,
    gfvi_size_ex_w: usize,
    ver_query_a: usize,
    ver_query_w: usize,
}

static API: OnceLock<Api> = OnceLock::new();

unsafe fn proc_addr(h: HMODULE, name: &[u8]) -> usize {
    match GetProcAddress(h, name.as_ptr()) {
        Some(f) => f as usize,
        None => 0,
    }
}

unsafe fn load_api() -> Api {
    // Resolve the real DLL by absolute System32 path. A bare name plus
    // LOAD_LIBRARY_SEARCH_SYSTEM32 can still resolve to this proxy in some
    // hosts, which turns every forwarded call into infinite recursion.
    let path = match system_version_path() {
        Some(p) => p,
        None => {
            log_line(&module_dir(0), "[proxy] cannot resolve System32 directory");
            return empty_api();
        }
    };
    let h = LoadLibraryW(path.as_ptr());
    if h == 0 {
        log_line(
            &module_dir(0),
            &format!("[proxy] system version.dll load failed: {}", GetLastError()),
        );
        return empty_api();
    }
    log_line(
        &module_dir(0),
        &format!("[proxy] system version.dll = {}", module_path(h)),
    );
    Api {
        gfvi_a: proc_addr(h, b"GetFileVersionInfoA\0"),
        gfvi_w: proc_addr(h, b"GetFileVersionInfoW\0"),
        gfvi_size_a: proc_addr(h, b"GetFileVersionInfoSizeA\0"),
        gfvi_size_w: proc_addr(h, b"GetFileVersionInfoSizeW\0"),
        gfvi_ex_a: proc_addr(h, b"GetFileVersionInfoExA\0"),
        gfvi_ex_w: proc_addr(h, b"GetFileVersionInfoExW\0"),
        gfvi_size_ex_a: proc_addr(h, b"GetFileVersionInfoSizeExA\0"),
        gfvi_size_ex_w: proc_addr(h, b"GetFileVersionInfoSizeExW\0"),
        ver_query_a: proc_addr(h, b"VerQueryValueA\0"),
        ver_query_w: proc_addr(h, b"VerQueryValueW\0"),
    }
}

fn empty_api() -> Api {
    Api {
        gfvi_a: 0,
        gfvi_w: 0,
        gfvi_size_a: 0,
        gfvi_size_w: 0,
        gfvi_ex_a: 0,
        gfvi_ex_w: 0,
        gfvi_size_ex_a: 0,
        gfvi_size_ex_w: 0,
        ver_query_a: 0,
        ver_query_w: 0,
    }
}

unsafe fn system_version_path() -> Option<Vec<u16>> {
    let mut dir = [0u16; 260];
    let n = GetSystemDirectoryW(dir.as_mut_ptr(), dir.len() as u32);
    if n == 0 || n as usize >= dir.len() {
        return None;
    }
    let mut path = Vec::with_capacity(n as usize + 14);
    path.extend_from_slice(&dir[..n as usize]);
    path.push(b'\\' as u16);
    path.extend_from_slice(&wide("version.dll"));
    Some(path)
}

fn api() -> &'static Api {
    API.get_or_init(|| unsafe { load_api() })
}

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

fn module_path(h: HMODULE) -> String {
    let mut buf = [0u16; 260];
    let n = unsafe { GetModuleFileNameW(h, buf.as_mut_ptr(), buf.len() as u32) };
    if n == 0 {
        return "<unknown>".to_string();
    }
    OsString::from_wide(&buf[..n as usize])
        .to_string_lossy()
        .into_owned()
}

fn log_line(dir: &Path, msg: &str) {
    let logdir = log_dir(dir);
    if let Some(mut f) = pr2_common::open_append_capped(
        &logdir.join("proxy.log"),
        pr2_common::DEFAULT_MAX_BYTES,
    ) {
        let _ = writeln!(f, "{msg}");
        return;
    }
    // `logs\` 写不进去时退回游戏根目录：根目录不可写的话代理本身也加载不了。
    if let Some(mut f) = pr2_common::open_append_capped(
        &dir.join("proxy.log"),
        pr2_common::DEFAULT_MAX_BYTES,
    ) {
        let _ = writeln!(f, "{msg}");
    }
}

unsafe extern "system" fn bootstrap_thread(param: *mut c_void) -> u32 {
    let hinst = param as HMODULE;
    // Let the process leave the loader lock before touching the loader again.
    Sleep(50);
    let dir = module_dir(hinst);
    let dll = dir.join(TEXT_SOURCE);
    let h = LoadLibraryW(wide(dll.to_string_lossy().as_ref()).as_ptr());
    if h == 0 {
        log_line(
            &dir,
            &format!(
                "[proxy] {} load failed: {}",
                TEXT_SOURCE,
                GetLastError()
            ),
        );
    } else {
        log_line(&dir, &format!("[proxy] loaded {}", TEXT_SOURCE));
    }
    0
}

fn start_bootstrap(hinst: HMODULE) {
    let th = unsafe {
        CreateThread(
            ptr::null(),
            0,
            Some(bootstrap_thread),
            hinst as *mut c_void,
            0,
            ptr::null_mut(),
        )
    };
    if th != 0 {
        unsafe { CloseHandle(th as HANDLE) };
    }
}

#[no_mangle]
pub extern "system" fn DllMain(hinst: HANDLE, reason: u32, _reserved: *mut c_void) -> i32 {
    if reason == 1 {
        unsafe { DisableThreadLibraryCalls(hinst as HMODULE) };
        start_bootstrap(hinst as HMODULE);
    }
    1
}

#[no_mangle]
pub extern "system" fn GetFileVersionInfoA(
    filename: *const u8,
    handle: u32,
    len: u32,
    data: *mut c_void,
) -> i32 {
    let f = api().gfvi_a;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: GetFileVersionInfoAFn = std::mem::transmute(f);
        f(filename, handle, len, data)
    }
}

#[no_mangle]
pub extern "system" fn GetFileVersionInfoW(
    filename: *const u16,
    handle: u32,
    len: u32,
    data: *mut c_void,
) -> i32 {
    let f = api().gfvi_w;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: GetFileVersionInfoWFn = std::mem::transmute(f);
        f(filename, handle, len, data)
    }
}

#[no_mangle]
pub extern "system" fn GetFileVersionInfoSizeA(filename: *const u8, handle: *mut u32) -> u32 {
    let f = api().gfvi_size_a;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: GetFileVersionInfoSizeAFn = std::mem::transmute(f);
        f(filename, handle)
    }
}

#[no_mangle]
pub extern "system" fn GetFileVersionInfoSizeW(filename: *const u16, handle: *mut u32) -> u32 {
    let f = api().gfvi_size_w;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: GetFileVersionInfoSizeWFn = std::mem::transmute(f);
        f(filename, handle)
    }
}

#[no_mangle]
pub extern "system" fn GetFileVersionInfoExA(
    flags: u32,
    filename: *const u8,
    handle: u32,
    len: u32,
    data: *mut c_void,
) -> i32 {
    let f = api().gfvi_ex_a;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: GetFileVersionInfoExAFn = std::mem::transmute(f);
        f(flags, filename, handle, len, data)
    }
}

#[no_mangle]
pub extern "system" fn GetFileVersionInfoExW(
    flags: u32,
    filename: *const u16,
    handle: u32,
    len: u32,
    data: *mut c_void,
) -> i32 {
    let f = api().gfvi_ex_w;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: GetFileVersionInfoExWFn = std::mem::transmute(f);
        f(flags, filename, handle, len, data)
    }
}

#[no_mangle]
pub extern "system" fn GetFileVersionInfoSizeExA(flags: u32, filename: *const u8, handle: *mut u32) -> u32 {
    let f = api().gfvi_size_ex_a;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: GetFileVersionInfoSizeExAFn = std::mem::transmute(f);
        f(flags, filename, handle)
    }
}

#[no_mangle]
pub extern "system" fn GetFileVersionInfoSizeExW(flags: u32, filename: *const u16, handle: *mut u32) -> u32 {
    let f = api().gfvi_size_ex_w;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: GetFileVersionInfoSizeExWFn = std::mem::transmute(f);
        f(flags, filename, handle)
    }
}

#[no_mangle]
pub extern "system" fn VerQueryValueA(
    block: *const c_void,
    sub_block: *const u8,
    buffer: *mut *mut c_void,
    len: *mut u32,
) -> i32 {
    let f = api().ver_query_a;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: VerQueryValueAFn = std::mem::transmute(f);
        f(block, sub_block, buffer, len)
    }
}

#[no_mangle]
pub extern "system" fn VerQueryValueW(
    block: *const c_void,
    sub_block: *const u16,
    buffer: *mut *mut c_void,
    len: *mut u32,
) -> i32 {
    let f = api().ver_query_w;
    if f == 0 {
        return 0;
    }
    unsafe {
        let f: VerQueryValueWFn = std::mem::transmute(f);
        f(block, sub_block, buffer, len)
    }
}
