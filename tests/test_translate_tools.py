# -*- coding: utf-8 -*-
"""translate.py 的三个新入口回归：译完度判定、映射落盘、源缺失自查。

不碰真实译文：在临时 src\ 里造一份小 ko.toml，用 `T.set_src()` 把数据根
指过去，测完再指回来。
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src", "tools"))

import translate as T  # noqa: E402
from shared.core.validate import tokens  # noqa: E402
from text import toml_io as TI  # noqa: E402


class TestScriptDeclared(unittest.TestCase):
    def test_latin_langs_have_no_script(self):
        for lang in ("fr", "de", "es"):
            self.assertIsNone(T.lang_rules.script_re(lang), lang)

    def test_non_latin_langs_have_script(self):
        for lang in ("zh", "ja", "ko", "ru"):
            self.assertIsNotNone(T.lang_rules.script_re(lang), lang)


class TestIsTranslated(unittest.TestCase):
    def test_korean_needs_hangul(self):
        rx = T.lang_rules.script_re("ko")
        self.assertTrue(T.is_translated("안녕하세요", "ko", script=rx))
        self.assertFalse(T.is_translated("Hello there", "ko", script=rx))

    def test_chinese_without_hangul_is_not_korean(self):
        rx = T.lang_rules.script_re("ko")
        self.assertFalse(T.is_translated("你好，世界", "ko", script=rx))

    def test_japanese_needs_kana_not_kanji(self):
        rx = T.lang_rules.script_re("ja")
        self.assertTrue(T.is_translated("こちらは港です", "ja", script=rx))
        self.assertFalse(T.is_translated("这里是港口", "ja", script=rx))

    def test_symbol_only_entry_counts_as_done(self):
        rx = T.lang_rules.script_re("ko")
        for val in ("%1", "<n>", "12,000", "%1 / %2"):
            self.assertTrue(T.is_translated(val, "ko", script=rx), val)

    def test_latin_lang_compares_with_english(self):
        self.assertFalse(T.is_translated("Business", "fr", base="Business"))
        self.assertTrue(T.is_translated("Commerce", "fr", base="Business"))

    def test_tag_is_ignored_when_testing_content(self):
        rx = T.lang_rules.script_re("ko")
        self.assertFalse(T.is_translated("<c>Goods</c> <n>", "ko", script=rx))


class TestBand(unittest.TestCase):
    def test_band_edges(self):
        self.assertEqual(T.band_of("가" * 12), (0, 12))
        self.assertEqual(T.band_of("가" * 13), (13, 24))
        self.assertEqual(T.band_of("가" * 81), (81, None))


class TestLoadMap(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "m.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_accepts_wrapped_map(self):
        self._write('{"map": {"a": "甲"}}')
        self.assertEqual(T.load_map(self.path), {"a": "甲"})

    def test_strips_keys(self):
        self._write('{" a ": "甲"}')
        self.assertEqual(T.load_map(self.path), {"a": "甲"})


class TestApplyMap(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "src")
        os.makedirs(os.path.join(self.src, "translations"))
        os.makedirs(os.path.join(self.src, "orig"))
        self.old_src = T.SRC
        T.set_src(self.src)
        self.path = os.path.join(self.src, "translations", "ko.toml")
        self.doc = {"0xa1": " Hello ", "0xa2": "World",
                    "0xa3": "Take %1 now", "0xa4": "안녕",
                    "0xa5": "Get %1 and %2 now"}
        TI.write_doc_atomic(self.path, self.doc, list(self.doc), ["# 头"])

    def tearDown(self):
        T.set_src(self.old_src)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _read(self):
        doc, order = TI.read_doc(self.path)
        self.assertEqual(order, list(self.doc))
        return doc

    def test_hit_writes_and_keeps_edge_spaces(self):
        stats = T.apply_map("ko", {"Hello": "안녕하세요", "Nope": "없음"})
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(stats["unused"], ["Nope"])
        self.assertEqual(self._read()["0xa1"], " 안녕하세요 ")

    def test_second_run_is_idempotent(self):
        T.apply_map("ko", {"Hello": "안녕하세요"})
        again = T.apply_map("ko", {"Hello": "안녕하세요"})
        self.assertEqual(again["hit"], 0)
        self.assertGreaterEqual(again["applied"], 1)
        self.assertEqual(again["unused"], [])

    def test_english_value_is_refused_as_translation(self):
        stats = T.apply_map("ko", {"안녕": "Hello"})
        self.assertEqual(stats["hit"], 0)
        self.assertEqual(len(stats["lang"]), 1)
        self.assertEqual(self._read()["0xa4"], "안녕")

    def test_keep_entry_may_be_written_back_to_english(self):
        """名单内的职员表：写回英文原名是修正，不是抄错行。"""
        os.makedirs(os.path.join(self.src, "data", "keep_as_is"))
        with open(os.path.join(self.src, "data", "keep_as_is", "ko.txt"),
                  "w", encoding="utf-8") as f:
            f.write("0xa4\tcredit\n")
        stats = T.apply_map("ko", {"0xa4": "Hello"})
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(stats["lang"], [])
        self.assertEqual(self._read()["0xa4"], "Hello")

    def test_translated_entry_can_be_corrected(self):
        stats = T.apply_map("ko", {"안녕": "안녕하십니까"})
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(stats["rewrite"], 1)
        self.assertEqual(self._read()["0xa4"], "안녕하십니까")

    def test_hash_key_corrects_already_translated_entry(self):
        T.apply_map("ko", {"Hello": "안녕하세요"})
        stats = T.apply_map("ko", {"0xa1": "안녕하십니까"})
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(stats["unused"], [])
        self.assertEqual(self._read()["0xa1"], " 안녕하십니까 ")

    def test_bare_particle_blocks_the_write(self):
        stats = T.apply_map("ko", {"Take %1 now": "지금 %1를 가지세요"})
        self.assertEqual(stats["hit"], 0)
        self.assertEqual(len(stats["josa"]), 1)
        self.assertEqual(self._read()["0xa3"], "Take %1 now")

    def test_paired_particle_is_allowed(self):
        stats = T.apply_map("ko", {"Take %1 now": "지금 %1(을)를 가지세요"})
        self.assertEqual(stats["hit"], 1)

    def test_one_paired_form_does_not_excuse_another_bare(self):
        """同一句里 `%1이(가)` 与 `%2로` 并存：后者仍是错的，不许整条放过。"""
        stats = T.apply_map("ko", {"Get %1 and %2 now": "%1이(가) 나오면 %2로 가세요"})
        self.assertEqual(stats["hit"], 0)
        self.assertEqual([h for h, _ in stats["josa"]], ["0xa5"])
        self.assertEqual(self._read()["0xa5"], "Get %1 and %2 now")

    def test_every_bare_particle_is_listed(self):
        """一条里两处裸助词：两处都印，不是只印第一处。"""
        stats = T.apply_map("ko", {"Get %1 and %2 now": "%1를 %2를 가지세요"})
        self.assertEqual([t for _, t in stats["josa"]], ["%1를", "%2를"])

    def test_reversed_paired_order_blocks_the_write(self):
        """`%1를(을)` 反序：语义没错，但与全库 `%1을(를)` 不一致，落盘前改掉。"""
        stats = T.apply_map("ko", {"Take %1 now": "지금 %1를(을) 가지세요"})
        self.assertEqual(stats["hit"], 0)
        self.assertEqual([t for _, t in stats["pair"]], ["%1를(을)"])
        self.assertEqual(self._read()["0xa3"], "Take %1 now")

    def test_canonical_paired_order_passes(self):
        stats = T.apply_map("ko", {"Take %1 now": "지금 %1(을)를 가지세요"})
        self.assertEqual(stats["pair"], [])

    def test_bare_particle_after_graphic_tag_blocks_the_write(self):
        """`<g:…>` 后面跟裸助词与占位符同类；`<n>이` 那种正文词不算（34 条误报的来源）。"""
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write('"0xa6" = "<g:INTEXT_GOLD_800x600.screen> 받았습니다"\n')
        bad = T.apply_map("ko", {"0xa6": "<g:INTEXT_GOLD_800x600.screen>를 받았습니다"},
                          dry_run=True)
        self.assertEqual(bad["hit"], 0)
        self.assertEqual([t for _, t in bad["josa"]],
                         ["<g:INTEXT_GOLD_800x600.screen>를"])

    def test_plain_tag_before_word_is_not_a_particle_site(self):
        """`<n>이 마을은…` 里的「이」是正文冠词性指示词，不是助词，不许拦。"""
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write('"0xa6" = "<n>This town"\n')
        ok = T.apply_map("ko", {"0xa6": "<n>이 마을"}, dry_run=True)
        self.assertEqual(ok["hit"], 1)
        self.assertEqual(ok["josa"], [])

    def test_placeholder_base_allows_real_text(self):
        """英文基准是 `IDM_…_TEXT` 时没有可比模板：补正文不拦 token／标签门。"""
        en = os.path.join(self.src, "orig", "en.gog_1.1.2.3.toml")
        TI.write_doc_atomic(
            en, {"0xa1": "Hello", "0xa2": "World",
                 "0xa3": "IDM_CONTEST_01_2004_LOG_00_TEXT",
                 "0xa4": "Hi", "0xa5": "Get %1 and %2 now"},
            ["0xa1", "0xa2", "0xa3", "0xa4", "0xa5"], ["# 头"])
        stats = T.apply_map("ko", {"0xa3": "<n>지금 %1(을)를 가지세요"}, dry_run=True)
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(stats["tokens"], [])
        self.assertEqual(stats["tag"], [])

    def test_wrong_counter_blocks_the_write(self):
        """`%1 물자`（缺量词）在落盘前就拦下，不再等 text_lint 那一步。"""
        try:
            import kiwipiepy                       # noqa: F401
        except ImportError:
            self.skipTest("kiwipiepy 不在，量词检查整条跳过")
        stats = T.apply_map("ko", {"Take %1 now": "지금 %1 물자 가지세요"})
        self.assertEqual(stats["hit"], 0)
        self.assertTrue(stats["unit"], "缺量词应当在 apply 阶段被拦")
        self.assertEqual(self._read()["0xa3"], "Take %1 now")

    def test_tag_loss_blocks_the_write(self):
        """`<n>` 少一个、字体名写错一个字母，落盘前就拦（占位符检查管不到标签）。"""
        os.makedirs(os.path.join(self.src, "data", "keep_as_is"), exist_ok=True)
        stats = T.apply_map("ko", {"0xa1": "안녕"}, dry_run=True)
        self.assertEqual(stats["hit"], 1)          # 基线试探：无标签两侧都空
        # 造一条带标签的条目再试
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write('"0xa6" = "<n>Hello <f:fonts/AA.res> there"\n')
        bad = T.apply_map("ko", {"0xa6": "<n>안녕 <f:fonts/AAk.res>"}, dry_run=True)
        self.assertEqual(bad["hit"], 0)
        self.assertTrue(bad["tag"])
        self.assertIn("AAk.res", bad["tag"][0][1])

    def test_ids_filter_keeps_only_listed(self):
        """一个映射混两批时用 --ids 只落一批（源串键与 id 键都认）。"""
        args = T.build_parser().parse_args(
            ["apply", "--lang", "ko", "--map", "x.json", "--ids", "0xa2"])
        self.assertEqual(args.ids, "0xa2")

    def test_token_loss_blocks_the_write(self):
        stats = T.apply_map("ko", {"Take %1 now": "지금 가지세요"})
        self.assertEqual(stats["hit"], 0)
        self.assertEqual(stats["tokens"], ["0xa3"])
        self.assertEqual(self._read()["0xa3"], "Take %1 now")

    def test_duplicate_placeholder_counts(self):
        """原文同一个占位符出现两处、译文只留一处 → 拦下（集合比会漏）。"""
        self.assertTrue(T.token_diff("buy @G$Goods$ then @G$Goods$", "사고 @G$Goods$"))
        self.assertFalse(T.token_diff("@G$Goods$ @G$Goods$", "@G$Goods$ @G$Goods$"))

    def test_id_replay_is_counted_as_same_not_rewrite(self):
        """按 id 重放同一份映射：值没变就是「已是当前值」，不是「修正」。"""
        T.apply_map("ko", {"0xa1": "안녕하세요"})
        again = T.apply_map("ko", {"0xa1": "안녕하세요"})
        self.assertEqual(again["hit"], 0)
        self.assertEqual(again["rewrite"], 0)
        self.assertGreaterEqual(again["same"], 1)

    def test_dry_run_does_not_write(self):
        stats = T.apply_map("ko", {"Hello": "안녕하세요"}, dry_run=True)
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(self._read()["0xa1"], " Hello ")

    def test_reference_language_is_refused(self):
        with self.assertRaises(SystemExit):
            T.apply_map("en.gog_1.1.2.3", {"Hello": "안녕"})


class TestDumpLines(unittest.TestCase):
    """导出批次清单：分档、限条数、同源串撞车标记。"""

    def _es(self):
        return [
            {"id": "0xb1", "ko": "Short"},
            {"id": "0xb2", "ko": "A" * 90},
            {"id": "0xb3", "ko": "A" * 85},
            {"id": "0xb4", "ko": "이미 번역됨"},
        ]

    def test_long_band_selects_only_81_plus(self):
        lines = T.dump_lines(self._es(), "ko", (81, None), 0)
        rows = [l for l in lines if not l.startswith("#")]
        self.assertEqual([r.split("\t")[0] for r in rows], ["0xb2", "0xb3"])

    def test_limit_truncates_rows(self):
        lines = T.dump_lines(self._es(), "ko", (81, None), 1)
        rows = [l for l in lines if not l.startswith("#")]
        self.assertEqual(len(rows), 1)

    def test_header_states_counts(self):
        lines = T.dump_lines(self._es(), "ko", (81, None), 0)
        self.assertIn("该档 2 条", lines[0])
        self.assertTrue(lines[3].startswith("#"))

    def test_header_lists_whole_queue(self):
        """只报当前档看不见别档还剩多少；新表头把全队列各档一起列出来。"""
        lines = T.dump_lines(self._es(), "ko", (81, None), 0)
        self.assertIn("全队列", lines[1])
        self.assertIn(">80:2", lines[1])

    def test_order_short_takes_shortest_first(self):
        es = [{"id": "0xb2", "ko": "A" * 90},
              {"id": "0xb6", "ko": "C" * 120},
              {"id": "0xb7", "ko": "D" * 100}]
        rows = [l for l in T.dump_lines(es, "ko", (81, None), 2, order="short")
                if not l.startswith("#")]
        self.assertEqual([r.split("\t")[0] for r in rows], ["0xb2", "0xb7"])

    def test_ids_pick_ignores_band_and_limit(self):
        """同模板族按 id 单独成批：不受 `--band` 与 `--limit` 管。"""
        rows = [l for l in T.dump_lines(self._es(), "ko", (81, None), 1,
                                        ids=["0xb1", "0xb3"])
                if not l.startswith("#")]
        self.assertEqual([r.split("\t")[0] for r in rows], ["0xb1", "0xb3"])

    def test_ids_header_says_handpicked(self):
        lines = T.dump_lines(self._es(), "ko", None, 0, ids=["0xb1"])
        self.assertIn("手选批次：1 条", lines[0])

    def test_dump_defaults_to_shortest_first(self):
        """不写 `--order` 也按结构风险分层，纯文字先清、带标签最后。"""
        args = T.build_parser().parse_args(["dump", "--lang", "ko"])
        self.assertEqual(args.order, "risk")

    def test_risk_order_puts_plain_text_first_tags_last(self):
        es = [{"id": "0xb8", "ko": "<n>" + "A" * 90},
              {"id": "0xb9", "ko": "B" * 90},
              {"id": "0xba", "ko": "@A$USER$ " + "C" * 90}]
        rows = [l for l in T.dump_lines(es, "ko", (81, None), 0, order="risk")
                if not l.startswith("#")]
        self.assertEqual([r.split("\t")[0] for r in rows], ["0xb9", "0xba", "0xb8"])

    def test_ref_columns_are_appended(self):
        es = [{"id": "0xb9", "ko": "B" * 90, "zh": "中" * 40}]
        lines = T.dump_lines(es, "ko", (81, None), 0, ref_langs=("zh",))
        row = [l for l in lines if not l.startswith("#")][0]
        self.assertIn("\tzh=", row)
        self.assertIn("zh=zh", lines[2])

    def test_identical_sources_are_flagged(self):
        es = [{"id": "0xb2", "ko": "Same " + "A" * 85},
              {"id": "0xb3", "ko": "Same " + "A" * 85}]
        rows = [l for l in T.dump_lines(es, "ko", (81, None), 0)
                if not l.startswith("#")]
        self.assertIn("dup:2", rows[0])
        self.assertIn("0xb3", rows[0])

    def test_translated_entries_are_not_exported(self):
        rows = [l for l in T.dump_lines(self._es(), "ko", T.BAND_KEYS["all"], 0)
                if not l.startswith("#")]
        self.assertNotIn("0xb4", [r.split("\t")[0] for r in rows])

    def test_newlines_are_escaped(self):
        es = [{"id": "0xb5", "ko": "Line one\nLine two"}]
        rows = [l for l in T.dump_lines(es, "ko", T.BAND_KEYS["all"], 0)
                if not l.startswith("#")]
        self.assertEqual(len(rows), 1)
        self.assertIn("Line one\\nLine two", rows[0])


class TestTokensAreTheSameImplementation(unittest.TestCase):
    def test_token_set_order_free(self):
        self.assertEqual(sorted(tokens("A %1 <n> B")), sorted(tokens("%1 B <n> A")))


class TestKeepAsIs(unittest.TestCase):
    """有意不译：清单内的 id 不进待译，进度不再被按键名永久拖着。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "src")
        os.makedirs(os.path.join(self.src, "data", "keep_as_is"))
        self.old_src = T.SRC
        T.set_src(self.src)
        with open(os.path.join(self.src, "data", "keep_as_is", "ko.txt"),
                  "w", encoding="utf-8") as f:
            f.write("# 头\n0xb1\tkey\n0xb9\tcredit\n")

    def tearDown(self):
        T.set_src(self.old_src)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_listed_entry_leaves_pending(self):
        es = [{"id": "0xb1", "ko": "F1"}, {"id": "0xb2", "ko": "English"}]
        self.assertEqual(T.pending_ids(es, "ko"), ["0xb2"])

    def test_empty_when_no_file(self):
        T.set_src(self.src)
        os.remove(os.path.join(self.src, "data", "keep_as_is", "ko.txt"))
        self.assertEqual(T.keep_as_is("ko"), {})

    def test_common_baseline_is_shared_by_all_langs(self):
        """七语共用的职员表只在 _common.txt 写一遍，各语言文件不必抄。"""
        with open(os.path.join(self.src, "data", "keep_as_is", "_common.txt"),
                  "w", encoding="utf-8") as f:
            f.write("0xc1\tcredit\n0xc2\tsave-name\n")
        for lang in ("ko", "ja", "zh"):
            self.assertEqual(T.keep_as_is(lang).get("0xc1"), "credit")
        # 语言文件里的同名条目覆盖基线
        with open(os.path.join(self.src, "data", "keep_as_is", "ko.txt"),
                  "a", encoding="utf-8") as f:
            f.write("0xc2\tkey\n")
        self.assertEqual(T.keep_as_is("ko")["0xc2"], "key")
        self.assertEqual(T.keep_as_is("ja")["0xc2"], "save-name")


class TestDumpGroups(unittest.TestCase):
    """骨架分组：只差占位符/标签的条目归一组，导出时给一条代表句。"""

    def _es(self):
        return [
            {"id": "0xc1", "ko": "Loot the goods from %1 of the Twelve."},
            {"id": "0xc2", "ko": "Loot the goods from %2 of the Twelve."},
            {"id": "0xc3", "ko": "Loot the goods from %3 of the Twelve."},
            {"id": "0xc4", "ko": "Something completely different here."},
        ]

    def test_by_group_keeps_one_per_skeleton(self):
        rows = [l for l in T.dump_lines(self._es(), "ko", T.BAND_KEYS["all"], 0,
                                        True) if not l.startswith("#")]
        self.assertEqual([r.split("\t")[0] for r in rows], ["0xc1", "0xc4"])

    def test_group_marker_lists_mates(self):
        rows = [l for l in T.dump_lines(self._es(), "ko", T.BAND_KEYS["all"], 0)
                if not l.startswith("#")]
        self.assertIn("grp:3", rows[0])
        self.assertIn("0xc2", rows[0])

    def test_skeleton_collapses_vars_and_tags(self):
        self.assertEqual(T.skeleton("Take %1 <n> now"), T.skeleton("Take %2 <n> now"))


class TestNearPairs(unittest.TestCase):
    """近重复：只差一个词的成对条目要摆在一起，别各写一版。"""

    def test_similar_long_sentences_pair_up(self):
        es = [
            {"id": "0xd1", "ko": "You must be sure that the nation whose towns "
                                 "you want to capture is militarily weak here."},
            {"id": "0xd2", "ko": "You must be sure that the nation whose towns "
                                 "you want to capture is militarily strong here."},
            {"id": "0xd3", "ko": "Something else entirely."},
        ]
        pairs = T.near_pairs(es, "ko", min_ratio=0.90)
        self.assertEqual(len(pairs), 1)
        self.assertEqual({pairs[0][1], pairs[0][2]}, {"0xd1", "0xd2"})

    def test_short_sentences_are_skipped(self):
        es = [{"id": "0xd4", "ko": "Tools"}, {"id": "0xd5", "ko": "Toolz"}]
        self.assertEqual(T.near_pairs(es, "ko", min_ratio=0.90), [])


class TestOverrides(unittest.TestCase):
    """英文微调层：id 必须存在、token 必须与原版一致，白改要拦。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "src")
        os.makedirs(os.path.join(self.src, "orig"))
        os.makedirs(os.path.join(self.src, "overrides"))
        self.old_src = T.SRC
        T.set_src(self.src)
        raw = {"0xe1": "Take %1 now", "0xe2": "Second", "0xe3": "Third"}
        with open(os.path.join(self.src, "orig", "en.gog_1.1.2.3.toml"),
                  "w", encoding="utf-8") as f:
            for k, v in raw.items():
                f.write('"%s" = "%s"\n' % (k, v))
        with open(os.path.join(self.src, "overrides", "en.toml"),
                  "w", encoding="utf-8") as f:
            f.write('"0xe1" = "Take %2 now"\n')
            f.write('"0xe2" = "Second!"\n')
            f.write('"0xe4" = "Ghost"\n')
            f.write('"0xe3" = "Third"\n')

    def tearDown(self):
        T.set_src(self.old_src)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_load_overrides_reads_short_code(self):
        self.assertEqual(set(T.load_overrides("en")), {"0xe1", "0xe2", "0xe3", "0xe4"})

    def test_token_change_is_flagged(self):
        missing, bad_tok, noop = T.check_overrides("en")
        self.assertEqual(bad_tok, ["0xe1"])

    def test_missing_id_is_flagged(self):
        missing, bad_tok, noop = T.check_overrides("en")
        self.assertEqual(missing, ["0xe4"])

    def test_noop_is_flagged(self):
        missing, bad_tok, noop = T.check_overrides("en")
        self.assertEqual(noop, ["0xe3"])


if __name__ == "__main__":
    unittest.main()
