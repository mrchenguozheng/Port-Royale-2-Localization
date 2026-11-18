# -*- coding: utf-8 -*-
"""zh_space.py —— 按词给中文插空格，让「只按空格断行」的引擎能折行。

为什么需要
----------
引擎只按空格断行：一长串没有空格的汉字会被当成一个 token，token 超出控件
时**整行被丢弃**（不是截断），屏幕上就是一片空白。补空格是唯一不改文案的解法。

成组标准：字数，不是像素
------------------------
控件到底多宽**没有在游戏里量过**；用字体算出来的像素只是推测，不能当判据
（这一点记在 `docs/翻译局限.md`，别再拿 px 做决定）。所以这里用「每组最多
若干字」的预算：确定、可复现、机器之间不会因为字体文件不同而分叉。

预算取 12 字。这个数不是照英文行长推的，而是拿编年史提示那条在窄框里数行数
量出来的：12 字估算 6 行、和原文对得上，15 字就是 7 行、末句被裁。再小（9）
虽然也不裁，但正文每隔八九个字断一次，读着碎。偏小只是多断几处，偏大才可能
溢出或裁行，所以宁可小不能大；真要校准只能实机量，而按定则不做像素判据。

排版策略：按「距上一个空格」算预算（`compact()`）
--------------------------------------------------
旧路径 `spaced()` 逢词就插空格，全表 1719 条带空格、1214 条的空格紧贴标点
（「我刚听说， 一艘满载移民的 英格兰船沉了。」）。`compact()` 只在某个位置
离上一个空格超过预算时才动手，比它干净，但预算必须按整段算而不是按
「连续汉字串」算：只用逗号分开的短句段落里一个空格都没有，整段就是一个
超长 token，引擎照样整行丢弃。`<n>` 是唯一的清零点，`%1`/`<f:…>` 都算行内。
`ZhGroupSpacing` 保留为可回退的旧路径。

分词器只有 spaCy 一条路，兜底才机械切
--------------------------------------
* spaCy + zh_core_web_sm（OOV 比旧方案好：「私掠者」「总督府」「胡安·贝尔穆德斯」
  不会被拆）。它要求 Python 3.9～3.13，用环境变量 `PR2_SPACY_PYTHON` 指向那个
  解释器（或用仓库里的 `.venv-spacy`）；
* 没有 spaCy 就退回 `fallback_wrap()` —— 按字数机械切，**不保证切在词界**
  （会出现「因 而」这种断在词中间的结果）。这是降级路径，不是默认路径。

**不用 jieba**。它最后一次提交停在 2020-02-15，issues 攒了 649 个、基本无人处理，
当构建依赖等于把分词质量锁死在一个不再维护的词典上。这条是硬性规定，不是偏好：
见 `docs/构建与安装.md` 的「不要用 jieba」一节，别再加回来。


用法（生成逻辑在 engine_text.py，这里只提供能力）
----
    from text import zh_space
    runs = zh_space.collect_runs(texts, min_run=12)
    seg = zh_space.segment(runs)           # None 表示没有分词器
    zh_space.spaced(text, seg, max_chars=10)
"""

import json
import os
import re
import subprocess

from text.lang_rules import base

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(TOOLS))

#: 标签/占位符：占位符部分与校验用的 base.VAR 同源，避免两处各写一份。
TAG = re.compile("(<[^>]*>|" + base.VAR.pattern + ")")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
#: 带间隔号的人名：每段 1～10 字，不能贪婪到吞下整句。
#: 早先用 `[\u4e00-\u9fff]+`，只要句子里有一个 `·`，整个句子就被当成一个「名字」
#: 整体保护起来，永远等不到断行——长文空白的一部分就是这么来的。
NAME = re.compile(r"[\u4e00-\u9fff]{1,10}(?:·[\u4e00-\u9fff]{1,10})+")

#: 单字虚词：粘在前一个词后面
BIND_LEFT = set("的地得了着过是在和与及或而但也都不没把被给对从向为以于中上里外其之等们吗呢吧啊呀哦嗯")
#: 单字指示/量词：粘到后一个词前面
BIND_RIGHT = set("一二三四五六七八九十每各半几这那些")

#: 默认每组最多多少字（预算，不是像素）。
#:
#: 这个数字决定的是「一个空格片段有多长」，不是控件宽度，所以它有上下两个约束：
#: 太大（早先 16）时，教程框那种一行十来字的窄控件里一个片段就占满一行，行数比
#: 原文多，超高文本区把最后一句裁掉（编年史提示的「现在点标着 X 的按钮」就是这么
#: 丢的）；太小（9）确实不再裁，但正文每隔八九个字就断一次，读起来碎
#: （「你的目标是从 一个默默无闻的商人」）。
#: 12 是在编年史提示这条上量出来的：12 估算 6 行（和原文对齐），15 涨到 7 行又开始裁。
MAX_CHARS = 12
#: 只处理这么长以上的汉字串：= MAX_CHARS + 1。
#: 必须比 MAX_CHARS 大 1 而且不能再高 —— 只要一个片段会被切成两组，
#: 它就必须进分词器；否则 lookup 拿不到词表，只能按单字成组，
#: 于是出现「进口货 物」这种切在词中间的结果。
MIN_RUN = MAX_CHARS + 1


def spacy_python():
    """找一个装了 spaCy 的 Python。

    优先级：环境变量 PR2_SPACY_PYTHON > 仓库里的 .venv-spacy > 空（退回机械切）。
    """
    explicit = os.environ.get("PR2_SPACY_PYTHON")
    if explicit:
        return explicit
    local = os.path.join(ROOT, ".venv-spacy", "Scripts", "python.exe")
    return local if os.path.isfile(local) else ""


def _segment_spacy(runs):
    """批量分词：把 runs 交给 segment_zh.py，返回 {run: [词…]}；不可用时返回 None。"""
    py = spacy_python()
    if not py:
        return None
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "segment_zh.py")
    try:
        proc = subprocess.run([py, helper],
                              input=json.dumps(runs, ensure_ascii=False).encode(),
                              capture_output=True, timeout=600)
    except OSError as exc:
        print("调用 spaCy 失败：%s" % exc)
        return None
    if proc.returncode != 0:
        print("segment_zh.py 失败：%s" % proc.stderr.decode("utf-8", "replace")[-400:])
        return None
    return dict(zip(runs, json.loads(proc.stdout.decode("utf-8"))))


def segment(runs):
    """把待分词的片段一次性切成词。

    返回 `(lookup, name)`：lookup(run) 给出词表，name 是用了哪个分词器；
    没有 spaCy 时返回 `(None, "")`，调用方应退回 fallback_wrap。

    lookup 上挂着一个 `missing` 列表：调用方给的片段不在这次分词结果里时
    会记一条。正常情况下它必须为空 —— 有内容就说明「会被切两组的片段
    没进分词」，成组只能按单字来（会切在词中间）。

    这里**只认 spaCy**：jieba 已于 2020 年停更，不作构建依赖，见模块头注释。
    """
    if not runs:
        lookup = lambda run: list(run)  # noqa: E731
        lookup.missing = []
        return lookup, "none"
    seg = _segment_spacy(runs)
    if seg is None:
        return None, ""
    name = "spacy"
    missed = []

    def lookup(run):
        words = seg.get(run)
        if words is None:
            # 比预算还短的片段本来就不需要切，按单字也无所谓；
            # 超过预算的片段没进分词器，才是「切在词中间」的信号。
            if len(run) > MAX_CHARS:
                missed.append(run)
            return list(run)
        return words

    lookup.missing = missed
    return lookup, name


def bind(words):
    """单字虚词粘左、指示词粘右，减少碎词。"""
    out = []
    for w in words:
        if out and len(w) == 1 and w in BIND_LEFT:
            out[-1] += w
        else:
            out.append(w)
    merged = []
    for w in out:
        if merged and len(merged[-1]) == 1 and merged[-1][0] in BIND_RIGHT:
            merged[-1] += w
        else:
            merged.append(w)
    return merged


def pack(words, max_chars=MAX_CHARS):
    """按字数预算成组：组内不加空格，组间加空格。单个词超预算时自成一组。"""
    groups, cur = [], ""
    for w in words:
        cand = cur + w
        if cur and len(cand) > max_chars:
            groups.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        groups.append(cur)
    return " ".join(groups)


def spaced(text, lookup, max_chars=MAX_CHARS):
    """在汉字串内部按词成组插空格；标签/占位符/含间隔号的人名原样保留。"""
    names = []

    def keep(m):
        names.append(m.group(0))
        return "\x00%d\x00" % (len(names) - 1)

    text = NAME.sub(keep, text)
    parts = TAG.split(text)
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 1:
            out.append(p)
            continue
        out.append(CJK_RUN.sub(
            lambda m: pack(bind(lookup(m.group(0))), max_chars), p))
    text = "".join(out)
    return re.sub(r"\x00(\d+)\x00", lambda m: names[int(m.group(1))], text)


def collect_runs(texts, min_run=MIN_RUN):
    """收集需要分词的汉字串（去重、排序，便于一次调用分词器）。

    片段定义与 `compact()` 的拆件一致：连续汉字，间隔号人名算在同一片段里
    （`_RUN_RX`）。两边必须是同一批字符串，否则 `lookup()` 查不到词表，
    只能按单字成组，切出来就是「前私 / 掠者」这种断在词中间的结果。
    """
    runs = set()
    for t in texts:
        if not t:
            continue
        for m in _RUN_RX.finditer(t):
            if len(m.group(0)) >= min_run:
                runs.add(m.group(0))
    return sorted(runs)


def fallback_wrap(text, min_run=MIN_RUN, step=MAX_CHARS):
    """没有分词器时的兜底：按字数硬切。

    **不保证切在词界**（会切出「因 而」这种结果），所以只在
    spaCy 不可用时使用。这里走和 `compact()` 同一套分段逻辑：
    标点分段、按「距上一个空格」算预算，否则多短句的段落一条空格都没有，
    长文在游戏里直接空白。词粒度退化成两字一块。
    """
    def lookup(run):
        return [run[i:i + 2] for i in range(0, len(run), 2)] or [run]

    return _compact_seg(text, lookup, step, [])


#: 断在它后面最自然：优先「…移民的 / 英格兰船沉了」，而不是「…英格兰 / 船沉了」。
STOP_TAIL = set("的地得了着过们呢吧啊呀，、；：！？…")

#: 这些字开头多半是补语（「打听/到」「拿/出来」），断在它前面会把词拆开。
COMPLEMENT = set("到给出去起上下成开遍完掉")

#: 这些字是「往后粘」的介词/副词（「从/一个」「在/港口」「也/可以」）：
#: 断在它后面，前半截就成了残句——「你的目标是从 一个默默无闻的商人」
#: 就是这么来的。`_break_cost()` 对这类收尾加罚。
LEAD = set("从以向与和在对把被将为于跟同给也都还就才又最更")

#: 句内停顿：`compact()` 找断点时先在这里落，标点后面不额外留空格。
PAUSE = set("，。！？；：、…—")
#: 收尾符号：永远跟在前一个字后面，不能单独成段。
CLOSE = set("》」』）】〉〕”’")
#: 拆件：名字占位符整体一件、汉字串一件、其余单字一件。
_PIECE = re.compile(r"[\u4e00-\u9fff]+(?:·[\u4e00-\u9fff]+)*|.")
_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")
_RUN_RX = re.compile(r"[\u4e00-\u9fff]+(?:·[\u4e00-\u9fff]+)*")

#: 硬换行：`<n>` 与 `<n:25>` 这类带参数的换行都要清零；`<c>`、`<f:…>` 是行内标签。
_HARD = re.compile(r"(<n[^>]*>|\r?\n)", re.I)
_HARD_TAG = re.compile(r"<n[^>]*>|\r?\n", re.I)
#: 行内原子：名字占位符、标签、变量（`%1`、`@P$PirateName$`）。
_ATOM = re.compile(r"\x00\d+\x00|<[^>]*>|" + base.VAR.pattern)

#: 中文正文里可以贴着空格的两个字符集（汉字与中文标点）。
_TIGHT = "[\u4e00-\u9fff，。！？；：、…—（）()「」『』【】《》·]"
_TIGHT_SPACE = re.compile(r"(?<=%s)\s+|\s+(?=%s)" % (_TIGHT, _TIGHT))


def load_user_words(words):
    """把已知专名/术语交给分词器，免得切在词中间（「皇家 / 港」）。

    只剩 spaCy 一条路后这里不再需要往词典里塞词：spaCy 用统计模型分词，
    没有「用户词典」这个概念，专名由 `collect_runs()` 的整段交给它自己切。
    函数保留为空实现，仅为不破坏 `lang_rules/zh.py` 的调用点与外部脚本。
    """
    return 0


def _words(run, lookup):
    words = [w for w in lookup(run) if w]
    return bind(words) if words else [run]


def _groups(run, lookup, budget=MAX_CHARS):
    """在 ≤budget 的前提下挑断点：优先落在停顿字后，其次才按预算硬填。

    用动态规划而不是贪心。贪心会把「一艘满载移民的英格兰」塞满 10 字，
    断点落到「…英格兰 / 船沉了」（词中间，难看）；DP 允许这组只装 7 字就停，
    让断点落在「…移民的 / 英格兰船沉了」。
    """
    words = _words(run, lookup)
    n = len(words)
    if n <= 1:
        return run
    pre = [0]
    for w in words:
        pre.append(pre[-1] + len(w))
    INF = 1 << 30
    dp = [INF] * (n + 1)
    back = [0] * (n + 1)
    dp[0] = 0
    for i in range(n):
        if dp[i] >= INF:
            continue
        j = i
        while j < n and (j == i or pre[j + 1] - pre[i] <= budget):
            j += 1
            cost = dp[i] + 1 + _break_cost(words, i, j, n)
            if cost < dp[j]:
                dp[j] = cost
                back[j] = i
    if dp[n] >= INF:
        return run
    cuts, k = [], n
    while k:
        cuts.append(k)
        k = back[k]
    cuts.reverse()
    out, prev = [], 0
    for cp in cuts:
        out.append("".join(words[prev:cp]))
        prev = cp
    return " ".join(out)


def _break_cost(words, i, j, n):
    """这一组的收尾代价：断点越不像自然停顿，代价越高。

    * 末尾就结束 → 0；
    * 下一个词以补语字开头（「打听 / 到」）→ 6，最不愿这样断；
    * 组太短（孤字 4、两字 2）→ 加上去，免得出现「你的 / 船队」；
    * 断在「的/了/，」后面 → 0，这是最自然的停顿。
    """
    size = sum(len(w) for w in words[i:j])
    cost = 0
    if size == 1:
        cost += 4
    elif size == 2 and j < n:
        cost += 2
    if j == n:
        return cost
    if words[j][0] in COMPLEMENT:
        return cost + 6
    if words[j - 1][-1] in LEAD:
        return cost + 8
    if words[j - 1][-1] in STOP_TAIL:
        return cost
    return cost + 2


def compact(text, lookup, max_chars=MAX_CHARS):
    """中文紧凑排版：按「离上一个空格多远」算预算，不按汉字串算。

    引擎只在空格处折行，一长串没有空格的字符会被当成一个 token，超出控件
    时整行被丢弃（屏幕上就是一片空白）。所以预算必须按「距上一个空格的字数」
    算：只用标点分开的短句（「你可以在市场买货，也可以去酒馆打听，
    还可以……」）中间一个空格都没有，整段就是一个超长 token，照样会空白。
    旧实现只切「连续汉字串」，这类多短句段落一条空格都拿不到，正是长文空白的成因。

    断点顺序：先按停顿标点（，。！？；：、…— 与收尾引号括号）分段，
    段内放得下就不再动；放不下时用 `_groups()` 按词挑断点。标点本身不留空格，
    空格只落在「已经放不下了」的位置上，比逢词插空格干净得多。
    """
    parts = _HARD.split(text)
    out = []
    for p in parts:
        if _HARD_TAG.fullmatch(p):
            out.append(p)
            continue
        out.append(_compact_seg(_TIGHT_SPACE.sub("", p), lookup, max_chars, []))
    return "".join(out)


def _compact_seg(seg, lookup, max_chars, names):
    """给一段（行内）文本排空格：预算穿过占位符累加，只有 `<n>` 才清零。"""
    if not seg:
        return seg
    units = []          # [(文本, 权重, 是否强制断行), …]
    hard = False
    last = 0
    for m in _ATOM.finditer(seg):
        hard = _chunk_units(seg[last:m.start()], lookup, max_chars, names, hard, units)
        units.append((m.group(0), _atom_weight(m.group(0), names), False))
        hard = False
        last = m.end()
    _chunk_units(seg[last:], lookup, max_chars, names, hard, units)
    return _pack(units, max_chars)


def _chunk_units(chunk, lookup, max_chars, names, hard, units):
    """把一段纯文本按停顿切成单位，追加进 units；返回「下一块是否强制断行」。"""
    buf = []
    for ch in chunk:
        if ch.isspace():
            if buf:
                units.extend(_clause_units("".join(buf), lookup, max_chars, names, hard))
                buf = []
                hard = False
            hard = True
            continue
        buf.append(ch)
        if ch in PAUSE or ch in CLOSE:
            units.extend(_clause_units("".join(buf), lookup, max_chars, names, hard))
            buf = []
            hard = False
    if buf:
        units.extend(_clause_units("".join(buf), lookup, max_chars, names, hard))
        return False
    return hard


def _atom_weight(atom, names):
    """行内原子的权重：标签不占位，变量按替换后的大致长度算。"""
    if atom.startswith("<"):
        return 0
    m = _PLACEHOLDER.fullmatch(atom)
    if m:
        idx = int(m.group(1))
        return len(names[idx]) if 0 <= idx < len(names) else 3
    return 6 if atom.startswith("@") else 3


def _pack(units, max_chars):
    """把单位按预算拼回去：标点贴前字，其余超预算就插一个空格。"""
    out, cur = [], 0
    for text, weight, hard in units:
        if text in PAUSE or text in CLOSE:      # 标点永远贴着前一个字
            out.append(text)
            cur += weight
            continue
        if cur and (hard or cur + weight > max_chars):
            out.append(" ")
            cur = 0
        out.append(text)
        cur += weight
    return "".join(out)


def _clause_units(clause, lookup, max_chars, names, hard):
    """把一个短句拆成 [(文本, 权重, 强制断行)]：名字整体一件，长汉字串按词切。"""
    units = []
    first = hard
    for piece in _PIECE.findall(clause):
        m = _PLACEHOLDER.fullmatch(piece)
        if m:
            idx = int(m.group(1))
            label = names[idx] if 0 <= idx < len(names) else piece
            units.append((piece, len(label), first))
            first = False
            continue
        if piece.isascii():
            units.append((piece, len(piece), first))
            first = False
            continue
        if piece[0] in PAUSE or piece[0] in CLOSE or len(piece) == 1 and not _is_han(piece[0]):
            units.append((piece, len(piece), first))
            first = False
            continue
        pieces = [piece]
        if len(piece) > max_chars:
            pieces = [p for p in _groups(piece, lookup, max_chars).split(" ") if p]
        for k, sub in enumerate(pieces):
            units.append((sub, len(sub), first if k == 0 else True))
        first = False
    return units


def _is_han(ch):
    return "\u4e00" <= ch <= "\u9fff"


def perchar(text):
    """逐字断行：两个汉字之间一律插一个半角空格，其余位置不动。

    引擎只在空格处折行，每字一空格等于每个字后面都有断行点，行能填满、
    也不会把词切开（已经没有词了）。标签 `<…>`、变量 `@…@`/`%…%` 内部
    不插；标点两侧不留（标点自带全角宽度，行首行尾也不该挂孤立标点）；
    引号里的短标签（`「关闭」`）也不拆，免得按钮名里出现缝。

    代价是空格本身有宽度（当前字体 0.224 em），整段会变成均匀疏排。
    """
    if not text:
        return text
    out = []
    last = 0
    for m in _ATOM.finditer(text):
        out.append(_perchar_chunk(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_perchar_chunk(text[last:]))
    return "".join(out)


def _perchar_chunk(chunk):
    """纯文本片段：汉字之间插空格；引号里的短标签整块留着。"""
    if not chunk:
        return chunk
    protect = _quoted_spans(chunk)
    out = []
    prev = None
    prev_i = None
    for i, ch in enumerate(chunk):
        if (prev is not None and _is_han(prev) and _is_han(ch)
                and not (prev_i in protect and i in protect)):
            out.append(" ")
        out.append(ch)
        prev = ch
        prev_i = i
    return "".join(out)


_QUOTE_PAIRS = (("「", "」"), ("『", "』"), ("（", "）"), ("《", "》"), ("【", "】"),
                ("“", "”"))


def _quoted_spans(text):
    """找出「短引号标签」内部的字符下标：这些位置不插空格。"""
    idx = set()
    for a, b in _QUOTE_PAIRS:
        rx = re.compile("%s([^%s]{1,6})%s" % (
            re.escape(a), re.escape(a + b), re.escape(b)))
        for m in rx.finditer(text):
            if all(_is_han(c) for c in m.group(1)):
                idx.update(range(m.start(1), m.end(1)))
    return idx
