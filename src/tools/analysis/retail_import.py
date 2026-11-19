"""把官方零售版参照落进译文，并把标注层一起搬过去。

为什么要有这个脚本
------------------
`translate.py apply` 只会「把一份映射写进译文」，它不知道零售版参照在哪、
更不知道标注层。pl 那一轮是 `build/pl_retail_map.py` 一次性脚本干的，而且只做
最窄的一件事：**只填还没译的行**（现值等于英文的行）。换一门语言立刻就漏两件：

1. **替换已译**：es 有 1477 行与零售不同，其中 1400 行是整句改写 —— 不是「没译」，
   是「译过、但不如零售」。只填未译行的脚本对这 1400 行一个字都不动。
2. **承标注**：现译里有 `[town:Biloxi]`、`[term:en_tools]` 这类标注，零售文本是
   纯文本，一条标注都没有。整行覆盖等于把标注层抹掉，而标注层是给 `text/marks.py`
   消费的（地名按译名表展开、术语按术语表展开），抹掉之后校名识别和诗谜 clue
   都会跟着坏。

所以这里做两件事：把零售文本按标注**逐个搬回去**，再交给 `apply_map` 落盘——
占位符与标签的校验仍在 `apply_map` 里，一份实现，不在这里重复。

承标注的规则（宁可放弃，不猜）
------------------------------
标注 `[town:X]` 的参数不是显示文本，是译名表里的键；显示文本要用 `marks.expand`
按本语言的 names 表解析（`[town:St. Augustine]` 在 es 里展开成 `San Agustín`）。
所以搬运方法是「按展开结果定位」：先算出这条标注会显示的字符串，再在零售文本里
找它，找到且**只出现一次**就把那个片段换回标注本身。找不到、或出现多次，这行就
整条放弃并报「标注对不上」——位置猜错会把地名套到别的词上，那比不导更糟。

诗谜（`[riddle:…]`）与引用（`[ref:…]`）不在这条路上：前者要重算 clue 并逐字核对，
后者会牵出另一条文本，都该走 `riddle_marks` 与人工，这里整行跳过并计数。
"""

import argparse
import io
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import translate as T  # noqa: E402
from text import marks as MK  # noqa: E402

#: 一条标注的完整写法：`[key:arg]`。arg 里允许再出现冒号（`ref:键`）与斜杠（形态）。
MARK_RX = re.compile(r"\[(ref|town|lit|term|riddle):([^\[\]]{1,200})\]")
#: 需要绕开的两类标注：诗谜要重算 clue，引用牵出另一条文本。
DEFER_KEYS = ("riddle", "ref")
OUT_DIR = os.path.join(T.ROOT, "build", "qa")


def load(path):
    import tomllib
    with io.open(path, "rb") as f:
        return tomllib.load(f)


def resolve_path(ref):
    """`--ref` 既收短名（es.retail-1.0.0）也收路径。"""
    if os.path.isfile(ref):
        return ref
    cand = T.lang_path(ref)
    if os.path.isfile(cand):
        return cand
    raise SystemExit("找不到参照：%s（也不在 src\\orig\\ 下）" % ref)


def carried(cur, ref, resolve):
    """把 `cur` 里的标注搬到 `ref` 上。返回 (合并后的文本, 放弃原因或 None)。

    `resolve` 是 `(标注原文, id) -> 该标注的显示文本`，由调用方按语言注入；
    测试里换成字面表即可，不需要真的读译名表。
    """
    if "[" in ref or "]" in ref:
        return None, "参照自带方括号，不敢动"
    out = ref
    for key, arg in MARK_RX.findall(cur):
        if key in DEFER_KEYS:
            return None, "含 [%s:…]，要另一道工序" % key
        span = "[%s:%s]" % (key, arg)
        shown = resolve(span, "")
        if not shown:
            return None, "标注 %s 展开为空" % span
        n = out.count(shown)
        if n == 0:
            return None, "标注 %s 的显示文本不在参照里" % span
        if n > 1:
            return None, "标注 %s 的显示文本在参照里出现 %d 次" % (span, n)
        out = out.replace(shown, span, 1)
    return out, None


def build(lang, ref_name, only_empty=False):
    """算出待落盘映射与分流统计。不写文件。"""
    en = load(T.lang_path(T.BASE_LANG))
    cur = load(T.lang_path(lang))
    ref = load(resolve_path(ref_name))
    keep = set(T.keep_as_is(lang))
    table = MK.load_names(lang)
    terms = MK.load_terms(lang)

    mapping, why = {}, {}

    def note(hid, reason):
        why.setdefault(reason, []).append(hid)

    for hid, src in en.items():
        now = cur.get(hid, "")
        rv = ref.get(hid)
        if hid in keep:
            note(hid, "不译名单")
            continue
        if rv is None:
            note(hid, "参照里没有这条")
            continue
        rv = str(rv)
        if not rv.strip():
            note(hid, "参照为空")
            continue
        if rv.strip() == str(src).strip():
            note(hid, "参照没翻（等于英文）")
            continue
        if only_empty and now.strip() != str(src).strip():
            note(hid, "已有译文")
            continue
        if now == rv:
            note(hid, "与参照已一致")
            continue
        if "[" in now:
            try:
                body, reason = carried(now, rv, lambda s, h: MK.expand(
                    s, table, lang, h or hid, terms=terms, doc=cur))
            except MK.MarkError:
                note(hid, "标注展开失败（译名表或术语表缺条目）")
                continue
            if reason:
                note(hid, reason)
                continue
            rv = body
        mapping[hid] = rv
    return mapping, why


def render(lang, ref_name, mapping, why, stats):
    lines = ["# 零售参照导入：%s ← %s" % (lang, ref_name), ""]
    lines.append("候选 %d 条；apply 可落 %d 条、拦住 %d 条（令牌 %d、标签 %d、助词 %d、"
                 "非本语言 %d、并列次序 %d）"
                 % (len(mapping), stats.get("hit", 0), stats.get("skipped", 0),
                    len(stats.get("tokens", [])), len(stats.get("tag", [])),
                    len(stats.get("josa", [])), len(stats.get("lang", [])),
                    len(stats.get("pair", []))))
    lines.append("")
    lines.append("## 没进映射的行（按原因分流）")
    for reason, ids in sorted(why.items(), key=lambda kv: -len(kv[1])):
        lines.append("  %-24s %4d   %s" % (reason, len(ids), " ".join(ids[:6]))
                     + (" …" if len(ids) > 6 else ""))
    rows = []
    for key, label in (("tokens", "令牌"), ("tag", "标签"), ("pair", "并列"),
                       ("josa", "助词"), ("lang", "非本语言")):
        for row in stats.get(key, []) or []:
            rows.append("%-6s %s" % (label, row if isinstance(row, str) else str(row)))
    if rows:
        lines.append("")
        lines.append("## apply 拦下的条目（改参照里的结构缺陷后重跑即可）")
        lines.extend("  " + r for r in rows)
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="把零售版参照导入译文（含承标注）")
    ap.add_argument("--lang", required=True)
    ap.add_argument("--ref", required=True, help="短名或路径，如 es.retail-1.0.0")
    ap.add_argument("--only-empty", action="store_true",
                    help="只填还没译的行（pl 当年就是这个口径）")
    ap.add_argument("--write", action="store_true", help="真落盘；默认只出报告")
    ap.add_argument("--dump", default="", help="同时把映射写成 json")
    ap.add_argument("--out", default="", help="报告路径，默认 build\\qa\\retail_import_<lang>.txt")
    args = ap.parse_args(argv)

    mapping, why = build(args.lang, args.ref, args.only_empty)
    stats = T.apply_map(args.lang, mapping, dry_run=not args.write)
    text = render(args.lang, args.ref, mapping, why, stats)
    out = args.out or os.path.join(OUT_DIR, "retail_import_%s.txt" % args.lang)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(text)
    print(text)
    print("报告：%s" % out)
    if args.dump:
        json.dump(mapping, io.open(args.dump, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("映射：%s" % args.dump)
    if not args.write:
        print("（只出报告，加 --write 才落盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
