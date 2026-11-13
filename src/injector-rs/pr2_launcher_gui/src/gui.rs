use std::ffi::c_void;
use std::path::PathBuf;
use std::ptr;

use pr2_common::{
    exe_dir, language_fonts_complete, read_locale_language, write_locale_language, RUNTIME_VERSION,
};
use windows_sys::Win32::Foundation::{HINSTANCE, HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::Globalization::GetUserDefaultUILanguage;
use windows_sys::Win32::Graphics::Gdi::{
    CreateFontW, DeleteObject, GetDC, GetDeviceCaps, GetStockObject, HDC, ReleaseDC, SetBkMode,
    SetTextColor, CLEARTYPE_QUALITY, COLOR_BTNFACE, DEFAULT_CHARSET, DEFAULT_PITCH, FF_DONTCARE,
    FW_BOLD, FW_NORMAL, HBRUSH, LOGPIXELSX, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, TRANSPARENT,
    WHITE_BRUSH,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetMessageW, GetWindowLongPtrW,
    LoadCursorW, MessageBoxW, PostQuitMessage, RegisterClassW, SendMessageW, SetWindowLongPtrW,
    SetWindowTextW, ShowWindow, TranslateMessage, BS_DEFPUSHBUTTON, BS_PUSHBUTTON, CB_ADDSTRING,
    CB_GETCURSEL, CB_RESETCONTENT, CB_SETCURSEL, CBN_SELCHANGE, CBS_DROPDOWNLIST, CREATESTRUCTW,
    CW_USEDEFAULT, GWLP_USERDATA, IDC_ARROW, IDYES, MB_ICONERROR, MB_ICONWARNING, MB_YESNO, MSG,
    SW_SHOW, WM_COMMAND, WM_CREATE, WM_CTLCOLORSTATIC, WM_DESTROY, WM_NCDESTROY, WM_SETFONT,
    WS_CAPTION, WS_CHILD, WS_EX_CLIENTEDGE, WS_MINIMIZEBOX, WS_OVERLAPPED, WS_SYSMENU, WS_TABSTOP,
    WS_VISIBLE, WS_VSCROLL, WNDCLASSW,
};

use crate::packs::{self, Pack};
use crate::process::{self, LaunchError};
use crate::strings::{Arg, Strings};

const ID_LANG: i32 = 1001;
const ID_LAUNCH: i32 = 1002;
const ID_VANILLA: i32 = 1003;
const ID_REFRESH: i32 = 1004;
const ID_STATUS: i32 = 1005;
const ID_KILL: i32 = 1006;
const ID_TITLE: i32 = 1007;
const ID_SUBTITLE: i32 = 1008;
const ID_SEPARATOR: i32 = 1009;
const ID_HINT: i32 = 1010;
const ST_LEFT: u32 = 0x0000;
const ST_NOPREFIX: u32 = 0x0080;
const ST_ETCHEDHORZ: u32 = 0x0010;

struct AppInit {
    root: PathBuf,
    default_ui: String,
    strings: Strings,
    dpi: u32,
}

struct App {
    root: PathBuf,
    hwnd: HWND,
    title: HWND,
    subtitle: HWND,
    separator: HWND,
    hint: HWND,
    combo: HWND,
    status: HWND,
    label: HWND,
    btn_launch: HWND,
    btn_vanilla: HWND,
    btn_refresh: HWND,
    btn_kill: HWND,
    packs: Vec<Pack>,
    strings: Strings,
    default_ui: String,
    dpi: u32,
    font_title: isize,
    font_normal: isize,
    font_small: isize,
}

pub fn run() {
    unsafe {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }
    let dpi = dpi_for_system();
    let root = exe_dir();
    let default_ui = ui_for_system();
    let strings = Strings::load(&root, &default_ui);
    let init = Box::into_raw(Box::new(AppInit {
        root,
        default_ui,
        strings,
        dpi,
    })) as *const c_void;

    unsafe {
        let inst = GetModuleHandleW(ptr::null()) as HINSTANCE;
        let class_name = wide("PR2LocalizationGUI");
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
            drop(Box::from_raw(init as *mut AppInit));
            return;
        }
        let title = wide("Port Royale 2 Localization");
        let hwnd = CreateWindowExW(
            0,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            scale(560, dpi),
            scale(400, dpi),
            0,
            0,
            inst,
            init,
        );
        if hwnd == 0 {
            drop(Box::from_raw(init as *mut AppInit));
            return;
        }
        ShowWindow(hwnd, SW_SHOW);

        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, 0, 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

extern "system" fn wndproc(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    match msg {
        WM_CREATE => {
            let create = unsafe { &*(lp as *const CREATESTRUCTW) };
            let init = unsafe { Box::from_raw(create.lpCreateParams as *mut AppInit) };
            let mut app = Box::new(App::new(*init));
            app.create_controls(hwnd);
            let app_ptr = Box::into_raw(app);
            unsafe {
                SetWindowLongPtrW(hwnd, GWLP_USERDATA, app_ptr as i32);
            }
            if let Some(app) = app_mut(hwnd) {
                app.load_packs();
            }
            return 0;
        }
        WM_COMMAND => {
            let id = (wp & 0xffff) as i32;
            let note = ((wp >> 16) & 0xffff) as u32;
            if let Some(app) = app_mut(hwnd) {
                app.on_command(id, note);
            }
            return 0;
        }
        WM_CTLCOLORSTATIC => {
            if let Some(app) = app_mut(hwnd) {
                return app.color_static(wp as HDC, lp as HWND);
            }
            return unsafe { DefWindowProcW(hwnd, msg, wp, lp) };
        }
        WM_DESTROY => {
            unsafe {
                PostQuitMessage(0);
            }
            return 0;
        }
        WM_NCDESTROY => {
            let ptr = unsafe { GetWindowLongPtrW(hwnd, GWLP_USERDATA) };
            if ptr != 0 {
                unsafe {
                    SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
                    drop(Box::from_raw(ptr as *mut App));
                }
            }
            return unsafe { DefWindowProcW(hwnd, msg, wp, lp) };
        }
        _ => {}
    }
    unsafe { DefWindowProcW(hwnd, msg, wp, lp) }
}

fn app_mut(hwnd: HWND) -> Option<&'static mut App> {
    let ptr = unsafe { GetWindowLongPtrW(hwnd, GWLP_USERDATA) };
    if ptr == 0 {
        None
    } else {
        Some(unsafe { &mut *(ptr as *mut App) })
    }
}

impl App {
    fn new(init: AppInit) -> Self {
        let dpi = init.dpi;
        Self {
            root: init.root,
            hwnd: 0,
            title: 0,
            subtitle: 0,
            separator: 0,
            hint: 0,
            combo: 0,
            status: 0,
            label: 0,
            btn_launch: 0,
            btn_vanilla: 0,
            btn_refresh: 0,
            btn_kill: 0,
            packs: Vec::new(),
            strings: init.strings,
            default_ui: init.default_ui,
            dpi,
            font_title: make_font(dpi, 16, FW_BOLD as i32),
            font_normal: make_font(dpi, 10, FW_NORMAL as i32),
            font_small: make_font(dpi, 9, FW_NORMAL as i32),
        }
    }

    fn create_controls(&mut self, hwnd: HWND) {
        self.hwnd = hwnd;
        let dpi = self.dpi;
        let px = |v: i32| scale(v, dpi);
        unsafe {
            self.title = CreateWindowExW(
                0,
                wide("STATIC").as_ptr(),
                wide(&self.strings.t("title")).as_ptr(),
                WS_CHILD | WS_VISIBLE | ST_LEFT | ST_NOPREFIX,
                px(24),
                px(16),
                px(496),
                px(34),
                hwnd,
                ID_TITLE as isize,
                0,
                ptr::null(),
            );
            self.subtitle = CreateWindowExW(
                0,
                wide("STATIC").as_ptr(),
                wide(&self.strings.t("subtitle")).as_ptr(),
                WS_CHILD | WS_VISIBLE | ST_LEFT | ST_NOPREFIX,
                px(24),
                px(54),
                px(496),
                px(20),
                hwnd,
                ID_SUBTITLE as isize,
                0,
                ptr::null(),
            );
            self.separator = CreateWindowExW(
                0,
                wide("STATIC").as_ptr(),
                ptr::null(),
                WS_CHILD | WS_VISIBLE | ST_ETCHEDHORZ,
                px(24),
                px(82),
                px(496),
                px(2),
                hwnd,
                ID_SEPARATOR as isize,
                0,
                ptr::null(),
            );
            self.label = CreateWindowExW(
                0,
                wide("STATIC").as_ptr(),
                wide(&self.strings.t("label.language")).as_ptr(),
                WS_CHILD | WS_VISIBLE | ST_LEFT | ST_NOPREFIX,
                px(24),
                px(94),
                px(496),
                px(20),
                hwnd,
                0,
                0,
                ptr::null(),
            );
            self.combo = CreateWindowExW(
                0,
                wide("COMBOBOX").as_ptr(),
                ptr::null(),
                WS_CHILD | WS_VISIBLE | WS_TABSTOP | CBS_DROPDOWNLIST as u32 | WS_VSCROLL,
                px(24),
                px(116),
                px(496),
                px(260),
                hwnd,
                ID_LANG as isize,
                0,
                ptr::null(),
            );
            self.btn_launch = CreateWindowExW(
                0,
                wide("BUTTON").as_ptr(),
                wide(&self.strings.t("button.launch")).as_ptr(),
                WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON as u32,
                px(24),
                px(158),
                px(220),
                px(42),
                hwnd,
                ID_LAUNCH as isize,
                0,
                ptr::null(),
            );
            self.btn_vanilla = CreateWindowExW(
                0,
                wide("BUTTON").as_ptr(),
                wide(&self.strings.t("button.vanilla")).as_ptr(),
                WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON as u32,
                px(256),
                px(158),
                px(160),
                px(42),
                hwnd,
                ID_VANILLA as isize,
                0,
                ptr::null(),
            );
            self.btn_refresh = CreateWindowExW(
                0,
                wide("BUTTON").as_ptr(),
                wide(&self.strings.t("button.refresh")).as_ptr(),
                WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON as u32,
                px(428),
                px(158),
                px(90),
                px(42),
                hwnd,
                ID_REFRESH as isize,
                0,
                ptr::null(),
            );
            self.btn_kill = CreateWindowExW(
                0,
                wide("BUTTON").as_ptr(),
                wide(&self.strings.t("button.kill")).as_ptr(),
                WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON as u32,
                px(304),
                px(214),
                px(216),
                px(34),
                hwnd,
                ID_KILL as isize,
                0,
                ptr::null(),
            );
            self.status = CreateWindowExW(
                WS_EX_CLIENTEDGE,
                wide("STATIC").as_ptr(),
                ptr::null(),
                WS_CHILD | WS_VISIBLE | ST_LEFT | ST_NOPREFIX,
                px(24),
                px(262),
                px(496),
                px(52),
                hwnd,
                ID_STATUS as isize,
                0,
                ptr::null(),
            );
            self.hint = CreateWindowExW(
                0,
                wide("STATIC").as_ptr(),
                wide(&self.strings.t("hint.footer")).as_ptr(),
                WS_CHILD | WS_VISIBLE | ST_LEFT | ST_NOPREFIX,
                px(24),
                px(322),
                px(496),
                px(36),
                hwnd,
                ID_HINT as isize,
                0,
                ptr::null(),
            );
        }

        for (control, font) in [
            (self.title, self.font_title),
            (self.subtitle, self.font_small),
            (self.label, self.font_normal),
            (self.combo, self.font_normal),
            (self.btn_launch, self.font_normal),
            (self.btn_vanilla, self.font_normal),
            (self.btn_refresh, self.font_normal),
            (self.btn_kill, self.font_normal),
            (self.status, self.font_small),
            (self.hint, self.font_small),
        ] {
            if font != 0 {
                unsafe {
                    SendMessageW(control, WM_SETFONT, font as WPARAM, 1);
                }
            }
        }
    }

    fn color_static(&self, hdc: HDC, control: HWND) -> LRESULT {
        unsafe {
            SetBkMode(hdc, TRANSPARENT as i32);
            if control == self.status {
                SetTextColor(hdc, rgb(32, 32, 32));
                return GetStockObject(WHITE_BRUSH) as LRESULT;
            }
            if control == self.title {
                SetTextColor(hdc, rgb(20, 45, 80));
            } else if control == self.subtitle || control == self.hint {
                SetTextColor(hdc, rgb(96, 96, 96));
            } else {
                SetTextColor(hdc, rgb(32, 32, 32));
            }
            (COLOR_BTNFACE + 1) as LRESULT
        }
    }

    fn on_command(&mut self, id: i32, note: u32) {
        match id {
            ID_LANG => {
                if note == CBN_SELCHANGE {
                    self.apply_language();
                }
            }
            ID_LAUNCH => self.launch(false),
            ID_VANILLA => self.launch(true),
            ID_REFRESH => self.load_packs(),
            ID_KILL => self.kill_game(),
            _ => {}
        }
    }

    fn load_packs(&mut self) {
        self.packs = packs::scan(&self.root);
        unsafe {
            SendMessageW(self.combo, CB_RESETCONTENT, 0, 0);
        }
        for pack in &self.packs {
            let label = wide(&pack.label);
            unsafe {
                SendMessageW(
                    self.combo,
                    CB_ADDSTRING,
                    0,
                    label.as_ptr() as LPARAM,
                );
            }
        }

        let current = read_locale_language(&self.root).unwrap_or_default();
        let selected = self
            .packs
            .iter()
            .position(|p| p.code.eq_ignore_ascii_case(&current))
            .unwrap_or(0);
        if !self.packs.is_empty() {
            unsafe {
                SendMessageW(self.combo, CB_SETCURSEL, selected as WPARAM, 0);
            }
        }
        self.apply_language();
    }

    fn apply_language(&mut self) {
        let mut ui = self.default_ui.clone();
        if let Some(pack) = self.selected_pack() {
            if !pack.gui.is_empty() && safe_ui(&pack.gui) {
                ui = pack.gui.clone();
            }
        }
        self.strings = Strings::load(&self.root, &ui);
        self.update_texts();
    }

    fn selected_pack(&self) -> Option<&Pack> {
        let index = unsafe { SendMessageW(self.combo, CB_GETCURSEL, 0, 0) };
        if index < 0 {
            None
        } else {
            self.packs.get(index as usize)
        }
    }

    fn selected_code(&self) -> Option<String> {
        self.selected_pack().map(|p| p.code.clone())
    }

    fn update_texts(&self) {
        unsafe {
            SetWindowTextW(self.hwnd, wide(&self.strings.t("title")).as_ptr());
            SetWindowTextW(self.title, wide(&self.strings.t("title")).as_ptr());
            SetWindowTextW(
                self.subtitle,
                wide(&self.strings.t("subtitle")).as_ptr(),
            );
            SetWindowTextW(
                self.label,
                wide(&self.strings.t("label.language")).as_ptr(),
            );
            SetWindowTextW(
                self.btn_launch,
                wide(&self.strings.t("button.launch")).as_ptr(),
            );
            SetWindowTextW(
                self.btn_vanilla,
                wide(&self.strings.t("button.vanilla")).as_ptr(),
            );
            SetWindowTextW(
                self.btn_refresh,
                wide(&self.strings.t("button.refresh")).as_ptr(),
            );
            SetWindowTextW(
                self.btn_kill,
                wide(&self.strings.t("button.kill")).as_ptr(),
            );
            SetWindowTextW(
                self.hint,
                wide(&self.strings.t("hint.footer")).as_ptr(),
            );
        }
        self.update_status();
    }

    fn update_status(&self) {
        let count = self.packs.len() as u32;
        let text = if count > 0 {
            self.strings.tf("status.count", &[Arg::Num(count)])
        } else {
            self.strings.t("status.none")
        };
        unsafe {
            SetWindowTextW(self.status, wide(&text).as_ptr());
        }
    }

    fn launch(&mut self, vanilla: bool) {
        let lang = if vanilla {
            None
        } else {
            let Some(code) = self.selected_code() else {
                self.show_error("error.no_language", &[]);
                return;
            };
            Some(code)
        };

        if let Some(code) = lang.as_deref() {
            let min_runtime = self
                .packs
                .iter()
                .find(|p| p.code.eq_ignore_ascii_case(code))
                .map(|p| p.min_runtime)
                .unwrap_or(1);
            if min_runtime > RUNTIME_VERSION {
                self.show_error(
                    "error.pack_too_new",
                    &[Arg::Num(min_runtime), Arg::Num(RUNTIME_VERSION)],
                );
                return;
            }
            if !language_fonts_complete(&self.root, code) {
                let text = self
                    .strings
                    .tf("error.font_missing", &[Arg::Str(code.to_string())]);
                if !self.confirm(&text) {
                    return;
                }
            }
        }

        match process::launch(&self.root, lang.as_deref(), vanilla) {
            Ok(()) => {
                if !vanilla {
                    if let Some(code) = lang.as_deref() {
                        let _ = write_locale_language(&self.root, code);
                    }
                }
                let text = if vanilla {
                    self.strings.t("status.vanilla")
                } else {
                    self.strings.t("status.launched")
                };
                self.set_status(&text);
            }
            Err(err) => self.show_launch_error(err),
        }
    }

    fn show_launch_error(&self, err: LaunchError) {
        match err {
            LaunchError::NoLauncher => self.show_error("error.no_launcher", &[]),
            LaunchError::NoLanguage => self.show_error("error.no_language", &[]),
            LaunchError::LaunchFailed => self.show_error("error.launch_failed", &[]),
            LaunchError::ExitCode(code) => {
                self.show_error("error.exit_code", &[Arg::Num(code)])
            }
        }
    }

    fn kill_game(&mut self) {
        let pids = process::local_game_processes(&self.root);
        if pids.is_empty() {
            self.show_error("error.no_game", &[]);
            return;
        }

        let prompt = self
            .strings
            .tf("confirm.kill", &[Arg::Num(pids.len() as u32)]);
        if !self.confirm(&prompt) {
            return;
        }

        let mut killed = 0u32;
        let mut last_error = 0u32;
        for pid in pids {
            match process::terminate(pid) {
                Ok(()) => killed += 1,
                Err(code) => last_error = code,
            }
        }
        if killed == 0 {
            self.show_error("error.kill_failed", &[Arg::Num(last_error)]);
            return;
        }
        let text = self
            .strings
            .tf("status.killed", &[Arg::Num(killed)]);
        self.set_status(&text);
    }

    fn set_status(&self, text: &str) {
        unsafe {
            SetWindowTextW(self.status, wide(text).as_ptr());
        }
    }

    fn show_error(&self, key: &str, args: &[Arg]) {
        let text = self.strings.tf(key, args);
        let title = self.strings.t("title");
        unsafe {
            MessageBoxW(
                0,
                wide(&text).as_ptr(),
                wide(&title).as_ptr(),
                MB_ICONERROR,
            );
        }
    }

    fn confirm(&self, text: &str) -> bool {
        let title = self.strings.t("title");
        let answer = unsafe {
            MessageBoxW(
                0,
                wide(text).as_ptr(),
                wide(&title).as_ptr(),
                MB_YESNO | MB_ICONWARNING,
            )
        };
        answer == IDYES
    }
}

impl Drop for App {
    fn drop(&mut self) {
        for font in [self.font_title, self.font_normal, self.font_small] {
            if font != 0 {
                unsafe {
                    DeleteObject(font);
                }
            }
        }
    }
}

fn make_font(dpi: u32, point: i32, weight: i32) -> isize {
    let height = -((point * dpi as i32 + 36) / 72);
    let face = wide("Segoe UI");
    unsafe {
        CreateFontW(
            height,
            0,
            0,
            0,
            weight,
            0,
            0,
            0,
            DEFAULT_CHARSET as u32,
            OUT_DEFAULT_PRECIS as u32,
            CLIP_DEFAULT_PRECIS as u32,
            CLEARTYPE_QUALITY as u32,
            (DEFAULT_PITCH | FF_DONTCARE) as u32,
            face.as_ptr(),
        )
    }
}

fn scale(value: i32, dpi: u32) -> i32 {
    value * dpi as i32 / 96
}

fn dpi_for_system() -> u32 {
    unsafe {
        let dc = GetDC(0);
        if dc == 0 {
            return 96;
        }
        let dpi = GetDeviceCaps(dc, LOGPIXELSX as i32);
        ReleaseDC(0, dc);
        if dpi >= 96 {
            dpi as u32
        } else {
            96
        }
    }
}

fn rgb(r: u8, g: u8, b: u8) -> u32 {
    r as u32 | ((g as u32) << 8) | ((b as u32) << 16)
}

fn ui_for_system() -> String {
    let id = unsafe { GetUserDefaultUILanguage() };
    match id & 0x3ff {
        0x04 => "zh".to_string(),
        0x11 => "ja".to_string(),
        _ => "en".to_string(),
    }
}

fn safe_ui(ui: &str) -> bool {
    !ui.is_empty()
        && ui
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

fn wide(s: &str) -> Vec<u16> {
    let mut out: Vec<u16> = s.encode_utf16().collect();
    out.push(0);
    out
}
