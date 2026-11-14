#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经济档位口径：把唯一那个非德语习惯的档位名换成零售版的 Blütezeit，
并把引用了它的任务文本、以及“状态下降”的动词一起改成德语惯用说法。"""
import io
import tomllib

PATH = r"C:\Users\mrche\WorkBuddy\2026-10-15-23-47-12\Port Royale 2 Localization\src\translations\de.toml"

FRAG = [
    ("0xd2d0a577", "Blühende Wirtschaft", "Blütezeit"),
    ("0xdbec5c5c",
     "Der Zustand der Stadt darf nicht unter „blühende Wirtschaft“ fallen.",
     "Der Status der Stadt darf nicht unter „Blütezeit“ fallen."),
    ("0xf4024494", "„Blühende Wirtschaft“", "„Blütezeit“"),
    ("0xf8e13933", "„Blühende Wirtschaft“", "„Blütezeit“"),
    ("0xf8e13933", "müssen mit voller Kapazität arbeiten", "müssen voll ausgelastet sein"),
    ("0x007c2733", "„Blühende Wirtschaft“", "„Blütezeit“"),
    ("0x3ad7e095",
     "Der Zustand der Stadt @T$TOWN$ ist unter „blühende Wirtschaft“ gefallen.",
     "Der Status der Stadt @T$TOWN$ ist unter „Blütezeit“ gesunken."),
    ("0xf4e195bf", "„Blühende Wirtschaft“", "„Blütezeit“"),
    ("0xf4e195bf", "Das ist nur ein vorübergehender Trick.", "Das ist nur eine vorübergehende Taktik."),
    ("0xf4e195bf", "die Händler zu terrorisieren, die @T$TOWN$ besuchen",
     "die Händler einzuschüchtern, die @T$TOWN$ anlaufen"),
    ("0x08e78a8c", "auf „Rezession“ fällt", "auf „Rezession“ sinkt"),
    ("0xdf6a59b0",
     "Viele der Truppen der Stadt wurden getötet, und der Status der Stadt ist gefallen.",
     "Zahlreiche Truppen der Stadt wurden getötet, und der Status der Stadt ist gesunken."),
    ("0xeee3380a",
     "Viele der Truppen der Stadt wurden getötet, und der Status der Stadt ist gefallen.",
     "Zahlreiche Truppen der Stadt wurden getötet, und der Status der Stadt ist gesunken."),
    ("0xef77d11d", "Auch der Status der Stadt ist gefallen.",
     "Auch der Status der Stadt ist gesunken."),
]

FULL = {
"0xf8b3a303": "Der Status einer Stadt durchläuft sieben Stufen – von der Armut bis zum Reichtum. In den beiden untersten Stufen ist die Lebensqualität so schlecht, dass die Bürger der Stadt regelmäßig den Rücken kehren. Erreicht eine Stadt dagegen die Stufen „Blütezeit“, „Wohlstand“ und „Reichtum“, bringen Eure Betriebe einen Effizienzbonus, und Eure Arbeitskräfte arbeiten kostengünstiger. In der höchsten Stufe bringt eine Stadt sogar von selbst Siedler hervor.<n><n>Welche Wirkung die einzelnen Stufen haben, lest Ihr in den Stadtinformationen nach; sie öffnen sich per Klick auf den Stadtnamen.<n><n> Eine ausreichende Versorgung mit zwei bis drei Waren aus jeder Warengruppe sichert eine gute Lebensqualität in Eurer Stadt. Ausreichend heißt: Der Vorrat einer Ware reicht zehn Tage für die Bevölkerung der Stadt.<n><n>Übrigens: Der Status einer Stadt bessert sich nicht über Nacht. Es dauert eine Weile, bis sich die Bürger auf die neue Lage eingestellt haben."
}

old = tomllib.load(open(PATH, "rb"))
for k, a, b in FRAG:
    if a not in old[k]:
        raise SystemExit("片段未命中：%s / %r" % (k, a))
for k in FULL:
    if k not in old:
        raise SystemExit("无此键：%s" % k)

lines = io.open(PATH, encoding="utf-8", newline="\n").read().split("\n")
todo = {}
for k, a, b in FRAG:
    todo.setdefault(k, []).append((a, b))
done = set()
for i, line in enumerate(lines):
    if not line.startswith('"'):
        continue
    key = line.split('"')[1]
    if key in FULL:
        lines[i] = '"%s" = "%s"' % (key, FULL[key].replace("\\", "\\\\").replace('"', '\\"'))
        done.add(key)
        continue
    if key not in todo:
        continue
    for a, b in todo[key]:
        line = line.replace(a, b)
    lines[i] = line
    done.add(key)

io.open(PATH, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
chk = tomllib.load(open(PATH, "rb"))
print("改动 %d 条；键集合一致 %s" % (len(done), set(chk) == set(old)))
print("剩余 Blühende Wirtschaft：", sum(1 for v in chk.values() if "Blühende Wirtschaft" in v))
print("Blütezeit 出现条数：", sum(1 for v in chk.values() if "Blütezeit" in v))
