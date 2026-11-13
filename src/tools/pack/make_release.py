#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_release.py —— 生成按语言、按发行入口分发的发行包。

一个语言、一个入口一个 zip，解压到游戏根目录即可：

    PR2-zh-gog-v1.0.0/
      PR2Localization.exe
      PR2LocalizationGUI.exe
      PR2LocalizationCore.dll
      PR2Localization/
        packs/zh.txt
        packs/locale.ini
        fonts/zh/ARIAL.TTF ...    # Noto 替换字体（默认）
        ui/zh.ini
        logs/
      README.txt
      OFL.txt

GOG 版不带宿主 DLL；Steam 版带 Ascaron.Logging-2.6.dll 代理，安装时
必须先把原版备份成 Ascaron.Logging-2.6.orig.dll。PR2HostMount.ps1 负责
校验大小/哈希、备份、挂载和还原；校验不通过时不会覆盖原文件。
发行包不包含游戏本体，也不包含缝合字体。想用原版字形的人可以走
``--fonts stitch``（仅自用/私有包，不要公开分发）。

    python src\\tools\\pack\\make_release.py --lang zh --edition gog --version v1.0.0
    python src\\tools\\pack\\make_release.py --lang zh --edition steam --version v1.0.0
"""

import argparse
import os
import shutil
import sys
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)
BUILD = os.path.join(ROOT, "build")
RUNTIME = os.path.join(BUILD, "runtime")

LABELS = {"zh": "简体中文", "ja": "日本語"}
DATA_DIR = "PR2Localization"
FLAT_COMMON = ("PR2Localization.exe", "PR2LocalizationGUI.exe",
               "PR2LocalizationCore.dll")
HOST_DLL = "Ascaron.Logging-2.6.dll"
HOST_MOUNT_SCRIPT = "PR2HostMount.ps1"
FLAT_STEAM = FLAT_COMMON + (HOST_DLL, HOST_MOUNT_SCRIPT)
RUNTIME_VERSION = 1  # 与 src/injector-rs/pr2_common/src/lib.rs 的 RUNTIME_VERSION 保持一致


def build_pack(lang, stage, log):
    out = os.path.join(stage, DATA_DIR, "packs")
    os.makedirs(out, exist_ok=True)
    log("编译语言包 %s …" % lang)
    from build_artifacts import compile_pack
    if compile_pack(lang, out, no_fonts=True, on_line=log) != 0:
        raise RuntimeError("语言包编译失败：%s" % lang)
    with open(os.path.join(out, "locale.ini"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("language=%s\n" % lang)


def copy_runtime(stage, edition, log):
    flat = FLAT_STEAM if edition == "steam" else FLAT_COMMON
    for name in flat:
        if name == HOST_MOUNT_SCRIPT:
            src = os.path.join(TOOLS, "install", name)
        else:
            src = os.path.join(RUNTIME, name)
        if not os.path.isfile(src):
            raise FileNotFoundError("缺 %s，先构建注入器" % src)
        shutil.copy2(src, os.path.join(stage, name))
        log("复制 %s" % name)


def copy_fonts(lang, stage, mode, log, cache=True):
    if mode == "none":
        log("跳过字体（发行包不含字体）")
        return
    if mode == "config":
        src = os.path.join(SRC, "font-map.ini")
        if not os.path.isfile(src):
            raise FileNotFoundError("缺字体映射模板：%s" % src)
        dst = os.path.join(stage, DATA_DIR, "fonts", "font-map.ini")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        log("复制字体映射（不打包字体文件）")
        return
    dst = os.path.join(stage, DATA_DIR, "fonts", lang)
    from build_artifacts import build_fonts
    out_base = os.path.join(stage, DATA_DIR, "fonts")
    if mode == "stitch":
        ok, msg = build_fonts([lang], out_dir=None, mode="stitch", log=log)
        if not ok:
            raise FileNotFoundError(msg)
        shutil.copytree(os.path.join(RUNTIME, DATA_DIR, "fonts", lang),
                        dst, dirs_exist_ok=True)
        log("复制缝合字体（仅限私有/自用包）")
        return

    ok, msg = build_fonts([lang], out_dir=out_base, mode="noto",
                          log=log, cache=cache)
    if not ok:
        raise RuntimeError(msg)
    # 字体目录只留 TTF；来源说明移到包根，避免游戏扫描 PR2Localization\fonts\<语言>\*.* 时
    # 看到无关的 .txt。
    notice = os.path.join(dst, "NOTO-SOURCES.txt")
    if os.path.isfile(notice):
        shutil.move(notice, os.path.join(stage, "NOTO-SOURCES.txt"))


def write_runtime_version(stage, log):
    path = os.path.join(stage, "RUNTIME-VERSION")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%d\n" % RUNTIME_VERSION)
    log("写入 RUNTIME-VERSION (%d)" % RUNTIME_VERSION)


def write_readme(lang, stage, mode, edition):
    label = LABELS.get(lang, lang)
    edition_label = "GOG 版" if edition == "gog" else "Steam 版"
    font_line = {
        "noto": "字体：Noto Sans / Noto Serif（SIL OFL 1.1），完整字体，未裁剪。",
        "stitch": "字体：本地缝合版（仅限自用，不要公开分发）。",
        "none": "字体：本包不含字体，请自行准备中/日文字体。",
        "config": "字体：PR2Localization\\fonts\\font-map.ini 映射系统字体；非拉丁系默认 Noto，不打包字体文件。",
    }[mode]
    if edition == "gog":
        install_step = """  2. GOG：双击 PR2LocalizationGUI.exe，选语言后点「以所选语言启动」。
     本包是 GOG 版，刻意不包含 VERSION.dll；不要直接双击 PR2.exe。
     如果从旧包升级，根目录残留的 VERSION.dll 可以删除，GOG 不加载它。"""
    else:
        install_step = """  2. Steam：解压后先运行（在游戏根目录打开 PowerShell）：
       powershell -ExecutionPolicy Bypass -File .\\PR2HostMount.ps1 -Action Mount
     脚本会校验原版 Ascaron.Logging-2.6.dll 的 11,776 B / SHA-256，
     通过后备份为 Ascaron.Logging-2.6.orig.dll 和
     PR2Localization\\host-backup\\Ascaron.Logging-2.6.dll，再换上代理。
     大小或哈希不对时脚本会停止，不会强行覆盖。
  3. 挂载成功后从 Steam 正常启动游戏；需要临时指定语言时，可用
     PR2LocalizationGUI.exe 启动。"""
    if edition == "gog":
        uninstall_line = "  删除 PR2Localization.exe、PR2LocalizationGUI.exe、PR2LocalizationCore.dll\n  和整个 PR2Localization 目录（如果覆盖过根目录 fonts\\，请先用备份恢复）。"
    else:
        uninstall_line = "  先运行 .\\PR2HostMount.ps1 -Action Restore 还原 Ascaron.Logging-2.6.dll，\n  再删除 PR2Localization.exe、PR2LocalizationGUI.exe、PR2LocalizationCore.dll、\n  PR2HostMount.ps1 和整个 PR2Localization 目录（如果覆盖过根目录 fonts\\，请先用备份恢复）。"
    if edition == "gog":
        support_line = "支持游戏版本：GOG 英文 1.1.2.3 已实测。本包只用于 GOG；Steam 请下载 Steam 版。"
    else:
        support_line = "支持游戏版本：Steam 英文 1.1.2.3 已实测（宿主 DLL 代理，中文界面）；GOG 请下载 GOG 版。"
    if mode == "config":
        font_help = """字体：
  本包不含字体文件。PR2Localization\\fonts\\font-map.ini 把游戏请求的逻辑字体名
  （ARIAL.TTF、ELGRECO_.TTF、Tiepolo_black.ttf、Tiepolo_bold.ttf）映射到系统字体。
  按当前语言包的 [zh] / [ja] 节读取，[fonts] 提供全局默认；支持 %WINDIR% 和 | 候选。
  非拉丁系默认映射 Noto Sans/Serif SC 或 JP，优先静态字重，没有静态文件时使用 -VF.ttf；
  不使用 .ttc 集合。
  没有映射、映射文件缺失或候选文件不存在时，回退到
  PR2Localization\\fonts\\<语言>\\，最后回退根目录原版 fonts\\...

  如果启动器提示“字体缺失”：
  1. 确认 font-map.ini 里四个逻辑字体名都有映射，且路径指向真实存在的字体文件。
  2. 确认 %WINDIR%\\Fonts\\ 下确实有配置的字体；精简 Windows 可能没有中日字体。
  3. 可以把候选改成 %WINDIR%\\Fonts\\msyh.ttc 或单个 .ttf；多个候选用 | 分隔。
  4. 修改后重新启动游戏，字体映射只在启动时读取一次。"""
    else:
        font_help = """字体：
  字体在 PR2Localization\\fonts\\<语言>\\；DLL 通过路径重定向读取，不覆盖根目录原版。
  同一目录可以放多个语言（PR2Localization\\fonts\\zh、PR2Localization\\fonts\\ja），
  按 locale.ini 或启动器 --lang 选择。

  如果启动器提示“字体缺失”：
  1. 确认 PR2Localization\\fonts\\<语言>\\ 下四个文件都在：
     ARIAL.TTF、ELGRECO_.TTF、Tiepolo_black.ttf、Tiepolo_bold.ttf
  2. 从压缩包重新解压 PR2Localization 目录；只复制 packs 里的语言包不够。
  3. 不要把字体放到 PR2Localization\\fonts\\ 根目录；根目录保留原版。
  4. 检查杀毒软件是否隔离了字体文件。
  5. 确认 PR2Localization\\packs\\<语言>.txt、PR2Localization\\fonts\\<语言>\\、
     locale.ini 的语言代码一致。
  仍要启动会回退原版拉丁字体，中文可能缺字。"""
    if mode in ("noto", "stitch"):
        license_help = """字体许可：
  Noto 字体使用 SIL Open Font License 1.1，详见同目录 OFL.txt
  或 https://openfontlicense.org/"""
    else:
        license_help = """字体许可：
  本包不包含字体文件，不附带 OFL.txt。"""
    text = """Port Royale 2 本地化 - %s（%s）

%s

安装（解压即用）：
  1. 把本压缩包里的全部文件解压到游戏根目录（和 PR2.exe 同一层）。
%s

确认是否生效：
  游戏启动后检查 PR2Localization\\logs\\runtime.log 第一行是否为：
    [text] pack '%s' from <游戏目录>\\PR2Localization\\packs: ... overrides
  首行是 NO pack loaded 或没有日志，说明语言包/代理没有加载成功。

%s

卸载：
%s

注意：
  - 本包不包含游戏本体、地图、音乐等游戏资源。
  - 安装前建议备份游戏根目录的 fonts\\。
  - %s

%s
""" % (label, edition_label, support_line, install_step, lang, font_help, uninstall_line, font_line, license_help)
    with open(os.path.join(stage, "README.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def copy_license(stage, log, mode="noto"):
    if mode not in ("noto", "stitch"):
        return
    for rel in (os.path.join("assets", "fonts", "OFL.txt"),
                "OFL.txt",
                os.path.join("docs", "OFL.txt")):
        src = os.path.join(ROOT, rel)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(stage, "OFL.txt"))
            log("复制 OFL.txt")
            return
    log("提示：仓库里没有 OFL.txt，发行包只写了许可链接；正式发布前补上")


def make_zip(stage, out_dir):
    name = os.path.basename(stage.rstrip("\\/"))
    zip_path = os.path.join(out_dir, name + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, _dirs, files in os.walk(stage):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, stage)
                zf.write(full, rel)
    return zip_path


def make_release(lang, version, out_dir, mode, edition, log=None, cache=True):
    log = log or print
    stage = os.path.join(out_dir, "PR2-%s-%s-%s" % (lang, edition, version))
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)
    build_pack(lang, stage, log)
    copy_runtime(stage, edition, log)
    write_runtime_version(stage, log)
    # 优先用运行时构建产物里的 PR2Localization\ui\；没有时回退到 Rust 源码目录。
    # 旧路径 src/injector/ui 不存在，静默跳过会让发行包缺 ui/*.ini。
    ui_dir = os.path.join(RUNTIME, DATA_DIR, "ui")
    if not os.path.isdir(ui_dir):
        ui_dir = os.path.join(ROOT, "src", "injector-rs", "ui")
    if not os.path.isdir(ui_dir):
        raise FileNotFoundError("缺 ui 目录：%s（先构建注入器）" % ui_dir)
    shutil.copytree(ui_dir, os.path.join(stage, DATA_DIR, "ui"),
                    dirs_exist_ok=True)
    os.makedirs(os.path.join(stage, DATA_DIR, "logs"), exist_ok=True)
    log("复制 PR2Localization\\ui\\")
    copy_fonts(lang, stage, mode, log, cache=cache)
    write_readme(lang, stage, mode, edition)
    copy_license(stage, log, mode)
    zip_path = make_zip(stage, out_dir)
    log("完成：%s" % zip_path)
    return zip_path


def main():
    ap = argparse.ArgumentParser(description="生成按语言、按入口分发的 PR2 本地化发行包")
    ap.add_argument("--lang", action="append", required=True,
                    help="语言代码，可重复")
    ap.add_argument("--edition", choices=("gog", "steam"), required=True,
                    help="发行入口：gog 不带宿主 DLL；steam 带宿主 DLL 和挂载脚本")
    ap.add_argument("--version", default="dev")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--fonts", choices=("noto", "stitch", "config", "none"),
                    default="noto")
    ap.add_argument("--no-font-cache", action="store_true",
                    help="忽略 build/cache/noto 里的 Noto 字体缓存")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for lang in args.lang:
        make_release(lang, args.version, args.out, args.fonts, args.edition)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
