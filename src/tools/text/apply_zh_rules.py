# -*- coding: utf-8 -*-
r"""apply_zh_rules.py —— 把 src/translations/zh.toml 加工成引擎能直接用的中文文本。

产物：build/engine_text/zh.toml（**构建产物，不进仓库**）。
compile_pack 会在内存里做同样的事，这个文件只是给人看的中间结果；
删掉它不影响构建，下次编译会重新生成。

流程不再写死在这里：走 lang_rules 的三段式接口（lang_rules/spec.py），
由 `lang_rules.get_spec("zh")` 声明「标点 / 分词器 / 补空格」。

  1. 标点：lang_rules/zh.py 的 Punctuation（全角化、标点后空格、占位符）
  2. 连词、人名、数字/破折号/`<n><n>`：zh_pipeline.pre_space（分词前）
  3. 按词成组补空格：Spacing(mode="group")，分词器 spaCy → jieba → 机械兜底
  4. 连续空格归一

成组标准是**字数预算**，不是像素：控件宽度没有在游戏里实测过，
用字体算出来的 px 只是推测，不能当判据（见 docs/翻译局限.md）。

用法：
    python src/tools/text/apply_zh_rules.py            # 生成并写入 build/engine_text
    python src/tools/text/apply_zh_rules.py --check    # 与已生成的比较，不写文件
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
ROOT = os.path.dirname(os.path.dirname(TOOLS))
sys.path.insert(0, HERE)

from text import lang_rules, zh_pipeline, zh_space  # noqa: E402
from text.lang_rules import spec as specs  # noqa: E402

# 兼容层：这些名字以前直接定义在这里，测试与文档按旧名调用，保持可调。
TAG = zh_pipeline.TAG
fix_conj = zh_pipeline.fix_conj
load_list = zh_pipeline.load_list
build_names = zh_pipeline.build_names
find_names = zh_pipeline.find_names
pad_names = zh_pipeline.pad_names
space_tokens = zh_pipeline.space_tokens
collapse_spaces = zh_pipeline.collapse_spaces

#: 唯一手改的文本层
SRC = os.path.join(ROOT, "src", "translations", "zh.toml")
#: 构建产物（build/ 已 gitignore）
DST = os.path.join(ROOT, "build", "engine_text", "zh.toml")

CACHE = os.path.join(ROOT, "build", "cache", "zh.generated.json")
KEY_FILES = [SRC, __file__,
             os.path.join(HERE, "zh_pipeline.py"),
             os.path.join(HERE, "zh_space.py"),
             os.path.join(HERE, "lang_rules", "spec.py"),
             os.path.join(HERE, "lang_rules", "zh.py"),
             os.path.join(HERE, "lang_rules", "base.py"),
             os.path.join(TOOLS, "data", "zh_names.txt"),
             os.path.join(TOOLS, "data", "zh_towns.txt")]


def _cache_key():
    rows = []
    for p in KEY_FILES:
        try:
            st = os.stat(p)
            rows.append([os.path.basename(p), st.st_mtime_ns, st.st_size])
        except OSError:
            rows.append([os.path.basename(p), 0, 0])
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()


def _order_of(path):
    return [m.group(1) for m in
            (re.match(r'^"([^"]+)"\s*=', ln) for ln in io.open(path, encoding="utf-8"))
            if m]


def generate_doc(doc, order=None):
    """纯函数：{id: 译文} → {id: 引擎文本}。不读文件、不碰缓存。"""
    order = list(order or doc)
    spec = lang_rules.get_spec("zh")
    out, stats, seg_name = specs.build_texts(spec, doc, order)
    return order, out, stats, seg_name


def generate(use_cache=True):
    """按规则生成 {id: 引擎文本}，不写文件。"""
    if use_cache and not os.environ.get("PR2_NO_CACHE"):
        try:
            with open(CACHE, encoding="utf-8") as fh:
                cached = json.load(fh)
            if cached.get("key") == _cache_key():
                return (cached["order"], cached["out"], cached["stats"],
                        cached.get("segmenter", ""))
        except (OSError, ValueError, KeyError):
            pass

    doc = tomllib.load(open(SRC, "rb"))
    order = _order_of(SRC)
    result = generate_doc(doc, order)

    if use_cache and not os.environ.get("PR2_NO_CACHE"):
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            tmp = CACHE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"key": _cache_key(), "order": result[0], "out": result[1],
                           "stats": result[2], "segmenter": result[3]},
                          fh, ensure_ascii=False)
            os.replace(tmp, CACHE)
        except OSError:
            pass
    return result


def write(order, out):
    header = ("# 构建产物：由 src/tools/text/apply_zh_rules.py 从 src/translations/zh.toml 生成。\n"
              "# 不进仓库，删掉也没关系；改译文请改 src/translations/zh.toml，改规则请改脚本。\n")
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    io.open(DST, "w", encoding="utf-8", newline="\n").write(
        header + "\n".join('"%s" = "%s"' % (k, esc(out[k])) for k in order) + "\n")


def esc(t):
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只校验 build/engine_text/zh.toml 是否与「译文 + 规则」一致，不写文件")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    order, out, stats, seg_name = generate()
    print("生成 %d 条｜标点改动 %d｜连词 %d｜人名 %d｜补空格 %d｜分词器 %s" % (
        len(order), stats["punct"], stats["conj"], stats["name"], stats["space"],
        seg_name or "无（机械兜底）"))

    if args.check:
        old = {}
        if os.path.isfile(DST):
            try:
                old = tomllib.load(open(DST, "rb"))
            except Exception:
                old = {}
        diff = [h for h in order if old.get(h) != out[h]]
        extra = [h for h in old if h not in out]
        if diff or extra:
            print("生成物不一致：%d 条不同" % len(diff))
            for h in diff[:5]:
                print("  %s\n    文件：%s\n    应为：%s" % (h, old.get(h), out[h]))
            if extra:
                print("  文件里多出 %d 条" % len(extra))
            return 1
        print("生成物一致。")
        return 0

    if args.dry_run:
        return 0

    write(order, out)
    print("已写入", DST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
