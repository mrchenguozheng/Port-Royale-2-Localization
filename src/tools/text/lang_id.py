"""按常用虚词粗判一段文本最像哪种语言（只做「疑似」，不做精确识别）。

给 `qa/lang_mix.py`（扫参照层的串语言条目）与 `analysis/ref_clean.py --align-foreign`
（把零售里整条是外语的行退成占位）共用，判据只在这里维护一份。

故意粗：只看六门语言的常用虚词，一段 ≥3 词、本语言命中 ≤1、某门外语命中 ≥2 才算
「像外语」。人名、地名、版权声明这类专名与通用短语不该被它判成外语——所以单份扫描
只能缩小范围，结论仍要人看一眼。
"""
import re

LANGS = ["de", "en", "es", "fr", "pl", "ru"]

STOP = {
    "de": "der die das und ist nicht ein eine mit für von zu den dem sich auf im am "
          "wir sie ich ihr es auch aber wenn nach bei aus".split(),
    "en": "the and of to in is that for it with as on was are this you your they "
          "we not be have from by".split(),
    "fr": "le la les des et est une un pour dans que qui avec sur pas au du ce "
          "il elle nous vous sont être".split(),
    "es": "el la los las de que y en un una por con para se del al es son "
          "no su lo como".split(),
    "pl": "i w nie się na z że do to jest jak o co po za od oraz ale "
          "przez jego".split(),
    "ru": "и в не на что с по это он она как из у же за от для или "
          "его было".split(),
}

STRIP = [
    (re.compile(r"<[^<>]*>"), " "),
    (re.compile(r"\[[^\[\]]*\]"), " "),
    (re.compile(r"@[a-zA-Z]\$[^$]*\$"), " "),
    (re.compile(r"%\d"), " "),
    (re.compile(r"\b[fgh]:[^<> ]*"), " "),
]
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

#: 版权／许可声明：各语言版本一律保留英文原文，属正当保留，不判外语。
KEEP_FOREIGN = re.compile(r"Copyright|RAD Game Tools|Miles Sound System|©|All rights reserved",
                          re.I)


def plain(text):
    for rx, rep in STRIP:
        text = rx.sub(rep, text)
    return text


def words(text):
    return [w.lower() for w in WORD.findall(plain(text))]


def guess(text_or_words):
    """返回 (最像的语言, 该语言命中数, 各语言命中数)；命中数 <2 判不出，返回 (None, 0, 得分)。"""
    ws = text_or_words if isinstance(text_or_words, list) else words(text_or_words)
    sc = {lang: sum(1 for w in ws if w in STOP[lang]) for lang in LANGS}
    top = max(sc, key=lambda x: sc[x])
    if sc[top] < 2:
        return None, 0, sc
    return top, sc[top], sc


def is_foreign(text, lang, min_words=3, min_hits=2):
    """整条像别的语言就返回那个语言，否则 None。版权声明直接判不是外语。

    `min_hits=1` 只在「本语言的虚词得分明显低于最高分」时放宽——德语和法语／西语
    的虚词表有重叠（德语句首 `Es` 会撞西语 `es`），所以不能只看绝对得分，要看
    最高分领先本语言至少 2 个词。
    """
    if KEEP_FOREIGN.search(text):
        return None
    ws = words(text)
    if len(ws) < min_words or lang not in STOP:
        return None
    top, top_n, sc = guess(ws)
    if not top or top == lang:
        return None
    if top_n >= min_hits and top_n - sc[lang] >= 2:
        return top
    return None
