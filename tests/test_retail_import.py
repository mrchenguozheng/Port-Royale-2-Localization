"""零售参照导入：承标注规则与落盘行为。"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "tools"),
          os.path.join(ROOT, "src", "tools", "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)

import translate as T  # noqa: E402
from analysis import retail_import as RI  # noqa: E402
from text import toml_io as TI  # noqa: E402


class TestCarried(unittest.TestCase):
    """承标注是纯字符串搬运，用字面解析器就能测。"""

    def setUp(self):
        self.show = {"[town:Cartagena]": "Cartagena",
                     "[term:en_tools]": "Herramientas",
                     "[town:St. Augustine]": "San Agustín"}

    def _resolve(self, span, hid):
        return self.show.get(span, span)

    def test_mark_goes_back_to_its_place(self):
        body, why = RI.carried("La ciudad de [town:Cartagena] es rica.",
                               "La ciudad de Cartagena es muy rica.", self._resolve)
        self.assertIsNone(why)
        self.assertIn("[town:Cartagena]", body)
        self.assertNotIn("Cartagena es", body.replace("[town:Cartagena]", "X"))

    def test_display_text_differs_from_key(self):
        """`[town:St. Augustine]` 的参数是译名表的键，零售里是展开后的写法。"""
        body, why = RI.carried("Cerca de [town:St. Augustine] hay maíz.",
                               "Cerca de San Agustín hay maíz.", self._resolve)
        self.assertIsNone(why)
        self.assertIn("[town:St. Augustine]", body)

    def test_absent_display_text_refuses_the_row(self):
        body, why = RI.carried("Cerca de [town:Tortuga] hay agua.",
                               "Cerca de la isla hay agua.", self._resolve)
        self.assertIsNone(body)
        self.assertIn("不在参照里", why)

    def test_ambiguous_display_text_refuses_the_row(self):
        body, why = RI.carried("De [town:Cartagena] a Cartagena.",
                               "De Cartagena a Cartagena.", self._resolve)
        self.assertIsNone(body)
        self.assertIn("出现 2 次", why)

    def test_repeated_name_is_filled_by_ordinal(self):
        """一行里两处都写地名、两处都带标注：按先后交代，一个换一处。"""
        body, why = RI.carried(
            "Ve a [town:Cartagena].<n>Luego vuelve a [town:Cartagena] y vende.",
            "Ve a Cartagena.<n>Luego vuelve a Cartagena y vende.", self._resolve)
        self.assertIsNone(why)
        self.assertEqual(
            body, "Ve a [town:Cartagena].<n>Luego vuelve a [town:Cartagena] y vende.")

    def test_three_repeats_are_filled_in_order(self):
        body, why = RI.carried(
            "[town:Cartagena] es grande. En [town:Cartagena] hay un almacén. "
            "Sal de [town:Cartagena] pronto.",
            "Cartagena es grande. En Cartagena hay un almacén. Sal de Cartagena pronto.",
            self._resolve)
        self.assertIsNone(why)
        self.assertIn("[town:Cartagena] es grande", body)
        self.assertIn("Sal de [town:Cartagena] pronto", body)

    def test_fewer_places_than_marks_refuses(self):
        """标注两处、参照只写一处地名：没地方交代第二处，放弃。"""
        body, why = RI.carried(
            "Ve a [town:Cartagena].<n>Luego vuelve a [town:Cartagena] y vende.",
            "Ve a la ciudad.<n>Luego vuelve a Cartagena y vende.", self._resolve)
        self.assertIsNone(body)
        self.assertIn("标注 2 处", why)

    def test_missing_article_still_matches(self):
        """零售少写冠词（Habana），译名表是 La Habana：去掉冠词再认一次。"""
        self.show["[town:Havana]"] = "La Habana"
        body, why = RI.carried("Llegó a [town:Havana] de noche.",
                               "Llegó a Habana de noche.", self._resolve)
        self.assertIsNone(why)
        self.assertIn("[town:Havana] de noche", body)

    def test_riddle_and_ref_defer_to_other_stages(self):
        for mark in ("[riddle:答案]", "[ref:0xabc]"):
            body, why = RI.carried("x %s y" % mark, "x y", self._resolve)
            self.assertIsNone(body)
            self.assertIn("另一道工序", why)

    def test_long_riddle_mark_still_defers(self):
        # 诗谜的 arg 里带 `source=…@sha256=…`，上千字都有；按前缀判，不能因为长就漏掉。
        mark = "[riddle:answer=Tortuga;group=a,b,level=town;source=original-en" \
               "&manual:docs/x.md@sha256=" + "a" * 300 + "]"
        body, why = RI.carried("La ciudad que buscas es %s un lugar desierto." % mark,
                               "La ciudad que buscas es un lugar desierto.", self._resolve)
        self.assertIsNone(body)
        self.assertIn("另一道工序", why)

    def test_bracketed_reference_is_refused(self):
        body, why = RI.carried("Hola", "Hola [algo]", self._resolve)
        self.assertIsNone(body)
        self.assertIn("方括号", why)


class TestForeignWords(unittest.TestCase):
    """拉丁文字语言没有「字种」可判，只能按词典命中率判。"""

    def _known(self, words):
        vocab = set(words)

        def known(w):
            return w.lower() in vocab
        return known

    def test_spanish_sentence_passes(self):
        text = "La ciudad de Cartagena es muy rica y tiene muchas casas viejas"
        self.assertIsNone(RI.foreign_words(text, self._known(
            ["la", "ciudad", "de", "es", "muy", "rica", "y", "tiene", "muchas",
             "casas", "viejas"])))

    def test_german_row_is_flagged(self):
        # es 参照里真有一行是德语原文：字种、令牌、标签全对，只有词不是西语。
        text = "Sie sitzt seit vielen Tagen am Cap und winkt vorbeifahrenden Schiffe zu"
        hit, total = RI.foreign_words(text, self._known(["sie", "am"]))
        self.assertEqual((hit, total), (2, 12))

    def test_short_text_is_not_judged(self):
        self.assertIsNone(RI.foreign_words("Hola amigo",
                                           self._known(["hola"])))

    def test_no_dictionary_means_no_judgement(self):
        self.assertIsNone(RI.foreign_words(
            "Die Stadt ist sehr reich und hat viele alte Häuser am Hafen", None))

    def test_tokens_and_marks_are_masked_out(self):
        text = "%1 %2 [town:Cartagena] <n> <g:INTEXT.scr> La ciudad es rica y vieja"
        self.assertIsNone(RI.foreign_words(text, self._known(
            ["la", "ciudad", "es", "rica", "y", "vieja"])))


class TestRepair(unittest.TestCase):
    """结构修复只动 `<n>`／`<t>`，修不动就明确放弃。"""

    def test_missing_paragraph_break_is_inserted(self):
        base = "<g:x>A logo.<n>The logo is used."
        out = "<g:x>A logo. The logo is used."
        fixed, note = RI.repair_tags(base, out)
        self.assertEqual(fixed.count("<n>"), 1)
        self.assertIn("<n>", fixed)
        self.assertNotIn(".  ", fixed)
        self.assertIn("补 <n>", note)

    def test_paired_deficit_becomes_one_paragraph(self):
        """差额是 1，实际却要补两个 `<n>`：一段里两句并成了一段。"""
        base = "Uno.<n><n>Dos."
        out = "Primero es largo. Segundo es largo."
        fixed, note = RI.repair_tags(base, out)
        self.assertEqual(fixed.count("<n>"), base.count("<n>"))
        self.assertIn("<n>", fixed)
        self.assertIn("补 <n> 2", note)

    def test_surplus_breaks_are_removed_with_one_space(self):
        base = "<g:x>Fin de la costa.<n><g:x>La ciudad."
        out = "<g:x>Fin de la costa.<n><n><n><g:x>La ciudad."
        fixed, note = RI.repair_tags(base, out)
        self.assertEqual(fixed.count("<n>"), 1)
        self.assertNotIn(".La", fixed)
        self.assertIn("删 <n>", note)

    def test_bullet_is_restored_with_its_dash(self):
        base = "<g:x>-<t>Hay cinco tipos."
        out = "<g:x>Hay cinco tipos."
        fixed, note = RI.repair_tags(base, out)
        self.assertEqual(fixed, base)
        self.assertIn("补 <t>", note)

    def test_bullets_go_to_their_own_occurrences(self):
        """同一标签在一行里出现多次时，符号要按基准的第几处对齐，不能全塞在第一处。"""
        base = "<g:x>-<t>Uno.<n><g:x>Dos.<n><g:x>-<t>Tres."
        out = "<g:x>Uno.<n><g:x>Dos.<n><g:x>Tres."
        fixed, _ = RI.repair_tags(base, out)
        self.assertEqual(fixed, base)

    def test_parameterized_break_is_restored_from_base(self):
        """`<n:25>` 也是换行标签：个数跟基准一样，参数照抄基准那一个，不自己编。"""
        base = "<n:25>Texto largo y tendido."
        out = "Texto largo y tendido."
        fixed, why = RI.repair_tags(base, out)
        self.assertIsNotNone(fixed)
        self.assertEqual(fixed.count("<n:25>"), 1)
        self.assertIn("补 <n:25> 1", why)

    def test_parameterized_break_is_removed_when_base_has_none(self):
        """基准没有 `<n:25>`、零售有：按个数删掉，不留多出来的段标记。"""
        base = "Texto largo y tendido."
        out = "Texto largo<n:25>y tendido."
        fixed, why = RI.repair_tags(base, out)
        self.assertNotIn("<n:25>", fixed)
        self.assertIn("删 <n:25> 1", why)

    def test_pair_deficit_break_goes_to_a_clause_not_mid_word(self):
        """一行一句、没有句末标点：退到逗号分句处，不能在词中间断。"""
        base = ("Ahora, localiza la ciudad y envía tu convoy allí.<n>"
                "La campaña termina al llegar.")
        out = "Ahora, localiza la ciudad y envía tu convoy allí."
        fixed, _ = RI.repair_tags(base, out)
        self.assertEqual(fixed.count("<n>"), 1)
        self.assertRegex(fixed, r",<n>")

    def test_percent_column_is_normalized(self):
        """零售把「`%2` 制表 `%3%`」写成「`%2` 空格 `(%3%)`」，按基准还原。"""
        base = "%2<t>%3%<t>%4"
        out = "%2    (%3%)<t>%4"
        fixed, note = RI.repair_tags(base, out)
        self.assertEqual(fixed, base)
        self.assertIn("还原百分列 1", note)

    def test_percent_columns_all_occurrences(self):
        base = "%2<t>%3%<t>%4<n>%5<t>%6%<t>%7"
        out = "%2    (%3%)<t>%4<n>%5\t(%6%)<t>%7"
        fixed, _ = RI.repair_tags(base, out)
        self.assertEqual(fixed, base)

    def test_percent_parenthesis_without_base_pattern_is_not_guessed(self):
        """基准那一处不是 `%A<t>%B%<t>`，就不能把括注自行拆开。"""
        base = "Coste %1<t>%2<t>%3"
        out = "Coste %1    (%2%)<t>%3"
        fixed, why = RI.repair_tags(base, out)
        self.assertIsNone(fixed)
        self.assertIn("<t>", why)

    def test_token_deficit_is_left_to_humans(self):
        base = "Toma %1 y %2."
        out = "Toma %1."
        fixed, why = RI.repair_tags(base, out)
        self.assertIsNone(fixed)
        self.assertIn("%2", why)


class TestBuildAndWrite(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "src")
        for sub in ("translations", "orig"):
            os.makedirs(os.path.join(self.src, sub))
        self.old_src = T.SRC
        T.set_src(self.src)

        self.en = {"0xa1": "Hello", "0xa2": "Take %1 now",
                  "0xa3": "The town of Cartagena", "0xa4": "Bye",
                  "0xa5": "IDM_CONTEST_01",
                  "0xa6": "The ship sits at the cape and waves at passing vessels"}
        self.cur = {"0xa1": "Buenos días", "0xa2": "Toma %1 ahora",
                    "0xa3": "La ciudad de Cartagena",
                    "0xa4": "Bye", "0xa5": "IDM_CONTEST_01",
                    "0xa6": "El barco está en el cabo y saluda a los barcos que pasan"}
        self.ref = {"0xa1": "Hola", "0xa2": "Toma %2 ahora",
                    "0xa3": "La ciudad de Cartagena es rica",
                    "0xa4": "Adiós", "0xa5": "IDM_CONTEST_01",
                    "0xa6": "Sie sitzt seit vielen Tagen am Cap und winkt vorbeifahrenden Schiffe zu"}
        TI.write_doc_atomic(os.path.join(self.src, "orig", "en.gog_1.1.2.3.toml"),
                            self.en, list(self.en), ["# 头"])
        TI.write_doc_atomic(os.path.join(self.src, "translations", "es.toml"),
                            self.cur, list(self.cur), ["# 头"])
        TI.write_doc_atomic(os.path.join(self.src, "orig", "es.retail-1.0.0.toml"),
                            self.ref, list(self.ref), ["# 头"])
        hold = os.path.join(self.src, "data", "qa", "retail_hold")
        os.makedirs(hold, exist_ok=True)
        with open(os.path.join(hold, "es.txt"), "w", encoding="utf-8") as f:
            f.write("# 测试用\n0xa3\t零售内容对不上，保留现译\n")

    def tearDown(self):
        T.set_src(self.old_src)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _cur(self):
        doc, _ = TI.read_doc(os.path.join(self.src, "translations", "es.toml"))
        return doc

    def test_takes_retail_where_it_differs(self):
        mapping, why = RI.build("es", "es.retail-1.0.0")
        self.assertEqual(mapping["0xa1"], "Hola")
        self.assertEqual(mapping["0xa2"], "Toma %2 ahora")

    def test_ref_equal_to_english_is_not_a_translation(self):
        """参照里没翻的行（`IDM_CONTEST_01`）不能被当成译文写进去。"""
        _, why = RI.build("es", "es.retail-1.0.0")
        self.assertIn("0xa5", why["参照没翻（等于英文）"])

    def test_foreign_row_in_reference_is_refused(self):
        """拉丁文字之间没有字种可判：参照里的德语行靠词典命中率拦下。"""
        mapping, why = RI.build("es", "es.retail-1.0.0")
        self.assertNotIn("0xa6", mapping)
        self.assertTrue([r for r in why if "不是目标语言" in r],
                        why.keys())

    def test_outer_whitespace_only_is_not_a_change(self):
        """只差首尾空白不当改动：零售的行首缩进不该把已落盘的值改一遍。"""
        ref = dict(self.ref)
        ref["0xa1"] = "  Buenos días"      # 与现值同一句，只多一个行首缩进
        TI.write_doc_atomic(os.path.join(self.src, "orig", "es.retail-1.0.2.toml"),
                            ref, list(ref), ["# 头"])
        mapping, why = RI.build(
            "es", os.path.join(self.src, "orig", "es.retail-1.0.2.toml"))
        self.assertNotIn("0xa1", mapping)
        self.assertIn("0xa1", why["与参照只差首尾空白（保留现值）"])

    def test_coverage_counts_missing_and_extra_rows(self):
        """换语言前先看覆盖：零售没给的行，导入无从下手。"""
        ref = dict(self.ref)
        ref.pop("0xa4")
        ref["0xb1"] = "Solo en la versión de tienda"
        TI.write_doc_atomic(os.path.join(self.src, "orig", "es.retail-1.0.1.toml"),
                            ref, list(ref), ["# 头"])
        cover = RI.coverage(
            "es", os.path.join(self.src, "orig", "es.retail-1.0.1.toml"))
        self.assertEqual(cover["base"], 6)
        self.assertEqual(cover["ref"], 6)
        self.assertEqual(cover["hit"], 5)
        self.assertEqual(cover["missing"], ["0xa4"])
        self.assertEqual(cover["extra"], ["0xb1"])
        self.assertEqual(cover["todo"], ["0xa4"])       # 现值仍是英文，真要去译
        self.assertEqual(cover["done"], [])
        self.assertEqual(cover["keep"], [])

    def test_held_row_keeps_current_translation(self):
        """人工判定不导的行不能因为「结构修得齐」就被写进去。"""
        mapping, why = RI.build("es", "es.retail-1.0.0")
        self.assertNotIn("0xa3", mapping)
        self.assertTrue([r for r in why if "人工判定不导" in r], why.keys())
        self.assertEqual(self._cur()["0xa3"], "La ciudad de Cartagena")

    def test_repair_map_leaves_fitting_rows_alone(self):
        fixed, notes = RI.repair_map("es", {"0xa1": "Hola", "0xa3": "La ciudad es rica"})
        self.assertEqual(fixed, {"0xa1": "Hola", "0xa3": "La ciudad es rica"})
        self.assertEqual(notes, [])

    def test_only_empty_skips_already_translated(self):
        mapping, why = RI.build("es", "es.retail-1.0.0", only_empty=True)
        self.assertEqual(list(mapping), ["0xa4"])          # 只有它还是英文
        self.assertIn("0xa1", why["已有译文"])

    def test_broken_token_in_reference_is_blocked_by_apply(self):
        mapping = {"0xa2": "Toma %2 ahora"}
        stats = T.apply_map("es", mapping, dry_run=True)
        self.assertEqual(stats["hit"], 0)
        self.assertEqual(len(stats["tokens"]), 1)

    def test_write_lands_and_second_run_is_idempotent(self):
        mapping, _ = RI.build("es", "es.retail-1.0.0")
        stats = T.apply_map("es", mapping)
        self.assertGreaterEqual(stats["hit"], 1)
        self.assertEqual(self._cur()["0xa1"], "Hola")
        again, _ = RI.build("es", "es.retail-1.0.0")
        # 落过盘的行不再出现；被结构缺陷挡住的那条每次都会留下 —— 那是有意的提醒，
        # 参照里的 `<n>` / `%1` 不改，它就永远进不去。
        self.assertEqual(list(again), ["0xa2"])
        self.assertEqual(T.apply_map("es", again)["hit"], 0)


class TestCleanText(unittest.TestCase):
    """小修小补只动写法：空白、结构、标点；不改字，也不猜内容。"""

    def test_trims_and_squeezes_spaces(self):
        out, notes = RI.clean_text("es", "Hello", "  Hola.  Que  tal  ")
        self.assertEqual(out, "Hola. Que tal")
        self.assertIn("去首尾空白", notes)
        self.assertIn("压连续空格", notes)

    def test_column_row_keeps_its_spaces(self):
        """含 `<t>` 的行按列排版，空白是数据，不能压。"""
        out, _ = RI.clean_text("es", "a<t>b", "Uno<t>Dos   tres")
        self.assertIn("Dos   tres", out)

    def test_spanish_inverted_marks_added(self):
        out, _ = RI.clean_text("es", "Hello. How are you? I'll pay!",
                              "Hola. ¿Cómo estás? Te pagaré @g$Reward$!")
        self.assertTrue(out.endswith("¡Te pagaré @g$Reward$!"))

    def test_question_inside_parentheses_is_not_a_sentence(self):
        """年份缩写 `(1682? – 1722)` 里的问号不是句尾，不许在句首补 `¿`。"""
        text = ("El galés Bartholomew Roberts (1682? – 1722) fue uno de los piratas "
                "más importantes y también más peculiares que han existido.")
        out, notes = RI.clean_text("es", text, text)
        self.assertEqual(out, text)
        self.assertEqual(notes, [])

    def test_inverted_mark_not_duplicated_across_paragraph_break(self):
        """起头符号可以跨 `<n>`：`¡%1,<n>me alegro…!` 已经带了 `¡`，不许再补。"""
        text = "¡%1,<n>me alegro tanto de que hayas vuelto!"
        out, _ = RI.clean_text("es", "%1,<n>I am glad you are back!", text)
        self.assertEqual(out.count("¡"), 1)

    def test_other_languages_are_not_touched_by_inverted_rule(self):
        out, notes = RI.clean_text("de", "Frage", "Frage?")
        self.assertEqual(out, "Frage?")
        self.assertEqual(notes, [])

    def test_dangling_period_after_exclamation_removed(self):
        out, notes = RI.clean_text("es", "Hello!", "¡Hola!.")
        self.assertEqual(out, "¡Hola!")
        self.assertIn("去多余句号 1", notes)

    def test_big_paragraph_gap_is_aligned_to_base_count(self):
        """`<n>` 个数必须与基准一致：多 8 个也照删，接缝留空格（内容不动）。"""
        text = "Uno.<n><n>Dos.<n><n>Tres.<n><n>Cuatro.<n><n>Cinco."
        out, notes = RI.clean_text("es", "One paragraph.", text)
        self.assertEqual(out.count("<n>"), 0)
        self.assertIn("删 <n> 8", "、".join(notes))

    def test_small_paragraph_gap_is_filled(self):
        base = ("Selecciona el barco que quieres controlar.<n><n>"
                "En cualquier momento puedes seleccionar otro de la lista.")
        text = ("Selecciona el barco que quieres controlar. "
                "En cualquier momento puedes seleccionar otro de la lista.")
        out, notes = RI.clean_text("es", base, text)
        self.assertEqual(out.count("<n>"), 2)
        self.assertIn("补 <n> 2", notes)

    def test_issues_report_what_cannot_be_fixed(self):
        base = "Take @A$Amount$ now"
        self.assertIn("令牌 @A$Amount$ 1→0", RI.clean_issues(base, "Toma ahora"))
        self.assertIn("直引号 `\"` 奇数个", RI.clean_issues("Say \"hi\"", "Di \"hola"))
        self.assertIn("行内有裸制表符（应为 `<t>`）", RI.clean_issues("a<t>b", "a\tb"))


class TestCleanRef(unittest.TestCase):
    """清洁版落盘：派生文件进 `build/`，原始零售文件一字不动。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "src")
        for sub in ("translations", "orig"):
            os.makedirs(os.path.join(self.src, sub))
        self.old_src = T.SRC
        T.set_src(self.src)
        self.en = {"0xa1": "Hello", "0xa2": "Take %1 now.", "0xa3": "Bye"}
        self.ref = {"0xa1": "  Hola.  ", "0xa2": "Toma ahora.", "0xa3": "Adiós!"}
        TI.write_doc_atomic(os.path.join(self.src, "orig", "en.gog_1.1.2.3.toml"),
                            self.en, list(self.en), ["# 头"])
        self.cur = {"0xa1": "Hello", "0xa2": "Take %1 now.", "0xa3": "Bye"}
        TI.write_doc_atomic(os.path.join(self.src, "translations", "es.toml"),
                            self.cur, list(self.cur), ["# 头"])
        TI.write_doc_atomic(os.path.join(self.src, "orig", "es.retail-1.0.0.toml"),
                            self.ref, list(self.ref), ["# 头"])

    def tearDown(self):
        T.set_src(self.old_src)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_cleaned_file_and_original_both_kept(self):
        out, _, changed, issues, path = RI.clean_ref("es", "es.retail-1.0.0")
        self.assertEqual(out["0xa1"], "Hola.")
        self.assertEqual(out["0xa3"], "¡Adiós!")
        self.assertEqual([c[0] for c in changed], ["0xa1", "0xa3"])
        # `%1` 被零售吃掉了，只能报：不在清洁版里补。
        self.assertIn(("0xa2", "令牌 %1 1→0"), issues)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.replace("\\", "/").endswith("build/ref/retail_clean/es.retail-1.0.0.toml"))
        old, _ = TI.read_doc(os.path.join(self.src, "orig", "es.retail-1.0.0.toml"))
        self.assertEqual(old, self.ref)

    def test_held_row_keeps_structure_aligned_but_is_not_cleaned(self):
        """hold 行不导入，但清洁版里结构仍要对齐基准；标点空白不动。"""
        os.makedirs(os.path.join(self.src, "data", "qa", "retail_hold"), exist_ok=True)
        io.open(os.path.join(self.src, "data", "qa", "retail_hold", "es.txt"),
                "w", encoding="utf-8").write("0xa3\t人工判定\n")
        out, _, _, issues, _ = RI.clean_ref("es", "es.retail-1.0.0")
        self.assertEqual(out["0xa3"], self.ref["0xa3"])       # 没补 `¡`
        self.assertTrue([i for i in issues if i[0] == "0xa3" and "在 hold 名单" in i[1]])

    def test_build_accepts_the_cleaned_doc_in_memory(self):
        out, _, _, _, _ = RI.clean_ref("es", "es.retail-1.0.0")
        mapping, _ = RI.build("es", "es.retail-1.0.0", ref_doc=out)
        self.assertEqual(mapping["0xa1"], "Hola.")
        self.assertEqual(mapping["0xa3"], "¡Adiós!")
        # 清洁版不补令牌：缺 `%1` 的那条照样被 `apply` 拦下。
        self.assertEqual(len(T.apply_map("es", mapping, dry_run=True)["tokens"]), 1)

    def test_clean_ref_is_recognised_by_path(self):
        """落盘只该认清洁版；原始零售路径必须被识别成「未清洁」。"""
        self.assertTrue(RI.is_clean_ref("build\\ref\\retail_clean\\es.retail-1.0.0.toml"))
        self.assertTrue(RI.is_clean_ref("build/ref/retail_clean/es.retail-1.0.0.toml"))
        self.assertFalse(RI.is_clean_ref("es.retail-1.0.0"))
        self.assertFalse(RI.is_clean_ref("src\\orig\\es.retail-1.0.0.toml"))

    def test_write_on_raw_retail_warns_about_the_order(self):
        """拿原始零售直接 --write 要提醒先过清洁版，否则原始标点会一起落盘。"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            RI.main(["--lang", "es", "--ref", "es.retail-1.0.0", "--write",
                     "--out", os.path.join(self.src, "qa", "r.txt")])
        self.assertIn("未经清洁", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
