//! Steam 宿主 DLL：版别判断、状态查询与挂载脚本位置。
//!
//! 替换动作本身只有一份实现 —— 发行包里的 `PR2HostMount.ps1`（先校验原版
//! 大小/SHA-256、建两份备份、写 `.new` 校验后换名）。启动器和 GUI 只判断
//! 需不需要挂载，需要时去调那个脚本，不在这里重复实现一遍替换。

use std::fs;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

pub const HOST_DLL: &str = "Ascaron.Logging-2.6.dll";
pub const HOST_ORIG: &str = "Ascaron.Logging-2.6.orig.dll";
/// 发行包里的代理位置。不能放根目录，否则解压就覆盖掉游戏原版。
pub const HOST_PROXY_REL: &str = "PR2Localization/host/Ascaron.Logging-2.6.dll";
pub const HOST_BACKUP_REL: &str =
    "PR2Localization/host-backup/Ascaron.Logging-2.6.dll";
pub const HOST_MANIFEST_REL: &str = "PR2Localization/host-mount.json";
pub const HOST_MOUNT_SCRIPT: &str = "PR2HostMount.ps1";

/// Steam 英文 1.1.2.3 自带的 Ascaron.Logging-2.6.dll，必须大小和哈希同时对上。
pub const HOST_ORIGINAL_SIZE: u64 = 11776;
pub const HOST_ORIGINAL_SHA256: &str =
    "0568EC654E147B6D80F60B779843F020A9C8A7C4E53AE0BC364EC6937024D160";

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Edition {
    Gog,
    Steam,
}

/// 根目录宿主 DLL 的状态。`Mounted` 只表示「可以还原」，不代表代理内容正确。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum HostState {
    /// 根目录是 Steam 原版，还没挂载。
    Original,
    /// 根目录不是原版，但存在可验证的原版备份，能还原。
    Mounted,
    /// 根目录不是原版，也没有可验证的备份 —— 拒绝改动。
    Unknown,
    /// 根目录没有这个 DLL。
    Missing,
}

pub fn is_original_host(path: &Path) -> bool {
    let Ok(meta) = fs::metadata(path) else {
        return false;
    };
    if !meta.is_file() || meta.len() != HOST_ORIGINAL_SIZE {
        return false;
    }
    file_sha256_upper(path)
        .map(|sha| sha == HOST_ORIGINAL_SHA256)
        .unwrap_or(false)
}

fn file_sha256_upper(path: &Path) -> Option<String> {
    let data = fs::read(path).ok()?;
    let digest = Sha256::digest(&data);
    let mut out = String::with_capacity(64);
    for b in digest {
        out.push_str(&format!("{b:02X}"));
    }
    Some(out)
}

/// 发行包里代理的位置；旧包把代理放在根目录，这里保留回退。
pub fn host_proxy_path(root: &Path) -> PathBuf {
    let hosted = root.join(HOST_PROXY_REL);
    if hosted.is_file() {
        return hosted;
    }
    root.join(HOST_DLL)
}

pub fn host_state(root: &Path) -> HostState {
    let root_dll = root.join(HOST_DLL);
    if !root_dll.is_file() {
        return HostState::Missing;
    }
    if is_original_host(&root_dll) {
        return HostState::Original;
    }
    let orig = root.join(HOST_ORIG);
    let backup = root.join(HOST_BACKUP_REL);
    if is_original_host(&orig) || is_original_host(&backup) {
        HostState::Mounted
    } else {
        HostState::Unknown
    }
}

/// 判断是 Steam 还是 GOG。
///
/// 顺序：GOG 的 `goggame-*.info/.id/.script` 优先（法语 GOG 版也带同名宿主
/// DLL，不能按 DLL 存在与否猜）；然后是 Steam 的 `steam_appid.txt`；最后才是
/// 「根目录有宿主 DLL 就当 Steam」。两边都不像时按 GOG 处理，走注入启动。
pub fn detect_edition(root: &Path) -> Edition {
    if has_gog_marker(root) {
        return Edition::Gog;
    }
    if root.join("steam_appid.txt").is_file() {
        return Edition::Steam;
    }
    if root.join(HOST_DLL).is_file() {
        return Edition::Steam;
    }
    Edition::Gog
}

fn has_gog_marker(root: &Path) -> bool {
    let Ok(entries) = fs::read_dir(root) else {
        return false;
    };
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().to_lowercase();
        if name.starts_with("goggame-")
            && (name.ends_with(".info") || name.ends_with(".id")
                || name.ends_with(".script"))
        {
            return true;
        }
    }
    false
}

/// 发行包里的挂载脚本。放在游戏根目录。
pub fn host_script_path(root: &Path) -> PathBuf {
    root.join(HOST_MOUNT_SCRIPT)
}

/// `steam_appid.txt` 里的 appid，取不到返回 None。
pub fn steam_app_id(root: &Path) -> Option<String> {
    let text = fs::read_to_string(root.join("steam_appid.txt")).ok()?;
    let id = text.trim();
    if id.is_empty() || !id.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some(id.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "pr2-host-rs-{}-{}",
            tag,
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn detects_gog_by_marker_before_host_dll() {
        let dir = tmp("gog");
        fs::write(dir.join("goggame-1207659014.info"), b"x").unwrap();
        fs::write(dir.join(HOST_DLL), b"whatever").unwrap();
        assert_eq!(detect_edition(&dir), Edition::Gog);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn detects_steam_by_app_id() {
        let dir = tmp("steam");
        fs::write(dir.join("steam_appid.txt"), b"12470\n").unwrap();
        assert_eq!(detect_edition(&dir), Edition::Steam);
        assert_eq!(steam_app_id(&dir).as_deref(), Some("12470"));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn missing_host_is_missing_state() {
        let dir = tmp("missing");
        assert_eq!(host_state(&dir), HostState::Missing);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn unknown_host_without_backup_is_unknown() {
        let dir = tmp("unknown");
        fs::write(dir.join(HOST_DLL), b"not the original").unwrap();
        assert_eq!(host_state(&dir), HostState::Unknown);
        let _ = fs::remove_dir_all(&dir);
    }
}
