//! 日志落盘的体积上限与开发开关。
//!
//! 所有运行日志都按「打开时检查一次体积」处理：超过上限就把上一份滚成
//! `<name>.1`（同目录，只留一份旧档），再从空文件续写。这样单份文件最多是
//! 上限的两倍，不会像法语目录的 `vtable.log` 那样无上限 append 攒到 314 MB。
//!
//! `vtable.log`（槽位扫描）与 `resolve.log`（`[R]` / `[RGAP]`）是开发诊断，
//! 默认不写，只有进程环境里有 `PR2_LOG_DEBUG=1` 时才落盘。

use std::fs::{self, File, OpenOptions};
use std::path::{Path, PathBuf};

/// 单份日志的默认上限：1 MiB。超过就把旧文件滚成 `.1` 再写新的。
pub const DEFAULT_MAX_BYTES: u64 = 1 << 20;

/// 滚动旧档的后缀；只保留一份，不按序号堆叠。
pub const ROTATED_SUFFIX: &str = ".1";

/// 开发诊断日志是否开启（`PR2_LOG_DEBUG=1`，`0` 与空串视为关闭）。
pub fn debug_log_enabled() -> bool {
    match std::env::var("PR2_LOG_DEBUG") {
        Ok(value) => {
            let value = value.trim();
            !value.is_empty() && value != "0"
        }
        Err(_) => false,
    }
}

/// 打开一份 append 日志；文件已超过 `max_bytes` 时先滚成 `<name>.1`。
pub fn open_append_capped(path: &Path, max_bytes: u64) -> Option<File> {
    rotate_if_oversized(path, max_bytes);
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .ok()
}

/// 打开一份「每次启动重写」的日志；单次内容由调用方自己限额。
pub fn open_truncate(path: &Path) -> Option<File> {
    OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(path)
        .ok()
}

/// 超限时把文件改名成 `<name>.1`（旧的 `.1` 先删）。返回是否真的滚了。
pub fn rotate_if_oversized(path: &Path, max_bytes: u64) -> bool {
    let Ok(meta) = fs::metadata(path) else {
        return false;
    };
    if meta.len() < max_bytes {
        return false;
    }
    let rotated = rotated_path(path);
    let _ = fs::remove_file(&rotated);
    fs::rename(path, &rotated).is_ok()
}

/// `<name>` 对应的旧档路径 `<name>.1`。
pub fn rotated_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(ROTATED_SUFFIX);
    PathBuf::from(name)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn scratch_dir(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "pr2-log-util-{tag}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn rotates_once_past_the_cap() {
        let dir = scratch_dir("rotate");
        let path = dir.join("vtable.log");
        let mut f = open_append_capped(&path, 4).unwrap();
        f.write_all(b"12345678").unwrap();
        drop(f);

        assert!(rotate_if_oversized(&path, 4));
        assert!(!path.exists());
        assert_eq!(fs::read(rotated_path(&path)).unwrap(), b"12345678");
        // 只留一份旧档：再滚一次时旧 .1 被覆盖，不会出现 .2。
        fs::write(&path, b"abcdefgh").unwrap();
        assert!(rotate_if_oversized(&path, 4));
        assert_eq!(fs::read(rotated_path(&path)).unwrap(), b"abcdefgh");
        assert!(!rotated_path(&path).with_extension("log.2").exists());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn keeps_small_file_untouched() {
        let dir = scratch_dir("keep");
        let path = dir.join("runtime.log");
        fs::write(&path, b"abc").unwrap();
        assert!(!rotate_if_oversized(&path, 4));
        assert_eq!(fs::read(&path).unwrap(), b"abc");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn append_keeps_old_content_when_under_cap() {
        let dir = scratch_dir("append");
        let path = dir.join("proxy.log");
        let mut f = open_append_capped(&path, 1024).unwrap();
        f.write_all(b"first\n").unwrap();
        drop(f);
        let mut f = open_append_capped(&path, 1024).unwrap();
        f.write_all(b"second\n").unwrap();
        drop(f);
        assert_eq!(fs::read(&path).unwrap(), b"first\nsecond\n");
        let _ = fs::remove_dir_all(&dir);
    }
}
