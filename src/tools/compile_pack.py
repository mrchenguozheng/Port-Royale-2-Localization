#!/usr/bin/env python
# coding: utf-8
r"""src/tools/compile_pack.py — 把 translations\<语言>.toml 编译成引擎能读的语言包

    python src/tools/compile_pack.py                        # 编 zh（默认）
    python src/tools/compile_pack.py --lang de --out D:\\Games\\PR2

只做一件事：**占位符校验**。译文里的 %1 / @D$EndDate$ 必须与原文
一一对应，种类、数量、写法全都要对；顺序可以按中文语序调。

references\ 下的 en / fr 是校对译文的依据，但不做防篡改校验：
合并层（translate.load_toml）本身就是从这两个文件读出 en / fr 的，
拿它们校验自己永远相等，报不出任何东西。

【不做的事】不检查行宽。行宽上限因界面而异，没有全局值，
靠一套粗略字宽推出来的数字只会误导人。而中文不像英文那样天然用空格分界，
引擎会把一长串汉字连同标点当成一个超宽单词，整条**丢弃（不显示）**，
所以过宽的译文必须人工在游戏里验收。
"""

import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                              # 仓库的 src\
ROOT = os.path.dirname(SRC)                              # 仓库根
DEFAULT_OUT = os.path.join(ROOT, "build", "PR2Packs")

#: 只读参考语言：英文 / 法文原文。**不参与编辑，也不生成语言包**
#: （用户2026-10-19 明确要求）。en 还兼作 id 顺序与校验的基准。
REFERENCE_LANGS = ("en", "fr")

# ---------------------------------------------------------------- 占位符

# 占位符的提取规则**只有一份**，在 translate.py 里（tokens / tag_profile）。
# 那里处理了三个坑：
#   1) 剥标签时用空格替换 —— 否则紧邻的占位符会粘成 "%2%1"，
#      被一条贪婪正则读成根本不存在的 "%21"；
#   2) "%02" 这类补零写法归一化成 "%2" —— 同一参数的不同字面不该算不一致；
#   3) 字体标记 <f:fonts\A.res> 先剥掉，否则会被误认成占位符
#      （全量里有 67 条含它）。
#
# 以前这里另有一份自己的实现，它**不**做第 2 条归一化，于是原文写 "%02u"、
# 译文写 "%2u" 会被误报成「少了 %02」+「多了 %2」两条假警报。
# 真实数据里含 "%02" 的只有 1 条（0x33c2c533），且译文也写 %02，
# 所以当时没暴露 —— 但这是等着炸的地雷。
#
# 本模块只需要「集合」，translate.tokens 返回排序后的 list，
# 所以这里包一层转成 set —— 集合差（a - b）是本模块的用法。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import translate as _T


def tokens(s):
    r"""提取占位符集合（set）。

    规则见 translate.tokens —— 那是唯一的一份实现。
    """
    return set(_T.tokens(s))


def check_placeholders(h, en, txt, errors, warnings):
    """比对译文与原文的占位符集合。

    【少 = 警告，多 = 错误】两种情况都会让引擎出乱码，但性质不同：
      * **少了**：多半是翻译时手滑漏掉了，改回来就行；
      * **多了**：可能是刻意加的 —— 有些字符串原文是字面数字（比如
        "a discount of 5%"），译文若改用 %1 动态传参，是完全合理的做法。
        实测已有译文里就有 4 条这么干（0x1E8D41A5 等）。
        所以这里只报错误、不自动改，把判断权交给译者。
    占位符的顺序不算错 —— 各语言语序不同，位置可以自由调整。
    """
    a, b = tokens(en), tokens(txt)
    miss, extra = a - b, b - a
    if miss:
        warnings.append("%s 译文少了占位符：%s（游戏里会显示成字面量）"
                        % (h, " ".join(sorted(miss))))
    if extra:
        errors.append("%s 译文多了占位符：%s（确认是刻意为之的话可忽略）"
                      % (h, " ".join(sorted(extra))))
    return not miss and not extra


#: 未翻译条目的占位译文特征。编译时必须跳过它们的校验 ——
#: 占位文本本来就只有前 10 个字符，英文里的占位符必然被截掉，
#: 校验它只会产出 762 条假报警，把真问题淹掉。
RE_PLACEHOLDER = re.compile(r"^0x[0-9a-f]{8} \| ")


def is_placeholder(txt):
    return bool(RE_PLACEHOLDER.match(txt))


# ---------------------------------------------------------------- 输出

# 语言包**不带任何说明头**，一个 hash 一行就完事。
# 曾经在这里塞过一大段注释（格式说明 + 排版规则 + 「本文件是自动生成的」提醒），
# 现在移到 docs/译文与语言包.md 了：
#   · 排版规则是**给人看的**，而语言包是给机器读的（DLL 按行解析），
#     编译产物里不该夹着给人读的东西；
#   · 语言包是 gitignore 的产物，用户在仓库里看不到它，
#     把「这是自动生成的、别手改」写在产物里等于写给空气看；
#   · 那段提醒每次编译都写一遍，纯冗余字节。
#
# 唯一保留的是**空行**都不加：第一个字节就是第一条数据，
# 免得解析时先要跳过什么。


def _load_merged():
    """把所有语言 toml 按 id 合并成扁平的 {s:[{id,ctx,<语言>…}]}。

    统一走 translate.py 的合并层，保证各工具读到的形态完全一致。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import translate as T
    return T.load_toml()


def _default_lang():
    """--lang 不给时的默认语言：translations\\ 下第一个可编辑语言。"""
    import translate as T
    langs = T.target_langs()
    if not langs:
        raise SystemExit(r"%s 下没有任何可编辑的 *.toml 译文文件。"
                         % T.STRINGS_DIR)
    return langs[0]


def build(lang, out_dir, strict):
    # en / fr 是**只读参考语言**（用户 2026-10-19 明确：不参与编辑、不导出）。
    # 它们是原文，不是译文 —— 生成 en.txt / fr.txt 交给引擎等于用「原始英文」
    # 覆盖游戏，等于没汉化。所以直接拒绝，而不是打个警告继续跑。
    if lang in REFERENCE_LANGS:
        print("拒绝：%s 是原文参考语言（%s），不生成语言包。"
              % (lang, "/".join(REFERENCE_LANGS)))
        print("      英文/法文只用于校对译文与 id 顺序对照。")
        return 2

    # 合并层的字段名就是语言代码本身（文件名即语言名，不做映射）。
    field = lang
    doc = _load_merged()

    errors, warnings = [], []

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s.txt" % lang)
    lines = []
    n = n_ph = 0

    for s in doc.get("s", []):
        h = s.get("id", "").lower()
        txt = s.get(field)
        if not txt:
            continue
        # 占位译文跳过校验：它只有前 10 个字符，占位符必然不全。
        # 这不是放水 —— 它本来就没翻译，翻译后自然会进入校验。
        if not is_placeholder(txt):
            check_placeholders(h, s.get("en", ""), txt, errors, warnings)
        # 【坑】hash 必须写成**大写**（0x30A45770），与既有语言包一致。
        # patch.js 的合并逻辑按大写规范化 hash，产物若写成小写，
        # 用户手改过的条目就识别不出来，合并会静默失效（测试 test_patch.js
        # 会抓到）。小写 id 只存在于 src/translations\*.toml 里作为内部键。
        lines.append("%s = %s\n" % (h.upper().replace("0X", "0x"),
                                    txt.replace("\n", "<n>")))
        n += 1
        if is_placeholder(txt):
            n_ph += 1

    # 一条都没编出来就**不写文件**：写一个 0 条的语言包毫无用处，
    # 装进游戏目录等于没汉化，而调用方只看「文件在不在」。
    # 成因通常是 translations\<语言>.toml 压根不存在 ——
    # 合并层只为实际存在的语言建字段。
    if n == 0:
        print("错误：没有编出任何条目，未生成 %s" % path)
        print("      找不到 %s\\%s.toml，或它里面没有条目。"
              % (os.path.join(SRC, "translations"), lang))
        print("      加一种语言：python src\\tools\\new_lang.py"
              " --new-lang %s" % lang)
        return 1

    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(lines))

    print("已生成 %s" % path)
    print("  条目 %d 条，其中占位未翻译 %d 条" % (n, n_ph))
    if warnings:
        print("\n警告 %d 条：" % len(warnings))
        for w in warnings[:20]:
            print("  ! " + w)
        if len(warnings) > 20:
            print("  … 还有 %d 条" % (len(warnings) - 20))
    if errors:
        print("\n错误 %d 条：" % len(errors))
        for e in errors[:30]:
            print("  x " + e)
        if len(errors) > 30:
            print("  … 还有 %d 条" % (len(errors) - 30))
        if strict:
            return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="把 src/translations\\<语言>.toml 编译成引擎语言包")
    ap.add_argument("--lang", default="", help="语言代码，默认 translations\\ 下第一个可编辑语言")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录")
    ap.add_argument("--strict", action="store_true", help="有错误时返回非零")
    a = ap.parse_args()
    lang = a.lang
    if not lang:
        lang = _default_lang()
    return build(lang, a.out, a.strict)


if __name__ == "__main__":
    raise SystemExit(main())