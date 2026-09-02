#!/usr/bin/env python3
"""Acceptance tests for rebrew (复现那杯) — CLI end-to-end via subprocess."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = (sys.executable, str(ROOT / "rebrew.py"))
EXAMPLES = ROOT / "examples"

HEADER = "\t".join(["date", "bean", "dose_g", "water_g", "temp_c",
                    "grind", "time_s", "rating", "notes"])
GOOD = (HEADER + "\n"
        "2026-08-01\tEthiopia\t15\t225\t93\t6\t145\t7.0\t\n"
        "2026-08-02\tEthiopia\t15\t225\t93\t6\t150\t7.5\t\n"
        "2026-08-03\tEthiopia\t15\t225\t95\t6\t148\t7.5\t\n")
BAD = (HEADER + "\n"
       "2026-08-01\tEthiopia\t15\t225\thot\t6\t145\t7.0\t\n")


def run(args, cwd=None):
    return subprocess.run(CLI + tuple(args), capture_output=True,
                          text=True, cwd=cwd)


class TestAnalyze(unittest.TestCase):
    def test_exit_zero_and_section_titles(self):
        proc = run(["analyze", str(EXAMPLES / "realistic.tsv")])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for section in ["【总览】", "【复现半径】", "【旋钮排行】",
                        "【分组均值】", "【最小可检测效应】", "【下一步】"]:
            self.assertIn(section, proc.stdout)

    def test_bean_filter(self):
        proc = run(["analyze", str(EXAMPLES / "realistic.tsv"),
                    "--bean", "Colombia Huila"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Colombia Huila", proc.stdout)
        self.assertNotIn("Ethiopia", proc.stdout)

    def test_unknown_bean_fails_gracefully(self):
        proc = run(["analyze", str(EXAMPLES / "minimal.tsv"),
                    "--bean", "Nope"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("没有豆名为", proc.stderr)

    def test_broken_log_exits_two(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.tsv")
            with open(path, "w") as fh:
                fh.write(BAD)
            proc = run(["analyze", path])
            self.assertEqual(proc.returncode, 2)
            self.assertIn("解析失败", proc.stderr)

    def test_missing_file_exits_two(self):
        proc = run(["analyze", "/nonexistent/pours.tsv"])
        self.assertEqual(proc.returncode, 2)


class TestSuggest(unittest.TestCase):
    def test_exit_zero_and_stage_line(self):
        proc = run(["suggest", str(EXAMPLES / "realistic.tsv")])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("阶段：", proc.stdout)
        self.assertIn("单因素实验", proc.stdout)

    def test_minimal_log_also_works(self):
        proc = run(["suggest", str(EXAMPLES / "minimal.tsv")])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("计划：", proc.stdout)


class TestValidate(unittest.TestCase):
    def test_valid_log(self):
        proc = run(["validate", str(EXAMPLES / "minimal.tsv")])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("3 条记录有效", proc.stdout)

    def test_invalid_log_exit_one_with_lineno(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.tsv")
            with open(path, "w") as fh:
                fh.write(BAD)
            proc = run(["validate", path])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("第 2 行", proc.stdout)


class TestUsage(unittest.TestCase):
    def test_no_command_shows_help(self):
        proc = run([])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("analyze", proc.stdout)


if __name__ == "__main__":
    unittest.main()
