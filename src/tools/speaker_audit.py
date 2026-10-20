# -*- coding: utf-8 -*-
"""按「能不能判断说话人」给 3,548 条文本分级，只依据英语/法语原文。

输出：
  docs/说话人分级.md       —— 方法、统计、分级示例
  docs/speaker-audit.csv   —— 逐条：hash / 级别 / 类别 / 规则 / 人称 / 英文 / 法文

分级（2026-10-21 收紧定义）：
  A 确定   —— 文本直接写明身份：落款、自称、头衔标签
  B 可推断 —— 由内容可推断说话人的角色或与玩家的关系
  C 通用   —— 只有第一人称或祈使，没有任何角色线索
  N 无说话人 —— 系统界面、第三人称事件旁白

注意：
  * 日语不参与判定——日语是我们自己译的，用它反推说话人是循环论证；
  * 「提到亲属」不等于「说话人是亲属」，旧版把两者混为一谈，导致 41 条误判为 A。
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

# ---------------------------------------------------------------- 规则
#: 落款必须落在文本末尾（允许结尾空白），否则正文里的「viceroy of %1」会被误判
A_SIGNATURE = re.compile(r"(The\s+)?(Treasurer|Governor|Viceroy)\s+of\s+%\d\s*$", re.I)
A_SIGNATURE2 = re.compile(r"%\d\s*%\d,\s*(Governor|Viceroy|Treasurer)\s+of\s+%\d\s*$", re.I)
A_SELF = re.compile(r"\bmy name is\b|\bI am (the |a )?(Governor|Viceroy|treasurer|harbor master)\b", re.I)
A_LABEL = re.compile(r"^(<n>)*\s*(%\d,?\s*)?(Viceroy|Governor|Treasurer)\s+of\s+%\d\s*$", re.I)

N_SYSTEM = re.compile(
    r"\b(click|right-click|left-click|button|menu|window|toolbar|press|hotkey"
    r"|Scenario objective|Event window|tab)\b", re.I)
N_NARRATION = re.compile(
    r"^(Today\b|The pirate\b|The %\d buccaneer\b|A military convoy\b|A transport convoy\b"
    r"|A storm\b|A trade route\b|Natives\b|Famine\b|Plague\b|Gold discovered\b"
    r"|You have\b|You were\b|You cannot\b|You can\b|You must\b|Your convoy\b"
    r"|Your ships\b|Convoy %\w|Unfortunately\b|Congratulations\b|Well done\b"
    r"|Excellent\b|Sorry\b|While you\b)")
N_PAST3 = re.compile(r"\b(has|have)\s+(destroyed|broken through|attacked|looted|sunk|captured"
                     r"|been dismissed|moved)\b", re.I)

B_RULES = [
    ("财政官/借贷", re.compile(r"\b(loan|loans|repay\w*|debt\w*|interest|instalment)\b", re.I)),
    ("亲属/恋人关系", re.compile(
        r"\b(my (wife|husband|daughter|son|father|mother|sister|brother-in-law|darling"
        r"|beloved|dear friend))\b", re.I)),
    ("酒馆/醉汉", re.compile(r"\b(rum|drunkard\w*|inn|inns|tavern)\b", re.I)),
    ("海盗/私掠", re.compile(
        r"\b(pirate\w*|buccaneer\w*|Blackbeard|hideout\w*|privateer\w*"
        r"|Letter of Marque|Letters of Marque)\b", re.I)),
    ("官员/公务", re.compile(
        r"\b(Governor|Viceroy|viceroy|building permit|peace treaty|town council"
        r"|reputation|rank)\b", re.I)),
    ("商人/交易", re.compile(
        r"\b(deliver\w*|barrel\w*|market\w*|price\w*|goods|warehouse\w*|trade route"
        r"|cargo|profit\w*|import\w*|export\w*)\b", re.I)),
    ("教程/引导", re.compile(r"\b(you should|you can now|your task|your mission|objective|hint)\b", re.I)),
]

IMPERATIVE = re.compile(
    r"^(Deliver|Go|Attack|Destroy|Capture|Find|Search|Bring|Take|Visit|Build|Construct"
    r"|Buy|Sell|Hire|Return|Report|Pay|Set|Keep|Look|Use|Select|Click|Wait|Speak|Sail)\b")
FIRST_PERSON = re.compile(r"\b(I|my|me|we|our|us|I'm|I'd|I'll)\b")

ORDER = ["落款", "自称", "头衔标签", "财政官/借贷", "亲属/恋人关系", "酒馆/醉汉",
         "海盗/私掠", "官员/公务", "商人/交易", "教程/引导", "事件旁白", "系统界面", "通用对白"]


def person(en):
    t = re.sub(r"<[^>]*>", " ", en).strip()
    if N_PAST3.search(t) or t.startswith("Today"):
        return "第3人称"
    if IMPERATIVE.match(t):
        return "祈使"
    if FIRST_PERSON.search(t):
        return "第1人称"
    return "无"


def classify(en):
    e = en.strip()
    # A：落款必须在结尾附近，否则正文里的「viceroy of %1」会被误判
    tail = e[-90:]
    if len(e) > 60 and (A_SIGNATURE.search(tail) or A_SIGNATURE2.search(tail)):
        m = (A_SIGNATURE2.search(tail) or A_SIGNATURE.search(tail)).group(0)
        return "A", "落款", "A1", "结尾落款：" + m[:40]
    if A_LABEL.match(e):
        return "A", "头衔标签", "A2", "整句就是「头衔 + 地名」标签"
    if A_SELF.search(e):
        return "A", "自称", "A3", "自称：" + A_SELF.search(e).group(0)[:30]
    if N_SYSTEM.search(e):
        return "N", "系统界面", "N1", "界面词：" + N_SYSTEM.search(e).group(0)
    if N_NARRATION.search(e) or N_PAST3.search(e):
        return "N", "事件旁白", "N2", "第三人称通报"
    for name, rx in B_RULES:
        m = rx.search(e)
        if m:
            return "B", name, "B", "线索词：" + m.group(0)
    return "C", "通用对白", "C", "只有人称/祈使，无角色线索"


def load():
    en = tomllib.load(open(os.path.join(REF, "en.gog_1.1.2.3.toml"), "rb"))
    fr = tomllib.load(open(os.path.join(REF, "fr.gog_1.1.2.42.toml"), "rb"))
    keep_doc = tomllib.load(open(os.path.join(TRANS, "keep_original.toml"), "rb"))
    keep = {k for v in keep_doc.values() for k in (v.get("ids") or [])}
    return en, fr, keep


def build_rows():
    en, fr, keep = load()
    rows = []
    for k, e in en.items():
        e = e.strip()
        tier, cat, rule, why = classify(e)
        rows.append({
            "hash": k,
            "tier": tier,
            "category": cat,
            "rule": rule,
            "person": person(e) if tier != "N" or cat == "事件旁白" else "无",
            "en": e,
            "fr": fr.get(k, "").strip(),
            "keep": "是" if k in keep else "",
            "evidence": why,
        })
    return rows


def write_csv(rows):
    path = os.path.join(DOCS, "speaker-audit.csv")
    key = lambda r: (r["tier"], ORDER.index(r["category"]) if r["category"] in ORDER else 99, r["hash"])
    cols = ["hash", "tier", "category", "rule", "person", "en", "fr", "keep", "evidence"]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(sorted(rows, key=key))
    return path


def write_md(rows):
    tiers = Counter(r["tier"] for r in rows)
    cats = Counter(r["category"] for r in rows)
    A = [r for r in rows if r["tier"] == "A"]

    L = ["# 说话人分级（只依据英/法原文）", "",
         "> 自动生成：`python src/tools/speaker_audit.py`。逐条明细：[speaker-audit.csv](speaker-audit.csv)。",
         "> 判定只使用**英语**和**法语**原文。日语是我们自己译的，用它反推说话人是循环论证，所以不参与。", "",
         "## 分级定义", "",
         "| 级别 | 含义 | 条数 |", "|---|---|---|",
         "| **A 确定** | 文本直接写明身份：落款、自称、头衔标签 | %d |" % tiers["A"],
         "| **B 可推断** | 由内容可推断说话人的角色或与玩家的关系 | %d |" % tiers["B"],
         "| **C 通用** | 只有第一人称/祈使，没有角色线索 | %d |" % tiers["C"],
         "| **N 无说话人** | 系统界面、第三人称事件旁白 | %d |" % tiers["N"],
         "| 合计 | | %d |" % len(rows), "",
         "## 上一版为什么显得乱", "",
         "| 问题 | 旧规则 | 现规则 |", "|---|---|---|",
         "| 把「提到亲属」当成「说话人是亲属」 | 出现 `my wife` / `my daughter` 就判 A 级，"
         "于是旁白 `While you are looting the town, a young woman comes running up…` 也被算成亲属 | "
         "改为 B 级「亲属/恋人关系」，只表示**可推断**关系，且另设 `person` 列标明是第几人称 |",
         "| 落款规则匹配到正文 | 全文搜索 `viceroy of %1`，"
         "事件通报 `The viceroy of %1 has moved to %2. Governor…` 被判成「信件署名」 | "
         "只在**结尾 90 字**内找落款，且要求文本足够长 |",
         "| CSV 带过期日语列 | 混入 `ja` 列，且换词后未同步（还显示 `総督代理`） | "
         "删掉日语列，改成英语 + 法语两列（法语是另一份权威文本） |",
         "| 没有可核查的依据 | 只有一句中文说明 | 新增 `rule`（A1/A2/A3/N1/N2/B/C）与 `person`（第1/第3人称/祈使/无） |",
         "", "## 类别分布", "",
         "| 类别 | 条数 |", "|---|---|"]
    for c in ORDER:
        if cats[c]:
            L.append("| %s | %d |" % (c, cats[c]))
    L += ["", "## A 级：文本自己写明身份（%d 条）" % len(A), "",
          "| hash | 类别 | 规则 | 英文原文 |", "|---|---|---|---|"]
    for r in A:
        L.append("| `%s` | %s | %s | %s |" % (r["hash"], r["category"], r["rule"],
                                              r["en"][:110].replace("|", "\\|")))
    L += ["", "## B 级样例（每类 3 条）", ""]
    for c in ORDER:
        sub = [r for r in rows if r["tier"] == "B" and r["category"] == c]
        if not sub:
            continue
        L.append("### %s（%d 条）" % (c, len(sub)))
        L.append("")
        for r in sub[:3]:
            L.append("- `%s`（%s）" % (r["hash"], r["person"]))
            L.append("  - EN: %s" % r["en"][:120])
            L.append("  - FR: %s" % r["fr"][:120])
        L.append("")
    L += ["## 局限", "",
          "- 规则是启发式的：一条文本可能命中多个类别，取优先级最高者；",
          "- B 级只表示「能推断角色」，不等于确定是哪位 NPC；",
          "- 通用委托/感谢/奖励文案被多个角色复用，无法确定说话人；",
          "- 要拿到真正的说话人，需要解析引擎的对话结构（语言包里没有）。", ""]
    path = os.path.join(DOCS, "说话人分级.md")
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(L))
    return path


def main():
    rows = build_rows()
    write_csv(rows)
    write_md(rows)
    tiers = Counter(r["tier"] for r in rows)
    cats = Counter(r["category"] for r in rows)
    print("条目 %d｜A %d｜B %d｜C %d｜N %d" % (len(rows), tiers["A"], tiers["B"], tiers["C"], tiers["N"]))
    for c, n in cats.most_common():
        print("  %-14s %d" % (c, n))
    print("人称分布：", dict(Counter(r["person"] for r in rows)))


if __name__ == "__main__":
    main()
