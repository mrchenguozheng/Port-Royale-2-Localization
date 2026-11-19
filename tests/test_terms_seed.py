#!/usr/bin/env python3
# coding: utf-8
"""术语表自动化与屈折匹配的回归用例。

判据都是「照这行会怎样」：
- 整行标签那一档（英文整条就是该词）必须直接取原形，单数优先于复数；
- 屈折语按词干比对（`Konwój` 认 `Konwoje`），非屈折语仍按整串；
- `copy=` 指向的成员正文与代表不同时必须点名，不许静默覆盖。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "tools"),
          os.path.join(ROOT, "src", "tools", "analysis"),
          os.path.join(ROOT, "src", "tools", "text")):
    if p not in sys.path:
        sys.path.insert(0, p)

import terms_seed as TS          # noqa: E402
import text_lint as L            # noqa: E402
import riddle_marks as RM        # noqa: E402


class TestTermsSeed(unittest.TestCase):
    def test_fold_strips_diacritics(self):
        self.assertEqual(TS.fold("Żeglarz"), "zeglarz")
        self.assertEqual(TS.fold("Kryjówkę"), "kryjowke")

    def test_clean_drops_tags(self):
        self.assertEqual(TS.clean("  <n>Kryjówka  "), "Kryjówka")

    def test_cluster_merges_inflections(self):
        self.assertEqual(TS.cluster_key("pirat"), TS.cluster_key("piratów"))
        self.assertEqual(TS.cluster_key("magazyn"), TS.cluster_key("magazynu"))

    def test_anchor_rx_is_word_bounded(self):
        rx = TS.anchor_rx("market")
        self.assertTrue(rx.search("the market"))
        self.assertFalse(rx.search("marketing"))

    def test_label_value_prefers_singular(self):
        rows = [("a", "Warehouse", "Magazyn "),
                ("b", "Warehouses", "Magazyny"),
                ("c", "Warehouses", "Magazyny")]
        self.assertEqual(TS.label_value("Warehouse", rows)[0], "Magazyn")

    def test_label_value_none_without_whole_line(self):
        rows = [("a", "Deliver goods to the market", "Dostarcz towar na rynek")]
        self.assertIsNone(TS.label_value("market", rows)[0])


class TestTermHit(unittest.TestCase):
    def test_exact_match_any_language(self):
        """整串比对沿用原有口径：大小写与重音都算不同的事。"""
        self.assertTrue(L.term_hit("Konwój", "Zniszcz Konwój wroga", "de"))

    def test_inflected_match_for_polish(self):
        self.assertTrue(L.term_hit("Konwój", "Dwa konwoje płyną", "pl"))
        self.assertTrue(L.term_hit("Pirat", "Piraci atakują", "pl"))
        self.assertTrue(L.term_hit("Kryjówka", "w jego kryjówce", "pl"))
        self.assertTrue(L.term_hit("jakość życia", "poziom jakości życia", "pl"))

    def test_non_inflected_language_stays_exact(self):
        self.assertFalse(L.term_hit("Konwój", "Dwa konwoje płyną", "de"))

    def test_absent_word_is_miss(self):
        self.assertFalse(L.term_hit("Konwój", "Zniszcz flotę wroga", "pl"))


class TestRiddleCopyBody(unittest.TestCase):
    def test_same_body_no_conflict(self):
        doc = {"0x1": "[riddle:answer=Port Royal]Zagadka", "0x2": "Zagadka"}
        self.assertFalse(RM.body_conflict(doc, "0x2", "0x1"))

    def test_different_body_conflicts(self):
        doc = {"0x1": "[riddle:answer=Port Royal]Zagadka", "0x2": "Inna zagadka"}
        self.assertTrue(RM.body_conflict(doc, "0x2", "0x1"))


if __name__ == "__main__":
    unittest.main()
