#!/usr/bin/env python3
"""Acceptance tests for 种草账 · Want Ledger.

Every acceptance criterion in README.md maps to a test class here.
Synthetic ledgers are written to a scratch dir; the demo reports are the
dogfood and are byte-checked against the delivered CLI. Key demo numbers
(half-life, survival, arm rates, tuition ratio) were hand-counted from the
pinned demo ledger and are re-derived here by explicit arithmetic.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import want_ledger as wl  # noqa: E402

CLI = ROOT / "want_ledger.py"
EXAMPLES = ROOT / "examples"
GRASS = str(EXAMPLES / "grass.csv")
AS_OF = "2026-09-04"
TODAY = "2026-09-04"

# Hand-counted demo ledger facts (see README acceptance table).
DEMO_HALFLIFE = 13.0          # median of [3,8,12,13,14,24,51]
DEMO_SURVIVAL = 4 / 21.0      # 3 resolved-at->=30d + 1 still aged 40d
DEMO_IMULSE_RATE = 6 / 8.0    # impulse arm: 6 of 8 graded regrets
DEMO_DELIB_RATE = 1 / 5.0     # deliberate arm: 1 of 5 graded regrets
DEMO_SPENT = 12717.0
DEMO_TUITION = 5833.0
DEMO_SAVED = 8214.0


def scratch_rows(rows, name="grass.csv"):
    tmp = getattr(scratch_rows, "tmp", None)
    if tmp is None:
        tmp = tempfile.mkdtemp()
        scratch_rows.tmp = tmp
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return path


def run_cli(argv):
    result = subprocess.run(
        [sys.executable, str(CLI)] + argv, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def call_main(argv):
    """Run main() in-process; returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = wl.main(argv)
    return code, out.getvalue(), err.getvalue()


def demo():
    return wl.parse_wants(GRASS)


def report_json(argv=None):
    argv = argv or ["report", GRASS, "--as-of", AS_OF, "--format", "json"]
    code, out, _ = call_main(argv)
    return json.loads(out)


# ---------------------------------------------------------------- parsing

class ParserTests(unittest.TestCase):

    def test_demo_ledger_parses_22_sprouts(self):
        wants = demo()
        self.assertEqual(len(wants), 22)
        self.assertEqual(wants[0].item, "投影仪")

    def test_status_aliases(self):
        path = scratch_rows(["种草日,品名,结局",
                             "2026-01-01,a,拔草",
                             "2026-01-02,b,枯草",
                             "2026-01-03,c,在长",
                             "2026-01-04,d,bought",
                             "2026-01-05,e,passed",
                             "2026-01-06,f"])
        got = [(w.item, w.status) for w in wl.parse_wants(path)]
        self.assertEqual(got, [("a", "BOUGHT"), ("b", "PASSED"),
                               ("c", "STILL"), ("d", "BOUGHT"),
                               ("e", "PASSED"), ("f", "STILL")])

    def test_empty_price_is_none(self):
        path = scratch_rows(["种草日,品名,价位", "2026-01-01,a,"])
        self.assertIsNone(wl.parse_wants(path)[0].price)

    def test_bad_price_refused(self):
        path = scratch_rows(["种草日,品名,价位", "2026-01-01,a,-5"])
        with self.assertRaises(wl.Refuse):
            wl.parse_wants(path)

    def test_bad_status_refused_with_line(self):
        path = scratch_rows(["种草日,品名,结局", "2026-01-01,a,吃土"])
        with self.assertRaises(wl.Refuse) as ctx:
            wl.parse_wants(path)
        self.assertIn("line 2", str(ctx.exception))
        self.assertIn("吃土", str(ctx.exception))

    def test_bad_regret_refused(self):
        path = scratch_rows(["种草日,品名,结局,后悔", "2026-01-01,a,拔草,有点"])
        with self.assertRaises(wl.Refuse):
            wl.parse_wants(path)

    def test_regret_aliases(self):
        path = scratch_rows(["种草日,品名,结局,后悔",
                             "2026-01-01,a,拔草,真后悔",
                             "2026-01-02,b,拔草,不后悔"])
        got = [w.regret for w in wl.parse_wants(path)]
        self.assertEqual(got, [True, False])

    def test_missing_header(self):
        path = scratch_rows(["种草日", "2026-01-01"])
        with self.assertRaises(wl.Refuse) as ctx:
            wl.parse_wants(path)
        self.assertIn("item", str(ctx.exception))

    def test_empty_item_refused(self):
        path = scratch_rows(["种草日,品名", "2026-01-01, "])
        with self.assertRaises(wl.Refuse):
            wl.parse_wants(path)

    def test_blank_rows_tolerated_and_unsorted_sorted(self):
        path = scratch_rows(["种草日,品名", "", "2026-01-01,b", "  ",
                             "2025-01-01,a"])
        wants = wl.parse_wants(path)
        self.assertEqual([w.item for w in wants], ["a", "b"])


# -------------------------------------------------------------- validation

class ValidateTests(unittest.TestCase):

    def test_still_with_resolved_date_refused(self):
        path = scratch_rows(["种草日,品名,结局,结局日",
                             "2026-01-01,a,在长,2026-01-05"])
        with self.assertRaises(wl.Refuse) as ctx:
            wl.validate_wants(wl.parse_wants(path))
        self.assertIn("still growing", str(ctx.exception))

    def test_resolved_without_date_refused(self):
        path = scratch_rows(["种草日,品名,结局", "2026-01-01,a,拔草"])
        with self.assertRaises(wl.Refuse) as ctx:
            wl.validate_wants(wl.parse_wants(path))
        self.assertIn("decision date", str(ctx.exception))

    def test_resolved_before_seed_refused(self):
        path = scratch_rows(["种草日,品名,结局,结局日",
                             "2026-01-10,a,拔草,2026-01-05"])
        with self.assertRaises(wl.Refuse) as ctx:
            wl.validate_wants(wl.parse_wants(path))
        self.assertIn("time travel", str(ctx.exception))

    def test_regret_on_passed_refused(self):
        path = scratch_rows(["种草日,品名,结局,结局日,后悔",
                             "2026-01-01,a,枯草,2026-01-05,y"])
        with self.assertRaises(wl.Refuse) as ctx:
            wl.validate_wants(wl.parse_wants(path))
        self.assertIn("never bought", str(ctx.exception))

    def test_demo_ledger_valid(self):
        wl.validate_wants(demo())  # must not raise


# ----------------------------------------------------------------- census

class CensusTests(unittest.TestCase):

    def test_demo_counts(self):
        data = report_json()
        self.assertEqual(data["wants_seeded"], 22)
        self.assertEqual(data["counts"]["bought"], 13)
        self.assertEqual(data["counts"]["passed"], 7)
        self.assertEqual(data["counts"]["still"], 2)

    def test_demo_half_life(self):
        data = report_json()
        self.assertAlmostEqual(data["half_life_days"], DEMO_HALFLIFE, places=6)
        self.assertEqual(data["half_life_n"], 7)

    def test_half_life_thin(self):
        path = scratch_rows(["种草日,品名,结局,结局日",
                             "2026-01-01,a,枯草,2026-01-04",
                             "2026-01-02,b,拔草,2026-01-03",
                             "2026-01-03,c,枯草,2026-01-10",
                             "2026-01-04,d,拔草,2026-01-05",
                             "2026-01-05,e,拔草,2026-01-06"], "thin-t.csv")
        data = report_json(["report", path, "--format", "json"])
        self.assertIsNone(data["half_life_days"])

    def test_demo_survival(self):
        data = report_json()
        self.assertAlmostEqual(data["survival_30"], DEMO_SURVIVAL, places=6)
        self.assertEqual(data["survival_observable"], 21)

    def test_survival_thin(self):
        # 5 sprouts but only 4 observable at day 30: the fifth is a fresh
        # seedling whose age is 0 at the default as-of (its own seed date).
        rows = ["种草日,品名,结局,结局日,后悔",
                "2026-01-01,a,拔草,2026-01-21,n",
                "2026-01-02,b,拔草,2026-01-22,n",
                "2026-01-03,c,拔草,2026-01-23,n",
                "2026-01-04,d,拔草,2026-01-24,n",
                "2026-06-01,seedling"]
        path = scratch_rows(rows, "thin-s.csv")
        data = report_json(["report", path, "--format", "json"])
        self.assertIsNone(data["survival_30"])
        self.assertEqual(data["survival_observable"], 4)

    def test_time_travel_censors_later_resolutions(self):
        # as-of 2026-03-20: 香薰机 (seed 03-15, resolved 03-29) is a censored
        # still — the census looks exactly as it did that night.
        data = report_json(["report", GRASS, "--as-of", "2026-03-20",
                            "--format", "json"])
        self.assertEqual(data["as_of"], "2026-03-20")
        self.assertEqual(data["wants_seeded"], 13)
        self.assertEqual(data["counts"]["bought"], 8)
        self.assertEqual(data["counts"]["passed"], 4)
        self.assertEqual(data["counts"]["still"], 1)

    def test_asof_before_first_sprout_refused(self):
        code, _, err = call_main(["report", GRASS, "--as-of", "2025-08-01"])
        self.assertEqual(code, 3)
        self.assertIn("first sprout", err)

    def test_default_asof_is_ledger_last_day(self):
        data = report_json(["report", GRASS, "--format", "json"])
        self.assertEqual(data["as_of"], "2026-08-30")

    def test_too_few_sprouts_refused(self):
        path = scratch_rows(["种草日,品名",
                             "2026-01-01,a", "2026-01-02,b",
                             "2026-01-03,c", "2026-01-04,d"], "tiny.csv")
        code, _, err = call_main(["report", path])
        self.assertEqual(code, 3)
        self.assertIn("at least 5", err)


# ------------------------------------------------------------------- arms

class ArmsTests(unittest.TestCase):

    def test_demo_arms(self):
        data = report_json()
        self.assertAlmostEqual(data["arms"]["impulse"]["regret_rate"],
                               DEMO_IMULSE_RATE, places=6)
        self.assertAlmostEqual(data["arms"]["deliberate"]["regret_rate"],
                               DEMO_DELIB_RATE, places=6)
        self.assertEqual(data["arms"]["impulse"]["graded"], 8)
        self.assertEqual(data["arms"]["deliberate"]["graded"], 5)

    def test_seven_day_boundary_is_impulse(self):
        rows = ["种草日,品名,结局,结局日,后悔",
                "2026-01-01,quick,拔草,2026-01-08,n",   # 7 days: impulse
                "2026-01-01,slow,拔草,2026-01-09,n",    # 8 days: deliberate
                "2026-02-01,i2,拔草,2026-02-02,n",
                "2026-02-01,i3,拔草,2026-02-03,n",
                "2026-02-01,i4,拔草,2026-02-04,n",
                "2026-02-01,i5,拔草,2026-02-05,n",
                "2026-02-01,i6,拔草,2026-02-06,n",
                "2026-03-01,d2,拔草,2026-03-15,n",
                "2026-03-01,d3,拔草,2026-03-16,n",
                "2026-03-01,d4,拔草,2026-03-17,n",
                "2026-03-01,d5,拔草,2026-03-18,n",
                "2026-04-01,s,枯草,2026-04-10"]
        path = scratch_rows(rows, "boundary.csv")
        data = report_json(["report", path, "--format", "json"])
        impulse = {w["item"] for w in []}  # placeholder
        self.assertEqual(data["arms"]["impulse"]["bought"], 6)
        self.assertEqual(data["arms"]["deliberate"]["bought"], 5)

    def test_ungraded_regret_excluded_from_rate(self):
        rows = ["种草日,品名,结局,结局日,后悔",
                "2026-01-01,a,拔草,2026-01-02,y",
                "2026-02-01,b,拔草,2026-02-02,"]  # never graded
        path = scratch_rows(rows + ["2026-03-01,c,枯草,2026-03-05",
                                    "2026-03-02,d,拔草,2026-03-03,n",
                                    "2026-03-03,e,拔草,2026-03-04,n",
                                    "2026-03-04,f,拔草,2026-03-05,n",
                                    "2026-03-05,g,拔草,2026-03-06,n",
                                    "2026-03-06,h,拔草,2026-03-20,n"],
                            "ungraded.csv")
        data = report_json(["report", path, "--format", "json"])
        self.assertEqual(data["arms"]["impulse"]["bought"], 6)
        self.assertEqual(data["arms"]["impulse"]["graded"], 5)
        self.assertEqual(data["arms"]["impulse"]["ungraded"], 1)
        self.assertAlmostEqual(data["arms"]["impulse"]["regret_rate"],
                               1 / 5.0, places=6)

    def test_deliberate_worse_flips_verdict_line(self):
        rows = ["种草日,品名,结局,结局日,后悔"]
        for i in range(5):
            rows.append("2026-01-0%d,i%d,拔草,2026-01-0%d,n" % (i + 1, i, i + 2))
        for i in range(5):
            rows.append("2026-02-0%d,d%d,拔草,2026-03-0%d,%s"
                        % (i + 1, i, i + 1, "y" if i < 3 else "n"))
        rows.append("2026-04-01,x,枯草,2026-04-10")
        path = scratch_rows(rows, "slow-worse.csv")
        code, out, _ = call_main(["report", path])
        self.assertEqual(code, 0)
        self.assertIn("waiting is not automatically wisdom", out)
        self.assertIn("0.0%", out)
        self.assertIn("60.0%", out)

    def test_thin_arms_reuse_to_conclude(self):
        rows = ["种草日,品名,结局,结局日,后悔",
                "2026-01-01,a,拔草,2026-01-02,y",
                "2026-01-02,b,拔草,2026-01-03,n",
                "2026-01-03,c,拔草,2026-01-04,n",
                "2026-01-04,d,拔草,2026-01-05,n",
                "2026-01-05,e,拔草,2026-01-06,n"]
        path = scratch_rows(rows, "thin-arms.csv")
        code, out, _ = call_main(["report", path])
        self.assertIn("THIN", out)


# ------------------------------------------------------------------ money

class MoneyTests(unittest.TestCase):

    def test_demo_money(self):
        data = report_json()
        self.assertAlmostEqual(data["money"]["spent"], DEMO_SPENT, places=2)
        self.assertAlmostEqual(data["money"]["tuition"], DEMO_TUITION,
                               places=2)
        self.assertAlmostEqual(data["money"]["saved"], DEMO_SAVED, places=2)
        self.assertAlmostEqual(data["money"]["tuition_ratio_pct"],
                               DEMO_TUITION / DEMO_SPENT * 100, places=3)

    def test_unpriced_bought_excluded_and_disclosed(self):
        rows = ["种草日,品名,价位,结局,结局日,后悔"]
        for i in range(1, 8):
            rows.append("2026-01-%02d,p%d,100,拔草,2026-01-%02d,n"
                        % (i, i, i + 10))
        rows.append("2026-01-08,noprice,,拔草,2026-01-09,n")
        path = scratch_rows(rows, "unpriced-bought.csv")
        data = report_json(["report", path, "--format", "json"])
        self.assertAlmostEqual(data["money"]["spent"], 700.0, places=6)
        self.assertEqual(data["money"]["unpriced"], 1)

    def test_regret_heavy_gate_fires(self):
        rows = ["种草日,品名,价位,结局,结局日,后悔"]
        for i in range(1, 9):  # 8 priced buys, 5 regretted
            rows.append("2026-01-%02d,p%d,100,拔草,2026-01-%02d,%s"
                        % (i, i, i + 10, "y" if i <= 5 else "n"))
        rows.append("2026-02-01,x,200,枯草,2026-02-10,")
        path = scratch_rows(rows, "heavy.csv")
        code, out, _ = call_main(["report", path])
        self.assertEqual(code, 4)
        self.assertIn("REGRET-HEAVY", out)
        self.assertIn("62.5%", out)

    def test_gate_needs_eight_priced_buys(self):
        rows = ["种草日,品名,价位,结局,结局日,后悔"]
        for i in range(1, 8):  # only 7 priced buys, all regretted
            rows.append("2026-01-%02d,p%d,100,拔草,2026-01-%02d,y"
                        % (i, i, i + 10))
        rows.append("2026-02-01,x,200,枯草,2026-02-10,")
        path = scratch_rows(rows, "notyet.csv")
        code, out, _ = call_main(["report", path])
        self.assertEqual(code, 0)
        self.assertIn("SETTLED", out)

    def test_tuition_line_override(self):
        code, _, _ = call_main(["report", GRASS, "--as-of", AS_OF,
                                "--tuition-line", "50"])
        self.assertEqual(code, 0)  # 45.9% is inside a 50% line

    def test_demo_verdict_regret_heavy_exit_4(self):
        code, out, _ = call_main(["report", GRASS, "--as-of", AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("REGRET-HEAVY", out)
        self.assertIn("45.9%", out)
        self.assertIn("13.0 days", out)
        self.assertIn("19.0% of wants live past day 30", out)
        self.assertIn("8,214.00", out)


# ------------------------------------------------------------------ check

class CheckTests(unittest.TestCase):

    def test_cooling_blocks_young_sprout(self):
        code, out, _ = call_main(["check", GRASS, "--item", "机械键盘",
                                  "--price", "899", "--seeded", "2026-09-01",
                                  "--today", TODAY])
        self.assertEqual(code, 4)
        self.assertIn("STILL COOLING", out)
        self.assertIn("2026-09-15", out)
        self.assertIn("19.0%", out)

    def test_cooled_sprout_gets_the_evidence(self):
        code, out, _ = call_main(["check", GRASS, "--item", "机械键盘",
                                  "--price", "899", "--seeded", "2026-08-10",
                                  "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("DECIDE NOW", out)
        self.assertIn("impulse regret 75.0% (n=8)", out)
        self.assertIn("tuition 45.9% of spending", out)

    def test_cool_override_flips_verdict(self):
        code, out, _ = call_main(["check", GRASS, "--item", "x",
                                  "--seeded", "2026-09-01",
                                  "--today", TODAY, "--cool", "2"])
        self.assertEqual(code, 0)
        self.assertIn("DECIDE NOW", out)

    def test_today_before_seeded_refused(self):
        code, _, err = call_main(["check", GRASS, "--item", "x",
                                  "--seeded", "2026-09-04",
                                  "--today", "2026-09-01"])
        self.assertEqual(code, 3)
        self.assertIn("before it is planted", err)

    def test_check_does_not_mutate_the_ledger(self):
        before = Path(GRASS).read_text(encoding="utf-8")
        call_main(["check", GRASS, "--item", "新草", "--price", "99",
                   "--seeded", "2026-09-01", "--today", TODAY])
        self.assertEqual(Path(GRASS).read_text(encoding="utf-8"), before)

    def test_check_json(self):
        code, out, _ = call_main(["check", GRASS, "--item", "机械键盘",
                                  "--seeded", "2026-09-01", "--today", TODAY,
                                  "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["verdict"], "STILL_COOLING")
        self.assertEqual(data["age_days"], 3)
        self.assertEqual(data["due"], "2026-09-15")


# ----------------------------------------------------------------- doctor

class DoctorTests(unittest.TestCase):

    def test_demo_healthy(self):
        code, out, _ = call_main(["doctor", GRASS])
        self.assertEqual(code, 0)
        self.assertIn("HEALTHY", out)

    def test_ungraded_regret_warns(self):
        rows = ["种草日,品名,结局,结局日,后悔"]
        for i in range(1, 6):
            suffix = ",y" if i == 1 else ""
            rows.append("2026-01-%02d,p%d,拔草,2026-01-2%d%s"
                        % (i, i, i, suffix))
        rows.append("2026-02-01,x,枯草,2026-02-05,")
        path = scratch_rows(rows, "d-ungraded.csv")
        code, out, _ = call_main(["doctor", path])
        self.assertEqual(code, 0)
        self.assertIn("USABLE WITH NOTES", out)
        self.assertIn("missing lab result", out)

    def test_unpriced_bought_warns(self):
        rows = ["种草日,品名,价位,结局,结局日,后悔"]
        for i in range(1, 6):
            rows.append("2026-01-%02d,p%d,100,拔草,2026-01-2%d,n"
                        % (i, i, i))
        rows.append("2026-02-01,free,,拔草,2026-02-02,n")
        path = scratch_rows(rows, "d-unpriced.csv")
        code, out, _ = call_main(["doctor", path])
        self.assertIn("tuition bill cannot count it", out)

    def test_duplicate_seed_warns(self):
        rows = ["种草日,品名,价位,结局,结局日,后悔"]
        for i in range(1, 5):
            rows.append("2026-01-%02d,p%d,100,拔草,2026-01-2%d,n"
                        % (i, i, i))
        rows.append("2026-02-01,dup,200,枯草,2026-02-05,")
        rows.append("2026-02-01,dup,200,枯草,2026-02-06,")
        path = scratch_rows(rows, "d-dup.csv")
        code, out, _ = call_main(["doctor", path])
        self.assertIn("appears 2 times", out)

    def test_thin_ledger_fatal(self):
        path = scratch_rows(["种草日,品名",
                             "2026-01-01,a", "2026-01-02,b",
                             "2026-01-03,c", "2026-01-04,d"], "d-thin.csv")
        code, out, _ = call_main(["doctor", path])
        self.assertEqual(code, 3)
        self.assertIn("UNHEALTHY", out)

    def test_doctor_json(self):
        code, out, _ = call_main(["doctor", GRASS, "--format", "json"])
        data = json.loads(out)
        self.assertTrue(data["healthy"])
        self.assertEqual(data["wants"], 22)


# -------------------------------------------------------------------- CLI

class CliTests(unittest.TestCase):

    def test_no_args_exits_2(self):
        code, _, _ = call_main([])
        self.assertEqual(code, 2)

    def test_missing_file_exits_3(self):
        code, _, err = call_main(["report", "/no/such/grass.csv"])
        self.assertEqual(code, 3)
        self.assertIn("file not found", err)

    def test_check_required_args(self):
        result = subprocess.run(
            [sys.executable, str(CLI), "check", GRASS],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_report_json_never_gates(self):
        code, out, _ = call_main(["report", GRASS, "--as-of", AS_OF,
                                  "--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["verdict"], "REGRET-HEAVY")

    def test_check_json_never_gates(self):
        code, out, _ = call_main(["check", GRASS, "--item", "x",
                                  "--seeded", "2026-09-01",
                                  "--today", TODAY, "--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["verdict"], "STILL_COOLING")


# ---------------------------------------------------------------- dogfood

class DogfoodTests(unittest.TestCase):

    def test_examples_in_sync(self):
        script = EXAMPLES / "build_examples.py"
        result = subprocess.run(
            [sys.executable, str(script), "--check"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("in sync"), 4)

    def test_report_snapshot_pins_the_story(self):
        text = (EXAMPLES / "sample-report.txt").read_text(encoding="utf-8")
        for needle in ("REGRET-HEAVY", "13.0 days", "19.0%",
                       "75.0% regret it", "20.0% regret it",
                       "5,833.00 bought in regret",
                       "8,214.00 of wants you let die",
                       "tuition 2,999.00"):
            self.assertIn(needle, text)

    def test_check_snapshots_pin_both_sides_of_the_gate(self):
        cooling = (EXAMPLES / "sample-check-cooling.txt").read_text(
            encoding="utf-8")
        self.assertIn("verdict: STILL COOLING", cooling)
        self.assertIn("Come back on 2026-09-15", cooling)
        decide = (EXAMPLES / "sample-check-decide.txt").read_text(
            encoding="utf-8")
        self.assertIn("verdict: DECIDE NOW", decide)
        self.assertIn("the vote is yours", decide)

    def test_doctor_snapshot_healthy(self):
        text = (EXAMPLES / "sample-doctor.txt").read_text(encoding="utf-8")
        self.assertIn("HEALTHY", text)

    def test_demo_numbers_match_independent_math(self):
        data = report_json()
        self.assertAlmostEqual(data["half_life_days"], DEMO_HALFLIFE,
                               places=6)
        self.assertAlmostEqual(data["survival_30"], 0.190476, places=5)
        self.assertAlmostEqual(data["arms"]["impulse"]["regret_rate"], 0.75,
                               places=6)
        self.assertAlmostEqual(data["money"]["tuition_ratio_pct"], 45.8677,
                               places=3)


if __name__ == "__main__":
    unittest.main()
