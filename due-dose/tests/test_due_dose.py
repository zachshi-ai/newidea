# -*- coding: utf-8 -*-
"""欠针 · Due Dose 验收测试。

每条验收标准都转成自动化测试:词表归一与 --map 教学、抗原翻译(五联→三抗原)、
月龄钟(月末钳制/恰线语义/双算法)、欠账状态机(FUTURE/DUE/OVERDUE 边界)、
补种几何(闭式==贪心/同日并种/最早可种日/RUSH 恰线/GATE-BLOCKED)、账坏九类、
空账、多孩隔离、--schedule 翻案、零墙钟与字节复现。

测试构造纪律:用一本「22 剂全齐」的基准账本当底,每个场景只定点摘除/改期
——稀疏账本里所有抗原同时超龄,exit code 断言会失真(开发中踩过)。
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE)))
import due_dose as dd  # noqa: E402

KID_HDR = "kid\tbirth\tnote\n"
DOSE_HDR = "date\tkid\tproduct\tprice\tnote\n"

BIRTH = date(2024, 1, 1)
# 基准账本:一类 22 剂全部在册(含未来的 4 岁/6 岁剂次——后视行按 as-of 排除)。
# 同抗原相邻剂次间隔均 ≥28 天,无 INTERRUPTED;同日多针均为不同抗原。
BASE_ROWS = [
    ("2024-01-01", "乙肝疫苗"), ("2024-01-01", "卡介苗"),
    ("2024-02-01", "乙肝疫苗"),
    ("2024-03-01", "脊灰疫苗"),
    ("2024-04-01", "脊灰疫苗"), ("2024-04-01", "百白破疫苗"),
    ("2024-05-01", "脊灰疫苗"), ("2024-05-01", "百白破疫苗"),
    ("2024-06-01", "百白破疫苗"),
    ("2024-07-01", "乙肝疫苗"), ("2024-07-01", "A群流脑多糖疫苗"),
    ("2024-09-01", "麻腮风疫苗"), ("2024-09-01", "乙脑减毒活疫苗"),
    ("2024-10-01", "A群流脑多糖疫苗"),
    ("2025-07-01", "麻腮风疫苗"), ("2025-07-01", "百白破疫苗"),
    ("2025-07-01", "甲肝减毒活疫苗"),
    ("2026-01-01", "乙脑减毒活疫苗"),
    ("2027-01-01", "A群C群流脑多糖疫苗"),
    ("2028-01-01", "脊灰疫苗"),
    ("2030-01-01", "白破疫苗"), ("2030-01-01", "A群C群流脑多糖疫苗"),
]
ASOF_A = "2024-06-01"   # 5 月龄:基础针已齐,后续剂次全部未到龄 → 绿
ASOF_B = "2026-06-01"   # 29 月龄:到龄剂次全齐(4 岁/6 岁的未到龄) → 绿


def _d(s):
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def base_ledger_rows(omit=(), extra=()):
    """按 (产品, 第几针) 从基准账本摘除,extra 追加,按日期稳定排序。"""
    counters = {}
    kept = []
    for dt, prod in BASE_ROWS:
        counters[prod] = counters.get(prod, 0) + 1
        if (prod, counters[prod]) in omit:
            continue
        kept.append((dt, prod))
    for dt, prod in extra:
        kept.append((dt, prod))
    kept.sort(key=lambda r: (r[0], r[1]))
    return kept


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def ledger(self, kids, doses):
        if kids is not None:
            with open(os.path.join(self.tmp, "kids.tsv"), "w",
                      encoding="utf-8") as f:
                f.write(kids)
        if doses is not None:
            with open(os.path.join(self.tmp, "doses.tsv"), "w",
                      encoding="utf-8") as f:
                f.write(doses)
        return self.tmp

    def base_ledger(self, omit=(), extra=(), kid="小满", birth="2024-01-01"):
        body = "".join("%s\t%s\t%s\t\t\n" % (dt, kid, prod)
                       for dt, prod in base_ledger_rows(omit, extra))
        return self.ledger(KID_HDR + "%s\t%s\t\n" % (kid, birth),
                           DOSE_HDR + body)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = dd.main(list(args))
            return code, out.getvalue() + err.getvalue()
        except dd.LedgerError:
            return 2, out.getvalue() + err.getvalue()
        except dd.EmptyLedger as e:
            return 3, out.getvalue() + err.getvalue() + str(e)
        except SystemExit as e:
            return (e.code if isinstance(e.code, int) else 1), \
                out.getvalue() + err.getvalue()

    def write_sched(self, text):
        p = os.path.join(self.tmp, "sched.tsv")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p


class TestLexicon(Base):
    def test_wulian_translates_to_three_antigens(self):
        """核心翻译:四支五联替代全部脊灰+百白破 → 三种抗原各 4/4/4
        (本子印产品名,查验读抗原)。"""
        counters, kept = {}, []
        for dt, prod in BASE_ROWS:
            counters[prod] = counters.get(prod, 0) + 1
            if prod in ("脊灰疫苗", "百白破疫苗"):
                continue
            kept.append((dt, prod))
        for dt in ("2024-03-01", "2024-04-01", "2024-05-01", "2025-07-01"):
            kept.append((dt, "五联疫苗"))
        kept.sort()
        body = "".join("%s\t小满\t%s\t\t\n" % r for r in kept)
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n", DOSE_HDR + body)
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", ASOF_B)
        self.assertEqual(code, 0)
        self.assertIn("脊灰          4   4  ✓齐", out)
        self.assertIn("百白破         4   4  ✓齐", out)
        self.assertIn("hib        4/4", out)

    def test_normalization(self):
        lex = dd.build_lexicon()
        for name in ("五联", "五联疫苗", "五联 疫苗", "DTaP-IPV-Hib",
                     "dtap-ipv-hib", "（五联疫苗）"):
            self.assertIn(dd._norm(name), lex)
        self.assertEqual(lex[dd._norm("DTaP-IPV-Hib")][1]["polio"], 1)

    def test_unknown_product_is_ledger_error(self):
        self.ledger(KID_HDR + "小满\t2023-03-15\t\n",
                    DOSE_HDR + "2023-03-15\t小满\t某神秘疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 2)

    def test_map_teaches_one_alias(self):
        self.ledger(KID_HDR + "小满\t2023-03-15\t\n",
                    DOSE_HDR + "2023-03-15\t小满\t杭州五联白\t\t\n")
        code, _ = self.run_cli("report", "--dir", self.tmp,
                               "--map", "杭州五联白=五联疫苗")
        self.assertEqual(code, 0)

    def test_map_unknown_target_refused(self):
        with self.assertRaises(SystemExit):
            dd.build_lexicon(dd.parse_maps(["某=不存在的苗"]))

    def test_lexicon_no_confusion(self):
        """b型流感嗜血杆菌 ≠ 流感:易混名各归各的抗原。"""
        lex = dd.build_lexicon()
        self.assertEqual(lex[dd._norm("b型流感嗜血杆菌疫苗")][0], "hib疫苗")
        self.assertEqual(lex[dd._norm("四价流感裂解疫苗")][0], "流感疫苗")


class TestMonthClock(Base):
    def test_add_months_end_of_month_clamp(self):
        self.assertEqual(dd.add_months(date(2023, 1, 31), 1), date(2023, 2, 28))
        # 不链式钳制:每次从原始 day 重新对齐
        self.assertEqual(dd.add_months(date(2023, 1, 31), 2), date(2023, 3, 31))

    def test_add_months_leap(self):
        self.assertEqual(dd.add_months(date(2024, 2, 29), 12), date(2025, 2, 28))
        self.assertEqual(dd.add_months(date(2024, 2, 29), 1), date(2024, 3, 29))

    def test_add_months_parity_grid(self):
        for base in (date(2020, 1, 31), date(2021, 8, 15), date(2023, 3, 15),
                     date(2024, 2, 29)):
            for n in range(0, 74):
                self.assertEqual(dd.add_months(base, n),
                                 dd.add_months_walk(base, n),
                                 "%s +%d" % (base, n))

    def test_months_between_boundary(self):
        b = date(2023, 3, 15)
        self.assertEqual(dd.months_between(b, date(2024, 9, 14)), 17)
        self.assertEqual(dd.months_between(b, date(2024, 9, 15)), 18)
        self.assertEqual(dd.months_between(b, date(2025, 10, 10)), 30)

    def test_months_between_parity_probe(self):
        b = date(2020, 1, 31)
        cur = b
        while cur <= dd.add_months(b, 24):
            self.assertEqual(dd.months_between(b, cur),
                             dd.months_between_walk(b, cur))
            cur += timedelta(days=1)

    def test_age_text(self):
        self.assertEqual(dd.age_text(date(2023, 3, 15), date(2025, 10, 10)),
                         "2 岁 6 个月")
        self.assertEqual(dd.age_text(date(2023, 3, 15), date(2023, 6, 14)),
                         "2 个月")


class TestStatusMachine(Base):
    def test_future_not_a_debt(self):
        """程序表只欠到龄的,不欠还没到的(6 岁白破不是 5 月龄孩子的债)。"""
        self.base_ledger()
        code, out = self.run_cli("report", "--dir", self.tmp, "--as-of", ASOF_A)
        self.assertEqual(code, 0)
        self.assertIn("白破          1   0  ·未到龄", out)

    def test_overdue_exact_line_not_lit(self):
        """恰满 3 个月不亮(宁少报);再过一天亮。"""
        self.base_ledger(omit={("麻腮风疫苗", 2)})
        # mmr#2 应 18 月龄 = 2025-07-01;+3 月 = 2025-10-01
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", "2025-10-01")
        self.assertEqual(code, 0)
        self.assertIn("麻腮风         2   1  ●该种", out)
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", "2025-10-02")
        self.assertEqual(code, 4)
        self.assertIn("麻腮风         2   1  ✗超龄欠针", out)

    def test_overdue_months_flag_moves_line(self):
        self.base_ledger(omit={("麻腮风疫苗", 2)})
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", "2025-10-02", "--overdue-months", "6")
        self.assertEqual(code, 0)
        self.assertIn("●该种", out)

    def test_never_seen_annotation(self):
        self.base_ledger(omit={("卡介苗", 1)})
        code, out = self.run_cli("gaps", "--dir", self.tmp, "--as-of", ASOF_B)
        self.assertEqual(code, 4)
        self.assertIn("从未见过这种针", out)

    def test_extra_dose_disclosed_not_error(self):
        """补种重打的第 4 剂乙肝:照实记,点名「多 1 剂」。"""
        self.base_ledger(extra=[("2025-01-02", "乙肝疫苗")])
        code, out = self.run_cli("report", "--dir", self.tmp, "--as-of", ASOF_B)
        self.assertEqual(code, 0)
        self.assertIn("多 1 剂", out)

    def test_interrupted_yellow_not_refused(self):
        """同抗原 15 天两针:点灯不销账,黄灯不判 4。"""
        self.base_ledger(omit={("A群流脑多糖疫苗", 2)},
                         extra=[("2024-07-16", "A群流脑多糖疫苗")])
        code, out = self.run_cli("report", "--dir", self.tmp, "--as-of", ASOF_B)
        self.assertEqual(code, 0)
        self.assertIn("INTERRUPTED", out)
        self.assertIn("只隔 15 天", out)

    def test_interrupted_exact_28_not_lit(self):
        self.base_ledger(omit={("A群流脑多糖疫苗", 2)},
                         extra=[("2024-07-29", "A群流脑多糖疫苗")])
        code, out = self.run_cli("report", "--dir", self.tmp, "--as-of", ASOF_B)
        self.assertEqual(code, 0)
        self.assertNotIn("INTERRUPTED", out)

    def test_min_gap_flag_controls_interrupted(self):
        self.base_ledger(omit={("A群流脑多糖疫苗", 2)},
                         extra=[("2024-07-29", "A群流脑多糖疫苗")])
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", ASOF_B, "--min-gap", "40")
        self.assertIn("INTERRUPTED", out)

    def test_half_course_lit_when_all_past(self):
        self.base_ledger(extra=[("2024-08-01", "EV71疫苗")])
        code, out = self.run_cli("report", "--dir", self.tmp, "--as-of", ASOF_B)
        self.assertEqual(code, 0)
        self.assertIn("HALF-COURSE", out)

    def test_half_course_not_lit_when_second_not_due(self):
        """水痘第 2 剂应 4 岁——刚打完第 1 剂不是半程。"""
        self.base_ledger(extra=[("2025-06-10", "水痘减毒活疫苗")])
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", "2026-03-01")
        self.assertEqual(code, 0)
        self.assertNotIn("HALF-COURSE", out)

    def test_base_ledger_is_green_at_both_anchors(self):
        """基准账本在两个锚点都是绿的——所有场景从绿出发。"""
        self.base_ledger()
        for as_of in (ASOF_A, ASOF_B):
            code, out = self.run_cli("report", "--dir", self.tmp,
                                     "--as-of", as_of)
            self.assertEqual(code, 0, as_of)
            self.assertNotIn("🔴", out)


class TestCatchup(Base):
    def test_plan_parity_closed_vs_greedy_grids(self):
        """两条路径:逐抗原递推 == 逐日贪心,欠账网格全对拍。"""
        grids = [
            {"mmr": [(2, date(2025, 1, 1))]},
            {"polio": [(3, date(2025, 1, 1)), (4, date(2026, 1, 1))]},
            {"mmr": [(1, date(2025, 1, 1)), (2, date(2025, 8, 1))],
             "hepa": [(1, date(2025, 1, 1))]},
            {"a": [(1, date(2025, 6, 1))], "b": [(1, date(2025, 6, 1))],
             "c": [(1, date(2025, 6, 1))]},
            {"a": [(1, date(2025, 1, 1)), (2, date(2025, 1, 1)),
                   (3, date(2025, 1, 1))]},
        ]
        for owed in grids:
            for gap in (28, 14):
                plan = dd.plan_catchup(owed, date(2025, 1, 1),
                                       date(2027, 1, 1), gap, 14)
                self.assertTrue(plan["feasible"], owed)

    def test_same_day_multi_antigen(self):
        """不同抗原同日并种(含两个活疫苗):一天补完。"""
        self.base_ledger(omit={("麻腮风疫苗", 2), ("甲肝减毒活疫苗", 1)})
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2025-12-31", "--as-of", "2025-06-01")
        self.assertEqual(code, 0)
        self.assertIn("甲肝 第1剂 + 麻腮风 第2剂", out)
        self.assertIn("2025-07-01", out)   # 两剂都排在其应种日(18 月龄)

    def test_same_antigen_gap_via_schedule_override(self):
        """同抗原欠 2 剂且都已到龄:第二剂 = 第一剂 + 28 天。"""
        sched = self.write_sched("polio\t2,3,30,31\n")
        self.base_ledger(omit={("脊灰疫苗", 3), ("脊灰疫苗", 4)})
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2027-06-30", "--as-of", "2027-01-01",
                                 "--schedule", sched)
        self.assertEqual(code, 0)
        self.assertIn("脊灰 第3剂", out)
        self.assertIn("2027-01-29  脊灰 第4剂", out)   # as-of + 28 天

    def test_earliest_date_respected(self):
        """查验日前才到龄的剂次排在它的应种日,不提前到 as-of。"""
        self.base_ledger(omit={("A群C群流脑多糖疫苗", 1)})
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2027-06-30", "--as-of", "2026-06-01")
        self.assertEqual(code, 0)
        self.assertIn("2027-01-01  流脑AC 第1剂", out)

    def test_rush_exact_line_not_lit(self):
        """余量恰 14 天不亮,<14 亮(完成日被应种日钉在 2025-07-01)。"""
        self.base_ledger(omit={("甲肝减毒活疫苗", 1)})
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2025-07-15", "--as-of", "2025-06-01")
        self.assertEqual(code, 0)
        self.assertNotIn("RUSH", out)
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2025-07-14", "--as-of", "2025-06-01")
        self.assertEqual(code, 0)
        self.assertIn("RUSH", out)

    def test_gate_blocked_exit4(self):
        """同抗原欠 2 剂需 28 天,只剩 20 天 → GATE-BLOCKED,差 8 天。"""
        sched = self.write_sched("polio\t2,3,30,31\n")
        self.base_ledger(omit={("脊灰疫苗", 3), ("脊灰疫苗", 4)})
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2027-01-21", "--as-of", "2027-01-01",
                                 "--schedule", sched)
        self.assertEqual(code, 4)
        self.assertIn("GATE-BLOCKED", out)
        self.assertIn("差 8 天", out)

    def test_gate_horizon_includes_not_yet_due(self):
        """查验口径:查验日前才到龄的剂次也进排期(36 月龄流脑AC)。"""
        self.base_ledger(omit={("A群C群流脑多糖疫苗", 1)})
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2027-02-01", "--as-of", "2026-06-01")
        self.assertIn("流脑AC×1", out)

    def test_post_gate_doses_disclosed(self):
        self.base_ledger(omit={("A群C群流脑多糖疫苗", 1)})
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2027-02-01", "--as-of", "2026-06-01")
        self.assertIn("查验后才到龄", out)
        self.assertIn("白破", out)

    def test_by_before_asof_refused(self):
        self.base_ledger()
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2024-01-01", "--as-of", "2025-06-01")
        self.assertEqual(code, 2)

    def test_clean_kid_nothing_to_do(self):
        self.base_ledger()
        code, out = self.run_cli("catchup", "--dir", self.tmp,
                                 "--by", "2026-08-31", "--as-of", ASOF_B)
        self.assertEqual(code, 0)
        self.assertIn("什么都不用补", out)

    def test_real_slot_numbers_displayed(self):
        """欠的是账本上第几剂,不是「欠的第几剂」(麻腮风欠的是第 2 剂)。"""
        self.base_ledger(omit={("麻腮风疫苗", 2)})
        code, out = self.run_cli("gaps", "--dir", self.tmp,
                                 "--as-of", "2025-10-02")
        self.assertIn("麻腮风        第2剂", out)


class TestLedgerErrors(Base):
    def test_both_files_missing_exit3(self):
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 3)
        self.assertIn("kid\tbirth", out)

    def test_kids_only_no_doses_no_asof_exit3(self):
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n", None)
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 3)
        self.assertIn("--as-of", out)

    def test_doses_without_kids_exit3(self):
        self.ledger(None, DOSE_HDR + "2024-02-01\t小满\t乙肝疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 3)

    def test_dose_before_birth_exit2(self):
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n",
                    DOSE_HDR + "2023-12-31\t小满\t乙肝疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 2)

    def test_unknown_kid_ref_exit2(self):
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n",
                    DOSE_HDR + "2024-02-01\t大满\t乙肝疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 2)

    def test_same_product_same_day_exit2(self):
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n",
                    DOSE_HDR + "2024-02-01\t小满\t乙肝疫苗\t\t\n"
                    "2024-02-01\t小满\t乙肝疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 2)

    def test_same_antigen_same_day_via_combo_exit2(self):
        """五联+百白破同天 = dtap 两剂同日,不存在。"""
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n",
                    DOSE_HDR + "2024-04-01\t小满\t五联疫苗\t628\t\n"
                    "2024-04-01\t小满\t百白破疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 2)

    def test_unpadded_date_exit2(self):
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n",
                    DOSE_HDR + "2024-2-1\t小满\t乙肝疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 2)

    def test_missing_column_exit2(self):
        with open(os.path.join(self.tmp, "kids.tsv"), "w", encoding="utf-8") as f:
            f.write("kid\tbirth\n小满\t2024-01-01\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 2)

    def test_future_rows_excluded_disclosed(self):
        """显式 as-of 早于部分行:后视行排除并披露,不是账坏(基准账本含
        2030 年的 6 岁剂次)。"""
        self.base_ledger()
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", "2026-06-01")
        self.assertEqual(code, 0)
        self.assertIn("后视行排除", out)
        self.assertIn("白破          1   0", out)

    def test_duplicate_kid_exit2(self):
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n小满\t2024-01-01\t\n",
                    DOSE_HDR + "2024-02-01\t小满\t乙肝疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertEqual(code, 2)


class TestPaid(Base):
    def test_series_grouped_by_product(self):
        """五联的钱归五联系列,不拆进三种抗原;年针披露上次。"""
        self.ledger(KID_HDR + "小满\t2023-03-15\t\n", DOSE_HDR +
                    "2023-05-20\t小满\t五联疫苗\t628\t\n"
                    "2023-06-20\t小满\t五联疫苗\t628\t\n"
                    "2023-07-21\t小满\t五联疫苗\t628\t\n"
                    "2024-05-21\t小满\t五联疫苗\t628\t\n"
                    "2023-11-25\t小满\tEV71疫苗\t268\t\n"
                    "2024-10-09\t小满\t流感疫苗\t159\t\n")
        code, out = self.run_cli("paid", "--dir", self.tmp)
        self.assertEqual(code, 0)
        self.assertIn("五联疫苗           4 针  ¥2,512", out)
        self.assertIn("年针", out)
        self.assertIn("自费合计: ¥2,939", out)   # 2512 + 268 + 159

    def test_free_rows_excluded(self):
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n",
                    DOSE_HDR + "2024-02-01\t小满\t乙肝疫苗\t\t\n")
        code, out = self.run_cli("paid", "--dir", self.tmp)
        self.assertEqual(code, 0)
        self.assertIn("无自费在册", out)

    def test_bad_price_exit2(self):
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n",
                    DOSE_HDR + "2024-02-01\t小满\t五联疫苗\t六二八\t\n")
        code, out = self.run_cli("paid", "--dir", self.tmp)
        self.assertEqual(code, 2)


class TestScheduleOverride(Base):
    def test_je_inactivated_alternative(self):
        """乙脑灭活替代程序 4 剂:--schedule 整表翻案,2 剂记录变欠 1
        (29 月龄应 3 剂);缺省减毒表下同一本账全齐。"""
        self.base_ledger(omit={("乙脑减毒活疫苗", 1), ("乙脑减毒活疫苗", 2)},
                         extra=[("2024-09-01", "乙脑灭活疫苗"),
                                ("2024-10-01", "乙脑灭活疫苗")])
        sched = self.write_sched("# 灭活替代\nje\t8,9,24,72\n")
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", ASOF_B, "--schedule", sched)
        self.assertEqual(code, 4)   # 4 剂程序下 29 月龄应 3 剂,只打 2 剂
        self.assertIn("乙脑          4   2", out)
        # 缺省(减毒 2 剂)下同一本账是齐的
        code, out = self.run_cli("report", "--dir", self.tmp, "--as-of", ASOF_B)
        self.assertEqual(code, 0)

    def test_unknown_antigen_in_schedule_refused(self):
        self.base_ledger()
        sched = self.write_sched("水痘针\t8,18\n")
        code, out = self.run_cli("report", "--dir", self.tmp, "--schedule", sched)
        self.assertEqual(code, 1)   # SystemExit(str) → 1

    def test_schedule_total_changes_conservation(self):
        """程序被翻案后,守恒恒等式跟着新表走(不是钉死 22 的死账)。"""
        self.ledger(KID_HDR + "小满\t2022-01-01\t\n",
                    DOSE_HDR + "2022-09-01\t小满\t乙脑灭活疫苗\t\t\n"
                    "2022-10-01\t小满\t乙脑灭活疫苗\t\t\n")
        sched = self.write_sched("je\t8,9,24,72\n")
        code, out = self.run_cli("validate", "--dir", self.tmp,
                                 "--schedule", sched)
        self.assertEqual(code, 0)
        self.assertIn("翻案表合计 24", out)   # 22 − 2 + 4


class TestValidate(Base):
    def test_sample_validate_green(self):
        self.ledger(KID_HDR + "小满\t2023-03-15\t\n", DOSE_HDR +
                    "2023-05-20\t小满\t五联疫苗\t628\t\n"
                    "2023-06-20\t小满\t五联疫苗\t628\t\n"
                    "2023-07-21\t小满\t五联疫苗\t628\t\n"
                    "2024-05-21\t小满\t五联疫苗\t628\t\n"
                    "2023-11-17\t小满\t麻腮风疫苗\t\t\n")
        code, out = self.run_cli("validate", "--dir", self.tmp)
        self.assertEqual(code, 0)
        self.assertIn("全部通过", out)
        self.assertIn("已覆盖 9 + 欠 7 + 未到龄 6 == 22 剂", out)

    def test_program_total_pinned_to_22(self):
        self.base_ledger()
        code, out = self.run_cli("validate", "--dir", self.tmp)
        self.assertIn("22 == 通识 22", out)

    def test_base_ledger_conservation_zero_owed(self):
        self.base_ledger()
        code, out = self.run_cli("validate", "--dir", self.tmp,
                                 "--as-of", ASOF_B)
        self.assertIn("已覆盖 18 + 欠 0 + 未到龄 4 == 22 剂", out)
        self.assertEqual(code, 0)


class TestMultiKid(Base):
    def test_two_kids_isolated(self):
        """干净的孩子不背账坏的锅;空账的孩子照常红灯——互不串账。"""
        counters = {}
        kept = []
        for dt, prod in BASE_ROWS:
            counters[prod] = counters.get(prod, 0) + 1
            kept.append("%s\t大宝\t%s\t\t" % (dt, prod))
        self.ledger(KID_HDR + "大宝\t2024-01-01\t\n二宝\t2024-01-01\t\n",
                    DOSE_HDR + "\n".join(kept) + "\n")
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", ASOF_B)
        self.assertEqual(code, 4)   # 二宝一针没打
        i_a, i_b = out.index("大宝"), out.index("二宝")
        self.assertLess(i_a, i_b)
        seg_a = out[i_a:i_b]
        self.assertIn("超龄欠 0 项", seg_a)
        self.assertIn("✗超龄欠针", out[i_b:])

    def test_kid_order_follows_kids_tsv(self):
        self.ledger(KID_HDR + "阿二\t2024-01-01\t\n阿大\t2022-01-01\t\n",
                    DOSE_HDR + "2024-02-01\t阿二\t乙肝疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp,
                                 "--as-of", "2026-01-01")
        self.assertLess(out.index("阿二"), out.index("阿大"))


class TestZeroWallClock(Base):
    def test_no_wall_clock_in_source(self):
        with open(os.path.join(os.path.dirname(HERE), "due_dose.py"),
                  encoding="utf-8") as f:
            src = f.read()
        for bad in ("datetime.now", "date.today", "time.time", "utcnow"):
            self.assertNotIn(bad, src)

    def test_reproducible_bytes(self):
        self.base_ledger()
        c1, o1 = self.run_cli("report", "--dir", self.tmp, "--as-of", ASOF_B)
        c2, o2 = self.run_cli("report", "--dir", self.tmp, "--as-of", ASOF_B)
        self.assertEqual(c1, c2)
        self.assertEqual(o1, o2)

    def test_asof_defaults_to_ledger_max(self):
        self.ledger(KID_HDR + "小满\t2024-01-01\t\n",
                    DOSE_HDR + "2024-02-01\t小满\t乙肝疫苗\t\t\n")
        code, out = self.run_cli("report", "--dir", self.tmp)
        self.assertIn("as-of: 2024-02-01 (账本最大日期,零墙钟)", out)

    def test_examples_snapshots_byte_exact(self):
        """仓库样例:CLI 重放 == 快照文件,逐字节(CI 同款检查)。"""
        import subprocess
        ex = os.path.join(os.path.dirname(HERE), "examples")
        if not os.path.exists(os.path.join(ex, "doses.tsv")):
            self.skipTest("examples not built")
        proc = subprocess.run([sys.executable,
                               os.path.join(ex, "build_examples.py"), "--check"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class TestSampleStory(Base):
    """样例账本的故事线:搬家丢的两针、五联的翻译、查验排期、时间机器。"""

    EX = os.path.join(os.path.dirname(os.path.abspath(HERE)), "examples")

    def setUp(self):
        super().setUp()
        if not os.path.exists(os.path.join(self.EX, "doses.tsv")):
            self.skipTest("examples not built")

    def test_report_red_390_days(self):
        code, out = self.run_cli("report", "--dir", self.EX)
        self.assertEqual(code, 4)
        self.assertIn("已超 390 天", out)
        self.assertIn("2 岁 6 个月", out)
        self.assertIn("麻腮风         2   1  ✗超龄欠针", out)

    def test_time_machine_green_before_move(self):
        code, out = self.run_cli("report", "--dir", self.EX,
                                 "--as-of", "2024-08-01")
        self.assertEqual(code, 0)
        self.assertIn("超龄欠 0 项", out)
        self.assertIn("后视行排除", out)

    def test_catchup_kindergarten(self):
        code, out = self.run_cli("catchup", "--dir", self.EX,
                                 "--by", "2026-08-31",
                                 "--label", "幼儿园入园查验")
        self.assertEqual(code, 0)
        self.assertIn("需补 3 剂", out)
        self.assertIn("麻腮风 第2剂", out)
        self.assertIn("2026-03-15  流脑AC 第1剂", out)
        self.assertIn("余量 169 天", out)

    def test_paid_total_3279(self):
        code, out = self.run_cli("paid", "--dir", self.EX)
        self.assertEqual(code, 0)
        self.assertIn("自费合计: ¥3,279", out)
        self.assertIn("⚠半程", out)


if __name__ == "__main__":
    unittest.main()
