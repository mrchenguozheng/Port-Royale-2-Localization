# -*- coding: utf-8 -*-
"""配置校验的冒烟测试：仓库自身应通过，坏字体行应被拦下。"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

import config_check  # noqa: E402


class TestConfigCheck(unittest.TestCase):
    def test_repository_config_is_clean(self):
        errors, _warnings = config_check.check_repository(ROOT)
        self.assertEqual(errors, [])

    def test_font_map_rejects_ttc_and_unknown_key(self):
        tmp = tempfile.mkdtemp(prefix="pr2-config-check-")
        path = os.path.join(tmp, "font-map.ini")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[zh]\nARIAL.TTF=fake.ttc\nNOPE=MyFont.ttf\n")
        errors = []
        config_check._parse_font_map(path, tmp, errors)
        self.assertTrue(any("不接受" in e for e in errors))
        self.assertTrue(any("未知逻辑名" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
