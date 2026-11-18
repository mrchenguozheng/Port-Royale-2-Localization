# -*- coding: utf-8 -*-
"""快路径的纯函数回归：查找、hash 归一化、单条校验。

不测写文件/编译，避免测试依赖真实译文和游戏目录；这两步由
`quick.py` 的集成路径负责，手工冒烟已覆盖。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import quick  # noqa: E402
import translate as T  # noqa: E402


def entry(hid, zh, en="", fr=""):
    return {
        "id": hid,
        "zh": zh,
        T.BASE_LANG: en,
        T.FR_LANG: fr,
    }


class TestNormalize(unittest.TestCase):
    def test_fullwidth_case_and_breaks(self):
        self.assertEqual(quick.norm("  ＡＢＣ  "), "abc")
        self.assertEqual(quick.norm("甲<n>乙"), "甲 乙")
        self.assertEqual(quick.norm("甲 | 乙"), "甲 乙")

    def test_whitespace_collapsed(self):
        self.assertEqual(quick.norm("a\tb\n c"), "a b c")


class TestFind(unittest.TestCase):
    def setUp(self):
        self.entries = [
            entry("0xaaa", "可惜你的信用额度不够。",
                  "Unfortunately you do not have enough credit."),
            entry("0xbbb", "信用额度", "Credit line"),
            entry("0xccc", "港口里有一艘可用的船。",
                  "There is a ship available in the port."),
        ]

    def test_exact_scores_higher_than_substring(self):
        out = quick.find_candidates(self.entries, "信用额度", "zh")
        self.assertEqual(out[0][1]["id"], "0xbbb")
        self.assertEqual(out[0][0], 4)

    def test_search_can_hit_english(self):
        out = quick.find_candidates(self.entries, "enough credit", "zh")
        self.assertEqual(out[0][1]["id"], "0xaaa")

    def test_search_can_hit_french(self):
        entries = [entry("0xddd", "甲", "English", "Pas assez de crédit")]
        out = quick.find_candidates(entries, "crédit", "zh")
        self.assertEqual(out[0][1]["id"], "0xddd")

    def test_no_match(self):
        self.assertEqual(quick.find_candidates(self.entries, "完全不存在", "zh"), [])


class TestIdAndValidation(unittest.TestCase):
    def test_normalize_id(self):
        self.assertEqual(quick.normalize_id("0XC4BDE7D1"), "0xc4bde7d1")
        self.assertEqual(quick.normalize_id("c4bde7d1"), "0xc4bde7d1")

    def test_extra_placeholder_is_error(self):
        e = entry("0xaaa", "原文", "No placeholder")
        errors, warnings, problems = quick.validate_new(e, "zh", "多了 %1")
        self.assertTrue(errors)
        self.assertFalse(warnings)
        self.assertEqual(len(problems), 1)

    def test_missing_placeholder_is_warning(self):
        e = entry("0xaaa", "原文", "%1 与 %2")
        errors, warnings, problems = quick.validate_new(e, "zh", "只有 %1")
        self.assertFalse(errors)
        self.assertTrue(warnings)
        self.assertEqual(len(problems), 1)


if __name__ == "__main__":
    unittest.main()
