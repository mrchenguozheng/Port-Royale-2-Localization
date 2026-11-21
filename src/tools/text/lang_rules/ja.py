# -*- coding: utf-8 -*-
"""日文规则：标点 + 分词器 + 补空格策略（三段式接口见 lang_rules/spec.py）。"""

import re
import os

from . import base
from . import spec as S

LANG = "ja"

PUNCT = {
    "open": "「『（［【〈〔",
    "close": "」』）］】〉〕",
    "single": "、。！？…：；～—",
    "runs": "…—",
    "cjk": r"\u3040-\u30ff\u4e00-\u9fff\uff66-\uff9f",
}

ASCII = {",": "、", ";": "；", ":": "：", "!": "！", "?": "？", "(": "（", ")": "）"}

FMT, PUNCT_CHARS = base.make_fmt(PUNCT)

CJK_RX = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uff66-\uff9f]")

#: 目标文字：假名（平假名/片假名/半角片假名）。判「译没译」时不收汉字 ——
#: 中文译文里也全是汉字，只有假名能证明这条真的改成了日语。
SCRIPT = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\uff66-\uff9f]")

#: 助词。长的写在前面（正则会先匹配到长的）。
JA_PARTICLES = [
    "から", "まで", "より", "など", "ほど", "ばかり", "だけ", "しか", "こそ",
    "さえ", "でも", "って", "ので", "のに", "けど",
    "は", "が", "を", "に", "で", "と", "も", "へ", "や", "か", "ね", "よ",
]
JA_HEAD = r"\u4e00-\u9fff\u3400-\u4dbf\u30a1-\u30fa\u30fc"
JA_TAIL = r"\u4e00-\u9fff\u3400-\u4dbf\u30a1-\u30fa\u30fc「『（【〈〔"
JA_PART_RX = re.compile(
    r"(?<=[%s])(%s)(?=[%s])" % (JA_HEAD, "|".join(JA_PARTICLES), JA_TAIL))

SPLIT_RX = re.compile(r"(<[^<>]*>|@[A-Za-z]\$[^$]*\$|%[0-9A-Za-z]+)")
NO_SPACE_AFTER = "、。！？…：；～—」』）"
IDIOM_TAIL = ("つい", "つき", "よっ", "より", "とっ", "おい", "かか", "わた",
              "対", "伴", "応", "関", "際", "先立", "向け", "通じ", "基づ",
              "限", "代わ", "加え", "従", "即", "照", "いう", "いっ",
              # 「〜にある」「〜がいる」「〜がない」这类存在句/否定，助词后不留在断点，
              # 否则会出现「北の島に あるポートロワイヤル」这种切开惯用搭配的写法。
              "ある", "いる", "ない")

_TOK = None


class _Tagger:
    """形态素分析器：janome → fugashi → 无。`tag()` 统一成 [(surface, pos)]。"""

    def __init__(self, name, tok=None):
        self.name = name
        self.tok = tok

    def tag(self, text):
        if self.name == "janome":
            return [(t.surface, t.part_of_speech) for t in self.tok.tokenize(text)]
        if self.name == "fugashi":
            out = []
            for w in self.tok(text):
                f = w.feature
                pos = getattr(f, "pos1", "") or (f[0] if isinstance(f, (list, tuple)) else "")
                out.append((w.surface, pos))
            return out
        return None


def _tagger():
    global _TOK
    if _TOK is not None:
        return _TOK
    try:
        from janome.tokenizer import Tokenizer
        _TOK = _Tagger("janome", Tokenizer())
        return _TOK
    except Exception:
        pass
    try:
        import fugashi
        _TOK = _Tagger("fugashi", fugashi.Tagger())
        return _TOK
    except Exception:
        pass
    _TOK = _Tagger("none")
    return _TOK


def space_particles(text):
    """正则版：汉字/片假名 + 助词 + 汉字/片假名 → 助词后补空格。"""
    return JA_PART_RX.sub(lambda m: m.group(1) + " ", text)


def space_particles_analyzer(text, tagger=None):
    """形态素版：只给「名词/代词/数词 + 助词」补空格；不可用时退回正则。"""
    tok = tagger or _tagger()
    if tok.name == "none":
        return space_particles(text)
    out = []
    for part in SPLIT_RX.split(text):
        if not part:
            continue
        if SPLIT_RX.fullmatch(part):
            out.append(part)
            continue
        lead = part[:len(part) - len(part.lstrip())]
        tail = part[len(part.rstrip()):]
        core = part.strip()
        if not core:
            out.append(part)
            continue
        part = core
        toks = tok.tag(part) or []
        res = []
        for i, (surf, pos) in enumerate(toks):
            res.append(surf)
            if not pos.startswith("助詞"):
                continue
            if surf == "の" or "連体化" in pos:
                continue
            if "接続助詞" in pos or "終助詞" in pos or "間投助詞" in pos:
                continue
            prev_pos = toks[i - 1][1] if i > 0 else ""
            if not prev_pos.startswith(("名詞", "代名詞", "数詞", "固有名詞")):
                continue
            nxt_tok = toks[i + 1][0] if i + 1 < len(toks) else ""
            nxt_pos = toks[i + 1][1] if i + 1 < len(toks) else ""
            if nxt_tok.startswith(IDIOM_TAIL):
                continue
            if nxt_pos.startswith("助詞"):
                continue
            nxt = nxt_tok[:1]
            if not nxt or nxt == " " or nxt in NO_SPACE_AFTER:
                continue
            res.append(" ")
        out.append(lead + "".join(res) + tail)
    return "".join(out)


def normalize_punct(text, date_format=False):
    """标点 → 占位符 → <n>，不含助词空格。"""
    text = base.fix_ascii_punct(text, ASCII, CJK_RX)
    if date_format:
        return base.clean_n(FMT(text))
    return base.clean_n(base.fix_vars(FMT(text), PUNCT_CHARS, CJK_RX))


def normalize(text, particles=False, date_format=False):
    """兼容旧调用：particles=True 时先补助词空格。新代码请用 spec() 的补空格策略。"""
    if particles:
        text = space_particles_analyzer(text)
    return normalize_punct(text, date_format=date_format)


class JaLineBreak:
    r"""引擎层断行：机械断行先切，切不动的交给手工断点表。

    机械断行只切在三个安全点：助词后、接续词后、标点后（`、。！？」』`）。
    片假名专名、拉丁串、数字串整体保留，宁可留一段超限也不硬拆——那种拆法
    在词中间下刀，读起来比换行更糟。切完仍超限的条目记进
    `build\qa\line_manual_ja.txt`，由 `src\data\line_breaks\ja.toml` 的手工位置兜底。

    手工表优先：某条在表里就直接用人工断点，不再跑机械切（人工位置未必是
    机械层会选的点）。
    """

    def __init__(self, root=None, limit=None):
        self.LB = _line_breaks()
        self.root = root or _root()
        self.limit = int(limit or 13)
        self.table = self.LB.read_table(self.root, LANG)

    # ---- 对外 ----------------------------------------------------
    def run(self, out, order):
        changed = manual = unresolved = 0
        missed = []
        for hid in order:
            text = out.get(hid)
            if not text:
                continue
            if hid in self.table:
                new = self.LB.insert(text, self.table[hid], limit=self.limit, hid=hid)
                if new != text:
                    out[hid] = new
                    changed += 1
                    manual += 1
                continue
            new, ok, bad = self.wrap(text)
            if not ok:
                unresolved += 1
                missed.append((hid, bad))
            elif new != text:
                out[hid] = new
                changed += 1
        self.write_missed(missed)
        return {"changed": changed, "manual": manual, "unresolved": unresolved}

    def wrap(self, text):
        """按段机械断行。返回 (新文本, 是否全部解决, 第一个切不动的段)。

        引擎在空格与 `<n>` 处都断，所以两者都是段边界；只有一段里没有空格才
        需要靠 `<n>` 切。第三项回的是**真正切不动的那一段**，不是最长段——
        清单要拿它给人工填位置。
        """
        segs = re.split(r"(<n(?::\d+)?>|[ \t]+)", text)
        out = []
        bad = ""
        for part in segs:
            if not part:
                continue
            if re.fullmatch(r"<n(?::\d+)?>", part) or re.fullmatch(r"[ \t]+", part):
                out.append(part)
                continue
            if self.LB.visible_length(part) <= self.limit:
                out.append(part)
                continue
            wrapped = self.wrap_segment(part)
            if wrapped is None:
                if not bad:
                    bad = part
                out.append(part)
            else:
                out.append(wrapped)
        return "".join(out), (bad == ""), bad

    def wrap_segment(self, seg):
        """一段超限文本 → 加 `<n>` 的文本；切不动返回 None。"""
        ub = self._units(seg)
        chars = "".join(u["c"] for u in ub)
        if len(chars) > 400:
            return None
        toks = _tagger().tag(chars) if _tagger().name != "none" else None
        if toks and "".join(s for s, _p in toks) != chars:
            toks = None
        strong, weak = self._safe_points(chars, toks)
        cuts = self._greedy(len(chars), strong, weak)
        if cuts is None:
            return None
        # 把字符位置映射回原串：`ub` 里的标签 c 为空，按可见字符计数对齐，
        # 不能按 ub 下标对齐（标签会让下标与字符位置错开）。
        out = []
        seen = 0
        next_cut = 0
        for u in ub:
            if not u["c"]:
                out.append(u["raw"])
                continue
            if next_cut < len(cuts) and seen == cuts[next_cut]:
                out.append("<n>")
                next_cut += 1
            out.append(u["raw"])
            seen += 1
        while next_cut < len(cuts):
            out.append("<n>")
            next_cut += 1
        return "".join(out)

    # ---- 内部 ----------------------------------------------------
    def _units(self, seg):
        """可见单位：[{raw, c}]。标签 c 为空（不占宽），占位用一个字符占 1 字。"""
        ub = []
        for part in UNIT_SPLIT.split(seg):
            if not part:
                continue
            if UNIT_SPLIT.fullmatch(part):
                if part.startswith("<"):
                    ub.append({"raw": part, "c": ""})
                else:
                    # 变量渲染成一个数字或一个地名，按 1 字算，与 line_run 同口径
                    ub.append({"raw": part, "c": "\u25cf"})
                continue
            for ch in part:
                ub.append({"raw": ch, "c": ch})
        return ub

    def _safe_points(self, chars, toks):
        """切点分两级：强（标点/助词/接续词后），弱（普通词边界，避开不可切串内部）。

        弱切点只在一段里找不到强切点、又只超几个字时才用：`再びきちんと生産できるように`
        14 字，没有强切点，切在「きちんと」后读得通；而片假名专名、拉丁串、数字串的
        内部边界不给弱切点——那是词中间下刀。
        """
        strong, weak = set(), set()
        if toks:
            acc = 0
            for i, (surf, pos) in enumerate(toks):
                acc += len(surf)
                if i + 1 >= len(toks) or not (0 < acc < len(chars)):
                    continue
                nxt_surf, nxt_pos = toks[i + 1]
                if nxt_pos.startswith("助詞"):
                    continue
                if (pos.startswith("助詞") or pos.startswith("接続詞")
                        or "読点" in pos or "句点" in pos
                        or surf in "、。！？：；"):
                    strong.add(acc)
                    continue
                if _same_unbreakable(surf, pos, nxt_surf, nxt_pos):
                    continue
                weak.add(acc)
        # 没有分词器（或分词把字符吃掉）时，退回「标点后」的切点
        if not strong:
            for i, ch in enumerate(chars[:-1], 1):
                if ch in "、。！？：；":
                    strong.add(i)
        return strong, weak

    def _greedy(self, total, strong, weak):
        """贪心切点：每段不超过上限；强切点优先，退而用弱切点。切不动返回 None。"""
        cuts = []
        start = 0
        while total - start > self.limit:
            cand = [p for p in strong if start < p <= start + self.limit]
            if not cand:
                cand = [p for p in weak if start < p <= start + self.limit]
            if not cand:
                return None
            cut = max(cand)
            cuts.append(cut)
            start = cut
        return cuts

    def write_missed(self, rows):
        """写手工断点清单：分「含日文」与「技术串」两节。

        报的是**切不动的那一段**，不是整条——人工要数位置的是段，不是整条。
        """
        qa = os.path.join(self.root, "build", "qa")
        os.makedirs(qa, exist_ok=True)
        path = os.path.join(qa, "line_manual_ja.txt")
        need, tech = [], []
        for hid, seg in rows:
            plain = TAG_SUB.sub("", seg)
            if JAPANESE.search(plain):
                need.append((hid, seg, plain))
            else:
                tech.append((hid, seg, plain))
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# 机械断行切不动的段（整条 %d 条）\n" % len(rows))
            f.write("# 多数是段里有超过上限的不可切串（专名、职位名、键名、数字），\n")
            f.write("# 机械层不硬拆；有的只能靠改译缩短或容忍超限。\n")
            f.write("# 确实要换个人工位置的，写进 src\\data\\line_breaks\\ja.toml：\n")
            f.write('#   "0x…" = [12]   # 在第 12 个可见字之前插 <n>（段首记 0）\n')
            f.write("\n## 含日文（%d 条）\n" % len(need))
            for hid, seg, plain in sorted(need):
                f.write("%s\t%d 字\t%s\n"
                        % (hid, self.LB.visible_length(seg), plain[:120]))
            f.write("\n## 技术串（键名／资源名／数字／符号，%d 条）\n" % len(tech))
            for hid, seg, plain in sorted(tech):
                f.write("%s\t%d 字\t%s\n"
                        % (hid, self.LB.visible_length(seg), plain[:120]))


UNIT_SPLIT = re.compile(r"<n(?::\d+)?>|@[A-Za-z]\$[^$]*\$|%[0-9]+[A-Za-z]?|<[^<>]*>")
LATIN = re.compile(r"[A-Za-z0-9_]")
TAG_SUB = re.compile(r"<n(?::\d+)?>|<[^<>]*>")
JAPANESE = re.compile(r"[ぁ-ゖァ-ヺ一-龥]")


def _line_breaks():
    """取手工断点层模块。

    两种加载方式都要活：`text.lang_rules.ja`（流水线）与顶层 `lang_rules.ja`
    （`tests/test_rules.py` 把 `lang_rules` 目录直接放上 `sys.path`）。后者下
    `..` 会越界，所以退回同名顶层导入。
    """
    try:
        from .. import line_breaks
    except ImportError:
        import line_breaks
    return line_breaks


def _same_unbreakable(surf, pos, nxt_surf, nxt_pos):
    """两个相邻词是否同属一个「不该切开」的串：拉丁/数字串、专名内部。"""
    latin_a = bool(LATIN.search(surf))
    latin_b = bool(LATIN.search(nxt_surf))
    if latin_a and latin_b:
        return True
    if "固有名詞" in pos and "固有名詞" in nxt_pos:
        return True
    return False


def _root():
    import os as _os
    here = _os.path.dirname(_os.path.abspath(__file__))       # src/text/lang_rules
    return _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(here))))


class JaSegmenter(S.Segmenter):
    """日文分词器：janome → fugashi → 无（无分词器时助词空格退回正则版）。"""
    def __init__(self):
        self.name = _tagger().name

    def tag(self, text):
        return _tagger().tag(text)


class JaParticleSpacing(S.Spacing):
    """日文补空格：形态素判「名詞/代名詞/数詞 + 助詞」，在助词后加一格。

    它必须发生在标点规范化**之前**（`pre_punct`）：标点自己也会加空格，
    顺序反了会和标点空格互相干扰。
    """

    mode = "particle"

    def __init__(self, segmenter):
        self.segmenter = segmenter

    def pre_punct(self, text):
        return space_particles_analyzer(text, self.segmenter)


def spec():
    """给 engine_text / apply_*_rules 用的语言声明。"""
    seg = JaSegmenter()
    return S.LangSpec(
        code=LANG,
        punct=S.Punctuation(normalize_punct, {"lang": LANG, **PUNCT}),
        segmenter=seg,
        spacing=JaParticleSpacing(seg),
        linebreak=JaLineBreak(),
    )


