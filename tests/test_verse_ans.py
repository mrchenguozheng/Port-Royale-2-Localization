# -*- coding: utf-8 -*-
"""诗谜谜底队列的不变式：分组覆盖、同组同文、已填的线索六语齐备且真在谜面里。

工具是 src/tools/text/verse_ans.py，队列是 glossary/verse_ans.toml。
这里读真实数据，属于全仓不变式：队列填错（漏线索、线索写了个谜面里没有的词）在
check.py 就会红，而不是等构建到一半才报。
"""
import os
import sys
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))
import toml_io
import terms_check as TC
import verse_ans as VA

LANGS = ("zh", "de", "es", "fr", "ja", "ru")
QUEUE = os.path.join(ROOT, "glossary", "verse_ans.toml")


def load():
    with open(QUEUE, "rb") as f:
        return tomllib.load(f)["group"]


class TestVerseQueue(unittest.TestCase):
    def setUp(self):
        self.en, _o = toml_io.read_doc(
            os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml"))
        self.groups = load()
        self.rows = {l: toml_io.read_doc(
            os.path.join(ROOT, "src", "translations", "%s.toml" % l))[0]
            for l in LANGS}

    def test_queue_covers_every_verse_row_exactly_once(self):
        groups, _ignore, verse = TC.load_terms()
        want = TC.verse_ids(verse, self.en)
        got = [k for g in self.groups for k in g["ids"]]
        self.assertEqual(len(got), len(set(got)))
        self.assertEqual(set(got), want)

    def test_group_is_one_same_verse(self):
        # 尾空白不算区别：0x35f48fdd 比 0x35f48fde 只多一个尾空格（09 卷第一百一十三节
        # 已按同一条计），组里两条仍是同一首谜面。
        for g in self.groups:
            texts = {self.en[k].strip() for k in g["ids"]}
            self.assertEqual(len(texts), 1, g["ids"])

    def test_filled_groups_have_usable_clues(self):
        for g in self.groups:
            ans = (g.get("ans") or "").strip()
            if not ans:
                continue
            for lang in LANGS:
                clues = (g["clues"].get(lang) or "").strip()
                self.assertTrue(clues, (ans, lang))
                text = self.rows[lang][g["ids"][0]].casefold()
                for c in VA.split_clues(clues, lang):
                    self.assertIn(c.casefold(), text, (ans, lang, c))

    def test_kinds_are_optional_but_aligned_when_given(self):
        # kinds 可选：整组不给 = 全裸写；给了就必须与该语线索一条对一条；
        # 取值要么是唯一保留的已知类型 pun，要么是 `_` 开头的自造标签，空串表示裸写
        ok = ("pun",)
        for g in self.groups:
            kinds = g.get("kinds") or {}
            for lang, arr in kinds.items():
                self.assertIn(lang, LANGS, g["ids"])
                clues = VA.split_clues(g["clues"].get(lang) or "", lang)
                self.assertEqual(len(arr), len(clues), (g["ids"], lang))
                for kind in arr:
                    self.assertTrue(kind == "" or kind in ok or kind.startswith("_"),
                                    (g["ids"], lang, kind))


class TestClueText(unittest.TestCase):
    """kinds 可选：整组不给就全裸写，给了就按位贴标签，条数不等即停。"""

    def test_bare_is_allowed(self):
        # 不给 kinds 就整组裸写：只给正文词，用 `,` 并列
        self.assertEqual(VA.clue_text(["四座", "东"], [], "zh"), "四座,东")

    def test_empty_kind_is_bare(self):
        # 逐位对齐时留空串＝这条不贴标签，输出裸写
        self.assertEqual(VA.clue_text(["四座"], [""], "zh"), "四座")

    def test_tag_repeats_per_item(self):
        # 一项一段：同标签不合并（`+` 并值已退役），标签逐条重复
        self.assertEqual(VA.clue_text(["August", "Holy", "北"],
                                      ["pun", "pun", ""], "zh"),
                         "pun:August,pun:Holy,北")

    def test_quote_only_when_needed(self):
        # 带逗号/冒号/加号的值才加引号；撇号或中段双引号裸写仍能读（quote 只在项首开）
        self.assertEqual(VA.clue_text(["12:30", "I'm a captain", "a+b"], [], "en"),
                         "\"12:30\",I'm a captain,\"a+b\"")
        self.assertEqual(VA.clue_text(['say "hi"'], [], "en"), 'say "hi"')
        # 值里有双引号又必须加引号时换单引号外层；再不行换反引号；三种都占满就转义
        self.assertEqual(VA.clue_text(['say "hi", twice'], [], "en"), "'say \"hi\", twice'")
        self.assertEqual(VA.clue_text(['a,b"c\'d'], [], "en"), '`a,b"c\'d`')
        self.assertEqual(VA.clue_text(['a,b"c\'d`e'], [], "en"), '"a,b\\"c\'d`e"')

    def test_count_mismatch_stops(self):
        with self.assertRaises(SystemExit):
            VA.clue_text(["四座", "东"], ["pun"], "zh")

    def test_unknown_kind_is_passed_through(self):
        # 写错/自造的类型不拦：展开侧对未知前缀只扫冒号后的正文（并记 warning）
        self.assertEqual(VA.clue_text(["四座"], ["vibe"], "zh"), "vibe:四座")
        self.assertEqual(VA.clue_text(["四座"], ["_hello"], "zh"), "_hello:四座")


class TestMarkKey(unittest.TestCase):
    """--apply 的「已标成同值就跳过」判据要能容忍不规范写法。"""

    ENT = {"vera cruz": ["Vera Cruz"], "san juan": ["San Juan"]}

    def key(self, text):
        return VA.mark_key(text, self.ENT)

    def test_plain_equals_canonical(self):
        self.assertEqual(
            self.key("[riddle:answer=Vera Cruz;group=00000001;clue=count:三座]"),
            self.key("[riddle:answer=Vera Cruz;group=00000001;clue=count:三座]"))

    def test_case_and_diacritics_are_tolerated(self):
        self.assertEqual(
            self.key("[riddle:answer=vera cruz;group=00000001;clue=count:三座] 三座城镇。"),
            self.key("[riddle:answer=Vera Cruz;group=00000001;clue=count:三座] 三座城镇。"))

    def test_direction_spellings_are_tolerated(self):
        self.assertEqual(
            self.key("[riddle:answer=not north;group=00000001;clue=count:三座]"),
            self.key("[riddle:answer=-north;group=00000001;clue=count:三座]"))

    def test_answer_and_town_are_interchangeable(self):
        self.assertEqual(
            self.key("[riddle:town=Vera Cruz;group=00000001;clue=count:三座]"),
            self.key("[riddle:answer=Vera Cruz;group=00000001;clue=count:三座]"))

    def test_group_prefix_and_order_are_tolerated(self):
        self.assertEqual(
            self.key("[riddle:answer=Vera Cruz;group=0x00000002,0x00000001;clue=count:三座]"),
            self.key("[riddle:answer=Vera Cruz;group=00000001,00000002;clue=count:三座]"))

    def test_old_group_plus_is_no_longer_normalized(self):
        # 收紧：`+` 不再被当成 `,` 的同值写法，旧写法应当报冲突而不是悄悄规范化
        self.assertNotEqual(
            self.key("[riddle:answer=Vera Cruz;group=00000001+00000002;clue=count:三座]"),
            self.key("[riddle:answer=Vera Cruz;group=00000001,00000002;clue=count:三座]"))

    def test_different_clue_still_differs(self):
        self.assertNotEqual(
            self.key("[riddle:answer=Vera Cruz;group=00000001;clue=count:三座]"),
            self.key("[riddle:answer=Vera Cruz;group=00000001;clue=count:四座]"))

    def test_tail_fields_are_kept(self):
        # certainty / source 不在队列里：重写标注时必须原样带回去
        wanted = "[riddle:answer=Vera Cruz;group=00000001;clue=count:三座]"
        old = ("[riddle:answer=vera cruz;group=00000001;clue=count:三座;"
               "certainty=certain;source=original-en] 三座城镇。")
        self.assertEqual(
            VA.with_tail(wanted, old),
            "[riddle:answer=Vera Cruz;group=00000001;clue=count:三座;"
            "certainty=certain;source=original-en]")

    def test_tail_fields_absent_means_plain_wanted(self):
        wanted = "[riddle:answer=Vera Cruz;group=00000001;clue=count:三座]"
        self.assertEqual(VA.with_tail(wanted, "三座城镇。"), wanted)
        self.assertEqual(VA.with_tail(wanted, wanted), wanted)

    def test_tail_fields_order_preserved(self):
        wanted = "[riddle:answer=Vera Cruz;group=00000001;clue=count:三座]"
        old = ("[riddle:answer=Vera Cruz;group=00000001;clue=count:三座;"
               "source=original-en;certainty=certain]")
        self.assertEqual(
            VA.with_tail(wanted, old),
            "[riddle:answer=Vera Cruz;group=00000001;clue=count:三座;"
            "source=original-en;certainty=certain]")

    def test_no_mark_gives_none(self):
        self.assertIsNone(self.key("三座城镇，X 在最西。"))


if __name__ == "__main__":
    unittest.main()
