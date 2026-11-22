# -*- coding: utf-8 -*-
"""切批与合并的纯函数回归：分类、同文组、块边界、占位符拒绝、同文回填。

不碰真实译文文件，也不用建语言包；只测 `split_batches.build_plan` 与
`merge_batches.apply_rows` 这两个不写盘的部分。
"""

import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import split_batches as S  # noqa: E402
import merge_batches as M  # noqa: E402
from shared.core import en_base as EB  # noqa: E402


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def toml_lines(items):
    return "\n".join('"%s" = "%s"' % (k, v) for k, v in items) + "\n"


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        items = [
            ("0x00000001", "Gold"),
            ("0x00000002", "Hello"),
            ("0x00000003", "Hello"),
            ("0x00000004", "Hello"),
            ("0x00000005", "Riddle line"),
            ("0x00000006", "100"),
            ("0x00000007", "Ships"),
        ]
        self.en = os.path.join(self.dir, "en.toml")
        write(self.en, toml_lines(items))
        self.terms = os.path.join(self.dir, "terms.toml")
        write(self.terms, '[[group]]\nname = "货物"\nids = ["0x00000001"]\n')
        self.verse = os.path.join(self.dir, "verse.toml")
        write(self.verse, '[[group]]\nids = ["0x00000005"]\nans = "X"\n')

    def plan(self, blocks=2):
        return S.build_plan(self.en, self.terms, self.verse,
                            blocks=blocks, keep={"0x00000007"})

    def test_classification(self):
        plan, _ = self.plan()
        self.assertEqual(plan["special"]["0x00000001"], "terms")
        self.assertEqual(plan["special"]["0x00000005"], "verse")
        self.assertEqual(plan["special"]["0x00000006"], "keep")   # 纯数字
        self.assertEqual(plan["special"]["0x00000007"], "keep")   # KEEP 名单
        self.assertEqual(plan["totals"]["pool"], 3)               # 02/03/04

    def test_dups_keep_only_leader(self):
        plan, en = self.plan()
        self.assertEqual(plan["dups"], {"0x00000002": ["0x00000003", "0x00000004"]})
        self.assertEqual(plan["member_of"]["0x00000003"], "0x00000002")
        main = [b for b in plan["batches"] if b["kind"] == "main"][0]
        self.assertEqual(main["keys"], ["0x00000002"])

    def test_batches_cover_every_key_once(self):
        plan, _ = self.plan(blocks=2)
        seen = []
        for b in plan["batches"]:
            seen += b["keys"]
        self.assertEqual(len(seen), len(set(seen)))
        # 同文组成员不进批（由 dups.json 回填），其余每条都必须出现一次。
        expect = [k for k in plan["order"] if k not in plan["member_of"]]
        self.assertEqual(set(seen), set(expect))
        self.assertEqual([b["id"] for b in plan["batches"]],
                         ["00-terms", "01-verse", "02-keep", "b01"])

    def test_blocks_upper_bound(self):
        with self.assertRaises(ValueError):
            S.build_plan(self.en, self.terms, self.verse, blocks=0)


class TestApply(unittest.TestCase):
    en = {
        "0x01": "Deal with %s now",
        "0x02": "Deal with %s now",
        "0x03": "Hello",
        "0x04": "Credit line",
        "0x05": "Port",
    }
    doc = dict(en)

    def test_placeholder_extra_is_error(self):
        rows = [{"key": "0x03", "text": "%9 Hello"}]
        pending, report = M.apply_rows(rows, self.doc, self.en, "zh")
        self.assertEqual(pending, {})
        self.assertEqual(report["errors"][0][0], "0x03")

    def test_missing_key_is_error(self):
        rows = [{"key": "0x99", "text": "甲"}]
        pending, report = M.apply_rows(rows, self.doc, self.en, "zh")
        self.assertEqual(pending, {})
        self.assertTrue(report["errors"])

    def test_empty_text_skipped(self):
        rows = [{"key": "0x03", "text": "  "}]
        pending, report = M.apply_rows(rows, self.doc, self.en, "zh")
        self.assertEqual(pending, {})
        self.assertEqual(report["skipped"][0][1], "空 text")

    def test_dup_fill_by_leader(self):
        doc = dict(self.en)
        rows = [{"key": "0x01", "text": "%s 成交"}]
        pending, report = M.apply_rows(
            rows, doc, self.en, "zh",
            dups={"0x01": ["0x02"]})
        self.assertEqual(pending["0x02"], "%s 成交")
        self.assertEqual(report["filled"], 1)

    def test_dup_fill_does_not_overwrite_translated(self):
        doc = dict(self.en)
        doc["0x02"] = "%s 现货"
        pending, _ = M.apply_rows(
            [{"key": "0x01", "text": "%s 成交"}], doc, self.en, "zh",
            dups={"0x01": ["0x02"]})
        self.assertNotIn("0x02", pending)

    def test_no_fill_dups_flag(self):
        pending, report = M.apply_rows(
            [{"key": "0x01", "text": "%s 成交"}], dict(self.en), self.en, "zh",
            fill_dups=False, dups={"0x01": ["0x02"]})
        self.assertNotIn("0x02", pending)
        self.assertEqual(report["filled"], 0)


class TestEnBase(unittest.TestCase):
    """合并用的英文基准：默认读 clean 版，与 text_lint 同源。

    照 en 原件判，`0xdb0108dd` 这类被 clean 补过 `<n>` 的条目会被判成「Extra tag」
    而整批拒写；这里钉住「默认取 clean」「clean 缺了退回原件」「--base 显式优先」。
    """

    orig_path = os.path.join(M.ORIG, M.BASE + ".toml")

    @unittest.skipUnless(os.path.isfile(M.CLEAN), "没有 clean 产物")
    def test_default_base_is_clean(self):
        doc, path = M.load_en_doc()
        self.assertEqual(os.path.normcase(path), os.path.normcase(M.CLEAN))

    @unittest.skipUnless(os.path.isfile(M.CLEAN) and os.path.isfile(orig_path),
                         "没有 clean 或 en 原件")
    def test_both_bases_are_padded(self):
        """补齐在代码里做，两份来源对同一键给出同样的占位符数。"""
        clean, _ = M.load_en_doc(M.CLEAN)
        orig, _ = M.load_en_doc(self.orig_path)
        for key, want in EB.EXPECTED.items():
            self.assertEqual(clean.get(key, "").count("<n>"), want)
            self.assertEqual(orig.get(key, "").count("<n>"), want)

    @unittest.skipUnless(os.path.isfile(orig_path), "没有 en 原件")
    def test_orig_fallback_is_padded_without_clean(self):
        """干净 clone 上没有 clean，退回原件也必须补齐——CI 就栽在这。"""
        keep = M.CLEAN
        try:
            M.CLEAN = os.path.join(tempfile.gettempdir(), "no-such-clean.toml")
            doc, path = M.load_en_doc()
            self.assertEqual(os.path.normcase(path), os.path.normcase(self.orig_path))
            for key, want in EB.EXPECTED.items():
                self.assertEqual(doc.get(key, "").count("<n>"), want)
        finally:
            M.CLEAN = keep

    @unittest.skipUnless(os.path.isfile(orig_path), "没有 en 原件")
    def test_fallback_to_orig_when_clean_missing(self):
        keep = M.CLEAN
        try:
            M.CLEAN = os.path.join(tempfile.gettempdir(), "no-such-clean.toml")
            doc, path = M.load_en_doc()
            self.assertEqual(os.path.normcase(path),
                             os.path.normcase(self.orig_path))
        finally:
            M.CLEAN = keep

    @unittest.skipUnless(os.path.isfile(orig_path), "没有 en 原件")
    def test_explicit_base_wins(self):
        doc, path = M.load_en_doc(self.orig_path)
        self.assertEqual(os.path.normcase(path),
                         os.path.normcase(self.orig_path))


if __name__ == "__main__":
    unittest.main()
