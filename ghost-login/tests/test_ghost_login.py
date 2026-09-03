#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance suite for ghost-login.

Every README acceptance criterion is pinned here. The numeric fixtures are
hand-checkable: zhou's twelve-account vault (CloudDrive 25+18+8+25 = 76
ZOMBIE, BankApp 5+0+8+25 = 38 SOUND despite its vital tier) and mei's
three-account control with no clusters at all.
"""

from __future__ import annotations

import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # ghost-login/
EXAMPLES = os.path.join(ROOT, "examples")

sys.path.insert(0, ROOT)
import ghost_login as gl  # noqa: E402


def run_cli(*argv):
    """Run main() in-process; return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = gl.main(list(argv))
    except SystemExit as exc:
        code = exc.code
        if code is None:
            code = 0
    return code, out.getvalue(), err.getvalue()


def write_vault(rows, directory=None, name="vault.tsv"):
    """rows: (name, username, password, pw_set, last_used, tier);
    last_used may be '' or '-' for never."""
    if directory is None:
        directory = tempfile.mkdtemp()
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write("\t".join(r) + "\n")
    return path


def account_of(surface, name):
    return next((a, sc) for a, sc in surface.scored if a.name == name)


ZHOU = os.path.join(EXAMPLES, "zhou-vault.tsv")
MEI = os.path.join(EXAMPLES, "mei-vault.tsv")


# ---------------------------------------------------------------------------
# entropy
# ---------------------------------------------------------------------------

class EntropyTests(unittest.TestCase):
    def test_eight_digits_is_26_6_bits_weak(self):
        bits = gl.entropy_bits("12345678")
        self.assertAlmostEqual(bits, 8 * math.log2(10), places=3)
        self.assertEqual(gl.entropy_grade(bits), "weak")

    def test_lower_plus_digits_is_fair(self):
        bits = gl.entropy_bits("hunter22")       # 8 chars over 36 symbols
        self.assertAlmostEqual(bits, 8 * math.log2(36), places=3)
        self.assertEqual(gl.entropy_grade(bits), "fair")

    def test_four_class_password_is_strong(self):
        bits = gl.entropy_bits("Ink&Well9go")    # 11 chars over 95 symbols
        self.assertAlmostEqual(bits, 11 * math.log2(95), places=3)
        self.assertEqual(gl.entropy_grade(bits), "strong")

    def test_grade_thresholds(self):
        self.assertEqual(gl.entropy_grade(27.9), "weak")
        self.assertEqual(gl.entropy_grade(28.0), "fair")
        self.assertEqual(gl.entropy_grade(44.9), "fair")
        self.assertEqual(gl.entropy_grade(45.0), "strong")

    def test_only_present_classes_count(self):
        # 10 lowercase chars: 10 * log2(26), no upper/digit/other bonus
        self.assertAlmostEqual(gl.entropy_bits("abcdefghij"),
                               10 * math.log2(26), places=3)


# ---------------------------------------------------------------------------
# vault parsing
# ---------------------------------------------------------------------------

class VaultParseTests(unittest.TestCase):
    def test_comments_header_and_blank_lines(self):
        entries = gl.read_vault(ZHOU)             # has all three
        self.assertEqual(len(entries), 12)

    def test_five_columns_default_tier_normal(self):
        path = write_vault([("Blog", "a@b.c", "pw one two", "2020-01-01", "-")])
        accs = gl.read_vault(path)
        self.assertEqual(accs[0].tier, "normal")
        self.assertIsNone(accs[0].last_used)

    def test_dash_means_never_relogged(self):
        path = write_vault([("Blog", "a@b.c", "pw one two", "2020-01-01", "-",
                             "trivial")])
        self.assertIsNone(gl.read_vault(path)[0].last_used)

    def test_bad_tier_reports_line(self):
        path = write_vault([("Blog", "a@b.c", "pw", "2020-01-01", "-", "core")])
        with self.assertRaises(gl.VaultError) as ctx:
            gl.read_vault(path)
        self.assertIn("line 1", str(ctx.exception))

    def test_bad_date_reports_line(self):
        path = write_vault([("Blog", "a@b.c", "pw", "2020-1-1", "-", "normal")])
        with self.assertRaises(gl.VaultError) as ctx:
            gl.read_vault(path)
        self.assertIn("line 1", str(ctx.exception))
        self.assertIn("pw_set", str(ctx.exception))

    def test_empty_password_rejected(self):
        path = write_vault([("Blog", "a@b.c", "", "2020-01-01", "-")])
        with self.assertRaises(gl.VaultError) as ctx:
            gl.read_vault(path)
        self.assertIn("empty password", str(ctx.exception))

    def test_duplicate_account_rejected_with_first_line(self):
        path = write_vault([("Blog", "a@b.c", "pw1", "2020-01-01", "-"),
                            ("Shop", "a@b.c", "pw2", "2020-01-01", "-"),
                            ("Blog", "a@b.c", "pw3", "2020-01-01", "-")])
        with self.assertRaises(gl.VaultError) as ctx:
            gl.read_vault(path)
        self.assertIn("line 3", str(ctx.exception))
        self.assertIn("first seen on line 1", str(ctx.exception))

    def test_empty_vault_rejected(self):
        with self.assertRaises(gl.VaultError):
            gl.read_vault(write_vault([]))

    def test_missing_file_rejected(self):
        with self.assertRaises(gl.VaultError) as ctx:
            gl.read_vault("/nonexistent/vault.tsv")
        self.assertIn("cannot read", str(ctx.exception))

    def test_same_password_two_accounts_is_not_an_error(self):
        path = write_vault([("A", "a@b.c", "pw", "2020-01-01", "-"),
                            ("B", "a@b.c", "pw", "2020-01-01", "-")])
        self.assertEqual(len(gl.read_vault(path)), 2)


# ---------------------------------------------------------------------------
# scoring factors
# ---------------------------------------------------------------------------

class ScoreFactorTests(unittest.TestCase):
    def test_age_floor_semantics(self):
        # 1.99y -> 0 points; exactly 2y -> 5; 10y+ capped at 25
        self.assertEqual(gl.age_score_of("2024-11-01", "2026-08-30"), 0)
        self.assertEqual(gl.age_score_of("2024-08-29", "2026-08-30"), 5)
        self.assertEqual(gl.age_score_of("2011-03-01", "2026-08-30"), 25)

    def test_age_future_pw_set_clamps_to_zero(self):
        self.assertEqual(gl.age_score_of("2027-01-01", "2026-08-30"), 0)

    def test_stale_missing_is_never_floor(self):
        self.assertEqual(gl.stale_score_of(None, "2026-08-30"),
                         gl.STALE_NEVER)

    def test_stale_floor_semantics(self):
        # 0y -> 0; 1.08y -> 8; 5y+ capped at 25
        self.assertEqual(gl.stale_score_of("2026-08-30", "2026-08-30"), 0)
        self.assertEqual(gl.stale_score_of("2025-08-01", "2026-08-30"), 8)
        self.assertEqual(gl.stale_score_of("2021-06-01", "2026-08-30"), 25)

    def test_stale_future_date_clamps_to_zero(self):
        self.assertEqual(gl.stale_score_of("2027-01-01", "2026-08-30"), 0)

    def test_reuse_scales_and_caps(self):
        self.assertEqual(min(25, gl.REUSE_PER_PEER * 0), 0)
        self.assertEqual(min(25, gl.REUSE_PER_PEER * (2 - 1)), 8)
        self.assertEqual(min(25, gl.REUSE_PER_PEER * (4 - 1)), 24)
        self.assertEqual(min(25, gl.REUSE_PER_PEER * (9 - 1)), 25)

    def test_sens_mapping(self):
        self.assertEqual(gl.SENS_SCORE,
                         {"vital": 25, "normal": 12, "trivial": 4})

    def test_grade_boundaries(self):
        def grade_of(total):
            sc = gl.Score(age=0, stale=0, reuse=0, sens=0, total=total,
                          cluster=1, bits=0.0)
            return sc.grade
        self.assertEqual(grade_of(39), "SOUND")
        self.assertEqual(grade_of(40), "MUSTY")
        self.assertEqual(grade_of(59), "MUSTY")
        self.assertEqual(grade_of(60), "ZOMBIE")


# ---------------------------------------------------------------------------
# pinned numbers on the zhou fixture
# ---------------------------------------------------------------------------

class ZhouFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.accounts = gl.read_vault(ZHOU)
        cls.surface = gl.compute_surface(cls.accounts, "2026-08-30")

    def test_as_of_is_last_vault_date(self):
        self.assertEqual(gl.resolve_as_of(self.accounts, None), "2026-08-30")

    def test_primary_default_is_most_frequent_username(self):
        self.assertEqual(self.surface.primary, "zhou@mail.com")

    def test_primary_exposure_pinned(self):
        self.assertEqual(self.surface.primary_exposure, 4)
        self.assertEqual(self.surface.primary_zombies, 3)

    def test_clouddrive_76_zombie(self):
        a, sc = account_of(self.surface, "CloudDrive")
        self.assertEqual((sc.age, sc.stale, sc.reuse, sc.sens),
                         (25, 18, 8, 25))
        self.assertEqual(sc.total, 76)
        self.assertEqual(sc.grade, "ZOMBIE")
        self.assertEqual(sc.cluster, 2)

    def test_oldforum_71_in_size3_cluster(self):
        a, sc = account_of(self.surface, "OldForum")
        self.assertEqual((sc.age, sc.stale, sc.reuse, sc.sens),
                         (25, 18, 16, 12))
        self.assertEqual(sc.total, 71)
        self.assertEqual(sc.cluster, 3)

    def test_news_site_65_and_music_site_63(self):
        _, sc = account_of(self.surface, "NewsSite")
        self.assertEqual((sc.age, sc.stale, sc.reuse, sc.sens),
                         (20, 25, 8, 12))
        self.assertEqual(sc.total, 65)
        _, sc = account_of(self.surface, "MusicSite")
        self.assertEqual(sc.total, 63)
        self.assertEqual(sc.grade, "ZOMBIE")

    def test_bankapp_38_sound_despite_vital(self):
        """A vital account that is fresh and unique stays SOUND: the tier
        factor alone must not drag good accounts into the danger zone."""
        _, sc = account_of(self.surface, "BankApp")
        self.assertEqual((sc.age, sc.stale, sc.reuse, sc.sens),
                         (5, 0, 8, 25))
        self.assertEqual(sc.total, 38)
        self.assertEqual(sc.grade, "SOUND")

    def test_grade_counts_444(self):
        self.assertEqual(gl.grade_counts(self.surface.scored),
                         {"SOUND": 4, "MUSTY": 4, "ZOMBIE": 4})

    def test_ordering_score_desc_name_asc(self):
        totals = [sc.total for _, sc in self.surface.scored]
        self.assertEqual(totals, sorted(totals, reverse=True))
        first = self.surface.scored[0][0].name
        self.assertEqual(first, "CloudDrive")

    def test_weakest_password_pinned(self):
        a, sc = self.surface.weakest
        self.assertEqual(a.name, "StreamVideo")
        self.assertAlmostEqual(round(sc.bits, 1), 26.6)
        self.assertEqual(gl.entropy_grade(sc.bits), "weak")

    def test_never_logged_warning(self):
        self.assertEqual(self.surface.never_logged, 3)
        self.assertIn("3 account(s) have no last-login on record",
                      self.surface.warnings_list()[0])

    def test_vital_clusters(self):
        holders = {m.name for _, m in self.surface.vital_clusters for m in m}
        # every member of a vital-bearing cluster sits in the blast radius
        self.assertEqual(holders,
                         {"CloudDrive", "NewsSite", "BankApp", "UtilityBill"})


class MeiFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.surface = gl.compute_surface(gl.read_vault(MEI), "2026-08-30")

    def test_all_sound_no_clusters(self):
        self.assertEqual(gl.grade_counts(self.surface.scored),
                         {"SOUND": 3, "MUSTY": 0, "ZOMBIE": 0})
        self.assertEqual(self.surface.n_reused, 0)
        self.assertEqual(self.surface.vital_clusters, [])

    def test_pinned_scores(self):
        self.assertEqual(account_of(self.surface, "Bank")[1].total, 25)
        self.assertEqual(account_of(self.surface, "Shop")[1].total, 16)
        self.assertEqual(account_of(self.surface, "Diary")[1].total, 12)


class PrimaryTests(unittest.TestCase):
    def _surface(self, rows, primary=None):
        return gl.compute_surface(gl.read_vault(write_vault(rows)),
                                  "2026-08-30", primary)

    def test_tie_broken_alphabetically(self):
        rows = [("A", "b@x.com", "pw1", "2020-01-01", "-"),
                ("B", "a@x.com", "pw2", "2020-01-01", "-")]
        self.assertEqual(self._surface(rows).primary, "a@x.com")

    def test_override_flag_wins(self):
        rows = [("A", "a@x.com", "pw1", "2020-01-01", "-"),
                ("B", "b@x.com", "pw2", "2020-01-01", "-")]
        self.assertEqual(self._surface(rows, "b@x.com").primary, "b@x.com")


class FingerprintTests(unittest.TestCase):
    def test_same_password_same_fingerprint(self):
        a1, _ = account_of(ZHOU_SURFACE, "OldForum")
        a2, _ = account_of(ZHOU_SURFACE, "MusicSite")
        self.assertEqual(a1.fingerprint, a2.fingerprint)

    def test_reports_never_contain_plaintext_passwords(self):
        code, text, _ = run_cli("report", ZHOU)
        self.assertEqual(code, gl.EXIT_OK)
        for secret in ("hunter22", "12345678", "Sunny#day88",
                       "Tidy!Quilt7Lamp", "Corr3ct-Horse!9"):
            self.assertNotIn(secret, text)
        code, text, _ = run_cli("clusters", ZHOU)
        for secret in ("hunter22", "12345678", "Sunny#day88"):
            self.assertNotIn(secret, text)
        code, js, _ = run_cli("report", ZHOU, "--format", "json")
        for secret in ("hunter22", "12345678"):
            self.assertNotIn(secret, js)


ZHOU_SURFACE = gl.compute_surface(gl.read_vault(ZHOU), "2026-08-30")


# ---------------------------------------------------------------------------
# report & clusters rendering
# ---------------------------------------------------------------------------

class ReportTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(EXAMPLES, "sample-report-zhou.txt"),
                  encoding="utf-8") as fh:
            cls.text = fh.read()

    def test_header_snapshot(self):
        self.assertIn("-- Ghost login report: zhou-vault.tsv  "
                      "(as of 2026-08-30)", self.text)
        self.assertIn("accounts tracked       : 12  "
                      "(4 vital / 4 normal / 4 trivial)", self.text)
        self.assertIn("grades                 : 4 SOUND · 4 MUSTY · "
                      "4 ZOMBIE", self.text)
        self.assertIn("primary identity       : zhou@mail.com "
                      "(4 accounts · 3 zombie(s) behind it)", self.text)
        self.assertIn("weakest password       : StreamVideo  26.6 bits (weak)",
                      self.text)

    def test_zombie_block_sorted_desc_with_factor_lines(self):
        i_z = self.text.index("ZOMBIE — score >= 60")
        i_m = self.text.index("MUSTY — 40-59")
        block = self.text[i_z:i_m]
        self.assertIn("score 76  CloudDrive", block)
        self.assertIn("score 71  OldForum", block)
        self.assertLess(block.index("CloudDrive"), block.index("OldForum"))
        self.assertIn("set 2016 · never re-logged · age 25 · stale 18 · "
                      "reuse 8 · sens 25", block)

    def test_verdict_pinned(self):
        self.assertIn("Your attack surface is not your strongest password",
                      self.text)
        self.assertIn("recovery channel\nfor 3 of them", self.text)
        self.assertIn("2 reuse cluster(s) hold a vital account", self.text)
        self.assertIn("Deletion clears zombies; only a password change "
                      "breaks a cluster.", self.text)

    def test_mei_no_zombie_verdict_branch(self):
        with open(os.path.join(EXAMPLES, "sample-report-mei.txt"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("No zombies: nothing here is statistically dead.",
                      text)


class ClustersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(EXAMPLES, "sample-clusters-zhou.txt"),
                  encoding="utf-8") as fh:
            cls.text = fh.read()

    def test_cluster_sizes_and_vital_marks(self):
        self.assertIn("3 cluster(s); 7 of 12 accounts share a password.",
                      self.text)
        self.assertIn("cluster #20d2fe5e  size 3", self.text)
        self.assertIn("cluster #e16f29ae  size 2  !! holds a vital account",
                      self.text)
        self.assertIn("cluster #fc99a59f  size 2  !! holds a vital account",
                      self.text)

    def test_conditional_footer(self):
        # vital cluster: start from the vital one; plain cluster: any member
        self.assertIn("the fix is one password change (start from the vital "
                      "one).", self.text)
        self.assertIn("the fix is one password change on any member of the "
                      "cluster.", self.text)

    def test_no_cluster_branch(self):
        code, out, _ = run_cli("clusters", MEI)
        self.assertEqual(code, gl.EXIT_OK)
        self.assertIn("none — every account runs on its own password.", out)


# ---------------------------------------------------------------------------
# simulation
# ---------------------------------------------------------------------------

class SimulateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(EXAMPLES, "sample-simulate-drop3.txt"),
                  encoding="utf-8") as fh:
            cls.text = fh.read()

    def test_drop3_pinned(self):
        self.assertIn("dropped                : CloudDrive, NewsSite, "
                      "OldForum", self.text)
        self.assertIn("grades                 : 4 ZOMBIE · 4 MUSTY · "
                      "4 SOUND  ->  1 ZOMBIE · 4 MUSTY · 4 SOUND", self.text)
        self.assertIn("reuse clusters         : 3 -> 2   (largest 3 -> 2)",
                      self.text)
        self.assertIn("primary exposure       : 4 accounts -> 1  "
                      "(zombies behind it 3 -> 0)", self.text)
        self.assertIn("mean score             : 49.8 -> 42.8", self.text)

    def test_survivor_verdict_pinned(self):
        self.assertIn("Deletion cleared 3 zombie(s) — but 2 cluster(s) "
                      "survived, holding: BankApp, MusicSite, PizzaApp, "
                      "UtilityBill.", self.text)
        self.assertIn("Zombies are removed by deletion; clusters only by "
                      "a password change.", self.text)

    def test_drop4_removes_every_zombie_but_one_cluster(self):
        """The 4th zombie is MusicSite (hunter22's third member): dropping
        it shrinks that cluster to PizzaApp alone, but Tidy!Quilt7Lamp
        still binds BankApp to UtilityBill — deletion cannot break it."""
        code, out, _ = run_cli("simulate", ZHOU, "drop", "4")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertIn("dropped                : CloudDrive, MusicSite, "
                      "NewsSite, OldForum", out)
        self.assertIn("->  0 ZOMBIE · 4 MUSTY · 4 SOUND", out)
        self.assertIn("reuse clusters         : 3 -> 1   (largest 3 -> 2)",
                      out)
        self.assertIn("Deletion cleared 4 zombie(s) — but 1 cluster(s) "
                      "survived, holding: BankApp, UtilityBill.", out)

    def test_drop0_is_noop(self):
        code, out, _ = run_cli("simulate", ZHOU, "drop", "0")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertIn("nothing dropped — you asked for 0", out)

    def test_overshoot_noted(self):
        code, out, _ = run_cli("simulate", ZHOU, "drop", "99")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertIn("note: only 4 zombie(s) exist; dropping all 4.", out)

    def test_no_zombie_branch(self):
        code, out, _ = run_cli("simulate", MEI, "drop", "3")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertIn("nothing to drop", out)


# ---------------------------------------------------------------------------
# gate, validate & CLI contract
# ---------------------------------------------------------------------------

class GateTests(unittest.TestCase):
    def test_gate_trips(self):
        code, _, err = run_cli("report", ZHOU, "--fail-zombies", "4")
        self.assertEqual(code, gl.EXIT_GATE)
        self.assertIn("gate: 4 ZOMBIE >= --fail-zombies 4", err)

    def test_gate_passes(self):
        code, _, err = run_cli("report", ZHOU, "--fail-zombies", "5")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertEqual(err, "")


class ValidateTests(unittest.TestCase):
    def test_validate_zhou_pinned(self):
        code, out, _ = run_cli("validate", ZHOU)
        self.assertEqual(code, gl.EXIT_OK)
        self.assertIn("rows parsed           : 12  "
                      "(4 vital / 4 normal / 4 trivial)", out)
        self.assertIn("unique usernames      : 5", out)
        self.assertIn("pw_set range          : 2011-03-01 .. 2025-06-01", out)
        self.assertIn("as_of                 : 2026-08-30", out)
        self.assertIn("3 row(s) with no last-login date", out)

    def test_validate_warns_on_future_rows(self):
        code, out, _ = run_cli("validate", ZHOU, "--today", "2020-01-01")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertIn("row(s) dated after as_of", out)


class CliTests(unittest.TestCase):
    def test_report_text_ok(self):
        code, out, _ = run_cli("report", ZHOU)
        self.assertEqual(code, gl.EXIT_OK)
        self.assertTrue(out.startswith("-- Ghost login report:"))

    def test_report_json_ok(self):
        code, out, _ = run_cli("report", ZHOU, "--format", "json")
        self.assertEqual(code, gl.EXIT_OK)
        doc = json.loads(out)
        self.assertEqual(doc["n_accounts"], 12)

    def test_clusters_ok(self):
        code, out, _ = run_cli("clusters", ZHOU)
        self.assertEqual(code, gl.EXIT_OK)
        self.assertTrue(out.startswith("-- Reuse clusters:"))

    def test_missing_file_exit_3(self):
        code, _, err = run_cli("report", "/nonexistent.tsv")
        self.assertEqual(code, gl.EXIT_INPUT)
        self.assertIn("error:", err)

    def test_bad_row_exit_3(self):
        path = write_vault([("Blog", "a@b.c", "pw", "2020-13-01", "-")])
        code, _, err = run_cli("report", path)
        self.assertEqual(code, gl.EXIT_INPUT)
        self.assertIn("line 1", err)

    def test_bad_today_exit_3(self):
        code, _, err = run_cli("report", ZHOU, "--today", "2026-02-30")
        self.assertEqual(code, gl.EXIT_INPUT)
        self.assertIn("bad --today", err)

    def test_bad_scenario_exit_2(self):
        code, _, _ = run_cli("simulate", ZHOU, "merge")
        self.assertEqual(code, gl.EXIT_USAGE)

    def test_negative_drop_exit_2(self):
        code, _, _ = run_cli("simulate", ZHOU, "drop", "-1")
        self.assertEqual(code, gl.EXIT_USAGE)

    def test_no_subcommand_prints_help_exit_2(self):
        code, out, _ = run_cli()
        self.assertEqual(code, gl.EXIT_USAGE)
        self.assertIn("usage:", out)

    def test_primary_override_flag(self):
        code, out, _ = run_cli("report", ZHOU, "--primary", "zhou1985")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertIn("primary identity       : zhou1985 "
                      "(3 accounts · 0 zombie(s) behind it)", out)


# ---------------------------------------------------------------------------
# dogfood: the committed examples must reproduce byte for byte
# ---------------------------------------------------------------------------

class ExamplesSyncTests(unittest.TestCase):
    def test_build_examples_check(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(EXAMPLES, "build_examples.py"),
             "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("all 6 example files in sync", proc.stdout)


class DogfoodTests(unittest.TestCase):
    """Re-run the CLI on the committed vaults; the outputs must match the
    pinned samples byte for byte."""

    def _pinned(self, name):
        with open(os.path.join(EXAMPLES, name), encoding="utf-8") as fh:
            return fh.read()

    def _in_examples(self, *argv):
        cwd = os.getcwd()
        os.chdir(EXAMPLES)
        try:
            return run_cli(*argv)
        finally:
            os.chdir(cwd)

    def test_report_zhou_reproduces(self):
        code, out, _ = self._in_examples("report", "zhou-vault.tsv")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertEqual(out, self._pinned("sample-report-zhou.txt"))

    def test_report_mei_reproduces(self):
        code, out, _ = self._in_examples("report", "mei-vault.tsv")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertEqual(out, self._pinned("sample-report-mei.txt"))

    def test_clusters_zhou_reproduces(self):
        code, out, _ = self._in_examples("clusters", "zhou-vault.tsv")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertEqual(out, self._pinned("sample-clusters-zhou.txt"))

    def test_simulate_zhou_reproduces(self):
        code, out, _ = self._in_examples("simulate", "zhou-vault.tsv",
                                         "drop", "3")
        self.assertEqual(code, gl.EXIT_OK)
        self.assertEqual(out, self._pinned("sample-simulate-drop3.txt"))

    def test_json_invariants(self):
        code, out, _ = run_cli("report", ZHOU, "--format", "json")
        doc = json.loads(out)
        self.assertEqual(sum(doc["grades"].values()), doc["n_accounts"])
        for a in doc["accounts"]:
            self.assertEqual(a["score"], sum(a["factors"].values()))
            if a["grade"] == "ZOMBIE":
                self.assertGreaterEqual(a["score"], 60)
            if a["grade"] == "SOUND":
                self.assertLess(a["score"], 40)
        # same fingerprint <=> same cluster
        fps = {}
        for a in doc["accounts"]:
            fps.setdefault(a["password_fingerprint"], set()).add(
                a["cluster_size"])
        self.assertTrue(all(len(v) == 1 for v in fps.values()))


if __name__ == "__main__":
    unittest.main()
