# -*- coding: utf-8 -*-
"""Steam 宿主 DLL 的替换动作：校验、备份、原子替换、还原。

原版 DLL 的期望大小与哈希在真实环境里固定（11,776 B / 0568EC65…），
这里不造那个文件，而是把常量换成合成样本，专测「动作」本身的约束：

- 只有内容等于原版才允许备份和替换；
- 未知 DLL 一律拒绝，且不动文件；
- 代理写到临时文件、校验通过才换名，失败时根目录仍是原来那份；
- 还原只接受本工具代理，还原后哈希必须回到原版。
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from install.pr2ctl import steam_host  # noqa: E402


def _sha(data):
    import hashlib
    return hashlib.sha256(data).hexdigest().upper()


class SteamHostSwapTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pr2-host-")
        self.original = b"PR2 original host dll" + bytes(64)
        self.proxy = b"PR2 localization proxy" + bytes(64)
        self.orig_path = os.path.join(self.dir, steam_host.HOST_DLL)
        with open(self.orig_path, "wb") as fh:
            fh.write(self.original)
        self.proxy_path = os.path.join(self.dir, "proxy-source.dll")
        with open(self.proxy_path, "wb") as fh:
            fh.write(self.proxy)

        # 把「原版」的判定换成合成样本。
        self._old = (steam_host.HOST_ORIGINAL_SIZE, steam_host.HOST_ORIGINAL_SHA256)
        steam_host.HOST_ORIGINAL_SIZE = len(self.original)
        steam_host.HOST_ORIGINAL_SHA256 = _sha(self.original)

    def tearDown(self):
        steam_host.HOST_ORIGINAL_SIZE, steam_host.HOST_ORIGINAL_SHA256 = self._old
        shutil.rmtree(self.dir, ignore_errors=True)

    def _read(self, name):
        with open(os.path.join(self.dir, name), "rb") as fh:
            return fh.read()

    def test_swap_backs_up_and_replaces(self):
        info = steam_host.swap_host(self.dir, self.proxy_path)
        self.assertEqual(info["state"], "original")
        self.assertEqual(info["proxy_sha256"], _sha(self.proxy))
        self.assertEqual(self._read(steam_host.HOST_DLL), self.proxy)
        self.assertEqual(self._read(steam_host.HOST_ORIG), self.original)
        self.assertEqual(
            self._read(os.path.join(steam_host.HOST_BACKUP_DIR, steam_host.HOST_DLL)),
            self.original)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, steam_host.HOST_MANIFEST)))
        self.assertEqual(steam_host.status(self.dir)[0], "mounted")
        self.assertFalse(os.path.exists(os.path.join(self.dir, steam_host.HOST_DLL + ".new")))

    def test_swap_is_idempotent(self):
        steam_host.swap_host(self.dir, self.proxy_path)
        before = self._read(steam_host.HOST_DLL)
        info = steam_host.swap_host(self.dir, self.proxy_path)
        self.assertEqual(info["state"], "mounted")
        self.assertEqual(self._read(steam_host.HOST_DLL), before)
        self.assertEqual(self._read(steam_host.HOST_ORIG), self.original)

    def test_has_host_is_the_only_gate(self):
        # 两版都带同名 DLL，能不能挂只看它在不在，与版别无关。
        self.assertTrue(steam_host.has_host(self.dir))
        os.remove(self.orig_path)
        self.assertFalse(steam_host.has_host(self.dir))

    def test_manifest_has_no_edition_field(self):
        # 两版同路后版别不决定任何行为，清单里不再记 edition；
        # 这里锁住键集合，防止有人把没人读的字段加回来。
        steam_host.swap_host(self.dir, self.proxy_path)
        import json
        with open(os.path.join(self.dir, steam_host.HOST_MANIFEST),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(sorted(data), ["backup", "host", "original_sha256",
                                        "proxy_sha256"])

    def test_unknown_dll_is_refused_untouched(self):
        unknown = b"someone else's mod" + bytes(64)
        with open(self.orig_path, "wb") as fh:
            fh.write(unknown)
        with self.assertRaises(steam_host.HostError):
            steam_host.swap_host(self.dir, self.proxy_path)
        self.assertEqual(self._read(steam_host.HOST_DLL), unknown)
        self.assertFalse(os.path.exists(os.path.join(self.dir, steam_host.HOST_ORIG)))
        self.assertFalse(os.path.exists(os.path.join(self.dir, steam_host.HOST_DLL + ".new")))

    def test_restore_returns_original(self):
        steam_host.swap_host(self.dir, self.proxy_path)
        self.assertEqual(steam_host.restore_host(self.dir, self.proxy_path), "restored")
        self.assertEqual(self._read(steam_host.HOST_DLL), self.original)
        self.assertFalse(os.path.isfile(os.path.join(self.dir, steam_host.HOST_MANIFEST)))
        self.assertEqual(steam_host.status(self.dir)[0], "original")

    def test_restore_refuses_foreign_dll(self):
        with open(self.orig_path, "wb") as fh:
            fh.write(self.proxy)
        with self.assertRaises(steam_host.HostError):
            steam_host.restore_host(self.dir, self.proxy_path)
        self.assertEqual(self._read(steam_host.HOST_DLL), self.proxy)


if __name__ == "__main__":
    unittest.main()
