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
