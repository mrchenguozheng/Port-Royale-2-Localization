# -*- coding: utf-8 -*-
"""法文：显式不加工——不补空格、不换空格、不引入任何特殊空白。

法语排版在 `? ! ; :` 前、`%` 前要留一格，但**这一格就保持译文作者写的普通空格**：
本项目不把那一格换成 U+00A0，也不换成窄空格、零宽空格。口径是用户定的，
`text_lint --lang fr` 的 `fr_space_checks` 是它的守卫（E 级）：一旦有人在
`src/translations/fr.toml` 里写进 U+00A0 或其它非 U+0020 空白，复核直接失败。

已知副作用，明确接受：普通空格是引擎的断行点，窄框里 `Vraiment ?` 的问号可能
单独落到下一行；这是保持「不引进特殊字符」的代价，不用构建期规则去绕。

本模块因此只做一件事：声明「我不用加工」，让 `REGISTRY` 里的七门语言都有文件、
有理由、有确定的透传行为。
"""

import re

from . import spec as S

LANG = "fr"

SKIP = (
    "法语标点间距保留作者写的普通空格，不引入 U+00A0 等特殊空白；"
    "空格分词、无 CJK 语境，构建期没有可做的加工；"
    "口径由 text_lint 的 fr_space_checks（E 级）守住。"
)

#: 符号表判据（字符集自检串这类条目整条不做判断）。
ODD_RX = re.compile(r"[`\\^|~\[\]{}]")


def spec():
    return S.LangSpec(
        code=LANG,
        punct=None,
        segmenter=S.NullSegmenter(),
        spacing=S.NoSpacing(),
    )
