# -*- coding: utf-8 -*-
"""把 3548 条文本按「能不能判断说话人身份」分级，输出清单。

生成：
  docs/说话人分级.md      —— 方法、统计、分级示例、语体待查清单
  docs/speaker-audit.csv —— 逐条明细（hash/tier/category/evidence/flag/en/ja）

分级：
  A 确定   —— 文本自己交代了身份（信件落款、自称、亲属/恋人称呼）
  B 可推断 —— 有强线索词，能归到某一类说话人（公务/商人/海盗/财政官/酒馆/教程）
  C 弱推断 —— 只能看出是「任务委托/感谢」，分不清是谁
  N 无说话人 —— 系统提示、界面文案、事件旁白
"""

import csv
import io
import os
import re
import tomllib
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRANS = os.path.join(ROOT, "src", "translations")
REF = os.path.join(TRANS, "references")
DOCS = os.path.join(ROOT, "docs")

# ---------------------------------------------------------------- 分级规则
A_SIGNATURE = re.compile(
    r"(The\s+)?(Treasurer|Governor|Viceroy)\s+of\s+%\d"
    r"|%\d\s*%\d,\s*(Governor|Viceroy|Treasurer)\s+of\s+%\d",
    re.I,
)
A_SELFPROCLAIM = re.compile(
    r"\bI am (the |a )?(Governor|Viceroy|treasurer|harbor master|mayor)\b"
    r"|\bmy name is\b",
    re.I,
)
A_FAMILY = re.compile(
    r"\bmy (darling|beloved daughter|dear friend|wife|husband|father|mother"
    r"|sister|brother-in-law|daughter)\b",
    re.I,
)

N_SYSTEM = re.compile(
    r"\b(click|right-click|left-click|button|menu|window|screen|toolbar"
    r"|press|hotkey|Scenario objective|Event window|tab)\b",
    re.I,
)
N_NARRATION = re.compile(
    r"^(Today\b|The pirate\b|The %\d buccaneer\b|A military convoy\b|A transport convoy\b"
    r"|A storm\b|A trade route\b|Natives\b|Famine\b|Plague\b|Gold discovered\b"
    r"|You have\b|You were\b|You cannot\b|You can\b|You must\b|Your convoy\b"
    r"|Your ships\b|Convoy %\w|Unfortunately\b|Congratulations\b|Well done\b"
    r"|Excellent\b|Sorry\b|I see you\b|I hear\b|I am afraid\b)",
)
N_PAST3 = re.compile(
    r"\b(has|have) (destroyed|broken through|attacked|looted|sunk|captured)\b", re.I)

B_RULES = [
    ("财政官/借贷", re.compile(
        r"\b(loan|loans|repay\w*|debt\w*|interest|instalment|credit)\b", re.I)),
    ("恋人/家人", re.compile(
        r"\b(my dear|my darling|my beloved|my wife|my husband|my daughter|my father"
        r"|my sister|my brother-in-law|wedding|marriage|betroth\w*)\b", re.I)),
    ("酒馆/醉汉", re.compile(r"\b(rum|drunkard\w*|inn|inns|tavern|bottle)\b", re.I)),
    ("海盗/私掠", re.compile(
        r"\b(pirate\w*|buccaneer\w*|Blackbeard|hideout\w*|booty|privateer\w*"
        r"|Letter of Marque|Letters of Marque)\b", re.I)),
    ("总督/公务", re.compile(
        r"\b(Governor|Viceroy|viceroy|building permit|nation|nations|war|peace treaty"
        r"|town council|reputation|rank)\b", re.I)),
    ("商人/交易", re.compile(
        r"\b(deliver\w*|barrel\w*|market\w*|price\w*|goods|warehouse\w*|trade route"
        r"|convoy\w*|cargo|profit\w*|export\w*|import\w*)\b", re.I)),
    ("教程/引导", re.compile(
        r"\b(you should|you can now|your task|your mission|objective|hint)\b", re.I)),
]

#: 真正的「超出原文礼数」：谦让语/美化语。おめでとうございます 这类系统祝贺不算。
POLITE = re.compile(r"差し上げ|お(受け取り|持ち|越し)|申し上げ|いたします")

ORDER = ["信件署名", "自称身份", "亲属/恋人称呼", "财政官/借贷", "恋人/家人",
         "酒馆/醉汉", "海盗/私掠", "总督/公务", "商人/交易", "教程/引导",
         "事件旁白", "界面/系统", "通用委托/应答"]


def classify(en, ja):
    if A_SIGNATURE.search(en):
        return "A", "信件署名", "落款：" + A_SIGNATURE.search(en).group(0)[:40]
    if A_SELFPROCLAIM.search(en):
        return "A", "自称身份", "自称：" + A_SELFPROCLAIM.search(en).group(0)[:40]
    if A_FAMILY.search(en):
        return "A", "亲属/恋人称呼", "称呼：" + A_FAMILY.search(en).group(0)[:40]
    if N_SYSTEM.search(en):
        return "N", "界面/系统", "界面词：" + N_SYSTEM.search(en).group(0)
    if N_NARRATION.search(en) or N_PAST3.search(en):
        return "N", "事件旁白", "第三人称通报"
    for name, rx in B_RULES:
        m = rx.search(en)
        if m:
            return "B", name, "线索词：" + m.group(0)
    return "C", "通用委托/应答", "无线索"


def build_rows():
    en = tomllib.load(open(os.path.join(REF, "en.gog_1.1.2.3.toml"), "rb"))
    ja = tomllib.load(open(os.path.join(TRANS, "ja.toml"), "rb"))
    try:
        keep_doc = tomllib.load(open(os.path.join(TRANS, "keep_original.toml"), "rb"))
        keep = {k for v in keep_doc.values() for k in (v.get("ids") or [])}
    except FileNotFoundError:
        keep = set()

    rows = []
    for k in ja:
        e = (en.get(k) or "").strip()
        j = ja[k].strip()
        tier, cat, why = classify(e, j)
        flag = ""
        if POLITE.search(j) and not e.startswith("Congratulations"):
            flag = "谦让/美化语超出原文（建议平实化）"
        rows.append({"hash": k, "tier": tier, "category": cat, "evidence": why,
                     "flag": flag, "keep": "是" if k in keep else "", "en": e, "ja": j})
    return rows


def write_csv(rows):
    os.makedirs(DOCS, exist_ok=True)
    path = os.path.join(DOCS, "speaker-audit.csv")
    key = lambda r: (r["tier"], ORDER.index(r["category"]) if r["category"] in ORDER else 99,
                     r["hash"])
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["hash", "tier", "category", "evidence",
                                           "flag", "keep", "en", "ja"])
        w.writeheader()
        w.writerows(sorted(rows, key=key))
    return path


def write_md(rows):
    A = [r for r in rows if r["tier"] == "A"]
    B = [r for r in rows if r["tier"] == "B"]
    C = [r for r in rows if r["tier"] == "C"]
    N = [r for r in rows if r["tier"] == "N"]
    flags = [r for r in rows if r["flag"]]

    L = []
    L.append("# 说话人 / 语气 分级清单")
    L.append("")
    L.append("> 自动生成：`python src/tools/speaker_audit.py`。"
             "逐条明细：[speaker-audit.csv](speaker-audit.csv)。")
    L.append("")
    L.append("这个清单回答一个问题：**从文本本身，能不能判断这句话是谁说的？**")
    L.append("")
    L.append("语言包里只有 `hash = 文本`，没有 speaker 字段；同一个 hash 由哪个 NPC 调用，"
             "在包文件里看不出来。所以按「文本能否自证身份」分成四级。")
    L.append("")
    L.append("> 判定只依据**英语**与**法语**原文——这两个版本是权威文本。"
             "荷兰语/西班牙语语音只用于核对同一句的发音，德语旁白没有权威文本，都不作为判定依据。")
    L.append("")
    L.append("**日语不参与对照**：日语是我们自己译的，用它反推说话人等于循环论证；"
             "本清单的示例一律用英语原文。")
    L.append("")
    L.append("## 总览")
    L.append("")
    L.append("| 级别 | 含义 | 条数 |")
    L.append("|---|---|---|")
    L.append("| **A 确定** | 文本自己交代了身份（落款、自称、亲属/恋人称呼） | %d |" % len(A))
    L.append("| **B 可推断** | 有强线索词，能归到某一类说话人 | %d |" % len(B))
    L.append("| **C 弱推断** | 只看出是「委托/应答/感谢」，分不清是谁 | %d |" % len(C))
    L.append("| **N 无说话人** | 界面文案、系统提示、事件旁白 | %d |" % len(N))
    L.append("| 合计 | | %d |" % len(rows))
    L.append("")
    L.append("## 类别 × 级别")
    L.append("")
    L.append("| 类别 | A | B | C | N | 合计 |")
    L.append("|---|---|---|---|---|---|")
    for c in ORDER:
        sub = [r for r in rows if r["category"] == c]
        if not sub:
            continue
        cnt = Counter(r["tier"] for r in sub)
        L.append("| %s | %d | %d | %d | %d | %d |" % (
            c, cnt["A"], cnt["B"], cnt["C"], cnt["N"], len(sub)))
    L.append("")
    L.append("## A 级：能确定说话人（%d 条）" % len(A))
    L.append("")
    L.append("这些要么带落款，要么自称职务，要么有只可能出自某个关系人之口的称呼。")
    L.append("")
    for r in A:
        L.append("- `%s`（%s，%s）" % (r["hash"], r["category"], r["evidence"]))
        L.append("  - EN: %s" % r["en"][:150])
    L.append("")
    L.append("## B 级：能推断类别（%d 条）" % len(B))
    L.append("")
    L.append("有强线索词，能判断**这段话在谈什么**（场景/话题），"
             "但不等于说话人就是那个角色 —— 例如「海盗」类里，"
             "很多是总督在感谢你打掉海盗。判断语气时请把这一层区别记住。")
    L.append("")
    for c in ORDER:
        sub = [r for r in B if r["category"] == c]
        if not sub:
            continue
        L.append("### %s（%d 条）" % (c, len(sub)))
        L.append("")
        for r in sub[:4]:
            L.append("- `%s`（%s）" % (r["hash"], r["evidence"]))
            L.append("  - EN: %s" % r["en"][:130])
        L.append("")
    L.append("## N 级：没有说话人（%d 条）" % len(N))
    L.append("")
    L.append("界面文案、系统提示、事件通报。不要按「对某人说话」来写："
             "提示用中性语气，事件通报用第三人称过去时。")
    L.append("")
    for r in N[:6]:
        L.append("- `%s`（%s，%s）" % (r["hash"], r["category"], r["evidence"]))
        L.append("  - EN: %s" % r["en"][:130])
    L.append("")
    L.append("## C 级：无法判定（%d 条）" % len(C))
    L.append("")
    L.append("占大头：通用委托、感谢、奖励、条件说明，被多个角色复用。"
             "只能按「公务/任务」的通用语体写，别绑定具体身份。")
    L.append("")
    for r in C[:6]:
        L.append("- `%s`" % r["hash"])
        L.append("  - EN: %s" % r["en"][:130])
    L.append("")
    L.append("## 怎么用")
    L.append("")
    L.append("1. 调语气先看 **A 级**：身份明确，按身份定敬体/常体；")
    L.append("2. **B 级**按类别定基调：公务=です・ます，海盗/酒馆=常体，财政官=公文化；")
    L.append("3. **N 级**一律中性，不出现对玩家的直接请求；")
    L.append("4. **C 级**保持通用与克制，别加原文没有的敬语修饰。")
    L.append("")
    L.append("## 局限")
    L.append("")
    L.append("- 规则是启发式的，一条文本可能命中多个类别，取优先级最高者；")
    L.append("- 「亲属/恋人称呼」能确定说话人与玩家的关系，确定不了具体是哪位 NPC；")
    L.append("- 通用奖励/感谢文案被多个角色复用，任何「确定说话人」的判断都不成立；")
    L.append("- 要从资源层面拿到真正的说话人，需要解析引擎的对话结构（不在语言包里）。")
    L.append("")

    path = os.path.join(DOCS, "说话人分级.md")
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(L))
    return path


def main():
    rows = build_rows()
    csv_path = write_csv(rows)
    md_path = write_md(rows)
    tiers = Counter(r["tier"] for r in rows)
    cats = Counter(r["category"] for r in rows)
    print("条目 %d｜A %d｜B %d｜C %d｜N %d｜语体待查 %d" % (
        len(rows), tiers["A"], tiers["B"], tiers["C"], tiers["N"],
        sum(1 for r in rows if r["flag"])))
    for c, n in cats.most_common():
        print("  %-14s %d" % (c, n))
    print("已写出：", os.path.relpath(md_path, ROOT), "、", os.path.relpath(csv_path, ROOT))


if __name__ == "__main__":
    main()
