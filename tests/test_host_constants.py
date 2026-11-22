# -*- coding: utf-8 -*-
"""宿主 DLL 常量必须三处一致。

原版 ``Ascaron.Logging-2.6.dll`` 的大小和 SHA-256 同时被三份实现硬编码：

- Rust 启动器 ``pr2_common/src/host.rs``（判断根目录是原版还是代理）；
- Python ``pr2ctl/steam_host.py``（安装器/工具链）；
- 发行包里的 ``PR2HostMount.ps1``（真正执行替换的那一份）。

这三处谁也读不到谁：Rust 编译进 exe，PS1 随包发出去由 Windows PowerShell
执行，Python 只在开发机上跑。任何一处改错都不会有编译错误，只会让某一侧的
「是不是原版」判断失真 —— 于是可能把未知文件当原版备份，或者拒绝还原一份
本来正确的原版。这个测试就是那条唯一的连接线：只要有一处落后于其它两处，
立刻失败。
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST_RS = os.path.join(ROOT, "src", "injector-rs", "pr2_common", "src", "host.rs")
STEAM_HOST_PY = os.path.join(ROOT, "src", "tools", "install", "pr2ctl", "steam_host.py")
MOUNT_PS1 = os.path.join(ROOT, "src", "tools", "install", "PR2HostMount.ps1")
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


def python_size():
    return int(_search(r"HOST_ORIGINAL_SIZE\s*=\s*(\d+)",
                       _read(STEAM_HOST_PY), STEAM_HOST_PY, "HOST_ORIGINAL_SIZE"))


def python_sha():
    return _search(r"HOST_ORIGINAL_SHA256\s*=\s*\(\s*\"(%s)\"\s*\)" % SHA_RE,
                   _read(STEAM_HOST_PY), STEAM_HOST_PY, "HOST_ORIGINAL_SHA256")


def ps1_size():
    return int(_search(r"\$ExpectedSize\s*=\s*(\d+)",
                       _read(MOUNT_PS1), MOUNT_PS1, "$ExpectedSize"))


def ps1_sha():
    return _search(r"\$ExpectedSha\s*=\s*'(%s)'" % SHA_RE,
                   _read(MOUNT_PS1), MOUNT_PS1, "$ExpectedSha")


class TestHostConstants(unittest.TestCase):
    def test_size_matches_across_implementations(self):
        sizes = {"host.rs": rust_size(), "steam_host.py": python_size(),
                 "PR2HostMount.ps1": ps1_size()}
        self.assertEqual(len(set(sizes.values())), 1,
                         "原版宿主 DLL 大小不一致：%s" % sizes)
        size = next(iter(sizes.values()))
        self.assertGreater(size, 0)
        self.assertLess(size, 10 * 1024 * 1024, "大小看着不像一个 DLL")

    def test_sha_matches_across_implementations(self):
        shas = {"host.rs": rust_sha(), "steam_host.py": python_sha(),
                "PR2HostMount.ps1": ps1_sha()}
        # 三处统一用大写：PS1 用 .ToUpperInvariant()，Rust 手写大写，Python 也大写。
        uppercase = {name: value.upper() for name, value in shas.items()}
        self.assertEqual(len(set(uppercase.values())), 1,
                         "原版宿主 DLL 的 SHA-256 不一致：%s" % shas)
        digest = next(iter(uppercase.values()))
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
        """文件名同样三处硬编码；拼错一个就会去校验一个不存在的文件。"""
        dll = "Ascaron.Logging-2.6.dll"
        orig = "Ascaron.Logging-2.6.orig.dll"
        self.assertIn('HOST_DLL: &str = "%s"' % dll, _read(HOST_RS))
        self.assertIn('HOST_ORIG: &str = "%s"' % orig, _read(HOST_RS))
        self.assertIn('HOST_DLL = "%s"' % dll, _read(STEAM_HOST_PY))
        self.assertIn('HOST_ORIG = "%s"' % orig, _read(STEAM_HOST_PY))
        ps1 = _read(MOUNT_PS1)
        self.assertIn("$HostDll = '%s'" % dll, ps1)
        self.assertIn("$OrigDll = '%s'" % orig, ps1)


if __name__ == "__main__":
    unittest.main()
