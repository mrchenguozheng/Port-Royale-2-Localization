# -*- coding: utf-8 -*-
r"""line_breaks.py —— 手工断行层：机械断行切不动的条目，人工指定断点。

为什么要有这一层
----------------
日语没有空格分词，引擎只在空格与 `<n>` 处断行，所以长句得自带断点。
机械断行（`lang_rules/ja.py` 的 `JaLineBreak`）只在安全点下刀：助词后、
接续词后、顿号句号后；片假名专名、拉丁串、数字整体不切。机械层仍写 `<n>`；
这一层**只补空格**——人工挑的断点就用最普通的字符表达，不引入标签，
标签门与 lint 都不必为它开口子。

数据
----
`src/data/line_breaks/<lang>.toml`，一行一条：

    # 值是在第 N 个可见字之前补一个空格，段首记 0，位置严格递增。
    "0x0e4a1b2c" = [12]
    "0x0e4a1b2d" = [9, 18]

可见字：标签 `<…>` 与已有的 `<n>` 不计，空格／制表不计（它们本来就是断行点），
占位 `@a$Name$` / `%1` 各记 1 字（引擎渲染成一个数字或一个地名，宽度与一个字
相当）。位置按**整条**累计，不因已有的 `<n>` 重置。

校验
----
* 位置必须是正整数、严格递增、且小于总字数；
* 每个位置两侧的段都不能超过上限（默认 13 字），否则抛 `ManualBreakError`；
* 位置正好落在已有空白处时不重复补空格（那里本来就会断）。

这一层只加空格，不改任何字、不动 `<n>`。写错一条不会污染别的条目：
位置落不下来就整条报错，表里 id 与译文对不上也当场上报。
"""

import os
import re
import tomllib

UNIT = re.compile(r"<n(?::\d+)?>|@[A-Za-z]\$[^$]*\$|%[0-9]+[A-Za-z]?|<[^<>]*>")
NODE = re.compile(r"^<n(?::\d+)?>$")
SPACE = (" ", "\t", "\u3000")


class ManualBreakError(ValueError):
    """手工断点数据不合法。"""


def data_path(root, lang):
    return os.path.join(root, "src", "data", "line_breaks", "%s.toml" % lang)


def read_table(root, lang):
    """读手工断点表：{id: [位置, ...]}。文件不存在就是空表，不是错误。

    这里直接用 `tomllib`，不走 `toml_io`：本模块会被 `lang_rules.ja` 在两种
    加载方式下导入（`text.lang_rules.ja` 与顶层 `lang_rules.ja`），少一层包内
    相对导入，两路都不会断。
    """
    path = data_path(root, lang)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as fh:
            doc = tomllib.load(fh)
    except (OSError, ValueError) as exc:
        raise ManualBreakError("%s: 读不出断点表（%s）" % (path, exc))
    if not doc:
        return {}
    return {hid: parse_positions(hid, val) for hid, val in doc.items()}


def parse_positions(hid, val):
    if isinstance(val, dict):
        val = val.get("at")
    if not isinstance(val, list) or not val:
        raise ManualBreakError("%s: 值必须是位置数组，如 [12] 或 [9, 18]" % hid)
    pos = []
    for item in val:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ManualBreakError("%s: 位置必须是整数，收到 %r" % (hid, item))
        if item <= 0:
            raise ManualBreakError("%s: 位置必须大于 0（段首不切）" % hid)
        if pos and item <= pos[-1]:
            raise ManualBreakError("%s: 位置必须严格递增，收到 %r" % (hid, pos + [item]))
        pos.append(item)
    return pos


def units(text):
    """切成可见单位：[(片段, 可见宽度)]。

    标签 `<…>` 与已有 `<n>` 宽 0；占位 `@a$Name$` / `%1` 渲染成一个数字或一
    个地名，按 1 字算（与 `line_run.py` 的 VAR→1、TAG→0 同口径）；其余逐字计
    1。注意不能直接 `UNIT.split`——`re.split` 会把匹配串丢掉，占位就此消失。
    """
    out = []
    pos = 0
    for m in UNIT.finditer(text):
        if m.start() > pos:
            for ch in text[pos:m.start()]:
                out.append((ch, 1))
        tok = m.group(0)
        out.append((tok, 0 if tok.startswith("<") else 1))
        pos = m.end()
    for ch in text[pos:]:
        out.append((ch, 1))
    return out


def visible_length(text, skip_space=False):
    return sum(w for s, w in units(text)
               if not (skip_space and s in SPACE))


def insert(text, positions, limit=None, hid=""):
    """按可见字位置补空格（不是 `<n>`）。位置**不数空白**——人工照正文数第 N 个字。

    空白（空格／制表）在引擎那里本身就是断行点，所以既不占位置，也不吃位置；
    位置正好落在已有空白上时跳过，不制造连续空格。
    """
    if not positions:
        return text
    total = visible_length(text, skip_space=True)
    positions = sorted(set(positions))
    for p in positions:
        if not isinstance(p, int) or p <= 0:
            raise ManualBreakError("%s: 位置必须是正整数" % hid)
    if positions[-1] >= total:
        raise ManualBreakError("%s: 位置超出总字数（%d）" % (hid, total))

    out = []
    seen = 0
    pending = list(positions)
    for piece, w in units(text):
        if NODE.match(piece):
            out.append(piece)
            continue
        if piece in SPACE:
            # 这里本来就会断行，人为位置落在这上面就不必再补
            if pending and seen == pending[0]:
                pending.pop(0)
            out.append(piece)
            continue
        if w and pending and seen == pending[0]:
            out.append(" ")
            pending.pop(0)
        out.append(piece)
        seen += w

    result = "".join(out)
    if pending:
        raise ManualBreakError("%s: 位置没有全部落地，表比文本长" % hid)
    if limit is not None:
        # 引擎在空格与 `<n>` 处都断行，两处都算段边界
        for seg in re.split(r"<n(?::\d+)?>[ \t]*|[ \t]+", result):
            if visible_length(seg) > limit:
                raise ManualBreakError(
                    "%s: 补完仍有 %d 字段超过上限 %d：%s"
                    % (hid, visible_length(seg), limit, seg[:40]))
    return result
