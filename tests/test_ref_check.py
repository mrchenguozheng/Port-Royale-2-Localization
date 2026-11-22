#!/usr/bin/env python3
# coding: utf-8
"""参照版健康检查的回归用例。

判据都是「照抄这行会怎样」：令牌/标签对不上必被 apply 拦（E），
长度骤降或停在上限且收尾不完整是疑似截断（W）。全句完整、只是比
英文短的不许报——波兰语零售版里位比只有 1.01，压到 0.8 的地方多半
是译得简洁，报出来会淹掉真问题。
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "tools"),
          os.path.join(ROOT, "src", "tools", "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ref_check as RC  # noqa: E402


def _write(path, pairs):
    lines = ["# 造数据"]
    for hid, text in pairs:
        esc = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        lines.append('"%s" = "%s"' % (hid, esc))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


class TestRefCheck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.base = os.path.join(self.dir, "en.toml")
        self.ref = os.path.join(self.dir, "xx.toml")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _run(self, base_pairs, ref_pairs):
        _write(self.base, base_pairs)
        _write(self.ref, ref_pairs)
        e_rows, w_rows, same, extra, common = RC.check(self.ref, self.base)
        return e_rows, w_rows, same

    def test_token_loss_is_e(self):
        e_rows, _w, _s = self._run(
            [("0xa1", "Pay %1 for @g$Price$")],
            [("0xa1", "Zaplac %1 za cene")])
        self.assertEqual([h for h, _ in e_rows], ["0xa1"])
        self.assertIn("令牌不齐", e_rows[0][1])

    def test_tag_count_loss_is_e(self):
        e_rows, _w, _s = self._run(
            [("0xa2", "<n>One<n>Two")],
            [("0xa2", "<n>Raz")])
        self.assertEqual([h for h, _ in e_rows], ["0xa2"])
        self.assertIn("标签个数不齐", e_rows[0][1])
        self.assertIn("<n> 基准 2 参照 1", e_rows[0][1])

    def test_truncation_at_limit_is_w(self):
        long_en = "A" * 300
        # 正好落在 255 字符、且停在逗号上：导出工具截一半的样子。
        cut = "B" * (RC.HARD_LIMIT - 2) + ", "
        e_rows, w_rows, _s = self._run(
            [("0xa3", long_en + ".")],
            [("0xa3", cut)])
        self.assertEqual(len(cut), RC.HARD_LIMIT)
        self.assertEqual(e_rows, [])
        self.assertEqual([h for h, _ in w_rows], ["0xa3"])
        self.assertIn("收尾不完整", w_rows[0][1])

    def test_short_but_complete_is_not_reported(self):
        """译得简洁的长句不报——W 只留给真的像断了的。"""
        en = "I have nothing further to say to you, other than this warning: " \
             "watch out for the military convoys of my nation, for they are hunting you!"
        ref = "Moge cie jeszcze tylko ostrzec: uwazaj na konwoje wojskowe z mojego " \
              "narodu, ktore poluja na ciebie, wiec nie wychodz bez broni!"
        e_rows, w_rows, _s = self._run([("0xa4", en)], [("0xa4", ref)])
        self.assertGreaterEqual(len(ref), len(en) * RC.SHORT_RATIO)
        self.assertEqual(e_rows, [])
        self.assertEqual(w_rows, [])

    def test_same_as_english_is_only_counted(self):
        _e, _w, same = self._run(
            [("0xa5", "Port Royale")],
            [("0xa5", "Port Royale")])
        self.assertEqual(same, 1)

    def test_ids_absent_from_base_are_skipped(self):
        e_rows, _w, _s = self._run(
            [("0xa6", "Hello")],
            [("0xa6", "Witaj"), ("0xb1", "Extra %9")])
        self.assertEqual(e_rows, [])


if __name__ == "__main__":
    unittest.main()
