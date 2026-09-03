#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance suite for wilting-point.

Every README acceptance criterion is pinned here. The numeric fixtures are
hand-checkable: che's ten-plant shelf as of 2026-09-02 (2 WILTED ·
3 PARCHED · 3 DUE · 2 OK, cadence 6d, 9 misses on 4 plants, the orchid
running 3d-3d gaps against a 3.5d half-line) and tang's five-plant control
(all OK, cadence 7d, zero misses — with the rot lamp still flagging the
two 21-day plants).
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # wilting-point/
EXAMPLES = os.path.join(ROOT, "examples")

sys.path.insert(0, ROOT)
import wilting_point as wp  # noqa: E402


def run_cli(*argv):
    """Run main() in-process; return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = wp.main(list(argv))
    except SystemExit as exc:
        code = exc.code
        if code is None:
            code = 0
    return code, out.getvalue(), err.getvalue()


def write_shelf(ledger_rows, log_rows, directory=None):
    """Write a ledger+log pair; return (ledger_path, log_path).
    ledger_rows: (name, species, dry_min, dry_max, acquired[, notes])
    log_rows:    (date, plant[, note])"""
    if directory is None:
        directory = tempfile.mkdtemp()
    lpath = os.path.join(directory, "ledger.tsv")
    with open(lpath, "w", encoding="utf-8") as fh:
        fh.write("plant\tspecies\tdry_min\tdry_max\tacquired\tnotes\n")
        for r in ledger_rows:
            fh.write("\t".join(r) + "\n")
    gpath = os.path.join(directory, "log.tsv")
    with open(gpath, "w", encoding="utf-8") as fh:
        fh.write("date\tplant\tnote\n")
        for r in log_rows:
            fh.write("\t".join(r) + "\n")
    return lpath, gpath


CHE_LEDGER = os.path.join(EXAMPLES, "che-ledger.tsv")
CHE_LOG = os.path.join(EXAMPLES, "che-log.tsv")
TANG_LEDGER = os.path.join(EXAMPLES, "tang-ledger.tsv")
TANG_LOG = os.path.join(EXAMPLES, "tang-log.tsv")


# ---------------------------------------------------------------------------
# built-in species table
# ---------------------------------------------------------------------------

class SpeciesTableTests(unittest.TestCase):
    def test_sixteen_rows_unique_keys(self):
        keys = [row[0] for row in wp.SPECIES]
        self.assertEqual(len(keys), 16)
        self.assertEqual(len(set(keys)), 16)

    def test_lines_are_sane(self):
        for key, zh, mn, mx, note in wp.SPECIES:
            self.assertGreater(mn, 0, key)
            self.assertLess(mn, mx, key)
            self.assertTrue(zh)
            self.assertTrue(note)
        self.assertIn("boston-fern", wp.SPECIES_BY_KEY)
        self.assertIn("snake-plant", wp.SPECIES_BY_KEY)

    def test_species_command_lists_table(self):
        code, out, _ = run_cli("species")
        self.assertEqual(code, wp.EXIT_OK)
        for row in wp.SPECIES:
            self.assertIn(row[0], out)
            self.assertIn(row[1], out)


# ---------------------------------------------------------------------------
# ledger parsing
# ---------------------------------------------------------------------------

class LedgerParseTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_header_and_comments_are_optional(self):
        lpath = os.path.join(self.dir, "l.tsv")
        with open(lpath, "w", encoding="utf-8") as fh:
            fh.write("# a comment\nFern\tboston-fern\t4\t8\t2025-03-15\thi\n")
        gpath = os.path.join(self.dir, "g.tsv")
        with open(gpath, "w", encoding="utf-8") as fh:
            fh.write("2026-09-01\tFern\n")
        shelf = wp.load_shelf(lpath, gpath)
        self.assertEqual([p.name for p in shelf.plants], ["Fern"])

    def test_notes_column_is_optional(self):
        lpath, gpath = write_shelf(
            [("Fern", "boston-fern", "4", "8", "2025-03-15")],
            [("2026-09-01", "Fern")], self.dir)
        shelf = wp.load_shelf(lpath, gpath)
        self.assertEqual(shelf.plants[0].notes, "")

    def test_bad_dry_line_carries_line_number(self):
        lpath = os.path.join(self.dir, "l.tsv")
        with open(lpath, "w", encoding="utf-8") as fh:
            fh.write("plant\tspecies\tdry_min\tdry_max\tacquired\n")
            fh.write("Fern\tboston-fern\tfour\t8\t2025-03-15\n")
        with self.assertRaisesRegex(wp.LedgerError, "line 2"):
            wp.read_ledger(lpath)

    def test_safe_line_above_wilting_point_rejected(self):
        lpath = os.path.join(self.dir, "l.tsv")
        with open(lpath, "w", encoding="utf-8") as fh:
            fh.write("plant\tspecies\tdry_min\tdry_max\tacquired\n")
            fh.write("Fern\tboston-fern\t9\t8\t2025-03-15\n")
        with self.assertRaisesRegex(wp.LedgerError, "exceeds"):
            wp.read_ledger(lpath)

    def test_non_positive_dry_line_rejected(self):
        lpath = os.path.join(self.dir, "l.tsv")
        with open(lpath, "w", encoding="utf-8") as fh:
            fh.write("plant\tspecies\tdry_min\tdry_max\tacquired\n")
            fh.write("Fern\tboston-fern\t0\t8\t2025-03-15\n")
        with self.assertRaisesRegex(wp.LedgerError, "positive"):
            wp.read_ledger(lpath)

    def test_duplicate_plant_names_first_line(self):
        lpath = os.path.join(self.dir, "l.tsv")
        with open(lpath, "w", encoding="utf-8") as fh:
            fh.write("plant\tspecies\tdry_min\tdry_max\tacquired\n")
            fh.write("Fern\tboston-fern\t4\t8\t2025-03-15\n")
            fh.write("Fern\tpothos\t7\t15\t2025-03-15\n")
        with self.assertRaisesRegex(wp.LedgerError, "line 3.*duplicate"):
            wp.read_ledger(lpath)

    def test_empty_ledger_rejected(self):
        lpath = os.path.join(self.dir, "l.tsv")
        with open(lpath, "w", encoding="utf-8") as fh:
            fh.write("plant\tspecies\tdry_min\tdry_max\tacquired\n")
        with self.assertRaisesRegex(wp.LedgerError, "no plants"):
            wp.read_ledger(lpath)

    def test_missing_ledger_is_input_error(self):
        code, _, err = run_cli("report",
                               os.path.join(self.dir, "nope.tsv"),
                               os.path.join(self.dir, "nope2.tsv"))
        self.assertEqual(code, wp.EXIT_INPUT)
        self.assertIn("cannot read", err)

    def test_bad_acquired_date_rejected(self):
        lpath = os.path.join(self.dir, "l.tsv")
        with open(lpath, "w", encoding="utf-8") as fh:
            fh.write("plant\tspecies\tdry_min\tdry_max\tacquired\n")
            fh.write("Fern\tboston-fern\t4\t8\t2025-13-99\n")
        with self.assertRaisesRegex(wp.LedgerError, "line 2.*acquired"):
            wp.read_ledger(lpath)


# ---------------------------------------------------------------------------
# log parsing
# ---------------------------------------------------------------------------

class LogParseTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.lpath, _ = write_shelf(
            [("Fern", "boston-fern", "4", "8", "2025-03-15")],
            [], self.dir)

    def write_log(self, text):
        gpath = os.path.join(self.dir, "g.tsv")
        with open(gpath, "w", encoding="utf-8") as fh:
            fh.write(text)
        return gpath

    def test_unknown_plant_names_the_line(self):
        gpath = self.write_log("2026-09-01\tCactus\n")
        with self.assertRaisesRegex(wp.LedgerError, "line 1.*Cactus"):
            wp.read_log(gpath, wp.read_ledger(self.lpath))

    def test_watering_before_acquisition_rejected(self):
        gpath = self.write_log("2025-03-14\tFern\n")
        with self.assertRaisesRegex(wp.LedgerError, "before it was acquired"):
            wp.read_log(gpath, wp.read_ledger(self.lpath))

    def test_duplicate_watering_rejected(self):
        gpath = self.write_log("2026-09-01\tFern\n2026-09-01\tFern\n")
        with self.assertRaisesRegex(wp.LedgerError, "duplicate watering"):
            wp.read_log(gpath, wp.read_ledger(self.lpath))

    def test_bad_date_carries_line_number(self):
        gpath = self.write_log("2026-02-30\tFern\n")
        with self.assertRaisesRegex(wp.LedgerError, "line 1.*bad date"):
            wp.read_log(gpath, wp.read_ledger(self.lpath))

    def test_note_column_is_optional_and_indexed(self):
        gpath = self.write_log("2026-09-01\tFern\tdeep soak\n")
        log = wp.read_log(gpath, wp.read_ledger(self.lpath))
        self.assertEqual(log[0].note, "deep soak")


# ---------------------------------------------------------------------------
# waterline: the four bands and their boundaries
# ---------------------------------------------------------------------------

class WaterlineTests(unittest.TestCase):
    def shelf_for(self, day_offset, season=None, dry_min=10, dry_max=20):
        """One plant, safe 10 / wilt 20, watered 2026-06-01,
        clock moved `day_offset` days past that watering."""
        lpath, gpath = write_shelf(
            [("P", "pothos", str(dry_min), str(dry_max), "2026-01-01")],
            [("2026-06-01", "P")])
        as_of = wp.as_of_date(wp.load_shelf(lpath, gpath), None)
        from datetime import date as d, timedelta
        today = (d.fromisoformat("2026-06-01")
                 + timedelta(days=day_offset)).isoformat()
        shelf = wp.load_shelf(lpath, gpath)
        as_of = wp.as_of_date(shelf, today)
        readings, _ = wp.read_shelf_state(shelf, as_of, season)
        return readings[0]

    def test_below_seventy_percent_is_ok(self):
        self.assertEqual(self.shelf_for(6).band, wp.OK)

    def test_seventy_percent_opens_the_window(self):
        self.assertEqual(self.shelf_for(7).band, wp.DUE)

    def test_nine_days_is_still_due(self):
        self.assertEqual(self.shelf_for(9).band, wp.DUE)

    def test_safe_line_exactly_is_parched(self):
        self.assertEqual(self.shelf_for(10).band, wp.PARCHED)

    def test_one_before_wilt_is_parched(self):
        self.assertEqual(self.shelf_for(19).band, wp.PARCHED)

    def test_wilting_point_exactly_is_wilted(self):
        self.assertEqual(self.shelf_for(20).band, wp.WILTED)

    def test_days_dry_is_pinned(self):
        self.assertEqual(self.shelf_for(15).days_dry, 15)
        self.assertEqual(self.shelf_for(15).last_watered, "2026-06-01")

    def test_summer_shrinks_both_lines(self):
        r = self.shelf_for(4, season="summer")
        self.assertAlmostEqual(r.safe, 7.0)          # 10 × 0.7
        self.assertAlmostEqual(r.wilt, 14.0)         # 20 × 0.7
        self.assertEqual(r.band, wp.OK)              # 4 < 4.9 window
        self.assertEqual(self.shelf_for(5, season="summer").band, wp.DUE)   # 5 ≥ 4.9
        self.assertEqual(self.shelf_for(7, season="summer").band, wp.PARCHED)  # 7 ≥ 7.0
        self.assertEqual(self.shelf_for(14, season="summer").band, wp.WILTED)  # 14 ≥ 14.0

    def test_summer_wilt_boundary(self):
        r = self.shelf_for(14, season="summer")
        self.assertEqual(r.band, wp.WILTED)          # 14 ≥ 14.0

    def test_winter_stretches_both_lines(self):
        r = self.shelf_for(10, season="winter")
        self.assertAlmostEqual(r.safe, 13.0)         # 10 × 1.3
        self.assertEqual(r.band, wp.DUE)             # 10 < 13.0 and ≥ 9.1
        self.assertEqual(self.shelf_for(9, season="winter").band, wp.OK)

    def test_never_watered_falls_back_to_acquisition(self):
        lpath, gpath = write_shelf(
            [("P", "pothos", "10", "20", "2026-01-01")], [])
        shelf = wp.load_shelf(lpath, gpath)
        readings, _ = wp.read_shelf_state(shelf, wp.as_of_date(shelf, None), None)
        r = readings[0]
        self.assertTrue(r.never_watered)
        self.assertIsNone(r.last_watered)
        self.assertEqual(r.days_dry, 0)              # as_of == acquired
        self.assertEqual(r.band, wp.OK)

    def test_as_of_is_max_of_ledger_and_log(self):
        lpath, gpath = write_shelf(
            [("P", "pothos", "10", "20", "2026-08-01")],
            [("2026-08-01", "P")])
        shelf = wp.load_shelf(lpath, gpath)
        self.assertEqual(wp.as_of_date(shelf, None).isoformat(), "2026-08-01")

    def test_today_before_a_log_date_is_rejected(self):
        code, _, err = run_cli("report", CHE_LEDGER, CHE_LOG,
                               "--today", "2026-08-01")
        self.assertEqual(code, wp.EXIT_INPUT)
        self.assertIn("after as-of", err)


# ---------------------------------------------------------------------------
# cadence: your watering personality
# ---------------------------------------------------------------------------

class CadenceTests(unittest.TestCase):
    def test_median_odd_and_even(self):
        self.assertEqual(wp.median([5.0]), 5.0)
        self.assertEqual(wp.median([4.0, 6.0]), 5.0)
        self.assertEqual(wp.median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_cadence_pools_every_plants_gaps(self):
        lpath, gpath = write_shelf(
            [("A", "ivy", "3", "6", "2026-01-01"),
             ("B", "aloe", "10", "20", "2026-01-01")],
            [("2026-06-01", "A"), ("2026-06-05", "A"), ("2026-06-09", "A"),
             ("2026-06-01", "B"), ("2026-06-15", "B")])
        shelf = wp.load_shelf(lpath, gpath)
        cadence, gaps = wp.profile(shelf)
        self.assertEqual(gaps, [4.0, 4.0, 14.0])
        self.assertEqual(cadence, 4.0)

    def test_single_watering_per_plant_yields_no_cadence(self):
        lpath, gpath = write_shelf(
            [("A", "ivy", "3", "6", "2026-01-01")],
            [("2026-06-01", "A")])
        shelf = wp.load_shelf(lpath, gpath)
        cadence, gaps = wp.profile(shelf)
        self.assertIsNone(cadence)
        self.assertEqual(gaps, [])

    def test_che_cadence_is_six_days(self):
        shelf = wp.load_shelf(CHE_LEDGER, CHE_LOG)
        cadence, gaps = wp.profile(shelf)
        self.assertEqual(len(gaps), 178)
        self.assertEqual(cadence, 6.0)

    def test_mismatch_counts_strictly_tighter_lines(self):
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG)
        self.assertIn("  mismatch        : 4 of 10 plants", out)
        code, out, _ = run_cli("report", TANG_LEDGER, TANG_LOG)
        self.assertIn("  mismatch        : 0 of 5 plants", out)


# ---------------------------------------------------------------------------
# neglect ledger: misses, blacklist, green teammates
# ---------------------------------------------------------------------------

class NeglectTests(unittest.TestCase):
    def che(self):
        return wp.load_shelf(CHE_LEDGER, CHE_LOG)

    def test_misses_count_only_gaps_strictly_past_the_line(self):
        readings, _ = wp.read_shelf_state(self.che(),
                                          wp.as_of_date(self.che(), None), None)
        by_name = {r.plant.name: r for r in readings}
        self.assertEqual(by_name["Fern"].misses, 4)      # 11, 8, 8, 13 > 4
        self.assertEqual(by_name["NervePlant"].misses, 2)  # 5, 7 > 4
        self.assertEqual(by_name["Calathea"].misses, 2)  # 6, 6 > 5
        self.assertEqual(by_name["Ivy"].misses, 1)       # 9 > 5
        self.assertEqual(by_name["Jade"].misses, 0)      # 14 == 14 is not a miss
        self.assertEqual(by_name["Orchid"].misses, 0)    # loved, never starved

    def test_gap_equal_to_safe_line_is_not_a_miss(self):
        lpath, gpath = write_shelf(
            [("P", "pothos", "14", "30", "2026-01-01")],
            [("2026-06-01", "P"), ("2026-06-15", "P")])
        shelf = wp.load_shelf(lpath, gpath)
        readings, _ = wp.read_shelf_state(shelf, wp.as_of_date(shelf, None), None)
        self.assertEqual(readings[0].misses, 0)
        self.assertEqual(readings[0].worst_overshoot, 0.0)

    def test_worst_overshoot_is_pinned(self):
        readings, _ = wp.read_shelf_state(self.che(),
                                          wp.as_of_date(self.che(), None), None)
        by_name = {r.plant.name: r for r in readings}
        self.assertEqual(by_name["Fern"].worst_overshoot, 9.0)  # 13 - 4

    def test_blacklist_needs_two_misses_and_aggregates_species(self):
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG)
        self.assertIn("  blacklist       : 3 species (≥2 misses) — stop rebuying: "
                      "boston-fern, calathea, nerve-plant", out)
        # Ivy missed once: no species hits the line from a single miss
        self.assertNotIn("ivy:", out)

    def test_green_teammates_exclude_damage_zone(self):
        # Jade: zero misses but PARCHED -> not a teammate
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG)
        self.assertIn("  green teammates : 4 — Aloe, Haworthia, Monstera, Pothos", out)

    def test_tang_is_a_clean_record(self):
        code, out, _ = run_cli("report", TANG_LEDGER, TANG_LOG)
        self.assertIn("  neglect ledger  : 0 misses on 0 plant(s) — a clean record", out)
        self.assertNotIn("  blacklist", out)
        self.assertIn("  green teammates : 5 — Aloe, Jade, Rubber, SnakePlant, ZZPlant", out)


# ---------------------------------------------------------------------------
# overwater: the rot lamp
# ---------------------------------------------------------------------------

class OverwaterTests(unittest.TestCase):
    def gaps_shelf(self, g1, g2, dry_min=4):
        lpath, gpath = write_shelf(
            [("P", "orchid", str(dry_min), "14", "2026-01-01")],
            [("2026-06-01", "P"), ("2026-06-%02d" % (1 + g1), "P"),
             ("2026-06-%02d" % (1 + g1 + g2), "P")])
        shelf = wp.load_shelf(lpath, gpath)
        readings, _ = wp.read_shelf_state(shelf, wp.as_of_date(shelf, None), None)
        return readings[0]

    def test_two_short_gaps_light_the_lamp(self):
        r = self.gaps_shelf(3, 3, dry_min=7)         # 3, 3 < 3.5
        self.assertTrue(r.overwater)
        self.assertEqual(r.overwater_gaps, (3.0, 3.0))

    def test_gaps_above_the_half_line_stay_dark(self):
        r = self.gaps_shelf(3, 3, dry_min=4)         # 3, 3 not < 2.0
        self.assertFalse(r.overwater)

    def test_two_very_short_gaps_light_the_lamp(self):
        r = self.gaps_shelf(1, 1, dry_min=4)         # 1, 1 < 2.0
        self.assertTrue(r.overwater)
        self.assertEqual(r.overwater_gaps, (1.0, 1.0))

    def test_half_line_is_strict(self):
        r = self.gaps_shelf(2, 2, dry_min=4)         # 2 == half: not below
        self.assertFalse(r.overwater)

    def test_one_short_gap_is_not_enough(self):
        lpath, gpath = write_shelf(
            [("P", "orchid", "4", "14", "2026-01-01")],
            [("2026-06-01", "P"), ("2026-06-02", "P"), ("2026-06-09", "P")])
        shelf = wp.load_shelf(lpath, gpath)
        readings, _ = wp.read_shelf_state(shelf, wp.as_of_date(shelf, None), None)
        self.assertFalse(readings[0].overwater)

    def test_che_orchid_is_flagged_with_its_gaps(self):
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG)
        self.assertIn("  overwater       : 1 flagged — Orchid", out)
        self.assertIn("OVERWATER(rot lamp: last gaps 3d,3d < 3.5d half-line)", out)

    def test_tang_uniform_schedule_taxes_the_tolerant_end(self):
        code, out, _ = run_cli("report", TANG_LEDGER, TANG_LOG)
        self.assertIn("  overwater       : 2 flagged — SnakePlant, ZZPlant", out)


# ---------------------------------------------------------------------------
# report rendering
# ---------------------------------------------------------------------------

class ReportTextTests(unittest.TestCase):
    def test_che_header_and_bands(self):
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG)
        self.assertEqual(code, wp.EXIT_OK)
        self.assertIn("wilting-point · 凋萎点 — as of 2026-09-02 · "
                      "ledger 10 plants · log 188 events", out)
        self.assertIn("  bands           : 2 OK · 3 DUE · 3 PARCHED · 2 WILTED", out)
        self.assertIn("  cadence         : 6d median gap between your waterings", out)
        self.assertIn("  neglect ledger  : 9 misses on 4 plant(s)", out)

    def test_che_wilted_rows_sorted_by_overshoot(self):
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG)
        fern = out.index("  Fern ")
        nerve = out.index("  NervePlant ")
        self.assertLess(fern, nerve)                 # most-past first

    def test_che_verdict_wilted_branch(self):
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG)
        self.assertIn("verdict: 2 plant(s) crossed the wilting point on your watch — "
                      "triage the PARCHED ones today; the wilted are a lesson, not a guilt trip", out)

    def test_tang_verdict_all_green_branch(self):
        code, out, _ = run_cli("report", TANG_LEDGER, TANG_LOG)
        self.assertIn("wilting-point · 凋萎点 — as of 2026-08-30 · "
                      "ledger 5 plants · log 45 events", out)
        self.assertIn("  bands           : 5 OK · 0 DUE · 0 PARCHED · 0 WILTED", out)
        self.assertIn("verdict: all green — your cadence and your shelf agree with each other", out)

    def test_due_band_rows_show_countdowns(self):
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG)
        self.assertIn("dry 15d ago · past wilt line by 7d", out)
        self.assertIn("wilt line in 1d (15d past safe)", out)
        self.assertIn("window opens in 2.9d", out)

    def test_never_watered_flag_renders(self):
        lpath, gpath = write_shelf(
            [("P", "pothos", "10", "20", "2026-01-01")], [])
        code, out, _ = run_cli("report", lpath, gpath)
        self.assertIn("NEVER-WATERED since purchase", out)
        self.assertIn("cadence         : n/a — no watering gaps on record yet", out)

    def test_season_note_in_header(self):
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG, "--season", "summer")
        self.assertIn("season summer (lines ×0.7)", out)


# ---------------------------------------------------------------------------
# json output
# ---------------------------------------------------------------------------

class JsonTests(unittest.TestCase):
    def test_json_parses_and_is_sorted(self):
        code, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG, "--format", "json")
        self.assertEqual(code, wp.EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["as_of"], "2026-09-02")
        self.assertEqual(payload["cadence"], 6.0)
        self.assertEqual(len(payload["plants"]), 10)

    def test_json_plant_fields_pinned(self):
        _, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG, "--format", "json")
        payload = json.loads(out)
        by_name = {p["name"]: p for p in payload["plants"]}
        fern = by_name["Fern"]
        self.assertEqual(fern["band"], "WILTED")
        self.assertEqual(fern["days_dry"], 15)
        self.assertEqual(fern["misses"], 4)
        self.assertEqual(fern["worst_overshoot"], 9.0)
        self.assertFalse(fern["overwater"])
        orchid = by_name["Orchid"]
        self.assertTrue(orchid["overwater"])
        self.assertEqual(orchid["band"], "PARCHED")
        nerve = by_name["NervePlant"]
        self.assertEqual(nerve["days_dry"] - nerve["effective"]["wilt"], 0)

    def test_json_blacklist_is_sorted(self):
        _, out, _ = run_cli("report", CHE_LEDGER, CHE_LOG, "--format", "json")
        self.assertEqual(json.loads(out)["blacklist"],
                         ["boston-fern", "calathea", "nerve-plant"])


# ---------------------------------------------------------------------------
# due: the countdown order
# ---------------------------------------------------------------------------

class DueTests(unittest.TestCase):
    def test_order_is_pinned(self):
        code, out, _ = run_cli("due", CHE_LEDGER, CHE_LOG)
        self.assertEqual(code, wp.EXIT_OK)
        expected = ["Fern", "NervePlant", "Jade", "Calathea", "Orchid",
                    "Ivy", "Pothos", "Aloe", "Monstera", "Haworthia"]
        rows = [ln for ln in out.splitlines() if re.match(r"\s*\d+\.\s", ln)]
        listed = [ln.split()[1] for ln in rows]
        self.assertEqual(listed, expected)

    def test_rows_carry_their_tail(self):
        _, out, _ = run_cli("due", CHE_LEDGER, CHE_LOG)
        self.assertIn("1. Fern         WILTED   past wilt line by 7d", out)
        self.assertIn("3. Jade         PARCHED  wilt line in 1d", out)
        self.assertIn("10. Haworthia    OK       window opens in 7d", out)


# ---------------------------------------------------------------------------
# simulate: the trip
# ---------------------------------------------------------------------------

class SimulateTests(unittest.TestCase):
    def test_che_trip_seven_pinned(self):
        code, out, _ = run_cli("simulate", CHE_LEDGER, CHE_LOG, "trip", "7")
        self.assertEqual(code, wp.EXIT_OK)
        self.assertIn("wilting-point · simulate trip 7 — away 2026-09-02 → back 2026-09-09", out)
        self.assertIn("  nobody waters          : 6 of 10 cross a line before you are back", out)
        self.assertIn("    Fern         dies by 2026-08-26  (safe 4d / wilt 8d) already past", out)
        self.assertIn("    Ivy          dies by 2026-09-08  (safe 5d / wilt 10d)", out)
        self.assertIn("  water everything and go: 1 of 10 still cross — "
                      "NervePlant (wilt 7d ≤ trip 7d)", out)
        self.assertIn("  verdict: hand NervePlant to a friend before you leave; "
                      "everyone else survives one soak", out)

    def test_trip_zero_leaves_only_the_already_wilted(self):
        _, out, _ = run_cli("simulate", CHE_LEDGER, CHE_LOG, "trip", "0")
        self.assertIn("  nobody waters          : 2 of 10 cross a line before you are back", out)
        self.assertIn("  water everything and go: 0 of 10 — one pre-departure soak covers the whole trip", out)

    def test_long_trip_sinks_everyone_even_soaked(self):
        _, out, _ = run_cli("simulate", CHE_LEDGER, CHE_LOG, "trip", "45")
        self.assertIn("  water everything and go: 10 of 10 still cross", out)
        # soak list is sorted by thirstiest first: NervePlant (7d) leads
        self.assertIn("  verdict: hand NervePlant, Fern,", out)

    def test_tang_trip_is_survivable(self):
        _, out, _ = run_cli("simulate", TANG_LEDGER, TANG_LOG, "trip", "7")
        self.assertIn("  nobody waters          : 0 of 5 cross a line before you are back", out)
        self.assertIn("  verdict: the trip is survivable: water before you leave and forget the guilt", out)

    def test_negative_trip_is_usage(self):
        code, _, _ = run_cli("simulate", CHE_LEDGER, CHE_LOG, "trip", "-1")
        self.assertEqual(code, wp.EXIT_USAGE)


# ---------------------------------------------------------------------------
# advice: the purchase gate
# ---------------------------------------------------------------------------

class AdviceTests(unittest.TestCase):
    def test_incompatible_exits_gate(self):
        code, out, _ = run_cli("advice", CHE_LEDGER, CHE_LOG, "boston-fern")
        self.assertEqual(code, wp.EXIT_GATE)
        self.assertIn("verdict      : INCOMPATIBLE — its safe line (4d) is shorter "
                      "than your natural cadence (6d): your ordinary rhythm is already its drought", out)
        self.assertIn("  evidence     : your Fern already missed its line 4 time(s) in your own log", out)

    def test_risky_band_between_cadence_and_margin(self):
        # orchid: safe 7d, cadence 6d -> 6 ≤ 7 < 9
        code, out, _ = run_cli("advice", CHE_LEDGER, CHE_LOG, "orchid")
        self.assertEqual(code, wp.EXIT_OK)
        self.assertIn("RISKY — one late watering puts it in the damage zone", out)
        self.assertNotIn("evidence", out)            # zero misses: no evidence line

    def test_compatible_has_margin(self):
        code, out, _ = run_cli("advice", CHE_LEDGER, CHE_LOG, "snake-plant")
        self.assertEqual(code, wp.EXIT_OK)
        self.assertIn("verdict      : COMPATIBLE — it tolerates your cadence with room "
                      "to spare (safe 21d ≥ 1.5 × 6d)", out)

    def test_unknown_species_is_usage(self):
        code, _, err = run_cli("advice", CHE_LEDGER, CHE_LOG, "fern")
        self.assertEqual(code, wp.EXIT_USAGE)
        self.assertIn("unknown species 'fern'", err)
        self.assertIn("boston-fern", err)

    def test_cold_start_defers(self):
        lpath, gpath = write_shelf(
            [("P", "pothos", "7", "15", "2026-01-01")], [])
        code, out, _ = run_cli("advice", lpath, gpath, "boston-fern")
        self.assertEqual(code, wp.EXIT_OK)
        self.assertIn("your cadence : n/a — water something for a month first", out)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

class ValidateTests(unittest.TestCase):
    def test_che_validate_pinned(self):
        code, out, _ = run_cli("validate", CHE_LEDGER, CHE_LOG)
        self.assertEqual(code, wp.EXIT_OK)
        self.assertIn("  plants        : 10", out)
        self.assertIn("  log events    : 188 (yielding 178 gaps)", out)
        self.assertIn("  as_of         : 2026-09-02 (max of ledger/log; --today to override)", out)
        self.assertIn("  never watered : none", out)

    def test_never_and_single_listed(self):
        lpath, gpath = write_shelf(
            [("A", "ivy", "5", "10", "2026-01-01"),
             ("B", "aloe", "14", "30", "2026-01-01")],
            [("2026-06-01", "B")])
        _, out, _ = run_cli("validate", lpath, gpath)
        self.assertIn("  never watered : A", out)
        self.assertIn("  single record : B", out)


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------

class GateTests(unittest.TestCase):
    def test_report_gate_trips_at_exact_count(self):
        code, _, _ = run_cli("report", CHE_LEDGER, CHE_LOG, "--fail-wilted", "2")
        self.assertEqual(code, wp.EXIT_GATE)
        code, _, _ = run_cli("report", CHE_LEDGER, CHE_LOG, "--fail-wilted", "3")
        self.assertEqual(code, wp.EXIT_OK)

    def test_due_gate(self):
        code, _, _ = run_cli("due", CHE_LEDGER, CHE_LOG, "--fail-wilted", "1")
        self.assertEqual(code, wp.EXIT_GATE)
        code, _, _ = run_cli("due", TANG_LEDGER, TANG_LOG, "--fail-wilted", "1")
        self.assertEqual(code, wp.EXIT_OK)


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------

class CliTests(unittest.TestCase):
    def test_no_subcommand_prints_help_exits_usage(self):
        code, out, _ = run_cli()
        self.assertEqual(code, wp.EXIT_USAGE)
        self.assertIn("usage:", out)

    def test_bad_today_is_input_error(self):
        code, _, err = run_cli("report", CHE_LEDGER, CHE_LOG,
                               "--today", "2026-13-01")
        self.assertEqual(code, wp.EXIT_INPUT)
        self.assertIn("bad --today", err)

    def test_bad_season_is_argparse_exit(self):
        code, _, _ = run_cli("report", CHE_LEDGER, CHE_LOG,
                             "--season", "monsoon")
        self.assertEqual(code, 2)

    def test_bad_trip_word_is_argparse_exit(self):
        code, _, _ = run_cli("simulate", CHE_LEDGER, CHE_LOG, "cruise", "7")
        self.assertEqual(code, 2)

    def test_non_integer_trip_is_argparse_exit(self):
        code, _, _ = run_cli("simulate", CHE_LEDGER, CHE_LOG, "trip", "week")
        self.assertEqual(code, 2)

    def test_missing_files_are_input_errors(self):
        code, _, _ = run_cli("due", "/nonexistent.tsv", "/nonexistent2.tsv")
        self.assertEqual(code, wp.EXIT_INPUT)


# ---------------------------------------------------------------------------
# dogfood: the committed examples must reproduce byte for byte
# ---------------------------------------------------------------------------

class ExamplesSyncTests(unittest.TestCase):
    def test_build_examples_check(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(EXAMPLES, "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("all 7 example files in sync", proc.stdout)


class DogfoodTests(unittest.TestCase):
    def test_pinned_samples_match_fresh_runs(self):
        pairs = {
            "sample-report-che.txt": ["report", CHE_LEDGER, CHE_LOG],
            "sample-due-che.txt": ["due", CHE_LEDGER, CHE_LOG],
            "sample-simulate-che.txt": ["simulate", CHE_LEDGER, CHE_LOG, "trip", "7"],
            "sample-advice-fern.txt": ["advice", CHE_LEDGER, CHE_LOG, "boston-fern"],
            "sample-advice-snake.txt": ["advice", CHE_LEDGER, CHE_LOG, "snake-plant"],
            "sample-report-tang.txt": ["report", TANG_LEDGER, TANG_LOG],
            "sample-simulate-tang.txt": ["simulate", TANG_LEDGER, TANG_LOG, "trip", "7"],
        }
        for name, argv in pairs.items():
            with open(os.path.join(EXAMPLES, name), "r", encoding="utf-8") as fh:
                pinned = fh.read()
            _, out, _ = run_cli(*argv)
            self.assertEqual(out, pinned, name)

    def test_json_identity_band_counts_match_text(self):
        _, text, _ = run_cli("report", CHE_LEDGER, CHE_LOG)
        _, js, _ = run_cli("report", CHE_LEDGER, CHE_LOG, "--format", "json")
        payload = json.loads(js)
        bands = [p["band"] for p in payload["plants"]]
        expected = "  bands           : %d OK · %d DUE · %d PARCHED · %d WILTED" % (
            bands.count("OK"), bands.count("DUE"),
            bands.count("PARCHED"), bands.count("WILTED"))
        self.assertIn(expected, text)

    def test_simulate_at_risk_consistent_with_wilt_lines(self):
        _, js, _ = run_cli("report", CHE_LEDGER, CHE_LOG, "--format", "json")
        payload = json.loads(js)
        _, sim, _ = run_cli("simulate", CHE_LEDGER, CHE_LOG, "trip", "7")
        # every plant whose wilt date is on/before 2026-09-09 must be listed
        from datetime import date as d
        listed = 0
        for p in payload["plants"]:
            wilt_date = d.fromisoformat(p["last_watered"]) + \
                __import__("datetime").timedelta(days=p["effective"]["wilt"])
            if wilt_date <= d.fromisoformat("2026-09-09"):
                listed += 1
                self.assertIn(p["name"], sim)
        self.assertIn("%d of 10 cross a line" % listed, sim)


if __name__ == "__main__":
    unittest.main()
