#!/usr/bin/env python3
# coding: utf-8
"""把第三方零售语言包里的 strings.jsonl 抽成 src/orig 参考原文。

只做参考/QA，不生成译文、不改语言包。零售包没有 license 字段，输出文件
头会写明许可未确认，不能直接当作我们的发布译文。

用法：
    python src/tools/extract_retail_reference.py --zip \
        C:\\Downloads\\ru-retail-1.0.0.pr2loc.zip --lang ru

默认输出 src/orig/<lang>.retail-<version>.toml；已存在时拒绝覆盖。
"""

import argparse
import hashlib
import json
import os
import sys
import tomllib
import zipfile

from paths import ROOT, SRC

GOG_EN_1123 = "394CE2A48BC6B21708B81A232C7C88459BE7F3C8082CC593AD83B0B8E4C168EC"
KNOWN_TARGETS = {
    GOG_EN_1123: "GOG 英文版 1.1.2.3",
}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def toml_string(value):
    """TOML 基本字符串；控制字符转义，Unicode 原样保留。"""
    out = ['"']
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append("\\u%04X" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def load_retail(zip_path, lang):
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        for need in ("manifest.json", "strings.jsonl"):
            if need not in names:
                raise SystemExit("零售包缺少 %s：%s" % (need, zip_path))
        manifest = json.loads(zf.read("manifest.json"))
        strings_raw = zf.read("strings.jsonl")

    if str(manifest.get("language", "")).lower() != lang.lower():
        raise SystemExit(
            "语言不匹配：manifest.language=%r，--lang=%r"
            % (manifest.get("language"), lang))
    target = manifest.get("target") or {}
    exe_sha = str(target.get("exe_sha256", "")).upper()
    if exe_sha not in KNOWN_TARGETS:
        raise SystemExit(
            "未知目标 exe 哈希：%s（只接受已核对的英文 GOG 1.1.2.3）" % exe_sha)

    rows = []
    for no, raw in enumerate(strings_raw.decode("utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit("strings.jsonl 第 %d 行不是合法 JSON：%s"
                             % (no, exc))
        h = str(row.get("hash", "")).lower()
        if not h.startswith("0x") or len(h) < 3:
            raise SystemExit("strings.jsonl 第 %d 行 hash 非法：%r" % (no, h))
        if h in {r["hash"] for r in rows}:
            raise SystemExit("strings.jsonl 第 %d 行 hash 重复：%s" % (no, h))
        rows.append({
            "hash": h,
            "source": str(row.get("source", "")),
            "text": str(row.get("text", "")),
            "status": str(row.get("status", "")),
        })

    review = manifest.get("review") or {}
    if review.get("count") != len(rows):
        raise SystemExit(
            "行数不一致：manifest.review.count=%r，实际=%d"
            % (review.get("count"), len(rows)))
    if review.get("sha256") != sha256_bytes(strings_raw):
        raise SystemExit("strings.jsonl 的 SHA-256 与 manifest 不一致")

    return manifest, rows, strings_raw


def render(manifest, rows, zip_path, strings_raw):
    lang = str(manifest["language"]).lower()
    version = str(manifest.get("version", "1.0.0"))
    out_name = "%s.retail-%s.toml" % (lang, version)
    source = manifest.get("source") or {}
    target = manifest.get("target") or {}
    lines = [
        "# 参考原文：%s" % out_name,
        "# 来源：%s（第三方 pr2loc 零售包，仅供翻译参考/QA）"
        % (manifest.get("display_name") or manifest.get("package_id") or lang),
        "# 来源压缩包：%s" % os.path.basename(zip_path),
        "# 来源压缩包 SHA-256：%s" % sha256_file(zip_path),
        "# 原始档案：%s" % (source.get("archive_name") or "（未记录）"),
        "# 原始档案 SHA-256：%s" % (source.get("archive_sha256") or "（未记录）"),
        "# strings.jsonl SHA-256：%s" % sha256_bytes(strings_raw),
        "# 目标 exe：%s（%s）" % (
            str(target.get("exe_sha256", "")).upper(),
            KNOWN_TARGETS[str(target.get("exe_sha256", "")).upper()]),
        "# 许可状态：零售包未提供 license，不能直接作为发布译文；"
        "本文件只用于对照/QA。",
        "# 行数：%d" % len(rows),
        "",
    ]
    for row in rows:
        lines.append("%s = %s" % (toml_string(row["hash"]),
                                  toml_string(row["text"])))
    return out_name, "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, help="零售 .pr2loc.zip")
    parser.add_argument("--lang", required=True, help="de/es/pl/ru")
    parser.add_argument("--out", help="输出路径；默认 src/orig/<lang>.retail-<version>.toml")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的输出")
    args = parser.parse_args(argv)

    lang = args.lang.strip().lower()
    manifest, rows, strings_raw = load_retail(args.zip, lang)
    out_name, text = render(manifest, rows, args.zip, strings_raw)
    out_path = args.out or os.path.join(SRC, "orig", out_name)
    if os.path.exists(out_path) and not args.force:
        raise SystemExit("已存在，拒绝覆盖：%s（要覆盖加 --force）" % out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

    # 回读校验：TOML 能解析，行数与 hash 都在。
    with open(out_path, "rb") as fh:
        parsed = tomllib.load(fh)
    if len(parsed) != len(rows):
        raise SystemExit("回读失败：解析 %d 条，预期 %d 条"
                         % (len(parsed), len(rows)))
    print("写入 %s（%d 条）" % (os.path.relpath(out_path, ROOT), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
