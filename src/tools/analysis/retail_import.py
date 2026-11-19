"""把官方零售版参照落进译文，并把标注层一起搬过去。

为什么要有这个脚本
------------------
`translate.py apply` 只会「把一份映射写进译文」，它不知道零售版参照在哪、
更不知道标注层。pl 那一轮是 `build/pl_retail_map.py` 一次性脚本干的，而且只做
最窄的一件事：**只填还没译的行**（现值等于英文的行）。换一门语言立刻就漏两件：

1. **替换已译**：es 有 1477 行与零售不同，其中 1400 行是整句改写 —— 不是「没译」，
   是「译过、但不如零售」。只填未译行的脚本对这 1400 行一个字都不动。
2. **承标注**：现译里有 `[town:Biloxi]`、`[term:en_tools]` 这类标注，零售文本是
   纯文本，一条标注都没有。整行覆盖等于把标注层抹掉，而标注层是给 `text/marks.py`
   消费的（地名按译名表展开、术语按术语表展开），抹掉之后校名识别和诗谜 clue
   都会跟着坏。

所以这里做两件事：把零售文本按标注**逐个搬回去**，再交给 `apply_map` 落盘——
占位符与标签的校验仍在 `apply_map` 里，一份实现，不在这里重复。

承标注的规则（宁可放弃，不猜）
------------------------------
标注 `[town:X]` 的参数不是显示文本，是译名表里的键；显示文本要用 `marks.expand`
按本语言的 names 表解析（`[town:St. Augustine]` 在 es 里展开成 `San Agustín`）。
所以搬运方法是「按展开结果定位」：先算出这条标注会显示的字符串，再在零售文本里
找它，找到且**只出现一次**就把那个片段换回标注本身。找不到、或出现多次，这行就
整条放弃并报「标注对不上」——位置猜错会把地名套到别的词上，那比不导更糟。

诗谜（`[riddle:…]`）与引用（`[ref:…]`）不在这条路上：前者要重算 clue 并逐字核对，
后者会牵出另一条文本，都该走 `riddle_marks` 与人工，这里整行跳过并计数。
"""

import argparse
import io
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import translate as T  # noqa: E402
from text import marks as MK  # noqa: E402

#: 一条标注的完整写法：`[key:arg]`。arg 里允许再出现冒号（`ref:键`）与斜杠（形态）。
MARK_RX = re.compile(r"\[(ref|town|lit|term|riddle):([^\[\]]{1,200})\]")
#: 判「要不要绕开」只认前缀，不看 arg 多长：诗谜的 arg 里带 `source=…@sha256=…`，
#: 上千字都有，用带上限的 MARK_RX 去找会漏掉，整行就被当成没标注覆盖掉了。
DEFER_RX = re.compile(r"\[(riddle|ref):")
#: 需要绕开的两类标注：诗谜要重算 clue，引用牵出另一条文本。
DEFER_KEYS = ("riddle", "ref")
OUT_DIR = os.path.join(T.ROOT, "build", "qa")


def load(path):
    import tomllib
    with io.open(path, "rb") as f:
        return tomllib.load(f)


def resolve_path(ref):
    """`--ref` 既收短名（es.retail-1.0.0）也收路径。"""
    if os.path.isfile(ref):
        return ref
    cand = T.lang_path(ref)
    if os.path.isfile(cand):
        return cand
    raise SystemExit("找不到参照：%s（也不在 src\\orig\\ 下）" % ref)


# ---------------------------------------------------------------- 语言判定

#: 领词用的形态词典（`src/data/qa/dict/<base>.aff|.dic`，与 lang_check 同一份）。
#: 位置按仓库根算，不跟 `set_src` 走：测试会把数据根指到临时目录，词典不该跟着消失。
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "..", ".."))
DICT_DIR = os.path.join(REPO_ROOT, "src", "data", "qa", "dict")
DICT_BASE = {"de": "de_DE_frami", "fr": "fr_FR", "es": "es_ES", "ru": "ru_RU", "pl": "pl_PL"}
#: 判语言前先抹掉的东西：令牌、标签、标注。长诗谜标注也一并抹掉。
MASK_RX = re.compile(r"%[0-9]+|@[a-zA-Z]\$[^$]*\$|<[^<>]*>|\[[^\[\]]*\]")
WORD_RX = re.compile(r"[^\W\d_]{2,}")
_LEXICON = {}


def lexicon(lang):
    """`known(词) -> bool`；没词典就返回 None —— 那时不判语言，宁可放过也不错杀。"""
    if lang in _LEXICON:
        return _LEXICON[lang]
    base = DICT_BASE.get(lang)
    path = os.path.join(DICT_DIR, base or "")
    fn = None
    if base and os.path.isfile(path + ".dic"):
        try:
            from spylls.hunspell import Dictionary
            hd = Dictionary.from_files(path)
        except Exception:                  # 词典坏了／没装 spylls：不判
            hd = None
        if hd is not None:
            fn = lambda w: bool(hd.lookup(w) or hd.lookup(w.capitalize())
                                or hd.lookup(w.lower()))  # noqa: E731
    _LEXICON[lang] = fn
    return fn


def foreign_words(text, known, min_words=8, floor=0.30):
    """返回 (词典认得的词数, 词数)；不足 `min_words` 或比例高于 `floor` 时返回 None。

    这一步是给「零售文件里混进另一门语言」留的闸：es 参照里真有一行是德语原文，
    结构、令牌全对，只有词不是西语，`apply` 那套按文字种类的检查对拉丁字母束手无策。
    判据只用词典命中率，不用 n-gram 之类说不清的东西。
    """
    if known is None:
        return None
    words = WORD_RX.findall(MASK_RX.sub(" ", text))
    if len(words) < min_words:
        return None
    hit = sum(1 for w in words if known(w))
    if hit / float(len(words)) >= floor:
        return None
    return hit, len(words)


def carried(cur, ref, resolve):
    """把 `cur` 里的标注搬到 `ref` 上。返回 (合并后的文本, 放弃原因或 None)。

    `resolve` 是 `(标注原文, id) -> 该标注的显示文本`，由调用方按语言注入；
    测试里换成字面表即可，不需要真的读译名表。
    """
    if "[" in ref or "]" in ref:
        return None, "参照自带方括号，不敢动"
    deferred = DEFER_RX.search(cur)
    if deferred:
        return None, "含 [%s:…]，要另一道工序" % deferred.group(1)
    out = ref
    for key, arg in MARK_RX.findall(cur):
        span = "[%s:%s]" % (key, arg)
        shown = resolve(span, "")
        if not shown:
            return None, "标注 %s 展开为空" % span
        n = out.count(shown)
        if n == 0:
            return None, "标注 %s 的显示文本不在参照里" % span
        if n > 1:
            return None, "标注 %s 的显示文本在参照里出现 %d 次" % (span, n)
        out = out.replace(shown, span, 1)
    return out, None


# ---------------------------------------------------------------- 结构修复

TAG_RX = re.compile(r"<[^<>]{1,60}>")
TOK_RX = re.compile(r"%[0-9]+|@[A-Z]\$[A-Za-z0-9_$]+\$")
RUN_RX = re.compile(r"(?:<n>)+")
SENT_END_RX = re.compile(r"[.!?:»”\"](?=\s|<|$)")


def _segments(text):
    """按 `<n>` 串切段，返回 [(起, 止, 文本)]。"""
    segs, prev = [], 0
    for m in RUN_RX.finditer(text):
        segs.append((prev, m.start()))
        prev = m.end()
    segs.append((prev, len(text)))
    return [(a, b, text[a:b]) for a, b in segs]


def _insert_n(text, k, unit="<n>"):
    """在最长的段里按句末插入 k 个换行单元——不拆句，也不贴着已有的换行堆。"""
    for _ in range(k):
        segs = _segments(text)
        a, b, seg = max(segs, key=lambda s: len(s[2]))
        ends = [a + m.end() for m in SENT_END_RX.finditer(seg)]
        mid = a + len(seg) / 2
        cands = [p for p in ends if p - a > 6 and b - p > 6]
        if not cands:
            return text
        pos = min(cands, key=lambda p: abs(p - mid))
        text = text[:pos] + unit + text[pos:].lstrip(" ")
    return text


def _strip_n(text, k):
    """删 k 个 `<n>`：从最长段前面那个换行串里删，接缝处留一个空格。"""
    for _ in range(k):
        runs = list(RUN_RX.finditer(text))
        if not runs:
            return text
        segs = _segments(text)
        starts = [m.start() for m in runs]
        after = [(starts[i], len(segs[i + 1][2])) for i in range(len(starts))]
        pos, _ = max(after, key=lambda x: x[1])
        head = text[:pos].rstrip(" ")
        tail = text[pos + 3:].lstrip(" ")
        sep = "" if (not head or not tail
                     or tail.startswith(("<", ",", ".", ";", ":", "!", "?"))) else " "
        text = head + sep + tail
    return text


def _nth_occurrence(text, tag, n):
    """`tag` 在 `text` 里的第 n 个（从 1 起）起点；不够就 -1。"""
    pos = -1
    for _ in range(n):
        pos = text.find(tag, pos + 1)
        if pos < 0:
            return -1
    return pos


def _restore_bullets(base, out, need):
    """基准里写成 `标签-<t>` 的项目符号，零售连破折号一起去掉了：按基准的次序补回。

    补的是布局符号（项目符号），不是词：基准这一条本来就在这儿画一个破折号加一个制表
    位，本语言的译文只是把它丢了。位置按「同一标签的第几处」对齐——同一标签会在一行里
    出现好几次，只按「下一处还没跟符号」找会把三处全塞在第一处。
    """
    fixed = 0
    for m in re.finditer(r"(<[^<>]{1,60}>)-<t>", base):
        if fixed >= need:
            break
        tag = m.group(1)
        nth = base.count(tag, 0, m.end())          # 这一处是该标签的第几处（从 1 起）
        at = _nth_occurrence(out, tag, nth)
        if at < 0:
            continue
        pos = at + len(tag)
        if out[pos:pos + 3] == "<t>" or out[pos:pos + 4] == "-<t>":
            continue
        out = out[:pos] + "-<t>" + out[pos:]
        fixed += 1
    return out, fixed


def repair_tags(base, text):
    """只调 `<n>` 与 `<t>`：段落数按基准对齐、项目符号补回；一个字不动。

    能用机械规则修的只有这两样：零售 1.0.0 常把两段并成一段（`<n><n>` 写成一个
    `<n>`），或把列表前的 `-<t>` 去掉（连破折号一起）。字体标签、`<c>`、`<n:25>` 与
    令牌不对就不动——那些要么是内容缺了，要么得人给成分，猜不得。

    返回 (修好的文本, 说明) 或 (None, 放弃原因)。
    """
    out, notes = text, []
    need_t = base.count("<t>") - out.count("<t>")
    if need_t > 0:
        fixed = 0
        for m in list(re.finditer(r"-(?!<t>)", out)):
            if fixed < need_t:
                out = out[:m.end()] + "<t>" + out[m.end():]
                fixed += 1
        if fixed < need_t:
            out, more = _restore_bullets(base, out, need_t - fixed)
            fixed += more
        if fixed:
            notes.append("补 <t> %d" % fixed)
    delta = base.count("<n>") - out.count("<n>")
    if delta > 0:
        out = _insert_n(out, delta // 2, "<n><n>")   # 差额成对时补一整个段落
        if delta % 2:
            out = _insert_n(out, 1)
        notes.append("补 <n> %d" % delta)
    elif delta < 0:
        out = _strip_n(out, -delta)
        notes.append("删 <n> %d" % -delta)
    for name in set(TAG_RX.findall(base)) | set(TAG_RX.findall(out)):
        if out.count(name) != base.count(name):
            return None, "标签 %s 个数仍不齐" % name
    for name in set(TOK_RX.findall(base)) | set(TOK_RX.findall(out)):
        if out.count(name) != base.count(name):
            return None, "令牌 %s 个数仍不齐（要人补成分）" % name
    return out, "、".join(notes) or "无改动"


def build(lang, ref_name, only_empty=False):
    en = load(T.lang_path(T.BASE_LANG))
    cur = load(T.lang_path(lang))
    ref = load(resolve_path(ref_name))
    keep = set(T.keep_as_is(lang))
    table = MK.load_names(lang)
    terms = MK.load_terms(lang)
    known = lexicon(lang)

    mapping, why = {}, {}

    def note(hid, reason):
        why.setdefault(reason, []).append(hid)

    for hid, src in en.items():
        now = cur.get(hid, "")
        rv = ref.get(hid)
        if hid in keep:
            note(hid, "不译名单")
            continue
        if rv is None:
            note(hid, "参照里没有这条")
            continue
        rv = str(rv)
        if not rv.strip():
            note(hid, "参照为空")
            continue
        seen = foreign_words(rv, known)
        if seen:
            note(hid, "参照这一行不是目标语言（词典只认得 %d/%d 个词）" % seen)
            continue
        if rv.strip() == str(src).strip():
            note(hid, "参照没翻（等于英文）")
            continue
        if only_empty and now.strip() != str(src).strip():
            note(hid, "已有译文")
            continue
        if now == rv:
            note(hid, "与参照已一致")
            continue
        if "[" in now:
            try:
                body, reason = carried(now, rv, lambda s, h: MK.expand(
                    s, table, lang, h or hid, terms=terms, doc=cur))
            except MK.MarkError:
                note(hid, "标注展开失败（译名表或术语表缺条目）")
                continue
            if reason:
                note(hid, reason)
                continue
            rv = body
        mapping[hid] = rv
    return mapping, why


def structure_off(base, text):
    """标签或令牌的个数与基准不一致。"""
    from collections import Counter
    return (Counter(TAG_RX.findall(base)) != Counter(TAG_RX.findall(text))
            or Counter(TOK_RX.findall(base)) != Counter(TOK_RX.findall(text)))


def repair_map(lang, mapping):
    """对结构不对的行套 `repair_tags`，返回 (改过的映射, 说明列表)。

    令牌仍不齐（要人补成分）的行**留在报告里不动**，让 `apply` 继续拦住它们。
    """
    en = load(T.lang_path(T.BASE_LANG))
    notes, out = [], dict(mapping)
    for hid, val in sorted(mapping.items()):
        base = str(en.get(hid, ""))
        if not base or not structure_off(base, val):
            continue
        fixed, note = repair_tags(base, val)
        if fixed is None:
            notes.append((hid, "修不了：" + note))
        elif fixed == val:
            notes.append((hid, "结构已齐，不用改"))
        else:
            out[hid] = fixed
            notes.append((hid, note))
    return out, notes


def render(lang, ref_name, mapping, why, stats, repairs=()):
    lines = ["# 零售参照导入：%s ← %s" % (lang, ref_name), ""]
    lines.append("候选 %d 条；apply 可落 %d 条、拦住 %d 条（令牌 %d、标签 %d、助词 %d、"
                 "非本语言 %d、并列次序 %d）"
                 % (len(mapping), stats.get("hit", 0), stats.get("skipped", 0),
                    len(stats.get("tokens", [])), len(stats.get("tag", [])),
                    len(stats.get("josa", [])), len(stats.get("lang", [])),
                    len(stats.get("pair", []))))
    lines.append("")
    lines.append("## 没进映射的行（按原因分流）")
    for reason, ids in sorted(why.items(), key=lambda kv: -len(kv[1])):
        lines.append("  %-24s %4d   %s" % (reason, len(ids), " ".join(ids[:6]))
                     + (" …" if len(ids) > 6 else ""))
    if repairs:
        lines.append("")
        lines.append("## 结构修复（--repair，只调 `<n>`／`<t>`，不改字）")
        for hid, note in repairs:
            lines.append("  %s  %s" % (hid, note))
    rows = []
    for key, label in (("tokens", "令牌"), ("tag", "标签"), ("pair", "并列"),
                       ("josa", "助词"), ("lang", "非本语言")):
        for row in stats.get(key, []) or []:
            rows.append("%-6s %s" % (label, row if isinstance(row, str) else str(row)))
    if rows:
        lines.append("")
        lines.append("## apply 拦下的条目（改参照里的结构缺陷后重跑即可）")
        lines.extend("  " + r for r in rows)
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="把零售版参照导入译文（含承标注）")
    ap.add_argument("--lang", required=True)
    ap.add_argument("--ref", required=True, help="短名或路径，如 es.retail-1.0.0")
    ap.add_argument("--only-empty", action="store_true",
                    help="只填还没译的行（pl 当年就是这个口径）")
    ap.add_argument("--write", action="store_true", help="真落盘；默认只出报告")
    ap.add_argument("--repair", action="store_true",
                    help="先按基准修参照的结构（只调 <n>／<t>，不改字）再校验")
    ap.add_argument("--dump", default="", help="同时把映射写成 json")
    ap.add_argument("--out", default="", help="报告路径，默认 build\\qa\\retail_import_<lang>.txt")
    args = ap.parse_args(argv)

    mapping, why = build(args.lang, args.ref, args.only_empty)
    repairs = ()
    if args.repair:
        mapping, repairs = repair_map(args.lang, mapping)
    stats = T.apply_map(args.lang, mapping, dry_run=not args.write)
    text = render(args.lang, args.ref, mapping, why, stats, repairs)
    out = args.out or os.path.join(OUT_DIR, "retail_import_%s.txt" % args.lang)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(text)
    print(text)
    print("报告：%s" % out)
    if args.dump:
        json.dump(mapping, io.open(args.dump, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("映射：%s" % args.dump)
    if not args.write:
        print("（只出报告，加 --write 才落盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
