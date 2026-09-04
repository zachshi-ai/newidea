#!/usr/bin/env python3
"""Acceptance tests for life-tag (生命价签) — hourly economics & waterfall."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import life_tag as lt  # noqa: E402


def metro():
    """一线城市通勤画像（与 examples/metro_worker.json 一致）。"""
    return {
        "gross_monthly": 18000.0,
        "tax_rate": 0.15,
        "workdays": 21.0,
        "daily_hours": 8.0,
        "commute_min": 55.0,
        "commute_cost": 300.0,
        "recovery_ratio": 0.30,
        "work_costs_extra": 700.0,
        "pulse_line": 8.0,
        "currency": "¥",
    }


class TestEconomics(unittest.TestCase):
    def setUp(self):
        self.p = lt.validate_profile(metro())
        self.e = lt.economics(self.p)

    def test_net_month(self):
        self.assertAlmostEqual(self.e["net_month"], 15300.0)

    def test_nominal_hours(self):
        self.assertAlmostEqual(self.e["nominal_hours"], 168.0)

    def test_nominal(self):
        self.assertAlmostEqual(self.e["nominal"], 15300.0 / 168.0)

    def test_commute_hours(self):
        # 55 分钟 × 2 × 21 天 ÷ 60
        self.assertAlmostEqual(self.e["commute_hours"], 38.5)

    def test_recovery_hours(self):
        self.assertAlmostEqual(self.e["recovery_hours"], 50.4)

    def test_real_hours(self):
        self.assertAlmostEqual(self.e["real_hours"], 256.9)

    def test_true_hourly(self):
        self.assertAlmostEqual(self.e["true"], 14300.0 / 256.9)

    def test_true_below_nominal(self):
        self.assertLess(self.e["true"], self.e["nominal"])

    def test_ratio(self):
        self.assertAlmostEqual(self.e["ratio"], (14300.0 / 256.9) / (15300.0 / 168.0))
        self.assertLess(self.e["ratio"], 0.7)  # 名义时薪高估近四成

    def test_erosion_complement_of_ratio(self):
        self.assertAlmostEqual(self.e["erosion"], 1.0 - self.e["ratio"])

    def test_day_net(self):
        self.assertAlmostEqual(self.e["day_net"], 14300.0 / 21.0)


class TestWaterfallIdentity(unittest.TestCase):
    """瀑布分解的硬约束：三笔税之和与总侵蚀精确相抵，不多不少。"""

    def setUp(self):
        self.p = lt.validate_profile(metro())
        self.e = lt.economics(self.p)

    def test_taxes_sum_to_gap(self):
        gap = self.e["nominal"] - self.e["true"]
        taxes = (self.e["recovery_tax"] + self.e["commute_tax"]
                 + self.e["cost_tax"])
        self.assertAlmostEqual(gap, taxes, places=9)

    def test_recovery_tax_value(self):
        p1 = 15300.0 / (168.0 + 50.4)
        self.assertAlmostEqual(self.e["recovery_tax"], 15300.0 / 168.0 - p1)
        self.assertAlmostEqual(self.e["recovery_tax"], 21.0165, places=3)

    def test_commute_tax_value(self):
        p1 = 15300.0 / 218.4
        p2 = 15300.0 / 256.9
        self.assertAlmostEqual(self.e["commute_tax"], p1 - p2, places=9)
        self.assertAlmostEqual(self.e["commute_tax"], 10.4986, places=3)

    def test_cost_tax_value(self):
        self.assertAlmostEqual(self.e["cost_tax"], 1000.0 / 256.9, places=9)

    def test_order_is_recovery_then_commute_then_cost(self):
        # 恢复税只由恢复系数决定（固定 15300/218.4 分母），通勤税次之
        self.assertGreater(self.e["recovery_tax"], self.e["commute_tax"])
        self.assertGreater(self.e["commute_tax"], self.e["cost_tax"])

    def test_each_tax_nonnegative(self):
        for key in ("recovery_tax", "commute_tax", "cost_tax"):
            self.assertGreaterEqual(self.e[key], 0.0)


class TestEdges(unittest.TestCase):
    def test_no_commute_no_costs_low_recovery_true_near_nominal(self):
        p = lt.validate_profile({"gross_monthly": 10000, "tax_rate": 0.0,
                                 "recovery_ratio": 0.0})
        e = lt.economics(p)
        self.assertAlmostEqual(e["true"], e["nominal"])
        self.assertAlmostEqual(e["erosion"], 0.0)
        for key in ("recovery_tax", "commute_tax", "cost_tax"):
            self.assertAlmostEqual(e[key], 0.0)

    def test_only_recovery(self):
        p = lt.validate_profile({"gross_monthly": 10000, "tax_rate": 0.0,
                                 "recovery_ratio": 0.5})
        e = lt.economics(p)
        self.assertAlmostEqual(e["true"], 10000.0 / (168.0 + 84.0))
        self.assertAlmostEqual(e["commute_tax"], 0.0)
        self.assertAlmostEqual(e["cost_tax"], 0.0)

    def test_only_costs(self):
        p = lt.validate_profile({"gross_monthly": 10000, "tax_rate": 0.0,
                                 "recovery_ratio": 0.0,
                                 "work_costs_extra": 500.0})
        e = lt.economics(p)
        self.assertAlmostEqual(e["true"], 9500.0 / 168.0)
        self.assertAlmostEqual(e["recovery_tax"], 0.0)
        self.assertAlmostEqual(e["commute_tax"], 0.0)
        self.assertAlmostEqual(e["cost_tax"], 500.0 / 168.0)

    def test_full_tax_free_extreme_commute(self):
        # 通勤到上限：真实时薪被腰斩再腰斩
        p = lt.validate_profile({"gross_monthly": 10000, "tax_rate": 0.0,
                                 "commute_min": 480, "recovery_ratio": 1.0})
        e = lt.economics(p)
        self.assertAlmostEqual(e["real_hours"], 168.0 + 336.0 + 168.0)
        self.assertLess(e["ratio"], 0.3)

    def test_high_tax(self):
        p = lt.validate_profile({"gross_monthly": 10000, "tax_rate": 0.5})
        e = lt.economics(p)
        self.assertAlmostEqual(e["net_month"], 5000.0)


if __name__ == "__main__":
    unittest.main()
