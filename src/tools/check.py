#!/usr/bin/env python3
# coding: utf-8
"""check.py —— 提交前统一检查。

依次跑：
1. 跨模块引用检查（lint_imports.py）
2. 语言配置检查（config_check.py）
3. 译文规范复核（analysis/text_lint.py，**逐语言**，E 级与 W 级都算失败）
4. 断行长度复核（analysis/line_run.py，**逐语言**）
5. 英文微调层自查（translate.py overrides：id 存在、token 一致、不许白改）
6. 不译清单对账（analysis/keep_audit.py，**逐语言**：登记的 id 存在、登记项
   没译过、结构性不可译的不许占着待译）
7. 文档一致性（docs_check.py）
8. 脚本地图（tools_check.py：每个脚本都有 docstring、都登记在 README、路径可落地）
9. 规则单元测试（tests/）

语言清单只认一处：`translate.target_langs()`（即 `src/translations/*.toml` 里
可编辑的那些），新加一门语言不需要再来这里登记。**默认每门语言都要过**，
要跳过必须显式：

- `src/data/check_skip.txt` 一行一门：`代码<TAB>理由`（或 `代码  # 理由`），
  理由会打在报告头上 —— 跳过的语言在 git 里留痕，不会被当成「查过了」；
  这份清单里出现不存在的语言代码直接算失败（防手滑）。
- 命令行 `--skip-lang xx`（可重复），用于本地临时排障，不写进仓库。

    python src/tools/check.py
    python src/tools/check.py --skip-lang pl      # 临时跳过波兰语
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import translate as T                                   # noqa: E402

SKIP_FILE = os.path.join(ROOT, "src", "data", "check_skip.txt")


def run(title, cmd):
    print("\n== %s ==" % title)
    p = subprocess.run(cmd, cwd=ROOT)
    if p.returncode:
        print("失败：%s（exit %d）" % (title, p.returncode))
        return False
    return True


def read_skip_file():
    """`代码<TAB>理由`；返回 ({代码: 理由}, 坏行清单)。"""
    if not os.path.exists(SKIP_FILE):
        return {}, []
    skip, bad = {}, []
    with open(SKIP_FILE, encoding="utf-8") as f:
        for no, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" in line:
                code, reason = line.split("\t", 1)
            elif "  # " in line:
                code, reason = line.split("  # ", 1)
            else:
                code, reason = line, ""
            if "  # " in reason:
                reason = reason.split("  # ", 1)[0]
            code, reason = code.strip(), reason.strip()
            if not code:
                bad.append("%d 行：没有语言代码" % no)
                continue
            skip[code] = reason or "未写理由"
    return skip, bad


def langs(skip):
    """要跑的语言：全部可编辑译文语言减去显式跳过的。返回 (语言表, 错误)。"""
    all_langs = T.target_langs()
    errors = []
    unknown = sorted(set(skip) - set(all_langs))
    if unknown:
        errors.append("check_skip：%s 不是已存在的译文语言（现有：%s）"
                      % ("、".join(unknown), "、".join(all_langs)))
    return [c for c in all_langs if c not in skip], errors


def run_each_lang(title, script, langs_, extra=()):
    """逐语言跑一遍，任一语言失败即整体失败。

    只跑默认语言等于没查：`text_lint.py` 不带 `--lang` 时只看 zh，此前
    `check.ps1` 因此只挡住中文的 E 级，其他七语一条都没进过 CI（pl 的 W1
    就是这么漏过去的）。`--strict` 再把 W 级也算失败。
    """
    print("\n== %s ==" % title)
    ok = True
    for lang in langs_:
        p = subprocess.run([PY, script, "--lang", lang] + list(extra), cwd=ROOT)
        if p.returncode:
            print("失败：%s（%s，exit %d）" % (title, lang, p.returncode))
            ok = False
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="提交前统一检查")
    ap.add_argument("--skip-lang", action="append", default=[],
                    metavar="代码", help="临时跳过某门语言（可重复，不写进仓库）")
    args = ap.parse_args(argv)

    skip, bad = read_skip_file()
    for line in bad:
        print("检查跳过清单有坏行：%s" % line)
    if bad:
        return 1
    for code in args.skip_lang:
        skip[code] = "命令行 --skip-lang"
    langs_, errors = langs(skip)
    for err in errors:
        print(err)
    if errors:
        return 1
    if skip:
        print("跳过语言（%d 门）：%s"
              % (len(skip), "；".join("%s —— %s" % (c, r) for c, r in sorted(skip.items()))))
    print("本次检查语言：%s" % "、".join(langs_))

    lint = os.path.join("src", "tools", "analysis", "text_lint.py")
    line_run = os.path.join("src", "tools", "analysis", "line_run.py")
    keep = os.path.join("src", "tools", "analysis", "keep_audit.py")
    if not run("跨模块引用", [PY, os.path.join("src", "tools", "lint_imports.py")]):
        return 1
    if not run("语言配置", [PY, os.path.join("src", "tools", "config_check.py")]):
        return 1
    if not run_each_lang("译文规范", lint, langs_, ["--strict"]):
        return 1
    if not run_each_lang("断行长度", line_run, langs_):
        return 1
    if not run_each_lang("不译清单", keep, langs_):
        return 1
    steps = [
        ("英文微调层", [PY, os.path.join("src", "tools", "translate.py"), "overrides"]),
        ("文档一致性", [PY, os.path.join("src", "tools", "docs_check.py")]),
        ("脚本地图", [PY, os.path.join("src", "tools", "tools_check.py")]),
        ("规则单测", [PY, "-m", "unittest", "discover", "-s", "tests", "-q"]),
    ]
    for title, cmd in steps:
        if not run(title, cmd):
            return 1
    print("\n全部检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
