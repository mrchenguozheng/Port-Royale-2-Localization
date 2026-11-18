# -*- coding: utf-8 -*-
"""字体映射发行命名：默认文件与用户文件分离。"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import make_release  # noqa: E402


class TestFontMapPackaging(unittest.TestCase):
    def setUp(self):
        self.stage = tempfile.mkdtemp(prefix="pr2-font-map-pack-")
        self.fonts = os.path.join(self.stage, "PR2Localization", "fonts")
        os.makedirs(self.fonts)

    def tearDown(self):
        shutil.rmtree(self.stage, ignore_errors=True)

    def test_ships_default_and_preserves_user_map(self):
        user_map = os.path.join(self.fonts, "font-map.ini")
        with open(user_map, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("[zh]\nARIAL.TTF=my-font.ttf\n")

        make_release.copy_font_map(self.stage, lambda _m: None)

        self.assertTrue(os.path.isfile(
            os.path.join(self.fonts, "font-map.default.ini")))
        with open(user_map, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "[zh]\nARIAL.TTF=my-font.ttf\n")

    def test_no_user_map_written(self):
        make_release.copy_font_map(self.stage, lambda _m: None)
        self.assertTrue(os.path.isfile(
            os.path.join(self.fonts, "font-map.default.ini")))
        self.assertFalse(os.path.isfile(
            os.path.join(self.fonts, "font-map.ini")))


if __name__ == "__main__":
    unittest.main()
