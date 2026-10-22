#!/usr/bin/env python3
"""fontstitch - graft CJK glyphs into a Latin font (game font localisation).

Keeps the original Latin glyphs, metrics and name table untouched; adds only the
Chinese characters the translation needs.  The `augment` command handles the
subsetting of the donor font and verifies the Latin side afterwards.

    python fontstitch.py augment LATIN.ttf CJK.ttf OUT.ttf --text-file used.txt
    python fontstitch.py augment LATIN.ttf CJK.ttc OUT.ttf --scan text/ --donor-index 0
    python fontstitch.py extract COLLECTION.ttc INDEX OUT.ttf
    python fontstitch.py validate FONT.ttf

`augment` needs fontTools; `extract` and `validate` are standard-library only.
"""
"""Merge all glyphs/cmap entries of a Latin TTF into a CJK TTF (glyf, same UPM).

Pure stdlib: no fontTools available offline.
Usage: python merge_ttf.py base.ttf latin.ttf out.ttf
"""
import struct, sys, os, re

def u16(b, o): return struct.unpack_from(">H", b, o)[0]
def s16(b, o): return struct.unpack_from(">h", b, o)[0]
def u32(b, o): return struct.unpack_from(">I", b, o)[0]
def p16(v): return struct.pack(">H", v & 0xFFFF)
def ps16(v): return struct.pack(">h", v)
def p32(v): return struct.pack(">I", v & 0xFFFFFFFF)

def read_tables(data):
    n = u16(data, 4)
    t = {}
    for i in range(n):
        o = 12 + 16 * i
        tag = data[o:o+4].decode("latin-1")
        off, ln = u32(data, o + 8), u32(data, o + 12)
        t[tag] = (off, ln)
    return t


_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def resolve_path(value):
    """Expand %VAR%, ${VAR}, ${VAR:-default}, $VAR and ~ in a path.

    Relative paths are left relative (resolved against the current working
    directory when opened), so relative paths stay portable.
    """
    if not value:
        return value
    def sub(m):
        name, default = m.group(1), m.group(2)
        return os.environ.get(name) or (default if default is not None else m.group(0))
    value = _VAR_RE.sub(sub, value)
    value = os.path.expandvars(value)
    value = os.path.expanduser(value)
    if "%" in value or "${" in value:
        raise ValueError("unresolved environment variable in path: %r" % value)
    return os.path.normpath(value)


class Sfnt:
    def __init__(self, path):
        self.path = resolve_path(path)
        self.data = open(self.path, "rb").read()
        self.tabs = read_tables(self.data)
        self.upm = u16(self.data, self.tabs["head"][0] + 18)
        self.numGlyphs = u16(self.data, self.tabs["maxp"][0] + 4)
        self.loca = self._loca()
        self.hmtx = self._hmtx()
        self.cmap = self._cmap()

    def _loca(self):
        d, t = self.data, self.tabs
        fmt = s16(d, t["head"][0] + 50)
        lo = t["loca"][0]
        if fmt == 0:
            return [u16(d, lo + 2 * i) * 2 for i in range(self.numGlyphs + 1)]
        return [u32(d, lo + 4 * i) for i in range(self.numGlyphs + 1)]

    def _hmtx(self):
        d, t = self.data, self.tabs
        n = u16(d, t["hhea"][0] + 34)
        ho = t["hmtx"][0]
        out = []
        adv = 0
        for i in range(self.numGlyphs):
            if i < n:
                adv, lsb = u16(d, ho + 4 * i), s16(d, ho + 4 * i + 2)
            else:
                lsb = s16(d, ho + 4 * n + 2 * (i - n))
            out.append((adv, lsb))
        return out

    def _cmap(self):
        d, t = self.data, self.tabs
        res = {}
        if "cmap" not in t:
            return res
        co = t["cmap"][0]
        n = u16(d, co + 2)
        found = []
        for i in range(n):
            pid, eid, off = struct.unpack_from(">HHI", d, co + 4 + 8 * i)
            o = co + off
            found.append((pid, eid, u16(d, o), o))
        # only trust Windows/Unicode subtables; Mac (1,x) tables use legacy encodings
        PRIORITY = [(3, 10, 12), (3, 1, 4), (0, 4, 12), (0, 3, 4), (0, 6, 12)]
        best = None
        for want in PRIORITY:
            for pid, eid, fmt, o in found:
                if (pid, eid, fmt) == want:
                    best = (o, fmt); break
            if best:
                break
        if not best:                                  # last resort: Unicode-capable only
            for pid, eid, fmt, o in found:
                if pid != 1 and fmt in (4, 12):
                    best = (o, fmt); break
        if not best:
            return res
        o, fmt = best
        if fmt == 12:
            ng = u32(d, o + 12)
            for i in range(ng):
                sc, ec, sg = struct.unpack_from(">III", d, o + 16 + 12 * i)
                for c in range(sc, ec + 1):
                    res[c] = sg + (c - sc)
        else:
            segX2 = u16(d, o + 6); seg = segX2 // 2
            end = o + 14; start = end + segX2 + 2
            delta = start + segX2; ro = delta + segX2
            for s in range(seg):
                e, st = u16(d, end + 2 * s), u16(d, start + 2 * s)
                if st == 0xFFFF: continue
                dd, r = s16(d, delta + 2 * s), u16(d, ro + 2 * s)
                for c in range(st, e + 1):
                    if r == 0:
                        g = (c + dd) & 0xFFFF
                    else:
                        gi = ro + 2 * s + r + 2 * (c - st)
                        if gi + 2 > len(d): continue
                        g = u16(d, gi)
                        if g: g = (g + dd) & 0xFFFF
                    if g: res[c] = g
        return res

    def glyph(self, i):
        o = self.tabs["glyf"][0] + self.loca[i]
        e = self.tabs["glyf"][0] + self.loca[i + 1]
        return self.data[o:e]

# ---------------------------------------------------------------- glyph helpers

def strip_hints(g):
    """Remove TrueType instructions and any source padding from a glyph record."""
    if len(g) < 10:
        return g
    n = s16(g, 0)
    if n >= 0:
        p = 10 + 2 * n
        if p + 2 > len(g):
            return g
        il = u16(g, p)
        start = p + 2 + il
        npts = (u16(g, p - 2) + 1) if n else 0
        flags = []
        k = start
        while len(flags) < npts and k < len(g):
            f = g[k]; k += 1
            flags.append(f)
            if f & 0x08 and k < len(g):
                r = g[k]; k += 1
                flags.extend([f] * r)
        flags = flags[:npts]
        q = k
        for f in flags:
            if f & 0x02: q += 1
            elif not f & 0x10: q += 2
        for f in flags:
            if f & 0x04: q += 1
            elif not f & 0x20: q += 2
        return g[:p] + b"\x00\x00" + g[start:q]
    p = 10
    while True:
        flags = u16(g, p); p += 2
        p += 2
        p += 4 if flags & 1 else 2
        if flags & 0x0008: p += 2
        elif flags & 0x0040: p += 4
        elif flags & 0x0080: p += 8
        if not flags & 0x0020: break
    return g[:p] + b"\x00\x00"
def patch_components(g, delta):
    """Shift composite component glyph indices by delta."""
    if len(g) < 10 or s16(g, 0) != -1:
        return g
    b = bytearray(g)
    p = 10
    while True:
        flags = u16(g, p)
        idx = u16(g, p + 2)
        struct.pack_into(">H", b, p + 2, idx + delta)
        p += 2 + 2 + (4 if flags & 1 else 2)
        if flags & 0x0008: p += 2
        elif flags & 0x0040: p += 4
        elif flags & 0x0080: p += 8
        if not flags & 0x0020: break
    return bytes(b)

def glyph_metrics(g):
    """Return (contours, points, components, maxdepth, bbox) for maxp/head."""
    if len(g) < 10:
        return (0, 0, 0, 0, None)
    n = s16(g, 0)
    bbox = (s16(g, 2), s16(g, 4), s16(g, 6), s16(g, 8))
    if n >= 0:
        pts = u16(g, 10 + 2 * (n - 1)) + 1 if n else 0
        return (n, pts, 0, 0, bbox)
    comps = 0
    p = 10
    while True:
        flags = u16(g, p); p += 4
        p += 4 if flags & 1 else 2
        if flags & 0x0008: p += 2
        elif flags & 0x0040: p += 4
        elif flags & 0x0080: p += 8
        comps += 1
        if not flags & 0x0020: break
    return (-1, 0, comps, 1, bbox)

# ---------------------------------------------------------------- cmap builders

def _delta_runs(mapping):
    items = sorted((c, g) for c, g in mapping.items() if 0 < c <= 0xFFFF)
    runs = []
    for c, g in items:
        d = (g - c) & 0xFFFF
        if runs and c == runs[-1][-1][0] + 1 and d == runs[-1][-1][2]:
            runs[-1].append((c, g, d))
        else:
            runs.append([(c, g, d)])
    return runs

def build_fmt4(mapping):
    runs = _delta_runs(mapping)
    n = len(runs)
    pref = [0] * (n + 1)
    blockstart = [True] * n
    for i, r in enumerate(runs):
        pref[i + 1] = pref[i] + len(r)
        if i and r[0][0] == runs[i - 1][-1][0] + 1:
            blockstart[i] = False

    INF = float("inf")
    dp = [INF] * (n + 1)
    back = [0] * (n + 1)
    dp[0] = 0
    W = 256
    for j in range(1, n + 1):
        if dp[j - 1] + 8 < dp[j]:
            dp[j] = dp[j - 1] + 8
            back[j] = 1
        for k in range(2, min(W, j) + 1):
            i = j - k
            # runs i..j-1 must be one contiguous code point range
            if blockstart[i + 1]:
                break
            cost = 8 + 2 * (pref[j] - pref[i])
            if dp[i] + cost < dp[j]:
                dp[j] = dp[i] + cost
                back[j] = k

    sizes, j = [], n
    while j > 0:
        k = back[j]
        sizes.append(k)
        j -= k
    sizes.reverse()

    segs, i = [], 0
    for k in sizes:
        grp = runs[i:i + k]
        start = grp[0][0][0]
        end = grp[-1][-1][0]
        if k == 1:
            segs.append((start, end, grp[0][0][2], None))
        else:
            segs.append((start, end, 0, [g for r in grp for (_, g, _) in r]))
        i += k

    segCount = len(segs) + 1
    glyphArray, starts = [], []
    for _, _, _, arr in segs:
        starts.append(len(glyphArray))
        if arr:
            glyphArray.extend(arr)

    total = 16 + 8 * segCount + 2 * len(glyphArray)
    if total > 0xFFFF:
        raise RuntimeError("format 4 cmap too large: %d bytes" % total)
    import math
    searchRange = 2 * (2 ** int(math.log2(segCount)))
    entrySelector = int(math.log2(segCount))
    rangeShift = 2 * segCount - searchRange
    out = bytearray()
    out += p16(4) + p16(total) + p16(0)
    out += p16(segCount * 2) + p16(searchRange) + p16(entrySelector) + p16(rangeShift)
    for s, e, d, arr in segs:
        out += p16(e)
    out += p16(0xFFFF)
    out += p16(0)
    for s, e, d, arr in segs:
        out += p16(s)
    out += p16(0xFFFF)
    for s, e, d, arr in segs:
        out += p16(d)
    out += p16(1)
    for idx, (s, e, d, arr) in enumerate(segs):
        out += p16(0 if arr is None else 2 * (segCount - idx) + 2 * starts[idx])
    out += p16(0)
    for g in glyphArray:
        out += p16(g)
    assert len(out) == total, (len(out), total)
    return bytes(out)
def build_fmt12(mapping):
    items = sorted((c, g) for c, g in mapping.items() if c > 0)
    groups = []
    for c, g in items:
        if groups and c == groups[-1][1] + 1 and g == groups[-1][2] + (c - groups[-1][0]):
            groups[-1][1] = c
        else:
            groups.append([c, c, g])
    out = bytearray()
    out += p16(12) + p16(0) + p32(16 + 12 * len(groups)) + p32(0) + p32(len(groups))
    for s, e, g in groups:
        out += p32(s) + p32(e) + p32(g)
    return bytes(out)

def build_cmap(mapping):
    f4 = build_fmt4(mapping)
    f12 = build_fmt12(mapping)
    recs = [(0, 3, f4), (0, 4, f12), (3, 1, f4), (3, 10, f12)]
    header = p16(0) + p16(len(recs))
    offset = 4 + 8 * len(recs)
    body = bytearray()
    table = bytearray()
    for pid, eid, sub in recs:
        table += struct.pack(">HHI", pid, eid, offset + len(body))
        body += sub
    return bytes(header) + bytes(table) + bytes(body)

# ---------------------------------------------------------------- name / post

def build_name(strings):
    recs = []
    for nid, s in strings:
        raw = s.encode("utf-16-be")
        recs.append((3, 1, 0x409, nid, raw))
    recs.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    count = len(recs)
    strOff = 6 + 12 * count
    head = p16(0) + p16(count) + p16(strOff)
    off = 0
    recbytes = bytearray()
    strs = bytearray()
    for pid, eid, lid, nid, raw in recs:
        recbytes += struct.pack(">HHHHHH", pid, eid, lid, nid, len(raw), off)
        strs += raw
        off += len(raw)
    return head + bytes(recbytes) + bytes(strs)

def parse_post(data, tabs):
    off = tabs["post"][0]
    ver = u32(data, off)
    if ver != 0x00020000:
        return None
    n = u16(data, off + 32)
    idx = [u16(data, off + 34 + 2 * i) for i in range(n)]
    p = off + 34 + 2 * n
    custom = []
    while p < off + tabs["post"][1]:
        ln = data[p]; p += 1
        custom.append(data[p:p + ln].decode("latin-1")); p += ln
    return idx, custom

def build_post(idx, custom, newnames):
    n = len(idx)
    out = bytearray()
    out += p32(0x00020000)
    out += struct.pack(">i", 0)          # italicAngle 0
    out += ps16(-100) + ps16(50)          # underline pos/thickness
    out += p32(0)                         # isFixedPitch
    out += p32(0) + p32(0) + p32(0) + p32(0)
    out += p16(n)
    for v in idx: out += p16(v)
    for s in custom + newnames:
        b = s.encode("latin-1")
        out += bytes([len(b)]) + b
    return bytes(out)

def build_post3():
    out = bytearray()
    out += p32(0x00030000)
    out += struct.pack(">i", 0)
    out += ps16(-100) + ps16(50)
    out += p32(0) + p32(0) * 4
    return bytes(out)

# ---------------------------------------------------------------- kern

def build_kern(pairs):
    if not pairs:
        return None
    pairs = sorted(set(pairs))
    n = len(pairs)
    import math
    sr = 6 * (2 ** int(math.log2(n)))
    es = int(math.log2(n))
    rs = 6 * n - sr
    sub = bytearray()
    sub += p16(0) + p16(14 + 6 * n) + p16(0x0001) + p16(n) + p16(sr) + p16(es) + p16(rs)
    for l, r, v in pairs:
        sub += p16(l) + p16(r) + ps16(v)
    return p16(0) + p16(1) + bytes(sub)

# ---------------------------------------------------------------- checksums

def checksum(b):
    b = b + b"\x00" * ((4 - len(b) % 4) % 4)
    return sum(struct.unpack(">%dI" % (len(b) // 4), b)) & 0xFFFFFFFF

def build_font(tables, numGlyphs):
    order = sorted(tables)
    n = len(order)
    # head.checkSumAdjustment must be 0 while computing every checksum
    tabs = dict(tables)
    h = bytearray(tabs["head"])
    struct.pack_into(">I", h, 8, 0)
    tabs["head"] = bytes(h)

    off = 12 + 16 * n
    dirs, body = bytearray(), bytearray()
    offs = {}
    for tag in order:
        offs[tag] = off + len(body)
        body += tabs[tag]
        body += b"\x00" * ((4 - len(body) % 4) % 4)
    for tag in order:
        data = tabs[tag]
        dirs += tag.encode("latin-1") + p32(checksum(data)) + p32(offs[tag]) + p32(len(data))

    sel = 1 << (n.bit_length() - 1)          # largest power of two <= n
    sr = 16 * sel
    es = n.bit_length() - 1
    rs = 16 * n - sr
    head = p32(0x00010000) + p16(n) + p16(sr) + p16(es) + p16(rs)
    font = bytearray(head + bytes(dirs) + bytes(body))
    adj = (0xB1B0AFBA - checksum(bytes(font))) & 0xFFFFFFFF
    ho = offs["head"]
    struct.pack_into(">I", font, ho + 8, adj)
    return bytes(font), adj

# ---------------------------------------------------------------- main

def _merge_glyphs(base_path, latin_path, out_path, family=None, kern=True,
                 prefer_base=False, keep_names=False):
    out_path = resolve_path(out_path)
    base = Sfnt(base_path)
    lat = Sfnt(latin_path)
    assert base.upm == lat.upm, f"UPM mismatch {base.upm} vs {lat.upm}"
    assert "glyf" in base.tabs and "glyf" in lat.tabs, "need glyf fonts"

    B = base.numGlyphs
    base_data = bytearray(base.data)
    bd, bt = base.data, base.tabs

    # ---- new glyf
    glyphs = []
    glyf_off = bt["glyf"][0]
    for i in range(B):
        g = bd[glyf_off + base.loca[i]: glyf_off + base.loca[i + 1]]
        glyphs.append(g)

    new_glyphs = []
    for i in range(lat.numGlyphs):
        g = lat.glyph(i)
        g = patch_components(g, B)
        g = strip_hints(g)
        glyphs.append(g)
        new_glyphs.append(g)

    # ---- build loca + glyf
    glyf = bytearray()
    loca = []
    for g in glyphs:
        loca.append(len(glyf))
        glyf += g
        glyf += b"\x00" * ((4 - len(glyf) % 4) % 4)
    loca.append(len(glyf))
    loca_data = b"".join(p32(x) for x in loca)

    # ---- hmtx (full metrics per glyph)
    hm = list(base.hmtx) + list(lat.hmtx)
    hmtx = bytearray()
    for adv, lsb in hm:
        hmtx += p16(adv) + ps16(lsb)
    hhea = bytearray(bd[bt["hhea"][0]: bt["hhea"][0] + bt["hhea"][1]])
    struct.pack_into(">H", hhea, 34, len(hm))

    # ---- cmap
    mapping = dict(base.cmap)
    for cp, gid in lat.cmap.items():
        if prefer_base and cp in base.cmap:
            continue                      # keep the original glyph for this code point
        mapping[cp] = gid + B
    cmap = build_cmap(mapping)

    # ---- head
    head = bytearray(bd[bt["head"][0]: bt["head"][0] + bt["head"][1]])
    struct.pack_into(">H", head, 50, 1)                       # long loca
    xs, ys = [], []
    for g in glyphs:
        if len(g) >= 10:
            xs += [s16(g, 2), s16(g, 6)]
            ys += [s16(g, 4), s16(g, 8)]
    if xs:
        struct.pack_into(">hhhh", head, 36, min(xs), min(ys), max(xs), max(ys))

    # ---- maxp
    maxp = bytearray(bd[bt["maxp"][0]: bt["maxp"][0] + bt["maxp"][1]])
    struct.pack_into(">H", maxp, 4, len(glyphs))

    # ---- OS/2
    os2 = bytearray(bd[bt["OS/2"][0]: bt["OS/2"][0] + bt["OS/2"][1]])
    cps = sorted(c for c in mapping if c > 0)
    struct.pack_into(">HH", os2, 64, min(min(cps), 0xFFFF), min(max(cps), 0xFFFF))
    ur1 = u32(os2, 42)
    ur1 |= 0x1 | 0x2                                          # Basic Latin, Latin-1 Supp
    struct.pack_into(">I", os2, 42, ur1)
    if u16(os2, 0) >= 1:
        cp1 = u32(os2, 78) | 0x1
        struct.pack_into(">I", os2, 78, cp1)
    ymax = max(ys) if ys else u16(os2, 74)
    if ymax > u16(os2, 74):
        struct.pack_into(">H", os2, 74, min(ymax, 0xFFFF))

    # ---- name
    def get_name(font, rec_id):
        d, t = font.data, font.tabs
        if "name" not in t:
            return ""
        for i in range(u16(d, t["name"][0] + 2)):
            r = t["name"][0] + 6 + 12 * i
            pid, eid, lid, nid, ln, so = struct.unpack_from(">HHHHHH", d, r)
            if nid == rec_id and pid == 3:
                off = t["name"][0] + u16(d, t["name"][0] + 4) + so
                return d[off:off + ln].decode("utf-16-be", "replace")
        return ""

    fam = family or ((get_name(base, 1) or "CJK") + " " + (get_name(lat, 1) or "Latin"))
    ps_fam = fam.replace(" ", "")
    if keep_names:
        name = bd[bt["name"][0]: bt["name"][0] + bt["name"][1]]
    else:
        name = build_name([
            (0, get_name(base, 0) + " | Latin glyphs from " + get_name(lat, 1) + ": "
                + get_name(lat, 0) + " Merged for personal use only; not for redistribution."),
            (1, fam),
            (2, "Regular"),
            (3, ps_fam + "-Regular"),
            (4, fam + " Regular"),
            (5, "Version 1.000; merged " + fam),
            (6, ps_fam + "-Regular"),
            (13, get_name(base, 13)),
            (14, get_name(base, 14)),
        ])

    # ---- post (format 2 if available, otherwise a valid format 3 header)
    pg = parse_post(bd, bt)
    newnames = ["lt%05d" % i for i in range(lat.numGlyphs)]
    if pg:
        idx, custom = pg
        idx = idx + [258 + len(custom) + k for k in range(len(newnames))]
        post = build_post(idx, custom, newnames)
    else:
        post = build_post3()
    # ---- kern (legacy, rebased)
    kern_tbl = None
    if kern and "kern" in lat.tabs:
        ko, kl = lat.tabs["kern"]
        cov = u16(lat.data, ko + 8)
        if u16(lat.data, ko) == 0 and u16(lat.data, ko + 2) >= 1 and (cov >> 8) == 0:
            npairs = u16(lat.data, ko + 10)
            pairs = []
            for k in range(npairs):
                l, r, v = struct.unpack_from(">HHh", lat.data, ko + 18 + 6 * k)
                pairs.append((l + B, r + B, v))
            kern_tbl = build_kern(pairs)

    tables = {
        "head": bytes(head), "hhea": bytes(hhea), "maxp": bytes(maxp),
        "hmtx": bytes(hmtx), "cmap": cmap, "glyf": bytes(glyf),
        "loca": loca_data, "name": name, "OS/2": bytes(os2), "post": post,
    }
    DENY = {"DSIG", "vhea", "vmtx", "hdmx", "LTSH", "VDMX", "VORG"}
    for tag in bt:
        if tag in tables or tag in DENY:
            continue
        o, l = bt[tag]
        tables[tag] = bd[o:o + l]
    if kern_tbl:
        tables["kern"] = kern_tbl

    tables = {k: v for k, v in tables.items() if v is not None}
    font, adj = build_font(tables, len(glyphs))
    open(out_path, "wb").write(font)
    return {
        "out": out_path,
        "base_glyphs": B,
        "latin_glyphs": lat.numGlyphs,
        "glyphs": len(glyphs),
        "cmap": len(cps),
        "bytes": len(font),
        "checksum": adj,
        "family": fam,
    }


# ------------------------------------------------------------------ augment

def _augment_codes(a):
    """Characters requested for grafting (text / file / ranges / scanned files)."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import fontsubset as FS

    codes = set()
    if a.text:
        codes.update(ord(c) for c in a.text if c not in "\r\n\t")
    if a.text_file:
        with open(resolve_path(a.text_file), encoding=a.encoding) as f:
            codes.update(ord(c) for c in f.read() if c not in "\r\n\t")
    if a.chars:
        for part in FS.normalize_ranges(a.chars).split(","):
            if not part:
                continue
            if "-" in part:
                x, y = part.split("-", 1)
                codes.update(range(int(x, 16), int(y, 16) + 1))
            else:
                codes.add(int(part, 16))
    if a.scan:
        chars, _, _ = FS.scan_paths([resolve_path(x) for x in a.scan], a.scan_encoding)
        codes.update(ord(c) for c in chars)
    return codes


def augment(base_path, donor_path, out_path, codes, donor_index=0, family=None,
            missing_report=None):
    """Graft CJK glyphs into a Latin font without touching the Latin side.

    Only code points the base font does not already map are added; the base
    cmap, glyphs, metrics and name table stay as they are.
    """
    from fontTools import subset as ftsubset
    from fontTools.ttLib import TTFont

    base_path = resolve_path(base_path)
    donor_path = resolve_path(donor_path)
    out_path = resolve_path(out_path)
    if missing_report:
        missing_report = resolve_path(missing_report)

    base = TTFont(base_path, lazy=True)
    base_cmap = base.getBestCmap() or {}
    base_family = base["name"].getDebugName(1)
    base_glyphs = base["maxp"].numGlyphs
    base.close()

    need = sorted(c for c in codes if c not in base_cmap)
    donor = TTFont(donor_path, fontNumber=donor_index, lazy=False)
    donor_cmap = donor.getBestCmap() or {}
    missing = [c for c in need if c not in donor_cmap]
    available = [c for c in need if c in donor_cmap]

    if not available:
        raise ValueError("nothing to add: the donor covers none of the requested characters")

    opt = ftsubset.Options()
    opt.layout_features = []
    opt.name_IDs = ["*"]
    opt.name_legacy = True
    opt.notdef_outline = True
    opt.recalc_timestamp = False
    opt.hinting = False
    sub = ftsubset.Subsetter(options=opt)
    sub.populate(unicodes=available)
    sub.subset(donor)
    for tag in ("GSUB", "GPOS", "GDEF"):
        if tag in donor:
            del donor[tag]

    donor_tmp = out_path + ".donor.ttf"
    donor.save(donor_tmp, reorderTables=True)

    r = _merge_glyphs(base_path, donor_tmp, out_path,
                     family=family or base_family,
                     kern=True, prefer_base=True, keep_names=True)
    os.remove(donor_tmp)

    out = TTFont(out_path, lazy=False)
    out_cmap = out.getBestCmap() or {}
    # Latin side must be byte-for-byte identical in outline terms
    b = TTFont(base_path, lazy=False)
    bo, oo = b.getGlyphOrder(), out.getGlyphOrder()
    bg, og = b["glyf"], out["glyf"]
    changed = 0
    for i, name in enumerate(bo):
        ca = bg[name].getCoordinates(bg)
        cb = og[oo[i]].getCoordinates(og)
        if ca[0] != cb[0] or list(ca[1]) != list(cb[1]) or list(ca[2]) != list(cb[2]):
            changed += 1
    base_cmap_moved = [c for c in base_cmap if out_cmap.get(c) != base_cmap[c]]

    if missing_report and missing:
        with open(missing_report, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join("U+%04X %s\n" % (c, chr(c)) for c in missing))

    return {
        "out": out_path,
        "base_glyphs": base_glyphs,
        "appended": len(oo) - base_glyphs,      # includes the donor's .notdef
        "chars_requested": len(codes),
        "chars_in_base": len([c for c in codes if c in base_cmap]),
        "chars_added": len(available),
        "missing": missing,
        "latin_changed": changed,
        "base_cmap_moved": base_cmap_moved,
        "glyphs": len(oo),
        "cmap": len(out_cmap),
        "bytes": os.path.getsize(out_path),
        "family": out["name"].getDebugName(1),
    }


def _cmd_augment(a):
    codes = _augment_codes(a)
    if not codes:
        print("error: no characters requested (--text / --text-file / --chars / --scan)")
        return 1
    r = augment(a.base, a.donor, a.out, codes, a.donor_index, a.family, a.missing_report)
    print("family     :", r["family"])
    print("characters : %d added, %d already in base, %d missing"
          % (r["chars_added"], r["chars_in_base"], len(r["missing"])))
    print("glyphs     : %d (base %d + appended %d)"
          % (r["glyphs"], r["base_glyphs"], r["appended"]))
    print("cmap       : %d code points" % r["cmap"])
    print("size       : %.2f MB" % (r["bytes"] / 1048576))
    print("latin      : %d glyph(s) changed, %d base code point(s) remapped"
          % (r["latin_changed"], len(r["base_cmap_moved"])))
    if r["missing"]:
        print("MISSING    : %d character(s) the donor cannot provide: %s"
              % (len(r["missing"]), " ".join("U+%04X" % c for c in r["missing"][:20])))
    if a.missing_report and r["missing"]:
        print("missing    : written to", a.missing_report)
    ok = not r["latin_changed"] and not r["base_cmap_moved"] and not r["missing"]
    if a.check and not check(r["out"]):
        ok = False
    print("RESULT     :", "OK" if ok else "CHECK")
    return 0 if ok else 1


# ------------------------------------------------------------------ validation

def u16(b, o): return struct.unpack_from(">H", b, o)[0]
def s16(b, o): return struct.unpack_from(">h", b, o)[0]
def u32(b, o): return struct.unpack_from(">I", b, o)[0]

def csum(b):
    b = b + b"\x00" * ((4 - len(b) % 4) % 4)
    return sum(struct.unpack(">%dI" % (len(b) // 4), b)) & 0xFFFFFFFF

def check(path):
    path = resolve_path(path)
    d = open(path, "rb").read()
    errs, warns = [], []
    sfnt = u32(d, 0)
    n = u16(d, 4)
    sr, es, rs = u16(d, 6), u16(d, 8), u16(d, 10)
    if sfnt not in (0x00010000, 0x74727565, 0x4F54544F):
        errs.append("bad sfnt version")
    sel = 1 << (n.bit_length() - 1)
    if (sr, es, rs) != (16 * sel, n.bit_length() - 1, 16 * n - 16 * sel):
        errs.append("bad searchRange/entrySelector/rangeShift %s" % ((sr, es, rs),))

    tabs, order = {}, []
    prev_tag = None
    spans = []
    for i in range(n):
        o = 12 + 16 * i
        tag = d[o:o+4].decode("latin-1")
        cs, off, ln = u32(d, o + 4), u32(d, o + 8), u32(d, o + 12)
        tabs[tag] = (off, ln, cs); order.append(tag)
        if prev_tag is not None and tag < prev_tag:
            errs.append("tables not sorted: %s after %s" % (tag, prev_tag))
        prev_tag = tag
        if off % 4:
            errs.append("%s offset not 4-aligned" % tag)
        if off + ln > len(d):
            errs.append("%s exceeds file" % tag)
        spans.append((off, ln, tag))
    spans.sort()
    for (o1, l1, t1), (o2, l2, t2) in zip(spans, spans[1:]):
        if o1 + l1 > o2:
            errs.append("%s overlaps %s" % (t2, t1))
    if spans and spans[0][0] < 12 + 16 * n:
        errs.append("table data overlaps directory")
    for tag, (off, ln, cs) in tabs.items():
        raw = d[off:off + ln]
        if tag == "head":
            raw = raw[:8] + b"\x00\x00\x00\x00" + raw[12:]
        if csum(raw) != cs:
            errs.append("%s checksum mismatch got %08x want %08x" % (tag, csum(raw), cs))

    if csum(d) != 0xB1B0AFBA:
        errs.append("whole-file checksum invalid")

    for need in ("head", "hhea", "maxp", "hmtx", "cmap", "loca", "glyf", "name", "post", "OS/2"):
        if need not in tabs:
            errs.append("missing table " + need)

    ho = tabs["head"][0]
    if u32(d, ho + 12) != 0x5F0F3CF5:
        errs.append("bad head magic")
    upm = u16(d, ho + 18)
    locfmt = s16(d, ho + 50)
    ng = u16(d, tabs["maxp"][0] + 4)
    nhm = u16(d, tabs["hhea"][0] + 34)
    lo, lol = tabs["loca"][0], tabs["loca"][1]
    want = (ng + 1) * (4 if locfmt else 2)
    if lol < want:
        errs.append("loca too short %d < %d" % (lol, want))
    if locfmt:
        loca = [u32(d, lo + 4 * i) for i in range(ng + 1)]
    else:
        loca = [u16(d, lo + 2 * i) * 2 for i in range(ng + 1)]
    if loca[-1] > tabs["glyf"][1]:
        errs.append("glyf too short for loca")
    if any(loca[i] > loca[i+1] for i in range(ng)):
        errs.append("loca not monotonic")
    if nhm < 1 or nhm > ng:
        errs.append("bad numberOfHMetrics")
    if tabs["hmtx"][1] < 4 * nhm + 2 * (ng - nhm):
        errs.append("hmtx too short")

    # cmap
    co = tabs["cmap"][0]
    seen = set()
    for i in range(u16(d, co + 2)):
        pid, eid, off = struct.unpack_from(">HHI", d, co + 4 + 8 * i)
        o = co + off
        fmt = u16(d, o)
        seen.add((pid, eid, fmt))
        if fmt == 4:
            ln = u16(d, o + 2); seg = u16(d, o + 6) // 2
            if 16 + 8 * seg > ln:
                errs.append("cmap4 length too small")
            end = o + 14; start = end + 2 * seg + 2
            delta = start + 2 * seg; ro = delta + 2 * seg
            for s in range(seg):
                e, st = u16(d, end + 2*s), u16(d, start + 2*s)
                if st > e:
                    errs.append("cmap4 seg start>end")
                dd, r = s16(d, delta + 2*s), u16(d, ro + 2*s)
                for c in range(st, min(e, 0xFFFE) + 1):
                    gi = (c + dd) & 0xFFFF if r == 0 else (
                        u16(d, ro + 2*s + r + 2*(c - st)) or 0xFFFF)
                    if r and gi != 0xFFFF:
                        gi = (gi + dd) & 0xFFFF
                    if gi != 0xFFFF and gi >= ng:
                        errs.append("cmap4 gid out of range")
                        break
        elif fmt == 12:
            ngroups = u32(d, o + 12)
            for g in range(ngroups):
                s, e, sg = struct.unpack_from(">III", d, o + 16 + 12*g)
                if sg + (e - s) >= ng:
                    errs.append("cmap12 gid out of range"); break
    if (3, 1, 4) not in seen:
        errs.append("missing (3,1) format 4 cmap")

    # post
    po = tabs["post"][0]
    ver = u32(d, po)
    if ver == 0x00020000:
        npg = u16(d, po + 32)
        if npg != ng:
            errs.append("post numGlyphs %d != maxp %d" % (npg, ng))

    # name
    no = tabs["name"][0]
    cnt, so = u16(d, no + 2), u16(d, no + 4)
    ids = set()
    for i in range(cnt):
        pid, eid, lid, nid, ln, off = struct.unpack_from(">HHHHHH", d, no + 6 + 12*i)
        ids.add(nid)
        end = no + so + off + ln
        if end > no + tabs["name"][1]:
            errs.append("name record out of range")
        if pid == 3:
            d[no + so + off:end].decode("utf-16-be")
    for need in (1, 2, 4, 6):
        if need not in ids:
            errs.append("name id %d missing" % need)

    os2 = tabs["OS/2"][1]
    if os2 not in (68, 78, 86, 96, 100):
        warns.append("OS/2 length %d unusual" % os2)

    print(os.path.basename(path), "| glyphs", ng, "| upm", upm,
          "| tables", len(tabs), "| errors", len(errs), "| warnings", len(warns))
    for e in errs[:20]:
        print("  ERR:", e)
    for w in warns:
        print("  WARN:", w)
    return not errs


# ------------------------------------------------------------------ TTC split

def extract_ttc(path, index, out_path, family=None):
    """Write one face of a TrueType Collection out as a standalone TTF."""
    path = resolve_path(path)
    out_path = resolve_path(out_path)
    d = open(path, "rb").read()
    if d[:4] != b"ttcf":
        raise ValueError("not a TTC/OTC file")
    n = u32(d, 8)
    if not 0 <= index < n:
        raise ValueError("index %d out of range (collection has %d faces)" % (index, n))
    base_off = u32(d, 12 + 4 * index)

    ntab = u16(d, base_off + 4)
    tables = {}
    for i in range(ntab):
        o = base_off + 12 + 16 * i
        tag = d[o:o + 4].decode("latin-1")
        off, ln = u32(d, o + 8), u32(d, o + 12)
        tables[tag] = d[off:off + ln]
    tables.pop("DSIG", None)                      # invalid after re-assembly
    ng = u16(tables["maxp"], 4)
    font, adj = build_font(tables, ng)
    open(out_path, "wb").write(font)
    return {"out": out_path, "glyphs": ng, "bytes": len(font), "checksum": adj}


# ------------------------------------------------------------------ CLI

def _cmd_extract(a):
    r = extract_ttc(a.ttc, a.index, a.out)
    print("glyphs %d, %.2f MB -> %s" % (r["glyphs"], r["bytes"] / 1048576, r["out"]))
    return 0


def _cmd_validate(a):
    bad = 0
    for path in a.files:
        if not check(path):
            bad += 1
    return 0 if not bad else 1


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        prog="fontstitch",
        description="Graft the Chinese glyphs a game needs into its original Latin font.")
    sub = p.add_subparsers(dest="cmd", required=True)

    au = sub.add_parser("augment", help="add CJK glyphs to a Latin font, leaving Latin untouched")
    au.add_argument("base", help="original Latin font (.ttf/.ttc)")
    au.add_argument("donor", help="CJK font that supplies the glyphs")
    au.add_argument("out", help="output .ttf")
    au.add_argument("--text", help="characters used, as a literal string")
    au.add_argument("--text-file", help="file of used characters (see --encoding)")
    au.add_argument("--chars", help="code point ranges, e.g. U+4E00-U+9FFF")
    au.add_argument("--scan", nargs="+", metavar="PATH",
                    help="scan text files/dirs for used characters")
    au.add_argument("--scan-encoding", default="auto",
                    choices=("auto", "utf-8", "utf-16", "gbk", "cp1252"))
    au.add_argument("--encoding", default="utf-8-sig", help="encoding of --text-file")
    au.add_argument("--donor-index", type=int, default=0, help="face index when donor is a .ttc")
    au.add_argument("--family", help="family name (default: keep the base font's family)")
    au.add_argument("--missing-report", help="write characters the donor lacks to this file")
    au.add_argument("--check", action="store_true", help="run structural validation afterwards")
    au.set_defaults(func=_cmd_augment)

    e = sub.add_parser("extract", help="extract one face from a .ttc")
    e.add_argument("ttc")
    e.add_argument("index", type=int)
    e.add_argument("out")
    e.set_defaults(func=_cmd_extract)

    v = sub.add_parser("validate", help="check tables/checksums/cmap of one or more fonts")
    v.add_argument("files", nargs="+")
    v.set_defaults(func=_cmd_validate)

    a = p.parse_args(argv)
    try:
        return a.func(a)
    except (ValueError, FileNotFoundError, OSError) as exc:
        print("error:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
