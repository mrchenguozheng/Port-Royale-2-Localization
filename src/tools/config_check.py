#!/usr/bin/env python3
# coding: utf-8
"""config_check.py —— 语言相关配置的只读校验。

检查仓库里的配置源，不检查运行中的游戏目录：

- `src/locale.ini` 的语言代码与语法；
- `src/packs/*.toml` 的 alias/gui/min_runtime；
- `src/translations/<code>.toml` 是否存在；
- `src/injector-rs/ui/<gui>.ini` 是否存在、是否有重复键；
- `src/font-map.ini` / `src/font-map-stitch.ini` 的逻辑名、坏行和禁用字体；
- `src/data/placeholder_roles/<code>.toml` 是否存在且可解析。

这些检查只保证配置之间对得上；字体文件是否真的存在由 release/build 阶段
再按实际产物检查。
"""

import os
import re
import sys
import tomllib

from paths import ROOT, SRC

INSTALL = os.path.join(SRC, "tools", "install")
if INSTALL not in sys.path:
    sys.path.insert(0, INSTALL)
from pr2ctl.detect import read_ini_language  # noqa: E402

FONT_NAMES = (
    "ARIAL.TTF",
    "ELGRECO_.TTF",
    "Tiepolo_black.ttf",
    "Tiepolo_bold.ttf",
)
PACK_KEYS = ("alias", "gui", "min_runtime")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,63}$")


def _rel(path, root):
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def _load_toml(path, root, errors):
    try:
        with open(path, "rb") as fh:
            doc = tomllib.load(fh)
    except OSError as exc:
        errors.append("%s：读不到（%s）" % (_rel(path, root), exc))
        return None
    except tomllib.TOMLDecodeError as exc:
        errors.append("%s：TOML 解析失败（%s）" % (_rel(path, root), exc))
        return None
    if not isinstance(doc, dict):
        errors.append("%s：根节点不是表" % _rel(path, root))
        return None
    return doc


def _check_packs(src, errors, warnings):
    packs = {}
    pack_dir = os.path.join(src, "packs")
    if not os.path.isdir(pack_dir):
        errors.append("src/packs：目录不存在")
        return packs

    for name in sorted(os.listdir(pack_dir)):
        if not name.lower().endswith(".toml"):
            continue
        code = name[:-5]
        if not CODE_RE.match(code):
            errors.append("src/packs/%s：语言代码不合法" % name)
            continue
        doc = _load_toml(os.path.join(pack_dir, name), ROOT, errors)
        if doc is None:
            continue
        packs[code] = doc

        alias = doc.get("alias")
        if not isinstance(alias, str) or not alias.strip():
            errors.append("src/packs/%s：alias 必须是非空字符串" % name)
        gui = doc.get("gui")
        if not isinstance(gui, str) or not gui.strip():
            errors.append("src/packs/%s：gui 必须是非空字符串" % name)
        else:
            if not CODE_RE.match(gui):
                errors.append("src/packs/%s：gui=%r 不是合法语言代码"
                              % (name, gui))
            if not os.path.isfile(os.path.join(
                    src, "injector-rs", "ui", gui + ".ini")):
                errors.append("src/packs/%s：缺少 src/injector-rs/ui/%s.ini"
                              % (name, gui))
        runtime = doc.get("min_runtime")
        if runtime is not None:
            if isinstance(runtime, bool) or not isinstance(runtime, int) or runtime < 1:
                errors.append("src/packs/%s：min_runtime 必须是 >=1 的整数"
                              % name)
        unknown = sorted(set(doc) - set(PACK_KEYS))
        if unknown:
            warnings.append("src/packs/%s：未识别字段 %s"
                            % (name, ", ".join(unknown)))
    return packs


def _parse_font_map(path, root, errors):
    """返回 {section: {logical: value}}；坏行和重复键直接报错。"""
    sections = {}
    section = "fonts"
    sections["fonts"] = {}
    if not os.path.isfile(path):
        errors.append("%s：文件不存在" % _rel(path, root))
        return sections

    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        errors.append("%s：读不到（%s）" % (_rel(path, root), exc))
        return sections

    for no, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip().lower()
            if not name:
                errors.append("%s:%d：节名为空" % (_rel(path, root), no))
                continue
            section = name
            sections.setdefault(section, {})
            continue
        if "=" not in line:
            errors.append("%s:%d：无法解析（%s）" % (_rel(path, root), no, line))
            continue
        key, value = line.split("=", 1)
        key = key.strip().strip("\"'").lower()
        if not key:
            errors.append("%s:%d：逻辑名为空" % (_rel(path, root), no))
            continue
        if key not in {n.lower() for n in FONT_NAMES}:
            errors.append("%s:%d：未知逻辑名 %s（只允许 %s）"
                          % (_rel(path, root), no, key, ", ".join(FONT_NAMES)))
            continue
        if key in sections[section]:
            errors.append("%s:%d：重复逻辑名 %s" % (_rel(path, root), no, key))
            continue
        values = [v.strip().strip("\"'") for v in value.split("|")]
        if not values or any(not v for v in values):
            errors.append("%s:%d：%s 的值为空" % (_rel(path, root), no, key))
            continue
        for value in values:
            low = value.lower()
            if low in ("none", "-"):
                continue
            if low.endswith(".ttc") or "-vf.ttf" in low:
                errors.append("%s:%d：%s 使用了不接受的字体（%s）"
                              % (_rel(path, root), no, key, value))
            if os.path.isabs(value) or "\\" in value or "/" in value:
                errors.append("%s:%d：%s 只能写文件名，不能带路径（%s）"
                              % (_rel(path, root), no, key, value))
        sections[section][key] = value
    return sections


def _check_font_maps(src, packs, errors, warnings):
    required = _parse_font_map(os.path.join(src, "font-map.ini"), ROOT, errors)
    for code, _doc in packs.items():
        section = required.get(code.lower())
        if not section:
            errors.append("src/font-map.ini：缺少 [%s] 字体映射" % code)
            continue
        missing = [n for n in FONT_NAMES if n.lower() not in section]
        if missing:
            errors.append("src/font-map.ini：[%s] 缺少 %s"
                          % (code, ", ".join(missing)))

    stitch_path = os.path.join(src, "font-map-stitch.ini")
    if os.path.isfile(stitch_path):
        stitch = _parse_font_map(stitch_path, ROOT, errors)
        for code, _doc in packs.items():
            if code.lower() not in stitch:
                warnings.append("src/font-map-stitch.ini：缺少 [%s]"
                                % code)


def _check_translations(src, packs, errors):
    trans_dir = os.path.join(src, "translations")
    if not os.path.isdir(trans_dir):
        errors.append("src/translations：目录不存在")
        return
    for code in packs:
        path = os.path.join(trans_dir, code + ".toml")
        if not os.path.isfile(path):
            errors.append("src/translations/%s.toml：文件不存在" % code)
            continue
        if _load_toml(path, ROOT, errors) is None:
            continue


def _parse_ui(path, root, errors):
    keys = set()
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        errors.append("%s：读不到（%s）" % (_rel(path, root), exc))
        return
    for no, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";") \
                or line.startswith("["):
            continue
        if "=" not in line:
            errors.append("%s:%d：无法解析（%s）" % (_rel(path, root), no, line))
            continue
        key = line.split("=", 1)[0].strip()
        if not key:
            errors.append("%s:%d：key 为空" % (_rel(path, root), no))
            continue
        if key in keys:
            errors.append("%s:%d：重复 key %s" % (_rel(path, root), no, key))
        keys.add(key)


def _check_ui(src, packs, errors):
    ui_dir = os.path.join(src, "injector-rs", "ui")
    if not os.path.isfile(os.path.join(ui_dir, "en.ini")):
        errors.append("src/injector-rs/ui/en.ini：基础英文文件不存在")
    if os.path.isdir(ui_dir):
        for name in sorted(os.listdir(ui_dir)):
            if name.lower().endswith(".ini"):
                _parse_ui(os.path.join(ui_dir, name), ROOT, errors)


def _check_placeholder_roles(src, packs, errors, warnings):
    roles_dir = os.path.join(src, "data", "placeholder_roles")
    for code in packs:
        path = os.path.join(roles_dir, code + ".toml")
        if not os.path.isfile(path):
            warnings.append("src/data/placeholder_roles/%s.toml：不存在"
                            % code)
            continue
        _load_toml(path, ROOT, errors)


def check_repository(root=ROOT):
    """返回 (errors, warnings)；不抛异常，不写文件。"""
    errors, warnings = [], []
    src = os.path.join(root, "src")

    locale = os.path.join(src, "locale.ini")
    code = read_ini_language(locale)
    if not code:
        errors.append("src/locale.ini：没有有效的 language= 值")
    elif not CODE_RE.match(code):
        errors.append("src/locale.ini：language=%r 不是合法语言代码" % code)

    packs = _check_packs(src, errors, warnings)
    _check_font_maps(src, packs, errors, warnings)
    _check_translations(src, packs, errors)
    _check_ui(src, packs, errors)
    _check_placeholder_roles(src, packs, errors, warnings)

    if code and code not in packs:
        errors.append("src/locale.ini：language=%s 没有 src/packs/%s.toml"
                      % (code, code))
    return errors, warnings


def main():
    errors, warnings = check_repository()
    for warning in warnings:
        print("警告：%s" % warning)
    for error in errors:
        print("错误：%s" % error)
    if errors:
        print("\n配置检查失败：%d 项错误。" % len(errors))
        return 1
    print("配置检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
