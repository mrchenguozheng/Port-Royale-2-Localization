# -*- coding: utf-8 -*-
"""发行包布局：Steam 代理不能占根目录原名。

根目录的 ``Ascaron.Logging-2.6.dll`` 是游戏原版。包里的代理一旦同名解压，
原版就没有了 —— 既不能校验，也没有可回滚的备份。所以代理必须落在
``PR2Localization\\host\\``，由挂载动作在确认原版之后换进根目录。
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import make_release  # noqa: E402


class TestSteamLayout(unittest.TestCase):
    def setUp(self):
        self.stage = tempfile.mkdtemp(prefix="pr2-layout-stage-")
        self.runtime = tempfile.mkdtemp(prefix="pr2-layout-runtime-")
        for name in ("PR2Localization.exe", "PR2LocalizationGUI.exe",
                     "PR2LocalizationCore.dll", make_release.HOST_DLL):
            with open(os.path.join(self.runtime, name), "wb") as fh:
                fh.write(b"MZ fake " + name.encode("ascii"))
        self._old_runtime = make_release.RUNTIME
        make_release.RUNTIME = self.runtime

    def tearDown(self):
        make_release.RUNTIME = self._old_runtime
        shutil.rmtree(self.stage, ignore_errors=True)
        shutil.rmtree(self.runtime, ignore_errors=True)

    def test_steam_proxy_is_not_at_root(self):
        make_release.copy_runtime(self.stage, "steam", lambda _m: None)
        proxy = os.path.join(self.stage, make_release.HOST_PROXY_REL)
        self.assertTrue(os.path.isfile(proxy), "代理应落在 PR2Localization\\host")
        self.assertFalse(
            os.path.exists(os.path.join(self.stage, make_release.HOST_DLL)),
            "根目录不能出现与原版同名的 DLL")
        self.assertTrue(os.path.isfile(
            os.path.join(self.stage, make_release.HOST_MOUNT_SCRIPT)))

    def test_gog_pack_has_neither_proxy_nor_script(self):
        make_release.copy_runtime(self.stage, "gog", lambda _m: None)
        self.assertFalse(os.path.exists(
            os.path.join(self.stage, make_release.HOST_PROXY_REL)))
        self.assertFalse(os.path.exists(
            os.path.join(self.stage, make_release.HOST_MOUNT_SCRIPT)))


class TestUiLayout(unittest.TestCase):
    """界面文案只发 ui.default.ini；旧的按语言 ini 不再进包。"""

    def test_only_default_ui_is_shipped(self):
        ui = os.path.join(ROOT, "src", "injector-rs", "ui")
        self.assertTrue(os.path.isfile(os.path.join(ui, "ui.default.ini")))
        for name in ("en.ini", "ja.ini", "zh.ini"):
            self.assertFalse(
                os.path.exists(os.path.join(ui, name)),
                "旧布局的 %s 还留在源码目录；文案已统一到 ui.default.ini" % name)

    def test_default_ui_has_restore_keys(self):
        path = os.path.join(ROOT, "src", "injector-rs", "ui", "ui.default.ini")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for key in ("button.restore", "status.restored", "status.restore_gog",
                    "confirm.restore", "error.restore_failed"):
            self.assertIn("\n%s=" % key, text.replace("\r\n", "\n"),
                          "ui.default.ini 缺 %s" % key)
        # 还原失败要把退出码和落盘日志一起塞进弹框，两个占位符少一个就白搭。
        self.assertIn("error.restore_failed=", text)
        line = [ln for ln in text.replace("\r\n", "\n").split("\n")
                if ln.startswith("error.restore_failed=")][0]
        self.assertIn("%lu", line)
        self.assertIn("%s", line)

    def test_build_copies_default_ui_only(self):
        script = os.path.join(ROOT, "src", "build_injector.ps1")
        with open(script, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("ui.default.ini", text)
        # 旧写法是逐个语言 Copy-Item 到 runtime；现在只发默认文件，旧文件被清掉。
        self.assertNotIn("Copy-Item -LiteralPath $ini", text)


if __name__ == "__main__":
    unittest.main()
