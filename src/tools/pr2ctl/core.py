#!/usr/bin/env python3
# coding: utf-8
r"""pr2ctl.core — Port Royale 2 本地化工具的核心逻辑（无 UI 依赖）

一个窗口分三段，段号就是步骤号：

界面无关：版本识别、构建、部署、启动、设置读写都在这里。
tkinter 窗口（build_install.py）只负责显示与回调。
"""

import ctypes
import hashlib
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser



HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src/tools
SRC = os.path.dirname(HERE)                              # 仓库的 src\
ROOT = os.path.dirname(SRC)                              # 仓库根
BUILD = os.path.join(ROOT, "build")
PACK_OUT = os.path.join(BUILD, "PR2Packs")
LOCALE_INI = os.path.join(SRC, "locale.ini")

# 直接复制进游戏目录的文件。
FLAT_FILES = ("PR2Launcher.exe", "PR2TextSource.dll")
# 整个目录一起复制。
PACK_DIR = "PR2Packs"
GAME_EXE = "PR2.exe"
#: 装好之后用它启动游戏。它挂起 PR2.exe、注入 DLL、再恢复执行。
LAUNCHER = "PR2Launcher.exe"
#: 编译注入器。子进程里跑，结果读它的输出。
INJECTOR_BAT = os.path.join(SRC, "build_injector.bat")
#: 译文编辑器（本地 Web）。它跟上面三条链路都无关 —— 不编译、不复制、
#: 不启动游戏，只改 src\translations\*.toml，所以自己一个按钮。
EDITOR_DIR = os.path.join(SRC, "editor")
#: 独立入口（想不开工具窗口时双击用）。
EDITOR_BAT = os.path.join(EDITOR_DIR, "StartEditor.bat")
EDITOR_DIST = os.path.join(EDITOR_DIR, "dist")
#: 编辑器从 8777 起往上找空端口，所以探测也按这个范围来 ——
#: 这样才能找到「上一次 start 留下、还在跑」的那个实例并复用它。
EDITOR_PORT_BASE = 8777
#: 扫得比 server.py 的候选范围（8777 + 20）再宽一点：端口被占时它会往上挪，
#: 而上一轮留下的实例可能正好停在更上面。多扫几个端口很便宜（本地拒绝是
#: 立刻返回的），漏扫的代价却是「没认出来 → 又起一个」。
EDITOR_PORT_TRIES = 24
#: 启动语言下拉里的「不指定」项：读PR2Packs\locale.ini 的 language=。
FOLLOW_LANG = "跟随 locale.ini"

#: 日志保留的最大行数。超过就丢最老的那些：一次构建几十行，
#: 反复操作几千行会让 Text 控件越来越慢，但全清又等于把刚才的
#: 排查线索一起丢了，所以留一个上限而不是清空。
LOG_MAX_LINES = 4000


# ------------------------------------------------------------ 可用语言

def available_langs():
    r"""src\translations\ 下可编辑的语言代码，供勾选。

    规则只有一份，在 translate.py 里（文件名即语言代码，
    `_` 开头的不是语言）；这里直接问它，避免两处各扫一遍而漂移。
    """
    sys.path.insert(0, HERE)
    import translate as T
    # test_en 这类测试用语言不进界面（与 apply_patch 的过滤一致）
    return [c for c in T.target_langs() if not c.startswith("test_")]


# ------------------------------------------------------------ 构建产物

def missing_outputs(need_pack=True):
    """部署前必须存在的构建产物。"""
    missing = [n for n in FLAT_FILES if not os.path.isfile(os.path.join(BUILD, n))]
    if need_pack:
        if not os.path.isdir(PACK_OUT):
            missing.append(PACK_DIR + "\\")
    return missing


def is_game_dir(path):
    return bool(path) and os.path.isfile(os.path.join(path, GAME_EXE))


def writable(path):
    """游戏在运行时旧 DLL 与启动器都被占着，复制会以共享冲突失败，
    不是权限不足。先探一下写权限，好在报错时说清是哪一种。"""
    probe = os.path.join(path, ".pr2loc_write_test")
    try:
        with open(probe, "wb"):
            pass
        os.remove(probe)
    except OSError:
        return False
    return True


def same_content(a, b):
    """两个文件内容是否一致。

    比大小先过一遍：语言包几百 KB，同尺寸却不同的机会极少，
    而逐字节比只在尺寸相同时才做。
    """
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
    except OSError:
        return False
    return file_digest(a) == file_digest(b)


def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def deploy_steps(target, langs):
    """列出复制要做的事，供进度条按步推进。

    langs 给出时只复制这些语言的语言包 —— build\\PR2Packs 是累积
    目录，里面可能还留着上一次构建的其他语言，整目录照搬会把
    locale.ini 根本没指向的语言也塞进游戏。langs 为 None 时整目录复制。
    """
    steps = [(n, os.path.join(BUILD, n), os.path.join(target, n))
             for n in FLAT_FILES]

    # 字体：游戏自带的是纯拉丁字体，不换掉中文就画不出来。
    # 由 src\tools\subset_fonts.py 生成到 build\fonts\；没有就跳过
    # （旧版本的构建目录里可能还没有字体）。
    font_dir = os.path.join(BUILD, "fonts")
    if os.path.isdir(font_dir):
        for name in sorted(os.listdir(font_dir)):
            if name.lower().endswith(".ttf"):
                steps.append(("fonts\\%s" % name,
                              os.path.join(font_dir, name),
                              os.path.join(target, "fonts", name)))

    steps.append(("%s\\" % PACK_DIR, None, os.path.join(target, PACK_DIR)))
    wanted = ["locale.ini"]
    if langs:
        wanted += ["%s.txt" % c for c in langs]
    for name in wanted:
        src = os.path.join(PACK_OUT, name)
        if os.path.isfile(src):
            steps.append(("%s\\%s" % (PACK_DIR, name), src,
                          os.path.join(target, PACK_DIR, name)))
    return steps


def copy_if_different(src, dst):
    """内容不同才复制。返回 "copied" / "same" / "failed"。

    已经一致就不动目标文件：反复点复制时 DLL 与启动器不会被
    反复改写，而正在运行的游戏加载着旧 DLL，跳过也能避免
    撞上文件占用。
    """
    if os.path.isfile(dst) and same_content(src, dst):
        return "same"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.copy2(src, dst)
        return "copied"
    except OSError:
        # 目标被占用（典型：游戏/杀毒还开着）时直接覆盖会失败，
        # 改成「把旧文件改名让位，再写新文件」；旧文件删不掉就留着 .old。
        alt = dst + ".old"
        try:
            os.replace(dst, alt)
            shutil.copy2(src, dst)
        except OSError:
            return "failed"
        try:
            os.remove(alt)
        except OSError:
            pass
        return "copied"


def prune_stale_pack(target, langs):
    """删掉游戏目录 PR2Packs\\ 里本次不装的文件，返回删掉的名字。

    只删多出来的，不动要留的 —— 整个 rmtree 会让「内容相同就跳过」
    永远生效不了，语言包每次都被重写。
    """
    dst_pack = os.path.join(target, PACK_DIR)
    if not os.path.isdir(dst_pack):
        return []
    keep = {"locale.ini"}
    if langs:
        keep |= {"%s.txt" % c for c in langs}
    removed = []
    for name in os.listdir(dst_pack):
        if name in keep:
            continue
        p = os.path.join(dst_pack, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            removed.append(name)
        except OSError:
            pass
    return removed


def deploy(target, langs=None):
    """把构建产物复制到 target。返回 (是否成功, 说明)。"""
    if not writable(target):
        return False, (
            "无法写入该目录。\n\n"
            "最常见的原因是游戏正在运行 —— 请先关闭 Port Royale 2 再试。"
        )
    copied, same, failed = [], [], []
    try:
        for name in prune_stale_pack(target, langs):
            same.append("%s（已移除）" % name)

        for label, src, dst in deploy_steps(target, langs):
            if src is None:                        # 目录本身
                os.makedirs(dst, exist_ok=True)
                continue
            r = copy_if_different(src, dst)
            name = os.path.basename(dst)
            (copied if r == "copied" else same if r == "same" else failed).append(name)

    except PermissionError:
        return False, "权限不足。请确认游戏已关闭，且该目录允许写入。"
    except OSError as exc:
        return False, "复制失败：%s" % exc

    if failed:
        return False, "以下文件复制失败：%s\n\n请确认游戏已关闭。" % "、".join(failed)
    return True, (
        "已复制到：\n%s\n\n"
        "新复制：%s\n未改动：%s\n\n"
        "点「启动游戏（已注入）」即可启动，或以后手动运行这个目录下的\n"
        "%s。语言包在游戏启动时读取，改完翻译重新构建再复制一次即可。"
        % (target,
           "、".join(copied) or "（无）",
           "、".join(same) or "（无）",
           LAUNCHER)
    )


def run_deploy(target, langs, events):
    """部署线程主体，逐步推进进度条。任何一步失败就停下。"""
    try:
        if not writable(target):
            events.put(("line", "无法写入该目录。"))
            events.put(("line", "最常见的原因是游戏正在运行 —— 请先关闭游戏再试。"))
            events.put(("deploy_failed", ""))
            return

        for name in prune_stale_pack(target, langs):
            events.put(("line", "移除 %s\\%s（本次不装）" % (PACK_DIR, name)))

        steps = deploy_steps(target, langs)
        for i, (label, src, dst) in enumerate(steps, 1):
            events.put(("deploy_step", (i, len(steps), label)))
            if src is None:
                os.makedirs(dst, exist_ok=True)
                events.put(("line", "  新建 %s" % label))
                continue

            r = copy_if_different(src, dst)
            if r == "same":
                events.put(("line", "  跳过 %s（内容相同）" % label))
            elif r == "copied":
                events.put(("line", "  已复制 %s" % label))
            else:
                events.put(("line", "  复制失败 %s —— 游戏可能正在运行" % label))
                events.put(("deploy_failed", ""))
                return

        events.put(("deploy_ok", target))
    except Exception as exc:                      # 兜底，别让线程静默死掉
        events.put(("line", "部署出错：%s" % exc))
        events.put(("deploy_failed", ""))


def launcher_installed(target):
    return os.path.isfile(os.path.join(target, LAUNCHER))


#: 我们装进游戏目录的东西 —— 「移除补丁」只删这些，别的一概不碰。
#: 目录项以反斜杠结尾：删它里面的文件，空了再把目录删掉。
PATCH_ITEMS = (
    "PR2Launcher.exe",
    "PR2TextSource.dll",
    "PR2TextSource.log",
    "PR2TextSource_gap.log",
    "PR2TextSource_lsr.log",
    "PR2TextSource_resolve.log",
    "PR2Packs\\",
)


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


# ---------------------------------------------------------------- 游戏版本

#: 已知的 PR2.exe 构建（SHA-256 为实测值，来自 1.1.2.3 的三种发行版）。
#: 用途只有一个：识别用户手上是哪个版本，从而记住对应目录、提示兼容性。
KNOWN_BUILDS = (
    {
        "id": "gog-en-1.1.2.3",
        "label": "GOG 英文版 1.1.2.3",
        "sha256": "394CE2A48BC6B21708B81A232C7C88459BE7F3C8082CC593AD83B0B8E4C168EC",
        "note": "原版英文，注入方案首选；安装目录自带 PR2Packs 目录。",
    },
    {
        "id": "gog-fr-1.1.2.42",
        "label": "GOG 法语版 1.1.2.42",
        "sha256": "EF0E97D40F8DDF24186D18D39D07F12C562949D005654E99B7C1D21429110FA5",
        "note": "法文界面文本编在 exe 里；exe 版本号是 1.1.2.42，比英文版高。",
    },
    {
        "id": "steam-en-1.1.2.3",
        "label": "Steam 英文版 1.1.2.3",
        "sha256": "5295C06689147F7565F72510AEB686719CF0AE38AA581A6DF3E4D61D0CF76264",
        "note": "带 CEG 校验，exe 不能改；必须走注入。",
    },
)
BUILD_BY_SHA = {b["sha256"].upper(): b for b in KNOWN_BUILDS}


def settings_path():
    """设置文件：优先 %LOCALAPPDATA%，没有就放仓库 build\\ 下。"""
    override = os.environ.get("PR2_SETTINGS")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return os.path.join(base, "PR2Localization", "settings.json")
    return os.path.join(ROOT, "build", "settings.json")


def load_settings():
    path = settings_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("dirs", {})
            data.setdefault("current", "")
            data.setdefault("last_dir", "")
            return data
    except (OSError, ValueError):
        pass
    return {"dirs": {}, "current": "", "last_dir": ""}


def save_settings(data):
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
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


def launch_game(target, lang=None):
    """用注入器启动器把游戏拉起来（带语言包）。返回 (是否成功, 说明)。

    启动器自己会 CreateProcess 一个挂起的 PR2.exe、注入 DLL 再恢复，
    所以它很快就会退出 —— 不用等它结束。控制台留给它自己开，
    那里会打印注入结果，窗口不该抢。

    工作目录必须设成游戏目录：启动器给 CreateProcess 传的
    lpCurrentDirectory 是 NULL，PR2.exe 会继承启动器的 cwd，
    而它按相对路径找资源文件。

    lang 非空时给启动器传 --lang=xx，它写进子进程的 PR2_PACK_LANG，
    DLL 优先用它而不是 locale.ini —— 只影响这一次启动，不写任何文件。
    """
    exe = os.path.join(target, LAUNCHER)
    if not os.path.isfile(exe):
        return False, "该目录下没有 %s，请先复制到游戏目录。" % LAUNCHER
    if not is_game_dir(target):
        return False, "该目录下没有 %s，请重新选择游戏目录。" % GAME_EXE
    try:
        cmd = [exe]
        if lang:
            cmd.append("--lang=%s" % lang)
        proc = subprocess.Popen(cmd, cwd=target, close_fds=True)
    except OSError as exc:
        return False, "启动 %s 失败：%s\n\n%s" % (LAUNCHER, exc,
                                                _oserr_hint(exc))

    # 启动器很快退出：注入完就返回，不等游戏。所以「两秒内退出码非 0」
    # 就是它没把游戏拉起来（例如 --lang 的值它不接受）。这种失败只打在
    # 它自己的控制台里，而那个窗口一闪就关 —— 不给提示的话，用户看到的
    # 就是「黑框一闪，游戏没了」。这里补一句人话。
    try:
        code = proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        code = 0            # 还在跑，说明游戏已经拉起来了
    if code != 0:
        return False, ("%s 退出码 %d —— 游戏没有启动。\n\n"
                       "常见原因：语言代码里有它不接受的字符（只允许字母、数字、"
                       "连字符、下划线）。\n本次命令行：%s"
                       % (LAUNCHER, code, " ".join(cmd)))

    if lang:
        return True, "已通过 %s 启动游戏，本次使用 %s.txt。" % (LAUNCHER, lang)
    return True, "已通过 %s 启动游戏。" % LAUNCHER


def launch_vanilla(target):
    """直接启动原版 PR2.exe，不注入任何东西。返回 (是否成功, 说明)。

    用来对比：同一个界面到底有没有换成译文。游戏按相对路径读资源，
    所以 cwd 必须是游戏目录。
    """
    if not is_game_dir(target):
        return False, "该目录下没有 %s，请重新选择游戏目录。" % GAME_EXE
    try:
        subprocess.Popen([os.path.join(target, GAME_EXE)], cwd=target,
                         close_fds=True)
    except OSError as exc:
        return False, "启动 %s 失败：%s\n\n%s" % (GAME_EXE, exc,
                                                _oserr_hint(exc))
    return True, "已直接启动 %s（未注入任何组件，显示原版英文）。" % GAME_EXE


def _oserr_hint(exc):
    """把 WinError 翻译成能照着做的话。返回纯人话的补充说明。

    光把 %s 抛给用户等于让他去猜 WinError 193 是什么意思。
    """
    win = getattr(exc, "winerror", None)
    if win == 193:
        return ("这个文件不是能直接运行的程序 —— 通常是文件是空的、"
                "被截断了，或者是别的架构的 exe（32/64 位不匹配）。\n"
                "如果是空的，说明复制没成功，重新「复制到游戏目录」一次。")
    if win == 2:
        return "文件不存在。检查游戏目录是否选对了。"
    if win in (5,):
        return ("没有权限。检查文件是不是设成了只读，"
                "或者游戏正在运行占着它。")
    return ""


def editor_health(port, timeout=0.25):
    """问一句「这个端口上跑的是我们的编辑器吗」，是就返回它的自述。

    查的是 /api/health，而不是「端口通不通」：8777 附近完全可能有别的东西
    在监听，端口通不代表是我们的服务，认错比没认出来更难查。
    """
    url = "http://127.0.0.1:%d/api/health" % port
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            info = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return info if isinstance(info, dict) and info.get("app") == "pr2-editor" else None


def _port_open(port, timeout=0.05):
    """这个端口上有没有人 accept。只做 TCP 握手，不问 HTTP。

    先用它筛一遍再发请求：没有监听者的端口在正常机器上立刻 refused，
    但在网络栈被拦的环境里会一直等到超时 —— 24 个端口逐个等就是十几秒。
    握手超时放得很短，代价只是偶尔漏掉一个响应极慢的实例。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def find_editor():
    """找已经在跑的编辑器。返回 (port, info)；没有就是 (None, None)。

    先做 TCP 探测、再问 /api/health：只有真正有监听者的端口才值得发请求。
    """
    for port in range(EDITOR_PORT_BASE, EDITOR_PORT_BASE + EDITOR_PORT_TRIES):
        if not _port_open(port):
            continue
        info = editor_health(port)
        if info:
            return port, info
    return None, None


def wait_editor(proc, token, timeout=20.0):
    """等刚拉起的这个进程把 /api/health 答上来。

    认的是**令牌**而不是 pid：Windows 上的 python.exe 有时只是个转接器，
    Popen 拿到的 pid 与真正在监听的进程不是同一个（实测差了一个 pid，
    于是「明明起来了」被判成「20 秒没响应」）。
    """
    end = time.time() + timeout
    exited_at = None
    # 先给子进程半秒：它要在 exec 之后才 bind，立刻扫必然扫空，
    # 白扫一遍 24 个端口。
    time.sleep(0.5)
    while time.time() < end:
        port, info = find_editor()
        if info and token and info.get("token") == token:
            return port, info
        if proc is not None and proc.poll() is not None:
            # 转接器退出不代表服务没起来，再等两秒看看；
            # 真起不来（比如端口全占）就没必要干等到超时。
            exited_at = exited_at or time.time()
            if time.time() - exited_at > 2:
                return None, None
        time.sleep(0.3)
    return None, None


def editor_shutdown(port, timeout=3.0):
    """请编辑器自己退出，并等它真的消失。返回是否已经停了。

    走 /api/shutdown 而不是直接杀进程：不依赖进程权限，也不用管
    python.exe 是不是中转进程 —— 真正在监听的那个会自己退出，
    它的控制台窗口随之关闭，端口也一起放掉。
    """
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/shutdown" % port, method="POST")
        urllib.request.urlopen(req, timeout=1.5).read()
    except Exception:
        return False
    end = time.time() + timeout
    while time.time() < end:
        if not editor_health(port, timeout=0.3):
            return True
        time.sleep(0.2)
    return False


def open_editor():
    """拉起本地 Web 编辑器服务，返回 (是否成功, 说明, Popen, 令牌)。

    编辑器是一个长驻的 HTTP 服务（src\\editor\\server.py），不是一次性
    任务 —— 所以**不等待它退出**，只把它拉起来、把句柄交给调用方。
    句柄是用来收尾的：窗口关掉时由 start 负责把它停掉，不留孤儿进程。

    起服务时带 --no-open：浏览器由这边在确认 /api/health 通了之后再开，
    免得服务还没起来就先弹一个打不开的页面。

    令牌从环境变量传进去，服务在 /api/health 里原样回传 —— 这样即使
    机器上还有别的实例，也能认出「哪个是我刚起的这个」。
    """
    if not os.path.isdir(EDITOR_DIST):
        return False, ("前端还没构建（缺少 %s）。\n\n"
                       "先在仓库里跑一次：\n"
                       "  cd src\\editor\n"
                       "  npm install\n"
                       "  npm run build" % EDITOR_DIST), None, None

    # 用 python.exe 而不是 pythonw.exe：**故意留一个控制台窗口**。
    # 服务打印的地址、端口被占时的提示、请求报错都在那个窗口里，
    # 关掉它就等于停掉编辑器 —— 这是这个常驻服务最直观的把手。
    token = uuid.uuid4().hex
    env = child_env()
    env["PR2_EDITOR_TOKEN"] = token
    try:
        proc = subprocess.Popen(
            [_server_exe(), os.path.join(EDITOR_DIR, "server.py"), "--no-open"],
            cwd=EDITOR_DIR, env=env, close_fds=True)
    except OSError as exc:
        return False, "启动编辑器失败：%s" % exc, None, None
    return True, "编辑器进程已拉起。", proc, token


def _server_exe():
    """挑一个**带控制台**的 Python 来起编辑器服务。

    工具窗口自己是 pythonw 起的（没有控制台），拿它启动服务就什么都看不见；
    这里优先用同目录的 python.exe。服务只用标准库，不需要任何 venv。
    """
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.isfile(cand):
            return cand
    return exe


# ------------------------------------------------------------ 构建

def child_env():
    r"""子进程环境：UTF-8 + 无缓冲。

    Windows 上 Python 给文本流套的是**控制台代码页**（简体中文机器是
    cp936），而这里把管道按 utf-8 解 —— 两边不一致，中文输出就成了
    一串「已生成」模样的乱码。PYTHONIOENCODING 管的就是文本流本身，
    比事后猜编码可靠（猜错了会把正常文本也毁掉）。

    PYTHONUNBUFFERED：输出要实时进日志，不能攒够一块才吐。
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def read_lines(proc, events):
    r"""把子进程的输出逐行送进队列。

    Python 子进程由 child_env() 统一成 UTF-8；MSVC 的 cl.exe 不受它
    影响，按控制台代码页写中文提示。所以每行先按 utf-8 解，解不动
    再退回代码页 —— 只在确实解不出时才换，不会把正常文本弄坏。
    """
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError:
            # mbcs = 系统 ANSI 代码页（简体中文机器是 cp936），
            # 也就是 cl.exe 写中文提示时用的那套。不用
            # getpreferredencoding()：开了 UTF-8 模式的 Python 会
            # 把它报成 utf-8，退回原处等于没退。
            line = line.decode("mbcs", "replace")
        events.put(("line", line))


def build_pack(lang, out_dir, events):
    """在子进程里跑 compile_pack.py，把输出送到事件队列。

    不直接 import 它：那个脚本会做 import-time 的路径推导，而且
    它的 stdout 是给命令行看的，逐行读回来反而更可控 —— 失败时
    整个 stderr 都能显示出来。

    脚本自己已经在「编不出条目」时报错退出码 1 且不写文件了。
    这里仍查一次条目数兜底：空包装进游戏等于没生效，而 GUI 是
    会把它复制过去的最后一道关口。
    """
    script = os.path.join(HERE, "compile_pack.py")
    # --no-fonts：字体由 run_build 在所有语言编完后统一做一次，
    # 免得选三种语言就重裁三遍字体。
    cmd = [sys.executable, script, "--lang", lang, "--out", out_dir, "--no-fonts"]
    events.put(("line", "[%s] 编译中…" % lang))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=ROOT, env=child_env(),
    )
    read_lines(proc, events)
    code = proc.wait()

    pack = os.path.join(out_dir, "%s.txt" % lang)
    if code == 0:
        entries = count_entries(pack)
        if entries == 0:
            events.put(("line", "[%s] 失败：%s 一条译文都没有，已拦下。"
                        % (lang, pack)))
            try:
                os.remove(pack)
            except OSError:
                pass
            code = 1
        else:
            events.put(("line", "[%s] 完成，%d 条，%s.txt（%d 字节）"
                        % (lang, entries, lang, os.path.getsize(pack))))
    else:
        events.put(("line", "[%s] 失败，退出码 %d" % (lang, code)))
    events.put(("lang_done", (lang, code)))
    return code


def count_entries(pack_path):
    """语言包里的条目数。空行与 # 注释行不算条目。"""
    if not os.path.isfile(pack_path):
        return 0
    n = 0
    with open(pack_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                n += 1
    return n


def build_injector(events):
    """在子进程里跑 build_injector.bat，编译 PR2TextSource.dll 与
    PR2Launcher.exe。

    走 bat 而不是直接调 cl：脚本自己会定位 MSVC 与 SDK，那是它的职责；
    这里只负责把输出转成事件、以及把退出码如实带回来。
    """
    events.put(("line", "[注入器] 编译中…"))
    proc = subprocess.Popen(
        ["cmd", "/c", INJECTOR_BAT, "--no-pause"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=ROOT, env=child_env(),
    )
    read_lines(proc, events)
    code = proc.wait()

    missing = missing_outputs(need_pack=False)
    if code == 0 and missing:
        code = 1
        events.put(("line", "[注入器] 失败：产物不完整，缺少 %s"
                             % "、".join(missing)))
    elif code == 0:
        events.put(("line", "[注入器] 完成，%s"
                             % "、".join(FLAT_FILES)))
    else:
        events.put(("line", "[注入器] 失败，退出码 %d" % code))
    events.put(("injector_done", code))
    return code


def run_build(langs, events):
    """构建线程主体。语言逐个编译，任何一个失败就停下。"""
    try:
        if not langs:
            events.put(("line", "没有勾选任何语言。"))
            events.put(("build_failed", ""))
            return

        os.makedirs(PACK_OUT, exist_ok=True)

        for lang in langs:
            events.put(("lang_start", lang))
            code = build_pack(lang, PACK_OUT, events)
            if code != 0:
                events.put(("build_failed", lang))
                return

        # locale.ini 决定 DLL 读哪个语言包。它是**可写的配置**，不是纯
        # 模板：GUI 改语言时会直接写 build\PR2Packs\locale.ini（以及游戏
        # 目录那份）。所以这里只在它还不存在时才用 src\locale.ini 兜底
        # 建一份 —— 无条件覆盖会把用户刚选的语言打回 language=zh。
        ini_out = os.path.join(PACK_OUT, "locale.ini")
        if os.path.isfile(ini_out):
            events.put(("line", "已保留现有 %s\\locale.ini（%s）"
                        % (PACK_DIR, read_ini_language(ini_out) or "未设置")))
        elif os.path.isfile(LOCALE_INI):
            shutil.copy2(LOCALE_INI, ini_out)
            events.put(("line", "已按 %s 建立 %s\\locale.ini"
                        % (os.path.basename(LOCALE_INI), PACK_DIR)))
        else:
            events.put(("line", "缺少 %s，无法建立 %s\\locale.ini，"
                                "游戏将全程显示英文"
                        % (LOCALE_INI, PACK_DIR)))
            events.put(("build_failed", ""))
            return

        # 字体：语言包编完后统一检查一次。译文里出现新字而字体没跟上，
        # 游戏里就画成空白 —— 所以并进同一个构建动作，别让人单记一步。
        try:
            sys.path.insert(0, HERE)
            import subset_fonts
            events.put(("line", "检查字体…"))
            ok, msg = subset_fonts.ensure_fonts(
                log=lambda m: events.put(("line", m)))
            events.put(("line", "字体：" + msg))
        except Exception as exc:                  # 字体失败不该让构建失败
            events.put(("line", "字体检查跳过：%s" % exc))

        # 术语对照表：同样是「跟着译文走」的产物，顺手重生成一份，
        # 省得改完译文忘了同步。产物在 build\glossary\，不进仓库。
        try:
            script = os.path.join(HERE, "glossary.py")
            events.put(("line", "生成术语对照…"))
            cmd = [sys.executable, script]
            for l in langs:
                cmd += ["--lang", l]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=ROOT, env=child_env())
            read_lines(proc, events)
            proc.wait()
        except Exception as exc:
            events.put(("line", "术语对照跳过：%s" % exc))

        events.put(("build_ok", list(langs)))
    except Exception as exc:                      # 兜底，别让线程静默死掉
        events.put(("line", "构建出错：%s" % exc))
        events.put(("build_failed", ""))


