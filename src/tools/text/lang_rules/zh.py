# -*- coding: utf-8 -*-
"""中文规则：标点 + 分词器 + 补空格策略（三段式接口见 lang_rules/spec.py）。"""

import re

from . import base
from . import spec as S
from text import zh_pipeline, zh_space

LANG = "zh"

PUNCT = {
    "open": "「『（［【〈〔",
    "close": "」』）］】〉〕",
    "single": "，。、；：！？…",
    "runs": "…—",
    "cjk": r"\u4e00-\u9fff\u3400-\u4dbf",
}

ASCII = {",": "，", ";": "；", ":": "：", "!": "！", "?": "？", "(": "（", ")": "）"}

FMT, PUNCT_CHARS = base.make_fmt(PUNCT)

CJK_RX = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def normalize(text, date_format=False):
    """标点 → 占位符 → <n>，中文的完整规范化（不含任何补空格）。

    `FMT` 那套「单标点后补空格、成对标点外侧补空格」是英文排版习惯，
    中文一律不用：标点自带停顿，「你好， 世界！」里的空格是多余的。
    占位符两侧也不再补空格（「1603爆发了瘟疫」「5名士兵」）。
    """
    text = base.fix_ascii_punct(text, ASCII, CJK_RX)
    return base.clean_n(text)


class ZhSegmenter(S.Segmenter):
    """中文分词器：只有 spaCy 一条路；没有就由 Spacing 退回机械切。

    `prepare()` 一次性把所有待切片段交出去，避免逐条起子进程。
    jieba 已于 2020 年停更，不作构建依赖（见 `zh_space` 模块头注释）。
    """

    name = "none"

    def prepare(self, texts):
        runs = zh_space.collect_runs(texts)
        self.runs = runs
        if not runs:
            return None
        lookup, name = zh_space.segment(runs)
        self.name = name
        if lookup is None:
            print("提示：没有 spaCy，中文补空格退回按字数机械切"
                  "（会切在词中间，见 zh_space.fallback_wrap）。"
                  "装法见 docs/构建与安装.md。")
        return lookup


class ZhCompactSpacing(S.Spacing):
    """中文紧凑排版：默认不留空格，只在超预算的片段里断行。

    旧版 `ZhGroupSpacing` 逢词就插空格，理由是引擎只按空格断行；
    但那样会得到「我刚听说， 一艘满载移民的 英格兰船沉了。」这种
    满屏空格的中文，且 1214 条的空格紧贴标点。这里改成：
    一段连续汉字不到预算就不动，超了才在词界断，标点不插空格。
    """

    mode = "compact"

    def __init__(self, max_chars=None):
        self.max_chars = max_chars or zh_space.MAX_CHARS
        self.lookup = None

    def setup(self, doc):
        return None

    def before(self, text):
        # 不再做「连词/人名/数字两侧补空格」那三步：对中文是纯噪声。
        return text, {"conj": 0, "name": 0}

    def prepare(self, texts, segmenter):
        self.lookup = segmenter.prepare(texts) if segmenter else None
        return self.lookup

    def apply(self, text, ctx):
        if ctx is None:
            return zh_space.fallback_wrap(text, step=self.max_chars)
        return zh_space.compact(text, ctx, max_chars=self.max_chars)

    def report(self):
        missing = getattr(self.lookup, "missing", None) or []
        if missing:
            print("提示：%d 个片段没进分词器，只能按单字成组（可能切在词中间）。"
                  % len(missing))


class ZhPerCharSpacing(S.Spacing):
    """逐字断行（试验）：两个汉字之间插一个半角空格，其余不动。

    动机是绕开「预算多少字」这个标定问题：每字后面都有断行点，引擎
    总能填满一行，不会因为超宽 token 被裁、也不会把词从中间切开。
    代价是空格本身有宽度，整段变成均匀疏排。

    用 `PR2_ZH_SPACING=perchar` 打开，默认仍是 `compact`。
    """

    mode = "perchar"

    def setup(self, doc):
        return None

    def before(self, text):
        return text, {"conj": 0, "name": 0}

    def prepare(self, texts, segmenter):
        return None

    def apply(self, text, ctx):
        return zh_space.perchar(text)


class ZhTwoSpaceSpacing(S.Spacing):
    """两种空白（试验）：汉字之间 0.05 em 的 U+0020，英文词内 0.25 em 的 U+00A0。

    配合 `src/tools/font/thin_space.py` 改过的中文包字体：U+0020 被压到
    0.05 em，只当折行标记，所以中文看起来是连续的；U+00A0 换成独立的
    0.25 em 空格字形，`Port Royale 2` 这种词的词距保持正常。

    `PR2_ZH_SPACING=twospace` 打开，字体侧还要 `PR2_ZH_THIN_SPACE=1`。
    """

    mode = "twospace"

    def setup(self, doc):
        return None

    def before(self, text):
        return text, {"conj": 0, "name": 0}

    def prepare(self, texts, segmenter):
        return None

    def apply(self, text, ctx):
        return zh_space.perchar_twospace(text)


class ZhGroupSpacing(S.Spacing):
    """中文补空格：先连词/人名/数字标签，再按词成组（每组 ≤ max_chars 字）。"""

    mode = "group"

    def __init__(self, max_chars=None):
        self.max_chars = max_chars or zh_space.MAX_CHARS
        self.names = None
        self.lookup = None

    # 标点之后、分词之前：中文特有的三步
    def setup(self, doc):
        self.names = zh_pipeline.make_name_tables(doc)

    def before(self, text):
        if self.names is None:
            self.names = {"given": set(), "surn": set(), "extras": [],
                          "towns": [], "all": frozenset()}
        return zh_pipeline.pre_space(text, self.names)

    def prepare(self, texts, segmenter):
        self.lookup = segmenter.prepare(texts) if segmenter else None
        return self.lookup

    def apply(self, text, ctx):
        if ctx is None:
            out = zh_space.fallback_wrap(text, step=self.max_chars)
        else:
            out = zh_space.spaced(text, ctx, max_chars=self.max_chars)
        return zh_pipeline.collapse_spaces(out)

    def report(self):
        missing = getattr(self.lookup, "missing", None) or []
        if missing:
            print("提示：%d 个片段没进分词器，只能按单字成组（可能切在词中间）。"
                  % len(missing))


def spec():
    """给 engine_text / apply_*_rules 用的语言声明。"""
    import os
    mode = os.environ.get("PR2_ZH_SPACING", "").strip().lower()
    if mode == "perchar":
        spacing = ZhPerCharSpacing()
    elif mode == "twospace":
        spacing = ZhTwoSpaceSpacing()
    else:
        spacing = ZhCompactSpacing()
    return S.LangSpec(
        code=LANG,
        punct=S.Punctuation(normalize, {"lang": LANG, **PUNCT}),
        segmenter=ZhSegmenter(),
        spacing=spacing,
    )
