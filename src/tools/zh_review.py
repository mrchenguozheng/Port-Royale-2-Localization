# -*- coding: utf-8 -*-
"""zh_review.py —— 把「生成 → 编辑器人工审核」接进链路。

背景
----
`zh.toml` 是规则从 `references/zh.gog_1.1.2.3.toml` 生成的。人工在编辑器里
过一遍时，多半只调空格（换行位置、该不该断开）；偶尔才真改字。这个脚本负责
分清这两种情况：

  · 只有空白差异  → 「格式审核」，审核稿就按它算（记一个标记，构建不再重新生成）；
  · 文字有差异    → 真正改字，需要同步回文本源（或人工决定忽略）。

用法
----
    python src/tools/zh_review.py --diff      # 列出「只改格式」和「真改字」
    python src/tools/zh_review.py --accept    # 只有格式差异时，接受审核稿
    python src/tools/zh_review.py --sync      # 把真改的字同步回 references 再重生成
    python src/tools/zh_review.py --clear     # 清掉审核标记（下次构建重新生成）
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import lang_rules  # noqa: E402
import apply_zh_rules as GEN  # noqa: E402

REF = os.path.join(ROOT, "src", "references", "zh.gog_1.1.2.3.toml")
ZH = os.path.join(ROOT, "src", "translations", "zh.toml")
MARK = os.path.join(ROOT, "build", "zh.reviewed.json")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(text):
    return re.sub(r"\s+", "", text)


def generate_all():
    doc = tomllib.load(open(REF, "rb"))
    order = [m.group(1) for m in
             (re.match(r'^"([^"]+)"\s*=', l) for l in io.open(REF, encoding="utf-8"))
             if m]
    zh_rules = lang_rules.get("zh")
    given, surn, extras = GEN.build_names(doc)
    out = {}
    for h in order:
        text = doc[h]
        if not text:
            out[h] = text
            continue
        a = zh_rules.normalize(text)
        b = GEN.fix_conj(a)
        parts = GEN.TAG.split(b)
        res = []
        for i, part in enumerate(parts):
            if i % 2 == 1 or not part:
                res.append(part)
                continue
            spans = GEN.find_names(part, given, surn, extras)
            res.append(GEN.pad_names(part, spans) if spans else part)
        out[h] = "".join(res)
    return out


def load_zh():
    return tomllib.load(open(ZH, "rb"))


def diff():
    gen = generate_all()
    cur = load_zh()
    real, fmt = [], []
    for h, text in gen.items():
        c = cur.get(h)
        if c is None:
            real.append((h, text, ""))
            continue
        if c == text:
            continue
        if norm(c) == norm(text):
            fmt.append((h, text, c))
        else:
            real.append((h, text, c))
    return real, fmt


def marker_ok():
    try:
        m = json.load(open(MARK, encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return m.get("ref") == sha(REF) and m.get("zh") == sha(ZH)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--accept", action="store_true")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    if args.clear:
        if os.path.isfile(MARK):
            os.remove(MARK)
            print("已清除审核标记")
        else:
            print("没有审核标记")
        return

    real, fmt = diff()
    print("只改格式（空白）：%d 条；真改字：%d 条" % (len(fmt), len(real)))

    if args.diff or not (args.accept or args.sync):
        for h, old, new in real[:args.limit]:
            print("\n[真改字] %s\n  生成: %s\n  审核: %s" % (h, old[:80], new[:80]))
        for h, old, new in fmt[:args.limit]:
            print("\n[只改格式] %s\n  生成: %s\n  审核: %s" % (h, old[:80], new[:80]))
        return

    if args.accept:
        if real:
            print("还有 %d 条真改字，先 --sync 或人工确认，不能直接接受格式。" % len(real))
            return
        m = {"ref": sha(REF), "zh": sha(ZH)}
        os.makedirs(os.path.dirname(MARK), exist_ok=True)
        json.dump(m, open(MARK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已接受审核稿：以后构建直接用当前 zh.toml（文本源或 zh.toml 一变就失效）")
        return

    if args.sync:
        if not real:
            print("没有真改字，无需同步。")
            return
        print("同步 %d 条到文本源…" % len(real))
        ref = tomllib.load(open(REF, "rb"))
        order = [m.group(1) for m in
                 (re.match(r'^"([^"]+)"\s*=', l) for l in io.open(REF, encoding="utf-8"))
                 if m]
        head = []
        for ln in io.open(REF, encoding="utf-8"):
            if ln.startswith("#"):
                head.append(ln.rstrip("\n"))
            else:
                break
        for h, _old, new in real:
            ref[h] = GEN.strip_padding(new)
        def esc(t):
            return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        io.open(REF, "w", encoding="utf-8", newline="\n").write(
            "\n".join(head + ['"%s" = "%s"' % (k, esc(ref[k])) for k in order]) + "\n")
        print("文本源已更新；接下来跑 apply_zh_rules.py 重新生成（格式审核标记会失效）")


if __name__ == "__main__":
    main()
