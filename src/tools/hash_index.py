#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hash_index.py —— 给每条字符串生成「这条是干什么用的」索引。

为什么要它：3500 多个 hash 只看编号没法判断用途，改译文时很难定位。
这份索引把每条按用途归类，附中文摘要（没有中文时用英文），
生成 build\\hash-index.csv（Excel 可读）和 build\\hash-index.md（分组的表）。

用法
----
    python src\\tools\\hash_index.py            # 生成两份索引
    python src\\tools\\hash_index.py --lang ja  # 摘要用日语
"""
import argparse
import csv
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
ROOT = os.path.dirname(SRC)
OUT_DIR = os.path.join(ROOT, "build")

sys.path.insert(0, HERE)
import translate as T
import glossary as G

#: 按 id 段落归类的固定区间（游戏表里同类文本连续排列）
RANGES = [
    (0x37328fb9, 0x37329033, "货物"),
    (0x24646e0b, 0x24646e83, "船只"),
    (0xe9278a47, 0xe9278abe, "军衔"),
    (0xc77f4c7a, 0xc77f4e47, "城镇"),
    (0xcf570000, 0xcf580000, "人名·姓氏"),
    (0xd5dd1200, 0xd5dd1400, "人名·海盗"),
    (0xf7acef00, 0xf7acf100, "人名·海盗"),
    (0xfc516e00, 0xfc51b000, "人名·常用名"),
    (0x2ee8b900, 0x2ee8be00, "教程"),
    (0x2efebf00, 0x2eff0000, "教程"),
]

#: 关键词归类（按顺序匹配，先具体后笼统）
KEYWORDS = [
    (r"\b(scenario objective|introductory scenario|scenario is over|scenario will end)\b", "剧本目标"),
    (r"\b(mission|letter of marque|reward|deadline)\b", "任务/信件"),
    (r"\b(congratulations|congratulation)\b", "提示·祝贺"),
    (r"\b(you have|you can|you must|click|right-click|select the)\b", "提示/操作说明"),
    (r"\b(save|load|options|quit|cancel|continue|game menu|return to game)\b", "界面·菜单"),
    (r"\b(trade|convoy|ship|cargo|goods|harbor|warehouse)\b", "交易/舰队"),
]


def classify(k, en):
    """按「用途」给条目归类：段落区间 → 结构特征 → 关键词。"""
    n = int(k, 16)
    for lo, hi, name in RANGES:
        if lo <= n <= hi:
            return name

    text = en.strip()
    low = text.lower()
    words = re.findall(r"[A-Za-z']+", text)

    if re.fullmatch(r"[\s%<@\d.:/%-]+", text):
        return "格式串/符号"
    if text in ("+++EMPTY+++", "...", "—"):
        return "占位/空文本"
    if re.search(r"\b(dear|sincerely|yours faithfully)\b", low):
        return "信件"
    for pat, name in KEYWORDS:
        if re.search(pat, low):
            return name
    if "click" in low or "right-click" in low:
        return "提示/操作说明"
    if '"' in text or "“" in text:
        return "对话"
    if len(words) <= 3 and len(text) < 32 and not re.search(r"[.!?]$", text):
        return "短标签/词条"
    if len(text) > 180:
        return "长文/轶事"
    if re.search(r"\b(you|your|we|our|i)\b", low):
        return "叙述/提示句"
    return "其它"


def main():
    ap = argparse.ArgumentParser(description="生成 hash 用途索引")
    ap.add_argument("--lang", default="zh", help="摘要用哪种语言（默认 zh）")
    a = ap.parse_args()

    rows = T.load_toml()["s"]
    groups = G.load_terms()
    term_cat = {}
    for g in groups:
        for k in G.pick_ids(g, G.load_table(T.lang_path(T.BASE_LANG))):
            term_cat[k] = "术语·" + g["name"]

    os.makedirs(OUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUT_DIR, "hash-index.csv")
    md_path = os.path.join(OUT_DIR, "hash-index.md")

    out = []
    for r in rows:
        k = r["id"]
        en = r.get(T.BASE_LANG, "") or ""
        text = (r.get(a.lang) or "") or en
        cat = term_cat.get(k) or classify(k, en)
        brief = re.sub(r"\s+", " ", text).strip()[:60]
        out.append({"id": k, "cat": cat, "brief": brief,
                    "en": re.sub(r"\s+", " ", en).strip()[:60],
                    "n": len(re.findall(r"<n", en)),
                    "vars": len(re.findall(r"%\d|@[A-Za-z]\$", en))})

    with io.open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "用途", "摘要", "English", "<n>", "占位符"])
        for x in out:
            w.writerow([x["id"], x["cat"], x["brief"], x["en"], x["n"], x["vars"]])

    # 按 hash 顺序输出（游戏表里的原始顺序），一条一行
    lines = ["# 字符串用途索引（按 hash 顺序）", "",
             "> 由 `src\\tools\\hash_index.py` 生成；用途按段落/关键词判定，"
             "内容取自 `%s`（没有译文时退回英文）。" % a.lang, "",
             "| # | hash | 作用 | 内容 | English |", "|---|---|---|---|---|"]
    for i, x in enumerate(out, 1):
        lines.append("| %d | `%s` | %s | %s | %s |" % (
            i, x["id"], x["cat"],
            x["brief"].replace("|", "\\|"), x["en"].replace("|", "\\|")))
    io.open(md_path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("已生成 %s / %s（%d 条，按 hash 顺序）" % (csv_path, md_path, len(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
