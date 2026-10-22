# -*- coding: utf-8 -*-
"""placeholder_roles.py —— 按 hash 记录「占位符之间的连接符」规则。

问题：编年史里 `%1 %2` 既可能是「等级 + 全名」（要空格），也可能是
「名 + 姓」（要 `・`）。用正则批量替换一定会在某一边出错。

做法：不猜整条，只针对「相邻的两个 %N 参数」逐条记录规则：

    src/live/placeholder_roles.toml
    ["0x338a357f"]
    pair = ["1", "2"]
    sep  = " "          # 等级 + 全名，用空格
    note = "等级 + 全名"

可用 --report 导出所有相邻参数对（含英文上下文与推断建议），
人工确认后写进上面的 toml；--check 校验，--fix 只改有明确规则的条目。

    python src/tools/placeholder_roles.py --report
    python src/tools/placeholder_roles.py --check
    python src/tools/placeholder_roles.py --fix
"""

import argparse
import csv
import io
import os
import re
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EN = os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")
RULES_DIR = os.path.join(ROOT, "src", "live", "placeholder_roles")


def lang_source(lang):
    """中文文本源在 orig/，其他语言在 live/。"""
    if lang == "zh":
        return os.path.join(ROOT, "src", "seed", "zh.toml")
    return os.path.join(ROOT, "src", "live", "%s.toml" % lang)


def rules_path(lang):
    return os.path.join(RULES_DIR, "%s.toml" % lang)


def report_path(lang):
    return os.path.join(ROOT, "docs", "csv", "analysis", "占位符语义.%s.csv" % lang)

PAIR = re.compile(r"%0?(\d+)([ \u3000・]*)(%0?(\d+))")
TITLES = ("Governor", "Captain", "Viceroy", "King", "Queen", "Prince",
          "Princess", "Lord", "Sir", "Mr", "Mrs", "Ms", "Dr", "Admiral",
          "General", "Colonel", "Major", "Lieutenant", "Father", "Brother",
          "Sister")


def suggest(en, a, b):
    """给一对相邻参数一个保守建议；不确定返回 (None, 说明)。"""
    s = en.strip()
    if (a, b) == ("1", "2"):
        if s.startswith("%1 %2 %3"):
            return " ", "等级 + 名（%3 才是姓）"
        if s.startswith("%1 %2 "):
            return " ", "等级 + 全名"
        for t in TITLES:
            if t + " %1 %2" in s:
                return "・", "头衔 + 名 + 姓"
    if (a, b) == ("2", "3") and s.startswith("%1 %2 %3"):
        return "・", "名 + 姓"
    return None, "上下文不足"


def rules(lang):
    """返回 {(hash, (a, b)): sep}。"""
    path = rules_path(lang)
    if not os.path.isfile(path):
        return {}
    try:
        data = tomllib.load(open(path, "rb"))
    except (OSError, ValueError):
        return {}
    out = {}
    for h, spec in data.items():
        for r in spec.get("rules", []):
            pair = tuple(str(x) for x in r.get("pair", []))
            if len(pair) == 2:
                out[(h.lower(), pair)] = r.get("sep")
    return out


def scan(lang):
    en = tomllib.load(open(EN, "rb"))
    zh = tomllib.load(open(lang_source(lang), "rb"))
    rows = []
    for h, text in zh.items():
        for m in PAIR.finditer(text):
            a, sep, _tok, b = m.group(1), m.group(2), m.group(3), m.group(4)
            hint_sep, why = suggest(en.get(h, ""), a, b)
            rows.append({"id": h, "pair": (a, b), "sep": sep,
                         "hint": hint_sep, "why": why,
                         "en": en.get(h, ""), "zh": text})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="zh", help="语言代码，默认 zh")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--fix", action="store_true")
    args = ap.parse_args()

    lang = args.lang
    rows = scan(lang)
    rl = rules(lang)

    if args.report:
        with io.open(report_path(lang), "w", encoding="utf-8-sig", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["hash", "参数", "当前连接符", "建议", "依据", "英文", "中文"])
            for r in rows:
                wr.writerow([r["id"], "%s-%s" % r["pair"], r["sep"],
                             r["hint"] or "", r["why"],
                             r["en"].replace("\n", " ")[:120],
                             r["zh"].replace("\n", " ")[:120]])
        print("已写", report_path(lang), "（%d 对相邻参数）" % len(rows))

    bad = []
    for r in rows:
        want = rl.get((r["id"].lower(), r["pair"]))
        if want is not None and r["sep"] != want:
            bad.append((r, want))

    if args.check or not (args.report or args.fix):
        for r, want in bad:
            print("%s  %%%s%s%%%s 现在是 %r，规则要求 %r"
                  % (r["id"], r["pair"][0], r["sep"] or "", r["pair"][1], r["sep"], want))
        print("\n与规则不符：%d 处（已记录规则 %d 条）" % (len(bad), len(rl)))

    if args.fix:
        ref_path = lang_source(lang)
        doc = tomllib.load(open(ref_path, "rb"))
        order = [m.group(1) for m in
                 (re.match(r'^"([^"]+)"\s*=', l) for l in io.open(ref_path, encoding="utf-8")) if m]
        head = []
        for ln in io.open(ref_path, encoding="utf-8"):
            if ln.startswith("#"):
                head.append(ln.rstrip("\n"))
            else:
                break
        changed = 0
        for r in rows:
            want = rl.get((r["id"].lower(), r["pair"]))
            if want is None or r["sep"] == want:
                continue
            text = doc[r["id"]]
            a, b = r["pair"]
            pat = re.compile(r"%%0?%s([ \u3000・]*)%%0?%s" % (a, b))
            new_text, n = pat.subn("%%%s%s%%%s" % (a, want, b), text, count=1)
            if n and new_text != text:
                doc[r["id"]] = new_text
                changed += 1

        def esc(t):
            return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        io.open(ref_path, "w", encoding="utf-8", newline="\n").write(
            "\n".join(head + ['"%s" = "%s"' % (k, esc(doc[k])) for k in order]) + "\n")
        print("按规则修正 %d 条；接着跑 apply_zh_rules.py。" % changed)


if __name__ == "__main__":
    main()
