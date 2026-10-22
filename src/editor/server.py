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
import io
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

# pythonw 拉起时 stdout/stderr 是 None；warnings/print 往它们写会抛
# AttributeError: 'NoneType' object has no attribute 'write'。
# 换成 devnull，保证没有控制台窗口时服务也正常。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")

DIST = os.path.join(HERE, "dist")                            # astro build 的产物
DEFAULT_PORT = 8777

# translate / compile_pack 是脚本不是包，直接把 tools\ 加进 sys.path 来 import。
# 这也让规则只有一份：编辑器与语言包走同一批函数。
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import translate as T          # noqa: E402
import compile_pack as C       # noqa: E402
import terms_check             # noqa: E402
import apply_zh_rules as ZH_GEN  # noqa: E402
import lang_rules  # noqa: E402
import pr2ctl as P            # noqa: E402


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
    """扫一遍编辑器常用端口，列出还在跑的实例（含自己）。"""
    out = []
    for port in range(8777, 8777 + 24):
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/api/health" % port, timeout=0.3) as resp:
                info = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
        if not isinstance(info, dict) or info.get("app") != "pr2-editor":
            continue
        info["current"] = port == CURRENT_PORT
        out.append(info)
    return {"current": CURRENT_PORT, "instances": out}


def rule_trace(hid, lang):
    """逐阶段还原这条译文经过的格式化规则。"""
    seed_path = os.path.join(os.path.dirname(SRC), "src", "seed", "%s.toml" % lang)
    if not os.path.isfile(seed_path):
        return None
    doc = tomllib.load(open(seed_path, "rb"))
    if hid not in doc:
        return None
    seed = doc[hid]
    rules = lang_rules.get(lang)
    stages = [{"key": "seed", "label": "初版", "text": seed}]

    if lang == "zh":
        norm = rules.normalize(seed)
        stages.append({"key": "punct", "label": "标点规范化", "text": norm})
        conj = ZH_GEN.fix_conj(norm)
        stages.append({"key": "conj", "label": "连词后空格", "text": conj})
        given, surn, extras, towns = ZH_GEN.build_names(doc)
        parts = ZH_GEN.TAG.split(conj)
        res = []
        for i, part in enumerate(parts):
            if i % 2 == 1 or not part:
                res.append(part)
                continue
            spans = ZH_GEN.find_names(part, given, surn, extras + towns)
            res.append(ZH_GEN.pad_names(part, spans, towns) if spans else part)
        stages.append({"key": "names", "label": "人名/城镇名空格", "text": "".join(res)})
    else:
        stages.append({"key": "punct", "label": "规范化",
                       "text": rules.normalize(seed)})

    live = {r["id"]: r.get(lang, "") for r in load_all()}.get(hid, "")
    stages.append({"key": "live", "label": "当前译文", "text": live})
    return stages


def known_dirs():
    """settings 里记住过的游戏目录，按最近使用排序。"""
    st = P.load_settings()
    cur = st.get("current") or ""
    out = []
    for sha, entry in (st.get("dirs") or {}).items():
        d = entry.get("dir") or ""
        valid = bool(d) and P.is_game_dir(d)
        label = entry.get("label") or (P.version_label(sha) if valid else "")
        out.append({
            "sha": sha,
            "dir": d,
            "label": label,
            "last_used": entry.get("last_used") or "",
            "current": sha == cur,
            "valid": valid,
        })
    out.sort(key=lambda x: x.get("last_used") or "", reverse=True)
    return out


def start_dir():
    """当前游戏目录。current 存的是 PR2.exe 的 SHA，不是路径。"""
    st = P.load_settings()
    cur = st.get("current") or ""
    entry = (st.get("dirs") or {}).get(cur)
    if entry and entry.get("dir"):
        return entry["dir"]
    return cur if os.path.isdir(cur) else (st.get("last_dir") or "")


def start_status():
    d = start_dir()
    info = {"dir": d, "valid": False, "langs": P.available_langs()}
    if d and P.is_game_dir(d):
        sha, build = P.identify_dir(d)
        info.update({
            "valid": True,
            "version": P.version_label(sha),
            "sha": sha,
            "patches": [{"name": n, "exists": True} for n, _p, _d in P.patch_items(d)],
            "packs": P.installed_langs(d),
            "locale": P.read_ini_language(os.path.join(d, P.PACK_DIR, "locale.ini")),
        })
    return info


class _StartEvents:
    """把 core 的事件流写进 START_JOB。"""

    def put(self, ev):
        kind, payload = ev if isinstance(ev, tuple) else ("line", str(ev))
        with START_LOCK:
            if kind == "line":
                START_JOB["lines"].append(payload)
                if len(START_JOB["lines"]) > 500:
                    del START_JOB["lines"][:-500]
            elif kind.endswith("_ok"):
                START_JOB["ok"] = True
            elif kind.endswith("_failed"):
                START_JOB["ok"] = False


def start_run(kind, fn):
    with START_LOCK:
        if START_JOB["running"]:
            return {"ok": False, "error": "已有任务在运行"}
        START_JOB.update(running=True, lines=[], done=False, ok=False,
                         kind=kind, error="")
    ev = _StartEvents()

    def worker():
        try:
            fn(ev)
        except Exception as exc:
            with START_LOCK:
                START_JOB["error"] = str(exc)
                START_JOB["ok"] = False
        finally:
            with START_LOCK:
                START_JOB["running"] = False
                START_JOB["done"] = True

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "kind": kind}


# ---------------------------------------------------------------- 筛选

_ATTN_CACHE = {}


def attention_ids(lang):
    """有问题的条目：占位符/标签错误、空译文、术语不一致。

    check_one 是纯正则，但 3500 条也不便宜，按译文文件 mtime 缓存。
    """
    try:
        files = [T.lang_path(lang),
                 os.path.join(os.path.dirname(SRC), "glossary", "terms.toml")]
        key = (lang, tuple(os.path.getmtime(f) for f in files if os.path.isfile(f)))
    except OSError:
        key = (lang, 0)
    if key in _ATTN_CACHE:
        return _ATTN_CACHE[key]

    rows = load_all()
    bad = []
    for r in rows:
        text = r.get(lang, "") or ""
        probs = check_one(r, lang, text)
        if any(p.get("level") in ("error", "warn") for p in probs):
            bad.append(r["id"])
    try:
        groups, ignore = terms_check.load_terms()
        if groups:
            en = {r["id"]: r.get(T.BASE_LANG, "") for r in rows}
            doc = {r["id"]: r.get(lang, "") for r in rows if r["id"] not in ignore}
            for x in terms_check.check_lang(lang, groups, en, doc):
                if x["id"] not in bad:
                    bad.append(x["id"])
    except Exception:
        pass
    _ATTN_CACHE[key] = bad
    return bad



MEANINGS = os.path.join(os.path.dirname(SRC), "glossary", "placeholder_meanings.toml")
_MEAN_CACHE = {"key": None, "data": {}}


def load_meaning_overrides():
    try:
        key = os.path.getmtime(MEANINGS)
    except OSError:
        return {}
    if _MEAN_CACHE["key"] != key:
        try:
            with open(MEANINGS, "rb") as fh:
                _MEAN_CACHE.update(key=key, data=tomllib.load(fh))
        except Exception:
            _MEAN_CACHE.update(key=key, data={})
    return _MEAN_CACHE["data"]


def meaning_for(lang, hid):
    return (load_meaning_overrides().get(lang) or {}).get(hid.lower(), {})


def save_meaning(lang, hid, token, meaning):
    data = {}
    if os.path.isfile(MEANINGS):
        try:
            data = tomllib.load(open(MEANINGS, "rb"))
        except Exception:
            data = {}
    by_lang = dict(data.get(lang) or {})
    key = hid.lower()
    cur = dict(by_lang.get(key) or {})
    if meaning is None:
        cur.pop(token, None)
    else:
        cur[token] = meaning        # 允许空字符串
    if cur:
        by_lang[key] = cur
    else:
        by_lang.pop(key, None)
    if by_lang:
        data[lang] = by_lang
    else:
        data.pop(lang, None)

    lines = ["# 按语言 + hash 的占位符含义覆盖（编辑器里手动修改）。", ""]
    for lg in sorted(data):
        for h in sorted(data[lg]):
            lines.append('["%s"."%s"]' % (lg, h))
            for tok in sorted(data[lg][h]):
                val = data[lg][h][tok].replace("\\", "\\\\").replace('"', '\\"')
                lines.append('"%s" = "%s"' % (tok.replace('"', '\\"'), val))
            lines.append("")
    with open(MEANINGS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return meaning_for(lang, hid)


HASH_RULES = os.path.join(os.path.dirname(SRC), "glossary", "hash_rules.toml")
_HASH_CACHE = {"key": None, "data": {}}


def load_hash_rules():
    """按 hash 的例外规则，目前只有 skip_terms（不检查这些术语）。"""
    try:
        key = os.path.getmtime(HASH_RULES)
    except OSError:
        return {}
    if _HASH_CACHE["key"] != key:
        try:
            with open(HASH_RULES, "rb") as fh:
                data = tomllib.load(fh)
        except Exception:
            data = {}
        _HASH_CACHE.update(key=key, data=data)
    return _HASH_CACHE["data"]


def hash_rule(hid):
    return load_hash_rules().get(hid.lower(), {})


def filter_term_issues(issues):
    out = []
    for x in issues:
        skip = hash_rule(x.get("id", "")).get("skip_terms", [])
        if x.get("term") in skip:
            continue
        out.append(x)
    return out


def save_hash_rule(hid, term, skip):
    data = {}
    if os.path.isfile(HASH_RULES):
        try:
            data = tomllib.load(open(HASH_RULES, "rb"))
        except Exception:
            data = {}
    key = hid.lower()
    cur = dict(data.get(key) or {})
    terms = list(cur.get("skip_terms") or [])
    if skip and term not in terms:
        terms.append(term)
    if not skip and term in terms:
        terms.remove(term)
    if terms:
        cur["skip_terms"] = terms
        data[key] = cur
    else:
        data.pop(key, None)
    lines = ["# 按 hash 的术语例外：skip_terms 里的术语在这条不检查。", ""]
    for k in sorted(data):
        lines.append('["%s"]' % k)
        vals = ", ".join('"%s"' % v.replace('"', '\\"') for v in data[k].get("skip_terms", []))
        lines.append("skip_terms = [%s]" % vals)
        lines.append("")
    io_open = open
    with io_open(HASH_RULES, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return data.get(key, {})

def filter_ids(kind, lang):
    rows = load_all()
    if kind == "attention":
        keep = set(attention_ids(lang))
        return [r["id"] for r in rows if r["id"] in keep]
    return [r["id"] for r in rows]



# ---------------------------------------------------------------- 语境推断

ORDER_FILE = os.path.join(HERE, "data", "table-order.txt")
_ORDER = None

PH_MEAN = {
    "@T$": "城镇名", "@N$": "人名", "@n$": "国家", "@D$": "日期",
    "@I$": "整数", "@a$": "数量", "@G$": "货物/商品", "@g$": "金额",
    "@S$": "船型", "@l$": "位置（海图）", "@C$": "船队", "@P$": "海盗名",
}
TAG_MEAN = [
    ("<n:", "段落间距"), ("<n>", "换行"), ("<c>", "颜色：开始"), ("<o:", "颜色值"),
    ("<r>", "红色文字"), ("<t>", "制表"), ("<ts:", "制表位"), ("<g:", "图标/图形"),
    ("<gs:", "图形脚本标记（需原样保留）"), ("<f:", "字体"),
]


def table_order():
    global _ORDER
    if _ORDER is None:
        try:
            with open(ORDER_FILE, encoding="utf-8") as fh:
                _ORDER = [l.strip() for l in fh if l.strip()]
        except OSError:
            _ORDER = []
    return _ORDER


ARG_RX = re.compile(r"@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z]")


def placeholder_counts(text):
    from collections import Counter
    return Counter(ARG_RX.findall(text or ""))


def placeholder_problems(hid, lang, text):
    """返回 [(token, 原文数, 译文数)]，只列数量不一致的。"""
    c = context_of(hid, lang)
    if c is None:
        return []
    en = placeholder_counts(c.get("en") or "")
    zh = placeholder_counts(text)
    out = []
    for tok in set(en) | set(zh):
        if en[tok] != zh[tok]:
            out.append((tok, en[tok], zh[tok]))
    out.sort()
    return out


def placeholders_of(text):
    out = []
    for m in re.finditer(r"@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z]", text):
        tok = m.group(0)
        if tok in out:
            continue
        out.append(tok)
    return out


def context_of(hid, lang):
    rows = {r["id"]: r for r in load_all()}
    row = rows.get(hid)
    if row is None:
        return None
    en = row.get(T.BASE_LANG, "") or ""
    zh = row.get(lang, "") or ""
    reasons = []

    # %N 没有固定名字，按英文上下文给个保守说明。
    es = en.strip()
    role_hint = {}
    if es.startswith("%1 %2 %3"):
        role_hint = {"%1": "等级/头衔", "%2": "名", "%3": "姓"}
    elif es.startswith("%1 %2 "):
        role_hint = {"%1": "等级/头衔", "%2": "姓名"}
    elif re.search(r"\b(Governor|Captain|Viceroy|King|Queen|Prince|Princess|"
                   r"Lord|Sir|Mr|Mrs|Ms|Dr|Admiral|General|Colonel|Major|"
                   r"Lieutenant)\s+%1 %2", en):
        role_hint = {"%1": "名", "%2": "姓"}

    overrides = meaning_for(lang, hid)
    ph = []
    for tok in placeholders_of(en):
        if tok in overrides:
            mean = overrides[tok]      # 空字符串也算显式含义
        else:
            mean = (role_hint.get(tok)
                    or next((v for k, v in PH_MEAN.items()
                             if tok.startswith(k)), "变量/参数"))
        ph.append({"token": tok, "meaning": mean})

    tags = []
    for tok, mean in TAG_MEAN:
        if tok in en and mean not in tags:
            tags.append(mean)

    cat = "通用文本"
    try:
        ko = C.load_keep_original()
    except Exception:
        ko = {}
    group = ko.get(hid) or ko.get(hid.lower())
    if group:
        cat = "原样保留：%s" % group
        reasons.append("在 keep_original 清单里，编译时强制输出英文原文")
    elif not zh:
        cat = "空译文"
        reasons.append("这条还没有译文，游戏里会显示英文")
    elif not re.sub(r"<[^>]*>|@[A-Za-z]\$[^$]*\$|%[0-9A-Za-z]+", "", en).strip():
        cat = "格式串（只有占位符/标签）"
        reasons.append("去掉标签和占位符后没有正文")
    elif re.search(r"(?i)\b(producer|manager|director|qa|ascaron|programming|music|sound)\b", en) and len(en) < 60:
        cat = "职员表条目"
        reasons.append("匹配到制作名单/职位用语")
    elif ph and re.search(r"(?i)(until|before|destroy|deliver|supply|build|bring|escort|attack|capture)", en):
        cat = "任务目标/委托"
        reasons.append("含占位符，且出现 until/before/destroy/deliver 这类任务用语")
    elif "?" in en or "!" in en:
        cat = "对话/口气句"
        reasons.append("含问号或感叹号")
    elif len(en) <= 24 and not re.search(r"[.。!?]", en):
        cat = "界面标签/短标题"
        reasons.append("很短且没有句末标点，常见于按钮、标题、列表项")
    elif "<n><n>" in en or len(en) > 200:
        cat = "长文本（帮助/编年史/教程）"
        reasons.append("多段或篇幅长，通常出现在帮助、编年史、教程窗口")
    if tags:
        reasons.append("含格式标记：" + "、".join(tags))

    ids = table_order()
    try:
        idx = ids.index(hid)
    except ValueError:
        idx = -1
    neigh = []
    if idx >= 0:
        for j in range(max(0, idx - 3), min(len(ids), idx + 4)):
            if j == idx:
                continue
            r = rows.get(ids[j])
            if not r:
                continue
            neigh.append({"id": r["id"],
                          "en": (r.get(T.BASE_LANG, "") or "")[:120],
                          "zh": (r.get(lang, "") or "")[:120]})

    return {"id": hid, "category": cat, "reasons": reasons,
            "placeholders": ph, "tags": tags, "en": en, "zh": zh,
            "neighbors": neigh}


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

    # 模板与基准表对不齐时（版本不同、多几条少几条），按基准表的 id 重新排：
    # 多出来的 id 丢掉，缺的 id 用基准语言补齐，保证新语言仍是一张完整的表。
    aligned = rows == order
    dropped = filled = 0
    if not aligned:
        src_map = {k: v for k, v in doc.items() if k != "ctx"}
        dropped = len(set(src_map) - set(order))
        filled = len(set(order) - set(src_map))
        lines = ["# 由模板 %s 自动对齐到 %s 生成。" % (src, T.BASE_LANG), ""]
        for hid in order:
            val = src_map.get(hid)
            if val is None:
                val = base.get(hid, "")
                filled += 0
            val = str(val).replace("\\", "\\\\").replace('"', '\\"')
            lines.append('"%s" = "%s"' % (hid, val))
        data = ("\n".join(lines) + "\n").encode("utf-8")

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

    return {"code": code, "from": src, "aligned": aligned,
            "dropped": dropped, "filled": filled}


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
        if path == "/api/server/stop":
            try:
                port = int(body.get("port") or 0)
            except (TypeError, ValueError):
                return self.send_json({"ok": False, "error": "端口不对"})
            if port in (0, CURRENT_PORT):
                return self.send_json({"ok": False, "error": "不能停当前服务"})
            ok = P.editor_shutdown(port)
            return self.send_json({"ok": ok, "port": port})

        if path == "/api/start/pick":
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-STA", "-Command",
                     "Add-Type -AssemblyName System.Windows.Forms; "
                     "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                     "$d.Description = '选择 Port Royale 2 游戏目录'; "
                     "$d.ShowNewFolderButton = $false; "
                     "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
                     "{ Write-Output $d.SelectedPath }"],
                    capture_output=True, text=True, timeout=180,
                    creationflags=0x08000000)
                chosen = (out.stdout or "").strip().splitlines()
                chosen = chosen[-1].strip() if chosen else ""
            except Exception as exc:
                return self.send_json({"ok": False, "error": "打开目录选择框失败：%s" % exc})
            if not chosen:
                return self.send_json({"ok": False, "error": "已取消"})
            return self.send_json({"ok": True, "path": chosen})

        if path == "/api/start/use":
            sha = (body.get("sha") or "").strip()
            st = P.load_settings()
            entry = (st.get("dirs") or {}).get(sha)
            if not entry:
                return self.send_json({"ok": False, "error": "没有这个目录"})
            st["current"] = sha
            st["last_dir"] = entry.get("dir") or st.get("last_dir", "")
            P.save_settings(st)
            return self.send_json({"ok": True, **start_status()})

        if path == "/api/start/forget":
            sha = (body.get("sha") or "").strip()
            st = P.load_settings()
            dirs = st.get("dirs") or {}
            entry = dirs.pop(sha, None)
            if not entry:
                return self.send_json({"ok": False, "error": "没有这个目录"})
            if st.get("current") == sha:
                st["current"] = ""
                st["last_dir"] = ""
            P.save_settings(st)
            return self.send_json({"ok": True, "dirs": known_dirs()})

        if path == "/api/start/dir":
            d = (body.get("path") or "").strip()
            if not P.is_game_dir(d):
                return self.send_json({"ok": False,
                                       "error": "该目录里没有 %s" % P.GAME_EXE})
            st = P.load_settings()
            sha, _build = P.identify_dir(d)
            st.setdefault("dirs", {})[sha] = {
                "dir": d,
                "label": P.version_label(sha),
                "last_used": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            st["current"] = sha
            st["last_dir"] = d
            P.save_settings(st)
            return self.send_json({"ok": True, **start_status()})

        if path == "/api/start/build":
            langs = [x for x in (body.get("langs") or []) if x in P.available_langs()]
            if not langs:
                return self.send_json({"ok": False, "error": "没有勾选语言"})
            return self.send_json(start_run("build", lambda ev: P.run_build(langs, ev)))

        if path == "/api/start/deploy":
            langs = [x for x in (body.get("langs") or []) if x in P.available_langs()]
            d = start_dir()
            if not d or not P.is_game_dir(d):
                return self.send_json({"ok": False, "error": "还没有选择游戏目录"})
            return self.send_json(start_run(
                "deploy", lambda ev: P.run_deploy(d, langs or None, ev)))

        if path == "/api/start/lang":
            d = start_dir()
            if not d or not P.is_game_dir(d):
                return self.send_json({"ok": False, "error": "还没有选择游戏目录"})
            code = (body.get("lang") or "").strip()
            if code not in P.available_langs():
                return self.send_json({"ok": False, "error": "没有这个语言包：%s" % code})
            ok, code = P.set_game_language(d, code)
            return self.send_json({"ok": ok, "lang": code, **start_status()})

        if path == "/api/start/launch":
            d = start_dir()
            if not d or not P.is_game_dir(d):
                return self.send_json({"ok": False, "error": "还没有选择游戏目录"})
            lang = body.get("lang") or P.game_language(d) or None
            if body.get("vanilla"):
                ok, msg = P.launch_vanilla(d)
            else:
                ok, msg = P.launch_game(d, lang)
            return self.send_json({"ok": ok, "message": msg})

        if path == "/api/health":
            return self.send_json(health_info())

        if path == "/api/server/instances":
            return self.send_json(server_instances())

        if path == "/api/langs":
            return self.send_json({"editable": T.target_langs(),
                                   "all": T.all_langs(),
                                   "base": T.BASE_LANG})

        if path == "/api/lang-exists":
            # 输入框一边打字一边问：这个名字能不能用、是不是已经有一份了。
            return self.send_json(lang_status((query.get("code") or [""])[0]))

        if path == "/api/start/status":
            return self.send_json(start_status())

        if path == "/api/start/dirs":
            return self.send_json({"dirs": known_dirs()})

        if path == "/api/start/job":
            with START_LOCK:
                return self.send_json(dict(START_JOB))

        if path == "/api/context-batch":
            ids = [x for x in (query.get("ids") or [""])[0].split(",") if x]
            lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
            out = {}
            for hid in ids[:200]:
                c = context_of(hid, lang)
                if c:
                    out[hid] = c
            return self.send_json(out)

        if path == "/api/placeholder-meanings":
            hid = (query.get("id") or [""])[0]
            lang = (query.get("lang") or ["zh"])[0]
            return self.send_json({"id": hid, "lang": lang,
                                   "meanings": meaning_for(lang, hid)})

        if path == "/api/rule-hits":
            hid = (query.get("id") or [""])[0]
            lang = (query.get("lang") or ["zh"])[0]
            data = rule_hits(hid, lang)
            if data is None:
                return self.send_json({"detail": "没有初版或条目"}, 404)
            return self.send_json(data)


        if path == "/api/rule-trace":
            hid = (query.get("id") or [""])[0]
            lang = (query.get("lang") or ["zh"])[0]
            stages = rule_trace(hid, lang)
            if stages is None:
                return self.send_json({"detail": "没有初版或条目"}, 404)
            return self.send_json({"id": hid, "stages": stages})

        if path == "/api/placeholder-meaning":
            lang = (body.get("lang") or "zh").strip() or "zh"
            hid = (body.get("id") or "").strip().lower()
            token = (body.get("token") or "").strip()
            meaning = body.get("meaning", None)
            if meaning is not None:
                meaning = str(meaning)
            if not hid or not token:
                return self.send_json({"ok": False, "error": "缺少 id 或占位符"})
            save_meaning(lang, hid, token, meaning)
            return self.send_json({"ok": True,
                                   "meanings": meaning_for(lang, hid)})

        if path == "/api/seed":
            hid = (query.get("id") or [""])[0]
            lang = (query.get("lang") or ["zh"])[0]
            ref_name = ("zh.toml" if lang == "zh"
                        else "%s.toml" % lang)
            ref_path = os.path.join(os.path.dirname(SRC), "src", "seed", ref_name)
            if not os.path.isfile(ref_path):
                return self.send_json({"detail": "没有干净文本源"}, 404)
            try:
                clean = tomllib.load(open(ref_path, "rb")).get(hid)
            except Exception as exc:
                return self.send_json({"detail": str(exc)}, 400)
            if clean is None:
                return self.send_json({"detail": "干净文本里没有这一条"}, 404)
            return self.send_json({"text": clean})

        if path == "/api/hash-rules":
            hid = (query.get("id") or [""])[0]
            return self.send_json({"id": hid, "rules": hash_rule(hid)})

        if path == "/api/entry-info":
            hid = (query.get("id") or [""])[0]
            lang = (query.get("lang") or ["zh"])[0]
            c = context_of(hid, lang)
            if c is None:
                return self.send_json({"detail": "no such entry"}, 404)
            zh = c.get("zh") or ""
            en = c.get("en") or ""
            spaces = [i for i, ch in enumerate(zh) if ch == " "]
            en_ph = placeholders_of(en)
            zh_ph = placeholders_of(zh)
            missing = [t for t in en_ph if t not in zh_ph]
            extra = [t for t in zh_ph if t not in en_ph]
            # 「干净文本」的空格数：优先读 references 里的干净文本源。
            clean_spaces = None
            ref_name = ("zh.toml" if lang == "zh"
                        else "%s.toml" % lang)
            ref_path = os.path.join(os.path.dirname(SRC), "src", "seed", ref_name)
            if os.path.isfile(ref_path):
                try:
                    with open(ref_path, "rb") as fh:
                        clean = tomllib.load(fh).get(hid)
                    if isinstance(clean, str):
                        clean_spaces = clean.count(" ")
                except Exception:
                    clean_spaces = None
            if clean_spaces is None:
                # 没有干净文本源时退回启发式：只算拉丁字符之间的空格。
                clean_spaces = 0
                for i, ch in enumerate(zh):
                    if ch != " ":
                        continue
                    l = zh[i - 1] if i else ""
                    r = zh[i + 1] if i + 1 < len(zh) else ""
                    if (l.isascii() and l.isalnum()) or (r.isascii() and r.isalnum()):
                        clean_spaces += 1
            en_c = placeholder_counts(en)
            zh_c = placeholder_counts(zh)
            counts = [{"token": t, "en": en_c[t], "zh": zh_c[t]}
                      for t in sorted(set(en_c) | set(zh_c))]
            return self.send_json({
                "placeholders": c.get("placeholders") or [],
                "counts": counts,
                "mismatch": [x["token"] for x in counts if x["en"] != x["zh"]],
                "tags": c.get("tags") or [],
                "missing": missing,
                "extra": extra,
                "used": zh_ph,
                "spaces": len(spaces),
                "clean_spaces": clean_spaces,
                "extra_spaces": len(spaces) - clean_spaces,
                "length": len(zh),
                "en_len": len(en),
            })

        if path == "/api/context":
            hid = (query.get("id") or [""])[0]
            lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
            ctx = context_of(hid, lang)
            if ctx is None:
                return self.send_error_json(404, "没有这个 id：%s" % hid)
            return self.send_json(ctx)

        if path == "/api/list":
            lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
            rows = load_all()
            return self.send_json([
                {"id": r["id"],
                 "en": (r.get(T.BASE_LANG, "") or "")[:60],
                 "zh": (r.get(lang, "") or "")[:60]}
                for r in rows])

        if path == "/api/ids":
            q = (query.get("q") or [""])[0].strip().lower()
            if q.startswith("0x"):
                q = q[2:]
            try:
                limit = int((query.get("limit") or ["20"])[0])
            except ValueError:
                limit = 20
            rows = load_all()
            hits = [r for r in rows if q in r["id"].lower()] if q else []
            return self.send_json({
                "ids": [{"id": r["id"],
                         "en": (r.get(T.BASE_LANG, "") or "")[:80],
                         "zh": (r.get((query.get("lang") or ["zh"])[0], "") or "")[:60]}
                        for r in hits[:limit]],
                "count": len(hits),
            })

        if path == "/api/find":
            hid = (query.get("id") or [""])[0]
            lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
            ids = filter_ids("all", lang)
            try:
                idx = ids.index(hid)
            except ValueError:
                idx = -1
            return self.send_json({"id": hid, "index": idx, "count": len(ids)})

        if path == "/api/count":
            # 只报条数与 id 顺序，不带正文：首屏拿到它就能把滚动条画对。
            kind = (query.get("filter") or ["all"])[0]
            lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
            ids = filter_ids(kind, lang)
            return self.send_json({"count": len(ids), "ids": ids,
                                   "filter": kind, "lang": lang})

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
            issues = filter_term_issues(terms_check.check_lang(lang, groups, en, doc))
            out = {}
            for x in issues:
                out.setdefault(x["id"], []).append(
                    "%s：应为「%s」" % (x["term"], x["expected"]))
            return self.send_json({"count": len(issues), "issues": out,
                                   "lang": lang})

        if path == "/api/entries":
            offset = int((query.get("offset") or ["0"])[0])
            limit = int((query.get("limit") or ["0"])[0])
            kind = (query.get("filter") or ["all"])[0]
            lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
            rows = load_all()
            if kind != "all":
                keep = set(filter_ids(kind, lang))
                rows = [r for r in rows if r["id"] in keep]
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
            kind = (query.get("filter") or ["all"])[0]
            lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
            keep = None if kind == "all" else set(filter_ids(kind, lang))
            for e in rows:
                if keep is not None and e["id"] not in keep:
                    continue
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

        if path == "/api/server/stop":
            try:
                port = int(body.get("port") or 0)
            except (TypeError, ValueError):
                return self.send_json({"ok": False, "error": "端口不对"})
            if port in (0, CURRENT_PORT):
                return self.send_json({"ok": False, "error": "不能停当前服务"})
            ok = P.editor_shutdown(port)
            return self.send_json({"ok": ok, "port": port})

        if path == "/api/start/pick":
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-STA", "-Command",
                     "Add-Type -AssemblyName System.Windows.Forms; "
                     "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                     "$d.Description = '选择 Port Royale 2 游戏目录'; "
                     "$d.ShowNewFolderButton = $false; "
                     "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
                     "{ Write-Output $d.SelectedPath }"],
                    capture_output=True, text=True, timeout=180,
                    creationflags=0x08000000)
                chosen = (out.stdout or "").strip().splitlines()
                chosen = chosen[-1].strip() if chosen else ""
            except Exception as exc:
                return self.send_json({"ok": False, "error": "打开目录选择框失败：%s" % exc})
            if not chosen:
                return self.send_json({"ok": False, "error": "已取消"})
            return self.send_json({"ok": True, "path": chosen})

        if path == "/api/start/use":
            sha = (body.get("sha") or "").strip()
            st = P.load_settings()
            entry = (st.get("dirs") or {}).get(sha)
            if not entry:
                return self.send_json({"ok": False, "error": "没有这个目录"})
            st["current"] = sha
            st["last_dir"] = entry.get("dir") or st.get("last_dir", "")
            P.save_settings(st)
            return self.send_json({"ok": True, **start_status()})

        if path == "/api/start/forget":
            sha = (body.get("sha") or "").strip()
            st = P.load_settings()
            dirs = st.get("dirs") or {}
            entry = dirs.pop(sha, None)
            if not entry:
                return self.send_json({"ok": False, "error": "没有这个目录"})
            if st.get("current") == sha:
                st["current"] = ""
                st["last_dir"] = ""
            P.save_settings(st)
            return self.send_json({"ok": True, "dirs": known_dirs()})

        if path == "/api/start/dir":
            d = (body.get("path") or "").strip()
            if not P.is_game_dir(d):
                return self.send_json({"ok": False,
                                       "error": "该目录里没有 %s" % P.GAME_EXE})
            st = P.load_settings()
            sha, _build = P.identify_dir(d)
            st.setdefault("dirs", {})[sha] = {
                "dir": d,
                "label": P.version_label(sha),
                "last_used": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            st["current"] = sha
            st["last_dir"] = d
            P.save_settings(st)
            return self.send_json({"ok": True, **start_status()})

        if path == "/api/start/build":
            langs = [x for x in (body.get("langs") or []) if x in P.available_langs()]
            if not langs:
                return self.send_json({"ok": False, "error": "没有勾选语言"})
            return self.send_json(start_run("build", lambda ev: P.run_build(langs, ev)))

        if path == "/api/start/deploy":
            langs = [x for x in (body.get("langs") or []) if x in P.available_langs()]
            d = start_dir()
            if not d or not P.is_game_dir(d):
                return self.send_json({"ok": False, "error": "还没有选择游戏目录"})
            return self.send_json(start_run(
                "deploy", lambda ev: P.run_deploy(d, langs or None, ev)))

        if path == "/api/start/lang":
            d = start_dir()
            if not d or not P.is_game_dir(d):
                return self.send_json({"ok": False, "error": "还没有选择游戏目录"})
            code = (body.get("lang") or "").strip()
            if code not in P.available_langs():
                return self.send_json({"ok": False, "error": "没有这个语言包：%s" % code})
            ok, code = P.set_game_language(d, code)
            return self.send_json({"ok": ok, "lang": code, **start_status()})

        if path == "/api/start/launch":
            d = start_dir()
            if not d or not P.is_game_dir(d):
                return self.send_json({"ok": False, "error": "还没有选择游戏目录"})
            lang = body.get("lang") or P.game_language(d) or None
            if body.get("vanilla"):
                ok, msg = P.launch_vanilla(d)
            else:
                ok, msg = P.launch_game(d, lang)
            return self.send_json({"ok": ok, "message": msg})


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

        if path == "/api/rule-hits":
            hid = (query.get("id") or [""])[0]
            lang = (query.get("lang") or ["zh"])[0]
            data = rule_hits(hid, lang)
            if data is None:
                return self.send_json({"detail": "没有初版或条目"}, 404)
            return self.send_json(data)


        if path == "/api/rule-trace":
            hid = (query.get("id") or [""])[0]
            lang = (query.get("lang") or ["zh"])[0]
            stages = rule_trace(hid, lang)
            if stages is None:
                return self.send_json({"detail": "没有初版或条目"}, 404)
            return self.send_json({"id": hid, "stages": stages})


        if path == "/api/placeholder-meaning":
            lang = (body.get("lang") or "zh").strip() or "zh"
            hid = (body.get("id") or "").strip().lower()
            token = (body.get("token") or "").strip()
            meaning = body.get("meaning", None)
            if meaning is not None:
                meaning = str(meaning)
            if not hid or not token:
                return self.send_json({"ok": False, "error": "缺少 id 或占位符"})
            save_meaning(lang, hid, token, meaning)
            return self.send_json({"ok": True,
                                   "meanings": meaning_for(lang, hid)})

        if path == "/api/seed":
            lang = body.get("lang", "zh")
            hid = body.get("id", "")
            text = body.get("text", "")
            seed = os.path.join(os.path.dirname(SRC), "src", "seed", "%s.toml" % lang)
            if not os.path.isfile(seed):
                return self.send_json({"detail": "没有初版文件"}, 404)
            cur = tomllib.load(open(seed, "rb"))
            if hid not in cur:
                return self.send_json({"detail": "初版里没有这一条"}, 404)
            if lang == "zh":
                text = ZH_GEN.strip_padding(text)
            order = list(cur)
            cur[hid] = text
            with io.open(seed, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("# 初版译文：可解锁修改；生成工作文本时从这里起步。\n")
                for rid in order:
                    fh.write('"%s" = "%s"\n' % (rid, toml_escape(cur[rid])))
            return self.send_json({"ok": True, "text": text})

        if path == "/api/hash-rule":
            hid = (body.get("id") or "").strip()
            term = (body.get("term") or "").strip()
            if not hid or not term:
                return self.send_json({"ok": False, "error": "缺少 id 或术语"})
            rules = save_hash_rule(hid, term, bool(body.get("skip")))
            return self.send_json({"ok": True, "rules": rules})


        if path == "/api/placeholder-meanings":
            lang = (body.get("lang") or "zh").strip() or "zh"
            hid = (body.get("id") or "").strip().lower()
            meanings = body.get("meanings") or {}
            if not hid or not isinstance(meanings, dict):
                return self.send_json({"ok": False, "error": "参数不对"})
            for tok, mean in meanings.items():
                save_meaning(lang, hid, str(tok), str(mean))
            return self.send_json({"ok": True,
                                   "meanings": meaning_for(lang, hid)})

        if path == "/api/patch":
            lang = body.get("lang", "")
            rows = rows_of(body)
            bad = []
            for row in rows:
                for tok, want, got in placeholder_problems(
                        row.get("id", ""), lang, row.get("text", "")):
                    bad.append("%s 的 %s（原文 %d 个，译文 %d 个）"
                               % (row.get("id", ""), tok, want, got))
            if bad:
                return self.send_error_json(
                    400, "占位符数量不符，未保存：\n" + "\n".join(bad[:10]))
            written, changed = patch_all(lang, rows)
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
    ap.add_argument("--open-page", default="/",
                    help="自动打开的页面，默认 /（安装页用 /start）")
    ap.add_argument("--restart", action="store_true",
                    help="若已有编辑器在跑，先停掉它再用新代码启动")
    a = ap.parse_args()

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
