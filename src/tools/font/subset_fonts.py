#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""subset_fonts.py —— 按语言把字形缝合进游戏原版拉丁字体。

术语
----
* **原版字体**：游戏自带的四个 TTF（``assets/fonts/original/``）。
* **donor**：提供字形的来源字体（系统/商业字体，不进仓库）。
* **按用字裁剪**：从 donor 中只取当前译文用到的字形，是缝合的内部步骤。
* **缝合**：把裁剪后的 donor 字形追加进原版字体。
* **重缝**：译文变化后重新执行一次缝合。

按语言分开
----------
每个语言一份配置：``fontstitch/presets/<语言>.toml``，互不影响。
字体也按语言分别生成到 ``build/fonts/<语言>/``，部署时只复制目标语言那一套。

    python src\\tools\\font\\subset_fonts.py --check
    python src\\tools\\font\\subset_fonts.py --lang zh --force
    python src\\tools\\font\\subset_fonts.py --all --force

依赖
----
需要 fontTools；缺了只返回说明，不会把已有字体覆盖成坏文件。
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import threading
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
SRC_DIR = os.path.dirname(TOOLS)                       # 仓库的 src\
ROOT = os.path.dirname(SRC_DIR)                       # 仓库根
STRINGS = os.path.join(SRC_DIR, "live")

DEFAULT_SRC = os.path.join(ROOT, "assets", "fonts", "original")
DEFAULT_OUT = os.path.join(ROOT, "build", "fonts")
FONTS = ("ARIAL.TTF", "ELGRECO_.TTF", "Tiepolo_black.ttf", "Tiepolo_bold.ttf")

STITCH_DIR = os.path.join(TOOLS, "font", "fontstitch")
PRESETS_DIR = os.path.join(STITCH_DIR, "presets")
PRESETS_EXAMPLE = os.path.join(STITCH_DIR, "presets.example.toml")

EXTRA = ("，。、；：！？…—～·「」『』“”《》【】（）〔〕〈〉［］％０１２３４５６７８９"
         "　￥· ‐–")
STITCH_VERSION = 4


def toml_chars(paths):
    chars = set(chr(c) for c in range(0x20, 0x7F))
    for path in paths:
        if not os.path.isfile(path):
            continue
        doc = tomllib.load(open(path, "rb"))
        for v in doc.values():
            if isinstance(v, str):
                chars.update(v)
    chars.update(EXTRA)
    return chars


def needed_chars(langs):
    return toml_chars([os.path.join(STRINGS, lang + ".toml") for lang in langs])


def _fonttools():
    site = os.environ.get("PR2_FONTTOOLS_SITE")
    if site and site not in sys.path:
        sys.path.insert(0, site)
    try:
        import fontTools  # noqa: F401
        return True
    except ImportError:
        pass
    import glob
    for cand in glob.glob(os.path.expanduser(
            r"~\.workbuddy\binaries\python\envs\*\Lib\site-packages")):
        if os.path.isdir(os.path.join(cand, "fontTools")):
            sys.path.insert(0, cand)
            try:
                import fontTools  # noqa: F401
                return True
            except ImportError:
                continue
    return False


def _fontstitch():
    if STITCH_DIR not in sys.path:
        sys.path.insert(0, STITCH_DIR)
    import fontstitch
    return fontstitch


def preset_path(lang):
    return os.path.join(PRESETS_DIR, lang + ".toml")


def list_presets():
    if not os.path.isdir(PRESETS_DIR):
        return []
    return sorted(n[:-5] for n in os.listdir(PRESETS_DIR)
                  if n.endswith(".toml"))


def load_preset(lang, game_file=None):
    """返回 (donors, fallback)；可按 game_file 过滤。"""
    path = preset_path(lang)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    doc = tomllib.load(open(path, "rb"))
    donors = []
    for key in ("pair", "supplement"):
        for p in doc.get(key, []):
            if game_file and p.get("game_file") != game_file:
                continue
            if p.get("donor_file"):
                donors.append((p["donor_file"], int(p.get("donor_index", 0))))
    fb = doc.get("fallback") or {}
    fallback = None
    if fb.get("donor_file"):
        fallback = (fb["donor_file"], int(fb.get("donor_index", 0)))
    return donors, fallback


_PRESETS_LOCK = threading.Lock()


def add_language_presets(code, template=None):
    """给新语言复制一份 ``presets/<code>.toml``，返回 {"added", "source"}。"""
    code = (code or "").strip()
    if not code:
        raise ValueError("语言代码为空")
    with _PRESETS_LOCK:
        dst = preset_path(code)
        if os.path.isfile(dst):
            return {"added": False, "source": None, "path": dst}
        os.makedirs(PRESETS_DIR, exist_ok=True)
        source = None
        for cand in (template, "zh"):
            cand_path = preset_path(cand) if cand else ""
            if cand_path and os.path.isfile(cand_path):
                source = cand_path
                break
        if not source and os.path.isfile(PRESETS_EXAMPLE):
            source = PRESETS_EXAMPLE
        if not source:
            raise ValueError("缺少 presets.example.toml，无法生成字体配置")
        shutil.copyfile(source, dst)
        return {"added": True,
                "source": os.path.basename(source)[:-5], "path": dst}


def _upm(path, index=0):
    from fontTools.ttLib import TTFont
    f = TTFont(path, fontNumber=index, lazy=True)
    try:
        return f["head"].unitsPerEm
    finally:
        f.close()


def _resolve(path):
    return _fontstitch().resolve_path(path)


def _donors_for(lang, game_file):
    donors, fallback = load_preset(lang, game_file)
    out = list(donors)
    if fallback:
        out.append(fallback)
    seen, uniq = set(), []
    for item in out:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def _key(lang, chars, donors, src):
    h = hashlib.sha1("".join(sorted(chars)).encode("utf-8")).hexdigest()
    rows = [STITCH_VERSION, lang, h, len(chars)]
    for name in FONTS:
        p = os.path.join(src, name)
        try:
            s = os.stat(p)
            rows += [name, s.st_mtime_ns, s.st_size]
        except OSError:
            rows += [name, 0, 0]
    for donor, idx in donors:
        p = _resolve(donor)
        try:
            s = os.stat(p)
            rows += [os.path.basename(p), s.st_mtime_ns, s.st_size, idx]
        except OSError:
            rows += [os.path.basename(p), 0, 0, idx]
    return hashlib.sha1(json.dumps(rows).encode("utf-8")).hexdigest()


def _load_cache(lang_dir):
    try:
        with open(os.path.join(lang_dir, ".stitch.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_cache(lang_dir, data):
    try:
        path = os.path.join(lang_dir, ".stitch.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def _write_notice(out_dir):
    text = (
        "这些字体是衍生作品：游戏原版拉丁字体 + 商业/系统 donor 字体。\n"
        "只允许在本机自用；禁止再分发、上传、打包进发布物或提交到仓库。\n"
    )
    try:
        with open(os.path.join(out_dir, "不要分发.txt"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except OSError:
        pass


def _stitch_one(base, out, donors, codes, log):
    cur = base
    temps = []
    upm = _upm(base)
    missing = []
    passes = 0
    for donor, index in donors:
        dp = _resolve(donor)
        if not os.path.isfile(dp):
            log("   跳过 donor（不存在）：%s" % dp)
            continue
        donor_upm = _upm(dp, index)
        if donor_upm != upm:
            log("   跳过 donor（UPM %d ≠ %d）：%s" % (donor_upm, upm, dp))
            continue
        tmp = out + ".p%d" % passes
        try:
            r = _fontstitch().augment(cur, dp, tmp, codes, donor_index=index)
        except ValueError as exc:
            log("   跳过 donor（没有可补字符）：%s" % exc)
            continue
        if r["latin_changed"] or r["base_cmap_moved"]:
            raise ValueError("donor %s 改动了原版字形/映射" % dp)
        temps.append(tmp)
        cur = tmp
        missing = r["missing"]
        passes += 1
        log("   追加 %-20s +%d 字形，缺 %d" % (
            os.path.basename(dp), r["chars_added"], len(missing)))
        if not missing:
            break
    if cur == base:
        raise ValueError("没有可用的 donor")
    os.replace(cur, out)
    for t in temps:
        if os.path.exists(t):
            os.remove(t)
    return missing


def ensure_fonts(out_dir=None, langs=None, src=None, log=None, force=False):
    """按语言生成 build/fonts/<语言>/；返回 (ok, 说明)。"""
    out_dir = out_dir or DEFAULT_OUT
    log = log or (lambda msg: None)
    src = src or os.environ.get("PR2_ORIG_FONTS") or DEFAULT_SRC

    wanted = [l for l in (langs or list_presets()) if l]
    if not wanted:
        return False, ("没有找到语言配置：请在 fontstitch/presets/ 下放 "
                       "<语言>.toml（可从 presets.example.toml 复制）")

    if not _fonttools():
        return False, ("缺 fontTools，字体未更新：python -m pip install fonttools，"
                       "或用 PR2_FONTTOOLS_SITE 指向已装好 fontTools 的 site-packages")
    if not os.path.isdir(src):
        return False, "找不到原版字体目录 %s" % src
    for name in FONTS:
        if not os.path.isfile(os.path.join(src, name)):
            return False, "缺少原版字体 %s" % os.path.join(src, name)

    done, failed = [], []
    for lang in wanted:
        if not os.path.isfile(preset_path(lang)):
            log("  %s：缺 presets/%s.toml，跳过" % (lang, lang))
            failed.append(lang)
            continue
        try:
            chars = needed_chars([lang])
            codes = sorted(ord(c) for c in chars)
            lang_dir = os.path.join(out_dir, lang)
            key = _key(lang, chars, _donors_for(lang, None), src)
            cache = _load_cache(lang_dir)
            if (not force and cache.get("key") == key and all(
                    os.path.isfile(os.path.join(lang_dir, f)) for f in FONTS)):
                log("  %s：已是最新（%d 个用字）" % (lang, len(chars)))
                done.append(lang)
                continue
            os.makedirs(lang_dir, exist_ok=True)
            log("  %s：%d 个用字" % (lang, len(chars)))
            for name in FONTS:
                base = os.path.join(src, name)
                out = os.path.join(lang_dir, name)
                log("    %s" % name)
                missing = _stitch_one(base, out, _donors_for(lang, name), codes, log)
                if missing:
                    log("      仍有 %d 个字符缺字形：%s" % (
                        len(missing), " ".join("U+%04X" % c for c in missing[:12])))
            _save_cache(lang_dir, {"key": key, "chars": len(chars)})
            _write_notice(lang_dir)
            done.append(lang)
        except Exception as exc:
            log("  %s：失败 %s" % (lang, exc))
            failed.append(lang)

    if failed and not done:
        return False, "字体缝合失败：%s" % "、".join(failed)
    msg = "字体已处理：%s" % "、".join(done)
    if failed:
        msg += "；失败/跳过：%s" % "、".join(failed)
        return False, msg
    log("注意：缝合字体只限本机自用，不要分发/上传/打包。")
    return True, msg


def check_prereqs(langs=None):
    """检查原版字体、donor、fontTools；返回 (信息行, 问题行)。"""
    src = os.environ.get("PR2_ORIG_FONTS") or DEFAULT_SRC
    selected = langs or list_presets()
    info, bad = [], []
    info.append("已配置语言：%s" % ("、".join(selected) if selected else "（无）"))
    if not selected:
        bad.append("没有 presets/<语言>.toml；可从 presets.example.toml 复制")
    for lang in selected:
        if not os.path.isfile(preset_path(lang)):
            bad.append("缺 presets/%s.toml" % lang)
            continue
        donors, fallback = load_preset(lang)
        if not donors:
            bad.append("%s 没有 [[pair]] donor" % lang)
        for donor, _idx in donors:
            p = _resolve(donor)
            if not os.path.isfile(p):
                bad.append("缺 donor %s（%s 需要）" % (p, lang))
    for name in FONTS:
        if not os.path.isfile(os.path.join(src, name)):
            bad.append("缺原版字体 %s（用 extract_fonts.py 从游戏导出）" % name)
    if not _fonttools():
        bad.append("缺 fontTools（pip install fonttools，或设 PR2_FONTTOOLS_SITE）")
    return info, bad


def main():
    ap = argparse.ArgumentParser(description="按语言缝合游戏字体")
    ap.add_argument("--src", default="", help="原版拉丁字体目录")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出根目录（默认 build\\fonts）")
    ap.add_argument("--lang", action="append", default=[],
                    help="只处理这个语言，可重复")
    ap.add_argument("--all", action="store_true", help="处理 presets/ 下全部语言")
    ap.add_argument("--force", action="store_true", help="忽略缓存，强制重缝")
    ap.add_argument("--check", action="store_true", help="只检查前置条件")
    args = ap.parse_args()
    langs = args.lang or None
    if args.check:
        info, bad = check_prereqs(langs)
        for line in info:
            print(line)
        for line in bad:
            print("缺少：" + line)
        if bad:
            return 1
        print("字体缝合前置条件齐全。")
        return 0
    ok, msg = ensure_fonts(out_dir=args.out, langs=langs,
                           src=args.src or None, log=print, force=args.force)
    print(msg)
    if ok:
        print("部署时只复制目标语言那一套：build\\fonts\\<语言>\\")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
