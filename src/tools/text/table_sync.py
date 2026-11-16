# -*- coding: utf-8 -*-
"""table_sync.py —— 术语表与译名表的骨架生成、跨语言同步、覆盖率报表。

两张表是同一种东西的两半：术语表是扁平的 `<语言>_<原词> = "译词"`，
译名表是按实体分节的 `["原词"] / default = "译名"`。它们都必须**键集合一致**，
否则一门语言里引用了、另一门语言没这一行，构建时就只能靠人肉发现。

本工具做四件事：

    --init ja es            为没有表的新语言生成骨架，值留空（空 = 待译）
    --sync                  已存在的表补齐缺的键，只追加空占位，不动已有译文
    --status                每门语言已译/总数，附待译键清单
    --check                 有缺键就返回非零，给 CI 和单测用

基准从哪来：译名表的基准是 `entities.toml`（唯一真源，全语言共用一份）；
术语表没有清单文件，基准取**所有语言表的并集**——任何一门语言新加的键，
`--sync` 之后其余语言都会多出一行空占位。

空值在加载端是「表里有这一行、但还没译」：引用它会明确报未译，而不是报
「没有这个词条」，也不会被死条目校验当成拼错的键（见 text/marks.py）。
"""

import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))            # src/tools/text
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # 项目根

DATA_DIR = os.path.join(ROOT, "src", "data")

#: 术语表的一条赋值行；行尾注释（原形大小写、用在哪条键）要原样保留
_ASSIGN = re.compile(r'^([A-Za-z0-9_]+)\s*=\s*"(?:[^"\\]|\\.)*"(.*)$')
_SECTION = re.compile(r'^\["([^"]+)"\]$')


# ----------------------------------------------------------------- 路径与读取

def terms_path(lang, data_dir=None):
    return os.path.join(data_dir or DATA_DIR, "terms", "%s.toml" % lang)


def names_path(lang, data_dir=None):
    return os.path.join(data_dir or DATA_DIR, "names", "%s.toml" % lang)


def entities_path(data_dir=None):
    return os.path.join(data_dir or DATA_DIR, "names", "entities.toml")


def _read_toml(path):
    if not os.path.isfile(path):
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _read_text(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_text(path, text, mode="w"):
    with io.open(path, mode, encoding="utf-8", newline="") as fh:
        fh.write(text)


def read_terms(lang, data_dir=None):
    """术语表：{键: 译词}。文件不存在返回空表。"""
    return _read_toml(terms_path(lang, data_dir))


def read_names(lang, data_dir=None):
    """译名表：{原词: {default, 形态…}}，也接受字符串形式。"""
    return _read_toml(names_path(lang, data_dir))


def read_entities(data_dir=None):
    """实体清单：按文件里的节序返回 [(名字, kind, note)]。"""
    path = entities_path(data_dir)
    order, meta, cur = [], {}, None
    if not os.path.isfile(path):
        return order
    for stripped in (line.strip() for line in _read_text(path).splitlines()):
        m = _SECTION.match(stripped)
        if m:
            cur = m.group(1)
            order.append(cur)
            meta[cur] = {"kind": "", "note": ""}
            continue
        if cur is None or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        key = key.strip()
        if key in ("kind", "note"):
            meta[cur][key] = val.strip().strip('"')
    return [(name, meta[name]["kind"], meta[name]["note"]) for name in order]


def table_langs(data_dir=None):
    """已有译名表的语言（entities.toml 不算）。"""
    base = os.path.join(data_dir or DATA_DIR, "names")
    if not os.path.isdir(base):
        return []
    return [n[:-5] for n in sorted(os.listdir(base))
            if n.endswith(".toml") and n != "entities.toml"]


def term_langs(data_dir=None):
    base = os.path.join(data_dir or DATA_DIR, "terms")
    if not os.path.isdir(base):
        return []
    return [n[:-5] for n in sorted(os.listdir(base)) if n.endswith(".toml")]


# -------------------------------------------------------------------- 基准键

def terms_baseline(langs, data_dir=None):
    """术语键的并集，顺序按语言顺序（zh 排前面）依次出现。"""
    keys = []
    for lang in langs:
        for key in read_terms(lang, data_dir):
            if key not in keys:
                keys.append(key)
    return keys


def names_baseline(data_dir=None):
    return [name for name, _, _ in read_entities(data_dir)]


# ------------------------------------------------------------------ 骨架文本

def _skeleton_terms_text(src_lang, data_dir=None):
    """按源语言表的结构生成骨架：保留注释与分组，把每条的值清成占位。"""
    path = terms_path(src_lang, data_dir)
    out = ["# 术语表骨架：由 table_sync 从 %s 生成，键集合与源表一致。" % src_lang,
           "# 值为空 = 待译；填完把引号里的内容补上即可，键与注释不要改。"]
    if not os.path.isfile(path):
        return "\n".join(out) + "\n"
    for raw in _read_text(path).splitlines():
        m = _ASSIGN.match(raw)
        out.append('%s = ""%s' % (m.group(1), m.group(2)) if m else raw)
    return "\n".join(out) + "\n"


def _skeleton_names_text(data_dir=None):
    """译名表骨架：按 entities.toml 的节序来，每个实体的 kind/note 写成注释。"""
    out = ["# 译名表骨架：键与 src/data/names/entities.toml 一致，由 table_sync 生成。",
           "# 值空 = 待译；值写成原文本身 = 决定不译（例如厂商名）。"]
    for name, kind, note in read_entities(data_dir):
        out.append("")
        if kind or note:
            tail = "%s：%s" % (kind, note) if kind and note else (kind or note)
            out.append('# ["%s"] %s' % (name, tail))
        out.append('["%s"]' % name)
        out.append('default = ""')
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ 同步动作

def _append_block(path, lines):
    """在文件末尾追加一段；保证前一段与这一段之间有空行，不重写已有内容。"""
    block = "\n".join(lines)
    existing = _read_text(path) if os.path.isfile(path) else ""
    sep = "" if not existing else ("" if existing.endswith("\n") else "\n")
    _write_text(path, sep + block + "\n", mode="a")


def init_lang(lang, data_dir=None, src_lang="zh"):
    """给一门新语言生成两张骨架表，返回写出的文件路径。"""
    written = []
    tpath = terms_path(lang, data_dir)
    npath = names_path(lang, data_dir)
    for path in (tpath, npath):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.isfile(path):
            raise SystemExit("已存在，不覆盖：%s" % path)
    _write_text(tpath, _skeleton_terms_text(src_lang, data_dir))
    written.append(tpath)
    _write_text(npath, _skeleton_names_text(data_dir))
    written.append(npath)
    return written


def sync_terms(lang, keys, data_dir=None):
    """补齐缺的术语键，只追加空占位；返回追加的键。"""
    path = terms_path(lang, data_dir)
    have = read_terms(lang, data_dir)
    missing = [k for k in keys if k not in have]
    if not missing:
        return []
    if not os.path.isfile(path):
        raise SystemExit("没有这张表：%s（先用 --init %s）" % (path, lang))
    _append_block(path, ["# ---- 待译（table_sync 追加，值空 = 未译）----"]
                  + ['%s = ""' % k for k in missing])
    return missing


def sync_names(lang, names, data_dir=None):
    """补齐缺的实体节，只追加空占位；返回追加的实体名。"""
    path = names_path(lang, data_dir)
    have = read_names(lang, data_dir)
    missing = [n for n in names if n not in have]
    if not missing:
        return []
    if not os.path.isfile(path):
        raise SystemExit("没有这张表：%s（先用 --init %s）" % (path, lang))
    meta = {name: (kind, note) for name, kind, note in read_entities(data_dir)}
    block = ["# ---- 待译（table_sync 追加，值空 = 未译）----"]
    for name in missing:
        kind, note = meta.get(name, ("", ""))
        if kind or note:
            block.append("# %s：%s" % (name, ("%s：" % kind if kind else "") + note))
        block.append('["%s"]' % name)
        block.append('default = ""')
    _append_block(path, block)
    return missing


# ---------------------------------------------------------------- 覆盖率报表

def _is_translated(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_is_translated(v) for v in value.values())
    return bool(value)


def report(data_dir=None):
    """返回 (rows, 术语基线, 专名基线)；每行含 lang 与两张表的 (已译, 总数, 待译)。"""
    langs = sorted(set(term_langs(data_dir)) | set(table_langs(data_dir)))
    tkeys = terms_baseline(langs, data_dir)
    nkeys = names_baseline(data_dir)
    rows = []
    for lang in langs:
        t = read_terms(lang, data_dir)
        n = read_names(lang, data_dir)
        t_missing = [k for k in tkeys if not _is_translated(t.get(k))]
        n_missing = [k for k in nkeys if not _is_translated(n.get(k))]
        rows.append({
            "lang": lang,
            "terms": (len(tkeys) - len(t_missing), len(tkeys), t_missing),
            "names": (len(nkeys) - len(n_missing), len(nkeys), n_missing),
        })
    return rows, tkeys, nkeys


def print_report(rows, tkeys, nkeys):
    print("语言   术语     译名     待译术语 / 待译专名")
    for row in rows:
        t_done, t_all, t_missing = row["terms"]
        n_done, n_all, n_missing = row["names"]
        print("%-5s  %2d/%-2d   %2d/%-2d   %s / %s"
              % (row["lang"], t_done, t_all, n_done, n_all,
                 ",".join(t_missing) or "-", ",".join(n_missing) or "-"))
    print("术语键 %d 个（多语言并集）；专名 %d 个（entities.toml）"
          % (len(tkeys), len(nkeys)))


# -------------------------------------------------------------------- 命令行

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    data_dir = None
    if "--data-dir" in argv:
        data_dir = argv[argv.index("--data-dir") + 1]
    src_lang = argv[argv.index("--source") + 1] if "--source" in argv else "zh"

    if "--init" in argv:
        i = argv.index("--init")
        langs = argv[i + 1].replace(",", " ").split() if i + 1 < len(argv) else []
        if not langs:
            raise SystemExit("--init 后面写语言代码，例如 --init ja es")
        for lang in langs:
            for path in init_lang(lang, data_dir, src_lang):
                print("写出骨架：%s" % path)
        return 0

    if "--sync" in argv:
        langs = [l for l in term_langs(data_dir) if l != src_lang] or term_langs(data_dir)
        if src_lang not in langs:
            langs = [src_lang] + langs
        tkeys = terms_baseline(sorted(set(term_langs(data_dir) | set(table_langs(data_dir))),
                               key=lambda l: (l != src_lang, l)), data_dir)
        nkeys = names_baseline(data_dir)
        changed = 0
        for lang in langs:
            miss_t = sync_terms(lang, tkeys, data_dir)
            miss_n = sync_names(lang, nkeys, data_dir)
            if miss_t or miss_n:
                changed += 1
                print("%s：补术语 %d 条，补专名 %d 条"
                      % (lang, len(miss_t), len(miss_n)))
        print("同步完成，%d 张表有新增" % changed)
        return 0

    if "--status" in argv or "--check" in argv:
        rows, tkeys, nkeys = report(data_dir)
        print_report(rows, tkeys, nkeys)
        if "--check" in argv:
            bad = [r["lang"] for r in rows if r["terms"][2] or r["names"][2]]
            if bad:
                print("未通过：%s 还有空占位（跑 --sync 补骨架，再填译词）"
                      % ",".join(bad))
                return 1
        return 0

    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
