#!/usr/bin/env python3
"""Acceptance tests for 里程错觉 · Odometer Illusion.

Every acceptance criterion in README.md maps to a test class here.
Synthetic ledgers are written to a temp dir; the demo reports are the
dogfood and are byte-checked against the delivered CLI.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import odometer_illusion as oi  # noqa: E402

CLI = ROOT / "odometer_illusion.py"
EXAMPLES = ROOT / "examples"
AS_OF = date(2025, 12, 1)


def write_ledger(tmp, car_rows, service_rows,
                 car_name="car.csv", service_name="service.csv"):
    car_path = os.path.join(tmp, car_name)
    with open(car_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(car_rows) + "\n")
    service_path = os.path.join(tmp, service_name)
    with open(service_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(service_rows) + "\n")
    return car_path, service_path


def run_cli(argv):
    result = subprocess.run(
        [sys.executable, str(CLI)] + argv, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


CAR = ["name,bought_date,bought_km", "TestCar,2022-03-15,0"]


class ParserTests(unittest.TestCase):
    tmp = None

    def setUp(self):
        if self.tmp is None:
            self.tmp = tempfile.mkdtemp()
        self.car, _ = write_ledger(
            self.tmp, CAR,
            ["date,km,item", "2025-04-13,19200,engine_oil"])

    def test_basic_english_headers(self):
        car = oi.parse_car(self.car)
        self.assertEqual(car["name"], "TestCar")
        self.assertEqual(car["bought_date"], date(2022, 3, 15))
        self.assertEqual(car["bought_km"], 0)

    def test_chinese_headers_and_aliases(self):
        path, _ = write_ledger(
            self.tmp,
            ["车名,购入日期,购入里程", "小白,2022年3月15日,0"],
            ["日期,里程,项目", "2025-04-13,19200,机油"],
            "cn.csv", "cn-svc.csv")
        car = oi.parse_car(path)
        self.assertEqual(car["name"], "小白")
        events = oi.parse_service(_)
        self.assertEqual(events[0]["item"], "engine_oil")
        self.assertEqual(events[0]["km"], 19200)

    def test_bom_and_blank_lines_tolerated(self):
        _, path = write_ledger(
            self.tmp, CAR, ["date,km,item", "", "2025-04-13,19200,engine_oil", ""],
            "bom.csv", "bom-svc.csv")
        events = oi.parse_service(path)
        self.assertEqual(len(events), 1)

    def test_date_formats(self):
        for text, expected in [
            ("2025-12-01", date(2025, 12, 1)),
            ("2025/12/1", date(2025, 12, 1)),
            ("2025.12.01", date(2025, 12, 1)),
            ("2025年12月1日", date(2025, 12, 1)),
            ("20251201", date(2025, 12, 1)),
        ]:
            self.assertEqual(oi.parse_date(text), expected, text)

    def test_bad_date_reports_value(self):
        with self.assertRaises(oi.ParseError) as ctx:
            oi.parse_date("soon")
        self.assertIn("soon", str(ctx.exception))

    def test_service_needs_header(self):
        _, path = write_ledger(self.tmp, CAR, ["2025-04-13,19200,engine_oil"], "nohdr.csv", "nohdr-svc.csv")
        with self.assertRaises(oi.ParseError) as ctx:
            oi.parse_service(path)
        self.assertIn("no header row", str(ctx.exception))

    def test_car_without_row_rejected(self):
        path, _ = write_ledger(
            self.tmp, ["name,bought_date,bought_km"], ["date,km,item"], "empty-car.csv")
        with self.assertRaises(oi.ParseError) as ctx:
            oi.parse_car(path)
        self.assertIn("no car row", str(ctx.exception))

    def test_unknown_item_is_kept_not_dropped(self):
        _, path = write_ledger(
            self.tmp, CAR,
            ["date,km,item", "2025-04-13,19200,雨刮", "2025-04-13,19200,神秘液体"])
        events = oi.parse_service(path)
        self.assertEqual(events[0]["item"], "wipers")
        self.assertIsNone(events[1]["item"])


class ClockTests(unittest.TestCase):
    def state(self, events, km_now, periods=None, as_of=AS_OF):
        car = {"name": "T", "bought_date": date(2022, 3, 15), "bought_km": 0}
        return oi.compute_state(car, events, periods or {}, as_of, km_now)

    def item(self, state, key):
        return [it for it in state["items"] if it["item"] == key][0]

    def test_progress_is_max_of_both_clocks(self):
        evs = [{"date": date(2025, 4, 13), "km": 19200, "item": "engine_oil",
                "raw_item": "engine_oil", "cost": None, "note": "", "row": 2}]
        oil = self.item(self.state(evs, 21400), "engine_oil")
        self.assertAlmostEqual(oil["mileage_progress"], (21400 - 19200) / 5000.0)
        self.assertAlmostEqual(oil["calendar_progress"], 232 / 180.0)
        self.assertAlmostEqual(oil["progress"], max(232 / 180.0, 2200 / 5000.0))
        self.assertEqual(oil["binding"], "calendar")

    def test_calendar_only_item_has_no_mileage_clock(self):
        evs = [{"date": date(2024, 6, 20), "km": 16700, "item": "wipers",
                "raw_item": "wipers", "cost": None, "note": "", "row": 2}]
        wipers = self.item(self.state(evs, 21400), "wipers")
        self.assertIsNone(wipers["mileage_progress"])
        self.assertEqual(wipers["binding"], "calendar")
        self.assertAlmostEqual(wipers["progress"], 529 / 365.0)

    def test_mileage_only_item_via_period_override(self):
        evs = [{"date": date(2025, 4, 13), "km": 10000, "item": "brake_pads",
                "raw_item": "brake_pads", "cost": None, "note": "", "row": 2}]
        pads = self.item(self.state(evs, 21400, periods={"brake_pads": (0, 40000)}), "brake_pads")
        self.assertIsNone(pads["calendar_progress"])
        self.assertEqual(pads["binding"], "mileage")
        self.assertAlmostEqual(pads["progress"], 11400 / 40000.0)

    def test_band_boundaries(self):
        cases = [(0.699, "OK"), (0.70, "SOON"), (0.849, "SOON"),
                 (0.85, "DUE"), (0.999, "DUE"), (1.0, "OVERDUE"), (1.5, "OVERDUE")]
        for progress, expected in cases:
            self.assertEqual(oi.band_of(progress), expected, progress)

    def test_binding_clock_is_the_larger_progress(self):
        evs = [{"date": date(2025, 4, 13), "km": 19200, "item": "engine_oil",
                "raw_item": "e", "cost": None, "note": "", "row": 2}]
        oil = self.item(self.state(evs, 21400), "engine_oil")
        self.assertEqual(oil["binding"], "calendar")
        evs_high = [{"date": date(2025, 10, 1), "km": 1000, "item": "engine_oil",
                     "raw_item": "e", "cost": None, "note": "", "row": 2}]
        oil_high = self.item(self.state(evs_high, 21400), "engine_oil")
        self.assertEqual(oil_high["binding"], "mileage")

    def test_items_without_service_start_at_purchase_and_are_marked(self):
        battery = self.item(self.state([], 21400), "battery")
        self.assertTrue(battery["assumed"])
        self.assertEqual(battery["last_date"], date(2022, 3, 15))
        self.assertAlmostEqual(battery["progress"],
                               (AS_OF - date(2022, 3, 15)).days / 1095.0)

    def test_latest_service_resets_both_clocks(self):
        evs = [
            {"date": date(2022, 9, 10), "km": 4200, "item": "engine_oil",
             "raw_item": "e", "cost": None, "note": "", "row": 2},
            {"date": date(2025, 4, 13), "km": 19200, "item": "engine_oil",
             "raw_item": "e", "cost": None, "note": "", "row": 3},
        ]
        oil = self.item(self.state(evs, 21400), "engine_oil")
        self.assertEqual(oil["last_date"], date(2025, 4, 13))
        self.assertEqual(oil["last_km"], 19200)
        self.assertFalse(oil["assumed"])

    def test_period_override_changes_the_verdict(self):
        evs = [{"date": date(2025, 4, 13), "km": 19200, "item": "engine_oil",
                "raw_item": "e", "cost": None, "note": "", "row": 2}]
        oil = self.item(self.state(evs, 21400, periods={"engine_oil": (365, 10000)}), "engine_oil")
        self.assertEqual(oil["band"], "OK")
        self.assertAlmostEqual(oil["progress"], 232 / 365.0)


class MismatchTests(unittest.TestCase):
    """The core insight: the odometer lies for low-mileage drivers."""

    def test_low_mileage_oil_overdue_on_calendar_only(self):
        car = {"name": "T", "bought_date": date(2022, 3, 15), "bought_km": 0}
        evs = [{"date": date(2025, 4, 13), "km": 19200, "item": "engine_oil",
                "raw_item": "e", "cost": None, "note": "", "row": 2}]
        st = oi.compute_state(car, evs, {}, AS_OF, 21400)
        oil = [it for it in st["items"] if it["item"] == "engine_oil"][0]
        self.assertLess(oil["mileage_progress"], 0.5)
        self.assertGreater(oil["calendar_progress"], 1.0)
        self.assertEqual(oil["band"], "OVERDUE")
        self.assertEqual(oil["binding"], "calendar")

    def test_high_mileage_oil_overdue_on_mileage_only(self):
        car = {"name": "T", "bought_date": date(2024, 1, 1), "bought_km": 0}
        evs = [{"date": date(2025, 10, 1), "km": 88000, "item": "engine_oil",
                "raw_item": "e", "cost": None, "note": "", "row": 2}]
        st = oi.compute_state(car, evs, {}, date(2025, 12, 1), 101000)
        oil = [it for it in st["items"] if it["item"] == "engine_oil"][0]
        self.assertLess(oil["calendar_progress"], 0.5)
        self.assertGreater(oil["mileage_progress"], 1.0)
        self.assertEqual(oil["band"], "OVERDUE")
        self.assertEqual(oil["binding"], "mileage")

    def test_odometer_is_max_of_ledger_and_flag(self):
        car = {"name": "T", "bought_date": date(2022, 3, 15), "bought_km": 100}
        evs = [{"date": date(2025, 4, 13), "km": 19200, "item": "engine_oil",
                "raw_item": "e", "cost": None, "note": "", "row": 2}]
        st = oi.compute_state(car, evs, {}, AS_OF, None)
        self.assertEqual(st["odometer"], 19200)
        st = oi.compute_state(car, evs, {}, AS_OF, 21400)
        self.assertEqual(st["odometer"], 21400)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.car, self.svc = write_ledger(
            self.tmp, CAR,
            ["date,km,item", "2025-04-13,19200,engine_oil", "2025-04-13,19200,神秘液体"])

    def test_items_sorted_by_progress_desc(self):
        code, out, _ = run_cli(["status", self.car, self.svc,
                                "--as-of", "2025-12-01", "--km-now", "21400"])
        self.assertEqual(code, 0)
        progress_col = []
        for line in out.splitlines():
            tokens = line.split()
            if (line.startswith("  ") and len(tokens) >= 4
                    and tokens[-2] in ("!!", "!", "~", ".")):
                progress_col.append(float(tokens[-3].rstrip("%")))
        self.assertEqual(progress_col, sorted(progress_col, reverse=True))
        self.assertIn("items in the log with no known period", out)
        self.assertIn("神秘液体", out)

    def test_counts_line_and_unknown_items(self):
        code, out, _ = run_cli(["status", self.car, self.svc,
                                "--as-of", "2025-12-01", "--km-now", "21400"])
        self.assertIn("11 tracked", out)
        self.assertIn("8 OVERDUE", out)
        self.assertIn("not judged", out)

    def test_json_format(self):
        code, out, _ = run_cli(["status", self.car, self.svc,
                                "--as-of", "2025-12-01", "--km-now", "21400",
                                "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["odometer"], 21400)
        self.assertTrue(any(it["item"] == "engine_oil" and it["band"] == "OVERDUE"
                            for it in payload["items"]))


class ProfileTests(unittest.TestCase):
    def build(self, car, evs, km_now, as_of=AS_OF):
        state = oi.compute_state(car, evs, {}, as_of, km_now)
        return state, oi.build_profile(car, state, as_of)

    def test_km_per_year(self):
        car = {"name": "T", "bought_date": date(2022, 3, 15), "bought_km": 0}
        _, profile = self.build(car, [], 21400)
        expected = 21400 / ((AS_OF - date(2022, 3, 15)).days / 365.25)
        self.assertAlmostEqual(profile["km_per_year"], expected, places=2)

    def test_calendar_bound_label(self):
        car = {"name": "T", "bought_date": date(2022, 3, 15), "bought_km": 0}
        state, profile = self.build(car, [], 21400)
        self.assertEqual(profile["label"], "calendar")
        self.assertEqual(profile["calendar_bound"], profile["due_count"])
        self.assertGreaterEqual(profile["due_count"], 2)

    def test_mileage_bound_label(self):
        car = {"name": "T", "bought_date": date(2024, 6, 1), "bought_km": 0}
        evs = [
            {"date": date(2025, 6, 1), "km": 50000, "item": "wipers",
             "raw_item": "w", "cost": None, "note": "", "row": 2},
            {"date": date(2025, 8, 1), "km": 60000, "item": "air_filter",
             "raw_item": "a", "cost": None, "note": "", "row": 3},
            {"date": date(2025, 8, 1), "km": 60000, "item": "cabin_filter",
             "raw_item": "c", "cost": None, "note": "", "row": 4},
            {"date": date(2025, 10, 1), "km": 88000, "item": "engine_oil",
             "raw_item": "e", "cost": None, "note": "", "row": 5},
            {"date": date(2025, 11, 1), "km": 95000, "item": "oil_filter",
             "raw_item": "o", "cost": None, "note": "", "row": 6},
        ]
        state, profile = self.build(car, evs, 101000, date(2025, 12, 1))
        due = [it for it in state["items"] if it["band"] in ("OVERDUE", "DUE")]
        self.assertGreaterEqual(len(due), 2)
        self.assertEqual({it["binding"] for it in due}, {"mileage"})
        self.assertEqual(profile["label"], "mileage")
        self.assertEqual(profile["mileage_bound"], profile["due_count"])

    def test_no_label_below_two_due_items(self):
        car = {"name": "T", "bought_date": date(2025, 8, 1), "bought_km": 0}
        state, profile = self.build(car, [], 3000, date(2025, 12, 1))
        self.assertLess(profile["due_count"], 2)
        self.assertIsNone(profile["label"])


class TripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.car, self.svc = write_ledger(
            self.tmp, CAR,
            ["date,km,item", "2025-04-13,19200,engine_oil"])

    def test_fail_exit_4_with_service_list(self):
        code, out, _ = run_cli(["trip", self.car, self.svc,
                                "--as-of", "2025-12-01", "--km-now", "21400",
                                "--km", "2600", "--days", "12"])
        self.assertEqual(code, 4)
        self.assertIn("gate: FAIL", out)
        self.assertIn("service before you leave", out)
        self.assertIn("engine_oil", out)

    def test_pass_exit_0_on_fresh_ledger(self):
        car2, svc2 = write_ledger(
            self.tmp, ["name,bought_date,bought_km", "Fresh,2025-10-01,0"],
            ["date,km,item", "2025-10-01,0,engine_oil", "2025-10-01,0,wipers"],
            "fresh.csv", "fresh-svc.csv")
        code, out, _ = run_cli(["trip", car2, svc2,
                                "--as-of", "2025-12-01", "--km", "500"])
        self.assertEqual(code, 0)
        self.assertIn("gate: PASS", out)
        self.assertIn("no item crosses its line", out)

    def test_return_point_is_asof_plus_days_and_km(self):
        code, out, _ = run_cli(["trip", self.car, self.svc,
                                "--as-of", "2025-12-01", "--km-now", "21400",
                                "--km", "2600", "--days", "12"])
        self.assertIn("return    : 2025-12-13 @ 24,000 km", out)

    def test_warn_band_reported_without_failing(self):
        car2, svc2 = write_ledger(
            self.tmp, ["name,bought_date,bought_km", "Mid,2024-03-01,0"],
            ["date,km,item",
             "2024-03-25,500,brake_fluid",
             "2025-06-01,2000,wipers",
             "2025-09-01,3000,coolant",
             "2025-10-01,3000,engine_oil",
             "2025-10-01,3000,oil_filter",
             "2025-10-01,3000,air_filter",
             "2025-10-01,3000,cabin_filter"],
            "mid.csv", "mid-svc.csv")
        code, out, _ = run_cli(["trip", car2, svc2,
                                "--as-of", "2025-12-01", "--km-now", "3000",
                                "--km", "100", "--days", "12"])
        self.assertEqual(code, 0)
        self.assertIn("enters the DUE band mid-trip", out)
        self.assertIn("brake_fluid", out)
        self.assertIn("gate: PASS", out)

    def test_days_defaults_to_seven_and_km_required(self):
        code, _, _ = run_cli(["trip", self.car, self.svc,
                              "--as-of", "2025-12-01", "--km-now", "21400"])
        self.assertEqual(code, 2)
        code, out, _ = run_cli(["trip", self.car, self.svc,
                                "--as-of", "2025-12-01", "--km-now", "21400",
                                "--km", "100"])
        self.assertIn("/ 7 days", out)

    def test_negative_km_rejected(self):
        code, _, err = run_cli(["trip", self.car, self.svc, "--km", "-5"])
        self.assertIn("error", err)


class CostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_full_cost_account(self):
        car, svc = write_ledger(
            self.tmp, CAR,
            ["date,km,item,cost", "2022-09-10,4200,engine_oil,380",
             "2025-04-13,19200,engine_oil,420", "2025-04-13,19200,wipers,130"])
        code, out, _ = run_cli(["cost", car, svc,
                                "--as-of", "2025-12-01", "--km-now", "21400"])
        self.assertEqual(code, 0)
        self.assertIn("3 priced entries · ¥930 total", out)
        self.assertIn("¥0.043 / km", out)
        self.assertIn("engine_oil ¥800", out)
        self.assertIn("wipers ¥130", out)

    def test_no_cost_column_stays_honest(self):
        car, svc = write_ledger(self.tmp, CAR,
                                ["date,km,item", "2025-04-13,19200,engine_oil"])
        code, out, _ = run_cli(["cost", car, svc,
                                "--as-of", "2025-12-01", "--km-now", "21400"])
        self.assertEqual(code, 0)
        self.assertIn("no cost column", out)
        self.assertIn("will not invent", out)

    def test_bad_cost_reports_row(self):
        _, svc = write_ledger(
            self.tmp, CAR, ["date,km,item,cost", "2025-04-13,19200,engine_oil,贵"],
            "bad.csv", "bad-svc.csv")
        with self.assertRaises(oi.ParseError) as ctx:
            oi.parse_service(svc)
        self.assertIn("row 2", str(ctx.exception))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.car, self.svc = write_ledger(
            self.tmp, CAR,
            ["date,km,item", "2025-04-13,19200,engine_oil"])

    def test_no_arguments_exits_2(self):
        code, _, _ = run_cli([])
        self.assertEqual(code, 2)

    def test_missing_file_exits_3(self):
        code, _, err = run_cli(["status", "no-such.csv", self.svc])
        self.assertEqual(code, 3)
        self.assertIn("file not found", err)

    def test_bad_period_spec_exits_3(self):
        code, _, err = run_cli(["status", self.car, self.svc, "--period", "engine_oil=180"])
        self.assertEqual(code, 3)
        code, _, err = run_cli(["status", self.car, self.svc, "--period", "engine_oil=0,0"])
        self.assertEqual(code, 3)

    def test_as_of_defaults_to_today(self):
        code, out, _ = run_cli(["status", self.car, self.svc])
        self.assertEqual(code, 0)
        self.assertIn(date.today().isoformat(), out)

    def test_km_now_pinned(self):
        code, out, _ = run_cli(["status", self.car, self.svc,
                                "--as-of", "2025-12-01", "--km-now", "30000"])
        self.assertIn("30,000 km on the odometer", out)
        code, out, _ = run_cli(["status", self.car, self.svc,
                                "--as-of", "2025-12-01", "--km-now", "21400"])
        self.assertIn("21,400 km on the odometer", out)


class DogfoodTests(unittest.TestCase):
    def test_examples_in_sync(self):
        result = subprocess.run(
            [sys.executable, str(EXAMPLES / "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("in sync", result.stdout)

    def test_demo_status_tells_the_calendar_story(self):
        code, out, _ = run_cli(["status", str(EXAMPLES / "family-car.csv"),
                                str(EXAMPLES / "service-log.csv"),
                                "--as-of", "2025-12-01", "--km-now", "21400"])
        self.assertEqual(code, 0)
        self.assertIn("6 OVERDUE · 0 DUE · 2 SOON · 3 OK", out)
        oil_line = [line for line in out.splitlines()
                    if line.strip().startswith("engine_oil")][0]
        self.assertIn("44%", oil_line)
        self.assertIn("129%", oil_line)
        self.assertIn("calendar-bound driver", out)
        self.assertIn("aging in the garage, not on the road", out)

    def test_demo_trip_fails_and_cost_adds_up(self):
        code, out, _ = run_cli(["trip", str(EXAMPLES / "family-car.csv"),
                                str(EXAMPLES / "service-log.csv"),
                                "--as-of", "2025-12-01", "--km-now", "21400",
                                "--km", "2600", "--days", "12"])
        self.assertEqual(code, 4)
        self.assertIn("6 of 11 items cross the line mid-trip", out)
        self.assertIn("gate: FAIL", out)
        code, out, _ = run_cli(["cost", str(EXAMPLES / "family-car.csv"),
                                str(EXAMPLES / "service-log.csv"),
                                "--as-of", "2025-12-01", "--km-now", "21400"])
        self.assertIn("¥3,161 total", out)
        self.assertIn("¥0.148 / km", out)


if __name__ == "__main__":
    unittest.main()
