# -*- coding: utf-8 -*-
"""占位符与标签规则的回归测试。

同一套规则原先有四份实现，口径互不相同且都不报错：有的把 "%2%1" 读成
"%21"、有的把 %02 归一成 %2（0 是补零宽度，归一化会把真差异藏掉）、有
的比对标签时把 <n><n> 吞成一个假名字。这里把这几条语义、判定级别以及
「调用方必须复用同一份」都钉住。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from shared.core import validate as V  # noqa: E402


class TestTokens(unittest.TestCase):
    def test_adjacent_position_args_not_merged(self):
        # 原文 <c><ts:175>%2<t>…%1：剥标签若删空，会粘成 "%2%1" 并被读成 "%21"
        self.assertEqual(V.tokens("<c><ts:175>%2<t>%1"), {"%1", "%2"})

    def test_zero_padding_is_literal(self):
        # %02u 是「2 位补零的存档编号」，0 有含义，不能和 %2u 算同一个
        self.assertEqual(V.tokens("Autosave %02u"), {"%02"})
        self.assertNotEqual(V.tokens("%02u"), V.tokens("%2u"))
        self.assertEqual(V.tokens("%002u"), {"%002"})

    def test_font_tag_is_not_placeholder(self):
        self.assertEqual(V.tokens(r"<f:fonts\Tiepolo.res>你好"), set())

    def test_script_token_keeps_prefix(self):
        # 同一变量名配不同前缀是两个不同的引用
        self.assertEqual(V.tokens("@P$TeacherName$"), {"@P$TeacherName$"})
        self.assertNotEqual(V.tokens("@P$TeacherName$"), V.tokens("@N$TeacherName$"))

    def test_script_token_requires_trailing_dollar(self):
        self.assertEqual(V.tokens("@P$TeacherName"), set())


class TestTagProfile(unittest.TestCase):
    def test_newline_forms_are_equivalent(self):
        # 项目写 " | "、引擎认 <n>，是同一个换行
        self.assertEqual(V.tag_profile("甲 | 乙"), V.tag_profile("甲<n>乙"))

    def test_color_value_ignored(self):
        self.assertEqual(V.tag_profile("<o:0xFFF2FAAD>甲"),
                         V.tag_profile("<o:0x00112233>甲"))

    def test_counts_are_kept(self):
        self.assertEqual(V.tag_profile("<n><n>甲"), ["|", "|"])


class TestCheckText(unittest.TestCase):
    def test_missing_is_warn_extra_is_error(self):
        out = V.check_text("%1", "%1 与 %2", lang="zh")
        self.assertEqual([x["level"] for x in out], ["warn"])

        out = V.check_text("%1 与 %2", "%1", lang="zh")
        self.assertEqual([x["level"] for x in out], ["error"])

    def test_adjacent_source_ok(self):
        # 原文紧邻、译文分开写：不算不一致
        self.assertEqual(V.check_text("%1 %2", "%2%1", lang="zh"), [])

    def test_zero_padding_mismatch_reported(self):
        # 原文 Autosave %02u、译文 Autosave %2u：少 %02 是警告、多 %2 是错误
        out = V.check_text("Autosave %2u", "Autosave %02u", lang="zh")
        self.assertEqual([x["level"] for x in out], ["warn", "error"])

    def test_empty_and_untranslated(self):
        self.assertEqual(V.check_text("", "%1", lang="zh")[0]["level"], "warn")
        out = V.check_text("0x1234abcd | hello", "%1", lang="zh")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["level"], "warn")

    def test_pipe_vs_n_ok(self):
        # 原文用 |、译文用 <n>：引擎里同一个换行，不该报擅自加标签
        self.assertEqual(V.check_text("甲<n>乙", "甲 | 乙", lang="zh"), [])

    def test_extra_tag_is_error(self):
        out = V.check_text("甲<n>乙<n>丙", "甲 | 乙", lang="zh")
        self.assertEqual([x["level"] for x in out], ["error"])


class TestSingleImplementation(unittest.TestCase):
    """调用方必须复用同一份规则，不能各留一份。"""

    def test_compile_pack_tokens_is_shared(self):
        from pack import compile_pack as C
        for s in ("%1 与 %2", "<c><ts:175>%2<t>%1", "%02u", r"<f:a\b.res>%1"):
            self.assertEqual(C.tokens(s), V.tokens(s), s)

    def test_translate_tokens_is_shared(self):
        import translate as T
        for s in ("%1 与 %2", "<c><ts:175>%2<t>%1", "%02u"):
            self.assertEqual(T.tokens(s), V.tokens(s), s)

    def test_no_second_implementation(self):
        """这两个模块里不该再出现自己的 RE_SCRIPT 或 def tokens。"""
        for rel in ("src/tools/translate.py", "src/tools/pack/compile_pack.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                src = f.read()
            self.assertNotIn("RE_SCRIPT", src, rel)
            self.assertNotIn("def tokens(", src, rel)


if __name__ == "__main__":
    unittest.main()
