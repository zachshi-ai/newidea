#!/usr/bin/env python3
"""Acceptance tests A1/A10 (parsing & honesty) for left-behind (漏带时刻)."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import left_behind as lb  # noqa: E402

HEADER = "\t".join(lb.REQUIRED_COLUMNS)


def row(**over):
    """一行合法事件，字段可覆盖。"""
    values = {
        "date": "2026-04-08", "trip_id": "T001", "trip_type": "business",
        "days": "3", "item": "手机充电头", "category": "electronics",
        "event": "left", "cost": "89", "weight_g": "", "notes": "",
    }
    values.update(over)
    return "\t".join(values[c] for c in lb.REQUIRED_COLUMNS)


def parse(body):
    return lb.parse_events(HEADER + "\n" + body)


class TestHeaderAndComments(unittest.TestCase):
    def test_missing_column_rejected(self):
        bad = HEADER.replace("\tweight_g", "")
        with self.assertRaises(lb.ParseError) as ctx:
            lb.parse_events(bad + "\n" + row())
        self.assertIn("weight_g", str(ctx.exception))

    def test_column_order_free(self):
        shuffled = "\t".join(["notes", "weight_g", "cost", "event", "category",
                              "item", "days", "trip_type", "trip_id", "date"])
        body = "\t".join(["备注", "", "25", "left", "misc", "折叠衣架",
                          "3", "business", "T001", "2026-04-08"])
        events = lb.parse_events(shuffled + "\n" + body)
        self.assertEqual(events[0].item, "折叠衣架")
        self.assertEqual(events[0].cost, 25.0)

    def test_comments_and_blank_lines_skipped(self):
        text = ("# 头部注释\n\n" + HEADER + "\n"
                + row() + "\n# 行中注释\n\n" + row(trip_id="T002") + "\n")
        self.assertEqual(len(lb.parse_events(text)), 2)


class TestBadRows(unittest.TestCase):
    def assert_bad(self, body, fragment):
        with self.assertRaises(lb.ParseError) as ctx:
            parse(body)
        self.assertIn(fragment, str(ctx.exception))

    def test_bad_event_enum(self):
        self.assert_bad(row(event="forgot"), "event")

    def test_days_must_be_positive_int(self):
        self.assert_bad(row(days="0"), "days")
        self.assert_bad(row(days="2.5"), "days")

    def test_bad_date(self):
        self.assert_bad(row(date="2026/04/08"), "date")

    def test_negative_cost_rejected(self):
        self.assert_bad(row(cost="-1"), "cost")

    def test_negative_weight_rejected(self):
        self.assert_bad(row(weight_g="-3"), "weight_g")

    def test_non_numeric_cost_rejected(self):
        self.assert_bad(row(cost="eighty"), "cost")

    def test_empty_key_fields_rejected(self):
        self.assert_bad(row(item=""), "item")
        self.assert_bad(row(category=""), "category")
        self.assert_bad(row(trip_id=""), "trip_id")

    def test_all_bad_rows_reported_at_once(self):
        body = row(cost="x") + "\n" + row(trip_id="T002", event="maybe")
        with self.assertRaises(lb.ParseError) as ctx:
            parse(body)
        message = str(ctx.exception)
        self.assertIn("第 2 行", message)
        self.assertIn("第 3 行", message)

    def test_lineno_counts_from_file_not_body(self):
        # 表头是第 1 行，第一条数据是第 2 行
        with self.assertRaises(lb.ParseError) as ctx:
            parse(row(days="九"))
        self.assertIn("第 2 行", str(ctx.exception))


class TestTripConsistency(unittest.TestCase):
    def test_same_trip_consistent_meta_ok(self):
        body = row() + "\n" + row(item="雨伞", event="ghost", cost="",
                                  weight_g="350")
        self.assertEqual(len(parse(body)), 2)

    def test_conflicting_days_rejected(self):
        body = row() + "\n" + row(item="雨伞", days="4")
        with self.assertRaises(lb.ParseError) as ctx:
            parse(body)
        self.assertIn("元数据", str(ctx.exception))

    def test_conflicting_type_rejected(self):
        body = row() + "\n" + row(item="雨伞", trip_type="leisure")
        with self.assertRaises(lb.ParseError) as ctx:
            parse(body)
        self.assertIn("元数据", str(ctx.exception))


class TestHonestyClauses_A10(unittest.TestCase):
    def test_empty_ledger_rejected(self):
        with self.assertRaises(lb.ParseError) as ctx:
            lb.parse_events("# 只有注释\n")
        self.assertIn("账本为空", str(ctx.exception))

    def test_header_only_is_empty_ledger(self):
        # 空账本（只有表头）合法：analyze 会拒绝它，pack 要靠它出第一张基线清单
        self.assertEqual(parse(""), [])

    def test_blank_cost_and_weight_are_none_not_zero(self):
        events = parse(row(cost="", weight_g=""))
        self.assertIsNone(events[0].cost)
        self.assertIsNone(events[0].weight_g)

    def test_ghost_without_weight_is_kept_and_flagged(self):
        events = parse(row(event="ghost", cost="", weight_g=""))
        self.assertEqual(len(events), 1)
        item, count, weight, unweighted = lb.ghost_cargo(events)[0]
        self.assertEqual((item, count, weight, unweighted), ("手机充电头", 1, 0.0, 1))


if __name__ == "__main__":
    unittest.main()
