# -*- coding: utf-8 -*-
"""意大利文：显式不加工（no-op），但把它的排版忌讳写清楚。

不处理的原因：
* 补空格：意语用空格分词，不需要按字数成组；
* 标点：`?` `!` 前面不留空格，后面照常接空格（与法语的前置空格相反），
  没有可以挪的正字法间距；
* 半角→全角：没有 CJK 语境；
* 字形：原版四款拉丁字体对意语用字（`à è é ì ò ó ù ú` 及其大写）**全覆盖**，
  实测见 `font-map.ini` 的 `[it]` 一节，因此按 config 出包、不打包字体。

唯一需要守的排版点是**省音撇号**：`l'isola`、`dell'acqua`、`un'amica` 里的 `'`
必须紧贴前后，写成 `l' isola` 是错的。这一条属译文层，由 `text_lint` 的
`it_checks`（E 级）守，构建期不做改写——撇号本身是字形，改不了它的位置。
"""

import re

from . import spec as S

LANG = "it"

SKIP = (
    "空格分词、标点无前置空格；省音撇号必须紧贴前后，由 text_lint 的 it_checks 守；"
    "原版拉丁字体对意语用字全覆盖，按 config 出包。"
)

#: 省音撇号后误加空格（`l' isola` / `dell' acqua`）。只查字母后紧跟撇号再跟空白，
#: 不误伤 `c'è` 之外的人名缩写与引号结尾。
APOS_SPACE_RX = re.compile(r"[A-Za-zÀ-ÿ]'\s+(?=[A-Za-zÀ-ÿ])")

#: 标点前误留空格（`Città ?`），意语不允许。
PUNCT_SPACE_RX = re.compile(r"\s+[?!:,;]")


def spec():
    return S.LangSpec(
        code=LANG,
        punct=None,
        segmenter=S.NullSegmenter(),
        spacing=S.NoSpacing(),
    )
