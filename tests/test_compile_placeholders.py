# -*- coding: utf-8 -*-
"""编译期占位符比对的回归测试。

2025 批补译 15 条 2004 年竞赛文本时暴露的问题：这些键的英文原文是开发
残留标识符（`IDM_CONTEST_01_2004_LOG_06_TEXT`），不是句子，占位符比对
没有基准；照德语零售版补上 `@g$PirateGold$` 就被判成「多了占位符」。
豁免只认标识符形状，正常句子仍要照原文比对。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from pack import compile_pack as C  # noqa: E402
from shared.core import validate as V  # noqa: E402


class TestIdentifierExemption(unittest.TestCase):
    def test_identifier_origin_is_not_checked(self):
        errors, warnings = [], []
        ok = C.check_placeholders(
            "0x3426834a", "IDM_CONTEST_01_2004_LOG_06_TEXT",
            "让一名海盗听你调遣，他至少要交给你 @g$PirateGold$ 的战利品分成。",
            errors, warnings)
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_normal_sentence_still_checked(self):
        errors, warnings = [], []
        ok = C.check_placeholders(
            "0x11111111", "Give me %1 gold for %2 crates.",
            "给我 %2 箱，我就付你金币。", errors, warnings)
        self.assertFalse(ok)
        self.assertTrue(warnings)        # 少了占位符进警告
        self.assertEqual(errors, [])

    def test_short_uppercase_still_checked(self):
        # "OK" 这类短标签不是标识符，不能掉进豁免里
        self.assertFalse(V.is_identifier("OK"))
        self.assertFalse(V.is_identifier("CTRL"))
        self.assertFalse(V.is_identifier("Give me %1 gold."))
        self.assertTrue(V.is_identifier("IDM_CONTEST_01_2004_LOG_00_HDR"))


class TestVariableCodeCase(unittest.TestCase):
    """变量码按字面比：大写小写是两个不同引用，不做归一。

    0xca4930dc 的 @A$Amount$ 与全文 55 处的 @a$Amount$ 不一致，但引擎是否区分这个字母
    没有证据（见 09 卷 67.7），所以译文一律跟原文同形，比对也不替原文做主。
    """

    def test_original_typo_not_normalized(self):
        en = "I have to ship @A$Amount$ of @G$Goods$."
        zh = "我得运 @a$Amount$ 的 @G$Goods$。"
        self.assertNotEqual(V.tokens(en), V.tokens(zh))
        errors, warnings = [], []
        C.check_placeholders("0xca4930dc", en, zh, errors, warnings)
        # 大小写不同 = 少一个、多一个：少了进警告，多了进错误，不做归一
        self.assertIn("少了占位符", warnings[0])
        self.assertIn("多了占位符", errors[0])

    def test_same_form_passes(self):
        en = "I have to ship @A$Amount$ of @G$Goods$."
        zh = "我得运 @A$Amount$ 的 @G$Goods$。"
        self.assertEqual(V.tokens(en), V.tokens(zh))


class TestVersionOwnValueWins(unittest.TestCase):
    """出包按「这一版原文是什么」判：标识串原样、`+++EMPTY+++` 原样。

    两版键集不同（en 3548 / fr 3571 / 并集 3590），各自出包时行必须与**本版**
    原文对得上：本版是 `IDM_…` 开发标识的条目原样写出（哪怕译文层写了正文），
    本版是空占位的条目写回 `+++EMPTY+++`。另一版有正文的键才吃译文。
    """

    def _pack(self, orig, translated):
        from translate import BASE_LANG
        h = "0xaaaa1111"
        b = {"id": "en.test", "keys": [h], "table": {h: orig}, "primary": True}
        engine = {h: translated}
        by_hash = {h: {"id": h, BASE_LANG: orig}}
        errors, warnings, fatal = [], [], []
        res = C._pack_lines("zh", b, engine, by_hash, set(), False,
                            errors, warnings, fatal)
        lines, n, n_ph, n_empty, n_ident, _meta = res
        return lines, (n, n_ph, n_empty, n_ident), errors, warnings

    def test_identifier_origin_is_written_verbatim(self):
        lines, counts, errors, warnings = self._pack(
            "IDM_CONTEST_01_2004_LOG_00_TEXT", "到下面的城市去领取许可证：")
        self.assertEqual(counts, (0, 0, 0, 1))
        self.assertIn("IDM_CONTEST_01_2004_LOG_00_TEXT", lines[-1])
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_empty_origin_is_written_back(self):
        lines, counts, errors, _w = self._pack("+++EMPTY+++", "这里有正文")
        self.assertEqual(counts, (0, 0, 1, 0))
        self.assertIn("+++EMPTY+++", lines[-1])
        self.assertEqual(errors, [])

    def test_real_text_origin_uses_translation(self):
        lines, counts, errors, _w = self._pack("Give me %1 gold.", "给我 %1 枚金币。")
        self.assertEqual(counts[0], 1)
        self.assertIn("给我 %1 枚金币。", lines[-1])
        self.assertEqual(errors, [])

    def test_allcaps_word_is_not_a_resource_id(self):
        # fr 版 0x274e9455 的原文是 "ATTENTION"：全大写、9 个字母，形状上像标识，
        # 但没有下划线，是界面词，必须照译。
        lines, counts, errors, _w = self._pack("ATTENTION", "注意")
        self.assertEqual(counts[0], 1)
        self.assertIn("注意", lines[-1])
        self.assertEqual(errors, [])


class TestUnionBaseline(unittest.TestCase):
    """并集基线：键集取并，重复键只留一份，顺序先主基线再其余独有。"""

    def test_union_merges_keys_without_duplicates(self):
        b1 = {"id": "en.test", "keys": ["0x1", "0x2"],
              "table": {"0x1": "A", "0x2": "B"}, "primary": True}
        b2 = {"id": "fr.test", "keys": ["0x2", "0x3"],
              "table": {"0x2": "B 的另一版", "0x3": "+++EMPTY+++"}, "primary": False}
        u = C.union_baseline([b1, b2])
        self.assertEqual(u["keys"], ["0x1", "0x2", "0x3"])
        # 重复键取先出现那份的原文（主基线），不制造第二份正文
        self.assertEqual(u["table"]["0x2"], "B")
        self.assertEqual(u["table"]["0x3"], "+++EMPTY+++")
        self.assertTrue(u["primary"])
        self.assertIn("union", u["id"])


if __name__ == "__main__":
    unittest.main()
