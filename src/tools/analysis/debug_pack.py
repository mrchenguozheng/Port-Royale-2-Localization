#!/usr/bin/env python
# coding: utf-8
"""生成一个可以单独选中的排查语言包 <lang>-debug.txt。

    python src/tools/analysis/debug_pack.py --lang de
    python src/tools/analysis/debug_pack.py --lang zh     # 中文界面，边玩边记键

产物：build\\debug\\<lang>-debug\\<lang>-debug.txt
用法：复制到 PR2Localization\\packs\\ 下，启动器语言列表里会多出一项
"<原名> (Debug)"，选它进游戏即可；正式的 <lang>.txt 一个字都不用动，
排查完在列表里选回原语言，或者直接删掉这个文件。

每条正文前缀一个标记 `[XXXX]`，取 id 尾数（逐条取能区分自己的最短尾数，
德语 3548 条实测 4~8 位全唯一）。标记插在行首标签之后，
不影响 <ts:>/<f:fonts/> 与占位。

非拉丁语言（zh/ja/ru）需要字体映射：脚本会把 font-map.default.ini 里
[<lang>] 的四条映射复制成 [<lang>-debug] 写进 font-map.ini（用户级覆盖文件），
否则该代码没有自己的段，运行时回退到游戏原版字体，汉字会画不出来。

限制：每条长 4~7 个字符，短标签会被挤到溢出或换行，只适合排查，不适合游玩；
同文条目（de_index 里的 dup 簇）在画面上仍是同一句，只能记到簇一级。
"""

import glob
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(SRC)
GAME = r"C:\Program Files (x86)\GOG Galaxy\Games\Port Royale 2"
MARK = re.compile(r"^0x[0-9A-F]{8} = (?:<[^>\n]*>)*\[[0-9A-F]{4,8}\] ")
MARK_ANY = re.compile(r"^0x([0-9A-F]{8}) = ((?:<[^>\n]*>)*)\[([0-9A-F]{3,8})\] ?")
MAP_DIR = os.path.join(ROOT, "docs", "界面映射")
MAP_DOC = os.path.join(ROOT, "docs", "界面映射.md")   # 拆卷前的单文件，只作兼容
CLEARED_DATA = os.path.join(SRC, "data", "ui_mapping", "cleared.txt")


def map_sources(target=None):
    """返回作为“已查清清单”的源文件列表。

    默认只读 `src/data/ui_mapping/cleared.txt`：文档里的批次日志不再参与运行。
    传目录 → 该目录下全部 *.md；传文件 → 只有它（排查旧文档时用）。
    数据文件不存在时退回旧行为：`docs/界面映射/` 下全部 *.md 加旧单文件。
    """
    if target is None:
        if os.path.isfile(CLEARED_DATA):
            return [CLEARED_DATA]
        out = []
        if os.path.isdir(MAP_DIR):
            out += sorted(glob.glob(os.path.join(MAP_DIR, "*.md")))
        if os.path.isfile(MAP_DOC):
            out.append(MAP_DOC)
        return out
    if os.path.isdir(target):
        return sorted(glob.glob(os.path.join(target, "*.md")))
    return [target] if os.path.isfile(target) else []


def load_cleared(sources):
    """从数据文件或界面映射分卷里取已实机确认的键，支持三类写法。

    1. 逐条：同一行既有 `[XXXX]` 又有 0x 键 —— 这一条已确认；
    2. 整段：`- 整体清除：`0xfc51xxxx`（名表）` —— 该前缀下全部视为已确认（类别级）；
    3. 例外：`- 整体保留：`0xfc512ea5`` —— 即使落在已清除的整段里也保留标记。
    数据文件 `src/data/ui_mapping/cleared.txt` 是唯一来源；文档里的批次日志只作证据。
    推断行（标记列写 —）不算确认。
    """
    if not sources:
        print("清除：找不到已确认键数据，全部保留标记")
        return {}, [], set()
    cleared, prefixes, keep = {}, [], set()
    for path in sources:
        for line in io.open(path, encoding="utf-8"):
            line = line.rstrip("\n")
            if "整体保留：" in line:
                for kk in re.findall(r"0x([0-9a-fA-F]{8})", line):
                    keep.add("0x" + kk.upper())
                continue
            if "整体清除：" in line:
                for pp in re.findall(r"0x([0-9a-fA-F]{4})xxxx", line):
                    prefixes.append("0x" + pp.upper())
                continue
            mk = re.search(r"\[([0-9A-F]{3,8})\]", line)
            kk = re.search(r"0x([0-9a-fA-F]{8})", line)
            if mk and kk:
                cleared["0x" + kk.group(1).upper()] = mk.group(1)
    return cleared, prefixes, keep


def pack_meta(lang):
    p = os.path.join(SRC, "packs", lang + ".toml")
    if not os.path.isfile(p):
        return "", 1
    text = io.open(p, encoding="utf-8").read()
    alias = ""
    for line in text.split("\n"):
        m = re.match(r'\s*alias\s*=\s*"(.*)"', line)
        if m:
            alias = m.group(1)
    return alias, 1


def ensure_fonts(lang, code):
    """把 [lang] 的字体映射复制成 [code]，写进用户级 font-map.ini。"""
    fonts = os.path.join(GAME, "PR2Localization", "fonts")
    default = os.path.join(fonts, "font-map.default.ini")
    user = os.path.join(fonts, "font-map.ini")
    if not os.path.isfile(default):
        print("字体：找不到 %s，跳过" % default)
        return
    text = io.open(default, encoding="utf-8").read()
    block, cur = [], ""
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1].strip().lower()
            continue
        if cur == lang and s and not s.startswith(";"):
            block.append(s)
    if not block or all("=none" in b.replace(" ", "").lower() for b in block):
        print("字体：%s 用原版字体即可，不需要映射" % code)
        return
    existing = io.open(user, encoding="utf-8").read() if os.path.isfile(user) else ""
    if re.search(r"^\[%s\]" % re.escape(code), existing, re.M):
        print("字体：font-map.ini 已有 [%s] 段，未改动" % code)
        return
    head = "" if existing else (
        "; 排查包专用：给 <语言>-debug 代码补字体映射，正式语言包不读这里。\n"
        "; 由 src/tools/analysis/debug_pack.py 生成，删掉本文件即回到默认。\n")
    add = head + "\n[%s]\n" % code + "".join("  " + b + "\n" for b in block)
    body = (existing.rstrip("\n") + "\n" + add) if existing else add
    io.open(user, "w", encoding="utf-8", newline="\n").write(body)
    print("字体：已写 %s 的 [%s] 段（%d 条映射）" % (os.path.basename(user), code, len(block)))


def build(lang, sources=None):
    alias, _ = pack_meta(lang)
    code = lang + "-debug"
    out = os.path.join(ROOT, "build", "debug", code)
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, lang + ".txt")
    r = subprocess.run([sys.executable, os.path.join(SRC, "tools", "pack", "compile_pack.py"),
                        "--lang", lang, "--out", out, "--strict", "--no-fonts", "--marks"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    print(((r.stdout or "") + (r.stderr or "")).rstrip())
    if r.returncode != 0:
        raise SystemExit("编译失败（退出码 %d）" % r.returncode)

    lines = io.open(tmp, encoding="utf-8").read().split("\n")
    headline = "# pack-meta alias=%s (Debug)" % (alias or lang)
    out_lines, done = [], False
    for l in lines:
        if l.startswith("# pack-meta alias=") and not done:
            out_lines.append(headline)
            done = True
            continue
        out_lines.append(l)
    if not done:
        out_lines.insert(0, headline)

    # 已实机确认的条目按界面映射清单去掉标记，剩下的继续带标记
    sources = map_sources() if sources is None else sources
    cleared, prefixes, keep = load_cleared(sources)

    def drop(key):
        if key in keep:
            return False
        if key in cleared:
            return True
        return any(key.startswith(p) for p in prefixes)

    present, stripped = set(), []
    unmarked_before = 0
    for l in out_lines:
        m = MARK_ANY.match(l)
        if not m:
            if l.startswith("0x"):
                unmarked_before += 1
            continue
        key = "0x" + m.group(1)
        present.add(key)
        if drop(key):
            stripped.append(key)
    missing = sorted(set(cleared) - present)
    if missing:
        print("清除：清单里有 %d 条键不在本包内，已跳过：%s" % (len(missing), ", ".join(missing)))
    if stripped:
        new = []
        for l in out_lines:
            m = MARK_ANY.match(l)
            if m and drop("0x" + m.group(1)):
                new.append("0x%s = %s%s" % (m.group(1), m.group(2), l[m.end():]))
            else:
                new.append(l)
        out_lines = new
    path = os.path.join(out, code + ".txt")
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(out_lines))

    total = sum(1 for l in out_lines if l.startswith("0x"))
    marked = sum(1 for l in out_lines if MARK.match(l))
    print("产物 %s：条目 %d、带标记 %d、按已确认键数据（%d 份清单）去掉标记 %d 条"
          "（其中原本无标记 %d 条）、%d 字节"
          % (path, total, marked, len(sources), len(stripped), unmarked_before,
             os.path.getsize(path)))
    if marked + len(stripped) + unmarked_before != total:
        raise SystemExit("计数不符：带标记 %d + 已去标记 %d + 原本无标记 %d ≠ 条目 %d"
                         % (marked, len(stripped), unmarked_before, total))
    audit = os.path.join(out, "cleared.txt")
    io.open(audit, "w", encoding="utf-8", newline="\n").write(
        "\n".join(sorted(stripped)) + "\n")
    print("已去标记的键清单：%s（%d 条）" % (audit, len(stripped)))
    ensure_fonts(lang, code)
    print("复制到 PR2Localization\\packs\\ 后，列表里会多出 \"%s (Debug)\"（代码 %s）"
          % (alias or lang, code))
    return path


def main():
    lang = "de"
    if "--lang" in sys.argv:
        lang = sys.argv[sys.argv.index("--lang") + 1]
    sources = None                      # None = src/data/ui_mapping/cleared.txt
    if "--no-clear" in sys.argv:
        sources = []                    # 空列表 = 一份清单都不读，全部保留标记
    if "--clear-map" in sys.argv:
        sources = map_sources(os.path.abspath(sys.argv[sys.argv.index("--clear-map") + 1]))
    build(lang, sources)


if __name__ == "__main__":
    main()
