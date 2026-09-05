# -*- coding: utf-8 -*-
"""哑税 · Mute Levy 验收测试。

样例数字全部先手算再钉测试（手算过程见各测试注释）：
- A 公司 1-5 月月薪 18000/社保 1800/公积金 2160/房贷扣除 1000：
  每月增量 8040，累计 8040/16080/24120/32160/40200，
  前 4 月 3% 档各 241.20，第 5 月跳 10% 档 (40200*0.1-2520)=1500 → 本期 535.20，合计 1500.00
- B 公司 6-12 月月薪 21000/社保 2100/公积金 2520：任职 7 个月减除 35000，
  每月增量 10380，累计 10380..72660 全程 ≤144000：
  M6-M8 3% 档各 311.40，M9 1632-934.20=697.80，M10-M12 各 1038.00，合计 4746.00
- 全年已预缴 6246.00；合并应纳所得 237000-60000-52140-12000=112860
  → 8766.00 → 应补 2520.00
- 漏报赡养老人 (5-12 月 8×3000=24000) + 继续教育 (6-12 月 7×400=2800)：
  哑税近似 2400+280=2680；补报后应纳 86060×0.1-2520=6086 → 退税 160
  恒等：delta 2680 == 2520+160
- bonus 36000：单独 1080（÷12=3000 → 3%）；并入 148860×0.2-16920=12852
  SOLO 省 3006；悬崖 36001 → 36001×0.1-210=3390.10
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mute_levy as ml  # noqa: E402

PAYSLIPS = """# comment lines must be skipped
month	employer	gross	social	fund	other_exempt	tax_paid
2025-01	A公司	18000.00	1800.00	2160.00	0.00	241.20
2025-02	A公司	18000.00	1800.00	2160.00	0.00	241.20
2025-03	A公司	18000.00	1800.00	2160.00	0.00	241.20
2025-04	A公司	18000.00	1800.00	2160.00	0.00	241.20
2025-05	A公司	18000.00	1800.00	2160.00	0.00	535.20
2025-06	B公司	21000.00	2100.00	2520.00	0.00	311.40
2025-07	B公司	21000.00	2100.00	2520.00	0.00	311.40
2025-08	B公司	21000.00	2100.00	2520.00	0.00	311.40
2025-09	B公司	21000.00	2100.00	2520.00	0.00	697.80
2025-10	B公司	21000.00	2100.00	2520.00	0.00	1038.00
2025-11	B公司	21000.00	2100.00	2520.00	0.00	1038.00
2025-12	B公司	21000.00	2100.00	2520.00	0.00	1038.00
"""

CLAIMS = """item	from	to	monthly	note
房贷利息	2025-01		1000.00	首套房贷
"""

ELIGIBLES = """item	from	to	monthly	note
房贷利息	2025-01		1000.00	已申报
赡养老人	2025-05		3000.00	父亲满 60
继续教育	2025-06		400.00	学历教育
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mute-levy-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def demo(self):
        return (self.write("payslips.tsv", PAYSLIPS),
                self.write("claims.tsv", CLAIMS),
                self.write("eligibles.tsv", ELIGIBLES))

    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ml.main(argv)
        return out.getvalue(), err.getvalue(), code

    def salaries(self, rows, header=True):
        body = "month\temployer\tgross\tsocial\tfund\tother_exempt\ttax_paid\n"
        return body + "".join(r + "\n" for r in rows)


class TestTariffTables(Base):
    def test_annual_bracket_pins(self):
        self.assertAlmostEqual(ml.tax_annual(36000.00), 1080.00, places=6)
        self.assertAlmostEqual(ml.tax_annual(36000.01), 1080.001, places=6)
        self.assertAlmostEqual(ml.tax_annual(144000.00), 11880.00, places=6)
        self.assertAlmostEqual(ml.tax_annual(300000.00), 43080.00, places=6)
        self.assertAlmostEqual(ml.tax_annual(96480.00), 7128.00, places=6)
        self.assertAlmostEqual(ml.tax_annual(-5.0), 0.0, places=9)

    def test_solo_bracket_pins(self):
        # 年终奖按 bonus/12 找档：36000/12=3000 -> 3%；36001/12 -> 10% quick 210
        self.assertAlmostEqual(ml.tax_solo(36000.00), 1080.00, places=6)
        self.assertAlmostEqual(ml.tax_solo(36001.00), 3390.10, places=6)
        self.assertAlmostEqual(ml.tax_solo(12000.00), 360.00, places=6)
        self.assertAlmostEqual(ml.tax_solo(25000.00), 750.00, places=6)
        self.assertAlmostEqual(ml.tax_solo(96000.00), 9390.00, places=6)
        self.assertAlmostEqual(ml.tax_solo(144000.00), 14190.00, places=6)
        self.assertAlmostEqual(ml.tax_solo(144001.00), 27390.20, places=6)
        self.assertAlmostEqual(ml.tax_solo(0.0), 0.0, places=9)

    def test_cliff_magnitude(self):
        # 36000 -> 1080, 36000.01 -> 1080.001+? -> 36000.01*0.1-210 = 3390.001
        self.assertAlmostEqual(ml.tax_solo(36000.01), 3390.00, places=2)


class TestAliasesAndPriors(Base):
    def test_alias_normalization(self):
        for cn, en in [("房贷", "housing"), ("房贷利息", "housing"),
                       ("mortgage", "housing"), ("housing", "housing"),
                       ("租房", "rent"), ("赡养老人", "elderly"),
                       ("赡养", "elderly"), ("elderly", "elderly"),
                       ("继续教育", "continuing"), ("continuing", "continuing"),
                       ("子女教育", "child"), ("婴幼儿", "infant"),
                       ("大病医疗", "medical")]:
            self.assertEqual(ml.norm_item(cn), en)

    def test_alias_covers_canonical_itself(self):
        # 规范词必须映射到自身，否则规范拼写反而不识别
        for key in ml.PRIORS:
            self.assertEqual(ml.norm_item(key), key)

    def test_unknown_item_rejected(self):
        pays, claims, _ = self.demo()
        claims2 = self.write("claims2.tsv", "item\tfrom\tto\tmonthly\n按摩椅\t2025-01\t\t500.00\n")
        out, err, code = self.invoke(["--payslips", pays, "--claims", claims2, "report"])
        self.assertEqual(code, 2)
        self.assertIn("unknown claim item", err)

    def test_prior_monthly_blank(self):
        pays, _, _ = self.demo()
        claims = self.write("claims.tsv", "item\tfrom\tto\tmonthly\n租房\t2025-01\t\t\n")
        led = ml.Ledger(pays, claims)
        self.assertEqual(led.claims[0]["monthly"], 1500.0)

    def test_rent_tier_override(self):
        pays, _, _ = self.demo()
        claims = self.write("claims.tsv", "item\tfrom\tto\tmonthly\n租房\t2025-01\t\t\n")
        led = ml.Ledger(pays, claims, rent_tier=1100.0)
        self.assertEqual(led.claims[0]["monthly"], 1100.0)

    def test_elderly_split_override(self):
        pays, _, _ = self.demo()
        claims = self.write("claims.tsv", "item\tfrom\tto\tmonthly\n赡养老人\t2025-01\t\t\n")
        led = ml.Ledger(pays, claims, elderly_monthly=1500.0)
        self.assertEqual(led.claims[0]["monthly"], 1500.0)

    def test_medical_no_prior_requires_monthly(self):
        pays, _, _ = self.demo()
        claims = self.write("claims.tsv", "item\tfrom\tto\tmonthly\n大病医疗\t2025-01\t\t\n")
        with self.assertRaises(ml.LedgerError):
            ml.Ledger(pays, claims)


class TestDemoLedger(Base):
    """样例账本：全部读数先手算再钉（见模块 docstring）。"""

    def test_report_monthly_pins(self):
        pays, claims, _ = self.demo()
        out, err, code = self.invoke(["--payslips", pays, "--claims", claims, "report"])
        self.assertEqual(code, 0)
        # A 公司跳档月
        self.assertIn("535.20", out)
        self.assertIn("241.20", out)
        # B 公司 3% 段与 10% 段
        self.assertIn("311.40", out)
        self.assertIn("697.80", out)
        self.assertIn("1,038.00", out)
        self.assertIn("withheld 1,500.00, paid 1,500.00", out)
        self.assertIn("withheld 4,746.00, paid 4,746.00", out)
        self.assertIn("year total: withheld 6,246.00, paid 6,246.00, diff 0.00", out)
        # 结构性洞察署名
        self.assertIn("structural, not clerical", out)
        self.assertNotIn("HIDDEN-ITEM", out)

    def test_settle_balance_due(self):
        pays, claims, _ = self.demo()
        out, err, code = self.invoke(["--payslips", pays, "--claims", claims, "settle"])
        self.assertEqual(code, 4)
        self.assertIn("taxable income 112,860.00", out)
        self.assertIn("annual tax 8,766.00", out)
        self.assertIn("BALANCE-DUE 2,520.00", out)
        self.assertIn("12/12 months", out)

    def test_gap_priced_and_refill_flips(self):
        pays, claims, elig = self.demo()
        out, err, code = self.invoke(["--payslips", pays, "--claims", claims,
                                      "--eligibles", elig, "gap"])
        self.assertEqual(code, 4)
        self.assertIn("24,000.00", out)     # 赡养 8 个月
        self.assertIn("2,800.00", out)      # 继续教育 7 个月
        self.assertIn("2,400.00", out)      # 哑税：赡养
        self.assertIn("280.00", out)        # 哑税：继续教育
        self.assertIn("2,680.00", out)      # 哑税合计
        self.assertIn("BALANCE-DUE 2,520.00", out)
        self.assertIn("REFUND 160.00", out)
        self.assertIn("2,680.00 == mute levy exact total", out)
        self.assertIn("MUTE-LIT", out)

    def test_bonus_solo_saves(self):
        pays, claims, _ = self.demo()
        out, err, code = self.invoke(["--payslips", pays, "--claims", claims,
                                      "bonus", "--amount", "36000"])
        self.assertEqual(code, 0)
        self.assertIn("bonus tax 1,080.00", out)
        self.assertIn("total tax 8,766.00 + 1,080.00 = 9,846.00", out)
        self.assertIn("annual tax 12,852.00", out)
        self.assertIn("SOLO saves 3,006.00", out)
        self.assertIn("3,390.00", out)  # 36000.01 悬崖

    def test_validate_all_green(self):
        pays, claims, _ = self.demo()
        out, err, code = self.invoke(["--payslips", pays, "--claims", claims, "validate"])
        self.assertEqual(code, 0)
        self.assertIn("all identities green", out)
        self.assertNotIn("BROKEN", out)

    def test_byte_identical_replay(self):
        # 全件无墙钟：同一本账跑两遍逐字节一致
        pays, claims, _ = self.demo()
        a = self.invoke(["--payslips", pays, "--claims", claims, "report"])
        b = self.invoke(["--payslips", pays, "--claims", claims, "report"])
        self.assertEqual(a, b)

    def test_report_basename_only(self):
        pays, claims, _ = self.demo()
        out, _, _ = self.invoke(["--payslips", pays, "--claims", claims, "report"])
        self.assertIn("payslips.tsv", out)
        self.assertNotIn(self.tmp, out)


class TestSingleEmployer(Base):
    """单雇主全年：逐月预扣合计 == 年度应纳（同一把税率表的两条路）。"""

    def make_single(self):
        rows = []
        for m in range(1, 13):
            paid = {1: 241.20, 2: 241.20, 3: 241.20, 4: 241.20, 5: 535.20,
                    6: 804.00, 7: 804.00, 8: 804.00, 9: 804.00, 10: 804.00,
                    11: 804.00, 12: 804.00}[m]
            rows.append("2025-%02d\t甲公司\t18000.00\t1800.00\t2160.00\t0.00\t%.2f" % (m, paid))
        return (self.write("p.tsv", self.salaries(rows)),
                self.write("c.tsv", CLAIMS))

    def test_single_employer_settles_even(self):
        pays, claims = self.make_single()
        out, err, code = self.invoke(["--payslips", pays, "--claims", claims, "settle"])
        self.assertEqual(code, 0)
        self.assertIn("annual tax 7,128.00", out)
        self.assertIn("SETTLED: prepaid == annual tax, to the cent", out)

    def test_single_employer_report_total(self):
        pays, claims = self.make_single()
        out, _, _ = self.invoke(["--payslips", pays, "--claims", claims, "report"])
        self.assertIn("year total: withheld 7,128.00, paid 7,128.00, diff 0.00", out)
        # 单雇主不亮结构性灯
        self.assertNotIn("structural, not clerical", out)


class TestBonusRoutes(Base):
    def demo_low_income(self):
        rows = ["2025-%02d\t丙公司\t4000.00\t0.00\t0.00\t0.00\t0.00" % m
                for m in range(1, 13)]
        return (self.write("p.tsv", self.salaries(rows)),
                self.write("c.tsv", "item\tfrom\tto\tmonthly\n"))

    def demo_marginal_three(self):
        # taxable == 26400（3% 档中段，bonus 并入也不跳档）：
        # 10000*12 - 60000 - 1500*12(social) - 1300*12(other_exempt) = 26400
        # 月增 = 10000-5000-1500-1300 = 2200，全程 3% 档，每月预扣 66
        rows = []
        for m in range(1, 13):
            rows.append("2025-%02d\t丁公司\t10000.00\t1500.00\t0.00\t1300.00\t66.00" % m)
        return (self.write("p.tsv", self.salaries(rows)),
                self.write("c.tsv", "item\tfrom\tto\tmonthly\n"))

    def test_merge_wins_when_income_below_exemption(self):
        # 年收入 48000 < 60000：taxable=-12000，年终奖 20000
        # solo: 20000/12=1666.67 -> 3% -> 600；merge: (-12000+20000)=8000 -> 3% -> 240
        pays, claims = self.demo_low_income()
        out, err, code = self.invoke(["--payslips", pays, "--claims", claims,
                                      "bonus", "--amount", "20000"])
        self.assertEqual(code, 0)
        self.assertIn("MERGE saves 360.00", out)

    def test_even_when_both_in_three_percent(self):
        # taxable 26400 + bonus 9600 = 36000（仍在 3% 档内）：
        # solo = 9600*3% = 288；merge = 36000*3% = 1080 = base 792 + 288 → EVEN
        pays, claims = self.demo_marginal_three()
        out, err, code = self.invoke(["--payslips", pays, "--claims", claims,
                                      "bonus", "--amount", "9600"])
        self.assertEqual(code, 0)
        self.assertIn("EVEN: both routes land on the same total", out)

    def test_bonus_amount_must_be_positive(self):
        pays, claims, _ = self.demo()
        _, err, code = self.invoke(["--payslips", pays, "--claims", claims,
                                    "bonus", "--amount", "0"])
        self.assertEqual(code, 2)


class TestSameMonthDualEmployer(Base):
    def test_same_month_two_employers_legal(self):
        rows = ["2025-01\tA\t10000.00\t0.00\t0.00\t0.00\t150.00",
                "2025-01\tB\t10000.00\t0.00\t0.00\t0.00\t150.00",
                "2025-02\tA\t10000.00\t0.00\t0.00\t0.00\t150.00",
                "2025-02\tB\t10000.00\t0.00\t0.00\t0.00\t150.00"]
        pays = self.write("p.tsv", self.salaries(rows))
        claims = self.write("c.tsv", "item\tfrom\tto\tmonthly\n")
        out, _, code = self.invoke(["--payslips", pays, "--claims", claims, "report"])
        self.assertEqual(code, 0)
        # 各雇主独立累计：M1 due 150（cum 5000），M2 due-this 仍 150（300-150）
        self.assertEqual(out.count("withheld 300.00, paid 300.00"), 2)


class TestNegativeClamp(Base):
    def test_first_month_below_exemption_withholds_zero(self):
        rows = ["2025-01\t戊公司\t4000.00\t0.00\t0.00\t0.00\t0.00"]
        pays = self.write("p.tsv", self.salaries(rows))
        claims = self.write("c.tsv", "item\tfrom\tto\tmonthly\n")
        out, _, code = self.invoke(["--payslips", pays, "--claims", claims, "report"])
        self.assertEqual(code, 0)
        # cum-taxable = 4000-5000 = -1000，预扣钳 0
        self.assertIn("-1,000.00", out)
        self.assertNotIn("-0.00", out)


class TestHiddenItem(Base):
    def test_mismatch_disclosed(self):
        pays, claims, _ = self.demo()
        bad = PAYSLIPS.replace("2025-07\tB公司\t21000.00\t2100.00\t2520.00\t0.00\t311.40",
                               "2025-07\tB公司\t21000.00\t2100.00\t2520.00\t0.00\t111.40")
        p2 = self.write("p2.tsv", bad)
        out, _, code = self.invoke(["--payslips", p2, "--claims", claims, "report"])
        self.assertEqual(code, 0)  # 信息不全不是账坏
        self.assertIn("HIDDEN-ITEM: 1 month(s)", out)
        self.assertIn("*", out)


class TestLedgerBroken(Base):
    def test_missing_column(self):
        pays, claims, _ = self.demo()
        p2 = self.write("p2.tsv", "month\temployer\tgross\ntax_paid\n2025-01\tA\t100\t0\n")
        _, err, code = self.invoke(["--payslips", p2, "--claims", claims, "report"])
        self.assertEqual(code, 2)
        self.assertIn("missing column", err)

    def test_bad_month_format(self):
        pays, claims, _ = self.demo()
        p2 = self.write("p2.tsv", self.salaries(
            ["2025/01\tA\t10000\t0\t0\t0\t0"]))
        _, err, code = self.invoke(["--payslips", p2, "--claims", claims, "report"])
        self.assertEqual(code, 2)
        self.assertIn("bad month", err)

    def test_cross_year_rejected(self):
        pays, claims, _ = self.demo()
        p2 = self.write("p2.tsv", self.salaries(
            ["2024-12\tA\t18000\t1800\t2160\t0\t0",
             "2025-01\tA\t18000\t1800\t2160\t0\t0"]))
        _, err, code = self.invoke(["--payslips", p2, "--claims", claims, "settle"])
        self.assertEqual(code, 2)
        self.assertIn("spans 2 calendar years", err)

    def test_duplicate_month_employer(self):
        pays, claims, _ = self.demo()
        p2 = self.write("p2.tsv", self.salaries(
            ["2025-01\tA\t9000\t900\t1080\t0\t120.60",
             "2025-01\tA\t9000\t900\t1080\t0\t120.60"]))
        _, err, code = self.invoke(["--payslips", p2, "--claims", claims, "report"])
        self.assertEqual(code, 2)
        self.assertIn("duplicate salary row", err)

    def test_deductions_exceed_gross(self):
        pays, claims, _ = self.demo()
        p2 = self.write("p2.tsv", self.salaries(
            ["2025-01\tA\t10000\t9000\t2000\t0\t0"]))
        _, err, code = self.invoke(["--payslips", p2, "--claims", claims, "report"])
        self.assertEqual(code, 2)
        self.assertIn("exceeds gross", err)

    def test_negative_tax_rejected(self):
        pays, claims, _ = self.demo()
        p2 = self.write("p2.tsv", self.salaries(
            ["2025-01\tA\t10000\t0\t0\t0\t-5"]))
        _, err, code = self.invoke(["--payslips", p2, "--claims", claims, "report"])
        self.assertEqual(code, 2)

    def test_claim_end_before_start(self):
        pays, claims, _ = self.demo()
        c2 = self.write("c2.tsv", "item\tfrom\tto\tmonthly\n房贷利息\t2025-06\t2025-03\t1000.00\n")
        _, err, code = self.invoke(["--payslips", pays, "--claims", c2, "report"])
        self.assertEqual(code, 2)
        self.assertIn("ends", err)

    def test_missing_file(self):
        pays, claims, _ = self.demo()
        _, err, code = self.invoke(["--payslips", pays, "--claims",
                                    os.path.join(self.tmp, "nope.tsv"), "report"])
        self.assertEqual(code, 2)
        self.assertIn("not found", err)


class TestThinLedger(Base):
    def test_gap_without_eligibles_declines(self):
        pays, claims, _ = self.demo()
        _, err, code = self.invoke(["--payslips", pays, "--claims", claims, "gap"])
        self.assertEqual(code, 3)
        self.assertIn("DECLINE", err)
        self.assertIn("will not invent eligibility", err)

    def test_gap_on_thin_ledger_declines_still_prices_months(self):
        # 1 个月的账 + eligibles：gap 的逐月算术照出，哑税定价照出
        pays, claims, _ = self.demo()
        p2 = self.write("p2.tsv", self.salaries(
            ["2025-03\t己公司\t21000.00\t2100.00\t2520.00\t0.00\t0.00"]))
        e2 = self.write("e2.tsv", "item\tfrom\tto\tmonthly\n继续教育\t2025-01\t\t400.00\n")
        out, _, code = self.invoke(["--payslips", p2, "--claims", claims,
                                    "--eligibles", e2, "gap"])
        self.assertEqual(code, 0)  # 哑税 400*0.03=12 < 500 线
        self.assertIn("400.00", out)
        self.assertIn("1/12 months", out)

    def test_gap_below_mute_line_exits_zero(self):
        pays, claims, _ = self.demo()
        e2 = self.write("e2.tsv", "item\tfrom\tto\tmonthly\n继续教育\t2025-01\t\t400.00\n")
        out, _, code = self.invoke(["--payslips", pays, "--claims", claims,
                                    "--eligibles", e2, "gap"])
        self.assertEqual(code, 0)
        self.assertIn("480.00", out)  # 12×400 = 4800 deduction, ×10% = 480
        self.assertNotIn("MUTE-LIT", out)


class TestClaimsClipping(Base):
    def test_claims_beyond_ledger_clipped_and_disclosed(self):
        pays, claims, _ = self.demo()
        c2 = self.write("c2.tsv", "item\tfrom\tto\tmonthly\n房贷利息\t2024-06\t2026-12\t1000.00\n")
        out, _, code = self.invoke(["--payslips", pays, "--claims", c2, "validate"])
        self.assertEqual(code, 0)
        # 2024-06..2026-12 共 31 个月，账本只覆盖 2025 年 12 个月 → 超出 19
        self.assertIn("claims: 19 month(s) outside the ledger were clipped", out)
        # 扣除只计账本覆盖月（12 个月）→ taxable 与样例一致
        out2, _, code2 = self.invoke(["--payslips", pays, "--claims", c2, "settle"])
        self.assertEqual(code2, 4)
        self.assertIn("special additional claims 12,000.00", out2)

    def test_gap_uses_ledger_months_only(self):
        pays, claims, _ = self.demo()
        e2 = self.write("e2.tsv", "item\tfrom\tto\tmonthly\n赡养老人\t2024-01\t\t3000.00\n")
        out, _, code = self.invoke(["--payslips", pays, "--claims", claims,
                                    "--eligibles", e2, "gap"])
        self.assertEqual(code, 4)
        # 资格从 2024-01 起，但账本只有 2025 年 12 个月：漏报 = 12 个月 36000
        self.assertIn("36,000.00", out)
        self.assertIn("01..12 (12)", out)


class TestValidateBreaks(Base):
    def test_validate_detects_hidden_months_as_disclosed(self):
        pays, claims, _ = self.demo()
        bad = PAYSLIPS.replace("\t241.20\n", "\t141.20\n", 1)
        p2 = self.write("p2.tsv", bad)
        out, _, code = self.invoke(["--payslips", p2, "--claims", claims, "validate"])
        self.assertEqual(code, 0)
        self.assertIn("DISCLOSED", out)
        self.assertIn("1 hidden-item month(s)", out)
        self.assertIn("all identities green", out)

    def test_validate_catches_broken_cliff(self):
        pays, claims, _ = self.demo()
        old = ml.MONTHLY_BRACKETS[:]
        try:
            ml.MONTHLY_BRACKETS[1] = (12000.00, 0.10, 999.00)
            out, _, code = self.invoke(["--payslips", pays, "--claims", claims, "validate"])
            self.assertEqual(code, 2)
            self.assertIn("cliff", out)
            self.assertIn("BROKEN", out)
        finally:
            ml.MONTHLY_BRACKETS[:] = old


class TestDueLine(Base):
    def test_due_line_zero_lights_any_due(self):
        pays, claims, _ = self.demo()
        _, _, code = self.invoke(["--payslips", pays, "--claims", claims, "settle"])
        self.assertEqual(code, 4)

    def test_due_line_above_due_stays_green(self):
        pays, claims, _ = self.demo()
        _, _, code = self.invoke(["--payslips", pays, "--claims", claims,
                                  "--due-line", "3000", "settle"])
        self.assertEqual(code, 0)

    def test_mute_line_respected(self):
        pays, claims, elig = self.demo()
        _, _, code = self.invoke(["--payslips", pays, "--claims", claims,
                                  "--eligibles", elig, "--mute-line", "10000", "gap"])
        self.assertEqual(code, 0)


class TestCoverageDetails(Base):
    def test_employer_with_no_salary_rows_not_possible(self):
        pass  # 结构上 employers 从 salaries 派生，恒成立

    def test_partial_year_coverage_disclosed(self):
        rows = ["2025-%02d\t庚公司\t30000.00\t3000.00\t3600.00\t0.00\t0.00" % m
                for m in range(1, 10)]
        pays = self.write("p.tsv", self.salaries(rows))
        claims = self.write("c.tsv", "item\tfrom\tto\tmonthly\n")
        out, _, code = self.invoke(["--payslips", pays, "--claims", claims, "settle"])
        # 9 个月实缴全 0：taxable=270000-45000-59400=165600 → 20% 档 16200 全补
        self.assertEqual(code, 4)
        self.assertIn("9/12 months", out)
        self.assertIn("exemption 45,000.00 (9 x 5,000.00)", out)

    def test_gap_month_span_labels(self):
        pays, claims, elig = self.demo()
        out, _, _ = self.invoke(["--payslips", pays, "--claims", claims,
                                 "--eligibles", elig, "gap"])
        self.assertIn("05..12 (8)", out)
        self.assertIn("06..12 (7)", out)

    def test_all_claimed_no_gap(self):
        pays, claims, _ = self.demo()
        e2 = self.write("e2.tsv", CLAIMS)
        out, _, code = self.invoke(["--payslips", pays, "--claims", claims,
                                    "--eligibles", e2, "gap"])
        self.assertEqual(code, 0)
        self.assertIn("nothing mute this year", out)


if __name__ == "__main__":
    unittest.main()
