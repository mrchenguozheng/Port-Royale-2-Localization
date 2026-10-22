# -*- coding: utf-8 -*-
"""lint_imports.py —— 找出「用了但没导入」的全局名。

模块拆分（pr2ctl）之后最容易犯的错：函数里调了另一个模块的函数，
但本文件只写了 `from .base import *`，直到运行时才 NameError。
这个脚本静态扫一遍，提交前跑一次即可。

    python src/tools/lint_imports.py            # 默认扫 src/tools/pr2ctl/*.py
    python src/tools/lint_imports.py 文件...    # 扫指定文件

退出码：0 = 干净，1 = 有可疑名字。
"""

import ast
import builtins
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "pr2ctl")

BUILTINS = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "__package__"}


def module_names(path, cache, stack=()):
    """模块里可直接用的全局名（含相对星号导入展开）。"""
    if path in cache:
        return cache[path]
    if path in stack:                       # 循环导入，先给空集合
        return set()
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src, filename=path)
    names = set()
    stars = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            names |= target_names(n.targets)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
        elif isinstance(n, ast.Import):
            for a in n.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            if any(a.name == "*" for a in n.names):
                stars.append(n)
            for a in n.names:
                if a.name != "*":
                    names.add(a.asname or a.name)
    for st in stars:
        base = st.module or ""
        if st.level == 1 and base:
            sub = os.path.join(os.path.dirname(path), base + ".py")
            if os.path.isfile(sub):
                names |= module_names(sub, cache, stack + (path,))
    cache[path] = names
    return names


def target_names(targets):
    out = set()
    for t in targets:
        for x in ast.walk(t):
            if isinstance(x, ast.Name):
                out.add(x.id)
    return out


def local_names(fn):
    """函数体内所有会绑定名字的位置（参数、赋值、import、for、with、except、推导式…）。"""
    out = set()
    for a in list(fn.args.args) + list(fn.args.kwonlyargs) + \
             list(getattr(fn.args, "posonlyargs", [])):
        out.add(a.arg)
    if fn.args.vararg:
        out.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        out.add(fn.args.kwarg.arg)
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name != "*":
                    out.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n is not fn:
            out.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.Lambda):
            for a in list(n.args.args) + list(n.args.kwonlyargs) + \
                     list(getattr(n.args, "posonlyargs", [])):
                out.add(a.arg)
            if n.args.vararg:
                out.add(n.args.vararg.arg)
            if n.args.kwarg:
                out.add(n.args.kwarg.arg)
    return out


def check(path, cache):
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src, filename=path)
    globals_ = module_names(path, cache)
    problems = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        locals_ = local_names(fn)
        for x in ast.walk(fn):
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load):
                if x.id not in globals_ and x.id not in locals_ and x.id not in BUILTINS:
                    problems.append((fn.name, x.id, x.lineno))
    return problems


def main():
    args = sys.argv[1:]
    if args:
        files = [os.path.abspath(a) for a in args]
    else:
        files = sorted(os.path.join(PKG, f) for f in os.listdir(PKG)
                       if f.endswith(".py")) if os.path.isdir(PKG) else []
    if not files:
        print("没有可检查的文件")
        return 1

    cache = {}
    bad = 0
    for path in files:
        for fn, name, line in check(path, cache):
            bad += 1
            print("%s:%d  %s() 用了未定义的名字 %r"
                  % (os.path.relpath(path, HERE), line, fn, name))
    if bad:
        print("\n共 %d 处可疑引用。" % bad)
        return 1
    print("检查通过：%d 个文件，没有未定义的全局名。" % len(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
