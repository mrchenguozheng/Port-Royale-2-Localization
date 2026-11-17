#!/usr/bin/env python3
# coding: utf-8
"""text_lint.py —— 把复查里已经定下的译文定则做成可重跑的检查。

原名 zh_lint.py，因检查范围早已扩到六语（模板、占位、标注、空值、同原文异译
对所有语言都适用，只有标点与引号几类是中文专有），更名为 text_lint.py。

判据全部来自 docs/界面映射/09-推断-连续键区.md 里已经落卷的结论，
这里只负责机械复核，不做判断。分级：

  E（必改）：模板与原文不一致、汉字旁的半角标点、直引号、`・`、空值
  W（提示）：本段新定则里「建议但历史遗留较多」的几类

已知豁免（写进来是为了不误报，不是放宽标准）：
  · 字体资源可换中文字形变体（`…aaFH.res` ↔ `…aaFHk.res`，09 卷定则）
  · `0xfc512ea5` 版权声明按 KEEP_ORIGINAL 保留英文原文
  · 纯符号／纯数字条目（字符清单、`,` 这种单标点）不进中文规则
  · 千分位 `1,000` 不算半角逗号
  · 含 `%` 或 `<` 的引擎格式串不算「连续空格」

    python src/tools/analysis/text_lint.py            # 摘要
    python src/tools/analysis/text_lint.py --all      # 打印全部命中
    python src/tools/analysis/text_lint.py --lang de  # 换一门语言跑模板类检查

退出码：有 E 级命中时返回 1。
"""

import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

EN = os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")
TR = os.path.join(ROOT, "src", "translations", "%s.toml")

# 模板只比「会被引擎解释的东西」：%N、@x$Name$、<n>/<c>/<t>/<ts:N>/<gs:…> 一类。
# 字体资源 <f:…> 不进模板（允许按字形替换，见 09 卷定则），另按资源名单独检查。
TPL = re.compile(r"%[0-9]+|@[a-zA-Z]\$[^$]*\$|<(?:n|c|t|ts:[0-9]+|gs:[^>]*|r|b)>|<\.[^>]*>")
FONT = re.compile(r"<f:([^>]*)>")
HAN = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]")
MARK_ANY = re.compile(r"\[(?:ref|lit|term):?")
ANS_MARK = re.compile(r"\[ans:")

KEEP = {"0xfc512ea5"}

sys.path.insert(0, os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from shared.core.validate import is_identifier  # noqa: E402
from text import marks as MK  # noqa: E402
import terms_check as TC  # noqa: E402


def norm_font(v):
    """把原文里坏掉的标签归一到合法写法（英文 0x103b68ea 的 `<.<n>` 是笔误）。"""
    return re.sub(r"<\.[^>]*>", "<n>", v)


def tpl_set(v):
    return sorted(TPL.findall(norm_font(v)))


def half_width_punct(v):
    """只在汉字紧邻半角标点时报；千分位、英文缩写里的逗号不算。"""
    hits = []
    if re.search(r"[\u4e00-\u9fff）)」”]\s*,", v):
        hits.append("半角逗号")
    if re.search(r",\s*[\u4e00-\u9fff]", v):
        hits.append("半角逗号")
    if re.search(r"[\u4e00-\u9fff）)」”]\s*\.(?![0-9])", v):
        hits.append("半角句号")
    if re.search(r"\.\s*[\u4e00-\u9fff]", v):
        hits.append("半角句号")
    return sorted(set(hits))


def main(argv):
    lang = "zh"
    show_all = "--all" in argv
    if "--lang" in argv:
        lang = argv[argv.index("--lang") + 1]
    en = tomllib.load(open(EN, "rb"))
    tr_raw = tomllib.load(open(TR % lang, "rb"))
    # 规则比对一律用展开后的文本：否则 [ref:Tortuga]的麻烦 与字面「托尔图加的麻烦」
    # 会被当成同原文异译。标注本身的检查另走 check_doc（用带标注原文）。
    tr = MK.expand_doc(lang, tr_raw)
    zh_mode = lang == "zh"

    E, W = [], []

    for k, v in tr.items():
        if k in KEEP:
            continue
        src = en.get(k)
        # 纯符号／纯数字条目：字符清单、单个标点，不参与中文规则
        if zh_mode and not HAN.search(v) and not LATIN.search(v):
            if src is not None and tpl_set(v) != tpl_set(src):
                E.append((k, "模板不一致", "EN=%s | %s=%s" % (tpl_set(src), lang, tpl_set(v))))
            continue

        if src is not None and not is_identifier(src) and tpl_set(v) != tpl_set(src):
            E.append((k, "模板不一致", "EN=%s | %s=%s" % (tpl_set(src), lang, tpl_set(v))))
        if not str(v).strip():
            E.append((k, "空值", repr(v)))
        if not zh_mode:
            continue

        if "\u30fb" in v:
            E.append((k, "片假名中点・", v[:60]))
        if '"' in v:
            E.append((k, "直引号", v[:60]))
        for h in half_width_punct(v):
            E.append((k, h, v[:60]))
        if re.search(r"[0-9]+\s+[年月日天艘张名条个人次]", v):
            W.append((k, "数字与量词间有空格", v[:60]))
        if "您" in v:
            W.append((k, "称谓混用您", v[:60]))
        if "%" not in v and "<" not in v and re.search(r"[^\s<]\s{2,}[^\s>]", v.replace("<n>", "")):
            W.append((k, "连续空格", v[:60]))
        if "\u3000" in v:
            W.append((k, "全角空格", v[:60]))

    if zh_mode:
        byen = {}
        for k, v in en.items():
            if k in tr:
                byen.setdefault(v, []).append(k)
        for src, keys in byen.items():
            outs = {tr[k]: k for k in keys}
            if len(outs) > 1 and len(src) > 8:
                W.append((sorted(keys)[0], "同原文异译 %d 种" % len(outs),
                          " / ".join(sorted(outs))[:120]))

    # 内联标注（[ref:…] / [lit:…] / [term:…]）：未定义引用、缺形态、方括号写错、死条目
    for p in MK.check_doc(lang, tr_raw, entities=MK.load_entities()):
        E.append(("标注", "标注", p))

    # 诗谜整片不许挂 ref/lit/term：谜面的用词由韵脚和字数决定，这几种标注会把词冻成
    # 表里的写法，谜语也被提前泄底（`Holy August` 的双关就没了）。诗里只写自由文本，
    # 谜底另走 [ans:实体]——只给翻译人看，展开为空。
    _g, _ig, verse = TC.load_terms()
    vids = sorted(TC.verse_ids(verse, en), key=lambda x: int(x, 16))
    for k in vids:
        if MARK_ANY.search(tr_raw.get(k, "") or ""):
            E.append((k, "诗谜挂标注", tr_raw[k][:60]))
    no_ans = [k for k in vids if not ANS_MARK.search(tr_raw.get(k, "") or "")]
    if no_ans:
        W.append(("诗谜", "缺谜底 %d 条" % len(no_ans),
                  "已标 %d/%d，第一个缺：%s"
                  % (len(vids) - len(no_ans), len(vids), no_ans[0])))

    lines = []
    lines.append("# %s 机械复核（判据见 09 卷已落卷定则）\n" % lang)
    lines.append("E 级 %d 条，W 级 %d 条。\n" % (len(E), len(W)))
    for tag, items in (("E", E), ("W", W)):
        shown = items if show_all else items[:40]
        for k, why, ctx in shown:
            lines.append("%s %-12s %-16s %s" % (tag, k, why, ctx))
        if len(items) > len(shown):
            lines.append("（%s 级另有 %d 条，用 --all 看全）" % (tag, len(items) - len(shown)))

    text = "\n".join(lines) + "\n"
    print(text)
    out = os.path.join(ROOT, "build", "qa", "text_lint_%s.txt" % lang)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, "w", encoding="utf-8", newline="").write(text)
    print("报告：%s" % os.path.relpath(out, ROOT))
    return 1 if E else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
