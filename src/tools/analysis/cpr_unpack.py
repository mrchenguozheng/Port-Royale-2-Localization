# -*- coding: utf-8 -*-
"""ASCARON_ARCHIVE V0.9（.cpr）解包，只读，不依赖第三方库。

格式（pr2_arcs.cpr / pr2_loca.cpr 实测，见 09 卷第六十九节）：
    0   魔法 "ASCARON_ARCHIVE V0.9"（20 字节）
    32  u32 = 0x1000
    36  u32 = 目录表长度
    40  u32 = 条目数
    44  u32 = 数据段长度（各文件真实长度之和，不是整个文件长度）
    48  u32 = 第一个文件的数据起点
    52  u32 = 第一个文件的**真实长度**
    56  u32 = 1
    60  目录项：名字（\\x00 结尾）+ u32 本条目结束偏移 + u32 下一个文件的真实长度 + u32 标志

两个长度概念：
    对齐长度 = 本条目结束偏移 - 上一条目结束偏移，恒为 32 的倍数；
    真实长度 = 下一个文件的实际字节数，记在**上一条目**里（第一项记在头部 52）。
文件内容 = 对齐长度那块的前「上一个 mid」个字节，其余是零填充。最后一个文件的
真实长度无从取（它的 mid 恒为 0），只能用尾部零填充推断。
改内容长度时两处都要改，正是社区帖说的「每个文件两个数值」。

用法：
    python src/tools/analysis/cpr_unpack.py <file.cpr> --list
    python src/tools/analysis/cpr_unpack.py <file.cpr> -o build/cpr/<name>
"""
import argparse
import os
import struct
import sys

MAGIC = b"ASCARON_ARCHIVE V0.9"


def _zero_trim(blob):
    k = len(blob)
    while k > 0 and blob[k - 1] == 0:
        k -= 1
    return k


def parse(path):
    with open(path, "rb") as f:
        d = f.read()
    assert d[:20] == MAGIC, "不是 ASCARON_ARCHIVE V0.9：%s" % d[:20]
    (v1, table_len, count, data_len, data_start, first_len, v3) = struct.unpack_from("<7I", d, 32)
    assert data_start < len(d), "数据起点 %d 越过文件长度 %d" % (data_start, len(d))
    pos = 60
    entries = []
    cur = data_start
    prev_len = first_len          # 头部 52 处的真实长度属于第一个文件
    for i in range(count):
        end = d.index(b"\x00", pos)
        name = d[pos:end].decode("latin-1")
        pos = end + 1
        (next_end, mid, flag) = struct.unpack_from("<3I", d, pos)
        pos += 12
        if next_end == 0:      # 最后一个条目的结束偏移记为 0，表示到归档末尾
            next_end = len(d)
        padded = next_end - cur
        assert padded >= 0, "条目 %d（%s）对齐长度 %d 为负" % (i, name, padded)
        blob = d[cur:cur + padded]
        if prev_len:
            content = prev_len
            exact = True
        else:                  # 最后一条：前一项没记它，只能按尾部零填充推断
            content = _zero_trim(blob)
            exact = False
        assert content <= padded, "条目 %d（%s）真实长度 %d 超过对齐长度 %d" % (
            i, name, content, padded)
        entries.append({"idx": i, "name": name, "start": cur, "padded": padded,
                        "content": content, "exact": exact, "mid": mid, "flag": flag})
        cur = next_end
        prev_len = mid
    assert pos <= data_start, "目录表越过数据起点（%d > %d）" % (pos, data_start)
    # 头部记的是数据段长度，不是整个文件长度
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
        print("%-52s %10s %10s  %s" % ("名字", "真实长度", "对齐长度", "起点"))
        for e in entries:
            print("%-52s %10d %10d  @%d%s"
                  % (e["name"], e["content"], e["padded"], e["start"],
                     "" if e["exact"] else "  (尾部推断)"))
        return 0

    root = os.path.normpath(a.out)
    total = 0
    for e in entries:
        tgt = os.path.normpath(os.path.join(root, *e["name"].split("\\")))
        assert tgt.startswith(root + os.sep) or tgt == root, "路径越界：%s" % tgt
        os.makedirs(os.path.dirname(tgt) or root, exist_ok=True)
        with open(tgt, "wb") as f:
            f.write(d[e["start"]:e["start"] + e["content"]])
        total += e["content"]
    print("解包 %d 个文件到 %s（%d 字节）" % (len(entries), root, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
