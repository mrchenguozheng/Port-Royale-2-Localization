# -*- coding: utf-8 -*-
"""不译清单对账（keep_audit）的回归测试。

来源：`translate.py status` 对 zh 给 55 条「待译」，全是按键名（F1–F12）、
`Dummy`、职员表、游戏标题、场景文件名模板、`+++EMPTY+++` —— 值本来只能是
英文原样，却因为判据是「值里有没有汉字」被算成没译，又没登记进不译清单，
于是这个数字永远下不去。对账检查要能自己指出这类条目。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "analysis"))

import keep_audit as K  # noqa: E402


class TestStructural(unittest.TestCase):
    def test_symbols_and_placeholders_are_structural(self):
        for v in ("+++EMPTY+++", "--", "12", "IDM_CONTEST_01_2004_LOG_06_TEXT",
                  "<t:12>@I$Idx$</t>"):
            self.assertTrue(K.structural(v), v)

    def test_letters_are_not_structural(self):
        # 按键名、Dummy、人名都含字母：机器只报出来，登记与否由人定
        for v in ("F1", "Dummy", "Andreas Jupe", "Port Royale 2", "x 10",
                  "让一名海盗听你调遣"):
            self.assertFalse(K.structural(v), v)


class TestResourceId(unittest.TestCase):
    def test_identifier_shape(self):
        self.assertTrue(K.is_resource_id("IDM_CONTEST_01_2004_LOG_06_TEXT"))
        self.assertTrue(K.is_resource_id("PORT_ROYALE"))
        self.assertFalse(K.is_resource_id("ATTENTION"))
        self.assertFalse(K.is_resource_id("Port Royale 2"))


if __name__ == "__main__":
    unittest.main()
