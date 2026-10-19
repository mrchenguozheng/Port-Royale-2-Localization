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
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

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
#: 编辑器有自己的 venv（FastAPI 不是标准库，装在 src\editor\.venv 里）。
#: 所以这里**不直接跑 python.exe** —— 直接跑会挑到系统 Python，而系统
#: Python 不一定装了 FastAPI（这台机器上 3.14 就没有），表现是
#: 「点了没反应」：pythonw 吞掉 traceback，谁也看不到 ModuleNotFoundError。
EDITOR_BAT = os.path.join(EDITOR_DIR, "StartEditor.bat")
#: venv 放在**仓库根**，不放 src\editor\ 下 —— 它是仓库的依赖环境，
#: 将来别的东西要加包也用同一个。目前只有编辑器用得上 fastapi/uvicorn。
VENV = os.path.join(ROOT, ".venv")
VENV_SCRIPTS = os.path.join(VENV, "Scripts")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
EDITOR_DIST = os.path.join(EDITOR_DIR, "dist")
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
        subprocess.Popen(cmd, cwd=target, close_fds=True)
    except OSError as exc:
        return False, "启动 %s 失败：%s\n\n%s" % (LAUNCHER, exc,
                                                _oserr_hint(exc))
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


def venv_ensure():
    """确保编辑器的 venv 存在且装好依赖。返回 (是否成功, 说明)。

    为什么要有 venv：编辑器要 FastAPI + uvicorn，**这两个不是标准库**。
    这台机器上有两个 Python —— 3.14（没有 FastAPI）和 3.11（有）——
    哪个被挑中取决于 PATH 顺序。挑错的后果是启动三秒后
    ModuleNotFoundError，而它跑在 pythonw 下（无控制台），
    traceback 被丢弃，用户只看到「点了没反应」。

    venv 把这件事一次解决：不管哪个 Python 建了它，venv 自带
    site-packages，依赖钉死在里面，而且不往系统 Python 里装任何东西。

    venv 在**仓库根**（.venv\），不是 src\editor\ 下：它是仓库的依赖
    环境，不是编辑器专属的。以后别的东西要加包，装同一个。

    全程用列表参数调子进程，不经过 cmd —— 仓库路径里有空格，
    经 cmd 就会被引号吃掉。
    """
    exe = os.path.join(VENV_SCRIPTS, "python.exe")
    if os.path.isfile(exe):
        # 已有 venv：只在缺依赖时补装，避免每次启动都联网
        probe = subprocess.run(
            [exe, "-c", "import fastapi, uvicorn"],
            capture_output=True, close_fds=True)
        if probe.returncode == 0:
            return True, "venv 就绪"
        steps = [[exe, "-m", "pip", "install", "--quiet",
                  "-r", REQUIREMENTS]]
        what = "补装依赖"
    else:
        steps = [[sys.executable, "-m", "venv", VENV],
                 [os.path.join(VENV_SCRIPTS, "python.exe"),
                  "-m", "pip", "install", "--quiet",
                  "-r", REQUIREMENTS]]
        what = "创建 venv 并装依赖"

    for cmd in steps:
        try:
            r = subprocess.run(cmd, capture_output=True, close_fds=True)
        except OSError as exc:
            return False, "%s 失败：%s" % (what, exc)
        if r.returncode != 0:
            # pip 的错误在 stderr；按 bytes 读再猜编码（同 read_lines 的道理）
            raw = (r.stderr or b"")[:400]
            for enc in ("utf-8", "mbcs"):
                try:
                    msg = raw.decode(enc).strip().splitlines()[-1]
                    break
                except Exception:
                    msg = raw.decode("utf-8", "replace").strip()
            return False, "%s 失败：%s" % (what, msg or "退出码 %d" % r.returncode)
    return True, "venv %s完成" % what


def open_editor():
    """启动本地 Web 编辑器，返回 (是否成功, 说明)。

    编辑器是一个长驻的 HTTP 服务（src\\editor\\server.py），不是一次性
    任务 —— 所以**不等待它退出**，只把它拉起来就跑。窗口照常可以继续
    构建、复制。

    走 StartEditor.bat 而不是直接跑 python：那个脚本负责首次运行时
    建 venv 并装 FastAPI，然后用 venv 里的 pythonw 启动。
    """
    if not os.path.isfile(EDITOR_BAT):
        return False, "找不到 %s。" % EDITOR_BAT
    if not os.path.isdir(EDITOR_DIST):
        return False, ("前端还没构建（缺少 %s）。\n\n"
                       "先在仓库里跑一次：\n"
                       "  cd src\\editor\n"
                       "  npm install\n"
                       "  npm run build" % EDITOR_DIST)

    # 直接跑 venv 里的 pythonw，**不碰 .bat、不套 cmd /c**。
    #
    # `cmd /c "C:\...\Port Royale 2 Localization\...\StartEditor.bat"` 在
    # 路径含空格时必然失败：cmd 把整行当一条命令解析，第一个引号被吃掉，
    # 路径被截断，报「此时不在…」。仓库目录名里就有空格，所以这是必踩的坑。
    #
    # venv 的建法也搬进 Python（venv_ensure）：同样是空格问题，
    # `python -m venv <含空格路径>` 用列表参数传是对的，但外层一旦
    # 经过 cmd 就会碎。在 Python 里全程用列表，不经 cmd。
    try:
        exe = os.path.join(VENV_SCRIPTS, "pythonw.exe")
        if not os.path.isfile(exe):
            exe = os.path.join(VENV_SCRIPTS, "python.exe")
        subprocess.Popen([exe, os.path.join(EDITOR_DIR, "server.py")],
                         cwd=EDITOR_DIR, env=child_env(), close_fds=True)
    except OSError as exc:
        return False, "启动编辑器失败：%s" % exc
    return True, "编辑器已启动，稍候会在浏览器中打开。"


# ------------------------------------------------------------ 构建

def child_env():
    r"""子进程环境：强制 stdout / stderr 用 UTF-8。

    Windows 上 Python 给文本流套的是**控制台代码页**（简体中文机器是
    cp936），而这里把管道按 utf-8 解 —— 两边不一致，中文输出就成了
    一串「已生成」模样的乱码。PYTHONIOENCODING 管的就是文本流本身，
    比事后猜编码可靠（猜错了会把正常文本也毁掉）。

    只改这一个变量，其余环境原样继承。
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
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
    cmd = [sys.executable, script, "--lang", lang, "--out", out_dir]
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
        events.put(("build_ok", list(langs)))
    except Exception as exc:                      # 兜底，别让线程静默死掉
        events.put(("line", "构建出错：%s" % exc))
        events.put(("build_failed", ""))


# ------------------------------------------------------------ 界面

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
        self.installed_done = True
        self.build_cool = 0
        self.missing_injector = missing_outputs(need_pack=False)

        self.var_dir = tk.StringVar()
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
        self._sync()
        self._center()
        self.after(self.POLL_MS, self._poll)

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
        """游戏目录 + 部署。两者挨着，因为部署只对目录生效。"""
        ttk.Label(box, text="游戏目录").grid(row=0, column=0, sticky="w")
        dir_row = ttk.Frame(box)
        dir_row.grid(row=0, column=1, sticky="we", padx=(10, 0))
        dir_row.columnconfigure(0, weight=1)
        tk.Entry(dir_row, textvariable=self.var_dir, width=44,
                 state="readonly").grid(row=0, column=0, sticky="we")
        ttk.Button(dir_row, text="浏览…", width=8,
                   command=self.on_browse).grid(row=0, column=1, padx=(6, 0))
        self.btn_install = ttk.Button(
            box, text="复制到游戏目录", width=16, command=self.on_install)
        self.btn_install.grid(row=0, column=2, padx=(10, 0))

        ttk.Label(box, text="须含 %s。只复制构建产物，内容相同就跳过。"
                  % GAME_EXE).grid(row=1, column=0, columnspan=3,
                                   sticky="w", pady=(6, 0))

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

        编辑器是常驻服务，所以这里只负责把它拉起来 —— 关掉这个窗口
        不会停它，要停得关浏览器或者在任务管理器里结束 pythonw。
        """
        self.btn_editor = ttk.Button(
            box, text="打开译文编辑器", command=self.on_editor)
        self.btn_editor.grid(row=0, column=0, sticky="w")
        ttk.Label(box, text="改 src\\translations\\ 下的译文。"
                  "首次会创建 venv 并装依赖。").grid(
            row=0, column=1, sticky="w", padx=(10, 0))

    def on_editor(self):
        if self.busy():
            return
        self.status.set("准备编辑器…（首次运行要装依赖，约一分钟）")
        self.editing = True
        self._set_state(self.btn_editor, "disabled")
        self.worker = threading.Thread(target=self._editor_worker, daemon=True)
        self.worker.start()

    def _editor_worker(self):
        """venv + 启动。放线程里是因为建 venv 要几十秒，
        放主线程会把窗口冻住 —— 用户会以为程序卡死了。"""
        ok, message = venv_ensure()
        self.events.put(("editor_ready", (ok, message)))
        if ok:
            started, msg = open_editor()
            self.events.put(("line", msg if started else "启动失败：" + msg))
        else:
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
        self._sync()

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

    def on_vanilla(self):
        ok, message = launch_vanilla(self.var_dir.get())
        if ok:
            self.status.set(message)
        else:
            messagebox.showerror("无法启动", message)

    def on_close(self):
        # 构建与复制线程都是 daemon，窗口关掉时它们随进程一起结束。
        self.destroy()

    # ---- 队列泵

    def _poll(self):
        self._drain()
        self._sync()
        self.after(self.POLL_MS, self._poll)

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

                elif kind == "editor_ready":
                    self.editing = False
                    ok, message = payload
                    self.status.set(message)
                    self._sync()
                    if not ok:
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
