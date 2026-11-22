//! 宿主 DLL：版别判断、状态查询与挂载/还原。
//!
//! GOG 与 Steam 的 `PR2.exe` 都静态导入同目录的 `Ascaron.Logging-2.6.dll`
//! （导入表里只有 `Log` 一个函数），两版的原版 DLL 也是同一份字节。所以两版
//! 走同一条本地化入口：先挂载宿主代理，再由代理去加载 Core。拉起的进程不同：
//! GOG 版由启动器直启 `PR2.exe`；Steam 版交给客户端（`steam://rungameid/12470`），
//! 装在 `Program Files` 下的 `PR2.exe` 直接 CreateProcess 会拿到错误 740。
//!
//! 替换动作只有一份实现，就在本模块：先校验原版大小/SHA-256、建两份备份、
//! 写 `.new` 校验后换名，最后写挂载清单。启动器直接调用，运行期不依赖
//! PowerShell，也不受组策略的脚本限制。

use std::fs;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

pub const HOST_DLL: &str = "Ascaron.Logging-2.6.dll";
pub const HOST_ORIG: &str = "Ascaron.Logging-2.6.orig.dll";
/// 发行包里的代理位置。不能放根目录，否则解压就覆盖掉游戏原版。
pub const HOST_PROXY_REL: &str = "PR2Localization/host/Ascaron.Logging-2.6.dll";
pub const HOST_BACKUP_REL: &str = "PR2Localization/host-backup/Ascaron.Logging-2.6.dll";
pub const HOST_MANIFEST_REL: &str = "PR2Localization/host-mount.json";

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

/// Steam 商店页的 appid，`steam://rungameid/` 后面跟的就是它。
pub const STEAM_APP_ID: u32 = 12470;

/// Steam 版的启动地址：由客户端拉起 `PR2.exe`，而不是启动器自己建进程。
pub fn steam_run_url() -> String {
    format!("steam://rungameid/{}", STEAM_APP_ID)
}

/// 怎么把游戏拉起来。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum LaunchMode {
    /// 启动器直启 `PR2.exe`（GOG 版，或 Steam 版的排查路径）。
    Direct,
    /// 交给 Steam 客户端拉起（`steam://rungameid/12470`）。
    Steam,
    /// 挂起进程后远程注入（`--inject`），两版都能用。
    Inject,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum LaunchModeError {
    /// Steam 版由客户端拉起，父进程的环境变量传不进游戏，`--lang` 没法做一次性覆盖。
    SteamLangUnsupported,
}

/// 选启动方式。
///
/// - `--inject` 优先：它要自己挂起进程再写远程线程，steam:// 做不到这件事。
/// - Steam 版不接受 `--lang`：Steam 拉起的 `PR2.exe` 不是启动器的子进程，
///   `PR2_PACK_LANG` / `PR2_FONT_DIR` 都传不过去；语言只能改
///   `PR2Localization\packs\locale.ini` 的 `language=`。
/// - 其余情况直启。
pub fn launch_mode(
    edition: Edition,
    has_lang: bool,
    inject: bool,
) -> Result<LaunchMode, LaunchModeError> {
    if inject {
        return Ok(LaunchMode::Inject);
    }
    match edition {
        Edition::Steam if has_lang => Err(LaunchModeError::SteamLangUnsupported),
        Edition::Steam => Ok(LaunchMode::Steam),
        Edition::Gog => Ok(LaunchMode::Direct),
    }
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

fn is_original_like(path: &Path, size: u64, sha: &str) -> bool {
    let Ok(meta) = fs::metadata(path) else {
        return false;
    };
    if !meta.is_file() || meta.len() != size {
        return false;
    }
    file_sha256_upper(path)
        .map(|actual| actual == sha)
        .unwrap_or(false)
}

pub fn is_original_host(path: &Path) -> bool {
    is_original_like(path, HOST_ORIGINAL_SIZE, HOST_ORIGINAL_SHA256)
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
/// 只取这一个字段，不引 JSON 解析：清单由本模块写、格式固定，读坏了返回 None。
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
    if proxy_sha256(root)
        .map(|sha| sha == root_sha)
        .unwrap_or(false)
    {
        return true;
    }
    manifest_proxy_sha(root)
        .map(|sha| sha == root_sha)
        .unwrap_or(false)
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
/// 决定的事只有一件：**由谁来拉起 `PR2.exe`**（GOG 直启，Steam 交给客户端）。
/// 本地化能力与版别无关，能不能挂只看根目录有没有宿主 DLL（`has_host_dll`）。
///
/// 顺序：GOG 的 `goggame-*.info/.id/.script` 优先（法语 GOG 版也带同名宿主
/// DLL，不能按 DLL 存在与否猜）；然后是 Steam 库路径 `...\steamapps\common\...`；
/// 再看 Steam 的 `steam_appid.txt`；最后才是「根目录有宿主 DLL 就当 Steam」。
/// 两边都不像时按 GOG 处理。
pub fn detect_edition(root: &Path) -> Edition {
    if has_gog_marker(root) {
        return Edition::Gog;
    }
    if in_steam_library(root) {
        return Edition::Steam;
    }
    if root.join("steam_appid.txt").is_file() {
        return Edition::Steam;
    }
    if root.join(HOST_DLL).is_file() {
        return Edition::Steam;
    }
    Edition::Gog
}

/// Steam 的库目录是 `...\steamapps\common\<游戏>`。这条判据比「有宿主 DLL」
/// 硬：GOG 版没有这个路径，Steam 版只要装在库里就一定有。
fn in_steam_library(root: &Path) -> bool {
    let path = root.to_string_lossy().replace('/', "\\").to_lowercase();
    path.contains("\\steamapps\\common\\")
}

fn has_gog_marker(root: &Path) -> bool {
    let Ok(entries) = fs::read_dir(root) else {
        return false;
    };
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().to_lowercase();
        if name.starts_with("goggame-")
            && (name.ends_with(".info") || name.ends_with(".id") || name.ends_with(".script"))
        {
            return true;
        }
    }
    false
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

// ---------------------------------------------------------------------------
// 挂载与还原：这里就是唯一实现，启动器直接调用，不再拉起 PowerShell。
// ---------------------------------------------------------------------------

/// 挂载/还原失败的原因。文案直接写进 `host.log`，玩家在 GUI 里能看到。
#[derive(Debug, Clone)]
pub struct HostActionError(pub String);

impl std::fmt::Display for HostActionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn err(message: String) -> HostActionError {
    HostActionError(message)
}

/// 解析代理源：只认 `PR2Localization\host\`，旧包才回退到根目录。
///
/// 回退本身是兼容旧包的行为，所以调用方必须再校验「代理不等于原版」：
/// 部署目录缺 `host\` 时回退到根目录同名文件，那就是原版自己。
fn resolve_proxy(root: &Path) -> Result<(PathBuf, String), HostActionError> {
    let path = host_proxy_path(root);
    if !path.is_file() {
        return Err(err(format!("找不到代理：{}", path.display())));
    }
    let sha =
        file_sha256_upper(&path).ok_or_else(|| err(format!("代理不可读：{}", path.display())))?;
    Ok((path, sha))
}

fn write_manifest(root: &Path, proxy_sha: &str, original_sha: &str) -> Result<(), HostActionError> {
    let path = root.join(HOST_MANIFEST_REL);
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| err(format!("建目录失败 {}：{e}", dir.display())))?;
    }
    // 字段与顺序与旧脚本写的一致，读端（manifest_proxy_sha、pr2ctl）不用改。
    let text = format!(
        "{{\n  \"host\": \"{HOST_DLL}\",\n  \"original_sha256\": \"{original_sha}\",\n  \"proxy_sha256\": \"{proxy_sha}\",\n  \"backup\": \"{}\"\n}}\n",
        HOST_BACKUP_REL
    );
    fs::write(&path, text).map_err(|e| err(format!("写挂载清单失败 {}：{e}", path.display())))
}

fn remove_manifest(root: &Path) {
    let path = root.join(HOST_MANIFEST_REL);
    if path.is_file() {
        let _ = fs::remove_file(&path);
    }
}

/// 先写 `<目标>.new`、校验 SHA-256，通过后再换名。
///
/// 复制一半被杀毒或占用打断时，根目录还是原来那份 DLL，不会留下半截文件。
/// Windows 上 `fs::rename` 走 `MoveFileExW(REPLACE_EXISTING)`，换名是原子的。
fn copy_atomically(
    source: &Path,
    dest: &Path,
    expect_sha: &str,
    what: &str,
) -> Result<(), HostActionError> {
    let mut tmp_name = dest.as_os_str().to_owned();
    tmp_name.push(".new");
    let tmp = PathBuf::from(tmp_name);
    let _ = fs::remove_file(&tmp);

    let result = (|| {
        fs::copy(source, &tmp).map_err(|e| err(format!("{what} 复制失败：{e}")))?;
        if file_sha256_upper(&tmp).as_deref() != Some(expect_sha) {
            return Err(err(format!("{what} 复制后校验失败（临时文件哈希不符）")));
        }
        fs::rename(&tmp, dest).map_err(|e| {
            err(format!(
                "{what} 替换失败：{e}（游戏或杀毒可能正占用 {}）",
                dest.file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_default()
            ))
        })?;
        Ok(())
    })();

    if result.is_err() {
        let _ = fs::remove_file(&tmp);
        return result;
    }
    if file_sha256_upper(dest).as_deref() != Some(expect_sha) {
        return Err(err(format!("{what} 替换后校验失败")));
    }
    Ok(())
}

/// 保证 `.orig.dll` 与 `host-backup\` 两份备份都是可验证的原版。
///
/// `from_root` 只在根目录确认是原版时为真：这时可以直接把根目录文件复制成
/// 第一份备份。根目录已经是代理时，只能从已有的备份反推，绝不能拿代理当备份。
fn ensure_backups(
    root: &Path,
    original_size: u64,
    original_sha: &str,
    from_root: bool,
) -> Result<(), HostActionError> {
    let root_dll = root.join(HOST_DLL);
    let orig = root.join(HOST_ORIG);
    let backup = root.join(HOST_BACKUP_REL);

    if orig.is_file() {
        if !is_original_like(&orig, original_size, original_sha) {
            return Err(err(".orig.dll 不是已知原版，拒绝覆盖".to_string()));
        }
    } else if from_root && is_original_like(&root_dll, original_size, original_sha) {
        fs::copy(&root_dll, &orig).map_err(|e| err(format!("备份 .orig.dll 失败：{e}")))?;
    } else if is_original_like(&backup, original_size, original_sha) {
        // 只剩 host-backup 一份时先把它补回 .orig.dll，还原路径才有得用。
        if let Some(dir) = orig.parent() {
            fs::create_dir_all(dir).ok();
        }
        fs::copy(&backup, &orig).map_err(|e| err(format!("补回 .orig.dll 失败：{e}")))?;
    } else {
        return Err(err(
            "没有可验证的 .orig.dll 或 host-backup，拒绝继续".to_string()
        ));
    }

    if let Some(dir) = backup.parent() {
        fs::create_dir_all(dir)
            .map_err(|e| err(format!("建备份目录失败 {}：{e}", dir.display())))?;
    }
    if !is_original_like(&backup, original_size, original_sha) {
        fs::copy(&orig, &backup).map_err(|e| err(format!("备份 host-backup 失败：{e}")))?;
        if !is_original_like(&backup, original_size, original_sha) {
            return Err(err("第二份备份写入后校验失败".to_string()));
        }
    }
    Ok(())
}

/// 把根目录宿主 DLL 换成代理：校验 → 建两份备份 → 原子替换 → 写清单。
///
/// 只接受「根目录是已知原版」或「根目录是本工具代理且备份可验证」两种状态；
/// 其余一律拒绝，避免覆盖别的 mod 或未知文件。
pub fn mount_host(root: &Path) -> Result<(), HostActionError> {
    mount_host_with(root, HOST_ORIGINAL_SIZE, HOST_ORIGINAL_SHA256)
}

fn mount_host_with(
    root: &Path,
    original_size: u64,
    original_sha: &str,
) -> Result<(), HostActionError> {
    if !root.join("PR2.exe").is_file() {
        return Err(err(format!("目标目录没有 PR2.exe：{}", root.display())));
    }
    let root_dll = root.join(HOST_DLL);
    if !root_dll.is_file() {
        return Err(err(format!("目标目录没有 {HOST_DLL}，不能挂载宿主代理")));
    }

    let (proxy, proxy_sha) = resolve_proxy(root)?;
    if proxy_sha == original_sha {
        return Err(err(format!(
            "代理源是原版 DLL：{}。发行包应在 {HOST_PROXY_REL} 放本地化代理；把原版当代理挂载只会静默失败。",
            proxy.display()
        )));
    }

    let root_sha = file_sha256_upper(&root_dll);
    if is_original_like(&root_dll, original_size, original_sha) {
        ensure_backups(root, original_size, original_sha, true)?;
    } else {
        let orig = root.join(HOST_ORIG);
        let backup = root.join(HOST_BACKUP_REL);
        let has_backup = is_original_like(&orig, original_size, original_sha)
            || is_original_like(&backup, original_size, original_sha);
        let is_proxy = root_sha.as_deref() == Some(proxy_sha.as_str())
            || manifest_proxy_sha(root).as_deref() == root_sha.as_deref();
        if !has_backup || !is_proxy {
            return Err(err(
                "根目录 DLL 不是已知原版，也不是本工具代理；拒绝挂载".to_string()
            ));
        }
        ensure_backups(root, original_size, original_sha, false)?;
    }

    if root_sha.as_deref() != Some(proxy_sha.as_str()) {
        copy_atomically(&proxy, &root_dll, &proxy_sha, "宿主代理")?;
    }
    write_manifest(root, &proxy_sha, original_sha)?;
    Ok(())
}

/// 把根目录宿主 DLL 换回原版。只接受本工具代理，不覆盖未知文件。
pub fn restore_host(root: &Path) -> Result<(), HostActionError> {
    restore_host_with(root, HOST_ORIGINAL_SIZE, HOST_ORIGINAL_SHA256)
}

fn restore_host_with(
    root: &Path,
    original_size: u64,
    original_sha: &str,
) -> Result<(), HostActionError> {
    let root_dll = root.join(HOST_DLL);
    if !root_dll.is_file() {
        return Err(err(format!("找不到 {HOST_DLL}，无法还原")));
    }
    if is_original_like(&root_dll, original_size, original_sha) {
        remove_manifest(root);
        return Ok(());
    }

    let orig = root.join(HOST_ORIG);
    let backup = root.join(HOST_BACKUP_REL);
    if !is_original_like(&orig, original_size, original_sha) {
        if is_original_like(&backup, original_size, original_sha) {
            fs::copy(&backup, &orig).map_err(|e| err(format!("补回 .orig.dll 失败：{e}")))?;
        } else {
            return Err(err(
                "没有可验证的 .orig.dll 或 host-backup，拒绝还原".to_string()
            ));
        }
    }

    let root_sha = file_sha256_upper(&root_dll).unwrap_or_default();
    let proxy_sha = file_sha256_upper(&host_proxy_path(root)).unwrap_or_default();
    let known = manifest_proxy_sha(root).unwrap_or_default();
    if root_sha != proxy_sha && root_sha != known {
        return Err(err(
            "根目录 DLL 不是本工具代理；拒绝覆盖未知文件".to_string()
        ));
    }

    copy_atomically(&orig, &root_dll, original_sha, "原版宿主")?;
    remove_manifest(root);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("pr2-host-rs-{}-{}", tag, std::process::id()));
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
    fn detects_steam_by_library_path() {
        // Steam 安装本身不写 steam_appid.txt（那是给非 Steam 启动用的），
        // 所以库路径也得能单独认出来。
        let root = PathBuf::from(r"C:\Program Files (x86)\Steam\steamapps\common\Port Royale 2");
        assert!(in_steam_library(&root));
        assert!(!in_steam_library(Path::new(
            r"C:\My\Games\Port Royale 2 GOG EN"
        )));
        assert!(!in_steam_library(Path::new(r"D:\Games\Port Royale 2")));
    }

    #[test]
    fn steam_url_is_the_store_app_id() {
        assert_eq!(steam_run_url(), "steam://rungameid/12470");
    }

    #[test]
    fn steam_launch_mode_rejects_single_run_language() {
        // Steam 拉起的 PR2.exe 不是启动器的子进程，环境变量传不过去。
        assert_eq!(
            launch_mode(Edition::Steam, false, false),
            Ok(LaunchMode::Steam)
        );
        assert_eq!(
            launch_mode(Edition::Steam, true, false),
            Err(LaunchModeError::SteamLangUnsupported)
        );
        // --inject 要自己挂起进程再写远程线程，两种版别都不能交给 Steam。
        assert_eq!(
            launch_mode(Edition::Steam, true, true),
            Ok(LaunchMode::Inject)
        );
        assert_eq!(
            launch_mode(Edition::Gog, true, false),
            Ok(LaunchMode::Direct)
        );
        assert_eq!(
            launch_mode(Edition::Gog, false, false),
            Ok(LaunchMode::Direct)
        );
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
        fs::write(
            dir.join(HOST_MANIFEST_REL),
            format!("{{\n  \"proxy_sha256\": \"{sha}\"\n}}\n"),
        )
        .unwrap();
        assert_eq!(host_state(&dir), HostState::ProxyNoBackup);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn manifest_proxy_sha_ignores_garbage() {
        let dir = tmp("manifest-garbage");
        fs::create_dir_all(dir.join("PR2Localization")).unwrap();
        fs::write(dir.join(HOST_MANIFEST_REL), b"not json").unwrap();
        assert_eq!(manifest_proxy_sha(&dir), None);
        fs::write(
            dir.join(HOST_MANIFEST_REL),
            b"{\"proxy_sha256\": \"short\"}",
        )
        .unwrap();
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

    /// 用假的原版字节跑挂载/还原：真实原版是 11776 B 的二进制，不便入库。
    /// 大小与 SHA 由 `*_with` 参数传入，判定逻辑与真实常量完全同一套代码。
    struct Fixture {
        dir: PathBuf,
        size: u64,
        sha: String,
    }

    fn fixture(tag: &str) -> Fixture {
        let dir = tmp(tag);
        let original = b"fake original host dll".to_vec();
        fs::write(dir.join("PR2.exe"), b"stub").unwrap();
        fs::write(dir.join(HOST_DLL), &original).unwrap();
        fs::create_dir_all(dir.join("PR2Localization/host")).unwrap();
        fs::write(dir.join(HOST_PROXY_REL), b"fake localization proxy").unwrap();
        let sha = file_sha256_upper(&dir.join(HOST_DLL)).unwrap();
        Fixture {
            dir,
            size: original.len() as u64,
            sha,
        }
    }

    #[test]
    fn mount_backs_up_twice_and_swaps_in_proxy() {
        let f = fixture("mount-ok");
        mount_host_with(&f.dir, f.size, &f.sha).unwrap();

        let root = fs::read(f.dir.join(HOST_DLL)).unwrap();
        assert_eq!(root, b"fake localization proxy");
        assert_eq!(
            fs::read(f.dir.join(HOST_ORIG)).unwrap(),
            b"fake original host dll"
        );
        assert_eq!(
            fs::read(f.dir.join(HOST_BACKUP_REL)).unwrap(),
            b"fake original host dll"
        );
        assert_eq!(
            manifest_proxy_sha(&f.dir),
            file_sha256_upper(&f.dir.join(HOST_DLL))
        );
        assert!(!f
            .dir
            .join("PR2Localization/host/Ascaron.Logging-2.6.dll.new")
            .exists());

        // 已经挂载时再跑一次：不重复改写，也不破坏备份。
        mount_host_with(&f.dir, f.size, &f.sha).unwrap();
        assert_eq!(
            fs::read(f.dir.join(HOST_DLL)).unwrap(),
            b"fake localization proxy"
        );
        let _ = fs::remove_dir_all(&f.dir);
    }

    #[test]
    fn restore_puts_the_original_back_and_drops_manifest() {
        let f = fixture("restore-ok");
        mount_host_with(&f.dir, f.size, &f.sha).unwrap();
        restore_host_with(&f.dir, f.size, &f.sha).unwrap();

        assert_eq!(
            fs::read(f.dir.join(HOST_DLL)).unwrap(),
            b"fake original host dll"
        );
        assert!(!f.dir.join(HOST_MANIFEST_REL).exists());
        // 还原后再还原一次是幂等的。
        restore_host_with(&f.dir, f.size, &f.sha).unwrap();
        let _ = fs::remove_dir_all(&f.dir);
    }

    #[test]
    fn restore_recovers_from_host_backup_when_orig_is_gone() {
        let f = fixture("restore-backup");
        mount_host_with(&f.dir, f.size, &f.sha).unwrap();
        fs::remove_file(f.dir.join(HOST_ORIG)).unwrap();
        restore_host_with(&f.dir, f.size, &f.sha).unwrap();
        assert_eq!(
            fs::read(f.dir.join(HOST_DLL)).unwrap(),
            b"fake original host dll"
        );
        assert!(f.dir.join(HOST_ORIG).is_file());
        let _ = fs::remove_dir_all(&f.dir);
    }

    #[test]
    fn mount_refuses_unknown_root_dll() {
        let f = fixture("mount-unknown");
        fs::write(f.dir.join(HOST_DLL), b"some other mod").unwrap();
        let err = mount_host_with(&f.dir, f.size, &f.sha).unwrap_err();
        assert!(err.0.contains("拒绝挂载"), "{}", err.0);
        assert_eq!(fs::read(f.dir.join(HOST_DLL)).unwrap(), b"some other mod");
        let _ = fs::remove_dir_all(&f.dir);
    }

    #[test]
    fn mount_refuses_proxy_that_is_the_original() {
        let f = fixture("mount-proxy-original");
        fs::write(f.dir.join(HOST_PROXY_REL), b"fake original host dll").unwrap();
        let err = mount_host_with(&f.dir, f.size, &f.sha).unwrap_err();
        assert!(err.0.contains("代理源是原版 DLL"), "{}", err.0);
        let _ = fs::remove_dir_all(&f.dir);
    }

    #[test]
    fn mount_refuses_corrupt_orig_backup() {
        let f = fixture("mount-corrupt-orig");
        fs::write(f.dir.join(HOST_ORIG), b"not an original").unwrap();
        let err = mount_host_with(&f.dir, f.size, &f.sha).unwrap_err();
        assert!(err.0.contains(".orig.dll 不是已知原版"), "{}", err.0);
        assert_eq!(
            fs::read(f.dir.join(HOST_DLL)).unwrap(),
            b"fake original host dll"
        );
        let _ = fs::remove_dir_all(&f.dir);
    }
}
