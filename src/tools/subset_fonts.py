#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""subset_fonts.py —— 用 fontstitch 把中文字形缝进游戏原版拉丁字体。

思路
----
游戏自带的四个 TTF（``assets/fonts/original/``）是纯拉丁字体，排版、字宽
和名字表都是原版的。本项目不再用「整个换成某个中文字体」的做法，而是：

    base（原版 TTF） + donor（中文/日文字体） → 只追加译文用到的字形

这样英文/法文的字形、字宽、kern 都不变，只是额外多了中文和日文字形。
缝合引擎就是本仓库自带的 ``fontstitch/``（从独立项目并入）。

用法
----
    python src\\tools\\subset_fonts.py            # 用全部译文用字重新缝合
    python src\\tools\\subset_fonts.py --force    # 忽略缓存，强制重缝
    python src\\tools\\subset_fonts.py --out D:\\fonts

依赖
----
需要 fontTools。默认解释器没装时会尝试 ``PR2_FONTTOOLS_SITE``，再试
``~/.workbuddy/binaries/python/envs/*/Lib/site-packages``。donor 路径来自
``src/tools/fontstitch/presets.toml``，可用 ``%WINDIR%`` 等变量。

缺 donor 或缺 fontTools 时只返回失败说明，不会把现有 build/fonts 覆盖成坏文件。
"""

import argparse
import hashlib
import json
import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(HERE)                       # 仓库的 src\
ROOT = os.path.dirname(SRC_DIR)                       # 仓库根
STRINGS = os.path.join(SRC_DIR, "live")
REFS = os.path.join(SRC_DIR, "orig")

DEFAULT_SRC = os.path.join(ROOT, "assets", "fonts", "original")
DEFAULT_OUT = os.path.join(ROOT, "build", "fonts")
FONTS = ("ARIAL.TTF", "ELGRECO_.TTF", "Tiepolo_black.ttf", "Tiepolo_bold.ttf")

STITCH_DIR = os.path.join(HERE, "fontstitch")
PRESETS = os.path.join(STITCH_DIR, "presets.toml")

#: 除了译文用字，还要保留的字符：ASCII、中文标点、数字全角等。
EXTRA = ("，。、；：！？…—～·「」『』“”《》【】（）〔〕〈〉［］％０１２３４５６７８９"
         "　￥· ‐–")

#: 装饰字体：主 donor 覆盖不到的字符（假名、部分标点）用宋体补。
SUPPLEMENT = {
    "ELGRECO_.TTF": [("%WINDIR%\\Fonts\\STZHONGS.TTF", 0)],
    "Tiepolo_black.ttf": [("%WINDIR%\\Fonts\\STZHONGS.TTF", 0)],
    "Tiepolo_bold.ttf": [("%WINDIR%\\Fonts\\STZHONGS.TTF", 0)],
}

#: 最后一层兜底：假名和少数标点。
FALLBACK = [("%WINDIR%\\Fonts\\NotoSansJP-VF.ttf", 0)]

STITCH_VERSION = 2


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


def text_files():
    out = []
    if os.path.isdir(REFS):
        out += sorted(os.path.join(REFS, f) for f in os.listdir(REFS) if f.endswith(".toml"))
    if os.path.isdir(STRINGS):
        out += sorted(os.path.join(STRINGS, f) for f in os.listdir(STRINGS) if f.endswith(".toml"))
    return out


def needed_chars():
    return toml_chars(text_files())


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


def _pairs():
    if not os.path.isfile(PRESETS):
        return {}
    doc = tomllib.load(open(PRESETS, "rb"))
    out = {}
    for p in doc.get("pair", []):
        out[p["game_file"]] = (p["donor_file"], int(p.get("donor_index", 0)))
    return out


def _upm(path, index=0):
    from fontTools.ttLib import TTFont
    f = TTFont(path, fontNumber=index, lazy=True)
    try:
        return f["head"].unitsPerEm
    finally:
        f.close()


def _resolve(path):
    return _fontstitch().resolve_path(path)


def _key(chars, donors, src):
    h = hashlib.sha1("".join(sorted(chars)).encode("utf-8")).hexdigest()
    rows = [STITCH_VERSION, h, len(chars)]
    for base in FONTS:
        p = os.path.join(src, base)
        try:
            s = os.stat(p)
            rows += [base, s.st_mtime_ns, s.st_size]
        except OSError:
            rows += [base, 0, 0]
        for donor, idx in donors.get(base, []):
            dp = _resolve(donor)
            try:
                s = os.stat(dp)
                rows += [base, os.path.basename(dp), s.st_mtime_ns, s.st_size, idx]
            except OSError:
                rows += [base, os.path.basename(dp), 0, 0, idx]
    return hashlib.sha1(json.dumps(rows).encode("utf-8")).hexdigest()


def _cache_path(out_dir):
    return os.path.join(out_dir, ".stitch.json")


def _load_cache(out_dir):
    try:
        with open(_cache_path(out_dir), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_cache(out_dir, data):
    try:
        cache = _cache_path(out_dir)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        tmp = cache + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, cache)
    except OSError:
        pass


def _stitch_one(base, out, donors, codes, log):
    """base 上追加 donors 的字形；返回 (missing, passes)。"""
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
    return missing, passes


def ensure_fonts(out_dir=None, src=None, log=None, force=False):
    """确保 build/fonts 覆盖当前全部用字；返回 (ok, 说明)。"""
    out_dir = out_dir or DEFAULT_OUT
    log = log or (lambda msg: None)
    chars = needed_chars()
    src = src or os.environ.get("PR2_ORIG_FONTS") or DEFAULT_SRC

    pairs = _pairs()
    donors = {}
    for name in FONTS:
        ds = []
        if name in pairs:
            ds.append(pairs[name])
        ds += SUPPLEMENT.get(name, [])
        ds.append(FALLBACK[0])
        seen, uniq = set(), []
        for item in ds:
            if item not in seen:
                seen.add(item)
                uniq.append(item)
        donors[name] = uniq

    key = _key(chars, donors, src)
    cache = _load_cache(out_dir)
    if not force and cache.get("key") == key and all(
            os.path.isfile(os.path.join(out_dir, f)) for f in FONTS):
        return True, "字体已是最新（%d 个用字），无需重缝" % len(chars)

    if not _fonttools():
        return False, ("缺 fontTools，字体未更新：python -m pip install fonttools，"
                       "或用 PR2_FONTTOOLS_SITE 指向已装好 fontTools 的 site-packages")
    if not os.path.isdir(src):
        return False, "找不到原版字体目录 %s" % src
    for name in FONTS:
        if not os.path.isfile(os.path.join(src, name)):
            return False, "缺少原版字体 %s" % os.path.join(src, name)

    os.makedirs(out_dir, exist_ok=True)
    codes = sorted(ord(c) for c in chars)
    log("字体缝合：%d 个用字，%d 个原版字体" % (len(codes), len(FONTS)))
    try:
        for name in FONTS:
            base = os.path.join(src, name)
            out = os.path.join(out_dir, name)
            log("  %s" % name)
            missing, _ = _stitch_one(base, out, donors[name], codes, log)
            if missing:
                log("   仍有 %d 个字符缺字形：%s" % (
                    len(missing), " ".join("U+%04X" % c for c in missing[:12])))
            log("   完成：%.1f KB" % (os.path.getsize(out) / 1024.0))
    except Exception as exc:
        return False, "字体缝合失败：%s" % exc

    _save_cache(out_dir, {"key": key, "chars": len(chars)})
    return True, "字体已重新缝合（%d 个用字）" % len(chars)


def main():
    ap = argparse.ArgumentParser(description="用 fontstitch 给原版字体补中文字形")
    ap.add_argument("--src", default="", help="原版拉丁字体目录")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录（默认 build\\fonts）")
    ap.add_argument("--force", action="store_true", help="忽略缓存，强制重缝")
    args = ap.parse_args()
    ok, msg = ensure_fonts(out_dir=args.out, src=args.src or None,
                           log=print, force=args.force)
    print(msg)
    if ok:
        print("把这里的 4 个 TTF 复制到 <游戏目录>\\fonts\\ 覆盖，重启游戏生效。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
