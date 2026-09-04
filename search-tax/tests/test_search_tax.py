# -*- coding: utf-8 -*-
"""Acceptance tests for search-tax · Search Tax.

Every acceptance criterion in README.md is pinned here as a test:
event-stream parsing guards (per-event field discipline, exact
duplicates), the minutes-first / money-as-translation discipline, the
ledger-week caliper (first Monday -> last Sunday, inclusive), the
annualized search tax, repeat-offender gating (exit 4), the
duplicate-buy confirmation audit, fixed-home prescriptions and fix
reviews (per-observed-day rates), the ledger-measured cure rate in
`simulate` (no invented numbers), identity checks, and exit codes
(2 data / 3 thin / 4 red line).

Toy ledgers are hand-computed: the demo-shaped two-week ledger has
35 hunt-minutes across 9 searches, weekly 17.5, annualized 910 min;
钥匙's four hunts (19 min, avg 4.75) annualize to 77 min/yr at the
90-day window. Every asserted number is derived by hand first.
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import search_tax as st  # noqa: E402

HEADER = "date\tevent\titem\tminutes\tplace\tamount\tnote\n"

# Two ledger weeks (2026-07-27 Mon -> 2026-08-09 Sun), hand-computed:
# 9 searches / 35 minutes; 钥匙 x4 (19 min), 剪刀 x3 (6 min), 4 singletons.
TOY_A = [
    ("2026-07-27", "search", "钥匙", "5", "沙发缝", "", ""),
    ("2026-07-29", "search", "钥匙", "8", "外套口袋", "", ""),
    ("2026-07-30", "buy", "剪刀", "", "", "19.9", "找不到就下单了"),
    ("2026-07-31", "search", "剪刀", "3", "抽屉", "", ""),
    ("2026-08-01", "fix", "门禁卡", "", "玄关托盘", "", ""),
    ("2026-08-02", "search", "钥匙", "2", "沙发缝", "", ""),
    ("2026-08-03", "search", "保温杯", "4", "-", "", ""),
    ("2026-08-04", "search", "剪刀", "1", "抽屉", "", ""),
    ("2026-08-05", "buy", "门禁卡", "", "", "30", "补办"),
    ("2026-08-06", "search", "雨伞", "6", "玄关", "", ""),
    ("2026-08-08", "search", "剪刀", "2", "文具盒", "", ""),
    ("2026-08-09", "search", "钥匙", "4", "玄关碗", "", ""),
]


def ledger_text(rows):
    return HEADER + "".join("\t".join(r) + "\n" for r in rows)


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = st.main(argv)
    return code, out.getvalue(), err.getvalue()


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "ledger.tsv")

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.path

    def toy(self, rows):
        return self.write(ledger_text(rows))


class ParsingGuards(TmpCase):
    """Acceptance 1: event-stream parsing discipline — all exit 2."""

    def test_valid_ledger_with_and_without_note(self):
        rows = st.parse_ledger(self.toy(TOY_A))
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["item"], "钥匙")
        self.assertEqual(rows[-1]["note"], "")

    def test_missing_header(self):
        code, _, err = run_main(
            ["report", self.write("2026-08-01\tsearch\t钥匙\t5\t沙发缝\t\t\n")])
        self.assertEqual(code, 2)
        self.assertIn("header", err)

    def test_column_count(self):
        for line in ("2026-08-01\tsearch\t钥匙\t5\t沙发缝\n",
                     "2026-08-01\tsearch\t钥匙\t5\t沙发缝\t\tnote\textra\n"):
            code, _, err = run_main(["report", self.write(HEADER + line)])
            self.assertEqual(code, 2)
            self.assertIn("columns", err)

    def test_bad_date(self):
        code, _, err = run_main(
            ["report", self.write(HEADER + "2026-02-30\tsearch\t钥匙\t5\t沙发缝\t\t\n")])
        self.assertEqual(code, 2)
        self.assertIn("bad date", err)

    def test_bad_event(self):
        code, _, _ = run_main(
            ["report", self.write(HEADER + "2026-08-01\tsteal\t钥匙\t5\t\t\t\n")])
        self.assertEqual(code, 2)

    def test_empty_item(self):
        code, _, _ = run_main(
            ["report", self.write(HEADER + "2026-08-01\tsearch\t\t5\t沙发缝\t\t\n")])
        self.assertEqual(code, 2)

    def test_search_needs_positive_integer_minutes(self):
        for minutes in ("", "0", "-3", "abc", "2.5"):
            code, _, _ = run_main(
                ["report", self.write(HEADER +
                 "2026-08-01\tsearch\t钥匙\t%s\t沙发缝\t\t\n" % minutes)])
            self.assertEqual(code, 2, "minutes=%r should reject" % minutes)

    def test_search_must_not_carry_amount(self):
        code, _, err = run_main(
            ["report", self.write(HEADER +
             "2026-08-01\tsearch\t钥匙\t5\t沙发缝\t9.9\t\n")])
        self.assertEqual(code, 2)
        self.assertIn("amount", err)

    def test_buy_needs_amount_and_only_amount(self):
        bad = [
            "2026-08-01\tbuy\t剪刀\t\t\t0\t\n",      # amount <= 0
            "2026-08-01\tbuy\t剪刀\t\t\t\t\n",      # amount missing
            "2026-08-01\tbuy\t剪刀\t5\t\t19.9\t\n",  # stray minutes
            "2026-08-01\tbuy\t剪刀\t\t玄关\t19.9\t\n",  # stray place
        ]
        for line in bad:
            code, _, _ = run_main(["report", self.write(HEADER + line)])
            self.assertEqual(code, 2, line.strip())

    def test_fix_needs_place_and_no_numbers(self):
        bad = [
            "2026-08-01\tfix\t门禁卡\t\t\t\t\n",       # place missing
            "2026-08-01\tfix\t门禁卡\t5\t玄关\t\t\n",   # stray minutes
            "2026-08-01\tfix\t门禁卡\t\t玄关\t30\t\n",  # stray amount
        ]
        for line in bad:
            code, _, _ = run_main(["report", self.write(HEADER + line)])
            self.assertEqual(code, 2, line.strip())

    def test_exact_duplicate_row_rejected(self):
        row = "2026-08-01\tsearch\t钥匙\t5\t沙发缝\t\t\n"
        code, _, err = run_main(["report", self.write(HEADER + row + row)])
        self.assertEqual(code, 2)
        self.assertIn("duplicate", err)

    def test_comments_and_blank_lines_skipped(self):
        text = HEADER + "# a comment\n\n" + "\t".join(TOY_A[0]) + "\n"
        self.assertEqual(len(st.parse_ledger(self.write(text))), 1)

    def test_placeholder_marks_never_found(self):
        rows = st.parse_ledger(self.toy(TOY_A))
        cup = [r for r in rows if r["item"] == "保温杯"][0]
        self.assertEqual(cup["place"], "")

    def test_rows_sorted_by_date(self):
        rows = st.parse_ledger(self.toy(list(reversed(TOY_A))))
        dates = [r["date"] for r in rows]
        self.assertEqual(dates, sorted(dates))


class SearchTaxCaliper(TmpCase):
    """Acceptance 2: ledger-week caliper, the annualized tax, honesty clauses."""

    def setUp(self):
        super().setUp()
        self.path = self.toy(TOY_A)
        self.code, self.out, _ = run_main(["report", self.path])

    def test_report_ok(self):
        self.assertEqual(self.code, 0)

    def test_ledger_weeks_inclusive(self):
        # first Monday 07-27 -> last Sunday 08-09: exactly 2 ledger weeks
        stats = st.Stats(st.parse_ledger(self.path))
        self.assertEqual(stats.weeks, 2.0)
        self.assertIn("14 days, 2 ledger weeks", self.out)

    def test_annualized_tax_hand_pinned(self):
        # 35 min / 2 weeks = 17.5 min/week; x52 = 910 min = 15.2 h
        self.assertIn("hunt time: 35 min total | 17.5 min/week", self.out)
        self.assertIn("annualized 910 min = 15.2 h/yr", self.out)

    def test_most_hunted_order_with_name_tiebreak(self):
        # by minutes desc, name asc on ties: 钥匙 19, 剪刀 6, 雨伞 6, 保温杯 4
        section = self.out.split("most hunted (by minutes):\n")[1].split("\n")
        self.assertIn("钥匙", section[0])
        self.assertIn("剪刀", section[1])
        self.assertIn("雨伞", section[2])

    def test_place_histogram_counts_found_only(self):
        section = self.out.split("where they turn up (found-in-place counts):\n")[1]
        self.assertIn("x2", section)          # 沙发缝 x2, 抽屉 x2
        self.assertNotIn("保温杯", section)    # never found -> no place to count

    def test_duplicate_buy_line_and_unpriced_note(self):
        self.assertIn("duplicate buys: 2 rows, 49.90 total", self.out)
        self.assertIn("NOTE unpriced", self.out)
        self.assertNotIn("/yr + duplicate buys", self.out)

    def test_wage_translation(self):
        # 910 min at 40/h = 606.67; + 49.90 duplicate buys = 656.57
        code, out, _ = run_main(["report", self.path, "--wage", "40"])
        self.assertEqual(code, 0)
        self.assertIn(
            "at 40.00/h: search tax 606.67/yr + duplicate buys 49.90 = 656.57/yr", out)
        self.assertNotIn("NOTE unpriced", out)

    def test_salary_hours_translation_and_exclusivity(self):
        code, out, _ = run_main(
            ["report", self.path, "--salary", "5200", "--hours", "130"])
        self.assertEqual(code, 0)
        self.assertIn("at 40.00/h", out)
        code, _, _ = run_main(
            ["report", self.path, "--wage", "40", "--salary", "5200", "--hours", "130"])
        self.assertEqual(code, 2)
        code, _, _ = run_main(["report", self.path, "--salary", "5200"])
        self.assertEqual(code, 2)

    def test_deterministic_by_construction(self):
        _, out1, _ = run_main(["report", self.path, "--wage", "40"])
        _, out2, _ = run_main(["report", self.path, "--wage", "40"])
        self.assertEqual(out1, out2)

    def test_thin_refusal_few_searches(self):
        rows = [r for r in TOY_A if r[1] == "search"][:7]
        code, _, err = run_main(["report", self.toy(rows)])
        self.assertEqual(code, 3)
        self.assertIn("thin", err)

    def test_thin_refusal_short_coverage(self):
        rows = [r for r in TOY_A if r[0] <= "2026-08-03"]
        code, _, err = run_main(["report", self.toy(rows)])
        self.assertEqual(code, 3)
        self.assertIn("thin", err)


class RepeatOffenders(TmpCase):
    """Acceptance 3: the repeat-offender gate — the light before the rebuy."""

    def setUp(self):
        super().setUp()
        self.path = self.toy(TOY_A)

    def test_gate_fires_at_three_or_more(self):
        # 钥匙 x4 and 剪刀 x3 in the 90-day window -> exit 4
        code, out, _ = run_main(["repeat", self.path])
        self.assertEqual(code, 4)
        self.assertEqual(out.count("REPEAT OFFENDER  ->"), 2)
        self.assertIn("RED LINE: 2 repeat offender(s)", out)

    def test_watch_band_below_the_line(self):
        _, out, _ = run_main(["repeat", self.path])
        self.assertIn("WATCH", out)
        self.assertIn("WATCH = one hunt below the offender line", out)

    def test_hits_threshold_adjustable(self):
        code, out, _ = run_main(["repeat", self.path, "--hits", "5"])
        self.assertEqual(code, 0)  # nothing reaches 5
        self.assertNotIn("RED LINE", out)

    def test_window_excludes_old_hunts(self):
        # window shrunk to 3 days (start 08-07): only the 08-09 钥匙 hunt survives
        code, out, _ = run_main(["repeat", self.path, "--window", "3"])
        self.assertEqual(code, 0)
        self.assertIn("钥匙", out)
        self.assertNotIn("RED LINE", out)

    def test_prescription_attached_when_place_recurrs(self):
        _, out, _ = run_main(["repeat", self.path])
        self.assertIn("prescription: fixed home at '沙发缝' (x2)", out)

    def test_never_found_gets_no_spot(self):
        _, out, _ = run_main(["repeat", self.path])
        self.assertIn("no recurring hiding spot yet", out)

    def test_repeat_needs_evidence(self):
        rows = [r for r in TOY_A if r[1] == "search"][:7]
        code, _, _ = run_main(["repeat", self.toy(rows)])
        self.assertEqual(code, 3)


class DuplicateBuyAudit(TmpCase):
    """Acceptance 4: rebuys confronted with hunt history."""

    def setUp(self):
        super().setUp()
        self.path = self.toy(TOY_A)

    def test_confirmation_verdicts(self):
        code, out, _ = run_main(["dup", self.path])
        self.assertEqual(code, 0)
        # 剪刀 has hunt history -> CONFIRMED; 门禁卡 has none -> UNEXPLAINED
        scissor_line = [l for l in out.split("\n") if "剪刀" in l][0]
        card_line = [l for l in out.split("\n") if "门禁卡" in l][0]
        self.assertIn("CONFIRMED", scissor_line)
        self.assertIn("UNEXPLAINED", card_line)
        self.assertIn("why did you rebuy", out)

    def test_confirmation_rate_identity(self):
        _, out, _ = run_main(["dup", self.path])
        self.assertIn("duplicate-buy total: 49.90 across 2 item(s)", out)
        self.assertIn("confirmation rate 1/2 = 50.0%", out)

    def test_no_buys_is_thin(self):
        rows = [r for r in TOY_A if r[1] != "buy"]
        code, _, err = run_main(["dup", self.toy(rows)])
        self.assertEqual(code, 3)


class FixedHomeClinic(TmpCase):
    """Acceptance 5: prescriptions from the mode hiding spot; reviews per day."""

    def setUp(self):
        super().setUp()
        self.path = self.toy(TOY_A)

    def test_prescriptions_for_unfixed_recurring_items(self):
        code, out, _ = run_main(["place", self.path])
        self.assertEqual(code, 0)
        self.assertIn("give it a home at '沙发缝' (found there x2)", out)
        self.assertIn("give it a home at '抽屉' (found there x2)", out)

    def test_fix_review_quiet_when_no_hunts_either_side(self):
        # 门禁卡 fix 08-01: pre 07-27..08-01 no hunts, post 08-02..08-09 none
        _, out, _ = run_main(["place", self.path])
        self.assertIn("QUIET", out)

    def test_wandering_pair_gets_watch_line(self):
        # 钥匙 found twice at 床头柜 and twice at 阳台: a 2-2 tie, no single home
        rows = list(TOY_A)
        rows[0] = ("2026-07-27", "search", "钥匙", "5", "床头柜", "", "")
        rows[1] = ("2026-07-29", "search", "钥匙", "8", "阳台", "", "")
        rows[5] = ("2026-08-02", "search", "钥匙", "2", "床头柜", "", "")
        rows[11] = ("2026-08-09", "search", "钥匙", "4", "阳台", "", "")
        _, out, _ = run_main(["place", self.toy(rows)])
        self.assertIn("wanders between", out)

    def test_too_early_when_ledger_ends_soon_after_fix(self):
        # fix on the last day: zero observed post days -> not judgable
        rows = [r for r in TOY_A if not (r[1] == "fix" and r[2] == "门禁卡")]
        rows.append(("2026-08-09", "fix", "雨伞", "", "门后挂钩", "", ""))
        _, out, _ = run_main(["place", self.toy(rows)])
        self.assertIn("TOO EARLY", out)

    def test_no_cure_when_post_rate_stays_high(self):
        # 门禁卡: 2 hunts in the 5 pre days (0.4/day), fix, then 2 hunts in the
        # 9 observed post days (0.22/day) — above the half-rate working line
        rows = [
            ("2026-07-27", "search", "门禁卡", "5", "沙发缝", "", ""),
            ("2026-07-28", "search", "雨伞", "6", "玄关", "", ""),
            ("2026-07-29", "search", "保温杯", "4", "-", "", ""),
            ("2026-07-30", "search", "门禁卡", "3", "外套", "", ""),
            ("2026-07-31", "fix", "门禁卡", "", "玄关托盘", "", ""),
            ("2026-08-02", "search", "门禁卡", "4", "沙发缝", "", ""),
            ("2026-08-03", "search", "雨伞", "2", "阳台", "", ""),
            ("2026-08-04", "search", "剪刀", "3", "抽屉", "", ""),
            ("2026-08-05", "search", "门禁卡", "2", "床头柜", "", ""),
            ("2026-08-06", "search", "剪刀", "1", "文具盒", "", ""),
            ("2026-08-08", "search", "钥匙", "4", "玄关碗", "", ""),
            ("2026-08-09", "search", "保温杯", "2", "碗架", "", ""),
        ]
        _, out, _ = run_main(["place", self.toy(rows)])
        self.assertIn("NO-CURE", out)


class Simulate(TmpCase):
    """Acceptance 6: counterfactuals priced by the ledger's own cure rate."""

    def setUp(self):
        super().setUp()
        self.path = self.toy(TOY_A)

    def test_internal_cure_from_quiet_review(self):
        # the only judgable fix (门禁卡) went quiet: cure = 100%
        code, out, _ = run_main(["simulate", self.path, "fix", "--item", "钥匙"])
        self.assertEqual(code, 0)
        self.assertIn("cure rate: 100%", out)
        self.assertIn("measured from this ledger's fix reviews", out)
        # 钥匙: 4 hunts / 90d, avg 4.75 min -> 77 min/yr; cure 100% -> 0
        self.assertIn("as-is:    77 min/yr hunted for this item", out)
        self.assertIn("fixed:    0 min/yr (-77 min/yr)", out)
        self.assertIn("ledger-wide annual hunt: 910 min -> would drop to 833 min", out)

    def test_explicit_cure_is_disclosed_as_assumption(self):
        code, out, _ = run_main(
            ["simulate", self.path, "fix", "--item", "钥匙", "--cure", "0.5"])
        self.assertEqual(code, 0)
        self.assertIn("cure rate: 50%", out)
        self.assertIn("assumed", out)
        self.assertIn("fixed:    39 min/yr (-39 min/yr)", out)  # 77.06 x 0.5

    def test_no_evidence_no_invention(self):
        rows = [r for r in TOY_A if r[1] != "fix"]
        code, _, err = run_main(["simulate", self.toy(rows), "fix", "--item", "钥匙"])
        self.assertEqual(code, 3)
        self.assertIn("refuses to invent", err)

    def test_unknown_item_rejected(self):
        code, _, _ = run_main(["simulate", self.path, "fix", "--item", "火箭"])
        self.assertEqual(code, 2)

    def test_cure_bounds(self):
        for cure in ("0", "1", "1.5", "-0.2"):
            code, _, _ = run_main(
                ["simulate", self.path, "fix", "--item", "钥匙", "--cure", cure])
            self.assertEqual(code, 2, "cure=%r should reject" % cure)

    def test_replay_always_exit_zero_even_with_wage(self):
        code, out, _ = run_main(
            ["simulate", self.path, "fix", "--item", "钥匙", "--wage", "40"])
        self.assertEqual(code, 0)
        self.assertIn("saves 51.37/yr", out)  # 77.06 min at 40/h


class Validate(TmpCase):
    """Acceptance 7: identities and disclosures."""

    def test_healthy_ledger(self):
        path = self.toy(TOY_A)
        code, out, _ = run_main(["validate", path])
        self.assertEqual(code, 0)
        self.assertIn("identity rows: 9 + 2 + 1 == 12  [OK]", out)
        self.assertIn("identity minutes: per-item sum 35 == total 35  [OK]", out)
        self.assertIn("ledger healthy", out)

    def test_never_found_disclosed(self):
        _, out, _ = run_main(["validate", self.toy(TOY_A)])
        self.assertIn("disclosures:", out)
        self.assertIn("search of '保温杯' never found", out)

    def test_demo_ledger_byte_exact_vs_generator(self):
        builder = os.path.join(os.path.dirname(HERE), "examples", "build_examples.py")
        proc = subprocess.run([sys.executable, builder, "--check"],
                              capture_output=True, text=True,
                              cwd=os.path.dirname(HERE))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class ExitSemantics(TmpCase):
    """Acceptance 8: exit codes and honesty clauses."""

    def test_exit_2_missing_file(self):
        code, _, err = run_main(["report", "/nonexistent/ledger.tsv"])
        self.assertEqual(code, 2)

    def test_no_command_prints_help(self):
        code, out, _ = run_main([])
        self.assertEqual(code, 2)
        self.assertIn("usage", out.lower())

    def test_unpriced_never_talks_money(self):
        code, out, _ = run_main(["report", self.toy(TOY_A)])
        self.assertEqual(code, 0)
        for banned in ("¥", "at 40", "/yr +"):
            self.assertNotIn(banned, out)


if __name__ == "__main__":
    unittest.main()
