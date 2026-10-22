#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_fonts.py —— 从 pr2_loca.cpr 里导出游戏内置的 TTF 字体。

游戏字体不是磁盘上的独立文件，而是打包在 `pr2_loca.cpr`
（ASCARON_ARCHIVE V0.9）里，一共四个：

| 归档内路径 | 字节 | 字体家族 | 用途 |
|---|---|---|---|
| `fonts\\ARIAL.TTF` | 296,712 | Arial | 界面正文 |
| `fonts\\ELGRECO_.TTF` | 65,680 | ElGreco | 标题/点缀 |
| `fonts\\Tiepolo_black.ttf` | 52,876 | Tiepolo-Black | 花体（标题、印章感文字） |
| `fonts\\Tiepolo_bold.ttf` | 53,120 | Tiepolo-Bold | 花体（加粗） |

这四个都是**纯拉丁**字体，没有中文字形 —— 所以汉化要把 `fonts\\*.TTF`
换成带中文的字体（见 `subset_fonts.py`）。原版字体留在这里，是为了
随时能对照「游戏原本长什么样」。

用法
----
    python src\\tools\\extract_fonts.py --game-dir "<游戏目录>" \\
        --out .tmp\\fonts_orig
"""
import argparse
import os
import struct


def main():
    ap = argparse.ArgumentParser(description="导出游戏内置字体")
    ap.add_argument("--game-dir", required=True, help="含 pr2_loca.cpr 的游戏目录")
    ap.add_argument("--out", required=True, help="输出目录")
    a = ap.parse_args()

    path = os.path.join(a.game_dir, "pr2_loca.cpr")
    if not os.path.isfile(path):
        raise SystemExit("找不到 %s" % path)
    d = open(path, "rb").read()
    if not d.startswith(b"ASCARON_ARCHIVE"):
        raise SystemExit("不是 ASCARON_ARCHIVE：%s" % path)

    count = struct.unpack_from("<I", d, 0x28)[0]
    os.makedirs(a.out, exist_ok=True)
    o, n = 0x30, 0
    for _ in range(count):
        off, size, _flags = struct.unpack_from("<III", d, o)
        o += 12
        end = d.index(b"\x00", o)
        name = d[o:end].decode("latin1")
        o = end + 1
        if name.lower().endswith(".ttf"):
            dst = os.path.join(a.out, os.path.basename(name))
            open(dst, "wb").write(d[off:off + size])
            print("%-28s %8d B -> %s" % (name, size, dst))
            n += 1
    print("共导出 %d 个字体" % n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
