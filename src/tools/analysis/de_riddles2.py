#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诗谜二轮打磨：把上一轮凑韵凑坏或干脆没韵的几条按零售版节奏重写，
并修两处把“城市”写成“你们”的语法错。"""
import io
import re
import tomllib

PATH = r"C:\Users\mrche\WorkBuddy\2026-10-15-23-47-12\Port Royale 2 Localization\src\translations\de.toml"

FULL = {
# 荒城（三份同文）
"0x35f48f6c": "Die Stadt, die Ihr sucht, ist fern und allein, verlassen und öde – dort kehrt niemand ein. Verbannt und vergessen, von aller Welt fort, so wartet sie stumm, ein einsamer Ort.",
"0x35f48f74": "Die Stadt, die Ihr sucht, ist fern und allein, verlassen und öde – dort kehrt niemand ein. Verbannt und vergessen, von aller Welt fort, so wartet sie stumm, ein einsamer Ort.",
"0x35f48f75": "Die Stadt, die Ihr sucht, ist fern und allein, verlassen und öde – dort kehrt niemand ein. Verbannt und vergessen, von aller Welt fort, so wartet sie stumm, ein einsamer Ort.",
# Sankt August 向北（三份同文）
"0x35f48f70": "Sankt August zieht gen Norden hin, bald sitzt er in der Stadt drin.",
"0x35f48f72": "Sankt August zieht gen Norden hin, bald sitzt er in der Stadt drin.",
"0x35f48f73": "Sankt August zieht gen Norden hin, bald sitzt er in der Stadt drin.",
# 三岛有绳
"0x35f4904f": "Drei kleine Inseln umschließen dies Gebiet, doch Seile gibt es nur auf einer – wie man sieht.",
# 岛链缺口
"0x35f49051": "Hier macht die Inselkette einen Knick. Im Westen liegen Inseln, im Süden auch. Im Norden ist nichts – nur Wasser und Rauch.",
# 湾中福地（原句凑韵堆成一句）
"0x35f49135": "Ein Ort wie aus dem Traum gemacht, in einer Bucht, von Klippen bewacht. So still und fern und ganz allein – hier soll es X, die Stadt, wohl sein.",
# 语法：城市被写成“你们”
"0x35f490c5": "Weißer Strand neben dem Dschungel, ein kleiner Fluss, den niemand kennt. Hier liegt sie gut verborgen, in einer Bucht, die nur die Sonne sieht.",
"0x35f490c6": "Hier liegt die Stadt und überblickt den Sund. Sie bewacht die Bucht, in der es von Schiffen wimmelt.",
"0x35f490c8": "Spanien errichtete hier einst einen Hafen. Ihr findet Holz und Ziegel, doch Weizen findet Ihr dort keinen.",
}

old = tomllib.load(open(PATH, "rb"))
for k, v in FULL.items():
    if k not in old:
        raise SystemExit("无此键：%s" % k)
    if sorted(re.findall(r"@[A-Za-z$]+[A-Za-z0-9_$]+@", old[k])) != sorted(
            re.findall(r"@[A-Za-z$]+[A-Za-z0-9_$]+@", v)):
        raise SystemExit("占位符不一致：%s" % k)

lines = io.open(PATH, encoding="utf-8", newline="\n").read().split("\n")
n = 0
for i, line in enumerate(lines):
    if not line.startswith('"'):
        continue
    key = line.split('"')[1]
    if key in FULL:
        lines[i] = '"%s" = "%s"' % (key, FULL[key].replace("\\", "\\\\").replace('"', '\\"'))
        n += 1
io.open(PATH, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
chk = tomllib.load(open(PATH, "rb"))
print("改写 %d 条；键集合一致 %s" % (n, set(chk) == set(old)))
