#!/usr/bin/env python3
# coding: utf-8
"""precommit.py —— 轻量提交前检查：语言配置、文档、截图画廊。"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(REPO, "src", "tools", "precommit.py")

if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, TOOL] + sys.argv[1:]).returncode)
