#!/usr/bin/env python3
"""Acceptance tests for 来得及 · Make It.

Every acceptance criterion in README.md is a test here. Synthetic
ledgers are written to temp dirs with hand-computable numbers; the
dogfood suite regenerates the committed examples and byte-compares
them, and drives the real CLI end to end.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import make_it as mi  # noqa: E402

AS_OF = "2026-08-29"
EXAMPLES = ROOT / "examples"


def run_main(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = mi.main(argv)
    return code, out.getvalue()


def call_cli(argv):
    """Run the CLI as a subprocess; return (exit code, stdout)."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "make_it.py")] + argv,
        capture_output=True, text=True)
    return proc.returncode, proc.stdout


def clock(text):
    return mi.parse_clock(text, "test")


def fmt(minutes):
    return mi.fmt_clock(minutes)


def rows_csv(rows, header="date,route,depart,arrive,target"):
    tmp = tempfile.mkdtemp(prefix="makeit-test-")
    path = os.path.join(tmp, "commutes.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + "\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")
    return path


def uniform(durs, route="r", dep="08:00", target="09:00",
            start="2026-01-01"):
    """One row per duration, sequential dates, arrive = depart + dur."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    dep_min = clock(dep)
    out = []
    for i, dur in enumerate(durs):
        d = (d0 + timedelta(days=i)).isoformat()
        out.append((d, route, dep, fmt(dep_min + dur), target))
    return out


EXAMPLE = str(EXAMPLES / "commutes.csv")


class QuantileTests(unittest.TestCase):
    def test_nearest_rank_hand_case(self):
        vals = sorted([30, 10, 40, 20, 50, 60, 70, 80, 90, 100])
        self.assertEqual(mi.quantile(vals, 0.5), 50)
        self.assertEqual(mi.quantile(vals, 0.8), 80)
        self.assertEqual(mi.quantile(vals, 0.9), 90)

    def test_nearest_rank_rounds_up(self):
        vals = [10, 20, 30, 40]  # ceil(0.8*4)=4 -> 40
        self.assertEqual(mi.quantile(vals, 0.8), 40)
        self.assertEqual(mi.quantile(vals, 0.5), 20)  # ceil(2)=2nd

    def test_median_sorts_input(self):
        # regression: unsorted input once returned the wrong late median
        # (nearest-rank P50 of two values takes the lower one)
        self.assertEqual(mi.median([8, 13, 8, 7]), 8)
        self.assertEqual(mi.median([13, 7]), 7)
        self.assertEqual(mi.median([13, 14]), 13)

    def test_quantile_single_value(self):
        self.assertEqual(mi.quantile([42], 0.99), 42)

    def test_quantile_clamps_top(self):
        vals = [1, 2, 3]
        self.assertEqual(mi.quantile(vals, 1.0), 3)


class ParserTests(unittest.TestCase):
    def test_minimal_four_columns(self):
        path = rows_csv([("2026-03-02", "m1", "08:00", "08:40", "")],
                        header="date,route,depart,arrive")
        rows = mi.read_ledger(path)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["timed"])
        self.assertIsNone(rows[0]["target"])
        self.assertEqual(rows[0]["duration"], 40)

    def test_chinese_header_aliases(self):
        path = rows_csv([("2026-03-02", "一号线", "07:58", "08:37", "09:00")],
                        header="日期,路线,出发,到达,目标")
        rows = mi.read_ledger(path)
        self.assertEqual(rows[0]["route"], "一号线")
        self.assertEqual(rows[0]["margin"], 23)

    def test_extra_columns_ignored(self):
        path = rows_csv([("2026-03-02", "m1", "08:00", "08:40", "09:00", "rain")],
                        header="date,route,depart,arrive,target,note")
        self.assertEqual(len(mi.read_ledger(path)), 1)

    def test_blank_lines_skipped(self):
        tmp = tempfile.mkdtemp(prefix="makeit-test-")
        path = os.path.join(tmp, "c.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("date,route,depart,arrive,target\n"
                     "2026-03-02,m1,08:00,08:40,09:00\n\n"
                     "2026-03-04,m1,08:00,08:41,09:00\n")
        self.assertEqual(len(mi.read_ledger(path)), 2)

    def test_bad_date_rejected(self):
        path = rows_csv([("2026-13-02", "m1", "08:00", "08:40", "09:00")])
        with self.assertRaises(mi.ParseError):
            mi.read_ledger(path)

    def test_bad_time_rejected(self):
        path = rows_csv([("2026-03-02", "m1", "8:00", "08:40", "09:00")])
        with self.assertRaises(mi.ParseError):
            mi.read_ledger(path)

    def test_arrive_not_after_depart_rejected(self):
        path = rows_csv([("2026-03-02", "m1", "08:40", "08:40", "09:00")])
        with self.assertRaises(mi.ParseError):
            mi.read_ledger(path)

    def test_crossing_midnight_rejected(self):
        path = rows_csv([("2026-03-02", "m1", "23:50", "00:20", "")])
        with self.assertRaises(mi.ParseError):
            mi.read_ledger(path)

    def test_empty_route_rejected(self):
        path = rows_csv([("2026-03-02", "", "08:00", "08:40", "09:00")])
        with self.assertRaises(mi.ParseError):
            mi.read_ledger(path)

    def test_no_data_rows_rejected(self):
        tmp = tempfile.mkdtemp(prefix="makeit-test-")
        path = os.path.join(tmp, "c.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("date,route,depart,arrive,target\n")
        with self.assertRaises(mi.ParseError):
            mi.read_ledger(path)

    def test_missing_columns_named(self):
        tmp = tempfile.mkdtemp(prefix="makeit-test-")
        path = os.path.join(tmp, "c.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("date,route,depart\n2026-03-02,m1,08:00\n")
        with self.assertRaises(mi.ParseError) as ctx:
            mi.read_ledger(path)
        self.assertIn("arrive", str(ctx.exception))

    def test_weekday_derived(self):
        path = rows_csv([("2026-08-28", "m1", "08:00", "08:40", "09:00")])
        self.assertEqual(mi.read_ledger(path)[0]["weekday"], "Fri")


class NowTests(unittest.TestCase):
    def test_safe_when_worst_day_fits(self):
        # example ledger: leave 07:50 -> 70m margin; the early-window
        # pool (30 rides) worst day is 45m -> 25m spare
        code, out = run_main(["now", EXAMPLE, "--route", "metro-line2",
                              "--at", "07:50", "--by", "09:00",
                              "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("SAFE", out)
        self.assertIn("25m to spare", out)

    def test_risky_when_median_fits_but_worst_overruns(self):
        # leave 08:16 -> 44m; 17 of the 25 from-08:15 rides fit (68%)
        code, out = run_main(["now", EXAMPLE, "--route", "metro-line2",
                              "--at", "08:16", "--by", "09:00",
                              "--as-of", AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("RISKY", out)
        self.assertIn("68%", out)

    def test_dead_when_median_already_misses(self):
        code, out = run_main(["now", EXAMPLE, "--route", "metro-line2",
                              "--at", "08:24", "--by", "09:00",
                              "--as-of", AS_OF])
        self.assertEqual(code, 5)
        self.assertIn("DEAD", out)
        self.assertIn("misses by 8m", out)

    def test_thin_refuses_to_invent_probability(self):
        code, out = run_main(["now", EXAMPLE, "--route", "bike",
                              "--at", "08:00", "--by", "09:00",
                              "--as-of", AS_OF])
        self.assertEqual(code, 3)
        self.assertIn("THIN", out)
        self.assertIn("only 4 trips", out)

    def test_deadline_already_passed(self):
        code, out = run_main(["now", EXAMPLE, "--route", "metro-line2",
                              "--at", "09:05", "--by", "09:00",
                              "--as-of", AS_OF])
        self.assertEqual(code, 5)
        self.assertIn("no longer about the commute", out)

    def test_window_bucket_beats_route_pool(self):
        # early rides 20 min (x10), from-08:15 rides 60 min (x8):
        # at 08:20 the verdict must read the late window, not the pool
        rows = uniform([20] * 10, dep="07:50")
        rows += uniform([60] * 8, route="r", dep="08:20",
                        start="2026-02-01")
        path = rows_csv(rows)
        code, out = run_main(["now", path, "--route", "r",
                              "--at", "08:25", "--by", "09:00",
                              "--as-of", AS_OF])
        self.assertEqual(code, 5)
        self.assertIn("departures from 08:15 (n=8)", out)

    def test_bucket_too_thin_falls_back_to_route(self):
        rows = uniform([20] * 10, dep="07:50")
        rows += uniform([60] * 3, dep="08:20", start="2026-02-01")
        path = rows_csv(rows)
        code, out = run_main(["now", path, "--route", "r",
                              "--at", "07:55", "--by", "09:00",
                              "--as-of", AS_OF])
        self.assertEqual(code, 0)  # early bucket is thick and fast
        self.assertIn("departures before 08:15 (n=10)", out)

    def test_verdict_boundary_p_equals_want_is_safe(self):
        rows = uniform([10] * 6 + [20] * 2)
        path = rows_csv(rows)
        code, out = run_main(["now", path, "--route", "r",
                              "--at", "08:50", "--by", "09:00",
                              "--want", "0.75", "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("SAFE", out)

    def test_boundary_p_half_is_risky(self):
        rows = uniform([10] * 4 + [20] * 4)
        path = rows_csv(rows)
        code, out = run_main(["now", path, "--route", "r",
                              "--at", "08:45", "--by", "09:00",
                              "--as-of", AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("RISKY", out)

    def test_untimed_rows_still_count_as_evidence(self):
        # 10 timed + 4 untimed rides: n=14, durations pooled from all
        rows = uniform([25] * 10)
        rows += uniform([22] * 4, target="", start="2026-03-01")
        path = rows_csv(rows)
        code, out = run_main(["now", path, "--route", "r",
                              "--at", "08:30", "--by", "09:00",
                              "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("SAFE", out)

    def test_unknown_route_is_usage_error(self):
        code, out = run_main(["now", EXAMPLE, "--route", "ferry",
                              "--at", "08:00", "--by", "09:00"])
        self.assertEqual(code, 2)

    def test_missing_at_is_usage_error(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "make_it.py"), "now", EXAMPLE,
             "--route", "metro-line2", "--by", "09:00"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--at", proc.stderr)

    def test_want_out_of_range_rejected(self):
        code, _ = run_main(["now", EXAMPLE, "--route", "metro-line2",
                            "--at", "08:00", "--by", "09:00",
                            "--want", "0.4"])
        self.assertEqual(code, 2)


class LeaveTests(unittest.TestCase):
    def test_go_solves_against_window_refined_bucket(self):
        code, out = run_main(["leave", EXAMPLE, "--route", "metro-line2",
                              "--by", "09:00", "--at", "08:05",
                              "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("leave at 08:13", out)
        self.assertIn("budget 47m", out)
        self.assertIn("departures from 08:15, n=25", out)
        self.assertIn("8m of margin", out)

    def test_window_closed_reports_expected_lateness(self):
        code, out = run_main(["leave", EXAMPLE, "--route", "metro-line2",
                              "--by", "09:00", "--at", "08:20",
                              "--as-of", AS_OF])
        self.assertEqual(code, 5)
        self.assertIn("WINDOW CLOSED", out)
        self.assertIn("arrives 09:04", out)  # 08:20 + 44m median

    def test_thin_route_refuses(self):
        code, out = run_main(["leave", EXAMPLE, "--route", "bike",
                              "--by", "09:00", "--as-of", AS_OF])
        self.assertEqual(code, 3)
        self.assertIn("THIN", out)

    def test_bucket_too_thin_falls_back_with_label(self):
        rows = uniform([30] * 10, dep="07:50")
        rows += uniform([50] * 3, dep="08:20", start="2026-02-01")
        path = rows_csv(rows)
        code, out = run_main(["leave", path, "--route", "r",
                              "--by", "09:00", "--as-of", AS_OF])
        self.assertEqual(code, 0)
        # the early bucket solves 08:30, but a 08:30 departure belongs to
        # the late window, which is too thin to condition on — so the
        # honest answer falls back to the route-wide P90 (50m -> 08:10),
        # a line that is safe under every window's own statistics
        self.assertIn("leave at 08:10", out)
        self.assertIn("budget 50m", out)
        self.assertIn("route overall (window bucket thin), n=13", out)

    def test_no_at_still_solves(self):
        code, out = run_main(["leave", EXAMPLE, "--route", "metro-line2",
                              "--by", "09:00", "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("leave at 08:13", out)
        self.assertNotIn("of margin", out)

    def test_later_target_earlier_line(self):
        code_early, out_early = run_main(
            ["leave", EXAMPLE, "--route", "metro-line2",
             "--by", "08:45", "--as-of", AS_OF])
        code_late, out_late = run_main(
            ["leave", EXAMPLE, "--route", "metro-line2",
             "--by", "09:15", "--as-of", AS_OF])
        self.assertEqual(code_early, 0)
        self.assertEqual(code_late, 0)
        self.assertIn("leave at 08:03", out_early)
        self.assertIn("leave at 08:28", out_late)

    def test_higher_confidence_costs_more_margin(self):
        _, out80 = run_main(["leave", EXAMPLE, "--route", "metro-line2",
                             "--by", "09:00", "--want", "0.8",
                             "--as-of", AS_OF])
        _, out90 = run_main(["leave", EXAMPLE, "--route", "metro-line2",
                             "--by", "09:00", "--want", "0.9",
                             "--as-of", AS_OF])
        _, out95 = run_main(["leave", EXAMPLE, "--route", "metro-line2",
                             "--by", "09:00", "--want", "0.95",
                             "--as-of", AS_OF])
        self.assertIn("leave at 08:15", out80)   # P80 of the late window
        self.assertIn("leave at 08:13", out90)   # oscillates -> conservative
        self.assertIn("leave at 08:12", out95)   # P95 of the late window
        self.assertIn("08:15", out80)
        # higher bar never means a later line
        self.assertNotIn("budget 42m (42m ride, departures before 08:15",
                         out80)


class RoutesTests(unittest.TestCase):
    def test_p80_crowns_the_steady_route(self):
        code, out = run_main(["routes", EXAMPLE, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("metro-line2    55   42m    44m", out)
        self.assertIn("proven steadiest at P80", out)

    def test_p50_flip_crowns_the_fast_jittery_route(self):
        code, out = run_main(["routes", EXAMPLE, "--quantile", "0.5",
                              "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("bus-73", out)
        self.assertLess(out.index("bus-73"), out.index("metro-line2"))
        self.assertIn("proven steadiest at P50", out)

    def test_thin_route_never_crowned(self):
        # bike sorts first at P80 (31m) but must not take the crown
        code, out = run_main(["routes", EXAMPLE, "--as-of", AS_OF])
        lines = out.splitlines()
        bike_line = next(l for l in lines if l.strip().startswith("bike"))
        crown_line = next(l for l in lines if "proven steadiest" in l)
        self.assertLess(lines.index(bike_line), lines.index(crown_line))
        self.assertIn("never crowned", bike_line)
        self.assertIn("metro-line2", crown_line)

    def test_all_thin_crowns_nothing(self):
        rows = uniform([20] * 3, route="a")
        rows += uniform([25] * 2, route="b", start="2026-03-01")
        path = rows_csv(rows)
        code, out = run_main(["routes", path, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("no route is proven yet", out)

    def test_untimed_route_on_time_na(self):
        code, out = run_main(["routes", EXAMPLE, "--as-of", AS_OF])
        self.assertIn("n/a", out)

    def test_quantile_out_of_range_rejected(self):
        code, _ = run_main(["routes", EXAMPLE, "--quantile", "0.3"])
        self.assertEqual(code, 2)

    def test_mean_trap_named_in_report(self):
        _, out = run_main(["routes", EXAMPLE, "--as-of", AS_OF])
        self.assertIn("the mean hides jitter", out)


class LateTests(unittest.TestCase):
    def test_totals(self):
        code, out = run_main(["late", EXAMPLE, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("8 late trips in 67 timed (11.9%)", out)
        self.assertIn("22 close calls", out)

    def test_by_route_sorted_rates(self):
        _, out = run_main(["late", EXAMPLE, "--as-of", AS_OF])
        self.assertIn("bus-73         12     4   33.3%", out)
        self.assertIn("metro-line2    55     4    7.3%", out)

    def test_median_late_is_sorted_median(self):
        # metro lateness margins: 7, 8, 8, 13 -> median 8 (not ledger order)
        _, out = run_main(["late", EXAMPLE, "--as-of", AS_OF])
        self.assertIn("metro-line2    55     4    7.3%           8m    13m", out)

    def test_weekday_concentration(self):
        _, out = run_main(["late", EXAMPLE, "--as-of", AS_OF])
        self.assertIn("Fri            23     6   26.1%", out)

    def test_repeat_offender(self):
        _, out = run_main(["late", EXAMPLE, "--as-of", AS_OF])
        self.assertIn("metro-line2 on Fri — 50% of all lateness", out)

    def test_clean_ledger_confesses_nothing(self):
        rows = uniform([30] * 12)
        path = rows_csv(rows)
        code, out = run_main(["late", path, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("0 late trips in 12 timed (0.0%)", out)
        self.assertIn("nothing to confess", out)

    def test_close_call_window_is_five_minutes(self):
        # dep 08:30 -> arrive 08:59 / 09:00 / 09:01: margins +1 / 0 / -1
        rows = uniform([29] * 4 + [30] * 4 + [31] * 4, dep="08:30")
        path = rows_csv(rows)
        _, out = run_main(["late", path, "--as-of", AS_OF])
        self.assertIn("4 late trips in 12 timed (33.3%)", out)
        self.assertIn("8 close calls", out)


class SimulateTests(unittest.TestCase):
    def test_ten_minutes_earlier_fixes_the_clock(self):
        code, out = run_main(["simulate", EXAMPLE, "--earlier", "10",
                              "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("88.1%   97.0%", out)
        self.assertIn("late trips        8       2", out)
        self.assertIn("late minutes     65       5", out)
        self.assertIn("FIXED BY CLOCK", out)

    def test_annualized_numbers_present(self):
        _, out = run_main(["simulate", EXAMPLE, "--earlier", "10",
                           "--as-of", AS_OF])
        self.assertIn("16 -> 4 late trips a year", out)
        self.assertIn("132 -> 10 late minutes", out)

    def test_route_filter(self):
        _, out = run_main(["simulate", EXAMPLE, "--earlier", "10",
                           "--route", "bus-73", "--as-of", AS_OF])
        self.assertIn("(n=12", out)
        self.assertIn("66.7%", out)
        self.assertIn("91.7%", out)

    def test_still_late_after_shift_is_advisory_red(self):
        code, out = run_main(["simulate", EXAMPLE, "--earlier", "2",
                              "--as-of", AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("STILL LATE", out)

    def test_untimed_only_route_is_usage_error(self):
        code, _ = run_main(["simulate", EXAMPLE, "--earlier", "10",
                            "--route", "bike"])
        self.assertEqual(code, 2)

    def test_nonpositive_earlier_rejected(self):
        code, _ = run_main(["simulate", EXAMPLE, "--earlier", "0"])
        self.assertEqual(code, 2)

    def test_unknown_route_rejected(self):
        code, _ = run_main(["simulate", EXAMPLE, "--earlier", "10",
                            "--route", "ferry"])
        self.assertEqual(code, 2)


class StatsTests(unittest.TestCase):
    def test_example_portrait(self):
        code, out = run_main(["stats", EXAMPLE, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("71 commutes · 3 routes · 2026-03-02 .. 2026-08-28 · 67 timed",
                      out)
        self.assertIn("metro-line2    55   42m   44m   45m    49m    92.7%     21",
                      out)
        self.assertIn("bus-73         12   36m   50m   56m    60m    66.7%      1",
                      out)

    def test_late_departure_inflation_line(self):
        _, out = run_main(["stats", EXAMPLE, "--as-of", AS_OF])
        self.assertIn("median 39m (n=30) vs 44m (n=25) — leaving later costs +12.8%",
                      out)
        self.assertIn("median 36m (n=7) vs 38m (n=5) — leaving later costs +5.6%",
                      out)

    def test_thin_route_tagged(self):
        _, out = run_main(["stats", EXAMPLE, "--as-of", AS_OF])
        self.assertIn("bike            4   27m   31m   31m    31m      n/a      -"
                      "  (thin: n=4 < 10)", out)
        self.assertIn("thin routes: bike", out)

    def test_route_filter(self):
        _, out = run_main(["stats", EXAMPLE, "--route", "bus-73",
                           "--as-of", AS_OF])
        self.assertIn("bus-73", out)
        self.assertNotIn("metro-line2", out)

    def test_untimed_route_has_no_ontime(self):
        rows = uniform([25] * 4, target="")
        path = rows_csv(rows)
        _, out = run_main(["stats", path, "--as-of", AS_OF])
        self.assertIn("n/a", out)

    def test_unknown_route_rejected(self):
        code, _ = run_main(["stats", EXAMPLE, "--route", "ferry"])
        self.assertEqual(code, 2)


class JsonTests(unittest.TestCase):
    def test_now_json_verdict_and_code(self):
        code, out = run_main(["now", EXAMPLE, "--route", "metro-line2",
                              "--at", "08:24", "--by", "09:00",
                              "--format", "json", "--as-of", AS_OF])
        self.assertEqual(code, 5)
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "DEAD")
        self.assertEqual(payload["expected_late"], 8)
        self.assertEqual(payload["p"], 0.0)

    def test_stats_json_rows(self):
        _, out = run_main(["stats", EXAMPLE, "--format", "json",
                           "--as-of", AS_OF])
        payload = json.loads(out)
        metro = next(r for r in payload["rows"]
                     if r["route"] == "metro-line2")
        self.assertEqual(metro["p50"], 42)
        self.assertEqual(metro["p80"], 44)
        self.assertAlmostEqual(metro["inflation"], 0.128, places=2)

    def test_late_json_offender(self):
        _, out = run_main(["late", EXAMPLE, "--format", "json",
                           "--as-of", AS_OF])
        payload = json.loads(out)
        self.assertEqual(payload["late_n"], 8)
        self.assertEqual(payload["offender"], "metro-line2 on Fri")
        self.assertAlmostEqual(payload["offender_share"], 0.5)

    def test_leave_json(self):
        _, out = run_main(["leave", EXAMPLE, "--route", "metro-line2",
                           "--by", "09:00", "--at", "08:05",
                           "--format", "json", "--as-of", AS_OF])
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "GO")
        self.assertEqual(payload["leave_by"], "08:13")
        self.assertEqual(payload["budget"], 47)

    def test_simulate_json(self):
        _, out = run_main(["simulate", EXAMPLE, "--earlier", "10",
                           "--format", "json", "--as-of", AS_OF])
        payload = json.loads(out)
        self.assertEqual(payload["before"]["late"], 8)
        self.assertEqual(payload["after"]["late"], 2)


class DogfoodTests(unittest.TestCase):
    def test_examples_rebuild_byte_identical(self):
        proc = subprocess.run(
            [sys.executable, "build_examples.py", "--check"],
            cwd=EXAMPLES, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("examples in sync", proc.stdout)

    def test_ledger_shape(self):
        lines = (EXAMPLES / "commutes.csv").read_text(
            encoding="utf-8").strip().splitlines()
        self.assertEqual(lines[0], "date,route,depart,arrive,target")
        self.assertEqual(len(lines) - 1, 71)

    def test_sample_reports_pinned(self):
        for name in ("sample-stats.txt", "sample-now.txt", "sample-leave.txt",
                     "sample-routes.txt", "sample-late.txt",
                     "sample-simulate.txt"):
            text = (EXAMPLES / name).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("-- Make It:"))
            self.assertIn("(as of 2026-08-29)", name and text)

    def test_cli_end_to_end_exit_codes(self):
        self.assertEqual(call_cli(["stats", EXAMPLE, "--as-of", AS_OF])[0], 0)
        self.assertEqual(call_cli(["late", EXAMPLE, "--as-of", AS_OF])[0], 0)
        self.assertEqual(call_cli(["routes", EXAMPLE, "--as-of", AS_OF])[0], 0)
        self.assertEqual(call_cli(["now", EXAMPLE, "--route", "metro-line2",
                                   "--at", "08:24", "--by", "09:00",
                                   "--as-of", AS_OF])[0], 5)
        self.assertEqual(call_cli(["leave", EXAMPLE, "--route", "metro-line2",
                                   "--by", "09:00", "--at", "08:05",
                                   "--as-of", AS_OF])[0], 0)

    def test_reproducible_byte_for_byte(self):
        argv = ["now", EXAMPLE, "--route", "metro-line2",
                "--at", "08:16", "--by", "09:00", "--as-of", AS_OF]
        self.assertEqual(call_cli(argv)[1], call_cli(argv)[1])

    def test_no_dependencies_beyond_stdlib(self):
        source = (ROOT / "make_it.py").read_text(encoding="utf-8")
        imports = [line.strip() for line in source.splitlines()
                   if line.startswith("import ") or line.startswith("from ")]
        allowed = ("import argparse", "import csv", "import json",
                   "import math", "import sys", "from datetime import")
        for line in imports:
            self.assertTrue(line.startswith(allowed),
                            "non-stdlib import: %s" % line)


if __name__ == "__main__":
    unittest.main()
