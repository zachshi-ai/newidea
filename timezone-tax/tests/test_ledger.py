#!/usr/bin/env python3
"""时区税验收 A7 — 账本：追加、汇总、校验一次报全。"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import timezone_tax as tzt  # noqa: E402
from datetime import datetime  # noqa: E402


class TestLedger(unittest.TestCase):
    def test_append_and_summarize(self):
        ledger = tzt.empty_ledger()
        tzt.append_meeting(ledger, datetime(2026, 9, 7, 15, 0),
                           {"A": 1.5, "B": 0.0}, note="周会")
        tzt.append_meeting(ledger, datetime(2026, 9, 14, 15, 0),
                           {"A": 1.5, "B": 1.0})
        self.assertEqual(len(ledger["meetings"]), 2)
        self.assertEqual(ledger["meetings"][0]["utc"], "2026-09-07T15:00")
        self.assertEqual(ledger["meetings"][0]["note"], "周会")
        totals = tzt.summarize_ledger(ledger)
        self.assertAlmostEqual(totals["A"], 3.0)
        self.assertAlmostEqual(totals["B"], 1.0)

    def test_summarize_with_team_adds_zero_members(self):
        ledger = tzt.empty_ledger()
        tzt.append_meeting(ledger, datetime(2026, 9, 7, 15, 0), {"A": 1.0})
        team = {"members": [{"name": "A", "offset_min": 0},
                            {"name": "B", "offset_min": 60}]}
        totals = tzt.summarize_ledger(ledger, team=team)
        self.assertEqual(totals, {"A": 1.0, "B": 0.0})

    def test_roundtrip_preserves_totals(self):
        ledger = tzt.empty_ledger()
        tzt.append_meeting(ledger, datetime(2026, 9, 7, 15, 0),
                           {"A": 1.5, "B": 3.0})
        revived = json.loads(json.dumps(ledger))
        tzt.validate_ledger(revived)
        self.assertAlmostEqual(tzt.summarize_ledger(revived)["B"], 3.0)

    def test_validate_rejects_bad_shapes(self):
        with self.assertRaises(tzt.TaxError) as ctx:
            tzt.validate_ledger({"meetings": "all"})
        self.assertIn("meetings", str(ctx.exception))

        with self.assertRaises(tzt.TaxError) as ctx:
            tzt.validate_ledger({"meetings": [{"utc": "2026-09-07T15:00"}]})
        self.assertIn("bills", str(ctx.exception))

        with self.assertRaises(tzt.TaxError) as ctx:
            tzt.validate_ledger({"meetings": [
                {"utc": "2026-09-07T15:00", "bills": {"A": "贵"}}]})
        self.assertIn("数字", str(ctx.exception))

    def test_validate_reports_bad_utc_with_index(self):
        with self.assertRaises(tzt.TaxError) as ctx:
            tzt.validate_ledger({"meetings": [
                {"utc": "上周一", "bills": {"A": 1.0}}]})
        self.assertIn("第 1 条", str(ctx.exception))

    def test_validate_team_aggregates_problems(self):
        team = {"members": [
            {"name": "x", "offset_min": 99999},
            {"name": "x", "offset_min": 0},
            {"name": "y", "offset_min": 0, "dst": [{"from": "13-01",
                                                    "to": "02-01",
                                                    "offset_min": 60}]},
        ], "grid_min": 7.5}
        with self.assertRaises(tzt.TaxError) as ctx:
            tzt.validate_team(team)
        message = str(ctx.exception)
        self.assertIn("offset_min", message)
        self.assertIn("重复", message)
        self.assertIn("MM-DD", message)
        self.assertIn("grid_min", message)

    def test_load_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nope.json")
            with self.assertRaises(tzt.TaxError):
                tzt.load_ledger(path)
            with self.assertRaises(tzt.TaxError):
                tzt.load_team(path)


if __name__ == "__main__":
    unittest.main()
