#!/usr/bin/env python
# coding: utf-8
r"""src/tools/translate.py — 译文数据层：合并、进度、落盘

    python src/tools/translate.py status                    # 看翻译进度（全语言）
    python src/tools/translate.py status --lang ko          # 只看一门
    python src/tools/translate.py apply --lang ko --map build/x.json
    python src/tools/translate.py gaps --lang ko            # 源缺失自查

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
  * apply —— 把一份 `{英文原串: 译文}` 的映射落进译文文件。
    以前每批翻译都要手写一遍「读 → 查表 → 贴回首尾空白 → 写」，
    六批下来攒了八个一次性脚本，其中两次踩到同一个坑（带尾空格的键
    对不上、自检逻辑写反）。这里把这件事收成一条命令：
      - 按 strip 后的值查表，首尾空白原样贴回；
      - 同一条译文只写一次，重复条目自动一致；
      - 报「命中几条、映射里哪几条根本没对上」（后者是真缺口，必须报）；
      - 写盘前跑占位符-助词检查与 token 齐备检查，不合格直接拒绝落盘；
      - 再跑一次命中 0 条，幂等性自证。
  * gaps —— 源缺失自查：英文原值本身就是个令牌（如
    `IDM_CONTEST_01_2004_LOG_00_HDR`），而译文里有实文。这类条目
    靠长度分档抽查碰不到，只能机械扫。
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
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                     # 仓库的 src\
ROOT = os.path.dirname(SRC)                     # 仓库根
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)                    # 让 `text` 包可导入

# 占位符与标签规则只有一份，在 shared\core\validate.py。
# 这里转出来，是为了让 `import translate as T` 的老调用点（编辑器、
# 审计脚本）继续能用 T.tokens / T.tag_profile。
from shared.core.validate import PH_RE, tag_profile, tokens  # noqa: E402
from text import lang_rules, toml_io  # noqa: E402

STRINGS_DIR = os.path.join(SRC, "translations")
REFERENCES_DIR = os.path.join(SRC, "orig")

#: 译文**唯一手改层**：translations\<语言>.toml，**每条一行**：
#:     "0xd2d0a572" = "萧条"
#: 文件名以语言代码开头，没有块头也没有字段名，所以语言代码与文件里
#: 的内容是同一个名字，不需要任何映射表。
#: 引擎文本（补空格、全角标点、`<n>` 之类的排版加工）是**构建产物**，
#: 由 src\tools\text\engine_text.py 生成到 build\preview\engine_text\<语言>.toml，
#: 不进仓库 —— 所以这里只读译文层，不存在第二份成品文本。
#: 只读参考原文放在 orig\ 目录：
#:     orig\en.gog_1.1.2.3.toml    英文原文（GOG 1.1.2.3 原版表），合并基准
#:     orig\fr.gog_1.1.2.42.toml   法文原文（GOG 1.1.2.42 原版表）
#: 文件名里带来源与版本：这两份是**从原版 exe 里原样提取**的，不经过我们的
#: 导出/整理，所以 `<n>`、行尾空格都保持原样。版本号不同，两边条目数可能
#: 对不齐（法语 3571 vs 英文 3548），合并时按 id 对齐、多退少空。
#: 语言列表不写死 —— 加一种语言只需把 <代码>.toml 放进 translations\。
BASE_LANG = "en.gog_1.1.2.3"

#: 只读参考语言：参与 id 顺序与占位符校验，但不提供译文。
#: 英语/法语是主参考；零售包只作补充对照，不优先采用。
PRIMARY_REFERENCE_LANGS = ("en.gog_1.1.2.3", "fr.gog_1.1.2.42")
RETAIL_REFERENCE_LANGS = (
    "de.retail-1.0.0",
    "es.retail-1.0.0",
    "pl.retail-1.0.0",
    "ru.retail-1.0.0",
)
REFERENCE_LANGS = PRIMARY_REFERENCE_LANGS + RETAIL_REFERENCE_LANGS
#: 法文原文的字段名（合并结果里 lang 字段就是文件名，没有短键别名）。
FR_LANG = "fr.gog_1.1.2.42"


def set_src(src):
    """把数据根指到另一份 src（测试用临时副本），重算派生路径。

    只改路径，不改语言清单与规则：`target_langs()`、`all_langs()` 都是
    现算的，所以换根之后自然跟着走。
    """
    global SRC, ROOT, STRINGS_DIR, REFERENCES_DIR
    SRC = os.path.abspath(src)
    ROOT = os.path.dirname(SRC)
    STRINGS_DIR = os.path.join(SRC, "translations")
    REFERENCES_DIR = os.path.join(SRC, "orig")


def lang_path(code):
    """语言代码 -> 文件路径。只读参考在 orig\\ 目录下。"""
    base = REFERENCES_DIR if code in REFERENCE_LANGS else STRINGS_DIR
    return os.path.join(base, code + ".toml")


def target_langs():
    """可编辑的译文语言代码，按文件名排序（不含只读参考）。"""
    if not os.path.isdir(STRINGS_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(STRINGS_DIR)
                  if f.endswith(".toml") and not f.startswith("_")
                  and f[:-5] not in REFERENCE_LANGS)


def all_langs():
    """合并时读取的全部语言代码：只读参考在前，译文在后。"""
    return [c for c in REFERENCE_LANGS if os.path.exists(lang_path(c))] \
        + target_langs()


def target_field():
    """status 默认操作的那个译文语言字段名。

    取 src\\translations 下第一个可编辑语言；一个译文都没有时报错，
    因为那样「已译 / 待译」根本没有对象。
    """
    langs = target_langs()
    if not langs:
        raise SystemExit(r"%s 下没有任何可编辑的 *.toml 译文文件。" % STRINGS_DIR)
    return langs[0]

# 占位符与标签规则已移到 shared\core\validate.py（tokens / tag_profile）。
# 编译脚本与两个编辑器后端原先各有一份，取值口径互不相同。本文件只把
# import 进来的转出去给老调用点。注意 %02 与 %2 按字面区分 —— 0 是补零
# 宽度，别归一化（这里以前干过，是错的）。

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

    #: 英文微调层：`src/overrides/en.toml` 只放「确认原版写错」的条目。
    #: 原版提取（orig/en.gog…）永远保持原样，做审计与 token 比对都用它；
    #: 这里改的是合并后的语义基准，出 english 包与翻译参照都走这一版。
    overrides = load_overrides(OVERRIDES_CODE)
    missing_ov = [i for i in overrides if i not in merged]
    for rid, text in overrides.items():
        if rid in merged:
            merged[rid][BASE_LANG] = text
    if missing_ov:
        sys.stderr.write("提示：overrides 里有 %d 条 id 不在基准表里：%s\n"
                         % (len(missing_ov), "、".join(missing_ov[:5])))

    return {"s": [merged[i] for i in order], "missing": missing}


def entries(doc):
    return doc.get("s", [])


def overrides_dir():
    """英文微调层目录（现算，set_src 换根后跟着走）。"""
    return os.path.join(SRC, "overrides")

#: 微调层按语言代码存（`en.toml`），基准名 `en.gog_1.1.2.3` 取前缀。
OVERRIDES_CODE = BASE_LANG.split(".")[0]


def load_overrides(code):
    """读 `src/overrides/<code>.toml`：{id: 修正后的原文}。

    只用于「原版确实写错」的条目。不做文风润色 —— 每次改动都要在
    `overrides/<code>.md` 里留一行依据，否则半年后没人知道为什么和原版不一样。
    """
    path = os.path.join(overrides_dir(), code + ".toml")
    if not os.path.exists(path):
        return {}
    import tomllib
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    return {k: v for k, v in doc.items() if isinstance(v, str)}


def check_overrides(code):
    """防线：overrides 的 id 必须存在、token 必须与原版完全一致。

    微调改的是词句，不该动 `%1` / `@n$…$` / `<n>` —— 改坏了会让所有语言的
    占位符校验都失去基准。返回 (缺 id, token 不一致, 白改) 三张清单。
    """
    #: 原版提取，按当前基准名取（`set_src` 换根后也跟着走）。
    raw_path = os.path.join(REFERENCES_DIR, BASE_LANG + ".toml")
    if not os.path.exists(raw_path):
        return [], [], []
    import tomllib
    with open(raw_path, "rb") as f:
        raw = tomllib.load(f)
    ov = load_overrides(code)
    missing = [i for i in ov if i not in raw]
    bad_tok = [i for i, t in ov.items()
               if i in raw and sorted(tokens(t)) != sorted(tokens(raw[i]))]
    noop = [i for i, t in ov.items() if i in raw and t.strip() == str(raw[i]).strip()]
    for i in bad_tok:
        print("  token  %s  原版 %s | 微调 %s"
              % (i, tokens(raw[i]), tokens(ov[i])))
    for i in missing:
        print("  缺条目 %s" % i)
    for i in noop:
        print("  白改   %s  与原版无差别" % i)
    return missing, bad_tok, noop


# ── 进度 ────────────────────────────────────────────────────

#: 判「有没有字」时先抹掉引擎标签：`<n>`、`<ts:0>` 之类不算内容。
#: 判「有没有字」时先抹掉结构成分：`<n>`/`<ts:0>` 这类引擎标签、
#: `[town:Havana]`/`[term:en_business]` 这类键、`%1`/`@A$Amount$` 占位符。
#: 它们本来就不该译，留在里面会把「保持原样是对的」误报成待译。
TAG_RX = re.compile(r"<[^<>]*>")
STRUCT_RX = re.compile(r"\[[^\[\]]*\]|%[0-9A-Za-z]+|@[A-Za-z]\$[^$]*\$")
#: 「有没有文字」按 Unicode 字母算，不只 ASCII —— 中文译文里全是汉字、
#: 韩语里混进中文，都是「有文字但不是目标文字」，不能当成纯符号条目放过。
LETTER_RX = re.compile(r"[^\W\d_]", re.UNICODE)

#: 英文原值像个令牌：全大写、无空格、没有小写字母。`IDM_CONTEST_01_2004_*`
#: 这一类在英文表里就是键名本身，中文表却是实文 —— `gaps` 专门抓这个。
TOKEN_SRC_RX = re.compile(r"^[A-Z][A-Z0-9_]{8,}$")

#: 待译条目的长度分档，与批次划分口径一致。
BANDS = ((0, 12), (13, 24), (25, 40), (41, 80), (81, None))


def content_of(value):
    """抹掉标签、方括号键与占位符后剩下的人话。"""
    return STRUCT_RX.sub("", TAG_RX.sub("", value or ""))


def is_translated(value, lang, base=None, script=None):
    """这条值算不算「已译」。

    三个判定，按顺序：

    1. 目标语言有 `SCRIPT`（zh/ja/ko/ru）：出现目标文字才算译。
       未翻译的条目值就是英文原串，所以「不是纯占位符」那种判据在这里
       会把整篇判成已译 —— 这正是上一版 `status` 的毛病；
       反过来，韩语文件里出现中文也要判待译，所以「有没有文字」按 Unicode
       字母算，只有纯数字/纯符号/纯标签条目才当成天然已译；
    2. 拉丁字母语言（fr/de/es）没有目标文字可认，只能按「与英文原文不同」判。
       纯符号条目同样天然已译。

    `lang_rules.script_re()` 取第 1 条的正则，`base` 是英文原值（第 2 条用）。
    """
    vis = content_of(value)
    if script is not None:
        if script.search(vis):
            return True
        return not LETTER_RX.search(vis)
    if not LETTER_RX.search(vis):
        return True
    return vis.strip() != content_of(base).strip()


def band_of(text):
    n = len(text.strip())
    for lo, hi in BANDS:
        if hi is None or n <= hi:
            return lo, hi
    return 81, None


def band_label(lo, hi):
    return ">%d" % (lo - 1) if hi is None else ("%d–%d" % (lo, hi) if lo else "≤%d" % hi)


def keep_dir():
    """有意不译清单目录（现算，set_src 换根后跟着走）。"""
    return os.path.join(SRC, "data", "keep_as_is")


def keep_as_is(lang):
    """「有意不译」清单：{id: 理由}。文件不存在就是空清单。

    这些条目（按键名 F1/ESC、表头 Looted<t>…、职员表、脚本 id）的正确译法
    就是英文原样。不单列出来，它们会永久占着「待译」，进度永远到不了 100%，
    也分不清剩下的是「没干」还是「不该干」。

    读两份：`_common.txt`（七种语言共用，职员表、存档名模板都在这里）+ `<lang>.txt`
    （语言自己的按键名/表头）。同一个 id 两边都写了，以语言文件为准。
    """
    out = {}
    for name in ("_common.txt", lang + ".txt"):
        path = os.path.join(keep_dir(), name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    out[parts[0].strip()] = parts[1].strip()
    return out


def pending_ids(es, field):
    """还待译的条目 id 列表（判据同 `is_translated`，扣掉有意不译的）。"""
    script = lang_rules.script_re(field)
    keep = keep_as_is(field)
    return [e["id"] for e in es
            if e["id"] not in keep
            and not is_translated(e.get(field, ""), field,
                                  base=e.get(BASE_LANG, ""), script=script)]


def pending_of(es, field):
    """待译条目。

    这里以前还会顺带数一个「与英文逐字相同」的条数，后来发现它必然
    等于待译条数（没译的条目，值就是英文原串），全表和待译集合两种口径
    算出来的数还互相打脸（773 vs 657）。没有信息量的统计不如不要。
    """
    ids = set(pending_ids(es, field))
    return [e for e in es if e["id"] in ids]


def report_status(field, es):
    pend = pending_of(es, field)
    keep = keep_as_is(field)
    total = len(es)
    done = total - len(pend) - len(keep)
    print("[%s] 共 %d 条，已译 %d 条（%.1f%%），待译 %d 条%s"
          % (field, total, done, 100.0 * done / max(1, total), len(pend),
             "（另 %d 条有意不译，不计）" % len(keep) if keep else ""))
    if not pend:
        return
    buckets = {}
    for e in pend:
        buckets.setdefault(band_of(content_of(e.get(field, ""))), []).append(e)
    parts = ["%s:%d" % (band_label(lo, hi), len(buckets[(lo, hi)]))
             for lo, hi in BANDS if (lo, hi) in buckets]
    print("     待译长度分布：%s" % "  ".join(parts))


def cmd_status(args):
    doc = load_toml()
    es = entries(doc)
    langs = [args.lang] if args.lang else target_langs()
    for field in langs:
        report_status(field, es)


# ── 落盘：把映射应用进译文 ──────────────────────────────────


def josa_rules():
    """占位符-助词检查的两条正则，取 `text_lint` 的唯一一份实现。

    取不到就返回 (None, None)：检查缺失不该让落盘失败，但会打印提示 ——
    宁可少一道门，也不要偷偷改成另一份规则。
    """
    path = os.path.join(HERE, "analysis")
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import text_lint
        return text_lint.PH_BARE, text_lint.PH_PAIR
    except Exception as exc:                    # noqa: BLE001
        print("提示：取不到 text_lint 的占位符-助词规则（%s），跳过这道检查。" % exc)
        return None, None


def load_map(path):
    """读 `{英文原串: 译文}`；值不是字符串、或源串重复归一化后撞车就报错。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("map"), dict):
        data = data["map"]                    # 允许 {"map": {...}} 包一层
    if not isinstance(data, dict):
        raise SystemExit("映射文件必须是 {\"英文原串\": \"译文\"} 的 JSON 对象。")
    out, clash = {}, []
    for k, v in data.items():
        if not isinstance(v, str):
            raise SystemExit("映射 %r 的值不是字符串。" % k)
        kk = k.strip()
        if kk in out and out[kk] != v:
            clash.append(kk)
        out[kk] = v
    if clash:
        raise SystemExit("映射里有 %d 个源串去掉首尾空白后撞车：%s"
                         % (len(clash), "、".join(clash[:5])))
    return out


def token_diff(old, new):
    """占位符/token 与原文比，缺了或多了都算不合格（顺序允许调）。"""
    return sorted(tokens(old)) != sorted(tokens(new))


def apply_map(lang, mapping, dry_run=False):
    """把映射落进 `translations/<lang>.toml`。返回统计字典。

    查表用 strip 后的值，命中后把原值的首尾空白贴回 —— 六批脚本里只有
    最后两批写对了这一点，所以这里把它写进代码，而不是写进注释。

    三种命中状态分开报：
      * `hit`   写进去的条数（改过的）；
      * `same`  值已经等于映射译文的条数 —— 重跑时就是这些，幂等的证据；
      * `rewrite` 命中里有几条本来已经是目标文字（即这次是**修正**旧译文）。
    映射里既没按源串命中、也没按译文对上的键才进 `unused`，那才是真缺口。
    """
    if lang in REFERENCE_LANGS:
        raise SystemExit("%s 是只读参考语言，不能落盘。" % lang)
    path = lang_path(lang)
    if not os.path.exists(path):
        raise SystemExit("没有 %s" % path)
    doc, order = toml_io.read_doc(path)
    header = toml_io.head_lines(path)

    hit_ids, used, same, rewritten = [], set(), 0, 0
    bad_josa, bad_tok, bad_lang = [], [], []
    script = lang_rules.script_re(lang)
    ph_bare, ph_pair = josa_rules()
    #: 有意不译的条目：它们**正确**的值就是英文原串，写回去不算「抄错行」。
    keep_ids = set(keep_as_is(lang))

    #: 已经落过盘的译文：映射里没按源串命中的键，可能只是「已经应用过」。
    landed = set()
    for hid in order:
        val = (doc.get(hid, "") or "").strip()
        if val:
            landed.add(val)

    for hid in order:
        cur = doc.get(hid, "")
        key = cur.strip()
        # 键有两种：英文原串（正常落盘）、hash（修正已经译过的条目 ——
        # 那时原串已经不在文件里了，只能按 id 找）。
        by_id = hid in mapping
        if by_id:
            new = mapping[hid]
        elif key in mapping:
            new = mapping[key]
        else:
            continue
        if not by_id and key == new.strip():
            same += 1                      # 映射与现值一模一样
            used.add(key)
            continue
        if script is not None and script.search(content_of(cur)):
            rewritten += 1                 # 现值是目标文字：这次是修正
        lead = cur[:len(cur) - len(cur.lstrip())]
        trail = cur[len(cur.rstrip()):]
        val = lead + new.strip() + trail
        if token_diff(cur, val):
            bad_tok.append(hid)
            continue
        if ph_bare is not None and not ph_pair.search(val) and ph_bare.search(val):
            bad_josa.append((hid, val))
            continue
        # 映射值必须是目标文字：韩语映射里写回英文，多半是抄错了行。
        # 例外是名单内条目 —— 它们的正确值本来就是英文，用来把译错的名字改回去。
        vis = content_of(val)
        if (script is not None and hid not in keep_ids
                and LETTER_RX.search(vis) and not script.search(vis)):
            bad_lang.append((hid, val))
            continue
        doc[hid] = val
        hit_ids.append(hid)
        used.add(hid if by_id else key)

    unused = sorted(k for k, v in mapping.items()
                    if k not in used and v.strip() not in landed)
    applied = sum(1 for k, v in mapping.items()
                  if k not in used and v.strip() in landed)
    stats = {"hit": len(hit_ids), "unused": unused, "josa": bad_josa,
             "tokens": bad_tok, "lang": bad_lang, "same": same,
             "rewrite": rewritten, "applied": applied, "ids": hit_ids}

    if bad_tok or bad_josa or bad_lang:
        print("拒绝落盘：%d 条 token 与原文不齐、%d 条占位符后接助词、"
              "%d 条映射值不是目标文字。" % (len(bad_tok), len(bad_josa),
                                          len(bad_lang)))
        for hid in bad_tok[:5]:
            print("  token  %s  %s" % (hid, doc.get(hid, "")[:60]))
        for hid, val in bad_josa[:5]:
            print("  助词   %s  %s" % (hid, val[:60]))
        for hid, val in bad_lang[:5]:
            print("  非目标文字 %s  %s" % (hid, val[:60]))
        print("改完映射后重跑；本次一个字节都没写。")
        return stats

    if hit_ids and not dry_run:
        toml_io.write_doc_atomic(path, doc, order, header)
    return stats


def cmd_apply(args):
    field = args.lang or target_field()
    mapping = load_map(args.map)
    was = set(pending_ids(entries(load_toml()), field))
    stats = apply_map(field, mapping, dry_run=args.dry_run)
    if stats["tokens"] or stats["josa"] or stats["lang"]:
        return 1
    tail = "（--dry-run，未写盘）" if args.dry_run else ""
    print("[%s] 映射 %d 条，写入 %d 条%s，其中修正旧译文 %d 条，已是当前值 %d 条。"
          % (field, len(mapping), stats["hit"], tail, stats["rewrite"],
             stats["same"]))
    if stats["applied"]:
        print("     另有 %d 条已落过盘（值已存在，未重复计）。" % stats["applied"])
    if not stats["hit"] and not stats["same"] and not args.dry_run:
        print("     命中 0 条：映射要么已应用过（幂等），要么源串对不上。")
    for key in stats["unused"][:10]:
        print("  未对上：%s" % key[:80])
    if len(stats["unused"]) > 10:
        print("  ……另有 %d 条，完整清单见映射文件。" % (len(stats["unused"]) - 10))
    if not args.dry_run and stats["hit"]:
        bad = reconcile(field, was, stats)
        if bad:
            return 1
    return 0


def reconcile(field, was, stats):
    """写完之后对账：待译条数应当正好减少「本次写进去的、原本待译的」那些。

    防的是两类静默失败：写盘只落了一半、或同源串撞车导致另一条 id 没写上
    （映射按源串作键时，撞车的两条只能写进一条）。
    """
    now = set(pending_ids(entries(load_toml()), field))
    expect_ids = [h for h in stats["ids"] if h in was]
    lost = was - now
    if len(lost) == len(expect_ids):
        print("     对账：待译 %d → %d（-%d）。" % (len(was), len(now), len(lost)))
        return 0
    print("     对账不符：应减少 %d 条待译，实际减少 %d 条。"
          % (len(expect_ids), len(lost)))
    stuck = [h for h in expect_ids if h in now]
    for hid in stuck[:10]:
        print("  仍待译 %s" % hid)
    if len(stuck) > 10:
        print("  ……另有 %d 条。" % (len(stuck) - 10))
    print("     多半是映射里同源串撞车：两条 id 共用一句英文，只能写进一条。"
          "改用 id 作键 {\"0x...\": \"译文\"} 再跑一次。")
    return 1


# ── 导出批次清单 ────────────────────────────────────────────

#: `--band` 的可取值 → BANDS 的下标区间。名字取代 `len(...) > 80` 这类内联式。
BAND_KEYS = {
    "short": (0, 12), "12": (0, 12),
    "24": (13, 24),
    "40": (25, 40),
    "80": (41, 80),
    "long": (81, None), "all": None,
}


def skeleton(text):
    """把占位符/标签抹成 § 后的句子骨架。

    `%@1$` 之类只差变量的条目、只差一个国家名的公告，骨架相同 —— 这就是
    「一条模板一次翻完、按变量回填」的信号。逐字相同的比对抓不到它们。
    """
    text = STRUCT_RX.sub("\u00a7", TAG_RX.sub("\u00a7", text or ""))
    return re.sub(r"\u00a7+", "\u00a7", text).strip()


def dump_lines(es, field, band, limit, by_group=False):
    """把待译条目渲染成批次清单的行（首行是注释头的第 1 行）。

    纯函数，不碰文件：`cmd_dump` 只负责读数据与写盘，单测直接喂合成条目。
    """
    pend = pending_of(es, field)

    def key_of(e):
        return content_of(e.get(field, "")).strip()

    groups = {}
    skels = {}
    for e in pend:
        groups.setdefault(key_of(e), []).append(e["id"])
        skels.setdefault(skeleton(key_of(e)), []).append(e["id"])

    in_band = [e for e in pend
               if band is None or band_of(content_of(e.get(field, ""))) == band]
    if by_group:
        # 每个骨架只留第一条：先翻一版代表句，再按变量替换回填
        seen = set()
        keep = []
        for e in in_band:
            sk = skeleton(key_of(e))
            if sk in seen:
                continue
            seen.add(sk)
            keep.append(e)
        in_band = keep
    rows = in_band[:limit] if limit > 0 else in_band

    lines = ["# 待译批次：%s  共 %d 条（待译 %d 条，该档 %d 条）%s"
             % (band_label(*band) if band else "全部", len(rows), len(pend),
                len(in_band), "  按骨架分组" if by_group else ""),
             "# 制表符分隔：id / 可见字数 / 英文原文（换行写作 \\n）",
             "# 行末 dup:N = 与另外几条共用同一句英文；需不同译法时用 id 作键"
             "：{\"0x...\": \"译文\"}；grp:N = 与另外几条只差占位符/标签，"
             "可照同一模板改词填空"]
    for e in rows:
        text = (e.get(field, "") or "").replace("\n", "\\n")
        line = "%s\t%d\t%s" % (e["id"], len(content_of(e.get(field, ""))), text)
        mates = [h for h in groups.get(key_of(e), []) if h != e["id"]]
        if mates:
            line += "\tdup:%d %s" % (len(mates) + 1, ",".join(mates))
        same = [h for h in skels.get(skeleton(key_of(e)), []) if h != e["id"]]
        if same:
            line += "\tgrp:%d %s" % (len(same) + 1, ",".join(same))
        lines.append(line)
    return lines


def near_pairs(es, field, base_lang=BASE_LANG, min_ratio=0.90, min_len=40):
    """相似度 ≥ min_ratio 的条目对：(ratio, id_a, id_b, 英文a, 英文b)。

    只比长度够长的句子，且只在待译集合里比 —— 已译完的批次里这种「只差一个
    词」的成对条目（四国公告、七档城镇状态）在翻译时最容易各写一版、术语漂移，
    导出时就摆出来比事后 audit 省事。
    """
    import difflib
    pend = pending_of(es, field)
    rows = [(e["id"], e.get(base_lang) or e.get(field, "") or "") for e in pend]
    rows = [(i, t) for i, t in rows if len(t) >= min_len]
    out = []
    for i in range(len(rows)):
        for j in range(i + 1, min(len(rows), i + 30)):
            ra, rb = rows[i][1], rows[j][1]
            ratio = difflib.SequenceMatcher(None, ra, rb).ratio()
            if ratio >= min_ratio:
                out.append((ratio, rows[i][0], rows[j][0], ra, rb))
    out.sort(reverse=True)
    return out


def cmd_dump(args):
    """导出待译批次：id / 可见字数 / 英文原文，并把同源串撞车标出来。

    以前每批都是手写一段 here-string：改 sys.path、`pending_of`、`len>80`、
    写制表符、`\\n` 转义。八批下来这段重复了八次，条件还漂过（>80 与 ≥81），
    所以收成一条命令。撞车列是为了让「按源串作键只能写一条」这件事在导出时
    就看得见，而不是等 apply 对账才发现。
    """
    if args.band not in BAND_KEYS:
        raise SystemExit("--band 只认 %s。" % "、".join(BAND_KEYS))
    field = args.lang or target_field()
    lines = dump_lines(entries(load_toml()), field,
                       BAND_KEYS[args.band], args.limit, args.by_group)
    body = "\n".join(lines) + "\n"
    if args.out:
        parent = os.path.dirname(os.path.abspath(args.out))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        print("[%s] 导出 %d 条 → %s" % (field, len(lines) - 3, args.out))
    else:
        sys.stdout.write(body)
    return 0


# ── 源缺失自查 ────────────────────────────────────────────────


def cmd_near(args):
    """近重复自查：待译里相似度 ≥ 阈值的条目对，并排打印差异片段。

    用途有两层：一是「只差一个词」的条目（四国公告、七档城镇状态）照着同一
    模板去翻，别各写一版；二是原文自相矛盾时会自己浮出来 —— 批次十一那条
    「替你夺城的国家也必须军力虚弱」对「必须军力强大」正是这一类。
    """
    import difflib
    field = args.lang or target_field()
    es = entries(load_toml())
    pairs = near_pairs(es, field, min_ratio=args.min)
    print("[%s] 待译 %d 条里相似度 ≥ %.2f 的成对条目：%d 对"
          % (field, len(pending_of(es, field)), args.min, len(pairs)))
    for ratio, a, b, ra, rb in pairs[:args.limit]:
        print("%.2f  %s  %s" % (ratio, a, b))
        sm = difflib.SequenceMatcher(None, ra, rb)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            left = ra[max(0, i1 - 12):i2 + 12].replace("\n", "\\n")
            right = rb[max(0, j1 - 12):j2 + 12].replace("\n", "\\n")
            print("      %-7s %s" % (tag, left))
            print("      %-7s %s" % ("", right))
    if len(pairs) > args.limit:
        print("  ……另有 %d 对。" % (len(pairs) - args.limit))
    return 0


def cmd_overrides(args):
    """微调版原文自查。有问题返回 1，供 check 收口。"""
    missing, bad_tok, noop = check_overrides(OVERRIDES_CODE)
    print("[%s] 微调版 overrides：%d 条（缺 id %d、token 不一致 %d、白改 %d）"
          % (BASE_LANG, len(load_overrides(OVERRIDES_CODE)), len(missing),
             len(bad_tok), len(noop)))
    return 1 if (missing or bad_tok or noop) else 0


def cmd_gaps(args):
    """英文原值是令牌、译文却是实文的条目。只报告，不改，不进 check 的判定。"""
    field = args.lang or target_field()
    doc = load_toml()
    es = entries(doc)
    rows = []
    for e in es:
        en = e.get(BASE_LANG, "")
        if not TOKEN_SRC_RX.match(en.strip()):
            continue
        val = content_of(e.get(field, "")).strip()
        if val and val != en.strip():
            rows.append((e["id"], en.strip(), val))
    print("[%s] 源缺失 %d 条（英文原值即令牌，译文有实文）" % (field, len(rows)))
    for hid, en, val in rows[:20]:
        print("  %s  %-36s  %s" % (hid, en[:36], val[:48]))
    if len(rows) > 20:
        print("  ……另有 %d 条。" % (len(rows) - 20))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="看进度")
    p.add_argument("--lang", default="", help="译文语言代码，默认列出全部可编辑语言")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("apply", help="把 {英文原串: 译文} 映射落进译文文件")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.add_argument("--map", required=True, help="映射 JSON 文件")
    p.add_argument("--dry-run", action="store_true", help="只报告，不写盘")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("dump", help="导出待译批次清单（id/字数/原文，标撞车与同骨架）")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.add_argument("--band", default="long",
                   help="长度档：short/24/40/80/long/all，默认 long（81+）")
    p.add_argument("--limit", type=int, default=40, help="最多导几条，0 = 不限")
    p.add_argument("--by-group", action="store_true",
                   help="按骨架去重：只留每组一条代表句")
    p.add_argument("--out", default="", help="写到这个文件；不给就打到 stdout")
    p.set_defaults(fn=cmd_dump)

    p = sub.add_parser("near", help="近重复自查：相似度 ≥ 阈值的待译条目对")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.add_argument("--min", type=float, default=0.90, help="相似度阈值，默认 0.90")
    p.add_argument("--limit", type=int, default=20, help="最多列几对")
    p.set_defaults(fn=cmd_near)

    p = sub.add_parser("overrides", help="微调版原文自查：id 存在、token 一致")
    p.set_defaults(fn=cmd_overrides)

    p = sub.add_parser("gaps", help="源缺失自查：英文原值是令牌、译文有实文")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.set_defaults(fn=cmd_gaps)

    args = ap.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()