#!/usr/bin/env python3
# coding: utf-8
"""ref_check.py —— 参照版健康检查（落盘前的「这批参照能不能照抄」）。

为什么要有这个：新语言的零售/官方文本是整批照抄的参照。可它是**别人的
成品**，不是校验过的数据 —— 本轮 pl 的 2744 条里有 7 条自带毛病：4 条占位符
写坏（少 `@`、漏 `%3`）、2 条多插 `<n>`、1 条在 255 字符处截断。`translate.py
apply` 的门禁能拦住它们，但只在**逐条落盘**时才吐出来，而且吐在几千条的批次
中间；想事先知道「哪几条别照抄」，此前没有入口。

三类判定：

  E（照抄必被拦）：令牌不齐、标签个数不齐（`<n>` 多/少一个）。
  W（照抄大概坏）：疑似截断 —— 比基准短一大截、或正好停在 255 字符、
     或以逗号／连接词收尾（句子没说完）。
  · 与基准逐字相同的不算问题，只计数：那是没翻，不是坏数据。

只比对两边都在的 id；参照版多出来的版本差条目跳过并计数。

    python src/tools/analysis/ref_check.py --ref src/orig/pl.retail-1.0.0.toml
    python src/tools/analysis/ref_check.py --ref <...>.toml --all   # 列出全部命中

退出码：有 E 级命中时返回 1。
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import translate as T                                  # noqa: E402
from shared.core.validate import tag_literals, token_counts  # noqa: E402

BASE = os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")
QA_DIR = os.path.join(ROOT, "build", "qa")

#: 疑似截断的两条尺寸线索：比基准短到这个比例（波兰语零售版中位比 1.01，
#: 缩到 0.75 以下就不是「译得简洁」而是掉了后半句），或正好落在 255 字符上
#: （导出工具的一行上限）。
SHORT_RATIO, SHORT_MIN_BASE, HARD_LIMIT = 0.75, 120, 255
#: 收尾这些字符说明句子断在半截。
DANGLING = (",", ";", "-", "i", "oraz", "albo", "lub", "iż", "że")


def _ends_sentence(text):
    return text.rstrip()[-1:] in (".", "!", "?", ")", "…", "”", '"', "'")


def _dangling(text):
    tail = text.rstrip()
    if not tail:
        return False
    if tail.endswith((",", ";", "-", ":")):
        return True
    last = tail.rsplit(None, 1)[-1].lower()
    return last in DANGLING


def _counts(seq):
    out = {}
    for item in seq:
        out[item] = out.get(item, 0) + 1
    return out


def check(ref_path, base_path=BASE):
    import tomllib
    with open(base_path, "rb") as f:
        base = tomllib.load(f)
    with open(ref_path, "rb") as f:
        ref = tomllib.load(f)

    common = [hid for hid in ref if hid in base]
    extra = len(ref) - len(common)
    e_rows, w_rows, same = [], [], 0
    for hid in common:
        b, r = str(base[hid] or ""), str(ref[hid] or "")
        if not r:
            if b:
                w_rows.append((hid, "空值（基准有正文）"))
            continue
        if b == r:
            same += 1
            continue
        tok_b, tok_r = _counts(token_counts(b)), _counts(token_counts(r))
        if tok_b != tok_r:
            e_rows.append((hid, "令牌不齐：基准 %s 参照 %s" % (tok_b, tok_r)))
            continue
        tag_b, tag_r = _counts(tag_literals(b)), _counts(tag_literals(r))
        if tag_b != tag_r:
            diff = "、".join("%s 基准 %d 参照 %d" % (t, tag_b.get(t, 0), tag_r.get(t, 0))
                            for t in sorted(set(tag_b) | set(tag_r))
                            if tag_b.get(t, 0) != tag_r.get(t, 0))
            e_rows.append((hid, "标签个数不齐：%s" % diff))
            continue
        if len(r) == HARD_LIMIT and not _ends_sentence(r):
            w_rows.append((hid, "正好停在 %d 字符且收尾不完整（疑似截断）" % HARD_LIMIT))
        elif len(b) >= SHORT_MIN_BASE and len(r) < len(b) * SHORT_RATIO:
            w_rows.append((hid, "长度骤降：基准 %d 参照 %d 字符" % (len(b), len(r))))
        elif _dangling(r) and _ends_sentence(b):
            w_rows.append((hid, "收尾悬空（参照停在连词/逗号）：…%s" % r.rstrip()[-24:]))
            w_rows.append((hid, "收尾悬空（参照停在连词/逗号）：…%s" % r.rstrip()[-24:]))
    return e_rows, w_rows, same, extra, len(common)


def main(argv=None):
    ap = argparse.ArgumentParser(description="参照版健康检查")
    ap.add_argument("--ref", required=True, help="参照译文（src\\orig 下的 toml）")
    ap.add_argument("--base", default=BASE, help="英文基准表")
    ap.add_argument("--all", action="store_true", help="打印全部命中（默认各列 20 条）")
    args = ap.parse_args(argv)

    ref = args.ref if os.path.isabs(args.ref) else os.path.join(ROOT, args.ref)
    name = os.path.splitext(os.path.basename(ref))[0]
    e_rows, w_rows, same, extra, common = check(ref, args.base)
    lines = ["# 参照版健康检查：%s" % os.path.relpath(ref, ROOT), ""]
    lines.append("可对照 %d 条（参照版另有 %d 条不在基准表里，版本差，跳过）"
                 % (common, extra))
    lines.append("与基准逐字相同 %d 条（没翻，不算坏）" % same)
    lines.append("")
    lines.append("E 级 %d 条（照抄必被 apply 拦）：" % len(e_rows))
    for hid, why in (e_rows if args.all else e_rows[:20]):
        lines.append("  %s  %s" % (hid, why))
    lines.append("")
    lines.append("W 级 %d 条（照抄大概坏，逐条看）：" % len(w_rows))
    for hid, why in (w_rows if args.all else w_rows[:20]):
        lines.append("  %s  %s" % (hid, why))
    text = "\n".join(lines) + "\n"
    print(text)
    os.makedirs(QA_DIR, exist_ok=True)
    out = os.path.join(QA_DIR, "ref_check_%s.txt" % name)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("报告：%s" % os.path.relpath(out, ROOT))
    return 1 if e_rows else 0


if __name__ == "__main__":
    sys.exit(main())
