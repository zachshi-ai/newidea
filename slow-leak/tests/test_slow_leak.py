#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slow-leak · 暗漏 — 验收测试.

验收标准（全部转成自动化测试）：
  A1  账本解析：坏行带行号 exit 2（月份/用量/列数/重复/未来账期/文件缺失）
  A2  THIN：某表不足 4 期不判灯（◌ THIN），不触发 exit 4
  A3  SPIKE：同比上涨 >25% 触发；恰 25% 不触发；基线 = 去年 + 前年同月中位
  A4  LEAK：近 4 期 ≥3 次环比上涨 且 最新 ≥1.2× 窗口首期 且 ≥1.2× 去年同期；
      三涨但不足 1.2× 不触发；断月不判
  A5  季节免疫：冬季爬坡（采暖/空调）不误报——同比对照压制纯环比误报
  A6  detect 全史扫描：修好的历史事件仍被记住；误报率为零（示例账本）
  A7  floor：各表历史最低月及其占最新月的比例
  A8  annualized：SPIKE 的量 ×12 年化（示例：(395−205)×12 = 2280 度）
  A9  判灯：任一表 SPIKE/LEAK → exit 4；全部正常 → exit 0
  A10 单表账本正常出账；trend 指定不存在的表 exit 3
  A11 空账本 exit 3
  A12 注释行（#）与空行跳过
  A13 --today 钉死逐字节可复现
  A14 utilities 命令列出三表与单位
"""

import contextlib
import datetime as dt
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import slow_leak as sl  # noqa: E402

TODAY = "2026-09-04"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(BASE, "examples", "ledger.tsv")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sl.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def tsv(rows):
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return path


def row(ym, utility, amount):
    return sl.Row(int(ym[:4]), int(ym[5:7]), utility, amount, 1)


class TestParsing(unittest.TestCase):
    """A1/A11/A12：账本解析。"""

    def test_a1_bad_rows_carry_line_numbers(self):
        cases = [
            (["2026-01\telectric"], "至少 3 列"),
            (["2026-13\telectric\t100"], "YYYY-MM"),
            (["2026-01\telectric\tabc"], "不是数字"),
            (["2026-01\telectric\t0"], "必须 > 0"),
            (["2026-01\telectric\t100", "2026-01\telectric\t120"], "重复记账"),
            (["2026-10\telectric\t100"], "当前月之后"),
        ]
        for rows, needle in cases:
            with self.subTest(rows=rows):
                code, _, err = run_cli("check", tsv(rows), "--today", TODAY)
                self.assertEqual(code, 2)
                self.assertIn("第 1 行" if len(rows) == 1 else "第 2 行", err)
                self.assertIn(needle, err)

    def test_a1_missing_file(self):
        code, _, err = run_cli("check", "/no/such/ledger.tsv", "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("不存在", err)

    def test_a11_empty_ledger_refuses(self):
        code, _, err = run_cli("check", tsv([]), "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("账本是空的", err)

    def test_a12_comments_and_blank_lines_skipped(self):
        p = tsv(["# 注释", "", "2026-05\telectric\t100", "2026-06\telectric\t102",
                 "2026-07\telectric\t101", "2026-08\telectric\t103"])
        code, out, _ = run_cli("validate", p, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("4 期", out)

    def test_a13_pinned_today_is_byte_identical(self):
        _, out1, _ = run_cli("check", EXAMPLE, "--today", TODAY)
        _, out2, _ = run_cli("check", EXAMPLE, "--today", TODAY)
        self.assertEqual(out1, out2)


class TestSpike(unittest.TestCase):
    """A3/A8：同比突变。"""

    def ledgers(self):
        return sl.load_ledger(EXAMPLE, (2026, 9))

    def test_a3_example_electric_spikes(self):
        rows = self.ledgers()["electric"]
        st = sl.period_status(rows, len(rows) - 1)  # 2026-08 = 395
        self.assertAlmostEqual(st["baseline"], 205.0)  # median(2025-08=210, 2024-08=200)
        self.assertAlmostEqual(st["ratio"], 395 / 205)
        self.assertTrue(st["spike"])
        self.assertTrue(st["leak"])

    def test_a3_boundary_exactly_25_percent_is_not_spike(self):
        rows = [row("2025-06", "x", 100), row("2025-03", "x", 10),
                row("2025-04", "x", 11), row("2025-05", "x", 10),
                row("2026-03", "x", 10), row("2026-04", "x", 11),
                row("2026-05", "x", 10), row("2026-06", "x", 125)]
        st = sl.period_status(rows, len(rows) - 1)
        self.assertAlmostEqual(st["ratio"], 1.25)
        self.assertFalse(st["spike"])

    def test_a3_spike_just_above_boundary(self):
        rows = [row("2025-03", "x", 10), row("2025-04", "x", 11), row("2025-05", "x", 10),
                row("2025-06", "x", 100),
                row("2026-03", "x", 10), row("2026-04", "x", 11), row("2026-05", "x", 10),
                row("2026-06", "x", 126)]
        st = sl.period_status(rows, 7)
        self.assertAlmostEqual(st["ratio"], 1.26)
        self.assertTrue(st["spike"])

    def test_a8_annualized_excess_in_red_report(self):
        code, out, _ = run_cli("check", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("2280 度", out)  # (395-205) × 12


class TestLeak(unittest.TestCase):
    """A4/A5：蠕升与季节免疫。"""

    def leak(self, amounts, months=None, yoy=None):
        """构造连续月份的账并返回最新期的 leak 判定。yoy = 去年同期值序列。"""
        months = months or [f"2026-{m:02d}" for m in range(1, len(amounts) + 1)]
        rows = [row(ym, "x", a) for ym, a in zip(months, amounts)]
        if yoy:
            rows = [row(ym.replace("2026", "2025"), "x", a) for ym, a in
                    zip([f"2026-{m:02d}" for m in range(1, len(yoy) + 1)], yoy)] + rows
            rows.sort(key=lambda r: r.ym)
        st = sl.period_status(rows, len(rows) - 1)
        return st["leak"]

    def test_a4_three_rises_and_growth_triggers(self):
        # 100→110→121→150：三连涨，150 ≥ 1.2×100=120；去年同期 120 → 150 ≥ 144
        self.assertTrue(self.leak([100, 110, 121, 150], yoy=[110, 115, 118, 120]))

    def test_a4_growth_below_1_2x_window_start_does_not(self):
        # 三连涨但 115 < 1.2×100
        self.assertFalse(self.leak([100, 105, 110, 115], yoy=[110, 111, 112, 113]))

    def test_a4_below_last_year_same_month_does_not(self):
        # 窗口内 1.2× 满足，但今年 150 < 1.2×去年同期 130=156 —— 去年也涨过，不算泄漏
        self.assertFalse(self.leak([100, 110, 121, 150], yoy=[100, 110, 120, 130]))

    def test_a4_no_yoy_baseline_refuses_to_judge(self):
        # 无去年同期（首年）→ 一律不判 leak，宁可漏报不误报
        self.assertFalse(self.leak([100, 110, 121, 150]))

    def test_a4_gap_months_block_leak(self):
        # 断月（缺 2026-02）：环比不可信，不判
        months = ["2026-01", "2026-03", "2026-04", "2026-05"]
        self.assertFalse(self.leak([100, 110, 121, 150], months=months,
                                   yoy=[110, 115, 118, 120]))

    def test_a5_heating_season_does_not_false_positive(self):
        # 燃气从夏 60 爬到冬 300 是采暖不是泄漏：去年同期也在爬 → 不判
        cur = [60, 120, 200, 300]
        yoy = [65, 125, 210, 310]
        self.assertFalse(self.leak(cur, months=["2026-09", "2026-10", "2026-11", "2026-12"],
                                   yoy=yoy))


class ExampleLedgerTest(unittest.TestCase):
    """示例账本的端到端读数。"""

    def test_a5_gas_seasonimmune_in_example(self):
        code, out, _ = run_cli("check", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("gas        8 月    70 方   去年同期 62.5 → +12.0%   · NORMAL", out)

    def test_a6_detect_remembers_repaired_event(self):
        code, out, _ = run_cli("detect", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("water      2025-06  25 吨  ⚡ SPIKE（同比 +127.3%）", out)
        self.assertIn("SPIKE（同比突变）：3 次", out)
        self.assertIn("LEAK（连涨蠕升）：2 次", out)
        self.assertIn("electric   2026-08  395 度  ✗ LEAK", out)

    def test_a7_floor_is_historic_minimum(self):
        code, out, _ = run_cli("floor", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("electric   底座   180 度（2024-06）  最新月   395 → 底座占 46%", out)
        self.assertIn("gas        底座    60 方（2024-07）  最新月    70 → 底座占 86%", out)

    def test_a9_red_gate_and_green(self):
        code, out, _ = run_cli("check", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("判定  RED —— electric 在偷跑", out)
        # 全正常的账本（2024+2025 两个完整年，2026 之后无未来账期）→ exit 0
        rows = []
        for y in (2024, 2025):
            for m in range(1, 13):
                rows.append(f"{y}-{m:02d}\twater\t{10 + (m % 3)}")
        code2, out2, _ = run_cli("check", tsv(rows), "--today", TODAY)
        self.assertEqual(code2, 0)
        self.assertIn("判定  GREEN", out2)


class TestCommands(unittest.TestCase):
    """A10/A14：命令行为。"""

    def test_a10_single_utility_ledger(self):
        rows = [f"2026-0{m}\twater\t{9 + m}" for m in range(1, 9)]
        rows += [f"2025-0{m}\twater\t{9 + m}" for m in range(1, 9)]
        code, out, _ = run_cli("check", tsv(rows), "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("1 张表", out)
        self.assertNotIn("electric", out)

    def test_a10_trend_unknown_utility_refuses(self):
        code, _, err = run_cli("trend", EXAMPLE, "--utility", "solar", "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("没有「solar」这张表", err)

    def test_a10_trend_marks_spike_periods(self):
        code, out, _ = run_cli("trend", EXAMPLE, "--utility", "electric", "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("2026-08     395    +92.7%  ⚡ SPIKE  ✗ LEAK", out)
        self.assertIn("2024-01     320       —  · NORMAL（无同期对照）", out)

    def test_a14_utilities_lists_three(self):
        code, out, _ = run_cli("utilities")
        self.assertEqual(code, 0)
        for name, unit in [("electric", "度"), ("water", "吨"), ("gas", "方")]:
            self.assertIn(name, out)
            self.assertIn(unit, out)


class TestUnits(unittest.TestCase):
    """A15/A16/A18：检测器单元行为。"""

    def test_a15_contiguous_year_boundary(self):
        rows = [row("2025-11", "x", 10), row("2025-12", "x", 11),
                row("2026-01", "x", 12), row("2026-02", "x", 13)]
        self.assertTrue(sl.contiguous(rows, 4))

    def test_a15_contiguous_gap_detected(self):
        rows = [row("2025-11", "x", 10), row("2026-01", "x", 11),
                row("2026-02", "x", 12), row("2026-03", "x", 13)]
        self.assertFalse(sl.contiguous(rows, 4))

    def test_a16_baseline_median_of_two_years(self):
        rows = [row("2024-06", "x", 100), row("2025-06", "x", 120), row("2026-06", "x", 130)]
        base, n = sl.yoy_baseline(rows, (2026, 6))
        self.assertEqual(n, 2)
        self.assertAlmostEqual(base, 110.0)  # median(100, 120)

    def test_a16_baseline_single_year(self):
        rows = [row("2025-06", "x", 120), row("2026-06", "x", 130)]
        base, n = sl.yoy_baseline(rows, (2026, 6))
        self.assertEqual(n, 1)
        self.assertAlmostEqual(base, 120.0)

    def test_a18_drop_is_advisory_not_gate(self):
        rows = [row("2024-06", "x", 200), row("2025-06", "x", 210),
                row("2026-03", "x", 10), row("2026-04", "x", 11),
                row("2026-05", "x", 10), row("2026-06", "x", 80)]
        st = sl.period_status(rows, 5)
        self.assertTrue(st["drop"])   # 80/205 = 0.39 < 0.75
        self.assertFalse(st["spike"])
        self.assertFalse(st["leak"])  # 陡降不进判灯

    def test_a18_thin_utility_never_gates(self):
        rows = [row("2026-06", "x", 1000), row("2026-07", "x", 1100),
                row("2026-08", "x", 1200)]
        st = sl.period_status(rows, 2)  # 三期连涨 20%，但不足 4 期
        self.assertTrue(st["thin"])
        self.assertFalse(st["spike"])
        self.assertFalse(st["leak"])

    def test_a19_example_gas_full_history_normal(self):
        code, out, _ = run_cli("trend", EXAMPLE, "--utility", "gas", "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("全史异常 0 期", out)

    def test_a20_thin_marker_in_mixed_ledger(self):
        p = tsv(["2026-06\tsolar\t50", "2026-07\tsolar\t55",
                 "2026-08\tsolar\t60"])
        code, out, _ = run_cli("check", p, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("solar      8 月    60 单位", out)
        self.assertIn("◌ THIN", out)


if __name__ == "__main__":
    unittest.main()
