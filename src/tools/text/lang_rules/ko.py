# -*- coding: utf-8 -*-
"""韩文：显式不处理（no-op）。放在这里是为了让「不处理」是一份声明，而不是缺失。

不处理的原因：
* 补空格：韩语以「语节（eojeol）」为单位用空格分开，空格位置由译文决定，不能像
  中文那样按字数预算插空格；中文的 `ZhCompactSpacing` 在这里会切坏词尾助词；
* 标点：韩语标点前面不留空格，没有要补的格；
* 半角→全角：韩语没有 CJK 语境，不需要；
* 已知更该处理的问题不在这里：`ko.toml` 3548 条里有 2461 条没有谚文、2435 条与英文
  原文逐字相同（大面积未完成）。那是译文内容缺口，属于补译工作，构建期规则只能
  原样透传，不能替作者写韩文。
"""

import re

from . import spec as S

LANG = "ko"

#: 目标文字：谚文（含古谚文字母与相容字母）。`translate.py status` 用这一份
#: 判「这条到底译没译」，不再靠「值不是纯占位符」那种会把整篇判成已译的口径。
SCRIPT = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")

SKIP = "语节空格分词、标点无前置空格；大面积未翻译属内容层"


def spec():
    return S.LangSpec(code=LANG, punct=None,
                      segmenter=S.NullSegmenter(), spacing=S.NoSpacing())
