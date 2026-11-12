#!/usr/bin/env python3
# coding: utf-8
r"""src/editor/server.py — 本地 Web 编辑器的后端（纯标准库）

浏览器负责显示与编辑，**校验规则全在这里** —— 因为规则本来就在
translate.py / compile_pack.py 里，那是唯一的一份。抄到 JS 里就多一份
实现，两边不一致时没人知道该信哪个。

同时托管前端产物 dist\（astro build 的输出）。所以只起一个服务就够，
不需要再单独跑 astro dev，也不需要任何第三方包：

    只用 http.server / json / urllib，和仓库里其它脚本一样是标准库。
    以前这里是 FastAPI + uvicorn 的，但那样每次「打开译文编辑器」都要
    先建 venv、再联网装依赖 —— 网络不通就永远打不开，而它只是 8 个
    本地 JSON 接口，用不上框架。

启动：
    python src/editor/server.py              # 起服务并开浏览器
    python src/editor/server.py --no-open    # 只起服务
    python src/editor/server.py --port 9000

只监听 127.0.0.1：这些接口能改仓库里的译文文件，不该暴露到网络上。
"""

import argparse
import difflib
import json
import mimetypes
import os
import re
import sys
import threading
import time
import tomllib
import subprocess
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                                  # 仓库的 src\
TOOLS = os.path.join(SRC, "tools")
ROOT = os.path.dirname(SRC)                                  # 仓库根

# pythonw 拉起时 stdout/stderr 是 None；warnings/print 往它们写会抛
# AttributeError: 'NoneType' object has no attribute 'write'。
# 换成 devnull，保证没有控制台窗口时服务也正常。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")

DIST = os.path.join(HERE, "dist")                            # astro build 的产物
DATA_ROOT = SRC                                              # 译文/原文的根，可被 --data 覆盖
DEFAULT_PORT = 8777

# translate / compile_pack 是脚本不是包，直接把 tools\ 加进 sys.path 来 import。
# 这也让规则只有一份：编辑器与语言包走同一批函数。
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from install import pr2ctl as P  # noqa: E402
import translate as T  # noqa: E402
from api import store as ST  # noqa: E402
from api.request import Req  # noqa: E402
from api import translate as TR, langs as LG, install as IN  # noqa: E402


#: 真实端口，由 main() 在启动前填上。工具窗口靠 /api/health 判断
#: 「这个端口上跑的是不是编辑器、是哪一个」。
CURRENT_PORT = 0

#: 工具窗口起的实例会带一个随机令牌；/api/health 原样回传，
#: 用来把「我刚拉起的这个」和「旁边已经在跑的另一个」区分开。
CURRENT_TOKEN = os.environ.get("PR2_EDITOR_TOKEN", "")

#: serve_forever() 的那个实例。关服务时用它。
SERVER = None

#: 启动时刻与前端产物的时间，用来在页面上判断「后端是不是旧的」。
STARTED = time.time()

#: 译者分发包：只开放翻译页，构建/部署/启动接口全部拒绝。
TRANSLATOR = False
TRANSLATOR_LANG = "zh"


# ---------------------------------------------------------------- 校验

# ---------------------------------------------------------------- 安装页

START_JOB = {"running": False, "lines": [], "done": False, "ok": False,
             "kind": "", "error": ""}
START_LOCK = threading.Lock()


def health_info():
    dist = DIST
    try:
        dist_mtime = max(os.path.getmtime(os.path.join(dp, f))
                         for dp, _dn, fn in os.walk(dist) for f in fn)
    except (OSError, ValueError):
        dist_mtime = 0
    return {
        "app": "pr2-editor",
        "pid": os.getpid(),
        "port": CURRENT_PORT,
        "token": CURRENT_TOKEN,
        "started": STARTED,
        "uptime": int(time.time() - STARTED),
        "python": sys.version.split()[0],
        "root": os.path.dirname(SRC),
        "dist_mtime": int(dist_mtime),
    }


def server_instances():
    """并发扫一遍编辑器常用端口，列出还在跑的实例（含自己）。"""
    from concurrent.futures import ThreadPoolExecutor

    def probe(port):
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/api/health" % port, timeout=0.15) as resp:
                info = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
        if not isinstance(info, dict) or info.get("app") != "pr2-editor":
            return None
        info["current"] = port == CURRENT_PORT
        return info

    with ThreadPoolExecutor(max_workers=24) as ex:
        found = list(ex.map(probe, range(8777, 8777 + 24)))
    return {"current": CURRENT_PORT, "instances": [x for x in found if x]}


# ---------------------------------------------------------------- 数据

# 读缓存、整表写回、补丁写回都在 api\store.py；这里只剩「换根」。
# 换根之后必须清掉 store 的缓存，否则拿到的还是旧文件的内容。


# ---------------------------------------------------------------- 元信息

def get_health(req):
    query = req.query
    body = req.body
    return req.send_json(health_info())



def get_server_instances(req):
    query = req.query
    body = req.body
    return req.send_json(server_instances())



def post_server_stop(req):
    query = req.query
    body = req.body
    try:
        port = int(body.get("port") or 0)
    except (TypeError, ValueError):
        return req.send_json({"ok": False, "error": "端口不对"})
    if port in (0, CURRENT_PORT):
        return req.send_json({"ok": False, "error": "不能停当前服务"})
    ok = P.editor_shutdown(port)
    return req.send_json({"ok": ok, "port": port})



def post_shutdown(req):
    query = req.query
    body = req.body
    req.send_json({"ok": True})
    # 稍等一点，先让这条响应写回客户端，再收摊。
    threading.Timer(0.2, stop_server).start()
    return None




def set_data_root(path, presets_dir=None):
    r"""把数据根（默认仓库 src\）指到别处，主要用于测试隔离。

    这里没有第二份路径表：`translate` 的 SRC\ 是唯一的根，译文、原文都
    由它派生；`glossary\` 两文件按「根的同级」算；字体 presets 目录可以
    单独指定（它不在 src\ 的同一层）。换根之后所有按 mtime 的缓存都要清，
    否则拿到的还是旧文件的内容。
    """
    global DATA_ROOT
    DATA_ROOT = os.path.abspath(path)
    T.set_src(DATA_ROOT)
    ST._ALL_CACHE.update(key=None, rows=None)
    LG.set_root(DATA_ROOT)
    if presets_dir:
        IN.set_presets_dir(presets_dir)


# ---------------------------------------------------------------- HTTP

ROUTER = {}
for _m in (TR, LG, IN):
    ROUTER.update(_m.ROUTES)
ROUTER.update({
    ("GET", "/api/health"): get_health,
    ("GET", "/api/server/instances"): get_server_instances,
    ("POST", "/api/server/stop"): post_server_stop,
    ("POST", "/api/shutdown"): post_shutdown,
})


class Handler(BaseHTTPRequestHandler):
    server_version = "PR2Editor/2"
    #: keep-alive：前端一屏要连发好几个请求，省掉反复握手。
    protocol_version = "HTTP/1.1"

    # 访问日志一屏几十行，全打进控制台反而看不见真正的报错。
    def log_message(self, fmt, *args):
        pass

    # ---- 输出

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"detail": str(message)}, status)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("请求体不是合法 JSON")
        if not isinstance(body, dict):
            raise ValueError("请求体必须是对象")
        return body

    def send_file(self, path):
        if not os.path.isfile(path):
            body = "404 not found: %s" % path
            data = body.encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "application/json"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            data = f.read()
        if TRANSLATOR and os.path.basename(path) == "index.html":
            script = (
                b"<script>window.__PR2_TRANSLATOR__=true;"
                b"document.addEventListener('DOMContentLoaded',function(){"
                b"var t=document.querySelector('.tab[data-view=\"start\"]');"
                b"if(t)t.style.display='none';"
                b"var e=document.querySelector('.tab[data-view=\"editor\"]');"
                b"if(e)e.click();});</script>"
            )
            data = data.replace(b"</head>", script + b"</head>", 1) \
                       if b"</head>" in data else data + script
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # 前端产物带内容哈希，静态文件可以放心缓存；index.html 不行。
        if os.path.basename(path) != "index.html":
            self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    # ---- 路由

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        try:
            if TRANSLATOR and path.startswith("/api/start/"):
                return self.send_error_json(403, "translator mode: build/deploy disabled")
            if path.startswith("/api/"):
                _say("GET  %s" % path)
                return self.get_api(path, urllib.parse.parse_qs(parsed.query))
            return self.get_static(path)
        except Exception as exc:            # 兜底：别让一个异常把连接挂死
            _say("ERROR GET %s: %s\n%s" % (path, exc, traceback.format_exc()))
            return self.send_error_json(500, exc)

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        try:
            if TRANSLATOR and path.startswith("/api/start/"):
                return self.send_error_json(403, "translator mode: build/deploy disabled")
            if not path.startswith("/api/"):
                return self.send_error_json(404, "not found")
            return self.post_api(path)
        except ValueError as exc:
            return self.send_error_json(400, exc)
        except Exception as exc:
            _say("ERROR %s %s: %s\n%s" % (self.command, path, exc, traceback.format_exc()))
            return self.send_error_json(500, exc)

    # ---- GET

    def redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def get_static(self, path):
        if TRANSLATOR:
            if path in ("/", "/start", "/install"):
                return self.redirect("/translate/%s" % TRANSLATOR_LANG)
            if path == "/translate":
                return self.redirect("/translate/%s" % TRANSLATOR_LANG)
        if path in ("/start",):
            return self.redirect("/install")
        if path == "/":
            return self.redirect("/translate/zh")
        if path == "/translate":
            return self.redirect("/translate/zh")
        if re.match(r"^/translate/(?:0x)?[0-9a-f]{8}$", path, re.I) or \
                re.match(r"^/translate/\d+$", path):
            return self.redirect("/translate/zh/" + path.rsplit("/", 1)[1])
        if path == "/install" or path.startswith("/translate/"):
            path = "/index.html"
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(DIST, rel))
        # 目录穿越：拼出来的路径必须还在 dist\ 里
        if os.path.commonpath([full, DIST]) != DIST:
            return self.send_error_json(404, "not found")
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        return self.send_file(full)

    def get_api(self, path, query):
        fn = ROUTER.get(("GET", path))
        if fn is None:
            return self.send_error_json(404, "unknown api: %s" % path)
        return fn(Req(self, query=query))

    def post_api(self, path):
        body = self.read_json()
        fn = ROUTER.get(("POST", path))
        if fn is None:
            return self.send_error_json(404, "unknown api: %s" % path)
        return fn(Req(self, body=body))



def stop_server():
    global SERVER
    if SERVER is not None:
        SERVER.shutdown()


# ---------------------------------------------------------------- 启动

def editor_on(host, port):
    """这个端口上是不是我们自己的编辑器？问一句 /api/health。

    只测「端口通不通」不够：旁边完全可能有别的服务在监听，
    把它当成「编辑器已在运行」会让浏览器打开一个不相干的页面。
    """
    try:
        with urllib.request.urlopen(
                "http://%s:%d/api/health" % (host, port), timeout=1.0) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    return isinstance(info, dict) and info.get("app") == "pr2-editor"


def port_in_use(host, port):
    """端口有没有人在占着。

    Windows 上 SO_REUSEADDR 的语义和 Unix **相反**：它允许两个 socket 绑
    同一个端口，于是「bind 成功」根本不能证明端口空着 —— 旧实现据此判
    「空闲」，uvicorn 随后绑定失败，进程静默退出（pythonw 下连报错都看不到）。
    SO_EXCLUSIVEADDRUSE 才是 Windows 上「我独占这个端口」的开关：
    绑不上，就是有人占着。
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return True
    return False


def _say(text):
    """打印一行提示，但在没有 stdout 的环境下（pythonw）安静跳过。

    这个服务可能被 pythonw 拉起 —— 不弹黑框。pythonw 里 sys.stdout 是
    None，任何 print 都会 AttributeError。所以每句提示都要先问一句。
    """
    if sys.stdout is not None:
        print(text, flush=True)


def main():
    ap = argparse.ArgumentParser(description="PR2 本地化编辑器（本地 Web）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help="端口，默认 %d" % DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1",
                    help="只监听本机。有接口能写文件，不要改成 0.0.0.0。")
    ap.add_argument("--no-open", action="store_true", help="不自动开浏览器")
    ap.add_argument("--open-page", default="/",
                    help="自动打开的页面，默认 /（安装页用 /start）")
    ap.add_argument("--restart", action="store_true",
                    help="若已有编辑器在跑，先停掉它再用新代码启动")
    ap.add_argument("--translator", action="store_true",
                    help="译者模式：只开放翻译页，禁用构建/部署/启动")
    ap.add_argument("--translator-lang", default="zh",
                    help="译者模式下默认打开的语言代码")
    ap.add_argument("--web-dir", default=None,
                    help="前端目录；默认使用 src/editor/dist")
    ap.add_argument("--data", default=None,
                    help="译文/原文的根目录（默认 src\\）；测试用临时副本")
    ap.add_argument("--presets-dir", default=None,
                    help="字体 presets 目录；默认 src\\data\\fontstitch\\presets")
    a = ap.parse_args()

    global TRANSLATOR, TRANSLATOR_LANG, DIST
    TRANSLATOR = a.translator
    TRANSLATOR_LANG = (a.translator_lang or "zh").strip() or "zh"
    if a.web_dir:
        DIST = os.path.abspath(a.web_dir)
    if a.data:
        set_data_root(a.data, a.presets_dir)
    elif a.presets_dir:
        set_data_root(DATA_ROOT, a.presets_dir)

    if not os.path.isdir(DIST):
        _say("注意：找不到前端产物 %s" % DIST)
        _say("      先构建：cd src\\editor && npm install && npm run build")

    port = a.port
    restarted = False
    if port_in_use(a.host, port):
        if editor_on(a.host, port):
            if a.restart:
                _say("检测到旧编辑器在运行，正在重启以加载最新代码…")
                try:
                    with urllib.request.urlopen(
                            "http://%s:%d/api/health" % (a.host, port), timeout=2) as r:
                        old = json.load(r).get("pid")
                    if old:
                        import subprocess
                        subprocess.run(["taskkill", "/PID", str(old), "/F"],
                                       capture_output=True)
                        import time as _t
                        for _ in range(30):
                            if not port_in_use(a.host, port):
                                break
                            _t.sleep(0.2)
                except Exception as exc:
                    _say("重启失败：%s" % exc)
                restarted = True
            else:
                _say("编辑器已在运行：http://%s:%d/" % (a.host, port))
                if not a.no_open:
                    webbrowser.open("http://%s:%d%s" % (a.host, port, a.open_page))
                return 0

        if not restarted:
            # 被别的程序占着 —— 往上找一个空位。
            for p in range(a.port + 1, a.port + 20):
                if not port_in_use(a.host, p):
                    _say("端口 %d 被占，改用 %d。" % (a.port, p))
                    port = p
                    break
            else:
                _say("从 %d 往上 20 个端口都被占了。" % a.port)
                return 1

    global SERVER, CURRENT_PORT
    CURRENT_PORT = port
    try:
        httpd = ThreadingHTTPServer((a.host, port), Handler)
    except OSError:
        # 刚重启时端口可能还在 TIME_WAIT：换个口也要能起来。
        httpd = None
        for p in range(a.port + 1, a.port + 30):
            try:
                httpd = ThreadingHTTPServer((a.host, p), Handler)
                port = p
                CURRENT_PORT = p
                break
            except OSError:
                continue
        if httpd is None:
            _say("端口都被占用，编辑器没能启动。")
            return 1
    httpd.daemon_threads = True
    SERVER = httpd

    _say("PR2 本地化编辑器：http://%s:%d/" % (a.host, port))
    _say("（只监听本机。按 Ctrl+C 停止。）")
    if not a.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(
            "http://%s:%d%s" % (a.host, port, a.open_page))).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())