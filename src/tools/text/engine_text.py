# -*- coding: utf-8 -*-
r"""engine_text.py —— 译文层 → 引擎层（构建期产物）。

分层
----
    src/translations/<lang>.toml   干净译文，唯一手改层，入库
            ↓ 本模块（标点 / 连词 / 人名 / 按词补空格）
    build/engine_text/<lang>.toml  引擎文本，构建产物，不进仓库
            ↓ compile_pack
    build/PR2Packs/<lang>.txt      语言包

只有一份真相源：译文层。引擎层随时可以从头重建，删掉它不影响构建。

语言分派
--------
    spec = lang_rules.get_spec(lang)   # 标点 / 分词器 / 补空格，见 lang_rules/spec.py
    zh     标点全角化 + 连词后空格 + 人名空格 + 按词补空格（Spacing mode=group）
    ja     助词后空格 + 标点规范化（Spacing mode=particle）
    其他   原样返回（Spacing mode=none，用空格分词的语言不需要加工）

新语言只写一个 lang_rules/<代码>.py 声明 spec()，本模块不需要改。

补空格「按词成组」的标准是**字数预算**，不是像素 —— 控件宽度没有在游戏里
实测过，用字体算出来的 px 只是推测，不能当判据。

用法
----
    python src/tools/text/engine_text.py --lang zh          # 生成 build/engine_text/zh.toml
    python src/tools/text/engine_text.py --lang zh --check  # 只对比
"""

import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
ROOT = os.path.dirname(os.path.dirname(TOOLS))
OUT_DIR = os.path.join(ROOT, "build", "engine_text")


def _order_of(path):
    return [m.group(1) for m in
            (re.match(r'^"([^"]+)"\s*=', ln) for ln in io.open(path, encoding="utf-8"))
            if m]


def build(lang, doc, order=None):
    """{id: 译文} → {id: 引擎文本}。不写文件。

    只认 spec，不认语言：三段式接口统一走 lang_rules.spec.build_texts。
    """
    from text import lang_rules
    from text.lang_rules import spec as specs
    order = list(order or doc)
    out, _stats, _seg = specs.build_texts(lang_rules.get_spec(lang), doc, order)
    return out


def write(lang, out, order=None):
    """写 build/engine_text/<lang>.toml，返回路径。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "%s.toml" % lang)
    order = list(order or out)
    header = ("# 构建产物：由 src/tools/text/engine_text.py 从 "
              "src/translations/%s.toml 生成。\n"
              "# 不进仓库，删掉也没关系；改译文请改 src/translations/%s.toml。\n"
              % (lang, lang))
    lines = [header.rstrip("\n")]
    for h in order:
        lines.append('"%s" = "%s"' % (h, _esc(out[h])))
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    return path


def _esc(t):
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def generate(lang):
    """从 src/translations/<lang>.toml 读译文并加工，返回 (order, out)。"""
    import translate as T
    path = T.lang_path(lang)
    if not os.path.isfile(path):
        raise SystemExit("没有 %s（译文层）" % path)
    doc = tomllib.load(open(path, "rb"))
    order = _order_of(path)
    return order, build(lang, doc, order)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    order, out = generate(a.lang)
    path = os.path.join(OUT_DIR, "%s.toml" % a.lang)

    if a.check:
        old = {}
        if os.path.isfile(path):
            try:
                old = tomllib.load(open(path, "rb"))
            except Exception:
                old = {}
        diff = [h for h in order if old.get(h) != out[h]]
        if diff:
            print("不一致 %d 条" % len(diff))
            for h in diff[:5]:
                print("  %s\n    文件：%s\n    应为：%s" % (h, old.get(h), out[h]))
            return 1
        print("一致。")
        return 0

    print("已生成", write(a.lang, out, order))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
