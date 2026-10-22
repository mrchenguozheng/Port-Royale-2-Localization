# -*- coding: utf-8 -*-
"""pr2ctl.launch —— 启动游戏、原版对比、拉起/关闭编辑器。"""

from .base import *  # noqa: F401,F403
from .build import child_env

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

