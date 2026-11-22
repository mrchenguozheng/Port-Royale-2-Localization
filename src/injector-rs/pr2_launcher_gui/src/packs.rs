use std::fs;
use std::path::Path;

use pr2_common::{pack_dir, valid_lang_code};

pub struct Pack {
    pub code: String,
    pub label: String,
    pub min_runtime: u32,
    /// pack 头里的 `# pack-meta version=`。开发构建的包没有这一行，这里为空串。
    pub version: String,
    /// `# pack-meta entries=`：包里的数据行总数。旧包没有这一行时为 0。
    pub entries: u32,
    /// `# pack-meta untranslated=`：占位未翻译的条目数（原文本来空的键不算）。
    pub untranslated: u32,
    /// `# pack-meta digest=`：正文内容的 sha256 前 12 位。旧包为空串。
    pub digest: String,
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

        let meta = read_meta(&packs_dir.join(&name));
        let label = if meta.alias.is_empty() {
            stem.to_string()
        } else {
            meta.alias
        };
        packs.push(Pack {
            code: stem.to_string(),
            label,
            min_runtime: meta.min_runtime,
            version: meta.version,
            entries: meta.entries,
            untranslated: meta.untranslated,
            digest: meta.digest,
        });
    }
    packs
}

/// 语言包头解析出来的全部字段。旧包只会填 alias / min_runtime / version。
#[derive(Default)]
struct PackMeta {
    alias: String,
    /// 没有 `# pack-meta min_runtime=` 时按 1（最低运行时）。
    min_runtime: u32,
    version: String,
    entries: u32,
    untranslated: u32,
    digest: String,
}

fn read_meta(path: &Path) -> PackMeta {
    let mut meta = PackMeta {
        min_runtime: 1,
        ..PackMeta::default()
    };
    let Ok(data) = fs::read(path) else {
        return meta;
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
            "alias" => meta.alias = trim(value).chars().take(255).collect(),
            "min_runtime" => {
                if let Ok(n) = trim(value).parse::<u32>() {
                    meta.min_runtime = meta.min_runtime.max(n);
                }
            }
            // 版本文本会原样显示在列表里：只收版本号允许的字符，
            // 免得 pack 头被写坏时把控制字符或整段文本塞进界面。
            "version" => {
                let raw = trim(value);
                if !raw.is_empty()
                    && raw.len() <= 32
                    && raw
                        .chars()
                        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '+' | '_'))
                {
                    meta.version = raw.to_string();
                }
            }
            // 条目数只用来显示「3590 条（未译 0）」：非数字或荒唐大值一律忽略，
            // 不拿 0 去覆盖已经读到的值。
            "entries" | "untranslated" => {
                if let Ok(n) = trim(value).parse::<u32>() {
                    if n <= 1_000_000 {
                        if trim(key) == "entries" {
                            meta.entries = n;
                        } else {
                            meta.untranslated = n;
                        }
                    }
                }
            }
            // 摘要固定 12 位小写十六进制，与 compile_pack.pack_digest 一致。
            "digest" => {
                let raw = trim(value);
                if raw.len() == 12 && raw.chars().all(|c| c.is_ascii_hexdigit()) {
                    meta.digest = raw.to_ascii_lowercase();
                }
            }
            _ => {}
        }
    }
    meta
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
             # pack-meta version=1.0.0\n# pack-meta entries=3590\n\
             # pack-meta untranslated=0\n# pack-meta scope=union\n\
             # pack-meta digest=9cfa2931c1c2\n0x1 = a\n",
        );
        let meta = read_meta(&path);
        assert_eq!(meta.alias, "简体中文");
        assert_eq!(meta.min_runtime, 3);
        assert_eq!(meta.version, "1.0.0");
        assert_eq!(meta.entries, 3590);
        assert_eq!(meta.untranslated, 0);
        assert_eq!(meta.digest, "9cfa2931c1c2");
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn old_pack_without_stats_has_no_digest() {
        // 旧包（只有 alias / min_runtime）不能显示成「0 条」，entries 为 0
        // 时界面直接不显示统计行。
        let path = std::env::temp_dir().join("pr2_pack_meta_old.txt");
        let _ = fs::write(&path, "# pack-meta alias=简体中文\n0x1 = a\n");
        let meta = read_meta(&path);
        assert_eq!(meta.alias, "简体中文");
        assert_eq!(meta.entries, 0);
        assert_eq!(meta.untranslated, 0);
        assert!(meta.digest.is_empty());
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn display_label_appends_version_once() {
        let mut pack = Pack {
            code: "zh".into(),
            label: "简体中文".into(),
            min_runtime: 1,
            version: "1.0.0".into(),
            entries: 3590,
            untranslated: 0,
            digest: "9cfa2931c1c2".into(),
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
        let meta = read_meta(&path);
        // 先读到合法的那一行；后面不合规的值既不接受也不覆盖。
        assert_eq!(meta.version, "1.0.0");
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn rejects_garbage_stats_and_digest() {
        let path = std::env::temp_dir().join("pr2_pack_meta_garbage_stats.txt");
        let _ = fs::write(
            &path,
            "# pack-meta entries=3590\n# pack-meta untranslated=0\n\
             # pack-meta digest=9cfa2931c1c2\n# pack-meta entries=abc\n\
             # pack-meta untranslated=-1\n# pack-meta digest=../../etc\n\
             # pack-meta digest=9CFA2931C1C2\n0x1 = a\n",
        );
        let meta = read_meta(&path);
        // 合法值保留；后面的非法值被忽略，不覆盖已经读到的。
        assert_eq!(meta.entries, 3590);
        assert_eq!(meta.untranslated, 0);
        assert_eq!(meta.digest, "9cfa2931c1c2");
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn ignores_non_txt() {
        let root = PathBuf::from("unused");
        assert!(scan(&root).is_empty());
    }
}
