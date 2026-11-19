# -*- coding: utf-8 -*-
"""entries.py —— 把译文条目按结构分成几类。

为什么分
--------
3548 条译文里只有约 45% 是**正文**（带句读的那种），而「按预算补空格、
挑断点」只对正文有意义：短标签（约 43%）一旦折断就是毁词，工具条里
「游戏菜单」只画出「游 戏 菜」就是例证；模板与无汉字条目连碰都不能碰
（算式 `%1 %2  +  %3` 的双空格是作者的对齐，字体名插空格就废）。

分类只看结构——汉字数、句读、去掉标签与变量后还剩什么——不查词典，
纯函数、可复现。汉字口径取自 `lang_rules/base.CJK_RX`，和标点归一、
断点判定同一份；`glossary/terms.toml` 里的 `verse`（诗谜）是唯一需要
外部清单的类别，由调用方传入 id 集合。
"""

import os
import re
import tomllib

from .lang_rules import base

#: 类别常量。名字同时用作打印标签，别改成缩写。
PROSE = "正文"
LABEL = "短标签"
PHRASE = "名词短语"
NO_CJK = "无汉字"
TEMPLATE = "模板/符号"
VERSE = "诗谜"

ALL = (PROSE, LABEL, PHRASE, NO_CJK, TEMPLATE, VERSE)

#: 只有这两类会被补空格/断行。
WRAPPED = (PROSE, VERSE)

#: 不进排版的类别：不是中文文本，空格与顺序本身有意义。
#: 标签与名词短语**要**进排版——它们短，通常一刀都不用，但带变量时
#: （「你还需要%1才能升到下一级」）正好在变量前留一个断点，窄框里有用。
UNTOUCHED = (NO_CJK, TEMPLATE)

#: 句读：出现就把条目当正文（`<n>` 之外，靠它区分「一句完整的话」与「一个词」）。
_PUNCT = re.compile(r"[，。！？；：、…—]")

_TAG = re.compile(r"<[^>]*>")
_VAR = re.compile(r"%\d+|@[A-Za-z]\$[^$]*\$")

#: 标签与变量之外的可见内容都去掉后，什么都不剩、或只剩纯符号。
_VISIBLE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")

#: 短标签的字数上限：界面按钮、列表项、工具条小标签都在这个量级。
LABEL_MAX = 6

#: 不带句读但超过这个字数就不再是「一个词」，按正文处理。
PHRASE_MAX = 13


def body(text):
    """去掉行内标签与变量后的可见正文（变量替换成什么构建期不知道）。"""
    return _VAR.sub("", _TAG.sub("", text))


def kind(text, verse=False):
    """返回条目类别，见 ALL。`verse=True` 表示 id 在诗谜清单里。"""
    if verse:
        return VERSE
    b = body(text)
    if not _VISIBLE.search(b):
        return TEMPLATE
    if not base.CJK_RX.search(b):
        return NO_CJK
    if _PUNCT.search(b):
        return PROSE
    cjk = len(base.CJK_RX.findall(b))
    if cjk <= LABEL_MAX:
        return LABEL
    if cjk <= PHRASE_MAX:
        return PHRASE
    return PROSE


def tally(texts, verse_ids=()):
    """按类别计数，返回 {类别: 条数}（顺序见 ALL）。"""
    out = {k: 0 for k in ALL}
    for h, t in texts:
        out[kind(t, h in verse_ids)] += 1
    return out


def verse_ids(root=None):
    """从 `glossary/terms.toml` 的 `verse` 读诗谜 id 集合（无文件就返回空集）。

    诗谜本身也带句读，会被判成正文；清单只让统计与文案评审能单独点出这一类。
    """
    root = root or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "glossary", "terms.toml")
    if not os.path.isfile(path):
        return frozenset()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    ids = set()
    for pair in data.get("verse", []):
        ids.update(pair if isinstance(pair, (list, tuple)) else [pair])
    return frozenset(ids)
