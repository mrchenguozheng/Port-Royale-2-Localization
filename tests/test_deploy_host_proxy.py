# -*- coding: utf-8 -*-
"""部署只送宿主代理，不再送任何脚本。"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "install"))

deploy = importlib.import_module("pr2ctl.deploy")  # noqa: E402


class TestDeployHostProxy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr2-host-proxy-")
        self.runtime = os.path.join(self.tmp, "runtime")
        self.target = os.path.join(self.tmp, "target")
        os.makedirs(self.runtime)
        os.makedirs(os.path.join(self.target, "PR2Localization", "packs"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _with(self, fn):
        old = (deploy.RUNTIME, deploy.FLAT_FILES)
        try:
            deploy.RUNTIME = self.runtime
            deploy.FLAT_FILES = ()
            return fn()
        finally:
            deploy.RUNTIME, deploy.FLAT_FILES = old

    def test_repo_has_no_mount_script(self):
        # 挂载已收进启动器；仓库里再冒出 ps1 就说明旧路径又回来了。
        self.assertFalse(
            os.path.isfile(os.path.join(
                ROOT, "src", "tools", "install", "PR2HostMount.ps1")))

    def test_steps_never_include_scripts(self):
        steps = self._with(
            lambda: deploy.deploy_steps(self.target, [], edition="gog"))
        scripts = [dst for _label, _src, dst in steps
                   if dst and dst.lower().endswith(".ps1")]
        self.assertFalse(scripts, "部署清单不该再带脚本：%s" % scripts)

    def test_proxy_lands_in_localization_host_dir(self):
        # 启动器只认 PR2Localization\host\ 里的代理；部署不送到位，
        # 挂载就只能回退到根目录的原版，等于没挂。
        proxy = os.path.join(self.runtime, "Ascaron.Logging-2.6.dll")
        with open(proxy, "wb") as fh:
            fh.write(b"proxy")
        steps = self._with(
            lambda: deploy.deploy_steps(self.target, [], edition="gog"))
        rel = [os.path.relpath(dst, self.target).replace("\\", "/")
               for _label, _src, dst in steps if dst]
        self.assertIn("PR2Localization/host/Ascaron.Logging-2.6.dll", rel)


if __name__ == "__main__":
    unittest.main()
