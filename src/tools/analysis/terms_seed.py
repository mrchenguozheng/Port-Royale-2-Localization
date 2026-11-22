#!/usr/bin/env python3
# coding: utf-8
"""terms_seed.py —— 新语言术语表的证据化起草（术语不再逐条手填）。

为什么要有这个：`src/data/terms/<语言>.toml` 是「术语锁定」表，键一律
`en_<英文词>`，两条检查要用它（`text_lint` 的短标签术语检查、`translate.py
terms` 的全量落词检查）。新语言此前只有一份**空值骨架**，19 个键全靠人填；
pl 这轮连骨架都没有，`terms --lang pl` 于是报「0 条（0 个词）」——没有词表
可查的「通过」比报错更危险。

本脚本只做**取证**，不猜译法，分两档：

1. **整行标签**（最硬）：英文原串整条就是这个词（`Pirate`、`Trade route`），
   译文那一条就是该词的对照形。直接取值，`Whitespace`、`<…>` 标签先剥掉；
   单数行优先于复数行（`Warehouses` 那几条会把答案带成 `Magazyny`）。
2. **全库共现**：锚定条目（英文里出现该词）里，看目标语言反复用哪个词。
   屈折语要按词干簇合并（`pirat / piraci / piratów` 是同一个词，按整形计数
   `pirate` 的榜首只有三成）。还要求**位置吻合**：锚词在英文句子里的相对位置
   与候选在译文里的相对位置差不超过 0.35 才算一次命中——这一条专门挡
   「`market` 那批句子都在说『把货运到市场』，`towaru`（货物）跟着出现」这类
   假阳性（实测 `rynek` 位置吻合 95%、`towaru` 只有 79%，词频却反过来）。
   最后要求这个词在锚定条目里的密度至少是它在全库的 2.5 倍。

达不到门槛的留空，候选与覆盖写在行尾注释里等人定；`--write` 只写
`src/data/terms/<语言>.toml`，已有值默认不动（`--force` 才覆盖）。

    python src/tools/analysis/terms_seed.py --lang pl            # 只看
    python src/tools/analysis/terms_seed.py --lang pl --write    # 落盘

不管的部分（保持手工）：`de_…` / `fr_…` 键是「英文一个词、德/法拆两个义项」
的登记，英文侧没有可锚的词，统计取不了证。
"""
import argparse
import os
import re
import sys
import tomllib
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for p in (os.path.join(ROOT, "src", "tools"), os.path.join(ROOT, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import translate as T                                  # noqa: E402

EN = os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")
TR = os.path.join(ROOT, "src", "translations", "%s.toml")
TERMS_DIR = os.path.join(ROOT, "src", "data", "terms")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
TAGS = re.compile(r"<[^>]*>")
#: 位置吻合判据：锚词与候选在各自句子里的相对位置差。
POS_TOL = 0.35
#: 密度判据：锚定条目里的覆盖率至少是全库覆盖率的这么多倍。
MIN_LIFT = 2.5
SKIP_WORDS = {"the", "and", "for", "you", "your", "with", "that", "this", "are",
              "was", "have", "has", "not", "but", "all", "can", "will", "our",
              "its", "his", "her", "they", "them", "from", "one", "two",
              "a", "an", "of", "to", "in", "on", "is", "it", "be", "as", "at",
              "or", "by", "we", "i", "if", "no", "so", "do", "he", "she",
              "der", "die", "das", "und", "ist", "ein", "eine", "mit", "von",
              "zu", "den", "dem", "les", "des", "une", "est", "pour", "dans",
              "sur", "que", "qui", "pas", "plus", "vous", "nous", "avec"}


def fold(word):
    """比较用：去重音、小写。`Piraci` 与 `piraci` 是同一个词。"""
    s = unicodedata.normalize("NFKD", word or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def clean(text):
    """去掉引擎标签与首尾空白：`'Magazyn  '`、`'<n>Kryjówka'` 都是同一个词。"""
    return TAGS.sub("", text or "").strip()


def anchor_rx(anchor):
    """整词 + 可选复数 s，与 terms_check.compile_rule 同一口径。"""
    case = re.IGNORECASE if anchor[:1].islower() else 0
    body = r"\s+".join(re.escape(p) for p in anchor.split())
    return re.compile(r"(?<![A-Za-z])%s(?:s)?(?![A-Za-z])" % body, case)


def cluster_key(cand_key):
    """屈折形并簇：每个词取前 4 个折叠字母。

    波兰语 `pirat / piraci / piratów`、`magazyn / magazynu`、
    `jakość życia / jakości życia` 都是一个词的不同格，按整形计数会把票拆散。
    """
    return " ".join(w[:4] for w in cand_key.split())


def candidates(text, max_words=3):
    """一条译文里的候选片段（1~3 词连续），返回 [(折叠键, 原写法)]。"""
    out = []
    toks = WORD.findall(text or "")
    for n in range(1, max_words + 1):
        for i in range(len(toks) - n + 1):
            phrase = " ".join(toks[i:i + n])
            key = fold(phrase)
            if len(key) < 4 or key in SKIP_WORDS:
                continue
            out.append((key, phrase))
    return out


def _pos_ratio(text, needle_rx):
    m = needle_rx.search(text)
    return None if m is None else m.start() / float(max(1, len(text)))


def label_value(anchor, rows):
    """整行标签那一档：英文整条就是这个词，取译文的对照形。

    单数行优先（`Warehouse` 比 `Warehouses` 更能给原形）；多种写法时取最常见的。
    """
    singular, plural = {}, {}
    for _hid, en_text, tr in rows:
        head = clean(en_text)
        if head.casefold() == anchor.casefold():
            bucket = singular
        elif head.casefold() == (anchor + "s").casefold():
            bucket = plural
        else:
            continue
        val = clean(tr)
        if val:
            bucket[val] = bucket.get(val, 0) + 1
    for bucket in (singular, plural):
        if bucket:
            return max(bucket.items(), key=lambda kv: (kv[1], len(kv[0])))[0], len(bucket)
    return None, 0


def corpus_value(anchor, hits, all_rows, min_rows, min_share, min_precision):
    """全库共现那一档：词干簇覆盖 + 位置吻合 + 密度比。返回 (值, 候选表, 证据)。"""
    rx = anchor_rx(anchor)
    counts, forms, rows_of = {}, {}, {}
    for hid, en_text, tr in hits:
        seen = set()
        for cand_key, cand_text in candidates(tr):
            ck = cluster_key(cand_key)
            if ck in seen:
                continue
            seen.add(ck)
            counts[ck] = counts.get(ck, 0) + 1
            forms.setdefault(ck, {})
            forms[ck][cand_text] = forms[ck].get(cand_text, 0) + 1
            rows_of.setdefault(ck, []).append((en_text, tr))

    # 位置吻合：锚词与候选各自首次出现的相对位置差 ≤ POS_TOL 算一次。
    def precision(ck):
        ok = 0
        for en_text, tr in rows_of[ck]:
            a = _pos_ratio(en_text, rx)
            c = None
            for surf in forms[ck]:
                c = _pos_ratio(tr, re.compile(r"(?<![^\W\d_])" + re.escape(surf) +
                                              r"(?![^\W\d_])", re.IGNORECASE))
                if c is not None:
                    break
            if a is not None and c is not None and abs(a - c) <= POS_TOL:
                ok += 1
        return ok / float(len(rows_of[ck])) if rows_of[ck] else 0.0

    prec = {ck: precision(ck) for ck in counts}
    ranked = sorted(counts.items(), key=lambda kv: (-(kv[1] * prec[kv[0]]), -len(kv[0])))[:5]
    top, value, why = [], None, "证据不足"
    base_n = {}
    for ck, n in ranked:
        floor = max(1, int(n * 0.4))
        good = [f for f, c in forms[ck].items() if c >= floor] or list(forms[ck])
        surf = min(good, key=lambda f: (len(f), -forms[ck][f]))
        if len(top) < 3:
            top.append((surf, n, prec[ck]))
        share = n / float(len(hits))
        ck_key = cluster_key(fold(surf))
        if ck_key not in base_n:
            base_n[ck_key] = sum(1 for _h, _e, tr in all_rows
                                 if any(cluster_key(k) == ck_key
                                        for k, _t in candidates(tr)))
        lift = share / max(base_n[ck_key] / float(len(all_rows) or 1), 1e-6)
        # 取「排在这个名次上仍然站得住」的第一个：`market` 的榜首 `towaru`
        # 是位置对不上的词，往下翻一位才是真译法 `rynek`。
        if (value is None and len(hits) >= min_rows and share >= min_share
                and prec[ck] >= min_precision and lift >= MIN_LIFT):
            value = surf
            why = "%d/%d 条、位置吻合 %.0f%%、密度比 %.1f" % (
                n, len(hits), prec[ck] * 100, lift)
        elif value is None and why == "证据不足":
            why = "首选 %s %d/%d 条、位置吻合 %.0f%%、密度比 %.1f（未达标）" % (
                surf, n, len(hits), prec[ck] * 100, lift)
    return value, top, why


def mine(lang, min_rows=4, min_share=0.95, min_precision=0.95):
    with open(EN, "rb") as f:
        en = tomllib.load(f)
    with open(TR % lang, "rb") as f:
        doc = tomllib.load(f)
    with open(os.path.join(TERMS_DIR, "zh.toml"), "rb") as f:
        keys = [k for k, v in tomllib.load(f).items() if isinstance(v, str)]
    keep = T.keep_as_is(lang)

    rows = []                                  # (id, 英文, 译文)，已排除不译与未译
    for hid, text in en.items():
        tr = doc.get(hid, "") or ""
        if hid in keep or not tr.strip() or tr.strip() == (text or "").strip():
            continue
        rows.append((hid, text or "", tr))

    out = []
    for key in keys:
        prefix, _, rest = key.partition("_")
        if prefix != "en" or not rest:
            out.append({"key": key, "anchor": None, "value": None, "rows": 0,
                        "top": [], "why": "非 en 键"})
            continue
        anchor = rest.replace("_", " ")
        rx = anchor_rx(anchor)
        hits = [(hid, text, tr) for hid, text, tr in rows if rx.search(text)]
        value, n_label = label_value(anchor, hits)
        if not value:
            value, top, why = corpus_value(anchor, hits, rows, min_rows, min_share,
                                           min_precision)
            out.append({"key": key, "anchor": anchor, "value": value,
                        "rows": len(hits), "top": top, "why": why})
            continue
        out.append({"key": key, "anchor": anchor, "value": value,
                    "rows": len(hits), "top": [], "why": "整行标签 %d 种写法" % n_label})
    return out


HEAD = """# 术语锁定表：<语言>_<原词> → 该语言译词。
#
# 键一律 ASCII 小写、以语言前缀开头（en_ / de_ / fr_），原形大小写与重音写在注释里。
# 英文词只收「同一语境里只有一个义项」的；同词两义改用**把义项分开的那门参考语言**
# 做键 —— 哪门语言分得开就用哪门，分不开的不进表。
#
# 用法：译文里写 [term:en_business]，展开查这张表；查不到直接 MarkError，构建失败。
#
# 本表由 terms_seed.py 起草：值 = 证据达标的候选（注释写证据），留空 = 证据不足，
# 候选与覆盖列在注释里，等人定。
"""


def render(result, old_values, force):
    lines = [HEAD]
    for item in result:
        key = item["key"]
        old = (old_values.get(key) or "").strip()
        value = old if (old and not force) else (item["value"] or "")
        if item["anchor"] is None:
            note = ("de/fr 键：英文侧没有可锚的词，统计取不了证"
                    if key.split("_")[0] in ("de", "fr") else item["why"])
            lines.append('"%s" = "%s"%s' % (key, old or "", "        # " + note if not old else ""))
            continue
        if value:
            lines.append('"%s" = "%s"        # en: %s，%s'
                         % (key, value, item["anchor"], item["why"]))
        else:
            cands = "、".join("%s(%d)" % (c, n) for c, n, _p in item["top"]) or "无命中"
            lines.append('"%s" = ""        # en: %s，%d 条；候选：%s；%s'
                         % (key, item["anchor"], item["rows"], cands,
                            item["why"] or "证据不足"))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="术语表证据化起草")
    ap.add_argument("--lang", required=True)
    ap.add_argument("--write", action="store_true", help="写入 src/data/terms/<语言>.toml")
    ap.add_argument("--force", action="store_true", help="已有值也按本次取证重写")
    ap.add_argument("--min-rows", type=int, default=4, help="锚定条目下限")
    ap.add_argument("--min-share", type=float, default=0.95, help="首选候选的覆盖下限")
    ap.add_argument("--min-precision", type=float, default=0.95, help="位置吻合下限")
    args = ap.parse_args(argv)

    result = mine(args.lang, args.min_rows, args.min_share, args.min_precision)
    path = os.path.join(TERMS_DIR, args.lang + ".toml")
    old = {}
    if os.path.exists(path):
        with open(path, "rb") as f:
            old = {k: v for k, v in tomllib.load(f).items() if isinstance(v, str)}

    filled = sum(1 for r in result if r["value"])
    print("== %s：%d 个键，已成值 %d、留空 %d"
          % (args.lang, len(result), filled, len(result) - filled))
    for r in result:
        if r["anchor"] is None:
            print("   %-22s （%s，留手工）" % (r["key"], r["why"]))
            continue
        cands = " / ".join("%s(%d)" % (c, n) for c, n, _p in r["top"])
        print("   %-22s %-18s %d 条  %s%s"
              % (r["key"], r["value"] or "—", r["rows"], r["why"],
                 ("  候选：" + cands) if cands and not r["value"] else ""))

    if args.write:
        os.makedirs(TERMS_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(render(result, old, args.force))
        print("写入：%s" % os.path.relpath(path, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
