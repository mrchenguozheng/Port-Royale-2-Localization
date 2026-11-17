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
    只有撞名才改用 town= / direction= 字段把类型写明（`kw` 已删）；`|` 是「或」的候选。
    `group` 列同组其余副本的文本键，`+` 连接，单副本不写。
    `clue` 的每一项必写 `<标签>:<正文>`：已知类型按类型校验，`_` 开头的自造标签
    静默，字母开头的自造标签报 warning；相邻同类型可用 `+` 并值，语义仍是「都要成立」。
    """

    VERSE = "[riddle:answer=St. Augustine;group=00000001;clue=pun:August,direction:north]He left for the north in August."

    def test_expands_to_nothing(self):
        self.assertEqual(M.expand(self.VERSE, TABLE, "zh"),
                         "He left for the north in August.")

    def test_does_not_count_as_name_usage(self):
        doc = {"0x00000001": self.VERSE}
        self.assertEqual(M.used_names(doc), set())

    def test_clue_missing_is_error(self):
        # 谜面里没有 south 这个词 → 这条谜面推不出这个答案
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=direction:south,pun:August]"
                     "He went north in August.", TABLE, "zh")
        self.assertIn("south", str(ctx.exception))

    def test_no_clue_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;group=00000001]He went north.", TABLE, "zh")

    def test_clue_case_insensitive(self):
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=direction:NORTH]He went north.",
                     TABLE, "zh"),
            "He went north.")

    def test_fullwidth_comma_rejected(self):
        # 线索只用英文逗号；全角「，」会把两个词粘成一条，报错比「命中不了」更好查
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=pun:north，pun:August]"
                     "He went north in August.", TABLE, "zh")
        self.assertIn(",", str(ctx.exception))

    def test_answer_without_kind_is_normal(self):
        # 类型前缀正常不写：值不在方位键里就当城镇查 entities.toml
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=pun:August]He went south in August.",
                     TABLE, "zh"),
            "He went south in August.")
        doc = {"0x00000001": "[riddle:answer=St. Augustine;group=00000001;clue=pun:August]He went south in August."}
        self.assertEqual(M.check_doc("zh", doc, entities={"St. Augustine": {}}, terms={}), [])

    def test_unknown_answer_prefix_is_error(self):
        # 写了前缀就必须是 town / direction；`kw` 已删，别想当前缀蒙过去
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=kw:Havana;group=00000001;clue=pun:August]He went south in August.",
                     TABLE, "zh")
        self.assertIn("kw", str(ctx.exception))

    def test_bare_clue_is_error(self):
        # 裸写不认：clue 每项都得有标签，写不出类型就写 `_` 开头的自造标签
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=north]He went north.", TABLE, "zh")
        self.assertIn("裸写", str(ctx.exception))

    def test_unknown_tag_scans_value(self):
        # 不是已知类型 → 只当标签：核对的是冒号后的正文，展开本身不失败
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=dirction:north]He went north.",
                     TABLE, "zh"),
            "He went north.")
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=aaa:He went north]He went north.",
                     TABLE, "zh"),
            "He went north.")

    def test_unknown_tag_warns(self):
        # 字母开头的自造标签要报 warning（多半是拼错类型名），`_` 开头的不报
        doc = {"0x00000001": "[riddle:answer=St. Augustine;group=00000001;clue=dirction:north]He went north."}
        warns = []
        self.assertEqual(M.check_doc("zh", doc, entities={"St. Augustine": {}}, terms={},
                                    warns=warns), [])
        self.assertEqual(len(warns), 1, warns)
        self.assertIn("dirction", warns[0])

        doc2 = {"0x00000001": "[riddle:answer=St. Augustine;group=00000001;clue=_hello:north]He went north."}
        warns2 = []
        self.assertEqual(M.check_doc("zh", doc2, entities={"St. Augustine": {}}, terms={},
                                     warns=warns2), [])
        self.assertEqual(warns2, [])

    def test_unknown_tag_blocks_build_under_strict_warns(self):
        # 构建前（strict_warns）自造标签必须升级成问题，不许以 W 级留到 build
        doc = {"0x00000001": "[riddle:answer=St. Augustine;group=00000001;clue=dirction:north]He went north."}
        problems = M.check_doc("zh", doc, entities={"St. Augustine": {}}, terms={},
                               warns=[], strict_warns=True)
        self.assertTrue(any("dirction" in p for p in problems), problems)
        # `_` 开头是显式声明，严格档也静默
        doc2 = {"0x00000001": "[riddle:answer=St. Augustine;group=00000001;clue=_hello:north]He went north."}
        self.assertEqual(M.check_doc("zh", doc2, entities={"St. Augustine": {}}, terms={},
                                     warns=[], strict_warns=True), [])

    def test_unknown_tag_still_needs_value(self):
        # 标签后面的正文不在谜面里，照样失败——未预定义不等于免检
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=aaa:south]He went north.",
                     TABLE, "zh")
        self.assertIn("south", str(ctx.exception))

    def test_tag_must_be_lowercase(self):
        # 大写标签报错：类型名区分大小写，`Pun:` 会被当成自造标签，不如直接拦住
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=Pun:August]He went south in August.",
                     TABLE, "zh")
        self.assertIn("Pun", str(ctx.exception))

    def test_digit_start_is_error(self):
        # `12:30` 不是标签（数字开头），裸写也不认 → 报错；要写就写 `feature:12:30`
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=12:30]He left at 12:30.",
                     TABLE, "zh")
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=feature:12:30]He left at 12:30.",
                     TABLE, "zh"),
            "He left at 12:30.")

    def test_empty_clue_value_is_error(self):
        # `clue=direction:` 只写了类型、没写原词，等于没指到正文任何东西
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=direction:]He went north.",
                     TABLE, "zh")

    def test_unknown_answer_is_reported(self):
        doc = {"0x00000001": "[riddle:answer=Nowhere;group=00000001;clue=direction:north]He went north."}
        problems = M.check_doc("zh", doc, entities={"St. Augustine": {}}, terms={})
        self.assertTrue(any("Nowhere" in p for p in problems), problems)

    def test_known_answer_passes(self):
        doc = {"0x00000001": self.VERSE}
        self.assertEqual(M.check_doc("zh", doc, entities={"St. Augustine": {}},
                                     terms={}), [])

    def test_direction_answer_needs_no_entity(self):
        # 方位谜底不进 entities.toml：它不是专名，也没有译名可登记
        doc = {"0x00000001": "[riddle:answer=southeast;group=00000001;clue=direction:东南]望向东南，第三座便是。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_answer_counts_as_used_name(self):
        # 谜底那座城的名字在诗里被替换成 X，正文本来就没有它；
        # 按「死条目」报会误伤，故谜底算一次引用
        doc = {"0x00000001": "[riddle:answer=San Juan;group=00000001;clue=direction:东南]X 在一座岛上，但望向东南。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}}, terms={})
        self.assertFalse(any("既没被引用" in p for p in problems), problems)

    def test_wrong_direction_answer_is_error(self):
        # 方位值必须真的是方位键；写错就是写错，不再靠「查不到就放过」蒙过去
        doc = {"0x00000001": "[riddle:answer=eastnorth;group=00000001;clue=direction:东南]望向东南，第三座便是。"}
        problems = M.check_doc("zh", doc, entities={}, terms={})
        self.assertTrue(any("eastnorth" in p for p in problems), problems)

    def test_negative_direction_answer_is_a_key(self):
        # 「往东南去航是白费力气」只能排除东南，写 -southeast 不替原文补正向
        doc = {"0x00000001": "[riddle:answer=-southeast;group=00000001;clue=exclude:东南]往东南去航是白费力气。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_not_word_form_is_accepted(self):
        # 收两种写法：`-north`（规范）与 `not north`（空格）；解析期归一成 -north
        for spelling in ("not north", "-north"):
            doc = {"0x00000001": "[riddle:answer=%s;group=00000001;clue=direction:北]北边什么也没有。"
                                 % spelling}
            self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [], spelling)

    def test_not_underscore_is_rejected(self):
        # 下划线写法不再接受：报错直接给两种合法写法
        for bad in ("not_north", "not_southeast"):
            with self.assertRaises(M.MarkError) as ctx:
                M.expand("[riddle:answer=%s;group=00000001;clue=direction:北]北边什么也没有。" % bad,
                         TABLE, "zh")
            self.assertIn("-north", str(ctx.exception))

    def test_long_direction_abbrev_is_accepted(self):
        # 长方位允许缩写，解析期补全成 northeast 这类完整键；大小写不限
        for abbr, full in (("NE", "northeast"), ("SE", "southeast"),
                           ("SW", "southwest"), ("NW", "northwest"),
                           ("ne", "northeast"), ("nW", "northwest")):
            doc = {"0x00000001": "[riddle:answer=%s;group=00000001;clue=direction:north]north 侧只有水。"
                                 % abbr}
            problems = M.check_doc("zh", doc, entities={}, terms={})
            self.assertEqual(problems, [], abbr)
            neg = {"0x00000001": "[riddle:answer=-%s;group=00000001;clue=direction:north]north 侧只有水。"
                                % abbr}
            self.assertEqual(M.check_doc("zh", neg, entities={}, terms={}), [], abbr)

    def test_full_direction_word_any_case_is_accepted(self):
        # 八个方位词的值域是封闭的，大小写怎么写都认；连 `not East` 也认
        for spelling in ("East", "east", "EAST", "eaSt",
                         "-East", "not East", "NOT east"):
            doc = {"0x00000001": "[riddle:answer=%s;group=00000001;clue=direction:north]north 侧只有水。"
                                 % spelling}
            self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [], spelling)

    def test_fullwidth_letters_are_rejected(self):
        # 只认半角 ASCII：全角字母肉眼和半角几乎一样，混进来必须当场点名
        for bad in ("ｅａｓｔ", "ＥＡＳＴ", "Ｅ", "nｏrth"):
            with self.assertRaises(M.MarkError) as ctx:
                M.expand("[riddle:answer=%s;group=00000001;clue=direction:north]north 侧只有水。" % bad,
                         TABLE, "zh")
            self.assertIn("全角", str(ctx.exception))
        for bad in ("ｅａｓｔ", "NＯＲＴＨ"):
            with self.assertRaises(M.MarkError) as ctx:
                M.expand("[riddle:direction=%s;group=00000001;clue=direction:north]north 侧只有水。" % bad,
                         TABLE, "zh")
            self.assertIn("全角", str(ctx.exception))
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:town=Ｖｅｒａ Ｃｒｕｚ;group=00000001;clue=direction:north]北边。", TABLE, "zh")
        self.assertIn("全角", str(ctx.exception))

    def test_cardinal_single_letter_is_accepted(self):
        # 值域封闭，裸的 `n` 只能是 north（要指同名地名就写 town=）；否定形态同理
        for spelling in ("N", "n", "E", "s", "-N", "not w"):
            doc = {"0x00000001": "[riddle:answer=%s;group=00000001;clue=direction:north]north 侧只有水。"
                                 % spelling}
            self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [], spelling)

    def test_cardinal_single_letter_under_direction_is_accepted(self):
        # 明写 direction= 时单字母一定是方向，N/E/S/W 及其否定形态都收
        for spelling, key in (("direction=N", "north"), ("direction=E", "east"),
                              ("direction=S", "south"), ("direction=W", "west"),
                              ("direction=-N", "not north"), ("direction=-E", "not east")):
            doc = {"0x00000001": "[riddle:%s;group=00000001;clue=direction:north]north 侧只有水。"
                                 % spelling}
            problems = M.check_doc("zh", doc, entities={}, terms={})
            self.assertEqual(problems, [], spelling)

    def test_lowercase_cardinal_under_direction_is_accepted(self):
        # direction= 明写类型，单字母大小写不再要求；正向与否定都收
        for spelling in ("direction=n", "direction=-s", "direction=E", "direction=-w"):
            doc = {"0x00000001": "[riddle:%s;group=00000001;clue=direction:north]north 侧只有水。"
                                 % spelling}
            self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [], spelling)

    def test_town_answer_ignores_case_and_diacritics(self):
        # 城名只比对「字母顺序 + 空格」：大小写、变音符号都不计较，对上就用登记名本身
        for canon, spelling in (("Vera Cruz", "vera cruz"), ("Vera Cruz", "VERA  CRUZ"),
                                ("Roatán", "Roatan"), ("Roatán", "roatán")):
            for field in ("answer", "town"):
                doc = {"0x00000001": "[riddle:%s=%s;group=00000001;clue=count:三座]三座城镇。"
                                     % (field, spelling)}
                self.assertEqual(M.check_doc("zh", doc, entities={canon: {}}, terms={}),
                                 [], (field, spelling))

    def test_town_answer_matching_two_names_is_error(self):
        # 折平后对上两条登记名，说明写法本身分不清是哪一条，必须按登记名原样写
        ents = {"San Juan": {}, "San Juán": {}}
        doc = {"0x00000001": "[riddle:town=san juan;group=00000001;clue=count:三座]三座城镇。"}
        problems = M.check_doc("zh", doc, entities=ents, terms={})
        self.assertTrue(any("多条登记名" in p for p in problems), problems)

    def test_town_answer_case_variants_share_group_signature(self):
        # 组内副本用不同大小写写同一个城名，归一后是同一串谜底，不能报不一致
        ents = {"Vera Cruz": {}}
        doc = {"0x00000001": "[riddle:town=vera cruz;group=00000001+00000002;clue=count:三座]三座城镇。",
               "0x00000002": "[riddle:town=VERA CRUZ;group=00000001+00000002;clue=count:三座]三座城镇。"}
        self.assertEqual(M.check_doc("zh", doc, entities=ents, terms={}), [])

    def test_bare_answer_matching_town_is_lenient(self):
        # answer= 也吃大小写/变音写法；判类型时同样先折平再查表
        doc = {"0x00000001": "[riddle:answer=veracruzx;group=00000001;clue=count:三座]三座城镇。"}
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("veracruzx" in p for p in problems), problems)
        doc2 = {"0x00000001": "[riddle:answer=east;group=00000001;clue=direction:东]望向东边。"}
        self.assertEqual(M.check_doc("zh", doc2, entities={}, terms={}), [])

    def test_answer_field_may_be_omitted_with_type(self):
        # 省略 answer=：字段名直接写 town= / direction=
        doc = {"0x00000001": "[riddle:town=Vera Cruz;group=00000001;clue=count:三座]三座城镇，X 在最西。",
               "0x00000002": "[riddle:direction=SE;group=00000002;clue=count:三座]三座城镇，去东南。"}
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertEqual(problems, [])

    def test_typed_field_with_group_is_fine(self):
        # 省略 answer= 后 group/clue 照旧；group 列全组含自己，8 位不带 0x
        doc = {"0x00000001": "[riddle:town=Vera Cruz;group=00000001+00000002;clue=count:三座]三座城镇。",
               "0x00000002": "[riddle:town=Vera Cruz;group=00000001+00000002;clue=count:三座]三座城镇。"}
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_answer_and_typed_field_conflict(self):
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=Vera Cruz;town=Havana;group=00000001;clue=count:三座]", TABLE, "zh")
        self.assertIn("两处", str(ctx.exception))

    def test_two_typed_answer_fields_conflict(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:town=Vera Cruz;town=Havana;group=00000001;clue=count:三座]", TABLE, "zh")

    def test_bare_untyped_field_is_error(self):
        # 没有 = 的片段不认（否则「哪个是谜底」失去依据）
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:Vera Cruz;group=00000001;clue=count:三座]", TABLE, "zh")
        self.assertIn("字段要写成", str(ctx.exception))

    def test_colon_prefix_is_rejected(self):
        # 类型声明改成字段后，值里不再收 `town:` / `direction:` 前缀
        for bad in ("answer=town:Vera Cruz", "answer=direction:SE"):
            with self.assertRaises(M.MarkError) as ctx:
                M.expand("[riddle:%s;group=00000001;clue=count:三座]三座城镇。" % bad, TABLE, "zh")
            self.assertIn("冒号", str(ctx.exception))
        # 整段写成 `town:城`（没有 =）连字段都算不上
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:town:Vera Cruz;group=00000001;clue=count:三座]三座城镇。", TABLE, "zh")
        self.assertIn("字段要写成", str(ctx.exception))

    def test_abbrev_normalizes_to_same_candidate(self):
        # NE 与 northeast 归一后是同一个候选，写两遍算重复
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=NE|northeast;group=00000001;clue=direction:东]north 侧只有水。",
                     TABLE, "zh")
        self.assertIn("重复", str(ctx.exception))

    def test_not_word_form_under_field_is_accepted(self):
        doc = {"0x00000001": "[riddle:direction=not north;group=00000001;clue=direction:北]"
                             "北边什么也没有。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_not_word_form_normalizes_to_same_candidate(self):
        # 归一的意义：两种写法不能把同一个谜底分裂成两串不同文本，写重就算重复
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=not north|-north;group=00000001;clue=direction:北]北边什么也没有。",
                     TABLE, "zh")
        self.assertIn("重复", str(ctx.exception))

    def test_bad_not_shapes_are_errors(self):
        # 大小写放宽后，`not East` 是合法写法；剩下的都是真形状错
        for bad in ("not", "not-", "not- north", "not eastnorth"):
            with self.assertRaises(M.MarkError):
                M.expand("[riddle:answer=%s;group=00000001;clue=direction:北]北边什么也没有。" % bad,
                         TABLE, "zh")

    def test_lone_dash_is_error(self):
        # `-East` 现在合法（负 east）；剩下这些还是形状错
        for bad in ("-", "--east", "-not_east", "-eastnorth"):
            with self.assertRaises(M.MarkError):
                M.expand("[riddle:answer=%s;group=00000001;clue=exclude:东南]往东南去航是白费力气。" % bad,
                         TABLE, "zh")

    def test_dash_lookalike_is_error(self):
        # 全角减号和长破折号肉眼几乎看不出，报错要直接点名是字符问题
        for bad in ("－east", "–east", "—east", "−east", "‐east"):
            with self.assertRaises(M.MarkError) as ctx:
                M.expand("[riddle:answer=%s;group=00000001;clue=exclude:东南]往东南去航是白费力气。" % bad,
                         TABLE, "zh")
            self.assertIn("ASCII", str(ctx.exception))

    def test_kw_answer_is_gone(self):
        # `kw` 谜底已删：谜底只能指到城镇或方位，写 kw 既不是方位键也没登记，
        # 报错要指名这个值，别让人以为它被当成城市名收下了
        ok = {"0x00000001": "[riddle:answer=kw;group=00000001;clue=produce:黄金,feature:港口]街道以黄金铺就，港口雄伟。"}
        problems = M.check_doc("zh", ok, entities={}, terms={})
        self.assertTrue(any("kw" in p for p in problems), problems)

    def test_plus_groups_same_kind(self):
        # `feature:白沙+丛林` 与 `feature:白沙,feature:丛林` 等价：两个词都要在谜面里
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=feature:白沙+丛林]"
                     "白沙与丛林。", TABLE, "zh"),
            "白沙与丛林。")
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=feature:白沙+峡谷]"
                     "白沙与丛林。", TABLE, "zh")
        self.assertIn("峡谷", str(ctx.exception))

    def test_plus_needs_value_on_both_sides(self):
        for bad in ("feature:白沙+", "feature:+丛林", "feature:白+  +沙"):
            with self.assertRaises(M.MarkError):
                M.expand("[riddle:answer=St. Augustine;group=00000001;clue=%s]白沙与丛林。" % bad,
                         TABLE, "zh")

    def test_alternative_names_both_count_as_used(self):
        # `|` 是「或」：两个候选都算被引用，也都要登记，否则死条目会误报其中一城
        doc = {"0x00000001": "[riddle:answer=San Juan|St. Juan;group=00000001;clue=feature:岛,direction:东南]"
                             "X 在一座岛上，望向东南。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}, "St. Juan": {}}, terms={})
        self.assertEqual(problems, [])

    def test_alternative_name_unregistered_is_reported(self):
        doc = {"0x00000001": "[riddle:answer=San Juan|Nowhere;group=00000001;clue=feature:岛]X 在一座岛上。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}}, terms={})
        self.assertTrue(any("Nowhere" in p for p in problems), problems)

    def test_alternative_mixing_town_and_direction(self):
        # 候选可以是不同类型：一座城或「不是北边」，两种都能解释谜面。
        # 混类型只能写 answer=，让每个值各自推断；town=/direction= 里放不了别的类型。
        doc = {"0x00000001": "[riddle:answer=San Juan|-north;group=00000001;clue=direction:北]"
                             "X 在北边什么也没有的地方。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}}, terms={})
        self.assertEqual(problems, [])

    def test_old_pipe_syntax_now_means_alternatives(self):
        # 旧写法 `[riddle:实体|线索]` 现在会被读成「两个候选、没有 clue」，必须报缺 clue，
        # 不能悄悄当成谜底+线索
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:St. Augustine|north]", TABLE, "zh")
        self.assertIn("clue", str(ctx.exception))

    def test_unknown_field_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=direction:north;note=x]He went north.",
                     TABLE, "zh")

    def test_duplicate_field_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;answer=Havana;group=00000001;clue=direction:north]"
                     "He went north.", TABLE, "zh")

    def test_empty_alternative_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=San Juan||St. Juan;group=00000001;clue=feature:岛]X is on an island.",
                     TABLE, "zh")


class TestAnswerGroup(unittest.TestCase):
    """`group` 列全组含本条自己：键形、成员存在、集合一致，谜底按字段比。"""

    A = "0x00000001"
    B = "0x00000002"
    C = "0x00000003"
    D = "0x00000004"

    @staticmethod
    def _b(key):
        """group 里写的是 8 位十六进制，不带 0x。"""
        return key[2:]

    def _doc(self, a, b, c=None, d=None):
        doc = {self.A: a, self.B: b}
        if c is not None:
            doc[self.C] = c
        if d is not None:
            doc[self.D] = d
        return doc

    S = ";clue=count:三座]三座城镇，X 在最西。"

    def _g(self, *keys):
        """整组的 group 段（含每个成员自己，升序）。"""
        return ";group=%s" % "+".join(sorted(self._b(k) for k in keys))

    def test_symmetric_pair_passes(self):
        same = self._g(self.A, self.B) + self.S
        doc = self._doc("[riddle:answer=Vera Cruz%s" % same,
                        "[riddle:answer=Vera Cruz%s" % same)
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_three_copies_pass(self):
        same = self._g(self.A, self.B, self.C) + self.S
        doc = self._doc("[riddle:answer=Vera Cruz%s" % same,
                        "[riddle:answer=Vera Cruz%s" % same,
                        "[riddle:answer=Vera Cruz%s" % same)
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_group_is_required(self):
        # 不可省略：单副本也要写 group=<自己>
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=Vera Cruz%s" % self.S, TABLE, "zh", self.A)
        self.assertIn("缺 group", str(ctx.exception))

    def test_group_must_include_self(self):
        # 列全组含自己：只写别人就是漏了本条
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=Vera Cruz;group=%s%s" % (self._b(self.B), self.S),
                     TABLE, "zh", self.A)
        self.assertIn("漏了本条自己", str(ctx.exception))

    def test_self_only_group_is_legal(self):
        doc = {self.A: "[riddle:answer=Vera Cruz%s%s" % (self._g(self.A), self.S)}
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_unordered_keys_are_error(self):
        # 升序是为了让「同组几条」一眼可比，也让人手写与 --apply 的结果一致
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=Vera Cruz;group=%s+%s%s"
                     % (self._b(self.C), self._b(self.A), self.S), TABLE, "zh", self.A)
        self.assertIn("升序", str(ctx.exception))

    def test_0x_prefix_is_error(self):
        # 有 0x 就比 8 位多两个字符，且大小写会分叉
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=Vera Cruz;group=%s;clue=count:三座]X。"
                     % self.B, TABLE, "zh", self.A)

    def test_bad_key_form_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=Vera Cruz;group=%sZZZ%s" % (self._b(self.A), self.S),
                     TABLE, "zh", self.A)

    def test_empty_token_is_error(self):
        # `+` 两侧都要有键：多打一个 `+` 就是空项
        for bad in ("%s+" % self._b(self.A), "+%s" % self._b(self.A),
                    "%s++%s" % (self._b(self.A), self._b(self.B))):
            with self.assertRaises(M.MarkError):
                M.expand("[riddle:answer=Vera Cruz;group=%s%s" % (bad, self.S), TABLE, "zh")

    def test_member_set_mismatch_is_reported(self):
        # A 列了三个人、B 只列了自己：B 的键列表与整组不等
        doc = self._doc(
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.A, self.B, self.C), self.S),
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.B), self.S),
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.A, self.B, self.C), self.S))
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("组员集合不一致" in p for p in problems), problems)

    def test_answer_mismatch_is_reported(self):
        same = self._g(self.A, self.B) + self.S
        doc = self._doc("[riddle:answer=Vera Cruz%s" % same,
                        "[riddle:answer=Santa Marta%s" % same)
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}, "Santa Marta": {}},
                               terms={})
        self.assertTrue(any("城镇部分不一致" in p for p in problems), problems)

    def test_town_mismatch_is_reported(self):
        same = self._g(self.A, self.B) + self.S
        doc = self._doc("[riddle:town=Vera Cruz%s" % same,
                        "[riddle:town=Santa Marta%s" % same)
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}, "Santa Marta": {}},
                               terms={})
        self.assertTrue(any("城镇部分不一致" in p for p in problems), problems)

    def test_answer_and_town_fields_share_comparison(self):
        # 一条写 answer=、另一条写 town=：都是「指明是城镇」，值相同就算一致
        same = self._g(self.A, self.B) + self.S
        doc = self._doc("[riddle:answer=Vera Cruz%s" % same,
                        "[riddle:town=Vera Cruz%s" % same)
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_answer_and_town_fields_mismatch_is_reported(self):
        same = self._g(self.A, self.B) + self.S
        doc = self._doc("[riddle:answer=Vera Cruz%s" % same,
                        "[riddle:town=Santa Marta%s" % same)
        problems = M.check_doc("zh", doc,
                               entities={"Vera Cruz": {}, "Santa Marta": {}}, terms={})
        self.assertTrue(any("城镇部分不一致" in p for p in problems), problems)

    def test_direction_does_not_participate(self):
        # 只有 direction 的成员不参与比对：同组可以用不同方位写法
        same = self._g(self.A, self.B) + self.S
        doc = self._doc("[riddle:direction=SE%s" % same,
                        "[riddle:direction=north%s" % same)
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_direction_part_of_answer_does_not_participate(self):
        # `answer=` 里的方位候选拆开后不比对：`San Juan|-north` 与 `San Juan` 同组不算不一致
        same = self._g(self.A, self.B) + self.S
        doc = self._doc("[riddle:answer=San Juan|-north%s" % same,
                        "[riddle:answer=San Juan%s" % same)
        self.assertEqual(M.check_doc("zh", doc, entities={"San Juan": {}}, terms={}), [])

    def test_all_direction_answers_skip_comparison(self):
        # 整条谜底都是方位：比较为空，不参与
        same = self._g(self.A, self.B) + self.S
        doc = self._doc("[riddle:answer=-north%s" % same,
                        "[riddle:answer=-southwest%s" % same)
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_town_part_of_answer_still_compared(self):
        same = self._g(self.A, self.B) + self.S
        doc = self._doc("[riddle:answer=San Juan|-north%s" % same,
                        "[riddle:answer=Havana|-north%s" % same)
        problems = M.check_doc("zh", doc, entities={"San Juan": {}, "Havana": {}},
                               terms={})
        self.assertTrue(any("城镇部分不一致" in p for p in problems), problems)

    def test_member_without_riddle_is_reported(self):
        doc = self._doc(
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.A, self.B), self.S),
            "普通一句，没有标注。")
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("没有 riddle" in p for p in problems), problems)

    def test_alternatives_must_match_across_copies(self):
        # `|` 是「这一组答案还没定」：副本之间必须写同一串候选
        doc = self._doc(
            "[riddle:answer=Vera Cruz|Santa Marta%s%s" % (self._g(self.A, self.B), self.S),
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.A, self.B), self.S))
        problems = M.check_doc("zh", doc,
                               entities={"Vera Cruz": {}, "Santa Marta": {}}, terms={})
        self.assertTrue(any("城镇部分不一致" in p for p in problems), problems)

    def test_same_text_without_any_group_is_reported(self):
        # 两条同文各自写成单副本（各自 group=自己），集合自洽，只能从谜面反查
        doc = self._doc(
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.A), self.S),
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.B), self.S))
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("逐字相同" in p and "group" in p for p in problems), problems)

    def test_same_text_with_different_answers_is_reported(self):
        doc = self._doc(
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.A), self.S),
            "[riddle:answer=Santa Marta%s%s" % (self._g(self.B), self.S))
        problems = M.check_doc("zh", doc,
                               entities={"Vera Cruz": {}, "Santa Marta": {}}, terms={})
        self.assertTrue(any("逐字相同" in p and "answer" in p for p in problems), problems)

    def test_different_texts_may_share_answer(self):
        # 反方向不立：不同谜面可以同谜底（Roatán 在 14/15 两组、Providence 在 20/26 两组）
        doc = self._doc(
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.A), self.S),
            "[riddle:answer=Vera Cruz%s;clue=count:三座]三座城，X 在西边。" % self._g(self.B))
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_same_text_across_case_and_spacing_is_reported(self):
        # 同文判定折平：全半角以外的写法差异不该让它漏过去
        doc = self._doc(
            "[riddle:answer=Vera Cruz%s%s" % (self._g(self.A), self.S),
            "[riddle:answer=vera  cruz%s%s" % (self._g(self.B), self.S))
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("逐字相同" in p for p in problems), problems)


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
