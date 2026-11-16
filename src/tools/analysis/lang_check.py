#!/usr/bin/env python3
# coding: utf-8
"""lang_check.py — 外语形态层检查：语法、拼写、复合词拆分。

与 text_lint.py 的分工：
  text_lint   查「是否照着原文说对了」——模板、占位、标注、空值、同原文异译
  lang_check  查「这门语言写得对不对」——语法格位、拼写、德语复合词切分

判据都取自目标语言本身，不依赖中文，因此每种语言各跑一遍。
报告写到 build/qa/lang_check_<lang>.txt。

    python src/tools/analysis/lang_check.py --lang de
    python src/tools/analysis/lang_check.py --lang de --grammar-only
    python src/tools/analysis/lang_check.py --lang de --spell-only
"""

import argparse
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TR = os.path.join(ROOT, "src", "translations", "%s.toml")

sys.path.insert(0, os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from text import toml_io  # noqa: E402
from text import marks as MK  # noqa: E402

#: LanguageTool 的语言码；这里没有的语言跳过语法检查（日文、中文不在 LT 覆盖内）
LT_CODE = {"de": "de-DE", "fr": "fr", "es": "es", "ru": "ru-RU", "nl": "nl", "pt": "pt-PT"}

#: 字母串：任何非 ASCII 标点、非数字、非中日韩的字母（法语重音、西语 ñ、俄语西里尔都靠它）
ANY_WORD = re.compile(r"[^\W\d_\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]{2,}")

#: 引擎占位与标签：等长替换成下划线，既让 LT 不把它们当单词，又不打乱 offset
MASK = re.compile(r"%[0-9]+|@[a-zA-Z]\$[^$]*\$|<[^>]*>|\[[^\]]*\]")


def mask(text):
    """把占位符与标签替换成等长的下划线，保持字符位置不变。"""
    return MASK.sub(lambda m: "_" * len(m.group(0)), text)


def load(lang):
    doc, _ = toml_io.read_doc(TR % lang)
    return MK.expand_doc(lang, doc)


# ---------------------------------------------------------------- 语法

def grammar(lang, tr):
    """整包过一遍 LanguageTool，命中按规则归纳。"""
    code = LT_CODE.get(lang)
    if not code:
        return None, []
    import language_tool_python

    tool = language_tool_python.LanguageTool(code)
    keys = [k for k in tr if mask(str(tr[k])).strip("_ ")]
    hits = []
    # 按字符数切批：百科长文单独成批，否则一批几万字 LanguageTool 会跑几分钟到几十分钟
    BATCH_CHARS = 3000
    batches, cur, cur_chars = [], [], 0
    for k in keys:
        n = len(str(tr[k]))
        if cur and cur_chars + n > BATCH_CHARS:
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(k)
        cur_chars += n
    if cur:
        batches.append(cur)
    for bi, batch in enumerate(batches):
        chunk = [(k, mask(str(tr[k]))) for k in batch]
        joined = "\n".join(t for _, t in chunk)
        spans, pos = [], 0
        for k, t in chunk:
            spans.append((k, pos, pos + len(t)))
            pos += len(t) + 1
        for m in tool.check(joined):
            off = m.offset
            for k, s, e in spans:
                if s <= off < e:
                    hits.append((k, m.rule_id, m.context.replace("\n", " ")[:80],
                                 (m.replacements[0] if m.replacements else "")[:40]))
                    break
    return len(keys), hits


# ---------------------------------------------------------------- 拼写

def split_head(w, vocab, link=("s", "n", "en", "er", "es", "e")):
    """长复合词切出词头；切不动返回 None。连接元音后至少还得剩两个字母。"""
    low = w.lower()
    for i in range(len(low) - 3, 2, -1):
        h, rest = low[:i], low[i:]
        if h in vocab and (rest in vocab or (rest[:1] in link and rest[1:] in vocab and len(rest) > 2)):
            return h
    return None


#: 本地 hunspell 词典（src/data/qa/dict/<base>.aff + .dic）。有就用它，它带变形与复合词规则，
#: 比纯频率表准得多；没有就退回 pyspellchecker。
HUNSPELL = {"de": "de_DE_frami", "fr": "fr_FR", "es": "es_ES", "ru": "ru_RU"}


def spell(lang, tr, allow):
    """未收录词。专名、术语、缩写、以及能拆成两个词典词的复合词都不报。"""
    base = HUNSPELL.get(lang)
    dic = os.path.join(ROOT, "src", "data", "qa", "dict", base or "")
    hd = None
    if base and os.path.isfile(dic + ".dic"):
        from spylls.hunspell import Dictionary
        hd = Dictionary.from_files(dic)

    if hd is None:
        from spellchecker import SpellChecker
        sp = SpellChecker(language=lang)
        vocab = set(w.lower() for w in sp.word_frequency.words())

    def known(w):
        if hd is not None:
            return hd.lookup(w) or hd.lookup(w.capitalize()) or hd.lookup(w.lower())
        return w.lower() not in sp.unknown([w.lower()])

    words, per_key = {}, {}
    WORD = ANY_WORD
    for k, v in tr.items():
        for w in WORD.findall(mask(str(v))):
            if w.lower() in allow or w in allow:
                continue
            words.setdefault(w, set()).add(k)
    for w in words:
        if known(w):
            continue
        if hd is None and (len(w) <= 3 or split_head(w, vocab)):
            continue
        if len(w) <= 3:
            continue
        per_key[w] = sorted(words[w])[:3]
    return per_key


def build_allow(lang, tr):
    """白名单：译名表的值、术语表的值、全大写缩写、以及文本里逐字出现过的英文词。"""
    allow = set()
    for tbl in (MK.load_names(lang), MK.load_terms(lang)):
        for v in tbl.values():
            if isinstance(v, dict):
                v = v.get("default", "")
            for w in ANY_WORD.findall(str(v)):
                allow.add(w.lower())
    for v in tr.values():
        for w in ANY_WORD.findall(str(v)):
            if w.isupper() and len(w) <= 5:      # STRG、OK、CTRL 这类键名与缩写
                allow.add(w.lower())
    return allow


# ---------------------------------------------------------------- 复合词

def compounds(tr, limit=40):
    """德语名词连写切分：长词按最长前缀 + 连接元音拆开，统计词头分布。"""
    from spellchecker import SpellChecker

    sp = SpellChecker(language="de")
    vocab = set(w.lower() for w in sp.word_frequency.words())
    heads, misses = {}, []
    LINK = ("s", "n", "en", "er", "es", "e")
    WORD = re.compile(r"[A-ZÄÖÜ][a-zäöüß]{11,}")
    for k, v in tr.items():
        for w in WORD.findall(str(v)):
            low = w.lower()
            cut = None
            for i in range(len(low) - 4, 3, -1):
                h, rest = low[:i], low[i:]
                if h in vocab and (rest in vocab or (rest[:1] in LINK and rest[1:] in vocab)):
                    cut = h
                    break
            if cut:
                heads[cut] = heads.get(cut, 0) + 1
            elif low not in vocab:
                misses.append((w, k))
    top = sorted(heads.items(), key=lambda x: -x[1])[:limit]
    return top, misses[:60]


# ---------------------------------------------------------------- 报告

def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="de")
    ap.add_argument("--grammar-only", action="store_true")
    ap.add_argument("--spell-only", action="store_true")
    a = ap.parse_args(argv)

    lang = a.lang
    tr = load(lang)
    lines = ["# %s 形态层检查（%d 条）\n" % (lang, len(tr))]

    if not a.spell_only:
        n, hits = grammar(lang, tr)
        if n is None:
            lines.append("## 语法\n\nLanguageTool 不覆盖 %s，跳过。\n" % lang)
        else:
            rules = {}
            for k, r, msg, rep in hits:
                rules[r] = rules.get(r, 0) + 1
            lines.append("## 语法（LanguageTool %s）\n" % LT_CODE[lang])
            lines.append("检查 %d 条，命中 %d 处，涉及 %d 条规则。\n" % (n, len(hits), len(rules)))
            lines.append("| 规则 | 次数 |")
            lines.append("|---|---|")
            for r, c in sorted(rules.items(), key=lambda x: -x[1])[:25]:
                lines.append("| `%s` | %d |" % (r, c))
            lines.append("")
            for k, r, msg, rep in hits[:120]:
                lines.append("%s | %-24s | %s | → %s" % (k, r, msg, rep))
            lines.append("")

    if not a.grammar_only:
        allow = build_allow(lang, tr)
        unk = spell(lang, tr, allow)
        lines.append("## 拼写\n\n未收录词 %d 个（已剔除译名表、术语表与缩写）。\n" % len(unk))
        for w, ks in sorted(unk.items(), key=lambda x: x[1][0])[:120]:
            lines.append("%s | %s" % (w, ", ".join(ks)))
        lines.append("")
        if lang == "de":
            top, misses = compounds(tr)
            lines.append("## 复合词词头（前 40）\n")
            lines.append("| 词头 | 出现 |")
            lines.append("|---|---|")
            for h, c in top:
                lines.append("| %s | %d |" % (h, c))
            lines.append("\n未能切分的长词 %d 个（前 60）：\n" % len(misses))
            for w, k in misses:
                lines.append("%s | %s" % (w, k))

    text = "\n".join(lines) + "\n"
    out = os.path.join(ROOT, "build", "qa", "lang_check_%s.txt" % lang)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, "w", encoding="utf-8", newline="").write(text)
    print(text[:4000])
    print("报告：%s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
