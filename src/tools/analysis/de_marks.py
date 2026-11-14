#!/usr/bin/env python
# coding: utf-8
"""生成一个可以单独选中的排查语言包 de-debug.txt。

    python src/tools/analysis/de_marks.py

产物：build\\debug\\de-marks\\de-debug.txt
用法：把这个文件复制到 PR2Localization\\packs\\ 下，启动器语言列表里会多出
一项 "Deutsch (Debug)"，选它进游戏即可；de.txt 一个字都不用动，正式的德语包
不受任何影响，排查完在列表里选回 Deutsch 就行，也可以直接删掉这个文件。

标记形如 `[0BEE]`，取 id 尾数（逐条取能区分自己的最短尾数，本批 4~8 位，
3548 条全部唯一）。标记插在行首标签之后，不影响 <ts:>/<f:fonts/> 与占位。

限制：每条长 4~7 个字符，短标签会被挤到溢出或换行，只适合排查，不适合游玩；
同文条目（de_index 里的 dup 簇）在画面上仍是同一句，只能记到簇一级。
"""

import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(SRC)
OUT = os.path.join(ROOT, "build", "debug", "de-marks")
CODE = "de-debug"
ALIAS = "Deutsch (Debug)"
MARK = re.compile(r"^0x[0-9A-F]{8} = (?:<[^>\n]*>)*\[[0-9A-F]{4,8}\] ")


def build():
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, "de.txt")
    r = subprocess.run([sys.executable, os.path.join(SRC, "tools", "pack", "compile_pack.py"),
                        "--lang", "de", "--out", OUT, "--strict", "--no-fonts", "--marks"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    print(((r.stdout or "") + (r.stderr or "")).rstrip())
    if r.returncode != 0:
        raise SystemExit("编译失败（退出码 %d）" % r.returncode)

    lines = io.open(tmp, encoding="utf-8").read().split("\n")
    out, done = [], False
    for l in lines:
        if l.startswith("# pack-meta alias=") and not done:
            out.append("# pack-meta alias=%s" % ALIAS)
            done = True
            continue
        out.append(l)
    if not done:
        out.insert(0, "# pack-meta alias=%s" % ALIAS)
    path = os.path.join(OUT, CODE + ".txt")
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(out))

    total = sum(1 for l in out if l.startswith("0x"))
    marked = sum(1 for l in out if MARK.match(l))
    print("产物 %s：条目 %d、带标记 %d、%d 字节"
          % (path, total, marked, os.path.getsize(path)))
    if marked != total:
        raise SystemExit("有 %d 条没加上标记" % (total - marked))
    print("复制到 PR2Localization\\packs\\ 后，启动器语言列表会多出 \"%s\"（代码 %s）"
          % (ALIAS, CODE))


if __name__ == "__main__":
    build()
