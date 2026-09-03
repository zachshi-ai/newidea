#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""borderline · 贴线 — 验收测试.

验收标准（全部转成自动化测试）：
  A1  账本解析：坏行带行号 exit 2（列数/日期/未来体检/数值/单位冲突/参考区间/文件缺失）
  A2  THIN：不足 3 次测量不判趋势（◌ THIN），永不触发门禁
  A3  斜率：Theil-Sen 成对斜率中位；单点离群（化验失误）不绑架趋势
  A4  噪声地板：净涨幅 ≥ 参考区间宽度 10% 才算「在爬」；斜率 ≤ 0 不算
  A5  BORDERLINE：在爬且余量 ≤ 3 年 → 门禁 exit 4；恰 3 年触发；> 3 年 → WATCH exit 0
  A6  OVER：越线仍在爬 → 门禁；越线但已企稳 → exit 0（在管，不进门禁）
  A7  首越年份与线上次数：按当年各自的参考区间记（示例 uric-acid 2023 首越、线上 3 次）
  A8  余量：按最新参考区间算（示例 fasting-glucose 0.7 年、ldl 0.2 年）
  A9  门禁：示例账本 4 项在爬 → RED exit 4；全稳账本 → GREEN exit 0
  A10 trend：未知指标 exit 3；越线（首次）/（第 N 次）标注；区间变更脚注
  A11 空账本 exit 3
  A12 注释行（#）与空行跳过
  A13 --today 钉死逐字节可复现
  A14 markers 命令：列出常见指标、单位、惯犯与科室
  A15 区间变更：余量按最新区间算（换体检机构更严的新区间能把人判越线）
  A16 单位冲突：同一指标两种单位 → exit 2，指认两处行号
  A17 next：专项复查 / 半年加测 / 年度照旧 / 继续攒，附科室；账本新鲜提示
  A18 新鲜度：距上次体检 > 15 个月 → ⚠ 过期提示（panel/next/validate）
  A19 面板排序：OVER 按首越日期、BORDERLINE 按余量升序，同组内确定性
  A20 ▽ 在降：净跌幅 ≥ 10% 区间宽度 → 记功标注（示例 alt）
  A21 重复记账：同指标同日期 → exit 2
  A22 参考下限「-」：只有上限的指标照常计算（示例 ldl ≤ 3.4）
"""

import contextlib
import datetime as dt
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import borderline as bl  # noqa: E402

TODAY = "2026-09-04"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(BASE, "examples", "ledger.tsv")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = bl.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def tsv(rows):
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return path


def row(marker, ymd, value, unit="x", low="0", high="100"):
    return bl.Row(marker, dt.datetime.strptime(ymd, "%Y-%m-%d").date(), value,
                  unit, None if low == "-" else float(low), float(high), "", 1)


def ann(m, d, y0=2020, n=3):
    """n 个连续年份的 1 月 N 日日期。"""
    return [f"{y0 + i:04d}-01-{d:02d}" for i in range(n)]


class TestParsing(unittest.TestCase):
    """A1/A11/A12/A13/A16/A21：账本解析。"""

    def test_a1_bad_rows_carry_line_numbers(self):
        cases = [
            (["uric-acid\t2025-01-01\t400\tµmol/L\t208"], "至少 6 列"),
            (["uric-acid\t2025-01\t400\tµmol/L\t208\t428"], "YYYY-MM-DD"),
            (["uric-acid\t2026-12-01\t400\tµmol/L\t208\t428"], "在今天之后"),
            (["uric-acid\t2025-01-01\tabc\tµmol/L\t208\t428"], "不是数字"),
            (["uric-acid\t2025-01-01\t0\tµmol/L\t208\t428"], "必须 > 0"),
            (["uric-acid\t2025-01-01\t400\tµmol/L\t300\t208"], "必须 > 参考下限"),
        ]
        for rows, needle in cases:
            with self.subTest(rows=rows, needle=needle):
                code, _, err = run_cli("panel", tsv(rows), "--today", TODAY)
                self.assertEqual(code, 2)
                self.assertIn("第 1 行", err)
                self.assertIn(needle, err)

    def test_a1_missing_file(self):
        code, _, err = run_cli("panel", "/no/such/ledger.tsv", "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("不存在", err)

    def test_a16_unit_conflict_names_both_lines(self):
        p = tsv(["uric-acid\t2024-01-01\t400\tµmol/L\t208\t428",
                 "uric-acid\t2025-01-01\t6.5\tmg/dL\t3.4\t7.0"])
        code, _, err = run_cli("panel", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("第 2 行", err)
        self.assertIn("第 1 行", err)
        self.assertIn("冲突", err)

    def test_a21_duplicate_marker_date(self):
        p = tsv(["ldl\t2025-01-01\t3.0\tmmol/L\t-\t3.4",
                 "ldl\t2025-01-01\t3.1\tmmol/L\t-\t3.4"])
        code, _, err = run_cli("panel", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("重复记账", err)

    def test_a11_empty_ledger_refuses(self):
        code, _, err = run_cli("panel", tsv([]), "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("账本是空的", err)

    def test_a12_comments_and_blank_lines_skipped(self):
        p = tsv(["# 注释", "", "sbp\t2024-01-01\t120\tmmHg\t90\t139",
                 "sbp\t2025-01-01\t122\tmmHg\t90\t139"])
        code, out, _ = run_cli("validate", p, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("1 个指标", out)
        self.assertIn("2 次", out)

    def test_a13_pinned_today_is_byte_identical(self):
        _, out1, _ = run_cli("panel", EXAMPLE, "--today", TODAY)
        _, out2, _ = run_cli("panel", EXAMPLE, "--today", TODAY)
        self.assertEqual(out1, out2)


class TestSlope(unittest.TestCase):
    """A3：Theil-Sen 斜率。"""

    def test_a3_median_of_pairwise_slopes(self):
        rows = [row("m", y, v) for y, v in zip(ann(1, 1), [100, 110, 121])]
        self.assertAlmostEqual(bl.theil_sen_slope(rows), 10.5)  # median(10, 10.5, 11)

    def test_a3_outlier_lab_error_does_not_hijack(self):
        # 最后一次化验失误 500：Theil-Sen 中位 10.25，OLS 会给 82 —— 差 8 倍
        rows = [row("m", y, v) for y, v in zip(ann(1, 1, y0=2020, n=5), [100, 110, 121, 130, 500])]
        ts = bl.theil_sen_slope(rows)
        self.assertLess(ts, 20.0)
        xs = [bl.decimal_year(r.date) for r in rows]
        ys = [r.value for r in rows]
        mean_x, mean_y = sum(xs) / 5, sum(ys) / 5
        ols = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sum((x - mean_x) ** 2 for x in xs)
        self.assertGreater(ols, 80.0)


class TestLadder(unittest.TestCase):
    """A2/A4/A5/A6：状态阶梯与门禁语义。"""

    def analyze(self, values, low="0", high="100", y0=2020):
        rows = [row("m", y, v, low=low, high=high)
                for y, v in zip(ann(1, 1, y0=y0, n=len(values)), values)]
        return bl.analyze(rows)

    def test_a2_thin_never_judges_and_never_gates(self):
        rows = [row("m", "2024-01-01", 90), row("m", "2025-01-01", 99)]
        a = bl.analyze(rows)
        self.assertEqual(a["status"], "THIN")
        self.assertFalse(a["gate"])
        code, out, _ = run_cli("panel", tsv(["m\t2024-01-01\t90\tx\t0\t100",
                                             "m\t2025-01-01\t99\tx\t0\t100"]), "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("◌ THIN", out)
        self.assertIn("满 3 次才判趋势", out)

    def test_a4_noise_floor_blocks_flat_jitter(self):
        a = self.analyze([90, 91, 92])  # 净涨 2 < 宽度 100 的 10%
        self.assertFalse(a["climbing"])
        self.assertEqual(a["status"], "STEADY")

    def test_a4_negative_slope_not_climbing(self):
        a = self.analyze([95, 92, 90])
        self.assertFalse(a["climbing"])
        self.assertEqual(a["status"], "STEADY")

    def test_a5_borderline_gates_at_or_under_three_years(self):
        a = self.analyze([75, 80, 85])  # 斜率 5，余量 (100-85)/5 = 3.0 年
        self.assertEqual(a["status"], "BORDERLINE")
        self.assertTrue(a["gate"])

    def test_a5_watch_over_three_years_does_not_gate(self):
        a = self.analyze([70, 75, 80])  # 余量 4.0 年
        self.assertEqual(a["status"], "WATCH")
        self.assertFalse(a["gate"])

    def test_a6_over_climbing_gates(self):
        a = self.analyze([90, 100, 110])  # 2022 年 110 > 100 越线，净涨 20 ≥ 10
        self.assertEqual(a["status"], "OVER")
        self.assertTrue(a["climbing"])
        self.assertTrue(a["gate"])

    def test_a6_over_but_managed_does_not_gate(self):
        a = self.analyze([110, 105, 104])  # 越线但斜率为负
        self.assertEqual(a["status"], "OVER")
        self.assertFalse(a["climbing"])
        self.assertFalse(a["gate"])
        p = tsv(["m\t2024-01-01\t110\tx\t0\t100",
                 "m\t2025-01-01\t105\tx\t0\t100",
                 "m\t2026-01-01\t104\tx\t0\t100"])
        code, out, _ = run_cli("panel", p, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("已企稳/在管", out)

    def test_a20_down_trend_gets_credit(self):
        a = self.analyze([80, 75, 70])  # 净跌 10 ≥ 10%
        self.assertTrue(a["down"])
        self.assertEqual(a["status"], "STEADY")


class ExampleLedgerTest(unittest.TestCase):
    """A7/A8/A9/A19/A20/A22：示例账本（老陈 2019-2025）的端到端读数。"""

    def test_a9_panel_red_gates(self):
        code, out, _ = run_cli("panel", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("判定  RED —— 4 项在爬", out)
        self.assertIn("越线的还在爬（bmi、uric-acid）；贴线的快到线（ldl、fasting-glucose）", out)
        self.assertIn("「正常」是区间，不是方向", out)

    def test_a7_first_cross_year_and_over_count(self):
        code, out, _ = run_cli("panel", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("2022 首越 · 线上 4 次 · 仍在爬", out)   # bmi 24.2 > 23.9
        self.assertIn("2023 首越 · 线上 3 次 · 仍在爬", out)   # uric 432 > 428
        code2, out2, _ = run_cli("trend", EXAMPLE, "--marker", "uric-acid", "--today", TODAY)
        self.assertEqual(code2, 0)
        self.assertIn("2023-09-12     432   101%   ✗ 越线（首次）", out2)
        self.assertIn("2025-09-10     452   106%   ✗ 越线（第 3 次）", out2)
        self.assertIn("Theil-Sen 斜率   +9.02 /年（7 次测量 · 21 对斜率取中位）", out2)
        self.assertIn("已越线：2023 年首次越线，线上 3 次，且仍在爬——门禁 RED", out2)

    def test_a8_runway_uses_latest_range_and_slope(self):
        _, out, _ = run_cli("trend", EXAMPLE, "--marker", "fasting-glucose", "--today", TODAY)
        self.assertIn("按当前斜率 0.7 年到线（上限 6.1，最新 6）", out)
        self.assertIn("净涨幅           +0.9（区间宽度的 41%", out)
        code, out2, _ = run_cli("panel", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("贴线爬坡 · 距线 0.2 年", out2)   # ldl
        self.assertIn("在爬 · 余量 3.6 年", out2)         # sbp WATCH

    def test_a19_panel_sorting_deterministic(self):
        _, out, _ = run_cli("panel", EXAMPLE, "--today", TODAY)
        self.assertLess(out.index("✗ OVER     bmi"), out.index("✗ OVER     uric-acid"))  # 2022 首越 < 2023
        self.assertLess(out.index("▲ BORDER   ldl"), out.index("▲ BORDER   fasting-glucose"))  # 余量 0.2 < 0.7
        self.assertLess(out.index("○ WATCH    sbp"), out.index("· STEADY   alt"))
        self.assertGreater(out.index("◌ THIN     tsh"), out.index("· STEADY   hemoglobin"))

    def test_a20_alt_self_heals_with_credit(self):
        _, out, _ = run_cli("trend", EXAMPLE, "--marker", "alt", "--today", TODAY)
        self.assertIn("▽ 方向向下：净跌 +5，占区间宽度 16%", out)
        _, panel, _ = run_cli("panel", EXAMPLE, "--today", TODAY)
        self.assertIn("▽ 在降", panel)

    def test_a22_ldl_upper_only_reference(self):
        _, out, _ = run_cli("panel", EXAMPLE, "--today", TODAY)
        self.assertIn("≤ 3.4", out)
        _, trend, _ = run_cli("trend", EXAMPLE, "--marker", "ldl", "--today", TODAY)
        self.assertIn("参考 ≤ 3.4", trend)

    def test_a9_green_ledger_exits_zero(self):
        rows = []
        for y in (2023, 2024, 2025):
            rows.append(f"hemoglobin\t{y}-01-01\t{150 + (y - 2023)}\tg/L\t130\t175")
        code, out, _ = run_cli("panel", tsv(rows), "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("判定  GREEN", out)
        self.assertIn("化验噪声内", out)  # 净涨 2 < 宽度 45 的 10%

    def test_a15_range_change_rejudges_against_latest_range(self):
        p = tsv(["m\t2020-01-01\t80\tx\t0\t100",
                 "m\t2021-01-01\t85\tx\t0\t100",
                 "m\t2022-01-01\t95\tx\t0\t90"])  # 新医院区间更严：95 > 90 越线
        code, out, _ = run_cli("panel", p, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("✗ OVER", out)
        self.assertIn("参考区间自 2022-01-01 起变更（0-100 → 0-90）", out)
        _, trend, _ = run_cli("trend", p, "--marker", "m", "--today", TODAY)
        self.assertIn("2022-01-01      95   106%   ✗ 越线（首次）", trend)
        self.assertIn("* 参考区间自 2022-01-01 起变更：0-100 → 0-90", trend)
        self.assertIn("越线史按当年区间记，余量按最新区间算", trend)


class TestCommands(unittest.TestCase):
    """A10/A14/A17/A18：命令行为。"""

    def test_a10_trend_unknown_marker_refuses(self):
        code, _, err = run_cli("trend", EXAMPLE, "--marker", "crp", "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("没有「crp」这个指标", err)
        self.assertIn("uric-acid", err)  # 提示现有的指标

    def test_a14_markers_lists_known(self):
        code, out, _ = run_cli("markers")
        self.assertEqual(code, 0)
        for slug, unit, dept in [("uric-acid", "µmol/L", "风湿免疫"),
                                 ("fasting-glucose", "mmol/L", "内分泌"),
                                 ("ldl", "mmol/L", "心内科"),
                                 ("sbp", "mmHg", "心内科")]:
            self.assertIn(slug, out)
            self.assertIn(unit, out)
            self.assertIn(dept, out)
        self.assertIn("别抄网上的", out)  # 区间因医院/人群而异

    def test_a17_next_orders_and_advises(self):
        code, out, _ = run_cli("next", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("专项复查", out)
        self.assertIn("越线 4 次仍在爬", out)
        self.assertIn("半年加测：按当前斜率 0.2 年到线", out)
        self.assertIn("年度照旧：在爬但余量 3.6 年", out)
        self.assertIn("▽ 在降，方向是对的", out)
        self.assertIn("继续攒", out)
        self.assertIn("（营养科 / 内分泌）", out)   # bmi 科室
        self.assertIn("距上次体检 12 个月，账本新鲜", out)
        self.assertLess(out.index("✗ OVER     bmi"), out.index("◌ THIN     tsh"))

    def test_a17_thin_over_gets_must_test(self):
        p = tsv(["m\t2024-01-01\t90\tx\t0\t100",
                 "m\t2025-01-01\t105\tx\t0\t100"])
        code, out, _ = run_cli("next", p, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("已越线但点数不足——下次体检必测", out)

    def test_a18_staleness_warns(self):
        p = tsv(["sbp\t2024-05-01\t120\tmmHg\t90\t139",
                 "sbp\t2025-05-01\t122\tmmHg\t90\t139"])
        for cmd in ("panel", "next", "validate"):
            with self.subTest(cmd=cmd):
                code, out, _ = run_cli(cmd, p, "--today", TODAY)
                self.assertEqual(code, 0)
                self.assertIn("⚠ 距上次体检已", out)
                self.assertIn("账本过期", out)

    def test_a18_fresh_ledger_no_warning(self):
        code, out, _ = run_cli("validate", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("9 个指标 · 58 次测量", out)
        self.assertIn("（区间有变更）", out)
        self.assertIn("（THIN，不足 3 次）", out)
        self.assertIn("账本新鲜", out)
        self.assertNotIn("⚠", out)


if __name__ == "__main__":
    unittest.main()
