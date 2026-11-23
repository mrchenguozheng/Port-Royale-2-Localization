# -*- coding: utf-8 -*-
"""诗谜谜底队列：把 glossary\\verse_ans.toml 里填好的 ans 落进各语译文。

谜面在 09 卷第六十四节定义的 verse 区间里，整片不挂 town/ref/lit/term，只允许
[riddle:answer=谜底;group=整组键含自己;clue=线索,…]（`;` 分字段；`answer` 里 `|` 是
「或」，`group` 里 `,` 连本组全体成员（含本条），`clue` 里 `,` 分项；
见 09 卷第七十八、七十九、八十一、八十三、一百零六、一百零七节）。`group` 与 `clue`
都必填，单副本写 `group=<自己的键>`（见第八十九节）。谜底正常写 `answer=`，靠值推断
类型；要明写类型就把字段名换成 `town=`（城名）或 `direction=`（方位），此时省掉
`answer=`（见第八十六节）。
`clue` 每项写成 `<标签>:<正文>` 或裸写 `<正文>`：唯一保留的已知类型是 pun，`_` 开头的
自造标签静默，字母开头的未知标签报 warning；裸写没有标签，整项就是正文片段。
项里带 `,`／`:`／`+` 就用半角引号包起来（`"…"`／`'…'`／`` `…` ``），引号里可以写另外
两种、不能写同一种；`I'm`、`l'abondance` 这类撇号在项中间，不必包。
这个工具只管那一件事：

    python src\\tools\\text\\verse_ans.py --list     # 看 32 组 / 48 槽位，谁还没填
    python src\\tools\\text\\verse_ans.py --apply    # 把填好的组写进各语译文

--apply 的判据：
  · answer 正常不写类型前缀：值在 marks.ANS_KEYS 里就是方位，否则按城镇查 entities；
    方位包括正向（north/east/southeast…）与否定（-north/-southeast…，减号表示
    「不是那边」）。这两类不登记实体、不查译名；
  · 各语线索都不能空，只收英文逗号，每条线索都要出现在该语言自己的谜面正文里；
  · 已经标成同值的组直接跳开（可重复跑），标成别的值则报错，不覆盖；没标注的键不算
    冲突，按待写补上（新接入一门语言时，它的谜面还没有 `[riddle:]` 头就属于这种）；
  · 诗谜副本（整行 `[riddle:copy=键]`）与不含谜的同文引用（整行 `[ref:键]`）都没有自己的
    谜面，一律跳过：标注只落在带文本的那条上，副本靠目标键继承（见 09 卷第一百一十六节）；
  · 队列只生成 answer/town/direction/group/clue 五个字段；`certainty` / `source`
    这类队列之外的字段由人工维护，重写标注时原样保留（`tail_fields`/`with_tail`）。
"""
import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import toml_io
import marks as MK

QUEUE = os.path.join(ROOT, "glossary", "verse_ans.toml")
EN_PATH = os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")
ENTITIES = os.path.join(ROOT, "src", "data", "names", "entities.toml")
NAMES_DIR = os.path.join(ROOT, "src", "data", "names")
TRANS = os.path.join(ROOT, "src", "translations")
LANGS = ("zh", "de", "es", "fr", "ja", "ru", "it", "pt-BR")
#: 城镇名在英文表里分 8 段，段间留空，合起来 76 条 = staedte.ini 的段数。
#: 早先只认了第一段（50 镇），Maracaibo / Caracas / Gibraltar / Port of Spain 这些
#: 落在后面的段里，查不到就等于「不在城镇表」。
TOWN_RANGES = (
    ("0xc77f4c7a", "0xc77f4c83"),   # 01–10
    ("0xc77f4ceb", "0xc77f4cf4"),   # 11–20
    ("0xc77f4d5c", "0xc77f4d65"),   # 21–30
    ("0xc77f4dcd", "0xc77f4dd6"),   # 31–40
    ("0xc77f4e3e", "0xc77f4e47"),   # 41–50
    ("0xc77f4eaf", "0xc77f4eb8"),   # 51–60
    ("0xc77f4f20", "0xc77f4f29"),   # 61–70
    ("0xc77f4f91", "0xc77f4f96"),   # 71–76
)
ANS_MARK = re.compile(r"^\[riddle:[^\[\]]*\]")
REF_ROW = re.compile(r"^\[ref:([^\[\]]*)\]$")
#: 诗谜副本行：`[riddle:copy=键]`——没有自己的谜面，标注只写在带文本的那条上。
COPY_ROW = re.compile(r"^\[riddle:copy\s*=[^\[\]]*\]$")


def is_copy_row(text):
    """这条是不是诗谜副本（`[riddle:copy=键]`）：副本没有谜面，--apply 不碰。"""
    return bool(COPY_ROW.match((text or "").strip()))


def load_queue():
    with open(QUEUE, "rb") as f:
        doc = tomllib.load(f)
    return doc.get("group", [])


def load_rows():
    en, _o = toml_io.read_doc(EN_PATH)
    return en, {l: toml_io.read_doc(os.path.join(TRANS, "%s.toml" % l))[0] for l in LANGS}


def town_ids():
    """城名（小写）→ 城镇表里的 id。"""
    en, _rows = load_rows()
    spans = [(int(a, 16), int(b, 16)) for a, b in TOWN_RANGES]
    out = {}
    for k in en:
        n = int(k, 16)
        if any(lo <= n <= hi for lo, hi in spans):
            name = en[k].strip()
            if name:
                out.setdefault(name.lower(), k)
    return out


def expand_name(lang, row):
    """城镇行 → 纯名字：`[ref:X]` 取名字表，否则用行内文本。"""
    m = REF_ROW.match(row.strip())
    if not m:
        return row.strip()
    names, _n = toml_io.read_doc(os.path.join(NAMES_DIR, "%s.toml" % lang))
    return (names.get(m.group(1), {}) or {}).get("default", "").strip()


def register_entity(name, town_id, rows):
    """登记成实体：entities.toml 一条 + names/<lang>.toml 一版（缺哪个语就报错）。

    两张表都按行追加文本，不经过 toml_io 的写回——名字表的值是 `default = "…"` 这种
    单纯表，嵌套写回没有必要，手写两行更不容易碰坏别的东西。
    """
    if os.path.isfile(ENTITIES):
        entities, _e = toml_io.read_doc(ENTITIES)
        if name in entities:
            return False
    with io.open(ENTITIES, "a", encoding="utf-8", newline="") as f:
        f.write('\n["%s"]\nkind = "town"\nnote = "诗谜谜底；登记来给 [riddle:] 用"\n' % name)
    for lang in LANGS:
        path = os.path.join(NAMES_DIR, "%s.toml" % lang)
        doc, _order = toml_io.read_doc(path)
        if name in doc:
            continue
        value = expand_name(lang, rows[lang].get(town_id, ""))
        if not value:
            raise SystemExit("%s 里推不出「%s」的译名（城镇行 %s 是空的）"
                             % (lang, name, town_id))
        with io.open(path, "a", encoding="utf-8", newline="") as f:
            f.write('\n["%s"]\ndefault = "%s"\n' % (name, value.replace('"', '\\"')))
    return True


def split_clues(text, lang):
    """把 `glossary/verse_ans.toml` 的 clues 串按顶层 `,` 切成值列表（引号里的逗号不算）。

    glossary 的线索只给值、不带标签（标签写在 `kinds` 里），所以这里把标签解析也走一遍
    只是为了统一引号口径；真写了 `pun:` 前缀会当标签吃掉并报错，免得悄悄变成值的一部分。
    """
    text = (text or "").strip()
    if not text:
        raise SystemExit("%s 的线索是空的——至少写一条" % lang)
    try:
        items = MK.split_clue_items(text, lang)
        parsed = [MK._clue_item(part, lang) for part in items]
    except MK.MarkError as exc:
        raise SystemExit("%s：%s" % (lang, exc))
    for tag, _value in parsed:
        if tag:
            raise SystemExit("%s 的线索不带标签（标签写在 kinds 里，收到 %r）" % (lang, tag))
    clues = [value for _tag, value in parsed]
    if any(not c for c in clues):
        raise SystemExit("%s 的线索里有空项（连着两个逗号，或首尾多逗号）" % lang)
    return clues


def cmd_list(all_langs=False):
    en, rows = load_rows()
    groups = load_queue()
    done = 0
    for i, g in enumerate(groups, 1):
        ids = g.get("ids", [])
        ans = (g.get("ans") or "").strip()
        marked = any("[riddle:" in rows["zh"].get(k, "") for k in ids)
        done += 1 if marked else 0
        print("[%02d] %-3s %s" % (i, "已标" if marked else "待填", ",".join(ids)))
        print("     EN %s" % en.get(ids[0], "")[:100].replace("\n", " "))
        print("     ZH %s" % rows["zh"].get(ids[0], "")[:80].replace("\n", " "))
        if all_langs:
            # 线索必须在每门语言的谜面里都能找到，逐门读一遍省得来回翻 toml
            for lang in LANGS:
                if lang == "zh":
                    continue
                print("     %-2s %s" % (lang.upper(),
                                        rows[lang].get(ids[0], "").replace("\n", " ")))
        if ans:
            print("     ans %s" % ans)
    print("\n%d 组，已标 %d 组，待填 %d 组" % (len(groups), done, len(groups) - done))


def clue_value_text(value):
    r"""一个线索值写进标注串时的形状：能裸写就裸写，需要才加引号。

    裸写里 `,` 是项分隔、`:` 是标签分隔、`+` 是已退役的并值符，正文里带这些字符就
    整项包引号；项首是引号字符（`'tis`、`"quoted"`、`` `code` ``）也要包，否则会被当成
    引号起点。外层按「值里没有的那种」挑：先双引号，再单引号，再反引号；三种都占满时
    退回双引号并把值里的 `"` 与 `\` 转义（`\"` 与 `\\`），语法里没有写不出的值。
    """
    v = value or ""
    if not v.strip():
        raise SystemExit("线索值是空的")
    if ";" in v:
        raise SystemExit("线索 %r 里有 `;`：它切字段，加引号也保不住" % v)
    need = (v != v.strip() or v[0] in _QUOTE_LEAD or
            any(ch in v for ch in ",:+"))
    if not need:
        return v
    for q in _QUOTE_LEAD:
        if q not in v:
            return q + v + q
    return '"%s"' % v.replace("\\", "\\\\").replace('"', '\\"')


#: 可用的外层引号，按「优先用哪个」排：值里的竖线/撇号比反引号常见。
_QUOTE_LEAD = "\"'`"


def clue_text(clues, kinds, lang):
    """把一语的线索拼成标注串。

    `clue` 里 `,` 是唯一的并列符，每一项一段：`kinds` 缺省（空）就整组裸写；给了就按位
    贴标签，条数与线索必须相等，某一项给空串表示这条不贴标签。不再用 `+` 并值——连写
    两个值就是两段，与逗号并列完全重复，留两套写法只会让 `--apply` 判不清谁规范。
    标签可以是唯一的已知类型 `pun`，也可以是自造标签：`_` 开头静默，字母开头的未知
    标签展开侧会报 warning（这里不拦）。
    """
    if not clues:
        raise SystemExit("%s 的线索是空的" % lang)
    if not kinds:
        kinds = [""] * len(clues)
    if len(kinds) != len(clues):
        raise SystemExit("%s 的线索 %d 条，kinds 给了 %d 条（逐语对齐）"
                         % (lang, len(clues), len(kinds)))
    parts = []
    for k, c in zip(kinds, clues):
        val = clue_value_text(c)
        parts.append("%s:%s" % (k, val) if k else val)
    return ",".join(parts)


def _fields(arg):
    """`[riddle:…]` 里的字段串 → {字段名: 原值}，只做最松的切分（不校验）。"""
    out = {}
    for part in arg.split(";"):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        out.setdefault(name.strip(), value.strip())
    return out


#: 队列负责生成的字段；其余字段（`certainty` / `source` …）由人工维护，重写时必须原样带回。
QUEUE_FIELDS = ("answer", "town", "direction", "group", "clue")


def tail_fields(text):
    """已有标注里队列不生成的那些字段，按原样返回（`;` 分隔的一段段）。

    引号内不可能出现 `;`（语法禁止），所以这里按 `;` 直接切是安全的；切出来的段不重排、
    不改写，原封不动带回去。
    """
    m = ANS_MARK.match(text or "")
    if not m:
        return []
    arg = m.group(0)[len("[riddle:"):-1]
    out = []
    for part in arg.split(";"):
        name = part.partition("=")[0].strip()
        if name in QUEUE_FIELDS:
            continue
        if part.strip():
            out.append(part.strip())
    return out


def with_tail(wanted, text):
    """把 `text` 里的尾字段接到 `wanted` 上，返回新的标注串。"""
    tails = tail_fields(text)
    if not tails:
        return wanted
    assert wanted.endswith("]"), wanted
    return wanted[:-1] + ";" + ";".join(tails) + "]"


def _group_norm(raw):
    """group 值 → 升序键元组；顺手吃掉 `0x` 前缀、大小写与两侧空白，用来比较而不是校验。

    `--apply` 不再接受旧分隔符：`a+b` 在这里就是一个非法令牌（与 `a,b` 不同值），
    该被当冲突报出来，而不是悄悄规范成逗号写法。
    """
    toks = []
    for t in (raw or "").split(","):
        t = t.strip().lower()
        if t.startswith("0x"):
            t = t[2:]
        if t:
            toks.append(t)
    return tuple(sorted(toks))


def _clue_norm(raw):
    """clue 值 → ((标签, 值)…)（值折平），没有语法先按原串比。

    一项一段、顺序与写法都留着：`a+b` 已经被语法禁掉（`+` 在裸写里报错），所以
    `a+b,c` 与 `a+b+c` 这种「两套写法同语义」的歧义不存在——谁写了谁报错，不用猜。
    引号里的值与裸写值比的是同一个东西（`"12:30"` 与 `12:30` 的正文一致）。
    """
    try:
        items = MK.split_clue_items(raw or "")
        parsed = [MK._clue_item(part, "") for part in items]
    except MK.MarkError:
        return ("RAW", raw)
    return tuple((tag or "", value.casefold()) for tag, value in parsed)


def mark_key(text, ent_index):
    """把一条已有标注归一成可比较的键：没有标注返回 None。

    这是 `--apply` 的「已标成同值就跳过」判据，所以比 `check_doc` 松：
    谜底值走 marks 的解析（方位缩写/否定/大小写/变音都归成一串），城名再按折平查登记名；
    字段名 answer= 与 town= 不再区分（两者都「指明是城镇」，check_doc 侧也是同一个比对集），
    group 吃 `0x` 前缀与顺序，clue 只忽略分隔符两侧空白。
    """
    m = ANS_MARK.match(text or "")
    if not m:
        return None
    arg = m.group(0)[len("[riddle:"):-1]
    fields = _fields(arg)
    kind = "town" if "town" in fields else ("direction" if "direction" in fields else None)
    raw = fields.get("town") or fields.get("direction") or fields.get("answer")
    if raw is None:
        return ("RAW", arg)
    try:
        items = MK._answer_items(raw, "", kind)
    except MK.MarkError:
        return ("RAW", arg)
    answers = []
    for item_kind, value in items:
        is_dir = item_kind == "direction" or (item_kind is None and value in MK.ANS_KEYS)
        if is_dir:
            answers.append(("direction", value))
            continue
        cands = ent_index.get(MK._fold(value), [])
        answers.append(("town", cands[0] if len(cands) == 1 else value))
    return (tuple(sorted(answers)), _group_norm(fields.get("group", "")),
            _clue_norm(fields.get("clue", "")))


def cmd_apply():
    en, rows = load_rows()
    groups = load_queue()
    towns = town_ids()
    ents = toml_io.read_doc(ENTITIES)[0] if os.path.isfile(ENTITIES) else {}
    ent_index = {}
    for name in ents:
        ent_index.setdefault(MK._fold(name), []).append(name)
    changed = skipped = normed = 0
    for g in groups:
        ans = (g.get("ans") or "").strip()
        if not ans:
            continue
        ids = g.get("ids", [])
        assert ids, "组里没有 id"
        for k in ids:
            assert k in en, "队列里的 %s 不在英文原文里" % k

        # `|` 是并列成立的候选（certainty=either）：每个候选都是独立的谜底值，
        # 各自过登记/城镇表校验；方位候选不登记实体。
        cands = [c.strip() for c in ans.split("|")]
        assert cands and all(cands), "谜底「%s」的 | 两侧不能空" % ans
        for cand in cands:
            if cand in MK.ANS_KEYS:
                continue        # 方位谜底不进 entities.toml：它不是专名，也没有译名可登记
            if os.path.isfile(ENTITIES) and cand in toml_io.read_doc(ENTITIES)[0]:
                continue
            tid = towns.get(cand.lower())
            if not tid:
                raise SystemExit("谜底「%s」既不在 entities.toml、城镇表，也不是方位键"
                                 "（正向 north…、否定 -north…，见 marks.ANS_DIRECTIONS）"
                                 % cand)
            register_entity(cand, tid, rows)
            print("登记实体 %s（城镇行 %s）" % (cand, tid))

        # 谜底字段：方位与城名默认写 answer=（靠值推断）；只有单候选的城名恰好与方位键
        # 同名（目前 0 例）才改写成 town= 字段，把类型说明白。
        answer_field = "answer"
        if len(cands) == 1 and ans in MK.ANS_KEYS and towns.get(ans.lower()):
            answer_field = "town"

        wanted = {}
        # 整行 `[ref:键]` 是普通同文引用；`[riddle:copy=键]` 是诗谜副本——两者都没有
        # 自己的谜面：标注只写在带文本的那条上，副本靠目标键继承（组里仍然列全组键，
        # 副本仍在 group 名单里）。--apply 只碰带文本的键。
        text_ids = {lang: [k for k in ids
                           if not REF_ROW.match((rows[lang].get(k) or "").strip())
                           and not is_copy_row(rows[lang].get(k))]
                    for lang in LANGS}
        for lang in LANGS:
            clues = split_clues((g.get("clues") or {}).get(lang, ""), lang)
            kinds = (g.get("kinds") or {}).get(lang, [])
            text = ANS_MARK.sub("", rows[lang].get(text_ids[lang][0], ""))
            for c in clues:
                if c.casefold() not in text.casefold():
                    raise SystemExit("%s 的线索「%s」没出现在谜面里（%s）"
                                     "——谜面推不出这个谜底，或者线索该换" % (lang, c, ids[0]))
            clue_part = clue_text(clues, kinds, lang)
            for k in text_ids[lang]:
                # group 列全组含本条自己（8 位小写十六进制、不带 0x、升序、`,` 分隔）
                members = ",".join(sorted(
                    x[2:] if x.startswith("0x") else x for x in ids))
                wanted[(lang, k)] = "[riddle:%s=%s;group=%s;clue=%s]" % (
                    answer_field, ans, members, clue_part)

        order = [(lang, k) for k in ids for lang in LANGS if (lang, k) in wanted]
        already = {lk: rows[lk[0]].get(lk[1], "") for lk in order}
        want_mark = {lk: ANS_MARK.match(wanted[lk]).group(0) for lk in order}
        # 尾字段（certainty / source）不在队列里，重写时原样接回去，不能抹掉。
        new_mark = {lk: with_tail(want_mark[lk], already[lk]) for lk in order}
        # 只有「已经有标注」的键才谈得上冲突：没标注的键是要补写（比如刚接入一门
        # 新语言），mark_key 对它返回 None，不能拿 None 跟队列值比，否则每次加语言
        # 都会在第一组就报「已有标注与队列填的不同」，而打印的又是按 order 排在最
        # 前面的 zh 那条（本身完全正确）。
        conflict = []
        same_key = []
        for lk in order:
            mk = mark_key(already[lk], ent_index)
            if mk is None:
                same_key.append(False)          # 待写，不是冲突
                continue
            same = mk == mark_key(want_mark[lk], ent_index)
            same_key.append(same)
            if not same:
                conflict.append(lk)
        same_text = [(ANS_MARK.match(already[lk]).group(0) if ANS_MARK.match(already[lk])
                      else None) == new_mark[lk] for lk in order]
        if all(same_key) and all(same_text):
            skipped += 1
            continue
        if conflict:
            lk = conflict[0]
            raise SystemExit("%s 里 %s 的 %s 已有标注 %s，与队列填的不同；先人工核对"
                             % (ids, lk[0], lk[1], ANS_MARK.match(already[lk]).group(0)))


        for lang in LANGS:
            path = os.path.join(TRANS, "%s.toml" % lang)
            doc, order_t = toml_io.read_doc(path)
            for k in text_ids[lang]:
                mark = new_mark[(lang, k)]
                if "[riddle:" in doc[k]:
                    # 值相同、只是写法不规范（大小写/变音/方位缩写/group 带 0x 之类）：
                    # 原地换成规范串，正文和尾字段都不动。
                    assert ANS_MARK.match(doc[k]), (lang, k)
                    doc[k] = ANS_MARK.sub(mark, doc[k], count=1)
                else:
                    doc[k] = mark + doc[k]
            toml_io.write_doc_atomic(path, doc, order=order_t,
                                     header=toml_io.head_lines(path))
        if all(same_key):
            normed += 1
            print("规范化 %s -> %s" % (",".join(ids), ans))
        else:
            changed += 1
            print("落标注 %s -> %s" % (",".join(ids), ans))
    print("\n本次落 %d 组，规范化 %d 组，跳过（已是该值）%d 组"
          % (changed, normed, skipped))


def main():
    ap = argparse.ArgumentParser(description="诗谜谜底队列")
    ap.add_argument("--list", action="store_true", help="列出各组与填写状态")
    ap.add_argument("--langs", action="store_true",
                    help="配合 --list：六门谜面全打出来（线索要逐门核对）")
    ap.add_argument("--apply", action="store_true", help="把填好的谜底落进各语译文")
    args = ap.parse_args()
    if args.list:
        cmd_list(args.langs)
    elif args.apply:
        cmd_apply()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
