#!/usr/bin/env python3
"""Acceptance tests A5 (convergence trend) for left-behind (漏带时刻)."""

import unittest
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import left_behind as lb  # noqa: E402


def ev(date_s, trip_id, lefts=0):
    """一次行程 = 一条 left 事件（或 used 占位行）。"""
    kind = "left" if lefts else "used"
    events = []
    for i in range(max(1, lefts)):
        events.append(lb.Event(
            lineno=0, date=date.fromisoformat(date_s), trip_id=trip_id,
            trip_type="business", days=3, item="物%s" % i, category="misc",
            event=kind if i == 0 else "left",
            cost=1.0 if kind == "left" else None,
            weight_g=None, notes=""))
    return events


def ledger(trip_specs):
    """trip_specs: [(date, trip_id, left_n), ...]（无需按日期有序）。"""
    events = []
    for date_s, trip_id, left_n in trip_specs:
        events.extend(ev(date_s, trip_id, left_n))
    return lb.aggregate_trips(events)


class TestConvergence_A5(unittest.TestCase):
    def test_improving(self):
        trips = ledger([
            ("2026-03-01", "T1", 2), ("2026-03-10", "T2", 1),
            ("2026-04-01", "T3", 2), ("2026-04-10", "T4", 1),
            ("2026-05-01", "T5", 0), ("2026-05-10", "T6", 1),
        ])
        conv = lb.convergence(trips)
        self.assertEqual(conv["direction"], "improving")
        self.assertAlmostEqual(conv["before"], 5 / 3)
        self.assertAlmostEqual(conv["after"], 2 / 3)
        self.assertEqual((conv["before_n"], conv["after_n"]), (3, 3))

    def test_worsening(self):
        trips = ledger([
            ("2026-03-01", "T1", 0), ("2026-03-10", "T2", 1),
            ("2026-04-01", "T3", 0), ("2026-04-10", "T4", 2),
            ("2026-05-01", "T5", 2), ("2026-05-10", "T6", 2),
        ])
        conv = lb.convergence(trips)
        self.assertEqual(conv["direction"], "worsening")
        self.assertAlmostEqual(conv["after"], 2.0)

    def test_flat(self):
        trips = ledger([
            ("2026-03-01", "T1", 1), ("2026-03-10", "T2", 1),
            ("2026-04-01", "T3", 1), ("2026-04-10", "T4", 1),
        ])
        conv = lb.convergence(trips)
        self.assertEqual(conv["direction"], "flat")

    def test_refuses_fewer_than_four_trips(self):
        trips = ledger([
            ("2026-03-01", "T1", 1), ("2026-03-10", "T2", 0),
            ("2026-04-01", "T3", 0),
        ])
        self.assertIsNone(lb.convergence(trips))

    def test_minimum_four_trips_passes(self):
        trips = ledger([
            ("2026-03-01", "T1", 1), ("2026-03-10", "T2", 1),
            ("2026-04-01", "T3", 0), ("2026-04-10", "T4", 0),
        ])
        conv = lb.convergence(trips)
        self.assertIsNotNone(conv)
        self.assertEqual(conv["direction"], "improving")

    def test_odd_count_median_trip_sits_out(self):
        # 5 次行程 → 前 2 后 2；中位行程漏 99 件也不影响趋势
        trips = ledger([
            ("2026-03-01", "T1", 2), ("2026-03-10", "T2", 2),
            ("2026-04-01", "T3", 99),
            ("2026-04-10", "T4", 0), ("2026-05-01", "T5", 0),
        ])
        conv = lb.convergence(trips)
        self.assertEqual((conv["before_n"], conv["after_n"]), (2, 2))
        self.assertAlmostEqual(conv["before"], 2.0)
        self.assertAlmostEqual(conv["after"], 0.0)

    def test_unordered_input_sorted_by_date_first(self):
        trips = ledger([
            ("2026-05-01", "T5", 0), ("2026-03-01", "T1", 2),
            ("2026-04-10", "T4", 0), ("2026-03-10", "T2", 2),
        ])
        conv = lb.convergence(trips)
        self.assertEqual(conv["direction"], "improving")

    def test_same_day_trips_tie_broken_by_trip_id(self):
        trips = ledger([
            ("2026-03-01", "T1", 0), ("2026-03-01", "T2", 2),
            ("2026-04-01", "T3", 0), ("2026-04-01", "T4", 0),
        ])
        conv = lb.convergence(trips)
        self.assertEqual(conv["direction"], "improving")


if __name__ == "__main__":
    unittest.main()
