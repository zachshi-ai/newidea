# -*- coding: utf-8 -*-
"""A2/A3 验收：负荷与 ACWR 数学。"""
import unittest
from datetime import date, timedelta

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from redline import (acute_at, chronic_weekly_at, acwr_at, daily_loads,
                     window_sum)


def daily_from(loads_by_offset, start=date(2026, 1, 1)):
    """{相对首日偏移: 当日负荷} → daily map。"""
    return {start + timedelta(days=k): v for k, v in loads_by_offset.items()}


class TestLoads(unittest.TestCase):
    def test_session_rpe_load(self):
        sessions = [{"date": date(2026, 1, 1), "load": 0}]
        # load = minutes × rpe 的精确性由解析测试覆盖；这里钉死口径：
        s = {"minutes": 70, "rpe": 7}
        self.assertEqual(s["minutes"] * s["rpe"], 490)

    def test_window_sum_counts_missing_days_as_zero(self):
        daily = daily_from({0: 100, 6: 100})
        self.assertEqual(window_sum(daily, date(2026, 1, 7), 7), 200.0)
        self.assertEqual(window_sum(daily, date(2026, 1, 5), 7), 100.0)
        self.assertEqual(window_sum(daily, date(2026, 1, 4), 7), 100.0)  # 只剩第 0 日
        self.assertEqual(window_sum(daily, date(2025, 12, 31), 7), 0.0)  # 7 日窗外

    def test_steady_state_acwr_is_one(self):
        # 28 天每天 100 负荷：急性 = 700，慢性周均 = 2800/4 = 700，比率 1.0
        daily = daily_from({k: 100.0 for k in range(28)})
        d = date(2026, 1, 28)
        a, c, ratio = acwr_at(daily, d)
        self.assertEqual(a, 700.0)
        self.assertEqual(c, 700.0)
        self.assertAlmostEqual(ratio, 1.0, places=12)

    def test_acwr_exact_fixture(self):
        # 前 21 天每天 80（慢性原料），最后 7 天每天 160（加量）
        loads = {k: 80.0 for k in range(21)}
        loads.update({k: 160.0 for k in range(21, 28)})
        daily = daily_from(loads)
        d = date(2026, 1, 28)
        a, c, ratio = acwr_at(daily, d)
        self.assertEqual(a, 1120.0)                    # 7 × 160
        self.assertAlmostEqual(c, (21 * 80 + 7 * 160) / 4, places=12)  # (1680+1120)/4
        self.assertAlmostEqual(ratio, 1120.0 / 700.0, places=12)       # 1.6

    def test_chronic_is_mean_weekly_not_raw_sum(self):
        daily = daily_from({k: 100.0 for k in range(28)})
        d = date(2026, 1, 28)
        self.assertEqual(window_sum(daily, d, 28), 2800.0)
        self.assertEqual(chronic_weekly_at(daily, d), 700.0)

    def test_acute_window_is_seven_days_inclusive(self):
        daily = daily_from({20: 50.0, 21: 60.0, 22: 70.0})
        d = date(2026, 1, 23)
        self.assertEqual(acute_at(daily, d), 180.0)   # 偏移 20/21/22
        # 窗口外（偏移 15 = 8 天前）不计入
        daily2 = daily_from({15: 999.0, 20: 50.0, 21: 60.0, 22: 70.0})
        self.assertEqual(acute_at(daily2, d), 180.0)

    def test_chronic_zero_returns_none_ratio(self):
        daily = daily_from({0: 100.0})   # 唯一会话在 28 天窗外
        d = date(2026, 2, 1)
        a, c, ratio = acwr_at(daily, d)
        self.assertEqual(c, 0.0)
        self.assertIsNone(ratio)

    def test_doubles_aggregate_into_daily(self):
        from redline import parse_session_file
        import os, tempfile
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "log.tsv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("date\tminutes\trpe\n")
            f.write("2026-01-01\t40\t4\n")
            f.write("2026-01-01\t30\t6\n")
        sessions, _ = parse_session_file(path)
        daily = daily_loads(sessions)
        self.assertEqual(daily[date(2026, 1, 1)], 160.0 + 180.0)


if __name__ == "__main__":
    unittest.main()
