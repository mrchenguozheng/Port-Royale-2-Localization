# -*- coding: utf-8 -*-
"""中文规则。"""

import re

from . import base

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
    """标点 → 占位符 → <n>，中文的完整规范化。"""
    text = base.fix_ascii_punct(text, ASCII, CJK_RX)
    if date_format:
        return base.clean_n(FMT(text))
    return base.clean_n(base.fix_vars(FMT(text), PUNCT_CHARS, CJK_RX))
