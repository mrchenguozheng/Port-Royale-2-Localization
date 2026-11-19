#!/usr/bin/env python3
# coding: utf-8
"""ref_clean.py — 参照层清洁：把 en / fr 这两份「最初的参考」对齐成 `*-clean`。

与 `retail_import.py --clean-ref` 的分工：

| 工具 | 清洁对象 | 做什么 |
|---|---|---|
| `--clean-ref` | 零售版（措辞来源） | 结构对齐基准 + 按语言定则补标点、规整空白 |
| `ref_clean.py` | 基准与官方译文（结构来源） | 只做结构、令牌与项目符号，**不动措辞** |

基准自身没有更高一层的基准，所以它的结构缺口只能靠其他 retail 的多数票定（票数
不足就只报，切点要人定）。官方译文（fr）用 `en-clean` 当基准。

    python src/tools/analysis/ref_clean.py --ref en.gog_1.1.2.3 --votes fr,de,es,pl,ru
    python src/tools/analysis/ref_clean.py --ref fr.gog_1.1.2.42 --base en-clean
    python src/tools/analysis/ref_clean.py --ref fr.gog_1.1.2.42 --base en-clean --write

产物落在 `build/ref/clean/<名字>-clean.toml`（派生件，与 `build/` 一起 gitignore）。
"""

import argparse
import collections
import io
import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from text import toml_io as TI            # noqa: E402
from analysis import retail_import as RI  # noqa: E402

OUT_DIR = os.path.join(ROOT, "build", "qa")

#: 参照里写成 `@$Name$`（漏了类型字母）的令牌：基准同名的是 `@X$Name$` 就照基准补。
TOK_BARE_RX = re.compile(r"@\$([^$\n]{1,60})\$")
#: 占位名的形态：`IDM_CONTEST_01_2004_LOG_01_HDR`。上市文本里没这句，mod 作者就拿键名
#: 顶上，当占位用。
IDM_RX = re.compile(r"IDM_[A-Z0-9_]+$")


def _cand(name):
    """按名字找文件。注意不要替人猜 `-clean`：短名 `en` 必须指原始 `en.*.toml`，
    否则 `resolve("en")` 会命中已有的 `en-clean.toml`，清洁就变成自己清洁自己。"""
    return [os.path.join(ROOT, "src", "orig", name + ".toml"),
            os.path.join(ROOT, "build", "ref", "clean", name + ".toml")]


def resolve(name):
    """短名或路径都能认：`en.gog_1.1.2.3`、`en`、`en-clean`、绝对路径。

    只给语言前缀（`fr`）时在 `src/orig` 里找 `fr.*.toml`，唯一命中才算数。
    """
    if os.path.isfile(name):
        return name, os.path.basename(name)[:-5] if name.endswith(".toml") else os.path.basename(name)
    for p in _cand(name):
        if os.path.isfile(p):
            return p, os.path.basename(p)[:-5]
    d = os.path.join(ROOT, "src", "orig")
    hits = sorted(f for f in os.listdir(d)
                  if f.endswith(".toml") and f.startswith(name.split("-")[0] + "."))
    if len(hits) == 1:
        return os.path.join(d, hits[0]), hits[0][:-5]
    raise SystemExit("找不到参照：%s" % name)


def load(path):
    return tomllib.loads(io.open(path, encoding="utf-8").read())


def fix_token_prefix(base, text):
    """`@$Settlers$` 这类漏了类型字母的令牌，按基准同名补回前缀（`@I$Settlers$`）。"""
    known = {}
    for m in re.finditer(r"@([A-Za-z])\$([^$\n]{1,60})\$", base):
        known.setdefault(m.group(2), []).append(m.group(0))
    fixed = [0]

    def repl(m):
        name = m.group(1)
        cands = known.get(name) or []
        if len(cands) == 1:
            fixed[0] += 1
            return cands[0]
        return m.group(0)

    return TOK_BARE_RX.sub(repl, text), fixed[0]


def align_idm(base_val, text):
    """基准只有 `IDM_` 键名、本参照却译了正文：退回键名。

    `IDM_CONTEST_01_2004_LOG_01_HDR` 这类值是 mod 作者给「上市版没有这句」留的占位，
    不是给人看的文本。德语零售把这批 2004 竞赛日志自己译了，别家只有键名——留着正文，
    下游抄参照就会把德语搬进别的语言。
    """
    if (isinstance(base_val, str) and IDM_RX.match(base_val.strip())
            and text.strip() != base_val.strip()):
        return base_val, True
    return text, False


def max_run(text, unit="<n>"):
    """一段里最长的那串连续 `unit`（`<n><n>` 记 2，单个记 1，没有记 0）。"""
    best = cur = 0
    i = 0
    while True:
        i = text.find(unit, i)
        if i < 0:
            return best
        cur = cur + 1 if i and text[i - len(unit):i] == unit else 1
        best = max(best, cur)
        i += len(unit)


def diff_snip(old, new):
    """报告里用的小片段：找出第一处不同的前后各 12 字。"""
    i = 0
    while i < min(len(old), len(new)) and old[i] == new[i]:
        i += 1
    return "%r → %r" % (old[max(0, i - 12):i + 14], new[max(0, i - 12):i + 14])


def main(argv=None):
    ap = argparse.ArgumentParser(description="把参照（基准／官方译文）对齐成 *-clean")
    ap.add_argument("--ref", required=True, help="要清洁的参照，如 en.gog_1.1.2.3")
    ap.add_argument("--base", default="", help="结构基准，如 en-clean；省了就走多数票")
    ap.add_argument("--votes", default="fr,de,es,pl,ru",
                    help="多数票来源（逗号分隔），只在没有 --base 时用")
    ap.add_argument("--patch", default="", help="手工补丁 json：{id: [[old, new], ...]}")
    ap.add_argument("--add-only", action="store_true",
                    help="只补不删：给零售版用。零售的段落划分是它自己的排版，按基准删会"
                         "把一整段挤成一行")
    ap.add_argument("--align-idm", action="store_true",
                    help="基准是 `IDM_` 占位名、本参照却写成了正文的行：对齐成那个占位名")
    ap.add_argument("--write", action="store_true", help="真写盘；默认只出报告")
    ap.add_argument("--out", default="", help="输出路径，默认 build/ref/clean/<名字>-clean.toml")
    args = ap.parse_args(argv)

    ref_path, ref_name = resolve(args.ref)
    doc, order = TI.read_doc(ref_path)
    base = load(resolve(args.base)[0]) if args.base else None
    votes = []
    if not base:
        for name in [v.strip() for v in args.votes.split(",") if v.strip()]:
            try:
                votes.append(load(resolve(name)[0]))
            except SystemExit:
                continue
    patch = {}
    if args.patch:
        patch = json.load(io.open(args.patch, encoding="utf-8"))

    out = {}
    changed, issues = [], []
    for hid, val in doc.items():
        if not isinstance(val, str):
            out[hid] = val
            continue
        text, notes = val, []
        # 占位对齐排在最前：基准只有键名、本参照却译了正文的行，先退回键名，
        # 否则后面拿一段德语去跟一个键名比结构，白忙。
        b_pre = (base or {}).get(hid)
        if args.align_idm:
            text, hit = align_idm(b_pre, text)
            if hit:
                notes.append("对齐 IDM 占位（原 %d 字正文：%s）"
                              % (len(val), val[:28].replace("\n", " ")))
        # 补丁先上：它给的是「基准里那处标签到底落在哪句末」，先定好切点，
        # 后面的自动对齐就无事可做（否则自动挑的切点会先占位，patch 的 old 串就找不到了）。
        for old, new in patch.get(hid, []):
            if text.count(old) != 1:
                issues.append((hid, "补丁片段不是唯一命中（%d 次）：%r"
                               % (text.count(old), old)))
                continue
            text = text.replace(old, new)
            notes.append("按补丁补结构")
        b = (base or {}).get(hid)
        if isinstance(b, str):
            fixed, how = RI.structural_fix(b, text, strip=not args.add_only,
                                            strict_break=args.add_only)
            if fixed != text:
                # 补 `<n>` 找不到足够句末时 `_insert_n` 会把剩下的挂在行末，挂成
                # `<n><n><n>` 一长串是一段被生生截断的信号（ru `0xe1cdc367`）。原参照
                # 本来就有这么长的连续换行才算正常，否则整条退回。
                if max_run(fixed) > max_run(text):
                    fixed = text
                    gap = len(RI.NL_RX.findall(b)) - len(RI.NL_RX.findall(text))
                    issues.append((hid, "补换行找不到合语句末（差 %d 处），切点得人定（用 --patch）"
                                   % gap))
                else:
                    notes.append("、".join(how) or "结构对齐")
                    text = fixed
            text, npfx = fix_token_prefix(b, text)
            if npfx:
                notes.append("令牌前缀 %d" % npfx)
            if collections.Counter(RI.TOK_RX.findall(b)) != collections.Counter(RI.TOK_RX.findall(text)):
                issues.append((hid, "令牌对不上（只报）：基准 %s / 清洁后 %s"
                               % (RI.TOK_RX.findall(b), RI.TOK_RX.findall(text))))
            if b.count("<t>") != text.count("<t>"):
                issues.append((hid, "`<t>` 对不上（只报）"))
        # 多数票放到最后看：刚按补丁补齐的行不该再报一次。
        if votes and not isinstance(b, str):
            got = len(RI.NL_RX.findall(text))
            cnt = collections.Counter(len(RI.NL_RX.findall(v[hid]))
                                      for v in votes if isinstance(v.get(hid), str))
            if cnt:
                mode, n = cnt.most_common(1)[0]
                if mode != got and n >= 3:
                    issues.append((hid, "`<n>` 只有 %d 处，%d 个语言都是 %d 处"
                                   "（多数票，切点要人定，用 --patch）"
                                   % (got, n, mode)))
                elif mode != got:
                    issues.append((hid, "`<n>` %d 处，票数不足（%s）" % (got, dict(cnt))))
        out[hid] = text
        if text != val:
            changed.append((hid, "、".join(notes), diff_snip(val, text)))

    # 输出名按语言取：`en.gog_1.1.2.3` → `en-clean.toml`（用户口径就喊「en-clean」）。
    name = ref_name.split(".")[0]
    if name.endswith("-clean"):
        name = name[:-6]
    path = args.out or os.path.join(ROOT, "build", "ref", "clean", name + "-clean.toml")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    head = ["# 参照层清洁版：%s ← %s" % (name, "en-clean" if base else "多数票 " + args.votes),
            "# 只对齐结构（换行标签／项目符号／令牌前缀），不改措辞；原参照文件仍是权威。",
            "# 由 analysis/ref_clean.py 生成，可随时重建。"]
    if args.write:
        TI.write_doc_atomic(path, out, order, head)

    lines = ["# 参照层清洁：%s" % name, "",
             "改动 %d 条；剩 %d 处对不上（只报不修）" % (len(changed), len(issues)),
             "清洁版：%s" % path, ""]
    if changed:
        lines.append("## 改动明细（只动结构）")
        for hid, note, snip in changed:
            lines.append("  %s  %s  %s" % (hid, note, snip))
    if issues:
        lines.append("")
        lines.append("## 留着没修的")
        for hid, issue in issues:
            lines.append("  %s  %s" % (hid, issue))
    report = "\n".join(lines) + "\n"
    os.makedirs(OUT_DIR, exist_ok=True)
    io.open(os.path.join(OUT_DIR, "ref_clean_%s.txt" % name), "w", encoding="utf-8").write(report)
    print(report)
    if not args.write:
        print("（只出报告，加 --write 才写盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
