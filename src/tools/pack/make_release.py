#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_release.py —— 生成发行包（一个包同时面向 GOG 与 Steam）。

一个分组一个 zip，解压到游戏根目录即可：

    PR2-zh-v1.0.0/
      PR2Localization.exe
      PR2LocalizationGUI.exe
      PR2LocalizationCore.dll
      PR2Localization/
        host/Ascaron.Logging-2.6.dll   # 宿主代理，挂载时才换进根目录
        packs/zh.txt
        packs/locale.default.ini      # 本包的默认语言；用户 locale.ini 优先
        fonts/NotoSansSC-Regular.ttf ...  # 实际字体文件（默认）
        fonts/font-map.default.ini      # 默认逻辑名到实际文件名的映射
        docs/OFL.txt                    # 字体许可文本
        docs/NOTO-SOURCES.txt           # 字体来源说明
        ui/ui.default.ini
        logs/
      README.txt

两个版本共用同一个包，本地化入口也相同：GOG 与 Steam 的 PR2.exe 都静态
导入 Ascaron.Logging-2.6.dll（导入表里只有 Log 一个函数），两版的原版 DLL
还是同一份字节。所以启动器先确保宿主代理挂载，再按版别拉起游戏：GOG 直启
PR2.exe，Steam 交给客户端（steam://rungameid/12470）；
根目录没有这个 DLL 的版本才退回注入。宿主代理放在 PR2Localization\\host\\，
不占根目录原名，解压不会覆盖游戏原版。启动器在自己进程里校验原版大小/
哈希、备份成 Ascaron.Logging-2.6.orig.dll、原子换进根目录和还原，运行期
不调用 PowerShell，也不受组策略的脚本限制。
发行包不包含游戏本体。字体只做映射：默认 ``noto``（静态 Noto 替换字体 +
``font-map.default.ini``）；``config`` 只带默认映射；用户可另建 font-map.ini
按项覆盖它，解压升级不会覆盖这个文件。``none`` 不带字体。

    python src\\tools\\pack\\make_release.py --lang zh --version v1.0.0
    python src\\tools\\pack\\make_release.py --bundle latin --version v1.0.0
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
    "de": "Deutsch", "es": "Español", "fr": "Français", "it": "Italiano",
    "pl": "Polski",
}
DATA_DIR = "PR2Localization"
UI_DEFAULT_FILE = "ui.default.ini"

# 日文全角 advance 是 1 em，而界面框按拉丁宽度设计；旧版实测只能横向压 10%，
# 再压字形会明显变形。zh/ko 不压，保持原始 Noto。
JA_FONT_SQUEEZE = 0.9
FLAT_COMMON = ("PR2Localization.exe", "PR2LocalizationGUI.exe",
               "PR2LocalizationCore.dll")
HOST_DLL = "Ascaron.Logging-2.6.dll"
#: 宿主代理放在数据目录里，不能放在根目录：根目录的同名文件是游戏原版，
#: 解压时覆盖它就没有原版可校验、可备份、可还原了。挂载动作再把代理换进根目录。
#: 两版都带同名原版 DLL、都静态导入它，所以这两份文件两版都用得上。
HOST_PROXY_REL = os.path.join(DATA_DIR, "host", HOST_DLL)
FLAT_PACKAGE = FLAT_COMMON
RUNTIME_VERSION = 2  # 与 src/injector-rs/pr2_common/src/lib.rs 的 RUNTIME_VERSION 保持一致
# 空目录条目没有内容，时间戳固定成 zip 能表示的最早时刻，保证重建逐字节相同。
DEFAULT_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
#: 发行包里的占位空目录 —— 玩家自己要往里放东西的位置。显式列出来，
#: 免得构建目录里别的空目录（如运行留下的 logs\）被顺手塞进包里。
EMPTY_DIRS = (os.path.join(DATA_DIR, "packs", "overrides"),)
RUST_RUNTIME_SOURCE = os.path.join(
    SRC, "injector-rs", "pr2_common", "src", "lib.rs")
#: 发行分组：同一份字体能共用的语言打成一个 zip。见文件内注释。
BUNDLES_FILE = os.path.join(SRC, "release-bundles.toml")


def load_bundles():
    """读 src\\release-bundles.toml，返回 [{id, label, langs, default}]。

    分组是「共用字体」的判定落点：de/es/fr/it 四项映射全 none，共用同一份空字体集；
    zh/ja/ko/ru/pl 各带一套文件名不同的字体，各出一包。这里不做推断，只读清单。
    """
    import tomllib
    if not os.path.isfile(BUNDLES_FILE):
        raise FileNotFoundError("缺发行分组清单：%s" % BUNDLES_FILE)
    with open(BUNDLES_FILE, "rb") as fh:
        doc = tomllib.load(fh)
    bundles = []
    seen = set()
    for item in doc.get("bundle", []):
        bid = str(item.get("id", "")).strip()
        langs = [str(x).strip() for x in item.get("langs", [])]
        default = str(item.get("default", "") or (langs[0] if langs else ""))
        if not bid or not langs:
            raise ValueError("release-bundles.toml 里有条目缺 id 或 langs")
        if bid in seen:
            raise ValueError("release-bundles.toml 里 id 重复：%s" % bid)
        if default not in langs:
            raise ValueError("分组 %s 的 default=%s 不在 langs 里" % (bid, default))
        if len(set(langs)) != len(langs):
            raise ValueError("分组 %s 的 langs 有重复语言" % bid)
        seen.add(bid)
        bundles.append({
            "id": bid,
            "label": str(item.get("label", "") or bid),
            "langs": langs,
            "default": default,
        })
    return bundles


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



def build_pack(langs, stage, log, default_lang, version=""):
    """发行包里的语言包恒为**并集**：两版都走宿主代理，启动器把
    Ascaron.Logging-2.6.dll 换成代理，代理再加载同一个
    PR2LocalizationCore.dll；两条路径读的都是 packs\\<lang>.txt，
    所以一个包里放同一份文件，装哪种版本都行。逐版对照在 build\\variants 里。

    每个 pack 头写 ``# pack-meta version=<发行版本>``，以及 ``entries`` /
    ``untranslated`` / ``scope`` / ``digest`` 四行：同一门语言的不同版本在游戏
    目录里只靠文件名分不出来，启动器列表要显示成「简体中文 · v1.0.0」，
    状态框再显示「3590 条（未译 0）· 摘要 1a2b3c4d5e6f」。

    （VERSION.dll 代理是历史路线：GOG 直启 PR2.exe 时它会被解析到 SysWOW64，
    同目录代理进不了进程，发行包也已改用宿主 DLL，两边都不再依赖它。）"""
    out = os.path.join(stage, DATA_DIR, "packs")
    os.makedirs(out, exist_ok=True)
    from build_artifacts import compile_pack
    for lang in langs:
        log("编译语言包 %s（并集，版本 %s）…" % (lang, version or "未标注"))
        if compile_pack(lang, out, no_fonts=True, on_line=log, union=True,
                        version=version) != 0:
            raise RuntimeError("语言包编译失败：%s" % lang)
    # 发行包只带默认文件：活动 locale.ini 是玩家自己的选择，解压不该覆盖它。
    with open(os.path.join(out, "locale.default.ini"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("language=%s\n" % default_lang)
    # 覆盖目录只放一个空文件夹：它是玩家自己的本机补丁位，不是发行物。
    # 建出来是为了解压后能直接看见这个通道（否则要自己猜目录名和安全位置）；
    # 里面不放任何示例文件，免得被当成「包里自带这几条覆盖」。
    for rel in EMPTY_DIRS:
        os.makedirs(os.path.join(stage, rel), exist_ok=True)


def copy_runtime(stage, log):
    """平铺运行时文件，代理单独落 ``PR2Localization\\host\\``。"""
    for name in FLAT_PACKAGE:
        src = os.path.join(RUNTIME, name)
        if not os.path.isfile(src):
            raise FileNotFoundError("缺 %s，先构建注入器" % src)
        shutil.copy2(src, os.path.join(stage, name))
        log("复制 %s" % name)
    src = os.path.join(RUNTIME, HOST_DLL)
    if not os.path.isfile(src):
        raise FileNotFoundError("缺 %s，先构建注入器" % src)
    dst = os.path.join(stage, HOST_PROXY_REL)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    log("复制 %s（宿主代理，挂载时才换进根目录）"
        % HOST_PROXY_REL.replace(os.sep, "\\"))


def copy_ui(stage, ui_dir, default_lang, log):
    """界面默认文案跟随发包语言。

    源目录里每种语言只有一份 ``ui.<lang>.ini``（简体中文就是 ``ui.zh.ini``，
    没有额外的 ``ui.default.ini`` 副本）；包里只放分组默认语言那一份，并
    统一命名成 ``ui.default.ini``。其他语言文件不进包，避免同一份文案在包里
    存多份、日后各自漂移。
    """
    lang_ui = os.path.join(ui_dir, "ui.%s.ini" % default_lang)
    if not os.path.isfile(lang_ui):
        raise FileNotFoundError("缺默认语言界面文案：%s" % lang_ui)
    ui_stage = os.path.join(stage, DATA_DIR, "ui")
    os.makedirs(ui_stage, exist_ok=True)
    shutil.copy2(lang_ui, os.path.join(ui_stage, UI_DEFAULT_FILE))
    log("复制 PR2Localization\\ui\\（默认界面 %s）" % default_lang)


def copy_font_map(stage, log):
    src = os.path.join(SRC, "font-map.ini")
    if not os.path.isfile(src):
        raise FileNotFoundError("缺字体映射模板：%s" % src)
    dst = os.path.join(stage, DATA_DIR, "fonts", "font-map.default.ini")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    log("复制字体映射（默认 font-map.default.ini；不覆盖用户 font-map.ini）")


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


def package_font_mode(modes):
    """一个包里各语言的字体模式合成一个：有一门要带字体就带，全 none 才 none。"""
    if not modes:
        return "none"
    if all(m == "none" for m in modes.values()):
        return "none"
    if any(m == "noto" for m in modes.values()):
        return "noto"
    return "config"


def _ttf_files(directory):
    return sorted(n for n in os.listdir(directory)
                  if n.lower().endswith(".ttf")
                  and os.path.isfile(os.path.join(directory, n)))


def copy_fonts(langs, stage, modes, log, cache=True):
    """把包内所有语言的字体合并成一份平铺在 PR2Localization\\fonts\\。

    组内语言共用同一份字体目录是合包的全部意义：判定依据是 font-map.ini 里
    各语言节的四个逻辑名指向的实际文件。de/es/fr/it 四项全 none，组内没有字体，
    只带一份映射；将来若有语言共用同一批文件名，这里按 SHA-256 核对，
    同名不同内容直接失败，不允许后写的一份静默盖掉前一份。
    """
    pkg = package_font_mode(modes)
    if pkg == "none":
        log("跳过字体（发行包不含字体）")
        return
    noto = [lang for lang in langs if modes[lang] == "noto"]
    if not noto:
        copy_font_map(stage, log)
        log("不打包字体文件（%s 四项映射全 none，回落到原版字体）"
            % "/".join(langs))
        return
    flat = os.path.join(stage, DATA_DIR, "fonts")
    from build_artifacts import build_fonts
    import release_manifest
    ok, msg = build_fonts(noto, out_dir=flat, mode="noto",
                          log=log, cache=cache)
    if not ok:
        raise RuntimeError(msg)

    seen, notices, n = {}, [], 0
    for lang in noto:
        sub = os.path.join(flat, lang)
        expected = 4 if lang == "ru" else 3
        files = _ttf_files(sub)
        if len(files) != expected:
            raise FileNotFoundError(
                "字体文件数量不对：%s 下应有 %d 个 TTF，实际 %d 个"
                % (sub, expected, len(files)))
        for name in files:
            src = os.path.join(sub, name)
            sha = release_manifest.sha256_file(src)
            if name in seen:
                if seen[name] != sha:
                    raise RuntimeError(
                        "组内两份字体同名但内容不同：%s（%s）" % (name, lang))
                continue
            dst = os.path.join(flat, name)
            if lang == "ja":
                from font import squeeze_fonts
                if not squeeze_fonts._fonttools():
                    raise RuntimeError("日文字体压缩需要 fontTools")
                squeeze_fonts.squeeze(src, dst, JA_FONT_SQUEEZE)
                log("压缩日文字体 %s（x%.3f）" % (name, JA_FONT_SQUEEZE))
            else:
                shutil.copy2(src, dst)
            seen[name] = sha
            n += 1
        # 来源说明移到 PR2Localization\docs\；游戏会扫描 fonts\*.*，字体目录只放
        # TTF 与映射，不放说明文本。
        notice = os.path.join(sub, "NOTO-SOURCES.txt")
        if os.path.isfile(notice):
            with open(notice, "r", encoding="utf-8") as fh:
                notices.append(fh.read().strip())
        shutil.rmtree(sub)

    if notices:
        lines = []
        for block in notices:
            for line in block.splitlines():
                if line not in lines:
                    lines.append(line)
        docs_dir = os.path.join(stage, DATA_DIR, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        with open(os.path.join(docs_dir, "NOTO-SOURCES.txt"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
    log("平铺字体 %d 个文件到 PR2Localization\\fonts\\（%s）"
        % (n, "/".join(noto)))
    copy_font_map(stage, log)
    log("复制实际字体文件（由 font-map.default.ini 映射逻辑名）")


def write_runtime_version(stage, log):
    path = os.path.join(stage, "RUNTIME-VERSION")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%d\n" % RUNTIME_VERSION)
    log("写入 RUNTIME-VERSION (%d)" % RUNTIME_VERSION)


def pack_identity(langs):
    """读 src/packs/<lang>.toml 的标记，返回给玩家看的一行（多语言时每行一门）。"""
    import pack_tags
    import tomllib
    lines = []
    for lang in langs:
        path = os.path.join(SRC, "packs", lang + ".toml")
        with open(path, "rb") as fh:
            doc = tomllib.load(fh)
        lines.append("%s：%s" % (LABELS.get(lang, lang),
                                pack_tags.describe(doc.get("tags"),
                                                   doc.get("review_status")))
                     if len(langs) > 1 else
                     pack_tags.describe(doc.get("tags"), doc.get("review_status")))
    return "\n".join(lines)


def _delta_note(delta):
    """一门语言的「相对上一次发行」短句；没有可用基准时说清为什么没有。"""
    if not delta:
        return "未统计变化"
    kind = delta.get("kind")
    base = delta.get("baseline") or ""
    if kind == "initial":
        return "第一次收录（%s 里没有这份译文）" % base
    if kind == "same":
        return "与上一次发行（%s）逐条一致" % base
    if kind == "changed":
        return "相对 %s 新增 %d 条、修改 %d 条、删除 %d 条" % (
            base, delta.get("added", 0), delta.get("changed", 0),
            delta.get("removed", 0))
    if kind == "none":
        return "无可比基准（仓库里没有 release-v* 发行 tag）"
    return "变化统计失败（git 出错，不猜数字）"


def _changes_block(langs, stage, deltas):
    """README 的「语言包变化」段：条目数 + 未译数 + 相对上一次发行改了多少。

    条目数和未译数从**包里的语言包头**读回来，与启动器显示的是同一份数据。
    """
    import release_manifest
    lines = ["语言包变化："]
    for lang in langs:
        head = release_manifest._pack_head_info(stage, lang)
        stat = ""
        if head.get("entries"):
            stat = "%d 条" % head["entries"]
            if "untranslated" in head:
                stat += "（未译 %d）" % head["untranslated"]
        note = _delta_note((deltas or {}).get(lang))
        label = LABELS.get(lang, lang)
        if stat:
            lines.append("  %s（%s）：%s；%s" % (lang, label, stat, note))
        else:
            lines.append("  %s（%s）：%s" % (lang, label, note))
    lines.append("  数字按译文条目算：一条译文改了算 1 条，挪换行、改排版不算。")
    return "\n".join(lines)


def write_readme(langs, default_lang, stage, modes, version="",
                 bundle_label="", deltas=None):
    pkg_mode = package_font_mode(modes)
    labels = "、".join(LABELS.get(lang, lang) for lang in langs)
    if len(langs) > 1:
        label = "%s —— 同一包内含 %d 种语言（%s），在启动器里切换" % (
            bundle_label or "多语言包", len(langs), labels)
    else:
        label = LABELS.get(langs[0], langs[0])
    edition_label = "GOG / Steam 通用"
    font_line = {
        "noto": "字体：Noto Sans / Noto Serif 原始文件名（SIL OFL 1.1），完整静态字体；font-map.default.ini 负责映射四个逻辑名。",
        "none": "字体：本包不含字体，也无法通过映射读取系统字体。",
        "config": "字体：PR2Localization\\fonts\\font-map.default.ini 把逻辑名映射到 fonts 内的实际文件；本包不含字体，需要自己放入。",
    }[pkg_mode]
    if pkg_mode == "noto" and "ru" in langs:
        # 俄语不是直接挂 Noto：正文是与 Arial 度量一致的 Liberation Sans，
        # 标题是按原版度量压缩并改名的 Noto Serif 衍生文件。
        font_line = ("字体：正文 PR2CyrBody-Regular.ttf（Liberation Sans 未修改副本），"
                     "标题 PR2CyrDisplay-Head / -Black / -Bold.ttf（由 Noto Serif 按原版度量"
                     "压缩并改名）；均为 SIL OFL 1.1，font-map.default.ini 映射四个逻辑名。")
    install_step = """  2. 双击 PR2LocalizationGUI.exe，选语言后点「以所选语言启动」。
     先校验原版 Ascaron.Logging-2.6.dll 的 11,776 B / SHA-256，
     备份成 Ascaron.Logging-2.6.orig.dll 和
     PR2Localization\\host-backup\\Ascaron.Logging-2.6.dll，
     再把代理换进根目录（不注入），然后按版别拉起游戏：
       GOG 版：直接启动根目录的 PR2.exe
       Steam 版：交给客户端，打开 steam://rungameid/12470
     GOG 与 Steam 的 PR2.exe 都静态导入这个 DLL。Steam 版读不到启动器的
     命令行与环境变量，语言写在 PR2Localization\\packs\\locale.ini，GUI 会先
     把所选语言写进这个文件再交给客户端。
     校验不对或被占用时它会停止，不会覆盖未知文件。
     代理本身在 PR2Localization\\host\\Ascaron.Logging-2.6.dll，解压不会覆盖原版。
     根目录没有这个 DLL 的版本会自动退回注入启动，原因写在
     PR2Localization\\logs\\host.log。
     习惯命令行的可以在游戏根目录运行（--lang 只对 GOG 版有效，
     Steam 版会直接报错退出）：
       PR2Localization.exe --lang=<代码>
       PR2Localization.exe --mount          （只挂载，不启动）
  3. 还原原版：在启动器里点「还原原版」，或运行
       PR2Localization.exe --restore
     等价写法：PR2Localization.exe --restore（再次运行不会重复改动）
     会把 Ascaron.Logging-2.6.dll 换回原版并恢复原版字体。
     还原过程写在 PR2Localization\\logs\\host.log，失败时 GUI 对话框会带上它的末尾几行。"""
    uninstall_line = """  先点启动器的「还原」（会换回原版宿主 DLL），或运行
  PR2Localization.exe --restore；再删除 PR2Localization.exe、
  PR2LocalizationGUI.exe、PR2LocalizationCore.dll
  和整个 PR2Localization 目录（如果覆盖过根目录 fonts\\，请先用备份恢复）。
  如果保留过 PR2Localization\\packs\\overrides\\，卸载前先复制出来。"""
    support_line = ("支持游戏版本：GOG 英文 1.1.2.3、Steam 英文 1.1.2.3 与 GOG 法语 1.1.2.42 "
                    "都已实测（同一个包；GOG 版直启，Steam 版交给客户端启动；"
                    "法语版多 42 条 +++EMPTY+++ 空占位、少 19 条，按原样保留）。")
    if pkg_mode == "config":
        font_help = """字体：
  本包不含字体文件。
  默认映射在 PR2Localization\\fonts\\font-map.default.ini；
  要自定义时新建或编辑同目录的 font-map.ini（运行时优先读它），
  把游戏请求的四个逻辑名
  （ARIAL.TTF、ELGRECO_.TTF、Tiepolo_black.ttf、Tiepolo_bold.ttf）
  映射到实际字体文件名。
  按当前语言包的 [zh] / [ja] / [de] / [es] / [fr] / [it] 等小节读取，
  [fonts] 提供全局默认；支持 | 候选。
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
  不按语言单开子目录；同一个包里的语言共用这一份 fonts\\ 目录。

  如果启动器提示“字体缺失”：
  1. 确认 font-map.ini（没有它时用默认文件）的四个逻辑名都指向 PR2Localization\\fonts\\ 下真实存在的文件。
  2. 从压缩包重新解压整个 PR2Localization 目录；只复制 packs 里的语言包不够。
  3. 实际字体文件平铺在 PR2Localization\\fonts\\，不要多包一层语言子目录。
  4. 检查杀毒软件是否隔离了字体文件。
  5. 确认 PR2Localization\\packs\\<语言>.txt、PR2Localization\\fonts\\、
     locale.ini（或缺失时的 locale.default.ini）的语言代码一致。
  仍要启动会回退原版拉丁字体，中文可能缺字。"""
        if "ru" in langs:
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
  不按语言单开子目录；同一个包里的语言共用这一份 fonts\\ 目录。

  如果启动器提示“字体缺失”：
  1. 确认 font-map.ini（没有它时用默认文件）的四个逻辑名都指向 PR2Localization\\fonts\\ 下真实存在的文件。
  2. 从压缩包重新解压整个 PR2Localization 目录；只复制 packs 里的语言包不够。
  3. 实际字体文件平铺在 PR2Localization\\fonts\\，不要多包一层语言子目录。
  4. 检查杀毒软件是否隔离了字体文件。
  5. 确认 PR2Localization\\packs\\ru.txt、PR2Localization\\fonts\\、
     locale.ini（或缺失时的 locale.default.ini）的语言代码一致。
  仍要启动会回退原版拉丁字体，俄语会显示成方框或缺字。"""
    if pkg_mode == "noto" and "ru" in langs:
        license_help = """字体许可：
  正文 Liberation Sans 与标题所用的 Noto Serif 都是 SIL Open Font License 1.1，
  详见 PR2Localization\\docs\\OFL.txt 或 https://openfontlicense.org/
  字体来源清单：PR2Localization\\docs\\NOTO-SOURCES.txt
  Liberation Sans 为未修改副本；标题字体是 Noto Serif 的压缩衍生版本，
  已改族名（PR2 Cyrillic Display *），不沿用 Noto 的保留字体名。"""
    elif pkg_mode == "noto":
        license_help = """字体许可：
  Noto 字体使用 SIL Open Font License 1.1，详见 PR2Localization\\docs\\OFL.txt
  字体来源清单：PR2Localization\\docs\\NOTO-SOURCES.txt
  或 https://openfontlicense.org/"""
    else:
        license_help = """字体许可：
  本包不包含字体文件，不附带 OFL.txt。"""
    # packs\overrides\ 在发行包里固定是空目录：注入器读完语言包后按固定路径
    # 再读 packs\overrides\<语言>.txt，这个位置必须预先存在玩家才有地方放补丁；
    # 而补丁是玩家自己的改动，不能随包分发，所以只留空目录、不放示例文件。
    overrides_help = """packs\\overrides\\ 是留给你自己的本机覆盖目录，包里只放一个空文件夹：
  为什么有这个空目录：注入器读完语言包后，会再去读 packs\\overrides\\<语言>.txt，
  那个位置必须预先存在，否则你放了文件也不会被读；文件本身是你的改动，
  不属于发行内容，所以包里不放，安装/升级也不会删除你放进去的东西。
  怎么用：新建文本文件，文件名等于 locale.ini 里选的语言，本包默认是
  packs\\overrides\\%s.txt；每行一条「0xHASH = 译文」，与语言包格式相同，
  哈希相同的条目会盖掉语言包里那一条，其余照旧；改完重启游戏生效。
  只改几句、不想动语言包时用这里；要改的条目较多请直接反馈，不要靠覆盖。""" % default_lang
    if len(langs) > 1:
        locale_help = """语言设置：
  本包带 %d 种语言：%s；默认 %s。
  默认语言在 PR2Localization\\packs\\locale.default.ini；
  已有 locale.ini（GUI 选语言时写入）优先，解压升级不会覆盖它。
  切换语言不改字体：同一个包里的语言共用 fonts\\ 目录与一份映射。

%s""" % (len(langs), labels, default_lang, overrides_help)
    else:
        locale_help = """语言设置：
  默认语言在 PR2Localization\\packs\\locale.default.ini；
  已有 locale.ini（GUI 选语言时写入）优先，解压升级不会覆盖它。

%s""" % overrides_help
    text = """Port Royale 2 本地化 - %s（%s）
版本：%s（运行时版本 %d）
%s

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
""" % (label, edition_label, version, RUNTIME_VERSION, pack_identity(langs),
       _changes_block(langs, stage, deltas),
       support_line,
       install_step, default_lang, font_help,
       locale_help, uninstall_line, font_line, license_help)
    with open(os.path.join(stage, "README.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def copy_license(stage, log, mode="noto"):
    """把 OFL 文本放进 PR2Localization\\docs\\，与字体来源说明放在一起。

    不能放进 fonts\\：游戏会按 ``fonts\\*.*`` 枚举字体文件，说明文本不应混进去。
    """
    if mode != "noto":
        return
    dst_dir = os.path.join(stage, DATA_DIR, "docs")
    for rel in (os.path.join("assets", "fonts", "OFL.txt"),
                "OFL.txt",
                os.path.join("docs", "OFL.txt")):
        src = os.path.join(ROOT, rel)
        if os.path.isfile(src):
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, os.path.join(dst_dir, "OFL.txt"))
            log("复制 PR2Localization\\docs\\OFL.txt")
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
        # 占位空目录不会出现在 files 里，不显式写条目就会被 zip 丢掉：
        # packs\overrides\ 就是这样一个空目录，解压后要能看见。
        for rel in EMPTY_DIRS:
            if not os.path.isdir(os.path.join(stage, rel)):
                continue
            rel_zip = rel.replace(os.sep, "/") + "/"
            info = zipfile.ZipInfo(
                rel_zip, date_time=epoch or DEFAULT_ZIP_DATE)
            # 0x10 置位表示「目录」，解压工具据此建文件夹而不是建空文件。
            info.external_attr = (0o40755 << 16) | 0x10
            zf.writestr(info, b"")
    return zip_path


def make_release(langs, version, out_dir, mode, log=None, cache=True,
                 package_id=None, default_lang=None, bundle_label="",
                 baseline_tag=""):
    """出一份发行 zip：langs 里所有语言放进同一个包，共用字体与一份映射。

    一个包同时面向 GOG 与 Steam：宿主代理恒定进包，两版都由启动器先挂载；
    之后由谁来拉起进程按版别决定。包名不含版别，`PR2-<pkg_id>-<version>.zip`。

    package_id 为空时按第一个语言命名（单语言包，与旧行为一致）；
    合包时由 src\\release-bundles.toml 给 id（如 latin）。
    """
    import release_version
    log = log or print
    langs = list(langs)
    if not langs:
        raise ValueError("没有语言")
    default_lang = default_lang or langs[0]
    if default_lang not in langs:
        raise ValueError("默认语言 %s 不在包内语言里（%s）"
                         % (default_lang, "、".join(langs)))
    modes = {lang: resolve_font_mode(lang, mode) for lang in langs}
    pkg_mode = package_font_mode(modes)
    # 一个包里语言各走各的模式时，混出 noto 与 config 说明容易把人带偏，
    # 这里直接拒绝：合包的前提就是字体能共用。
    if len(set(modes.values())) > 1:
        raise RuntimeError(
            "组内语言字体模式不一致（%s），不能合包"
            % "、".join("%s=%s" % (k, v) for k, v in modes.items()))
    version = release_version.normalize(version)
    pkg_id = package_id or langs[0]
    stage = os.path.join(out_dir, "PR2-%s-%s" % (pkg_id, version))
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)
    build_pack(langs, stage, log, default_lang, version=version)
    # 相对上一次发行（``release-v*`` 里版本号最大的 tag）的条目变化。
    # 数字写进 README 与 manifest；基准不可用时只写原因，不猜数字。
    import pack_delta
    deltas = {lang: pack_delta.pack_delta(lang, version, tag=baseline_tag)
              for lang in langs}
    for lang in langs:
        log("语言包变化 %s：%s" % (lang, _delta_note(deltas[lang])))
    copy_runtime(stage, log)
    write_runtime_version(stage, log)
    # 优先用运行时构建产物里的 PR2Localization\ui\；没有时回退到 Rust 源码目录。
    # 旧路径 src/injector/ui 不存在，静默跳过会让发行包缺 ui/*.ini。
    ui_dir = os.path.join(RUNTIME, DATA_DIR, "ui")
    if not os.path.isdir(ui_dir):
        ui_dir = os.path.join(ROOT, "src", "injector-rs", "ui")
    if not os.path.isdir(ui_dir):
        raise FileNotFoundError("缺 ui 目录：%s（先构建注入器）" % ui_dir)
    # 界面文案跟随发包语言：分组默认语言是哪门，就把哪门的 ui.<lang>.ini
    # 以 ui.default.ini 的名字放进包；其他语言文件不进包，避免多份文案漂移。
    copy_ui(stage, ui_dir, default_lang, log)
    os.makedirs(os.path.join(stage, DATA_DIR, "logs"), exist_ok=True)
    copy_fonts(langs, stage, modes, log, cache=cache)
    write_readme(langs, default_lang, stage, modes, version, bundle_label,
                 deltas)
    copy_license(stage, log, pkg_mode)
    import release_manifest
    release_manifest.write_release_manifest(
        stage, langs, version, pkg_mode, package_id=pkg_id, deltas=deltas)
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

    ap = argparse.ArgumentParser(description="生成 PR2 本地化发行包（GOG / Steam 通用）")
    ap.add_argument("--lang", action="append", default=[],
                    help="语言代码，可重复；不给 --package-id 时每门语言各出一包")
    ap.add_argument("--bundle", action="append", default=[],
                    help="按 src\\release-bundles.toml 的分组出包（可重复，与 --lang 互斥）；"
                         "同一组的语言进同一个 zip，共用字体与一份 font-map")
    ap.add_argument("--package-id", default="",
                    help="把多个 --lang 合成一个包时的包标识（进文件名）")
    ap.add_argument("--default-lang", default="",
                    help="合成包里的默认语言（locale.default.ini）；默认取第一个")
    ap.add_argument("--list-bundles", action="store_true",
                    help="只打印分组清单，每行 id|default|langs")
    ap.add_argument("--version",
                    help="发行版本号，规范形式 vMAJOR.MINOR.PATCH[-prerelease]")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--fonts", choices=("auto", "noto", "config", "none"),
                    default="auto",
                    help="字体模式：auto 按 font-map.ini 该语言的映射自动决定")
    ap.add_argument("--no-font-cache", action="store_true",
                    help="忽略 build/cache/noto 里的 Noto 字体缓存")
    ap.add_argument("--baseline-tag", default="",
                    help="变化统计的基准 tag；默认取 release-v* 里版本号最大、"
                         "且不与本次版本同名的那一个")
    args = ap.parse_args()

    if args.list_bundles:
        for b in load_bundles():
            print("%s|%s|%s" % (b["id"], b["default"], ",".join(b["langs"])))
        return 0

    if not args.bundle and not args.lang:
        ap.error("要么给 --bundle，要么给 --lang")
    if args.bundle and args.lang:
        ap.error("--bundle 与 --lang 只能给一个")
    if not args.version:
        ap.error("出包需要 --version")

    try:
        version = release_version.normalize(args.version)
    except ValueError as exc:
        print("拒绝出包：%s" % exc)
        return 2
    print("发行版本：%s（运行时版本 %d）" % (version, check_runtime_version()))

    if args.bundle:
        known = {b["id"]: b for b in load_bundles()}
        jobs = []
        for bid in args.bundle:
            if bid not in known:
                print("拒绝出包：没有这个分组：%s（可选：%s）"
                      % (bid, "、".join(sorted(known))))
                return 2
            jobs.append(dict(known[bid], merge=True))
    else:
        langs = list(args.lang)
        jobs = [{"id": args.package_id or langs[0], "label": "",
                 "langs": langs,
                 "default": args.default_lang or langs[0],
                 "merge": bool(args.package_id)}]

    for job in jobs:
        for lang in job["langs"]:
            problems = release_version.check_language(SRC, lang)
            if problems:
                print("拒绝出包：%s 不作为发行语言：%s"
                      % (lang, "；".join(problems)))
                return 2
        # 分组只允许从发行语言集里挑，防止在 bundles 里偷偷塞一门没验收的语言。
        if job.get("merge"):
            allowed = set(release_version.read_languages(SRC))
            outside = [lang for lang in job["langs"] if lang not in allowed]
            if outside:
                print("拒绝出包：分组 %s 里有语言不在 src\\release-languages.txt：%s"
                      % (job["id"], "、".join(outside)))
                return 2

    os.makedirs(args.out, exist_ok=True)
    for job in jobs:
        if job.get("merge"):
            # 显式 --package-id：多门语言进一个包。
            make_release(job["langs"], version, args.out, args.fonts,
                         package_id=job["id"],
                         default_lang=job["default"],
                         bundle_label=job["label"],
                         baseline_tag=args.baseline_tag)
            continue
        # 旧行为：每门语言各出一包，文件名沿用语言代码。
        for lang in job["langs"]:
            make_release([lang], version, args.out, args.fonts,
                         default_lang=lang, baseline_tag=args.baseline_tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
