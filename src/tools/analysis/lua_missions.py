# -*- coding: utf-8 -*-
"""从 luac -l 反汇编清单里读 PR2 的任务注册表。不解析字节码，只解析清单文本。

PR2 的 ``lua\\data\\missions.bin`` 是 Ascaron 改过的 Lua 4.1 字节码（签名 \\x1bLuaA），
任何 Lua 5.1 工具都读不了；能读它的是游戏自带的 luac —— Darkstar One Modding Tools
里的 ``ScriptCompiler.exe``（自报 ``Lua 4.1.0 (ASCARON_LUA,modified 4.0.1 source)``，
2004 年的构件，见 09 卷第七十节）。清单这样生成：

    ScriptCompiler.exe -l missions.bin > list.txt

本模块只吃这份文本，所以在任何机器上都能跑，不需要那个 exe。

注册形态（abduction.lua 实测）：

    GETGLOBAL  ; Script_Register
    PUSHSTRING ; "abduction"     PUSHSTRING ; "govern"    GETGLOBAL ; MTYPE_GOVERNOR
    CALL
    F["USES"]     = { "abduction_spawn_treasure", "abduction_spawn_goods" }
    F["OnInit"]   = function ... end
    F["OnCreate"] = function ... end

即 ``Script_Register(名字, 分组, 类型)``，随后把回调挂到返回表上。DSO 用的是
``NScript.Register{Name/Group/Type/Transitions}``，字段名完全不同，不能套用。

用法：
    python src/tools/analysis/lua_missions.py <list.txt>
    python src/tools/analysis/lua_missions.py <list.txt> --json build/qa/pr2_missions.json
"""
import argparse
import io
import json
import re
import sys

#: ``main <0:@LUA Mission Source/data/abduction.lua> (65 instructions/260 bytes at ...)``
_CHUNK = re.compile(r"^main <\d+:(.*?)> \(")
_SUB = re.compile(r"^function <\d+:(.*?)> \(")
_REG = re.compile(r"GETGLOBAL\s+\d+\s*;\s*Script_Register$")
_PUSHSTRING = re.compile(r'PUSHSTRING\s+\d+\s*;\s*"(.*)"$')
_GETGLOBAL = re.compile(r"GETGLOBAL\s+\d+\s*;\s*(\S+)$")
#: 文本键：任务脚本用 IDM_/ID_ 具名常量，不是 0x 哈希。
_TEXT_ID = re.compile(r"^ID[A-Z0-9_]{4,}$")

TYPE_PREFIX = "MTYPE_"


def blocks(text):
    """按 main chunk 切块：``[(源名, [指令行, ...]), ...]``。

    子函数（``function <...>``）的行并进所属 main 块——文本键常常写在回调里。
    """
    out = []
    name = None
    lines = None
    for line in text.splitlines():
        m = _CHUNK.match(line)
        if m:
            if name is not None:
                out.append((name, lines))
            name, lines = m.group(1), []
            continue
        if name is not None:
            lines.append(line.strip())
    if name is not None:
        out.append((name, lines))
    return out


def _registration(lines):
    """读一条 ``Script_Register``；读不到完整的三元组就返回 None。"""
    for i, line in enumerate(lines):
        if not _REG.search(line):
            continue
        if i + 1 < len(lines) and _SUB.match(lines[i + 1]):
            return None                # 注册不可能出现在子函数里
        name = group = mtype = None
        for line in lines[i + 1:i + 8]:
            s = _PUSHSTRING.search(line)
            if s:
                if name is None:
                    name = s.group(1)
                elif group is None:
                    group = s.group(1)
                continue
            g = _GETGLOBAL.search(line)
            if g and g.group(1).startswith(TYPE_PREFIX):
                mtype = g.group(1)
                break
        if name and mtype:
            return {"name": name, "group": group, "type": mtype}
        return None
    return None


def _states(lines):
    """挂上来的状态名：``PUSHSTRING ; "OnX"`` 紧跟 ``CLOSURE``。

    只认 ``On`` 开头的键，``USES`` 那类数据表不算状态。
    """
    out = []
    for i, line in enumerate(lines[:-1]):
        s = _PUSHSTRING.search(line)
        if not s or not s.group(1).startswith("On"):
            continue
        if "CLOSURE" in lines[i + 1] and s.group(1) not in out:
            out.append(s.group(1))
    return out


def _text_ids(lines):
    ids = []
    for line in lines:
        s = _PUSHSTRING.search(line)
        if s and _TEXT_ID.match(s.group(1)) and s.group(1) not in ids:
            ids.append(s.group(1))
    return ids


def parse_listing(text):
    """清单文本 -> 任务记录列表（按名字排序，名字唯一）。"""
    rows = []
    for source, lines in blocks(text):
        reg = _registration(lines)
        if not reg:
            continue                       # 库 chunk 不注册任务，跳过而不是报错
        rows.append({
            # 清单里源名带 Lua 4 的 '@' 前缀，去掉后就是落盘的相对路径
            "source": source[1:] if source.startswith("@") else source,
            "name": reg["name"],
            "group": reg["group"],
            "type": reg["type"],
            "states": _states(lines),
            "text_ids": _text_ids(lines),
        })
    names = [r["name"] for r in rows]
    assert len(names) == len(set(names)), "任务名重复：%r" % (
        sorted(n for n in set(names) if names.count(n) > 1),)
    for r in rows:
        assert r["type"].startswith(TYPE_PREFIX), "类型不合规：%s" % r["type"]
    rows.sort(key=lambda r: r["name"])
    return rows


def summarize(rows):
    return {
        "missions": len(rows),
        "types": {t: sum(1 for r in rows if r["type"] == t)
                  for t in sorted({r["type"] for r in rows})},
        "groups": sorted({r["group"] for r in rows if r["group"]}),
        "states": sorted({s for r in rows for s in r["states"]}),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="读 luac -l 清单里的 PR2 任务注册表")
    ap.add_argument("listing", help="ScriptCompiler.exe -l 的输出")
    ap.add_argument("--json", help="把整表写成 JSON")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    text = io.open(args.listing, encoding="utf-8", errors="replace").read()
    rows = parse_listing(text)
    s = summarize(rows)
    print("任务记录：%d" % s["missions"])
    print("类型分布：%s" % s["types"])
    print("分组：%s" % ", ".join(s["groups"]))
    print("状态名 %d 个" % len(s["states"]))
    if not args.quiet:
        for r in rows:
            print("  %-28s %-12s %-16s %2d 状态 %3d 文本键"
                  % (r["name"], r["group"], r["type"],
                     len(r["states"]), len(r["text_ids"])))
    if args.json:
        io.open(args.json, "w", encoding="utf-8", newline="").write(
            json.dumps({"schema": 1, "missions": rows},
                       ensure_ascii=False, indent=1) + "\n")
        print("写出 %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
