# -*- coding: utf-8 -*-
"""cart-line acceptance tests: the line math, the identities, the gates.

Every acceptance criterion in README.md lands here. The identities are
pinned to 9 decimal places; the verdicts are pinned by exit code.
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import cart_line as cl  # noqa: E402

ORDERS = os.path.join(ROOT, "examples", "orders.tsv")
ITEMS = os.path.join(ROOT, "examples", "items.tsv")


def run_cli(*argv):
    """Run the CLI in-process; return (exit_code, stdout)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cl.main(list(argv))
    return code, buf.getvalue()


def write_tsv(rows):
    """rows: list of tab-joined strings; a header is prepended."""
    body = "\n".join(["date\torder\trule\tplanned\tfiller\tdiscount\tpaid"] + rows)
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body + "\n")
    self_addhoc = path
    return self_addhoc


def write_items(rows, header=True):
    head = "date\torder\tname\tprice\tfiller\tfate\tfate_date" if header else ""
    body = "\n".join(([head] if header else []) + rows)
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body + "\n")
    return path


# ------------------------------------------------------------------ parsing

class OrdersParsingTest(unittest.TestCase):
    def test_demo_ledger_loads(self):
        orders = cl.load_orders(ORDERS)
        self.assertEqual(len(orders), 8)
        self.assertEqual(orders[0].oid, "O-101")

    def test_header_and_comments_skipped(self):
        path = write_tsv(["# a comment", "", "2026-11-01\tX\tnone\t10\t0\t0\t10"])
        try:
            orders = cl.load_orders(path)
            self.assertEqual(len(orders), 1)
        finally:
            os.unlink(path)

    def test_missing_column_exit2(self):
        path = write_tsv(["2026-11-01\tX\tnone\t10\t0\t0"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_orders(path)
        finally:
            os.unlink(path)

    def test_bad_date_exit2(self):
        path = write_tsv(["2026-13-01\tX\tnone\t10\t0\t0\t10"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_orders(path)
        finally:
            os.unlink(path)

    def test_negative_money_exit2(self):
        path = write_tsv(["2026-11-01\tX\tnone\t-10\t0\t0\t-10"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_orders(path)
        finally:
            os.unlink(path)

    def test_bad_rule_exit2(self):
        for rule in ("sometimes:300:50", "every:300", "every:a:50"):
            path = write_tsv(["2026-11-01\tX\t%s\t10\t0\t0\t10" % rule])
            try:
                with self.assertRaises(cl.LedgerError):
                    cl.load_orders(path)
            finally:
                os.unlink(path)

    def test_rule_needs_d_below_m(self):
        path = write_tsv(["2026-11-01\tX\tevery:300:400\t10\t0\t0\t10"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_orders(path)
        finally:
            os.unlink(path)

    def test_empty_order_id_exit2(self):
        path = write_tsv(["2026-11-01\t\tnone\t10\t0\t0\t10"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_orders(path)
        finally:
            os.unlink(path)

    def test_missing_file_exit2(self):
        with self.assertRaises(cl.LedgerError):
            cl.load_orders("/nonexistent/nope.tsv")


class OrderConsistencyTest(unittest.TestCase):
    def test_discount_must_recompute_exit2(self):
        # full:99:20 on total 122 grants 20; claiming 50 breaks I1
        path = write_tsv(["2026-11-01\tX\tfull:99:20\t88\t34\t50\t72"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_orders(path)
        finally:
            os.unlink(path)

    def test_paid_identity_exit2(self):
        # paid must equal planned + filler - discount
        path = write_tsv(["2026-11-01\tX\tnone\t100\t0\t0\t99.5"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_orders(path)
        finally:
            os.unlink(path)

    def test_rounding_dust_tolerated(self):
        # a cent of rounding is a ledger, not a lie
        path = write_tsv(["2026-11-01\tX\tfull:99:20\t88\t34\t20\t102.004"])
        try:
            orders = cl.load_orders(path)
            self.assertEqual(len(orders), 1)
        finally:
            os.unlink(path)


class ItemsParsingTest(unittest.TestCase):
    def test_demo_items_load(self):
        items = cl.load_items(ITEMS)
        self.assertEqual(len(items), 31)
        fillers = [it for it in items if it.filler == 1]
        self.assertEqual(len(fillers), 10)

    def test_bad_filler_flag_exit2(self):
        path = write_items(["2026-11-01\tX\tthing\t10\t2\tused\t2026-11-02"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_items(path)
        finally:
            os.unlink(path)

    def test_bad_fate_exit2(self):
        path = write_items(["2026-11-01\tX\tthing\t10\t1\teaten\t2026-11-02"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_items(path)
        finally:
            os.unlink(path)

    def test_open_row_with_date_exit2(self):
        path = write_items(["2026-11-01\tX\tthing\t10\t1\topen\t2026-11-02"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_items(path)
        finally:
            os.unlink(path)

    def test_settled_row_without_date_exit2(self):
        path = write_items(["2026-11-01\tX\tthing\t10\t1\tused\t"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_items(path)
        finally:
            os.unlink(path)

    def test_fate_before_buy_exit2(self):
        path = write_items(["2026-11-05\tX\tthing\t10\t1\tused\t2026-11-01"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_items(path)
        finally:
            os.unlink(path)

    def test_unknown_order_exit2_when_orders_given(self):
        orders = cl.load_orders(ORDERS)
        path = write_items(["2026-11-01\tO-999\tthing\t10\t1\tused\t2026-11-02"])
        try:
            with self.assertRaises(cl.LedgerError):
                cl.load_items(path, orders)
        finally:
            os.unlink(path)


# --------------------------------------------------------------- rule math

class RuleMathTest(unittest.TestCase):
    def test_full_discount_once(self):
        rule = cl.parse_rule("full:99:20")
        self.assertEqual(cl.rule_discount(rule, 98.0), 0.0)
        self.assertEqual(cl.rule_discount(rule, 99.0), 20.0)
        self.assertEqual(cl.rule_discount(rule, 500.0), 20.0)  # still once

    def test_every_discount_stacks(self):
        rule = cl.parse_rule("every:300:50")
        self.assertEqual(cl.rule_discount(rule, 299.0), 0.0)
        self.assertEqual(cl.rule_discount(rule, 300.0), 50.0)
        self.assertEqual(cl.rule_discount(rule, 600.0), 100.0)
        self.assertEqual(cl.rule_discount(rule, 1280.0), 200.0)

    def test_every_float_dust(self):
        rule = cl.parse_rule("every:300:50")
        # 299.999999... must still be one tier, 300.000000 dust-free
        self.assertEqual(cl.rule_discount(rule, 300 - 1e-9), 50.0)

    def test_none_rule(self):
        rule = cl.parse_rule("none")
        self.assertEqual(cl.rule_discount(rule, 9999.0), 0.0)

    def test_line_full_win_zone(self):
        kind, gap, d = cl.rule_line(cl.parse_rule("full:99:20"), 88.0)
        self.assertEqual(kind, "FILLABLE")
        self.assertAlmostEqual(gap, 11.0)
        self.assertEqual(d, 20.0)  # win zone [11, 20]

    def test_line_full_past_line(self):
        kind, gap, d = cl.rule_line(cl.parse_rule("full:99:20"), 120.0)
        self.assertEqual(kind, "NO_NEED")
        self.assertIsNone(gap)

    def test_line_full_unwinnable(self):
        kind, gap, d = cl.rule_line(cl.parse_rule("full:99:20"), 45.0)
        self.assertEqual(kind, "NOT_WORTH")
        self.assertAlmostEqual(gap, 54.0)

    def test_line_every_rest_zero(self):
        kind, gap, d = cl.rule_line(cl.parse_rule("every:300:50"), 600.0)
        self.assertEqual(kind, "NO_NEED")

    def test_line_every_unwinnable(self):
        kind, gap, d = cl.rule_line(cl.parse_rule("every:300:50"), 1280.0)
        self.assertEqual(kind, "NOT_WORTH")
        self.assertAlmostEqual(gap, 220.0)

    def test_unified_judgment_gap_vs_discount(self):
        # the same law on both shapes: g <= d -> FILLABLE, g > d -> NOT_WORTH
        for rule_s, subtotal, want in (
                ("full:99:20", 88.0, "FILLABLE"),     # g=11 <= 20
                ("full:99:20", 45.0, "NOT_WORTH"),    # g=54 > 20
                ("every:300:50", 268.0, "FILLABLE"),  # g=32 <= 50
                ("every:300:50", 320.0, "NOT_WORTH")):
            kind, gap, d = cl.rule_line(cl.parse_rule(rule_s), subtotal)
            self.assertEqual(kind, want, (rule_s, subtotal))


# ------------------------------------------------------------------ judge

class CandidateTest(unittest.TestCase):
    def test_fill_when_inside_win_zone(self):
        rule = cl.parse_rule("every:300:50")
        verdict, delta = cl.candidate_verdict(rule, 268.0, 32.0)
        self.assertEqual(verdict, "FILL")
        self.assertAlmostEqual(delta, -18.0)

    def test_miss_pays_full_price(self):
        rule = cl.parse_rule("every:300:50")
        verdict, delta = cl.candidate_verdict(rule, 268.0, 15.0)
        self.assertEqual(verdict, "OVERPAY")
        self.assertAlmostEqual(delta, 15.0)

    def test_overshoot_overpays_c_minus_d(self):
        rule = cl.parse_rule("full:99:20")
        verdict, delta = cl.candidate_verdict(rule, 88.0, 34.0)
        self.assertEqual(verdict, "OVERPAY")
        self.assertAlmostEqual(delta, 14.0)

    def test_gratuity_after_line(self):
        rule = cl.parse_rule("full:300:50")
        verdict, delta = cl.candidate_verdict(rule, 320.0, 25.0)
        self.assertEqual(verdict, "OVERPAY")
        self.assertAlmostEqual(delta, 25.0)


class BestComboTest(unittest.TestCase):
    def test_cheapest_subset_inside_zone(self):
        rule = cl.parse_rule("every:300:50")
        best = cl.best_combo(rule, 268.0, [15.0, 32.0, 49.0])
        self.assertIsNotNone(best)
        total, combo = best
        self.assertAlmostEqual(total, 32.0)
        self.assertEqual(len(combo), 1)

    def test_combo_uses_multiple_items(self):
        rule = cl.parse_rule("full:99:20")
        best = cl.best_combo(rule, 88.0, [6.0, 5.0, 30.0])
        self.assertIsNotNone(best)
        total, combo = best
        self.assertAlmostEqual(total, 11.0)  # 6 + 5 lands on the gap
        self.assertEqual(len(combo), 2)

    def test_no_combo_when_all_outside(self):
        rule = cl.parse_rule("every:300:50")
        self.assertIsNone(cl.best_combo(rule, 268.0, [70.0, 80.0]))  # all > d


class JudgeCmdTest(unittest.TestCase):
    def test_fillable_exit0(self):
        code, out = run_cli("judge", "--subtotal", "268",
                            "--rule", "every:300:50",
                            "--fill", "15", "--fill", "32")
        self.assertEqual(code, cl.EXIT_OK)
        self.assertIn("win zone [¥32.00, ¥50.00]", out)
        self.assertIn("best single pick: ¥32.00 (gain ¥18.00)", out)

    def test_not_worth_exit4(self):
        code, out = run_cli("judge", "--subtotal", "45",
                            "--rule", "full:99:20", "--fill", "54")
        self.assertEqual(code, cl.EXIT_RED)
        self.assertIn("NOT_WORTH", out)
        self.assertIn("buy nothing extra", out)

    def test_no_candidates_still_draws_the_line(self):
        code, out = run_cli("judge", "--subtotal", "268")
        self.assertEqual(code, cl.EXIT_OK)
        self.assertIn("gap ¥32.00", out)

    def test_all_candidates_lose_exit4(self):
        code, out = run_cli("judge", "--subtotal", "268",
                            "--rule", "every:300:50", "--fill", "70")
        self.assertEqual(code, cl.EXIT_RED)

    def test_no_need_says_keep_checkout(self):
        code, out = run_cli("judge", "--subtotal", "320",
                            "--rule", "full:300:50", "--fill", "10")
        self.assertEqual(code, cl.EXIT_OK)
        self.assertIn("nothing to chase", out)

    def test_negative_fill_rejected(self):
        code, _ = run_cli("judge", "--subtotal", "268", "--fill", "-5")
        self.assertEqual(code, cl.EXIT_DATA)

    def test_combo_reported_when_single_misses(self):
        code, out = run_cli("judge", "--subtotal", "88",
                            "--rule", "full:99:20",
                            "--fill", "6", "--fill", "5")
        self.assertEqual(code, cl.EXIT_OK)
        self.assertIn("best combo: ¥11.00 (¥6.00 + ¥5.00, 2 item(s), gain ¥9.00)", out)


# -------------------------------------------------------------- identities

class IdentityTest(unittest.TestCase):
    """The algebra of the illusion, pinned to 9 decimal places."""

    def setUp(self):
        self.orders = cl.load_orders(ORDERS)

    def totals(self):
        o = self.orders
        discount = sum(x.discount for x in o)
        filler = sum(x.filler for x in o)
        planned = sum(x.planned for x in o)
        paid = sum(x.paid for x in o)
        net = discount - filler
        free = sum(cl.per_order_facts(x)[0] for x in o)
        earned = discount - free
        bare = sum(cl.per_order_facts(x)[3] for x in o)
        return planned, filler, discount, paid, net, free, earned, bare

    def test_illusion_gap_equals_filler_total(self):
        _p, filler, discount, _paid, net, *_ = self.totals()
        self.assertAlmostEqual(discount - net - filler, 0.0, places=9)

    def test_demo_totals(self):
        planned, filler, discount, paid, net, free, earned, bare = self.totals()
        self.assertAlmostEqual(planned, 2709.0, places=9)
        self.assertAlmostEqual(filler, 232.0, places=9)
        self.assertAlmostEqual(discount, 460.0, places=9)
        self.assertAlmostEqual(paid, 2481.0, places=9)
        self.assertAlmostEqual(net, 228.0, places=9)
        self.assertAlmostEqual(free, 300.0, places=9)
        self.assertAlmostEqual(earned, 160.0, places=9)

    def test_free_plus_earned_is_discount(self):
        _p, _f, discount, _paid, _n, free, earned, _b = self.totals()
        self.assertAlmostEqual(free + earned - discount, 0.0, places=9)

    def test_cash_diff_is_filler_minus_earned(self):
        _p, filler, _d, paid, _n, _free, earned, bare = self.totals()
        cash_diff = paid - bare
        self.assertAlmostEqual(cash_diff, filler - earned, places=9)
        self.assertAlmostEqual(cash_diff, 72.0, places=9)

    def test_net_equals_free_minus_cash_diff(self):
        _p, _f, _d, paid, net, free, _e, bare = self.totals()
        self.assertAlmostEqual(net, free - (paid - bare), places=9)

    def test_filler_ratio(self):
        _p, filler, discount, *_ = self.totals()
        self.assertAlmostEqual(filler / discount, 0.5043, places=3)

    def test_platform_never_underestimates(self):
        # net_i <= discount_i for every order, since filler >= 0
        for o in self.orders:
            self.assertLessEqual(o.discount - o.filler, o.discount + 1e-9)


# ------------------------------------------------------------------- audit

class AuditCmdTest(unittest.TestCase):
    def test_demo_audit_red(self):
        code, out = run_cli("audit", ORDERS)
        self.assertEqual(code, cl.EXIT_RED)
        self.assertIn('you saved ¥460.00', out)
        self.assertIn('you really kept ¥228.00', out)
        self.assertIn('EXACTLY the filler total', out)
        self.assertIn("0.000000000", out)
        self.assertIn("50.4% of the discount", out)
        self.assertIn("¥1248.00/year", out)

    def test_overpaid_orders_named(self):
        code, out = run_cli("audit", ORDERS)
        self.assertIn("O-106", out)
        self.assertIn("O-102", out)
        self.assertIn("unwinnable", out)

    def test_green_season_exit0(self):
        rows = [
            "2026-11-01\tA\tevery:300:50\t280\t20\t50\t250",
            "2026-11-02\tB\tevery:300:50\t275\t25\t50\t250",
            "2026-11-03\tC\tevery:300:50\t299\t1\t50\t250",
            "2026-11-04\tD\tevery:300:50\t150\t0\t0\t150",
            "2026-11-05\tE\tevery:300:50\t600\t0\t100\t500",
        ]
        path = write_tsv(rows)
        try:
            code, out = run_cli("audit", path)
            self.assertEqual(code, cl.EXIT_OK)
            self.assertIn("VERDICT: GREEN", out)
            # ratio = 46/250 = 18.4%, net = 204 = free(150) - cash(−54)... check
            self.assertIn("illusion identity: discount - net - filler = 0.000000000", out)
        finally:
            os.unlink(path)

    def test_too_few_orders_exit3(self):
        rows = [
            "2026-11-01\tA\tnone\t100\t0\t0\t100",
            "2026-11-02\tB\tnone\t100\t0\t0\t100",
            "2026-11-03\tC\tnone\t100\t0\t0\t100",
        ]
        path = write_tsv(rows)
        try:
            code, _ = run_cli("audit", path)
            self.assertEqual(code, cl.EXIT_THIN)
        finally:
            os.unlink(path)

    def test_no_promotion_exit3(self):
        rows = ["2026-11-0%d\t%s\tnone\t100\t0\t0\t100" % (i, chr(64 + i))
                for i in range(1, 6)]
        path = write_tsv(rows)
        try:
            code, _ = run_cli("audit", path)
            self.assertEqual(code, cl.EXIT_THIN)
        finally:
            os.unlink(path)

    def test_custom_red_line(self):
        rows = [
            "2026-11-01\tA\tevery:300:50\t280\t20\t50\t250",
            "2026-11-02\tB\tevery:300:50\t275\t25\t50\t250",
            "2026-11-03\tC\tevery:300:50\t299\t1\t50\t250",
            "2026-11-04\tD\tevery:300:50\t150\t0\t0\t150",
            "2026-11-05\tE\tevery:300:50\t600\t0\t100\t500",
        ]
        path = write_tsv(rows)
        try:
            code, _ = run_cli("audit", path, "--red-line", "0.10")
            self.assertEqual(code, cl.EXIT_RED)  # 18.4% > 10%
        finally:
            os.unlink(path)


# -------------------------------------------------------------------- fate

class FateCmdTest(unittest.TestCase):
    def test_demo_fate_red(self):
        code, out = run_cli("fate", ORDERS, ITEMS)
        self.assertEqual(code, cl.EXIT_RED)
        self.assertIn("69.5%", out)               # filler junk rate (money)
        self.assertIn("vs planned items 14.1% — fillers die 4.9x faster", out)
        self.assertIn("coverage: filler items ¥232.00 of ¥232.00 (100.0%)", out)

    def test_open_rows_never_enter_the_denominator(self):
        # same settled rows plus one open filler: rates must not move
        base = write_items(
            ["2026-11-01\tO-101\ta\t30\t1\tused\t2026-11-02",
             "2026-11-01\tO-101\tb\t30\t1\tused\t2026-11-02",
             "2026-11-01\tO-101\tc\t30\t1\tused\t2026-11-02",
             "2026-11-01\tO-101\td\t30\t1\tidle\t2026-11-02",
             "2026-11-01\tO-101\te\t30\t1\ttrashed\t2026-11-02",
             "2026-11-01\tO-101\tf\t70\t0\tused\t2026-11-02"])
        with_open = write_items(
            ["2026-11-01\tO-101\ta\t30\t1\tused\t2026-11-02",
             "2026-11-01\tO-101\tb\t30\t1\tused\t2026-11-02",
             "2026-11-01\tO-101\tc\t30\t1\tused\t2026-11-02",
             "2026-11-01\tO-101\td\t30\t1\tidle\t2026-11-02",
             "2026-11-01\tO-101\te\t30\t1\ttrashed\t2026-11-02",
             "2026-11-01\tO-101\tz\t20\t1\topen\t",
             "2026-11-01\tO-101\tf\t70\t0\tused\t2026-11-02"])
        try:
            _c1, out1 = run_cli("fate", ORDERS, base)
            _c2, out2 = run_cli("fate", ORDERS, with_open)
            r1 = [ln for ln in out1.splitlines() if ln.startswith("filler items")][0]
            r2 = [ln for ln in out2.splitlines() if ln.startswith("filler items")][0]
            self.assertIn("40.0%", r1)   # 2/5 settled junked, by count
            self.assertIn("40.0%", r2)   # open changed nothing
        finally:
            os.unlink(base)
            os.unlink(with_open)

    def test_thin_filler_sample_exit3(self):
        path = write_items(
            ["2026-11-01\tO-101\ta\t30\t1\tused\t2026-11-02",
             "2026-11-01\tO-101\tb\t30\t1\tused\t2026-11-02"])
        try:
            code, out = run_cli("fate", ORDERS, path)
            self.assertEqual(code, cl.EXIT_THIN)
        finally:
            os.unlink(path)

    def test_low_coverage_withholds_verdict(self):
        rows = ["2026-11-0%d\t%s\tevery:300:50\t280\t20\t50\t250" % (i, chr(64 + i))
                for i in range(1, 6)]
        orders_path = write_tsv(rows)
        items_path = write_items(
            ["2026-11-01\tA\ta\t1.0\t1\tidle\t2026-11-02",
             "2026-11-01\tA\tb\t1.0\t1\tused\t2026-11-02",
             "2026-11-01\tA\tc\t1.0\t1\tused\t2026-11-02",
             "2026-11-01\tA\td\t1.0\t1\tused\t2026-11-02",
             "2026-11-01\tA\te\t2.0\t1\ttrashed\t2026-11-02",
             "2026-11-01\tA\tf\t2.0\t1\tused\t2026-11-02",   # ¥8 of ¥100 = 8%
             "2026-11-01\tA\tg\t70\t0\tused\t2026-11-02"])
        try:
            code, out = run_cli("fate", orders_path, items_path)
            self.assertEqual(code, cl.EXIT_OK)
            self.assertIn("BELOW 50.0%", out)
            self.assertIn("withheld", out)
            self.assertNotIn("VERDICT: RED", out)
        finally:
            os.unlink(orders_path)
            os.unlink(items_path)

    def test_orders_without_fillers_exit3(self):
        rows = ["2026-11-0%d\t%s\tnone\t100\t0\t0\t100" % (i, chr(64 + i))
                for i in range(1, 6)]
        orders_path = write_tsv(rows)
        items_path = write_items(
            ["2026-11-01\tA\tf\t70\t0\tused\t2026-11-02"])
        try:
            code, _ = run_cli("fate", orders_path, items_path)
            self.assertEqual(code, cl.EXIT_THIN)
        finally:
            os.unlink(orders_path)
            os.unlink(items_path)


# ---------------------------------------------------------------- simulate

class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.orders = cl.load_orders(ORDERS)
        self.by_id = {o.oid: o for o in self.orders}

    def test_best_is_a_true_minimum(self):
        # brute-force every filler amount on a cent grid: nothing beats "best"
        for o in self.orders:
            _bare, _at, best, _op, _m = cl.replay_order(o)
            step = 1.0
            limit = 400.0
            c = 0.0
            while c <= limit:
                total = o.planned + c
                paid = total - cl.rule_discount(o.rule, total)
                self.assertGreaterEqual(paid, best - 0.005, (o.oid, c))
                c += step

    def test_best_never_exceeds_bare_buy(self):
        for o in self.orders:
            bare, _at, best, _op, _m = cl.replay_order(o)
            self.assertLessEqual(best, bare + 1e-9)

    def test_demo_replay_money(self):
        sums = [cl.replay_order(o) for o in self.orders]
        self.assertAlmostEqual(sum(s[2] for s in sums), 2364.0, places=9)
        self.assertAlmostEqual(sum(s[0] for s in sums), 2409.0, places=9)
        self.assertAlmostEqual(sum(s[3] for s in sums), 117.0, places=9)

    def test_mistake_taxonomy(self):
        taxonomy = {
            "O-101": None,        # filled the line exactly
            "O-102": "OVERFILLED",
            "O-103": None,        # walked away from an unwinnable line
            "O-104": None,        # filled the line exactly
            "O-105": None,        # no fill worth making
            "O-106": "FORCED",
            "O-107": "GRATUITY",
            "O-108": "OVERFILLED",  # one yuan past the line
        }
        for oid, want in taxonomy.items():
            _b, _a, _best, _op, mistake = cl.replay_order(self.by_id[oid])
            self.assertEqual(mistake, want, oid)

    def test_undershot_classified(self):
        # FILLABLE line, filler below the gap: paid > best, never crossed
        o = cl.Order()
        o.line = 1
        o.date = date(2026, 11, 1)
        o.oid = "T"
        o.rule = cl.parse_rule("every:300:50")
        o.planned, o.filler, o.discount, o.paid = 268.0, 15.0, 50.0, 283.0
        _bare, _at, best, overpay, mistake = cl.replay_order(o)
        self.assertAlmostEqual(best, 250.0, places=9)
        self.assertAlmostEqual(overpay, 33.0, places=9)
        self.assertEqual(mistake, "UNDERSHOT")

    def test_simulate_always_exit0(self):
        code, out = run_cli("simulate", ORDERS)
        self.assertEqual(code, cl.EXIT_OK)
        self.assertIn("best decision      ¥2364.00", out)
        self.assertIn("never any filler   ¥2409.00", out)
        self.assertIn("what you paid      ¥2481.00", out)
        self.assertIn("replay is a mirror", out)

    def test_simulate_names_mistakes(self):
        _code, out = run_cli("simulate", ORDERS)
        self.assertIn("FORCED", out)
        self.assertIn("GRATUITY", out)
        self.assertIn("OVERFILLED", out)
        self.assertIn("(O-106)", out)


# ---------------------------------------------------------------- validate

class ValidateCmdTest(unittest.TestCase):
    def test_demo_validate_ok(self):
        code, out = run_cli("validate", ORDERS, ITEMS)
        self.assertEqual(code, cl.EXIT_OK)
        self.assertIn("worst residual:                    0.000000000  -> OK", out)
        self.assertIn("filler value coverage:             100.0%", out)
        self.assertIn("planned value coverage:            100.0%", out)

    def test_validate_orders_only(self):
        code, out = run_cli("validate", ORDERS)
        self.assertEqual(code, cl.EXIT_OK)
        self.assertNotIn("coverage", out)


# ----------------------------------------------------------------- e2e/cli

class CliBehaviourTest(unittest.TestCase):
    def test_no_command_prints_usage_exit2(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cl.main([])
        self.assertEqual(code, cl.EXIT_DATA)
        self.assertIn("usage:", buf.getvalue())

    def test_version_flag(self):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                cl.build_parser().parse_args(["--version"])
        except SystemExit as exc:
            self.assertEqual(exc.code, 0)
        self.assertIn("cart-line", buf.getvalue())

    def test_examples_snapshots_byte_exact(self):
        proc = subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "examples", "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)

    def test_demo_all_commands_exit_codes(self):
        self.assertEqual(run_cli("audit", ORDERS)[0], 4)
        self.assertEqual(run_cli("fate", ORDERS, ITEMS)[0], 4)
        self.assertEqual(run_cli("simulate", ORDERS)[0], 0)
        self.assertEqual(run_cli("validate", ORDERS, ITEMS)[0], 0)


if __name__ == "__main__":
    unittest.main()
