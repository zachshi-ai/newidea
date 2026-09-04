# -*- coding: utf-8 -*-
"""暗息 · Stealth Interest 验收测试。

数值真值由独立实现的牛顿法（newton_irr，crosscheck 惯例）解出后以字面量
钉死——CLI 的二分法必须复现它们。行为真值（exit code / verdict 词）钉死
在 CLI 子进程断言里。

Exit codes: 0 绿 · 2 损坏 · 3 薄/裁决挂起 · 4 红灯。
"""

import importlib.util
import math
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
IDEA = os.path.dirname(HERE)
CLI = os.path.join(IDEA, "stealth_interest.py")
EXAMPLES = os.path.join(IDEA, "examples", "plans.tsv")

_spec = importlib.util.spec_from_file_location("stealth_interest", CLI)
si = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(si)


def go(*args):
    """跑 CLI 子进程，返回 (stdout, stderr, exit_code)。"""
    proc = subprocess.run(
        [sys.executable, CLI] + list(args),
        capture_output=True, text=True)
    return proc.stdout, proc.stderr, proc.returncode


def newton_irr(pv, flows, guess=0.01):
    """独立牛顿法——与 CLI 的二分法互为对拍。"""
    i = guess
    for _ in range(300):
        f = sum(cf / (1 + i) ** k for k, cf in enumerate(flows, 1)) - pv
        df = sum(-k * cf / (1 + i) ** (k + 1)
                 for k, cf in enumerate(flows, 1))
        i -= f / df
    return i


# ---- 手算钉值（12000 × 12 期 × 0.6%/期，独立牛顿法解出） ----------------
P, N, R = 12000, 12, 0.006
AP, FEE = P / N, P * R * N                      # 1000, 864
FLAT_I = 0.010861854                            # 月 IRR
FLAT_APR = 0.130342243                          # 名义年化
FLAT_EAR = 0.138417851                          # 有效年化
UPFRONT_I = 0.011546693                         # 首期一次收
REMAIN_AVG_I = 0.020116772                      # remaining 规则第 3 期结清的全程平均
MARG3_I = 0.014135519                           # paid=3 边际月 IRR
MARG3_APR, MARG3_EAR = 0.169626, 0.183455
MARG11_I = 0.072                                # 尾期 = n·r 精确
LAP_MARG_APR = 0.185818                         # 样例账本 laptop 边际
TRIP_MARG_APR = 0.162745                        # trip 边际
WEIGHTED_APR = 0.171369                         # 剩余本金加权
BE_YIELD_EAR = 0.064909262                      # 折扣 400 的盈亏平衡收益率
PV_FREE_2PCT = 11872.16                         # 免息流 @ 年化 2% 的 PV
BE_DISCOUNT = 127.84                            # @2% 的盈亏平衡折扣
PV_DIFF = 272.16                                # 折扣胜出差额


def make_ledger(tmpdir, lines):
    path = os.path.join(tmpdir, "plans.tsv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


HEADER = ["platform", "item", "principal", "months", "fee_rate",
          "paid", "mode", "prepay_rule"]
GOOD = [
    "\t".join(HEADER),
    "huabei\tphone-12k\t12000\t12\t0.006\t3\tflat\tremaining",
    "jingdong\tlaptop-8k\t8000\t24\t0.005\t10\tflat\twaived",
    "merchant\ttour-6k\t6000\t6\t0.008\t0\tflat\tremaining",
]


class TestSolver(unittest.TestCase):
    """求解器：与牛顿法对拍 + 手算钉值。"""

    def test_pv_identity_flat(self):
        flows = si.plan_flows(P, N, R)
        i = si.solve_irr(P, flows)
        pv = sum(cf / (1 + i) ** k for k, cf in enumerate(flows, 1))
        self.assertAlmostEqual(pv, P, delta=1e-6)

    def test_flat_irr_pinned(self):
        i = si.real_rate(P, N, R)
        self.assertAlmostEqual(i, newton_irr(P, [AP + FEE / N] * N), delta=1e-9)
        self.assertAlmostEqual(i, FLAT_I, delta=1e-8)

    def test_annuals_pinned(self):
        i = si.real_rate(P, N, R)
        apr, ear = si.annualize(i)
        self.assertAlmostEqual(apr, FLAT_APR, delta=1e-7)
        self.assertAlmostEqual(ear, FLAT_EAR, delta=1e-7)

    def test_multiplier_181(self):
        apr, _ = si.annualize(si.real_rate(P, N, R))
        self.assertAlmostEqual(apr / (R * 12), 1.8103, delta=1e-3)

    def test_approx_within_3pct(self):
        apr, _ = si.annualize(si.real_rate(P, N, R))
        approx = 2 * N / (N + 1) * R * 12
        self.assertLess(abs(approx - apr) / apr, 0.03)

    def test_n1_exact_equality(self):
        """n=1：单期无余额递减，真实 = 名义恰等（钉到机器精度）。"""
        i = si.real_rate(5000, 1, 0.01)
        self.assertAlmostEqual(i, 0.01, delta=1e-12)

    def test_real_gt_nominal_grid(self):
        """定理：n>=2、r>0 时真实年化严格大于名义。"""
        for n in range(2, 25):
            for r in (0.002, 0.006, 0.015):
                apr, _ = si.annualize(si.real_rate(10000, n, r))
                self.assertGreater(apr, r * 12, "n={} r={}".format(n, r))

    def test_monotonic_in_fee_rate(self):
        prev = -1.0
        for r in (0.003, 0.006, 0.012):
            i = si.real_rate(12000, 12, r)
            self.assertGreater(i, prev)
            prev = i

    def test_upfront_pinned_and_pricier(self):
        i = si.real_rate(P, N, R, mode="upfront")
        self.assertAlmostEqual(i, newton_irr(P, [AP + FEE] + [AP] * (N - 1)),
                               delta=1e-9)
        self.assertAlmostEqual(i, UPFRONT_I, delta=1e-8)
        self.assertGreater(i, si.real_rate(P, N, R))

    def test_zero_fee_is_zero(self):
        i = si.real_rate(12000, 12, 0.0)
        apr, ear = si.annualize(i)
        self.assertEqual((i, apr, ear), (0.0, 0.0, 0.0))

    def test_marginal_pinned_paid3(self):
        i = si.marginal_rate(P, N, R, 3)
        apr, ear = si.annualize(i)
        self.assertAlmostEqual(i, MARG3_I, delta=1e-8)
        self.assertAlmostEqual(apr, MARG3_APR, delta=1e-5)
        self.assertAlmostEqual(ear, MARG3_EAR, delta=1e-5)

    def test_marginal_last_period_exact(self):
        """尾期：欠 1000 还 1072 一个月 → 月息 = n·r = 7.2%，年化 86.4%。"""
        i = si.marginal_rate(P, N, R, 11)
        self.assertAlmostEqual(i, MARG11_I, delta=1e-9)

    def test_marginal_monotone_in_paid(self):
        prev = -1.0
        for paid in range(0, 12):
            i = si.marginal_rate(P, N, R, paid)
            self.assertGreater(i, prev, "paid={}".format(paid))
            prev = i

    def test_remaining_inception_average_pinned(self):
        settle = 9 * (AP + FEE / N)          # 9648
        i = si.average_rate_with_prepay(P, N, R, 3, settle)
        self.assertAlmostEqual(i, REMAIN_AVG_I, delta=1e-8)

    def test_breakeven_yield_pinned(self):
        i = si.breakeven_yield(12000, [1000.0] * 12, 11600.0)
        _, ear = si.annualize(i)
        self.assertAlmostEqual(ear, BE_YIELD_EAR, delta=1e-6)

    def test_breakeven_yield_no_sign_change(self):
        with self.assertRaises(si.LedgerError):
            si.breakeven_yield(12000, [900.0] * 12, 11600.0)


class TestRateCLI(unittest.TestCase):
    def test_rate_output_pinned(self):
        out, err, code = go("rate", "--principal", "12000",
                            "--months", "12", "--fee-rate", "0.006")
        self.assertEqual(code, 0)
        for needle in ("1.0862%", "7.20%", "13.03%", "13.84%", "1.81x",
                       "13.29%", "864.00", "12,864.00"):
            self.assertIn(needle, out)

    def test_rate_line_gate(self):
        out, err, code = go("rate", "--principal", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--line", "0.12")
        self.assertEqual(code, 4)
        self.assertIn("LINE BREACH", out)
        out, err, code = go("rate", "--principal", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--line", "0.20")
        self.assertEqual(code, 0)
        self.assertNotIn("BREACH", out)
        self.assertIn("within line", out)

    def test_rate_bad_args(self):
        for args in (
            ("--principal", "-5", "--months", "12", "--fee-rate", "0.006"),
            ("--principal", "12000", "--months", "0", "--fee-rate", "0.006"),
            ("--principal", "12000", "--months", "12", "--fee-rate", "0.5"),
            ("--principal", "12000", "--months", "12", "--fee-rate", "-0.01"),
        ):
            out, err, code = go("rate", *args)
            self.assertEqual(code, 2, str(args))

    def test_rate_upfront_output(self):
        out, err, code = go("rate", "--principal", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--mode", "upfront")
        self.assertEqual(code, 0)
        self.assertIn("13.86%", out)
        self.assertIn("2,864.00", out)      # 首期 = 1000 + 864 全费
        self.assertIn("principal only", out)

    def test_rate_fee_zero(self):
        out, err, code = go("rate", "--principal", "12000", "--months", "12",
                            "--fee-rate", "0")
        self.assertEqual(code, 0)
        self.assertIn("interest-free", out)


class TestPrepayCLI(unittest.TestCase):
    BASE = ("--principal", "12000", "--months", "12",
            "--fee-rate", "0.006", "--paid", "3")

    def test_remaining_zero_saving(self):
        out, err, code = go("prepay", *self.BASE, "--rule", "remaining")
        self.assertEqual(code, 0)
        self.assertIn("ZERO-SAVING", out)
        self.assertIn("9,648.00", out)
        self.assertIn("648.00", out)        # 剩余手续费照列
        self.assertIn("verdict: KEEP", out)
        self.assertIn("24.14%", out)        # 平均镜披露
        self.assertIn("16.96%", out)        # 边际镜（判据）
        self.assertNotIn("PAYOFF", out)

    def test_waived_saving_648(self):
        out, err, code = go("prepay", *self.BASE, "--rule", "waived")
        self.assertEqual(code, 3)           # 算术照出、裁决挂起（无 --yield）
        self.assertIn("9,000.00", out)      # 结清额
        self.assertIn("648.00", out)        # 名义节省

    def test_waived_verdicts(self):
        out, err, code = go("prepay", *self.BASE, "--rule", "waived",
                            "--yield", "0.02")
        self.assertEqual(code, 0)
        self.assertIn("verdict: PAYOFF", out)
        out, err, code = go("prepay", *self.BASE, "--rule", "waived",
                            "--yield", "0.20")
        self.assertEqual(code, 0)
        self.assertIn("verdict: KEEP", out)

    def test_waived_no_yield_suspended(self):
        out, err, code = go("prepay", *self.BASE, "--rule", "waived")
        self.assertEqual(code, 3)
        self.assertIn("648.00", out)        # 算术照出
        self.assertIn("TOO THIN", err)

    def test_pct_rule_needs_yield_then_payoff(self):
        out, err, code = go("prepay", *self.BASE, "--rule", "pct",
                            "--penalty", "0.02")
        self.assertEqual(code, 3)           # 与 waived 同规：裁决要 --yield
        self.assertIn("9,180.00", out)      # 9000 × 1.02
        self.assertIn("468.00", out)        # 名义节省
        out, err, code = go("prepay", *self.BASE, "--rule", "pct",
                            "--penalty", "0.02", "--yield", "0.02")
        self.assertEqual(code, 0)
        self.assertIn("verdict: PAYOFF", out)

    def test_pct_rule_breach(self):
        out, err, code = go("prepay", *self.BASE, "--rule", "pct",
                            "--penalty", "0.10")
        self.assertEqual(code, 4)
        self.assertIn("SETTLE COSTS MORE", out)
        self.assertIn("9,900.00", out)

    def test_upfront_after_first_fee_sunk(self):
        out, err, code = go("prepay", "--principal", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--paid", "1",
                            "--mode", "upfront")
        self.assertEqual(code, 0)
        self.assertIn("verdict: KEEP", out)  # 费已沉没，无息可省
        self.assertIn("remaining fee                 0.00", out)
        self.assertIn("0.00%   nominal, EAR 0.00%", out)
        self.assertIn("45.89%", out)        # 平均镜：全额手续费压进 1 期使用

    def test_settled_plan_thin(self):
        out, err, code = go("prepay", "--principal", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--paid", "12")
        self.assertEqual(code, 3)
        self.assertIn("TOO THIN", err)

    def test_paid_out_of_range(self):
        out, err, code = go("prepay", "--principal", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--paid", "13")
        self.assertEqual(code, 2)
        out, err, code = go("prepay", "--principal", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--paid", "-1")
        self.assertEqual(code, 2)


class TestOfferCLI(unittest.TestCase):
    def test_free_no_discount(self):
        out, err, code = go("offer", "--price", "12000", "--months", "12")
        self.assertEqual(code, 0)
        self.assertIn("verdict: TAKE-PLAN", out)

    def test_free_discount_with_yield(self):
        out, err, code = go("offer", "--price", "12000", "--months", "12",
                            "--cash-discount", "400", "--yield", "0.02")
        self.assertEqual(code, 0)
        for needle in ("11,872.16", "127.84", "272.16", "verdict: TAKE-CASH",
                       "6.49%"):
            self.assertIn(needle, out)

    def test_free_discount_high_yield_plan_wins(self):
        out, err, code = go("offer", "--price", "12000", "--months", "12",
                            "--cash-discount", "400", "--yield", "0.50")
        self.assertEqual(code, 0)
        self.assertIn("verdict: TAKE-PLAN", out)

    def test_interest_bearing_vs_cash_price(self):
        out, err, code = go("offer", "--price", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--cash-price", "12000",
                            "--yield", "0.02")
        self.assertEqual(code, 0)
        self.assertIn("verdict: TAKE-CASH", out)

    def test_nominal_decisive_cash(self):
        """无 --yield 但名义胜负分明：折扣 1000 > 总费 864 → 名义 TAKE-CASH。"""
        out, err, code = go("offer", "--price", "12000", "--months", "12",
                            "--cash-discount", "1000")
        self.assertEqual(code, 0)
        self.assertIn("verdict: TAKE-CASH (nominal)", out)

    def test_nominal_undecidable_suspended(self):
        """无 --yield 且分期名义更贵：时间价值问题，裁决挂起。"""
        out, err, code = go("offer", "--price", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--cash-discount", "400")
        self.assertEqual(code, 3)
        self.assertIn("TOO THIN", err)
        self.assertIn("864.00", out)        # 名义账照出

    def test_nominal_tie_suspended(self):
        out, err, code = go("offer", "--price", "12000", "--months", "12",
                            "--fee-rate", "0.006", "--cash-discount", "864")
        self.assertEqual(code, 3)

    def test_cash_price_alias(self):
        a = go("offer", "--price", "12000", "--months", "12",
               "--cash-price", "11600", "--yield", "0.02")
        b = go("offer", "--price", "12000", "--months", "12",
               "--cash-discount", "400", "--yield", "0.02")
        self.assertEqual(a[2], b[2])
        self.assertEqual(a[0], b[0])

    def test_bad_inputs(self):
        out, err, code = go("offer", "--price", "12000", "--months", "12",
                            "--cash-discount", "12000")
        self.assertEqual(code, 2)
        out, err, code = go("offer", "--price", "12000", "--months", "12",
                            "--cash-price", "11000", "--cash-discount", "400")
        self.assertEqual(code, 2)


class TestStackCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = make_ledger(self.tmp.name, GOOD)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pinned_totals(self):
        out, err, code = go("stack", self.ledger, "--salary", "10000")
        self.assertEqual(code, 0)
        for needle in ("19,666.67", "1,496.00", "21,162.67", "16.96%",
                       "18.58%", "16.27%", "17.14%"):
            self.assertIn(needle, out)

    def test_timeline_segments(self):
        out, err, code = go("stack", self.ledger)
        self.assertEqual(code, 0)
        self.assertIn("months 1-6", out)
        self.assertIn("2,493.33", out)
        self.assertIn("months 7-9", out)
        self.assertIn("1,445.33", out)
        self.assertIn("months 10-14", out)
        self.assertIn("373.33", out)

    def test_burden_green(self):
        out, err, code = go("stack", self.ledger, "--salary", "10000")
        self.assertEqual(code, 0)
        self.assertIn("24.93%", out)
        self.assertIn("within line", out)
        self.assertNotIn("BREACH", out)

    def test_burden_red(self):
        out, err, code = go("stack", self.ledger, "--salary", "5000")
        self.assertEqual(code, 4)
        self.assertIn("BURDEN LINE BREACHED", out)
        self.assertIn("49.87%", out)

    def test_burden_line_flag(self):
        out, err, code = go("stack", self.ledger, "--salary", "10000",
                            "--burden-line", "0.20")
        self.assertEqual(code, 4)

    def test_no_salary_no_verdict(self):
        out, err, code = go("stack", self.ledger)
        self.assertEqual(code, 0)
        self.assertIn("give --salary", out)

    def test_percent_fee_rate_form(self):
        lines = [GOOD[0],
                 "a\tx\t12000\t12\t0.6%\t3\tflat\tremaining"]
        path = make_ledger(self.tmp.name, lines)
        out, err, code = go("stack", path)
        self.assertEqual(code, 0)
        self.assertIn("16.96%", out)

    def test_empty_ledger_thin(self):
        path = make_ledger(self.tmp.name, ["\t".join(HEADER)])
        out, err, code = go("stack", path)
        self.assertEqual(code, 3)

    def test_missing_file(self):
        out, err, code = go("stack", os.path.join(self.tmp.name, "nope.tsv"))
        self.assertEqual(code, 2)
        self.assertNotIn(self.tmp.name, out + err)   # 只报 basename
        self.assertIn("nope.tsv", err)

    def _broken(self, line):
        return make_ledger(self.tmp.name, [GOOD[0]] + [line])

    def test_dup_row(self):
        path = make_ledger(self.tmp.name, GOOD + [GOOD[1]])
        out, err, code = go("stack", path)
        self.assertEqual(code, 2)

    def test_paid_over_months(self):
        out, err, code = go("stack", self._broken(
            "a\tx\t100\t12\t0.006\t13\tflat\tremaining"))
        self.assertEqual(code, 2)

    def test_negative_principal(self):
        out, err, code = go("stack", self._broken(
            "a\tx\t-100\t12\t0.006\t0\tflat\tremaining"))
        self.assertEqual(code, 2)

    def test_unknown_mode(self):
        out, err, code = go("stack", self._broken(
            "a\tx\t100\t12\t0.006\t0\tweird\tremaining"))
        self.assertEqual(code, 2)

    def test_unknown_rule(self):
        out, err, code = go("stack", self._broken(
            "a\tx\t100\t12\t0.006\t0\tflat\tmaybe"))
        self.assertEqual(code, 2)

    def test_short_row(self):
        out, err, code = go("stack", self._broken(
            "a\tx\t100\t12\t0.006\t0\tflat"))
        self.assertEqual(code, 2)

    def test_long_row(self):
        out, err, code = go("stack", self._broken(
            "a\tx\t100\t12\t0.006\t0\tflat\tremaining\textra"))
        self.assertEqual(code, 2)

    def test_bad_header(self):
        out, err, code = go("stack", self._broken(
            "who\twhat\thow\twhen"))
        self.assertEqual(code, 2)

    def test_settled_rows_ignored(self):
        lines = GOOD + ["old\tdone\t1200\t12\t0.006\t12\tflat\tremaining"]
        path = make_ledger(self.tmp.name, lines)
        out, err, code = go("stack", path, "--salary", "10000")
        self.assertEqual(code, 0)
        self.assertIn("1 settled plan(s) ignored", out)
        self.assertNotIn("old", out.split("platform")[1].split("totals")[0])

    def test_all_settled_thin(self):
        path = make_ledger(self.tmp.name, [GOOD[0],
                                           "old\tdone\t1200\t12\t0.006\t12\tflat\tremaining"])
        out, err, code = go("stack", path)
        self.assertEqual(code, 3)

    def test_cjk_names_aligned(self):
        lines = [GOOD[0],
                 "花呗\t手机分期\t12000\t12\t0.006\t3\tflat\tremaining"]
        path = make_ledger(self.tmp.name, lines)
        out, err, code = go("stack", path)
        self.assertEqual(code, 0)
        self.assertIn("花呗", out)

    def test_examples_fixture_dogfood(self):
        """dogfood：仓库示例账本本身就是测试夹具。"""
        out, err, code = go("stack", EXAMPLES, "--salary", "8500")
        self.assertEqual(code, 0)
        self.assertIn("29.33%", out)
        self.assertIn("within line", out)


class TestValidateCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = make_ledger(self.tmp.name, GOOD)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ok(self):
        out, err, code = go("validate", self.ledger)
        self.assertEqual(code, 0)
        self.assertIn("ledger OK: 3 plans", out)
        self.assertIn("all identities hold", out)

    def test_empty_thin(self):
        path = make_ledger(self.tmp.name, ["\t".join(HEADER)])
        out, err, code = go("validate", path)
        self.assertEqual(code, 3)

    def test_dup_is_broken(self):
        path = make_ledger(self.tmp.name, GOOD + [GOOD[2]])
        out, err, code = go("validate", path)
        self.assertEqual(code, 2)

    def test_examples_fixture(self):
        out, err, code = go("validate", EXAMPLES)
        self.assertEqual(code, 0)


class TestPlumbing(unittest.TestCase):
    def test_help_each_subcommand(self):
        for cmd in ("rate", "prepay", "offer", "stack", "validate"):
            out, err, code = go(cmd, "--help")
            self.assertEqual(code, 0, cmd)

    def test_top_help(self):
        out, err, code = go("--help")
        self.assertEqual(code, 0)
        self.assertIn("STEALTH", out.upper())

    def test_no_args_usage(self):
        out, err, code = go()
        self.assertEqual(code, 2)

    def test_unknown_subcommand(self):
        out, err, code = go("refinance")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
