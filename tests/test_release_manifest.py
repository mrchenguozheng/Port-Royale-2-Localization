# -*- coding: utf-8 -*-
"""发行包 manifest 的哈希与来源校验。"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import release_manifest  # noqa: E402


class TestReleaseManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2-manifest-")
        self.stage = os.path.join(self.tmp, "PR2-zh-v1.0.0")
        self._write("RUNTIME-VERSION", "1\n")
        self._write("README.txt", "test\n")
        self._write("PR2Localization/packs/zh.txt", "0x1 = 测试\n")
        self._write("PR2Localization/packs/locale.default.ini",
                    "language=zh\n")
        self._write("PR2Localization/fonts/NotoSansSC-Regular.ttf", b"font")
        self._write("PR2Localization/fonts/font-map.default.ini",
                    "[zh]\nARIAL.TTF=NotoSansSC-Regular.ttf\n")
        self._write("PR2Localization/ui/ui.default.ini", "[gui]\ntitle=测试\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rel, content):
        path = os.path.join(self.stage, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if isinstance(content, bytes):
            with open(path, "wb") as fh:
                fh.write(content)
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)

    def test_manifest_hashes_targets_source_and_provenance(self):
        path = release_manifest.write_release_manifest(
            self.stage, "zh", "v1.0.0", "noto")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        # 合并包：一个清单同时声明 GOG 与 Steam 两个已知构建。
        self.assertEqual(data["edition"], "universal")
        self.assertEqual(data["schema"], 2)
        self.assertNotIn("target", data, "schema 2 起改用 targets 列表")
        targets = {item["build"]: item for item in data["targets"]}
        self.assertEqual(set(targets), {"gog-en-1.1.2.3", "steam-en-1.1.2.3"})
        self.assertEqual(
            targets["gog-en-1.1.2.3"]["exe_sha256"],
            "394CE2A48BC6B21708B81A232C7C88459BE7F3C8082CC593AD83B0B8E4C168EC",
        )
        self.assertEqual(
            targets["steam-en-1.1.2.3"]["exe_sha256"],
            "5295C06689147F7565F72510AEB686719CF0AE38AA581A6DF3E4D61D0CF76264",
        )
        self.assertEqual(targets["gog-en-1.1.2.3"]["edition"], "gog")
        self.assertEqual(targets["steam-en-1.1.2.3"]["edition"], "steam")
        self.assertEqual(data["translation"]["tags"],
                         ["fan", "community", "ai-assist"])
        self.assertEqual(data["translation"]["review_status"], "preview")
        self.assertEqual(data["translation"]["source_lang"], "en.gog_1.1.2.3")
        self.assertEqual(len(data["source"]["sha256"]), 64)
        self.assertNotIn("manifest.json", [x["path"] for x in data["files"]])
        self.assertIn("PR2Localization/packs/zh.txt",
                      [x["path"] for x in data["files"]])
        self.assertEqual(data["counts"]["files"], len(data["files"]))

    def test_manifest_verifies_and_detects_changed_file(self):
        release_manifest.write_release_manifest(
            self.stage, "zh", "v1.0.0", "noto")
        ok, errors = release_manifest.verify_release_manifest(self.stage)
        self.assertTrue(ok, errors)
        with open(os.path.join(self.stage, "PR2Localization", "packs",
                               "zh.txt"), "a", encoding="utf-8") as fh:
            fh.write("0x2 = 改动\n")
        ok, errors = release_manifest.verify_release_manifest(self.stage)
        self.assertFalse(ok)
        self.assertTrue(any("SHA-256 不一致" in e for e in errors))

    def test_manifest_detects_unlisted_file(self):
        release_manifest.write_release_manifest(
            self.stage, "zh", "v1.0.0", "noto")
        self._write("PR2Localization/extra.txt", "extra\n")
        ok, errors = release_manifest.verify_release_manifest(self.stage)
        self.assertFalse(ok)
        self.assertTrue(any("清单未登记" in e for e in errors))

    def test_manifest_rejects_path_escape(self):
        path = release_manifest.write_release_manifest(
            self.stage, "zh", "v1.0.0", "noto")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["files"].append({
            "path": "../outside.txt",
            "kind": "data",
            "size": 1,
            "sha256": "0" * 64,
        })
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(data, ensure_ascii=False))
        ok, errors = release_manifest.verify_release_manifest(self.stage)
        self.assertFalse(ok)
        self.assertTrue(any("路径越界" in e for e in errors))

    def test_translation_records_pack_head_and_delta(self):
        """清单里的 pack 段是**从包里读回来的**，与玩家看到的是同一份数据。"""
        self._write(
            "PR2Localization/packs/zh.txt",
            "# pack-meta alias=简体中文\n# pack-meta min_runtime=1\n"
            "# pack-meta version=1.0.0\n# pack-meta entries=2\n"
            "# pack-meta untranslated=0\n# pack-meta scope=union\n"
            "# pack-meta digest=9cfa2931c1c2\n0x1 = 测试\n",
        )
        delta = {"baseline": "release-v0.9.1", "kind": "initial"}
        path = release_manifest.write_release_manifest(
            self.stage, "zh", "v1.0.0", "noto", deltas={"zh": delta})
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        entry = data["translations"][0]
        self.assertEqual(entry["lang"], "zh")
        self.assertEqual(entry["pack"], {
            "alias": "简体中文",
            "version": "1.0.0",
            "entries": 2,
            "untranslated": 0,
            "scope": "union",
            "digest": "9cfa2931c1c2",
        })
        self.assertEqual(entry["delta"], delta)
        # translation 是第一个语言的同一份内容，旧读法不受影响。
        self.assertEqual(data["translation"]["pack"], entry["pack"])

    def test_broken_digest_is_not_recorded(self):
        # 头被写坏时宁可不记，也不把 `../../etc` 当成摘要写进清单。
        self._write(
            "PR2Localization/packs/zh.txt",
            "# pack-meta alias=简体中文\n# pack-meta digest=../../etc\n"
            "# pack-meta entries=abc\n0x1 = 测试\n",
        )
        path = release_manifest.write_release_manifest(
            self.stage, "zh", "v1.0.0", "noto")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        pack = data["translations"][0]["pack"]
        self.assertEqual(pack["alias"], "简体中文")
        self.assertNotIn("digest", pack)
        self.assertNotIn("entries", pack)


if __name__ == "__main__":
    unittest.main()
