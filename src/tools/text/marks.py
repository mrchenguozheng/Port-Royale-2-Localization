# -*- coding: utf-8 -*-
"""marks.py —— 译文层的内联标注：解析、展开、剥标。

译文层（src/translations/<lang>.toml）允许极少量内联标注，用来表达
「从英文原文推不出来」的两件事：这段是专名（译名统一查表）、这串原样照写。

语法只有一种形状，全部自闭合，没有闭合符：

    [town:Charleston]           查 src/data/names/<lang>.toml，换成该语言的译名
    [town:Charleston|gen]       指名形态（俄语格变化用；该语言没存这个形态就报错）
    [ref:0x0746253d]            本条与目标键是同一句：展开取目标键在本语言的译文
                                （目标须存在、非空、不是自己，且**目标不得再含 ref**——
                                只许一层，禁 A→B→C）
                                （`ref` 不再查名字表：它留给「同一条文本的跨键引用」，
                                见 09 卷第七十六节）
    [lit:%2 %1日]               字面照写，原文保留
    [term:en_business]          术语：键是 <语言>_<原词>，查 src/data/terms/<lang>.toml
    [term:de_general]           同词两义时换成「把义项分开的那门语言」做键
    [riddle:answer=Corpus Christi;clue=feature:荒凉+遗弃]
                                诗谜的谜底（只给翻译人看，展开为空，玩家看不到）
                                字段：`answer=` 谜底（`|` 是「或」的候选），
                                `group=` 同组其余副本的文本键（`+` 连接，单副本不写），
                                `clue=` 线索（`,` 分隔、`+` 同标签并值）。
                                answer 正常不写类型：方位键照写原词（east / not_north），
                                其余一律按城镇查 entities.toml；只有城名与方位键撞名
                                （目前 0 例）才写 town: / direction: 消歧。
                                clue 的每一项必写 `<标签>:<正文>`，
                                pun / direction / count / feature / produce / history /
                                exclude 是已知类型，值必须是**谜面正文里逐字出现的片段**；
                                `_` 开头的自造标签静默，字母开头的自造标签报 warning，
                                裸写报错。
                                展开时逐条核对——
                                写不出线索就说明这条谜面根本推不到这个答案（或线索该改）。
                                谜底/线索都不生成本文，也不许把答案照抄成 town，
                                否则既泄底又冻死用词（见 09 卷第六十三、六十四节）
                                谜底也可以只写方位（`direction:east`），那批谜面只说朝向，
                                写不出城名（09 卷第七十二节）。
                                字段语法见 09 卷第七十八、七十九节。

为什么不用成对标记
------------------
混合「自闭合 + 成对」要求解析器维护 void 白名单，还要容忍漏闭合；本库只有
两三种标注，一种形状就够，失败模式也只剩「多打/漏打一个 `]`」。

与排查包的关系
--------------
`debug_pack.py` 注入的 `[F4CF1]` 是打包最后一步的事；标注在 engine_text
（更早）就已剥掉，两者永不同框。所以共用一个括号字符是安全的，但**不做
「带标注且不剥标」的 debug 包**——那会让一行里出现两种 `[]`。

硬规则
------
* `[` 后必须是已知关键字加冒号，否则失败（正文里不许出现方括号）。
* 参数里不许出现 `[` 或 `]`：扫到第一个 `]` 结束。
* 唯一豁免：0x11f0398f 是字符清单，`[]` 在那里是被展示的字符。
"""

import io
import os
import re
import tomllib
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(TOOLS))
NAMES_DIR = os.path.join(ROOT, "src", "data", "names")
ENTITIES = os.path.join(NAMES_DIR, "entities.toml")
TERMS_DIR = os.path.join(ROOT, "src", "data", "terms")

#: 这个键是字符清单，方括号是被展示的字符本身，整条豁免。
EXEMPT_KEYS = {"0x11f0398f"}

#: `ref` 只做跨键引用（refid）：本条与目标键是同一句，展开取目标键译文。
#: **只允许一层**——目标键本身不得再含 `[ref:…]`，禁链式展开。
#: `riddle` 是诗谜标注（旧名 `ans`，2026-11-17 改名）：谜底与线索只给翻译人看，
#: 展开为空。代码里的 `ANS_*` 常量仍按「answer 这个概念」命名，与标记名无关。
KEYWORDS = ("ref", "town", "lit", "term", "riddle")

#: term 参数允许的语言前缀。目前只有三种对照语言有原文表：英文（主原文）、
#: 德语零售版、法语 GOG 版。加语言时同时确认 src/orig 里有对应文件。
TERM_PREFIXES = ("en", "de", "fr")

#: [riddle:] 允许的第二种谜底：方位。诗谜里有一批谜面只说朝向（东向第三座、
#: 三座里最西/最南、火山东南面、从西边过桥往东…），没有可直读的城镇名，
#: 城镇坐标又不在数据里。这类只把**朝向**当谜底，理由记在 09 卷第七十二节。
#: 取值是固定的英文键（和地名一样不随语言变），中文线索里写「东/东南」。
ANS_DIRECTIONS = frozenset({
    "north", "northeast", "east", "southeast",
    "south", "southwest", "west", "northwest",
})

#: 第三种谜底：否定朝向 `-<方位>`。谜面明写「往东南去航是白费力气」「北边什么
#: 也没有」这种**只能排除一个方向**的句子用它——原文明写的是「不是那边」，
#: 硬填成一个正向方位就是替原文做主。写 `-north` 表示「不是北边」。
#: 减号是规范写法（短、无下划线、与布尔取反区分）；`not north`（空格）同样接受，
#: `_canon_answer` 归一成 `-north`。`not_north` 的下划线写法明确不接受。
#: 长方位可缩写 NE/SE/SW/NW，但必须大写；north/east/south/west 不设缩写。
ANS_NEGATIVE = frozenset("-" + d for d in ANS_DIRECTIONS)

#: `[riddle:]` 里允许不登记实体的全部谜底取值：只有方位（正向与否定）。
#: 早先还有第四种谜底 `kw`（关键词组合），一条都没用上就删了——它靠空值表达
#: 「这不是专名」，既不比方位表清楚，也和「谜底要能指到具体地方」的初衷相反。
#: 真拿不准的时候谜底留空，而不是拿关键词凑。
ANS_KEYS = ANS_DIRECTIONS | ANS_NEGATIVE

_MARK = re.compile(r"\[([A-Za-z]+):([^\[\]]*)\]")
_ANY_BRACKET = re.compile(r"[\[\]]")
_ANS_SPAN = re.compile(r"\[riddle:[^\[\]]*\]")
#: clue 项的标签形态：只允许小写字母或 `_` 开头，后面小写字母/数字/_/-。
#: 大写、数字开头都报错（大写还会让人误以为类型名不区分大小写）。
_TAG_RX = re.compile(r"^[a-z_][a-z0-9_-]*$")
#: 判断「目标键自己又挂了 ref」用：只看 ref，别的标注不算第二层。
_REF_MARK = re.compile(r"\[ref:")


class MarkError(Exception):
    """标注写错。带键名和原因，直接判构建失败，不猜。"""


def load_entities():
    """实体清单：{名字: {kind, note}}。文件不存在就当空表。"""
    if not os.path.isfile(ENTITIES):
        return {}
    with io.open(ENTITIES, "rb") as f:
        return tomllib.load(f)


def names_path(lang):
    return os.path.join(NAMES_DIR, "%s.toml" % lang)


def load_names(lang):
    """某语言的译名表：{名字: {default, 形态…}}。文件不存在就当空表（全缺）。"""
    path = names_path(lang)
    if not os.path.isfile(path):
        return {}
    with io.open(path, "rb") as f:
        return tomllib.load(f)


def terms_path(lang):
    return os.path.join(TERMS_DIR, "%s.toml" % lang)


def load_terms(lang):
    """某语言的术语表：{英文锚词: 该语言译词}。文件不存在就当空表（全缺）。"""
    path = terms_path(lang)
    if not os.path.isfile(path):
        return {}
    with io.open(path, "rb") as f:
        return tomllib.load(f)


def _split_form(arg):
    if "|" not in arg:
        return arg, "default"
    name, form = arg.split("|", 1)
    return name, (form or "default")


def term_parts(arg):
    """术语参数：`<语言>_<原词>`，例如 en_business / de_general / fr_medium。

    语言前缀是必需的：英文同词两义时（General、normal、Wealth），靠换成「把义项分开的
    那门语言」来区分，所以键必须自带语言，不能只有英文原词。键一律 ASCII 小写，
    原形大小写与重音写在 terms 表的注释里。
    """
    word = arg.strip()
    if not word:
        raise MarkError("term 参数为空")
    if "|" in word:
        raise MarkError("term 不写译词（译词在 terms/<lang>.toml）；`|` 是 town 的形态分隔符")
    if word != word.lower():
        raise MarkError("term 参数要 ASCII 小写：%r（原形写进 terms 表的注释里）" % word)
    if "_" not in word:
        raise MarkError("term 参数要写成 <语言>_<原词>，例如 en_business / de_general")
    lang = word.split("_", 1)[0]
    if lang not in TERM_PREFIXES:
        raise MarkError("term 参数的语言前缀 %r 不在 %s 里"
                        % (lang, " / ".join(TERM_PREFIXES)))
    return word


def _resolve_term(arg, terms, hid, lang):
    """查术语表；缺条目或只留了空占位都报错，与 ref 缺译名同样硬失败。

    空占位（`key = ""`）是新语言骨架同步出来的待译行：报「未译」而不是
    「没有这个词条」，排错时能分清是表没同步还是词还没定。
    """
    word = term_parts(arg)
    value = terms.get(word)
    if not value:
        if word in terms:
            raise MarkError("%s：terms/%s.toml 的 %r 还是空占位（表里有这一行，译词没填）"
                            % (hid, lang, word))
        raise MarkError("%s：terms/%s.toml 里没有 %r（先定这个词的译法）"
                        % (hid, lang, word))
    return value


def _resolve(arg, table, hid, lang):
    """把 town 的参数解析成落地字符串；缺少条目或形态就报错，绝不回退。"""
    name, form = _split_form(arg)
    if not name:
        raise MarkError("%s：town 参数为空" % hid)
    entry = table.get(name)
    if entry is None:
        raise MarkError("%s：names/%s.toml 里没有 %r" % (hid, lang, name))
    if isinstance(entry, str):
        if form != "default":
            raise MarkError("%s：%r 只有默认写法，没有形态 %r"
                            % (hid, name, form))
        if not entry:
            raise MarkError("%s：names/%s.toml 的 %r 还是空占位（译名没填）"
                            % (hid, lang, name))
        return entry
    value = entry.get(form)
    if not value:
        if form in entry:
            raise MarkError("%s：%r 的形态 %r 还是空占位（译名没填）"
                            % (hid, name, form))
        raise MarkError("%s：%r 在 names/%s.toml 里没有形态 %r"
                        % (hid, name, lang, form))
    return value


def _ref_target(arg, doc, hid=""):
    """校验并取出 `[ref:键]` 的目标原文。只许一层：目标不得再含 ref。

    `doc` 是本语言整份译文（键 → 原文），ref 查的是它，不是名字表。
    """
    key = (arg or "").strip()
    if not key:
        raise MarkError("%s：ref 参数为空（写成 [ref:目标键]）" % hid)
    if doc is None:
        raise MarkError("%s：ref 要查同语言的整份译文，调用方没提供 doc" % hid)
    if key not in doc:
        raise MarkError("%s：ref 的目标键 %r 不在本语言译文里" % (hid, key))
    if key == hid:
        raise MarkError("%s：ref 指向自己（%r）" % (hid, key))
    target = doc.get(key) or ""
    if not target.strip():
        raise MarkError("%s：ref 的目标键 %r 还是空占位（目标没译完就不许引用）"
                        % (hid, key))
    if _REF_MARK.search(target):
        raise MarkError("%s：ref 只许一层，目标键 %r 自己也含 ref（禁 A→B→C）"
                        % (hid, key))
    return key, target


#: `[riddle:]` 的字段名。`;` 分字段：`answer=` 谜底（`|` 是「或」），
#: `group=` 同组其余副本的键（`+` 连接），`clue=` 线索（`,` 分隔、`+` 同标签并值）。
#: 谜底字段：`answer=` 靠值推断类型；`town=` / `direction=` 把类型明写出来，
#: 因此可以省掉 `answer=`——两者只能出现一处。
ANS_ANSWER_FIELDS = ("answer", "town", "direction")
ANS_FIELDS = ANS_ANSWER_FIELDS + ("group", "clue")

#: 谜底的两种类型。正常**不写**：值在方位键里就是方位，否则按城镇查 entities.toml；
#: 只有城名与方位键撞名（目前 0 例）才需要在字段名上写明。
ANS_NAME_KINDS = ("town", "direction")

#: answer 的类型前缀。正常**不写**：值在方位键里就是方位，否则按城镇查 entities.toml。
#: 只有城名与方位键撞名（目前 0 例）才需要 `town:` / `direction:` 消歧。
ANS_NAME_KINDS = ("town", "direction")

#: group 列的是「同组其余副本」的文本键：8 位小写十六进制、**不带 0x**，
#: 且必须按十六进制升序排列。实测量过：去掉 0x 后 8 位仍全表唯一，
#: 只留末 6 位会撞（`0x1db7f908` 与 `0xfdb7f908` 末 6 位都是 `b7f908`）。
#: 一条诗谜最多三个同谜底副本（13 组 Vera Cruz），所以最多列三个键；
#: 单副本的组不写这个字段。
ANS_KEY_RX = re.compile(r"^[0-9a-f]{8}$")

#: clue 的类型：说明这条谜面的信息属于哪一类，也决定译者必须保住什么。
ANS_CLUE_KINDS = ("pun", "direction", "count", "feature", "produce", "history", "exclude")


#: 长得像减号、但不是 ASCII 减号的字符：中文输入法下的全角`－`、排版用的各种破折号。
#: 它们会让 `-north` 变成「未知谜底」，报错文案得先点出这个坑，否则读者以为方位拼错。
_DASH_LOOKALIKES = frozenset("‐‑‒–—−－")


#: 否定方位只收两种：`-east`（规范）与 `not east`（空格，大小写不限）。
#: `not_east` 不再接受，下划线是纯形式负担、也容易漏打。
_NEG_WORD_RX = re.compile(r"^not\s+(.*)$", re.I)

#: 四个「长」方位（复合词）允许缩写。缩写与完整词都不限大小写（`NE` / `ne` / `Ne`
#: 都认），因为值域就是这八个方位，认出来不会跟别的东西抢。写进值的仍是完整键。
ANS_ABBREV = {
    "NE": "northeast",
    "SE": "southeast",
    "SW": "southwest",
    "NW": "northwest",
}
_CARDINAL_1 = {"N": "north", "E": "east", "S": "south", "W": "west"}


def _fold(text):
    """把写法差异折平：大小写、变音符号、首尾与连续空白。

    `East` / `east` / `EAST` / `eaSt` → `east`；`Roatán` / `roatan` → `roatan`；
    `St.  Juan` → `st. juan`。只用来比对，写进数据的仍是原本那个键。
    **宽度不折**：全角字母不该被悄悄当成半角，值里有全角/兼容字符先报错（见
    `_wide_char`）。
    """
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


def _wide_char(text):
    """返回值里第一个全角/兼容字符；没有则 None。

    检查规则是「这个字符自身 NFKC 后是否变样」：`ｅ`(U+FF45)、`Ａ`、全角空格、
    `ﬁ` 连字、`１` 都算。变音字母（`á`）不算——那是正字法的一部分，本来就要折平。
    全角字母肉眼和半角几乎一样，混进来最容易被当成「怎么对不上」的怪问题，所以在
    任何比对之前先点名。
    """
    for ch in text:
        if unicodedata.normalize("NFKC", ch) != ch:
            return ch
    return None


#: 折平后的方位写法 → 正向方位键。八个完整词 + 四个缩写 + 四个单字母。
_DIR_TOKEN = {_fold(k): k for k in ANS_DIRECTIONS}
_DIR_TOKEN.update({_fold(k): v for k, v in ANS_ABBREV.items()})
_DIR_TOKEN.update({_fold(k): v for k, v in _CARDINAL_1.items()})


def _check_chars(value, hid):
    """先拦字符层面的坑：长破折号/全角减号、全角字母。两者肉眼都几乎看不出。"""
    if value[:1] in _DASH_LOOKALIKES:
        raise MarkError("%s：谜底 %r 开头那个是长破折号/全角减号，不是半角 ASCII 减号"
                        "（改成 -north 这种写法，全角字符肉眼几乎看不出）" % (hid, value))
    ch = _wide_char(value)
    if ch is not None:
        raise MarkError("%s：谜底 %r 里有全角字符 %r——只认半角 ASCII（把输入法切到半角）"
                        % (hid, value, ch))


def _dir_word(text, hid, raw):
    """把一个方位写法归一成正向方位键；不认识的抛错，报错里给出全部合法写法。

    大小写、变音符号、多余空白都不计较（`East`、`eaSt` 都是 east）；单字母 N/E/S/W
    也收——值域封闭，认出来就是方向，不会跟城名抢。
    """
    key = _DIR_TOKEN.get(_fold(text))
    if key is not None:
        return key
    opts = " / ".join(sorted(ANS_DIRECTIONS))
    raise MarkError("%s：谜底 %r 里的 %r 不是方位词（写全 %s，或缩写 NE/SE/SW/NW，"
                    "大小写均可）" % (hid, raw, text, opts))


def _canon_answer(value, hid):
    """把否定方位归一成 `-方位`，把缩写/大小写/变音写法归一成完整方位键。

    收 `-east`（规范）与 `not east`（自然英语，大小写不限）；`not_east` 明确不再接受。
    归一发生在解析期，后面的 `ANS_KEYS` 查表、组内副本比对、`--apply` 复核只见到
    `-east` / `east`，所以同一谜底不会因为写法不同分裂成两串文本。

    不是方位模样的值原样返回（交给 check_doc 当城名去查 entities，查的时候同样不计
    大小写与变音符号）。形状写错的一律报错：`-`、`--east`、`-not_east`、`not`、
    `not-`；长破折号/全角减号开头的先单独报字符问题，因为肉眼几乎看不出。
    """
    _check_chars(value, hid)
    folded = _fold(value)
    if value.startswith("-"):
        return "-" + _dir_word(value[1:], hid, value)
    if folded.startswith("not_"):
        raise MarkError("%s：谜底 %r 用了 not_ 写法（下划线不再接受）——写 -north 或 "
                        "not north" % (hid, value))
    if folded.startswith("not-"):
        raise MarkError("%s：谜底 %r 用了 not- 连字符（写 not north，或者直接 -north）"
                        % (hid, value))
    m = _NEG_WORD_RX.match(value)
    if m:
        return "-" + _dir_word(m.group(1), hid, value)
    if folded == "not":
        raise MarkError("%s：谜底写成了光秃秃的 not（后面要跟方位词）" % hid)
    key = _DIR_TOKEN.get(folded)
    if key is not None:
        return key
    return value


def _answer_items(raw, hid, kind=None):
    """谜底字段的值 → [(类型|None, 值)]。

    类型由字段名决定：`town=` 全部按城镇、`direction=` 全部按方位；`answer=` 不写类型，
    留给 check_doc 按值推断（方位词裸写也认，单字母同样认——值域封闭，`n` 就是 north）。
    `|` 分隔「或」的候选，候选必须同类型——混类型（一城一方向）就写 `answer=`，
    让每个值各自推断。值里不再有 `town:` / `direction:` 前缀：那层类型声明已经上移到
    字段名。
    """
    parts = [p.strip() for p in raw.split("|")]
    if any(not p for p in parts):
        raise MarkError("%s：ans 的 %s 字段里有空的候选（`|` 两侧都要写）"
                        % (hid, kind or "answer"))
    items = []
    for part in parts:
        _check_chars(part, hid)
        if ":" in part:
            raise MarkError(
                "%s：谜底里的 %r 用了冒号前缀——类型声明写成字段：town=%s（方位则写 "
                "direction=%s）" % (hid, part, part.partition(":")[2],
                                   part.partition(":")[2]))
        if kind == "direction":
            value = _canon_answer(part, hid)
            if value not in ANS_KEYS:
                raise MarkError("%s：direction= 的值 %r 不是方位键（正向 north…、"
                                "否定 -north 或 not north、缩写 NE…）" % (hid, value))
        elif kind == "town":
            folded = _fold(part)
            if (part.startswith("-") or folded.startswith("not ")
                    or part[:1] in _DASH_LOOKALIKES):
                raise MarkError("%s：town= 的值 %r 写成了否定方位——方位谜底用 "
                                "direction=，town= 里只放城名" % (hid, part))
            value = part
        else:
            value = _canon_answer(part, hid)
        items.append((kind, value))
    if len(set(items)) != len(items):
        raise MarkError("%s：ans 的谜底有重复候选" % hid)
    return items


def _group_tokens(raw, hid):
    """`group=` → 同组其余副本的键（8 位小写十六进制、不带 0x、按升序排列）。

    `hid` 是本文键（`0x` 形式），比对时去掉前缀；键列表必须升序，写乱了就是错——
    排序是为了让「同组几条」一眼可比，也让手写与自动生成的结果一致。
    """
    toks = [t.strip() for t in raw.split("+")]
    if any(not t for t in toks):
        raise MarkError("%s：ans 的 group 里 `+` 两侧都要写键（收到 %r）" % (hid, raw))
    self_bare = hid[2:] if hid.startswith("0x") else hid
    for t in toks:
        if not ANS_KEY_RX.match(t):
            raise MarkError("%s：group 的键 %r 不是 8 位小写十六进制（不带 0x）"
                            % (hid, t))
        if t == self_bare:
            raise MarkError("%s：group 里列了本条自己（只列同组其余副本）" % hid)
    if len(set(toks)) != len(toks):
        raise MarkError("%s：ans 的 group 里有重复的键" % hid)
    if toks != sorted(toks):
        raise MarkError("%s：group 的键要按十六进制升序排列（收到 %s）"
                        % (hid, "+".join(toks)))
    return toks


def _split_ans(arg, hid="", warns=None):
    """`[riddle:answer=城|城;group=00000001+00000002;clue=direction:东,count:四座+第三座]`
    → ([(类型|None, 值)…], [同组其余副本的键…], [(类型|None, 词)…])。

    `answer` 里 `|` 是「或」（多个候选），`group` 里 `+` 连接同组其余副本的键，
    `clue` 里 `,` 是「并列」（全部必须成立）、`+` 是「同一个标签下的多个值」
    （展开后等价于把该项重复几遍）。
    `answer` 正常不写类型（值在方位键里算方位，否则按城镇查表）；想明写类型就改用
    `town=` / `direction=` 这两个字段名，此时可以省掉 `answer=`：
    `[riddle:town=Vera Cruz;clue=…]` / `[riddle:direction=SE;clue=…]`。
    `clue` 的每一项必须写成 `<标签>:<正文>`：标签是七个已知类型就按类型校验，
    `_` 开头的自造标签静默通过，字母开头的自造标签只当关键词并往 `warns` 记一条
    （多半是拼错）。
    裸写、标签含大写/数字开头、已知类型缺值、`+` 两侧缺值、缺谜底、字段重名、
    谜底写两处、全角逗号、group 列了自己或键形不对，一律失败。
    """
    fields = {}
    kind = None
    has_answer = False
    for part in arg.split(";"):
        part = part.strip()
        if not part:
            raise MarkError("%s：ans 里有空字段（多打了 `;`？）" % hid)
        if "=" not in part:
            raise MarkError("%s：ans 的字段要写成 answer=… / town=… / direction=… / "
                            "group=… / clue=…（收到 %r）" % (hid, part))
        name, _, value = part.partition("=")
        name, value = name.strip(), value.strip()
        if name not in ANS_FIELDS:
            raise MarkError("%s：ans 没有字段 %r（只有 %s）"
                            % (hid, name, " / ".join(ANS_FIELDS)))
        if name in ANS_ANSWER_FIELDS:
            # 谜底只能写一处：answer= / town= / direction= 三选一
            if has_answer:
                raise MarkError("%s：ans 的谜底写了两处（%s= 与 %s=）"
                                % (hid, kind or "answer", name))
            has_answer = True
            kind = None if name == "answer" else name
            fields["answer"] = value
            continue
        if name in fields:
            raise MarkError("%s：ans 的 %s 字段写了两遍" % (hid, name))
        fields[name] = value

    if not has_answer:
        raise MarkError(
            "%s：ans 缺谜底字段（answer=城、town=城、direction=方位 三选一；"
            "线索写 clue=direction:东,…）" % hid)
    answers = _answer_items(fields["answer"], hid, kind)
    group = _group_tokens(fields["group"], hid) if "group" in fields else []

    clue_raw = fields.get("clue", "")
    if "，" in clue_raw:
        raise MarkError("%s：ans 的线索用英文逗号 `,` 分隔，不要用全角「，」" % hid)
    clues = []
    for part in clue_raw.split(","):
        part = part.strip()
        if not part:
            raise MarkError("%s：ans 的 clue 里有空项（多打了 `,`？）" % hid)
        if ":" not in part:
            raise MarkError("%s：ans 的 clue 项要写成 <标签>:<正文>，不接受裸写（收到 %r）"
                            % (hid, part))
        tag, _, tail = part.partition(":")
        tag, tail = tag.strip(), tail.strip()
        if not _TAG_RX.match(tag):
            raise MarkError("%s：clue 的标签 %r 不合法（只允许小写字母或 `_` 开头，"
                            "后面只能是小写字母/数字/`_`/`-`）" % (hid, tag))
        if not tail:
            raise MarkError("%s：clue 的 %s 项缺值（要写谜面里出现的原词）"
                            % (hid, tag))
        # 同类型并值：`feature:白沙+丛林` 等价于 `feature:白沙,feature:丛林`。
        # `+` 只在标签内部起作用，语义仍是「都要成立」，省掉重复标签。
        values = [v.strip() for v in tail.split("+")]
        if any(not v for v in values):
            raise MarkError("%s：clue 的 %s 项里 `+` 两侧都要写值（收到 %r）"
                            % (hid, tag, tail))
        known = tag in ANS_CLUE_KINDS
        if not known:
            # 自造标签：`_` 开头是显式声明，静默；字母开头多半是拼错，记一条 warning。
            if not tag.startswith("_") and warns is not None:
                warns.append("%s：clue 的标签 %r 不是已知类型，按关键词扫描"
                             "（自造标签请用 `_` 开头）" % (hid, tag))
        for value in values:
            clues.append((tag if known else None, value))
    if not clues:
        raise MarkError(
            "%s：ans 只写了谜底 %r，没有 clue（谜面里能推出它的词要逐条写进来）"
            % (hid, "|".join(v for _, v in answers)))
    return answers, group, clues


def _check_ans(arg, body, hid="", warns=None):
    """核对谜底与线索：线索必须逐条出现在谜面正文里。

    返回 (候选 [(类型|None, 值)…], 同组其余副本的键, 线索)。写错抛 MarkError。
    """
    answers, group, clues = _split_ans(arg, hid, warns=warns)
    text = (body or "").casefold()
    missing = [v for _, v in clues if v.casefold() not in text]
    if missing:
        raise MarkError(
            "%s：ans 的谜底是 %r，但线索 %s 没出现在谜面里（谜面推不出这个答案，"
            "或者线索该换）" % (hid, "|".join(v for _, v in answers),
                                " / ".join(repr(v) for v in missing)))
    return answers, group, clues


def expand(text, table, lang, hid="", terms=None, doc=None):
    """展开一条标注文本，返回纯文本。写错一律抛 MarkError。

    `table` 是 names 表（town 用），`terms` 是术语表（term 用），`doc` 是本语言整份
    译文（ref 用）。前两者缺省按 lang 现读；`doc` 不给就不要写 ref——那是调用方的错，
    会明确报「没提供 doc」，不会静默跳过。
    """
    if terms is None:
        terms = load_terms(lang)
    out = []
    ans_args = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "[":
            out.append(ch)
            i += 1
            continue
        m = _MARK.match(text, i)
        if not m:
            raise MarkError("%s：第 %d 个字符处的 `[` 不成标记（要写成 [town:…] / "
                            "[lit:…] / [term:…] / [riddle:…]）" % (hid, i + 1))
        key, arg = m.group(1), m.group(2)
        if key not in KEYWORDS:
            raise MarkError("%s：未知标注关键字 %r（只有 %s）"
                            % (hid, key, " / ".join(KEYWORDS)))
        if key == "town":
            out.append(_resolve(arg, table, hid, lang))
        elif key == "ref":
            key_id, target = _ref_target(arg, doc, hid)
            out.append(expand(target, table, lang, key_id, terms=terms, doc=doc))
        elif key == "term":
            out.append(_resolve_term(arg, terms, hid, lang))
        elif key == "riddle":
            ans_args.append(arg)      # 谜底只给翻译人看，玩家文本里不出现
        else:
            out.append(arg)
        i = m.end()
    rest = "".join(out)
    if _ANY_BRACKET.search(rest):
        raise MarkError("%s：展开后仍残留方括号（正文里不许出现 `[` 或 `]`）" % hid)
    for arg in ans_args:
        _check_ans(arg, rest, hid)
    return rest


def scan(text):
    """只解析不展开：返回 [(key, arg)]，给校验和统计用。写错抛 MarkError。"""
    out = []
    i = 0
    while i < len(text):
        if text[i] != "[":
            i += 1
            continue
        m = _MARK.match(text, i)
        if not m:
            raise MarkError("第 %d 个字符处的 `[` 不成标记（要写成 [town:…] 或 "
                            "[lit:…]）" % (i + 1))
        if m.group(1) not in KEYWORDS:
            raise MarkError("第 %d 个字符处是未知标注关键字 %r（只有 %s）"
                            % (i + 1, m.group(1), " / ".join(KEYWORDS)))
        out.append((m.group(1), m.group(2)))
        i = m.end()
    return out


def has_marks(doc):
    return any("[" in v for v in doc.values())


def expand_doc(lang, doc):
    """整份译文展开：{键: 带标注文本} → {键: 纯文本}。

    没有标注的文件原样返回（零标注的阶段就是这条路径，一行都不用动）。
    """
    if not has_marks(doc):
        return dict(doc)
    table = load_names(lang)
    terms = load_terms(lang)
    out = {}
    for hid, text in doc.items():
        if not text:
            out[hid] = text
            continue
        if hid in EXEMPT_KEYS:
            out[hid] = text
            continue
        out[hid] = expand(text, table, lang, hid, terms=terms, doc=doc)
    return out


def used_names(doc):
    """译文里实际引用到的名字集合（含带形态的），给「死条目」校验用。"""
    used = set()
    for hid, text in doc.items():
        if not text or hid in EXEMPT_KEYS:
            continue
        try:
            marks = scan(text)
        except MarkError:
            continue
        for key, arg in marks:
            if key == "town":
                used.add(_split_form(arg)[0])
    return used


def used_terms(doc):
    """译文里实际引用到的术语锚词集合。"""
    used = set()
    for hid, text in doc.items():
        if not text or hid in EXEMPT_KEYS:
            continue
        try:
            marks = scan(text)
        except MarkError:
            continue
        for key, arg in marks:
            if key == "term":
                used.add(arg.strip())
    return used


def _appears(value, doc, lang):
    """译词是否在正文出现过。

    大小写不敏感（西语 `Bucanero` 在句中是 `bucanero`），屈折语再放宽到词尾：
    俄语 `Колония` 在正文里只会是 `колонии`/`колонию`。中日不按词尾放宽——
    「殖民」会把「殖民地」吃掉，反而放过真正的死条目。
    """
    v = value.strip()
    if not v:
        return True
    hay = "\n".join(t or "" for t in doc.values()).casefold()
    if v.casefold() in hay:
        return True
    if lang not in ("zh", "ja") and " " not in v and len(v) >= 6:
        return v[:-2].casefold() in hay
    return False


def _dead_entries(problems, label, table, used, doc, lang):
    """表里有、但既没被标注引用、译词也没在正文出现过的条目。

    空占位（骨架同步出来的待译行）不算死条目：它本来就还没译，
    既不引用也不出现是正常状态，报它只会淹掉真正拼错的键。
    """
    for name in sorted(set(table) - used):
        value = table[name]
        values = list(value.values()) if isinstance(value, dict) else [value]
        filled = [v for v in values if isinstance(v, str) and v.strip()]
        if not filled:
            continue
        if any(_appears(v, doc, lang) for v in filled):
            continue
        problems.append(
            "%s 的 %r 既没被引用、译词也没在正文出现过（拼错或该删）"
            % (label, name))


def check_doc(lang, doc, entities=None, terms=None, warns=None):
    """返回问题列表（空 = 通过）。构建前和 lint 共用这一份判据。

    town 查 names 表、term 查 terms 表、ref 查本语言译文（只许一层），两边都是
    「缺条目即失败 + 死条目提醒」，调用方不需要额外提供原文。

    `warns` 传一个列表时，会把「自造 clue 标签」（非 `_` 开头、也不是已知类型）
    这类不致命的问题记进去——lint 打 W 级，构建不受影响。
    """
    problems = []
    entities = load_entities() if entities is None else entities
    table = load_names(lang)
    terms = load_terms(lang) if terms is None else terms
    # 城名的宽容查表：同一串折平后可能对上几条登记名，那就得让作者挑明。
    ent_index = {}
    for name in entities:
        ent_index.setdefault(_fold(name), []).append(name)
    ans_used = set()
    ans_groups = {}
    for hid in sorted(doc):
        text = doc[hid] or ""
        if not text or hid in EXEMPT_KEYS:
            continue
        try:
            marks = scan(text)
        except MarkError as e:
            problems.append(str(e))
            continue
        for key, arg in marks:
            if key == "term":
                try:
                    _resolve_term(arg, terms, hid, lang)
                except MarkError as e:
                    problems.append(str(e))
                continue
            if key == "riddle":
                # 谜底必须登记过实体，线索必须真的在谜面里——否则「这条谜面指向
                # 哪座城」无从核对，标注就退化成一条注释。答案本身不查译名：
                # 诗里不照抄译名。
                try:
                    answers, group, _clues = _check_ans(
                        arg, _ANS_SPAN.sub("", text), hid, warns=warns)
                except MarkError as e:
                    problems.append(str(e))
                    continue
                sig = []
                for kind, value in answers:
                    # 城名比对不计大小写、变音符号和多余空白；对上了就用登记名本身
                    # 作为规范值（组内比对、死条目统计都用它）。
                    cands = ent_index.get(_fold(value), []) if value not in entities else [value]
                    if kind is None:
                        # 没写类型：值在方位键里算方位，否则按城镇查 entities。
                        in_keys = value in ANS_KEYS
                        if in_keys and cands:
                            kind = "town"
                            problems.append(
                                "%s：谜底 %r 既是方位键又是登记过的城镇 %s，改用 town=… 或 "
                                "direction=… 字段消歧" % (hid, value, cands[0]))
                        elif in_keys:
                            kind = "direction"
                        elif len(cands) == 1:
                            kind = "town"
                            value = cands[0]
                        elif len(cands) > 1:
                            problems.append(
                                "%s：谜底 %r 折平后对上多条登记名（%s），大小写/变音写成了"
                                "哪一条分不清——按登记名原样写" % (hid, value, " / ".join(cands)))
                        else:
                            problems.append(
                                "%s：谜底 %r 既不是方位键，也没登记在 entities.toml"
                                "（先决定它算不算专名；方位只能写 %s 或 -方位）"
                                % (hid, value, " / ".join(sorted(ANS_DIRECTIONS))))
                    elif kind == "town":
                        if len(cands) == 1:
                            value = cands[0]
                        elif len(cands) > 1:
                            problems.append(
                                "%s：谜底 %r 折平后对上多条登记名（%s），大小写/变音写成了"
                                "哪一条分不清——按登记名原样写" % (hid, value, " / ".join(cands)))
                        else:
                            problems.append(
                                "%s：谜底 %r 没登记在 entities.toml（先决定它算不算专名）"
                                % (hid, value))
                    if kind == "town" and value in entities:
                        ans_used.add(value)
                    sig.append(value)
                ans_groups[hid] = ("|".join(sig), group)
                continue
            if key == "ref":
                # 只校验结构，不展开：目标键自身的标注在它自己那一轮里查。
                try:
                    _ref_target(arg, doc, hid)
                except MarkError as e:
                    problems.append(str(e))
                continue
            if key == "town":
                name, form = _split_form(arg)
                if name and name not in entities:
                    problems.append(
                        "%s：%r 没登记在 entities.toml（先决定它算不算专名）"
                        % (hid, name))
                try:
                    _resolve(arg, table, hid, lang)
                except MarkError as e:
                    problems.append(str(e))
    # 同组副本互指：`group` 只列其余副本，所以「本条 + group 里的键」就是整组。
    # 组是身份不是答案——Roatán 出现在 14/15 两组、Providence 出现在 20/26 两组，
    # 按 answer 自动归并会把两个不同的寻宝组合成一个。
    for hid_g in sorted(ans_groups):
        sig_g, toks = ans_groups[hid_g]
        if not toks:
            continue
        members = {"0x" + t for t in toks} | {hid_g}
        for t in toks:
            t_key = "0x" + t
            if t_key not in ans_groups:
                problems.append(
                    "%s：group 里的 %s 没有 riddle 标注（同组每条都要标）" % (hid_g, t))
                continue
            sig_t, toks_t = ans_groups[t_key]
            if sig_t != sig_g:
                problems.append(
                    "%s：group 里的 %s 谜底是 %r，本条是 %r——同组副本不一致"
                    % (hid_g, t, sig_t, sig_g))
            if hid_g not in {"0x" + x for x in toks_t}:
                problems.append(
                    "%s：group 里的 %s 没反过来列出本条（互指必须对称）" % (hid_g, t))
            elif {"0x" + x for x in toks_t} | {t_key} != members:
                problems.append(
                    "%s：与 %s 的组员集合不一致（两边都要列全整组其余副本）"
                    % (hid_g, t))
    used = used_names(doc) | ans_used
    if used:
        # 死条目：既没被标注引用、译名也没在正文任何一条里出现，才报。
        # 这样表可以先建好、译文再逐步改标注，不会因为「暂时还没引用」而卡住。
        # 谜底算「用」：诗里写的是 X，谜底那座城的名字本来就不该出现在正文里。
        names_table = {k: v for k, v in table.items() if k in entities}
        _dead_entries(problems, "names/%s.toml" % lang, names_table, used, doc, lang)
    used_t = used_terms(doc)
    if used_t:
        _dead_entries(problems, "terms/%s.toml" % lang, terms, used_t, doc, lang)
    return problems
