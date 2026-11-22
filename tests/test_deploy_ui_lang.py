# -*- coding: utf-8 -*-
"""部署默认界面文案跟随安装语言：ui.<lang>.ini 落到目标 ui.default.ini。"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "install"))

deploy = importlib.import_module("pr2ctl.deploy")  # noqa: E402


class TestDeployUiLang(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2-deploy-ui-")
        self.runtime = os.path.join(self.tmp, "runtime")
        self.target = os.path.join(self.tmp, "target")
        self.ui = os.path.join(self.runtime, deploy.UI_DIR)
        os.makedirs(self.ui)
        os.makedirs(os.path.join(self.target, "PR2Localization", "packs"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _steps(self, langs):
        old = (deploy.RUNTIME, deploy.FLAT_FILES)
        try:
            deploy.RUNTIME = self.runtime
            deploy.FLAT_FILES = ()
            return deploy.deploy_steps(self.target, langs, edition="gog")
        finally:
            deploy.RUNTIME, deploy.FLAT_FILES = old

    def _write(self, name, text):
        with open(os.path.join(self.ui, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_selected_language_becomes_default(self):
        self._write("ui.default.ini", "[gui]\ntitle=中文\n")
        self._write("ui.ko.ini", "[gui]\ntitle=한국어\n")
        steps = self._steps(["ko"])
        dst = [s for _label, s, d in steps
               if d and d.endswith(os.path.join("ui", "ui.default.ini"))]
        self.assertTrue(dst, "部署清单里没有 ui.default.ini")
        self.assertEqual(os.path.basename(dst[0]), "ui.ko.ini")

    def test_missing_language_falls_back_to_default(self):
        self._write("ui.default.ini", "[gui]\ntitle=中文\n")
        steps = self._steps(["fr"])
        dst = [s for _label, s, d in steps
               if d and d.endswith(os.path.join("ui", "ui.default.ini"))]
        self.assertTrue(dst, "部署清单里没有 ui.default.ini")
        self.assertEqual(os.path.basename(dst[0]), "ui.default.ini")


if __name__ == "__main__":
    unittest.main()
