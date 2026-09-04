# -*- coding: utf-8 -*-
"""赶考线 · Pace Gap — acceptance tests.

Hand-computed ground truth first (样例数字先手算再钉):
  example ledger: 40 chapters, 13 closed (math 6, english 7),
  remaining 27; as-of 2026-09-05; exam 2026-12-19 -> 105 days.
  proven = 3/28 = 0.1071 (closes 8/12, 8/20, 8/30)
  peak   = 8/28 = 0.2857 (window 2026-03-02..2026-03-29)
  required = 27/105 = 0.2571; multiple = 2.40 -> REDLINE exit 4.
  uniform plan: start 03-02, span 292d, elapsed 187d ->
  planned 40*187/292 = 25.6, lag 12.6.
  minutes: math 2065, english 2745, major 115, politics 0 -> 4925 total.
  shares: english 55.7% time vs 20% weight (TILTED +35.7pp),
  major 2.3% vs 30% (STARVED, 78.3 pts/hour, top of the ranking),
  politics 0 minutes / 20% weight (NEVER).
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
EXAMPLES = os.path.join(PKG, "examples")
SYL = os.path.join(EXAMPLES, "syllabus.tsv")
STUDY = os.path.join(EXAMPLES, "study.tsv")
CLI = os.path.join(PKG, "pace_gap.py")

sys.path.insert(0, PKG)
import pace_gap  # noqa: E402

EXAM = ["--exam-date", "2026-12-19"]


def go(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = pace_gap.main(list(args))
    return code, out.getvalue(), err.getvalue()


def write_ledger(tmp, name, rows, header):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for row in rows:
            fh.write("\t".join(str(c) for c in row) + "\n")
    return path


SYL_HEADER = ["subject", "order", "chapter", "weight"]
STUDY_HEADER = ["date", "subject", "order", "minutes", "status"]


class PaceGapExample(unittest.TestCase):
    """钉值：样例账本上的全部关键读数。"""

    def test_report_coverage_pinned(self):
        code, out, _ = go("report", SYL, STUDY)
        self.assertEqual(code, 0)
        self.assertIn("math          6       1     5"
                      "          12     50.0%", out)
        self.assertIn("english       7       0     3"
                      "          10     70.0%", out)
        self.assertIn("politics      0       0     10         10     0.0%",
                      out)
        self.assertIn("TOTAL         13      -     27         40     32.5%",
                      out)

    def test_report_hours_pinned(self):
        code, out, _ = go("report", SYL, STUDY)
        self.assertEqual(code, 0)
        self.assertIn("34.42", out)   # math 2065 min
        self.assertIn("45.75", out)   # english 2745 min
        self.assertIn("1.92", out)    # major 115 min
        self.assertIn("82.08", out)   # 4925 min
        self.assertIn("last 28d 3, prior 28d 0", out)

    def test_report_uniform_plan_lag_pinned(self):
        code, out, _ = go("report", SYL, STUDY, EXAM[0], EXAM[1])
        self.assertEqual(code, 0)
        self.assertIn("start 2026-03-02 -> exam 2026-12-19 (292 days)",
                      out)
        self.assertIn("elapsed 187 days (64.0% of the plan)", out)
        self.assertIn("should have closed 25.6 chapters", out)
        self.assertIn("lag 12.6 chapters", out)

    def test_report_start_override(self):
        code, out, _ = go("report", SYL, STUDY, "--start", "2026-04-01",
                          "--exam-date", "2026-12-19")
        self.assertEqual(code, 0)
        # span = 262, elapsed = 157 -> 40*157/262 = 23.967 -> 24.0
        self.assertIn("should have closed 24.0 chapters", out)

    def test_report_exam_before_start_is_ledger_error(self):
        code, _, err = go("report", SYL, STUDY, "--exam-date", "2026-01-01")
        self.assertEqual(code, 2)
        self.assertIn("before plan start", err)

    def test_report_basename_only(self):
        code, out, _ = go("report", SYL, STUDY)
        self.assertEqual(code, 0)
        self.assertNotIn(EXAMPLES, out)
        self.assertIn("study.tsv", out)

    def test_pace_pinned_speeds(self):
        code, out, err = go("pace", SYL, STUDY, *EXAM)
        self.assertEqual(code, 4, err)
        self.assertIn("40 total, 13 closed, 27 remaining", out)
        self.assertIn("proven  0.1071 ch/day", out)
        self.assertIn("peak    0.2857 ch/day", out)
        self.assertIn("2026-03-02..2026-03-29: 8 chapters", out)
        self.assertIn("required 0.2571 ch/day", out)
        self.assertIn("27 remaining / 105 days", out)
        self.assertIn("multiple required/proven = 2.40x", out)
        self.assertIn("need 95 more days; the calendar gives 105", out)
        self.assertIn("REDLINE", out)
        self.assertIn("GATE: REDLINE", err)

    def test_pace_no_exam_declines_to_rule(self):
        code, out, _ = go("pace", SYL, STUDY)
        self.assertEqual(code, 0)
        self.assertIn("0.1071", out)
        self.assertIn("0.2857", out)
        self.assertIn("does not invent deadlines", out)
        for word in ("ON-PACE", "STRETCH", "REDLINE", "MATH-DEAD"):
            self.assertNotIn(word, out)

    def test_pace_asof_replay_july_still_red(self):
        code, out, err = go("pace", SYL, STUDY, "--as-of", "2026-07-01",
                            *EXAM)
        self.assertEqual(code, 4, err)
        # at 07-01: closed 10 (5 march math + 5 english), remaining 30,
        # 171 days left -> required 0.1754; proven 0/28; peak 8/28 clears.
        self.assertIn("30 remaining", out)
        self.assertIn("proven  0.0000 ch/day", out)
        self.assertIn("required 0.1754 ch/day", out)
        self.assertIn("REDLINE", out)

    def test_pace_exam_is_today_with_chapters_open_is_math_dead(self):
        code, out, err = go("pace", SYL, STUDY, "--as-of", "2026-12-19",
                            *EXAM)
        self.assertEqual(code, 4, err)
        self.assertIn("required inf ch/day", out)
        self.assertIn("GATE: MATH-DEAD", err)
        self.assertIn("calendar arithmetic", err)

    def test_pace_exam_after_ledger_end_still_math_dead(self):
        # exam already past the last study day: 40 closed? no — 13 closed,
        # exam 2026-09-10 is after as-of 09-05: fine; pick exam before as-of
        # for the ledger-end case
        code, _, err = go("pace", SYL, STUDY, "--exam-date", "2026-08-31")
        self.assertEqual(code, 4, err)
        self.assertIn("MATH-DEAD", err)

    def test_done_ledger_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            syl = write_ledger(tmp, "syl.tsv", [
                ("m", 1, "c1", "10"), ("m", 2, "c2", "10")], SYL_HEADER)
            std = write_ledger(tmp, "study.tsv", [
                ("2026-05-01", "m", 1, "60", "done"),
                ("2026-05-02", "m", 2, "60", "done")], STUDY_HEADER)
            code, out, _ = go("pace", syl, std,
                              "--exam-date", "2026-06-01")
            self.assertEqual(code, 0)
            self.assertIn("DONE", out)
            self.assertNotIn("MATH-DEAD", out)


class PaceGapBoundaries(unittest.TestCase):
    """判级边界：恰 1.0 / 恰 1.5 / 恰 peak / 超 peak，全部合成账本钉死。"""

    @staticmethod
    def build(rows, chapters):
        tmp = tempfile.mkdtemp()
        syl = write_ledger(tmp, "syl.tsv",
                           [("m", i + 1, "c%d" % (i + 1), "10")
                            for i in range(chapters)], SYL_HEADER)
        std = write_ledger(tmp, "study.tsv", rows, STUDY_HEADER)
        return syl, std

    def test_multiple_exactly_one_is_on_pace(self):
        # 3 closes in the trailing 28d (proven = peak = 3/28), 3 left,
        # 28 days -> required 3/28, multiple 1.0 -> ON-PACE exit 0.
        rows = [
            ("2026-04-20", "m", 4, "30", "open"),
            ("2026-05-01", "m", 5, "30", "open"),
            ("2026-05-10", "m", 4, "30", "open"),
            ("2026-05-18", "m", 5, "30", "open"),
            ("2026-05-22", "m", 1, "60", "done"),
            ("2026-05-25", "m", 2, "60", "open"),
            ("2026-05-27", "m", 2, "60", "done"),
            ("2026-05-30", "m", 3, "60", "done"),
            ("2026-06-01", "m", 6, "30", "open"),
        ]
        syl, std = self.build(rows, 6)
        code, out, err = go("pace", syl, std, "--exam-date", "2026-06-29")
        self.assertEqual(code, 0, err)
        self.assertIn("ON-PACE", out)
        self.assertIn("multiple required/proven = 1.00x", out)

    def test_multiple_exactly_stretch_line_is_stretch(self):
        # peak = 3/28 (early burst), proven = 2/28, remaining 3/28d ->
        # multiple exactly 1.5 -> STRETCH exit 0 (boundary, 1e-9 tolerant).
        rows = [
            ("2026-04-12", "m", 1, "60", "done"),
            ("2026-04-17", "m", 2, "60", "done"),
            ("2026-04-22", "m", 3, "60", "done"),
            ("2026-05-01", "m", 6, "30", "open"),
            ("2026-05-10", "m", 7, "30", "open"),
            ("2026-05-18", "m", 8, "30", "open"),
            ("2026-05-22", "m", 4, "60", "done"),
            ("2026-05-27", "m", 5, "60", "done"),
            ("2026-06-01", "m", 6, "30", "open"),
        ]
        syl, std = self.build(rows, 8)
        code, out, err = go("pace", syl, std, "--exam-date", "2026-06-29")
        self.assertEqual(code, 0, err)
        self.assertIn("STRETCH", out)
        self.assertIn("multiple required/proven = 1.50x", out)

    def test_required_equal_peak_is_redline_not_math_dead(self):
        # required 4/28 == peak 4/28 (tolerance) but multiple 4.0 -> REDLINE.
        rows = [
            ("2026-04-12", "m", 1, "60", "done"),
            ("2026-04-17", "m", 2, "60", "done"),
            ("2026-04-22", "m", 3, "60", "done"),
            ("2026-04-27", "m", 4, "60", "done"),
            ("2026-05-08", "m", 6, "30", "open"),
            ("2026-05-15", "m", 7, "30", "open"),
            ("2026-05-22", "m", 5, "60", "done"),
            ("2026-06-01", "m", 8, "30", "open"),
        ]
        syl, std = self.build(rows, 9)
        code, out, err = go("pace", syl, std, "--exam-date", "2026-06-29")
        self.assertEqual(code, 4, err)
        self.assertIn("REDLINE", out)
        self.assertNotIn("MATH-DEAD", out)

    def test_required_above_peak_is_math_dead(self):
        # peak = proven = 3/28 (only three closes ever), remaining 4/28d
        # -> required 4/28 > peak -> MATH-DEAD exit 4.
        rows = [
            ("2026-05-01", "m", 4, "30", "open"),
            ("2026-05-08", "m", 4, "30", "open"),
            ("2026-05-10", "m", 5, "30", "open"),
            ("2026-05-15", "m", 5, "30", "open"),
            ("2026-05-20", "m", 1, "60", "done"),
            ("2026-05-22", "m", 2, "60", "done"),
            ("2026-05-27", "m", 3, "60", "done"),
            ("2026-06-01", "m", 6, "30", "open"),
        ]
        syl, std = self.build(rows, 7)
        code, out, err = go("pace", syl, std, "--exam-date", "2026-06-29")
        self.assertEqual(code, 4, err)
        self.assertIn("MATH-DEAD", out)
        self.assertIn("exceeds your proven peak", out)

    def test_stretch_line_is_tunable(self):
        rows = [
            ("2026-04-12", "m", 1, "60", "done"),
            ("2026-04-17", "m", 2, "60", "done"),
            ("2026-04-22", "m", 3, "60", "done"),
            ("2026-04-27", "m", 4, "60", "done"),
            ("2026-05-08", "m", 6, "30", "open"),
            ("2026-05-15", "m", 7, "30", "open"),
            ("2026-05-22", "m", 5, "60", "done"),
            ("2026-06-01", "m", 8, "30", "open"),
        ]
        syl, std = self.build(rows, 9)
        code, out, err = go("pace", syl, std, "--exam-date", "2026-06-29",
                            "--stretch-line", "5.0")
        self.assertEqual(code, 0, err)
        self.assertIn("STRETCH", out)

    def test_grade_pace_zero_proven_with_peak_is_redline(self):
        grade, multiple = pace_gap.grade_pace(3, 28, 3 / 28.0, 0.0, 3 / 28.0,
                                              1.5)
        self.assertEqual(grade, "REDLINE")
        self.assertEqual(multiple, float("inf"))

    def test_grade_pace_zero_proven_zero_peak_is_math_dead(self):
        grade, _ = pace_gap.grade_pace(3, 28, 3 / 28.0, 0.0, 0.0, 1.5)
        self.assertEqual(grade, "MATH-DEAD")

    def test_grade_pace_remaining_zero_is_done(self):
        grade, _ = pace_gap.grade_pace(0, 28, 0.0, 0.1, 0.2, 1.5)
        self.assertEqual(grade, "DONE")


class PaceGapThin(unittest.TestCase):
    """薄账分层：统计判级拒答 exit 3，纯日历算术再薄也裁决。"""

    THIN_ROWS = [
        ("2026-05-30", "m", 1, "60", "done"),
        ("2026-06-01", "m", 2, "30", "open"),
    ]

    def build(self, rows, chapters=4):
        return PaceGapBoundaries.build(rows, chapters)

    def test_thin_pace_declines(self):
        syl, std = self.build(self.THIN_ROWS)
        code, _, err = go("pace", syl, std, "--exam-date", "2026-07-15")
        self.assertEqual(code, 3, err)
        self.assertIn("too thin", err)

    def test_thin_math_dead_still_rules(self):
        # exam == as-of with chapters open: calendar arithmetic, no mercy
        syl, std = self.build(self.THIN_ROWS)
        code, _, err = go("pace", syl, std, "--exam-date", "2026-06-01")
        self.assertEqual(code, 4, err)
        self.assertIn("MATH-DEAD", err)

    def test_thin_report_still_prints_arithmetic(self):
        syl, std = self.build(self.THIN_ROWS)
        code, out, _ = go("report", syl, std)
        self.assertEqual(code, 0)
        self.assertIn("TOTAL", out)

    def test_thin_simulate_declines(self):
        syl, std = self.build(self.THIN_ROWS)
        code, _, err = go("simulate", syl, std,
                          "--finish-by", "2026-07-15")
        self.assertEqual(code, 3, err)
        self.assertIn("too thin", err)

    def test_six_days_declines_seven_days_rules(self):
        # 3 closes on 6 distinct days -> decline; add a 7th day -> verdict
        rows6 = [
            ("2026-05-01", "m", 1, "60", "done"),
            ("2026-05-02", "m", 2, "60", "done"),
            ("2026-05-03", "m", 3, "60", "done"),
            ("2026-05-04", "m", 4, "30", "open"),
            ("2026-05-05", "m", 4, "30", "open"),
            ("2026-06-01", "m", 5, "30", "open"),
        ]
        syl, std = self.build(rows6, 6)
        code, _, err = go("pace", syl, std, "--exam-date", "2026-06-29")
        self.assertEqual(code, 3, err)
        rows7 = rows6 + [("2026-05-06", "m", 5, "30", "open")]
        syl, std = self.build(rows7, 6)
        code, out, err = go("pace", syl, std, "--exam-date", "2026-06-29")
        self.assertIn(code, (0, 4), err)
        self.assertNotIn("too thin", err)

    def test_min_days_override(self):
        # 3 closes on only 2 distinct days: still declined at the default
        # 7-day floor, but --min-days 2 arms the verdict ->
        # required 3/44 = 0.068 < proven 3/28 = 0.107 -> ON-PACE.
        rows = [
            ("2026-05-30", "m", 1, "60", "done"),
            ("2026-05-30", "m", 2, "60", "done"),
            ("2026-06-01", "m", 3, "60", "done"),
        ]
        syl, std = self.build(rows, 6)
        code, _, err = go("pace", syl, std, "--exam-date", "2026-07-15")
        self.assertEqual(code, 3, err)
        self.assertIn("too thin", err)
        code, out, err = go("pace", syl, std, "--exam-date", "2026-07-15",
                            "--min-days", "2")
        self.assertEqual(code, 0, err)
        self.assertIn("ON-PACE", out)


class PaceGapAllocation(unittest.TestCase):
    """错配账：时长占比 vs 权重占比，每小时期望分。"""

    def test_pinned_table(self):
        code, out, err = go("allocation", SYL, STUDY)
        self.assertEqual(code, 4, err)
        self.assertIn("math          34.42   41.9%   30.0%   +11.9pp",
                      out)
        self.assertIn("english       45.75   55.7%   20.0%   +35.7pp",
                      out)
        self.assertIn("major         1.92    2.3%    30.0%   -27.7pp",
                      out)
        self.assertIn("politics      0.00    0.0%    20.0%   -20.0pp",
                      out)
        self.assertIn("major (78.3 pts/hour)", out)
        self.assertIn("2.3% of your logged time", out)

    def test_three_lights_named(self):
        code, out, err = go("allocation", SYL, STUDY)
        self.assertEqual(code, 4, err)
        self.assertIn("TILTED  english", out)
        self.assertIn("STARVED major", out)
        self.assertIn("NEVER   politics", out)
        self.assertIn("1 tilted, 1 starved, 1 never-started", err)

    def test_no_weights_is_disclosure_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            syl = write_ledger(tmp, "syl.tsv", [
                ("m", 1, "c1", ""), ("m", 2, "c2", ""),
                ("e", 1, "c1", "")], SYL_HEADER)
            std = write_ledger(tmp, "study.tsv", [
                ("2026-05-01", "m", 1, "60", "done"),
                ("2026-05-02", "e", 1, "60", "done")], STUDY_HEADER)
            code, out, _ = go("allocation", syl, std)
            self.assertEqual(code, 0)
            self.assertIn("does not invent exam weights", out)
            self.assertNotIn("TILTED", out)

    def test_partial_weight_scope_is_ledger_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            syl = write_ledger(tmp, "syl.tsv", [
                ("m", 1, "c1", "10"), ("e", 1, "c1", "")], SYL_HEADER)
            std = write_ledger(tmp, "study.tsv", [
                ("2026-05-01", "m", 1, "60", "done")], STUDY_HEADER)
            code, _, err = go("allocation", syl, std)
            self.assertEqual(code, 2)
            self.assertIn("weight scope", err)

    def test_intra_subject_mixed_weights_is_ledger_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            syl = write_ledger(tmp, "syl.tsv", [
                ("m", 1, "c1", "10"), ("m", 2, "c2", ""),
                ("e", 1, "c1", "10")], SYL_HEADER)
            std = write_ledger(tmp, "study.tsv", [
                ("2026-05-01", "m", 1, "60", "done")], STUDY_HEADER)
            code, _, err = go("allocation", syl, std)
            self.assertEqual(code, 2)
            self.assertIn("mixes weighted and unweighted", err)

    def test_tilt_line_tunable_never_still_named(self):
        # 35.7pp english tilt disappears at --tilt-line 0.40;
        # politics (zero minutes) is still NEVER — a blank is always named.
        code, out, err = go("allocation", SYL, STUDY, "--tilt-line", "0.40")
        self.assertEqual(code, 4, err)
        self.assertNotIn("TILTED", out)
        self.assertIn("NEVER   politics", out)
        self.assertIn("0 tilted, 0 starved, 1 never-started", err)

    def test_balanced_ledger_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            syl = write_ledger(tmp, "syl.tsv", [
                ("m", 1, "c1", "50"), ("m", 2, "c2", "50"),
                ("e", 1, "c1", "50"), ("e", 2, "c2", "50")], SYL_HEADER)
            std = write_ledger(tmp, "study.tsv", [
                ("2026-05-01", "m", 1, "60", "done"),
                ("2026-05-02", "m", 2, "60", "done"),
                ("2026-05-03", "e", 1, "60", "done"),
                ("2026-05-04", "e", 2, "60", "done")], STUDY_HEADER)
            code, out, err = go("allocation", syl, std)
            self.assertEqual(code, 0, err)
            self.assertIn("allocation balanced", out)


class PaceGapSimulate(unittest.TestCase):
    def test_rate_before_deadline(self):
        code, out, err = go("simulate", SYL, STUDY, "--rate", "0.3",
                            "--exam-date", "2026-12-19")
        self.assertEqual(code, 0, err)
        self.assertIn("90 days -> 2026-12-04", out)
        self.assertIn("BEFORE the 2026-12-19 deadline by 15 days", out)

    def test_rate_after_deadline(self):
        code, out, err = go("simulate", SYL, STUDY, "--rate", "0.1",
                            "--exam-date", "2026-12-19")
        self.assertEqual(code, 4, err)
        self.assertIn("270 days -> 2027-06-02", out)
        self.assertIn("AFTER the 2026-12-19 deadline by 165 days", out)

    def test_finish_by_matches_pace_verdict(self):
        code, out, err = go("simulate", SYL, STUDY,
                            "--finish-by", "2026-12-19")
        self.assertEqual(code, 4, err)
        self.assertIn("required 0.2571 ch/day", out)
        self.assertIn("REDLINE", out)
        code2, out2, _ = go("pace", SYL, STUDY, *EXAM)
        self.assertEqual(code2, 4)
        self.assertIn("required 0.2571 ch/day", out2)

    def test_no_deadline_prints_date_only(self):
        code, out, _ = go("simulate", SYL, STUDY, "--rate", "0.3")
        self.assertEqual(code, 0)
        self.assertIn("2026-12-04", out)
        self.assertIn("does not invent deadlines", out)

    def test_bad_arguments(self):
        code, _, _ = go("simulate", SYL, STUDY)
        self.assertEqual(code, 2)
        code, _, _ = go("simulate", SYL, STUDY, "--rate", "0.3",
                        "--finish-by", "2026-12-19")
        self.assertEqual(code, 2)
        code, _, _ = go("simulate", SYL, STUDY, "--rate", "0")
        self.assertEqual(code, 2)
        code, _, err = go("simulate", SYL, STUDY,
                          "--finish-by", "2026-01-01")
        self.assertEqual(code, 2)
        self.assertIn("before as-of", err)

    def test_done_remaining_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            syl = write_ledger(tmp, "syl.tsv",
                               [("m", 1, "c1", "10")], SYL_HEADER)
            std = write_ledger(tmp, "study.tsv",
                               [("2026-05-01", "m", 1, "60", "done")],
                               STUDY_HEADER)
            code, out, _ = go("simulate", syl, std, "--rate", "0.5")
            self.assertEqual(code, 0)
            self.assertIn("DONE", out)


class PaceGapValidate(unittest.TestCase):
    def test_example_passes_with_pinned_identity(self):
        code, out, _ = go("validate", SYL, STUDY)
        self.assertEqual(code, 0)
        self.assertIn("closed 13 + opened-only 3 + untouched 24 = 40", out)
        self.assertIn("residual 0", out)
        self.assertIn("residual 0.00", out)
        self.assertIn("weights present, total 500", out)
        self.assertIn("validate: PASS", out)

    def test_ghost_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            syl = write_ledger(tmp, "syl.tsv",
                               [("m", 1, "c1", "10")], SYL_HEADER)
            std = write_ledger(tmp, "study.tsv",
                               [("2026-05-01", "m", 2, "60", "done")],
                               STUDY_HEADER)
            code, _, err = go("validate", syl, std)
            self.assertEqual(code, 2)
            self.assertIn("ghost chapter", err)

    def test_duplicate_syllabus_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            syl = write_ledger(tmp, "syl.tsv",
                               [("m", 1, "c1", "10"), ("m", 1, "c1", "10")],
                               SYL_HEADER)
            std = write_ledger(tmp, "study.tsv",
                               [("2026-05-01", "m", 1, "60", "done")],
                               STUDY_HEADER)
            code, _, err = go("validate", syl, std)
            self.assertEqual(code, 2)
            self.assertIn("duplicate chapter", err)

    def test_bad_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            syl = write_ledger(tmp, "syl.tsv",
                               [("m", 1, "c1", "10")], SYL_HEADER)
            bad_date = write_ledger(tmp, "s1.tsv",
                                    [("2026-05", "m", 1, "60", "done")],
                                    STUDY_HEADER)
            code, _, err = go("validate", syl, bad_date)
            self.assertEqual(code, 2)
            self.assertIn("bad date", err)

            neg = write_ledger(tmp, "s2.tsv",
                               [("2026-05-01", "m", 1, "-5", "done")],
                               STUDY_HEADER)
            code, _, err = go("validate", syl, neg)
            self.assertEqual(code, 2)
            self.assertIn("must be >=", err)

            zero = write_ledger(tmp, "syl2.tsv",
                                [("m", 0, "c1", "10")], SYL_HEADER)
            code, _, err = go("validate", zero, "whatever")
            self.assertEqual(code, 2)
            self.assertIn("order must be >= 1", err)

            status = write_ledger(tmp, "s3.tsv",
                                  [("2026-05-01", "m", 1, "60", "skipped")],
                                  STUDY_HEADER)
            code, _, err = go("validate", syl, status)
            self.assertEqual(code, 2)
            self.assertIn("status must be done|open", err)

    def test_missing_and_empty_files(self):
        code, _, err = go("validate", SYL, os.path.join(EXAMPLES, "nope.tsv"))
        self.assertEqual(code, 2)
        self.assertIn("missing file", err)
        code, _, err = go("validate",
                          os.path.join(EXAMPLES, "nope.tsv"), STUDY)
        self.assertEqual(code, 2)
        code, _, err = go("validate", SYL,
                          write_ledger(tempfile.mkdtemp(), "empty.tsv",
                                       [], STUDY_HEADER))
        self.assertEqual(code, 2)
        self.assertIn("no rows", err)


class PaceGapReproducibility(unittest.TestCase):
    """账本自锚定 + 逐字节可复现 + 零时钟。"""

    def test_byte_identical_reruns(self):
        _, first, _ = go("pace", SYL, STUDY, *EXAM)
        _, second, _ = go("pace", SYL, STUDY, *EXAM)
        self.assertEqual(first, second)

    def test_default_asof_equals_explicit(self):
        _, implicit, _ = go("pace", SYL, STUDY, *EXAM)
        _, explicit, _ = go("pace", SYL, STUDY, "--as-of", "2026-09-05",
                            *EXAM)
        self.assertEqual(implicit, explicit)

    def test_examples_are_byte_stable(self):
        proc = subprocess.run(
            [sys.executable,
             os.path.join(EXAMPLES, "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("byte-identical", proc.stdout)

    def test_no_clock_anywhere(self):
        with open(CLI, encoding="utf-8") as fh:
            source = fh.read()
        for banned in ("date.today", "datetime.now", "time.time",
                       "utcnow"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
