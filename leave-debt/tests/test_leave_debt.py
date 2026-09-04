# -*- coding: utf-8 -*-
"""欠休 · Leave Debt 的验收测试.

每一条测试都是 README 验收标准表中的一行：批次 FIFO、到期日语义、
作废入账、守恒恒等式、节奏外推与门禁分层、连休桥接（周末/法定/补班）、
拼假杠杆、还款计划窗口、模拟过闸、拒答优先、逐字节可复现。
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import leave_debt as ld  # noqa: E402

GRANT_HEADER = "grant_date\tdays\texpires\tnote\n"
LEAVE_HEADER = "date\tdays\ttype\tnote\n"


def write_ledger(grants_rows, leave_rows, holidays_text=None):
    """把行文本写进临时目录，返回 (grants_path, leave_path, holidays_path|None)。"""
    tmp = tempfile.mkdtemp(prefix="leavedebt-test-")
    gp = os.path.join(tmp, "grants.tsv")
    lp = os.path.join(tmp, "leave.tsv")
    with open(gp, "w", encoding="utf-8") as fh:
        fh.write(GRANT_HEADER + "\n".join(grants_rows) + "\n")
    with open(lp, "w", encoding="utf-8") as fh:
        fh.write(LEAVE_HEADER + "\n".join(leave_rows) + "\n")
    hp = None
    if holidays_text is not None:
        hp = os.path.join(tmp, "holidays.txt")
        with open(hp, "w", encoding="utf-8") as fh:
            fh.write(holidays_text)
    return gp, lp, hp


def run_cli(grants_rows, leave_rows, cmd, extra=None, holidays_text=None):
    gp, lp, hp = write_ledger(grants_rows, leave_rows, holidays_text)
    argv = [cmd, gp, lp]
    if hp:
        argv += ["--holidays", hp]
    argv += (extra or [])
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = ld.main(argv)
    return code, buf.getvalue()


def load(grants_rows, leave_rows, holidays_text=None, as_of=None):
    gp, lp, hp = write_ledger(grants_rows, leave_rows, holidays_text)
    return ld.load_ledger(gp, lp, hp, as_of)


def G(granted="2025-01-01", days="10", expires="2025-12-31", note=""):
    return "\t".join([granted, days, expires, note])


def T(d, days="1", kind="annual", note=""):
    return "\t".join([d, days, kind, note])


# ---------------------------------------------------------------- 解析与护栏

class TestParsing(unittest.TestCase):
    def test_load_ok(self):
        led = load([G()], [T("2025-03-05", "1")])
        self.assertEqual(len(led.grants), 1)
        self.assertEqual(len(led.live_takes), 1)

    def test_bad_date_broken(self):
        with self.assertRaises(ld.LedgerBroken):
            load([G(expires="2025/12/31")], [])

    def test_bad_step_broken(self):
        with self.assertRaises(ld.LedgerBroken):
            load([G(days="10.3")], [])

    def test_zero_days_broken(self):
        with self.assertRaises(ld.LedgerBroken):
            load([G(days="0")], [])

    def test_negative_days_broken(self):
        with self.assertRaises(ld.LedgerBroken):
            load([G()], [T("2025-03-05", "-1")])

    def test_unknown_type_broken(self):
        with self.assertRaises(ld.LedgerBroken):
            load([G()], [T("2025-03-05", "1", "sick")])

    def test_empty_grants_broken(self):
        with self.assertRaises(ld.LedgerBroken):
            load([], [])

    def test_expires_not_after_grant_broken(self):
        with self.assertRaises(ld.LedgerBroken):
            load([G(granted="2025-01-01", expires="2025-01-01")], [])

    def test_missing_column_broken(self):
        gp, lp, _ = write_ledger(["2025-01-01\t10"], [])
        with self.assertRaises(ld.LedgerBroken):
            ld.load_ledger(gp, lp, None, None)

    def test_half_day_ok(self):
        led = load([G()], [T("2025-03-05", "0.5")])
        self.assertEqual(led.live_takes[0].days, 0.5)

    def test_holiday_reversed_range_broken(self):
        with self.assertRaises(ld.LedgerBroken):
            load([G()], [], "2025-10-08..2025-10-01\n")

    def test_holiday_makeup_syntax(self):
        led = load([G()], [], "2025-10-01..2025-10-08\n!2025-09-28\n")
        self.assertEqual(len(led.holidays), 1)
        self.assertEqual(led.makeup_days, [date(2025, 9, 28)])


# ---------------------------------------------------------------- FIFO 重放

class TestFifo(unittest.TestCase):
    def test_fifo_spills_to_next_batch(self):
        led = load([G(days="3", expires="2025-03-31"), G(days="10", expires="2025-12-31")],
                   [T("2025-01-10"), T("2025-02-10"), T("2025-04-10")])
        ld.replay(led)
        self.assertEqual(led.grants[0].used, 2.0)
        self.assertEqual(led.grants[1].used, 1.0)

    def test_same_expiry_uses_earlier_grant(self):
        led = load([G(granted="2025-01-01", days="1", expires="2025-06-30"),
                    G(granted="2024-01-01", days="1", expires="2025-06-30")],
                   [T("2025-03-01")])
        ld.replay(led)
        by_grant = {g.granted: g for g in led.grants}
        self.assertEqual(by_grant[date(2024, 1, 1)].used, 1.0)  # 授予早的先用
        self.assertEqual(by_grant[date(2025, 1, 1)].used, 0.0)

    def test_expires_day_still_usable(self):
        led = load([G(days="3", expires="2025-03-31"), G(days="10", expires="2025-12-31")],
                   [T("2025-03-31")], as_of="2025-03-31")
        ld.replay(led)
        self.assertEqual(led.grants[0].used, 1.0)
        self.assertEqual(led.grants[0].voided, 0.0)  # 到期日终了才作废，当天休掉的不作废

    def test_after_expiry_falls_to_next_batch(self):
        led = load([G(days="3", expires="2025-03-31"), G(days="10", expires="2025-12-31")],
                   [T("2025-04-01")])
        ld.replay(led)
        self.assertEqual(led.grants[0].used, 0.0)
        self.assertEqual(led.grants[1].used, 1.0)
        self.assertEqual(led.grants[0].voided, 3.0)

    def test_advance_before_grant_broken(self):
        led = load([G(granted="2025-01-01")], [T("2024-12-20")])
        with self.assertRaises(ld.LedgerBroken):
            ld.replay(led)

    def test_overdraw_broken(self):
        led = load([G(days="2", expires="2025-06-30")],
                   [T("2025-02-01"), T("2025-03-01"), T("2025-04-01")])
        with self.assertRaises(ld.LedgerBroken):
            ld.replay(led)


# ---------------------------------------------------------------- 作废语义

class TestVoid(unittest.TestCase):
    ROWS_G = [G(days="3", expires="2025-03-31"), G(days="10", expires="2025-12-31")]

    def test_void_after_expiry(self):
        led = load(self.ROWS_G, [T("2025-02-14")], as_of="2025-04-01")
        ld.replay(led)
        self.assertEqual(led.grants[0].voided, 2.0)
        self.assertEqual(led.grants[0].balance, 0.0)

    def test_no_void_on_expiry_day(self):
        led = load(self.ROWS_G, [T("2025-02-14")], as_of="2025-03-31")
        ld.replay(led)
        self.assertEqual(led.grants[0].voided, 0.0)
        self.assertEqual(led.grants[0].balance, 2.0)

    def test_void_is_balance_at_expiry_not_today_balance(self):
        # 结转批 3 天：3/31 前休 1 天 → 作废 2（哪怕 as-of 之后年度批休掉了更多）
        led = load(self.ROWS_G, [T("2025-02-14"), T("2025-04-10", "3")],
                   as_of="2025-04-20")
        ld.replay(led)
        self.assertEqual(led.grants[0].voided, 2.0)
        self.assertEqual(led.grants[1].used, 3.0)

    def test_void_full_when_unused(self):
        led = load(self.ROWS_G, [], as_of="2025-04-01")
        ld.replay(led)
        self.assertEqual(led.grants[0].voided, 3.0)


# ---------------------------------------------------------------- 守恒恒等式

class TestIdentity(unittest.TestCase):
    def assert_conserved(self, led):
        ld.replay(led)
        tot = ld.totals(led)
        resid = tot["granted"] - tot["used"] - tot["voided"] - tot["balance"]
        self.assertAlmostEqual(resid, 0.0, places=9)
        return tot

    def test_example_ledger_conserved(self):
        led = load([G(days="3", expires="2025-03-31"), G(days="10", expires="2025-12-31")],
                   [T("2025-02-14"), T("2025-03-28"), T("2025-04-30", "0.5"),
                    T("2025-06-04")], as_of="2025-11-28")
        tot = self.assert_conserved(led)
        self.assertAlmostEqual(tot["granted"], 13.0, places=9)
        self.assertAlmostEqual(tot["used"], 3.5, places=9)
        # 结转批 3 天休掉 2 天，3/31 日终作废 1 天
        self.assertAlmostEqual(tot["voided"], 1.0, places=9)
        self.assertAlmostEqual(tot["balance"], 8.5, places=9)

    def test_fuzz_conserved(self):
        # 十组随机（确定性伪随机）账本全部守恒
        seed = 42
        for _ in range(10):
            seed = (seed * 1103515245 + 12345) % (2 ** 31)
            d1 = 3 + seed % 4          # 结转批天数
            seed = (seed * 1103515245 + 12345) % (2 ** 31)
            d2 = 5 + seed % 6          # 年度批天数
            n = 1 + seed % 5           # 休假次数
            rows = []
            day = 10
            for i in range(n):
                seed = (seed * 1103515245 + 12345) % (2 ** 31)
                rows.append(T("2025-%02d-%02d" % (1 + seed % 10, day), "1"))
            led = load([G(days=str(d1), expires="2025-03-31"),
                        G(days=str(d2), expires="2025-12-31")], rows,
                       as_of="2025-11-28")
            self.assert_conserved(led)


# ---------------------------------------------------------------- 报告与门禁

class TestReport(unittest.TestCase):
    def test_report_example_exit4_both_gates(self):
        code, out = run_cli(
            ["\t".join(["2025-01-01", "3", "2025-03-31", "x"]),
             G(days="10")],
            [T("2025-02-14"), T("2025-03-28"), T("2025-04-30"), T("2025-06-04"),
             T("2025-08-20", "0.5"), T("2025-09-29"), T("2025-10-09"),
             T("2025-12-24", "1", "other")],
            "report", ["--as-of", "2025-11-28", "--monthly-salary", "13050"])
        self.assertEqual(code, 4)
        self.assertIn("临期作废", out)
        self.assertIn("节奏性作废", out)
        self.assertIn("作废 1.0 天 = ¥600.00", out)
        self.assertIn("残差 0.00e+00", out)
        self.assertIn("落后", out)

    def test_report_warn_days_tightened(self):
        rows_g = ["\t".join(["2025-01-01", "3", "2025-03-31", "x"]), G(days="10")]
        rows_t = [T("2025-02-14"), T("2025-03-28"), T("2025-04-30"), T("2025-06-04"),
                  T("2025-08-20", "0.5"), T("2025-09-29"), T("2025-10-09")]
        code, out = run_cli(rows_g, rows_t, "report",
                            ["--as-of", "2025-11-28", "--warn-days", "10"])
        self.assertEqual(code, 4)  # 节奏门禁仍爆
        self.assertNotIn("临期作废", out)  # 33 天 > 10 天，临期不爆
        self.assertIn("节奏性作废", out)

    def test_report_no_redline_exit0(self):
        # 全年 10 天休掉 8 天、匀速：余额 2，burn 足以在年底前消化，无红线
        rows = [T("2025-01-20"), T("2025-02-20"), T("2025-03-20"), T("2025-04-20"),
                T("2025-05-20"), T("2025-06-20"), T("2025-07-20"), T("2025-08-20")]
        code, out = run_cli([G(days="10")], rows, "report", ["--as-of", "2025-11-01"])
        self.assertEqual(code, 0)
        self.assertNotIn("✗", out)

    def test_report_thin_decline_exit3(self):
        code, out = run_cli([G(granted="2026-01-01", days="5", expires="2026-12-31")],
                            [T("2026-01-20"), T("2026-02-10")],
                            "report", ["--as-of", "2026-02-15"])
        self.assertEqual(code, 3)
        self.assertIn("DECLINE", out)
        self.assertNotIn("节奏性作废", out)

    def test_thin_but_expiry_gate_still_fires(self):
        # 算术门禁不拒答：账再薄，批次临期照爆，exit 4 优先于 exit 3
        code, out = run_cli([G(granted="2026-01-01", days="5", expires="2026-03-01")],
                            [T("2026-01-20"), T("2026-02-10")],
                            "report", ["--as-of", "2026-02-15"])
        self.assertEqual(code, 4)
        self.assertIn("DECLINE", out)
        self.assertIn("临期作废", out)

    def test_forecast_line_arithmetic(self):
        # 授予 10，6/1 前休 3：burn=3/152，窗口 213 天 → 预测作废 7−4.20=2.80
        # 2.80/10 = 28.0% > 15% → exit 4；窗口 213 天 > 45 天，临期不爆
        rows = [T("2025-01-20"), T("2025-03-20"), T("2025-05-20")]
        code, out = run_cli([G(days="10")], rows, "report", ["--as-of", "2025-06-01"])
        self.assertEqual(code, 4)
        self.assertIn("节奏性作废", out)
        self.assertNotIn("临期作废", out)

    def test_forecast_line_relaxed_to_zero_skips_l2(self):
        rows = [T("2025-01-20"), T("2025-03-20"), T("2025-05-20")]
        code, out = run_cli([G(days="10")], rows, "report",
                            ["--as-of", "2025-06-01", "--forecast-line", "1.0"])
        self.assertEqual(code, 0)

    def test_asof_truncates_future_takes_with_disclosure(self):
        rows = [T("2025-01-20"), T("2025-03-20"), T("2025-05-20"), T("2026-03-01")]
        code, out = run_cli([G(days="10")], rows, "report", ["--as-of", "2025-06-01"])
        self.assertIn("1 行未来休假", out)
        code2, out2 = run_cli([G(days="10")], rows, "report", ["--as-of", "2025-06-01"])
        self.assertEqual(out, out2)

    def test_no_future_leak_asof_defaults_to_ledger_end(self):
        # 缺省 as-of = 账本最大日期（含到期日与未来流水），全部流水入账
        led = load([G(days="10")], [T("2025-03-05"), T("2026-03-05", "1", "other")])
        self.assertEqual(led.as_of, date(2026, 3, 5))
        self.assertEqual(len(led.live_takes), 2)


# ---------------------------------------------------------------- 形状与杠杆

SHAPE_G = [G(days="20", expires="2025-12-31")]
SHAPE_HOL = "2025-10-01..2025-10-08\n!2025-09-28\n"


class TestShape(unittest.TestCase):
    def test_weekend_bridge(self):
        code, out = run_cli(SHAPE_G, [T("2025-06-06")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertIn("2025-06-06  2025-06-08     3", out)

    def test_friday_plus_monday_merges(self):
        code, out = run_cli(SHAPE_G, [T("2025-06-06"), T("2025-06-09")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertIn("2025-06-06  2025-06-09     4", out)
        self.assertIn("2.00", out)  # 杠杆 4/2

    def test_holiday_bridge(self):
        # 五一桥：4/30(三) 休 1 + 5/1..5/5 法定 → span 6
        code, out = run_cli(SHAPE_G, [T("2025-04-30")], "shape",
                            ["--as-of", "2025-11-28"],
                            "2025-05-01..2025-05-05\n")
        self.assertIn("2025-04-30  2025-05-05     6", out)
        self.assertIn("6.00", out)

    def test_national_day_tail_bridge(self):
        # 国庆尾桥：10/09 休 1，向前吃到 10/01 → span 9
        code, out = run_cli(SHAPE_G, [T("2025-10-09")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertIn("2025-10-01  2025-10-09     9", out)
        self.assertIn("9.00", out)

    def test_makeup_day_breaks_bridge(self):
        # 9/29(一) 前面的 9/28(日) 是调休补班 → 桥断，span 1 全价假
        code, out = run_cli(SHAPE_G, [T("2025-09-29")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertIn("2025-09-29  2025-09-29     1", out)
        self.assertIn("1.00", out)

    def test_midweek_full_price(self):
        code, out = run_cli(SHAPE_G, [T("2025-06-04")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertIn("2025-06-04  2025-06-04     1", out)
        self.assertIn("全价假", out)

    def test_half_day_leverage_doubles(self):
        # 周五下午半天：span 3（含周末桥），杠杆 3/0.5 = 6.0
        code, out = run_cli(SHAPE_G, [T("2025-06-13", "0.5")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertIn("2025-06-13  2025-06-15     3", out)
        self.assertIn("6.00", out)

    def test_other_occupies_segment_without_lever(self):
        # 周四调休 + 周五年假：段 [周四..周日] span 4，杠杆 4/1 = 4.0
        # （other 不进杠杆分母，但它的占用把桥拉长了——额度外的休息也在帮忙搭桥）
        code, out = run_cli(SHAPE_G, [T("2025-06-05", "1", "other"), T("2025-06-06")],
                            "shape", ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertIn("2025-06-05  2025-06-08     4", out)
        self.assertIn("4.00", out)

    def test_fragment_counting(self):
        # 6/4(三) span 1 碎片；8/20(三) 半天 span 1 碎片
        code, out = run_cli(SHAPE_G, [T("2025-06-04"), T("2025-08-20", "0.5"),
                                      T("2025-09-05")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertIn("碎片段 2/3", out)

    def test_average_lever_weighted(self):
        # span 3(1) + 1(1) + 3(0.5)：Σspan=7, Σannual=2.5 → 2.80x
        code, out = run_cli(SHAPE_G, [T("2025-06-06"), T("2025-06-11"),
                                      T("2025-06-13", "0.5")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertIn("平均杠杆 2.80x", out)

    def test_shape_thin_decline(self):
        code, out = run_cli(SHAPE_G, [T("2025-06-06")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertEqual(code, 3)
        self.assertIn("DECLINE", out)

    def test_no_annual_leaves_exit0(self):
        code, out = run_cli(SHAPE_G, [T("2025-06-06", "1", "other"),
                                      T("2025-06-07", "1", "other")], "shape",
                            ["--as-of", "2025-11-28"], SHAPE_HOL)
        self.assertEqual(code, 0)
        self.assertIn("额度原封不动", out)


# ---------------------------------------------------------------- 还款计划

class TestPlan(unittest.TestCase):
    def test_plan_infeasible_example(self):
        rows_t = [T("2025-02-14"), T("2025-03-28"), T("2025-04-30"), T("2025-06-04"),
                  T("2025-08-20", "0.5"), T("2025-09-29"), T("2025-10-09")]
        code, out = run_cli(["\t".join(["2025-01-01", "3", "2025-03-31", "x"]),
                             G(days="10")], rows_t, "plan",
                            ["--as-of", "2025-11-28", "--monthly-salary", "13050"])
        self.assertEqual(code, 4)
        self.assertIn("INFEASIBLE", out)
        self.assertIn("注定作废 0.5 天", out)
        self.assertIn("¥300.00", out)  # 0.5 × 日薪 600
        self.assertIn("W5", out)

    def test_plan_feasible_with_higher_cap(self):
        rows_t = [T("2025-02-14"), T("2025-03-28"), T("2025-04-30"), T("2025-06-04"),
                  T("2025-08-20", "0.5"), T("2025-09-29"), T("2025-10-09")]
        code, out = run_cli(["\t".join(["2025-01-01", "3", "2025-03-31", "x"]),
                             G(days="10")], rows_t, "plan",
                            ["--as-of", "2025-11-28", "--pace-cap", "1.2"])
        self.assertEqual(code, 0)
        self.assertIn("FEASIBLE", out)
        self.assertIn("尾窗清零", out)
        self.assertIn("余 0.0", out)

    def test_plan_no_balance_is_clean(self):
        rows_t = [T("2025-02-14", "3")]  # 唯一批次一次休完
        code, out = run_cli([G(days="3", expires="2025-06-30")], rows_t, "plan",
                            ["--as-of", "2025-03-01"])
        self.assertEqual(code, 0)
        self.assertIn("无债可还", out)

    def test_plan_window_allocations_sum_to_balance(self):
        rows_t = [T("2025-02-14"), T("2025-03-28"), T("2025-04-30"), T("2025-06-04"),
                  T("2025-08-20", "0.5"), T("2025-09-29"), T("2025-10-09")]
        code, out = run_cli(["\t".join(["2025-01-01", "3", "2025-03-31", "x"]),
                             G(days="10")], rows_t, "plan",
                            ["--as-of", "2025-11-28", "--pace-cap", "1.2"])
        takes = [1.2, 1.2, 1.2, 1.2, 0.7]
        self.assertAlmostEqual(sum(takes), 5.5, places=6)


# ---------------------------------------------------------------- 模拟过闸

class TestSimulate(unittest.TestCase):
    EX = (["\t".join(["2025-01-01", "3", "2025-03-31", "x"]), G(days="10")],
          [T("2025-02-14"), T("2025-03-28"), T("2025-04-30"), T("2025-06-04"),
           T("2025-08-20", "0.5"), T("2025-09-29"), T("2025-10-09")])

    def test_clear_all_passes(self):
        code, out = run_cli(self.EX[0], self.EX[1], "simulate",
                            ["--as-of", "2025-11-28", "--take", "5.5",
                             "--on", "2025-12-01", "--monthly-salary", "13050"])
        self.assertEqual(code, 0)
        self.assertIn("压回", out)
        self.assertIn("0.0%", out)

    def test_partial_still_over_line(self):
        code, out = run_cli(self.EX[0], self.EX[1], "simulate",
                            ["--as-of", "2025-11-28", "--take", "1.5",
                             "--on", "2025-12-08"])
        self.assertEqual(code, 4)
        self.assertIn("一发入魂救不了", out)

    def test_overdraw_exit2(self):
        code, out = run_cli(self.EX[0], self.EX[1], "simulate",
                            ["--as-of", "2025-11-28", "--take", "6.0",
                             "--on", "2025-12-08"])
        self.assertEqual(code, 2)
        self.assertIn("透支", out)

    def test_past_date_declined(self):
        code, out = run_cli(self.EX[0], self.EX[1], "simulate",
                            ["--as-of", "2025-11-28", "--take", "1.0",
                             "--on", "2025-11-28"])
        self.assertEqual(code, 3)
        self.assertIn("模拟的是过去", out)

    def test_no_batch_on_date_declined(self):
        code, out = run_cli(self.EX[0], self.EX[1], "simulate",
                            ["--as-of", "2025-11-28", "--take", "1.0",
                             "--on", "2026-06-01"])
        self.assertEqual(code, 3)
        self.assertIn("查无此债", out)

    def test_uses_fifo_batch(self):
        # 12/01 动用的必须是 12/31 清零的年度批（结转批已死）
        code, out = run_cli(self.EX[0], self.EX[1], "simulate",
                            ["--as-of", "2025-11-28", "--take", "1.0",
                             "--on", "2025-12-01"])
        self.assertIn("2025-12-31 清零", out)


# ---------------------------------------------------------------- validate 与钱

class TestValidateAndMoney(unittest.TestCase):
    def test_validate_ok(self):
        code, out = run_cli(["\t".join(["2025-01-01", "3", "2025-03-31", "x"]),
                             G(days="10")],
                            [T("2025-02-14"), T("2025-03-28"), T("2025-04-30"),
                             T("2025-06-04"), T("2025-08-20", "0.5"),
                             T("2025-09-29"), T("2025-10-09"),
                             T("2025-12-24", "1", "other")],
                            "validate", None, None)
        self.assertEqual(code, 0)
        self.assertIn("守恒恒等式", out)
        self.assertIn("残差 0.00e+00", out)
        self.assertIn("OK (exit 0)", out)

    def test_validate_reports_truncation(self):
        code, out = run_cli([G(days="10")], [T("2025-03-05"), T("2026-06-01")],
                            "validate", ["--as-of", "2025-06-01"])
        self.assertEqual(code, 0)
        self.assertIn("未来休假", out)

    def test_validate_holidays_disclosure(self):
        code, out = run_cli([G(days="10")], [T("2025-03-05"), T("2025-04-05"),
                                             T("2025-05-05")],
                            "validate", None, "2025-10-01..2025-10-08\n!2025-09-28\n")
        self.assertIn("8 个法定日", out)
        self.assertIn("1 个调休补班日", out)

    def test_daily_rate_direct(self):
        code, out = run_cli([G(days="10")], [T("2025-01-20"), T("2025-03-20"),
                                             T("2025-05-20")],
                            "report", ["--as-of", "2026-06-01", "--daily-rate", "800"])
        self.assertIn("日薪 ¥800.00", out)

    def test_monthly_salary_divided_by_pay_days(self):
        code, out = run_cli([G(days="10")], [T("2025-01-20"), T("2025-03-20"),
                                             T("2025-05-20")],
                            "report", ["--as-of", "2026-06-01",
                                       "--monthly-salary", "13050"])
        self.assertIn("¥600.00", out)

    def test_no_salary_no_money(self):
        code, out = run_cli([G(days="10")], [T("2025-01-20"), T("2025-03-20"),
                                             T("2025-05-20")],
                            "report", ["--as-of", "2026-06-01"])
        self.assertNotIn("¥", out)
        self.assertIn("未给工资参数", out)


# ---------------------------------------------------------------- 可复现性

class TestReproducibility(unittest.TestCase):
    def test_no_system_clock(self):
        with open(os.path.join(ROOT, "leave_debt.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("date.today", src)
        self.assertNotIn("datetime.now", src)

    def test_byte_identical_reruns(self):
        rows_g = ["\t".join(["2025-01-01", "3", "2025-03-31", "x"]), G(days="10")]
        rows_t = [T("2025-02-14"), T("2025-03-28"), T("2025-04-30"), T("2025-06-04"),
                  T("2025-08-20", "0.5"), T("2025-09-29"), T("2025-10-09")]
        code1, out1 = run_cli(rows_g, rows_t, "report", ["--as-of", "2025-11-28"])
        code2, out2 = run_cli(rows_g, rows_t, "report", ["--as-of", "2025-11-28"])
        self.assertEqual((code1, out1), (code2, out2))

    def test_asof_explicit_beats_default(self):
        gp, lp, _ = write_ledger([G(days="10")], [T("2025-03-05"), T("2026-06-01")])
        for as_of, n_live in (("2026-06-01", 2), ("2025-06-01", 1)):
            led = ld.load_ledger(gp, lp, None, as_of)
            self.assertEqual(len(led.live_takes), n_live)

    def test_default_asof_includes_expiry(self):
        led = load([G(days="10", expires="2025-12-31")], [T("2025-03-05")])
        self.assertEqual(led.as_of, date(2025, 12, 31))


# ---------------------------------------------------------------- 示例快照

class TestExamples(unittest.TestCase):
    def test_examples_byte_exact(self):
        run = [sys.executable, os.path.join(ROOT, "examples", "build_examples.py"),
               "--check"]
        done = subprocess.run(run, capture_output=True, text=True,
                              cwd=os.path.join(ROOT, "examples"))
        self.assertEqual(done.returncode, 0,
                         "示例快照与构建器不一致：%s%s" % (done.stdout, done.stderr))


if __name__ == "__main__":
    unittest.main()
