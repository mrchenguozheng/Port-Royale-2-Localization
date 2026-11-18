# -*- coding: utf-8 -*-
"""版本基线（键集）与定向版本差的回归测试。

两份原版字符串表的键集不一样（实测 en.gog_1.1.2.3 3548 / fr.gog_1.1.2.42 3571），
译文只有一套、按并集组织，构建时按目标版本过滤。定向差
（src/data/versions/<源>-to-<目标>.toml）是过滤的唯一依据，所以这里盯死四件事：

  1. 基线清单读得出，键集与 src/orig 的表一致，并集 = 3590；
  2. 两个方向的差都在，数目 19 / 42，且与 orig 表逐键对得上；
  3. 手改差（多一条、少一条、镜像不一致）必须被 check() 抓到；
  4. 目标版独有的键若原文是正文，不能靠「目标版多出来的」进包 —— 不写译文行就报漏译。
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from text import versions as V  # noqa: E402

EN = "en.gog_1.1.2.3"
FR = "fr.gog_1.1.2.42"


class TestBaselines(unittest.TestCase):
    def test_two_baselines_and_counts(self):
        bases = V.load_baselines()
        self.assertEqual([b["id"] for b in bases], [EN, FR])
        self.assertEqual([len(b["keys"]) for b in bases], [3548, 3571])
        self.assertEqual(sum(1 for b in bases if b["primary"]), 1)
        self.assertTrue(bases[0]["primary"])

    def test_keys_match_orig_order(self):
        # 语言包按目标版原文表的顺序出行，这里确认没有额外排序
        en = V.read_orig(EN)
        fr = V.read_orig(FR)
        for b, src in ((V.load_baselines()[0], en), (V.load_baselines()[1], fr)):
            self.assertEqual(b["keys"], list(src))
            self.assertEqual(b["table"], src)

    def test_union_is_3590(self):
        self.assertEqual(len(V.union_keys()), 3590)


class TestDiffs(unittest.TestCase):
    def test_counts(self):
        diffs = V.load_diffs()
        self.assertEqual(len(diffs), 2)
        self.assertEqual(len(diffs[(EN, FR)]["only_from"]), 19)
        self.assertEqual(len(diffs[(EN, FR)]["only_to"]), 42)
        self.assertEqual(len(diffs[(FR, EN)]["only_from"]), 42)
        self.assertEqual(len(diffs[(FR, EN)]["only_to"]), 19)

    def test_mirror(self):
        diffs = V.load_diffs()
        self.assertEqual(diffs[(EN, FR)]["only_from"], diffs[(FR, EN)]["only_to"])
        self.assertEqual(diffs[(EN, FR)]["only_to"], diffs[(FR, EN)]["only_from"])

    def test_clean_data_passes(self):
        self.assertEqual(V.check(), [])

    def test_only_to_values_are_empty_or_translated(self):
        diffs = V.load_diffs()
        for (frm, to), d in diffs.items():
            table = V.read_orig(to)
            covered = V._translation_keys()
            for k in d["only_to"]:
                v = table[k]
                if v.strip() == V.EMPTY:
                    continue
                self.assertIn(k, covered,
                              "%s→%s %s 在目标版是正文，却没有译文行" % (frm, to, k))


class TestDiffTampering(unittest.TestCase):
    """手改差必须被抓到 —— 否则「按版本出包」就是靠一句注释在维持。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pr2-versions-")
        src = os.path.join(ROOT, "src", "data", "versions")
        for name in os.listdir(src):
            shutil.copy2(os.path.join(src, name), os.path.join(self.dir, name))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _load(self, pair):
        import tomllib
        path = os.path.join(self.dir, "%s-to-%s.toml" % pair)
        with open(path, "rb") as fh:
            return tomllib.load(fh)

    def _dump(self, pair, doc):
        import io
        path = os.path.join(self.dir, "%s-to-%s.toml" % pair)
        lines = ['from = "%s"' % doc["from"], 'to = "%s"' % doc["to"], ""]
        for field in ("only_from", "only_to"):
            lines.append("%s = [" % field)
            lines += ['  "%s",' % k for k in doc[field]]
            lines.append("]")
            lines.append("")
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines))

    def test_missing_key_is_reported(self):
        doc = self._load((EN, FR))
        doc["only_from"].pop()
        self._dump((EN, FR), doc)
        errs = V.check(data_dir=self.dir)
        self.assertTrue(any("only_from" in e for e in errs), errs)

    def test_extra_key_is_reported(self):
        doc = self._load((EN, FR))
        doc["only_to"].append("0xc46f793a")        # 共有键，不该在差里
        self._dump((EN, FR), doc)
        errs = V.check(data_dir=self.dir)
        self.assertTrue(any("only_to" in e for e in errs), errs)

    def test_mirror_break_is_reported(self):
        doc = self._load((FR, EN))
        doc["only_from"].pop()
        self._dump((FR, EN), doc)
        errs = V.check(data_dir=self.dir)
        self.assertTrue(any("镜像" in e for e in errs), errs)

    def test_descending_order_is_reported(self):
        doc = self._load((EN, FR))
        doc["only_from"].reverse()
        self._dump((EN, FR), doc)
        errs = V.check(data_dir=self.dir)
        self.assertTrue(any("升序" in e for e in errs), errs)

    def test_missing_diff_file_is_reported(self):
        os.remove(os.path.join(self.dir, "%s-to-%s.toml" % (FR, EN)))
        errs = V.check(data_dir=self.dir)
        self.assertTrue(any("缺定向差" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
