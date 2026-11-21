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

#: 单字虚词：粘在前一个词后面。不能收「不/没/都/也」这类否定与副词 ——
#: 它们管的是后面那个动词，粘左会拼出「城镇不 / 能是」；介词（从/在/把/被/给）
#: 管的是宾语，粘左会拼出「目标是从 / 一个」。
BIND_LEFT = set("的地得了着过是等们吗呢吧啊呀哦嗯中上里外其之")
#: 单字指示/量词/否定/副词/前缀/介词/连词：粘到后一个词前面
#: （「这座」「不能」「总建筑师」「从一个」「或副王」）。
BIND_RIGHT = set("一二三四五六七八九十每各半几这那些不没未别很太更最都也还就才总副前"
                 "在把被给对从向为于跟同与和及或而")

#: 数量/指示短语（两字以内、首字或末字落在这里）：整词粘到后面的中心语上。
#: spaCy 把「好几件事」切成「好几 / 件事」、「几乎没有商人」切成「几乎 / 没有」，
#: 只靠单字粘右消不掉：DP 会在两词之间落刀，实机就是「好几 件事」「几乎 没有商人」
#: ——前者用户判定为词内断刀。这类词天然修饰后一个词，粘上不会拼出坏边界。
QUANT_HEAD = set("一二三四五六七八九十每各半几这那些")

#: 量词收尾：后面紧跟**单字**名词时粘上（spaCy 会把「好几件事」切成
#: 「好几件 / 事」，「件事」硬拆成量词和名词两段，照样被 DP 拦腰断）。
QUANT_TAIL = set("件个只条艘座名位张支门枚种项份类批群次段块片句页行章节层根粒颗"
                 "滴束把间所处场轮趟番期笔封幅顶")
#: 后置方位/范围词：紧贴前一个名词才读得顺。spaCy 把「这些城镇之间」切成
#: 「这些 / 城镇 / 之间」，DP 就在「城镇」和「之间」中间落刀，实机出
#: 「在这些城镇 之间运输」——名词和它的后置词被拆到两行，读起来别扭。
POSTPOS = set("之间 之后 之前 以上 以下 以内 以外 之中 中间 附近 周围 旁边 里面 外面 当中".split())

#: 默认每组最多多少字（预算，不是像素）。
#:
#: 这个数字决定的是「一个空格片段有多长」，不是控件宽度，所以它有上下两个约束：
#: 太大（早先 16）时，教程框那种一行十来字的窄控件里一个片段就占满一行，行数比
#: 原文多，超高文本区把最后一句裁掉（编年史提示的「现在点标着 X 的按钮」就是这么
#: 丢的）；太小（9）确实不再裁，但正文每隔八九个字就断一次，读起来碎
#: （「你的目标是从 一个默默无闻的商人」）。12 是当年在编年史提示这条上量出来的：
#: 12 估算 6 行（和原文对齐），15 涨到 7 行又开始裁。
#:
#: 现在定成 13：每个没有空格的片段不超过 13 字，也就是连续 13 个字之内必有一刀。
#: 位置交给 `_dp_pack()` 按 `_cut_cost()` 挑（标点后 > 词界）。
MAX_CHARS = 13
#: 只处理这么长以上的汉字串。
#:
#: 断点现在按词挑（`_pack()` 的 DP），一个 8 字的片段照样会被拦腰断刀，所以
#: 短片段也得进分词器，否则「在/之前/攻/占/一座」这种单字单位会让断点落在词中间。
#: 6 是折中：再往下 spaCy 要处理的片段数涨得比收益快。
MIN_RUN = 6


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
            # 比 MIN_RUN 还短的片段本来就不需要分词；进了收集范围却没结果，
            # 才是「只能按单字成组、可能切在词中间」的信号。
            if len(run) >= MIN_RUN:
                missed.append(run)
            return list(run)
        return words

    lookup.missing = missed
    return lookup, name


def bind(words):
    """单字虚词粘左、指示词粘右，减少碎词。

    `BIND_RIGHT` 只收单字，两字以上的数量/指示短语交给 `QUANT_HEAD`：
    「好几」+「件事」拼成一件，断点就不会落在「好几」和「件事」之间。
    """
    out = []
    for w in words:
        if out and len(w) == 1 and w in BIND_LEFT:
            out[-1] += w
        else:
            out.append(w)
    merged = []
    for w in out:
        if merged:
            prev = merged[-1]
            if len(prev) == 1 and prev[0] in BIND_RIGHT:
                merged[-1] += w
                continue
            if len(prev) <= 2 and (prev[0] in QUANT_HEAD or prev[-1] in QUANT_HEAD):
                merged[-1] += w
                continue
            if len(prev) <= 3 and prev[-1] in QUANT_TAIL and len(w) == 1 and _is_han(w):
                merged[-1] += w
                continue
            if len(prev) <= 3 and prev[-1] in QUANT_TAIL and len(w) == 2 \
                    and prev not in POSTPOS and _is_han(w[0]) and _is_han(w[1]):
                merged[-1] += w
                continue
            if w in POSTPOS and prev and _is_han(prev[-1]):
                merged[-1] += w
                continue
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


#: 这些字是「往后粘」的介词/副词（「从/一个」「在/港口」「也/可以」）：
#: 断在它后面，前半截就成了残句——「你的目标是从 一个默默无闻的商人」
#: 就是这么来的。`_cut_cost()` 对这类收尾加罚。
LEAD = set("从以向与和在对把被将为于跟同给也都还就才又最更")

#: 句内停顿：`compact()` 找断点时先在这里落，标点后面不额外留空格。
PAUSE = set("，。！？；：、…—")
#: 收尾符号：永远跟在前一个字后面，不能单独成段。
CLOSE = set("》」』）】〉〕”’")
#: 开括号：不能落在一行末尾（「「 / X」」）。
OPEN = set("「『（［【〈〔")
#: 往左粘的字（「…的 / 按钮」跨行读起来是残句）：断在它前面要加罚。
#: 只收虚词，不收「而/或/及/与」这类可以起头的连词。
STICKY = set("的了着过地得们呢吧啊吗呀")
#: 字面并列的连词：断在它前后都会把「A 或 B」拆开。
CONJ = set("与和及或而")
#: 标点字符集（前面能断、后面不能断的那种）。
PUNCT_CHARS = PAUSE | CLOSE
#: 间隔号。它连着西文姓名的名与姓（「罗德里戈·德埃斯科瓦尔」），排版上**黏左**：
#: 只能断在它后面，不能让它起头（行首孤零零一个「·」再跟姓氏，实机里就是这个样子）。
DOT = "·"
#: 可以出现在行首的标点：破折号与省略号不占「禁则」，断在它们前面是合法的。
LINE_HEAD_OK = set("—…")
#: 拆件：名字占位符整体一件、汉字串一件、其余单字一件。
_PIECE = re.compile(r"[\u4e00-\u9fff]+(?:·[\u4e00-\u9fff]+)*|.")
_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")
_VAR_UNIT = re.compile(r"\x00\d+\x00|%\d+|@[A-Za-z]\$[^$]*\$")
_RUN_RX = re.compile(r"[\u4e00-\u9fff]+(?:·[\u4e00-\u9fff]+)*")

#: 硬换行：`<n>` 与 `<n:25>` 这类带参数的换行都要清零；`<c>`、`<f:…>` 是行内标签。
_HARD = re.compile(r"(<n[^>]*>|\r?\n)", re.I)
_HARD_TAG = re.compile(r"<n[^>]*>|\r?\n", re.I)
#: 行内原子：名字占位符、标签、变量（`%1`、`@P$PirateName$`）。
_ATOM = re.compile(r"\x00\d+\x00|<[^>]*>|" + base.VAR.pattern)

#: 中文正文里可以贴着空格的两个字符集（汉字与中文标点）。
_TIGHT = "[\u4e00-\u9fff，。！？；：、…—（）()「」『』【】《》·]"
#: 只抹「两边都是汉字/全角标点」的空格（作者手打的多余空格）。
#: 汉字与拉丁词、数字之间那点空隙要留着：中文与西文混排本来就该有间隔，
#: 而引擎正好把空格当折行点，白送一个可断位置。
_TIGHT_SPACE = re.compile(r"(?<=%s)\s+(?=%s)" % (_TIGHT, _TIGHT))


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



def compact(text, lookup, max_chars=MAX_CHARS):
    """中文紧凑排版：按「离上一个空格多远」算预算，不按汉字串算。

    引擎只在空格处折行，一长串没有空格的字符会被当成一个 token，超出控件
    时整行被丢弃（屏幕上就是一片空白）。所以预算必须按「距上一个空格的字数」
    算：只用标点分开的短句（「你可以在市场买货，也可以去酒馆打听，
    还可以……」）中间一个空格都没有，整段就是一个超长 token，照样会空白。
    旧实现只切「连续汉字串」，这类多短句段落一条空格都拿不到，正是长文空白的成因。

    断点顺序：先按停顿标点（，。！？；：、…— 与收尾引号括号）分段，
    **标点后强制断一刀**（`_break_after_punct()`）：标点本来就是行末最自然的
    位置，留一刀在这里，行只会更短，不会更长。分句内部放得下就不再动；
    放不下时用 `_dp_pack()` 在词界里挑断点。

    早先的做法是「标点后不额外留空格，只在放不下时才落刀」，理由是少刀、
    行更饱满。代价是逗号会被并进下一条 13 字预算里：两个标点之间那段只要没
    超预算，这一刀就丢，行随之后移。行数多不是问题（实机窄框关心的是一行能
    不能放下，行多了顶多滚动），所以改成逢标点必断。
    禁则仍生效：下一件若是收尾引号括号（`」` `』`）这类不能起头的标点，不断。
    """
    parts = _HARD.split(text)
    out = []
    for p in parts:
        if _HARD_TAG.fullmatch(p):
            out.append(p)
            continue
        out.append(_compact_seg(_TIGHT_SPACE.sub("", p).strip(), lookup, max_chars, []))
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
        atom = m.group(0)
        units.append((atom, _atom_weight(atom, names), hard))
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


def _break_after_punct(prev, nxt):
    """上一件是停顿标点收尾时，这里是否强制断一刀。

    `，。！？；：、…—` 与收尾引号括号之后一律断：标点在行末本来就合法，
    断在这里的行只会比不断更短。唯一例外是下一件以不能起头的标点开头
    （`」` `』` `）` 这类连在一起写的收尾符号），那会把标点顶到行首。
    """
    tail = prev[0][-1:] if prev[0] else ""
    if not tail or (tail not in PAUSE and tail not in CLOSE):
        return False
    head = nxt[0][:1] if nxt[0] else ""
    if head and head in PUNCT_CHARS and head not in LINE_HEAD_OK:
        return False
    return True


def _break_after_dot(prev):
    """上一件以间隔号收尾：断在 `·` 之后，让它留在上一行行末。

    `·` 连的是名与姓（「罗德里戈·德埃斯科瓦尔」），黏左。名字整体受 `NAME`
    保护时不会拆到这里；会拆到的只有变量拼出来的写法（`%1 %2·%3` 这类
    消息模板），原本 DP 可以在 `·` 前落刀，实机行首就是孤零零一个「·」。
    """
    return bool(prev[0]) and prev[0][-1] == DOT


def _pack(units, max_chars):
    """把单位按预算拼回去：预算内不插空格，超了才挑一个最像停顿的位置断。

    断点由 DP 挑，不再「填满就断」：贪心会在「…「X」/的按钮」这种地方落刀，
    前半截成了残句。代价函数见 `_cut_cost()`；`hard`（来自原文空格与 `<n>`）
    是死断点，标点收尾处（见 `_break_after_punct()`）与间隔号之后（见
    `_break_after_dot()`）也算死断点，先把 units 切块，块内再各自挑。

    间隔号要断两刀：`·` 后一刀（把它留在上一行）、姓氏那个单位之后再来一刀
    （姓名整体独占一行，下一行从「到某某城镇」这类正文起）。所以断在 `·`
    之后要记一个 `after_dot`，等姓那一件收尾时再断一次。

    这两刀只对**整段超预算**的串生效：`%1·%2` 这种只有三件的姓名模板
    本身就在一行里，再断只会变成「名· 姓」（多一个空格），没必要。
    标点收尾的断（`_break_after_punct()`）仍是无条件的。
    """
    blocks, cur = [], []
    after_dot = False
    dot_cut = sum(u[1] for u in units) > max_chars
    for u in units:
        if cur and (u[2] or _break_after_punct(cur[-1], u)
                    or (dot_cut and (_break_after_dot(cur[-1]) or after_dot))):
            blocks.append(cur)
            cur = []
            after_dot = _break_after_dot(blocks[-1][-1])
        cur.append(u)
    if cur:
        blocks.append(cur)
    return " ".join(_dp_pack(b, max_chars) for b in blocks) if blocks else ""


def _dp_pack(block, max_chars):
    """块内挑断点：token 权重 ≤ 预算（单个单位超预算时自成一组）。

    先按硬约束求一次；求不出来（规则互相打架）再按软约束求一次，违规记重罚
    而不是禁止。硬约束下会出现死锁的只有一种情形：开括号 + 一整段正好占满
    预算的长串（「（」+ 13 字），「开括号不能收尾」和「不超过预算」两条同时
    成立就没有合法断点——那样整块会退化成没有空格的长串，在窄控件里会被
    引擎当成超宽 token 整行丢掉。软约束阶段宁可让「（」吊在行尾，也不让整
    段失去断点。
    """
    for soft in (False, True):
        out = _dp_solve(block, max_chars, soft)
        if out is not None:
            return out
    return "".join(t for t, _, _ in block)


def _dp_solve(block, max_chars, soft=False):
    """一次 DP。无解返回 None；`soft=True` 时预算与 `_cut_ok()` 降级为罚分。"""
    n = len(block)
    if n == 1:
        return block[0][0]
    pre = [0]
    for _, w, _ in block:
        pre.append(pre[-1] + w)
    INF = 1 << 30
    dp = [INF] * (n + 1)
    back = [0] * (n + 1)
    dp[0] = 0
    for i in range(n):
        if dp[i] >= INF:
            continue
        j = i + 1
        while j <= n:
            over = pre[j] - pre[i] - max_chars
            if not soft and j > i + 1 and over > 0:
                break
            legal = j >= n or _cut_ok(block, i, j)
            if not soft and not legal:
                j += 1
                continue
            cost = dp[i] + _cut_cost(block, i, j, n)
            if soft:
                if over > 0:
                    cost += 40 * over
                if not legal:
                    cost += 300 if _ascii_split(block, i, j) else 60
            # 代价打平时保留**最早**的分割（`<`，同级不覆盖）：这样断点会落在
            # 前一个词界刚过预算的位置，不会为了「填满」把专名和后面的名词切开
            # （「英格兰 / 船沉了」是这条规则挡住的）。词内断刀另由 `bind()`
            # 合并数量短语解决（「好几件事」成一件），不靠这里偏后断来凑。
            if cost < dp[j]:
                dp[j] = cost
                back[j] = i
            j += 1
    if dp[n] >= INF:
        return None
    cuts, k = [], n
    while k:
        cuts.append(k)
        k = back[k]
    cuts.reverse()
    out, prev = [], 0
    for cp in cuts:
        out.append("".join(t for t, _, _ in block[prev:cp]))
        prev = cp
    return " ".join(out)


def _ascii_split(block, i, j):
    """这一刀是不是切在两个半角字符之间（「5 %」「% 1」那种）。

    「半角字符」的口径取自 `base.is_ascii_ch()`，和标点全角化的豁免判定同源。
    """
    tail = block[j - 1][0]
    head = block[j][0]
    return bool(tail and head and base.is_ascii_ch(tail[-1])
                and base.is_ascii_ch(head[0]))


def _cut_ok(block, i, j):
    """断点（units[j] 之前）是否合法：标点不能起头、开括号不能收尾、半角串不许拆开。

    行内标签（`<o:…>`、`<c>`、`<f:…>`）不占位、渲染成空，断在它前后都无所谓，
    所以不在这里拦；拦了反而会把「…享受<o:…>5%<o> / 的折扣」逼回无断点的长句。
    间隔号同标点：不能起头（`·德埃斯科瓦尔` 那种断法），只能断在它后面。
    """
    head = block[j][0]
    # 破折号「——」和省略号「…」可以起头（中文排版禁则只管逗号句号那一类），
    # 拦掉它们会让「…印度人——」这种尾巴多出两格，窄框里就多占一格。
    if head and head[0] in PUNCT_CHARS and head[0] not in LINE_HEAD_OK:
        return False
    if head and head[0] == DOT:
        return False
    tail = block[j - 1][0]
    if tail and tail[-1] in OPEN:
        return False
    # 数字、单位、`%`、`$` 这类半角串必须连在一起（「5 %」「% 1」都是坏的）。
    if tail and head and base.is_ascii_ch(tail[-1]) and base.is_ascii_ch(head[0]):
        return False
    return True


def _cut_cost(block, i, j, n):
    """断点代价（越小越自然）：先算「多这一刀要付多少」，再按三张表微调。

    * 每一刀都算 2：这一项让 DP 先求「刀数最少」，刀数打平时才看下面的罚分；
    * 收尾是标点（「，」「。」）→ 不收这 2，标点后本来就是响亮停顿；
    * 收尾是「从/在/也」这类往后粘的字 → +8，会断出残句；
    * 下一件以「的/了/着」起头、或是「与/和/或」这类并列连词 → +8。

    只有这三条罚分有实测收益（消融记录见 docs/翻译局限.md）：补语字、
    指示词+量词、孤字/两字组原来各是一张手写表，在 3548 条上对比坏断率
    一动不动，已删。
    """
    if j >= n:
        return 0
    tail = block[j - 1][0]
    if _is_var(tail):
        # 断在变量之后：变量换成数字/名字后，在它后面起行是自然的断法
        # （「还需 1234 / 才能升到下一级」），所以不收那 2，也不吃 LEAD 罚分。
        # 但下一件以「的/了/着」或「与/和/或」起头时不享受免单，按常规价算——
        # 否则会断出「@T$TOWN$ / 和奥格斯堡」这种更碎的切口。
        head = block[j][0]
        if not head or head[0] not in STICKY and head[0] not in CONJ:
            return 0
    cost = 0
    head = block[j][0]
    if head and (head[0] in STICKY or head[0] in CONJ):
        cost += 8
    if tail and tail[-1] in LEAD:
        cost += 8
    if tail and tail[-1] in PUNCT_CHARS:
        return cost
    return cost + 2


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
        if len(piece) >= max_chars:
            # 刚好等于预算的汉字串也要按词拆：它自己一组放得下，但前后挨着
            # 「（」「）」这类单位就凑不进去了，而「开括号不能收尾」又不许把
            # 括号吊在行尾——那时整段就没有合法断点（预算 13 时撞到过两次）。
            # 断点仍统一交给 `_pack()` 的 DP 挑，这里只把单位切细，不定边界。
            words = _words(piece, lookup)
            for k, w in enumerate(words):
                units.append((w, len(w), first if k == 0 else False))
        else:
            units.append((piece, len(piece), first))
        first = False
    return units


def _is_var(unit_text):
    """这一件是不是变量：`%1` 直写、`\\x00N\\x00`（`compact()` 内部记法）、
    `@X$Name$` 这类名字。三者都算，否则规则只在名字上生效、`%1` 全漏。"""
    return bool(_VAR_UNIT.fullmatch(unit_text))


def _is_han(ch):
    return "\u4e00" <= ch <= "\u9fff"
