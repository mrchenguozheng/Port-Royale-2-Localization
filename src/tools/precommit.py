#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量 pre-commit：只跑不依赖 Rust 工具链的本地闸门。

完整构建与游戏内验收仍在 ``check.ps1`` / CI。这里挡的是最容易在提交前
漏掉、又能在几秒内发现的问题：

- 语言配置与语言注册表对账（``config_check.py``）；
- 文档索引、码表与语言矩阵是否漂移（``docs_check.py``）；
- 截图画廊 HTML / Markdown / 缩略图是否为最新生成物
  （``build_screenshots.py --check``）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKS = [
    ("配置检查", [ROOT / "src" / "tools" / "config_check.py"]),
    ("文档检查", [ROOT / "src" / "tools" / "docs_check.py"]),
    (
        "截图画廊",
        [ROOT / "src" / "tools" / "docs" / "build_screenshots.py", "--check"],
    ),
]


def main() -> int:
    for name, args in CHECKS:
        print(f"[pre-commit] {name} …")
        completed = subprocess.run([sys.executable, *map(str, args)], cwd=ROOT)
        if completed.returncode:
            print(
                f"[pre-commit] {name} 未通过；修好后重新 git add / git commit。",
                file=sys.stderr,
            )
            return completed.returncode
    print("[pre-commit] 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
