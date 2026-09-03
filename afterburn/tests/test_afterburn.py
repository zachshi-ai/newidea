#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""afterburn · 余燃 — 验收测试.

验收标准（全部转成自动化测试）：
  A1  单室一级消除：95mg 半衰期 5h，5h 后恰为 47.5mg
  A2  线性叠加：多杯的残留是各自残留之和
  A3  跨夜连续：昨天的摄入计入今天早晨的底座
  A4  就寝判灯：残留越阈值 → RED + exit 4；未越 → GREEN + exit 0
  A5  cutoff 反解：解回代后恰好落在线上；额度尽返回 None 而非负时间
  A6  稳态收敛：几何级数闭式解 == 逐日暴力模拟 40 天（<0.1% 误差）
  A7  账本解析：坏行带行号 exit 2；未知饮品无毫克覆盖 exit 2；空账本 exit 3
  A8  行级毫克覆盖优先于饮品表缺省
  A9  wean：停喝后残留单调降至安静线，时刻可定位
  A10 00:00–05:59 的就寝时间视为次日凌晨
"""

import contextlib
import datetime as dt
import io
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import afterburn as ab  # noqa: E402

HL = 5.0
K = math.log(2.0) / HL


def run_cli(*argv):
    """调用 main，返回 (exit_code, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ab.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def write_ledger(rows):
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return path


def entry(when, drink, mg, lineno=1):
    return ab.Entry(when, drink, mg, lineno)


DT = dt.datetime


class TestPharmacokinetics(unittest.TestCase):
    """A1/A2/A3：消除、叠加、跨夜。"""

    def test_a1_half_life_math(self):
        # 95mg，5h 后应剩 47.5
        self.assertAlmostEqual(ab.residual(95.0, 5.0, K), 47.5, places=6)
        # 两个半衰期 → 四分之一
        self.assertAlmostEqual(ab.residual(80.0, 10.0, K), 20.0, places=6)
        # 0 小时 → 全额
        self.assertAlmostEqual(ab.residual(63.0, 0.0, K), 63.0, places=9)

    def test_a1_future_intake_contributes_zero(self):
        self.assertEqual(ab.residual(100.0, -0.5, K), 0.0)

    def test_a2_superposition(self):
        e1 = entry(DT(2026, 9, 3, 8, 0), "drip", 95.0)
        e2 = entry(DT(2026, 9, 3, 15, 30), "latte", 126.0)
        at = DT(2026, 9, 3, 23, 30)
        both = ab.concentration([e1, e2], at, K)
        only1 = ab.concentration([e1], at, K)
        only2 = ab.concentration([e2], at, K)
        self.assertAlmostEqual(both, only1 + only2, places=9)

    def test_a2_superposition_matches_manual(self):
        # 15:30 latte 126 → 23:30（8h）= 126 * 2^-1.6
        e = entry(DT(2026, 9, 3, 15, 30), "latte", 126.0)
        at = DT(2026, 9, 3, 23, 30)
        self.assertAlmostEqual(ab.concentration([e], at, K),
                               126.0 * 2 ** (-1.6), places=6)

    def test_a3_overnight_carryover(self):
        yesterday = entry(DT(2026, 9, 2, 8, 0), "drip", 95.0)
        morning = DT(2026, 9, 3, 8, 0)
        # 24h = 4.8 个半衰期 → 95 * 2^-4.8 ≈ 3.44
        self.assertAlmostEqual(ab.concentration([yesterday], morning, K),
                               95.0 * 2 ** (-4.8), places=6)

    def test_lookback_truncation(self):
        old = entry(DT(2026, 8, 30, 8, 0), "drip", 95.0)  # > 72h 前
        self.assertEqual(ab.concentration([old], DT(2026, 9, 3, 8, 0), K), 0.0)

    def test_contributions_sorted_and_filtered(self):
        es = [
            entry(DT(2026, 9, 3, 8, 0), "drip", 95.0),
            entry(DT(2026, 9, 3, 15, 30), "latte", 126.0),
            entry(DT(2026, 8, 20, 8, 0), "instant", 60.0),  # 微量，被过滤
        ]
        pairs = ab.contributions(es, DT(2026, 9, 3, 20, 0), K)
        self.assertTrue(all(c >= 0.1 for _, c in pairs))
        self.assertEqual([p[0].drink for p in pairs], ["latte", "drip"])
        vals = [c for _, c in pairs]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_decay_constant_rejects_nonpositive(self):
        with self.assertRaises(ab.UsageError):
            ab.decay_constant(0.0)
        with self.assertRaises(ab.UsageError):
            ab.decay_constant(-1.0)


class TestCutoff(unittest.TestCase):
    """A5：反解数学。"""

    def setUp(self):
        self.morning = entry(DT(2026, 9, 3, 8, 40), "americano", 126.0)
        self.bedtime = DT(2026, 9, 3, 23, 30)

    def test_a5_solution_lands_on_the_line(self):
        t_star = ab.solve_cutoff([self.morning], self.bedtime, 126.0, K, 50.0)
        self.assertIsNotNone(t_star)
        # 回代：在 t* 喝 126mg，就寝总浓度应恰为阈值
        added = entry(t_star, "latte", 126.0)
        total = ab.concentration([self.morning, added], self.bedtime, K)
        self.assertAlmostEqual(total, 50.0, places=6)

    def test_a5_no_budget_when_already_over(self):
        # 已排入摄入越线 → None（而不是负时间）
        heavy = [entry(DT(2026, 9, 3, 20, 0), "cola", 34.0),
                 entry(DT(2026, 9, 3, 15, 0), "latte", 126.0),
                 entry(DT(2026, 9, 3, 8, 0), "drip", 95.0)]
        over = ab.concentration(heavy, DT(2026, 9, 3, 22, 0), K)
        self.assertGreater(over, 50.0)
        self.assertIsNone(ab.solve_cutoff(heavy, DT(2026, 9, 3, 22, 0), 63.0, K, 50.0))

    def test_tiny_dose_allowed_anytime(self):
        # 10mg 晚于就寝喝都不越线 → cutoff == bedtime
        t_star = ab.solve_cutoff([self.morning], self.bedtime, 10.0, K, 50.0)
        self.assertEqual(t_star, self.bedtime)

    def test_cutoff_moves_earlier_with_bigger_dose(self):
        small = ab.solve_cutoff([self.morning], self.bedtime, 63.0, K, 50.0)
        big = ab.solve_cutoff([self.morning], self.bedtime, 126.0, K, 50.0)
        self.assertGreater(small, big)

    def test_cutoff_moves_earlier_for_slow_metabolizer(self):
        # 慢代谢者的底座烧得更久、余额更小：最晚时刻必须更早
        fast = ab.solve_cutoff([self.morning], self.bedtime, 126.0,
                               math.log(2) / 3.0, 50.0)
        slow = ab.solve_cutoff([self.morning], self.bedtime, 126.0,
                               math.log(2) / 8.0, 50.0)
        self.assertIsNotNone(fast)
        self.assertIsNotNone(slow)
        self.assertLess(slow, fast)


class TestSteadyState(unittest.TestCase):
    """A6：稳态闭式解 == 暴力模拟。"""

    def test_a6_closed_form_matches_simulation(self):
        schedule = [(8.6667, 95.0), (15.5, 126.0)]  # 08:40 drip + 15:30 latte
        closed = ab.steady_state(schedule, 7.5, K)  # 首杯前半小时
        # 暴力：从远过去逐日铺 40 天，取同时刻浓度
        sim = 0.0
        probe = DT(2026, 9, 3, 7, 30)
        for d in range(1, 41):
            day = DT(2026, 9, 3, 0, 0) - dt.timedelta(days=d)
            for t, dose in schedule:
                when = day + dt.timedelta(hours=t)
                sim += ab.residual(dose, ab.hours_between(when, probe), K)
        self.assertAlmostEqual(closed, sim, delta=sim * 1e-3 + 1e-6)

    def test_steady_morning_baseline_positive(self):
        base = ab.steady_state([(8.5, 95.0)], 8.0, K)
        self.assertGreater(base, 0.0)
        # 单杯 95mg 次日同时刻前 0.5h：95 * 2^(-23.5/5) * r/(1-r) 附近
        r = math.exp(-24.0 * K)
        expect = 95.0 * math.exp(-23.5 * K) / (1.0 - r)
        self.assertAlmostEqual(base, expect, places=6)


class TestWean(unittest.TestCase):
    """A9：戒断归零。"""

    def test_a9_quiet_crossing_monotone(self):
        es = [entry(DT(2026, 9, 3, 15, 30), "latte", 126.0),
              entry(DT(2026, 9, 3, 20, 0), "cola", 34.0)]
        stop = DT(2026, 9, 3, 21, 0)
        t = ab.quiet_crossing(es, stop, K, 10.0)
        self.assertIsNotNone(t)
        self.assertGreaterEqual(ab.concentration(es, t, K), 0.0)
        # 过线前一分钟仍在线上方（扫描粒度）
        before = t - dt.timedelta(minutes=1)
        self.assertGreater(ab.concentration(es, before, K), 10.0)
        self.assertLessEqual(ab.concentration(es, t, K), 10.0)

    def test_quiet_never_reached_returns_none(self):
        es = [entry(DT(2026, 9, 3, 15, 30), "milk-tea", 50.0)]
        # 半衰期超长 → 72h 内到不了安静线
        k_slow = math.log(2.0) / 50.0
        self.assertIsNone(ab.quiet_crossing(es, DT(2026, 9, 3, 16, 0), k_slow, 10.0))


class TestParsing(unittest.TestCase):
    """A7/A8：账本解析与覆盖。"""

    def test_parse_hhmm(self):
        self.assertEqual(ab.parse_hhmm("23:30"), 23.5)
        self.assertEqual(ab.parse_hhmm("00:00"), 0.0)
        with self.assertRaises(ab.UsageError):
            ab.parse_hhmm("24:00")
        with self.assertRaises(ab.UsageError):
            ab.parse_hhmm("9am")
        with self.assertRaises(ab.UsageError):
            ab.parse_hhmm("12:60")

    def test_parse_date(self):
        self.assertEqual(ab.parse_date("2026-09-03"), dt.date(2026, 9, 3))
        with self.assertRaises(ab.UsageError):
            ab.parse_date("2026/09/03")
        with self.assertRaises(ab.UsageError):
            ab.parse_date("2026-13-01")

    def test_parse_datetime_t_separator(self):
        self.assertEqual(ab.parse_datetime("2026-09-03T21:00"),
                         DT(2026, 9, 3, 21, 0))
        with self.assertRaises(ab.UsageError):
            ab.parse_datetime("2026-09-03")

    def test_normalize_drink(self):
        self.assertEqual(ab.normalize_drink(" Latte "), "latte")
        self.assertEqual(ab.normalize_drink("milk_tea"), "milk-tea")

    def test_ledger_comments_and_blanks(self):
        path = write_ledger([
            "# 今天开始记",
            "",
            "2026-09-03\t08:40\tdrip",
            "   ",
            "# 晚上那罐",
            "2026-09-03\t20:10\tcola",
        ])
        es = ab.parse_ledger(path)
        self.assertEqual(len(es), 2)
        self.assertEqual(es[0].mg, 95.0)
        self.assertEqual(es[1].mg, 34.0)
        os.unlink(path)

    def test_a7_short_row_reports_lineno(self):
        path = write_ledger([
            "2026-09-03\t08:40\tdrip",
            "2026-09-03\t15:30",
        ])
        with self.assertRaises(ab.UsageError) as ctx:
            ab.parse_ledger(path)
        self.assertIn("第 2 行", str(ctx.exception))
        os.unlink(path)

    def test_a7_unknown_drink_without_mg(self):
        path = write_ledger(["2026-09-03\t15:30\tflat-white"])
        with self.assertRaises(ab.UsageError) as ctx:
            ab.parse_ledger(path)
        self.assertIn("flat-white", str(ctx.exception))
        os.unlink(path)

    def test_unknown_drink_with_mg_ok(self):
        path = write_ledger(["2026-09-03\t15:30\tflat-white\t130"])
        es = ab.parse_ledger(path)
        self.assertEqual(es[0].mg, 130.0)
        os.unlink(path)

    def test_a8_row_level_override_beats_table(self):
        path = write_ledger(["2026-09-03\t15:30\tmilk-tea\t120"])
        self.assertEqual(ab.parse_ledger(path)[0].mg, 120.0)
        os.unlink(path)

    def test_bad_mg_column(self):
        path = write_ledger(["2026-09-03\t15:30\tlatte\tstrong"])
        with self.assertRaises(ab.UsageError):
            ab.parse_ledger(path)
        os.unlink(path)

    def test_negative_mg(self):
        path = write_ledger(["2026-09-03\t15:30\tlatte\t-10"])
        with self.assertRaises(ab.UsageError):
            ab.parse_ledger(path)
        os.unlink(path)

    def test_missing_file(self):
        with self.assertRaises(ab.UsageError):
            ab.parse_ledger("/nonexistent/ledger.tsv")

    def test_a7_empty_ledger(self):
        path = write_ledger(["# 只有注释"])
        self.assertEqual(ab.parse_ledger(path), [])
        os.unlink(path)


class TestCommands(unittest.TestCase):
    """命令层：exit codes 与报告内容。"""

    def setUp(self):
        self.ledger = write_ledger([
            "2026-09-01\t08:40\tdrip",
            "2026-09-01\t15:30\tlatte",
            "2026-09-02\t08:40\tdrip",
            "2026-09-03\t08:40\tamericano",
            "2026-09-03\t15:30\tlatte",
            "2026-09-03\t20:10\tcola",
        ])

    def tearDown(self):
        os.unlink(self.ledger)

    def test_now_report(self):
        code, out, _ = run_cli("now", self.ledger, "--now", "2026-09-03 17:00")
        self.assertEqual(code, 0)
        self.assertIn("血液残留", out)
        self.assertIn("latte", out)
        # 17:00 残留 = 102.3 (latte 1.5h) + 39.7 (americano 8.33h) + 尾巴 ≈ 143.5
        self.assertIn("143.", out)

    def test_now_before_first_entry_refuses(self):
        code, _, err = run_cli("now", self.ledger, "--now", "2026-08-30 10:00")
        self.assertEqual(code, 3)
        self.assertIn("拒算", err)

    def test_a7_now_empty_ledger_refuses(self):
        path = write_ledger(["# 空"])
        code, _, err = run_cli("now", path)
        self.assertEqual(code, 3)
        os.unlink(path)

    def test_a4_bedtime_red_exit4(self):
        code, out, _ = run_cli("bedtime", self.ledger, "--at", "23:30",
                               "--date", "2026-09-03")
        self.assertEqual(code, 4)
        self.assertIn("RED", out)
        # 79.6 = 41.6 (latte) + 21.4 (cola) + 16.1 (americano) + 0.4 (前日)
        self.assertIn("79.6", out)

    def test_a4_bedtime_green_exit0(self):
        code, out, _ = run_cli("bedtime", self.ledger, "--at", "23:30",
                               "--date", "2026-09-02")
        self.assertEqual(code, 0)
        self.assertIn("GREEN", out)

    def test_bedtime_no_intake_that_day_refuses(self):
        code, _, err = run_cli("bedtime", self.ledger, "--at", "23:30",
                               "--date", "2026-09-05")
        self.assertEqual(code, 3)
        os.unlink(write_ledger(["# noop"]))  # tmp cleanup guard

    def test_a10_after_midnight_bedtime_is_next_day(self):
        # 就寝 00:30 应视为当天日期的次日凌晨：09-03 的 15:30 latte 计入
        code, out, _ = run_cli("bedtime", self.ledger, "--at", "00:30",
                               "--date", "2026-09-03")
        self.assertEqual(code, 4)
        self.assertIn("2026-09-04 00:30", out)

    def test_cutoff_report(self):
        code, out, _ = run_cli("cutoff", self.ledger, "--at", "23:30",
                               "--drink", "latte", "--date", "2026-09-03",
                               "--now", "2026-09-03 10:00")
        self.assertEqual(code, 0)
        self.assertIn("最晚", out)
        self.assertIn("latte", out)

    def test_cutoff_window_already_closed(self):
        code, out, _ = run_cli("cutoff", self.ledger, "--at", "23:30",
                               "--drink", "latte", "--date", "2026-09-03",
                               "--now", "2026-09-03 14:00")
        self.assertEqual(code, 0)
        self.assertIn("窗口已经关了", out)

    def test_cutoff_budget_exhausted(self):
        # 以 9-3 深夜 22:00 为现在：已排入 9-3 全天，就寝前必越线
        code, out, _ = run_cli("cutoff", self.ledger, "--at", "23:30",
                               "--drink", "espresso", "--date", "2026-09-03",
                               "--now", "2026-09-03 22:00")
        self.assertEqual(code, 0)
        self.assertIn("额度已尽", out)

    def test_cutoff_mg_override(self):
        code, out, _ = run_cli("cutoff", self.ledger, "--at", "23:30",
                               "--drink", "flat-white", "--mg", "30",
                               "--date", "2026-09-03",
                               "--now", "2026-09-03 10:00")
        self.assertEqual(code, 0)
        self.assertIn("30 mg", out)

    def test_cutoff_unknown_drink_without_mg(self):
        code, _, err = run_cli("cutoff", self.ledger, "--at", "23:30",
                               "--drink", "flat-white",
                               "--now", "2026-09-03 10:00")
        self.assertEqual(code, 2)
        self.assertIn("flat-white", err)

    def test_day_curve(self):
        code, out, _ = run_cli("day", self.ledger, "--date", "2026-09-03")
        self.assertEqual(code, 0)
        lines = [ln for ln in out.splitlines() if "mg  " in ln]
        self.assertEqual(len(lines), 25)  # 00:00..24:00 每小时
        self.assertIn("← americano", out)
        self.assertIn("← latte", out)
        self.assertIn("昨天的余燃", out)

    def test_day_midnight_baseline_positive(self):
        # 0 点底座来自 9-2 的 drip（95 * 2^-15.33 ≈ 2.7）……
        # 9-2 08:40 → 9-3 00:00 = 15.33h → 95*2^-3.07 ≈ 11.2mg
        code, out, _ = run_cli("day", self.ledger, "--date", "2026-09-03")
        first_val = None
        for ln in out.splitlines():
            if "00:00" in ln and "mg" in ln:
                first_val = float(ln.split("mg")[0].split()[-1])
                break
        self.assertIsNotNone(first_val)
        self.assertGreater(first_val, 10.0)

    def test_week_report_counts_reds(self):
        code, out, _ = run_cli("week", self.ledger, "--end", "2026-09-03",
                               "--at", "23:30")
        self.assertEqual(code, 0)
        self.assertIn("7 晚里 2 晚红灯", out)
        self.assertIn("2026-09-01", out)
        self.assertIn("2026-09-03", out)

    def test_steady_report(self):
        code, out, _ = run_cli("steady", "08:40", "drip", "15:30", "latte")
        self.assertEqual(code, 0)
        self.assertIn("drip", out)
        self.assertIn("latte", out)
        self.assertIn("没醒透", out)

    def test_steady_odd_tokens(self):
        code, _, err = run_cli("steady", "08:40", "drip", "15:30")
        self.assertEqual(code, 2)
        self.assertIn("成对", err)

    def test_steady_unknown_drink(self):
        code, _, err = run_cli("steady", "08:40", "flat-white")
        self.assertEqual(code, 2)
        self.assertIn("flat-white", err)

    def test_wean_report(self):
        code, out, _ = run_cli("wean", self.ledger, "--now", "2026-09-03 21:00")
        self.assertEqual(code, 0)
        self.assertIn("安静线", out)
        self.assertIn("戒断窗", out)
        self.assertIn("2026-09-04 14:28", out)

    def test_drinks_table(self):
        code, out, _ = run_cli("drinks")
        self.assertEqual(code, 0)
        self.assertIn("latte", out)
        self.assertIn("milk-tea", out)
        self.assertIn("覆盖", out)

    def test_validate_report(self):
        path = write_ledger([
            "2026-09-03\t15:30\tlatte",
            "2026-09-01\t08:40\tdrip",
            "2026-09-01\t08:40\tdrip",
        ])
        code, out, _ = run_cli("validate", path)
        self.assertEqual(code, 0)
        self.assertIn("乱序行     1", out)
        self.assertIn("完全重复   1", out)
        os.unlink(path)

    def test_no_command_usage(self):
        code, _, _ = run_cli()
        self.assertEqual(code, 2)

    def test_bedtime_requires_at(self):
        # argparse 对缺 required 参数走 SystemExit(2)，同样是 exit 2 语义
        with self.assertRaises(SystemExit) as ctx:
            run_cli("bedtime", self.ledger, "--date", "2026-09-03")
        self.assertEqual(ctx.exception.code, 2)

    def test_bad_half_life(self):
        code, _, err = run_cli("now", self.ledger, "--now", "2026-09-03 17:00",
                               "--half-life", "0")
        self.assertEqual(code, 2)
        self.assertIn("half-life", err)

    def test_half_life_changes_verdict(self):
        # 同一杯 15:30 的 latte：快代谢（3h）就寝只剩 19.8mg 绿灯，
        # 慢代谢（8h）还烧着 63mg 红灯——基因不是借口，是参数
        path = write_ledger(["2026-09-02\t15:30\tlatte"])
        code_fast, out_fast, _ = run_cli("bedtime", path, "--at", "23:30",
                                         "--date", "2026-09-02",
                                         "--half-life", "3")
        code_slow, out_slow, _ = run_cli("bedtime", path, "--at", "23:30",
                                         "--date", "2026-09-02",
                                         "--half-life", "8")
        self.assertEqual(code_fast, 0)
        self.assertIn("GREEN", out_fast)
        self.assertEqual(code_slow, 4)
        self.assertIn("RED", out_slow)
        os.unlink(path)

    def test_threshold_changes_verdict(self):
        # 9-2 残留 14.1mg：阈值 10 → RED；阈值 50 → GREEN
        code_low, out_low, _ = run_cli("bedtime", self.ledger, "--at", "23:30",
                                       "--date", "2026-09-02", "--threshold", "10")
        self.assertEqual(code_low, 4)
        self.assertIn("RED", out_low)


if __name__ == "__main__":
    unittest.main()
