# -*- coding: utf-8 -*-
"""toml_io.py —— 译文/构建产物共用的 TOML 读写小工具。

以前 `esc()`、`_order_of()`、「读文件 + 按行取 id 顺序」、「写两行 header + 逐条」
在 engine_text / apply_*_rules / normalize_text 里各写一遍，改格式要改三处。
这里收成一份：顺序以文件的 `"id" = ...` 行序为准（不依赖字典序）。
"""

import io
import os
import re
import tomllib

_ORDER_RX = re.compile(r'^"([^"]+)"\s*=')

#: 双引号字符串里必须转义的三个常见控制符
_CTRL = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def esc(text):
    r"""把一条译文安全地放进 TOML 的双引号字符串里。

    反斜杠必须**先**转，否则会把后面刚加的引号再转一遍；换行不转会把
    一条劈成两行，TOML 立刻解析失败；其余控制符写成 \uXXXX。
    """
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch in _CTRL:
            out.append(_CTRL[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04X" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


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


def write_doc_atomic(path, out, order=None, header=()):
    r"""同 write_doc，但先写 .tmp、解析自检、再原子替换。

    写的是译文（人改的唯一一层），一个转义 bug 会毁掉整份文件，而错误
    要到下次构建才暴露。所以：能重新解析、条数一致，才替换。
    """
    order = list(order or out)
    lines = [h.rstrip("\n") for h in header]
    lines += ['"%s" = "%s"' % (k, esc(out[k])) for k in order]
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    try:
        with open(tmp, "rb") as fh:
            back = tomllib.load(fh)
    except Exception as exc:
        os.remove(tmp)
        raise ValueError("写入后的文件无法解析，已放弃写入：%s" % exc)
    if len(back) != len(order):
        os.remove(tmp)
        raise ValueError("写入后条目数不符（%d vs %d），已放弃写入"
                         % (len(back), len(order)))
    os.replace(tmp, path)
    return len(lines)

