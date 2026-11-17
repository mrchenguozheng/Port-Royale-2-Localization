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

    def test_town(self):
        self.assertEqual(M.expand("[town:Charleston]遭到围攻。", TABLE, "zh"),
                         "查尔斯顿遭到围攻。")

    def test_town_form(self):
        self.assertEqual(M.expand("в [town:Havana|gen]", TABLE, "ru"),
                         "в Хаваны")

    def test_town_form_missing(self):
        with self.assertRaises(M.MarkError):
            M.expand("[town:Havana|dat]", TABLE, "ru")

    def test_town_unknown(self):
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

    def test_ref_expands_target(self):
        doc = {"0xa": "[town:Charleston]遭到围攻。", "0xb": "[ref:0xa]"}
        self.assertEqual(M.expand("[ref:0xa]", TABLE, "zh", "0xb", doc=doc),
                         "查尔斯顿遭到围攻。")

    def test_ref_needs_doc(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0xa]", TABLE, "zh", "0xb")

    def test_ref_target_missing(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0xb]", TABLE, "zh", "0xc", doc={"0xa": "一句。"})

    def test_ref_target_empty(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0xa]", TABLE, "zh", "0xb", doc={"0xa": ""})

    def test_ref_self(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0xa]", TABLE, "zh", "0xa", doc={"0xa": "[ref:0xa]"})

    def test_ref_only_one_level(self):
        doc = {"0xa": "[ref:0xb]", "0xb": "[ref:0xa]"}
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0xa]", TABLE, "zh", "0xc", doc=doc)

    def test_ref_chain_caught_by_check_doc(self):
        doc = {"0x1": "[ref:0x2]", "0x2": "[ref:0x1]"}
        problems = M.check_doc("zh", doc)
        self.assertTrue(any("只许一层" in p for p in problems), problems)

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
    """[riddle:…] 是给翻译人看的谜底，展开必须为空；线索词必须真在谜面里。

    `answer` 正常不写类型：值在方位键里算方位，其余按城镇查 entities.toml，
    只有撞名才写 town: / direction: 消歧（`kw` 已删）；`|` 是「或」的候选。
    `group` 列同组其余副本的文本键，`+` 连接，单副本不写。
    `clue` 的每一项必写 `<标签>:<正文>`：已知类型按类型校验，`_` 开头的自造标签
    静默，字母开头的自造标签报 warning；相邻同类型可用 `+` 并值，语义仍是「都要成立」。
    """

    VERSE = "[riddle:answer=St. Augustine;clue=pun:August,direction:north]He left for the north in August."

    def test_expands_to_nothing(self):
        self.assertEqual(M.expand(self.VERSE, TABLE, "zh"),
                         "He left for the north in August.")

    def test_does_not_count_as_name_usage(self):
        doc = {"0x00000001": self.VERSE}
        self.assertEqual(M.used_names(doc), set())

    def test_clue_missing_is_error(self):
        # 谜面里没有 south 这个词 → 这条谜面推不出这个答案
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;clue=direction:south,pun:August]"
                     "He went north in August.", TABLE, "zh")
        self.assertIn("south", str(ctx.exception))

    def test_no_clue_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine]He went north.", TABLE, "zh")

    def test_clue_case_insensitive(self):
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;clue=direction:NORTH]He went north.",
                     TABLE, "zh"),
            "He went north.")

    def test_fullwidth_comma_rejected(self):
        # 线索只用英文逗号；全角「，」会把两个词粘成一条，报错比「命中不了」更好查
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;clue=pun:north，pun:August]"
                     "He went north in August.", TABLE, "zh")
        self.assertIn(",", str(ctx.exception))

    def test_answer_without_kind_is_normal(self):
        # 类型前缀正常不写：值不在方位键里就当城镇查 entities.toml
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;clue=pun:August]He went south in August.",
                     TABLE, "zh"),
            "He went south in August.")
        doc = {"0x00000001": "[riddle:answer=St. Augustine;clue=pun:August]He went south in August."}
        self.assertEqual(M.check_doc("zh", doc, entities={"St. Augustine": {}}, terms={}), [])

    def test_unknown_answer_prefix_is_error(self):
        # 写了前缀就必须是 town / direction；`kw` 已删，别想当前缀蒙过去
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=kw:Havana;clue=pun:August]He went south in August.",
                     TABLE, "zh")
        self.assertIn("kw", str(ctx.exception))

    def test_bare_clue_is_error(self):
        # 裸写不认：clue 每项都得有标签，写不出类型就写 `_` 开头的自造标签
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;clue=north]He went north.", TABLE, "zh")
        self.assertIn("裸写", str(ctx.exception))

    def test_unknown_tag_scans_value(self):
        # 不是已知类型 → 只当标签：核对的是冒号后的正文，展开本身不失败
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;clue=dirction:north]He went north.",
                     TABLE, "zh"),
            "He went north.")
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;clue=aaa:He went north]He went north.",
                     TABLE, "zh"),
            "He went north.")

    def test_unknown_tag_warns(self):
        # 字母开头的自造标签要报 warning（多半是拼错类型名），`_` 开头的不报
        doc = {"0x00000001": "[riddle:answer=St. Augustine;clue=dirction:north]He went north."}
        warns = []
        self.assertEqual(M.check_doc("zh", doc, entities={"St. Augustine": {}}, terms={},
                                    warns=warns), [])
        self.assertEqual(len(warns), 1, warns)
        self.assertIn("dirction", warns[0])

        doc2 = {"0x00000001": "[riddle:answer=St. Augustine;clue=_hello:north]He went north."}
        warns2 = []
        self.assertEqual(M.check_doc("zh", doc2, entities={"St. Augustine": {}}, terms={},
                                     warns=warns2), [])
        self.assertEqual(warns2, [])

    def test_unknown_tag_still_needs_value(self):
        # 标签后面的正文不在谜面里，照样失败——未预定义不等于免检
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;clue=aaa:south]He went north.",
                     TABLE, "zh")
        self.assertIn("south", str(ctx.exception))

    def test_tag_must_be_lowercase(self):
        # 大写标签报错：类型名区分大小写，`Pun:` 会被当成自造标签，不如直接拦住
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;clue=Pun:August]He went south in August.",
                     TABLE, "zh")
        self.assertIn("Pun", str(ctx.exception))

    def test_digit_start_is_error(self):
        # `12:30` 不是标签（数字开头），裸写也不认 → 报错；要写就写 `feature:12:30`
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;clue=12:30]He left at 12:30.",
                     TABLE, "zh")
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;clue=feature:12:30]He left at 12:30.",
                     TABLE, "zh"),
            "He left at 12:30.")

    def test_empty_clue_value_is_error(self):
        # `clue=direction:` 只写了类型、没写原词，等于没指到正文任何东西
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;clue=direction:]He went north.",
                     TABLE, "zh")

    def test_unknown_answer_is_reported(self):
        doc = {"0x00000001": "[riddle:answer=Nowhere;clue=direction:north]He went north."}
        problems = M.check_doc("zh", doc, entities={"St. Augustine": {}}, terms={})
        self.assertTrue(any("Nowhere" in p for p in problems), problems)

    def test_known_answer_passes(self):
        doc = {"0x00000001": self.VERSE}
        self.assertEqual(M.check_doc("zh", doc, entities={"St. Augustine": {}},
                                     terms={}), [])

    def test_direction_answer_needs_no_entity(self):
        # 方位谜底不进 entities.toml：它不是专名，也没有译名可登记
        doc = {"0x00000001": "[riddle:answer=southeast;clue=direction:东南]望向东南，第三座便是。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_answer_counts_as_used_name(self):
        # 谜底那座城的名字在诗里被替换成 X，正文本来就没有它；
        # 按「死条目」报会误伤，故谜底算一次引用
        doc = {"0x00000001": "[riddle:answer=San Juan;clue=direction:东南]X 在一座岛上，但望向东南。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}}, terms={})
        self.assertFalse(any("既没被引用" in p for p in problems), problems)

    def test_wrong_direction_answer_is_error(self):
        # 方位值必须真的是方位键；写错就是写错，不再靠「查不到就放过」蒙过去
        doc = {"0x00000001": "[riddle:answer=eastnorth;clue=direction:东南]望向东南，第三座便是。"}
        problems = M.check_doc("zh", doc, entities={}, terms={})
        self.assertTrue(any("eastnorth" in p for p in problems), problems)

    def test_negative_direction_answer_is_a_key(self):
        # 「往东南去航是白费力气」只能排除东南，写 not_southeast 不替原文补正向
        doc = {"0x00000001": "[riddle:answer=not_southeast;clue=exclude:东南]往东南去航是白费力气。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_kw_answer_is_gone(self):
        # `kw` 谜底已删：谜底只能指到城镇或方位，写 kw 既不是方位键也没登记，
        # 报错要指名这个值，别让人以为它被当成城市名收下了
        ok = {"0x00000001": "[riddle:answer=kw;clue=produce:黄金,feature:港口]街道以黄金铺就，港口雄伟。"}
        problems = M.check_doc("zh", ok, entities={}, terms={})
        self.assertTrue(any("kw" in p for p in problems), problems)

    def test_plus_groups_same_kind(self):
        # `feature:白沙+丛林` 与 `feature:白沙,feature:丛林` 等价：两个词都要在谜面里
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;clue=feature:白沙+丛林]"
                     "白沙与丛林。", TABLE, "zh"),
            "白沙与丛林。")
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;clue=feature:白沙+峡谷]"
                     "白沙与丛林。", TABLE, "zh")
        self.assertIn("峡谷", str(ctx.exception))

    def test_plus_needs_value_on_both_sides(self):
        for bad in ("feature:白沙+", "feature:+丛林", "feature:白+  +沙"):
            with self.assertRaises(M.MarkError):
                M.expand("[riddle:answer=St. Augustine;clue=%s]白沙与丛林。" % bad,
                         TABLE, "zh")

    def test_alternative_names_both_count_as_used(self):
        # `|` 是「或」：两个候选都算被引用，也都要登记，否则死条目会误报其中一城
        doc = {"0x00000001": "[riddle:answer=San Juan|town:St. Juan;clue=feature:岛,direction:东南]"
                             "X 在一座岛上，望向东南。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}, "St. Juan": {}}, terms={})
        self.assertEqual(problems, [])

    def test_alternative_name_unregistered_is_reported(self):
        doc = {"0x00000001": "[riddle:answer=San Juan|town:Nowhere;clue=feature:岛]X 在一座岛上。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}}, terms={})
        self.assertTrue(any("Nowhere" in p for p in problems), problems)

    def test_alternative_mixing_town_and_direction(self):
        # 候选可以是不同类型：一座城或「不是北边」，两种都能解释谜面
        doc = {"0x00000001": "[riddle:answer=San Juan|direction:not_north;clue=direction:北]"
                             "X 在北边什么也没有的地方。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}}, terms={})
        self.assertFalse(any("not_north" in p for p in problems), problems)

    def test_old_pipe_syntax_now_means_alternatives(self):
        # 旧写法 `[riddle:实体|线索]` 现在会被读成「两个候选、没有 clue」，必须报缺 clue，
        # 不能悄悄当成谜底+线索
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:St. Augustine|north]", TABLE, "zh")
        self.assertIn("clue", str(ctx.exception))

    def test_unknown_field_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;clue=direction:north;note=x]He went north.",
                     TABLE, "zh")

    def test_duplicate_field_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;answer=Havana;clue=direction:north]"
                     "He went north.", TABLE, "zh")

    def test_empty_alternative_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=San Juan||St. Juan;clue=feature:岛]X is on an island.",
                     TABLE, "zh")


class TestAnswerGroup(unittest.TestCase):
    """同谜底副本靠 `group` 互指：每组只列其余副本，两边都要列全，答案必须一致。"""

    A = "0x00000001"
    B = "0x00000002"
    C = "0x00000003"
    D = "0x00000004"

    def _doc(self, a, b, c=None, d=None):
        doc = {self.A: a, self.B: b}
        if c is not None:
            doc[self.C] = c
        if d is not None:
            doc[self.D] = d
        return doc

    S = ";clue=count:三座]三座城镇，X 在最西。"

    def test_symmetric_pair_passes(self):
        doc = self._doc(
            "[riddle:answer=Vera Cruz;group=%s%s" % (self.B, self.S),
            "[riddle:answer=Vera Cruz;group=%s%s" % (self.A, self.S))
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_three_copies_pass(self):
        doc = self._doc(
            "[riddle:answer=Vera Cruz;group=%s+%s%s" % (self.B, self.C, self.S),
            "[riddle:answer=Vera Cruz;group=%s+%s%s" % (self.A, self.C, self.S),
            "[riddle:answer=Vera Cruz;group=%s+%s%s" % (self.A, self.B, self.S))
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_self_not_allowed(self):
        # 自己列自己等于把「其余副本」变成「含本条的组」，hid 比对靠调用方传键
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=Vera Cruz;group=%s%s" % (self.A, self.S),
                     TABLE, "zh", self.A)
        self.assertIn("自己", str(ctx.exception))

    def test_bad_key_form_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=Vera Cruz;group=0xZZZ%s" % self.S, TABLE, "zh")

    def test_empty_token_is_error(self):
        # `+` 两侧都要有键：多打一个 `+` 就是空项
        for bad in ("%s+" % self.A, "+%s" % self.A, "%s++%s" % (self.A, self.B)):
            with self.assertRaises(M.MarkError):
                M.expand("[riddle:answer=Vera Cruz;group=%s%s" % (bad, self.S), TABLE, "zh")

    def test_asymmetric_is_reported(self):
        # A 列了 B，B 没列 A：一条链断在半路，翻译时看不出这组有几条
        doc = self._doc(
            "[riddle:answer=Vera Cruz;group=%s%s" % (self.B, self.S),
            "[riddle:answer=Vera Cruz%s" % self.S)
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("对称" in p for p in problems), problems)

    def test_member_set_mismatch_is_reported(self):
        doc = self._doc(
            "[riddle:answer=Vera Cruz;group=%s+%s%s" % (self.B, self.C, self.S),
            "[riddle:answer=Vera Cruz;group=%s%s" % (self.A, self.S),
            "[riddle:answer=Vera Cruz;group=%s%s" % (self.A, self.S))
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("组员集合" in p for p in problems), problems)

    def test_answer_mismatch_is_reported(self):
        doc = self._doc(
            "[riddle:answer=Vera Cruz;group=%s%s" % (self.B, self.S),
            "[riddle:answer=Santa Marta;group=%s%s" % (self.A, self.S))
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}, "Santa Marta": {}},
                               terms={})
        self.assertTrue(any("不一致" in p for p in problems), problems)

    def test_member_without_riddle_is_reported(self):
        doc = self._doc(
            "[riddle:answer=Vera Cruz;group=%s%s" % (self.B, self.S),
            "普通一句，没有标注。")
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("没有 riddle" in p for p in problems), problems)

    def test_alternatives_must_match_across_copies(self):
        # `|` 是「这一组答案还没定」：副本之间必须写同一串候选
        doc = self._doc(
            "[riddle:answer=Vera Cruz|Santa Marta;group=%s%s" % (self.B, self.S),
            "[riddle:answer=Vera Cruz;group=%s%s" % (self.A, self.S))
        problems = M.check_doc("zh", doc,
                               entities={"Vera Cruz": {}, "Santa Marta": {}}, terms={})
        self.assertTrue(any("不一致" in p for p in problems), problems)


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
