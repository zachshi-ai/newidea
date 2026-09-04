#!/usr/bin/env python3
"""时区税验收 A2 — 税带：边界半开、税率可配置。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import timezone_tax as tzt  # noqa: E402

W = tzt.DEFAULT_WEIGHTS


class TestBands(unittest.TestCase):
    def test_band_boundaries_half_open(self):
        cases = [
            (0, "night", 3.0),      # 深夜从零点起
            (419, "night", 3.0),    # 06:59
            (420, "early", 1.5),    # 07:00
            (539, "early", 1.5),    # 08:59
            (540, "prime", 0.0),    # 09:00
            (1079, "prime", 0.0),   # 17:59
            (1080, "evening", 1.0),  # 18:00
            (1319, "evening", 1.0),  # 21:59
            (1320, "night", 3.0),   # 22:00
            (1439, "night", 3.0),   # 23:59
        ]
        for minute, band, tax in cases:
            got_band, got_tax = tzt.classify_band(minute, W)
            self.assertEqual((got_band, got_tax), (band, tax),
                             "local_min=%d" % minute)

    def test_custom_weights(self):
        weights = dict(W, night=10.0, early=2.0)
        self.assertEqual(tzt.classify_band(100, weights), ("night", 10.0))
        self.assertEqual(tzt.classify_band(480, weights), ("early", 2.0))
        self.assertEqual(tzt.classify_band(600, weights), ("prime", 0.0))

    def test_team_weights_merge(self):
        team = {"members": [{"name": "a", "offset_min": 0}],
                "weights": {"night": 9}}
        weights = tzt.team_weights(team)
        self.assertEqual(weights["night"], 9)
        self.assertEqual(weights["early"], 1.5)  # 未覆盖的键用默认
        self.assertEqual(weights["prime"], 0.0)


if __name__ == "__main__":
    unittest.main()
