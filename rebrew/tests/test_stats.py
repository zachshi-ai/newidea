#!/usr/bin/env python3
"""Acceptance tests for rebrew (复现那杯) — statistics primitives."""

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rebrew as rb  # noqa: E402


class TestMean(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(rb.mean([1, 2, 3]), 2.0)
        self.assertAlmostEqual(rb.mean([7.0, 8.0]), 7.5)

    def test_mean_single(self):
        self.assertEqual(rb.mean([42]), 42.0)


class TestStdev(unittest.TestCase):
    def test_undefined_below_two(self):
        self.assertIsNone(rb.sample_stdev([5]))
        self.assertIsNone(rb.sample_stdev([]))

    def test_two_points(self):
        # s(7, 8) = |7-8|/sqrt(2)
        self.assertAlmostEqual(rb.sample_stdev([7.0, 8.0]),
                               1.0 / math.sqrt(2))

    def test_constant_series_is_zero(self):
        self.assertEqual(rb.sample_stdev([7.0, 7.0, 7.0, 7.0]), 0.0)

    def test_known_value(self):
        # sample stdev of 2,4,4,4,5,5,7,9 = 2.138...
        self.assertAlmostEqual(rb.sample_stdev([2, 4, 4, 4, 5, 5, 7, 9]),
                               2.138089935299395)


class TestPearson(unittest.TestCase):
    def test_perfect_positive(self):
        self.assertAlmostEqual(rb.pearson([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)

    def test_perfect_negative(self):
        self.assertAlmostEqual(rb.pearson([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)

    def test_flat_series_returns_none(self):
        self.assertIsNone(rb.pearson([5, 5, 5], [1, 2, 3]))
        self.assertIsNone(rb.pearson([1, 2, 3], [5, 5, 5]))

    def test_too_few_points(self):
        self.assertIsNone(rb.pearson([1], [1]))

    def test_known_value(self):
        # classic small dataset: r(1..5, 2,1,4,3,5) = 0.8
        self.assertAlmostEqual(rb.pearson([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]), 0.8)

    def test_noise_dilutes_correlation(self):
        signal = rb.pearson([1, 2, 3, 4, 5, 6, 7, 8],
                            [1, 2, 3, 4, 5, 6, 7, 8])
        noisy = rb.pearson([1, 2, 3, 4, 5, 6, 7, 8],
                           [1, 5, 2, 6, 3, 7, 4, 8])
        self.assertLess(abs(noisy), abs(signal))


class TestRms(unittest.TestCase):
    def test_rms(self):
        self.assertAlmostEqual(rb.rms([3.0, 4.0]), math.sqrt(12.5))

    def test_rms_single(self):
        self.assertAlmostEqual(rb.rms([2.0]), 2.0)

    def test_rms_zeros(self):
        self.assertEqual(rb.rms([0.0, 0.0]), 0.0)


class TestMde(unittest.TestCase):
    def test_none_without_sigma(self):
        self.assertIsNone(rb.mde(None, 2))

    def test_none_without_repeats(self):
        self.assertIsNone(rb.mde(0.5, 0))

    def test_known_value(self):
        # 2.8 * 0.5 * sqrt(2/2) = 1.4
        self.assertAlmostEqual(rb.mde(0.5, 2), 1.4)

    def test_grows_with_sigma(self):
        self.assertGreater(rb.mde(1.0, 2), rb.mde(0.5, 2))

    def test_shrinks_with_repeats(self):
        self.assertLess(rb.mde(0.5, 3), rb.mde(0.5, 2))


class TestStep(unittest.TestCase):
    def test_min_gap(self):
        self.assertEqual(rb._step([90, 92, 96]), 2)

    def test_single_level(self):
        self.assertIsNone(rb._step([90]))

    def test_unsorted_levels_use_adjacent_gaps(self):
        self.assertEqual(rb._step([10, 4, 8]), 2)


if __name__ == "__main__":
    unittest.main()
