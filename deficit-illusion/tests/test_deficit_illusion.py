# -*- coding: utf-8 -*-
"""赤字幻觉 · Deficit Illusion —— 验收标准全部转成自动化测试。"""

import datetime
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "deficit_illusion.py")
SAMPLE = os.path.join(ROOT, "examples", "ledger.tsv")

sys.path.insert(0, ROOT)
import deficit_illusion as di  # noqa: E402

D0 = datetime.date(2026, 6, 8)


def write_ledger(rows, header=True):
    """rows: [(date, kg|None, kcal|None, note|None)] -> temp tsv path"""
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        if header:
            f.write("date\tkg\tkcal\tnote\n")
        for r in rows:
            d, kg, kcal = r[0], r[1], r[2]
            note = r[3] if len(r) > 3 else ""
            f.write("%s\t%s\t%s\t%s\n" % (
                d, "" if kg is None else kg,
                "" if kcal is None else kcal, note or ""))
    return path


def synth_days(n, start_kg, true_intake, tdee, reported_intake,
               first=D0, spike_at=None, spike_amt=0.0):
    """合成账本：无噪声，能量账精确已知。
    每日脂肪变化 = (true_intake - tdee)/7700 kg。"""
    rows = []
    kg = start_kg
    daily = (true_intake - tdee) / 7700.0
    for i in range(n):
        if spike_at is not None and i == spike_at:
            kg += spike_amt
        rows.append((str(first + datetime.timedelta(days=i)),
                     round(kg, 6), str(reported_intake)))
        kg += daily
    return rows


def run_cli(*argv):
    p = subprocess.run(
        [sys.executable, CLI] + list(argv),
        capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class ParseTests(unittest.TestCase):
    def test_load_sample(self):
        days = di.load_ledger(SAMPLE)
        self.assertEqual(len(days), 56)
        self.assertEqual(days[0].date, D0)
        self.assertEqual(days[0].kg, 68.0)
        self.assertEqual(days[-1].date, datetime.date(2026, 8, 2))

    def test_blank_cells_allowed(self):
        path = write_ledger([("2026-06-08", 68.0, None, "没记吃"),
                             ("2026-06-09", None, 1500, "没上秤")])
        days = di.load_ledger(path)
        self.assertIsNone(days[0].kcal)
        self.assertIsNone(days[1].kg)
        os.unlink(path)

    def test_bad_date(self):
        path = write_ledger([("2026/06/08", 68.0, 1500)])
        with self.assertRaises(di.LedgerError):
            di.load_ledger(path)
        os.unlink(path)

    def test_duplicate_date(self):
        path = write_ledger([("2026-06-08", 68.0, 1500),
                             ("2026-06-08", 67.9, 1480)])
        with self.assertRaises(di.LedgerError):
            di.load_ledger(path)
        os.unlink(path)

    def test_bad_header(self):
        path = write_ledger([("2026-06-08", 68.0, 1500)], header=False)
        with self.assertRaises(di.LedgerError):
            di.load_ledger(path)
        os.unlink(path)

    def test_kg_out_of_range(self):
        path = write_ledger([("2026-06-08", 500.0, 1500)])
        with self.assertRaises(di.LedgerError):
            di.load_ledger(path)
        os.unlink(path)

    def test_kcal_out_of_range(self):
        path = write_ledger([("2026-06-08", 68.0, -5)])
        with self.assertRaises(di.LedgerError):
            di.load_ledger(path)
        os.unlink(path)

    def test_missing_columns(self):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w") as f:
            f.write("date\tkg\tkcal\tnote\n2026-06-08\t68.0\n")
        with self.assertRaises(di.LedgerError):
            di.load_ledger(path)
        os.unlink(path)

    def test_as_of_before_first_row(self):
        path = write_ledger([("2026-06-08", 68.0, 1500)])
        days = di.load_ledger(path)
        with self.assertRaises(di.LedgerError):
            di.apply_as_of(days, datetime.date(2026, 1, 1))
        os.unlink(path)


class FactsTests(unittest.TestCase):
    def test_moving_avg_exact(self):
        # 前 7 天都是 68.0 → 首窗均重 68.0
        rows = [(str(D0 + datetime.timedelta(days=i)), 68.0, 1500)
                for i in range(7)]
        path = write_ledger(rows)
        f = di.Facts(di.load_ledger(path), 7700)
        self.assertAlmostEqual(f.mw_at(6), 68.0, places=9)
        os.unlink(path)

    def test_moving_avg_needs_5_readings(self):
        # 7 天窗里只有 4 天有读数 → mw None
        rows = []
        for i in range(7):
            kg = 68.0 if i < 4 else None
            rows.append((str(D0 + datetime.timedelta(days=i)), kg, 1500))
        path = write_ledger(rows)
        f = di.Facts(di.load_ledger(path), 7700)
        self.assertIsNone(f.mw_at(6))
        os.unlink(path)

    def test_apparent_tdee_recovers_true_tdee(self):
        # 自报=真实=1800，TDEE=2000 → 28 天亏 200/天，apparent==2000
        # （窗口对齐口径：ΔW 是 21 个中心天，分母同窗）
        rows = synth_days(28, 68.0, 1800, 2000, 1800)
        path = write_ledger(rows)
        f = di.Facts(di.load_ledger(path), 7700)
        self.assertAlmostEqual(f.dw(), -200 * 21 / 7700.0, places=4)
        self.assertAlmostEqual(f.apparent_tdee(), 2000.0, places=3)
        os.unlink(path)

    def test_mifflin_st_jeor(self):
        rows = synth_days(28, 68.0, 1800, 2000, 1800)
        path = write_ledger(rows)
        f = di.Facts(di.load_ledger(path), 7700)
        import argparse
        a = argparse.Namespace(tdee=None, sex="f", age=30, height=168,
                               activity=1.5)
        prior, why = f.prior_tdee(a)
        # BMR = 10*W + 6.25*168 - 5*30 - 161，W = 账本首 7 天均重
        bmr = 10.0 * f.first_week_weight() + 6.25 * 168 - 5.0 * 30 - 161.0
        self.assertAlmostEqual(prior, bmr * 1.5, places=6)
        self.assertIn("Mifflin", why)
        os.unlink(path)

    def test_explicit_tdee_wins(self):
        rows = synth_days(28, 68.0, 1800, 2000, 1800)
        path = write_ledger(rows)
        f = di.Facts(di.load_ledger(path), 7700)
        import argparse
        a = argparse.Namespace(tdee=2100.0, sex="f", age=30, height=168,
                               activity=1.5)
        prior, why = f.prior_tdee(a)
        self.assertEqual(prior, 2100.0)
        self.assertIn("--tdee", why)
        os.unlink(path)

    def test_gap_identity(self):
        # 恒等式：漏记 = 先验 − 表观 = 真实摄入 − 自报摄入
        rows = synth_days(28, 68.0, true_intake=1900, tdee=2000,
                          reported_intake=1400)
        path = write_ledger(rows)
        f = di.Facts(di.load_ledger(path), 7700)
        apparent = f.apparent_tdee()
        prior = 2000.0
        gap = prior - apparent
        i_true = prior + 7700 * f.dw() / 21.0
        self.assertAlmostEqual(gap, 1900 - 1400, places=3)
        self.assertAlmostEqual(i_true, 1900.0, places=3)
        self.assertAlmostEqual(i_true / 1400.0, 1900.0 / 1400.0, places=3)
        os.unlink(path)

    def test_spike_detection_and_threshold(self):
        # 日基线每天 -0.026，环比 = spike_amt + daily：恰 0.8 与恰不达
        daily = (1800.0 - 2000.0) / 7700.0
        rows = synth_days(10, 68.0, 1800, 2000, 1800, spike_at=5,
                          spike_amt=0.8 - daily)
        f = di.Facts(di.load_ledger(write_ledger(rows)), 7700)
        self.assertEqual(len(f.spikes), 1)
        self.assertAlmostEqual(f.spikes[0][1], 0.8, places=9)
        rows2 = synth_days(10, 68.0, 1800, 2000, 1800, spike_at=5,
                           spike_amt=0.8 - daily - 0.01)
        f2 = di.Facts(di.load_ledger(write_ledger(rows2)), 7700)
        self.assertEqual(len(f2.spikes), 0)

    def test_spike_shadow_directional(self):
        # 涨 spike：豁免 [s-1, s+14]；跌 spike：只豁 [s, s+6]
        rows = synth_days(30, 68.0, 1800, 2000, 1800, spike_at=5,
                          spike_amt=1.2)
        f = di.Facts(di.load_ledger(write_ledger(rows)), 7700)
        s = D0 + datetime.timedelta(days=5)
        self.assertIsNotNone(f.spike_shadow(s - datetime.timedelta(days=1)))
        self.assertIsNotNone(f.spike_shadow(s + datetime.timedelta(days=14)))
        self.assertIsNone(f.spike_shadow(s + datetime.timedelta(days=15)))
        rows2 = synth_days(30, 68.0, 1800, 2000, 1800, spike_at=5,
                           spike_amt=-1.2)
        f2 = di.Facts(di.load_ledger(write_ledger(rows2)), 7700)
        self.assertIsNone(f2.spike_shadow(s - datetime.timedelta(days=1)))
        self.assertIsNotNone(f2.spike_shadow(s))
        self.assertIsNotNone(f2.spike_shadow(s + datetime.timedelta(days=6)))
        self.assertIsNone(f2.spike_shadow(s + datetime.timedelta(days=7)))

    def test_week_table_thin_week(self):
        rows = [(str(D0 + datetime.timedelta(days=i)),
                 68.0 if i % 2 == 0 else None, 1500)
                for i in range(10)]
        f = di.Facts(di.load_ledger(write_ledger(rows)), 7700)
        wtab = f.week_table()
        self.assertEqual(len(wtab), 2)
        self.assertIsNone(wtab[1][3])  # 第二周 4 读数 < 5 → None

    def test_thin_ledger_flag(self):
        rows = synth_days(15, 68.0, 1800, 2000, 1800)
        f = di.Facts(di.load_ledger(write_ledger(rows)), 7700)
        self.assertTrue(f.thin())  # 跨度 15 < 21
        rows2 = synth_days(28, 68.0, 1800, 2000, 1800)
        f2 = di.Facts(di.load_ledger(write_ledger(rows2)), 7700)
        self.assertFalse(f2.thin())


class SampleLedgerTests(unittest.TestCase):
    """样例账本的叙事数字：样例生成时构造的真实世界必须被工具复原。"""

    @classmethod
    def setUpClass(cls):
        cls.days = di.load_ledger(SAMPLE)
        cls.f = di.Facts(cls.days, 7700)

    def test_span_and_coverage(self):
        self.assertEqual(self.f.span, 56)
        self.assertAlmostEqual(self.f.kg_cov, 1.0)
        self.assertAlmostEqual(self.f.kcal_cov, 1.0)

    def test_dw_matches_true_fat_change(self):
        # 构造的真实脂肪变化 ≈ -1.73 kg；均重口径必须复原它
        self.assertAlmostEqual(self.f.dw(), -1.729, places=2)

    def test_apparent_tdee(self):
        self.assertAlmostEqual(self.f.apparent_tdee(), 1658.1, places=1)

    def test_gap_coefficient(self):
        prior = 1419.0 * 1.5
        apparent = self.f.apparent_tdee()
        i_true = prior + 7700 * self.f.dw() / 49.0
        coef = i_true / self.f.rep_avg_win()
        self.assertAlmostEqual(prior - apparent, 470.4, places=1)
        self.assertAlmostEqual(coef, 1.339, places=3)

    def test_spikes(self):
        got = [(d, round(delta, 1)) for d, delta in self.f.spikes]
        self.assertIn((datetime.date(2026, 6, 15), 1.0), got)
        self.assertIn((datetime.date(2026, 7, 31), -0.9), got)
        self.assertEqual(len(got), 2)

    def test_worst_unconfounded_diff(self):
        clean = [(e, d) for e, d, c in self.f.diffs if not c]
        worst = min(clean, key=lambda t: t[1])
        self.assertEqual(worst[0], datetime.date(2026, 7, 29))
        self.assertAlmostEqual(worst[1], -0.70, places=2)

    def test_spike_shadow_does_not_hide_true_surge(self):
        # 火锅退潮段必须被豁免，真超速段必须不豁免
        conf = [e for e, d, c in self.f.diffs if c]
        self.assertIn(datetime.date(2026, 6, 25), conf)
        self.assertNotIn(datetime.date(2026, 7, 29), conf)

    def test_validate_ok(self):
        rc, out, _ = run_cli("validate", SAMPLE)
        self.assertEqual(rc, 0)
        self.assertIn("ledger OK", out)

    def test_trend_exit0_and_phantom_lines(self):
        rc, out, _ = run_cli("trend", SAMPLE)
        self.assertEqual(rc, 0)
        self.assertIn("2026-06-15", out)
        self.assertIn("脂肪在数学上不可能", out)
        self.assertIn("spike week", out)

    def test_reconcile_red(self):
        rc, out, _ = run_cli("reconcile", SAMPLE, "--sex", "f",
                             "--age", "30", "--height", "168",
                             "--activity", "1.5")
        self.assertEqual(rc, 4)
        self.assertIn("RECORD GAP", out)
        self.assertIn("1.339", out)
        self.assertIn("账面赤字", out)
        self.assertIn("4.72", out)

    def test_reconcile_without_prior_declined(self):
        rc, out, _ = run_cli("reconcile", SAMPLE)
        self.assertEqual(rc, 0)
        self.assertIn("declined", out)
        self.assertIn("--tdee", out)

    def test_rate_red(self):
        rc, out, _ = run_cli("rate", SAMPLE)
        self.assertEqual(rc, 4)
        self.assertIn("MUSCLE RISK", out)
        self.assertIn("2026-07-29", out)
        self.assertIn("spike shadow 豁免", out)

    def test_plateau_green_full_ledger(self):
        rc, out, _ = run_cli("plateau", SAMPLE)
        self.assertEqual(rc, 0)
        self.assertIn("PASSED", out)
        self.assertIn("当前不在平台期", out)

    def test_plateau_active_red_with_as_of(self):
        rc, out, _ = run_cli("plateau", SAMPLE, "--as-of", "2026-07-19")
        self.assertEqual(rc, 4)
        self.assertIn("ACTIVE", out)
        self.assertIn("你正在平台期上", out)

    def test_report_lamp_summary(self):
        rc, out, _ = run_cli("report", SAMPLE, "--sex", "f", "--age", "30",
                             "--height", "168", "--activity", "1.5",
                             "--goal", "62")
        self.assertEqual(rc, 4)
        self.assertIn("LAMP RECORD GAP", out)
        self.assertIn("LAMP MUSCLE RISK", out)
        self.assertEqual(out.count("LAMP PHANTOM"), 2)
        self.assertIn("48 天", out)

    def test_simulate_continue(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "continue", "--goal", "62")
        self.assertEqual(rc, 0)
        self.assertIn("2026-09-19", out)
        self.assertIn("-0.62", out)

    def test_simulate_intake_needs_prior(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "intake", "1600")
        self.assertEqual(rc, 3)
        self.assertIn("declined", out)

    def test_simulate_intake(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "intake", "1600",
                             "--sex", "f", "--age", "30", "--height", "168",
                             "--activity", "1.5", "--goal", "62")
        self.assertEqual(rc, 0)
        self.assertIn("-0.48", out)
        self.assertIn("2026-10-04", out)
        self.assertIn("如实", out)

    def test_basename_only_in_output(self):
        rc, out, _ = run_cli("report", SAMPLE, "--sex", "f", "--age", "30",
                             "--height", "168")
        self.assertNotIn(ROOT, out)
        self.assertIn("ledger.tsv", out)

    def test_byte_identical_rerun(self):
        rc1, out1, _ = run_cli("report", SAMPLE, "--sex", "f", "--age", "30",
                               "--height", "168")
        rc2, out2, _ = run_cli("report", SAMPLE, "--sex", "f", "--age", "30",
                               "--height", "168")
        self.assertEqual((rc1, out1), (rc2, out2))

    def test_as_of_truncates(self):
        rc, out, _ = run_cli("report", SAMPLE, "--as-of", "2026-06-10",
                             "--sex", "f", "--age", "30", "--height", "168")
        self.assertEqual(rc, 3)  # 3 天 → thin
        self.assertIn("3 days", out)

    def test_as_of_boundary_day_included(self):
        rc, out, _ = run_cli("validate", SAMPLE, "--as-of", "2026-06-08")
        self.assertEqual(rc, 0)
        self.assertIn("span: 2026-06-08 .. 2026-06-08 (1 days)", out)


class ReconcileGradesTests(unittest.TestCase):
    """判级阶梯：HONEST < 1.10 ≤ WATCH < 1.25 ≤ RECORD GAP。"""

    def run_rec(self, rows, extra=()):
        path = write_ledger(rows)
        argv = ["reconcile", path, "--tdee", "2000"] + list(extra)
        rc, out, _ = run_cli(*argv)
        os.unlink(path)
        return rc, out

    def test_honest(self):
        # 自报=真实=1850，亏 150/天 → 系数 2000/1850 = 1.081
        rows = synth_days(28, 68.0, 1850, 2000, 1850)
        rc, out = self.run_rec(rows)
        self.assertEqual(rc, 0)
        self.assertIn("HONEST", out)

    def test_watch(self):
        # 自报 1600 真实 1850 → 系数 1850/1600 = 1.156
        rows = synth_days(28, 68.0, 1850, 2000, 1600)
        rc, out = self.run_rec(rows)
        self.assertEqual(rc, 0)
        self.assertIn("WATCH", out)

    def test_record_gap(self):
        rows = synth_days(28, 68.0, 1900, 2000, 1400)
        rc, out = self.run_rec(rows)
        self.assertEqual(rc, 4)
        self.assertIn("RECORD GAP", out)

    def test_watch_watch_gap_boundary(self):
        # 系数恰在 1.25 附近：自报 1600、真实 2000、TDEE 2100（亏 100/天）
        # apparent = 1600+100 = 1700；i_true = 2100-100 = 2000；coef 1.25
        rows = synth_days(28, 68.0, 2000, 2100, 1600)
        path = write_ledger(rows)
        rc, out, _ = run_cli("reconcile", path, "--tdee", "2100")
        os.unlink(path)
        self.assertIn("1.25", out)
        if rc == 4:
            self.assertIn("RECORD GAP", out)
        else:
            self.assertEqual(rc, 0)
            self.assertIn("WATCH", out)

    def test_low_coverage_declined(self):
        rows = synth_days(28, 68.0, 1850, 2000, 1850)
        rows = [(d, kg, kcal if i >= 15 else None)
                for i, (d, kg, kcal) in enumerate(rows)]  # 13/28 < 50%
        path = write_ledger(rows)
        rc, out, _ = run_cli("reconcile", path, "--tdee", "2000")
        os.unlink(path)
        self.assertEqual(rc, 3)
        self.assertIn("覆盖率", out)

    def test_thin_declined(self):
        rows = synth_days(15, 68.0, 1850, 2000, 1850)
        path = write_ledger(rows)
        rc, out, _ = run_cli("reconcile", path, "--tdee", "2000")
        os.unlink(path)
        self.assertEqual(rc, 3)


class RateAndPlateauSynthTests(unittest.TestCase):
    def test_rate_green_slow_steady(self):
        # -150/天 = -0.136 kg/周，远低于 1% 线
        rows = synth_days(35, 68.0, 1850, 2000, 1850)
        path = write_ledger(rows)
        rc, out, _ = run_cli("rate", path)
        os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("线内", out)

    def test_rate_red_fast_cut(self):
        # -800/天 = -0.727 kg/周 ≈ 1.07% → 超 1% 线
        rows = synth_days(35, 68.0, 1200, 2000, 1200)
        path = write_ledger(rows)
        rc, out, _ = run_cli("rate", path)
        os.unlink(path)
        self.assertEqual(rc, 4)
        self.assertIn("MUSCLE RISK", out)

    def test_rate_thin(self):
        rows = synth_days(18, 68.0, 1850, 2000, 1850)
        path = write_ledger(rows)
        rc, out, _ = run_cli("rate", path)
        os.unlink(path)
        self.assertEqual(rc, 3)

    def test_plateau_detects_flat_run(self):
        # 前 20 天缓慢掉，末端完全平坦 → ACTIVE 平台段 + ROT 裁决 = 红灯
        rows = []
        kg = 68.0
        for i in range(34):
            if i >= 20:
                pass  # 平坦
            else:
                kg -= 150 / 7700.0
            rows.append((str(D0 + datetime.timedelta(days=i)),
                         round(kg, 3), 1850))
        path = write_ledger(rows)
        rc, out, _ = run_cli("plateau", path)
        os.unlink(path)
        self.assertEqual(rc, 4)
        self.assertIn("平台段", out)
        self.assertIn("ACTIVE", out)

    def test_plateau_behavior_verdict(self):
        # 平台段 + 段内自报比段前高 ≥100 → BEHAVIOR（吃回来了）
        rows = []
        kg = 68.0
        for i in range(40):
            if i >= 26:
                pass  # 平台
            else:
                kg -= 150 / 7700.0
            kcal = 1850 if i < 26 else 2100
            rows.append((str(D0 + datetime.timedelta(days=i)),
                         round(kg, 3), kcal))
        path = write_ledger(rows)
        rc, out, _ = run_cli("plateau", path)
        os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("BEHAVIOR", out)

    def test_plateau_thin(self):
        rows = synth_days(18, 68.0, 1850, 2000, 1850)
        path = write_ledger(rows)
        rc, out, _ = run_cli("plateau", path)
        os.unlink(path)
        self.assertEqual(rc, 3)

    def test_simulate_thin(self):
        rows = synth_days(15, 68.0, 1850, 2000, 1850)
        path = write_ledger(rows)
        rc, out, _ = run_cli("simulate", path, "continue")
        os.unlink(path)
        self.assertEqual(rc, 3)


class CliBehaviorTests(unittest.TestCase):
    def test_exit2_on_broken_ledger(self):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w") as f:
            f.write("date\tkg\tkcal\tnote\n2026-06-08\t68.0\tabc\n")
        rc, _, err = run_cli("validate", path)
        os.unlink(path)
        self.assertEqual(rc, 2)
        self.assertIn("ledger error", err)

    def test_simulate_needs_subcommand(self):
        rc, out, _ = run_cli("simulate", SAMPLE)
        self.assertEqual(rc, 2)

    def test_report_green_without_lamps(self):
        # 诚实慢速账本：HONEST 灯但无红灯 → exit 0
        rows = synth_days(35, 68.0, 1850, 2000, 1850)
        path = write_ledger(rows)
        rc, out, _ = run_cli("report", path, "--tdee", "2000")
        os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("HONEST", out)
        self.assertNotIn("RECORD GAP", out)
        self.assertNotIn("MUSCLE RISK", out)


if __name__ == "__main__":
    unittest.main()
