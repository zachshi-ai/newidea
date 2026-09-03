#!/usr/bin/env python3
"""Acceptance tests A9 (dogfood) for left-behind (漏带时刻).

示例账本埋入了已知模式（见 examples/build_examples.py 的剧本注释）：
验收即断言「报告能恢复埋进去的模式」。生成器为确定性剧本——
重跑必须与提交文件逐字节一致。
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import left_behind as lb  # noqa: E402

EXAMPLES = ROOT / "examples"
REALISTIC = EXAMPLES / "realistic.tsv"
MINIMAL = EXAMPLES / "minimal.tsv"


def analyze_text(path=REALISTIC, extra=()):
    proc = subprocess.run(
        (sys.executable, str(ROOT / "left_behind.py"), "analyze", str(path))
        + tuple(extra), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


class TestExamplesAreDeterministic(unittest.TestCase):
    def test_rebuild_is_byte_identical(self):
        for path in (REALISTIC, MINIMAL):
            before = path.read_bytes()
            proc = subprocess.run(
                (sys.executable, str(EXAMPLES / "build_examples.py")),
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(path.read_bytes(), before,
                             "%s 重跑生成器后发生了变化" % path.name)


class TestBuriedPatternsAreRecovered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = analyze_text()
        cls.events = lb.read_events(REALISTIC)

    def test_overview_numbers(self):
        self.assertIn("12 次行程、35 条事件", self.report)
        self.assertIn("漏带率 0.58 件/次（7 件）", self.report)
        self.assertIn("幽灵率 0.58 件/次（7 件）", self.report)
        self.assertIn("补救账单 ¥279", self.report)
        self.assertIn("1 件漏带未记价", self.report)

    def test_blind_spot_charger(self):
        self.assertIn("手机充电头（electronics）：漏带 2 次，累计 ¥158", self.report)
        self.assertIn("2026-07-08（T006）", self.report)

    def test_ghost_ranking(self):
        self.assertIn("雨伞：3 次白扛（1.1 kg）", self.report)
        self.assertIn("健身裤：2 次白扛（800 g）", self.report)

    def test_convergence_improving(self):
        self.assertIn("前 6 次行程漏带率 0.83 件/次 → 后 6 次 0.33 件/次：在改善",
                      self.report)

    def test_minimal_refuses_trend(self):
        report = analyze_text(MINIMAL)
        self.assertIn("拒绝评估趋势", report)

    def test_pack_surface_carries_the_lessons(self):
        proc = subprocess.run(
            (sys.executable, str(ROOT / "left_behind.py"), "pack",
             str(REALISTIC), "--type", "business", "--days", "3"),
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        pack_text = proc.stdout
        self.assertIn("⚠ 手机充电头（electronics）：已漏带 2 次", pack_text)
        self.assertIn("· 手机充电线（7/7 次）", pack_text)
        self.assertIn("雨伞：3 次原样往返，累计白扛 1.1 kg", pack_text)
        del pack_text

    def test_programmatic_ground_truth(self):
        trips = lb.aggregate_trips(self.events)
        conv = lb.convergence(trips)
        self.assertAlmostEqual(conv["before"], 5 / 6)
        self.assertAlmostEqual(conv["after"], 2 / 6)
        self.assertEqual(conv["direction"], "improving")
        spots = lb.blind_spots(self.events)
        self.assertEqual([row[0] for row in spots], ["手机充电头"])
        cargo = lb.ghost_cargo(self.events)
        self.assertEqual(cargo[0][0], "雨伞")
        self.assertAlmostEqual(cargo[0][2], 1050.0)


if __name__ == "__main__":
    unittest.main()
