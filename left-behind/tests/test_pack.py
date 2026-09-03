#!/usr/bin/env python3
"""Acceptance tests A6/A7 (pack generation) for left-behind (漏带时刻)."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import left_behind as lb  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load_realistic():
    events = lb.read_events(EXAMPLES / "realistic.tsv")
    return events, lb.aggregate_trips(events)


class TestBaselineScaling_A6(unittest.TestCase):
    def test_durable_is_one(self):
        self.assertEqual(lb.baseline_quantity(False, 7), 1)

    def test_consumable_is_days_plus_one(self):
        self.assertEqual(lb.baseline_quantity(True, 3), 4)

    def test_consumable_capped_at_ten(self):
        self.assertEqual(lb.baseline_quantity(True, 20), 10)
        self.assertEqual(lb.baseline_quantity(True, 9), 10)

    def test_pack_text_renders_scaling(self):
        events, trips = load_realistic()
        pack = lb.build_pack(events, trips, "business", 2)
        text = lb.build_pack_text(pack)
        self.assertIn("内裤×3", text)  # days=2 → 2+1
        self.assertIn("外套", text)    # 耐用品不带 ×


class TestPackSections_A6(unittest.TestCase):
    def setUp(self):
        self.events, self.trips = load_realistic()

    def test_blindspot_flagged_with_trip_and_date(self):
        pack = lb.build_pack(self.events, self.trips, "business", 3)
        self.assertEqual(pack["blindspots"][0][0], "手机充电头")
        text = lb.build_pack_text(pack)
        self.assertIn("已漏带 2 次", text)
        self.assertIn("T006", text)

    def test_staples_from_trip_type_history_only(self):
        pack = lb.build_pack(self.events, self.trips, "business", 3)
        items = [row[0] for row in pack["staples"]]
        self.assertIn("手机充电线", items)          # business used 7 次
        self.assertIn("笔记本电脑+电源", items)     # business used 5 次
        self.assertNotIn("防晒", items)             # 防晒是 leisure 的常备
        self.assertNotIn("水杯", items)

    def test_blindspot_not_duplicated_in_staples(self):
        pack = lb.build_pack(self.events, self.trips, "business", 3)
        text = lb.build_pack_text(pack)
        flagged = {row[0] for row in pack["blindspots"]}
        staples_in_text = [row[0] for row in pack["staples"] if row[0] not in flagged]
        self.assertNotIn("手机充电头", staples_in_text)  # 已置顶，不重复列
        self.assertEqual(staples_in_text.count("手机充电头"), 0)
        del text

    def test_ghosts_demoted_after_two(self):
        pack = lb.build_pack(self.events, self.trips, "business", 3)
        demoted = {row[0] for row in pack["demoted"]}
        self.assertIn("雨伞", demoted)      # 3 次白扛
        self.assertIn("健身裤", demoted)    # 2 次白扛
        self.assertNotIn("会议资料", demoted)  # 只白扛 1 次，不到降级线
        text = lb.build_pack_text(pack)
        self.assertIn("这次真的会用到吗", text)

    def test_all_flag_restores_ghosts(self):
        pack = lb.build_pack(self.events, self.trips, "business", 3, all_ghosts=True)
        self.assertEqual(pack["demoted"], [])
        self.assertEqual(len(pack["demoted_full"]), 2)
        text = lb.build_pack_text(pack)
        self.assertIn("--all 已生效", text)


class TestDefaults_A7(unittest.TestCase):
    def setUp(self):
        self.events, self.trips = load_realistic()

    def test_default_type_is_most_frequent(self):
        pack = lb.build_pack(self.events, self.trips)
        self.assertEqual(pack["trip_type"], "business")  # 7 次 > leisure 5 次

    def test_default_days_is_type_median_mean(self):
        pack = lb.build_pack(self.events, self.trips)
        self.assertEqual(pack["days"], 3)  # business 行程天数均值 (3+2+4+3+2+3+4)/7
        self.assertIn("均值", pack["days_source"])

    def test_unknown_type_falls_back_to_baseline(self):
        pack = lb.build_pack(self.events, self.trips, "safari")
        self.assertEqual(pack["days"], 3)
        self.assertIn("没有 safari 行程的历史", pack["days_source"])
        self.assertEqual(pack["staples"], [])
        text = lb.build_pack_text(pack)
        self.assertIn("used 记录", text)  # 声明「你的常备」区为什么是空的

    def test_empty_ledger_declares_no_personalization(self):
        pack = lb.build_pack([], [])
        self.assertFalse(pack["has_data"])
        self.assertIsNone(pack["trip_type"])
        text = lb.build_pack_text(pack)
        self.assertIn("平均人", text)
        self.assertIn("首次出发", text)
        self.assertIn("身份证/护照", text)  # 基线仍然完整

    def test_type_with_no_history_still_declares_days_fallback(self):
        pack = lb.build_pack(self.events, self.trips, "safari", None)
        self.assertEqual(pack["days_source"], "默认（账本里没有 safari 行程的历史）")


if __name__ == "__main__":
    unittest.main()
