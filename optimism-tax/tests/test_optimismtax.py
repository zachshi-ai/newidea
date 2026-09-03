#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for optimism-tax — every acceptance criterion from README, as code.

Acceptance criteria under test:
  AC1  ratio is actual/estimate, per record
  AC2  the tax rate is the MEDIAN ratio (robust to one exploded project)
  AC3  the safe quote uses the P80 of ratios (linear interpolation)
  AC4  per-tag accounts split the ledger; thin buckets (< 3) get no rate
  AC5  quote refuses below 8 records; tag quotes fall back to the whole
       ledger when the tag has < 8 records, and say so
  AC6  trend compares the most recent 10 records against the prior;
       verdict unknown until 5+ prior records exist
  AC7  sandbagging flag when > 40% of records finished early
  AC8  bad ledger lines are skipped and counted, never fatal
  AC9  CLI: record appends, report audits, quote prices, exit codes
  AC10 zero dependencies: standard library only (import-level guarantee)
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import optimism_tax  # noqa: E402

from optimism_tax import (  # noqa: E402
    Audit,
    LedgerError,
    QuoteRefused,
    Record,
    audit_ledger,
    bracket_for,
    build_parser,
    build_quote,
    build_report,
    calibration_trend,
    load_ledger,
    median,
    parse_record,
    quantile,
    ratios_of,
    tag_accounts,
)


def rec(estimate: float, actual: float, tag: str = "untagged",
        date: str = "2026-01-01", line: int = 0, note: str = "") -> Record:
    return Record(estimate, actual, tag, note, date, line)


def to_row(row):
    """Accept either a dict or a Record when writing ledger fixtures."""
    if isinstance(row, Record):
        return {"estimate": row.estimate, "actual": row.actual,
                "tag": row.tag, "note": row.note, "date": row.date}
    return row


def write_ledger(rows: List[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(to_row(row), ensure_ascii=False) + "\n")
    return path


def run_cli(argv: List[str]):
    """Run the CLI, capture (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = optimism_tax.main(argv)
    return code, out.getvalue(), err.getvalue()


def audit_of(rows: List[dict]) -> Audit:
    path = write_ledger(rows)
    try:
        records, skipped = load_ledger(path)
        return audit_ledger(records, skipped)
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# AC1 — ratio

class TestRatio(unittest.TestCase):
    def test_ratio_is_actual_over_estimate(self):
        self.assertAlmostEqual(rec(3, 5).ratio, 5 / 3)

    def test_ratio_one_when_on_time(self):
        self.assertAlmostEqual(rec(4, 4).ratio, 1.0)

    def test_ratio_below_one_when_early(self):
        self.assertAlmostEqual(rec(4, 2).ratio, 0.5)

    def test_ratio_zero_actual_is_legal(self):
        self.assertAlmostEqual(rec(4, 0).ratio, 0.0)


# ---------------------------------------------------------------------------
# AC2 — median tax rate

class TestTaxRate(unittest.TestCase):
    def test_median_of_three(self):
        rows = [rec(1, 2), rec(1, 3), rec(1, 4)]
        self.assertAlmostEqual(audit_of(rows).tax_rate, 3.0)

    def test_median_robust_to_one_explosion(self):
        # Nine 1.5x projects and one 20x disaster: the rate must stay 1.5x.
        rows = [rec(1, 1.5) for _ in range(9)] + [rec(1, 20)]
        self.assertAlmostEqual(audit_of(rows).tax_rate, 1.5)

    def test_median_even_count_interpolates(self):
        self.assertAlmostEqual(median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_untagged_records_landed_in_untagged(self):
        rows = [rec(1, 2, tag="untagged"), rec(2, 2, tag="feature")]
        audit = audit_of(rows)
        self.assertEqual(audit.accounts[0].tag, "feature")


# ---------------------------------------------------------------------------
# AC3 — quantile / P80

class TestQuantile(unittest.TestCase):
    def test_single_value(self):
        self.assertAlmostEqual(quantile([7.0], 0.8), 7.0)

    def test_exact_hit(self):
        self.assertAlmostEqual(quantile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5), 3.0)

    def test_interpolates_between_neighbors(self):
        # pos = (5-1)*0.8 = 3.2 -> between 4.0 and 5.0, 20% up: 4.2
        self.assertAlmostEqual(quantile([1.0, 2.0, 3.0, 4.0, 5.0], 0.8), 4.2)

    def test_p80_of_ledger(self):
        ratios = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 5.0]
        audit_rows = [rec(1, r) for r in ratios]
        audit = audit_of(audit_rows)
        expected = quantile(sorted(ratios), 0.8)
        self.assertAlmostEqual(audit.p80_ratio, expected)

    def test_p80_above_median_when_skewed(self):
        audit = audit_of([rec(1, r) for r in [1.0, 1.1, 1.2, 1.3, 1.4,
                                             1.5, 1.6, 1.7, 1.8, 5.0]])
        self.assertGreater(audit.p80_ratio, audit.tax_rate)

    def test_quantile_empty_raises(self):
        with self.assertRaises(ValueError):
            quantile([], 0.8)


# ---------------------------------------------------------------------------
# AC4 — per-tag accounts

class TestTagAccounts(unittest.TestCase):
    def test_buckets_are_split_by_tag(self):
        rows = ([rec(1, 3, tag="research", date=f"2026-01-{d:02d}")
                 for d in range(1, 5)] +
                [rec(1, 1.2, tag="bugfix", date=f"2026-02-{d:02d}")
                 for d in range(1, 5)])
        accounts = {a.tag: a for a in tag_accounts(audit_of(rows).records)}
        self.assertAlmostEqual(accounts["research"].median_ratio, 3.0)
        self.assertAlmostEqual(accounts["bugfix"].median_ratio, 1.2)

    def test_thin_bucket_gets_no_rate(self):
        rows = ([rec(1, 3, tag="research") for _ in range(4)] +
                [rec(1, 9, tag="ops") for _ in range(2)])
        accounts = {a.tag: a for a in tag_accounts(audit_of(rows).records)}
        self.assertIsNotNone(accounts["research"].median_ratio)
        self.assertIsNone(accounts["ops"].median_ratio)
        self.assertTrue(accounts["ops"].thin)

    def test_buckets_sorted_by_size(self):
        rows = ([rec(1, 2, tag="a") for _ in range(5)] +
                [rec(1, 2, tag="b") for _ in range(2)] +
                [rec(1, 2, tag="c") for _ in range(4)])
        order = [a.tag for a in tag_accounts(audit_of(rows).records)]
        self.assertEqual(order, ["a", "c", "b"])


# ---------------------------------------------------------------------------
# AC5 — quote refusal and fallback

EIGHT_PLUS = [rec(1, 2.0, tag="feature") for _ in range(8)] + \
             [rec(1, 3.0, tag="research") for _ in range(4)]


class TestQuote(unittest.TestCase):
    def _audit(self, rows):
        return audit_of(rows)

    def test_quote_uses_median_and_p80(self):
        rows = [rec(1, 2.0) for _ in range(9)]  # median 2.0, p80 2.0
        text = build_quote(self._audit(rows), 3.0, None)
        self.assertIn("6.0 days", text)
        self.assertIn("P50", text)
        self.assertIn("P80", text)

    def test_quote_refused_below_threshold(self):
        audit = self._audit([rec(1, 2.0) for _ in range(7)])
        with self.assertRaises(QuoteRefused):
            build_quote(audit, 3.0, None)

    def test_quote_allowed_at_threshold(self):
        rows = [rec(1, 2.0) for _ in range(8)]
        text = build_quote(self._audit(rows), 3.0, None)
        self.assertIn("6.0 days", text)

    def test_quote_tag_fallback_declares_basis(self):
        rows = ([rec(1, 2.0, tag="feature") for _ in range(10)] +
                [rec(1, 9.0, tag="research") for _ in range(2)])
        text = build_quote(self._audit(rows), 3.0, "research")
        self.assertIn("whole ledger", text)
        self.assertIn("2 record(s) tagged 'research'", text)

    def test_quote_tag_calibrates_when_deep_enough(self):
        rows = ([rec(1, 1.0, tag="feature") for _ in range(2)] +
                [rec(1, 4.0, tag="research") for _ in range(9)])
        text = build_quote(self._audit(rows), 2.0, "research")
        self.assertIn("8.0 days", text)          # 2.0 x 4.0 median
        self.assertIn("9 records tagged 'research'", text)

    def test_quote_unknown_tag_is_refused(self):
        # An unknown tag is probably a typo: silently falling back to the
        # whole ledger would dress a wrong tag in the tool's authority.
        rows = [rec(1, 2.0, tag="feature") for _ in range(9)]
        with self.assertRaises(QuoteRefused):
            build_quote(self._audit(rows), 3.0, "design")

    def test_quote_tag_refused_when_untagged_is_thin(self):
        # Tag fallback still requires a quotable whole ledger.
        rows = [rec(1, 2.0, tag="feature") for _ in range(5)]
        with self.assertRaises(QuoteRefused):
            build_quote(self._audit(rows), 3.0, "design")


# ---------------------------------------------------------------------------
# AC6 — trend

class TestTrend(unittest.TestCase):
    def test_unknown_without_enough_prior(self):
        rows = [rec(1, 2.0, date=f"2026-01-{d + 1:02d}") for d in range(12)]
        self.assertEqual(calibration_trend(audit_of(rows).records).verdict,
                         "unknown")

    def test_worsening_detected(self):
        # Prior records 1.0x, recent 10 records 3.0x.
        rows = ([rec(1, 1.0, date=f"2025-12-{d + 1:02d}") for d in range(8)] +
                [rec(1, 3.0, date=f"2026-01-{d + 1:02d}") for d in range(10)])
        trend = calibration_trend(audit_of(rows).records)
        self.assertEqual(trend.verdict, "worsening")
        self.assertAlmostEqual(trend.prior_median, 1.0)
        self.assertAlmostEqual(trend.recent_median, 3.0)

    def test_improving_detected(self):
        rows = ([rec(1, 3.0, date=f"2025-12-{d + 1:02d}") for d in range(8)] +
                [rec(1, 1.0, date=f"2026-01-{d + 1:02d}") for d in range(10)])
        self.assertEqual(calibration_trend(audit_of(rows).records).verdict,
                         "improving")

    def test_flat_detected(self):
        rows = [rec(1, 1.5, date=f"2026-01-{d + 1:02d}") for d in range(15)]
        self.assertEqual(calibration_trend(audit_of(rows).records).verdict,
                         "flat")

    def test_trend_window_is_recent_ten(self):
        rows = ([rec(1, 1.0, date=f"2025-12-{d + 1:02d}") for d in range(10)] +
                [rec(1, 2.0, date=f"2026-01-{d + 1:02d}") for d in range(10)])
        trend = calibration_trend(audit_of(rows).records)
        self.assertAlmostEqual(trend.recent_median, 2.0)


# ---------------------------------------------------------------------------
# AC7 — sandbagging and red flags

class TestRedFlags(unittest.TestCase):
    def test_sandbagging_flag_fires(self):
        # 8 records: 6 finished early (r < 1), 2 slightly late.
        rows = [rec(4, 3, date=f"2026-01-{d + 1:02d}") for d in range(6)] + \
               [rec(4, 5, date=f"2026-02-{d + 1:02d}") for d in range(2)]
        audit = audit_of(rows)
        self.assertTrue(any("SANDBAGGING" in f for f in audit.flags))

    def test_no_sandbagging_when_mostly_late(self):
        rows = [rec(1, 2.0, date=f"2026-01-{d + 1:02d}") for d in range(9)]
        audit = audit_of(rows)
        self.assertFalse(any("SANDBAGGING" in f for f in audit.flags))

    def test_too_few_records_flag(self):
        audit = audit_of([rec(1, 2.0) for _ in range(5)])
        self.assertTrue(any("TOO FEW RECORDS" in f for f in audit.flags))
        self.assertFalse(audit.quotable)

    def test_fragmented_calibration_flag(self):
        # Median pinned at 1.0x by seven on-target records, but 30% of the
        # ledger sits at 6x: p80/median = 6.0 > 2.5 -> fragmented.
        rows = ([rec(1, 1.0, date=f"2026-01-{d + 1:02d}") for d in range(7)] +
                [rec(1, 6.0, date=f"2026-02-{d + 1:02d}") for d in range(3)])
        audit = audit_of(rows)
        self.assertTrue(any("FRAGMENTED" in f for f in audit.flags))

    def test_worsening_flag(self):
        rows = ([rec(1, 1.0, date=f"2025-12-{d + 1:02d}") for d in range(8)] +
                [rec(1, 3.0, date=f"2026-01-{d + 1:02d}") for d in range(10)])
        audit = audit_of(rows)
        self.assertTrue(any("WORSENING" in f for f in audit.flags))

    def test_clean_ledger_has_no_flags(self):
        rows = [rec(1, 1.2, date=f"2026-01-{d + 1:02d}") for d in range(12)]
        audit = audit_of(rows)
        self.assertEqual(audit.flags, [])


# ---------------------------------------------------------------------------
# Tax brackets

class TestBrackets(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(bracket_for(1.1)[0], "calibrated")
        self.assertEqual(bracket_for(1.1001)[0], "mild")
        self.assertEqual(bracket_for(1.5)[0], "mild")
        self.assertEqual(bracket_for(1.9)[0], "standard")
        self.assertEqual(bracket_for(2.0)[0], "standard")
        self.assertEqual(bracket_for(2.1)[0], "heavy")

    def test_tax_paid_sums_overrun_days(self):
        rows = [rec(3, 5, date="2026-01-01"), rec(2, 2, date="2026-01-02"),
                rec(1, 3, date="2026-01-03")]
        audit = audit_of(rows)
        self.assertAlmostEqual(audit.tax_paid, (5 - 3) + (2 - 2) + (3 - 1))


# ---------------------------------------------------------------------------
# AC8 — ledger parsing

class TestLedgerParsing(unittest.TestCase):
    def test_parse_full_record(self):
        r = parse_record({"estimate": 3, "actual": 5, "tag": "research",
                          "note": "oauth", "date": "2026-03-01"}, 1)
        self.assertEqual(r.tag, "research")
        self.assertEqual(r.note, "oauth")
        self.assertEqual(r.date, "2026-03-01")

    def test_parse_defaults(self):
        r = parse_record({"estimate": 3, "actual": 5}, 1)
        self.assertEqual(r.tag, "untagged")
        self.assertEqual(r.note, "")
        self.assertEqual(r.date, __import__("datetime").date.today().isoformat())

    def test_parse_rejects_zero_estimate(self):
        with self.assertRaises(LedgerError):
            parse_record({"estimate": 0, "actual": 5}, 1)

    def test_parse_rejects_negative_estimate(self):
        with self.assertRaises(LedgerError):
            parse_record({"estimate": -1, "actual": 5}, 1)

    def test_parse_rejects_negative_actual(self):
        with self.assertRaises(LedgerError):
            parse_record({"estimate": 3, "actual": -5}, 1)

    def test_parse_rejects_missing_fields(self):
        with self.assertRaises(LedgerError):
            parse_record({"estimate": 3}, 1)
        with self.assertRaises(LedgerError):
            parse_record({"actual": 3}, 1)

    def test_parse_rejects_non_numeric(self):
        with self.assertRaises(LedgerError):
            parse_record({"estimate": "3", "actual": 5}, 1)

    def test_parse_rejects_bool(self):
        # bool is an int subclass in Python — must still be rejected.
        with self.assertRaises(LedgerError):
            parse_record({"estimate": True, "actual": 5}, 1)

    def test_parse_rejects_non_dict(self):
        with self.assertRaises(LedgerError):
            parse_record([3, 5], 1)

    def test_load_skips_bad_lines_and_counts(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"estimate": 1, "actual": 2}) + "\n")
            fh.write("this is not json\n")
            fh.write(json.dumps({"estimate": 0, "actual": 2}) + "\n")
            fh.write("\n")  # blank line: ignored, not an error
            fh.write(json.dumps({"estimate": 1, "actual": 2}) + "\n")
        try:
            records, skipped = load_ledger(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(records), 2)
        self.assertEqual(skipped, 2)

    def test_load_missing_file_raises(self):
        with self.assertRaises(LedgerError):
            load_ledger("/nonexistent/ledger.jsonl")

    def test_empty_ledger_audits_as_error(self):
        path = write_ledger([])
        try:
            records, skipped = load_ledger(path)
            with self.assertRaises(LedgerError):
                audit_ledger(records, skipped)
        finally:
            os.unlink(path)

    def test_records_sorted_by_date_then_line(self):
        # Same-date records keep their ledger (file) order: the trend and
        # the "recent" window must be stable within a day.
        path = write_ledger([
            {"date": "2026-02-01", "estimate": 1, "actual": 2},
            {"date": "2026-01-01", "estimate": 1, "actual": 3},
            {"date": "2026-02-01", "estimate": 1, "actual": 4},
        ])
        try:
            records, _ = load_ledger(path)
        finally:
            os.unlink(path)
        ordered = sorted(records, key=lambda r: (r.date, r.line))
        self.assertEqual([r.ratio for r in ordered], [3.0, 2.0, 4.0])


# ---------------------------------------------------------------------------
# AC9 — CLI integration

class TestCLI(unittest.TestCase):
    def setUp(self):
        fd, self.ledger = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.unlink(self.ledger)  # record should create it

    def tearDown(self):
        if os.path.exists(self.ledger):
            os.unlink(self.ledger)

    def test_record_appends_and_counts(self):
        code, out, _ = run_cli(["record", "--estimate", "3", "--actual", "5",
                                "--tag", "research", "--note", "oauth",
                                "--file", self.ledger])
        self.assertEqual(code, 0)
        self.assertIn("r = 1.67x", out)
        self.assertIn("1 record(s)", out)
        with open(self.ledger, encoding="utf-8") as fh:
            row = json.loads(fh.readline())
        self.assertEqual(row["tag"], "research")
        self.assertEqual(row["estimate"], 3.0)

    def test_record_hints_until_quotable(self):
        run_cli(["record", "--estimate", "1", "--actual", "1",
                 "--file", self.ledger])
        code, out, _ = run_cli(["record", "--estimate", "1", "--actual", "1",
                                "--file", self.ledger])
        self.assertIn("quotes unlock at 8", out)

    def test_record_rejects_bad_estimate(self):
        code, _, err = run_cli(["record", "--estimate", "0", "--actual", "5",
                                "--file", self.ledger])
        self.assertEqual(code, 2)
        self.assertIn("estimate", err)

    def test_report_on_empty_ledger_is_error(self):
        code, _, err = run_cli(["report", "--file", self.ledger])
        self.assertEqual(code, 2)  # file was created empty -> no valid records

    def test_report_missing_ledger_is_error(self):
        code, _, err = run_cli(["report", "--file", "/nonexistent/x.jsonl"])
        self.assertEqual(code, 2)
        self.assertIn("ledger not found", err)

    def test_report_full_flow(self):
        for i in range(12):
            run_cli(["record", "--estimate", "2", "--actual", "3",
                     "--tag", "feature", "--file", self.ledger])
        code, out, _ = run_cli(["report", "--file", self.ledger])
        self.assertEqual(code, 0)
        self.assertIn("optimism tax rate", out)
        self.assertIn("1.50x", out)
        self.assertIn("feature", out)
        self.assertIn("12.0 days", out)  # total tax paid: 12 x (3-2)

    def test_report_json_is_parseable(self):
        for i in range(10):
            run_cli(["record", "--estimate", "2", "--actual", "3",
                     "--file", self.ledger])
        code, out, _ = run_cli(["report", "--format", "json",
                                "--file", self.ledger])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertAlmostEqual(data["tax_rate"], 1.5)
        self.assertEqual(data["records"], 10)
        self.assertTrue(data["quotable"])

    def test_report_fail_under_gate(self):
        # 9 records at 3.0x each -> tax rate 3.0x.
        for i in range(9):
            run_cli(["record", "--estimate", "1", "--actual", "3",
                     "--file", self.ledger])
        code, _, _ = run_cli(["report", "--fail-under", "4", "--file", self.ledger])
        self.assertEqual(code, 0)
        code, _, err = run_cli(["report", "--fail-under", "2", "--file", self.ledger])
        self.assertEqual(code, 4)
        self.assertIn("gate", err)

    def test_quote_refused_exit_code(self):
        run_cli(["record", "--estimate", "1", "--actual", "2",
                 "--file", self.ledger])
        code, _, err = run_cli(["quote", "3", "--file", self.ledger])
        self.assertEqual(code, 3)
        self.assertIn("QUOTE REFUSED", err)

    def test_quote_after_enough_records(self):
        for i in range(9):
            run_cli(["record", "--estimate", "1", "--actual", "2",
                     "--file", self.ledger])
        code, out, _ = run_cli(["quote", "3", "--file", self.ledger])
        self.assertEqual(code, 0)
        self.assertIn("6.0 days", out)

    def test_quote_skips_bad_lines_with_warning(self):
        for i in range(9):
            run_cli(["record", "--estimate", "1", "--actual", "2",
                     "--file", self.ledger])
        with open(self.ledger, "a", encoding="utf-8") as fh:
            fh.write("garbage\n")
        code, out, err = run_cli(["quote", "3", "--file", self.ledger])
        self.assertEqual(code, 0)
        self.assertIn("unreadable line(s) skipped", err)


# ---------------------------------------------------------------------------
# AC10 — zero dependencies

class TestZeroDependencies(unittest.TestCase):
    def test_module_imports_nothing_outside_stdlib(self):
        import ast
        import inspect
        import optimism_tax as mod
        tree = ast.parse(inspect.getsource(mod))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    imported.add(node.module.split(".")[0])
        imported.discard("__future__")
        allowed = {"argparse", "json", "math", "sys", "os", "dataclasses",
                   "datetime", "typing", "statistics"}
        self.assertEqual(imported - allowed, set(),
                         f"unexpected imports: {imported - allowed}")

    def test_version_present(self):
        self.assertEqual(optimism_tax.__version__, "1.0.0")

    def test_parser_has_three_commands(self):
        parser = build_parser()
        for cmd in ("record", "report", "quote"):
            try:
                parser.parse_args([cmd, "--help"])
            except SystemExit:
                pass  # --help exits 0


# ---------------------------------------------------------------------------
# dogfood + example sync

EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples")
SAMPLE_FILES = ("records.jsonl", "sample-report.txt", "sample-quote.txt",
                "sample-quote-research.txt")


class ExamplesSyncTests(unittest.TestCase):
    def test_examples_rebuild_byte_identical(self):
        before = {}
        for name in SAMPLE_FILES:
            with open(os.path.join(EXAMPLES, name), encoding="utf-8") as fh:
                before[name] = fh.read()
        script = os.path.join(EXAMPLES, "build_examples.py")
        result = subprocess.run([sys.executable, script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, old in before.items():
            with open(os.path.join(EXAMPLES, name), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), old,
                                 f"{name} drifted from committed sample")


class DogfoodTests(unittest.TestCase):
    """The example ledger is the tool's own audit surface: pinned data,
    deterministic output, and every exit path exercised end to end."""

    LEDGER = os.path.join(EXAMPLES, "records.jsonl")

    def test_dogfood_audit_matches_pinned_story(self):
        records, skipped = load_ledger(self.LEDGER)
        self.assertEqual(len(records), 25)
        self.assertEqual(skipped, 1)  # the half-written receipt
        audit = audit_ledger(records, skipped)
        self.assertAlmostEqual(audit.tax_rate, 1.25, places=2)
        self.assertAlmostEqual(audit.p80_ratio, 3.42, places=2)
        self.assertEqual(audit.bracket, "mild")
        self.assertAlmostEqual(audit.tax_paid, 56.0, places=1)
        self.assertTrue(audit.quotable)
        research = next(a for a in audit.accounts if a.tag == "research")
        self.assertAlmostEqual(research.median_ratio, 3.55, places=2)
        self.assertTrue(any("FRAGMENTED" in f for f in audit.flags))

    def test_dogfood_quote_research_end_to_end(self):
        code, out, err = run_cli(
            ["quote", "3", "--tag", "research", "--file", self.LEDGER])
        self.assertEqual(code, 0, err)
        self.assertIn("10.6 days", out)
        self.assertIn("8 records tagged 'research'", out)

    def test_dogfood_unknown_tag_exit_3(self):
        code, _, err = run_cli(
            ["quote", "3", "--tag", "resarch", "--file", self.LEDGER])
        self.assertEqual(code, 3)  # typo is refused, not silently calibrated
        self.assertIn("QUOTE REFUSED", err)

    def test_dogfood_report_is_deterministic(self):
        first = run_cli(["report", "--file", self.LEDGER])
        second = run_cli(["report", "--file", self.LEDGER])
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
