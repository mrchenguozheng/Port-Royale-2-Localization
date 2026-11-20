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


#: 固定种子：同一份文件两次体检拿到同一批替身，两次报告能逐行对照。
RENDER_SEED = 20261120

#: 船型：取本语言船型列表里已落盘的那几条，不另造词。
SHIP_IDS = ("0x24646e0b", "0x24646e0d", "0x24646e0e", "0x24646e10",
            "0x24646e12", "0x24646e13", "0x24646e7d", "0x24646e7e")

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


def pools(lang):
    """本语言的替身池。城镇与人名用典型占位名，不拿游戏里的真实专名去顶替——
    真实的卡塔赫纳、黑胡子这类名字在词典里是生僻词，容易把拼写规则带起来。"""
    if lang in _CACHE:
        return _CACHE[lang]
    base = POOL.get(lang, POOL["fr"])
    _CACHE[lang] = dict(base)
    return _CACHE[lang]


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
    颜色、尺寸、屏幕）没有语义可换，抹成空白；段落标记 <n> 还原成换行。
    """
    rng = random.Random("%s-%d" % (lang, RENDER_SEED))
    p = pools(lang)
    terms = MK.load_terms(lang)
    names = MK.load_names(lang)

    def pick(seq):
        return rng.choice(seq)

    s = str(text).replace("<n>", "\n")
    # 方括号标注：城镇与术语展开成该语言的词，其余（谜题、引用）没有语义，抹掉
    def bracket(m):
        body = m.group(1)
        if body.startswith("town:"):
            key = body[5:]
            return _val(names.get(key, "")) or key
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
            return _val(tr.get(pick(SHIP_IDS), "")) or pick(p["goods"])
        if kind == "C":
            return p["convoy"]
        # @l/@d/@r/@M 是位置。首字母大写：这类占位常落在段首或句号之后，
        # 小写开头会凭空触发「句首应大写」
        return "%s %s" % (p["near"][:1].upper() + p["near"][1:], pick(p["town"]))
    s = re.sub(r"@([a-zA-Z])\$([^$]*)\$", at, s)

    # 条形参数 %N：默认填数；紧跟冠词时原文多半是船名或货物名，改填名词
    def pct(m):
        art = m.group(1)
        if art:
            noun = _val(tr.get(pick(SHIP_IDS), "")) or pick(p["goods"])
            return "%s %s" % (art, noun)
        # 无冠词时是条形参数，多半跟单数名词（`%d troupe`），同样避开 0–10
        return str(rng.randrange(11, 100))
    s = re.sub(r"(?:(un|une|le|la|les|ein|eine|der|die|das|el|los|las)\s+)?%[0-9]+", pct, s)
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
    # 拼写由下面的 spell() 用 hunspell 词典单独做；这里关掉 LT 自带的拼写规则，
    # 否则替身里替换进去的城镇名、人名会反过来被报成拼写错。
    tool.disable_spellchecking()
    keys = [k for k in tr if clean(tr[k])]
    ren = {k: render(tr[k], lang, tr) for k in keys}

    # 按字符数切批：百科长文不跟短标签挤在一批，否则一批几万字要跑几分钟
    BATCH_CHARS = 3000
    SEP = "\n\n"
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

    hits = []
    for batch in batches:
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

    text = "\n".join(lines) + "\n"
    out = os.path.join(ROOT, "build", "qa", "lang_check_%s.txt" % lang)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, "w", encoding="utf-8", newline="").write(text)
    print(text[:4000])
    print("报告：%s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
