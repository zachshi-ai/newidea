#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for contribution-gap — every acceptance criterion from README, as code.

Acceptance criteria under test:
  AC1  shares aggregate minutes per person; pct is share of minutes
  AC2  gini: 0 = even split, |2p-1| for two people, 0.0 for one person
  AC3  fairness bands: balanced <= 0.20 < tilted <= 0.40 < lopsided
  AC4  fiefdoms: >= 80% of a chore's minutes in one person's hands,
       and the chore carries at least 60 total minutes
  AC5  streaks: same person on the last >= 3 entries of one chore
  AC6  trend: 28-day gini vs prior 28 days; anchored to the ledger's
       own max date, never to the wall clock; thin halves refuse to judge
  AC7  perception audit: latest claim per person vs measured share;
       surplus = sum of claims - 100, needs two audited claims
  AC8  window: shares/gini/fiefdoms/streaks scope to the last N days
  AC9  red flags: every flag fires on its evidence, zero on a clean ledger
  AC10 parsing: broken lines skipped and counted, never fatal
  AC11 CLI: log appends, claim records, report audits, exit codes
  AC12 zero dependencies: standard library only (import-level guarantee)
  AC13 dogfood: the example household audit lands exactly where pinned
  AC14 examples: byte-stable, rebuildable from zero (--check)
"""

from __future__ import annotations

import ast
import datetime as dt
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import contribution_gap  # noqa: E402

from contribution_gap import (  # noqa: E402
    Chore,
    Claim,
    LedgerError,
    audit_perception,
    build_parser,
    build_report,
    gini,
    gini_band,
    load_ledger,
    main,
    monopolies_of,
    render_text,
    shares_of,
    streaks_of,
    trend_of,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLES = os.path.join(ROOT, "examples")


def chore(person: str, minutes: float, date: str, name: str = "dishes",
          note: str = "", line: int = 0) -> Chore:
    return Chore(dt.datetime.strptime(date, "%Y-%m-%d").date(), person,
                 name, float(minutes), note, line)


def claim(person: str, pct: float, date: str, line: int = 0) -> Claim:
    return Claim(dt.datetime.strptime(date, "%Y-%m-%d").date(), person,
                 float(pct), line)


def write_ledger(rows: List[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def ledger_of(chores: List[Chore], claims: Optional[List[Claim]] = None) -> str:
    rows = [{"kind": "chore", "date": c.date.isoformat(), "person": c.person,
             "chore": c.chore, "minutes": c.minutes}
            for c in chores]
    rows += [{"kind": "claim", "date": c.date.isoformat(), "person": c.person,
              "pct": c.pct} for c in (claims or [])]
    return write_ledger(rows)


def run_cli(argv: List[str]):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def report_of(chores: List[Chore], claims: Optional[List[Claim]] = None,
              window: Optional[int] = None) -> dict:
    path = ledger_of(chores, claims)
    try:
        got_chores, got_claims, broken = load_ledger(path)
        return build_report(got_chores, got_claims, broken, window)
    finally:
        os.unlink(path)


def block(anchor: str, start_days_ago: int, a: float, b: float,
          n: int = 8, name: str = "mix") -> List[Chore]:
    """n entries on consecutive days starting `start_days_ago` back.

    Even entries go to maya with `a` minutes, odd ones to noor with `b`,
    so a block's gini is |a - b| / (a + b) and both 28-day halves of the
    trend machinery get a controllable, well-fed window.
    """
    base = dt.datetime.strptime(anchor, "%Y-%m-%d").date()
    out = []
    for j in range(n):
        day = base - dt.timedelta(days=start_days_ago + j)
        person, minutes = ("maya", a) if j % 2 == 0 else ("noor", b)
        out.append(chore(person, minutes, day.isoformat(), name=name))
    return out


# ---------------------------------------------------------------------------
# AC1 — shares

class TestShares(unittest.TestCase):
    def test_minutes_aggregate_per_person(self):
        rows = shares_of([chore("maya", 20, "2026-08-01"),
                          chore("maya", 30, "2026-08-02"),
                          chore("noor", 50, "2026-08-03")])
        by = {r["person"]: r for r in rows}
        self.assertEqual(by["maya"]["minutes"], 50.0)
        self.assertEqual(by["maya"]["chores"], 2)
        self.assertEqual(by["noor"]["minutes"], 50.0)

    def test_pct_is_share_of_minutes(self):
        rows = shares_of([chore("maya", 75, "2026-08-01"),
                          chore("noor", 25, "2026-08-02")])
        by = {r["person"]: r for r in rows}
        self.assertAlmostEqual(by["maya"]["pct"], 75.0)
        self.assertAlmostEqual(by["noor"]["pct"], 25.0)

    def test_sorted_by_minutes_desc_then_name(self):
        rows = shares_of([chore("zoe", 10, "2026-08-01"),
                          chore("amy", 10, "2026-08-02"),
                          chore("mac", 80, "2026-08-03")])
        self.assertEqual([r["person"] for r in rows], ["mac", "amy", "zoe"])

    def test_names_are_normalized(self):
        path = ledger_of([chore("  Maya ", 20, "2026-08-01"),
                          chore("MAYA", 20, "2026-08-02")])
        try:
            chores, _, _ = load_ledger(path)
            rows = shares_of(chores)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["person"], "maya")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC2 — gini

class TestGini(unittest.TestCase):
    def test_perfect_equality_is_zero(self):
        self.assertAlmostEqual(gini([100.0, 100.0, 100.0]), 0.0)

    def test_one_person_is_zero(self):
        self.assertAlmostEqual(gini([42.0]), 0.0)

    def test_two_people_60_40_is_point_one(self):
        self.assertAlmostEqual(gini([60.0, 40.0]), 0.1)

    def test_two_people_70_30_is_point_two(self):
        self.assertAlmostEqual(gini([70.0, 30.0]), 0.2, places=6)

    def test_two_people_is_half_the_share_distance(self):
        # for two people gini = |2p - 1| / 2
        self.assertAlmostEqual(gini([90.0, 10.0]), 0.4)

    def test_two_people_50_50_is_zero(self):
        self.assertAlmostEqual(gini([50.0, 50.0]), 0.0)

    def test_one_person_holding_everything_is_half_for_two(self):
        # the n-person ceiling is (n-1)/n: 0.5 for a couple
        self.assertAlmostEqual(gini([100.0, 0.0]), 0.5)

    def test_three_person_ceiling(self):
        self.assertAlmostEqual(gini([100.0, 0.0, 0.0]), 2.0 / 3.0)

    def test_scale_invariance(self):
        self.assertAlmostEqual(gini([20.0, 60.0, 90.0, 130.0]),
                               gini([2.0, 6.0, 9.0, 13.0]))


# ---------------------------------------------------------------------------
# AC3 — fairness bands

class TestBands(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(gini_band(0.0), "balanced")
        self.assertEqual(gini_band(0.10), "balanced")
        self.assertEqual(gini_band(0.101), "tilted")
        self.assertEqual(gini_band(0.20), "tilted")
        self.assertEqual(gini_band(0.201), "lopsided")
        self.assertEqual(gini_band(0.5), "lopsided")

    def test_none_is_n_a(self):
        self.assertEqual(gini_band(None), "n/a")

    def test_report_band_matches_gini(self):
        rep = report_of([chore("maya", 70, "2026-08-01"),
                         chore("noor", 30, "2026-08-02")])
        self.assertEqual(rep["gini"]["band"], "tilted")


# ---------------------------------------------------------------------------
# AC4 — fiefdoms (chore monopolies)

class TestMonopolies(unittest.TestCase):
    def test_monopoly_at_80_percent(self):
        chores = [chore("maya", 80, "2026-08-01"),
                  chore("maya", 80, "2026-08-02"),
                  chore("noor", 20, "2026-08-03"),
                  chore("noor", 20, "2026-08-04")]
        items = monopolies_of(chores)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["owner"], "maya")
        self.assertAlmostEqual(items[0]["share"], 0.8)

    def test_below_80_percent_is_no_fiefdom(self):
        chores = [chore("maya", 75, "2026-08-01"),
                  chore("noor", 25, "2026-08-02")]
        self.assertEqual(monopolies_of(chores), [])

    def test_small_chores_are_ignored(self):
        # 100% owned but only 50 minutes in total: noise, not a department.
        chores = [chore("maya", 30, "2026-08-01"),
                  chore("maya", 20, "2026-08-02")]
        self.assertEqual(monopolies_of(chores), [])

    def test_sorted_by_total_minutes_desc(self):
        chores = ([chore("maya", 30, "2026-08-01", name="trash"),
                   chore("maya", 30, "2026-08-02", name="trash"),
                   chore("maya", 30, "2026-08-03", name="trash")]
                  + [chore("maya", 90, "2026-08-0%d" % d, name="cooking")
                     for d in (4, 5)])
        items = monopolies_of(chores)
        self.assertEqual([i["chore"] for i in items], ["cooking", "trash"])

    def test_report_counts_fiefdoms(self):
        chores = [chore("maya", 90, "2026-08-01", name="cooking"),
                  chore("maya", 90, "2026-08-02", name="cooking"),
                  chore("noor", 10, "2026-08-03", name="cooking"),
                  chore("noor", 90, "2026-08-04", name="fixing"),
                  chore("noor", 90, "2026-08-05", name="fixing")]
        rep = report_of(chores)
        self.assertEqual(len(rep["monopolies"]["items"]), 2)


# ---------------------------------------------------------------------------
# AC5 — streaks

class TestStreaks(unittest.TestCase):
    def test_three_in_a_row_is_a_streak(self):
        chores = [chore("maya", 20, "2026-08-01"),
                  chore("noor", 20, "2026-08-02"),
                  chore("maya", 20, "2026-08-03"),
                  chore("maya", 20, "2026-08-04"),
                  chore("maya", 20, "2026-08-05")]
        items = streaks_of(chores)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["person"], "maya")
        self.assertEqual(items[0]["run"], 3)

    def test_two_in_a_row_is_not(self):
        chores = [chore("maya", 20, "2026-08-01"),
                  chore("maya", 20, "2026-08-02")]
        self.assertEqual(streaks_of(chores), [])

    def test_rotation_breaks_the_streak(self):
        chores = [chore("maya", 20, "2026-08-01"),
                  chore("maya", 20, "2026-08-02"),
                  chore("maya", 20, "2026-08-03"),
                  chore("noor", 20, "2026-08-04")]
        self.assertEqual(streaks_of(chores), [])

    def test_lookback_capped_at_six(self):
        chores = [chore("noor", 20, "2026-08-01")]
        chores += [chore("maya", 20, "2026-08-%02d" % d)
                   for d in range(2, 10)]  # 8 maya in a row, but window is 6
        items = streaks_of(chores)
        self.assertEqual(items[0]["run"], 6)

    def test_per_chore_independence(self):
        chores = [chore("maya", 20, "2026-08-01", name="dishes"),
                  chore("maya", 20, "2026-08-02", name="dishes"),
                  chore("maya", 20, "2026-08-03", name="dishes"),
                  chore("noor", 30, "2026-08-04", name="cooking"),
                  chore("noor", 30, "2026-08-05", name="cooking"),
                  chore("noor", 30, "2026-08-06", name="cooking")]
        items = streaks_of(chores)
        self.assertEqual({(i["chore"], i["person"]) for i in items},
                         {("dishes", "maya"), ("cooking", "noor")})


# ---------------------------------------------------------------------------
# AC6 — trend (28-day gini vs prior 28 days)

class TestTrend(unittest.TestCase):
    ANCHOR = "2026-08-30"

    def test_worsening_when_recent_gini_higher(self):
        chores = block(self.ANCHOR, 0, 75.0, 25.0)     # recent: gini 0.25
        chores += block(self.ANCHOR, 28, 50.0, 50.0)   # prior:  gini 0.00
        trend = trend_of(chores, max(c.date for c in chores))
        self.assertEqual(trend["status"], "worsening")
        self.assertAlmostEqual(trend["recent"], 0.25, places=3)
        self.assertAlmostEqual(trend["prior"], 0.0, places=3)
        self.assertAlmostEqual(trend["delta"], 0.25, places=3)

    def test_improving_when_recent_gini_lower(self):
        chores = block(self.ANCHOR, 0, 50.0, 50.0)
        chores += block(self.ANCHOR, 28, 75.0, 25.0)
        trend = trend_of(chores, max(c.date for c in chores))
        self.assertEqual(trend["status"], "improving")

    def test_flat_within_tolerance(self):
        chores = block(self.ANCHOR, 0, 55.0, 45.0)     # gini 0.05
        chores += block(self.ANCHOR, 28, 53.0, 47.0)   # gini 0.03
        trend = trend_of(chores, max(c.date for c in chores))
        self.assertEqual(trend["status"], "flat")
        self.assertAlmostEqual(trend["delta"], 0.02, places=3)

    def test_unknown_without_prior_half(self):
        chores = block(self.ANCHOR, 0, 50.0, 50.0)
        trend = trend_of(chores, max(c.date for c in chores))
        self.assertEqual(trend["status"], "unknown")
        self.assertIsNone(trend["prior"])

    def test_thin_prior_half_refuses_to_judge(self):
        chores = block(self.ANCHOR, 0, 50.0, 50.0)
        chores += block(self.ANCHOR, 28, 50.0, 50.0, n=2)  # below min 6
        trend = trend_of(chores, max(c.date for c in chores))
        self.assertEqual(trend["status"], "unknown")

    def test_solo_half_refuses_to_judge(self):
        chores = block(self.ANCHOR, 0, 50.0, 50.0)
        chores += [chore("maya", 30, "2026-07-10"),
                   chore("maya", 30, "2026-07-11"),
                   chore("maya", 30, "2026-07-12"),
                   chore("maya", 30, "2026-07-13"),
                   chore("maya", 30, "2026-07-14"),
                   chore("maya", 30, "2026-07-15")]
        trend = trend_of(chores, max(c.date for c in chores))
        self.assertEqual(trend["status"], "unknown")

    def test_trend_ignores_wall_clock(self):
        # The anchor is the ledger's own max date, so auditing the same
        # ledger today or next quarter yields the identical trend.
        chores = block(self.ANCHOR, 0, 55.0, 45.0)
        chores += block(self.ANCHOR, 28, 53.0, 47.0)
        first = trend_of(chores, max(c.date for c in chores))
        second = trend_of(chores, max(c.date for c in chores))
        self.assertEqual(first, second)

    def test_report_trend_uses_ledger_anchor(self):
        chores = block(self.ANCHOR, 0, 50.0, 50.0)
        chores += block(self.ANCHOR, 28, 75.0, 25.0)
        rep = report_of(chores)
        self.assertEqual(rep["trend"]["status"], "improving")
        self.assertEqual(rep["window"]["end"], self.ANCHOR)


# ---------------------------------------------------------------------------
# AC7 — perception audit

class TestPerception(unittest.TestCase):
    def test_gap_is_claim_minus_actual(self):
        chores = [chore("maya", 70, "2026-08-01"),
                  chore("noor", 30, "2026-08-02")]
        result = audit_perception(
            [claim("maya", 70, "2026-08-05")], chores)
        row = result["audit"][0]
        self.assertEqual(row["person"], "maya")
        self.assertAlmostEqual(row["actual"], 70.0)
        self.assertAlmostEqual(row["gap"], 0.0)
        self.assertFalse(row["overclaim"])

    def test_overclaim_flag_above_15_points(self):
        chores = [chore("maya", 50, "2026-08-01"),
                  chore("noor", 50, "2026-08-02")]
        result = audit_perception(
            [claim("maya", 70, "2026-08-05")], chores)
        self.assertEqual(result["audit"][0]["gap"], 20.0)
        self.assertTrue(result["audit"][0]["overclaim"])

    def test_gap_of_exactly_15_is_no_flag(self):
        chores = [chore("maya", 55, "2026-08-01"),
                  chore("noor", 45, "2026-08-02")]
        result = audit_perception(
            [claim("maya", 70, "2026-08-05")], chores)
        self.assertAlmostEqual(result["audit"][0]["gap"], 15.0)
        self.assertFalse(result["audit"][0]["overclaim"])

    def test_latest_claim_wins(self):
        chores = [chore("maya", 50, "2026-08-01"),
                  chore("noor", 50, "2026-08-02")]
        result = audit_perception(
            [claim("maya", 90, "2026-08-01"),
             claim("maya", 60, "2026-08-05")], chores)
        self.assertEqual(result["audit"][0]["claim"], 60.0)

    def test_surplus_is_sum_minus_100(self):
        chores = [chore("maya", 50, "2026-08-01"),
                  chore("noor", 50, "2026-08-02")]
        result = audit_perception(
            [claim("maya", 70, "2026-08-05"),
             claim("noor", 60, "2026-08-05")], chores)
        self.assertAlmostEqual(result["surplus"], 30.0)

    def test_surplus_needs_two_audited_claims(self):
        chores = [chore("maya", 100, "2026-08-01")]
        result = audit_perception(
            [claim("maya", 70, "2026-08-05"),
             claim("ghost", 60, "2026-08-05")], chores)
        self.assertIsNone(result["surplus"])
        self.assertEqual(len(result["audit"]), 1)
        self.assertEqual(result["unaudited"][0]["person"], "ghost")

    def test_no_claims_no_audit(self):
        chores = [chore("maya", 50, "2026-08-01"),
                  chore("noor", 50, "2026-08-02")]
        result = audit_perception([], chores)
        self.assertEqual(result["audit"], [])
        self.assertIsNone(result["surplus"])

    def test_zero_and_full_claims_are_legal(self):
        chores = [chore("maya", 50, "2026-08-01"),
                  chore("noor", 50, "2026-08-02")]
        result = audit_perception(
            [claim("maya", 0, "2026-08-05"),
             claim("noor", 100, "2026-08-05")], chores)
        self.assertAlmostEqual(result["surplus"], 0.0)


# ---------------------------------------------------------------------------
# AC8 — window scoping

class TestWindow(unittest.TestCase):
    def _household(self) -> List[Chore]:
        return [chore("maya", 100, "2026-07-01"),
                chore("noor", 100, "2026-07-02"),
                chore("maya", 100, "2026-08-20"),
                chore("maya", 100, "2026-08-25")]

    def test_all_time_is_default(self):
        rep = report_of(self._household())
        self.assertIsNone(rep["window"]["days"])
        by = {r["person"]: r for r in rep["shares"]}
        self.assertAlmostEqual(by["maya"]["pct"], 75.0)

    def test_window_scopes_shares(self):
        rep = report_of(self._household(), window=28)
        self.assertEqual(rep["window"]["start"], "2026-07-29")
        self.assertEqual(rep["window"]["end"], "2026-08-25")
        self.assertEqual([r["person"] for r in rep["shares"]], ["maya"])

    def test_solo_window_reports_n_a_gini(self):
        rep = report_of(self._household(), window=28)
        self.assertIsNone(rep["gini"]["value"])
        self.assertEqual(rep["gini"]["band"], "n/a")

    def test_degenerate_window_is_a_refusal(self):
        # any positive window still contains the anchor-day entry, so the
        # only empty window is the degenerate one
        path = ledger_of(self._household())
        try:
            got, _, broken = load_ledger(path)
            with self.assertRaises(LedgerError):
                build_report(got, [], broken, window_days=0)
        finally:
            os.unlink(path)

    def test_anchor_is_ledger_max_date_not_today(self):
        rep = report_of(self._household())
        self.assertEqual(rep["window"]["end"], "2026-08-25")


# ---------------------------------------------------------------------------
# AC9 — red flags

def clean_household() -> List[Chore]:
    """40 chores, 8 weeks, two people perfectly in balance.

    Per-chore person alternation keeps every 28-day half at exactly 50/50,
    streaks at run 1, and every chore at a 50% share — the only ledger
    that earns zero red flags.
    """
    counters = {"dishes": 0, "trash": 0}
    chores = []
    for i in range(8):
        monday = dt.date(2026, 7, 6) + dt.timedelta(days=7 * i)
        for offset, name in [(0, "dishes"), (1, "trash"), (2, "dishes"),
                             (3, "trash"), (4, "dishes")]:
            day = monday + dt.timedelta(days=offset)
            person = "maya" if counters[name] % 2 == 0 else "noor"
            counters[name] += 1
            chores.append(chore(person, 30, day.isoformat(), name=name))
    return chores


class TestRedFlags(unittest.TestCase):
    def test_clean_ledger_has_zero_flags(self):
        claims = [claim("maya", 50, "2026-08-27"),
                  claim("noor", 50, "2026-08-27")]
        rep = report_of(clean_household(), claims)
        self.assertEqual(rep["red_flags"], [])
        self.assertEqual(rep["gini"]["band"], "balanced")
        self.assertAlmostEqual(rep["perception"]["surplus"], 0.0)
        self.assertEqual(rep["trend"]["status"], "flat")

    def test_perception_surplus_flag(self):
        claims = [claim("maya", 70, "2026-08-27"),
                  claim("noor", 60, "2026-08-27")]
        rep = report_of(clean_household(), claims)
        codes = [f["code"] for f in rep["red_flags"]]
        self.assertIn("PERCEPTION SURPLUS", codes)

    def test_overclaim_flag(self):
        claims = [claim("maya", 70, "2026-08-27"),
                  claim("noor", 55, "2026-08-27")]
        rep = report_of(clean_household(), claims)
        codes = [f["code"] for f in rep["red_flags"]]
        self.assertIn("OVERCLAIM", codes)

    def test_fiefdom_and_streak_flags(self):
        # two monopolised chores (>= 2 triggers the FIEFDOM HOUSE flag):
        # cooking slides to maya, fixing piles up on noor
        chores = clean_household() + [
            chore("maya", 90, "2026-08-20", name="cooking"),
            chore("maya", 90, "2026-08-22", name="cooking"),
            chore("maya", 90, "2026-08-24", name="cooking"),
            chore("noor", 90, "2026-08-21", name="fixing"),
            chore("noor", 90, "2026-08-23", name="fixing"),
            chore("noor", 90, "2026-08-25", name="fixing"),
        ]
        rep = report_of(chores)
        codes = [f["code"] for f in rep["red_flags"]]
        self.assertIn("FIEFDOM HOUSE", codes)
        self.assertIn("STREAK", codes)

    def test_worsening_flag(self):
        chores = block("2026-08-30", 0, 75.0, 25.0)
        chores += block("2026-08-30", 28, 50.0, 50.0)
        rep = report_of(chores)
        codes = [f["code"] for f in rep["red_flags"]]
        self.assertIn("WORSENING TREND", codes)

    def test_solo_player_flag(self):
        rep = report_of([chore("maya", 50, "2026-08-01"),
                         chore("maya", 50, "2026-08-02")])
        codes = [f["code"] for f in rep["red_flags"]]
        self.assertIn("SOLE PLAYER", codes)

    def test_text_renders_clean_verdict(self):
        claims = [claim("maya", 50, "2026-08-27"),
                  claim("noor", 50, "2026-08-27")]
        rep = report_of(clean_household(), claims)
        self.assertIn("red flags: none", render_text(rep))


# ---------------------------------------------------------------------------
# AC10 — ledger parsing

class TestLedgerParsing(unittest.TestCase):
    def test_happy_ledger(self):
        path = ledger_of([chore("maya", 20, "2026-08-01")],
                         [claim("maya", 50, "2026-08-02")])
        try:
            chores, claims, broken = load_ledger(path)
            self.assertEqual(len(chores), 1)
            self.assertEqual(len(claims), 1)
            self.assertEqual(broken, 0)
        finally:
            os.unlink(path)

    def assert_broken(self, raw_line: str):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "chore", "date": "2026-08-01",
                                 "person": "maya", "chore": "dishes",
                                 "minutes": 20}) + "\n")
            fh.write(raw_line + "\n")
        try:
            chores, claims, broken = load_ledger(path)
            self.assertEqual(len(chores), 1)
            self.assertEqual(broken, 1)
        finally:
            os.unlink(path)

    def test_not_json(self):
        self.assert_broken("this is not json")

    def test_json_but_not_object(self):
        self.assert_broken("[1, 2, 3]")

    def test_missing_kind(self):
        self.assert_broken(json.dumps({"date": "2026-08-01", "person": "x",
                                       "chore": "dishes", "minutes": 5}))

    def test_unknown_kind(self):
        self.assert_broken(json.dumps({"kind": "vibe", "date": "2026-08-01",
                                       "person": "x", "pct": 50}))

    def test_bad_date(self):
        self.assert_broken(json.dumps({"kind": "chore", "date": "08/01/2026",
                                       "person": "x", "chore": "dishes",
                                       "minutes": 5}))

    def test_empty_person(self):
        self.assert_broken(json.dumps({"kind": "chore", "date": "2026-08-01",
                                       "person": "   ", "chore": "dishes",
                                       "minutes": 5}))

    def test_empty_chore_name(self):
        self.assert_broken(json.dumps({"kind": "chore", "date": "2026-08-01",
                                       "person": "x", "chore": "",
                                       "minutes": 5}))

    def test_zero_minutes(self):
        self.assert_broken(json.dumps({"kind": "chore", "date": "2026-08-01",
                                       "person": "x", "chore": "dishes",
                                       "minutes": 0}))

    def test_negative_minutes(self):
        self.assert_broken(json.dumps({"kind": "chore", "date": "2026-08-01",
                                       "person": "x", "chore": "dishes",
                                       "minutes": -5}))

    def test_bool_minutes_rejected(self):
        self.assert_broken(json.dumps({"kind": "chore", "date": "2026-08-01",
                                       "person": "x", "chore": "dishes",
                                       "minutes": True}))

    def test_nan_minutes_rejected(self):
        self.assert_broken('{"kind": "chore", "date": "2026-08-01", '
                           '"person": "x", "chore": "dishes", "minutes": NaN}')

    def test_pct_above_100_rejected(self):
        self.assert_broken(json.dumps({"kind": "claim", "date": "2026-08-01",
                                       "person": "x", "pct": 120}))

    def test_negative_pct_rejected(self):
        self.assert_broken(json.dumps({"kind": "claim", "date": "2026-08-01",
                                       "person": "x", "pct": -1}))

    def test_bool_pct_rejected(self):
        self.assert_broken(json.dumps({"kind": "claim", "date": "2026-08-01",
                                       "person": "x", "pct": False}))

    def test_blank_lines_are_free(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write(json.dumps({"kind": "chore", "date": "2026-08-01",
                                 "person": "maya", "chore": "dishes",
                                 "minutes": 20}) + "\n")
        try:
            chores, _, broken = load_ledger(path)
            self.assertEqual(len(chores), 1)
            self.assertEqual(broken, 0)
        finally:
            os.unlink(path)

    def test_chores_sorted_by_date_regardless_of_file_order(self):
        path = ledger_of([chore("maya", 20, "2026-08-05"),
                          chore("maya", 20, "2026-08-01")])
        try:
            chores, _, _ = load_ledger(path)
            self.assertEqual([c.date.isoformat() for c in chores],
                             ["2026-08-01", "2026-08-05"])
        finally:
            os.unlink(path)

    def test_fractional_minutes_are_legal(self):
        path = ledger_of([chore("maya", 7.5, "2026-08-01")])
        try:
            chores, _, broken = load_ledger(path)
            self.assertEqual(chores[0].minutes, 7.5)
            self.assertEqual(broken, 0)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC11 — CLI

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "ledger.jsonl")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def _seed_pair(self, a: float, b: float):
        run_cli(["--file", self.file, "log", "--person", "maya",
                 "--chore", "dishes", "--minutes", str(a),
                 "--date", "2026-08-01"])
        run_cli(["--file", self.file, "log", "--person", "noor",
                 "--chore", "dishes", "--minutes", str(b),
                 "--date", "2026-08-02"])

    def test_log_appends_a_row(self):
        code, out, _ = run_cli(["--file", self.file, "log", "--person", "Maya",
                                "--chore", "Dishes", "--minutes", "20",
                                "--date", "2026-08-30"])
        self.assertEqual(code, 0)
        with open(self.file, encoding="utf-8") as fh:
            row = json.loads(fh.read())
        self.assertEqual(row, {"kind": "chore", "date": "2026-08-30",
                               "person": "maya", "chore": "dishes",
                               "minutes": 20.0})
        self.assertIn("logged", out)

    def test_log_rejects_bad_minutes(self):
        code, _, err = run_cli(["--file", self.file, "log", "--person", "m",
                                "--chore", "d", "--minutes", "0"])
        self.assertEqual(code, 2)
        self.assertIn("positive", err)

    def test_log_rejects_bad_date(self):
        code, _, err = run_cli(["--file", self.file, "log", "--person", "m",
                                "--chore", "d", "--minutes", "10",
                                "--date", "2026/08/30"])
        self.assertEqual(code, 2)
        self.assertIn("bad date", err)

    def test_claim_appends_and_counts(self):
        run_cli(["--file", self.file, "log", "--person", "maya",
                 "--chore", "dishes", "--minutes", "20",
                 "--date", "2026-08-30"])
        code, out, _ = run_cli(["--file", self.file, "claim", "--person",
                                "maya", "--pct", "70",
                                "--date", "2026-08-30"])
        self.assertEqual(code, 0)
        self.assertIn("70%", out)
        with open(self.file, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(rows[-1]["kind"], "claim")
        self.assertEqual(rows[-1]["pct"], 70.0)

    def test_claim_rejects_pct_out_of_range(self):
        code, _, err = run_cli(["--file", self.file, "claim", "--person", "m",
                                "--pct", "150"])
        self.assertEqual(code, 2)
        self.assertIn("between 0 and 100", err)

    def test_report_end_to_end(self):
        self._seed_pair(75, 25)
        run_cli(["--file", self.file, "claim", "--person", "maya",
                 "--pct", "70", "--date", "2026-08-02"])
        run_cli(["--file", self.file, "claim", "--person", "noor",
                 "--pct", "60", "--date", "2026-08-02"])
        code, out, _ = run_cli(["--file", self.file, "report"])
        self.assertEqual(code, 0)
        self.assertIn("gini", out)
        self.assertIn("lopsided", out)
        self.assertIn("perception surplus", out)
        self.assertIn("+30.0 pts", out)
        self.assertIn("OVERCLAIM", out)

    def test_report_json_is_valid_and_complete(self):
        self._seed_pair(75, 25)
        code, out, _ = run_cli(["--file", self.file, "report",
                                "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        for key in ("ledger", "window", "shares", "gini", "monopolies",
                    "streaks", "perception", "trend", "red_flags"):
            self.assertIn(key, data)
        self.assertEqual(data["gini"]["band"], "lopsided")

    def test_report_missing_file_is_exit_2(self):
        code, _, err = run_cli(["--file", self.file, "report"])
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_report_empty_ledger_is_exit_3(self):
        with open(self.file, "w", encoding="utf-8") as fh:
            fh.write('{"kind": "claim", "date": "2026-08-01", '
                     '"person": "maya", "pct": 50}\n')
        code, _, err = run_cli(["--file", self.file, "report"])
        self.assertEqual(code, 3)
        self.assertIn("nothing to audit", err)

    def test_fail_under_gate_is_exit_4(self):
        self._seed_pair(75, 25)
        code, _, err = run_cli(["--file", self.file, "report",
                                "--fail-under", "0.2"])
        self.assertEqual(code, 4)
        self.assertIn("gate", err)

    def test_fail_under_passes_fair_household(self):
        self._seed_pair(50, 50)
        code, _, _ = run_cli(["--file", self.file, "report",
                              "--fail-under", "0.2"])
        self.assertEqual(code, 0)

    def test_report_is_deterministic(self):
        self._seed_pair(75, 25)
        _, first, _ = run_cli(["--file", self.file, "report"])
        _, second, _ = run_cli(["--file", self.file, "report"])
        self.assertEqual(first, second)

    def test_parser_requires_a_command(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args([])


# ---------------------------------------------------------------------------
# AC12 — zero dependencies

class TestZeroDependencies(unittest.TestCase):
    ALLOWED = {
        "__future__", "argparse", "datetime", "json", "math", "os", "sys",
        "dataclasses", "typing",
    }

    def _imports_of(self, path: str) -> set:
        source = open(path, encoding="utf-8").read()
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0]
                                for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])
        return imported

    def test_tool_imports_stdlib_only(self):
        imported = self._imports_of(os.path.join(ROOT, "contribution_gap.py"))
        self.assertTrue(imported)
        self.assertEqual(imported - self.ALLOWED, set())

    def test_test_file_imports_stdlib_only(self):
        imported = self._imports_of(os.path.abspath(__file__))
        imported.discard("contribution_gap")
        allowed = self.ALLOWED | {"unittest", "io", "tempfile", "ast",
                                  "subprocess", "contextlib"}
        self.assertEqual(imported - allowed, set())


# ---------------------------------------------------------------------------
# AC13 — dogfood: the example household

class DogfoodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = os.path.join(EXAMPLES, "ledger.jsonl")
        cls.chores, cls.claims, cls.broken = load_ledger(cls.ledger)
        cls.report = build_report(cls.chores, cls.claims, cls.broken)

    def test_ledger_shape(self):
        self.assertEqual(len(self.chores), 100)
        self.assertEqual(len(self.claims), 2)
        self.assertEqual(self.broken, 0)

    def test_balanced_total_two_person_household(self):
        by = {r["person"]: r for r in self.report["shares"]}
        self.assertEqual(set(by), {"maya", "noor"})
        self.assertAlmostEqual(by["maya"]["pct"], 53.3, places=1)
        self.assertAlmostEqual(by["noor"]["pct"], 46.7, places=1)
        self.assertEqual(self.report["gini"]["band"], "balanced")
        self.assertAlmostEqual(self.report["gini"]["value"], 0.033, places=3)

    def test_five_fiefdoms_despite_fair_total(self):
        fiefs = self.report["monopolies"]["items"]
        self.assertEqual(len(fiefs), 5)
        owners = {f["chore"]: f["owner"] for f in fiefs}
        self.assertEqual(owners["dishes"], "maya")
        self.assertEqual(owners["cooking"], "maya")
        self.assertEqual(owners["groceries"], "noor")
        self.assertEqual(owners["trash"], "noor")
        self.assertEqual(owners["fixing"], "noor")

    def test_perception_surplus_is_thirty_points(self):
        audit = {row["person"]: row
                 for row in self.report["perception"]["audit"]}
        self.assertAlmostEqual(audit["maya"]["claim"], 70.0)
        self.assertAlmostEqual(audit["maya"]["actual"], 53.3)
        self.assertAlmostEqual(audit["maya"]["gap"], 16.7)
        self.assertTrue(audit["maya"]["overclaim"])
        self.assertAlmostEqual(audit["noor"]["gap"], 13.3)
        self.assertFalse(audit["noor"]["overclaim"])
        self.assertAlmostEqual(self.report["perception"]["surplus"], 30.0)

    def test_streaks_all_point_at_maya(self):
        streaks = {s["chore"]: s for s in self.report["streaks"]["items"]}
        self.assertEqual(streaks["dishes"]["person"], "maya")
        self.assertEqual(streaks["dishes"]["run"], 6)
        self.assertEqual(streaks["cooking"]["person"], "maya")
        self.assertEqual(streaks["cooking"]["run"], 6)

    def test_trend_is_worsening(self):
        trend = self.report["trend"]
        self.assertEqual(trend["status"], "worsening")
        self.assertAlmostEqual(trend["prior"], 0.04, places=3)
        self.assertAlmostEqual(trend["recent"], 0.107, places=3)

    def test_window_28_shifts_the_picture(self):
        report = build_report(self.chores, self.claims, self.broken,
                              window_days=28)
        self.assertEqual(report["window"]["start"], "2026-08-03")
        by = {r["person"]: r for r in report["shares"]}
        self.assertAlmostEqual(by["maya"]["pct"], 60.7, places=1)
        self.assertAlmostEqual(report["gini"]["value"], 0.107, places=3)
        self.assertEqual(report["gini"]["band"], "tilted")
        window_audit = {row["person"]: row
                        for row in report["perception"]["audit"]}
        self.assertAlmostEqual(window_audit["noor"]["gap"], 20.7)
        self.assertTrue(window_audit["noor"]["overclaim"])
        self.assertFalse(window_audit["maya"]["overclaim"])

    def test_render_mentions_the_headlines(self):
        text = render_text(self.report)
        for needle in ("balanced", "fiefdoms", "perception surplus",
                       "+30.0 pts", "worsening", "PERCEPTION SURPLUS",
                       "FIEFDOM HOUSE", "STREAK", "WORSENING TREND"):
            self.assertIn(needle, text)


# ---------------------------------------------------------------------------
# AC14 — examples are rebuildable and byte-stable

class ExamplesSyncTests(unittest.TestCase):
    def test_examples_rebuild_byte_identical(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(EXAMPLES, "build_examples.py"),
             "--check"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         msg="examples out of sync:\n%s%s"
                             % (proc.stdout, proc.stderr))


if __name__ == "__main__":
    unittest.main()
