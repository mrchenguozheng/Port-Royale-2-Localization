#!/usr/bin/env python3
# coding: utf-8
r"""src/editor/server.py — 本地 Web 编辑器的后端（FastAPI）

浏览器负责显示与编辑，**校验规则全在这里** —— 因为规则本来就在
translate.py / compile_pack.py 里，那是唯一的一份。抄到 JS 里就多一份
实现，两边不一致时没人知道该信哪个。

同时托管前端产物 dist\（astro build 的输出）。所以只起一个服务就够，
不需要再单独跑 astro dev。

启动：
    python src/editor/server.py              # 起服务并开浏览器
    python src/editor/server.py --no-open    # 只起服务
    python src/editor/server.py --port 9000

只监听 127.0.0.1：这些接口能改仓库里的译文文件，不该暴露到网络上。
"""

import argparse
import os
import sys
import threading
import webbrowser

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

from fastapi import FastAPI, HTTPException    # noqa: E402
from fastapi.responses import JSONResponse      # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel               # noqa: E402


# ---------------------------------------------------------------- 模型

class RowIn(BaseModel):
    id: str
    text: str = ""


class CheckIn(BaseModel):
    id: str
    text: str = ""
    lang: str = "zh"


class SaveIn(BaseModel):
    lang: str
    rows: list[RowIn]


class PatchIn(BaseModel):
    """只提交改动过的条目 —— 配合分段加载用。

    分段之后前端只握着几十条，没加载过的那些它根本没见过。
    整表提交就得先把 320 KB 重新拉一遍再原样送回，纯浪费。
    """
    lang: str
    rows: list[RowIn]


app = FastAPI(title="PR2 本地化编辑器", docs_url=None, redoc_url=None)


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

    en = entry.get("en", "") or ""

    # 占位符：复用 compile_pack 的实现 —— 那里处理了 %2%1 紧邻的情况
    errors, warnings = [], []
    C.check_placeholders(entry.get("id", ""), en, text, errors, warnings)
    for e in errors:
        out.append({"level": "error", "text": _strip_id(e, entry.get("id", ""))})
    for w in warnings:
        out.append({"level": "warn", "text": _strip_id(w, entry.get("id", ""))})

    # 标签轮廓：只比数量与名字（译文可以换颜色）。
    # 但译文**不得新增**任何排版标签 —— 换行只能用原文已有的 <n> 或 |。
    en_p, zh_p = T.tag_profile(en), T.tag_profile(text)
    if en_p != zh_p:
        added = sorted({t for t in zh_p if zh_p.count(t) > en_p.count(t)})
        if added:
            out.append({"level": "error",
                        "text": "译文擅自新增标签 %s —— 换行只能用原文已有的 <n> 或 |"
                                % " ".join(added)})
        else:
            out.append({"level": "warn",
                        "text": "标签数量比原文少（原文 %s，译文 %s）"
                                % (" ".join(en_p), " ".join(zh_p))})
    return out


def _strip_id(msg, hid):
    """去掉 compile_pack 消息开头重复的 id，界面自己会显示 id 列。"""
    return msg[len(hid):].strip() if msg.startswith(hid) else msg


# ---------------------------------------------------------------- 数据

def load_all():
    """读全部语言，按 id 合并成前端要的形态。

    走 translate.load_toml —— 它已经在做合并，且强制条目数与顺序与
    en.toml 一致。这条是硬要求：多一条会让后面全部错位。
    """
    doc = T.load_toml()
    langs = T.all_langs()
    rows = []
    for e in T.entries(doc):
        r = {"id": e.get("id", ""), "ctx": e.get("ctx", "") or ""}
        for k in langs:
            r[k] = e.get(k, "") or ""
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


# ---------------------------------------------------------------- 接口

@app.get("/api/langs")
def api_langs():
    return {"editable": T.target_langs(), "all": T.all_langs()}


@app.get("/api/count")
def api_count():
    """只报条数与 id 顺序，不带正文。

    前端首屏只要这个：拿到条数就能把滚动条画对，正文等滚到哪再取哪。
    """
    rows = load_all()
    return {"count": len(rows), "ids": [r["id"] for r in rows]}


@app.get("/api/entries")
def api_entries(offset: int = 0, limit: int = 0):
    """按需取一段。limit=0 表示全量（给命令行 / 调试用）。

    为什么分段：3548 条全量是约 320 KB 的 JSON，加上前端要建
    3548×3 个 DOM 节点，首屏会明显卡一下。分段之后首屏只取
    屏幕上那几十条，其余等滚到再取。
    """
    try:
        rows = load_all()
    except SystemExit as exc:          # load_toml 用它报业务错误
        raise HTTPException(500, str(exc))
    if limit <= 0:
        return rows
    if offset < 0:
        offset = 0
    return rows[offset:offset + limit]


@app.get("/api/search")
def api_search(q: str = ""):
    """按关键字搜索，只返回命中的条目。

    搜索必须走服务端而不是前端过滤：正文本来就**没有**全量在前端
    （现在只按需取可视区域那段），前端过滤等于又要先把 320 KB 全拉下来，
    分段的意义就没了。
    """
    q = (q or "").strip().lower()
    if not q:
        return []
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
    return out


@app.post("/api/check")
def api_check(body: CheckIn):
    try:
        rows = load_all()
    except SystemExit as exc:
        raise HTTPException(500, str(exc))
    entry = next((r for r in rows if r["id"] == body.id), None)
    if entry is None:
        return []
    return check_one(entry, body.lang, body.text)


@app.post("/api/save")
def api_save(body: SaveIn):
    try:
        n = save_all(body.lang, [r.model_dump() for r in body.rows])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "written": n}


@app.post("/api/patch")
def api_patch(body: PatchIn):
    """只写改动过的条目，其余原样保留。

    分段加载之后前端只见过几十条，顺序也不保证，所以**不能**按
    「前端说什么就是什么」整表写回去 —— 那样会把没加载过的条目
    全清空。这里只改传上来的那几个，其余从现有文件里原样读出来。

    顺序以**现有文件**为准（基准 id 顺序不能变，多一条会让后面
    全部错位），所以传上来的 id 只用来查值。
    """
    if body.lang in T.REFERENCE_LANGS:
        raise HTTPException(400, "%s 是只读参考原文，不能写入" % body.lang)

    path = T.lang_path(body.lang)
    try:
        import tomllib
        with open(path, "rb") as f:
            cur = tomllib.load(f)
    except FileNotFoundError:
        cur = {}
    except Exception as exc:
        raise HTTPException(500, "读现有 %s.toml 失败：%s" % (body.lang, exc))

    base = load_all()                    # 含 id 顺序与 ctx
    order = [r["id"] for r in base]

    upd = {r.id: r.text for r in body.rows}
    unknown = [i for i in upd if i not in cur and i not in order]
    if unknown:
        raise HTTPException(400, "有 id 不在文件里：%s" % "、".join(unknown[:3]))

    lines = []
    for rid in order:
        text = upd.get(rid)
        if text is None:
            text = cur.get(rid, "")      # 没传的保持原样
        lines.append('"%s" = "%s"' % (rid, toml_escape(text)))

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    import tomllib
    try:
        with open(tmp, "rb") as f:
            back = tomllib.load(f)
    except Exception as exc:
        os.remove(tmp)
        raise HTTPException(500, "写入后的文件无法解析，已放弃写入：%s" % exc)
    if len(back) != len(order):
        os.remove(tmp)
        raise HTTPException(500, "写入后条目数不符，已放弃写入")

    os.replace(tmp, path)
    return {"ok": True, "written": len(order), "changed": len(upd)}


# ---------------------------------------------------------------- 静态

# 挂在最后：前面的 /api 路由要先注册，否则全被静态兜底吃掉。
if os.path.isdir(DIST):
    # Astro 把带哈希的资源放在 /_astro/ 下，目录名是它自己定的，
    # 别猜 —— 直接把 dist 整体挂到根，前端要的路径原样就能命中。
    app.mount("/", StaticFiles(directory=DIST, html=True), name="static")
else:
    @app.get("/")
    def index():
        return JSONResponse(
            {"error": "前端还没构建。请先在 src\\editor 下跑 npm install && npm run build"},
            status_code=503)


def _say(text):
    """打印一行提示，但在没有 stdout 的环境下（pythonw）安静跳过。

    这个服务是用 pythonw 启动的 —— 不弹黑框。pythonw 里 sys.stdout 是
    None，任何 print 都会 AttributeError。所以每句提示都要先问一句。
    """
    if sys.stdout is not None:
        print(text)


def main():
    ap = argparse.ArgumentParser(description="PR2 本地化编辑器（本地 Web）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help="端口，默认 %d" % DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1",
                    help="只监听本机。有接口能写文件，不要改成 0.0.0.0。")
    ap.add_argument("--no-open", action="store_true", help="不自动开浏览器")
    a = ap.parse_args()

    import uvicorn

    if not os.path.isdir(DIST):
        _say("注意：找不到前端产物 %s" % DIST)
        _say("      先构建：cd src\\editor && npm install && npm run build")

    port = a.port
    if port_in_use(a.host, port):
        # 这不是错误 —— 编辑器是**常驻服务**，关掉浏览器不会停它。
        # 所以「端口已占用」最常见的意思就是「它已经在跑了」，
        # 该做的是把浏览器打开，而不是报错退出。
        _say("端口 %d 已有服务在跑，直接打开它。" % port)
        if not a.no_open:
            webbrowser.open("http://%s:%d/" % (a.host, port))
        return 0

    # 端口被别的程序占了（比如上次崩了留下的）—— 往上找一个空的。
    for p in range(a.port + 1, a.port + 20):
        if not port_in_use(a.host, p):
            _say("端口 %d 被占，改用 %d。" % (a.port, p))
            port = p
            break
    else:
        _say("从 %d 往上 20 个端口都被占了。" % a.port)
        return 1

    _say("PR2 本地化编辑器：http://%s:%d/" % (a.host, port))
    _say("（只监听本机。按 Ctrl+C 停止。）")
    if not a.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(
            "http://%s:%d/" % (a.host, port))).start()

    # uvicorn 的日志初始化会调 sys.stdout.isatty() 来决定要不要上色，
    # 而 pythonw.exe **根本没有 stdout**（是 None）—— 于是直接
    # AttributeError 崩掉，表现为「点了按钮什么都没发生」。
    # log_config=None 跳过那套配置，access_log=False 关掉每请求一行的
    # 访问日志（本地服务，吵）。
    uvicorn.run(app, host=a.host, port=port, log_config=None,
                access_log=False)
    return 0


def port_in_use(host, port):
    """端口有没有人在听。

    用 bind 试探而不是「连接一下」：后者分不清「服务在跑」与
    「连接被拒」，而在端口冲突时恰恰要分清。
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
