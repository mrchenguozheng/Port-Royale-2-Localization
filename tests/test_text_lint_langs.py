# -*- coding: utf-8 -*-
"""非中文语言层检查（text_lint 的 ko / ja / es 分支）还能不能抓错。

这三条规则都是 W 级提示，不进门禁；这里只保证「判据没写反」：
韩语助词收音要报错的那一侧、占位符后接助词要报、并列写法不报、
西语倒置符号要成对、日语同条内不打一处体。
"""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "text_lint", os.path.join(ROOT, "src", "tools", "analysis", "text_lint.py"))
TL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(TL)

try:
    import kiwipiepy  # noqa: F401
    HAS_KIWI = True
except Exception:
    HAS_KIWI = False

try:
    import janome  # noqa: F401
    HAS_JANOME = True
except Exception:
    HAS_JANOME = False


class TestKeepViolations(unittest.TestCase):
    """有意不译名单的反向检查：save-name 只认 ASCII，其余要等于英文。"""

    def test_key_must_equal_english(self):
        W = TL.keep_violations({"0x1": "key"}, {"0x1": "이스케이프"}, {"0x1": "ESC"})
        self.assertEqual([w[1] for w in W], ["名单内但已改动（key）"])

    def test_ascii_save_name_is_fine_even_if_localized(self):
        W = TL.keep_violations({"0x2": "save-name"},
                               {"0x2": "Autospeichern %02u"}, {"0x2": "Autosave %02u"})
        self.assertEqual(W, [])

    def test_non_ascii_save_name_is_reported(self):
        W = TL.keep_violations({"0x3": "save-name"},
                               {"0x3": "オートセーブ %02u"}, {"0x3": "Autosave %02u"})
        self.assertEqual([w[1] for w in W], ["存档名非 ASCII"])

    def test_missing_entry_is_ignored(self):
        self.assertEqual(TL.keep_violations({"0x4": "key"}, {}, {}), [])

    def test_identifier_base_allows_translation(self):
        """版本差：英文侧是 `IDM_…_TEXT` 资源标识，正文只在零售版里，补译不算错。"""
        W = TL.keep_violations(
            {"0x5": "id"},
            {"0x5": "在以下城镇取得建筑许可：<n>哈瓦那、玛格丽塔。"},
            {"0x5": "IDM_CONTEST_01_2004_LOG_00_TEXT"})
        self.assertEqual(W, [])

    def test_empty_base_allows_translation(self):
        W = TL.keep_violations({"0x6": "id"}, {"0x6": "正文"},
                               {"0x6": "+++EMPTY+++"})
        self.assertEqual(W, [])

    def test_real_text_base_still_reports_change(self):
        """基准有正文时判据照旧：credit 名单里改了名就是错。"""
        W = TL.keep_violations({"0x7": "credit"}, {"0x7": "Johann Meier"},
                               {"0x7": "John Meier"})
        self.assertEqual([w[1] for w in W], ["名单内但已改动（credit）"])


class TestKoParticle(unittest.TestCase):
    def test_placeholder_followed_by_bare_josa_is_reported(self):
        W = []
        TL.ko_checks({"0x00000001": "@a$Amount$를 가지고 오십시오."}, W)
        self.assertEqual([w[1] for w in W], ["占位符后接助词"])

    def test_placeholder_followed_by_paired_josa_is_fine(self):
        W = []
        TL.ko_checks({"0x00000002": "@a$Amount$를(을) 가지고 오십시오."}, W)
        self.assertNotIn("占位符后接助词", [w[1] for w in W])

    def test_reversed_pair_order_is_reported(self):
        """反序 `과(와)`／`는(은)`／`로(으로)` 语义没错，但排版与全库不一致。"""
        W = []
        TL.ko_checks({"0x00000008": "%1과(와) 전쟁 중입니다."}, W)
        kinds = [w[1] for w in W]
        self.assertIn("并列助词次序", kinds)
        detail = "".join(w[2] for w in W if w[1] == "并列助词次序")
        self.assertIn("%1와(과)", detail)

    def test_canonical_pair_order_is_silent(self):
        W = []
        TL.ko_checks({"0x00000009": "%1와(과) 전쟁 중입니다."}, W)
        self.assertNotIn("并列助词次序", [w[1] for w in W])

    def test_bare_particle_after_graphic_tag_is_reported(self):
        W = []
        TL.ko_checks({"0x0000000a": "<g:INTEXT_GOLD_800x600.screen>를 받았습니다."}, W)
        self.assertIn("标签后接助词", [w[1] for w in W])

    def test_plain_tag_before_word_is_silent(self):
        """`<n>이 마을은…` 的「이」是正文指示词，不是助词。"""
        W = []
        TL.ko_checks({"0x0000000b": "<n>이 마을은 번성합니다."}, W)
        self.assertNotIn("标签后接助词", [w[1] for w in W])

    @unittest.skipUnless(HAS_KIWI, "需要 kiwipiepy")
    def test_wrong_jongseong_is_reported(self):
        W = []
        TL.ko_checks({"0x00000003": "물품를 드리겠습니다."}, W)
        self.assertIn("助词收音", [w[1] for w in W])

    @unittest.skipUnless(HAS_KIWI, "需要 kiwipiepy")
    def test_correct_jongseong_is_silent(self):
        W = []
        TL.ko_checks({"0x00000004": "물품을 드리겠습니다."}, W)
        self.assertNotIn("助词收音", [w[1] for w in W])

    @unittest.skipUnless(HAS_KIWI, "需要 kiwipiepy")
    def test_adnominal_ending_is_not_a_particle(self):
        # 「없는」是冠形词形词尾，不是助词；纯正则时代这里会误报
        W = []
        TL.ko_checks({"0x00000005": "교역 경험이 없는 선장을 보내십시오."}, W)
        self.assertNotIn("助词收音", [w[1] for w in W])


class TestEsInvertedMarks(unittest.TestCase):
    def test_unpaired_exclamation_is_reported(self):
        W = []
        TL.es_checks({"0x00000006": "Como no puedes superarlo, la partida es mía!"}, W)
        self.assertEqual([w[1] for w in W], ["倒置符号不配对"])

    def test_paired_marks_are_silent(self):
        W = []
        TL.es_checks({"0x00000007": "¿Quieres devolver tu permiso? ¡Recuerda que no!"}, W)
        self.assertEqual(W, [])

    def test_birth_year_uncertainty_is_not_a_question(self):
        # `1682?-1722` 是生卒年不确定，不是疑问句，不能被要成对。
        W = []
        TL.es_checks({"0x0000000a": "El galés Bartholomew Roberts (1682?-1722) fue pirata."}, W)
        self.assertEqual(W, [])

    def test_sentence_final_question_after_year_is_still_reported(self):
        # 同一条里句末的 ? 不能被上面的年份规则吃掉。
        W = []
        TL.es_checks({"0x0000000b": "Nació en 1682? ¡No lo sé!"}, W)
        self.assertEqual([w[1] for w in W], ["倒置符号不配对"])

    def test_punctuation_only_entry_is_silent(self):
        W = []
        TL.es_checks({"0x0000000c": "?"}, W)
        self.assertEqual(W, [])


class TestJaSpeechLevel(unittest.TestCase):
    @unittest.skipUnless(HAS_JANOME, "需要 janome")
    def test_mixed_levels_in_one_entry_are_reported(self):
        W = []
        TL.ja_checks({"0x00000008": "私は5点を宣言します。この勝負は私のものだ！"}, W)
        self.assertEqual([w[1] for w in W], ["语体混用"])

    @unittest.skipUnless(HAS_JANOME, "需要 janome")
    def test_uniform_level_is_silent(self):
        W = []
        TL.ja_checks({"0x00000009": "私は5点を宣言します。この勝負は私のものです。"}, W)
        self.assertEqual(W, [])

    @unittest.skipUnless(HAS_JANOME, "需要 janome")
    def test_quoted_plain_speech_does_not_count_as_mixing(self):
        # 引号里是别人原话，海盗就该说常体；叙述本身只有一个语体。
        W = []
        TL.ja_checks({"0x0000000d": "彼女の言葉が残っています。「この勝負は私のものだ」"}, W)
        self.assertEqual(W, [])


class TestKoUnit(unittest.TestCase):
    """韩语量词：缺量词 / 搭配错（都要 Kiwi 词元，子串不算）。"""

    @unittest.skipUnless(HAS_KIWI, "需要 kiwipiepy")
    def test_bare_noun_after_number_is_reported(self):
        out = TL.ko_unit_checks({"0x00000011": "@a$Amount$ 배를 확보하십시오."})
        self.assertEqual([o[1] for o in out], ["缺量词"])

    @unittest.skipUnless(HAS_KIWI, "需要 kiwipiepy")
    def test_counter_with_right_noun_is_silent(self):
        out = TL.ko_unit_checks({"0x00000012": "@a$Amount$척의 배를 확보하십시오."})
        self.assertEqual(out, [])

    @unittest.skipUnless(HAS_KIWI, "需要 kiwipiepy")
    def test_wrong_counter_for_noun_is_reported(self):
        out = TL.ko_unit_checks({"0x00000013": "5척의 병사를 보내십시오."})
        self.assertEqual([o[1] for o in out], ["量词搭配错"])

    @unittest.skipUnless(HAS_KIWI, "需要 kiwipiepy")
    def test_word_internal_char_is_not_a_counter(self):
        # 「%1 병력」「%1 대연회」「럼주 한 병」里的字不是量词用法，不能报
        for v in ("%1 병력 요청", "%1 대연회", "럼주 한 병 시켜 주십시오."):
            self.assertEqual(TL.ko_unit_checks({"0x00000014": v}), [], v)

    @unittest.skipUnless(HAS_KIWI, "需要 kiwipiepy")
    def test_particle_after_counter_is_skipped(self):
        # 「3척의 배」的量词后隔一个 의 再是名词，仍算搭配正确
        self.assertEqual(TL.ko_unit_checks({"0x00000015": "배 두 척은 항구에 있습니다."}), [])


class TestLintOk(unittest.TestCase):
    """W 级豁免清单：一行 `id<TAB>理由`，只免 W，理由要能被报告点名。"""

    def setUp(self):
        import shutil
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.old = TL.LINT_OK
        TL.LINT_OK = self.dir
        self.cleanup = lambda: shutil.rmtree(self.dir, ignore_errors=True)

    def tearDown(self):
        TL.LINT_OK = self.old
        self.cleanup()

    def _write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_common_and_lang_files_both_load(self):
        self._write("_common.txt", "# 注释\n0xc1\t字面就是原文\n")
        self._write("fr.txt", "0xf1\t字形覆盖测试串\n\n")
        got = TL.load_lint_ok("fr")
        self.assertEqual(got, {"0xc1": "字面就是原文", "0xf1": "字形覆盖测试串"})

    def test_comment_and_blank_lines_are_skipped(self):
        self._write("fr.txt", "# 头\n\n0xf1\t理由\n")
        self.assertEqual(list(TL.load_lint_ok("fr")), ["0xf1"])

    def test_other_language_file_is_not_loaded(self):
        self._write("de.txt", "0xd1\t德语专用\n")
        self.assertEqual(TL.load_lint_ok("fr"), {})

    def test_reason_may_be_omitted_but_id_still_counts(self):
        self._write("fr.txt", "0xf1\n")
        self.assertEqual(TL.load_lint_ok("fr"), {"0xf1": ""})


if __name__ == "__main__":
    unittest.main()
