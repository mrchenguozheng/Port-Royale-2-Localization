# -*- coding: utf-8 -*-
"""占位符与标签规则的唯一实现。

编辑器（src/editor、editor）、编译脚本（pack/compile_pack）与
tools/translate 都从这里取，不再各写一份。合并之前同一条规则散在四处，
各处的口径其实不一样，而且**都不报错**，只会让同一个文件在两个界面里
得出不同结论：%02 与 %2 的归一化只有 translate 做过；<n> 与正文里的
" | " 算同一个换行只有 src/editor 做过；那边比对标签用的正则还会把连续
的 <n><n> 吞成一个不存在的名字 "n><n"。

下面两个坑是这份实现必须绕开的（实测踩过）：

1) 剥标签必须**用空格替换**，不能删空 —— 原文 <c><ts:175>%2<t>…%1 剥掉
   <t> 后两个占位符紧邻成 "%2%1"，用一条贪婪正则去搜索会读成一个根本
   不存在的 "%21"。
2) %02 与 %2 是同一个参数，比对前归一化（去掉前导零）；否则原文写
   "%02u"、译文写 "%2u" 会被报成「少了 %02」+「多了 %2」两条假警报。

标签另算：比「轮廓」，即名字与数量，不比 <o:0xFF...> 里的颜色值（译文
可以换颜色）。<n> 与正文里的 " | " 是同一个换行，比对时算同一种 ——
否则「原文写 |、译文写 <n>」会被判成擅自加标签，而这正是编译期的写法。
"""
import re
from collections import Counter

#: 脚本变量 @前缀$变量名$ —— 首尾两个 $ 都是必需的。
#: 实测 3548 条原文里共 770 处引用，**770 处全部带尾 $，零例外**，
#: 所以这里用必需的 $ 而不是 \$? —— 漏掉尾 $ 必须报错，不能静默放过。
#: 比对时用**完整 token**：@P$TeacherName$ 与 @N$TeacherName$ 是两个
#: 不同的引用（同一变量名配不同前缀），别只比变量名。
RE_SCRIPT = re.compile(r"@[A-Za-z]\$[A-Za-z_][A-Za-z_0-9]*\$")

#: 任何排版标签（剥标签用）。含 <f:fonts\A.res> 这类字体标记 ——
#: 不剥它，全量里 67 条会被误认成占位符。
RE_TAG_ALL = re.compile(r"</?[a-zA-Z][^>]*>")

#: 位置参数（查找用）。剥标签时已用空格隔开紧邻情况，所以可以直接查；
#: %0*d 覆盖 %02 这类补零写法，归一化时再算回 %2。
RE_POS = re.compile(r"%0*\d+")

#: 轮廓里认的标签名（<o:0xFFF2FAAD>、<ts:175> 取冒号前的部分）。
TAG_NAMES = ("n", "o", "f", "t", "c", "tc", "ts")

#: 正文里的段落/换行分隔符（" | "）。排除 <|> 里的字面竖线。
RE_PIPE_BREAK = re.compile(r"(?<!<)\s*\|\s*(?!>)")

#: 未翻译条目的占位文本形态：8 位 hash + 竖线（编译时据此跳过校验）。
RE_PLACEHOLDER = re.compile(r"^0x[0-9a-f]{8} \| ", re.I)

#: 宽松版：原文里的 hash 有时被截成 6~7 位，还带空格。
PH_RE = re.compile(r"^\s*0x[0-9a-fA-F]{6,8}\s*\|")


def tokens(text):
    """占位符集合。只比种类与数量，顺序不管（各语言语序不同）。"""
    if text is None:
        return set()
    t = RE_TAG_ALL.sub(" ", str(text))
    out = set(RE_SCRIPT.findall(t))
    out |= {"%" + str(int(m.group(0)[1:])) for m in RE_POS.finditer(t)}
    return out


def tag_counts(text):
    """各标签出现次数。<n> 与正文里的 " | " 都记为 "|"。

    逐个 <...> 取，不靠一条大的名字正则：连续标签（<n><n>）会被
    `<n[^>]*>` 这类写法吞成一整段，拼出 "n><n" 这种不存在的名字
    （旧编辑器里的 tag_profile 正是这个毛病）。
    """
    t = str(text or "")
    c = Counter()
    for m in RE_TAG_ALL.finditer(t):
        raw = m.group(0)                        # <n> / </c> / <o:0xFFF2FAAD>
        closing = raw.startswith("</")
        name = raw[2 if closing else 1:].split(">")[0].split(":")[0].strip().lower()
        if name not in TAG_NAMES:
            continue
        if name == "n" and not closing:
            c["|"] += 1
            continue
        c[("/" if closing else "") + name] += 1
    c["|"] += len(RE_PIPE_BREAK.findall(t))
    return c


def tag_profile(text):
    """标签轮廓：把 tag_counts 展开成排序后的名字列表，便于整体比对。"""
    if text is None:
        return []
    return sorted(tag_counts(text).elements())


def is_placeholder(text):
    return bool(RE_PLACEHOLDER.match(text or ""))


#: 消息按界面语言分表。规则只有一份，措辞才分语言。
MESSAGES = {
    "en": {
        "empty": "Empty; the game will show English.",
        "placeholder": "Untranslated placeholder.",
        "missing": "Missing placeholder(s): %s",
        "extra": "Extra placeholder(s): %s",
        "extra_tag": "Extra tag: %s",
        "missing_tag": "Missing tag: %s",
    },
    "zh": {
        "empty": "这一条是空的（游戏里显示英文）",
        "placeholder": "还没翻（仍是占位文本）",
        "missing": "译文少了占位符：%s（游戏里会显示成字面量）",
        "extra": "译文多了占位符：%s（确认是刻意为之的话可忽略）",
        "extra_tag": "译文擅自新增标签 %s（换行只允许 <n> 或 |）",
        "missing_tag": "标签比原文少：%s",
    },
}


def check_text(text, english, lang="en"):
    """比对一条译文，返回 [{level, text}]，level 为 error 或 warn。

    【少 = 警告，多 = 错误】两种都会让引擎出乱码，但性质不同：
      * 少了：多半是手滑漏掉，改回来就行；
      * 多了：可能是刻意的 —— 原文是字面数字（"a discount of 5%"），
        译文改用 %1 动态传参完全合理，实测已有译文这么干。
    所以只报，不自动改，判断权交给译者。
    """
    msg = MESSAGES.get(lang) or MESSAGES["en"]
    if not text:
        return [{"level": "warn", "text": msg["empty"]}]
    if PH_RE.match(text):
        return [{"level": "warn", "text": msg["placeholder"]}]

    out = []
    a, b = tokens(english), tokens(text)
    if a - b:
        out.append({"level": "warn",
                    "text": msg["missing"] % " ".join(sorted(a - b))})
    if b - a:
        out.append({"level": "error",
                    "text": msg["extra"] % " ".join(sorted(b - a))})

    ta, tb = tag_counts(english), tag_counts(text)
    for tag in sorted(set(ta) | set(tb)):
        if tb[tag] > ta[tag]:
            out.append({"level": "error", "text": msg["extra_tag"] % tag})
        elif tb[tag] < ta[tag]:
            out.append({"level": "warn", "text": msg["missing_tag"] % tag})
    return out
