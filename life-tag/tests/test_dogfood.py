#!/usr/bin/env python3
"""Dogfood ground truth for life-tag (生命价签).

examples/metro_worker.json 是一个合成但真实感的画像：
税前月薪 ¥18,000、综合税负 15%、月 21 个工作日 × 8 小时、
单程通勤 55 分钟（月通勤费 ¥300）、恢复系数 0.30、
其他工作开销 ¥700/月。

画像里埋着可手算的已知事实，验收标准：完整管线跑完，
报告必须把它们原样恢复出来。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import life_tag as lt  # noqa: E402

EXAMPLE = str(ROOT / "examples" / "metro_worker.json")


def economics_of_example():
    return lt.economics(lt.load_profile(EXAMPLE))


class TestExampleProfileLoads(unittest.TestCase):
    def test_loads_and_matches_intent(self):
        p = lt.load_profile(EXAMPLE)
        self.assertEqual(p["gross_monthly"], 18000.0)
        self.assertEqual(p["tax_rate"], 0.15)
        self.assertEqual(p["commute_min"], 55.0)
        self.assertEqual(p["recovery_ratio"], 0.30)
        self.assertEqual(p["workdays"], 21.0)
        self.assertEqual(p["daily_hours"], 8.0)


class TestGroundTruthHourly(unittest.TestCase):
    """手算基准：nominal 91.07 → true 55.66，三重税合计侵蚀 38.9%。"""

    def test_nominal_hourly(self):
        e = economics_of_example()
        self.assertAlmostEqual(e["nominal"], 91.07, places=2)

    def test_true_hourly(self):
        e = economics_of_example()
        self.assertAlmostEqual(e["true"], 55.66, places=2)

    def test_erosion_about_39_pct(self):
        e = economics_of_example()
        self.assertAlmostEqual(e["erosion"], 0.3889, places=3)

    def test_true_is_61_pct_of_nominal(self):
        e = economics_of_example()
        self.assertAlmostEqual(e["ratio"], 0.6111, places=3)

    def test_waterfall_taxes(self):
        e = economics_of_example()
        self.assertAlmostEqual(e["recovery_tax"], 21.02, places=2)
        self.assertAlmostEqual(e["commute_tax"], 10.50, places=2)
        self.assertAlmostEqual(e["cost_tax"], 3.89, places=2)
        gap = e["nominal"] - e["true"]
        self.assertAlmostEqual(
            gap, e["recovery_tax"] + e["commute_tax"] + e["cost_tax"], places=9)

    def test_day_net(self):
        e = economics_of_example()
        self.assertAlmostEqual(e["day_net"], 680.95, places=2)


class TestGroundTruthTags(unittest.TestCase):
    def setUp(self):
        self.e = economics_of_example()

    def test_iphone_prohibitive(self):
        # iPhone ¥6999 = 125.7 生命小时 = 10.3 个班次，远超心跳线
        t = lt.price_tag(6999.0, self.e, 8.0)
        self.assertAlmostEqual(t["hours"], 125.7, places=1)
        self.assertAlmostEqual(t["shifts"], 10.3, places=1)
        self.assertTrue(t["over_line"])

    def test_milk_tea_trivial(self):
        # 奶茶 ¥20 = 22 分钟，心跳线以内
        t = lt.price_tag(20.0, self.e, 8.0)
        self.assertAlmostEqual(t["minutes"], 21.6, places=1)
        self.assertFalse(t["over_line"])
        self.assertEqual(t["unit"], "minutes")

    def test_gym_membership_borderline(self):
        # 年卡 ¥3000 = 53.9 小时 = 4.4 个班次：过线，但要自己掂量
        t = lt.price_tag(3000.0, self.e, 8.0)
        self.assertAlmostEqual(t["hours"], 53.9, places=1)
        self.assertTrue(t["over_line"])
        self.assertEqual(t["unit"], "hours")


class TestGroundTruthOvertime(unittest.TestCase):
    def test_one_and_half_mult(self):
        e = economics_of_example()
        o = lt.overtime_math(4.0, 1.5, e)
        self.assertAlmostEqual(o["marginal"], 136.61, places=2)
        self.assertTrue(o["worth_it"])
        # 每小时溢价 = 136.61 − 55.66 = 80.94
        self.assertAlmostEqual(o["premium"], 80.94, places=2)

    def test_flat_rate_still_worth_it(self):
        e = economics_of_example()
        o = lt.overtime_math(4.0, 1.0, e)
        self.assertTrue(o["worth_it"])


class TestGroundTruthLeverage(unittest.TestCase):
    """这个画像的核心洞察：搬近公司 > 涨薪 10%。

    直觉以为加薪是万能药，算术说 55 分钟单程通勤才是最大的出血点。
    """

    def test_ranking(self):
        p = lt.load_profile(EXAMPLE)
        moves = lt.leverage_moves(p, {
            "commute_to": 15.0, "raise_pct": 10.0, "remote_days": 2.0,
            "recovery_to": 0.2, "cut_costs": 200.0,
        })
        labels = [m["label"] for m in moves]
        self.assertIn("通勤", labels[0])
        self.assertIn("涨薪", labels[1])
        self.assertIn("远程", labels[2])
        self.assertIn("砍", labels[-1])

    def test_commute_move_value(self):
        p = lt.load_profile(EXAMPLE)
        moves = lt.leverage_moves(p, {"commute_to": 15.0})
        self.assertAlmostEqual(moves[0]["true"], 63.43, places=2)
        self.assertAlmostEqual(moves[0]["delta"], 7.76, places=2)

    def test_remote_beats_nothing_here(self):
        # 远程 2 天（+4.05）比涨薪 10%（+5.96）少，但对画像仍是正贡献
        p = lt.load_profile(EXAMPLE)
        remote = lt.leverage_moves(p, {"remote_days": 2.0})[0]
        self.assertAlmostEqual(remote["delta"], 4.05, places=2)
        self.assertGreater(remote["delta"], 0)


class TestReportRenders(unittest.TestCase):
    """报告是产品：关键数字必须真的出现在渲染结果里。"""

    def test_hourly_report(self):
        p = lt.load_profile(EXAMPLE)
        text = lt.render_hourly(p, economics_of_example())
        for needle in ("91.07", "55.66", "21.02", "10.50", "3.89",
                       "38.9%", "680.95", "恢复税", "通勤税", "开销税"):
            self.assertIn(needle, text)

    def test_tag_report_over_line(self):
        p = lt.load_profile(EXAMPLE)
        e = economics_of_example()
        t = lt.price_tag(6999.0, e, 8.0)
        text = lt.render_tag(p, e, t, 8.0, 6999.0)
        for needle in ("生命价签", "10.3 个班次", "超过心跳线", "睡一觉"):
            self.assertIn(needle, text)

    def test_tag_report_under_line(self):
        p = lt.load_profile(EXAMPLE)
        e = economics_of_example()
        t = lt.price_tag(20.0, e, 8.0)
        text = lt.render_tag(p, e, t, 8.0, 20.0)
        self.assertIn("22 分钟", text)
        self.assertIn("心跳线以内", text)

    def test_overtime_report(self):
        p = lt.load_profile(EXAMPLE)
        e = economics_of_example()
        text = lt.render_overtime(p, e, lt.overtime_math(4.0, 1.5, e))
        for needle in ("136.61", "55.66", "边际时薪", "自我估价"):
            self.assertIn(needle, text)

    def test_leverage_report(self):
        p = lt.load_profile(EXAMPLE)
        moves = lt.leverage_moves(p, {"commute_to": 15.0, "raise_pct": 10.0})
        text = lt.render_leverage(p, economics_of_example()["true"], moves)
        for needle in ("杠杆排行", "最有效", "通勤", "涨薪"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
