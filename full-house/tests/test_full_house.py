# -*- coding: utf-8 -*-
"""Acceptance tests for full-house · Full House.

Every acceptance criterion in README.md is pinned here as a test:
ledger parsing guards, the person-hours first / money-as-translation
discipline, the money identity, week-span and annualization calipers,
recurring series clustering, calendar shape (sandwiches / chains /
clean weekdays), outcome accounting, the cancel counterfactual, the
person-hour gate, and exit codes (2 data / 3 thin / 4 red line).

`--today` is pinned to 2026-08-31 everywhere so the past/scheduled
split — and therefore every assertion — is reproducible.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import full_house as fh  # noqa: E402

TODAY = "2026-08-31"

HEADER = ("date\tstart\tduration_min\tattendees\tsubject\tkind\toutcome\n")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fh.main(argv)
    return code, out.getvalue(), err.getvalue()


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def ledger(self, rows, name="meetings.tsv"):
        return self.write(name, HEADER + "".join(r + "\n" for r in rows))

    @staticmethod
    def row(day, start, minutes, attendees, subject, kind="sync", outcome="none"):
        return "\t".join([day, start, str(minutes), str(attendees),
                          subject, kind, outcome])

    def fh_run(self, *argv, **kw):
        today = kw.pop("today", TODAY)
        prefix = ["--today", today] if today is not None else []
        return run_main(prefix + list(argv))


# --------------------------------------------------------------- parsing

class ParsingTest(TmpCase):
    def test_rows_sorted_by_date_and_start(self):
        path = self.ledger([
            self.row("2026-08-05", "09:00", 30, 2, "b"),
            self.row("2026-08-03", "10:00", 60, 8, "a"),
            self.row("2026-08-05", "08:00", 30, 2, "c"),
        ])
        meetings = fh.read_ledger(path)
        self.assertEqual([m.subject for m in meetings], ["a", "c", "b"])

    def test_missing_header_is_data_error(self):
        path = self.write("bad.tsv", self.row("2026-08-03", "10:00", 60, 8, "a") + "\n")
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_short_row_is_data_error(self):
        path = self.write("bad.tsv", HEADER + "2026-08-03\t10:00\t60\t8\t会\n")
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_bad_date_is_data_error(self):
        path = self.ledger([self.row("2026-13-40", "10:00", 60, 8, "a")])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_bad_start_is_data_error(self):
        path = self.ledger([self.row("2026-08-03", "25:00", 60, 8, "a")])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_zero_duration_is_data_error(self):
        path = self.ledger([self.row("2026-08-03", "10:00", 0, 8, "a")])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_negative_duration_is_data_error(self):
        path = self.ledger([self.row("2026-08-03", "10:00", -5, 8, "a")])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_non_numeric_duration_is_data_error(self):
        path = self.ledger([self.row("2026-08-03", "10:00", "一小时", 8, "a")])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_zero_attendees_is_data_error(self):
        path = self.ledger([self.row("2026-08-03", "10:00", 60, 0, "a")])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_fractional_attendees_is_data_error(self):
        path = self.ledger([self.row("2026-08-03", "10:00", 60, 8.5, "a")])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_empty_subject_is_data_error(self):
        path = self.ledger([self.row("2026-08-03", "10:00", 60, 8, "")])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_unknown_outcome_is_data_error(self):
        path = self.ledger([self.row("2026-08-03", "10:00", 60, 8, "a", outcome="vibes")])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_duplicate_meeting_is_data_error(self):
        row = self.row("2026-08-03", "10:00", 60, 8, "周例会")
        path = self.ledger([row, row])
        code, _, _ = self.fh_run("bill", path)
        self.assertEqual(code, 2)

    def test_same_subject_different_time_is_not_duplicate(self):
        path = self.ledger([
            self.row("2026-08-03", "10:00", 60, 8, "周例会"),
            self.row("2026-08-03", "15:00", 60, 8, "周例会"),
        ] + [self.row("2026-08-0%d" % d, "10:00", 30, 2, "other%d" % d) for d in (4, 5, 6)])
        code, _, _ = self.fh_run("bill", path, "--weekly-cap", "25")
        self.assertEqual(code, 0)

    def test_comments_and_blank_lines_skipped(self):
        path = self.write("ok.tsv", "# a comment\n\n" + HEADER +
                          self.row("2026-08-03", "10:00", 60, 8, "a") + "\n\n")
        code, _, _ = self.fh_run("bill", path, today=None)
        # only one meeting -> thin (exit 3), but parsing must succeed (not 2)
        self.assertEqual(code, 3)

    def test_missing_file_is_data_error(self):
        code, _, _ = self.fh_run("bill", os.path.join(self.dir, "nope.tsv"))
        self.assertEqual(code, 2)

    def test_outcome_defaults_to_none_and_is_disclosed(self):
        # rows written with only 6 columns: the outcome cell is missing
        rows = ["\t".join(["2026-08-0%d" % d, "10:00", "30", "4", "m%d" % d, "sync"])
                for d in range(3, 8)]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("bill", path)
        self.assertEqual(code, 0)
        self.assertIn("defaulted to 'none' on 5 row(s)", out)


# ------------------------------------------------------------------ thin

class ThinLedgerTest(TmpCase):
    def test_below_meeting_floor_refuses_conclusions(self):
        path = self.ledger([self.row("2026-08-03", "10:00", 60, 8, "a"),
                            self.row("2026-08-04", "10:00", 60, 8, "b")])
        code, _, err = self.fh_run("bill", path)
        self.assertEqual(code, 3)
        self.assertIn("below the 5-meeting floor", err)

    def test_unpriced_is_not_thin(self):
        path = self.ledger([self.row("2026-08-0%d" % d, "10:00", 30, 4, "m%d" % d)
                            for d in range(3, 8)])  # 10 person-hours, 1 week
        code, out, _ = self.fh_run("bill", path)
        self.assertEqual(code, 0)
        self.assertIn("unpriced mode", out)
        self.assertNotIn("¥", out)  # unpriced: no money figures at all

    def test_gate_on_empty_ledger_is_thin(self):
        path = self.write("empty.tsv", HEADER)
        code, _, err = self.fh_run("gate", path)
        self.assertEqual(code, 3)
        self.assertIn("empty ledger", err)


# ------------------------------------------------------------------ bill

class BillTest(TmpCase):
    def rows(self):
        return [
            self.row("2026-08-03", "10:00", 60, 8, "周例会", "sync", "action"),      # 8.0 h
            self.row("2026-08-04", "14:00", 90, 6, "评审会", "review", "decision"),  # 9.0 h
            self.row("2026-08-05", "09:30", 15, 5, "站会"),                          # 1.25 h
            self.row("2026-08-06", "15:00", 60, 4, "需求对齐"),                      # 4.0 h
            self.row("2026-08-07", "16:30", 30, 3, "周复盘", "sync", "action"),      # 1.5 h
        ]

    def test_person_hours_and_weekly_average(self):
        path = self.ledger(self.rows())
        code, out, _ = self.fh_run("bill", path, "--weekly-cap", "30")
        self.assertEqual(code, 0)
        self.assertIn("23.8 h total", out)     # 8 + 9 + 1.25 + 4 + 1.5 = 23.75
        self.assertIn("23.8 h/week", out)      # Mon..Sun of one week

    def test_money_at_rate_150(self):
        path = self.ledger(self.rows())
        code, out, _ = self.fh_run("bill", path, "--rate", "150", "--weekly-cap", "30")
        self.assertEqual(code, 0)
        self.assertIn("¥3,562.50 total", out)  # 23.75 * 150
        self.assertIn("annualized ¥185,250.00", out)  # 3562.50 * 52
        self.assertIn("money identity", out)
        self.assertIn("23.75 h × ¥150.00 = ¥3,562.50", out)

    def test_salary_hours_derive_rate(self):
        path = self.ledger(self.rows())
        # 26000 / 173 = 150.289... person-hour
        code, out, _ = self.fh_run("bill", path, "--salary", "26000", "--hours", "173",
                                   "--weekly-cap", "30")
        self.assertEqual(code, 0)
        self.assertIn("¥3,569.36 total", out)  # 23.75 * 150.289017...
        self.assertNotIn("--rate", out)

    def test_rate_and_salary_conflict_is_data_error(self):
        path = self.ledger(self.rows())
        with self.assertRaises(SystemExit) as cm:
            self.fh_run("bill", path, "--rate", "150", "--salary", "26000",
                        "--hours", "173")
        self.assertEqual(cm.exception.code, 2)

    def test_salary_without_hours_is_data_error(self):
        path = self.ledger(self.rows())
        code, _, _ = self.fh_run("bill", path, "--salary", "26000")
        self.assertEqual(code, 2)

    def test_weekly_red_line_exit_4(self):
        path = self.ledger(self.rows())  # 23.75 h in one week > 12 h cap
        code, out, _ = self.fh_run("bill", path, "--rate", "150", "--weekly-cap", "12")
        self.assertEqual(code, 4)
        self.assertIn("RED LINE", out)
        self.assertIn("11.8 h", out)  # 23.75 - 12
        self.assertIn("¥91,650.00/year", out)  # 11.75 * 52 * 150

    def test_weekly_cap_is_adjustable(self):
        path = self.ledger(self.rows())
        code, out, _ = self.fh_run("bill", path, "--weekly-cap", "30")
        self.assertEqual(code, 0)
        self.assertIn("within the 30.0 h cap", out)

    def test_span_caliper_two_weeks(self):
        # Wed 2026-08-05 .. Tue 2026-08-11 spans two Mon..Sun weeks -> 14 days
        rows = [
            self.row("2026-08-05", "10:00", 60, 4, "a"),
            self.row("2026-08-11", "10:00", 60, 4, "b"),
            self.row("2026-08-06", "10:00", 60, 4, "c"),
            self.row("2026-08-07", "10:00", 60, 4, "d"),
            self.row("2026-08-10", "10:00", 60, 4, "e"),
        ]
        path = self.ledger(rows)  # 20 h over 2 weeks = 10 h/week, under cap
        code, out, _ = self.fh_run("bill", path)
        self.assertEqual(code, 0)
        self.assertIn("span 14 days = 2.0 weeks", out)
        self.assertIn("10.0 h/week", out)

    def test_future_rows_skipped_and_disclosed(self):
        rows = self.rows() + [self.row("2026-09-07", "10:00", 60, 8, "future")]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("bill", path, "--weekly-cap", "30")
        self.assertEqual(code, 0)
        self.assertIn("meetings: 5", out)
        self.assertIn("1 scheduled meeting(s)", out)

    def test_zero_rate_rejected(self):
        path = self.ledger(self.rows())
        code, _, _ = self.fh_run("bill", path, "--rate", "0")
        self.assertEqual(code, 2)


# ------------------------------------------------------------------- top

class TopTest(TmpCase):
    def test_ranking_and_truncation(self):
        rows = [
            self.row("2026-08-03", "10:00", 60, 8, "big"),
            self.row("2026-08-04", "10:00", 90, 2, "medium"),
            self.row("2026-08-05", "10:00", 30, 3, "small"),
            self.row("2026-08-06", "10:00", 15, 2, "tiny"),
            self.row("2026-08-07", "10:00", 120, 32, "all-hands", "all-hands"),
        ]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("top", path, "--rate", "100", "-n", "3")
        self.assertEqual(code, 0)
        lines = [l for l in out.splitlines() if l.strip().startswith(("1.", "2.", "3."))]
        self.assertEqual(len(lines), 3)
        self.assertIn("all-hands", lines[0])   # 64.0 h
        self.assertIn("big", lines[1])         # 8.0 h
        self.assertIn("medium", lines[2])      # 3.0 h
        self.assertIn("3.0 h", out)
        self.assertIn("¥6,400.00", lines[0])   # 64 * 100

    def test_concentration_line(self):
        rows = [
            self.row("2026-08-03", "10:00", 60, 8, "a"),
            self.row("2026-08-04", "10:00", 60, 4, "b"),
            self.row("2026-08-05", "10:00", 60, 4, "c"),
            self.row("2026-08-06", "10:00", 60, 4, "d"),
            self.row("2026-08-07", "10:00", 60, 4, "e"),
        ]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("top", path, "-n", "1")
        self.assertEqual(code, 0)
        self.assertIn("33.3% of all rented attention", out)  # 8 / 24


# ------------------------------------------------------------- recurring

class RecurringTest(TmpCase):
    def series_rows(self):
        rows = []
        for week, monday in enumerate(("03", "10", "17", "24")):
            rows.append(self.row("2026-08-%s" % monday, "10:00", 60, 8, "周例会",
                                 "sync", "action"))                      # 8 h each
            rows.append(self.row("2026-08-%s" % monday, "14:00", 90, 6, "评审会",
                                 "review", "decision"))                  # 9 h each
        rows.append(self.row("2026-08-12", "16:00", 30, 3, "临时对齐"))
        return rows

    def test_series_clustered_and_annualized(self):
        path = self.ledger(self.series_rows())
        code, out, _ = self.fh_run("recurring", path, "--rate", "150")
        self.assertEqual(code, 0)
        self.assertIn("· 周例会 — 4 times, median gap 7 day(s), mean 8.0 h/meeting", out)
        self.assertIn("52 meetings/year = 416.0 h = ¥62,400.00", out)
        # empirical: 4 meetings / 4 covered weeks * 52 = 52/year × 8 h × ¥150

    def test_annualized_value_exact(self):
        path = self.ledger(self.series_rows())
        code, out, _ = self.fh_run("recurring", path, "--rate", "150")
        self.assertIn("52 meetings/year", out)
        self.assertIn("416.0 h", out)
        self.assertIn("¥62,400.00", out)  # 4/4 weeks * 52 = 52/yr * 8 h * 150

    def test_one_offs_not_annualized(self):
        path = self.ledger(self.series_rows())
        code, out, _ = self.fh_run("recurring", path)
        self.assertIn("one-off meetings (no repeat observed): 1", out)

    def test_unpriced_annualization_shows_hours_only(self):
        path = self.ledger(self.series_rows())
        code, out, _ = self.fh_run("recurring", path)
        self.assertEqual(code, 0)
        self.assertIn("416.0 h  (unpriced)", out)

    def test_same_day_series_annualization_undefined(self):
        rows = [
            self.row("2026-08-03", "10:00", 60, 4, "同名不同场"),
            self.row("2026-08-03", "15:00", 60, 4, "同名不同场"),
        ] + [self.row("2026-08-0%d" % d, "09:00", 30, 2, "filler%d" % d) for d in (4, 5, 6)]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("recurring", path)
        self.assertEqual(code, 0)
        self.assertIn("annualization undefined (median gap = 0)", out)


# --------------------------------------------------------------- density

class DensityTest(TmpCase):
    def test_busiest_day_and_sandwich_and_chain(self):
        rows = [
            # Tue 08-04: 10:00-11:30 (9h), 11:30-12:00 chain (gap 0), 12:10 sandwich (gap 10)
            self.row("2026-08-04", "10:00", 90, 6, "评审会", "review"),
            self.row("2026-08-04", "11:30", 30, 6, "连轴小会"),
            self.row("2026-08-04", "12:10", 30, 6, "顺便对齐"),
            # Wed 08-05: one small meeting
            self.row("2026-08-05", "10:00", 30, 3, "站会"),
            # Thu 08-06: overlap pair
            self.row("2026-08-06", "10:00", 60, 4, "a会"),
            self.row("2026-08-06", "10:30", 60, 4, "b会"),
        ]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("density", path)
        self.assertEqual(code, 0)
        self.assertIn("2026-08-04 (T)  15.0 h", out)     # 9 + 3 + 3 person-hours
        self.assertIn("meeting sandwiches (gap < 15 min between two meetings): 2", out)
        self.assertIn("评审会 → 连轴小会  (0 min gap)", out)
        self.assertIn("连轴小会 → 顺便对齐  (10 min gap)", out)
        self.assertIn("longest back-to-back chain (gap ≤ 5 min): 2 meetings", out)
        self.assertIn("overlapping meetings on the books: 1", out)

    def test_gap_of_exactly_15_is_not_a_sandwich(self):
        rows = [
            self.row("2026-08-04", "10:00", 30, 4, "a"),
            self.row("2026-08-04", "10:45", 30, 4, "b"),   # gap 15: not a sandwich
            self.row("2026-08-05", "10:00", 30, 3, "c"),
            self.row("2026-08-06", "10:00", 30, 3, "d"),
            self.row("2026-08-07", "10:00", 30, 3, "e"),
        ]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("density", path)
        self.assertEqual(code, 0)
        self.assertIn("meeting sandwiches (gap < 15 min between two meetings): 0", out)

    def test_clean_weekday_share(self):
        rows = [
            self.row("2026-08-03", "10:00", 60, 4, "mon1"),
            self.row("2026-08-10", "10:00", 60, 4, "mon2"),
            self.row("2026-08-17", "10:00", 60, 4, "mon3"),
            self.row("2026-08-04", "10:00", 60, 4, "tue1"),
            self.row("2026-08-11", "10:00", 60, 4, "tue2"),
        ]
        # span: Mon 08-03 .. Sun 08-23 = 21 days -> 15 weekdays, 5 with meetings
        path = self.ledger(rows)
        code, out, _ = self.fh_run("density", path)
        self.assertEqual(code, 0)
        self.assertIn("clean weekdays: 10 of 15 (66.7%) had zero meetings", out)

    def test_weekend_meeting_disclosed(self):
        rows = [
            self.row("2026-08-03", "10:00", 60, 4, "a"),
            self.row("2026-08-04", "10:00", 60, 4, "b"),
            self.row("2026-08-05", "10:00", 60, 4, "c"),
            self.row("2026-08-06", "10:00", 60, 4, "d"),
            self.row("2026-08-08", "10:00", 60, 4, "周六加班会", "sync", "none"),
        ]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("density", path)
        self.assertEqual(code, 0)
        self.assertIn("weekend meetings on record: 1", out)


# --------------------------------------------------------------- outcome

class OutcomeTest(TmpCase):
    def rows(self):
        return [
            self.row("2026-08-03", "10:00", 60, 8, "周例会", "sync", "action"),
            self.row("2026-08-04", "14:00", 90, 6, "评审会", "review", "decision"),
            self.row("2026-08-05", "09:30", 15, 5, "站会", "sync", "none"),
            self.row("2026-08-06", "15:00", 60, 4, "需求对齐", "sync", "none"),
            self.row("2026-08-07", "16:30", 30, 3, "周复盘", "sync", "none"),
        ]

    def test_decision_cost(self):
        path = self.ledger(self.rows())
        code, out, _ = self.fh_run("outcome", path, "--rate", "150")
        self.assertEqual(code, 0)
        self.assertIn("1 decision · 1 action · 3 none", out)
        self.assertIn("23.8 h per decision", out)       # 23.75 / 1
        self.assertIn("(¥3,562.50 each)", out)
        self.assertIn("no-outcome bill: ¥1,012.50 of ¥3,562.50 (28.4%)", out)

    def test_zero_decisions_is_na_not_crash(self):
        rows = [self.row("2026-08-0%d" % d, "10:00", 60, 4, "m%d" % d) for d in range(3, 8)]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("outcome", path)
        self.assertEqual(code, 0)
        self.assertIn("decision cost: n/a", out)
        self.assertIn("refuses to divide by nothing", out)

    def test_by_kind_cross_table(self):
        path = self.ledger(self.rows())
        code, out, _ = self.fh_run("outcome", path)
        self.assertIn("review", out)
        self.assertIn("9.0 h", out)
        self.assertIn("0.0%", out)

    def test_unpriced_outcome_still_reports_hours(self):
        path = self.ledger(self.rows())
        code, out, _ = self.fh_run("outcome", path)
        self.assertEqual(code, 0)
        self.assertIn("23.8 h per decision  (unpriced)", out)
        self.assertNotIn("no-outcome bill", out)


# -------------------------------------------------------------- simulate

class SimulateTest(TmpCase):
    def series(self):
        rows = []
        for monday in ("03", "10", "17", "24"):
            rows.append(self.row("2026-08-%s" % monday, "10:00", 60, 8, "周例会",
                                 "sync", "action"))
        rows.append(self.row("2026-08-04", "10:00", 60, 4, "需求对齐"))
        rows.append(self.row("2026-08-11", "10:00", 60, 4, "需求对齐"))
        rows.append(self.row("2026-08-18", "10:00", 60, 4, "需求对齐"))
        rows.append(self.row("2026-08-25", "10:00", 60, 4, "需求对齐"))
        return rows

    def test_cancel_series_savings(self):
        path = self.ledger(self.series())
        code, out, _ = self.fh_run("simulate", path, "cancel", "--match", "周例会",
                                   "--rate", "150")
        self.assertEqual(code, 0)
        self.assertIn("match '周例会': 4 meeting(s), 32.0 h rented", out)
        # window: Mon 08-03 .. Sun 08-30 = 28 days = 4 weeks; total 48 h
        self.assertIn("weekly load: 12.0 h → 4.0 h  (−8.0 h/week)", out)
        self.assertIn("annualized saving: 416.0 h", out)      # 8.0 * 52
        self.assertIn("annualized saving: ¥62,400.00", out)   # 416 * 150
        self.assertIn("66.7% of the total bill", out)

    def test_every_two_halves_the_saving(self):
        path = self.ledger(self.series())
        code, out, _ = self.fh_run("simulate", path, "cancel", "--match", "周例会",
                                   "--every", "2", "--rate", "150")
        self.assertEqual(code, 0)
        self.assertIn("you keep 50.0% of the series", out)
        self.assertIn("annualized saving: ¥31,200.00", out)

    def test_no_match_is_data_error(self):
        path = self.ledger(self.series())
        code, _, err = self.fh_run("simulate", path, "cancel", "--match", "不存在的会")
        self.assertEqual(code, 2)
        self.assertIn("no past meeting subject matches", err)

    def test_unpriced_simulate_shows_hours(self):
        path = self.ledger(self.series())
        code, out, _ = self.fh_run("simulate", path, "cancel", "--match", "周例会")
        self.assertEqual(code, 0)
        self.assertIn("annualized saving: 416.0 h", out)
        self.assertIn("(unpriced: add --rate to see the money)", out)


# ------------------------------------------------------------------ gate

class GateTest(TmpCase):
    def test_all_clear_exit_0(self):
        rows = [self.row(day, "10:00", 60, 4, name) for day, name in
                (("2026-08-03", "m1"), ("2026-08-04", "m2"), ("2026-08-10", "m3"),
                 ("2026-08-11", "m4"), ("2026-08-12", "m5"))]  # 20 h / 2 weeks = 10 h/wk
        path = self.ledger(rows + [self.row("2026-09-02", "10:00", 60, 4, "planned")])
        code, out, _ = self.fh_run("gate", path)
        self.assertEqual(code, 0)
        self.assertIn("VERDICT: PASS", out)
        self.assertIn("scheduled ahead: 1 meeting(s)", out)

    def test_single_cap_breach_on_scheduled_all_hands(self):
        rows = [self.row(day, "10:00", 60, 4, name) for day, name in
                (("2026-08-03", "m1"), ("2026-08-04", "m2"), ("2026-08-10", "m3"),
                 ("2026-08-11", "m4"), ("2026-08-12", "m5"))]  # 10 h/wk: only single cap fires
        path = self.ledger(rows + [self.row("2026-09-07", "10:00", 90, 32,
                                            "全员会", "all-hands")])  # 48 h
        code, out, _ = self.fh_run("gate", path, "--rate", "150")
        self.assertEqual(code, 4)
        self.assertIn("rents 48.0 h in one room, over the 16.0 h single cap", out)
        self.assertIn("VERDICT: 1 breach(es). exit 4", out)

    def test_weekly_cap_breach(self):
        rows = [self.row("2026-08-0%d" % d, "10:00", 60, 10, "m%d" % d)
                for d in range(3, 8)]  # 50 h in one week
        path = self.ledger(rows)
        code, out, _ = self.fh_run("gate", path)
        self.assertEqual(code, 4)
        self.assertIn("weekly average 50.0 h/week over the 40.0 h cap", out)

    def test_caps_are_adjustable(self):
        rows = [self.row("2026-08-0%d" % d, "10:00", 60, 8, "m%d" % d)
                for d in range(3, 8)]
        path = self.ledger(rows + [self.row("2026-09-07", "10:00", 120, 10, "大屋会")])
        code, out, _ = self.fh_run("gate", path, "--weekly-cap", "50",
                                   "--single-cap", "25")
        self.assertEqual(code, 0)
        self.assertIn("caps: 50.0 h/week · 25.0 h/single meeting", out)

    def test_gate_audits_future_only_for_single_cap(self):
        # a huge meeting in the PAST must not trigger the single cap:
        # the gate prices the schedule ahead, history is reported by bill.
        rows = [self.row(day, "10:00", 60, 4, name) for day, name in
                (("2026-08-03", "m1"), ("2026-08-04", "m2"), ("2026-08-10", "m3"),
                 ("2026-08-11", "m4"), ("2026-08-12", "m5"))]
        rows.append(self.row("2026-08-06", "14:00", 90, 32, "过去的全员会", "all-hands"))
        # total 60 h over 2 weeks = 30 h/week: under the weekly cap
        path = self.ledger(rows)
        # 20+48=68 h over 2 weeks = 34 h/week: under the weekly cap, and the
        # past 48-hour meeting must NOT trip the single cap — gate prices the
        # schedule ahead; history belongs to `bill` and `top`.
        code, out, _ = self.fh_run("gate", path)
        self.assertEqual(code, 0)
        self.assertIn("VERDICT: PASS", out)
        self.assertNotIn("single cap", out)


# -------------------------------------------------------------- validate

class ValidateTest(TmpCase):
    def test_healthy_ledger(self):
        rows = [self.row("2026-08-0%d" % d, "10:00", 60, 4, "m%d" % d)
                for d in range(3, 8)]
        path = self.ledger(rows)
        code, out, _ = self.fh_run("validate", path)
        self.assertEqual(code, 0)
        self.assertIn("rows: 5  (past 5 · scheduled 0)", out)
        self.assertIn("person-hours identity", out)
        self.assertIn("ledger healthy. exit 0", out)

    def test_money_identity_drift_below_tolerance(self):
        rows = [self.row("2026-08-0%d" % d, "%02d:00" % (7 + d), 41, 7, "m%d" % d)
                for d in range(3, 8)]  # ugly minutes on purpose
        path = self.ledger(rows)
        code, out, _ = self.fh_run("validate", path, "--rate", "150")
        self.assertEqual(code, 0)
        self.assertIn("money identity", out)
        import re
        match = re.search(r"drift ([\d.e+-]+)\)", out)
        self.assertIsNotNone(match)
        self.assertLess(float(match.group(1)), 1e-6)

    def test_future_rows_disclosed(self):
        rows = [self.row("2026-08-0%d" % d, "10:00", 60, 4, "m%d" % d)
                for d in range(3, 8)]
        path = self.ledger(rows + [self.row("2026-09-15", "10:00", 60, 4, "排期中")])
        code, out, _ = self.fh_run("validate", path)
        self.assertEqual(code, 0)
        self.assertIn("rows: 6  (past 5 · scheduled 1)", out)
        self.assertIn("gate audits them", out)

    def test_thin_ledger_flagged(self):
        path = self.ledger([self.row("2026-08-03", "10:00", 60, 4, "a")])
        code, out, _ = self.fh_run("validate", path)
        self.assertEqual(code, 0)  # validate itself is a health check, not a verdict
        self.assertIn("THIN: 1 past meeting(s) < 5", out)


# ------------------------------------------------------------- interface

class InterfaceTest(TmpCase):
    def test_version(self):
        with self.assertRaises(SystemExit) as cm:
            run_main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_no_command_prints_help_exit_2(self):
        code, out, err = run_main([])
        self.assertEqual(code, 2)
        self.assertIn("usage:", out + err)

    def test_bad_today_is_data_error(self):
        code, _, _ = run_main(["--today", "not-a-date", "bill", "/dev/null"])
        self.assertEqual(code, 2)

    def test_today_pin_changes_past_future_split(self):
        rows = [self.row("2026-08-0%d" % d, "10:00", 60, 4, "m%d" % d)
                for d in range(3, 8)]
        rows.append(self.row("2026-09-07", "10:00", 60, 4, "planned"))
        path = self.ledger(rows)
        code_before, out_before, _ = self.fh_run("bill", path, "--weekly-cap", "30")  # today = 08-31
        code_after, out_after, _ = self.fh_run("bill", path, today="2026-09-30",
                                                weekly_cap="30")
        self.assertEqual(code_before, 0)
        self.assertEqual(code_after, 0)
        self.assertIn("meetings: 5", out_before)
        self.assertIn("meetings: 6", out_after)


if __name__ == "__main__":
    unittest.main()
