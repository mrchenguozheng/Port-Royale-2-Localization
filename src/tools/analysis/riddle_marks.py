#!/usr/bin/env python3
# coding: utf-8
"""riddle_marks.py —— 诗谜标注的骨架搬运与核对（新语言不再手抄一遍）。

为什么要有这个：`[riddle:…]` 里只有 `clue=` 是语言相关的，其余
`answer` / `group` / `level` / `certainty` / `source` 都是**谜题本身的元数据**，
跟译文用哪种字无关。可这些字段此前只能从已核过的语言（ko）一条条抄，
抄错一个字就是 `text_lint` 的 E；而 `clue=` 更麻烦：`marks.py` 要求每一项都
**逐字**出现在本语言谜面正文里（大小写都算），抄来的韩文 clue 必然对不上
——本轮 pl 就因此被拦了 5 条。

本脚本做两件事，都不猜谜底：

1. 从 `--from`（已核语言）搬 answer / group / level / certainty / source，
   副本照旧写成 `[riddle:copy=代表键]`（独占整行）；
2. 用 `--clues` 给的每行 clue 核对：每一项必须真的在**本语言**谜面里，
   否则拒绝出表并点名哪一条的哪个词没命中。

clue 本身仍要人写——那是「这条谜面凭什么指向这座城」的判断，机器没有。
缺 clue 的条目会被逐条列出，不会悄悄留空。

    python src/tools/analysis/riddle_marks.py --lang pl --from ko \
        --clues build/pl_riddle_clues.json --out build/pl_riddle_map.json

产出的表直接喂 `translate.py apply --lang pl --map …`。退出码：有任何
「clue 缺失 / clue 不在谜面 / group 成员对不上」时返回 1，且不写表。
"""
import argparse
import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "tools"),
          os.path.join(ROOT, "src", "tools", "text")):
    if p not in sys.path:
        sys.path.insert(0, p)

import terms_check as TC                      # noqa: E402

EN = os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")
TR = os.path.join(ROOT, "src", "translations", "%s.toml")

MARK = re.compile(r"\[riddle[^]]*\]")


def _load(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def _fields(mark):
    inner = mark[len("[riddle:"):-1]
    return [kv for kv in inner.split(";") if kv]


def _kv(items):
    out = {}
    for kv in items:
        if "=" in kv:
            k, v = kv.split("=", 1)
            out[k] = v
    return out


def _body(text):
    return MARK.sub("", text or "").strip()


def _clue_items(raw):
    return [x.strip() for x in raw.split(",") if x.strip()]


def body_conflict(target, vid, ref):
    """本条正文与代表那条是否不同（不同就意味着写 copy 会覆盖掉一份已有译法）。"""
    return (_body(str(target.get(vid, ""))).strip()
            != _body(str(target.get(ref, ""))).strip())


def build(lang, from_lang, clues):
    en = _load(EN)
    target = _load(TR % lang)
    donor = _load(TR % from_lang)
    _g, _ig, verse = TC.load_terms()
    vids = sorted(TC.verse_ids(verse, en), key=lambda x: int(x, 16))

    problems, out, answer_ids, covered = [], {}, [], set()
    body_diff = []          # 组内成员正文与代表不一致：写 copy 会把本条正文顶掉
    for vid in vids:
        marks = MARK.findall(str(donor.get(vid, "") or ""))
        if not marks:
            continue
        covered.add(vid)
        items = _fields(marks[0])
        kv = _kv(items)
        if "copy" in kv:
            ref = kv["copy"].strip()
            if not ref.startswith("0x"):
                ref = "0x" + ref
            out[vid] = "[riddle:copy=%s]" % ref
            continue
        answer_ids.append(vid)
        clue = clues.get(vid)
        if not clue:
            problems.append("%s：缺 clue（谜面：%s）" % (vid, _body(target.get(vid, ""))[:60]))
            continue
        body = _body(str(target.get(vid, "")))
        missing = [w for w in _clue_items(clue) if w not in body]
        if missing:
            problems.append("%s：clue 词不在本语言谜面里：%s" % (vid, "、".join(missing)))
            continue
        rest = [kv_item for kv_item in items if not kv_item.startswith("clue=")]
        if any(kv_item.startswith("level=") for kv_item in rest):
            merged = []
            for kv_item in rest:
                if kv_item.startswith("level="):
                    merged.append("clue=" + clue)
                merged.append(kv_item)
        else:
            merged = rest + ["clue=" + clue]
        out[vid] = "[riddle:%s]%s" % (";".join(merged), body)

    # 副本必须指向本语言里真的有谜底的那一条，且组里列出的成员都得在谜面集合里。
    for vid, mark in out.items():
        m = re.fullmatch(r"\[riddle:copy=(0x[0-9a-fA-F]{8})\]", mark)
        if not m:
            continue
        ref = m.group(1)
        if ref == vid:
            problems.append("%s：copy 指向自己" % vid)
        elif ref not in answer_ids:
            problems.append("%s：copy 指向的 %s 不是带谜底的代表条目" % (vid, ref))
        # `copy=` 说的是「本条没有自己的谜面，正文取代表那条」。本语言这条的正文
        # 若与代表不同，落盘后就会被顶掉——那不是搬运，是覆盖一份已有的译法，
        # 所以默认报错，逼人选：要么把这条算成代表（自己带谜底），要么统一正文。
        elif body_conflict(target, vid, ref):
            body_diff.append("%s → %s" % (vid, ref))
    by_id = {vid: out[vid] for vid in answer_ids if vid in out}
    for vid, mark in by_id.items():
        kv = _kv(_fields(mark))
        for member in (kv.get("group") or "").split(","):
            member = member.strip()
            if not member:
                continue
            full = member if member.startswith("0x") else "0x" + member
            if full not in vids:
                problems.append("%s：group 里的 %s 不是诗谜条目" % (vid, member))
    # 组内每个成员都得有标注（代表或副本），否则那几条谜面就没有谜底。
    for vid in vids:
        if vid not in covered:
            problems.append("%s：%s 里没有 [riddle:…]，无从搬" % (vid, from_lang))
    return out, problems, len(answer_ids), len(vids), body_diff


def main(argv=None):
    ap = argparse.ArgumentParser(description="诗谜标注骨架搬运")
    ap.add_argument("--lang", required=True, help="目标语言代码")
    ap.add_argument("--from", dest="from_lang", required=True, help="已核语言代码（如 ko）")
    ap.add_argument("--clues", help="每条代表条目的 clue（JSON：{id: \"词, 词\"}）")
    ap.add_argument("--out", help="输出映射表（喂 translate.py apply --map）")
    ap.add_argument("--dump", action="store_true",
                    help="只把待写 clue 的条目列出来（含本语言谜面），不校验")
    ap.add_argument("--strict", action="store_true",
                    help="副本正文与代表不同就拒绝出表（默认只逐条列出并继续）")
    args = ap.parse_args(argv)

    en = _load(EN)
    _g, _ig, verse = TC.load_terms()
    vids = sorted(TC.verse_ids(verse, en), key=lambda x: int(x, 16))
    if args.dump:
        target = _load(TR % args.lang)
        donor = _load(TR % args.from_lang)
        for vid in vids:
            marks = MARK.findall(str(donor.get(vid, "") or ""))
            if marks and "copy=" in marks[0]:
                continue
            print("%s\t%s" % (vid, _body(str(target.get(vid, "")))))
        return 0

    if not args.clues:
        ap.error("--clues 必填（或缺 clue；先用 --dump 看每条的谜面）")
    with open(args.clues, encoding="utf-8") as f:
        clues = json.load(f)

    out, problems, reps, total, body_diff = build(args.lang, args.from_lang, clues)
    if body_diff:
        print("诗谜 %d 条副本的正文与代表不同（照写 copy 会用代表的正文覆盖本条）："
              % len(body_diff))
        for item in body_diff:
            print("  " + item)
        print("  —— 要保留本条自己的写法，就把该条升为代表（自己带谜底）；"
              "要统一，就照出表。")
        if args.strict:
            return 1
    if problems:
        print("诗谜标注 %d 条没能生成：\n" % len(problems))
        for p in problems:
            print("  " + p)
        return 1

    print("诗谜 %d 条：代表 %d、副本 %d（谜底与分组取自 %s）"
          % (total, reps, total - reps, args.from_lang))
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("映射表：%s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
