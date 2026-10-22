#!/usr/bin/env python3
# coding: utf-8
r"""apply_ja_rules.py —— 从干净日语源生成带排版空格的 ja.toml

来源：src/seed/ja.toml（无排版空格）
产物：src/live/ja.toml（引擎用，带助词/标点后的空格）

规则来自 lang_rules/ja.py：
- 标点规范化；
- 占位符两侧的空格；
- 助词后补空格（优先形态素分析，装了 janome/fugashi 更准；没装则用正则）。

    python src/tools/apply_ja_rules.py             # 只对比，不写文件
    python src/tools/apply_ja_rules.py --write     # 写入 live/ja.toml
"""

import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CLEAN = os.path.join(ROOT, "src", "seed", "ja.toml")
OUT = os.path.join(ROOT, "src", "live", "ja.toml")

sys.path.insert(0, HERE)
import lang_rules.ja as JA  # noqa: E402

HEADER = [
    "# 日语生成物：由 src/seed/ja.toml 经 apply_ja_rules.py 生成，请勿手改。",
    "# 改动请改 seed/ja.toml（干净文本），再跑一次 apply_ja_rules.py。",
]


def esc(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def generate():
    clean = tomllib.load(open(CLEAN, "rb"))
    order = [m.group(1) for m in
             (re.match(r'^"([^"]+)"\s*=', line)
              for line in io.open(CLEAN, encoding="utf-8")) if m]
    out = {}
    for hid in order:
        out[hid] = JA.normalize(clean[hid], particles=True)
    return order, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="真正写入 live/ja.toml（默认只对比）")
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

    if not args.write:
        print("\n默认不写文件；确认后加 --write 生成 live/ja.toml。")
        return 0

    lines = list(HEADER)
    for h in order:
        lines.append('"%s" = "%s"' % (h, esc(new[h])))
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("已写入", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
