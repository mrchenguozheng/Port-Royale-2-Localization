# -*- coding: utf-8 -*-
r"""apply_zh_rules.py —— 把 src/translations/zh.toml 加工成引擎能直接用的中文文本。

产物：build/engine_text/zh.toml（**构建产物，不进仓库**）。
compile_pack 会在内存里做同样的事，这个文件只是给人看的中间结果；
删掉它不影响构建，下次编译会重新生成。

流水线（顺序固定，每一步只加空格、不改字）：
  1. 标点：全角化、单标点后空格、成对标点外侧空格（lang_rules/zh.py: normalize）
  2. 连词：标点后的连词后面补一个空格（不在句末才补）
  3. 人名：名・姓两侧按「句首只补后 / 句末不补 / 句中缺哪补哪」补空格
  4. 数字 / 破折号 / 省略号 / `<n><n>` 两侧补空格（space_tokens）
  5. 按词成组补空格：分词器优先（spaCy → jieba），
     两个都没有时才退回 zh_space.fallback_wrap 的按字数机械切
  6. 连续空格归一

成组标准是**字数预算**，不是像素：控件宽度没有在游戏里实测过，
用字体算出来的 px 只是推测，不能当判据（见 docs/翻译局限.md）。

用法：
    python src/tools/text/apply_zh_rules.py            # 生成并写入 build/engine_text
    python src/tools/text/apply_zh_rules.py --check    # 与已生成的比较，不写文件
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
ROOT = os.path.dirname(os.path.dirname(TOOLS))
sys.path.insert(0, HERE)

from text import lang_rules, zh_space  # noqa: E402

#: 唯一手改的文本层
SRC = os.path.join(ROOT, "src", "translations", "zh.toml")
#: 构建产物（build/ 已 gitignore）
DST = os.path.join(ROOT, "build", "engine_text", "zh.toml")

TAG = zh_space.TAG
CONJ = ("因为", "所以", "但是", "如果", "虽然", "然后", "而且", "以及", "因此", "不过",
        "并且", "或者", "还是", "于是", "同时", "此外", "例如", "比如", "由于", "无论",
        "即使", "尽管", "然而", "可是", "因而", "从而", "况且", "何况", "假如", "要是",
        "一旦", "以便", "以免", "甚至", "反而", "否则", "不然", "总之", "也就是说")
SINGLE_CONJ = {"但": "是", "而": "是且也又在对就", "却": "是也又就",
               "并": "且不没未非能会已将无发", "或": "者是许", "因": "为此", "所": "以"}
PUNCT_CHARS = "，。！？；：、…—）)」』】》”’·"
TITLES = ("先生", "爵士", "女士", "小姐", "夫人", "船长", "总督", "副王", "国王",
          "女王", "伯爵", "将军", "指挥官", "上校", "中尉", "少校", "神父", "医生")
NAME_STOP = "的了他是在和与也就都但而或又着过们吗呢吧啊呀哦嗯，。！？、；：…—（）()「」『』【】《》 \u3000<@%"
SPACE = " \u3000"
SENT_END = "。！？…!?"

conj_re = re.compile(
    r"(?P<pre>[%s])(?P<gap>\s*)(?P<conj>%s|%s)(?P<next>[^\s%s<@%%])"
    % (re.escape(PUNCT_CHARS),
       "|".join(sorted(CONJ, key=len, reverse=True)),
       "|".join("%s(?![%s])" % (k, re.escape(v)) for k, v in SINGLE_CONJ.items()),
       re.escape(PUNCT_CHARS)))


def fix_conj(text):
    """标点后的连词补一个空格；「因 此」这类被切开的词粘回去。"""
    text = conj_re.sub(
        lambda m: m.group("pre") + m.group("gap") + m.group("conj") + " " + m.group("next"),
        text)
    return text.replace("因 此", "因此")


def load_list(name):
    path = os.path.join(TOOLS, "data", name)
    out = []
    if os.path.isfile(path):
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append(line)
    return out


def build_names(doc):
    given = {v for h, v in doc.items() if h.startswith("0xfc51") and 1 <= len(v) <= 5}
    surn = {v for h, v in doc.items() if h.startswith("0xcf57") and 1 <= len(v) <= 6}
    extras = load_list("zh_names.txt")
    towns = load_list("zh_towns.txt")
    return given, surn, extras, towns


name_re = None

QUOTE_RX = re.compile(r"「[^」]*」|『[^』]*』|《[^》]*》")
_NAME_CACHE = {}


def _name_regexes(all_names):
    key = all_names if isinstance(all_names, frozenset) else frozenset(all_names)
    hit = _NAME_CACHE.get(key)
    if hit is not None:
        return hit

    bare = sorted((n for n in all_names if len(n) >= 3), key=len, reverse=True)
    bare_re = re.compile("|".join(map(re.escape, bare))) if bare else None

    names_alt = "|".join(map(re.escape, sorted(all_names, key=len, reverse=True)))
    titles_alt = "|".join(map(re.escape, sorted(TITLES, key=len, reverse=True)))
    titled_re = re.compile(
        "(%s)\\s*((?:[\\u4e00-\\u9fff]{1,3}世|\\d+世)(?:\\s*(?:%s))?|(?:%s))"
        % (names_alt, titles_alt, titles_alt))
    first_chars = frozenset(n[0] for n in all_names if n)
    _NAME_CACHE[key] = (bare_re, titled_re, first_chars)
    return bare_re, titled_re, first_chars


def find_names(text, given, surn, extras, all_names=None):
    global name_re
    if name_re is None:
        name_re = re.compile(
            "(%s)\u00b7([\\u4e00-\\u9fff]{1,6}?)(?=[%s]|%s|$)"
            % ("|".join(map(re.escape, sorted(given, key=len, reverse=True))),
               re.escape(NAME_STOP), "|".join(map(re.escape, TITLES))))
    spans = ([(m.start(), m.end()) for m in name_re.finditer(text)]
             if "·" in text else [])

    if all_names is None:
        all_names = set(given) | set(surn) | set(extras)
    bare_re, titled_re, first_chars = _name_regexes(all_names)
    if not first_chars.isdisjoint(text):
        if bare_re:
            spans.extend(m.span() for m in bare_re.finditer(text))
        spans.extend(m.span() for m in titled_re.finditer(text))

    # 引号里的通常是船名/书名，不按人名加空格。
    quotes = ([(m.start(), m.end()) for m in QUOTE_RX.finditer(text)]
              if ("「" in text or "『" in text or "《" in text) else [])

    def in_quote(s0, e0):
        return any(q0 <= s0 and e0 <= q1 for q0, q1 in quotes)

    spans = [(s0, e0) for s0, e0 in spans if not in_quote(s0, e0)]

    spans.sort(key=lambda x: (x[0], -x[1]))
    merged = []
    for sp in spans:
        if merged and sp[0] < merged[-1][1]:
            if sp[1] > merged[-1][1]:
                merged[-1] = (merged[-1][0], sp[1])
            continue
        merged.append(sp)
    return merged


def pad_names(text, spans, towns=()):
    out, last = [], 0
    for start, end in spans:
        before = text[start - 1] if start > 0 else None
        after = text[end] if end < len(text) else None

        i = start - 1
        while i >= 0 and text[i] in SPACE:
            i -= 1
        at_start = (i < 0) or (text[i] in SENT_END)

        j = end
        while j < len(text) and text[j] in SPACE:
            j += 1
        at_end = (j >= len(text)) or (text[j] in SENT_END)

        need_before = (not at_start) and before is not None and before not in SPACE and before not in PUNCT_CHARS
        need_after = (not at_end) and after is not None and after not in SPACE and after not in PUNCT_CHARS
        if need_after and text[start:end] in towns and after in "的地得们等城人镇岛港":
            need_after = False

        out.append(text[last:start])
        if need_before:
            out.append(" ")
        out.append(re.sub(r"\s+", "", text[start:end]))
        if need_after:
            out.append(" ")
        last = end
    out.append(text[last:])
    return "".join(out)


def _is_han(ch):
    return ch and "\u4e00" <= ch <= "\u9fff"


SPLIT_RX = re.compile(r"(<n><n>|<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z])")


def space_tokens(text):
    """数字 / 破折号 / 省略号 / `<n><n>` 两侧补空格（标签与占位符内部不动）。

    这是唯一实现：以前 space_years / space_marks / space_dash / space_ellipsis /
    space_before_double_break 五个名字指向同一件事，合并成这一个。
    """
    out = []
    for part in SPLIT_RX.split(text):
        if part == "<n><n>":
            if out and not out[-1].endswith(" "):
                out.append(" ")
            out.append(part)
            continue
        if not part:
            continue
        if part[0] in "<@" or (part.startswith("%") and len(part) <= 6):
            out.append(part)
            continue

        seg = part

        def year_repl(m):
            s0 = m.group(0)
            left = seg[m.start() - 1] if m.start() > 0 else ""
            right = seg[m.end()] if m.end() < len(seg) else ""
            pre = " " if _is_han(left) else ""
            post = " " if _is_han(right) else ""
            return pre + s0 + post

        seg = re.sub(r"(?<!\d)\d{4}(?!\d)", year_repl, seg)

        def mark_repl(m):
            mark = m.group(0).strip()
            pre = " " if m.start() > 0 and seg[m.start() - 1] not in " \n" else ""
            post = "" if m.end() >= len(seg) or seg[m.end()] in " \n" else " "
            return pre + mark + post

        out.append(re.sub(r" *—— *| *…… *", mark_repl, seg))
    result = "".join(out)
    # <n><n> 两端都留空格（出现在段中也一样）。
    result = re.sub(r" *<n><n> *", " <n><n> ", result)
    return result.strip()


def collapse_spaces(text):
    if "  " not in text:
        return text
    return re.sub(r" {2,}", " ", text)


CACHE = os.path.join(ROOT, "build", "cache", "zh.generated.json")
KEY_FILES = [SRC, __file__,
             os.path.join(HERE, "zh_space.py"),
             os.path.join(HERE, "lang_rules", "zh.py"),
             os.path.join(HERE, "lang_rules", "base.py"),
             os.path.join(TOOLS, "data", "zh_names.txt"),
             os.path.join(TOOLS, "data", "zh_towns.txt")]


def _cache_key():
    rows = []
    for p in KEY_FILES:
        try:
            st = os.stat(p)
            rows.append([os.path.basename(p), st.st_mtime_ns, st.st_size])
        except OSError:
            rows.append([os.path.basename(p), 0, 0])
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()


def _order_of(path):
    return [m.group(1) for m in
            (re.match(r'^"([^"]+)"\s*=', ln) for ln in io.open(path, encoding="utf-8"))
            if m]


def _pipeline(names, text):
    """单条译文走到「分词前后」的中间态（标点、连词、人名、数字/标记空格）。"""
    a = names["rules"].normalize(text)
    b = fix_conj(a)
    parts = TAG.split(b)
    res = []
    for i, part in enumerate(parts):
        if i % 2 == 1 or not part:
            res.append(part)
            continue
        spans = find_names(part, names["given"], names["surn"],
                           names["extras"] + names["towns"], names["all"])
        res.append(pad_names(part, spans, names["towns"]) if spans else part)
    c = space_tokens("".join(res))
    return a, b, c


def generate_doc(doc, order=None):
    """纯函数：{id: 译文} → {id: 引擎文本}。不读文件、不碰缓存。"""
    order = list(order or doc)
    rules = lang_rules.get("zh")
    given, surn, extras, towns = build_names(doc)
    names = {"rules": rules, "given": given, "surn": surn,
             "extras": extras, "towns": towns,
             "all": frozenset(set(given) | set(surn) | set(extras) | set(towns))}

    # 第一遍：规则到「分词前」。同时收集需要分词的片段，避免逐条起子进程。
    interim, stats = {}, {"punct": 0, "conj": 0, "name": 0, "space": 0}
    for h in order:
        text = doc.get(h) or ""
        if not text:
            interim[h] = ""
            continue
        a, b, c = _pipeline(names, text)
        interim[h] = c
        stats["punct"] += a != text
        stats["conj"] += b != a
        stats["name"] += c != b

    runs = zh_space.collect_runs([t for t in interim.values() if t])
    seg, seg_name = zh_space.segment(runs)
    if seg is None and runs:
        print("提示：没有 spaCy/jieba，中文补空格退回按字数机械切"
              "（会切在词中间，见 zh_space.fallback_wrap）。")

    # 第二遍：补空格
    out = {}
    for h in order:
        c = interim[h]
        if not c:
            out[h] = c
            continue
        d = (zh_space.fallback_wrap(c) if seg is None
             else zh_space.spaced(c, seg))
        out[h] = collapse_spaces(d)
        stats["space"] += out[h] != c

    missing = getattr(seg, "missing", None) or []
    if missing:
        print("提示：%d 个片段没进分词器，只能按单字成组（可能切在词中间）。"
              % len(missing))
    return order, out, stats, seg_name


def generate(use_cache=True):
    """按规则生成 {id: 引擎文本}，不写文件。"""
    if use_cache and not os.environ.get("PR2_NO_CACHE"):
        try:
            with open(CACHE, encoding="utf-8") as fh:
                cached = json.load(fh)
            if cached.get("key") == _cache_key():
                return (cached["order"], cached["out"], cached["stats"],
                        cached.get("segmenter", ""))
        except (OSError, ValueError, KeyError):
            pass

    doc = tomllib.load(open(SRC, "rb"))
    order = _order_of(SRC)
    result = generate_doc(doc, order)

    if use_cache and not os.environ.get("PR2_NO_CACHE"):
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            tmp = CACHE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"key": _cache_key(), "order": result[0], "out": result[1],
                           "stats": result[2], "segmenter": result[3]},
                          fh, ensure_ascii=False)
            os.replace(tmp, CACHE)
        except OSError:
            pass
    return result


def write(order, out):
    header = ("# 构建产物：由 src/tools/text/apply_zh_rules.py 从 src/translations/zh.toml 生成。\n"
              "# 不进仓库，删掉也没关系；改译文请改 src/translations/zh.toml，改规则请改脚本。\n")
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    io.open(DST, "w", encoding="utf-8", newline="\n").write(
        header + "\n".join('"%s" = "%s"' % (k, esc(out[k])) for k in order) + "\n")


def esc(t):
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只校验 build/engine_text/zh.toml 是否与「译文 + 规则」一致，不写文件")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    order, out, stats, seg_name = generate()
    print("生成 %d 条｜标点改动 %d｜连词 %d｜人名 %d｜补空格 %d｜分词器 %s" % (
        len(order), stats["punct"], stats["conj"], stats["name"], stats["space"],
        seg_name or "无（机械兜底）"))

    if args.check:
        old = {}
        if os.path.isfile(DST):
            try:
                old = tomllib.load(open(DST, "rb"))
            except Exception:
                old = {}
        diff = [h for h in order if old.get(h) != out[h]]
        extra = [h for h in old if h not in out]
        if diff or extra:
            print("生成物不一致：%d 条不同" % len(diff))
            for h in diff[:5]:
                print("  %s\n    文件：%s\n    应为：%s" % (h, old.get(h), out[h]))
            if extra:
                print("  文件里多出 %d 条" % len(extra))
            return 1
        print("生成物一致。")
        return 0

    if args.dry_run:
        return 0

    write(order, out)
    print("已写入", DST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
