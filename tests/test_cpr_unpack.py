# -*- coding: utf-8 -*-
"""cpr 解包器的不变式：长度链、真实长度与对齐长度的错位约定、末项 0、目录穿越防护。

真实格式见 09 卷第六十九节；真实归档在游戏安装目录，测试不依赖它。
"""
import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "analysis"))
import cpr_unpack as CPR

MAGIC = b"ASCARON_ARCHIVE V0.9"
DATA_START = 4096


def build_cpr(names, payloads, pad=32, last_end_zero=True):
    """按实测布局拼归档：真实长度记在「上一条目」，第一项记在头部 52。"""
    assert len(names) == len(payloads)
    table = b""
    starts = []
    cur = DATA_START
    padded = []
    for p in payloads:
        n = ((len(p) + pad - 1) // pad) * pad
        starts.append(cur)
        padded.append(n)
        cur += n
    ends = [starts[i] + padded[i] for i in range(len(names))]
    for i, name in enumerate(names):
        nxt = 0 if (last_end_zero and i == len(names) - 1) else ends[i]
        mid = len(payloads[i + 1]) if i + 1 < len(payloads) else 0
        table += name.encode("latin-1") + b"\x00" + struct.pack("<3I", nxt, mid, 1)
    total_len = DATA_START + len(payloads[0])
    data = b""
    for i, p in enumerate(payloads):
        data += p + b"\x00" * (padded[i] - len(p))
    head = MAGIC + b"\x00" * 12 + struct.pack("<7I", 0x1000, len(table), len(names),
                                             sum(len(p) for p in payloads),
                                             DATA_START, len(payloads[0]), 1)
    out = head + table
    out += b"\x00" * (DATA_START - len(out))
    assert len(out) == DATA_START
    return out + data


class TestCprUnpack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, data):
        p = os.path.join(self.tmp, "t.cpr")
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_content_and_padding(self):
        names = ["Data\\a.ini", "Data\\b.ini", "lua\\c.bin"]
        payloads = [b"AAA", b"BBBBBB", b"C" * 9]
        p = self.write(build_cpr(names, payloads))
        d, entries, meta = CPR.parse(p)
        self.assertEqual([e["name"] for e in entries], names)
        for i, e in enumerate(entries):
            self.assertEqual(e["content"], len(payloads[i]))
            self.assertEqual(e["padded"] % 32, 0)
            self.assertTrue(e["content"] <= e["padded"])
            got = d[e["start"]:e["start"] + e["content"]]
            self.assertEqual(got, payloads[i])
        self.assertEqual(meta["chain_end"], len(d))

    def test_last_entry_zero_means_eof(self):
        d, entries, meta = CPR.parse(
            self.write(build_cpr(["a"], [b"xyz"], last_end_zero=True)))
        self.assertEqual(entries[0]["content"], 3)
        self.assertEqual(meta["chain_end"], len(d))

    def test_last_entry_length_comes_from_previous_mid(self):
        # 最后一个文件的真实长度记在上一条目里；它自己的 mid 写 0 只表示「没有下一个」
        d, entries, _m = CPR.parse(self.write(build_cpr(["a", "b"], [b"xy", b"zzzz"])))
        self.assertEqual(entries[-1]["content"], 4)
        self.assertTrue(entries[-1]["exact"])

    def test_negative_size_rejected(self):
        # 末项结束偏移写成比自身起点还小的非零值，必须断言失败而不是算出负长度
        bad = bytearray(build_cpr(["a", "b"], [b"xy", b"zzz"], last_end_zero=False))
        idx = bad.index(b"b\x00")
        struct.pack_into("<I", bad, idx + 2, DATA_START)
        with self.assertRaises(AssertionError):
            CPR.parse(self.write(bytes(bad)))

    def test_directory_entry_overlaps_data_start(self):
        # arct 那类：头部 count 多算一项，末项的 12 字节偏移字段落到数据起点之后。
        # 应当停在该项之前，把名字报出来，而不是读越界数据。
        data = bytearray(build_cpr(["a", "bbbb"], [b"xy", b"zzzz"]))
        pos = 60
        for _ in range(2):
            pos = data.index(b"\x00", pos) + 1 + 12
        struct.pack_into("<I", data, 48, pos - 12 + 1)   # 数据起点压进末项字段块
        _d, entries, meta = CPR.parse(self.write(bytes(data)))
        self.assertEqual([e["name"] for e in entries], ["a"])
        self.assertEqual(meta["truncated"], "bbbb")

    def test_no_truncation_reports_none(self):
        _d, _e, meta = CPR.parse(self.write(build_cpr(["a"], [b"xyz"])))
        self.assertIsNone(meta["truncated"])

    def test_content_never_escapes_outdir(self):
        p = self.write(build_cpr(["dir\\x.txt"], [b"ok"]))
        _d, entries, _m = CPR.parse(p)
        root = os.path.normpath(os.path.join(self.tmp, "out"))
        for e in entries:
            tgt = os.path.normpath(os.path.join(root, *e["name"].split("\\")))
            self.assertTrue(tgt.startswith(root + os.sep))


if __name__ == "__main__":
    unittest.main()
