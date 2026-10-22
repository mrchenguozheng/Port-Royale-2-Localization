# -*- coding: utf-8 -*-
"""按词给中文插空格：把超宽的「一长串汉字」拆成词，引擎才能在空格处换行。

背景
----
引擎只按空格换行；中文没有词间空格时，整句会被当成一个 token。
token 比控件宽时，要么整行被丢弃（空白），要么被裁掉（截断）。

分词器
------
默认用 **spaCy + zh_core_web_sm**（维护活跃，OOV 比 jieba 好：
「私掠者」「总督府」「胡安·贝尔穆德斯」都不会被拆）。它需要 Python 3.11
（spaCy 的依赖在 3.14 上还没有轮子），所以脚本通过子进程调用
`segment_zh.py`，用环境变量 `PR2_SPACY_PYTHON` 指定那个解释器：

    set PR2_SPACY_PYTHON=<venv-spacy>\\Scripts\\python.exe

装法（3.11）：

    py -3.11 -m pip install "spacy==3.7.5" "spacy-pkuseg==0.0.33"
    py -3.11 -m spacy download zh_core_web_sm

没有 spaCy 时退回 jieba（结果会差一些，仅作兜底）。

做法
----
1. 分词后，单字虚词（的/了/是/在/和…）粘在前一个词后；
2. 含间隔号的人名整段不拆；
3. 只处理「最长汉字串 >= --min-run」且「最宽 token >= --max-token 像素」的条目；
4. 按目标宽度成组，组间才加空格 —— 一句话通常只多 1–5 个空格。

用法
----
    python src/tools/text/space_words.py --lang zh --dry-run
    python src/tools/text/space_words.py --lang zh --apply
"""

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import tomllib

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
ROOT = os.path.dirname(os.path.dirname(TOOLS))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".tmp", "deps"))

TAG = re.compile(r"(<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z])")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
NAME = re.compile(r"[\u4e00-\u9fff]+(?:·[\u4e00-\u9fff]+)+")
#: 单字虚词：粘在前一个词后面
BIND_LEFT = set("的地得了着过是在和与及或而但也都不没把被给对从向为以于中上里外其之等们吗呢吧啊呀哦嗯")
#: 单字指示/量词：粘到后一个词前面
BIND_RIGHT = set("一二三四五六七八九十每各半几这那些")

WIDTH = None
TARGET_PX = 120.0
CACHE = {}


def spacy_python():
    """找一个装了 spaCy 的 Python。

    优先级：环境变量 PR2_SPACY_PYTHON > 仓库里的 .venv-spacy > 空（退回 jieba）。
    """
    explicit = os.environ.get("PR2_SPACY_PYTHON")
    if explicit:
        return explicit
    local = os.path.join(ROOT, ".venv-spacy", "Scripts", "python.exe")
    return local if os.path.isfile(local) else ""


def segment_spacy(runs):
    """批量分词：把 runs 交给 segment_zh.py，返回 {run: [词…]}。"""
    py = spacy_python()
    if not py:
        return None
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "segment_zh.py")
    env = dict(os.environ)
    # 不要在这里塞 .tmp/spacy37：那是 3.11 的 numpy，给 3.12 的 venv 会直接炸。
    # segment_zh.py 自己会在 import 失败时再补。
    try:
        proc = subprocess.run([py, helper], input=json.dumps(runs, ensure_ascii=False).encode(),
                              capture_output=True, env=env, timeout=600)
    except OSError as exc:
        print("调用 spaCy 失败：%s" % exc)
        return None
    if proc.returncode != 0:
        print("segment_zh.py 失败：%s" % proc.stderr.decode("utf-8", "replace")[-400:])
        return None
    return dict(zip(runs, json.loads(proc.stdout.decode("utf-8"))))


def segment_jieba(run, jieba):
    words = []
    for w in jieba.cut(run, HMM=True):
        if w:
            words.append(w)
    return words


def bind(words):
    """单字虚词粘左、指示词粘右。"""
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


def pack(words):
    """按目标宽度成组：组内不加空格，组间加空格。"""
    groups, cur = [], ""
    for w in words:
        cand = cur + w if cur else w
        if cur and WIDTH(cand, 14.0) > TARGET_PX:
            groups.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        groups.append(cur)
    return " ".join(groups)


def spaced(text, backend):
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
            lambda m: pack(bind(backend(m.group(0)))), p))
    text = "".join(out)
    return re.sub(r"\x00(\d+)\x00", lambda m: names[int(m.group(1))], text)


def token_widths(text, width):
    return [width(t, 14.0) for t in text.split() if t.strip()]


def main():
    global WIDTH, TARGET_PX
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--min-run", type=int, default=12)
    ap.add_argument("--max-token", type=float, default=180.0)
    ap.add_argument("--target", type=float, default=120.0)
    ap.add_argument("--font", default=os.path.join(ROOT, "build", "fonts", "ARIAL.TTF"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import width_check
    WIDTH = width_check.load_font(args.font)
    TARGET_PX = args.target

    path = os.path.join(ROOT, "src", "live", "%s.toml" % args.lang)
    doc = tomllib.load(open(path, "rb"))
    order = [m.group(1) for m in
             (re.match(r'^"([^"]+)"\s*=', ln) for ln in io.open(path, encoding="utf-8"))
             if m]

    # 先挑候选，再一次性分词（spaCy 启动一次就够）
    cand = []
    for k in order:
        t = doc.get(k) or ""
        run = max((len(m.group(0)) for m in CJK_RUN.finditer(NAME.sub("名", t))), default=0)
        if run < args.min_run:
            continue
        before = max(token_widths(t, WIDTH), default=0.0)
        if before < args.max_token:
            continue
        cand.append((k, t, before))

    runs = []
    for _k, t, _b in cand:
        for m in CJK_RUN.finditer(NAME.sub("名", t)):
            runs.append(m.group(0))
    runs = sorted(set(runs))

    seg = segment_spacy(runs)
    if seg is not None:
        backend = lambda run: seg.get(run) or list(run)
        print("分词器：spaCy zh_core_web_sm（%d 个片段）" % len(runs))
    else:
        try:
            import jieba
            dict_path = os.path.join(TOOLS, "data", "zh_userdict.txt")
            if os.path.isfile(dict_path):
                jieba.load_userdict(dict_path)
        except ImportError:
            sys.exit("没有 spaCy 也没有 jieba。装一个：pip install jieba，"
                     "或设 PR2_SPACY_PYTHON 指向装了 spaCy 的 Python 3.11。")
        backend = lambda run: segment_jieba(run, jieba)
        print("分词器：jieba（兜底，质量较差）")

    rows = []
    for k, t, before in cand:
        new = spaced(t, backend)
        after = max(token_widths(new, WIDTH), default=0.0)
        if after >= before - 20:
            continue
        rows.append({"hash": k, "before_px": round(before, 1), "after_px": round(after, 1),
                     "spaces": new.count(" ") - t.count(" "), "zh": t, "new": new})

    rows.sort(key=lambda r: -r["before_px"])
    out = args.out or os.path.join(ROOT, "docs", "csv", "generated", "space-words-%s.csv" % args.lang)
    with io.open(out, "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["hash", "before_px", "after_px", "spaces", "zh", "new"])
        wr.writeheader()
        wr.writerows(rows)

    print("候选 %d 条（汉字串 >= %d、最宽 token >= %gpx、目标 %gpx）" % (
        len(rows), args.min_run, args.max_token, args.target))
    for r in rows[:8]:
        print("  %-12s %6.1f -> %6.1f px (+%d) | %s" % (
            r["hash"], r["before_px"], r["after_px"], r["spaces"], r["new"][:52]))
    print("明细:", out)

    if args.apply and rows:
        for r in rows:
            doc[r["hash"]] = r["new"]

        def esc(x):
            o = []
            for ch in x:
                if ch == "\\":
                    o.append("\\\\")
                elif ch == '"':
                    o.append('\\"')
                elif ch == "\n":
                    o.append("\\n")
                elif ch == "\r":
                    o.append("\\r")
                elif ch == "\t":
                    o.append("\\t")
                elif ord(ch) < 0x20:
                    o.append("\\u%04X" % ord(ch))
                else:
                    o.append(ch)
            return "".join(o)

        io.open(path, "w", encoding="utf-8", newline="\n").write(
            "\n".join('"%s" = "%s"' % (k, esc(doc[k])) for k in order) + "\n")
        print("已写回", path)


if __name__ == "__main__":
    main()
