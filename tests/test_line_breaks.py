# -*- coding: utf-8 -*-
"""手工断行层（src/tools/text/line_breaks.py）与日语机械断行（JaLineBreak）的判据。

这一层最容易错的两处：可见宽度口径（标签 0、占位 1、`<n>` 0）和
「切不动就返回不切」——后者决定手工清单是不是空的。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from text import line_breaks as LB          # noqa: E402
from text.lang_rules import ja             # noqa: E402


class TestVisibleLength(unittest.TestCase):

    def test_tags_and_nodes_are_zero_width(self):
        self.assertEqual(LB.visible_length("@a$X$<gs:x>あ<n>い%1"), 4)

    def test_poll_placeholder_counts_one(self):
        self.assertEqual(LB.visible_length('%1%2'), 2)

    def test_named_placeholder_counts_one(self):
        self.assertEqual(LB.visible_length('@a$Name$'), 1)

    def test_existing_node_does_not_add_width(self):
        self.assertEqual(LB.visible_length("あ<n>い<n:2>う"), 3)


class TestParsePositions(unittest.TestCase):

    def test_accepts_ascending(self):
        self.assertEqual(LB.parse_positions("0x1", [9, 18]), [9, 18])

    def test_rejects_zero(self):
        with self.assertRaises(LB.ManualBreakError):
            LB.parse_positions("0x1", [0])

    def test_rejects_not_ascending(self):
        with self.assertRaises(LB.ManualBreakError):
            LB.parse_positions("0x1", [9, 9])

    def test_rejects_non_int(self):
        with self.assertRaises(LB.ManualBreakError):
            LB.parse_positions("0x1", ["12"])

    def test_rejects_empty(self):
        with self.assertRaises(LB.ManualBreakError):
            LB.parse_positions("0x1", [])


class TestInsert(unittest.TestCase):

    def test_inserts_before_visible_char(self):
        self.assertEqual(LB.insert("あいうえお", [2], hid="0x1"), "あい<n>うえお")

    def test_skips_tags_when_counting(self):
        # 第 2 个可见字之前，标签不占位
        self.assertEqual(LB.insert("あ<gs:x>いう", [2], hid="0x1"),
                         "あ<gs:x>い<n>う")

    def test_limit_counts_space_as_boundary(self):
        # 位置不数空白：位置 3 是第 3 个非空白可见字（「え」）之前
        self.assertEqual(LB.insert("あいう えお", [3], limit=3, hid="0x1"),
                         "あいう <n>えお")

    def test_space_does_not_consume_a_position(self):
        self.assertEqual(LB.insert("あ い う", [2], hid="0x1"), "あ い <n>う")

    def test_limit_raises_when_segment_too_long(self):
        with self.assertRaises(LB.ManualBreakError):
            LB.insert("あいうえお", [2], limit=2, hid="0x1")

    def test_position_beyond_text_raises(self):
        with self.assertRaises(LB.ManualBreakError):
            LB.insert("あいうえお", [5], hid="0x1")


class TestReadTable(unittest.TestCase):

    def test_missing_file_is_empty_table(self):
        self.assertEqual(LB.read_table(os.path.join(ROOT, "build", "qa"), "zz"), {})

    def test_shipped_ja_table_parses(self):
        table = LB.read_table(ROOT, "ja")
        self.assertIsInstance(table, dict)


class TestJaWrap(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.lb = ja.JaLineBreak()

    def test_short_text_untouched(self):
        self.assertEqual(self.lb.wrap("短い文です。"), ("短い文です。", True, ""))

    def test_spaces_alone_already_break(self):
        # 每段都在上限内，不该插 <n>
        self.assertEqual(self.lb.wrap("これは とても 短い 文です。"),
                         ("これは とても 短い 文です。", True, ""))

    def test_cuts_after_particle(self):
        self.assertEqual(self.lb.wrap("所在地であってはなりません！"),
                         ("所在地であっては<n>なりません！", True, ""))

    def test_key_name_is_unbreakable(self):
        t = "IDM_CONTEST_01_2004_LOG_00_TEXT"
        self.assertEqual(self.lb.wrap(t), (t, False, t))

    def test_proper_noun_is_unbreakable(self):
        t = "インターナショナルプロダクトマネージャー"
        self.assertEqual(self.lb.wrap(t), (t, False, t))

    def test_reports_the_failed_segment_not_the_longest(self):
        # 前面能切的段照切，报的是后面那段含长专名的
        t = "所在地であってはなりません！ クラウス・シュテルテベッカーを"
        new, ok, bad = self.lb.wrap(t)
        self.assertFalse(ok)
        self.assertEqual(bad, "クラウス・シュテルテベッカーを")
        self.assertIn("<n>", new)


if __name__ == "__main__":
    unittest.main()
