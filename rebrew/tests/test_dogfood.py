#!/usr/bin/env python3
"""Dogfood acceptance tests for rebrew (复现那杯).

examples/realistic.tsv is synthetic data with KNOWN ground truth baked in
(see examples/build_examples.py): water temp +, grind -, 1:15 ratio optimum,
σ≈0.5 noise. The tool passes only if its report recovers those directions —
i.e. it actually mines the embedded causality instead of narrating vibes.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rebrew as rb  # noqa: E402

EXAMPLES = ROOT / "examples"


class TestRealisticLogGroundTruth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pours = rb.read_pours(EXAMPLES / "realistic.tsv")
        cls.chosen, cls.domain = rb.select_domain(cls.pours)
        cls.repeated, cls.sigma = rb.reproducibility(cls.domain)
        cls.ranking = rb.knob_ranking(cls.domain)

    def test_log_shape(self):
        self.assertEqual(len(self.pours), 59)
        self.assertEqual(self.chosen, "Ethiopia Chelbesa")
        self.assertEqual(len(self.domain), 49)

    def test_noise_recovered(self):
        # 埋入噪声 σ=0.5：估计值应落在 [0.25, 0.85]，且低于实验线 1.5
        self.assertIsNotNone(self.sigma)
        self.assertGreaterEqual(self.sigma, 0.25)
        self.assertLessEqual(self.sigma, 0.85)

    def test_repeated_groups_exist(self):
        self.assertGreaterEqual(len(self.repeated), 4)

    def test_temperature_effect_recovered(self):
        # 埋入主效应：水温 +0.45 分/°C → 应登顶旋钮排行且方向为正
        top = self.ranking[0]
        self.assertEqual(top["attr"], "temp_c")
        self.assertGreater(top["r"], 0.5)

    def test_grind_effect_direction_recovered(self):
        # 埋入副作用：研磨越细越过萃 → 方向应为负
        by_attr = {s["attr"]: s for s in self.ranking}
        self.assertLess(by_attr["grind"]["r"], 0)

    def test_temperature_group_means_monotone_up(self):
        rows = dict((v, m) for v, m, n in rb.group_means(self.domain, "temp_c"))
        self.assertLess(rows[90.0], rows[92.0])
        self.assertLess(rows[92.0], rows[94.0])
        self.assertGreater(rows[96.0] - rows[90.0], 1.0)

    def test_ratio_optimum_recovered(self):
        # 埋入：1:15 是这支豆的最优比例（倒 U）→ 分组均值 15 应优于 14 与 16
        rows = dict((v, m) for v, m, n in rb.group_means(self.domain, "ratio"))
        self.assertGreater(rows[15.0], rows[14.0])
        self.assertGreater(rows[15.0], rows[16.0])

    def test_suggestion_is_single_factor_on_temp(self):
        result = rb.suggest(self.domain)
        self.assertEqual(result["kind"], "experiment")
        self.assertIn("temp_c", result["message"])
        plan = "\n".join(result["plan"])
        self.assertIn("锁定", plan)
        self.assertIn("MDE", plan)

    def test_full_report_renders(self):
        report = rb.build_report(self.pours)
        self.assertIn("复现那杯", report)
        self.assertIn("σ̂ ≈ %.2f" % self.sigma, report)
        self.assertIn("水温", report)


class TestMinimalExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pours = rb.read_pours(EXAMPLES / "minimal.tsv")

    def test_two_identical_recipes(self):
        repeated, sigma = rb.reproducibility(self.pours)
        self.assertEqual(len(repeated), 1)
        # 7.0 与 8.0 → s = 1/√2
        import math
        self.assertAlmostEqual(sigma, 1 / math.sqrt(2))

    def test_suggestion_reachable(self):
        result = rb.suggest(self.pours)
        self.assertIn(result["kind"], ("experiment", "explore"))


class TestExamplesAreReproducible(unittest.TestCase):
    def test_regeneration_is_byte_identical(self):
        """固定 seed：重跑生成器必须得到与仓库提交完全一致的示例文件。"""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "examples"
            target.mkdir()
            shutil.copy(EXAMPLES / "build_examples.py", target / "build_examples.py")
            subprocess.run([sys.executable, str(target / "build_examples.py")],
                           check=True, capture_output=True)
            for name in ("realistic.tsv", "minimal.tsv"):
                committed = (EXAMPLES / name).read_bytes()
                regenerated = (target / name).read_bytes()
                self.assertEqual(committed, regenerated,
                                 "%s 与 build_examples.py 输出不一致" % name)


if __name__ == "__main__":
    unittest.main()
