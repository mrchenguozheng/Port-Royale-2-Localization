# -*- coding: utf-8 -*-
"""截图画廊必须由数据生成，不能因为手改 HTML/Markdown 与源数据脱节。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "docs"))

import build_screenshots  # noqa: E402


class TestScreenshotsGallery(unittest.TestCase):
    def setUp(self):
        self.data = build_screenshots.load_json(build_screenshots.DEFAULT_DATA)
        self.lang_count = len(self.data["languages"])
        self.screen_count = len(self.data["screens"])
        self.extra_count = len(self.data.get("extras", []))
        self.figure_count = self.lang_count * self.screen_count + self.extra_count
        self.preview_count = len(self.data.get("page", {}).get("player", {}).get("samples", []))
        self.rendered_figure_count = self.figure_count + self.preview_count
        self.generated = build_screenshots.build()
        self.checked_in = build_screenshots.DEFAULT_OUTPUT.read_text(encoding="utf-8")
        self.generated_md = build_screenshots.build_markdown(
            self.data, build_screenshots.DEFAULT_DATA.parent
        )
        self.checked_in_md = build_screenshots.DEFAULT_MARKDOWN.read_text(encoding="utf-8")

    def test_checked_in_html_is_generated(self):
        self.assertEqual(
            self.generated,
            self.checked_in,
            "docs/screenshots.html 与生成结果不一致；运行 "
            "python src/tools/docs/build_screenshots.py --thumbs",
        )

    def test_checked_in_markdown_is_generated(self):
        self.assertEqual(
            self.generated_md,
            self.checked_in_md,
            "docs/实机截图.md 与生成结果不一致；运行 "
            "python src/tools/docs/build_screenshots.py --thumbs",
        )

    def test_counts(self):
        self.assertEqual(self.generated.count('<section class="row">'), self.screen_count)
        self.assertEqual(self.generated.count("<figure>"), self.rendered_figure_count)
        self.assertEqual(
            self.generated.count('<img src="assets/screenshots/thumbs/'),
            self.rendered_figure_count,
        )
        self.assertEqual(
            self.generated.count('<span class="lang">'), self.rendered_figure_count
        )
        self.assertEqual(
            self.generated.count('<p class="note">'), len(self.data.get("notes", []))
        )
        self.assertIn(f"{self.figure_count} 张", self.generated)
        self.assertIn(f"共 {self.figure_count} 张", self.generated)

    def test_coverage_table_is_well_formed(self):
        self.assertNotIn("</tr></tr>", self.generated)
        self.assertNotIn("<td>✓<td>✓</td>", self.generated)
        rows = self.generated.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        self.assertEqual(rows.count("<tr>"), self.screen_count)
        expected_cells = 3 + self.lang_count
        for row in rows.split("<tr>")[1:]:
            self.assertEqual(row.count("<td>"), expected_cells)
            self.assertEqual(row.count("</td>"), expected_cells)

    def test_lazy_thumbnail_with_full_image(self):
        self.assertNotIn('decoding="sync"', self.generated)
        self.assertEqual(
            self.generated.count('loading="lazy"'), self.rendered_figure_count
        )
        self.assertEqual(
            self.generated.count('data-full="assets/screenshots/'),
            self.rendered_figure_count,
        )
        self.assertIn('width="800"', self.generated)
        self.assertIn('height="600"', self.generated)

    def test_semantic_fixes_survive_regeneration(self):
        self.assertIn("名 / 姓 / 起始城镇", self.generated)
        self.assertIn("名 / 姓 / 起始城鎮", self.generated)
        self.assertIn("總督易卜拉欣 加西亞 / 見習水手 魔貝卡 博豪", self.generated)
        self.assertIn("이름 / 성 / 시작 도시", self.generated)
        self.assertIn("Nome / Sobrenome / Cidade inicial", self.generated)
        self.assertIn("归档的简体、繁体台湾与繁体香港建号图都已替换", self.generated)
        self.assertIn("十二语五屏覆盖", self.generated_md)

    def test_player_entry_has_effect_and_usage(self):
        player = self.data["page"]["player"]
        self.assertIn(player["heading"], self.generated)
        self.assertIn("下载语言包", self.generated)
        self.assertIn("PR2LocalizationGUI.exe", self.generated)
        self.assertIn("PR2Localization.exe --restore", self.generated)
        self.assertEqual(
            self.generated.count('<section class="player"'),
            1,
        )
        self.assertEqual(
            self.generated.count('<section class="how"'),
            1,
        )


if __name__ == "__main__":
    unittest.main()
