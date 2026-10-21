#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normalize_text.py —— 统一译文的空格：全角标点、占位符、换行标签。

规则已经不在这里了：每种语言一份，放在 src\\tools\\lang_rules\\ 下：

    lang_rules/zh.py   中文的标点表、半角→全角映射、占位符规则
    lang_rules/ja.py   日文的（外加助词空格）

本文件只负责：选语言、读 toml、逐条调用该语言的 normalize()、写回。

用法
----
    python src\\tools\\normalize_text.py --lang zh --dry-run
    python src\\tools\\normalize_text.py --lang zh
    python src\\tools\\normalize_text.py --lang ja --particles
"""

import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import translate as T  # noqa: E402
import lang_rules  # noqa: E402
from lang_rules import base  # noqa: E402


def esc(t):
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main():
    ap = argparse.ArgumentParser(description="统一译文的空格（规则按语言分开）")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    ap.add_argument("--force", action="store_true",
                    help="没有专用规则的语言，改用中文规则")
    ap.add_argument("--particles", action="store_true",
                    help="日语：在句子中间的助词后补空格")
    a = ap.parse_args()

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
    doc = tomllib.load(open(path, "rb"))
    ids = [m.group(1) for m in
           (re.match(r'^"([^"]+)"\s*=', l) for l in io.open(path, encoding="utf-8")) if m]

    changed = 0
    for k in ids:
        if not rules.CJK_RX.search(doc[k]):
            continue                       # 还没译的条目保持与原文逐字一致
        opts = {"date_format": k in base.DATE_FORMAT_IDS}
        if a.lang == "ja":
            opts["particles"] = a.particles
        new = rules.normalize(doc[k], **opts)
        if new != doc[k]:
            changed += 1
            doc[k] = new

    print("%s：%d / %d 条需要调整" % (a.lang, changed, len(ids)))
    if a.dry_run or not changed:
        return

    head = []
    try:
        for ln in io.open(path, encoding="utf-8"):
            if ln.startswith("#"):
                head.append(ln.rstrip("\n"))
            else:
                break
    except OSError:
        pass
    io.open(path, "w", encoding="utf-8", newline="\n").write(
        "\n".join(head + ['"%s" = "%s"' % (k, esc(doc[k])) for k in ids]) + "\n")
    print("已写回", path)


if __name__ == "__main__":
    main()
