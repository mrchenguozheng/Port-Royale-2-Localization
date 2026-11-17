# -*- coding: utf-8 -*-
""""翻译"域：条目读取、校验、语境、规则轨迹，以及保存/补丁写回。

路由处理函数都是 req -> handler 返回值；HTTP 编解码在 server.py。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(SRC, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import re
import tomllib

from shared.core.validate import check_text  # noqa: E402
import translate as T           # noqa: E402
import terms_check              # noqa: E402
from pack import compile_pack as C  # noqa: E402
from text import lang_rules     # noqa: E402
from text import toml_io as TI  # noqa: E402
from text import zh_pipeline as ZH_GEN  # noqa: E402
from api.store import load_all, rows_of, patch_all  # noqa: E402
from api import langs as LG     # noqa: E402

ORDER_FILE = os.path.join(os.path.dirname(HERE), "data", "table-order.txt")
_ORDER = None
_ATTN_CACHE = {}
TAG_MEAN = [
    ("<n:", "Paragraph spacing"), ("<n>", "Line break"), ("<c>", "Color: start"),
    ("<o:", "Color value"), ("<r>", "Red text"), ("<t>", "Tab"),
    ("<ts:", "Tab stop"), ("<g:", "Icon/graphic"),
    ("<gs:", "Graphic script marker (keep as is)"), ("<f:", "Font"),
]
ARG_RX = re.compile(r"@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z]")


def check_one(entry, lang, text):
    """校验一条译文，返回 [{level, text}]。

    规则与消息都在 shared\\core\\validate.py —— 编译脚本和这个编辑器共用同一份。
    以前这里借 compile_pack 的实现，再自己补一段标签比对，三处对 %02 补零与
    紧邻占位符的处理并不一致。

    level 分 error / warn：error 大概率出乱码，warn 需要人工确认。
    """
    en = entry.get(T.BASE_LANG, "") or ""
    return check_text(text, en, lang="zh")


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
        groups, ignore, verse = terms_check.load_terms()
        if groups:
            en = {r["id"]: r.get(T.BASE_LANG, "") for r in rows}
            skip = set(ignore) | terms_check.verse_ids(verse, en)
            doc = {r["id"]: r.get(lang, "") for r in rows if r["id"] not in skip}
            for x in terms_check.check_lang(lang, groups, en, doc)["missing"]:
                if x["id"] not in bad:
                    bad.append(x["id"])
    except Exception:
        pass
    _ATTN_CACHE[key] = bad
    return bad


def filter_ids(kind, lang):
    rows = load_all()
    if kind == "attention":
        keep = set(attention_ids(lang))
        return [r["id"] for r in rows if r["id"] in keep]
    return [r["id"] for r in rows]


def filter_term_issues(issues):
    out = []
    for x in issues:
        skip = LG.hash_rule(x.get("id", "")).get("skip_terms", [])
        if x.get("term") in skip:
            continue
        out.append(x)
    return out


def table_order():
    global _ORDER
    if _ORDER is None:
        try:
            with open(ORDER_FILE, encoding="utf-8") as fh:
                _ORDER = [l.strip() for l in fh if l.strip()]
        except OSError:
            _ORDER = []
    return _ORDER


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
    """按出现顺序列出占位符（去重）。

    这里用的是 ARG_RX 而不是 shared\\core\\validate.tokens：面板要把
    「同一个占位符出现几次」也显示出来，tokens 是集合、会丢掉次数；
    而且它会额外认 %s / %d 这类 printf 式写法 —— tokens 只认 %N，
    那种写法在游戏里是字面量，不算占位符。
    """
    out = []
    for m in ARG_RX.finditer(text):
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
        role_hint = {"%1": "Rank/Title", "%2": "Given name", "%3": "Surname"}
    elif es.startswith("%1 %2 "):
        role_hint = {"%1": "Rank/Title", "%2": "Full name"}
    elif re.search(r"\b(Governor|Captain|Viceroy|King|Queen|Prince|Princess|"
                   r"Lord|Sir|Mr|Mrs|Ms|Dr|Admiral|General|Colonel|Major|"
                   r"Lieutenant)\s+%1 %2", en):
        role_hint = {"%1": "Given name", "%2": "Surname"}

    overrides = LG.meaning_for(lang, hid)
    ph = []
    for tok in placeholders_of(en):
        # 默认不给标签：占位符本身就是英文变量名，需要时在编辑器里手动补含义。
        ph.append({"token": tok, "meaning": overrides.get(tok, "")})

    tags = []
    for tok, mean in TAG_MEAN:
        if tok in en and mean not in tags:
            tags.append(mean)

    cat = "通用文本"
    try:
        ko = C.KEEP_ORIGINAL
    except Exception:
        ko = {}
    group = ko.get(hid) or ko.get(hid.lower())
    if group:
        cat = "原样保留：%s" % group
        reasons.append("在 KEEP_ORIGINAL 清单里，编译时强制输出英文原文")
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


def rule_trace(hid, lang):
    """逐阶段还原这条译文经过的格式化规则（译文层 → 补空格前）。

    译文层（src/translations/）是唯一手改层；补空格等排版是**构建期**由
    src/tools/text/engine_text.py 做的，产物在 build/preview/engine_text/，编辑器里
    不重复算一遍（那要起一次分词器，界面会卡）。
    """
    rows = load_all()
    doc = {r["id"]: (r.get(lang) or "") for r in rows}
    cur = doc.get(hid)
    if cur is None:
        return None
    rules = lang_rules.get(lang)
    stages = [{"key": "text", "label": "译文（手改层）", "text": cur}]

    if lang == "zh":
        norm = rules.normalize(cur)
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
        stages.append({"key": "names", "label": "人名/城镇名空格（补空格前）",
                       "text": "".join(res)})
    else:
        stages.append({"key": "punct", "label": "规范化",
                       "text": rules.normalize(cur)})
    return stages


def get_context_batch(req):
    query = req.query
    body = req.body
    ids = [x for x in (query.get("ids") or [""])[0].split(",") if x]
    lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
    out = {}
    for hid in ids[:200]:
        c = context_of(hid, lang)
        if c:
            out[hid] = c
    return req.send_json(out)


def get_rule_trace(req):
    query = req.query
    body = req.body
    hid = (query.get("id") or [""])[0]
    lang = (query.get("lang") or ["zh"])[0]
    stages = rule_trace(hid, lang)
    if stages is None:
        return req.send_json({"detail": "没有译文或条目"}, 404)
    return req.send_json({"id": hid, "stages": stages})


def get_translation(req):
    query = req.query
    body = req.body
    hid = (query.get("id") or [""])[0]
    lang = (query.get("lang") or ["zh"])[0]
    doc = {r["id"]: (r.get(lang) or "") for r in load_all()}
    if hid not in doc:
        return req.send_json({"detail": "译文里没有这一条"}, 404)
    return req.send_json({"text": doc[hid]})


def get_entry_info(req):
    query = req.query
    body = req.body
    hid = (query.get("id") or [""])[0]
    lang = (query.get("lang") or ["zh"])[0]
    c = context_of(hid, lang)
    if c is None:
        return req.send_json({"detail": "no such entry"}, 404)
    zh = c.get("zh") or ""
    en = c.get("en") or ""
    spaces = [i for i, ch in enumerate(zh) if ch == " "]
    en_ph = placeholders_of(en)
    zh_ph = placeholders_of(zh)
    missing = [t for t in en_ph if t not in zh_ph]
    extra = [t for t in zh_ph if t not in en_ph]
    # 译文层只有一份，而且就是「干净文本」：这里的空格全部是译者自己
    # 写的。引擎补的空格是构建期产物（build/preview/engine_text/），不进这一层，
    # 所以「额外补的空格」在这个接口里恒为 0。
    clean_spaces = len(spaces)
    en_c = placeholder_counts(en)
    zh_c = placeholder_counts(zh)
    counts = [{"token": t, "en": en_c[t], "zh": zh_c[t]}
              for t in sorted(set(en_c) | set(zh_c))]
    return req.send_json({
        "placeholders": c.get("placeholders") or [],
        "counts": counts,
        "mismatch": [x["token"] for x in counts if x["en"] != x["zh"]],
        "tags": c.get("tags") or [],
        "missing": missing,
        "extra": extra,
        "used": zh_ph,
        "spaces": len(spaces),
        "clean_spaces": clean_spaces,
        "extra_spaces": 0,
        "length": len(zh),
        "en_len": len(en),
    })


def get_list(req):
    query = req.query
    body = req.body
    lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
    rows = load_all()
    return req.send_json([
        {"id": r["id"],
         "en": (r.get(T.BASE_LANG, "") or "")[:60],
         "zh": (r.get(lang, "") or "")[:60]}
        for r in rows])


def get_ids(req):
    query = req.query
    body = req.body
    q = (query.get("q") or [""])[0].strip().lower()
    if q.startswith("0x"):
        q = q[2:]
    try:
        limit = int((query.get("limit") or ["20"])[0])
    except ValueError:
        limit = 20
    rows = load_all()
    hits = [r for r in rows if q in r["id"].lower()] if q else []
    return req.send_json({
        "ids": [{"id": r["id"],
                 "en": (r.get(T.BASE_LANG, "") or "")[:80],
                 "zh": (r.get((query.get("lang") or ["zh"])[0], "") or "")[:60]}
                for r in hits[:limit]],
        "count": len(hits),
    })


def get_find(req):
    query = req.query
    body = req.body
    hid = (query.get("id") or [""])[0]
    lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
    ids = filter_ids("all", lang)
    try:
        idx = ids.index(hid)
    except ValueError:
        idx = -1
    return req.send_json({"id": hid, "index": idx, "count": len(ids)})


def get_count(req):
    query = req.query
    body = req.body
    # 只报条数与 id 顺序，不带正文：首屏拿到它就能把滚动条画对。
    kind = (query.get("filter") or ["all"])[0]
    lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
    ids = filter_ids(kind, lang)
    return req.send_json({"count": len(ids), "ids": ids,
                           "filter": kind, "lang": lang})


def get_terms(req):
    query = req.query
    body = req.body
    # 术语一致性：术语表（glossary\terms.toml）当规则用。
    # 返回 {id: ["术语：Frigate 应为「巡防舰」", …]}，前端标在行上。
    lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
    groups, ignore, verse = terms_check.load_terms()
    if not groups:
        return req.send_json({"count": 0, "issues": {},
                               "note": "没有术语表"})
    rows = load_all()
    en = {r["id"]: r.get(T.BASE_LANG, "") for r in rows}
    skip = set(ignore) | terms_check.verse_ids(verse, en)
    doc = {r["id"]: r.get(lang, "") for r in rows if r["id"] not in skip}
    issues = filter_term_issues(terms_check.check_lang(lang, groups, en, doc)["missing"])
    out = {}
    for x in issues:
        out.setdefault(x["id"], []).append(
            "%s：应为「%s」" % (x["term"], x["expected"]))
    return req.send_json({"count": len(issues), "issues": out,
                           "lang": lang})


def get_entries(req):
    query = req.query
    body = req.body
    offset = int((query.get("offset") or ["0"])[0])
    limit = int((query.get("limit") or ["0"])[0])
    kind = (query.get("filter") or ["all"])[0]
    lang = (query.get("lang") or [""])[0] or (T.target_langs() or ["zh"])[0]
    rows = load_all()
    if kind != "all":
        keep = set(filter_ids(kind, lang))
        rows = [r for r in rows if r["id"] in keep]
    if limit <= 0:
        return req.send_json(rows)
    if offset < 0:
        offset = 0
    return req.send_json(rows[offset:offset + limit])


def get_search(req):
    query = req.query
    body = req.body
    # 搜索必须走服务端：正文本来就没全量在前端，前端过滤等于
    # 又要先把 320 KB 全拉下来，分段加载就白做了。
    q = (query.get("q") or [""])[0].strip().lower()
    if not q:
        return req.send_json([])
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
    return req.send_json(out)


def post_check(req):
    query = req.query
    body = req.body
    text = body.get("text", "")
    lang = body.get("lang", "zh")
    hid = body.get("id", "")
    row = next((r for r in load_all() if r["id"] == hid), None)
    return req.send_json([] if row is None else check_one(row, lang, text))


def post_translation(req):
    query = req.query
    body = req.body
    lang = body.get("lang", "zh")
    hid = body.get("id", "")
    text = body.get("text", "")
    path = T.lang_path(lang)
    if not os.path.isfile(path):
        return req.send_json({"detail": "没有译文文件"}, 404)
    cur = tomllib.load(open(path, "rb"))
    if hid not in cur:
        return req.send_json({"detail": "译文里没有这一条"}, 404)
    order = list(cur)
    cur[hid] = text
    TI.write_doc_atomic(path, cur, order, TI.head_lines(path))
    return req.send_json({"ok": True, "text": text})


def post_patch(req):
    query = req.query
    body = req.body
    lang = body.get("lang", "")
    rows = rows_of(body)
    bad = []
    for row in rows:
        for tok, want, got in placeholder_problems(
                row.get("id", ""), lang, row.get("text", "")):
            bad.append("%s 的 %s（原文 %d 个，译文 %d 个）"
                       % (row.get("id", ""), tok, want, got))
    if bad:
        return req.send_error_json(
            400, "占位符数量不符，未保存：\n" + "\n".join(bad[:10]))
    written, changed = patch_all(lang, rows)
    return req.send_json({"ok": True, "written": written,
                           "changed": changed})



ROUTES = {
    ("GET", "/api/context-batch"): get_context_batch,
    ("GET", "/api/rule-trace"): get_rule_trace,
    ("GET", "/api/translation"): get_translation,
    ("GET", "/api/entry-info"): get_entry_info,
    ("GET", "/api/list"): get_list,
    ("GET", "/api/ids"): get_ids,
    ("GET", "/api/find"): get_find,
    ("GET", "/api/count"): get_count,
    ("GET", "/api/terms"): get_terms,
    ("GET", "/api/entries"): get_entries,
    ("GET", "/api/search"): get_search,
    ("POST", "/api/check"): post_check,
    ("POST", "/api/translation"): post_translation,
    ("POST", "/api/patch"): post_patch,
}
