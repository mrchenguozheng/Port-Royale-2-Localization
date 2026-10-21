# -*- coding: utf-8 -*-
"""apply_patch.py —— 开发流程用：一条命令把当前译文构建并打补丁到游戏目录。

做四件事，任何一步失败就停：

1. 归一化译文（normalize_text）
2. 校验换行/占位符（check_breaks --strict）
3. 编译语言包 + 字体（compile_pack）
4. 复制到游戏目录并核对（deploy + SHA-256 比对）

用法
----
    python src/tools/apply_patch.py                 # 构建 ja/zh 并部署到上次的游戏目录
    python src/tools/apply_patch.py --langs ja      # 只弄日语
    python src/tools/apply_patch.py --game-dir "<游戏目录>" --launch
    python src/tools/apply_patch.py --dry-run       # 只打印计划

游戏目录的确定顺序：--game-dir > 设置里的 last_dir > 「记住的版本」里第一个。
"""

import argparse
import hashlib
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import build_install as B  # noqa: E402
import zh_review  # noqa: E402

PACK_OUT = os.path.join(ROOT, "build", "PR2Packs")


def sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def run(step, cmd):
    print("\n── %s ──" % step)
    print("   " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        sys.exit("\n[失败] %s（退出码 %d）" % (step, proc.returncode))


def pick_langs(explicit):
    if explicit:
        return [x.strip() for x in explicit.split(",") if x.strip()]
    langs = [x for x in B.available_langs() if not x.startswith("test_")]
    return langs or ["ja"]


def pick_game_dir(explicit):
    if explicit:
        d = os.path.normpath(explicit)
        if not B.is_game_dir(d):
            sys.exit("该目录里没有 %s：%s" % (B.GAME_EXE, d))
        return d
    settings = B.load_settings()
    cand = [settings.get("last_dir") or ""]
    cand += [rec.get("dir") or "" for rec in (settings.get("dirs") or {}).values()]
    for d in cand:
        if d and B.is_game_dir(d):
            return d
    sys.exit("找不到游戏目录：用 --game-dir 指定，或先在 start.bat 里选一次。")


def spacy_python():
    explicit = os.environ.get("PR2_SPACY_PYTHON")
    if explicit:
        return explicit
    local = os.path.join(ROOT, ".venv-spacy", "Scripts", "python.exe")
    return local if os.path.isfile(local) else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="", help="逗号分隔，默认 ja,zh")
    ap.add_argument("--game-dir", default="", help="游戏目录（含 PR2.exe）")
    ap.add_argument("--no-normalize", action="store_true", help="跳过 normalize_text")
    ap.add_argument("--no-check", action="store_true", help="跳过 check_breaks")
    ap.add_argument("--no-fonts", action="store_true", help="编译时不重裁字体")
    ap.add_argument("--launch", action="store_true", help="部署完成后启动游戏")
    ap.add_argument("--dep", action="store_true",
                    help="中文：用依存句法给 ≥60 字的段落补空格（需要 .venv-spacy）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    args = ap.parse_args()

    langs = pick_langs(args.langs)
    target = pick_game_dir(args.game_dir)
    sha, build = B.identify_dir(target)

    print("游戏目录：%s" % target)
    print("版本：%s（SHA %s…）" % (B.version_label(sha), sha[:12]))
    print("语言：%s" % "、".join(langs))

    if "zh" in langs:
        import zh_review
        pend = zh_review.unsynced_edits()
        if pend:
            print("\n[停止] 编辑器里还有 %d 条人工修订没同步进文本源：" % len(pend))
            for h in sorted(pend)[:8]:
                print("   ", h)
            print("   先跑：python src/tools/zh_review.py --sync")
            print("   （--sync 会把人工改后的文字写回 references，并记进 docs/人工修订.csv）")
            return 2

    if args.dry_run:
        for lang in langs:
            print("\n[计划] %s" % lang)
            if not args.no_normalize:
                print("  normalize_text --lang %s" % lang)
            if not args.no_check:
                print("  check_breaks --lang %s --strict" % lang)
            print("  compile_pack --lang %s%s" % (lang, " --no-fonts" if args.no_fonts else ""))
        print("\n[计划] deploy -> %s（复制 %s）" % (target, "、".join(langs)))
        return 0

    # 1) 归一化 + 校验 + 编译
    for lang in langs:
        # 中文：先由 references/zh.gog_1.1.2.3.toml 生成 zh.toml（文本只改 references）
        if lang == "zh":
            ref = os.path.join(HERE, "..", "references", "zh.gog_1.1.2.3.toml")
            import zh_review
            if os.path.isfile(ref) and zh_review.marker_ok():
                print("   使用已审核的 zh.toml（文本源未变，跳过生成）")
            elif os.path.isfile(ref):
                run("生成 zh.toml（references/zh.gog_1.1.2.3.toml → 规则）",
                    [sys.executable, os.path.join(HERE, "apply_zh_rules.py")])
        if not args.no_normalize:
            cmd = [sys.executable, os.path.join(HERE, "normalize_text.py"), "--lang", lang]
            if lang == "ja":
                if has_module("janome") or has_module("fugashi"):
                    cmd.append("--particles")
                else:
                    print("   （未装 janome/fugashi，跳过助词空格判定；pip install -r requirements.txt 可补）")
            run("归一化 %s" % lang, cmd)
        if not args.no_check:
            run("校验换行 %s" % lang,
                [sys.executable, os.path.join(HERE, "check_breaks.py"), "--lang", lang, "--strict"])
        cmd = [sys.executable, os.path.join(HERE, "compile_pack.py"), "--lang", lang]
        if args.no_fonts:
            cmd.append("--no-fonts")
        run("编译 %s" % lang, cmd)

    if "zh" in langs:
        st = zh_review.status()
        if st.get("status") != "ok":
            n = st.get("count")
            print("\n   ⚠ 中文需要人工审核：%s" % (
                "还没有接受过审核稿" if n is None else "%d 条待看" % n))
            print("     跑 python src/tools/zh_review.py --diff 查看，"
                  "审完 --accept；改字用 --sync。")

    # 2) 注入器产物必须已在 build\ 里
    missing = [n for n in B.FLAT_FILES if not os.path.isfile(os.path.join(ROOT, "build", n))]
    if missing:
        sys.exit("缺少注入器产物：%s\n先运行 build_injector.bat（需要 Visual Studio）。"
                 % "、".join(missing))

    # 3) 部署
    print("\n── 部署到游戏目录 ──")
    ok, msg = B.deploy(target, langs)
    if not ok:
        sys.exit("[失败] " + msg)
    print("   " + msg.replace("\n", "\n   "))

    # 4) locale.ini 指向本次的主语言
    primary = langs[0]
    ini = os.path.join(target, B.PACK_DIR, "locale.ini")
    B.write_ini_language(ini, primary)

    # 5) 比对：构建产物 vs 游戏目录里实际文件
    print("\n── 核对 ──")
    bad = 0
    for lang in langs:
        src = os.path.join(PACK_OUT, "%s.txt" % lang)
        dst = os.path.join(target, B.PACK_DIR, "%s.txt" % lang)
        same = sha256(src) == sha256(dst) and os.path.isfile(dst)
        print("   %-24s %s" % ("PR2Packs\\%s.txt" % lang, "一致" if same else "不一致"))
        bad += 0 if same else 1
    for name in B.FLAT_FILES:
        src = os.path.join(ROOT, "build", name)
        dst = os.path.join(target, name)
        same = sha256(src) == sha256(dst)
        print("   %-24s %s" % (name, "一致" if same else "不一致"))
        bad += 0 if same else 1
    print("   %-24s %s" % ("locale.ini language", B.read_ini_language(ini) or "（空）"))
    if bad:
        sys.exit("\n[失败] %d 个文件与构建产物不一致" % bad)

    print("\n完成：%s 已应用（%s）。" % (target, "、".join(langs)))

    if args.launch:
        ok, msg = B.launch_game(target, primary)
        print(("启动：" if ok else "启动失败：") + msg)
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
