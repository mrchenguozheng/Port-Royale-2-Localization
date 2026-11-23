# -*- coding: utf-8 -*-
"""语言注册表、发行语言解析和部署参数兼容性。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import language_registry  # noqa: E402
import release_version  # noqa: E402
import apply_patch  # noqa: E402
import check_breaks  # noqa: E402


class TestLanguageRegistry(unittest.TestCase):
    def test_audit_has_no_errors(self):
        errors, _warnings, _rows = language_registry.audit(ROOT)
        self.assertEqual(errors, [])

    def test_release_languages_include_region_codes(self):
        langs = release_version.read_languages(os.path.join(ROOT, "src"))
        self.assertEqual(len(langs), 12)
        self.assertIn("zh-TW", langs)
        self.assertIn("zh-HK", langs)
        self.assertIn("pt-BR", langs)

    def test_preview_list_is_empty(self):
        preview = language_registry._read_raw_languages(
            os.path.join(ROOT, "src", "preview-languages.txt")
        )
        self.assertEqual(preview, [])

    def test_zh_hk_has_own_screenshots(self):
        errors, warnings, rows = language_registry.audit(ROOT)
        self.assertEqual(errors, [])
        row = next(r for r in rows if r.code == "zh-HK")
        self.assertTrue(row.screenshot)
        self.assertEqual(row.screenshot_source, "")
        self.assertFalse(any("zh-HK" in w and "截图" in w for w in warnings))

    def test_pick_langs_accepts_list_and_csv(self):
        self.assertEqual(apply_patch.pick_langs(["ja,zh"]), ["ja", "zh"])
        self.assertEqual(apply_patch.pick_langs([], ["ko", "pt-BR"]),
                         ["ko", "pt-BR"])
        self.assertEqual(apply_patch.pick_langs(["ja"], ["ko"]),
                         ["ja", "ko"])

    def test_break_check_expands_ref(self):
        rows = [
            {"id": "0x00000001", "en": "first<n><n>second",
             "de": "first<n><n>second"},
            {"id": "0x00000002", "en": "duplicate", "de": "[ref:0x00000001]"},
        ]
        doc = check_breaks._doc_for(rows, "de")
        self.assertEqual(check_breaks.nn(doc["0x00000002"]), 2)


if __name__ == "__main__":
    unittest.main()
