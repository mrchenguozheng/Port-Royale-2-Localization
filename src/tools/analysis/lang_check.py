#!/usr/bin/env python3
# coding: utf-8
"""lang_check.py — 外语形态层检查：语法、拼写、复合词拆分。

与 text_lint.py 的分工：
  text_lint   查「是否照着原文说对了」——模板、占位、标注、空值、同原文异译
  lang_check  查「这门语言写得对不对」——语法格位、拼写、德语复合词切分

判据都取自目标语言本身，不依赖中文，因此每种语言各跑一遍。
报告写到 build/qa/lang_check_<lang>.txt。

    python src/tools/analysis/lang_check.py --lang de
    python src/tools/analysis/lang_check.py --lang de --grammar-only
    python src/tools/analysis/lang_check.py --lang de --spell-only
"""

import argparse
import io
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TR = os.path.join(ROOT, "src", "translations", "%s.toml")

sys.path.insert(0, os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from text import toml_io  # noqa: E402
from text import marks as MK  # noqa: E402

#: LanguageTool 的语言码。6.8 的 /languages 列表里其实有 ja-JP 与 zh-CN，但实测：ja-JP
#: 对三条日语样本零命中（规则集近乎为空）；zh-CN 有 wa5／wb2／wb4 一类规则，三条样本三处
#: 命中全是误报（「一种叫作 xocoatl 的饮品」不含量词错、「以它的尺寸而言」本可搭配、
#: 「精细的装饰」是形容词修饰名词）。两门语言的 LT 结果都不能当判据，故不入表。
LT_CODE = {"de": "de-DE", "fr": "fr", "es": "es", "ru": "ru-RU", "nl": "nl", "pt": "pt-PT"}

#: 字母串：任何非 ASCII 标点、非数字、非中日韩的字母（法语重音、西语 ñ、俄语西里尔都靠它）
ANY_WORD = re.compile(r"[^\W\d_\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]{2,}")

#: 引擎占位与标签：送检前抹掉，免得 LanguageTool 把它们当单词或当句子成分读。
#: 抹成空白而不是下划线：下划线会把 `considération.<n><n>Les` 读成「句号紧跟字母」，
#: 反过来造出「此处应加空格」的假命中，遮蔽本身成了误报来源。
MASK = re.compile(r"%[0-9]+|@[a-zA-Z]\$[^$]*\$|<[^>]*>|\[[^\]]*\]")


def clean(text):
    """抹掉占位符与标签，把段落标记 <n> 还原成换行，收掉多余空白。

    拼写层与「这条值有没有可检内容」的判断用它；语法层用 render()。
    """
    s = str(text).replace("<n>", "\n")
    s = MASK.sub(" ", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


#: 界面与任务标识：整条只有大写字母、数字、下划线（`IDM_CONTEST_01_2004_LOG_01_HDR`、
#: `CAT`、`OK`）。这类串不是句子，送检只会被词典判未收录，显式跳过。
IDENT_RX = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)*(?:[.\-/][A-Z0-9]+)*$")


def ident_only(text):
    """整条是否只有一个标识串（界面键、任务编号、调试开关）。"""
    s = clean(text)
    return bool(s) and bool(IDENT_RX.match(s))


def checkable(text):
    """这条值要不要送检：空的跳过，整条只有标识串的也跳过。

    `Dummy`、`+++EMPTY+++` 这类测试残留同样不是句子，送检只会往拼写里记一笔。
    `scenario004 - @I$Idx$` 是编号行，占位抹掉后只剩「编号 + 连字符」，也跳过。
    """
    s = clean(text)
    if not s or IDENT_RX.match(s):
        return False
    if s.strip("+. ") in JUNK:
        return False
    return not re.fullmatch(r"[A-Za-z]*[0-9]+(?:\s*[-–:|.\s]+)*", s)


#: 固定种子：同一份文件两次体检拿到同一批替身，两次报告能逐行对照。
RENDER_SEED = 20261120

#: 重复词类规则：批内相邻两条会互相干扰（`nun` 在两条各出现一次就报重复），
#: 这类命中必须拿单条复检一遍才算数。
REPEAT_RX = re.compile(r"REPEATEDWORDS|WORD_REPEAT|PHRASE_REPETITION")

#: 船型：取本语言船型列表里已落盘的那几条，不另造词。
SHIP_IDS = ("0x24646e0b", "0x24646e0d", "0x24646e0e", "0x24646e10",
            "0x24646e12", "0x24646e13", "0x24646e7d", "0x24646e7e")

#: 船型的语法性别：冠词显式标性别的语言才需要。西语 `un Fragata` 一读就错，
#: 冠词是阳的就得配阳性船型；不筛的话每次随机取词，这条规则全靠骰子。
#: pl / ru 的船名不带冠词，这张表用不上，缺省按「没有性别」处理。
SHIP_GENDER = {
    "es": {"Pinaza": "f", "Bergantín": "m", "Bricbarca": "f", "Filibote": "m",
           "Corbeta": "f", "Fragata": "f", "Galeón": "m", "Carraca": "f"},
    "fr": {"Caravelle": "f", "Brick": "m", "Pinasse": "f", "Flûte": "f",
           "Corvette": "f", "Frégate": "f", "Galion": "m", "Caraque": "f"},
    "de": {"Pinasse": "f", "Brigg": "f", "Barke": "f", "Fleute": "f",
           "Korvette": "f", "Fregatte": "f", "Galeone": "f", "Karacke": "f"},
}

#: 冠词 → 名词语法性别。`les`、`de las`、没有性别表的语言记空串，不筛。
ART_GENDER = {
    "es": {"un": "m", "el": "m", "del": "m", "los": "m",
           "una": "f", "la": "f", "de la": "f", "las": "f"},
    "fr": {"un": "m", "le": "m", "une": "f", "la": "f"},
    "de": {"ein": "m", "der": "m", "eine": "f", "die": "f"},
}

#: 替身池。城镇与人名用各语言「典型占位名」——首都级大城市、通用姓名——
#: 这类名字在词典和语料里都常见，不会因为生僻把拼写规则拱起来；国家、货物、
#: 月份、位置介词、船队取本语言的常用词。只为让句子读得通，不追原文直译。
POOL = {
    "fr": {"town": ["Paris", "Lyon", "Marseille", "Bordeaux"],
           "person": ["Jean Dupont", "Pierre Martin", "Paul Durand", "Jacques Moreau"],
           "nation": ["Espagne", "Angleterre", "France", "Pays-Bas"],
           "goods": ["café", "sucre", "tabac", "rhum", "cacao", "indigo"],
           "month": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                     "août", "septembre", "octobre", "novembre", "décembre"],
           "near": "près de", "convoy": "convoi marchand"},
    "de": {"town": ["Berlin", "Hamburg", "München", "Köln"],
           "person": ["Max Mustermann", "Erika Mustermann", "Hans Schmidt", "Anna Müller"],
           "nation": ["Spanien", "England", "Frankreich", "Holland"],
           "goods": ["Kaffee", "Zucker", "Tabak", "Rum", "Kakao", "Indigo"],
           "month": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                     "August", "September", "Oktober", "November", "Dezember"],
           "near": "bei", "convoy": "Handelskonvoi"},
    "es": {"town": ["Madrid", "Barcelona", "Sevilla", "Valencia"],
           "person": ["Juan Pérez", "María García", "José López", "Ana Martínez"],
           "nation": ["España", "Inglaterra", "Francia", "Holanda"],
           "goods": ["café", "azúcar", "tabaco", "ron", "cacao", "índigo"],
           "month": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                     "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
           "near": "cerca de", "convoy": "convoy mercante"},
    "ru": {"town": ["Москва", "Санкт-Петербург", "Казань", "Одесса"],
           "person": ["Иван Иванов", "Пётр Петров", "Сергей Смирнов", "Анна Кузнецова"],
           "nation": ["Испания", "Англия", "Франция", "Голландия"],
           "goods": ["кофе", "сахар", "табак", "ром", "какао", "индиго"],
           "month": ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                     "августа", "сентября", "октября", "ноября", "декабря"],
           "near": "около", "convoy": "торговый конвой"},
    "pl": {"town": ["Warszawa", "Kraków", "Gdańsk", "Łódź"],
           "person": ["Jan Kowalski", "Anna Nowak", "Piotr Wiśniewski", "Maria Wójcik"],
           "nation": ["Hiszpania", "Anglia", "Francja", "Holandia"],
           "goods": ["kawa", "cukier", "tytoń", "rum", "kakao", "indygo"],
           "month": ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
                     "lipca", "sierpnia", "września", "października", "listopada", "grudnia"],
           "near": "koło", "convoy": "konwój handlowy"},
}

_CACHE = {}


def _val(entry):
    if isinstance(entry, dict):
        return str(entry.get("default", "") or "")
    return str(entry or "")


def _ships(tr, lang):
    """本语言的船型候选：{词: 语法性别}。没有性别表的语言性别记空串。"""
    kind = SHIP_GENDER.get(lang, {})
    out = {}
    for k in SHIP_IDS:
        w = _val(tr.get(k, "")).strip()
        if w:
            out[w] = kind.get(w, "")
    return out


def _ship_noun(lang, art, tr, rng):
    """按冠词性别挑船型：阴性冠词配阴名词，阳性冠词配阳名词。

    `un Fragata`、`del Galeón` 这类性别错配是冠词与占位的接口问题，不是哪条译文
    写错：同一个模板 `un %1` 会填进阴／阳不同的船型，冠词定不下来。渲染层按冠词
    性别取词，送检才不会把这条当成译文的错。

    冠词不标性别（`les`、无冠词、语言没有性别表）时同性别候选为空，退回全表随机。
    """
    ships = _ships(tr, lang)
    if not ships:
        return ""
    want = ART_GENDER.get(lang, {}).get((art or "").strip().lower(), "")
    cands = [w for w, g in ships.items() if not want or not g or g == want]
    return rng.choice(cands or list(ships))


def pools(lang, tr):
    """本语言的替身池。城镇与人名用典型占位名，不拿游戏里的真实专名去顶替——
    真实的卡塔赫纳、黑胡子这类名字在词典里是生僻词，容易把拼写规则带起来。
    `townset` 是译名表里的城镇名，`proper` 是从译文里抽出来的专名替换表。
    """
    if lang in _CACHE:
        return _CACHE[lang]
    base = POOL.get(lang, POOL["fr"])
    names = MK.load_names(lang)
    ent, _ = toml_io.read_doc(os.path.join(ROOT, "src", "data", "names", "entities.toml"))
    townset = set()
    for key, meta in ent.items():
        if isinstance(meta, dict) and meta.get("kind") == "town":
            v = _val(names.get(key, ""))
            if v:
                townset.add(v.strip())
    _CACHE[lang] = dict(base, townset=townset, proper=proper_names(lang, tr))
    return _CACHE[lang]


#: 整条只是两三个首字母大写的词（`Villa Hermosa`、`Nouvelle Orléans`、`Port St. Joe`）：
#: 地名清单条目，送检时换占位城镇。至少两词，单字留给 townset 判定，免得把
#: `Population`、`Battre` 这类单词标签也当专名换掉。
NAME_RX = re.compile(r"^[A-ZÀ-ÖØ-Ý][\w'’.-]*(?:\s+[A-ZÀ-ÖØ-Ý\d][\w'’.-]*)+$")

#: 整条只有一个大写开头的词（`Collingwood`、`Otchaqua`、`Biloxi`）：名单里的一条，
#: 语法层没有句子可检。至少三个字符，`OK`／`QA` 这类标识另有 ident_only 先排除。
WORD_RX = re.compile(r"^[A-ZÀ-ÖØ-Ý][\w'’.-]{2,}$")


def name_only(text):
    """整条是否只是一串首字母大写的词，且没有句末标点（排除 `Fin. Suite.` 这种断行）。"""
    s = clean(text)
    return bool(s) and bool(NAME_RX.match(s)) and s[-1] not in ".?!"


def list_item(text, p):
    """整条只是一个地名或一串专名（`Biloxi`、`Collingwood`、`New Orleans`、`St. Kitts`）。

    这类条目语法层没有句子可检：一条就是一个词，没有主谓、没有冠词与名词的搭配
    关系。留在语法层只会被渲染层整条换成同一个占位城镇——每个地名条目都换一次，
    一批二十条拼起来就是 `Hamburg  Hamburg  Hamburg  Hamburg`，被判重复词与拼写错，
    凭空造出原文里没有的噪声。拼写层另有词表与 allow 表兜底，不靠这里。

    单个词也算（`Collingwood` 这种人名条目在名单里成百条，`NAME_RX` 要求两词，
    漏掉它们才是连排的主因）。两词大写标题（`Feindliche Stadt`、`Militärische
    Stärke`）与两词地名（`New Orleans`）在文本上不可分，一并排除；这类短语本来
    也没有 LT 能判的语法，单词拼错仍由拼写层抓。
    """
    s = clean(text)
    if not s:
        return False
    return s in p["townset"] or bool(NAME_RX.match(s)) or bool(WORD_RX.match(s))


#: 专名候选：大写开头的词，可带 `de`／`van`／`von` 这类小写虚词再接词
#: （`Nombre de Dios`、`Villa Hermosa`、`Port St`）。
PROPER_RX = re.compile(
    r"\b[A-ZÀ-ÖØ-Ý][\w'’-]*"
    r"(?:\s+(?:(?:de|du|des|van|von|di|da|del|della|of|the|la|le)\s+)?[A-ZÀ-ÖØ-Ý][\w'’-]*)*")

_DICT = {}

#: 测试残留与截断标签：`Dummy`、`+++EMPTY+++`、`Conv`、`Suppr` 不是名字，
#: 抽进替换表只会把表弄脏
JUNK = {"Dummy", "EMPTY", "Conv", "Suppr"}

#: 句首大写常常是冠词／介词，`PROPER_RX` 会把它们连到后面的名字上
LEAD = {"À", "A", "Le", "La", "Les", "L'", "Un", "Une", "Des", "Du", "De",
        "Au", "Aux", "Et", "Ou", "Si", "Ce", "Cette", "Ces"}


#: keep_as_is 里这些理由的值是「原文即本语言写法」的专名，不能当普通译文改
KEEP_KINDS = ("name", "id", "label", "key", "credit")

_KEEP = {}


def keep_entries(lang):
    """`src/data/keep_as_is/<lang>.txt` 里按原文保留的条目 id（小写集合）。

    理由为 `save-name` 的是存档文件名，写法由各语言自己定（`Sauvegarde
    automatique` 合法），仍需检查拼写与语法，不在此列。
    """
    if lang in _KEEP:
        return _KEEP[lang]
    path = os.path.join(ROOT, "src", "data", "keep_as_is", "%s.txt" % lang)
    ids = set()
    if os.path.isfile(path):
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[0].strip() and parts[1].strip() in KEEP_KINDS:
                    ids.add(parts[0].strip().lower())
    _KEEP[lang] = ids
    return ids


def dict_of(lang):
    """本语言的 hunspell 查询函数；没有词典的语言返回 None。"""
    if lang in _DICT:
        return _DICT[lang]
    base = HUNSPELL.get(lang)
    dic = os.path.join(ROOT, "src", "data", "qa", "dict", base or "")
    known = None
    if base and os.path.isfile(dic + ".dic"):
        from spylls.hunspell import Dictionary
        hd = Dictionary.from_files(dic)

        def known(w):
            return hd.lookup(w) or hd.lookup(w.capitalize()) or hd.lookup(w.lower())
    _DICT[lang] = known
    return known


def proper_names(lang, tr):
    """抽取专名候选：大写开头、且至少一个词不在词典里。

    句首大写不算证据——`Bonjour`、`Population` 也会大写，但它们在词典里，被这道
    词典闸拦住。`Tortuga`、`Nombre de Dios` 这类词典没有的大写串就是专名，抽取后
    换成占位城镇再送检。

    两个例外：
    * `keep_as_is` 里按原文保留的名单条目（`name`／`id`／`label`／`key`／`credit`）
      是「原文即本语言写法」的专名（`Elisabeth`、`Tampa`），text_lint 要求它们与
      原文一字不差，抽进替换表只会掩盖门禁要看的东西，直接跳过。
    * hunspell 的法语词典收了 `nassau`、`smith`，这两类抽不出来，语法层仍会由
      LanguageTool 报拼写——两套词典口径不同，不在这里调和。
    """
    known = dict_of(lang)
    names = {}
    if known is None:
        return names
    skip = keep_entries(lang)
    for k, v in tr.items():
        if str(k).lower() in skip:
            continue
        for m in PROPER_RX.finditer(clean(str(v))):
            s = m.group(0).strip()
            if len(s) < 4 or "@" in s or "%" in s:
                continue
            # 界面标识整条进不了句子，测试残留（`Dummy`）与截断标签（`Suppr`）
            # 也不是名字，都别进表；句首的冠词与介词（`À Tortuga`、`Le Havre`）
            # 更不是名字的一部分
            if ident_only(s) or s in JUNK or s.split()[0] in LEAD:
                continue
            if any(not known(w.strip(".,;:!?'’")) for w in s.split()):
                names[s] = names.get(s, 0) + 1
    return names


#: 每个字符位置能补上的变音符，按语言分开——同一个 `a`，法语补成 `à`、西语补成
#: `á`、德语补成 `ä`，混在一张表里会互相打架
ACCENT_OF = {
    "fr": {"e": "é", "a": "à", "E": "É", "A": "À", "i": "ï", "u": "ù"},
    "es": {"n": "ñ", "N": "Ñ", "a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú",
           "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú"},
    "de": {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü"},
    "pl": {"a": "ą", "e": "ę", "o": "ó", "l": "ł", "n": "ń", "s": "ś", "c": "ć",
           "z": "ź", "A": "Ą", "E": "Ę", "O": "Ó", "L": "Ł", "N": "Ń", "S": "Ś",
           "C": "Ć", "Z": "Ź"},
    "ru": {"e": "ё", "E": "Ё"},
}

#: 单词：至少三个字母，不许带数字与下划线。字符类必须含小写带变音符的字母，
#: 否则 `nación` 会被截成 `nacion`、`travesía` 截成 `traves`，碎片全被当成缺变音符
ACCENT_RX = re.compile(r"[^\W\d_][^\W\d_'’-]{2,}")


def accents(lang, tr):
    """缺变音符的真词：原词词典查不到，把某一位换成带变音符的形式后查得到。

    逐位试一次，只收「一词一改就成立」的情形：`Espanol`→`Español`、
    `Ecole`→`École`、`Periodo`→`Período`。原词本来就在词典里的（`solo`、
    `periodo` 这类两种写法都合法的）不会被报。名单条目的写法由原文定，豁免。
    """
    known = dict_of(lang)
    out = {}
    fixmap = ACCENT_OF.get(lang)
    if known is None or not fixmap:
        return out
    skip = keep_entries(lang)
    for k, v in tr.items():
        if str(k).lower() in skip:
            continue
        for w in ACCENT_RX.findall(clean(str(v))):
            if known(w):
                continue
            for i, ch in enumerate(w):
                fix = fixmap.get(ch)
                if not fix:
                    continue
                cand = w[:i] + fix + w[i + 1:]
                if known(cand):
                    out.setdefault(cand, []).append((w, k))
                    break
    return out


def _skeleton(text):
    """去掉变音符的粗比较键：`Événement`／`Evénement` 同键，`Nassau`／`Naco` 不同键。"""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text.lower())
                   if not unicodedata.combining(c))


def _read_names(lang):
    """上一次落盘的专名表（`build/qa/lang_check_<lang>_names.txt`），没有就空。

    表里是 `词 | 次数` 的行。复用这张表，第一遍就能按已知专名替换，第二轮只用来
    收这次新冒出来的词。
    """
    path = os.path.join(ROOT, "build", "qa", "lang_check_%s_names.txt" % lang)
    out = {}
    if not os.path.isfile(path):
        return out
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            if " | " not in line or line.lstrip().startswith("#"):
                continue
            k, _, n = line.rpartition(" | ")
            try:
                out[k.strip()] = int(n.strip())
            except ValueError:
                continue
    return out


def _date(lang, day, month, year):
    m = POOL.get(lang, POOL["fr"])["month"][month - 1]
    if lang == "de":
        return "%d. %s %d" % (day, m, year)
    if lang == "es":
        return "%d de %s de %d" % (day, m, year)
    return "%d %s %d" % (day, m, year)


def render(text, lang, tr):
    """把占位符与标注换成该语言说得出、读得通的具体词，再交给 LanguageTool。

    换法是同类替换：城镇换成城镇表里的城镇，人名换成人名表里的人名，国家、货物、
    船型、日期各取本语言的词或格式，数字落在一个合理区间。纯图形标签（字体、图片、
    颜色、尺寸、屏幕）没有语义可换，抹成空白；段落标记 <n> 还原成空行。

    随机种子带上本条原文，同一条永远渲染出同一个结果（报告可复现），不同条目
    则取到不同的替身词。种子只按语言定死时，条目一多、地名清单一批拼起来，
    全批二十条都换成同一个 `Hamburg`，送检就判成「重复词」「拼写错」。
    """
    rng = random.Random("%s-%d" % (lang, RENDER_SEED))
    p = pools(lang, tr)
    terms = MK.load_terms(lang)

    def pick(seq):
        return rng.choice(seq)

    # <n> 是游戏里的硬换行，多数落在两句之间。送检要换成空行：LanguageTool 只在
    # 空行切段，单换行它当同一段，`wollt.  feindliche` 这种句号后接小写的开头会被
    # 当成「句中大写」或「句首小写」判掉
    s = str(text).replace("<n>", "\n\n")
    whole = s.strip()
    if whole and (whole in p["townset"] or name_only(whole)):
        # 整条就是一个地名（城镇清单、地名列表项）：没有句子可读，换占位城镇，
        # 免得把真实地名丢给词典判未收录
        return pick(p["town"])
    # 正文里出现的本语言城镇真名、抽取出来的专名，一律换占位城镇：送检只求词库
    # 覆盖，不核对真地名。合并成一个 alternation 一次扫完——逐个 `re.sub` 的成本
    # 是名字数乘以条目数（397 × 3445）。按词边界匹配，`Conv` 这类短标签才不会咬掉
    # `Convoi` 的开头。
    names = sorted(set(p["townset"]) | set(p["proper"]), key=len, reverse=True)
    if names:
        rx = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(n) for n in names))
        s = rx.sub(lambda m: pick(p["town"]), s)
    # 方括号标注：城镇与术语展开成该语言的词，其余（谜题、引用）没有语义，抹掉
    def bracket(m):
        body = m.group(1)
        if body.startswith("town:"):
            # 方括号里的城镇同样换占位城镇：送检只求词库覆盖，不还原原文语境
            return pick(p["town"])
        if body.startswith("term:"):
            return str(terms.get(body[5:], "") or "")
        return ""
    s = re.sub(r"\[([^\[\]]*)\]", bracket, s)

    # @ 占位：按前缀决定替身类别
    def at(m):
        kind, name = m.group(1), m.group(2)
        if kind == "T":
            return pick(p["town"])
        if kind == "n":
            return pick(p["nation"])
        if kind in ("P", "N", "F", "L", "A", "s"):
            return pick(p["person"])
        if kind == "G":
            return pick(p["goods"])
        if kind == "g":
            return str(rng.randrange(100, 1000))
        if kind == "a":
            return str(rng.randrange(20, 201))
        if kind == "I":
            # 一律两位以上：法语把 0–10 写作字母（`un`、`deux`），填个位数会触发
            # 「数字应写成词」这条规则，等于替身自己造错
            return str(rng.randrange(11, 61))
        if kind == "D":
            return _date(lang, rng.randrange(1, 29), rng.randrange(1, 13), rng.randrange(1660, 1701))
        if kind == "S":
            tail = m.string[max(0, m.start() - 16):m.start()]
            words = re.findall(r"[^\W\d_]+", tail.lower())
            art = ""
            if words and len(words) >= 2:
                two = words[-2] + " " + words[-1]
                if two in ART_GENDER.get(lang, {}):
                    art = two
            if words and not art and words[-1] in ART_GENDER.get(lang, {}):
                art = words[-1]
            return _ship_noun(lang, art, tr, rng) or pick(p["goods"])
        if kind == "C":
            return p["convoy"]
        # @l/@d/@r/@M 是位置。首字母大写：这类占位常落在段首或句号之后，
        # 小写开头会凭空触发「句首应大写」
        return "%s %s" % (p["near"][:1].upper() + p["near"][1:], pick(p["town"]))
    s = re.sub(r"@([a-zA-Z])\$([^$]*)\$", at, s)

    # 条形参数 %N：默认填数；紧跟冠词时原文多半是船名或货物名，改填同性名词
    def pct(m):
        art = m.group(1)
        if art:
            noun = _ship_noun(lang, art, tr, rng) or pick(p["goods"])
            return "%s %s" % (art.strip(), noun)
        # 无冠词时是条形参数，多半跟单数名词（`%d troupe`），同样避开 0–10
        return str(rng.randrange(11, 100))
    s = re.sub(r"(?:(de las|de la|una|un|une|le|la|les|ein|eine|der|die|das|el|los|las|del)\s+)?%[0-9]+", pct, s)
    # 其余尖括号标签全是图形与排版，抹成空白——不留空会把前后词粘成一个词
    s = re.sub(r"<[^<>]*>", " ", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def load(lang):
    doc, _ = toml_io.read_doc(TR % lang)
    return MK.expand_doc(lang, doc)


# ---------------------------------------------------------------- 语法

def grammar(lang, tr):
    """过 LanguageTool，命中按规则归纳。

    条目先各自渲染成读得通的句子，再按字符数分批拼起来送检。批内一律用空行
    （两个换行）分隔——LanguageTool 只在空行处切段，单换行它当成同一段，
    `Population` 这类没有句末标点的短标签就会与下一条首句粘成一句而被判错。
    """
    code = LT_CODE.get(lang)
    if not code:
        return None, []
    import language_tool_python

    tool = language_tool_python.LanguageTool(code)
    # 拼写规则保持开启：替身已换成词典里的常见词（Paris、Jean Dupont 这类），
    # 专名不会再把拼写命中拱起来。`## 拼写` 一节的 hunspell 统计照旧独立跑，
    # 两处口径并列，不互相替代。
    # 上一次落盘的专名表先并进来：第一遍就按已知专名替换，只有这次新冒出来的
    # 词才触发第二轮，常态下省掉一整遍 LanguageTool
    p = pools(lang, tr)
    for w, n in _read_names(lang).items():
        p["proper"].setdefault(w, n)
    # 地名与专名清单项不进语法层：一条一个词，没有句子可查，渲染后被换成同一个
    # 占位城镇，一批拼起来就是 `Hamburg  Hamburg  Hamburg`（见 list_item）
    keys = [k for k in tr if checkable(tr[k]) and not list_item(tr[k], p)]

    # 按字符数切批：百科长文不跟短标签挤在一批，否则一批几万字要跑几分钟
    BATCH_CHARS = 3000
    SEP = "\n\n"

    def batches_of(ren):
        batches, cur, cur_chars = [], [], 0
        for k in keys:
            n = len(ren[k])
            if cur and cur_chars + n > BATCH_CHARS:
                batches.append(cur)
                cur, cur_chars = [], 0
            cur.append(k)
            cur_chars += n
        if cur:
            batches.append(cur)
        return batches

    def run(ren):
        hits, extra = [], set()
        for batch in batches_of(ren):
            joined = SEP.join(ren[k] for k in batch)
            spans, pos = [], 0
            for k in batch:
                spans.append((k, pos, pos + len(ren[k])))
                pos += len(ren[k]) + len(SEP)
            for m in tool.check(joined):
                off = m.offset
                for k, s, e in spans:
                    if s <= off < e:
                        hits.append((k, m.rule_id, m.context.replace("\n", " ")[:80],
                                     (m.replacements[0] if m.replacements else "")[:40]))
                        break
                # 拼写命中的大写词若被建议换成完全不同的词，就是词典没收录的专名
                # （`Nassau`→`Naco`）。若只是差变音符（`Evénement`→`Événement`），
                # 那是真拼写错，留给报告，不吸收进替换表。
                txt = (getattr(m, "matched_text", "") or "").strip().strip(".,;:!?«»\"'’")
                if (getattr(m, "category", "") == "TYPOS" and txt[:1].isupper()
                        and len(txt) >= 3 and not re.search(r"[@%<>\[\]]", txt)):
                    rep = (m.replacements[0] if m.replacements else "").strip()
                    if (rep and _skeleton(rep) != _skeleton(txt)
                            and txt not in JUNK and not ident_only(txt)):
                        extra.add(txt)
        return drop_cross_batch(hits, ren), extra

    def drop_cross_batch(hits, ren):
        """重复词类规则只认单条内的重复：批内相邻两条被当成同一段。

        把一批 3000 字的文本连着送检，`nun` 这种高频词在 A 条出现一次、B 条出现一次，
        LanguageTool 就判「同一段里重复」——加几个换行都拦不住，它把整个 check 文本
        当一个文档。判据用「单条复检」：单条文本也报同一条规则才算真命中。实测
        `GERMAN_WORD_REPEAT_BEGINNING_RULE` 抽 15 条有 14 条单条不报，
        `DE_REPEATEDWORDS_NUN`、`GERMAN_WORD_REPEAT_RULE` 则全部不报。
        只复检这一类规则，命中约 200 条、去重后 150 条上下，多花几秒。
        """
        kept, cache, dropped = [], {}, 0
        for k, rule, ctx, rep in hits:
            if REPEAT_RX.search(rule):
                if k not in cache:
                    cache[k] = {m.rule_id for m in tool.check(ren[k])}
                if rule not in cache[k]:
                    dropped += 1
                    continue
            kept.append((k, rule, ctx, rep))
        if dropped:
            sys.stderr.write("跨条重复噪声丢弃 %d 处（单条复检不报）\n" % dropped)
        return kept

    ren = {k: render(tr[k], lang, tr) for k in keys}
    hits, extra = run(ren)
    if extra:
        # 这一遍认出的专名并入替换表，下一轮生效。不重跑 LanguageTool：重跑一遍
        # 是全量成本，而每次替换的组合不同，重跑常又冒出一两个新的假专名，收敛
        # 不了；报告里多报一次，表里留一条，下次就干净。
        p = pools(lang, tr)
        for w in extra:
            p["proper"][w] = p["proper"].get(w, 0) + 1
        sys.stderr.write("新认出 %d 个专名，已并入替换表，下一轮生效\n" % len(extra))
    return len(keys), hits


# ---------------------------------------------------------------- 拼写

def split_head(w, vocab, link=("s", "n", "en", "er", "es", "e")):
    """长复合词切出词头；切不动返回 None。连接元音后至少还得剩两个字母。"""
    low = w.lower()
    for i in range(len(low) - 3, 2, -1):
        h, rest = low[:i], low[i:]
        if h in vocab and (rest in vocab or (rest[:1] in link and rest[1:] in vocab and len(rest) > 2)):
            return h
    return None


#: 本地 hunspell 词典（src/data/qa/dict/<base>.aff + .dic）。有就用它，它带变形与复合词规则，
#: 比纯频率表准得多；没有就退回 pyspellchecker（pyspellchecker 只收拉丁系与俄语、波兰语等，
#: 中日韩没有词表，硬走会抛 ValueError，因此这里显式跳过）。
HUNSPELL = {"de": "de_DE_frami", "fr": "fr_FR", "es": "es_ES", "ru": "ru_RU", "pl": "pl_PL"}
NO_HUNSPELL = {"zh", "ja", "ko"}


def spell(lang, tr, allow):
    """未收录词。专名、术语、缩写、以及能拆成两个词典词的复合词都不报。

    中日韩没有 hunspell 词典、pyspellchecker 也没有对应词表：这两门语言的「拼写」不是
    词形问题，而是分词与用字问题（日语假名种类混用、中文简繁与全半角），词表法查不出来，
    所以这里直接返回空，交给 test_lint 的字符层规则。
    """
    if lang in NO_HUNSPELL:
        print("  「%s」无形态词典，拼写层跳过" % lang)
        return {}

    base = HUNSPELL.get(lang)
    dic = os.path.join(ROOT, "src", "data", "qa", "dict", base or "")
    hd = None
    if base and os.path.isfile(dic + ".dic"):
        from spylls.hunspell import Dictionary
        hd = Dictionary.from_files(dic)

    if hd is None:
        from spellchecker import SpellChecker
        sp = SpellChecker(language=lang)
        vocab = set(w.lower() for w in sp.word_frequency.words())

    def known(w):
        if hd is not None:
            return hd.lookup(w) or hd.lookup(w.capitalize()) or hd.lookup(w.lower())
        return w.lower() not in sp.unknown([w.lower()])

    words, per_key = {}, {}
    WORD = ANY_WORD
    for k, v in tr.items():
        if ident_only(v):                       # 界面键与任务编号不是词，不查拼写
            continue
        for w in WORD.findall(clean(str(v))):
            if w.lower() in allow or w in allow:
                continue
            words.setdefault(w, set()).add(k)
    for w in words:
        if known(w):
            continue
        if hd is None and (len(w) <= 3 or split_head(w, vocab)):
            continue
        if len(w) <= 3:
            continue
        per_key[w] = sorted(words[w])[:3]
    return per_key


def build_allow(lang, tr):
    """白名单：译名表的值、术语表的值、全大写缩写、以及文本里逐字出现过的英文词。"""
    allow = set()
    for tbl in (MK.load_names(lang), MK.load_terms(lang)):
        for v in tbl.values():
            if isinstance(v, dict):
                v = v.get("default", "")
            for w in ANY_WORD.findall(str(v)):
                allow.add(w.lower())
    for v in tr.values():
        for w in ANY_WORD.findall(str(v)):
            if w.isupper() and len(w) <= 5:      # STRG、OK、CTRL 这类键名与缩写
                allow.add(w.lower())
    return allow


# ---------------------------------------------------------------- 复合词

def compounds(tr, limit=40):
    """德语名词连写切分：长词按最长前缀 + 连接元音拆开，统计词头分布。"""
    from spellchecker import SpellChecker

    sp = SpellChecker(language="de")
    vocab = set(w.lower() for w in sp.word_frequency.words())
    heads, misses = {}, []
    LINK = ("s", "n", "en", "er", "es", "e")
    WORD = re.compile(r"[A-ZÄÖÜ][a-zäöüß]{11,}")
    for k, v in tr.items():
        for w in WORD.findall(str(v)):
            low = w.lower()
            cut = None
            for i in range(len(low) - 4, 3, -1):
                h, rest = low[:i], low[i:]
                if h in vocab and (rest in vocab or (rest[:1] in LINK and rest[1:] in vocab)):
                    cut = h
                    break
            if cut:
                heads[cut] = heads.get(cut, 0) + 1
            elif low not in vocab:
                misses.append((w, k))
    top = sorted(heads.items(), key=lambda x: -x[1])[:limit]
    return top, misses[:60]


# ---------------------------------------------------------------- 报告

def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="de")
    ap.add_argument("--grammar-only", action="store_true")
    ap.add_argument("--spell-only", action="store_true")
    a = ap.parse_args(argv)

    lang = a.lang
    tr = load(lang)
    lines = ["# %s 形态层检查（%d 条）\n" % (lang, len(tr))]
    n_blank = sum(1 for v in tr.values() if not str(v).strip())
    n_phold = sum(1 for v in tr.values() if str(v).strip() and not clean(v))
    n_ident = sum(1 for v in tr.values() if ident_only(v))
    n_skip = sum(1 for v in tr.values() if clean(v) and not checkable(v))
    n_keys = sum(1 for v in tr.values() if checkable(v))
    p = pools(lang, tr)
    n_list = sum(1 for v in tr.values() if checkable(v) and list_item(v, p))
    lines.append("口径：空值 %d 条、纯占位 %d 条、跳过 %d 条（其中 %d 条整条只有大写"
                 "字母、数字、下划线，其余是测试串与编号行）、送检 %d 条"
                 "（另 %d 条是地名／专名清单，只进拼写层）。\n"
                 % (n_blank, n_phold, n_skip, n_ident, n_keys - n_list, n_list))

    if not a.spell_only:
        n, hits = grammar(lang, tr)
        if n is None:
            lines.append("## 语法\n\nLanguageTool 不覆盖 %s，跳过。\n" % lang)
        else:
            rules = {}
            for k, r, msg, rep in hits:
                rules[r] = rules.get(r, 0) + 1
            lines.append("## 语法（LanguageTool %s）\n" % LT_CODE[lang])
            lines.append("检查 %d 条，命中 %d 处，涉及 %d 条规则。\n" % (n, len(hits), len(rules)))
            lines.append("| 规则 | 次数 |")
            lines.append("|---|---|")
            for r, c in sorted(rules.items(), key=lambda x: -x[1])[:25]:
                lines.append("| `%s` | %d |" % (r, c))
            lines.append("")
            for k, r, msg, rep in hits[:120]:
                lines.append("%s | %-24s | %s | → %s" % (k, r, msg, rep))
            lines.append("")

    proper = pools(lang, tr)["proper"]
    for w, n in _read_names(lang).items():
        proper.setdefault(w, n)
    if proper:
        lines.append("## 抽取的专名（替换表）\n")
        lines.append("%d 个，送检前换成占位城镇。判据：大写开头、至少一个词不在词典里，"
                     "且不是 keep_as_is 里按原文保留的名单条目。\n" % len(proper))
        for w, c in sorted(proper.items(), key=lambda x: (-x[1], x[0]))[:80]:
            lines.append("%s | %d" % (w, c))
        lines.append("")

    acc = accents(lang, tr)
    if acc:
        lines.append("## 缺变音符（%d 个）\n" % len(acc))
        lines.append("判据：原词查不到、任一位换成带变音符的形式后查得到；"
                     "原词本就在词典里的不报，名单条目豁免。\n")
        for w, ks in sorted(acc.items(), key=lambda x: (-len(x[1]), x[0]))[:60]:
            lines.append("%s | %d | %s" % (w, len(ks), ", ".join(
                "%s@%s" % (o, i) for o, i in ks[:2])))
        lines.append("")

    # 清零时也要落盘：留着上一轮的文件会让人以为还没修完
    path = os.path.join(ROOT, "build", "qa", "lang_check_%s_accents.txt" % lang)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s 缺变音符（%d 个）\n\n" % (lang, len(acc)))
        for w, ks in sorted(acc.items(), key=lambda x: (-len(x[1]), x[0])):
            f.write("%s | %d | %s\n" % (w, len(ks),
                                       ", ".join("%s@%s" % (o, i) for o, i in ks)))

    if not a.grammar_only:
        allow = build_allow(lang, tr)
        unk = spell(lang, tr, allow)
        lines.append("## 拼写\n\n未收录词 %d 个（已剔除译名表、术语表与缩写）。\n" % len(unk))
        for w, ks in sorted(unk.items(), key=lambda x: x[1][0])[:120]:
            lines.append("%s | %s" % (w, ", ".join(ks)))
        lines.append("")
        if lang == "de":
            top, misses = compounds(tr)
            lines.append("## 复合词词头（前 40）\n")
            lines.append("| 词头 | 出现 |")
            lines.append("|---|---|")
            for h, c in top:
                lines.append("| %s | %d |" % (h, c))
            lines.append("\n未能切分的长词 %d 个（前 60）：\n" % len(misses))
            for w, k in misses:
                lines.append("%s | %s" % (w, k))

    if proper:
        out2 = os.path.join(ROOT, "build", "qa", "lang_check_%s_names.txt" % lang)
        body = ["# %s 专名替换表（%d 个）\n" % (lang, len(proper)),
                "抽取判据：大写开头、至少一个词不在 hunspell 词典里，且不是 keep_as_is\n"
                "里按原文保留的名单条目。送检前换成占位城镇；下次运行会先读这张表。\n\n"]
        for w, c in sorted(proper.items(), key=lambda x: (-x[1], x[0])):
            body.append("%s | %d" % (w, c))
        with io.open(out2, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(body) + "\n")

    text = "\n".join(lines) + "\n"
    out = os.path.join(ROOT, "build", "qa", "lang_check_%s.txt" % lang)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, "w", encoding="utf-8", newline="").write(text)
    print(text[:4000])
    print("报告：%s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
