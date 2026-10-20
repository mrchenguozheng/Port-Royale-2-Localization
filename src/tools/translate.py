#!/usr/bin/env python
# coding: utf-8
r"""src/tools/translate.py — src/translations\<语言>.toml 的翻译流水线

    python src/tools/translate.py export --out work.jsonl   # 导出待译条目
    python src/tools/translate.py check  work.jsonl         # 校验译文（占位符/标签）
    python src/tools/translate.py status                    # 看进度

为什么要有这个脚本
------------------
3535 条、32 万字符，手工编辑 toml 出错的后果很严重：
占位符 %1 少一个、游戏里就显示字面 "%1"；标签坏了、超宽的整行
**直接不显示**。所以「翻译」这件事必须配一个机械的校验环节，
而不是直接改文件。

占位符的两条判定
----------------
1) **数量与种类**必须与原文一致，顺序可以按中文语序调。
2) @P$TeacherName$ 与 @N$TeacherName$ 是**不同的**引用（同一变量配不同前缀），
   比对时必须按完整 token 比，不能只比变量名。

段落分隔符 |
--------------
原文自带的段落分隔符（494 条里有），作用与 <n> 类似。
译文里**数量与位置要对应**，不能因为中文短就并段。
"""

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                     # 仓库的 src\
ROOT = os.path.dirname(SRC)                     # 仓库根
STRINGS_DIR = os.path.join(SRC, "translations")

#: 译文主源：translations\<语言>.toml，**每条一行**：
#:     "0xd2d0a572" = "萧条"
#: 文件名以语言代码开头，没有块头也没有字段名，所以语言代码与文件里
#: 的内容是同一个名字，不需要任何映射表。
#: 只读参考原文放在 references\ 子目录：
#:     references\en.gog_1.1.2.3.toml    英文原文（GOG 1.1.2.3 原版表），合并基准
#:     references\fr.gog_1.1.2.42.toml   法文原文（GOG 1.1.2.42 原版表）
#: 文件名里带来源与版本：这两份是**从原版 exe 里原样提取**的，不经过我们的
#: 导出/整理，所以 `<n>`、行尾空格都保持原样。版本号不同，两边条目数可能
#: 对不齐（法语 3571 vs 英文 3548），合并时按 id 对齐、多退少空。
#: 其余 translations\*.toml 是可编辑的译文，文件名即语言代码。
#: 语言列表不写死 —— 加一种语言只需把 <代码>.toml 放进 translations\。
BASE_LANG = "en.gog_1.1.2.3"

#: 只读参考语言：参与 id 顺序与占位符校验，但不提供译文。
REFERENCE_LANGS = ("en.gog_1.1.2.3", "fr.gog_1.1.2.42")
#: 导出 / 校验里「法文那列」的字段名（导出产物仍沿用 en / fr 两个短键，
#: 免得改掉外部脚本的约定）。
FR_LANG = "fr.gog_1.1.2.42"


def lang_path(code):
    """语言代码 -> 文件路径。只读参考在 references\\ 子目录下。"""
    return os.path.join(STRINGS_DIR,
                        "references" if code in REFERENCE_LANGS else "",
                        code + ".toml")


def target_langs():
    """可编辑的译文语言代码，按文件名排序（不含只读参考）。"""
    if not os.path.isdir(STRINGS_DIR):
        return []
    # keep_original.toml 是「原样保留」清单，不是语言文件，跳过
    return sorted(f[:-5] for f in os.listdir(STRINGS_DIR)
                  if f.endswith(".toml") and not f.startswith("_")
                  and f != "keep_original.toml"
                  and f[:-5] not in REFERENCE_LANGS)


def all_langs():
    """合并时读取的全部语言代码：只读参考在前，译文在后。"""
    return [c for c in REFERENCE_LANGS if os.path.exists(lang_path(c))] \
        + target_langs()


def target_field():
    """export / check / status 默认操作的那个译文语言字段名。

    取 translations\\ 下第一个可编辑语言；一个译文都没有时报错，
    因为那样「已译 / 待译」根本没有对象。
    """
    langs = target_langs()
    if not langs:
        raise SystemExit(r"%s 下没有任何可编辑的 *.toml 译文文件。" % STRINGS_DIR)
    return langs[0]

#: 占位文本的标记形态。未翻译的都是这个形状：
#: 开头是 8 位十六进制哈希（有时被截成 6~7 位），然后竖线。
PH_RE = re.compile(r"^\s*0x[0-9a-fA-F]{6,8}\s*\|")

# ── 占位符 ──────────────────────────────────────────────────

#: 脚本变量 @前缀$变量名$ —— 首尾两个 $ 都是必需的。
#: 实测 3548 条原文里 770 处引用，770 处全部带尾 $，零例外。
RE_SCRIPT = re.compile(r"@[A-Za-z]\$[A-Za-z_][A-Za-z_0-9]*\$")
#: 位置参数起点。用查找切成一段一段，每段独占匹配。
#: 【坑】剥掉标签后两个占位符会紧邻成 "%2%1"（原文 <c><ts:175>%2<t>…%1
#: 剥掉 <t> 就是这样）。若直接用一条贪婪正则去搜索，"%2%1" 会被读成
#: 一个根本不存在的 "%21"。所以先切段、再逐段整匹配。
RE_POS_SPLIT = re.compile(r"%\d+")


def _pos_tokens(s):
    """提取位置参数，正确处理紧邻的情况。'%2%1' -> ['%2', '%1']"""
    return [m.group(0) for m in RE_POS_SPLIT.finditer(s)]


def tokens(text):
    """把一段文本拆成「占位符 token 列表」，供比对用。

    顺序会被排序，因为中文语序允许调整占位符先后 —— 比对的是
    「种类与数量的集合」，不是先后。

    ★ 两个必须绕开的坑：
    1) 紧邻的位置参数：原文 <c><ts:175>%2<t>…%1<t> 剥掉标签后变成 "%2%1"，
       用一条贪婪正则去搜会读成根本不存在的 "%21"。所以剥标签时**用空格
       替换标签**，把紧邻情况天然隔开。
    2) %02 这类补零写法：与 %2 是同一个参数，但字面不同。比对时先归一化
       （去掉前导零），否则原文 %02、译文 %2 会被误报成不一致。
    """
    if text is None:
        return []
    t = str(text)
    # 用空格替换标签：既剥掉 <n>/<o:..>，也把可能紧邻的占位符隔开
    t = RE_TAG_ALL.sub(" ", t)
    out = set()
    for m in RE_SCRIPT.finditer(t):
        out.add(m.group(0))
    for m in RE_POS_ANY.finditer(t):
        # 归一化：%02 -> %2、%002 -> %2。同一参数的不同写法不该算不一致。
        out.add("%" + str(int(m.group(0)[1:])))
    return sorted(out)


#: 任意位置参数（查找用，先把紧邻情况隔开就安全了）
RE_POS_ANY = re.compile(r"%0*\d+")
#: 任何排版标签（用于剥离；不做结构判断）
RE_TAG_ALL = re.compile(r"</?[a-zA-Z][^>]*>")


#: 排版标签。比对时只看数量与配对，不看具体参数。
RE_TAG = re.compile(r"<(/?)(n(?:[:>][^>]*)?|o(?::[^>]*)?|f[^>]*|t|c|tc|ts(?::[^>]*)?)\s*>")


def tag_profile(text):
    """标签的「轮廓」：排序后的标签名列表，用来比对结构是否一致。

    只比数量与名字，不比 <o:0xFFF2FAAD> 里的颜色值 —— 译文可以换颜色。
    但 <n> 的数量必须一致：少一个 <n> 可能导致整行超宽而不显示。
    """
    if text is None:
        return []
    names = []
    for m in RE_TAG.finditer(str(text)):
        closing, name = m.group(1), m.group(2)
        base = name.split(":")[0]
        names.append(("/" if closing else "") + base)
    return sorted(names)


# ── 导出 ────────────────────────────────────────────────────

def load_toml():
    """读取全部语言文件，按 hash 合并成 [{id, ctx, <语言>…}]。

    每种语言一个字段，字段名就是语言代码（en / fr / zh / …），
    所以加一种语言不需要改这里。对外形态仍是扁平的 s 列表，
    下游脚本（审计、compile_pack、各种 fill_batch）只需改字段名。
    """
    try:
        import tomllib
    except ImportError:
        raise SystemExit("需要 Python 3.11+（tomllib）")

    langs = all_langs()
    base = lang_path(BASE_LANG)
    if not os.path.exists(base):
        raise SystemExit(
            r"找不到 %s —— 它是合并的基准文件，没有它就无法确定 id 顺序。" % base)

    def read(path):
        with open(path, "rb") as f:
            doc = tomllib.load(f)
        # ctx 是子表，不算条目；其余顶层键全是 hash -> 译文
        return [(k, v) for k, v in doc.items() if k != "ctx"], doc.get("ctx", {})

    base_rows, ctx = read(base)
    blank = dict.fromkeys(langs, "")
    merged = {rid: dict(blank, id=rid, ctx=ctx.get(rid, ""))
              for rid, _t in base_rows}
    order = [rid for rid, _t in base_rows]
    for rid, t in base_rows:
        merged[rid][BASE_LANG] = t

    #: 参考语言里缺了哪些 id（版本差异）。参照时把它们标出来，
    #: 免得「空」和「这一版根本没这条」混在一起。
    missing = {}

    for lang in langs:
        path = lang_path(lang)
        if lang == BASE_LANG or not os.path.exists(path):
            continue
        rows, _ = read(path)

        if lang in REFERENCE_LANGS:
            # 参考原文是**原版提取**，版本可能与基准不同（法语 1.1.2.42 比
            # 英文 1.1.2.3 多 42 条、少 19 条）。做参照时按 id 对齐即可：
            # 多出来的丢掉，缺的记进 missing —— 它们不参与译文，也不进语言包。
            extra = 0
            have = set()
            for rid, t in rows:
                have.add(rid)
                if rid in merged:
                    merged[rid][lang] = t
                else:
                    extra += 1
            lack = [rid for rid in order if rid not in have]
            if lack:
                missing[lang] = lack
            if extra:
                sys.stderr.write(
                    "提示：%s 有 %d 条不在基准表里（版本差异），参照时已忽略。\n"
                    % (lang, extra))
            continue

        # 对齐检查（只对可编辑译文）：条目数与顺序必须与基准一致。
        # 少一条只是显示问题，多一条会让后面的 hash 全部错位 —— 必须挡住。
        ids = [r for r, _ in rows]
        if ids != order:
            if len(ids) != len(order):
                raise SystemExit(
                    "%s.toml 有 %d 条，%s.toml 有 %d 条——条目数不一致，无法合并。"
                    % (lang, len(ids), BASE_LANG, len(order)))
            n = next(i for i, (a, b) in enumerate(zip(ids, order)) if a != b)
            raise SystemExit(
                "%s.toml 第 %d 条是 %s，%s.toml 同位置是 %s——条目顺序不一致。"
                % (lang, n, ids[n], BASE_LANG, order[n]))
        for rid, t in rows:
            merged[rid][lang] = t

    return {"s": [merged[i] for i in order], "missing": missing}


def entries(doc):
    return doc.get("s", [])


def cmd_export(args):
    doc = load_toml()
    field = args.lang or target_field()
    out = []
    for e in entries(doc):
        txt = e.get(field, "")
        if not PH_RE.match(txt):
            continue        # 已译或已空，跳过
        if args.limit and len(out) >= args.limit:
            break
        out.append({
            "id": e.get("id", ""),
            "en": e.get(BASE_LANG, ""),
            "fr": e.get(FR_LANG, ""),
            "ctx": e.get("ctx", ""),
            field: txt,
        })
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print("已导出 %d 条 -> %s" % (len(out), args.out))


# ── 校验 ────────────────────────────────────────────────────

def cmd_check(args):
    field = args.lang or target_field()
    rows = [json.loads(l) for l in io.open(args.file, encoding="utf-8") if l.strip()]
    errors = []
    ok = 0
    for r in rows:
        zh = r.get(field, "")
        if not zh:
            continue
        if PH_RE.match(zh):
            errors.append((r["id"], "译文仍是占位文本（没翻）"))
            continue
        # 占位符
        en_t, zh_t = tokens(r["en"]), tokens(zh)
        if en_t != zh_t:
            miss = [t for t in en_t if t not in zh_t]
            extra = [t for t in zh_t if t not in en_t]
            errors.append((r["id"], "占位符不一致　缺 %s　多 %s" % (miss or "无", extra or "无")))
            continue
        # 标签结构：译文**不得**新增 <n>/<o>/<f>/<c>/<t> 任何标签。
        # 换行只在原文已有 <n> 或 | 的位置换；中文自然要另起行时，
        # 交给渲染器按宽度自动折行，不靠手工插 <n>。
        en_p, zh_p = tag_profile(r["en"]), tag_profile(zh)
        if en_p != zh_p:
            add = [t for t in zh_p if zh_p.count(t) > en_p.count(t)]
            miss = [t for t in en_p if en_p.count(t) > zh_p.count(t)]
            hint = ""
            if add:
                hint = "　（译文擅自新增 %s）" % sorted(set(add))
            errors.append((r["id"], "标签结构不一致　原文 %s　译文 %s%s"
                           % (en_p, zh_p, hint)))
            continue
        ok += 1

    if errors:
        print("发现 %d 个问题（通过 %d 条）：" % (len(errors), ok))
        for i, (h, m) in enumerate(errors[:60]):
            print("  %s  %s" % (h, m))
        if len(errors) > 60:
            print("  … 还有 %d 条" % (len(errors) - 60))
        return 1
    print("全部通过：%d 条" % ok)
    return 0


# ── 写回 ────────────────────────────────────────────────────


def cmd_status(args):
    field = args.lang or target_field()
    doc = load_toml()
    es = entries(doc)
    total = len(es)
    done = sum(1 for e in es if not PH_RE.match(e.get(field, "")))
    print("[%s] 共 %d 条，已译 %d 条（%.1f%%），待译 %d 条"
          % (field, total, done, 100.0 * done / max(1, total), total - done))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("export", help="导出待译条目")
    p.add_argument("--out", default=os.path.join(ROOT, "work", "strings.jsonl"))
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("check", help="校验译文")
    p.add_argument("file")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("status", help="看进度")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.set_defaults(fn=cmd_status)

    args = ap.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()