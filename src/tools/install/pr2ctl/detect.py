# -*- coding: utf-8 -*-
"""pr2ctl.detect —— 版本识别、补丁状态、语言包盘点。"""

from .base import *  # noqa: F401,F403

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
    missing = [n for n in FLAT_FILES if not os.path.isfile(os.path.join(BUILD, n))]
    if need_pack:
        if not os.path.isdir(PACK_OUT):
            missing.append(PACK_DIR + "\\")
    return missing


def launcher_installed(target):
    return os.path.isfile(os.path.join(target, LAUNCHER))


#: 我们装进游戏目录的东西 —— 「移除补丁」只删这些，别的一概不碰。
#: 目录项以反斜杠结尾：删它里面的文件，空了再把目录删掉。


def patch_items(target):
    """游戏目录里实际存在的补丁文件。返回 [(相对名, 绝对路径, 是否目录)]。

    **只按这张固定清单找**：不扫目录、不猜通配，所以不可能误删 PR2.exe、
    存档或别的 mod 的 DLL。
    """
    out = []
    for rel in PATCH_ITEMS:
        p = os.path.join(target, rel.rstrip("\\"))
        if os.path.exists(p):
            out.append((rel, p, os.path.isdir(p)))
    return out


def remove_patch(target, only=None):
    """删掉补丁文件。返回 (是否全部成功, 删掉列表, 失败列表)。

    only 给定时只处理其中的相对名 —— 二次确认的勾选框就是靠它生效的。
    """
    removed, failed = [], []
    for rel, path, isdir in patch_items(target):
        if only is not None and rel not in only:
            continue
        try:
            if isdir:
                for name in sorted(os.listdir(path)):
                    fp = os.path.join(path, name)
                    if os.path.isfile(fp):
                        os.remove(fp)
                        removed.append(rel + name)
                    else:
                        failed.append("%s%s（不是文件，保留）" % (rel, name))
                if not os.listdir(path):
                    os.rmdir(path)
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
    只有装进 PR2Packs\\ 的才真的能让游戏切换过去。
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


def read_ini_language(ini_path):
    """读一份 locale.ini 的 language= 值。读不到返回 None。

    与 DLL 里的 IniGet 同义：认 "language=" 开头，忽略空值。
    """
    try:
        with open(ini_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("language="):
                    return line.split("=", 1)[1].strip() or None
    except OSError:
        pass
    return None


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
    for i, line in enumerate(lines):
        if line.strip().startswith("language="):
            lines[i] = "language=%s" % code
            replaced = True
            break
    if not replaced:
        lines.insert(0, "language=%s" % code)

    try:
        os.makedirs(os.path.dirname(ini_path), exist_ok=True)
        with open(ini_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
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
    out.append(("PR2Launcher.exe", "有" if launcher_installed(path) else "无",
                "注入启动器"))
    out.append(("PR2TextSource.dll", "有" if os.path.isfile(
        os.path.join(path, "PR2TextSource.dll")) else "无", "注入 DLL"))
    packs = installed_langs(path)
    out.append(("PR2Packs\\", "%d 个语言包" % len(packs) if packs else "无",
                "、".join(packs) if packs else "还没有复制语言包"))
    ini = os.path.join(path, PACK_DIR, "locale.ini")
    if os.path.isfile(ini):
        out.append(("PR2Packs\\locale.ini", read_ini_language(ini) or "无 language=",
                    "决定游戏加载哪个包"))
    else:
        out.append(("PR2Packs\\locale.ini", "无", "复制后才会生成"))
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
    return out

