#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance suite for social-jetlag.

Every README acceptance criterion is pinned here. The numeric fixtures are
hand-checkable: an owl whose alarm nights end at 07:10 and whose free
nights drift to 10:40, plus a metronome lark as the aligned control.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # social-jetlag/
EXAMPLES = os.path.join(ROOT, "examples")

sys.path.insert(0, ROOT)
import social_jetlag as sj  # noqa: E402


def run_cli(*argv):
    """Run main() in-process; return (exit_code, stdout, stderr).
    argparse errors raise SystemExit — map it to the exit code."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = sj.main(list(argv))
    except SystemExit as exc:
        code = exc.code
        if code is None:
            code = 0
    return code, out.getvalue(), err.getvalue()


def write_log(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    return path


def owl_week() -> str:
    """21 nights, the mia fixture: 15 work / 6 free, medians hand-checked."""
    rows = ["# comment lines and a header row must be ignored",
            "date\tsleep\twake\tkind"]
    d = ["2026-08-%02d" % day for day in range(17, 32)] + \
        ["2026-09-%02d" % day for day in range(1, 7)]
    kinds = {i: ("work" if (i % 7) < 5 else "free") for i in range(21)}
    for i, day in enumerate(d):
        if kinds[i] == "work":
            if i % 7 == 4:                       # Fridays run late
                rows.append("%s\t01:20\t07:10\twork\tyes" % day)
            elif day == "2026-08-26":            # one late Wednesday
                rows.append("%s\t00:50\t08:10\twork\tyes" % day)
            else:
                rows.append("%s\t00:20\t07:10\twork\tyes" % day)
        else:
            if day == "2026-09-05":
                rows.append("%s\t03:10\t11:20\tfree\tno" % day)
            elif day == "2026-09-06":
                rows.append("%s\t01:40\t09:00\tfree\tno" % day)
            else:
                rows.append("%s\t02:30\t10:40\tfree\tno" % day)
    return "\n".join(rows) + "\n"


def lark_week() -> str:
    rows = []
    d = ["2026-08-%02d" % day for day in range(17, 32)] + \
        ["2026-09-%02d" % day for day in range(1, 7)]
    for i, day in enumerate(d):
        if (i % 7) < 5:
            rows.append("%s\t22:40\t05:50\twork\tyes" % day)
        else:
            rows.append("%s\t22:50\t06:10\tfree\tno" % day)
    return "\n".join(rows) + "\n"


class ClockArithmeticTests(unittest.TestCase):
    def test_parse_hhmm(self):
        self.assertEqual(sj.parse_hhmm("00:00"), 0)
        self.assertEqual(sj.parse_hhmm("07:10"), 430)
        self.assertEqual(sj.parse_hhmm("23:59"), 1439)

    def test_parse_hhmm_rejects_junk(self):
        for bad in ("7:10", "24:00", "07:60", "0710", "07-10", "", "aa:bb"):
            with self.assertRaises(ValueError):
                sj.parse_hhmm(bad)

    def test_fmt_clock_wraps(self):
        self.assertEqual(sj.fmt_clock(245), "04:05")
        self.assertEqual(sj.fmt_clock(366.43), "06:06")
        self.assertEqual(sj.fmt_clock(1440 + 30), "00:30")
        self.assertEqual(sj.fmt_clock(-15), "23:45")

    def test_fmt_dur_and_signed(self):
        self.assertEqual(sj.fmt_dur(410), "6h50m")
        self.assertEqual(sj.fmt_dur(80), "1h20m")
        self.assertEqual(sj.fmt_signed(170), "+2h50m")
        self.assertEqual(sj.fmt_signed(-15), "-0h15m")
        self.assertEqual(sj.fmt_signed(60), "+1h00m")


class NightTests(unittest.TestCase):
    def test_midnight_crossing(self):
        n = sj.Night("2026-01-01", sj.parse_hhmm("00:20"),
                     sj.parse_hhmm("07:10"), "work", 1)
        self.assertEqual(n.duration, 410)
        self.assertEqual(n.midpoint, 225)            # 03:45

    def test_late_evening_bedtime(self):
        n = sj.Night("2026-01-01", sj.parse_hhmm("22:40"),
                     sj.parse_hhmm("05:50"), "work", 1)
        self.assertEqual(n.duration, 430)
        self.assertEqual(n.midpoint, 135)            # 02:15

    def test_noon_to_noon(self):
        n = sj.Night("2026-01-01", sj.parse_hhmm("12:00"),
                     sj.parse_hhmm("00:00"), "free", 1)
        self.assertEqual(n.duration, 720)
        self.assertEqual(n.midpoint, 1080)           # 18:00


class MedianTests(unittest.TestCase):
    def test_odd_and_even(self):
        self.assertEqual(sj.median([3.0]), 3.0)
        self.assertEqual(sj.median([1.0, 3.0]), 2.0)
        self.assertEqual(sj.median([5.0, 1.0, 3.0]), 3.0)
        self.assertEqual(sj.median([4.0, 1.0, 3.0, 2.0]), 2.5)

    def test_median_survives_outliers_mean_does_not(self):
        vals = [410.0] * 11 + [350.0] * 3 + [440.0]
        self.assertEqual(sj.median(vals), 410.0)
        self.assertEqual(sum(vals) / len(vals), 400.0)


class LogParseTests(unittest.TestCase):
    def test_header_comments_optional_column(self):
        path = write_log("# nightly log\n"
                         "date\tsleep\twake\tkind\talarm\n"
                         "2026-01-05\t23:40\t06:50\twork\tyes\n"
                         "\n"
                         "2026-01-10\t01:10\t09:40\tfree\tno\n")
        nights = sj.read_log(path)
        self.assertEqual(len(nights), 2)
        self.assertEqual(nights[0].kind, "work")
        self.assertEqual(nights[1].alarm, "no")

    def test_out_of_order_dates_are_tolerated(self):
        path = write_log("2026-01-10\t01:10\t09:40\tfree\n"
                         "2026-01-05\t23:40\t06:50\twork\n")
        nights = sj.read_log(path)
        self.assertEqual([n.date for n in nights], ["2026-01-10", "2026-01-05"])

    def test_missing_file(self):
        with self.assertRaises(sj.LogError):
            sj.read_log("/nonexistent/nope.tsv")

    def test_empty_log(self):
        path = write_log("# nothing here\n\n")
        with self.assertRaises(sj.LogError) as cm:
            sj.read_log(path)
        self.assertIn("no data rows", str(cm.exception))

    def test_line_numbers_in_errors(self):
        cases = [
            ("2026-01-05\t23:40\t06:50\n", "expected 4 tab-separated"),
            ("2026-01-05\t23:40\t06:50\tnap\n", "kind must be"),
            ("2026-1-5\t23:40\t06:50\twork\n", "bad date"),
            ("2026-01-05\t24:00\t06:50\twork\n", "out-of-range"),
            ("2026-01-05\t07:00\t07:00\twork\n", "same minute"),
            ("2026-01-05\t23:40\t06:50\twork\n"
             "2026-01-05\t23:40\t06:50\twork\n", "duplicate date"),
        ]
        for text, needle in cases:
            path = write_log(text)
            with self.assertRaises(sj.LogError) as cm:
                sj.read_log(path)
            self.assertIn(needle, str(cm.exception))
            self.assertIn("line 1", str(cm.exception))


class MetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = write_log(owl_week())
        cls.nights = sj.read_log(path)
        cls.m = sj.compute_metrics(cls.nights)
        cls.m_mean = sj.compute_metrics(cls.nights, use_mean=True)
        lark = sj.read_log(write_log(lark_week()))
        cls.lark = sj.compute_metrics(lark)

    def test_counts_and_span(self):
        self.assertEqual(self.m.n_work, 15)
        self.assertEqual(self.m.n_free, 6)
        self.assertEqual(self.m.span_days, 21)
        self.assertEqual(self.m.first_date, "2026-08-17")
        self.assertEqual(self.m.last_date, "2026-09-06")

    def test_median_metrics_hand_checked(self):
        self.assertEqual(self.m.sd_work, 410.0)      # 6h50m
        self.assertEqual(self.m.sd_free, 490.0)      # 8h10m
        self.assertEqual(self.m.msw, 225.0)          # 03:45
        self.assertEqual(self.m.msf, 395.0)          # 06:35
        self.assertEqual(self.m.sjl, 170.0)          # +2h50m

    def test_mean_metrics_hand_checked(self):
        self.assertEqual(self.m_mean.sd_work, 400.0)
        self.assertAlmostEqual(self.m_mean.sd_free, 2890 / 6)
        self.assertEqual(self.m_mean.msw, 234.0)     # 03:54
        self.assertAlmostEqual(self.m_mean.msf, 2335 / 6)
        self.assertAlmostEqual(self.m_mean.sjl, 2335 / 6 - 234)

    def test_sjl_identity(self):
        self.assertAlmostEqual(self.m.sjl, self.m.msf - self.m.msw)
        self.assertAlmostEqual(self.m.sjl_sc, self.m.msf_sc - self.m.msw)

    def test_msfsc_correction_direction_and_value(self):
        # sd_week = (410*15 + 490*6)/21 = 432.857; correction = (490-...)/2
        expected_sc = 395.0 - (490.0 - (410 * 15 + 490 * 6) / 21) / 2
        self.assertAlmostEqual(self.m.msf_sc, expected_sc)
        self.assertLess(self.m.msf_sc, self.m.msf)   # pulls the midpoint back
        self.assertAlmostEqual(expected_sc, 366.428571, places=5)  # 06:06

    def test_msfsc_zero_when_no_oversleep(self):
        # lark: free nights only 10 min longer, still positive -> tiny shift
        self.assertLessEqual(self.lark.msf_sc, self.lark.msf)
        # a flat schedule: free = work duration -> no correction at all
        flat = sj.read_log(write_log(
            "2026-01-05\t23:00\t07:00\twork\n"
            "2026-01-10\t01:00\t09:00\tfree\n"))
        m = sj.compute_metrics(flat)
        self.assertAlmostEqual(m.sd_free, m.sd_week)
        self.assertAlmostEqual(m.msf_sc, m.msf)

    def test_sleep_debt_accounts(self):
        self.assertEqual(self.m.bd_day, 80.0)
        self.assertEqual(self.m.work_per_week, 5.0)
        self.assertEqual(self.m.bd_week, 400.0)      # 6h40m
        self.assertEqual(self.m.bd_year, 20800.0)    # 346h40m

    def test_year_annualizes_from_actual_ratio(self):
        # 10 work / 4 free of 14 nights -> 5.0 work nights a week
        rows = ["2026-02-%02d\t23:00\t07:00\twork" % d for d in range(2, 12)]
        rows += ["2026-02-%02d\t01:00\t09:30\tfree" % d for d in range(12, 16)]
        m = sj.compute_metrics(sj.read_log(write_log("\n".join(rows) + "\n")))
        self.assertAlmostEqual(m.work_per_week, 5.0)
        self.assertAlmostEqual(m.bd_week, 150.0)     # 30 * 5

    def test_repay_rate(self):
        # owed = 11*80 + 3*140 + 50 = 1350; paid = 4*80 + 80 + 30 = 430
        self.assertEqual(self.m.repay_owed, 1350.0)
        self.assertEqual(self.m.repay_paid, 430.0)
        self.assertAlmostEqual(self.m.repay_rate, 430 / 1350)
        # lark oversleeps the whole shortfall: 6*10 of 15*10
        self.assertAlmostEqual(self.lark.repay_rate, 0.4)

    def test_repay_rate_na_when_no_debt(self):
        # free nights SHORTER than work nights: nothing owed, nothing repaid
        rows = ["2026-03-%02d\t23:00\t07:00\twork" % d for d in range(2, 12)]
        rows += ["2026-03-%02d\t23:30\t07:00\tfree" % d for d in range(12, 16)]
        m = sj.compute_metrics(sj.read_log(write_log("\n".join(rows) + "\n")))
        self.assertEqual(m.bd_day, 0.0)
        self.assertEqual(m.repay_rate, -1.0)

    def test_negative_sjl_lark(self):
        # work midpoint 02:15, free midpoint 02:20 -> small positive; flip it
        rows = ["2026-04-%02d\t22:00\t06:00\twork" % d for d in range(6, 11)]
        rows += ["2026-04-%02d\t21:00\t05:00\tfree" % d for d in range(11, 13)]
        m = sj.compute_metrics(sj.read_log(write_log("\n".join(rows) + "\n")))
        self.assertEqual(m.msw, sj.parse_hhmm("02:00"))
        self.assertEqual(m.msf, sj.parse_hhmm("01:00"))
        self.assertEqual(m.sjl, -60.0)

    def test_one_sided_log_rejected(self):
        rows = ["2026-01-%02d\t23:00\t07:00\twork" % d for d in range(5, 8)]
        with self.assertRaises(sj.LogError) as cm:
            sj.compute_metrics(sj.read_log(write_log("\n".join(rows) + "\n")))
        self.assertIn("at least one of each", str(cm.exception))


class GradeTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(sj.grade_of(0), "ALIGNED")
        self.assertEqual(sj.grade_of(59.9), "ALIGNED")
        self.assertEqual(sj.grade_of(60), "DRIFTING")
        self.assertEqual(sj.grade_of(119.9), "DRIFTING")
        self.assertEqual(sj.grade_of(120), "HIGH")

    def test_absolute_value(self):
        self.assertEqual(sj.grade_of(-130), "HIGH")
        self.assertEqual(sj.grade_of(-59), "ALIGNED")

    def test_marks(self):
        self.assertEqual(sj.grade_mark("HIGH"), "!!")
        self.assertEqual(sj.grade_mark("DRIFTING"), "~~")
        self.assertEqual(sj.grade_mark("ALIGNED"), "OK")


class WarningsTests(unittest.TestCase):
    def test_small_samples_warn(self):
        path = write_log("2026-01-05\t23:00\t07:00\twork\n"
                         "2026-01-10\t01:00\t09:00\tfree\n")
        m = sj.compute_metrics(sj.read_log(path))
        warns = " ".join(m.warnings())
        self.assertIn("work nights", warns)
        self.assertIn("free nights", warns)
        self.assertIn("spans 6 days", warns)

    def test_full_log_has_no_warnings(self):
        self.assertEqual(self._m().warnings(), [])

    def _m(self):
        return sj.compute_metrics(sj.read_log(write_log(owl_week())))


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nights = sj.read_log(write_log(owl_week()))
        cls.base = sj.compute_metrics(cls.nights)

    def test_flat_keeps_bedtime_drops_duration(self):
        sim = sj.simulate_flat(self.nights, self.base, use_mean=False)
        self.assertEqual(sim.msf, 355.0)             # 05:55, hand-checked
        self.assertEqual(sim.sjl, 130.0)             # +2h10m: phase remains
        self.assertEqual(sim.grade, "HIGH")
        # the point of the counterfactual: less lag than the base
        self.assertLess(sim.sjl, self.base.sjl)

    def test_flat_never_increases_positive_sjl(self):
        sim = sj.simulate_flat(self.nights, self.base, use_mean=False)
        # base free midpoint = sleep + sd_free/2 vs sim = sleep + sd_work/2
        self.assertLessEqual(sim.msf, self.base.msf)

    def test_anchor_shifts_linearly(self):
        sim = sj.simulate_anchor(self.nights, 60, use_mean=False)
        self.assertAlmostEqual(sim.msf, self.base.msf - 60)
        self.assertAlmostEqual(sim.sjl, self.base.sjl - 60)
        late = sj.simulate_anchor(self.nights, -30, use_mean=False)
        self.assertAlmostEqual(late.msf, self.base.msf + 30)
        # durations are untouched by a rigid shift
        self.assertAlmostEqual(sim.sd_free, self.base.sd_free)

    def test_target_reaches_goal(self):
        # |SJL| 170 -> goal 60 needs a 110 min earlier shift; lands at 60
        sim = sj.simulate_anchor(self.nights, 110, use_mean=False)
        self.assertAlmostEqual(sim.sjl, 60.0)
        self.assertEqual(sim.grade, "DRIFTING")      # 60 sits on the line

    def test_target_moves_toward_msw_not_away(self):
        # shifting earlier must pull MSF toward MSW (395 -> 285), never past
        sim = sj.simulate_anchor(self.nights, 110, use_mean=False)
        self.assertAlmostEqual(sim.msf, self.base.msw + 60)


class ReportTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = write_log(owl_week())
        cls.m = sj.compute_metrics(sj.read_log(path))
        cls.text = sj.report_text("owl.tsv", cls.m)

    def test_key_lines(self):
        for needle in (
            "nights logged          : 21  (15 work / 6 free",
            "sleep duration         : work 6h50m · free 8h10m",
            "sleep midpoint         : work 03:45 (MSW) · free 06:35 (MSF)",
            "MSFsc (debt-corrected) : 06:06",
            "social jetlag          : +2h50m   !! HIGH",
            "debt-corrected SJL     : +2h21m   !! HIGH",
            "sleep debt             : 1h20m per work night · 6h40m per week "
            "· 346h40m per year",
            "weekend repay rate     : 32%  (430 repaid of 1350 owed)",
            "warnings               : none",
        ):
            self.assertIn(needle, self.text)

    def test_verdict_speaks_both_accounts(self):
        self.assertIn("fly twice", self.text)
        self.assertIn("not repaying", self.text)

    def test_lark_verdict_points_at_debt(self):
        lark = sj.compute_metrics(sj.read_log(write_log(lark_week())))
        text = sj.report_text("lark.tsv", lark)
        self.assertIn("OK ALIGNED", text)
        self.assertIn("look at the debt account", text)
        self.assertIn("0h10m per work night", text)

    def test_high_repay_verdict_names_the_fare(self):
        # The fare line needs BOTH lag and repayment: 5 identical work
        # nights (480) and 5 free nights (660) with the same bedtime ->
        # SJL +1h30m, owed = paid = 5*180 -> repay 100%.
        rows = ["2026-05-%02d\t23:00\t07:00\twork" % d for d in range(4, 9)]
        rows += ["2026-05-%02d\t23:00\t09:30\tfree" % d for d in range(9, 14)]
        m = sj.compute_metrics(sj.read_log(write_log("\n".join(rows) + "\n")))
        self.assertEqual(m.sjl, 75.0)
        self.assertEqual(m.sd_work, 480.0)
        self.assertEqual(m.sd_free, 630.0)
        self.assertEqual(m.repay_owed, 750.0)
        self.assertEqual(m.repay_paid, 750.0)
        text = sj.report_text("x.tsv", m)
        self.assertIn("does repay the debt (100%)", text)
        self.assertIn("crossing your own time zone twice a week", text)


class JsonTests(unittest.TestCase):
    def test_json_structure_and_values(self):
        path = write_log(owl_week())
        m = sj.compute_metrics(sj.read_log(path))
        doc = json.loads(sj.report_json("owl.tsv", m))
        self.assertEqual(doc["n_work"], 15)
        self.assertEqual(doc["n_free"], 6)
        self.assertAlmostEqual(doc["sjl_min"], 170.0)
        self.assertEqual(doc["grade"], "HIGH")
        self.assertEqual(doc["warnings"], [])
        self.assertIn("verdict", doc)
        self.assertAlmostEqual(doc["msf_sc_min"], 366.428571, places=5)


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owl = write_log(owl_week())
        cls.lark = write_log(lark_week())

    def test_report_exit0_and_text(self):
        code, out, err = run_cli("report", self.owl)
        self.assertEqual(code, sj.EXIT_OK)
        self.assertIn("social jetlag          : +2h50m   !! HIGH", out)

    def test_report_json(self):
        code, out, err = run_cli("report", self.owl, "--format", "json")
        self.assertEqual(code, sj.EXIT_OK)
        self.assertEqual(json.loads(out)["sjl_min"], 170.0)

    def test_report_mean_switch(self):
        code, out, err = run_cli("report", self.owl, "--mean")
        self.assertEqual(code, sj.EXIT_OK)
        self.assertIn("work 6h40m", out)
        self.assertIn("work 03:54 (MSW)", out)

    def test_gate_exit4_and_pass(self):
        code, out, err = run_cli("report", self.owl, "--fail-over", "100")
        self.assertEqual(code, sj.EXIT_GATE)
        self.assertIn("exceeds --fail-over 100m", err)
        code, out, err = run_cli("report", self.owl, "--fail-over", "200")
        self.assertEqual(code, sj.EXIT_OK)

    def test_simulate_scenarios(self):
        code, out, err = run_cli("simulate", self.owl, "flat")
        self.assertEqual(code, sj.EXIT_OK)
        self.assertIn("+2h50m -> +2h10m", out)
        code, out, err = run_cli("simulate", self.owl, "anchor", "60")
        self.assertEqual(code, sj.EXIT_OK)
        self.assertIn("60 min EARLIER", out)
        self.assertIn("+2h50m -> +1h50m", out)
        code, out, err = run_cli("simulate", self.owl, "target", "60")
        self.assertEqual(code, sj.EXIT_OK)
        self.assertIn("110 min EARLIER", out)
        self.assertIn("reached: yes", out)

    def test_target_already_met(self):
        code, out, err = run_cli("simulate", self.owl, "target", "200")
        self.assertEqual(code, sj.EXIT_OK)
        self.assertIn("already at or below target", out)
        self.assertIn("+2h50m -> +2h50m", out)

    def test_anchor_negative_value(self):
        code, out, err = run_cli("simulate", self.owl, "anchor", "-30")
        self.assertEqual(code, sj.EXIT_OK)
        self.assertIn("30 min LATER", out)

    def test_missing_value_exit2(self):
        code, _, err = run_cli("simulate", self.owl, "target")
        self.assertEqual(code, sj.EXIT_USAGE)

    def test_bad_scenario_exit2(self):
        code, _, err = run_cli("simulate", self.owl, "teleport", "60")
        self.assertEqual(code, sj.EXIT_USAGE)

    def test_one_sided_report_exit3(self):
        path = write_log("2026-01-05\t23:00\t07:00\twork\n")
        code, _, err = run_cli("report", path)
        self.assertEqual(code, sj.EXIT_INPUT)

    def test_missing_file_exit3(self):
        code, _, err = run_cli("report", "/nonexistent/log.tsv")
        self.assertEqual(code, sj.EXIT_INPUT)

    def test_bad_line_reports_line_number(self):
        path = write_log("2026-01-05\t23:00\t07:00\twork\n"
                         "2026-01-06\t25:00\t07:00\twork\n")
        code, out, err = run_cli("report", path)
        self.assertEqual(code, sj.EXIT_INPUT)
        self.assertIn("line 2", err)

    def test_validate(self):
        code, out, err = run_cli("validate", self.owl)
        self.assertEqual(code, sj.EXIT_OK)
        self.assertIn("rows parsed           : 21", out)
        self.assertIn("SJL computable        : yes", out)
        code, out, err = run_cli("validate", "/nonexistent/log.tsv")
        self.assertEqual(code, sj.EXIT_INPUT)

    def test_no_subcommand_exit2(self):
        code, _, err = run_cli()
        self.assertEqual(code, sj.EXIT_USAGE)


class ExamplesSyncTests(unittest.TestCase):
    def test_build_examples_check(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(EXAMPLES, "build_examples.py"),
             "--check"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        self.assertIn("in sync", proc.stdout)


class DogfoodTests(unittest.TestCase):
    """The committed example logs must reproduce the committed reports —
    run through the real CLI, not through build_examples."""

    @classmethod
    def setUpClass(cls):
        cls.mia = os.path.join(EXAMPLES, "wooly-week.tsv")
        cls.lark = os.path.join(EXAMPLES, "lark-week.tsv")

    def test_mia_report_matches_pinned_sample(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "social_jetlag.py"),
             "report", "wooly-week.tsv"],
            capture_output=True, text=True, cwd=EXAMPLES, timeout=60)
        self.assertEqual(proc.returncode, 0)
        with open(os.path.join(EXAMPLES, "sample-report-mia.txt")) as fh:
            self.assertEqual(proc.stdout, fh.read())

    def test_lark_report_matches_pinned_sample(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "social_jetlag.py"),
             "report", "lark-week.tsv"],
            capture_output=True, text=True, cwd=EXAMPLES, timeout=60)
        self.assertEqual(proc.returncode, 0)
        with open(os.path.join(EXAMPLES, "sample-report-lark.txt")) as fh:
            self.assertEqual(proc.stdout, fh.read())

    def test_simulations_match_pinned_samples(self):
        for scenario, sample in (
            (("flat"), "sample-simulate-flat.txt"),
            (("target", "60"), "sample-simulate-target.txt"),
        ):
            argv = scenario if isinstance(scenario, tuple) else (scenario,)
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "social_jetlag.py"),
                 "simulate", "wooly-week.tsv", *argv],
                capture_output=True, text=True, cwd=EXAMPLES, timeout=60)
            self.assertEqual(proc.returncode, 0)
            with open(os.path.join(EXAMPLES, sample)) as fh:
                self.assertEqual(proc.stdout, fh.read())

    def test_consistency_numbers_within_bounds(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "social_jetlag.py"),
             "report", "wooly-week.tsv", "--format", "json"],
            capture_output=True, text=True, cwd=EXAMPLES, timeout=60)
        doc = json.loads(proc.stdout)
        self.assertTrue(0 <= abs(doc["sjl_min"]) <= 24 * 60)
        self.assertEqual(doc["grade"], "HIGH")
        self.assertAlmostEqual(doc["sjl_min"],
                               doc["msf_min"] - doc["msw_min"])
        self.assertLessEqual(doc["msf_sc_min"], doc["msf_min"])


if __name__ == "__main__":
    unittest.main()
