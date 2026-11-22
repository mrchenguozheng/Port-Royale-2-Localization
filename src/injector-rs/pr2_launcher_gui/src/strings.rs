use pr2_common::{ui_dir, UI_DEFAULT_FILE, UI_FILE};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

const BUILTIN: &[(&str, &str)] = &[
    ("title", "Port Royale 2 Localization"),
    ("subtitle", "Port Royale 2 localization runtime"),
    // %d 运行时版本、%s 发行版本标签（v1.0.0 (c8aa6e3) 或 dev）。
    (
        "subtitle.version",
        "Port Royale 2 localization runtime v%d · %s",
    ),
    ("label.language", "Language pack:"),
    ("button.launch", "Launch localized"),
    ("button.vanilla", "Launch original"),
    ("button.restore", "Restore original"),
    ("button.refresh", "Refresh"),
    ("button.kill", "End game process"),
    ("status.count", "%d language pack(s)"),
    ("status.count_pack", "%d language pack(s) · current %s"),
    // %d 条目数、%d 未译条目数；没有 digest 的旧包用这一条。
    ("status.pack_stats", "%d entries · %d untranslated"),
    // 再加 %s 内容摘要（12 位），用来判断两份包是不是逐字相同。
    (
        "status.pack_detail",
        "%d entries · %d untranslated · digest %s",
    ),
    ("status.none", "No .txt in PR2Localization\\packs"),
    ("status.launched", "Localized game launched."),
    ("status.vanilla", "Original game launched."),
    (
        "status.restored",
        "Restored the original host DLL and fonts.",
    ),
    ("status.killed", "Ended %d PR2.exe process(es)."),
    (
        "confirm.restore",
        "Restore the original host DLL and original fonts?\n\
         The game will start in English until you launch localized again.",
    ),
    (
        "hint.footer",
        "Language packs live in PR2Localization\\packs.\nIf exit hangs, end PR2.exe here.",
    ),
    (
        "confirm.kill",
        "Force-end %d PR2.exe process(es) from this folder?\nUnsaved game progress will be lost.",
    ),
    (
        "error.no_launcher",
        "PR2Localization.exe not found in this folder.",
    ),
    ("error.no_language", "No language pack selected."),
    (
        "error.no_game",
        "No running PR2.exe from this folder was found.",
    ),
    (
        "error.launch_failed",
        "Failed to start PR2Localization.exe.",
    ),
    ("error.kill_failed", "Failed to end PR2.exe (error %lu)."),
    (
        "error.exit_code",
        "Launcher exit code %lu; the game did not start.",
    ),
    (
        "error.font_missing",
        "PR2Localization\\fonts\\ has no TTF fonts.",
    ),
    (
        "error.pack_too_new",
        "Language pack needs a newer launcher (runtime v%d, current v%d).",
    ),
    (
        "error.restore_failed",
        "Restore failed (exit code %lu).\n%s",
    ),
];

pub enum Arg {
    /// `%s`：用来把落盘日志的末尾几行带进对话框。
    Str(String),
    Num(u32),
}

pub struct Strings {
    values: HashMap<String, String>,
}

impl Strings {
    pub fn load(root: &Path) -> Self {
        let mut values = HashMap::new();
        let dir = ui_dir(root);
        // 包内只有一份按发包语言选好的 ui.default.ini；用户把要改的项抄进 ui.ini
        // 即可按项覆盖，不需要整份替换，升级也不会覆盖用户文件。
        let has_default = read_ini(&dir.join(UI_DEFAULT_FILE), &mut values);
        if !has_default {
            // 兼容仍带旧 en.ini 的安装目录；新包不再生成多语言 UI 文件。
            read_ini(&dir.join("en.ini"), &mut values);
        }
        read_ini(&dir.join(UI_FILE), &mut values);
        Self { values }
    }

    pub fn t(&self, key: &str) -> String {
        if let Some(value) = self.values.get(key) {
            return value.clone();
        }
        for (name, value) in BUILTIN {
            if *name == key {
                return value.to_string();
            }
        }
        key.to_string()
    }

    pub fn tf(&self, key: &str, args: &[Arg]) -> String {
        let fmt = self.t(key);
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
}

fn read_ini(path: &Path, out: &mut HashMap<String, String>) -> bool {
    let data = match fs::read(path) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let text = String::from_utf8_lossy(&data);
    let text = text.trim_start_matches('\u{feff}');
    for raw in text.lines() {
        let line = trim(raw);
        if line.is_empty()
            || line.starts_with('#')
            || line.starts_with(';')
            || line.starts_with('[')
        {
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
    true
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_root() -> std::path::PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("pr2-ui-strings-{stamp}"));
        fs::create_dir_all(pr2_common::ui_dir(&root)).unwrap();
        root
    }

    #[test]
    fn formats_numbers_and_strings() {
        let s = Strings {
            values: HashMap::from([("k".to_string(), "%d/%s/%lu".to_string())]),
        };
        assert_eq!(
            s.tf("k", &[Arg::Num(3), Arg::Str("zh".into()), Arg::Num(9)]),
            "3/zh/9"
        );
    }

    #[test]
    fn unescapes_newlines() {
        assert_eq!(unescape("a\\nb"), "a\nb");
    }

    #[test]
    fn default_ui_keeps_restore_format_placeholders() {
        // 简体中文是唯一来源（ui.zh.ini）；运行时默认文件由构建脚本从它生成。
        // 还原失败的弹框要把退出码和落盘日志末尾都填进去。
        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../ui/ui.zh.ini");
        let mut values = HashMap::new();
        assert!(read_ini(&path, &mut values), "读不到 {}", path.display());
        let strings = Strings { values };
        let text = strings.tf(
            "error.restore_failed",
            &[Arg::Num(2), Arg::Str("a\nb".into())],
        );
        assert!(text.starts_with("还原失败（退出码 2）"), "{text}");
        assert!(text.ends_with("a\nb"), "{text}");
    }

    #[test]
    fn user_file_overrides_selected_keys() {
        let root = temp_root();
        let dir = pr2_common::ui_dir(&root);
        fs::write(
            dir.join("ui.default.ini"),
            "[gui]\ntitle=默认标题\nbutton.launch=启动\n",
        )
        .unwrap();
        fs::write(dir.join("ui.ini"), "[gui]\ntitle=我的标题\n").unwrap();

        let strings = Strings::load(&root);
        assert_eq!(strings.t("title"), "我的标题");
        assert_eq!(strings.t("button.launch"), "启动");
        assert_eq!(strings.t("subtitle"), "Port Royale 2 localization runtime");
        let _ = fs::remove_dir_all(&root);
    }
}
