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

预算取 16 字。理由是「与英文原文的换行机会相当」而不是像素：英文同一条
长句约 60~80 字符折成两行，一个汉字约占两个英文字符宽，16 字对应约 32
字符，仍比英文单行保守。这是推测值——偏小只是多断几处，偏大才可能溢出，
所以宁可小不能大；真要校准只能实机量，而按定则不做像素判据。

排版策略：默认不留空格（`compact()`）
------------------------------------
旧路径 `spaced()` 逢词就插空格，全表 1719 条带空格、1214 条的空格紧贴标点
（「我刚听说， 一艘满载移民的 英格兰船沉了。」）。现在只在「一段连续汉字
长到超过预算」时才动手，标点不插空格。`ZhGroupSpacing` 保留为可回退的旧路径。

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
NAME = re.compile(r"[\u4e00-\u9fff]+(?:·[\u4e00-\u9fff]+)+")

#: 单字虚词：粘在前一个词后面
BIND_LEFT = set("的地得了着过是在和与及或而但也都不没把被给对从向为以于中上里外其之等们吗呢吧啊呀哦嗯")
#: 单字指示/量词：粘到后一个词前面
BIND_RIGHT = set("一二三四五六七八九十每各半几这那些")

#: 默认每组最多多少字（预算，不是像素）
MAX_CHARS = 16
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

    间距号人名先换成非汉字占位（和 `spaced()` 的做法一致），这样这里收的
    片段和 `spaced()` 之后要查的片段是**同一批字符串**；否则带人名的句子
    查不到词表，只能按单字成组。
    """
    runs = set()
    for t in texts:
        if not t:
            continue
        for m in CJK_RUN.finditer(NAME.sub("\x00", t)):
            if len(m.group(0)) >= min_run:
                runs.add(m.group(0))
    return sorted(runs)


def fallback_wrap(text, min_run=MIN_RUN, step=MAX_CHARS):
    """没有分词器时的兜底：超长汉字串按字数硬切。

    **不保证切在词界**（会切出「因 而」这种结果），所以只在
    spaCy 不可用时使用。步长取 `MAX_CHARS`，兜底出来的组
    也不超过同一份字数预算。
    """
    particles = set("的了是在和与而或也就都但并且时后中上下里外为以于对把被将从到着过们吗呢吧啊呀哦嗯")

    def split_run(run):
        out, s0 = [], run
        while len(s0) > step:
            cut = step
            for k in range(step, max(5, step // 2), -1):
                if s0[k - 1] in particles:
                    cut = k
                    break
            out.append(s0[:cut])
            s0 = s0[cut:]
        out.append(s0)
        return " ".join(out)

    return re.sub(r"[\u4e00-\u9fff]{%d,}" % min_run,
                  lambda m: split_run(m.group(0)), text)


#: 断在它后面最自然：优先「…移民的 / 英格兰船沉了」，而不是「…英格兰 / 船沉了」。
STOP_TAIL = set("的地得了着过们呢吧啊呀，、；：！？…")

#: 这些字开头多半是补语（「打听/到」「拿/出来」），断在它前面会把词拆开。
COMPLEMENT = set("到给出去起上下成开遍完掉")

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
    if words[j - 1][-1] in STOP_TAIL:
        return cost
    return cost + 2


def compact(text, lookup, max_chars=MAX_CHARS):
    """中文紧凑排版：正文默认不留空格，只在会撑爆控件的片段里断行。

    与 `spaced()` 的区别：`spaced()` 逢词就插空格（全表 1719 条带空格，
    其中 1214 条的空格紧贴标点，「我刚听说， 一艘…」）；这里只在
    「一段连续汉字长到超过预算」时才动手，标点本身不插空格——
    中文标点自带停顿，加空格是英文排版的习惯。
    """
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
        p = _TIGHT_SPACE.sub("", p)
        out.append(CJK_RUN.sub(
            lambda m: (m.group(0) if len(m.group(0)) <= max_chars
                       else _groups(m.group(0), lookup, max_chars)), p))
    text = "".join(out)
    return re.sub(r"\x00(\d+)\x00", lambda m: names[int(m.group(1))], text)
