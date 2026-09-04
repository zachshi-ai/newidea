#!/usr/bin/env python3
"""Acceptance tests for life-tag (生命价签) — price tags & overtime decisions."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import life_tag as lt  # noqa: E402

METRO = {
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


class TestPriceTag(unittest.TestCase):
    def setUp(self):
        self.p = lt.validate_profile(METRO)
        self.e = lt.economics(self.p)
        self.true = self.e["true"]
        self.day_net = self.e["day_net"]

    def test_hours_is_price_over_true(self):
        t = lt.price_tag(6999.0, self.e, 8.0)
        self.assertAlmostEqual(t["hours"], 6999.0 / self.true)

    def test_minutes(self):
        t = lt.price_tag(6999.0, self.e, 8.0)
        self.assertAlmostEqual(t["minutes"], 6999.0 / self.true * 60.0)

    def test_shifts_is_price_over_day_net(self):
        t = lt.price_tag(6999.0, self.e, 8.0)
        self.assertAlmostEqual(t["shifts"], 6999.0 / self.day_net)

    def test_iphone_ground_truth(self):
        # 真实时薪 ≈ 55.66：iPhone = 125.7 生命小时 = 10.3 个班次
        t = lt.price_tag(6999.0, self.e, 8.0)
        self.assertAlmostEqual(t["hours"], 125.7, places=1)
        self.assertAlmostEqual(t["shifts"], 10.3, places=1)

    def test_milk_tea_ground_truth(self):
        # 一杯奶茶 = 22 分钟的命
        t = lt.price_tag(20.0, self.e, 8.0)
        self.assertAlmostEqual(t["minutes"], 21.6, places=1)
        self.assertAlmostEqual(t["hours"], 0.36, places=2)

    def test_over_pulse_line(self):
        t = lt.price_tag(6999.0, self.e, 8.0)
        self.assertTrue(t["over_line"])

    def test_under_pulse_line(self):
        t = lt.price_tag(20.0, self.e, 8.0)
        self.assertFalse(t["over_line"])

    def test_exactly_on_line_is_not_over(self):
        price = self.true * 8.0  # 恰好 8 小时
        t = lt.price_tag(price, self.e, 8.0)
        self.assertAlmostEqual(t["hours"], 8.0)
        self.assertFalse(t["over_line"])

    def test_custom_line_override(self):
        t = lt.price_tag(6999.0, self.e, 200.0)
        self.assertFalse(t["over_line"])
        t2 = lt.price_tag(6999.0, self.e, 100.0)
        self.assertTrue(t2["over_line"])

    def test_unit_minutes_below_three_hours(self):
        t = lt.price_tag(self.true * 2.9, self.e, 8.0)
        self.assertEqual(t["unit"], "minutes")

    def test_unit_hours_between_three_and_200(self):
        t = lt.price_tag(self.true * 50, self.e, 8.0)
        self.assertEqual(t["unit"], "hours")

    def test_unit_shifts_above_200_hours(self):
        t = lt.price_tag(self.true * 201, self.e, 8.0)
        self.assertEqual(t["unit"], "shifts")

    def test_expensive_salary_compresses_hours(self):
        # 同样的钱，时薪高的人生命价签更小
        rich = lt.validate_profile({"gross_monthly": 60000, "tax_rate": 0.2,
                                    "commute_min": 0, "recovery_ratio": 0.1})
        e_rich = lt.economics(rich)
        self.assertLess(lt.price_tag(6999.0, e_rich, 8.0)["hours"],
                        lt.price_tag(6999.0, self.e, 8.0)["hours"])


class TestShiftsText(unittest.TestCase):
    def test_tiny(self):
        self.assertIn("不足 0.05", lt._shifts_text(0.01))

    def test_normal(self):
        self.assertEqual(lt._shifts_text(10.28), "10.3 个班次的净收入")

    def test_boundary_not_tiny(self):
        self.assertIn("0.1", lt._shifts_text(0.05))


class TestOvertime(unittest.TestCase):
    def setUp(self):
        self.p = lt.validate_profile(METRO)
        self.e = lt.economics(self.p)

    def test_marginal_is_nominal_times_mult(self):
        o = lt.overtime_math(4.0, 1.5, self.e)
        self.assertAlmostEqual(o["marginal"], self.e["nominal"] * 1.5)
        self.assertAlmostEqual(o["marginal"], 136.61, places=2)

    def test_earn(self):
        o = lt.overtime_math(4.0, 1.5, self.e)
        self.assertAlmostEqual(o["earn"], o["marginal"] * 4.0)

    def test_premium_over_avg(self):
        o = lt.overtime_math(4.0, 1.5, self.e)
        self.assertAlmostEqual(o["premium"], o["marginal"] - self.e["true"])
        self.assertGreater(o["premium"], 0)

    def test_even_flat_rate_beats_avg(self):
        # 反直觉洞见：1 倍率的边际时薪（=名义时薪）仍高于被侵蚀的真实时薪
        o = lt.overtime_math(1.0, 1.0, self.e)
        self.assertAlmostEqual(o["marginal"], self.e["nominal"])
        self.assertTrue(o["worth_it"])

    def test_low_mult_not_worth(self):
        # 0.4 倍率：边际时薪 36.4 < 真实时薪 55.7
        o = lt.overtime_math(2.0, 0.4, self.e)
        self.assertFalse(o["worth_it"])
        self.assertLess(o["marginal"], self.e["true"])

    def test_breakeven_equals_marginal(self):
        o = lt.overtime_math(3.0, 2.0, self.e)
        self.assertAlmostEqual(o["breakeven"], o["marginal"])

    def test_zero_hours_still_reports_rates(self):
        o = lt.overtime_math(0.0, 1.5, self.e)
        self.assertAlmostEqual(o["earn"], 0.0)
        self.assertAlmostEqual(o["marginal"], self.e["nominal"] * 1.5)


if __name__ == "__main__":
    unittest.main()
