use std::fs;
use std::path::Path;

use pr2_common::valid_lang_code;

pub struct Pack {
    pub code: String,
    pub label: String,
    pub gui: String,
    pub min_runtime: u32,
}

pub fn scan(root: &Path) -> Vec<Pack> {
    let packs_dir = root.join("PR2Packs");
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

        let (alias, gui, min_runtime) = read_meta(&packs_dir.join(&name));
        let label = if alias.is_empty() {
            stem.to_string()
        } else {
            alias
        };
        packs.push(Pack {
            code: stem.to_string(),
            label,
            gui,
            min_runtime,
        });
    }
    packs
}

fn read_meta(path: &Path) -> (String, String, u32) {
    let mut alias = String::new();
    let mut gui = String::new();
    let mut min_runtime = 1u32;
    let Ok(data) = fs::read(path) else {
        return (alias, gui, min_runtime);
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
            "gui" => gui = trim(value).chars().take(15).collect(),
            "min_runtime" => {
                if let Ok(n) = trim(value).parse::<u32>() {
                    min_runtime = min_runtime.max(n);
                }
            }
            _ => {}
        }
    }
    (alias, gui, min_runtime)
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
            "# pack-meta alias=简体中文\n# pack-meta gui=zh\n# pack-meta min_runtime=3\n0x1 = a\n",
        );
        let (alias, gui, min_runtime) = read_meta(&path);
        assert_eq!(alias, "简体中文");
        assert_eq!(gui, "zh");
        assert_eq!(min_runtime, 3);
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn ignores_non_txt() {
        let root = PathBuf::from("unused");
        assert!(scan(&root).is_empty());
    }
}
