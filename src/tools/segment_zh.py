# -*- coding: utf-8 -*-
"""给 space_words.py 用的分词子进程：读 JSON 字符串数组，输出 JSON 词数组的数组。

必须用装了 spaCy + zh_core_web_sm 的 Python 3.11 运行（spaCy 的依赖在 3.14 上
还没有轮子）。space_words.py 会通过 PR2_SPACY_PYTHON 指定的解释器调用它。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
try:
    import spacy  # noqa: E402
except ImportError:                      # 老环境：spaCy 装在 .tmp/spacy37
    sys.path.insert(0, os.path.join(ROOT, ".tmp", "spacy37"))
    import spacy  # noqa: E402

_model = os.environ.get("PR2_SPACY_MODEL", "zh_core_web_sm")
_nlp = spacy.load(_model)


def main():
    runs = json.load(sys.stdin)
    out = [[t.text for t in _nlp(r)] for r in runs]
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
