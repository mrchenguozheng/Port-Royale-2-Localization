#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""squeeze_fonts.py —— 对 TrueType（glyf）字体做水平压缩。

只改字形横向坐标与水平前进宽度，文件名、内部名、垂直度量一律不动，
所以 font-map.ini 的映射不用改。

用途：日文在按拉丁宽度设计的界面框里放不下（全角 advance = 1em，
拉丁平均 0.5-0.6em），按可接受上限压 10%（scale 0.9）。

    python src\\tools\\font\\squeeze_fonts.py --src build\\release-ja\\fonts ^
        --dst build\\release-ja\\fonts-sq --scale 0.9
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


def squeeze(src, dst, scale):
    """原地横向压缩一份副本；返回 (读入字形数, 输出字节数)。"""
    from fontTools.ttLib import TTFont

    font = TTFont(src, fontNumber=0)
    if "glyf" not in font:
        raise ValueError("%s 不是 glyf 轮廓字体（CFF/OTF 不支持本工具）"
                         % os.path.basename(src))
    glyf = font["glyf"]
    order = font.getGlyphOrder()

    for name in order:
        g = glyf[name]
        if g.numberOfContours == 0:
            continue
        if g.isComposite():
            for comp in g.components:
                comp.x = int(round(comp.x * scale))
        else:
            coords = g.coordinates
            for i in range(len(coords)):
                x, y = coords[i]
                coords[i] = (int(round(x * scale)), y)
            g.coordinates = coords
        g.recalcBounds(glyf)

    hmtx = font["hmtx"]
    for name in order:
        adv, lsb = hmtx[name]
        hmtx[name] = (int(round(adv * scale)), int(round(lsb * scale)))

    # head 的整字体包围盒跟着重算
    xs_min, xs_max = [], []
    for name in order:
        g = glyf[name]
        if g.numberOfContours == 0:
            continue
        xs_min.append(g.xMin)
        xs_max.append(g.xMax)
    if xs_min:
        font["head"].xMin = min(xs_min)
        font["head"].xMax = max(xs_max)

    font.save(dst)
    font.close()
    return len(order), os.path.getsize(dst)


def main():
    ap = argparse.ArgumentParser(description="水平压缩 glyf 字体（文件名不变）")
    ap.add_argument("--src", required=True, help="源文件或源目录")
    ap.add_argument("--dst", required=True, help="输出目录")
    ap.add_argument("--scale", type=float, default=0.9,
                    help="横向缩放，0.9 = 压 10%%")
    ap.add_argument("--only", default=None,
                    help="只处理文件名包含该子串的字体")
    args = ap.parse_args()

    if not (0.5 <= args.scale <= 1.0):
        raise SystemExit("--scale 应在 0.5..1.0 之间")
    if not _fonttools():
        raise SystemExit("需要 fontTools；可用 PR2_FONTTOOLS_SITE 指向 site-packages")

    if os.path.isdir(args.src):
        names = sorted(n for n in os.listdir(args.src) if n.lower().endswith((".ttf", ".otf")))
    else:
        names = [os.path.basename(args.src)]
    os.makedirs(args.dst, exist_ok=True)

    total = 0
    for name in names:
        if args.only and args.only not in name:
            continue
        src = args.src if os.path.isfile(args.src) else os.path.join(args.src, name)
        dst = os.path.join(args.dst, name)
        glyphs, size = squeeze(src, dst, args.scale)
        total += 1
        print("  %-30s %d 字形 -> %.1f MB (x%.3f)"
              % (name, glyphs, size / 1048576.0, args.scale))
    print("压缩 %d 个字体到 %s" % (total, args.dst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
