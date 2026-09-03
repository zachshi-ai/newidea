# -*- coding: utf-8 -*-
"""A8 验收：伤停检测与归队阶梯（含 is_frozen 回归测试）。"""
import unittest
from datetime import date, timedelta

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from redline import (FREEZE_DAYS, LAYOFF_DAYS, REBUILD_LADDER, build_report,
                     chronic_weekly_at, daily_loads, find_layoffs,
                     freeze_until, is_frozen, rebuild_ladder)


def sess(d, load, rpe=5):
    return {"date": d, "activity": "跑", "minutes": load / rpe, "rpe": rpe,
            "notes": "", "load": float(load)}


BASE = date(2026, 1, 1)


class TestLayoffDetection(unittest.TestCase):
    def test_gap_of_13_days_not_a_layoff(self):
        daily = {BASE: 300.0, BASE + timedelta(days=14): 300.0}  # 空窗 13 天
        self.assertEqual(find_layoffs(daily), [])

    def test_gap_of_14_days_is_a_layoff(self):
        daily = {BASE: 300.0, BASE + timedelta(days=15): 300.0}  # 空窗 14 天
        layoffs = find_layoffs(daily)
        self.assertEqual(layoffs, [(BASE, BASE + timedelta(days=15))])

    def test_threshold_constant_is_fourteen(self):
        self.assertEqual(LAYOFF_DAYS, 14)
        self.assertEqual(FREEZE_DAYS, 28)

    def test_multiple_layoffs_detected(self):
        daily = {BASE: 100.0,
                 BASE + timedelta(days=20): 100.0,
                 BASE + timedelta(days=60): 100.0}
        layoffs = find_layoffs(daily)
        self.assertEqual(len(layoffs), 2)

    def test_sparse_short_gaps_ignored(self):
        # 每隔 5 天练一次的正常节奏：无伤停
        daily = {BASE + timedelta(days=7 * k): 400.0 for k in range(10)}
        self.assertEqual(find_layoffs(daily), [])


class TestRebuildLadder(unittest.TestCase):
    def test_ladder_percentages(self):
        rows = rebuild_ladder(1000.0)
        self.assertEqual([r["pct"] for r in rows], [0.40, 0.60, 0.80, 1.00])
        self.assertEqual([r["week_load"] for r in rows],
                         [400.0, 600.0, 800.0, 1000.0])

    def test_ladder_constant(self):
        self.assertEqual(REBUILD_LADDER, [0.40, 0.60, 0.80, 1.00])


class TestFreezeWindow(unittest.TestCase):
    RET = date(2026, 8, 6)

    def test_return_day_is_frozen(self):
        self.assertTrue(is_frozen(self.RET, [(BASE, self.RET)]))

    def test_day_27_frozen_day_28_not(self):
        self.assertTrue(is_frozen(self.RET + timedelta(days=FREEZE_DAYS - 1),
                                  [(BASE, self.RET)]))
        self.assertFalse(is_frozen(self.RET + timedelta(days=FREEZE_DAYS),
                                   [(BASE, self.RET)]))

    def test_days_before_layoff_not_frozen(self):
        # 回归测试：冻结只作用于归队之后，不许把历史周一并冻结
        self.assertFalse(is_frozen(date(2026, 7, 12), [(BASE, self.RET)]))
        self.assertFalse(is_frozen(BASE, [(BASE, self.RET)]))

    def test_freeze_until_none_without_layoffs(self):
        self.assertIsNone(freeze_until([]))

    def test_freeze_uses_latest_layoff(self):
        later = date(2026, 9, 1)
        self.assertTrue(is_frozen(later, [(BASE, self.RET), (BASE, later)]))


class TestReportRebuild(unittest.TestCase):
    def test_layoff_report_anchors_pre_injury_baseline(self):
        # 4 周稳定 700/日（慢性周均 700），然后空窗 20 天，再归队
        sessions = [sess(BASE + timedelta(days=k), 700) for k in range(28)]
        gap_start = BASE + timedelta(days=27)
        ret = gap_start + timedelta(days=21)
        sessions.append(sess(ret, 200))
        rep = build_report(daily_loads(sessions))
        self.assertEqual(len(rep["layoffs"]), 1)
        lo = rep["layoffs"][0]
        self.assertEqual(lo["days"], 20)
        pre_c = chronic_weekly_at(daily_loads(sessions), gap_start)
        self.assertAlmostEqual(rep["rebuild"]["pre_chronic_weekly"], pre_c)
        # 阶梯以伤前基线为锚，而不是已衰减的当前基线
        self.assertAlmostEqual(rep["rebuild"]["ladder"][0]["week_load"],
                               pre_c * 0.4)

    def test_rebuild_weeks_are_frozen_in_report(self):
        sessions = [sess(BASE + timedelta(days=k), 700) for k in range(28)]
        ret = BASE + timedelta(days=27) + timedelta(days=21)
        sessions.append(sess(ret, 200))
        rep = build_report(daily_loads(sessions))
        ret_week = [w for w in rep["weeks"]
                    if w["monday"] <= ret <= w["sunday"]]
        self.assertTrue(ret_week[0]["frozen"])
        self.assertEqual(ret_week[0]["zone"], "gray")

    def test_no_layoff_no_rebuild_section(self):
        sessions = [sess(BASE + timedelta(days=k), 700) for k in range(28)]
        rep = build_report(daily_loads(sessions))
        self.assertIsNone(rep["rebuild"])
        self.assertEqual(rep["layoffs"], [])


if __name__ == "__main__":
    unittest.main()
