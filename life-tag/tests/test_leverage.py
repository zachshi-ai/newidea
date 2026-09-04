#!/usr/bin/env python3
"""Acceptance tests for life-tag (生命价签) — leverage ranking."""

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


class TestLeverage(unittest.TestCase):
    def setUp(self):
        self.p = lt.validate_profile(METRO)
        self.base = lt.economics(self.p)["true"]  # ≈ 55.66

    def _deltas(self, actions):
        moves = lt.leverage_moves(self.p, actions)
        return {m["label"]: m for m in moves}

    def test_raise(self):
        moves = lt.leverage_moves(self.p, {"raise_pct": 10.0})
        self.assertEqual(len(moves), 1)
        # 真实时薪 = 16830−1000 ÷ 256.9 = 61.62
        self.assertAlmostEqual(moves[0]["true"], 15830.0 / 256.9)
        self.assertAlmostEqual(moves[0]["delta"], 15830.0 / 256.9 - self.base)

    def test_negative_raise_hurts(self):
        moves = lt.leverage_moves(self.p, {"raise_pct": -10.0})
        self.assertLess(moves[0]["delta"], 0)
        self.assertAlmostEqual(moves[0]["true"], 12770.0 / 256.9)

    def test_commute_to_scales_cost_proportionally(self):
        moves = lt.leverage_moves(self.p, {"commute_to": 15.0})
        # 通勤开销随距离同比缩水：300 × 15/55 = 81.82
        self.assertAlmostEqual(moves[0]["true"],
                               (15300 - 300 * 15.0 / 55.0 - 700) / 228.9)

    def test_commute_to_zero_keeps_fixed_cost(self):
        # 通勤为 0 时开销不可再按比例摊（除零保护），只保留原通勤开销中的固定部分？
        # 设计决策：单程 0 分钟 → 通勤开销归零（不出门=不花钱），
        # 但画像里的其他开销不动。
        moves = lt.leverage_moves(self.p, {"commute_to": 0.0})
        self.assertAlmostEqual(moves[0]["true"], (15300 - 0 - 700) / 218.4)

    def test_remote_two_days(self):
        moves = lt.leverage_moves(self.p, {"remote_days": 2.0})
        # 远程 2/5：通勤时间 38.5→23.1，开销 300→180
        self.assertAlmostEqual(moves[0]["true"], (15300 - 180 - 700) / 241.5)

    def test_remote_full_week(self):
        moves = lt.leverage_moves(self.p, {"remote_days": 5.0})
        self.assertAlmostEqual(moves[0]["true"], (15300 - 0 - 700) / 218.4)

    def test_remote_days_out_of_range(self):
        for bad in (-1.0, 6.0):
            with self.assertRaises(lt.ProfileError):
                lt.leverage_moves(self.p, {"remote_days": bad})

    def test_recovery_to(self):
        moves = lt.leverage_moves(self.p, {"recovery_to": 0.2})
        self.assertAlmostEqual(moves[0]["true"], 14300.0 / 240.1)

    def test_cut_costs(self):
        moves = lt.leverage_moves(self.p, {"cut_costs": 200.0})
        self.assertAlmostEqual(moves[0]["true"], 14500.0 / 256.9)

    def test_cut_costs_clamped_at_zero(self):
        # 砍超过上限：extra 归零，通勤开销 300 不受 cut_costs 影响
        moves = lt.leverage_moves(self.p, {"cut_costs": 99999.0})
        self.assertAlmostEqual(moves[0]["true"], 15000.0 / 256.9)

    def test_ranking_ground_truth(self):
        # 对这个画像：搬近 > 涨薪 10% > 远程 2 天 > 降恢复 > 砍开销
        moves = lt.leverage_moves(self.p, {
            "commute_to": 15.0, "raise_pct": 10.0, "remote_days": 2.0,
            "recovery_to": 0.2, "cut_costs": 200.0,
        })
        self.assertEqual(len(moves), 5)
        values = [m["true"] for m in moves]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertIn("通勤", moves[0]["label"])
        self.assertAlmostEqual(moves[0]["delta"], 7.76, places=2)
        self.assertAlmostEqual(moves[1]["delta"], 5.96, places=2)

    def test_best_move_flagged_by_delta_not_label(self):
        # 低通勤画像下换涨薪才是第一名：排行跟着数值走，不跟着标签走
        near = lt.validate_profile({"gross_monthly": 18000.0, "tax_rate": 0.15,
                                    "commute_min": 5.0, "recovery_ratio": 0.3})
        moves = lt.leverage_moves(near, {
            "commute_to": 1.0, "raise_pct": 50.0, "cut_costs": 100.0})
        self.assertIn("涨薪", moves[0]["label"])

    def test_empty_actions_returns_empty(self):
        self.assertEqual(lt.leverage_moves(self.p, {}), [])

    def test_deltas_relative_to_base(self):
        moves = lt.leverage_moves(self.p, {"raise_pct": 10.0})
        self.assertAlmostEqual(moves[0]["delta"],
                               moves[0]["true"] - self.base, places=9)
        self.assertAlmostEqual(moves[0]["delta_pct"],
                               (moves[0]["true"] - self.base) / self.base * 100,
                               places=9)

    def test_actions_measured_independently(self):
        # 涨薪 +10% 的效果不叠加其他动作：单独测 vs 与砍开销同测，
        # 涨薪那一条的 true 值应完全一致
        alone = lt.leverage_moves(self.p, {"raise_pct": 10.0})
        both = lt.leverage_moves(self.p, {"raise_pct": 10.0,
                                          "cut_costs": 200.0})
        self.assertAlmostEqual(alone[0]["true"],
                               [m for m in both
                                if "涨薪" in m["label"]][0]["true"], places=9)


if __name__ == "__main__":
    unittest.main()
