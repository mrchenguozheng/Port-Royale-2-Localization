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
import struct
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
EXTRA = ("，。、；：！？…—～·「」『』“”《》【】（）〔〕〈〉［］※％０１２３４５６７８９"
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


def text_files():
    """当前所有译文与参考 toml：translations\\*.toml + references\\*.toml。"""
    out = []
    if os.path.isdir(REFS):
        out += sorted(os.path.join(REFS, f) for f in os.listdir(REFS) if f.endswith(".toml"))
    if os.path.isdir(STRINGS):
        out += sorted(os.path.join(STRINGS, f) for f in os.listdir(STRINGS) if f.endswith(".toml"))
    return out


def needed_chars():
    """当前译文/参考用到的全部字符。"""
    return toml_chars(text_files())


def cmap_chars(path):
    """读 TTF 的 cmap（格式 4 / 12），返回码位集合。"""
    d = open(path, "rb").read()
    ntab = struct.unpack_from(">H", d, 4)[0]
    tables = {}
    for i in range(ntab):
        o = 12 + 16 * i
        tag = d[o:o + 4].decode("latin1")
        off, ln = struct.unpack_from(">II", d, o + 8)
        tables[tag] = (off, ln)
    if "cmap" not in tables:
        return set()
    off = tables["cmap"][0]
    n = struct.unpack_from(">H", d, off + 2)[0]
    chars = set()
    for i in range(n):
        pid, eid, sub = struct.unpack_from(">HHI", d, off + 4 + 8 * i)
        p = off + sub
        try:
            fmt = struct.unpack_from(">H", d, p)[0]
        except struct.error:
            continue
        if fmt == 4:
            segx2 = struct.unpack_from(">H", d, p + 6)[0]
            seg = segx2 // 2
            ends = struct.unpack_from(">%dH" % seg, d, p + 14)
            starts = struct.unpack_from(">%dH" % seg, d, p + 16 + segx2)
            for s, e in zip(starts, ends):
                if s != 0xFFFF and e >= s:
                    chars.update(range(s, e + 1))
        elif fmt == 12:
            ngroups = struct.unpack_from(">I", d, p + 12)[0]
            for g in range(ngroups):
                q = p + 16 + 12 * g
                s, e, _ = struct.unpack_from(">III", d, q)
                if e >= s:
                    chars.update(range(s, e + 1))
    return chars


def missing_in(out_dir, chars):
    """现有字体里缺了哪些字（按第一个字体算；四个字体字符集一致）。"""
    first = os.path.join(out_dir, FONTS[0])
    if not os.path.isfile(first):
        return sorted(chars)
    have = cmap_chars(first)
    return sorted(c for c in chars if ord(c) not in have)


def ensure_fonts(out_dir=None, src=None, log=None, force=False):
    """确保 build\\fonts 覆盖当前全部用字；不够就重新裁剪。

    返回 (ok, 说明)。**缺 fontTools 或找不到全量字体时不抛异常** ——
    它常常跟在「编译语言包」后面跑，字体没更新不该让整次构建失败，
    只提醒一句就好。
    """
    out_dir = out_dir or DEFAULT_OUT
    log = log or (lambda msg: None)
    chars = needed_chars()

    if not force:
        lack = missing_in(out_dir, chars)
        if not lack and os.path.isdir(out_dir):
            return True, "字体已覆盖 %d 个用字，无需重建" % len(chars)
    else:
        lack = sorted(chars)

    src = src or os.environ.get("PR2_ORIG_FONTS") or DEFAULT_SRC
    if not os.path.isdir(src):
        return False, ("找不到全量字体目录 %s —— 字体未更新，新字可能显示为空白"
                       "（可用 --src 或环境变量 PR2_ORIG_FONTS 指定）" % src)

    site = os.environ.get("PR2_FONTTOOLS_SITE")
    if site and site not in sys.path:
        sys.path.insert(0, site)
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        # 本机没装 fontTools 时再试几个常见位置（用户级路径，不写死盘符）：
        # 有的机器把依赖装在别的解释器环境里，没必要为此再装一份。
        import glob
        for cand in glob.glob(os.path.expanduser(
                r"~\.workbuddy\binaries\python\envs\*\Lib\site-packages")):
            if os.path.isdir(os.path.join(cand, "fontTools")):
                sys.path.insert(0, cand)
                break
        try:
            from fontTools import subset
            from fontTools.ttLib import TTFont
        except ImportError:
            return False, ("缺 fontTools，字体未更新（新字可能显示为空白）："
                           "python -m pip install fonttools，或用 PR2_FONTTOOLS_SITE "
                           "指向已装好 fontTools 的 site-packages")

    log("字体：当前用字 %d 个，%s，开始重裁…"
        % (len(chars), "强制重建" if force else "现有字体缺 %d 个" % len(lack)))
    os.makedirs(out_dir, exist_ok=True)
    for name in FONTS:
        sp = os.path.join(src, name)
        if not os.path.exists(sp):
            return False, "缺少源字体 %s" % sp
        font = TTFont(sp)
        opts = subset.Options()
        opts.layout_features = ["*"]
        opts.name_IDs = ["*"]
        opts.name_legacy = True
        opts.notdef_outline = True
        opts.glyph_names = False
        ss = subset.Subsetter(options=opts)
        ss.populate(unicodes=[ord(c) for c in chars])
        ss.subset(font)
        dp = os.path.join(out_dir, name)
        font.save(dp)
        font.close()
        log("   %-20s %8.1f KB -> %8.1f KB" % (
            name, os.path.getsize(sp) / 1024.0, os.path.getsize(dp) / 1024.0))
    return True, "字体已按 %d 个用字重裁（缺 %d 个已补上）" % (len(chars), len(lack))


def main():
    ap = argparse.ArgumentParser(description="按当前译文用字重新裁剪游戏字体")
    ap.add_argument("--src", default="", help="全量字体所在目录")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录（默认 build\\fonts）")
    ap.add_argument("--force", action="store_true", help="即使字符都能覆盖也重建")
    args = ap.parse_args()
    ok, msg = ensure_fonts(out_dir=args.out, src=args.src or None,
                           log=print, force=args.force)
    print(msg)
    if ok:
        print("把这里的 4 个 TTF 复制到 <游戏目录>\\fonts\\ 覆盖，重启游戏生效。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
