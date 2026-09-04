#!/usr/bin/env python3
"""Acceptance tests for life-tag (生命价签) — profile config & validation."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import life_tag as lt  # noqa: E402


class TestBlankProfile(unittest.TestCase):
    def test_defaults(self):
        p = lt.blank_profile()
        self.assertEqual(p["workdays"], 21.0)
        self.assertEqual(p["daily_hours"], 8.0)
        self.assertEqual(p["recovery_ratio"], lt.DEFAULT_RECOVERY)
        self.assertEqual(p["pulse_line"], lt.DEFAULT_PULSE)
        self.assertEqual(p["currency"], "¥")
        self.assertEqual(p["commute_min"], 0.0)
        self.assertEqual(p["work_costs_extra"], 0.0)

    def test_required_fields_start_none(self):
        p = lt.blank_profile()
        self.assertIsNone(p["gross_monthly"])
        self.assertIsNone(p["tax_rate"])


class TestValidate(unittest.TestCase):
    def test_minimal_valid(self):
        p = lt.validate_profile({"gross_monthly": 10000, "tax_rate": 0.1})
        self.assertEqual(p["gross_monthly"], 10000)
        self.assertEqual(p["workdays"], 21.0)

    def test_missing_gross(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"tax_rate": 0.1})

    def test_missing_tax(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 10000})

    def test_zero_gross(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 0, "tax_rate": 0.1})

    def test_negative_gross(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": -1, "tax_rate": 0.1})

    def test_tax_above_one(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": 1.0})

    def test_tax_negative(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": -0.05})

    def test_tax_boundaries_one_allowed_no(self):
        # 税率恰为 0 合法（免税），恰为 1 不合法（白干）
        p = lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.0})
        self.assertEqual(p["tax_rate"], 0.0)

    def test_zero_workdays(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "workdays": 0})

    def test_zero_daily_hours(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "daily_hours": 0})

    def test_recovery_above_one_rejected(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "recovery_ratio": 1.2})

    def test_recovery_one_allowed(self):
        # 睡满一整天缓过来：极端但真实，放行
        p = lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "recovery_ratio": 1.0})
        self.assertEqual(p["recovery_ratio"], 1.0)

    def test_negative_commute_min(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "commute_min": -5})

    def test_commute_over_480_rejected(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "commute_min": 481})

    def test_commute_480_allowed(self):
        p = lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "commute_min": 480})
        self.assertEqual(p["commute_min"], 480)

    def test_negative_costs(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "work_costs_extra": -1})
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "commute_cost": -1})

    def test_empty_currency(self):
        with self.assertRaises(lt.ProfileError):
            lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "currency": ""})

    def test_unknown_fields_ignored(self):
        p = lt.validate_profile({"gross_monthly": 100, "tax_rate": 0.1,
                                 "nickname": "metro"})
        self.assertNotIn("nickname", p)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "sub"))
        self.path = os.path.join(self.tmp, "sub", "profile.json")

    def test_save_creates_parent_dirs(self):
        lt.save_profile({"gross_monthly": 12000, "tax_rate": 0.1}, self.path)
        self.assertTrue(os.path.exists(self.path))

    def test_roundtrip(self):
        lt.save_profile({"gross_monthly": 12000, "tax_rate": 0.1,
                         "commute_min": 40}, self.path)
        p = lt.load_profile(self.path)
        self.assertEqual(p["gross_monthly"], 12000)
        self.assertEqual(p["commute_min"], 40)
        self.assertEqual(p["recovery_ratio"], lt.DEFAULT_RECOVERY)

    def test_saved_file_is_readable_json(self):
        lt.save_profile({"gross_monthly": 12000, "tax_rate": 0.1}, self.path)
        with open(self.path, encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertEqual(raw["gross_monthly"], 12000)

    def test_load_rejects_non_dict(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2, 3]")
        with self.assertRaises(lt.ProfileError):
            lt.load_profile(self.path)

    def test_load_rejects_garbage(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("not json at all")
        with self.assertRaises(Exception):
            lt.load_profile(self.path)

    def test_load_validates(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"gross_monthly": -5, "tax_rate": 0.1}, fh)
        with self.assertRaises(lt.ProfileError):
            lt.load_profile(self.path)

    def test_default_path_under_home(self):
        self.assertTrue(lt.default_profile_path().endswith(
            os.path.join(".life_tag", "profile.json")))


if __name__ == "__main__":
    unittest.main()
