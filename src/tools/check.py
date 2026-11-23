#!/usr/bin/env python3
# coding: utf-8
"""check.py —— 提交前统一检查。

依次跑：
1. 跨模块引用检查（lint_imports.py）
2. 语言配置检查（config_check.py）
3. 译文规范复核（analysis/text_lint.py，**逐语言**）：发行语言 E 级与 W 级都算失败，
   预览语言只把 E 级算失败（W 级照报，不卡预览进度）
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
import re
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import translate as T                                   # noqa: E402

PACK_TOOLS = os.path.join(HERE, "pack")
if PACK_TOOLS not in sys.path:
    sys.path.insert(0, PACK_TOOLS)
import release_version as RV                            # noqa: E402

SKIP_FILE = os.path.join(ROOT, "src", "data", "check_skip.txt")


def _echo(p, tail=8):
    """把子进程输出原样打出来；失败时再补一小段尾部，省得往上翻几十行找原因。"""
    if p.stdout:
        sys.stdout.write(p.stdout)
    if p.stderr:
        sys.stderr.write(p.stderr)
    if p.returncode:
        rows = [l for l in (p.stdout or "").splitlines() if l.strip()]
        rows += [l for l in (p.stderr or "").splitlines() if l.strip()]
        for l in rows[-tail:]:
            print("   | %s" % l)


def run(title, cmd):
    print("\n== %s ==" % title)
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    _echo(p)
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


def run_each_lang(title, script, langs_, extra=(), jobs=1):
    """逐语言跑一遍，任一语言失败即整体失败。

    只跑默认语言等于没查：`text_lint.py` 不带 `--lang` 时只看 zh，此前
    `check.ps1` 因此只挡住中文的 E 级，其他七语一条都没进过 CI（pl 的 W1
    就是这么漏过去的）。`--strict` 再把 W 级也算失败。

    各语言之间只读、互不写盘，所以 `jobs > 1` 时并行跑；输出仍按语言顺序
    逐块打印，日志可读性与串行一致。
    """
    print("\n== %s ==" % title)
    jobs = max(1, min(int(jobs or 1), len(langs_)))

    def one(lang):
        return lang, subprocess.run([PY, script, "--lang", lang] + list(extra),
                                    cwd=ROOT, capture_output=True, text=True,
                                    encoding="utf-8")

    if jobs == 1:
        results = [one(lang) for lang in langs_]
    else:
        print("（%d 门语言，%d 路并行）" % (len(langs_), jobs))
        sys.stdout.flush()
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(one, langs_))
    ok = True
    for lang, p in results:
        if jobs > 1:
            print("-- %s --" % lang)
        _echo(p)
        if p.returncode:
            print("失败：%s（%s，exit %d）" % (title, lang, p.returncode))
            ok = False
    return ok


def _flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flatten(test)
        else:
            yield test


def shard_cases(shard, total, tests_dir=None):
    """把全部用例按「类」装箱分到 total 片，返回第 shard 片。

    同一测试类不拆：`setUpClass` 只跑一次，与串行时一致。按用例数做贪心
    装箱，33 个测试文件的条数差得远，按文件名取模分不均匀。

    `tests_dir` 按仓库根解析，不依赖当前目录（分片是自身再拉起的子进程，
    从别处调用 `check.py` 时 cwd 不一定是仓库根）。`tests/` 不是包（没有
    `__init__.py`），所以顶层目录就是 `tests/` 本身，与 `-s tests` 一致。
    """
    tests_dir = tests_dir or os.path.join(ROOT, "tests")
    loader = unittest.TestLoader()
    groups = {}
    for case in _flatten(loader.discover(tests_dir, top_level_dir=tests_dir)):
        key = (type(case).__module__, type(case).__qualname__)
        groups.setdefault(key, []).append(case)
    buckets = [[] for _ in range(total)]
    loads = [0] * total
    for _, cases in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        i = loads.index(min(loads))
        buckets[i].extend(cases)
        loads[i] += len(cases)
    suite = unittest.TestSuite()
    for case in buckets[shard]:
        suite.addTest(case)
    return suite


def run_shard(shard, total):
    """只跑这一片单测（分片并行时由自身再拉起来）。"""
    if total < 1 or not 0 <= shard < total:
        print("分片参数不合法：shard=%d total=%d" % (shard, total))
        return 2
    print("\n== 规则单测（片 %d/%d）==" % (shard + 1, total))
    sys.stdout.flush()
    suite = shard_cases(shard, total)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


def run_tests(jobs):
    """规则单测：`jobs > 1` 时分片并行，否则照旧一次 discover。"""
    jobs = max(1, int(jobs or 1))
    if jobs == 1:
        return run("规则单测", [PY, "-m", "unittest", "discover", "-s", "tests", "-q"])
    print("\n== 规则单测（%d 片并行）==" % jobs)
    sys.stdout.flush()

    def one(i):
        return subprocess.run([PY, os.path.join("src", "tools", "check.py"),
                               "--shard", str(i), "--total", str(jobs)],
                              cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8")

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        procs = list(pool.map(one, range(jobs)))
    ok = True
    ran = 0
    for i, p in enumerate(procs):
        print("-- 片 %d/%d --" % (i + 1, jobs))
        _echo(p)
        m = re.search(r"Ran (\d+) tests", (p.stdout or "") + (p.stderr or ""))
        if m:
            ran += int(m.group(1))
        if p.returncode:
            ok = False
    if ok:
        print("合计 Ran %d tests（%d 片）" % (ran, jobs))
    else:
        print("失败：规则单测（%d 片中有片 exit 非 0）" % jobs)
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="提交前统一检查")
    ap.add_argument("--skip-lang", action="append", default=[],
                    metavar="代码", help="临时跳过某门语言（可重复，不写进仓库）")
    ap.add_argument("--jobs", type=int, default=1, metavar="N",
                    help="并行度：逐语言检查与规则单测都用它（默认 1；CI 传 4）")
    ap.add_argument("--shard", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--total", type=int, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.shard is not None:
        return run_shard(args.shard, args.total or 1)

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
    release = set(RV.read_languages(os.path.join(ROOT, "src")))
    strict_langs = [c for c in langs_ if c in release]
    preview_langs = [c for c in langs_ if c not in release]
    if strict_langs and not run_each_lang(
            "译文规范（发行）", lint, strict_langs, ["--strict"], args.jobs):
        return 1
    if preview_langs and not run_each_lang(
            "译文规范（预览）", lint, preview_langs, (), args.jobs):
        return 1
    if not run_each_lang("断行长度", line_run, langs_, (), args.jobs):
        return 1
    if not run_each_lang("不译清单", keep, langs_, (), args.jobs):
        return 1
    steps = [
        ("英文微调层", [PY, os.path.join("src", "tools", "translate.py"), "overrides"]),
        ("文档一致性", [PY, os.path.join("src", "tools", "docs_check.py")]),
        ("脚本地图", [PY, os.path.join("src", "tools", "tools_check.py")]),
    ]
    for title, cmd in steps:
        if not run(title, cmd):
            return 1
    if not run_tests(args.jobs):
        return 1
    print("\n全部检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
