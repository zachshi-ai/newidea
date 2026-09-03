# -*- coding: utf-8 -*-
"""A9 验收：计划模拟与甜区余额（headroom 闭式解）。"""
import os
import tempfile
import unittest
from datetime import date, timedelta

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from redline import (LogError, ZONE_HIGH, build_plan, daily_loads,
                     headroom_exact, parse_plan_sessions, acute_at,
                     window_sum)


def sess(d, load, rpe=5):
    return {"date": d, "activity": "跑", "minutes": load / rpe, "rpe": rpe,
            "notes": "", "load": float(load)}


BASE = date(2026, 1, 1)


class TestHeadroom(unittest.TestCase):
    def test_exact_closed_form_steady_state(self):
        # 28 天稳定 100/日：S28=2800, A=700
        daily = {BASE + timedelta(days=k): 100.0 for k in range(28)}
        d = BASE + timedelta(days=27)
        h = headroom_exact(daily, d)
        self.assertAlmostEqual(h, (ZONE_HIGH * 2800 - 4 * 700) / (4 - ZONE_HIGH),
                               places=9)
        # 代回验证：加上 headroom 后 ACWR 恰好 = 1.3
        daily2 = dict(daily)
        daily2[d] = daily2.get(d, 0.0) + h
        a = acute_at(daily2, d)
        c = window_sum(daily2, d, 28) / 4
        self.assertAlmostEqual(a / c, ZONE_HIGH, places=9)

    def test_headroom_zero_when_already_over(self):
        # 单日爆拉：急性远超甜区，余额必须是 0（不许建议负训练）
        daily = {BASE + timedelta(days=27): 100.0}
        h = headroom_exact(daily, BASE + timedelta(days=27))
        self.assertEqual(h, 0.0)

    def test_headroom_positive_but_limited_when_amber(self):
        # 稳态后多加一点：仍有余额但变小
        daily = {BASE + timedelta(days=k): 100.0 for k in range(28)}
        d = BASE + timedelta(days=27)
        full = headroom_exact(daily, d)
        daily[d] += 200.0
        less = headroom_exact(daily, d)
        self.assertLess(less, full)
        self.assertGreater(less, 0)


class TestParsePlanSessions(unittest.TestCase):
    def test_valid_spec(self):
        out = parse_plan_sessions(["2026-03-01,60,7,间歇课"])
        self.assertEqual(out[0]["date"], date(2026, 3, 1))
        self.assertEqual(out[0]["load"], 420.0)
        self.assertEqual(out[0]["activity"], "间歇课")

    def test_default_activity(self):
        out = parse_plan_sessions(["2026-03-01,60,7"])
        self.assertEqual(out[0]["activity"], "计划")

    def test_missing_fields_raise(self):
        with self.assertRaises(LogError):
            parse_plan_sessions(["2026-03-01,60"])

    def test_bad_values_raise(self):
        with self.assertRaises(LogError):
            parse_plan_sessions(["2026-03-01,60,11"])     # RPE 超过 10
        with self.assertRaises(LogError):
            parse_plan_sessions(["2026-03-01,0,5"])       # 0 分钟
        with self.assertRaises(ValueError):
            parse_plan_sessions(["垃圾,60,5"])            # 日期直接报错


class TestBuildPlan(unittest.TestCase):
    def log_28_steady(self, per_day=100.0):
        return {BASE + timedelta(days=k): per_day for k in range(28)}

    def test_red_plan_flagged(self):
        daily = self.log_28_steady()
        # 末日再砸 700 负荷：acute=1400, chronic=875 → 1.6 红
        planned = [{"date": BASE + timedelta(days=27), "activity": "爆冲",
                    "minutes": 100, "rpe": 7, "load": 700.0}]
        plan = build_plan(daily, BASE, planned)
        self.assertEqual(plan["rows"][-1]["zone"], "red")

    def test_green_plan_stays_green(self):
        daily = self.log_28_steady()
        # 末日 100：acute=800, chronic=(2800+100)/4=725 → 1.10 绿
        planned = [{"date": BASE + timedelta(days=27), "activity": "轻松跑",
                    "minutes": 50, "rpe": 2, "load": 100.0}]
        plan = build_plan(daily, BASE, planned)
        self.assertAlmostEqual(plan["rows"][-1]["acwr"], 800.0 / 725.0, places=9)
        self.assertEqual(plan["rows"][-1]["zone"], "green")

    def test_uncalibrated_plan_days_marked(self):
        daily = {BASE + timedelta(days=k): 100.0 for k in range(5)}
        planned = [{"date": BASE + timedelta(days=5), "activity": "跑",
                    "minutes": 60, "rpe": 5, "load": 300.0}]
        plan = build_plan(daily, BASE, planned)
        self.assertFalse(plan["rows"][-1]["calibrated"])
        self.assertEqual(plan["rows"][-1]["zone"], "gray")

    def test_frozen_plan_days_marked(self):
        # 伤停归队后 7 天内计划：判据冻结
        sessions = [sess(BASE + timedelta(days=k), 700) for k in range(28)]
        ret = BASE + timedelta(days=48)          # 空窗 20 天后归队
        sessions.append(sess(ret, 200))
        daily = daily_loads(sessions)
        layoffs = [(BASE + timedelta(days=27), ret)]
        planned = [{"date": ret + timedelta(days=2), "activity": "跑",
                    "minutes": 40, "rpe": 4, "load": 160.0}]
        plan = build_plan(daily, BASE, planned, layoffs=layoffs)
        self.assertTrue(plan["rows"][-1]["frozen"])
        self.assertEqual(plan["rows"][-1]["zone"], "gray")


if __name__ == "__main__":
    unittest.main()
