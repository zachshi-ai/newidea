# -*- coding: utf-8 -*-
"""avalanche acceptance tests — hand-computed figures nailed first.

Every pinned number below was computed by hand from the pinned ledgers
before running the CLI (median = lower median, index (n-1)//2 of the
sorted list). Where the sample ledger is asserted, the figures were
re-derived by an independent script over the TSV, not copied from output.
"""

import atexit
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))
import avalanche as av  # noqa: E402

TMP = tempfile.mkdtemp(prefix="avalanche_tests_")


@atexit.register
def _cleanup():
    shutil.rmtree(TMP, ignore_errors=True)


_counter = [0]


def write_ledger(text, name=None):
    _counter[0] += 1
    name = name or "case%03d.tsv" % _counter[0]
    p = os.path.join(TMP, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def write_leeches(pairs):
    _counter[0] += 1
    p = os.path.join(TMP, "leech%03d.tsv" % _counter[0])
    lines = ["card\tlapses"]
    for card, lapses in pairs:
        lines.append("%s\t%d" % (card, lapses))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return p


def go(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = av.main(args)
    return code, out.getvalue(), err.getvalue()


# ------------------------------------------------------------ hand ledgers

def rows_text(rows):
    lines = ["date\tdue\tdone\tagain\tnew"]
    for r in rows:
        lines.append("\t".join(str(c) for c in r))
    return "\n".join(lines) + "\n"


# U1: 10 rows. carried = [0,0,0,2,0,0,2,6,12,20]
# D=27 C=24 s=+3 line=72 k=18 doom=2026-01-28 AVALANCHE
# fresh=[0,20,25,30,25,25,28,28,28,28]... F=25 structural=-1
#   (hand-check: fresh_i = due_i - carried_{i-1}; lower median idx 4)
#   -> freeze net C-F = -1 -> MATH-DEAD
U1 = rows_text([
    ("2026-01-01", 0, 20, 2, 20),
    ("2026-01-02", 20, 20, 1, 5),
    ("2026-01-03", 25, 25, 2, 5),
    ("2026-01-04", 30, 28, 3, 0),
    ("2026-01-05", 27, 30, 1, 0),
    ("2026-01-06", 25, 25, 2, 0),
    ("2026-01-07", 28, 26, 2, 0),
    ("2026-01-08", 30, 24, 4, 0),
    ("2026-01-09", 34, 22, 5, 0),
    ("2026-01-10", 40, 20, 6, 0),
])

# U2: 7 healthy rows, done > due everywhere -> HARVEST, quota 6
U2 = rows_text([
    ("2026-02-01", 50, 60, 5, 0),
    ("2026-02-02", 55, 60, 4, 0),
    ("2026-02-03", 52, 58, 6, 0),
    ("2026-02-04", 58, 62, 3, 0),
    ("2026-02-05", 54, 60, 5, 0),
    ("2026-02-06", 56, 61, 2, 0),
    ("2026-02-07", 53, 59, 4, 0),
])

# U3: dead flat -> TREADING (spread exactly 0)
U3 = rows_text([("2026-03-0%d" % d, 50, 50, 5, 0) for d in range(1, 8)])

# U4: U1 + one drowning row -> OVERFLOW
U4 = U1.rstrip("\n") + "\n" + "2026-01-11\t500\t20\t7\t0\n"

# U5: k == 42 exactly with --doom-line 50 -> AVALANCHE boundary (inclusive)
U5 = rows_text([("2026-03-0%d" % d, 21, 20, 2, 0) for d in range(1, 7)] +
               [("2026-03-07", 28, 20, 3, 0)])

# U6: thin ledger (6 rows) -> statistics declined
U6 = rows_text([("2026-06-0%d" % d, 30, 25, 3, 0) for d in range(1, 7)])

# U7: one forgiven row (due 10 < carried 20)
U7 = rows_text([
    ("2026-05-01", 40, 20, 2, 0),
    ("2026-05-02", 10, 10, 1, 0),
] + [("2026-05-0%d" % d, 30, 30, 3, 0) for d in range(3, 9)])

# U9: 28 rows -- 8 flat days then 20 days where due grows by +3/day (the
# carried rolls back in: due_i = 33 + 3k, so nothing is forgiven).
# full (window = all 28): D=48 C=30 s=+18, B=60, line=90, k=2 -> AVALANCHE,
#   doom = 2026-04-11 + 2 = 2026-04-13. F=33 structural=+3 -> freeze
#   MATH-DEAD; accelerate x2 net +27 -> 3 review-days, divmod(60,27)=(2,6).
# as-of 2026-03-22 (8 flat rows): D=30 C=30 s=0 -> TREADING
def _u9_rows():
    from datetime import date, timedelta
    d0 = date(2026, 3, 15)
    rows = []
    for i in range(28):
        d = (d0 + timedelta(days=i)).isoformat()
        if i < 8:
            rows.append((d, 30, 30, 3, 0))
        else:
            rows.append((d, 33 + 3 * (i - 8), 30, 4, 0))
    return rows


U9 = rows_text(_u9_rows())

SAMPLE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "examples", "reviews.tsv"))
SAMPLE_LEECH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "examples", "leeches.tsv"))

# the constants above are ledger *text*; the CLI takes paths -- materialize
U4_TEXT = U4
U1 = write_ledger(U1, "u1.tsv")
U2 = write_ledger(U2, "u2.tsv")
U3 = write_ledger(U3, "u3.tsv")
U4 = write_ledger(U4_TEXT, "u4.tsv")
U5 = write_ledger(U5, "u5.tsv")
U6 = write_ledger(U6, "u6.tsv")
U7 = write_ledger(U7, "u7.tsv")
U9 = write_ledger(U9, "u9.tsv")


# ------------------------------------------------------------ parsing

class TestParsing(unittest.TestCase):
    def test_missing_column(self):
        p = write_ledger("date\tdue\tdone\tagain\n2026-01-01\t1\t1\t0\n")
        code, out, err = go(["report", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("header missing column(s): new", err)

    def test_bad_integer(self):
        p = write_ledger("date\tdue\tdone\tagain\tnew\n"
                         "2026-01-01\tx\t1\t0\t0\n")
        code, out, err = go(["report", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("row 1: due is not an integer: 'x'", err)

    def test_negative_value(self):
        p = write_ledger("date\tdue\tdone\tagain\tnew\n"
                         "2026-01-01\t-1\t1\t0\t0\n")
        code, out, err = go(["report", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("due is negative", err)

    def test_again_gt_done(self):
        p = write_ledger("date\tdue\tdone\tagain\tnew\n"
                         "2026-01-01\t1\t2\t3\t0\n")
        code, out, err = go(["report", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("again 3 > done 2", err)

    def test_duplicate_date(self):
        p = write_ledger("date\tdue\tdone\tagain\tnew\n"
                         "2026-01-01\t1\t1\t0\t0\n2026-01-01\t1\t1\t0\t0\n")
        code, out, err = go(["report", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("not strictly after", err)

    def test_bad_calendar_date(self):
        p = write_ledger("date\tdue\tdone\tagain\tnew\n"
                         "2026-02-30\t1\t1\t0\t0\n")
        code, out, err = go(["report", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("not a valid date", err)

    def test_no_header(self):
        p = write_ledger("")
        code, out, err = go(["report", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("no header row found", err)

    def test_missing_file(self):
        code, out, err = go(["report", os.path.join(TMP, "nope.tsv")])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("cannot read ledger", err)

    def test_comments_and_crlf_ok(self):
        p = write_ledger("# a leading comment\r\ndate\tdue\tdone\tagain\tnew\r\n"
                         "2026-01-01\t10\t10\t1\t0\r\n\r\n"
                         "# mid comment\r\n2026-01-02\t10\t10\t1\t0\r\n")
        code, out, _ = go(["report", p])
        self.assertEqual(code, av.EXIT_THIN)  # only 2 rows -> thin, not broken

    def test_leeches_duplicate_card(self):
        p = write_leeches([("a", 3), ("a", 4)])
        code, out, err = go(["leeches", U1, "--leeches", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("duplicate card", err)

    def test_leeches_zero_lapses(self):
        p = write_leeches([("a", 0)])
        code, out, err = go(["leeches", U1, "--leeches", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("lapses must be >= 1", err)


# ------------------------------------------------------------ report verdicts

class TestReport(unittest.TestCase):
    def test_u1_avalanche_pinned(self):
        code, out, _ = go(["report", U1])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("backlog now:", out)
        self.assertIn("20 cards", out)
        self.assertIn("42 card-days", out)
        self.assertIn("due pressure D:", out)
        self.assertIn("27/day", out)
        self.assertIn("capacity C:", out)
        self.assertIn("24/day", out)
        self.assertIn("+3/day", out)
        self.assertIn("fresh inflow F:", out)
        self.assertIn("24/day", out)
        self.assertIn("doom line:", out)
        self.assertIn("72 cards", out)
        self.assertIn("in 18 day(s) -> 2026-01-28", out)
        self.assertIn("verdict: AVALANCHE [exit 4]", out)

    def test_u2_harvest(self):
        code, out, _ = go(["report", U2])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("verdict: HARVEST [exit 0]", out)
        self.assertIn("-6/day", out)
        self.assertIn("paid-ahead rows:", out)
        self.assertIn("7", out)

    def test_u3_treading_zero_spread(self):
        code, out, _ = go(["report", U3])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("verdict: TREADING [exit 0]", out)

    def test_u4_overflow(self):
        code, out, _ = go(["report", U4])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("verdict: OVERFLOW [exit 4]", out)
        self.assertIn("already crossed (still growing +4/day)", out)
        self.assertIn("480 cards", out)

    def test_u5_boundary_day_inclusive(self):
        code, out, _ = go(["report", U5, "--doom-line", "50"])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("in 42 day(s) -> 2026-04-18", out)
        self.assertIn("verdict: AVALANCHE [exit 4]", out)

    def test_u5_boundary_day_beyond(self):
        code, out, _ = go(["report", U5, "--doom-line", "50",
                           "--doom-window", "41"])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("verdict: ACCRUING [exit 0]", out)
        self.assertIn("2026-04-18", out)
        self.assertIn("beyond the 41-day window", out)

    def test_thin_declines_statistics_but_keeps_stock(self):
        code, out, _ = go(["report", U6])
        self.assertEqual(code, av.EXIT_THIN)
        self.assertIn("backlog now:", out)
        self.assertIn("5 cards", out)          # 30 - 25
        self.assertIn("declining:", out)
        self.assertNotIn("verdict:", out)
        self.assertNotIn("due pressure", out)

    def test_forgiven_disclosed_and_excluded_from_fresh(self):
        code, out, _ = go(["report", U7])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("forgiven rows:      1", out)
        self.assertIn("1 forgiven row(s) excluded", out)
        # fresh = [30 x 6] -> F = 30, C = 30, spread 0 -> TREADING
        self.assertIn("verdict: TREADING [exit 0]", out)

    def test_as_of_improves_verdict(self):
        code_full, out_full, _ = go(["report", U9])
        self.assertEqual(code_full, av.EXIT_GATE)
        self.assertIn("verdict: AVALANCHE [exit 4]", out_full)
        self.assertIn("in 2 day(s) -> 2026-04-13", out_full)
        code_past, out_past, _ = go(["report", U9, "--as-of", "2026-03-22"])
        self.assertEqual(code_past, av.EXIT_OK)
        self.assertIn("verdict: TREADING [exit 0]", out_past)
        self.assertIn("rows: 8", out_past)

    def test_as_of_before_first_row(self):
        code, out, _ = go(["report", U1, "--as-of", "2025-12-31"])
        self.assertEqual(code, av.EXIT_THIN)
        self.assertIn("rows: 0", out)

    def test_sparkline_only_block_chars(self):
        code, out, _ = go(["report", U1])
        lines = out.splitlines()
        idx = [i for i, ln in enumerate(lines)
               if ln.startswith("  backlog curve")][0]
        curve = lines[idx + 1].strip()
        self.assertEqual(len(curve), 10)
        for ch in curve:
            self.assertIn(ch, av.BLOCKS)


# ------------------------------------------------------------ add gate

class TestAdd(unittest.TestCase):
    def test_pass_on_exact_quota(self):
        code, out, _ = go(["add", U2, "6"])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("quota:              6 new cards", out)
        self.assertIn("verdict: PASS [exit 0] -- 6 <= quota 6", out)

    def test_leveraged_over_quota(self):
        code, out, _ = go(["add", U2, "7"])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("verdict: LEVERAGED [exit 4] -- 7 > quota 6", out)

    def test_thin_declines(self):
        code, out, _ = go(["add", U6, "3"])
        self.assertEqual(code, av.EXIT_THIN)
        self.assertIn("declining:", out)

    def test_zero_request_on_red_ledger(self):
        # U1: C=24, D=27 -> quota max(0, -3) = 0; requesting 0 still passes
        code, out, _ = go(["add", U1, "0"])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("verdict: PASS [exit 0] -- 0 <= quota 0", out)


# ------------------------------------------------------------ simulate

class TestSimulate(unittest.TestCase):
    def test_healthy_nothing_to_clear(self):
        code, out, _ = go(["simulate", U2])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("verdict: FEASIBLE [exit 0]", out)
        self.assertIn("nothing to clear", out)
        self.assertIn("no crossing", out)

    def test_u1_freeze_math_dead(self):
        code, out, _ = go(["simulate", U1])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("net -1/day -> NEVER clears", out)
        self.assertIn("verdict: MATH-DEAD [exit 4]", out)

    def test_u9_accelerate_clears_with_repayment_check(self):
        code, out, _ = go(["simulate", U9])
        self.assertEqual(code, av.EXIT_GATE)  # as-is doom inside window
        self.assertIn("net +27.0/day -> clears the 60-card backlog in "
                      "3 review-day(s), earliest clear date 2026-04-14", out)
        self.assertIn("repayment check: 2 x 27 + 6 = 60 == backlog", out)

    def test_freeze_inflow_override(self):
        code, out, _ = go(["simulate", U1, "--freeze-inflow", "14"])
        self.assertEqual(code, av.EXIT_GATE)  # as-is still AVALANCHE
        self.assertIn("net +10/day -> clears the 20-card backlog in "
                      "2 review-day(s), earliest clear date 2026-01-12", out)
        self.assertIn("repayment check: 2 x 10 + 0 = 20 == backlog", out)

    def test_sample_gate_red(self):
        code, out, _ = go(["simulate", SAMPLE, "--leeches", SAMPLE_LEECH])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("verdict: GATE RED [exit 4]", out)
        self.assertIn("MATH-DEAD", out)
        self.assertIn("109 review-day(s), earliest clear date 2026-04-17", out)
        self.assertIn("108 x 31 + 4 = 3352 == backlog", out)

    def test_thin_declines(self):
        code, out, _ = go(["simulate", U6])
        self.assertEqual(code, av.EXIT_THIN)

    def test_doom_date_matches_report(self):
        _, rep, _ = go(["report", U9])
        _, sim, _ = go(["simulate", U9])
        self.assertIn("2026-04-13", rep)
        self.assertIn("2026-04-13", sim)


# ------------------------------------------------------------ leeches

U2_LEECH = [("card-a", 10), ("card-b", 9), ("card-c", 6), ("card-d", 4)]


class TestLeeches(unittest.TestCase):
    def test_table_pareto_kill_list(self):
        p = write_leeches(U2_LEECH)
        code, out, _ = go(["leeches", U2, "--leeches", p])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("cards: 4", out)
        self.assertIn("lapses total: 29", out)
        self.assertIn("lapses 29 == again 29 OK", out)
        self.assertIn("top 20% of cards (1) hold 34.5%", out)
        self.assertIn("card-a", out)
        self.assertIn("card-b", out)
        self.assertIn("kill list (lapses >= 8): 2 card(s), 19 lapses "
                      "(65.5% of all forgetting)", out)
        self.assertIn("removes at least 2.7 due/day", out)
        self.assertIn("verdict: KILL-LIST [exit 4]", out)

    def test_clean_with_higher_line(self):
        p = write_leeches(U2_LEECH)
        code, out, _ = go(["leeches", U2, "--leeches", p,
                           "--leech-line", "11"])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("kill list (lapses >= 11): empty", out)
        self.assertIn("verdict: CLEAN [exit 0]", out)

    def test_needs_leeches_file(self):
        code, out, err = go(["leeches", U2])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("needs --leeches", err)

    def test_mismatch_disclosed(self):
        p = write_leeches([("card-a", 1)])
        code, out, _ = go(["leeches", U2, "--leeches", p])
        self.assertEqual(code, av.EXIT_OK)  # census view discloses, validate gates
        self.assertIn("lapses 1 == again 29 MISMATCH", out)

    def test_as_of_parity_not_applicable(self):
        p = write_leeches(U2_LEECH)
        code, out, _ = go(["leeches", U2, "--leeches", p,
                           "--as-of", "2026-02-03"])
        self.assertIn("parity vs ledger: n/a", out)

    def test_sample_kill_list(self):
        code, out, _ = go(["leeches", SAMPLE, "--leeches", SAMPLE_LEECH])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("cards: 2092", out)
        self.assertIn("lapses total: 3313", out)
        self.assertIn("lapses 3313 == again 3313 OK", out)
        self.assertIn("hold 40.5% of all lapses", out)
        self.assertIn("kill list (lapses >= 8): 22 card(s), 192 lapses "
                      "(5.8% of all forgetting)", out)
        self.assertIn("removes at least 6.9 due/day", out)


# ------------------------------------------------------------ validate

class TestValidate(unittest.TestCase):
    def test_clean(self):
        p = write_leeches(U2_LEECH)
        code, out, _ = go(["validate", U2, "--leeches", p])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("verdict: LEDGER OK [exit 0]", out)
        self.assertIn("leech parity: lapses 29 == again 29 .. OK", out)

    def test_parity_broken(self):
        p = write_leeches([("card-a", 1)])
        code, out, err = go(["validate", U2, "--leeches", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("leech parity broken: lapses 1 != again 29", err)

    def test_parity_skipped_under_as_of(self):
        p = write_leeches([("card-a", 1)])
        code, out, _ = go(["validate", U2, "--leeches", p,
                           "--as-of", "2026-02-03"])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("leech parity: skipped", out)

    def test_row_number_in_error(self):
        rows = [("2026-01-0%d" % d, 30, 25, 3, 0) for d in range(1, 10)]
        rows[8] = ("2026-01-09", 34, 22, 30, 0)  # 9th data row: again 30
        p = write_ledger(rows_text(rows))
        code, out, err = go(["validate", p])
        self.assertEqual(code, av.EXIT_BROKEN)
        self.assertIn("row 9 (2026-01-09): again 30 > done 22", err)

    def test_forgiven_row_named(self):
        code, out, _ = go(["validate", U7])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("forgiven rows (due < carried): 1 on 2026-05-02", out)

    def test_sample_ok(self):
        code, out, _ = go(["validate", SAMPLE, "--leeches", SAMPLE_LEECH])
        self.assertEqual(code, av.EXIT_OK)
        self.assertIn("paid-ahead rows (done > due): 1", out)
        self.assertIn("leech parity: lapses 3313 == again 3313 .. OK", out)
        self.assertIn("verdict: LEDGER OK [exit 0]", out)


# ------------------------------------------------------------ sample story

class TestSample(unittest.TestCase):
    def test_report_overflow_pinned(self):
        code, out, _ = go(["report", SAMPLE])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("rows: 117", out)
        self.assertIn("idle days (no rows): 3", out)
        self.assertIn("backlog now:        3352 cards", out)
        self.assertIn("(last day: due 3412 - done 60)", out)
        self.assertIn("171711 card-days", out)
        self.assertIn("2970/day", out)
        self.assertIn("capacity C:         60/day", out)
        self.assertIn("+2910/day", out)
        self.assertIn("fresh inflow F:     89/day", out)
        self.assertIn("structural spread:  +29/day", out)
        self.assertIn("83.8%", out)
        self.assertIn("doom line:          180 cards", out)
        self.assertIn("verdict: OVERFLOW [exit 4]", out)

    def test_as_of_replay(self):
        code, out, _ = go(["report", SAMPLE, "--as-of", "2025-10-05"])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("rows: 35", out)
        self.assertIn("backlog now:        417 cards", out)
        self.assertIn("113/day", out)
        self.assertIn("capacity C:         110/day", out)
        self.assertIn("verdict: OVERFLOW [exit 4]", out)

    def test_add_leveraged(self):
        code, out, _ = go(["add", SAMPLE, "30"])
        self.assertEqual(code, av.EXIT_GATE)
        self.assertIn("quota:              0 new cards", out)
        self.assertIn("recent pipeline:    840 new cards", out)
        self.assertIn("verdict: LEVERAGED [exit 4]", out)


# ------------------------------------------------------------ reproducibility

class TestReproducibility(unittest.TestCase):
    def test_byte_identical_reruns(self):
        _, out1, _ = go(["report", SAMPLE])
        _, out2, _ = go(["report", SAMPLE])
        self.assertEqual(out1, out2)

    def test_explicit_asof_equals_default(self):
        _, out1, _ = go(["report", SAMPLE])
        _, out2, _ = go(["report", SAMPLE, "--as-of", "2025-12-29"])
        self.assertEqual(out1, out2)

    def test_basename_only(self):
        _, out, _ = go(["report", SAMPLE])
        self.assertIn("reviews.tsv", out)
        self.assertNotIn(os.path.dirname(SAMPLE), out)

    def test_no_wall_clock_words(self):
        # the report must not claim anything about "today"
        _, out, _ = go(["report", SAMPLE])
        self.assertNotIn("today is", out.lower())


# ------------------------------------------------------------ properties

class TestProperties(unittest.TestCase):
    def test_project_days(self):
        self.assertEqual(av.project_days(10, 3, 19), 3)
        self.assertEqual(av.project_days(10, 3, 11), 1)
        self.assertIsNone(av.project_days(10, 0, 19))
        self.assertIsNone(av.project_days(10, -3, 19))
        self.assertIsNone(av.project_days(25, 3, 19))  # already over the line

    def test_projection_monotone(self):
        for s in (1, 3, 7, 50):
            for b in (0, 5, 40):
                k1 = av.project_days(b, s, 100)
                k2 = av.project_days(b + 1, s, 100)
                if k1 is not None:
                    self.assertGreaterEqual(k1, k2 if k2 is not None else 0)

    def test_lower_median(self):
        self.assertEqual(av.lower_median([3, 1, 2]), 2)
        self.assertEqual(av.lower_median([4, 1, 2, 3]), 2)
        self.assertEqual(av.lower_median([5]), 5)


if __name__ == "__main__":
    unittest.main()
