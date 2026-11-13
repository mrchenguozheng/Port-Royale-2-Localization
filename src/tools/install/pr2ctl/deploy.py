# -*- coding: utf-8 -*-
"""pr2ctl.deploy —— 把构建产物复制进游戏目录。"""

from .base import *  # noqa: F401,F403
from . import steam_host


def edition_of(target, edition=None):
    """显式传入优先；否则按 Steam 宿主 DLL 或 PR2.exe 哈希判断。"""
    return edition or steam_host.detect_edition(target)


def _font_lang(target, langs):
    """部署哪一套字体：优先游戏当前 locale，否则选中的第一个语言。"""
    if not langs:
        return None
    ini = os.path.join(target, PACK_DIR, "locale.ini")
    try:
        with open(ini, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip().lower() == "language":
                    cur = v.strip()
                    if cur in langs:
                        return cur
                    break
    except OSError:
        pass
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

    # 字体按语言分别生成在 build\runtime\fonts\<语言>\；复制到游戏 fonts\<语言>\，
    # 不覆盖根目录的原版字体。启动器用 PR2_FONT_DIR 做重定向。
    font_lang = _font_lang(target, langs)
    cfg = os.path.join(RUNTIME, FONT_DIR, "font-map.ini")
    if os.path.isfile(cfg):
        steps.append(("PR2Localization\\fonts\\font-map.ini", cfg,
                      os.path.join(target, FONT_DIR, "font-map.ini")))
    for fl in (langs or ([font_lang] if font_lang else [])):
        font_dir = os.path.join(RUNTIME, FONT_DIR, fl)
        if not os.path.isdir(font_dir):
            continue
        for name in sorted(os.listdir(font_dir)):
            if name.lower().endswith(".ttf"):
                steps.append(("PR2Localization\\fonts\\%s\\%s" % (fl, name),
                              os.path.join(font_dir, name),
                              os.path.join(target, FONT_DIR, fl, name)))

    ui_src = os.path.join(RUNTIME, UI_DIR)
    if os.path.isdir(ui_src):
        for name in sorted(os.listdir(ui_src)):
            src = os.path.join(ui_src, name)
            if os.path.isfile(src):
                steps.append(("PR2Localization\\ui\\%s" % name, src,
                              os.path.join(target, UI_DIR, name)))

    steps.append(("PR2Localization\\logs\\", None, os.path.join(target, LOG_DIR)))
    steps.append(("%s\\" % PACK_DIR, None, os.path.join(target, PACK_DIR)))
    wanted = ["locale.ini"]
    if langs:
        wanted += ["%s.txt" % c for c in langs]
    for name in wanted:
        src = os.path.join(PACK_OUT, name)
        if os.path.isfile(src):
            steps.append(("%s\\%s" % (PACK_DIR, name), src,
                          os.path.join(target, PACK_DIR, name)))

    if edition == "steam":
        # 宿主代理最后复制：前面的文件失败时，原版 DLL 还没有被替换。
        steps.append((steam_host.HOST_DLL,
                      os.path.join(RUNTIME, steam_host.HOST_DLL),
                      os.path.join(target, steam_host.HOST_DLL)))
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
    永远生效不了，语言包每次都被重写。
    """
    dst_pack = os.path.join(target, PACK_DIR)
    if not os.path.isdir(dst_pack):
        return []
    keep = {"locale.ini"}
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
            steam_host.write_manifest(target)

    except steam_host.HostError as exc:
        return False, "Steam 宿主 DLL 清单写入失败：\n\n%s" % exc
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
            "还原时先把 .orig.dll 复制回 %s。"
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
            steam_host.write_manifest(target)
            events.put(("line", "已写入 Steam 宿主挂载清单"))

        events.put(("deploy_ok", target))
    except steam_host.HostError as exc:
        events.put(("line", "Steam 宿主清单写入失败：%s" % exc))
        events.put(("deploy_failed", ""))
    except Exception as exc:                      # 兜底，别让线程静默死掉
        events.put(("line", "部署出错：%s" % exc))
        events.put(("deploy_failed", ""))

