#!/usr/bin/env python3
# coding: utf-8
"""align_export.py —— 把七语（英德法西波俄 + 中日）拉成一张对齐表。

下次翻一门新语言时，最省力的做法不是从英文重译，而是先查这张表：
同一个键在德/法/西/波/俄/日里已经有现成译法，多数语怎么说一眼可见，
分岔点（哪几门语言背离英文）也直接写在 `split` 列。

    python src/tools/analysis/align_export.py
    python src/tools/analysis/align_export.py --out docs/csv/analysis/七语对齐.csv

列：key, words_en, split, en, de, fr, es, pl, ru, ja, zh
  words_en  按既定分档口径算的英文词数（去占位/标签后）
  split     该条有几门语言与英文原文不同（英文基准里全是标识符的会是 0）
"""

import csv
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

LANGS = [
    ("en", os.path.join("src", "orig", "en.gog_1.1.2.3.toml")),
    ("de", os.path.join("src", "orig", "de.retail-1.0.0.toml")),
    ("fr", os.path.join("src", "orig", "fr.gog_1.1.2.42.toml")),
    ("es", os.path.join("src", "orig", "es.retail-1.0.0.toml")),
    ("pl", os.path.join("src", "orig", "pl.retail-1.0.0.toml")),
    ("ru", os.path.join("src", "orig", "ru.retail-1.0.0.toml")),
    ("ja", os.path.join("src", "translations", "ja.toml")),
    ("zh", os.path.join("src", "translations", "zh.toml")),
]

TPL = re.compile(r"@[a-zA-Z]\$[^$]*\$|<[^>]*>|%[0-9]")


def words(v):
    return len(re.findall(r"[A-Za-zÀ-ÿ']+", TPL.sub(" ", v)))


def main(argv):
    out = os.path.join("docs", "csv", "analysis", "七语对齐.csv")
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    data = {}
    for code, rel in LANGS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            print("跳过（缺文件）：%s" % rel)
            continue
        data[code] = tomllib.load(open(p, "rb"))

    en = data["en"]
    order = [c for c, _ in LANGS]
    rows = []
    for k in sorted(en):
        cols = []
        split = 0
        for c in order:
            v = data[c].get(k, "")
            cols.append(v)
            if c not in ("en", "ja", "zh") and v and v != en[k]:
                split += 1
        rows.append([k, words(en[k]), split] + cols)

    path = os.path.join(ROOT, out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "words_en", "split"] + order)
        w.writerows(rows)
    print("导出 %d 行 → %s" % (len(rows), out))
    # 顺带给出按分档的条数，方便下次分批
    buckets = {"长文>10": 0, "中句4-10": 0, "短标签1-3": 0, "纯参数0": 0}
    for r in rows:
        n = r[1]
        if n == 0:
            buckets["纯参数0"] += 1
        elif n <= 3:
            buckets["短标签1-3"] += 1
        elif n <= 10:
            buckets["中句4-10"] += 1
        else:
            buckets["长文>10"] += 1
    print("分档：" + "，".join("%s=%d" % (k, v) for k, v in buckets.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
