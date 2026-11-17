#!/usr/bin/env python
# coding: utf-8
r"""src/tools/text/versions.py —— 版本基线（键集）与定向版本差

为什么需要
----------
原版有不止一份字符串表，而且**键集不同**（实测，见 build\qa\版本对表.md）：

    en.gog_1.1.2.3    3548 条
    fr.gog_1.1.2.42   3571 条
    共有 3529；只 en 有 19；只 fr 有 42（42 条全部是 `+++EMPTY+++`）

译文只有一套，按 **并集** 组织（3548 ∪ 42 = 3590），但并集里那 42 条在任何语言版
里都没有正文，所以 `src\translations\` 不为它们建行 —— 它们由本模块在构建时
从目标版的 orig 表复制空值。缺行不是漏译，是「原文本来就是空的」。

版本差写成**定向**文件（`src\data\versions\<源>-to-<目标>.toml`）：
    only_from —— 源版有、目标版没有（目标包不带）
    only_to   —— 源版没有、目标版才有（目标包里是空占位）
语义：`keys(源) - only_from + only_to == keys(目标)`。

这些差不是注释性文档，是构建按版本出包的唯一依据，所以要能被 orig 表逐键核对：
`check()` 把算出来的差和文件里的差比对，任何一边手改漂移都会报错。

【不做什么】不判断「哪个版本更该用」。1.1.2.3 是键集基准，1.1.2.42 是参照语言，
两者都出包，装哪个由使用者按自己的安装选。
"""

import os
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))         # src\tools\text
TOOLS = os.path.dirname(HERE)                            # src\tools
SRC = os.path.dirname(TOOLS)                             # src
ROOT = os.path.dirname(SRC)                              # 仓库根

VERSIONS_DIR = os.path.join(SRC, "data", "versions")
ORIG_DIR = os.path.join(SRC, "orig")

#: 原文里表示「这条没有正文」的标记。空值只认它：
#: 别的空串（"" 或空白）要当错误 —— 那是提取或改写出了岔子，不是原文空。
EMPTY = "+++EMPTY+++"

#: 版本 id 的写法：<来源>.<版本号>，与 src\orig\<id>.toml 的文件名一致。
#: 只做形状检查，不枚举 —— 加第三个版本时不用改这里。


def _check_id(vid):
    """版本 id 必须与 src\\orig 的文件名对得上，形如 en.gog_1.1.2.3。"""
    if not isinstance(vid, str) or not vid or "/" in vid or "\\" in vid:
        return False
    return vid.count(".") >= 3 and vid[0].isalpha()


def _read_toml(path):
    with open(path, "rb") as fh:
        return tomllib.load(fh)

def read_orig(vid, orig_dir=None):
    """读 src\\orig\\<id>.toml：返回 {键: 值}，顺序是文件里的顺序。

    顺序有意义：语言包按目标版的键序输出，与既有产物一致（不是按 hash 排序，
    原表的顺序不是 hash 升序）。
    """
    orig_dir = orig_dir or ORIG_DIR
    return read_orig_file(os.path.join(orig_dir, vid + ".toml"))


def read_orig_file(path):
    """按路径读一份原文表，返回 {键: 值}（文件里的顺序）。"""
    if not os.path.isfile(path):
        raise SystemExit("找不到原文表：%s" % path)
    doc = _read_toml(path)
    return {k.lower(): v for k, v in doc.items()}


def load_baselines(data_dir=None, orig_dir=None):
    """读 src\\data\\versions\\baselines.toml，返回 [{id, orig, primary, keys, table}]。

    `keys` 是该版本字符串表的键集，`table` 是键→原文。primary 那份构建成
    `packs\\<语言>.txt`，其余写到 `build\\variants\\<id>\\<语言>.txt`。
    """
    data_dir = data_dir or VERSIONS_DIR
    orig_dir = orig_dir or ORIG_DIR
    path = os.path.join(data_dir, "baselines.toml")
    if not os.path.isfile(path):
        raise SystemExit("找不到版本基线表：%s" % path)
    doc = _read_toml(path)
    out = []
    for vid, cfg in (doc.get("baselines") or {}).items():
        if not _check_id(vid):
            raise SystemExit("版本 id 不像话：%r" % vid)
        orig = cfg.get("orig") or (vid + ".toml")
        if os.path.basename(orig) != orig:
            raise SystemExit("%s 的 orig 只许写文件名：%r" % (vid, orig))
        table = read_orig_file(os.path.join(orig_dir, orig))
        out.append({"id": vid, "orig": orig, "primary": bool(cfg.get("primary")),
                    "keys": list(table), "table": table})
    if not out:
        raise SystemExit("%s 里没有 [baselines.*] 段" % path)
    if sum(1 for b in out if b["primary"]) != 1:
        raise SystemExit("%s 里必须恰好有一个 primary" % path)
    return out


def load_diffs(data_dir=None):
    """读 src\\data\\versions\\*-to-*.toml，返回 {(源, 目标): {only_from, only_to, path}}。"""
    data_dir = data_dir or VERSIONS_DIR
    out = {}
    if not os.path.isdir(data_dir):
        return out
    for name in sorted(os.listdir(data_dir)):
        if not name.endswith(".toml") or name == "baselines.toml":
            continue
        path = os.path.join(data_dir, name)
        doc = _read_toml(path)
        frm, to = doc.get("from"), doc.get("to")
        only_from = [str(k).lower() for k in doc.get("only_from") or []]
        only_to = [str(k).lower() for k in doc.get("only_to") or []]
        out[(frm, to)] = {"only_from": only_from, "only_to": only_to, "path": path}
    return out


def _ascending(keys):
    return keys == sorted(keys, key=lambda k: int(k, 16))


def _translation_keys(translations_dir=None):
    """译文层覆盖的键（各语言 toml 的并集）；目录不存在时返回 None。"""
    d = translations_dir or os.path.join(SRC, "translations")
    if not os.path.isdir(d):
        return None
    keys = set()
    for name in os.listdir(d):
        if not name.endswith(".toml"):
            continue
        keys |= {k.lower() for k in _read_toml(os.path.join(d, name))}
    return keys


def check(data_dir=None, orig_dir=None, translations_dir=None):
    """把版本差与 orig 表逐键核对，返回错误清单（空 = 通过）。

    查的事：
      1. baselines.toml 里每个 id 的 orig 表存在，键集非空；
      2. 任意两个基线都有且只有一条定向差（不重不漏）；
      3. 每条定向差算出来与文件里写的一致（`keys(源) - only_from + only_to == keys(目标)`）；
      4. 两向互为镜像（A→B 的 only_from 就是 B→A 的 only_to）；
      5. only_to 里**译文层没有行**的键，在目标版原文必须是 `+++EMPTY+++`；
         原文有正文却没有译文行，是漏译，不能靠「目标版多出来的」悄悄带进包；
      6. 两个列表按键升序，重复键报错。
    """
    errors = []
    data_dir = data_dir or VERSIONS_DIR
    orig_dir = orig_dir or ORIG_DIR
    covered = _translation_keys(translations_dir)
    try:
        bases = load_baselines(data_dir, orig_dir)
    except SystemExit as exc:
        return ["版本基线：" + str(exc)]
    ids = [b["id"] for b in bases]
    tables = {b["id"]: set(b["keys"]) for b in bases}
    if len(set(ids)) != len(ids):
        errors.append("版本 id 重复：%s" % "、".join(ids))
    for b in bases:
        if not b["keys"]:
            errors.append("%s 的原文表是空的（%s）" % (b["id"], b["orig"]))
        if not os.path.isfile(os.path.join(orig_dir, b["orig"])):
            errors.append("%s 缺原文表：src/orig/%s" % (b["id"], b["orig"]))

    try:
        diffs = load_diffs(data_dir)
    except Exception as exc:
        return errors + ["定向差读不出：%s" % exc]

    pairs = {(a, b) for a in ids for b in ids if a != b}
    extra = set(diffs) - pairs
    for frm, to in sorted(extra):
        errors.append("%s→%s 不是基线对，多余的定向差：%s"
                      % (frm, to, os.path.basename(diffs[(frm, to)]["path"])))

    for frm, to in sorted(pairs):
        d = diffs.get((frm, to))
        if d is None:
            errors.append("缺定向差：%s→%s（src/data/versions/%s-to-%s.toml）"
                          % (frm, to, frm, to))
            continue
        a, b = tables[frm], tables[to]
        for label in ("only_from", "only_to"):
            keys = d[label]
            if len(set(keys)) != len(keys):
                errors.append("%s→%s 的 %s 有重复键" % (frm, to, label))
            if not _ascending(keys):
                errors.append("%s→%s 的 %s 没按 hash 升序" % (frm, to, label))
        only_from, only_to = d["only_from"], d["only_to"]
        dup = set(only_from) & set(only_to)
        if dup:
            errors.append("%s→%s 的 only_from 与 only_to 撞了：%s"
                          % (frm, to, "、".join(sorted(dup))))
        if set(only_from) != a - b:
            got, want = sorted(a - b), sorted(set(only_from))
            errors.append("%s→%s 的 only_from 与原文表不符：源有目标没有 %d 条，"
                          "文件写 %d 条（缺 %s / 多 %s）"
                          % (frm, to, len(got), len(want),
                             "、".join(k for k in got if k not in want) or "-",
                             "、".join(k for k in want if k not in got) or "-"))
        if set(only_to) != b - a:
            got, want = sorted(b - a), sorted(set(only_to))
            errors.append("%s→%s 的 only_to 与原文表不符：目标有源没有 %d 条，"
                          "文件写 %d 条（缺 %s / 多 %s）"
                          % (frm, to, len(got), len(want),
                             "、".join(k for k in got if k not in want) or "-",
                             "、".join(k for k in want if k not in got) or "-"))
        mirror = diffs.get((to, frm))
        if mirror is not None:
            if mirror["only_from"] != only_to or mirror["only_to"] != only_from:
                errors.append("%s→%s 与反向的 %s→%s 不是镜像"
                              % (frm, to, to, frm))

    table_of = {b["id"]: b["table"] for b in bases}
    for (frm, to), d in sorted(diffs.items()):
        if to not in table_of:
            continue
        for k in d["only_to"]:
            v = table_of[to].get(k)
            if v is None:
                continue
            if v.strip() == EMPTY:
                continue
            if covered is not None and k not in covered:
                errors.append("%s→%s：%s 在目标版是正文（%r），译文层却没有这一行"
                              "（漏译，不能当空占位）" % (frm, to, k, v[:40]))
    return errors


def pack_keys(baseline):
    """某个版本的语言包里应有的键（= 该版本字符串表的键集）。"""
    return list(baseline["keys"])


def union_keys(bases=None, data_dir=None, orig_dir=None):
    """并集键（按 hash 升序）：译文层覆盖的部分 + 各版本独有的空占位。"""
    bases = bases or load_baselines(data_dir, orig_dir)
    u = set()
    for b in bases:
        u |= set(b["keys"])
    return sorted(u, key=lambda k: int(k, 16))


def fill_value(baseline, key):
    """目标版独有、译文层没有行的键：返回该版本原文（只应为 +++EMPTY+++）。"""
    return baseline["table"].get(key)
