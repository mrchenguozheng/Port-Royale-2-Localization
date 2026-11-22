# -*- coding: utf-8 -*-
"""条目分类（entries.kind）的单元测试。"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))

from text import entries  # noqa: E402


class TestEntryKind(unittest.TestCase):
    def test_label(self):
        self.assertEqual(entries.kind("游戏菜单"), entries.LABEL)
        self.assertEqual(entries.kind("货物运输"), entries.LABEL)

    def test_phrase(self):
        self.assertEqual(entries.kind("科珀斯克里斯蒂"), entries.PHRASE)
        self.assertEqual(entries.kind("<n>货物运输与贸易"), entries.PHRASE)

    def test_prose(self):
        self.assertEqual(entries.kind("我刚听说，一艘船沉了。"), entries.PROSE)
        self.assertEqual(entries.kind("来到新大陆，你将从一无所有开始。"), entries.PROSE)

    def test_no_cjk(self):
        self.assertEqual(entries.kind("Dirk Niestadtkötter"), entries.NO_CJK)
        self.assertEqual(entries.kind("Tiepolo_black14x14aaFHk.res"), entries.NO_CJK)

    def test_template(self):
        self.assertEqual(entries.kind("%1 / %2"), entries.TEMPLATE)
        self.assertEqual(entries.kind("……"), entries.TEMPLATE)

    def test_variable_does_not_count_as_text(self):
        # 变量与标签不参与分类：剩 4 个汉字仍算短标签
        self.assertEqual(entries.kind("<c>%1  %2 货物"), entries.LABEL)

    def test_verse_override(self):
        self.assertEqual(entries.kind("海角西边有一座孤零零的城镇。", verse=True),
                         entries.VERSE)

    def test_tally(self):
        got = entries.tally([("0x1", "资产"), ("0x2", "我刚听说。"),
                             ("0x3", "%1 / %2")])
        self.assertEqual(got[entries.LABEL], 1)
        self.assertEqual(got[entries.PROSE], 1)
        self.assertEqual(got[entries.TEMPLATE], 1)

    def test_verse_ids(self):
        ids = entries.verse_ids()
        if ids:
            self.assertTrue(all(i.startswith("0x") for i in ids))


if __name__ == "__main__":
    unittest.main()
