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
    [riddle:answer=Corpus Christi;group=35f48f6c;clue=荒凉,遗弃;level=town;
            certainty=inferred;source=original-en&manual:docs/_src/x.md@sha256-ab12cd34ef56#"小节标题"]
                                诗谜的谜底（只给翻译人看，展开为空，玩家看不到）
                                字段（`;` 分隔；answer=/town=/direction= 三选一，其余不重复）：
                                `answer=` 谜底（`|` 是「或」的候选），
                                `group=` 同组全体成员的文本键（`,` 分隔、含本条自己，
                                       单副本就写自己那一个键；一条文本只许一个 riddle），
                                `clue=` 线索（`,` 分隔、每项都必须在谜面正文里出现），
                                `level=` 谜题分级：direction / town / mixed（必须与谜底字段
                                       算出来的一致——只有方位键、只有城镇名、两者齐备），
                                `certainty=` certain / inferred / either / disputed，
                                `source=` 依据（`+`/`&` 并列，类别见 ANS_SOURCE_*）。
                                level / certainty / source 在构建前复核时必写（check_doc 的
                                require_ans_meta，见 09 卷第一百零九、一百一十节）。
                                answer 正常不写类型：方位键照写原词（east / -north / not north），
                                其余一律按城镇查 entities.toml；只有城名与方位键撞名
                                （目前 0 例）才写 town: / direction: 消歧。
                                clue 的每一**项**两种形状都认：
                                  `<标签>:<正文>`（唯一保留的已知类型是 pun；`_` 开头的
                                   自造标签静默，字母开头的未知标签报 warning），
                                  裸写 `<正文>`（不带标签，直接当正文片段）。
                                两种形状里的值都必须是**谜面正文里逐字出现的片段**；
                                值里含 `:` 就整项加引号（`:` 在裸写里是标签分隔）；`+` 不用——
                                clue 里 `+` 已没有任何含义，裸写的加号就是正文（第一百一十节）；
                                全角「，」是误输入的分隔符；`;` 例外，它在解析 clue 之前就切字段，
                                引号保不住，只能改写或换词。
                                引号三种半角等价（`"…"`／`'…'`／`` `…` ``），里可写另外两种；
                                同种引号用反斜杠转义（`\"`、`\\`），见 09 卷第一百零八节。
                                展开时逐条核对——
                                写不出线索就说明这条谜面根本推不到这个答案（或线索该改）。
                                谜底/线索都不生成本文，也不许把答案照抄成 town，
                                否则既泄底又冻死用词（见 09 卷第六十三、六十四节）
                                谜底也可以只写方位（`direction=east`，或 `answer=east`），
                                那批谜面只说朝向，写不出城名（09 卷第七十二节）。
                                字段语法见 09 卷第七十八、七十九、一百零九、一百一十节。

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

import hashlib
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
#: 判断「目标键自己也是诗谜副本」用：`[riddle:copy=…]` 也不许再被引用（只许一层）。
_COPY_MARK = re.compile(r"\[riddle:\s*copy\s*=")
#: 整行就是一个 ref 的行：这条文本本身没有谜面，身份（谜底/组/分级）随目标键。
_PURE_REF_RX = re.compile(r"\[ref:([^\[\]]*)\]")
#: 文本键的宽容写法：8 位十六进制，`0x` 可写可不写，大小写照收，统一规范成 `0x` + 小写。
#: 只放宽写法，不放宽位数——8 位是「去掉 0x 后仍全表唯一」的实测结论（见 ANS_KEY_RX）。
_HEX8_RX = re.compile(r"^(?:0x)?([0-9a-fA-F]{8})$")


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


def _norm_key(raw, hid="", what="键"):
    """把引用到的文本键规范成 `0x` + 8 位小写十六进制。

    `0x` 可写可不写（`0x35f48f6c` 与 `35f48f6c` 同一条），大小写照收；位数不宽：
    8 位是「去掉 0x 后仍全表唯一」的实测结论，写短了会撞别的键，所以照旧报错。
    """
    m = _HEX8_RX.match((raw or "").strip())
    if not m:
        raise MarkError("%s：%s %r 不是 8 位十六进制键（写 0x35f48f6c 或 35f48f6c）"
                        % (hid, what, (raw or "").strip()))
    return "0x" + m.group(1).lower()


def _ref_target(arg, doc, hid=""):
    """校验并取出 `[ref:键]` 的目标原文。只许一层：目标不得再含 ref。

    `doc` 是本语言整份译文（键 → 原文），ref 查的是它，不是名字表。
    """
    key = _norm_key(arg, hid, "ref 的目标键")
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
    if _REF_MARK.search(target) or _COPY_MARK.search(target):
        raise MarkError("%s：ref 只许一层，目标键 %r 自己也含 ref/copy（禁 A→B→C）"
                        % (hid, key))
    return key, target


def _ans_copy_target(arg, hid=""):
    """`[riddle:copy=键]` → 目标键（`0x` 形式）；不是副本写法返回 None。

    `copy=` 要独占：它说的是「本条没有自己的谜面，文本与身份都取目标键」，再带
    `answer=`/`clue=`/`group=` 就成了两种说法并存。目标键的写法照样宽容（`0x` 可省）。
    """
    parts = [p.strip() for p in _join_source_parts(arg, hid)]
    names = [p.partition("=")[0].strip() for p in parts]
    if "copy" not in names:
        return None
    if len(parts) != 1:
        raise MarkError("%s：copy= 要独占整条（写成 [riddle:copy=键]，不许再带 "
                        "answer/clue/group 等字段）" % hid)
    _, _, value = parts[0].partition("=")
    return _norm_key(value, hid, "copy 的目标键")


def _copy_target(arg, doc, hid=""):
    """校验 `[riddle:copy=键]` 的目标并取出它的原文（只许一层，且目标必须真是谜面）。

    不是副本写法时返回 (None, None)——调用方靠这个区分「普通 [riddle:]」。
    """
    key = _ans_copy_target(arg, hid)
    if key is None:
        return None, None
    if doc is None:
        raise MarkError("%s：copy 要查同语言的整份译文，调用方没提供 doc" % hid)
    if key not in doc:
        raise MarkError("%s：copy 的目标键 %r 不在本语言译文里" % (hid, key))
    if key == hid:
        raise MarkError("%s：copy 指向自己（%r）" % (hid, key))
    target = doc.get(key) or ""
    if not target.strip():
        raise MarkError("%s：copy 的目标键 %r 还是空占位（目标没译完就不许引用）"
                        % (hid, key))
    if not _ANS_SPAN.search(target):
        raise MarkError("%s：copy 的目标键 %r 没有 riddle 标注（副本要指向一条谜面）"
                        % (hid, key))
    if _REF_MARK.search(target) or _COPY_MARK.search(target):
        raise MarkError("%s：copy 只许一层，目标键 %r 自己也是 ref/copy（禁 A→B→C）"
                        % (hid, key))
    return key, target


#: `[riddle:]` 的字段名。`;` 分字段：`answer=` 谜底（`|` 是「或」），
#: `group=` 同组全体成员的键（`,` 分隔、含自己），`clue=` 线索（`,` 分隔、每项都要出现）。
#: 谜底字段：`answer=` 靠值推断类型；`town=` / `direction=` 把类型明写出来，
#: 因此可以省掉 `answer=`——两者只能出现一处。
ANS_ANSWER_FIELDS = ("answer", "town", "direction")
ANS_FIELDS = ANS_ANSWER_FIELDS + ("group", "clue", "certainty", "source", "level")

#: 谜题分级（`level=`）：这条谜面把玩家指到多远——只有方位、只有城镇、还是两者混合。
#: 值不是自由声明的精度，而是必须与谜底字段算出来的结果一致（`check_doc` 比对）：
#: 方位键 → direction，城镇名 → town，`answer=城|-方位` 这种两项齐备 → mixed。
#: 分级的意义在消费侧：方向级的谜面写不出城名，玩家得自己走到；报告/统计按这一档分开看。
#: 所以它由谜底**决定**而不是由作者**选择**，写它等于把「这条谜面指到哪一档」显式记下来。
ANS_LEVELS = ("direction", "town", "mixed")

#: 谜底的两种类型。正常**不写**：值在方位键里就是方位，否则按城镇查 entities.toml；
#: 只有城名与方位键撞名（目前 0 例）才需要在字段名上写明（`town=` / `direction=`）。
ANS_NAME_KINDS = ("town", "direction")

#: group 列的是「同组全体成员」的文本键：8 位小写十六进制、**不带 0x**，
#: 且必须按十六进制升序排列。实测量过：去掉 0x 后 8 位仍全表唯一，
#: 只留末 6 位会撞（`0x1db7f908` 与 `0xfdb7f908` 末 6 位都是 `b7f908`）。
#: 一条诗谜最多三个同谜底副本（13 组 Vera Cruz），所以最多列三个键；
#: 单副本的组写自己。
ANS_KEY_RX = re.compile(r"^[0-9a-f]{8}$")

#: clue 的已知类型：只留 `pun`（双关——这条谜面的谜底靠谐音，译文必须保住那个音）。
#: 原先还有 direction / count / feature / produce / history / exclude 六类，只做统计与
#: 提示，2026-11-18 退役：它们的值本来就只是「要在谜面正文里出现的片段」，标签是多余的，
#: 写分类直接裸写即可（见 09 卷第一百零五节）。这六类若再写，按字母开头的自造标签处理
#: （text_lint 记 W 级警告），想保留分类语义就改用 `_` 开头的自造标签。
ANS_CLUE_KINDS = ("pun",)

#: certainty：这条谜底有多确定（见 09 卷第九十一、九十五节）。
#: `either` 专指「两个地点都成立」——不是没定，是并列成立，答案用 `answer=A|B` 列全。
ANS_CERTAINTY = ("certain", "inferred", "either", "disputed")

#: source 的两份原文（GOG 版英文与法语）：`original-en` / `original-fr`。
ANS_ORIGINALS = ("original-en", "original-fr")

#: `retail-xx` / `fan-xx` 里允许的语言码：以 `src/orig` 里有原文表的语言为准。
ANS_SOURCE_LANGS = ("de", "en", "es", "fr", "pl", "ru")

#: 带指向的网页来源：只有一个 `url`（`steam` / `forum` 已合并进来——那两个类别只是
#: 用域名互相排斥，而域名本来就写在 URL 里，分类等于让人多记一个词）。
ANS_SOURCE_URLS = ("url",)
#: 只记类别、不带指向的来源：`cargo` 是货物清单推出来的，`map` 是地图实测，
#: `authored` 是本语言自己编写/新编的谜面（不是从任何一版原文推来的，见 09 卷第一百零九节）。
#: 用 `authored` 而不是 `local`：`local` 在工程语境里更像「本机/本地文件」，而这一栏要说的是
#: 「谁写的」——本语言译者。
ANS_SOURCE_BARE = ("cargo", "map", "authored")

#: 弯引号/全角引号：`_wide_char` 认不出它们（NFKC 不变），只在这些字符进到 source 时点名。
_CURLY_QUOTES = "\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f\u00ab\u00bb\u300c\u300d"
_QUOTE_PAIRS = {"'": "'", '"': '"', "`": "`"}
#: manual 的摘要算法前缀允许值（12 位小写十六进制），语法上容得下换算法。
_DIGEST_RX = re.compile(r"^(sha256|md5|blake2b)-([0-9a-f]{12})$")
_ANCHOR_RX = re.compile(r"^p\d+$")
_SHA_CACHE = {}


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
    """`group=` → 本组全体成员的键（**含本条自己**）：8 位小写十六进制、不带 0x、升序。

    `hid` 是本文键（`0x` 形式），比对时去掉前缀。列全组含自己有两个好处：
    「单副本」也有明确写法（`group=<自己>`），于是没写 group 与写了但漏人分得清；
    组员集合可以直接拿两边的键列表相等来比，不用再补一条自己。

    并列符与 `clue` 一致，只用 `,`：`group=00000001,00000002`。`+` 在这里退役，`source=`
    的并列项另有 `+` / `&`（那是「几个来源」，不是同一种并列）——理由与第一百零六、
    一百零八节同：同一个符号不在一个字段里表示两种并列。

    键的写法宽容：`0x` 可写可不写（`group=0x35f48f6c` 与 `group=35f48f6c` 同一条），
    大小写照收；存进来的仍是去前缀的小写 8 位，排序也按这个比（写 `0x` 不会改变顺序）。
    """
    toks = [t.strip() for t in raw.split(",")]
    if any(not t for t in toks):
        raise MarkError("%s：ans 的 group 里 `,` 两侧都要写键（收到 %r）" % (hid, raw))
    toks = [_norm_key(t, hid, "group 的键")[2:] for t in toks]
    self_bare = hid[2:] if hid.startswith("0x") else hid
    for t in toks:
        if not ANS_KEY_RX.match(t):
            raise MarkError("%s：group 的键 %r 不是 8 位小写十六进制（不带 0x）"
                            % (hid, t))
    if len(set(toks)) != len(toks):
        raise MarkError("%s：ans 的 group 里有重复的键" % hid)
    if toks != sorted(toks):
        raise MarkError("%s：group 的键要按十六进制升序排列（收到 %s）"
                        % (hid, ",".join(toks)))
    if self_bare and self_bare not in toks:
        raise MarkError("%s：group 里漏了本条自己（group 列整组含自己：单副本写 "
                        "group=%s）" % (hid, self_bare))
    return toks


def _unbalanced(text):
    """这个值里的半角引号有没有没配平的（`\\` 后面的引号算正文，不计数）。"""
    for q in _QUOTE_PAIRS:
        n, esc = 0, False
        for ch in text:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == q:
                n += 1
        if n % 2:
            return True
    return False


def _join_source_parts(arg, hid):
    """按 `;` 切字段，但 `source=` 值里**引号内**的 `;` 不算分隔。

    只有 source 的 URL 引号里才可能出现 `;`（谜面与线索里的引号可能是原文的撇号，
    不能当分隔符对待），所以先朴素切，再发现 source 的值引号没配平就把后面的字段
    拼回来——其它字段一切照旧。
    """
    raw = arg.split(";")
    parts = []
    i = 0
    while i < len(raw):
        part = raw[i]
        i += 1
        if part.strip().startswith("source=") and _unbalanced(part.partition("=")[2]):
            while i < len(raw) and _unbalanced(part.partition("=")[2]):
                part += ";" + raw[i]
                i += 1
        parts.append(part)
    return parts


def _split_source_items(raw, hid):
    """source 的值按 `+` / `&` 切成并列项；引号内的 `+`、`&` 与转义后的字符原样保留。"""
    items, buf, quote, esc = [], [], None, False
    for ch in raw:
        if esc:
            buf.append(ch)
            esc = False
            continue
        if quote is not None and ch == "\\":
            buf.append(ch)
            esc = True
            continue
        if quote is None and ch in _QUOTE_PAIRS:
            quote = ch
        elif quote is not None and ch == quote:
            quote = None
        elif quote is None and ch in "+&":
            items.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if quote is not None:
        if esc:
            raise MarkError("%s：source 里的引号以反斜杠结尾——正文要一个反斜杠就写 `\\\\`"
                            % hid)
        raise MarkError("%s：source 里的引号没闭合（%r）" % (hid, raw))
    items.append("".join(buf))
    return [i.strip() for i in items]


def _unquote(raw, hid, what="URL"):
    """取引号里的内容：必须成对、同种、紧贴；里面可以写另外两种引号。

    三种引号等价（`"…"`、`'…'`、`` `…` ``）。里面有同种引号时用反斜杠转义：
    `"say \"hi\""`；`\\` 表示正文里的一个反斜杠；其它 `\\x` 一律原样保留（URL、路径里
    本身可能带反斜杠，不当转义）。弯引号一律不认。
    """
    text = raw.strip()
    if not text or text[0] not in _QUOTE_PAIRS:
        raise MarkError("%s：%s 要用引号包起来（半角单引号 '…'／双引号 \"…\"／反引号 `…`，"
                        "收到 %r）" % (hid, what, raw))
    q = text[0]
    if len(text) < 2 or text[-1] != q:
        raise MarkError("%s：%s 的引号没成对（收到 %r）" % (hid, what, raw))
    inner = text[1:-1]
    for ch in _CURLY_QUOTES:
        if ch in inner:
            raise MarkError("%s：%s 里有弯引号/全角引号 %r——只认半角 '／\"／`"
                            % (hid, what, ch))
    out = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\":
            if i + 1 >= len(inner):
                raise MarkError("%s：%s 的引号里以反斜杠结尾——正文要一个反斜杠就写 "
                                "`\\\\`" % (hid, what))
            nxt = inner[i + 1]
            if nxt in (q, "\\"):
                out.append(nxt)
                i += 2
                continue
            out.append(ch)
            i += 1
            continue
        if ch == q:
            raise MarkError("%s：%s 的引号里出现同种引号 %r——写成 \\%s 转义，或换另一种外层引号"
                            % (hid, what, q, q))
        out.append(ch)
        i += 1
    value = "".join(out)
    if not value:
        raise MarkError("%s：%s 的引号里是空的" % (hid, what))
    return value


def _check_url(raw, hid):
    """校验带引号的 URL，返回去掉引号、补齐 `https:` 省略形式之后的完整串。"""
    url = _unquote(raw, hid)
    if any(c.isspace() for c in url) or ";" in url:
        raise MarkError("%s：URL 里不能有空白或裸 `;`（`;` 写 %%3B）" % hid)
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("https://"):
        rest = url[len("https://"):]
    elif url.startswith("http://"):
        rest = url[len("http://"):]
    else:
        raise MarkError("%s：URL 要以 https:// 开头（https 可省写 //）；http:// 不能省" % hid)
    host, sep, path = rest.partition("/")
    if not host or "." not in host:
        raise MarkError("%s：URL 缺少域名（收到 %r）" % (hid, url))
    if not sep or not path.strip():
        raise MarkError("%s：URL 只写了域名，没有路径（收到 %r）" % (hid, url))
    return url


def _digest12(path, algo):
    """文件的摘要前 12 位（小写十六进制），带 mtime 缓存，重复校验同一文件只读一遍。"""
    st = os.stat(path)
    key = (path, algo, st.st_size, int(st.st_mtime))
    if key in _SHA_CACHE:
        return _SHA_CACHE[key]
    h = {"sha256": hashlib.sha256, "md5": hashlib.md5, "blake2b": hashlib.blake2b}[algo]()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    got = h.hexdigest()[:12]
    _SHA_CACHE[key] = got
    return got


def _headings(full):
    """目标文件里的 markdown 标题集合（`#`…`######` 后面那段文本，去两侧空白）。

    带 mtime 缓存：同一份参考文件被几十条 source 反复指到，不该反复读盘。
    """
    st = os.stat(full)
    key = (full, st.st_size, int(st.st_mtime))
    if key in _SHA_CACHE:
        return _SHA_CACHE[key]
    with io.open(full, encoding="utf-8") as fh:
        text = fh.read()
    found = set()
    for line in text.splitlines():
        m = re.match(r"^#{1,6}[ \t]+(.*\S)\s*$", line)
        if m:
            found.add(m.group(1).strip())
    _SHA_CACHE[key] = found
    return found


def _check_manual(tail, hid):
    """`manual:仓库内路径@sha256-<12 位>[#"小节标题"|#pNN]`：路径在仓库内、摘要对得上、
    指到的小节标题真在目标文件里。

    锚点两种：`#"标题"` 指到 markdown 小节（三种半角引号都收，标题必须逐字存在于该文件
    的同级标题里）；`#pNN` 只记页码形状、不校验（留给分页文档）。旧的 `#chNN` 已退役：
    它只是自造编号，校验不了，等于把「指到哪一章」写成了一句无法核对的话。
    """
    if "@" not in tail:
        raise MarkError("%s：manual 要写成 路径@sha256-<12 位>（缺 @摘要）" % hid)
    path, _, rest = tail.partition("@")
    path = path.strip()
    if not path:
        raise MarkError("%s：manual 缺路径" % hid)
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise MarkError("%s：manual 只收仓库内的相对路径（收到绝对路径 %r）" % (hid, path))
    if ".." in path.replace("\\", "/").split("/"):
        raise MarkError("%s：manual 的路径不许跳出仓库（去不掉 `..`）" % hid)
    rest = rest.strip()
    anchor = None
    if "#" in rest:
        rest, _, anchor = rest.partition("#")
        anchor = anchor.strip()
        if anchor[:1] in _QUOTE_PAIRS:
            title = _unquote(anchor, hid, "锚点")
            anchor = ("title", title)
        elif _ANCHOR_RX.match(anchor):
            anchor = ("page", anchor)
        elif re.match(r"^ch\d+$", anchor):
            raise MarkError("%s：manual 的 #%s 这种自造章号已退役——写成 #\"小节标题\""
                            "（标题必须真在目标文件里）" % (hid, anchor))
        else:
            raise MarkError("%s：manual 的锚点要么写 #\"小节标题\"，要么写 #pNN（页），"
                            "收到 %r" % (hid, anchor))
    m = _DIGEST_RX.match(rest)
    if not m:
        raise MarkError("%s：manual 的摘要要写成 sha256-<12 位小写十六进制>（收到 %r）"
                        % (hid, rest))
    full = os.path.join(ROOT, path.replace("\\", "/").replace("/", os.sep))
    if not os.path.isfile(full):
        raise MarkError("%s：manual 的路径 %r 不在仓库里（仓库根 %s）" % (hid, path, ROOT))
    got = _digest12(full, m.group(1))
    if got != m.group(2):
        raise MarkError("%s：manual 的 %s 对不上：写的是 %s，文件里算出来是 %s"
                        % (hid, m.group(1), m.group(2), got))
    if anchor and anchor[0] == "title":
        heads = _headings(full)
        if anchor[1] not in heads:
            near = sorted(h for h in heads if anchor[1].split()[0] in h)[:3]
            raise MarkError("%s：manual 指到的小节 %r 不在 %s 的标题里%s"
                            % (hid, anchor[1], path,
                               ("（相近的有：%s）" % " / ".join(near)) if near else ""))
        anchor = anchor[1]
    elif anchor:
        anchor = anchor[1]
    return (path, rest, anchor)


def _check_source_item(item, hid):
    """解析一个来源项，返回 (类别, 目标)。写错抛 MarkError。"""
    if item[:1] in _QUOTE_PAIRS:
        return ("url", _check_url(item, hid))
    cat, sep, tail = item.partition(":")
    cat, tail = cat.strip(), tail.strip()
    if not sep:
        tail = ""
    if cat in ANS_ORIGINALS:
        if tail:
            raise MarkError("%s：%s 不带指向（收到 %r）" % (hid, cat, item))
        return ("original", cat)
    if cat in ANS_SOURCE_BARE:
        if tail:
            raise MarkError("%s：%s 先只记类别，不带指向（收到 %r）" % (hid, cat, item))
        return (cat, None)
    if cat.startswith("retail-") or cat.startswith("fan-"):
        lang = cat.split("-", 1)[1].strip()
        if lang not in ANS_SOURCE_LANGS:
            raise MarkError("%s：%s 的语言码 %r 不认识（只有 %s）"
                            % (hid, cat, lang, " / ".join(ANS_SOURCE_LANGS)))
        if tail and not ANS_KEY_RX.match(tail):
            raise MarkError("%s：%s 的指向要写 8 位小写十六进制键（收到 %r）"
                            % (hid, cat, tail))
        return (cat.split("-", 1)[0], cat if not tail else (cat, tail))
    if cat in ANS_SOURCE_URLS:
        if not tail:
            raise MarkError("%s：url 后面要跟引号包的网址（url:'https://…'；也可以裸写 "
                            "'https://…'）" % hid)
        return ("url", _check_url(tail, hid))
    if cat == "manual":
        if not tail:
            raise MarkError("%s：manual 后面要写 路径@sha256-<12 位>" % hid)
        return ("manual", _check_manual(tail, hid))
    if cat == "riddle":
        toks = [t.strip() for t in tail.split(",")]
        if any(not t for t in toks):
            raise MarkError("%s：riddle 的键列表里 `,` 两侧都要写键（收到 %r）"
                            % (hid, tail))
        # 键的写法同样宽容：`0x` 可写可不写，存进来的是去前缀的 8 位小写。
        toks = [_norm_key(t, hid, "riddle 指向的键")[2:] for t in toks]
        if len(set(toks)) != len(toks):
            raise MarkError("%s：riddle 的键列表里有重复（%r）" % (hid, tail))
        if toks != sorted(toks):
            raise MarkError("%s：riddle 的键要按升序写（收到 %r）" % (hid, tail))
        return ("riddle", tuple(toks))
    raise MarkError("%s：source 没有类别 %r（只有 %s）"
                    % (hid, cat, " / ".join(ANS_ORIGINALS + ANS_SOURCE_URLS
                                            + ("manual", "riddle") + ANS_SOURCE_BARE
                                            + ("retail-xx", "fan-xx"))))


def _check_source(raw, hid):
    """校验整个 source 值，返回 [(类别, 目标)…]。"""
    items = _split_source_items(raw, hid)
    if any(not i for i in items):
        raise MarkError("%s：source 里有空项（多打了 `+` 或 `&`？）" % hid)
    for ch in _CURLY_QUOTES:
        if ch in raw and ch not in "".join(_unquote(i, hid) for i in items
                                           if i[:1] in _QUOTE_PAIRS):
            raise MarkError("%s：source 里有弯引号/全角引号 %r——只认半角 ' 或 \""
                            % (hid, ch))
    return [_check_source_item(i, hid) for i in items]


#: clue 项里必须靠引号才写得进来的字符：只有 `:`（标签分隔）。`+` 不在其中——clue 里
#: `+` 已经没有任何含义（并值在第一百零六节退役），裸写的加号就是正文，不必加引号；
#: `,` 也不用列，它在项切分那一步已经走掉了。全角「，」是误输入的分隔符，单独报错。
_CLUE_NEEDS_QUOTE = ":"


def _clue_item_head(buf):
    """buf 是否还停在「项首」：空，或只写了一个待定的标签前缀（`xxx:`）。

    引号只在项首才算开引号。这样正文里的撇号（`I'm a captain`、`l'abondance`）不会被当成
    引号起点——它前面已经有字母，不在项首。
    """
    t = buf.strip()
    if not t:
        return True
    if not t.endswith(":"):
        return False
    return bool(_TAG_RX.match(t[:-1]))


def split_clue_items(raw, hid=""):
    """按顶层 `,` 切 clue 项，引号里的逗号不算分隔；返回原项串列表（引号与转义原样保留）。

    项可以整段用引号包起来（`"Good! Very good!"`），也可以裸写；引号认半角 `'` / `"` / `` ` ``，
    且必须紧贴项首（标签前缀之后也算项首，`pun:"12:30"` 成立）。引号里可以用 `\\` 转义
    同种引号（`"say \"hi\""`），转义后紧跟的字符不再当闭合引号。逗号后的空白不计。
    """
    items, buf, quote, esc = [], [], None, False
    for ch in raw:
        if esc:
            buf.append(ch)
            esc = False
            continue
        if quote is not None and ch == "\\":
            buf.append(ch)
            esc = True
            continue
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch == ",":
            items.append("".join(buf))
            buf = []
            continue
        if ch in _QUOTE_PAIRS and _clue_item_head("".join(buf)):
            quote = ch
        buf.append(ch)
    if quote is not None:
        if esc:
            raise MarkError("%s：clue 的引号里以反斜杠结尾——正文要一个反斜杠就写 `\\\\`"
                            % hid)
        raise MarkError("%s：clue 的引号没闭合（%r）" % (hid, raw))
    items.append("".join(buf))
    return items


def _clue_item(part, hid, warns=None):
    """解析一个 clue 项（已按顶层逗号切开），返回 (标签|None, 值)。"""
    part = part.strip()
    if not part:
        raise MarkError("%s：ans 的 clue 里有空项（多打了 `,`？）" % hid)
    if part[0] in _QUOTE_PAIRS:
        return None, _unquote(part, hid, "clue 项")
    tag = None
    if ":" in part:
        raw_tag, _, tail = part.partition(":")
        raw_tag, tail = raw_tag.strip(), tail.strip()
        if not _TAG_RX.match(raw_tag):
            raise MarkError("%s：clue 的标签 %r 不合法（只允许小写字母或 `_` 开头，后面只能是"
                            "小写字母/数字/`_`/`-`）；正文本身含冒号时把整项用引号包起来"
                            % (hid, raw_tag))
        if raw_tag in ANS_CLUE_KINDS:
            tag = raw_tag
        elif not raw_tag.startswith("_") and warns is not None:
            # 自造标签：`_` 开头是显式声明，静默；字母开头多半是拼错，记一条 warning。
            warns.append("%s：clue 的标签 %r 不是已知类型，按关键词扫描"
                         "（自造标签请用 `_` 开头）" % (hid, raw_tag))
    else:
        tail = part
    if not tail:
        raise MarkError("%s：clue 的 %s 项缺值（要写谜面里出现的原词）"
                        % (hid, tag or "裸写"))
    if tail[0] in _QUOTE_PAIRS:
        return tag, _unquote(tail, hid, "clue 项")
    if "，" in tail:
        raise MarkError("%s：clue 项之间用英文逗号 `,`，不要用全角「，」"
                        "（正文本身带它就整项加引号）" % hid)
    for ch in _CLUE_NEEDS_QUOTE:
        if ch in tail:
            raise MarkError("%s：clue 项 %r 里有 %r——正文本身带冒号就整项用引号包起来，"
                            "例如 \"12:30\"" % (hid, tail, ch))
    if ";" in tail:
        raise MarkError("%s：clue 项里不能有 `;`（它切字段，引号也保不住）" % hid)
    return tag, tail


def _split_ans(arg, hid="", warns=None):
    """`[riddle:answer=城|城;group=00000001,00000002;clue=pun:August, "North, by sea"]`
    → ([(类型|None, 值)…], [同组其余副本的键…], [(类型|None, 词)…])。

    `answer` 里 `|` 是「或」（多个候选），`group` 里 `,` 连接本组全体成员的键（含本条）。
    `clue` 里 `,` 是唯一的并列符（每项都要在谜面正文里逐字出现）：`a,b,c` 三项。
    唯一保留的已知标签是 `pun`；`_` 开头的自造标签静默，字母开头的未知标签（含已退役的
    direction / count / feature / produce / history / exclude）只当关键词并往 `warns`
    记一条（多半是拼错；lint 算 E 级，构建前必须清零）。
    项里带冒号 `:` 时整项必须用引号包起来（`"12:30"`）：`:` 在裸写里是标签分隔，加引号才是
    正文。次要：`+` 在 clue 里已经没有任何含义（并值在第一百零六节退役），裸写就是正文，
    不必加引号；但裸写里若出现「谜面正文里找不到、却恰好含 `+`」的值，报错会提示改用 `,`
    并列——那是误用了旧写法，不是正文。
    `level=` 是谜题分级（direction / town / mixed），必须与谜底字段算出来的结果一致：
    这条只有方位键、只有城镇名、还是两者齐备。
    `answer` 正常不写类型（值在方位键里算方位，否则按城镇查表）；想明写类型就改用
    `town=` / `direction=` 这两个字段名，此时可以省掉 `answer=`：
    `[riddle:town=Vera Cruz;clue=…]` / `[riddle:direction=SE;clue=…]`。
    `group` 与 `clue` 都必填：单副本写 `group=<自己的键>`。
    空项、标签含大写/数字开头、已知类型缺值、缺谜底、字段重名、谜底写两处、裸写里的
    全角逗号、group 漏了本条或键形不对，一律失败。
    """
    fields = {}
    kind = None
    has_answer = False
    for part in _join_source_parts(arg, hid):
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
            "线索写 clue=东,四座）" % hid)
    answers = _answer_items(fields["answer"], hid, kind)
    group = _group_tokens(fields["group"], hid) if "group" in fields else []

    clue_raw = fields.get("clue", "")
    if not clue_raw:
        # clue 是必填：没有线索的谜底无从核对，标注就退化成一条注释。
        raise MarkError(
            "%s：ans 缺 clue（谜面里能推出谜底的词要逐条写成 clue=东,四座）" % hid)
    clues = []
    for part in split_clue_items(clue_raw, hid):
        tag, value = _clue_item(part, hid, warns)
        clues.append((tag, value))
    if not clues:
        raise MarkError(
            "%s：ans 只写了谜底 %r，没有 clue（谜面里能推出它的词要逐条写进来）"
            % (hid, "|".join(v for _, v in answers)))
    if "group" not in fields:
        raise MarkError(
            "%s：ans 缺 group（group 必填：列全组含本条自己；单副本写 group=%s）"
            % (hid, hid[2:] if hid.startswith("0x") else (hid or "<本条键>")))

    certainty = None
    if "certainty" in fields:
        certainty = fields["certainty"].strip()
        if certainty not in ANS_CERTAINTY:
            raise MarkError("%s：certainty 只能写 %s（收到 %r）"
                            % (hid, " / ".join(ANS_CERTAINTY), certainty))
    level = None
    if "level" in fields:
        level = fields["level"].strip()
        if level not in ANS_LEVELS:
            raise MarkError("%s：level 只能写 %s（收到 %r）"
                            % (hid, " / ".join(ANS_LEVELS), level))
    sources = _check_source(fields["source"], hid) if "source" in fields else []
    if certainty == "inferred":
        # inferred 是「靠别的证据推出来的」，所以必须写清推自哪里，且不能只说原文或自写。
        if not sources:
            raise MarkError("%s：certainty=inferred 必须写 source（推自哪份材料）" % hid)
        if all(kind in ("original", "authored") for kind, _t in sources):
            raise MarkError("%s：certainty=inferred 的 source 不能只有 original-*/authored"
                            "（没有外部依据就该写 certain）" % hid)
    # either 是「两个地点都成立」，答案用 `|` 列全。反向不设禁令：`|` 既可能是两座城，
    # 也可能同一座城的异写（`San Juan|St. Juan`），机器只数得出候选个数、分不清哪种，
    # 所以「多候选却没写 either」不报错，由作者自己交代清楚。
    if certainty == "either":
        if len(answers) < 2:
            raise MarkError("%s：certainty=either 要在 answer 里列两个以上候选"
                            "（answer=A|B）；只有一个答案就写 certain / inferred" % hid)
        if not sources:
            raise MarkError("%s：certainty=either 必须写 source（凭哪份材料说两个都成立）" % hid)
    return answers, group, clues, (kind or "answer"), certainty, sources, level


def _check_ans(arg, body, hid="", warns=None):
    """核对谜底与线索：线索必须逐条出现在谜面正文里。

    返回 (候选 [(类型|None, 值)…], 本组全体成员的键, 线索, 谜底字段名, certainty,
    来源 [(类别, 目标)…], level)。写错抛 MarkError。
    """
    answers, group, clues, field, certainty, sources, level = _split_ans(
        arg, hid, warns=warns)
    text = (body or "").casefold()
    missing = [v for _, v in clues if v.casefold() not in text]
    if missing:
        hint = ""
        if any("+" in v for v in missing):
            hint = ("（值里带 `+` 且整项不在谜面里：`+` 在 clue 里已不是并列符，要并列多个"
                    "片段请用半角 `,`；正文里真有加号就整项加引号）")
        raise MarkError(
            "%s：ans 的谜底是 %r，但线索 %s 没出现在谜面里（谜面推不出这个答案，"
            "或者线索该换）%s" % (hid, "|".join(v for _, v in answers),
                                  " / ".join(repr(v) for v in missing), hint))
    return answers, group, clues, field, certainty, sources, level


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
    copy_span = None
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
            # `[riddle:copy=键]` 是诗谜副本：本条没有自己的谜面，文本与身份都取目标键。
            # 它要独占整行，所以展开完正文后再整体确认没有别的东西。
            copy_key, copy_text = _copy_target(arg, doc, hid)
            if copy_key is None:
                ans_args.append(arg)  # 谜底只给翻译人看，玩家文本里不出现
            else:
                if copy_span is not None:
                    raise MarkError("%s：一行只能有一个 [riddle:copy=…]" % hid)
                copy_span = (m.start(), m.end())
                out.append(expand(copy_text, table, lang, copy_key,
                                  terms=terms, doc=doc))
        else:
            out.append(arg)
        i = m.end()
    rest = "".join(out)
    if _ANY_BRACKET.search(rest):
        raise MarkError("%s：展开后仍残留方括号（正文里不许出现 `[` 或 `]`）" % hid)
    if copy_span is not None:
        outside = (text[:copy_span[0]] + text[copy_span[1]:]).strip()
        if outside:
            raise MarkError("%s：copy= 要独占整行（[riddle:copy=键] 之外不许有正文）"
                            % hid)
    if len(ans_args) > 1:
        raise MarkError("%s：一条文本里只能写一个 [riddle:…]（收到 %d 个）"
                        % (hid, len(ans_args)))
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


def check_doc(lang, doc, entities=None, terms=None, warns=None, strict_warns=False,
              require_ans_meta=False):
    """返回问题列表（空 = 通过）。构建前和 lint 共用这一份判据。

    town 查 names 表、term 查 terms 表、ref 查本语言译文（只许一层），两边都是
    「缺条目即失败 + 死条目提醒」，调用方不需要额外提供原文。

    `warns` 传一个列表时，会把「自造 clue 标签」（非 `_` 开头、也不是已知类型）
    记进去。`strict_warns=True` 时这些条目同时算问题：构建前的复核走这一档，
    因为这种标签只做关键词扫描、没有任何校验，留在译文里等于放过拼错的类型名。
    `_` 开头的自造标签是显式声明，静默。

    `require_ans_meta=True` 时每条 riddle 都必须写 `certainty=` 与 `source=`（构建前的
    复核走这一档；语法解析期不强制，方便先写谜面再补依据）。见 09 卷第一百零九节。
    """
    problems = []
    warn_start = len(warns) if warns is not None else 0
    entities = load_entities() if entities is None else entities
    table = load_names(lang)
    terms = load_terms(lang) if terms is None else terms
    # 城名的宽容查表：同一串折平后可能对上几条登记名，那就得让作者挑明。
    ent_index = {}
    for name in entities:
        ent_index.setdefault(_fold(name), []).append(name)
    ans_used = set()
    ans_groups = {}
    riddle_bodies = {}
    ref_rows = {}
    copy_rows = {}
    for hid in sorted(doc):
        text = doc[hid] or ""
        if not text or hid in EXEMPT_KEYS:
            continue
        m_pure = _PURE_REF_RX.fullmatch(text.strip())
        if m_pure:
            # 整行 ref：本条没有自己的谜面，身份随目标键。ref 本身在下面的 ref
            # 分支里照常校验（存在、非空、不是自己、只许一层）。
            ref_rows[hid] = m_pure.group(1).strip()
        try:
            marks = scan(text)
        except MarkError as e:
            problems.append(str(e))
            continue
        riddle_marks = 0
        for key, arg in marks:
            if key == "term":
                try:
                    _resolve_term(arg, terms, hid, lang)
                except MarkError as e:
                    problems.append(str(e))
                continue
            if key == "riddle":
                riddle_marks += 1
                if riddle_marks > 1:
                    # 第二条 riddle 会把第一条的组信息覆盖掉（ans_groups[hid] 只留最后一个），
                    # 组内比对与统计就看不见第一条了——一条文本只许一个谜底标注。
                    problems.append("%s：一条文本里只能写一个 [riddle:…]（第二条会覆盖"
                                    "第一条的组信息）" % hid)
                    continue
                try:
                    copy_key, _copy_text = _copy_target(arg, doc, hid)
                except MarkError as e:
                    problems.append(str(e))
                    continue
                if copy_key is not None:
                    # 诗谜副本：语法自己声明了组身份，下面照 ref 的办法继承目标键的
                    # ans_groups。形状上要独占整行，否则「副本没有自己的谜面」不成立。
                    copy_rows[hid] = copy_key
                    if _ANS_SPAN.sub("", text).strip():
                        problems.append(
                            "%s：copy= 要独占整行（[riddle:copy=键] 之外不许有正文）" % hid)
                    continue
                # 谜底必须登记过实体，线索必须真的在谜面里——否则「这条谜面指向
                # 哪座城」无从核对，标注就退化成一条注释。答案本身不查译名：
                # 诗里不照抄译名。
                try:
                    answers, group, _clues, field, certainty, sources, level = _check_ans(
                        arg, _ANS_SPAN.sub("", text), hid, warns=warns)
                except MarkError as e:
                    problems.append(str(e))
                    continue
                if require_ans_meta:
                    if certainty is None:
                        problems.append(
                            "%s：ans 缺 certainty（certain / inferred / either / disputed 必写）"
                            % hid)
                    if not sources:
                        problems.append(
                            "%s：ans 缺 source（original-* / retail-* / fan-* / url / manual / "
                            "riddle / cargo / map / authored 必写一项）" % hid)
                    if level is None:
                        problems.append(
                            "%s：ans 缺 level（谜题分级 direction / town / mixed 必写）" % hid)
                # source 里指到别的诗谜时，目标必须存在、真带 riddle 标注、且不是自己。
                for kind_src, target in sources:
                    if kind_src != "riddle":
                        continue
                    for tok in target:
                        key = "0x" + tok
                        if key == hid:
                            problems.append("%s：source 的 riddle 指向自己" % hid)
                        elif key not in doc or not (doc[key] or "").strip():
                            problems.append("%s：source 的 riddle 指向的键 %r 不存在"
                                            % (hid, key))
                        elif not _ANS_SPAN.search(doc[key] or ""):
                            problems.append("%s：source 的 riddle 指向的键 %r 没有 riddle "
                                            "标注（指向了不相干的文本）" % (hid, key))
                sig = []
                cmp_sig = []
                kinds = set()
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
                    if kind in ANS_NAME_KINDS:
                        kinds.add(kind)
                    # 比对用的部分：「指明是城镇」的那几项。`answer=` 里夹着的方位候选
                    # 不参与（`|` 拆开后逐项看类型），`town=` 整字段参与，`direction=`
                    # 整字段不参与。两者落进同一个集合，所以一条写 answer=Vera Cruz、
                    # 另一条写 town=Vera Cruz 也算一致。
                    if field == "town" or (field == "answer" and kind == "town"):
                        cmp_sig.append(value)
                # 分级由谜底算：只有方位键 = direction，只有城镇名 = town，两者齐备 = mixed。
                # 声明（level=）只用来核对，不许跟谜底各说各话——否则「分级」就成了一句注释。
                if kinds:
                    derived = "mixed" if len(kinds) > 1 else sorted(kinds)[0]
                    if level is not None and level != derived:
                        problems.append(
                            "%s：level 写的是 %s，但谜底字段算出来是 %s（只用方位键就写 "
                            "direction，只给城镇名就写 town，城+方位齐备才写 mixed）"
                            % (hid, level, derived))
                ans_groups[hid] = (field, "|".join(sig), tuple(cmp_sig), group)
                # 同文索引：同一段谜面在数据里出现多次时，用来反向查「谁漏写了 group」。
                riddle_bodies.setdefault(_fold(_ANS_SPAN.sub("", text)), []).append(hid)
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
    # 整行 `[ref:键]` 的副本没有自己的谜面，身份（谜底、组、分级）随目标键继承。
    # 这样「同组的每一条都要标」与「同文副本必须同组」两条判据对 ref 副本同样成立：
    # 复制谜面时不必把整段 `[riddle:…]` 抄一遍（抄一遍反而会和目标键的写法分叉）。
    # 诗谜副本用 `[riddle:copy=键]`：身份同样继承，但归属是语法声明的，不是从「整行 ref」
    # 反推出来的——所以 ref 与 copy 互斥：诗谜行只许写 copy。
    for hid in sorted(ref_rows):
        target = ref_rows[hid]
        if target in ans_groups:
            problems.append(
                "%s：这条是诗谜副本，写 [riddle:copy=%s]，不要用 [ref:]（ref 只管不含谜的同文）"
                % (hid, target[2:] if target.startswith("0x") else target))
            continue
    for hid in sorted(copy_rows):
        target = copy_rows[hid]
        if target in ans_groups:
            ans_groups[hid] = ans_groups[target]
            riddle_bodies.setdefault(
                _fold(_ANS_SPAN.sub("", doc[target] or "")), []).append(hid)
        else:
            problems.append("%s：copy 的目标键 %s 没有 riddle 标注（副本要指向一条谜面）"
                            % (hid, target[2:] if target.startswith("0x") else target))
    # 同组自证：`group` 列全组含本条自己，所以每个成员的键列表本身就应该是同一个集合。
    # 组是身份不是答案——Roatán 出现在 14/15 两组、Providence 出现在 20/26 两组，
    # 按 answer 自动归并会把两个不同的寻宝组合成一个。
    group_sets = {}
    for hid_g in sorted(ans_groups):
        toks = ans_groups[hid_g][3]
        group_sets.setdefault(frozenset("0x" + t for t in toks), []).append(hid_g)
    for whole, hids in sorted(group_sets.items()):
        for hid_g in hids:
            for t_key in whole:
                if t_key not in ans_groups:
                    problems.append(
                        "%s：group 里的 %s 没有 riddle 标注（同组每条都要标）"
                        % (hid_g, t_key[2:]))
        present = [h for h in whole if h in ans_groups]
        for hid_g in present:
            if frozenset("0x" + t for t in ans_groups[hid_g][3]) != whole:
                problems.append(
                    "%s：与本组的组员集合不一致（group 列全组含自己，两边要一模一样）"
                    % hid_g)
        # 组内比对只看「指明是城镇」的部分：answer= 里推断成 town 的项 + town= 整字段，
        # 两者合成一个集合比（同组一条写 answer=Vera Cruz、另一条写 town=Vera Cruz
        # 也算一致）。direction= 与整条全是方位的成员比较为空，跳过。
        vals = {frozenset(ans_groups[h][2]) for h in present if ans_groups[h][2]}
        if len(vals) > 1:
            problems.append(
                "%s：同组谜底里的城镇部分不一致（%s）——同组的 answer/town 必须一样"
                "（方位部分不参与比对）"
                % (" / ".join(sorted(present)),
                   " / ".join("+".join(sorted(v)) for v in sorted(vals, key=lambda s: sorted(s)))))
    # 反向查漏：`group` 只从声明方出发，若整组都写错成「各写各的」，集合比对能抓；
    # 但两条同文的谜面各自声明成单副本时，集合也是自洽的——所以再从谜面本身出发：
    # 展开后的正文逐字相同（折平后）就算同文副本，必须同一组。
    # 只立这一个方向：同文 ⇒ 同组；不同文的条目当然可以同谜底（Roatán 在 14/15 两组、
    # Providence 在 20/26 两组，都是不同谜面同谜底），不能反过来要求。
    for body_key in sorted(riddle_bodies):
        members = riddle_bodies[body_key]
        if len(members) < 2:
            continue
        bad_sig = False
        vals = {frozenset(ans_groups[h][2]) for h in members if ans_groups[h][2]}
        if len(vals) > 1:
            problems.append(
                "%s 的谜面逐字相同，谜底里的城镇部分却不一样（%s）——同文副本的 "
                "answer/town 必须一样（方位部分不参与比对）"
                % (" / ".join(members),
                   " / ".join("+".join(sorted(v)) for v in sorted(vals, key=lambda s: sorted(s))))
                )
            bad_sig = True
        if bad_sig:
            continue
        whole = set(members)
        bad = [h for h in members
               if frozenset("0x" + t for t in ans_groups[h][3]) != whole]
        if bad:
            problems.append(
                "%s 的谜面逐字相同，group 却没列成同一组（%s 的声明对不上这 %d 条）——"
                "同文副本的 group 要完全相同"
                % (" / ".join(members), " / ".join(bad), len(members)))
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
    if strict_warns and warns is not None:
        # 自造标签不许留到构建：严格档把它们升级成问题，和 E 级一样卡住。
        for w in warns[warn_start:]:
            problems.append(w + "——构建前必须清零（改用 `_` 开头，或换成七个已知类型）")
    return problems
