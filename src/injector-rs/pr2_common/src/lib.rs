use std::collections::HashMap;
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
pub const FONT_MAP_FILE: &str = "font-map.ini";
pub const FONT_MAP_DEFAULT_FILE: &str = "font-map.default.ini";

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

/// `PR2Localization\fonts\font-map.ini`（旧布局为 `fonts\font-map.ini`）。
///
/// 配置按语言分段，`[fonts]` 是全局默认，`[zh]` / `[ja]` 覆盖它。
/// 值只写实际字体文件名，文件必须位于 `PR2Localization\fonts`；
/// 多个候选用 `|` 分隔，取第一个存在的文件。
///
/// 发行包只携带 `font-map.default.ini`。运行时优先读取用户可编辑的
/// `font-map.ini`；它不存在时才用默认文件，所以解压升级不会覆盖手工配置。
pub struct FontMap {
    entries: HashMap<String, Vec<String>>,
}

fn font_map_candidates(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let data = data_dir(root);
    let dirs = [data.join("fonts"), root.join("fonts"), data.clone()];
    // 任何位置的显式 font-map.ini 都优先于默认文件，避免旧布局的默认
    // 映射压过用户已经改过的配置。
    for name in [FONT_MAP_FILE, FONT_MAP_DEFAULT_FILE] {
        for dir in &dirs {
            let path = dir.join(name);
            if !out.iter().any(|p| p == &path) {
                out.push(path);
            }
        }
    }
    out
}

fn font_map_path(root: &Path) -> Option<PathBuf> {
    font_map_candidates(root)
        .into_iter()
        .find(|path| path.is_file())
}

fn expand_env(value: &str) -> String {
    let mut out = String::new();
    let mut rest = value;
    while let Some(start) = rest.find('%') {
        let Some(end_rel) = rest[start + 1..].find('%') else {
            break;
        };
        let end = start + 1 + end_rel;
        let name = &rest[start + 1..end];
        if name.is_empty() {
            out.push_str(&rest[..=start]);
            rest = &rest[start + 1..];
            continue;
        }
        if let Ok(replacement) = std::env::var(name) {
            out.push_str(&rest[..start]);
            out.push_str(&replacement);
            rest = &rest[end + 1..];
        } else {
            out.push_str(&rest[..=end]);
            rest = &rest[end + 1..];
        }
    }
    out.push_str(rest);
    out
}

fn normalize_font_key(value: &str) -> String {
    let mut name = value.trim();
    if let Some(pos) = name.rfind(|c| c == '\\' || c == '/') {
        name = &name[pos + 1..];
    }
    name.trim_matches('"').to_ascii_lowercase()
}

fn resolve_font_path(root: &Path, value: &str) -> Option<String> {
    let expanded = expand_env(value.trim().trim_matches('"'));
    if expanded.trim().is_empty() {
        return None;
    }
    // 不把 .ttc 集合或 -VF.ttf 可变字体交给游戏字体读取器：两者都未验证/不接受。
    let lower = expanded.to_ascii_lowercase();
    if lower.ends_with(".ttc") || lower.contains("-vf.ttf") {
        return None;
    }
    // 映射值只取文件名：实际字体必须位于 PR2Localization\fonts\，
    // 避免配置把游戏引到系统字体目录或字体目录之外。
    let file_name = Path::new(&expanded).file_name()?.to_string_lossy().into_owned();
    if file_name.trim().is_empty() {
        return None;
    }
    let path = fonts_dir(root).join(file_name);
    if path.is_file() {
        Some(path.to_string_lossy().into_owned())
    } else {
        None
    }
}

impl FontMap {
    pub fn load(root: &Path, lang: &str) -> Option<FontMap> {
        let path = font_map_path(root)?;
        let text = fs::read_to_string(path).ok()?;
        let lang = lang.to_ascii_lowercase();
        let mut global: HashMap<String, Vec<String>> = HashMap::new();
        let mut local: HashMap<String, Vec<String>> = HashMap::new();
        let mut section = "fonts".to_string();

        for raw in text.lines() {
            let line = raw.trim().trim_start_matches('\u{feff}');
            if line.is_empty() || line.starts_with(';') || line.starts_with('#') {
                continue;
            }
            if line.starts_with('[') && line.ends_with(']') {
                section = line[1..line.len() - 1].trim().to_ascii_lowercase();
                continue;
            }
            let Some((key, value)) = line.split_once('=') else {
                continue;
            };
            let key = normalize_font_key(key);
            if key.is_empty() {
                continue;
            }
            let values: Vec<String> = value
                .split('|')
                .map(|v| v.trim().trim_matches('"').to_string())
                .filter(|v| !v.is_empty())
                .collect();
            if values.is_empty() {
                continue;
            }
            if section == "fonts" || section == "font" {
                global.insert(key, values);
            } else if !lang.is_empty() && section == lang {
                local.insert(key, values);
            }
        }

        for (key, values) in local {
            global.insert(key, values);
        }
        // 在加载时一次性解析字体的存在性。运行时 lookup 位于文件 API hook 内，
        // 这里若再访问文件系统会重新进入 hook，导致递归崩溃。
        let mut entries: HashMap<String, Vec<String>> = HashMap::new();
        for (key, values) in global {
            let resolved: Vec<String> = values
                .iter()
                .filter_map(|value| resolve_font_path(root, value))
                .collect();
            if !resolved.is_empty() {
                entries.insert(key, resolved);
            }
        }
        if entries.is_empty() {
            return None;
        }
        Some(FontMap { entries })
    }

    /// 按游戏请求的文件名/路径取第一个实际存在的映射文件。
    pub fn lookup(&self, logical: &str) -> Option<String> {
        let key = normalize_font_key(logical);
        self.entries.get(&key)?.first().cloned()
    }

    pub fn has_all(&self) -> bool {
        FONT_NAMES.iter().all(|name| self.lookup(name).is_some())
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

pub fn bundled_fonts_complete(root: &Path, lang: &str) -> bool {
    if lang.is_empty() {
        return false;
    }
    FontMap::load(root, lang)
        .map(|map| map.has_all())
        .unwrap_or(false)
}

pub fn language_fonts_complete(root: &Path, lang: &str) -> bool {
    if lang.is_empty() {
        return false;
    }
    bundled_fonts_complete(root, lang)
}

pub fn font_rel_dir(root: &Path, _lang: &str) -> String {
    let new = root.join(DATA_DIR).join("fonts");
    let old = root.join("fonts");
    if new.is_dir() {
        format!("{}\\fonts", DATA_DIR)
    } else if old.is_dir() {
        "fonts".to_string()
    } else {
        format!("{}\\fonts", DATA_DIR)
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_root() -> PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("pr2-font-map-{stamp}"));
        fs::create_dir_all(root.join(DATA_DIR).join("fonts")).unwrap();
        root
    }

    #[test]
    fn font_map_parses_sections_and_resolves_paths() {
        let root = temp_root();
        let font = root.join(DATA_DIR).join("fonts").join("fake-cjk.ttf");
        fs::write(&font, b"fake").unwrap();
        let cfg = "[fonts]\nARIAL.TTF=fake-cjk.ttf\n[zh]\nELGRECO_.TTF=fake-cjk.ttf\nTiepolo_black.ttf=fake-cjk.ttf\nTiepolo_bold.ttf=fake-cjk.ttf\n";
        fs::write(
            root.join(DATA_DIR).join("fonts").join(FONT_MAP_FILE),
            cfg,
        )
        .unwrap();

        let map = FontMap::load(&root, "zh").unwrap();
        assert!(map.has_all());
        assert_eq!(
            map.lookup("fonts\\ELGRECO_.TTF").unwrap(),
            font.to_string_lossy()
        );
        assert!(language_fonts_complete(&root, "zh"));
        assert!(!language_fonts_complete(&root, "ja"));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn font_map_prefers_user_file_and_falls_back_to_default() {
        let root = temp_root();
        let fonts = root.join(DATA_DIR).join("fonts");
        let default_font = fonts.join("default-cjk.ttf");
        let user_font = fonts.join("user-cjk.ttf");
        fs::write(&default_font, b"fake").unwrap();
        fs::write(&user_font, b"fake").unwrap();

        let default_cfg = "[zh]\nARIAL.TTF=default-cjk.ttf\n";
        let default_path = fonts.join(FONT_MAP_DEFAULT_FILE);
        fs::write(&default_path, default_cfg).unwrap();

        // 没有用户文件时，回退到 font-map.default.ini。
        let map = FontMap::load(&root, "zh").unwrap();
        assert_eq!(
            map.lookup("fonts\\ARIAL.TTF").unwrap(),
            default_font.to_string_lossy()
        );

        // 用户 font-map.ini 存在时优先，默认文件不再决定映射。
        let user_cfg = "[zh]\nARIAL.TTF=user-cjk.ttf\n";
        fs::write(fonts.join(FONT_MAP_FILE), user_cfg).unwrap();
        let map = FontMap::load(&root, "zh").unwrap();
        assert_eq!(
            map.lookup("fonts\\ARIAL.TTF").unwrap(),
            user_font.to_string_lossy()
        );

        // 候选顺序必须保证任何位置的手工 font-map.ini 都在默认文件之前。
        let candidates = font_map_candidates(&root);
        assert_eq!(candidates[0], fonts.join(FONT_MAP_FILE));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn font_map_skips_ttc_candidates() {
        let root = temp_root();
        let collection = root.join(DATA_DIR).join("fonts").join("fake-cjk.ttc");
        fs::write(&collection, b"fake").unwrap();
        let cfg = "[zh]\nARIAL.TTF=fake-cjk.ttc\n";
        fs::write(
            root.join(DATA_DIR).join("fonts").join(FONT_MAP_FILE),
            cfg,
        )
        .unwrap();
        let map = FontMap::load(&root, "zh");
        assert!(map
            .map(|m| m.lookup("fonts\\ARIAL.TTF").is_none())
            .unwrap_or(true));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn font_map_skips_variable_fonts() {
        let root = temp_root();
        let variable = root.join(DATA_DIR).join("fonts").join("fake-cjk-VF.ttf");
        fs::write(&variable, b"fake").unwrap();
        let cfg = "[zh]\nARIAL.TTF=fake-cjk-VF.ttf\n";
        fs::write(
            root.join(DATA_DIR).join("fonts").join(FONT_MAP_FILE),
            cfg,
        )
        .unwrap();
        let map = FontMap::load(&root, "zh");
        assert!(map
            .map(|m| m.lookup("fonts\\ARIAL.TTF").is_none())
            .unwrap_or(true));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn font_map_rejects_fonts_outside_fonts_dir() {
        let root = temp_root();
        let outside = root.join("outside.ttf");
        fs::write(&outside, b"fake").unwrap();
        let cfg = format!("[zh]\nARIAL.TTF={}\n", outside.display());
        fs::write(
            root.join(DATA_DIR).join("fonts").join(FONT_MAP_FILE),
            cfg,
        )
        .unwrap();
        let map = FontMap::load(&root, "zh");
        assert!(map
            .map(|m| m.lookup("fonts\\ARIAL.TTF").is_none())
            .unwrap_or(true));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn actual_font_files_without_map_are_incomplete() {
        let root = temp_root();
        let fonts = root.join(DATA_DIR).join("fonts");
        for name in FONT_NAMES {
            fs::write(fonts.join(name), b"fake").unwrap();
        }
        assert!(!language_fonts_complete(&root, "zh"));
        let _ = fs::remove_dir_all(&root);
    }
}
