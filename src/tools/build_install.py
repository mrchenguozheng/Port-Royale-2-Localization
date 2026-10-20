#!/usr/bin/env python3
# coding: utf-8
r"""src/tools/build_install.py — Port Royale 2 本地化工具窗口

一个窗口分三段，段号就是步骤号：

1. 构建 —— 注入器（编译 DLL 与启动器）与语言包（编译勾选的语言）；
2. 部署 —— 选游戏目录，把产物复制进去；
3. 启动 —— 用注入器启动器拉起游戏，或直接跑原版对比。

PR2.exe 全程不被修改。部署好之后用装到游戏目录里的
PR2Launcher.exe 启动游戏，语言包在启动时读取，
所以改完翻译只要重新构建 + 重新部署。

本脚本是整个流程的唯一入口，每一步都由按钮单独触发，
不会自动替你编译。
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

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    # 并非所有 Python 都带 tkinter。直接告诉用户手工复制哪些文件，
    # 而不是抛一段 traceback。
    sys.stderr.write(
        "[pr2loc] This Python has no tkinter, so the window cannot open.\n"
        "[pr2loc] Copy these into your Port Royale 2 folder by hand:\n"
        "[pr2loc]   PR2Launcher.exe\n"
        "[pr2loc]   PR2TextSource.dll\n"
        "[pr2loc]   PR2Packs\\\n"
    )
    sys.exit(2)


HERE = os.path.dirname(os.path.abspath(__file__))
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
    return T.target_langs()


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
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return "copied"
    except OSError:
        return "failed"


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
        "id": "gog-fr-1.1.2.3",
        "label": "GOG 法语版 1.1.2.3",
        "sha256": "EF0E97D40F8DDF24186D18D39D07F12C562949D005654E99B7C1D21429110FA5",
        "note": "法文界面文本编在 exe 里；同样可注入。",
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


# ------------------------------------------------------------ 界面

#: 危险动作统一用这个红。白字 + 深红底，和窗口里其它按钮一眼分开。
_DANGER_BG = "#b3261e"
_DANGER_BG_HOVER = "#8c1d18"


class ConfirmDialog(tk.Toplevel):
    """自定义确认框 —— 按钮文字自己定，不用「是/否」。

    messagebox 只给「是的 / 否」，对「删除补丁」这种事说不清：用户看到的
    「要继续吗？」配「是」并不告诉他按下之后会做什么。这里把动词写在按钮上
    （「继续删除」「确认删除」），并且让危险按钮是红的。

    body 里的清单直接换行显示，所以「第二次确认看不到要删什么」不会再发生。

    choices 给出时，正文下面会列成一排复选框（默认全勾），只有勾选的才算数；
    self.selected 返回勾中的那些。一个都不勾时按「确认」不会关窗，而是提示 ——
    否则按下去等于什么都没做，用户却以为删过了。
    """

    def __init__(self, master, title, body, ok_text, cancel_text="取消",
                 danger=True, choices=None):
        super().__init__(master)
        self.result = False
        self._choices = list(choices or [])
        self.selected = []                        # 默认一个都不勾
        self.vars = []
        self.title(title)
        self.transient(master)
        self.resizable(False, False)

        box = ttk.Frame(self, padding=16)
        box.pack(fill="both", expand=True)

        head = ttk.Frame(box)
        head.pack(fill="x")
        ttk.Label(head, text="⚠", foreground=_DANGER_BG,
                  font=("Segoe UI", 16, "bold")).pack(side="left", padx=(0, 8))
        ttk.Label(head, text=title,
                  font=("Segoe UI", 10, "bold")).pack(side="left")

        ttk.Label(box, text=body, justify="left", wraplength=560).pack(
            fill="x", pady=(10, 10))

        if choices:
            wrap = ttk.Frame(box, borderwidth=1, relief="solid", padding=8)
            wrap.pack(fill="x", pady=(0, 10))
            allvar = tk.BooleanVar(value=False)

            def toggle_all():
                for v in self.vars:
                    v.set(allvar.get())

            ttk.Checkbutton(wrap, text="全选 / 全不选", variable=allvar,
                            command=toggle_all).pack(anchor="w", pady=(0, 4))
            for c in choices:
                v = tk.BooleanVar(value=False)
                self.vars.append(v)
                ttk.Checkbutton(wrap, text=c, variable=v).pack(
                    anchor="w", padx=(18, 0))

        self.warn = ttk.Label(box, text="", foreground=_DANGER_BG)
        self.warn.pack(fill="x")

        row = ttk.Frame(box)
        row.pack(fill="x", pady=(6, 0))
        if danger:
            ok = tk.Button(row, text=ok_text, command=self._ok,
                           fg="white", bg=_DANGER_BG,
                           activebackground=_DANGER_BG_HOVER,
                           activeforeground="white", relief="flat",
                           padx=14, pady=3, cursor="hand2")
        else:
            ok = ttk.Button(row, text=ok_text, command=self._ok)
        ok.pack(side="right")
        cancel = ttk.Button(row, text=cancel_text, command=self._cancel)
        cancel.pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Return>", lambda e: self._ok())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        try:
            px, py = master.winfo_rootx(), master.winfo_rooty()
            pw, ph = master.winfo_width(), master.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry("+%d+%d" % (px + (pw - w) // 2, py + (ph - h) // 3))
        except tk.TclError:
            pass
        self.grab_set()
        cancel.focus_set()          # 默认落在「取消」上，回车不会误删

    def _ok(self):
        if self.vars:
            self.selected = [c for c, v in zip(self._choices, self.vars) if v.get()]
            if not self.selected:
                self.warn.configure(
                    text="一个都没勾选 —— 这样不会删除任何东西。取消或至少勾一项。")
                return
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


class App(tk.Tk):
    POLL_MS = 80
    #: 构建结束后按钮还要多锁一会儿。构建常常不到一秒，禁用状态
    #: 一闪而过，用户会以为没生效而连点；这段时间里重复构建
    #: 也确实没有意义（产物一样）。
    BUILD_COOLDOWN_MS = 1200

    def __init__(self, do_build):
        super().__init__()
        self.title("Port Royale 2 本地化工具")
        self.resizable(True, True)
        self.minsize(560, 520)

        self.events = queue.Queue()
        self.worker = None
        self.built_langs = []
        self.total = 0
        self.done = 0
        self.building = False
        self.compiling = False
        self.installing = False
        self.editing = False
        #: 编辑器准备工作开始的时刻 + 当前在第几步 —— 用来在状态栏里
        #: 显示「已等 N 秒」，让用户看得出它是在干活，而不是卡住了。
        self._editor_t0 = 0.0
        self._editor_step = ""
        #: 编辑器服务的 pid / 端口 / 句柄。本窗口起的，或者探测到的旧实例。
        #: 收了 pid 才能在关窗口时把它一起停掉，也才知道「停止」按钮该不该亮。
        self.editor_pid = None
        self.editor_proc = None
        self.editor_port = None
        #: 轮询计数：编辑器存活检查不用每 80ms 做一次。
        self._tick = 0
        self.installed_done = True
        self.build_cool = 0
        self.missing_injector = missing_outputs(need_pack=False)

        self.var_dir = tk.StringVar()
        #: 已记住的游戏版本（按 PR2.exe 的 SHA-256 索引）与当前选中项
        self.settings = load_settings()
        self.var_version = tk.StringVar()
        self._version_items = []
        self.status = tk.StringVar()
        #: 启动语言下拉。FOLLOW_LANG 是「不指定」，让 locale.ini 说话。
        self.var_lang = tk.StringVar(value=FOLLOW_LANG)
        #: 缓存游戏目录里已装的语言，换目录时用它判断列表要不要刷新。
        self.installed = []

        langs = available_langs()
        self.vars = {}
        for code in langs:
            v = tk.BooleanVar(value=True)
            self.vars[code] = v

        self._build_ui(langs, do_build)
        self._refresh_version_choices()
        self._restore_last_dir()
        self._sync()
        self._center()
        self._poll_id = self.after(self.POLL_MS, self._poll)

    # ---- 布局

    def _build_ui(self, langs, do_build):
        frm = tk.Frame(self, padx=14, pady=10)
        frm.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        # 日志吸收多余高度：窗口拉高时它变高，而不是按钮之间被撑开。
        self.rowconfigure(7, weight=1)

        # 分三段，顺序就是使用顺序：构建 -> 部署 -> 启动。
        # 每段一个 LabelFrame，读起来是步骤而不是控件堆。
        build_box = ttk.LabelFrame(frm, text="1  构建", padding=10)
        build_box.grid(row=0, column=0, sticky="we")
        build_box.columnconfigure(1, weight=1)

        deploy_box = ttk.LabelFrame(frm, text="2  部署到游戏目录", padding=10)
        deploy_box.grid(row=1, column=0, sticky="we", pady=(12, 0))
        deploy_box.columnconfigure(1, weight=1)

        run_box = ttk.LabelFrame(frm, text="3  启动", padding=10)
        run_box.grid(row=2, column=0, sticky="new", pady=(12, 0))

        # 编辑器不在三段流程里 —— 它改的是仓库里的译文，不碰游戏目录。
        # 硬塞进「构建」段会让人以为构建语言包要先开编辑器，所以单列一段。
        edit_box = ttk.LabelFrame(frm, text="4  译文编辑器（可选）", padding=10)
        edit_box.grid(row=3, column=0, sticky="we", pady=(12, 0))

        self._build_section(build_box, langs)
        self._deploy_section(deploy_box)
        self._run_section(run_box)
        self._editor_section(edit_box)
        # 开窗时游戏目录还是空的，先给一个只有「跟随」的下拉；
        # refresh_langs() 会在选定目录或装完之后填上真实语言。
        self.lang_box.configure(values=[FOLLOW_LANG])

        # -- 进度与日志。放在最后：它是结果，不是入口。
        self.bar = ttk.Progressbar(frm, mode="determinate", maximum=1.0)
        self.bar.grid(row=4, column=0, sticky="we", pady=(16, 2))
        self.lbl_status = tk.Label(
            frm, textvariable=self.status, anchor="w", justify="left")
        # 间距挂在状态行自己身上：进度条空闲时是 grid_remove 掉的，
        # 把间距挂在它上面等于空闲时什么间距都没有。
        self.lbl_status.grid(row=5, column=0, sticky="we", pady=(12, 0))

        ttk.Label(frm, text="日志").grid(row=6, column=0, sticky="w",
                                         pady=(10, 2))
        self.log = tk.Text(frm, height=8, width=62, state="disabled",
                           wrap="word", bg="#f4f4f4", relief="solid",
                           borderwidth=1)
        self.log.grid(row=7, column=0, sticky="nsew", pady=(0, 0))

        if self.missing_injector:
            self.status.set("注入器未构建，请先点上方按钮。")
        else:
            self.status.set("就绪")
        self._refresh_injector_label()

        if do_build:
            self.after(120, self.on_build)

    def _build_section(self, box, langs):
        """注入器与语言包。两行，各自独立触发。"""
        ttk.Label(box, text="注入器").grid(row=0, column=0, sticky="w")
        self.btn_injector = ttk.Button(
            box, text="构建注入器（DLL + 启动器）",
            command=self.on_build_injector)
        self.btn_injector.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.lbl_injector = tk.Label(box, anchor="w", justify="left")
        self.lbl_injector.grid(row=0, column=2, sticky="w", padx=(10, 0))

        ttk.Label(box, text="语言包").grid(
            row=1, column=0, sticky="nw", pady=(8, 0))

        # 勾选项按固定列宽铺开，满了自动换行。
        # 单行无限拉伸在语言多时会把窗口撑到比屏幕还宽，右侧的
        # 「构建所选语言」按钮会跑出屏幕点不到。
        cols = max(4, min(6, len(langs) or 1))
        lang_grid = ttk.Frame(box)
        lang_grid.grid(row=1, column=1, columnspan=2, sticky="w",
                       padx=(10, 0), pady=(8, 0))
        if langs:
            for i, code in enumerate(langs):
                ttk.Checkbutton(
                    lang_grid, text=code, variable=self.vars[code],
                    command=self._sync,
                ).grid(row=i // cols, column=i % cols, sticky="w",
                       padx=(0, 14), pady=(0, 2))

            # 按钮无条件创建：_sync 每轮轮询都要访问它，
            # 只在有语言时建会直接 AttributeError。
            rows = (len(langs) + cols - 1) // cols
            self.btn_build = ttk.Button(
                box, text="构建所选语言", command=self.on_build)
            self.btn_build.grid(row=rows + 1, column=0, columnspan=3,
                                sticky="w", pady=(8, 0))
        else:
            tk.Label(lang_grid, text="src\\translations\\ 下没有可构建的语言",
                     fg="#a00000").grid(row=0, column=0, sticky="w")
            self.btn_build = ttk.Button(
                box, text="构建所选语言", command=self.on_build,
                state="disabled")
            self.btn_build.grid(row=1, column=1, sticky="w", pady=(8, 0))

    def _deploy_section(self, box):
        """版本识别 + 游戏目录 + 部署。

        版本一段放在最上面：先认出是哪个构建，再决定用哪个目录，
        顺序与用户的心智一致（「我装的是哪个版本」→「它在哪」）。
        """
        ttk.Label(box, text="已知版本").grid(row=0, column=0, sticky="w")
        self.version_box = ttk.Combobox(
            box, textvariable=self.var_version, state="readonly", width=44)
        self.version_box.grid(row=0, column=1, sticky="we", padx=(10, 0))
        self.version_box.bind("<<ComboboxSelected>>", self.on_pick_version)

        ver_btns = ttk.Frame(box)
        ver_btns.grid(row=0, column=2, sticky="e", padx=(10, 0))
        self.btn_remember = ttk.Button(
            ver_btns, text="记住当前目录", width=12, command=self.on_remember_version)
        self.btn_remember.grid(row=0, column=0)
        self.btn_check = ttk.Button(
            ver_btns, text="检查补丁…", width=10, command=self.on_check_patch)
        self.btn_check.grid(row=0, column=1, padx=(6, 0))

        self.lbl_version = tk.Label(box, text="", anchor="w", justify="left")
        self.lbl_version.grid(row=1, column=0, columnspan=3, sticky="w",
                              pady=(4, 0))

        ttk.Label(box, text="游戏目录").grid(row=2, column=0, sticky="w",
                                            pady=(10, 0))
        dir_row = ttk.Frame(box)
        dir_row.grid(row=2, column=1, sticky="we", padx=(10, 0), pady=(10, 0))
        dir_row.columnconfigure(0, weight=1)
        tk.Entry(dir_row, textvariable=self.var_dir, width=44,
                 state="readonly").grid(row=0, column=0, sticky="we")
        ttk.Button(dir_row, text="浏览…", width=8,
                   command=self.on_browse).grid(row=0, column=1, padx=(6, 0))
        self.btn_install = ttk.Button(
            box, text="复制到游戏目录", width=16, command=self.on_install)
        self.btn_install.grid(row=2, column=2, padx=(10, 0), pady=(10, 0))

        ttk.Label(box, text="须含 %s。只复制构建产物，内容相同就跳过。"
                  % GAME_EXE).grid(row=3, column=0, columnspan=3,
                                   sticky="w", pady=(6, 0))

        # 危险操作：把补丁从游戏目录里删干净。放在部署段里，
        # 但**不**跟着 busy() 一起锁 —— 复制失败时恰恰需要它来善后。
        self.btn_remove = tk.Button(
            box, text="移除补丁（危险）…", command=self.on_remove_patch,
            fg="white", bg=_DANGER_BG, activebackground=_DANGER_BG_HOVER,
            activeforeground="white", relief="flat", padx=10, pady=2,
            cursor="hand2")
        self.btn_remove.grid(row=4, column=2, sticky="e", padx=(10, 0), pady=(8, 0))
        ttk.Label(box, text="只删本补丁的文件：启动器、DLL、语言包与它的日志；"
                  "PR2.exe 不会动。").grid(row=4, column=0, columnspan=2,
                                          sticky="w", pady=(8, 0))

    def _run_section(self, box):
        """启动语言 + 启动与保存。

        启动按钮只在语言**确有变化**时顺手保存，没变化就一个字都不写；
        这次跑哪个语言始终由下拉决定，通过 --lang 传给子进程。
        「保存语言设置」是给「不想进游戏、只想改配置」用的入口，
        走同一条保存路径。
        """
        ttk.Label(box, text="启动语言").grid(row=0, column=0, sticky="w")
        self.lang_box = ttk.Combobox(
            box, textvariable=self.var_lang, state="readonly", width=22)
        self.lang_box.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.lang_box.bind("<<ComboboxSelected>>", self.on_pick_lang)
        ttk.Label(box, text="下拉本身不保存").grid(
            row=0, column=2, sticky="w", padx=(8, 0))

        self.btn_play = ttk.Button(box, text="启动游戏（已注入）",
                                   command=self.on_play)
        self.btn_play.grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.btn_save_lang = ttk.Button(box, text="保存语言设置",
                                        command=self.on_save_lang)
        self.btn_save_lang.grid(row=1, column=1, sticky="w", padx=(8, 0),
                                pady=(10, 0))
        self.btn_vanilla = ttk.Button(box, text="运行游戏（原版）",
                                      command=self.on_vanilla)
        self.btn_vanilla.grid(row=1, column=2, sticky="w", padx=(8, 0),
                              pady=(10, 0))
        ttk.Label(box, text="原版不注入任何组件，也不保存语言设置。"
                  ).grid(row=2, column=0, columnspan=3, sticky="w",
                         pady=(6, 0))
        ttk.Button(box, text="关闭", width=10,
                   command=self.destroy).grid(row=3, column=2, sticky="e",
                                              pady=(10, 0))
        box.columnconfigure(2, weight=1)

    def _editor_section(self, box):
        """译文编辑器入口。跟前三段无关，单列一段。

        编辑器由这个窗口**启动并收尾**：已经开着就复用（不再起第二个），
        窗口关掉就一起停，不留孤儿进程。前端（dist\\ 的静态文件）和后端
        （FastAPI）跑在同一个进程里 —— 服务顺便把前端托管了 ——
        所以这里只有这一个进程要管。
        """
        self.btn_editor = ttk.Button(
            box, text="打开译文编辑器", command=self.on_editor)
        self.btn_editor.grid(row=0, column=0, sticky="w")

        self.btn_editor_stop = ttk.Button(
            box, text="停止编辑器", command=self.on_stop_editor, state="disabled")
        self.btn_editor_stop.grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Label(box, text="改 src\\translations\\ 下的译文。不需要装任何依赖；"
                  "关掉本窗口会一并停掉编辑器。").grid(
            row=0, column=2, sticky="w", padx=(10, 0))
        box.columnconfigure(2, weight=1)

    def _forget_editor(self):
        self.editor_pid = None
        self.editor_proc = None
        self.editor_port = None

    def _kill_editor(self):
        """停掉编辑器：先请它自己退，不行再强杀。

        1) /api/shutdown：不给权限问题、也不怕 python.exe 是个中转进程 ——
           真正监听的进程自己退出，控制台窗口跟着关。
        2) taskkill /T：服务没响应（比如卡死）时兜底，杀整棵树。
           只杀父进程会留下还在监听的孤儿，端口继续占着。
        """
        pid = self.editor_pid
        port = self.editor_port
        stopped = editor_shutdown(port) if port else False
        if not stopped:
            # pid 可能是 /api/health 报上来的真实服务进程；还没探测完就关窗口时
            # 只有 Popen 的 pid（可能是中转进程），两种都用 /T 杀整棵树。
            target = pid or (self.editor_proc.pid if self.editor_proc else None)
            if target:
                try:
                    subprocess.run(["taskkill", "/PID", str(target), "/T", "/F"],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                except OSError:
                    pass
        proc = self.editor_proc
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()      # 对自家子进程一定有权限，再兜一道
            except OSError:
                pass
        self._forget_editor()

    def on_stop_editor(self):
        """停掉编辑器。pid 可能是本窗口起的，也可能是探测到的旧实例。"""
        if not self.editor_pid:
            port, info = find_editor()
            if info:
                self.editor_pid = int(info.get("pid") or 0) or None
                self.editor_port = port
        if not self.editor_pid:
            self.status.set("没有找到正在运行的编辑器。")
            self._sync()
            return
        pid = self.editor_pid
        port = self.editor_port
        self._kill_editor()
        # 只看**原来那个端口**：别的实例（或用户自己另开的）不该影响判断。
        if port and editor_health(port):
            self.status.set("停止命令已发出，但编辑器仍在运行。")
            self._log("停止后端口 %d 仍有响应，可能卡住了。" % port)
        else:
            self.status.set("编辑器已停止。")
            self._log("已停止编辑器（pid %d）。" % pid)
        self._sync()

    def on_editor(self):
        if self.busy():
            return
        # 已经有一个在跑（可能是上一次 start 留下的）：复用，不再起第二个。
        # 以前每点一次就新起一个，结果 8777/8778/8779 各躺着一个服务。
        port, info = find_editor()
        if info:
            self.editor_pid = int(info.get("pid") or 0) or None
            self.editor_port = port
            webbrowser.open("http://127.0.0.1:%d/" % port)
            self.status.set("编辑器已在运行（端口 %d），已打开浏览器。" % port)
            self._log("复用已在运行的编辑器：端口 %d，pid %s"
                      % (port, self.editor_pid))
            self._sync()
            return

        self._begin_log("译文编辑器")
        # 起服务本身只要一两秒，但「等它真的答话」最多 20 秒。进度条用
        # 不确定模式，同时状态文字一直在报已经等了多少秒 —— 这样"在启动"
        # 和"卡死了"能一眼分开。
        self.bar.configure(mode="indeterminate")
        self.bar.start(80)
        self._editor_t0 = time.time()
        self._editor_step = "启动服务"
        self.status.set("正在启动编辑器…")
        self.editing = True
        self._set_state(self.btn_editor, "disabled")
        self.worker = threading.Thread(target=self._editor_worker, daemon=True)
        self.worker.start()
        self._sync()

    def _editor_worker(self):
        """启动 + 等服务答话。放线程里是因为等 /api/health 最多要 20 秒，
        放主线程会把窗口冻住 —— 用户会以为程序卡死了。
        """
        ok, message = False, "编辑器准备时出现未知错误。"
        pid, port, proc = None, None, None
        try:
            started, msg, child, token = open_editor()
            if not started:
                ok, message = False, "编辑器启动失败：\n\n" + msg
            else:
                # 先记下句柄：等待期间用户可能直接关窗口，那时要靠它收尾。
                self.editor_proc = child
                # 起进程 ≠ 起来了：要等它真的能回答 /api/health，
                # 否则浏览器会在服务还没监听时打开一个打不开的页面。
                port, info = wait_editor(child, token)
                if not info:
                    ok, message = False, (
                        "编辑器进程起来了，但 20 秒内没有响应。\n\n"
                        "看一下它那个控制台窗口里的报错。")
                else:
                    proc = child
                    pid = int(info.get("pid") or 0) or child.pid
                    webbrowser.open("http://127.0.0.1:%d/" % port)
                    message = "编辑器已启动（端口 %d），浏览器已打开。" % port
                    ok = True
        except Exception as exc:      # 线程里抛出去没人接，界面会一直卡在「准备中」
            ok, message = False, "编辑器准备时出错：%s" % exc
        finally:
            self.events.put(("editor_ready", {"ok": ok, "message": message,
                                              "pid": pid, "port": port,
                                              "proc": proc}))
        if not ok:
            self.events.put(("line", message))

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 3
        self.geometry("+%d+%d" % (max(x, 0), max(y, 0)))

    # ---- 状态

    def selected_langs(self):
        return [c for c in sorted(self.vars) if self.vars[c].get()]

    def busy(self):
        return (self.building or self.compiling or self.installing
                or self.editing)

    def end_build(self):
        """构建线程收尾：进冷却，之后才允许再点。

        冷却用 self.after 而不是 busy()：构建常常不到一秒，
        禁用态一闪而过，重复点击的意图却很清楚。
        """
        self.building = False
        self.build_cool = 1
        self.after(self.BUILD_COOLDOWN_MS, self._clear_cool)

    def _clear_cool(self):
        self.build_cool = 0
        self._sync()

    def ready_to_play(self):
        """与本次构建无关：游戏目录里已经装好启动器就能跑，
        不要求这次构建过语言包。"""
        d = self.var_dir.get()
        return (not self.busy()
                and is_game_dir(d)
                and launcher_installed(d))

    def ready_to_vanilla(self):
        d = self.var_dir.get()
        return not self.busy() and is_game_dir(d)

    def _refresh_injector_label(self):
        """按 missing_injector 刷新注入器状态标签。"""
        self.missing_injector = missing_outputs(need_pack=False)
        if self.missing_injector:
            self.lbl_injector.configure(
                text="未构建，缺少：%s" % "、".join(self.missing_injector),
                fg="#a00000")
        else:
            self.lbl_injector.configure(
                text="已就绪（%s）" % "、".join(FLAT_FILES), fg="#006000")

    def _set_state(self, widget, state):
        """只在状态真的变了时才 configure。

        ttk 控件的 active（悬停高亮）是瞬态标志，任何一次 configure()
        都会把它清掉。而 _sync() 由 _poll() 每 80ms 调一次，无条件写
        的话等于每 80ms 擦一次悬停态 —— 鼠标停在按钮上时高亮只闪一下。
        「浏览」和「关闭」不闪，正是因为它们不在 _sync() 里。
        """
        if str(widget["state"]) != state:
            widget.configure(state=state)

    def _sync(self):
        locked = self.busy()
        self._set_state(
            self.btn_install,
            "normal" if (not locked
                         and not self.missing_injector
                         and bool(self.built_langs)
                         and is_game_dir(self.var_dir.get()))
            else "disabled")
        self._set_state(
            self.btn_play,
            "normal" if self.ready_to_play() else "disabled")
        # 没有需要保存的东西时禁用「保存语言设置」：按钮本身就是
        # 「这里有变化要落盘」的提示，亮着却什么都不做等于骗人。
        self._set_state(
            self.btn_save_lang,
            "normal" if (not locked and self.lang_to_save()) else "disabled")
        self._set_state(
            self.btn_vanilla,
            "normal" if self.ready_to_vanilla() else "disabled")
        self._set_state(
            self.btn_build,
            "disabled" if locked or self.build_cool or not self.vars
            else "normal")
        self._set_state(
            self.btn_injector,
            "disabled" if locked else "normal")
        self._set_state(
            self.btn_editor,
            "disabled" if locked else "normal")
        # 「停止编辑器」只在确实知道有个实例在跑时才是亮的。
        self._set_state(
            self.btn_editor_stop,
            "normal" if (not locked and self.editor_pid) else "disabled")
        # 没有已装语言包时无法指定语言，下拉只剩「跟随 locale.ini」。
        self._set_state(
            self.lang_box,
            "readonly" if (not locked and self.installed) else "disabled")
        # 空闲时不显示进度条：一条 0% 的灰带看着像卡住了。
        # grid 过的控件用 grid_remove 收起来，不影响它继续占同一格。
        # 同样只在真的需要时调，grid/grid_remove 也是重绘。
        if self.busy():
            if not self.bar.winfo_ismapped():
                self.bar.grid()
        elif self.bar.winfo_ismapped():
            self.bar.grid_remove()

    def _log(self, text):
        """追加一行日志。只追加，不清空 —— 日志是唯一的排查线索。"""
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self._trim_log()
        self.log.see("end")
        self.log.configure(state="disabled")

    def _trim_log(self):
        """超量时丢最老的行，保留最近的 LOG_MAX_LINES 行。"""
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > LOG_MAX_LINES:
            self.log.delete("1.0", "%d.0" % (lines - LOG_MAX_LINES))

    def _begin_log(self, title):
        """开始一个新操作：空一行 + 标题行，好把几段记录分开。"""
        self._log("")
        self._log("── %s ── %s" % (title, time.strftime("%H:%M:%S")))

    # ---- 事件

    def on_build(self):
        if self.busy() or self.build_cool:
            return
        langs = self.selected_langs()
        if not langs:
            messagebox.showwarning("没有选择", "请至少勾选一种语言。")
            return
        self._begin_log("构建语言包：%s" % "、".join(langs))
        self.built_langs = []
        self.bar.configure(value=0.0, maximum=float(len(langs)))
        self.total = len(langs)
        self.done = 0
        # 先置位再起线程：busy() 不再靠 is_alive()，否则构建太快时
        # 两次轮询之间就结束，按钮看起来一直可点，还能重复起线程。
        self.building = True
        self.status.set("正在构建 %s…" % "、".join(langs))
        self.worker = threading.Thread(
            target=run_build, args=(langs, self.events), daemon=True)
        self.worker.start()
        self._sync()

    def on_build_injector(self):
        if self.busy():
            return
        self._begin_log("构建注入器")
        self.bar.configure(value=0.0, maximum=1.0)
        # 先置位再起线程，理由同 on_build。
        self.compiling = True
        self.status.set("正在编译注入器…")
        self.worker = threading.Thread(
            target=build_injector, args=(self.events,), daemon=True)
        self.worker.start()
        self._sync()

    def on_browse(self):
        chosen = filedialog.askdirectory(
            title="选择 Port Royale 2 的游戏目录（需包含 %s）" % GAME_EXE,
            mustexist=True)
        if chosen:
            self.set_dir(chosen)

    def set_dir(self, path):
        path = os.path.normpath(path)
        self.var_dir.set(path)
        self.refresh_langs()
        if not is_game_dir(path):
            self.status.set("该目录里没有 %s，请选游戏所在目录。" % GAME_EXE)
        else:
            self._sync_lang_display()
            self._auto_remember(path)
        self._update_version_status()
        self._sync()

    # ---- 版本记忆

    def _refresh_version_choices(self):
        """把已记住的版本填进下拉框（按上次使用时间倒序）。"""
        dirs = self.settings.get("dirs") or {}
        items = []
        for sha, rec in dirs.items():
            d = rec.get("dir") or ""
            if not d:
                continue
            items.append((rec.get("last_used") or "", sha, d))
        items.sort(reverse=True)
        self._version_items = [(sha, d) for _t, sha, d in items]
        labels = ["%s — %s" % (version_label(sha), d) for sha, d in self._version_items]
        self.version_box.configure(values=labels)
        cur = self.settings.get("current") or ""
        for i, (sha, _d) in enumerate(self._version_items):
            if sha == cur:
                self.var_version.set(labels[i])
                break
        else:
            self.var_version.set("")

    def _restore_last_dir(self):
        """启动时恢复上次的目录；没有就用最近记住的那个。"""
        last = (self.settings.get("last_dir")
                or (self._version_items[0][1] if self._version_items else ""))
        if last and is_game_dir(last):
            self.set_dir(last)

    def _auto_remember(self, path):
        """识别并静默记住当前目录（不弹窗，失败只写日志）。"""
        sha, build = identify_dir(path)
        if not sha:
            return
        dirs = self.settings.setdefault("dirs", {})
        rec = dirs.get(sha, {})
        rec.update({"dir": path, "label": version_label(sha),
                    "last_used": time.strftime("%Y-%m-%d %H:%M:%S")})
        dirs[sha] = rec
        self.settings["current"] = sha
        self.settings["last_dir"] = path
        save_settings(self.settings)
        self._refresh_version_choices()
        if build:
            self._log("识别到 %s（%s）" % (build["label"], sha[:12]))
        else:
            self._log("未识别的 PR2.exe（%s），仍可记住该目录。" % sha[:12])

    def _update_version_status(self):
        path = self.var_dir.get()
        if not is_game_dir(path):
            self.lbl_version.configure(
                text="未选择游戏目录，或目录里没有 %s。" % GAME_EXE, fg="#a00000")
            return
        sha, build = identify_dir(path)
        if not sha:
            self.lbl_version.configure(text="无法读取 %s。" % GAME_EXE, fg="#a00000")
            return
        known = "已记住" if sha in (self.settings.get("dirs") or {}) else "未记住"
        if build:
            self.lbl_version.configure(
                text="%s ｜ %s ｜ SHA %s… ｜ %s" % (build["label"], known, sha[:12], build["note"]),
                fg="#006000")
        else:
            self.lbl_version.configure(
                text="未知版本 ｜ %s ｜ SHA %s…（可用「记住当前目录」保存）" % (known, sha[:12]),
                fg="#a06000")

    def on_pick_version(self, _event=None):
        idx = self.version_box.current()
        if 0 <= idx < len(self._version_items):
            sha, path = self._version_items[idx]
            self.settings["current"] = sha
            self.settings["last_dir"] = path
            save_settings(self.settings)
            if is_game_dir(path):
                self.set_dir(path)
            else:
                self.status.set("该版本的目录已不存在：%s" % path)

    def on_remember_version(self):
        path = self.var_dir.get()
        if not is_game_dir(path):
            messagebox.showinfo("记住当前目录", "请先选择一个包含 %s 的游戏目录。" % GAME_EXE)
            return
        sha, build = identify_dir(path)
        if not sha:
            messagebox.showerror("记住当前目录", "读取 %s 失败。" % GAME_EXE)
            return
        self._auto_remember(path)
        self._update_version_status()
        label = build["label"] if build else "未知版本"
        messagebox.showinfo("记住当前目录",
                            "已记住：\n%s\n%s\n\nSHA-256：%s" % (label, path, sha))

    def on_check_patch(self):
        path = self.var_dir.get()
        if not is_game_dir(path):
            messagebox.showinfo("检查补丁", "请先选择一个包含 %s 的游戏目录。" % GAME_EXE)
            return
        rows = patch_report(path)
        lines = ["%s：%s%s" % (name, state, ("  — " + note) if note else "")
                 for name, state, note in rows]
        sha, build = identify_dir(path)
        head = build["label"] if build else "未知版本"
        messagebox.showinfo(
            "补丁状态 — %s" % head,
            "\n".join(lines) + "\n\nSHA-256：%s" % sha)

    def _sync_lang_display(self):
        """把 locale.ini 的设置显示到下拉框上，并说明读到了什么。

        三种情况分别给出不同的说法，免得用户对着一个说不清的下拉框
        猜游戏到底会跑哪种语言：
          · 文件在且有language=  -> 下拉显示那个语言，状态说明来源
          · 文件在但没有language= -> 下拉退回「跟随」，状态说明会看英文
          · 文件不存在（还没复制过去）-> 下拉退回「跟随」，状态说明复制完才有
        """
        d = self.var_dir.get()
        pack = os.path.join(d, PACK_DIR)
        ini = os.path.join(pack, "locale.ini")

        if not os.path.isdir(pack):
            self.var_lang.set(FOLLOW_LANG)
            self.status.set("找到 %s，但还没有 %s\\ —— 先构建并复制过去。"
                            % (GAME_EXE, PACK_DIR))
            return

        if not os.path.isfile(ini):
            self.var_lang.set(FOLLOW_LANG)
            self.status.set("找到 %s，但没有 %s\\locale.ini —— "
                            "语言未设置，游戏会显示英文。"
                            % (GAME_EXE, PACK_DIR))
            return

        code = read_ini_language(ini)
        if not code:
            self.var_lang.set(FOLLOW_LANG)
            self.status.set("%s\\locale.ini 里没有 language=，"
                            "游戏会显示英文。" % PACK_DIR)
            return

        self.var_lang.set(code if code in self.installed else FOLLOW_LANG)
        if code in self.installed:
            self.status.set("当前语言：%s（读自 %s\\locale.ini）。"
                            % (code, PACK_DIR))
        else:
            self.status.set("%s\\locale.ini 指定 %s，但游戏目录里没有 "
                            "%s.txt —— 游戏会显示英文。"
                            % (PACK_DIR, code, code))

    def refresh_langs(self):
        """按游戏目录里实际存在的语言包重建下拉列表。

        列表变过才重设 values：Combobox.configure 同样是重绘，
        在 80ms 的轮询路径上无条件写会连带影响交互。
        """
        langs = installed_langs(self.var_dir.get())
        if langs == self.installed:
            return
        self.installed = langs
        self.lang_box.configure(values=[FOLLOW_LANG] + langs)
        # 换目录等于换了一份 locale.ini，当前选择可能在新目录里不存在，
        # 这时按新目录的设置重新对齐，而不是留一个选不中的值。
        cur = self.var_lang.get()
        if cur != FOLLOW_LANG and cur not in langs:
            cur = self.ini_lang() or FOLLOW_LANG
            if cur != FOLLOW_LANG and cur not in langs:
                cur = FOLLOW_LANG
        self.var_lang.set(cur)

    def ini_lang(self):
        """游戏目录 locale.ini 里设的语言；读不到返回 None。"""
        d = self.var_dir.get()
        if not d or not os.path.isdir(os.path.join(d, PACK_DIR)):
            return None
        return read_ini_language(os.path.join(d, PACK_DIR, "locale.ini"))

    def chosen_lang(self):
        """下拉当前选中的语言代码；选「跟随 locale.ini」时返回 None。"""
        v = self.var_lang.get()
        return None if v == FOLLOW_LANG else v

    def lang_to_save(self):
        """真正需要落盘的语言代码；没有需要保存的返回 None。

        「不写」的理由只有两个，都得是真无变化：
          · 选的是「跟随」—— 本来就没有要保存的东西
          · 游戏目录里已经是这个语言 —— 写回去是逐字节相同的事，
            白白改文件时间戳，也让「我到底动过它没有」变得不可查
        """
        code = self.chosen_lang()
        if code is None:
            return None
        d = self.var_dir.get()
        if d and os.path.isdir(os.path.join(d, PACK_DIR)):
            if read_ini_language(os.path.join(d, PACK_DIR, "locale.ini")) == code:
                return None
        return code

    def on_pick_lang(self, _event=None):
        """下拉改动只记录选择，不落盘。

        启动按钮也用它（不落盘），落盘只有「保存语言设置」一个入口。
        改下拉不发文件：选错了、或者只是想看看别的语言，
        都不该在游戏目录里留下痕迹。
        """
        if self.lang_to_save() is None:
            self.status.set("语言未变（%s）—— 没有需要保存的东西。"
                            % self.var_lang.get())
            return
        self.status.set("已选 %s.txt —— 还没保存，点「启动游戏（已注入）」"
                        "或「保存语言设置」才写入。" % self.chosen_lang())

    def save_lang_choice(self):
        """把下拉里的选择写进 locale.ini。返回 (是否成功, 说明)。

        落盘的唯一实现，调用方是「启动游戏（已注入）」与「保存语言设置」。
        两者走同一条路径，所以不会出现两套保存行为。

        写两处：build\\PR2Packs\\ 与游戏目录那份。前者保证下次构建不会
        把选择打回模板默认值（run_build 只在文件不存在时才用模板），
        后者让下一次启动直接生效，不必先构建一次。

        **无变化时一个字都不写** —— 选了「跟随」或游戏目录已是该语言
        时直接返回，由调用方照样启动（本次语言照样生效，走 --lang）。

        写不成不算失败 —— 本次启动仍会用所选语言（走环境变量），
        只是下次启动会回退，所以只提示不弹窗打断。
        """
        code = self.lang_to_save()
        if code is None:
            return True, "语言没有变化，未写入任何文件。"

        targets = [os.path.join(PACK_OUT, "locale.ini")]
        d = self.var_dir.get()
        if d and os.path.isdir(os.path.join(d, PACK_DIR)):
            targets.append(os.path.join(d, PACK_DIR, "locale.ini"))

        failed = [p for p in targets if not write_ini_language(p, code)]
        if failed:
            return False, ("已选了 %s，但 %s 写不进去（多半是只读）—— "
                           "本次启动仍用 %s，下次启动会回到原来的语言。"
                           % (code,
                              "、".join(os.path.basename(
                                  os.path.dirname(p)) + "\\locale.ini"
                                  for p in failed),
                              code))
        return True, "语言已保存为 %s.txt。" % code

    def on_play(self):
        """启动已注入版。语言确有变化时顺手保存，没变化就一个字都不写。

        保存不是这个按钮独有的功能，而是「有变化就落盘」这条规则的
        唯一实现（save_lang_choice）：无变化时它直接返回，文件不动。
        单独的「保存语言设置」是给「不想进游戏、只想改配置」用的入口，
        走的是同一条路径，不会出现两套保存逻辑。
        """
        saved, note = self.save_lang_choice()
        lang = self.chosen_lang()
        ok, message = launch_game(self.var_dir.get(), lang)
        if not ok:
            messagebox.showerror("无法启动", message)
            return
        self.status.set("%s %s" % (note, message))
        if not saved:
            messagebox.showwarning("语言设置没有保存", note)

    def on_save_lang(self):
        """只保存语言，不启动。"""
        saved, note = self.save_lang_choice()
        self.status.set(note)
        if not saved:
            messagebox.showwarning("语言设置没有保存", note)

    def on_install(self):
        if self.busy():
            return
        langs = list(self.built_langs)
        self._begin_log("复制到游戏目录：%s" % self.var_dir.get())
        self.bar.configure(value=0.0)
        self.status.set("正在复制到 %s …" % self.var_dir.get())
        self.installing = True
        self.worker = threading.Thread(
            target=run_deploy,
            args=(self.var_dir.get(), langs, self.events), daemon=True)
        self.worker.start()
        self._sync()

    def on_remove_patch(self):
        """把补丁从游戏目录删掉 —— 整个窗口里唯一会删东西的地方。

        所以做得比别的操作都啰嗦：
          · 先列出**实际存在**的文件，不是「可能有哪些」；
          · 两次确认**都带清单**，第二次不是「确定吗」这种空话；
          · 按钮写动词（继续删除 / 确认删除），不用含糊的是/否；
          · 每个文件的结果都写进日志，失败（比如游戏正在运行）原样报出来。
        """
        if self.busy():
            return
        d = self.var_dir.get()
        if not is_game_dir(d):
            messagebox.showerror("没有游戏目录",
                                 "先选择一个含 %s 的目录。" % GAME_EXE)
            return

        items = patch_items(d)
        if not items:
            messagebox.showinfo("没有可删的", "这个目录里没有本补丁的文件。")
            return

        names = "\n".join("   " + rel for rel, _p, _isdir in items)

        # 第一次：说清删什么、不删什么、后果。
        dlg = ConfirmDialog(
            self, "从游戏目录移除补丁",
            "目录：\n%s\n\n将删除以下 %d 项：\n%s\n\n"
            "不会删除 PR2.exe、存档、其它 DLL 或其它语言包。\n"
            "删除后游戏回到原版（英文），而且不可撤销。"
            % (d, len(items), names),
            ok_text="继续删除")
        self.wait_window(dlg)
        if not dlg.result:
            return

        # 第二次：逐项复选 —— 只删勾中的。清单再摊一遍，不靠记忆。
        dlg2 = ConfirmDialog(
            self, "再次确认：勾选要删除的文件",
            "下面这些是本补丁在游戏目录里的文件。**只有勾选的会被删除**，"
            "取消勾选的会原样留在目录里。\n\n"
            "删除后无法恢复；PR2.exe、存档、其它 DLL 都不受影响。",
            ok_text="删除勾选项",
            choices=[rel for rel, _p, _isdir in items])
        self.wait_window(dlg2)
        if not dlg2.result:
            return
        chosen = dlg2.selected

        ok, removed, failed = remove_patch(d, only=chosen)

        self._begin_log("移除补丁（勾选 %d / %d 项）：%s"
                        % (len(chosen), len(items), d))
        for r in removed:
            self._log("  已删除 %s" % r)
        for f in failed:
            self._log("  失败 %s" % f)
        for rel, _p, _isdir in items:
            if rel not in chosen:
                self._log("  保留 %s（未勾选）" % rel)

        # 语言包没了，启动语言下拉必须跟着变（否则还列着已经不存在的包）
        self.refresh_langs()
        self.installed_done = False
        self.built_langs = []
        if ok:
            self.status.set("已按勾选删除 %d 项（勾了 %d 项），未勾选的保留。"
                            % (len(removed), len(chosen)))
        else:
            self.status.set("有 %d 项没删掉 —— 游戏可能正在运行。" % len(failed))
            messagebox.showwarning(
                "部分文件没删掉",
                "常见原因是游戏正在运行（文件被占用）。\n关闭游戏后可以再试一次。\n\n"
                "详见下方日志。")
        self._sync()

    def on_vanilla(self):
        ok, message = launch_vanilla(self.var_dir.get())
        if ok:
            self.status.set(message)
        else:
            messagebox.showerror("无法启动", message)

    def on_close(self):
        """关窗口 = 收工：编辑器是 start 拉起来的，也由 start 停掉。

        构建/复制线程都是 daemon，随进程一起结束；编辑器是**独立进程**，
        不主动停就会一直留在后台 —— 以前正是这样，点几次攒几个。
        """
        # 先取消下一轮轮询：窗口都销毁了还回调，Tk 会往 stderr 抛
        # 「invalid command name ...」。
        if getattr(self, "_poll_id", None):
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        if self.editor_pid or self.editor_proc is not None:
            self._kill_editor()
        self.destroy()

    # ---- 队列泵

    def _poll(self):
        self._drain()
        self._tick += 1
        # 编辑器没了（控制台被关掉 / 崩了）就把「停止」按钮和 pid 一起清掉，
        # 免得界面还显示「在运行」。每 40 个轮询（约 3 秒）探一次。
        if self.editor_pid and self._tick % 40 == 0:
            port, info = find_editor()
            if not info:
                self._forget_editor()
                self.status.set("编辑器已退出（控制台窗口被关掉了？）。")
        # 编辑器准备期间每秒刷新一次「已等 N 秒」：进度条在动、数字在走，
        # 才能把「正在下东西」和「已经卡死」区分开。
        if self.editing and self._editor_t0:
            secs = int(time.time() - self._editor_t0)
            if secs >= 1 and secs != getattr(self, "_editor_secs", -1):
                self._editor_secs = secs
                self.status.set("编辑器：%s… 已等 %d 秒"
                                % (self._editor_step or "检查依赖", secs))
        self._sync()
        self._poll_id = self.after(self.POLL_MS, self._poll)

    def _drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "line":
                    self._log(payload)

                elif kind == "lang_start":
                    self.status.set("正在构建 %s…" % payload)

                elif kind == "lang_done":
                    lang, code = payload
                    if code == 0:
                        self.done += 1
                        self.bar.configure(value=float(self.done))

                elif kind == "injector_done":
                    self.compiling = False
                    self._refresh_injector_label()
                    if self.missing_injector:
                        self.status.set("注入器编译失败，详见下方日志。")
                    else:
                        self.status.set("注入器已就绪，可以构建语言包了。")

                elif kind == "build_ok":
                    self.end_build()
                    self.built_langs = payload
                    left = missing_outputs()
                    if left:
                        self.status.set("构建结束，但缺少：%s" % "、".join(left))
                    elif is_game_dir(self.var_dir.get()):
                        self.status.set("构建完成，可以复制到游戏目录。")
                    else:
                        self.status.set("构建完成，请选择游戏目录。")

                elif kind == "build_failed":
                    self.end_build()
                    self.status.set("构建失败，没有复制任何文件。")
                    messagebox.showerror(
                        "构建失败", "详见下方日志。\n没有向游戏目录复制任何文件。")

                elif kind == "deploy_step":
                    i, n, label = payload
                    self.bar.configure(maximum=float(n), value=float(i - 1))
                    self.status.set("正在复制（%d/%d）：%s" % (i, n, label))

                elif kind == "deploy_ok":
                    self.installing = False
                    self.installed_done = True
                    self.bar.configure(value=float(self.bar["maximum"]))
                    # 刚复制进去的语言包现在可以选了。
                    self.refresh_langs()
                    self.status.set("复制完成，可以点「启动游戏（已注入）」。")
                    self._sync()
                    messagebox.showinfo(
                        "复制完成",
                        "已复制到：\n%s\n\n现在可以点「启动游戏（已注入）」，"
                        "或点「运行游戏（原版）」对比。" % payload)

                elif kind == "editor_step":
                    i, n, label = payload
                    self._editor_step = "%s（第 %d/%d 步）" % (label, i, n)
                    self.status.set("编辑器：" + self._editor_step + "…")

                elif kind == "editor_line":
                    self._log("  " + str(payload))

                elif kind == "editor_ready":
                    self.editing = False
                    info = payload
                    ok, message = info["ok"], info["message"]
                    self.editor_pid = info.get("pid")
                    self.editor_port = info.get("port")
                    self.editor_proc = info.get("proc")
                    # 退出不确定模式，交还给构建/复制用的确定模式进度条。
                    self.bar.stop()
                    self.bar.configure(mode="determinate", maximum=1.0, value=0.0)
                    # 失败说明可能有好几行，状态栏只放第一行，全文进日志
                    self.status.set(message.splitlines()[0] if message else "")
                    self._sync()
                    if not ok:
                        self._log(message)
                        messagebox.showerror("编辑器准备失败", message)

                elif kind == "deploy_failed":
                    self.installing = False
                    self.status.set("复制失败，详见下方日志。")
                    messagebox.showerror(
                        "复制失败", "详见下方日志。\n游戏目录可能未发生变化。")
        except queue.Empty:
            pass


def main():
    # 产物缺失不再拦在窗口外面：注入器可以在窗口里现编，
    # 缺什么窗口自己会说。拦在这里等于不给用户补的机会。
    do_build = "--build" in sys.argv[1:]

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = App(do_build=do_build)
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
