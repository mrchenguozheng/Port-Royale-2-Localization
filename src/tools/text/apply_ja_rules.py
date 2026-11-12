#!/usr/bin/env python3
# coding: utf-8
r"""apply_ja_rules.py —— 从日语译文生成引擎能用的文本（带排版空格）

来源：src/translations/ja.toml（无排版空格，唯一手改层）
产物：build/engine_text/ja.toml（**构建产物，不进仓库**）

规则来自 lang_rules/ja.py：
- 标点规范化；
- 占位符两侧的空格；
- 助词后补空格（优先形态素分析，装了 janome/fugashi 更准；没装则用正则）。

    python src/tools/text/apply_ja_rules.py             # 生成并写入 build/engine_text
    python src/tools/text/apply_ja_rules.py --check     # 只对比，不写文件
"""

import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
ROOT = os.path.dirname(os.path.dirname(TOOLS))
CLEAN = os.path.join(ROOT, "src", "translations", "ja.toml")
OUT = os.path.join(ROOT, "build", "engine_text", "ja.toml")

sys.path.insert(0, HERE)
from text.lang_rules import spec as specs  # noqa: E402
from text import lang_rules  # noqa: E402

HEADER = [
    "# 构建产物：由 src/translations/ja.toml 经 apply_ja_rules.py 生成，不进仓库。",
    "# 改译文请改 src/translations/ja.toml（干净文本），构建时会重新生成。",
]


def esc(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def generate_from(clean, order):
    """纯函数：{id: 译文} + 顺序 → {id: 引擎文本}。

    走 lang_rules 的三段式接口（标点 / 分词器 / 补空格），与 engine_text 同一条路。
    """
    out, _stats, _seg = specs.build_texts(lang_rules.get_spec("ja"), clean, list(order))
    return out


def generate():
    clean = tomllib.load(open(CLEAN, "rb"))
    order = [m.group(1) for m in
             (re.match(r'^"([^"]+)"\s*=', line)
              for line in io.open(CLEAN, encoding="utf-8")) if m]
    return order, generate_from(clean, order)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只对比 build/engine_text/ja.toml，不写文件")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    order, new = generate()
    old = {}
    if os.path.isfile(OUT):
        try:
            old = tomllib.load(open(OUT, "rb"))
        except (OSError, ValueError):
            old = {}

    changed = [h for h in order if old.get(h) != new[h]]
    added = [h for h in order if h not in old]
    only_old = [h for h in old if h not in new]

    print("条目：%d，新生成 %d 条，与现有不同 %d 条"
          % (len(order), len(new), len(changed)))
    if added:
        print("  新增：%d" % len(added))
    if only_old:
        print("  仅旧文件有：%d" % len(only_old))
    for h in changed[:10]:
        print("  %s\n    旧：%s\n    新：%s" % (h, old.get(h), new[h]))
    if len(changed) > 10:
        print("  …其余 %d 条" % (len(changed) - 10))

    if args.check:
        return 1 if (changed or only_old) else 0
    if args.dry_run:
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    lines = list(HEADER)
    for h in order:
        lines.append('"%s" = "%s"' % (h, esc(new[h])))
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("已写入", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
