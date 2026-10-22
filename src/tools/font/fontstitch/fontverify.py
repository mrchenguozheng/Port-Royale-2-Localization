#!/usr/bin/env python3
"""fontverify - optional quality checks for fonts produced by fontstitch.

Uses fontTools (pip install fonttools).  Three commands:

    python fontverify.py info FONT...
    python fontverify.py verify MERGED.ttf BASE.ttf LATIN.ttf [--sample N]
    python fontverify.py scale IN.ttf OUT.ttf UPM

`verify` compares a merged font against the exact base + donor pair it was built
from, so the donor must be the same (already subset) file that was merged.
`augment` checks its own Latin side, so verify is mostly useful for custom
pipelines.  `scale` rescales a font to a new units-per-em (it drops the kern
table, which would need rescaling too).
"""
import sys

from fontTools.ttLib import TTFont


def _load(path):
    return TTFont(path, checkChecksums=2, lazy=False)


def _same(A, B, ta, tb):
    ca, cb = A.getCoordinates(ta), B.getCoordinates(tb)
    return ca[0] == cb[0] and list(ca[1]) == list(cb[1]) and list(ca[2]) == list(cb[2])


def cmd_info(args):
    for p in args.files:
        f = _load(p)
        cmap = f.getBestCmap() or {}
        print(p)
        print("  glyphs %d | upm %d | cmap %d | tables %s"
              % (f["maxp"].numGlyphs, f["head"].unitsPerEm, len(cmap),
                 " ".join(sorted(k for k in f.keys() if k != "GlyphOrder"))))
        for nid in (1, 2, 4, 6):
            v = f["name"].getDebugName(nid)
            if v:
                print("  name%d: %s" % (nid, v))
    return 0


def cmd_verify(args):
    m, b, l = _load(args.merged), _load(args.base), _load(args.latin)
    mg, bg, lg = m["glyf"], b["glyf"], l["glyf"]
    mo, bo, lo = m.getGlyphOrder(), b.getGlyphOrder(), l.getGlyphOrder()
    nb = len(bo)

    problems = 0
    if len(mo) != nb + len(lo):
        print("ERROR glyph count %d != %d + %d" % (len(mo), nb, len(lo)))
        return 1

    bad_lat = [lo[i] for i in range(len(lo)) if not _same(lg[lo[i]], mg[mo[nb + i]], lg, mg)]
    bad_hmtx = [lo[i] for i in range(len(lo)) if l["hmtx"][lo[i]] != m["hmtx"][mo[nb + i]]]

    step = args.sample or (1 if nb < 12000 else 3)
    idxs = list(range(0, nb, step))
    bad_base = [bo[i] for i in idxs if not _same(bg[bo[i]], mg[mo[i]], bg, mg)]

    lc, bc, mc = l.getBestCmap() or {}, b.getBestCmap() or {}, m.getBestCmap() or {}
    lat_missing = [c for c in lc if c not in mc]
    lat_wrong = [c for c in lc if c in mc and mc[c] != mo[nb + lo.index(lc[c])]]
    base_missing = [c for c in bc if c not in mc]
    overridden = [c for c in bc if c in lc]

    print("merged %s" % args.merged)
    print("  glyphs      %d = %d base + %d latin" % (len(mo), nb, len(lo)))
    print("  cmap        %d code points" % len(mc))
    print("  latin       outlines bad: %d | metrics bad: %d | cmap missing: %d | wrong target: %d"
          % (len(bad_lat), len(bad_hmtx), len(lat_missing), len(lat_wrong)))
    print("  cjk         outlines bad: %d (checked %d/%d) | cmap missing: %d"
          % (len(bad_base), len(idxs), nb, len(base_missing)))
    print("  intentional latin overrides of base cmap: %d" % len(overridden))

    problems = len(bad_lat) + len(bad_hmtx) + len(lat_missing) + len(lat_wrong) + len(bad_base) + len(base_missing)
    if problems:
        for name in (bad_lat + bad_hmtx)[:10]:
            print("  ! latin glyph problem:", name)
        for name in bad_base[:10]:
            print("  ! cjk glyph problem:", name)
        print("RESULT: FAIL")
        return 1
    print("RESULT: OK")
    return 0


def cmd_scale(args):
    from fontTools.ttLib.scaleUpem import scale_upem
    f = TTFont(args.input, lazy=False)
    old = f["head"].unitsPerEm
    if "kern" in f:
        del f["kern"]
        print("note: kern table dropped before scaling (values would be wrong)")
    scale_upem(f, args.upm)
    f.save(args.output)
    print("scaled %s: %d -> %d upm, wrote %s" % (args.input, old, args.upm, args.output))
    return 0


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="fontverify", description="Quality checks for stitched fonts.")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("info", help="dump tables, name ids and coverage")
    i.add_argument("files", nargs="+")
    i.set_defaults(func=cmd_info)

    v = sub.add_parser("verify", help="compare glyphs against the two source fonts")
    v.add_argument("merged")
    v.add_argument("base")
    v.add_argument("latin")
    v.add_argument("--sample", type=int, default=0, help="check every Nth base glyph (default auto)")
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("scale", help="rescale outlines to another units-per-em")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("upm", type=int)
    s.set_defaults(func=cmd_scale)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())


