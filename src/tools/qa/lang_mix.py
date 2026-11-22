"""扫参照清洁版里的串语言条目。

用法：python -X utf8 src/tools/qa/lang_mix.py

产物 `build/qa/lang_mix.txt`，三种判据分开标，人工甄别时按 `why=` 看是哪一类：

* `identical`：同一 id 在 ≥3 份 clean 里逐字相同（≥4 字符、含字母）。零售没做本地化
  的条目基本都在这一类；单词条目（`Überschrift`）只有这一条能抓到——它只有 1 个词，
  停用词法永远够不上阈值。
* `xlang`：同一 id 在各份 clean 里判出的语种不一致（每份取停用词得分最高的语言，
  得分 ≥2 才算判出）。
* `foreign`：本份判出别的语言（≥3 词、本语言得分 ≤1、对方得分 ≥2）。

旧版只有 `foreign` 一路，阈值 ≥4 词、对方 ≥3 分，于是单词条目漏检；fr 侧 6 条误报
是因为 `de`／`la`／`en` 在 fr 与 es 两张停用词表里重叠。跨份一致性比单份打分稳：
同一字符串出现在四份里，本身就是「没本地化」的证据。
"""
import collections
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, ROOT)

from text import lang_id as LI  # noqa: E402
from text import toml_io  # noqa: E402

LANGS = LI.LANGS

LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
NON_ASCII = re.compile(r"[^\x00-\x7f]")
IDENT_ONLY = re.compile(r"^[A-Z0-9_]+$")

plain = LI.plain
words_of = LI.words


def guess(ws):
    """返回 (判定语种, 得分)。判据在 `text/lang_id.py`，这里只做二元组适配。"""
    top, _n, sc = LI.guess(ws)
    return top, sc


def main():
    docs = {}
    for lang in LANGS:
        path = os.path.join(ROOT, "build", "ref", "clean", lang + "-clean.toml")
        doc, _ = toml_io.read_doc(path)
        vals = {}
        for k, entry in doc.items():
            t = entry.get("default", "") if isinstance(entry, dict) else str(entry or "")
            if t:
                vals[str(k)] = t
        docs[lang] = vals

    # 每条 id 在六份里的值
    by_id = collections.defaultdict(dict)
    for lang in LANGS:
        for k, t in docs[lang].items():
            by_id[k][lang] = t

    rows = []

    def note(k, why, langs, detail):
        rows.append((why, k, langs, detail))

    for k, per in by_id.items():
        # identical：≥3 份逐字相同。跳过全大写标识串（`IDM_CONTEST_…`）、
        # 只收长句（≥20 字符）或带非 ASCII 字母的串——短的全 ASCII 同形串多半是
        # 地名与通用词（`Logo`、`Corpus Christi`），正当保留；单词条目 `Überschrift`
        # 靠 `Ü` 这个非 ASCII 字母才抓得到。
        same = collections.defaultdict(list)
        for lang, t in per.items():
            same[t].append(lang)
        for t, langs in same.items():
            if len(langs) < 3 or len(t) < 4:
                continue
            if IDENT_ONLY.match(t.strip()) or not LETTER.search(plain(t)):
                continue
            if len(t) < 20 and not NON_ASCII.search(plain(t)):
                continue
            note(k, "identical", langs, t[:80])

        # xlang：≥2 份判出「同一个外来语种」（en=de、es=de、pl=de、ru=de 这种）。
        # 各份各判出自己的语言是正常本地化，不能算不一致。
        judged = {}
        for lang, t in per.items():
            words = words_of(t)
            if len(words) < 2:
                continue
            top, sc = guess(words)
            if top:
                judged[lang] = (top, sc[lang], sc[lang])
        foreign = {lang: top for lang, (top, _b, _t) in judged.items() if top != lang}
        if len(foreign) >= 2 and len(set(foreign.values())) == 1:
            desc = ";".join("%s=%s" % (lg, top) for lg, top in sorted(foreign.items()))
            note(k, "xlang", sorted(foreign), "外来语一致：" + desc)
        for lang, (top, b, ts) in judged.items():
            if top != lang and b <= 1 and ts >= 2 and len(words_of(per[lang])) >= 3:
                note(k, "foreign", [lang], "%s->%s (%d/%d) %s" % (
                    lang, top, b, ts, per[lang][:80]))

    out = os.path.join(ROOT, "build", "qa", "lang_mix.txt")
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        for why, k, langs, detail in rows:
            fh.write("%s\t%s\t%s\t%s\n" % (why, k, ",".join(langs), detail))
    print("命中 %d 条，写出 %s" % (len(rows), out))
    for why, k, langs, detail in rows[:60]:
        print("%-10s %s [%s] %s" % (why, k, ",".join(langs), detail[:70]))


if __name__ == "__main__":
    main()
