# -*- coding: utf-8 -*-
"""俄文：显式不处理（no-op）。放在这里是为了让「不处理」是一份声明，而不是缺失。

不处理的原因：
* 补空格：俄语用空格分词，不需要按字数成组；
* 标点：`,` `.` `;` `:` `?` `!` 前面都不留空格，没有要补的格；
* 引号：正文一律用 `«…»`，且两侧本来就带空格，现有文本已经是这个形状，不需要规则
  二次加工（若以后出现 `"…"`，由 `text_lint` 的引号检查先报出来）；
* 半角→全角：俄语没有 CJK 语境，不需要；
* 西里尔字形由包里自带的 `PR2CyrBody-*` / `PR2CyrDisplay-*` 提供，`font-map.ini` 的
  `[ru]` 已映射，不需要额外处理。
"""

import re

from . import spec as S

LANG = "ru"

#: 目标文字：西里尔字母。供 `translate.py status` 判「译没译」用。
SCRIPT = re.compile(r"[\u0400-\u045f\u0460-\u04ff]")

SKIP = "空格分词、标点无前置空格、«» 已自带空格"


def spec():
    return S.LangSpec(code=LANG, punct=None,
                      segmenter=S.NullSegmenter(), spacing=S.NoSpacing())
