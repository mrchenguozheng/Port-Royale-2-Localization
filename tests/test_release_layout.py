# -*- coding: utf-8 -*-
"""发行包布局：一个包同时面向 GOG 与 Steam，Steam 代理不能占根目录原名。

根目录的 ``Ascaron.Logging-2.6.dll`` 是游戏原版。包里的代理一旦同名解压，
原版就没有了 —— 既不能校验，也没有可回滚的备份。所以代理必须落在
``PR2Localization\\host\\``，由挂载动作在确认原版之后换进根目录。

合并包以后 GOG 也会带着代理；判版走标记文件，GOG 侧从不执行注入。
"""

import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "pack"))

import make_release  # noqa: E402


class TestUniversalLayout(unittest.TestCase):
    def setUp(self):
        self.stage = tempfile.mkdtemp(prefix="pr2-layout-stage-")
        self.runtime = tempfile.mkdtemp(prefix="pr2-layout-runtime-")
        for name in ("PR2Localization.exe", "PR2LocalizationGUI.exe",
                     "PR2LocalizationCore.dll", make_release.HOST_DLL,
                     "VERSION.dll"):
            with open(os.path.join(self.runtime, name), "wb") as fh:
                fh.write(b"MZ fake " + name.encode("ascii"))
        self._old_runtime = make_release.RUNTIME
        make_release.RUNTIME = self.runtime

    def tearDown(self):
        make_release.RUNTIME = self._old_runtime
        shutil.rmtree(self.stage, ignore_errors=True)
        shutil.rmtree(self.runtime, ignore_errors=True)

    def test_pack_has_both_editions_but_no_root_dll(self):
        make_release.copy_runtime(self.stage, lambda _m: None)
        proxy = os.path.join(self.stage, make_release.HOST_PROXY_REL)
        self.assertTrue(os.path.isfile(proxy), "代理应落在 PR2Localization\\host")
        self.assertFalse(
            os.path.exists(os.path.join(self.stage, "PR2HostMount.ps1")),
            "发行包不再带挂载脚本：挂载已收进启动器")
        self.assertFalse(
            [n for n in make_release.FLAT_PACKAGE if n.lower().endswith(".ps1")],
            "运行期不再依赖任何 PowerShell 脚本")
        self.assertFalse(
            os.path.exists(os.path.join(self.stage, make_release.HOST_DLL)),
            "根目录不能出现与原版同名的 DLL")

    def test_license_sits_in_docs_not_fonts_or_root(self):
        """许可文本放 PR2Localization\\docs\\：字体目录会被游戏按 *.* 扫描。"""
        make_release.copy_license(self.stage, lambda _m: None)
        docs_ofl = os.path.join(
            self.stage, make_release.DATA_DIR, "docs", "OFL.txt")
        self.assertTrue(os.path.isfile(docs_ofl))
        self.assertFalse(os.path.exists(os.path.join(
            self.stage, make_release.DATA_DIR, "fonts", "OFL.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.stage, "OFL.txt")))

    def test_ja_only_title_fonts_are_squeezed(self):
        """日文只压标题字重到 0.78；正文原样复制，不做压缩。"""
        self.assertEqual(make_release.JA_TITLE_FONT_SQUEEZE, 0.78)
        self.assertEqual(make_release.ja_font_squeeze_scale(
            "NotoSerifJP-Black.ttf"), 0.78)
        self.assertEqual(make_release.ja_font_squeeze_scale(
            "NotoSerifJP-Bold.ttf"), 0.78)
        self.assertIsNone(make_release.ja_font_squeeze_scale(
            "NotoSansJP-Regular.ttf"))

    def test_no_version_dll_fallback(self):
        """VERSION.dll 代理是历史路线，GOG 直启时会被解析到 SysWOW64；不进包。"""
        make_release.copy_runtime(self.stage, lambda _m: None)
        self.assertNotIn("VERSION.dll", make_release.FLAT_PACKAGE)
        self.assertFalse(os.path.exists(os.path.join(self.stage, "VERSION.dll")))


class TestUiLayout(unittest.TestCase):
    """界面文案按语言分文件；发行包带全部语言文件，另存一份默认兜底。"""

    LANGS = ("zh", "zh-TW", "zh-HK", "ja", "ko", "ru", "pl", "pt-BR",
             "de", "es", "fr", "it")

    def _ui_dir(self):
        return os.path.join(ROOT, "src", "injector-rs", "ui")

    def _values(self, path):
        values = {}
        with open(path, encoding="utf-8") as fh:
            for line in fh.read().replace("\r\n", "\n").split("\n"):
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("["):
                    continue
                key, sep, value = line.partition("=")
                if sep:
                    values[key.strip()] = value.strip()
        return values

    def test_language_ui_files_exist_and_legacy_gone(self):
        ui = self._ui_dir()
        # 源码里不再有 ui.default.ini：简体中文就是 ui.zh.ini，运行时默认文件
        # 由 build_injector.ps1 从它生成，避免同一套中文文案存两份。
        self.assertFalse(os.path.isfile(os.path.join(ui, "ui.default.ini")),
                         "源码不该再有 ui.default.ini 副本（默认文件构建时生成）")
        for lang in self.LANGS:
            self.assertTrue(
                os.path.isfile(os.path.join(ui, "ui.%s.ini" % lang)),
                "缺 %s 的界面文案 ui.%s.ini" % (lang, lang))
        for name in ("en.ini", "ja.ini", "zh.ini"):
            self.assertFalse(
                os.path.exists(os.path.join(ui, name)),
                "旧布局的 %s 还留在源码目录；新文案是 ui.<lang>.ini" % name)

    def test_language_ui_keys_and_placeholders_match(self):
        """各语言必须是同一套 key、同一组占位符，少一个就会显示成 key 名或丢字段。"""
        base = self._values(os.path.join(self._ui_dir(), "ui.zh.ini"))
        for lang in self.LANGS:
            values = self._values(
                os.path.join(self._ui_dir(), "ui.%s.ini" % lang))
            self.assertEqual(sorted(values), sorted(base),
                             "ui.%s.ini 的 key 与 ui.zh.ini 不一致" % lang)
            for key, text in base.items():
                self.assertEqual(
                    re.findall(r"%[a-z]+", values[key]),
                    re.findall(r"%[a-z]+", text),
                    "ui.%s.ini 的 %s 占位符与简体中文不一致" % (lang, key))

    def test_build_generates_default_from_zh(self):
        """运行时默认文件必须来自 ui.zh.ini，不能另存一份中文副本。"""
        script = os.path.join(ROOT, "src", "build_injector.py")
        with open(script, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('"ui.zh.ini"', text)
        self.assertIn('"ui.default.ini"', text)
        self.assertIn("shutil.copy2(zh", text)

    def test_release_copies_all_language_files_and_default(self):
        src = tempfile.mkdtemp(prefix="pr2-ui-src-")
        stage = tempfile.mkdtemp(prefix="pr2-ui-stage-")
        try:
            os.makedirs(os.path.join(src, "ui"))
            for lang, text in (("zh", "title=中文"), ("de", "title=Deutsch"),
                               ("pl", "title=Polski")):
                path = os.path.join(src, "ui", "ui.%s.ini" % lang)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("[gui]\n%s\n" % text)
            make_release.copy_ui(stage, os.path.join(src, "ui"), "de",
                                 lambda _m: None)
            out = os.path.join(stage, make_release.DATA_DIR, "ui")
            self.assertEqual(
                sorted(os.listdir(out)),
                ["ui.de.ini", "ui.default.ini", "ui.pl.ini", "ui.zh.ini"])
            with open(os.path.join(out, "ui.default.ini"), encoding="utf-8") as fh:
                self.assertIn("title=Deutsch", fh.read())
            with self.assertRaises(FileNotFoundError):
                make_release.copy_ui(stage, os.path.join(src, "ui"), "fr",
                                     lambda _m: None)
        finally:
            shutil.rmtree(src, ignore_errors=True)
            shutil.rmtree(stage, ignore_errors=True)

    def test_build_copies_all_language_ui_files(self):
        script = os.path.join(ROOT, "src", "build_injector.py")
        with open(script, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('name.startswith("ui.")', text)
        self.assertIn("name.endswith(\".ini\")", text)
        # 旧布局的 en/ja/zh.ini 仍要从 runtime 清掉，否则旧安装带过期文案。
        self.assertIn('for stale in ("en.ini", "ja.ini", "zh.ini")', text)


    def test_default_ui_has_version_keys(self):
        """副标题与状态框的版本文案：ini 与 Rust 内置回退必须成对，占位符也要对得上。

        ini 少一个 key 时旧安装的界面会直接显示 key 名；Rust 少一个时旧包
        （没有新 key 的 ui.default.ini）会显示成 key 名。两边都得有。
        """
        ini = os.path.join(ROOT, "src", "injector-rs", "ui", "ui.zh.ini")
        with open(ini, encoding="utf-8") as fh:
            text = fh.read().replace("\r\n", "\n")

        def line_for(key):
            return [ln for ln in text.split("\n") if ln.startswith(key + "=")][0]

        self.assertEqual(line_for("subtitle.version").count("%"), 2,
                         "subtitle.version 要同时填运行时版本与发行版本")
        self.assertIn("%d", line_for("subtitle.version"))
        self.assertIn("%s", line_for("subtitle.version"))
        self.assertEqual(line_for("status.count_pack").count("%"), 2,
                         "status.count_pack 要填包数量与当前包名")
        # 状态框第二行：条目数、未译数、摘要。三条占位符缺一条就会少显示一项。
        self.assertEqual(line_for("status.pack_stats").count("%"), 2,
                         "status.pack_stats 要填条目数与未译数")
        detail = line_for("status.pack_detail")
        self.assertEqual(detail.count("%"), 3,
                         "status.pack_detail 要填条目数、未译数与摘要")
        self.assertIn("%s", detail)
        # overrides\ 是玩家自己的本机补丁，界面不报它的条数：这个 key 不该存在。
        self.assertNotIn("status.pack_overrides", text,
                         "状态框不统计覆盖条数，ini 里不该有 status.pack_overrides")

        rust = os.path.join(ROOT, "src", "injector-rs", "pr2_launcher_gui",
                            "src", "strings.rs")
        with open(rust, encoding="utf-8") as fh:
            builtin = fh.read()
        for key in ("subtitle.version", "status.count_pack",
                    "status.pack_stats", "status.pack_detail"):
            self.assertIn('"%s"' % key, builtin,
                          "strings.rs 的 BUILTIN 缺 %s" % key)
        self.assertNotIn("status.pack_overrides", builtin,
                         "启动器不再统计覆盖条数，BUILTIN 里不该留这个 key")
        self.assertNotIn("status.restore_gog", builtin,
                         "还原不再按版别分叉，BUILTIN 里不该留 GOG 专用文案")


class TestBundles(unittest.TestCase):
    """分组要覆盖全部发行语言，显示名要和 packs/<lang>.toml 的 alias 一致。

    ``LABELS`` 在 make_release.py 里另存一份，与 packs 的 alias 是两份数据：
    新增语言只改清单和分组、忘了补 ``LABELS``，README 标题就掉成语言代码。
    """

    def _release_langs(self):
        path = os.path.join(ROOT, "src", "release-languages.txt")
        langs = []
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                for tok in raw.split("#", 1)[0].replace(",", " ").split():
                    langs.append(tok)
        return langs

    def test_bundles_cover_every_release_language(self):
        langs = self._release_langs()
        bundled = [lang for b in make_release.load_bundles()
                   for lang in b["langs"]]
        self.assertEqual(sorted(bundled), sorted(langs))
        self.assertEqual(len(bundled), len(set(bundled)),
                         "同一门语言进了两个分组")

    def test_labels_match_pack_alias(self):
        import tomllib
        for lang in self._release_langs():
            path = os.path.join(ROOT, "src", "packs", lang + ".toml")
            with open(path, "rb") as fh:
                alias = tomllib.load(fh)["alias"]
            self.assertEqual(make_release.LABELS.get(lang), alias,
                             "LABELS 与 %s 的 alias 不一致" % path)

    def test_region_code_font_map_lookup_is_case_insensitive(self):
        """`zh-TW` 这类带地区码的语言，font-map 节名不能按小写字符串直接比。"""
        import release_version
        self.assertEqual(
            release_version.check_language(
                os.path.join(ROOT, "src"), "zh-TW"), [])
        self.assertEqual(
            release_version.check_language(
                os.path.join(ROOT, "src"), "zh-HK"), [])


class TestPackOverridesDir(unittest.TestCase):
    """发行包里只放一个空的 ``packs\\overrides\\``。

    它是玩家自己的补丁位，不是发行物：里面不放任何示例文件（否则玩家会以为
    包里自带这些覆盖），但空目录必须真的进 zip —— 不显式写目录条目，解压后
    就看不到这个通道。
    """

    def test_empty_overrides_dir_survives_zip(self):
        import zipfile
        stage = tempfile.mkdtemp(prefix="pr2-overrides-stage-")
        out = tempfile.mkdtemp(prefix="pr2-overrides-out-")
        try:
            stage = os.path.join(stage, "PR2-zh-v1.0.0")
            packs = os.path.join(stage, make_release.DATA_DIR, "packs")
            os.makedirs(os.path.join(packs, "overrides"))
            # 构建目录里常有别的空目录（运行留下的 logs\）；只有清单里的
            # 占位目录该进包，别的不能顺手塞进来。
            os.makedirs(os.path.join(stage, make_release.DATA_DIR, "logs"))
            with open(os.path.join(packs, "zh.txt"), "w", encoding="utf-8") as fh:
                fh.write("0x1 = 甲\n")
            zip_path = make_release.make_zip(stage, out)
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
            entry = "%s/packs/overrides/" % make_release.DATA_DIR
            self.assertIn(entry, names, "空 overrides\\ 没有写成 zip 目录条目")
            with zipfile.ZipFile(zip_path) as zf:
                self.assertTrue(zf.getinfo(entry).is_dir(),
                                "overrides\\ 条目不是目录")
            # 空目录里不该凭空多出文件。
            self.assertEqual(
                [n for n in names if n.startswith(entry)], [entry])
            self.assertNotIn("%s/logs/" % make_release.DATA_DIR, names,
                             "非占位空目录不该进包")
        finally:
            shutil.rmtree(os.path.dirname(stage), ignore_errors=True)
            shutil.rmtree(out, ignore_errors=True)

    def test_build_pack_creates_empty_overrides(self):
        rel = os.path.join(make_release.DATA_DIR, "packs", "overrides")
        self.assertIn(rel, make_release.EMPTY_DIRS,
                      "overrides\\ 不在占位目录清单里")
        script = os.path.join(ROOT, "src", "tools", "pack", "make_release.py")
        with open(script, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("for rel in EMPTY_DIRS:", text)


class TestInjectorVersionStamp(unittest.TestCase):
    """``-SkipInjector`` 出包不许让 exe 版本和包版本悄悄错开。

    跳过构建时不设 ``PR2_VERSION``，exe 里编的还是上一次的版本；语言包包头
    用的是本次 ``-Version``。两处不一致，玩家看到的是「新版本的包装着旧版
    运行时」，且没有任何提示，所以出包前必须比对构建期记录。
    """

    def _read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_build_writes_the_stamp(self):
        text = self._read(os.path.join("src", "build_injector.py"))
        self.assertIn('"build", "injector-version.txt"', text)
        self.assertIn("show_version", text)
        # 记录放在 build 根：放进 runtime 会被装进游戏目录、也可能进包。
        self.assertNotIn('os.path.join("build", "runtime", "injector-version.txt")', text)

    def test_skip_injector_refuses_a_mismatch(self):
        text = self._read("release.py")
        self.assertIn('"build", "injector-version.txt"', text)
        self.assertIn("built", text)
        self.assertIn("built != version", text)
        self.assertIn("无法确认现有 exe 版本", text)


class TestReleaseLanguageCodes(unittest.TestCase):
    """``release.py`` 的发行语言校验要允许地区子标签。

    ``release-languages.txt`` 里有 ``zh-TW`` / ``zh-HK``；只写 ``^[a-z]{2,3}$``
    会在出包第一步就判「语言代码不合法」，本地也复现不了 CI 才走到的路径。
    """

    def test_region_subtags_are_accepted(self):
        sys.path.insert(0, ROOT)
        import release
        for code in ("zh", "zh-TW", "zh-HK", "pt-BR"):
            self.assertRegex(code, release.LANG_RX.pattern)
        for code in ("zh_TW", "zh-", "-TW", "zh-TW-"):
            self.assertNotRegex(code, release.LANG_RX.pattern)


    def test_traditional_fonts_are_selected_by_release_codes(self):
        # CI 传的是发行代码 zh-TW / zh-HK；字体清单若只标 zh-hant，
        # fetch_noto_fonts.py 会认为「没有要补的字体」，出包时才报缺 TC 文件。
        sys.path.insert(0, os.path.join(ROOT, "src", "tools", "font"))
        import fetch_noto_fonts
        items = fetch_noto_fonts.load_manifest()
        for lang in ("zh-TW", "zh-HK"):
            names = set(fetch_noto_fonts.wanted(items, [lang]))
            for font in ("NotoSansTC-Regular.ttf", "NotoSerifTC-Black.ttf",
                         "NotoSerifTC-Bold.ttf"):
                self.assertIn(font, names, "%s 取不到 %s" % (lang, font))


if __name__ == "__main__":
    unittest.main()
