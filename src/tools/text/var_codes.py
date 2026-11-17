# -*- coding: utf-8 -*-
"""文本变量码查询/校验：`@格式码$变量名$`。

数据在 glossary/variable_codes.toml（由 build/qa/_var_table_gen.py 从语料生成，人工补含义）。

用法：
    python src/tools/text/var_codes.py --table            # 码表
    python src/tools/text/var_codes.py --vars             # 变量清单（可加 --code T 过滤）
    python src/tools/text/var_codes.py --token "@A$USER$" # 解释单个引用（可给多个）
    python src/tools/text/var_codes.py --check            # 校验全库引用是否都在表里

--check 的判据是「码与变量名的配对」：码未登记、变量名未登记、或该变量名没登记这个码，
都算违规并以非零退出。它查的是表与语料是否一致，不判断语义对错。
"""
import argparse
import os
import re
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
TABLE = os.path.join(ROOT, "glossary", "variable_codes.toml")
LANGS = ("zh", "de", "es", "fr", "ja", "ru")
SOURCES = [os.path.join(ROOT, "src", "orig", "en.gog_1.1.2.3.toml")] + [
    os.path.join(ROOT, "src", "translations", "%s.toml" % l) for l in LANGS]

TOKEN = re.compile(r"@([A-Za-z])\$([A-Za-z_][A-Za-z0-9_]*)\$")


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


def scan(paths=None):
    """统计并校验：返回 (违规列表, 引用总数)。"""
    paths = SOURCES if paths is None else paths
    codes, vars_ = load_table()[1], load_table()[2]
    bad = []
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
                if code not in codes:
                    bad.append((rel, key, m.group(0), "码未登记"))
                elif name not in vars_:
                    bad.append((rel, key, m.group(0), "变量名未登记"))
                elif code not in vars_[name].get("codes", []):
                    bad.append((rel, key, m.group(0),
                                "该变量名没登记这个码（表里：%s）"
                                % "/".join(vars_[name].get("codes", []))))
    return bad, total


def print_table(codes):
    order = sorted(codes, key=lambda c: (-codes[c].get("refs_en", 0), c))
    w = max(len(c) for c in codes) + 2
    print("%-*s %-22s %-11s %6s  %s" % (w, "码", "含义", "置信度", "原文", "配的变量名"))
    for c in order:
        info = codes[c]
        names = info.get("names", [])
        print("%-*s %-22s %-11s %6d  %d 个：%s"
              % (w, c, info.get("meaning", ""), info.get("conf", ""),
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
    ap = argparse.ArgumentParser(description="PR2 文本变量码查询/校验")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--table", action="store_true", help="打印码表")
    g.add_argument("--vars", action="store_true", help="打印变量清单")
    g.add_argument("--token", nargs="+", help="解释一个或多个 @码$名$")
    g.add_argument("--check", action="store_true", help="校验全库引用")
    ap.add_argument("--code", help="与 --vars 连用，只列某个码的变量")
    a = ap.parse_args(argv)

    meta, codes, vars_ = load_table()
    if a.table:
        print("%s（%s 处引用 / %d 个码 / %d 个变量名）"
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
            if r["problems"]:
                rc = 1
                for p in r["problems"]:
                    print("  ! " + p)
        return rc
    else:
        bad, total = scan()
        print("扫描 %d 个文件，%d 处引用" % (len(SOURCES), total))
        if bad:
            for rel, key, tok, why in bad:
                print("  %s  %s  %s  %s" % (rel, key, tok, why))
            print("违规 %d 处" % len(bad))
            return 1
        print("全部在表内。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
