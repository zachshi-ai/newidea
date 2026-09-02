#!/usr/bin/env python3
"""Acceptance tests for rebrew (复现那杯) — parsing.

All acceptance criteria from README.md are pinned here as unittest cases.

Run:  python3 -m unittest discover -s rebrew/tests -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rebrew as rb  # noqa: E402


HEADER = "\t".join(rb.REQUIRED_COLUMNS)


def row(date="2026-08-01", bean="Ethiopia", dose="15", water="225",
        temp="93", grind="6", time="145", rating="7.0", notes=""):
    return "\t".join([date, bean, dose, water, temp, grind, time, rating, notes])


class TestHeaderAndRows(unittest.TestCase):
    def test_standard_log(self):
        pours = rb.parse_pours(HEADER + "\n" + row() + "\n" + row(date="2026-08-02", rating="7.5"))
        self.assertEqual(len(pours), 2)
        self.assertEqual(pours[0].bean, "Ethiopia")
        self.assertEqual(pours[0].rating, 7.0)
        self.assertEqual(pours[1].rating, 7.5)

    def test_leading_comment_and_blank_lines_before_header(self):
        text = "# 我的冲煮日志\n\n" + HEADER + "\n" + row() + "\n"
        pours = rb.parse_pours(text)
        self.assertEqual(len(pours), 1)

    def test_inline_comment_and_blank_rows_skipped(self):
        text = HEADER + "\n# 中间注释\n\n" + row() + "\n"
        self.assertEqual(len(rb.parse_pours(text)), 1)

    def test_column_order_is_free(self):
        shuffled = "\t".join(["rating", "date", "bean", "temp_c",
                              "grind", "time_s", "dose_g", "water_g", "notes"])
        line = "\t".join(["8.0", "2026-08-01", "Kenya", "92", "8",
                          "150", "16", "240", ""])
        pours = rb.parse_pours(shuffled + "\n" + line)
        self.assertEqual(pours[0].rating, 8.0)
        self.assertEqual(pours[0].temp_c, 92)
        self.assertEqual(pours[0].bean, "Kenya")

    def test_short_row_defaults_notes_to_empty(self):
        pours = rb.parse_pours(HEADER + "\n" + row(notes="") + "\n")
        self.assertEqual(pours[0].notes, "")

    def test_ratio_derived(self):
        pours = rb.parse_pours(HEADER + "\n" + row(dose="15", water="240"))
        self.assertAlmostEqual(pours[0].ratio, 16.0)
        pours = rb.parse_pours(HEADER + "\n" + row(dose="18", water="250"))
        self.assertAlmostEqual(pours[0].ratio, 250 / 18)


class TestBadRows(unittest.TestCase):
    def assert_problem(self, text, needle):
        with self.assertRaises(rb.ParseError) as ctx:
            rb.parse_pours(text)
        self.assertIn(needle, str(ctx.exception))

    def test_non_numeric_field_reports_lineno(self):
        self.assert_problem(HEADER + "\n" + row() + "\n" + row(temp="hot"),
                            "第 3 行")

    def test_rating_out_of_range(self):
        self.assert_problem(HEADER + "\n" + row(rating="11"),
                            "rating=11 超出 0~10")

    def test_zero_rating_is_valid(self):
        pours = rb.parse_pours(HEADER + "\n" + row(rating="0"))
        self.assertEqual(pours[0].rating, 0.0)

    def test_nonpositive_dose_rejected(self):
        self.assert_problem(HEADER + "\n" + row(dose="0"),
                            "必须为正")

    def test_empty_date_rejected(self):
        self.assert_problem(HEADER + "\n" + row(date=""),
                            "date/bean 不能为空")

    def test_all_bad_rows_reported_at_once(self):
        text = (HEADER + "\n" + row(rating="12") + "\n" + row(temp="x")
                + "\n" + row(grind="") + "\n")
        with self.assertRaises(rb.ParseError) as ctx:
            rb.parse_pours(text)
        msg = str(ctx.exception)
        self.assertIn("第 2 行", msg)
        self.assertIn("第 3 行", msg)
        self.assertIn("第 4 行", msg)

    def test_empty_file(self):
        self.assert_problem("", "日志为空")

    def test_comment_only_file(self):
        self.assert_problem("# 只有注释\n", "日志为空")

    def test_header_only(self):
        self.assert_problem(HEADER + "\n", "没有有效冲煮记录")

    def test_missing_header_column(self):
        bad = "\t".join(c for c in rb.REQUIRED_COLUMNS if c != "rating")
        self.assert_problem(bad + "\n" + row(), "rating")


if __name__ == "__main__":
    unittest.main()
