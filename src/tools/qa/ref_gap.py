"""参照层 gap 复核：把 ref_check 报出的 E 级残留分成「疑似」几类，并输出并排全文。

用法：python -X utf8 src/tools/qa/ref_gap.py [de es pl ru] [--no-view]

产物：

* `build/qa/ref_gap.txt`：分级表，一条一行 `id  级别  读数`。
* `build/qa/ref_gap_view.txt`：每条「疑似」的 EN／FR／本参照 clean／本语言译文
  四段全文并排，供人工逐条定性。

判据全部可复现，不猜语义：

* 缺令牌：把基准的 `@X$Name$` / `%N` 去掉后本参照少一个 → 零售原文没写这个量。
* 减译：参照长度不到基准 55%，且句子数也少 → 零售版把几条并成一条或删了后半。
* 缺句：句子数少 ≥1，长度比不低于 55% → 少了中间的句子。
* 参照多分段：参照的 `<n>` 比基准多 → add-only 不删，无害（下游 text_lint 会拦）。

级别一律带「疑似」前缀：这些都是启发式读数，不是判定。真缺句必须并排读过全文
才能落 `apply --ids`（ru `0xe6d9252f` 就是这样确认的：7 条疑似里只有它真缺第 3 句）。
"""
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, ROOT)

from text import toml_io  # noqa: E402

TOK = re.compile(r"@[A-Za-z]*\$[^$\n]*\$|%[0-9]+")
SENT = re.compile(r"[.!?…]+")
HIT = re.compile(r"\s+(0x[0-9a-f]{8})\s+")

DEFAULT_LANGS = ("de", "es", "pl", "ru")


def values(path):
    """读一份 toml 成 {id: 文本}，只收字符串值。"""
    doc, _order = toml_io.read_doc(path)
    out = {}
    for k, entry in doc.items():
        t = entry.get("default", "") if isinstance(entry, dict) else str(entry or "")
        if t:
            out[str(k)] = t
    return out


def hit_ids(path):
    """只取 E 级那一段（`ref_check` 报告先 E 后 W，遇到「W 级」就停）。"""
    ids = []
    for line in io.open(path, encoding="utf-8"):
        if line.startswith("W 级"):
            break
        m = HIT.match(line)
        if m:
            ids.append(m.group(1))
    return ids


def classify(base, ref):
    nb, nr = len(TOK.findall(base)), len(TOK.findall(ref))
    sb, sr = len(SENT.findall(base)), len(SENT.findall(ref))
    if nb != nr:
        return "疑似缺令牌", "%d/%d 个令牌" % (nr, nb)
    if base.count("<n") > ref.count("<n"):
        return "疑似参照少分段", "%d/%d 处" % (ref.count("<n"), base.count("<n"))
    if base.count("<n") < ref.count("<n"):
        return "参照多分段（无害）", "%d/%d 处" % (ref.count("<n"), base.count("<n"))
    ratio = (len(ref) + 1) / (len(base) + 1)
    if ratio < 0.55 and sr < sb:
        return "疑似减译", "长度 %.0f%%、句 %d/%d" % (ratio * 100, sr, sb)
    if sr < sb:
        return "疑似缺句", "句 %d/%d、长度 %.0f%%" % (sr, sb, ratio * 100)
    return "疑似结构差", "句 %d/%d" % (sr, sb)


def main(argv):
    langs = [a for a in argv if not a.startswith("--")] or list(DEFAULT_LANGS)
    make_view = "--no-view" not in argv

    en = values(os.path.join(ROOT, "build", "ref", "clean", "en-clean.toml"))
    fr = values(os.path.join(ROOT, "build", "ref", "clean", "fr-clean.toml"))

    table, view = [], []
    total = 0
    for lang in langs:
        ref = values(os.path.join(ROOT, "build", "ref", "clean", "%s-clean.toml" % lang))
        tr = values(os.path.join(ROOT, "src", "translations", "%s.toml" % lang))
        ids = hit_ids(os.path.join(ROOT, "build", "qa", "ref_check_%s-clean.txt" % lang))
        table.append("## %s（%d 条）" % (lang, len(ids)))
        kinds = {}
        for hid in ids:
            b, t = en.get(hid), ref.get(hid)
            if not isinstance(b, str) or not isinstance(t, str):
                table.append("  %s  <!-- 键缺失 -->" % hid)
                continue
            kind, detail = classify(b, t)
            kinds[kind] = kinds.get(kind, 0) + 1
            table.append("  %s  %-16s %s" % (hid, kind, detail))
            if kind.startswith("疑似"):
                total += 1
                view.append("=== %s %s  %s  %s" % (lang, hid, kind, detail))
                for label, text in (("EN", b), ("FR", fr.get(hid, "")),
                                    ("%s-clean" % lang.upper(), t),
                                    ("%s" % lang.upper(), tr.get(hid, ""))):
                    view.append("--- %s" % label)
                    view.append(text if text else "<!-- 无 -->")
                view.append("")
        table.append("  小计：%s" % "、".join("%s %d" % (k, v) for k, v in kinds.items()))
        table.append("")

    out = os.path.join(ROOT, "build", "qa", "ref_gap.txt")
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(table) + "\n")
    print("\n".join(table))
    if make_view:
        vout = os.path.join(ROOT, "build", "qa", "ref_gap_view.txt")
        head = "并排全文：%d 条疑似（EN／FR／参照 clean／本语言译文）\n\n" % total
        with io.open(vout, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(head + "\n".join(view) + "\n")
        print("并排全文 %d 条 → %s" % (total, vout))


if __name__ == "__main__":
    main(sys.argv[1:])
