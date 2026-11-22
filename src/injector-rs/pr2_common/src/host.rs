//! 宿主 DLL：版别判断、状态查询与挂载脚本位置。
//!
//! GOG 与 Steam 的 `PR2.exe` 都静态导入同目录的 `Ascaron.Logging-2.6.dll`
//! （导入表里只有 `Log` 一个函数），两版的原版 DLL 也是同一份字节。所以两版
//! 走同一条启动路径：先挂载宿主代理，再直启 `PR2.exe`，由代理去加载 Core。
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

/// 原版 `Ascaron.Logging-2.6.dll`，必须大小和哈希同时对上。
///
/// 三份实测样本逐字节相同：Steam 英文 1.1.2.3、GOG 英文 1.1.2.3、
/// GOG 法语 1.1.2.42。所以一份常量覆盖两版，不需要按版别维护指纹表。
pub const HOST_ORIGINAL_SIZE: u64 = 11776;
pub const HOST_ORIGINAL_SHA256: &str =
    "0568EC654E147B6D80F60B779843F020A9C8A7C4E53AE0BC364EC6937024D160";

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Edition {
    Gog,
    Steam,
}

/// 根目录宿主 DLL 的状态。
///
/// ``Mounted`` 要求两件事同时成立：根目录 DLL 确实是本工具的代理（SHA 与
/// 包内代理或挂载清单一致），并且存在一份可验证的原版备份。只看备份是不够的 ——
/// 根目录被别的 mod 换掉、但备份还在时，那不是"可还原"，而是"不知道这是什么"。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum HostState {
    /// 根目录是 Steam 原版，还没挂载。
    Original,
    /// 根目录是本工具代理，且有可验证的原版备份，能还原。
    Mounted,
    /// 根目录是本工具代理，但原版备份缺失或不可验证 —— 没有东西可还原。
    ProxyNoBackup,
    /// 根目录既不是原版，也不是本工具代理 —— 拒绝改动。
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

/// 包内代理的 SHA-256。
///
/// 只认 ``PR2Localization\host\``，**不回退到根目录**：代理回退路径是给挂载
/// 动作找源文件用的，拿来算校验值等于让根目录自己跟自己比，永远"一致"。
pub fn proxy_sha256(root: &Path) -> Option<String> {
    file_sha256_upper(&root.join(HOST_PROXY_REL))
}

/// 挂载清单里记录的代理 SHA-256（`PR2Localization\host-mount.json`）。
///
/// 只取这一个字段，不引 JSON 解析：清单由挂载脚本写、格式固定，读坏了返回 None。
pub fn manifest_proxy_sha(root: &Path) -> Option<String> {
    let text = fs::read_to_string(root.join(HOST_MANIFEST_REL)).ok()?;
    let key = "\"proxy_sha256\"";
    let rest = &text[text.find(key)? + key.len()..];
    let rest = rest.trim_start().strip_prefix(':')?.trim_start();
    let rest = rest.strip_prefix('"')?;
    let value = rest[..rest.find('"')?].trim().to_uppercase();
    if value.len() == 64 && value.chars().all(|c| c.is_ascii_hexdigit()) {
        Some(value)
    } else {
        None
    }
}

/// 根目录 DLL 是不是本工具代理：与包内代理一致，或与挂载清单记录的一致。
fn is_agent_proxy(root: &Path, root_dll: &Path) -> bool {
    let Some(root_sha) = file_sha256_upper(root_dll) else {
        return false;
    };
    if proxy_sha256(root).map(|sha| sha == root_sha).unwrap_or(false) {
        return true;
    }
    manifest_proxy_sha(root).map(|sha| sha == root_sha).unwrap_or(false)
}

/// 非原版的两个维度：有没有可验证的原版备份、根目录是不是本工具代理。
fn classify_non_original(has_original_backup: bool, is_agent_proxy: bool) -> HostState {
    match (is_agent_proxy, has_original_backup) {
        (true, true) => HostState::Mounted,
        (true, false) => HostState::ProxyNoBackup,
        (false, _) => HostState::Unknown,
    }
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
    // 两份备份任一有效都算有得还原：PS1 的还原分支也是这么回退的。
    let has_backup = is_original_host(&orig) || is_original_host(&backup);
    classify_non_original(has_backup, is_agent_proxy(root, &root_dll))
}

/// 判断是 Steam 还是 GOG。
///
/// 只用来说明「这是哪个发行版」，**不决定启动路径**：两版都走宿主挂载，
/// 能不能挂只看根目录有没有宿主 DLL（`has_host_dll`）。
///
/// 顺序：GOG 的 `goggame-*.info/.id/.script` 优先（法语 GOG 版也带同名宿主
/// DLL，不能按 DLL 存在与否猜）；然后是 Steam 的 `steam_appid.txt`；最后才是
/// 「根目录有宿主 DLL 就当 Steam」。两边都不像时按 GOG 处理。
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

/// 根目录有没有宿主 DLL。有就能挂载直启；没有只能退回注入。
///
/// 这是两版共用的唯一判据：`detect_edition` 只决定显示哪个版别名。
pub fn has_host_dll(root: &Path) -> bool {
    root.join(HOST_DLL).is_file()
}

/// 代理自己写的启动日志，在 `PR2Localization\logs\` 下。
pub const PROXY_LOG_FILE: &str = "proxy.log";

/// 代理进到 `PR2.exe` 进程后写的第一行。
///
/// 这是「挂载到底生效没有」的唯一运行时证据：静态导入表只能证明「应该会加载」，
/// 这行才能证明「这一次真的加载了」。
pub const PROXY_LOADED_MARKER: &str = "[host] DllMain loaded";

pub fn proxy_log_path(root: &Path) -> PathBuf {
    crate::log_dir(root).join(PROXY_LOG_FILE)
}

/// 日志当前长度，用来在启动游戏前记一个基线偏移。
pub fn proxy_log_len(root: &Path) -> u64 {
    fs::metadata(proxy_log_path(root))
        .map(|meta| meta.len())
        .unwrap_or(0)
}

/// `offset` 之后新写入的内容里有没有代理加载标记。
///
/// 只看增量而不是整份文件：同一个目录反复启动过几十次，整份文件里到处都是
/// 旧标记，按整份判会把「这次没加载」误当成「加载了」。
pub fn proxy_loaded_after(root: &Path, offset: u64) -> bool {
    use std::io::{Read, Seek, SeekFrom};
    let Ok(mut file) = fs::File::open(proxy_log_path(root)) else {
        return false;
    };
    let Ok(meta) = file.metadata() else {
        return false;
    };
    if meta.len() <= offset {
        return false;
    }
    if file.seek(SeekFrom::Start(offset)).is_err() {
        return false;
    }
    let mut buf = Vec::new();
    if file.read_to_end(&mut buf).is_err() {
        return false;
    }
    String::from_utf8_lossy(&buf).contains(PROXY_LOADED_MARKER)
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

    #[test]
    fn mounted_needs_both_proxy_and_backup() {
        // 只有"是代理"和"有备份"同时成立才算 Mounted；
        // 有备份但不是代理 = 别人的 mod，绝不能当可还原状态处理。
        // classify_non_original(has_original_backup, is_agent_proxy)
        assert_eq!(classify_non_original(true, true), HostState::Mounted);
        assert_eq!(classify_non_original(true, false), HostState::Unknown);
        assert_eq!(classify_non_original(false, true), HostState::ProxyNoBackup);
        assert_eq!(classify_non_original(false, false), HostState::Unknown);
    }

    #[test]
    fn agent_proxy_without_backup_is_not_mounted() {
        let dir = tmp("proxy-no-backup");
        let proxy = b"pr2 proxy bytes";
        fs::write(dir.join(HOST_DLL), proxy).unwrap();
        fs::create_dir_all(dir.join("PR2Localization/host")).unwrap();
        fs::write(dir.join(HOST_PROXY_REL), proxy).unwrap();
        assert_eq!(host_state(&dir), HostState::ProxyNoBackup);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn foreign_dll_is_unknown_even_when_pack_has_proxy() {
        let dir = tmp("foreign-dll");
        fs::write(dir.join(HOST_DLL), b"some other mod").unwrap();
        fs::create_dir_all(dir.join("PR2Localization/host")).unwrap();
        fs::write(dir.join(HOST_PROXY_REL), b"pr2 proxy bytes").unwrap();
        assert_eq!(host_state(&dir), HostState::Unknown);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn agent_proxy_can_be_recognised_from_manifest() {
        // 代理升级后包内文件换了，但根目录还是上一版代理：清单能证明它是本工具的。
        let dir = tmp("manifest-proxy");
        let root_bytes = b"previous proxy build";
        fs::write(dir.join(HOST_DLL), root_bytes).unwrap();
        fs::create_dir_all(dir.join("PR2Localization/host")).unwrap();
        fs::write(dir.join(HOST_PROXY_REL), b"new proxy build").unwrap();
        let sha = file_sha256_upper(&dir.join(HOST_DLL)).unwrap();
        fs::write(dir.join(HOST_MANIFEST_REL),
                  format!("{{\n  \"proxy_sha256\": \"{sha}\"\n}}\n")).unwrap();
        assert_eq!(host_state(&dir), HostState::ProxyNoBackup);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn manifest_proxy_sha_ignores_garbage() {
        let dir = tmp("manifest-garbage");
        fs::create_dir_all(dir.join("PR2Localization")).unwrap();
        fs::write(dir.join(HOST_MANIFEST_REL), b"not json").unwrap();
        assert_eq!(manifest_proxy_sha(&dir), None);
        fs::write(dir.join(HOST_MANIFEST_REL),
                  b"{\"proxy_sha256\": \"short\"}").unwrap();
        assert_eq!(manifest_proxy_sha(&dir), None);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn has_host_dll_is_the_only_gate_for_mounting() {
        // 两版都带同名宿主 DLL，挂载能力只看这个文件在不在。
        let dir = tmp("has-host");
        assert!(!has_host_dll(&dir));
        fs::write(dir.join(HOST_DLL), b"x").unwrap();
        assert!(has_host_dll(&dir));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn proxy_marker_only_counts_bytes_after_offset() {
        let dir = tmp("proxy-log");
        let log = proxy_log_path(&dir);
        fs::create_dir_all(log.parent().unwrap()).unwrap();
        // 上一次启动留下的旧标记，不能算作这一次的。
        fs::write(&log, "old run\n[host] DllMain loaded\n").unwrap();
        let base = proxy_log_len(&dir);
        assert!(!proxy_loaded_after(&dir, base));

        // 这一次启动追加了别的行但没有标记 —— 仍然是「没加载」。
        let mut file = fs::OpenOptions::new().append(true).open(&log).unwrap();
        use std::io::Write;
        writeln!(file, "[host] bootstrap thread start").unwrap();
        drop(file);
        assert!(!proxy_loaded_after(&dir, base));

        let mut file = fs::OpenOptions::new().append(true).open(&log).unwrap();
        writeln!(file, "[host] DllMain loaded").unwrap();
        drop(file);
        assert!(proxy_loaded_after(&dir, base));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn proxy_log_absent_is_not_loaded() {
        let dir = tmp("proxy-log-missing");
        assert_eq!(proxy_log_len(&dir), 0);
        assert!(!proxy_loaded_after(&dir, 0));
        let _ = fs::remove_dir_all(&dir);
    }
}
