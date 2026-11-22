# -*- coding: utf-8 -*-
"""release_manifest.py —— 生成并校验发行包根目录的 manifest.json。

清单只用于审计和 CI，不参与运行时解析：

- 目标游戏版本和 PR2.exe SHA-256；
- 参考原文文件及其 SHA-256；
- 语言来源 / 是否 AI 辅助 / 审阅状态；
- 包内每个文件的大小和 SHA-256。

运行时仍然从 `PR2Localization/packs/*.txt`、`locale.ini` 和
`font-map.default.ini` 读取，不依赖这份 JSON。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib

import build_time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)
INSTALL = os.path.join(TOOLS, "install")
if INSTALL not in sys.path:
    sys.path.insert(0, INSTALL)
from pr2ctl.base import KNOWN_BUILDS  # noqa: E402

MANIFEST_NAME = "manifest.json"
SCHEMA_VERSION = 2
#: 合并包同时面向两个版本，清单里把两个目标都列出来（schema 2 起是 targets 列表）。
TARGET_BUILDS = ("gog-en-1.1.2.3", "steam-en-1.1.2.3")
TARGET_EDITION = "universal"
DEFAULT_SOURCE_LANG = "en.gog_1.1.2.3"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _pack_doc(lang):
    path = os.path.join(SRC, "packs", lang + ".toml")
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _targets():
    """合并包要同时声明 GOG 与 Steam 两个已知构建。"""
    found = []
    for build_id in TARGET_BUILDS:
        for build in KNOWN_BUILDS:
            if build["id"] == build_id:
                found.append({
                    "build": build["id"],
                    "label": build["label"],
                    "edition": "gog" if build["id"].startswith("gog") else "steam",
                    "exe_sha256": build["sha256"].upper(),
                })
                break
        else:
            raise ValueError("KNOWN_BUILDS 里没有目标版本：%s" % build_id)
    return found


def _source(source_lang):
    rel = os.path.join("src", "orig", source_lang + ".toml")
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        raise FileNotFoundError("缺参考原文：%s" % rel)
    return {
        "reference": rel.replace(os.sep, "/"),
        "sha256": sha256_file(path),
    }


def _translation(lang):
    doc = _pack_doc(lang)
    import pack_tags
    tags = pack_tags.normalize_tags(doc.get("tags"))
    return {
        "tags": tags,
        "review_status": doc.get("review_status") or "unspecified",
        "source_lang": doc.get("source_lang") or DEFAULT_SOURCE_LANG,
    }


def kind_for(path):
    path = path.replace("\\", "/")
    if path == MANIFEST_NAME:
        return "manifest"
    if path == "RUNTIME-VERSION":
        return "runtime-version"
    if path in ("README.txt", "OFL.txt", "NOTO-SOURCES.txt"):
        return "doc"
    if path == "PR2HostMount.ps1":
        return "script"
    if path.startswith("PR2Localization/host/"):
        return "host-proxy"
    if path.startswith("PR2Localization/packs/"):
        if path.endswith(".txt"):
            return "pack"
        if path.endswith(".ini"):
            return "locale"
    if path.startswith("PR2Localization/fonts/"):
        if path.endswith(".ttf"):
            return "font"
        if path.endswith(".ini"):
            return "font-map"
    if path.startswith("PR2Localization/ui/"):
        return "ui"
    if path.endswith((".exe", ".dll")):
        return "runtime"
    return "data"


def iter_release_files(stage):
    stage = os.path.abspath(stage)
    for root, _dirs, files in os.walk(stage):
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, stage).replace(os.sep, "/")
            if rel == MANIFEST_NAME:
                continue
            yield rel, full


def _git(*args):
    """调用 git；找不到 git 时返回 None。"""
    exe = shutil.which("git")
    if not exe and os.path.isfile(r"C:\Program Files\Git\cmd\git.exe"):
        exe = r"C:\Program Files\Git\cmd\git.exe"
    if not exe:
        return None
    try:
        out = subprocess.run([exe] + list(args), cwd=ROOT, text=True,
                             encoding="utf-8", errors="replace",
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _build_info():
    """构建元信息：时间、源码提交、工作树是否有未提交改动。

    ``SOURCE_DATE_EPOCH`` 有值时 ``at`` 也取该时间，同一 commit 可复现出同一清单。
    """
    commit = _git("rev-parse", "--short=7", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=no")
    return {
        "at": build_time.utc_timestamp(),
        "commit": commit or None,
        "dirty": None if status is None else bool(status),
    }


def _as_langs(lang):
    """接受单个语言代码或语言列表；合包里是列表。"""
    return [lang] if isinstance(lang, str) else list(lang)


def build_manifest(stage, lang, version, font_mode, package_id=None):
    stage = os.path.abspath(stage)
    package_id = package_id or os.path.basename(os.path.normpath(stage))
    langs = _as_langs(lang)
    primary = langs[0]
    translation = _translation(primary)
    files = []
    for rel, full in iter_release_files(stage):
        files.append({
            "path": rel,
            "kind": kind_for(rel),
            "size": os.path.getsize(full),
            "sha256": sha256_file(full),
        })
    files.sort(key=lambda item: item["path"])
    return {
        "schema": SCHEMA_VERSION,
        "package_id": package_id,
        # lang 保留为默认语言（兼容旧读法）；合包里的全量在 langs / translations。
        "lang": primary,
        "langs": langs,
        "edition": TARGET_EDITION,
        "version": version,
        "runtime_version": _runtime_version(stage),
        "font_mode": font_mode,
        "build": _build_info(),
        "targets": _targets(),
        "translation": translation,
        "translations": [_translation(lang) for lang in langs],
        "source": _source(translation["source_lang"]),
        "counts": {
            "files": len(files),
            "bytes": sum(item["size"] for item in files),
        },
        "files": files,
    }


def _runtime_version(stage):
    path = os.path.join(stage, "RUNTIME-VERSION")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def write_release_manifest(stage, lang, version, font_mode, package_id=None):
    path = os.path.join(stage, MANIFEST_NAME)
    data = build_manifest(stage, lang, version, font_mode,
                          package_id=package_id)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return path


def _safe_path(stage, rel):
    if os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
        return None
    path = os.path.abspath(os.path.join(stage, *rel.replace("\\", "/").split("/")))
    try:
        if os.path.commonpath([stage, path]) != stage:
            return None
    except ValueError:
        return None
    return path


def verify_release_manifest(stage, manifest_path=None):
    """返回 (ok, errors)。校验清单内每个文件，也拦截清单外的多余文件。"""
    stage = os.path.abspath(stage)
    path = manifest_path or os.path.join(stage, MANIFEST_NAME)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        return False, ["读不到 %s：%s" % (MANIFEST_NAME, exc)]
    except json.JSONDecodeError as exc:
        return False, ["%s 不是合法 JSON：%s" % (MANIFEST_NAME, exc)]

    files = data.get("files")
    if not isinstance(files, list):
        return False, ["%s 缺少 files 列表" % MANIFEST_NAME]

    errors = []
    expected = set()
    for item in files:
        if not isinstance(item, dict):
            errors.append("%s 的 files 项不是对象" % MANIFEST_NAME)
            continue
        rel = item.get("path")
        if not isinstance(rel, str) or not rel:
            errors.append("%s 的 files 项缺少 path" % MANIFEST_NAME)
            continue
        rel = rel.replace("\\", "/")
        if rel in expected:
            errors.append("%s 重复登记：%s" % (MANIFEST_NAME, rel))
            continue
        expected.add(rel)
        full = _safe_path(stage, rel)
        if not full:
            errors.append("%s 路径越界：%s" % (MANIFEST_NAME, rel))
            continue
        if not os.path.isfile(full):
            errors.append("清单登记但文件不存在：%s" % rel)
            continue
        size = item.get("size")
        if not isinstance(size, int) or size < 0:
            errors.append("%s 的 size 不合法：%s" % (rel, size))
        elif os.path.getsize(full) != size:
            errors.append("大小不一致：%s" % rel)
        sha = item.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64:
            errors.append("%s 的 sha256 不合法" % rel)
        elif sha256_file(full) != sha.upper():
            errors.append("SHA-256 不一致：%s" % rel)

    actual = {rel for rel, _full in iter_release_files(stage)}
    for rel in sorted(actual - expected):
        errors.append("清单未登记的文件：%s" % rel)
    for rel in sorted(expected - actual):
        if not any(rel in e for e in errors):
            errors.append("清单登记但实际缺失：%s" % rel)
    return not errors, errors
