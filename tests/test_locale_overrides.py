# -*- coding: utf-8 -*-
"""locale 与 overrides 的防覆盖：默认文件、用户文件、本机覆盖都保留。"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "install"))

import pr2ctl  # noqa: E402
deploy = importlib.import_module("pr2ctl.deploy")  # noqa: E402


class TestLocaleAndOverrides(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2-locale-overrides-")
        self.runtime = os.path.join(self.tmp, "runtime")
        self.target = os.path.join(self.tmp, "target")
        self.pack = os.path.join(self.target, "PR2Localization", "packs")
        os.makedirs(os.path.join(
            self.runtime, "PR2Localization", "packs"))
        os.makedirs(self.pack)
        with open(os.path.join(
                self.runtime, "PR2Localization", "packs",
                "locale.default.ini"), "w", encoding="utf-8") as fh:
            fh.write("language=zh\n")
        shutil.copy2(os.path.join(
            self.runtime, "PR2Localization", "packs", "locale.default.ini"),
            os.path.join(self.pack, "locale.default.ini"))
        self.user_ini = os.path.join(self.pack, "locale.ini")
        with open(self.user_ini, "w", encoding="utf-8") as fh:
            fh.write("language=ja\n")
        self.overrides = os.path.join(self.pack, "overrides")
        os.makedirs(self.overrides)
        with open(os.path.join(self.overrides, "zh.txt"),
                  "w", encoding="utf-8") as fh:
            fh.write("0x1=本机临时译文\n")
        with open(os.path.join(self.pack, "fr.txt"),
                  "w", encoding="utf-8") as fh:
            fh.write("0x1=fr\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _with_runtime(self, fn):
        old = (deploy.RUNTIME, deploy.FLAT_FILES, deploy.PACK_OUT,
               deploy.PACK_DIR)
        try:
            deploy.RUNTIME = self.runtime
            deploy.FLAT_FILES = ()
            deploy.PACK_OUT = os.path.join(self.runtime, "PR2Localization",
                                           "packs")
            deploy.PACK_DIR = "PR2Localization/packs"
            return fn()
        finally:
            (deploy.RUNTIME, deploy.FLAT_FILES, deploy.PACK_OUT,
             deploy.PACK_DIR) = old

    def test_deploy_writes_default_locale_for_installed_language(self):
        def run():
            return deploy.deploy_steps(self.target, ["zh"], edition="gog")
        steps = self._with_runtime(run)
        dests = [dst for _label, _src, dst in steps if dst]
        self.assertTrue(any(
            os.path.normcase(d).endswith("locale.default.ini") for d in dests))
        self.assertFalse(any(
            os.path.normcase(d).endswith("locale.ini")
            and not os.path.normcase(d).endswith("locale.default.ini")
            for d in dests))
        default_steps = [(src, dst) for _label, src, dst in steps
                         if dst and os.path.normcase(dst).endswith(
                             "locale.default.ini")]
        self.assertEqual(len(default_steps), 1)
        self.assertIsInstance(default_steps[0][0], deploy.Generated)
        self.assertEqual(default_steps[0][0].text, "language=zh\n")
        with open(self.user_ini, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "language=ja\n")

    def test_generated_default_locale_overwrites_stale_value(self):
        default_ini = os.path.join(self.pack, "locale.default.ini")
        with open(default_ini, "w", encoding="utf-8") as fh:
            fh.write("language=pl\n")
        r = deploy.copy_if_different(
            deploy.Generated("language=zh\n"), default_ini)
        self.assertEqual(r, "copied")
        with open(default_ini, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "language=zh\n")
        self.assertEqual(deploy.copy_if_different(
            deploy.Generated("language=zh\n"), default_ini), "same")

    def test_deploy_without_langs_still_ships_building_default(self):
        os.remove(os.path.join(
            self.runtime, "PR2Localization", "packs",
            "locale.default.ini"))
        shutil.copy2(self.user_ini, os.path.join(
            self.runtime, "PR2Localization", "packs", "locale.ini"))

        def run():
            return deploy.deploy_steps(self.target, [], edition="gog")
        steps = self._with_runtime(run)
        default_steps = [
            (src, dst) for _label, src, dst in steps
            if dst and os.path.normcase(dst).endswith("locale.default.ini")
        ]
        self.assertEqual(len(default_steps), 1)
        self.assertTrue(default_steps[0][0].endswith("locale.ini"))

    def test_prune_keeps_overrides_and_locale_files(self):
        def run():
            return deploy.prune_stale_pack(self.target, ["zh"])
        removed = self._with_runtime(run)
        self.assertIn("fr.txt", removed)
        self.assertTrue(os.path.isfile(self.user_ini))
        self.assertTrue(os.path.isfile(os.path.join(
            self.pack, "locale.default.ini")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.overrides, "zh.txt")))

    def test_read_locale_prefers_user_then_default(self):
        self.assertEqual(pr2ctl.read_locale_language(self.target), "ja")
        os.remove(self.user_ini)
        self.assertEqual(pr2ctl.read_locale_language(self.target), "zh")

    def test_empty_user_value_is_not_filled_from_default(self):
        with open(self.user_ini, "w", encoding="utf-8") as fh:
            fh.write("language=\n")
        self.assertIsNone(pr2ctl.read_locale_language(self.target))
        self.assertEqual(pr2ctl.game_language(self.target), "")
        with open(self.user_ini, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "language=\n")

    def test_language_line_accepts_spaces_and_inline_comment(self):
        with open(self.user_ini, "w", encoding="utf-8") as fh:
            fh.write("# locale\nlanguage = ja ; selected in launcher\n")
        self.assertEqual(pr2ctl.read_locale_language(self.target), "ja")

    def test_write_replaces_spaced_language_without_duplicate(self):
        with open(self.user_ini, "w", encoding="utf-8") as fh:
            fh.write("# keep\nlanguage = zh\nother=1\n")
        self.assertTrue(pr2ctl.write_ini_language(self.user_ini, "ja"))
        with open(self.user_ini, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines[0], "# keep")
        self.assertEqual(lines[1], "language=ja")
        self.assertEqual(lines[2], "other=1")
        self.assertEqual(
            [line for line in lines if line.lower().startswith("language")],
            ["language=ja"])

    def test_write_appends_when_no_language_line(self):
        with open(self.user_ini, "w", encoding="utf-8") as fh:
            fh.write("other=1\n")
        self.assertTrue(pr2ctl.write_ini_language(self.user_ini, "ja"))
        with open(self.user_ini, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "other=1\nlanguage=ja\n")

    def test_write_removes_duplicate_language_lines(self):
        with open(self.user_ini, "w", encoding="utf-8") as fh:
            fh.write("language=ja\nlanguage = zh\nother=1\n")
        self.assertTrue(pr2ctl.write_ini_language(self.user_ini, "ko"))
        with open(self.user_ini, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "language=ko\nother=1\n")


if __name__ == "__main__":
    unittest.main()
