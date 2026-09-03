# -*- coding: utf-8 -*-
"""A4/A5 验收：分区边界、校准门、归零保护。"""
import unittest
from datetime import date, timedelta

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import redline
from redline import (CALIBRATION_DAYS, build_report, daily_loads, zone_of)


def make_sessions(start_day, n_days, load_per_day, rpe=5):
    """在连续 n_days 天里制造每日 load_per_day 的会话（minutes×rpe 拆分随意）。"""
    sessions = []
    start = date(2026, 1, 1) + timedelta(days=start_day)
    for k in range(n_days):
        minutes = load_per_day / rpe
        sessions.append({"date": start + timedelta(days=k),
                         "activity": "跑", "minutes": minutes, "rpe": rpe,
                         "notes": "", "load": float(load_per_day)})
    return sessions


class TestZoneBoundaries(unittest.TestCase):
    def test_sweet_spot_bounds_inclusive(self):
        self.assertEqual(zone_of(0.8), "green")
        self.assertEqual(zone_of(1.0), "green")
        self.assertEqual(zone_of(1.3), "green")     # 甜区含上界

    def test_amber_exclusive(self):
        self.assertEqual(zone_of(1.30001), "amber")
        self.assertEqual(zone_of(1.5), "amber")     # 红线是严格大于

    def test_red_strictly_above(self):
        self.assertEqual(zone_of(1.50001), "red")
        self.assertEqual(zone_of(2.0), "red")

    def test_blue_below_sweet(self):
        self.assertEqual(zone_of(0.79), "blue")
        self.assertEqual(zone_of(0.5), "blue")

    def test_gray_for_none(self):
        self.assertEqual(zone_of(None), "gray")

    def test_uncalibrated_or_frozen_never_judged(self):
        self.assertEqual(zone_of(2.0, calibrated=False), "gray")
        self.assertEqual(zone_of(2.0, frozen=True), "gray")
        self.assertEqual(zone_of(1.0, calibrated=False), "gray")


class TestCalibrationGate(unittest.TestCase):
    def test_before_calibration_refuses_zone(self):
        # 10 个连续日：首尾差 9 天，未过 21 天校准线
        sessions = make_sessions(0, 10, 500)
        rep = build_report(daily_loads(sessions))
        self.assertFalse(rep["calibrated"])
        self.assertEqual(rep["calibration_shortfall"], CALIBRATION_DAYS - 9)
        self.assertEqual(rep["current"]["zone"], "gray")
        # 周表里的早期周也不判区
        for w in rep["weeks"]:
            self.assertEqual(w["zone"], "gray")

    def test_after_calibration_zone_active(self):
        # 28 天稳定 700/日 → 校准通过，比率 1.0 甜区
        sessions = make_sessions(0, 28, 700)
        rep = build_report(daily_loads(sessions))
        self.assertTrue(rep["calibrated"])
        self.assertEqual(rep["current"]["zone"], "green")
        self.assertAlmostEqual(rep["current"]["acwr"], 1.0, places=9)

    def test_calibration_day_boundary(self):
        # 恰好第 21 天（首练后 21 天）通过
        sessions = make_sessions(0, 22, 700)
        rep = build_report(daily_loads(sessions))
        self.assertTrue(rep["calibrated"])

    def test_uncalibrated_red_load_not_labeled_red(self):
        # 校准期里塞一个爆表周：数字夸张但不许亮红
        sessions = make_sessions(0, 7, 1500)
        rep = build_report(daily_loads(sessions))
        self.assertFalse(rep["calibrated"])
        flags = [f for w in rep["weeks"] for f in w["flags"]]
        self.assertFalse(any("红线" in f for f in flags))

    def test_calibration_holds_when_as_of_backdated(self):
        sessions = make_sessions(0, 40, 700)
        daily = daily_loads(sessions)
        late = build_report(daily, as_of=date(2026, 2, 10))
        self.assertTrue(late["calibrated"])
        early = build_report(daily, as_of=date(2026, 1, 15))
        self.assertFalse(early["calibrated"])


class TestZeroChronic(unittest.TestCase):
    def test_all_chronic_gone_returns_gray_not_crash(self):
        # 唯一会话在 40 天前：慢性归零，比率 None，区域 gray，不抛异常
        sessions = make_sessions(0, 2, 800)
        rep = build_report(daily_loads(sessions), as_of=date(2026, 2, 15))
        self.assertIsNone(rep["current"]["acwr"])
        self.assertEqual(rep["current"]["zone"], "gray")

    def test_single_session_report_complete(self):
        sessions = make_sessions(0, 1, 500)
        rep = build_report(daily_loads(sessions))
        self.assertEqual(rep["sessions"], 1)
        self.assertFalse(rep["calibrated"])
        self.assertEqual(rep["rebuild"], None)
        self.assertEqual(len(rep["weeks"]), 1)


class TestConstants(unittest.TestCase):
    def test_methodology_defaults(self):
        self.assertEqual(redline.ACUTE_DAYS, 7)
        self.assertEqual(redline.CHRONIC_DAYS, 28)
        self.assertEqual(redline.CALIBRATION_DAYS, 21)
        self.assertEqual(redline.LAYOFF_DAYS, 14)
        self.assertEqual(redline.FREEZE_DAYS, 28)
        self.assertEqual((redline.ZONE_LOW, redline.ZONE_HIGH, redline.ZONE_RED),
                         (0.8, 1.3, 1.5))
        self.assertEqual(redline.REBUILD_LADDER, [0.40, 0.60, 0.80, 1.00])


if __name__ == "__main__":
    unittest.main()
