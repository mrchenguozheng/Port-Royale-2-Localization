use std::collections::{HashMap, HashSet};
use std::ffi::OsString;
use std::fs;
use std::os::windows::ffi::OsStringExt;
use std::path::{Path, PathBuf};

use windows_sys::Win32::System::LibraryLoader::GetModuleFileNameW;

mod host;
pub use host::*;

mod log_util;
pub use log_util::*;

/// 运行时契约版本。
///
/// v1：GOG 走远程注入、Steam 走宿主 DLL 挂载，两条启动路径。
/// v2：两版都走宿主 DLL 挂载；GOG 直启 `PR2.exe`，Steam 交给客户端（`steam://`），
/// 远程注入只在根目录没有宿主 DLL 时用。
/// 语言包的 `min_runtime` 只约束这个数字；从 v1 升到 v2 是因为启动契约变了，
/// 不是包格式变了（包头与正文格式都没动）。
pub const RUNTIME_VERSION: u32 = 2;

/// 发行版本号（如 `v1.0.0`），由构建脚本通过 `PR2_VERSION` 注入；开发构建为空串。
/// 语言包里的 `# pack-meta version=` 与它同源，都由 `release.ps1 -Version` 给。
pub const BUILD_VERSION: &str = env!("PR2_BUILD_VERSION");
/// 构建对应的短 commit；取不到时为空串。
pub const BUILD_COMMIT: &str = env!("PR2_BUILD_COMMIT");
/// `1` 表示构建时工作树有未提交改动。
pub const BUILD_DIRTY: &str = env!("PR2_BUILD_DIRTY");

/// 拼给玩家/排障看的版本标签：`v1.0.0 (c8aa6e3)`、`v1.0.0 (c8aa6e3+dirty)`、`dev`。
///
/// 纯函数，便于单测；真正的值从 [`BUILD_VERSION`] 等常量来。
pub fn format_build_label(version: &str, commit: &str, dirty: &str) -> String {
    let mut out = if version.is_empty() {
        "dev".to_string()
    } else if version.starts_with('v') {
        version.to_string()
    } else {
        format!("v{version}")
    };
    if !commit.is_empty() {
        let suffix = if dirty.is_empty() || dirty == "0" {
            commit.to_string()
        } else {
            format!("{commit}+dirty")
        };
        out.push_str(&format!(" ({suffix})"));
    }
    out
}

/// 当前进程的版本标签，GUI 副标题与 `--version` 共用。
pub fn build_label() -> String {
    format_build_label(BUILD_VERSION, BUILD_COMMIT, BUILD_DIRTY)
}
pub const DATA_DIR: &str = "PR2Localization";
pub const FONT_NAMES: [&str; 4] = [
    "ARIAL.TTF",
    "ELGRECO_.TTF",
    "Tiepolo_black.ttf",
    "Tiepolo_bold.ttf",
];
pub const FONT_MAP_FILE: &str = "font-map.ini";
pub const FONT_MAP_DEFAULT_FILE: &str = "font-map.default.ini";
pub const LOCALE_FILE: &str = "locale.ini";
pub const LOCALE_DEFAULT_FILE: &str = "locale.default.ini";
pub const UI_FILE: &str = "ui.ini";
pub const UI_DEFAULT_FILE: &str = "ui.default.ini";

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
/// 发行包只携带 `font-map.default.ini`。运行时先加载默认文件，再用用户可编辑的
/// `font-map.ini` **按项覆盖**：用户只写一个逻辑名时，其余逻辑名仍保留默认映射。
/// 要显式禁用某项，写 `ARIAL.TTF=none` 或 `ARIAL.TTF=-`。
pub struct FontMap {
    entries: HashMap<String, Vec<String>>,
    /// 四个逻辑名都被显式写成 none / -：该语言使用游戏根目录原版字体，
    /// 不重定向任何字体文件，也不算“字体缺失”。
    originals: bool,
}

fn font_map_dirs(root: &Path) -> [PathBuf; 3] {
    let data = data_dir(root);
    [data.join("fonts"), root.join("fonts"), data]
}

fn first_font_map(root: &Path, name: &str) -> Option<PathBuf> {
    font_map_dirs(root)
        .into_iter()
        .map(|dir| dir.join(name))
        .find(|path| path.is_file())
}

fn font_map_paths(root: &Path) -> Vec<PathBuf> {
    let default = first_font_map(root, FONT_MAP_DEFAULT_FILE);
    let user = first_font_map(root, FONT_MAP_FILE);
    let mut paths = Vec::new();
    if let Some(path) = default {
        paths.push(path);
    }
    if let Some(path) = user {
        if !paths.iter().any(|p| p == &path) {
            paths.push(path);
        }
    }
    paths
}

fn parse_font_map(
    text: &str,
    lang: &str,
) -> (HashMap<String, Vec<String>>, HashMap<String, Vec<String>>) {
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
    (global, local)
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

fn is_disabled_font(value: &str) -> bool {
    let lower = value.trim().trim_matches('"').to_ascii_lowercase();
    lower == "none" || lower == "-"
}

fn resolve_font_path(root: &Path, value: &str) -> Option<String> {
    let expanded = expand_env(value.trim().trim_matches('"'));
    if expanded.trim().is_empty() {
        return None;
    }
    // 显式禁用某一项；其余项仍可沿用默认映射。
    if is_disabled_font(&expanded) {
        return None;
    }
    // 不把 .ttc 集合或 -VF.ttf 可变字体交给游戏字体读取器：两者都未验证/不接受。
    let lower = expanded.to_ascii_lowercase();
    if lower.ends_with(".ttc") || lower.contains("-vf.ttf") {
        return None;
    }
    // 映射值只取文件名：实际字体必须位于 PR2Localization\fonts\，
    // 避免配置把游戏引到系统字体目录或字体目录之外。
    let file_name = Path::new(&expanded)
        .file_name()?
        .to_string_lossy()
        .into_owned();
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
        let paths = font_map_paths(root);
        if paths.is_empty() {
            return None;
        }
        let lang = lang.to_ascii_lowercase();
        let mut merged: HashMap<String, Vec<String>> = HashMap::new();

        // 顺序即优先级：默认全局 → 默认语言节 → 用户全局 → 用户语言节。
        for path in paths {
            let Ok(text) = fs::read_to_string(path) else {
                continue;
            };
            let (global, local) = parse_font_map(&text, &lang);
            for (key, values) in global {
                merged.insert(key, values);
            }
            for (key, values) in local {
                merged.insert(key, values);
            }
        }

        // 在加载时一次性解析字体的存在性。运行时 lookup 位于文件 API hook 内，
        // 这里若再访问文件系统会重新进入 hook，导致递归崩溃。
        let mut entries: HashMap<String, Vec<String>> = HashMap::new();
        let mut disabled: HashSet<String> = HashSet::new();
        for (key, values) in merged {
            let resolved: Vec<String> = values
                .iter()
                .filter_map(|value| resolve_font_path(root, value))
                .collect();
            if !resolved.is_empty() {
                entries.insert(key.clone(), resolved);
            } else if values.iter().all(|value| is_disabled_font(value)) {
                disabled.insert(key);
            }
        }
        if entries.is_empty() {
            let all_disabled = FONT_NAMES
                .iter()
                .all(|name| disabled.contains(&normalize_font_key(name)));
            if all_disabled {
                return Some(FontMap {
                    entries,
                    originals: true,
                });
            }
            return None;
        }
        Some(FontMap {
            entries,
            originals: false,
        })
    }

    /// 按游戏请求的文件名/路径取第一个实际存在的映射文件。
    pub fn lookup(&self, logical: &str) -> Option<String> {
        let key = normalize_font_key(logical);
        self.entries.get(&key)?.first().cloned()
    }

    pub fn has_all(&self) -> bool {
        self.originals || FONT_NAMES.iter().all(|name| self.lookup(name).is_some())
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
    pack_dir(root).join(LOCALE_FILE)
}

pub fn locale_default_path(root: &Path) -> PathBuf {
    pack_dir(root).join(LOCALE_DEFAULT_FILE)
}

pub fn read_locale_language(root: &Path) -> Option<String> {
    let user_path = locale_path(root);
    // 用户文件存在即优先；即使 language= 为空，也视为用户明确清空，
    // 不拿默认文件把它补回去。只有活动文件不存在时才回退默认文件。
    if user_path.is_file() {
        return read_language_file(&user_path);
    }
    read_language_file(&locale_default_path(root))
}

/// 解析一行 `language = 代码`。
///
/// 返回 `None` 表示不是 language 行；返回 `Some(None)` 表示是 language 行但值为空。
/// `=` 两侧允许空白，值后的 `;` / `#` 视为行内注释；这与 Python 端的
/// `pr2ctl.detect.read_ini_language()` 使用同一套规则。
fn language_line(line: &str) -> Option<Option<String>> {
    let trimmed = line.trim().trim_start_matches('\u{feff}');
    if trimmed.is_empty() || trimmed.starts_with(';') || trimmed.starts_with('#') {
        return None;
    }
    let (key, value) = trimmed.split_once('=')?;
    if !key.trim().eq_ignore_ascii_case("language") {
        return None;
    }
    let value = value
        .split(|c| c == ';' || c == '#')
        .next()
        .unwrap_or("")
        .trim();
    if value.is_empty() {
        Some(None)
    } else {
        Some(Some(value.to_string()))
    }
}

fn read_language_file(path: &Path) -> Option<String> {
    let text = fs::read_to_string(path).ok()?;
    for line in text.lines() {
        if let Some(value) = language_line(line) {
            return value;
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
    let lines: Vec<String> = old.lines().map(str::to_string).collect();
    let mut out_lines: Vec<String> = Vec::with_capacity(lines.len() + 1);
    let mut replaced = false;
    for line in lines {
        if language_line(&line).is_some() {
            if !replaced {
                out_lines.push(format!("language={lang}"));
                replaced = true;
            }
            // 旧版本可能留下两行 language；写回时只保留第一行。
            continue;
        }
        out_lines.push(line);
    }
    if !replaced {
        out_lines.push(format!("language={lang}"));
    }
    let mut out = out_lines.join("\n");
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

/// 语言包一行：`0x1234 = 文本`，也接受 `1234<TAB>文本`。
///
/// 注入器读主包和读 `packs/overrides/<lang>.txt` 都用这一份解析，格式只有一处。
pub fn parse_pack_line(s: &str) -> Option<(u32, &str)> {
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

    #[test]
    fn parses_pack_lines() {
        assert_eq!(parse_pack_line("0x1A2B = 文本"), Some((0x1A2B, "文本")));
        assert_eq!(parse_pack_line("  0X1a2b=文本"), Some((0x1A2B, "文本")));
        // 老格式：十六进制紧接制表符，没有 0x 前缀。
        assert_eq!(parse_pack_line("1a2b\t文本"), Some((0x1A2B, "文本")));
        assert_eq!(parse_pack_line("0x = 空键"), None);
        assert_eq!(parse_pack_line("这不是一行"), None);
    }

    #[test]
    fn build_label_reports_version_and_commit() {
        // 开发构建：没有注入版本时显示 dev，而不是一个看起来像发行版的假版本号。
        assert_eq!(format_build_label("", "", ""), "dev");
        assert_eq!(format_build_label("v1.0.0", "", ""), "v1.0.0");
        // 写进 pack 头的是不带 v 的 1.0.0；两处都要显示成 v1.0.0。
        assert_eq!(format_build_label("1.0.0", "c8aa6e3", ""), "v1.0.0 (c8aa6e3)");
        assert_eq!(
            format_build_label("v1.0.0", "c8aa6e3", "1"),
            "v1.0.0 (c8aa6e3+dirty)"
        );
        assert_eq!(format_build_label("", "c8aa6e3", "0"), "dev (c8aa6e3)");
    }

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
        fs::write(root.join(DATA_DIR).join("fonts").join(FONT_MAP_FILE), cfg).unwrap();

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
    fn locale_prefers_user_file_and_falls_back_to_default() {
        let root = temp_root();
        let packs = root.join(DATA_DIR).join("packs");
        fs::create_dir_all(&packs).unwrap();
        let default_path = packs.join(LOCALE_DEFAULT_FILE);
        let user_path = packs.join(LOCALE_FILE);
        fs::write(&default_path, "language=zh\n").unwrap();

        assert_eq!(read_locale_language(&root).as_deref(), Some("zh"));

        fs::write(&user_path, "language=\n").unwrap();
        assert_eq!(read_locale_language(&root), None);

        fs::write(&user_path, "language=ja\n").unwrap();
        assert_eq!(read_locale_language(&root).as_deref(), Some("ja"));

        let _ = fs::remove_file(&user_path);
        assert_eq!(read_locale_language(&root).as_deref(), Some("zh"));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn locale_accepts_spaces_and_writes_single_line() {
        let root = temp_root();
        let packs = root.join(DATA_DIR).join("packs");
        fs::create_dir_all(&packs).unwrap();
        let path = packs.join(LOCALE_FILE);
        fs::write(&path, "# keep\nlanguage = ja ; selected in launcher\n").unwrap();

        assert_eq!(read_locale_language(&root).as_deref(), Some("ja"));
        assert!(write_locale_language(&root, "ko"));
        let text = fs::read_to_string(&path).unwrap();
        assert_eq!(text, "# keep\nlanguage=ko\n");
    }

    #[test]
    fn locale_writer_appends_when_key_is_absent() {
        let root = temp_root();
        let packs = root.join(DATA_DIR).join("packs");
        fs::create_dir_all(&packs).unwrap();
        let path = packs.join(LOCALE_FILE);
        fs::write(&path, "other=1\n").unwrap();

        assert!(write_locale_language(&root, "ja"));
        assert_eq!(fs::read_to_string(&path).unwrap(), "other=1\nlanguage=ja\n");
    }

    #[test]
    fn locale_writer_removes_duplicate_language_lines() {
        let root = temp_root();
        let packs = root.join(DATA_DIR).join("packs");
        fs::create_dir_all(&packs).unwrap();
        let path = packs.join(LOCALE_FILE);
        fs::write(&path, "language=ja\nlanguage = zh\nother=1\n").unwrap();

        assert!(write_locale_language(&root, "ko"));
        assert_eq!(
            fs::read_to_string(&path).unwrap(),
            "language=ko\nother=1\n"
        );
    }

    #[test]
    fn font_map_prefers_user_file_and_falls_back_to_default() {
        let root = temp_root();
        let fonts = root.join(DATA_DIR).join("fonts");
        let default_font = fonts.join("default-cjk.ttf");
        let user_font = fonts.join("user-cjk.ttf");
        fs::write(&default_font, b"fake").unwrap();
        fs::write(&user_font, b"fake").unwrap();

        let default_cfg = "[zh]\nARIAL.TTF=default-cjk.ttf\nELGRECO_.TTF=default-cjk.ttf\nTiepolo_black.ttf=default-cjk.ttf\nTiepolo_bold.ttf=default-cjk.ttf\n";
        let default_path = fonts.join(FONT_MAP_DEFAULT_FILE);
        fs::write(&default_path, default_cfg).unwrap();

        // 没有用户文件时，使用默认文件。
        let map = FontMap::load(&root, "zh").unwrap();
        assert_eq!(
            map.lookup("fonts\\ARIAL.TTF").unwrap(),
            default_font.to_string_lossy()
        );

        // 用户只覆盖一个逻辑名，其余三个仍沿用默认文件。
        let user_cfg = "[zh]\nARIAL.TTF=user-cjk.ttf\n";
        fs::write(fonts.join(FONT_MAP_FILE), user_cfg).unwrap();
        let map = FontMap::load(&root, "zh").unwrap();
        assert_eq!(
            map.lookup("fonts\\ARIAL.TTF").unwrap(),
            user_font.to_string_lossy()
        );
        assert_eq!(
            map.lookup("fonts\\ELGRECO_.TTF").unwrap(),
            default_font.to_string_lossy()
        );
        assert!(map.has_all());

        // 默认文件在前，用户文件在后。
        let paths = font_map_paths(&root);
        assert_eq!(paths[0], default_path);
        assert_eq!(paths[1], fonts.join(FONT_MAP_FILE));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn font_map_all_none_means_original_fonts_are_complete() {
        let root = temp_root();
        let fonts = root.join(DATA_DIR).join("fonts");
        fs::write(
            fonts.join(FONT_MAP_DEFAULT_FILE),
            "[es]\nARIAL.TTF=none\nELGRECO_.TTF=-\nTiepolo_black.ttf=none\nTiepolo_bold.ttf=none\n",
        )
        .unwrap();

        let map = FontMap::load(&root, "es").unwrap();
        assert!(map.has_all());
        assert!(map.lookup("fonts\\ARIAL.TTF").is_none());
        assert!(language_fonts_complete(&root, "es"));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn font_map_user_none_disables_only_that_slot() {
        let root = temp_root();
        let fonts = root.join(DATA_DIR).join("fonts");
        let font = fonts.join("default-cjk.ttf");
        fs::write(&font, b"fake").unwrap();
        let default_cfg = "[zh]\nARIAL.TTF=default-cjk.ttf\nELGRECO_.TTF=default-cjk.ttf\nTiepolo_black.ttf=default-cjk.ttf\nTiepolo_bold.ttf=default-cjk.ttf\n";
        fs::write(fonts.join(FONT_MAP_DEFAULT_FILE), default_cfg).unwrap();
        fs::write(fonts.join(FONT_MAP_FILE), "[zh]\nARIAL.TTF=none\n").unwrap();

        let map = FontMap::load(&root, "zh").unwrap();
        assert!(map.lookup("fonts\\ARIAL.TTF").is_none());
        assert_eq!(
            map.lookup("fonts\\ELGRECO_.TTF").unwrap(),
            font.to_string_lossy()
        );
        assert!(!map.has_all());
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn font_map_skips_ttc_candidates() {
        let root = temp_root();
        let collection = root.join(DATA_DIR).join("fonts").join("fake-cjk.ttc");
        fs::write(&collection, b"fake").unwrap();
        let cfg = "[zh]\nARIAL.TTF=fake-cjk.ttc\n";
        fs::write(root.join(DATA_DIR).join("fonts").join(FONT_MAP_FILE), cfg).unwrap();
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
        fs::write(root.join(DATA_DIR).join("fonts").join(FONT_MAP_FILE), cfg).unwrap();
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
        fs::write(root.join(DATA_DIR).join("fonts").join(FONT_MAP_FILE), cfg).unwrap();
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
