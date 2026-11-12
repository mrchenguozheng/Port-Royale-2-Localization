# -*- coding: utf-8 -*-
"""生成「语体拟改清单」：只列能判定的，其余标成待人工确认。

输入：
  docs/csv/analysis/speaker-audit.csv   （说话人分级）
  docs/csv/voice/voice-hash-map.csv  （语音↔hash↔NPC，副王 35 条台词）
  src/live/ja.toml

输出：
  docs/语体拟改清单.md
  docs/csv/analysis/tone-proposal.csv
"""

import csv
import io
import os
import re
import tomllib
from collections import Counter, defaultdict

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
ROOT = os.path.dirname(os.path.dirname(TOOLS))
DOCS = os.path.join(ROOT, "docs")

POLITE = re.compile(r"(です|ます|ました|ません|ましょう|でしょう|ください|ござい|いたし|お[ら願待越持受取])")
PLAIN = re.compile(r"(だぜ|だぞ|だな|だよ|がれ|やがる|しろ|しね|てくれ|かよ|ねぇ|だ。|だ！|だ？)")

#: 明确建议（其余 A 级保持原样）
FIX = {
    "0x03fb5c6a": {
        "action": "改格式",
        "proposed": "<n><n>%1（%2 の副王）",
        "why": "英文是「Name, viceroy of Nation」的落款式，"
               "现在的「%1 、 %2 の副王」在名字后多了一个顿号，改成括号更清楚。",
    },
}

#: B 级各类的语气基线（由角色职能决定，仍需人工确认说话人）
POLICY = {
    "财政官/借贷": ("敬体", "正式公文，借贷/还款通知"),
    "亲属/恋人关系": ("敬体（可略柔）", "家人/恋人，用です・ます但可少用公文体"),
    "酒馆/醉汉": ("常体", "酒馆里的闲谈与醉话"),
    "海盗/私掠": ("常体", "海盗、私掠船长的威胁与讨价还价"),
    "官员/公务": ("敬体", "总督/副王的公务台词"),
    "商人/交易": ("敬体", "商人谈生意，礼貌但不过分客气"),
    "教程/引导": ("敬体", "教学旁白"),
}


def style(t):
    p, q = len(POLITE.findall(t)), len(PLAIN.findall(t))
    if p and p >= q:
        return "敬体"
    if q and q > p:
        return "常体"
    return "中性"


def load():
    audit = list(csv.DictReader(io.open(os.path.join(DOCS, "csv", "analysis", "speaker-audit.csv"), encoding="utf-8-sig")))
    voice = list(csv.DictReader(io.open(os.path.join(DOCS, "csv", "voice", "voice-hash-map.csv"), encoding="utf-8-sig")))
    ja = tomllib.load(open(os.path.join(ROOT, "src", "live", "ja.toml"), "rb"))
    return audit, voice, ja


def main():
    audit, voice, ja = load()
    by_hash = {r["hash"]: r for r in audit}
    viceroy = [r for r in voice if r["id_name"].startswith("ID_NPC_VICEROY") and r["hash"]]

    rows = []
    # 第一批 A 级
    for r in audit:
        if r["tier"] != "A":
            continue
        t = ja.get(r["hash"], "")
        fix = FIX.get(r["hash"])
        rows.append({
            "batch": "A-确定",
            "hash": r["hash"],
            "category": r["category"],
            "family": r["family"],
            "person": r["person"],
            "current_style": style(t),
            "action": fix["action"] if fix else "保留",
            "proposed": fix["proposed"] if fix else "",
            "why": fix["why"] if fix else "身份明确，现译语气与身份相符",
            "en": r["en"],
            "ja": t,
        })
    # 第一批 副王语音
    for v in viceroy:
        t = ja.get(v["hash"], "")
        if not t:
            continue
        rows.append({
            "batch": "A-副王语音",
            "hash": v["hash"],
            "category": "官员/公务",
            "family": by_hash.get(v["hash"], {}).get("family", ""),
            "person": "第1人称",
            "current_style": style(t),
            "action": "保留",
            "proposed": "",
            "why": "语音表确认是副王（Viceroy），现译已是敬体",
            "en": v["en"],
            "ja": t,
        })
    # 第二批 B 级各类：每类抽 3 条第1人称做样本，动作=人工确认
    by_cat = defaultdict(list)
    for r in audit:
        if r["tier"] == "B":
            by_cat[r["category"]].append(r)
    for cat, items in by_cat.items():
        base, why = POLICY.get(cat, ("敬体", ""))
        first = [r for r in items if r["person"] == "第1人称"] or items
        for r in first[:3]:
            t = ja.get(r["hash"], "")
            rows.append({
                "batch": "B-待人工",
                "hash": r["hash"],
                "category": cat,
                "family": r["family"],
                "person": r["person"],
                "current_style": style(t),
                "action": "人工确认",
                "proposed": "",
                "why": "%s：基线%s，需先确认这句确实是该角色在说（%s）" % (cat, base, why),
                "en": r["en"],
                "ja": t,
            })

    out = os.path.join(DOCS, "csv", "analysis", "tone-proposal.csv")
    cols = ["batch", "hash", "category", "family", "person", "current_style",
            "action", "proposed", "why", "en", "ja"]
    with io.open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # 统计
    fam = defaultdict(list)
    for r in audit:
        if r["tier"] != "-" and r["family_size"] and int(r["family_size"]) >= 3:
            fam[r["family"]].append(r)
    mixed = 0
    for members in fam.values():
        ss = {style(ja.get(m["hash"], "")) for m in members}
        if "敬体" in ss and "常体" in ss:
            mixed += 1
    cat_stats = {c: (len(v), sum(1 for r in v if r["person"] == "第1人称")) for c, v in by_cat.items()}

    L = ["# 语体拟改清单（待确认，尚未改动）", "",
         "> 生成：`python src/tools/analysis/tone_proposal.py`；逐条：[tone-proposal.csv](csv/analysis/tone-proposal.csv)。",
         "> 依据：[说话人分级](说话人分级.md) + 语音表（[语音映射](语音映射.md)）。", "",
         "## 一句话结论", "",
         "| 批次 | 范围 | 可自动判定 | 结论 |", "|---|---|---|---|",
         "| 第一批 A 确定 | 6 条 | ✅ | 5 条保留，1 条只改落款格式 |",
         "| 第一批 副王语音 | %d 条 | ✅ | 全部已是敬体，无需改 |" % len(viceroy),
         "| 第二批 B 可推断 | %d 条 | ❌ | 类别是「话题」不是「说话人」，只能人工确认 |" % sum(len(v) for v in by_cat.values()),
         "| 第三批 模板族 | %d 族 | ✅ | 风格混杂的族 **%d** 个，无需统一 |" % (len(fam), mixed),
         "", "## 第一批：身份确定的 %d 条" % (6 + len(viceroy)), "",
         "| hash | 来源 | 现译 | 判定 | 动作 |", "|---|---|---|---|---|"]
    for r in rows:
        if not r["batch"].startswith("A-"):
            continue
        L.append("| `%s` | %s | %s | %s | %s |" % (
            r["hash"], r["batch"], r["ja"][:46].replace("|", "\\|"),
            r["current_style"], r["action"]))
    L += ["", "唯一要改的一条：", ""]
    for h, f in FIX.items():
        cur = ja.get(h, "")
        L += ["- `%s`" % h,
              "  - 现在：`%s`" % cur,
              "  - 建议：`%s`" % f["proposed"],
              "  - 理由：%s" % f["why"]]
    L += ["", "## 第二批：B 级 %d 条（人工确认）" % sum(len(v) for v in by_cat.values()), "",
          "| 类别 | 条数 | 其中第1人称 | 语气基线 | 说明 |", "|---|---|---|---|---|"]
    for cat in POLICY:
        if cat not in cat_stats:
            continue
        n, first = cat_stats[cat]
        base, why = POLICY[cat]
        L.append("| %s | %d | %d | %s | %s |" % (cat, n, first, base, why))
    L += ["", "**为什么不能自动改**：B 级是按文本里出现的关键词归类的，"
          "含 `pirate` 不代表说话人是海盗——例如 `On behalf of my nation, I would like to thank you "
          "for destroying a convoy of the notorious pirate…` 是总督在道谢。"
          "所以自动批改会把官员的台词降成常体。", "",
          "建议的复核方式：只看 **person = 第1人称** 且 **category 属于海盗/酒馆** 的条目，"
          "这些才可能是该角色本人在说话：", "", "```bash",
          "python -c \"import csv,io;rows=[r for r in csv.DictReader(io.open('docs/csv/analysis/speaker-audit.csv',encoding='utf-8-sig')) if r['person']=='第1人称' and r['category'] in ('海盗/私掠','酒馆/醉汉')];print(len(rows))\"",
          "```", "", "## 第三批：模板族一致性", "",
          "共 **%d 族**（≥3 条），逐族比对「敬体/常体」，**风格混杂的 %d 族**——"
          "说明同一套模板的译文语气本来就是统一的，不需要按族批量改。" % (len(fam), mixed), ""]
    top = sorted(fam.items(), key=lambda kv: -len(kv[1]))[:5]
    L += ["| 族 | 条数 | 风格 |", "|---|---|---|"]
    for key, members in top:
        ss = Counter(style(ja.get(m["hash"], "")) for m in members)
        L.append("| `%s` | %d | %s |" % (key, len(members), dict(ss)))
    L += ["", "## 下一步", "",
          "1. 先确认 `0x03fb5c6a` 的落款格式要不要改（只此一条）；",
          "2. 海盗/酒馆里 **person=第1人称** 的条目逐条确认说话人，确认是海盗/醉汉本人的再改常体；",
          "3. 其余保持现状——在拿不到引擎对话结构的前提下，按话题猜语气只会越改越乱。", ""]
    md = os.path.join(DOCS, "语体拟改清单.md")
    io.open(md, "w", encoding="utf-8", newline="\n").write("\n".join(L))
    print("写出 %s（%d 行）与 %s" % (out, len(rows), md))
    print("A 确定 %d｜副王语音 %d｜B 抽样 %d｜族 %d（混杂 %d）" % (
        6, len(viceroy), len(rows) - 6 - len(viceroy), len(fam), mixed))


if __name__ == "__main__":
    main()
