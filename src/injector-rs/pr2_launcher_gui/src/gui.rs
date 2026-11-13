use std::ffi::c_void;
use std::path::PathBuf;
use std::ptr;

use pr2_common::{
    exe_dir, language_fonts_complete, read_locale_language, write_locale_language, RUNTIME_VERSION,
};
use windows_sys::Win32::Foundation::{HINSTANCE, HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::Globalization::GetUserDefaultUILanguage;
use windows_sys::Win32::Graphics::Gdi::{COLOR_BTNFACE, HBRUSH};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetMessageW, GetWindowLongPtrW,
    LoadCursorW, MessageBoxW, PostQuitMessage, RegisterClassW, SendMessageW, SetWindowLongPtrW,
    SetWindowTextW, ShowWindow, TranslateMessage, BS_PUSHBUTTON, CB_ADDSTRING, CB_GETCURSEL,
    CB_RESETCONTENT, CB_SETCURSEL, CBN_SELCHANGE, CBS_DROPDOWNLIST, CREATESTRUCTW, CW_USEDEFAULT,
    GWLP_USERDATA, IDC_ARROW, IDYES, MB_ICONERROR, MB_ICONWARNING, MB_YESNO, MSG, SW_SHOW,
    WM_COMMAND, WM_CREATE, WM_DESTROY, WM_NCDESTROY, WS_CAPTION, WS_CHILD, WS_MINIMIZEBOX,
    WS_OVERLAPPED, WS_SYSMENU, WS_TABSTOP, WS_VISIBLE, WS_VSCROLL, WNDCLASSW,
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

struct AppInit {
    root: PathBuf,
    default_ui: String,
    strings: Strings,
}

struct App {
    root: PathBuf,
    hwnd: HWND,
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
}

pub fn run() {
    let root = exe_dir();
    let default_ui = ui_for_system();
    let strings = Strings::load(&root, &default_ui);
    let init = Box::into_raw(Box::new(AppInit {
        root,
        default_ui,
        strings,
    })) as *const c_void;

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
            drop(Box::from_raw(init as *mut AppInit));
            return;
        }
        let title = wide("Port Royale 2 Launcher");
        let hwnd = CreateWindowExW(
            0,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            490,
            240,
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
        Self {
            root: init.root,
            hwnd: 0,
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
        }
    }

    fn create_controls(&mut self, hwnd: HWND) {
        self.hwnd = hwnd;
        unsafe {
            self.label = CreateWindowExW(
                0,
                wide("STATIC").as_ptr(),
                wide(&self.strings.t("label.language")).as_ptr(),
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
            self.combo = CreateWindowExW(
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
            self.btn_launch = CreateWindowExW(
                0,
                wide("BUTTON").as_ptr(),
                wide(&self.strings.t("button.launch")).as_ptr(),
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
            self.btn_vanilla = CreateWindowExW(
                0,
                wide("BUTTON").as_ptr(),
                wide(&self.strings.t("button.vanilla")).as_ptr(),
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
            self.btn_refresh = CreateWindowExW(
                0,
                wide("BUTTON").as_ptr(),
                wide(&self.strings.t("button.refresh")).as_ptr(),
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
            self.btn_kill = CreateWindowExW(
                0,
                wide("BUTTON").as_ptr(),
                wide(&self.strings.t("button.kill")).as_ptr(),
                WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON as u32,
                16,
                124,
                190,
                28,
                hwnd,
                ID_KILL as isize,
                0,
                ptr::null(),
            );
            self.status = CreateWindowExW(
                0,
                wide("STATIC").as_ptr(),
                ptr::null(),
                WS_CHILD | WS_VISIBLE,
                16,
                164,
                440,
                40,
                hwnd,
                ID_STATUS as isize,
                0,
                ptr::null(),
            );
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
