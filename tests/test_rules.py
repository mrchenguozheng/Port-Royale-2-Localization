# -*- coding: utf-8 -*-
"""规则层的小样本测试：改规则前后跑一遍，防止回归。

补空格是「按词成组 + 字数预算」，**不按像素**（控件宽度没在游戏里实测过，
px 只是推测）。所以这里只测字数预算的行为，不测任何宽度数字。
"""

import os
import sys
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "tools", "text"))

from text import apply_zh_rules as ZH  # noqa: E402
from text import engine_text as ET  # noqa: E402
from text import zh_space  # noqa: E402
import lang_rules  # noqa: E402
from text.lang_rules import spec as specs  # noqa: E402

TRANS = os.path.join(ROOT, "src", "translations")


def two_chars(run):
    """假分词器：每两个字一个词，用于测 pack/spaced 而不依赖真分词器。"""
    return [run[i:i + 2] for i in range(0, len(run), 2)]


class TestZhText(unittest.TestCase):
    def test_punctuation_converted(self):
        zh = lang_rules.get("zh")
        self.assertEqual(zh.normalize("你好,世界!"), "你好，世界！")

    def test_ascii_token_kept(self):
        """半角记号内部的标点不转全角：版本号、时间、文件名、英文词。"""
        zh = lang_rules.get("zh")
        for src, want in (
            ("版本 1.0.0 已发布", "版本 1.0.0 已发布"),
            ("每天 12:30 开市", "每天 12:30 开市"),
            ("缺少 14x14aaFHk.res 文件", "缺少 14x14aaFHk.res 文件"),
            ("Port Royale 2!", "Port Royale 2!"),
            ("你好,世界!", "你好，世界！"),
        ):
            self.assertEqual(zh.normalize(src), want)

    def test_punct_context(self):
        from text.lang_rules import base
        t = "版本 1.0.0 已发布, 端口 Port Royale 2 在 12:30 开市"
        self.assertEqual(base.punct_context(t, t.index(", ")), base.CTX_CJK)
        self.assertEqual(base.punct_context(t, t.index("1.0.0") + 1), base.CTX_NUM)
        self.assertEqual(base.punct_context(t, t.index("12:30") + 2), base.CTX_TIME)
        lo, hi = base.ascii_token(t, t.index("Royale"))
        self.assertEqual(t[lo:hi], "Royale")

    def test_non_cjk_entry_untouched(self):
        """整条没有汉字就不是中文正文：算式、字体名、英文人名一个空格都别动。"""
        spec = lang_rules.get_spec("zh").spacing
        for src in (
            "%1 %2  +  %3 %4  +  %5 %6  =  %7",
            "Tiepolo_black14x14aaFHk.res",
            "Dirk Niestadtkötter",
        ):
            self.assertEqual(spec.apply(src, {}), src)

    def test_placeholder_kept(self):
        zh = lang_rules.get("zh")
        out = zh.normalize("支付 @g$TotalPrice$ 元")
        self.assertIn("@g$TotalPrice$", out)

    def test_fix_conj(self):
        self.assertEqual(ZH.fix_conj("，因此只有"), "，因此 只有")
        self.assertEqual(ZH.fix_conj("，因此 只有"), "，因此 只有")
        self.assertEqual(ZH.fix_conj("因 此"), "因此")

    def test_space_tokens(self):
        self.assertEqual(
            ZH.space_tokens("在1502 年元旦—— 就这样<n><n>下一段"),
            "在 1502 年元旦 —— 就这样 <n><n> 下一段")
        self.assertEqual(ZH.space_tokens("<n><n> 开头"), "<n><n> 开头")
        self.assertEqual(ZH.space_tokens("<o:0xFF131512>年"), "<o:0xFF131512>年")

    def test_names_with_titles_and_quotes(self):
        with open(os.path.join(TRANS, "zh.toml"), "rb") as f:
            doc = tomllib.load(f)
        given, surn, extras, _towns = ZH.build_names(doc)
        spans = ZH.find_names("自伊丽莎白女王时代", given, surn, extras)
        self.assertEqual([("自伊丽莎白女王时代")[a:b] for a, b in spans], ["伊丽莎白女王"])
        spans = ZH.find_names("亨利八世国王和教宗", given, surn, extras)
        self.assertEqual([("亨利八世国王和教宗")[a:b] for a, b in spans], ["亨利八世国王"])
        txt = "亨利·摩根爵士 出任"
        spans = ZH.find_names(txt, given, surn, extras)
        self.assertEqual([txt[a:b] for a, b in spans], ["亨利·摩根爵士"])
        self.assertEqual(ZH.pad_names(txt, spans), "亨利·摩根爵士 出任")
        # 引号里的船名不按人名处理
        spans = ZH.find_names("「安妮女王复仇号」", given, surn, extras)
        self.assertEqual(spans, [])
        # 中间点不能被空格拆开
        spans = ZH.find_names("胡安·德·塞普尔维达之类", given, surn, extras)
        self.assertEqual([("胡安·德·塞普尔维达之类")[a:b] for a, b in spans],
                         ["胡安·德·塞普尔维达"])


class TestZhSpace(unittest.TestCase):
    def test_pack_counts_chars(self):
        self.assertEqual(zh_space.pack(["你好", "世界", "这是"], 5), "你好世界 这是")
        self.assertEqual(zh_space.pack(["你好", "世界"], 4), "你好世界")
        # 单个词超预算时自成一组，不会被切碎
        self.assertEqual(zh_space.pack(["总督府"], 1), "总督府")

    def test_bind_glues_particles(self):
        self.assertEqual(zh_space.bind(["总督", "的", "府"]), ["总督的", "府"])

    def test_spaced_keeps_tags_and_names(self):
        self.assertEqual(zh_space.spaced("你好世界", two_chars, 2), "你好 世界")
        self.assertEqual(zh_space.spaced("你好<n>世界", two_chars, 2), "你好<n>世界")
        self.assertEqual(zh_space.spaced("胡安·德·塞普尔维达来了", two_chars, 2),
                         "胡安·德·塞普尔维达来了")

    def test_collect_runs(self):
        runs = zh_space.collect_runs(["短句", "这是一个足够长的中文句子用来收集并测试断行"])
        self.assertEqual(runs, ["这是一个足够长的中文句子用来收集并测试断行"])
        # 阈值 = MIN_RUN（6）：断点按词挑，短片段也会被断，所以也得进分词器；
        # 低于阈值的仍不送出去，免得拖慢分词。
        self.assertEqual(zh_space.collect_runs(["短句"]), [])
        self.assertEqual(zh_space.collect_runs(["六个字的句子"]), ["六个字的句子"])
        self.assertEqual(zh_space.collect_runs(["胡安·德·塞普尔维达到来这里看看"]),
                         ["胡安·德·塞普尔维达到来这里看看"])

    def test_fallback_wrap(self):
        t = "这是一个非常长的没有空格的中文句子用来测试自动断行"
        out = zh_space.fallback_wrap(t)
        self.assertIn(" ", out)
        self.assertNotIn("  ", out)
        self.assertEqual(zh_space.fallback_wrap("短句"), "短句")

    def test_compact_leaves_short_text_alone(self):
        """紧凑排版：不到预算就一个字都不动，标点旁也不插空格。"""
        whole = lambda run: [run]
        self.assertEqual(zh_space.compact("我刚听说。", whole), "我刚听说。")
        self.assertEqual(zh_space.compact("我刚听说，一艘船沉了。", whole, 20),
                         "我刚听说，一艘船沉了。")

    def test_compact_breaks_on_particle_not_mid_word(self):
        """超预算时才断，且断点落在停顿字「的」后面，不切「英格兰/船」。"""
        lookup = lambda run: ["一艘", "满载", "移民", "的",
                              "英格兰", "船", "沉了"]
        out = zh_space.compact("我刚听说，一艘满载移民的英格兰船沉了。", lookup, 10)
        self.assertTrue(out.startswith("我刚听说，"))
        self.assertIn(" ", out)
        self.assertNotIn("英格兰 船", out)

    def test_compact_budget_runs_across_punctuation(self):
        """多短句段落：预算按「距上一个空格」算，每句都短也要断，否则整段空白。"""
        lookup = lambda run: [run[i:i + 2] for i in range(0, len(run), 2)]
        t = "你可以在市场买货，也可以去酒馆打听消息，还可以去码头找船长领任务。"
        out = zh_space.compact(t, lookup, 8)
        self.assertIn(" ", out)
        for tok in out.split(" "):
            han = sum(1 for c in tok if "\u4e00" <= c <= "\u9fff")
            self.assertLessEqual(han, 8, tok)

    def test_compact_budget_runs_across_vars(self):
        """`%1` 这类行内变量不能把预算清零，否则「9 字 + %1 + 16 字」仍是超长 token。"""
        lookup = lambda run: [run[i:i + 2] for i in range(0, len(run), 2)]
        t = "那个恶名昭著的海盗%1所在的藏身处如今已不是什么秘密了。"
        out = zh_space.compact(t, lookup, 10)
        self.assertIn(" ", out)

    def test_compact_keeps_name_intact(self):
        """带间隔号的人名整体不被切开，也不能把整句吞成一个「人名」。"""
        words = ["当时", "的", "捕海盗人", "罗伯特·梅纳德", "追踪", "到", "了",
                 "他", "的", "单桅帆船"]
        lookup = lambda run: words if run == "当时的捕海盗人罗伯特·梅纳德追踪到了他的单桅帆船" else list(run)
        t = "当时的捕海盗人罗伯特·梅纳德追踪到了他的单桅帆船。"
        out = zh_space.compact(t, lookup, 10)
        self.assertIn("罗伯特·梅纳德", out)
        for tok in out.split(" "):
            han = sum(1 for c in tok if "\u4e00" <= c <= "\u9fff")
            self.assertLessEqual(han, 10, tok)

    def test_compact_never_breaks_after_lead_char(self):
        """断点不能落在「从/在/也/和」这类往后粘的字后面，否则前半截成了残句。"""
        words = ["你的目标", "是", "从", "一个", "默默无闻", "的", "商人"]
        lookup = lambda run: words if run == "你的目标是从一个默默无闻的商人" else list(run)
        out = zh_space.compact("你的目标是从一个默默无闻的商人。", lookup, 9)
        for prefix in ("从 ", "在 ", "也 ", "和 ", "与 ", "把 ", "被 ", "将 "):
            self.assertNotIn(prefix, out)

    def test_compact_treats_parameterized_break_as_hard(self):
        """`<n:25>` 也算换行：预算要在它那里清零，不能把两段粘成一条超长 token。"""
        lookup = lambda run: [run[i:i + 2] for i in range(0, len(run), 2)]
        t = "第一段话就在这里结束。<n:25>第二段话从这里重新开始算预算，不要接着上一段累加。"
        out = zh_space.compact(t, lookup, 9)
        self.assertIn("<n:25>", out)
        head, tail = out.split("<n:25>")
        self.assertTrue(tail)
        for tok in tail.split(" "):
            self.assertLessEqual(len(tok), 12, tok)

    def test_compact_breaks_after_var_not_before(self):
        """断点紧邻变量时优先落在变量**之后**：数字后面起行是自然断法。

        实测背景：`你还需要%1才能升到下一级`（重量 4+3+7=14）只差一点就得断一刀，
        旧 DP 把这一刀切在 `%1` 之前，剩下 `%1才能升到下一级` 连成 9 字，窄提示条
        放不下、整行被引擎丢掉。切在 `%1` 之后是 7 / 7，两行都放得下。
        """
        lookup = lambda run: [run[i:i + 2] for i in range(0, len(run), 2)]
        out = zh_space.compact("你还需要%1才能升到下一级", lookup, 13)
        self.assertIn("%1 ", out)
        self.assertNotIn(" %1", out)

    def test_cut_cost_around_var(self):
        """变量之后的断点免单，但变量之前不免费；下一件是粘连字/连词时也不免单。

        直接钉在 `_cut_cost()` 上，避免靠一句人造文本间接验证（人造文本里
        两侧代价可能打平，断点落在哪里取决于 DP 的扫描顺序）。
        """
        block = [("你还需要", 4, False), ("%1", 3, False), ("才能升到下一级", 7, False)]
        n = len(block)
        self.assertEqual(zh_space._cut_cost(block, 1, 2, n), 0)   # 变量之后：免单
        self.assertEqual(zh_space._cut_cost(block, 0, 1, n), 2)   # 变量之前：原价

        blocked = [("他提到了", 4, False), ("%1", 3, False), ("和奥格斯堡", 5, False)]
        self.assertEqual(zh_space._cut_cost(blocked, 1, 2, len(blocked)), 10)

        particle = [("这艘船", 3, False), ("%1", 3, False), ("的船队", 4, False)]
        self.assertEqual(zh_space._cut_cost(particle, 1, 2, len(particle)), 10)

    def test_compact_no_run_longer_than_budget(self):
        """连续 15 个字之内必须有一个断点：没有任何标点的长句也得被切开。"""
        lookup = lambda run: [run[i:i + 2] for i in range(0, len(run), 2)]
        t = "他沿着海岸线一路向北航行经过无数个无名小岛最后抵达了那片传说中的海域"
        out = zh_space.compact(t, lookup, 15)
        for tok in out.split(" "):
            han = sum(1 for c in tok if "\u4e00" <= c <= "\u9fff")
            self.assertLessEqual(han, 15, tok)
        self.assertGreaterEqual(out.count(" "), 2)


class TestSpecInterface(unittest.TestCase):
    """三段式接口：语言只声明 spec，engine_text 不认语言。"""

    def test_zh_spec_parts(self):
        sp = lang_rules.get_spec("zh")
        self.assertEqual((sp.code, sp.spacing.mode), ("zh", "compact"))
        self.assertIn(sp.segmenter.name, ("spacy", "none"))
        self.assertEqual(sp.punct.normalize("你好,世界!"), "你好，世界！")

    def test_ja_spec_parts(self):
        sp = lang_rules.get_spec("ja")
        self.assertEqual((sp.code, sp.spacing.mode), ("ja", "particle"))
        self.assertIn(sp.segmenter.name, ("janome", "fugashi", "none"))
        # 助词空格属于补空格策略，标点接口本身不补
        self.assertEqual(sp.punct.normalize("テスト。"), "テスト。")

    def test_unknown_language_passes_through(self):
        sp = lang_rules.get_spec("en")
        self.assertIsNone(sp.punct)
        self.assertEqual(sp.spacing.mode, "none")
        doc = {"0x1": "Hello  world"}
        out, _stats, _seg = specs.build_texts(sp, doc, ["0x1"])
        self.assertEqual(out, doc)

    def test_fr_spec_parts(self):
        """法语：构建期不加工——排版（NBSP）已经写在译文里。"""
        sp = lang_rules.get_spec("fr")
        self.assertEqual((sp.code, sp.spacing.mode), ("fr", "none"))
        self.assertIsNone(sp.punct)
        self.assertIsNone(sp.segmenter.tag("x"))
        doc = {"0x1": "Vraiment\u00a0? Or\u00a0: 100", "0x2": "%1:%2:%3"}
        out, _stats, _seg = specs.build_texts(sp, doc, ["0x1", "0x2"])
        self.assertEqual(out, doc)

    def test_skip_languages_are_declared(self):
        """de/es/ru/ko/fr 不加工，但必须是「显式声明」：模块在、理由在、行为确定。"""
        for lang in ("de", "es", "ru", "ko", "fr"):
            mod = lang_rules.get(lang)
            self.assertIsNotNone(mod, lang)
            self.assertTrue(getattr(mod, "SKIP", "").strip(), lang)
            sp = lang_rules.get_spec(lang)
            self.assertEqual(sp.code, lang)
            self.assertIsNone(sp.punct)
            self.assertEqual(sp.spacing.mode, "none")
            doc = {"0x1": "Fass 10? x: 1"}
            out, _stats, _seg = specs.build_texts(sp, doc, ["0x1"])
            self.assertEqual(out, doc)

    def test_build_texts_matches_engine_text(self):
        doc = {"0x1": "你好,世界。"}
        out, _stats, _seg = specs.build_texts(lang_rules.get_spec("zh"), doc, ["0x1"])
        self.assertEqual(out, ET.build("zh", doc, ["0x1"]))


class TestEngineText(unittest.TestCase):
    def test_build_zh_no_pixel_and_no_double_space(self):
        doc = {"0x1": "你好,世界。"}
        out = ET.build("zh", doc, ["0x1"])["0x1"]
        self.assertNotIn(",", out)
        self.assertNotIn("  ", out)

    def test_build_ja(self):
        doc = {"0x1": "これは テストです。"}
        out = ET.build("ja", doc, ["0x1"])["0x1"]
        self.assertIsInstance(out, str)
        self.assertTrue(out)

    def test_build_passthrough(self):
        doc = {"0x1": "Hello world"}
        self.assertEqual(ET.build("en", doc, ["0x1"]), doc)

    def test_ja_generate_from_pure(self):
        ja = lang_rules.get("ja")
        self.assertEqual(
            ET.build("ja", {"0x1": "テスト。"}, ["0x1"]).get("0x1"),
            ja.normalize("テスト。", particles=True))

    def test_zh_keys_preserved(self):
        doc = {"0x1": "你好", "0x2": "世界"}
        order, out, _stats, _seg = ZH.generate_doc(doc, list(doc))
        self.assertEqual(order, ["0x1", "0x2"])
        self.assertEqual(set(out), set(doc))
        # 译文层必须是完整的一份（键集与原文对齐由 tests/test_validate.py 之外的人工流程保证）
        with open(os.path.join(TRANS, "zh.toml"), "rb") as f:
            cur = tomllib.load(f)
        self.assertGreater(len(cur), 3000)


if __name__ == "__main__":
    unittest.main()
