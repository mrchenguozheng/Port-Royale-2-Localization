# -*- coding: utf-8 -*-
"""toml_io 回归：转义、写回顺序、header 保留、原子写不留 tmp。"""

import os
import shutil
import sys
import tempfile
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from text import toml_io as TI  # noqa: E402

TRICKY = '引号" 反斜杠\\ 换行\n 制表\t 控制符\x01 占位符%02 <n>'


class TestTomlIo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "a.toml")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_esc(self):
        self.assertEqual(TI.esc('a"b\\c\n\t\x01'),
                         'a\\"b\\\\c\\n\\t\\u0001')

    def test_roundtrip_keeps_text_and_header(self):
        doc = {"0x1": TRICKY, "0x2": "普通"}
        TI.write_doc_atomic(self.path, doc, ["0x1", "0x2"], ["# 头"])
        with open(self.path, "rb") as fh:
            back = tomllib.load(fh)
        self.assertEqual(back, doc)
        self.assertEqual(TI.head_lines(self.path), ["# 头"])
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_order_comes_from_order_list(self):
        TI.write_doc_atomic(self.path, {"0xb": "B", "0xa": "A"}, ["0xa", "0xb"])
        with open(self.path, "rb") as fh:
            self.assertEqual(TI.order_of(self.path), ["0xa", "0xb"])


if __name__ == "__main__":
    unittest.main()
