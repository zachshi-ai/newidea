#!/usr/bin/env python3
"""时区税验收 A8 — CLI 端到端：六个子命令、退出码、优雅失败。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = (sys.executable, str(ROOT / "timezone_tax.py"))
EXAMPLES = ROOT / "examples"
TEAM = str(EXAMPLES / "team-global.json")
IMPOSSIBLE = str(EXAMPLES / "team-impossible.json")
LEDGER = str(EXAMPLES / "ledger-halfyear.json")


def run(args):
    return subprocess.run(CLI + tuple(args), capture_output=True,
                          text=True)


class TestInspect(unittest.TestCase):
    def test_known_bill(self):
        proc = run(["inspect", TEAM, "--utc", "2026-09-10T15:00"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for fragment in ["【税单】2026-09-10 15:00 UTC", "周四 23:00",
                         "深夜", "3", "合计 5.5 税点",
                         "最惨成员：Dawei · 上海"]:
            self.assertIn(fragment, proc.stdout)

    def test_infeasible_slot_flagged(self):
        proc = run(["inspect", TEAM, "--utc", "2026-09-10T16:00"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("不可行", proc.stdout)
        self.assertIn("睡眠时段", proc.stdout)

    def test_bad_utc_fails_gracefully(self):
        proc = run(["inspect", TEAM, "--utc", "下周四"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("错误", proc.stderr)

    def test_missing_team_fails_gracefully(self):
        proc = run(["inspect", str(ROOT / "nope.json"),
                    "--utc", "2026-09-10T15:00"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("读不了", proc.stderr)


class TestPlan(unittest.TestCase):
    def test_structural_plan(self):
        proc = run(["plan", TEAM, "--start", "2026-09-07", "--weeks", "8"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for fragment in ["【轮换计划】", "14:00 UTC", "【计划期末税负】",
                         "【判定】警报", "结构性失衡", "轮换无效"]:
            self.assertIn(fragment, proc.stdout)

    def test_dst_week_visible(self):
        proc = run(["plan", TEAM, "--start", "2026-09-07", "--weeks", "12"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("第 9 周 2026-11-02 · 15:00 UTC", proc.stdout)

    def test_impossible_team_reports_no_solution(self):
        proc = run(["plan", IMPOSSIBLE, "--start", "2026-09-07",
                    "--weeks", "3"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("无解", proc.stdout)

    def test_save_writes_reportable_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "plan-ledger.json")
            proc = run(["plan", TEAM, "--start", "2026-09-07",
                        "--weeks", "12", "--save", out])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(len(data["meetings"]), 12)
            rep = run(["report", out, "--team", TEAM])
            self.assertEqual(rep.returncode, 3, rep.stdout)
            self.assertIn("警报", rep.stdout)


class TestSimulate(unittest.TestCase):
    def test_halfyear_projection(self):
        proc = run(["simulate", TEAM, "--utc", "15:00",
                    "--start", "2026-09-07", "--weeks", "52"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for fragment in ["【固定槽模拟】", "23:00（第1–52周）", "156",
                         "缴税基尼 0.43", "最惨比率 ∞", "【判定】警报"]:
            self.assertIn(fragment, proc.stdout)

    def test_always_infeasible_slot(self):
        proc = run(["simulate", TEAM, "--utc", "16:00",
                    "--start", "2026-09-07", "--weeks", "3"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("3 周不可行", proc.stdout)


class TestRecord(unittest.TestCase):
    def test_init_then_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "ledger.json")
            first = run(["record", out, TEAM, "--init",
                         "--utc", "2026-09-14T15:00", "--note", "周会"])
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("现共 1 条会议", first.stdout)
            second = run(["record", out, TEAM,
                          "--utc", "2026-09-21T15:00"])
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("现共 2 条会议", second.stdout)
            rep = run(["report", out, "--team", TEAM])
            # 两次 15:00 会议：Alice 3 / Chitra 2 / Dawei 6 / Bruno 0 → 警报
            self.assertEqual(rep.returncode, 3, rep.stdout)

    def test_record_without_init_on_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "ledger.json")
            proc = run(["record", out, TEAM, "--utc", "2026-09-14T15:00"])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("读不了", proc.stderr)


class TestReport(unittest.TestCase):
    def test_halfyear_ledger_alarms_with_exit_3(self):
        proc = run(["report", LEDGER, "--team", TEAM])
        self.assertEqual(proc.returncode, 3, proc.stdout)
        for fragment in ["【税负账本】", "52 条会议",
                         "累计 156 税点（占 55%）", "累计 0 税点（占 0%）",
                         "∞", "警报", "从未缴税"]:
            self.assertIn(fragment, proc.stdout)

    def test_balanced_ledger_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "balanced.json")
            with open(out, "w", encoding="utf-8") as fh:
                json.dump({"meetings": [
                    {"utc": "2026-09-07T15:00", "note": "",
                     "bills": {"早班": 1.5, "夜班": 1.5}},
                    {"utc": "2026-09-14T15:00", "note": "",
                     "bills": {"早班": 1.5, "夜班": 1.5}},
                ]}, fh, ensure_ascii=False)
            proc = run(["report", out])
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("健康", proc.stdout)

    def test_missing_ledger_fails_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run(["report", os.path.join(tmp, "nope.json")])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("读不了", proc.stderr)


class TestValidate(unittest.TestCase):
    def test_valid_files_pass(self):
        proc = run(["validate", TEAM, LEDGER])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("全部通过", proc.stdout)
        self.assertIn("52 条会议", proc.stdout)

    def test_broken_team_reports_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "bad.json")
            with open(out, "w", encoding="utf-8") as fh:
                json.dump({"members": [{"name": "x", "offset_min": 99999}]},
                          fh)
            proc = run(["validate", out])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("offset_min", proc.stderr)

    def test_broken_json_fails_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "bad.json")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("{oops")
            proc = run(["validate", out])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("JSON", proc.stderr)


class TestBareInvocation(unittest.TestCase):
    def test_no_command_shows_help_and_exits_1(self):
        proc = run([])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("usage", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
