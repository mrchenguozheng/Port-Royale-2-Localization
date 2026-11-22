#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""德语文案条目索引：把每一对英／德／法／零售译文与它的结构关系记成可查表。

记录字段
- ord        条目在 de.toml 中的排列序号（表内顺序）
- key        条目键
- sha_en/ de/ fr/ ret   四条译文各自的内容哈希（sha1 前 12 位），任一处改动都能立即发现
- len_en/len_de         字符长度（英文基准与德语）
- ph         占位集合（@X$..$、%1 等，排序后拼接，可用于找“同一接口的同一批条目”）
- tags       标记签名 <n>/<t>/<c>/<ts:>/<f:fonts/>/<g:>/<gs:> 的个数
- sentences  粗略句数（按 . ! ? 后接空格或标签计）
- prev/next  上下相邻条目键；prev_same_ph / next_same_ph 表示是否与邻条共用同一占位集合
- block      同段簇：键的前 4 位十六进制（同一批连续写入的条目通常落在一起）
- dup        同文簇：德语正文完全相同的条目共用一个簇号（不同场景复用同一句）
- terms      术语命中（基线里已定案的词），形如 “Lagerhaus:2”

用法
    python src/tools/analysis/de_index.py
    python src/tools/analysis/de_index.py --base 00e5e6c      # 标出相对该提交的改动
输出
    build/qa/de_index.json   机读全量
    build/qa/de_index.csv    表格（Excel 可直开）
    docs/archive/德语条目索引.md      摘要：分组、同文簇、改动清单
"""

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import tomllib
from collections import Counter, defaultdict

EN = "src/orig/en.gog_1.1.2.3.toml"
FR = "src/orig/fr.gog_1.1.2.42.toml"
RET = "src/orig/de.retail-1.0.0.toml"
DE = "src/translations/de.toml"

PH = re.compile(r"@[A-Za-z]+\$[^$]*\$|%\d+")
TAGS = ("<n>", "<t>", "<c>", "<ts:", "<f:fonts/", "<g:", "<gs:")
TERMS = ["Lagerhaus", "Schatzflotte", "Werft", "Handelsdock", "Konvoi", "Mannschaft",
         "Betrieb", "Status", "sinkt", "gesunken", "erober", "Blütezeit", "Logbuch",
         "Turksinseln", "Chronik", "Reede", "Kontor"]


def sha12(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def load(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_rev(rev, path=DE):
    out = subprocess.run(["git", "show", "%s:%s" % (rev, path)],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit("git show 失败：%s" % out.stderr.strip())
    tmp = "build/qa/_index_base.toml"
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(out.stdout)
    return load(tmp)


def build(base_rev=None):
    en, fr, ret, de = load(EN), load(FR), load(RET), load(DE)
    base = load_rev(base_rev) if base_rev else None
    order = list(de)
    rows = []
    dup_groups = defaultdict(list)
    for i, k in enumerate(order):
        e, d = en.get(k, ""), de[k]
        f, r = fr.get(k, ""), ret.get(k, "")
        prev_k = order[i - 1] if i else ""
        next_k = order[i + 1] if i + 1 < len(order) else ""
        ph = sorted(set(PH.findall(d)))
        rows.append({
            "ord": i,
            "key": k,
            "sha_en": sha12(e),
            "sha_de": sha12(d),
            "sha_fr": sha12(f),
            "sha_ret": sha12(r),
            "len_en": len(e),
            "len_de": len(d),
            "ph": " ".join(ph),
            "tags": " ".join("%s%d" % (t.rstrip("/").lstrip("<").replace(":", ""), d.count(t))
                             for t in TAGS if d.count(t)),
            "sentences": len(re.findall(r"[.!?](?=\s|<|$|„|“)", d)),
            "prev": prev_k,
            "next": next_k,
            "prev_same_ph": bool(prev_k) and PH.findall(de[prev_k]) == PH.findall(d),
            "next_same_ph": bool(next_k) and PH.findall(de[next_k]) == PH.findall(d),
            "block": k[:6],
            "dup": "",
            "terms": "; ".join("%s:%d" % (t, d.count(t)) for t in TERMS if t in d),
            "changed": "" if not base else ("1" if base.get(k) != d else ""),
        })
        dup_groups[sha12(d)].append(k)

    for r in rows:
        keys = dup_groups[r["sha_de"]]
        if len(keys) > 1:
            r["dup"] = "D" + r["sha_de"][:6]

    return rows, dup_groups, de, base


def write(rows, dup_groups, de, base, base_rev):
    io.open("build/qa/de_index.json", "w", encoding="utf-8", newline="\n").write(
        json.dumps({"total": len(rows), "base": base_rev or "", "rows": rows},
                   ensure_ascii=False, indent=1))

    fields = ["ord", "key", "sha_en", "sha_de", "sha_fr", "sha_ret", "len_en", "len_de",
              "ph", "tags", "sentences", "prev", "next", "prev_same_ph", "next_same_ph",
              "block", "dup", "terms", "changed"]
    with io.open("build/qa/de_index.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    dup = {g: ks for g, ks in dup_groups.items() if len(ks) > 1}
    blocks = Counter(r["block"] for r in rows)
    term_hits = Counter()
    for r in rows:
        for kv in [x for x in r["terms"].split("; ") if x]:
            term_hits[kv.split(":")[0]] += 1
    changed = [r for r in rows if r["changed"]]

    md = ["# 德语条目索引", "",
          "由 `src/tools/analysis/de_index.py` 生成，机读版见 `build/qa/de_index.json`，",
          "表格版 `build/qa/de_index.csv`（Excel 可直接打开）。", "",
          "共 **%d** 条；同文簇 **%d** 组（德语正文完全相同、被不同场景复用的句子）；" % (len(rows), len(dup)),
          "段簇（键前 6 位相同）**%d** 个。" % len(blocks), ""]

    if base_rev:
        md += ["## 相对 `%s` 的改动" % base_rev, "",
               "命中 **%d** 条：" % len(changed), "",
               "| 键 | 段簇 | 新旧哈希 | 前一条 | 改动前后 |", "|---|---|---|---|---|"]
        for r in changed:
            old = (base or {}).get(r["key"], "")
            md.append("| `%s` | %s | %s → %s | `%s` | %s → %s |" % (
                r["key"], r["block"], r["sha_de"][:12] if not old else sha12(old),
                r["sha_de"], r["prev"],
                (old[:34] + "…") if len(old) > 34 else old,
                (de[r["key"]][:34] + "…") if len(de[r["key"]]) > 34 else de[r["key"]]))
        md.append("")

    md += ["## 同文簇（复用同一句的条目）", "",
           "不同场景共用同一德语正文时，改一处就要同步改这一簇的全部条目。", "",
           "| 簇 | 条目 |", "|---|---|"]
    for g, ks in sorted(dup.items(), key=lambda x: -len(x[1]))[:30]:
        md.append("| `%s` | %s |" % (g, "、".join("`%s`" % k for k in ks)))
    md.append("")

    md += ["## 术语命中分布", "",
           "| 术语 | 出现条数 |", "|---|---|"]
    for t, n in term_hits.most_common():
        md.append("| `%s` | %d |" % (t, n))
    md += ["", "## 字段说明", "",
           "| 字段 | 含义 |", "|---|---|",
           "| `ord` | 在 `de.toml` 中的排列序号 |",
           "| `sha_en`/`sha_de`/`sha_fr`/`sha_ret` | 英／德／法／零售四条正文的内容哈希前 12 位 |",
           "| `len_en`/`len_de` | 字符长度 |",
           "| `ph` | 占位集合（同一接口的条目通常占位相同，可据此成组） |",
           "| `tags` | `<n>`/`<t>`/`<c>`/`<ts:>`/`<f:fonts/>`/`<g:`/`<gs:` 的个数签名 |",
           "| `sentences` | 粗略句数 |",
           "| `prev`/`next` | 上下相邻条目；`prev_same_ph`/`next_same_ph` 表示是否与邻条同占位 |",
           "| `block` | 键前 6 位，同一批连续写入的条目通常同簇 |",
           "| `dup` | 同文簇号（德语正文完全相同） |",
           "| `terms` | 基线定案术语的命中次数 |", ""]

    io.open("docs/archive/德语条目索引.md", "w", encoding="utf-8", newline="\n").write("\n".join(md))
    print("条目 %d 条；同文簇 %d 组；改写 %d 条" % (len(rows), len(dup), len(changed)))
    print("写出 build\\qa\\de_index.json / build\\qa\\de_index.csv / docs\\archive\\德语条目索引.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="", help="git 提交号，标出相对它的改动")
    a = ap.parse_args()
    rows, dup, de, base = build(a.base or None)
    write(rows, dup, de, base, a.base)


if __name__ == "__main__":
    main()
