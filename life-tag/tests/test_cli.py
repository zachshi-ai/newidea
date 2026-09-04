#!/usr/bin/env python3
"""Acceptance tests for life-tag (生命价签) — CLI behaviour."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import life_tag as lt  # noqa: E402

EXAMPLE = str(ROOT / "examples" / "metro_worker.json")


class CliCase(unittest.TestCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lt.main(argv)
        return code, out.getvalue(), err.getvalue()


class TestHappyPaths(CliCase):
    def test_hourly_exit_zero_and_key_numbers(self):
        code, out, _ = self.run_cli(["hourly", "--path", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("名义时薪", out)
        self.assertIn("91.07", out)
        self.assertIn("真实", out)
        self.assertIn("55.66", out)
        self.assertIn("恢复税", out)
        self.assertIn("通勤税", out)
        self.assertIn("开销税", out)

    def test_tag_small_price(self):
        code, out, _ = self.run_cli(["tag", "20", "--path", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("22 分钟", out)
        self.assertIn("心跳线以内", out)

    def test_tag_big_price(self):
        code, out, _ = self.run_cli(["tag", "6999", "--path", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("超过心跳线", out)
        self.assertIn("10.3", out)

    def test_tag_line_override(self):
        code, out, _ = self.run_cli(
            ["tag", "6999", "--line", "300", "--path", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("心跳线以内", out)

    def test_overtime(self):
        code, out, _ = self.run_cli(
            ["overtime", "4", "--mult", "1.5", "--path", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("136.61", out)
        self.assertIn("算术上划算", out)

    def test_leverage(self):
        code, out, _ = self.run_cli(
            ["leverage", "--commute-to", "15", "--raise", "10",
             "--path", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("杠杆排行", out)
        self.assertIn("最有效", out)

    def test_leverage_no_actions_still_exits_zero(self):
        code, out, _ = self.run_cli(["leverage", "--path", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("未给出任何候选动作", out)

    def test_profile_show_outputs_json(self):
        code, out, _ = self.run_cli(["profile", "show", "--path", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("gross_monthly", out)


class TestProfileSet(CliCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "p.json")

    def test_set_then_hourly(self):
        code, out, _ = self.run_cli(
            ["profile", "set", "--gross", "9000", "--tax", "0.1",
             "--path", self.path])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(self.path))
        code, out, _ = self.run_cli(["hourly", "--path", self.path])
        self.assertEqual(code, 0)
        self.assertIn("48.21", out)  # 9000×0.9 ÷ 168 时 = 48.21

    def test_set_merges_with_existing(self):
        self.run_cli(["profile", "set", "--gross", "9000", "--tax", "0.1",
                      "--commute", "30", "--path", self.path])
        self.run_cli(["profile", "set", "--gross", "12000",
                      "--path", self.path])
        code, out, _ = self.run_cli(["profile", "show", "--path", self.path])
        self.assertEqual(code, 0)
        self.assertIn("12000", out)
        self.assertIn("30.0", out)  # 未重设的 commute_min 沿用旧值

    def test_set_missing_tax_reports_error(self):
        code, _, err = self.run_cli(
            ["profile", "set", "--gross", "9000", "--path", self.path])
        self.assertEqual(code, 2)
        self.assertIn("tax_rate", err)
        self.assertFalse(os.path.exists(self.path))

    def test_set_prints_immediate_report(self):
        code, out, _ = self.run_cli(
            ["profile", "set", "--gross", "9000", "--tax", "0.1",
             "--path", self.path])
        self.assertIn("名义时薪", out)


class TestErrorHandling(CliCase):
    def test_missing_profile_file(self):
        code, _, err = self.run_cli(
            ["hourly", "--path", "/nonexistent/life_tag.json"])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)

    def test_negative_price(self):
        code, _, err = self.run_cli(["tag", "-5", "--path", EXAMPLE])
        self.assertEqual(code, 2)
        self.assertIn("正数", err)

    def test_zero_price(self):
        code, _, _ = self.run_cli(["tag", "0", "--path", EXAMPLE])
        self.assertEqual(code, 2)

    def test_zero_overtime_hours(self):
        code, _, _ = self.run_cli(["overtime", "0", "--path", EXAMPLE])
        self.assertEqual(code, 2)

    def test_zero_multiplier(self):
        code, _, _ = self.run_cli(
            ["overtime", "2", "--mult", "0", "--path", EXAMPLE])
        self.assertEqual(code, 2)

    def test_no_subcommand(self):
        code, _, _ = self.run_cli([])
        self.assertEqual(code, 2)

    def test_bare_profile(self):
        code, out, _ = self.run_cli(["profile"])
        self.assertEqual(code, 2)
        self.assertIn("set", out)  # 引导到 profile 的用法


if __name__ == "__main__":
    unittest.main()
