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

CJK_RX = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def normalize(text, date_format=False):
    """标点 → 占位符 → <n>，中文的完整规范化。"""
    fmt, punct = base.make_fmt(PUNCT)
    text = base.fix_ascii_punct(text, ASCII, CJK_RX)
    if date_format:
        return base.clean_n(fmt(text))
    return base.clean_n(base.fix_vars(fmt(text), punct, CJK_RX))
