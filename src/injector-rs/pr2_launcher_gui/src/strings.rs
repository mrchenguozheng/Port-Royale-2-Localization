use pr2_common::ui_dir;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

const BUILTIN: &[(&str, &str)] = &[
    ("title", "Port Royale 2 Localization"),
    ("subtitle", "Port Royale 2 localization runtime"),
    ("label.language", "Language pack:"),
    ("button.launch", "Launch localized"),
    ("button.vanilla", "Launch original"),
    ("button.refresh", "Refresh"),
    ("button.kill", "End game process"),
    ("status.count", "%d language pack(s)"),
    ("status.none", "No .txt in PR2Localization\\packs"),
    ("status.launched", "Localized game launched."),
    ("status.vanilla", "Original game launched."),
    ("status.killed", "Ended %d PR2.exe process(es)."),
    (
        "hint.footer",
        "Language packs live in PR2Localization\\packs.\nIf exit hangs, end PR2.exe here.",
    ),
    (
        "confirm.kill",
        "Force-end %d PR2.exe process(es) from this folder?\nUnsaved game progress will be lost.",
    ),
    ("error.no_launcher", "PR2Localization.exe not found in this folder."),
    ("error.no_language", "No language pack selected."),
    ("error.no_game", "No running PR2.exe from this folder was found."),
    ("error.launch_failed", "Failed to start PR2Localization.exe."),
    ("error.kill_failed", "Failed to end PR2.exe (error %lu)."),
    ("error.exit_code", "Launcher exit code %lu; the game did not start."),
    ("error.font_missing", "PR2Localization\\fonts\\ has no TTF fonts."),
    (
        "error.pack_too_new",
        "Language pack needs a newer launcher (runtime v%d, current v%d).",
    ),
];

pub enum Arg {
    Str(String),
    Num(u32),
}

pub struct Strings {
    values: HashMap<String, String>,
}

impl Strings {
    pub fn load(root: &Path, ui: &str) -> Self {
        let mut values = HashMap::new();
        let dir = ui_dir(root);
        read_ini(&dir.join(format!("{ui}.ini")), &mut values);
        if values.is_empty() && ui != "en" {
            read_ini(&dir.join("en.ini"), &mut values);
        }
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

#[cfg(test)]
mod tests {
    use super::*;

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
}
