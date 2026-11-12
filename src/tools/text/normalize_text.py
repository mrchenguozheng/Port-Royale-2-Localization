#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normalize_text.py —— 统一译文的空格：全角标点、占位符、换行标签。

规则已经不在这里了：每种语言一份，放在 src\\tools\\text\\lang_rules\\ 下：

    lang_rules/zh.py   中文的标点表、半角→全角映射、占位符规则
    lang_rules/ja.py   日文的

本文件只负责：选语言、读 toml、逐条调用该语言的 normalize()、写回。

注意：这里只改**标点**，不补排版空格。补空格（按词成组 / 助词后加一格）
是构建期的事，见 lang_rules/spec.py 的 Spacing；所以 --particles 已移除。

用法
----
    python src\\tools\\text\\normalize_text.py --lang zh --dry-run
    python src\\tools\\text\\normalize_text.py --lang zh
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
import translate as T  # noqa: E402
from text import lang_rules, toml_io  # noqa: E402
from text.lang_rules import base  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="统一译文的空格（规则按语言分开）")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    ap.add_argument("--force", action="store_true",
                    help="没有专用规则的语言，改用中文规则")
    ap.add_argument("--particles", action="store_true",
                    help="（已移除）助词空格属构建期，见 engine_text.py")
    a = ap.parse_args()

    if a.particles:
        raise SystemExit(
            "--particles 已移除：助词空格是构建期的补空格策略"
            "（lang_rules/spec.py，Spacing mode=\"particle\"），不写回译文层。\n"
            "请用：python src/tools/text/engine_text.py --lang ja")

    rules = lang_rules.get(a.lang)
    if rules is None:
        if not a.force:
            raise SystemExit(
                "没有 %s 的规则（已有：%s）。真要按中文规则处理请加 --force。"
                % (a.lang, "、".join(lang_rules.names())))
        rules = lang_rules.get("zh")

    path = T.lang_path(a.lang)
    if not os.path.isfile(path):
        raise SystemExit("没有 %s" % path)
    doc, ids = toml_io.read_doc(path)

    changed = 0
    for k in ids:
        if not rules.CJK_RX.search(doc[k]):
            continue                       # 还没译的条目保持与原文逐字一致
        opts = {"date_format": k in base.DATE_FORMAT_IDS}
        new = rules.normalize(doc[k], **opts)
        if new != doc[k]:
            changed += 1
            doc[k] = new

    print("%s：%d / %d 条需要调整" % (a.lang, changed, len(ids)))
    if a.dry_run or not changed:
        return

    head = toml_io.head_lines(path)
    toml_io.write_doc(path, doc, ids, head)
    print("已写回", path)


if __name__ == "__main__":
    main()
