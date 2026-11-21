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

    def test_inserts_space_before_visible_char(self):
        # 手工层只补空格，不写 <n>
        self.assertEqual(LB.insert("あいうえお", [2], hid="0x1"), "あい うえお")

    def test_skips_tags_when_counting(self):
        # 第 2 个可见字之前，标签不占位
        self.assertEqual(LB.insert("あ<gs:x>いう", [2], hid="0x1"),
                         "あ<gs:x>い う")

    def test_limit_counts_space_as_boundary(self):
        # 位置不数空白：位置 3 是第 3 个非空白可见字（「え」）之前
        self.assertEqual(LB.insert("あいう えお", [3], limit=3, hid="0x1"),
                         "あいう えお")

    def test_space_does_not_consume_a_position(self):
        self.assertEqual(LB.insert("あ い う", [2], hid="0x1"), "あ い う")

    def test_no_double_space_when_position_lands_on_space(self):
        # 位置落在已有空白上，不再补第二个空格
        self.assertEqual(LB.insert("あ い", [1], hid="0x1"), "あ い")

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


class TestReadSkip(unittest.TestCase):

    def test_missing_file_is_empty_set(self):
        self.assertEqual(LB.read_skip(os.path.join(ROOT, "build", "qa"), "zz"), {})

    def test_shipped_ja_skip_has_dev_placeholder(self):
        skip = LB.read_skip(ROOT, "ja")
        self.assertIn("0xd3481940", skip)


class TestJaWrap(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.lb = ja.JaLineBreak()

    def test_short_text_untouched(self):
        self.assertEqual(self.lb.wrap("短い文です。"), ("短い文です。", True, "", False))

    def test_spaces_alone_already_break(self):
        # 每段都在上限内，不该插 <n>
        self.assertEqual(self.lb.wrap("これは とても 短い 文です。"),
                         ("これは とても 短い 文です。", True, "", False))

    def test_cuts_after_particle(self):
        self.assertEqual(self.lb.wrap("所在地であってはなりません！"),
                         ("所在地であっては<n>なりません！", True, "", False))

    def test_key_name_is_unbreakable(self):
        t = "IDM_CONTEST_01_2004_LOG_00_TEXT"
        self.assertEqual(self.lb.wrap(t), (t, False, t, False))

    def test_proper_noun_is_unbreakable(self):
        t = "インターナショナルプロダクトマネージャー"
        self.assertEqual(self.lb.wrap(t), (t, False, t, False))

    def test_reports_the_failed_segment_not_the_longest(self):
        # 前面能切的段照切，报的是后面那段含长专名的
        t = "所在地であってはなりません！ クラウス・シュテルテベッカーを"
        new, ok, bad, _used = self.lb.wrap(t)
        self.assertFalse(ok)
        self.assertEqual(bad, "クラウス・シュテルテベッカーを")
        self.assertIn("<n>", new)

    def test_fix_covers_the_block_it_lands_in(self):
        # 手工位置落在后一块：那一块由人工决定，前一块的机械 <n> 保留
        t = "所在地であってはなりません！ クラウス・シュテルテベッカーを"
        fix = lambda whole: LB.cover(whole, [18, 19], limit=13, hid="x")
        new, ok, bad, used = self.lb.wrap(t, fix=fix)
        self.assertTrue(ok)
        self.assertTrue(used)
        self.assertEqual(bad, "")
        self.assertIn("<n>", new)                      # 前一块的机械切还在
        self.assertIn("クラウス ・ シュテルテベッカーを", new)

    def test_fix_drops_mechanical_cut_inside_the_block(self):
        # 机械把「かも」割开；人工点了这一块，块里的 <n> 就作废
        t = "船が沈んで生存者がいるかもしれません。"
        fix = lambda whole: LB.cover(whole, [9], limit=13, hid="x")
        new, ok, _bad, used = self.lb.wrap(t, fix=fix)
        self.assertTrue(ok)
        self.assertTrue(used)
        self.assertNotIn("<n>", new)
        self.assertEqual(new, "船が沈んで生存者が いるかもしれません。")

    def test_fix_that_still_overflows_stays_unresolved(self):
        t = "所在地であってはなりません！ クラウス・シュテルテベッカーを"
        fix = lambda whole: LB.cover(whole, [400], limit=13, hid="x")
        new, ok, bad, used = self.lb.wrap(t, fix=fix)
        self.assertFalse(ok)
        self.assertFalse(used)
        self.assertEqual(bad, "クラウス・シュテルテベッカーを")

    def test_fix_that_changes_nothing_does_not_count_as_manual(self):
        # 位置全落在已有空白上时不改文本，也不该算「用了手工」
        t = "これは とても 短い 文です。"
        fix = lambda whole: LB.cover(whole, [3], limit=13, hid="x")
        new, ok, _bad, used = self.lb.wrap(t, fix=fix)
        self.assertTrue(ok)
        self.assertFalse(used)
        self.assertEqual(new, t)


class TestCover(unittest.TestCase):

    def test_leaves_other_blocks_alone(self):
        t = "あ<n>い かきくけこ"
        self.assertEqual(LB.cover(t, [2, 3], limit=13, hid="x"), "あ<n>い か きくけこ")

    def test_position_between_blocks_is_skipped(self):
        t = "あい かき"
        self.assertEqual(LB.cover(t, [2], limit=13, hid="x"), "あい かき")

    def test_position_outside_raises(self):
        with self.assertRaises(LB.ManualBreakError):
            LB.cover("あい かき", [9], limit=13, hid="x")

    def test_too_long_block_raises(self):
        with self.assertRaises(LB.ManualBreakError):
            LB.cover("あいかき", [1], limit=2, hid="x")


if __name__ == "__main__":
    unittest.main()
