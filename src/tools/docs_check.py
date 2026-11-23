# -*- coding: utf-8 -*-
"""文档一致性检查：索引完整性、编号唯一、生成物无漂移、几条窄断言。

为什么要有这个：手册型文档会替代码撒谎——目录里加了文件没人补索引索引，
语料变了文档里的次数还是旧的，代码里的豁免清单与文档里的例外说明各走各的。
这里把「能从数据算出来的」与「必须两边一致的」都变成可跑的红灯。

刻意不做：不解析自然语言正文。断言只认两种语法——markdown 链接、
以及显式写死的「未知码清单」一行。09 卷那种日志型文档的叙述不归这里管。

用法：python src/tools/docs_check.py
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "docs"))
import var_codes as VC
import build_language_matrix as LM
LANGUAGE_MATRIX = os.path.join(ROOT, "docs", "语言矩阵.md")

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
NUM = re.compile(r"^(\d\d)-")
INFER_DOC = os.path.join(ROOT, "docs", "界面映射", "09-推断-连续键区.md")
LINT = os.path.join(ROOT, "src", "tools", "analysis", "text_lint.py")
README = os.path.join(ROOT, "docs", "README.md")
MAPS_README = os.path.join(ROOT, "docs", "界面映射", "README.md")
ARCHIVE_README = os.path.join(ROOT, "docs", "archive", "README.md")


def _md_files(d):
    return sorted(f for f in os.listdir(d)
                  if f.endswith(".md") and f != "README.md")


def _links(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out = []
    for target in LINK.findall(text):
        t = target.split("#")[0].strip()
        if not t or t.startswith("http") or not t.endswith(".md"):
            continue
        out.append((target, os.path.normpath(os.path.join(os.path.dirname(path), t))))
    return out


def check_index(path, title):
    """索引里的链接都要能落地；目录里的每个 .md 都要被索引到。"""
    bad = []
    linked = set()
    for raw, full in _links(path):
        if not os.path.isfile(full):
            bad.append("索引链接指向不存在的文件：%s（写的是 %s）"
                       % (os.path.relpath(full, ROOT), raw))
        else:
            linked.add(os.path.relpath(full, ROOT))
    d = os.path.dirname(path)
    for f in _md_files(d):
        rel = os.path.relpath(os.path.join(d, f), ROOT)
        if rel not in linked:
            bad.append("%s 里没有索引到：%s" % (title, rel))
    return bad


def check_numbering(d, title):
    """NN- 前缀不许重复。"""
    bad = []
    seen = {}
    for f in os.listdir(d):
        m = NUM.match(f)
        if not m:
            continue
        seen.setdefault(m.group(1), []).append(f)
    for num, files in sorted(seen.items()):
        if len(files) > 1:
            bad.append("%s 编号 %s 重复：%s" % (title, num, "、".join(files)))
    return bad


def check_drift():
    """TOML 的统计字段与语料一致；md 文档与重新生成的结果一致。"""
    bad = []
    meta, codes, vars_ = VC.load_table()
    st = VC.stats()
    want_t = VC.render_toml(meta, codes, vars_, st)
    with open(VC.TABLE, encoding="utf-8") as f:
        got_t = f.read()
    if want_t != got_t:
        bad.append("glossary/variable_codes.toml 与语料不符（次数/例句/清单是旧的），"
                   "跑 python src/tools/text/var_codes.py --sync")
    want_m = VC.render_md(meta, codes, vars_, st)
    with open(VC.DOC_MD, encoding="utf-8") as f:
        got_m = f.read()
    if want_m != got_m:
        bad.append("docs/文本变量码表.md 与重新生成的不一致（不要手改这个文件），"
                   "跑 python src/tools/text/var_codes.py --sync")
    return bad


def _unknown_from_doc():
    with open(INFER_DOC, encoding="utf-8") as f:
        for line in f:
            if "未知码清单" in line:
                return set(re.findall(r"`([A-Za-z])`", line))
    return None


def check_unknown_codes():
    """09 卷点名的未知码 == 表里 conf=unknown 的码 == meta.unknown_codes。"""
    bad = []
    meta, codes, _v = VC.load_table()
    table = {c for c in codes if codes[c].get("conf") == "unknown"}
    doc = _unknown_from_doc()
    if doc is None:
        bad.append("09 卷 68.1 找不到「未知码清单」这一行（它是机器可读断言的锚点）")
        return bad
    if doc != table:
        bad.append("09 卷点名的未知码 %s 与表里 conf=unknown 的 %s 不一致"
                   % (sorted(doc), sorted(table)))
    if set(meta.get("unknown_codes", [])) != table:
        bad.append("meta.unknown_codes 与 conf=unknown 不一致，跑 --sync")
    return bad


def _lint_const(name):
    with open(LINT, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError("text_lint.py 里找不到常量 %s" % name)


def check_exceptions():
    """例外清单：代码里的例外 == 表里的 exception_keys；多码变量名两边对得上。"""
    bad = []
    meta, _codes, vars_ = VC.load_table()
    orig = _lint_const("VAR_CODE_ORIG")
    multi_src = _lint_const("VAR_CODE_MULTI")
    if set(VC.EXCEPTIONS) != set(orig):
        bad.append("var_codes.EXCEPTIONS 的键 %s 与 text_lint.VAR_CODE_ORIG 的 %s 不一致"
                   % (sorted(VC.EXCEPTIONS), sorted(orig)))
    if set(meta.get("exception_keys", [])) != set(VC.EXCEPTIONS):
        bad.append("meta.exception_keys 与 EXCEPTIONS 不一致，跑 --sync")
    multi_tbl = {n for n, v in vars_.items() if len(v.get("codes", [])) > 1}
    exc_vars = {e["var"] for e in VC.EXCEPTIONS.values()}
    if multi_tbl != set(multi_src) | exc_vars:
        bad.append("表里多码变量 %s 应等于 VAR_CODE_MULTI %s 并上例外涉及的 %s"
                   % (sorted(multi_tbl), sorted(multi_src), sorted(exc_vars)))
    for key, exc in VC.EXCEPTIONS.items():
        v = vars_.get(exc["var"], {})
        code = exc["token"][1]
        if code not in v.get("codes", []):
            bad.append("例外 %s 的 %s 没登记在 var.%s.codes 里" % (key, exc["token"], exc["var"]))
    return bad


def check_language_matrix():
    """docs/语言矩阵.md 必须与配置审计结果一致；生成物不手改。"""
    try:
        want = LM.build()
    except ValueError as exc:
        return ["语言矩阵审计失败：%s" % exc]
    with open(LANGUAGE_MATRIX, encoding="utf-8") as fh:
        got = fh.read()
    if want != got:
        return ["docs/语言矩阵.md 与配置不一致；运行 "
                "python src/tools/docs/build_language_matrix.py"]
    return []


def main():
    items = [
        ("docs 索引", lambda: check_index(README, "docs/README.md")),
        ("界面映射索引", lambda: check_index(MAPS_README, "界面映射/README.md")),
        ("归档索引", lambda: check_index(ARCHIVE_README, "docs/archive/README.md")),
        ("界面映射编号", lambda: check_numbering(os.path.join(ROOT, "docs", "界面映射"),
                                              "界面映射")),
        ("码表与语料", check_drift),
        ("语言矩阵", check_language_matrix),
        ("未知码清单", check_unknown_codes),
        ("例外与源码常量", check_exceptions),
    ]
    failed = 0
    for title, fn in items:
        bad = fn()
        if bad:
            failed += 1
            print("× %s" % title)
            for b in bad:
                print("    " + b)
        else:
            print("√ %s" % title)
    if failed:
        print("\n文档一致性问题 %d 组。" % failed)
        return 1
    print("\n文档一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
