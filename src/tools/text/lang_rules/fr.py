# -*- coding: utf-8 -*-
"""法文规则：标点前的**不换行空格**；分词与补空格不需要（`Spacing` 显式 NoSpacing）。

为什么这一格必须是不换行空格（U+00A0）
--------------------------------------
法语要求在 `? ! ; :` 前、`%` 前、`« »` 内侧各留一格。普通空格（0x20）是引擎的
断行点，补上去会让「Vraiment ?」的「?」单独落到下一行。NBSP 两个条件都满足：

* 字体有字形，且与空格同一个字形、同宽 —— `ARIAL.TTF` 里 0x20 与 0xA0 都指向
  `space`，advance 均为 569/2048 em（`ELGRECO_.TTF`、`Tiepolo_*` 同样有）；
* 引擎只在 0x20 处断行，NBSP 不算空格，于是这一格既不丢、也不会断。

实测口径（改前 `src/translations/fr.toml`）
------------------------------------------
    ?  214 处，209 处已有一格            （5 处缺）
    !  215 处，212 处已有一格            （3 处缺）
    ;  161 处，0 处有前置空格            （全部缺）
    :  850 处，180 处有前置空格          （670 处缺；无 `数字:数字` 形态，标签内 390 个冒号在 <…> 里）
    %  866 处，558 处有一格              （308 处缺）

明确不做的几项（都是实测后决定，不是遗漏）
------------------------------------------
* 直撇 `'` 2400 处 vs 弯撇 `’` 2 处：统一会把 2400 处全部改掉，且大量是 `d'outils`
  这类缩写，视觉差异极小，收益不对等 → 不改；
* 省略号 `...` 12 处 vs `…` 2 处：两者都有字形但是不同字形（`…` 是 2048 宽的省略号），
  统一会改版面、也会抹掉作者的写法 → 不改；
* `« »` 全书 0 处使用：规则仍然就位（出现就会被规范），当前是空转；
* 不补词间空格、不做半角→全角：法语本来用空格分词，中文那套按词成组不适用。
"""

import re

from . import spec as S

LANG = "fr"

#: 不换行空格。只用这一个字符，不引入 U+202F（窄不换行空格）：法语字体里没有它。
NBSP = "\u00a0"

#: 法语前面要留一格的字符。`%` 不是标点，但按单位处理，规则相同。
SPACE_BEFORE = "?!;:%"

#: 这些字符后面不该再补一格：连着写两个标点时（`?!`、`…:`）只保留原样，
#: 否则会出现「Attention ! : x」这种双标点被空格劈开的形状。
NO_SPACE_AFTER = "?!;:,.\u2026»)]"

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
    """把正文片段里 `?!;:%` 前的一格统一成 NBSP（缺则补，乱则并）。"""
    out = []
    for i, ch in enumerate(seg):
        if ch not in SPACE_BEFORE:
            out.append(ch)
            continue
        # 看看这一格前面是什么：先跳过已经写着的空格 / 上一轮写进去的 NBSP。
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
    body = space_guillemets(space_before_punct(body))
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
