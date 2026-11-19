#!/usr/bin/env python3
# coding: utf-8
"""tools_check.py —— 脚本地图（`src/tools/README.md`）的完整性检查。

三件事，都属于「加了脚本却没留痕迹」这一类：

1. 每个脚本都有模块 docstring —— 否则地图上只能看到文件名；
2. 每个脚本都出现在地图里 —— 否则下一次没人知道它存在；
3. 地图里写的每个 `目录/脚本.py` 都真的存在 —— 否则地图在骗人。

`__init__.py` 不算脚本，不查。退出码非 0 表示有问题。
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = os.path.join(HERE, "README.md")
PATH_RX = re.compile(r"`([a-z_]+/[a-z_0-9/]*\.py)`")


def scripts():
    out = []
    for dirpath, _dirnames, filenames in os.walk(HERE):
        for name in sorted(filenames):
            if name.endswith(".py") and name != "__init__.py":
                rel = os.path.relpath(os.path.join(dirpath, name), HERE)
                out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def main():
    with open(MAP, encoding="utf-8") as fh:
        text = fh.read()
    problems = []
    names = scripts()
    for rel in names:
        path = os.path.join(HERE, rel.replace("/", os.sep))
        try:
            doc = ast.get_docstring(ast.parse(open(path, encoding="utf-8").read()))
        except SyntaxError as exc:
            problems.append("%s：语法错误（%s）" % (rel, exc.msg))
            doc = None
        if not doc or not doc.strip():
            problems.append("%s：没有模块 docstring" % rel)
        if ("`%s`" % rel) not in text:
            problems.append("%s：没有出现在 src/tools/README.md" % rel)

    for hit in PATH_RX.findall(text):
        if not os.path.exists(os.path.join(HERE, hit)):
            problems.append("README 写了 %s，但文件不存在" % hit)

    if problems:
        print("脚本地图有 %d 处问题：" % len(problems))
        for p in problems:
            print("  " + p)
        return 1
    print("脚本地图一致：%d 个脚本，均有说明且路径可落地。" % len(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
