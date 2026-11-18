#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""德语修补：交叉核对查出的 5 条硬错。"""
import io
import tomllib

PATH = r"C:\Users\mrche\WorkBuddy\2026-10-15-23-47-12\Port Royale 2 Localization\src\translations\de.toml"

PATCH = {
    # flute-ship 被译成乐器"竖笛"，零售德语用 Fleute
    "0x072a9579": ("zwei holländische Handelsflöten",
                   "zwei holländische Handelsfleuten"),
    # 货物术语：基线定 Waren，这里滑成 Güter
    "0xd83f794d": ("Liefert Güter, die die Stadt benötigt",
                   "Liefert Waren, die die Stadt benötigt"),
    # 火炮术语：其余全表用 Kanone，这里自造 Hafengeschütz
    "0x2d0e6567": ("fünf Hafengeschütze in Eurer Stadt",
                   "fünf Hafenkanonen in Eurer Stadt"),
    # 自造复合词，缺连接元音；采用零售德语的写法
    "0x1a7b911b": ("Konvoladung", "Konvoibeladung"),
    # 英文与法语都是问句，德语丢了问号
    "0x2546beba": ("Wie wäre es: Wenn Ihr mir einen Gefallen tut, tue ich Euch einen.",
                   "Wie wäre es, wenn Ihr mir einen Gefallen tut und ich Euch dafür einen?"),
}

doc = tomllib.load(open(PATH, "rb"))
for rid, (old, new) in PATCH.items():
    if old not in doc.get(rid, ""):
        raise SystemExit("命中失败：%s 里没有 %r" % (rid, old))

lines = io.open(PATH, encoding="utf-8", newline="\n").read().split("\n")
hit = {}
for i, line in enumerate(lines):
    if not line.startswith('"'):
        continue
    key = line.split('"')[1]
    if key not in PATCH:
        continue
    old, new = PATCH[key]
    lines[i] = line.replace(old, new)
    hit[key] = hit.get(key, 0) + 1
lines_text = "\n".join(lines)
io.open(PATH, "w", encoding="utf-8", newline="\n").write(lines_text)

doc2 = tomllib.load(open(PATH, "rb"))
for rid, (_o, new) in PATCH.items():
    if new not in doc2[rid]:
        raise SystemExit("写回校验失败：%s" % rid)

diff = sum(1 for k in doc if doc2[k] != doc.get(k))
print("命中 %d/%d，实际改动 %d 条" % (len(hit), len(PATCH), diff))
