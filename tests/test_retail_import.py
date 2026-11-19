"""零售参照导入：承标注规则与落盘行为。"""

import os
import shutil
import sys
import tempfile
import unittest

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
                  "0xa5": "IDM_CONTEST_01"}
        self.cur = {"0xa1": "Buenos días", "0xa2": "Toma %1 ahora",
                    "0xa3": "La ciudad de Cartagena",
                    "0xa4": "Bye", "0xa5": "IDM_CONTEST_01"}
        self.ref = {"0xa1": "Hola", "0xa2": "Toma %2 ahora",
                    "0xa3": "La ciudad de Cartagena es rica",
                    "0xa4": "Adiós", "0xa5": "IDM_CONTEST_01"}
        TI.write_doc_atomic(os.path.join(self.src, "orig", "en.gog_1.1.2.3.toml"),
                            self.en, list(self.en), ["# 头"])
        TI.write_doc_atomic(os.path.join(self.src, "translations", "es.toml"),
                            self.cur, list(self.cur), ["# 头"])
        TI.write_doc_atomic(os.path.join(self.src, "orig", "es.retail-1.0.0.toml"),
                            self.ref, list(self.ref), ["# 头"])

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


if __name__ == "__main__":
    unittest.main()
