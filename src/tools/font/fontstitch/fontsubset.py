#!/usr/bin/env python3
"""fontsubset - keep only the characters you use.

Thin wrapper around fontTools' own subsetter (`fonttools subset` / `pyftsubset`).
All actual subsetting, layout pruning and table rewriting is done by
fontTools.subset; this script only adds a friendlier character input and a
before/after report with a "did every requested character survive" check.

    python fontsubset.py INPUT.ttf OUT.ttf --text "见字如面 2026 El Greco"
    python fontsubset.py INPUT.ttf OUT.ttf --text-file used.txt
    python fontsubset.py INPUT.ttf OUT.ttf --chars U+4E00-U+4E10,U+3000-303F

Requires fontTools (pip install fonttools).
"""
import argparse
import logging
import os
import sys
import time
import unicodedata

from fontTools import subset
from fontTools.ttLib import TTFont

logging.disable(logging.WARNING)


def normalize_ranges(spec):
    """'U+4E00-U+4E10,3000-303F' -> '4E00-4E10,3000-303F' (pyftsubset syntax)."""
    out = []
    for part in spec.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = a.strip(), b.strip()
        else:
            a, b = part, None
        for prefix in ("U+", "u+"):
            if a.startswith(prefix):
                a = a[2:]
            if b and b.startswith(prefix):
                b = b[2:]
        out.append(a if b is None else "%s-%s" % (a, b))
    return ",".join(out)


TEXT_EXTS = {".txt", ".json", ".csv", ".tsv", ".xml", ".yaml", ".yml", ".ini",
             ".cfg", ".lua", ".po", ".md", ".srt", ".ass", ".strings"}


def _decode_text(raw, encodings=("utf-8-sig", "utf-16", "gbk", "cp1252")):
    for enc in encodings:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None


def scan_paths(paths, encoding="auto"):
    """Collect every character used in the given text files / directories."""
    import glob
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in names:
                    if os.path.splitext(n)[1].lower() in TEXT_EXTS:
                        files.append(os.path.join(root, n))
        else:
            files.extend(glob.glob(p))
    chars, used, skipped = set(), 0, 0
    for f in files:
        try:
            if os.path.getsize(f) > 8 * 1024 * 1024:
                skipped += 1
                continue
            raw = open(f, "rb").read()
        except OSError:
            skipped += 1
            continue
        encs = ("utf-8-sig", "utf-16", "gbk", "cp1252") if encoding == "auto" else (encoding,)
        text = _decode_text(raw, encs)
        if text is None:
            skipped += 1
            continue
        used += 1
        chars.update(c for c in text if c not in "\r\n\t" and ord(c) >= 0x20)
    return chars, used, skipped


def gather_text(a):
    """All literal characters the user asked for (--text, --text-file, --scan)."""
    parts = []
    if a.text:
        parts.append(a.text)
    if a.text_file:
        with open(a.text_file, encoding=a.encoding) as f:
            parts.append(f.read())
    return "".join(parts).replace("\ufeff", "")


def requested_codes(a):
    codes = set()
    if a.text or a.text_file:
        codes.update(ord(c) for c in gather_text(a) if c not in "\r\n\t")
    if a.scan:
        chars, _, _ = scan_paths(a.scan, a.scan_encoding)
        codes.update(ord(c) for c in chars)
    if a.chars:
        for part in normalize_ranges(a.chars).split(","):
            if not part:
                continue
            if "-" in part:
                x, y = part.split("-", 1)
                codes.update(range(int(x, 16), int(y, 16) + 1))
            else:
                codes.add(int(part, 16))
    if a.keep_ascii:
        codes.update(range(0x20, 0x7F))
    return codes


def build_argv(a):
    argv = [a.input, "--output-file=" + a.output]
    text = gather_text(a)
    if a.scan:
        chars, _, _ = scan_paths(a.scan, a.scan_encoding)
        text += "".join(sorted(chars))
    if text:
        argv.append("--text=" + text)
    if a.chars:
        argv.append("--unicodes=" + normalize_ranges(a.chars))
    if a.keep_ascii:
        argv.append("--unicodes=20-7E")
    if a.game:
        # modern engine preset: no hinting (SDF / high-res raster), keep kerning
        argv += ["--layout-features=kern", "--drop-tables+=GSUB,GDEF", "--no-hinting",
                 "--name-IDs=1,2,4,6", "--notdef-outline", "--no-recalc-timestamp"]
    elif a.legacy:
        # GDI-era engine: keep hinting, keep kern, drop layout tables it never reads
        argv += ["--layout-features=", "--drop-tables+=GSUB,GPOS,GDEF", "--legacy-kern",
                 "--name-IDs=*", "--name-legacy", "--notdef-outline", "--no-recalc-timestamp"]
    elif a.minimal:
        argv += ["--layout-features=", "--drop-tables+=GSUB,GPOS,GDEF", "--no-hinting",
                 "--name-IDs=1,2,4,6", "--no-notdef-outline", "--no-recalc-timestamp"]
    else:
        if a.no_layout:
            argv += ["--layout-features=", "--drop-tables+=GSUB,GPOS,GDEF"]
        else:
            argv.append("--layout-features=*")
        if a.no_hinting:
            argv.append("--no-hinting")
        argv += ["--name-IDs=*", "--name-legacy", "--notdef-outline", "--no-recalc-timestamp"]
    if a.keep_kern and not a.minimal:
        argv.append("--legacy-kern")
    if a.keep_glyph_names:
        argv.append("--glyph-names")
    if a.flavor:
        argv.append("--flavor=" + a.flavor)
    if is_collection(a.input):
        argv.append("--font-number=%d" % a.index)
    return argv


def is_collection(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"ttcf"
    except OSError:
        return False


def report(a, codes):
    before = TTFont(a.input, fontNumber=a.index, lazy=True)
    after = TTFont(a.output, lazy=False)
    before_glyphs = before["maxp"].numGlyphs
    before_cmap = before.getBestCmap() or {}
    after_cmap = after.getBestCmap() or {}
    after_glyphs = after["maxp"].numGlyphs

    size_before = os.path.getsize(a.input)
    size_after = os.path.getsize(a.output)
    missing = sorted(c for c in codes
                     if c not in after_cmap and c != 0x20
                     and unicodedata.name(chr(c), None))
    blank = []
    if "glyf" in after:
        for c in codes:
            name = after_cmap.get(c)
            if name and c not in (0x20, 0xA0):
                if after["glyf"][name].numberOfContours == 0:
                    blank.append(c)

    print("input      : %s (%.2f MB, %d glyphs, %d code points)"
          % (a.input, size_before / 1048576, before_glyphs, len(before_cmap)))
    print("output     : %s (%.2f MB, %d glyphs, %d code points)"
          % (a.output, size_after / 1048576, after_glyphs, len(after_cmap)))
    print("requested  : %d unique code points" % len(codes))
    print("reduction  : %.1f%% of file, %.1f%% of glyphs"
          % (100 * (1 - size_after / max(size_before, 1)),
             100 * (1 - after_glyphs / max(before_glyphs, 1))))
    if a.missing_report:
        with open(a.missing_report, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join("U+%04X %s\n" % (c, chr(c)) for c in missing))
        print("missing    : %d written to %s" % (len(missing), a.missing_report))
    if missing:
        print("MISSING    : %d requested characters not in the source font: %s"
              % (len(missing), " ".join("U+%04X" % c for c in missing[:20])))
    if blank:
        print("EMPTY      : %d requested characters map to blank glyphs: %s"
              % (len(blank), " ".join("U+%04X" % c for c in blank[:20])))
    ok = not missing and not blank
    print("RESULT     :", "OK" if ok else "CHECK")
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="fontsubset", description="Keep only the glyphs you use.")
    p.add_argument("input", help="source font (.ttf/.otf/.ttc/.woff)")
    p.add_argument("output", help="subset font to write")
    p.add_argument("--text", help="characters used, as a literal string")
    p.add_argument("--text-file", help="file whose characters are all kept")
    p.add_argument("--encoding", default="utf-8-sig",
                   help="encoding of --text-file (default utf-8-sig; use gbk for GBK files)")
    p.add_argument("--missing-report", help="write every missing assigned character to this file")
    p.add_argument("--chars", help="code point ranges, e.g. U+4E00-U+9FFF,U+3000-303F")
    p.add_argument("--keep-ascii", dest="keep_ascii", action="store_true", default=True,
                   help="always keep printable ASCII (default)")
    p.add_argument("--no-keep-ascii", dest="keep_ascii", action="store_false",
                   help="drop ASCII unless it appears in --text/--chars")
    p.add_argument("--no-layout", action="store_true",
                   help="drop GSUB/GPOS/GDEF (smaller, loses kerning/ligatures)")
    p.add_argument("--no-hinting", action="store_true",
                   help="strip TrueType hinting (about 15%% smaller, softer at small sizes)")
    p.add_argument("--minimal", action="store_true",
                   help="shorthand for --no-hinting --no-layout plus slim name/notdef")
    p.add_argument("--legacy", action="store_true",
                   help="old GDI-era engine: keep hinting and kern, drop GSUB/GPOS/GDEF")
    p.add_argument("--game", action="store_true",
                   help="game embedding preset: no hinting, no layout, keep .notdef and core names")
    p.add_argument("--scan", nargs="+", metavar="PATH",
                   help="scan text files/directories and keep every character they contain")
    p.add_argument("--scan-encoding", default="auto",
                   choices=("auto", "utf-8", "utf-16", "gbk", "cp1252"),
                   help="encoding of scanned files (default: auto-detect)")
    p.add_argument("--no-kern", dest="keep_kern", action="store_false", default=True,
                   help="drop the legacy kern table (kept by default)")
    p.add_argument("--keep-glyph-names", action="store_true",
                   help="keep post glyph names (needed by some PDF tools)")
    p.add_argument("--flavor", choices=("woff", "woff2"), help="output flavor (woff2 needs brotli)")
    p.add_argument("--index", type=int, default=0, help="face index for .ttc input")
    p.add_argument("--verbose", action="store_true", help="print the pyftsubset invocation")
    a = p.parse_args(argv)

    if a.text and len(a.text) > 1500:
        print("note: --text is %d characters; prefer --text-file for large character sets" % len(a.text))
    codes = requested_codes(a)
    if not codes:
        print("error: no characters requested (use --text / --text-file / --chars)")
        return 1
    try:
        t0 = time.time()
        if a.verbose:
            print("fonttools subset " + " ".join(
                ('"%s"' % x if " " in x else x) for x in build_argv(a)))
        subset.main(build_argv(a))
    except SystemExit as e:
        if e.code not in (0, None):
            return int(e.code)
    except FileNotFoundError as e:
        print("error:", e)
        return 1
    except ImportError as e:
        print("error: %s (woff2 output needs the brotli package: pip install brotli)" % e)
        return 1
    print("elapsed    : %.2f s" % (time.time() - t0))
    return report(a, codes)


if __name__ == "__main__":
    raise SystemExit(main())
