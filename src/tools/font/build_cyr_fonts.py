#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cyr_fonts.py —— 生成俄语用的「贴近原版度量」字体。

原版四个拉丁字体没有西里尔字形。直接把完整 Noto 挂上去，字宽和字高都比
原版大（实测平均 advance / cap height 见下表），长一点的俄语串就会撑出
木板。这里的做法不是再去缩文案，而是把 Noto 的字形改成原版的度量：

- 正文（ARIAL）：用 Liberation Sans。它与 Arial 的 advance 逐字相同
  （西里尔 64 字实测差 0 em），自带西里尔，UPM 2048，OFL 可分发。
- 标题（ELGRECO / Tiepolo_black / Tiepolo_bold）：把 Noto Serif 的轮廓
  按 sy 纵向缩小到原版 cap height，再按 sx 横向压到原版平均 advance。

实测（英文语料加权平均 advance / cap height，原版字体从 pr2_loca.cpr 导出）:

    ARIAL.TTF          avg 0.485  cap 0.716
    ELGRECO_.TTF       avg 0.343  cap 0.724
    Tiepolo_black.ttf  avg 0.517  cap 0.614
    Tiepolo_bold.ttf   avg 0.496  cap 0.614

    NotoSans-Regular   avg 0.590（俄语语料） cap 0.714
    NotoSerif-Black    avg 0.665（俄语语料） cap 0.714
    NotoSerif-Bold     avg 0.641（俄语语料） cap 0.714

因此标题的缩放是 sy = 0.614/0.714 ≈ 0.86，sx = 原版 avg / Noto avg
（Black 0.777、Bold 0.774）。输出改名成 PR2Cyr*，不沿用 Noto 的族名。

    python src\\tools\\font\\build_cyr_fonts.py --out build\\runtime\\PR2Localization\\fonts
"""

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)

NOTO_CACHE = os.path.join(ROOT, "build", "cache", "noto-src")
RU_TOML = os.path.join(ROOT, "src", "translations", "ru.toml")

#: 原版标题字体的 cap height（em），从 pr2_loca.cpr 导出的 Tiepolo 实测。
TARGET_CAP = 0.614
#: Noto Serif 静态字重的 cap height（em）。
NOTO_CAP = 0.714
#: 原版 Tiepolo 的纵向度量（em）：hhea / OS/2 typo / win。行盒高度也要跟原版一致，
#: 否则字形缩小了行盒没缩，标题在按钮里会显得偏下、行距也偏大。
TARGET_ASCENT = 0.791
TARGET_DESCENT = -0.292

#: 每个标题逻辑字体：Noto 源文件、原版平均 advance、输出名、字重名、原版 win 上下沿。
DISPLAY = [
    ("NotoSerif-Black.ttf", 0.517, "PR2CyrDisplay-Black.ttf", "Black", 0.869, 0.295),
    ("NotoSerif-Bold.ttf", 0.496, "PR2CyrDisplay-Bold.ttf", "Bold", 0.856, 0.295),
]

BODY_SRC = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts",
                        "LiberationSans-Regular.ttf")
BODY_OUT = "PR2CyrBody-Regular.ttf"


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


def _avg_advance(font, charset):
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    upm = font["head"].unitsPerEm
    total = count = 0
    for ch in charset:
        gname = cmap.get(ord(ch))
        if gname is None:
            continue
        total += hmtx[gname][0]
        count += 1
    return (total / count / upm) if count else 0.0


def _cap_height(font):
    cmap = font.getBestCmap()
    gname = cmap.get(ord("H"))
    if gname is None:
        return 0.0
    return font["glyf"][gname].yMax / font["head"].unitsPerEm


def _scale_font(src, dst, sx, sy, family, charset=None, win_asc=None, win_desc=None):
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables import ttProgram

    font = TTFont(src)
    glyf = font["glyf"]

    for gname in list(glyf.keys()):
        glyph = glyf[gname]
        if glyph.numberOfContours == -1:  # 复合字形：只缩放组件位移
            for comp in glyph.components:
                comp.x = int(round(comp.x * sx))
                comp.y = int(round(comp.y * sy))
        else:
            coords, _ends, _flags = glyph.getCoordinates(glyf)
            for i in range(len(coords)):
                coords[i] = (coords[i][0] * sx, coords[i][1] * sy)
            glyph.coordinates = coords
            glyph.program = ttProgram.Program()
        glyph.recalcBounds(glyf)

    hmtx = font["hmtx"]
    for gname, (advance, lsb) in list(hmtx.metrics.items()):
        hmtx.metrics[gname] = (int(round(advance * sx)), int(round(lsb * sx)))

    for tag in ("cvt ", "fpgm", "prep"):
        if tag in font:
            del font[tag]

    # 纵向度量按原版 Tiepolo 写回；win 上下沿取原版值，但不得小于实际字形范围，
    # 否则缩放后的 ё / й 一类会顶到裁剪区。
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    names = [cmap[ord(ch)] for ch in (charset or ()) if ord(ch) in cmap]
    if not names:
        names = set(glyf.keys())
    top = max(glyf[n].yMax for n in names)
    bottom = min(glyf[n].yMin for n in names)
    font["hhea"].ascent = int(round(TARGET_ASCENT * upm))
    font["hhea"].descent = int(round(TARGET_DESCENT * upm))
    font["hhea"].lineGap = 0
    os2 = font["OS/2"]
    os2.sTypoAscender = int(round(TARGET_ASCENT * upm))
    os2.sTypoDescender = int(round(TARGET_DESCENT * upm))
    os2.sTypoLineGap = 0
    win_asc_px = max(int(round((win_asc or TARGET_ASCENT) * upm)), top)
    win_desc_px = max(int(round((win_desc or -TARGET_DESCENT) * upm)), -bottom)
    os2.usWinAscent = win_asc_px
    os2.usWinDescent = win_desc_px

    for name_id, value in ((1, family), (2, "Regular"),
                           (4, family + " Regular"), (6, family.replace(" ", "") + "-Regular"),
                           (16, family), (17, "Regular")):
        font["name"].setName(value, name_id, 3, 1, 0x409)
    font.save(dst)
    return dst


def _charset():
    import tomllib
    with open(RU_TOML, "rb") as fh:
        data = tomllib.load(fh)
    chars = set()
    for value in data.values():
        for ch in value:
            if not ch.isspace():
                chars.add(ch)
    return chars


def build(out, noto_dir=None, log=None, charset=None):
    """生成三个俄语字体，返回 (ok, message)。"""
    log = log or (lambda m: None)
    if not _fonttools():
        return False, "需要 fontTools：python -m pip install fonttools"
    from fontTools.ttLib import TTFont

    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)
    noto_dir = noto_dir or NOTO_CACHE

    if not os.path.isfile(BODY_SRC):
        return False, "缺少 Liberation Sans：%s" % BODY_SRC
    shutil.copyfile(BODY_SRC, os.path.join(out, BODY_OUT))
    log("正文 %s ← %s" % (BODY_OUT, BODY_SRC))

    charset = charset if charset is not None else (_charset() if os.path.isfile(RU_TOML) else set())
    sy = TARGET_CAP / NOTO_CAP
    sx_used = {}

    for src_name, target_avg, out_name, weight, win_asc, win_desc in DISPLAY:
        src = os.path.join(noto_dir, src_name)
        if not os.path.isfile(src):
            return False, "缺少 Noto 源文件：%s" % src
        noto = TTFont(src, lazy=True)
        avg = _avg_advance(noto, charset) if charset else 0.0
        if not avg:
            return False, "无法测量 %s 的平均 advance（用字表为空）" % src_name
        sx = target_avg / avg
        sx_used[out_name] = sx
        _scale_font(src, os.path.join(out, out_name), sx, sy,
                    "PR2 Cyrillic Display " + weight,
                    charset=charset, win_asc=win_asc, win_desc=win_desc)
        log("标题 %s ← %s  sx=%.3f sy=%.3f" % (out_name, src_name, sx, sy))

    missing_total = 0
    for name in (BODY_OUT, DISPLAY[0][2], DISPLAY[1][2]):
        font = TTFont(os.path.join(out, name), lazy=True)
        cmap = font.getBestCmap()
        missing = sorted(ch for ch in charset if ord(ch) not in cmap)
        missing_total += len(missing)
        log("%s 用字 %d 缺字 %d %s" % (name, len(charset), len(missing),
                                      "".join(missing[:12])))
    if missing_total:
        return False, "生成字体缺字 %d 个" % missing_total
    return True, "俄语字体 3 个（正文 Liberation Sans，标题 Noto Serif 压缩）"


def main():
    ap = argparse.ArgumentParser(description="生成俄语用的度量贴近原版的字体")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--noto-dir", default=NOTO_CACHE, help="Noto 静态 TTF 目录")
    args = ap.parse_args()

    ok, msg = build(args.out, args.noto_dir, log=lambda m: print("  " + m))
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
