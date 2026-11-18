# -*- coding: utf-8 -*-
"""pr2ctl.launch —— 启动游戏与原版对比。"""

from .base import *  # noqa: F401,F403
from .build import child_env

def launch_game(target, lang=None):
    """用注入器启动器把游戏拉起来（带语言包）。返回 (是否成功, 说明)。

    启动器自己会 CreateProcess 一个挂起的 PR2.exe、注入 DLL 再恢复，
    所以它很快就会退出 —— 不用等它结束。控制台留给它自己开，
    那里会打印注入结果，窗口不该抢。

    工作目录必须设成游戏目录：启动器会给 CreateProcess 传游戏根目录，
    而 PR2.exe 按相对路径找资源文件。

    lang 非空时给启动器传 --lang=xx，它写进子进程的 PR2_PACK_LANG，
    DLL 优先用它而不是 locale.ini —— 只影响这一次启动，不写任何文件。
    """
    if not lang:
        try:
            from .settings import game_language
            lang = game_language(target) or None
        except Exception:
            lang = None
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
    """启动原版 PR2.exe，并先恢复 PR2Localization\\fonts\\_original\\ 里的原版字体。

    直接用 PR2.exe 启动也可以，但那样会继续用上一次替换过的字体；
    走 PR2Localization.exe --vanilla 才能先把原版字体恢复回来。
    没有启动器时退回直接启动。
    """
    if not is_game_dir(target):
        return False, "该目录下没有 %s，请重新选择游戏目录。" % GAME_EXE
    launcher = os.path.join(target, LAUNCHER)
    try:
        if os.path.isfile(launcher):
            subprocess.Popen([launcher, "--vanilla"], cwd=target, close_fds=True)
            return True, "已恢复原版字体，启动原版 %s（未注入）。" % GAME_EXE
        subprocess.Popen([os.path.join(target, GAME_EXE)], cwd=target,
                         close_fds=True)
    except OSError as exc:
        return False, "启动 %s 失败：%s\n\n%s" % (GAME_EXE, exc,
                                                _oserr_hint(exc))
    return True, "已直接启动 %s（未注入任何组件）。" % GAME_EXE


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


def game_processes():
    """列出正在运行的 PR2.exe / PR2Localization.exe。"""
    import csv as _csv
    import io as _io
    import subprocess as _sp
    try:
        out = _sp.run(["tasklist", "/FO", "CSV", "/NH"],
                      capture_output=True).stdout
    except OSError:
        return []
    text = out.decode("mbcs", "replace")
    procs = []
    for row in _csv.reader(_io.StringIO(text)):
        if len(row) < 2:
            continue
        name, pid = row[0].strip(), row[1].strip()
        if name.lower() in (GAME_EXE.lower(), LAUNCHER.lower()):
            procs.append({"name": name, "pid": pid})
    return procs


def kill_game():
    """强制结束 PR2.exe / PR2Localization.exe，返回 (ok, message)。"""
    import subprocess as _sp
    procs = game_processes()
    if not procs:
        return False, "没有运行中的游戏进程"
    killed = []
    for it in procs:
        r = _sp.run(["taskkill", "/PID", it["pid"], "/F"],
                    capture_output=True)
        if r.returncode == 0:
            killed.append(it)
    if not killed:
        return False, "结束进程失败（可能需要管理员权限）"
    return True, "已结束 " + "、".join("%s(pid %s)" % (x["name"], x["pid"]) for x in killed)
