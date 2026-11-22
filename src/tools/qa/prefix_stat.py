"""统计各语言译文里位置／国家占位的前文，判断替身该带什么形态。

用法：

    python -X utf8 src/tools/qa/prefix_stat.py            # 默认 fr es de pl ru
    python -X utf8 src/tools/qa/prefix_stat.py fr es      # 指定语言

对每个占位分别统计「前一词」（按词边界取，不是按字符窗口硬截）与「前 20 字符」，
全量输出，并写 `build/qa/prefix_<lang>.txt`。

旧版只打 `most_common(8)`、前文按 10 字符截，读出来是 `'ofesseur. '`、`'rtenant à '`
这种断词碎片；判定「介词 + 裸国名」时全靠猜。要看的前文实际是「前一个词」，所以
两列都给。
"""
import collections
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, ROOT)

from text import toml_io  # noqa: E402

POS = re.compile(r"@[ldrM]\$[^$]*\$")
NAT = re.compile(r"@n\$[^$]*\$")
LAST = re.compile(r"[^\W\d_]+['’]?$", re.UNICODE)
DEFAULT_LANGS = ["fr", "es", "de", "pl", "ru"]


def prev_word(pre):
    m = LAST.search(pre.rstrip())
    return m.group(0) if m else ""


def stat(tr, rx):
    pairs = collections.Counter()
    for key, entry in tr.items():
        t = entry.get("default", "") if isinstance(entry, dict) else str(entry or "")
        for m in rx.finditer(t):
            pre = t[:m.start()]
            pairs[(prev_word(pre), pre[-20:].replace("\n", "\\n"))] += 1
    return pairs


def main():
    langs = sys.argv[1:] or DEFAULT_LANGS
    for lang in langs:
        path = os.path.join(ROOT, "src", "translations", lang + ".toml")
        if not os.path.exists(path):
            sys.stderr.write("跳过 %s：没有 %s\n" % (lang, path))
            continue
        tr, _ = toml_io.read_doc(path)
        lines = []
        for label, rx in (("位置", POS), ("国家", NAT)):
            pairs = stat(tr, rx)
            total = sum(pairs.values())
            lines.append("== %s %s占位 %d 处" % (lang, label, total))
            for (word, ctx), n in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0])):
                lines.append("  %4d  prev=%-14r  ctx=%r" % (n, word, ctx))
            lines.append("")
        out = os.path.join(ROOT, "build", "qa", "prefix_%s.txt" % lang)
        with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
        print("\n".join(lines))
        print("写出", out)


if __name__ == "__main__":
    main()
