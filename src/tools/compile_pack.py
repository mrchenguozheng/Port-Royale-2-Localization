#!/usr/bin/env python
# coding: utf-8
r"""src/tools/compile_pack.py — 把 translations\<语言>.toml 编译成引擎能读的语言包

    python src/tools/compile_pack.py                        # 编 zh（默认）
    python src/tools/compile_pack.py --lang de --out <游戏目录>

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

#: 只读参考语言：英文 / 法文原文。**不参与编辑，也不生成语言包**。
#: 实际名单以 translate.REFERENCE_LANGS 为准（这里是 import 不到时的兜底常量，
#: 文件名带来源与版本：en.gog_1.1.2.3 / fr.gog_1.1.2.42）。
REFERENCE_LANGS = ("en.gog_1.1.2.3", "fr.gog_1.1.2.42")

# ---------------------------------------------------------------- 占位符

#: 脚本变量 @前缀$变量名$ —— 结构是「@前缀$」+「变量名$」，**首尾两个 $ 都是必需的**。
#: 实测 3548 条原文里共 770 处引用，**770 处全部带尾 $，零例外**
#: （包括看起来像裸变量的 @I$Val1$ 和 @n$Nation2$，尾 $ 都在）。
#: 所以这里用必需的 $ 而不是 \$? —— 译文漏掉尾 $ 时必须报错，
#: 可选的写法会把它当成合法，静默放过。
#: 比对时必须用**完整 token**：@P$TeacherName$ 与 @N$TeacherName$
#: 是两个不同的引用（同一变量名配不同前缀），别只比变量名。
RE_SCRIPT = re.compile(r"@[A-Za-z]\$[A-Za-z_][A-Za-z_0-9]*\$")
#: 位置参数起点。用**查找**把它切成一段一段，每段独占匹配。
#: 【坑】剥掉标签后两个占位符会紧邻成 "%2%1"（原文 <c><ts:175>%2<t>…%1
#: 剥掉 <t> 就是这样）。若直接用一条贪婪正则去搜索，"%2%1" 会被读成
#: 一个根本不存在的 "%21"。所以先切段、再逐段整匹配。
RE_POS_SPLIT = re.compile(r"%\d+")


def _pos_tokens(s):
    """提取位置参数，正确处理紧邻的情况。'%2%1' -> ['%2', '%1']"""
    return [m.group(0) for m in RE_POS_SPLIT.finditer(s)]
#: 右对齐填充标记 %1% —— 属于同一个参数，校验时忽略
#: 【坑】后面必须要求「不是数字」。否则紧邻的两个占位符 "%2%1" 会被当成
#: "%2%" 这个填充标记 + "1"，合并成一个不存在的 "%21"。
RE_PAD = re.compile(r"%(0?\d+)%(?!\d)")
#: 字体标记 —— 不是占位符，提取前必须剥掉
RE_FONT = re.compile(r"<f:[^>]*>")
#: 其他标签
RE_TAG = re.compile(r"<[^>]*>")


def tokens(s):
    r"""提取占位符集合。返回 (set, has_error)。

    【关键】先剥字体标记和标签，否则 `<f:fonts\A.res>` 会被误认成占位符
    （全量里有 67 条含它）。
    """
    s = RE_FONT.sub("", s)
    s = RE_TAG.sub("", s)
    s = RE_PAD.sub(r"%\1", s)          # %1% -> %1，避免重复计数
    out = set(RE_SCRIPT.findall(s))
    out |= set(_pos_tokens(s))          # 紧邻的 %N 也要切对
    return out


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


#: 译文与原文里用 " | " 表示换行，而**引擎只认 <n>**。
#: 这里必须换掉：把竖线原样交给引擎，屏幕上就是一行行竖线
#: （实测：test_en 的段落处显示 "| Your convoy is in..."，而同一句在原版里是分段）。
#: 只换被空白包着、或位于串首/串尾的竖线；`<|>` 里的字面竖线放过 ——
#: 0x11f0398f 是字符清单，正文里就有 `<|>`。
RE_PIPE_BREAK = re.compile(r"(?<!<)\s*\|\s*(?!>)")


#: 必须原样保留英文的条目（法律声明、第三方版权）。
#: 编译时强制用英文原文，译文里写成什么都覆盖掉。
KEEP_ORIGINAL = {
    "0xfc512ea5": "Miles Sound System / RAD Game Tools 版权声明",
}


def to_engine(txt):
    """把 toml 里的排版约定翻成引擎认的写法。

    * `|`（段落/换行分隔符）  -> `<n>`
    * 真正的换行符            -> `<n>`
    两件事在同一个地方做，免得以后又有人只改一半。
    """
    return RE_PIPE_BREAK.sub("<n>", txt).replace("\n", "<n>")


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
    # 参考原文**不参与编译**：生成 en.txt / fr.txt 交给引擎等于用「原始英文」
    # 覆盖游戏，等于没汉化。所以直接拒绝，而不是打个警告继续跑。
    # 名单问 translate —— 那里是唯一一份（references\en.gog_1.1.2.3 之类）。
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import translate as T
    if lang in T.REFERENCE_LANGS:
        print("拒绝：%s 是原文参考语言（%s），不生成语言包。"
              % (lang, "/".join(T.REFERENCE_LANGS)))
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
        if h in KEEP_ORIGINAL:
            eng = s.get(T.BASE_LANG, "") or txt
            if txt != eng:
                warnings.append("%s 是必须原样保留的文本（%s），已改用英文原文"
                                % (h, KEEP_ORIGINAL[h]))
            txt = eng
        # 占位译文跳过校验：它只有前 10 个字符，占位符必然不全。
        # 这不是放水 —— 它本来就没翻译，翻译后自然会进入校验。
        if not is_placeholder(txt):
            check_placeholders(h, s.get(T.BASE_LANG, ""), txt, errors, warnings)
        # 【坑】hash 必须写成**大写**（0x30A45770），与既有语言包一致。
        # patch.js 的合并逻辑按大写规范化 hash，产物若写成小写，
        # 用户手改过的条目就识别不出来，合并会静默失效（测试 test_patch.js
        # 会抓到）。小写 id 只存在于 src/translations\*.toml 里作为内部键。
        lines.append("%s = %s\n" % (h.upper().replace("0X", "0x"),
                                    to_engine(txt)))
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
    ap.add_argument("--no-fonts", action="store_true",
                    help="只编语言包，不检查/重建字体（批量编译时由调用方统一做）")
    a = ap.parse_args()
    lang = a.lang
    if not lang:
        lang = _default_lang()
    code = build(lang, a.out, a.strict)

    # 编完语言包顺手检查字体：译文里出现新字（比如新补的「嫩」）时，
    # 字体不重裁就会画成空白。字体出错不算构建失败 —— 语言包本身没问题。
    if code == 0 and not a.no_fonts:
        try:
            import subset_fonts
            ok, msg = subset_fonts.ensure_fonts(log=lambda m: print(m))
            print("字体：" + msg)
            if not ok:
                print("（部署时字体不会更新；详见上一行提示）")
        except Exception as exc:                  # 字体只是附带的，别拖垮构建
            print("字体检查跳过：%s" % exc)
    return code


if __name__ == "__main__":
    raise SystemExit(main())