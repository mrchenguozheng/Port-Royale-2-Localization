#!/usr/bin/env python
# coding: utf-8
"""src/tools/pack/split_batches.py — 把 3548 条译文拆成可并行的批次文件

    python src/tools/pack/split_batches.py --lang ko
    python src/tools/pack/split_batches.py --lang ko --blocks 12 --out build/qa/batches/ko

输出（默认 build\\qa\\batches\\<语言>\\）：

    manifest.json    参数、块边界、每块条数
    manifest.tsv     同一件事的表格版，给人看
    dups.json        「同文组」：{首条键: [其余同文键…]}
    00-terms.jsonl   术语与专名（9 组，必须先做）
    01-verse.jsonl   诗谜槽位（32 组，整组做）
    02-keep.jsonl    纯符号 / 必须原样保留英文（不用译，只登记）
    b01.jsonl …      主池，按 en 表内顺序切块

每行 JSON：

    {"key": "0xc46f793a", "en": "…", "words": 3,
     "flags": ["ph", "tag"], "refs": {"de": "…", "fr": "…"}, "text": ""}

译者只填 `text`（其余字段别动）。`flags` 里 `dup-of:<键>` 表示这条与 <键>
同文，只要 <键> 译好，merge 会自动回填，不必单译。

分块的依据是 **en.gog_1.1.2.3.toml 的文件顺序**（键值不是数值升序，首键
0xc46f793a、尾键 0x3b81bb81）。文件顺序就是引擎字符串表顺序，同屏同功能的
串天然相邻，按词数或按主题切都会把一条按钮和它自己的 tooltip 分到两批。

【不做的事】不写译文 TOML，不做占位符校验 —— 那是 merge_batches.py 的事。
"""

import argparse
import io
import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))     # src\tools\pack
TOOLS = os.path.dirname(HERE)                        # src\tools
SRC = os.path.dirname(TOOLS)                         # src
ROOT = os.path.dirname(SRC)                          # 仓库根
for p in (TOOLS, ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from text import toml_io as TI                       # noqa: E402
from compile_pack import KEEP_ORIGINAL               # noqa: E402
from shared.core.validate import tag_counts, tokens  # noqa: E402

BASE = "en.gog_1.1.2.3"
REF_LANGS = ("de.retail-1.0.0", "fr.gog_1.1.2.42", "es.retail-1.0.0",
             "pl.retail-1.0.0", "ru.retail-1.0.0")
ORIG = os.path.join(SRC, "orig")
TRANS = os.path.join(SRC, "translations")
GLOSSARY = os.path.join(ROOT, "glossary")
DEFAULT_OUT = os.path.join(ROOT, "build", "qa", "batches")

#: 去掉占位符/标签后一个词都没有 = 纯符号、纯数字。不用译。
_SYMBOL = re.compile(r"^[^a-zA-Z]*$")
#: 只用于切分次数的上限保护，别让它变成第二套规则。
MAX_BLOCKS = 64


def load_terms(path, en_doc):
    """术语成员：显式 ids + range 区间内长度不超 max_len 的条目。"""
    if not os.path.isfile(path):
        return set()
    with open(path, "rb") as fh:
        doc = tomllib.load(fh)
    groups = doc.get("group", [])
    if isinstance(groups, dict):
        groups = [groups]
    out = set()
    for g in groups:
        ids = list(g.get("ids") or [])
        rng = g.get("range")
        if rng:
            lo, hi = int(rng[0], 16), int(rng[1], 16)
            limit = g.get("max_len") or 10 ** 9
            for k, v in en_doc.items():
                n = int(k, 16)
                if lo <= n <= hi and len(v) <= limit:
                    ids.append(k)
        out |= {str(k).lower() for k in ids}
    return out


def load_verse(path):
    """诗谜槽位：verse_ans.toml 里每个 group 的 ids。"""
    if not os.path.isfile(path):
        return set()
    with open(path, "rb") as fh:
        doc = tomllib.load(fh)
    return {str(k).lower() for g in doc.get("group", []) for k in g.get("ids", [])}


def word_count(text):
    plain = re.sub(r"@[a-zA-Z]\$[^$]*\$|<[^>]*>|%[0-9]+", "", text or "")
    return len(" ".join(plain.split()).split())


def flags_of(en_text):
    out = []
    if tokens(en_text):
        out.append("ph")
    # tag_counts 总会带一个 "|": 0 的计数，直接 bool() 会永远为真。
    if sum(tag_counts(en_text).values()):
        out.append("tag")
    return out


def dup_groups(keys, en_doc):
    """同文组：返回 ({首键: [成员…]}, {成员: 首键})。只在主池内算。"""
    seen = {}
    for k in keys:
        seen.setdefault(en_doc[k], []).append(k)
    leaders, member_of = {}, {}
    for members in seen.values():
        if len(members) < 2:
            continue
        head = members[0]
        leaders[head] = members[1:]
        for m in members[1:]:
            member_of[m] = head
    return leaders, member_of


def build_plan(en_path, terms_path, verse_path, blocks=12, keep=None):
    """返回 (plan, en_doc)。plan 是纯数据，便于测试。"""
    if blocks < 1 or blocks > MAX_BLOCKS:
        raise ValueError("块数必须在 1..%d 之间" % MAX_BLOCKS)
    en_doc, order = TI.read_doc(en_path)
    keep = set(keep or KEEP_ORIGINAL)
    terms = load_terms(terms_path, en_doc)
    verse = load_verse(verse_path)

    special = {}
    for k in order:
        if k in keep:
            special[k] = "keep"
        elif k in verse:
            special[k] = "verse"
        elif k in terms:
            special[k] = "terms"
        elif _SYMBOL.match("".join((en_doc[k] or "").split())):
            special[k] = "keep"

    pool = [k for k in order if k not in special]
    leaders, member_of = dup_groups(pool, en_doc)
    # 同文组成员不进翻译批，只留首条；回填信息写进 dups.json。
    translatable = [k for k in pool if k not in member_of]

    n = min(blocks, len(translatable)) or 1
    size = (len(translatable) + n - 1) // n
    parts = [translatable[i * size:(i + 1) * size] for i in range(n)]
    parts = [p for p in parts if p]

    batches = []
    for kind, name in (("terms", "00-terms"), ("verse", "01-verse"),
                       ("keep", "02-keep")):
        keys = [k for k in order if special.get(k) == kind]
        batches.append({"id": name, "kind": kind, "keys": keys})
    for i, part in enumerate(parts, 1):
        batches.append({"id": "b%02d" % i, "kind": "main", "keys": part})

    plan = {
        "baseline": os.path.basename(en_path),
        "blocks": len(parts),
        "order": order,
        "special": special,
        "dups": leaders,
        "member_of": member_of,
        "batches": batches,
        "totals": {
            "entries": len(order),
            "terms": sum(1 for v in special.values() if v == "terms"),
            "verse": sum(1 for v in special.values() if v == "verse"),
            "keep": sum(1 for v in special.values() if v == "keep"),
            "pool": len(pool),
            "dups_fillable": len(member_of),
        },
    }
    return plan, en_doc


def load_refs():
    out = {}
    for code in REF_LANGS:
        path = os.path.join(ORIG, code + ".toml")
        if os.path.isfile(path):
            out[code] = TI.read_doc(path)[0]
    return out


def emit(plan, en_doc, out_dir, refs=None, have=None):
    refs = refs or {}
    have = have or {}
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for b in plan["batches"]:
        rows = []
        for k in b["keys"]:
            row = {
                "key": k,
                "en": en_doc[k],
                "words": word_count(en_doc[k]),
                "flags": flags_of(en_doc[k]),
                "refs": {c: refs[c][k] for c in refs
                         if k in refs[c] and refs[c][k] != en_doc[k]},
                "text": "",
            }
            head = plan["member_of"].get(k)
            if head:
                row["flags"].append("dup-of:" + head)
            elif k in plan["dups"]:
                row["flags"].append("dup-lead:%d" % len(plan["dups"][k]))
            if have.get(k) and have[k] != en_doc[k]:
                row["have"] = have[k]
            rows.append(row)
        path = os.path.join(out_dir, b["id"] + ".jsonl")
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        written.append({"id": b["id"], "kind": b["kind"], "rows": len(rows),
                        "first": b["keys"][0] if b["keys"] else "",
                        "last": b["keys"][-1] if b["keys"] else "",
                        "file": os.path.basename(path)})

    manifest = {
        "baseline": plan["baseline"],
        "blocks": plan["blocks"],
        "totals": plan["totals"],
        "batches": written,
    }
    with io.open(os.path.join(out_dir, "manifest.json"), "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with io.open(os.path.join(out_dir, "manifest.tsv"), "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write("batch\tkind\trows\tfirst\tlast\n")
        for w in written:
            fh.write("%s\t%s\t%d\t%s\t%s\n" % (w["id"], w["kind"], w["rows"],
                                               w["first"], w["last"]))
    with io.open(os.path.join(out_dir, "dups.json"), "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({h: m for h, m in plan["dups"].items()},
                            ensure_ascii=False, indent=2) + "\n")
    return manifest


def main():
    ap = argparse.ArgumentParser(description="按表内顺序切出译文批次")
    ap.add_argument("--lang", required=True, help="目标语言代码（决定输出目录与已有译文）")
    ap.add_argument("--blocks", type=int, default=12, help="主池切几块，默认 12")
    ap.add_argument("--out", default="", help="输出目录，默认 build\\qa\\batches\\<语言>")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的批次目录")
    ap.add_argument("--json", action="store_true", help="只输出 JSON 摘要")
    args = ap.parse_args()

    out_dir = args.out or os.path.join(DEFAULT_OUT, args.lang)
    if os.path.isdir(out_dir) and os.listdir(out_dir) and not args.force:
        print("[失败] 目录里已有批次文件：%s\n确认要覆盖就加 --force。" % out_dir,
              file=sys.stderr)
        return 2

    plan, en_doc = build_plan(os.path.join(ORIG, BASE + ".toml"),
                              os.path.join(GLOSSARY, "terms.toml"),
                              os.path.join(GLOSSARY, "verse_ans.toml"),
                              blocks=args.blocks)
    refs = load_refs()

    have = {}
    target = os.path.join(TRANS, args.lang + ".toml")
    if os.path.isfile(target):
        have = TI.read_doc(target)[0]

    manifest = emit(plan, en_doc, out_dir, refs=refs, have=have)
    manifest["out"] = out_dir
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    t = manifest["totals"]
    print("基准 %s：%d 条" % (manifest["baseline"], t["entries"]))
    print("  术语 %d / 诗谜 %d / 原样 %d / 主池 %d（其中同文可回填 %d）"
          % (t["terms"], t["verse"], t["keep"], t["pool"], t["dups_fillable"]))
    print("  主池切 %d 块" % manifest["blocks"])
    for w in manifest["batches"]:
        print("  %-8s %-5s %4d 条  %s .. %s"
              % (w["id"], w["kind"], w["rows"], w["first"], w["last"]))
    print("\n输出：%s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
