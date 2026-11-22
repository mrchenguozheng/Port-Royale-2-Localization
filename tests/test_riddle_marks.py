#!/usr/bin/env python3
# coding: utf-8
"""诗谜标注搬运的回归用例。

核心判据两条：clue 必须逐字出现在**本语言**谜面里（照抄别国语言的 clue
必然失败，本轮 pl 就被这条拦了 5 次）；副本必须指向「带谜底的代表条目」，
指向另一条副本等于组身份接不上。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "tools"),
          os.path.join(ROOT, "src", "tools", "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)

import riddle_marks as RM  # noqa: E402

REP_MARK = "[riddle:answer=Corpus Christi;group=35f48f6c,35f48f6d;level=town;" \
           "certainty=inferred;source=original-en&authored]"


def _write(path, pairs):
    lines = []
    for hid, text in pairs:
        esc = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        lines.append('"%s" = "%s"' % (hid, esc))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


class TestRiddleMarks(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.en = os.path.join(self.dir, "en.toml")
        self.ko = os.path.join(self.dir, "ko.toml")
        self.pl = os.path.join(self.dir, "pl.toml")
        self.old = (RM.EN, RM.TR)
        RM.EN = self.en
        RM.TR = os.path.join(self.dir, "%s.toml")
        _write(self.en, [("0x35f48f6c", "Far from the world, abandoned."),
                         ("0x35f48f6d", "Far from the world, abandoned.")])
        _write(self.ko, [("0x35f48f6c", REP_MARK + " 먼 곳에 버림받은."),
                         ("0x35f48f6d", "[riddle:copy=0x35f48f6c]")])
        _write(self.pl, [("0x35f48f6c", "Daleko od świata, porzucone."),
                         ("0x35f48f6d", "Daleko od świata, porzucone.")])

    def tearDown(self):
        RM.EN, RM.TR = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_metadata_is_copied_and_clue_checked(self):
        out, problems, reps, total, _bd = RM.build(
            "pl", "ko", {"0x35f48f6c": "Daleko, porzucone"})
        self.assertEqual(problems, [])
        self.assertEqual((reps, total), (1, 2))
        self.assertIn("answer=Corpus Christi", out["0x35f48f6c"])
        self.assertIn("clue=Daleko, porzucone", out["0x35f48f6c"])
        self.assertTrue(out["0x35f48f6c"].endswith("Daleko od świata, porzucone."))
        self.assertEqual(out["0x35f48f6d"], "[riddle:copy=0x35f48f6c]")

    def test_clue_word_must_appear_in_verse(self):
        _out, problems, _r, _t, _bd = RM.build(
            "pl", "ko", {"0x35f48f6c": "Daleko, wyspa"})
        self.assertEqual(len(problems), 1)
        self.assertIn("wyspa", problems[0])

    def test_clue_is_case_sensitive(self):
        """谜面写的是 `Daleko`；给小写就找不到——大小写算不同的事。"""
        _out, problems, _r, _t, _bd = RM.build(
            "pl", "ko", {"0x35f48f6c": "daleko"})
        self.assertEqual(len(problems), 1)
        self.assertIn("不在本语言谜面里", problems[0])

    def test_missing_clue_is_reported(self):
        out, problems, _r, _t, _bd = RM.build("pl", "ko", {})
        self.assertIn("缺 clue", problems[0])
        self.assertNotIn("0x35f48f6c", out)

    def test_copy_must_point_at_a_representative(self):
        _write(self.ko, [("0x35f48f6c", REP_MARK + " 먼 곳에."),
                         ("0x35f48f6d", "[riddle:copy=0x35f48f6d]")])
        _out, problems, _r, _t, _bd = RM.build("pl", "ko", {"0x35f48f6c": "Daleko"})
        self.assertTrue(any("copy 指向自己" in p for p in problems))

    def test_unannotated_entry_is_reported(self):
        _write(self.ko, [("0x35f48f6c", REP_MARK + " 먼 곳에.")])
        _out, problems, _r, _t, _bd = RM.build("pl", "ko", {"0x35f48f6c": "Daleko"})
        self.assertTrue(any("无从搬" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
