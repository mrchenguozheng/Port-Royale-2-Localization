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

分词器优先，兜底才机械切
------------------------
* 首选 spaCy + zh_core_web_sm（OOV 比 jieba 好：「私掠者」「总督府」
  「胡安·贝尔穆德斯」不会被拆）。它需要 Python 3.11，用环境变量
  `PR2_SPACY_PYTHON` 指向那个解释器（或用仓库里的 `.venv-spacy`）；
* 没有 spaCy 就用 jieba；
* 两个都没有，才退回 `fallback_wrap()` —— 按字数机械切，**不保证切在词界**
  （会出现「因 而」这种断在词中间的结果）。这是降级路径，不是默认路径。

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

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(TOOLS))

TAG = re.compile(r"(<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z])")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
NAME = re.compile(r"[\u4e00-\u9fff]+(?:·[\u4e00-\u9fff]+)+")

#: 单字虚词：粘在前一个词后面
BIND_LEFT = set("的地得了着过是在和与及或而但也都不没把被给对从向为以于中上里外其之等们吗呢吧啊呀哦嗯")
#: 单字指示/量词：粘到后一个词前面
BIND_RIGHT = set("一二三四五六七八九十每各半几这那些")

#: 默认每组最多多少字（预算，不是像素）
MAX_CHARS = 10
#: 只处理这么长以上的汉字串：= MAX_CHARS + 1。
#: 必须比 MAX_CHARS 大 1 而且不能再高 —— 只要一个片段会被切成两组，
#: 它就必须进分词器；否则 lookup 拿不到词表，只能按单字成组，
#: 于是出现「进口货 物」这种切在词中间的结果。
MIN_RUN = MAX_CHARS + 1


def spacy_python():
    """找一个装了 spaCy 的 Python。

    优先级：环境变量 PR2_SPACY_PYTHON > 仓库里的 .venv-spacy > 空（退回 jieba）。
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


def _segment_jieba(runs):
    try:
        import jieba
    except ImportError:
        return None
    dict_path = os.path.join(TOOLS, "data", "zh_userdict.txt")
    if os.path.isfile(dict_path):
        jieba.load_userdict(dict_path)
    return {run: [w for w in jieba.cut(run, HMM=True) if w] for run in runs}


def segment(runs):
    """把待分词的片段一次性切成词。

    返回 `(lookup, name)`：lookup(run) 给出词表，name 是用了哪个分词器；
    两个分词器都没有时返回 `(None, "")`，调用方应退回 fallback_wrap。

    lookup 上挂着一个 `missing` 列表：调用方给的片段不在这次分词结果里时
    会记一条。正常情况下它必须为空 —— 有内容就说明「会被切两组的片段
    没进分词」，成组只能按单字来（会切在词中间）。
    """
    if not runs:
        lookup = lambda run: list(run)  # noqa: E731
        lookup.missing = []
        return lookup, "none"
    seg = _segment_spacy(runs)
    if seg is not None:
        name = "spacy"
    else:
        seg = _segment_jieba(runs)
        if seg is None:
            return None, ""
        name = "jieba"
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
    spaCy/jieba 都不可用时使用。步长取 `MAX_CHARS`，兜底出来的组
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
