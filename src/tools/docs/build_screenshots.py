#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从结构化数据生成实机截图画廊。

页面结构、CSS 与灯箱脚本在 ``screenshots_template.html`` 里；图注、说明、
覆盖点和补充屏在 ``docs/screenshots.json`` 里；图片是否存在、尺寸与字节数
以 ``docs/assets/screenshots/manifest.json`` 为准。生成物是
``docs/screenshots.html``，不要手改它。

用法::

    python src/tools/docs/build_screenshots.py
    python src/tools/docs/build_screenshots.py --check

``--check`` 只比较生成结果与现有 HTML，不写文件；供测试和 CI 使用。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA = ROOT / "docs" / "screenshots.json"
DEFAULT_TEMPLATE = Path(__file__).with_name("screenshots_template.html")
DEFAULT_OUTPUT = ROOT / "docs" / "screenshots.html"


def cn_number(value: int) -> str:
    """把 1–99 写成中文数字；画廊只需要“五”“十一”这类小数目。"""
    digits = "零一二三四五六七八九"
    if value < 0 or value >= 100:
        return str(value)
    if value < 10:
        return digits[value]
    tens, ones = divmod(value, 10)
    prefix = "" if tens == 1 else digits[tens]
    return prefix + "十" + (digits[ones] if ones else "")


def inline(value: str) -> str:
    """转义文本，并把 `code` 与 **bold** 转成页面里的行内标记。"""
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", lambda m: "<code>" + m.group(1) + "</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", lambda m: "<b>" + m.group(1) + "</b>", text)
    return text


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def collect_manifest(data: dict, docs_root: Path) -> list[dict]:
    """校验清单、图片实际尺寸/字节数与数据引用，返回整份清单。"""
    page = data["page"]
    languages = data["languages"]
    screens = data["screens"]
    extras = data.get("extras", [])
    if not languages or not screens:
        raise ValueError("screenshots.json 里 languages/screens 不能为空")

    manifest_path = docs_root / page.get("manifest", "assets/screenshots/manifest.json")
    image_root = docs_root / page.get("image_root", "assets/screenshots")
    expected_width = int(page.get("image_width", 1600))
    expected_height = int(page.get("image_height", 1200))

    entries = load_json(manifest_path)
    if not isinstance(entries, list):
        raise ValueError("manifest.json 顶层必须是数组")

    by_key: dict[tuple[str, str], dict] = {}
    by_file: dict[str, dict] = {}
    for entry in entries:
        key = (entry["language"], entry["slug"])
        if key in by_key:
            raise ValueError(f"manifest.json 重复条目：{key}")
        if entry["file"] in by_file:
            raise ValueError(f"manifest.json 重复文件：{entry['file']}")
        by_key[key] = entry
        by_file[entry["file"]] = entry

    used: set[tuple[str, str]] = set()
    for screen in screens:
        slug = screen["slug"]
        captions = screen.get("captions", {})
        for lang in languages:
            code = lang["code"]
            key = (code, slug)
            entry = by_key.get(key)
            if entry is None:
                raise ValueError(f"manifest.json 缺少 {code}/{slug}")
            if entry["title"] != screen["title"]:
                raise ValueError(
                    f"{code}/{slug} 清单标题 {entry['title']!r} 与数据 {screen['title']!r} 不一致"
                )
            if code not in captions:
                raise ValueError(f"{code}/{slug} 缺少图注")
            image_path = image_root / entry["file"]
            if not image_path.is_file():
                raise ValueError(f"归档图不存在：{image_path}")
            if entry.get("width") != expected_width or entry.get("height") != expected_height:
                raise ValueError(
                    f"{entry['file']} 尺寸 {entry.get('width')}×{entry.get('height')}，"
                    f"期望 {expected_width}×{expected_height}"
                )
            if image_path.stat().st_size != entry["bytes"]:
                raise ValueError(
                    f"{entry['file']} 实际 {image_path.stat().st_size} B，"
                    f"清单写 {entry['bytes']} B"
                )
            used.add(key)

    for extra in extras:
        filename = extra["file"]
        entry = by_file.get(filename)
        if entry is None:
            raise ValueError(f"manifest.json 缺少补充屏 {filename}")
        key = (entry["language"], entry["slug"])
        if key in used:
            raise ValueError(f"补充屏重复引用：{filename}")
        image_path = image_root / filename
        if not image_path.is_file():
            raise ValueError(f"补充屏不存在：{image_path}")
        if image_path.stat().st_size != entry["bytes"]:
            raise ValueError(
                f"{filename} 实际 {image_path.stat().st_size} B，清单写 {entry['bytes']} B"
            )
        used.add(key)

    unused = set(by_key) - used
    if unused:
        raise ValueError("manifest.json 有条目未被页面引用：" + ", ".join(sorted(unused)))

    compare_count = len(screens) * len(languages)
    total = len(entries)
    if compare_count + len(extras) != total:
        raise ValueError(
            f"页面计算 {compare_count}+{len(extras)}={compare_count + len(extras)} 张，"
            f"清单是 {total} 张"
        )
    return entries


def groups_of(languages: list[dict], columns: int) -> list[list[dict]]:
    return [languages[i:i + columns] for i in range(0, len(languages), columns)]


def render_chips(page: dict, languages: list[dict], total: int) -> str:
    chips = [
        page.get("version", ""),
        page.get("package", ""),
        " / ".join(lang["native"] for lang in languages),
        page.get("date", ""),
        page.get("image_note", ""),
        f"{total} 张",
    ]
    return "\n".join(
        f'      <span class="chip">{inline(chip)}</span>'
        for chip in chips if chip
    )


def render_toc(page: dict) -> str:
    links = [
        f'      <a href="{html.escape(item["href"])}">{inline(item["label"])}</a>'
        for item in page.get("toc", [])
    ]
    links.extend(
        [
            '      <a href="实机截图.md">Markdown 版</a>',
            '      <a href="README.md">文档索引</a>',
        ]
    )
    return "\n".join(links)


def render_coverage(
    page: dict, languages: list[dict], screens: list[dict], by_key: dict
) -> tuple[str, str]:
    head = "<th>#</th><th>屏</th><th>验证点</th>" + "".join(
        f"<th>{inline(lang['native'])}</th>" for lang in languages
    )
    rows = []
    for screen in screens:
        cells = [screen["num"], screen["title"], screen["verify"]]
        cells.extend(
            "✓" if (lang["code"], screen["slug"]) in by_key else "—"
            for lang in languages
        )
        rows.append(
            "      <tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in cells) + "</tr>"
        )
    return head, "\n".join(rows)


def render_figure(src: str, alt: str, native: str, caption: str, indent: str = "      ") -> str:
    return (
        f"{indent}<figure>\n"
        f'{indent}  <img src="{html.escape(src)}" alt="{inline(alt)}" decoding="sync">\n'
        f'{indent}  <figcaption><span class="lang">{inline(native)}</span> {inline(caption)}</figcaption>\n'
        f"{indent}</figure>"
    )


def render_sections(
    page: dict, languages: list[dict], screens: list[dict], by_key: dict
) -> str:
    image_root = page.get("image_root", "assets/screenshots")
    blocks = []
    for screen in screens:
        figures = []
        for lang in languages:
            entry = by_key[(lang["code"], screen["slug"])]
            figures.append(
                render_figure(
                    f"{image_root}/{entry['file']}",
                    f"{lang['alt']}{screen['title']}",
                    lang["native"],
                    screen["captions"][lang["code"]],
                )
            )
        blocks.append(
            "  <section class=\"row\">\n"
            "    <div class=\"row-head\">\n"
            f"      <div class=\"num\">{inline(screen['num'])}</div>\n"
            f"      <div><h3>{inline(screen['title'])}</h3><p>{inline(screen['desc'])}</p></div>\n"
            "    </div>\n"
            "    <div class=\"pair\">\n"
            + "\n".join(figures)
            + "\n    </div>\n  </section>"
        )
    return "\n\n".join(blocks)


def render_notes(notes: list[dict]) -> str:
    return "\n\n".join(
        f'  <p class="note"><b>{inline(note["title"])}</b>：{inline(note["body"])}</p>'
        for note in notes
    )


def render_extras(page: dict, extras: list[dict]) -> str:
    image_root = page.get("image_root", "assets/screenshots")
    blocks = []
    for extra in extras:
        blocks.append(
            render_figure(
                f"{image_root}/{extra['file']}",
                extra["alt"],
                extra["lang"],
                extra["caption"],
                indent="    ",
            )
        )
    return "\n".join(blocks)


def render_footer(
    page: dict, languages: list[dict], screens: list[dict], extras: list[dict], total: int
) -> str:
    image_root = page.get("image_root", "assets/screenshots")
    compare_count = len(screens) * len(languages)
    extra_count = len(extras)
    return (
        f"图片目录：<code>docs/{image_root}/</code> · "
        f"{cn_number(len(screens))}屏对照{cn_number(len(languages))}语共 {compare_count} 张，"
        f"加{inline(page.get('extra_label', '补充'))} {extra_count} 张，共 {total} 张 · "
        "机器可读清单：<code>manifest.json</code> · 截图口径与覆盖表见 "
        '<a href="实机截图.md">实机截图.md</a>'
    )


def build_html(data: dict, template: str, docs_root: Path) -> str:
    page = data["page"]
    languages = data["languages"]
    screens = data["screens"]
    extras = data.get("extras", [])
    notes = data.get("notes", [])

    entries = collect_manifest(data, docs_root)
    by_key = {(entry["language"], entry["slug"]): entry for entry in entries}
    columns = int(page.get("columns", 4))
    groups = groups_of(languages, columns)

    h1 = (
        page.get("heading_prefix", "实机截图：")
        + cn_number(len(languages))
        + "种语言"
        + cn_number(len(screens))
        + "屏对照"
    )
    page_title = (
        page.get("title_prefix", "实机截图 · ")
        + " / ".join(lang["short"] for lang in languages)
        + " · "
        + page.get("title_suffix", "")
    )

    lede_rows = []
    for index, group in enumerate(groups, 1):
        text = "/".join(lang["code"] for lang in group)
        if len(group) < columns:
            text += " 居中"
        lede_rows.append(f"第 {index} 行 {text}")
    lede = (
        f"同一组{cn_number(len(screens))}个界面，{cn_number(len(languages))}种语言"
        f"按{cn_number(columns)}列排："
        + "，".join(lede_rows)
        + "。"
        + page.get("lede_tail", "")
    )

    compare_sub = (
        f"{cn_number(columns)}列{cn_number(len(languages))}语："
        + " · ".join(" / ".join(lang["native"] for lang in group) for group in groups)
    )

    coverage_head, coverage_rows = render_coverage(page, languages, screens, by_key)

    replacements = {
        "{{PAGE_TITLE}}": inline(page_title),
        "{{EYEBROW}}": inline(page.get("eyebrow", "")),
        "{{H1}}": inline(h1),
        "{{LEDE}}": inline(lede),
        "{{META_CHIPS}}": render_chips(page, languages, len(entries)),
        "{{TOC}}": render_toc(page),
        "{{INTRO}}": inline(page.get("intro", "")),
        "{{COVERAGE_HEADING}}": inline(page.get("coverage_heading", "五屏覆盖")),
        "{{COVERAGE_SUB}}": inline(page.get("coverage_sub", "")),
        "{{COVERAGE_HEAD}}": coverage_head,
        "{{COVERAGE_ROWS}}": coverage_rows,
        "{{COMPARE_HEADING}}": inline(page.get("compare_heading", "五屏对照")),
        "{{COMPARE_SUB}}": inline(compare_sub),
        "{{SECTIONS}}": render_sections(page, languages, screens, by_key),
        "{{NOTES}}": render_notes(notes),
        "{{EXTRA_HEADING}}": inline(page.get("extra_heading", "补充屏")),
        "{{EXTRA_SUB}}": inline(page.get("extra_sub", "")),
        "{{EXTRA_GRID}}": render_extras(page, extras),
        "{{FOOTER}}": render_footer(page, languages, screens, extras, len(entries)),
    }

    result = template
    for marker, value in replacements.items():
        if marker not in result:
            raise ValueError(f"模板缺少占位符：{marker}")
        result = result.replace(marker, value)

    leftover = re.findall(r"\{\{[A-Z_]+\}\}", result)
    if leftover:
        raise ValueError("模板还有未替换占位符：" + ", ".join(sorted(set(leftover))))
    return result


def build(
    data_path: Path = DEFAULT_DATA,
    template_path: Path = DEFAULT_TEMPLATE,
) -> str:
    data = load_json(data_path)
    template = template_path.read_text(encoding="utf-8")
    return build_html(data, template, data_path.parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="只检查生成物是否最新")
    args = parser.parse_args(argv)

    generated = build(args.data, args.template)
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if generated != current:
            print(f"{args.output} 不是最新生成物；运行 python src/tools/docs/build_screenshots.py", file=sys.stderr)
            return 1
        print(f"{args.output} 已是最新生成物")
        return 0

    with args.output.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(generated)
    print(f"已生成 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
