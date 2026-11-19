#!/usr/bin/env python3
# coding: utf-8
"""text_lint.py —— 把复查里已经定下的译文定则做成可重跑的检查。

原名 zh_lint.py，因检查范围早已扩到六语（模板、占位、标注、空值、同原文异译
对所有语言都适用，只有标点与引号几类是中文专有），更名为 text_lint.py。

判据全部来自 docs/界面映射/09-推断-连续键区.md 里已经落卷的结论，
这里只负责机械复核，不做判断。分级：

  E（必改）：模板与原文不一致、汉字旁的半角标点、直引号、`・`、空值
  W（提示）：本段新定则里「建议但历史遗留较多」的几类

已知豁免（写进来是为了不误报，不是放宽标准）：
  · 字体资源可换中文字形变体（`…aaFH.res` ↔ `…aaFHk.res`，09 卷定则）
  · `0xfc512ea5` 版权声明按 KEEP_ORIGINAL 保留英文原文
  · 纯符号／纯数字条目（字符清单、`,` 这种单标点）不进中文规则
  · 千分位 `1,000` 不算半角逗号
  · 含 `%` 或 `<` 的引擎格式串不算「连续空格」

    python src/tools/analysis/text_lint.py            # 摘要
    python src/tools/analysis/text_lint.py --all      # 打印全部命中
    python src/tools/analysis/text_lint.py --lang de  # 换一门语言跑模板类检查

退出码：有 E 级命中时返回 1。
"""

import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

EN = os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")
TR = os.path.join(ROOT, "src", "translations", "%s.toml")

# 模板只比「会被引擎解释的东西」：%N、@x$Name$、<n>/<c>/<t>/<ts:N>/<gs:…> 一类。
# 字体资源 <f:…> 不进模板（允许按字形替换，见 09 卷定则），另按资源名单独检查。
TPL = re.compile(r"%[0-9]+|@[a-zA-Z]\$[^$]*\$|<(?:n|c|t|ts:[0-9]+|gs:[^>]*|r|b)>|<\.[^>]*>")
FONT = re.compile(r"<f:([^>]*)>")
HAN = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]")
MARK_ANY = re.compile(r"\[(?:town|lit|term):?")
ANS_MARK = re.compile(r"\[riddle:")
# 站内变量 @x$Name$：x 是格式码。同一个变量在整份语料里几乎只有一种码，出现孤例多半是
# 原文笔误被逐语照抄（0xca4930dc 的 @A$Amount$ 就是：同文件 55 处 @a$Amount$）。
VAR_CODE = re.compile(r"@([A-Za-z])\$([A-Za-z0-9_]+)\$")
# 这几个变量的码本来就是一词多形：Pos 的 d/l/r/M 是方位，USER 的 A/s 是称呼与署名。
VAR_CODE_MULTI = {"Pos", "USER"}
# 已知与主流不一致、但暂随原文的键：0xca4930dc 的 @A$Amount$。同一变量全文 55 处写 @a$，
# 只有这一行（英文原文起、各语照抄）写 @A$。引擎是否区分这个字母没有证据，先不改原文口气；
# 等实机对照后再决定，豁免只收这一个键。
VAR_CODE_ORIG = {"0xca4930dc"}

KEEP = set()

#: 有意不译清单与术语表。两者都在 src/data 下，按语言分文件。
KEEP_DIR = os.path.join(ROOT, "src", "data", "keep_as_is")
TERMS_DIR = os.path.join(ROOT, "src", "data", "terms")


def load_keep(lang):
    """{id: 理由}；读 `_common.txt`（七语共用）再读 `<lang>.txt`，后者覆盖前者。"""
    out = {}
    for name in ("_common.txt", lang + ".txt"):
        path = os.path.join(KEEP_DIR, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    out[parts[0].strip()] = parts[1].strip()
    return out


def _allow_ids(lang):
    """术语检查的例外 id（专名、固定短语）。`src/data/terms/allow_<lang>.txt`。"""
    path = os.path.join(TERMS_DIR, "allow_%s.txt" % lang)
    if not os.path.exists(path):
        return set()
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.add(line.split()[0])
    return out


def load_allow_same_src(lang):
    """「同原文异译」的例外：同一句英文对应两条用途不同的条目。

    `src/data/allow_same_src_<lang>.txt`，一行一条 id，注释写为什么。
    """
    path = os.path.join(ROOT, "src", "data", "allow_same_src_%s.txt" % lang)
    if not os.path.exists(path):
        return set()
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.add(line.split()[0])
    return out


def _enforce_keys(lang):
    """要强制落词的术语键。`src/data/terms/enforce_<lang>.txt`，一行一个键。

    没这个文件就完全不查：术语表里很多键只是「参考用」，并未与译文约定统一
    （es 的 Pirata、ja 的 バッカニア 就与正文用词不同）。强求会和现实打架，
    报出来的几十条没人处理，检查就失去意义。只在对齐过的语言上开。
    """
    path = os.path.join(TERMS_DIR, "enforce_%s.txt" % lang)
    if not os.path.exists(path):
        return None
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.add(line.split()[0])
    return out


def load_terms(lang):
    """[(键, 英文词, 本语译词)]；值为空的不算。键形如 `en_governor`。"""
    path = os.path.join(TERMS_DIR, lang + ".toml")
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    out = []
    for key, val in doc.items():
        if not isinstance(val, str) or not val.strip():
            continue
        prefix, _, rest = key.partition("_")
        if prefix != "en" or not rest:
            continue
        out.append((key, rest.replace("_", " "), val.strip()))
    return out

# 货物数量的量词：全库统一「桶」。判据不是约定，而是模板自带的两处硬证据——
# 送货换钱的十条任务文本同时含 `@g$GoldPerBarrel$`（变量名直译「每桶金币价」）
# 与 `<g:INTEXT_FASS_800x600.screen>`（FASS = 德语的桶，渲染成一张桶的图片），
# 插在「每交付一__就能拿到每桶价」的位置；德/英原文写的是 Fass / barrel。
# 所以数量变量后面的量词只能是桶：写「单位」「份」这类泛称、或干脆不写（`@a$Amount$的
# 朗姆酒` 会被渲成「10 的朗姆酒」），都算偏离。检查是全域的：全库 56 处 @a$Amount$
# 全是货物数量，没有一处例外。
AMT_VAR = re.compile(r"@[aA]\$Amount\$")
BAD_AMT_UNIT = re.compile(r"@[aA]\$Amount\$(?:单位|份|件|担|公斤|箱)")
# 别的语言只在「桶模板族」里查：这批文本同屏带每桶价与桶图，数量单位必须是本语的
# 「桶」。不能全域硬卡——日语「10ずつ」「10個」语法合法，西语「10 de mercancía」
# 是合法的部分量表达，俄语数词直接管名词二格，都不需要量词。
BARREL_HINT = re.compile(r"@g\$GoldPerBarrel\$|INTEXT_FASS")

sys.path.insert(0, os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from shared.core.validate import is_identifier, tag_literals  # noqa: E402
from text import marks as MK  # noqa: E402
import terms_check as TC  # noqa: E402


def norm_font(v):
    """把原文里坏掉的标签归一到合法写法（英文 0x103b68ea 的 `<.<n>` 是笔误）。"""
    return re.sub(r"<\.[^>]*>", "<n>", v)


def tpl_set(v):
    return sorted(TPL.findall(norm_font(v)))


def half_width_punct(v):
    """只在汉字紧邻半角标点时报；千分位、英文缩写里的逗号不算。"""
    hits = []
    if re.search(r"[\u4e00-\u9fff）)」”]\s*,", v):
        hits.append("半角逗号")
    if re.search(r",\s*[\u4e00-\u9fff]", v):
        hits.append("半角逗号")
    if re.search(r"[\u4e00-\u9fff）)」”]\s*\.(?![0-9])", v):
        hits.append("半角句号")
    if re.search(r"\.\s*[\u4e00-\u9fff]", v):
        hits.append("半角句号")
    return sorted(set(hits))


# ---------------------------------------------------------------------------
# 非中文的语言层检查。原则：只做「判据由字形/音形决定、不依赖句法」的规则，
# 一律 W 级——报出来代表「与主流写法不同」，不是「错」；参照语言（de/fr/es/ru）
# 的译文不改，所以这些提示只留痕。
#
# 试过但未采纳（实测误报率过高，留在注释里省得以后再试一遍）：
#   · de 名词未大写：用「句中大写词自建名词表」去查小写形式，38 条命中全是
#     einen neuen / die eine 这类形容词、代词，自建词表没法分名词与动词变位；
#   · fr 漏省音：`le e` / `de   e` 这类命中全部来自被剥掉的 [town:…] 标注与 %1，
#     不是真漏省音；
#   · ja 助词连用：格助词相邻 9 条，へと / をと / ノといった 都合法，
#     真正的错（をを、はが）在这批语料里没有。
# ---------------------------------------------------------------------------

PH_ANY = re.compile(r"@[a-zA-Z]\$[^$]*\$|%[0-9]+|<[^>]*>")
# 占位符后写并列助词（을(를)、은(는)…）是合规做法：运行时替换值末音节未知时用
PH_PAIR = re.compile(r"(@[a-zA-Z]\$[^$]*\$|%[0-9]+)(을\(를\)|를\(을\)|은\(는\)|는\(은\)|"
                     r"이\(가\)|가\(이\)|와\(과\)|과\(와\)|으로\(로\)|로\(으로\))")
PH_BARE = re.compile(r"(@[a-zA-Z]\$[^$]*\$|%[0-9]+)(을|를|은|는|이|가|와|과|으로|로)(?![가-힣(])")
JOSA_PAIR = {"JKS": ("이", "가"), "JKO": ("을", "를"),
             "JX": ("은", "는"), "JKC": ("과", "와")}
FILLER = "\u25cb"          # 占位符掩码：禾…不用；○ 不含收音，不影响掩码后的助词判定
_KIWI = []


def jong(ch):
    """韩语音节末是否有收音；非谚文返回 None。"""
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3:
        return (o - 0xAC00) % 28 != 0
    return None


def _kiwi():
    """Kiwi 实例（缺包返回 None）。与 ko_checks 共用，避免重复加载模型。"""
    if not _KIWI:
        try:
            from kiwipiepy import Kiwi
        except Exception:
            return None
        _KIWI.append(Kiwi())
    return _KIWI[0]


def ko_checks(tr, W):
    """韩语：占位符后接助词（必改）+ 助词收音一致性（需 Kiwi，缺包自动跳过）。"""
    for k, v in tr.items():
        if k in KEEP or not v:
            continue
        # 逐处判。以前是「整条里出现过并列形就跳过整条」，于是
        # `@T$TOWN$이(가) … @T$Town$으로` 这种半对半错的条目两头都查不到。
        # PH_BARE 自带 `(?![가-힣(])`，并列形本身不会被误抓。
        for m in PH_BARE.finditer(v):
            W.append((k, "占位符后接助词",
                      "%s（替换值末音节未知；改写句式或写并列形）" % m.group(0)))

    kiwi = _kiwi()
    if kiwi is None:
        return
    for k, v in tr.items():
        if k in KEEP or not v:
            continue
        toks = kiwi.tokenize(PH_ANY.sub(FILLER, v))
        for i, t in enumerate(toks):
            pair = JOSA_PAIR.get(t.tag)
            if not pair or t.form not in pair or i == 0:
                continue
            prev = toks[i - 1]
            if prev.form == FILLER or prev.tag in ("SY", "SW", "SN", "SL", "SS", "UNK", "SF"):
                continue
            has = jong(prev.form[-1])
            if has is None:
                continue
            want = pair[0] if has else pair[1]
            if t.form != want:
                W.append((k, "助词收音", "%s 应为 %s%s" % (prev.form + t.form, prev.form, want)))


#: 韩语量词（只认由数词位引导、且是独立词元的那些；正则子串会把
#: 「대출」「대륙」「대신」里的「대」算成量词，616 处命中里 520 处是这种）。
KO_COUNTERS = {"개", "척", "통", "명", "대", "병", "자루", "상자", "채", "장", "권", "마리"}
#: 量词检查只掩码**占位符**；标签 `<t>` 一律抹成空格。用 `PH_ANY` 连标签一起
#: 掩成 ○，`<t>배` 会被当成「数词 + 배」（0x2ca2d7bd 就是这么误报的）。
KO_UNIT_PH = re.compile(r"@[a-zA-Z]\$[^$]*\$|%[0-9]+")
KO_UNIT_TAG = re.compile(r"<[^>]*>")
#: 必须带量词的可数名词 → 该用的量词。**只列白名单里的名词**：
#: 黑名单（「量词后面不是这些就报」）会把 `%1 대연회`（大宴会，不是「两台」）
#: 、`럼주 한 병 시켜`（一瓶朗姆酒，병 是量词但后面接动词）全判成错。
KO_REQUIRE = {"배": "척", "선박": "척", "함": "척", "배들": "척",
              "선원": "명", "병사": "명", "정착민": "명", "주민": "명",
              "사람": "명", "용병": "명",
              "물자": "통", "화물": "통", "곡물": "통", "목재": "통",
              "의류": "통", "상품": "통", "물품": "통",
              "상자": "개", "포": "대", "대포": "대"}
#: 白名单里**故意不收** `선장`：英文 `Captain %1 assembles…` 里的 %1 是船长名字，
#: 韩语照「이름 + 직함」写 `%1 선장이` 是合规的（存量 2 条正是这种，曾被判成
#: 「缺 명」）。只有确实表示人数时才该有量词，而那时 %1 也不跟在 선장 后面。


def ko_unit_checks(tr):
    """韩语：数量词位的量词缺失与搭配错（E 级）。

    只做两件机械判据（数词、量词必须都是 Kiwi 的独立词元，子串不算）：

      1. 缺量词：`%1 배` / `3 척` 里的数词位后直接是白名单名词，中间没量词 ——
         `%1 배` 会渲成「10 배」。
      2. 搭配错：数词 + 量词 + 名词，但名词要的不是这个量词 ——
         `5척의 병사`（兵用 척）、`3개의 배`（船用 개）。

    数词位只认**占位符与阿拉伯数字**。固有数词（한/두/여러）不进判据：
    `두 배로 늘었`（翻倍）、`한 사람`（一个人）、`여러 배`（好几倍）在韩语里
    本来就是词，不是「两艘船」；把衬词当数词会先在库存里刷出 5 条误报。
    标签按段切开再分词，否则 `물자:<t>%2<n>대포:<t>%3` 会把 %2 与下一行的
    대포 拼成「N 대포」（0xd23b7fdf 两条就是这么误报的）。
    存量 3090 条实测 0 命中：数词位 1973 处里 112 处带量词，其余紧跟的都是
    助词（의 66 / 이 57 / 을 42 / 에서 38 …）。这两条是给后续批次设的栅栏。
    """
    kiwi = _kiwi()
    if kiwi is None:
        return []
    out = []
    for k, v in tr.items():
        if k in KEEP or not v:
            continue
        # 按标签切段：`물자:<t>%2<n>대포:<t>%3` 这种损失清单是「标签 + 数字」，
        # 整段一起分词会让 %2 与下一行的「대포」相邻，误判成「N 대포」缺量词。
        for seg in KO_UNIT_TAG.split(KO_UNIT_PH.sub(FILLER, v)):
            toks = kiwi.tokenize(seg)
            for i, t in enumerate(toks):
                is_num = t.form == FILLER or t.tag == "SN"
                if not is_num or i + 1 >= len(toks):
                    continue
                nxt = toks[i + 1]
                want = KO_REQUIRE.get(nxt.form)
                if want is not None:                      # 数词 + 裸名词
                    out.append((k, "缺量词", "%s（应带 %s）" % (t.form + nxt.form, want)))
                    continue
                if nxt.form not in KO_COUNTERS:           # 数词 + 助词/动词，没有量词可比
                    continue
                j = i + 2
                while j < len(toks) and toks[j].form == "의":   # `3척의 배`
                    j += 1
                if j >= len(toks):
                    continue
                noun = toks[j].form
                need = KO_REQUIRE.get(noun)
                if need is not None and need != nxt.form:
                    out.append((k, "量词搭配错",
                                "%s（%s 用 %s）" % (t.form + nxt.form + noun, noun, need)))
    return out


JA_POLITE = {"ます", "です", "ました", "でした", "ません", "ましょう", "ください",
             "でしょう", "ませんでした", "ましょうか", "でしょうか"}
JA_PLAIN = {"だ", "である", "だった", "だろう", "ではない", "じゃない", "じゃ"}


def ja_checks(tr, W):
    """日语：同一条译文内 です/ます体 与 だ体 混用（引文与语气词会有误报，只做提示）。"""
    try:
        from janome.tokenizer import Tokenizer
    except Exception:
        return
    tk = Tokenizer()

    def kind(sent):
        toks = [t for t in tk.tokenize(sent) if t.surface.strip()]
        for t in reversed(toks):
            if t.part_of_speech.split(",")[0] in ("動詞", "助動詞", "形容詞", "形容動詞"):
                for p in JA_POLITE:
                    if t.surface.endswith(p):
                        return "polite"
                for p in JA_PLAIN:
                    if t.surface == p or t.surface.endswith(p):
                        return "plain"
                return None
        return None

    for k, v in tr.items():
        if k in KEEP or not v:
            continue
        kinds = [kind(x) for x in re.split(r"[。！？]", MARK_ANY.sub(" ", v)) if x.strip()]
        kinds = [x for x in kinds if x]
        if len(set(kinds)) > 1:
            W.append((k, "语体混用", " / ".join(kinds)))


def es_checks(tr, W):
    """西语：¿¡ 与 ?! 必须成对，感叹句/疑问句缺倒置符号。"""
    for k, v in tr.items():
        if k in KEEP or not v:
            continue
        s = MARK_ANY.sub(" ", v)
        if s.count("¿") != s.count("?") or s.count("¡") != s.count("!"):
            W.append((k, "倒置符号不配对", "¿%d ?%d ¡%d !%d"
                      % (s.count("¿"), s.count("?"), s.count("¡"), s.count("!"))))


def ja_unit_checks(tr):
    """日语：桶模板族里数量变量必须带量词「樽」（E 级）。

    只卡这批文本（同屏有每桶价 + 桶图），因为日语此处不能省量词：
    `@a$Amount$を届けて` 会渲成「10を届けて」。别的位置「10ずつ」「10個」合法，不查。
    """
    out = []
    for k, v in tr.items():
        if k in KEEP or not v or not BARREL_HINT.search(v):
            continue
        for m in AMT_VAR.finditer(v):
            if not v[m.end():].lstrip().startswith("樽"):
                out.append((k, "缺樽量词", v[max(0, m.start() - 8):m.end() + 10]))
    return out


def fr_unit_checks(tr):
    """法语：桶模板族里数量变量必须带 `tonneaux`（E 级）。

    「Livrez 10 d'outils」不成立，法语必须给量词；全库已用 tonneaux 18 条，口径一致。
    """
    out = []
    for k, v in tr.items():
        if k in KEEP or not v or not BARREL_HINT.search(v):
            continue
        for m in AMT_VAR.finditer(v):
            if not v[m.end():].lstrip().startswith("tonneau"):
                out.append((k, "缺 tonneaux 量词", v[max(0, m.start() - 8):m.end() + 12]))
    return out


def fr_space_checks(tr):
    """法语：不准引进特殊空白字符（U+00A0 及其它非 U+0020 空白）——E 级。

    口径来自用户：法语标点前那一格保持作者写的普通空格，不换成 NBSP，也不换成
    窄空格 / 零宽空格。这条规则就是那条口径的守卫：任何人把 NBSP 写回 fr.toml，
    复核直接失败。构建期同样不加工法语（`lang_rules/fr.py` 透传）。
    """
    spaces = re.compile("[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\u200b\ufeff\u2060]")
    out = []
    for k, v in tr.items():
        if k in KEEP or not v:
            continue
        for m in spaces.finditer(v):
            out.append((k, "法语不得引入特殊空格（U+%04X）" % ord(m.group(0)),
                        v[max(0, m.start() - 8):m.start() + 4]))
    return out


def keep_violations(keep, tr, en):
    """有意不译名单的反向检查，返回 W 级条目。

    两种理由的判据不同：
    - `save-name`：这条会变成**存档文件名**。PR2.exe 只导入 ANSI 版文件 API，
      名字里的非 ASCII 字节会被按 Latin-1 映射，存档写出去就是乱码文件、
      再读回来弹「存档无效」。所以它不必等于英文，但必须是纯 ASCII
      （de `Autospeichern`、fr `Sauvegarde automatique` 都合法）。
    - 其余（key / label / id / credit）：正确译法就是英文原样，值一变就是错。
    """
    W = []
    for k, why in keep.items():
        v = tr.get(k)
        if v is None:
            continue
        if why == "save-name":
            if not str(v).isascii():
                W.append((k, "存档名非 ASCII", str(v)[:60]))
        elif en.get(k) is not None and str(v).strip() != str(en[k]).strip():
            W.append((k, "名单内但已改动（%s）" % why, str(v)[:60]))
    return W


def main(argv):
    lang = "zh"
    show_all = "--all" in argv
    if "--lang" in argv:
        lang = argv[argv.index("--lang") + 1]
    en = tomllib.load(open(EN, "rb"))
    tr_raw = tomllib.load(open(TR % lang, "rb"))
    # 规则比对一律用展开后的文本：否则 [ref:Tortuga]的麻烦 与字面「托尔图加的麻烦」
    # 会被当成同原文异译。标注本身的检查另走 check_doc（用带标注原文）。
    tr = MK.expand_doc(lang, tr_raw)
    zh_mode = lang == "zh"
    # 有意不译的条目（七语共用基线 + 本语言）：语言层检查一律跳过它们
    KEEP.clear()
    KEEP.update(load_keep(lang))

    # 变量名 → 各格式码在本文里的出现次数，供逐行查孤例
    codes = {}
    for v in tr.values():
        for m in VAR_CODE.finditer(norm_font(v)):
            per = codes.setdefault(m.group(2), {})
            per[m.group(1)] = per.get(m.group(1), 0) + 1

    E, W = [], []

    for k, v in tr.items():
        if k in KEEP:
            continue
        for m in VAR_CODE.finditer(norm_font(v)):
            if k in VAR_CODE_ORIG or m.group(2) in VAR_CODE_MULTI:
                continue
            per = codes.get(m.group(2)) or {}
            top = max(per.values()) if per else 0
            if per.get(m.group(1), 0) == 1 and top >= 10:
                E.append((k, "变量码孤例",
                          "@%s$%s$（该变量本文 %d 处用 %s）"
                          % (m.group(1), m.group(2), top,
                             max(per, key=per.get))))
        src = en.get(k)
        # 纯符号／纯数字条目：字符清单、单个标点，不参与中文规则
        if zh_mode and not HAN.search(v) and not LATIN.search(v):
            if src is not None and tpl_set(v) != tpl_set(src):
                E.append((k, "模板不一致", "EN=%s | %s=%s" % (tpl_set(src), lang, tpl_set(v))))
            continue

        if src is not None and not is_identifier(src) and tpl_set(v) != tpl_set(src):
            E.append((k, "模板不一致", "EN=%s | %s=%s" % (tpl_set(src), lang, tpl_set(v))))
        if not str(v).strip():
            E.append((k, "空值", repr(v)))
        if not zh_mode:
            continue

        if "\u30fb" in v:
            E.append((k, "片假名中点・", v[:60]))
        if '"' in v:
            E.append((k, "直引号", v[:60]))
        for h in half_width_punct(v):
            E.append((k, h, v[:60]))
        if re.search(r"[0-9]+\s+[年月日天艘张名条个人次]", v):
            W.append((k, "数字与量词间有空格", v[:60]))
        if "您" in v:
            W.append((k, "称谓混用您", v[:60]))
        if "%" not in v and "<" not in v and re.search(r"[^\s<]\s{2,}[^\s>]", v.replace("<n>", "")):
            W.append((k, "连续空格", v[:60]))
        if "\u3000" in v:
            W.append((k, "全角空格", v[:60]))
        m_bad = BAD_AMT_UNIT.search(v)
        if m_bad:
            E.append((k, "量词不统一", "%s → 桶" % m_bad.group(0)))
        for m in AMT_VAR.finditer(v):
            if not v[m.end():].lstrip().startswith("桶"):
                E.append((k, "缺桶量词", v[max(0, m.start() - 8):m.end() + 12]))

    if zh_mode:
        allow_same = load_allow_same_src(lang)
        byen = {}
        for k, v in en.items():
            if k in tr:
                byen.setdefault(v, []).append(k)
        for src, keys in byen.items():
            outs = {tr[k]: k for k in keys}
            # 同一句英文对应「同名两用」时允许不同译法：Quick Save 的两条
            # 一条是 ESC 菜单木牌（可本地化），一条是存档文件名（必须 ASCII）。
            if len(outs) > 1 and len(src) > 8 and not set(keys) <= allow_same:
                W.append((sorted(keys)[0], "同原文异译 %d 种" % len(outs),
                          " / ".join(sorted(outs))[:120]))

    # 有意不译名单：按键名/表头/专名保持英文原样；存档名另有一条 —— 必须是
    # ASCII，因为引擎只用 ANSI 文件 API，非 ASCII 的文件名写出去就是乱码。
    W.extend(keep_violations(load_keep(lang), tr, en))

    # 标签字面保留：`<n>` 少一个就是丢分段，`<f:fonts/…FHk.res>` 多一个字母
    # 就是换字体。`tag_profile` 只比名字，抓不到字体路径的错；这里整段比。
    for k, v in tr.items():
        if k in KEEP or not v:
            continue
        want, got = tag_literals(en.get(k)), tag_literals(v)
        if want != got:
            W.append((k, "标签与原文不一致", "缺 %s 多 %s" % (
                "、".join(sorted(set(want) - set(got))) or "—",
                "、".join(sorted(set(got) - set(want))) or "—")))

    # 术语落词：术语表的英文词在原文出现时，译文里必须用指定译法。
    # 只在**短标签**上判（可见 ≤24 字）：长句里的同一个词是行文的一部分，
    # 「quality of life」在叙述句里写「生活水平」并不算错，全族强求会报 189 条
    # 噪音；标签才是名词即全部语义、必须与界面统一的地方。
    # 专名（Captain Bean 之类）登记在 src/data/terms/allow_<lang>.txt。
    allow = _allow_ids(lang)
    enforce = _enforce_keys(lang)
    seen_term = set()
    for key, word, val in load_terms(lang):
        if enforce is None or key not in enforce:
            continue
        rx = re.compile(r"\b%s\b" % re.escape(word), re.I)
        for k, v in tr.items():
            if k in KEEP or k in seen_term or k in allow:
                continue
            if len(str(v)) > 24:
                continue
            src = en.get(k) or ""
            if rx.search(src) and val not in str(v):
                seen_term.add(k)
                W.append((k, "术语未用「%s」" % val,
                          "原文含 %s：%s" % (word, str(v)[:50])))

    # 语言层：只挂在对得上判据的语言上；缺分析器时各函数自己静默跳过
    if lang == "ko":
        ko_checks(tr, W)
        E.extend(ko_unit_checks(tr))
    elif lang == "ja":
        ja_checks(tr, W)
        E.extend(ja_unit_checks(tr))
    elif lang == "es":
        es_checks(tr, W)
    elif lang == "fr":
        E.extend(fr_unit_checks(tr))
        E.extend(fr_space_checks(tr_raw))

    # 内联标注（[town:…] / [lit:…] / [term:…]）：未定义引用、缺形态、方括号写错、死条目
    # 自造 clue 标签（非 `_` 开头、也不是已知类型）只做关键词扫描、没有任何校验，
    # 所以走 strict_warns：在构建之前必须清零，不能降级成 W 留着。
    mwarn = []
    for p in MK.check_doc(lang, tr_raw, entities=MK.load_entities(), warns=mwarn,
                          strict_warns=True, require_ans_meta=True):
        E.append(("标注", "标注", p))

    # 诗谜整片不许挂 town/lit/term：谜面的用词由韵脚和字数决定，这几种标注会把词冻成
    # 表里的写法，谜语也被提前泄底（`Holy August` 的双关就没了）。诗里只写自由文本，
    # 谜底另走 [riddle:实体]——只给翻译人看，展开为空。
    _g, _ig, verse = TC.load_terms()
    vids = sorted(TC.verse_ids(verse, en), key=lambda x: int(x, 16))
    for k in vids:
        if MARK_ANY.search(tr_raw.get(k, "") or ""):
            E.append((k, "诗谜挂标注", tr_raw[k][:60]))
    no_ans = [k for k in vids if not ANS_MARK.search(tr_raw.get(k, "") or "")]
    if no_ans:
        W.append(("诗谜", "缺谜底 %d 条" % len(no_ans),
                  "已标 %d/%d，第一个缺：%s"
                  % (len(vids) - len(no_ans), len(vids), no_ans[0])))

    lines = []
    lines.append("# %s 机械复核（判据见 09 卷已落卷定则）\n" % lang)
    lines.append("E 级 %d 条，W 级 %d 条。\n" % (len(E), len(W)))
    for tag, items in (("E", E), ("W", W)):
        shown = items if show_all else items[:40]
        for k, why, ctx in shown:
            lines.append("%s %-12s %-16s %s" % (tag, k, why, ctx))
        if len(items) > len(shown):
            lines.append("（%s 级另有 %d 条，用 --all 看全）" % (tag, len(items) - len(shown)))

    text = "\n".join(lines) + "\n"
    print(text)
    out = os.path.join(ROOT, "build", "qa", "text_lint_%s.txt" % lang)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, "w", encoding="utf-8", newline="").write(text)
    print("报告：%s" % os.path.relpath(out, ROOT))
    return 1 if E else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
