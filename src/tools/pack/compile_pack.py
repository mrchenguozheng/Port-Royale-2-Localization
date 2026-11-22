#!/usr/bin/env python
# coding: utf-8
r"""src/tools/pack/compile_pack.py — 把 src\translations\<语言>.toml 编译成引擎语言包

    python src/tools/pack/compile_pack.py                        # 编 zh（默认）
    python src/tools/pack/compile_pack.py --lang de --out <输出目录>

只做一件事：**占位符校验**。译文里的 %1 / @D$EndDate$ 必须与原文
一一对应，种类、数量、写法全都要对；顺序可以按中文语序调。

编译前先在内存里套一遍排版规则（`src/tools/text/engine_text.py`），并把结果
写到 build\preview\engine_text\<语言>.toml 供人查看。译文层（src\translations\）是
唯一手改层，引擎文本是构建产物，不进仓库。

src/orig/ 下的 en / fr 是校对译文的依据，但不做防篡改校验：
合并层（translate.load_toml）本身就是从这两个文件读出 en / fr 的，
拿它们校验自己永远相等，报不出任何东西。

【不做的事】不检查行宽。控件到底多宽**没有在游戏里实测过**，
拿字体算出来的像素只会误导人（这条结论见 docs/翻译局限.md）。
中文这类不用空格分词的语言，引擎会把一长串汉字当成一个超宽单词，
整条**丢弃（不显示）**，所以过宽的译文必须人工在游戏里验收。
"""

import argparse
import hashlib
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
SRC = os.path.dirname(TOOLS)                              # 仓库的 src\
ROOT = os.path.dirname(SRC)                              # 仓库根
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
DEFAULT_OUT = os.path.join(ROOT, "build", "runtime", "PR2Localization", "packs")
#: 非 primary 基线的语言包落点。**不放进 packs\\**：运行时按 packs\\<语言>.txt
#: 找活动语言，多出来的同级文件会让语言列表出现重名项，子目录也会被部署脚本
#: 一起拷进游戏目录。放仓库 build\\variants\\<版本id>\\ 下，按目标安装手动取用。
DEFAULT_VARIANT_OUT = os.path.join(ROOT, "build", "variants")

# 占位符与「占位文本」的判定只有一份，在 shared\core\validate.py。
from shared.core.validate import (  # noqa: E402
    has_bare_pipe, is_identifier, is_placeholder, tokens)

#: 只读参考语言：英文 / 法文原文 + 四个零售包对照。**不参与编辑，也不生成语言包**。
#: 实际名单以 translate.REFERENCE_LANGS 为准（这里是 import 不到时的兜底常量，
#: 文件名带来源与版本：en.gog_1.1.2.3 / fr.gog_1.1.2.42 / *.retail-1.0.0）。
REFERENCE_LANGS = ("en.gog_1.1.2.3", "fr.gog_1.1.2.42",
                   "de.retail-1.0.0", "es.retail-1.0.0",
                   "pl.retail-1.0.0", "ru.retail-1.0.0")

# ---------------------------------------------------------------- 占位符
#
# 规则（@前缀$变量名$、%N、紧邻占位符的坑）都在 shared\core\validate.py。
# 本模块以前另有一份实现，现在只留一个入口，免得编译期与编辑器的判定分叉。
# %02 与 %2 按字面区分：0 是 printf 的补零宽度，"Autosave %02u" 写成
# "%2u" 出来会少一位（全量里只有 1 条 0x33c2c533 用到 %02u）。


#: 英文原文本身是开发残留标识符（`IDM_CONTEST_01_2004_LOG_06_TEXT` 这类）。
#: 这类键的英文侧从来不是句子，占位符比对没有基准：德语零售版里
#: `LOG_06_TEXT` 带 `@g$PirateGold$`，中文照译就会判成「多了占位符」。
#: 判定放在 shared\core\validate.py（text_lint 用的是同一份）。


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
    if is_identifier(en):
        return True          # 英文是标识符，没有可比对的基准
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
    """读取 src/packs/<语言>.toml 的 alias/min_runtime/version；这是写进语言包的元数据。

    ``version`` 可选：开发构建不写，发行时由 ``--version`` 注入（出包版本号）。
    """
    p = os.path.join(SRC, "packs", lang + ".toml")
    if not os.path.isfile(p):
        return {}
    try:
        doc = tomllib.load(open(p, "rb"))
    except Exception:
        return {}
    return {k: str(doc[k]) for k in ("alias", "min_runtime", "version")
            if doc.get(k)}


#: 写进 ``# pack-meta version=`` 的值：vMAJOR.MINOR.PATCH[-prerelease]，不带前缀 v。
PACK_VERSION_RE = re.compile(r"^v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?)$")


def normalize_pack_version(value):
    """把发行版本号归一成 pack 头里的写法（去掉 ``v``）；不合规返回空串。"""
    if not value:
        return ""
    match = PACK_VERSION_RE.match(str(value).strip())
    return match.group(1) if match else ""


LEAD_TAGS = re.compile(r"(?:<[^>]*>)*")


def mark_map(keys):
    """给每个 id 造一个尽量短且唯一的标记，形如 [D6E4]。

    逐条取“能区分自己”的最短尾数：多数是 4~6 位，只有重号的那两条才用到 8 位。
    4 位在 3548 条上会撞（3465/3548），所以不能统一按 4 位写死。
    """
    raw = [k.replace("0x", "").upper() for k in keys]
    out = {}
    for k in keys:
        r = k.replace("0x", "").upper()
        for n in range(4, 9):
            tail = r[-n:]
            if sum(1 for x in raw if x[-n:] == tail) == 1:
                out[k] = "[%s] " % tail
                break
    if len(out) != len(set(keys)):
        raise SystemExit("标记无法唯一化")
    return out


def add_mark(txt, mark):
    """标记插在行首标签之后，避免破坏 <ts:>/<f:fonts/> 的解析。"""
    m = LEAD_TAGS.match(txt)
    return txt[:m.end()] + mark + txt[m.end():]


def _version_bases(baseline):
    """选要出包的版本基线：'all' = 全部；否则按 id 选一个。

    基线清单与定向差在 src\\data\\versions\\ 下（versions.py 负责读与核对）。
    """
    from text import versions as V
    bases = V.load_baselines()
    if baseline in ("", "all"):
        return bases
    want = [b for b in bases if b["id"] == baseline]
    if not want:
        raise SystemExit("没有这个版本基线：%s（可选：all、%s）"
                         % (baseline, "、".join(b["id"] for b in bases)))
    return want


def _is_resource_id(s):
    """原文是不是「开发残留的资源标识」而不是界面文本。

    `validate.is_identifier` 只按形状判（`^[A-Z][A-Z0-9_]{7,}$`），会把
    `ATTENTION` 这种全大写单字界面词（fr 版 `0x274e9455`）也当标识 —— 实测
    三份原文表里，真正的资源标识 15 条全部带下划线，唯一无下划线的命中的就是
    `ATTENTION`。所以这里再加一条：必须含下划线。
    """
    return bool(s) and "_" in s and is_identifier(s)


def pack_digest(body_lines):
    """正文行的内容指纹：sha256 前 12 位（小写十六进制）。

    **只算正文**，不把 ``# pack-meta`` 头算进去 —— 否则版本号一变摘要就跟着
    变，同一份译文在 v1.0.0 与 v1.1.0 里会报出两个不同的「内容」。
    指纹用来回答「两份包是不是逐字相同」，回答不了「改了哪几条」。
    """
    data = "".join(body_lines).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:12]


def scope_token(baseline_id):
    """写进 ``# pack-meta scope=`` 的键集标记。

    GOG / Steam 合包用的是并集键集（``union(...)``），逐版对照是单个基线 id。
    这个值只用于排错：正文一样但键集不同（并集比单版多出别版独有的键），
    摘要本来就该不一样。
    """
    if baseline_id.startswith("union"):
        return "union"
    token = re.sub(r"[^A-Za-z0-9._-]", "", baseline_id)
    return token or "custom"


def _pack_head(lang, pack_version, scope, body_lines, entries, untranslated):
    """pack 头：alias / min_runtime / version / 统计两行 / scope / digest。

    ``entries`` 是写进包里的数据行总数，``untranslated`` 只数**占位未翻译**
    的条目 —— 原文本来就空的键（原版就是 ``+++EMPTY+++``）不算欠译，
    把它们算进去会让所有语言都显示成一堆待翻译。
    """
    lines = []
    meta = load_pack_meta(lang)
    if pack_version:
        # build() 入口已经归一过并把非法值挡在外面（return 2）；这里再归一一次，
        # 是为了让单独调用本函数时也不会写出 `version=v1.0.0` 这种双前缀。
        normalized = normalize_pack_version(pack_version)
        if normalized:
            meta["version"] = normalized
    for k in ("alias", "min_runtime", "version"):
        if meta.get(k):
            val = meta[k].replace("\n", " ").replace("\r", " ")
            lines.append("# pack-meta %s=%s\n" % (k, val))
    lines.append("# pack-meta entries=%d\n" % entries)
    lines.append("# pack-meta untranslated=%d\n" % untranslated)
    if scope:
        lines.append("# pack-meta scope=%s\n" % scope)
    lines.append("# pack-meta digest=%s\n" % pack_digest(body_lines))
    return lines, meta


def _pack_lines(lang, b, engine, by_hash, mk, marks, errors, warnings, fatal,
                pack_version="", scope=""):
    """按某份基线的键集出行（顺序 = 该版本原文表的顺序）。

    【并集与缺行】译文层是 `src\\translations\\<语言>.toml` 一套，键集覆盖基准版
    全部条目；个别版本独有的键（fr.gog_1.1.2.42 多出 42 条）在任何语版里都是
    `+++EMPTY+++`，译文层不为它们建行 —— 这里从原文表复制该值，既是「原文空」
    也是「不用翻」，不是漏译。原文非空却没有译文行，才是漏译，报错误。

    【pack 头】``alias`` / ``min_runtime`` 来自 src\\packs\\<语言>.toml；
    ``version`` 优先取调用方传进来的发行版本（``--version``），没有时用 toml 里的。
    另外写 ``entries`` / ``untranslated`` / ``scope`` / ``digest`` 四行：
    GUI 靠它们显示「简体中文 · v1.0.0」和「3590 条 · 未译 0 · 摘要 1a2b3c4d5e6f」。
    运行时只读 min_runtime，其余是给人看的。
    """
    from text import versions as V
    import translate as T
    body = []
    n = n_ph = n_empty = n_ident = 0

    for h in b["keys"]:
        orig = b["table"][h]
        orig_s = (orig or "").strip()
        # 原文空（目标版独有的 42 条，全是 +++EMPTY+++）：写回原文值，不用译文。
        if orig_s == V.EMPTY:
            body.append("%s = %s\n"
                        % (h.upper().replace("0X", "0x"), V.EMPTY))
            n_empty += 1
            continue
        # 原文本身是开发残留标识符（`IDM_CONTEST_01_2004_LOG_00_TEXT`）：
        # **原样保留**，不用译文覆盖。这一版里它本来就不是句子，玩家在原版
        # 英文里看到的也是这串标识；译文层就算写了正文，也不该凭空造出一段
        # 原文处没有的界面文本。要给出正文，得换到有正文的版本（见 versions）。
        if _is_resource_id(orig_s):
            body.append("%s = %s\n"
                        % (h.upper().replace("0X", "0x"), to_engine(orig_s)))
            n_ident += 1
            continue
        txt = engine.get(h)
        if not txt:
            errors.append("%s 缺译文：%s 里这条是正文（%r）"
                          % (h, b["id"], orig[:40]))
            continue
        s = by_hash.get(h, {})
        if h in KEEP_ORIGINAL:
            eng = s.get(T.BASE_LANG, "") or txt
            if txt != eng:
                warnings.append("%s 是必须原样保留的文本（%s），已改用英文原文"
                                % (h, KEEP_ORIGINAL[h]))
            txt = eng
        # 占位译文跳过校验：它只有前 10 个字符，占位符必然不全。
        # 这不是放水 —— 它本来就没翻译，翻译后自然会进入校验。
        # 原文是句子、译文却原样照抄英文的 `IDM_...` 串：那是没翻，报错。
        # （原文本身是标识符的情况在上面就原样写回、不进这里了。）
        en_ref = s.get(T.BASE_LANG, "") or ""
        ident_ph = is_identifier(txt) and txt.strip() == en_ref.strip()
        if ident_ph:
            errors.append("%s 仍是开发标识符占位（%s），没有翻译" % (h, txt))
        if not is_placeholder(txt) and not ident_ph:
            check_placeholders(h, en_ref, txt, errors, warnings)
        if has_bare_pipe(txt):
            fatal.append("%s 含未转换的 |（换行请写 <n>）" % h)
            continue
        # 【坑】hash 必须写成**大写**（0x30A45770），与既有语言包一致。
        # patch.js 的合并逻辑按大写规范化 hash，产物若写成小写，
        # 用户手改过的条目就识别不出来，合并会静默失效（测试 test_patch.js
        # 会抓到）。小写 id 只存在于 src\translations\*.toml 里作为内部键。
        out_txt = add_mark(txt, mk[h]) if marks and h in mk else txt
        body.append("%s = %s\n" % (h.upper().replace("0X", "0x"),
                                   to_engine(out_txt)))
        n += 1
        if is_placeholder(txt) or ident_ph:
            n_ph += 1
    head, meta = _pack_head(lang, pack_version, scope, body,
                           n + n_empty + n_ident, n_ph)
    return head + body, n, n_ph, n_empty, n_ident, meta


def union_baseline(bases):
    """把多份基线合成一份「并集」基线：键集是各行键集的并集，取值按**各自版本**的原文。

    同一键在多份基线里都出现时只留一份（取先出现的那份的原文）—— 实测
    en 1.1.2.3 与 fr 1.1.2.42 共有的 3529 条在两份原文表里正文一致，版本差只
    体现在键集。顺序：先主基线的顺序，再把其余基线独有的键按各自的表顺序接在后面。
    """
    keys, table = [], {}
    for b in bases:
        for k in b["keys"]:
            if k in table:
                continue
            keys.append(k)
            table[k] = b["table"][k]
    return {"id": "union(%s)" % "+".join(b["id"] for b in bases),
            "keys": keys, "table": table, "primary": True}


def build(lang, out_dir, strict, marks=False, baseline="all", variant_out=None,
          union=False, pack_version=""):
    # 参考原文**不参与编译**：生成 en.txt / fr.txt 交给引擎等于用「原始英文」
    # 覆盖游戏，等于没汉化。所以直接拒绝，而不是打个警告继续跑。
    # 名单问 translate —— 那里是唯一一份（src\orig\en.gog_1.1.2.3 之类）。
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import translate as T
    from text import versions as V
    if lang in T.REFERENCE_LANGS:
        print("拒绝：%s 是原文参考语言（%s），不生成语言包。"
              % (lang, "/".join(T.REFERENCE_LANGS)))
        print("      英文/法文只用于校对译文与 id 顺序对照。")
        return 2

    # 版本号写进 pack 头之前先归一：不合规就停，不要出一个版本号写成
    # 半截的包（GUI 只能把那段字符串原样显示）。
    if pack_version:
        normalized = normalize_pack_version(pack_version)
        if not normalized:
            print("拒绝：语言包版本号不合法：%s（只接受 vMAJOR.MINOR.PATCH[-prerelease]）"
                  % pack_version)
            return 2
        pack_version = normalized

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

    by_hash = {}
    for s in doc.get("s", []):
        if s.get("id"):
            by_hash[s["id"].lower()] = s

    bases = _version_bases(baseline)
    if union:
        bases = [union_baseline(bases)]
    variant_out = variant_out or DEFAULT_VARIANT_OUT
    mk = mark_map(list(by_hash)) if marks else {}

    # 定向差是「按版本出包」的唯一依据，构建前先核一遍：
    # 数据漂移（手改了 only_from/only_to、加了新基线没配差）必须在这里就停，
    # 不能出一个「键集与目标版不符」的包还没人知道。
    drift = V.check()
    if drift:
        print("\n版本差核对失败 %d 条：" % len(drift))
        for e in drift[:20]:
            print("  x " + e)
        return 1

    codes, made = [], []
    for b in bases:
        errors, warnings, fatal = [], [], []
        lines, n, n_ph, n_empty, n_ident, meta = _pack_lines(
            lang, b, engine, by_hash, mk, marks, errors, warnings, fatal,
            pack_version=pack_version, scope=scope_token(b["id"]))
        dst_dir = out_dir if b["primary"] else os.path.join(variant_out, b["id"])
        path = os.path.join(dst_dir, "%s.txt" % lang)
        os.makedirs(dst_dir, exist_ok=True)

        if fatal:
            print("\n错误 %d 条（旧写法 | 不再自动转换）：" % len(fatal))
            for e in fatal[:30]:
                print("  x " + e)
            if len(fatal) > 30:
                print("  … 还有 %d 条" % (len(fatal) - 30))
            print("未生成 %s（%s）" % (path, b["id"]))
            codes.append(1)
            continue

        # 一条都没编出来就**不写文件**：写一个 0 条的语言包毫无用处，
        # 装进游戏目录等于没汉化，而调用方只看「文件在不在」。
        # 成因通常是 src\translations\<语言>.toml 压根不存在 ——
        # 合并层只为实际存在的语言建字段。
        if n == 0 and n_empty == 0 and n_ident == 0:
            print("错误：没有编出任何条目，未生成 %s（%s）" % (path, b["id"]))
            print("      找不到 %s\\%s.toml，或它里面没有条目。"
                  % (os.path.join(SRC, "translations"), lang))
            print("      加一种语言：python src\\tools\\pack\\new_lang.py"
                  " --new-lang %s" % lang)
            codes.append(1)
            continue

        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(lines))

        print("\n已生成 %s（%s，键集 %d 条）" % (path, b["id"], len(b["keys"])))
        print("  条目 %d 条，其中占位未翻译 %d 条、原文空占位 %d 条、"
              "原文即标识原样 %d 条%s"
              % (n + n_empty + n_ident, n_ph, n_empty, n_ident,
                 "，已加排查标记" if marks else ""))
        made.append((b["id"], path, n + n_empty + n_ident, n_empty, n_ident))
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
                codes.append(1)
                continue
        codes.append(0)

    if len(made) > 1:
        print("\n本次共出 %d 份：" % len(made))
        for vid, path, total, n_empty, n_ident in made:
            print("  %-18s %5d 条（空占位 %d，原样 %d）  %s"
                  % (vid, total, n_empty, n_ident, path))
    return max(codes) if codes else 0


def main():
    ap = argparse.ArgumentParser(description="把 src/translations\\<语言>.toml 编译成引擎语言包")
    ap.add_argument("--lang", default="", help="语言代码，默认 src\\translations 下第一个可编辑语言")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录")
    ap.add_argument("--strict", action="store_true", help="有错误时返回非零")
    ap.add_argument("--no-fonts", action="store_true",
                    help="只编语言包，不检查/重建字体（批量编译时由调用方统一做）")
    ap.add_argument("--marks", action="store_true",
                    help="给每条正文加 [XXXX] 排查标记（开发用，正常包不要加）")
    ap.add_argument("--baseline", default="all",
                    help="按哪个原版键集出包：all（默认，每个基线各一份）、或某个版本 id"
                         "（如 fr.gog_1.1.2.42）。primary 那份写到 --out，其余写到"
                         " build\\variants\\<id>\\")
    ap.add_argument("--variant-out", default=DEFAULT_VARIANT_OUT,
                    help="非 primary 基线的输出根目录（默认 build\\variants）")
    ap.add_argument("--union", action="store_true",
                    help="只出一份并集包（所有基线的键集合并，写在 --out 的 <语言>.txt）。"
                         "GOG 与 Steam 两个发行包共用这一份；逐版对照仍用默认模式。")
    ap.add_argument("--version", default="",
                    help="写进 pack 头的发行版本号（如 v1.0.0），启动器用它显示"
                         "「简体中文 · v1.0.0」；不给时不写这一行")
    a = ap.parse_args()
    lang = a.lang
    if not lang:
        lang = _default_lang()
    code = build(lang, a.out, a.strict, a.marks, a.baseline, a.variant_out,
                 a.union, pack_version=a.version)

    # 编完语言包顺手检查字体：字体只做映射，按 Noto 替换字体生成。
    # 字体缺失 = 构建失败（以前这里吞异常打「字体检查跳过」，CI 上等于没有字体判据）。
    # 确实不要字体时用 --no-fonts 显式跳过。
    if code == 0 and a.no_fonts:
        print("字体：跳过（--no-fonts 显式指定）")
    if code == 0 and not a.no_fonts:
        from build_artifacts import build_fonts
        ok, msg = build_fonts([lang], mode="noto", log=lambda m: print("  " + m))
        if not ok:
            print("字体构建失败：\n%s" % msg)
            return 1
        print("字体：" + msg)
    return code


if __name__ == "__main__":
    raise SystemExit(main())