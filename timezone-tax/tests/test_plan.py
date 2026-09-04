#!/usr/bin/env python3
"""时区税验收 A5/A6 — 候选槽枚举、补偿式轮换、DST 自适应、无解判定。"""

import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import timezone_tax as tzt  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "examples"))
import build_examples  # noqa: E402

SF = {"name": "Alice · 旧金山", "offset_min": -480,
      "dst": [{"from": "03-08", "to": "11-01", "offset_min": -420}]}
BLR = {"name": "Chitra · 班加罗尔", "offset_min": 330}


class TestFeasibleSlots(unittest.TestCase):
    def test_global_team_feasible_band(self):
        # 2026-09-07：可行带只有 UTC 14:00–15:30（上海 22:00–23:30 / 旧金山 07:00–08:30）
        team = build_examples.build_team_global()
        slots = tzt.feasible_slots(team, date(2026, 9, 7))
        self.assertEqual([minute for minute, _ in slots],
                         [840, 870, 900, 930])

    def test_grid_step_is_honored(self):
        team = build_examples.build_team_global()
        team["grid_min"] = 60
        slots = tzt.feasible_slots(team, date(2026, 9, 7))
        self.assertEqual([minute for minute, _ in slots], [840, 900])

    def test_impossible_team_has_no_slots(self):
        team = build_examples.build_team_impossible()
        self.assertEqual(tzt.feasible_slots(team, date(2026, 9, 7)), [])


class TestPlanGlobal(unittest.TestCase):
    """四地团队：可行带内税单恒为 5.5（深夜+清晨+傍晚各一人），结构性失衡。"""

    def setUp(self):
        self.team = build_examples.build_team_global()

    def test_structural_verdict(self):
        result = tzt.plan_rotation(self.team, date(2026, 9, 7), 8)
        self.assertTrue(result["structural"])
        self.assertEqual(result["infeasible_weeks"], [])
        level, reasons = tzt.plan_verdict(result, self.team)
        self.assertEqual(level, "alarm")
        self.assertIn("结构性失衡", reasons[0])
        self.assertIn("轮换无效", reasons[0])

    def test_all_weeks_pick_earliest_slot(self):
        result = tzt.plan_rotation(self.team, date(2026, 9, 7), 8)
        for entry in result["entries"]:
            self.assertEqual(entry["bill"]["utc"][11:16], "14:00")

    def test_dst_shifts_the_meeting_not_the_bill(self):
        # 美国冬令时 2026-11-01 生效：第 9 周起会议自动挪到 15:00 UTC，税单仍是 5.5
        result = tzt.plan_rotation(self.team, date(2026, 9, 7), 12)
        self.assertEqual(result["entries"][7]["bill"]["utc"],
                         "2026-10-26 14:00")
        self.assertEqual(result["entries"][8]["bill"]["utc"],
                         "2026-11-02 15:00")
        self.assertAlmostEqual(result["entries"][8]["bill"]["total"], 5.5)

    def test_end_of_plan_cum(self):
        result = tzt.plan_rotation(self.team, date(2026, 9, 7), 12)
        self.assertEqual(result["cum"], {
            "Alice · 旧金山": 18.0, "Bruno · 柏林": 0.0,
            "Chitra · 班加罗尔": 12.0, "Dawei · 上海": 36.0})

    def test_deterministic(self):
        a = tzt.plan_rotation(self.team, date(2026, 9, 7), 6)
        b = tzt.plan_rotation(self.team, date(2026, 9, 7), 6)
        self.assertEqual([e["bill"]["utc"] for e in a["entries"]],
                         [e["bill"]["utc"] for e in b["entries"]])
        self.assertEqual(a["cum"], b["cum"])

    def test_single_week_is_not_called_structural(self):
        result = tzt.plan_rotation(self.team, date(2026, 9, 7), 1)
        self.assertFalse(result["structural"])


class TestPlanSeasonal(unittest.TestCase):
    """旧金山+班加罗尔二人组：美国冬令时把黄金时段让给 SF，
    缴税人集合随季节变化——轮换判定从结构性变成生效。"""

    def setUp(self):
        self.team = {"name": "Pair", "members": [dict(SF), dict(BLR)]}

    def test_signature_changes_across_dst(self):
        result = tzt.plan_rotation(self.team, date(2026, 10, 5), 10)
        slots = [e["bill"]["utc"][11:16] for e in result["entries"]]
        # 第 1–4 周（夏令时）：16:00 UTC，SF 黄金、BLR 傍晚 1 点
        self.assertEqual(slots[:4], ["16:00"] * 4)
        # 第 5 周起（冬令时）：15:00 UTC，SF 清晨 1.5、BLR 傍晚 1 点
        self.assertEqual(slots[4:], ["15:00"] * 6)
        self.assertFalse(result["structural"])
        self.assertEqual(len(result["signatures"]), 2)

    def test_verdict_reports_rotation(self):
        result = tzt.plan_rotation(self.team, date(2026, 10, 5), 10)
        level, reasons = tzt.plan_verdict(result, self.team)
        self.assertEqual(level, "ok")
        self.assertIn("轮换生效", reasons[0])


class TestPlanImpossible(unittest.TestCase):
    def test_all_weeks_infeasible(self):
        team = build_examples.build_team_impossible()
        result = tzt.plan_rotation(team, date(2026, 9, 7), 3)
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["infeasible_weeks"], [1, 2, 3])
        level, reasons = tzt.plan_verdict(result, team)
        self.assertEqual(level, "alarm")
        self.assertIn("无解", reasons[0])


class TestChooseSlot(unittest.TestCase):
    """补偿式选择：注入候选槽，钉死 (最大累计 → 总税 → 更早) 的字典序。"""

    @staticmethod
    def fake_bill(utc, pairs):
        return {
            "utc": utc, "total": sum(t for _, t in pairs),
            "max_payer": max(pairs, key=lambda p: p[1])[0] if pairs else None,
            "feasible": True,
            "rows": [{"name": n, "tax": t, "local": "周一 08:00",
                      "band": "early", "feasible": True, "reason": ""}
                     for n, t in pairs],
        }

    def slots(self, *bills):
        return [(int(b["utc"][11:13]) * 60 + int(b["utc"][14:16]), b)
                for b in bills]

    def test_tie_breaks_by_history_then_time(self):
        s1 = self.fake_bill("2026-09-07 08:00", [("A", 1.5), ("B", 0.0)])
        s2 = self.fake_bill("2026-09-07 16:30", [("A", 0.0), ("B", 1.5)])
        team = {"members": [{"name": "A", "offset_min": 0},
                            {"name": "B", "offset_min": -300}]}
        day = date(2026, 9, 7)
        slots = self.slots(s1, s2)
        # 白纸：并列时取更早的 S1
        self.assertEqual(tzt.choose_slot(team, {}, day, slots), s1)
        # A 已缴 10：补偿规则把会议推给 S2，让 B 开始缴
        self.assertEqual(tzt.choose_slot(team, {"A": 10.0, "B": 0.0}, day,
                                         slots), s2)
        # B 已缴 10：维持 S1
        self.assertEqual(tzt.choose_slot(team, {"A": 0.0, "B": 10.0}, day,
                                         slots), s1)

    def test_max_cum_beats_total(self):
        # max_after 字典序在前：总税低但制造新最惨的槽反而落选
        early = self.fake_bill("2026-09-07 10:00", [("A", 2.0)])
        shared = self.fake_bill("2026-09-07 11:00", [("A", 1.0), ("B", 1.0)])
        team = {"members": [{"name": "A", "offset_min": 0},
                            {"name": "B", "offset_min": 0}]}
        self.assertEqual(
            tzt.choose_slot(team, {}, date(2026, 9, 7),
                            self.slots(early, shared)), shared)

    def test_equal_max_equal_total_picks_earlier(self):
        x = self.fake_bill("2026-09-07 10:00", [("A", 2.0)])
        y = self.fake_bill("2026-09-07 11:00", [("B", 2.0)])
        team = {"members": [{"name": "A", "offset_min": 0},
                            {"name": "B", "offset_min": 0}]}
        self.assertEqual(
            tzt.choose_slot(team, {}, date(2026, 9, 7),
                            self.slots(y, x)), x)

    def test_no_slots_returns_none(self):
        team = {"members": [{"name": "A", "offset_min": 0}]}
        self.assertIsNone(tzt.choose_slot(team, {}, date(2026, 9, 7), []))


class TestSimulate(unittest.TestCase):
    def setUp(self):
        self.team = build_examples.build_team_global()
        self.result = tzt.simulate_fixed(self.team, 900, date(2026, 9, 7), 52)

    def test_halfyear_ground_truth(self):
        self.assertEqual(self.result["cum"], {
            "Alice · 旧金山": 78.0, "Bruno · 柏林": 0.0,
            "Chitra · 班加罗尔": 52.0, "Dawei · 上海": 156.0})
        self.assertEqual(self.result["infeasible_weeks"], [])
        self.assertEqual(len(self.result["entries"]), 52)

    def test_dst_segments_compressed(self):
        segments = tzt._member_local_segments(self.result["entries"],
                                              "Alice · 旧金山")
        self.assertEqual(segments, [["08:00", 1, 8], ["07:00", 9, 26],
                                    ["08:00", 27, 52]])

    def test_infeasible_fixed_slot(self):
        # 16:00 UTC 恒把上海推进 00:00：52 周全部不可行
        result = tzt.simulate_fixed(self.team, 960, date(2026, 9, 7), 3)
        self.assertEqual(result["infeasible_weeks"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
