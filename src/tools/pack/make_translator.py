# -*- coding: utf-8 -*-
"""make_translator.py —— 生成“译者工作台”分发包。

译者只需要解压后双击 start.bat：
- 只启动翻译编辑器；
- 只带当前语言、原文参考、术语表；
- 不带构建、部署、字体、注入器产物。

用法：
    python src\\tools\\pack\\make_translator.py --lang ko --out dist\\PR2Translator-ko

默认会复制当前 Python 运行时，译者不需要安装 Python。
    python src\\tools\\pack\\make_translator.py --lang ko --out dist\\PR2Translator-ko

用自定义 Python：
    python src\\tools\\pack\\make_translator.py --lang ko --out dist\\PR2Translator-ko ^
        --python-dir C:\\Python311

不内置 Python：
    python src\\tools\\pack\\make_translator.py --lang ko --out dist\\PR2Translator-ko ^
        --system-python
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def copy_tree(src, dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=IGNORE)


PY_KEEP_DIRS = {
    "site-packages", "test", "tests", "idlelib", "tkinter", "turtledemo",
    "ensurepip", "lib2to3", "pydoc_data", "venv", "__pycache__",
}
PY_KEEP_ROOT = ("python.exe", "pythonw.exe", "LICENSE.txt")


def copy_python_runtime(src, dst):
    """复制一份可独立运行的标准库 Python（Windows）。

    不复制 site-packages / test / tkinter 等，只保留 http.server、
    tomllib、json、ctypes 等编辑器需要的标准库。
    """
    src = os.path.abspath(src)
    exe = os.path.join(src, "python.exe")
    if not os.path.isfile(exe):
        raise SystemExit("Python 运行时里没有 python.exe: %s" % src)
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        sp = os.path.join(src, name)
        if os.path.isfile(sp):
            if name in PY_KEEP_ROOT or name.startswith("python") and name.endswith(".dll") \
                    or name.startswith("vcruntime"):
                shutil.copy2(sp, os.path.join(dst, name))
    lib_src = os.path.join(src, "Lib")
    lib_dst = os.path.join(dst, "Lib")
    if not os.path.isdir(lib_src):
        raise SystemExit("Python 运行时缺少 Lib/: %s" % src)
    def ignore(_dir, names):
        return [n for n in names if n in PY_KEEP_DIRS]
    shutil.copytree(lib_src, lib_dst, ignore=ignore)
    dll_src = os.path.join(src, "DLLs")
    if os.path.isdir(dll_src):
        shutil.copytree(dll_src, os.path.join(dst, "DLLs"))
    # 验证：不用系统 Python，直接跑包里的解释器。
    probe = [os.path.join(dst, "python.exe"), "-S", "-c",
             "import http.server, tomllib, json, ctypes; print('ok')"]
    try:
        r = subprocess.run(probe, capture_output=True, text=True, timeout=15)
    except Exception as exc:
        raise SystemExit("内置 Python 复制后无法运行：%s" % exc)
    if r.returncode != 0:
        raise SystemExit("内置 Python 复制后无法运行：%s" % (r.stderr or r.stdout))


def write_start(stage, lang, has_python):
    lines = [
        "@echo off",
        "setlocal",
        'set "ROOT=%~dp0"',
    ]
    if has_python:
        lines += [
            'set "PY=%ROOT%python\\python.exe"',
        ]
    else:
        lines += [
            'call "%ROOT%src\\find_python.bat"',
            'if not defined PY goto :nopython',
        ]
    lines += [
        f'start "" "%PY%" "%ROOT%src\\editor\\server.py" --translator '
        f'--translator-lang {lang} --open-page /translate/{lang} --restart',
        "endlocal",
        "exit /b 0",
        "",
        ":nopython",
        "echo.",
        "echo PR2 Translator needs Python 3.11+.",
        "echo Install it from https://www.python.org/downloads/",
        "echo and tick Add python.exe to PATH.",
        "pause",
        "endlocal",
        "exit /b 0",
        "",
    ]
    with open(os.path.join(stage, "start.bat"), "w",
              encoding="ascii", newline="\r\n") as fh:
        fh.write("\n".join(lines))


def write_readme(stage, lang, has_python):
    text = """PR2 Translator - %s
========================

只需要翻译和校对，不需要编译器、Node.js、fontTools 或注入器。

1. 解压到任意目录；
2. 双击 start.bat；
3. 浏览器会自动打开翻译页；
4. 翻译并保存；
5. 关闭控制台窗口或 Ctrl+C 停止服务。

这个包只有：
  - 翻译编辑器
  - live/%s.toml
  - 英文原文参考
  - 术语表
  %s

没有构建、部署、字体或游戏启动功能。
把修改后的文件交回维护者，由维护者构建和发行。
""" % (lang, lang, "Python：已内置，无需安装。" if has_python else "Python：需要系统安装 Python 3.11+。")
    with open(os.path.join(stage, "README.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def make(lang, out, python_dir=None, system_python=False):
    live = os.path.join(SRC, "live", lang + ".toml")
    if not os.path.isfile(live):
        raise SystemExit("找不到 %s；先创建该语言的译文文件。" % live)
    stage = os.path.abspath(out)
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)

    # 编辑器后端 + 已构建前端，不复制 node_modules。
    os.makedirs(os.path.join(stage, "src", "editor"))
    shutil.copy2(os.path.join(SRC, "editor", "server.py"),
                 os.path.join(stage, "src", "editor", "server.py"))
    copy_tree(os.path.join(SRC, "editor", "dist"),
              os.path.join(stage, "src", "editor", "dist"))

    # 编辑器依赖的工具；只保留运行所需源码（复制整棵 tools 仍很小，
    # 但避免以后漏模块）。
    copy_tree(os.path.join(SRC, "tools"), os.path.join(stage, "src", "tools"))
    shutil.copy2(os.path.join(SRC, "find_python.bat"),
                 os.path.join(stage, "src", "find_python.bat"))

    # 只带当前语言和 keep_original，避免把其他译文一起发给译者。
    live_out = os.path.join(stage, "src", "live")
    os.makedirs(live_out)
    shutil.copy2(live, os.path.join(live_out, lang + ".toml"))
    keep = os.path.join(SRC, "live", "keep_original.toml")
    if os.path.isfile(keep):
        shutil.copy2(keep, os.path.join(live_out, "keep_original.toml"))

    # 原文参考与 seed（有就带）。
    for name in ("orig", "seed"):
        src = os.path.join(SRC, name)
        if os.path.isdir(src):
            copy_tree(src, os.path.join(stage, "src", name))

    # 术语表（编辑器会读 terms.toml / placeholder_meanings.toml）。
    glossary = os.path.join(ROOT, "glossary")
    if os.path.isdir(glossary):
        copy_tree(glossary, os.path.join(stage, "glossary"))

    has_python = False
    if not system_python:
        src = os.path.abspath(python_dir) if python_dir else sys.base_prefix
        if not os.path.isfile(os.path.join(src, "python.exe")):
            raise SystemExit("找不到可复制的 Python：%s" % src)
        copy_python_runtime(src, os.path.join(stage, "python"))
        has_python = True

    write_start(stage, lang, has_python)
    write_readme(stage, lang, has_python)
    print("已生成译者工作台：%s" % stage)
    print("  语言：%s" % lang)
    print("  启动：双击 %s\\start.bat" % stage)
    print("  Python：%s" % ("已内置" if has_python else "使用系统 Python 3.11+"))
    return stage


def main():
    ap = argparse.ArgumentParser(description="生成译者工作台分发包")
    ap.add_argument("--lang", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--python-dir", default=None,
                    help="复制这份 Python 运行时（默认当前 Python）")
    ap.add_argument("--system-python", action="store_true",
                    help="不内置 Python，使用系统 Python 3.11+")
    args = ap.parse_args()
    make(args.lang, args.out, args.python_dir, args.system_python)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
