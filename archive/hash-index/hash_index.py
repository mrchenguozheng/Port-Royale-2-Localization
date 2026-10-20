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


def classify_hint(k, en):
    n = int(k, 16)
    for lo, hi, name in RANGES:
        if lo <= n <= hi:
            return name
    low = en.lower()
    for pat, name in KEYWORDS:
        if re.search(pat, low):
            return name
    if "click" in low:
        return "教程/操作"
    if len(en) > 180:
        return "长文"
    return "文本"


def kind(en):
    """一句话说清这条文本是干什么用的（不抄原文）。"""
    t = en.strip()
    low = t.lower()
    if re.fullmatch(r"[\s%<@\d.:/%-]+", t):
        return "格式串（只含占位符/符号）"
    if t in ("+++EMPTY+++", "...", "—"):
        return "空占位"
    if "letter of marque" in low:
        return "私掠许可证相关"
    if re.search(r"\b(dear|sincerely|yours faithfully)\b", low):
        return "信件（署名/正文）"
    if "scenario" in low:
        return "剧本目标/说明"
    if "mission" in low:
        return "任务相关提示"
    if re.search(r"\b(congratulations|congratulation)\b", low):
        return "祝贺提示"
    if re.search(r"\b(failed|not accomplished|not completed)\b", low):
        return "失败提示"
    if "click" in low or "right-click" in low:
        return "操作指引"
    if re.search(r"\b(i |my |me |we |our )\b", low):
        return "角色对白/叙述"
    if re.search(r"\b(you |your )\b", low):
        return "玩家提示"
    if re.search(r"^(save|load|options|quit|cancel|continue|ok|yes|no|back)\b", low):
        return "界面按钮"
    if len(t.split()) <= 3 and not re.search(r"[.!?]$", t):
        return "短标签/名词"
    return "普通句子"


TOPICS = [
    (r"\b(ship|convoy|fleet|vessel|sail)\b", "船队"),
    (r"\b(trade|goods|cargo|price|market|warehouse|stock)\b", "交易/货物"),
    (r"\b(war|peace|nation|england|spain|france|dutch|treaty)\b", "战争/国家"),
    (r"\b(mission|reward|deadline|order)\b", "任务"),
    (r"\b(town|building|permit|wall|council)\b", "城镇/建筑"),
    (r"\b(captain|governor|viceroy|pirate|buccaneer|crew)\b", "人物"),
    (r"\b(plague|fire|storm|hurricane|attack|siege)\b", "灾害/战斗"),
    (r"\b(loan|money|gold|debt|profit|income|wage)\b", "金钱"),
]


def topic(en):
    low = en.lower()
    for pat, name in TOPICS:
        if re.search(pat, low):
            return name
    return ""


def purpose(k, en, zh, cat):
    """一句话说清用途：术语带译名，句子只说类型。"""
    kind_s = kind(en)
    name = re.sub(r"\s+", " ", (zh or en)).strip()
    if len(name) > 16:
        name = name[:16]
    if cat.startswith("术语·") or cat.startswith("人名"):
        return "%s：%s" % (cat, name)
    if cat == "教程":
        return "教程：" + kind_s
    if kind_s == "短标签/名词":
        return "标签：" + name
    tp = topic(en)
    return (tp + "·" + kind_s) if tp else kind_s


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
        zh = (r.get(a.lang) or "") or ""
        cat = term_cat.get(k) or classify_hint(k, en)
        out.append({
            "id": k,
            "use": purpose(k, en, zh, cat),
            "n": len(re.findall(r"<n", en)),
            "vars": len(re.findall(r"%\d|@[A-Za-z]\$", en)),
        })

    with io.open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "作用", "段落数", "占位符数"])
        for x in out:
            w.writerow([x["id"], x["use"], x["n"], x["vars"]])

    # 按 hash 顺序输出（游戏表里的原始顺序），一条一行
    lines = ["# 字符串用途索引（按 hash 顺序）", "",
             "> 由 `src\\tools\\hash_index.py` 生成：每条按英文/法文原文的结构与关键词"
             "概括用途（不抄原文），术语类带上 `%s` 的译名。" % a.lang, "",
             "| # | hash | 作用 | 段落 | 占位符 |", "|---|---|---|---|---|"]
    for i, x in enumerate(out, 1):
        lines.append("| %d | `%s` | %s | %d | %d |" % (
            i, x["id"], x["use"].replace("|", "\\|"), x["n"], x["vars"]))
    io.open(md_path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("已生成 %s / %s（%d 条，按 hash 顺序）" % (csv_path, md_path, len(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
