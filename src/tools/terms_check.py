#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""terms_check.py —— 术语一致性检查：原文里出现了术语，译文有没有用约定的译法。

为什么需要
----------
术语表（glossary\\terms.toml）本身只是「查得到」；真正难的是 3500 多条里
同一个词被译成好几种。这个脚本把术语表当规则用：

    原文里出现 `Frigate`  →  译文里应该出现「巡防舰」

没出现就报出来，附带该条的 id、英文片段和实际译文，方便逐条改。

判定规则
--------
- 英文按**整词**匹配（`Frigate` 不会命中 `Frigatebird`）；术语首字母大写时
  区分大小写 —— 否则 `may`（情态动词）会被当成五月；
- 允许复数：`Frigate` 也匹配 `Frigates`；
- 译文里包含约定译法即通过；词组里嵌着也算（「军事巡防舰」含「巡防舰」）；
- 组里可以写 `accept = ["载入", "读取"]` 表示这几种译法都算对；
- 组里写 `check = false` 就整组不查（界面词这种一词多义的不适合自动判）。

三级判定（本版新增）
------------------
光看词面在屈折语上不成立：德语 `Spanien` 在句里变格成 `spanischen`、
`Lagerhaus` 变复数成 `Lagerhäuser:`、`Matrose` 变成 `Matrosen`，全都不是错译，
只是**词形不同**。所以判决分三级：

    EXACT   译文含基准形全文                        → 通过
    MORPH   只含基准形的词根（拉丁／西里尔字母）     → 不计错，`--show-morph` 时单列
    MISSING 都不含                                  → 报错，并给出该译文里的疑似写法

词根取基准形最后一段词的前缀，长度 `max(4, min(8, len-3))`：`Spanien`→`Span`、
`Matrose`→`Matr`、`Handelsroute`→`Handelsr`。中文和日文不走词根——汉字前缀没有
形态学意义，仍按精确匹配。

词根比对必然带来少量假通过（`Markt` 的词根 `Mark` 会命中 `Marktplatz`），所以它只
用来「不计错」，不用来放行报错；真错永远落在 MISSING 上。

用法
----
    python src\\tools\\terms_check.py             # 查所有可编辑语言
    python src\\tools\\terms_check.py --lang zh
    python src\\tools\\terms_check.py --json       # 给编辑器/脚本用
    python src\\tools\\terms_check.py --strict     # 有 MISSING 时退出码 1
    python src\\tools\\terms_check.py --show-morph # 连同词形差一起列出
"""
import argparse
import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
ROOT = os.path.dirname(SRC)
TERMS = os.path.join(ROOT, "glossary", "terms.toml")

sys.path.insert(0, HERE)
import translate as T

# 汉字语言：不做词根，只认全形
CJK_LANGS = {"zh", "ja"}


def load_terms():
    """返回 (各组, 整体跳过的 id 列表)。"""
    if not os.path.isfile(TERMS):
        return [], []
    with open(TERMS, "rb") as f:
        doc = tomllib.load(f)
    return doc.get("group", []), [x.lower() for x in doc.get("ignore", [])]


def pick_ids(group, en):
    if "range" in group:
        lo, hi = (int(x, 16) for x in group["range"])
        ids = [k for k in en if lo <= int(k, 16) <= hi]
    else:
        ids = [k.lower() for k in group.get("ids", [])]
        ids = [k for k in ids if k in en]
    top = group.get("max_len", 40)
    ids = [k for k in ids if len(en.get(k, "")) <= top]
    return sorted(ids, key=lambda k: int(k, 16))


def alt_for(group, term_id, lang):
    """组内某个 id 的补充译法。支持旧写法 [{id: [译法…]}] 与语言级写法
    [{id: {lang: [译法…], "*": [译法…]}}]。"""
    alt = (group.get("alt") or {}).get(term_id, [])
    if isinstance(alt, dict):
        alt = list(alt.get(lang) or []) + list(alt.get("*") or [])
    return [a.strip() for a in alt]


_TERM_CACHE = {}


def term_table(lang):
    """该语言的术语表（src/data/terms/<lang>.toml），给基准形里的 [term:x] 用。"""
    if lang not in _TERM_CACHE:
        path = os.path.join(ROOT, "src", "data", "terms", lang + ".toml")
        table = {}
        if os.path.isfile(path):
            with open(path, "rb") as f:
                table = {k: v for k, v in tomllib.load(f).items()
                         if isinstance(v, str)}
        _TERM_CACHE[lang] = table
    return _TERM_CACHE[lang]


def resolve_marks(want, lang):
    """基准形里可能写着标注（`[term:en_tools]`），换成该语言的术语值再比。

    换不出来（缺条目／空占位／还留着别的标注）就返回 None，这条规则不查——
    拿标注本身当译法去正文里搜，只会造出假阳性。
    """
    if "[term:" not in want:
        return want
    out = re.sub(r"\[term:([^\]]+)\]",
                 lambda m: term_table(lang).get(m.group(1).strip()) or "", want)
    if re.search(r"\[(term|ref|lit):", out):
        return None
    return out.strip()


def stem_prefix(term):
    """基准形的词根：最后一段词的前缀。取不到（太短／非纯字母）就返回 None。"""
    parts = term.split()
    last = parts[-1] if parts else term
    if not last or not last.isalpha():
        return None
    n = len(last)
    k = max(4, min(8, n - 3))
    if k >= n:
        return None
    return last[:k]


def compile_stem(stem):
    """词根只要求出现在词首，后面自由（Pirat→Piraten、Spanien→spanischen）。

    一律不区分大小写：`Spanien` 在句里会以形容词 `spanischen` 出现（首字母小写），
    而词根只用来「不计错」，宽松一点比把真词形差误报成 MISSING 更划算；真错译的词
    根本不会共享这几个字母。
    """
    return re.compile(r"(?<![^\W\d_])%s" % re.escape(stem), re.IGNORECASE)


def build_rules(groups, en, doc, lang):
    """[(英文术语, [可接受译法…], [词根正则…], 组名, 定义该术语的 id)]。"""
    rules = []
    for g in groups:
        if g.get("check", True) is False:
            continue
        ids_in_group = pick_ids(g, en)
        accept = [a.strip() for a in g.get("accept", [])]
        for k in ids_in_group:
            term = en[k].strip()
            want = doc.get(k, "").strip()
            if not term or not want:
                continue
            if not re.fullmatch(r"[A-Za-z][A-Za-z' -]{1,30}", term):
                continue                      # 术语本身不是纯英文词就不查
            want = resolve_marks(want, lang)
            if not want:
                continue                      # 基准形是换不出来的标注，这条不查
            alt = alt_for(g, k, lang)
            ok = [want] + accept + alt
            # 月份：中文数字与阿拉伯数字两种写法都算对（六月 / 6月）
            m = re.fullmatch(r"([一二三四五六七八九十]{1,2})月", want)
            if m:
                ok.append("%s月" % CN_NUM.get(m.group(1), ""))
            stems = []
            if lang not in CJK_LANGS:
                for cand in [want] + alt:
                    s = stem_prefix(cand)
                    if s:
                        stems.append(compile_stem(s))
            rules.append((term, [x for x in ok if x], stems, g["name"], k,
                          set(ids_in_group)))
    return rules


CN_NUM = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6",
          "七": "7", "八": "8", "九": "9", "十": "10", "十一": "11", "十二": "12"}


def compile_rule(term):
    """整词 + 可选复数 s；首字母大写时区分大小写（区分 May 与 may）。

    复数只认 `s`，不认 `es`：否则 `Wood` 会命中人名 `Woodes Rogers`。
    """
    case = re.IGNORECASE if term[:1].islower() else 0
    body = r"\s+".join(re.escape(p) for p in term.split())
    return re.compile(r"(?<![A-Za-z])%s(?:s)?(?![A-Za-z])" % body, case)


def near_forms(text, base):
    """在译文里找「像基准形」的片段：同长度、同首字符、纯字母/汉字。

    不是聚类，只是给人工一个「这里其实写成了什么」的提示。只同首字符不够——`Spanien`
    会把 `Steuern`、`Seeleut` 全捞上来，所以拉丁字母还要求与基准形共享 ≥3 个起始字母；
    汉字只共享 1 个字反而是有意义的（`贸易路线` ↔ `贸易航线`）。
    """
    if len(base) < 2:
        return []
    b0 = base[:1]
    # 一律不区分大小写找起点：`Spanien` 的疑似写形往往以小写 `spanischen` 出现
    flag = re.IGNORECASE
    latin = b0.isascii() and b0.isalpha()
    out = []
    for m in re.finditer(re.escape(b0), text, flag):
        i = m.start()
        # 必须是词首：`automatisch` 里的 `matisch`、`Neuengland` 里的 `england` 都是
        # 长词内部片段，提示出来只会误导。汉字没有词间空格，不做这条限制
        if latin and i > 0 and text[i - 1].isalpha():
            continue
        win = text[i:i + len(base)]
        if len(win) < len(base):
            continue
        if not all(c.isalpha() for c in win):
            continue
        if win == base:
            continue
        if latin:
            lcp = 0
            for a, b in zip(win.lower(), base.lower()):
                if a != b:
                    break
                lcp += 1
            if lcp < 3:
                continue
        if win not in out:
            out.append(win)
        if len(out) >= 4:
            break
    return out


def judge(trans, ok, stems):
    flat = re.sub(r"\s+", "", trans)
    for a in ok:
        if a and re.sub(r"\s+", "", a) in flat:
            return "EXACT", None
    for rx in stems:
        m = rx.search(trans)
        if m:
            return "MORPH", trans[m.start():m.start() + 12]
    return "MISSING", None


def check_lang(lang, groups, en, doc):
    """返回 {"missing": [...], "morph": [...]}。"""
    rules = [(compile_rule(t), t, ok, stems, g, k, same_group)
             for t, ok, stems, g, k, same_group in build_rules(groups, en, doc, lang)]
    missing, morph = [], []
    seen = set()
    for rid, en_text in en.items():
        tr = doc.get(rid, "") or ""
        if not tr.strip():
            continue
        # 先找出所有命中，再按「长的优先」消重叠：`Rear Admiral` 命中后，
        # 里面的 `Admiral` 就不再单独算一次。
        hits = []
        for rx, term, ok, stems, group, term_id, same_group in rules:
            # 术语条目本身、以及同组里的其它术语（Rear Admiral 里的 Admiral）不查
            if rid in same_group:
                continue
            for m in rx.finditer(en_text):
                hits.append((m.start(), m.end(), m.end() - m.start(),
                             term, ok, stems, group))
        hits.sort(key=lambda h: (-h[2], h[0]))
        kept, spans = [], []
        for h in hits:
            if any(not (h[1] <= s or h[0] >= e) for s, e in spans):
                continue
            spans.append((h[0], h[1]))
            kept.append(h)
        for _s, _e, _ln, term, ok, stems, group in kept:
            level, frag = judge(tr, ok, stems)
            if level == "EXACT":
                continue
            sig = (rid, term, level)
            if sig in seen:
                continue
            seen.add(sig)
            rec = {"id": rid, "term": term, "group": group, "level": level,
                   "expected": ok[0], "actual": tr, "en": en_text}
            if level == "MORPH":
                rec["form"] = frag
                morph.append(rec)
            else:
                rec["near"] = near_forms(tr, ok[0])
                missing.append(rec)
    return {"missing": missing, "morph": morph}


def main():
    ap = argparse.ArgumentParser(description="术语一致性检查")
    ap.add_argument("--lang", action="append", default=[])
    ap.add_argument("--json", action="store_true", help="输出 JSON（编辑器用）")
    ap.add_argument("--limit", type=int, default=40, help="每个语言打印多少条")
    ap.add_argument("--strict", action="store_true", help="有 MISSING 时退出码 1")
    ap.add_argument("--show-morph", action="store_true", help="列出词形差")
    args = ap.parse_args()

    groups, ignore = load_terms()
    if not groups:
        raise SystemExit("没有术语表：%s" % TERMS)
    en = T.load_toml()["s"]
    en = {r["id"]: r.get(T.BASE_LANG, "") for r in en}

    langs = args.lang or T.target_langs()
    out = {}
    total = 0
    for lang in langs:
        doc = {r["id"]: r.get(lang, "") for r in T.load_toml()["s"]}
        doc = {k: v for k, v in doc.items() if k not in ignore}
        res = check_lang(lang, groups, en, doc)
        out[lang] = res
        total += len(res["missing"])
        if not args.json:
            print("== %s：MISSING %d 条，词形差 %d 条"
                  % (lang, len(res["missing"]), len(res["morph"])))
            for x in res["missing"][:args.limit]:
                near = ("　疑似：%s" % " / ".join(x["near"])) if x["near"] else ""
                print("   %s [%s] 应为「%s」，实际：%s%s"
                      % (x["id"], x["term"], x["expected"],
                         x["actual"][:60].replace("\n", " "), near))
            if len(res["missing"]) > args.limit:
                print("   … 还有 %d 条" % (len(res["missing"]) - args.limit))
            if args.show_morph:
                for x in res["morph"][:args.limit]:
                    print("   ~ %s [%s] 基准「%s」，实际写成：%s"
                          % (x["id"], x["term"], x["expected"], x["form"]))
                if len(res["morph"]) > args.limit:
                    print("   … 还有 %d 条词形差" % (len(res["morph"]) - args.limit))

    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    if args.strict and total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
