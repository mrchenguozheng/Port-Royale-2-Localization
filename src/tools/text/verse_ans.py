# -*- coding: utf-8 -*-
"""诗谜谜底队列：把 glossary\\verse_ans.toml 里填好的 ans 落进六语译文。

谜面在 09 卷第六十四节定义的 verse 区间里，整片不挂 ref/lit/term，只允许 [ans:实体|线索,…]。
这个工具只管那一件事：

    python src\\tools\\text\\verse_ans.py --list     # 看 41 条 / 29 组，谁还没填
    python src\\tools\\text\\verse_ans.py --apply    # 把填好的组写进六语译文

--apply 的判据：
  · ans 必须是 entities.toml 里的实体键；若它是城镇表里的城名但还没登记，就顺带把
    六语译名从译文行里取出来，登记进 entities.toml 与 names/<lang>.toml；
  · 或者 ans 是 marks.ANS_KEYS 里的方位键（north/east/southeast…，以及否定的
    not_north/not_southeast…）：谜面只给朝向、给不出城名的那批诗谜用这种谜底，
    不登记实体、不查译名；
  · 六语线索都不能空，只收英文逗号，每条线索都要出现在该语言自己的谜面正文里；
  · 已经标成同值的组直接跳开（可重复跑），标成别的值则报错，不覆盖。
"""
import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import toml_io
import marks as MK

QUEUE = os.path.join(ROOT, "glossary", "verse_ans.toml")
EN_PATH = os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")
ENTITIES = os.path.join(ROOT, "src", "data", "names", "entities.toml")
NAMES_DIR = os.path.join(ROOT, "src", "data", "names")
TRANS = os.path.join(ROOT, "src", "translations")
LANGS = ("zh", "de", "es", "fr", "ja", "ru")
TOWN_RANGE = ("0xc77f4c7a", "0xc77f4e47")
ANS_MARK = re.compile(r"^\[ans:[^\[\]]*\]")
REF_ROW = re.compile(r"^\[ref:([^\[\]]*)\]$")


def load_queue():
    with open(QUEUE, "rb") as f:
        doc = tomllib.load(f)
    return doc.get("group", [])


def load_rows():
    en, _o = toml_io.read_doc(EN_PATH)
    return en, {l: toml_io.read_doc(os.path.join(TRANS, "%s.toml" % l))[0] for l in LANGS}


def town_ids():
    """城名（小写）→ 城镇表里的 id。"""
    en, _rows = load_rows()
    lo, hi = (int(x, 16) for x in TOWN_RANGE)
    out = {}
    for k in en:
        if lo <= int(k, 16) <= hi:
            name = en[k].strip()
            if name:
                out.setdefault(name.lower(), k)
    return out


def expand_name(lang, row):
    """城镇行 → 纯名字：`[ref:X]` 取名字表，否则用行内文本。"""
    m = REF_ROW.match(row.strip())
    if not m:
        return row.strip()
    names, _n = toml_io.read_doc(os.path.join(NAMES_DIR, "%s.toml" % lang))
    return (names.get(m.group(1), {}) or {}).get("default", "").strip()


def register_entity(name, town_id, rows):
    """登记成实体：entities.toml 一条 + names/<lang>.toml 一版（缺哪个语就报错）。

    两张表都按行追加文本，不经过 toml_io 的写回——名字表的值是 `default = "…"` 这种
    单纯表，嵌套写回没有必要，手写两行更不容易碰坏别的东西。
    """
    if os.path.isfile(ENTITIES):
        entities, _e = toml_io.read_doc(ENTITIES)
        if name in entities:
            return False
    with io.open(ENTITIES, "a", encoding="utf-8", newline="") as f:
        f.write('\n["%s"]\nkind = "town"\nnote = "诗谜谜底；登记来给 [ans:] 用"\n' % name)
    for lang in LANGS:
        path = os.path.join(NAMES_DIR, "%s.toml" % lang)
        doc, _order = toml_io.read_doc(path)
        if name in doc:
            continue
        value = expand_name(lang, rows[lang].get(town_id, ""))
        if not value:
            raise SystemExit("%s 里推不出「%s」的译名（城镇行 %s 是空的）"
                             % (lang, name, town_id))
        with io.open(path, "a", encoding="utf-8", newline="") as f:
            f.write('\n["%s"]\ndefault = "%s"\n' % (name, value.replace('"', '\\"')))
    return True


def split_clues(text, lang):
    text = (text or "").strip()
    if not text:
        raise SystemExit("%s 的线索是空的——至少写一条" % lang)
    if "，" in text:
        raise SystemExit("%s 的线索里有全角逗号，只收英文逗号" % lang)
    clues = [c.strip() for c in text.split(",")]
    if any(not c for c in clues):
        raise SystemExit("%s 的线索里有空项（连着两个逗号，或首尾多逗号）" % lang)
    return clues


def cmd_list(all_langs=False):
    en, rows = load_rows()
    groups = load_queue()
    done = 0
    for i, g in enumerate(groups, 1):
        ids = g.get("ids", [])
        ans = (g.get("ans") or "").strip()
        marked = any("[ans:" in rows["zh"].get(k, "") for k in ids)
        done += 1 if marked else 0
        print("[%02d] %-3s %s" % (i, "已标" if marked else "待填", ",".join(ids)))
        print("     EN %s" % en.get(ids[0], "")[:100].replace("\n", " "))
        print("     ZH %s" % rows["zh"].get(ids[0], "")[:80].replace("\n", " "))
        if all_langs:
            # 线索必须在每门语言的谜面里都能找到，逐门读一遍省得来回翻 toml
            for lang in LANGS:
                if lang == "zh":
                    continue
                print("     %-2s %s" % (lang.upper(),
                                        rows[lang].get(ids[0], "").replace("\n", " ")))
        if ans:
            print("     ans %s" % ans)
    print("\n%d 组，已标 %d 组，待填 %d 组" % (len(groups), done, len(groups) - done))


def cmd_apply():
    en, rows = load_rows()
    groups = load_queue()
    towns = town_ids()
    changed = skipped = 0
    for g in groups:
        ans = (g.get("ans") or "").strip()
        if not ans:
            continue
        ids = g.get("ids", [])
        assert ids, "组里没有 id"
        for k in ids:
            assert k in en, "队列里的 %s 不在英文原文里" % k

        if ans in MK.ANS_KEYS:
            pass            # 方位谜底不进 entities.toml：它不是专名，也没有译名可登记
        elif not os.path.isfile(ENTITIES) or ans not in toml_io.read_doc(ENTITIES)[0]:
            tid = towns.get(ans.lower())
            if not tid:
                raise SystemExit("谜底「%s」既不在 entities.toml、城镇表，也不是方位键"
                                 "（方位键见 marks.ANS_DIRECTIONS）" % ans)
            register_entity(ans, tid, rows)
            print("登记实体 %s（城镇行 %s）" % (ans, tid))

        wanted, ok = {}, True
        for lang in LANGS:
            clues = split_clues((g.get("clues") or {}).get(lang, ""), lang)
            text = ANS_MARK.sub("", rows[lang].get(ids[0], ""))
            for c in clues:
                if c.casefold() not in text.casefold():
                    raise SystemExit("%s 的线索「%s」没出现在谜面里（%s）"
                                     "——谜面推不出这个谜底，或者线索该换" % (lang, c, ids[0]))
            wanted[lang] = "[ans:%s|%s]" % (ans, ",".join(clues))

        already = [ANS_MARK.match(rows[lang].get(k, "")) for k in ids for lang in LANGS]
        if [m.group(0) if m else None for m in already] == \
                [wanted[lang] for k in ids for lang in LANGS]:
            skipped += 1
            continue
        present = [m.group(0) for m in already if m]
        if present:
            raise SystemExit("%s 已有标注 %s，与队列填的不同；先人工核对"
                             % (ids, present[0]))

        for lang in LANGS:
            path = os.path.join(TRANS, "%s.toml" % lang)
            doc, order = toml_io.read_doc(path)
            for k in ids:
                assert "[ans:" not in doc[k], (lang, k)
                doc[k] = wanted[lang] + doc[k]
            toml_io.write_doc_atomic(path, doc, order=order, header=toml_io.head_lines(path))
        changed += 1
        print("落标注 %s -> %s" % (",".join(ids), ans))
    print("\n本次落 %d 组，跳过（已是该值）%d 组" % (changed, skipped))


def main():
    ap = argparse.ArgumentParser(description="诗谜谜底队列")
    ap.add_argument("--list", action="store_true", help="列出各组与填写状态")
    ap.add_argument("--langs", action="store_true",
                    help="配合 --list：六门谜面全打出来（线索要逐门核对）")
    ap.add_argument("--apply", action="store_true", help="把填好的谜底落进六语译文")
    args = ap.parse_args()
    if args.list:
        cmd_list(args.langs)
    elif args.apply:
        cmd_apply()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
