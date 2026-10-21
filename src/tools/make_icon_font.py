# -*- coding: utf-8 -*-
"""生成编辑器用的图标字体（两个字形：加号、齿轮）。

不依赖任何现成图标字体或 SVG：用 fontTools 直接画轮廓，产出
`src/editor/public/fonts/icons.ttf`。改图标就改这里的几何，再跑：

    python src/tools/make_icon_font.py

需要 fontTools（pip install fonttools）。
"""

import io
import math
import os

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "editor", "public", "fonts", "icons.ttf")

UPM = 1000
PLUS = 0xE000
GEAR = 0xE001


def polygon(points, clockwise=False):
    """把点列画成闭合轮廓。points 按数学正方向（逆时针）给。"""
    pen = TTGlyphPen(None)
    pts = list(reversed(points)) if clockwise else list(points)
    pen.moveTo(pts[0])
    for p in pts[1:]:
        pen.lineTo(p)
    pen.closePath()
    return pen


def plus_glyph():
    pen = TTGlyphPen(None)
    pts = [
        (200, 440), (440, 440), (440, 200), (560, 200),
        (560, 440), (800, 440), (800, 560), (560, 560),
        (560, 800), (440, 800), (440, 560), (200, 560),
    ]
    pen.moveTo(pts[0])
    for p in pts[1:]:
        pen.lineTo(p)
    pen.closePath()
    return pen.glyph()


def circle(cx, cy, r, steps=48, clockwise=False):
    pts = []
    for i in range(steps):
        a = 2 * math.pi * i / steps
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return polygon(pts, clockwise=clockwise)


def gear_glyph():
    """齿轮：外圈带 8 个齿 + 中心孔。"""
    cx = cy = 500
    teeth = 8
    r_out = 400
    r_root = 300
    r_hole = 130

    pts = []
    a = 0.0
    while a < 2 * math.pi:
        deg = math.degrees(a) % 360
        phase = (deg * teeth / 360.0) % 1.0
        r = r_out if 0.12 <= phase <= 0.55 else r_root
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        a += math.radians(3)

    hole = []
    for i in range(48):
        ang = -2 * math.pi * i / 48
        hole.append((cx + r_hole * math.cos(ang), cy + r_hole * math.sin(ang)))

    pen = TTGlyphPen(None)
    pen.moveTo(pts[0])
    for p in pts[1:]:
        pen.lineTo(p)
    pen.closePath()
    pen.moveTo(hole[0])
    for p in hole[1:]:
        pen.lineTo(p)
    pen.closePath()
    return pen.glyph()


def main():
    fb = FontBuilder(UPM, isTTF=True)
    order = [".notdef", "plus", "gear"]
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({PLUS: "plus", GEAR: "gear"})

    notdef = TTGlyphPen(None).glyph()
    fb.setupGlyf({"plus": plus_glyph(), "gear": gear_glyph(), ".notdef": notdef})
    fb.setupHorizontalMetrics({g: (UPM, 0) for g in order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({
        "familyName": "PR2 Editor Icons",
        "styleName": "Regular",
        "uniqueFontIdentifier": "PR2EditorIcons-Regular",
        "psName": "PR2EditorIcons-Regular",
        "version": "Version 1.0",
    })
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200,
                usWinAscent=900, usWinDescent=200)
    fb.setupPost()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fb.save(OUT)
    print("写入", OUT, os.path.getsize(OUT), "字节")


if __name__ == "__main__":
    main()
