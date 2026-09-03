# -*- coding: utf-8 -*-
"""A6 验收：EWMA 变体（Williams et al. 2017）。"""
import unittest
from datetime import date, timedelta

from redline import EWMA_A, EWMA_C, ewma_series


class TestEwma(unittest.TestCase):
    def test_lambda_constants(self):
        self.assertAlmostEqual(EWMA_A, 2.0 / 8.0)
        self.assertAlmostEqual(EWMA_C, 2.0 / 29.0)

    def test_hand_computed_acute_series(self):
        # 100 → 0 → 0：λ=0.25，初值=首日负荷
        d0 = date(2026, 1, 1)
        daily = {d0: 100.0, d0 + timedelta(days=1): 0.0,
                 d0 + timedelta(days=2): 0.0}
        series = ewma_series(daily, d0 + timedelta(days=2))
        self.assertAlmostEqual(series[d0][0], 100.0)
        self.assertAlmostEqual(series[d0 + timedelta(days=1)][0], 75.0)
        self.assertAlmostEqual(series[d0 + timedelta(days=2)][0], 56.25)

    def test_hand_computed_chronic_series(self):
        d0 = date(2026, 1, 1)
        daily = {d0: 100.0, d0 + timedelta(days=1): 0.0}
        series = ewma_series(daily, d0 + timedelta(days=1))
        expected = 100.0 * (1 - EWMA_C)          # λ·0 + (1-λ)·100
        self.assertAlmostEqual(series[d0 + timedelta(days=1)][1], expected)
        self.assertAlmostEqual(expected, 93.10344827586206, places=10)

    def test_series_extends_past_last_session(self):
        # 停训日也要迭代衰减：end_d 超出最后会话日，仍有条目
        d0 = date(2026, 1, 1)
        daily = {d0: 100.0}
        end = d0 + timedelta(days=5)
        series = ewma_series(daily, end)
        self.assertEqual(len(series), 6)
        # 慢性衰减慢于急性
        e5a, e5c = series[end]
        self.assertGreater(e5c, e5a)
        self.assertGreater(e5a, 0)

    def test_ewma_spikier_than_rolling(self):
        # 三周平稳 + 末日大爆发：EWMA 急性应远低于滚动急性（滚动被当日拉满）
        d0 = date(2026, 1, 1)
        daily = {d0 + timedelta(days=k): 100.0 for k in range(21)}
        boom_day = d0 + timedelta(days=21)
        daily[boom_day] = 1000.0
        series = ewma_series(daily, boom_day)
        ew_a, ew_c = series[boom_day]
        from redline import acute_at
        rolling_acute = acute_at(daily, boom_day)
        self.assertLess(ew_a, rolling_acute)      # EWMA 不被单日脉冲牵着走
        # 慢性只被撼动 λ×超额 ≈ 0.069×900 ≈ 62，仍贴着基线（基线 100）
        self.assertGreater(ew_c, 100.0)
        self.assertLess(ew_c, 200.0)

    def test_empty_daily_returns_empty(self):
        self.assertEqual(ewma_series({}, date(2026, 1, 1)), {})


if __name__ == "__main__":
    unittest.main()
