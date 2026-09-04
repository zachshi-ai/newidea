# -*- coding: utf-8 -*-
"""redemption 验收测试：解析 / 日期 / 摊销恒等式 / 预付重放 / 省息 /
等效定理 / 分配 / 谬误法庭 / 门禁与拒答 / 工程约定."""

import ast
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import redemption  # noqa: E402

GOOD_LOANS = (
    "name\tprincipal\trate\tyears\tstart\tmethod\tnote\n"
    "商贷\t1400000\t4.2\t30\t2021-03-01\tannuity\t执行利率\n"
    "公积金\t600000\t3.1\t30\t2021-03-01\tannuity\n"
)
GOOD_PREPAYS = (
    "date\tamount\ttarget\tmode\tnote\n"
    "2024-01-15\t200000\t商贷\tterm\t年终奖\n"
    "2025-01-10\t100000\t商贷\tpayment\n"
)
TODAY = ["--today", "2026-09-04"]

# 独立公式交叉验证的手算常量（不经过 redemption 模块）：
#   annuity M = P·i·(1+i)^n/((1+i)^n−1)，i = 年利率/12
#   商贷月供 6846.24 · 公积金月供 2562.10 · 组合 9408.34
#   真实利率 (1+i)^12−1：4.2% → 4.2818% · 3.1% → 3.1444%
#   商贷首期利息 = 1,400,000×0.0035 = 4,900.00
M_COMM = 6846.24
M_FUND = 2562.10
TRUE_42 = 0.042818
I_COMM = 0.0035


def run(argv):
    buf = io.StringIO()
    err = io.StringIO()
    from contextlib import redirect_stderr
    code = None
    saved_err = sys.stderr
    try:
        with redirect_stdout(buf), redirect_stderr(err):
            code = redemption.main(argv)
    finally:
        sys.stderr = saved_err
    return code, buf.getvalue(), err.getvalue()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.loans = self._w("loans.tsv", GOOD_LOANS)
        self.prepays = self._w("prepays.tsv", GOOD_PREPAYS)

    def _w(self, name, text):
        path = os.path.join(self.dir.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def rewrite(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def args(self, cmd, extra=None, prepays=True):
        return [cmd, self.loans, self.prepays if prepays else "no-such.tsv"] \
            + (extra or []) + TODAY


class TestParsing(Fixture):
    def test_a1_parse_loans_fields(self):
        loans = redemption.parse_loans(self.loans)
        self.assertEqual([l.name for l in loans], ["商贷", "公积金"])
        self.assertEqual(loans[0].principal, 1400000.0)
        self.assertEqual(loans[0].rate, 4.2)
        self.assertEqual(loans[0].start, date(2021, 3, 1))
        self.assertEqual(loans[0].method, "annuity")
        self.assertEqual(loans[1].note, "")

    def test_a2_header_comment_blank_skipped(self):
        loans = redemption.parse_loans(self.loans)
        self.assertEqual(len(loans), 2)

    def test_a3_chinese_method_alias(self):
        self.rewrite(self.loans,
                     "name\tprincipal\trate\tyears\tstart\tmethod\n"
                     "商贷\t1000000\t4.2\t30\t2021-03-01\t等额本息\n"
                     "公积金\t500000\t3.1\t30\t2021-03-01\t等额本金\n")
        loans = redemption.parse_loans(self.loans)
        self.assertEqual([l.method for l in loans], ["annuity", "linear"])

    def test_a4_bad_columns_exit2(self):
        for text in ("a\t1\t4\t30\t2021-01-01\n",
                     "a\t1\t4\t30\t2021-01-01\tannuity\textra\tx\n"):
            self.rewrite(self.loans, text)
            with self.assertRaises(redemption.LedgerError):
                redemption.parse_loans(self.loans)

    def test_a5_principal_bad(self):
        for v in ("abc", "0", "-5"):
            self.rewrite(self.loans,
                         f"a\t{v}\t4\t30\t2021-01-01\tannuity\n")
            with self.assertRaises(redemption.LedgerError):
                redemption.parse_loans(self.loans)

    def test_a6_rate_bad(self):
        for v in ("x", "0", "120"):
            self.rewrite(self.loans,
                         f"a\t100\t{v}\t30\t2021-01-01\tannuity\n")
            with self.assertRaises(redemption.LedgerError):
                redemption.parse_loans(self.loans)

    def test_a7_years_bad(self):
        for v in ("y", "0", "200"):
            self.rewrite(self.loans,
                         f"a\t100\t4\t{v}\t2021-01-01\tannuity\n")
            with self.assertRaises(redemption.LedgerError):
                redemption.parse_loans(self.loans)

    def test_a8_date_bad(self):
        self.rewrite(self.loans,
                     "a\t100\t4\t30\t2021/01/01\tannuity\n")
        with self.assertRaises(redemption.LedgerError):
            redemption.parse_loans(self.loans)

    def test_a9_method_bad(self):
        self.rewrite(self.loans,
                     "a\t100\t4\t30\t2021-01-01\t等额本息plus\n")
        with self.assertRaises(redemption.LedgerError):
            redemption.parse_loans(self.loans)

    def test_a10_duplicate_name(self):
        self.rewrite(self.loans,
                     "a\t100\t4\t30\t2021-01-01\tannuity\n"
                     "A\t200\t5\t20\t2022-01-01\tannuity\n")
        with self.assertRaises(redemption.LedgerError):
            redemption.parse_loans(self.loans)

    def test_a11_too_many_loans(self):
        self.rewrite(self.loans, "".join(
            f"贷{i}\t100\t4\t30\t2021-01-01\tannuity\n" for i in range(5)))
        with self.assertRaises(redemption.LedgerError):
            redemption.parse_loans(self.loans)

    def test_a12_missing_file_exit2(self):
        with self.assertRaises(redemption.LedgerError):
            redemption.parse_loans("no-such-file.tsv")

    def test_a13_prepays_parse_sorted(self):
        ps = redemption.parse_prepays(self.prepays)
        self.assertEqual([p.amount for p in ps], [200000.0, 100000.0])
        self.assertEqual([p.mode for p in ps], ["term", "payment"])
        self.assertEqual(ps[0].target, "商贷")

    def test_a14_prepay_target_all_rejected(self):
        self.rewrite(self.prepays,
                     "date\tamount\ttarget\tmode\n"
                     "2024-01-15\t200000\tALL\tterm\n")
        with self.assertRaises(redemption.LedgerError):
            redemption.parse_prepays(self.prepays)

    def test_a15_prepay_mode_bad(self):
        self.rewrite(self.prepays,
                     "date\tamount\ttarget\tmode\n"
                     "2024-01-15\t200000\t商贷\tshorten\n")
        with self.assertRaises(redemption.LedgerError):
            redemption.parse_prepays(self.prepays)

    def test_a16_prepay_target_unknown(self):
        self.rewrite(self.prepays,
                     "date\tamount\ttarget\tmode\n"
                     "2024-01-15\t200000\t消费贷\tterm\n")
        with self.assertRaises(redemption.LedgerError):
            redemption.load(self.loans, self.prepays)

    def test_a17_empty_ledger_refusal(self):
        self.rewrite(self.loans, "# 只有注释\n")
        code, _out, err = run(["plan", self.loans, self.prepays] + TODAY)
        self.assertEqual(code, 3)
        self.assertIn("空", err)

    def test_a18_prepays_file_optional(self):
        loans, prepays = redemption.load(self.loans, None)
        self.assertEqual(prepays, [])
        loans, prepays = redemption.load(self.loans, "no-such.tsv")
        self.assertEqual(prepays, [])


class TestDates(unittest.TestCase):
    def test_b1_months_done(self):
        s = date(2021, 3, 1)
        self.assertEqual(redemption.months_done(s, date(2021, 3, 1)), 1)
        self.assertEqual(redemption.months_done(s, date(2021, 2, 28)), 0)
        self.assertEqual(redemption.months_done(s, date(2021, 3, 15)), 1)
        self.assertEqual(redemption.months_done(s, date(2026, 9, 4)), 67)
        self.assertEqual(redemption.months_done(s, date(2026, 9, 1)), 67)
        self.assertEqual(redemption.months_done(s, date(2026, 8, 31)), 66)
        # 月末钳制：start 31 日，2 月无 31 日 → 28/29 日算当期还款日
        s31 = date(2021, 1, 31)
        self.assertEqual(redemption.months_done(s31, date(2021, 2, 28)), 2)
        self.assertEqual(redemption.months_done(s31, date(2021, 2, 27)), 1)
        self.assertEqual(redemption.months_done(s31, date(2021, 1, 31)), 1)
        self.assertEqual(redemption.months_done(s31, date(2021, 1, 30)), 0)

    def test_b2_add_months_clamp(self):
        d = date(2021, 1, 31)
        self.assertEqual(redemption.add_months(d, 1), date(2021, 2, 28))
        self.assertEqual(redemption.add_months(d, 0), d)
        self.assertEqual(redemption.add_months(d, 13), date(2022, 2, 28))
        self.assertEqual(redemption.add_months(date(2020, 1, 31), 1),
                         date(2020, 2, 29))


class TestAnnuityMath(Fixture):
    def test_c1_annuity_payment_hand(self):
        pay = redemption.annuity_payment(1400000.0, I_COMM, 360)
        self.assertAlmostEqual(pay, M_COMM, places=1)

    def test_c2_split_identity_every_period(self):
        loan = redemption.parse_loans(self.loans)[0]
        rows, _ = redemption.replay(loan, [])
        for r in rows:
            self.assertAlmostEqual(r.payment - r.interest - r.principal,
                                   0.0, places=6)

    def test_c3_recursion_identity(self):
        loan = redemption.parse_loans(self.loans)[0]
        rows, _ = redemption.replay(loan, [])
        b = loan.principal
        for r in rows:
            self.assertAlmostEqual(r.interest, b * I_COMM, places=6)
            b = b - r.principal
            self.assertAlmostEqual(r.balance, max(b, 0.0), places=6)

    def test_c4_principal_regression(self):
        for loan in redemption.parse_loans(self.loans):
            rows, _ = redemption.replay(loan, [])
            self.assertAlmostEqual(sum(r.principal for r in rows),
                                   loan.principal, places=5)

    def test_c5_terminal_zero(self):
        for loan in redemption.parse_loans(self.loans):
            rows, _ = redemption.replay(loan, [])
            self.assertLess(rows[-1].balance, 1e-6)

    def test_c6_linear_shape(self):
        self.rewrite(self.loans,
                     "贷\t120000\t6\t2\t2021-01-01\tlinear\n")
        loan = redemption.parse_loans(self.loans)[0]
        rows, _ = redemption.replay(loan, [])
        i = redemption.month_rate(6.0)
        prins = [r.principal for r in rows]
        for p in prins[:-1]:
            self.assertAlmostEqual(p, 120000 / 24, places=6)
        self.assertAlmostEqual(rows[0].payment, 120000 / 24 + 120000 * i,
                               places=6)
        self.assertLess(rows[-1].payment, rows[0].payment)

    def test_c7_true_annual(self):
        self.assertAlmostEqual(redemption.true_annual(4.2) * 100, 4.2818,
                               places=3)
        self.assertAlmostEqual(redemption.true_annual(3.1) * 100, 3.1444,
                               places=3)

    def test_c8_interest_halfpoint_before_middle(self):
        loan = redemption.parse_loans(self.loans)[0]
        rows0 = redemption.factory_rows(loan)
        total = redemption.total_interest(rows0)
        cum = 0.0
        half = None
        for r in rows0:
            cum += r.interest
            if half is None and cum >= total / 2:
                half = r.k
        self.assertLess(half, 180)  # 利息半程点在时间半程之前
        self.assertEqual(half, 121)


class TestReplay(Fixture):
    def setUp(self):
        super().setUp()
        self.loan = redemption.parse_loans(self.loans)[0]

    def test_d1_term_prepay_shortens_keeps_pay(self):
        rows, events = redemption.replay(self.loan,
                                         redemption.parse_prepays(self.prepays))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].mode, "term")
        # 缩期：总期数 < 出厂 360，事件后月供不变
        self.assertLess(len(rows), 360)
        self.assertAlmostEqual(events[0].pay_before, events[0].pay_after,
                               places=6)

    def test_d2_payment_prepay_keeps_term_lowers_pay(self):
        rows, events = redemption.replay(self.loan,
                                         redemption.parse_prepays(self.prepays))
        ev = events[1]
        self.assertEqual(ev.mode, "payment")
        self.assertAlmostEqual(ev.pay_before, 6846.24, places=1)
        self.assertLess(ev.pay_after, ev.pay_before)
        # 新月供 = annuity_payment(新余额, i, 剩余期数) 精确
        i = I_COMM
        k = ev.k
        bal_after = rows[k - 1].balance  # 第 k 期还款+预付后
        n_rem = 360 - k if len(rows) >= 360 else len(rows) - k
        # end_k 被 term 事件缩过：从事件里拿
        n_rem = ev.n_after
        want = redemption.annuity_payment(bal_after, i, n_rem)
        self.assertAlmostEqual(ev.pay_after, want, places=6)

    def test_d3_effective_boundary_next_period_interest(self):
        # 预付生效在整期后：下一期利息按 (期初−预付) 计
        ps = [redemption.Prepay(date(2024, 1, 15), 50000, "商贷", "term",
                                "", 2)]
        rows_a, _ = redemption.replay(self.loan, ps)
        rows_b, _ = redemption.replay(self.loan, [])
        k = redemption.months_done(self.loan.start, ps[0].date)
        self.assertEqual(k, 35)
        bal = rows_b[k - 1].balance - 50000
        self.assertAlmostEqual(rows_a[k].interest, bal * I_COMM, places=6)

    def test_d4_prepay_ge_balance_exit2(self):
        self.rewrite(self.prepays,
                     "date\tamount\ttarget\tmode\n"
                     "2026-06-15\t2000000\t商贷\tterm\n")
        ps = redemption.parse_prepays(self.prepays)
        with self.assertRaises(redemption.LedgerError):
            redemption.replay(self.loan, ps)

    def test_d5_identities_hold_after_replay(self):
        for loan in redemption.parse_loans(self.loans):
            mine = redemption.loan_prepays(
                loan, redemption.parse_prepays(self.prepays))
            rows, _ = redemption.replay(loan, mine)
            self.assertAlmostEqual(
                sum(r.principal for r in rows) + sum(p.amount for p in mine),
                loan.principal, places=5)
            self.assertLess(rows[-1].balance, 1e-6)

    def test_d6_position_split_three_numbers(self):
        parts = redemption.ledger_positions(
            redemption.parse_loans(self.loans),
            redemption.parse_prepays(self.prepays), date(2026, 9, 4))
        loan, done, fut, _ev = parts[0]
        self.assertEqual(len(done), 67)
        self.assertEqual(fut[0].k, 68)
        self.assertEqual(fut[0].date, date(2026, 10, 1))


class TestSimulate(Fixture):
    def setUp(self):
        super().setUp()
        self.loan = redemption.parse_loans(self.loans)[0]
        parts = redemption.ledger_positions(
            redemption.parse_loans(self.loans),
            redemption.parse_prepays(self.prepays), date(2026, 9, 4))
        self.fut = parts[0][2]
        self.i = redemption.month_rate(self.loan.rate)

    def test_e1_term_exact_solution(self):
        n_new, new_rows, saving = redemption.simulate_prepay(
            self.fut, "annuity", self.i, 500000.0, "term")
        bal0 = self.fut[0].balance + self.fut[0].principal
        want = redemption.term_periods(bal0 - 500000.0, "annuity", self.i,
                                       self.fut[0].payment, 0.0)
        self.assertEqual(n_new, min(want, len(self.fut)))
        self.assertGreater(saving, 0.0)
        self.assertLess(new_rows[-1].balance, 1e-6)

    def test_e2_payment_exact_new_pay(self):
        n_new, new_rows, saving = redemption.simulate_prepay(
            self.fut, "annuity", self.i, 500000.0, "payment")
        self.assertEqual(n_new, len(self.fut))
        bal0 = self.fut[0].balance + self.fut[0].principal
        want = redemption.annuity_payment(bal0 - 500000.0, self.i,
                                          len(self.fut))
        self.assertAlmostEqual(new_rows[0].payment, want, places=6)
        self.assertGreater(saving, 0.0)

    def test_e3_saving_identity(self):
        for mode in ("term", "payment"):
            _n, new_rows, saving = redemption.simulate_prepay(
                self.fut, "annuity", self.i, 300000.0, mode)
            self.assertAlmostEqual(
                saving,
                redemption.total_interest(self.fut)
                - redemption.total_interest(new_rows), places=6)

    def test_e4_settle_refused(self):
        bal0 = self.fut[0].balance + self.fut[0].principal
        with self.assertRaises(redemption.Refusal):
            redemption.simulate_prepay(self.fut, "annuity", self.i,
                                       bal0, "term")

    def test_e5_one_period_left_refused(self):
        bal0 = self.fut[0].balance + self.fut[0].principal
        # 还到只剩 1 期：预付 = 期初 − 1 期本金的一小半
        amt = bal0 - self.fut[0].principal * 0.2
        with self.assertRaises(redemption.Refusal):
            redemption.simulate_prepay(self.fut, "annuity", self.i,
                                       amt, "term")

    def test_e6_term_saves_more_than_payment(self):
        _n1, _r1, s_t = redemption.simulate_prepay(
            self.fut, "annuity", self.i, 500000.0, "term")
        _n2, _r2, s_p = redemption.simulate_prepay(
            self.fut, "annuity", self.i, 500000.0, "payment")
        self.assertGreaterEqual(s_t, s_p)


class TestEquivalence(unittest.TestCase):
    """等效定理：提前还款 = 年化恰等于合同利率的无风险税后投资。"""

    LOAN_TSV = ("name\tprincipal\trate\tyears\tstart\tmethod\n"
                "贷\t1400000\t4.2\t30\t2021-03-01\tannuity\n")
    LOAN_LIN = ("name\tprincipal\trate\tyears\tstart\tmethod\n"
                "贷\t1400000\t4.2\t30\t2021-03-01\tlinear\n")

    def _fut(self, tsv):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.tsv")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(tsv)
            loan = redemption.parse_loans(p)[0]
        rows, _ = redemption.replay(loan, [])
        return loan, rows[40:]

    def _assert_flat(self, method_txt, mode):
        loan, fut = self._fut(method_txt)
        i = redemption.month_rate(loan.rate)
        wage = 3.0 * fut[0].payment
        w1, w2 = redemption.equivalent_check(fut, loan.method, i,
                                             500000.0, mode, i, wage)
        self.assertAlmostEqual(w1, w2, delta=max(abs(w1) * 1e-9, 1e-6))

    def test_f1_flat_annuity_term(self):
        self._assert_flat(self.LOAN_TSV, "term")

    def test_f2_flat_linear_term(self):
        self._assert_flat(self.LOAN_LIN, "term")

    def test_f3_flat_annuity_payment(self):
        self._assert_flat(self.LOAN_TSV, "payment")

    def test_f4_direction_by_rate_gap(self):
        loan, fut = self._fut(self.LOAN_TSV)
        i = redemption.month_rate(loan.rate)
        wage = 3.0 * fut[0].payment
        lo_p, lo_i = redemption.equivalent_check(
            fut, loan.method, i, 500000.0, "term",
            redemption.month_rate(2.0), wage)
        self.assertGreater(lo_p, lo_i)  # 投资弱 → 还贷世界赢
        hi_p, hi_i = redemption.equivalent_check(
            fut, loan.method, i, 500000.0, "term",
            redemption.month_rate(8.0), wage)
        self.assertLess(hi_p, hi_i)     # 投资强 → 投资世界赢

    def test_f5_wage_invariance_at_contract_rate(self):
        loan, fut = self._fut(self.LOAN_TSV)
        i = redemption.month_rate(loan.rate)
        gaps = []
        for wage_mult in (1.5, 3.0, 10.0):
            wage = wage_mult * fut[0].payment
            w1, w2 = redemption.equivalent_check(fut, loan.method, i,
                                                 500000.0, "term", i, wage)
            gaps.append(w1 - w2)
        for g in gaps:
            self.assertAlmostEqual(g, 0.0, delta=1e-6)


class TestAllocate(unittest.TestCase):
    def _loans(self):
        l1 = redemption.Loan("商贷", "商贷", 935428.0, 4.2, 30,
                             date(2021, 3, 1), "annuity", "", 1)
        l2 = redemption.Loan("公积金", "公积金", 524868.0, 3.1, 30,
                             date(2021, 3, 1), "annuity", "", 2)
        return l1, l2

    def test_g1_rate_descending(self):
        l1, l2 = self._loans()
        out = redemption.allocate(600000.0, [(l1, l1.principal),
                                             (l2, l2.principal)])
        self.assertEqual(out[0][0].key, "商贷")
        self.assertAlmostEqual(out[0][1], 600000.0, places=6)

    def test_g2_fully_allocated(self):
        l1, l2 = self._loans()
        out = redemption.allocate(600000.0, [(l1, l1.principal),
                                             (l2, l2.principal)])
        self.assertAlmostEqual(sum(s for _l, s in out), 600000.0, places=6)

    def test_g3_cap_overflow_to_next(self):
        l1, l2 = self._loans()
        out = redemption.allocate(1200000.0, [(l1, 400000.0), (l2, 600000.0)])
        self.assertAlmostEqual(out[0][1], 400000.0, places=6)
        self.assertAlmostEqual(out[1][1], 600000.0, places=6)
        self.assertAlmostEqual(sum(s for _l, s in out), 1000000.0, places=6)

    def test_g4_zero_when_no_cap(self):
        l1, _ = self._loans()
        out = redemption.allocate(50000.0, [])
        self.assertEqual(out, [])


class TestCommands(Fixture):
    def test_h1_myth_monotonic_earlier_saves_more(self):
        code, out, _err = run(self.args("myth"))
        self.assertEqual(code, 0)
        self.assertIn("省息公式里没有「已还进度」", out)
        self.assertIn("并案谬误二", out)
        nums = [float(line.split("省 ¥")[1].split("（")[0].replace(",", ""))
                for line in out.splitlines() if "（提前" in line and "省 ¥" in line]
        self.assertEqual(len(nums), 3)
        self.assertGreater(nums[0], nums[1])
        self.assertGreater(nums[1], nums[2])

    def test_i1_plan_reads(self):
        code, out, _err = run(self.args("plan"))
        self.assertEqual(code, 0)
        self.assertIn("利息半程点", out)
        self.assertIn("真实利率", out)
        self.assertIn("4.28%", out)
        self.assertIn("双倍房灯未亮", out)
        self.assertIn("组合月供合计 ¥8,780.02/月", out)  # 减供后本期口径 6217.93+2562.10

    def test_i2_plan_double_gate(self):
        self.rewrite(self.loans,
                     "name\tprincipal\trate\tyears\tstart\tmethod\n"
                     "高息\t1000000\t6.5\t30\t2022-01-01\tannuity\n")
        code, out, _err = run(["plan", self.loans, "no-such.tsv"] + TODAY)
        self.assertEqual(code, 4)
        self.assertIn("双倍房灯", out)

    def test_i3_position_three_progress(self):
        code, out, _err = run(self.args("position"))
        self.assertEqual(code, 0)
        self.assertIn("三种进度", out)
        self.assertIn("期数 20.9%", out)
        self.assertIn("今天一次结清全部代价", out)
        self.assertIn("67/281 期（出厂 360", out)

    def test_i4_prepay_all_allocates_high_rate_first(self):
        code, out, _err = run(self.args("prepay", ["--amount", "500000"]))
        self.assertEqual(code, 0)
        self.assertIn("商贷", out)
        self.assertIn("等效收益率定理", out)
        self.assertNotIn("公积金：预付", out)  # 50 万全被高息商贷吃下

    def test_i5_prepay_low_rate_target_exit4(self):
        code, _out, err = run(self.args(
            "prepay", ["--amount", "300000", "--target", "公积金"]))
        self.assertEqual(code, 4)
        self.assertIn("先还低息灯", err)

    def test_i6_prepay_high_rate_target_ok(self):
        code, out, _err = run(self.args(
            "prepay", ["--amount", "300000", "--target", "商贷"]))
        self.assertEqual(code, 0)
        self.assertIn("省息", out)

    def test_i7_compare_term_beats_payment(self):
        code, out, _err = run(self.args("compare", ["--amount", "500000"]))
        self.assertEqual(code, 0)
        self.assertIn("省息差：缩期多省", out)
        self.assertIn("判据（不替你选）", out)

    def test_i8_vsinvest_losing_exit4(self):
        code, out, _err = run(self.args(
            "vsinvest", ["--amount", "500000", "--yield", "2.3"]))
        self.assertEqual(code, 4)
        self.assertIn("跑输灯", out)

    def test_i9_vsinvest_winning_ok(self):
        code, out, _err = run(self.args(
            "vsinvest", ["--amount", "100000", "--yield", "8"]))
        self.assertEqual(code, 0)
        self.assertIn("投资灯", out)

    def test_i10_vsinvest_no_yield_exit3(self):
        code, _out, err = run(self.args(
            "vsinvest", ["--amount", "100000"]))
        self.assertEqual(code, 3)
        self.assertIn("不发明", err)
        self.assertIn("4.28%", err)  # 保本等效线 = 月复利口径

    def test_i11_batch_once_beats_staged(self):
        code, out, _err = run(self.args(
            "batch", ["--total", "500000", "--parts", "5"]))
        self.assertEqual(code, 0)
        self.assertIn("一次还清", out)
        self.assertIn("时间在钱前面", out)

    def test_i11b_batch_parts1_exit2(self):
        code, _out, err = run(self.args(
            "batch", ["--total", "500000", "--parts", "1"]))
        self.assertEqual(code, 2)

    def test_i12_validate_all_green(self):
        code, out, _err = run(self.args("validate"))
        self.assertEqual(code, 0)
        self.assertIn("0.00e+00", out)
        self.assertIn("等效定理", out)
        self.assertIn("分配恒等式", out)

    def test_i13_prepay_small_amount_banner(self):
        code, out, _err = run(self.args("prepay", ["--amount", "5000"]))
        self.assertEqual(code, 0)
        self.assertIn("横幅", out)


class TestEngineering(Fixture):
    def test_j1_stdlib_only(self):
        src = os.path.join(os.path.dirname(__file__), "..",
                           "redemption.py")
        with open(src, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        self.assertTrue(mods <= {
            "argparse", "calendar", "datetime", "math", "re", "sys",
            "unicodedata", "collections", "typing", "os", "io", "ast",
            "unittest", "tempfile", "contextlib", "__future__"},
            f"越界 import：{mods - {'argparse', 'calendar', 'datetime', 'math', 're', 'sys', 'unicodedata', 'collections', 'typing'}}")

    def test_j2_byte_identical_reruns(self):
        outs = []
        for _ in range(2):
            code, out, _err = run(self.args("plan"))
            self.assertEqual(code, 0)
            outs.append(out)
        self.assertEqual(outs[0], outs[1])

    def test_j3_cli_surface(self):
        from contextlib import redirect_stderr as _re
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            with self.assertRaises(SystemExit) as ctx:
                run(["--version"])
            self.assertEqual(ctx.exception.code, 0)
            with self.assertRaises(SystemExit):
                run([])
            with self.assertRaises(SystemExit):
                run(["nope", "a", "b"])
        finally:
            sys.stderr = saved

    def test_j4_examples_bite_constants(self):
        here = os.path.join(os.path.dirname(__file__), "..", "examples")
        with open(os.path.join(here, "loans.tsv"), encoding="utf-8") as fh:
            self.assertIn("商贷\t1400000\t4.2\t30\t2021-03-01\tannuity", fh.read())
        with open(os.path.join(here, "sample-vsinvest.txt"),
                  encoding="utf-8") as fh:
            self.assertIn("跑输灯", fh.read())
        with open(os.path.join(here, "sample-prepay-target.txt"),
                  encoding="utf-8") as fh:
            self.assertIn("先还低息灯", fh.read())


if __name__ == "__main__":
    unittest.main()
