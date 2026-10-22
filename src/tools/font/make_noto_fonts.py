#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_noto_fonts.py —— 为发行版生成 Noto 替换字体。

发行版不缝合，直接用完整的 Noto 字体替换游戏四个字体：

    ARIAL.TTF          Noto Sans  <语言> Regular
    ELGREGO_.TTF       Noto Serif <语言> Black
    Tiepolo_black.ttf  Noto Serif <语言> Black
    Tiepolo_bold.ttf   Noto Serif <语言> Bold

默认不裁剪。字体来源是本机安装的 Noto；VF 会实例化成静态字重。

    python src\\tools\\font\\make_noto_fonts.py --lang zh --out release\\zh\\fonts
"""

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)

OUT_NAMES = ("ARIAL.TTF", "ELGRECO_.TTF", "Tiepolo_black.ttf", "Tiepolo_bold.ttf")

#: 每个语言用哪套 Noto。静态文件优先，没有就用 VF 实例化。
LANGS = {
    "zh": {
        "sans": ("NotoSansSC", 400),
        "serif": ("NotoSerifSC", (700, 900)),
        "label": "Simplified Chinese",
    },
    "ja": {
        "sans": ("NotoSansJP", 400),
        "serif": ("NotoSerifJP", (700, 900)),
        "label": "Japanese",
    },
}


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


def _font_dirs():
    dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    return [d for d in dirs if os.path.isdir(d)]


def find_font(stem, weight=None):
    """找指定字重的静态文件；没有就退回 <stem>-VF.ttf。"""
    names = {400: "Regular", 700: "Bold", 900: "Black"}
    dirs = _font_dirs()
    if weight in names:
        for d in dirs:
            p = os.path.join(d, "%s-%s.ttf" % (stem, names[weight]))
            if os.path.isfile(p):
                return p, False
    for d in dirs:
        p = os.path.join(d, "%s-VF.ttf" % stem)
        if os.path.isfile(p):
            return p, True
    return None, False


def _static(path, weight, out_path):
    try:
        from fontTools.ttLib import TTFont
        from fontTools.varLib.instancer import instantiateVariableFont
    except ImportError:
        raise ValueError(
            "这个 Noto 字体是可变字体（VF），需要 fontTools 实例化："
            "python -m pip install fonttools\n"
            "或者安装静态字重文件，例如 NotoSerifSC-Black.ttf / -Bold.ttf，"
            "这样只复制改名，不需要 fontTools")
    font = TTFont(path)
    if "fvar" in font:
        font = instantiateVariableFont(font, {"wght": weight}, inplace=False)
    font.save(out_path)
    font.close()
    return out_path


def ensure_noto_fonts(lang, out_dir, log=None):
    """生成某语言的四个 Noto 替换字体；返回 {文件名: 字节数}。"""
    log = log or (lambda m: None)
    cfg = LANGS.get(lang)
    if not cfg:
        raise ValueError("没有为语言 %s 配置 Noto 字体映射" % lang)

    sans_path, sans_var = find_font(cfg["sans"][0], cfg["sans"][1])
    serif_path, serif_var = find_font(cfg["serif"][0], cfg["serif"][1][1])
    if not sans_path:
        raise FileNotFoundError("找不到 %s 的 NotoSans 文件" % lang)
    if not serif_path:
        raise FileNotFoundError("找不到 %s 的 NotoSerif 文件" % lang)

    os.makedirs(out_dir, exist_ok=True)
    serif_bold, serif_bold_var = find_font(cfg["serif"][0], cfg["serif"][1][0])
    if (sans_var or serif_var or serif_bold_var) and not _fonttools():
        raise ValueError(
            "源字体是 VF 可变字体，需要 fontTools 实例化："
            "python -m pip install fonttools；"
            "或安装静态字重文件（NotoSerifSC-Bold.ttf / -Black.ttf），"
            "这样只复制改名，不需要 fontTools")
    mapping = {
        "ARIAL.TTF": (sans_path, sans_var, cfg["sans"][1]),
        "ELGRECO_.TTF": (serif_path, serif_var, cfg["serif"][1][1]),
        "Tiepolo_black.ttf": (serif_path, serif_var, cfg["serif"][1][1]),
        "Tiepolo_bold.ttf": (serif_bold or serif_path,
                             serif_bold_var if serif_bold else serif_var,
                             cfg["serif"][1][0]),
    }
    result = {}
    for name, (path, is_var, weight) in mapping.items():
        dst = os.path.join(out_dir, name)
        if is_var:
            _static(path, weight, dst)
        else:
            shutil.copyfile(path, dst)
        result[name] = os.path.getsize(dst)
        log("  %-18s <- %s wght=%s (%.1f MB)" % (
            name, os.path.basename(path), weight, result[name] / 1048576.0))

    with open(os.path.join(out_dir, "NOTO-SOURCES.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("Noto font sources for %s (%s)\n\n" % (lang, cfg["label"]))
        fh.write("Sans:  %s\n" % sans_path)
        fh.write("Serif: %s\n" % serif_path)
        fh.write("Weights: Sans %s; Serif %s\n\n" % (
            cfg["sans"][1], ", ".join(str(w) for w in cfg["serif"][1])))
        fh.write("License: SIL Open Font License 1.1\n")
        fh.write("https://openfontlicense.org/\n")
    return result


def main():
    ap = argparse.ArgumentParser(description="生成发行版 Noto 替换字体（不裁剪）")
    ap.add_argument("--lang", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    result = ensure_noto_fonts(args.lang, args.out, log=print)
    print("已生成 %d 个字体到 %s（共 %.1f MB）" % (
        len(result), args.out, sum(result.values()) / 1048576.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
