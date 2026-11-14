#!/usr/bin/env python3
"""de_lint.py — 德语译文的确定性校验。

与 de_crosscheck.py 的分工：crosscheck 做跨语言相似度与对照统计（假阳性多，需人工判读）；
本脚本只查"不需要判断、命中即需处理"的硬规则与高频风格token，给 E（错）/ W（风格提示）两级。

用法:
    python src/tools/analysis/de_lint.py
    python src/tools/analysis/de_lint.py --json build/qa/de_lint.json --md docs/德语校对清单.md

退出码：存在 E 级命中时返回 1，否则 0（可直接串进提交前检查）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EN = ROOT / "src" / "orig" / "en.gog_1.1.2.3.toml"
DE = ROOT / "src" / "translations" / "de.toml"

# --- 规则表 ---------------------------------------------------------------
# 句首 du-命令式（表内应按 Ihr 敬称）
DU_IMPERATIVE = (
    "Statte Klicke Wähle Beachte Öffne Schließe Besuche Errichte Kaufe Verkaufe Segle Fahre"
    " Gehe Nimm Sieh Merke Denke Vergiss Halte Sorge Baue Ziehe Warte Drücke Aktiviere Starte"
    " Beende Speichere Lade Setze Stelle Schau Gib Zeig Sag Nutz Leg Trag Beweg Dreh Flieh"
    " Kämpfe Rüste Hebe Wirf Gieß Backe Räum Zahl Schalte Drück Erkunde Erwirtschafte"
).split()

# 禁用/待改的变体（左为错或不一致写法，右为定稿写法）
BANNED = {
    "Türkeninseln": "Turksinseln",
    "Turkinseln": "Turksinseln",
    "Blühende Wirtschaft": "Blütezeit",
    "Kraweel": "（无对应，德语无此词）",
    "Anheuerung": "anheuern（动词）",
}
# 状态下降口径（八档定案 sunk）
STATUS_BAD = re.compile(r"Status (?:fällt|gefallen|fiel)")
# 名词化/官僚腔 token（风格提示，不阻断）
STYLE = {
    "zur Verfügung": "改用 schenken / haben / geben",
    "verfügt über": "改用 hat",
    "verfügen über": "改用 haben",
    "verstrickt": "改用 im Krieg stehen 一类",
    "besteht darin, ": "目标句改 Zuerst sollt Ihr …",
    "Euer nächstes Ziel ist es": "改 Als Nächstes sollt Ihr …",
    "Euer erstes Ziel ist es": "改 Zuerst sollt Ihr …",
    "Die Aufgabe besteht darin": "改动词句",
    "gewährleisten": "改具体动词（bringen/sichern）",
    "erfolgt ": "改具体动词",
    "harren": "改 warten",
    "harret": "改 wartet",
}
# 占位与标记
PH = re.compile(r"@[A-Za-z]+\$[^$]*\$|%\d+")
TAGS = ("<ts:", "<f:fonts/", "<gs:", "<g:", "<c>", "<n>", "<t>", "<n:")
DU_PRONOUN = re.compile(r"(?<![A-Za-zÄÖÜäöüß])(du|dich|dir|dein|deine|deinem|deinen|deiner)(?![A-Za-zÄÖÜäöüß])")
SENT_SPLIT = re.compile(r"(?:<n>|<t>|\. |\? |! |: )")

E, W = [], []


def add(level, code, key, detail):
    (E if level == "E" else W).append({"level": level, "code": code, "key": key, "detail": detail})


def check_tags(key, en, de):
    # 占位集合
    if set(PH.findall(en)) != set(PH.findall(de)):
        add("E", "L1-占位", key, f"EN {sorted(PH.findall(en))} / DE {sorted(PH.findall(de))}")
    # 标记个数（<n>/<t>/<ts:>/<f:> 顺序敏感，按出现顺序比对名称）
    for tag in TAGS:
        a, b = en.count(tag), de.count(tag)
        if a != b:
            add("E", "L1-标记", key, f"{tag} EN {a} / DE {b}")


def check_register(key, de):
    # 句首 du-命令式
    for seg in SENT_SPLIT.split(de):
        s = seg.strip(" \t\n\u00a0-–—")
        if not s:
            continue
        word = s.split(" ")[0].strip(",.;:!?")
        if word in DU_IMPERATIVE:
            add("E", "L2-敬称命令式", key, f"{word} …（应为 Ihr 敬称形）")
    # 引号外的 du 系列
    outside = re.sub(r"„[^“]*“|\"[^\"]*\"", "", de)
    m = DU_PRONOUN.search(outside)
    if m:
        add("W", "L2-du 人称", key, f"{m.group(1)} 出现在引号外")


def check_terms(key, de):
    for bad, good in BANNED.items():
        if bad in de:
            add("E", "L3-禁用变体", key, f"{bad} → {good}")
    m = STATUS_BAD.search(de)
    if m:
        add("E", "L4-状态动词", key, f"{m.group(0)} → sinkt")
    for token, hint in STYLE.items():
        pattern = r"(?<![A-Za-zÄÖÜäöüß])" + re.escape(token.strip()) + r"(?![A-Za-zÄÖÜäöüß])"
        if re.search(pattern, de):
            add("W", "L5-风格", key, f"{token}：{hint}")


ABBR = {"z", "u", "d", "o", "v", "k", "Nr", "Jh", "Abb", "Bd", "St", "etc", "usw", "ca", "bzw",
        "Mio", "Mrd", "resp", "inkl", "zzgl", "evtl"}


def check_punct(key, de, en):
    if de.count("„") != de.count("“"):
        add("E", "L6-引号", key, f"„ {de.count('„')} / “ {de.count('“')}")
    # 双空格 / 标签前空格：英文本身也这样写的不算
    if "  " in de and "  " not in en:
        add("W", "L6-双空格", key, "连续空格（英文无）")
    if " <" in de and " <" not in en:
        add("W", "L6-标签前空格", key, "空格后紧跟 <")

    # 按 <n> 分段比对：只在英文该段有句末标点、德语没有时提示
    a_seg, b_seg = en.split("<n>"), de.split("<n>")
    if len(a_seg) == len(b_seg):
        for i, (sa, sb) in enumerate(zip(a_seg, b_seg)):
            sa_s, sb_s = sa.strip(), sb.strip()
            if not sa_s or not sb_s:
                continue
            if sa_s[-1] in ".!?:…" and sb_s[-1] not in ".!?:…>”\"'”":
                add("W", "L6-句末标点", key, f"第{i + 1}段 EN 有句末标点、DE 无 → …{sb_s[-26:]}")
            prev_ends_comma = i > 0 and b_seg[i - 1].strip().endswith(",")
            if not prev_ends_comma and re.match(r"[A-ZÄÖÜ]", sa_s) and re.match(r"[a-zäöüß]", sb_s):
                add("W", "L7-句首小写", key, f"第{i + 1}段 → {sb_s[:24]}")

    # 句中「. 」后小写：排除缩写
    for m in re.finditer(r"([A-Za-zÄÖÜäöüß]{4,})\. ([a-zäöüß])", de):
        if m.group(1) in ABBR or re.fullmatch(r"[IVXLCDM]{1,7}", m.group(1)):
            continue
        add("W", "L7-句首小写", key, de[m.start():m.start() + 28])


HARD_DUP = {"und", "ist", "nicht", "in", "zu", "von", "mit", "auf", "dass", "wenn", "oder"}


def check_dup(key, de):
    for m in re.finditer(r"(?<![A-Za-zÄÖÜäöüß])(\w+)\s+\1(?![A-Za-zÄÖÜäöüß])", de):
        w = m.group(1).lower()
        if w in HARD_DUP:
            add("E", "L8-叠词", key, m.group(0))
        # 冠词/关系代词相邻（die, die …）是正常德语，不报


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="build/qa/de_lint.json")
    ap.add_argument("--md", default="docs/德语校对清单.md")
    args = ap.parse_args()

    en = tomllib.loads(EN.read_text(encoding="utf-8"))
    de = tomllib.loads(DE.read_text(encoding="utf-8"))
    missing = [k for k in en if k not in de]
    for k in missing:
        add("E", "L0-缺条", k, "基准有、译文无")

    for k, env in en.items():
        if k not in de:
            continue
        dv = de[k]
        check_tags(k, env, dv)
        check_register(k, dv)
        check_terms(k, dv)
        check_punct(k, dv, env)
        check_dup(k, dv)

    by_code = {}
    for it in E + W:
        by_code.setdefault(it["code"], 0)
        by_code[it["code"]] += 1

    print(f"条目 {len(de)} 条；E 级 {len(E)} 条，W 级 {len(W)} 条")
    for code, n in sorted(by_code.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {code}: {n}")

    payload = {
        "total": len(de),
        "errors": E,
        "warnings": W,
        "counts": by_code,
    }
    jp = ROOT / args.json
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# 德语校对清单（de_lint.py 自动生成）", "",
             f"条目 {len(de)} 条｜E 级 {len(E)} 条｜W 级 {len(W)} 条", "",
             "E 级为确定性问题（占位/标记/敬称/禁用变体/叠词/引号），需改；W 级为风格提示，可判读后保留。", ""]
    cur = None
    for it in E + W:
        if it["code"] != cur:
            cur = it["code"]
            lines += ["", f"## {cur}", "", "| 级别 | 条目 | 命中 |", "|---|---|---|"]
        detail = it["detail"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {it['level']} | `{it['key']}` | {detail} |")
    mp = ROOT / args.md
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"写出 {args.json} / {args.md}")
    return 1 if E else 0


if __name__ == "__main__":
    sys.exit(main())
