# -*- coding: utf-8 -*-
"""波兰语：显式不处理（no-op）。放在这里是为了让「不处理」是一份声明。

逐条对着流水线会做的事：

* 补空格：波兰语用空格分词，词与词之间已经分开，中文那套「按字数预算成组」不适用；
* 标点：波兰语标点（`.` `,` `;` `:` `?` `!`）前面不留空格，与英语一致，没有可补的；
* 引号：正文用 `„…"` 与 `"…"`（零售版如此），不强制改成直引号 —— 直引号检查是
  中文那一支的规则（片假名中点、直引号都是中文排版口径），拉丁语种不适用；
* 半角→全角：没有 CJK 语境，不需要；
* 目标文字判据：拉丁字母语言，`SCRIPT` 不声明，进度按「与英文原文不同」计。

**字形（已实测，不是推断）**：fontTools 读 `assets\fonts\original\` 的 cmap，
正文 ARIAL 1186 个码位、波兰语 18 个字母全覆盖；三个标题体
（ELGRECO_ / Tiepolo_black / Tiepolo_bold）只收 223 个字形，缺 ą ć ę ł ń ś ź ż
及大写（ó 在 Latin-1 里反而有）。所以 `font-map.ini` 的 `[pl]` 正文回落原版、
三个标题槽位指向 `build_lat_fonts.py` 生成的 `PR2PlDisplay-*.ttf`
（Noto Serif 按原版 cap height / 平均 advance 缩放）。不要在任何地方做
「按字符替换成近似拉丁字母」的妥协 —— 那是改译文迁就字体。
"""

from . import spec as S

LANG = "pl"

#: 供 `engine_text --stats` / 文档引用的一句话理由。
SKIP = "空格分词、标点前置无空格、无 CJK 语境；字形覆盖待实机确认"


def spec():
    """显式透传：没有标点规则、没有分词器、不补空格。"""
    return S.LangSpec(code=LANG, punct=None,
                      segmenter=S.NullSegmenter(), spacing=S.NoSpacing())
