# -*- coding: utf-8 -*-
"""与语言无关的标点/占位符处理引擎。

各语言的差异写在 lang_rules/<代码>.py 里；这里只放三种语言共用的机制：
全角化的判定、标点后补空格、占位符两侧补空格、<n> 去空格。
"""

import re

VAR = re.compile(r"@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z]")

#: 日期格式串：占位符两侧不加空格，否则会渲染成「1600 年 4月 1 日」。
DATE_FORMAT_IDS = {"0x1ac38a65", "0x34d0f9eb", "0x22caa09f", "0x1813d72e"}


def make_fmt(sets):
    """按该语言的标点表生成 fmt(text)：单标点后补空格、成对标点外侧补。"""
    open_, close, single, runs = (sets["open"], sets["close"],
                                  sets["single"], sets["runs"])
    punct = open_ + close + single

    def fmt(s):
        out, i, n = [], 0, len(s)
        while i < n:
            c = s[i]
            if c in runs:
                j = i
                while j + 1 < n and s[j + 1] == c:
                    j += 1
                out.append(s[i:j + 1])
                nxt = s[j + 1] if j + 1 < n else ""
                if nxt and nxt not in punct:
                    out.append(" ")
                i = j + 1
                continue
            if c in open_:
                out.append(" ")
                out.append(c)
            elif c in close:
                out.append(c)
                nxt = s[i + 1] if i + 1 < n else ""
                if nxt and nxt not in punct:
                    out.append(" ")
            elif c in single:
                out.append(c)
                nxt = s[i + 1] if i + 1 < n else ""
                if nxt and nxt not in punct:
                    out.append(" ")
            else:
                out.append(c)
            i += 1
        s = "".join(out)
        return re.sub(r" {2,}", " ", s).strip(" ")

    return fmt, punct


_ASCII_CACHE = {}


def fix_ascii_punct(text, table, cjk_rx):
    """把 CJK 文本里的半角标点换成全角；不动纯 ASCII 的格式串。"""
    if not cjk_rx.search(text):
        return text
    key = tuple(sorted(table))
    rx = _ASCII_CACHE.get(key)
    if rx is None:
        rx = re.compile("|".join(map(re.escape, key)))
        _ASCII_CACHE[key] = rx

    def repl(m):
        ch = m.group(0)
        i = m.start()
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch == ":" and prev.isdigit() and nxt.isdigit():
            return ch
        if prev.isascii() and prev.isalnum() and nxt.isascii() and nxt.isalnum():
            return ch
        return table[ch]

    return rx.sub(repl, text)


def fix_vars(text, punct, cjk_rx, var=VAR):
    """占位符两侧补空格。

    规则（两种语言一致）：
      · 前面是正文或全角标点 → 前面补一个空格；
      · 后面是正文才补空格，**后面是标点不补**（「%1。」而不是「%1 。」）。
    """
    def is_text(ch):
        # ・(U+30FB) 与 ー(U+30FC) 虽落在假名区，但不是「词」：不能把
        # 「%2・%3」「迭戈・莫扎雷拉」拆开。
        return bool(ch) and ch not in "・ー" and bool(cjk_rx.match(ch))

    def need_prev(ch):
        return bool(ch) and (is_text(ch) or ch in punct)

    out, pos = [], 0
    for m in var.finditer(text):
        out.append(text[pos:m.start()])
        if out and out[-1] and out[-1][-1] != " " and need_prev(out[-1][-1]):
            out.append(" ")
        out.append(m.group(0))
        nxt = text[m.end()] if m.end() < len(text) else ""
        if nxt and nxt != " " and is_text(nxt):
            out.append(" ")
        pos = m.end()
    out.append(text[pos:])
    return re.sub(r" {2,}", " ", "".join(out))


def clean_n(text):
    text = re.sub(r" +(?=<n)", "", text)
    return re.sub(r"(<n(?::\d+)?>) +", r"\1", text)
