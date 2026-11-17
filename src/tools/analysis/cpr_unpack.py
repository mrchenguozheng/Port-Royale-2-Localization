# -*- coding: utf-8 -*-
"""ASCARON_ARCHIVE V0.9（.cpr）解包，只读，不依赖第三方库。

格式（pr2_arcs.cpr / pr2_loca.cpr 实测）：
    0   魔法 "ASCARON_ARCHIVE V0.9"（20 字节）
    32  u32 = 0x1000
    36  u32 = 文件表长度
    40  u32 = 条目数
    44  u32 = 整个归档长度
    48  u32 = 第一个文件的数据起点
    52  u32
    56  u32 = 1
    60  目录项：名字（\\x00 结尾）+ u32 本文件结束偏移 + u32 + u32 标志
文件大小 = 本文件结束偏移 - 上一个结束偏移（第一个从数据起点算）。

用法：
    python src/tools/analysis/cpr_unpack.py <file.cpr> --list
    python src/tools/analysis/cpr_unpack.py <file.cpr> -o build/cpr/<name>
"""
import argparse
import os
import struct
import sys

MAGIC = b"ASCARON_ARCHIVE V0.9"


def parse(path):
    with open(path, "rb") as f:
        d = f.read()
    assert d[:20] == MAGIC, "不是 ASCARON_ARCHIVE V0.9：%s" % d[:20]
    (v1, table_len, count, data_len, data_start, v2, v3) = struct.unpack_from("<7I", d, 32)
    assert data_start < len(d), "数据起点 %d 越过文件长度 %d" % (data_start, len(d))
    pos = 60
    entries = []
    cur = data_start
    for i in range(count):
        end = d.index(b"\x00", pos)
        name = d[pos:end].decode("latin-1")
        pos = end + 1
        (next_end, mid, flag) = struct.unpack_from("<3I", d, pos)
        pos += 12
        if next_end == 0:      # 最后一个条目的结束偏移记为 0，表示到归档末尾
            next_end = len(d)
        size = next_end - cur
        assert size >= 0, "条目 %d（%s）长度 %d 为负" % (i, name, size)
        entries.append({"idx": i, "name": name, "start": cur, "size": size,
                        "mid": mid, "flag": flag})
        cur = next_end
    assert pos <= data_start, "目录表越过数据起点（%d > %d）" % (pos, data_start)
    # 头部记的是数据段长度，不是整个文件长度：data_len + data_start 可能略小于文件尾
    assert cur <= len(d), "条目链末 %d 超过文件长度 %d" % (cur, len(d))
    return d, entries, {"table_len": table_len, "count": count,
                        "data_start": data_start, "header_end": pos,
                        "data_len": data_len, "chain_end": cur}


def main():
    ap = argparse.ArgumentParser(description="ASCARON CPR 解包（只读）")
    ap.add_argument("cpr")
    ap.add_argument("-o", "--out", help="解包目录")
    ap.add_argument("--list", action="store_true", help="只列目录")
    a = ap.parse_args()

    d, entries, meta = parse(a.cpr)
    if a.list or not a.out:
        print("%s：%d 条目，数据起点 %d，目录表 %d 字节"
              % (os.path.basename(a.cpr), meta["count"], meta["data_start"],
                 meta["header_end"] - 60))
        for e in entries:
            print("%-52s %10d  @%d" % (e["name"], e["size"], e["start"]))
        return 0

    root = os.path.normpath(a.out)
    for e in entries:
        tgt = os.path.normpath(os.path.join(root, *e["name"].split("\\")))
        assert tgt.startswith(root + os.sep) or tgt == root, "路径越界：%s" % tgt
        os.makedirs(os.path.dirname(tgt) or root, exist_ok=True)
        with open(tgt, "wb") as f:
            f.write(d[e["start"]:e["start"] + e["size"]])
    print("解包 %d 个文件到 %s（%d 字节）" % (len(entries), root, sum(e["size"] for e in entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
