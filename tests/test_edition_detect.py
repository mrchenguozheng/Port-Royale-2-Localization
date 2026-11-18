# -*- coding: utf-8 -*-
"""版本判断：GOG 目录里也有 Ascaron.Logging-2.6.dll，不能按存在性判成 Steam。"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

from install.pr2ctl import steam_host  # noqa: E402


class TestEditionDetect(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pr2-edition-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, name, data=b"x"):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_gog_marker_wins_over_host_dll(self):
        self._write("goggame-1207658698.info", b"{}")
        self._write(steam_host.HOST_DLL, b"original")
        self._write("PR2.exe", b"exe")
        self.assertEqual(steam_host.detect_edition(self.dir), "gog")

    def test_unknown_build_with_host_dll_stays_steam(self):
        self._write(steam_host.HOST_DLL, b"original")
        self._write("PR2.exe", b"exe")
        self.assertEqual(steam_host.detect_edition(self.dir), "steam")

    def test_plain_dir_is_gog(self):
        self._write("PR2.exe", b"exe")
        self.assertEqual(steam_host.detect_edition(self.dir), "gog")


if __name__ == "__main__":
    unittest.main()
