# -*- coding: utf-8 -*-
"""lua_missions.parse_listing 的合成清单测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "tools", "analysis"))
import lua_missions  # noqa: E402

#: 按 luac -l 的真实形态手写两段：一条注册 + 一条库 chunk（不注册）。
LISTING = """\
main <0:=(luac)> (2 instructions/8 bytes at 0114A830)
0 params, 1 stack, 0 locals, 0 strings, 0 numbers, 2 functions, 0 lines
     1\t[-]\tCLOSURE    \t0 0\t; 0114A9E8
     2\t[-]\tCALL       \t0 0
main <0:@LUA Mission Source/data/abduction.lua> (12 instructions/40 bytes at 0114A9E8)
0 params, 6 stacks, 1 local, 20 strings, 0 numbers, 13 functions, 55 lines
     1\t[1]\tGETGLOBAL  \t0\t; Script_Register
     2\t[1]\tPUSHSTRING \t1\t; "abduction"
     3\t[1]\tPUSHSTRING \t2\t; "govern"
     4\t[1]\tGETGLOBAL  \t3\t; MTYPE_GOVERNOR
     5\t[1]\tCALL       \t0 1
     6\t[3]\tGETLOCAL   \t0\t; F
     7\t[3]\tPUSHSTRING \t4\t; "USES"
     8\t[3]\tCREATETABLE\t2
     9\t[3]\tPUSHSTRING \t5\t; "abduction_spawn_treasure"
    10\t[3]\tPUSHSTRING \t6\t; "abduction_spawn_goods"
    11\t[3]\tSETLIST    \t0 2
    12\t[5]\tPUSHSTRING \t7\t; "OnInit"
    13\t[60]\tCLOSURE    \t0 0\t; 01141650
    14\t[60]\tSETTABLE   \t3 3
    15\t[62]\tPUSHSTRING \t8\t; "OnText"
    16\t[72]\tCLOSURE    \t1 0\t; 01142008
    17\t[72]\tSETTABLE   \t3 3
function <5:@LUA Mission Source/data/abduction.lua> (4 instructions/16 bytes at 01141650)
1 param, 12 stacks, 7 locals, 23 strings, 0 numbers, 0 functions, 43 lines
     1\t[10]\tGETLOCAL   \t0\t; V
     2\t[10]\tPUSHSTRING \t0\t; "TextIdx"
     3\t[10]\tPUSHINT    \t-1
     4\t[11]\tPUSHSTRING \t1\t; "IDM_ABDUCTION_LOG_TEXT"
main <0:@LUA Mission Source/data/bountyhunter.lua> (9 instructions/32 bytes at 0114CED0)
0 params, 6 stacks, 1 local, 20 strings, 0 numbers, 13 functions, 55 lines
     1\t[1]\tGETGLOBAL  \t0\t; Script_Register
     2\t[1]\tPUSHSTRING \t1\t; "bountyhunter"
     3\t[1]\tPUSHSTRING \t2\t; "tavern"
     4\t[1]\tGETGLOBAL  \t3\t; MTYPE_TAVERN
     5\t[1]\tCALL       \t0 1
     6\t[3]\tPUSHSTRING \t4\t; "OnCreate"
     7\t[3]\tCLOSURE    \t0 0\t; 0114D100
     8\t[3]\tSETTABLE   \t3 3
main <0:@LUA Mission Source/data/missionlib.lua> (3 instructions/12 bytes at 0114E160)
0 params, 1 stack, 0 locals, 0 strings, 0 numbers, 12 functions, 0 lines
     1\t[1]\tGETGLOBAL  \t0\t; MissionLib
     2\t[1]\tSETTABLE   \t1 0
     3\t[1]\tSETTABLE   \t2 0
"""


class ParseListing(unittest.TestCase):
    def setUp(self):
        self.rows = lua_missions.parse_listing(LISTING)

    def test_reads_only_registrations(self):
        self.assertEqual([r["name"] for r in self.rows],
                         ["abduction", "bountyhunter"])

    def test_fields(self):
        row = self.rows[0]
        self.assertEqual(row["group"], "govern")
        self.assertEqual(row["type"], "MTYPE_GOVERNOR")
        self.assertEqual(row["source"],
                         "LUA Mission Source/data/abduction.lua")

    def test_states_skip_data_tables(self):
        self.assertEqual(self.rows[0]["states"], ["OnInit", "OnText"])
        self.assertEqual(self.rows[1]["states"], ["OnCreate"])

    def test_text_ids_come_from_subfunctions(self):
        self.assertEqual(self.rows[0]["text_ids"], ["IDM_ABDUCTION_LOG_TEXT"])
        self.assertEqual(self.rows[1]["text_ids"], [])

    def test_summary(self):
        s = lua_missions.summarize(self.rows)
        self.assertEqual(s["missions"], 2)
        self.assertEqual(s["types"], {"MTYPE_GOVERNOR": 1, "MTYPE_TAVERN": 1})
        self.assertEqual(s["groups"], ["govern", "tavern"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
