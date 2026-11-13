#![allow(non_snake_case)]

use std::collections::{HashMap, HashSet};
use std::ffi::{c_char, c_void};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::os::windows::ffi::OsStringExt;
use std::path::Path;
use std::ptr;
use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicU32, AtomicUsize, Ordering};
use std::sync::{Mutex, OnceLock};

use pr2_common::{
    exe_dir, font_rel_dir, fonts_dir, log_dir, pack_dir, override_path, pack_path,
    read_locale_language, valid_lang_code,
};
use windows_sys::Win32::Foundation::{BOOL, CloseHandle, HANDLE, HMODULE};
use windows_sys::Win32::Storage::FileSystem::{
    GET_FILEEX_INFO_LEVELS, WIN32_FIND_DATAA,
};
use windows_sys::Win32::System::LibraryLoader::{
    DisableThreadLibraryCalls, GetModuleHandleA, GetProcAddress,
};
use windows_sys::Win32::System::Memory::{
    GetProcessHeap, HeapAlloc, MEMORY_BASIC_INFORMATION, MEM_COMMIT, PAGE_EXECUTE_READWRITE,
    PAGE_GUARD, PAGE_NOACCESS, PAGE_READWRITE, VirtualProtect, VirtualQuery,
};
use windows_sys::Win32::System::ProcessStatus::{EnumProcessModules, GetModuleBaseNameA};
use windows_sys::Win32::System::Threading::{CreateThread, GetCurrentProcess, Sleep};

const A2DLIB: &[u8] = b"A2dLib-2.20A.dll\0";
const ADD_EXPORT: &[u8] =
    b"?Add@CStringManager@NA2dLib@@QAEXPBDPBXI@Z\0";
const LSR_EXPORT: &[u8] = b"?LoadStringRes@CW32StringManager@NA2dLib@@UAE_NIAAV?$basic_string@GV?$char_traits@G@_STL@@V?$allocator@G@2@@_STL@@@Z\0";
const ADDSTR_EXPORT: &[u8] = b"?AddStringRes@CW32StringManager@NA2dLib@@MAE_NPBDPBXI@Z\0";
const STRING_MGR_EXPORT: &[u8] =
    b"?g_pStringMgr@NA2dLib@@3PAVCStringManager@1@A\0";

static REAL_ADD: AtomicUsize = AtomicUsize::new(0);
static REAL_ADDSTR: AtomicUsize = AtomicUsize::new(0);
static REAL_LSR: AtomicUsize = AtomicUsize::new(0);
static REAL_FOPEN_71: AtomicUsize = AtomicUsize::new(0);
static REAL_FOPEN_70: AtomicUsize = AtomicUsize::new(0);
static REAL_FOPEN_CRT: AtomicUsize = AtomicUsize::new(0);
static REAL_CREATE_A: AtomicUsize = AtomicUsize::new(0);
static REAL_CREATE_W: AtomicUsize = AtomicUsize::new(0);
static REAL_FIND_FIRST: AtomicUsize = AtomicUsize::new(0);
static REAL_GET_ATTR: AtomicUsize = AtomicUsize::new(0);
static RESOLVE_REAL: AtomicUsize = AtomicUsize::new(0);

static MGR: AtomicPtr<c_void> = AtomicPtr::new(ptr::null_mut());
static MGR_CAPTURED: AtomicBool = AtomicBool::new(false);
static VT_DONE: AtomicBool = AtomicBool::new(false);
static LSR_VT_DONE: AtomicBool = AtomicBool::new(false);
static ADDSTR_VT_DONE: AtomicBool = AtomicBool::new(false);
static RESOLVE_HOOKED: AtomicBool = AtomicBool::new(false);
static HOOK_STARTED: AtomicBool = AtomicBool::new(false);
static ADD_IAT_DONE: AtomicBool = AtomicBool::new(false);
static ADD_MISS_LOGGED: AtomicBool = AtomicBool::new(false);
static RESOLVE_MISS_LOGGED: AtomicBool = AtomicBool::new(false);
static FIRED: AtomicBool = AtomicBool::new(false);
static LSR_COUNT: AtomicU32 = AtomicU32::new(0);
static RESOLVE_COUNT: AtomicU32 = AtomicU32::new(0);

static PACK: OnceLock<Pack> = OnceLock::new();
static RESOLVE_LOG: OnceLock<Mutex<Option<File>>> = OnceLock::new();
static LSR_LOG: OnceLock<Mutex<Option<File>>> = OnceLock::new();
static FONT_LOG: OnceLock<Mutex<Option<File>>> = OnceLock::new();
static FONT_DIR: OnceLock<Option<String>> = OnceLock::new();
static GAP_SET: OnceLock<Mutex<HashSet<u32>>> = OnceLock::new();

struct Pack {
    locale: String,
    dir: String,
    edits: HashMap<u32, Box<[u16]>>,
}

type AddFn = unsafe extern "thiscall" fn(*mut c_void, *const c_char, *const c_void, u32);
type AddStrFn = unsafe extern "thiscall" fn(*mut c_void, *const c_char, *const c_void, u32) -> bool;
type LsrFn = unsafe extern "thiscall" fn(*mut c_void, u32, *mut c_void) -> bool;
type ResolveFn = unsafe extern "thiscall" fn(*mut c_void, i32, *mut c_void) -> i32;

#[no_mangle]
pub extern "system" fn DllMain(hinst: HANDLE, reason: u32, _reserved: *mut c_void) -> BOOL {
    if reason == 1 {
        unsafe {
            DisableThreadLibraryCalls(hinst as HMODULE);
            let th = CreateThread(
                ptr::null(),
                0,
                Some(init_thread),
                ptr::null_mut(),
                0,
                ptr::null_mut(),
            );
            if th != 0 {
                CloseHandle(th);
            }
        }
    }
    1
}

unsafe extern "system" fn init_thread(_: *mut c_void) -> u32 {
    Sleep(250);
    install_hook();
    0
}

unsafe fn install_hook() {
    if HOOK_STARTED.swap(true, Ordering::AcqRel) {
        return;
    }
    // Load the pack first: font_dir() falls back to the selected pack's
    // locale when no launcher set PR2_FONT_DIR.
    load_edit_file();
    install_font_log_hooks();
    log_line(&format!(
        "[text] pack '{}' from {}: {} overrides",
        pack_locale(),
        pack_dir_name(),
        pack_count()
    ));

    patch_add_iat();
    install_resolve_hook();
    start_hook_retry();
}

unsafe fn patch_add_iat() -> usize {
    if ADD_IAT_DONE.load(Ordering::Acquire) {
        return 0;
    }
    let detour = my_add as *const () as usize;
    let mut patched = 0usize;
    let main = GetModuleHandleA(ptr::null());
    if patch_iat_in(main, A2DLIB, ADD_EXPORT, detour, &REAL_ADD) {
        patched += 1;
    }
    for m in enum_modules() {
        if m == main {
            continue;
        }
        let name = module_name(m);
        if name.eq_ignore_ascii_case("A2dLib-2.20A.dll") {
            continue;
        }
        if patch_iat_in(m, A2DLIB, ADD_EXPORT, detour, &REAL_ADD) {
            log_line(&format!("[text] Add IAT patched in {}", name));
            patched += 1;
        }
    }
    if patched > 0 {
        ADD_IAT_DONE.store(true, Ordering::Release);
        log_line("[text] hook installed (CStringManager::Add -> MyAdd)");
    } else if !ADD_MISS_LOGGED.swap(true, Ordering::AcqRel) {
        log_line("[text] FAILED: Add not found in any module IAT (will retry)");
    }
    patched
}

unsafe fn start_hook_retry() {
    let th = CreateThread(
        ptr::null(),
        0,
        Some(hook_retry_thread),
        ptr::null_mut(),
        0,
        ptr::null_mut(),
    );
    if th != 0 {
        CloseHandle(th);
    }
}

unsafe extern "system" fn hook_retry_thread(_: *mut c_void) -> u32 {
    // The proxy may load this DLL before the import loader has finished.
    // Wait for A2dLib and retry the two hooks that need its module base.
    for _ in 0..120 {
        if GetModuleHandleA(A2DLIB.as_ptr()) != 0 {
            if !ADD_IAT_DONE.load(Ordering::Acquire) {
                patch_add_iat();
            }
            install_resolve_hook();
            if ADD_IAT_DONE.load(Ordering::Acquire)
                && RESOLVE_HOOKED.load(Ordering::Acquire)
            {
                return 0;
            }
        }
        Sleep(250);
    }
    log_line("[text] retry window ended; hook may be incomplete");
    0
}

unsafe extern "thiscall" fn my_add(
    this: *mut c_void,
    name: *const c_char,
    data: *const c_void,
    len: u32,
) {
    if !MGR_CAPTURED.load(Ordering::Acquire) {
        MGR.store(this, Ordering::Release);
        MGR_CAPTURED.store(true, Ordering::Release);
    }
    let real = REAL_ADD.load(Ordering::Acquire);
    if real == 0 {
        return;
    }
    let (payload, payload_len) = prepare_overlay(data, len);
    let real: AddFn = std::mem::transmute(real);
    real(
        overlay_manager(this),
        name,
        payload,
        payload_len,
    );
}

unsafe extern "thiscall" fn my_add_str(
    this: *mut c_void,
    name: *const c_char,
    data: *const c_void,
    len: u32,
) -> bool {
    if !MGR_CAPTURED.load(Ordering::Acquire) {
        MGR.store(this, Ordering::Release);
        MGR_CAPTURED.store(true, Ordering::Release);
    }
    let real = REAL_ADDSTR.load(Ordering::Acquire);
    if real == 0 {
        return false;
    }
    let (payload, payload_len) = prepare_overlay(data, len);
    let real: AddStrFn = std::mem::transmute(real);
    real(
        overlay_manager(this),
        name,
        payload,
        payload_len,
    )
}

unsafe fn overlay_manager(this: *mut c_void) -> *mut c_void {
    let captured = MGR.load(Ordering::Acquire);
    if captured.is_null() {
        this
    } else {
        captured
    }
}

unsafe fn prepare_overlay(
    data: *const c_void,
    len: u32,
) -> (*const c_void, u32) {
    if !VT_DONE.swap(true, Ordering::AcqRel) {
        install_vtable_hooks();
    }
    if !data.is_null() && len >= 4 {
        if let Some((new_data, new_len)) = replace_table(data as *const u8, len as usize) {
            if !FIRED.swap(true, Ordering::AcqRel) {
                log_line("[text] pack overlay applied to table");
            }
            return (new_data as *const c_void, new_len);
        }
    }
    (data, len)
}

unsafe fn install_vtable_hooks() {
    let h = GetModuleHandleA(A2DLIB.as_ptr());
    if h == 0 {
        return;
    }
    let target_lsr = GetProcAddress(h, LSR_EXPORT.as_ptr());
    let target_addstr = GetProcAddress(h, ADDSTR_EXPORT.as_ptr());
    if let Some(f) = target_lsr {
        hook_vtable_slot(
            h,
            f as usize,
            my_lsr as *const () as usize,
            &REAL_LSR,
            &LSR_VT_DONE,
            "LSR",
        );
    } else {
        log_line("[text] LSR: export not found");
    }
    if let Some(f) = target_addstr {
        hook_vtable_slot(
            h,
            f as usize,
            my_add_str as *const () as usize,
            &REAL_ADDSTR,
            &ADDSTR_VT_DONE,
            "AddStringRes",
        );
    } else {
        log_line("[text] AddStringRes: export not found");
    }
}

unsafe fn hook_vtable_slot(
    h: HMODULE,
    target: usize,
    detour: usize,
    original: &AtomicUsize,
    done: &AtomicBool,
    label: &str,
) {
    if done.load(Ordering::Acquire) {
        return;
    }
    let mut candidates: Vec<*const usize> = Vec::with_capacity(2);
    let mgr = MGR.load(Ordering::Acquire);
    if !mgr.is_null() {
        candidates.push(*(mgr as *const *const usize));
    }
    let gp = string_mgr_global(h);
    let pm = gp;
    if !pm.is_null() && pm != mgr {
        candidates.push(*(pm as *const *const usize));
    }

    for (ci, vt) in candidates.iter().enumerate() {
        if vt.is_null() || !readable(*vt as *const c_void, 512 * std::mem::size_of::<usize>()) {
            continue;
        }
        for i in 0..512 {
            let slot = (*vt).add(i) as *mut usize;
            let old = *slot;
            if old != target {
                continue;
            }
            let mut protect = 0u32;
            if VirtualProtect(
                slot as *const c_void,
                std::mem::size_of::<usize>(),
                PAGE_READWRITE,
                &mut protect,
            ) != 0
            {
                *slot = detour;
                VirtualProtect(
                    slot as *const c_void,
                    std::mem::size_of::<usize>(),
                    protect,
                    &mut protect,
                );
                original.store(old, Ordering::Release);
                done.store(true, Ordering::Release);
                log_line(&format!(
                    "[text] {} vtable hooked at slot {} (vt#{})",
                    label, i, ci
                ));
            }
            return;
        }
    }
    log_line(&format!(
        "[text] {}: 0x{:08X} not found in {} vtable(s)",
        label,
        target,
        candidates.len()
    ));
}

unsafe extern "thiscall" fn my_lsr(this: *mut c_void, hash: u32, out: *mut c_void) -> bool {
    let orig = REAL_LSR.load(Ordering::Acquire);
    let mut ret = false;
    if orig != 0 {
        let f: LsrFn = std::mem::transmute(orig);
        ret = f(this, hash, out);
    }
    if let Some(zh) = find_override(hash) {
        let header = wstr_header(out);
        let cap = if header.0 >= 0x10000 && header.2 > header.0 {
            (header.2 - header.0) / 2
        } else {
            0
        };
        let n = zh.len().min(4096);
        let wrote = write_wstr_inplace(out, &zh[..n]);
        let status = if wrote && n as u32 <= cap {
            "wrote"
        } else if (n as u32) > cap {
            "SKIP(too-long)"
        } else {
            "skip"
        };
        lsr_log(&format!(
            "[LSR*] 0x{:08X} raw={:08X},{:08X},{:08X} zhlen={} cap={} {}\n",
            hash, header.0, header.1, header.2, n, cap, status
        ));
        log_lsr_call(hash, 1, None);
    } else {
        let text = read_wstr_text(out);
        log_lsr_call(hash, 0, if text.is_empty() { None } else { Some(&text) });
    }
    ret
}

const RESOLVE_THUNK_RVA: usize = 0x1DC5;
const RESOLVE_REAL_RVA: usize = 0x25C70;
const STRING_MGR_FALLBACK_RVA: usize = 0x142084;

struct ResolveProfile {
    thunk_rva: usize,
    real_rva: usize,
}

// Only versions whose thunk actually resolves to the expected target are
// accepted. Unknown builds stop with a log line instead of patching blindly.
const RESOLVE_PROFILES: &[ResolveProfile] = &[ResolveProfile {
    thunk_rva: RESOLVE_THUNK_RVA,
    real_rva: RESOLVE_REAL_RVA,
}];

unsafe fn resolve_profile(h: HMODULE) -> Option<&'static ResolveProfile> {
    for p in RESOLVE_PROFILES {
        let thunk = (h as *mut u8).wrapping_add(p.thunk_rva);
        if !readable(thunk as *const c_void, 5) {
            continue;
        }
        if *thunk != 0xE9 {
            continue;
        }
        let rel = ptr::read_unaligned(thunk.add(1) as *const i32);
        let target = (thunk as isize + 5 + rel as isize) as usize;
        if target == (h as usize).wrapping_add(p.real_rva) {
            return Some(p);
        }
    }
    None
}

unsafe fn string_mgr_global(h: HMODULE) -> *mut c_void {
    // A2dLib exports the singleton pointer; prefer it over a fixed RVA.
    if let Some(f) = GetProcAddress(h, STRING_MGR_EXPORT.as_ptr()) {
        let p = f as *const *mut c_void;
        if readable(p as *const c_void, std::mem::size_of::<*mut c_void>()) {
            return *p;
        }
    }
    let p = (h as *const u8).wrapping_add(STRING_MGR_FALLBACK_RVA) as *const *mut c_void;
    if readable(p as *const c_void, std::mem::size_of::<*mut c_void>()) {
        return *p;
    }
    ptr::null_mut()
}

unsafe fn install_resolve_hook() {
    if RESOLVE_HOOKED.load(Ordering::Acquire) {
        return;
    }
    let h = GetModuleHandleA(A2DLIB.as_ptr());
    if h == 0 {
        if !RESOLVE_MISS_LOGGED.swap(true, Ordering::AcqRel) {
            log_line("[text] ResolveHook: A2dLib-2.20A.dll not loaded yet (will retry)");
        }
        return;
    }
    let Some(profile) = resolve_profile(h) else {
        if !RESOLVE_MISS_LOGGED.swap(true, Ordering::AcqRel) {
            log_line("[text] ResolveHook: no known profile for this A2dLib build");
        }
        return;
    };
    let real = (h as usize).wrapping_add(profile.real_rva);
    let thunk = (h as *mut u8).wrapping_add(profile.thunk_rva);
    let detour = my_resolve as *const () as usize;
    let mut old = 0u32;
    if VirtualProtect(
        thunk as *const c_void,
        5,
        PAGE_EXECUTE_READWRITE,
        &mut old,
    ) != 0
    {
        let rel = detour as isize - (thunk as isize + 5);
        *thunk = 0xE9;
        ptr::write_unaligned(thunk.add(1) as *mut i32, rel as i32);
        VirtualProtect(thunk as *const c_void, 5, old, &mut old);
        RESOLVE_REAL.store(real, Ordering::Release);
        RESOLVE_HOOKED.store(true, Ordering::Release);
        log_line(&format!(
            "[text] ResolveHook: CScreenStrings::ResolveByHash patched (thunk 0x{:X} -> MyResolve)",
            profile.thunk_rva
        ));
    } else {
        log_line("[text] ResolveHook: VirtualProtect failed");
    }
}

unsafe extern "thiscall" fn my_resolve(this: *mut c_void, key: i32, out: *mut c_void) -> bool {
    let real = RESOLVE_REAL.load(Ordering::Acquire);
    let mut ret = false;
    if real != 0 {
        let f: ResolveFn = std::mem::transmute(real);
        ret = f(this, key, out) != 0;
    }
    let n = RESOLVE_COUNT.fetch_add(1, Ordering::Relaxed);
    log_resolve_full(key as u32, out, ret);
    if n >= 8000 {
        return ret;
    }
    if let Some(zh) = find_override(key as u32) {
        let n = zh.len().min(4096);
        write_wstr_inplace(out, &zh[..n]);
    } else if ret {
        log_resolve_gap(key as u32, out);
    }
    ret
}

unsafe fn log_resolve_full(hash: u32, out: *mut c_void, ret: bool) {
    let text = read_wstr_text(out);
    let h = wstr_header(out);
    let line = format!(
        "[R] 0x{:08X} ret={} raw={:08X},{:08X},{:08X} txt={}\n",
        hash,
        if ret { 1 } else { 0 },
        h.0,
        h.1,
        h.2,
        text
    );
    resolve_log(&line);
}

unsafe fn log_resolve_gap(hash: u32, out: *mut c_void) {
    let set = GAP_SET.get_or_init(|| Mutex::new(HashSet::new()));
    let mut guard = set.lock().unwrap_or_else(|e| e.into_inner());
    if !guard.insert(hash) {
        return;
    }
    let text = read_wstr_text(out);
    let line = format!("[RGAP] 0x{:08X}  {}\n", hash, text);
    drop(guard);
    resolve_log(&line);
}

fn resolve_log(line: &str) {
    let m = RESOLVE_LOG.get_or_init(|| Mutex::new(None));
    let mut guard = m.lock().unwrap_or_else(|e| e.into_inner());
    if guard.is_none() {
        let path = log_dir(&exe_dir()).join("resolve.log");
        *guard = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(path)
            .ok();
        if let Some(f) = guard.as_mut() {
            let _ = writeln!(
                f,
                "=== CScreenStrings::ResolveByHash (menu/UI) gaps ==="
            );
        }
    }
    if let Some(f) = guard.as_mut() {
        let _ = f.write_all(line.as_bytes());
        let _ = f.flush();
    }
}

unsafe fn log_lsr_call(hash: u32, found: i32, text: Option<&String>) {
    if LSR_COUNT.load(Ordering::Relaxed) >= 5000 {
        return;
    }
    LSR_COUNT.fetch_add(1, Ordering::Relaxed);
    let mut line = format!("[LSR] 0x{:08X} f={} ", hash, found);
    if let Some(t) = text {
        for c in t.chars().take(6) {
            if (c as u32) < 0x80 {
                line.push(c);
            } else {
                line.push('?');
            }
        }
    }
    line.push('\n');
    lsr_log(&line);
}

fn lsr_log(line: &str) {
    let m = LSR_LOG.get_or_init(|| Mutex::new(None));
    let mut guard = m.lock().unwrap_or_else(|e| e.into_inner());
    if guard.is_none() {
        let path = log_dir(&exe_dir()).join("vtable.log");
        *guard = OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .ok();
    }
    if let Some(f) = guard.as_mut() {
        let _ = f.write_all(line.as_bytes());
        if line.starts_with("[LSR*]") {
            let _ = f.flush();
        }
    }
}

fn log_line(msg: &str) {
    let path = log_dir(&exe_dir()).join("runtime.log");
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(f, "{msg}");
    }
}

unsafe fn wstr_header(obj: *mut c_void) -> (u32, u32, u32) {
    if obj.is_null() || !readable(obj as *const c_void, 12) {
        return (0, 0, 0);
    }
    (
        read_u32(obj as *const u8),
        read_u32((obj as *const u8).add(4)),
        read_u32((obj as *const u8).add(8)),
    )
}

unsafe fn read_wstr_text(obj: *mut c_void) -> String {
    let mut buf = [0u16; 600];
    let n = read_wstr(obj, &mut buf);
    String::from_utf16_lossy(&buf[..n])
}

unsafe fn read_wstr(obj: *mut c_void, buf: &mut [u16]) -> usize {
    buf[0] = 0;
    if obj.is_null() || buf.len() < 2 || !readable(obj as *const c_void, 20) {
        return 0;
    }
    let w0 = read_u32(obj as *const u8);
    let w1 = read_u32((obj as *const u8).add(4));
    let _w2 = read_u32((obj as *const u8).add(8));

    if w0 > 0x10000
        && w1 >= w0
        && (w1 - w0) < 0x8000
        && ((w1 - w0) as usize) <= (buf.len() - 1) * 2
        && readable(w0 as *const c_void, (w1 - w0) as usize)
    {
        let n = ((w1 - w0) / 2) as usize;
        ptr::copy_nonoverlapping(w0 as *const u16, buf.as_mut_ptr(), n);
        buf[n] = 0;
        return n;
    }

    let sz = read_u32((obj as *const u8).add(16));
    if sz <= 15 && readable(obj as *const c_void, 32) {
        let n = (sz as usize).min(buf.len() - 1);
        ptr::copy_nonoverlapping(obj as *const u16, buf.as_mut_ptr(), n);
        buf[n] = 0;
        return n;
    }

    if w0 > 0x10000 && w0 < 0x80000000 {
        let mut n = 0usize;
        for i in 0..buf.len() - 1 {
            if !readable((w0 as *const u8).add(i * 2) as *const c_void, 2) {
                break;
            }
            let c = read_u16((w0 as *const u8).add(i * 2));
            if c == 0 {
                break;
            }
            buf[i] = c;
            n += 1;
        }
        buf[n] = 0;
        return n;
    }
    0
}

unsafe fn write_wstr_inplace(obj: *mut c_void, zh: &[u16]) -> bool {
    if obj.is_null() || !readable(obj as *const c_void, 12) {
        return false;
    }
    let w0 = read_u32(obj as *const u8);
    let w2 = read_u32((obj as *const u8).add(8));
    if w0 < 0x10000 || w2 <= w0 {
        return false;
    }
    let cap = ((w2 - w0) / 2) as usize;
    if zh.len() > cap {
        return false;
    }
    if !readable(w0 as *const c_void, zh.len() * 2) {
        return false;
    }
    ptr::copy_nonoverlapping(zh.as_ptr(), w0 as *mut u16, zh.len());
    write_u32(
        (obj as *mut u8).add(4),
        w0.wrapping_add((zh.len() as u32) * 2),
    );
    true
}

unsafe fn replace_table(d: *const u8, len: usize) -> Option<(*mut u8, u32)> {
    if !table_valid(d, len) {
        return None;
    }
    let cnt = read_u32(d) as usize;
    let pool_start_word = 2 + 8 * cnt;
    let mut out_words = pool_start_word;
    let mut replaced = 0usize;
    for i in 0..cnt {
        let e = 4 + 16 * i;
        let hash = read_u32(d.add(e));
        let ln = read_u32(d.add(e + 12)) as usize;
        let srclen = match find_override(hash) {
            Some(zh) => {
                replaced += 1;
                zh.len() * 2
            }
            None => ln,
        };
        out_words += srclen / 2;
    }
    if replaced == 0 {
        return None;
    }
    let bytes = out_words.checked_mul(2)?;
    let out = HeapAlloc(GetProcessHeap(), 0, bytes) as *mut u8;
    if out.is_null() {
        return None;
    }
    write_u32(out, cnt as u32);
    let mut pp = out.add(pool_start_word * 2);
    let mut cur_word = pool_start_word;
    for i in 0..cnt {
        let e = 4 + 16 * i;
        let hash = read_u32(d.add(e));
        let flags = read_u32(d.add(e + 8));
        let off = read_u32(d.add(e + 4)) as usize;
        let ln = read_u32(d.add(e + 12)) as usize;
        let mut src = d.add(4 + off);
        let mut srclen = ln;
        if let Some(zh) = find_override(hash) {
            src = zh.as_ptr() as *const u8;
            srclen = zh.len() * 2;
        }
        let off_byte = (2 * cur_word).wrapping_sub(4) as u32;
        write_u32(out.add(e), hash);
        write_u32(out.add(e + 4), off_byte);
        write_u32(out.add(e + 8), flags);
        write_u32(out.add(e + 12), srclen as u32);
        if srclen > 0 {
            ptr::copy_nonoverlapping(src, pp, srclen);
            pp = pp.add(srclen);
        }
        cur_word += srclen / 2;
    }
    Some((out, (out_words * 2) as u32))
}

unsafe fn table_valid(d: *const u8, len: usize) -> bool {
    if len < 4 || !readable(d as *const c_void, len) {
        return false;
    }
        let cnt = read_u32(d) as usize;
    if cnt == 0 || cnt > 200000 {
        return false;
    }
    let total_words = len / 2;
    let pool_start_word = 2 + 8 * cnt;
    if total_words < pool_start_word {
        return false;
    }
    for i in 0..cnt {
        let e = 4 + 16 * i;
        if e + 16 > len {
            return false;
        }
        let off = read_u32(d.add(e + 4)) as usize;
        let ln = read_u32(d.add(e + 12)) as usize;
        if 4 + off + ln > len {
            return false;
        }
    }
    true
}

fn pack() -> Option<&'static Pack> {
    PACK.get()
}

fn find_override(hash: u32) -> Option<&'static [u16]> {
    pack()
        .and_then(|p| p.edits.get(&hash).map(|b| &**b))
        .filter(|v| !v.is_empty())
}

fn pack_count() -> usize {
    pack().map(|p| p.edits.len()).unwrap_or(0)
}

fn pack_locale() -> String {
    pack().map(|p| p.locale.clone()).unwrap_or_else(|| "zh".into())
}

fn pack_dir_name() -> String {
    pack().map(|p| p.dir.clone()).unwrap_or_default()
}

unsafe fn load_edit_file() {
    if PACK.get().is_some() {
        return;
    }
    let root = exe_dir();
    let mut locale = "zh".to_string();
    let mut env_lang = false;
    if let Ok(env) = std::env::var("PR2_PACK_LANG") {
        let trimmed = env.trim();
        if valid_lang_code(trimmed) {
            locale = trimmed.to_string();
            env_lang = true;
        }
    }
    if !env_lang {
        if let Some(code) = read_locale_language(&root) {
            if valid_lang_code(&code) {
                locale = code;
            }
        }
    }

    let dir = pack_dir(&root);
    let mut edits = HashMap::new();
    load_override_file(&pack_path(&root, &locale), &mut edits);
    load_override_file(&override_path(&root, &locale), &mut edits);
    let _ = PACK.set(Pack {
        locale,
        dir: dir.to_string_lossy().into_owned(),
        edits,
    });
}

fn load_override_file(path: &Path, edits: &mut HashMap<u32, Box<[u16]>>) {
    let data = match std::fs::read(path) {
        Ok(v) => v,
        Err(_) => return,
    };
    if data.is_empty() || data.len() > 16 * 1024 * 1024 {
        return;
    }
    let data = data.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(&data);
    let text = String::from_utf8_lossy(data);
    for line in text.split('\n') {
        let line = line.trim_end_matches('\r');
        let s = line.trim_start_matches([' ', '\t']);
        if s.is_empty() || s.starts_with('#') || s.starts_with(';') {
            continue;
        }
        let (hash, value) = match parse_pack_line(s) {
            Some(v) => v,
            None => continue,
        };
        if edits.len() >= 16384 && !edits.contains_key(&hash) {
            continue;
        }
        let units: Vec<u16> = value.encode_utf16().take(2047).collect();
        edits.insert(hash, units.into_boxed_slice());
    }
}

fn parse_pack_line(s: &str) -> Option<(u32, &str)> {
    let s = s.trim_start_matches([' ', '\t']);
    let hex = s
        .strip_prefix("0x")
        .or_else(|| s.strip_prefix("0X"))
        .unwrap_or(s);
    let end = hex
        .find(|c: char| !c.is_ascii_hexdigit())
        .unwrap_or(hex.len());
    if end == 0 {
        return None;
    }
    let hash = u32::from_str_radix(&hex[..end], 16).ok()?;
    let rest = hex[end..].trim_start_matches(' ');
    let value = rest
        .strip_prefix('=')
        .or_else(|| rest.strip_prefix('\t'))?;
    Some((hash, value.trim_start_matches([' ', '\t'])))
}

unsafe fn readable(p: *const c_void, len: usize) -> bool {
    if p.is_null() {
        return false;
    }
    if len == 0 {
        return true;
    }
    let mut addr = p as usize;
    let end = match addr.checked_add(len) {
        Some(v) => v,
        None => return false,
    };
    while addr < end {
        let mut mbi = std::mem::zeroed::<MEMORY_BASIC_INFORMATION>();
        let got = VirtualQuery(
            addr as *const c_void,
            &mut mbi,
            std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
        );
        if got == 0 {
            return false;
        }
        if mbi.State != MEM_COMMIT {
            return false;
        }
        if mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD) != 0 {
            return false;
        }
        let region_end = (mbi.BaseAddress as usize).saturating_add(mbi.RegionSize);
        if region_end <= addr {
            return false;
        }
        if region_end >= end {
            return true;
        }
        addr = region_end;
    }
    true
}

unsafe fn read_u16(p: *const u8) -> u16 {
    ptr::read_unaligned(p as *const u16)
}

unsafe fn read_u32(p: *const u8) -> u32 {
    ptr::read_unaligned(p as *const u32)
}

unsafe fn write_u32(p: *mut u8, v: u32) {
    ptr::write_unaligned(p as *mut u32, v);
}

fn module_name(m: HMODULE) -> String {
    let mut buf = [0u8; 260];
    let n = unsafe { GetModuleBaseNameA(GetCurrentProcess(), m, buf.as_mut_ptr(), 260) };
    if n == 0 {
        return String::new();
    }
    String::from_utf8_lossy(&buf[..n as usize]).into_owned()
}

fn enum_modules() -> Vec<HMODULE> {
    let mut mods = [0 as HMODULE; 256];
    let mut cb = 0u32;
    if unsafe {
        EnumProcessModules(
            GetCurrentProcess(),
            mods.as_mut_ptr(),
            (mods.len() * std::mem::size_of::<HMODULE>()) as u32,
            &mut cb,
        )
    } == 0
    {
        return Vec::new();
    }
    let n = (cb as usize / std::mem::size_of::<HMODULE>()).min(mods.len());
    mods[..n].to_vec()
}

unsafe fn patch_iat_in(
    hmod: HMODULE,
    dll_name: &[u8],
    func_name: &[u8],
    detour: usize,
    original: &AtomicUsize,
) -> bool {
    if hmod == 0 {
        return false;
    }
    let base = hmod as *const u8;
    if read_u16(base) != 0x5A4D {
        return false;
    }
    let nt = base.add(read_u32(base.add(0x3C)) as usize);
    if read_u32(nt) != 0x0000_4550 {
        return false;
    }
    let opt = nt.add(24);
    let magic = read_u16(opt);
    let dd = if magic == 0x10B { opt.add(96) } else { opt.add(112) };
    let imp_rva = read_u32(dd.add(8)) as usize;
    if imp_rva == 0 {
        return false;
    }
    let mut imp = base.add(imp_rva);
    let mut found = false;
    loop {
        let name_rva = read_u32(imp.add(12)) as usize;
        if name_rva == 0 {
            break;
        }
        let mod_name = base.add(name_rva);
        if cstr_eq_ignore_ascii_case(mod_name, dll_name) {
            let oft = read_u32(imp) as usize;
            let ft = read_u32(imp.add(16)) as usize;
            if ft != 0 {
                let lookup = if oft != 0 { oft } else { ft };
                let mut oft_p = base.add(lookup);
                let mut ft_p = base.add(ft) as *mut usize;
                while read_u32(oft_p) != 0 {
                    let oft_val = read_u32(oft_p);
                    if oft_val & 0x8000_0000 == 0 {
                        let ibn = base.add(oft_val as usize);
                        if cstr_eq(ibn.add(2), func_name) {
                            if original.load(Ordering::Acquire) == 0 {
                                original.store(*ft_p, Ordering::Release);
                            }
                            let mut protect = 0u32;
                            if VirtualProtect(
                                ft_p as *const c_void,
                                std::mem::size_of::<usize>(),
                                PAGE_READWRITE,
                                &mut protect,
                            ) != 0
                            {
                                *ft_p = detour;
                                VirtualProtect(
                                    ft_p as *const c_void,
                                    std::mem::size_of::<usize>(),
                                    protect,
                                    &mut protect,
                                );
                                found = true;
                            }
                        }
                    }
                    oft_p = oft_p.add(4);
                    ft_p = ft_p.add(1);
                }
            }
        }
        imp = imp.add(20);
    }
    found
}

fn cstr_eq(p: *const u8, s: &[u8]) -> bool {
    let s = s.strip_suffix(&[0]).unwrap_or(s);
    let mut i = 0;
    loop {
        let a = unsafe { *p.add(i) };
        let b = if i < s.len() { s[i] } else { 0 };
        if a != b {
            return false;
        }
        if a == 0 {
            return true;
        }
        i += 1;
    }
}

fn cstr_eq_ignore_ascii_case(p: *const u8, s: &[u8]) -> bool {
    let s = s.strip_suffix(&[0]).unwrap_or(s);
    let mut i = 0;
    loop {
        let a = unsafe { *p.add(i) };
        let b = if i < s.len() { s[i] } else { 0 };
        if a.to_ascii_lowercase() != b.to_ascii_lowercase() {
            return false;
        }
        if a == 0 {
            return true;
        }
        i += 1;
    }
}

// ---- font path redirection / logging ----

type FopenFn = unsafe extern "C" fn(*const u8, *const u8) -> *mut c_void;
type CreateFileAFn =
    unsafe extern "system" fn(*const u8, u32, u32, *const c_void, u32, u32, HANDLE) -> HANDLE;
type CreateFileWFn =
    unsafe extern "system" fn(*const u16, u32, u32, *const c_void, u32, u32, HANDLE) -> HANDLE;
type FindFirstFileAFn = unsafe extern "system" fn(*const u8, *mut WIN32_FIND_DATAA) -> HANDLE;
type GetFileAttributesExAFn =
    unsafe extern "system" fn(*const u8, GET_FILEEX_INFO_LEVELS, *mut c_void) -> BOOL;

unsafe fn fopen_impl(
    path: *const u8,
    mode: *const u8,
    real: &AtomicUsize,
) -> *mut c_void {
    let real = real.load(Ordering::Acquire);
    if real == 0 {
        return ptr::null_mut();
    }
    let path_s = ansi_str(path);
    let redirected = redirect_font_path(&path_s);
    let use_s = redirected.as_deref().unwrap_or(&path_s);
    font_log_path(use_s);
    let f: FopenFn = std::mem::transmute(real);
    let c_path = to_cstr(use_s);
    f(c_path.as_ptr(), mode)
}

unsafe extern "C" fn my_fopen_71(path: *const u8, mode: *const u8) -> *mut c_void {
    fopen_impl(path, mode, &REAL_FOPEN_71)
}

unsafe extern "C" fn my_fopen_70(path: *const u8, mode: *const u8) -> *mut c_void {
    fopen_impl(path, mode, &REAL_FOPEN_70)
}

unsafe extern "C" fn my_fopen_crt(path: *const u8, mode: *const u8) -> *mut c_void {
    fopen_impl(path, mode, &REAL_FOPEN_CRT)
}

unsafe extern "system" fn my_create_file_a(
    name: *const u8,
    access: u32,
    share: u32,
    sa: *const c_void,
    create: u32,
    flags: u32,
    tmpl: HANDLE,
) -> HANDLE {
    let real = REAL_CREATE_A.load(Ordering::Acquire);
    if real == 0 {
        return 0;
    }
    let name_s = ansi_str(name);
    let redirected = redirect_font_path(&name_s);
    let use_s = redirected.as_deref().unwrap_or(&name_s);
    font_log_path(use_s);
    let c_name = to_cstr(use_s);
    let f: CreateFileAFn = std::mem::transmute(real);
    f(c_name.as_ptr(), access, share, sa, create, flags, tmpl)
}

unsafe extern "system" fn my_create_file_w(
    name: *const u16,
    access: u32,
    share: u32,
    sa: *const c_void,
    create: u32,
    flags: u32,
    tmpl: HANDLE,
) -> HANDLE {
    let real = REAL_CREATE_W.load(Ordering::Acquire);
    if real == 0 {
        return 0;
    }
    if name.is_null() {
        let f: CreateFileWFn = std::mem::transmute(real);
        return f(name, access, share, sa, create, flags, tmpl);
    }
    let mut units = Vec::new();
    for i in 0..1024 {
        let c = *name.add(i);
        if c == 0 {
            break;
        }
        units.push(c);
    }
    let name_s = std::ffi::OsString::from_wide(&units)
        .to_string_lossy()
        .into_owned();
    let redirected = redirect_font_path(&name_s);
    let use_s = redirected.as_deref().unwrap_or(&name_s);
    font_log_path(use_s);
    if redirected.is_some() {
        let w = pr2_common::wide(use_s);
        let f: CreateFileWFn = std::mem::transmute(real);
        f(w.as_ptr(), access, share, sa, create, flags, tmpl)
    } else {
        let f: CreateFileWFn = std::mem::transmute(real);
        f(name, access, share, sa, create, flags, tmpl)
    }
}

unsafe extern "system" fn my_find_first(
    name: *const u8,
    data: *mut WIN32_FIND_DATAA,
) -> HANDLE {
    let real = REAL_FIND_FIRST.load(Ordering::Acquire);
    if real == 0 {
        return 0;
    }
    let name_s = ansi_str(name);
    let redirected = redirect_font_path(&name_s);
    let use_s = redirected.as_deref().unwrap_or(&name_s);
    font_log_path(use_s);
    let c_name = to_cstr(use_s);
    let f: FindFirstFileAFn = std::mem::transmute(real);
    f(c_name.as_ptr(), data)
}

unsafe extern "system" fn my_get_attributes_ex(
    name: *const u8,
    level: GET_FILEEX_INFO_LEVELS,
    info: *mut c_void,
) -> BOOL {
    let real = REAL_GET_ATTR.load(Ordering::Acquire);
    if real == 0 {
        return 0;
    }
    let name_s = ansi_str(name);
    let redirected = redirect_font_path(&name_s);
    let use_s = redirected.as_deref().unwrap_or(&name_s);
    font_log_path(use_s);
    let c_name = to_cstr(use_s);
    let f: GetFileAttributesExAFn = std::mem::transmute(real);
    f(c_name.as_ptr(), level, info)
}

fn ansi_str(p: *const u8) -> String {
    if p.is_null() {
        return String::new();
    }
    let mut out = String::new();
    unsafe {
        for i in 0..1024 {
            let b = *p.add(i);
            if b == 0 {
                break;
            }
            out.push(b as char);
        }
    }
    out
}

fn to_cstr(s: &str) -> Vec<u8> {
    let mut v: Vec<u8> = s.bytes().collect();
    v.push(0);
    v
}

fn font_log_enabled() -> bool {
    std::env::var("PR2_FONT_LOG").is_ok() || std::env::var("PR2_FONT_LOG_ALL").is_ok()
}

fn font_log_all() -> bool {
    std::env::var("PR2_FONT_LOG_ALL").is_ok()
}

fn font_dir() -> Option<&'static str> {
    FONT_DIR
        .get_or_init(|| {
            let root = exe_dir();
            if let Ok(s) = std::env::var("PR2_FONT_DIR") {
                let s = s.trim().to_string();
                if !s.is_empty() && valid_lang_code(&s) {
                    return Some(font_rel_dir(&root, &s));
                }
            }
            // Steam natural launch has no launcher to set PR2_FONT_DIR.
            // Use the selected pack's font directory when it exists,
            // otherwise keep the original fonts.
            let lang = pack_locale();
            if fonts_dir(&root).join(&lang).is_dir() {
                Some(font_rel_dir(&root, &lang))
            } else {
                None
            }
        })
        .as_deref()
}

fn redirect_font_path(input: &str) -> Option<String> {
    let dir = font_dir()?;
    let lower = input.to_ascii_lowercase();
    let mut start = 0usize;
    let pos = loop {
        if start >= lower.len() {
            return None;
        }
        let rel = lower[start..].find("fonts")?;
        let p = start + rel;
        match input.as_bytes().get(p + 5) {
            Some(b'\\') | Some(b'/') => break p,
            _ => start = p + 5,
        }
    };
    let sep = input.as_bytes()[pos + 5] as char;
    let rest = &input[pos + 6..];
    let lowered_rest = rest.to_ascii_lowercase();
    if lower.contains("pr2localization\\fonts") || lower.contains("pr2localization/fonts") {
        return None;
    }
    let is_ttf = lowered_rest.ends_with(".ttf");
    if !is_ttf && !lowered_rest.contains("*.*") {
        return None;
    }
    Some(format!("{}{}{}{}", &input[..pos], dir, sep, rest))
}

fn font_log_path(path: &str) {
    if !font_log_enabled() {
        return;
    }
    if !font_log_all()
        && !path.contains("\\fonts")
        && !path.contains("/fonts")
        && !path.to_ascii_lowercase().contains(".ttf")
    {
        return;
    }
    let m = FONT_LOG.get_or_init(|| Mutex::new(None));
    let mut guard = m.lock().unwrap_or_else(|e| e.into_inner());
    if guard.is_none() {
        let p = log_dir(&exe_dir()).join("font-paths.log");
        *guard = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(p)
            .ok();
        if let Some(f) = guard.as_mut() {
            let _ = writeln!(f, "font path log (read-only hook)");
        }
    }
    if let Some(f) = guard.as_mut() {
        let _ = writeln!(f, "{path}");
    }
}

unsafe fn install_font_log_hooks() {
    let fd = font_dir();
    if !font_log_enabled() && fd.is_none() {
        return;
    }
    if font_log_enabled() {
        let m = FONT_LOG.get_or_init(|| Mutex::new(None));
        let mut guard = m.lock().unwrap_or_else(|e| e.into_inner());
        if guard.is_none() {
            let p = log_dir(&exe_dir()).join("font-paths.log");
            *guard = OpenOptions::new()
                .create(true)
                .truncate(true)
                .write(true)
                .open(p)
                .ok();
            if let Some(f) = guard.as_mut() {
                let _ = writeln!(f, "font path log (read-only hook)");
            }
        }
    }
    let mut f71 = 0usize;
    let mut f70 = 0usize;
    let mut fcrt = 0usize;
    for m in enum_modules() {
        let module = module_name(m);
        if module.eq_ignore_ascii_case("d3d8.dll") {
            continue;
        }
        if patch_iat_in(
            m,
            b"msvcr71.dll\0",
            b"fopen\0",
            my_fopen_71 as *const () as usize,
            &REAL_FOPEN_71,
        ) {
            f71 += 1;
        }
        if patch_iat_in(
            m,
            b"msvcr70.dll\0",
            b"fopen\0",
            my_fopen_70 as *const () as usize,
            &REAL_FOPEN_70,
        ) {
            f70 += 1;
        }
        if patch_iat_in(
            m,
            b"msvcrt.dll\0",
            b"fopen\0",
            my_fopen_crt as *const () as usize,
            &REAL_FOPEN_CRT,
        ) {
            fcrt += 1;
        }
        patch_iat_in(
            m,
            b"KERNEL32.dll\0",
            b"CreateFileA\0",
            my_create_file_a as *const () as usize,
            &REAL_CREATE_A,
        );
        patch_iat_in(
            m,
            b"KERNEL32.dll\0",
            b"CreateFileW\0",
            my_create_file_w as *const () as usize,
            &REAL_CREATE_W,
        );
        patch_iat_in(
            m,
            b"KERNEL32.dll\0",
            b"FindFirstFileA\0",
            my_find_first as *const () as usize,
            &REAL_FIND_FIRST,
        );
        patch_iat_in(
            m,
            b"KERNEL32.dll\0",
            b"GetFileAttributesExA\0",
            my_get_attributes_ex as *const () as usize,
            &REAL_GET_ATTR,
        );
    }
    if f71 + f70 + fcrt > 0 {
        log_line(&format!(
            "[text] font fopen hooks: msvcr71={} msvcr70={} msvcrt={}",
            f71, f70, fcrt
        ));
    }
}
