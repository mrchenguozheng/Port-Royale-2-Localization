# -*- coding: utf-8 -*-
"""配置校验的冒烟测试：仓库自身应通过，坏字体行应被拦下。"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

import config_check  # noqa: E402


class TestConfigCheck(unittest.TestCase):
    def test_repository_config_is_clean(self):
        errors, _warnings = config_check.check_repository(ROOT)
        self.assertEqual(errors, [])

    def test_font_map_rejects_ttc_and_unknown_key(self):
        tmp = tempfile.mkdtemp(prefix="pr2-config-check-")
        path = os.path.join(tmp, "font-map.ini")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[zh]\nARIAL.TTF=fake.ttc\nNOPE=MyFont.ttf\n")
        errors = []
        config_check._parse_font_map(path, tmp, errors)
        self.assertTrue(any("不接受" in e for e in errors))
        self.assertTrue(any("未知逻辑名" in e for e in errors))


    def test_pack_provenance_fields_are_known(self):
        errors, warnings = [], []
        config_check._check_packs(os.path.join(ROOT, "src"), errors, warnings)
        self.assertEqual(errors, [])
        self.assertFalse(any("未识别字段" in w for w in warnings))

    def test_pack_rejects_unknown_tag_and_bad_source_lang(self):
        tmp = tempfile.mkdtemp(prefix="pr2-config-pack-")
        src = os.path.join(tmp, "src")
        os.makedirs(os.path.join(src, "packs"))
        os.makedirs(os.path.join(src, "orig"))
        with open(os.path.join(src, "orig", "en.gog_1.1.2.3.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write("")
        with open(os.path.join(src, "packs", "zh.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write('alias = "简体中文"\n'
                     'tags = ["fan", "hand-made"]\n'
                     'source_lang = "../outside"\n')
        errors, _warnings = [], []
        config_check._check_packs(src, errors, _warnings)
        self.assertTrue(any("未知标记" in e for e in errors))
        self.assertTrue(any("source_lang" in e for e in errors))

    def test_pack_requires_tags(self):
        tmp = tempfile.mkdtemp(prefix="pr2-config-pack-")
        src = os.path.join(tmp, "src")
        os.makedirs(os.path.join(src, "packs"))
        with open(os.path.join(src, "packs", "zh.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write('alias = "简体中文"\n')
        errors, _warnings = [], []
        config_check._check_packs(src, errors, _warnings)
        self.assertTrue(any("缺 tags" in e for e in errors))

    def test_pack_rejects_legacy_provenance_fields(self):
        tmp = tempfile.mkdtemp(prefix="pr2-config-pack-")
        src = os.path.join(tmp, "src")
        os.makedirs(os.path.join(src, "packs"))
        with open(os.path.join(src, "packs", "zh.toml"),
                  "w", encoding="utf-8") as fh:
            fh.write('alias = "简体中文"\n'
                     'tags = ["fan"]\n'
                     'origin = "community"\n')
        errors, _warnings = [], []
        config_check._check_packs(src, errors, _warnings)
        self.assertTrue(any("已废弃" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
