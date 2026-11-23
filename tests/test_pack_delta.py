# -*- coding: utf-8 -*-
"""语言包变化统计：相对上一次发行（``v*`` tag）改了多少条译文。

口径是**译文条目**，不是 diff 行数，所以这里既测 id 集合的折算式，
也在一座临时 git 仓库里测基准选择与几种「没有可比基准」的分支 ——
基准选错会算出一个看着合理、其实毫无意义的数字。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import pack_delta  # noqa: E402


def _git(root, *args):
    exe = pack_delta._git_exe()
    subprocess.run([exe] + list(args), cwd=root, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class TestParseDiff(unittest.TestCase):
    def test_counts_changed_added_removed(self):
        diff = (
            "--- a/src/translations/zh.toml\n"
            "+++ b/src/translations/zh.toml\n"
            "@@ -1 +1 @@\n"
            '-"0xaaaabbbb" = "旧"\n'
            '+"0xaaaabbbb" = "新"\n'
            "@@ -5,0 +6,1 @@\n"
            '+"0xccccdddd" = "新增"\n'
            "@@ -9 +8,0 @@\n"
            '-"0xeeeeffff" = "删除"\n'
        )
        removed, added = pack_delta.parse_diff(diff)
        self.assertEqual(pack_delta.summarize(removed, added),
                         {"changed": 1, "added": 1, "removed": 1})

    def test_ignores_context_and_header_lines(self):
        diff = (
            "--- a/src/translations/zh.toml\n"
            "+++ b/src/translations/zh.toml\n"
            " 0x11112222 = 上下文\n"
        )
        removed, added = pack_delta.parse_diff(diff)
        self.assertEqual(pack_delta.summarize(removed, added),
                         {"changed": 0, "added": 0, "removed": 0})

    def test_same_id_on_both_sides_is_a_change(self):
        removed, added = pack_delta.parse_diff(
            '-"0xaaaabbbb" = "旧"\n+"0xaaaabbbb" = "新"\n')
        self.assertEqual(pack_delta.summarize(removed, added)["changed"], 1)


class TestPackDeltaInRepo(unittest.TestCase):
    """在临时仓库里跑真 git：基准 tag 的选择和几种缺失基准的分支。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2-delta-repo-")
        self.rel = os.path.join("src", "translations", "zh.toml")
        _git(self.tmp, "init", "-q")
        _git(self.tmp, "config", "user.email", "test@example.com")
        _git(self.tmp, "config", "user.name", "test")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, text):
        path = os.path.join(self.tmp, self.rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def _commit(self, message="c"):
        _git(self.tmp, "add", "-A")
        _git(self.tmp, "commit", "-q", "-m", message)

    def test_initial_when_baseline_has_no_translation_file(self):
        # 基准里压根没有这份译文（连文件都不存在）：不给数字，只标「第一次收录」。
        _git(self.tmp, "commit", "-q", "--allow-empty", "-m", "base")
        _git(self.tmp, "tag", "v0.1.0")
        self._write('"0xaaaabbbb" = "甲"\n')
        delta = pack_delta.pack_delta("zh", "v0.2.0", root=self.tmp)
        self.assertEqual(delta["kind"], "initial")
        self.assertEqual(delta["baseline"], "v0.1.0")

    def test_changed_counts_entries_not_lines(self):
        self._write('"0xaaaabbbb" = "甲"\n"0xccccdddd" = "乙"\n')
        self._commit()
        _git(self.tmp, "tag", "v0.1.0")
        # 改一条、加一条；没有提交也算进本次变化（出包前可能带着未提交改动）。
        self._write('"0xaaaabbbb" = "甲改"\n"0xccccdddd" = "乙"\n'
                    '"0xeeeeffff" = "丙"\n')
        delta = pack_delta.pack_delta("zh", "v0.2.0", root=self.tmp)
        self.assertEqual(delta["kind"], "changed")
        self.assertEqual(delta["changed"], 1)
        self.assertEqual(delta["added"], 1)
        self.assertEqual(delta["removed"], 0)

    def test_same_when_nothing_changed(self):
        self._write('"0xaaaabbbb" = "甲"\n')
        self._commit()
        _git(self.tmp, "tag", "v0.1.0")
        delta = pack_delta.pack_delta("zh", "v0.2.0", root=self.tmp)
        self.assertEqual(delta["kind"], "same")
        self.assertEqual(delta["changed"], 0)

    def test_same_version_tag_is_not_used_as_its_own_baseline(self):
        self._write('"0xaaaabbbb" = "甲"\n')
        self._commit()
        _git(self.tmp, "tag", "v0.1.0")
        self._write('"0xaaaabbbb" = "甲改"\n')
        self._commit()
        _git(self.tmp, "tag", "v0.2.0")
        delta = pack_delta.pack_delta("zh", "v0.2.0", root=self.tmp)
        self.assertEqual(delta["baseline"], "v0.1.0")
        self.assertEqual(delta["kind"], "changed")
        self.assertEqual(delta["changed"], 1)

    def test_none_when_no_release_tag(self):
        self._write('"0xaaaabbbb" = "甲"\n')
        self._commit()
        delta = pack_delta.pack_delta("zh", "v0.2.0", root=self.tmp)
        self.assertEqual(delta["kind"], "none")
        self.assertIsNone(delta["baseline"])

    def test_explicit_tag_overrides_auto(self):
        self._write('"0xaaaabbbb" = "甲"\n')
        self._commit()
        _git(self.tmp, "tag", "v0.1.0")
        delta = pack_delta.pack_delta("zh", "v0.2.0", root=self.tmp,
                                      tag="v0.1.0")
        self.assertEqual(delta["kind"], "same")


if __name__ == "__main__":
    unittest.main()
