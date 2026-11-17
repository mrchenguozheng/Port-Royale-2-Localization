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
        for g in self.groups:
            texts = {self.en[k] for k in g["ids"]}
            self.assertEqual(len(texts), 1, g["ids"])

    def test_filled_groups_have_usable_clues(self):
        for g in self.groups:
            ans = (g.get("ans") or "").strip()
            if not ans:
                continue
            for lang in LANGS:
                clues = (g["clues"].get(lang) or "").strip()
                self.assertTrue(clues, (ans, lang))
                self.assertNotIn("，", clues, (ans, lang))
                text = self.rows[lang][g["ids"][0]].casefold()
                for c in [x.strip() for x in clues.split(",")]:
                    self.assertIn(c.casefold(), text, (ans, lang, c))

    def test_kinds_are_optional_but_aligned_when_given(self):
        # kinds 是必填的译者标签（缺了就是裸写）：必须与该语线索一条对一条；
        # 取值要么是七个已知类型，要么是 `_` 开头的自造标签
        ok = ("pun", "direction", "count", "feature", "produce", "history", "exclude")
        for g in self.groups:
            kinds = g.get("kinds") or {}
            for lang, arr in kinds.items():
                self.assertIn(lang, LANGS, g["ids"])
                clues = [x for x in (g["clues"].get(lang) or "").split(",") if x.strip()]
                self.assertEqual(len(arr), len(clues), (g["ids"], lang))
                for kind in arr:
                    self.assertTrue(kind in ok or kind.startswith("_"),
                                    (g["ids"], lang, kind))


class TestClueText(unittest.TestCase):
    """kinds 可选：没给就只拼关键词，给了就逐条套类型，条数不等即停。"""

    def test_bare_is_error(self):
        # 不给 kinds 就是裸写，不许
        with self.assertRaises(SystemExit):
            VA.clue_text(["四座", "东"], [], "zh")

    def test_empty_kind_is_error(self):
        with self.assertRaises(SystemExit):
            VA.clue_text(["四座"], [""], "zh")

    def test_typed_items(self):
        # 相邻同类型并成一项：count:四座+第三座
        self.assertEqual(VA.clue_text(["四座", "第三座", "东"],
                                      ["count", "count", "direction"], "zh"),
                         "count:四座+第三座,direction:东")

    def test_same_kind_split_by_other_kind(self):
        # 同类型不连续就不合并，只并相邻的
        self.assertEqual(VA.clue_text(["四座", "东", "五座"],
                                      ["count", "direction", "count"], "zh"),
                         "count:四座,direction:东,count:五座")

    def test_count_mismatch_stops(self):
        with self.assertRaises(SystemExit):
            VA.clue_text(["四座", "东"], ["count"], "zh")

    def test_unknown_kind_is_passed_through(self):
        # 写错/自造的类型不拦：展开侧对未知前缀只扫冒号后的正文
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
            self.key("[riddle:answer=Vera Cruz;group=0x00000002+0x00000001;clue=count:三座]"),
            self.key("[riddle:answer=Vera Cruz;group=00000001+00000002;clue=count:三座]"))

    def test_different_clue_still_differs(self):
        self.assertNotEqual(
            self.key("[riddle:answer=Vera Cruz;group=00000001;clue=count:三座]"),
            self.key("[riddle:answer=Vera Cruz;group=00000001;clue=count:四座]"))

    def test_no_mark_gives_none(self):
        self.assertIsNone(self.key("三座城镇，X 在最西。"))


if __name__ == "__main__":
    unittest.main()
