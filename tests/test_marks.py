# -*- coding: utf-8 -*-
"""内联标注回归：解析、展开、缺条目/缺形态/未知关键字都要明确失败。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from text import marks as M  # noqa: E402

TABLE = {
    "Charleston": {"default": "查尔斯顿"},
    "Havana": {"default": "哈瓦那", "gen": "Хаваны"},
    "Miles Sound System": "Miles Sound System",
}


class TestExpand(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(M.expand("普通一句。", TABLE, "zh"), "普通一句。")

    def test_ref(self):
        self.assertEqual(M.expand("[ref:Charleston]遭到围攻。", TABLE, "zh"),
                         "查尔斯顿遭到围攻。")

    def test_ref_form(self):
        self.assertEqual(M.expand("в [ref:Havana|gen]", TABLE, "ru"),
                         "в Хаваны")

    def test_ref_form_missing(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:Havana|dat]", TABLE, "ru")

    def test_ref_unknown(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:Nowhere]", TABLE, "zh")

    def test_string_entry_only_default(self):
        self.assertEqual(M.expand("[ref:Miles Sound System]", TABLE, "zh"),
                         "Miles Sound System")
        with self.assertRaises(M.MarkError):
            M.expand("[ref:Miles Sound System|gen]", TABLE, "zh")

    def test_lit(self):
        self.assertEqual(M.expand("[lit:%2 %1日]", TABLE, "zh"), "%2 %1日")

    def test_keyword_unknown(self):
        with self.assertRaises(M.MarkError):
            M.expand("[keep:sample]", TABLE, "zh")

    def test_unclosed(self):
        with self.assertRaises(M.MarkError):
            M.expand("半个 [ref:Charleston", TABLE, "zh")

    def test_bare_bracket(self):
        with self.assertRaises(M.MarkError):
            M.expand("[F4CF1] 这一类界面标记不能进译文。", TABLE, "zh")

    def test_nested_arg(self):
        with self.assertRaises(M.MarkError):
            M.expand("[lit:a[ref:Charleston]b]", TABLE, "zh")

    def test_two_marks(self):
        self.assertEqual(M.expand("[ref:Havana]与[ref:Charleston]", TABLE, "es"),
                         "哈瓦那与查尔斯顿")

    def test_term(self):
        self.assertEqual(
            M.expand("一家[term:en_business]可雇用", TABLE, "zh",
                     terms={"en_business": "产业"}),
            "一家产业可雇用")

    def test_term_missing(self):
        with self.assertRaises(M.MarkError):
            M.expand("[term:en_tools]", TABLE, "zh", terms={"en_business": "产业"})

    def test_term_needs_lang_prefix(self):
        with self.assertRaises(M.MarkError):
            M.expand("[term:business]", TABLE, "zh", terms={"en_business": "产业"})

    def test_term_unknown_prefix(self):
        with self.assertRaises(M.MarkError):
            M.expand("[term:xx_business]", TABLE, "zh", terms={"en_business": "产业"})

    def test_term_form_forbidden(self):
        # `|` 是 ref 的形态分隔符，term 只接受 <语言>_<原词>
        with self.assertRaises(M.MarkError):
            M.expand("[term:en_business|产业]", TABLE, "zh",
                     terms={"en_business": "产业"})

    def test_term_dead_entry(self):
        doc = {"0x00000001": "[term:en_business]"}
        problems = M.check_doc("zh", doc, entities={},
                               terms={"en_business": "产业", "en_tools": "工具"})
        self.assertTrue(any("en_tools" in p for p in problems), problems)


class TestAnswerMark(unittest.TestCase):
    """[ans:…] 是给翻译人看的谜底，展开必须为空；线索词必须真在谜面里。"""

    VERSE = "[ans:St. Augustine|north,August]He left for the north in August."

    def test_expands_to_nothing(self):
        self.assertEqual(M.expand(self.VERSE, TABLE, "zh"),
                         "He left for the north in August.")

    def test_does_not_count_as_name_usage(self):
        doc = {"0x00000001": self.VERSE}
        self.assertEqual(M.used_names(doc), set())

    def test_clue_missing_is_error(self):
        # 谜面里没有 north 这个词 → 这条谜面推不出这个答案
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[ans:St. Augustine|south,August]He went north in August.",
                     TABLE, "zh")
        self.assertIn("south", str(ctx.exception))

    def test_no_clue_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ans:St. Augustine]He went north.", TABLE, "zh")

    def test_clue_case_insensitive(self):
        self.assertEqual(M.expand("[ans:St. Augustine|NORTH]He went north.", TABLE, "zh"),
                         "He went north.")

    def test_fullwidth_comma_rejected(self):
        # 线索只用英文逗号；全角「，」会把两个词粘成一条，报错比「命中不了」更好查
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[ans:St. Augustine|north，August]He went north in August.",
                     TABLE, "zh")
        self.assertIn(",", str(ctx.exception))

    def test_unknown_answer_is_reported(self):
        doc = {"0x00000001": "[ans:Nowhere|north]He went north."}
        problems = M.check_doc("zh", doc, entities={"St. Augustine": {}}, terms={})
        self.assertTrue(any("Nowhere" in p for p in problems), problems)

    def test_known_answer_passes(self):
        doc = {"0x00000001": self.VERSE}
        self.assertEqual(M.check_doc("zh", doc, entities={"St. Augustine": {}},
                                     terms={}), [])


class TestDoc(unittest.TestCase):
    def test_exempt_key(self):
        raw = '"``°§$%&()=?\\^<|>@/*~[]"'
        doc = {"0x11f0398f": raw}
        self.assertEqual(M.expand_doc("zh", doc), doc)

    def test_no_marks_untouched(self):
        doc = {"0x00000001": "产业", "0x00000002": ""}
        self.assertEqual(M.expand_doc("zh", doc), doc)

    def test_used_names(self):
        doc = {"0x00000001": "[ref:Charleston]与[ref:Havana|gen]",
               "0x00000002": "无标注"}
        self.assertEqual(M.used_names(doc), {"Charleston", "Havana"})


if __name__ == "__main__":
    unittest.main()
