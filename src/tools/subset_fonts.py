#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""subset_fonts.py —— 按当前译文重新裁剪游戏字体，补全缺失字形。

为什么需要
----------
游戏自带的字体（``pr2_loca.cpr`` 里的 ``fonts\\*.TTF``）是**纯拉丁**的，
没有中文字形。汉化只能把 ``fonts\\`` 目录下的 TTF 换成带中文的字体，
仓库里用的是 ``_orig_bak`` 那份全量字体（约 10 MB、2 万多个字形）。

但全量字体在游戏里要建字形缓存，体积和内存都大；之前因此裁过一版，
裁的时候用的是**旧译文**的字符集 —— 后来译文里新增的字（比如「嫩」）
不在裁剪结果里，游戏就画不出字形，表现为空白。

所以：换过译文/补过字之后，用这个脚本按**当前全部译文用字**重裁一遍。
输出默认写到 ``build\\fonts\\``，复制到 ``<游戏>\\fonts\\`` 即可。

用法
----
    python src\\tools\\subset_fonts.py                 # 用 references + translations 的全部用字
    python src\\tools\\subset_fonts.py --out D:\\fonts  # 指定输出目录
    python src\\tools\\subset_fonts.py --src "C:\\...\\fonts\\_orig_bak"

依赖
----
需要 fontTools（只在本脚本里用；编辑器与其它工具仍是纯标准库）：

    python -m pip install fonttools

如果机器上已经有装好 fontTools 的环境，也可以用 ``--site-packages``
把它的 site-packages 目录加进来，免得再装一份。
"""
import argparse
import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(HERE)                       # 仓库的 src\
ROOT = os.path.dirname(SRC_DIR)                       # 仓库根
STRINGS = os.path.join(SRC_DIR, "translations")
REFS = os.path.join(STRINGS, "references")

DEFAULT_SRC = r"<游戏目录>\fonts\_orig_bak"
DEFAULT_OUT = os.path.join(ROOT, "build", "fonts")
FONTS = ("ARIAL.TTF", "ELGRECO_.TTF", "Tiepolo_black.ttf", "Tiepolo_bold.ttf")

#: 除了译文用字，还要保留的字符：ASCII、中文标点、数字全角等。
EXTRA = ("，。、；：！？…—～·「」『』“”《》【】（）〔〕〈〉［］％０１２３４５６７８９"
         "　￥· ‐‑–")


def toml_chars(paths):
    """把若干 toml 文件里所有取值用到的字符收集起来。"""
    chars = set(chr(c) for c in range(0x20, 0x7F))
    for path in paths:
        if not os.path.isfile(path):
            continue
        doc = tomllib.load(open(path, "rb"))
        for v in doc.values():
            if isinstance(v, str):
                chars.update(v)
    chars.update(EXTRA)
    return chars


def main():
    ap = argparse.ArgumentParser(description="按当前译文用字重新裁剪游戏字体")
    ap.add_argument("--src", default=DEFAULT_SRC, help="全量字体所在目录")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录（默认 build\\fonts）")
    ap.add_argument("--site-packages", default="",
                    help="可选：额外加入 sys.path 的 site-packages（里面要有 fontTools）")
    args = ap.parse_args()

    if args.site_packages:
        sys.path.insert(0, args.site_packages)
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        raise SystemExit(
            "需要 fontTools：python -m pip install fonttools\n"
            "（或先用 --site-packages 指向一个已经装了 fontTools 的 site-packages）")

    refs = sorted(os.path.join(REFS, f) for f in os.listdir(REFS) if f.endswith(".toml")) \
        if os.path.isdir(REFS) else []
    tgts = sorted(os.path.join(STRINGS, f) for f in os.listdir(STRINGS) if f.endswith(".toml")) \
        if os.path.isdir(STRINGS) else []
    chars = toml_chars(refs + tgts)
    print("目标字符数：%d（来自 %d 个译文/参考文件）" % (len(chars), len(refs) + len(tgts)))

    os.makedirs(args.out, exist_ok=True)
    for name in FONTS:
        src = os.path.join(args.src, name)
        if not os.path.exists(src):
            print("  跳过 %s：找不到 %s" % (name, src))
            continue
        font = TTFont(src)
        opts = subset.Options()
        opts.layout_features = ["*"]
        opts.name_IDs = ["*"]
        opts.name_legacy = True
        opts.notdef_outline = True
        opts.glyph_names = False
        ss = subset.Subsetter(options=opts)
        ss.populate(unicodes=[ord(c) for c in chars])
        ss.subset(font)
        dst = os.path.join(args.out, name)
        font.save(dst)
        font.close()
        print("  %-20s %8.1f KB -> %8.1f KB" % (
            name, os.path.getsize(src) / 1024.0, os.path.getsize(dst) / 1024.0))

    print("完成：%s" % args.out)
    print("把这里的 4 个 TTF 复制到 <游戏目录>\\fonts\\ 覆盖，重启游戏生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
