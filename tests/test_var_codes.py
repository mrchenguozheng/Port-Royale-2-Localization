# -*- coding: utf-8 -*-
"""文本变量码表的不变式：表与语料一致、字段齐备、查询工具能解释已知引用。

表是 glossary/variable_codes.toml，工具是 src/tools/text/var_codes.py。
这里读真实数据，属于全仓不变式：谁在译文里手写了一个表里没有的码或名
（比如把 @a$Amount$ 敲成 @a$Amout$），check.py 就会红。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))
import var_codes as VC


class TestVariableCodeTable(unittest.TestCase):
    def setUp(self):
        self.meta, self.codes, self.vars_ = VC.load_table()

    def test_meta_counts_match_body(self):
        self.assertEqual(self.meta["codes"], len(self.codes))
        self.assertEqual(self.meta["names"], len(self.vars_))
        self.assertEqual(self.meta["references_en"], 770)

    def test_every_code_and_name_is_described(self):
        for code, info in self.codes.items():
            self.assertIn(info["conf"], ("confirmed", "inferred", "unknown"))
            self.assertTrue(info["meaning"].strip())
            self.assertTrue(info["evidence"].strip())
            self.assertGreater(info["refs_en"], 0)
        for name, info in self.vars_.items():
            self.assertTrue(info["meaning"].strip())
            self.assertTrue(info["codes"])
            self.assertTrue(info["example"].strip())

    def test_known_pairs(self):
        # 大小写是类型名的一部分：G 货物 / g 金币、N 人名 / n 国家
        self.assertEqual(self.vars_["Goods"]["codes"], ["G"])
        self.assertEqual(self.vars_["Gold"]["codes"], ["g"])
        self.assertEqual(self.vars_["Name"]["codes"], ["N"])
        self.assertEqual(self.vars_["Nation"]["codes"], ["n"])
        # 全库唯一一处 A 配非 USER 的变量，随原文保留
        self.assertEqual(self.vars_["Amount"]["codes"], ["A", "a"])
        self.assertEqual(self.vars_["USER"]["codes"], ["A", "s"])

    def test_corpus_tokens_all_resolve(self):
        bad, total = VC.scan()
        self.assertGreater(total, 5000)
        self.assertEqual(bad, [])

    def test_explain_known_token(self):
        r = VC.explain("@A$USER$", self.codes, self.vars_)
        self.assertEqual((r["code"], r["name"]), ("A", "USER"))
        self.assertEqual(r["problems"], [])

    def test_explain_rejects_unknown_pair(self):
        r = VC.explain("@T$Gold$", self.codes, self.vars_)
        self.assertEqual(r["problems"], ["变量名 Gold 没登记码 T（表里只有 g）"])
        with self.assertRaises(ValueError):
            VC.explain("T$Gold", self.codes, self.vars_)


if __name__ == "__main__":
    unittest.main()
