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


if __name__ == "__main__":
    unittest.main()
