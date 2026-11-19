# -*- coding: utf-8 -*-
"""法文规则：把标点前的那一格**变成不换行空格**；不补空格、不加标点、不改字形。

规则只做一件事：作者已经写了 `Vraiment ?`、`Or : 100` 的那一格，换成 U+00A0。
之所以要换（不是格式洁癖）：

* 普通空格（0x20）是引擎的断行点，`Vraiment ?` 在窄框里会把 `?` 单独带到下一行；
* NBSP 两个条件都满足 —— 法语字体里它与空格同一个字形、同宽（`ARIAL.TTF` 里
  0x20 与 0xA0 都指向 `space`，advance 均 569/2048 em；`ELGRECO_.TTF`、
  `Tiepolo_*` 同样有），而引擎只在 0x20 处断行。

这一格从哪来的：作者自己写的，不是规则加的
----------------------------------------
`src/translations/fr.toml`（标签外，实测）：

    ?  214 处，209 处已有一格，5 处紧贴
    !  215 处，212 处已有一格，3 处紧贴
    ;    1 处，0 处有前置空格（另一百多处都在 `[riddle:…;…]` 标注里，编译前已被展开掉）
    :  212 处，180 处已有一格，32 处紧贴（多数是 `%1:` 这种标签式写法）
    %  字面 23 处，标签内 75 处（`<c:0x…>`）；`%1` 这类占位符不算

所以「法语要在 ?!;: 前留一格」不是本项目的发明，是原文自己就写了 96% 的法语排版惯例
（Imprimerie nationale 的 espace insécable）；本规则只把那些格子改成不换行，
紧贴的 40 处一律保持原样——补格子是译文作者的事。

明确不做
--------
* 不补空格：紧贴的（`Roberts (1682?`、`%1:`、`Nous!`）保持紧贴；
* 不碰 `« »`：全书 0 处使用，等真出现再按内容层处理，规则不预置；
* 直撇 `'` 2400 处不换 `’`（大量是 `d'outils` 缩写，视觉差异极小）；
* 省略号 `...` 12 处不并成 `…`（不同字形，会改版面）；
* 不补词间空格、不做半角→全角：法语本来用空格分词。
"""

import re

from . import spec as S

LANG = "fr"

#: 不换行空格。只用这一个字符，不引入 U+202F（窄不换行空格）：法语字体里没有它。
NBSP = "\u00a0"

#: 这一格要保护的字符。`%` 不是标点，但排版处理相同。
SPACE_BEFORE = "?!;:%"

#: 只有「连续两个标点」才不留格子（`?!`、`…:`）。右括号、右引号后的句子标点
#: 该照常留一格（`… océans) : le Pacifique`），所以不列进这张表。
NO_SPACE_AFTER = "?!;:,\u2026"

#: 只有紧跟在「字母、数字、右引号、右括号」后面的标点才是句子标点。
#: 字符集自检串 `0x11f0398f` 是 ``°§$%&()=?\^';,:<|>@/*~[]²³€``，
#: 里面的 `% ? ; :` 前后都是符号，按这条判定一律不动——中文侧同类条目
#: （无汉字 / 模板符号）也已经被 `entries.UNTOUCHED` 排除在外。
WORDLIKE_HEAD = "\"'\u2019\u201d)]}\u2026\u00bb"


def _wordlike(ch):
    return ch.isalnum() or ch in WORDLIKE_HEAD or ch == "\x01"


#: 正文里不会出现这些字符；出现两个以上就判为符号表 / 字符集自检串，整条跳过。
#: `0x11f0398f` 是 ``°§$%&()=?\^';,:<|>@/*~[]²³€``，法语正文里 `` ` \ ^ | ~ [ ] `` 一个都没有。
ODD_RX = re.compile(r"[`\\^|~\[\]{}]")
ODD_MAX = 2

#: 与 base.VAR 同形，外加标签：`<gs:TEXTFLUSS_…>` 里的冒号不能被当成句子冒号。
TOKEN_RX = re.compile(r"(<[^<>]*>|@[A-Za-z]\$[^$]*\$|%[0-9A-Za-z]+)")


def _skip_colon(prev, nxt):
    """`:` 在某些记号里不是句子标点：时间 `12:30`、网址 `http://`、比例 `1:2`。"""
    if prev.isdigit() and nxt.isdigit():
        return True
    if nxt == "/":
        return True
    return False


def space_before_punct(seg):
    """把正文里**已经写着**的那一格换成 NBSP；不补新格子，多格并成一格。

    也就是只「保护」不「添加」：作者没写空格的地方（`%1:`、`Roberts (1682?`）
    保持原样——法语排版要求那一格，但补不补是译文作者的事，规则不替他改字面。
    """
    out = []
    for i, ch in enumerate(seg):
        if ch not in SPACE_BEFORE:
            out.append(ch)
            continue
        # 这一格前面是什么：先跳过已经写着的空格 / 上一轮写进去的 NBSP。
        j = len(out) - 1
        while j >= 0 and out[j] in (" ", NBSP):
            j -= 1
        prev = out[j] if j >= 0 else ""
        nxt = seg[i + 1] if i + 1 < len(seg) else ""
        if not _wordlike(prev):
            out.append(ch)           # 符号表里的标点：原样，不动
            continue
        if ch == ":" and _skip_colon(prev, nxt):
            out.append(ch)           # 时间 / 网址 / 比例里的冒号
            continue
        if len(out) - 1 == j:
            out.append(ch)           # 前面本来就没有格子：不补
            continue
        while len(out) > j + 1:
            out.pop()
        if prev not in NO_SPACE_AFTER:
            out.append(NBSP)
        out.append(ch)
    return "".join(out)


def space_guillemets(seg):
    """`«` 后、`»` 前各一格 NBSP（当前文本 0 处使用，规则先就位）。"""
    seg = re.sub(r"«[ \u00a0]*", "«" + NBSP, seg)
    return re.sub(r"[ \u00a0]*»", NBSP + "»", seg)


def _protect(text):
    """把标签/变量换成单字符占位符 `\\x01`，还原时按顺序换回。

    这样才能处理「变量、标签紧贴标点」的情况：`@T$DestTown$?`、`%1?`。按片段切开
    再做的话，占位符被切走，标点落在片段开头，前面就没有「词」可跟了。
    占位符算作一个词（`\\x01` 命中 `_wordlike` 的非字母分支需要单独列出）。
    """
    store = []

    def rep(m):
        store.append(m.group(0))
        return "\x01"

    return TOKEN_RX.sub(rep, text), store


def _restore(text, store):
    it = iter(store)
    return re.sub("\x01", lambda _m: next(it), text)


def normalize_punct(text, date_format=False):
    """标点规范化。`date_format` 只为接口对齐保留：本规则不碰变量，日期串无需区别对待。"""
    if len(ODD_RX.findall(text)) >= ODD_MAX:
        return text          # 符号表 / 自检串：整条不动
    body, store = _protect(text)
    body = space_before_punct(body)
    return _restore(body, store)


def normalize(text, date_format=False):
    return normalize_punct(text, date_format=date_format)


def spec():
    """法语声明：有标点规则，没有分词器，也不补词间空格。"""
    return S.LangSpec(
        code=LANG,
        punct=S.Punctuation(normalize_punct, {"lang": LANG, "nbsp": NBSP}),
        segmenter=S.NullSegmenter(),
        spacing=S.NoSpacing(),
    )
