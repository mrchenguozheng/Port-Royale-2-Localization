#!/usr/bin/env python
# coding: utf-8
r"""src/tools/pack/pack_delta.py — 语言包相对上一次发行的变化

出包时给 README 的「语言包变化」段和 manifest.json 的
``translations[].delta`` 提供数字。

【口径】数字是**译文条目**，不是 diff 行数：一条译文改了算 1 条，跟它跨几行、
换行位置怎么挪都无关。译文文件是 `"0xid" = "正文"` 一条一行，但重译时整段
重排很常见，按行统计会把「换行挪了位置」也算成改动。

【基准】默认取 ``v<版本>`` 形式里版本号最大的 tag（``--baseline-tag`` 可覆盖）。
* 与本次版本同名的 tag 会排除 —— 重打同一个版本时不能拿它跟自己比；
* 基准 tag 里没有 ``src/translations/<语言>.toml`` 时记 ``kind="initial"``、
  **不给数字**：基线里还没这份译文，「新增 N 条」只是整份文件相加，不是变化；
* 仓库里一个 ``v<版本>`` 都没有时记 ``kind="none"``。

diff 走的是「基准 tag 对**工作树**」（``git diff <tag> -- <路径>``），
所以还没提交的译文改动也会算进本次变化 —— 出包前本来就可能带着未提交改动。
"""

import os
import re
import subprocess

#: `src/tools/pack/` 往上四层是仓库根。
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

#: 译文文件里一条数据行：`-"0x1a2b3c4d" = "…"` / `+"0x1a2b3c4d" = "…"`。
#: id 允许带引号（译文层是带引号的 key），也允许裸写。
_ID_LINE = re.compile(r'^([+-])\s*"?0x([0-9a-fA-F]{8})"?\s*=')


def _git(root, *args):
    """跑 git；成功返回 stdout，失败或没有 git 返回 None。"""
    exe = _git_exe()
    if not exe:
        return None
    try:
        out = subprocess.run([exe] + list(args), cwd=root, text=True,
                             encoding="utf-8", errors="replace",
                             stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def _git_exe():
    import shutil
    exe = shutil.which("git")
    if exe:
        return exe
    fallback = r"C:\Program Files\Git\cmd\git.exe"
    return fallback if os.path.isfile(fallback) else ""


def _git_ok(root, *args):
    exe = _git_exe()
    if not exe:
        return False
    try:
        out = subprocess.run([exe] + list(args), cwd=root,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def parse_diff(text):
    """从 ``git diff --unified=0`` 的输出里取出被删/被加的条目 id 集合。"""
    removed, added = set(), set()
    for line in (text or "").splitlines():
        match = _ID_LINE.match(line)
        if not match:
            continue
        (removed if match.group(1) == "-" else added).add(
            match.group(2).lower())
    return removed, added


def summarize(removed, added):
    """把两份 id 集合折成 ``changed / added / removed`` 三个数字。

    同一个 id 既被删又被加 = 改了一条；只在加里出现 = 新增；只在删里 = 删除。
    """
    common = removed & added
    return {
        "changed": len(common),
        "added": len(added - removed),
        "removed": len(removed - added),
    }


def baseline_tag(version="", root=ROOT):
    """取上一个发行 tag：``v*`` 里版本号最大的那个，排除本次版本。"""
    tags = _git(root, "tag", "--list", "--merged", "HEAD",
                "--sort=-version:refname", "v[0-9]*")
    if not tags:
        return ""
    wanted = version if version.startswith("v") else ("v%s" % version if version else "")
    for name in (line.strip() for line in tags.splitlines()):
        if name and name != wanted and re.match(r"^v\d+\.\d+\.\d+", name):
            return name
    return ""


def pack_delta(lang, version="", root=ROOT, tag=""):
    """相对上一次发行，这门语言改了多少条。

    返回值里的 ``kind`` 说明数字能不能用：
      * ``changed`` —— 有增/改/删，数字有效；
      * ``same``    —— 与基准逐条一致（数字都是 0）；
      * ``initial`` —— 基准里没有这份译文，不给数字；
      * ``none``    —— 仓库里没有可用的基准 tag；
      * ``error``   —— 有基准但 git diff 失败（不猜数字）。
    """
    rel = "src/translations/%s.toml" % lang
    baseline = tag or baseline_tag(version, root)
    if not baseline:
        return {"baseline": None, "kind": "none"}
    if not _git_ok(root, "cat-file", "-e", "%s:%s" % (baseline, rel)):
        return {"baseline": baseline, "kind": "initial"}
    diff = _git(root, "diff", "--unified=0", "--no-color", baseline, "--", rel)
    if diff is None:
        return {"baseline": baseline, "kind": "error"}
    result = summarize(*parse_diff(diff))
    result["baseline"] = baseline
    result["kind"] = ("changed" if any(result[k] for k in
                                       ("changed", "added", "removed"))
                      else "same")
    return result
