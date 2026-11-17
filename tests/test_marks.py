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
        self.assertEqual(M.expand("[town:Charleston]遭到围攻。", TABLE, "zh"),
                         "查尔斯顿遭到围攻。")

    def test_ref_form(self):
        self.assertEqual(M.expand("в [town:Havana|gen]", TABLE, "ru"),
                         "в Хаваны")

    def test_ref_form_missing(self):
        with self.assertRaises(M.MarkError):
            M.expand("[town:Havana|dat]", TABLE, "ru")

    def test_ref_unknown(self):
        with self.assertRaises(M.MarkError):
            M.expand("[town:Nowhere]", TABLE, "zh")

    def test_string_entry_only_default(self):
        self.assertEqual(M.expand("[town:Miles Sound System]", TABLE, "zh"),
                         "Miles Sound System")
        with self.assertRaises(M.MarkError):
            M.expand("[town:Miles Sound System|gen]", TABLE, "zh")

    def test_lit(self):
        self.assertEqual(M.expand("[lit:%2 %1日]", TABLE, "zh"), "%2 %1日")

    def test_keyword_unknown(self):
        with self.assertRaises(M.MarkError):
            M.expand("[keep:sample]", TABLE, "zh")

    def test_unclosed(self):
        with self.assertRaises(M.MarkError):
            M.expand("半个 [town:Charleston", TABLE, "zh")

    def test_bare_bracket(self):
        with self.assertRaises(M.MarkError):
            M.expand("[F4CF1] 这一类界面标记不能进译文。", TABLE, "zh")

    def test_nested_arg(self):
        with self.assertRaises(M.MarkError):
            M.expand("[lit:a[town:Charleston]b]", TABLE, "zh")

    def test_two_marks(self):
        self.assertEqual(M.expand("[town:Havana]与[town:Charleston]", TABLE, "es"),
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
        # `|` 是 town 的形态分隔符，term 只接受 <语言>_<原词>
        with self.assertRaises(M.MarkError):
            M.expand("[term:en_business|产业]", TABLE, "zh",
                     terms={"en_business": "产业"})

    def test_term_dead_entry(self):
        doc = {"0x00000001": "[term:en_business]"}
        problems = M.check_doc("zh", doc, entities={},
                               terms={"en_business": "产业", "en_tools": "工具"})
        self.assertTrue(any("en_tools" in p for p in problems), problems)

    def test_term_alive_when_only_case_differs(self):
        # 西语正文里是小写 bucanero，表里写 Bucanero —— 不是死条目
        doc = {"0x00000001": "seguro que ya te has enfrentado a un bucanero"}
        problems = M.check_doc("es", doc, entities={},
                               terms={"en_buccaneer": "Bucanero"})
        self.assertEqual(problems, [])

    def test_term_alive_when_inflected(self):
        # 俄语正文里是 колонии，表里写主格 Колония —— 不是死条目
        doc = {"0x00000001": "жители колонии ждут корабль"}
        problems = M.check_doc("ru", doc, entities={},
                               terms={"en_colony": "Колония"})
        self.assertEqual(problems, [])

    def test_term_still_dead_in_inflected_language(self):
        # 死条目校验只在正文确实用过术语时才跑，所以先放一条被引用的术语
        doc = {"0x00000001": "[term:en_business] совсем другой текст"}
        problems = M.check_doc("ru", doc, entities={},
                               terms={"en_business": "Дела",
                                      "en_colony": "Колония"})
        self.assertTrue(any("en_colony" in p for p in problems), problems)


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

    def test_direction_answer_needs_no_entity(self):
        # 方位谜底不进 entities.toml：它不是专名，也没有译名可登记
        doc = {"0x00000001": "[ans:southeast|东南]望向东南，第三座便是。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_answer_counts_as_used_name(self):
        # 谜底那座城的名字在诗里被替换成 X，正文本来就没有它；
        # 按「死条目」报会误伤，故谜底算一次引用
        doc = {"0x00000001": "[ans:San Juan|东南]X 在一座岛上，但望向东南。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}}, terms={})
        self.assertFalse(any("既没被引用" in p for p in problems), problems)

    def test_wrong_direction_answer_still_passes_but_key_must_be_known(self):
        doc = {"0x00000001": "[ans:eastnorth|东南]望向东南，第三座便是。"}
        problems = M.check_doc("zh", doc, entities={}, terms={})
        self.assertTrue(any("eastnorth" in p for p in problems), problems)

    def test_negative_direction_answer_is_a_key(self):
        # 「往东南去航是白费力气」只能排除东南，写 not_southeast 不替原文补正向
        doc = {"0x00000001": "[ans:not_southeast|东南]往东南去航是白费力气。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_keyword_answer_needs_two_clues(self):
        ok = {"0x00000001": "[ans:kw|黄金,港口]街道以黄金铺就，港口雄伟。"}
        self.assertEqual(M.check_doc("zh", ok, entities={}, terms={}), [])
        bad = {"0x00000001": "[ans:kw|黄金]街道以黄金铺就，港口雄伟。"}
        problems = M.check_doc("zh", bad, entities={}, terms={})
        self.assertTrue(any("关键词组合" in p for p in problems), problems)


class TestDoc(unittest.TestCase):
    def test_exempt_key(self):
        raw = '"``°§$%&()=?\\^<|>@/*~[]"'
        doc = {"0x11f0398f": raw}
        self.assertEqual(M.expand_doc("zh", doc), doc)

    def test_no_marks_untouched(self):
        doc = {"0x00000001": "产业", "0x00000002": ""}
        self.assertEqual(M.expand_doc("zh", doc), doc)

    def test_used_names(self):
        doc = {"0x00000001": "[town:Charleston]与[town:Havana|gen]",
               "0x00000002": "无标注"}
        self.assertEqual(M.used_names(doc), {"Charleston", "Havana"})


if __name__ == "__main__":
    unittest.main()
