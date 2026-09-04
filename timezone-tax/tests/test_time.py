#!/usr/bin/env python3
"""时区税验收 A1 — 时间原语：偏移、夏令时（美/欧/南半球环绕）、跨日翻转。"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import timezone_tax as tzt  # noqa: E402
from datetime import datetime  # noqa: E402


def member(offset, dst=None):
    m = {"name": "x", "offset_min": offset}
    if dst:
        m["dst"] = dst
    return m


class TestOffsets(unittest.TestCase):
    def test_plain_offset(self):
        local_date, local_min = tzt.utc_to_local(
            datetime(2026, 9, 10, 15, 0), member(330))
        self.assertEqual((local_date, local_min), (date(2026, 9, 10), 1230))

    def test_day_rollover_and_weekday(self):
        # UTC 周四 23:00 + 上海 = 周五 07:00，本地星期随偏移翻转
        local_date, local_min = tzt.utc_to_local(
            datetime(2026, 9, 10, 23, 0), member(480))
        self.assertEqual(local_date, date(2026, 9, 11))
        self.assertEqual(local_min, 420)
        self.assertEqual(local_date.weekday(), 4)  # 周五

    def test_negative_rollover(self):
        # UTC 周四 02:00 - 8h = 周三 18:00
        local_date, local_min = tzt.utc_to_local(
            datetime(2026, 9, 10, 2, 0), member(-480))
        self.assertEqual((local_date, local_min), (date(2026, 9, 9), 1080))


class TestDstRules(unittest.TestCase):
    SF = [{"from": "03-08", "to": "11-01", "offset_min": -420}]
    EU = [{"from": "03-29", "to": "10-25", "offset_min": 120}]

    def test_us_summer_vs_winter(self):
        # 2026-07-01：美西夏令时 -420；2026-12-01：标准时 -480
        self.assertEqual(tzt.utc_to_local(datetime(2026, 7, 1, 15, 0),
                                          member(-480, self.SF)),
                         (date(2026, 7, 1), 480))
        self.assertEqual(tzt.utc_to_local(datetime(2026, 12, 1, 15, 0),
                                          member(-480, self.SF)),
                         (date(2026, 12, 1), 420))

    def test_eu_summer_vs_winter(self):
        self.assertEqual(tzt.utc_to_local(datetime(2026, 7, 1, 15, 0),
                                          member(60, self.EU)),
                         (date(2026, 7, 1), 1020))
        self.assertEqual(tzt.utc_to_local(datetime(2026, 12, 1, 15, 0),
                                          member(60, self.EU)),
                         (date(2026, 12, 1), 960))

    def test_rule_boundaries_are_half_open(self):
        rule = {"from": "03-08", "to": "11-01", "offset_min": -420}
        self.assertTrue(tzt.rule_applies(date(2026, 3, 8), rule))
        self.assertFalse(tzt.rule_applies(date(2026, 11, 1), rule))

    def test_southern_hemisphere_wrap(self):
        # 悉尼式规则 09-27 → 04-05，区间跨年环绕
        wrap = [{"from": "09-27", "to": "04-05", "offset_min": 660}]
        # 一月：南半球盛夏，在区间内
        self.assertEqual(tzt.utc_to_local(datetime(2026, 1, 15, 15, 0),
                                          member(600, wrap)),
                         (date(2026, 1, 16), 120))
        # 六月：南半球冬天，标准时
        self.assertEqual(tzt.utc_to_local(datetime(2026, 6, 15, 15, 0),
                                          member(600, wrap)),
                         (date(2026, 6, 16), 60))

    def test_fixed_year_rule_does_not_repeat_next_year(self):
        fixed = [{"from": "2026-03-08", "to": "2026-11-01",
                  "offset_min": -420}]
        self.assertTrue(tzt.rule_applies(date(2026, 7, 1), fixed[0]))
        self.assertFalse(tzt.rule_applies(date(2027, 7, 1), fixed[0]))

    def test_feb29_rule_clamps_on_common_years(self):
        # 02-29 端点在平年收敛到 02-28，不崩
        rule = {"from": "02-29", "to": "03-15", "offset_min": 120}
        self.assertTrue(tzt.rule_applies(date(2027, 2, 28), rule))
        self.assertTrue(tzt.rule_applies(date(2027, 3, 14), rule))
        self.assertFalse(tzt.rule_applies(date(2027, 3, 15), rule))

    def test_bad_rule_date_raises(self):
        with self.assertRaises(tzt.TaxError):
            tzt.parse_rule_date("13-40")
        with self.assertRaises(tzt.TaxError):
            tzt.parse_rule_date("2026/03/08")

    def test_multi_year_span_uses_fixed_dates(self):
        # 绝对日期区间可以跨年（from 固定 2026-10，to 固定 2027-04）
        rule = {"from": "2026-10-01", "to": "2027-04-01",
                "offset_min": 660}
        self.assertTrue(tzt.rule_applies(date(2027, 1, 15), rule))
        self.assertFalse(tzt.rule_applies(date(2026, 9, 30), rule))


class TestParsing(unittest.TestCase):
    def test_parse_hhmm(self):
        self.assertEqual(tzt.parse_hhmm("07:00"), 420)
        self.assertEqual(tzt.parse_hhmm("24:00", allow_24=True), 1440)
        with self.assertRaises(tzt.TaxError):
            tzt.parse_hhmm("24:30", allow_24=True)
        with self.assertRaises(tzt.TaxError):
            tzt.parse_hhmm("7am")

    def test_parse_utc_datetime(self):
        self.assertEqual(tzt.parse_utc_datetime("2026-09-10T15:00"),
                         datetime(2026, 9, 10, 15, 0))
        self.assertEqual(tzt.parse_utc_datetime("2026-09-10 15:00"),
                         datetime(2026, 9, 10, 15, 0))
        with self.assertRaises(tzt.TaxError):
            tzt.parse_utc_datetime("2026-09-10T15:00+08:00")

    def test_fmt_tax(self):
        self.assertEqual(tzt.fmt_tax(0), "0")
        self.assertEqual(tzt.fmt_tax(1.5), "1.5")
        self.assertEqual(tzt.fmt_tax(156.0), "156")
        self.assertEqual(tzt.fmt_tax(0.5), "0.5")


if __name__ == "__main__":
    unittest.main()
