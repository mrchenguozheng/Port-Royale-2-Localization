# -*- coding: utf-8 -*-
"""translate.py 的三个新入口回归：译完度判定、映射落盘、源缺失自查。

不碰真实译文：在临时 src\ 里造一份小 ko.toml，用 `T.set_src()` 把数据根
指过去，测完再指回来。
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

import translate as T  # noqa: E402
from shared.core.validate import tokens  # noqa: E402
from text import toml_io as TI  # noqa: E402


class TestScriptDeclared(unittest.TestCase):
    def test_latin_langs_have_no_script(self):
        for lang in ("fr", "de", "es"):
            self.assertIsNone(T.lang_rules.script_re(lang), lang)

    def test_non_latin_langs_have_script(self):
        for lang in ("zh", "ja", "ko", "ru"):
            self.assertIsNotNone(T.lang_rules.script_re(lang), lang)


class TestIsTranslated(unittest.TestCase):
    def test_korean_needs_hangul(self):
        rx = T.lang_rules.script_re("ko")
        self.assertTrue(T.is_translated("안녕하세요", "ko", script=rx))
        self.assertFalse(T.is_translated("Hello there", "ko", script=rx))

    def test_chinese_without_hangul_is_not_korean(self):
        rx = T.lang_rules.script_re("ko")
        self.assertFalse(T.is_translated("你好，世界", "ko", script=rx))

    def test_japanese_needs_kana_not_kanji(self):
        rx = T.lang_rules.script_re("ja")
        self.assertTrue(T.is_translated("こちらは港です", "ja", script=rx))
        self.assertFalse(T.is_translated("这里是港口", "ja", script=rx))

    def test_symbol_only_entry_counts_as_done(self):
        rx = T.lang_rules.script_re("ko")
        for val in ("%1", "<n>", "12,000", "%1 / %2"):
            self.assertTrue(T.is_translated(val, "ko", script=rx), val)

    def test_latin_lang_compares_with_english(self):
        self.assertFalse(T.is_translated("Business", "fr", base="Business"))
        self.assertTrue(T.is_translated("Commerce", "fr", base="Business"))

    def test_tag_is_ignored_when_testing_content(self):
        rx = T.lang_rules.script_re("ko")
        self.assertFalse(T.is_translated("<c>Goods</c> <n>", "ko", script=rx))


class TestBand(unittest.TestCase):
    def test_band_edges(self):
        self.assertEqual(T.band_of("가" * 12), (0, 12))
        self.assertEqual(T.band_of("가" * 13), (13, 24))
        self.assertEqual(T.band_of("가" * 81), (81, None))


class TestLoadMap(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "m.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_accepts_wrapped_map(self):
        self._write('{"map": {"a": "甲"}}')
        self.assertEqual(T.load_map(self.path), {"a": "甲"})

    def test_strips_keys(self):
        self._write('{" a ": "甲"}')
        self.assertEqual(T.load_map(self.path), {"a": "甲"})


class TestApplyMap(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "src")
        os.makedirs(os.path.join(self.src, "translations"))
        os.makedirs(os.path.join(self.src, "orig"))
        self.old_src = T.SRC
        T.set_src(self.src)
        self.path = os.path.join(self.src, "translations", "ko.toml")
        self.doc = {"0xa1": " Hello ", "0xa2": "World",
                    "0xa3": "Take %1 now", "0xa4": "안녕"}
        TI.write_doc_atomic(self.path, self.doc, list(self.doc), ["# 头"])

    def tearDown(self):
        T.set_src(self.old_src)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _read(self):
        doc, order = TI.read_doc(self.path)
        self.assertEqual(order, list(self.doc))
        return doc

    def test_hit_writes_and_keeps_edge_spaces(self):
        stats = T.apply_map("ko", {"Hello": "안녕하세요", "Nope": "없음"})
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(stats["unused"], ["Nope"])
        self.assertEqual(self._read()["0xa1"], " 안녕하세요 ")

    def test_second_run_is_idempotent(self):
        T.apply_map("ko", {"Hello": "안녕하세요"})
        again = T.apply_map("ko", {"Hello": "안녕하세요"})
        self.assertEqual(again["hit"], 0)
        self.assertGreaterEqual(again["applied"], 1)
        self.assertEqual(again["unused"], [])

    def test_english_value_is_refused_as_translation(self):
        stats = T.apply_map("ko", {"안녕": "Hello"})
        self.assertEqual(stats["hit"], 0)
        self.assertEqual(len(stats["lang"]), 1)
        self.assertEqual(self._read()["0xa4"], "안녕")

    def test_translated_entry_can_be_corrected(self):
        stats = T.apply_map("ko", {"안녕": "안녕하십니까"})
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(stats["rewrite"], 1)
        self.assertEqual(self._read()["0xa4"], "안녕하십니까")

    def test_hash_key_corrects_already_translated_entry(self):
        T.apply_map("ko", {"Hello": "안녕하세요"})
        stats = T.apply_map("ko", {"0xa1": "안녕하십니까"})
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(stats["unused"], [])
        self.assertEqual(self._read()["0xa1"], " 안녕하십니까 ")

    def test_bare_particle_blocks_the_write(self):
        stats = T.apply_map("ko", {"Take %1 now": "지금 %1를 가지세요"})
        self.assertEqual(stats["hit"], 0)
        self.assertEqual(len(stats["josa"]), 1)
        self.assertEqual(self._read()["0xa3"], "Take %1 now")

    def test_paired_particle_is_allowed(self):
        stats = T.apply_map("ko", {"Take %1 now": "지금 %1(을)를 가지세요"})
        self.assertEqual(stats["hit"], 1)

    def test_token_loss_blocks_the_write(self):
        stats = T.apply_map("ko", {"Take %1 now": "지금 가지세요"})
        self.assertEqual(stats["hit"], 0)
        self.assertEqual(stats["tokens"], ["0xa3"])
        self.assertEqual(self._read()["0xa3"], "Take %1 now")

    def test_dry_run_does_not_write(self):
        stats = T.apply_map("ko", {"Hello": "안녕하세요"}, dry_run=True)
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(self._read()["0xa1"], " Hello ")

    def test_reference_language_is_refused(self):
        with self.assertRaises(SystemExit):
            T.apply_map("en.gog_1.1.2.3", {"Hello": "안녕"})


class TestTokensAreTheSameImplementation(unittest.TestCase):
    def test_token_set_order_free(self):
        self.assertEqual(sorted(tokens("A %1 <n> B")), sorted(tokens("%1 B <n> A")))


if __name__ == "__main__":
    unittest.main()
