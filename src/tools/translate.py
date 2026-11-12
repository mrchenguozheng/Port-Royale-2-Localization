#!/usr/bin/env python
# coding: utf-8
r"""src/tools/translate.py — 译文数据层：合并、进度

    python src/tools/translate.py status                    # 看翻译进度

为什么要有这个脚本
------------------
3535 条、32 万字符，手工编辑 toml 出错的后果很严重：
占位符 %1 少一个、游戏里就显示字面 "%1"；标签坏了、超宽的整行
**直接不显示**。所以「翻译」这件事必须配一个机械的校验环节，
而不是直接改文件。

【本脚本的定位】数据层，不是给译者用的工作流：
  * load_toml —— 合并层，编译、编辑器、审计都走它，形态只有一份；
  * status —— 看进度。编辑器只显示「第 N 页 / 共 X 条」，
    不显示「已译多少」，这个命令补上那一块；
  * 占位符与标签规则**不在本文件**，在 shared\core\validate.py ——
    那里是唯一一份实现，编译脚本与两个编辑器后端都调它，
    本文件只是把 tokens / tag_profile 原样借出来给旧调用点用。

以前这里还有 export / check 两个子命令，走的是「导出成 JSONL →
在别处翻译 → 校验 JSONL」的流程。但那条流程**没有写回的一步**，
导出后回不去。编辑器（src\editor\）已经接管校验与写回，
而且比这条命令更严：校验 /api/check、写回 /api/save，所以已删除。

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
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                     # 仓库的 src\
ROOT = os.path.dirname(SRC)                     # 仓库根
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 占位符与标签规则只有一份，在 shared\core\validate.py。
# 这里转出来，是为了让 `import translate as T` 的老调用点（编辑器、
# 审计脚本）继续能用 T.tokens / T.tag_profile。
from shared.core.validate import PH_RE, tag_profile, tokens  # noqa: E402

STRINGS_DIR = os.path.join(SRC, "live")
REFERENCES_DIR = os.path.join(SRC, "orig")

#: 译文主源：live\<语言>.toml，**每条一行**：
#:     "0xd2d0a572" = "萧条"
#: 文件名以语言代码开头，没有块头也没有字段名，所以语言代码与文件里
#: 的内容是同一个名字，不需要任何映射表。
#: 只读参考原文放在 orig\ 目录：
#:     orig\en.gog_1.1.2.3.toml    英文原文（GOG 1.1.2.3 原版表），合并基准
#:     orig\fr.gog_1.1.2.42.toml   法文原文（GOG 1.1.2.42 原版表）
#: 文件名里带来源与版本：这两份是**从原版 exe 里原样提取**的，不经过我们的
#: 导出/整理，所以 `<n>`、行尾空格都保持原样。版本号不同，两边条目数可能
#: 对不齐（法语 3571 vs 英文 3548），合并时按 id 对齐、多退少空。
#: 其余 live\*.toml 是可编辑的译文，文件名即语言代码。
#: 语言列表不写死 —— 加一种语言只需把 <代码>.toml 放进 live\。
BASE_LANG = "en.gog_1.1.2.3"

#: 只读参考语言：参与 id 顺序与占位符校验，但不提供译文。
REFERENCE_LANGS = ("en.gog_1.1.2.3", "fr.gog_1.1.2.42")
#: 法文原文的字段名（合并结果里 lang 字段就是文件名，没有短键别名）。
FR_LANG = "fr.gog_1.1.2.42"


def lang_path(code):
    """语言代码 -> 文件路径。只读参考在 orig\\ 目录下。"""
    base = REFERENCES_DIR if code in REFERENCE_LANGS else STRINGS_DIR
    return os.path.join(base, code + ".toml")


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
    """status 默认操作的那个译文语言字段名。

    取 src\\live 下第一个可编辑语言；一个译文都没有时报错，
    因为那样「已译 / 待译」根本没有对象。
    """
    langs = target_langs()
    if not langs:
        raise SystemExit(r"%s 下没有任何可编辑的 *.toml 译文文件。" % STRINGS_DIR)
    return langs[0]

# 占位符与标签规则已移到 shared\core\validate.py（tokens / tag_profile）。
# 编译脚本与两个编辑器后端原先各有一份，四份里只有一份处理了紧邻占位符
# 与 %02 补零，其余会静默误判。本文件只把 import 进来的转出去给老调用点。

# ── 合并 ────────────────────────────────────────────────────

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


# ── 进度 ────────────────────────────────────────────────────


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

    p = sub.add_parser("status", help="看进度")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.set_defaults(fn=cmd_status)

    args = ap.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()