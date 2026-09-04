#!/usr/bin/env python3
"""时区税验收 A3 — 税单：已知样例精确、可行性边界、自定义税率。"""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import timezone_tax as tzt  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "examples"))
import build_examples  # noqa: E402


def rows_by_name(bill):
    return dict((row["name"], row) for row in bill["rows"])


class TestKnownBill(unittest.TestCase):
    """2026-09-10（周四）15:00 UTC，四地团队全部处于夏令时/标准时稳定期。"""

    def setUp(self):
        self.team = build_examples.build_team_global()
        self.bill = tzt.bill_at_utc(self.team, datetime(2026, 9, 10, 15, 0))
        self.rows = rows_by_name(self.bill)

    def test_row_values(self):
        expected = [
            ("Alice · 旧金山", "周四 08:00", "early", 1.5),
            ("Bruno · 柏林", "周四 17:00", "prime", 0.0),
            ("Chitra · 班加罗尔", "周四 20:30", "evening", 1.0),
            ("Dawei · 上海", "周四 23:00", "night", 3.0),
        ]
        for name, local, band, tax in expected:
            row = self.rows[name]
            self.assertEqual((row["local"], row["band"], row["tax"]),
                             (local, band, tax))
            self.assertTrue(row["feasible"])

    def test_totals(self):
        self.assertAlmostEqual(self.bill["total"], 5.5)
        self.assertEqual(self.bill["max_payer"], "Dawei · 上海")
        self.assertTrue(self.bill["feasible"])

    def test_bills_dict_keeps_team_order(self):
        bills = tzt.bill_bills(self.bill)
        self.assertEqual(list(bills.keys()), list(
            m["name"] for m in self.team["members"]))

    def test_payer_signature(self):
        self.assertEqual(tzt.payer_signature(self.bill),
                         frozenset(["Alice · 旧金山", "Chitra · 班加罗尔",
                                    "Dawei · 上海"]))


class TestFeasibility(unittest.TestCase):
    def setUp(self):
        self.team = build_examples.build_team_global()

    def test_night_edge_is_sleep_band(self):
        # 16:00 UTC → 上海 00:00（次日），睡梦中
        bill = tzt.bill_at_utc(self.team, datetime(2026, 9, 10, 16, 0))
        rows = rows_by_name(bill)
        self.assertFalse(bill["feasible"])
        self.assertFalse(rows["Dawei · 上海"]["feasible"])
        self.assertEqual(rows["Dawei · 上海"]["reason"], "睡眠时段")
        self.assertEqual(rows["Dawei · 上海"]["local"], "周五 00:00")
        # 其他成员照常：柏林 18:00、班加罗尔 21:30 都进傍晚
        self.assertTrue(rows["Alice · 旧金山"]["feasible"])
        self.assertAlmostEqual(bill["total"], 5.0)

    def test_waking_start_boundary(self):
        # 13:54 UTC → 旧金山 06:54，醒着线上不可行；14:00 → 07:00 可行
        early = tzt.bill_at_utc(self.team, datetime(2026, 9, 10, 13, 54))
        self.assertFalse(early["feasible"])
        self.assertEqual(rows_by_name(early)["Alice · 旧金山"]["reason"],
                         "睡眠时段")
        on_time = tzt.bill_at_utc(self.team, datetime(2026, 9, 10, 14, 0))
        self.assertTrue(rows_by_name(on_time)["Alice · 旧金山"]["feasible"])

    def test_non_workday(self):
        # 2026-09-12 是周六
        bill = tzt.bill_at_utc(self.team, datetime(2026, 9, 12, 15, 0))
        self.assertFalse(bill["feasible"])
        for row in bill["rows"]:
            self.assertFalse(row["feasible"])
            self.assertEqual(row["reason"], "非工作日")

    def test_custom_team_weights_change_bill(self):
        team = build_examples.build_team_global()
        team["weights"] = {"night": 10.0}
        bill = tzt.bill_at_utc(team, datetime(2026, 9, 10, 15, 0))
        self.assertAlmostEqual(rows_by_name(bill)["Dawei · 上海"]["tax"], 10.0)
        self.assertAlmostEqual(bill["total"], 12.5)

    def test_zero_tax_slot_has_no_max_payer(self):
        # 旧金山(0) + 西五区(-300)：14:00 UTC 双双落在黄金时段
        team = {"members": [{"name": "安", "offset_min": 0},
                            {"name": "贝", "offset_min": -300}]}
        bill = tzt.bill_at_utc(team, datetime(2026, 9, 7, 14, 0))
        self.assertAlmostEqual(bill["total"], 0.0)
        self.assertIsNone(bill["max_payer"])
        self.assertTrue(bill["feasible"])


if __name__ == "__main__":
    unittest.main()
