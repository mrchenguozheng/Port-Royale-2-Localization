# -*- coding: utf-8 -*-
"""按语言分文件存放的规范化规则。

加一种语言：在本目录放 <代码>.py，提供
    LANG, PUNCT, ASCII, CJK_RX, normalize(text, **opts)
然后在下方 REGISTRY 里登记即可。normalize_text.py 只做 CLI 和文件读写。
"""

import importlib

REGISTRY = ("zh", "ja")


def get(lang):
    if lang not in REGISTRY:
        return None
    return importlib.import_module("lang_rules." + lang)


def names():
    return list(REGISTRY)
