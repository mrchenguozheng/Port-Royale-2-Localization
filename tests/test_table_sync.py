# -*- coding: utf-8 -*-
"""术语表/译名表的骨架生成与跨语言同步。

临时目录里复制真实 src/data，避免测试碰生产表。
"""

import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from text import table_sync as TS      # noqa: E402
from text import marks as M            # noqa: E402


class SyncBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        shutil.copytree(os.path.join(ROOT, "src", "data"), self.data)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSkeleton(SyncBase):
    def test_terms_keys_match_and_values_empty(self):
        TS.init_lang("ja", self.data)
        zh = TS.read_terms("zh", self.data)
        ja = TS.read_terms("ja", self.data)
        self.assertEqual(sorted(ja), sorted(zh))
        self.assertTrue(all(v == "" for v in ja.values()))
        # 注释与行尾说明要保留：文件里必须还有原形的注释
        text = open(TS.terms_path("ja", self.data), encoding="utf-8").read()
        self.assertIn("en: business", text)

    def test_names_cover_every_entity(self):
        TS.init_lang("ja", self.data)
        ja = TS.read_names("ja", self.data)
        self.assertEqual(sorted(ja), sorted(TS.names_baseline(self.data)))
        for entry in ja.values():
            self.assertEqual(entry.get("default"), "")

    def test_init_refuses_overwrite(self):
        TS.init_lang("ja", self.data)
        with self.assertRaises(SystemExit):
            TS.init_lang("ja", self.data)


class TestSync(SyncBase):
    def test_terms_append_only_new_keys(self):
        TS.init_lang("ja", self.data)
        with open(TS.terms_path("zh", self.data), "a", encoding="utf-8") as fh:
            fh.write('\nen_extra = "附加"\n')
        keys = TS.terms_baseline(["zh", "ja"], self.data)
        added = TS.sync_terms("ja", keys, self.data)
        self.assertEqual(added, ["en_extra"])
        ja = TS.read_terms("ja", self.data)
        self.assertIn("en_extra", ja)
        # 已有的空占位不能被改写、也不能重复
        self.assertEqual(sorted(ja), sorted(keys))

    def test_terms_sync_is_idempotent(self):
        TS.init_lang("ja", self.data)
        keys = TS.terms_baseline(["zh", "ja"], self.data)
        TS.sync_terms("ja", keys, self.data)
        self.assertEqual(TS.sync_terms("ja", keys, self.data), [])

    def test_names_refill_missing_sections(self):
        TS.init_lang("ja", self.data)
        path = TS.names_path("ja", self.data)
        text = open(path, encoding="utf-8").read()
        # 砍掉最后一个实体节，模拟「新加的专名老表里没有」
        blocks = re.split(r'\n(?=\["[^"]+"\])', text)
        keep = "\n".join(blocks[:-1])
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(keep.rstrip("\n") + "\n")
        missing = TS.sync_names("ja", TS.names_baseline(self.data), self.data)
        self.assertEqual(len(missing), 1)
        self.assertIn(missing[0], TS.read_names("ja", self.data))


class TestPlaceholderSemantics(SyncBase):
    def test_empty_term_reports_untranslated_not_missing(self):
        with self.assertRaises(M.MarkError) as cm:
            M.expand("[term:en_business]", {}, "ja", "0x1",
                     terms={"en_business": ""})
        self.assertIn("空占位", str(cm.exception))

    def test_absent_term_still_reports_missing(self):
        with self.assertRaises(M.MarkError) as cm:
            M.expand("[term:en_business]", {}, "ja", "0x1", terms={})
        self.assertIn("没有", str(cm.exception))

    def test_empty_name_reports_untranslated(self):
        with self.assertRaises(M.MarkError) as cm:
            M.expand("[ref:Tortuga]", {"Tortuga": {"default": ""}}, "ja", "0x1")
        self.assertIn("空占位", str(cm.exception))

    def test_placeholder_is_not_dead_entry(self):
        doc = {"0x1": "港のテキスト"}
        problems = M.check_doc("ja", doc, entities={}, terms={"en_business": ""})
        self.assertEqual(problems, [])


class TestReport(SyncBase):
    def test_counts(self):
        TS.init_lang("ja", self.data)
        rows, tkeys, nkeys = TS.report(self.data)
        by_lang = {r["lang"]: r for r in rows}
        self.assertEqual(by_lang["zh"]["terms"][:2], (len(tkeys), len(tkeys)))
        self.assertEqual(by_lang["ja"]["terms"][:2], (0, len(tkeys)))
        self.assertEqual(by_lang["ja"]["names"][:2], (0, len(nkeys)))


if __name__ == "__main__":
    unittest.main()
