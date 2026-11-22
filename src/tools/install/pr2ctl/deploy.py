# -*- coding: utf-8 -*-
"""pr2ctl.deploy —— 把构建产物复制进游戏目录。"""

from .base import *  # noqa: F401,F403
from .detect import read_locale_language
from . import steam_host


def edition_of(target, edition=None):
    """显式传入优先；否则按 Steam 宿主 DLL 或 PR2.exe 哈希判断。"""
    return edition or steam_host.detect_edition(target)


def _font_lang(target, langs):
    """部署哪一套字体：优先游戏当前 locale，否则选中的第一个语言。"""
    if not langs:
        return None
    cur = read_locale_language(target)
    if cur in langs:
        return cur
    return langs[0]


def deploy_steps(target, langs, edition=None):
    """列出复制要做的事，供进度条按步推进。

    langs 给出时只复制这些语言的语言包 —— build\\runtime\\PR2Localization\\packs 是累积
    目录，里面可能还留着上一次构建的其他语言，整目录照搬会把
    locale.ini 根本没指向的语言也塞进游戏。langs 为 None 时整目录复制。
    """
    edition = edition_of(target, edition)
    steps = [(n, os.path.join(RUNTIME, n), os.path.join(target, n))
             for n in FLAT_FILES]

    # 四个 TTF 平铺在 build\runtime\PR2Localization\fonts\；也兼容旧的语言子目录。
    # 复制到游戏 PR2Localization\fonts\，不覆盖根目录的原版字体。
    font_lang = _font_lang(target, langs)
    # 默认映射以 src\font-map.ini 为准：runtime 里的 default 是派生物，可能落后于
    # 模板（[pl] 一节就是这么丢的）。模板不在时才退回 runtime 的旧文件。
    cfg = os.path.join(SRC, "font-map.ini")
    if not os.path.isfile(cfg):
        cfg = os.path.join(RUNTIME, FONT_DIR, "font-map.default.ini")
    if not os.path.isfile(cfg):
        # 兼容旧构建目录：旧文件只能作为默认映射复制，不能覆盖用户配置。
        cfg = os.path.join(RUNTIME, FONT_DIR, "font-map.ini")
    if os.path.isfile(cfg):
        steps.append(("PR2Localization\\fonts\\font-map.default.ini", cfg,
                      os.path.join(target, FONT_DIR, "font-map.default.ini")))
    font_src = os.path.join(RUNTIME, FONT_DIR)
    names = [n for n in sorted(os.listdir(font_src))
             if n.lower().endswith(".ttf")] if os.path.isdir(font_src) else []
    if not names and font_lang:
        fallback = os.path.join(font_src, font_lang)
        if os.path.isdir(fallback):
            font_src = fallback
            names = [n for n in sorted(os.listdir(font_src))
                     if n.lower().endswith(".ttf")]
    for name in names:
        steps.append(("PR2Localization\\fonts\\%s" % name,
                      os.path.join(font_src, name),
                      os.path.join(target, FONT_DIR, name)))
    # 新布局按语言分子目录放字体；游戏只认 fonts\ 根下的文件名，这里平铺复制
    # 当前语言那一份。只拷子目录、不拷别的语言，保持「一次安装一个语言」。
    if font_lang:
        sub = os.path.join(font_src, font_lang)
        if os.path.isdir(sub):
            for name in sorted(os.listdir(sub)):
                if not name.lower().endswith(".ttf") or name in names:
                    continue
                steps.append(("PR2Localization\\fonts\\%s" % name,
                              os.path.join(sub, name),
                              os.path.join(target, FONT_DIR, name)))

    ui_src = os.path.join(RUNTIME, UI_DIR)
    if os.path.isdir(ui_src):
        # 只装默认界面；用户自己的 ui.ini 是覆盖层，升级时不碰。
        for name in (UI_DEFAULT_FILE,):
            src = os.path.join(ui_src, name)
            if os.path.isfile(src):
                steps.append(("PR2Localization\\ui\\%s" % name, src,
                              os.path.join(target, UI_DIR, name)))

    steps.append(("PR2Localization\\logs\\", None, os.path.join(target, LOG_DIR)))
    steps.append(("%s\\" % PACK_DIR, None, os.path.join(target, PACK_DIR)))
    # locale.ini 是用户可写设置：只复制默认文件，已有 locale.ini 保持不动。
    locale_src = os.path.join(PACK_OUT, LOCALE_DEFAULT_FILE)
    if not os.path.isfile(locale_src):
        # 兼容旧构建目录：旧 locale.ini 只能作为默认值复制。
        locale_src = os.path.join(PACK_OUT, LOCALE_FILE)
    if os.path.isfile(locale_src):
        steps.append(("%s\\%s" % (PACK_DIR, LOCALE_DEFAULT_FILE), locale_src,
                      os.path.join(target, PACK_DIR, LOCALE_DEFAULT_FILE)))
    for name in (["%s.txt" % c for c in langs] if langs else []):
        src = os.path.join(PACK_OUT, name)
        if os.path.isfile(src):
            steps.append(("%s\\%s" % (PACK_DIR, name), src,
                          os.path.join(target, PACK_DIR, name)))

    # Steam 宿主代理不在这里复制：替换必须校验原版、留备份、写完临时文件再换名，
    # 这件事只在 steam_host.swap_host 里做（部署末尾单独调用）。
    return steps


def copy_if_different(src, dst):
    """内容不同才复制。返回 "copied" / "same" / "failed"。

    已经一致就不动目标文件：反复点复制时 DLL 与启动器不会被
    反复改写，而正在运行的游戏加载着旧 DLL，跳过也能避免
    撞上文件占用。
    """
    if os.path.isfile(dst) and same_content(src, dst):
        return "same"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.copy2(src, dst)
        return "copied"
    except OSError:
        # 目标被占用（典型：游戏/杀毒还开着）时直接覆盖会失败，
        # 改成「把旧文件改名让位，再写新文件」；旧文件删不掉就留着 .old。
        alt = dst + ".old"
        try:
            os.replace(dst, alt)
            shutil.copy2(src, dst)
        except OSError:
            return "failed"
        try:
            os.remove(alt)
        except OSError:
            pass
        return "copied"


def prune_stale_pack(target, langs):
    """删掉游戏目录 PR2Localization\\packs\\ 里本次不装的文件，返回删掉的名字。

    只删多出来的，不动要留的 —— 整个 rmtree 会让「内容相同就跳过」
    永远生效不了，语言包每次都被重写。用户活动 locale.ini、发行默认
    locale.default.ini 和本机 overrides 目录始终保留。
    """
    dst_pack = os.path.join(target, PACK_DIR)
    if not os.path.isdir(dst_pack):
        return []
    keep = {LOCALE_FILE, LOCALE_DEFAULT_FILE, "overrides"}
    if langs:
        keep |= {"%s.txt" % c for c in langs}
    removed = []
    for name in os.listdir(dst_pack):
        if name in keep:
            continue
        p = os.path.join(dst_pack, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            removed.append(name)
        except OSError:
            pass
    return removed


def deploy(target, langs=None, edition=None):
    """把构建产物复制到 target。返回 (是否成功, 说明)。"""
    if not writable(target):
        return False, (
            "无法写入该目录。\n\n"
            "最常见的原因是游戏正在运行 —— 请先关闭 Port Royale 2 再试。"
        )
    edition = edition_of(target, edition)
    try:
        if edition == "steam":
            # 先验证原版并建立 .orig / host-backup 备份；失败就完全不改目录。
            steam_host.prepare_mount(target)
    except steam_host.HostError as exc:
        return False, "Steam 宿主 DLL 检查失败，未挂载：\n\n%s" % exc

    copied, same, failed = [], [], []
    try:
        for name in prune_stale_pack(target, langs):
            same.append("%s（已移除）" % name)

        for label, src, dst in deploy_steps(target, langs, edition):
            if src is None:                        # 目录本身
                os.makedirs(dst, exist_ok=True)
                continue
            r = copy_if_different(src, dst)
            name = os.path.basename(dst)
            (copied if r == "copied" else same if r == "same" else failed).append(name)

        if edition == "steam" and not failed:
            # 宿主替换是独立动作：校验原版 → 备份 → 写临时文件 → 校验 → 换名 → 再校验。
            steam_host.swap_host(
                target, os.path.join(RUNTIME, steam_host.HOST_DLL))

    except steam_host.HostError as exc:
        return False, "Steam 宿主 DLL 替换失败，原文件未改动：\n\n%s" % exc
    except PermissionError:
        return False, "权限不足。请确认游戏已关闭，且该目录允许写入。"
    except OSError as exc:
        return False, "复制失败：%s" % exc

    if failed:
        return False, "以下文件复制失败：%s\n\n请确认游戏已关闭。" % "、".join(failed)
    extra = ""
    if edition == "steam":
        extra = (
            "\n\nSteam 宿主：原版已备份为 %s 和 %s；"
            "还原时运行 PR2HostMount.ps1 -Action Restore（或删掉根目录的代理后把 .orig.dll 改名回 %s）。"
            % (steam_host.HOST_ORIG, steam_host.HOST_BACKUP,
               steam_host.HOST_DLL)
        )
    return True, (
        "已复制到：\n%s\n\n"
        "新复制：%s\n未改动：%s\n\n"
        "点「启动游戏（已注入）」即可启动，或以后手动运行这个目录下的\n"
        "%s。语言包在游戏启动时读取，改完翻译重新构建再复制一次即可。%s"
        % (target,
           "、".join(copied) or "（无）",
           "、".join(same) or "（无）",
           LAUNCHER, extra)
    )


def run_deploy(target, langs, events, edition=None):
    """部署线程主体，逐步推进进度条。任何一步失败就停下。"""
    try:
        if not writable(target):
            events.put(("line", "无法写入该目录。"))
            events.put(("line", "最常见的原因是游戏正在运行 —— 请先关闭游戏再试。"))
            events.put(("deploy_failed", ""))
            return

        edition = edition_of(target, edition)
        if edition == "steam":
            try:
                steam_host.prepare_mount(target)
                events.put(("line", "已校验并备份 Steam 宿主 DLL"))
            except steam_host.HostError as exc:
                events.put(("line", "Steam 宿主检查失败，未挂载：%s" % exc))
                events.put(("deploy_failed", ""))
                return

        for name in prune_stale_pack(target, langs):
            events.put(("line", "移除 %s\\%s（本次不装）" % (PACK_DIR, name)))

        steps = deploy_steps(target, langs, edition)
        for i, (label, src, dst) in enumerate(steps, 1):
            events.put(("deploy_step", (i, len(steps), label)))
            if src is None:
                os.makedirs(dst, exist_ok=True)
                events.put(("line", "  新建 %s" % label))
                continue

            r = copy_if_different(src, dst)
            if r == "same":
                events.put(("line", "  跳过 %s（内容相同）" % label))
            elif r == "copied":
                events.put(("line", "  已复制 %s" % label))
            else:
                events.put(("line", "  复制失败 %s —— 游戏可能正在运行" % label))
                events.put(("deploy_failed", ""))
                return

        if edition == "steam":
            steam_host.swap_host(
                target, os.path.join(RUNTIME, steam_host.HOST_DLL))
            events.put(("line", "已校验原版、建立备份并替换 Steam 宿主 DLL"))

        events.put(("deploy_ok", target))
    except steam_host.HostError as exc:
        events.put(("line", "Steam 宿主 DLL 替换失败，原文件未改动：%s" % exc))
        events.put(("deploy_failed", ""))
    except Exception as exc:                      # 兜底，别让线程静默死掉
        events.put(("line", "部署出错：%s" % exc))
        events.put(("deploy_failed", ""))

