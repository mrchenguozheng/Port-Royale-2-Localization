# -*- coding: utf-8 -*-
"""pack_tags.py —— 语言包身份标记的唯一词表。

标记写在 `src/packs/<lang>.toml` 的 `tags` 里，描述“这份译文是谁做的、
怎么做的”，与完成度（`review_status`）是两条独立的轴：

    同人制作的社区协作版，AI 辅助起草，尚未全文校对
        tags = ["fan", "community", "ai-assist"]，review_status = "preview"

词表固定，config_check.py 拒绝表外标记；新增标记先改这里。
"""

TAGS = (
    ("official", "官方"),
    ("retail", "零售版官方本地化"),
    ("fan", "同人制作"),
    ("community", "社区协作"),
    ("ai-assist", "AI 辅助"),
    ("machine", "机器翻译"),
)

TAG_LABELS = dict(TAGS)

REVIEW_LABELS = {
    "preview": "预览版",
    "complete": "已校对",
}


def tag_names():
    return tuple(name for name, _label in TAGS)


def normalize_tags(tags):
    """校验并返回规范化后的标记列表；不合法时抛 ValueError。

    未知标记、重复标记、空列表都算错，报错信息里列出可用词表。
    """
    if not isinstance(tags, (list, tuple)) or not tags:
        raise ValueError("tags 必须是非空列表，例如 [\"fan\", \"community\", \"ai-assist\"]")
    cleaned = []
    for item in tags:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("tags 里每一项都必须是非空字符串：%r" % (item,))
        name = item.strip().lower()
        if name not in TAG_LABELS:
            raise ValueError("未知标记 %r；可用标记：%s"
                             % (item, ", ".join(tag_names())))
        if name in cleaned:
            raise ValueError("重复标记：%s" % name)
        cleaned.append(name)
    # 按词表顺序排列，避免同一组标记在不同语言里写法不一致。
    return [name for name in tag_names() if name in cleaned]


def describe(tags, review_status=None):
    """给玩家看的一行：“标记：同人制作 · 社区协作 · AI 辅助；审阅：预览版”。"""
    names = normalize_tags(tags)
    text = "标记：" + " · ".join(TAG_LABELS[name] for name in names)
    if review_status in REVIEW_LABELS:
        text += "；审阅：" + REVIEW_LABELS[review_status]
    return text
