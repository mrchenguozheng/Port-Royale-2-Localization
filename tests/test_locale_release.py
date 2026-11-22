# -*- coding: utf-8 -*-
"""发行包 locale 命名：只带默认文件，不带活动 locale.ini。"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import make_release  # noqa: E402


class TestLocalePackaging(unittest.TestCase):
    def setUp(self):
        self.stage = tempfile.mkdtemp(prefix="pr2-locale-pack-")

    def tearDown(self):
        shutil.rmtree(self.stage, ignore_errors=True)

    def test_build_pack_ships_default_only(self):
        with mock.patch("build_artifacts.compile_pack", return_value=0):
            make_release.build_pack(["zh"], self.stage, lambda _m: None, "zh")
        out = os.path.join(self.stage, "PR2Localization", "packs")
        default_ini = os.path.join(out, "locale.default.ini")
        self.assertTrue(os.path.isfile(default_ini))
        self.assertFalse(os.path.isfile(os.path.join(out, "locale.ini")))
        with open(default_ini, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "language=zh\n")


if __name__ == "__main__":
    unittest.main()
