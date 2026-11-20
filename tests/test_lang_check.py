"""形态层检查的送检文本：占位符抹成空白、段落标记还原成换行。"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "tools"),
          os.path.join(ROOT, "src", "tools", "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)

from analysis import lang_check as LC  # noqa: E402


class TestClean(unittest.TestCase):
    def test_paragraph_mark_becomes_a_line_break(self):
        self.assertEqual(LC.clean("considération.<n><n>Les marchands"),
                         "considération.\n\nLes marchands")

    def test_no_underscores_left_behind(self):
        # 旧实现把占位符换成等长下划线，`.<n><n>` 就成了「句号紧跟字母」，LT 报缺空格
        for s in ("considération.<n><n>Les marchands", "Retour à @T$Town$",
                  "Rang [Brick]", "%1 %2 %3"):
            self.assertNotIn("_", LC.clean(s))

    def test_placeholder_becomes_one_space(self):
        self.assertEqual(LC.clean("Retour à @T$Town$ demain"), "Retour à demain")
        self.assertEqual(LC.clean("100%1 navires"), "100 navires")

    def test_bare_tags_leave_nothing(self):
        self.assertEqual(LC.clean("[术语]"), "")
        self.assertEqual(LC.clean("<t><n>"), "")

    def test_runs_of_blank_are_collapsed(self):
        self.assertEqual(LC.clean("a   b\t\tc"), "a b c")

    def test_three_breaks_become_two(self):
        self.assertEqual(LC.clean("a<n><n><n>b"), "a\n\nb")

    def test_none_ascii_whitespace_is_not_introduced(self):
        out = LC.clean("a<n>b@T$Town$c")
        self.assertNotIn("\u00a0", out)
        self.assertNotIn("\u200b", out)


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tr = LC.load("fr")
        cls.p = LC.pools("fr")

    def out(self, text):
        return LC.render(text, "fr", self.tr)

    def test_town_placeholder_becomes_a_town_of_that_language(self):
        out = self.out("Rendez-vous à @T$Town$ demain.")
        self.assertNotIn("@", out)
        self.assertTrue(any(t in out for t in self.p["town"]), out)

    def test_pirate_name_comes_from_the_person_pool(self):
        out = self.out("Le pirate @P$PirateName$ s'enfuit.")
        self.assertTrue(any(n in out for n in self.p["person"]), out)

    def test_nation_and_goods_placeholder_keep_the_sentence_readable(self):
        out = self.out("Notre ennemi, @n$HostileNation$, bloque le port.")
        self.assertTrue(any(n in out for n in self.p["nation"]), out)
        out = self.out("Livrez du @G$Goods$ au marché.")
        self.assertTrue(any(g in out for g in self.p["goods"]), out)

    def test_amount_and_count_become_numbers_in_range(self):
        self.assertRegex(self.out("Vous recevrez @g$GoldPerBarrel$."), r"\b\d{3}\b")
        for n in (self.out("@a$Amount$ tonneaux"), self.out("@I$NumShips$ navires")):
            self.assertRegex(n, r"^\d+ ")
        # 两位数起：法语 0–10 要写成字母，填个位数会自己造出规则命中
        self.assertGreaterEqual(int(self.out("@I$NumShips$").split()[0]), 11)

    def test_percent_after_an_article_becomes_a_noun(self):
        out = self.out("En raison de son état, un %1 a coulé.")
        self.assertRegex(out, r"un \S+ a coulé")
        self.assertNotRegex(out, r"un \d+ a coulé")

    def test_percent_without_an_article_stays_a_number(self):
        out = self.out("Marchandises :<t>%2")
        self.assertRegex(out, r"Marchandises : \d+")

    def test_town_annotation_uses_the_language_name(self):
        out = self.out("Voir le gouverneur de [town:Cartagena].")
        self.assertIn("Carthagène", out)
        self.assertNotIn("[", out)

    def test_graphic_tags_are_masked_to_blank_not_empty(self):
        out = self.out("a<f:fonts/Tiepolo.res><c>b")
        self.assertEqual(out, "a b")
        self.assertNotIn("<", out)

    def test_paragraph_marks_survive_as_line_breaks(self):
        out = self.out("Fin.<n><n>Suite.")
        self.assertEqual(out, "Fin.\n\nSuite.")

    def test_rendering_is_repeatable(self):
        text = "À @T$Town$ avec @P$PirateName$, le %1."
        self.assertEqual(self.out(text), self.out(text))

    def test_no_placeholder_or_bracket_left_behind(self):
        text = "@T$TOWN$ @D$EndDate$ [term:en_pirate] [riddle:copy=0x35f48fdf] <ts:80>%3"
        out = self.out(text)
        self.assertNotIn("@", out)
        self.assertNotIn("[", out)
        self.assertNotIn("<", out)


if __name__ == "__main__":
    unittest.main()
