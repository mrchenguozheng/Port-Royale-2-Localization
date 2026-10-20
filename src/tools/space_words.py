# -*- coding: utf-8 -*-
"""按词给中文插空格：把超宽的「一长串汉字」拆成词，引擎才能在空格处换行。

背景
----
引擎只按空格换行；中文没有词间空格时，整句会被当成一个 token。
token 比控件宽时，要么整行被丢弃（空白），要么被裁掉（截断）。
已有的「标点后加空格」规则只能解决句子之间，句子内部仍可能是一长串汉字。

做法
----
1. jieba 分词（加载 zh_userdict.txt 的术语，避免把「私掠者」拆成「私 掠者」）；
2. 单字虚词（的/了/是/在/和…）粘在前一个词后，避免「你 的 目标」；
3. 含间隔号的人名（胡安·贝尔穆德斯）整段不拆；
4. 只处理「最长汉字串 >= --min-run」且「最宽 token >= --max-token 像素」的条目；
5. 按目标宽度把词**成组**拼，组与组之间才加空格 —— 一句话通常只多出一两个空格，
   而不是每个词都隔开。

用法
----
    python src/tools/space_words.py --lang zh --dry-run
    python src/tools/space_words.py --lang zh --apply

依赖
----
jieba（纯 Python）：
    python -m pip install jieba
也可以放在 <仓库>\\.tmp\\deps\\jieba，脚本会自动加进 sys.path。
"""

import argparse
import csv
import io
import os
import re
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".tmp", "deps"))

TAG = re.compile(r"(<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z])")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
NAME = re.compile(r"[\u4e00-\u9fff]+(?:·[\u4e00-\u9fff]+)+")
#: 单字虚词：粘在前一个词后面
BIND_LEFT = set("的地得了着过是在和与及或而但也都不没把被给对从向为以于中上里外其之等们吗呢吧啊呀哦嗯")
#: 单字指示/量词：粘到后一个词前面
BIND_RIGHT = set("一二三四五六七八九十每各半几这那些")

WIDTH = None
TARGET_PX = 120.0


def load_jieba():
    try:
        import jieba
    except ImportError:
        sys.exit("需要 jieba：python -m pip install jieba（或放到 .tmp/deps/jieba）")
    dict_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zh_userdict.txt")
    if os.path.isfile(dict_path):
        jieba.load_userdict(dict_path)
    return jieba


def segment(run, jieba):
    """返回「词」列表，单字虚词已并到相邻词里。"""
    words = []
    for w in jieba.cut(run, HMM=True):
        if not w:
            continue
        if words and len(w) == 1 and w in BIND_LEFT:
            words[-1] += w
        else:
            words.append(w)
    merged = []
    for w in words:
        if merged and len(merged[-1]) == 1 and merged[-1][0] in BIND_RIGHT:
            merged[-1] += w
        else:
            merged.append(w)
    return merged


def pack(words):
    """按目标宽度成组：组内不加空格，组间加空格。"""
    groups, cur = [], ""
    for w in words:
        cand = cur + w if cur else w
        if cur and WIDTH(cand, 14.0) > TARGET_PX:
            groups.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        groups.append(cur)
    return " ".join(groups)


def spaced(text, jieba):
    """只改汉字串；标签、占位符、人名原样。"""
    names = []

    def keep(m):
        names.append(m.group(0))
        return "\x00%d\x00" % (len(names) - 1)

    text = NAME.sub(keep, text)
    parts = TAG.split(text)
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 1:
            out.append(p)
            continue
        out.append(CJK_RUN.sub(lambda m: pack(segment(m.group(0), jieba)), p))
    text = "".join(out)
    return re.sub(r"\x00(\d+)\x00", lambda m: names[int(m.group(1))], text)


def token_widths(text, width):
    return [width(t, 14.0) for t in text.split() if t.strip()]


def main():
    global WIDTH, TARGET_PX
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--min-run", type=int, default=12)
    ap.add_argument("--max-token", type=float, default=180.0)
    ap.add_argument("--target", type=float, default=120.0)
    ap.add_argument("--font", default=os.path.join(ROOT, "build", "fonts", "ARIAL.TTF"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    jieba = load_jieba()
    import width_check
    WIDTH = width_check.load_font(args.font)
    TARGET_PX = args.target

    path = os.path.join(ROOT, "src", "translations", "%s.toml" % args.lang)
    doc = tomllib.load(open(path, "rb"))
    order = [m.group(1) for m in
             (re.match(r'^"([^"]+)"\s*=', ln) for ln in io.open(path, encoding="utf-8"))
             if m]

    rows = []
    for k in order:
        t = doc.get(k) or ""
        run = max((len(m.group(0)) for m in CJK_RUN.finditer(NAME.sub("名", t))), default=0)
        if run < args.min_run:
            continue
        before = max(token_widths(t, WIDTH), default=0.0)
        if before < args.max_token:
            continue
        new = spaced(t, jieba)
        after = max(token_widths(new, WIDTH), default=0.0)
        if after >= before - 20:
            continue
        rows.append({"hash": k, "run": run, "before_px": round(before, 1),
                     "after_px": round(after, 1), "spaces": new.count(" ") - t.count(" "),
                     "zh": t, "new": new})

    rows.sort(key=lambda r: -r["before_px"])
    out = args.out or os.path.join(ROOT, "docs", "space-words-%s.csv" % args.lang)
    with io.open(out, "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["hash", "run", "before_px", "after_px",
                                            "spaces", "zh", "new"])
        wr.writeheader()
        wr.writerows(rows)

    print("候选 %d 条（汉字串 >= %d、最宽 token >= %gpx、目标 %gpx）" % (
        len(rows), args.min_run, args.max_token, args.target))
    for r in rows[:8]:
        print("  %-12s %6.1f -> %6.1f px (+%d 空格) | %s" % (
            r["hash"], r["before_px"], r["after_px"], r["spaces"], r["new"][:52]))
    print("明细:", out)

    if args.apply and rows:
        for r in rows:
            doc[r["hash"]] = r["new"]

        def esc(x):
            o = []
            for ch in x:
                if ch == "\\":
                    o.append("\\\\")
                elif ch == '"':
                    o.append('\\"')
                elif ch == "\n":
                    o.append("\\n")
                elif ch == "\r":
                    o.append("\\r")
                elif ch == "\t":
                    o.append("\\t")
                elif ord(ch) < 0x20:
                    o.append("\\u%04X" % ord(ch))
                else:
                    o.append(ch)
            return "".join(o)

        io.open(path, "w", encoding="utf-8", newline="\n").write(
            "\n".join('"%s" = "%s"' % (k, esc(doc[k])) for k in order) + "\n")
        print("已写回", path)


if __name__ == "__main__":
    main()
