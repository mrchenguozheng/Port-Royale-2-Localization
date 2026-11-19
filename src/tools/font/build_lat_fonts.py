#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_lat_fonts.py —— 生成拉丁扩展 A 语言（目前是波兰语）的「贴近原版度量」字体。

为什么要换：原版四个字体里，正文 ARIAL 覆盖得很好（1186 个码位，U+FFFC 以前都有，
波兰语 18 个字母 ą ć ę ł ń ó ś ź ż 全在），**标题三体只收了 223 个字形**：
ELGRECO_ / Tiepolo_black / Tiepolo_bold 缺 ą ć ę ł ń ś ź ż 与它们的大写
（`ó` 在 Latin-1 里，反而有）。一进标题条、木牌、印章就会是空格子。

所以这里不换正文，只换三个标题槽位：
用 Noto Serif 的字形，按原版对应字体的 cap height 与平均 advance 缩放，
让波兰语标题和英文标题占同样的高度与宽度。度量全部沿用 build_cyr_fonts
里那组「原版实测值」（同一批原版字体，与语言无关）：

    ELGRECO_.TTF       avg 0.343  cap 0.724
    Tiepolo_black.ttf  avg 0.517  cap 0.614
    Tiepolo_bold.ttf   avg 0.496  cap 0.614

俄语当初在 Tiepolo 两档上额外压了 12%（西里尔串比英文长，会撑出木板）。
波兰语不压：波兰语串长与英文、德文同量级，按原版宽度即可；
实在放不下时改文案或补空格，不动字体。

    python src\\tools\\font\\build_lat_fonts.py --lang pl --out build\\runtime\\PR2Localization\\fonts

字体检查：生成后逐字体比「波兰语用字表」（零售版全文取字符）里缺几个，
缺一个就返回失败 —— 缺字必须当场看见，不能等实机看到空格子。
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)

sys.path.insert(0, HERE)
import build_cyr_fonts as CYR  # noqa: E402

NOTO_CACHE = os.path.join(ROOT, "build", "cache", "noto-src")
NOTO_CAP = 0.714

#: 波兰语字母表（含大写）：即使语料里那一刻没出现，也必须有字形。
PL_ALPHABET = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"

#: 每个语言：参照语料（取全部用字）、输出前缀、三个标题槽位的映射。
#: 槽位元组 = (输出名, Noto 源, 目标 avg, 目标 cap, win_asc, win_desc, asc, desc)。
LANGS = {
    "pl": {
        "corpus": os.path.join(SRC, "orig", "pl.retail-1.0.0.toml"),
        "prefix": "PR2PlDisplay",
        "slots": [
            ("Head", "NotoSerif-Black.ttf", 0.343, 0.724, 0.928, 0.308, 0.833, -0.250),
            ("Black", "NotoSerif-Black.ttf", 0.517, 0.614, 0.869, 0.295, 0.791, -0.292),
            ("Bold", "NotoSerif-Bold.ttf", 0.496, 0.614, 0.856, 0.295, 0.791, -0.292),
        ],
    },
}


def _charset(profile):
    """语料全部用字 ∪ 本语言字母表 ∪ ASCII 可见字符。

    语料取自**零售版全文**而不是 `src/translations/<lang>.toml`：后者在开工初期
    大半还是英文，用它取用字会漏掉波兰语字母（当年俄语也踩过这个坑）。
    """
    chars = set(chr(c) for c in range(0x20, 0x7F))
    chars.update(PL_ALPHABET)
    path = profile["corpus"]
    if os.path.isfile(path):
        import tomllib
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        for value in data.values():
            for ch in str(value):
                if not ch.isspace():
                    chars.add(ch)
    return chars


def build(lang, out, noto_dir=None, log=None):
    """生成该语言的三个标题字体；返回 (ok, message)。"""
    log = log or (lambda m: None)
    if lang not in LANGS:
        return False, "没有 %s 的字体方案（只支持 %s）" % (lang, "、".join(sorted(LANGS)))
    profile = LANGS[lang]
    if not CYR._fonttools():
        return False, "需要 fontTools：python -m pip install fonttools"
    from fontTools.ttLib import TTFont

    noto_dir = noto_dir or NOTO_CACHE
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)
    charset = _charset(profile)

    names = []
    for (slot, src_name, target_avg, target_cap,
         win_asc, win_desc, ascent, descent) in profile["slots"]:
        src = os.path.join(noto_dir, src_name)
        if not os.path.isfile(src):
            return False, "缺少 Noto 源文件：%s" % src
        noto = TTFont(src, lazy=True)
        avg = CYR._avg_advance(noto, charset)
        noto.close()
        if not avg:
            return False, "无法测量 %s 的平均 advance（用字表为空）" % src_name
        sx, sy = target_avg / avg, target_cap / NOTO_CAP
        out_name = "%s-%s.ttf" % (profile["prefix"], slot)
        CYR._scale_font(src, os.path.join(out, out_name), sx, sy,
                        "PR2 %s Display %s" % (lang.upper(), slot),
                        charset=charset, win_asc=win_asc, win_desc=win_desc,
                        ascent=ascent, descent=descent)
        names.append(out_name)
        log("%s ← %s  sx=%.3f sy=%.3f（目标 avg %.3f cap %.3f）"
            % (out_name, src_name, sx, sy, target_avg, target_cap))

    missing_total = 0
    for name in names:
        font = TTFont(os.path.join(out, name), lazy=True)
        cmap = font.getBestCmap()
        missing = sorted(ch for ch in charset if ord(ch) not in cmap)
        font.close()
        missing_total += len(missing)
        log("%s 用字 %d 缺字 %d %s" % (name, len(charset), len(missing),
                                      "".join(missing[:16])))
    if missing_total:
        return False, "生成字体缺字 %d 个——Noto 源选错了，换一份再试" % missing_total
    with open(os.path.join(out, "NOTO-SOURCES.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("Noto font sources for %s (display slots only)\n\n" % lang)
        fh.write("Serif: NotoSerif-Black.ttf, NotoSerif-Bold.ttf"
                 " (按原版 cap height / 平均 advance 缩放)\n")
        fh.write("Body:  沿用游戏原版 ARIAL.TTF（拉丁扩展 A 已全覆盖，未替换）\n")
        fh.write("Scaling: sx/sy 见上方日志；只缩放轮廓与横向度量，不改 cmap\n\n")
        fh.write("License: SIL Open Font License 1.1\n")
        fh.write("https://openfontlicense.org/\n")
    return True, "%s 标题字体 %d 个（Noto Serif 按原版 cap/avg 缩放；正文沿用原版 ARIAL）" \
        % (lang, len(names))


def main():
    ap = argparse.ArgumentParser(description="生成拉丁扩展 A 语言的标题字体")
    ap.add_argument("--lang", default="pl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--noto-dir", default=NOTO_CACHE)
    args = ap.parse_args()
    ok, msg = build(args.lang, args.out, args.noto_dir, log=lambda m: print("  " + m))
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
