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
    [ans:name=Corpus Christi;clue=荒凉,遗弃]
                                诗谜的谜底（只给翻译人看，展开为空，玩家看不到）
                                `name=` 是谜底，`|` 分隔「或」的多个候选；
                                `clue=` 是**谜面里能推出这个谜底的线索词**，用英文逗号
                                `,` 分隔（全角「，」不收），至少一条。展开时逐条核对
                                它们真的出现在谜面里——写不出
                                线索就说明这条谜面根本推不到这个答案（或线索该改）。
                                谜底/线索都不生成本文，也不许把答案照抄成 town，
                                否则既泄底又冻死用词（见 09 卷第六十三、六十四节）
                                谜底也可以只写方位（`east`/`southeast`…，见 ANS_DIRECTIONS）：
                                那批谜面只说朝向，写不出城名（09 卷第七十二节）。
                                字段语法见 09 卷第七十八节（`;` 分字段、`|` 是或、`,` 分线索）。

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
KEYWORDS = ("ref", "town", "lit", "term", "ans")

#: term 参数允许的语言前缀。目前只有三种对照语言有原文表：英文（主原文）、
#: 德语零售版、法语 GOG 版。加语言时同时确认 src/orig 里有对应文件。
TERM_PREFIXES = ("en", "de", "fr")

#: [ans:] 允许的第二种谜底：方位。诗谜里有一批谜面只说朝向（东向第三座、
#: 三座里最西/最南、火山东南面、从西边过桥往东…），没有可直读的城镇名，
#: 城镇坐标又不在数据里。这类只把**朝向**当谜底，理由记在 09 卷第七十二节。
#: 取值是固定的英文键（和地名一样不随语言变），中文线索里写「东/东南」。
ANS_DIRECTIONS = frozenset({
    "north", "northeast", "east", "southeast",
    "south", "southwest", "west", "northwest",
})

#: 第三种谜底：否定朝向 `not_<方位>`。谜面明写「往东南去航是白费力气」「北边什么
#: 也没有」这种**只能排除一个方向**的句子用它——原文明写的是「不是那边」，
#: 硬填成一个正向方位就是替原文做主。写 `not_north` 表示「不是北边」。
ANS_NEGATIVE = frozenset("not_" + d for d in ANS_DIRECTIONS)

#: 第四种谜底：`kw`——谜面既不指名城镇、也不给朝向（"荒凉之地、被遗弃"、
#: "三座小岛只有一座有缆绳"），只能拿**能定位它的关键词组合**当谜底。`ans` 写 `kw`，
#: 组合本身放进线索（至少两条，逐条要在谜面里出现）。见 09 卷第七十四节。
ANS_KEYWORD = "kw"

#: `[ans:]` 里允许不登记实体的全部谜底取值。
ANS_KEYS = ANS_DIRECTIONS | ANS_NEGATIVE | {ANS_KEYWORD}

_MARK = re.compile(r"\[([A-Za-z]+):([^\[\]]*)\]")
_ANY_BRACKET = re.compile(r"[\[\]]")
_ANS_SPAN = re.compile(r"\[ans:[^\[\]]*\]")
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


#: `[ans:]` 的字段名。`;` 分字段，`name=` 里 `|` 是「或」，`clue=` 里 `,` 分线索。
#: 只收这两个字段：写错的字段名会被报出来，不会静默忽略。
ANS_FIELDS = ("name", "clue")


def _split_ans(arg, hid=""):
    """`[ans:name=实体|实体;clue=线索,线索]` → ([实体…], [线索])。

    `name` 里 `|` 是「或」（多个候选），`clue` 里 `,` 分隔线索。
    缺 name、缺 clue、字段名写错、字段重名、全角逗号，一律失败。
    """
    fields = {}
    for part in arg.split(";"):
        part = part.strip()
        if not part:
            raise MarkError("%s：ans 里有空字段（多打了 `;`？）" % hid)
        if "=" not in part:
            raise MarkError("%s：ans 的字段要写成 name=… / clue=…，收到 %r"
                            % (hid, part))
        name, _, value = part.partition("=")
        name, value = name.strip(), value.strip()
        if name not in ANS_FIELDS:
            raise MarkError("%s：ans 没有字段 %r（只有 %s）"
                            % (hid, name, " / ".join(ANS_FIELDS)))
        if name in fields:
            raise MarkError("%s：ans 的 %s 字段写了两遍" % (hid, name))
        fields[name] = value

    if "name" not in fields:
        raise MarkError("%s：ans 缺 name 字段（写成 [ans:name=实体;clue=线索,…]）"
                        % hid)
    raw = fields["name"]
    if not raw:
        raise MarkError("%s：ans 的 name 为空" % hid)
    names = [n.strip() for n in raw.split("|")]
    if any(not n for n in names):
        raise MarkError("%s：ans 的 name 里有空的候选（`|` 两侧都要写）" % hid)
    if len(set(names)) != len(names):
        raise MarkError("%s：ans 的 name 有重复候选" % hid)

    clue_raw = fields.get("clue", "")
    if "，" in clue_raw:
        raise MarkError("%s：ans 的线索用英文逗号 `,` 分隔，不要用全角「，」" % hid)
    clues = [c.strip() for c in clue_raw.split(",")]
    clues = [c for c in clues if c]
    if not clues:
        raise MarkError(
            "%s：ans 只有谜底 %r，没有 clue 字段（谜面里能推出它的词要逐条写进来）"
            % (hid, raw))
    return names, clues


def _check_ans(arg, body, hid=""):
    """核对谜底与线索：线索必须逐条出现在谜面正文里。返回候选名单。写错抛 MarkError。"""
    names, clues = _split_ans(arg, hid)
    if ANS_KEYWORD in names and len(clues) < 2:
        raise MarkError(
            "%s：谜底是关键词组合（%s），至少写两条线索——一条算不上组合，"
            "也定位不到地方" % (hid, ANS_KEYWORD))
    text = (body or "").casefold()
    missing = [c for c in clues if c.casefold() not in text]
    if missing:
        raise MarkError(
            "%s：ans 的谜底是 %r，但线索 %s 没出现在谜面里（谜面推不出这个答案，"
            "或者线索该换）" % (hid, "|".join(names),
                                " / ".join(repr(c) for c in missing)))
    return names


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
                            "[lit:…] / [term:…] / [ans:…]）" % (hid, i + 1))
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
        elif key == "ans":
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


def check_doc(lang, doc, entities=None, terms=None):
    """返回问题列表（空 = 通过）。构建前和 lint 共用这一份判据。

    town 查 names 表、term 查 terms 表、ref 查本语言译文（只许一层），两边都是
    「缺条目即失败 + 死条目提醒」，调用方不需要额外提供原文。
    """
    problems = []
    entities = load_entities() if entities is None else entities
    table = load_names(lang)
    terms = load_terms(lang) if terms is None else terms
    ans_used = set()
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
            if key == "ans":
                # 谜底必须登记过实体，线索必须真的在谜面里——否则「这条谜面指向
                # 哪座城」无从核对，标注就退化成一条注释。答案本身不查译名：
                # 诗里不照抄译名。
                try:
                    names = _check_ans(arg, _ANS_SPAN.sub("", text), hid)
                except MarkError as e:
                    problems.append(str(e))
                    continue
                for name in names:
                    if name not in entities and name not in ANS_KEYS:
                        problems.append(
                            "%s：谜底 %r 没登记在 entities.toml（先决定它算不算专名）"
                            % (hid, name))
                    ans_used.add(name)
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
