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
    punct = open_ + close + single + runs
    esc = lambda s: re.escape(s)
    rx_open = re.compile(r"(?<!\s)([%s])" % esc(open_))
    rx_after = re.compile(r"([%s])(?=[^%s\s])" % (esc(close + single + runs), esc(punct)))
    rx_space = re.compile(r" {2,}")

    def fmt(s):
        s = rx_open.sub(r" \1", s)
        s = rx_after.sub(r"\1 ", s)
        return rx_space.sub(" ", s).strip(" ")

    return fmt, punct


#: 汉字口径（CJK 统一表意文字 + 扩展 A）。分类、标点、排版都问这个正则。
CJK_RX = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

_ASCII_CACHE = {}

#: 半角记号内部允许出现的字符：字母数字与 `., : / \ - _ +`。
#: 中文句子里夹着的 `Port Royale 2`、`22.8MB`、`12:30`、`14x14aaFHk.res`
#: 都是「一个整体记号」，里面的半角标点不能当句子标点处理。
ASCII_TOKEN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                             "abcdefghijklmnopqrstuvwxyz"
                             "0123456789.,:/-\\_+")

#: 半角标点所处的语境。`CTX_CJK` 才是「中文句子里的标点」，其余都保留半角。
CTX_CJK = "cjk"        # 中文语境（「你好, 世界」里的逗号）
CTX_WORD = "word"      # 纯字母词：Port、Royale
CTX_NUM = "number"     # 纯数字与小数点：22.8
CTX_TIME = "time"      # 数字:数字，如 12:30
CTX_IDENT = "ident"    # 混合标识：1.0.0、14x14aaFHk.res、rc.1


def ascii_token(text, i):
    """切出 `text[i]` 所在的半角记号，返回 (start, end)。

    `i` 不在记号内部时返回 (i, i+1)。`ASCII_TOKEN_CHARS` 是唯一的判定口径：
    标点要不要全角化、断点能不能落在这里，都问它，避免各处各写一套。
    """
    if not (0 <= i < len(text)) or text[i] not in ASCII_TOKEN_CHARS:
        return i, min(len(text), i + 1)
    lo = i
    while lo > 0 and text[lo - 1] in ASCII_TOKEN_CHARS:
        lo -= 1
    hi = i + 1
    while hi < len(text) and text[hi] in ASCII_TOKEN_CHARS:
        hi += 1
    return lo, hi


def is_ascii_ch(ch):
    """这个字符是不是「可见的半角字符」（空格与空串不算）。

    `zh_space` 判断「断点是不是落在半角记号内部」也问这个函数：口径只有一份。
    """
    return bool(ch) and ch.isascii() and not ch.isspace()


def punct_context(text, i):
    """`text[i]` 这个半角标点处在什么语境里，供全角化判断。"""
    if not (0 <= i < len(text)) or text[i] not in ASCII_TOKEN_CHARS:
        return CTX_CJK
    lo, hi = ascii_token(text, i)
    tok = text[lo:hi]
    if len(tok) <= 1:
        return CTX_CJK
    if tok.replace(":", "").isdigit() and ":" in tok:
        return CTX_TIME
    if tok.replace(".", "").isdigit():
        return CTX_NUM
    if any(ch.isdigit() for ch in tok):
        return CTX_IDENT
    if tok.replace(".", "").replace("'", "").isalpha():
        return CTX_WORD
    return CTX_IDENT


def fix_ascii_punct(text, table, cjk_rx):
    """把 CJK 文本里的半角标点换成全角；不动纯 ASCII 的记号。

    豁免不再靠「左右相邻都是字母数字」这种临时判断，而是问 `punct_context()`：
    只要这个标点落在某个半角记号内部（词、数字、时间、标识），就原样保留。
    别的模块要判断「这是不是记号内部」时用同一个函数，口径只有一份。
    """
    if not cjk_rx.search(text):
        return text
    key = tuple(sorted(table))
    rx = _ASCII_CACHE.get(key)
    if rx is None:
        rx = re.compile("|".join(map(re.escape, key)))
        _ASCII_CACHE[key] = rx

    def repl(m):
        ch = m.group(0)
        if punct_context(text, m.start()) != CTX_CJK:
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
