# -*- coding: utf-8 -*-
"""Acceptance tests for fridge-void · Fridge Void.

Every acceptance criterion in README.md is pinned here as a test:
ledger parsing guards, the waste-rate denominators, the two
contribution identities (category board, cause structure), the waste
tax, annualization, exit codes (2 data / 3 thin / 4 red line), the
pantry DUE lamps, item history, and the shopping-cart gate.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import fridge_void as fv  # noqa: E402


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fv.main(argv)
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

    @staticmethod
    def row(bought, name, cat, qty, unit, cost, outcome, odate="", cause=""):
        return "\t".join([bought, name, cat, str(qty), unit, str(cost),
                          outcome, odate, cause])

    def ledger(self, rows, name="ledger.tsv"):
        lines = ["# fridge-void ledger"] + [self.row(*r) for r in rows]
        return self.write(name, "\n".join(lines) + "\n")

    def cart(self, rows, name="cart.tsv"):
        lines = ["\t".join(str(c) for c in r[:9]) for r in rows]
        return self.write(name, "\n".join(lines) + "\n")


def big_ledger_rows():
    """21 settled rows across categories — enough evidence, ~12% waste."""
    rows = []
    # 12 clean 'ate' rows across 5 categories
    for i in range(12):
        cat = ["绿叶菜", "茄果", "肉禽", "蛋奶", "水果"][i % 5]
        rows.append(("2026-06-%02d" % (i + 1), "item%02d" % i, cat,
                     500, "g", 10.0, "ate", "2026-06-%02d" % (i + 5), ""))
    # 4 gave rows (a gift is not waste)
    for i in range(4):
        rows.append(("2026-06-%02d" % (i + 3), "gift%02d" % i, "肉禽",
                     500, "g", 15.0, "gave", "2026-06-%02d" % (i + 6), ""))
    # 2 tossed rows (waste)
    rows.append(("2026-06-05", "spinach", "绿叶菜", 300, "g", 9.0,
                 "tossed", "2026-06-09", "forgot"))
    rows.append(("2026-06-07", "yogurt", "蛋奶", 900, "ml", 18.0,
                 "tossed", "2026-06-19", "expired"))
    # 3 open rows (must not enter the rate denominator)
    rows.append(("2026-06-10", "eggs", "蛋奶", 750, "g", 21.0, "open"))
    rows.append(("2026-06-11", "pumpkin", "茄果", 1200, "g", 12.0, "open"))
    rows.append(("2026-06-12", "milk", "蛋奶", 1, "L", 13.0, "open"))
    return rows


# ---------------------------------------------------------------- parsing

class ParsingTest(TmpCase):
    def test_load_basic_fields(self):
        path = self.ledger([("2026-06-01", "菠菜", "绿叶菜", 400, "g", 6.5,
                             "tossed", "2026-06-05", "forgot")])
        entries = fv.load_ledger(path)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.name, "菠菜")
        self.assertEqual(e.category, "绿叶菜")
        self.assertEqual(e.cost, 6.5)
        self.assertEqual(e.cause, "forgot")
        self.assertEqual(e.outcome, "tossed")

    def test_comments_and_blank_lines_skipped(self):
        path = self.write("l.tsv", "# comment\n\n  \n" +
                          self.row("2026-06-01", "a", "c", 1, "g", 1,
                                   "open") + "\n")
        self.assertEqual(len(fv.load_ledger(path)), 1)

    def test_short_row_rejected(self):
        path = self.write("l.tsv", "2026-06-01\t菠菜\t绿叶菜\t400\tg\t6.5\topen\n")
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_bad_date_rejected(self):
        path = self.ledger([("2026/06/01", "a", "c", 1, "g", 1, "open")])
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_bad_outcome_rejected(self):
        path = self.ledger([("2026-06-01", "a", "c", 1, "g", 1, "eaten")])
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_open_with_outcome_date_rejected(self):
        path = self.ledger([("2026-06-01", "a", "c", 1, "g", 1,
                             "open", "2026-06-02")])
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_settled_without_outcome_date_rejected(self):
        path = self.ledger([("2026-06-01", "a", "c", 1, "g", 1, "ate")])
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_outcome_before_bought_rejected(self):
        path = self.ledger([("2026-06-05", "a", "c", 1, "g", 1,
                             "ate", "2026-06-04")])
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_tossed_requires_known_cause(self):
        path = self.ledger([("2026-06-01", "a", "c", 1, "g", 1,
                             "tossed", "2026-06-02", "aliens")])
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_tossed_requires_cause(self):
        path = self.ledger([("2026-06-01", "a", "c", 1, "g", 1,
                             "tossed", "2026-06-02", "")])
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_cause_only_on_tossed(self):
        path = self.ledger([("2026-06-01", "a", "c", 1, "g", 1,
                             "ate", "2026-06-02", "spoiled")])
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_negative_cost_rejected(self):
        path = self.ledger([("2026-06-01", "a", "c", 1, "g", -5, "open")])
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_empty_ledger_rejected(self):
        path = self.write("l.tsv", "# nothing\n")
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(path)

    def test_missing_file_rejected(self):
        with self.assertRaises(fv.LedgerError):
            fv.load_ledger(os.path.join(self.dir, "nope.tsv"))

    def test_weight_units(self):
        path = self.ledger([
            ("2026-06-01", "a", "c", 500, "g", 5, "open"),
            ("2026-06-01", "b", "c", 1.5, "kg", 5, "open"),
            ("2026-06-01", "c", "c", 1, "L", 5, "open"),
            ("2026-06-01", "d", "c", 6, "个", 5, "open"),
        ])
        kg = {e.name: e.kg for e in fv.load_ledger(path)}
        self.assertAlmostEqual(kg["a"], 0.5)
        self.assertAlmostEqual(kg["b"], 1.5)
        self.assertIsNone(kg["c"])
        self.assertIsNone(kg["d"])

    def test_name_normalization(self):
        self.assertEqual(fv.norm_name("  Spinach "), "spinach")
        self.assertEqual(fv.norm_name("老大娘 白菜"), "老大娘 白菜")


# ------------------------------------------------------------- accounting

class AccountingTest(TmpCase):
    def ledger_and_numbers(self):
        path = self.ledger(big_ledger_rows())
        entries = fv.load_ledger(path)
        return entries, fv.split(entries)

    def test_gave_is_not_waste(self):
        entries, (settled, _o, ate, tossed, gave) = self.ledger_and_numbers()
        rate = sum(e.cost for e in tossed) / sum(e.cost for e in settled)
        self.assertAlmostEqual(rate, 27.0 / 207.0)
        self.assertEqual(len(gave), 4)

    def test_open_rows_out_of_denominator(self):
        entries, (settled, open_items, _a, _t, _g) = self.ledger_and_numbers()
        self.assertEqual(len(open_items), 3)
        self.assertEqual(len(settled), 18)
        settled_cost = sum(e.cost for e in settled)
        self.assertAlmostEqual(settled_cost, 207.0)

    def test_category_contribution_identity(self):
        entries, (settled, _o, _a, tossed, _g) = self.ledger_and_numbers()
        board, sc, tc = fv.category_board(entries, settled, tossed)
        self.assertAlmostEqual(sc, sum(e.cost for e in settled))
        self.assertAlmostEqual(tc, sum(e.cost for e in tossed))
        total = sum(b["contribution"] for b in board
                    if b["contribution"] is not None)
        self.assertAlmostEqual(total, tc / sc, places=9)

    def test_cause_share_identity(self):
        entries, (settled, _o, _a, tossed, _g) = self.ledger_and_numbers()
        rows, total = fv.cause_structure(tossed)
        self.assertAlmostEqual(sum(r["share"] for r in rows), 1.0, places=9)
        self.assertAlmostEqual(sum(r["cost"] for r in rows), total)

    def test_waste_tax_multiplier(self):
        rate = 0.12
        self.assertAlmostEqual(1.0 / (1.0 - rate), 1.1363636, places=6)
        rate = 0.40
        self.assertAlmostEqual(1.0 / (1.0 - rate), 1.6666667, places=6)

    def test_annualization_uses_span(self):
        path = self.ledger(big_ledger_rows())
        entries = fv.load_ledger(path)
        tossed_cost = 27.0
        yearly, weeks = fv.annualize(entries, tossed_cost)
        days = (fv.date(2026, 6, 12) - fv.date(2026, 6, 1)).days
        self.assertAlmostEqual(weeks, days / 7.0)
        self.assertAlmostEqual(yearly, tossed_cost / (days / 7.0) * 52.0)

    def test_annualization_floor(self):
        rows = [("2026-06-01", "a", "c", 1, "g", 10, "tossed",
                 "2026-06-02", "spoiled"),
                ("2026-06-02", "b", "c", 1, "g", 10, "tossed",
                 "2026-06-03", "spoiled")]
        path = self.ledger(rows)
        yearly, weeks = fv.annualize(fv.load_ledger(path), 20.0)
        self.assertEqual(weeks, 1.0)
        self.assertAlmostEqual(yearly, 20.0 / 1.0 * 52.0)

    def test_per_week_buys(self):
        path = self.ledger(big_ledger_rows())
        entries = fv.load_ledger(path)
        bought = sum(e.cost for e in entries)
        self.assertAlmostEqual(fv.per_week(entries, bought),
                               bought / (11 / 7.0))


# ------------------------------------------------------------ exit codes

class ExitCodeTest(TmpCase):
    def test_full_ledger_ok(self):
        path = self.ledger(big_ledger_rows())
        code, out, _ = run_main(["ledger", path])
        self.assertEqual(code, fv.EXIT_OK)
        self.assertIn("waste rate", out)
        self.assertIn("VERDICT: OK", out)

    def test_thin_ledger_exit_3(self):
        rows = big_ledger_rows()[:10]
        path = self.ledger(rows)
        code, _out, err = run_main(["ledger", path])
        self.assertEqual(code, fv.EXIT_THIN)
        self.assertIn("exit 3", err)

    def test_no_settled_cost_exit_3(self):
        rows = [("2026-06-01", "a", "c", 1, "g", 1, "open")] * 25
        path = self.ledger(rows)
        code, _out, err = run_main(["ledger", path])
        self.assertEqual(code, fv.EXIT_THIN)

    def test_red_line_exit_4(self):
        rows = []
        for i in range(14):
            rows.append(("2026-06-%02d" % (i + 1), "eat%02d" % i, "肉禽",
                         500, "g", 10.0, "ate", "2026-06-%02d" % (i + 10), ""))
        for i in range(6):
            rows.append(("2026-06-%02d" % (i + 1), "bin%02d" % i, "绿叶菜",
                         500, "g", 10.0, "tossed", "2026-06-1%d" % i, "spoiled"))
        path = self.ledger(rows)
        code, out, _ = run_main(["ledger", path])
        self.assertEqual(code, fv.EXIT_RED)
        self.assertIn("VERDICT: RED", out)

    def test_red_line_flag_custom(self):
        rows = big_ledger_rows()  # rate ~14.06%
        path = self.ledger(rows)
        code, _out, _ = run_main(["ledger", path, "--red-line", "0.1"])
        self.assertEqual(code, fv.EXIT_RED)

    def test_bad_data_exit_2(self):
        path = self.write("l.tsv", "garbage\trow\n")
        code, _out, err = run_main(["ledger", path])
        self.assertEqual(code, fv.EXIT_DATA)
        self.assertIn("exit 2", err)

    def test_no_command_shows_help_exit_2(self):
        code, out, _err = run_main([])
        self.assertEqual(code, fv.EXIT_DATA)
        self.assertIn("usage:", out)


# ------------------------------------------------------------- commands

class BoardTest(TmpCase):
    def test_board_orders_and_sums(self):
        path = self.ledger(big_ledger_rows())
        code, out, _ = run_main(["board", path])
        self.assertEqual(code, fv.EXIT_OK)
        self.assertIn("add up to the global rate", out)

    def test_disaster_category_exit_4(self):
        rows = []
        for i in range(6):  # 蛋奶: 6/6 settled -> rate 100% >= 30%
            rows.append(("2026-06-%02d" % (i + 1), "yogurt%d" % i, "蛋奶",
                         900, "ml", 10.0, "tossed", "2026-06-20", "expired"))
        for i in range(14):
            rows.append(("2026-06-%02d" % (i + 1), "eat%02d" % i, "肉禽",
                         500, "g", 10.0, "ate", "2026-06-2%d" % (i % 10), ""))
        path = self.ledger(rows)
        code, out, _ = run_main(["board", path])
        self.assertEqual(code, fv.EXIT_RED)
        self.assertIn("disaster", out)

    def test_top_limits_rows(self):
        path = self.ledger(big_ledger_rows())
        _code, out, _ = run_main(["board", path, "--top", "2"])
        body = [l for l in out.splitlines() if l and not l.startswith("=")
                and not l.startswith("global") and not l.startswith("category")
                and not l.startswith("contributions")]
        self.assertEqual(len(body), 2)


class CauseTest(TmpCase):
    def test_cause_structure(self):
        path = self.ledger(big_ledger_rows())
        code, out, _ = run_main(["cause", path])
        self.assertEqual(code, fv.EXIT_OK)
        self.assertIn("forgot", out)
        self.assertIn("expired", out)
        self.assertIn("cause shares add up to 1", out)

    def test_cause_without_tossed_exit_3(self):
        rows = [("2026-06-01", "a", "c", 1, "g", 5, "ate", "2026-06-02", "")
                for _ in range(21)]
        path = self.ledger(rows)
        code, _out, err = run_main(["cause", path])
        self.assertEqual(code, fv.EXIT_THIN)


class TaxTest(TmpCase):
    def test_tax_report(self):
        path = self.ledger(big_ledger_rows())
        code, out, _ = run_main(["tax", path])
        self.assertEqual(code, fv.EXIT_OK)
        # 27/207 waste -> multiplier 207/180 = 1.150 exactly
        self.assertIn("¥1.150", out)
        self.assertIn("¥27.00", out)


class PantryTest(TmpCase):
    def test_pantry_orders_and_flags_due(self):
        path = self.ledger(big_ledger_rows())
        code, out, _ = run_main(["pantry", path])
        # anchor = 2026-06-12; eggs bought 06-10 (2d), pumpkin 06-11 (1d),
        # milk 06-12 (0d) -> nothing past 7 days
        self.assertEqual(code, fv.EXIT_OK)
        self.assertIn("ledger today = 2026-06-12", out)
        self.assertNotIn("\nDUE", out)

    def test_pantry_due_exit_4(self):
        rows = [("2026-05-01", "old", "绿叶菜", 300, "g", 5, "open")]
        rows += [("2026-06-%02d" % (i + 1), "eat%d" % i, "肉禽", 500, "g",
                  10, "ate", "2026-06-%02d" % (i + 2), "") for i in range(21)]
        path = self.ledger(rows)
        code, out, _ = run_main(["pantry", path])
        self.assertEqual(code, fv.EXIT_RED)
        self.assertIn("DUE", out)
        # anchor = 2026-06-21, old bought 2026-05-01 -> 51 days
        self.assertIn("51d", out)

    def test_pantry_empty_when_all_settled(self):
        rows = [("2026-06-01", "a", "c", 1, "g", 5, "ate", "2026-06-02", "")
                for _ in range(21)]
        path = self.ledger(rows)
        code, out, _ = run_main(["pantry", path])
        self.assertEqual(code, fv.EXIT_OK)
        self.assertIn("pantry is empty", out)


class ItemTest(TmpCase):
    def test_item_history(self):
        path = self.ledger(big_ledger_rows())
        code, out, _ = run_main(["item", path, "spinach"])
        self.assertEqual(code, fv.EXIT_OK)
        self.assertIn("item history: spinach", out)
        self.assertIn("dominant cause: forgot", out)

    def test_item_casefold_match(self):
        path = self.ledger(big_ledger_rows())
        code, out, _ = run_main(["item", path, "SPINACH"])
        self.assertEqual(code, fv.EXIT_OK)

    def test_item_unknown_exit_3(self):
        path = self.ledger(big_ledger_rows())
        code, _out, err = run_main(["item", path, "dragonfruit"])
        self.assertEqual(code, fv.EXIT_THIN)


# ------------------------------------------------------- shopping gate

class PlanTest(TmpCase):
    def base_ledger(self):
        rows = big_ledger_rows()
        # add rejected rows: oat milk tried & disliked
        rows.append(("2026-06-02", "燕麦奶", "乳品", 1000, "ml", 28.0,
                     "tossed", "2026-06-15", "rejected"))
        rows.append(("2026-06-09", "羽衣甘蓝", "绿叶菜", 200, "g", 9.9,
                     "tossed", "2026-06-16", "rejected"))
        # push 绿叶菜 into disaster zone: 5+ settled, rate >= 30%
        rows += [
            ("2026-06-03", "油麦菜", "绿叶菜", 400, "g", 6.0, "tossed",
             "2026-06-07", "forgot"),
            ("2026-06-04", "生菜", "绿叶菜", 400, "g", 5.0, "tossed",
             "2026-06-09", "spoiled"),
            ("2026-06-05", "苋菜", "绿叶菜", 300, "g", 4.5, "tossed",
             "2026-06-10", "forgot"),
            ("2026-06-06", "菠菜", "绿叶菜", 300, "g", 6.0, "ate",
             "2026-06-08", ""),
            ("2026-06-07", "青菜", "绿叶菜", 300, "g", 4.0, "ate",
             "2026-06-10", ""),
        ]
        return self.ledger(rows)

    def test_blacklist_blocks_exit_4(self):
        led = self.base_ledger()
        cart = self.cart([("燕麦奶", "乳品", 1000, "ml", 28.0, "", "", "", "")])
        code, out, _ = run_main(["plan", led, cart])
        self.assertEqual(code, fv.EXIT_RED)
        self.assertIn("BLOCKED", out)
        self.assertIn("rejected", out)

    def test_disaster_zone_warns_but_passes(self):
        led = self.base_ledger()
        cart = self.cart([("青菜", "绿叶菜", 300, "g", 4.0, "", "", "", "")])
        code, out, _ = run_main(["plan", led, cart])
        self.assertEqual(code, fv.EXIT_OK)
        self.assertIn("WARNING", out)
        self.assertIn("disaster zone", out)
        self.assertIn("VERDICT: PASS", out)

    def test_clean_cart_passes_silent(self):
        led = self.base_ledger()
        cart = self.cart([("鸡腿", "肉禽", 500, "g", 14.0, "", "", "", "")])
        code, out, _ = run_main(["plan", led, cart])
        self.assertEqual(code, fv.EXIT_OK)
        self.assertIn("VERDICT: PASS", out)
        self.assertNotIn("disaster zone", out)

    def test_cart_spike_warning(self):
        led = self.base_ledger()
        # weekly buy in base ledger is far below 1.5x of a huge cart
        cart = self.cart([
            ("牛排", "肉禽", 800, "g", 200.0, "", "", "", ""),
            ("三文鱼", "水产", 600, "g", 120.0, "", "", "", ""),
        ])
        code, out, _ = run_main(["plan", led, cart])
        self.assertEqual(code, fv.EXIT_OK)
        self.assertIn("weekly average", out)

    def test_empty_cart_rejected(self):
        led = self.base_ledger()
        cart = self.write("cart.tsv", "# empty\n")
        code, _out, err = run_main(["plan", led, cart])
        self.assertEqual(code, fv.EXIT_DATA)


# ---------------------------------------------------------------- meta

class VersionTest(unittest.TestCase):
    def test_version_string(self):
        self.assertRegex(fv.VERSION, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
