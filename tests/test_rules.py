# -*- coding: utf-8 -*-
"""规则层的小样本测试：改规则前后跑一遍，防止回归。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

import apply_zh_rules as ZH  # noqa: E402
import lang_rules  # noqa: E402


class TestZhRules(unittest.TestCase):
    def test_strip_padding_removes_cjk_spaces(self):
        self.assertEqual(ZH.strip_padding("你好 ， 世界 。"), "你好，世界。")
        self.assertEqual(ZH.strip_padding("谢谢 @g$TotalPrice$ 。"), "谢谢@g$TotalPrice$。")

    def test_punctuation_converted(self):
        zh = lang_rules.get("zh")
        self.assertEqual(zh.normalize("你好,世界!"), "你好， 世界！")

    def test_placeholder_kept(self):
        zh = lang_rules.get("zh")
        out = zh.normalize("支付 @g$TotalPrice$ 元")
        self.assertIn("@g$TotalPrice$", out)

    def test_generate_matches_file(self):
        order, out, _ = ZH.generate()
        import tomllib
        cur = tomllib.load(open(os.path.join(ROOT, "src", "translations", "zh.toml"), "rb"))
        self.assertEqual(len(cur), len(order))
        for h in order:
            self.assertEqual(cur.get(h), out[h], h)


if __name__ == "__main__":
    unittest.main()
