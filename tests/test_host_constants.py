# -*- coding: utf-8 -*-
"""宿主 DLL 的原版哈希只在 Rust 一处硬编码，文档抄的值必须与它一致。

替换/还原的唯一实现在 ``pr2_common/src/host.rs``；Python 侧
（``pr2ctl/steam_host.py``）只保留文件名做只读判断，不再保存第二份
大小/哈希。这里仍有两条连接线：

- 文档里抄了原版哈希的地方，必须等于 Rust 常量；
- Python 用来找根目录 DLL 的文件名，必须与 Rust 一致。
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST_RS = os.path.join(ROOT, "src", "injector-rs", "pr2_common", "src", "host.rs")
STEAM_HOST_PY = os.path.join(ROOT, "src", "tools", "install", "pr2ctl", "steam_host.py")
DOC_EDITION = os.path.join(ROOT, "docs", "发行版.md")

SHA_RE = r"[0-9A-Fa-f]{64}"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _search(pattern, text, path, what):
    match = re.search(pattern, text, re.S)
    if not match:
        raise AssertionError("%s 里找不到 %s（正则 %s）"
                             % (os.path.relpath(path, ROOT), what, pattern))
    return match.group(1)


def rust_size():
    return int(_search(r"HOST_ORIGINAL_SIZE\s*:\s*u64\s*=\s*(\d+)",
                       _read(HOST_RS), HOST_RS, "HOST_ORIGINAL_SIZE"))


def rust_sha():
    return _search(r"HOST_ORIGINAL_SHA256\s*:\s*&str\s*=\s*\"(%s)\"" % SHA_RE,
                   _read(HOST_RS), HOST_RS, "HOST_ORIGINAL_SHA256")


class TestHostConstants(unittest.TestCase):
    def test_size_is_sane(self):
        size = rust_size()
        self.assertGreater(size, 0)
        self.assertLess(size, 10 * 1024 * 1024, "大小看着不像一个 DLL")

    def test_sha_is_uppercase(self):
        digest = rust_sha()
        self.assertEqual(digest, digest.upper(),
                         "Rust 常量统一用大写，避免与文档比对时大小写漂移")
        self.assertEqual(len(digest), 64)
        self.assertRegex(digest, r"^[0-9A-F]{64}$")

    def test_docs_do_not_quote_a_stale_hash(self):
        """文档里凡是抄了这个哈希的地方，都必须是当前的值。"""
        text = _read(DOC_EDITION)
        found = re.findall(r"\b0?5[0-9A-Fa-f]{10,63}\b", text)
        for value in found:
            self.assertEqual(value.upper(), rust_sha().upper(),
                             "docs\\发行版.md 里的哈希已过期：%s" % value)

    def test_host_file_names_match(self):
        """文件名同样两处硬编码；拼错一个就会去校验一个不存在的文件。"""
        dll = "Ascaron.Logging-2.6.dll"
        self.assertIn('HOST_DLL: &str = "%s"' % dll, _read(HOST_RS))
        self.assertIn('HOST_DLL = "%s"' % dll, _read(STEAM_HOST_PY))
        # Python 只保留根目录文件名；.orig / host-backup 由 Rust 自己算。
        self.assertNotIn("HOST_ORIG", _read(STEAM_HOST_PY))
        self.assertNotIn("HOST_ORIGINAL_SHA256", _read(STEAM_HOST_PY))


if __name__ == "__main__":
    unittest.main()
