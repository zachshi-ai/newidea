# -*- coding: utf-8 -*-
"""实掏 · True Pocket — acceptance tests.

Hand-computed ground truth first (样例数字先手算再钉):
  example ledger: 陈家 2026 年 14 笔结算单。
  Σtotal  = 41,903.70   Σpool = 18,437.74 (44.0% 接住)
  Σacct   =  3,270.56   Σcash = 20,195.40
  真口袋  = 23,465.96 = Σown 10,865.96 + Σ自费 12,600.00 (分担恒等)
  严格现金= 20,195.40
  deduce: 基数 10,865.96 < 15,000 → 未达线，差 4,134.04。
  progress 门诊 1800 线: 爸爸累计 3,149.90 REACHED，跨线笔 04-14
    （线前 240.00 = 1800 − 1,560.00，线后 383.40，×60% = 230.04）；
    妈妈 792.00 差 1,008.00；小满 784.80；自己 268.40（种植牙 8,600
    全目录外，推不动进度条）。
  family: 爸爸 5,796.56 + 妈妈 8,016.20 + 小满 784.80 + 自己 8,868.40
    = 23,465.96（Σ成员恒等）。
  CAT: income 120,000 → 19.6% 不亮；50,000 → 46.9% exit 4；
    恰 40%（income 58,664.90）不亮（宁可少亮一盏灯）。
  as-of 2026-06-30 剪切后: 7 笔，Σtotal 20,944.00，抵扣基数 6,505.56。
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
EXAMPLES = os.path.join(PKG, "examples")
LEDGER = os.path.join(EXAMPLES, "settlements.tsv")
CLI = os.path.join(PKG, "true_pocket.py")

sys.path.insert(0, PKG)
import true_pocket  # noqa: E402

HEADER = ["date", "hospital", "member", "category", "total", "pool",
          "acct", "cash", "own", "cat_out", "note"]


def go(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = true_pocket.main(list(args))
    return code, out.getvalue(), err.getvalue()


def write_ledger(tmp, rows, header=None, name="settlements.tsv"):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(header or HEADER) + "\n")
        for row in rows:
            fh.write("\t".join(str(c) for c in row) + "\n")
    return path


def row(date, member, cat, total, pool, acct, cash, own, cat_out,
        hospital="市一院", note="x"):
    return [date, hospital, member, cat, total, pool, acct, cash,
            own, cat_out, note]


class ExampleLedger(unittest.TestCase):
    """钉值：样例账本上的全部关键读数。"""

    def test_report_annual_totals(self):
        code, out, _ = go(LEDGER, "report", "--income", "120000")
        self.assertEqual(code, 0)
        for want in ("41,903.70", "18,437.74", "23,465.96", "20,195.40",
                     "10,865.96", "12,600.00", "3,270.56", "19.6%",
                     "LAMP OK"):
            self.assertIn(want, out)

    def test_report_no_income_no_judgment(self):
        code, out, _ = go(LEDGER, "report")
        self.assertEqual(code, 0)
        self.assertIn("不发明你的收入", out)
        self.assertNotIn("LAMP CATASTROPHIC", out)

    def test_report_cat_gate_exit4(self):
        code, out, _ = go(LEDGER, "report", "--income", "50000")
        self.assertEqual(code, 4)
        self.assertIn("46.9%", out)
        self.assertIn("CATASTROPHIC", out)

    def test_report_cat_exactly_at_line_stays_dark(self):
        # 23,465.96 / 0.40 = 58,664.90 → ratio 恰 0.40：宁可少亮一盏灯
        code, out, _ = go(LEDGER, "report", "--income", "58664.90")
        self.assertEqual(code, 0)
        self.assertIn("LAMP OK", out)

    def test_report_cat_just_above_line_fires(self):
        code, _, _ = go(LEDGER, "report", "--income", "58664")
        self.assertEqual(code, 4)

    def test_report_two_pocket_definitions(self):
        code, out, _ = go(LEDGER, "report")
        self.assertIn("实掏·真口袋   23,465.96", out)
        self.assertIn("实掏·严格口径 20,195.40", out)
        self.assertIn("两个词，不是一回事", out)

    def test_progress_threshold_reached_and_split(self):
        code, out, _ = go(LEDGER, "progress", "--threshold", "1800",
                          "--rate-after", "0.6", "--category", "门诊")
        self.assertEqual(code, 0)
        self.assertIn("爸爸     REACHED", out)
        self.assertIn("3,149.90", out)
        self.assertIn("线前 240.00 / 线后 383.40", out)
        self.assertIn("60% 统筹 = 230.04", out)

    def test_progress_member_gaps_and_implant_freeze(self):
        code, out, _ = go(LEDGER, "progress", "--threshold", "1800")
        self.assertEqual(code, 0)
        self.assertIn("差 1,008.00   累计 792.00", out)     # 妈妈
        self.assertIn("差 1,015.20   累计 784.80", out)     # 小满
        self.assertIn("差 1,531.60   累计 268.40", out)     # 自己：种植牙不推进
        self.assertNotIn("全家无人到线", out)  # 有爸爸到线

    def test_progress_basis_changes_what_counts(self):
        # total 口径下种植牙 8,600 推进度 → 自己 REACHED（误判示范）
        code, out, _ = go(LEDGER, "progress", "--threshold", "1800",
                          "--basis", "total")
        self.assertEqual(code, 0)
        self.assertIn("自己     REACHED", out)
        self.assertIn("8,868.40", out)

    def test_progress_no_threshold_no_policy_invented(self):
        code, out, _ = go(LEDGER, "progress")
        self.assertEqual(code, 0)
        self.assertIn("不发明政策，不判进度", out)
        self.assertIn("爸爸", out)

    def test_deduce_below_line_honest_gap(self):
        code, out, _ = go(LEDGER, "deduce")
        self.assertEqual(code, 0)
        self.assertIn("10,865.96", out)
        self.assertIn("还差 4,134.04", out)
        self.assertIn("未达起抵线", out)

    def test_deduce_above_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "住院", "35000", "20000", "0",
                    "15000", "15000", "0", note="x"),
                row("2026-05-01", "自己", "住院", "10000", "4000", "0",
                    "6000", "6000", "0", note="y"),
            ])
            code, out, _ = go(p, "deduce")
            self.assertEqual(code, 0)
            self.assertIn("21,000.00", out)          # 基数 15000+6000
            self.assertIn("超线部分 6,000.00", out)   # 21000-15000
            self.assertIn("可抵扣 6,000.00", out)

    def test_deduce_tax_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "住院", "50000", "30000", "0",
                    "20000", "20000", "0"),
            ])
            code, out, _ = go(p, "deduce", "--tax-rate", "0.2")
            self.assertEqual(code, 0)
            self.assertIn("超线部分 5,000.00", out)   # 20000-15000
            self.assertIn("省税 ≈ 1,000.00", out)     # 5000×0.2

    def test_deduce_boundary_15000_01(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "住院", "35000", "19999.99", "0",
                    "15000.01", "15000.01", "0"),
            ])
            code, out, _ = go(p, "deduce")
            self.assertEqual(code, 0)
            self.assertIn("超线部分 0.01", out)

    def test_deduce_cap_80000(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "住院", "200000", "100000", "0",
                    "100000", "100000", "0"),
            ])
            code, out, _ = go(p, "deduce")
            self.assertEqual(code, 0)
            self.assertIn("超过限额 80,000.00", out)
            self.assertIn("可抵扣 80,000.00", out)

    def test_deduce_assumed_disclosure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "0", "500", "0",
                    "", ""),
            ])
            code, out, _ = go(p, "deduce")
            self.assertEqual(code, 0)
            self.assertIn("ASSUMED", out)
            self.assertIn("500.00", out)

    def test_claim_stated_and_crosschecked(self):
        code, out, _ = go(LEDGER, "claim", "--date", "2026-02-14")
        self.assertEqual(code, 0)
        self.assertIn("4,224.20", out)
        self.assertIn("声明列，已过交叉验证", out)
        self.assertIn("拒赔的经典开场", out)

    def test_claim_missing_date_exit2(self):
        code, _, _ = go(LEDGER, "claim", "--date", "2026-02-20")
        self.assertEqual(code, 2)

    def test_claim_derived_from_cat_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "1200", "400", "0", "800",
                    "", "600.00"),
            ])
            code, out, _ = go(p, "claim", "--date", "2026-03-01")
            self.assertEqual(code, 0)
            self.assertIn("反解", out)
            self.assertIn("200.00", out)  # 800 - 600

    def test_claim_assumed_upper_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "0", "500", "0",
                    "", ""),
            ])
            code, out, _ = go(p, "claim", "--date", "2026-03-01")
            self.assertEqual(code, 0)
            self.assertIn("ASSUMED", out)

    def test_claim_all_lists_full_year(self):
        code, out, _ = go(LEDGER, "claim", "--all")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n  2026-"), 14)  # 表体 14 行
        self.assertNotIn("ASSUMED", out)  # 样例账本全部拆齐

    def test_family_members_and_identity(self):
        code, out, _ = go(LEDGER, "family")
        self.assertEqual(code, 0)
        for want in ("爸爸", "5,796.56", "妈妈", "8,016.20",
                     "小满", "784.80", "自己", "8,868.40",
                     "23,465.96", "恒等校验残差 0.0000",
                     "个账消耗榜"):
            self.assertIn(want, out)

    def test_validate_clean(self):
        code, out, _ = go(LEDGER, "validate")
        self.assertEqual(code, 0)
        self.assertIn("三支付恒等】14 行全部通过", out)
        self.assertIn("分担交叉验证】14 行", out)
        self.assertIn("LAMP OK", out)


class LedgerLaws(unittest.TestCase):
    """恒等式与口径：账本坏了宁可 exit 2 也不带病出账。"""

    def test_three_pay_identity_within_eps_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "100", "200",
                    "199.99", "399.99", "0"),  # 499.99，差恰 0.01 在 EPS 内
            ])
            code, _, _ = go(p, "report")
            self.assertEqual(code, 0)

    def test_three_pay_identity_beyond_eps_exit2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "100", "200",
                    "198", "398", "0"),  # 差 0.02 > EPS
            ])
            code, _, _ = go(p, "report")
            self.assertEqual(code, 2)
            self.assertIn("三支付恒等破裂", _)

    def test_split_cross_identity_broken_exit2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "0", "300", "200",
                    "400", "200"),  # 400+200=600 ≠ 500
            ])
            code, _, err = go(p, "report")
            self.assertEqual(code, 2)
            self.assertIn("分担交叉恒等破裂", err)

    def test_negative_amount_exit2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "-100", "300",
                    "300", "600", "0"),
            ])
            code, _, err = go(p, "report")
            self.assertEqual(code, 2)
            self.assertIn("负数", err)

    def test_unknown_category_exit2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "体检", "500", "0", "500", "0",
                    "500", "0"),
            ])
            code, _, err = go(p, "report")
            self.assertEqual(code, 2)
            self.assertIn("未知类型", err)

    def test_category_alias_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "OP", "500", "0", "500", "0",
                    "500", "0"),
                row("2026-04-01", "自己", "OUTPATIENT", "300", "0", "300",
                    "0", "300", "0"),
                row("2026-05-01", "自己", "IP", "8000", "5000", "0",
                    "3000", "3000", "0"),
                row("2026-06-01", "自己", "INPATIENT", "4000", "2500", "0",
                    "1500", "1500", "0"),
            ])
            code, out, _ = go(p, "validate")
            self.assertEqual(code, 0)
            code, out, _ = go(p, "report")
            self.assertEqual(code, 0)
            # OP/OUTPATIENT/INPATIENT+IP：门诊 2 笔 800，住院 2 笔 12,000
            self.assertIn("门诊 2 笔 800.00", out)
            self.assertIn("住院 2 笔 12,000.00", out)

    def test_eps_boundary_exactly_01_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "100", "200",
                    "199.99", "399.99", "0"),  # 差恰 0.01
            ])
            code, _, _ = go(p, "report")
            self.assertEqual(code, 0)

    def test_own_gt_pocket_exit2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "0", "300", "200",
                    "600", ""),  # 自付 600 > 个账+现金 500
            ])
            code, _, err = go(p, "report")
            self.assertEqual(code, 2)
            self.assertIn("自付 600.00", err)


class Gates(unittest.TestCase):
    """薄账分层与时间剪切。"""

    def test_thin_year_declines_statistics_but_keeps_arithmetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "0", "500", "0",
                    "500", "0"),
                row("2026-03-05", "自己", "门诊", "300", "0", "300", "0",
                    "300", "0"),
            ])
            code, out, err = go(p, "report", "--income", "60000")
            self.assertEqual(code, 3)
            self.assertIn("账太薄", err)
            self.assertIn("薄账", out)
            self.assertIn("实掏·真口袋   800.00", out)  # 算术照出
            self.assertIn("灾难线", out)

    def test_short_span_declines(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "0", "500", "0",
                    "500", "0"),
                row("2026-03-05", "自己", "门诊", "300", "0", "300", "0",
                    "300", "0"),
                row("2026-03-09", "自己", "门诊", "200", "0", "200", "0",
                    "200", "0"),
            ])
            code, out, err = go(p, "report", "--income", "60000")
            self.assertEqual(code, 3)  # 3 笔但跨度 8 天 < 30 天
            self.assertIn("账太薄", err)

    def test_year_with_no_rows_declines(self):
        code, _, err = go(LEDGER, "--year", "2025", "report")
        self.assertEqual(code, 3)
        self.assertIn("2025 年度无结算行", err)

    def test_missing_file_exit2(self):
        code, _, err = go("/nonexistent/settlements.tsv", "report")
        self.assertEqual(code, 2)
        self.assertIn("缺文件", err)

    def test_header_only_ledger_exit2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [])
            code, _, err = go(p, "report")
            self.assertEqual(code, 2)
            self.assertIn("剪切后无结算行", err)

    def test_as_of_cuts_future_rows(self):
        code, out, _ = go(LEDGER, "--as-of", "2026-06-30", "--year", "2026",
                          "report")
        self.assertEqual(code, 0)
        self.assertIn("结算 7 笔", out)
        self.assertIn("29,544.00", out)       # 上半年 Σtotal（含种植牙 8,600）
        self.assertNotIn("2026-12-28", out)

    def test_as_of_cuts_deduce_base(self):
        code, out, _ = go(LEDGER, "--as-of", "2026-06-30", "deduce")
        self.assertEqual(code, 0)
        self.assertIn("6,505.56", out)        # 上半年目录内自付累计

    def test_default_as_of_is_max_date(self):
        code, out, _ = go(LEDGER, "report")
        self.assertIn("as-of: 2026-12-28", out)

    def test_report_prints_basename_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_ledger(tmp, [
                row("2026-03-01", "自己", "门诊", "500", "0", "500", "0",
                    "500", "0"),
                row("2026-04-01", "自己", "门诊", "300", "0", "300", "0",
                    "300", "0"),
                row("2026-05-01", "自己", "门诊", "200", "0", "200", "0",
                    "200", "0"),
                row("2026-06-01", "自己", "门诊", "100", "0", "100", "0",
                    "100", "0"),
            ])
            code, out, _ = go(p, "report")
            self.assertEqual(code, 0)
            self.assertIn("settlements.tsv", out)
            self.assertNotIn(tmp, out)


class CLIConventions(unittest.TestCase):
    """可复现与交付纪律。"""

    def test_example_snapshot_bytes(self):
        r = subprocess.run(
            [sys.executable,
             os.path.join(EXAMPLES, "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("snapshot ok", r.stdout)

    def test_no_command_prints_help(self):
        code, out, _ = go(LEDGER)
        self.assertEqual(code, 0)
        self.assertIn("usage", out.lower())

    def test_module_help(self):
        r = subprocess.run([sys.executable, CLI, "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("True Pocket", r.stdout)


if __name__ == "__main__":
    unittest.main()
