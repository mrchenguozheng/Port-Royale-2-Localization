# -*- coding: utf-8 -*-
"""文本变量码表的不变式：表与语料一致、字段齐备、例外留提示口。

表是 glossary/variable_codes.toml，工具是 src/tools/text/var_codes.py，
文档一致性（索引/编号/生成物漂移/未知码清单/例外与源码常量）在 src/tools/docs_check.py，
这里只测那几条断言本身还能不能用。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))
import var_codes as VC
import docs_check as DC


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
            if info["codes"]:
                self.assertTrue(info["example"].strip())
            else:
                # 语料里一条都不剩的变量名（`PirateGold` 只出现在德语零售版
                # 任务书里，那批正文不译之后就没了）只保留含义，统计写 0。
                self.assertEqual(info["refs_all"], 0)
                self.assertEqual(info["example"], "")

    def test_known_pairs(self):
        # 大小写是类型名的一部分：G 货物 / g 金币、N 人名 / n 国家
        self.assertEqual(self.vars_["Goods"]["codes"], ["G"])
        self.assertEqual(self.vars_["Gold"]["codes"], ["g"])
        self.assertEqual(self.vars_["Name"]["codes"], ["N"])
        self.assertEqual(self.vars_["Nation"]["codes"], ["n"])
        # 全库唯一一处 A 配非 USER 的变量，登记为例外并留提示
        self.assertEqual(self.vars_["Amount"]["codes"], ["A", "a"])
        self.assertEqual(self.vars_["USER"]["codes"], ["A", "s"])

    def test_corpus_tokens_all_resolve(self):
        bad, hints, total = VC.scan()
        self.assertEqual(bad, [])
        self.assertGreater(total, 5000)
        # 例外是提示而不是违规：七文件各一处
        self.assertEqual(len(hints), len(VC.SOURCES))
        self.assertEqual({h[1] for h in hints}, set(VC.EXCEPTIONS))

    def test_exception_is_hint_not_exemption(self):
        # 例外是提示：正常语料里七文件各一处提示，零违规
        bad, hints, _t = VC.scan()
        self.assertEqual(bad, [])
        self.assertEqual({h[1] for h in hints}, set(VC.EXCEPTIONS))
        self.assertEqual(len(hints), len(VC.SOURCES))
        # 登记了一个语料里根本不存在的例外 -> 按「例外过期」算违规，不会静静烂掉
        VC.EXCEPTIONS["0xdeadbeef"] = {"token": "@A$Amount$", "var": "Amount", "note": "x"}
        try:
            bad2, _h2, _t2 = VC.scan(VC.SOURCES[:1])
        finally:
            del VC.EXCEPTIONS["0xdeadbeef"]
        self.assertTrue(any("例外过期" in b[3] for b in bad2))

    def test_explain_known_token(self):
        r = VC.explain("@A$USER$", self.codes, self.vars_)
        self.assertEqual((r["code"], r["name"]), ("A", "USER"))
        self.assertEqual(r["problems"], [])

    def test_explain_rejects_unknown_pair(self):
        r = VC.explain("@T$Gold$", self.codes, self.vars_)
        self.assertEqual(r["problems"], ["变量名 Gold 没登记码 T（表里只有 g）"])
        with self.assertRaises(ValueError):
            VC.explain("T$Gold", self.codes, self.vars_)


class TestDocsChecks(unittest.TestCase):
    def test_generated_md_matches_render(self):
        self.assertEqual(DC.check_drift(), [])

    def test_unknown_codes_line_is_parseable(self):
        doc = DC._unknown_from_doc()
        self.assertEqual(doc, {"A", "M", "d", "r", "s"})

    def test_exception_keys_match_lint_constant(self):
        self.assertEqual(set(VC.EXCEPTIONS), set(DC._lint_const("VAR_CODE_ORIG")))
        self.assertEqual(DC.check_exceptions(), [])

    def test_index_covers_every_doc(self):
        self.assertEqual(DC.check_index(DC.README, "docs/README.md"), [])


if __name__ == "__main__":
    unittest.main()
