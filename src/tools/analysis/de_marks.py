#!/usr/bin/env python
# coding: utf-8
"""开发用排查包：给每条德文加 [XXXX] 标记，进游戏就能读出 key。

标记只在编译期加，`src/translations/de.toml` 一个字都不改；正常包也不受影响：
普通编译不带 `--marks`，产物里一个标记都没有。

    python src/tools/analysis/de_marks.py --build      # 编出带标记的排查包
    python src/tools/analysis/de_marks.py --install    # 装进游戏（先备份正常包）
    python src/tools/analysis/de_marks.py --restore    # 还原正常包

标记形如 `[D6E4]`，取 id 尾部 4 位十六进制；若 4 位有重号会自动加长到 6/8 位，
保证 3548 条一一对应。标记插在行首标签（<ts:>/<f:fonts/> 等）之后，
不影响标签解析与占位。

限速说明：加标记后每条长 7 个字符，版式会乱，只能用来排查，
不能用来正常游玩；同文条目（`de_index` 里的 dup 簇）在画面上仍分不出彼此，
只能记到簇一级。
"""

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(SRC)
TARGET = r"C:\Program Files (x86)\GOG Galaxy\Games\Port Royale 2"
PACKS = os.path.join(TARGET, "PR2Localization", "packs")
OUT = os.path.join(ROOT, "build", "debug", "de-marks")
BACKUP = os.path.join(os.environ.get("TEMP", ROOT), "de_normal.bak")
MARK = re.compile(r"^0x[0-9A-F]{8} = (?:<[^>\n]*>)*\[[0-9A-F]{4,8}\] ")


def build():
    os.makedirs(OUT, exist_ok=True)
    cmd = [sys.executable, os.path.join(SRC, "tools", "pack", "compile_pack.py"),
           "--lang", "de", "--out", OUT, "--strict", "--no-fonts", "--marks"]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip())
    if r.returncode != 0:
        raise SystemExit("标记包编译失败（退出码 %d）" % r.returncode)
    verify(os.path.join(OUT, "de.txt"))
    return os.path.join(OUT, "de.txt")


def verify(path):
    lines = io.open(path, encoding="utf-8").read().split("\n")
    total = marked = 0
    for l in lines:
        if not l.startswith("0x"):
            continue
        total += 1
        if MARK.match(l):
            marked += 1
    print("校验 %s：条目 %d、带标记 %d、未加标记 %d" % (os.path.basename(path), total, marked, total - marked))
    if marked != total:
        raise SystemExit("有 %d 条没加上标记" % (total - marked))
    sha = hashlib.sha1(io.open(path, "rb").read()).hexdigest()[:12]
    print("标记包 sha1 %s，%d 字节" % (sha, os.path.getsize(path)))


def normal_pack():
    """正常包：临时编到 build/debug/de-normal，避免动运行时目录。"""
    norm = os.path.join(ROOT, "build", "debug", "de-normal")
    os.makedirs(norm, exist_ok=True)
    subprocess.run([sys.executable, os.path.join(SRC, "tools", "pack", "compile_pack.py"),
                    "--lang", "de", "--out", norm, "--strict", "--no-fonts"],
                   cwd=ROOT, check=True)
    p = os.path.join(norm, "de.txt")
    lines = io.open(p, encoding="utf-8").read().split("\n")
    bad = [l[:40] for l in lines if l.startswith("0x") and MARK.match(l)]
    print("正常包检查：含标记 %d 条（应为 0）" % len(bad))
    if bad:
        raise SystemExit("正常包出现标记：%s" % bad[:3])
    return p


def install(marked=None):
    marked = marked or os.path.join(OUT, "de.txt")
    live = os.path.join(PACKS, "de.txt")
    if os.path.exists(live) and not os.path.exists(BACKUP):
        shutil.copy2(live, BACKUP)
        print("已备份正常包 → %s（%d 字节）" % (BACKUP, os.path.getsize(BACKUP)))
    shutil.copy2(marked, live)
    print("已装入排查包 → %s（%d 字节）" % (live, os.path.getsize(live)))


def restore():
    live = os.path.join(PACKS, "de.txt")
    if os.path.exists(BACKUP):
        shutil.copy2(BACKUP, live)
        print("已还原正常包 → %s（%d 字节）" % (live, os.path.getsize(live)))
        return
    p = normal_pack()
    shutil.copy2(p, live)
    print("备份不存在，已用现编正常包还原 → %s" % live)


def main():
    if "--build" in sys.argv:
        build()
    elif "--install" in sys.argv:
        if not os.path.exists(os.path.join(OUT, "de.txt")):
            build()
        install()
    elif "--restore" in sys.argv:
        restore()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
