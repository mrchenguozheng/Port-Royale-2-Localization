# -*- coding: utf-8 -*-
"""把语音转写结果匹配回语言包，得到「语音文件 ↔ hash」映射。

用法：
    python src\\tools\\voice_match.py --asr .tmp\\asr --out docs\\voice-hash-map.csv

输入：asr_run.py 生成的 <lang>.json（{文件名: 转写文本}）
输出：CSV，每个语音文件一行；带 <hash>、匹配分数、英/中/日原文。
同一基名的多语种转写会互相校验（英、法两边应当指向同一个 hash）。
"""

import argparse
import csv
import difflib
import io
import json
import os
import re
import sys
import tomllib

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
ROOT = os.path.dirname(os.path.dirname(TOOLS))
TRANS = os.path.join(ROOT, "src", "live")
REF = os.path.join(ROOT, "src", "orig")

TAG = re.compile(r"<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z]")
WORD = re.compile(r"[a-zà-öø-ÿ0-9']+")


def norm(s):
    s = TAG.sub(" ", s)
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[^a-zà-öø-ÿ0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s):
    return set(WORD.findall(norm(s)))


STOP = {"the", "a", "an", "of", "to", "and", "is", "it", "you", "i", "my", "your",
        "that", "this", "in", "for", "on", "me", "be", "will", "have", "has", "with"}


def score(transcript, candidate):
    t, c = norm(transcript), norm(candidate)
    if not t or not c:
        return 0.0
    ta, tc = WORD.findall(t), WORD.findall(c)
    # 按「词」比较而不是按字符：多出一整句的候选会被扣分，
    # 否则「同一段话 + 多一句提示」的两条会互相认错（5c/5d 就是这种情况）。
    tok_ratio = difflib.SequenceMatcher(None, ta, tc).ratio()
    char_ratio = difflib.SequenceMatcher(None, t, c).ratio()
    a, b = set(ta) - STOP, set(tc) - STOP
    jac = len(a & b) / len(a | b) if (a | b) else 0.0
    lr = min(len(t), len(c)) / max(len(t), len(c)) if max(len(t), len(c)) else 0.0
    return 0.45 * tok_ratio + 0.20 * char_ratio + 0.25 * jac + 0.10 * lr


def load_lang(name):
    path = os.path.join(REF, "%s.toml" % name)
    return tomllib.load(open(path, "rb"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asr", default=os.path.join(ROOT, ".tmp", "asr"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "voice-hash-map.csv"))
    ap.add_argument("--min-score", type=float, default=0.45)
    ap.add_argument("--durations", default=os.path.join(ROOT, ".tmp", "voice_dur.json"))
    args = ap.parse_args()

    en = load_lang("en.gog_1.1.2.3")
    fr = load_lang("fr.gog_1.1.2.42")
    zh = tomllib.load(open(os.path.join(TRANS, "zh.toml"), "rb"))
    ja = tomllib.load(open(os.path.join(TRANS, "ja.toml"), "rb"))

    # 语速：字符数 / 秒，用来在「只差一句话」的候选里分辨
    cps = None
    dur_map = {}
    if os.path.exists(args.durations):
        for fname, dur, _size in json.load(open(args.durations, encoding="utf-8")):
            dur_map[fname] = dur
        base_rows = []
        for lang in ("en", "fr"):
            path = os.path.join(args.asr, "%s.json" % lang)
            if not os.path.exists(path):
                continue
            table = en if lang == "en" else fr
            for fname, text in json.load(open(path, encoding="utf-8")).items():
                if not text.strip() or fname not in dur_map or dur_map[fname] <= 0:
                    continue
                best, best_score = None, 0.0
                for h, src in table.items():
                    sc = score(text, src)
                    if sc > best_score:
                        best, best_score = h, sc
                if best_score >= 0.6:
                    base_rows.append(len(norm(table[best])) / dur_map[fname])
        if base_rows:
            base_rows.sort()
            cps = base_rows[len(base_rows) // 2]
            print("估算语速：%.1f 字符/秒（%d 个样本）" % (cps, len(base_rows)))

    rows = []
    for lang in ("en", "fr"):
        path = os.path.join(args.asr, "%s.json" % lang)
        if not os.path.exists(path):
            continue
        data = json.load(open(path, encoding="utf-8"))
        table = en if lang == "en" else fr
        for fname, text in sorted(data.items()):
            if not text.strip():
                continue
            best, best_score = None, 0.0
            dur = dur_map.get(fname, 0)
            for h, src in table.items():
                sc = score(text, src)
                if cps and dur > 0:
                    predicted = cps * dur
                    ln = max(len(norm(src)), 1)
                    sc -= 0.35 * abs(ln - predicted) / ln
                if sc > best_score:
                    best, best_score = h, sc
            base = re.sub(r"_(En|Fr|Ho|Sp|ho)\.mp3$", "", fname)
            rows.append({
                "voice_file": fname,
                "base_id": base,
                "asr_lang": lang,
                "score": round(best_score, 3),
                "match": "OK" if best_score >= args.min_score else "低置信",
                "hash": best if best_score >= args.min_score else "",
                "en": en.get(best, "").strip() if best else "",
                "fr": fr.get(best, "").strip() if best else "",
                "zh": zh.get(best, "") if best else "",
                "ja": ja.get(best, "") if best else "",
                "asr_text": text,
            })

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["voice_file", "base_id", "asr_lang", "score",
                                           "match", "hash", "en", "fr", "zh", "ja", "asr_text"])
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r["match"] == "OK"]
    print("写入 %s：%d 行，其中高置信 %d 行" % (args.out, len(rows), len(ok)))
    by_base = {}
    for r in rows:
        by_base.setdefault(r["base_id"], set()).add(r["hash"])
    both = {b: hs for b, hs in by_base.items() if len([h for h in hs if h]) > 1}
    if both:
        print("英法两边指向不同 hash 的基名 %d 个：%s" % (len(both), list(both)[:5]))
    return rows


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
