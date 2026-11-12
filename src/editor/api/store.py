# -*- coding: utf-8 -*-
r"""数据层：读全部语言的缓存、整表写回、按 id 补丁写回。

从 `src\editor\server.py` 搬出来的一段纯逻辑 —— 它不碰 HTTP，也不碰
handler，所以可以单独测、单独改。路径不做第二套：`translate` 的 SRC\
仍是唯一的根，`set_data_root()` 换根之后这里只需要清缓存。
"""

import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))                 # 仓库的 src\
TOOLS = os.path.join(SRC, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from text import toml_io as TI  # noqa: E402
import translate as T           # noqa: E402

_ALL_CACHE = {"key": None, "rows": None}


def _all_key():
    parts = []
    for lang in T.all_langs():
        p = T.lang_path(lang)
        try:
            st = os.stat(p)
            parts.append((lang, st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append((lang, 0, 0))
    return tuple(parts)


def load_all():
    """读全部语言，按 id 合并成前端要的形态。

    走 translate.load_toml —— 它已经在做合并，且强制条目数与顺序与
    基准表（en.gog_1.1.2.3）一致。这条是硬要求：多一条会让后面全部错位。
    """
    key = _all_key()
    if _ALL_CACHE["key"] == key:
        return _ALL_CACHE["rows"]

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
    _ALL_CACHE.update(key=key, rows=rows)
    return rows


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

    texts = {}
    for rid in order:
        text = upd.get(rid)
        texts[rid] = cur.get(rid, "") if text is None else text
    TI.write_doc_atomic(path, texts, order, TI.head_lines(path))
    return len(order), len(upd)
