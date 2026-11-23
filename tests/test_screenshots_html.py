# -*- coding: utf-8 -*-
"""截图画廊必须由数据生成，不能因为手改 HTML 与源数据脱节。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "docs"))

import build_screenshots  # noqa: E402


class TestScreenshotsGallery(unittest.TestCase):
    def setUp(self):
        self.generated = build_screenshots.build()
        self.checked_in = build_screenshots.DEFAULT_OUTPUT.read_text(encoding="utf-8")

    def test_checked_in_html_is_generated(self):
        self.assertEqual(
            self.generated,
            self.checked_in,
            "docs/screenshots.html 与生成结果不一致；运行 "
            "python src/tools/docs/build_screenshots.py",
        )

    def test_counts(self):
        self.assertEqual(self.generated.count("<section class=\"row\">"), 5)
        self.assertEqual(self.generated.count("<figure>"), 59)
        self.assertEqual(self.generated.count('<img src="assets/screenshots/'), 59)
        self.assertEqual(self.generated.count("<span class=\"lang\">"), 59)
        self.assertEqual(self.generated.count("<p class=\"note\">"), 4)
        self.assertIn("59 张", self.generated)
        self.assertIn("共 59 张", self.generated)

    def test_coverage_table_is_well_formed(self):
        self.assertNotIn("</tr></tr>", self.generated)
        self.assertNotIn("<td>✓<td>✓</td>", self.generated)
        rows = self.generated.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        self.assertEqual(rows.count("<tr>"), 5)
        for row in rows.split("<tr>")[1:]:
            self.assertEqual(row.count("<td>"), 14)
            self.assertEqual(row.count("</td>"), 14)

    def test_semantic_fixes_survive_regeneration(self):
        self.assertIn("名 / 姓 / 起始城镇", self.generated)
        self.assertIn("名 / 姓 / 起始城鎮", self.generated)
        self.assertIn("이름 / 성 / 시작 도시", self.generated)
        self.assertIn("Nome / Sobrenome / Cidade inicial", self.generated)
        self.assertIn("归档的简体与繁体台湾建号图已替换", self.generated)


if __name__ == "__main__":
    unittest.main()
