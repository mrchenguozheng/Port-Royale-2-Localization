# -*- coding: utf-8 -*-
"""部署期宿主动作只调用启动器，不在 Python 里重算一遍替换算法。"""

import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "install"))

from pr2ctl import host_action, steam_host  # noqa: E402


class TestHostAction(unittest.TestCase):
    def setUp(self):
        self.target = tempfile.mkdtemp(prefix="pr2-host-action-")
        with open(os.path.join(self.target, "PR2Localization.exe"), "wb") as fh:
            fh.write(b"MZ")

    def tearDown(self):
        shutil.rmtree(self.target, ignore_errors=True)

    def test_python_side_has_no_replacement_algorithm(self):
        # 替换/还原只能有一份实现（Rust）；Python 再长出 swap_host 之类的名字，
        # 就说明部署期又分叉出一套「校验、备份、换名」。
        for name in ("swap_host", "prepare_mount", "restore_host",
                     "write_manifest", "mount_host"):
            self.assertFalse(hasattr(steam_host, name),
                             "steam_host.py 不该再有 %s" % name)

    def test_mount_runs_launcher_in_game_dir(self):
        proc = types.SimpleNamespace(returncode=0, stdout="")
        with mock.patch.object(host_action.subprocess, "run",
                               return_value=proc) as run:
            ok, detail = host_action.mount(self.target)
        self.assertTrue(ok)
        self.assertEqual(detail, "")
        args, kwargs = run.call_args
        self.assertEqual(args[0][0],
                         os.path.join(self.target, "PR2Localization.exe"))
        self.assertEqual(args[0][1], "--mount")
        self.assertEqual(kwargs["cwd"], self.target)

    def test_failure_reports_host_log_tail(self):
        log_dir = os.path.join(self.target, "PR2Localization", "logs")
        os.makedirs(log_dir)
        lines = ["[PR2Loc] line %d" % i for i in range(20)]
        with open(os.path.join(log_dir, "host.log"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        proc = types.SimpleNamespace(returncode=1, stdout="")
        with mock.patch.object(host_action.subprocess, "run",
                               return_value=proc):
            ok, detail = host_action.mount(self.target)
        self.assertFalse(ok)
        self.assertIn("line 19", detail)
        self.assertNotIn("line 0", detail)

    def test_missing_launcher_is_reported(self):
        os.remove(os.path.join(self.target, "PR2Localization.exe"))
        ok, detail = host_action.restore(self.target)
        self.assertFalse(ok)
        self.assertIn("PR2Localization.exe", detail)


if __name__ == "__main__":
    unittest.main()
