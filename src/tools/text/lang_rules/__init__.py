# -*- coding: utf-8 -*-
"""按语言分文件存放的规则，以及三段式接口的取用入口。

每种语言一个模块，提供：

    LANG, PUNCT, ASCII, CJK_RX, normalize(text, date_format=False)
    spec() -> LangSpec            # 标点 / 分词器 / 补空格 三件套
    SCRIPT                        # 目标文字正则（非拉丁字母语言才需要）

`spec()` 返回的对象见 spec.py；`engine_text.build()` 只认 spec，不认语言。
`normalize_text.py` 仍然只调 `normalize()`（它只改标点，不补排版空格）。
`SCRIPT` 不参与排版，只给 `translate.py status` 判「这条译文译没译」：
fr/de/es 用拉丁字母，没有这份声明，进度按「与英文原文不同」计。

加一种语言：在本目录放 <代码>.py，实现上面的契约，然后在 REGISTRY 登记。
新语言如果词间本来就有空格，`spec()` 里写 `spacing=spec.NoSpacing()` 即可。
**不需要加工的语言也要建模块并登记**：模块里 `spec()` 返回透传、用注释与 `SKIP`
写清「为什么不处理」，这样「不处理」是一份可审的声明，而不是一个没有文件的空白。

明确不做从右往左书写的语言：没有游戏源代码，绘制方向改不了。
"""

import importlib

#: 已登记的语言。fr 有真规则（标点前置不换行空格）；de / es / pl / ru / ko 是显式
#: 透传（各自模块里写了理由）。en 是原文语，不在这里。
REGISTRY = ("zh", "ja", "fr", "de", "es", "pl", "ru", "ko")


def get(lang):
    if lang not in REGISTRY:
        return None
    # 用包自身的名字导入，避免依赖「text 目录在 sys.path 上」这种副作用
    return importlib.import_module(__name__ + "." + lang)


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


def script_re(lang):
    """目标文字正则；拉丁字母语言（fr/de/es）没有，返回 None。

    「这条译文到底译没译」不能用「值不是纯占位符」判 —— 未翻译的条目
    值就是英文原串，那样会整篇判成已译。判据只能是**目标文字是否出现**，
    而且这份判据要和语言放同一个模块里，加一门语言只改一个地方。
    """
    mod = get(lang)
    return getattr(mod, "SCRIPT", None) if mod else None
