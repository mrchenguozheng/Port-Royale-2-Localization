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

    def test_space_ellipsis(self):
        self.assertEqual(ZH.space_ellipsis("等等…… 我"), "等等 …… 我")
        self.assertEqual(ZH.space_ellipsis("等等 …… 我"), "等等 …… 我")
        self.assertEqual(ZH.space_ellipsis("…… 开头"), "…… 开头")
        self.assertEqual(ZH.space_ellipsis("……"), "……")

    def test_space_dash(self):
        self.assertEqual(ZH.space_dash("关头—— 就在"), "关头 —— 就在")
        self.assertEqual(ZH.space_dash("关头 —— 就在"), "关头 —— 就在")
        self.assertEqual(ZH.space_dash("—— 开头"), "—— 开头")
        self.assertEqual(ZH.space_dash("范围 1554 — 1618"), "范围 1554 — 1618")

    def test_space_years(self):
        self.assertEqual(ZH.space_years("约1554 — 1618年"), "约 1554 — 1618 年")
        self.assertEqual(ZH.space_years("在1502 年"), "在 1502 年")
        self.assertEqual(ZH.space_years("超过1000，"), "超过 1000，")
        self.assertEqual(ZH.space_years("<o:0xFF131512>年"), "<o:0xFF131512>年")

    def test_space_before_double_break(self):
        self.assertEqual(ZH.space_before_double_break("你好。<n><n>下一段"),
                         "你好。 <n><n>下一段")
        self.assertEqual(ZH.space_before_double_break("你好。 <n><n>下一段"),
                         "你好。 <n><n>下一段")
        self.assertEqual(ZH.space_before_double_break("<n><n>开头"),
                         "<n><n>开头")

    def test_generate_keys_match_live(self):
        # live 可手改，不再要求和规则输出逐字一致，但键集合必须一致。
        order, out, _ = ZH.generate()
        import tomllib
        cur = tomllib.load(open(os.path.join(ROOT, "src", "live", "zh.toml"), "rb"))
        self.assertEqual(set(cur), set(order))


if __name__ == "__main__":
    unittest.main()
