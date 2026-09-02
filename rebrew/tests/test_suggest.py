#!/usr/bin/env python3
"""Acceptance tests for rebrew (复现那杯) — suggestion stages.

The suggestion ladder is the core product decision:
  reproduce → stabilize → explore → experiment
and each stage must fire exactly when its precondition holds.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rebrew as rb  # noqa: E402

from test_analysis import pour, temp_effect_pours  # noqa: E402


class TestReproduceStage(unittest.TestCase):
    def test_empty_log(self):
        result = rb.suggest([])
        self.assertEqual(result["kind"], "reproduce")

    def test_no_repeated_recipe_demands_reproduction(self):
        pours = [pour(temp=t) for t in (90, 92, 94, 96)]  # 每个配方只冲过一次
        result = rb.suggest(pours)
        self.assertEqual(result["kind"], "reproduce")
        self.assertIn("复冲", "".join(result["plan"]))
        self.assertIn("测不出", result["message"])


class TestStabilizeStage(unittest.TestCase):
    def test_high_noise_forbids_tuning(self):
        # 同配方重复评分 5 与 8 → σ̂=2.12 ≥ 1.5：调参都是抽奖
        pours = [pour(temp=90, rating=5.0), pour(temp=90, rating=8.0),
                 pour(temp=93, rating=5.5), pour(temp=93, rating=8.5),
                 pour(temp=96, rating=6.0), pour(temp=96, rating=9.0)]
        result = rb.suggest(pours)
        self.assertEqual(result["kind"], "stabilize")
        self.assertIn("抽奖", result["message"])

    def test_boundary_just_below_ceiling_still_experiments(self):
        # 组内差 2.0 → 每组 s = 2.0/√2 ≈ 1.414 < 1.5：还在实验线内
        pours = [pour(temp=90, rating=6.0), pour(temp=90, rating=8.0),
                 pour(temp=93, rating=6.5), pour(temp=93, rating=8.5),
                 pour(temp=96, rating=7.0), pour(temp=96, rating=9.0)]
        result = rb.suggest(pours)
        self.assertEqual(result["kind"], "experiment")


class TestExploreStage(unittest.TestCase):
    def test_single_recipe_with_low_noise(self):
        pours = [pour(rating=7.0), pour(rating=7.3), pour(rating=7.1)]
        result = rb.suggest(pours)
        self.assertEqual(result["kind"], "explore")
        self.assertIn("参数空间", result["message"])


class TestExperimentStage(unittest.TestCase):
    def test_single_factor_plan_on_embedded_effect(self):
        result = rb.suggest(temp_effect_pours())
        self.assertEqual(result["kind"], "experiment")
        self.assertIn("temp_c", result["message"])
        plan = "\n".join(result["plan"])
        self.assertIn("锁定", plan)
        self.assertIn("只动 temp_c", plan)
        self.assertIn("MDE", plan)

    def test_plan_locks_best_fingerprint(self):
        pours = ([pour(temp=90, rating=5.0), pour(temp=90, rating=5.2)]
                 + [pour(temp=96, rating=8.0), pour(temp=96, rating=8.2)])
        plan = "\n".join(rb.suggest(pours)["plan"])
        self.assertIn("96", plan.split("，")[0])  # 锁定行含最优水温

    def test_plan_reports_mde_threshold(self):
        pours = temp_effect_pours()
        _, sigma = rb.reproducibility(pours)
        plan = "\n".join(rb.suggest(pours)["plan"])
        self.assertIn("%.2f" % rb.mde(sigma, 2), plan)

    def test_step_is_min_historical_gap(self):
        # 水温取值 {90, 93, 96} → 步长 3 → 实验档 93 与 99（center=96）
        result = rb.suggest(temp_effect_pours())
        self.assertIn("93 与 99", "\n".join(result["plan"]))


class TestStageLadder(unittest.TestCase):
    """阶段顺序：复现 → 降方差 → 散开探索 → 单因素实验，逐级解锁。"""

    def test_ladder_progression(self):
        # 第 1 级：没有任何重复 → reproduce
        unrepeated = [pour(temp=t) for t in (90, 93, 96)]
        self.assertEqual(rb.suggest(unrepeated)["kind"], "reproduce")

        # 第 2 级：有重复但噪声爆炸 → stabilize
        noisy = unrepeated + [pour(temp=90, rating=2.0),
                              pour(temp=93, rating=2.0),
                              pour(temp=96, rating=2.0)]
        self.assertEqual(rb.suggest(noisy)["kind"], "stabilize")

        # 第 3、4 级见上方 TestExploreStage / TestExperimentStage


if __name__ == "__main__":
    unittest.main()
