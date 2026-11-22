# -*- coding: utf-8 -*-
"""德文：显式不处理（no-op）。放在这里是为了让「不处理」是一份声明，而不是缺失。

不处理的原因，逐条对着这条流水线会做的事：
* 补空格：德语用空格分词，词与词之间已经分开，中文那套「按字数预算成组」不适用；
* 标点：德语标点（`.` `,` `;` `:` `?` `!`）**前面不留空格**，与英语一致，没有可补的；
* 引号：正文里没有用 `„…“`，只有英式直引号，`text_lint` 已有 `直引号` 检查兜住；
* 半角→全角：德语没有 CJK 语境，不需要；
* 变音字母 `ä ö ü ß` 用的是原版拉丁字体，`font-map.ini` 的 `[de]` 已把四个逻辑名
  映射到原版字体，字形齐全，不需要额外处理。
"""

from . import spec as S

LANG = "de"

#: 供 `engine_text --stats` / 文档引用的一句话理由。
SKIP = "空格分词、标点前置无空格、无 CJK 语境"


def spec():
    """显式透传：没有标点规则、没有分词器、不补空格。"""
    return S.LangSpec(code=LANG, punct=None,
                      segmenter=S.NullSegmenter(), spacing=S.NoSpacing())
