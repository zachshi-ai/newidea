#!/usr/bin/env python3
"""Acceptance tests A2/A3/A4 (trip ledger, blind spots, ghosts) for left-behind."""

import unittest
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import left_behind as lb  # noqa: E402


def ev(date_s, trip_id, item, category, kind, cost=None, weight=None,
       trip_type="business", days=3):
    """手工构造一条事件（绕过 TSV，直接测聚合层）。"""
    return lb.Event(lineno=0, date=date.fromisoformat(date_s), trip_id=trip_id,
                    trip_type=trip_type, days=days, item=item, category=category,
                    event=kind, cost=cost, weight_g=weight, notes="")


class TestAggregation_A2(unittest.TestCase):
    def test_trips_grouped_and_sorted_by_date(self):
        events = [
            ev("2026-04-01", "T002", "雨伞", "misc", "ghost"),
            ev("2026-03-01", "T001", "充电线", "electronics", "used"),
            ev("2026-03-01", "T001", "充电头", "electronics", "left", cost=89),
        ]
        trips = lb.aggregate_trips(events)
        self.assertEqual([t.trip_id for t in trips], ["T001", "T002"])
        self.assertEqual(len(trips[0].events), 2)
        self.assertEqual(trips[0].days, 3)

    def test_rates_exact(self):
        events = [
            ev("2026-03-01", "T001", "充电头", "electronics", "left", cost=89),
            ev("2026-04-01", "T002", "雨伞", "misc", "ghost", weight=350),
            ev("2026-05-01", "T003", "充电线", "electronics", "used"),
            ev("2026-06-01", "T004", "药", "health", "left", cost=12),
        ]
        trips = lb.aggregate_trips(events)
        domain = lb._domain_events(trips)
        left_n = sum(1 for e in domain if e.event == "left")
        ghost_n = sum(1 for e in domain if e.event == "ghost")
        self.assertAlmostEqual(left_n / len(trips), 0.5)
        self.assertAlmostEqual(ghost_n / len(trips), 0.25)

    def test_salvage_bill_ignores_unpriced_but_counts_them(self):
        events = [
            ev("2026-03-01", "T001", "充电头", "electronics", "left", cost=89),
            ev("2026-03-01", "T001", "名片", "misc", "left"),  # 未记价
            ev("2026-04-01", "T002", "药", "health", "left", cost=12.5),
        ]
        total, unpriced = lb.salvage_bill(events)
        self.assertAlmostEqual(total, 101.5)
        self.assertEqual(unpriced, 1)

    def test_select_trips_filters_by_type(self):
        events = [
            ev("2026-03-01", "T1", "A", "misc", "used", trip_type="business"),
            ev("2026-04-01", "T2", "B", "misc", "used", trip_type="leisure"),
        ]
        self.assertEqual(len(lb.select_trips(lb.aggregate_trips(events), "leisure")), 1)
        self.assertEqual(len(lb.select_trips(lb.aggregate_trips(events))), 2)


class TestBlindSpots_A3(unittest.TestCase):
    def test_two_forgots_make_a_pattern(self):
        events = [
            ev("2026-04-08", "T003", "手机充电头", "electronics", "left", cost=89),
            ev("2026-07-08", "T006", "手机充电头", "electronics", "left", cost=69),
            ev("2026-05-01", "T004", "泳镜", "sports", "left", cost=39),
        ]
        spots = lb.blind_spots(events)
        self.assertEqual(len(spots), 1)
        item, cat, count, cost, last_date, last_trip = spots[0]
        self.assertEqual(item, "手机充电头")
        self.assertEqual(cat, "electronics")
        self.assertEqual(count, 2)
        self.assertAlmostEqual(cost, 158.0)
        self.assertEqual(last_date, date(2026, 7, 8))
        self.assertEqual(last_trip, "T006")

    def test_single_forgot_is_not_a_blind_spot(self):
        events = [ev("2026-04-08", "T003", "泳镜", "sports", "left", cost=39)]
        self.assertEqual(lb.blind_spots(events), [])

    def test_ranked_by_count_then_cost(self):
        events = [
            ev("2026-01-01", "A1", "伞", "misc", "left", cost=1),
            ev("2026-02-01", "A2", "伞", "misc", "left", cost=1),
            ev("2026-03-01", "A3", "伞", "misc", "left", cost=1),
            ev("2026-01-01", "B1", "充电头", "electronics", "left", cost=200),
            ev("2026-02-01", "B2", "充电头", "electronics", "left", cost=200),
        ]
        spots = lb.blind_spots(events)
        self.assertEqual([row[0] for row in spots], ["伞", "充电头"])

    def test_unpriced_blind_spot_still_ranks(self):
        events = [
            ev("2026-01-01", "A1", "名片", "misc", "left"),
            ev("2026-02-01", "A2", "名片", "misc", "left"),
        ]
        spots = lb.blind_spots(events)
        self.assertEqual(spots[0][3], 0.0)  # 累计成本为 0，不装作没看见


class TestGhostCargo_A4(unittest.TestCase):
    def test_ranked_by_count_then_cumulative_weight(self):
        events = [
            ev("2026-01-01", "A1", "雨伞", "misc", "ghost", weight=350),
            ev("2026-02-01", "A2", "雨伞", "misc", "ghost", weight=350),
            ev("2026-03-01", "A3", "雨伞", "misc", "ghost", weight=350),
            ev("2026-04-01", "B1", "健身裤", "clothes", "ghost", weight=400),
            ev("2026-05-01", "B2", "健身裤", "clothes", "ghost", weight=400),
        ]
        cargo = lb.ghost_cargo(events)
        self.assertEqual([row[0] for row in cargo], ["雨伞", "健身裤"])
        self.assertAlmostEqual(cargo[0][2], 1050.0)
        self.assertAlmostEqual(cargo[1][2], 800.0)

    def test_no_ghosts_returns_empty_not_crash(self):
        events = [ev("2026-01-01", "A1", "充电线", "electronics", "used")]
        self.assertEqual(lb.ghost_cargo(events), [])

    def test_unweighted_counted_not_silently_dropped(self):
        events = [
            ev("2026-01-01", "A1", "会议资料", "misc", "ghost", weight=200),
            ev("2026-02-01", "A2", "会议资料", "misc", "ghost"),
        ]
        item, count, weight, unweighted = lb.ghost_cargo(events)[0]
        self.assertEqual((count, unweighted), (2, 1))
        self.assertAlmostEqual(weight, 200.0)  # 不猜重量，只累计记了的


class TestProfilesAndStaples(unittest.TestCase):
    def test_profiles_counts_per_type(self):
        events = [
            ev("2026-03-01", "T1", "A", "misc", "left", trip_type="business"),
            ev("2026-03-01", "T1", "B", "misc", "used", trip_type="business"),
            ev("2026-04-01", "T2", "C", "misc", "ghost", trip_type="leisure"),
        ]
        profiles = lb.profiles(events)
        self.assertEqual(profiles["business"]["trips"], 1)
        self.assertEqual(profiles["business"]["left"], 1)
        self.assertEqual(profiles["leisure"]["ghost"], 1)

    def test_staples_require_min_used_and_type_match(self):
        events = [
            ev("2026-03-01", "T1", "充电线", "electronics", "used"),
            ev("2026-04-01", "T2", "充电线", "electronics", "used"),
            ev("2026-05-01", "T3", "充电线", "electronics", "used"),
            ev("2026-05-01", "T3", "防晒", "toiletries", "used", trip_type="leisure"),
        ]
        staples = lb.staples(events, "business")
        self.assertEqual(staples, [("充电线", 3, 3)])
        self.assertEqual(lb.staples(events, "leisure"), [])  # 1 次，不到 2 次线


if __name__ == "__main__":
    unittest.main()
