# -*- coding: utf-8 -*-
"""Acceptance tests for smooth-sailing · Smooth Sailing.

Every acceptance criterion in README.md is pinned here as a test:
ledger parsing guards, the burn-rate median discipline (a spike month
must not set the dial), the runway red line, the cash reconciliation
identity, the three-clamp paycheck engine, the simulate conservation
identity and its no-worse-smoothing guarantee, the tax jar and cliff
lamp, the dry/half stress scenarios, and exit codes
(2 data / 3 thin / 4 red line).
"""

import io
import math
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import smooth_sailing as ss  # noqa: E402

GOLD = os.path.join(os.path.dirname(HERE), "examples", "ledger.tsv")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ss.main(argv)
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

    def ledger(self, rows, name="ledger.tsv", header=True):
        """rows: list of (month, income, spend, cash[, tax_paid])."""
        lines = []
        if header:
            lines.append("month\tincome\tspend\tcash\ttax_paid")
        for r in rows:
            cells = [r[0]] + [str(c) for c in r[1:]]
            if len(cells) == 4:
                cells.append(str(r[4]) if len(r) > 4 else "0")
            lines.append("\t".join(cells))
        return self.write(name, "\n".join(lines) + "\n")


def salaried_rows(n=12, income=12000.0, spend=8000.0, start=50000.0):
    """A boring, effectively-salaried book: steady income, big cushion."""
    rows = []
    cash = start
    for i in range(n):
        month = ss.month_label(ss.month_index("2025-01") + i)
        cash += income - spend
        rows.append((month, income, spend, cash))
    return rows


# ------------------------------------------------------------------ pure helpers

class PureHelpers(unittest.TestCase):
    def test_month_index_label_roundtrip(self):
        self.assertEqual(ss.month_index("2026-09"), 2026 * 12 + 8)
        self.assertEqual(ss.month_label(2026 * 12 + 8), "2026-09")
        self.assertEqual(ss.month_label(ss.month_index("2024-12") + 1), "2025-01")

    def test_parse_month_guards(self):
        for bad in ("2025", "2025-13", "2025-00", "ab-cd", "2025-1x"):
            with self.assertRaises(ss.LedgerError):
                ss.parse_month(bad)

    def test_pctl_single_and_endpoints(self):
        self.assertEqual(ss.pctl([7.0], 0.9), 7.0)
        self.assertEqual(ss.pctl([1.0, 2.0, 3.0], 0.0), 1.0)
        self.assertEqual(ss.pctl([1.0, 2.0, 3.0], 1.0), 3.0)

    def test_pctl_linear_interpolation(self):
        self.assertAlmostEqual(ss.pctl([1.0, 2.0, 3.0, 4.0], 0.5), 2.5)
        self.assertAlmostEqual(ss.pctl([1.0, 2.0, 3.0, 4.0], 0.25), 1.75)

    def test_cv_constant_is_zero(self):
        self.assertEqual(ss.cv([5.0, 5.0, 5.0]), 0.0)

    def test_cv_known_value(self):
        self.assertAlmostEqual(ss.cv([1.0, 2.0, 3.0, 4.0]),
                               1.118033988749895 / 2.5)

    def test_vol_grade_ladder(self):
        self.assertEqual(ss.vol_grade(0.10), "STEADY")
        self.assertEqual(ss.vol_grade(0.30), "CHOPPY")
        self.assertEqual(ss.vol_grade(0.80), "WILD")

    def test_money_formatting(self):
        self.assertEqual(ss.money(24470), "24,470.00")
        self.assertEqual(ss.money(-16.5), "-16.50")
        self.assertEqual(ss.money(0), "0.00")

    def test_pct_formatting(self):
        self.assertEqual(ss.pct(0.1234), "12.3%")


# ------------------------------------------------------------------ parsing guards

class Parsing(TmpCase):
    def test_gold_ledger_parses_24_months(self):
        rows = ss.read_ledger(GOLD)
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows[0].month, "2024-10")
        self.assertEqual(rows[-1].month, "2026-09")
        self.assertEqual(rows[0].income, 9600.0)
        self.assertEqual(rows[-1].cash, 24700.0)

    def test_tax_paid_defaults_to_zero(self):
        path = self.ledger([("2025-01", 100, 80, 20)])
        self.assertEqual(ss.read_ledger(path)[0].tax_paid, 0.0)

    def test_comments_and_blank_lines_skipped(self):
        path = self.write("l.tsv",
                          "# comment\n\nmonth\tincome\tspend\tcash\ttax_paid\n"
                          "2025-01\t100\t80\t20\t0\n")
        self.assertEqual(len(ss.read_ledger(path)), 1)

    def test_header_missing_columns(self):
        path = self.write("l.tsv", "month\tincome\tspend\n2025-01\t1\t1\t1\n")
        with self.assertRaises(ss.LedgerError):
            ss.read_ledger(path)

    def test_short_row(self):
        path = self.ledger([("2025-01", 100, 80)])
        with self.assertRaises(ss.LedgerError):
            ss.read_ledger(path)

    def test_non_numeric_income(self):
        path = self.ledger([("2025-01", "rich", 80, 20)])
        with self.assertRaises(ss.LedgerError):
            ss.read_ledger(path)

    def test_negative_income_rejected(self):
        path = self.ledger([("2025-01", -5, 80, 20)])
        with self.assertRaises(ss.LedgerError):
            ss.read_ledger(path)

    def test_duplicate_month(self):
        path = self.ledger([("2025-01", 100, 80, 20), ("2025-01", 100, 80, 20)])
        with self.assertRaises(ss.LedgerError):
            ss.read_ledger(path)

    def test_descending_months(self):
        path = self.ledger([("2025-02", 100, 80, 20), ("2025-01", 100, 80, 20)])
        with self.assertRaises(ss.LedgerError):
            ss.read_ledger(path)

    def test_empty_book(self):
        path = self.write("l.tsv", "# nothing here\n")
        with self.assertRaises(ss.LedgerError):
            ss.read_ledger(path)

    def test_missing_file_is_data_error(self):
        code, out, err = run_main(["report", os.path.join(self.dir, "nope.tsv")])
        self.assertEqual(code, ss.EXIT_DATA)
        self.assertIn("io error", err)


# ------------------------------------------------------------------ statistics discipline

class Statistics(TmpCase):
    def setUp(self):
        super().setUp()
        self.rows = ss.read_ledger(GOLD)

    def test_burn_is_trailing_median(self):
        self.assertEqual(ss.burn_rate(self.rows, 6), 9000.0)

    def test_burn_resists_spike_month(self):
        """The 16,600 spend of 2026-05 (tax bill month) must not set the dial."""
        burn = ss.burn_rate(self.rows, 6)
        window_spends = [r.spend for r in self.rows[-6:]]
        self.assertEqual(max(window_spends), 16600.0)  # spike month is in-window
        self.assertLess(burn, ss.mean(window_spends) * 0.92)

    def test_runway_formula(self):
        runway, burn = ss.runway_months(self.rows, 6)
        self.assertAlmostEqual(burn, 9000.0)
        self.assertAlmostEqual(runway, 24700.0 / 9000.0)

    def test_recon_identity_holds_on_gold_book(self):
        drifts, seams = ss.recon_drifts(self.rows)
        self.assertEqual(len(drifts), 23)
        self.assertEqual(seams, 0)
        for month, drift in drifts:
            self.assertLessEqual(abs(drift), ss.RECON_TOL, month)

    def test_recon_skips_seams_across_gaps(self):
        """A hole in the book is missing evidence, not corruption: skip + disclose."""
        rows = [("2025-01", 100, 80, 20), ("2025-03", 100, 80, 40)]
        ledger = self.write("g.tsv", "month\tincome\tspend\tcash\ttax_paid\n" +
                            "\n".join("\t".join(str(c) for c in r) + "\t0" for r in rows) + "\n")
        book = ss.read_ledger(ledger)
        drifts, seams = ss.recon_drifts(book)
        self.assertEqual(seams, 1)
        self.assertEqual(drifts, [])

    def test_implied_start_cash(self):
        self.assertAlmostEqual(ss.implied_start_cash(self.rows), 18000.0)


# ------------------------------------------------------------------ report

class Report(TmpCase):
    def test_gold_numbers_are_pinned(self):
        code, out, _ = run_main(["report", GOLD])
        self.assertIn("P50 9,000.00", out)
        self.assertIn("P90 18,570.00", out)
        self.assertIn("P10 3,460.00", out)
        self.assertIn("P90/P50 2.06x", out)
        self.assertIn("CV 57.9% -> WILD", out)
        self.assertIn("9,000.00/mo", out)
        self.assertIn("2.7 months", out)
        self.assertIn("[RED]", out)

    def test_gold_book_below_runway_line_is_exit_4(self):
        code, out, _ = run_main(["report", GOLD])
        self.assertEqual(code, ss.EXIT_RED)
        self.assertIn("death line", out)

    def test_salaried_book_is_green(self):
        path = self.ledger(salaried_rows())
        code, out, _ = run_main(["report", path])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("[OK]", out)
        self.assertIn("STEADY", out)

    def test_thin_book_refuses_volatility_verdict(self):
        rows = salaried_rows(4)
        path = self.ledger(rows)
        code, out, _ = run_main(["report", path])
        self.assertEqual(code, ss.EXIT_THIN)
        self.assertIn("too thin", out)

    def test_broken_reconciliation_is_data_error(self):
        rows = salaried_rows(8)
        month, income, spend, cash = rows[3]
        rows[3] = (month, income, spend, cash + 3000)  # stash cash under the bed
        path = self.ledger(rows)
        code, out, _ = run_main(["report", path])
        self.assertEqual(code, ss.EXIT_DATA)
        self.assertIn("does not reconcile", out)

    def test_custom_red_line_widens_the_verdict(self):
        code, _, _ = run_main(["report", GOLD, "--red-runway", "2.5"])
        self.assertEqual(code, ss.EXIT_OK)

    def test_famine_count(self):
        code, out, _ = run_main(["report", GOLD])
        self.assertIn("famine months (income<P50) 12/24", out)


# ------------------------------------------------------------------ paycheck

class Paycheck(TmpCase):
    def test_auto_baseline_is_trailing_median_times_rate(self):
        code, out, _ = run_main(["paycheck", GOLD])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("6,210.00", out)  # median(4300..13400 trailing 6) 6900 x 0.9
        self.assertIn("auto median", out)

    def test_explicit_salary(self):
        code, out, _ = run_main(["paycheck", GOLD, "--salary", "9000"])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("PAY: 9,000.00  [OK]", out)
        self.assertIn("explicit", out)

    def test_cash_clamp_kicks_in(self):
        # cash 5,000, floor = 1.0 x burn 4,000 -> headroom 1,000 < salary 3,000
        path = self.ledger([
            ("2025-01", 5000, 4000, 5000),
            ("2025-02", 5000, 4000, 6000),
            ("2025-03", 5000, 4000, 7000),
            ("2025-04", 5000, 4000, 5000),
        ])
        code, out, _ = run_main(["paycheck", path, "--salary", "3000"])
        self.assertEqual(code, ss.EXIT_RED)
        self.assertIn("[CLAMPED by cash]", out)
        self.assertIn("PAY: 1,000.00", out)

    def test_below_dead_water_pays_zero(self):
        path = self.ledger([
            ("2025-01", 5000, 9000, 1000),
            ("2025-02", 5000, 9000, 2000),
            ("2025-03", 5000, 9000, 3000),
            ("2025-04", 5000, 9000, 2000),  # cash below floor (burn 9000)
        ])
        code, out, _ = run_main(["paycheck", path, "--salary", "4000"])
        self.assertEqual(code, ss.EXIT_RED)
        self.assertIn("PAY: 0.00  [FLOODED]", out)

    def test_thin_book_without_salary_refuses(self):
        path = self.ledger(salaried_rows(2))
        code, out, _ = run_main(["paycheck", path])
        self.assertEqual(code, ss.EXIT_THIN)

    def test_thin_book_with_explicit_salary_still_constrained_by_cash(self):
        path = self.ledger([
            ("2025-01", 80000, 4000, 1000),
            ("2025-02", 0, 4000, 2000),
        ])
        code, out, _ = run_main(["paycheck", path, "--salary", "5000"])
        self.assertEqual(code, ss.EXIT_RED)  # headroom 2000-4000 < 0 -> FLOODED

    def test_negative_salary_rejected(self):
        code, _, err = run_main(["paycheck", GOLD, "--salary", "-1"])
        self.assertEqual(code, ss.EXIT_DATA)
        self.assertIn("--salary", err)

    def test_float_months_move_the_floor(self):
        code, out, _ = run_main(["paycheck", GOLD, "--salary", "15000", "--float", "2.0"])
        self.assertEqual(code, ss.EXIT_RED)  # floor 18000, headroom 6700 < 15000
        self.assertIn("CLAMPED by cash", out)

    def test_custom_month_label(self):
        code, out, _ = run_main(["paycheck", GOLD, "--month", "2027-01"])
        self.assertIn("2027-01", out)


# ------------------------------------------------------------------ simulate

class Simulate(TmpCase):
    def test_conservation_identity_on_gold_book(self):
        code, out, _ = run_main(["simulate", GOLD, "--salary", "9000"])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("residual 0.00e+00", out)
        self.assertIn("start 18,000.00 + income 244,700.00 = paid 216,000.00", out)

    def test_smoothing_never_worse_at_affordable_salary(self):
        rows = ss.read_ledger(GOLD)
        sim = ss.simulate(rows, 9000, 0.10, 18000.0, 6, ss.FLOAT_MONTHS)
        actual_cv = ss.cv([r.spend for r in rows])
        sim_cv = ss.cv(sim["sim_spend"])
        self.assertEqual(sim["breaches"], 0)
        self.assertLessEqual(sim_cv, actual_cv + 1e-9)

    def test_wishful_salary_breaches_and_exit_4(self):
        code, out, _ = run_main(["simulate", GOLD, "--salary", "15000"])
        self.assertEqual(code, ss.EXIT_RED)
        self.assertIn("18/24 months", out)
        self.assertIn("wish, not a payroll", out)

    def test_famine_paygo_uplift(self):
        code, out, _ = run_main(["simulate", GOLD, "--salary", "9000"])
        self.assertIn("famine months    12/24", out)
        self.assertIn("median income 5,100.00", out)
        self.assertIn("+76.5%", out)

    def test_tax_jar_accumulates(self):
        rows = ss.read_ledger(GOLD)
        sim = ss.simulate(rows, 9000, 0.10, 18000.0, 6, ss.FLOAT_MONTHS)
        self.assertAlmostEqual(sim["jar"], 24470.0)

    def test_implied_start_cash_used_by_default(self):
        code, out, _ = run_main(["simulate", GOLD, "--salary", "9000"])
        self.assertIn("start 18,000.00", out)

    def test_explicit_start_cash(self):
        code, out, _ = run_main(["simulate", GOLD, "--salary", "9000", "--start-cash", "0"])
        self.assertIn("start 0.00", out)

    def test_thin_book_refuses(self):
        path = self.ledger(salaried_rows(2))
        code, out, _ = run_main(["simulate", path, "--salary", "5000"])
        self.assertEqual(code, ss.EXIT_THIN)

    def test_zero_start_cash_negative_implied_is_clamped(self):
        # cash 0 after a +4,000 month -> implied start = 0 - 4000 = -4000
        path = self.ledger([("2025-01", 5000, 1000, 0),
                            ("2025-02", 1000, 500, 500),
                            ("2025-03", 1000, 500, 1000)])
        code, out, _ = run_main(["simulate", path, "--salary", "500"])
        self.assertIn("clamped to 0", out)


# ------------------------------------------------------------------ tax jar

class TaxJar(TmpCase):
    def test_gold_jar_numbers_are_pinned(self):
        code, out, _ = run_main(["tax", GOLD])
        self.assertEqual(code, ss.EXIT_RED)
        self.assertIn("set aside   24,470.00", out)
        self.assertIn("paid        7,800.00", out)
        self.assertIn("jar owed    16,670.00", out)
        self.assertIn("real disposable 8,030.00", out)
        self.assertIn("CLIFF", out)

    def test_overfunded_jar_is_a_refund(self):
        rows = [("2025-0%d" % i, 10000, 5000, 5000 + i * 1000, 5000) for i in range(1, 7)]
        path = self.ledger(rows)
        code, out, _ = run_main(["tax", path])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("REFUND", out)

    def test_rate_parameter(self):
        code, out, _ = run_main(["tax", GOLD, "--rate", "0.05"])
        self.assertIn("set aside   12,235.00", out)
        self.assertIn("jar owed    4,435.00", out)

    def test_high_cliff_line_turns_lamp_green(self):
        code, _, _ = run_main(["tax", GOLD, "--cliff", "0.90"])
        self.assertEqual(code, ss.EXIT_OK)

    def test_thin_jar_discloses(self):
        path = self.ledger([("2025-01", 10000, 5000, 5000),
                            ("2025-02", 10000, 5000, 10000)])
        code, out, _ = run_main(["tax", path])
        self.assertEqual(code, ss.EXIT_THIN)
        self.assertIn("thin", out)


# ------------------------------------------------------------------ stress

class Stress(TmpCase):
    def test_dry_runway_matches_report(self):
        code, out, _ = run_main(["stress", GOLD])
        self.assertEqual(code, ss.EXIT_RED)
        self.assertIn("runway 2.7 months  [RED]", out)
        self.assertIn("cash hits zero in 2026-12", out)

    def test_half_scenario_net_burn(self):
        code, out, _ = run_main(["stress", GOLD])
        # burn 9000, mean income 10195.83 -> net burn 3902.08
        self.assertIn("net burn 3,902.08/mo, runway 6.3 months", out)
        self.assertIn("cash hits zero in 2027-04", out)

    def test_half_income_sustainable_for_salaried_book(self):
        path = self.ledger(salaried_rows(income=20000, spend=8000))
        code, out, _ = run_main(["stress", path])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("sustainable forever", out)

    def test_green_book_survives_horizon(self):
        path = self.ledger(salaried_rows(n=12, income=12000, spend=8000, start=200000))
        code, out, _ = run_main(["stress", path, "--horizon", "12"])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("survives the whole 12-month horizon", out)

    def test_zero_burn_unlimited(self):
        rows = [("2025-0%d" % i, 10000, 0, 10000 * i) for i in range(1, 7)]
        path = self.ledger(rows)
        code, out, _ = run_main(["stress", path])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("unlimited runway", out)


# ------------------------------------------------------------------ validate & CLI

class ValidateAndCli(TmpCase):
    def test_gold_book_validates_clean(self):
        code, out, _ = run_main(["validate", GOLD])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("continuous", out)
        self.assertIn("23 months checked against the cash identity", out)
        self.assertIn("all 23 reconcile", out)
        self.assertIn("clean", out)

    def test_gap_disclosed_not_interpolated(self):
        rows = salaried_rows(4)
        del rows[1]  # drop 2025-02
        path = self.ledger(rows)
        code, out, _ = run_main(["validate", path])
        self.assertEqual(code, ss.EXIT_OK)
        self.assertIn("1 break(s)", out)
        self.assertIn("2025-01 -> 2025-03", out)
        self.assertIn("never interpolated", out)
        self.assertIn("1 seam(s) across gaps skipped", out)
        self.assertIn("all 1 reconcile", out)

    def test_validate_exit_2_on_broken_book(self):
        rows = salaried_rows(8)
        month, income, spend, cash = rows[2]
        rows[2] = (month, income, spend, cash + 99999)
        path = self.ledger(rows)
        code, out, _ = run_main(["validate", path])
        self.assertEqual(code, ss.EXIT_DATA)
        self.assertIn("BROKEN", out)

    def test_ledger_error_is_data_error(self):
        path = self.ledger([("2025-01", 100, 80, 20), ("2024-12", 100, 80, 20)])
        code, _, err = run_main(["validate", path])
        self.assertEqual(code, ss.EXIT_DATA)
        self.assertIn("data error", err)

    def test_no_arguments_prints_usage(self):
        code, _, err = run_main([])
        self.assertEqual(code, ss.EXIT_DATA)
        self.assertIn("usage:", err)

    def test_unknown_command_rejected(self):
        code, _, err = run_main(["frobnicate", GOLD])
        self.assertEqual(code, ss.EXIT_DATA)
        self.assertIn("invalid choice", err)

    def test_every_command_routes(self):
        for argv in (
            ["report", GOLD],
            ["paycheck", GOLD, "--salary", "9000"],
            ["simulate", GOLD, "--salary", "9000"],
            ["tax", GOLD],
            ["stress", GOLD],
            ["validate", GOLD],
        ):
            code, out, _ = run_main(argv)
            self.assertIn(code, (ss.EXIT_OK, ss.EXIT_RED), argv)
            self.assertTrue(out.strip(), argv)

    def test_version_constant_present(self):
        self.assertTrue(ss.VERSION)


if __name__ == "__main__":
    unittest.main()
