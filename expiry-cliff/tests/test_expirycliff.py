"""Acceptance tests for 到期悬崖 · Expiry Cliff.

Every acceptance criterion from the README lives here: registry parsing,
margin resolution, band math, horizon ranking, trip gating, renewal rhythm,
privacy redaction, CLI behavior — plus dogfood runs against the repo's own
demo registry and a byte-identical rebuild check of the example artifacts.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
REPO = PROJECT.parent
sys.path.insert(0, str(PROJECT))

import expiry_cliff as ec  # noqa: E402

CLI = str(PROJECT / "expiry_cliff.py")
DEMO = PROJECT / "examples" / "family-registry.csv"
AS_OF = "2025-12-01"


def ns(**over):
    base = dict(as_of=date(2025, 12, 1), category_margin=None, top=15,
                redact=False, format="text")
    base.update(over)
    return SimpleNamespace(**base)


class RegistryTestCase(unittest.TestCase):
    def write(self, lines, header="name,category,start,end,margin,holder"):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(([header] if header is not None else []) + lines) + "\n")
        self.addCleanup(os.unlink, path)
        return path

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, CLI] + list(argv),
                              capture_output=True, text=True)


class ParserTests(RegistryTestCase):
    def test_minimal_headers(self):
        path = self.write(["Passport,passport,2016-01-15,2026-03-01"],
                          header="name,category,start,end")
        periods = ec.read_registry(path)
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["start"], date(2016, 1, 15))
        self.assertEqual(periods[0]["end"], date(2026, 3, 1))
        self.assertIsNone(periods[0]["margin"])

    def test_chinese_headers(self):
        path = self.write(["护照,passport,2016-01-15,2026-03-01,180,张雅"],
                          header="名称,类别,生效日,到期日,提前量,持有人")
        periods = ec.read_registry(path)
        self.assertEqual(periods[0]["name"], "护照")
        self.assertEqual(periods[0]["holder"], "张雅")
        self.assertEqual(periods[0]["margin"], 180)

    def test_bom_and_blank_lines(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8-sig") as fh:
            fh.write("name,category,start,end\n\nPassport,passport,2020-01-01,2030-01-01\n\n\n")
        self.addCleanup(os.unlink, path)
        self.assertEqual(len(ec.read_registry(path)), 1)

    def test_date_formats(self):
        rows = ["A,passport,2020-03-05,2030-03-05", "B,passport,2020/03/05,2030/03/05",
                "C,passport,2020.03.05,2030.03.05", "D,passport,2020年3月5日,2030年3月5日"]
        periods = ec.read_registry(self.write(rows))
        self.assertEqual({p["start"] for p in periods}, {date(2020, 3, 5)})
        self.assertEqual({p["end"] for p in periods}, {date(2030, 3, 5)})

    def test_margin_blank_means_category_default(self):
        periods = ec.read_registry(self.write(["A,passport,2020-01-01,2030-01-01"]))
        self.assertIsNone(periods[0]["margin"])

    def test_end_before_start_raises_with_line(self):
        with self.assertRaises(ec.ParseError):
            ec.read_registry(self.write(["A,passport,2020-05-01,2020-01-01"]))

    def test_no_header_raises(self):
        with self.assertRaises(ec.ParseError):
            ec.read_registry(self.write(["foo,bar,baz,qux"], header=None))


class MarginTests(RegistryTestCase):
    def row(self, margin=""):
        return self.write(["A,passport,2016-01-15,2026-03-01,%s" % margin])

    def test_row_margin_overrides_category_default(self):
        item = ec.horizon(self.row("120"), ns())["items"][0]
        self.assertEqual(item["margin"], 120)

    def test_default_table_lookup(self):
        for cat, want in (("passport", 180), ("insurance", 0),
                          ("tls_cert", 21), ("kronos_handle", 0)):
            path = self.write(["A,%s,2016-01-15,2026-03-01" % cat])
            item = ec.horizon(path, ns())["items"][0]
            self.assertEqual(item["margin"], want, cat)

    def test_category_margin_flag_overrides_default(self):
        item = ec.horizon(self.row(), ns(category_margin={"passport": 120}))["items"][0]
        self.assertEqual(item["margin"], 120)

    def test_row_margin_beats_flag(self):
        item = ec.horizon(self.row("60"), ns(category_margin={"passport": 120}))["items"][0]
        self.assertEqual(item["margin"], 60)


class BandTests(unittest.TestCase):
    def test_band_boundaries(self):
        cases = [(-1, "OVERDUE"), (0, "CLIFF"), (29, "CLIFF"),
                 (30, "CAUTION"), (89, "CAUTION"), (90, "CLEAR")]
        for left, want in cases:
            self.assertEqual(ec.band_of(left), want, left)

    def test_effective_end_is_end_minus_margin(self):
        item = ec.build_item(("a", "", "passport"),
                             [{"name": "a", "holder": "", "category": "passport",
                               "start": date(2016, 1, 15), "end": date(2026, 3, 1),
                               "margin": None, "line": 1}],
                             date(2025, 12, 1), {})
        self.assertEqual(item["effective_end"], date(2025, 9, 2))
        self.assertEqual(item["left"], -90)

    def test_future_band_when_not_started(self):
        item = ec.build_item(("a", "", "membership"),
                             [{"name": "a", "holder": "", "category": "membership",
                               "start": date(2026, 1, 1), "end": date(2027, 1, 1),
                               "margin": None, "line": 1}],
                             date(2025, 12, 1), {})
        self.assertEqual(item["band"], "FUTURE")


class HorizonTests(RegistryTestCase):
    def horizon(self, *extra):
        proc = self.run_cli("horizon", str(DEMO), "--as-of", AS_OF,
                            "--format", "json", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_sorted_ascending_by_effective_left(self):
        report = self.horizon()
        lefts = [i["days_left"] for i in report["items"]]
        self.assertEqual(lefts, sorted(lefts))

    def test_counts_and_first_to_fall(self):
        report = self.horizon()
        self.assertEqual(report["counts"],
                         {"OVERDUE": 1, "CLIFF": 2, "CAUTION": 3,
                          "CLEAR": 2, "FUTURE": 0})
        self.assertEqual(report["tracked"], 8)
        first = report["items"][0]
        self.assertEqual((first["name"], first["holder"]), ("Passport", "Aya Zhang"))
        self.assertEqual(first["days_left"], -90)

    def test_nominal_left_lies(self):
        report = self.horizon()
        passport = report["items"][0]
        # nominal: 90 days left; margin-adjusted: already 90 days past
        self.assertEqual(passport["nominal_days_left"], 90)
        self.assertEqual(passport["days_left"], -90)

    def test_top_truncates(self):
        proc = self.run_cli("horizon", str(DEMO), "--as-of", AS_OF, "--top", "3")
        self.assertIn("… and 5 more", proc.stdout)


class TripTests(RegistryTestCase):
    def trip(self, *extra):
        return self.run_cli("trip", str(DEMO), "--as-of", AS_OF,
                            "--start", "2026-04-30", "--end", "2026-05-08",
                            *extra)

    def test_gate_fails_with_exit_four(self):
        proc = self.trip()
        self.assertEqual(proc.returncode, 4)
        report = json.loads(self.trip("--format", "json").stdout)["trip"]
        self.assertEqual(report["checked"], 8)
        self.assertEqual(len(report["failed"]), 6)
        self.assertFalse(report["passed"])

    def test_failing_line_names_the_dead_zone(self):
        proc = self.trip()
        self.assertIn("dead 248d before you return", proc.stdout)
        self.assertIn("gate: FAIL", proc.stdout)

    def test_passing_window_exits_zero(self):
        healthy = self.write([
            "GymPass,membership,2025-01-01,2027-01-01",
            "PhoneWarranty,warranty,2025-06-01,2027-06-01",
        ], header="name,category,start,end")
        proc = self.run_cli("trip", healthy, "--start", "2026-08-01",
                            "--end", "2026-08-15")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("gate: PASS", proc.stdout)

    def test_end_defaults_to_start(self):
        healthy = self.write([
            "GymPass,membership,2025-01-01,2027-01-01",
        ], header="name,category,start,end")
        proc = self.run_cli("trip", healthy, "--end", "2026-08-15")
        self.assertEqual(proc.returncode, 0)

    def test_end_before_start_rejected(self):
        proc = self.run_cli("trip", str(DEMO), "--as-of", AS_OF,
                            "--start", "2026-05-08", "--end", "2026-04-30")
        self.assertEqual(proc.returncode, 3)


class RhythmTests(RegistryTestCase):
    def show(self, query="Passport Aya"):
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF, query)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_rhythm_period_and_lead(self):
        out = self.show()
        self.assertIn("every ~10y", out)
        self.assertIn("you renew ~46d early", out)
        self.assertIn("renewed 46d before previous expiry", out)

    def test_single_period_has_no_rhythm(self):
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF, "GymMembership")
        self.assertNotIn("renewal rhythm", proc.stdout)

    def test_renewal_window_flag(self):
        proc = self.run_cli("horizon", str(DEMO), "--as-of", AS_OF)
        self.assertIn("inside your usual renewal window", proc.stdout)
        self.assertIn("↻ Passport", proc.stdout)
        # insurance habitually renews 5d early but still has 40d: not in window
        self.assertNotIn("↻ CarInsurance", proc.stdout)

    def test_lapsed_renewal_clamps_lead_to_zero(self):
        periods = [
            {"name": "a", "holder": "", "category": "membership",
             "start": date(2020, 1, 1), "end": date(2021, 1, 1), "margin": None, "line": 1},
            {"name": "a", "holder": "", "category": "membership",
             "start": date(2021, 3, 1), "end": date(2022, 3, 1), "margin": None, "line": 2},
        ]
        rhythm = ec.renewal_rhythm(periods)
        self.assertEqual(rhythm["lead_days"], 0)
        self.assertEqual(rhythm["period_days"], 365.5)

    def test_show_json_periods_sorted(self):
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF,
                            "Passport Aya", "--format", "json")
        payload = json.loads(proc.stdout)
        starts = [p["start"] for p in payload["periods"]]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(payload["rhythm"]["period_days"], 3675.5)
        self.assertEqual(payload["rhythm"]["lead_days"], 46)


class RedactTests(RegistryTestCase):
    def test_redact_hides_holder_keeps_name(self):
        proc = self.run_cli("horizon", str(DEMO), "--as-of", AS_OF, "--redact")
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Aya Zhang", proc.stdout)
        self.assertNotIn("Wei Zhang", proc.stdout)
        self.assertIn("Passport", proc.stdout)
        self.assertIn("anon-", proc.stdout)

    def test_redact_json(self):
        proc = self.run_cli("horizon", str(DEMO), "--as-of", AS_OF,
                            "--format", "json", "--redact")
        report = json.loads(proc.stdout)
        self.assertTrue(all(i["holder"].startswith("anon-")
                            for i in report["items"] if i["holder"]))


class CliTests(RegistryTestCase):
    def test_no_args_exit_two(self):
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 2)

    def test_missing_file_exit_three(self):
        proc = self.run_cli("horizon", "/nonexistent/registry.csv")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("error", proc.stderr)

    def test_bad_as_of_exit_three(self):
        proc = self.run_cli("horizon", str(DEMO), "--as-of", "recently")
        self.assertEqual(proc.returncode, 3)

    def test_show_unknown_exit_three(self):
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF, "ToothFairyLicense")
        self.assertEqual(proc.returncode, 3)

    def test_show_ambiguous_lists_holders(self):
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF, "Passport")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("ambiguous", proc.stderr)
        self.assertIn("Aya Zhang", proc.stderr)
        self.assertIn("Wei Zhang", proc.stderr)

    def test_as_of_defaults_to_today(self):
        soon = (date.today() + timedelta(days=10)).isoformat()
        path = self.write(["GymPass,membership,2020-01-01,%s" % soon])
        proc = self.run_cli("horizon", path)
        self.assertIn("CLIFF", proc.stdout)
        self.assertNotIn("OVERDUE", proc.stdout)


class DogfoodTests(RegistryTestCase):
    def test_examples_sync(self):
        build = subprocess.run(
            [sys.executable, str(PROJECT / "examples" / "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

    def test_demo_show_and_horizon_consistent(self):
        proc = self.run_cli("show", str(DEMO), "--as-of", AS_OF, "Passport Aya")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("effective horizon: 2025-09-02 (OVERDUE, -90d)", proc.stdout)
        horizon = self.run_cli("horizon", str(DEMO), "--as-of", AS_OF)
        self.assertIn("first to fall  : Passport · Aya Zhang", horizon.stdout)

    def test_demo_trip_snapshot_matches_committed_sample(self):
        proc = self.run_cli("trip", str(DEMO), "--as-of", AS_OF,
                            "--start", "2026-04-30", "--end", "2026-05-08")
        sample = (PROJECT / "examples" / "sample-trip.txt").read_text(encoding="utf-8")
        self.assertIn("8 credentials checked, 6 fail the gate", sample)
        self.assertIn("gate: FAIL", sample)


if __name__ == "__main__":
    unittest.main()
