# -*- coding: utf-8 -*-
"""Language-neutral storage helpers for the translator editor and tools."""
import json
import os
import tomllib

EN = "en.gog_1.1.2.3"


def load_toml(path):
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def live_path(data_root, lang):
    return os.path.join(data_root, "live", lang + ".toml")


def orig_path(data_root):
    path = os.path.join(data_root, "orig", EN + ".toml")
    if not os.path.isfile(path):
        path = os.path.join(data_root, "orig", "en.toml")
    return path


def load_live(data_root, lang):
    path = live_path(data_root, lang)
    return load_toml(path) if os.path.isfile(path) else {}


def load_orig(data_root):
    path = orig_path(data_root)
    return load_toml(path) if os.path.isfile(path) else {}


def lang_codes(data_root):
    directory = os.path.join(data_root, "live")
    if not os.path.isdir(directory):
        return []
    return sorted(
        name[:-5] for name in os.listdir(directory)
        if name.endswith(".toml") and not name.startswith("_")
        and name != "keep_original.toml"
    )


def ordered_ids(data_root, lang):
    live = load_live(data_root, lang)
    orig = load_orig(data_root)
    return list(orig.keys()) + [x for x in live.keys() if x not in orig]


def rows(data_root, lang):
    live = load_live(data_root, lang)
    orig = load_orig(data_root)
    return [
        {"id": hid, EN: orig.get(hid, ""), lang: live.get(hid, "")}
        for hid in ordered_ids(data_root, lang)
    ]


def save_live(data_root, lang, updates):
    """Update known ids and rewrite one `id = text` line per entry."""
    live = load_live(data_root, lang)
    orig = load_orig(data_root)
    by_lower = {key.lower(): key for key in live}
    changed = 0
    for row in updates:
        hid = str(row.get("id") or "")
        key = by_lower.get(hid.lower())
        if not key:
            continue
        text = str(row.get("text") or "")
        if live[key] != text:
            live[key] = text
            changed += 1
    ids = list(orig.keys()) + [x for x in live.keys() if x not in orig]
    lines = []
    for hid in ids:
        if hid in live:
            lines.append("%s = %s\n" % (
                json.dumps(hid, ensure_ascii=False),
                json.dumps(live[hid], ensure_ascii=False)))
    with open(live_path(data_root, lang), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    return changed
