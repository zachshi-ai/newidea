#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance tests for dusty-subs.

Every README acceptance criterion maps to at least one test here. The
committed demo data (examples/demo-data/) doubles as the end-to-end
fixture: three years of one person's statement with eight subscriptions,
two rejected look-alikes and one ignored rent row, whose exact numbers
were verified by hand when the fixture was designed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import dusty_subs as ds  # noqa: E402

DEMO_BANK = os.path.join(ROOT, "examples", "demo-data", "bank.csv")
DEMO_USAGE = os.path.join(ROOT, "examples", "demo-data", "usage.csv")
CLI = os.path.join(ROOT, "dusty_subs.py")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, CLI] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True)


def write_file(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def debits(days, amount=30.0, desc="M"):
    return [ds.Debit(day=d, desc=desc, amount=amount) for d in days]


# ---------------------------------------------------------------------------
# Formatting


class MoneyFormatTests(unittest.TestCase):
    def test_integer_money_gets_no_decimals(self):
        self.assertEqual(ds.fmt_money(10498.0), "10,498")

    def test_fractional_money_keeps_two_places(self):
        self.assertEqual(ds.fmt_money(3520.484), "3,520.48")

    def test_pct_rounds_to_whole_percent_with_sign(self):
        self.assertEqual(ds.fmt_pct(0.129), "+13%")
        self.assertEqual(ds.fmt_pct(-0.051), "-5%")


# ---------------------------------------------------------------------------
# Merchant normalization


class NormalizeTests(unittest.TestCase):
    def test_case_and_reference_numbers_collapse(self):
        self.assertEqual(ds.normalize("NETFLIX.COM 8665797172 CA"),
                         "netflix com ca")

    def test_punctuation_and_card_tails_collapse(self):
        self.assertEqual(ds.normalize("P9RSK*SPOTIFY-STOCKHOLM, 4029357733"),
                         "p9rsk spotify stockholm")

    def test_chinese_descriptors_keep_their_words_drop_their_ids(self):
        self.assertEqual(ds.normalize("订单88231 超级猩猩月卡"),
                         "订单 超级猩猩月卡")

    def test_single_digits_survive_double_digits_go(self):
        self.assertEqual(ds.normalize("PS PLUS 3 MONTH 12"), "ps plus 3 month")


# ---------------------------------------------------------------------------
# Statement parsing


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name, text):
        return write_file(os.path.join(self.tmp.name, name), text)

    def test_chinese_headers_with_type_column(self):
        p = self.path("zh.csv",
                      "日期,摘要,金额,类型\n"
                      "2026-01-05,会员,30,支出\n"
                      "2026-01-06,工资,8000,收入\n")
        stmt = ds.read_statement(p)
        self.assertEqual(len(stmt.debits), 1)
        self.assertEqual(stmt.debits[0].desc, "会员")

    def test_english_headers_negative_amounts(self):
        p = self.path("en.csv",
                      "Date,Description,Amount\n"
                      "2026-01-05,NETFLIX,-30.00\n"
                      "2026-01-06,SALARY,3000.00\n")
        stmt = ds.read_statement(p)
        self.assertEqual([d.amount for d in stmt.debits], [30.0])
        self.assertTrue(any("negative amounts" in n for n in stmt.notes))

    def test_all_positive_without_type_column_assumes_debits(self):
        p = self.path("pos.csv",
                      "date,description,amount\n"
                      "2026-01-05,会员,30\n"
                      "2026-01-06,会员,30\n")
        stmt = ds.read_statement(p)
        self.assertEqual(len(stmt.debits), 2)
        self.assertTrue(any("assumed to be a debit" in n for n in stmt.notes))

    def test_utf8_bom_from_excel_exports(self):
        p = os.path.join(self.tmp.name, "bom.csv")
        with open(p, "w", encoding="utf-8-sig") as fh:
            fh.write("日期,摘要,金额,类型\n2026-01-05,会员,30,支出\n")
        self.assertEqual(len(ds.read_statement(p).debits), 1)

    def test_tab_delimiter(self):
        p = self.path("tsv.csv",
                      "date\tdescription\tamount\n"
                      "2026-01-05\t会员\t30\n")
        self.assertEqual(len(ds.read_statement(p).debits), 1)

    def test_currency_symbols_and_thousands(self):
        p = self.path("cur.csv",
                      'date,description,amount\n'
                      '2026-01-05,X,"¥1,234.50"\n')
        self.assertEqual(ds.read_statement(p).debits[0].amount, 1234.5)

    def test_date_formats(self):
        p = self.path("dates.csv",
                      "date,description,amount\n"
                      "2026-01-05,A,1\n2026/02/05,B,2\n"
                      "2026.03.05,C,3\n20260405,D,4\n")
        days = [d.day for d in ds.read_statement(p).debits]
        self.assertEqual(days, ["2026-01-05", "2026-02-05",
                                "2026-03-05", "2026-04-05"])

    def test_malformed_rows_are_skipped_and_counted(self):
        p = self.path("bad.csv",
                      "date,description,amount\n"
                      "2026-01-05,A,30\n"
                      "not-a-date,B,30\n"
                      "2026-02-05,C,thirty\n"
                      "\n"
                      "2026-03-05\n")
        stmt = ds.read_statement(p)
        self.assertEqual(len(stmt.debits), 1)
        self.assertTrue(any("3 malformed row(s)" in n for n in stmt.notes))

    def test_exact_duplicates_dropped_and_counted(self):
        p = self.path("dup.csv",
                      "date,description,amount\n"
                      "2026-01-05,A,30\n2026-01-05,A,30\n")
        stmt = ds.read_statement(p)
        self.assertEqual(len(stmt.debits), 1)
        self.assertTrue(any("1 duplicate row(s)" in n for n in stmt.notes))

    def test_missing_required_column_is_an_error(self):
        p = self.path("noamount.csv", "date,description\n2026-01-05,A\n")
        with self.assertRaises(ds.StatementError):
            ds.read_statement(p)

    def test_missing_file_and_empty_file_are_errors(self):
        with self.assertRaises(ds.StatementError):
            ds.read_statement(os.path.join(self.tmp.name, "nope.csv"))
        p = self.path("empty.csv", "")
        with self.assertRaises(ds.StatementError):
            ds.read_statement(p)


# ---------------------------------------------------------------------------
# Detection


class DetectTests(unittest.TestCase):
    def evaluate(self, days, amounts=None):
        rows = [ds.Debit(day=d, desc="M",
                         amount=amounts[i] if amounts else 30.0)
                for i, d in enumerate(days)]
        return ds.evaluate_group("m", "M", rows, ds.DEFAULT_MIN_HITS,
                                 ds.DEFAULT_GAP_CV, ds.DEFAULT_AMOUNT_TOL,
                                 ds.DEFAULT_AMOUNT_MIN)

    def test_four_monthly_hits_form_a_subscription(self):
        sub, rej = self.evaluate(["2026-01-10", "2026-02-10",
                                  "2026-03-10", "2026-04-10"])
        self.assertIsNone(rej)
        self.assertEqual(sub.cycle, "monthly")
        self.assertAlmostEqual(sub.annualized, 353.23, places=2)  # 30*365/31

    def test_fewer_than_min_hits_is_a_one_off(self):
        sub, rej = self.evaluate(["2026-01-10", "2026-02-10"])
        self.assertIsNone(sub)
        self.assertIsNone(rej)

    def test_one_missed_month_still_recognized(self):
        sub, rej = self.evaluate(["2026-01-10", "2026-02-10", "2026-03-10",
                                  "2026-05-10", "2026-06-10", "2026-07-10"])
        self.assertIsNone(rej)
        self.assertEqual(sub.cycle, "monthly")

    def test_two_missed_months_rejected_as_outlier(self):
        sub, rej = self.evaluate(["2026-01-10", "2026-02-10", "2026-03-10",
                                  "2026-06-10", "2026-07-10", "2026-08-10"])
        self.assertIsNone(sub)
        self.assertIn("outlier", rej.reason)

    def test_regular_gaps_but_scattered_amounts_rejected(self):
        days = ["2026-01-05", "2026-02-05", "2026-03-05",
                "2026-04-05", "2026-05-05", "2026-06-05"]
        sub, rej = self.evaluate(days, [40, 380, 90, 220, 30, 500])
        self.assertIsNone(sub)
        self.assertIn("amounts too scattered", rej.reason)

    def test_cycle_buckets(self):
        for days, want in (
            (["2026-01-01", "2026-01-08", "2026-01-15"], "weekly"),
            (["2026-01-08", "2026-04-08", "2026-07-08"], "quarterly"),
            (["2024-03-15", "2025-03-15", "2026-03-15"], "annual"),
            (["2025-09-20", "2026-03-20", "2026-09-20"], "182d"),
        ):
            rows = debits(days, 10.0)
            sub, rej = ds.evaluate_group("m", "M", rows, 3, 0.35, 0.2, 0.6)
            self.assertIsNotNone(sub, days)
            self.assertEqual(sub.cycle, want)


# ---------------------------------------------------------------------------
# Projection


class ProjectionTests(unittest.TestCase):
    def sub(self, days, amount):
        return ds.Sub(key="m", label="M", debits=debits(days, amount))

    def test_add_months_clamps_to_month_end(self):
        self.assertEqual(ds.add_months(date(2026, 1, 31), 1),
                         date(2026, 2, 28))
        self.assertEqual(ds.add_months(date(2024, 1, 31), 13),
                         date(2025, 2, 28))
        self.assertEqual(ds.add_months(date(2024, 2, 29), 12),
                         date(2025, 2, 28))

    def test_monthly_prediction_stays_on_the_day(self):
        sub = self.sub(["2026-01-10", "2026-02-10", "2026-03-10",
                        "2026-04-10"], 30)
        out = sub.predict(date(2027, 4, 10))
        self.assertEqual([d for d, _ in out][0], "2026-05-10")
        self.assertEqual([d for d, _ in out][-1], "2027-04-10")
        self.assertEqual(len(out), 12)

    def test_custom_cycle_steps_by_median_gap_days(self):
        sub = self.sub(["2025-09-20", "2026-03-20"], 2200)
        out = sub.predict(date(2027, 3, 20))
        self.assertEqual([d for d, _ in out],
                         ["2026-09-17", "2027-03-17"])

    def test_annual_prediction_feb29_rolls_to_feb28(self):
        sub = self.sub(["2024-02-29", "2025-02-28"], 398)
        out = sub.predict(date(2027, 2, 27))
        self.assertEqual([d for d, _ in out], ["2026-02-28"])

    def test_horizon_cuts_at_statement_date_plus_365(self):
        sub = self.sub(["2026-01-10", "2026-02-10", "2026-03-10",
                        "2026-04-10"], 30)
        self.assertEqual(len(sub.predict(date(2026, 12, 31))), 8)

    def test_gaps_ignore_same_day_repeats(self):
        sub = self.sub(["2026-01-10", "2026-01-10", "2026-02-10",
                        "2026-03-10"], 30)
        self.assertEqual(sub.gaps, [31, 28])


# ---------------------------------------------------------------------------
# Price moves


class MoveTests(unittest.TestCase):
    def test_hike_detected_against_previous_median(self):
        flags = ds.price_moves([30, 30, 30, 30, 36, 36])
        self.assertAlmostEqual(flags["hike"][0], 0.2)

    def test_drop_detected(self):
        flags = ds.price_moves([36, 36, 36, 30])
        self.assertAlmostEqual(flags["drop"][0], 1 / 6)

    def test_promo_first_month_detected(self):
        flags = ds.price_moves([4, 36, 36, 36])
        self.assertEqual(flags["promo"], (4.0, 36.0))

    def test_steady_price_has_no_flags(self):
        self.assertEqual(ds.price_moves([30, 30, 30]), {})


# ---------------------------------------------------------------------------
# Usage & cost per use


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_usage_zh_and_en_headers(self):
        p = write_file(os.path.join(self.tmp.name, "u1.csv"),
                       "商户,年使用次数\n超级猩猩,2\n")
        rows = ds.read_usage(p)
        self.assertEqual((rows[0].raw, rows[0].uses), ("超级猩猩", 2.0))
        p = write_file(os.path.join(self.tmp.name, "u2.csv"),
                       "merchant,uses_per_year\nNETFLIX,45\n")
        self.assertEqual(ds.read_usage(p)[0].uses, 45.0)

    def test_usage_headerless_two_columns(self):
        p = write_file(os.path.join(self.tmp.name, "u3.csv"),
                       "gym,2\nmusic,300\n")
        rows = ds.read_usage(p)
        self.assertEqual([r.raw for r in rows], ["gym", "music"])

    def test_match_usage_exact_then_unique_substring(self):
        keys = ["prsk spotify stockholm se", "超级猩猩月卡"]
        self.assertEqual(ds.match_usage("超级猩猩", keys), "超级猩猩月卡")
        self.assertEqual(ds.match_usage("spotify", keys),
                         "prsk spotify stockholm se")
        self.assertIsNone(ds.match_usage("月卡", ["超级猩猩月卡", "乐刻月卡"]))
        self.assertIsNone(ds.match_usage("nothing", keys))

    def test_verdict_tiers(self):
        self.assertEqual(ds.verdict_of(None, 15), "unknown")
        self.assertEqual(ds.verdict_of(15, 15), "keep")
        self.assertEqual(ds.verdict_of(45.0, 15), "watch")
        self.assertEqual(ds.verdict_of(45.01, 15), "cut")

    def test_apply_usage_join_zero_uses_and_unmatched(self):
        stmt = ds.read_statement(DEMO_BANK)
        analysis = ds.analyze(stmt, ignore=["房租"])
        usage = ds.read_usage(DEMO_USAGE) + [ds.UsageRow("不存在的东西", 7)]
        result = ds.apply_usage(analysis, usage, ds.DEFAULT_MPU)
        self.assertEqual(result["usage"]["unmatched"],
                         [{"name": "不存在的东西", "uses": 7.0}])
        self.assertEqual(result["usage"]["missing"], [])
        by_key = {v["merchant"]: v for v in result["usage"]["verdicts"]}
        self.assertIsNone(by_key["平安车险 自动续保"]["cost_per_use"])
        self.assertEqual(by_key["平安车险 自动续保"]["verdict"], "cut")


# ---------------------------------------------------------------------------
# End-to-end on the committed demo data


class ScenarioTests(unittest.TestCase):
    """Ground truth hand-verified when the fixture was designed."""

    @classmethod
    def setUpClass(cls):
        cls.stmt = ds.read_statement(DEMO_BANK)
        cls.full = ds.analyze(cls.stmt)
        cls.report = ds.apply_usage(
            ds.analyze(cls.stmt, ignore=["房租"]),
            ds.read_usage(DEMO_USAGE), ds.DEFAULT_MPU)

    def key(self, fragment):
        return next(s for s in self.report["subscriptions"]
                    if fragment in s["merchant"])

    def test_statement_counts(self):
        st = self.full["statement"]
        self.assertEqual((st["rows"], st["debits"], st["merchants"]),
                         (293, 256, 12))
        self.assertEqual(st["window"]["last"], "2026-08-25")

    def test_nine_subscriptions_without_ignore(self):
        self.assertEqual(len(self.full["subscriptions"]), 9)

    def test_rent_is_the_biggest_subscription_and_ignorable(self):
        rent = self.full["subscriptions"][0]
        self.assertEqual(rent["merchant"], "房租")
        self.assertEqual(rent["annualized"], 61225.81)
        self.assertEqual(self.full["annualized_total"], 71635.37)
        self.assertEqual(self.report["statement"]["notes"],
                         ["1 duplicate row(s) dropped"])
        self.assertIn("房租", self.report["ignored"])
        self.assertEqual(len(self.report["subscriptions"]), 8)
        self.assertEqual(self.report["annualized_total"], 10409.56)

    def test_netflix_hike_and_promo_notion(self):
        nf = self.key("netflix")
        self.assertEqual(nf["hits"], 36)
        self.assertEqual(nf["label"], "NETFLIX.COM 8665797172")
        self.assertEqual(nf["flags"]["hike"]["pct"], 0.129)
        self.assertEqual((nf["flags"]["hike"]["was"],
                          nf["flags"]["hike"]["last"]), (62.0, 70.0))
        notion = self.key("notion")
        self.assertEqual(notion["flags"]["promo"],
                         {"first": 4.0, "real": 36.0})

    def test_insurance_custom_cycle_and_gym_monthly(self):
        ins = self.key("车险")
        self.assertEqual(ins["cycle"], "182d")
        self.assertEqual(ins["hits"], 6)
        gym = self.key("猩猩")
        self.assertEqual((gym["cycle"], gym["annualized"]),
                         ("monthly", 3520.48))

    def test_next_year_locked_and_calendar(self):
        self.assertEqual(self.full["next_year_locked"], 72898)
        self.assertEqual(self.report["next_year_locked"], 10498)
        cal = {r["month"]: r for r in self.report["calendar"]}
        self.assertEqual(len(self.report["calendar"]), 12)
        self.assertEqual((cal["2026-09"]["total"],
                          cal["2026-09"]["charges"]), (2649, 6))
        self.assertEqual((cal["2027-03"]["total"],
                          cal["2027-03"]["charges"]), (3047, 7))

    def test_lookalikes_rejected_with_readable_reasons(self):
        reasons = {r["merchant"]: r["reason"] for r in self.full["rejected"]}
        self.assertEqual(len(self.full["rejected"]), 2)
        self.assertIn("outlier", reasons["滴滴出行"])
        self.assertIn("amounts too scattered", reasons["盒马鲜生"])

    def test_cost_per_use_verdicts_and_cut_refund(self):
        by_key = {v["merchant"]: v for v in self.report["usage"]["verdicts"]}
        self.assertEqual(by_key["超级猩猩月卡"]["verdict"], "cut")
        self.assertEqual(by_key["超级猩猩月卡"]["cost_per_use"], 1760.24)
        self.assertEqual(by_key["netflix com"]["verdict"], "watch")
        self.assertEqual(by_key["netflix com"]["cost_per_use"], 18.32)
        self.assertEqual(by_key["p9rsk spotify stockholm se"]["verdict"],
                         "keep")
        self.assertEqual(by_key["notion labs inc"]["verdict"], "cut")
        self.assertEqual(by_key["office home msft"]["cost_per_use"], 19.9)
        self.assertEqual(self.report["usage"]["cut_refund"], 8356.44)


# ---------------------------------------------------------------------------
# CLI


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bank = write_file(
            os.path.join(self.tmp.name, "bank.csv"),
            "date,description,amount\n"
            "2026-01-10,GYM,299\n2026-02-10,GYM,299\n"
            "2026-03-10,GYM,299\n2026-04-10,GYM,299\n")

    def test_scan_text_and_json(self):
        r = run_cli("scan", self.bank)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Dusty Subs scan", r.stdout)
        self.assertIn("GYM", r.stdout)
        r = run_cli("scan", self.bank, "--format", "json")
        data = json.loads(r.stdout)
        self.assertEqual(data["subscriptions"][0]["merchant"], "gym")
        self.assertEqual(data["subscriptions"][0]["annualized"], 3520.48)

    def test_report_and_explain(self):
        r = run_cli("report", self.bank)
        self.assertEqual(r.returncode, 0)
        self.assertIn("next-12-months calendar", r.stdout)
        r = run_cli("explain", "GYM", self.bank)
        self.assertEqual(r.returncode, 0)
        self.assertIn("predicted", r.stdout)
        r = run_cli("explain", "GYM", self.bank, "--format", "json")
        self.assertEqual(json.loads(r.stdout)["merchant"], "gym")

    def test_ignore_removes_merchant(self):
        r = run_cli("scan", self.bank, "--ignore", "gym")
        self.assertEqual(r.returncode, 0)
        self.assertIn("ignored by --ignore: gym", r.stdout)
        self.assertIn("no periodic debits found", r.stdout)
        self.assertNotIn("GYM", r.stdout)

    def test_fail_over_gate(self):
        r = run_cli("report", self.bank, "--fail-over", "100")
        self.assertEqual(r.returncode, 4)
        self.assertIn("over", r.stderr)
        r = run_cli("report", self.bank, "--fail-over", "100000")
        self.assertEqual(r.returncode, 0)

    def test_error_exit_codes(self):
        self.assertEqual(run_cli().returncode, 2)
        self.assertEqual(
            run_cli("scan", os.path.join(self.tmp.name, "nope.csv")
                    ).returncode, 3)
        bad = write_file(os.path.join(self.tmp.name, "bad.csv"),
                         "foo,bar\n1,2\n")
        self.assertEqual(run_cli("scan", bad).returncode, 3)
        self.assertEqual(run_cli("explain", "NOPE", self.bank).returncode, 3)


# ---------------------------------------------------------------------------
# Dogfood: the committed files through the real CLI


class DogfoodTests(unittest.TestCase):
    def test_scan_json_finds_nine(self):
        r = run_cli("scan", DEMO_BANK, "--format", "json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(json.loads(r.stdout)["subscriptions"]), 9)

    def test_report_through_cli_matches_ground_truth(self):
        r = run_cli("report", DEMO_BANK, "--usage", DEMO_USAGE,
                    "--ignore", "房租", "--format", "json")
        data = json.loads(r.stdout)
        self.assertEqual(data["next_year_locked"], 10498)
        self.assertEqual(data["usage"]["cut_refund"], 8356.44)

    def test_explain_gym_prices_a_use(self):
        r = run_cli("explain", "超级猩猩", DEMO_BANK, "--usage", DEMO_USAGE)
        self.assertEqual(r.returncode, 0)
        self.assertIn("1,760.24 per use (cut)", r.stdout)
        self.assertIn("no wall clock involved", r.stdout)


# ---------------------------------------------------------------------------
# Examples reproducibility


class ExamplesSyncTests(unittest.TestCase):
    def test_committed_examples_rebuild_byte_for_byte(self):
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "examples",
                                          "build_examples.py"), "--check"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("examples in sync", r.stdout)


if __name__ == "__main__":
    unittest.main()
