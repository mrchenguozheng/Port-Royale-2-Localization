"""改前／改后语法命中比对。

用法：

    python -X utf8 src/tools/qa/ab_diff.py fr
    python -X utf8 src/tools/qa/ab_diff.py fr --file src/tools/analysis/lang_check.py

把 `HEAD` 版与工作树版（或指定文件当前内容）两份 lang_check 各加载一次，对同一份
译文集跑 `grammar()`，输出规则集合的 gone／new／delta 与两边总命中数。产物写
`build/qa/ab_diff_<lang>.txt`。

为什么要有这个脚本：改替身池、改渲染顺序这类改动会让全局 `rng` 的消费序列整体漂移，
总命中数天然不可比；能判「有没有引入新规则」的只有规则集合差异。以前这一步靠手工
`git checkout`＋跑两次 dump＋`git checkout` 回来，中途覆盖文件还会丢读数。

注意：`grammar()` 每版各跑一遍，两边都会把本轮新认出的专名并入内存表（下一轮才生效），
所以两边的 hits 差里含这部分噪声；stderr 各自会打「新认出 N 个专名」，看 diff 时一并读。
"""
import argparse
import collections
import importlib.util
import io
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, ROOT)

GIT_EXE = os.environ.get("GIT_EXE") or r"C:\Program Files\Git\cmd\git.exe"
TMPDIR = os.path.join(ROOT, "build", "qa", "_head")


def git(*args):
    for exe in (GIT_EXE, "git"):
        try:
            r = subprocess.run([exe] + list(args), cwd=ROOT, capture_output=True,
                               text=True, encoding="utf-8")
        except FileNotFoundError:
            continue
        if r.returncode == 0:
            return r.stdout
    return None


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def counts(hits):
    return collections.Counter(h[1] for h in hits)


def dump(mod, lang, tr):
    n_keys, hits = mod.grammar(lang, tr)
    return n_keys, hits, counts(hits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lang")
    ap.add_argument("--file", default=os.path.join("src", "tools", "analysis", "lang_check.py"))
    ap.add_argument("--rev", default="HEAD", help="基线提交，默认 HEAD；可给 87ba9a2 这类短哈希")
    ap.add_argument("--no-head", action="store_true", help="只跑工作树版")
    args = ap.parse_args()

    rel = args.file.replace("\\", "/")
    cur_path = os.path.join(ROOT, rel)
    if not os.path.exists(cur_path):
        sys.exit("找不到 %s" % cur_path)

    sys.path.insert(0, os.path.join(ROOT, "src", "tools", "analysis"))
    from text import toml_io  # noqa: E402

    tr, _ = toml_io.read_doc(os.path.join(ROOT, "src", "translations", args.lang + ".toml"))
    head = (git("rev-parse", "--short", "HEAD") or "").strip() or "?"

    rows = []
    if not args.no_head:
        text = git("show", "%s:%s" % (args.rev, rel))
        if text is None:
            sys.exit("git show %s:%s 失败" % (args.rev, rel))
        os.makedirs(TMPDIR, exist_ok=True)
        base_path = os.path.join(TMPDIR, os.path.basename(rel))
        with io.open(base_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        rev = (git("rev-parse", "--short", args.rev) or args.rev).strip()
        sys.stderr.write("[base] %s @ %s\n" % (rel, rev))
        mod = load(base_path, "lang_check_base")
        rows.append(("base(%s)" % rev, base_path) + dump(mod, args.lang, tr))

    sys.stderr.write("[cur ] %s 工作树\n" % rel)
    mod = load(cur_path, "lang_check_cur")
    rows.append(("cur(worktree)", cur_path) + dump(mod, args.lang, tr))

    lines = []
    lines.append("lang=%s file=%s head=%s at=%s" % (args.lang, rel, head,
                                                    time.strftime("%Y-%m-%d %H:%M:%S")))
    for label, _p, n_keys, hits, _c in rows:
        lines.append("%-22s keys=%d hits=%d rules=%d" % (label, n_keys, len(hits), len(_c)))

    if len(rows) == 2:
        a = rows[0][4]
        b = rows[1][4]
        gone = sorted(set(a) - set(b))
        new = sorted(set(b) - set(a))
        lines.append("")
        lines.append("gone(%d): %s" % (len(gone), ", ".join(gone) or "-"))
        lines.append("new(%d): %s" % (len(new), ", ".join(new) or "-"))
        lines.append("")
        lines.append("%-40s %6s %6s %6s" % ("rule", "base", "cur", "delta"))
        for k in sorted(set(a) | set(b)):
            va, vb = a.get(k, 0), b.get(k, 0)
            if va != vb:
                lines.append("%-40s %6d %6d %+6d" % (k, va, vb, vb - va))
        total = sum(b.values()) - sum(a.values())
        lines.append("%-40s %6d %6d %+6d" % ("TOTAL", sum(a.values()), sum(b.values()), total))
        if new:
            lines.append("")
            lines.append("!! 新规则：%s —— 先判是不是渲染造错，别当成译文新增错" % ", ".join(new))

    out = os.path.join(ROOT, "build", "qa", "ab_diff_%s.txt" % args.lang)
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\n写出", out)


if __name__ == "__main__":
    main()
