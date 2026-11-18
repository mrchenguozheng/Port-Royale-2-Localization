#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thin_space.py —— 把正文字体里的 U+0020 压窄，另找一个字形当宽空格挂到 U+00A0。

动机：中文靠“每字一个半角空格”给引擎制造断行点，但空格本身有 0.22–0.25 em
的宽度，整段会变成疏排。这里把 U+0020 压到 0.05 em 当纯断行标记，中文看起来
是连续的；英文词与词之间改用 U+00A0（原空格宽度），词距正常。

实现上不新建字形（fontTools 里给 glyf 追加字形要同步 glyphOrder，容易把
maxp 弄坏），而是借用现成的 `uni2002`（EN SPACE，本来 0.5 em）：把它改成原
空格宽度，再把 U+00A0 映射过去。U+2002 本身在译文里不出现，改了没影响。

注意 U+00A0 原本和 U+0020 指向同一个 `space` 字形，不重映射的话两者会一起
变窄。U+2007/U+2009 在 Noto 里没有字形（会画成方框），不能用。

    python src\\tools\\font\\thin_space.py --dir PR2Localization\\fonts
"""

import argparse
import os
import sys


def _fonttools():
    site = os.environ.get("PR2_FONTTOOLS_SITE")
    if site and site not in sys.path:
        sys.path.insert(0, site)
    try:
        import fontTools  # noqa: F401
        return True
    except ImportError:
        pass
    import glob
    for cand in glob.glob(os.path.expanduser(
            r"~\.workbuddy\binaries\python\envs\*\Lib\site-packages")):
        if os.path.isdir(os.path.join(cand, "fontTools")):
            sys.path.insert(0, cand)
            return True
    return False


WIDE_CP = 0xA0
DONOR_CP = 0x2002


def rewrite(path, thin=50):
    """原地改一份字体；返回 (原空格宽度, 新空格宽度)。"""
    from fontTools.ttLib import TTFont

    font = TTFont(path)
    if "glyf" not in font:
        raise ValueError("%s 不是 glyf 轮廓字体" % os.path.basename(path))
    cmap = font.getBestCmap()
    space = cmap.get(0x20)
    donor = cmap.get(DONOR_CP)
    if not space:
        raise ValueError("%s 没有 U+0020" % os.path.basename(path))
    if not donor:
        raise ValueError("%s 没有 U+2002 可用作宽空格字形" % os.path.basename(path))

    hmtx = font["hmtx"]
    orig, space_lsb = hmtx[space]
    donor_lsb = hmtx[donor][1]
    hmtx[donor] = (orig, donor_lsb)
    hmtx[space] = (thin, space_lsb)

    for sub in font["cmap"].tables:
        if WIDE_CP in sub.cmap:
            sub.cmap[WIDE_CP] = donor
    font.save(path)
    font.close()
    return orig, thin


def main():
    ap = argparse.ArgumentParser(description="压窄半角空格，U+00A0 改指独立宽空格字形")
    ap.add_argument("--dir", required=True, help="字体目录（原地修改）")
    ap.add_argument("--thin", type=int, default=50, help="U+0020 宽度（/1000 em）")
    args = ap.parse_args()
    if not _fonttools():
        raise SystemExit("需要 fontTools；可用 PR2_FONTTOOLS_SITE 指向 site-packages")
    names = sorted(n for n in os.listdir(args.dir) if n.lower().endswith(".ttf"))
    if not names:
        raise SystemExit("目录里没有 ttf：%s" % args.dir)
    for name in names:
        orig, thin = rewrite(os.path.join(args.dir, name), args.thin)
        print("  %-30s U+0020 %d -> %d（U+00A0 沿用 %d）" % (name, orig, thin, orig))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
