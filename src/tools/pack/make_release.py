#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_release.py —— 生成发行包（一个包同时面向 GOG 与 Steam）。

一个分组一个 zip，解压到游戏根目录即可：

    PR2-zh-v1.0.0/
      PR2Localization.exe
      PR2LocalizationGUI.exe
      PR2LocalizationCore.dll
      PR2HostMount.ps1                 # Steam 侧挂载/还原，GOG 侧不执行
      PR2Localization/
        host/Ascaron.Logging-2.6.dll   # Steam 宿主代理，挂载时才换进根目录
        packs/zh.txt
        packs/locale.default.ini      # 默认语言；用户 locale.ini 优先
        fonts/NotoSansSC-Regular.ttf ...  # 实际字体文件（默认）
        fonts/font-map.default.ini      # 默认逻辑名到实际文件名的映射
        ui/ui.default.ini
        logs/
      README.txt
      OFL.txt

两个版本共用同一个包：启动器按游戏目录里的标记文件判断版本，GOG 走注入，
Steam 先确保宿主代理挂载再直启 PR2.exe。宿主代理放在 PR2Localization\\host\\，
不占根目录原名，解压不会覆盖游戏原版。PR2HostMount.ps1 负责校验原版大小/
哈希、备份成 Ascaron.Logging-2.6.orig.dll、原子换进根目录和还原；启动器
PR2Localization.exe 会自动调它，玩家不需要手动运行脚本。
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
FLAT_COMMON = ("PR2Localization.exe", "PR2LocalizationGUI.exe",
               "PR2LocalizationCore.dll")
HOST_DLL = "Ascaron.Logging-2.6.dll"
HOST_MOUNT_SCRIPT = "PR2HostMount.ps1"
#: Steam 代理放在数据目录里，不能放在根目录：根目录的同名文件是游戏原版，
#: 解压时覆盖它就没有原版可校验、可备份、可还原了。挂载动作再把代理换进根目录。
#: 合并包让 GOG 也带着这两个文件——判版走标记文件，GOG 侧根本不会碰它们。
HOST_PROXY_REL = os.path.join(DATA_DIR, "host", HOST_DLL)
FLAT_PACKAGE = FLAT_COMMON + (HOST_MOUNT_SCRIPT,)
RUNTIME_VERSION = 1  # 与 src/injector-rs/pr2_common/src/lib.rs 的 RUNTIME_VERSION 保持一致
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
    """发行包里的语言包恒为**并集**：GOG 由启动器 PR2LocalizationGUI.exe /
    PR2Localization.exe 挂起启动后远程注入 PR2LocalizationCore.dll，Steam 由
    PR2HostMount.ps1 替换宿主 Ascaron.Logging-2.6.dll（代理再加载同一个
    PR2LocalizationCore.dll）；两条注入路径读的都是 packs\\<lang>.txt，
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
    with open(os.path.join(out, "locale.default.ini"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("language=%s\n" % default_lang)


def copy_runtime(stage, log):
    """平铺运行时常量和 Steam 宿主脚本，代理单独落 ``PR2Localization\\host\\``。"""
    for name in FLAT_PACKAGE:
        if name == HOST_MOUNT_SCRIPT:
            src = os.path.join(TOOLS, "install", name)
        else:
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
            shutil.copy2(src, os.path.join(flat, name))
            seen[name] = sha
            n += 1
        # 来源说明移到包根；游戏会扫描 fonts\*.*，不应看到无关文本。
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
        with open(os.path.join(stage, "NOTO-SOURCES.txt"), "w",
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
     启动器按游戏目录自动判版，两版用同一个入口：
       GOG  —— 挂起 PR2.exe 后注入 PR2LocalizationCore.dll。
       Steam —— 先校验原版 Ascaron.Logging-2.6.dll 的 11,776 B / SHA-256，
                备份成 Ascaron.Logging-2.6.orig.dll 和
                PR2Localization\\host-backup\\Ascaron.Logging-2.6.dll，
                再把代理换进根目录，最后拉起 PR2.exe（不注入）。
     校验不对或文件被占用时它会停止，不会覆盖未知文件。
     代理本身在 PR2Localization\\host\\Ascaron.Logging-2.6.dll，解压不会覆盖原版。
     GOG 不要直接双击 PR2.exe：加载器会把 VERSION.dll 解析到
     C:\\Windows\\SysWOW64\\VERSION.dll，同目录代理进不了游戏进程。
     习惯命令行的可以在游戏根目录运行：
       PR2Localization.exe --lang=<代码>
       powershell -ExecutionPolicy Bypass -File .\\PR2HostMount.ps1 -Action Mount
  3. 还原原版：在启动器里点「还原 Steam 原版」，或运行
       PR2Localization.exe --restore
     等价写法：powershell -ExecutionPolicy Bypass -File .\\PR2HostMount.ps1 -Action Restore
     Steam 版会把 Ascaron.Logging-2.6.dll 换回原版并恢复原版字体；
     GOG 版没有宿主 DLL，这一步只恢复原版字体。
     还原过程写在 PR2Localization\\logs\\host.log，失败时 GUI 对话框会带上它的末尾几行。"""
    uninstall_line = """  先点启动器的「还原」（Steam 版会换回原版宿主 DLL），或运行
  PR2Localization.exe --restore；再删除 PR2Localization.exe、
  PR2LocalizationGUI.exe、PR2LocalizationCore.dll、PR2HostMount.ps1
  和整个 PR2Localization 目录（如果覆盖过根目录 fonts\\，请先用备份恢复）。
  GOG 版不需要删宿主的步骤，可直接删这些文件。
  如果保留过 PR2Localization\\packs\\overrides\\，卸载前先复制出来。"""
    support_line = ("支持游戏版本：GOG 英文 1.1.2.3 与 Steam 英文 1.1.2.3 都已实测"
                    "（同一个包，启动器按目录判版）。")
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
  详见同目录 OFL.txt 或 https://openfontlicense.org/
  Liberation Sans 为未修改副本；标题字体是 Noto Serif 的压缩衍生版本，
  已改族名（PR2 Cyrillic Display *），不沿用 Noto 的保留字体名。"""
    elif pkg_mode == "noto":
        license_help = """字体许可：
  Noto 字体使用 SIL Open Font License 1.1，详见同目录 OFL.txt
  或 https://openfontlicense.org/"""
    else:
        license_help = """字体许可：
  本包不包含字体文件，不附带 OFL.txt。"""
    if len(langs) > 1:
        locale_help = """语言设置：
  本包带 %d 种语言：%s；默认 %s。
  默认语言在 PR2Localization\\packs\\locale.default.ini；
  已有 locale.ini（GUI 选语言时写入）优先，解压升级不会覆盖它。
  切换语言不改字体：同一个包里的语言共用 fonts\\ 目录与一份映射。
  packs\\overrides\\ 是本机临时译文覆盖目录，安装/升级不会删除。""" % (
            len(langs), labels, default_lang)
    else:
        locale_help = """语言设置：
  默认语言在 PR2Localization\\packs\\locale.default.ini；
  已有 locale.ini（GUI 选语言时写入）优先，解压升级不会覆盖它。
  packs\\overrides\\ 是本机临时译文覆盖目录，安装/升级不会删除。"""
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


def make_release(langs, version, out_dir, mode, log=None, cache=True,
                 package_id=None, default_lang=None, bundle_label="",
                 baseline_tag=""):
    """出一份发行 zip：langs 里所有语言放进同一个包，共用字体与一份映射。

    一个包同时面向 GOG 与 Steam：宿主代理和挂载脚本恒定进包，GOG 侧不执行。
    包名不含版别，`PR2-<pkg_id>-<version>.zip`。

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
    shutil.copytree(ui_dir, os.path.join(stage, DATA_DIR, "ui"),
                    dirs_exist_ok=True)
    os.makedirs(os.path.join(stage, DATA_DIR, "logs"), exist_ok=True)
    log("复制 PR2Localization\\ui\\")
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
