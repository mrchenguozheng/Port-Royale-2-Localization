# -*- coding: utf-8 -*-
"""terms_check 的三级判定：词形差不该报成错，真错译不该被词根放行。

除最后一条「全仓不变式」外只测纯函数，不读真实术语表——真实表的组定义会随项目变。
"""

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))

import terms_check as TC      # noqa: E402


class TestStemPrefix(unittest.TestCase):
    def test_length_floor_and_ceiling(self):
        # 4 是下限：5 字词取 4，11 字以上封顶 8
        self.assertEqual(TC.stem_prefix("Pirat"), "Pira")
        self.assertEqual(TC.stem_prefix("Spanien"), "Span")
        self.assertEqual(TC.stem_prefix("Handelsroute"), "Handelsr")
        self.assertEqual(TC.stem_prefix("Weltmarktordnung"), "Weltmark")

    def test_too_short_returns_none(self):
        self.assertIsNone(TC.stem_prefix("Rot"))
        self.assertIsNone(TC.stem_prefix("猫"))

    def test_multiphrase_uses_last_word(self):
        self.assertEqual(TC.stem_prefix("Ruta comercial"), "comerc")

    def test_non_alpha_returns_none(self):
        self.assertIsNone(TC.stem_prefix("A1"))


class TestJudge(unittest.TestCase):
    def stems(self, want):
        s = TC.stem_prefix(want)
        return [TC.compile_stem(s)] if s else []

    def test_exact_wins(self):
        lvl, _ = TC.judge("Der Matrose %2", ["Matrose"], self.stems("Matrose"))
        self.assertEqual(lvl, "EXACT")

    def test_base_as_substring_is_exact(self):
        # 「Matrose」本身就嵌在「Matrosen」里，这类屈折直接算通过，不漏报
        lvl, _ = TC.judge("die Matrosen an Bord", ["Matrose"], self.stems("Matrose"))
        self.assertEqual(lvl, "EXACT")

    def test_suffix_changed_form_is_morph_not_error(self):
        # Marino → Marineros：词面不再是子串（中间插了 er），靠词根认出来
        lvl, frag = TC.judge("los Marineros:", ["Marino"], self.stems("Marino"))
        self.assertEqual(lvl, "MORPH")
        self.assertTrue(frag.startswith("Marin"))

    def test_accent_and_case_are_not_drift(self):
        # Eglise / église、Café / café 是同一个词，只是重音与句首位置不同
        lvl, _ = TC.judge("une église au bord", ["Eglise"], self.stems("Eglise"))
        self.assertEqual(lvl, "EXACT")

    def test_article_on_baseline_is_optional(self):
        # 基准形带着标签上的冠词，句子里反而不带
        ok = ["l'Angleterre"] + TC.article_variants("l'Angleterre")
        lvl, _ = TC.judge("en Angleterre", ok, [])
        self.assertEqual(lvl, "EXACT")

    def test_adjective_of_proper_noun_is_morph(self):
        # Spanien 在句里作形容词 spanischen，首字母小写也要认
        lvl, _ = TC.judge("das spanischen Weltreich", ["Spanien"], self.stems("Spanien"))
        self.assertEqual(lvl, "MORPH")

    def test_other_word_is_missing(self):
        lvl, _ = TC.judge("Die Seeleute jubelten", ["Matrose"], self.stems("Matrose"))
        self.assertEqual(lvl, "MISSING")

    def test_cjk_has_no_stem(self):
        # 汉字不取词根：build_rules 对 zh/ja 不生成 stem，de 才生成
        en = {"0x1": "Router", "0x2": "Route"}
        doc = {"0x1": "贸易路线", "0x2": "贸易路线"}
        groups = [{"name": "路线", "ids": ["0x1"]}]
        self.assertEqual(TC.build_rules(groups, en, doc, "zh")[0][2], [])
        self.assertTrue(TC.build_rules(groups, en, doc, "de")[0][2])
        lvl, _ = TC.judge("贸易航线", ["贸易路线"], [])
        self.assertEqual(lvl, "MISSING")

    def test_whitespace_insensitive_exact(self):
        lvl, _ = TC.judge("护 送 贸 易 路 线", ["贸易路线"], [])
        self.assertEqual(lvl, "EXACT")


class TestNearForms(unittest.TestCase):
    def test_latin_requires_shared_prefix(self):
        # Steuern 只是首字母相同，不能被当成 Spanien 的疑似写法
        self.assertEqual(TC.near_forms("Steuern und Seeleute", "Spanien"), [])

    def test_latin_similar_word_is_reported(self):
        # 窗口长度等于基准形长度，所以给出的是 spanisc 这类片段，共享前 5 个字母
        got = TC.near_forms("die spanischen Kolonien", "Spanien")
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].startswith("spani"))

    def test_cjk_single_char_shared_is_enough(self):
        self.assertEqual(TC.near_forms("这条贸易航线很长", "贸易路线"), ["贸易航线"])

    def test_exact_base_is_not_a_near_form(self):
        self.assertEqual(TC.near_forms("贸易路线", "贸易路线"), [])


class TestAltScope(unittest.TestCase):
    def test_language_scoped_alt(self):
        group = {"alt": {"0x1": {"de": ["Pirat"], "*": ["Seeräuber"]}}}
        self.assertEqual(TC.alt_for(group, "0x1", "de"), ["Pirat", "Seeräuber"])
        self.assertEqual(TC.alt_for(group, "0x1", "ru"), ["Seeräuber"])

    def test_legacy_flat_alt_still_works(self):
        group = {"alt": {"0x1": ["载入", "读取"]}}
        self.assertEqual(TC.alt_for(group, "0x1", "zh"), ["载入", "读取"])


class TestNameRows(unittest.TestCase):
    """术语表自己登记的那一行是「名字行」：里面的词是名字的一部分，不按别的组查。"""

    GROUPS = [{"name": "货物", "ids": ["0x1"]},
              {"name": "建筑", "ids": ["0x2"]}]

    def test_building_name_row_is_not_checked_against_goods(self):
        en = {"0x1": "Fruit", "0x2": "Fruit farm"}
        doc = {"0x1": "Obst", "0x2": "Obstfarm"}
        res = TC.check_lang("de", self.GROUPS, en, doc)
        self.assertEqual([x["id"] for x in res["missing"]], [])
        self.assertEqual(res["morph"], [])

    def test_prose_row_is_still_checked(self):
        en = {"0x1": "Fruit", "0x2": "Fruit farm", "0x3": "We sell Fruit here."}
        doc = {"0x1": "Obst", "0x2": "Obstfarm", "0x3": "Wir verkaufen Holz."}
        res = TC.check_lang("de", self.GROUPS, en, doc)
        self.assertEqual([x["id"] for x in res["missing"]], ["0x3"])


class TestVerseSkip(unittest.TestCase):
    def test_range_expands_to_ids_inside_it(self):
        en = {"0x0f": "", "0x10": "", "0x12": "", "0x13": ""}
        self.assertEqual(TC.verse_ids([["0x10", "0x12"]], en),
                         {"0x10", "0x12"})

    def test_empty_verse_list_skips_nothing(self):
        self.assertEqual(TC.verse_ids([], {"0x10": ""}), set())


class TestVerseHasNoMarks(unittest.TestCase):
    """诗谜整片不挂标注（读真实数据，属于全仓不变式）。"""

    def test_no_marker_in_any_language(self):
        import toml_io
        en, _o = toml_io.read_doc(
            os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml"))
        _g, _ig, verse = TC.load_terms()
        vids = TC.verse_ids(verse, en)
        self.assertTrue(vids, "术语表里没有 verse 区间")
        bad = []
        for lang in ("zh", "de", "es", "fr", "ja", "ru"):
            doc, _od = toml_io.read_doc(
                os.path.join(ROOT, "src", "translations", "%s.toml" % lang))
            for k in vids:
                if re.search(r"\[(?:ref|lit|term):?", doc.get(k, "") or ""):
                    bad.append((lang, k))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
