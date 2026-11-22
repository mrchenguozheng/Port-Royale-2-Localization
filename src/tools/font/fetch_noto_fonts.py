#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_noto_fonts.py —— 按清单核对 / 下载 Noto 源字体。

清单是 src\\fonts-sources.toml（入库）；字体文件不入库。

    # 只核对（CI 与构建前用，缺则 exit 1）
    python src\\tools\\font\\fetch_noto_fonts.py --langs zh,ja

    # 缺什么下载什么：可变字体按 axis.wght 实例化成静态文件，落盘后可被
    # 所有构建脚本按静态文件名直接使用
    python src\\tools\\font\\fetch_noto_fonts.py --langs zh,ja --fetch

    # 把文件直接放进仓库的兜底目录（可选，体积大）
    python src\\tools\\font\\fetch_noto_fonts.py --fetch --out assets\\fonts\\noto

下载后先验体积与字体魔数，再实例化；实例化产物同样复验。任何一步失败都
返回非零，不写半份文件（先写临时文件再替换）。
"""

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
import tomllib
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import font_sources as FS  # noqa: E402

#: TrueType / OpenType / 集合文件的头 4 字节。
FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")


def load_manifest():
    with open(FS.MANIFEST, "rb") as fh:
        data = tomllib.load(fh)
    items = data.get("font") or []
    if not items:
        raise RuntimeError("清单里没有 [[font]]：%s" % FS.MANIFEST)
    return items


def wanted(items, langs):
    out = {}
    for it in items:
        tags = it.get("langs") or []
        if not langs or (set(tags) & set(langs)):
            out[it["name"]] = it
    return out


def check_file(path, min_bytes):
    if not os.path.isfile(path):
        return False, "不存在"
    size = os.path.getsize(path)
    if size < min_bytes:
        return False, "体积 %d 字节，小于预期 %d" % (size, min_bytes)
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head not in FONT_MAGIC:
        return False, "不是字体文件（头 4 字节 %r）" % head
    return True, ""


def download(url, dst, log, tries=5):
    """下载到 dst；断线后按已下载字节续传（Range），最多试 5 次。

    GitHub raw 对大文件（NotoSansSC 17MB）会偶发断连，从零重试往往断在同一处，
    所以这里保留半成品并续传，只有最终失败才由调用方清掉。
    """
    last = None
    for attempt in range(1, tries + 1):
        have = os.path.getsize(dst) if os.path.isfile(dst) else 0
        headers = {"User-Agent": "pr2-localization-fonts/1"}
        if have:
            headers["Range"] = "bytes=%d-" % have
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                status = getattr(resp, "status", 200)
                if have and status == 206:
                    mode, start = "ab", have
                    remaining = int(resp.headers.get("Content-Length") or 0)
                else:
                    mode, start = "wb", 0
                    remaining = int(resp.headers.get("Content-Length") or 0)
                total = start + remaining
                written = start
                next_mark = ((written // (8 << 20)) + 1) * (8 << 20)
                with open(dst, mode) as fh:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        fh.write(chunk)
                        written += len(chunk)
                        if written >= next_mark:
                            log("  … %d MB%s" % (written >> 20,
                                                 (" / %d MB" % (total >> 20)) if total else ""))
                            next_mark += 8 << 20
            if remaining and written - start != remaining:
                raise IOError("只收到 %d/%d 字节" % (written - start, remaining))
            return written
        except Exception as exc:                       # 断连 / 超时 / 半截：续传重试
            last = exc
            if attempt < tries:
                log("  第 %d 次下载中断（%s），已到 %.1f MB，续传重试"
                    % (attempt, exc, (os.path.getsize(dst) if os.path.isfile(dst) else 0) / 1048576.0))
                time.sleep(3 * attempt)
    if os.path.isfile(dst):
        os.remove(dst)
    raise last


def make_static(src, dst, weight):
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    font = TTFont(src)
    if "fvar" in font:
        font = instantiateVariableFont(font, {"wght": weight}, inplace=False)
    font.save(dst)
    font.close()


def fetch_one(item, out_dir, log, raw_dir):
    name = item["name"]
    target = os.path.join(out_dir, name)
    min_bytes = int(item.get("min_bytes") or 0)

    ok, why = check_file(target, min_bytes)
    if ok:
        log("  已存在 %s（%d KB）" % (name, os.path.getsize(target) >> 10))
        return True

    weight = (item.get("axis") or {}).get("wght")
    # 同一个 URL 常被多个字重共用（NotoSerif-Black / -Bold），原件只下一次，
    # 存在临时目录里，不进 cache——cache 只留静态产物。
    raw = os.path.join(raw_dir, hashlib.sha1(item["source"].encode("utf-8")).hexdigest()[:16] + ".ttf")
    raw_ok = raw + ".ok"
    try:
        if os.path.isfile(raw_ok) and check_file(raw, 1024)[0]:
            log("  复用已下载的源 %s" % os.path.basename(raw))
            size = os.path.getsize(raw)
        else:
            log("  下载 %s ← %s" % (name, item["source"]))
            if os.path.isfile(raw_ok):
                os.remove(raw_ok)
            size = download(item["source"], raw, log)
            ok, why = check_file(raw, 0)
            if not ok:
                raise RuntimeError("下载内容不是字体：%s" % why)
            with open(raw_ok, "wb"):
                pass
        if weight:
            log("  实例化 wght=%d → %s" % (weight, name))
            make_static(raw, target + ".tmp", int(weight))
            os.replace(target + ".tmp", target)
        else:
            shutil.copyfile(raw, target)
        ok, why = check_file(target, min_bytes)
        if not ok:
            raise RuntimeError("落盘校验失败：%s" % why)
    except Exception as exc:
        for p in (raw, raw_ok, target + ".tmp"):
            if os.path.isfile(p):
                os.remove(p)
        log("  失败 %s：%s" % (name, exc))
        return False
    log("  完成 %s（源 %.1f MB，落盘 %.1f MB）"
        % (name, size / 1048576.0, os.path.getsize(target) / 1048576.0))
    return True


def report(items, dirs, log):
    found, missing = FS.scan([it["name"] for it in items.values()], dirs)
    log("[fonts] 需要 %d 个文件；搜索顺序：%s" % (len(items), FS.whoami()))
    for name in items:
        if name in found:
            log("  OK      %-26s %s" % (name, found[name]))
        else:
            log("  MISSING %s" % name)
    if missing:
        log("[fonts] 缺 %d 个：%s" % (len(missing), "、".join(missing)))
        log("[fonts] 查过：")
        for d in dirs:
            log("  - %s" % d)
        log("[fonts] 补法：%s（默认落盘 %s）" % (FS.FETCH_CMD, FS.CACHE_DIR))
        return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="核对 / 下载 Noto 源字体")
    ap.add_argument("--langs", default="",
                    help="逗号分隔的语言码；留空表示清单里全部")
    ap.add_argument("--fetch", action="store_true", help="缺什么下载什么")
    ap.add_argument("--out", default=FS.CACHE_DIR, help="下载落点（默认 build\\cache\\noto-src）")
    ap.add_argument("--no-system", action="store_true",
                    help="不查系统字体目录（模拟干净的 runner）")
    a = ap.parse_args(argv)

    langs = [x.strip() for x in a.langs.split(",") if x.strip()]
    items = wanted(load_manifest(), langs)
    if not items:
        print("[fonts] 没有匹配的语言：%s" % (a.langs or "(空)"))
        return 2

    def log(msg):
        print(msg, flush=True)

    dirs = FS.candidate_dirs(include_system=not a.no_system)
    ok = report(items, dirs, log)
    if ok:
        return 0
    if not a.fetch:
        return 1

    log("[fonts] 开始补齐，落点 %s" % a.out)
    os.makedirs(a.out, exist_ok=True)
    failed = []
    raw_dir = tempfile.mkdtemp(prefix="pr2-noto-raw-")
    try:
        for name, item in items.items():
            if FS.find(name, dirs):
                continue
            if not fetch_one(item, a.out, log, raw_dir):
                failed.append(name)
    finally:
        shutil.rmtree(raw_dir, ignore_errors=True)

    dirs2 = FS.candidate_dirs(include_system=not a.no_system, extra=[a.out])
    if not report(items, dirs2, log) or failed:
        log("[fonts] 补齐失败：%s" % "、".join(failed or ["见上"]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
