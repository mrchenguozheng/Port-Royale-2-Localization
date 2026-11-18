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


class TestKoParticle(unittest.TestCase):
    def test_placeholder_followed_by_bare_josa_is_reported(self):
        W = []
        TL.ko_checks({"0x00000001": "@a$Amount$를 가지고 오십시오."}, W)
        self.assertEqual([w[1] for w in W], ["占位符后接助词"])

    def test_placeholder_followed_by_paired_josa_is_fine(self):
        W = []
        TL.ko_checks({"0x00000002": "@a$Amount$를(을) 가지고 오십시오."}, W)
        self.assertNotIn("占位符后接助词", [w[1] for w in W])

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


if __name__ == "__main__":
    unittest.main()
