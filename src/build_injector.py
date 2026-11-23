#!/usr/bin/env python3
# coding: utf-8
"""build_injector.py —— 编译 Rust 运行时并铺 build/runtime。"""
import argparse
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
RUST = os.path.join(SRC, "injector-rs")
RUNTIME = os.path.join(REPO, "build", "runtime")
TARGET = "i686-pc-windows-msvc"
ARTIFACTS = {
    "PR2LocalizationCore.dll": "PR2LocalizationCore.dll",
    "PR2Localization.exe": "PR2Localization.exe",
    "PR2LocalizationGUI.exe": "PR2LocalizationGUI.exe",
    "PR2LocalizationProxy.dll": "VERSION.dll",
    "pr2_host_proxy.dll": "Ascaron.Logging-2.6.dll",
}


def run(args, cwd=None):
    print("$ " + " ".join(args))
    return subprocess.run(args, cwd=cwd).returncode


def git_out(*args):
    try:
        out = subprocess.run(
            ["git", "-C", REPO] + list(args),
            capture_output=True, text=True, check=False)
        return out.stdout.strip() if out.returncode == 0 else ""
    except OSError:
        return ""


def main():
    parser = argparse.ArgumentParser(description="构建 PR2 本地化运行时")
    parser.add_argument("--no-pause", action="store_true",
                        help="兼容旧入口，无实际作用")
    parser.parse_args()

    if not os.path.isfile(os.path.join(RUST, "Cargo.toml")):
        print("[build] ERROR: 找不到 %s" % os.path.join(RUST, "Cargo.toml"))
        return 1

    cargo = shutil.which("cargo") or os.path.join(
        os.environ.get("USERPROFILE", ""), ".cargo", "bin", "cargo.exe")
    if not os.path.isfile(cargo) and not shutil.which(cargo):
        print("[build] ERROR: 找不到 cargo.exe。")
        print("[build] 安装 rustup 后执行：rustup target add i686-pc-windows-msvc")
        return 1
    cargo = shutil.which("cargo") or cargo

    version = os.environ.get("PR2_VERSION", "")
    if not version:
        tag = git_out("describe", "--tags", "--exact-match")
        if tag:
            version = tag
            if version.startswith("release-"):
                version = version[len("release-"):]
    os.environ["PR2_VERSION"] = version
    os.environ.setdefault("PR2_COMMIT", git_out("rev-parse", "--short", "HEAD"))
    if "PR2_DIRTY" not in os.environ:
        os.environ["PR2_DIRTY"] = "1" if git_out("status", "--porcelain") else "0"

    show_version = version or "dev"
    print("[build] 版本：%s · commit %s%s" % (
        show_version, os.environ.get("PR2_COMMIT") or "unknown",
        "（未提交改动）" if os.environ.get("PR2_DIRTY") == "1" else ""))

    if run([cargo, "build", "--release", "--locked"], cwd=RUST) != 0:
        print("[build] FAILED. 见上方错误。")
        return 1

    out = os.path.join(RUST, "target", TARGET, "release")
    missing = [n for n in ARTIFACTS if not os.path.isfile(os.path.join(out, n))]
    if missing:
        print("[build] FAILED: 缺 " + "、".join(missing))
        return 1

    os.makedirs(RUNTIME, exist_ok=True)
    for src_name, dst_name in ARTIFACTS.items():
        shutil.copy2(os.path.join(out, src_name), os.path.join(RUNTIME, dst_name))

    stamp = os.path.join(REPO, "build", "injector-version.txt")
    with open(stamp, "w", encoding="utf-8") as fh:
        fh.write(show_version)

    data = os.path.join(RUNTIME, "PR2Localization")
    os.makedirs(os.path.join(data, "logs"), exist_ok=True)

    ui_src = os.path.join(RUST, "ui")
    if os.path.isdir(ui_src):
        ui_out = os.path.join(data, "ui")
        os.makedirs(ui_out, exist_ok=True)
        zh = os.path.join(ui_src, "ui.zh.ini")
        if not os.path.isfile(zh):
            print("[build] 缺简体中文界面文案：%s" % zh)
            return 1
        for name in os.listdir(ui_src):
            if name.startswith("ui.") and name.endswith(".ini"):
                shutil.copy2(os.path.join(ui_src, name), os.path.join(ui_out, name))
        shutil.copy2(zh, os.path.join(ui_out, "ui.default.ini"))
        for stale in ("en.ini", "ja.ini", "zh.ini"):
            path = os.path.join(ui_out, stale)
            if os.path.isfile(path):
                os.remove(path)

    font_src = os.path.join(SRC, "font-map.ini")
    if not os.path.isfile(font_src):
        print("[build] 缺字体映射模板：%s" % font_src)
        return 1
    font_out = os.path.join(data, "fonts")
    os.makedirs(font_out, exist_ok=True)
    shutil.copy2(font_src, os.path.join(font_out, "font-map.default.ini"))

    print("\n[build] SUCCESS:")
    for src_name, dst_name in ARTIFACTS.items():
        print("  %s  ->  %s" % (src_name, dst_name))
    print("  data  ->  %s" % data)
    print("\n[build] Next:  python src/build_translation.py --lang zh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
