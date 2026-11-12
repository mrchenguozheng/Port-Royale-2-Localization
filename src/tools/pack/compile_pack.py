#!/usr/bin/env python
# coding: utf-8
r"""src/tools/pack/compile_pack.py — 把 src\translations\<语言>.toml 编译成引擎语言包

    python src/tools/pack/compile_pack.py                        # 编 zh（默认）
    python src/tools/pack/compile_pack.py --lang de --out <输出目录>

只做一件事：**占位符校验**。译文里的 %1 / @D$EndDate$ 必须与原文
一一对应，种类、数量、写法全都要对；顺序可以按中文语序调。

编译前先在内存里套一遍排版规则（`src/tools/text/engine_text.py`），并把结果
写到 build\engine_text\<语言>.toml 供人查看。译文层（src\translations\）是
唯一手改层，引擎文本是构建产物，不进仓库。

src\orig\ 下的 en / fr 是校对译文的依据，但不做防篡改校验：
合并层（translate.load_toml）本身就是从这两个文件读出 en / fr 的，
拿它们校验自己永远相等，报不出任何东西。

【不做的事】不检查行宽。控件到底多宽**没有在游戏里实测过**，
拿字体算出来的像素只会误导人（这条结论见 docs/翻译局限.md）。
中文这类不用空格分词的语言，引擎会把一长串汉字当成一个超宽单词，
整条**丢弃（不显示）**，所以过宽的译文必须人工在游戏里验收。
"""

import argparse
import io
import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
SRC = os.path.dirname(TOOLS)                              # 仓库的 src\
ROOT = os.path.dirname(SRC)                              # 仓库根
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
DEFAULT_OUT = os.path.join(ROOT, "build", "PR2Packs")

# 占位符与「占位文本」的判定只有一份，在 shared\core\validate.py。
from shared.core.validate import has_bare_pipe, is_placeholder, tokens  # noqa: E402

#: 只读参考语言：英文 / 法文原文。**不参与编辑，也不生成语言包**。
#: 实际名单以 translate.REFERENCE_LANGS 为准（这里是 import 不到时的兜底常量，
#: 文件名带来源与版本：en.gog_1.1.2.3 / fr.gog_1.1.2.42）。
REFERENCE_LANGS = ("en.gog_1.1.2.3", "fr.gog_1.1.2.42")

# ---------------------------------------------------------------- 占位符
#
# 规则（@前缀$变量名$、%N、紧邻占位符的坑）都在 shared\core\validate.py。
# 本模块以前另有一份实现，现在只留一个入口，免得编译期与编辑器的判定分叉。
# %02 与 %2 按字面区分：0 是 printf 的补零宽度，"Autosave %02u" 写成
# "%2u" 出来会少一位（全量里只有 1 条 0x33c2c533 用到 %02u）。


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


#: 未翻译条目的占位译文：编译时必须跳过它们的校验 ——
#: 占位文本本来就只有前 10 个字符，英文里的占位符必然被截掉，
#: 校验它只会产出 762 条假报警，把真问题淹掉。
#: 判定本身（is_placeholder / RE_PLACEHOLDER）在 shared\core\validate.py。


#: 旧写法 `|` 已不再自动转换：换行统一写 `<n>`。裸 `|` 会在 build()
#: 里作为致命错误拦下，避免“看起来是换行、游戏里显示竖线”。
#: `<|>` 这种字面竖线（0x11f0398f 的字符清单）不算。


def to_engine(txt):
    """把 TOML 里的真实换行翻成引擎认的 `<n>`。

    旧 `|` 兜底已删除；换行只认 `<n>` 和实际换行符。
    """
    return txt.replace("\n", "<n>")


#: 必须原样保留英文的条目：法律声明、内部编号、纯符号/数字。
#: 编译时强制写英文原文，译文写成什么都会被覆盖并打警告。
#: 以后要加条目（其它第三方声明、商标行）直接往这里加 hash。
KEEP_ORIGINAL = {
    "0xfc512ea5": "版权声明",
}


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
    """--lang 不给时的默认语言：src\\translations 下第一个可编辑语言。"""
    import translate as T
    langs = T.target_langs()
    if not langs:
        raise SystemExit(r"%s 下没有任何可编辑的 *.toml 译文文件。"
                         % T.STRINGS_DIR)
    return langs[0]


def load_pack_meta(lang):
    """读取 src/packs/<语言>.toml 的 alias/gui；这是写进语言包的元数据。"""
    p = os.path.join(SRC, "packs", lang + ".toml")
    if not os.path.isfile(p):
        return {}
    try:
        doc = tomllib.load(open(p, "rb"))
    except Exception:
        return {}
    return {k: str(doc[k]) for k in ("alias", "gui", "min_runtime")
            if doc.get(k)}


def build(lang, out_dir, strict):
    # 参考原文**不参与编译**：生成 en.txt / fr.txt 交给引擎等于用「原始英文」
    # 覆盖游戏，等于没汉化。所以直接拒绝，而不是打个警告继续跑。
    # 名单问 translate —— 那里是唯一一份（src\orig\en.gog_1.1.2.3 之类）。
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

    # 译文层 → 引擎层：排版规则在构建期套一遍，结果只写到 build/ 里。
    # 这就是「引擎文本是构建产物」的落点（旧的 src/live 已并入这里）—— 仓库里不再有第二份成品文本。
    from text import engine_text as ET
    plain, order = {}, []
    for s in doc.get("s", []):
        h = s.get("id", "").lower()
        if s.get(field):
            plain[h] = s.get(field)
            order.append(h)
    engine = ET.build(field, plain, order)
    engine_path = ET.write(field, engine, order)
    print("引擎文本 %d 条 → %s" % (len(engine), engine_path))

    errors, warnings, fatal = [], [], []

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s.txt" % lang)
    lines = []
    meta = load_pack_meta(lang)
    for k in ("alias", "gui", "min_runtime"):
        if meta.get(k):
            val = meta[k].replace("\n", " ").replace("\r", " ")
            lines.append("# pack-meta %s=%s\n" % (k, val))
    n = n_ph = 0

    for s in doc.get("s", []):
        h = s.get("id", "").lower()
        txt = engine.get(h)
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
        if has_bare_pipe(txt):
            fatal.append("%s 含未转换的 |（换行请写 <n>）" % h)
            continue
        # 【坑】hash 必须写成**大写**（0x30A45770），与既有语言包一致。
        # patch.js 的合并逻辑按大写规范化 hash，产物若写成小写，
        # 用户手改过的条目就识别不出来，合并会静默失效（测试 test_patch.js
        # 会抓到）。小写 id 只存在于 src\translations\*.toml 里作为内部键。
        lines.append("%s = %s\n" % (h.upper().replace("0X", "0x"),
                                    to_engine(txt)))
        n += 1
        if is_placeholder(txt):
            n_ph += 1

    if fatal:
        print("\n错误 %d 条（旧写法 | 不再自动转换）：" % len(fatal))
        for e in fatal[:30]:
            print("  x " + e)
        if len(fatal) > 30:
            print("  … 还有 %d 条" % (len(fatal) - 30))
        print("未生成 %s" % path)
        return 1

    # 一条都没编出来就**不写文件**：写一个 0 条的语言包毫无用处，
    # 装进游戏目录等于没汉化，而调用方只看「文件在不在」。
    # 成因通常是 src\translations\<语言>.toml 压根不存在 ——
    # 合并层只为实际存在的语言建字段。
    if n == 0:
        print("错误：没有编出任何条目，未生成 %s" % path)
        print("      找不到 %s\\%s.toml，或它里面没有条目。"
              % (os.path.join(SRC, "translations"), lang))
        print("      加一种语言：python src\\tools\\pack\\new_lang.py"
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
    ap.add_argument("--lang", default="", help="语言代码，默认 src\\translations 下第一个可编辑语言")
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
    # 字体不重缝就会画成空白。字体出错不算构建失败 —— 语言包本身没问题。
    if code == 0 and not a.no_fonts:
        try:
            fdir = os.path.join(TOOLS, "font")
            if fdir not in sys.path:
                sys.path.insert(0, fdir)
            import subset_fonts
            ok, msg = subset_fonts.ensure_fonts(
                langs=[lang], log=lambda m: print(m))
            print("字体：" + msg)
            if not ok:
                print("（部署时字体不会更新；详见上一行提示）")
        except Exception as exc:                  # 字体只是附带的，别拖垮构建
            print("字体检查跳过：%s" % exc)
    return code


if __name__ == "__main__":
    raise SystemExit(main())