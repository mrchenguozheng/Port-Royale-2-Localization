#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""de_crosscheck.py —— 德语交叉核对：用英文基准、零售德语、同版法语三条线查问题。

为什么需要
----------
德语译文 2875 条是人工按术语表落的，语义是否有偏差没法靠"读一遍"发现。
但有三样东西是可以机械比的：

    英文基准   en.gog_1.1.2.3.toml    （句子结构、专名、数字、否定）
    零售德语   de.retail-1.0.0.toml   （德国厂自己写的德语措辞、术语）
    同版法语   fr.gog_1.1.2.42.toml   （第二参考，用来发现英文本身有歧义的位置）

这个脚本只用词面事实判断，不猜语义，所以结论可复核。

检查项
------
E1 英文残留      译文里出现只可能属于英文的功能词（the/and/of/with/you…）
E2 否定不一致    英文有否定而德语没有，或反过来
E3 标点不一致    问号、感叹号数量与英文不同
E4 专名缺失      英文里的大写专名在德语里找不到（Havana→Havanna 已列入允许表）
E5 数字缺失      英文里的数字串在德语里找不到（数词写法已按规则折算）
E6 零售无交集    与零售德语的实词交集过低 —— 只作待查清单，不作判据
E7 敬称破例      出现 du/dich/dir/dein… （本项目统一 Ihr/Euch）
F1 法语分歧      英文有否定而法语没有（或反之）—— 交给人工看的歧义清单

用法
----
    python src\\tools\\analysis\\de_crosscheck.py
    python src\\tools\\analysis\\de_crosscheck.py --json build\\qa\\de_crosscheck.json
    python src\\tools\\analysis\\de_crosscheck.py --md docs\\archive\\德语交叉核对.md
    python src\\tools\\analysis\\de_crosscheck.py --only E1,E4
"""
import argparse
import json
import os
import re
import tomllib
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(SRC)

EN_PATH = os.path.join(SRC, "orig", "en.gog_1.1.2.3.toml")
DE_PATH = os.path.join(SRC, "translations", "de.toml")
RETAIL_PATH = os.path.join(SRC, "orig", "de.retail-1.0.0.toml")
FR_PATH = os.path.join(SRC, "orig", "fr.gog_1.1.2.42.toml")

TAG = re.compile(r"<[^<>]*>")
PH = re.compile(r"@[A-Za-z]+\$[A-Za-z0-9_]+\$")

# 只可能属于英文的功能词（与德语同形的词一律不收：in/so/was/all/still/am/her/us…）
EN_ONLY = {
    "the", "and", "of", "with", "you", "your", "from", "this", "that", "these",
    "those", "which", "would", "should", "could", "cannot", "about", "there",
    "their", "they", "them", "we", "our", "into", "than", "because", "while",
    "although", "however", "only", "very", "more", "most", "such", "other",
    "another", "each", "both", "any", "some", "not", "just", "yet", "again",
    "once", "before", "after", "under", "over", "between", "during",
    "without", "within", "upon", "toward", "towards", "onto", "across",
    "along", "around", "behind", "beyond", "near", "through", "throughout",
    "until", "unless", "since", "whether", "if", "is", "are", "were", "have",
    "has", "had", "been", "being", "shall", "can", "may", "might", "must",
    "do", "does", "did", "he", "she", "it", "its", "him", "his", "my",
    "mine", "me",
}

STRONG_BIGRAMS = ("of the", "in the", "to the", "on the", "you can", "you must",
                  "you have", "you will", "there is", "there are", "it is",
                  "that the", "which is", "from the", "with the", "is not",
                  "are not", "does not", "did not", "do not")

EN_NEG = re.compile(
    r"\b(?:not|n't|never|none|nobody|nothing|cannot|without|neither|nor|no|"
    r"hardly|fail|fails|failed|failure)\b|\bwon't\b|\bcan't\b|\bdon't\b|"
    r"\bisn't\b|\baren't\b|\bwasn't\b|\bweren't\b|\bdidn't\b|\bdoesn't\b|"
    r"\bwouldn't\b|\bshouldn't\b|\bcouldn't\b",
    re.I)
DE_NEG = re.compile(r"\b(?:nicht|nichts|kein\w*|nie|niemals|niemand|ohne|weder|nein|"
                    r"kaum|spatestens)\b", re.I)

DU_FORM = re.compile(r"\b(?:du|dich|dir|dein|deine|deinen|deinem|deiner|deines)\b",
                     re.I)

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")

DE_NUMWORDS = re.compile(
    r"\b(?:ein|eine|einen|einem|einer|eines|zwei|drei|vier|fünf|sechs|sieben|acht|"
    r"neun|zehn|elf|zwölf|zwanzig|hundert|tausend|einmal|zweimal|dreimal|zehnmal)\w*",
    re.I)

NAME_ALLOW = {
    "havana": ("havanna",),
    "charles": ("karl",),
    "james": ("jakob",),
    "william": ("wilhelm",),
    "henry": ("heinrich",),
    "john": ("johannes",),
    "mary": ("maria",),
    "elizabeth": ("elisabeth",),
    "philip": ("philipp",),
    "nicholas": ("nikolaus",),
    "peter": ("petrus",),
}

EN_STOP_FOR_NAME = set("""the a an and or but if when while with without for from to of in on at by as
is are was were be been has have had do does did will would can could should
may must you your he she it they them their his her my our we us this that
these those which who what where why how not no never there then than so such
also only very more most one two three four five six seven eight nine ten now
again still just even ever before after during about because however although
""".split())

DE_STOP = set("""
der die das den dem des ein eine einen einem einer eines
ich du er sie es wir ihr mich mir dich dir uns euch ihn ihm ihnen
mein meine meinen meinem meiner meines dein deine deinen deinem deiner
sein seine seinen seinem seiner seines ihr ihre ihren ihrem ihrer ihres
unser unsere unseren unserem unserer eure euren eures
ist sind war waren sein sei seien bin bist hat haben hatte hatten habe hast
wird werden wurde wurden worden würde würden kann können konnte konnten
muss müssen musste sollten sollte soll wollen wollte mag mögen darf dürfen
nicht kein keine keinen keinem keiner keines nichts nie niemals niemand
und oder aber doch sondern denn wenn weil dass ob als wie so auch noch schon
nur erst sehr mehr meist viel viele man manche jeder jede jedes alle allen
allem aller alles etwas ganz gar zu zur zum auf aus bei mit nach von vor über
unter zwischen durch gegen ohne um an für hier dort da nun dann dabei dazu
daher damit sich ihrer ihres
""".split())

SUFFIX = ("ungen", "ung", "keiten", "keit", "heiten", "heit", "schaften",
          "schaft", "lichen", "lich", "ischer", "isch", "enden", "ende",
          "en", "er", "es", "em", "e", "n", "s")

# E8 术语内部一致性：英文概念 → 本项目约定的德语写法（可接受的前缀，大小写不敏感）。
# 依据 docs/德语术语基线.md 的实测表与界面词对齐表；一个概念允许多个写法时都列进来。
TERM_GROUPS = [
    ("ship", ("Schiff",), "船"),
    ("convoy", ("Konvoi",), "船队"),
    ("town", ("Stadt", "Städt", "Stadtteil"), "城镇"),
    ("goods", ("Ware",), "货物"),
    ("warehouse", ("Lagerhaus", "Lager"), "仓库"),
    ("captain", ("Kapitän",), "船长"),
    ("crew", ("Mannschaft", "Besatzung"), "船员"),
    ("cannon", ("Kanone", "Kanon"), "火炮"),
    ("cargo", ("Ladung", "Fracht"), "货物装载"),
    ("price", ("Preis",), "价格"),
    ("market", ("Markt",), "市场"),
    ("trade", ("Handel", "Handels"), "贸易"),
    ("fleet", ("Flotte",), "舰队"),
    ("governor", ("Gouverneur",), "总督"),
    ("privateer", ("Kaperschiff", "Kaperfahrer", "Kaperei"), "私掠船"),
    ("mission", ("Auftrag",), "任务"),
    ("shipyard", ("Werft",), "船厂"),
    ("sugar", ("Zucker",), "糖"),
    ("tobacco", ("Tabak",), "烟草"),
    ("cotton", ("Baumwoll",), "棉花"),
    ("wheat", ("Weizen",), "小麦"),
    ("meat", ("Fleisch",), "肉"),
    ("clothing", ("Kleidung", "Kleidungs"), "成衣"),
    ("rope", ("Seil", "Tau"), "绳索"),
    ("hemp", ("Hanf",), "大麻"),
    ("gold", ("Gold",), "黄金"),
    ("palace", ("Palast",), "宫殿"),
    ("sailor", ("Matrose", "Matrosen", "Seemann", "Seeleute"), "水手"),
    ("galleon", ("Galeone",), "大帆船"),
    ("frigate", ("Fregatte",), "护卫舰"),
    ("flute", ("Fleute",), "笛形船"),
    ("carrack", ("Karacke",), "大帆船"),
    ("barque", ("Barke",), "三桅帆船"),
    ("sloop", ("Schaluppe",), "单桅帆船"),
    ("musket", ("Muskete",), "火枪"),
    ("cutlass", ("Entermesser",), "弯刀"),
    ("bounty hunter", ("Kopfgeldjäger",), "赏金猎人"),
    ("harbor master", ("Hafenmeister",), "港务长"),
    ("treasurer", ("Schatzmeister",), "司库"),
]


def norm(text):
    """去标签、去重音、小写化用；只保留字母与数字。"""
    text = TAG.sub(" ", text)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.replace("ß", "ss")


def words(text):
    return re.findall(r"[a-zA-Z0-9']+", norm(text))


def stem(word):
    w = word.lower()
    for suf in SUFFIX:
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def content_words(text):
    out = set()
    for w in words(text):
        if len(w) < 4:
            continue
        low = w.lower()
        if low in DE_STOP:
            continue
        out.add(stem(low))
    return out


def load(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def split_names(en):
    """英文里非句首的大写词，按原文位置判断，不看词表之外的语义。"""
    names = []
    flat = TAG.sub(" ", en)
    for m in re.finditer(r"\b([A-Z][a-z]{2,})\b", flat):
        word = m.group(1)
        if word.lower() in EN_STOP_FOR_NAME:
            continue
        before = flat[:m.start()].rstrip()
        if not before or before[-1] in ".!?:":
            continue
        names.append(word)
    return names


ARTICLES = set("""
der die das den dem des ein eine einen einem einer eines
kein keine keinen keinem keiner keines
mein meine meinen meinem meiner meines dein deine deinen deinem deiner
sein seine seinen seinem seiner seines ihr ihre ihren ihrem ihrer ihres
unser unsere unseren unserem unserer eure euren eures
diese dieser dieses diesen diesem diese jene jener jenes jeden jedem jede
alle allen allem aller viele vielen viele wenige einige mehrere
""".split())

VERB_LOOKALIKE = set("""
waren reisen kehrt treiben laden speichern fest wild floss verkauf
""".split())

RETAIL_CASE = {}


def build_case_stats(retail):
    stat = {}
    for v in retail.values():
        for w in re.findall(r"[A-Za-zÄÖÜäöüß-]{4,}", TAG.sub(" ", v)):
            d = stat.setdefault(w.lower(), [0, 0])
            if w[0].isupper():
                d[0] += 1
            elif w[0].islower():
                d[1] += 1
    return stat


def check_one(en, de, retail, fr):
    """返回 [(代号, 说明)]。"""
    issues = []
    if not de.strip() or not en.strip() or de == en:
        return issues

    low_en = norm(en).lower()
    low_de = norm(de).lower()

    # E1 英文残留
    hits = sorted({w for w in re.findall(r"[a-zA-Z']+", low_de) if w in EN_ONLY})
    bigrams_hit = [b for b in STRONG_BIGRAMS
                   if re.search(r"\b" + b.replace(" ", r"\s+") + r"\b", low_de)]
    if len(hits) >= 2 or bigrams_hit:
        tag = ",".join(bigrams_hit[:3] + hits[:6])
        issues.append(("E1", "疑似英文残留：" + tag))

    # E2 否定
    en_neg = bool(EN_NEG.search(low_en))
    de_neg = bool(DE_NEG.search(low_de))
    if en_neg != de_neg:
        label = "有" if en_neg else "无"
        issues.append(("E2", "否定不一致：英文" + label + "否定"))

    # E3 标点
    eq, ee = en.count("?"), en.count("!")
    dq, dse = de.count("?"), de.count("!")
    if eq != dq or ee != dse:
        msg = "标点不一致：英文 ?%d !%d / 德语 ?%d !%d" % (eq, ee, dq, dse)
        issues.append(("E3", msg))

    # E4 专名：以零售德语为锚（见下），这里只准备小写文本
    flat_de = norm(de).lower()
    # E5 数字（千位分隔符 . 与 , 等价，只比数字串本身）
    def digits(s):
        flat = PH.sub(" ", TAG.sub(" ", s))
        return {d.replace(".", "").replace(",", "") for d in NUM_RE.findall(flat)}

    en_nums = digits(en)
    de_nums = digits(de)
    if en_nums and de_nums:
        missing = sorted(en_nums - de_nums)
        if missing:
            issues.append(("E5", "数字可能没保留：" + ",".join(missing[:5])))
    elif en_nums and not de_nums and not DE_NUMWORDS.search(de):
        issues.append(("E5", "数字全部消失：" + ",".join(sorted(en_nums)[:5])))

    # E4b 专名（以零售德语为锚：零售保留了的名字，我们也应保留）
    if retail.strip() and retail != en:
        kept_en = [n for n in split_names(en) if n in retail]
        for name in kept_en:
            if norm(name).lower() not in flat_de:
                issues.append(("E4", "零售保留的专名我们没保留：" + name))
                break
    if retail.strip() and retail != en:
        rw = content_words(retail)
        if len(rw) >= 3:
            own = content_words(de)
            common = len(rw & own)
            ratio = common / len(rw)
            if ratio < 0.30:
                msg = "与零售德语实词交集 %.0f%%（%d/%d）" % (ratio * 100,
                                                             common, len(rw))
                issues.append(("E6", msg))

    # E7 敬称
    m = DU_FORM.search(norm(de))
    if m:
        issues.append(("E7", "出现非敬称形式：" + m.group(0)))

    # E8 术语内部一致性（占位符与标签里的英文不算）
    en_terms = PH.sub(" ", TAG.sub(" ", en)).lower()
    de_terms = PH.sub(" ", low_de)
    for term, forms, label in TERM_GROUPS:
        if not re.search(r"\b" + term.replace(" ", r"\s+") + r"s?\b", en_terms):
            continue
        if any(norm(f).lower() in de_terms for f in forms):
            continue
        issues.append(("E8", "术语偏离（%s：应含 %s）" % (label, forms[0])))

    # E9 名词大小写（限定在冠词后面，避开 waren/reisen 这类同形动词）
    if RETAIL_CASE:
        flat = TAG.sub(" ", de)
        toks = [(m.group(0), m.start()) for m in
                re.finditer(r"[A-Za-zÄÖÜäöüß-]{3,}", flat)]
        for idx in range(1, len(toks)):
            tok, _pos = toks[idx]
            prev = toks[idx - 1][0].lower()
            if not tok[0].islower() or tok.lower() in VERB_LOOKALIKE:
                continue
            if prev not in ARTICLES:
                continue
            stat = RETAIL_CASE.get(tok.lower())
            if not stat:
                continue
            cap, low = stat
            if cap >= 2 and cap / (cap + low) >= 0.85:
                issues.append(("E9", "名词该大写：" + tok))
                break

    return issues


def french_neg_notes(en, fr):
    """英文与法语否定极性不一致 → 这句英文本身有歧义。"""
    if not fr.strip() or fr == en:
        return ""
    en_neg = bool(EN_NEG.search(norm(en)))
    fr_neg = bool(re.search(r"\b(?:ne|n'|pas|jamais|aucun|rien|personne|sans|ni)\b",
                            norm(fr), re.I))
    if en_neg != fr_neg:
        return "英文%s否定，法语%s否定" % ("有" if en_neg else "无",
                                     "有" if fr_neg else "无")
    return ""


def main():
    ap = argparse.ArgumentParser(description="德语交叉核对")
    ap.add_argument("--json", default="")
    ap.add_argument("--md", default="")
    ap.add_argument("--only", default="", help="只跑部分检查项，如 E1,E4")
    ap.add_argument("--limit", type=int, default=15)
    args = ap.parse_args()

    want = {x.strip().upper() for x in args.only.split(",") if x.strip()}
    en = load(EN_PATH)
    de = load(DE_PATH)
    retail = load(RETAIL_PATH)
    fr = load(FR_PATH)

    global RETAIL_CASE
    RETAIL_CASE = build_case_stats(retail)
    diff = sum(1 for k in en if de.get(k, "") != en[k])
    results, fr_split, counts = [], [], {}
    for rid in en:
        found = check_one(en[rid], de.get(rid, ""), retail.get(rid, ""),
                          fr.get(rid, ""))
        if want:
            found = [i for i in found if i[0] in want]
        if found:
            results.append({
                "id": rid,
                "en": en[rid],
                "de": de.get(rid, ""),
                "retail": retail.get(rid, ""),
                "fr": fr.get(rid, ""),
                "issues": [{"code": c, "detail": d} for c, d in found],
            })
            for c, _d in found:
                counts[c] = counts.get(c, 0) + 1
        if de.get(rid, "") != en[rid]:
            note = french_neg_notes(en[rid], fr.get(rid, ""))
            if note:
                fr_split.append({"id": rid, "note": note, "en": en[rid],
                                 "de": de[rid], "fr": fr.get(rid, "")})

    print("键总数 %d，已译 %d" % (len(en), diff))
    for code in sorted(counts):
        print("  %s: %d" % (code, counts[code]))
    print("  F1(法语否定分歧): %d" % len(fr_split))
    for item in results[:args.limit]:
        print(item["id"], item["issues"][0]["detail"])
        print("   en:", item["en"][:90])
        print("   de:", item["de"][:90])

    if args.json:
        parent = os.path.dirname(os.path.abspath(args.json))
        os.makedirs(parent, exist_ok=True)
        with open(args.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"counts": counts, "keys": len(en), "translated": diff,
                       "issues": results, "french_split": fr_split},
                      f, ensure_ascii=False, indent=1)
        print("JSON →", args.json)

    if args.md:
        write_md(args.md, counts, len(en), diff, results, fr_split, args.limit)
        print("Markdown →", args.md)
    return 0


NAMES = {"E1": "英文残留", "E2": "否定不一致", "E3": "标点不一致",
         "E4": "专名缺失", "E5": "数字缺失", "E6": "与零售无交集",
         "E7": "敬称破例", "E8": "术语偏离", "E9": "名词大小写"}


def write_md(path, counts, total, diff, results, fr_split, limit):
    lines = ["# 德语交叉核对（机械项）", "",
             "> 由 `python src/tools/analysis/de_crosscheck.py` 生成。",
             "> 只看词面事实：英文基准、零售德语措辞、同版法语否定分歧；",
             "> 不判断语义是否优美，语义仍要人看。", "",
             "## 一、总览", "",
             "| 项 | 数值 |", "| --- | --- |",
             "| 键总数 | %d |" % total,
             "| 与英文不同 | %d |" % diff]
    for code in sorted(NAMES):
        lines.append("| %s %s | %d |" % (code, NAMES[code], counts.get(code, 0)))
    lines.append("| F1 法语否定分歧 | %d |" % len(fr_split))

    for code in sorted(NAMES):
        sel = [r for r in results if any(i["code"] == code for i in r["issues"])]
        if not sel:
            continue
        lines += ["", "## %s %s（%d 条）" % (code, NAMES[code], len(sel)), ""]
        for r in sel[:limit]:
            detail = next(i["detail"] for i in r["issues"] if i["code"] == code)
            lines.append("- `%s` %s" % (r["id"], detail))
            lines.append("  - en: %s" % r["en"].replace("\n", " ")[:160])
            lines.append("  - de: %s" % r["de"].replace("\n", " ")[:160])
            if code == "E6" and r["retail"]:
                lines.append("  - 零售: %s" % r["retail"].replace("\n", " ")[:160])
        if len(sel) > limit:
            lines.append("")
            lines.append("其余 %d 条见 JSON。" % (len(sel) - limit))

    if fr_split:
        lines += ["", "## F1 法语否定分歧（%d 条）" % len(fr_split), "",
                  "英文与法语的否定极性不一致，说明这句本身有歧义；德语按英文落的，"
                  "需要对照法语判断英文是否写反了。", ""]
        for r in fr_split[:limit]:
            lines.append("- `%s` %s" % (r["id"], r["note"]))
            lines.append("  - en: %s" % r["en"].replace("\n", " ")[:160])
            lines.append("  - fr: %s" % r["fr"].replace("\n", " ")[:160])
            lines.append("  - de: %s" % r["de"].replace("\n", " ")[:160])

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

