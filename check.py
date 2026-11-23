#!/usr/bin/env python3
# coding: utf-8
"""check.py —— Rust 闸门 + Python 静态检查与单测。"""
import argparse
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
RUST = os.path.join(REPO, "src", "injector-rs")
CHECK = os.path.join(REPO, "src", "tools", "check.py")


def run(cmd, cwd=None):
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd).returncode


def rust_gate():
    cargo = shutil.which("cargo")
    if not cargo:
        print("找不到 cargo.exe；没装 Rust 工具链时用 --skip-rust。")
        return 1
    checks = [
        ([cargo, "fmt", "--all", "--", "--check"], "Rust 格式不一致：先 cargo fmt --all。"),
        ([cargo, "clippy", "--workspace", "--all-targets", "--locked", "--", "-D", "warnings"],
         "clippy 有错误或警告（-D warnings）。"),
        ([cargo, "test", "--workspace", "--locked"], "Rust 单测失败。"),
    ]
    for cmd, message in checks:
        if run(cmd, cwd=RUST) != 0:
            print(message)
            return 1

    raw = subprocess.run(
        [cargo, "metadata", "--no-deps", "--format-version", "1", "--locked"],
        cwd=RUST, capture_output=True, text=True)
    if raw.returncode != 0:
        print("读不到 cargo workspace 成员。")
        return 1
    members = [pkg["name"] for pkg in json.loads(raw.stdout)["packages"]]
    for member in members:
        if run([cargo, "check", "--locked", "-p", member], cwd=RUST) != 0:
            print("crate 单独构建失败：%s" % member)
            return 1
    print("[check] Rust 闸门通过：%d 个 crate 单独构建" % len(members))
    return 0


def main():
    parser = argparse.ArgumentParser(description="PR2 全量检查")
    parser.add_argument("--skip-lang", action="append", default=[])
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--skip-rust", action="store_true")
    parser.add_argument("--no-pause", action="store_true")
    args = parser.parse_args()

    if not args.skip_rust:
        if rust_gate() != 0:
            return 1
    else:
        print("[check] 已跳过 Rust 闸门")

    cmd = [sys.executable, CHECK]
    for lang in args.skip_lang:
        cmd += ["--skip-lang", lang]
    if args.jobs > 1:
        cmd += ["--jobs", str(args.jobs)]
    return run(cmd)


if __name__ == "__main__":
    sys.exit(main())
