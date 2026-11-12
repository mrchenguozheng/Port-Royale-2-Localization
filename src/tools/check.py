#!/usr/bin/env python3
# coding: utf-8
"""check.py —— 提交前统一检查。

依次跑：
1. 跨模块引用检查（lint_imports.py）
2. 规则单元测试（tests/）
3. （已移除：live 可手改，不再要求等于规则输出）

    python src/tools/check.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable


def run(title, cmd):
    print("\n== %s ==" % title)
    p = subprocess.run(cmd, cwd=ROOT)
    if p.returncode:
        print("失败：%s（exit %d）" % (title, p.returncode))
        return False
    return True


def main():
    steps = [
        ("跨模块引用", [PY, os.path.join("src", "tools", "lint_imports.py")]),
        ("规则单测", [PY, "-m", "unittest", "discover", "-s", "tests", "-q"]),
    ]
    for title, cmd in steps:
        if not run(title, cmd):
            return 1
    print("\n全部检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
