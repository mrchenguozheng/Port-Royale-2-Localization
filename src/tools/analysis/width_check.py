# -*- coding: utf-8 -*-
"""用游戏自带字体的度量，粗查译文相对英文的「宽度膨胀」。

为什么要做：引擎按空格切词、控件宽度固定，中文/日文比英文更容易撑破布局。
真正的溢出错位只有拿到控件矩形才能确认，这里用「同一字体下译文宽度 ÷ 英文宽度」
做代理指标，先把最可疑的挑出来。

用法：
    python src/tools/analysis/width_check.py --lang ja --font build/fonts/ARIAL.TTF --size 14
输出：
    docs/宽度粗查-<lang>.csv
"""

import argparse
import csv
import io
import os
import re
import struct
import tomllib

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
ROOT = os.path.dirname(os.path.dirname(TOOLS))
TAG = re.compile(r"<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z]")


def load_font(path):
    data = open(path, "rb").read()
    n = struct.unpack_from(">H", data, 4)[0]
    tables = {}
    for i in range(n):
        off = 12 + i * 16
        tag = data[off:off + 4].decode("latin-1")
        _cs, offset, length = struct.unpack_from(">III", data, off + 4)
        tables[tag] = offset
    upem = struct.unpack_from(">H", data, tables["head"] + 18)[0]
    nhm = struct.unpack_from(">H", data, tables["hhea"] + 34)[0]
    hmtx = tables["hmtx"]
    adv = [struct.unpack_from(">H", data, hmtx + 4 * i)[0] for i in range(nhm)]
    last = adv[-1]

    cm = tables["cmap"]
    cnt = struct.unpack_from(">H", data, cm + 2)[0]
    sub = None
    for i in range(cnt):
        pid, eid, off = struct.unpack_from(">HHI", data, cm + 4 + i * 8)
        fmt = struct.unpack_from(">H", data, cm + off)[0]
        if fmt == 4 and sub is None:
            sub = cm + off
    segx2 = struct.unpack_from(">H", data, sub + 6)[0]
    seg = segx2 // 2
    end = [struct.unpack_from(">H", data, sub + 14 + 2 * i)[0] for i in range(seg)]
    start_off = sub + 16 + segx2
    start = [struct.unpack_from(">H", data, start_off + 2 * i)[0] for i in range(seg)]
    delta_off = start_off + segx2
    delta = [struct.unpack_from(">h", data, delta_off + 2 * i)[0] for i in range(seg)]
    range_off = delta_off + segx2
    ro = [struct.unpack_from(">H", data, range_off + 2 * i)[0] for i in range(seg)]

    def glyph(ch):
        c = ord(ch)
        for i in range(seg):
            if start[i] <= c <= end[i]:
                if ro[i] == 0:
                    g = (c + delta[i]) & 0xFFFF
                else:
                    addr = range_off + 2 * i + ro[i] + 2 * (c - start[i])
                    if addr + 2 > len(data):
                        return 0
                    g = struct.unpack_from(">H", data, addr)[0]
                    if g:
                        g = (g + delta[i]) & 0xFFFF
                return g
        return 0

    def width(text, size):
        total = 0
        for ch in TAG.sub("", text):
            g = glyph(ch)
            total += adv[g] if g < len(adv) else last
        return total / upem * size

    return width


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="ja")
    ap.add_argument("--font", default=os.path.join(ROOT, "build", "fonts", "ARIAL.TTF"))
    ap.add_argument("--size", type=float, default=14.0)
    args = ap.parse_args()

    en = tomllib.load(open(os.path.join(ROOT, "src", "orig",
                                       "en.gog_1.1.2.3.toml"), "rb"))
    tr = tomllib.load(open(os.path.join(ROOT, "src", "live", "%s.toml" % args.lang), "rb"))
    w = load_font(args.font)

    rows = []
    for k, e in en.items():
        t = tr.get(k, "")
        if not t:
            continue
        # 去掉标签/占位符后英文几乎没有内容时，宽度比没有意义（占位符没有字形）
        if len(TAG.sub("", e).strip()) < 3:
            continue
        we, wt = w(e, args.size), w(t, args.size)
        if we <= 0:
            continue
        # 单个 token 太宽也会被引擎整行丢弃，单独记一下
        tok = max((w(x, args.size) for x in t.split()), default=0.0)
        rows.append({"hash": k, "w_en": round(we, 1), "w_tr": round(wt, 1),
                     "ratio": round(wt / we, 2), "max_token": round(tok, 1),
                     "en": e.strip(), "tr": t.strip()})
    rows.sort(key=lambda r: -r["ratio"])
    out = os.path.join(ROOT, "docs", "宽度粗查-%s.csv" % args.lang)
    with io.open(out, "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["hash", "w_en", "w_tr", "ratio",
                                            "max_token", "en", "tr"])
        wr.writeheader()
        wr.writerows(rows)

    import statistics
    ratios = [r["ratio"] for r in rows]
    over15 = sum(1 for r in ratios if r >= 1.5)
    over20 = sum(1 for r in ratios if r >= 2.0)
    wide_tok = sum(1 for r in rows if r["max_token"] >= 200)
    print("条目 %d｜宽度比中位数 %.2f｜>=1.5 倍 %d 条｜>=2.0 倍 %d 条｜单 token>=200px %d 条" % (
        len(rows), statistics.median(ratios), over15, over20, wide_tok))
    print("最宽的 10 条：")
    for r in rows[:10]:
        print("  %.2f  %-12s %-38s | %s" % (r["ratio"], r["hash"], r["en"][:38], r["tr"][:40]))
    print("写出", out)


if __name__ == "__main__":
    main()
