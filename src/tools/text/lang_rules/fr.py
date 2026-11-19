# -*- coding: utf-8 -*-
"""法文：显式不加工——法语排版已经写在译文里。

`src/translations/fr.toml` 直接写着 U+00A0（不换行空格）：`Vraiment?` 是 `Vraiment ?`、
`Or: 100` 是 `Or : 100`、`Réduire les prix de 5%` 是 `… de 5 %`。那是译文作者的字面，
构建期不再改第二遍——改字面属于内容层，不属于规则层。

为什么不在这里补空格 / 换空格
------------------------------
* 法语要求在 `? ! ; :` 前、`%` 前留一格（Imprimerie nationale 的 espace insécable），
  而这一格不能是普通空格：引擎只在 0x20 处断行，`Vraiment ?` 在窄框里会把问号
  单独带到下一行；NBSP 在法语字体里与空格同字形同宽（`ARIAL.TTF` 里 0x20 与 0xA0
  都指向 `space`，advance 均 569/2048 em）。
* 这些格子从哪来：`?` 209 / `!` 212 / `:` 180 处原文本来就写着一格，另有 46 处紧贴
  的（`%1: Route…`、`Roberts (1682?`）已按法语写法补齐，全部直接落在 fr.toml。
  规则层若再做一遍，等于拿构建期去补内容层的洞，且和译文里的写法双轨。
* 守住这个口径的是 `text_lint --lang fr` 的 `fr_typo_checks`（W 级）：谁改坏了
  （该有格子没格子、或写了一格普通空格），复核会报出来，不会静默。

本模块因此只做一件事：声明「我不用加工」，让 `REGISTRY` 里的七门语言都有文件、
有理由、有确定的透传行为。
"""

import re

from . import spec as S

LANG = "fr"

SKIP = (
    "法语排版（? ! ; : % 前的 NBSP）已直接写在 src/translations/fr.toml 里，"
    "空格分词、标点无前置空格之外的加工在构建期都没有必要；"
    "口径由 text_lint 的 fr_typo_checks 复核，不由构建期改写。"
)

#: 保留符号表判据：`lang_rules/fr.py` 不再改写文本，但这条判据仍被 lint 复用。
ODD_RX = re.compile(r"[`\\^|~\[\]{}]")


def spec():
    return S.LangSpec(
        code=LANG,
        punct=None,
        segmenter=S.NullSegmenter(),
        spacing=S.NoSpacing(),
    )
