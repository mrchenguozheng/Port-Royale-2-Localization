#!/usr/bin/env python3
# coding: utf-8
"""line_run.py —— 断行长度复核：断完之后，最长的一段有没有超过上限。

引擎只在 U+0020 与 `<n>` 处断行；一段里没有这两样，就永远排在同一行。
所以「最长段」是唯一能机械度量的断行指标——不是像素宽度（控件宽度没实测过）。

口径（与 dist/断行观察窗.html 完全同一份实现，页面直接 import 本模块）：

  · 断点：普通空格、`<n>` / `<n:N>`；
  · 计字：可见字数，标签 `<…>` 与标注 `[….]` 不计；
  · 变量 `%1` / `@a$Name$` 记 1 字（引擎渲染成数字，宽度与一个字相当）；
  · 片段分类：含 CJK/假名/谚文 → 正文；纯拉丁字母 → 单词；其余（路径、编号、
    键名）→ 技术串。CJK 语言只判正文——长路径不是「该补空格」的问题。

上限与级别
----------
  zh  14  E   中文 DP 预算 13，不可拆单位允许溢出到 14；>14 即回归
  ja  13  W   日语同一全角预算（方块字，同一控件装得下同样的字数）；
              当前 460 条超限，属待办，先提示不卡流水线
  ko  13  W   韩语同一全角预算；当前 9 条正文超限
  ru/de/es/fr  显式跳过：拉丁文字按空格断行，最长段就是一个单词，
              长度由词典与构词决定，补空格解决不了（见 SKIP 里的理由）

改上限是一个数字，改级别是一个字母；两处都在 LIMITS 里。

    python src/tools/analysis/line_run.py            # 摘要
    python src/tools/analysis/line_run.py --all      # 列出每条命中
    python src/tools/analysis/line_run.py --lang ja  # 只跑一门

退出码：有 E 级命中时返回 1。
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))

import engine_text  # noqa: E402

QA_DIR = os.path.join(ROOT, "build", "qa")

#: 上限（含）与级别。E 级命中即让流水线失败，W 级只报告。
LIMITS = {
    "zh": (14, "E"),
    "ja": (13, "W"),
    "ko": (13, "W"),
}

#: 显式跳过。没有要处理的东西也必须写清理由，别留空白。
SKIP = {
    "ru": "西里尔字母按空格断行，最长段=单词，长度由构词决定",
    "de": "拉丁字母按空格断行，复合词长度由构词决定，补空格解决不了",
    "es": "拉丁字母按空格断行，最长段=单词",
    "fr": "拉丁字母按空格断行，最长段=单词",
}

#: 只判「正文段」的语言：长路径/编号不该被算作排版缺口。
TEXT_ONLY = {"zh": True, "ja": True, "ko": True}

NL = re.compile(r"<n(?::\d+)?>")
VAR = re.compile(r"@[A-Za-z]\$[A-Za-z0-9_]*\$|%0?\d+[A-Za-z]?|%[A-Za-z]")
TAG = re.compile(r"<[^<>]*>|\[[^\[\]]*\]")
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff01-\uff60]")


def segments(text):
    """按引擎真实断点切段，返回 [(可见字数, 片段)]。"""
    s = NL.sub("\u0000", text)                    # 硬换行就是断点
    s = VAR.sub("\u25cf", s)                      # 变量记 1 字
    out = []
    for chunk in re.split(r"[\s\u0000]", s):
        out.append((len(TAG.sub("", chunk)), TAG.sub("", chunk)))
    return out


def kind_of(seg):
    """正文 / 单词 / 技术串。"""
    if CJK.search(seg):
        return "text"
    if re.fullmatch(r"[A-Za-z\u00c0-\u024f'’\-]+", seg or ""):
        return "word"
    return "tech"


def longest(text):
    """(最长段字数, 该片段, 类型)。"""
    segs = segments(text)
    if not segs:
        return 0, "", "tech"
    w, seg = max(segs, key=lambda x: x[0])
    return w, seg, kind_of(seg)


def scan_lang(lang):
    """从译文层现算引擎文本，返回 [(key, 字数, 片段, 类型)]，按字数降序。"""
    order, out, _stats, _seg = engine_text.generate(lang)
    rows = []
    for h in order:
        v = out.get(h)
        if not v:
            continue
        w, seg, kind = longest(v)
        rows.append((h, w, seg, kind))
    rows.sort(key=lambda x: -x[1])
    return rows


def report(lang, rows, limit, level, text_only, show_all):
    """写报告文件并返回 E 级命中条数。"""
    hits = [(h, w, seg, k) for h, w, seg, k in rows
            if w > limit and (k == "text" or not text_only)]
    os.makedirs(QA_DIR, exist_ok=True)
    path = os.path.join(QA_DIR, "line_run_%s.txt" % lang)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# %s：上限 %d 字（%s 级）%s\n" % (
            lang, limit, level, "，只判正文段" if text_only else ""))
        f.write("# 测量口径：只在空格与 <n> 处断行；标签不计字，变量记 1 字\n")
        f.write("命中 %d 条\n" % len(hits))
        for h, w, seg, k in (hits if show_all else hits[:40]):
            f.write("%s  最长 %d 字（%s）  %s\n" % (h, w, k, seg[:120]))
        if not show_all and len(hits) > 40:
            f.write("… 其余 %d 条见 --all\n" % (len(hits) - 40))
    worst = hits[0] if hits else None
    print("%-3s 上限 %-2d（%s） 命中 %-4d 最长 %-3d%s  → %s"
          % (lang, limit, level, len(hits), rows[0][1] if rows else 0,
             (" " + worst[0] + " " + str(worst[1])) if worst else "",
             os.path.relpath(path, ROOT)))
    return len(hits) if level == "E" else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="")
    ap.add_argument("--all", action="store_true", help="列出全部命中")
    a = ap.parse_args(argv)

    langs = [a.lang] if a.lang else list(LIMITS) + list(SKIP)
    bad = 0
    for lang in langs:
        if lang in SKIP:
            print("%-3s 跳过（显式声明）：%s" % (lang, SKIP[lang]))
            continue
        if lang not in LIMITS:
            print("%s 没有上限配置，跳过" % lang)
            continue
        limit, level = LIMITS[lang]
        rows = scan_lang(lang)
        bad += report(lang, rows, limit, level, TEXT_ONLY.get(lang, False), a.all)
    if bad:
        print("\nE 级命中 %d 条，流水线失败。" % bad)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
