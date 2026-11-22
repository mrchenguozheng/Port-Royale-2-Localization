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
    """真编一个 zh 包，确认头里那几行真的写进去了。

    编译一次 zh 要 20 秒上下，两个断言共用同一份产物（``setUpClass``），
    别为每项各编一遍。
    """

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="pr2-pack-version-")
        cls.code = build_artifacts.compile_pack(
            "zh", cls.out, no_fonts=True, union=True, version="v9.9.9")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_pack_header_carries_version(self):
        self.assertEqual(self.code, 0)
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

    def test_pack_header_carries_stats_and_digest(self):
        """头里还有条目数、未译数与内容摘要：GUI 状态框与清单都读这几行。"""
        self.assertEqual(self.code, 0)
        path = os.path.join(self.out, "zh.txt")
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        head = [ln for ln in lines if ln.startswith("# pack-meta")]
        keys = [ln[len("# pack-meta "):].split("=", 1)[0] for ln in head]
        # 顺序固定：alias/min_runtime/version 在前，统计与摘要收尾。
        self.assertEqual(keys, ["alias", "min_runtime", "version", "entries",
                                "untranslated", "scope", "digest"])
        body = [ln for ln in lines if ln and not ln.startswith("#")]
        entries = int([ln for ln in head if "entries=" in ln][0].split("=")[1])
        self.assertEqual(entries, len(body), "entries 必须等于正文行数")
        self.assertIn("# pack-meta untranslated=0", head)
        self.assertIn("# pack-meta scope=union", head)
        digest = [ln for ln in head if "digest=" in ln][0].split("=")[1]
        self.assertRegex(digest, r"^[0-9a-f]{12}$")
        self.assertEqual(digest, compile_pack.pack_digest(
            [ln + "\n" for ln in body]))


class TestDigest(unittest.TestCase):
    """摘要只跟正文有关：换版本号不能换摘要，否则「同一份译文」会被报成变化。"""

    def test_digest_ignores_version_line(self):
        body = ["0x1A2B3C4D = 甲\n", "0x5E6F7081 = 乙\n"]
        head_a, _ = compile_pack._pack_head(
            "zh", "v1.0.0", "union", body, 2, 0)
        head_b, _ = compile_pack._pack_head(
            "zh", "v1.1.0", "union", body, 2, 0)
        # 传进来的值带 v 也照样归一，头里不会出现双前缀。
        self.assertIn("# pack-meta version=1.0.0\n", head_a)
        self.assertIn("# pack-meta version=1.1.0\n", head_b)
        digest_a = [ln for ln in head_a if "digest=" in ln]
        digest_b = [ln for ln in head_b if "digest=" in ln]
        self.assertEqual(digest_a, digest_b)

    def test_digest_changes_with_body(self):
        a = compile_pack.pack_digest(["0x1 = 甲\n"])
        b = compile_pack.pack_digest(["0x1 = 乙\n"])
        self.assertNotEqual(a, b)

    def test_digest_is_twelve_lowercase_hex(self):
        digest = compile_pack.pack_digest(["0x1 = 甲\n"])
        self.assertRegex(digest, r"^[0-9a-f]{12}$")

    def test_scope_token_flattens_union_ids(self):
        self.assertEqual(
            compile_pack.scope_token("union(en.gog_1.1.2.3+fr.gog_1.1.2.42)"),
            "union")
        self.assertEqual(compile_pack.scope_token("en.gog_1.1.2.3"),
                         "en.gog_1.1.2.3")


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

    def test_rust_reads_stats_and_digest_keys(self):
        path = os.path.join(ROOT, "src", "injector-rs", "pr2_launcher_gui",
                            "src", "packs.rs")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for key in ('"entries" | "untranslated"', '"digest" =>'):
            self.assertIn(key, text, "读取侧缺这个键：%s" % key)

    def test_release_passes_version_into_pack(self):
        path = os.path.join(ROOT, "src", "tools", "pack", "make_release.py")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("version=version", text,
                      "make_release 必须把发行版本传给 compile_pack")


if __name__ == "__main__":
    unittest.main()
