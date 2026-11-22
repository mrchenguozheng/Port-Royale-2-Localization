# -*- coding: utf-8 -*-
"""西文：显式不处理（no-op）。放在这里是为了让「不处理」是一份声明，而不是缺失。

不处理的原因：
* 补空格：西语用空格分词，不需要按字数成组；
* 标点：`?` `!` 前面不留空格；句首的 `¿` `¡` 是**内容层面**的成对符号（漏写属于
  译文错误，不是排版问题），`text_lint` 的 `es_checks` 已经在 W 级报
  「¿ 与 ? 数量不匹配」，这类要靠改文案解决，不能靠构建期规则补；
* 半角→全角：西语没有 CJK 语境，不需要；
* 重音字母 `á é í ó ú ñ ü` 与原版拉丁字体一致，`font-map.ini` 的 `[es]` 已映射，
  字形齐全。
"""

from . import spec as S

LANG = "es"

SKIP = "空格分词、标点无前置空格、¿¡ 属内容层（lint 已报）"


def spec():
    return S.LangSpec(code=LANG, punct=None,
                      segmenter=S.NullSegmenter(), spacing=S.NoSpacing())
