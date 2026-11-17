# -*- coding: utf-8 -*-
"""cpr 解包器的不变式：用合成归档测长度链、末项 0 的约定、目录穿越防护。

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


def build_cpr(names, payloads, last_end_zero=True):
    """按实测布局拼一个归档：名字+12 字节目录项，数据从 DATA_START 起。"""
    assert len(names) == len(payloads)
    table = b""
    ends = []
    cur = DATA_START
    for p in payloads:
        cur += len(p)
        ends.append(cur)
    for i, name in enumerate(names):
        nxt = 0 if (last_end_zero and i == len(names) - 1) else ends[i]
        table += name.encode("latin-1") + b"\x00" + struct.pack("<3I", nxt, 0, 1)
    body = b"".join(payloads)
    total_len = DATA_START + len(body)
    head = MAGIC + b"\x00" * 12 + struct.pack("<7I", 0x1000, len(table), len(names),
                                             len(body), DATA_START, 0, 1)
    out = head + table
    out += b"\x00" * (DATA_START - len(out))
    return out + body


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

    def test_sizes_and_names(self):
        names = ["Data\\a.ini", "Data\\b.ini", "lua\\c.bin"]
        payloads = [b"AAA", b"BBBBBB", b"C" * 9]
        ps = {
            "Data\\a.ini": b"AAA",
            "Data\\b.ini": b"BBBBBB",
            "lua\\c.bin": b"C" * 9,
        }
        d, entries, meta = CPR.parse(self.write(build_cpr(names, payloads)))
        self.assertEqual([e["name"] for e in entries], names)
        for e in entries:
            self.assertEqual(e["size"], len(ps[e["name"]]))
            self.assertEqual(d[e["start"]:e["start"] + e["size"]], ps[e["name"]])

    def test_last_entry_zero_means_eof(self):
        d, entries, meta = CPR.parse(
            self.write(build_cpr(["a"], [b"xyz"], last_end_zero=True)))
        self.assertEqual(entries[0]["size"], 3)
        self.assertEqual(meta["chain_end"], len(d))

    def test_negative_size_rejected(self):
        # 末项结束偏移写成比自身起点还小的非零值，必须断言失败而不是算出负长度
        bad = build_cpr(["a", "b"], [b"xy", b"zzz"], last_end_zero=False)
        bad = bytearray(bad)
        idx = bad.index(b"b\x00")
        struct.pack_into("<I", bad, idx + 2, DATA_START)
        with self.assertRaises(AssertionError):
            CPR.parse(self.write(bytes(bad)))

    def test_writes_inside_outdir_only(self):
        p = self.write(build_cpr(["dir\\x.txt"], [b"ok"]))
        out = os.path.join(self.tmp, "out")
        d, entries, meta = CPR.parse(p)
        root = os.path.normpath(out)
        for e in entries:
            tgt = os.path.normpath(os.path.join(root, *e["name"].split("\\")))
            self.assertTrue(tgt.startswith(root + os.sep))


if __name__ == "__main__":
    unittest.main()
