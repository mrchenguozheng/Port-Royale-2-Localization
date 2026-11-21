#!/usr/bin/env python
# coding: utf-8
"""src/tools/pack/merge_batches.py — 把批次译文合并回 src\\translations\\<语言>.toml

    python src/tools/pack/merge_batches.py --lang ko
    python src/tools/pack/merge_batches.py --lang ko --in build/qa/batches/ko --dry-run
    python src/tools/pack/merge_batches.py --lang ko --in b03.jsonl --no-compile

这是**唯一**把批次译文写进 TOML 的地方，逐条规则：

    * 键必须在目标译文文件里存在，且不重复；
    * 占位符多重集、标签次数与英文原文一致（shared\\core\\validate.py 同一份规则）；
    * 空白 text 视为「本批没译」，跳过不改；
    * KEEP_ORIGINAL 里的条目拒写（编译期会强制回英文，写了也是白写）；
    * 同文组（dups.json）：首条译好后，成员默认自动回填，`--no-fill-dups` 关掉。

任一条 error 就整批不写，报告全部问题后再退出（不会留半成品）。写入成功后
默认立刻 compile_pack --strict 出包，失败自动还原 TOML。

【不做的事】不部署进游戏（引擎包只落 build\\），不建语言文件（那是 new_lang.py）。
"""

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)
for p in (TOOLS, ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from text import toml_io as TI                       # noqa: E402
from compile_pack import KEEP_ORIGINAL               # noqa: E402
from shared.core.validate import check_text          # noqa: E402
from build_artifacts import compile_pack             # noqa: E402

BASE = "en.gog_1.1.2.3"
ORIG = os.path.join(SRC, "orig")
#: 英文基准读清洁版（`ref_clean.py` 产出），与 `text_lint.py` 同源：en 原件有两处漏掉的
#: `<n>`（`0x0cf7abf0`、`0xdb0108dd`），照原件判会把已补齐的译文判成「Extra tag」。
#: clean 不在时（干净 clone、临时 src）退回原件，行为与从前一致。
CLEAN = os.path.join(ROOT, "build", "ref", "clean", "en-clean.toml")
TRANS = os.path.join(SRC, "translations")
PACK_OUT = os.path.join(ROOT, "build", "runtime", "PR2Localization", "packs")
DEFAULT_IN = os.path.join(ROOT, "build", "qa", "batches")


def read_rows(paths):
    """读 JSONL 批次；坏行直接报错，免得静默少译一片。"""
    rows, bad = [], []
    for path in paths:
        with io.open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    bad.append("%s:%d %s" % (os.path.basename(path), n, exc))
                    continue
                if not isinstance(row, dict) or not row.get("key"):
                    bad.append("%s:%d 缺 key" % (os.path.basename(path), n))
                    continue
                row["_batch"] = os.path.basename(path)
                rows.append(row)
    return rows, bad


def load_en_doc(explicit=""):
    """取英文基准：`--base` > clean 版 > 原件；返回 (doc, 用的是哪个文件)。"""
    for cand in (explicit, CLEAN, os.path.join(ORIG, BASE + ".toml")):
        if cand and os.path.isfile(cand):
            return TI.read_doc(cand)[0], cand
    raise ValueError("找不到英文基准：%s" % os.path.join(ORIG, BASE + ".toml"))


def collect_files(target):
    if os.path.isdir(target):
        names = sorted(f for f in os.listdir(target)
                       if f.endswith(".jsonl"))
        return [os.path.join(target, n) for n in names]
    if os.path.isfile(target):
        return [target]
    raise ValueError("找不到批次：%s" % target)


def keep_eol(path, raw):
    """按原文件换行风格写回，避免一次合并把整份文件变成 LF。"""
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    if crlf <= lf:
        return
    with open(path, "rb") as fh:
        data = fh.read()
    if b"\r\n" in data:
        return
    tmp = path + ".merge-eol"
    with open(tmp, "wb") as fh:
        fh.write(data.replace(b"\n", b"\r\n"))
    os.replace(tmp, path)


def apply_rows(rows, doc, en_doc, lang, fill_dups=True, dups=None):
    """纯函数：返回 (pending, report)。不写文件，便于测试。"""
    pending, errors, warnings, skipped = {}, [], [], []
    seen = set()
    for row in rows:
        key = str(row.get("key", "")).strip().lower()
        text = row.get("text") or ""
        if key in KEEP_ORIGINAL:
            skipped.append((key, "原样保留英文"))
            continue
        if not text.strip():
            skipped.append((key, "空 text"))
            continue
        if key not in doc:
            errors.append((key, "译文文件里没有这个键"))
            continue
        if key in seen:
            errors.append((key, "同一批里重复出现"))
            continue
        seen.add(key)
        problems = check_text(text, en_doc.get(key, ""), lang=lang)
        bad = [p for p in problems if p.get("level") == "error"]
        warn = [p for p in problems if p.get("level") == "warn"]
        if bad:
            for p in bad:
                errors.append((key, p.get("text", "")))
            continue
        for p in warn:
            warnings.append((key, p.get("text", "")))
        pending[key] = text

    filled = 0
    if fill_dups and dups:
        for head, members in dups.items():
            text = pending.get(head) or doc.get(head)
            if not text or text == en_doc.get(head):
                continue
            for m in members:
                if m in pending or m in KEEP_ORIGINAL:
                    continue
                cur = doc.get(m)
                if cur is not None and cur != en_doc.get(m):
                    continue          # 已经单独译过，不覆盖
                pending[m] = text
                filled += 1

    return pending, {
        "rows": len(rows),
        "applied": len(pending) - filled,
        "filled": filled,
        "skipped": skipped,
        "errors": errors,
        "warnings": warnings,
    }


def remaining(doc, en_doc):
    return sum(1 for k in doc if doc.get(k) == en_doc.get(k))


def main():
    ap = argparse.ArgumentParser(description="把批次译文合并回译文 TOML")
    ap.add_argument("--lang", required=True, help="目标语言代码")
    ap.add_argument("--in", dest="src", default="",
                    help="批次目录或单个 jsonl，默认 build\\qa\\batches\\<语言>")
    ap.add_argument("--no-fill-dups", action="store_true", help="不回填同文组")
    ap.add_argument("--strict", action="store_true", help="警告也拒绝写入")
    ap.add_argument("--no-compile", action="store_true", help="只写 TOML，不出包")
    ap.add_argument("--base", default="",
                    help="英文基准文件，默认取 build\\ref\\clean\\en-clean.toml，"
                         "缺省再退回 src\\orig\\en.gog_1.1.2.3.toml")
    ap.add_argument("--dry-run", action="store_true", help="只校验，不改文件")
    ap.add_argument("--json", action="store_true", help="只输出 JSON 摘要")
    args = ap.parse_args()

    src = args.src or os.path.join(DEFAULT_IN, args.lang)
    try:
        paths = collect_files(src)
    except ValueError as exc:
        print("[失败] " + str(exc), file=sys.stderr)
        return 2

    path = os.path.join(TRANS, args.lang + ".toml")
    if not os.path.isfile(path):
        print("[失败] 没有译文文件：%s\n先跑 new_lang.py --new-lang %s"
              % (path, args.lang), file=sys.stderr)
        return 2

    en_doc, en_path = load_en_doc(args.base)
    doc, order = TI.read_doc(path)
    rows, bad = read_rows(paths)

    dups = {}
    dup_path = os.path.join(os.path.dirname(paths[0]), "dups.json")
    if os.path.isfile(dup_path):
        with io.open(dup_path, encoding="utf-8") as fh:
            dups = json.load(fh)

    pending, report = apply_rows(rows, doc, en_doc, args.lang,
                                 fill_dups=not args.no_fill_dups, dups=dups)
    report["bad_lines"] = bad
    if args.strict:
        report["errors"] += [(k, "警告(严格模式)：%s" % w) for k, w in report["warnings"]]
        report["warnings"] = []
    report["files"] = [os.path.basename(p) for p in paths]
    report["remaining_before"] = remaining(doc, en_doc)
    report["will_write"] = bool(pending) and not report["errors"]

    if report["errors"] or bad:
        report["ok"] = False
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("合并拒绝：%d 条问题，未写入。" % (len(report["errors"]) + len(bad)))
            for key, msg in report["errors"][:30]:
                print("  × %s %s" % (key, msg))
            for b in bad[:10]:
                print("  × " + b)
            if len(report["errors"]) > 30:
                print("  …另有 %d 条" % (len(report["errors"]) - 30))
            print("修好这些行后重跑；目标文件没有被改动。")
        return 2

    if args.dry_run or not pending:
        report["ok"] = True
        report["wrote"] = False
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.dry_run:
            print("[dry-run] 将写入 %d 条（回填 %d），未改文件。"
                  % (report["applied"], report["filled"]))
        else:
            print("批次里没有填 text 的行，未改文件（跳过 %d 行）。"
                  % len(report["skipped"]))
        return 0

    merged = dict(doc)
    merged.update(pending)
    with open(path, "rb") as fh:
        raw = fh.read()
    TI.write_doc_atomic(path, merged, order, TI.head_lines(path))
    keep_eol(path, raw)

    report["remaining_after"] = remaining(merged, en_doc)
    wrote = True
    if not args.no_compile:
        rc = compile_pack(args.lang, PACK_OUT, no_fonts=True,
                          on_line=None if args.json else print)
        if rc != 0:
            with open(path, "wb") as fh:
                fh.write(raw)
            report["ok"] = False
            report["wrote"] = False
            report["error"] = "编译失败，已还原译文"
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print("[失败] 编译失败，已还原 %s" % path, file=sys.stderr)
            return 2

    report["ok"] = True
    report["wrote"] = True
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("合并 %d 条，同文回填 %d 条；未译 %d → %d。"
          % (report["applied"], report["filled"],
             report["remaining_before"], report["remaining_after"]))
    for key, msg in report["warnings"][:10]:
        print("  ! %s %s" % (key, msg))
    if not args.no_compile:
        print("出包：%s" % os.path.join(PACK_OUT, args.lang + ".txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
