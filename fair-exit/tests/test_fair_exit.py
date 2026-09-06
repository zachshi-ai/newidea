#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fair-exit acceptance tests.

Every headline number is hand-computed first and pinned here; if the CLI
disagrees with arithmetic done on paper, the test wins.

Demo ledger (老周 · 星云科技), as-of 2026-08-31 (the ledger's own anchor):

  tenure   2021-03-15 → 2026-08-31  协商解除  offer 105000  竞业 6 个月未约定补偿
  payslips 2025-09..2026-08 共 12 行: 24000×11 + 66000(2026-01 含 42000 年终奖)
           overtime 列 2026-05 = 3000（已付加班费单列）
           → Σgross 330000 · Σot 3000
           → comp_base (330000+3000)/12 = 27750.00
           → leave_base 330000/12 = 27500.00 · 日薪 27500/21.75 = 1264.367816...
  N        5 整年 + 5 整月 16 天（<6 整月）→ 5.5 个月
  经济补偿  5.5 × 27750 = 152,625.00（协商解除，法定无 +1）
  年假     2025: 10-8 → 2 天 · 2026: floor(10×243/365)=6, 6-1 → 5 天
           7 × 1264.367816... × 2 = 17,701.149425... → 17,701.15
  加班费    时薪 27500/21.75/8 = 158.045977...
           6h×2× + 3h×1.5× + 4h×2× = 3872.126436... → 3,872.13
  硬应得    152625 + 17701.149... + 3872.126... = 174,198.2758... → 174,198.28
  check    offer 105000 → 差额 +69,198.28 → exit 4
  竞业      0.30 × 27750 × 6 = 49,950.00（条件主张，不进合计）
  2N 世界   2×5.5×27750 + 年假 + 加班 = 326,823.28；与法定世界之差 ≡ 152,625.00
  clock    2026-08-31 + 365 = 2027-08-31，剩 365 天
"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
CLI = os.path.join(ROOT, "fair-exit", "fair_exit.py")
DEMO = os.path.join(ROOT, "fair-exit", "examples", "demo-data")

sys.path.insert(0, os.path.join(ROOT, "fair-exit"))
import fair_exit as fx  # noqa: E402
from datetime import date  # noqa: E402


def run_cli(*args):
    proc = subprocess.run([sys.executable, CLI] + list(args),
                          capture_output=True, text=True)
    return proc.stdout, proc.returncode


class TmpLedgerCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def ledger(self, tenure=None, payslips=None, leave=None, overtime=None):
        tenure = tenure or [
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tmutual\t\t\t\t"]
        payslips = payslips if payslips is not None else (
            ["month\tgross\tovertime\tnote"]
            + ["%s\t10000\t\t" % ("2025-%02d" % m) for m in range(9, 13)]
            + ["%s\t10000\t\t" % ("2026-%02d" % m) for m in range(1, 9)])
        leave = leave if leave is not None else [
            "year\tentitled\tused\tnote",
            "2025\t5\t5\t", "2026\t5\t2\t"]
        t = self.write("tenure.tsv", "\n".join(tenure) + "\n")
        p = self.write("payslips.tsv", "\n".join(payslips) + "\n")
        l = self.write("leave.tsv", "\n".join(leave) + "\n")
        # 空文件 = 无加班流水（load_tsv 对无数据行返回空）
        o = self.write("overtime.tsv",
                       "\n".join(overtime if overtime is not None else []) + "\n")
        return t, p, l, o


# ---------------------------------------------------------------------------
# A. 纯函数层：经济补偿年限折算边界（法条 47 条的 6 整月线）

class TestSeveranceMonths(TmpLedgerCase):
    def test_full_years_only(self):
        self.assertEqual(fx.severance_months(
            date(2021, 3, 15), date(2026, 3, 15)), 5.0)

    def test_remainder_six_full_months_inclusive(self):
        # 六个月「以上」含本数 → 按一年
        self.assertEqual(fx.severance_months(
            date(2021, 3, 15), date(2026, 9, 15)), 6.0)

    def test_remainder_one_day_short(self):
        self.assertEqual(fx.severance_months(
            date(2021, 3, 15), date(2026, 9, 14)), 5.5)

    def test_demo_span(self):
        self.assertEqual(fx.severance_months(
            date(2021, 3, 15), date(2026, 8, 31)), 5.5)

    def test_few_months_gets_half(self):
        self.assertEqual(fx.severance_months(
            date(2026, 1, 1), date(2026, 3, 1)), 0.5)

    def test_zero_days_gets_half(self):
        # 入职当天解除也是「不满六个月」——法条原文口径
        self.assertEqual(fx.severance_months(
            date(2026, 5, 10), date(2026, 5, 10)), 0.5)

    def test_eleven_months_rounds_up(self):
        self.assertEqual(fx.severance_months(
            date(2024, 9, 1), date(2025, 8, 31)), 1.0)

    def test_feb29_anniversary_clamp(self):
        # 闰日入职：周年钳到 02-28；再多 1 天 → 1 年 + 不满 6 个月 = 1.5
        self.assertEqual(fx.severance_months(
            date(2020, 2, 29), date(2021, 2, 28)), 1.0)
        self.assertEqual(fx.severance_months(
            date(2020, 2, 29), date(2021, 3, 1)), 1.5)

    def test_month_end_clamp_walk_vs_fast(self):
        # 月末入职的钳位边界：两算法在 3 起步日 × 40 月 × 6 偏移的网格上全等
        for base_d in (date(2020, 1, 31), date(2021, 3, 15), date(2019, 2, 28)):
            for k in range(0, 40):
                for delta in (-1, 0, 1, 182, 183, 184):
                    d2 = fx.add_days(fx.add_months_clamped(base_d, k), delta)
                    if d2 < base_d:
                        continue
                    self.assertAlmostEqual(
                        fx.severance_months(base_d, d2),
                        fx.severance_months_fast(base_d, d2), places=9,
                        msg="%s → %s" % (base_d, d2))


# ---------------------------------------------------------------------------
# B. 引擎层：基数、年假、加班费（demo 账本直接驱动）

class TestEngineDemo(TmpLedgerCase):
    def setUp(self):
        super().setUp()
        led = fx.build_ledger(
            os.path.join(DEMO, "tenure.tsv"),
            os.path.join(DEMO, "payslips.tsv"),
            os.path.join(DEMO, "leave.tsv"),
            os.path.join(DEMO, "overtime.tsv"),
            None, fx.LEAVE_DEFAULT)
        self.eng = fx.engine(led, False, fx.LEAVE_RATE, None,
                             fx.NONCOMP_RATE, None, fx.LEAVE_DEFAULT)

    def test_base_dual_calibers(self):
        self.assertAlmostEqual(self.eng.comp_base, 27750.00, places=6)
        self.assertAlmostEqual(self.eng.leave_base, 27500.00, places=6)
        self.assertAlmostEqual(self.eng.day_rate, 27500 / 21.75, places=6)

    def test_n(self):
        self.assertEqual(self.eng.n_months, 5.5)

    def test_severance_amount(self):
        self.assertAlmostEqual(self.eng.comp_amount, 152625.00, places=6)

    def test_notice_statutory_none_for_mutual(self):
        self.assertEqual(self.eng.notice_amount, 0.0)
        self.assertIn("协商解除", self.eng.notice_note)

    def test_leave_conversion(self):
        self.assertAlmostEqual(self.eng.leave_days, 7.0, places=9)
        self.assertAlmostEqual(self.eng.leave_total,
                               7 * (27500 / 21.75) * 2, places=6)
        by_year = {it.year: it for it in self.eng.leave_items}
        self.assertEqual(by_year[2025].rounded, 10.0)
        self.assertEqual(by_year[2025].unused, 2.0)
        self.assertEqual(by_year[2026].rounded, 6.0)   # floor(10×243/365)
        self.assertEqual(by_year[2026].unused, 5.0)

    def test_overtime_total(self):
        h = 27500 / 21.75 / 8
        want = 6 * 2 * h + 3 * 1.5 * h + 4 * 2 * h
        self.assertAlmostEqual(self.eng.ot_total, want, places=6)
        self.assertAlmostEqual(round(self.eng.ot_total, 2), 3872.13, places=2)

    def test_hard_total_and_identity(self):
        self.assertAlmostEqual(round(self.eng.hard_total, 2),
                               174198.28, places=2)
        resid = abs((self.eng.comp_amount + self.eng.notice_amount +
                     self.eng.leave_total + self.eng.ot_total) -
                    self.eng.hard_total)
        self.assertLess(resid, 1e-9)

    def test_noncomp_conditional_claim(self):
        self.assertAlmostEqual(self.eng.noncomp_claim, 49950.00, places=6)
        self.assertTrue(self.eng.noncomp_missing)

    def test_as_of_anchors_to_ledger_end(self):
        self.assertEqual(self.eng.led.as_of, date(2026, 8, 31))


# ---------------------------------------------------------------------------
# C. 口径翻案（旗标永远赢）

class TestFlags(TmpLedgerCase):
    def demo(self, *flags):
        argv = ["report"] + list(flags) + [
            os.path.join(DEMO, "tenure.tsv"),
            os.path.join(DEMO, "payslips.tsv"),
            os.path.join(DEMO, "leave.tsv"),
            os.path.join(DEMO, "overtime.tsv")]
        return run_cli(*argv)

    def test_exclude_overtime_flag(self):
        out, _ = self.demo("--exclude-overtime")
        self.assertIn("剔加班费", out)
        self.assertIn("27,500.00（应发平均", out)

    def test_leave_rate_flag(self):
        out, _ = self.demo("--leave-rate", "3.0")
        self.assertIn("300%", out)
        # 7 × (27500/21.75) × 3 = 26551.7241... → 26,551.72
        self.assertIn("26,551.72", out)

    def test_soc_double_cap_base_only(self):
        out, _ = self.demo("--soc-avg", "8000")
        self.assertIn("DOUBLE-CAP", out)
        self.assertIn("24,000.00", out)     # 3 × 8000 < 27,750
        self.assertIn("5.5 × 24,000.00 = 132,000.00", out)

    def test_min_wage_floor(self):
        t, p, l, o = self.ledger()
        out, code = run_cli("report", "--min-wage", "15000", t, p, l, o)
        self.assertEqual(code, 0)
        self.assertIn("DOUBLE-CAP", out)
        self.assertIn("15,000.00", out)


# ---------------------------------------------------------------------------
# D. 解除形式五分法

class TestKinds(TmpLedgerCase):
    def test_resign_zero_comp_but_leave_and_ot_paid(self):
        t, p, l, o = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\t辞职\t\t\t\t"])
        out, code = run_cli("report", t, p, l, o)
        self.assertEqual(code, 0)
        self.assertIn("主动辞职无经济补偿", out)
        self.assertIn("与辞职理由无关", out)
        # 年假照算：2026 折算 floor(5×243/365)=3，未休 1 天 × (10000/21.75) × 2
        h = 10000 / 21.75
        self.assertIn(money_of(1 * h * 2), out)

    def test_nofault_statutory_plus_one(self):
        t, p, l, o = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tnofault\t\t\t\t"])
        out, _ = run_cli("report", t, p, l, o)
        self.assertIn("法定 +1（按 2026-08 应发 10,000.00）", out)
        self.assertIn("10,000.00", out)

    def test_nofault_notice_already_paid(self):
        t, p, l, o = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tnofault\t\ty\t\t"])
        out, _ = run_cli("report", t, p, l, o)
        self.assertIn("代通知金已单独支付", out)

    def test_illegal_2n(self):
        t, p, l, o = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\t违法\t\t\t\t"])
        out, _ = run_cli("report", t, p, l, o)
        # N=2.0，2N = 2×2×10000 = 40000；2026 未休 1 天 = 1×(10000/21.75)×2
        h = 10000 / 21.75
        self.assertIn("2 × 2.0 × 10,000.00 = 40,000.00", out)
        self.assertIn(money_of(1 * h * 2), out)

    def test_expiry_note(self):
        t, p, l, o = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\t到期\t\t\t\t"])
        out, _ = run_cli("report", t, p, l, o)
        self.assertIn("到期终止无法定 +1", out)


def money_of(x):
    return "{:,.2f}".format(x)


# ---------------------------------------------------------------------------
# E. 竞业限制审计

class TestNoncomp(TmpLedgerCase):
    def test_below_line_topup(self):
        t, p, l, o = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tmutual\t\t\t6\t2000"])
        out, _ = run_cli("report", t, p, l, o)
        # 线 0.30×10000 = 3000 > 2000 → 补差 (3000-2000)×6 = 6000
        self.assertIn("6,000.00", out)
        self.assertIn("可主张补差", out)

    def test_at_line_ok(self):
        t, p, l, o = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tmutual\t\t\t6\t3000"])
        out, _ = run_cli("report", t, p, l, o)
        self.assertIn("月补已达标", out)
        self.assertIn("—   月补已达标", out)
        self.assertNotIn("可主张补差", out)

    def test_over_24_months_capped(self):
        t, p, l, o = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tmutual\t\t\t36\t10000"])
        out, _ = run_cli("report", t, p, l, o)
        self.assertIn("LEGAL-CAP", out)
        self.assertIn("按 24 算", out)


# ---------------------------------------------------------------------------
# F. 双封顶引擎层（合成账本，已知真值）

class TestDoubleCap(TmpLedgerCase):
    def ledger12(self, gross):
        return self.ledger(
            tenure=["employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
                    "测试公司\t2022-01-10\t2024-03-25\tmutual\t\t\t\t"],
            payslips=["month\tgross\tovertime\tnote"]
            + ["%s\t%d\t\t" % (m, gross) for m in _months("2022-01", "2024-03")],
            leave=["year\tentitled\tused\tnote", "2022\t5\t5\t",
                   "2023\t5\t5\t", "2024\t5\t5\t"])

    def test_soc_cap_base_not_years(self):
        t, p, l, o = self.ledger12(50000)
        out, _ = run_cli("report", "--soc-avg", "15000", t, p, l, o)
        # N: 2022-01-10→2024-03-25 = 2 年 + 2 整月 15 天 → 2.5；基数 3×15000
        self.assertIn("2.5 × 45,000.00 = 112,500.00", out)
        self.assertIn("基数按社平 3 倍封顶（年限未触 12 年封顶）", out)

    def test_soc_cap_years_too(self):
        t, p, l, o = self.ledger(
            tenure=["employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
                    "测试公司\t2000-01-01\t2024-03-31\tmutual\t\t\t\t"],
            payslips=["month\tgross\tovertime\tnote"]
            + ["%s\t60000\t\t" % m for m in _months("2023-04", "2024-03")],
            leave=["year\tentitled\tused\tnote", "2023\t5\t5\t",
                   "2024\t5\t5\t"])
        out, _ = run_cli("report", "--soc-avg", "15000", t, p, l, o)
        # 年限 24 年 → 封 12；基数 60000 → 封 45000
        self.assertIn("12.0 × 45,000.00 = 540,000.00", out)
        self.assertIn("年限按 12 年封顶", out)


def _months(a, b):
    out = []
    y, m = int(a[:4]), int(a[5:])
    ey, em = int(b[:4]), int(b[5:])
    while (y, m) <= (ey, em):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ---------------------------------------------------------------------------
# G. CLI 出口码与门禁

class TestCliExits(TmpLedgerCase):
    DEMOARGS = [os.path.join(DEMO, f) for f in
                ("tenure.tsv", "payslips.tsv", "leave.tsv", "overtime.tsv")]

    def test_check_shortfall_exit4(self):
        out, code = run_cli("check", *self.DEMOARGS)
        self.assertEqual(code, 4)
        self.assertIn("174,198.28", out)
        self.assertIn("+69,198.28", out)
        self.assertIn("SHORTFALL", out)
        self.assertIn("一次性了结", out)

    def test_check_green_exit0(self):
        led = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tmutual\t40000\t\t\t"])
        out, code = run_cli("check", *led)
        self.assertEqual(code, 0)
        self.assertIn("不低于法定账面硬应得", out)

    def test_check_no_offer_exit3(self):
        led = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tmutual\t\t\t\t"])
        out, code = run_cli("check", *led)
        self.assertEqual(code, 3)
        self.assertIn("没有报价，无从对质", out)

    def test_clock_green_365(self):
        out, code = run_cli("clock", *self.DEMOARGS)
        self.assertEqual(code, 0)
        self.assertIn("2027-08-31", out)
        self.assertIn("365 天", out)
        self.assertIn("绿灯", out)

    def test_clock_caution_window(self):
        led = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tmutual\t\t\t\t"])
        out, code = run_cli("clock", "--as-of", "2027-07-15", *led)
        self.assertEqual(code, 0)
        self.assertIn("CAUTION", out)

    def test_clock_expired_told_as_is(self):
        led = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tmutual\t\t\t\t"])
        out, code = run_cli("clock", "--as-of", "2027-09-30", *led)
        self.assertEqual(code, 0)
        self.assertIn("EXPIRED", out)
        self.assertIn("账本不装救护车", out)

    def test_report_thin_when_working(self):
        led = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t\tmutual\t\t\t\t"])
        out, code = run_cli("report", *led)
        self.assertEqual(code, 3)
        self.assertIn("DECLINED", out)
        self.assertIn("在职", out)

    def test_worlds_needs_offer(self):
        led = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\tmutual\t\t\t\t"])
        out, code = run_cli("worlds", *led)
        self.assertEqual(code, 3)


# ---------------------------------------------------------------------------
# H. 账坏 exit 2（抄录错误挡在算术前面）

class TestBrokenLedger(TmpLedgerCase):
    GOOD_TENURE = ("employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly\n"
                   "测试公司\t2024-09-01\t2026-08-31\tmutual\t\t\t\t\n")

    def broken(self, tenure=None, payslips=None, leave=None, overtime=None):
        t, p, l, o = self.ledger(tenure, payslips, leave, overtime)
        out, code = run_cli("report", t, p, l, o)
        return out, code

    def test_two_tenure_rows(self):
        out, code = self.broken(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "甲\t2024-09-01\t2026-08-31\tmutual\t\t\t\t",
            "乙\t2024-09-01\t2026-08-31\tmutual\t\t\t\t"])
        self.assertEqual(code, 2)
        self.assertIn("恰好 1 行", out)

    def test_end_before_start(self):
        out, code = self.broken(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2026-08-31\t2024-09-01\tmutual\t\t\t\t"])
        self.assertEqual(code, 2)

    def test_unknown_kind(self):
        out, code = self.broken(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\t炒股\t\t\t\t"])
        self.assertEqual(code, 2)
        self.assertIn("kind 未知", out)

    def test_duplicate_payslip_month(self):
        ps = ["month\tgross\tovertime\tnote",
              "2026-08\t10000\t\t", "2026-08\t12000\t\t"]
        ps += ["%s\t10000\t\t" % m for m in _months("2025-09", "2026-07")]
        out, code = self.broken(payslips=ps)
        self.assertEqual(code, 2)
        self.assertIn("月份重复", out)

    def test_payslip_after_end_month(self):
        ps = ["month\tgross\tovertime\tnote"]
        ps += ["%s\t10000\t\t" % m for m in _months("2025-09", "2026-08")]
        ps.append("2026-09\t5000\t\t补发")
        out, code = self.broken(payslips=ps)
        self.assertEqual(code, 2)
        self.assertIn("晚于解除月", out)

    def test_payslip_before_start_month(self):
        ps = ["month\tgross\tovertime\tnote", "2024-08\t10000\t\t"]
        ps += ["%s\t10000\t\t" % m for m in _months("2025-09", "2026-08")]
        out, code = self.broken(payslips=ps)
        self.assertEqual(code, 2)
        self.assertIn("早于入职月", out)

    def test_negative_gross(self):
        ps = ["month\tgross\tovertime\tnote"]
        ps += ["%s\t10000\t\t" % m for m in _months("2025-09", "2026-08")]
        ps.append("2026-08\t-500\t\t")
        out, code = self.broken(payslips=ps)
        self.assertEqual(code, 2)
        self.assertIn("负数", out)

    def test_duplicate_leave_year(self):
        lv = ["year\tentitled\tused\tnote",
              "2025\t5\t5\t", "2025\t5\t0\t", "2026\t5\t2\t"]
        out, code = self.broken(leave=lv)
        self.assertEqual(code, 2)
        self.assertIn("年度重复", out)

    def test_leave_year_out_of_tenure(self):
        lv = ["year\tentitled\tused\tnote",
              "2025\t5\t5\t", "2026\t5\t2\t", "2030\t5\t0\t"]
        out, code = self.broken(leave=lv)
        self.assertEqual(code, 2)
        self.assertIn("任期之外", out)

    def test_weekend_claim_on_wednesday(self):
        ot = ["date\thours\tkind\tnote", "2026-07-29\t2\tweekend\t"]
        out, code = self.broken(overtime=ot)
        self.assertEqual(code, 2)
        self.assertIn("日历对质失败", out)

    def test_workday_claim_on_saturday(self):
        ot = ["date\thours\tkind\tnote", "2026-08-01\t2\tworkday\t"]
        out, code = self.broken(overtime=ot)
        self.assertEqual(code, 2)
        self.assertIn("日历对质失败", out)

    def test_unknown_ot_kind(self):
        ot = ["date\thours\tkind\tnote", "2026-08-01\t2\t三倍\t"]
        out, code = self.broken(overtime=ot)
        self.assertEqual(code, 2)
        self.assertIn("kind 未知", out)

    def test_missing_column(self):
        t = self.write("tenure.tsv",
                       "employer\tstart\tend\n测试公司\t2024-09-01\t2026-08-31\n")
        p = self.write("payslips.tsv", "month\tgross\n2026-08\t1\n")
        l = self.write("leave.tsv", "year\tentitled\tused\n2026\t5\t0\n")
        out, code = run_cli("report", t, p, l)
        self.assertEqual(code, 2)
        self.assertIn("缺列", out)


# ---------------------------------------------------------------------------
# I. as-of 时间机器与确定性

class TestAsOfAndDeterminism(TmpLedgerCase):
    DEMOARGS = [os.path.join(DEMO, f) for f in
                ("tenure.tsv", "payslips.tsv", "leave.tsv", "overtime.tsv")]

    def test_asof_before_end_is_working_view(self):
        out, code = run_cli("report", "--as-of", "2026-06-30", *self.DEMOARGS)
        self.assertEqual(code, 3)
        self.assertIn("DECLINED", out)
        self.assertIn("AS-OF 剪除工资月 2026-07,2026-08", out)
        self.assertIn("账面 10 行", out)

    def test_asof_after_end_same_as_default(self):
        out1, c1 = run_cli("report", *self.DEMOARGS)
        out2, c2 = run_cli("report", "--as-of", "2026-09-30", *self.DEMOARGS)
        self.assertEqual(c1, c2)
        self.assertIn("174,198.28", out2)

    def test_byte_identical_rerun(self):
        out1, c1 = run_cli("report", *self.DEMOARGS)
        out2, c2 = run_cli("report", *self.DEMOARGS)
        self.assertEqual(c1, c2)
        self.assertEqual(out1, out2)

    def test_basename_only(self):
        out, _ = run_cli("report", *self.DEMOARGS)
        self.assertNotIn(DEMO, out)
        self.assertIn("tenure.tsv + payslips.tsv", out)

    def test_command_aliases(self):
        for alias, canon in (("sign", "check"), ("statement", "report"),
                             ("verify", "validate"), ("deadline", "clock"),
                             ("scenarios", "worlds")):
            o1, c1 = run_cli(alias, *self.DEMOARGS)
            o2, c2 = run_cli(canon, *self.DEMOARGS)
            self.assertEqual((o1, c1), (o2, c2), alias)

    def test_chinese_columns_and_kind(self):
        led = self.ledger(
            tenure=["单位\t入职\t解除\t类型\t报价\t代通知金\t竞业月数\t竞业月补",
                    "测试公司\t2024-09-01\t2026-08-31\t协商\t\t\t\t"],
            payslips=["月份\t应发\t加班费\t备注"]
            + ["%s\t10000\t\t" % m for m in _months("2025-09", "2026-08")],
            leave=["年度\t应享\t已休\t备注", "2025\t5\t5\t", "2026\t5\t2\t"])
        out, code = run_cli("report", *led)
        self.assertEqual(code, 0)
        self.assertIn("2.0 × 10,000.00 = 20,000.00", out)

    def test_no_wall_clock_in_source(self):
        with open(CLI, encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("date.today", "datetime.now", "time.time", "utcnow"):
            self.assertNotIn(banned, src)


# ---------------------------------------------------------------------------
# J. worlds / validate 恒等式

class TestIdentities(TmpLedgerCase):
    DEMOARGS = [os.path.join(DEMO, f) for f in
                ("tenure.tsv", "payslips.tsv", "leave.tsv", "overtime.tsv")]

    def test_worlds_three_rows_and_identities(self):
        out, code = run_cli("worlds", *self.DEMOARGS)
        self.assertEqual(code, 0)
        self.assertIn("105,000.00", out)
        self.assertIn("174,198.28", out)
        self.assertIn("326,823.28", out)
        self.assertIn("≡ check 差额 +69,198.28", out)
        self.assertIn("≡ 经济补偿本身", out)
        self.assertIn("152,625.00", out)

    def test_worlds_resign_has_no_2n_door(self):
        led = self.ledger(tenure=[
            "employer\tstart\tend\tkind\toffer\tnotice\tnoncomp_months\tnoncomp_monthly",
            "测试公司\t2024-09-01\t2026-08-31\t辞职\t1000\t\t\t"])
        out, code = run_cli("worlds", *led)
        self.assertEqual(code, 0)
        self.assertIn("主动辞职没有这扇门", out)

    def test_validate_green(self):
        out, code = run_cli("validate", *self.DEMOARGS)
        self.assertEqual(code, 0)
        self.assertIn("全部体检通过", out)
        self.assertIn("N 双算法一致", out)
        self.assertIn("年假舍尾边界", out)

    def test_snapshot_builder_check(self):
        script = os.path.join(ROOT, "fair-exit", "examples",
                              "build_examples.py")
        if not os.path.exists(script):
            self.skipTest("build_examples.py missing")
        proc = subprocess.run([sys.executable, script, "--check"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
