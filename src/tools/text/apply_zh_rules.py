# -*- coding: utf-8 -*-
"""apply_zh_rules.py —— 中文构建入口的兼容门面。

真正的构建入口已经统一到 engine_text.py（`--lang zh`），中文的排版步骤在
zh_pipeline.py（分词前）与 lang_rules/zh.py（标点 + 补空格策略）里。

本模块只保留旧名字，供编辑器（规则轨迹）、测试和旧脚本调用：
`fix_conj / space_tokens / build_names / find_names / pad_names / generate_doc`。
新代码请直接用 zh_pipeline 与 lang_rules。
"""

import sys
from os.path import abspath, dirname, join

HERE = dirname(abspath(__file__))
TOOLS = dirname(dirname(abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

from text import lang_rules, zh_pipeline  # noqa: E402
from text.lang_rules import spec as specs  # noqa: E402

TAG = zh_pipeline.TAG
fix_conj = zh_pipeline.fix_conj
load_list = zh_pipeline.load_list
build_names = zh_pipeline.build_names
find_names = zh_pipeline.find_names
pad_names = zh_pipeline.pad_names
space_tokens = zh_pipeline.space_tokens
collapse_spaces = zh_pipeline.collapse_spaces


def generate_doc(doc, order=None):
    """纯函数：{id: 译文} → (order, {id: 引擎文本}, stats, 分词器名)。"""
    order = list(order or doc)
    out, stats, seg_name = specs.build_texts(lang_rules.get_spec("zh"), doc, order)
    return order, out, stats, seg_name
