"""参照层清洁：短名解析、令牌前缀补全、补丁唯一命中。"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "tools"),
          os.path.join(ROOT, "src", "tools", "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)

from analysis import ref_clean as RC  # noqa: E402


class TestResolve(unittest.TestCase):
    def test_language_prefix_finds_the_only_file(self):
        path, name = RC.resolve("fr")
        self.assertTrue(path.endswith(os.path.join("src", "orig", "fr.gog_1.1.2.42.toml")))
        self.assertEqual(name, "fr.gog_1.1.2.42")

    def test_clean_name_is_resolvable(self):
        path, name = RC.resolve("en-clean")
        self.assertTrue(path.endswith("en-clean.toml"))
        self.assertEqual(name, "en-clean")

    def test_unknown_name_raises(self):
        with self.assertRaises(SystemExit):
            RC.resolve("no-such-language")


class TestTokenPrefix(unittest.TestCase):
    def test_bare_token_takes_the_base_prefix(self):
        out, n = RC.fix_token_prefix("have picked up @I$Settlers$ settlers",
                                     "sauvez @$Settlers$ colons")
        self.assertEqual(n, 1)
        self.assertIn("@I$Settlers$", out)

    def test_two_candidates_leave_it_alone(self):
        """基准里同名令牌有两种类型字母（真有两个不同的东西），就不猜。"""
        out, n = RC.fix_token_prefix("@I$Foo$ and @T$Foo$", "a @$Foo$ b")
        self.assertEqual(n, 0)
        self.assertIn("@$Foo$", out)

    def test_unknown_name_is_untouched(self):
        out, n = RC.fix_token_prefix("@I$Settlers$", "a @$Nobody$ b")
        self.assertEqual(n, 0)


class TestBaseAlignment(unittest.TestCase):
    """参照层的两档收紧：只补不删、只补在句末。"""

    def test_add_only_keeps_the_reference_own_paragraphs(self):
        base = "one.<n>two.<n>three."
        text = "eins.<n><n>zwei.<n><n>drei."
        out, notes = RC.RI.structural_fix(base, text, strip=False)
        self.assertEqual(out, text)
        self.assertIn("多 <n> 2（保留）", "、".join(notes))

    def test_strict_break_refuses_a_comma(self):
        base = "a.<n>b.<n>c."
        text = "x, y and z."
        out, notes = RC.RI.structural_fix(base, text, strip=False, strict_break=True)
        self.assertEqual(out.count("<n>"), 0)

    def test_strict_break_treats_a_quote_as_part_of_the_phrase(self):
        """`"Страны" хроники` 里引号后面不是句末，在这儿插换行会把标题劈开。"""
        self.assertIsNone(RC.RI._pick_break('в разделе "Страны" хроники.', strict=True))
        self.assertIsNotNone(RC.RI._pick_break('в разделе "Страны" хроники.', strict=False))

    def test_big_gap_is_left_to_a_human(self):
        base = "a.<n>b.<n>c.<n>d.<n>e."
        text = "x. y. z."
        out, notes = RC.RI.structural_fix(base, text, strip=False, strict_break=True)
        self.assertEqual(out, text)
        self.assertIn("缺口超过 2 处", "、".join(notes))


class TestAlignIdm(unittest.TestCase):
    def test_body_becomes_the_key_name(self):
        out, hit = RC.align_idm("IDM_CONTEST_01_2004_LOG_01_HDR", "Wachstum und Versorgung")
        self.assertTrue(hit)
        self.assertEqual(out, "IDM_CONTEST_01_2004_LOG_01_HDR")

    def test_an_empty_placeholder_is_not_a_key_name(self):
        """`+++EMPTY+++` 不是 IDM 键名：别家是空，本参照有正文时不按这套退。"""
        out, hit = RC.align_idm("+++EMPTY+++", "Seit einiger Zeit schon ...")
        self.assertFalse(hit)
        self.assertEqual(out, "Seit einiger Zeit schon ...")

    def test_already_aligned_is_no_change(self):
        out, hit = RC.align_idm("IDM_X", "IDM_X")
        self.assertFalse(hit)


class TestPatch(unittest.TestCase):
    def _run(self, patch, ref="en"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            RC.main(["--ref", ref, "--patch", patch])
        return buf.getvalue()

    def test_patch_that_misses_is_reported_not_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "p.json")
            io.open(p, "w", encoding="utf-8").write(
                json.dumps({"0xdb0108dd": [["not in this row", "x"]]}))
            text = self._run(p)
        self.assertIn("补丁片段不是唯一命中", text)

    def test_patch_hits_once_and_changes_the_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "p.json")
            io.open(p, "w", encoding="utf-8").write(json.dumps(
                {"0xdb0108dd": [["convoy.<n>Now return", "convoy.<n><n>Now return"]]}))
            text = self._run(p)
        self.assertIn("0xdb0108dd  按补丁补结构", text)
        self.assertIn("改动 1 条", text)


if __name__ == "__main__":
    unittest.main()
