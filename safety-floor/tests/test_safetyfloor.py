#!/usr/bin/env python3
"""Acceptance tests for 兜底 · Safety Floor.

Every acceptance criterion in README.md maps to a test class here.
Synthetic ledgers are written to a temp dir; the demo reports are the
dogfood and are byte-checked against the delivered CLI.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import safety_floor as sf  # noqa: E402

CLI = ROOT / "safety_floor.py"
EXAMPLES = ROOT / "examples"
FAMILY = str(EXAMPLES / "family.csv")
POLICIES = str(EXAMPLES / "policies.csv")
EXPENSE = ["--expense", "200000"]

# Demo ledger expectations (hand-derived, see README sample section).
DEM_TOTAL_PREMIUM = 14043.0
DEM_RATIO = 14043.0 / 450000.0        # 3.12%
DEM_SAVINGS_RATIO = 8000.0 / 14043.0  # 57.0%

TMP = None


def scratch():
    global TMP
    if TMP is None:
        TMP = tempfile.mkdtemp()
    return TMP


def write_csv(name, rows):
    path = os.path.join(scratch(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return path


def call_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = sf.main(argv)
    return code, out.getvalue(), err.getvalue()


def demo_matrix():
    members = sf.parse_family(FAMILY)
    policies = sf.parse_policies(POLICIES, members)
    return members, policies, sf.build_matrix(
        members, policies, 200000.0, sf.DEFAULT_LIFE_YEARS,
        sf.DEFAULT_CI_YEARS, sf.DEFAULT_MEDICAL_FLOOR,
        sf.DEFAULT_ACCIDENT_YEARS, sf.DEFAULT_ACCIDENT_FLAT)


# ---------------------------------------------------------------- parsing

class ParserTests(unittest.TestCase):

    def test_chinese_headers_and_roles(self):
        members = sf.parse_family(FAMILY)
        self.assertEqual([m.name for m in members],
                         ["陈小明", "林悦", "陈小满", "陈母"])
        self.assertEqual([m.role for m in members],
                         ["beam", "spouse", "child", "elder"])
        self.assertEqual(members[0].income, 300000.0)
        self.assertEqual(members[2].income, 0.0)

    def test_english_headers_and_aliases(self):
        fam = write_csv("fam-en.csv",
                        ["name,role,income", "Chen,pillar,300000",
                         "Kid,kid,0"])
        pol = write_csv("pol-en.csv",
                        ["policy,insured,type,coverage,premium",
                         "term,Chen,life,2000000,1800",
                         "ci-rider,Kid,critical,300000,900"])
        members = sf.parse_family(fam)
        policies = sf.parse_policies(pol, members)
        self.assertEqual(members[0].role, "beam")
        self.assertEqual(policies[0].type, "life")
        self.assertEqual(policies[1].type, "ci")

    def test_role_alias_taitai(self):
        fam = write_csv("fam-tt.csv", ["成员,角色,年收入",
                                       "张三,顶梁柱,100000",
                                       "李四,太太,80000"])
        self.assertEqual([m.role for m in sf.parse_family(fam)],
                         ["beam", "spouse"])

    def test_type_alias_jiaoyujin_is_other(self):
        fam = write_csv("fam-o.csv", ["成员,角色,年收入", "张三,成人,100000"])
        pol = write_csv("pol-o.csv", ["保单,被保人,险种,保额,年保费",
                                      "成长年金,张三,教育金,0,8000"])
        policies = sf.parse_policies(pol, sf.parse_family(fam))
        self.assertEqual(policies[0].type, "other")

    def test_income_optional_defaults_zero(self):
        fam = write_csv("fam-i.csv", ["成员,角色", "张三,成人"])
        self.assertEqual(sf.parse_family(fam)[0].income, 0.0)

    def test_coverage_and_premium_optional(self):
        fam = write_csv("fam-c.csv", ["成员,角色,年收入", "张三,成人,100000"])
        pol = write_csv("pol-c.csv", ["保单,被保人,险种",
                                      "团意,张三,意外"])
        p = sf.parse_policies(pol, sf.parse_family(fam))[0]
        self.assertEqual(p.coverage, 0.0)
        self.assertEqual(p.premium, 0.0)

    def test_negative_coverage_refused(self):
        fam = write_csv("fam-n.csv", ["成员,角色,年收入", "张三,成人,100000"])
        pol = write_csv("pol-n.csv", ["保单,被保人,险种,保额,年保费",
                                      "x,张三,意外,-5,0"])
        with self.assertRaises(sf.Refuse) as ctx:
            sf.parse_policies(pol, sf.parse_family(fam))
        self.assertIn("line 2", str(ctx.exception))

    def test_unknown_insured_refused(self):
        fam = write_csv("fam-u.csv", ["成员,角色,年收入", "张三,成人,100000"])
        pol = write_csv("pol-u.csv", ["保单,被保人,险种,保额,年保费",
                                      "x,路人,意外,100,0"])
        with self.assertRaises(sf.Refuse) as ctx:
            sf.parse_policies(pol, sf.parse_family(fam))
        self.assertIn("not in family", str(ctx.exception))

    def test_duplicate_member_refused(self):
        fam = write_csv("fam-d.csv", ["成员,角色,年收入", "张三,成人,1",
                                      "张三,孩子,0"])
        with self.assertRaises(sf.Refuse):
            sf.parse_family(fam)

    def test_unknown_role_refused(self):
        fam = write_csv("fam-r.csv", ["成员,角色,年收入", "张三,房东,1"])
        with self.assertRaises(sf.Refuse) as ctx:
            sf.parse_family(fam)
        self.assertIn("unknown role", str(ctx.exception))

    def test_unknown_type_refused(self):
        fam = write_csv("fam-t.csv", ["成员,角色,年收入", "张三,成人,1"])
        pol = write_csv("pol-t.csv", ["保单,被保人,险种,保额,年保费",
                                      "x,张三,航班延误险,100,0"])
        with self.assertRaises(sf.Refuse) as ctx:
            sf.parse_policies(pol, sf.parse_family(fam))
        self.assertIn("unknown policy type", str(ctx.exception))

    def test_blank_rows_tolerated(self):
        fam = write_csv("fam-b.csv", ["成员,角色,年收入", "",
                                      "张三,成人,1", "  "])
        self.assertEqual(len(sf.parse_family(fam)), 1)


# ----------------------------------------------------------------- targets

class TargetTests(unittest.TestCase):

    def test_life_is_income_times_years(self):
        members, _, matrix = demo_matrix()
        self.assertEqual(matrix["陈小明"]["life"]["target"], 3000000.0)
        self.assertEqual(matrix["林悦"]["life"]["target"], 1500000.0)

    def test_zero_income_no_life_target(self):
        m = sf.Member("老王", "adult", 0.0)
        self.assertEqual(sf.life_target(m, 10), 0.0)

    def test_child_and_elder_have_no_life_target(self):
        _, _, matrix = demo_matrix()
        self.assertEqual(matrix["陈小满"]["life"]["target"], 0.0)
        self.assertIsNone(matrix["陈小满"]["life"]["status"])
        self.assertIsNone(matrix["陈母"]["life"]["status"])

    def test_ci_is_expense_times_years_for_everyone(self):
        _, _, matrix = demo_matrix()
        for name in ("陈小明", "林悦", "陈小满", "陈母"):
            self.assertEqual(matrix[name]["ci"]["target"], 600000.0)

    def test_accident_is_max_income_times_flat(self):
        _, _, matrix = demo_matrix()
        self.assertEqual(matrix["陈小明"]["accident"]["target"], 1500000.0)
        self.assertEqual(matrix["陈小满"]["accident"]["target"], 200000.0)
        self.assertEqual(matrix["陈母"]["accident"]["target"], 200000.0)

    def test_overrides_win(self):
        code, out, _ = call_main(["report", FAMILY, POLICIES, "--expense",
                                  "200000", "--life-years", "8",
                                  "--ci-years", "5", "--medical-floor",
                                  "2000000", "--accident-flat", "500000"])
        self.assertEqual(code, 4)
        self.assertIn("0/2.40M", out)       # chen life 300k x 8
        self.assertIn("0/1.00M", out)       # ci 200k x 5, bare on the beam
        # kid medical 1,000,000 now below the raised floor -> BARE
        self.assertIn("BARE    1.00M/2.00M", out)
        # mom accident 200,000 under the raised flat floor 500,000 -> THIN
        self.assertIn("THIN    200k/500k", out)

    def test_missing_expense_refused(self):
        code, _, err = call_main(["report", FAMILY, POLICIES])
        self.assertEqual(code, 3)
        self.assertIn("--expense is required", err)

    def test_negative_expense_refused(self):
        code, _, err = call_main(["report", FAMILY, POLICIES,
                                  "--expense", "-1"])
        self.assertEqual(code, 3)
        self.assertIn("> 0", err)


# ------------------------------------------------------------------ matrix

class MatrixTests(unittest.TestCase):

    def test_demo_cells(self):
        _, _, matrix = demo_matrix()
        self.assertEqual(matrix["陈小明"]["life"]["status"], "BARE")
        self.assertEqual(matrix["陈小明"]["accident"]["status"], "THIN")
        self.assertEqual(matrix["林悦"]["ci"]["status"], "THIN")
        self.assertEqual(matrix["陈小满"]["ci"]["status"], "SHORT")
        self.assertEqual(matrix["陈母"]["accident"]["status"], "COVERED")

    def test_ladder_boundaries(self):
        self.assertEqual(sf.coverage_status("ci", 0, 100, 1000), "BARE")
        self.assertEqual(sf.coverage_status("ci", 299999, 600000, 1000),
                         "THIN")
        self.assertEqual(sf.coverage_status("ci", 300000, 600000, 1000),
                         "SHORT")
        self.assertEqual(sf.coverage_status("ci", 600000, 600000, 1000),
                         "COVERED")

    def test_medical_is_binary(self):
        self.assertEqual(sf.coverage_status("medical", 1000000, 1000000,
                                            1000000), "COVERED")
        self.assertEqual(sf.coverage_status("medical", 999999, 1000000,
                                            1000000), "BARE")
        self.assertEqual(sf.coverage_status("medical", 5000000, 1000000,
                                            1000000), "COVERED")

    def test_savings_type_excluded_from_matrix(self):
        _, _, matrix = demo_matrix()
        # 成长年金 (other, coverage 0) must not turn kid ci into anything
        self.assertEqual(matrix["陈小满"]["ci"]["have"], 500000.0)

    def test_beam_first_in_matrix(self):
        code, out, _ = call_main(["report", FAMILY, POLICIES] + EXPENSE)
        beam_line = out.index("陈小明")
        kid_line = out.index("陈小满")
        self.assertLess(beam_line, kid_line)

    def test_multiple_policies_same_peril_sum(self):
        fam = write_csv("fam-sum.csv", ["成员,角色,年收入", "张三,成人,100000"])
        pol = write_csv("pol-sum.csv",
                        ["保单,被保人,险种,保额,年保费",
                         "a,张三,重疾,200000,500", "b,张三,重疾,300000,500"])
        members = sf.parse_family(fam)
        matrix = sf.build_matrix(members, sf.parse_policies(pol, members),
                                 100000.0, 10, 3, 1000000, 5, 200000)
        self.assertEqual(matrix["张三"]["ci"]["have"], 500000.0)


# ----------------------------------------------------------------- premium

class PremiumTests(unittest.TestCase):

    def test_demo_premium_ledger(self):
        members = sf.parse_family(FAMILY)
        prem = sf.premium_ledger(members, sf.parse_policies(POLICIES,
                                                            members))
        self.assertEqual(prem["total"], DEM_TOTAL_PREMIUM)
        self.assertAlmostEqual(prem["ratio"], DEM_RATIO, places=6)
        self.assertAlmostEqual(prem["savings_ratio"], DEM_SAVINGS_RATIO,
                               places=6)
        self.assertEqual(prem["by_member"]["陈小满"], 9876.0)

    def test_ratio_tiers(self):
        fam = write_csv("fam-p.csv", ["成员,角色,年收入", "张三,成人,100000"])

        def pol(premium):
            return write_csv("pol-p-%s.csv" % premium,
                             ["保单,被保人,险种,保额,年保费",
                              "x,张三,意外,500000,%s" % premium])

        code, out, _ = call_main(["premium", fam, pol(10000)])
        self.assertIn("· OK", out)
        code, out, _ = call_main(["premium", fam, pol(15000)])
        self.assertIn("· TIGHT", out)
        code, out, _ = call_main(["premium", fam, pol(15001)])
        self.assertIn("· OVERPAY", out)
        self.assertEqual(code, 4)

    def test_report_overpay_exits_4_independently(self):
        fam = write_csv("fam-op.csv", ["成员,角色,年收入", "张三,成人,100000"])
        pol = write_csv("pol-op.csv",
                        ["保单,被保人,险种,保额,年保费",
                         "x,张三,意外,500000,18000"])
        code, out, _ = call_main(["report", fam, pol, "--expense", "100000"])
        self.assertEqual(code, 4)
        self.assertIn("OVERPAID", out)

    def test_zero_income_no_ratio_judgment(self):
        fam = write_csv("fam-z.csv", ["成员,角色,年收入", "张三,成人,0"])
        pol = write_csv("pol-z.csv", ["保单,被保人,险种,保额,年保费",
                                      "x,张三,意外,500000,500"])
        code, out, _ = call_main(["premium", fam, pol])
        self.assertEqual(code, 0)
        self.assertIn("no income denominator", out)


# -------------------------------------------------------------------- gaps

class GapsTests(unittest.TestCase):

    def test_demo_order(self):
        members, _, matrix = demo_matrix()
        gaps = sf.gap_list(members, matrix)
        got = [(g["member"], g["peril"]) for g in gaps]
        self.assertEqual(got[:4], [("陈小明", "life"), ("陈小明", "ci"),
                                   ("林悦", "life"), ("林悦", "accident")])
        self.assertEqual(got[-1], ("陈小满", "ci"))

    def test_status_beats_role_beats_gap(self):
        fam = write_csv("fam-g.csv",
                        ["成员,角色,年收入", "张三,成人,100000",
                         "小李,顶梁柱,200000"])
        pol = write_csv("pol-g.csv",
                        ["保单,被保人,险种,保额,年保费",
                         "a,小李,意外,0,0",       # beam BARE gap 1,000,000
                         "b,张三,重疾,0,0",        # adult BARE gap 300,000
                         "c,小李,重疾,100000,0",   # beam THIN gap 200,000
                         "d,小李,寿险,2000000,0",
                         "e,小李,医疗,1000000,0",
                         "f,张三,寿险,1000000,0",
                         "g,张三,医疗,1000000,0",
                         "h,张三,意外,500000,0"])
        members = sf.parse_family(fam)
        matrix = sf.build_matrix(members, sf.parse_policies(pol, members),
                                 100000.0, 10, 3, 1000000, 5, 200000)
        gaps = sf.gap_list(members, matrix)
        got = [(g["member"], g["peril"], g["status"]) for g in gaps]
        # BARE beam first (bigger gap first), then BARE adult, then THIN beam
        self.assertEqual(got, [("小李", "accident", "BARE"),
                               ("张三", "ci", "BARE"),
                               ("小李", "ci", "THIN")])

    def test_empty_gap_list_when_solid(self):
        fam = write_csv("fam-s.csv", ["成员,角色,年收入", "张三,成人,100000"])
        pol = write_csv("pol-s.csv",
                        ["保单,被保人,险种,保额,年保费",
                         "life,张三,寿险,1000000,500",
                         "ci,张三,重疾,300000,500",
                         "med,张三,医疗,1000000,300",
                         "acc,张三,意外,500000,200"])
        code, out, _ = call_main(["gaps", fam, pol, "--expense", "100000"])
        self.assertEqual(code, 0)
        self.assertIn("nothing below target", out)


# ----------------------------------------------------------------- verdict

class VerdictTests(unittest.TestCase):

    def test_demo_exposed_exit_4(self):
        code, out, _ = call_main(["report", FAMILY, POLICIES] + EXPENSE)
        self.assertEqual(code, 4)
        self.assertIn("EXPOSED", out)
        self.assertIn("life (0 of 3,000,000)", out)

    def test_solid_exit_0(self):
        fam = write_csv("fam-so.csv", ["成员,角色,年收入", "张三,成人,100000"])
        pol = write_csv("pol-so.csv",
                        ["保单,被保人,险种,保额,年保费",
                         "life,张三,寿险,1000000,500",
                         "ci,张三,重疾,300000,500",
                         "med,张三,医疗,1000000,300",
                         "acc,张三,意外,500000,200"])
        code, out, _ = call_main(["report", fam, pol, "--expense", "100000"])
        self.assertEqual(code, 0)
        self.assertIn("SOLID", out)

    def test_cracked_without_bare_exit_0(self):
        fam = write_csv("fam-cr.csv", ["成员,角色,年收入", "张三,成人,100000"])
        pol = write_csv("pol-cr.csv",
                        ["保单,被保人,险种,保额,年保费",
                         "life,张三,寿险,1000000,500",
                         "ci,张三,重疾,200000,500",     # SHORT
                         "med,张三,医疗,1000000,300",
                         "acc,张三,意外,500000,200"])
        code, out, _ = call_main(["report", fam, pol, "--expense", "100000"])
        self.assertEqual(code, 0)
        self.assertIn("CRACKED", out)

    def test_child_bare_never_gates(self):
        fam = write_csv("fam-kb.csv",
                        ["成员,角色,年收入", "张三,成人,100000",
                         "娃,孩子,0"])
        pol = write_csv("pol-kb.csv",
                        ["保单,被保人,险种,保额,年保费",
                         "life,张三,寿险,1000000,500",
                         "ci,张三,重疾,300000,500",
                         "med,张三,医疗,1000000,300",
                         "acc,张三,意外,500000,200",
                         "kidmed,娃,医疗,1000000,300",
                         "kidacc,娃,意外,0,0"])       # child accident BARE
        code, out, _ = call_main(["report", fam, pol, "--expense", "100000"])
        self.assertEqual(code, 0)
        self.assertNotIn("EXPOSED", out)
        self.assertIn("CRACKED", out)

    def test_two_bare_perils_listed(self):
        code, out, _ = call_main(["report", FAMILY, POLICIES] + EXPENSE)
        self.assertIn("life (0 of 3,000,000), ci (0 of 600,000)", out)


# ---------------------------------------------------------------------- CLI

class CliTests(unittest.TestCase):

    def test_no_args_exits_2(self):
        code, _, _ = call_main([])
        self.assertEqual(code, 2)

    def test_missing_file_exits_3(self):
        code, _, err = call_main(["report", "/no/such.csv", POLICIES,
                                  "--expense", "1"])
        self.assertEqual(code, 3)
        self.assertIn("file not found", err)

    def test_premium_needs_no_expense(self):
        code, out, _ = call_main(["premium", FAMILY, POLICIES])
        self.assertEqual(code, 0)
        self.assertIn("3.1% of income", out)

    def test_report_json(self):
        code, out, _ = call_main(["report", FAMILY, POLICIES, "--expense",
                                  "200000", "--format", "json"])
        self.assertEqual(code, 0)  # JSON is data, never a gate
        data = json.loads(out)
        self.assertEqual(data["verdict"], "EXPOSED")
        self.assertEqual(data["bare_beam"],
                         [{"member": "陈小明",
                           "perils": ["life", "ci"]}])
        self.assertAlmostEqual(data["premium"]["ratio"], DEM_RATIO, places=4)
        self.assertAlmostEqual(data["premium"]["savings_ratio"],
                               DEM_SAVINGS_RATIO, places=4)
        self.assertEqual(data["matrix"]["陈小明"]["life"]["target"], 3000000.0)


# ------------------------------------------------------------------ dogfood

class DogfoodTests(unittest.TestCase):

    def test_examples_in_sync(self):
        script = EXAMPLES / "build_examples.py"
        result = subprocess.run(
            [sys.executable, str(script), "--check"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("in sync"), 3)

    def test_report_snapshot_pins_the_story(self):
        text = (EXAMPLES / "sample-report.txt").read_text(encoding="utf-8")
        for needle in ("EXPOSED", "0/3.00M", "0/600k", "THIN    100k/1.50M",
                       "3.1% of income · OK",
                       "57.0% of every premium yuan",
                       "陈小满 70.3%", "exit 4"):
            self.assertIn(needle, text)

    def test_gaps_snapshot_pins_order(self):
        text = (EXAMPLES / "sample-gaps.txt").read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        first = [ln for ln in lines if "陈小明" in ln and "life" in ln][0]
        self.assertIn("3,000,000", first)
        self.assertLess(lines.index(first),
                        text.index("林悦"))

    def test_premium_snapshot_pins_feeds(self):
        text = (EXAMPLES / "sample-premium.txt").read_text(encoding="utf-8")
        for needle in ("14,043/yr", "57.0%", "陈小满 70.3%", "other 8,000"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
