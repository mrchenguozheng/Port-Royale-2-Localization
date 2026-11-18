# -*- coding: utf-8 -*-
"""部署清单：字体映射只写默认文件，不写用户 font-map.ini。"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "install"))

import importlib

import pr2ctl  # noqa: E402
deploy = importlib.import_module("pr2ctl.deploy")  # noqa: E402


class TestDeployFontMap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2-deploy-font-map-")
        self.runtime = os.path.join(self.tmp, "runtime")
        self.target = os.path.join(self.tmp, "target")
        os.makedirs(os.path.join(
            self.runtime, "PR2Localization", "fonts"))
        os.makedirs(os.path.join(
            self.target, "PR2Localization", "fonts"))
        with open(os.path.join(
                self.runtime, "PR2Localization", "fonts",
                "font-map.default.ini"), "w", encoding="utf-8") as fh:
            fh.write("[zh]\nARIAL.TTF=default-cjk.ttf\n")
        self.user_map = os.path.join(
            self.target, "PR2Localization", "fonts", "font-map.ini")
        with open(self.user_map, "w", encoding="utf-8") as fh:
            fh.write("[zh]\nARIAL.TTF=user-kept.ttf\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deploy_never_targets_user_font_map(self):
        old = (deploy.RUNTIME, deploy.FLAT_FILES, deploy.PACK_OUT,
               deploy.PACK_DIR)
        try:
            deploy.RUNTIME = self.runtime
            deploy.FLAT_FILES = ()
            deploy.PACK_OUT = os.path.join(self.runtime, "packs")
            deploy.PACK_DIR = "PR2Localization/packs"
            steps = deploy.deploy_steps(self.target, [], edition="gog")
        finally:
            (deploy.RUNTIME, deploy.FLAT_FILES, deploy.PACK_OUT,
             deploy.PACK_DIR) = old

        dests = [dst for _label, _src, dst in steps if dst]
        self.assertFalse(any(
            os.path.normcase(d).endswith("font-map.ini") for d in dests))
        self.assertTrue(any(
            os.path.normcase(d).endswith("font-map.default.ini")
            for d in dests))
        with open(self.user_map, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "[zh]\nARIAL.TTF=user-kept.ttf\n")


if __name__ == "__main__":
    unittest.main()
