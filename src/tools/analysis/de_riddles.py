#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重译藏宝诗谜：英文原句是押韵的，德语此前按散文直译，这里改回押韵短句，
方位与"X"位置等信息一律照旧。"""
import io
import tomllib

PATH = r"C:\Users\mrche\WorkBuddy\2026-10-15-23-47-12\Port Royale 2 Localization\src\translations\de.toml"

NEW = {
    # 神殿遗迹，X 在上方角落，往东南白跑
    "0x35f48fe4": "Es lebten hier Menschen vor langer Zeit, "
                  "in Tempeln, den Göttern zum Lob bereit. "
                  "Darüber liegt X, ganz oben im Eck. "
                  "Nach Südosten zu segeln, das hat keinen Zweck.",
    # 同上，往西南白跑
    "0x35f48fe5": "Es lebten hier Menschen vor langer Zeit, "
                  "in Tempeln, den Göttern zum Lob bereit. "
                  "Darüber liegt X, ganz oben im Eck. "
                  "Nach Südwesten zu segeln, das hat keinen Zweck.",
    # X 到 Nombre 不远，有酒有雪茄
    "0x35f48fe6": "Von X nach Nombre ist's nicht weit, "
                  "Rum ist genug an Bord und für eine Zigarre ist Zeit.",
    # 北边悬崖失足，到 X 就好了
    "0x35f4904e": "Stürzt Ihr im Norden die Klippen hinunter, "
                  "seid Ihr in X bald wieder munter.",
    # 岛上有个很小的城，东南方那个最大
    "0x35f49050": "X liegt auf der Insel, die winzig und klein, "
                  "im Südosten liegt die größte — die muss es sein.",
    "0x35f490bf": "X liegt auf der Insel, die winzig und klein, "
                  "im Südosten liegt die größte — die muss es sein.",
    # 大湾里三座城，X 是最西/最南/最东那座
    "0x35f49052": "In einer großen Bucht liegen Städte, drei; "
                  "die westlichste trägt das X — nur die, nicht zwei.",
    "0x35f490c1": "In einer großen Bucht liegen Städte, drei; "
                  "die westlichste trägt das X — nur die, nicht zwei.",
    "0x35f490c2": "In einer großen Bucht liegen Städte, drei; "
                  "die westlichste trägt das X — nur die, nicht zwei.",
    "0x35f49130": "In einer großen Bucht liegen Städte, drei; "
                  "die westlichste trägt das X — nur die, nicht zwei.",
    "0x35f49053": "In einer großen Bucht liegen Städte, drei; "
                  "die südlichste trägt das X — nur die, nicht zwei.",
    "0x35f49131": "In einer großen Bucht liegen Städte, drei; "
                  "die östlichste trägt das X — nur die, nicht zwei.",
    # 湾里两座岛，大的那座上的城是 X
    "0x35f49054": "In einer Bucht zwei Inseln liegen, groß und klein, "
                  "die Stadt auf der großen trägt X — so soll es sein.",
    # 远海孤岛，只能是 X
    "0x35f49055": "Eine Insel weit draußen, klein und allein, "
                  "sonst gibt es nichts, das könnte X sein.",
    # 街道铺金、港口气派
    "0x35f49056": "X ist die Stadt mit den Straßen aus Gold, "
                  "ihr Hafen ist prächtig, ein Anblick so hold.",
    # 从西边过桥，再走一点就是 X
    "0x35f49134": "Ihr kommt aus dem Westen und über die Brücke, "
                  "zur Stadt mit dem X ist's nur noch ein Stücke.",
    # 湾中福地，悬崖环护
    "0x35f49135": "Was für ein wunderbarer Ort, so fein, "
                  "in einer Bucht gelegen, ganz allein, "
                  "von hohen Klippen fest behütet und bewacht — "
                  "ja, X ist es, wer hätt's gedacht.",
    # 大河向东入沼泽，再往东南过一段陆路
    "0x35f49137": "Ein mächtiger Fluss zieht tief seine Bahn "
                  "nach Osten, in Sumpf und Morast hinein — dann "
                  "von dort nach Südosten, ein Stück über Land, "
                  "zur Stadt mit dem X, ganz außen am Rand.",
}

doc = tomllib.load(open(PATH, "rb"))
lines = io.open(PATH, encoding="utf-8", newline="\n").read().split("\n")

hit = 0
for i, line in enumerate(lines):
    if not line.startswith('"'):
        continue
    key = line.split('"')[1]
    if key not in NEW:
        continue
    if not line.endswith('"'):
        raise SystemExit("不是单行字符串，需人工处理：%s" % key)
    lines[i] = '"%s" = "%s"' % (key, NEW[key])
    hit += 1

io.open(PATH, "w", encoding="utf-8", newline="\n").write("\n".join(lines))

doc2 = tomllib.load(open(PATH, "rb"))
bad = [k for k, v in NEW.items() if doc2[k] != v]
old = [k for k in NEW if doc[k] != NEW[k]]
print("命中 %d/%d；实际变更 %d 条；未写入 %s" % (hit, len(NEW), len(old), bad or "无"))
