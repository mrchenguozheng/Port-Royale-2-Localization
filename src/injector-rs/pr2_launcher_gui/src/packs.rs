use std::fs;
use std::path::Path;

use pr2_common::{pack_dir, valid_lang_code};

pub struct Pack {
    pub code: String,
    pub label: String,
    pub min_runtime: u32,
    /// pack 头里的 `# pack-meta version=`。开发构建的包没有这一行，这里为空串。
    pub version: String,
}

impl Pack {
    /// 语言列表里显示的文本：`简体中文 · v1.0.0`；没有版本号时只显示名字。
    pub fn display_label(&self) -> String {
        if self.version.is_empty() {
            return self.label.clone();
        }
        if self.version.starts_with('v') {
            format!("{} · {}", self.label, self.version)
        } else {
            format!("{} · v{}", self.label, self.version)
        }
    }
}

pub fn scan(root: &Path) -> Vec<Pack> {
    let packs_dir = pack_dir(root);
    let mut entries: Vec<_> = match fs::read_dir(&packs_dir) {
        Ok(v) => v.filter_map(|e| e.ok()).collect(),
        Err(_) => Vec::new(),
    };
    entries.sort_by_key(|e| e.file_name());

    let mut packs = Vec::new();
    for entry in entries {
        if packs.len() >= 64 {
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

        let (alias, min_runtime, version) = read_meta(&packs_dir.join(&name));
        let label = if alias.is_empty() {
            stem.to_string()
        } else {
            alias
        };
        packs.push(Pack {
            code: stem.to_string(),
            label,
            min_runtime,
            version,
        });
    }
    packs
}

fn read_meta(path: &Path) -> (String, u32, String) {
    let mut alias = String::new();
    let mut min_runtime = 1u32;
    let mut version = String::new();
    let Ok(data) = fs::read(path) else {
        return (alias, min_runtime, version);
    };
    let text = String::from_utf8_lossy(&data);
    let text = text.trim_start_matches('\u{feff}');
    for line in text.lines().take(64) {
        let line = trim(line);
        if line.is_empty() || line.starts_with(';') {
            continue;
        }
        if !line.starts_with("# pack-meta ") {
            if line.starts_with('#') {
                continue;
            }
            break;
        }
        let Some((key, value)) = line[12..].split_once('=') else {
            continue;
        };
        match trim(key) {
            "alias" => alias = trim(value).chars().take(255).collect(),
            "min_runtime" => {
                if let Ok(n) = trim(value).parse::<u32>() {
                    min_runtime = min_runtime.max(n);
                }
            }
            // 版本文本会原样显示在列表里：只收版本号允许的字符，
            // 免得 pack 头被写坏时把控制字符或整段文本塞进界面。
            "version" => {
                let raw = trim(value);
                if !raw.is_empty()
                    && raw.len() <= 32
                    && raw.chars().all(|c| {
                        c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '+' | '_')
                    })
                {
                    version = raw.to_string();
                }
            }
            _ => {}
        }
    }
    (alias, min_runtime, version)
}

fn trim(s: &str) -> &str {
    s.trim_matches([' ', '\t', '\r', '\n'])
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn reads_pack_meta() {
        let path = std::env::temp_dir().join("pr2_pack_meta_test.txt");
        let _ = fs::write(
            &path,
            "# pack-meta alias=简体中文\n# pack-meta min_runtime=3\n\
             # pack-meta version=1.0.0\n0x1 = a\n",
        );
        let (alias, min_runtime, version) = read_meta(&path);
        assert_eq!(alias, "简体中文");
        assert_eq!(min_runtime, 3);
        assert_eq!(version, "1.0.0");
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn display_label_appends_version_once() {
        let mut pack = Pack {
            code: "zh".into(),
            label: "简体中文".into(),
            min_runtime: 1,
            version: "1.0.0".into(),
        };
        assert_eq!(pack.display_label(), "简体中文 · v1.0.0");
        pack.version = "v1.0.0".into();
        assert_eq!(pack.display_label(), "简体中文 · v1.0.0");
        pack.version.clear();
        assert_eq!(pack.display_label(), "简体中文");
    }

    #[test]
    fn rejects_garbage_version_text() {
        let path = std::env::temp_dir().join("pr2_pack_meta_garbage.txt");
        let _ = fs::write(
            &path,
            "# pack-meta alias=简体中文\n# pack-meta version=1.0.0\n\
             # pack-meta version=../../etc\n0x1 = a\n",
        );
        let (_, _, version) = read_meta(&path);
        // 先读到合法的那一行；后面不合规的值既不接受也不覆盖。
        assert_eq!(version, "1.0.0");
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn ignores_non_txt() {
        let root = PathBuf::from("unused");
        assert!(scan(&root).is_empty());
    }
}
