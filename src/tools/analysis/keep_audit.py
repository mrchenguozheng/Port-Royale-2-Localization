#!/usr/bin/env python3
# coding: utf-8
"""keep_audit.py —— 「有意不译」清单对账。

为什么要有这个：进度统计只剩两种合法状态 —— **译了**，或者**登记为有意不译**。
值等于英文原文的条目里，有些是漏译（该干活），有些本来就不该翻（按键名、
`+++EMPTY+++`、`Dummy`、纯符号、资源标识、职员表）。混在一起算「待译」，
比例永远说不清，也没人分得清剩下的是哪种。

三道断言：

1. `src/data/keep_as_is/` 里登记的 id 必须在基准表里存在；
2. 登记项的值不许出现目标文字 —— 出现了就是「该翻的却登记成不译」；
3. 待译里**不含任何字母**的条目（纯符号/数字/空占位/资源标识）必须登记，
   否则它们会永久占着「待译」，且这类条目按规则永远译不了。

含字母但值等于英文原文的（人名、`Dummy`、`Only 1 left` 之类）只在报告里列出，
由人判断是漏译还是该登记 —— 机器不猜。

输出 `build/qa/keep_audit_<语言>.txt`；有第 1、2、3 类问题时返回非零。

    python src/tools/analysis/keep_audit.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for p in (os.path.join(ROOT, "src", "tools"), os.path.join(ROOT, "src"),
          os.path.join(ROOT, "src", "tools", "text"),
          os.path.join(ROOT, "src", "tools", "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)

import translate as T                     # noqa: E402
from text import lang_rules               # noqa: E402

QA_DIR = os.path.join(ROOT, "build", "qa")
LETTER = re.compile(r"[^\W\d_]")          # 任何一个 Unicode 字母（含汉字/西里尔）
EMPTY = "+++EMPTY+++"


def has_letter(value):
    return bool(LETTER.search(T.content_of(value)))


def is_resource_id(value):
    v = (value or "").strip()
    return v.startswith("IDM_") or (v.isupper() and "_" in v and len(v) >= 8)


def structural(value):
    """纯符号/数字/空占位/资源标识：按规则不可能翻译。"""
    v = (value or "").strip()
    if v == EMPTY or is_resource_id(v):
        return True
    return not has_letter(v)


def audit(lang, es, base_field):
    keep = T.keep_as_is(lang)
    by_id = {e["id"]: e for e in es}
    problems, notes = [], []

    for hid, why in sorted(keep.items()):
        e = by_id.get(hid)
        if e is None:
            problems.append("登记了基准表里没有的 id：%s（%s）" % (hid, why))
            continue
        script = lang_rules.script_re(lang)
        val = e.get(lang) or ""
        if script is not None and script.search(val):
            problems.append("登记为不译，但译文里有目标文字：%s（%s）" % (hid, val[:40]))

    pending_ids = set(T.pending_ids(es, lang))
    same = [e for e in es
            if e["id"] in pending_ids
            and (e.get(lang) or "") == (e.get(base_field) or "")]
    must = [e for e in same if structural(e.get(lang))]
    rest = [e for e in same if not structural(e.get(lang))]

    for e in must:
        problems.append("待译，且不含任何字母，应登记不译：%s（%s）"
                        % (e["id"], (e.get(lang) or "")[:60]))
    for e in rest:
        notes.append(e)

    lines = ["# keep_audit：%s" % lang,
             "待译 %d 条；其中值等于英文原文 %d 条（结构性不可译 %d、需人判 %d）"
             % (len(pending_ids), len(same), len(must), len(rest))]
    if must:
        lines += ["", "## 未登记的结构性不可译（必须登记）"]
        lines += ["%s\t%s" % (e["id"], (e.get(lang) or "")[:80]) for e in must]
    if rest:
        lines += ["", "## 值等于英文原文、含字母（人判：漏译 or 登记 credit/key）"]
        lines += ["%s\t%s" % (e["id"], (e.get(lang) or "")[:80]) for e in rest[:80]]
        if len(rest) > 80:
            lines.append("… 还有 %d 条" % (len(rest) - 80))
    if problems:
        lines += ["", "## 问题"] + problems
    os.makedirs(QA_DIR, exist_ok=True)
    path = os.path.join(QA_DIR, "keep_audit_%s.txt" % lang)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return problems, len(pending_ids), len(same), len(must), path


def main():
    langs = []
    if "--lang" in sys.argv:
        i = sys.argv.index("--lang")
        langs = [a for a in sys.argv[i + 1:] if not a.startswith("-")]
    doc = T.load_toml()
    es = T.entries(doc)
    base_field = T.BASE_LANG if any(e.get(T.BASE_LANG) for e in es) else "en"
    failed = 0
    for lang in (langs or T.target_langs()):
        problems, n_pend, n_same, n_must, path = audit(lang, es, base_field)
        mark = "×" if problems else "√"
        print("%s %-3s 待译 %-4d 同英文 %-4d 结构性不可译未登记 %-3d %s"
              % (mark, lang, n_pend, n_same, n_must,
                 os.path.relpath(path, ROOT)))
        if problems:
            failed += 1
            for p in problems[:10]:
                print("    " + p)
            if len(problems) > 10:
                print("    … 还有 %d 条" % (len(problems) - 10))
    if failed:
        print("\n有意不译清单有 %d 门语言对不上。" % failed)
        return 1
    print("\n有意不译清单一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
