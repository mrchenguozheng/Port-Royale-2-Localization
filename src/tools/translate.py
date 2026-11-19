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
from shared.core.validate import (PH_RE, is_identifier, tag_literals,  # noqa: E402
                                 tag_profile, token_counts, tokens)
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
               if i in raw and token_counts(t) != token_counts(raw[i])]
    noop = [i for i, t in ov.items() if i in raw and t.strip() == str(raw[i]).strip()]
    for i in bad_tok:
        print("  token  %s  原版 %s | 微调 %s"
              % (i, dict(token_counts(raw[i])), dict(token_counts(ov[i]))))
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
#: 汉字块。日文里「資産」「倉庫」「不明」这类界面标签本来就只写汉字不带假名，
#: 光看假名会把它们全判成未译（实测 ja 560 条待译里 530 条是这种）。
CJK_RX = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]", re.UNICODE)

#: 英文原值像个令牌：全大写、无空格、没有小写字母。`IDM_CONTEST_01_2004_*`
#: 这一类在英文表里就是键名本身，中文表却是实文 —— `gaps` 专门抓这个。
TOKEN_SRC_RX = re.compile(r"^[A-Z][A-Z0-9_]{8,}$")

#: 待译条目的长度分档，与批次划分口径一致。
BANDS = ((0, 12), (13, 24), (25, 40), (41, 80), (81, None))


def content_of(value):
    """抹掉标签、方括号键与占位符后剩下的人话。"""
    return STRUCT_RX.sub("", TAG_RX.sub("", value or ""))


def is_translated(value, lang, base=None, script=None, avoid=None):
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
    `avoid` 是「不该跟它一样」的参照值（日文传中文值）：日文的界面标签常只写
    汉字不带假名（`資産`、`倉庫`、`不明`），只认假名会把这些判成未译；所以汉字
    也算日文，但要求既不等于英文原文、也不等于中文译文 —— 整句照抄中文仍然
    判待译。
    """
    vis = content_of(value)
    if script is not None:
        if script.search(vis):
            return True
        if not LETTER_RX.search(vis):
            return True
        if lang == "ja" and CJK_RX.search(vis):
            if vis.strip() == content_of(base).strip():
                return False
            # 短标签（`人口`、`武器`、`注意`）中日同形本来就正常；
            # 只有整句（>12 字）与中文一模一样才判成照抄。
            if (avoid is not None and len(vis.strip()) > 12
                    and vis.strip() == content_of(avoid).strip()):
                return False
            return True
        return False
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
    avoid = "zh" if field == "ja" else None
    return [e["id"] for e in es
            if e["id"] not in keep
            and not is_translated(e.get(field, ""), field,
                                  base=e.get(BASE_LANG, ""), script=script,
                                  avoid=e.get(avoid, "") if avoid else None)]


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
    translatable = total - len(keep)
    done = translatable - len(pend)
    print("[%s] 共 %d 条：已译 %d / 可译 %d（%.1f%%），待译 %d 条%s"
          % (field, total, done, translatable,
             100.0 * done / max(1, translatable), len(pend),
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
    """占位符-助词检查的四条正则，取 `text_lint` 的唯一一份实现。

    取不到就返回 (None, None, None, None)：检查缺失不该让落盘失败，但会打印
    提示 —— 宁可少一道门，也不要偷偷改成另一份规则。

    返回 `(裸助词, 并列形, 反序并列形, 图形标签后裸助词)`。
    """
    path = os.path.join(HERE, "analysis")
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import text_lint
        return (text_lint.PH_BARE, text_lint.PH_PAIR,
                text_lint.PH_PAIR_BAD, text_lint.PH_BARE_G)
    except Exception as exc:                    # noqa: BLE001
        print("提示：取不到 text_lint 的占位符-助词规则（%s），跳过这道检查。" % exc)
        return None, None, None, None


def unit_violations(lang, hid, val):
    """量词检查（只有 ko 有）：返回 text_lint 的 E 级命中，取不到就空。

    规则本身只有一份（`text_lint.ko_unit_checks`），这里只借过来当落盘前的门 ——
    抄一份到 apply 里，两处判据早晚各算各的。
    """
    if lang != "ko":
        return []
    path = os.path.join(HERE, "analysis")
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import text_lint
        return text_lint.ko_unit_checks({hid: val})
    except Exception:                          # noqa: BLE001
        return []


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
    """占位符与原文比，缺了或多了都算不合格（顺序允许调）。

    比的是**个数**：原文两处 `@G$Goods$`、译文只留一处，也必须报出来。
    """
    return token_counts(old) != token_counts(new)


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
    bad_josa, bad_tok, bad_lang, bad_unit, bad_tag = [], [], [], [], []
    bad_pair = []
    script = lang_rules.script_re(lang)
    ph_bare, _ph_pair, ph_pair_bad, ph_bare_g = josa_rules()
    #: 有意不译的条目：它们**正确**的值就是英文原串，写回去不算「抄错行」。
    keep_ids = set(keep_as_is(lang))
    #: 英文基准：占位符个数以它为准。拿现值比是没用的 —— 现值本身可能就是
    #: 少了一个 @G$Goods$ 的旧译文，那样只会「错得一致」。
    try:
        en_by_id = {e["id"]: e.get(BASE_LANG, "") for e in entries(load_toml())}
    except (OSError, SystemExit):
        en_by_id = {}                      # 单测的临时 src 里没有 orig/，按现值比

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
        # 按 id 重放同一份映射：值没变就是「已是当前值」，不是「修正」。
        # 以前一律算 hit + rewrite，重放会报「修正 40 条 / 已是当前值 0 条」，
        # 幂等核对时看着像全都改过。
        if by_id and key == new.strip():
            same += 1
            used.add(hid)
            continue
        if script is not None and script.search(content_of(cur)):
            rewritten += 1                 # 现值是目标文字：这次是修正
        lead = cur[:len(cur) - len(cur.lstrip())]
        trail = cur[len(cur.rstrip()):]
        val = lead + new.strip() + trail
        # 占位符按**个数**比英文（语序不管）：原文两处 @G$Goods$、译文只留一处
        # 也必须拦下，否则界面上会少印一个货物名。
        base = en_by_id.get(hid)
        # 版本差：英文基准里是 `IDM_…_TEXT` 这样的资源标识或 `+++EMPTY+++`，
        # 从来没有正文。这类条目拿英文当模板比必然全错（正文来自零售版），
        # 跳过 token 与标签两道门，余下的助词/量词/文字检查照旧。
        if base is not None and (is_identifier(base) or base.strip() == "+++EMPTY+++"):
            base = None
            no_text_base = True
        else:
            no_text_base = False
        if base is not None:
            bad = token_counts(base) != token_counts(val)
        elif no_text_base:
            bad = False
        else:
            bad = token_diff(cur, val)
        if bad:
            bad_tok.append(hid)
            continue
        # 标签按字面比：`<n>` 少一个、`<f:fonts/…FHk.res>` 的字体名多一个字母，
        # 屏幕上就是丢分段、换字体。占位符另由 token_counts 管，这里只管 `<...>`。
        # 基准侧无正文时不比 —— 那边只有一个标识串，一个标签都没有。
        if not no_text_base:
            base_tags = tag_literals(base if base is not None else cur)
            if base_tags != tag_literals(val):
                want = set(base_tags) - set(tag_literals(val))
                got = set(tag_literals(val)) - set(base_tags)
                bad_tag.append((hid, "缺 %s 多 %s" % (
                    "、".join(sorted(want)) or "—",
                    "、".join(sorted(got)) or "—")))
                continue
        # 逐处判，不再「整条里只要有一处并列形就放过整条」：同一句里
        # `@T$TOWN$이(가)` 与 `@T$Town$으로` 并存时，后者仍是错的。
        if ph_bare is not None:
            for m in ph_bare.finditer(val):
                bad_josa.append((hid, m.group(0)))
            # 图形标签后的裸助词与占位符同类：`<g:…screen>을(를)` 合规，`…>을` 不合规。
            if ph_bare_g is not None:
                for m in ph_bare_g.finditer(val):
                    bad_josa.append((hid, m.group(0)))
            if bad_josa and bad_josa[-1][0] == hid:
                continue
        # 并列形次序：`과(와)`／`는(은)`／`로(으로)` 语义没错，但与全库 `와(과)`／
        # `은(는)`／`으로(로)` 不一致。写成反序就是排版错，落盘前改掉。
        if ph_pair_bad is not None:
            for m in ph_pair_bad.finditer(val):
                bad_pair.append((hid, m.group(0)))
            if bad_pair and bad_pair[-1][0] == hid:
                continue
        # 量词：`%1 배`（缺 척）、`5척의 병사`（搭配错）。以前只在 text_lint
        # 阶段查，那时已经写盘；放在这里就是落盘前的门。
        for _k, why, detail in unit_violations(lang, hid, val):
            bad_unit.append((hid, "%s %s" % (why, detail)))
        if bad_unit and bad_unit[-1][0] == hid:
            continue
        # 映射值必须是目标文字：韩语映射里写回英文，多半是抄错了行。
        # 例外是名单内条目 —— 它们的正确值本来就是英文，用来把译错的名字改回去。
        # 日文的汉字标签（`資産`、`名前`）本身不带假名，走 `is_translated` 同一判据。
        vis = content_of(val)
        if (script is not None and hid not in keep_ids
                and LETTER_RX.search(vis)
                and not (script.search(vis) or (lang == "ja" and CJK_RX.search(vis)))):
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
             "unit": bad_unit, "tag": bad_tag, "pair": bad_pair,
             "rewrite": rewritten, "applied": applied, "ids": hit_ids}

    if bad_tok or bad_josa or bad_lang or bad_unit or bad_tag or bad_pair:
        print("拒绝落盘：%d 条 token 与原文不齐、%d 条占位符／标签后接助词、"
              "%d 条量词不对、%d 条标签与原文不一致、%d 条并列助词次序反了、"
              "%d 条映射值不是目标文字。"
              % (len(bad_tok), len(bad_josa), len(bad_unit), len(bad_tag),
                 len(bad_pair), len(bad_lang)))
        # 全列，不再只印前 5 条：一批 40 条里往往一次就有七八条同类问题，
        # 只印 5 条就得改—重跑—再改，白跑两三轮。
        for hid in bad_tok:
            print("  token  %s  %s" % (hid, doc.get(hid, "")[:60]))
        for hid, tok in bad_josa:
            print("  助词   %s  %s" % (hid, tok))
        for hid, tok in bad_pair:
            print("  次序   %s  %s" % (hid, tok))
        for hid, detail in bad_unit:
            print("  量词   %s  %s" % (hid, detail))
        for hid, detail in bad_tag:
            print("  标签   %s  %s" % (hid, detail))
        for hid, val in bad_lang:
            print("  非目标文字 %s  %s" % (hid, val[:60]))
        if bad_josa:
            # 只报片段的话，每条都得重新想一遍改法。三条路都给出来，选最省事的：
            # 量词后置（`…만큼을`）、换作定语、整句换述，实在不行才写并列形。
            print("     助词改法：① 量词后置（`@g$Reward$` → `@g$Reward$만큼을`）"
                  " ② 换句式（`…에 이르렀습니다` / `…, 그 값을`）"
                  " ③ 写并列形（`은(는)`／`을(를)`／`이(가)`／`와(과)`／`으로(로)`，只此一套次序）")
        print("改完映射后重跑；本次一个字节都没写。")
        return stats

    if hit_ids and not dry_run:
        toml_io.write_doc_atomic(path, doc, order, header)
    return stats


def cmd_apply(args):
    field = args.lang or target_field()
    mapping = load_map(args.map)
    only = [h.strip() for h in getattr(args, "ids", "").split(",") if h.strip()]
    if only:
        # 一个映射里混了两批时，靠 --ids 只落第一批：否则两份改动落在同一次
        # 写盘里，git 那边就是一个 hunk，提交信息也只能并成一条。
        want = {h.lower() for h in only}
        rows = entries(load_toml())
        by_en = {(e.get(BASE_LANG) or "").strip(): e["id"] for e in rows}
        by_id = {e["id"].lower(): e["id"] for e in rows}
        picked = {}
        skipped = []
        for k, v in mapping.items():
            hid = (by_id.get(k.lower()) if k.lower().startswith("0x")
                   else by_en.get(k.strip()))
            if hid and hid.lower() in want:
                picked[hid] = v                  # 统一改按 id 键送下去
            else:
                skipped.append(k)
        print("[%s] --ids 命中 %d 条，跳过 %d 条（不在清单里）。"
              % (field, len(picked), len(skipped)))
        mapping = picked
    was = set(pending_ids(entries(load_toml()), field))
    stats = apply_map(field, mapping, dry_run=args.dry_run)
    if (stats["tokens"] or stats["josa"] or stats["lang"]
            or stats["unit"] or stats["tag"] or stats["pair"]):
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


def dump_lines(es, field, band, limit, by_group=False, order=None, ids=None,
               ref_langs=()):
    """把待译条目渲染成批次清单的行（首行是注释头的第 1 行）。

    纯函数，不碰文件：`cmd_dump` 只负责读数据与写盘，单测直接喂合成条目。

    `order="risk"`（默认）先按结构风险分层：无占位符无标签 → 有占位符 →
    带标签，同层按字数。剩下的活全是长文时，纯字数排序已经没有区分度，
    而「纯文字」那批抄不错的概率最高、「带标签」那批最容易抄错。

    `order="short"` 按可见字数从短到长取，短档先清。
    `order="long"` 从长到短。`order="table"`（或 None）保持表序。

    `ids` 给了就只取这几条（无视 band / limit）：同模板换词的那一族（桶模板
    五条、四国公告六条）按字数散在整个长文队列里，一次只碰上一两条，靠手抄
    id 单独成批才收拾得干净。

    `ref_langs` 在英文原文后面追加参考列（`zh=…`、`ja=…`）：韩语剩下的长文
    在其余六语里都有现成译文，术语与句式照着最省事，也最不容易漂。
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
    if ids:
        want = {h.lower() for h in ids}
        in_band = [e for e in pend if e["id"].lower() in want]
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
    if order == "risk":
        # 风险分层：无占位符无标签 → 只有占位符 → 带标签；同层再按字数。
        def risk_key(e):
            t = e.get(BASE_LANG) or e.get(field) or ""   # 单测里没有英文基准列
            has_ph = bool(PH_RE.search(t))
            has_tag = "<" in t
            return (2 if has_tag else (1 if has_ph else 0),
                    len(content_of(e.get(field, ""))))
        in_band = sorted(in_band, key=risk_key)
    elif order == "short":
        in_band = sorted(in_band, key=lambda e: len(content_of(e.get(field, ""))))
    elif order == "long":
        in_band = sorted(in_band, key=lambda e: -len(content_of(e.get(field, ""))))
    rows = in_band[:limit] if (limit > 0 and not ids) else in_band

    # 队列全貌：只报当前档的话，「还剩多少、别的档排在哪」看不见
    queue = {}
    for e in pend:
        lab = band_label(*band_of(content_of(e.get(field, ""))))
        queue[lab] = queue.get(lab, 0) + 1
    qsum = "  ".join("%s:%d" % (band_label(*b), queue[band_label(*b)])
                     for b in BANDS if band_label(*b) in queue)
    head = ("# 手选批次：%d 条（待译 %d 条）" % (len(rows), len(pend)) if ids
            else "# 待译批次：%s  共 %d 条（待译 %d 条，该档 %d 条）%s"
                 % (band_label(*band) if band else "全部", len(rows), len(pend),
                    len(in_band), "  按骨架分组" if by_group else ""))
    lines = [head,
             "# 全队列 %s" % qsum,
             "# 制表符分隔：id / 可见字数 / 英文原文（换行写作 \\n）%s"
             % ("".join(" / %s=%s" % (r, r) for r in ref_langs)),
             "# 行末 dup:N = 与另外几条共用同一句英文；需不同译法时用 id 作键"
             "：{\"0x...\": \"译文\"}；grp:N = 与另外几条只差占位符/标签，"
             "可照同一模板改词填空"]
    for e in rows:
        text = (e.get(field, "") or "").replace("\n", "\\n")
        line = "%s\t%d\t%s" % (e["id"], len(content_of(e.get(field, ""))), text)
        for r in ref_langs:
            line += "\t%s=%s" % (r, (e.get(r, "") or "").replace("\n", "\\n"))
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
    order = getattr(args, "order", None)
    ids = [h.strip() for h in getattr(args, "ids", "").split(",") if h.strip()]
    refs = [r.strip() for r in getattr(args, "ref", "").split(",") if r.strip()]
    lines = dump_lines(entries(load_toml()), field,
                       BAND_KEYS[args.band], args.limit, args.by_group, order,
                       ids or None, refs)
    body = "\n".join(lines) + "\n"
    n_rows = sum(1 for ln in lines if not ln.startswith("#"))
    if args.out:
        parent = os.path.dirname(os.path.abspath(args.out))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        print("[%s] 导出 %d 条 → %s" % (field, n_rows, args.out))
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


def cmd_terms(args):
    """术语落词检查的全量版：长文也算，只报告不判定。

    `text_lint` 那边只在 ≤24 字的短标签上判（长句里同一个词是行文的一部分，
    强求会报一堆没人处理的 W）。但长文里术语漂掉也确实发生过 —— 用这个命令
    按词列出全量命中，人工挑要改的那些。
    """
    field = args.lang or target_field()
    sys.path.insert(0, os.path.join(HERE, "analysis"))
    import text_lint as L                      # noqa: E402  惰性：避免循环依赖

    enforce = None if args.all_keys else L._enforce_keys(field)
    keep = keep_as_is(field)
    script = lang_rules.script_re(field)
    rows = entries(load_toml())
    min_len = args.min_len
    hits = []
    for key, word, want in L.load_terms(field):
        if enforce is not None and key not in enforce:
            continue
        rx = re.compile(r"\b%s\b" % re.escape(word), re.I)
        ids = []
        for e in rows:
            if e["id"] in keep:
                continue
            en = (e.get(BASE_LANG) or "")
            val = e.get(field) or ""
            if not rx.search(en) or want in val:
                continue
            if len(content_of(val)) < min_len:
                continue
            if not is_translated(val, field, base=en, script=script):
                continue                      # 待译条目还是英文，不算漂
            ids.append(e["id"])
        if ids:
            hits.append((key, word, want, ids))
    total = sum(len(h[3]) for h in hits)
    print("[%s] 术语未落词 %d 条（%d 个词，可见 ≥%d 字）"
          % (field, total, len(hits), min_len))
    for key, word, want, ids in sorted(hits, key=lambda h: -len(h[3])):
        print("  %-22s %-26s → 「%s」  %d 条" % (key, word, want, len(ids)))
        for hid in ids[:6]:
            print("      %s" % hid)
        if len(ids) > 6:
            print("      ……另有 %d 条。" % (len(ids) - 6))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="看进度")
    p.add_argument("--lang", default="", help="译文语言代码，默认列出全部可编辑语言")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("apply", help="把 {英文原串: 译文} 映射落进译文文件")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.add_argument("--map", required=True, help="映射 JSON 文件")
    p.add_argument("--ids", default="",
                   help="只落这几条（逗号分隔 id）：一个映射里混了两批时按批提交")
    p.add_argument("--dry-run", action="store_true", help="只报告，不写盘")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("dump", help="导出待译批次清单（id/字数/原文，标撞车与同骨架）")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.add_argument("--band", default="long",
                   help="长度档：short/24/40/80/long/all，默认 long（81+）")
    p.add_argument("--limit", type=int, default=40, help="最多导几条，0 = 不限")
    p.add_argument("--by-group", action="store_true",
                   help="按骨架去重：只留每组一条代表句")
    p.add_argument("--order", choices=("risk", "short", "long", "table"),
                   default="risk",
                   help="risk=先清纯文字（无占位符无标签）再清带标签（默认）；"
                        "short=可见字数从短到长；long=从长到短；table=按表序")
    p.add_argument("--ids", default="",
                   help="只导这几条（逗号分隔 id），无视 --band/--limit；"
                        "同模板换词的一族用这个单独成批")
    p.add_argument("--ref", default="",
                   help="追加参考列，逗号分隔语言代码（如 zh,ja）："
                        "在英文原文后面每语多一列现成译文")
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

    p = sub.add_parser("terms", help="术语落词全量自查（长文也算，只报告）")
    p.add_argument("--lang", default="", help="译文语言代码，默认第一个可编辑语言")
    p.add_argument("--min-len", type=int, default=0,
                   help="只算可见字数 ≥N 的条目（默认 0 = 长短都算）")
    p.add_argument("--all-keys", action="store_true",
                   help="不看 enforce_<lang>.txt，术语表里的键全查")
    p.set_defaults(fn=cmd_terms)
    return ap


def main():
    args = build_parser().parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()