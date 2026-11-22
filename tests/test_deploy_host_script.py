# -*- coding: utf-8 -*-
"""部署清单必须带 PR2HostMount.ps1：还原原版只能靠它。"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "install"))

deploy = importlib.import_module("pr2ctl.deploy")  # noqa: E402


class TestDeployHostMountScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2-host-script-")
        self.runtime = os.path.join(self.tmp, "runtime")
        self.target = os.path.join(self.tmp, "target")
        os.makedirs(self.runtime)
        os.makedirs(os.path.join(self.target, "PR2Localization", "packs"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _with(self, src, fn):
        old = (deploy.RUNTIME, deploy.FLAT_FILES, deploy.HOST_MOUNT_SRC)
        try:
            deploy.RUNTIME = self.runtime
            deploy.FLAT_FILES = ()
            deploy.HOST_MOUNT_SRC = src
            return fn()
        finally:
            deploy.RUNTIME, deploy.FLAT_FILES, deploy.HOST_MOUNT_SRC = old

    def test_repo_has_the_script(self):
        # 常量写的路径必须真指向仓库里的脚本，否则部署会静默少一个文件。
        self.assertTrue(os.path.isfile(deploy.HOST_MOUNT_SRC),
                        deploy.HOST_MOUNT_SRC)

    def test_steps_include_script_at_game_root(self):
        src = os.path.join(self.tmp, "PR2HostMount.ps1")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("# mount\n")
        steps = self._with(
            src, lambda: deploy.deploy_steps(self.target, [], edition="gog"))
        script_steps = [(s, dst) for _label, s, dst in steps
                        if dst and os.path.basename(dst) == "PR2HostMount.ps1"]
        self.assertEqual(len(script_steps), 1)
        self.assertEqual(script_steps[0][0], src)
        self.assertEqual(os.path.dirname(script_steps[0][1]), self.target)

    def test_missing_script_is_not_a_step(self):
        missing = os.path.join(self.tmp, "nope.ps1")
        steps = self._with(
            missing,
            lambda: deploy.deploy_steps(self.target, [], edition="gog"))
        self.assertFalse([1 for _label, _s, dst in steps
                          if dst and os.path.basename(dst) == "PR2HostMount.ps1"])

    def test_proxy_lands_in_localization_host_dir(self):
        # 启动器只认 PR2Localization\host\ 里的代理；部署不送到位，
        # 脚本就会回退到根目录的原版，挂载变成空操作。
        proxy = os.path.join(self.runtime, "Ascaron.Logging-2.6.dll")
        with open(proxy, "wb") as fh:
            fh.write(b"proxy")
        steps = self._with(
            os.path.join(self.tmp, "nope.ps1"),
            lambda: deploy.deploy_steps(self.target, [], edition="gog"))
        rel = [os.path.relpath(dst, self.target).replace("\\", "/")
               for _label, _src, dst in steps if dst]
        self.assertIn("PR2Localization/host/Ascaron.Logging-2.6.dll", rel)


if __name__ == "__main__":
    unittest.main()
