# -*- coding: utf-8 -*-
"""文本变量码表：`@格式码$变量名$` 的事实源、生成与校验。

事实分两处：
  glossary/variable_codes.toml —— 手工维护（含义、置信度、依据、例外），统计字段是算的；
  src/orig/en.gog_1.1.2.3.toml + 六语译文 —— 统计来源（次数、例句、原文有没有）。

docs/文本变量码表.md 是**生成物**，不要手改；改含义改 TOML，再 `--sync` 重排统计与文档。

用法：
    python src/tools/text/var_codes.py --table            # 码表
    python src/tools/text/var_codes.py --vars             # 变量清单（可加 --code T 过滤）
    python src/tools/text/var_codes.py --token "@A$USER$" # 解释单个引用（可给多个）
    python src/tools/text/var_codes.py --sync             # 重算统计、重写 TOML 与 md 文档
    python src/tools/text/var_codes.py --check            # 校验全库引用（例外只提示，不算违规）

--check 的判据是「码与变量名的配对」：码未登记、变量名未登记、或该变量名没登记这个码，
都算违规并以非零退出；登记在 EXCEPTIONS 里的那几处只打印提示。
"""
import argparse
import collections
import os
import re
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
TABLE = os.path.join(ROOT, "glossary", "variable_codes.toml")
DOC_MD = os.path.join(ROOT, "docs", "文本变量码表.md")
LANGS = ("zh", "de", "es", "fr", "ja", "ru")
SOURCES = [os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")] + [
    os.path.join(ROOT, "src", "translations", "%s.toml" % l) for l in LANGS]

TOKEN = re.compile(r"@([A-Za-z])\$([A-Za-z_][A-Za-z0-9_]*)\$")

# 已知与主流不一致、但暂随原文的引用：键 + 该键里那一处 token。
# 这几个键必须与 src/tools/analysis/text_lint.py 的 VAR_CODE_ORIG 完全一致（docs_check 会断言）。
# 它们不是「豁免」，是「提示」：--check 每次都会把这几处列出来，只是不算违规。
EXCEPTIONS = {
    "0xca4930dc": {
        "token": "@A$Amount$",
        "var": "Amount",
        "note": "英文原文起、六语照抄；A 与 a 对数字是空操作（67.9），"
                "但引擎是否区分这个字母仍无证据，等实机对照这一行显示数字还是字面量（67.8）",
    },
}


def _toml_q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def load_table(path=TABLE):
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return raw["meta"], raw["code"], raw["var"]


def explain(tok, codes=None, vars_=None):
    """把一个 token 拆成 {code, name, code_info, var_info}；不合法时抛 ValueError。"""
    codes = load_table()[1] if codes is None else codes
    vars_ = load_table()[2] if vars_ is None else vars_
    m = re.fullmatch(TOKEN, tok)
    if not m:
        raise ValueError("不是合法的变量引用：%r（形如 @X$Name$）" % tok)
    code, name = m.group(1), m.group(2)
    c = codes.get(code)
    v = vars_.get(name)
    problems = []
    if c is None:
        problems.append("码 %s 未登记" % code)
    if v is None:
        problems.append("变量名 %s 未登记" % name)
    if c is not None and v is not None and code not in v.get("codes", []):
        problems.append("变量名 %s 没登记码 %s（表里只有 %s）"
                        % (name, code, "/".join(v.get("codes", []))))
    return {"token": tok, "code": code, "name": name,
            "code_info": c, "var_info": v, "problems": problems}


def _docs():
    sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))
    import toml_io
    return [toml_io.read_doc(p)[0] for p in SOURCES]


def stats(docs=None):
    """算统计：每个 (码,名) 的次数、每个名字在原文出现没有、每处引用的最短例句。"""
    docs = _docs() if docs is None else docs
    by_code = collections.defaultdict(collections.Counter)
    by_name = collections.defaultdict(collections.Counter)
    en_by_code = collections.defaultdict(collections.Counter)
    en_by_name = collections.defaultdict(collections.Counter)
    in_orig = set()
    example = {}
    total_en = 0
    total_all = 0
    for i, doc in enumerate(docs):
        for _k, text in doc.items():
            total_en += len(TOKEN.findall(text)) if i == 0 else 0
            total_all += len(TOKEN.findall(text))
            for code, name in TOKEN.findall(text):
                by_code[code][name] += 1
                by_name[name][code] += 1
                if i == 0:
                    en_by_code[code][name] += 1
                    en_by_name[name][code] += 1
                    in_orig.add(name)
                cur = example.get((code, name))
                if cur is None or len(text) < len(cur):
                    example[(code, name)] = text
    return {"by_code": by_code, "by_name": by_name, "en_by_code": en_by_code,
            "en_by_name": en_by_name, "in_orig": in_orig, "example": example,
            "total_en": total_en, "total_all": total_all}


def scan(paths=None):
    """校验语料：返回 (违规列表, 提示列表, 引用总数)。"""
    paths = SOURCES if paths is None else paths
    codes, vars_ = load_table()[1], load_table()[2]
    bad, hints = [], []
    total = 0
    sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))
    import toml_io
    for path in paths:
        doc, _o = toml_io.read_doc(path)
        rel = os.path.relpath(path, ROOT)
        for key, text in doc.items():
            for m in TOKEN.finditer(text):
                total += 1
                code, name = m.group(1), m.group(2)
                tok = m.group(0)
                exc = EXCEPTIONS.get(key)
                if exc and exc["token"] == tok:
                    hints.append((rel, key, tok, exc["note"]))
                    continue
                if code not in codes:
                    bad.append((rel, key, tok, "码未登记"))
                elif name not in vars_:
                    bad.append((rel, key, tok, "变量名未登记"))
                elif code not in vars_[name].get("codes", []):
                    bad.append((rel, key, tok,
                                "该变量名没登记这个码（表里：%s）"
                                % "/".join(vars_[name].get("codes", []))))
    # 例外也要保鲜：登记的键在七个语料文件里都必须真的有那一处，否则就是过期例外
    # （这一步不看 paths，永远按全部语料算，否则只扫一个文件就会误报）
    for key, exc in EXCEPTIONS.items():
        found = 0
        for path in SOURCES:
            doc, _o = toml_io.read_doc(path)
            if key in doc:
                found += doc[key].count(exc["token"])
        if found != len(SOURCES):
            bad.append(("", key, exc["token"],
                        "例外过期：%d 个文件里有这一处，应为 %d" % (found, len(SOURCES))))
    return bad, hints, total


def _note(name, codes, st):
    parts = []
    if len(codes) > 1:
        parts.append("同一变量名出现多种码：%s（原文次数）"
                     % " / ".join("%s×%d" % (c, st["en_by_name"][name][c])
                                  for c in codes))
    if name not in st["in_orig"]:
        parts.append("英文原文里没有这个引用，译自标识符行的补译（2004 竞赛文本）")
    for key, exc in EXCEPTIONS.items():
        if exc["var"] == name:
            parts.append("其中 %s 那处是已知例外（%s），见 --check 的提示" % (exc["token"], key))
    return "；".join(parts)


def render_toml(meta, codes, vars_, st):
    unknown = sorted(c for c in codes if codes[c].get("conf") == "unknown")
    L = []
    L.append("# PR2 文本变量码表（@码$变量名$）")
    L.append("#")
    L.append("# 结构：@ + 单字母格式码 + $ + 变量名 + $，尾 $ 必需（%d 处引用零例外）。"
             % st["total_en"])
    L.append("# 码是「类型/转换器」标签（大小写是类型名的一部分，不是文本变换，见 09 卷 67.9）。")
    L.append("#")
    L.append("# 手工维护：meaning / display / conf / evidence。其余字段由 --sync 重算，不要手改。")
    L.append("# 置信度三档：confirmed=配对结构实证 / inferred=由配对与语境推断 / unknown=只有配对事实")
    L.append("# 工具：python src/tools/text/var_codes.py --table / --check / --sync")
    L.append("")
    L.append("[meta]")
    L.append('title = %s' % _toml_q(meta.get("title", "PR2 文本变量码表")))
    L.append("references_en = %d" % st["total_en"])
    L.append("references_all = %d" % st["total_all"])
    L.append("names = %d" % len(vars_))
    L.append("codes = %d" % len(codes))
    L.append('confidence_legend = %s' % _toml_q(meta.get("confidence_legend", "")))
    L.append('tool = %s' % _toml_q("python src\\tools\\text\\var_codes.py --table"))
    L.append("unknown_codes = [%s]" % ", ".join(_toml_q(c) for c in unknown))
    L.append("exception_keys = [%s]" % ", ".join(_toml_q(k) for k in sorted(EXCEPTIONS)))
    L.append("")
    for code in sorted(codes):
        info = codes[code]
        L.append("[code.%s]" % code)
        L.append("meaning = %s" % _toml_q(info.get("meaning", "")))
        L.append("display = %s" % _toml_q(info.get("display", "")))
        L.append("conf = %s" % _toml_q(info.get("conf", "")))
        L.append("evidence = %s" % _toml_q(info.get("evidence", "")))
        L.append("refs_en = %d" % sum(st["en_by_code"][code].values()))
        L.append("refs_all = %d" % sum(st["by_code"][code].values()))
        L.append("names = [%s]" % ", ".join(
            _toml_q(n) for n in sorted(st["by_code"][code])))
        L.append("")
    for name in sorted(vars_):
        info = vars_[name]
        cs = sorted(st["by_name"][name])
        L.append("[var.%s]" % name)
        L.append("meaning = %s" % _toml_q(info.get("meaning", "")))
        L.append("codes = [%s]" % ", ".join(_toml_q(c) for c in cs))
        L.append("refs_en = %d" % sum(st["en_by_name"][name].values()))
        L.append("refs_all = %d" % sum(st["by_name"][name].values()))
        ex = st["example"][(cs[0], name)].replace("\r", " ").replace("\n", " ")
        L.append("example = %s" % _toml_q(ex[:110]))
        L.append("in_original = %s" % ("true" if name in st["in_orig"] else "false"))
        note = _note(name, cs, st)
        if note:
            L.append("note = %s" % _toml_q(note))
        L.append("")
    for key in sorted(EXCEPTIONS):
        exc = EXCEPTIONS[key]
        L.append('[exception."%s"]' % key)
        L.append("token = %s" % _toml_q(exc["token"]))
        L.append("var = %s" % _toml_q(exc["var"]))
        L.append("note = %s" % _toml_q(exc["note"]))
        L.append("")
    return "\n".join(L) + "\n"


def render_md(meta, codes, vars_, st):
    unknown = sorted(c for c in codes if codes[c].get("conf") == "unknown")
    L = []
    L.append("# 文本变量码表（`@码$变量名$`）")
    L.append("")
    L.append("引擎文本里的动态值都写成 `@格式码$变量名$`，例如 `@A$USER$`（玩家名）、"
             "`@a$Amount$`（数量）、`@T$Town$`（城镇名）。这一份是从 `en.gog_1.1.2.3` 的 "
             "**%d 处引用**（%d 个变量名、%d 个码）反推的表。"
             % (st["total_en"], len(vars_), len(codes)))
    L.append("")
    L.append("结构：`@` + 单字母格式码 + `$` + 变量名 + `$`，尾 `$` 必需（%d 处零例外）。"
             "**码是类型标签，不是文本变换**——同字母的大小写对应不同类型"
             "（`G` 货物 / `g` 金币、`N` 人名 / `n` 国家），详见 09 卷 67.9。"
             % st["total_en"])
    L.append("")
    L.append("> 本文件由 `src/tools/text/var_codes.py --sync` 生成，**不要手改**；"
             "改含义改 `glossary/variable_codes.toml` 后重跑。`src/tools/docs_check.py` 会比对"
             "本文件与重新生成的结果，不一致即红。")
    L.append("")
    L.append("## 格式码")
    L.append("")
    L.append("| 码 | 含义 | 显示成什么 | 置信度 | 原文次数 | 依据 |")
    L.append("|---|---|---|---|---|---|")
    for code in sorted(codes, key=lambda c: (-sum(st["en_by_code"][c].values()), c)):
        info = codes[code]
        L.append("| `%s` | %s | %s | %s | %d | %s |"
                 % (code, info.get("meaning", ""), info.get("display", ""),
                    info.get("conf", ""), sum(st["en_by_code"][code].values()),
                    info.get("evidence", "")))
    L.append("")
    L.append("置信度：`confirmed` = 配对结构实证（该码只配某一类变量名，全库无例外）；"
             "`inferred` = 由配对与语境推断（如金额的排版细节）；"
             "`unknown` = 只有配对事实，含义待实机/反汇编。当前 unknown：%s。"
             % "、".join("`%s`" % c for c in unknown))
    L.append("")
    L.append("## 变量名")
    L.append("")
    for code in sorted(codes, key=lambda c: (-sum(st["en_by_code"][c].values()), c)):
        info = codes[code]
        L.append("### `%s` — %s" % (code, info.get("meaning", "")))
        L.append("")
        L.append("| 变量名 | 含义 | 原文次数 |")
        L.append("|---|---|---|")
        for n in sorted(st["by_code"][code]):
            mark = "" if n in st["in_orig"] else "（译文补译，英文原文无）"
            L.append("| `%s` | %s%s | %d |"
                     % (n, vars_[n].get("meaning", ""), mark,
                        st["en_by_name"][n][code]))
        L.append("")
        ex = st["example"][(code, sorted(st["by_code"][code])[0])]
        ex = ex.replace("\r", " ").replace("\n", " ")
        L.append("样例：`%s`" % ex[:150].replace("|", "\\|"))
        L.append("")
    L.append("## 已知例外（提示，不是豁免）")
    L.append("")
    for key in sorted(EXCEPTIONS):
        exc = EXCEPTIONS[key]
        L.append("- `%s` 的 `%s`：%s" % (key, exc["token"], exc["note"]))
    L.append("")
    L.append("`--check` 每次都会把这几处打印成提示，不计违规；只有登记的键里真的找不到这一处时才算"
             "「例外过期」。这样它不会像静默豁免那样烂在代码里。")
    L.append("")
    L.append("## 怎么用")
    L.append("")
    L.append("```")
    L.append('python src/tools/text/var_codes.py --table            # 码表')
    L.append('python src/tools/text/var_codes.py --vars --code g     # 某码的变量')
    L.append('python src/tools/text/var_codes.py --token "@A$USER$"  # 解释单个引用')
    L.append('python src/tools/text/var_codes.py --check            # 校验全库引用')
    L.append('python src/tools/text/var_codes.py --sync             # 重算统计、重写本文件')
    L.append("```")
    L.append("")
    L.append("`--check` 扫 `src/orig/en.gog_1.1.2.3.toml` 加六语译文，共 %d 处引用；"
             "判据是「码与变量名的配对」，码或名未登记、或该名没登记这个码都算违规。"
             % st["total_all"])
    L.append("")
    L.append("译文里只照抄原文的 `@码$名$`（大小写不动）；要判断「这个码配这个名对不对」，"
             "用 `--check`，别用肉眼。`PirateGold` 在英文原文里没有引用，只在六语译文里出现"
             "（2004 竞赛文本的标识符行补译），所以它的原文次数是 0。")
    L.append("")
    return "\n".join(L)


def sync(write=True):
    meta, codes, vars_ = load_table()
    st = stats()
    t = render_toml(meta, codes, vars_, st)
    m = render_md(meta, codes, vars_, st)
    if write:
        import io
        io.open(TABLE, "w", encoding="utf-8", newline="").write(t)
        io.open(DOC_MD, "w", encoding="utf-8", newline="").write(m)
    return t, m


def print_table(codes):
    order = sorted(codes, key=lambda c: (-codes[c].get("refs_en", 0), c))
    print("%-3s %-22s %-11s %6s  %s" % ("码", "含义", "置信度", "原文", "配的变量名"))
    for c in order:
        info = codes[c]
        names = info.get("names", [])
        print("%-3s %-22s %-11s %6d  %d 个：%s"
              % (c, info.get("meaning", ""), info.get("conf", ""),
                 info.get("refs_en", 0), len(names),
                 ", ".join(names[:6]) + ("…" if len(names) > 6 else "")))


def print_vars(vars_, code=None):
    for name in sorted(vars_, key=lambda n: (-vars_[n].get("refs_all", 0), n)):
        v = vars_[name]
        cs = v.get("codes", [])
        if code and code not in cs:
            continue
        print("%-16s %-6s %-4d  %s%s" % (name, "/".join(cs),
                                        v.get("refs_en", 0), v.get("meaning", ""),
                                        "" if v.get("in_original", True) else "（原文无）"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="PR2 文本变量码表")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--table", action="store_true", help="打印码表")
    g.add_argument("--vars", action="store_true", help="打印变量清单")
    g.add_argument("--token", nargs="+", help="解释一个或多个 @码$名$")
    g.add_argument("--check", action="store_true", help="校验全库引用")
    g.add_argument("--sync", action="store_true", help="重算统计并重写表与文档")
    ap.add_argument("--code", help="与 --vars 连用，只列某个码的变量")
    a = ap.parse_args(argv)

    if a.sync:
        t, m = sync()
        meta, codes, vars_ = load_table()
        print("已重写 glossary/variable_codes.toml（%d 行）与 docs/文本变量码表.md（%d 行）"
              % (t.count("\n"), m.count("\n")))
        return 0

    meta, codes, vars_ = load_table()
    if a.table:
        print("%s（%d 处引用 / %d 个码 / %d 个变量名）"
              % (meta.get("title"), meta.get("references_en"), len(codes), len(vars_)))
        print("置信度：" + meta.get("confidence_legend", ""))
        print()
        print_table(codes)
    elif a.vars:
        if a.code and a.code not in codes:
            print("码 %s 未登记" % a.code, file=sys.stderr)
            return 2
        print_vars(vars_, a.code)
    elif a.token:
        rc = 0
        for tok in a.token:
            try:
                r = explain(tok, codes, vars_)
            except ValueError as e:
                print(str(e), file=sys.stderr)
                rc = 2
                continue
            c, v = r["code_info"] or {}, r["var_info"] or {}
            print("%s" % r["token"])
            print("  码 %s：%s（%s）" % (r["code"], c.get("meaning", "未登记"),
                                       c.get("conf", "")))
            print("  变量 %s：%s（码 %s）" % (r["name"], v.get("meaning", "未登记"),
                                            "/".join(v.get("codes", [])) or "-"))
            for key, exc in EXCEPTIONS.items():
                if exc["token"] == tok:
                    print("  提示：登记在例外 %s 里 —— %s" % (key, exc["note"]))
            if r["problems"]:
                rc = 1
                for p in r["problems"]:
                    print("  ! " + p)
        return rc
    else:
        bad, hints, total = scan()
        print("扫描 %d 个文件，%d 处引用" % (len(SOURCES), total))
        for rel, key, tok, note in hints:
            print("  提示：%s %s %s —— %s"
                  % (rel, key, tok, note.split("；")[0]))
        if hints:
            print("  以上 %d 处是已知例外，不计违规（见 docs/文本变量码表.md 的「已知例外」）"
                  % len(hints))
        if bad:
            for rel, key, tok, why in bad:
                print("  违规：%s %s %s %s" % (rel, key, tok, why))
            return 1
        print("全部在表内。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
