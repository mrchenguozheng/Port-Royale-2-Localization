#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从仓库配置生成 `docs/语言矩阵.md`，并校验各语言集合的差值身份。

矩阵回答的是“这门语言到底在哪一层存在”：发行、预览、UI、语言包、译文、
实机截图、字体模式、发行分组。生成物不要手改；改配置后运行本脚本。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import language_registry as LR  # noqa: E402

ROOT = TOOLS.parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "语言矩阵.md"


def cn_number(value: int) -> str:
    digits = "零一二三四五六七八九"
    if value < 0 or value >= 100:
        return str(value)
    if value < 10:
        return digits[value]
    tens, ones = divmod(value, 10)
    return ("" if tens == 1 else digits[tens]) + "十" + (digits[ones] if ones else "")


def build(root: Path = ROOT) -> str:
    errors, warnings, rows = LR.audit(str(root))
    if errors:
        raise ValueError("\n".join(errors))
    release = [row.code for row in rows if row.release]
    preview = [row.code for row in rows if row.review_status == "preview"]
    release_count, preview_count, shot_count = LR.summary(rows)
    shot_actual = sum(1 for row in rows if row.screenshot and not row.screenshot_source)
    shot_derived = [row for row in rows if row.screenshot_source]
    ui_count = sum(1 for row in rows if row.ui)
    pack_count = sum(1 for row in rows if row.pack)

    if shot_derived:
        shot_line = ("- 实机截图：%s门实拍；%s，共覆盖%s门。" % (
            cn_number(shot_actual),
            "、".join("`%s` 沿用 `%s`" % (row.code, row.screenshot_source)
                      for row in shot_derived),
            cn_number(shot_count),
        ))
    else:
        shot_line = "- 实机截图：%s门实拍。" % cn_number(shot_actual)

    lines = [
        "# 语言矩阵",
        "",
        "> 由 `src/tools/docs/build_language_matrix.py` 从 `release-languages.txt`、",
        "> `release-bundles.toml`、`packs/*.toml`、`ui.*.ini`、`translations/*.toml`、",
        "> `font-map.ini` 与 `screenshots.json` 生成；不要手改。",
        "",
        "## 一套账",
        "",
        "- 发行（release）：%s，共%s门。" % ("、".join(f"`{x}`" for x in release), cn_number(release_count)),
        "- 预览（preview）：%s，共%s门；不进发行包。" % (
            "、".join(f"`{x}`" for x in preview) or "无", cn_number(preview_count)),
        "- UI 与语言包：%s门（`ui.<lang>.ini` / `packs/<lang>.toml`）。" % cn_number(ui_count),
        shot_line,
        "",
        "`zh-Hant` 是繁体派生底稿，不是发行代码；`zh-TW` / `zh-HK` 是两个发行代码。",
        "`zh-HK` 的大部分界面文案与 `zh-TW` 相同，截图沿用 `zh-TW`，不是独立实机验证。",
        "`pt-BR` 是预览语言，有 pack、译文、UI 和截图，但不在 `release-languages.txt`，"
        "也不进 `release-bundles.toml`。",
        "",
        "| 语言 | 名称 | 状态 | UI | 语言包 | 译文 | 截图 | 字体 | 分组 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        mark = lambda value: "✓" if value else "—"
        shot_cell = ("—" if not row.screenshot
                     else ("✓（同 `%s`）" % row.screenshot_source
                           if row.screenshot_source else "✓"))
        lines.append("| `%s` | %s | %s | %s | %s | %s | %s | `%s` | `%s` |" % (
            row.code,
            row.name.replace("|", "\\|"),
            "发行" if row.release else ("预览" if row.review_status == "preview" else row.review_status),
            mark(row.ui),
            mark(row.pack),
            mark(row.translation),
            shot_cell,
            row.font_mode,
            row.bundle,
        ))
    if warnings:
        lines += ["", "## 已知缺口", ""] + [f"- {w}" for w in warnings]
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只检查生成物是否最新")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        generated = build()
    except ValueError as exc:
        print("语言矩阵审计失败：\n%s" % exc, file=sys.stderr)
        return 1
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if generated != current:
            print("%s 不是最新生成物；运行 python src/tools/docs/build_language_matrix.py"
                  % args.output, file=sys.stderr)
            return 1
        print("%s 已是最新生成物" % args.output)
        return 0
    args.output.write_text(generated, encoding="utf-8", newline="\n")
    print("已生成 %s" % args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
