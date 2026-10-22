#!/usr/bin/env python
# coding: utf-8
"""src/tools/new_lang.py — 新建一种语言的译文文件

    python src/tools/new_lang.py --new-lang <代码> [--from <语言代码>]

**加一种语言就是复制 en.gog_1.1.2.3.toml 再逐条改译文**，所以本脚本只做这一件事：

    src/orig/en.gog_1.1.2.3.toml  ->  src/live/<代码>.toml

复制出来的每一行右边都是英文原文，也就是「未译」状态。逐条把右边改成
译文即可；没改的那些游戏里就显示英文。

文件格式（一种语言一个文件，每条一行，无块头无注释）
--------------------------------------------------------
    "0xd2d0a572" = "Vegetating"

语言代码就是文件名。条目数与顺序必须和 `orig/en.gog_1.1.2.3.toml` 完全一致
—— 合并与校验都靠位置对齐，多一条少一条都会让后面的 hash 全部错位。

重建全部原文（极少用）
----------------------
    python src/tools/new_lang.py

不带参数时走这条路，从 `editor/data/editor-data.json` 重新生成
en / fr / zh 三份文件。只在初次建立或**换游戏版本**（英法原文变了）时用。
日常改译文直接编辑 `src/live/<语言>.toml`，不要跑它
—— 它会用旧数据覆盖你的改动。
"""

import json
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                     # 仓库的 src\
ROOT = os.path.dirname(SRC)                     # 仓库根
sys.path.insert(0, HERE)

REF_JSON = os.path.join(ROOT, "editor", "data", "editor-data.json")
ZH_TXT = os.path.join(ROOT, "build", "PR2Packs", "zh.txt")
STRINGS = os.path.join(SRC, "live")
#: 只读参考（英/法/中文文本源）在 src\references\
REFS = os.path.join(SRC, "orig")
#: 基准语言：id 顺序以它为准，且 write-toml 拒写它
#: 文件名带来源与版本：references\en.gog_1.1.2.3.toml
BASE = "en.gog_1.1.2.3"
#: 只读参考语言：英法原文，不参与编辑，也不生成语言包
REFERENCE_LANGS = ("en.gog_1.1.2.3", "fr.gog_1.1.2.42")

#: 未翻译时的占位译文：hash | 英文前 N 个**单词**
PLACEHOLDER_WORDS = 10


def read_ref():
    if not os.path.isfile(REF_JSON):
        if os.path.isfile(os.path.join(REFS, BASE + ".toml")):
            raise SystemExit(
                "找不到 %s，但 references\\%s.toml 已经在仓库里。\n"
                "这个脚本只在「换游戏版本、要从头重建全部原文」时才需要原始数据；\n"
                "日常维护直接改 references\\ 与 translations\\ 下的 toml 即可。"
                % (REF_JSON, BASE))
        raise SystemExit("找不到 %s —— 它是英法原文的来源，不在仓库内。"
                         % REF_JSON)
    with io.open(REF_JSON, encoding="utf-8") as f:
        return json.load(f)


#: 占位译文的前缀。zh.txt 是**本脚本上一轮的输出**，里面可能混着
#: 上一轮生成的占位文本 —— 那些不是译文，绝不能再当成"已有译文"，
#: 否则会出现自我循环：第 2 轮的占位是第 1 轮占位的前 10 个单词，
#: 再下一轮就更短，最后全部退化成 "0x... | You must n" 这种碎片。
RE_PLACEHOLDER = re.compile(r"^0x[0-9a-f]{8} \| ")


def read_zh_txt():
    """读现有 zh.txt，取**真正的译文**。返回 {hash(小写): 文本}。

    跳过注释、空行，以及占位文本（那是我们自己生成的，不是译文）。
    """
    out = {}
    if not os.path.isfile(ZH_TXT):
        return out
    with io.open(ZH_TXT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 【坑】这里只能用 \s? 而不是 \s*：
            #   \s* 会把段首那个空格一起吃掉（"0x… =  %1，…" 里的第二个空格），
            #   而长文的偶数段段首段尾各留1 个空格是排版的一部分，剥掉就没了。
            # 同时也不能 strip() —— 那会把段尾空格也剥掉。
            m = re.match(r"^(0x[0-9A-Fa-f]+)\s*=\s?(.*)$", line)
            if not m:
                continue
            # 【坑】不能 strip()：长文的偶数段段首段尾各留1 个空格，
            # 那是排版的一部分。剥掉它会让游戏里该段的缩进消失，
            # 且与 strings\zh.toml 不一致（实测 0x1629fb20 就被剥过一次）。
            val = m.group(2)
            if RE_PLACEHOLDER.match(val.strip()):
                continue                       # 上一轮的占位文本，丢弃
            out[m.group(1).lower()] = val
    return out


def placeholder(h, en):
    """未翻译条目的占位文本：<hash> | <英文前 10 个单词>。

    要短 —— 长的占位文本可能超宽被游戏丢弃，那就白占位了。

    【坑1】不能直接在 en[:10] 处按字符切：原文常有 <f:fonts/...> 这类标签，
    切在标签中间会得到 "<f:fonts/T" 这种碎片。先剥掉标签类标记。
    【坑2】按单词切也要小心：直接 split() 会把换行当成词边界，
    而原文里 | 是段落分隔符，切出来会是 "a | b | c | d | …" 这种没意义的碎片。
    所以先归一空白，再按词切，最后去掉裸的 | 标记。
    """
    plain = strip_markup(en)
    words = plain.split()
    head = " ".join(words[:PLACEHOLDER_WORDS])
    head = re.sub(r"\s*\|\s*", " ", head)      # 裸 | 只是段落标记
    head = re.sub(r"\s+", " ", head).strip()
    if not head:
        head = "?"                                # 原文本身就是一串标签
    return "%s | %s" % (h, head)


#: 引擎的标签类标记（不是占位符，占位译文里要剥掉）。
#: 字体标记 `<f:...>` 也归在这里 —— 它不是合法的 XML 标签名，
#: 所以单独写一条分支。
MARKUP_RE = re.compile(r"</?[a-zA-Z][^>]*>|<f:[^>]*>")


def strip_markup(s):
    return MARKUP_RE.sub("", s)


def toml_str(s, multiline_ok=True):
    """输出一个 TOML 字符串。

    含换行时用三引号字面量（更易读，也便于和游戏里的 <n> 断行对应），
    否则用双引号。内部的三引号需要转义。
    """
    if multiline_ok and "\n" in s and '"""' not in s:
        return '"""\n%s\n"""' % s
    return json.dumps(s, ensure_ascii=False)


def new_lang(code, source=None):
    """新建一种语言的译文文件：复制一份原文，逐条改右边的值。

    源默认 orig/en.gog_1.1.2.3.toml，也可以 --from fr.gog_1.1.2.42 换成法文。
    复制出来的每一行右边都是原文，也就是「未译」状态；
    没改的那些游戏里直接显示英文。

    不覆盖已有文件 —— 加语言时误填了已存在的代码不该把已有译文冲掉。
    """
    src = source or BASE
    spath = os.path.join(REFS, src + ".toml")
    if not os.path.isfile(spath):
        raise SystemExit("找不到 %s —— 它是 %s 原文的来源。" % (spath, src))
    dpath = os.path.join(STRINGS, code + ".toml")
    if os.path.exists(dpath):
        raise SystemExit("%s 已存在，不覆盖。要重做先自己删掉或改名。" % dpath)
    with io.open(spath, encoding="utf-8") as f:
        txt = f.read()
    with io.open(dpath, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    print("已复制 %s -> %s（%d 条）" % (spath, dpath, txt.count("\n")))
    print("接下来把每行右边的原文改成译文；没改的会显示英文。")
    return 0



ARGS = sys.argv[1:]


def argval(flag):
    """取 `--flag value` 的 value，没有就返回 None。"""
    if flag in ARGS:
        i = ARGS.index(flag)
        if i + 1 < len(ARGS) and not ARGS[i + 1].startswith("-"):
            return ARGS[i + 1]
    return None


def main():
    if "--new-lang" in ARGS:
        code = argval("--new-lang")
        if not code:
            raise SystemExit("用法：--new-lang <代码> [--from <语言代码>]")
        return new_lang(code, argval("--from"))

    return rebuild_all()

def rebuild_all():
    """从 editor-data.json 重建 en / fr / zh 三份文件。

    只在初次建立或**换游戏版本**（英法原文变了）时跑。日常改译文
    不要跑它 —— 它会用旧数据覆盖你的改动。
    """
    ref = read_ref()
    zh = read_zh_txt()

    rows = []          # [(hash, en, fr, zh)]
    for x in ref:
        h = x["h"].lower()
        v = x["v"][0]
        en = v.get("en", "")
        fr = v.get("fr", "")
        t = zh.get(h) or placeholder(h, en)
        rows.append((h, en, fr, t))

    os.makedirs(STRINGS, exist_ok=True)
    plan = [("en.gog_1.1.2.3", 1), ("fr.gog_1.1.2.42", 2), ("zh", 3)]
    for lang, idx in plan:
        body = "\n".join('"%s" = %s' % (r[0], toml_str(r[idx])) for r in rows)
        txt = body + "\n"
        # 只读参考落在 src\references\，译文在 translations\ 根下
        d = REFS if lang in REFERENCE_LANGS else STRINGS
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, lang + ".toml")
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(txt)
        n_ph = sum(1 for r in rows if RE_PLACEHOLDER.match(r[idx]))
        print("已生成 %s（%d 条，占位 %d，%.1f KB）"
              % (path, len(rows), n_ph, len(txt.encode("utf-8")) / 1024.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
