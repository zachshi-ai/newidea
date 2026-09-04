# -*- coding: utf-8 -*-
"""Acceptance tests for border-budget · Border Budget.

Every acceptance criterion in README.md is pinned here as a test:
ledger parsing guards, the rolling-window caliper (both entry and
exit days count, window = [D-179, D]), the balance/release schedule,
trip gating with the latest-legal-exit answer, the `when` search,
the all-booked-trips gate, the stay archive with the all-time peak,
the cancel counterfactual, the double-algorithm identity, and exit
codes (2 data / 3 no-honest-answer / 4 over quota).

The demo ledger mirrors examples/: six closed stays plus one booked
autumn trip, pinned to --today 2026-09-06 (used 83/90).
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import border_budget as bb  # noqa: E402

TODAY = "2026-09-06"
HEADER = "entry\texit\tregion\tnote\n"

DEMO_ROWS = [
    ("2026-03-15", "2026-03-22", "spring"),
    ("2026-04-20", "2026-05-03", "clients"),
    ("2026-05-28", "2026-06-10", "early summer"),
    ("2026-07-02", "2026-07-22", "july long stay"),
    ("2026-08-10", "2026-08-30", "august long stay"),
    ("2026-09-01", "2026-09-05", "top-up"),
    ("2026-10-02", "2026-10-15", "booked autumn"),
]


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = bb.main(argv)
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

    def demo(self, name="trips.tsv"):
        rows = "".join("%s\t%s\tschengen\t%s\n" % r for r in DEMO_ROWS)
        return self.write(name, HEADER + rows)

    def ledger(self, rows, name="trips.tsv"):
        return self.write(name, HEADER + "".join(r + "\n" for r in rows))

    def bb_run(self, *argv, **kw):
        today = kw.pop("today", TODAY)
        prefix = ["--today", today] if today is not None else []
        return run_main(prefix + list(argv))


# --------------------------------------------------------------- parsing

class ParsingTest(TmpCase):
    def test_rows_sorted_by_entry(self):
        path = self.ledger(["2026-05-01\t2026-05-10\tschengen\tb",
                            "2026-03-01\t2026-03-05\tschengen\ta"])
        stays = bb.read_ledger(path)
        self.assertEqual([s.note for s in stays], ["a", "b"])

    def test_missing_header_is_data_error(self):
        path = self.write("bad.tsv", "2026-03-01\t2026-03-05\tschengen\ta\n")
        code, _, _ = self.bb_run("balance", path)
        self.assertEqual(code, 2)

    def test_short_row_is_data_error(self):
        path = self.write("bad.tsv", HEADER + "2026-03-01\n")
        code, _, _ = self.bb_run("balance", path)
        self.assertEqual(code, 2)

    def test_bad_date_is_data_error(self):
        path = self.ledger(["2026-02-30\t2026-03-05\tschengen\ta"])
        code, _, _ = self.bb_run("balance", path)
        self.assertEqual(code, 2)

    def test_exit_before_entry_is_data_error(self):
        path = self.ledger(["2026-03-10\t2026-03-05\tschengen\ta"])
        code, _, _ = self.bb_run("balance", path)
        self.assertEqual(code, 2)

    def test_blank_region_defaults_to_schengen(self):
        path = self.write("t.tsv", HEADER + "2026-03-01\t2026-03-05\t\t\n")
        stays = bb.read_ledger(path)
        self.assertEqual(stays[0].region, "schengen")

    def test_region_filter_and_missing_region(self):
        path = self.demo()
        code, _, e = err_of(["--today", TODAY, "balance", path,
                             "--region", "UK"])
        self.assertEqual(code, 2)
        self.assertIn("no stays for region 'uk'", e)
        code, out, _ = self.bb_run("balance", path, "--region", "Schengen")
        self.assertEqual(code, 0)

    def test_missing_file_is_data_error(self):
        code, _, _ = self.bb_run("balance", os.path.join(self.dir, "nope.tsv"))
        self.assertEqual(code, 2)

    def test_comments_and_blank_lines_skipped(self):
        path = self.write("t.tsv", "# note\n\n" + HEADER +
                          "2026-03-01\t2026-03-05\tschengen\ta\n")
        stays = bb.read_ledger(path)
        self.assertEqual(len(stays), 1)


def err_of(argv):
    return run_main(argv)


# -------------------------------------------------------------- window

class WindowMathTest(TmpCase):
    def test_entry_and_exit_days_both_count(self):
        stay = bb.Stay(date(2026, 1, 1), date(2026, 1, 10), "r", "", 0)
        today = date(2026, 1, 10)
        # same calendar span via clipping: 10 days, not 9
        self.assertEqual(bb.stay_days_in_window(stay, date(2026, 1, 1),
                                                date(2026, 1, 10), today), 10)

    def test_window_is_d179_to_d_inclusive(self):
        # one 90-day stay ending today: usage == 90; the day before it
        # started, usage was 0.
        today = date(2026, 9, 6)
        stay = bb.Stay(today - timedelta(days=89), today, "r", "", 0)
        occ = bb.occupied_days([stay], "r", today,
                               today - timedelta(days=365), today)
        self.assertEqual(bb.used_on(today, occ, 180), 90)
        self.assertEqual(bb.used_on(today - timedelta(days=90), occ, 180), 0)

    def test_double_algorithm_identity_on_clean_ledger(self):
        stays = bb.read_ledger(self.demo())
        today = date(2026, 9, 6)
        occ = bb.occupied_days(stays, "schengen", today,
                               today - timedelta(days=365), today)
        a = bb.used_on(today, occ, 180)
        b = bb.used_clipped(today, stays, "schengen", today, 180)
        self.assertEqual(a, 83)
        self.assertEqual(a, b)


# ------------------------------------------------------------- balance

class BalanceTest(TmpCase):
    def test_used_spare_and_walk(self):
        code, out, _ = self.bb_run("balance", self.demo())
        self.assertEqual(code, 0)
        self.assertIn("used 83 of 90 day(s) — spare quota 7 day(s)", out)
        # the window slides: staying from today is possible for 15 days,
        # because March days keep draining out of the window
        self.assertIn("stay at most 15 more day(s)", out)
        self.assertIn("latest exit 2026-09-20", out)

    def test_release_schedule_aggregated(self):
        code, out, _ = self.bb_run("balance", self.demo())
        self.assertIn("2026-09-11 .. 2026-09-18  +1/day", out)
        self.assertIn("spare 15 by the end", out)

    def test_empty_ledger_full_quota(self):
        path = self.write("empty.tsv", HEADER)
        code, out, _ = self.bb_run("balance", path)
        self.assertEqual(code, 0)
        self.assertIn("used 0 of 90 day(s) — spare quota 90 day(s)", out)
        self.assertIn("stay at most 90 more day(s)", out)

    def test_over_quota_ledger_exits_4(self):
        # 95 consecutive days ending today: the ledger records the impossible
        path = self.ledger(["2026-06-04\t2026-09-06\tschengen\ttoo long"])
        code, out, _ = self.bb_run("balance", path)
        self.assertEqual(code, 4)
        self.assertIn("already exceeds the quota", out)

    def test_region_isolation(self):
        # a mixed ledger: two UK visits on top of the schengen demo
        path = self.demo()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("2026-03-20\t2026-03-24\tuk\tlondon\n")
            fh.write("2026-04-01\t2026-04-10\tuk\tedinburgh\n")
        code, out, _ = self.bb_run("balance", path, "--region", "uk")
        self.assertEqual(code, 0)
        self.assertIn("used 15 of 90", out)   # 5 + 10 days, uk window only
        code, out, _ = self.bb_run("balance", path, "--region", "schengen")
        self.assertIn("used 83 of 90", out)   # uk days never touch schengen

    def test_open_stay_counts_to_today_only(self):
        rows = ["2026-06-01\t\tschengen\tstill inside"]
        path = self.ledger(rows)
        code, out, _ = self.bb_run("balance", path, today="2026-07-15")
        self.assertEqual(code, 0)
        self.assertIn("used 45 of 90", out)  # Jun 1..Jul 15 inclusive

    def test_open_stay_over_quota_breathes_with_today(self):
        rows = ["2026-01-01\t\tschengen\tforgotten"]
        path = self.ledger(rows)
        code, out, _ = self.bb_run("balance", path, today="2026-09-06")
        self.assertEqual(code, 4)  # Jan 1..Sep 6 > 180 days: usage counts only
        # window-clipped part (179 days) but open stays cap at today -> 179+1=180?
        # clipped to window [Mar 11..Sep 6]: 180 days inside the window -> > 90


# --------------------------------------------------------------- check

class CheckTest(TmpCase):
    def test_safe_trip_on_the_edge(self):
        # the booked autumn trip, re-audited: 89/90 — one day of margin
        code, out, _ = self.bb_run("check", self.demo(),
                                   "--entry", "2026-10-02", "--exit", "2026-10-15")
        self.assertEqual(code, 0)
        self.assertIn("trip 2026-10-02 .. 2026-10-15 = 14 day(s)", out)
        self.assertIn("peaks 89/90", out)
        self.assertIn("VERDICT: SAFE — 1 day(s) of margin", out)
        self.assertIn("overlaps 1 booked stay(s)", out)  # identical to the booked one

    def test_over_trip_gives_latest_exit(self):
        code, out, _ = self.bb_run("check", self.demo(),
                                   "--entry", "2026-10-02", "--exit", "2026-11-13")
        self.assertEqual(code, 4)
        self.assertIn("peaks 104/90", out)
        self.assertIn("OVER by 14 day(s) on 2026-10-31", out)
        self.assertIn("exit by 2026-10-30 (a 29-day stay still fits)", out)

    def test_one_day_trip_counts_both_dates(self):
        code, out, _ = self.bb_run("check", self.demo(),
                                   "--entry", "2026-10-02", "--exit", "2026-10-02")
        self.assertEqual(code, 0)
        self.assertIn("= 1 day(s)", out)

    def test_overlap_with_booked_trip_disclosed(self):
        code, out, _ = self.bb_run("check", self.demo(),
                                   "--entry", "2026-10-05", "--exit", "2026-10-20")
        self.assertEqual(code, 0)
        self.assertIn("overlaps 1 booked stay(s)", out)
        self.assertIn("shared days count once", out)

    def test_ancient_entry_rejected(self):
        code, _, e = err_of(["--today", TODAY, "check", self.demo(),
                             "--entry", "2020-01-01", "--exit", "2020-01-05"])
        self.assertEqual(code, 2)
        self.assertIn("older than one window", e)


# ---------------------------------------------------------------- when

class WhenTest(TmpCase):
    def test_days_over_quota_is_data_error(self):
        code, _, e = err_of(["--today", TODAY, "when", self.demo(),
                             "--days", "91"])
        self.assertEqual(code, 2)
        self.assertIn("can never fit", e)

    def test_earliest_start_for_thirty_days(self):
        # Nov 29 start breaches at 91 on day 30; Nov 30 slides the July
        # stay out by two days and fits exactly 30 with 89/90.
        code, out, _ = self.bb_run("when", self.demo(), "--days", "30")
        self.assertEqual(code, 0)
        self.assertIn("earliest start: 2026-11-30 -> 2026-12-29", out)
        self.assertIn("85 day(s) of waiting", out)

    def test_when_from_tomorrow(self):
        code, out, _ = self.bb_run("when", self.demo(), "--days", "1")
        self.assertEqual(code, 0)
        self.assertIn("earliest start: 2026-09-06", out)  # can go today

    def test_no_answer_is_thin(self):
        # an 11-day visit every 60 days: a hypothetical 90-day trip can
        # swallow overlapping visits (shared days count once), but its tail
        # window [s-90, s+89] is 180 days wide and always catches at least
        # one visit it did NOT swallow - so 90 fresh days never exist.
        from datetime import timedelta as _td
        base = date(2026, 4, 1)
        rows = []
        for k in range(18):
            e0 = base + _td(days=60 * k)
            e1 = e0 + _td(days=10)
            rows.append("%s\t%s\tschengen\tcycle%d" % (e0.isoformat(), e1.isoformat(), k))
        path = self.ledger(rows)
        code, _, e = err_of(["--today", TODAY, "when", path,
                             "--days", "90"])
        self.assertEqual(code, 3)
        self.assertIn("no start within", e)


# ---------------------------------------------------------------- gate

class GateTest(TmpCase):
    def test_nothing_booked(self):
        rows = [r for r in DEMO_ROWS if r[0] < "2026-09-06"]
        path = self.ledger(["%s\t%s\tschengen\t%s" % r for r in rows])
        code, out, _ = self.bb_run("gate", path)
        self.assertEqual(code, 0)
        self.assertIn("nothing booked ahead", out)

    def test_booked_safe(self):
        code, out, _ = self.bb_run("gate", self.demo())
        self.assertEqual(code, 0)
        self.assertIn("booked trips ahead: 1", out)
        self.assertIn("projected window peak: 89/90", out)
        self.assertIn("VERDICT: SAFE", out)

    def test_booked_breach(self):
        path = self.write("over.tsv", HEADER +
                          "".join("%s\t%s\tschengen\t%s\n" % r
                                  for r in DEMO_ROWS[:-1]) +
                          "2026-10-02\t2026-11-13\tschengen\tgreedy autumn\n")
        code, out, _ = self.bb_run("gate", path)
        self.assertEqual(code, 4)
        self.assertIn("BREACH", out)
        self.assertIn("latest exit 2026-10-30", out)
        self.assertIn("move the entry, cut the days", out)

    def test_custom_window_quota(self):
        code, out, _ = self.bb_run("gate", self.demo(), "--window", "90",
                                   "--quota", "30")
        self.assertEqual(code, 4)  # the autumn trip cannot fit 30/90 either
        self.assertIn("(schengen, 90/30)", out)


# ------------------------------------------------------------- history

class HistoryTest(TmpCase):
    def test_archive_and_peak(self):
        code, out, _ = self.bb_run("history", self.demo())
        self.assertEqual(code, 0)
        self.assertIn("2026-03-15 .. 2026-03-22    8 day(s)", out)
        self.assertIn("2026-08-10 .. 2026-08-30   21 day(s)", out)
        self.assertIn("6 trip(s), 83 day(s) on record", out)
        self.assertIn("all-time window peak: 83/90 on 2026-09-05", out)

    def test_empty_history(self):
        path = self.write("empty.tsv", HEADER)
        code, out, _ = self.bb_run("history", path)
        self.assertEqual(code, 0)
        self.assertIn("window starts empty", out)


# ------------------------------------------------------------ simulate

class SimulateTest(TmpCase):
    def test_cancel_frees_future_peak(self):
        code, out, _ = self.bb_run("simulate", self.demo(), "cancel",
                                   "--match", "autumn")
        self.assertEqual(code, 0)
        self.assertIn("cancelled: 2026-10-02 .. 2026-10-15  booked autumn", out)
        self.assertIn("balance today: 83/90 -> 83/90", out)  # past is untouched
        # the autumn trip is what pushes the projection to 89; without it the
        # window only ever holds the 83 past days
        self.assertIn("projected 365-day peak: 89/90 -> 83/90", out)
        self.assertIn("could stay 15 day(s) instead of 15", out)

    def test_cancel_by_entry_date(self):
        code, out, _ = self.bb_run("simulate", self.demo(), "cancel",
                                   "--match", "2026-10-02")
        self.assertEqual(code, 0)
        self.assertIn("cancelled: 2026-10-02 .. 2026-10-15", out)

    def test_no_match_is_data_error(self):
        code, _, e = err_of(["--today", TODAY, "simulate", self.demo(),
                             "cancel", "--match", "不存在的行程"])
        self.assertEqual(code, 2)
        self.assertIn("no stay matches", e)


# ------------------------------------------------------------ validate

class ValidateTest(TmpCase):
    def test_healthy_ledger_identity(self):
        code, out, _ = self.bb_run("validate", self.demo())
        self.assertEqual(code, 0)
        self.assertIn("stays: 7  (open 0 · future 1)", out)
        self.assertIn("day-by-day == per-stay clipping  ->  83 == 83", out)
        self.assertIn("ledger healthy. exit 0", out)

    def test_overlap_is_data_error(self):
        path = self.ledger(["2026-03-01\t2026-03-10\tschengen\ta",
                            "2026-03-05\t2026-03-20\tschengen\tb"])
        code, out, _ = self.bb_run("validate", path)
        self.assertEqual(code, 2)
        self.assertIn("cannot be inside twice", out)

    def test_open_stay_disclosed(self):
        path = self.ledger(["2026-08-01\t\tschengen\tstill there"])
        code, out, _ = self.bb_run("validate", path)
        self.assertEqual(code, 0)
        self.assertIn("open 1", out)
        self.assertIn("counted up to 2026-09-06 only", out)

    def test_future_counted(self):
        code, out, _ = self.bb_run("validate", self.demo())
        self.assertIn("future 1", out)


# ----------------------------------------------------------- interface

class InterfaceTest(TmpCase):
    def test_version(self):
        with self.assertRaises(SystemExit) as cm:
            run_main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_no_command_prints_help_exit_2(self):
        code, out, e = run_main([])
        self.assertEqual(code, 2)
        self.assertIn("usage:", out + e)

    def test_bad_today_is_data_error(self):
        code, _, _ = run_main(["--today", "not-a-date", "balance", "/dev/null"])
        self.assertEqual(code, 2)

    def test_bad_window_quota(self):
        code, _, _ = self.bb_run("balance", self.demo(), "--window", "0")
        self.assertEqual(code, 2)

    def test_today_pin_changes_answer(self):
        path = self.demo()
        code_a, out_a, _ = self.bb_run("balance", path, today="2026-09-06")
        code_b, out_b, _ = self.bb_run("balance", path, today="2026-10-20")
        self.assertEqual(code_a, 0)
        self.assertEqual(code_b, 0)
        self.assertIn("used 83 of 90", out_a)
        self.assertNotIn("used 83 of 90", out_b)  # window has slid


if __name__ == "__main__":
    unittest.main()
