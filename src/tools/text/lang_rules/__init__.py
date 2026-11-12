# -*- coding: utf-8 -*-
"""按语言分文件存放的规则，以及三段式接口的取用入口。

每种语言一个模块，提供：

    LANG, PUNCT, ASCII, CJK_RX, normalize(text, date_format=False)
    spec() -> LangSpec            # 标点 / 分词器 / 补空格 三件套

`spec()` 返回的对象见 spec.py；`engine_text.build()` 只认 spec，不认语言。
`normalize_text.py` 仍然只调 `normalize()`（它只改标点，不补排版空格）。

加一种语言：在本目录放 <代码>.py，实现上面的契约，然后在 REGISTRY 登记。
新语言如果词间本来就有空格，`spec()` 里写 `spacing=spec.NoSpacing()` 即可。

明确不做从右往左书写的语言：没有游戏源代码，绘制方向改不了。
"""

import importlib

REGISTRY = ("zh", "ja")


def get(lang):
    if lang not in REGISTRY:
        return None
    return importlib.import_module("lang_rules." + lang)


def names():
    return list(REGISTRY)


def get_spec(lang):
    """取某语言的 LangSpec；没有声明就返回「原样透传」的 spec。"""
    from . import spec as S
    mod = get(lang)
    maker = getattr(mod, "spec", None) if mod else None
    if maker is None:
        return S.LangSpec(code=lang or "*", punct=None,
                          segmenter=S.NullSegmenter(), spacing=S.NoSpacing())
    return maker()
