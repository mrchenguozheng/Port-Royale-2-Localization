# -*- coding: utf-8 -*-
"""pr2ctl.detect —— 版本识别、补丁状态、语言包盘点。"""

from .base import *  # noqa: F401,F403
from . import steam_host

def available_langs():
    r"""src\translations\ 下可编辑的语言代码，供勾选。

    规则只有一份，在 translate.py 里（文件名即语言代码，
    `_` 开头的不是语言）；这里直接问它，避免两处各扫一遍而漂移。
    """
    sys.path.insert(0, HERE)
    import translate as T
    # test_en 这类测试用语言不进界面（与 apply_patch 的过滤一致）
    return [c for c in T.target_langs() if not c.startswith("test_")]


def missing_outputs(need_pack=True):
    """部署前必须存在的构建产物。"""
    missing = [n for n in FLAT_FILES if not os.path.isfile(os.path.join(RUNTIME, n))]
    if need_pack:
        if not os.path.isdir(PACK_OUT):
            missing.append(PACK_DIR + "\\")
    return missing


def launcher_installed(target):
    return os.path.isfile(os.path.join(target, LAUNCHER))


#: 我们装进游戏目录的东西 —— 「移除补丁」只删这些，别的一概不碰。
#: 目录项以反斜杠结尾：删它里面的文件，空了再把目录删掉。


def patch_items(target, edition=None):
    """游戏目录里实际存在的补丁文件。返回 [(相对名, 绝对路径, 是否目录)]。

    **只按这张固定清单找**：不扫目录、不猜通配，所以不可能误删 PR2.exe、
    存档或别的 mod 的 DLL。宿主 DLL 不在这里 —— 卸载前先还原
    原版，还原成功后才删公共文件。
    """
    out = []
    for rel in PATCH_ITEMS:
        p = os.path.join(target, rel.rstrip("\\"))
        if os.path.exists(p):
            out.append((rel, p, os.path.isdir(p)))
    return out


def remove_patch(target, only=None, edition=None):
    """删掉补丁文件。返回 (是否全部成功, 删掉列表, 失败列表)。

    only 给定时只处理其中的相对名 —— 二次确认的勾选框就是靠它生效的。
    两版都可能挂过宿主代理，先还原宿主 DLL；还原失败就停止，不删任何文件。
    edition 参数留着是给调用方兼容的，判据改用 has_host。
    """
    del edition                                   # 版别不再决定还原与否
    if steam_host.has_host(target):
        try:
            steam_host.restore_host(target)
        except steam_host.HostError as exc:
            return False, [], ["宿主还原失败：%s" % exc]
    removed, failed = [], []
    for rel, path, isdir in patch_items(target):
        if only is not None and rel not in only:
            continue
        try:
            if isdir:
                # 固定清单里的 PR2Localization\\ 是我们自己的数据目录，
                # 里面有 packs/fonts/ui/logs/host-backup 子目录，必须整树删。
                shutil.rmtree(path)
                removed.append(rel)
            else:
                os.remove(path)
                removed.append(rel)
        except OSError as exc:
            # 游戏在跑时文件被占，这里会失败 —— 原样报出来，别静默。
            failed.append("%s（%s）" % (rel, exc))
    return (not failed), removed, failed


def installed_langs(target):
    """游戏目录里真实存在的语言包代码，按字母序。

    选的是这里而不是 src\\translations\\：那边是还没编译的译文源，
    只有装进 PR2Localization\\packs\\ 的才真的能让游戏切换过去。
    """
    pack_dir = os.path.join(target, PACK_DIR)
    if not os.path.isdir(pack_dir):
        return []
    out = []
    for name in os.listdir(pack_dir):
        if name.lower().endswith(".txt"):
            code = name[:-4]
            if code:
                out.append(code)
    return sorted(out)


def _parse_language_line(line):
    """返回 (是否 language 行, 值)。

    与 Rust 端 `pr2_common::language_line()` 同一规则：`=` 两侧允许空白，
    值后的 `;` / `#` 视为行内注释；空值返回 ("", True)。
    """
    stripped = line.strip().lstrip("\ufeff")
    if not stripped or stripped.startswith(("#", ";")):
        return False, ""
    key, sep, value = stripped.partition("=")
    if not sep or key.strip().lower() != "language":
        return False, ""
    value = value.split(";", 1)[0].split("#", 1)[0].strip()
    return True, value


def read_ini_language(ini_path):
    """读一份 locale.ini 的 language= 值。读不到或空值返回 None。"""
    try:
        with open(ini_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                matched, value = _parse_language_line(line)
                if matched:
                    return value or None
    except OSError:
        pass
    return None


def read_locale_language(target):
    """游戏当前语言：优先用户 locale.ini，不存在再读 locale.default.ini。

    用户文件存在但 language= 为空时返回 None，不拿默认值补齐 ——
    空值是用户明确清空，部署和运行时都必须保留。
    """
    user_ini = os.path.join(target, PACK_DIR, LOCALE_FILE)
    if os.path.isfile(user_ini):
        return read_ini_language(user_ini)
    return read_ini_language(os.path.join(target, PACK_DIR,
                                          LOCALE_DEFAULT_FILE))


def write_ini_language(ini_path, code):
    """把 language= 写成 code，保留文件里其他行。

    返回 True 表示写成功。失败不抛 —— locale.ini 可能只读，
    而「界面选了但没存上」只需要提示，不必中断操作。
    """
    lines = []
    try:
        with open(ini_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []

    replaced = False
    out_lines = []
    for line in lines:
        matched, _value = _parse_language_line(line)
        if matched:
            if not replaced:
                out_lines.append("language=%s" % code)
                replaced = True
            # 旧版本可能留下两行 language；写回时只保留第一行。
            continue
        out_lines.append(line)
    if not replaced:
        out_lines.append("language=%s" % code)

    try:
        parent = os.path.dirname(ini_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(ini_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out_lines) + "\n")
        return True
    except OSError:
        return False


def exe_sha256(path):
    """PR2.exe 的 SHA-256（大写）；读不到返回空串。"""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest().upper()
    except OSError:
        return ""


def identify_dir(path):
    """返回 (sha256, 已知构建 dict 或 None)。"""
    sha = exe_sha256(os.path.join(path, GAME_EXE))
    return sha, BUILD_BY_SHA.get(sha)


def version_label(sha):
    b = BUILD_BY_SHA.get(sha)
    if b:
        return b["label"]
    return "未知版本（%s…）" % sha[:8] if sha else "未识别"


def patch_report(path):
    """检查游戏目录里补丁的安装状态，返回 [(项目, 状态, 说明)]。"""
    out = []
    out.append(("PR2.exe", "有" if is_game_dir(path) else "缺失",
                "必需" if is_game_dir(path) else "该目录里没有 PR2.exe"))
    out.append(("PR2Localization.exe", "有" if launcher_installed(path) else "无",
                "注入启动器"))
    out.append(("PR2LocalizationCore.dll", "有" if os.path.isfile(
        os.path.join(path, "PR2LocalizationCore.dll")) else "无", "注入 DLL"))
    packs = installed_langs(path)
    out.append(("PR2Localization\\packs\\", "%d 个语言包" % len(packs) if packs else "无",
                "、".join(packs) if packs else "还没有复制语言包"))
    ini = os.path.join(path, PACK_DIR, LOCALE_FILE)
    default_ini = os.path.join(path, PACK_DIR, LOCALE_DEFAULT_FILE)
    if os.path.isfile(ini):
        out.append(("PR2Localization\\packs\\locale.ini",
                    read_ini_language(ini) or "无 language=",
                    "决定游戏加载哪个包"))
    elif os.path.isfile(default_ini):
        out.append(("PR2Localization\\packs\\locale.default.ini",
                    read_ini_language(default_ini) or "无 language=",
                    "默认语言；建 locale.ini 可覆盖"))
    else:
        out.append(("PR2Localization\\packs\\locale.default.ini",
                    "无", "复制后才会生成"))
    fonts_dir = os.path.join(path, "fonts")
    orig_dir = os.path.join(ROOT, "assets", "fonts", "original")
    for name in ("ARIAL.TTF", "ELGRECO_.TTF", "Tiepolo_black.ttf", "Tiepolo_bold.ttf"):
        live = os.path.join(fonts_dir, name)
        orig = os.path.join(orig_dir, name)
        if not os.path.isfile(live):
            out.append(("fonts\\" + name, "缺失", "游戏目录里没有这个字体"))
            continue
        if not os.path.isfile(orig):
            out.append(("fonts\\" + name, "无法比对", "仓库缺原版字体"))
            continue
        replaced = file_digest(live) != file_digest(orig)
        out.append(("fonts\\" + name,
                    "已替换" if replaced else "原版",
                    "含中日文字形的子集" if replaced else "未动"))
    if steam_host.has_host(path):
        state, note = steam_host.status(path)
        out.append((steam_host.HOST_DLL, state, note))
    return out

