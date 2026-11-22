"""全量语法命中导出（含长尾规则）。

用法：

    python -X utf8 src/tools/qa/dump_hits.py <lang>

产物 `build/qa/<lang>_hits_all.txt`，首行写元数据（提交、语言、送检数、命中数、规则数、
渲染种子、时间）。同一个文件名在不同提交下可能是「跨条丢弃前 405／105」也可能是
「之后 352／74」，没有这行元数据就只能靠猜。
"""
import collections
import io
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "analysis"))
sys.path.insert(0, ROOT)

import lang_check as LC  # noqa: E402
from text import toml_io  # noqa: E402

GIT_EXE = os.environ.get("GIT_EXE") or r"C:\Program Files\Git\cmd\git.exe"


def head_rev():
    for exe in (GIT_EXE, "git"):
        try:
            r = subprocess.run([exe, "rev-parse", "--short", "HEAD"], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8")
        except FileNotFoundError:
            continue
        if r.returncode == 0:
            return r.stdout.strip()
    return "?"


def main():
    lang = sys.argv[1] if len(sys.argv) > 1 else "fr"
    tr, _ = toml_io.read_doc(os.path.join(ROOT, "src", "translations", lang + ".toml"))
    n_keys, hits = LC.grammar(lang, tr)
    rules = len({h[1] for h in hits})
    print("keys:", n_keys, "hits:", len(hits), "rules:", rules)

    path = os.path.join(ROOT, "build", "qa", lang + "_hits_all.txt")
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# head=%s lang=%s keys=%d hits=%d rules=%d seed=%s at=%s\n" % (
            head_rev(), lang, n_keys, len(hits), rules, LC.RENDER_SEED,
            time.strftime("%Y-%m-%d %H:%M:%S")))
        for k, rule, ctx, rep in sorted(hits, key=lambda h: (h[1], h[0])):
            fh.write("%s\t%s\t%s\t%s\n" % (rule, k, ctx, rep))
    print("写出", path)


if __name__ == "__main__":
    main()
