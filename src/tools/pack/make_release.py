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
        packs/locale.default.ini      # 默认语言；用户 locale.ini 优先
        fonts/NotoSansSC-Regular.ttf ...  # 实际字体文件（默认）
        fonts/font-map.default.ini      # 默认逻辑名到实际文件名的映射
        ui/ui.default.ini
        logs/
      README.txt
      OFL.txt

GOG 版不带宿主 DLL；Steam 版带 Ascaron.Logging-2.6.dll 代理，安装时
必须先把原版备份成 Ascaron.Logging-2.6.orig.dll。PR2HostMount.ps1 负责
校验大小/哈希、备份、挂载和还原；校验不通过时不会覆盖原文件。
发行包不包含游戏本体。字体只做映射：默认 ``noto``（静态 Noto 替换字体 +
``font-map.default.ini``）；``config`` 只带默认映射；用户可另建 font-map.ini
按项覆盖它，解压升级不会覆盖这个文件。``none`` 不带字体。

    python src\\tools\\pack\\make_release.py --lang zh --edition gog --version v1.0.0
    python src\\tools\\pack\\make_release.py --lang zh --edition steam --version v1.0.0
"""

import argparse
import os
import re
import shutil
import sys
import zipfile

import build_time



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

LABELS = {
    "zh": "简体中文", "ja": "日本語", "ko": "한국어", "ru": "Русский",
    "de": "Deutsch", "es": "Español", "fr": "Français",
}
DATA_DIR = "PR2Localization"
FLAT_COMMON = ("PR2Localization.exe", "PR2LocalizationGUI.exe",
               "PR2LocalizationCore.dll")
HOST_DLL = "Ascaron.Logging-2.6.dll"
HOST_MOUNT_SCRIPT = "PR2HostMount.ps1"
FLAT_STEAM = FLAT_COMMON + (HOST_DLL, HOST_MOUNT_SCRIPT)
RUNTIME_VERSION = 1  # 与 src/injector-rs/pr2_common/src/lib.rs 的 RUNTIME_VERSION 保持一致
RUST_RUNTIME_SOURCE = os.path.join(
    SRC, "injector-rs", "pr2_common", "src", "lib.rs")


def check_runtime_version(log=print):
    """``RUNTIME_VERSION`` 与 Rust 常量必须一致，否则发行包会与语言包契约错位。"""
    if not os.path.isfile(RUST_RUNTIME_SOURCE):
        raise FileNotFoundError("缺运行时版本常量：%s" % RUST_RUNTIME_SOURCE)
    with open(RUST_RUNTIME_SOURCE, "r", encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(r"pub\s+const\s+RUNTIME_VERSION\s*:\s*u32\s*=\s*(\d+)\s*;",
                      text)
    if not match:
        raise RuntimeError("在 %s 里找不到 RUNTIME_VERSION" % RUST_RUNTIME_SOURCE)
    rust_version = int(match.group(1))
    if rust_version != RUNTIME_VERSION:
        raise RuntimeError(
            "RUNTIME_VERSION 不一致：make_release.py=%d，lib.rs=%d"
            % (RUNTIME_VERSION, rust_version))
    return RUNTIME_VERSION



def build_pack(lang, stage, log):
    """发行包里的语言包恒为**并集**：GOG 用 PR2LocalizationGUI.exe 注入、Steam 用
    PR2HostMount 改 VERSION.dll，两条注入路径读的是同一份 packs\\<lang>.txt，
    所以两个 zip 里放同一个文件，装哪种版本都行。逐版对照在 build\\variants 里。"""
    out = os.path.join(stage, DATA_DIR, "packs")
    os.makedirs(out, exist_ok=True)
    log("编译语言包 %s（并集）…" % lang)
    from build_artifacts import compile_pack
    if compile_pack(lang, out, no_fonts=True, on_line=log, union=True) != 0:
        raise RuntimeError("语言包编译失败：%s" % lang)
    with open(os.path.join(out, "locale.default.ini"), "w",
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


def copy_font_map(stage, log):
    src = os.path.join(SRC, "font-map.ini")
    if not os.path.isfile(src):
        raise FileNotFoundError("缺字体映射模板：%s" % src)
    dst = os.path.join(stage, DATA_DIR, "fonts", "font-map.default.ini")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    log("复制字体映射（默认 font-map.default.ini；不覆盖用户 font-map.ini）")


def copy_fonts_flat(src_dir, flat_dir, log, expected=None):
    if not os.path.isdir(src_dir):
        raise FileNotFoundError("缺字体目录：%s" % src_dir)
    os.makedirs(flat_dir, exist_ok=True)
    n = 0
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        if os.path.isfile(src) and name.lower().endswith(".ttf"):
            shutil.copy2(src, os.path.join(flat_dir, name))
            n += 1
    if expected is not None and n != expected:
        raise FileNotFoundError(
            "字体文件数量不对：%s 下应有 %d 个 TTF，实际 %d 个" % (
                src_dir, expected, n))
    log("平铺字体 %d 个文件到 PR2Localization\\fonts\\" % n)


def resolve_font_mode(lang, mode):
    """``auto`` 按 font-map.ini 里该语言的四项映射决定：全 none → config，否则 noto。

    这样 de/es（原版拉丁字体已覆盖）自动出“只带映射”的包，zh/ja/ko/ru
    自动带实际字体，不需要在 release.ps1 或 CI 里为每种语言各传一个 -Fonts。
    """
    if mode != "auto":
        return mode
    import configparser
    path = os.path.join(SRC, "font-map.ini")
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    if not cfg.has_section(lang):
        return "noto"
    values = {}
    for key in ("ARIAL.TTF", "ELGRECO_.TTF", "Tiepolo_black.ttf",
                "Tiepolo_bold.ttf"):
        values[key] = cfg.get(lang, key, fallback="").strip().lower()
    if all(v in ("none", "-") for v in values.values()):
        return "config"
    return "noto"


def copy_fonts(lang, stage, mode, log, cache=True):
    if mode == "none":
        log("跳过字体（发行包不含字体）")
        return
    if mode == "config":
        copy_font_map(stage, log)
        log("不打包字体文件")
        return
    flat = os.path.join(stage, DATA_DIR, "fonts")
    from build_artifacts import build_fonts
    ok, msg = build_fonts([lang], out_dir=flat, mode="noto",
                          log=log, cache=cache)
    if not ok:
        raise RuntimeError(msg)
    src_lang = os.path.join(flat, lang)
    # 来源说明移到包根；游戏会扫描 fonts\*.*，不应看到无关文本。
    notice = os.path.join(src_lang, "NOTO-SOURCES.txt")
    if os.path.isfile(notice):
        shutil.move(notice, os.path.join(stage, "NOTO-SOURCES.txt"))
    # 俄语是自建的四个字体（正文 + 标题三档）；其余语言仍是三个 Noto 静态字重。
    copy_fonts_flat(src_lang, flat, log, expected=4 if lang == "ru" else 3)
    shutil.rmtree(src_lang)
    copy_font_map(stage, log)
    log("复制 Noto 实际字体文件（由 font-map.default.ini 映射逻辑名）")


def write_runtime_version(stage, log):
    path = os.path.join(stage, "RUNTIME-VERSION")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%d\n" % RUNTIME_VERSION)
    log("写入 RUNTIME-VERSION (%d)" % RUNTIME_VERSION)


def pack_identity(lang):
    """读 src/packs/<lang>.toml 的标记，返回给玩家看的一行。"""
    import pack_tags
    import tomllib
    path = os.path.join(SRC, "packs", lang + ".toml")
    with open(path, "rb") as fh:
        doc = tomllib.load(fh)
    return pack_tags.describe(doc.get("tags"), doc.get("review_status"))


def write_readme(lang, stage, mode, edition, version=""):
    label = LABELS.get(lang, lang)
    edition_label = "GOG 版" if edition == "gog" else "Steam 版"
    font_line = {
        "noto": "字体：Noto Sans / Noto Serif 原始文件名（SIL OFL 1.1），完整静态字体；font-map.default.ini 负责映射四个逻辑名。",
        "none": "字体：本包不含字体，也无法通过映射读取系统字体。",
        "config": "字体：PR2Localization\\fonts\\font-map.default.ini 把逻辑名映射到 fonts 内的实际文件；本包不含字体，需要自己放入。",
    }[mode]
    if mode == "noto" and lang == "ru":
        # 俄语不是直接挂 Noto：正文是与 Arial 度量一致的 Liberation Sans，
        # 标题是按原版度量压缩并改名的 Noto Serif 衍生文件。
        font_line = ("字体：正文 PR2CyrBody-Regular.ttf（Liberation Sans 未修改副本），"
                     "标题 PR2CyrDisplay-Head / -Black / -Bold.ttf（由 Noto Serif 按原版度量"
                     "压缩并改名）；均为 SIL OFL 1.1，font-map.default.ini 映射四个逻辑名。")
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
        uninstall_line = "  删除 PR2Localization.exe、PR2LocalizationGUI.exe、PR2LocalizationCore.dll\n  和整个 PR2Localization 目录（如果覆盖过根目录 fonts\\，请先用备份恢复）。\n  如果保留过 PR2Localization\\packs\\overrides\\，卸载前先复制出来。"
    else:
        uninstall_line = "  先运行 .\\PR2HostMount.ps1 -Action Restore 还原 Ascaron.Logging-2.6.dll，\n  再删除 PR2Localization.exe、PR2LocalizationGUI.exe、PR2LocalizationCore.dll、\n  PR2HostMount.ps1 和整个 PR2Localization 目录（如果覆盖过根目录 fonts\\，请先用备份恢复）。\n  如果保留过 PR2Localization\\packs\\overrides\\，卸载前先复制出来。"
    if edition == "gog":
        support_line = "支持游戏版本：GOG 英文 1.1.2.3 已实测。本包只用于 GOG；Steam 请下载 Steam 版。"
    else:
        support_line = "支持游戏版本：Steam 英文 1.1.2.3 已实测（宿主 DLL 代理，中文界面）；GOG 请下载 GOG 版。"
    if mode == "config":
        font_help = """字体：
  本包不含字体文件。
  默认映射在 PR2Localization\\fonts\\font-map.default.ini；
  要自定义时新建或编辑同目录的 font-map.ini（运行时优先读它），
  把游戏请求的四个逻辑名
  （ARIAL.TTF、ELGRECO_.TTF、Tiepolo_black.ttf、Tiepolo_bold.ttf）
  映射到实际字体文件名。
  按当前语言包的 [zh] / [ja] 节读取，[fonts] 提供全局默认；支持 | 候选。
  值只写文件名，实际字体必须放在 PR2Localization\\fonts\\；
  不会读取系统字体目录，也不使用 .ttc 或 -VF.ttf 可变字体。
  映射缺失或文件不存在时，回退到根目录原版 fonts\\...

  如果启动器提示“字体缺失”：
  1. 确认当前映射（font-map.ini 优先，否则 font-map.default.ini）里四个逻辑名都有映射。
  2. 确认映射到的实际 .ttf 文件都在 PR2Localization\\fonts\\ 下。
  3. 可以改用静态 .ttf 文件；多个候选用 | 分隔。不要使用 .ttc 或 -VF.ttf。
  4. 修改后重新启动游戏，字体映射只在启动时读取一次。"""
    else:
        font_help = """字体：
  字体文件在 PR2Localization\\fonts\\；DLL 通过路径重定向读取，不覆盖根目录原版。
  实际字体保留自己的文件名（默认是 NotoSansSC / NotoSerifSC 的原始文件名），
  不改名为 ARIAL.TTF、ELGRECO_.TTF 等游戏逻辑名。
  默认映射在 PR2Localization\\fonts\\font-map.default.ini；
  要自定义时新建或编辑同目录的 font-map.ini（运行时优先读它），
  它把四个逻辑名映射到这些实际文件；两个逻辑名可以指向同一个字体文件。
  解压升级只替换 font-map.default.ini，不会覆盖手工修改的 font-map.ini。
  不按语言单开子目录；同一次安装只放一个语言。

  如果启动器提示“字体缺失”：
  1. 确认 font-map.ini（没有它时用默认文件）的四个逻辑名都指向 PR2Localization\\fonts\\ 下真实存在的文件。
  2. 从压缩包重新解压整个 PR2Localization 目录；只复制 packs 里的语言包不够。
  3. 实际字体文件平铺在 PR2Localization\\fonts\\，不要多包一层语言子目录。
  4. 检查杀毒软件是否隔离了字体文件。
  5. 确认 PR2Localization\\packs\\<语言>.txt、PR2Localization\\fonts\\、
     locale.ini（或缺失时的 locale.default.ini）的语言代码一致。
  仍要启动会回退原版拉丁字体，中文可能缺字。"""
        if lang == "ru":
            font_help = """字体：
  字体文件在 PR2Localization\\fonts\\；DLL 通过路径重定向读取，不覆盖根目录原版。
  四个实际字体与游戏请求的四个逻辑名一一对应（正文一份、标题三份）：
    ARIAL.TTF         → PR2CyrBody-Regular.ttf（Liberation Sans，OFL 1.1）
    ELGRECO_.TTF      → PR2CyrDisplay-Head.ttf
    Tiepolo_black.ttf → PR2CyrDisplay-Black.ttf
    Tiepolo_bold.ttf  → PR2CyrDisplay-Bold.ttf
  标题三份是 Noto Serif 按原版各槽位度量压缩后的衍生文件，族名已改为
  PR2 Cyrillic Display *，不改名为 ARIAL.TTF 等游戏逻辑名。
  默认映射在 PR2Localization\\fonts\\font-map.default.ini；要自定义时新建或编辑
  同目录的 font-map.ini（运行时优先读它）。
  解压升级只替换 font-map.default.ini，不会覆盖手工修改的 font-map.ini。
  不按语言单开子目录；同一次安装只放一个语言。

  如果启动器提示“字体缺失”：
  1. 确认 font-map.ini（没有它时用默认文件）的四个逻辑名都指向 PR2Localization\\fonts\\ 下真实存在的文件。
  2. 从压缩包重新解压整个 PR2Localization 目录；只复制 packs 里的语言包不够。
  3. 实际字体文件平铺在 PR2Localization\\fonts\\，不要多包一层语言子目录。
  4. 检查杀毒软件是否隔离了字体文件。
  5. 确认 PR2Localization\\packs\\ru.txt、PR2Localization\\fonts\\、
     locale.ini（或缺失时的 locale.default.ini）的语言代码一致。
  仍要启动会回退原版拉丁字体，俄语会显示成方框或缺字。"""
    if mode == "noto" and lang == "ru":
        license_help = """字体许可：
  正文 Liberation Sans 与标题所用的 Noto Serif 都是 SIL Open Font License 1.1，
  详见同目录 OFL.txt 或 https://openfontlicense.org/
  Liberation Sans 为未修改副本；标题字体是 Noto Serif 的压缩衍生版本，
  已改族名（PR2 Cyrillic Display *），不沿用 Noto 的保留字体名。"""
    elif mode == "noto":
        license_help = """字体许可：
  Noto 字体使用 SIL Open Font License 1.1，详见同目录 OFL.txt
  或 https://openfontlicense.org/"""
    else:
        license_help = """字体许可：
  本包不包含字体文件，不附带 OFL.txt。"""
    locale_help = """语言设置：
  默认语言在 PR2Localization\\packs\\locale.default.ini；
  已有 locale.ini（GUI 选语言时写入）优先，解压升级不会覆盖它。
  packs\\overrides\\ 是本机临时译文覆盖目录，安装/升级不会删除。"""
    text = """Port Royale 2 本地化 - %s（%s）
版本：%s（运行时版本 %d）
%s

%s

安装（解压即用）：
  1. 把本压缩包里的全部文件解压到游戏根目录（和 PR2.exe 同一层）。
%s

发布清单：
  manifest.json 记录目标 exe、参考原文、译文标记（tags）、审阅状态和逐文件 SHA-256；
  只用于审计和校验，运行时不会读取它。

确认是否生效：
  游戏启动后检查 PR2Localization\\logs\\runtime.log 第一行是否为：
    [text] pack '%s' from <游戏目录>\\PR2Localization\\packs: ... overrides
  首行是 NO pack loaded 或没有日志，说明语言包/代理没有加载成功。

%s

%s

卸载：
%s

注意：
  - 本包不包含游戏本体、地图、音乐等游戏资源。
  - 安装前建议备份游戏根目录的 fonts\\。
  - %s

%s
""" % (label, edition_label, version, RUNTIME_VERSION, pack_identity(lang),
       support_line,
       install_step, lang, font_help,
       locale_help, uninstall_line, font_line, license_help)
    with open(os.path.join(stage, "README.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def copy_license(stage, log, mode="noto"):
    if mode != "noto":
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
    # 可复现：SOURCE_DATE_EPOCH 有值时，zip 条目统一用它当 mtime，
    # 同一 commit 重建出的包逐字节相同（manifest 的 build.at 也走同一时间）。
    epoch = build_time.zip_date_time()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, _dirs, files in os.walk(stage):
            for fn in sorted(files):
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, stage).replace(os.sep, "/")
                if epoch is None:
                    zf.write(full, rel)
                    continue
                info = zipfile.ZipInfo(rel, date_time=epoch)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read())
    return zip_path


def make_release(lang, version, out_dir, mode, edition, log=None, cache=True):
    import release_version
    log = log or print
    mode = resolve_font_mode(lang, mode)
    version = release_version.normalize(version)
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
    write_readme(lang, stage, mode, edition, version)
    copy_license(stage, log, mode)
    import release_manifest
    release_manifest.write_release_manifest(stage, lang, version, edition, mode)
    ok, manifest_errors = release_manifest.verify_release_manifest(stage)
    if not ok:
        raise RuntimeError("发布清单校验失败：%s" % "；".join(manifest_errors))
    log("写入并校验 manifest.json（目标 exe、来源、逐文件 SHA-256）")
    zip_path = make_zip(stage, out_dir)
    # 发行目录只留 zip 和校验和；stage 目录是中间产物，打包后立刻删掉。
    shutil.rmtree(stage, ignore_errors=True)
    log("完成：%s" % zip_path)
    return zip_path


def main():
    import config_check
    import release_version

    errors, warnings = config_check.check_repository()
    for warning in warnings:
        print("配置警告：%s" % warning)
    if errors:
        for error in errors:
            print("配置错误：%s" % error)
        print("拒绝出包：语言配置检查失败。")
        return 1

    ap = argparse.ArgumentParser(description="生成按语言、按入口分发的 PR2 本地化发行包")
    ap.add_argument("--lang", action="append", required=True,
                    help="语言代码，可重复")
    ap.add_argument("--edition", choices=("gog", "steam"), required=True,
                    help="发行入口：gog 不带宿主 DLL；steam 带宿主 DLL 和挂载脚本")
    ap.add_argument("--version", required=True,
                    help="发行版本号，规范形式 vMAJOR.MINOR.PATCH[-prerelease]")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--fonts", choices=("auto", "noto", "config", "none"),
                    default="auto",
                    help="字体模式：auto 按 font-map.ini 该语言的映射自动决定")
    ap.add_argument("--no-font-cache", action="store_true",
                    help="忽略 build/cache/noto 里的 Noto 字体缓存")
    args = ap.parse_args()
    try:
        version = release_version.normalize(args.version)
    except ValueError as exc:
        print("拒绝出包：%s" % exc)
        return 2
    print("发行版本：%s（运行时版本 %d）" % (version, check_runtime_version()))
    os.makedirs(args.out, exist_ok=True)
    for lang in args.lang:
        problems = release_version.check_language(SRC, lang)
        if problems:
            print("拒绝出包：%s 不作为发行语言：%s" % (lang, "；".join(problems)))
            return 2
    for lang in args.lang:
        make_release(lang, version, args.out, args.fonts, args.edition)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
