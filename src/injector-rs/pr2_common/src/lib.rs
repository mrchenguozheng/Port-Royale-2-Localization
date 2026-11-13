use std::ffi::OsString;
use std::fs;
use std::os::windows::ffi::OsStringExt;
use std::path::{Path, PathBuf};

use windows_sys::Win32::System::LibraryLoader::GetModuleFileNameW;

pub const RUNTIME_VERSION: u32 = 1;
pub const DATA_DIR: &str = "PR2Localization";
pub const FONT_NAMES: [&str; 4] = [
    "ARIAL.TTF",
    "ELGRECO_.TTF",
    "Tiepolo_black.ttf",
    "Tiepolo_bold.ttf",
];

pub fn exe_path() -> PathBuf {
    let mut buf = [0u16; 260];
    let n = unsafe { GetModuleFileNameW(0, buf.as_mut_ptr(), buf.len() as u32) };
    if n == 0 {
        return PathBuf::from(".");
    }
    PathBuf::from(OsString::from_wide(&buf[..n as usize]))
}

pub fn exe_dir() -> PathBuf {
    exe_path()
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."))
}

pub fn data_dir(root: &Path) -> PathBuf {
    let new = root.join(DATA_DIR);
    if new.is_dir() {
        new
    } else {
        root.to_path_buf()
    }
}

pub fn packs_dir(root: &Path) -> PathBuf {
    let new = root.join(DATA_DIR).join("packs");
    if new.is_dir() {
        new
    } else if root.join("PR2Packs").is_dir() {
        root.join("PR2Packs")
    } else {
        new
    }
}

pub fn fonts_dir(root: &Path) -> PathBuf {
    let new = root.join(DATA_DIR).join("fonts");
    if new.is_dir() {
        new
    } else if root.join("fonts").is_dir() {
        root.join("fonts")
    } else {
        new
    }
}

pub fn ui_dir(root: &Path) -> PathBuf {
    let new = root.join(DATA_DIR).join("ui");
    if new.is_dir() {
        new
    } else if root.join("ui").is_dir() {
        root.join("ui")
    } else {
        new
    }
}

pub fn log_dir(root: &Path) -> PathBuf {
    if root.join(DATA_DIR).is_dir() {
        let dir = root.join(DATA_DIR).join("logs");
        let _ = fs::create_dir_all(&dir);
        dir
    } else {
        root.to_path_buf()
    }
}

pub fn pack_dir(root: &Path) -> PathBuf {
    packs_dir(root)
}

pub fn pack_path(root: &Path, lang: &str) -> PathBuf {
    pack_dir(root).join(format!("{lang}.txt"))
}

pub fn override_path(root: &Path, lang: &str) -> PathBuf {
    pack_dir(root).join("overrides").join(format!("{lang}.txt"))
}

pub fn locale_path(root: &Path) -> PathBuf {
    pack_dir(root).join("locale.ini")
}

pub fn read_locale_language(root: &Path) -> Option<String> {
    let text = fs::read_to_string(locale_path(root)).ok()?;
    for line in text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("language") {
            let rest = rest.trim_start();
            if let Some(value) = rest.strip_prefix('=') {
                let value = value.trim();
                if !value.is_empty() {
                    return Some(value.to_string());
                }
            }
        }
    }
    None
}

pub fn write_locale_language(root: &Path, lang: &str) -> bool {
    let path = locale_path(root);
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let old = fs::read_to_string(&path).unwrap_or_default();
    let mut lines: Vec<String> = old.lines().map(str::to_string).collect();
    let mut replaced = false;
    for line in &mut lines {
        if line.trim_start().starts_with("language") {
            let rest = line.trim_start()["language".len()..].trim_start();
            if rest.starts_with('=') {
                *line = format!("language={lang}");
                replaced = true;
                break;
            }
        }
    }
    if !replaced {
        lines.push(format!("language={lang}"));
    }
    let mut out = lines.join("\n");
    out.push('\n');
    fs::write(path, out).is_ok()
}

pub fn pack_min_runtime(root: &Path, lang: &str) -> u32 {
    let path = pack_path(root, lang);
    let text = match fs::read_to_string(path) {
        Ok(v) => v,
        Err(_) => return 1,
    };
    let mut version = 1;
    for line in text.lines().take(64) {
        let line = line.trim_start();
        if let Some(rest) = line.strip_prefix("# pack-meta ") {
            if let Some(value) = rest.trim().strip_prefix("min_runtime=") {
                if let Ok(v) = value.trim().parse::<u32>() {
                    version = version.max(v);
                }
            }
        } else if !line.is_empty() && !line.starts_with('#') {
            break;
        }
    }
    version
}

pub fn pack_runtime_ok(root: &Path, lang: &str) -> bool {
    pack_min_runtime(root, lang) <= RUNTIME_VERSION
}

pub fn language_fonts_complete(root: &Path, lang: &str) -> bool {
    if lang.is_empty() {
        return false;
    }
    let dir = fonts_dir(root).join(lang);
    FONT_NAMES
        .iter()
        .all(|name| dir.join(name).is_file())
}

pub fn font_rel_dir(root: &Path, lang: &str) -> String {
    let new = root.join(DATA_DIR).join("fonts").join(lang);
    let old = root.join("fonts").join(lang);
    if new.is_dir() {
        format!("{}\\fonts\\{}", DATA_DIR, lang)
    } else if old.is_dir() {
        format!("fonts\\{}", lang)
    } else {
        format!("{}\\fonts\\{}", DATA_DIR, lang)
    }
}

pub fn valid_lang_code(s: &str) -> bool {
    if s.is_empty() || s.len() >= 64 || s == "." || s == ".." {
        return false;
    }
    s.bytes()
        .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

pub fn wide(s: &str) -> Vec<u16> {
    let mut out: Vec<u16> = s.encode_utf16().collect();
    out.push(0);
    out
}

pub fn path_string(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}
