#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lang_add.py —— 加一门语言：能自动的自动，剩下的当场列清单。

加一种语言要改六处，其中五处是「照抄一份、改个名字」，一处是「知道该改哪」。
本脚本把前五处一次做完，并顺带把**字形够不够**量出来 —— 这一步以前靠人拿
fontTools 现写脚本、再肉眼判断要不要换字体。

    python src\\tools\\pack\\lang_add.py --lang pl --alias Polski \\
        --alphabet "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ" --ref pl.retail-1.0.0

自动做的部分
------------
1. `src/translations/<lang>.toml`  ← 复制英文基准（每行右边是英文 = 未译）；
2. `src/packs/<lang>.toml`        ← 新建语言包标记（alias / source / tags）；
3. `src/data/placeholder_roles/<lang>.toml` ← 占位符角色声明存根；
4. `src/data/keep_as_is/<lang>.txt` ← 有官方参照版时，逐条与英文比：参照版也写
   英文的那些就是「有意不译」，自动分类成 name / key / label / id / credit /
   save-name / same，写注释头 + id<TAB>理由（判据同 build\\tail_plan.py）；
5. `src/tools/text/lang_rules/<lang>.py` + `REGISTRY` 登记 ← 显式 no-op 声明；
6. `src/font-map.ini` 的 `[<lang>]` ← 四个逻辑名先全 `none`（回落原版字体），
   实测缺字形再换成替换字体（脚本会把实测结果打在结尾）；
7. `src/tools/analysis/line_run.py` 的 `SKIP` ← 断行上限对拉丁语种不适用；
8. `src/tools/README.md` 的脚本地图 ← tools_check 强制每个脚本都要有一行；
9. `README.md` 语言完成度表 ← 新增一行（数字从 keep 清单实时算）。

脚本不做的
----------
译文本身、术语表（`src/data/terms/<lang>.toml`）、诗谜谜底（`[ans:…]`）、
实机截图、docs 里那几段叙述 —— 这些没有判据可循，脚本只把它们列成待办，
不假装完成。已存在的文件一律不覆盖（加语言误填了已有代码不该冲掉已有译文）。

`--dry-run` 只打印要做什么；`--force` 允许覆盖已有文件（仅重建骨架时用）。
"""

import argparse
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # 仓库根
BASE = "en.gog_1.1.2.3"

#: 有意不译的分类判据（与 build\tail_plan.py 同一套，别再分叉）。
KEYS = {"F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
        "ESC", "CTRL", "Shift", "Enter", "Insert", "Delete", "Backspace",
        "Page Up", "Page Down", "End", "Pause", "Tab key", "x 10"}
IDS = {"dummy", "Dummy", "+++EMPTY+++"}
CREDITS = {"Take2", "M&S Music", "MBA Studios", "Between Us!", "Yanco", "QA"}
PARTICLES = {"van", "de", "le", "la", "der", "los", "do", "Don", "von"}
NAMEWORDS = re.compile(r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ'´`\.\-]*$")
SHORT_LABELS = {"OK", "Ok", "Yes", "No", "On", "Off", "Cancel", "Total", "Max", "Min",
                "Quit", "Exit", "Apply", "Back", "Next", "Done", "Help", "Info"}

KEEP_HEAD = """# 有意不译：正确译法就是保持原文（英文）原样，算进度时不计入待译。
# 一行一条：id<TAB>理由。理由取值：
#   key=按键名、label=界面键名、id=脚本/资源标识、credit=职员表/机构名、
#   save-name=存档文件名（必须纯 ASCII）、name=专名（原文即本语言写法）、
#   same=原文与本语言同形（Total:、max、Version %1 这类，写法本来就一样）。
#
# 七语共用的条目（职员表、场景存档名、存档名模板）在 _common.txt，本文件只写本语言独有的。
#
# 判据不是「懒得翻」：逐条与官方零售版（src/orig/<参照文件>）比过 ——
# 零售版这一条写的就是英文原文，改反而错。人名、商品名、城镇名与按键都在这一批。
"""

PACK_TMPL = """# 语言包标记：{alias}（{lang}）。release 时写进 RUNTIME-VERSION 旁的身份行。
alias = "{alias}"
#: 译文起手自哪个原文版本：现在是从英文基准起的，改完照参照版核一遍再动这里。
source_lang = "{base}"
#: 出包必须的最低运行时版本。
min_runtime = 1
#: fan = 玩家自制；official = 官方语言；community = 社区协作翻译
tags = ["fan", "community", "ai-assist"]
#: draft / preview / released —— 试做批阶段一律 preview
review_status = "preview"
"""

PLACEHOLDER_ROLES_TMPL = """# 占位符角色声明（{lang}）。留空是合法状态：config_check 只警告、不报错。
# 填法见同目录 zh.toml：`角色 = [占位符…]`，用来说明 %1 / %2 在句子里站什么位置
# （主语、宾语、数量…），给「需要重排语序」的语言做参考。
# {lang} 语序与英语一致时不必填。
"""

LANG_RULES_TMPL = '''# -*- coding: utf-8 -*-
"""__LANG_NAME__：显式不处理（no-op）。放在这里是为了让「不处理」是一份声明。

逐条对着流水线会做的事：

* 补空格：__LANG_NAME__用空格分词，词与词之间已经分开，中文那套「按字数预算成组」不适用；
* 标点：拉丁语种标点前面不留空格，与英语一致，没有可补的；
* 引号：沿用零售版写法，不强制改成直引号（直引号检查是中文那一支的规则）；
* 半角→全角：没有 CJK 语境，不需要；
* 目标文字判据：拉丁字母语言，`SCRIPT` 不声明，进度按「与英文原文不同」计。

**字形**：见 `font-map.ini` 的 `[__LANG__]` 注释 —— 原版正文体是否覆盖本语言字母、
标题体缺哪些，都是 fontTools 读 cmap 实测的结论，不要凭「拉丁字体应该有」推断。
"""

from . import spec as S

LANG = "__LANG__"

#: 供 `engine_text --stats` / 文档引用的一句话理由。
SKIP = "空格分词、标点前置无空格、无 CJK 语境；字形覆盖见 font-map.ini 注释"


def spec():
    """显式透传：没有标点规则、没有分词器、不补空格。"""
    return S.LangSpec(code=LANG, punct=None,
                      segmenter=S.NullSegmenter(), spacing=S.NoSpacing())
'''


def reason_for(en):
    """一条英文原文「该不该译」的分类。返回值就是 keep 清单里的理由。"""
    v = en.strip()
    if v in KEYS:
        return "key"
    if v in IDS:
        return "id"
    if v.startswith("scenario"):
        return "save-name"
    if v in CREDITS:
        return "credit"
    if v in SHORT_LABELS:
        return "label"
    words = v.split()
    if words and all(NAMEWORDS.match(w) or w in PARTICLES for w in words) \
            and not v.endswith(":"):
        return "name"
    return "same"


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, text, dry, log, name):
    if dry:
        log("  [dry] 将写 %s（%d 字节）" % (name, len(text.encode("utf-8"))))
        return "dry"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    log("  写入 %s" % name)
    return "done"


def _insert(text, anchor_re, addition, name, dry, log):
    """在锚点行之后插入一行；已存在同名内容就跳过（幂等）。"""
    if addition.strip() in text:
        log("  %s 已有该行，跳过" % name)
        return text, "skip"
    m = re.search(anchor_re, text, re.M)
    if not m:
        raise SystemExit("找不到插入锚点（%s）：%s" % (name, anchor_re))
    end = m.end()
    return text[:end] + "\n" + addition + "\n" + text[end:], _write_state(dry, log, name)


def _write_state(dry, log, name):
    if dry:
        log("  [dry] 将改 %s" % name)
        return "dry"
    return "done"


def font_glyph_report(root, lang, alphabet):
    """实测原版四个字体覆盖本语言字母表没有；返回 [(文件名, 缺字数, 缺字)]。"""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    fonts = os.path.join(root, "assets", "fonts", "original")
    if not os.path.isdir(fonts):
        return None
    out = []
    for name in ("ARIAL.TTF", "ELGRECO_.TTF", "Tiepolo_black.ttf", "Tiepolo_bold.ttf"):
        path = os.path.join(fonts, name)
        if not os.path.isfile(path):
            continue
        font = TTFont(path, lazy=True)
        cmap = font.getBestCmap()
        missing = "".join(ch for ch in alphabet if ord(ch) not in cmap)
        out.append((name, len(cmap), missing))
        font.close()
    return out


def scaffold(root, lang, alias, alphabet=None, ref=None, dry=False, log=print,
             force=False):
    src = os.path.join(root, "src")
    steps = []

    # 1. 译文文件：复制英文基准
    en_path = os.path.join(src, "orig", BASE + ".toml")
    tr_path = os.path.join(src, "translations", lang + ".toml")
    if force or not os.path.exists(tr_path):
        base = _read(en_path)
        steps.append(("translations", _write(tr_path, base, dry, log, tr_path)))
    else:
        log("  translations/%s.toml 已存在，保留（要重建加 --force）" % lang)
        steps.append(("translations", "keep"))

    # 2. 语言包标记
    pack_path = os.path.join(src, "packs", lang + ".toml")
    if force or not os.path.exists(pack_path):
        steps.append(("pack", _write(pack_path,
                                     PACK_TMPL.format(alias=alias, lang=lang, base=BASE),
                                     dry, log, pack_path)))
    else:
        log("  packs/%s.toml 已存在，保留" % lang)
        steps.append(("pack", "keep"))

    # 3. 占位符角色存根
    pr_path = os.path.join(src, "data", "placeholder_roles", lang + ".toml")
    if force or not os.path.exists(pr_path):
        steps.append(("placeholder_roles",
                      _write(pr_path, PLACEHOLDER_ROLES_TMPL.format(lang=lang),
                             dry, log, pr_path)))
    else:
        log("  placeholder_roles/%s.toml 已存在，保留" % lang)
        steps.append(("placeholder_roles", "keep"))

    # 4. 有意不译清单：与参照版逐条比
    keep_path = os.path.join(src, "data", "keep_as_is", lang + ".txt")
    if force or not os.path.exists(keep_path):
        ref_path = None
        if ref:
            ref_path = os.path.join(src, "orig", ref + ".toml")
        else:
            for name in os.listdir(os.path.join(src, "orig")):
                if name.startswith(lang + ".") and name != lang + ".toml":
                    ref_path = os.path.join(src, "orig", name)
                    break
        if ref_path and os.path.isfile(ref_path):
            import tomllib
            with open(en_path, "rb") as fh:
                en = tomllib.load(fh)
            with open(ref_path, "rb") as fh:
                rv = tomllib.load(fh)
            keep, diff = [], 0
            for hid, value in en.items():
                other = rv.get(hid)
                if other is None or str(other).strip() == str(value).strip():
                    keep.append((hid, reason_for(str(value))))
                else:
                    diff += 1
            head = KEEP_HEAD.replace("<参照文件>", os.path.basename(ref_path))
            body = "".join("%s\t%s\n" % (h, w) for h, w in keep)
            steps.append(("keep_as_is", _write(keep_path, head + "\n" + body,
                                               dry, log, keep_path)))
            log("  参照版 %d 条与英文不同（这些要照零售版落盘，不列进 keep）"
                % diff)
        else:
            log("  没有 %s 的官方参照版，keep 清单留空（先译着，之后补）" % lang)
            steps.append(("keep_as_is", "skip"))
    else:
        log("  keep_as_is/%s.txt 已存在，保留" % lang)
        steps.append(("keep_as_is", "keep"))

    # 5. lang_rules 模块 + REGISTRY
    lr_path = os.path.join(src, "tools", "text", "lang_rules", lang + ".py")
    if force or not os.path.exists(lr_path):
        steps.append(("lang_rules", _write(lr_path,
                                           LANG_RULES_TMPL.replace("__LANG_NAME__", alias)
                                           .replace("__LANG__", lang),
                                           dry, log, lr_path)))
    else:
        log("  lang_rules/%s.py 已存在，保留" % lang)
        steps.append(("lang_rules", "keep"))
    init_path = os.path.join(src, "tools", "text", "lang_rules", "__init__.py")
    text = _read(init_path)
    if '"%s"' % lang in text.split("REGISTRY = ")[1].split("\n")[0]:
        log("  REGISTRY 已登记 %s" % lang)
        steps.append(("registry", "skip"))
    else:
        m = re.search(r'REGISTRY = \(([^)]*)\)', text)
        if not m:
            raise SystemExit("REGISTRY 形状变了，手工登记 %s" % lang)
        entries = [e.strip() for e in m.group(1).split(",") if e.strip()]
        entries.append('"%s"' % lang)
        text = text[:m.start()] + "REGISTRY = (" + ", ".join(entries) + ")" + text[m.end():]
        steps.append(("registry", _write(init_path, text, dry, log, init_path)))

    # 6. font-map.ini 的 [lang]
    fm_path = os.path.join(src, "font-map.ini")
    text = _read(fm_path)
    if re.search(r"^\s*\[%s\]" % re.escape(lang), text, re.M):
        log("  font-map.ini 已有 [%s]" % lang)
        steps.append(("font_map", "skip"))
    else:
        block = ("\n[%s]\n"
                 "; 先回落原版字体：缺哪些字形以 fontTools 读 cmap 的实测为准（见本脚本结尾）。\n"
                 "ARIAL.TTF=none\nELGRECO_.TTF=none\nTiepolo_black.ttf=none\nTiepolo_bold.ttf=none\n"
                 % lang)
        text = text.rstrip("\n") + "\n" + block
        steps.append(("font_map", _write(fm_path, text, dry, log, fm_path)))

    # 7. line_run 的 SKIP
    lr2 = os.path.join(src, "tools", "analysis", "line_run.py")
    text = _read(lr2)
    body = text.split("SKIP = {", 1)[1].split("}", 1)[0]
    if '"%s"' % lang in body:
        log("  line_run SKIP 已有 %s" % lang)
        steps.append(("line_run", "skip"))
    else:
        add = '    "%s": "空格分词，按字数定上限不适用",' % lang
        text, state = _insert(text, r"SKIP = \{\n", add, "line_run.py", dry, log)
        steps.append(("line_run", state))
        if state != "dry":
            _write(lr2, text, dry, log, lr2)

    # 8. src/tools/README.md 脚本地图
    tr_readme = os.path.join(src, "tools", "README.md")
    text = _read(tr_readme)
    if "`text/lang_rules/%s.py`" % lang in text:
        log("  脚本地图已有 lang_rules/%s.py" % lang)
        steps.append(("tools_readme", "skip"))
    else:
        row = ("| `text/lang_rules/%s.py` | %s：显式 no-op（「不处理」是一份声明，不是缺失） |"
               % (lang, alias))
        anchor = r"\n\| `text/lang_rules/[a-z]+\.py` \|[^\n]*"
        ms = list(re.finditer(anchor, text))
        if not ms:
            raise SystemExit("脚本地图找不到 lang_rules 行，手工加 `text/lang_rules/%s.py`" % lang)
        end = ms[-1].end()
        text = text[:end] + "\n" + row + text[end:]
        steps.append(("tools_readme", _write(tr_readme, text, dry, log, tr_readme)))

    # 9. README 完成度表
    rm_path = os.path.join(root, "README.md")
    text = _read(rm_path)
    if re.search(r"\| .*\`%s\` \|" % re.escape(lang), text):
        log("  README 完成度表已有 %s" % lang)
        steps.append(("readme_table", "skip"))
    else:
        n_keep = 0
        if os.path.isfile(keep_path):
            n_keep = sum(1 for line in _read(keep_path).splitlines()
                         if line.strip() and not line.startswith("#"))
        total = sum(1 for line in _read(en_path).splitlines() if line.strip())
        translatable = max(total - n_keep, 0)
        row = "| %s `%s` | 0 / %d（0%%） | %d | %d |" % (
            alias, lang, translatable, translatable, n_keep)
        m = re.search(r"\n\| 语言 \| 已译 / 可译 \| 待译 \| 有意不译 \|\n\|[-| ]+\|\n((?:\|[^\n]*\n)+)",
                      text)
        if not m:
            raise SystemExit("README 完成度表形状变了，手工加 %s 行" % lang)
        end = m.end(1)
        text = text[:end] + row + "\n" + text[end:]
        steps.append(("readme_table", _write(rm_path, text, dry, log, rm_path)))

    # 字形实测（不改文件，只报结论）
    report = font_glyph_report(root, lang, alphabet) if alphabet else None
    return steps, report


def main():
    ap = argparse.ArgumentParser(description="加一门语言：自动建骨架并实测字形")
    ap.add_argument("--lang", required=True, help="语言代码，如 pl")
    ap.add_argument("--alias", help="语言名，如 Polski（写进 packs 与 README）")
    ap.add_argument("--alphabet", default="",
                    help="本语言特有字母串，用来实测原版字体覆盖，如 ąćęłńóśźż")
    ap.add_argument("--ref", default="", help="官方参照版文件名（src/orig 下，不带 .toml）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="覆盖已有文件（重建骨架时用）")
    ap.add_argument("--src", default=DEFAULT_SRC, help="仓库根（默认自动定位）")
    a = ap.parse_args()
    if not a.alias:
        raise SystemExit("要 --alias（语言名），它会写进语言包标记与 README")
    log = (lambda m: print("[dry] " + m)) if a.dry_run else print
    steps, report = scaffold(a.src, a.lang, a.alias, a.alphabet, a.ref,
                             a.dry_run, log, a.force)
    print("\n步骤：" + "、".join("%s=%s" % (k, v) for k, v in steps))

    if report:
        print("\n原版字形实测（fontTools 读 cmap）：")
        for name, total, missing in report:
            print("  %-20s 码位 %4d  缺 %2d  %s"
                  % (name, total, len(missing), missing or "—"))
        body = [r for r in report if r[0].startswith("ARIAL")]
        heads = [r for r in report if not r[0].startswith("ARIAL")]
        if body and body[0][2]:
            print("  结论：正文体也缺（%s）→ 正文要从 Latin 基线（Noto Sans）重建" % body[0][2])
        if heads and any(r[2] for r in heads):
            print("  结论：标题体缺字 → 用 src\\tools\\font\\build_lat_fonts.py 生成替换字体，"
                  "再把 font-map.ini 的 [%s] 三个标题槽位指过去" % a.lang)
    elif a.alphabet:
        print("\n字形实测跳过：没装 fontTools（pip install fonttools）")

    print("\n剩下必须人工的（脚本无法判断对错）：")
    print("  · 译文本身；术语表 src\\data\\terms\\%s.toml（缺了就只报警告）" % a.lang)
    print("  · 诗谜谜底要随译文带 [ans:…]，不然 text_lint 出 W")
    print("  · docs\\译文与语言包.md、docs\\待定.md 的叙述段")
    print("  · 实机截图：标题换字体后要和英文标题同高同宽")
    return 0


if __name__ == "__main__":
    sys.exit(main())
