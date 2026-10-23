# -*- coding: utf-8 -*-
"""Placeholder and tag checks shared by the editor and build tools."""
import re

RE_SCRIPT = re.compile(r"@[A-Za-z]\$[A-Za-z_][A-Za-z_0-9]*\$")
RE_POS = re.compile(r"%\d+")
RE_PAD = re.compile(r"%(0?\d+)%(?!\d)")
RE_FONT = re.compile(r"<f:[^>]*>")
RE_TAG = re.compile(r"<[^>]*>")
RE_PLACEHOLDER = re.compile(r"^0x[0-9a-f]{8} \| ", re.I)


def tokens(text):
    text = RE_FONT.sub("", text)
    text = RE_TAG.sub("", text)
    text = RE_PAD.sub(r"%\1", text)
    return set(RE_SCRIPT.findall(text)) | set(RE_POS.findall(text))


def tag_counts(text):
    text = RE_FONT.sub("", text)
    return {tag: text.count(tag) for tag in set(RE_TAG.findall(text))}


def check_text(text, english):
    """Return UI-ready issues: [{'level': 'error'|'warn', 'text': ...}]."""
    out = []
    if not text:
        return [{"level": "warn", "text": "Empty; the game will show English."}]
    if RE_PLACEHOLDER.match(text):
        return [{"level": "warn", "text": "Untranslated placeholder."}]
    a, b = tokens(english), tokens(text)
    missing, extra = a - b, b - a
    if missing:
        out.append({"level": "warn",
                    "text": "Missing placeholder(s): " + " ".join(sorted(missing))})
    if extra:
        out.append({"level": "error",
                    "text": "Extra placeholder(s): " + " ".join(sorted(extra))})
    ta, tb = tag_counts(english), tag_counts(text)
    for tag in sorted(set(ta) | set(tb)):
        if tb.get(tag, 0) > ta.get(tag, 0):
            out.append({"level": "error", "text": "Extra tag: " + tag})
        elif tb.get(tag, 0) < ta.get(tag, 0):
            out.append({"level": "warn", "text": "Missing tag: " + tag})
    return out
