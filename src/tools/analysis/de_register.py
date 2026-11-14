#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口语语体回补：把对话、酒馆、海盗场景里被压平成书信体的句子改回口语。
叙事、百科、任务说明不动（那部分中性语体是对的）。敬称仍用 Ihr/Euch。"""
import io
import tomllib

PATH = r"C:\Users\mrche\WorkBuddy\2026-10-15-23-47-12\Port Royale 2 Localization\src\translations\de.toml"

# (key, 旧片段, 新片段) —— 片段必须唯一且真实存在，脚本会逐条断言
PAIRS = [
    # 醉汉偷船
    ("0x273267f2", "ich kann es nicht glauben", "ich kann's noch gar nicht fassen"),
    ("0x273267f2", "Trunkenbolde haben mein schönes Schiff gestohlen",
     "Da haben mir Trunkenbolde doch glatt mein schönes Schiff geklaut"),
    ("0x273267f2", "Sie haben es mit Flaschen Rum beladen und sind davongefahren",
     "Sie haben es mit Flaschen voll Rum beladen und sind damit abgehauen"),
    # 儿子借船
    ("0x273267f3", "Mein leichtsinniger Sohn Boris", "Mein nichtsnutziger Sohn Boris"),
    ("0x273267f3", "hat mein feinstes Schiff ausgeliehen", "hat sich mein schönstes Schiff ausgeliehen"),
    ("0x273267f3", "beschlossen haben, einen Ausflug zu unternehmen",
     "beschlossen haben, einen Ausflug zu machen"),
    ("0x273267f3", "Zweifellos haben sie den Laderaum mit Rum gefüllt",
     "Sicher haben sie den Laderaum mit Rum vollgepackt"),
    ("0x273267f3", "ich werde mein Schiff nie wiedersehen", "ich werde mein Schiff wohl nie wiedersehen"),
    # 找醉汉（两版）
    ("0x08d9e61b", "Vielleicht findet Ihr Hinweise auf den Aufenthaltsort der Trunkenbolde.",
     "Vielleicht findet Ihr einen Hinweis, wo sich die Trunkenbolde verkrochen haben."),
    ("0x08d9e61c", "Ihr seid wahrlich großzügig.", "Wie großzügig Ihr doch seid!"),
    ("0x08d9e61c", "vielleicht findet Ihr Hinweise darauf, wo sich die Trunkenbolde versammeln",
     "vielleicht findet Ihr einen Hinweis, wo die Trunkenbolde ihr Saufgelage abhalten"),
    # 醉鬼讨酒
    ("0xd9942741", "Ihr habt mir all mein Geld abgenommen", "Ihr habt mir mein ganzes Gold abgenommen"),
    ("0xd9942741", "Bestellt mir eine Flasche Rum", "Bestellt mir noch eine Buddel Rum"),
    # 藏宝提示
    ("0x1269b779", "ich habe hier einen Hinweis", "ich hab hier einen Hinweis"),
    ("0x166c0814", "nur um etwas Gesellschaft zu haben", "nur damit ich mal etwas Gesellschaft habe"),
    # 招呼
    ("0xd4b8ac64", "Kommt Ihr nicht herüber?", "Kommt doch mal her zu mir!"),
    # 狗被扔下船
    ("0x3657dd23", "Ihr meint, Ihr habt den Hund über Bord geworfen?",
     "Ihr habt den Hund tatsächlich über Bord geworfen?"),
    ("0x3657dd23", "Ich bin Euch trotzdem sehr dankbar.", "Ich danke Euch trotzdem."),
    ("0x3657dd23", "doch ich habe einst einen Schatz an einem geheimen Ort versteckt. Hier ist eine Karte.",
     "aber ich habe einst einen Schatz an einem geheimen Ort versteckt. Hier, die Karte."),
    # 酒馆闲谈（情报员）
    ("0xd3ac64cc", "Ihr handelt gewiss auch mit Rum? Ich kann Euch etwas darüber erzählen.",
     "Ihr handelt doch sicher auch mit Rum? Dazu kann ich Euch was erzählen."),
    ("0xd3ac63eb", "Seid Ihr schon einmal dem Begriff „Schuldknechtschaft“ begegnet? Ich könnte Euch etwas darüber erzählen.",
     "Habt Ihr schon mal vom Begriff „Schuldknechtschaft“ gehört? Ich könnte Euch was dazu erzählen."),
    ("0xd3ac64cd", "Ich erzähle Euch ein wenig über Jamaika, die Insel, auf der die Stadt Port Royale liegt.",
     "Ich erzähl Euch mal was über Jamaika — die Insel, auf der Port Royale liegt."),
    ("0xd3ac6460", "Habt Ihr schon die Bermudainseln im fernen Nordosten besucht? Ich kann Euch etwas über sie erzählen.",
     "Wart Ihr schon mal bei den Bermudainseln, ganz im Nordosten? Ich kann Euch was darüber erzählen."),
    ("0xd3ac645e", "Gewiss seid Ihr schon einem Bukanier begegnet oder habt bereits einen Kaperbrief angenommen?",
     "Ihr seid doch sicher schon einem Bukanier begegnet oder habt schon einen Kaperbrief angenommen?"),
    ("0xd3ac64ca", "Woher hat Amerika seinen Namen? Ich kann Euch die Antwort geben.",
     "Warum heißt Amerika eigentlich „Amerika“? Ich kann es Euch erzählen."),
    ("0xd3ac64d1", "aber es gibt auch Piratinnen!", "— es gibt auch Piratinnen!"),
    # 总督之女
    ("0xe8d7e960", "und mein Herz sehnt sich danach, dass Ihr allein mein seid.",
     "und mein Herz wünscht sich nichts mehr, als dass Ihr ganz allein mir gehört."),
    ("0xe8d7e960", "Wollt Ihr meinen Vater nicht um meine Hand bitten?",
     "Wollt Ihr nicht bei meinem Vater um meine Hand anhalten?"),
    # 收购商
    ("0xeeced82f", "Ich möchte den Mangel an @G$Goods$ dort ausnutzen.",
     "Ich will den Mangel an @G$Goods$ dort ausnutzen."),
    ("0xeeced82f", "Ich biete an, so viele Waren zu kaufen, wie Ihr liefern könnt, und zahle Euch einen sehr guten Preis pro Fass, sagen wir @g$FullPrice$.",
     "Ich kaufe Euch so viele Waren ab, wie Ihr liefern könnt, und zahle einen sehr guten Preis pro Fass — sagen wir @g$FullPrice$."),
    # 报价
    ("0xff8d2f24", "Ich bin bereit, die Summe von @g$TotalPrice$ zu zahlen, was einem Stückpreis von @g$Price$ entspräche.",
     "Ich würde Euch @g$TotalPrice$ dafür zahlen — das wäre ein Stückpreis von @g$Price$."),
    ("0x0076d778", "Ich würde sie gern zu einem Stückpreis von @g$Price$ loswerden. Habt Ihr Interesse?",
     "Ich würde sie gern loswerden, zum Stückpreis von @g$Price$. Na, wie sieht's aus?"),
    # 总督委托口吻
    ("0xcdf0b227", "Eine Anzahl Händler hat sich zusammengeschlossen und verlangt besseren Schutz in unseren Gewässern.",
     "Ein paar Händler haben sich zusammengetan und verlangen besseren Schutz in unseren Gewässern."),
    ("0xcdf0b228", "weil sich das Gerücht verbreitet hat, eine Seuche habe die Stadt erfasst",
     "weil das Gerücht umgeht, eine Seuche habe die Stadt erwischt"),
    ("0xca4930dc", "Wie wäre es, Ihr zahlt mir eine Sicherheit", "Wie wär's, Ihr zahlt mir eine Sicherheit"),
    ("0xca6f7276", "Seid Ihr dieser Aufgabe gewachsen?", "Traut Ihr Euch das zu?"),
]

doc = tomllib.load(open(PATH, "rb"))
for rid, old, _new in PAIRS:
    if old not in doc.get(rid, ""):
        raise SystemExit("命中失败：%s 里没有 %r" % (rid, old))

lines = io.open(PATH, encoding="utf-8", newline="\n").read().split("\n")
count = {}
for i, line in enumerate(lines):
    if not line.startswith('"'):
        continue
    key = line.split('"')[1]
    rel = [(o, n) for k, o, n in PAIRS if k == key]
    if not rel:
        continue
    for old, new in rel:
        if old not in line:
            raise SystemExit("行内未命中：%s" % key)
        line = line.replace(old, new, 1)
    lines[i] = line
    count[key] = len(rel)

io.open(PATH, "w", encoding="utf-8", newline="\n").write("\n".join(lines))

doc2 = tomllib.load(open(PATH, "rb"))
touched = sum(1 for k in doc if doc2.get(k) != doc.get(k))
print("条目 %d 条、片段 %d 处；实际改动 %d 条" % (len(count), len(PAIRS), touched))
