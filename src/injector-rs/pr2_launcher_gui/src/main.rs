#![windows_subsystem = "windows"]
// The GUI state is a single-threaded Win32 message-loop singleton; no
// reference to it escapes the thread that owns the window.
#![allow(static_mut_refs)]

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::ptr;

use pr2_common::{
    exe_dir, language_fonts_complete, read_locale_language, valid_lang_code,
    write_locale_language, RUNTIME_VERSION,
};
use windows_sys::Win32::Foundation::{
    CloseHandle, HINSTANCE, HWND, LPARAM, LRESULT, WPARAM,
};
use windows_sys::Win32::Globalization::GetUserDefaultUILanguage;
use windows_sys::Win32::Graphics::Gdi::{COLOR_BTNFACE, HBRUSH};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::{
    CreateProcessA, GetExitCodeProcess, WaitForSingleObject, CREATE_NO_WINDOW, PROCESS_INFORMATION,
    STARTUPINFOA,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetMessageW, LoadCursorW, MessageBoxW,
    PostQuitMessage, RegisterClassW, SendMessageW, SetWindowTextW, ShowWindow, TranslateMessage,
    BS_PUSHBUTTON, CB_ADDSTRING, CB_GETCURSEL, CB_RESETCONTENT, CB_SETCURSEL, CBN_SELCHANGE,
    CBS_DROPDOWNLIST, CW_USEDEFAULT, IDC_ARROW, IDYES, MB_ICONERROR, MB_ICONWARNING, MB_YESNO, MSG,
    SW_SHOW, WM_COMMAND, WM_CREATE, WM_DESTROY, WS_CAPTION, WS_CHILD, WS_MINIMIZEBOX,
    WS_OVERLAPPED, WS_SYSMENU, WS_TABSTOP, WS_VISIBLE, WS_VSCROLL, WNDCLASSW,
};

const ID_LANG: i32 = 1001;
const ID_LAUNCH: i32 = 1002;
const ID_VANILLA: i32 = 1003;
const ID_REFRESH: i32 = 1004;
const ID_STATUS: i32 = 1005;

const BUILTIN: &[(&str, &str)] = &[
    ("title", "Port Royale 2 Launcher"),
    ("label.language", "Language pack:"),
    ("button.launch", "Launch localized"),
    ("button.vanilla", "Launch original"),
    ("button.refresh", "Refresh"),
    ("status.count", "%d language pack(s)"),
    ("status.none", "No .txt in PR2Packs"),
    ("status.launched", "Localized game launched."),
    ("status.vanilla", "Original game launched."),
    ("error.no_launcher", "PR2Launcher.exe not found in this folder."),
    ("error.no_language", "No language pack selected."),
    ("error.launch_failed", "Failed to start PR2Launcher.exe."),
    ("error.exit_code", "Launcher exit code %lu; the game did not start."),
    ("error.font_missing", "fonts\\%s\\ has no TTF fonts."),
    (
        "error.pack_too_new",
        "Language pack needs a newer launcher (runtime v%d, current v%d).",
    ),
];

struct PackInfo {
    code: String,
    gui: String,
    min_runtime: u32,
}

struct GuiState {
    root: PathBuf,
    hwnd: HWND,
    combo: HWND,
    status: HWND,
    label: HWND,
    btn_launch: HWND,
    btn_vanilla: HWND,
    btn_refresh: HWND,
    codes: Vec<PackInfo>,
    strings: HashMap<String, String>,
    default_ui: String,
}

static mut STATE: Option<GuiState> = None;

fn state() -> &'static mut GuiState {
    unsafe { STATE.as_mut().expect("GUI state not initialized") }
}

fn main() {
    let root = exe_dir();
    let default_ui = ui_for_system();
    let strings = load_ui_strings(&root, &default_ui);
    unsafe {
        STATE = Some(GuiState {
            root,
            hwnd: 0,
            combo: 0,
            status: 0,
            label: 0,
            btn_launch: 0,
            btn_vanilla: 0,
            btn_refresh: 0,
            codes: Vec::new(),
            strings,
            default_ui,
        });
    }

    unsafe {
        let inst = GetModuleHandleW(ptr::null()) as HINSTANCE;
        let class_name = wide("PR2LauncherGUI");
        let mut wc: WNDCLASSW = std::mem::zeroed();
        wc.style = 0;
        wc.lpfnWndProc = Some(wndproc);
        wc.cbClsExtra = 0;
        wc.cbWndExtra = 0;
        wc.hInstance = inst;
        wc.hIcon = 0;
        wc.hCursor = LoadCursorW(0, IDC_ARROW);
        wc.hbrBackground = (COLOR_BTNFACE + 1) as HBRUSH;
        wc.lpszMenuName = ptr::null();
        wc.lpszClassName = class_name.as_ptr();
        if RegisterClassW(&wc) == 0 {
            return;
        }
        let title = wide(&t("title"));
        let hwnd = CreateWindowExW(
            0,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            490,
            210,
            0,
            0,
            inst,
            ptr::null(),
        );
        if hwnd == 0 {
            return;
        }
        state().hwnd = hwnd;
        ShowWindow(hwnd, SW_SHOW);

        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, 0, 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

extern "system" fn wndproc(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    unsafe {
        match msg {
            WM_CREATE => {
                let s = state();
                s.hwnd = hwnd;
                s.label = CreateWindowExW(
                    0,
                    wide("STATIC").as_ptr(),
                    wide(&t("label.language")).as_ptr(),
                    WS_CHILD | WS_VISIBLE,
                    16,
                    18,
                    420,
                    20,
                    hwnd,
                    0,
                    0,
                    ptr::null(),
                );
                s.combo = CreateWindowExW(
                    0,
                    wide("COMBOBOX").as_ptr(),
                    ptr::null(),
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP | CBS_DROPDOWNLIST as u32 | WS_VSCROLL,
                    16,
                    42,
                    420,
                    200,
                    hwnd,
                    ID_LANG as isize,
                    0,
                    ptr::null(),
                );
                s.btn_launch = CreateWindowExW(
                    0,
                    wide("BUTTON").as_ptr(),
                    wide(&t("button.launch")).as_ptr(),
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON as u32,
                    16,
                    84,
                    190,
                    32,
                    hwnd,
                    ID_LAUNCH as isize,
                    0,
                    ptr::null(),
                );
                s.btn_vanilla = CreateWindowExW(
                    0,
                    wide("BUTTON").as_ptr(),
                    wide(&t("button.vanilla")).as_ptr(),
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON as u32,
                    216,
                    84,
                    150,
                    32,
                    hwnd,
                    ID_VANILLA as isize,
                    0,
                    ptr::null(),
                );
                s.btn_refresh = CreateWindowExW(
                    0,
                    wide("BUTTON").as_ptr(),
                    wide(&t("button.refresh")).as_ptr(),
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON as u32,
                    376,
                    84,
                    80,
                    32,
                    hwnd,
                    ID_REFRESH as isize,
                    0,
                    ptr::null(),
                );
                s.status = CreateWindowExW(
                    0,
                    wide("STATIC").as_ptr(),
                    ptr::null(),
                    WS_CHILD | WS_VISIBLE,
                    16,
                    126,
                    440,
                    40,
                    hwnd,
                    ID_STATUS as isize,
                    0,
                    ptr::null(),
                );
                load_languages();
                return 0;
            }
            WM_COMMAND => {
                let id = (wp & 0xffff) as i32;
                let note = ((wp >> 16) & 0xffff) as u32;
                match id {
                    ID_LANG => {
                        if note == CBN_SELCHANGE {
                            apply_pack_language();
                        }
                    }
                    ID_LAUNCH => {
                        let sel = SendMessageW(state().combo, CB_GETCURSEL, 0, 0);
                        if sel >= 0 {
                            let i = sel as usize;
                            if i < state().codes.len() {
                                let code = state().codes[i].code.clone();
                                launch(Some(&code), false);
                            }
                        }
                    }
                    ID_VANILLA => launch(None, true),
                    ID_REFRESH => load_languages(),
                    _ => {}
                }
                return 0;
            }
            WM_DESTROY => {
                PostQuitMessage(0);
                return 0;
            }
            _ => {}
        }
        let _ = lp;
        DefWindowProcW(hwnd, msg, wp, lp)
    }
}

fn ui_for_system() -> String {
    let id = unsafe { GetUserDefaultUILanguage() };
    match id & 0x3ff {
        0x04 => "zh".to_string(),
        0x11 => "ja".to_string(),
        _ => "en".to_string(),
    }
}

fn load_ui_strings(root: &Path, ui: &str) -> HashMap<String, String> {
    let mut strings = HashMap::new();
    let path = root.join("ui").join(format!("{ui}.ini"));
    read_ini(&path, &mut strings);
    if strings.is_empty() && ui != "en" {
        read_ini(&root.join("ui").join("en.ini"), &mut strings);
    }
    strings
}

fn read_ini(path: &Path, out: &mut HashMap<String, String>) {
    let data = match fs::read(path) {
        Ok(v) => v,
        Err(_) => return,
    };
    let text = String::from_utf8_lossy(&data);
    let text = text.trim_start_matches('\u{feff}');
    for raw in text.lines() {
        let line = trim(raw);
        if line.is_empty() || line.starts_with('#') || line.starts_with(';') || line.starts_with('[') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        let key = trim(key);
        if key.is_empty() {
            continue;
        }
        out.insert(key.to_string(), unescape(trim(value)));
    }
}

fn trim(s: &str) -> &str {
    s.trim_matches([' ', '\t', '\r', '\n'])
}

fn unescape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars();
    while let Some(c) = chars.next() {
        if c == '\\' {
            if let Some(next) = chars.next() {
                if next == 'n' {
                    out.push('\n');
                } else {
                    out.push('\\');
                    out.push(next);
                }
            } else {
                out.push('\\');
            }
        } else {
            out.push(c);
        }
    }
    out
}

fn t(key: &str) -> String {
    let s = state();
    if let Some(v) = s.strings.get(key) {
        return v.clone();
    }
    for (k, v) in BUILTIN {
        if *k == key {
            return v.to_string();
        }
    }
    key.to_string()
}

enum Arg {
    Str(String),
    Num(u32),
}

fn tf(key: &str, args: &[Arg]) -> String {
    let fmt = t(key);
    let mut out = String::with_capacity(fmt.len() + 16);
    let mut chars = fmt.chars().peekable();
    let mut ai = 0usize;
    while let Some(c) = chars.next() {
        if c != '%' {
            out.push(c);
            continue;
        }
        if chars.peek() == Some(&'%') {
            chars.next();
            out.push('%');
            continue;
        }
        let mut long = false;
        if chars.peek() == Some(&'l') {
            chars.next();
            long = true;
        }
        let Some(spec) = chars.next() else {
            out.push('%');
            break;
        };
        match spec {
            'd' | 'u' => {
                if let Some(Arg::Num(n)) = args.get(ai) {
                    out.push_str(&n.to_string());
                }
                ai += 1;
            }
            's' => {
                if let Some(Arg::Str(s)) = args.get(ai) {
                    out.push_str(s);
                }
                ai += 1;
            }
            _ => {
                out.push('%');
                if long {
                    out.push('l');
                }
                out.push(spec);
            }
        }
    }
    out
}

fn load_languages() {
    let s = state();
    s.codes.clear();
    unsafe {
        SendMessageW(s.combo, CB_RESETCONTENT, 0, 0);
    }
    let packs = s.root.join("PR2Packs");
    let mut entries: Vec<_> = match fs::read_dir(&packs) {
        Ok(v) => v.filter_map(|e| e.ok()).collect(),
        Err(_) => Vec::new(),
    };
    entries.sort_by_key(|e| e.file_name());
    for entry in entries {
        if s.codes.len() >= 64 {
            break;
        }
        let name = match entry.file_name().into_string() {
            Ok(v) => v,
            Err(_) => continue,
        };
        let Some((stem, ext)) = name.rsplit_once('.') else {
            continue;
        };
        if !ext.eq_ignore_ascii_case("txt") || stem.contains('.') {
            continue;
        }
        if stem.is_empty() || stem.len() >= 64 || !valid_lang_code(stem) {
            continue;
        }
        let meta = read_pack_meta(&packs.join(&name));
        let label = if meta.0.is_empty() {
            stem.to_string()
        } else {
            meta.0.clone()
        };
        let label_w = wide(&label);
        unsafe {
            SendMessageW(
                s.combo,
                CB_ADDSTRING,
                0,
                label_w.as_ptr() as LPARAM,
            );
        }
        s.codes.push(PackInfo {
            code: stem.to_string(),
            gui: meta.1,
            min_runtime: meta.2,
        });
    }

    let current = read_locale_language(&s.root).unwrap_or_default();
    let mut sel = 0usize;
    for (i, p) in s.codes.iter().enumerate() {
        if p.code.eq_ignore_ascii_case(&current) {
            sel = i;
            break;
        }
    }
    if !s.codes.is_empty() {
        unsafe {
            SendMessageW(s.combo, CB_SETCURSEL, sel as WPARAM, 0);
        }
    }
    apply_pack_language();
}

fn read_pack_meta(path: &Path) -> (String, String, u32) {
    let mut alias = String::new();
    let mut gui = String::new();
    let mut min_runtime = 1u32;
    let Ok(data) = fs::read(path) else {
        return (alias, gui, min_runtime);
    };
    let text = String::from_utf8_lossy(&data);
    let text = text.trim_start_matches('\u{feff}');
    for line in text.lines().take(64) {
        let p = trim(line);
        if p.is_empty() || p.starts_with(';') {
            continue;
        }
        if !p.starts_with("# pack-meta ") {
            if p.starts_with('#') {
                continue;
            }
            break;
        }
        let Some((k, v)) = p[12..].split_once('=') else {
            continue;
        };
        match trim(k) {
            "alias" => {
                alias = trim(v).chars().take(255).collect();
            }
            "gui" => {
                gui = trim(v).chars().take(15).collect();
            }
            "min_runtime" => {
                if let Ok(n) = trim(v).parse::<u32>() {
                    min_runtime = min_runtime.max(n);
                }
            }
            _ => {}
        }
    }
    (alias, gui, min_runtime)
}

fn apply_pack_language() {
    let s = state();
    let sel = unsafe { SendMessageW(s.combo, CB_GETCURSEL, 0, 0) };
    let mut ui = s.default_ui.clone();
    if sel >= 0 {
        let i = sel as usize;
        if i < s.codes.len() && !s.codes[i].gui.is_empty() {
            let g = &s.codes[i].gui;
            if safe_ui(g) {
                ui = g.clone();
            }
        }
    }
    s.strings = load_ui_strings(&s.root, &ui);
    update_texts();
}

fn safe_ui(ui: &str) -> bool {
    !ui.is_empty()
        && ui
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

fn update_texts() {
    let s = state();
    unsafe {
        SetWindowTextW(s.hwnd, wide(&t("title")).as_ptr());
        SetWindowTextW(s.label, wide(&t("label.language")).as_ptr());
        SetWindowTextW(s.btn_launch, wide(&t("button.launch")).as_ptr());
        SetWindowTextW(s.btn_vanilla, wide(&t("button.vanilla")).as_ptr());
        SetWindowTextW(s.btn_refresh, wide(&t("button.refresh")).as_ptr());
    }
    update_status();
}

fn update_status() {
    let s = state();
    let count = s.codes.len() as u32;
    let text = if count > 0 {
        tf("status.count", &[Arg::Num(count)])
    } else {
        t("status.none")
    };
    unsafe {
        SetWindowTextW(s.status, wide(&text).as_ptr());
    }
}

fn launch(lang: Option<&str>, vanilla: bool) {
    let s = state();
    let launcher = s.root.join("PR2Launcher.exe");
    if !launcher.is_file() {
        message("error.no_launcher", &[]);
        return;
    }
    if !vanilla {
        let Some(code) = lang else {
            message("error.no_language", &[]);
            return;
        };
        let minv = s
            .codes
            .iter()
            .find(|p| p.code.eq_ignore_ascii_case(code))
            .map(|p| p.min_runtime)
            .unwrap_or(1);
        if minv > RUNTIME_VERSION {
            message("error.pack_too_new", &[Arg::Num(minv), Arg::Num(RUNTIME_VERSION)]);
            return;
        }
        if !language_fonts_complete(&s.root, code) {
            let text = tf("error.font_missing", &[Arg::Str(code.to_string())]);
            let title = t("title");
            let r = unsafe {
                MessageBoxW(
                    0,
                    wide(&text).as_ptr(),
                    wide(&title).as_ptr(),
                    MB_YESNO | MB_ICONWARNING,
                )
            };
            if r != IDYES {
                return;
            }
        }
    }

    let cmd = if vanilla {
        format!("\"{}\" --vanilla", launcher.display())
    } else {
        format!("\"{}\" --lang={}", launcher.display(), lang.unwrap())
    };
    let mut cmd_c: Vec<u8> = cmd.as_bytes().to_vec();
    cmd_c.push(0);
    let dir = s.root.to_string_lossy().into_owned();
    let mut dir_c: Vec<u8> = dir.as_bytes().to_vec();
    dir_c.push(0);
    let mut si: STARTUPINFOA = unsafe { std::mem::zeroed() };
    si.cb = std::mem::size_of::<STARTUPINFOA>() as u32;
    let mut pi: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    let ok = unsafe {
        CreateProcessA(
            ptr::null(),
            cmd_c.as_mut_ptr(),
            ptr::null(),
            ptr::null(),
            0,
            CREATE_NO_WINDOW,
            ptr::null(),
            dir_c.as_ptr(),
            &si,
            &mut pi,
        )
    };
    if ok == 0 {
        message("error.launch_failed", &[]);
        return;
    }
    let mut code = 0u32;
    unsafe {
        if WaitForSingleObject(pi.hProcess, 4000) == 0 {
            GetExitCodeProcess(pi.hProcess, &mut code);
        }
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    if code != 0 {
        message("error.exit_code", &[Arg::Num(code)]);
    } else {
        if !vanilla {
            if let Some(lang) = lang {
                let _ = write_locale_language(&s.root, lang);
            }
        }
        let text = if vanilla {
            t("status.vanilla")
        } else {
            t("status.launched")
        };
        unsafe {
            SetWindowTextW(s.status, wide(&text).as_ptr());
        }
    }
}

fn message(key: &str, args: &[Arg]) {
    let text = tf(key, args);
    let title = t("title");
    unsafe {
        MessageBoxW(0, wide(&text).as_ptr(), wide(&title).as_ptr(), MB_ICONERROR);
    }
}

fn wide(s: &str) -> Vec<u16> {
    let mut out: Vec<u16> = s.encode_utf16().collect();
    out.push(0);
    out
}
