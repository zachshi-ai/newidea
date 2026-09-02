#!/usr/bin/env python3
"""Acceptance tests for rebrew (复现那杯) — analysis core.

Key acceptance claims:
  * reproducibility (复现半径) is exact on synthetic groups, and honestly
    reports "cannot estimate" when no recipe was ever repeated
  * knob_ranking recovers an embedded parameter effect
  * fingerprints ignore time_s (a process outcome, not a knob)
"""

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rebrew as rb  # noqa: E402


def pour(date="2026-08-01", bean="Ethiopia", dose=15.0, water=225.0,
         temp=93.0, grind=6.0, time=145.0, rating=7.0, notes=""):
    return rb.Pour(date=date, bean=bean, dose_g=dose, water_g=water,
                   temp_c=temp, grind=grind, time_s=time, rating=rating,
                   notes=notes, lineno=0)


def temp_effect_pours():
    """6 杯、3 个配方各重复 2 次，评分随水温线性上升、组内小波动。

    埋入效应：水温每 +3°C 评分 +1.3 → r(temp_c, rating) 应接近 1。
    """
    pours = []
    for temp, base in [(90.0, 6.0), (93.0, 7.3), (96.0, 8.6)]:
        pours.append(pour(temp=temp, rating=base))
        pours.append(pour(temp=temp, rating=base + 0.2))
    return pours


class TestFingerprint(unittest.TestCase):
    def test_same_recipe_same_fingerprint(self):
        self.assertEqual(pour().fingerprint(), pour().fingerprint())

    def test_time_is_not_part_of_fingerprint(self):
        self.assertEqual(pour(time=140).fingerprint(),
                         pour(time=200).fingerprint())

    def test_any_knob_change_changes_fingerprint(self):
        fp = pour().fingerprint()
        for changed in (pour(temp=94), pour(grind=7), pour(dose=16),
                        pour(water=230), pour(bean="Kenya")):
            self.assertNotEqual(fp, changed.fingerprint())


class TestReproducibility(unittest.TestCase):
    def test_no_repeats_honest_none(self):
        pours = [pour(temp=t) for t in (90, 92, 94, 96)]
        groups, sigma = rb.reproducibility(pours)
        self.assertEqual(groups, [])
        self.assertIsNone(sigma)  # 测不了就说测不了，不假装能算

    def test_sigma_exact_on_single_group(self):
        pours = [pour(rating=7.0), pour(rating=8.0)]
        groups, sigma = rb.reproducibility(pours)
        self.assertEqual(len(groups), 1)
        self.assertAlmostEqual(sigma, 1.0 / math.sqrt(2))

    def test_sigma_is_rms_across_groups(self):
        # 组1: 5,8 → s=2.1213；组2: 7,7 → s=0；rms = sqrt((4.5+0)/2)
        pours = [pour(temp=90, rating=5.0), pour(temp=90, rating=8.0),
                 pour(temp=96, rating=7.0), pour(temp=96, rating=7.0)]
        _, sigma = rb.reproducibility(pours)
        self.assertAlmostEqual(sigma, math.sqrt(4.5 / 2))

    def test_identical_ratings_give_zero_sigma(self):
        pours = [pour(rating=7.0), pour(rating=7.0), pour(rating=7.0)]
        _, sigma = rb.reproducibility(pours)
        self.assertEqual(sigma, 0.0)

    def test_singletons_do_not_pollute(self):
        pours = [pour(rating=7.0), pour(rating=7.5),
                 pour(temp=91, rating=9.0)]  # 第 3 杯是单独配方
        groups, sigma = rb.reproducibility(pours)
        self.assertEqual(len(groups), 1)
        self.assertAlmostEqual(sigma, 0.5 / math.sqrt(2))


class TestDomainSelection(unittest.TestCase):
    def test_dominant_bean(self):
        pours = [pour(bean="Ethiopia")] * 3 + [pour(bean="Kenya")] * 1
        self.assertEqual(rb.dominant_bean(pours), "Ethiopia")

    def test_domain_filters_by_bean(self):
        pours = [pour(bean="Ethiopia")] * 3 + [pour(bean="Kenya")] * 1
        chosen, domain = rb.select_domain(pours)
        self.assertEqual(chosen, "Ethiopia")
        self.assertEqual(len(domain), 3)

    def test_explicit_bean_override(self):
        pours = [pour(bean="Ethiopia")] * 3 + [pour(bean="Kenya")] * 1
        chosen, domain = rb.select_domain(pours, bean="Kenya")
        self.assertEqual(chosen, "Kenya")
        self.assertEqual(len(domain), 1)


class TestKnobRanking(unittest.TestCase):
    def test_embedded_effect_ranked_first(self):
        ranking = rb.knob_ranking(temp_effect_pours())
        self.assertEqual(ranking[0]["attr"], "temp_c")
        self.assertGreater(ranking[0]["r"], 0.8)

    def test_unchanged_knobs_lands_last_with_none(self):
        ranking = rb.knob_ranking(temp_effect_pours())
        # 只有水温动过：其余旋钮全部 r=None 垫底
        self.assertEqual(ranking[0]["attr"], "temp_c")
        self.assertIsNotNone(ranking[0]["r"])
        none_attrs = {s["attr"] for s in ranking if s["r"] is None}
        self.assertEqual(none_attrs, {"dose_g", "water_g", "grind", "ratio"})
        self.assertTrue(all(s["r"] is None for s in ranking[1:]))

    def test_levels_collected(self):
        ranking = {s["attr"]: s for s in rb.knob_ranking(temp_effect_pours())}
        self.assertEqual(ranking["temp_c"]["levels"], [90.0, 93.0, 96.0])

    def test_negative_effect_keeps_sign(self):
        pours = []
        for grind, base in [(4.0, 8.0), (8.0, 6.0)]:
            pours.append(pour(grind=grind, rating=base))
            pours.append(pour(grind=grind, rating=base + 0.2))
        ranking = {s["attr"]: s for s in rb.knob_ranking(pours)}
        self.assertLess(ranking["grind"]["r"], 0)


class TestGroupMeans(unittest.TestCase):
    def test_grouping_counts_and_means(self):
        pours = temp_effect_pours()
        rows = rb.group_means(pours, "temp_c")
        self.assertEqual([r[0] for r in rows], [90.0, 93.0, 96.0])
        by_value = {v: (m, n) for v, m, n in rows}
        self.assertAlmostEqual(by_value[90.0][0], 6.1)
        self.assertEqual(by_value[90.0][1], 2)
        self.assertEqual(by_value[96.0][1], 2)

    def test_sorted_by_value(self):
        rows = rb.group_means(temp_effect_pours(), "temp_c")
        values = [r[0] for r in rows]
        self.assertEqual(values, sorted(values))


class TestBestFingerprint(unittest.TestCase):
    def test_highest_mean_wins(self):
        pours = ([pour(temp=90, rating=5.0)] * 2
                 + [pour(temp=96, rating=8.0)] * 2)
        fp, cups = rb.best_fingerprint(pours)
        self.assertEqual(fp[3], 96.0)
        self.assertEqual(len(cups), 2)

    def test_tie_broken_by_cup_count(self):
        pours = ([pour(temp=90, rating=8.0)] * 3
                 + [pour(temp=96, rating=8.0)] * 2)
        fp, cups = rb.best_fingerprint(pours)
        self.assertEqual(fp[3], 90.0)
        self.assertEqual(len(cups), 3)


class TestBestPour(unittest.TestCase):
    def test_highest_rating_then_latest_date(self):
        pours = [pour(date="2026-08-01", rating=8.0),
                 pour(date="2026-08-05", rating=8.0),
                 pour(date="2026-08-03", rating=7.0)]
        self.assertEqual(rb.best_pour(pours).date, "2026-08-05")


if __name__ == "__main__":
    unittest.main()
