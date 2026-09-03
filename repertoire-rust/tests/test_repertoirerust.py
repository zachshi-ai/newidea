"""Acceptance tests for 绝活生锈 · Repertoire Rust.

Every acceptance criterion from the README lives here: ledger parsing,
the durability model (half-life growth/shrink/cap, freshness decay),
collapse and never-stuck detection, gig readiness on the night, the
minute-budgeted tonight plan, the keep-alive budget, CLI behavior —
plus dogfood runs against the repo's own demo ledger and a
byte-identical rebuild check of the example artifacts.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

import repertoire_rust as rr  # noqa: E402

CLI = str(PROJECT / "repertoire_rust.py")
DEMO = PROJECT / "examples" / "gig-ledger.jsonl"
AS_OF = "2026-08-31"


def rec(piece, d, kind="maintain", quality=4, minutes=20):
    return {"piece": piece, "date": rr.parse_date(d), "kind": kind,
            "quality": quality, "minutes": minutes, "line_no": 0}


def ns(**over):
    base = dict(as_of=date(2026, 8, 31), line=70, rebuild_line=40,
                format="text")
    base.update(over)
    return SimpleNamespace(**base)


class LedgerTestCase(unittest.TestCase):
    def write(self, rows):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.addCleanup(os.unlink, path)
        return path

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, CLI] + list(argv),
                              capture_output=True, text=True)


class ParserTests(LedgerTestCase):
    def test_roundtrip_fields(self):
        records = rr.read_ledger(self.write(
            [{"piece": "月亮颂", "date": "2026-03-14", "kind": "learn",
              "quality": 4, "minutes": 30}]))
        self.assertEqual(records[0]["piece"], "月亮颂")
        self.assertEqual(records[0]["date"], date(2026, 3, 14))
        self.assertEqual((records[0]["kind"], records[0]["quality"],
                          records[0]["minutes"]), ("learn", 4, 30))

    def test_defaults_quality_and_minutes(self):
        records = rr.read_ledger(self.write(
            [{"piece": "A", "date": "2026-03-14", "kind": "maintain"}]))
        self.assertEqual((records[0]["quality"], records[0]["minutes"]),
                         (3, 0))

    def test_float_quality_and_minutes_accepted(self):
        records = rr.read_ledger(self.write(
            [{"piece": "A", "date": "2026-03-14", "kind": "maintain",
              "quality": 5.0, "minutes": 20.0}]))
        self.assertEqual((records[0]["quality"], records[0]["minutes"]),
                         (5, 20))

    def test_alternate_date_formats(self):
        records = rr.read_ledger(self.write(
            [{"piece": "A", "date": "2026/3/14", "kind": "maintain"},
             {"piece": "B", "date": "2026年3月14日", "kind": "maintain"}]))
        self.assertEqual({r["date"] for r in records}, {date(2026, 3, 14)})

    def test_blank_lines_and_bom(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8-sig") as fh:
            fh.write("\n")
            fh.write(json.dumps({"piece": "A", "date": "2026-03-14",
                                 "kind": "maintain"}) + "\n\n")
        self.addCleanup(os.unlink, path)
        self.assertEqual(len(rr.read_ledger(path)), 1)

    def test_bad_json_names_the_line(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"piece": "A", "date": "2026-03-14",
                                 "kind": "maintain"}) + "\n")
            fh.write("{oops}\n")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(rr.ParseError) as cm:
            rr.read_ledger(path)
        self.assertIn("line 2", str(cm.exception))

    def test_missing_piece_and_bad_kind(self):
        with self.assertRaises(rr.ParseError):
            rr.read_ledger(self.write([{"date": "2026-03-14",
                                        "kind": "maintain"}]))
        with self.assertRaises(rr.ParseError) as cm:
            rr.read_ledger(self.write([{"piece": "A", "date": "2026-03-14",
                                        "kind": "jam"}]))
        self.assertIn("jam", str(cm.exception))

    def test_quality_bounds(self):
        for bad in (0, 6, 2.5, "good", True):
            with self.assertRaises(rr.ParseError):
                rr.read_ledger(self.write(
                    [{"piece": "A", "date": "2026-03-14", "kind": "maintain",
                      "quality": bad}]))

    def test_negative_minutes_rejected(self):
        with self.assertRaises(rr.ParseError):
            rr.read_ledger(self.write(
                [{"piece": "A", "date": "2026-03-14", "kind": "maintain",
                  "minutes": -5}]))

    def test_bad_date_and_empty_ledger(self):
        with self.assertRaises(rr.ParseError):
            rr.read_ledger(self.write([{"piece": "A", "date": "soon",
                                        "kind": "maintain"}]))
        with self.assertRaises(rr.ParseError) as cm:
            rr.read_ledger(self.write([]))
        self.assertIn("no records", str(cm.exception))

    def test_unsorted_input_is_sorted_per_piece(self):
        records = rr.read_ledger(self.write(
            [{"piece": "A", "date": "2026-03-20", "kind": "maintain"},
             {"piece": "A", "date": "2026-03-10", "kind": "maintain"}]))
        states, _ = rr.replay(records, date(2026, 3, 31))
        dates = [t["date"] for t in states["A"]["trace"]]
        self.assertEqual(dates, sorted(dates))

    def test_duplicate_same_day_sessions_kept(self):
        records = rr.read_ledger(self.write(
            [{"piece": "A", "date": "2026-03-10", "kind": "maintain",
              "quality": 4},
             {"piece": "A", "date": "2026-03-10", "kind": "maintain",
              "quality": 4}]))
        states, _ = rr.replay(records, date(2026, 3, 31))
        # 7 -> 9.1 -> 11.83
        self.assertAlmostEqual(states["A"]["half_life"], 7 * 1.3 * 1.3)


class ModelTests(unittest.TestCase):
    def test_freshness_half_life_math(self):
        d0 = date(2026, 1, 1)
        self.assertEqual(rr.freshness(7, d0, d0), 100.0)
        self.assertAlmostEqual(rr.freshness(7, d0, date(2026, 1, 8)), 50.0)
        self.assertAlmostEqual(rr.freshness(7, d0, date(2026, 1, 15)), 25.0)
        self.assertAlmostEqual(rr.freshness(365, d0,
                                            date(2026, 12, 27)) > 49, True)

    def test_growth_table(self):
        self.assertAlmostEqual(rr.half_life_after(7, "maintain", 5), 11.2)
        self.assertAlmostEqual(rr.half_life_after(7, "maintain", 4), 9.1)
        self.assertAlmostEqual(rr.half_life_after(7, "maintain", 3), 7.0)
        self.assertAlmostEqual(rr.half_life_after(7, "maintain", 2), 4.9)
        self.assertAlmostEqual(rr.half_life_after(7, "maintain", 1), 3.5)

    def test_perform_bonus(self):
        self.assertAlmostEqual(rr.half_life_after(7, "perform", 5), 14.0)

    def test_half_life_clamped(self):
        self.assertEqual(rr.half_life_after(400, "maintain", 5), rr.H_MAX)
        self.assertEqual(rr.half_life_after(1.2, "maintain", 1), rr.H_MIN)

    def test_neutral_touch_resets_clock_keeps_h(self):
        records = [rec("A", "2026-01-01", "learn", 5),
                   rec("A", "2026-02-01", "maintain", 3)]
        states, _ = rr.replay(records, date(2026, 2, 1))
        st = states["A"]
        self.assertAlmostEqual(st["half_life"], 11.2)
        self.assertEqual(rr.freshness(st["half_life"], st["last"],
                                      date(2026, 2, 1)), 100.0)

    def test_shaky_touch_shrinks_h(self):
        records = [rec("A", "2026-01-01", "learn", 5),
                   rec("A", "2026-02-01", "maintain", 2)]
        states, _ = rr.replay(records, date(2026, 2, 1))
        self.assertAlmostEqual(states["A"]["half_life"], 11.2 * 0.7)

    def test_touch_interval_and_touch_by(self):
        self.assertAlmostEqual(rr.touch_interval(7.0, 70), 3.602012, places=5)
        self.assertEqual(rr.touch_by(7.0, date(2026, 1, 1), 70),
                         date(2026, 1, 4))

    def test_band_boundaries(self):
        self.assertEqual(rr.band_of(70.0, 70, 40), "FRESH")
        self.assertEqual(rr.band_of(69.99, 70, 40), "RUSTING")
        self.assertEqual(rr.band_of(40.0, 70, 40), "RUSTING")
        self.assertEqual(rr.band_of(39.99, 70, 40), "RUSTED")


class CollapseTests(LedgerTestCase):
    def history(self):
        # builds h: 9.1 -> 14.56 -> 23.30 -> 30.29 -> 48.46 -> 62.99
        return [
            rec("Romance", "2026-01-05", "learn", 4),
            rec("Romance", "2026-01-19", "learn", 5),
            rec("Romance", "2026-02-02", "maintain", 5),
            rec("Romance", "2026-02-16", "maintain", 4),
            rec("Romance", "2026-03-02", "maintain", 5),
            rec("Romance", "2026-03-16", "maintain", 4),
        ]

    def state(self, rows):
        states, _ = rr.replay(rows, date(2026, 8, 31))
        return states["Romance"]

    def test_surprise_failure_is_a_collapse(self):
        rows = self.history()
        rows.append(rec("Romance", "2026-04-20", "maintain", 2))
        st = self.state(rows)
        self.assertEqual(len(st["collapses"]), 1)
        self.assertEqual(st["collapses"][0]["fresh_before"], 68)
        self.assertTrue(st["trace"][-1]["collapse"])

    def test_collapse_caps_half_life(self):
        rows = self.history()
        rows.append(rec("Romance", "2026-04-20", "maintain", 2))
        st = self.state(rows)
        self.assertAlmostEqual(st["half_life"], rr.COLLAPSE_CAP)

    def test_expected_failure_is_not_a_collapse(self):
        # 3 days later: ledger still believes (F ~94%) but rust has not
        # had a week to form — a bad day, not a collapse.
        rows = self.history()
        rows.append(rec("Romance", "2026-03-19", "maintain", 2))
        st = self.state(rows)
        self.assertEqual(st["collapses"], [])

    def test_failure_below_collapse_line_is_rebuild_not_surprise(self):
        rows = self.history()
        rows.append(rec("Romance", "2026-06-20", "maintain", 2))
        st = self.state(rows)
        self.assertEqual(st["collapses"], [])

    def test_two_collapses_never_stuck(self):
        rows = self.history()
        rows.append(rec("Romance", "2026-04-20", "maintain", 2))  # h -> 21
        rows.append(rec("Romance", "2026-05-11", "learn", 5))     # 33.6
        rows.append(rec("Romance", "2026-05-25", "maintain", 5))  # 53.76
        rows.append(rec("Romance", "2026-06-08", "maintain", 5))  # 86.0
        rows.append(rec("Romance", "2026-06-29", "maintain", 1))  # collapse 2
        st = self.state(rows)
        self.assertEqual(len(st["collapses"]), 2)
        self.assertAlmostEqual(st["half_life"], rr.COLLAPSE_CAP)
        states, _ = rr.replay(rows, date(2026, 8, 31))
        report = rr.build_report(states, 0, rows, date(2026, 8, 31), 70, 40,
                                 True)
        self.assertEqual([p["name"] for p in report["perma"]], ["Romance"])


class ArchiveTests(LedgerTestCase):
    def view(self, days_ago, as_of):
        rows = [rec("Old", (as_of - timedelta(days=days_ago)).isoformat(),
                    "maintain", 5)]
        states, _ = rr.replay(rows, as_of)
        return rr.state_view(states["Old"], as_of, 70, 40, rr.DEFAULT_MINUTES)

    def test_archive_window_boundary(self):
        self.assertTrue(self.view(181, date(2026, 8, 31))["archived"])
        self.assertFalse(self.view(180, date(2026, 8, 31))["archived"])


class BudgetTests(LedgerTestCase):
    def test_budget_math_underfunded(self):
        rows = [rec("A", "2026-01-01", "learn", 5, 30),
                rec("A", "2026-01-15", "maintain", 5, 20)]
        states, _ = rr.replay(rows, date(2026, 2, 8))
        # h 17.92 -> interval 9.221d; cost 20 -> 15.18 min/wk required
        b = rr.budget_of(states, rows, date(2026, 2, 8), 70)
        self.assertAlmostEqual(b["required"], 15.18, places=1)
        # actual: 20 min inside the 28d window / 4 = 5.0
        self.assertAlmostEqual(b["actual"], 5.0)
        self.assertEqual(b["verdict"], "underfunded")

    def test_budget_holding(self):
        rows = [rec("A", "2026-01-01", "learn", 5, 30),
                rec("A", "2026-01-15", "maintain", 5, 20),
                rec("A", "2026-02-01", "maintain", 5, 40)]
        states, _ = rr.replay(rows, date(2026, 2, 8))
        b = rr.budget_of(states, rows, date(2026, 2, 8), 70)
        self.assertAlmostEqual(b["actual"], 15.0)
        self.assertEqual(b["verdict"], "holding")

    def test_cost_fallback_to_default(self):
        rows = [rec("A", "2026-01-01", "learn", 5, 0)]
        states, _ = rr.replay(rows, date(2026, 2, 8))
        self.assertEqual(rr.touch_cost(states["A"], rr.DEFAULT_MINUTES),
                         rr.DEFAULT_MINUTES)


class GigTests(LedgerTestCase):
    def gig(self, *extra):
        proc = self.run_cli("gig", str(DEMO), "--as-of", AS_OF,
                            "--date", "2026-09-12", *extra)
        return proc

    def test_fresh_today_not_ready_on_the_night(self):
        proc = self.run_cli("gig", str(DEMO), "--as-of", AS_OF,
                            "--date", "2026-09-12", "--format", "json")
        payload = json.loads(proc.stdout)
        by_name = {v["name"]: v for v in payload["ready"] + payload["missed"]}
        firefly = by_name["Firefly"]
        self.assertGreaterEqual(firefly["today_pct"], 70)
        self.assertLess(firefly["night_pct"], 70)
        self.assertFalse(firefly["ready"])

    def test_gate_fail_exit_four(self):
        proc = self.gig("--need", "3", "--must", "Blackbird",
                        "--must", "Fast Car")
        self.assertEqual(proc.returncode, 4)
        self.assertIn("gate: FAIL", proc.stdout)
        self.assertIn("need 3 ready, have 2", proc.stdout)
        self.assertIn('must-have "Fast Car" not ready', proc.stdout)

    def test_gate_pass_exit_zero(self):
        proc = self.gig("--need", "2", "--must", "Blackbird",
                        "--must", "Wish You Were Here")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("gate: PASS", proc.stdout)
        self.assertIn("must-have ok", proc.stdout)

    def test_no_gate_flags_no_gate(self):
        proc = self.gig()
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("gate:", proc.stdout)

    def test_must_unknown_exit_three(self):
        proc = self.gig("--must", "Stairway to Heaven")
        self.assertEqual(proc.returncode, 3)


class PlanTests(LedgerTestCase):
    def ledger(self):
        return self.write([
            {"piece": "Alpha", "date": "2026-08-01", "kind": "maintain",
             "quality": 4, "minutes": 20},          # h 9.1, F 10% RUSTED
            {"piece": "Beta", "date": "2026-08-21", "kind": "maintain",
             "quality": 5, "minutes": 15},          # h 11.2, F 54% RUSTING
            {"piece": "Gamma", "date": "2026-08-24", "kind": "maintain",
             "quality": 5, "minutes": 25},          # h 11.2, F 65% RUSTING
            {"piece": "Delta", "date": "2026-08-05", "kind": "maintain",
             "quality": 4, "minutes": 20},          # h 9.1, F 14% RUSTED
        ])

    def plan(self, minutes, *extra):
        proc = self.run_cli("plan", self.ledger(), "--as-of", AS_OF,
                            "--minutes", str(minutes), "--format", "json",
                            *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_urgency_order_and_greedy_fill(self):
        plan = self.plan(45)
        # Alpha (touch-by oldest) rebuilds for 30, Beta's 15 fits, Gamma 25
        # does not.
        self.assertEqual([s["name"] for s in plan["steps"]], ["Alpha", "Beta"])
        self.assertEqual([s["kind"] for s in plan["steps"]],
                         ["rebuild", "maintain"])
        self.assertEqual((plan["used"], plan["left"]), (45, 0))
        self.assertEqual(plan["blocked"], {"name": "Gamma", "minutes": 25})

    def test_everything_fits(self):
        plan = self.plan(70)
        self.assertEqual([s["name"] for s in plan["steps"]],
                         ["Alpha", "Beta", "Gamma"])
        self.assertEqual(plan["left"], 0)

    def test_one_rebuild_per_sitting(self):
        proc = self.run_cli("plan", self.ledger(), "--as-of", AS_OF,
                            "--minutes", "100", "--format", "json")
        plan = json.loads(proc.stdout)
        rebuilds = [s["name"] for s in plan["steps"] if s["kind"] == "rebuild"]
        self.assertEqual(rebuilds, ["Alpha"])
        self.assertEqual(plan["deferred"], ["Delta"])
        self.assertEqual((plan["used"], plan["left"]), (70, 30))

    def test_perma_rebuild_carries_the_warning(self):
        rows = [rec("Romance", "2026-01-05", "learn", 4),
                rec("Romance", "2026-01-19", "learn", 5),
                rec("Romance", "2026-02-02", "maintain", 5),
                rec("Romance", "2026-02-16", "maintain", 4),
                rec("Romance", "2026-03-02", "maintain", 5),
                rec("Romance", "2026-03-16", "maintain", 4),
                rec("Romance", "2026-04-20", "maintain", 2),
                rec("Romance", "2026-05-11", "learn", 5),
                rec("Romance", "2026-05-25", "maintain", 5),
                rec("Romance", "2026-06-08", "maintain", 5),
                rec("Romance", "2026-06-29", "maintain", 1)]
        states, _ = rr.replay(rows, date(2026, 8, 31))
        plan = rr.build_plan(states, date(2026, 8, 31), 60, 70, 40)
        self.assertTrue(plan["steps"][0]["perma"])

    def test_no_touch_line_skips_polish(self):
        rows = [rec("Pristine", "2026-08-31", "maintain", 5, 10)]
        states, _ = rr.replay(rows, date(2026, 8, 31))
        plan = rr.build_plan(states, date(2026, 8, 31), 45, 70, 40)
        self.assertEqual(plan["steps"], [])
        self.assertEqual(plan["skipped"], ["Pristine"])


class ReportTests(LedgerTestCase):
    def test_future_sessions_ignored_with_note(self):
        rows = [rec("A", "2026-08-01", "maintain", 4),
                rec("A", "2026-09-15", "maintain", 5)]
        states, future = rr.replay(rows, date(2026, 8, 31))
        self.assertEqual(future, 1)
        self.assertEqual(len(states["A"]["trace"]), 1)
        report = rr.build_report(states, future, rows, date(2026, 8, 31),
                                 70, 40, True)
        self.assertEqual(report["future_ignored"], 1)

    def test_ordering_rustiest_first_then_name(self):
        rows = [rec("Zulu", "2026-08-10", "maintain", 4),
                rec("Alpha", "2026-08-10", "maintain", 4),
                rec("Mid", "2026-08-01", "maintain", 4)]
        states, _ = rr.replay(rows, date(2026, 8, 31))
        report = rr.build_report(states, 0, rows, date(2026, 8, 31), 70, 40,
                                 True)
        self.assertEqual([v["name"] for v in report["items"]],
                         ["Mid", "Alpha", "Zulu"])
        self.assertEqual(report["first_to_rust"], "Mid")

    def test_next_to_drop_is_earliest_fresh_touch_by(self):
        rows = [rec("Held", "2026-08-31", "maintain", 5),
                rec("Decay", "2026-08-31", "maintain", 3)]
        states, _ = rr.replay(rows, date(2026, 8, 31))
        report = rr.build_report(states, 0, rows, date(2026, 8, 31), 70, 40,
                                 True)
        self.assertEqual(report["next_to_drop"]["name"], "Decay")


class ShowTests(LedgerTestCase):
    def test_show_trace_and_status(self):
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF, "Romance")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("never stuck (2 collapses)", proc.stdout)
        self.assertIn("← COLLAPSE (ledger said 68%, hands said no)",
                      proc.stdout)

    def test_show_unknown_and_ambiguous(self):
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF, "Nonexistent")
        self.assertEqual(proc.returncode, 3)
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF, "a")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("ambiguous", proc.stderr)

    def test_exact_match_beats_substring_ambiguity(self):
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF,
                            "More Than Words")
        self.assertEqual(proc.returncode, 0)


class CliTests(LedgerTestCase):
    def test_no_args_exit_two(self):
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 2)

    def test_missing_file_exit_three(self):
        proc = self.run_cli("fresh", "/nonexistent/ledger.jsonl")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("error", proc.stderr)

    def test_bad_as_of_exit_three(self):
        proc = self.run_cli("fresh", str(DEMO), "--as-of", "recently")
        self.assertEqual(proc.returncode, 3)

    def test_bad_gig_date_exit_two(self):
        proc = self.run_cli("gig", str(DEMO), "--as-of", AS_OF,
                            "--date", "someday")
        self.assertEqual(proc.returncode, 2)

    def test_line_validation(self):
        proc = self.run_cli("fresh", str(DEMO), "--line", "0")
        self.assertEqual(proc.returncode, 2)
        proc = self.run_cli("fresh", str(DEMO), "--line", "40",
                            "--rebuild-line", "40")
        self.assertEqual(proc.returncode, 2)

    def test_json_formats_parse(self):
        for cmd in (["fresh", str(DEMO)],
                    ["gig", str(DEMO), "--date", "2026-09-12"],
                    ["plan", str(DEMO)],
                    ["show", str(DEMO), "Blackbird"]):
            proc = self.run_cli(*(cmd + ["--as-of", AS_OF, "--format",
                                         "json"]))
            self.assertEqual(proc.returncode, 0, cmd)
            json.loads(proc.stdout)

    def test_as_of_defaults_to_today(self):
        proc = self.run_cli("fresh", str(DEMO))
        self.assertIn("(today)", proc.stdout)


class DogfoodTests(LedgerTestCase):
    def test_examples_sync(self):
        build = subprocess.run(
            [sys.executable, str(PROJECT / "examples" / "build_examples.py"),
             "--check"], capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

    def test_demo_report_headline(self):
        proc = self.run_cli("fresh", str(DEMO), "--as-of", AS_OF)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("underfunded", proc.stdout)
        self.assertIn("never stuck (2 collapses)", proc.stdout)

    def test_demo_gate_snapshot_matches_committed_sample(self):
        sample = (PROJECT / "examples" / "sample-gig.txt").read_text(
            encoding="utf-8")
        self.assertIn("gate: FAIL", sample)
        self.assertIn("need 3 ready, have 2", sample)


if __name__ == "__main__":
    unittest.main()
