# -*- coding: utf-8 -*-
""""语言"域：语言列表、进度、新建语言、占位符含义与术语例外（glossary）。

这两份 glossary 文件按「数据根的同级」算路径，所以 set_root() 必须由
server.set_data_root() 调用；换根后要清缓存。
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

import translate as T           # noqa: E402
from api.store import load_all  # noqa: E402
from api.install import _font_module  # noqa: E402

RE_LANG_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")
MEANINGS = os.path.join(os.path.dirname(SRC), "glossary", "placeholder_meanings.toml")
_HASH_RULES = os.path.join(os.path.dirname(SRC), "glossary", "hash_rules.toml")
_MEAN_CACHE = {"key": None, "data": {}}
_HASH_CACHE = {"key": None, "data": {}}


def set_root(src):
    """换数据根：重算 glossary 两文件路径并清缓存。"""
    global MEANINGS, _HASH_RULES
    MEANINGS = os.path.join(os.path.dirname(os.path.abspath(src)),
                            "glossary", "placeholder_meanings.toml")
    _HASH_RULES = os.path.join(os.path.dirname(os.path.abspath(src)),
                               "glossary", "hash_rules.toml")
    _MEAN_CACHE.update(key=None, data={})
    _HASH_CACHE.update(key=None, data={})


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


def load_hash_rules():
    """按 hash 的例外规则，目前只有 skip_terms（不检查这些术语）。"""
    try:
        key = os.path.getmtime(_HASH_RULES)
    except OSError:
        return {}
    if _HASH_CACHE["key"] != key:
        try:
            with open(_HASH_RULES, "rb") as fh:
                data = tomllib.load(fh)
        except Exception:
            data = {}
        _HASH_CACHE.update(key=key, data=data)
    return _HASH_CACHE["data"]


def hash_rule(hid):
    return load_hash_rules().get(hid.lower(), {})


def save_hash_rule(hid, term, skip):
    data = {}
    if os.path.isfile(_HASH_RULES):
        try:
            data = tomllib.load(open(_HASH_RULES, "rb"))
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
    with io_open(_HASH_RULES, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return data.get(key, {})


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

    result = {"code": code, "from": src, "aligned": aligned,
              "dropped": dropped, "filled": filled}
    try:
        result["presets"] = _font_module().add_language_presets(code, src)
    except Exception as exc:
        result["presets_error"] = str(exc)
    return result


def get_langs(req):
    query = req.query
    body = req.body
    return req.send_json({"editable": T.target_langs(),
                           "all": T.all_langs(),
                           "base": T.BASE_LANG})


def get_lang_summary(req):
    query = req.query
    body = req.body
    lang = (query.get("lang") or ["zh"])[0]
    rows = load_all()
    base = getattr(T, "BASE_LANG", "en.gog_1.1.2.3")
    total = len(rows)
    todo = sum(1 for r in rows
               if not r.get(lang) or r.get(lang) == r.get(base))
    return req.send_json({"lang": lang, "total": total,
                           "todo": todo, "done": total - todo})


def get_lang_exists(req):
    query = req.query
    body = req.body
    # 输入框一边打字一边问：这个名字能不能用、是不是已经有一份了。
    return req.send_json(lang_status((query.get("code") or [""])[0]))


def get_placeholder_meanings(req):
    query = req.query
    body = req.body
    hid = (query.get("id") or [""])[0]
    lang = (query.get("lang") or ["zh"])[0]
    return req.send_json({"id": hid, "lang": lang,
                           "meanings": meaning_for(lang, hid)})


def get_hash_rules(req):
    query = req.query
    body = req.body
    hid = (query.get("id") or [""])[0]
    return req.send_json({"id": hid, "rules": hash_rule(hid)})


def post_placeholder_meaning(req):
    query = req.query
    body = req.body
    lang = (body.get("lang") or "zh").strip() or "zh"
    hid = (body.get("id") or "").strip().lower()
    token = (body.get("token") or "").strip()
    meaning = body.get("meaning", None)
    if meaning is not None:
        meaning = str(meaning)
    if not hid or not token:
        return req.send_json({"ok": False, "error": "缺少 id 或占位符"})
    save_meaning(lang, hid, token, meaning)
    return req.send_json({"ok": True,
                           "meanings": meaning_for(lang, hid)})


def post_hash_rule(req):
    query = req.query
    body = req.body
    hid = (body.get("id") or "").strip()
    term = (body.get("term") or "").strip()
    if not hid or not term:
        return req.send_json({"ok": False, "error": "缺少 id 或术语"})
    rules = save_hash_rule(hid, term, bool(body.get("skip")))
    return req.send_json({"ok": True, "rules": rules})


def post_placeholder_meanings(req):
    query = req.query
    body = req.body
    lang = (body.get("lang") or "zh").strip() or "zh"
    hid = (body.get("id") or "").strip().lower()
    meanings = body.get("meanings") or {}
    if not hid or not isinstance(meanings, dict):
        return req.send_json({"ok": False, "error": "参数不对"})
    for tok, mean in meanings.items():
        save_meaning(lang, hid, str(tok), str(mean))
    return req.send_json({"ok": True,
                           "meanings": meaning_for(lang, hid)})


def post_newlang(req):
    query = req.query
    body = req.body
    made = new_lang(body.get("code", ""), body.get("from", ""))
    return req.send_json({"ok": True, **made})



ROUTES = {
    ("GET", "/api/langs"): get_langs,
    ("GET", "/api/lang-summary"): get_lang_summary,
    ("GET", "/api/lang-exists"): get_lang_exists,
    ("GET", "/api/placeholder-meanings"): get_placeholder_meanings,
    ("GET", "/api/hash-rules"): get_hash_rules,
    ("POST", "/api/placeholder-meaning"): post_placeholder_meaning,
    ("POST", "/api/hash-rule"): post_hash_rule,
    ("POST", "/api/placeholder-meanings"): post_placeholder_meanings,
    ("POST", "/api/newlang"): post_newlang,
}
