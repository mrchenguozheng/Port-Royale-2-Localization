# -*- coding: utf-8 -*-
"""部署清单：根下平铺的 TTF 只拷当前语言映射引用的那几个。

build\\runtime\\PR2Localization\\fonts\\ 是累积目录，上一次构建别的语言留下的
PR2Cyr* 会一直躺在那儿；整目录照搬就会把没装的语言字体塞进游戏。
"""

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

MAP = """[fonts]
; 全局默认留空

[zh]
ARIAL.TTF=zh-body.ttf
ELGRECO_.TTF=zh-display.ttf|zh-display-alt.ttf
Tiepolo_black.ttf=none
Tiepolo_bold.ttf=-

[ru]
ARIAL.TTF=PR2CyrBody-Regular.ttf
ELGRECO_.TTF=PR2CyrDisplay-Head.ttf

[es]
ARIAL.TTF=none
ELGRECO_.TTF=none
"""


class TestDeployFontFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2-deploy-font-filter-")
        self.runtime = os.path.join(self.tmp, "runtime")
        self.src = os.path.join(self.tmp, "src")
        self.target = os.path.join(self.tmp, "target")
        self.font_src = os.path.join(
            self.runtime, deploy.FONT_DIR)
        os.makedirs(self.font_src)
        os.makedirs(self.target)
        for name in ("zh-body.ttf", "zh-display.ttf", "zh-display-alt.ttf",
                     "PR2CyrBody-Regular.ttf", "PR2CyrDisplay-Head.ttf"):
            with open(os.path.join(self.font_src, name), "wb") as fh:
                fh.write(b"")
        os.makedirs(self.src)
        with open(os.path.join(self.src, "font-map.ini"),
                  "w", encoding="utf-8") as fh:
            fh.write(MAP)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _steps(self, langs):
        old = (deploy.RUNTIME, deploy.FLAT_FILES, deploy.PACK_OUT,
               deploy.PACK_DIR, deploy.SRC)
        try:
            deploy.RUNTIME = self.runtime
            deploy.FLAT_FILES = ()
            deploy.PACK_OUT = os.path.join(self.runtime, "packs")
            deploy.PACK_DIR = "PR2Localization/packs"
            deploy.SRC = self.src
            return deploy.deploy_steps(self.target, langs, edition="gog")
        finally:
            (deploy.RUNTIME, deploy.FLAT_FILES, deploy.PACK_OUT,
             deploy.PACK_DIR, deploy.SRC) = old

    def _font_dests(self, steps):
        prefix = os.path.join(self.target, deploy.FONT_DIR) + os.sep
        return sorted(os.path.basename(dst) for _l, _s, dst in steps
                      if dst and os.path.normcase(dst).startswith(
                          os.path.normcase(prefix)) and dst.lower().endswith(".ttf"))

    def test_only_mapped_fonts_of_the_language(self):
        names = self._font_dests(self._steps(["zh"]))
        self.assertEqual(names, ["zh-body.ttf", "zh-display-alt.ttf",
                                 "zh-display.ttf"])

    def test_other_language_fonts_stay_behind(self):
        steps = self._steps(["zh"])
        self.assertFalse(any("PR2Cyr" in (dst or "")
                             for _l, _s, dst in steps))

    def test_language_with_all_none_copies_no_font(self):
        self.assertEqual(self._font_dests(self._steps(["es"])), [])
    def test_no_langs_still_copies_the_whole_folder(self):
        # langs 为空＝整目录复制，是打包/排查路径，保持原行为。
        names = self._font_dests(self._steps([]))
        self.assertEqual(len(names), 5)


if __name__ == "__main__":
    unittest.main()
