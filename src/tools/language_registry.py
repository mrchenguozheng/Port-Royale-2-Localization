#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语言注册表审计：把 release / preview / UI / pack / 译文 / 截图 / 字体 / bundle 对成一套账。

`src/release-languages.txt` 只负责“哪些语言进发行包”；`src/packs/`、
`src/injector-rs/ui/`、`src/translations/` 负责“能构建哪些语言”；
`docs/screenshots.json` 负责“哪些语言拍过实机图”。这些集合不必相等，
但差值必须有明确身份：发行、预览，还是只是截图缺口。

本模块只读仓库，不写文件；`docs/build_language_matrix.py` 用同一份审计
生成语言矩阵，`config_check.py` 把它作为配置闸门。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_DIR = os.path.join(HERE, "pack")
if PACK_DIR not in sys.path:
    sys.path.insert(0, PACK_DIR)
import release_version as RV  # noqa: E402

CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
PREVIEW_FILE = "preview-languages.txt"
FONT_LOGICAL = ("arial.ttf", "elgreco_.ttf", "tiepolo_black.ttf", "tiepolo_bold.ttf")


@dataclass
class LanguageRow:
    code: str
    name: str
    release: bool
    ui: bool
    pack: bool
    translation: bool
    screenshot: bool
    screenshot_source: str
    font_mode: str
    bundle: str
    review_status: str


def _read_raw_languages(path):
    if not os.path.isfile(path):
        return []
    tokens = []
    with open(path, encoding="utf-8-sig") as fh:
        for raw in fh.read().splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            for token in line.replace(",", " ").split():
                tokens.append(token)
    return tokens


def _read_packs(src):
    packs = {}
    pack_dir = os.path.join(src, "packs")
    if not os.path.isdir(pack_dir):
        return packs
    for name in sorted(os.listdir(pack_dir)):
        if not name.lower().endswith(".toml"):
            continue
        code = name[:-5]
        with open(os.path.join(pack_dir, name), "rb") as fh:
            packs[code] = tomllib.load(fh)
    return packs


def _read_bundles(src):
    path = os.path.join(src, "release-bundles.toml")
    if not os.path.isfile(path):
        return []
    with open(path, "rb") as fh:
        doc = tomllib.load(fh)
    return [dict(item) for item in doc.get("bundle", [])]


def _read_font_modes(src):
    path = os.path.join(src, "font-map.ini")
    modes = {}
    if not os.path.isfile(path):
        return modes
    section = None
    values = {}
    with open(path, encoding="utf-8-sig") as fh:
        for raw in fh.read().splitlines():
            line = raw.strip()
            if not line or line.startswith((";", "#")):
                continue
            if line.startswith("[") and line.endswith("]"):
                if section:
                    modes[section] = values
                section = line[1:-1].strip()
                values = {}
                continue
            if section is None or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip().lower()] = value.strip()
    if section:
        modes[section] = values
    for code, mapping in modes.items():
        if code.lower() == "fonts":
            continue
        entries = [mapping.get(name, "none").lower() for name in FONT_LOGICAL]
        modes[code] = "noto" if any(v not in ("none", "-") for v in entries) else "config"
    modes.pop("fonts", None)
    return modes


def _read_ui(src):
    ui_dir = os.path.join(src, "injector-rs", "ui")
    if not os.path.isdir(ui_dir):
        return set()
    return {
        name[3:-4]
        for name in os.listdir(ui_dir)
        if name.startswith("ui.") and name.endswith(".ini")
        and name not in ("ui.default.ini",)
    }


def _read_translations(src):
    trans_dir = os.path.join(src, "translations")
    if not os.path.isdir(trans_dir):
        return set()
    return {name[:-5] for name in os.listdir(trans_dir)
            if name.endswith(".toml") and not name.startswith("_")}


def _read_screenshots(root):
    """返回 (实拍语言集合, 沿用映射)。沿用只做视觉参考，不冒充独立实机验证。"""
    path = os.path.join(root, "docs", "screenshots.json")
    if not os.path.isfile(path):
        return set(), {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    shots = {item["code"] for item in data.get("languages", [])}
    derived = {}
    for item in data.get("derived_languages", []):
        code = item.get("code")
        source = item.get("from")
        if code and source:
            derived[code] = source
    return shots, derived


def audit(root):
    """返回 (errors, warnings, rows)。errors 会让 config_check 失败。"""
    src = os.path.join(root, "src")
    errors, warnings = [], []

    raw_path = os.path.join(src, RV.LANGUAGES_FILE)
    raw = _read_raw_languages(raw_path)
    bad_tokens = [t for t in raw if not CODE_RE.match(t)]
    if bad_tokens:
        errors.append("src/release-languages.txt：语言代码不合法：%s"
                      % "、".join(sorted(set(bad_tokens))))
    release = RV.read_languages(src)

    preview_path = os.path.join(src, PREVIEW_FILE)
    preview_raw = _read_raw_languages(preview_path)
    preview_bad = [t for t in preview_raw if not CODE_RE.match(t)]
    if preview_bad:
        errors.append("src/preview-languages.txt：语言代码不合法：%s"
                      % "、".join(sorted(set(preview_bad))))
    preview = set(preview_raw) - set(preview_bad)
    if set(release) & preview:
        errors.append("语言不能同时进 release 与 preview：%s"
                      % "、".join(sorted(set(release) & preview)))
    if set(release) != set(raw) - set(bad_tokens):
        skipped = sorted(set(raw) - set(bad_tokens) - set(release))
        if skipped:
            errors.append("src/release-languages.txt：解析时漏掉 %s"
                          % "、".join(skipped))

    packs = _read_packs(src)
    bundles = _read_bundles(src)
    fonts = _read_font_modes(src)
    ui = _read_ui(src)
    translations = _read_translations(src)
    screenshots, shot_derived = _read_screenshots(root)
    shot_coverage = set(screenshots) | set(shot_derived)

    bundle_by_lang = {}
    bundle_ids = set()
    bundled = []
    for bundle in bundles:
        bid = bundle.get("id", "")
        if not bid:
            errors.append("src/release-bundles.toml：分组缺 id")
            continue
        if bid in bundle_ids:
            errors.append("src/release-bundles.toml：分组 id 重复：%s" % bid)
        bundle_ids.add(bid)
        langs = list(bundle.get("langs", []))
        if not langs:
            errors.append("src/release-bundles.toml：分组 %s 的 langs 为空" % bid)
        if bundle.get("default") not in langs:
            errors.append("src/release-bundles.toml：分组 %s 的 default=%r 不在 langs 里"
                          % (bid, bundle.get("default")))
        for lang in langs:
            if lang in bundle_by_lang:
                errors.append("src/release-bundles.toml：%s 同时出现在 %s 与 %s"
                              % (lang, bundle_by_lang[lang], bid))
            bundle_by_lang[lang] = bid
            bundled.append(lang)

    if set(bundled) != set(release):
        missing = sorted(set(release) - set(bundled))
        extra = sorted(set(bundled) - set(release))
        if missing:
            errors.append("发行分组缺语言：%s（在 release-languages.txt 里但不在任何 bundle）"
                          % "、".join(missing))
        if extra:
            errors.append("发行分组多语言：%s（在 bundle 里但不在 release-languages.txt）"
                          % "、".join(extra))

    for code in sorted(set(release) | set(packs)):
        if code not in packs:
            errors.append("src/packs/%s.toml：发行语言缺少语言包配置" % code)
        if code not in translations:
            errors.append("src/translations/%s.toml：缺少译文底稿" % code)
        if code not in ui:
            errors.append("src/injector-rs/ui/ui.%s.ini：缺少界面文案" % code)
        if code not in fonts:
            errors.append("src/font-map.ini：[%s] 缺少字体映射" % code)

    for code in sorted(set(ui) - set(packs)):
        errors.append("src/injector-rs/ui/ui.%s.ini：没有对应 src/packs/%s.toml" % (code, code))

    for code in sorted(preview):
        if code not in packs:
            errors.append("src/preview-languages.txt：%s 没有 src/packs/%s.toml"
                          % (code, code))

    for code in sorted(set(packs) - set(release) - preview):
        errors.append("src/packs/%s.toml：既不在 release-languages.txt，也不在 "
                      "preview-languages.txt（先决定身份，不要留在灰色地带）" % code)

    for code in sorted(set(screenshots) - set(packs)):
        errors.append("docs/screenshots.json：截图语言 %s 没有语言包配置" % code)
    for code, source in sorted(shot_derived.items()):
        if code in screenshots:
            errors.append("docs/screenshots.json：%s 既有实拍又有沿用，删掉一边" % code)
        if code not in packs:
            errors.append("docs/screenshots.json：沿用语言 %s 没有语言包配置" % code)
        if source not in screenshots:
            errors.append("docs/screenshots.json：%s 沿用 %s，但后者没有实拍截图"
                          % (code, source))
        if source == code:
            errors.append("docs/screenshots.json：%s 不能沿用自己" % code)
    for code in sorted(set(release) - shot_coverage):
        warnings.append("docs/screenshots.json：发行语言 %s 还没有实机截图" % code)
    for code in sorted(set(ui) - shot_coverage):
        if code in release:
            continue
        warnings.append("docs/screenshots.json：UI 语言 %s 还没有实机截图" % code)

    ordered = sorted(set(release) | set(packs) | ui | screenshots,
                     key=lambda c: (c not in release, c.lower()))
    rows = []
    for code in ordered:
        pack = packs.get(code, {})
        if code in release:
            review = "release"
        elif code in preview:
            review = "preview"
        else:
            review = str(pack.get("review_status") or "pack")
        rows.append(LanguageRow(
            code=code,
            name=str(pack.get("alias") or code),
            release=code in release,
            ui=code in ui,
            pack=code in packs,
            translation=code in translations,
            screenshot=code in shot_coverage,
            screenshot_source=shot_derived.get(code, ""),
            font_mode=fonts.get(code, "—"),
            bundle=bundle_by_lang.get(code, "—"),
            review_status=review,
        ))
    return errors, warnings, rows


def summary(rows):
    release = sum(1 for row in rows if row.release)
    preview = sum(1 for row in rows if row.review_status == "preview")
    shots = sum(1 for row in rows if row.screenshot)
    return release, preview, shots
