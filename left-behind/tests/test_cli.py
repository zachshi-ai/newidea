#!/usr/bin/env python3
"""Acceptance tests A8 (CLI end-to-end) for left-behind (漏带时刻)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = (sys.executable, str(ROOT / "left_behind.py"))
EXAMPLES = ROOT / "examples"

HEADER = "\t".join(["date", "trip_id", "trip_type", "days", "item", "category",
                    "event", "cost", "weight_g", "notes"])
GOOD = (HEADER + "\n"
        + "2026-04-08\tT001\tbusiness\t3\t手机充电头\telectronics\tleft\t89\t\t\n"
        + "2026-04-08\tT001\tbusiness\t3\t雨伞\tmisc\tghost\t\t350\t\n")
BAD = (HEADER + "\n"
       + "2026-04-08\tT001\tbusiness\t3\t手机充电头\telectronics\tforgot\t89\t\t\n")


def run(args, cwd=None):
    return subprocess.run(CLI + tuple(args), capture_output=True,
                          text=True, cwd=cwd)


class TestAnalyze(unittest.TestCase):
    def test_exit_zero_and_section_titles(self):
        proc = run(["analyze", str(EXAMPLES / "realistic.tsv")])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for section in ["【总览】", "【盲区】", "【品类分布】", "【幽灵货物】",
                        "【收敛】", "【行程画像】", "【下一步】"]:
            self.assertIn(section, proc.stdout)

    def test_type_filter(self):
        proc = run(["analyze", str(EXAMPLES / "realistic.tsv"),
                    "--type", "leisure"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("leisure×5", proc.stdout)
        self.assertNotIn("business×7", proc.stdout)

    def test_unknown_type_fails_gracefully(self):
        proc = run(["analyze", str(EXAMPLES / "realistic.tsv"),
                    "--type", "safari"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("safari", proc.stderr)

    def test_broken_ledger_exits_two(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.tsv")
            with open(path, "w") as fh:
                fh.write(BAD)
            proc = run(["analyze", path])
            self.assertEqual(proc.returncode, 2)
            self.assertIn("解析失败", proc.stderr)
            self.assertIn("第 2 行", proc.stderr)

    def test_missing_file_exits_two(self):
        proc = run(["analyze", "/nonexistent/ledger.tsv"])
        self.assertEqual(proc.returncode, 2)

    def test_empty_ledger_refuses_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "empty.tsv")
            with open(path, "w") as fh:
                fh.write(HEADER + "\n")
            proc = run(["analyze", path])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("没东西可分析", proc.stderr)


class TestPack(unittest.TestCase):
    def test_exit_zero_and_sections(self):
        proc = run(["pack", str(EXAMPLES / "realistic.tsv"),
                    "--type", "business", "--days", "3"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for section in ["【先摸口袋】", "【基线】", "【你的常备】", "【想清楚再带】"]:
            self.assertIn(section, proc.stdout)
        self.assertIn("手机充电头", proc.stdout)
        self.assertIn("雨伞", proc.stdout)

    def test_all_flag_shows_restored_ghosts(self):
        proc = run(["pack", str(EXAMPLES / "realistic.tsv"), "--all"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--all 已生效", proc.stdout)

    def test_empty_ledger_prints_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "empty.tsv")
            with open(path, "w") as fh:
                fh.write(HEADER + "\n")
            proc = run(["pack", path])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("平均人", proc.stdout)
            self.assertIn("身份证/护照", proc.stdout)


class TestValidate(unittest.TestCase):
    def test_valid_ledger(self):
        proc = run(["validate", str(EXAMPLES / "realistic.tsv")])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("12 次行程、35 条事件有效", proc.stdout)

    def test_invalid_ledger_exit_one_with_lineno(self):
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
