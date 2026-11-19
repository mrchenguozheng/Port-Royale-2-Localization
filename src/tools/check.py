#!/usr/bin/env python3
# coding: utf-8
"""check.py —— 提交前统一检查。

依次跑：
1. 跨模块引用检查（lint_imports.py）
2. 语言配置检查（config_check.py）
3. 译文规范复核（analysis/text_lint.py，**逐语言**跑，E 级与 W 级都算失败）
4. 断行长度复核（analysis/line_run.py，**逐语言**跑）
5. 英文微调层自查（translate.py overrides：id 存在、token 一致、不许白改）
6. 不译清单对账（analysis/keep_audit.py：登记的 id 存在、登记项没译过、
   结构性不可译的不许占着待译）
7. 文档一致性（docs_check.py）
8. 脚本地图（tools_check.py：每个脚本都有 docstring、都登记在 README、路径可落地）
9. 规则单元测试（tests/）

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


def langs():
    """`src/packs/*.toml` 的文件名就是启用中的语言代码（config_check 同一口径）。"""
    packs = os.path.join(ROOT, "src", "packs")
    return sorted(n[:-5] for n in os.listdir(packs) if n.endswith(".toml"))


def run_each_lang(title, script, extra=()):
    """逐语言跑一遍，任一语言失败即整体失败。

    只跑默认语言等于没查：`text_lint.py` 不带 `--lang` 时只看 zh，此前
    `check.ps1` 因此只挡住中文的 E 级，其他七语一条都没进 CI（pl 的 W1 就是
    这么漏过去的）。`--strict` 再把 W 级也算失败。
    """
    print("\n== %s ==" % title)
    ok = True
    for lang in langs():
        p = subprocess.run([PY, script, "--lang", lang] + list(extra), cwd=ROOT)
        if p.returncode:
            print("失败：%s（%s，exit %d）" % (title, lang, p.returncode))
            ok = False
    return ok


def main():
    steps = [
        ("跨模块引用", [PY, os.path.join("src", "tools", "lint_imports.py")]),
        ("语言配置", [PY, os.path.join("src", "tools", "config_check.py")]),
        ("英文微调层", [PY, os.path.join("src", "tools", "translate.py"), "overrides"]),
        ("不译清单", [PY, os.path.join("src", "tools", "analysis", "keep_audit.py")]),
        ("文档一致性", [PY, os.path.join("src", "tools", "docs_check.py")]),
        ("脚本地图", [PY, os.path.join("src", "tools", "tools_check.py")]),
        ("规则单测", [PY, "-m", "unittest", "discover", "-s", "tests", "-q"]),
    ]
    if not run("跨模块引用", steps[0][1]):
        return 1
    if not run("语言配置", steps[1][1]):
        return 1
    # 译文规范：逐语言、W 级也算失败
    if not run_each_lang("译文规范", os.path.join("src", "tools", "analysis", "text_lint.py"),
                         ["--strict"]):
        return 1
    # 断行长度：同样逐语言（原来只跑 zh，等同没查）
    if not run_each_lang("断行长度", os.path.join("src", "tools", "analysis", "line_run.py")):
        return 1
    for title, cmd in steps[2:]:
        if not run(title, cmd):
            return 1
    print("\n全部检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
