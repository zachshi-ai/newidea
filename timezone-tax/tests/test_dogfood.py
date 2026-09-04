#!/usr/bin/env python3
"""时区税验收 A9 — Dogfood：示例数据里的已知答案必须被工具挖出来，
示例生成器重跑必须与提交文件逐字节一致。"""

import filecmp
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

import timezone_tax as tzt  # noqa: E402
import build_examples  # noqa: E402

TEAM = build_examples.build_team_global()
IMPOSSIBLE = build_examples.build_team_impossible()


class TestGeneratorIsDeterministic(unittest.TestCase):
    def test_rebuild_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [sys.executable, str(ROOT / "examples" / "build_examples.py"),
                 tmp], check=True, capture_output=True)
            for name in ["team-global.json", "team-impossible.json",
                         "ledger-halfyear.json"]:
                same = filecmp.cmp(ROOT / "examples" / name,
                                   os.path.join(tmp, name), shallow=False)
                self.assertTrue(same, "%s 重建不一致" % name)


class TestGroundTruth(unittest.TestCase):
    """示例里埋入的事实（人工推演钉死），工具必须原样挖出。"""

    def test_thursday_bill_known_answer(self):
        bill = tzt.bill_at_utc(TEAM, tzt.parse_utc_datetime("2026-09-10T15:00"))
        pinned = {
            "Alice · 旧金山": ("周四 08:00", 1.5),
            "Bruno · 柏林": ("周四 17:00", 0.0),
            "Chitra · 班加罗尔": ("周四 20:30", 1.0),
            "Dawei · 上海": ("周四 23:00", 3.0),
        }
        for row in bill["rows"]:
            local, tax = pinned[row["name"]]
            self.assertEqual(row["local"], local)
            self.assertAlmostEqual(row["tax"], tax)
        self.assertAlmostEqual(bill["total"], 5.5)

    def test_halfyear_ledger_known_answer(self):
        ledger = tzt.load_ledger(str(ROOT / "examples" / "ledger-halfyear.json"))
        self.assertEqual(len(ledger["meetings"]), 52)
        self.assertEqual(ledger["meetings"][0]["utc"], "2026-09-07T15:00")
        self.assertEqual(ledger["meetings"][-1]["utc"], "2027-08-30T15:00")
        # 固定 15:00 UTC 一整年：上海每周深夜 3 点，柏林从未缴税
        self.assertEqual(tzt.summarize_ledger(ledger), {
            "Alice · 旧金山": 78.0, "Bruno · 柏林": 0.0,
            "Chitra · 班加罗尔": 52.0, "Dawei · 上海": 156.0})
        gini = tzt.gini(list(tzt.summarize_ledger(ledger).values()))
        self.assertAlmostEqual(gini, 988.0 / (2 * 16 * 71.5), places=9)
        # README 里印的「0.43」必须就是这两个算式
        self.assertEqual("%.2f" % gini, "0.43")
        self.assertIsNone(tzt.burden_ratio(
            list(tzt.summarize_ledger(ledger).values())))

    def test_report_alarms_on_halfyear_ledger(self):
        totals = tzt.summarize_ledger(
            tzt.load_ledger(str(ROOT / "examples" / "ledger-halfyear.json")),
            team=TEAM)
        level, _ = tzt.fairness_verdict(totals)
        self.assertEqual(level, "alarm")

    def test_plan_says_rotation_cannot_help(self):
        result = tzt.plan_rotation(TEAM, date(2026, 9, 7), 12)
        self.assertTrue(result["structural"])
        level, reasons = tzt.plan_verdict(result, TEAM)
        self.assertEqual(level, "alarm")
        self.assertIn("结构性失衡", reasons[0])
        # 夏令时把会议从 14:00 UTC 挪到 15:00 UTC，但税单分毫未动
        self.assertEqual(result["entries"][0]["bill"]["total"],
                         result["entries"][8]["bill"]["total"])

    def test_impossible_team_is_honestly_impossible(self):
        result = tzt.plan_rotation(IMPOSSIBLE, date(2026, 9, 7), 4)
        self.assertEqual(result["infeasible_weeks"], [1, 2, 3, 4])
        level, reasons = tzt.plan_verdict(result, IMPOSSIBLE)
        self.assertEqual(level, "alarm")
        self.assertIn("组织分布问题", reasons[1])


if __name__ == "__main__":
    unittest.main()
