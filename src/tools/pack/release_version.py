# -*- coding: utf-8 -*-
"""release_version.py —— 发行版本号与发行语言集的唯一口径。

两件事都只在这里定义，其它脚本调用它，避免本地 release.ps1 和 CI 各写一套：

1. 版本号：``vMAJOR.MINOR.PATCH`` 或 ``vMAJOR.MINOR.PATCH-prerelease``。
   用户输入可以不带 ``v``；归一化后一律带 ``v``，文件名、manifest、
   README、tag 全用归一化结果。
2. 发行语言集：``src/release-languages.txt`` 每行一个语言代码，``#`` 起注释。
   有 pack 和译文、但没列进清单的语言不进发行包（比如试点中的 de/es/fr）。
"""

import os
import re

VERSION_RE = re.compile(
    r"^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z][0-9A-Za-z.-]*))?$")
LANG_RE = re.compile(r"^[a-z]{2,3}$")
LANGUAGES_FILE = "release-languages.txt"


def normalize(version):
    """把输入归一化成 ``v…``；不合法时抛 ValueError。

    ``1.0.0`` → ``v1.0.0``；``v1.0.0-rc.1`` 原样返回。
    """
    if not isinstance(version, str) or not version.strip():
        raise ValueError("版本号为空，应为 v1.0.0 这类形式")
    text = version.strip()
    if not text.startswith("v"):
        text = "v" + text
    if not VERSION_RE.match(text):
        raise ValueError(
            "版本号不合法：%r；只接受 vMAJOR.MINOR.PATCH[-prerelease]，"
            "例如 v1.0.0、v1.2.3-rc.1" % version)
    return text


def is_prerelease(version):
    return "-" in normalize(version)


def version_number(version):
    """返回 ``(major, minor, patch)``。"""
    match = VERSION_RE.match(normalize(version))
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def languages_path(src):
    return os.path.join(src, LANGUAGES_FILE)


def read_languages(src):
    """读发行语言清单；文件缺失或为空时返回空列表。"""
    path = languages_path(src)
    if not os.path.isfile(path):
        return []
    names = []
    with open(path, "r", encoding="utf-8-sig") as fh:
        for raw in fh.read().splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            for item in line.replace(",", " ").split():
                if LANG_RE.match(item):
                    names.append(item)
    return sorted(set(names))


def check_language(src, lang):
    """返回该语言作为发行语言的缺件清单（空列表表示齐全）。"""
    problems = []
    if not os.path.isfile(os.path.join(src, "packs", lang + ".toml")):
        problems.append("缺 src/packs/%s.toml" % lang)
    if not os.path.isfile(os.path.join(src, "translations", lang + ".toml")):
        problems.append("缺 src/translations/%s.toml" % lang)
    font_map = os.path.join(src, "font-map.ini")
    if os.path.isfile(font_map):
        has_section = False
        with open(font_map, "r", encoding="utf-8-sig") as fh:
            for raw in fh.read().splitlines():
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    if line[1:-1].strip().lower() == lang:
                        has_section = True
                        break
        if not has_section:
            problems.append("缺 src/font-map.ini [%s] 节" % lang)
    return problems
