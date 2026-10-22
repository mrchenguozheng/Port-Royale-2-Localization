#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_strings.py —— 从游戏的 PR2.exe 里提取字符串表，写成 toml。

为什么需要
----------
`src\\references\\` 里的英文/法文原文不是抄来的，是从各自版本
的 exe 里解出来的。换游戏版本（或想对照别的语言版本）时用这个脚本重提一次，
拿到的是**原样**的表：`<n>` 换行、占位符、行尾空格都保持游戏里的样子。

原理（实测）
------------
字符串表在 PE 资源 `BINARY/167`（约 700 KB），按 16 位字解码：

    dst[0] = src[0] ^ 0x45AD
    dst[i] = src[i-1] ^ src[i]

解出来是：`u32 条数` + 每条 `{u32 hash, u32 偏移, u32 flags, u32 长度}`
+ 一张 UTF-16 文本池（文本从 `4 + 偏移` 开始，长度按 UTF-16 字符数算）。

用法
----
    python src\\tools\\extract_strings.py --exe "<游戏目录>\\PR2.exe" \\
        --out src\\references\\en.gog_1.1.2.3.toml
"""
import argparse
import io
import os
import struct
import sys


def read_table(exe):
    d = open(exe, "rb").read()
    e = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, e + 6)[0]
    opt = e + 24
    dd = opt + (96 if struct.unpack_from("<H", d, opt)[0] == 0x10b else 112)
    rsrc_rva, _ = struct.unpack_from("<II", d, dd + 16)

    secs = []
    so = opt + struct.unpack_from("<H", d, e + 20)[0]
    for i in range(nsec):
        o = so + 40 * i
        vsz, va, rsz, ra = struct.unpack_from("<IIII", d, o + 8)
        secs.append((va, max(vsz, rsz), ra))

    def rva2off(r):
        for va, size, ra in secs:
            if va <= r < va + size:
                return ra + (r - va)
        raise SystemExit("RVA 0x%x 不在任何节里" % r)

    base = rva2off(rsrc_rva)

    def walk(off):
        n = struct.unpack_from("<H", d, base + off + 12)[0]
        m = struct.unpack_from("<H", d, base + off + 14)[0]
        for i in range(n + m):
            _nm, do = struct.unpack_from("<II", d, base + off + 16 + 8 * i)
            do2 = do & 0x7FFFFFFF
            if do & 0x80000000:
                yield from walk(do2)
            else:
                rva, size, _cp = struct.unpack_from("<III", d, base + do2)
                yield rva, size

    # 候选资源里挑「解出来条数合理」的那个：exe 里还有一个更大的资源，
    # 但它不是字符串表（解出来的条数是天文数字）。
    def decode(rva, size):
        raw = d[rva2off(rva):rva2off(rva) + size]
        w = struct.unpack_from("<%dH" % (len(raw) // 2), raw, 0)
        dec = [0] * len(w)
        dec[0] = w[0] ^ 0x45AD
        for i in range(1, len(w)):
            dec[i] = (w[i - 1] ^ w[i]) & 0xFFFF
        return dec

    picked = None
    for rva, size in sorted(walk(0), key=lambda t: -t[1]):
        if size < 400000 or size > 4000000:
            continue
        dec = decode(rva, size)
        cnt = dec[0] | (dec[1] << 16)
        if 100 <= cnt <= 20000:
            picked = (rva, size, dec, cnt)
            break
    if picked is None:
        raise SystemExit("没找到像字符串表的资源")
    rva, size, dec, cnt = picked
    out = []
    for i in range(cnt):
        q = 2 + 8 * i
        h = dec[q] | (dec[q + 1] << 16)
        off = dec[q + 2] | (dec[q + 3] << 16)
        ln = dec[q + 6] | (dec[q + 7] << 16)
        text = "".join(chr(c) for c in dec[(4 + off) // 2:(4 + off + ln) // 2])
        out.append((h, text))
    return out, size


def esc(s):
    o = []
    for ch in s:
        if ch == "\\":
            o.append("\\\\")
        elif ch == '"':
            o.append('\\"')
        elif ch == "\n":
            o.append("\\n")
        elif ch == "\r":
            o.append("\\r")
        elif ch == "\t":
            o.append("\\t")
        elif ord(ch) < 0x20:
            o.append("\\u%04X" % ord(ch))
        else:
            o.append(ch)
    return "".join(o)


def main():
    ap = argparse.ArgumentParser(description="从 PR2.exe 提取字符串表")
    ap.add_argument("--exe", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sorted", action="store_true", help="按 hash 升序输出（默认保持表内顺序）")
    a = ap.parse_args()

    rows, size = read_table(a.exe)
    if a.sorted:
        rows.sort(key=lambda r: r[0])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    io.open(a.out, "w", encoding="utf-8", newline="\n").write(
        "\n".join('"0x%08x" = "%s"' % (h, esc(t)) for h, t in rows) + "\n")
    print("从 %s 提取 %d 条（资源 %d 字节）→ %s" % (a.exe, len(rows), size, a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
