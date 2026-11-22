# -*- coding: utf-8 -*-
"""语言包版本：写进 pack 头的 ``# pack-meta version=``，启动器靠它显示「简体中文 · v1.0.0」。

要点有三个，缺一个都会让版本显示不出来或显示错：

- 写入侧（``compile_pack.py``）只接受 vMAJOR.MINOR.PATCH[-prerelease]，
  写进头的值不带 ``v``，避免 ``vv1.0.0`` 这种双前缀；
- 发行版本由 ``release.ps1 -Version`` 一路传到 ``make_release.build_pack``；
- 读取侧（``packs.rs``）的键名必须与写入侧一致 —— 两边各写各的，
  改一边不会有任何报错，列表只会静默地不显示版本。
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import build_artifacts  # noqa: E402
import compile_pack  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_strips_v_prefix(self):
        self.assertEqual(compile_pack.normalize_pack_version("v1.0.0"), "1.0.0")
        self.assertEqual(compile_pack.normalize_pack_version("1.0.0"), "1.0.0")
        self.assertEqual(compile_pack.normalize_pack_version(" v1.0.0-rc.1 "),
                         "1.0.0-rc.1")

    def test_rejects_half_versions(self):
        for bad in ("v1", "1.0", "latest", "v1.0.0.0", "", None):
            self.assertEqual(compile_pack.normalize_pack_version(bad), "",
                             "应拒绝：%r" % (bad,))


class TestCompiledPack(unittest.TestCase):
    """真编一个 zh 包，确认头里那行真的写进去了。"""

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="pr2-pack-version-")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_pack_header_carries_version(self):
        code = build_artifacts.compile_pack(
            "zh", self.out, no_fonts=True, union=True, version="v9.9.9")
        self.assertEqual(code, 0)
        path = os.path.join(self.out, "zh.txt")
        self.assertTrue(os.path.isfile(path))
        head = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.startswith("#"):
                    break
                head.append(line.rstrip("\n"))
        self.assertIn("# pack-meta alias=简体中文", head)
        self.assertIn("# pack-meta min_runtime=1", head)
        # 写进头的是归一化后的 9.9.9：前缀 v 只在显示时补。
        self.assertIn("# pack-meta version=9.9.9", head)
        self.assertFalse(any("version=v" in ln for ln in head), head)


class TestReaderMatchesWriter(unittest.TestCase):
    """Rust 读取侧的键名与 Python 写入侧必须一致。"""

    def test_rust_reads_the_version_key(self):
        path = os.path.join(ROOT, "src", "injector-rs", "pr2_launcher_gui",
                            "src", "packs.rs")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('"# pack-meta "', text)
        self.assertIn('"version" =>', text)
        self.assertIn("display_label", text)

    def test_release_passes_version_into_pack(self):
        path = os.path.join(ROOT, "src", "tools", "pack", "make_release.py")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("version=version", text,
                      "make_release 必须把发行版本传给 compile_pack")


if __name__ == "__main__":
    unittest.main()
