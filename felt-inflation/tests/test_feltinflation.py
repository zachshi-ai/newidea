#!/usr/bin/env python3
"""Acceptance tests for 体感通胀 · Felt Inflation.

Every acceptance criterion in README.md is a test here. The golden
fixture (alpha/beta/gamma/delta) has hand-computed index values; the
drift fixtures exercise trade-down pairing in both directions; the
dogfood suite regenerates the committed examples and byte-compares them.
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import felt_inflation as fi  # noqa: E402

# price is the LINE TOTAL (unit price = price / qty). alpha/beta/gamma/
# epsilon form the evaluable basket (den 180 -> num 205, L = 1.138889);
# delta is never seen after the base month (uncovered, excluded) and
# gamma's period price is carried forward from 2024-02 (imputed).
GOLDEN = """\
date\titem\tcategory\tqty\tprice\tstore
2024-01-05\talpha\tgrocery\t1\t100.0\tM
2024-01-06\tbeta\tgrocery\t2\t20.0\tM
2024-01-07\tgamma\tgrocery\t1\t50.0\tM
2024-01-08\tdelta\ttransport\t3\t15.0\tC
2024-01-09\tepsilon\tgrocery\t1\t10.0\tM
2024-02-05\talpha\tgrocery\t1\t100.0\tM
2024-02-06\tbeta\tgrocery\t2\t20.0\tM
2024-02-07\tgamma\tgrocery\t1\t55.0\tM
2024-02-09\tepsilon\tgrocery\t1\t10.0\tM
2024-03-05\talpha\tgrocery\t1\t100.0\tM
2024-03-06\tbeta\tgrocery\t2\t24.0\tM
2024-03-09\tepsilon\tgrocery\t1\t10.0\tM
2024-04-05\talpha\tgrocery\t1\t110.0\tM
2024-04-06\tbeta\tgrocery\t2\t30.0\tM
2024-04-09\tepsilon\tgrocery\t1\t10.0\tM
"""

# base 2024-01, period 2024-07. shampoo-a abandoned after 02; coffee cut
# from qty 2 to 1 in the window; eggs jump 25->31 per unit in 06; two
# cheaper grocery newcomers (shampoo-b chosen over soap-x: closer to 40)
# and a transport newcomer that must never be paired.
DRIFT_POSITIVE = """\
date\titem\tcategory\tqty\tprice\tstore
2024-01-01\tshampoo-a\tgrocery\t1\t40.0\tM
2024-01-02\tcoffee\tgrocery\t2\t96.0\tM
2024-01-03\tmetro\ttransport\t1\t100.0\tC
2024-01-04\teggs\tgrocery\t2\t50.0\tM
2024-02-01\tshampoo-a\tgrocery\t1\t40.0\tM
2024-02-02\tcoffee\tgrocery\t2\t96.0\tM
2024-02-03\tmetro\ttransport\t1\t100.0\tC
2024-02-04\teggs\tgrocery\t2\t50.0\tM
2024-03-02\tcoffee\tgrocery\t2\t96.0\tM
2024-03-03\tmetro\ttransport\t1\t100.0\tC
2024-03-04\teggs\tgrocery\t2\t50.0\tM
2024-04-02\tcoffee\tgrocery\t2\t96.0\tM
2024-04-03\tmetro\ttransport\t1\t100.0\tC
2024-04-04\teggs\tgrocery\t2\t50.0\tM
2024-05-02\tcoffee\tgrocery\t1\t48.0\tM
2024-05-03\tmetro\ttransport\t1\t100.0\tC
2024-05-04\teggs\tgrocery\t2\t50.0\tM
2024-05-05\tshampoo-b\tgrocery\t1\t20.0\tM
2024-05-06\tsoap-x\tgrocery\t1\t18.0\tM
2024-05-07\tbuscard\ttransport\t1\t35.0\tC
2024-06-02\tcoffee\tgrocery\t1\t48.0\tM
2024-06-03\tmetro\ttransport\t1\t100.0\tC
2024-06-04\teggs\tgrocery\t2\t62.0\tM
2024-06-05\tshampoo-b\tgrocery\t1\t20.0\tM
2024-06-06\tsoap-x\tgrocery\t1\t18.0\tM
2024-06-07\tbuscard\ttransport\t1\t35.0\tC
2024-07-02\tcoffee\tgrocery\t1\t48.0\tM
2024-07-03\tmetro\ttransport\t1\t100.0\tC
2024-07-04\teggs\tgrocery\t2\t62.0\tM
2024-07-05\tshampoo-b\tgrocery\t1\t20.0\tM
2024-07-06\tsoap-x\tgrocery\t1\t18.0\tM
2024-07-07\tbuscard\ttransport\t1\t35.0\tC
"""

# same shape, but no price rises and no cart cuts: the bill grows while
# the basket is flat -> negative concession gap (upgrade / more volume).
DRIFT_NEGATIVE = DRIFT_POSITIVE.replace("\t62.0\t", "\t50.0\t").replace(
    "2024-05-02\tcoffee\tgrocery\t1\t48.0\t", "2024-05-02\tcoffee\tgrocery\t2\t96.0\t").replace(
    "2024-06-02\tcoffee\tgrocery\t1\t48.0\t", "2024-06-02\tcoffee\tgrocery\t2\t96.0\t").replace(
    "2024-07-02\tcoffee\tgrocery\t1\t48.0\t", "2024-07-02\tcoffee\tgrocery\t2\t96.0\t")


def write_ledger(text):
    tmp = tempfile.mkdtemp(prefix="feltinflation-test-")
    path = os.path.join(tmp, "ledger.tsv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class RunnerMixin(object):
    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = fi.main(list(argv))
        return code, out.getvalue()


class ParsingTest(unittest.TestCase):
    def test_comments_header_blank_lines_skipped(self):
        text = ("# a comment\n\n"
                "date\titem\tcategory\tqty\tprice\tstore\n"
                "2024-01-05\talpha\tgrocery\t1\t10.0\tM\n")
        rows, skipped = fi.parse_ledger(write_ledger(text))
        self.assertEqual(len(rows), 1)
        self.assertEqual(skipped, [])

    def test_malformed_rows_counted_not_fatal(self):
        text = ("2024-01-05\talpha\tgrocery\t1\t10.0\tM\n"      # good
                "2024-01-06\tbeta\tgrocery\t1\n"                # 2 cols
                "2024-01-07\tgamma\tgrocery\t0\t10.0\tM\n"      # qty 0
                "2024-01-08\tdelta\tgrocery\t1\t-3\tM\n"        # price < 0
                "2024-13-09\tepsilon\tgrocery\t1\t10.0\tM\n"    # bad month
                "\tnull\tgrocery\t1\t10.0\tM\n")                # empty item
        rows, skipped = fi.parse_ledger(write_ledger(text))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(skipped), 5)

    def test_rows_sorted_by_date(self):
        text = ("2024-01-09\tlate\tgrocery\t1\t10.0\tM\n"
                "2024-01-02\tearly\tgrocery\t1\t10.0\tM\n")
        rows, _ = fi.parse_ledger(write_ledger(text))
        self.assertEqual([r.item for r in rows], ["early", "late"])

    def test_unit_price_is_spend_over_qty_per_month(self):
        text = ("2024-01-05\talpha\tgrocery\t1\t10.0\tM\n"
                "2024-01-20\talpha\tgrocery\t3\t36.0\tM\n")  # 9.0 blended
        units = fi.monthly_unit_prices(fi.parse_ledger(write_ledger(text))[0])
        self.assertAlmostEqual(units["alpha"][(2024, 1)], 46.0 / 4.0)

    def test_zero_dependency_stdlib_only(self):
        allow = {"argparse", "io", "json", "math", "os", "sys", "collections"}
        with open(os.path.join(ROOT, "felt_inflation.py"), encoding="utf-8") as fh:
            src = fh.read()
        mods = set(re.findall(r"^(?:import|from)\s+([a-zA-Z_][\w]*)", src, re.M))
        self.assertTrue(mods <= allow, "non-stdlib import found: %s" % (mods - allow))


class GoldenIndexTest(RunnerMixin, unittest.TestCase):
    """alpha/beta/gamma/epsilon fixture, base 2024-01 -> period 2024-04.

    Hand-computed: den = 100 + 2x10 + 50 + 10 = 180 (delta uncovered,
    excluded); num = 110 + 2x15 + 55 + 10 = 205; L = 1.138889;
    annual = L^4 - 1 = 68.2385%. P = 150/130 = 1.153846 (alpha, beta,
    epsilon bought exactly in the period month).
    """

    def setUp(self):
        self.path = write_ledger(GOLDEN)
        global GOLDEN_PATH
        GOLDEN_PATH = self.path

    def rate_golden(self, *extra):
        return self.run_cli("rate", self.path, "--base", "2024-01",
                            "--period", "2024-04", *extra)

    def test_laspeyres_cumulative_and_annualized(self):
        code, out = self.rate_golden()
        self.assertIn("+13.89% cumulative", out)
        self.assertIn("+68.24% annualized", out)

    def test_paasche_and_fisher(self):
        _, out = self.rate_golden()
        self.assertIn("+15.38% cumulative", out)   # paasche: 150/130
        self.assertIn("+14.63% cumulative", out)   # fisher

    def test_coverage_imputed_uncovered_disclosed(self):
        _, out = self.rate_golden()
        self.assertIn("coverage 80.0%", out)
        self.assertIn("imputed prices  1 of 4", out)
        self.assertIn("gamma", out)
        self.assertIn("uncovered       1  delta", out)

    def test_contribution_decomposition_identity(self):
        rows, _ = fi.parse_ledger(self.path)
        basket = fi.Basket(rows, (2024, 1), (2024, 4))
        contribs = basket.contributions()
        total = (basket.laspeyres - 1.0) * 100.0
        self.assertAlmostEqual(sum(pp for _, pp in contribs), total, places=9)
        by_item = dict(contribs)
        self.assertAlmostEqual(by_item["alpha"], 5.555556, places=4)
        self.assertAlmostEqual(by_item["beta"], 5.555556, places=4)
        self.assertAlmostEqual(by_item["gamma"], 2.777778, places=4)
        self.assertAlmostEqual(by_item["epsilon"], 0.0, places=6)

    def test_red_line_breach_exit_4(self):
        code, out = self.rate_golden()
        self.assertEqual(code, fi.EXIT_RED_LINE)
        self.assertIn("OVER THE RED LINE", out)

    def test_below_red_line_exit_0(self):
        code, out = self.rate_golden("--red-line", "80")
        self.assertEqual(code, fi.EXIT_OK)
        self.assertIn("WITHIN THE RED LINE", out)

    def test_power_translates_into_money(self):
        code, out = self.run_cli("power", self.path, "--base", "2024-01",
                                 "--period", "2024-04")
        self.assertIn("\u00a525.00 per month", out)
        self.assertIn("\u00a5300.00 per year", out)
        self.assertIn("\u00a5100.00 in 2024-04 buys what \u00a587.80 bought in 2024-01", out)


class GateTest(RunnerMixin, unittest.TestCase):
    def test_basket_under_five_refused_exit_3(self):
        rows = []
        for d in range(1, 4):  # 3 items, all still bought -> coverage fine
            rows.append("2024-01-0%d\ti%d\tg\t1\t10.0\tM" % (d, d))
            rows.append("2024-04-0%d\ti%d\tg\t1\t10.0\tM" % (d, d))
        code, out = self.run_cli("rate", write_ledger("\n".join(rows) + "\n"))
        self.assertEqual(code, fi.EXIT_TOO_THIN)
        self.assertIn("REFUSED", out)
        self.assertIn("base basket under 5 items", out)

    def test_coverage_under_fifty_refused_exit_3(self):
        rows = []
        for d in range(1, 6):  # 5 base items, only i1/i2 seen again -> 40%
            rows.append("2024-01-0%d\ti%d\tg\t1\t10.0\tM" % (d, d))
            if d <= 2:
                rows.append("2024-04-0%d\ti%d\tg\t1\t10.0\tM" % (d, d))
        code, out = self.run_cli("rate", write_ledger("\n".join(rows) + "\n"))
        self.assertEqual(code, fi.EXIT_TOO_THIN)
        self.assertIn("coverage 40% is below 50%", out)

    def test_thin_banner_between_fifty_and_sixty(self):
        rows = []
        for d in range(1, 8):  # 7 base items, i5..i7 uncovered -> 57.1%
            rows.append("2024-01-0%d\ti%d\tg\t1\t10.0\tM" % (d, d))
            if d <= 4:
                rows.append("2024-04-0%d\ti%d\tg\t1\t10.0\tM" % (d, d))
        code, out = self.run_cli("rate", write_ledger("\n".join(rows) + "\n"))
        self.assertEqual(code, fi.EXIT_OK)  # flat prices: 0% annualized
        self.assertIn("THIN: coverage under 60%", out)

    def test_exit_codes_documented_values(self):
        self.assertEqual((fi.EXIT_OK, fi.EXIT_USAGE, fi.EXIT_TOO_THIN,
                          fi.EXIT_RED_LINE), (0, 2, 3, 4))


class DriftTest(RunnerMixin, unittest.TestCase):
    def setUp(self):
        self.pos = write_ledger(DRIFT_POSITIVE)
        self.neg = write_ledger(DRIFT_NEGATIVE)

    def drift(self, path):
        return self.run_cli("drift", path, "--base", "2024-01", "--period", "2024-07")

    def test_abandoned_item_detected_with_last_price(self):
        _, out = self.drift(self.pos)
        self.assertIn("shampoo-a", out)
        self.assertIn("last bought at \u00a540.00", out)

    def test_pair_picks_closest_same_category_newcomer(self):
        _, out = self.drift(self.pos)
        self.assertIn("shampoo-a", out)
        self.assertIn("shampoo-b", out)
        self.assertIn("-50.00%", out)  # 20/40 - 1
        # soap-x loses the pairing race (|18-40|=22 > |20-40|=20) and
        # buscard is transport, never paired with a grocery item.
        self.assertIn("newcomers with no abandoned partner: buscard, soap-x", out)

    def test_positive_concession_gap_trade_down(self):
        _, out = self.drift(self.pos)
        self.assertIn("+6.64pp", out)
        self.assertIn("the concession you already made", out)

    def test_negative_gap_means_no_downgrade(self):
        _, out = self.drift(self.neg)
        self.assertIn("-11.54pp", out)
        self.assertIn("buying more/better", out)


class BoardSidesTest(RunnerMixin, unittest.TestCase):
    def test_price_drop_shows_on_cooling_side(self):
        rows = []
        prices = {"a": 100.0, "b": 50.0, "c": 40.0, "d": 30.0, "e": 20.0}
        for item, p0 in prices.items():  # b drops 50 -> 45, rest flat
            rows.append("2024-01-0%d\t%s\tg\t1\t%.1f\tM" % (len(rows) + 1, item, p0))
            p1 = 45.0 if item == "b" else p0
            rows.append("2024-04-0%d\t%s\tg\t1\t%.1f\tM" % (len(rows) + 1, item, p1))
        code, out = self.run_cli("board", write_ledger("\n".join(rows) + "\n"),
                                 "--base", "2024-01", "--period", "2024-04")
        self.assertEqual(code, fi.EXIT_OK)
        self.assertIn("-2.08pp", out)
        self.assertIn("(cooling)", out)


class UsageTest(RunnerMixin, unittest.TestCase):
    def path(self):
        return write_ledger(GOLDEN)

    @staticmethod
    def code_of(exc):
        return exc.code if isinstance(exc.code, int) else exc.code[0]

    def expect_usage(self, *argv):
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli(*argv)
        self.assertEqual(self.code_of(ctx.exception), fi.EXIT_USAGE)

    def test_period_equal_base_rejected(self):
        self.expect_usage("rate", self.path(), "--base", "2024-01",
                          "--period", "2024-01")

    def test_period_before_base_rejected(self):
        self.expect_usage("rate", self.path(), "--base", "2024-04",
                          "--period", "2024-01")

    def test_base_outside_ledger_range_rejected(self):
        self.expect_usage("rate", self.path(), "--base", "2023-01",
                          "--period", "2024-04")

    def test_period_outside_ledger_range_rejected(self):
        self.expect_usage("rate", self.path(), "--base", "2024-01",
                          "--period", "2025-04")

    def test_bad_month_format_rejected(self):
        self.expect_usage("rate", self.path(), "--base", "2024-13",
                          "--period", "2024-04")

    def test_missing_ledger_file_exit_2(self):
        code = fi.main(["rate", os.path.join(tempfile.mkdtemp(), "nope.tsv")])
        self.assertEqual(code, fi.EXIT_USAGE)


class JsonAndMonthsTest(RunnerMixin, unittest.TestCase):
    def setUp(self):
        self.golden = write_ledger(GOLDEN)

    def test_rate_json_payload_and_exit_code(self):
        code, out = self.run_cli("rate", self.golden, "--base", "2024-01",
                                 "--period", "2024-04", "--format", "json")
        payload = json.loads(out)
        self.assertEqual(payload["exit_code"], fi.EXIT_RED_LINE)
        self.assertAlmostEqual(payload["laspeyres_cum_pct"], 13.8889, places=3)
        self.assertAlmostEqual(payload["annualized_pct"], 68.2385, places=3)
        self.assertAlmostEqual(payload["coverage_pct"], 80.0, places=6)
        self.assertEqual(payload["imputed"], ["gamma"])
        self.assertEqual(payload["uncovered"], ["delta"])
        self.assertTrue(payload["over_red_line"])
        self.assertAlmostEqual(payload["basket_cost_base"], 180.0, places=6)
        self.assertAlmostEqual(payload["basket_cost_period"], 205.0, places=6)

    def test_power_json_fields(self):
        _, out = self.run_cli("power", self.golden, "--base", "2024-01",
                              "--period", "2024-04", "--format", "json")
        payload = json.loads(out)
        self.assertAlmostEqual(payload["delta_month"], 25.0, places=6)
        self.assertAlmostEqual(payload["delta_year"], 300.0, places=6)
        self.assertAlmostEqual(payload["cash_equivalent_at_base"], 87.8049, places=3)

    def test_months_command_lists_density(self):
        code, out = self.run_cli("months", self.golden)
        self.assertEqual(code, fi.EXIT_OK)
        self.assertEqual(out.count("2024-0"), 4)
        self.assertIn("LEDGER DENSITY", out)

    def test_months_json(self):
        _, out = self.run_cli("months", self.golden, "--format", "json")
        payload = json.loads(out)
        self.assertEqual(len(payload["months"]), 4)
        self.assertEqual(payload["months"][0]["month"], "2024-01")


GOLDEN_PATH = None


class DemoLedgerTest(RunnerMixin, unittest.TestCase):
    """The committed example ledger (Lin Xiao, 2025-01 .. 2026-06)."""

    def setUp(self):
        self.ledger = os.path.join(ROOT, "examples", "ledger.tsv")

    def test_demo_rate_over_red_line_exit_4(self):
        code, out = self.run_cli("rate", self.ledger, "--base", "2025-01",
                                 "--period", "2026-06")
        self.assertEqual(code, fi.EXIT_RED_LINE)
        self.assertIn("+12.88% cumulative", out)
        self.assertIn("+8.93% annualized", out)
        self.assertIn("coverage 100.0%", out)

    def test_demo_board_takeaway_is_driver_one(self):
        _, out = self.run_cli("board", self.ledger)
        self.assertIsNotNone(re.search(r"takeaway-lunch.*<- driver #1", out))
        self.assertIn("+4.65pp", out)
        self.assertIn("half your inflation comes from two items", out)

    def test_demo_drift_trade_down_found(self):
        _, out = self.run_cli("drift", self.ledger)
        self.assertIn("shampoo-a-400ml", out)
        self.assertIn("-49.11%", out)
        self.assertIn("the concession you already made", out)

    def test_demo_power_translated(self):
        _, out = self.run_cli("power", self.ledger)
        self.assertIn("\u00a5110.80 per month", out)
        self.assertIn("\u00a51,329.60 per year", out)
        self.assertIn("\u00a588.59 bought in 2025-01", out)


class DogfoodTest(unittest.TestCase):
    def test_examples_byte_sync(self):
        proc = subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "examples", "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("all example artifacts are in sync", proc.stdout)


if __name__ == "__main__":
    unittest.main()
