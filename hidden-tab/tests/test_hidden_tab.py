# -*- coding: utf-8 -*-
"""瘾账 · Hidden Tab —— 验收标准全部转成自动化测试。

样例账本 examples/smoking.tsv 的真值全部手算钉死：
  attempt1  2026-03-02 quit（基线 15）→ 05-20 复发
            跨度 03-02..06-17 = 108 天；clean 77（40+37）；lapse 2 天 5 根
            复发期 29 天（记 3 行 45 根，插补 26 天）；实抽 440；已省 1180
  attempt2  2026-06-18 quit（基线 15）→ 账本末日 2026-08-31（today 打卡行）
            跨度 75 天；clean 73（42+4+27）；lapse 2 天 3 根；实抽 3；已省 1122
  全史      已省 2302 根 = ¥2,877.50（@¥25/包÷20）；纯无烟 150 天；最长纯无烟 42
  复发      第一次活了 79 天，最后一场 lapse 之后 38 天弹回
"""

import argparse
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "hidden_tab.py")
SAMPLE = os.path.join(ROOT, "examples", "smoking.tsv")

sys.path.insert(0, ROOT)
import hidden_tab as ht  # noqa: E402


def write_ledger(rows):
    """rows: (date, kind, n, baseline, trigger, note) —— None 写空列。"""
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("date\tkind\tn\tbaseline\ttrigger\tnote\n")
        for r in rows:
            d, kind = r[0], r[1]
            n = r[2] if len(r) > 2 else None
            b = r[3] if len(r) > 3 else None
            t = r[4] if len(r) > 4 else ""
            note = r[5] if len(r) > 5 else ""
            f.write("%s\t%s\t%s\t%s\t%s\t%s\n" % (
                d, kind, "" if n is None else n,
                "" if b is None else b, t, note))
    return path


def args(**kw):
    base = dict(as_of=None, price=None, pack_size=20, minutes=5,
                baseline=None, relapse_days=3, relapse_line=0.5,
                milestone=None, no_default_milestones=False)
    base.update(kw)
    return argparse.Namespace(**base)


def run_cli(*argv):
    p = subprocess.run([sys.executable, CLI] + list(argv),
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def sample_ledger():
    return ht.Ledger(SAMPLE, args(price=25))


# ---------------------------------------------------------------- 解析层

class TestParse(unittest.TestCase):
    def test_sample_rows_sorted_and_kinds(self):
        ev = ht.parse_ledger(SAMPLE)
        self.assertEqual(len(ev), 11)
        self.assertEqual([e["kind"] for e in ev],
                         ["smoke", "quit", "smoke", "smoke", "smoke",
                          "smoke", "smoke", "quit", "smoke", "smoke", "today"])
        self.assertTrue(all(ev[i]["date"] <= ev[i + 1]["date"]
                            for i in range(len(ev) - 1)))

    def test_alias_normalization(self):
        path = write_ledger([
            ("2026-01-01", "烟", 12), ("2026-01-02", "cigarettes", 10),
            ("2026-01-03", "抽烟", 11), ("2026-01-10", "戒烟", None, 11),
            ("2026-01-25", "打卡"), ("2026-01-25", "checkin"),
        ])
        led = ht.Ledger(path, args())
        self.assertEqual(led.quit_count, 1)
        self.assertEqual(led.as_of, date(2026, 1, 25))

    def test_unknown_kind_is_ledger_error(self):
        path = write_ledger([("2026-01-01", "vape", 1)])
        with self.assertRaises(ht.LedgerError):
            ht.parse_ledger(path)

    def test_smoke_without_n_is_error(self):
        path = write_ledger([("2026-01-01", "smoke", None)])
        with self.assertRaises(ht.LedgerError):
            ht.parse_ledger(path)

    def test_quit_with_n_is_error(self):
        path = write_ledger([("2026-01-01", "quit", 3)])
        with self.assertRaises(ht.LedgerError):
            ht.parse_ledger(path)

    def test_today_with_n_is_error(self):
        path = write_ledger([("2026-01-01", "today", 3)])
        with self.assertRaises(ht.LedgerError):
            ht.parse_ledger(path)

    def test_bad_date_and_bad_n(self):
        for rows, exc in (
                ([("2026-13-01", "smoke", 1)], ht.LedgerError),
                ([("not-a-date", "smoke", 1)], ht.LedgerError),
                ([("2026-01-01", "smoke", 2.5)], ht.LedgerError),
                ([("2026-01-01", "smoke", 0)], ht.LedgerError),
                ([("2026-01-01", "smoke", -3)], ht.LedgerError),
                ([("2026-01-01", "smoke", 1, 0.05)], ht.LedgerError),
                ([("2026-01-01", "smoke", 1, 999)], ht.LedgerError)):
            path = write_ledger(rows)
            with self.assertRaises(exc):
                ht.parse_ledger(path)

    def test_empty_ledger_is_error(self):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("date\tkind\tn\n")
        with self.assertRaises(ht.LedgerError):
            ht.parse_ledger(path)


# ---------------------------------------------------------------- 样例真值

class TestSampleGroundTruth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = sample_ledger()
        cls.a1, cls.a2 = cls.led.attempts

    def test_two_attempts_and_pre_history(self):
        self.assertEqual(self.led.quit_count, 2)
        self.assertEqual(len(self.led.pre_rows), 1)
        self.assertEqual(self.led.pre_rows[0]["date"], date(2025, 6, 1))

    def test_ledger_span_457_days(self):
        self.assertEqual(self.led.span, 457)
        self.assertEqual(self.led.as_of, date(2026, 8, 31))

    def test_attempt1_full_anatomy(self):
        a = self.a1
        self.assertEqual(a.quit_date, date(2026, 3, 2))
        self.assertEqual(a.end_date, date(2026, 6, 17))
        self.assertEqual(a.span_days, 108)
        self.assertEqual(a.baseline, 15)
        self.assertEqual(a.baseline_src, "claim")
        self.assertEqual(a.clean_days, 77)
        self.assertEqual(a.lapse_days, 2)
        self.assertEqual(a.lapse_cigs, 5)
        self.assertEqual(a.relapse_days, 29)
        self.assertEqual(a.relapse_recorded_cigs, 45)
        self.assertEqual(a.imputed_days, 26)
        self.assertEqual(a.actual_cigs, 440)
        self.assertEqual(a.saved_cigs, 1180)
        self.assertEqual(a.relapse_start, date(2026, 5, 20))
        self.assertFalse(a.alive)
        self.assertEqual(a.effective_days, 79)

    def test_attempt1_clean_runs(self):
        self.assertEqual(self.a1.clean_runs, [
            (date(2026, 3, 2), date(2026, 4, 10), 40),
            (date(2026, 4, 13), date(2026, 5, 19), 37),
        ])
        self.assertEqual(self.a1.lapse_runs,
                         [[date(2026, 4, 11), date(2026, 4, 12), 5]])
        self.assertEqual(self.a1.longest_clean(), 40)
        self.assertEqual(self.a1.clock_days(date(2026, 8, 31)), 79)

    def test_attempt2_full_anatomy(self):
        a = self.a2
        self.assertEqual(a.span_days, 75)
        self.assertEqual(a.clean_days, 73)
        self.assertEqual(a.lapse_days, 2)
        self.assertEqual(a.lapse_cigs, 3)
        self.assertEqual(a.relapse_days, 0)
        self.assertTrue(a.alive)
        self.assertEqual(a.actual_cigs, 3)
        self.assertEqual(a.saved_cigs, 1122)
        self.assertEqual(a.clean_runs, [
            (date(2026, 6, 18), date(2026, 7, 29), 42),
            (date(2026, 7, 31), date(2026, 8, 3), 4),
            (date(2026, 8, 5), date(2026, 8, 31), 27),
        ])
        self.assertEqual(a.trailing_clean(), 27)
        self.assertEqual(a.longest_clean(), 42)
        self.assertEqual(a.clock_days(date(2026, 8, 31)), 75)

    def test_totals(self):
        tot_saved = sum(a.saved_cigs for a in self.led.attempts)
        tot_clean = sum(a.clean_days for a in self.led.attempts)
        self.assertEqual(tot_saved, 2302)
        self.assertEqual(tot_clean, 150)
        self.assertEqual(self.led.price_per_cig(), 1.25)
        self.assertAlmostEqual(1122 * 1.25, 1402.50, places=6)
        self.assertAlmostEqual(2302 * 1.25, 2877.50, places=6)

    def test_current_alive_not_stalled(self):
        self.assertIsNotNone(self.led.current)
        self.assertTrue(self.led.current.alive)
        self.assertFalse(self.led.stalled())

    def test_relapse_dual_algorithms_agree_on_sample(self):
        a1 = self.a1
        self.assertEqual(
            ht.find_relapse_by_window(a1, 3, 0.5), date(2026, 5, 20))
        self.assertEqual(a1.relapse_start, ht.find_relapse_by_window(a1, 3, 0.5))
        self.assertIsNone(
            ht.find_relapse_by_window(self.a2, 3, 0.5))


# ---------------------------------------------------------------- 复发规则

class TestRelapseRule(unittest.TestCase):
    def build(self, rows):
        return ht.Ledger(write_ledger(rows), args())

    def test_exactly_three_days_at_line_is_relapse(self):
        led = self.build([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-05", "smoke", 5), ("2026-01-06", "smoke", 5),
            ("2026-01-07", "smoke", 5),
            ("2026-01-30", "today"),
        ])
        a = led.current
        self.assertFalse(a.alive)
        self.assertEqual(a.relapse_start, date(2026, 1, 5))
        self.assertEqual(a.effective_days, 4)

    def test_two_consecutive_days_is_lapse_not_relapse(self):
        led = self.build([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-05", "smoke", 9), ("2026-01-06", "smoke", 9),
            ("2026-01-30", "today"),
        ])
        a = led.current
        self.assertTrue(a.alive)
        self.assertIsNone(a.relapse_start)
        self.assertEqual(a.lapse_runs, [[date(2026, 1, 5), date(2026, 1, 6), 18]])

    def test_three_sparse_days_below_line_is_not_relapse(self):
        led = self.build([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-05", "smoke", 1), ("2026-01-07", "smoke", 1),
            ("2026-01-09", "smoke", 1),
            ("2026-01-30", "today"),
        ])
        self.assertTrue(led.current.alive)

    def test_heavy_single_day_stays_lapse(self):
        led = self.build([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-05", "smoke", 25),
            ("2026-01-30", "today"),
        ])
        a = led.current
        self.assertTrue(a.alive)
        self.assertEqual(a.lapse_days, 1)
        # 桶分解：clean 29×10 + lapse (10−25) = 275 = 10×30 − 25
        self.assertEqual(a.clean_days, 29)
        self.assertEqual(a.saved_cigs, 275)

    def test_relapse_era_imputes_baseline(self):
        led = self.build([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-10", "smoke", 10), ("2026-01-11", "smoke", 10),
            ("2026-01-12", "smoke", 10),
            # 01-13..01-19 没记：活跃吸烟期按基线插补 7 天
            ("2026-01-20", "quit", None, 10),
            ("2026-01-30", "today"),
        ])
        a = led.attempts[0]
        self.assertEqual(a.relapse_days, 10)   # 01-10..01-19
        self.assertEqual(a.relapse_recorded_days, 3)
        self.assertEqual(a.imputed_days, 7)
        self.assertEqual(a.actual_cigs, 30 + 70)
        self.assertEqual(a.saved_cigs, 10 * 19 - 100)  # 跨度 01-01..01-19
        self.assertFalse(led.attempts[0].alive)
        self.assertTrue(led.attempts[1].alive)

    def test_relapse_needs_baseline(self):
        led = self.build([
            ("2026-01-01", "quit", None, None),
            ("2026-01-10", "smoke", 10), ("2026-01-11", "smoke", 10),
            ("2026-01-12", "smoke", 10),
            ("2026-01-30", "today"),
        ])
        a = led.current
        self.assertIsNone(a.baseline)
        self.assertTrue(a.alive)  # 无基线无法判复发——如实拒绝，不硬判

    def test_two_lapse_to_relapse_transitions_mean(self):
        led = self.build([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-20", "smoke", 2),
            ("2026-02-01", "smoke", 10), ("2026-02-02", "smoke", 10),
            ("2026-02-03", "smoke", 10),
            ("2026-02-20", "quit", None, 10),
            ("2026-03-01", "smoke", 1),
            ("2026-03-15", "smoke", 9), ("2026-03-16", "smoke", 10),
            ("2026-03-17", "smoke", 11),
            ("2026-04-01", "quit", None, 10),
            ("2026-04-30", "today"),
        ])
        gaps = [(a.relapse_start - a.lapse_runs[-1][1]).days
                for a in led.attempts if a.dead and a.lapse_runs]
        self.assertEqual(gaps, [12, 14])
        self.assertTrue(led.attempts[2].alive)


# ---------------------------------------------------------------- 基线

class TestBaseline(unittest.TestCase):
    def test_history_fallback_from_daily_rows(self):
        led = ht.Ledger(write_ledger([
            ("2026-01-01", "smoke", 10), ("2026-01-02", "smoke", 12),
            ("2026-01-03", "smoke", 11),
            ("2026-01-10", "quit", None, None),
            ("2026-01-25", "today"),
        ]), args())
        a = led.current
        self.assertEqual(a.baseline, 11.0)
        self.assertEqual(a.baseline_src, "history")
        self.assertEqual(a.saved_cigs, 11 * 16)  # 跨度 01-10..01-25 = 16 天

    def test_history_needs_min_rows(self):
        led = ht.Ledger(write_ledger([
            ("2026-01-08", "smoke", 10), ("2026-01-09", "smoke", 12),
            ("2026-01-10", "quit", None, None),
            ("2026-01-25", "today"),
        ]), args())
        self.assertIsNone(led.current.baseline)

    def test_flag_fills_missing_never_overrides_claim(self):
        fill = ht.Ledger(write_ledger([
            ("2026-01-10", "quit", None, None), ("2026-01-25", "today"),
        ]), args(baseline=9))
        self.assertEqual(fill.current.baseline, 9)
        self.assertEqual(fill.current.baseline_src, "flag")
        claim = ht.Ledger(write_ledger([
            ("2026-01-10", "quit", None, 15), ("2026-01-25", "today"),
        ]), args(baseline=9))
        self.assertEqual(claim.current.baseline, 15)
        self.assertEqual(claim.current.baseline_src, "claim")


# ---------------------------------------------------------------- 边界

class TestEdges(unittest.TestCase):
    def test_quit_and_smoke_same_day(self):
        led = ht.Ledger(write_ledger([
            ("2026-01-01", "smoke", 10),
            ("2026-01-05", "quit", None, 10),
            ("2026-01-05", "smoke", 1),      # 当天最后一支：记 smoke 行
            ("2026-01-20", "today"),
        ]), args())
        a = led.current
        self.assertEqual(a.span_days, 16)
        self.assertEqual(a.lapse_days, 1)
        self.assertEqual(a.clean_days, 15)
        self.assertEqual(a.anchor(), date(2026, 1, 6))  # quit 日不干净，次日起算
        self.assertEqual(a.clock_days(date(2026, 1, 20)), 15)
        self.assertEqual(a.trailing_clean(), 15)
        self.assertEqual(a.saved_cigs, 10 * 16 - 1)

    def test_same_day_double_quit_dedupes(self):
        led = ht.Ledger(write_ledger([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-01", "quit", None, 12),   # 后一行覆盖
            ("2026-01-15", "today"),
        ]), args())
        self.assertEqual(led.quit_count, 1)
        self.assertEqual(led.current.baseline, 12)

    def test_today_row_extends_as_of_only(self):
        led = ht.Ledger(write_ledger([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-10", "today"),
            ("2026-01-05", "today"),            # 中间的打卡也合法
        ]), args())
        self.assertEqual(led.as_of, date(2026, 1, 10))
        self.assertEqual(led.current.span_days, 10)
        self.assertEqual(len(led.events), 3)

    def test_today_only_ledger_has_no_attempts(self):
        led = ht.Ledger(write_ledger([("2026-01-01", "today")]), args())
        self.assertEqual(led.attempts, [])
        self.assertEqual(led.span, 1)


# ---------------------------------------------------------------- as-of 裁剪

class TestAsOf(unittest.TestCase):
    def test_asof_before_relapse_attempt_still_alive(self):
        led = ht.Ledger(SAMPLE, args(price=25, as_of="2026-05-10"))
        a = led.current
        self.assertTrue(a.alive)
        self.assertIsNone(a.relapse_start)
        self.assertEqual(a.span_days, 70)      # 03-02..05-10
        self.assertEqual(a.clean_days, 68)     # 扣掉 04-11/04-12
        self.assertEqual(a.saved_cigs, 15 * 70 - 5)

    def test_asof_mid_attempt2(self):
        led = ht.Ledger(SAMPLE, args(price=25, as_of="2026-07-29"))
        a = led.current
        self.assertEqual(a.span_days, 42)
        self.assertEqual(a.clean_days, 42)
        self.assertEqual(a.saved_cigs, 630)
        tot = sum(x.saved_cigs for x in led.attempts)
        self.assertEqual(tot, 1180 + 630)

    def test_asof_cuts_future_rows_without_error(self):
        rc, out, _ = run_cli("report", SAMPLE, "--as-of", "2026-04-30")
        self.assertEqual(rc, 0)
        self.assertIn("2026-04-30", out)

    def test_bad_asof_is_ledger_error(self):
        rc, _, err = run_cli("report", SAMPLE, "--as-of", "2026-02-30")
        self.assertEqual(rc, 2)


# ---------------------------------------------------------------- CLI: report

class TestCLIReport(unittest.TestCase):
    def test_ground_truths_in_output(self):
        rc, out, _ = run_cli("report", SAMPLE, "--price", "25")
        self.assertEqual(rc, 0)
        for s in ("457 天", "第 75 天", "连续纯无烟 27 天",
                  "1,122 根", "¥1,402.50", "2,302 根", "¥2,877.50",
                  "累计纯无烟 150 天", "最长纯无烟 42 天",
                  "活了 79 天", "38 天", "5,460.4 根/年", "¥6,825.50",
                  "26 天", "灯：绿"):
            self.assertIn(s, out)

    def test_report_prints_basename_only(self):
        rc, out, _ = run_cli("report", SAMPLE)
        self.assertEqual(rc, 0)
        self.assertIn("smoking.tsv", out)
        self.assertNotIn(ROOT, out)

    def test_no_price_no_yen(self):
        rc, out, _ = run_cli("report", SAMPLE)
        self.assertEqual(rc, 0)
        self.assertIn("2,302 根", out)
        self.assertNotIn("¥", out)
        self.assertIn("钱是翻译不是前提", out)

    def test_no_quit_is_thin_with_arithmetic(self):
        path = write_ledger([("2026-01-01", "smoke", 12),
                             ("2026-01-20", "smoke", 14)])
        rc, out, _ = run_cli("report", path)
        self.assertEqual(rc, 3)
        self.assertIn("这不是一本戒烟账本", out)
        self.assertIn("26 根", out)  # 算术照出

    def test_missing_baseline_is_thin(self):
        path = write_ledger([("2026-01-10", "quit"), ("2026-01-25", "today")])
        rc, out, _ = run_cli("report", path)
        self.assertEqual(rc, 3)
        self.assertIn("无基线", out)

    def test_stalled_is_red(self):
        path = write_ledger([
            ("2026-01-01", "quit", None, 15),
            ("2026-02-10", "smoke", 15), ("2026-02-11", "smoke", 15),
            ("2026-02-12", "smoke", 15),
            ("2026-02-20", "today"),
        ])
        rc, out, _ = run_cli("report", path)
        self.assertEqual(rc, 4)
        self.assertIn("STALLED", out)
        self.assertIn("重新戒不丢人", out)

    def test_stalled_with_checkin_still_red(self):
        path = write_ledger([
            ("2026-01-01", "quit", None, 15),
            ("2026-01-20", "smoke", 15), ("2026-01-21", "smoke", 15),
            ("2026-01-22", "smoke", 15),
            ("2026-02-05", "today"),
        ])
        rc, out, _ = run_cli("report", path)
        self.assertEqual(rc, 4)

    def test_ledger_error_exit_2(self):
        path = write_ledger([("2026-01-01", "vape", 1)])
        rc, _, err = run_cli("report", path)
        self.assertEqual(rc, 2)
        self.assertIn("LEDGER ERROR", err)


# ---------------------------------------------------------------- CLI: clock

class TestCLIClock(unittest.TestCase):
    def test_milestones_reached_and_countdown(self):
        rc, out, _ = run_cli("clock", SAMPLE)
        self.assertEqual(rc, 0)
        self.assertIn("已走 75 天", out)
        self.assertIn("下一站 3 个月：肺功能显著改善，还差 15 天", out)
        self.assertIn("1 年：冠心病风险减半", out)
        self.assertIn("累计纯无烟 150 天", out)
        self.assertEqual(out.count("✓"), 5)  # 点火/20分钟/12小时/2周/1个月

    def test_clock_red_when_stalled(self):
        path = write_ledger([
            ("2026-01-01", "quit", None, 15),
            ("2026-01-20", "smoke", 15), ("2026-01-21", "smoke", 15),
            ("2026-01-22", "smoke", 15),
        ])
        rc, out, _ = run_cli("clock", path)
        self.assertEqual(rc, 4)

    def test_clock_thin_without_quit(self):
        path = write_ledger([("2026-01-01", "smoke", 5)])
        rc, out, _ = run_cli("clock", path)
        self.assertEqual(rc, 3)

    def test_dead_attempt_clock_stops_before_relapse(self):
        path = write_ledger([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-10", "smoke", 10), ("2026-01-11", "smoke", 10),
            ("2026-01-12", "smoke", 10),
            ("2026-01-30", "today"),
        ])
        rc, out, _ = run_cli("clock", path)
        self.assertEqual(rc, 4)
        self.assertIn("已走 9 天", out)  # 01-01..01-09，复发前夜停车


# ---------------------------------------------------------------- CLI: relapse

class TestCLIRelapse(unittest.TestCase):
    def test_single_transition_declines_mean(self):
        rc, out, _ = run_cli("relapse", SAMPLE, "--price", "25")
        self.assertEqual(rc, 3)
        self.assertIn("79 天", out)
        self.assertIn("5 根之后 38 天弹回", out)
        self.assertIn("仅 1 个样本", out)

    def test_two_transitions_give_mean_and_price(self):
        path = write_ledger([
            ("2026-01-01", "quit", None, 10),
            ("2026-01-20", "smoke", 2),
            ("2026-02-01", "smoke", 10), ("2026-02-02", "smoke", 10),
            ("2026-02-03", "smoke", 10),
            ("2026-02-20", "quit", None, 10),
            ("2026-03-01", "smoke", 1),
            ("2026-03-15", "smoke", 9), ("2026-03-16", "smoke", 10),
            ("2026-03-17", "smoke", 11),
            ("2026-04-01", "quit", None, 10),
            ("2026-04-30", "today"),
        ])
        rc, out, _ = run_cli("relapse", path, "--price", "20")
        self.assertEqual(rc, 0)
        self.assertIn("平均 13.0 天弹回", out)
        self.assertIn("¥", out)

    def test_no_relapse_message(self):
        path = write_ledger([("2026-01-01", "quit", None, 10),
                             ("2026-01-30", "today")])
        rc, out, _ = run_cli("relapse", path)
        self.assertEqual(rc, 0)
        self.assertIn("尚无 relapse", out)


# ---------------------------------------------------------------- CLI: trigger

class TestCLITrigger(unittest.TestCase):
    def test_distribution_ground_truth(self):
        rc, out, _ = run_cli("trigger", SAMPLE)
        self.assertEqual(rc, 0)
        self.assertIn("7 天、共 53 根", out)
        self.assertIn("加班：3 天 32 根", out)
        self.assertIn("酒局：2 天 5 根", out)
        self.assertIn("（未标）：2 天 16 根", out)
        self.assertIn("2026-05-20：加班", out)

    def test_zero_in_attempt_smoke_days(self):
        path = write_ledger([("2025-12-01", "smoke", 10),
                             ("2026-01-01", "quit", None, 10),
                             ("2026-01-15", "today")])
        rc, out, _ = run_cli("trigger", path)
        self.assertEqual(rc, 0)
        self.assertIn("零吸烟日", out)


# ---------------------------------------------------------------- CLI: simulate

class TestCLISimulate(unittest.TestCase):
    def test_smoke_one_never_resets_attempt(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "smoke", "1", "--price", "25")
        self.assertEqual(rc, 0)
        self.assertIn("第 75 天不清盘", out)
        self.assertIn("27 天 → 归零重计", out)
        self.assertIn("¥1.25", out)
        self.assertIn("样本 1 个", out)

    def test_continue_30_days(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "continue",
                             "--days", "30", "--price", "25")
        self.assertEqual(rc, 0)
        self.assertIn("450 根", out)
        self.assertIn("¥562.50", out)
        self.assertIn("重新出发的成本是零", out)

    def test_quit_calendar(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "quit", "2026-09-01",
                             "--price", "25")
        self.assertEqual(rc, 0)
        self.assertIn("2027-09-01", out)   # 1 年里程碑日历
        self.assertIn("5,475 根", out)
        self.assertIn("决定永远是人的", out)

    def test_simulate_never_enforces(self):
        for extra in (["smoke", "3"], ["continue"], ["quit"]):
            rc, _, _ = run_cli("simulate", SAMPLE, *extra)
            self.assertEqual(rc, 0)

    def test_simulate_declines_without_baseline(self):
        path = write_ledger([("2026-01-01", "smoke", 10),
                             ("2026-01-05", "smoke", 12)])
        rc, out, _ = run_cli("simulate", path, "smoke", "1")
        self.assertEqual(rc, 3)
        self.assertIn("不发明", out)


# ---------------------------------------------------------------- CLI: validate

class TestCLIValidate(unittest.TestCase):
    def test_sample_passes(self):
        rc, out, _ = run_cli("validate", SAMPLE)
        self.assertEqual(rc, 0)
        self.assertIn("体检通过", out)
        self.assertIn("三桶恒等", out)
        self.assertIn("双算法", out)

    def test_validate_passes_on_stalled_ledger(self):
        path = write_ledger([
            ("2026-01-01", "quit", None, 15),
            ("2026-01-20", "smoke", 15), ("2026-01-21", "smoke", 15),
            ("2026-01-22", "smoke", 15),
            ("2026-02-05", "today"),
        ])
        rc, out, _ = run_cli("validate", path)
        self.assertEqual(rc, 0)  # 体检是算术：账本坏与账本红是两回事
        self.assertIn("体检通过", out)

    def test_validate_exit_2_on_broken_ledger(self):
        path = write_ledger([("2026-01-01", "quit", 5, None)])
        rc, _, _ = run_cli("validate", path)
        self.assertEqual(rc, 2)

    def test_validate_asof_pin(self):
        rc, out, _ = run_cli("validate", SAMPLE, "--as-of", "2026-07-29")
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------- 里程碑

class TestMilestones(unittest.TestCase):
    def test_custom_milestone_sorted_in(self):
        rc, out, _ = run_cli(
            "clock", SAMPLE,
            "--milestone", "60:六十大关", "--milestone", "7:第七天")
        self.assertEqual(rc, 0)
        i7 = out.index("第七天")
        i60 = out.index("六一大关" if False else "六十大关")
        i90 = out.index("3 个月")
        self.assertLess(i7, i60)
        self.assertLess(i60, i90)
        self.assertIn("✓ 六十大关", out)    # 60 ≤ 75 已到达

    def test_no_default_milestones(self):
        rc, out, _ = run_cli(
            "clock", SAMPLE, "--no-default-milestones",
            "--milestone", "100:百日")
        self.assertEqual(rc, 0)
        self.assertNotIn("冠心病", out)
        self.assertIn("百日，还差 25 天", out)

    def test_bad_milestone_spec_is_error(self):
        rc, _, _ = run_cli("clock", SAMPLE, "--milestone", "abc:nope")
        self.assertEqual(rc, 2)

    def test_default_table_sorted_strictly(self):
        ms = ht.DEFAULT_MILESTONES
        self.assertTrue(all(ms[i][0] < ms[i + 1][0]
                            for i in range(len(ms) - 1)))


# ---------------------------------------------------------------- 口径与输出

class TestConventions(unittest.TestCase):
    def test_exit_code_constants(self):
        self.assertEqual(ht.EXIT_OK, 0)
        self.assertEqual(ht.EXIT_LEDGER, 2)
        self.assertEqual(ht.EXIT_THIN, 3)
        self.assertEqual(ht.EXIT_RED, 4)

    def test_no_wall_clock_in_module(self):
        with open(os.path.join(ROOT, "hidden_tab.py"),
                  encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("date.today", src)
        self.assertNotIn("datetime.now", src)
        self.assertNotIn("time.time", src)

    def test_time_account_formatting(self):
        self.assertEqual(ht.time_str(2302, 5),
                         "11,510 分钟 ＝ 191.8 小时 ＝ 8.0 天")
        self.assertEqual(ht.time_str(1, 5),
                         "5 分钟 ＝ 0.1 小时 ＝ 0.0 天")

    def test_byte_reproducible_across_runs(self):
        outs = set()
        for _ in range(3):
            rc, out, _ = run_cli("report", SAMPLE, "--price", "25")
            self.assertEqual(rc, 0)
            outs.add(out)
        self.assertEqual(len(outs), 1)


if __name__ == "__main__":
    unittest.main()
