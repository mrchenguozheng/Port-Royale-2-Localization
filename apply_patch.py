#!/usr/bin/env python3
# coding: utf-8
"""apply_patch.py —— 归一化 → 校验 → 编译 → 部署 → 核对。"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(REPO, "src", "tools", "pack", "apply_patch.py")

if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, TOOL] + sys.argv[1:]).returncode)
