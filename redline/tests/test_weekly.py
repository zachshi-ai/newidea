# -*- coding: utf-8 -*-
"""A7 验收：单调性、应变与周表。"""
import unittest
from datetime import date, timedelta

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from redline import (MONOTONY_FLAG, build_report, daily_loads,
                     monotony_strain, weekly_rows)


def run_sessions(week_day_offsets, minutes=60, rpe=5):
    """offsets: 相对 2026-01-05（周一）的天数。"""
    base = date(2026, 1, 5)
    return [{"date": base + timedelta(days=o), "activity": "跑",
             "minutes": minutes, "rpe": rpe, "notes": "",
             "load": float(minutes * rpe)} for o in week_day_offsets]


class TestMonotonyStrain(unittest.TestCase):
    def test_high_monotony_for_grind_week(self):
        # 7 天每天 300：σ=0 → 单调性 ∞
        mon, strain = monotony_strain([300.0] * 7)
        self.assertEqual(mon, float("inf"))
        self.assertEqual(strain, float("inf"))

    def test_low_monotony_for_polarized_week(self):
        # 硬易交替：σ 大 → 单调性低
        mon, _ = monotony_strain([600, 0, 600, 0, 600, 0, 0])
        self.assertLess(mon, 1.0)

    def test_monotony_exact_value(self):
        loads = [200.0, 0.0, 300.0, 0.0, 200.0, 0.0, 400.0]
        mon, strain = monotony_strain(loads)
        import statistics
        expected = statistics.mean(loads) / statistics.pstdev(loads)
        self.assertAlmostEqual(mon, expected, places=12)
        self.assertAlmostEqual(strain, sum(loads) * expected, places=9)

    def test_all_zero_week(self):
        mon, strain = monotony_strain([0.0] * 7)
        self.assertEqual(mon, 0.0)
        self.assertEqual(strain, 0.0)

    def test_single_day_week(self):
        # 单日周没有离散度可言：σ=0 → ∞（诚实报告，不假装）
        mon, strain = monotony_strain([500.0])
        self.assertEqual(mon, float("inf"))


class TestWeeklyRows(unittest.TestCase):
    def test_partial_current_week_uses_elapsed_days(self):
        # 只有一周的周三：日均应按 1 天算（当时刻只过 1 天）
        sessions = run_sessions([2])          # 周三
        daily = daily_loads(sessions)
        rows = weekly_rows(daily, date(2026, 1, 5), date(2026, 1, 7))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["elapsed_days"], 3)   # 周一~周三
        self.assertAlmostEqual(rows[0]["daily_avg"], 300.0 / 3)

    def test_week_monday_anchored_to_iso(self):
        # 首练在周四：第一周从周一对齐，只算 4 天
        sessions = run_sessions([3])
        daily = daily_loads(sessions)
        rows = weekly_rows(daily, date(2026, 1, 5), date(2026, 1, 8))
        self.assertEqual(rows[0]["monday"], date(2026, 1, 5))
        self.assertEqual(rows[0]["effective_end"], date(2026, 1, 8))
        self.assertEqual(rows[0]["elapsed_days"], 4)

    def test_full_week_totals(self):
        sessions = run_sessions([0, 2, 4], minutes=60, rpe=5)   # 一三五
        daily = daily_loads(sessions)
        rows = weekly_rows(daily, date(2026, 1, 5), date(2026, 1, 11))
        self.assertAlmostEqual(rows[0]["total"], 3 * 300.0)
        import statistics
        loads = [300.0, 0, 300.0, 0, 300.0, 0, 0]
        expected = statistics.mean(loads) / statistics.pstdev(loads)
        self.assertAlmostEqual(rows[0]["monotony"], expected, places=9)

    def test_week_spans_multiple_iso_weeks(self):
        # 10 天数据 → 两个 ISO 周（第二个为部分周）
        sessions = run_sessions(list(range(10)))
        daily = daily_loads(sessions)
        rows = weekly_rows(daily, date(2026, 1, 5), date(2026, 1, 14))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["elapsed_days"], 7)
        self.assertEqual(rows[1]["elapsed_days"], 3)

    def test_high_monotony_flag_in_report(self):
        # 每天一模一样的两周 → 单调性 ∞，必须举旗
        sessions = run_sessions(list(range(14)), minutes=50, rpe=6)
        rep = build_report(daily_loads(sessions))
        flags = [f for w in rep["weeks"] for f in w["flags"]]
        self.assertTrue(any("单调性" in f for f in flags))

    def test_strain_displayed_not_judged(self):
        # 应变只展示（绝对量纲因人而异），不做绝对阈值判定
        sessions = run_sessions([0, 1, 2, 3, 4, 5, 6], minutes=60, rpe=5)
        rep = build_report(daily_loads(sessions))
        for w in rep["weeks"]:
            self.assertIn("strain", w)
        flags = [f for w in rep["weeks"] for f in w["flags"]]
        self.assertFalse(any("应变" in f for f in flags))

    def test_monotony_threshold_constant(self):
        self.assertEqual(MONOTONY_FLAG, 2.0)


if __name__ == "__main__":
    unittest.main()
