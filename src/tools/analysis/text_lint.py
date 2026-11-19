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

KEEP = {"0xfc512ea5"}

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
from shared.core.validate import is_identifier  # noqa: E402
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


def ko_checks(tr, W):
    """韩语：占位符后接助词（必改）+ 助词收音一致性（需 Kiwi，缺包自动跳过）。"""
    for k, v in tr.items():
        if k in KEEP or not v:
            continue
        if PH_PAIR.search(v):
            continue
        m = PH_BARE.search(v)
        if m:
            W.append((k, "占位符后接助词",
                      "%s（替换值末音节未知；改写句式或写并列形）" % m.group(0)))

    if not _KIWI:
        try:
            from kiwipiepy import Kiwi
        except Exception:
            return
        _KIWI.append(Kiwi())
    kiwi = _KIWI[0]
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
        byen = {}
        for k, v in en.items():
            if k in tr:
                byen.setdefault(v, []).append(k)
        for src, keys in byen.items():
            outs = {tr[k]: k for k in keys}
            if len(outs) > 1 and len(src) > 8:
                W.append((sorted(keys)[0], "同原文异译 %d 种" % len(outs),
                          " / ".join(sorted(outs))[:120]))

    # 语言层：只挂在对得上判据的语言上；缺分析器时各函数自己静默跳过
    if lang == "ko":
        ko_checks(tr, W)
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
