# -*- coding: utf-8 -*-
"""recoup 验收测试：解析重放 / 状态机边界 / 恒等式 / 弹性 / 拒答与 exit 码."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import recoup  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "examples", "events.tsv")


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = recoup.main(argv)
    return code, buf.getvalue()


def write_ledger(rows):
    """rows: list of tab-joined strings; returns temp file path."""
    body = "date\titem\taction\tamount\tpaid\tcategory\tnote\n"
    body += "".join(row + "\n" for row in rows)
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


# 三周期达标底账：1 sold（furniture n=1）+ 1 gave + 1 open(YELLOW)，span 55d
BASE = [
    "2026-01-05\t台灯\tlist\t80\t299\tfurniture",
    "2026-01-06\t椅子\tlist\t100\t399\tfurniture",
    "2026-01-06\t书\tlist\t30\t90\tbook",
    "2026-01-20\t台灯\task\t60",
    "2026-02-10\t台灯\tsold\t60",
    "2026-03-01\t椅子\tgave",
]


class ParseReplay(unittest.TestCase):
    def test_base_ledger_replays(self):
        path = write_ledger(BASE)
        ledger = recoup.load_ledger(path, None, {})
        self.assertEqual(len(ledger.lots), 3)
        self.assertEqual(len(ledger.open_lots), 1)
        self.assertEqual(ledger.as_of, date(2026, 3, 1))

    def test_default_asof_is_ledger_end_not_today(self):
        path = write_ledger(BASE)
        ledger = recoup.load_ledger(path, None, {})
        self.assertEqual(ledger.as_of, date(2026, 3, 1))

    def test_price_moves_current_price(self):
        rows = BASE + ["2026-02-01\t书\tprice\t25"]
        path = write_ledger(rows)
        ledger = recoup.load_ledger(path, None, {})
        book = ledger.open_lots[0]
        self.assertEqual(book.current_price, 25)
        self.assertEqual(len(book.reductions), 1)

    def test_asks_collect_offers(self):
        path = write_ledger(BASE)
        lamp = ledger = recoup.load_ledger(path, None, {})
        lots = {lot.item: lot for lot in ledger.lots}
        self.assertEqual(lots["台灯"].n_asks, 1)
        self.assertEqual(lots["台灯"].max_offer, 60)

    def test_relist_after_close_starts_new_lot(self):
        rows = BASE + ["2026-03-05\t椅子\tlist\t90\t399\tfurniture"]
        path = write_ledger(rows)
        ledger = recoup.load_ledger(path, None, {})
        self.assertEqual(len(ledger.lots), 4)
        self.assertEqual(len(ledger.open_lots), 2)

    def test_future_events_truncated_not_error(self):
        path = write_ledger(BASE + ["2026-09-01\t书\ttrash"])
        ledger = recoup.load_ledger(path, date(2026, 3, 1), {})
        self.assertEqual(ledger.ignored_events, 1)
        self.assertEqual(len(ledger.open_lots), 1)

    def test_blank_lines_tolerated(self):
        path = write_ledger(BASE)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n")
        ledger = recoup.load_ledger(path, None, {})
        self.assertEqual(len(ledger.lots), 3)


class StructuralErrors(unittest.TestCase):
    def expect_broken(self, rows):
        path = write_ledger(rows)
        with self.assertRaises(recoup.Broken):
            recoup.load_ledger(path, None, {})

    def test_event_before_list(self):
        self.expect_broken(["2026-01-05\t书\task\t50"])

    def test_double_list_while_open(self):
        self.expect_broken([
            "2026-01-05\t书\tlist\t30\t90\tbook",
            "2026-01-06\t书\tlist\t20\t90\tbook",
        ])

    def test_event_after_close(self):
        self.expect_broken([
            "2026-01-05\t书\tlist\t30\t90\tbook",
            "2026-01-10\t书\tgave",
            "2026-01-11\t书\task\t20",
        ])

    def test_sold_requires_amount(self):
        self.expect_broken([
            "2026-01-05\t书\tlist\t30\t90\tbook",
            "2026-01-10\t书\tsold",
        ])

    def test_close_action_rejects_amount(self):
        self.expect_broken([
            "2026-01-05\t书\tlist\t30\t90\tbook",
            "2026-01-10\t书\tgave\t5",
        ])

    def test_bad_date(self):
        self.expect_broken(["2026-13-05\t书\tlist\t30\t90\tbook"])

    def test_negative_amount(self):
        self.expect_broken(["2026-01-05\t书\tlist\t-5\t90\tbook"])

    def test_zero_paid(self):
        self.expect_broken(["2026-01-05\t书\tlist\t30\t0\tbook"])

    def test_unknown_action(self):
        self.expect_broken(["2026-01-05\t书\tswap\t30"])

    def test_unknown_category(self):
        self.expect_broken(["2026-01-05\t书\tlist\t30\t90\tcar"])

    def test_list_requires_category(self):
        self.expect_broken(["2026-01-05\t书\tlist\t30\t90"])

    def test_broken_exit_code_via_cli(self):
        path = write_ledger(["2026-01-05\t书\task\t50"])
        code, out = run_cli(["report", path])
        self.assertEqual(code, recoup.EXIT_BROKEN)
        self.assertIn("BROKEN", out)

    def test_header_missing_column(self):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("date\titem\taction\n2026-01-05\t书\tlist\n")
        code, out = run_cli(["validate", path])
        self.assertEqual(code, recoup.EXIT_BROKEN)


class LightMachine(unittest.TestCase):
    """零询价路径 GREEN→YELLOW→DEAD 与出手线，边界值钉死。"""

    def light(self, ask, price, paid, age_days, dead_days=100, asks=None):
        lot = recoup.Lot("x", "other", paid, date(2026, 1, 1))
        lot.prices = [(date(2026, 1, 1), price)]
        for i, amount in enumerate(asks or []):
            lot.asks.append((date(2026, 1, 2 + i), amount))
        as_of = date(2026, 1, 1)
        from datetime import timedelta
        as_of = as_of + timedelta(days=age_days)
        table = {"other": (50, dead_days, 0.35)}
        return recoup.light_for(lot, as_of, table)[0]

    def test_green_below_half_line(self):
        self.assertEqual(self.light(None, 50, 100, 49, 100), "GREEN")

    def test_yellow_exactly_at_half_line(self):
        self.assertEqual(self.light(None, 50, 100, 50, 100), "YELLOW")

    def test_yellow_below_line(self):
        self.assertEqual(self.light(None, 50, 100, 99, 100), "YELLOW")

    def test_dead_exactly_at_line(self):
        self.assertEqual(self.light(None, 50, 100, 100, 100), "DEAD")

    def test_low_offer_with_interest_is_yellow(self):
        self.assertEqual(self.light(None, 100, 100, 30, 100, asks=[50]), "YELLOW")

    def test_offer_line_exactly_at_80pct_is_red(self):
        self.assertEqual(self.light(None, 100, 100, 30, 100, asks=[80]), "RED")

    def test_just_below_offer_line_not_red(self):
        self.assertEqual(self.light(None, 100, 100, 30, 100, asks=[79.9]), "YELLOW")

    def test_low_offer_past_line_is_fantasy_red(self):
        self.assertEqual(self.light(None, 100, 100, 120, 100, asks=[10]), "RED")

    def test_offer_line_beats_dead(self):
        # 有高出价在架永远不判 DEAD：钱包在敲门
        self.assertEqual(self.light(None, 100, 100, 200, 100, asks=[90]), "RED")

    def test_light_monotonic_for_zero_ask_lot(self):
        seq = [self.light(None, 50, 100, d, 100) for d in (10, 60, 120)]
        self.assertEqual(seq, ["GREEN", "YELLOW", "DEAD"])


class LotProperties(unittest.TestCase):
    def test_max_offer_ignores_bare_asks(self):
        lot = recoup.Lot("x", "other", 100, date(2026, 1, 1))
        lot.asks = [(date(2026, 1, 2), None), (date(2026, 1, 3), 40)]
        self.assertEqual(lot.max_offer, 40)
        self.assertEqual(lot.n_asks, 2)

    def test_bare_ask_only_has_no_offer(self):
        lot = recoup.Lot("x", "other", 100, date(2026, 1, 1))
        lot.asks = [(date(2026, 1, 2), None)]
        self.assertIsNone(lot.max_offer)

    def test_reductions_only_count_price_drops(self):
        lot = recoup.Lot("x", "other", 100, date(2026, 1, 1))
        lot.prices = [(date(2026, 1, 1), 100), (date(2026, 1, 5), 120),
                      (date(2026, 1, 9), 90)]
        self.assertEqual(len(lot.reductions), 1)

    def test_implied_ratio(self):
        lot = recoup.Lot("x", "other", 200, date(2026, 1, 1))
        lot.prices = [(date(2026, 1, 1), 150)]
        self.assertAlmostEqual(lot.implied_ratio(), 0.75)


class Identities(unittest.TestCase):
    """恒等式：漏斗守恒 / 回血加总 / 金额加权 / simulate 敞口分解。"""

    def test_funnel_conservation(self):
        ledger = recoup.load_ledger(EXAMPLES, date(2026, 8, 20), {})
        closed = [lot for lot in ledger.lots if lot.closed]
        tally = {}
        for lot in closed:
            tally[lot.closed[1]] = tally.get(lot.closed[1], 0) + 1
        self.assertEqual(sum(tally.values()) + len(ledger.open_lots), len(ledger.lots))
        self.assertEqual(tally, {"sold": 4, "gave": 1, "trash": 1, "pull": 1})

    def test_cash_in_matches_categories_total(self):
        ledger = recoup.load_ledger(EXAMPLES, date(2026, 8, 20), {})
        stats = recoup.category_stats(ledger)
        total = sum(st.sold_amount for st in stats.values())
        self.assertAlmostEqual(total, 1810.0, places=6)

    def test_realized_ratio_is_money_weighted(self):
        ledger = recoup.load_ledger(EXAMPLES, date(2026, 8, 20), {})
        stats = recoup.category_stats(ledger)
        cash = sum(st.sold_amount for st in stats.values())
        paid = sum(st.paid_amount for st in stats.values())
        self.assertAlmostEqual(cash / paid, 1810 / 5596, places=9)

    def test_simulate_window_decomposition(self):
        ledger = recoup.load_ledger(EXAMPLES, date(2026, 8, 20), {})
        table = recoup.CATEGORY_PRIOR
        stats = recoup.category_stats(ledger)
        upper = lower = 0.0
        for lot in ledger.open_lots:
            base, _ = recoup.baseline_ratio(lot.category, stats, table)
            upper += lot.paid * base
            light, _ = recoup.light_for(lot, ledger.as_of, table)
            if light != "DEAD":
                lower += lot.paid * base
        # DEAD 在架 = 平板(0.45×3588) + 冲锋衣(0.25×1299)
        expected_gap = 3588 * 0.45 + 1299 * 0.25
        self.assertAlmostEqual(upper - lower, expected_gap, places=6)

    def test_report_cash_in_printed(self):
        code, out = run_cli(["report", EXAMPLES, "--as-of", "2026-08-20"])
        self.assertIn("¥1,810", out)
        self.assertIn("32.3%", out)

    def test_categories_cash_check_line(self):
        code, out = run_cli(["categories", EXAMPLES, "--as-of", "2026-08-20"])
        self.assertIn("cash-in check: ¥1,810", out)


class PriorAndCalibration(unittest.TestCase):
    def test_prior_fallback_below_three_sales(self):
        ledger = recoup.load_ledger(EXAMPLES, date(2026, 8, 20), {})
        stats = recoup.category_stats(ledger)
        ratio, prior = recoup.baseline_ratio("electronics", stats, recoup.CATEGORY_PRIOR)
        self.assertTrue(prior)
        self.assertEqual(ratio, 0.45)

    def test_own_sales_win_at_three(self):
        path = write_ledger([
            "2026-01-01\tA\tlist\t100\t100\telectronics",
            "2026-01-05\tA\tsold\t90",
            "2026-01-02\tB\tlist\t100\t100\telectronics",
            "2026-01-06\tB\tsold\t90",
            "2026-01-03\tC\tlist\t100\t100\telectronics",
            "2026-01-07\tC\tsold\t90",
            "2026-01-04\tD\tlist\t100\t100\telectronics",
        ])
        ledger = recoup.load_ledger(path, None, {})
        stats = recoup.category_stats(ledger)
        ratio, prior = recoup.baseline_ratio("electronics", stats, recoup.CATEGORY_PRIOR)
        self.assertFalse(prior)
        self.assertAlmostEqual(ratio, 0.9)

    def test_cat_override_extends_table(self):
        path = write_ledger(["2026-01-05\t胶片机\tlist\t500\t2000\tcamera"])
        override = recoup.load_category_overrides(["camera:40:120:0.6"])
        table = dict(recoup.CATEGORY_PRIOR)
        table.update(override)
        ledger = recoup.load_ledger(path, None, override)
        stats = recoup.category_stats(ledger)
        ratio, prior = recoup.baseline_ratio("camera", stats, table)
        self.assertTrue(prior)
        self.assertEqual(ratio, 0.6)

    def test_percentile_interpolation(self):
        self.assertEqual(recoup.percentile([10, 20, 30], 0.5), 20)
        self.assertEqual(recoup.percentile([10, 20], 0.9), 19)
        self.assertIsNone(recoup.percentile([], 0.5))


class Elasticity(unittest.TestCase):
    def cuts(self, rows, as_of="2026-02-15"):
        path = write_ledger(rows)
        return run_cli(["elastic", path, "--as-of", as_of])

    def test_three_observable_reductions_required(self):
        rows = [
            "2026-01-01\tA\tlist\t100\t200\tother",
            "2026-01-10\tA\tprice\t90",
            "2026-01-20\tA\tprice\t80",
            "2026-01-02\tB\tlist\t100\t300\tother",
            "2026-01-03\tC\tlist\t100\t300\tother",
        ]
        code, out = self.cuts(rows)
        self.assertEqual(code, recoup.EXIT_DECLINE)
        self.assertIn("DECLINE", out)

    def test_responsive_verdict(self):
        rows = [
            "2026-01-01\tA\tlist\t100\t200\tother",
            "2026-01-10\tA\tprice\t90",
            "2026-01-15\tA\task",
            "2026-01-20\tA\tprice\t80",
            "2026-01-25\tA\task",
            "2026-01-25\tA\task",
            "2026-02-01\tA\tprice\t70",
            "2026-02-05\tA\task",
            "2026-02-05\tA\task",
            "2026-02-05\tA\task",
            "2026-02-06\tA\task",
            "2026-01-02\tB\tlist\t100\t300\tother",
            "2026-01-03\tC\tlist\t100\t300\tother",
        ]
        code, out = self.cuts(rows)
        self.assertEqual(code, recoup.EXIT_OK)
        self.assertIn("RESPONSIVE", out)

    def test_no_response_verdict(self):
        rows = [
            "2026-01-01\tA\tlist\t100\t200\tother",
            "2026-01-10\tA\tprice\t90",
            "2026-01-20\tA\tprice\t80",
            "2026-02-01\tA\tprice\t70",
            "2026-01-02\tB\tlist\t100\t300\tother",
            "2026-01-03\tC\tlist\t100\t300\tother",
        ]
        code, out = self.cuts(rows)
        self.assertEqual(code, recoup.EXIT_OK)
        self.assertIn("NO-RESPONSE", out)

    def test_weak_verdict(self):
        rows = [
            "2026-01-01\tA\tlist\t100\t200\tother",
            "2026-01-10\tA\tprice\t90",
            "2026-01-15\tA\task",
            "2026-01-20\tA\tprice\t80",
            "2026-01-25\tA\task",
            "2026-02-01\tA\tprice\t70",
            "2026-02-05\tA\task",
            "2026-01-02\tB\tlist\t100\t300\tother",
            "2026-01-03\tC\tlist\t100\t300\tother",
        ]
        code, out = self.cuts(rows)
        self.assertEqual(code, recoup.EXIT_OK)
        self.assertIn("WEAK", out)

    def test_price_rise_not_counted_as_reduction(self):
        rows = [
            "2026-01-01\tA\tlist\t100\t200\tother",
            "2026-01-10\tA\tprice\t110",
            "2026-01-20\tA\tprice\t120",
            "2026-01-02\tB\tlist\t100\t300\tother",
            "2026-01-03\tC\tlist\t100\t300\tother",
        ]
        code, out = self.cuts(rows)
        self.assertEqual(code, recoup.EXIT_DECLINE)


class Gates(unittest.TestCase):
    """拒答 exit 3 与红线 exit 4。"""

    def test_too_few_lots_declined(self):
        path = write_ledger([
            "2026-01-05\t书\tlist\t30\t90\tbook",
            "2026-02-05\t书\ttrash",
        ])
        code, out = run_cli(["report", path])
        self.assertEqual(code, recoup.EXIT_DECLINE)

    def test_short_span_declined(self):
        path = write_ledger([
            "2026-01-05\t书\tlist\t30\t90\tbook",
            "2026-01-06\t椅\tlist\t30\t90\tbook",
            "2026-01-07\t灯\tlist\t30\t90\tbook",
        ])
        code, out = run_cli(["report", path])
        self.assertEqual(code, recoup.EXIT_DECLINE)
        self.assertIn("span", out)

    def test_hoarding_alarm_two_x_white_gift(self):
        path = write_ledger(BASE + [
            "2026-01-07\t旧椅\tlist\t50\t200\tother",
        ])
        # 旧椅 zero asks, age = 1/7 → 3/1 = 53d < 2×91; 用 --cat 缩短白送线到 26d
        code, out = run_cli(["stale", path, "--as-of", "2026-03-01",
                             "--cat", "other:10:26:0.35"])
        self.assertEqual(code, recoup.EXIT_REDLINE)
        self.assertIn("hoarding", out)

    def test_verdict_unknown_item_declined(self):
        path = write_ledger(BASE)
        code, out = run_cli(["verdict", path, "相机"])
        self.assertEqual(code, recoup.EXIT_DECLINE)

    def test_verdict_sold_is_ok(self):
        path = write_ledger(BASE)
        code, out = run_cli(["verdict", path, "台灯"])
        self.assertEqual(code, recoup.EXIT_OK)
        self.assertIn("SOLD", out)

    def test_verdict_dead_two_x_exit4(self):
        path = write_ledger(BASE + [
            "2026-01-07\t旧椅\tlist\t50\t200\tother",
        ])
        code, out = run_cli(["verdict", path, "旧椅", "--as-of", "2026-03-01",
                             "--cat", "other:10:26:0.35"])
        self.assertEqual(code, recoup.EXIT_REDLINE)
        self.assertIn("DEAD", out)

    def test_verdict_offer_line_exit4(self):
        path = write_ledger(BASE + [
            "2026-01-07\t旧椅\tlist\t100\t200\tother",
            "2026-01-08\t旧椅\task\t85",
        ])
        code, out = run_cli(["verdict", path, "旧椅", "--as-of", "2026-03-01"])
        self.assertEqual(code, recoup.EXIT_REDLINE)
        self.assertIn("offer line", out)

    def test_anchor_gap_alarm_exit4(self):
        path = write_ledger([
            "2026-01-05\t书\tlist\t50\t100\tbook",
            "2026-01-20\t书\tsold\t50",
            "2026-01-06\t相机\tlist\t9000\t10000\telectronics",
            "2026-01-07\t镜头\tlist\t8500\t10000\telectronics",
        ])
        code, out = run_cli(["report", path, "--as-of", "2026-02-28"])
        self.assertEqual(code, recoup.EXIT_REDLINE)
        self.assertIn("ALARM", out)
        self.assertIn("anchor gap", out)

    def test_simulate_empty_shelf_ok(self):
        path = write_ledger([
            "2026-01-05\t书\tlist\t30\t90\tbook",
            "2026-02-05\t书\tgave",
        ])
        code, out = run_cli(["simulate", path])
        self.assertEqual(code, recoup.EXIT_OK)
        self.assertIn("nothing on the shelf", out)

    def test_simulate_declines_short_span(self):
        path = write_ledger([
            "2026-01-05\t书\tlist\t30\t90\tbook",
            "2026-01-06\t椅\tlist\t30\t90\tbook",
            "2026-01-07\t灯\tlist\t30\t90\tbook",
        ])
        code, out = run_cli(["simulate", path])
        self.assertEqual(code, recoup.EXIT_DECLINE)


class EndToEnd(unittest.TestCase):
    def test_report_redline_on_examples(self):
        code, out = run_cli(["report", EXAMPLES, "--as-of", "2026-08-20"])
        self.assertEqual(code, recoup.EXIT_REDLINE)
        self.assertIn("hoarding", out)

    def test_light_tally_on_report(self):
        code, out = run_cli(["report", EXAMPLES, "--as-of", "2026-08-20"])
        self.assertEqual(code, recoup.EXIT_REDLINE)
        for light, count in (("DEAD", 2), ("RED", 2), ("YELLOW", 2), ("GREEN", 1)):
            rows = [line for line in out.splitlines()
                    if line.strip().startswith(light + " ")]
            self.assertTrue(rows, light)
            self.assertIn(str(count), rows[0])

    def test_elastic_responsive_on_examples(self):
        code, out = run_cli(["elastic", EXAMPLES, "--as-of", "2026-08-20"])
        self.assertEqual(code, recoup.EXIT_OK)
        self.assertIn("RESPONSIVE", out)

    def test_asof_truncation_discloses_ignored(self):
        code, out = run_cli(["report", EXAMPLES, "--as-of", "2026-05-31"])
        self.assertEqual(code, recoup.EXIT_OK)
        self.assertIn("11 event(s) after as-of ignored", out)

    def test_asof_before_all_events_is_broken(self):
        code, out = run_cli(["report", EXAMPLES, "--as-of", "2026-02-01"])
        self.assertEqual(code, recoup.EXIT_BROKEN)

    def test_determinism_same_output_twice(self):
        argv = ["report", EXAMPLES, "--as-of", "2026-08-20"]
        first = run_cli(argv)
        second = run_cli(argv)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
