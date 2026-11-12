#!/usr/bin/env python
# coding: utf-8
"""quick.py —— 单条译文的快速修正路径。

用途：
    1. 从截图里看到的文本，先在译文/英文/法文里找候选 hash；
    2. 确认 hash 后，只改这一条，重新生成目标语言的 PR2Packs/<lang>.txt；
    3. 只把这个 .txt 复制进游戏目录，不重编字体、不复制 DLL/启动器。

它不改变 TOML 的格式，也不改变 compile_pack 的排版规则：
compile_pack 仍然是唯一的“译文 -> 引擎文本”生成器，只是被收进了
这条单条写入命令里。

用法：
    # 只查找，不改文件
    python src\\tools\\pack\\quick.py --lang zh --find "可惜你的信用额度"

    # 直接按 id 改并部署
    python src\\tools\\pack\\quick.py --lang zh --id 0xc4bde7d1 --text "新的译文"

    # 只找到一个候选时才允许 --find + --text
    python src\\tools\\pack\\quick.py --lang zh --find "完整的一句" --text "新的译文"

    # 只写入并构建，不复制到游戏
    python src\\tools\\pack\\quick.py --lang zh --id 0xc4bde7d1 --text "新的译文" --no-deploy

    # 给 agent 用：结构化输出
    python src\\tools\\pack\\quick.py --lang zh --find "..." --json

设计边界：
    * 不做全量 check_breaks、不做字体检查、不复制运行时；
    * 占位符 / 标签校验和 compile_pack 共用 shared\\core\\validate.py；
    * 写入后如果编译失败，会把原 TOML 还原，避免留下半成品；
    * 游戏目录不存在或写不进去时，构建产物仍保留，报告部署失败。
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tomllib
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))    # src\tools\pack
TOOLS = os.path.dirname(HERE)                       # src\tools
SRC = os.path.dirname(TOOLS)                        # src
ROOT = os.path.dirname(SRC)                         # 仓库根
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import translate as T                              # noqa: E402
from shared.core.validate import check_text        # noqa: E402
from text import toml_io as TI                     # noqa: E402
from build_artifacts import compile_pack           # noqa: E402
from compile_pack import KEEP_ORIGINAL             # noqa: E402
from install import pr2ctl as B                    # noqa: E402

PACK_OUT = os.path.join(ROOT, "build", "PR2Packs")
MAX_TEXT = 300
MAX_CANDIDATES = 8


def norm(value):
    """搜索用的宽松归一化：全半角、大小写、换行/竖线、连续空白。"""
    s = unicodedata.normalize("NFKC", str(value or "")).casefold()
    s = s.replace("<n>", " ")
    s = s.replace("|", " ")
    return re.sub(r"\s+", " ", s).strip()


def short(value, full=False):
    s = str(value or "")
    s = s.replace("\r", "").replace("\n", "\\n")
    if not full and len(s) > MAX_TEXT:
        return s[:MAX_TEXT] + "…"
    return s


def entry_fields(entry, lang):
    return (
        entry.get(lang) or "",
        entry.get(T.BASE_LANG) or "",
        entry.get(T.FR_LANG) or "",
    )


def score_entry(entry, query, lang):
    q = norm(query)
    if not q:
        return 0
    best = 0
    for value in entry_fields(entry, lang):
        n = norm(value)
        if not n:
            continue
        if q == n:
            best = max(best, 4)
        elif n.startswith(q) or n.endswith(q):
            best = max(best, 3)
        elif q in n:
            best = max(best, 2)
        elif len(q) >= 4 and n in q:
            best = max(best, 1)
    return best


def find_candidates(entries, query, lang, limit=MAX_CANDIDATES):
    """按中文/英文/法文模糊查找，返回 [(score, entry)]。"""
    scored = []
    for entry in entries:
        score = score_entry(entry, query, lang)
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda x: (-x[0], x[1].get("id", "")))
    return scored[:limit]


def normalize_id(value):
    hid = str(value or "").strip().lower()
    if hid and not hid.startswith("0x"):
        hid = "0x" + hid
    return hid


def entry_of(entries, hid):
    target = normalize_id(hid)
    for entry in entries:
        if (entry.get("id") or "").lower() == target:
            return entry
    return None


def describe(entry, lang, full=False):
    zh, en, fr = entry_fields(entry, lang)
    return {
        "id": entry.get("id", ""),
        "translation": short(zh, full),
        "en": short(en, full),
        "fr": short(fr, full),
    }


def print_candidate(entry, lang, full=False):
    out = describe(entry, lang, full)
    print("%s" % out["id"])
    print("  译文：%s" % out["translation"])
    print("  英文：%s" % out["en"])
    print("  法文：%s" % out["fr"])


def validate_new(entry, lang, text):
    """返回 (errors, warnings, problems)；规则与编辑器/编译脚本同一份。"""
    problems = check_text(text, entry.get(T.BASE_LANG, "") or "", lang=lang)
    errors = [p for p in problems if p.get("level") == "error"]
    warnings = [p for p in problems if p.get("level") == "warn"]
    return errors, warnings, problems


def restore(path, raw):
    """编译失败时把原 TOML 原子还原。"""
    tmp = path + ".quick-restore"
    with open(tmp, "wb") as fh:
        fh.write(raw)
    os.replace(tmp, path)


def keep_eol(path, raw):
    """按原文件的换行风格写回，避免一次单条修改把整个文件变成 LF。"""
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    if crlf <= lf:
        return
    with open(path, "rb") as fh:
        data = fh.read()
    if b"\r\n" in data:
        return
    tmp = path + ".quick-eol"
    with open(tmp, "wb") as fh:
        fh.write(data.replace(b"\n", b"\r\n"))
    os.replace(tmp, path)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pick_game_dir(explicit):
    if explicit:
        d = os.path.normpath(explicit)
        if not B.is_game_dir(d):
            raise ValueError("该目录里没有 %s：%s" % (B.GAME_EXE, d))
        return d
    settings = B.load_settings()
    cand = [settings.get("last_dir") or ""]
    cand += [rec.get("dir") or "" for rec in (settings.get("dirs") or {}).values()]
    for d in cand:
        if d and B.is_game_dir(d):
            return d
    raise ValueError("找不到游戏目录：用 --game-dir 指定，或先选一次游戏目录。")


def write_one(lang, entry, text, args):
    hid = entry.get("id", "")
    path = T.lang_path(lang)
    if not os.path.isfile(path):
        raise ValueError("没有译文文件：%s" % path)
    if lang in T.REFERENCE_LANGS:
        raise ValueError("%s 是只读参考语言，不能写入" % lang)
    if hid in KEEP_ORIGINAL:
        raise ValueError("%s 是必须原样保留英文的条目（%s）"
                         % (hid, KEEP_ORIGINAL[hid]))

    with open(path, "rb") as fh:
        raw = fh.read()
    with open(path, "rb") as fh:
        cur = tomllib.load(fh)
    if hid not in cur:
        raise ValueError("译文里没有 %s" % hid)
    order = TI.order_of(path) or list(cur)
    old = cur.get(hid, "")
    cur[hid] = text
    TI.write_doc_atomic(path, cur, order, TI.head_lines(path))
    keep_eol(path, raw)

    quiet = getattr(args, "json", False)
    if not quiet:
        print("\n── 编译 %s ──" % lang)
    rc = compile_pack(lang, PACK_OUT, no_fonts=True,
                      on_line=None if quiet else print)
    if rc != 0:
        restore(path, raw)
        raise ValueError("编译失败，已还原 %s" % path)

    pack = os.path.join(PACK_OUT, "%s.txt" % lang)
    if not os.path.isfile(pack):
        restore(path, raw)
        raise ValueError("编译没有生成 %s，已还原译文" % pack)

    return {
        "id": hid,
        "old": old,
        "new": text,
        "source": path,
        "pack": pack,
        "pack_sha256": sha256(pack),
    }


def deploy_one(lang, pack, game_dir):
    target = os.path.join(game_dir, B.PACK_DIR, "%s.txt" % lang)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    result = B.copy_if_different(pack, target)
    if result == "failed":
        raise ValueError("复制失败：%s（游戏可能正在运行）" % target)
    return {
        "deployed": target,
        "action": result,
        "sha256": sha256(target),
    }


def main():
    ap = argparse.ArgumentParser(description="单条译文快速查找/修正/部署")
    ap.add_argument("--lang", default="zh", help="目标语言，默认 zh")
    ap.add_argument("--find", default="", help="按截图/文本片段查找候选")
    ap.add_argument("--id", default="", help="直接指定 hash id")
    ap.add_argument("--text", default="", help="新译文；给出时才会写入")
    ap.add_argument("--game-dir", default="", help="游戏目录（含 PR2.exe）")
    ap.add_argument("--no-deploy", action="store_true", help="只写入/构建，不复制到游戏")
    ap.add_argument("--dry-run", action="store_true", help="只显示将要做什么，不改文件")
    ap.add_argument("--json", action="store_true", help="输出 JSON，供 agent 读取")
    ap.add_argument("--full", action="store_true", help="候选显示完整文本")
    ap.add_argument("--limit", type=int, default=MAX_CANDIDATES,
                    help="候选数量上限，默认 %d" % MAX_CANDIDATES)
    ap.add_argument("--force", action="store_true",
                    help="允许占位符/标签警告（默认拒绝）")
    args = ap.parse_args()

    def fail(message):
        if args.json:
            print(json.dumps({"ok": False, "error": message},
                             ensure_ascii=False, indent=2))
        else:
            print("\n[失败] " + message, file=sys.stderr)
        return 2

    if args.lang in T.REFERENCE_LANGS:
        return fail("%s 是只读参考语言，不能作为目标语言" % args.lang)

    if args.json:
        # translate.load_toml 会向 stderr 提示法语版本差异；JSON 模式
        # 只留 stdout 的结构化结果，避免调用方把提示当成 JSON。
        with contextlib.redirect_stderr(io.StringIO()):
            entries = T.entries(T.load_toml())
    else:
        entries = T.entries(T.load_toml())
    hid = normalize_id(args.id)
    entry = entry_of(entries, hid) if hid else None
    if hid and not entry:
        return fail("译文里没有这个 id：%s" % hid)

    # 1) 查找模式：给出候选后退出，不改任何文件
    if not entry and args.find:
        scored = find_candidates(entries, args.find, args.lang, args.limit)
        if not scored:
            return fail("没有找到匹配文本：%s" % args.find)
        candidates = [describe(e, args.lang, args.full) for _, e in scored]
        if args.json:
            print(json.dumps({"ok": True, "query": args.find,
                              "candidates": candidates},
                             ensure_ascii=False, indent=2))
            return 0
        print("找到 %d 个候选（按匹配强度）：" % len(scored))
        for _, e in scored:
            print()
            print_candidate(e, args.lang, args.full)
        if not args.text:
            print("\n确认 hash 后，用 --id <hash> --text <新译文> 写入。")
            return 0
        # --find + --text：只允许唯一候选，避免自动改错行
        if len(scored) != 1:
            return fail("有 %d 个候选，不能自动写入；先确认 --id。" % len(scored))
        entry = scored[0][1]

    if not entry:
        return fail("没有指定 --id，且 --find 没有唯一命中。")

    # 2) 只按 id 查看
    if not args.text:
        if args.json:
            print(json.dumps({"ok": True, "entry": describe(entry, args.lang, args.full)},
                             ensure_ascii=False, indent=2))
        else:
            print_candidate(entry, args.lang, args.full)
        return 0

    text = args.text
    errors, warnings, problems = validate_new(entry, args.lang, text)
    if not args.json:
        print("目标：%s" % entry.get("id", ""))
        print("旧译文：%s" % short(entry.get(args.lang) or "", args.full))
        print("新译文：%s" % short(text, args.full))
        for p in problems:
            print("  %s %s" % ("×" if p.get("level") == "error" else "!", p.get("text")))

    if errors or (warnings and not args.force):
        message = ("新译文有占位符/标签错误，未写入。" if errors
                   else "新译文有占位符/标签警告，未写入；确认无误可加 --force。")
        if args.json:
            print(json.dumps({
                "ok": False,
                "error": message,
                "id": entry.get("id", ""),
                "old": entry.get(args.lang) or "",
                "new": text,
                "problems": problems,
                "wrote": False,
            }, ensure_ascii=False, indent=2))
            return 2
        return fail(message)

    if args.dry_run:
        if args.json:
            print(json.dumps({
                "ok": True,
                "dry_run": True,
                "id": entry.get("id", ""),
                "old": entry.get(args.lang) or "",
                "new": text,
                "problems": problems,
            }, ensure_ascii=False, indent=2))
        else:
            print("\n[dry-run] 未写入。")
        return 0

    try:
        result = write_one(args.lang, entry, text, args)
    except (OSError, ValueError) as exc:
        return fail(str(exc))

    if not args.no_deploy:
        try:
            game_dir = pick_game_dir(args.game_dir)
        except ValueError as exc:
            return fail(str(exc) + "\n构建产物已保留；可加 --no-deploy 跳过复制。")
        try:
            result.update(deploy_one(args.lang, result["pack"], game_dir))
        except (OSError, ValueError) as exc:
            return fail(str(exc) + "\n构建产物已保留：%s" % result["pack"])

    if args.json:
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    else:
        print("\n完成：%s" % result["id"])
        print("  pack：%s" % result["pack"])
        if result.get("deployed"):
            print("  已复制：%s（%s）" % (result["deployed"], result["action"]))
            print("  重启游戏后生效。")
        else:
            print("  未复制到游戏；需要时手动复制，或去掉 --no-deploy。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
