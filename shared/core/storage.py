# -*- coding: utf-8 -*-
"""Language-neutral storage helpers for the translator editor and tools."""
import json
import os
import tomllib

EN = "en.gog_1.1.2.3"
FR = "fr.gog_1.1.2.42"


def load_toml(path):
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def translation_path(data_root, lang):
    """译文唯一手改层：<data_root>/translations/<lang>.toml（入库）。

    引擎文本（补空格等排版加工）是构建产物，不在这一层，见
    src/tools/text/engine_text.py。
    """
    return os.path.join(data_root, "translations", lang + ".toml")


def reference_path(data_root, code):
    return os.path.join(data_root, "orig", code + ".toml")


def orig_path(data_root):
    path = reference_path(data_root, EN)
    if not os.path.isfile(path):
        path = os.path.join(data_root, "orig", "en.toml")
    return path


def load_translation(data_root, lang):
    path = translation_path(data_root, lang)
    return load_toml(path) if os.path.isfile(path) else {}


def load_orig(data_root):
    path = orig_path(data_root)
    return load_toml(path) if os.path.isfile(path) else {}


def lang_codes(data_root):
    directory = os.path.join(data_root, "translations")
    if not os.path.isdir(directory):
        return []
    return sorted(
        name[:-5] for name in os.listdir(directory)
        if name.endswith(".toml") and not name.startswith("_")
    )


def ordered_ids(data_root, lang):
    translation = load_translation(data_root, lang)
    orig = load_orig(data_root)
    return list(orig.keys()) + [x for x in translation.keys() if x not in orig]


def rows(data_root, lang):
    translation = load_translation(data_root, lang)
    orig = load_orig(data_root)
    fr_path = reference_path(data_root, FR)
    fr = load_toml(fr_path) if os.path.isfile(fr_path) else {}
    return [
        {"id": hid, EN: orig.get(hid, ""), FR: fr.get(hid, ""),
         lang: translation.get(hid, "")}
        for hid in ordered_ids(data_root, lang)
    ]


def save_translation(data_root, lang, updates):
    """Update known ids and rewrite one `id = text` line per entry."""
    translation = load_translation(data_root, lang)
    orig = load_orig(data_root)
    by_lower = {key.lower(): key for key in translation}
    changed = 0
    for row in updates:
        hid = str(row.get("id") or "")
        key = by_lower.get(hid.lower())
        if not key:
            continue
        text = str(row.get("text") or "")
        if translation[key] != text:
            translation[key] = text
            changed += 1
    ids = list(orig.keys()) + [x for x in translation.keys() if x not in orig]
    lines = []
    for hid in ids:
        if hid in translation:
            lines.append("%s = %s\n" % (
                json.dumps(hid, ensure_ascii=False),
                json.dumps(translation[hid], ensure_ascii=False)))
    with open(translation_path(data_root, lang), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    return changed
