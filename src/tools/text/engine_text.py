# -*- coding: utf-8 -*-
r"""engine_text.py —— 译文层 → 引擎层（构建期的唯一入口）。

分层
----
    src/translations/<lang>.toml   干净译文，唯一手改层，入库
            ↓ 本模块（标点 / 分词 / 补空格，规则见 lang_rules 的 spec）
    build/preview/engine_text/<lang>.toml  引擎文本，构建产物，不进仓库
            ↓ compile_pack
    build/runtime/PR2Localization/packs/<lang>.txt      语言包

只有一份真相源：译文层。引擎层随时可以从头重建，删掉它不影响构建。

语言分派
--------
    spec = lang_rules.get_spec(lang)   # 标点 / 分词器 / 补空格，见 lang_rules/spec.py
    zh     标点全角化 + 连词/人名 + 按词补空格（Spacing mode=group）
    ja     助词后空格 + 标点规范化（Spacing mode=particle）
    fr     显式透传：法语排版（? ! ; : % 前的 NBSP）已写在译文里，构建期不改字面
    de/es/ru/ko  显式透传：模块存在、`SKIP` 里写明理由，`spec()` 不加工
    en/其他 未登记语言同样原样返回

新语言只写一个 lang_rules/<代码>.py 声明 spec()，本模块不需要改。

补空格「按词成组」的标准是**字数预算**，不是像素 —— 控件宽度没有在游戏里
实测过，用字体算出来的 px 只是推测，不能当判据。

用法
----
    python src/tools/text/engine_text.py --lang zh          # 生成 build/preview/engine_text/zh.toml
    python src/tools/text/engine_text.py --lang zh --check  # 只对比
    python src/tools/text/engine_text.py --lang zh --stats  # 额外打印各阶段改动条数
    python src/tools/text/engine_text.py --lang ja --diff   # 对比并逐条打印差异
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
ROOT = os.path.dirname(os.path.dirname(TOOLS))
OUT_DIR = os.path.join(ROOT, "build", "preview", "engine_text")

from text import entries, lang_rules, marks, toml_io  # noqa: E402
from text.lang_rules import spec as specs  # noqa: E402

def header(lang):
    return [
        "# 构建产物：由 src/tools/text/engine_text.py 从 "
        "src/translations/%s.toml 生成。" % lang,
        "# 不进仓库，删掉也没关系；改译文请改 src/translations/%s.toml，"
        "改规则请改 lang_rules/%s.py。" % (lang, lang),
    ]


def build(lang, doc, order=None):
    """{id: 译文} → {id: 引擎文本}。不写文件。

    只认 spec，不认语言：三段式接口统一走 lang_rules.spec.build_texts。
    标注（[town:…] / [lit:…]）在这里最先展开——语言规则完全看不到它们。
    """
    return build_full(lang, doc, order)[0]


def build_full(lang, doc, order=None):
    """同 build，但把统计和分词器名一起带出来（CLI 用）。"""
    order = list(order or doc)
    plain = marks.expand_doc(lang, doc)
    marks_n = sum(1 for h in order if plain.get(h) != doc.get(h))
    out, stats, seg = specs.build_texts(lang_rules.get_spec(lang), plain, order)
    stats["marks"] = marks_n
    stats["kinds"] = entries.tally([(h, plain[h]) for h in order if plain.get(h)],
                                   entries.verse_ids())
    return out, stats, seg


def out_path(lang):
    return os.path.join(OUT_DIR, "%s.toml" % lang)


def write(lang, out, order=None):
    """写 build/preview/engine_text/<lang>.toml，返回路径。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    return toml_io.write_doc(out_path(lang), out, order, header(lang))


def generate(lang):
    """从 src/translations/<lang>.toml 读译文并加工，返回 (order, out, stats, seg)。"""
    import translate as T
    path = T.lang_path(lang)
    if not os.path.isfile(path):
        raise SystemExit("没有 %s（译文层）" % path)
    doc, order = toml_io.read_doc(path)
    out, stats, seg = build_full(lang, doc, order)
    return order, out, stats, seg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--check", action="store_true", help="只对比，不写文件")
    ap.add_argument("--stats", action="store_true",
                    help="打印标点/连词/人名/补空格的改动条数与分词器")
    ap.add_argument("--diff", action="store_true",
                    help="对比时逐条打印差异（默认只打印前 5 条）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    order, out, stats, seg = generate(a.lang)

    if a.stats:
        print("生成 %d 条｜标注展开 %d｜标点改动 %d｜连词 %d｜人名 %d｜补空格 %d｜"
              "分词器 %s" % (
                  len(order), stats.get("marks", 0), stats["punct"], stats["conj"],
                  stats["name"], stats["space"], seg or "无（机械兜底）"))
        kinds = stats.get("kinds") or {}
        if kinds:
            print("分类：" + "｜".join("%s %d" % (k, n) for k, n in kinds.items()))

    if a.check:
        old = toml_io.read_doc_loose(out_path(a.lang))
        diff = [h for h in order if old.get(h) != out[h]]
        extra = [h for h in old if h not in out]
        if diff or extra:
            print("不一致 %d 条" % len(diff))
            for h in (diff if a.diff else diff[:5]):
                print("  %s\n    文件：%s\n    应为：%s" % (h, old.get(h), out[h]))
            if extra:
                print("  文件里多出 %d 条" % len(extra))
            return 1
        print("一致。")
        return 0

    if a.dry_run:
        return 0

    print("已生成", write(a.lang, out, order))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
