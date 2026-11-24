#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从结构化数据生成实机截图画廊（HTML 与 Markdown 同一份源）。

页面结构与 CSS/灯箱在 ``screenshots_template.html`` 里；图注、说明、覆盖点
和补充屏在 ``docs/screenshots.json`` 里；图片是否存在、尺寸、字节数与
SHA-256 以 ``docs/assets/screenshots/manifest.json`` 为准。两个生成物
``docs/screenshots.html`` 与 ``docs/实机截图.md`` 都是生成物，不要手改。

缩略图放在 ``docs/assets/screenshots/thumbs/``，由 ``--thumbs`` 生成；
HTML 只引用 800×600 的缩略图，灯箱打开原图。Markdown 直接引用原图。

用法::

    python src/tools/docs/build_screenshots.py --thumbs
    python src/tools/docs/build_screenshots.py --check

``--check`` 比较 HTML/Markdown 是否为最新，并检查缩略图是否存在。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA = ROOT / "docs" / "screenshots.json"
DEFAULT_TEMPLATE = Path(__file__).with_name("screenshots_template.html")
DEFAULT_OUTPUT = ROOT / "docs" / "screenshots.html"
DEFAULT_MARKDOWN = ROOT / "docs" / "实机截图.md"
SCHEMA_VERSION = 1


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def thumb_rel(page: dict, entry: dict) -> str:
    return f"{page.get('thumb_root', 'assets/screenshots/thumbs')}/{entry['file']}"


def full_rel(page: dict, entry: dict) -> str:
    return f"{page.get('image_root', 'assets/screenshots')}/{entry['file']}"


def collect_manifest(data: dict, docs_root: Path) -> list[dict]:
    """校验清单、图片实际尺寸/字节数/SHA-256 与数据引用，返回整份清单。"""
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"screenshots.json.schema_version={data.get('schema_version')!r}，"
            f"期望 {SCHEMA_VERSION}"
        )
    page = data["page"]
    languages = data["languages"]
    screens = data["screens"]
    extras = data.get("extras", [])
    if not languages or not screens:
        raise ValueError("screenshots.json 里 languages/screens 不能为空")
    thumb_width = int(page.get("thumb_width", 800))
    thumb_height = int(page.get("thumb_height", 600))
    if thumb_width <= 0 or thumb_height <= 0:
        raise ValueError("page.thumb_width/thumb_height 必须是正数")

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
        if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
            raise ValueError(f"manifest.json 缺少合法 sha256：{entry['file']}")
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
            if sha256_file(image_path) != entry["sha256"]:
                raise ValueError(f"{entry['file']} 的 SHA-256 与清单不一致")
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
        if entry.get("width") != expected_width or entry.get("height") != expected_height:
            raise ValueError(
                f"{filename} 尺寸 {entry.get('width')}×{entry.get('height')}，"
                f"期望 {expected_width}×{expected_height}"
            )
        if image_path.stat().st_size != entry["bytes"]:
            raise ValueError(
                f"{filename} 实际 {image_path.stat().st_size} B，清单写 {entry['bytes']} B"
            )
        if sha256_file(image_path) != entry["sha256"]:
            raise ValueError(f"{filename} 的 SHA-256 与清单不一致")
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
        (page.get("version", ""), ""),
        (page.get("package", ""), ""),
        (" / ".join(lang["native"] for lang in languages), " chip-langs"),
        (page.get("date", ""), ""),
        (page.get("image_note", ""), ""),
        (f"{total} 张", ""),
    ]
    return "\n".join(
        f'      <span class="chip{suffix}">{inline(chip)}</span>'
        for chip, suffix in chips if chip
    )


def render_toc(page: dict) -> str:
    links = [
        f'      <a href="{html.escape(item["href"], quote=True)}">{inline(item["label"])}</a>'
        for item in page.get("toc", [])
    ]
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


def render_figure(
    page: dict, entry: dict, alt: str, native: str, caption: str,
    indent: str = "      ",
) -> str:
    thumb = thumb_rel(page, entry)
    full = full_rel(page, entry)
    width = int(page.get("thumb_width", 800))
    height = int(page.get("thumb_height", 600))
    return (
        f"{indent}<figure>\n"
        f'{indent}  <img src="{html.escape(thumb)}" data-full="{html.escape(full)}" '
        f'alt="{inline(alt)}" width="{width}" height="{height}" '
        f'loading="lazy" decoding="async">\n'
        f'{indent}  <figcaption><span class="lang">{inline(native)}</span> {inline(caption)}</figcaption>\n'
        f"{indent}</figure>"
    )


def render_player(page: dict, by_file: dict) -> str:
    """玩家入口：先给效果图与安装步骤，再进入完整对照。"""
    player = page.get("player")
    if not player:
        return ""

    facts = "\n".join(
        f"        <li>{inline(item)}</li>" for item in player.get("facts", [])
    )
    samples = []
    for sample in player.get("samples", []):
        entry = by_file.get(sample["file"])
        if entry is None:
            raise ValueError(f"玩家入口引用了不存在的截图：{sample['file']}")
        samples.append(
            render_figure(
                page,
                entry,
                sample.get("alt", ""),
                sample.get("lang", ""),
                sample.get("caption", ""),
                indent="        ",
            )
        )
    steps = "\n".join(
        f'        <li><span class="step-num">{index:02d}</span>'
        f"<h3>{inline(step['title'])}</h3><p>{inline(step['body'])}</p></li>"
        for index, step in enumerate(player.get("steps", []), 1)
    )
    download = html.escape(player.get("download_url", "#"), quote=True)
    secondary = html.escape(player.get("secondary_href", "#compare"), quote=True)

    return (
        '  <section class="player" id="effect">\n'
        '    <div class="player-copy">\n'
        f'      <div class="eyebrow">{inline(player.get("kicker", ""))}</div>\n'
        f'      <h2>{inline(player.get("heading", ""))}</h2>\n'
        f'      <p class="player-body">{inline(player.get("body", ""))}</p>\n'
        '      <ul class="facts">\n'
        f'{facts}\n'
        "      </ul>\n"
        '      <div class="actions">\n'
        f'        <a class="btn primary" href="{download}">{inline(player.get("download_label", "下载"))}</a>\n'
        f'        <a class="btn" href="{secondary}">{inline(player.get("secondary_label", "看全部"))}</a>\n'
        "      </div>\n"
        "    </div>\n"
        '    <div class="preview-grid">\n'
        + "\n".join(samples)
        + "\n    </div>\n"
        "  </section>\n\n"
        '  <section class="how" id="how">\n'
        '    <div class="section-head">\n'
        f'      <h2>{inline(player.get("how_heading", "怎么用"))}</h2>\n'
        f'      <span class="sub">{inline(player.get("how_lead", ""))}</span>\n'
        "    </div>\n"
        '    <ol class="how-steps">\n'
        + steps
        + "\n    </ol>\n"
        f'    <p class="caveat">{inline(player.get("caveat", ""))}</p>\n'
        "  </section>"
    )


def render_sections(
    page: dict, languages: list[dict], screens: list[dict], by_key: dict
) -> str:
    blocks = []
    for screen in screens:
        figures = []
        for lang in languages:
            entry = by_key[(lang["code"], screen["slug"])]
            figures.append(
                render_figure(
                    page,
                    entry,
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


def render_extras(page: dict, extras: list[dict], by_file: dict) -> str:
    blocks = []
    for extra in extras:
        entry = by_file[extra["file"]]
        blocks.append(
            render_figure(
                page,
                entry,
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
    thumb_root = page.get("thumb_root", "assets/screenshots/thumbs")
    repo_url = page.get("repo_url", "#").rstrip("/")
    compare_count = len(screens) * len(languages)
    extra_count = len(extras)
    return (
        f"缩略图：<code>docs/{thumb_root}/</code> · 原图：<code>docs/{image_root}/</code> · "
        f"{cn_number(len(screens))}屏对照{cn_number(len(languages))}语共 {compare_count} 张，"
        f"加{inline(page.get('extra_label', '补充'))} {extra_count} 张，共 {total} 张 · "
        "机器可读清单：<code>manifest.json</code> · 截图口径与覆盖表见 "
        f'<a href="{html.escape(repo_url, quote=True)}/blob/main/docs/实机截图.md">实机截图.md</a>'
    )


def build_html(data: dict, template: str, docs_root: Path) -> str:
    page = data["page"]
    languages = data["languages"]
    screens = data["screens"]
    extras = data.get("extras", [])
    notes = data.get("notes", [])

    entries = collect_manifest(data, docs_root)
    by_key = {(entry["language"], entry["slug"]): entry for entry in entries}
    by_file = {entry["file"]: entry for entry in entries}
    columns = int(page.get("columns", 4))
    groups = groups_of(languages, columns)

    h1 = page.get("h1") or (
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
    lede = page.get("lede") or (
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
        "{{PLAYER}}": render_player(page, by_file),
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
        "{{EXTRA_GRID}}": render_extras(page, extras, by_file),
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


def md_cell(value: str) -> str:
    """表格单元：竖线转义，换行压成空格。"""
    return re.sub(r"\s+", " ", str(value)).replace("|", "\\|").strip()


def md_path(path: str) -> str:
    return quote(path, safe="/-._~")


def render_markdown_coverage(
    page: dict, languages: list[dict], screens: list[dict], by_key: dict
) -> list[str]:
    head = "| # | 屏 | 验证点 | " + " | ".join(
        md_cell(lang["native"]) for lang in languages
    ) + " |"
    sep = "|" + "---|" * (3 + len(languages))
    lines = [head, sep]
    for screen in screens:
        cells = [md_cell(screen["num"]), md_cell(screen["title"]), md_cell(screen["verify"])]
        for lang in languages:
            entry = by_key.get((lang["code"], screen["slug"]))
            if entry is None:
                cells.append("—")
            else:
                cells.append(f"[{lang['code']}]({md_path(full_rel(page, entry))})")
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_markdown_sections(
    page: dict, languages: list[dict], screens: list[dict], by_key: dict
) -> list[str]:
    lines = []
    for screen in screens:
        lines.extend([
            f"### {screen['num']}. {screen['title']}",
            "",
            screen["desc"],
            "",
            "| " + " | ".join(md_cell(lang["native"]) for lang in languages) + " |",
            "|---|" + "---|" * (len(languages) - 1),
        ])
        cells = []
        for lang in languages:
            entry = by_key[(lang["code"], screen["slug"])]
            alt = f"{lang['code']} {screen['title']}"
            cells.append(f"![{md_cell(alt)}]({md_path(full_rel(page, entry))})")
        lines.extend(["| " + " | ".join(cells) + " |", ""])
    return lines


def render_markdown_extras(page: dict, extras: list[dict], by_file: dict) -> list[str]:
    lines = []
    for start in range(0, len(extras), 2):
        group = extras[start:start + 2]
        labels = [
            md_cell(extra["caption"].split("：", 1)[0] or extra["alt"])
            for extra in group
        ]
        lines.append("| " + " | ".join(labels) + " |")
        lines.append("|" + "---|" * len(group))
        cells = []
        for extra in group:
            entry = by_file[extra["file"]]
            cells.append(
                f"![{md_cell(extra['alt'])}]({md_path(full_rel(page, entry))})"
            )
        lines.extend(["| " + " | ".join(cells) + " |", ""])
    return lines


def build_markdown(data: dict, docs_root: Path) -> str:
    page = data["page"]
    languages = data["languages"]
    screens = data["screens"]
    extras = data.get("extras", [])
    markup = page.get("markdown", {})
    entries = collect_manifest(data, docs_root)
    by_key = {(entry["language"], entry["slug"]): entry for entry in entries}
    by_file = {entry["file"]: entry for entry in entries}

    title = markup.get("title", "实机截图")
    bullets = markup.get("bullets", [])
    notes_heading = markup.get("notes_heading", "语言注记")
    notes = markup.get("notes", [])
    extra_intro = markup.get("extra_intro", "")

    lines = [
        f"# {title}",
        "",
        "> 本文件与 `screenshots.html` 均由 `docs/screenshots.json` 经",
        "> `src/tools/docs/build_screenshots.py` 生成，不要手改。",
        "",
        f"在线画廊：[GitHub Pages]({page.get('site_url', 'screenshots.html')})。",
        "",
        "## 口径",
        "",
    ]
    lines.extend(f"- {item}" for item in bullets)
    lines.extend([
        "",
        f"## {cn_number(len(languages))}语{cn_number(len(screens))}屏覆盖",
        "",
        "✓ 表示该语言在该屏有归档实机图；点击语言代码打开原图。",
        "",
    ])
    lines.extend(render_markdown_coverage(page, languages, screens, by_key))
    lines.extend([
        "",
        "## 对照",
        "",
    ])
    lines.extend(render_markdown_sections(page, languages, screens, by_key))
    lines.extend([
        f"## {notes_heading}",
        "",
    ])
    lines.extend(f"- {note}" for note in notes)
    lines.extend([
        "",
        f"## {page.get('extra_heading', '补充屏')}",
        "",
        extra_intro,
        "",
    ])
    lines.extend(render_markdown_extras(page, extras, by_file))
    return "\n".join(lines).rstrip() + "\n"


def check_thumbnails(data: dict, docs_root: Path) -> None:
    page = data["page"]
    thumb_root = docs_root / page.get("thumb_root", "assets/screenshots/thumbs")
    for entry in collect_manifest(data, docs_root):
        path = thumb_root / entry["file"]
        if not path.is_file():
            raise ValueError(f"缩略图不存在：{path}；运行 --thumbs")


def generate_thumbnails(data: dict, docs_root: Path) -> int:
    """把归档原图缩到 thumb_width/height；需要 Pillow。"""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - 只在缺依赖时触发
        raise SystemExit("需要 Pillow：python -m pip install Pillow") from exc

    page = data["page"]
    image_root = docs_root / page.get("image_root", "assets/screenshots")
    thumb_root = docs_root / page.get("thumb_root", "assets/screenshots/thumbs")
    width = int(page.get("thumb_width", 800))
    height = int(page.get("thumb_height", 600))
    entries = collect_manifest(data, docs_root)
    for entry in entries:
        source = image_root / entry["file"]
        target = thumb_root / entry["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS).save(
                target, "JPEG", quality=82, optimize=True, progressive=True
            )
    return len(entries)


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
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--thumbs", action="store_true", help="生成/刷新 800×600 缩略图")
    parser.add_argument("--check", action="store_true", help="只检查生成物是否最新")
    args = parser.parse_args(argv)

    data = load_json(args.data)
    template = args.template.read_text(encoding="utf-8")
    generated = build_html(data, template, args.data.parent)
    generated_md = build_markdown(data, args.data.parent)
    docs_root = args.data.parent

    if args.thumbs:
        count = generate_thumbnails(data, docs_root)
        print(f"已生成 {count} 张缩略图")

    if args.check:
        errors = []
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if generated != current:
            errors.append(f"{args.output} 不是最新生成物")
        current_md = args.markdown.read_text(encoding="utf-8") if args.markdown.exists() else ""
        if generated_md != current_md:
            errors.append(f"{args.markdown} 不是最新生成物")
        try:
            check_thumbnails(data, docs_root)
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            for item in errors:
                print(item, file=sys.stderr)
            print("运行 python src/tools/docs/build_screenshots.py --thumbs", file=sys.stderr)
            return 1
        print("screenshots.html / 实机截图.md / 缩略图 都已是最新生成物")
        return 0

    with args.output.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(generated)
    with args.markdown.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(generated_md)
    print(f"已生成 {args.output}")
    print(f"已生成 {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
