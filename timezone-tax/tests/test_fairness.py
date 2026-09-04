#!/usr/bin/env python3
"""时区税验收 A4 — 公平度量：基尼精确、最惨比率、判定阈值。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import timezone_tax as tzt  # noqa: E402


class TestGini(unittest.TestCase):
    def test_degenerate_inputs(self):
        self.assertEqual(tzt.gini([]), 0.0)
        self.assertEqual(tzt.gini([5.0]), 0.0)
        self.assertEqual(tzt.gini([0.0, 0.0, 0.0]), 0.0)

    def test_equal_split_is_zero(self):
        self.assertAlmostEqual(tzt.gini([1.0, 1.0, 1.0]), 0.0)

    def test_known_values(self):
        # 手算钉死：Σ|xi-xj| 有序对 / (2·n²·mean)
        self.assertAlmostEqual(tzt.gini([3.0, 0.0, 0.0]), 2.0 / 3.0,
                               places=9)
        self.assertAlmostEqual(tzt.gini([0.0, 78.0, 156.0]), 4.0 / 9.0,
                               places=9)
        self.assertAlmostEqual(tzt.gini([0.0, 52.0, 78.0, 156.0]),
                               988.0 / (2 * 16 * 71.5), places=9)

    def test_monotone_under_concentration(self):
        flat = tzt.gini([1.0, 1.0, 1.0, 1.0])
        skewed = tzt.gini([4.0, 0.0, 0.0, 0.0])
        self.assertGreater(skewed, flat)


class TestRatio(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(tzt.burden_ratio([2.0, 1.0]), 2.0)
        self.assertAlmostEqual(tzt.burden_ratio([4.0, 2.0, 1.0]), 4.0)
        self.assertAlmostEqual(tzt.burden_ratio([0.0, 0.0]), 1.0)
        self.assertAlmostEqual(tzt.burden_ratio([]), 1.0)

    def test_zero_min_is_infinite(self):
        self.assertIsNone(tzt.burden_ratio([2.0, 0.0]))
        self.assertIsNone(tzt.burden_ratio([5.0, 0.0, 3.0]))


class TestVerdict(unittest.TestCase):
    def test_healthy_split(self):
        level, reasons = tzt.fairness_verdict({"a": 1.5, "b": 1.5})
        self.assertEqual(level, "ok")

    def test_single_member_is_too_early_to_talk_fairness(self):
        level, reasons = tzt.fairness_verdict({"solo": 9.0})
        self.assertEqual(level, "ok")
        self.assertIn("成员不足", reasons[0])

    def test_all_zero_is_free_meeting(self):
        level, reasons = tzt.fairness_verdict({"a": 0.0, "b": 0.0})
        self.assertEqual(level, "ok")
        self.assertIn("全员零税", reasons[0])

    def test_mild_skew_warns(self):
        # gini([3,1]) = 0.25 ≤ 0.3 但最惨比率 3 > 2
        level, reasons = tzt.fairness_verdict({"a": 3.0, "b": 1.0})
        self.assertEqual(level, "warn")
        self.assertTrue(any("最惨比率" in r for r in reasons))

    def test_never_payer_alarms(self):
        level, reasons = tzt.fairness_verdict(
            {"Dawei": 156.0, "Alice": 78.0, "Chitra": 52.0, "Bruno": 0.0})
        self.assertEqual(level, "alarm")
        self.assertTrue(any("从未缴税" in r for r in reasons))

    def test_high_gini_alarms(self):
        level, _ = tzt.fairness_verdict({"a": 5.0, "b": 0.0, "c": 0.0})
        self.assertEqual(level, "alarm")

    def test_thresholds_are_configurable(self):
        # 同一组数字，把阈值放宽就变健康
        level, _ = tzt.fairness_verdict({"a": 3.0, "b": 1.0},
                                        ratio_warn=5.0, ratio_alarm=9.0)
        self.assertEqual(level, "ok")


if __name__ == "__main__":
    unittest.main()
