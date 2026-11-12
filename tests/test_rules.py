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
from text import apply_ja_rules as JA  # noqa: E402
from text import engine_text as ET  # noqa: E402
from text import zh_space  # noqa: E402
import lang_rules  # noqa: E402

TRANS = os.path.join(ROOT, "src", "translations")


def two_chars(run):
    """假分词器：每两个字一个词，用于测 pack/spaced 而不依赖真分词器。"""
    return [run[i:i + 2] for i in range(0, len(run), 2)]


class TestZhText(unittest.TestCase):
    def test_punctuation_converted(self):
        zh = lang_rules.get("zh")
        self.assertEqual(zh.normalize("你好,世界!"), "你好， 世界！")

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
        runs = zh_space.collect_runs(["短句", "这是一个足够长的中文句子用来收集"])
        self.assertEqual(runs, ["这是一个足够长的中文句子用来收集"])
        self.assertEqual(zh_space.collect_runs(["胡安·德·塞普尔维达到来这里看看"]), [])

    def test_fallback_wrap(self):
        t = "这是一个非常长的没有空格的中文句子用来测试自动断行"
        out = zh_space.fallback_wrap(t)
        self.assertIn(" ", out)
        self.assertNotIn("  ", out)
        self.assertEqual(zh_space.fallback_wrap("短句"), "短句")


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
        self.assertEqual(JA.generate_from({"0x1": "テスト。"}, ["0x1"]).get("0x1"),
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
