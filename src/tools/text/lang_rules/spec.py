# -*- coding: utf-8 -*-
r"""spec.py —— 按语言声明的三段式接口：标点 / 分词器 / 补空格。

为什么要有这一层
----------------
以前 `engine_text.build()` 是 `if lang == "zh" … elif lang == "ja" … else 原样`，
补空格策略一半写在 `apply_zh_rules`、一半藏在 `ja.normalize(particles=True)` 里，
新语言要同时改三个地方。现在按语言只声明一份 `LangSpec`：

    LangSpec(code, punct, segmenter, spacing)

三个部件各自的职责：

* `Punctuation.normalize(text, date_format=False)`
    纯函数、不碰分词：全角化、标点后空格、占位符两侧空格、`<n>` 去空格。
* `Segmenter`
    `prepare(texts)` 批量准备（中文要把所有要切的片段一次性交给分词器），
    `tag(text)` 给出 `[(surface, pos)]`（日语判助词用）。
    没有分词器就声明 `NullSegmenter`，`name` 为 `"none"`。
* `Spacing`
    `pre_punct(text)`：标点规范化**之前**做的事（日语助词空格就属于这里，
    它必须先于标点，否则和标点补的空格互相干扰）；
    `before(text)`：标点之后、分词之前的语言私有步骤（中文的连词/人名/
    数字标签空格），返回 `(文本, 统计增量)`；
    `prepare(texts, segmenter)`：批量准备分词上下文（中文在这里一次性切词）；
    `apply(text, ctx)`：成组/加助词空格，得到引擎文本。

`build_texts()` 是唯一的执行器：先 `pre_punct`，再 `punct.normalize`，
再 `before`，再批量 `prepare`，最后 `apply`。所有语言走同一条路。

明确不做从右往左书写的语言：没有游戏源代码，绘制方向改不了，
`Spacing` 只有 `none / group / particle` 三种模式，没有方向字段。
"""

from dataclasses import dataclass, field

from . import base


class Punctuation:
    """标点接口。tables 只是留个引用，方便调试时看清用了哪张表。"""

    def __init__(self, normalize, tables=None):
        self.normalize = normalize
        self.tables = tables or {}

    def __repr__(self):
        return "<Punctuation %s>" % (self.tables.get("lang", "?"))


class Segmenter:
    """分词器接口。默认实现=没有分词器。"""

    name = "none"

    def prepare(self, texts):
        """批量准备，返回不透明上下文（给 Spacing.apply 用）；不需要就返回 None。"""
        return None

    def tag(self, text):
        """返回 [(surface, pos)]；不支持词性标注就返回 None。"""
        return None


class NullSegmenter(Segmenter):
    name = "none"


class Spacing:
    """补空格策略。默认=不动（词间本来就有空格的语言）。"""

    mode = "none"

    def pre_punct(self, text):
        return text

    def setup(self, doc):
        """整份译文准备一次（中文在这里建人名表）。"""
        return None

    def before(self, text):
        return text, None

    def prepare(self, texts, segmenter):
        return None

    def apply(self, text, ctx):
        return text

    def report(self):
        """收尾提示（如「哪些片段没进分词器」）。默认什么都不说。"""
        return None


class NoSpacing(Spacing):
    pass


@dataclass
class LangSpec:
    code: str
    punct: object = None
    segmenter: object = field(default_factory=NullSegmenter)
    spacing: object = field(default_factory=NoSpacing)


#: 没有专用声明的语言：原样返回（用空格分词的语言不需要加工）
PASSTHROUGH = LangSpec(code="*", punct=None, segmenter=NullSegmenter(),
                       spacing=NoSpacing())


def build_texts(spec, doc, order=None):
    """执行器：{id: 译文} → ({id: 引擎文本}, stats, 分词器名)。

    两遍：第一遍到「分词前」，第二遍补空格。分词要批量，所以不能逐条做完。
    """
    order = list(order or doc)
    stats = {"punct": 0, "conj": 0, "name": 0, "space": 0}
    spec.spacing.setup(doc)

    interim = {}
    for hid in order:
        raw = doc.get(hid) or ""
        if not raw:
            interim[hid] = ""
            continue
        a = spec.spacing.pre_punct(raw)
        b = spec.punct.normalize(a) if spec.punct else a
        stats["punct"] += int(b != a)
        c, meta = spec.spacing.before(b)
        interim[hid] = c
        if meta:
            stats["conj"] += int(meta.get("conj", 0))
            stats["name"] += int(meta.get("name", 0))

    ctx = spec.spacing.prepare([t for t in interim.values() if t], spec.segmenter)

    out = {}
    for hid in order:
        c = interim[hid]
        if not c:
            out[hid] = ""
            continue
        d = spec.spacing.apply(c, ctx)
        stats["space"] += int(d != c)
        out[hid] = d

    spec.spacing.report()
    seg_name = getattr(ctx, "segmenter_name", "") or getattr(spec.segmenter, "name", "")
    return out, stats, (seg_name if seg_name not in ("", "none") else "")


def date_format(hid):
    """这个 hash 是不是日期格式串（占位符两侧不加空格）。"""
    return hid in base.DATE_FORMAT_IDS
