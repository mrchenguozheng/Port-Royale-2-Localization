# -*- coding: utf-8 -*-
"""字体模式判定与构建时间源。"""

import datetime
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import build_time  # noqa: E402
import make_release  # noqa: E402


class TestResolveFontMode(unittest.TestCase):
    def test_languages_using_original_fonts_get_config(self):
        # de / es 在 font-map.ini 里四项都是 none，原版拉丁字体直接可用。
        self.assertEqual(make_release.resolve_font_mode("de", "auto"), "config")
        self.assertEqual(make_release.resolve_font_mode("es", "auto"), "config")

    def test_languages_with_real_fonts_get_noto(self):
        for lang in ("zh", "ja", "ko", "ru"):
            self.assertEqual(make_release.resolve_font_mode(lang, "auto"),
                             "noto", lang)

    def test_explicit_mode_passes_through(self):
        for mode in ("noto", "config", "none"):
            self.assertEqual(make_release.resolve_font_mode("zh", mode), mode)

    def test_unknown_language_defaults_to_noto(self):
        self.assertEqual(make_release.resolve_font_mode("xx", "auto"), "noto")


class TestBuildTime(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("SOURCE_DATE_EPOCH", None)

    def tearDown(self):
        os.environ.pop("SOURCE_DATE_EPOCH", None)
        if self._saved is not None:
            os.environ["SOURCE_DATE_EPOCH"] = self._saved

    def test_epoch_absent(self):
        self.assertIsNone(build_time.epoch())
        self.assertIsNone(build_time.zip_date_time())

    def test_epoch_parsed_and_invalid_ignored(self):
        os.environ["SOURCE_DATE_EPOCH"] = " 1795006965 "
        self.assertEqual(build_time.epoch(), 1795006965)
        os.environ["SOURCE_DATE_EPOCH"] = "not-a-number"
        self.assertIsNone(build_time.epoch())

    def test_timestamp_and_zip_date_come_from_same_epoch(self):
        os.environ["SOURCE_DATE_EPOCH"] = "1795006965"
        moment = datetime.datetime.fromtimestamp(1795006965,
                                                 datetime.timezone.utc)
        self.assertEqual(build_time.utc_timestamp(),
                         moment.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual(build_time.zip_date_time(),
                         (moment.year, moment.month, moment.day,
                          moment.hour, moment.minute, moment.second))

    def test_zip_date_clamped_to_1980(self):
        os.environ["SOURCE_DATE_EPOCH"] = "0"
        self.assertEqual(build_time.zip_date_time(), (1980, 1, 1, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
