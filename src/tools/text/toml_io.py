# -*- coding: utf-8 -*-
"""toml_io.py —— 译文/构建产物共用的 TOML 读写小工具。

以前 `esc()`、`_order_of()`、「读文件 + 按行取 id 顺序」、「写两行 header + 逐条」
在 engine_text / apply_*_rules / normalize_text 里各写一遍，改格式要改三处。
这里收成一份：顺序以文件的 `"id" = ...` 行序为准（不依赖字典序）。
"""

import io
import re
import tomllib

_ORDER_RX = re.compile(r'^"([^"]+)"\s*=')


def esc(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def order_of(path):
    """按 `"id" = ...` 的行序取 id 列表（注释与空行忽略）。"""
    return [m.group(1) for m in
            (_ORDER_RX.match(line) for line in io.open(path, encoding="utf-8"))
            if m]


def read_doc(path):
    """返回 (doc, order)。"""
    with open(path, "rb") as fh:
        return tomllib.load(fh), order_of(path)


def read_doc_loose(path):
    """读构建产物：文件不存在或格式坏掉时返回空字典。"""
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, ValueError):
        return {}


def head_lines(path):
    """取文件开头的连续 `#` 注释行（写回时原样保留）。"""
    out = []
    try:
        for line in io.open(path, encoding="utf-8"):
            if not line.startswith("#"):
                break
            out.append(line.rstrip("\n"))
    except OSError:
        pass
    return out


def write_doc(path, out, order=None, header=()):
    """写 `"id" = "文本"`，header 是注释行列表（不带换行）。"""
    order = list(order or out)
    lines = [h.rstrip("\n") for h in header]
    lines += ['"%s" = "%s"' % (k, esc(out[k])) for k in order]
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    return path
