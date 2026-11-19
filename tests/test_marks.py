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
        doc = {"0x0000000a": "[town:Charleston]遭到围攻。",
               "0x0000000b": "[ref:0x0000000a]"}
        self.assertEqual(M.expand("[ref:0x0000000a]", TABLE, "zh", "0x0000000b", doc=doc),
                         "查尔斯顿遭到围攻。")

    def test_ref_needs_doc(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0x0000000a]", TABLE, "zh", "0x0000000b")

    def test_ref_target_missing(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0x0000000b]", TABLE, "zh", "0x0000000c",
                     doc={"0x0000000a": "一句。"})

    def test_ref_target_empty(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0x0000000a]", TABLE, "zh", "0x0000000b",
                     doc={"0x0000000a": ""})

    def test_ref_self(self):
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0x0000000a]", TABLE, "zh", "0x0000000a",
                     doc={"0x0000000a": "[ref:0x0000000a]"})

    def test_ref_only_one_level(self):
        doc = {"0x0000000a": "[ref:0x0000000b]",
               "0x0000000b": "[ref:0x0000000a]"}
        with self.assertRaises(M.MarkError):
            M.expand("[ref:0x0000000a]", TABLE, "zh", "0x0000000c", doc=doc)

    def test_ref_target_without_0x(self):
        # 引用键的写法宽容：`0x` 可省，大小写照收，落到同一个键上
        doc = {"0x35f48f6c": "一句普通文本。"}
        self.assertEqual(
            M.expand("[ref:35F48F6C]", TABLE, "zh", "0x0000000c", doc=doc),
            "一句普通文本。")

    def test_ref_chain_caught_by_check_doc(self):
        doc = {"0x00000001": "[ref:0x00000002]",
               "0x00000002": "[ref:0x00000001]"}
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
    `group` 列同组全体成员的文本键（含本条自己），`,` 连接；单副本写自己那一个键。
    `clue` 的每一项两种形状都认：`<标签>:<正文>`（唯一已知类型是 `pun`，其余标签含退役的
    direction / feature 都只当关键词并记 warning；`_` 开头的自造标签静默）与裸写的
    `<正文>`；`,` 并列，每一项都要在谜面里出现；值里带 `,` `:` `+` 就整项加引号。
    """

    VERSE = "[riddle:answer=St. Augustine;group=00000001;clue=pun:August,north]He left for the north in August."

    def test_expands_to_nothing(self):
        self.assertEqual(M.expand(self.VERSE, TABLE, "zh"),
                         "He left for the north in August.")

    def test_does_not_count_as_name_usage(self):
        doc = {"0x00000001": self.VERSE}
        self.assertEqual(M.used_names(doc), set())

    def test_clue_missing_is_error(self):
        # 谜面里没有 south 这个词 → 这条谜面推不出这个答案
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=south,pun:August]"
                     "He went north in August.", TABLE, "zh")
        self.assertIn("south", str(ctx.exception))

    def test_no_clue_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;group=00000001]He went north.", TABLE, "zh")

    def test_clue_case_insensitive(self):
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=NORTH]He went north.",
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

    def test_bare_clue_scans_value(self):
        # 裸写认：没有标签，整项当正文片段匹配；多个片段用 `,` 并列
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=north]He went north.",
                     TABLE, "zh"),
            "He went north.")
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=north,August]"
                     "He went north in August.", TABLE, "zh"),
            "He went north in August.")
        # 裸写与带标签可以混在同一条 clue 里
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=pun:August,north]"
                     "He went north in August.", TABLE, "zh"),
            "He went north in August.")

    def test_bare_clue_missing_is_error(self):
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=south]He went north.",
                     TABLE, "zh")
        self.assertIn("south", str(ctx.exception))

    def test_plus_in_clue_is_gone(self):
        # `+` 并值退役：逗号并列已经能写，「两套写法同语义」只会让 --apply 判不清谁规范
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=north+August]"
                     "He went north in August.", TABLE, "zh")
        self.assertIn("+", str(ctx.exception))
        # 正文本身带 + 就把整项包起来
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=\"a+b\"]He wrote a+b.",
                     TABLE, "zh"),
            "He wrote a+b.")

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
        # `12:30` 不是标签（数字开头）；裸写又带冒号，要写就整项加引号
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=12:30]He left at 12:30.",
                     TABLE, "zh")
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=\"12:30\"]He left at 12:30.",
                     TABLE, "zh"),
            "He left at 12:30.")

    def test_empty_clue_value_is_error(self):
        # `clue=` 只写了类型、没写原词，等于没指到正文任何东西
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=pun:]He went north.",
                     TABLE, "zh")

    def test_unknown_answer_is_reported(self):
        doc = {"0x00000001": "[riddle:answer=Nowhere;group=00000001;clue=north]He went north."}
        problems = M.check_doc("zh", doc, entities={"St. Augustine": {}}, terms={})
        self.assertTrue(any("Nowhere" in p for p in problems), problems)

    def test_known_answer_passes(self):
        doc = {"0x00000001": self.VERSE}
        self.assertEqual(M.check_doc("zh", doc, entities={"St. Augustine": {}},
                                     terms={}), [])

    def test_direction_answer_needs_no_entity(self):
        # 方位谜底不进 entities.toml：它不是专名，也没有译名可登记
        doc = {"0x00000001": "[riddle:answer=southeast;group=00000001;clue=东南]望向东南，第三座便是。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_answer_counts_as_used_name(self):
        # 谜底那座城的名字在诗里被替换成 X，正文本来就没有它；
        # 按「死条目」报会误伤，故谜底算一次引用
        doc = {"0x00000001": "[riddle:answer=San Juan;group=00000001;clue=东南]X 在一座岛上，但望向东南。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}}, terms={})
        self.assertFalse(any("既没被引用" in p for p in problems), problems)

    def test_wrong_direction_answer_is_error(self):
        # 方位值必须真的是方位键；写错就是写错，不再靠「查不到就放过」蒙过去
        doc = {"0x00000001": "[riddle:answer=eastnorth;group=00000001;clue=东南]望向东南，第三座便是。"}
        problems = M.check_doc("zh", doc, entities={}, terms={})
        self.assertTrue(any("eastnorth" in p for p in problems), problems)

    def test_negative_direction_answer_is_a_key(self):
        # 「往东南去航是白费力气」只能排除东南，写 -southeast 不替原文补正向
        doc = {"0x00000001": "[riddle:answer=-southeast;group=00000001;clue=exclude:东南]往东南去航是白费力气。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_not_word_form_is_accepted(self):
        # 收两种写法：`-north`（规范）与 `not north`（空格）；解析期归一成 -north
        for spelling in ("not north", "-north"):
            doc = {"0x00000001": "[riddle:answer=%s;group=00000001;clue=北]北边什么也没有。"
                                 % spelling}
            self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [], spelling)

    def test_not_underscore_is_rejected(self):
        # 下划线写法不再接受：报错直接给两种合法写法
        for bad in ("not_north", "not_southeast"):
            with self.assertRaises(M.MarkError) as ctx:
                M.expand("[riddle:answer=%s;group=00000001;clue=北]北边什么也没有。" % bad,
                         TABLE, "zh")
            self.assertIn("-north", str(ctx.exception))

    def test_long_direction_abbrev_is_accepted(self):
        # 长方位允许缩写，解析期补全成 northeast 这类完整键；大小写不限
        for abbr, full in (("NE", "northeast"), ("SE", "southeast"),
                           ("SW", "southwest"), ("NW", "northwest"),
                           ("ne", "northeast"), ("nW", "northwest")):
            doc = {"0x00000001": "[riddle:answer=%s;group=00000001;clue=north]north 侧只有水。"
                                 % abbr}
            problems = M.check_doc("zh", doc, entities={}, terms={})
            self.assertEqual(problems, [], abbr)
            neg = {"0x00000001": "[riddle:answer=-%s;group=00000001;clue=north]north 侧只有水。"
                                % abbr}
            self.assertEqual(M.check_doc("zh", neg, entities={}, terms={}), [], abbr)

    def test_full_direction_word_any_case_is_accepted(self):
        # 八个方位词的值域是封闭的，大小写怎么写都认；连 `not East` 也认
        for spelling in ("East", "east", "EAST", "eaSt",
                         "-East", "not East", "NOT east"):
            doc = {"0x00000001": "[riddle:answer=%s;group=00000001;clue=north]north 侧只有水。"
                                 % spelling}
            self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [], spelling)

    def test_fullwidth_letters_are_rejected(self):
        # 只认半角 ASCII：全角字母肉眼和半角几乎一样，混进来必须当场点名
        for bad in ("ｅａｓｔ", "ＥＡＳＴ", "Ｅ", "nｏrth"):
            with self.assertRaises(M.MarkError) as ctx:
                M.expand("[riddle:answer=%s;group=00000001;clue=north]north 侧只有水。" % bad,
                         TABLE, "zh")
            self.assertIn("全角", str(ctx.exception))
        for bad in ("ｅａｓｔ", "NＯＲＴＨ"):
            with self.assertRaises(M.MarkError) as ctx:
                M.expand("[riddle:direction=%s;group=00000001;clue=north]north 侧只有水。" % bad,
                         TABLE, "zh")
            self.assertIn("全角", str(ctx.exception))
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:town=Ｖｅｒａ Ｃｒｕｚ;group=00000001;clue=north]北边。", TABLE, "zh")
        self.assertIn("全角", str(ctx.exception))

    def test_cardinal_single_letter_is_accepted(self):
        # 值域封闭，裸的 `n` 只能是 north（要指同名地名就写 town=）；否定形态同理
        for spelling in ("N", "n", "E", "s", "-N", "not w"):
            doc = {"0x00000001": "[riddle:answer=%s;group=00000001;clue=north]north 侧只有水。"
                                 % spelling}
            self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [], spelling)

    def test_cardinal_single_letter_under_direction_is_accepted(self):
        # 明写 direction= 时单字母一定是方向，N/E/S/W 及其否定形态都收
        for spelling, key in (("direction=N", "north"), ("direction=E", "east"),
                              ("direction=S", "south"), ("direction=W", "west"),
                              ("direction=-N", "not north"), ("direction=-E", "not east")):
            doc = {"0x00000001": "[riddle:%s;group=00000001;clue=north]north 侧只有水。"
                                 % spelling}
            problems = M.check_doc("zh", doc, entities={}, terms={})
            self.assertEqual(problems, [], spelling)

    def test_lowercase_cardinal_under_direction_is_accepted(self):
        # direction= 明写类型，单字母大小写不再要求；正向与否定都收
        for spelling in ("direction=n", "direction=-s", "direction=E", "direction=-w"):
            doc = {"0x00000001": "[riddle:%s;group=00000001;clue=north]north 侧只有水。"
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
        doc = {"0x00000001": "[riddle:town=vera cruz;group=00000001,00000002;clue=count:三座]三座城镇。",
               "0x00000002": "[riddle:town=VERA CRUZ;group=00000001,00000002;clue=count:三座]三座城镇。"}
        self.assertEqual(M.check_doc("zh", doc, entities=ents, terms={}), [])

    def test_bare_answer_matching_town_is_lenient(self):
        # answer= 也吃大小写/变音写法；判类型时同样先折平再查表
        doc = {"0x00000001": "[riddle:answer=veracruzx;group=00000001;clue=count:三座]三座城镇。"}
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("veracruzx" in p for p in problems), problems)
        doc2 = {"0x00000001": "[riddle:answer=east;group=00000001;clue=东]望向东边。"}
        self.assertEqual(M.check_doc("zh", doc2, entities={}, terms={}), [])

    def test_answer_field_may_be_omitted_with_type(self):
        # 省略 answer=：字段名直接写 town= / direction=
        doc = {"0x00000001": "[riddle:town=Vera Cruz;group=00000001;clue=count:三座]三座城镇，X 在最西。",
               "0x00000002": "[riddle:direction=SE;group=00000002;clue=count:三座]三座城镇，去东南。"}
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertEqual(problems, [])

    def test_typed_field_with_group_is_fine(self):
        # 省略 answer= 后 group/clue 照旧；group 列全组含自己，8 位不带 0x
        doc = {"0x00000001": "[riddle:town=Vera Cruz;group=00000001,00000002;clue=count:三座]三座城镇。",
               "0x00000002": "[riddle:town=Vera Cruz;group=00000001,00000002;clue=count:三座]三座城镇。"}
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
            M.expand("[riddle:answer=NE|northeast;group=00000001;clue=东]north 侧只有水。",
                     TABLE, "zh")
        self.assertIn("重复", str(ctx.exception))

    def test_not_word_form_under_field_is_accepted(self):
        doc = {"0x00000001": "[riddle:direction=not north;group=00000001;clue=北]"
                             "北边什么也没有。"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])

    def test_not_word_form_normalizes_to_same_candidate(self):
        # 归一的意义：两种写法不能把同一个谜底分裂成两串不同文本，写重就算重复
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=not north|-north;group=00000001;clue=北]北边什么也没有。",
                     TABLE, "zh")
        self.assertIn("重复", str(ctx.exception))

    def test_bad_not_shapes_are_errors(self):
        # 大小写放宽后，`not East` 是合法写法；剩下的都是真形状错
        for bad in ("not", "not-", "not- north", "not eastnorth"):
            with self.assertRaises(M.MarkError):
                M.expand("[riddle:answer=%s;group=00000001;clue=北]北边什么也没有。" % bad,
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
        ok = {"0x00000001": "[riddle:answer=kw;group=00000001;clue=黄金,港口]街道以黄金铺就，港口雄伟。"}
        problems = M.check_doc("zh", ok, entities={}, terms={})
        self.assertTrue(any("kw" in p for p in problems), problems)

    def test_comma_list_needs_every_value(self):
        # 逗号并列：每一项都要在谜面里，少一个就报错
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=白沙,丛林]"
                     "白沙与丛林。", TABLE, "zh"),
            "白沙与丛林。")
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=白沙,峡谷]"
                     "白沙与丛林。", TABLE, "zh")
        self.assertIn("峡谷", str(ctx.exception))

    def test_quoted_item_keeps_separators(self):
        # 项里带逗号/冒号只能整项加引号；引号里的逗号不再切项
        doc = ("He said \"Good, very good!\" at 12:30 to the captain."
               "He said \"Good, very good!\" at 12:30 to the captain.")
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;"
                     "clue=\"Good, very good!\", \"12:30\"]" + doc, TABLE, "zh"),
            doc)
        # 裸写里出现冒号要报错并提示加引号
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=12:30]" + doc,
                     TABLE, "zh")
        self.assertIn("引号", str(ctx.exception))

    def test_apostrophe_is_not_a_quote(self):
        # 项首不是引号位置就按普通字符：`I'm a captain` 里的撇号不开引号
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=I'm a captain, wine]"
                     "I'm a captain, and I drink wine.", TABLE, "zh"),
            "I'm a captain, and I drink wine.")

    def test_quotes_may_hold_the_other_quote(self):
        # 双引号里可以写单引号、单引号里可以写双引号；同种引号在里面就报错
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=\"l'abondance\"]"
                     "Il parle de l'abondance.", TABLE, "zh"),
            "Il parle de l'abondance.")
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue='say \"hi\"']"
                     "They say \"hi\" twice.", TABLE, "zh"),
            "They say \"hi\" twice.")
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=\"a \"b\" c\"]"
                     "a \"b\" c", TABLE, "zh")

    def test_backtick_is_a_third_quote(self):
        # 反引号也是外层引号：项里同时有单引号与双引号时用它包
        body = "He said it's \"good, very good\" twice."
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;"
                     "clue=`it's \"good, very good\"`]" + body, TABLE, "zh"),
            body)
        # 反引号里写反引号同样报错
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=`a `b`]a `b",
                     TABLE, "zh")
        # URL 也共用
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=August;"
                     "certainty=certain;source=url:`//example.com/it's`]He went north in August.",
                     TABLE, "zh"),
            "He went north in August.")

    def test_backslash_escapes_the_delimiter(self):
        # 引号里写同种引号要转义：\" "、\' '、\` `
        body = 'He said "hi" and left.'
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;"
                     "clue=\"said \\\"hi\\\"\"]" + body, TABLE, "zh"), body)
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue='it\\'s']"
                     "He says it's fine.", TABLE, "zh"), "He says it's fine.")
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=`a\\`b`]"
                     "Code a`b runs.", TABLE, "zh"), "Code a`b runs.")

    def test_backslash_backslash_is_one_backslash(self):
        # `\\` 表示正文里的一个反斜杠；其它 `\x` 原样保留（URL/路径里本来就可能带）
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=\"a\\\\b\"]"
                     "It reads a\\b here.", TABLE, "zh"), "It reads a\\b here.")

    def test_trailing_backslash_in_quotes_is_error(self):
        # 值本身以反斜杠结尾（没闭合）要明确报「反斜杠结尾」，不能只说引号没配平
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=\"a\\]"
                     "It reads ab.", TABLE, "zh")
        self.assertIn("反斜杠结尾", str(ctx.exception))

    def test_escaped_quote_keeps_item_split(self):
        # 转义后的引号不再当闭合引号，所以后面的逗号仍属于这一项
        body = 'He said "a, b" twice.'
        self.assertEqual(
            M.expand("[riddle:answer=St. Augustine;group=00000001;"
                     "clue=\"said \\\"a, b\\\"\"]" + body, TABLE, "zh"), body)

    def test_quoted_value_needs_pairing(self):
        for bad in ("\"白沙", "白沙\"", "\"\"", "白沙,"):
            with self.assertRaises(M.MarkError):
                M.expand("[riddle:answer=St. Augustine;group=00000001;clue=%s]白沙与丛林。" % bad,
                         TABLE, "zh")

    def test_alternative_names_both_count_as_used(self):
        # `|` 是「或」：两个候选都算被引用，也都要登记，否则死条目会误报其中一城
        doc = {"0x00000001": "[riddle:answer=San Juan|St. Juan;group=00000001;clue=岛,东南]"
                             "X 在一座岛上，望向东南。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}, "St. Juan": {}}, terms={})
        self.assertEqual(problems, [])

    def test_alternative_name_unregistered_is_reported(self):
        doc = {"0x00000001": "[riddle:answer=San Juan|Nowhere;group=00000001;clue=岛]X 在一座岛上。"}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}}, terms={})
        self.assertTrue(any("Nowhere" in p for p in problems), problems)

    def test_alternative_mixing_town_and_direction(self):
        # 候选可以是不同类型：一座城或「不是北边」，两种都能解释谜面。
        # 混类型只能写 answer=，让每个值各自推断；town=/direction= 里放不了别的类型。
        doc = {"0x00000001": "[riddle:answer=San Juan|-north;group=00000001;clue=北]"
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
            M.expand("[riddle:answer=St. Augustine;group=00000001;clue=north;note=x]He went north.",
                     TABLE, "zh")

    def test_duplicate_field_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=St. Augustine;answer=Havana;group=00000001;clue=north]"
                     "He went north.", TABLE, "zh")

    def test_empty_alternative_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=San Juan||St. Juan;group=00000001;clue=岛]X is on an island.",
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
        """整组的 group 段（含每个成员自己，升序，`,` 连接）。"""
        return ";group=%s" % ",".join(sorted(self._b(k) for k in keys))

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
            M.expand("[riddle:answer=Vera Cruz;group=%s,%s%s"
                     % (self._b(self.C), self._b(self.A), self.S), TABLE, "zh", self.A)
        self.assertIn("升序", str(ctx.exception))

    def test_plus_in_group_is_gone(self):
        # group 的并列符与 clue 统一为 `,`；`+` 在这里不再认，报键形错误
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=Vera Cruz;group=%s+%s%s"
                     % (self._b(self.A), self._b(self.B), self.S), TABLE, "zh", self.A)
        self.assertIn("8 位十六进制键", str(ctx.exception))

    def test_0x_prefix_is_accepted(self):
        # 引用键的写法宽容：`0x` 可省，写上也行，存进来的仍是去前缀的小写 8 位
        with self.assertRaises(M.MarkError):
            # 只改写法不改成员：单写 0x 形式仍然报「漏了本条自己」
            M.expand("[riddle:answer=Vera Cruz;group=0x%s;clue=三座]三座城镇。"
                     % self._b(self.B), TABLE, "zh", self.A)
        problems = M.check_doc(
            "zh", {self.A: "[riddle:answer=Vera Cruz;group=0x%s;clue=三座]三座城镇。"
                          % self._b(self.A)}, entities={"Vera Cruz": {}}, terms={})
        self.assertEqual(problems, [])

    def test_seven_digit_key_is_error(self):
        # 只放宽 0x，不放宽位数：少一位就认不出是哪个键
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=Vera Cruz;group=%s;clue=三座]三座城镇。"
                     % self._b(self.A)[:-1], TABLE, "zh", self.A)

    def test_bad_key_form_is_error(self):
        with self.assertRaises(M.MarkError):
            M.expand("[riddle:answer=Vera Cruz;group=%sZZZ%s" % (self._b(self.A), self.S),
                     TABLE, "zh", self.A)

    def test_empty_token_is_error(self):
        # `,` 两侧都要有键：多打一个逗号就是空项；全角「，」不认
        for bad in ("%s," % self._b(self.A), ",%s" % self._b(self.A),
                    "%s,,%s" % (self._b(self.A), self._b(self.B))):
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


def _riddle(tail, body="He went north in August."):
    """拼一条最小可用的诗谜标注：尾巴放 certainty / source。"""
    return ("[riddle:answer=St. Augustine;group=00000001;clue=north%s]%s"
            % ((";" + tail) if tail else "", body))


class TestCertaintyAndSource(unittest.TestCase):
    """certainty / source：取值域、引号、并列、URL 形状、manual 摘要、riddle 升序。"""

    def ok(self, tail):
        return M.expand(_riddle(tail), TABLE, "zh")

    def bad(self, tail, needle):
        with self.assertRaises(M.MarkError) as ctx:
            self.ok(tail)
        self.assertIn(needle, str(ctx.exception))
        return str(ctx.exception)

    def test_certainty_values(self):
        for v in M.ANS_CERTAINTY:
            if v in ("inferred", "either"):
                # 两者都自带附加规则（要 source / 要两个候选），单独测
                continue
            self.assertEqual(self.ok("certainty=" + v), "He went north in August.")
        self.assertEqual(self.ok("certainty=inferred;source=original-en&cargo"),
                         "He went north in August.")

    def test_certainty_unknown_value(self):
        self.bad("certainty=maybe", "certainty 只能写")

    def test_inferred_requires_source(self):
        self.bad("certainty=inferred", "必须写 source")

    def test_inferred_rejects_only_original(self):
        self.bad("certainty=inferred;source=original-en&original-fr", "不能只有 original-*")

    def test_inferred_accepts_other_evidence(self):
        self.assertEqual(self.ok("certainty=inferred;source=original-en&cargo"),
                         "He went north in August.")

    def test_original_and_retail(self):
        self.assertEqual(self.ok("certainty=certain;source=original-en"), "He went north in August.")
        self.assertEqual(self.ok("source=retail-de"), "He went north in August.")
        self.bad("source=retail-xx", "语言码")

    def test_quoted_url_both_quote_styles(self):
        self.assertEqual(self.ok("source=url:'https://steamcommunity.com/app/1/x'"),
                         "He went north in August.")
        self.assertEqual(self.ok('source=url:"https://example.com/a"'),
                         "He went north in August.")

    def test_quotes_may_hold_the_other_quote(self):
        # 同一套引号规则：双引号里可以写单引号，单引号里可以写双引号
        self.assertEqual(self.ok('source=url:"https://example.com/it\'s"'),
                         "He went north in August.")
        # 同种引号在里面就没法配平，报错
        self.bad('source=url:"https://example.com/a"b"', "引号")

    def test_url_unquoted_rejected(self):
        self.bad("source=url:https://example.com/a", "要用引号包起来")

    def test_https_scheme_may_be_omitted(self):
        self.assertEqual(self.ok("source=url:'//steamcommunity.com/app/1/x'"),
                         "He went north in August.")

    def test_http_scheme_may_not_be_omitted(self):
        # `//` 只能代表 https；裸写域名（没路径）直接报错
        self.assertEqual(self.ok("source=url:'//example.com/a'"), "He went north in August.")
        self.bad("source=url:'https://example.com'", "只写了域名")

    def test_any_domain_accepted(self):
        # 域名不再是分类依据：steam / 论坛 / wiki 都走 url
        for host in ("steamcommunity.com/app/1/x", "forum.example.org/thread/2",
                     "wiki.example.net/page"):
            self.assertEqual(self.ok("source=url:'https://%s'" % host),
                             "He went north in August.")

    def test_steam_forum_categories_removed(self):
        self.bad("source=steam:'https://steamcommunity.com/app/1/x'", "没有类别")
        self.bad("source=forum:'https://example.com/a'", "没有类别")

    def test_bare_url_item_equals_url(self):
        self.assertEqual(self.ok("source='https://example.com/a?b=1'"), "He went north in August.")

    def test_semicolon_inside_quotes_is_rejected(self):
        # 引号内一律按字面，但 `;` 例外：它必须写 %3B，否则字段边界无从判断
        self.bad("source=url:'https://example.com/a;jsessionid=1'", "`;`")

    def test_ampersand_and_plus_are_equivalent(self):
        self.assertEqual(self.ok("source=original-en&original-fr"), "He went north in August.")
        self.assertEqual(self.ok("source=original-en+original-fr"), "He went north in August.")
        self.bad("source=original-en+", "空项")

    def test_ampersand_inside_quotes_kept(self):
        self.assertEqual(self.ok("source='https://example.com/a?x=1&y=2'"),
                         "He went north in August.")

    def test_curly_quote_rejected(self):
        self.bad("source=\u201chttps://example.com/a\u201d", "弯引号")

    def test_quote_unbalanced(self):
        self.bad("source='https://example.com/a", "没闭合")

    def test_riddle_keys_must_ascend(self):
        self.bad("source=riddle:00000002,00000001", "升序")
        self.assertEqual(self.ok("source=riddle:00000001,00000002"), "He went north in August.")
        self.bad("source=riddle:00000001,00000001", "重复")

    def test_riddle_keys_use_comma(self):
        # `+` 在 riddle 的键列表里也退役：整段会被切成两个并列来源，后一个不是类别
        self.bad("source=riddle:00000001+00000002", "没有类别")
        self.bad("source=riddle:00000001,", "`,` 两侧都要写键")

    def test_manual_path_and_digest(self):
        path = os.path.join("glossary", "verse_ans.toml")
        import hashlib
        with open(os.path.join(M.ROOT, path), "rb") as fh:
            dg = hashlib.sha256(fh.read()).hexdigest()[:12]
        self.assertEqual(self.ok("source=manual:%s@sha256-%s#p12" % (path, dg)),
                         "He went north in August.")
        self.bad("source=manual:%s@sha256-%s" % (path, "0" * 12), "对不上")
        self.bad("source=manual:/etc/passwd@sha256-%s" % dg, "相对路径")
        self.bad("source=manual:../x.toml@sha256-%s" % dg, "跳出仓库")

    def test_manual_anchor_is_a_real_heading(self):
        # 锚点写真实小节标题：三种引号都收，标题必须逐字存在于目标文件里
        import hashlib
        path = "docs/_src/pr2-treasure-hunts.md"
        with open(os.path.join(M.ROOT, path), "rb") as fh:
            dg = hashlib.sha256(fh.read()).hexdigest()[:12]
        for q in ("`", "'", '"'):
            self.assertEqual(
                self.ok("source=manual:%s@sha256-%s#%sHunt Text 12%s" % (path, dg, q, q)),
                "He went north in August.")
        self.bad("source=manual:%s@sha256-%s#`Hunt Text 99`" % (path, dg), "不在")
        self.bad("source=manual:%s@sha256-%s#ch12" % (path, dg), "已退役")

    def test_url_accepts_three_quotes(self):
        for q in ("'", '"', "`"):
            self.assertEqual(
                self.ok("source=url:%shttps://example.com/a%s" % (q, q)),
                "He went north in August.")
            self.assertEqual(self.ok("source=%shttps://example.com/a%s" % (q, q)),
                             "He went north in August.")
        # 外层单引号里带撇号：转义成 \'
        self.assertEqual(self.ok("source='https://example.com/it\\'s'"),
                         "He went north in August.")

    def test_authored_is_a_bare_category(self):
        self.assertEqual(self.ok("source=original-en&authored"), "He went north in August.")
        self.bad("source=authored:00000001", "不带指向")
        self.bad("source=local", "没有类别")

    def test_unknown_source_category(self):
        self.bad("source=hearsay", "没有类别")

    # ---- either：两个地点都成立（answer=A|B），不是「没定」 ----

    EITHER_BODY = "He went north in August."

    def either_mark(self, answer="St. Augustine|Havana", tail="certainty=either;source=original-en&cargo"):
        return ("[riddle:answer=%s;group=00000001;clue=north;%s]%s"
                % (answer, tail, self.EITHER_BODY))

    def test_either_with_two_candidates(self):
        self.assertEqual(M.expand(self.either_mark(), TABLE, "zh"), self.EITHER_BODY)

    def test_either_needs_two_candidates(self):
        with self.assertRaises(M.MarkError) as ctx:
            M.expand(self.either_mark(answer="St. Augustine"), TABLE, "zh")
        self.assertIn("两个以上候选", str(ctx.exception))

    def test_either_needs_source(self):
        with self.assertRaises(M.MarkError) as ctx:
            M.expand(self.either_mark(tail="certainty=either"), TABLE, "zh")
        self.assertIn("必须写 source", str(ctx.exception))

    def test_multi_candidate_without_either_is_allowed(self):
        # `|` 也可能是同一座城的异写（San Juan|St. Juan），机器分不清，所以不设禁令
        self.assertEqual(
            M.expand(self.either_mark(tail="certainty=inferred;source=original-en&cargo"),
                     TABLE, "zh"), self.EITHER_BODY)

    def test_single_candidate_without_either_is_fine(self):
        self.assertEqual(self.ok("certainty=certain"), self.EITHER_BODY)


class TestRiddleStricter(unittest.TestCase):
    """一条文本只许一个 riddle；certainty/source 在构建前复核档必写；local 是自写谜面。"""

    H = "0x00000001"
    ONE = "[riddle:answer=San Juan;group=00000001;clue=island;level=town]An island."
    TWO = ("[riddle:answer=San Juan;group=00000001;clue=island;level=town;certainty=certain"
           ";source=original-en&authored]An island.")

    @staticmethod
    def _ent():
        return {"San Juan": {}}

    def test_two_riddle_marks_in_one_text(self):
        doc = {self.H: self.ONE + " [riddle:answer=Havana;group=00000001;clue=gold]Gold."}
        problems = M.check_doc("zh", doc, entities={"San Juan": {}, "Havana": {}}, terms={})
        self.assertTrue(any("只能写一个" in p for p in problems), problems)

    def test_expand_rejects_two_marks(self):
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=San Juan;group=00000001;clue=island;level=town]"
                     "An island. "
                     "[riddle:answer=San Juan;group=00000001;clue=island;level=town]"
                     "An island.", TABLE, "zh")
        self.assertIn("只能写一个", str(ctx.exception))

    def test_meta_required_only_in_strict_mode(self):
        bare = "[riddle:answer=San Juan;group=00000001;clue=island]An island."
        doc = {self.H: bare}
        self.assertEqual(M.check_doc("zh", doc, entities=self._ent(), terms={}), [])
        problems = M.check_doc("zh", doc, entities=self._ent(), terms={},
                               require_ans_meta=True)
        self.assertTrue(any("certainty" in p for p in problems), problems)
        self.assertTrue(any("source" in p for p in problems), problems)
        self.assertTrue(any("level" in p for p in problems), problems)

    def test_meta_complete_passes_strict(self):
        self.assertEqual(
            M.check_doc("zh", {self.H: self.TWO}, entities=self._ent(), terms={},
                        require_ans_meta=True), [])

    def test_inferred_cannot_be_only_original_or_authored(self):
        for tail in ("source=original-en&authored", "source=authored"):
            with self.assertRaises(M.MarkError) as ctx:
                M.expand("[riddle:answer=San Juan;group=00000001;clue=island;level=town"
                         ";certainty=inferred;%s]An island." % tail, TABLE, "zh")
            self.assertIn("没有外部依据", str(ctx.exception))

    # ---- level：分级由谜底算出来，声明只能跟它一致 ----

    def test_level_direction_ok(self):
        text = ("[riddle:direction=north;group=00000001;clue=north;level=direction"
                ";certainty=certain;source=original-en]He went north.")
        self.assertEqual(M.check_doc("zh", {self.H: text}, entities=self._ent(), terms={},
                                     require_ans_meta=True), [])

    def test_level_mixed_needs_both_kinds(self):
        text = ("[riddle:answer=San Juan|-north;group=00000001;clue=island,north;level=mixed"
                ";certainty=either;source=original-en]An island, then north.")
        self.assertEqual(M.check_doc("zh", {self.H: text}, entities=self._ent(), terms={},
                                     require_ans_meta=True), [])

    def test_level_must_match_answers(self):
        text = ("[riddle:answer=San Juan;group=00000001;clue=island;level=direction"
                ";certainty=certain;source=original-en]An island.")
        problems = M.check_doc("zh", {self.H: text}, entities=self._ent(), terms={},
                               require_ans_meta=True)
        self.assertTrue(any("level 写的是 direction" in p for p in problems), problems)

    def test_level_only_accepts_three_values(self):
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=San Juan;group=00000001;clue=island;level=hard]"
                     "An island.", TABLE, "zh")
        self.assertIn("level 只能写", str(ctx.exception))

    # ---- `+` 在 clue 里就是正文，不是并列 ----

    def test_plus_in_bare_clue_is_literal(self):
        self.assertEqual(
            M.expand("[riddle:answer=San Juan;group=00000001;clue=a+b]Meet at a+b.",
                     TABLE, "zh"), "Meet at a+b.")
        # 引号里也一样，不需要为加号加引号
        self.assertEqual(
            M.expand("[riddle:answer=San Juan;group=00000001;clue=\"a+b\"]Meet at a+b.",
                     TABLE, "zh"), "Meet at a+b.")

    def test_plus_not_in_verse_points_to_comma(self):
        with self.assertRaises(M.MarkError) as ctx:
            M.expand("[riddle:answer=San Juan;group=00000001;clue=island+gold]An island.",
                     TABLE, "zh")
        self.assertIn("用半角 `,`", str(ctx.exception))


class TestRefCoveredRiddle(unittest.TestCase):
    """同组逐字相同的诗谜副本写成整行 `[riddle:copy=最小键]`：身份随目标键继承。

    副本没有自己的谜面，所以不该、也不需要再抄一遍完整 `[riddle:…]`；但「同组每条都要标」
    与「同文副本必须同组」两条判据对它照样成立。`ref` 与 `copy` 互斥：诗谜行只许 copy，不含谜的同文才用 ref（见 09 卷第一百一十六节）。
    """

    A = "0x00000001"
    B = "0x00000002"

    def test_copy_inherits_riddle(self):
        doc = {self.A: "[riddle:answer=Vera Cruz;group=00000001,00000002;clue=三座]"
                       "三座城镇，X 在最西。",
               self.B: "[riddle:copy=0x00000001]"}
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_copy_without_0x_is_the_same_row(self):
        doc = {self.A: "[riddle:answer=Vera Cruz;group=00000001,00000002;clue=三座]"
                       "三座城镇，X 在最西。",
               self.B: "[riddle:copy=00000001]"}
        self.assertEqual(M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={}), [])

    def test_copy_cannot_dodge_group_membership(self):
        # group 只列自己、副本靠 copy 混过去：集合比对仍要把副本算进去
        doc = {self.A: "[riddle:answer=Vera Cruz;group=00000001;clue=三座]"
                       "三座城镇，X 在最西。",
               self.B: "[riddle:copy=0x00000001]"}
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("没列成同一组" in p for p in problems), problems)

    def test_ref_on_riddle_row_is_refused(self):
        # 诗谜副本写 ref：身份会隐式继承，语义与 copy 混在一起，直接指出来改写法
        doc = {self.A: "[riddle:answer=Vera Cruz;group=00000001,00000002;clue=三座]"
                       "三座城镇，X 在最西。",
               self.B: "[ref:0x00000001]"}
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("riddle:copy=" in p for p in problems), problems)

    def test_copy_must_be_alone(self):
        doc = {self.A: "[riddle:answer=Vera Cruz;group=00000001;clue=三座]三座城镇，X 在最西。",
               self.B: "[riddle:copy=0x00000001;clue=三座]"}
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("要独占整条" in p for p in problems), problems)

    def test_copy_with_text_is_refused(self):
        doc = {self.A: "[riddle:answer=Vera Cruz;group=00000001,00000002;clue=三座]"
                       "三座城镇，X 在最西。",
               self.B: "[riddle:copy=0x00000001]多写的正文"}
        problems = M.check_doc("zh", doc, entities={"Vera Cruz": {}}, terms={})
        self.assertTrue(any("要独占整行" in p for p in problems), problems)

    def test_copy_of_plain_text_is_refused(self):
        doc = {"0x00000001": "一句普通文本。", "0x00000002": "[riddle:copy=0x00000001]"}
        problems = M.check_doc("zh", doc, entities={}, terms={})
        self.assertTrue(any("没有 riddle 标注" in p for p in problems), problems)

    def test_ref_to_plain_text_is_not_a_riddle(self):
        # 目标是普通文本：ref 只是同句引用，不该被当成谜面成员
        doc = {"0x00000001": "一句普通文本。", "0x00000002": "[ref:0x00000001]"}
        self.assertEqual(M.check_doc("zh", doc, entities={}, terms={}), [])


if __name__ == "__main__":
    unittest.main()
