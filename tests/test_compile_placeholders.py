# -*- coding: utf-8 -*-
"""编译期占位符比对的回归测试。

2025 批补译 15 条 2004 年竞赛文本时暴露的问题：这些键的英文原文是开发
残留标识符（`IDM_CONTEST_01_2004_LOG_06_TEXT`），不是句子，占位符比对
没有基准；照德语零售版补上 `@g$PirateGold$` 就被判成「多了占位符」。
豁免只认标识符形状，正常句子仍要照原文比对。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from pack import compile_pack as C  # noqa: E402
from shared.core import validate as V  # noqa: E402


class TestIdentifierExemption(unittest.TestCase):
    def test_identifier_origin_is_not_checked(self):
        errors, warnings = [], []
        ok = C.check_placeholders(
            "0x3426834a", "IDM_CONTEST_01_2004_LOG_06_TEXT",
            "让一名海盗听你调遣，他至少要交给你 @g$PirateGold$ 的战利品分成。",
            errors, warnings)
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_normal_sentence_still_checked(self):
        errors, warnings = [], []
        ok = C.check_placeholders(
            "0x11111111", "Give me %1 gold for %2 crates.",
            "给我 %2 箱，我就付你金币。", errors, warnings)
        self.assertFalse(ok)
        self.assertTrue(warnings)        # 少了占位符进警告
        self.assertEqual(errors, [])

    def test_short_uppercase_still_checked(self):
        # "OK" 这类短标签不是标识符，不能掉进豁免里
        self.assertFalse(V.is_identifier("OK"))
        self.assertFalse(V.is_identifier("CTRL"))
        self.assertFalse(V.is_identifier("Give me %1 gold."))
        self.assertTrue(V.is_identifier("IDM_CONTEST_01_2004_LOG_00_HDR"))


if __name__ == "__main__":
    unittest.main()
