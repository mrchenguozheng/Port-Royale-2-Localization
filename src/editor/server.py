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
import json
import mimetypes
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                                  # 仓库的 src\
TOOLS = os.path.join(SRC, "tools")
DIST = os.path.join(HERE, "dist")                            # astro build 的产物
DEFAULT_PORT = 8777

# translate / compile_pack 是脚本不是包，直接把 tools\ 加进 sys.path 来 import。
# 这也让规则只有一份：编辑器与语言包走同一批函数。
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import translate as T          # noqa: E402
import compile_pack as C       # noqa: E402
import terms_check             # noqa: E402


#: 真实端口，由 main() 在启动前填上。工具窗口靠 /api/health 判断
#: 「这个端口上跑的是不是编辑器、是哪一个」。
CURRENT_PORT = 0

#: 工具窗口起的实例会带一个随机令牌；/api/health 原样回传，
#: 用来把「我刚拉起的这个」和「旁边已经在跑的另一个」区分开。
CURRENT_TOKEN = os.environ.get("PR2_EDITOR_TOKEN", "")

#: serve_forever() 的那个实例。关服务时用它。
SERVER = None


# ---------------------------------------------------------------- 校验

def check_one(entry, lang, text):
    """校验一条译文，返回 [{level, text}]。

    三条规则与 translate.cmd_check 一致：
      1. 仍是占位文本 = 没翻
      2. 占位符集合要与原文相同（少=警告，多=错误）
      3. 标签轮廓要与原文相同，且译文不得新增标签

    level 分 error / warn：error 大概率出乱码，warn 需要人工确认。
    """
    out = []
    if not text:
        out.append({"level": "warn", "text": "这一条是空的（游戏里显示英文）"})
        return out

    if C.is_placeholder(text):
        out.append({"level": "warn", "text": "还没翻（仍是占位文本）"})
        return out

    en = entry.get(T.BASE_LANG, "") or ""

    # 占位符：复用 compile_pack 的实现 —— 那里处理了 %2%1 紧邻的情况
    errors, warnings = [], []
    C.check_placeholders(entry.get("id", ""), en, text, errors, warnings)
    for e in errors:
        out.append({"level": "error", "text": _strip_id(e, entry.get("id", ""))})
    for w in warnings:
        out.append({"level": "warn", "text": _strip_id(w, entry.get("id", ""))})

    # 标签轮廓：只比数量与名字（译文可以换颜色）。
    # 译文**不得新增**排版标签 —— 除了换行：项目里写 " | "，引擎认 <n>，
    # 两者等价，所以先把 <n> 折成 | 再比。顺带绕开 tag_profile 在
    # 连续标签（<n><n>）上的一个分词毛病：它会拼出 "n><n" 这种假标签。
    en_p, zh_p = T.tag_profile(_canon_breaks(en)), T.tag_profile(_canon_breaks(text))
    if en_p != zh_p:
        added = sorted({t for t in zh_p if zh_p.count(t) > en_p.count(t)})
        if added:
            out.append({"level": "error",
                        "text": "译文擅自新增标签 %s —— 换行只能用 <n> 或 |"
                                % " ".join(added)})
        else:
            out.append({"level": "warn",
                        "text": "标签数量比原文少（原文 %s，译文 %s）"
                                % (" ".join(en_p), " ".join(zh_p))})
    return out


def _strip_id(msg, hid):
    """去掉 compile_pack 消息开头重复的 id，界面自己会显示 id 列。"""
    return msg[len(hid):].strip() if msg.startswith(hid) else msg


def _canon_breaks(s):
    """把引擎的 <n> 折回项目里的 |，用于标签比对。

    两种写法在游戏里是同一个东西（换行）；不折平的话，「原文写 |、译文写
    <n>」会被判成"擅自加标签"，而这种写法正是编译期会生成的。
    """
    return re.sub(r"<n>", "|", s or "")


# ---------------------------------------------------------------- 数据

def load_all():
    """读全部语言，按 id 合并成前端要的形态。

    走 translate.load_toml —— 它已经在做合并，且强制条目数与顺序与
    基准表（en.gog_1.1.2.3）一致。这条是硬要求：多一条会让后面全部错位。
    """
    doc = T.load_toml()
    langs = T.all_langs()
    # 参考语言缺的 id（版本差异）：给前端一个显式标记，
    # 否则「空字符串」和「这一版根本没这条」看起来一模一样。
    lack = {k: set(v) for k, v in (doc.get("missing") or {}).items()}
    rows = []
    for e in T.entries(doc):
        r = {"id": e.get("id", ""), "ctx": e.get("ctx", "") or ""}
        for k in langs:
            r[k] = e.get(k, "") or ""
        gone = [k for k, ids in lack.items() if e.get("id", "") in ids]
        if gone:
            r["missing"] = gone
        rows.append(r)
    return rows


def toml_escape(s):
    r"""把一条译文安全地放进 TOML 的双引号字符串里。

    【必须做】译文里有三种字符会破坏文件结构：
      * 双引号 "   —— 不转义就把字符串提前关掉
      * 反斜杠 \  —— 后面跟字符会被当转义序列
      * 控制符（换行、Tab…）—— 换行最致命，它会把一条劈成两行，
        而 load_toml 立刻报 TOMLDecodeError
    实测 0x11f0398f 就是这种：``"``°§$%&()=?\^';,:<|>@/*~[]"²³€``。
    转义顺序也有讲究：反斜杠必须**先**转，否则会把后面刚加的引号再转一遍。
    """
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\u%04X" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def rows_of(body):
    """从请求体里取 rows，并保持 (id, text) 的形状。

    以前这层是 pydantic 做的；现在只有这一处要校验，手写更直接 ——
    也顺手把「id 不是字符串」「text 是 null」这类脏数据挡在外面。
    """
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValueError("rows 必须是数组")
    out = []
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str):
            raise ValueError("rows 里的每一项都要有字符串 id")
        text = r.get("text", "")
        out.append({"id": r["id"], "text": "" if text is None else str(text)})
    return out


def _keep_header(path, lines):
    """保留目标文件开头的注释块（生成物头部说明）。"""
    head = []
    try:
        for ln in open(path, encoding="utf-8"):
            if ln.startswith("#"):
                head.append(ln.rstrip("\n"))
            else:
                break
    except OSError:
        pass
    return head + lines


def save_all(lang, rows):
    r"""把译文写回 translations\<lang>.toml（整表写，要求顺序完整）。

    写之前核对 id 与基准：条目数或顺序不对时宁可拒绝写，也不能写出一个
    会让后面全部错位的文件。
    """
    if lang in T.REFERENCE_LANGS:
        raise ValueError("%s 是只读参考原文，不能写入" % lang)

    path = T.lang_path(lang)
    order = [e.get("id", "") for e in T.entries(T.load_toml())]

    given = [r["id"] for r in rows]
    if len(given) != len(order):
        raise ValueError("条目数不对：收到 %d 条，基准 %s.toml 有 %d 条"
                         % (len(given), T.BASE_LANG, len(order)))
    for i, (a, b) in enumerate(zip(given, order)):
        if a != b:
            raise ValueError("第 %d 条 id 不符：收到 %s，应为 %s" % (i, a, b))

    lines = ['"%s" = "%s"' % (r["id"], toml_escape(r["text"])) for r in rows]
    lines = _keep_header(path, lines)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    # 写完立刻自检：自己能解析出来的才算写成功。否则一个转义 bug
    # 会毁掉译文文件，而错误要等到下次构建才暴露 —— 那时已经晚了。
    import tomllib
    try:
        with open(tmp, "rb") as f:
            back = tomllib.load(f)
    except Exception as exc:
        os.remove(tmp)
        raise ValueError("写入后的文件无法解析，已放弃写入：%s" % exc)
    if len(back) != len(rows):
        os.remove(tmp)
        raise ValueError("写入后条目数不符（%d vs %d），已放弃写入"
                         % (len(back), len(rows)))

    os.replace(tmp, path)          # 原子替换：中途失败不留半个文件
    return len(lines)


def patch_all(lang, rows):
    """只写改动过的条目，其余原样保留。

    分段加载之后前端只见过几十条，顺序也不保证，所以**不能**按
    「前端说什么就是什么」整表写回去 —— 那样会把没加载过的条目
    全清空。这里只改传上来的那几个，其余从现有文件里原样读出来。

    顺序以**现有文件**为准（基准 id 顺序不能变，多一条会让后面
    全部错位），所以传上来的 id 只用来查值。
    """
    if lang in T.REFERENCE_LANGS:
        raise ValueError("%s 是只读参考原文，不能写入" % lang)

    path = T.lang_path(lang)
    try:
        import tomllib
        with open(path, "rb") as f:
            cur = tomllib.load(f)
    except FileNotFoundError:
        cur = {}

    base = load_all()                    # 含 id 顺序与 ctx
    order = [r["id"] for r in base]

    upd = {r["id"]: r["text"] for r in rows}
    unknown = [i for i in upd if i not in cur and i not in order]
    if unknown:
        raise ValueError("有 id 不在文件里：%s" % "、".join(unknown[:3]))

    lines = []
    for rid in order:
        text = upd.get(rid)
        if text is None:
            text = cur.get(rid, "")      # 没传的保持原样
        lines.append('"%s" = "%s"' % (rid, toml_escape(text)))
    lines = _keep_header(path, lines)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    import tomllib
    try:
        with open(tmp, "rb") as f:
            back = tomllib.load(f)
    except Exception as exc:
        os.remove(tmp)
        raise ValueError("写入后的文件无法解析，已放弃写入：%s" % exc)
    if len(back) != len(order):
        os.remove(tmp)
        raise ValueError("写入后条目数不符，已放弃写入")

    os.replace(tmp, path)
    return len(order), len(upd)


#: 语言代码就是文件名，也只允许这些字符 —— 它要拼进路径。
RE_LANG_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")


def lang_status(code):
    """这个语言代码现在能不能用。返回一份给界面直接显示的自述。

    为什么要单独有这一步：新建语言是**写文件**，而".toml 已经在那儿"
    在界面上完全看不出来（下拉里只列已记录的语言）。让输入框一边打字
    一边问服务端，用户当场就能看到「这个名字已被占用」，而不是点下去
    才发现。真正写盘那一步还有一道独占创建的保险（见 new_lang）。
    """
    code = (code or "").strip()
    if not code:
        return {"code": code, "ok": False, "reason": "先填一个语言代码"}
    if not RE_LANG_CODE.match(code):
        return {"code": code, "ok": False, "exists": False,
                "reason": "只能字母开头，含字母 / 数字 / - / _，最长 16 个字符"}
    if code.lower() in T.REFERENCE_LANGS:
        return {"code": code, "ok": False, "exists": True, "reference": True,
                "reason": "%s 是只读参考语言，不能当新语言的代码" % code}

    path = T.lang_path(code)
    if os.path.exists(path):
        return {"code": code, "ok": False, "exists": True, "reference": False,
                "path": path,
                "reason": "%s 已经存在（%s.toml），不会覆盖" % (code, code)}
    return {"code": code, "ok": True, "exists": False, "reference": False}


def new_lang(code, src):
    """以 src 为模板，复制出一份新语言。返回 {"code", "from"}。

    为什么是「复制一份」而不是「建一张空表」：条目数必须与基准表（en.gog_1.1.2.3）
    完全一致（合并与校验都按位置对齐，少一条都会让后面的 hash 错位）。
    空表在第一次保存时就会被判成「少 3548 条」；拿一个现成语言当模板，
    天然就是完整的一张表 —— 而且它自带参照，用户只要把右边逐条改掉。

    只做复制：不替用户决定新语言的译文。模板选 zh 就是「以中文为底」，
    选 en 就是「从英文原文起译」，两种都合理。
    """
    code = (code or "").strip()
    src = (src or "").strip()

    st = lang_status(code)
    if not st["ok"]:
        raise ValueError(st["reason"])
    if not src:
        raise ValueError("没有选择模板语言")

    src_path = T.lang_path(src)
    if not os.path.isfile(src_path):
        raise ValueError("模板语言不存在：%s" % src)
    dst = T.lang_path(code)

    with open(src_path, "rb") as f:
        data = f.read()

    # 模板本身得是一张完整的表：id 顺序与基准表一致才敢复制。
    # 复制一份对不齐的表，等于把错误原样传给新语言，而且更晚才发现。
    import tomllib
    doc = tomllib.loads(data.decode("utf-8"))
    rows = [k for k in doc if k != "ctx"]
    with open(T.lang_path(T.BASE_LANG), "rb") as f:
        base = tomllib.load(f)
    order = [k for k in base if k != "ctx"]
    if rows != order:
        raise ValueError("模板 %s 的条目与 %s 对不齐（%d vs %d），不能当模板"
                         % (src, T.BASE_LANG, len(rows), len(order)))

    # 【关键】独占创建，不用「先 exists() 再 replace」：那两步之间有窗口，
    # 期间别人（另一个编辑器窗口、或用户自己刚放进去的文件）建了同名文件，
    # replace 会把它**静默覆盖**掉。O_EXCL 让内核来保证「只能新建」。
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(dst, flags)
    except FileExistsError:
        raise ValueError("语言 %s 已经存在（%s.toml），没有覆盖" % (code, code))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except Exception:
        # 写了一半就失败：别留一个残缺的语言文件
        try:
            os.remove(dst)
        except OSError:
            pass
        raise

    return {"code": code, "from": src}


# ---------------------------------------------------------------- HTTP

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
            if path.startswith("/api/"):
                return self.get_api(path, urllib.parse.parse_qs(parsed.query))
            return self.get_static(path)
        except Exception as exc:            # 兜底：别让一个异常把连接挂死
            return self.send_error_json(500, exc)

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        try:
            if not path.startswith("/api/"):
                return self.send_error_json(404, "not found")
            return self.post_api(path)
        except ValueError as exc:
            return self.send_error_json(400, exc)
        except Exception as exc:
            return self.send_error_json(500, exc)

    # ---- GET

    def get_static(self, path):
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(DIST, rel))
        # 目录穿越：拼出来的路径必须还在 dist\ 里
        if os.path.commonpath([full, DIST]) != DIST:
            return self.send_error_json(404, "not found")
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        return self.send_file(full)

    def get_api(self, path, query):
        if path == "/api/health":
            return self.send_json({"app": "pr2-editor", "pid": os.getpid(),
                                   "port": CURRENT_PORT, "token": CURRENT_TOKEN})

        if path == "/api/langs":
            return self.send_json({"editable": T.target_langs(),
                                   "all": T.all_langs(),
                                   "base": T.BASE_LANG})

        if path == "/api/lang-exists":
            # 输入框一边打字一边问：这个名字能不能用、是不是已经有一份了。
            return self.send_json(lang_status((query.get("code") or [""])[0]))

        if path == "/api/count":
            # 只报条数与 id 顺序，不带正文：首屏拿到它就能把滚动条画对。
            rows = load_all()
            return self.send_json({"count": len(rows),
                                   "ids": [r["id"] for r in rows]})

        if path == "/api/terms":
            # 术语一致性：术语表（glossary\terms.toml）当规则用。
            # 返回 {id: ["术语：Frigate 应为「巡防舰」", …]}，前端标在行上。
            lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
            groups, ignore = terms_check.load_terms()
            if not groups:
                return self.send_json({"count": 0, "issues": {},
                                       "note": "没有术语表"})
            rows = load_all()
            en = {r["id"]: r.get(T.BASE_LANG, "") for r in rows}
            doc = {r["id"]: r.get(lang, "") for r in rows if r["id"] not in ignore}
            issues = terms_check.check_lang(lang, groups, en, doc)
            out = {}
            for x in issues:
                out.setdefault(x["id"], []).append(
                    "%s：应为「%s」" % (x["term"], x["expected"]))
            return self.send_json({"count": len(issues), "issues": out,
                                   "lang": lang})

        if path == "/api/entries":
            offset = int((query.get("offset") or ["0"])[0])
            limit = int((query.get("limit") or ["0"])[0])
            rows = load_all()
            if limit <= 0:
                return self.send_json(rows)
            if offset < 0:
                offset = 0
            return self.send_json(rows[offset:offset + limit])

        if path == "/api/search":
            # 搜索必须走服务端：正文本来就没全量在前端，前端过滤等于
            # 又要先把 320 KB 全拉下来，分段加载就白做了。
            q = (query.get("q") or [""])[0].strip().lower()
            if not q:
                return self.send_json([])
            rows = load_all()
            langs = T.all_langs()
            out = []
            for e in rows:
                if q in e["id"].lower():
                    out.append(e)
                    continue
                for k in langs:
                    if q in (e.get(k) or "").lower():
                        out.append(e)
                        break
            return self.send_json(out)

        return self.send_error_json(404, "unknown api: %s" % path)

    # ---- POST

    def post_api(self, path):
        body = self.read_json()

        if path == "/api/check":
            text = body.get("text", "")
            lang = body.get("lang", "zh")
            hid = body.get("id", "")
            row = next((r for r in load_all() if r["id"] == hid), None)
            return self.send_json([] if row is None else check_one(row, lang, text))

        if path == "/api/save":
            lang = body.get("lang", "")
            return self.send_json({"ok": True,
                                   "written": save_all(lang, rows_of(body))})

        if path == "/api/patch":
            lang = body.get("lang", "")
            written, changed = patch_all(lang, rows_of(body))
            return self.send_json({"ok": True, "written": written,
                                   "changed": changed})

        if path == "/api/newlang":
            made = new_lang(body.get("code", ""), body.get("from", ""))
            return self.send_json({"ok": True, **made})

        if path == "/api/shutdown":
            self.send_json({"ok": True})
            # 稍等一点，先让这条响应写回客户端，再收摊。
            threading.Timer(0.2, stop_server).start()
            return None

        return self.send_error_json(404, "unknown api: %s" % path)


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
    a = ap.parse_args()

    if not os.path.isdir(DIST):
        _say("注意：找不到前端产物 %s" % DIST)
        _say("      先构建：cd src\\editor && npm install && npm run build")

    port = a.port
    if port_in_use(a.host, port):
        # 编辑器是**常驻服务**，关掉浏览器不会停它，所以「端口被占」
        # 最常见的意思是「它已经在跑了」。但必须问一句是不是**我们**的 ——
        # 别的程序占着这个端口时，打开浏览器只会看到一个不相干的页面。
        if editor_on(a.host, port):
            _say("编辑器已在运行：http://%s:%d/" % (a.host, port))
            if not a.no_open:
                webbrowser.open("http://%s:%d/" % (a.host, port))
            return 0

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
    httpd = ThreadingHTTPServer((a.host, port), Handler)
    httpd.daemon_threads = True
    SERVER = httpd

    _say("PR2 本地化编辑器：http://%s:%d/" % (a.host, port))
    _say("（只监听本机。按 Ctrl+C 停止。）")
    if not a.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(
            "http://%s:%d/" % (a.host, port))).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
