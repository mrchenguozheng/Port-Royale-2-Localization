# -*- coding: utf-8 -*-
"""Build a standalone translator workbench.

    python src\\tools\\pack\\make_translator.py

默认输出 dist\\PR2Translator；包内包含所有可编辑语言。

The package contains only:
- editor/server.py and editor/web (English UI);
- data/live/*.toml and the English/French references;
- a bundled Python runtime by default.

No build, injector, fonts, PR2Packs or install page.
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
EDITOR = os.path.join(ROOT, "editor")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
PY_SKIP = {
    "site-packages", "test", "tests", "idlelib", "tkinter", "turtledemo",
    "ensurepip", "lib2to3", "pydoc_data", "venv", "__pycache__",
}


def copy_tree(src, dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=IGNORE)


def copy_python_runtime(src, dst):
    """Copy a self-contained stdlib-only Python runtime on Windows."""
    src = os.path.abspath(src)
    if not os.path.isfile(os.path.join(src, "python.exe")):
        raise SystemExit("Python runtime has no python.exe: %s" % src)
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        path = os.path.join(src, name)
        if not os.path.isfile(path):
            continue
        keep = (name in ("python.exe", "pythonw.exe", "LICENSE.txt")
                or (name.startswith("python") and name.endswith(".dll"))
                or name.startswith("vcruntime"))
        if keep:
            shutil.copy2(path, os.path.join(dst, name))
    lib_src = os.path.join(src, "Lib")
    if not os.path.isdir(lib_src):
        raise SystemExit("Python runtime has no Lib/: %s" % src)
    shutil.copytree(lib_src, os.path.join(dst, "Lib"),
                    ignore=lambda _d, names: [n for n in names if n in PY_SKIP])
    dll_src = os.path.join(src, "DLLs")
    if os.path.isdir(dll_src):
        shutil.copytree(dll_src, os.path.join(dst, "DLLs"))
    probe = [os.path.join(dst, "python.exe"), "-S", "-c",
             "import http.server, tomllib, json; print('ok')"]
    r = subprocess.run(probe, capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise SystemExit("bundled Python failed: %s" % (r.stderr or r.stdout))


def write_start(stage, has_python):
    lines = ["@echo off", "setlocal", 'set "ROOT=%~dp0"']
    if has_python:
        lines.append('set "PY=%ROOT%python\\python.exe"')
    else:
        lines += [
            'set "PY=python"',
            '"%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" '
            ">nul 2>&1",
            "if errorlevel 1 goto :nopython",
        ]
    lines += [
        "echo.",
        "echo Starting PR2 Translator Workbench...",
        "echo.",
        f'"%PY%" "%ROOT%editor\\server.py" --data "%ROOT%data" '
        f'--web-dir "%ROOT%editor\\web" --port 8781',
        "endlocal",
        "exit /b 0",
        "",
    ]
    if not has_python:
        lines += [
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


def write_readme(stage, languages, has_python):
    text = """PR2 Translator Workbench
========================

Translate and proofread only. No build, injector, fonts or game launcher.

1. Extract this folder anywhere.
2. Double-click start.bat.
3. The browser opens the translation page.
4. Translate, then click Save changes.
5. Close the console window to stop.

Files:
  editor/server.py   local translation server
  editor/web/        English workbench UI
  shared/core/       shared translation storage/validation
  data/live/*.toml   translation files (%s)
  data/orig/         English and French references
  %s

The workbench listens on 127.0.0.1 only.
Return the edited data/live/<lang>.toml to the maintainer.
""" % (languages,
       "python/            bundled Python (no install needed)" if has_python
       else "Python 3.11+      required on PATH")
    with open(os.path.join(stage, "README.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def make(out, python_dir=None, system_python=False):
    live_dir = os.path.join(SRC, "live")
    codes = sorted(x[:-5] for x in os.listdir(live_dir)
                   if x.endswith(".toml") and not x.startswith("_")
                   and x != "keep_original.toml")
    if not codes:
        raise SystemExit("no editable language in %s" % live_dir)
    orig = os.path.join(SRC, "orig", "en.gog_1.1.2.3.toml")
    if not os.path.isfile(orig):
        raise SystemExit("missing %s" % orig)
    stage = os.path.abspath(out)
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)

    os.makedirs(os.path.join(stage, "editor"))
    shutil.copy2(os.path.join(EDITOR, "server.py"),
                 os.path.join(stage, "editor", "server.py"))
    copy_tree(os.path.join(EDITOR, "web"),
              os.path.join(stage, "editor", "web"))
    copy_tree(os.path.join(ROOT, "shared"),
              os.path.join(stage, "shared"))

    os.makedirs(os.path.join(stage, "data", "live"))
    os.makedirs(os.path.join(stage, "data", "orig"))
    for name in os.listdir(os.path.join(SRC, "live")):
        if name.endswith(".toml") and not name.startswith("_") \
                and name != "keep_original.toml":
            shutil.copy2(os.path.join(SRC, "live", name),
                         os.path.join(stage, "data", "live", name))
    for name in os.listdir(os.path.join(SRC, "orig")):
        if name.endswith(".toml"):
            shutil.copy2(os.path.join(SRC, "orig", name),
                         os.path.join(stage, "data", "orig", name))

    has_python = False
    if not system_python:
        src = os.path.abspath(python_dir) if python_dir else sys.base_prefix
        copy_python_runtime(src, os.path.join(stage, "python"))
        has_python = True

    write_start(stage, has_python)
    write_readme(stage, ", ".join(codes), has_python)
    print("built translator workbench: %s" % stage)
    print("  languages: %s" % ", ".join(codes))
    print("  start: %s\\start.bat" % stage)
    print("  python: %s" % ("bundled" if has_python else "system 3.11+"))
    return stage


def main():
    ap = argparse.ArgumentParser(description="Build a standalone translator workbench")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "PR2Translator"))
    ap.add_argument("--python-dir", default=None,
                    help="Python runtime to copy (default: current interpreter)")
    ap.add_argument("--system-python", action="store_true",
                    help="do not bundle Python")
    args = ap.parse_args()
    make(args.out, args.python_dir, args.system_python)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
