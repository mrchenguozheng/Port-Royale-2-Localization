#!/usr/bin/env python3
# coding: utf-8
"""release.py —— 构建运行时、按分组打 zip、写校验和与 release.json。

版本 tag 使用普通语义化版本 ``vX.Y.Z``，不覆盖已有 tag；CI 只构建，
GitHub Release 由维护者从草稿里选择发布。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "src")
FONT_DIR = os.path.join(REPO, "assets", "fonts", "noto")
MAKE_RELEASE = os.path.join(SRC, "tools", "pack", "make_release.py")
CHECK_FONTS = os.path.join(SRC, "tools", "font", "fetch_noto_fonts.py")
CONFIG_CHECK = os.path.join(SRC, "tools", "config_check.py")
LANG_FILE = os.path.join(SRC, "release-languages.txt")
VERSION_RX = re.compile(r"^v\d+\.\d+\.\d+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
LANG_RX = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")


def die(message):
    print("[release] " + message)
    raise SystemExit(1)


def run(args, cwd=None, capture=False):
    print("$ " + " ".join(args))
    env = dict(os.environ)
    env["PR2_FONT_DIRS"] = FONT_DIR
    if capture:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    return subprocess.run(args, cwd=cwd, env=env).returncode


def git(*args):
    out = subprocess.run(["git", "-C", REPO] + list(args),
                         capture_output=True, text=True)
    return out.returncode, out.stdout.strip()


def read_languages():
    names = []
    with open(LANG_FILE, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if line:
                names.extend(part for part in re.split(r"[,\s]+", line) if part)
    return list(dict.fromkeys(names))


def read_bundles(selected):
    out = run([sys.executable, MAKE_RELEASE, "--list-bundles"], capture=True)
    if out.returncode != 0:
        die("读不到发行分组：src/release-bundles.toml")
    bundles = []
    for line in out.stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            bundles.append({
                "id": parts[0],
                "default": parts[1],
                "langs": [x for x in parts[2].split(",") if x],
            })
    if not bundles:
        die("发行分组清单为空：src/release-bundles.toml")
    if selected:
        wanted = [x.strip() for item in selected for x in item.split(",") if x.strip()]
        missing = [x for x in wanted if x not in {b["id"] for b in bundles}]
        if missing:
            die("没有这个分组：" + "、".join(missing))
        bundles = [b for b in bundles if b["id"] in wanted]
    return bundles


def assert_languages(langs):
    problems = []
    for lang in langs:
        if not LANG_RX.match(lang):
            problems.append("语言代码不合法：%s" % lang)
            continue
        for rel in ("src/packs/%s.toml" % lang, "src/translations/%s.toml" % lang):
            if not os.path.isfile(os.path.join(REPO, rel)):
                problems.append("缺 " + rel)
    if problems:
        die("发行语言不全：" + "；".join(problems))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    parser = argparse.ArgumentParser(description="构建 PR2 发行包")
    parser.add_argument("--version", required=True)
    parser.add_argument("--lang", action="append", default=[])
    parser.add_argument("--bundle", action="append", default=[])
    parser.add_argument("--out", default="dist")
    parser.add_argument("--fonts", choices=["auto", "noto", "config", "none"],
                        default="auto")
    parser.add_argument("--skip-injector", action="store_true")
    parser.add_argument("--no-font-cache", action="store_true")
    parser.add_argument("--tag", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--no-pause", action="store_true")
    args = parser.parse_args()

    version = args.version.strip()
    if not version.startswith("v"):
        version = "v" + version
    if not VERSION_RX.match(version):
        die("版本号不合法：%s；只接受 vMAJOR.MINOR.PATCH[-prerelease]" % version)

    if args.tag and args.allow_dirty:
        die("--tag 与 --allow-dirty 不能同时使用。")
    code, commit = git("rev-parse", "--short", "HEAD")
    if code != 0:
        die("不是 git 仓库，无法确认 commit。")
    _, porcelain = git("status", "--porcelain")
    dirty = bool(porcelain)
    if dirty:
        if args.tag:
            die("工作树有未提交改动，不能打 tag：\n" + porcelain)
        if not args.allow_dirty:
            die("工作树有未提交改动，拒绝出包：\n" + porcelain +
                "\n先提交，或显式加 --allow-dirty。")
        print("[release] 警告：工作树有未提交改动（--allow-dirty）。")
    print("[release] commit：%s%s" % (commit, "（dirty）" if dirty else ""))

    lang_mode = bool(args.lang)
    if lang_mode and args.bundle:
        die("--lang 与 --bundle 只能给一个。")
    if lang_mode:
        langs = list(dict.fromkeys(
            x.strip() for item in args.lang for x in item.split(",") if x.strip()))
        groups = []
    else:
        groups = read_bundles(args.bundle)
        langs = list(dict.fromkeys(l for g in groups for l in g["langs"]))
        declared = read_languages()
        outside = [l for l in langs if l not in declared]
        if outside:
            die("分组里有语言不在 src/release-languages.txt：" + "、".join(outside))
    if not langs:
        die("没有发行语言。")
    assert_languages(langs)

    # 字体必须在仓库里，且在编译注入器之前确认。
    print("[release] 检查仓库字体")
    print("$ python src/tools/font/fetch_noto_fonts.py --no-system")
    if run([sys.executable, CHECK_FONTS, "--no-system"]) != 0:
        die("Noto 源字体缺失：assets/fonts/noto 必须带齐 src/fonts-sources.toml 列出的文件。")

    out_dir = args.out if os.path.isabs(args.out) else os.path.join(REPO, args.out)
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        path = os.path.join(out_dir, name)
        if os.path.isdir(path) and re.match(r"PR2-.*-v", name):
            shutil.rmtree(path)
        elif os.path.isfile(path) and re.match(
                r"PR2-.*-%s\.zip$" % re.escape(version), name):
            os.remove(path)

    print("[release] 版本：%s" % version)
    print("[release] 语言：%s" % ", ".join(langs))
    if groups:
        print("[release] 分组：%s" % " ".join(
            "%s(%s)" % (g["id"], "+".join(g["langs"])) for g in groups))
    print("[release] 输出：%s" % out_dir)
    print("[release] 字体：%s" % args.fonts)

    print("\n[release] 0/2 检查语言配置")
    if run([sys.executable, CONFIG_CHECK]) != 0:
        die("语言配置检查失败。")

    if not args.skip_injector:
        print("\n[release] 1/2 构建注入器")
        os.environ["PR2_VERSION"] = version
        if run([sys.executable, os.path.join(REPO, "build.py"),
                "--target", "injector", "--no-pause"]) != 0:
            die("构建注入器失败。")
    else:
        print("\n[release] 1/2 跳过注入器")
        stamp = os.path.join(REPO, "build", "injector-version.txt")
        built = ""
        if os.path.isfile(stamp):
            with open(stamp, encoding="utf-8") as fh:
                built = fh.readline().strip()
        if not built:
            die("无法确认现有 exe 版本：build/injector-version.txt 不存在。")
        if built != version:
            die("现有运行时编的是 %s，本次发行版本是 %s。" % (built, version))
        print("[release] 现有运行时版本：%s（与本次发行一致）" % built)

    print("\n[release] 2/2 组装发行包")
    if groups:
        for group in groups:
            cmd = [sys.executable, MAKE_RELEASE, "--version", version,
                   "--out", out_dir, "--fonts", args.fonts,
                   "--bundle", group["id"]]
            if args.no_font_cache:
                cmd.append("--no-font-cache")
            print("\n[release] 分组 %s：%s" % (group["id"], ", ".join(group["langs"])))
            if run(cmd) != 0:
                die("生成 %s 发行包失败。" % group["id"])
    else:
        cmd = [sys.executable, MAKE_RELEASE, "--version", version,
               "--out", out_dir, "--fonts", args.fonts]
        for lang in langs:
            cmd += ["--lang", lang]
        if args.no_font_cache:
            cmd.append("--no-font-cache")
        if run(cmd) != 0:
            die("生成发行包失败。")

    zips = sorted(
        os.path.join(out_dir, n) for n in os.listdir(out_dir)
        if n.startswith("PR2-") and n.endswith("-%s.zip" % version))
    if not zips:
        die("没有找到生成的 zip：%s" % os.path.join(out_dir, "PR2-*-%s.zip" % version))
    artifacts = [{"file": os.path.basename(z), "sha256": sha256(z),
                  "size": os.path.getsize(z)} for z in zips]

    sums_path = os.path.join(out_dir, "SHA256SUMS.txt")
    with open(sums_path, "w", encoding="utf-8", newline="\n") as fh:
        for item in artifacts:
            fh.write("%s  %s\n" % (item["sha256"], item["file"]))

    meta_bundles = []
    if groups:
        for group in groups:
            name = "PR2-%s-%s.zip" % (group["id"], version)
            found = next((a for a in artifacts if a["file"] == name), None)
            if not found:
                die("分组 %s 没有生成 %s" % (group["id"], name))
            meta_bundles.append({
                "id": group["id"], "default": group["default"],
                "langs": group["langs"], "file": found["file"],
                "sha256": found["sha256"], "size": found["size"],
            })
    else:
        for lang in langs:
            name = "PR2-%s-%s.zip" % (lang, version)
            found = next((a for a in artifacts if a["file"] == name), None)
            if not found:
                die("语言 %s 没有生成 %s" % (lang, name))
            meta_bundles.append({
                "id": lang, "default": lang, "langs": [lang],
                "file": found["file"], "sha256": found["sha256"],
                "size": found["size"],
            })

    meta_path = os.path.join(out_dir, "release.json")
    meta = {
        "version": version, "commit": commit, "dirty": dirty,
        "pack_mode": "bundle" if groups else "lang",
        "languages": langs, "bundles": meta_bundles,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(meta_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print("\n[release] 已生成：")
    for path in zips:
        print("  %s  (%.1f MB)" % (path, os.path.getsize(path) / (1024 * 1024)))
    print("  " + sums_path)
    print("  " + meta_path)

    if args.tag:
        tag_name = version
        _, branch = git("rev-parse", "--abbrev-ref", "HEAD")
        if branch != "main" and not branch.startswith("release/"):
            die("当前分支是 %s；打 tag 只允许在 main 或 release/* 上。" % branch)
        _, porcelain = git("status", "--porcelain")
        if porcelain:
            die("工作树有未提交改动，先提交再打 tag：\n" + porcelain)
        code, existing = git("tag", "-l", tag_name)
        if existing:
            die("tag 已存在：%s（普通版本 tag 不覆盖）" % tag_name)
        if git("tag", "-a", tag_name, "-m", "PR2 Localization %s" % version)[0] != 0:
            die("创建 tag 失败：%s" % tag_name)
        print("[release] 已创建 annotated tag：%s" % tag_name)
        if args.push:
            if git("push", "origin", tag_name)[0] != 0:
                die("推送 tag 失败：%s" % tag_name)
            print("[release] 已推送 tag：%s" % tag_name)

    print("\n[release] 完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
