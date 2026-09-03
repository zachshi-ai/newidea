#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mood-barometer 验收测试.

每条验收标准都落在这里：日度口径（日内取均值）、中位数基线、星期节律的
样本下限、事件账单的成本与 THIN、回弹/滞留判定、气候漂移、双信号门禁、
以及全部 exit code（0 / 2 / 3 / 4）。
"""

import datetime as dt
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mood_barometer as mb  # noqa: E402

TODAY = dt.date(2026, 9, 4)
CLI = os.path.join(ROOT, "mood_barometer.py")


def d(n: int) -> dt.date:
    return TODAY - dt.timedelta(days=n)


def ent(date, mood, events=""):
    if isinstance(date, str):
        date = dt.date.fromisoformat(date)
    return mb.Entry(date, None, mood, [e for e in events.split(",") if e], "", 1)


def series(*pairs):
    return {dt.date.fromisoformat(dd) if isinstance(dd, str) else dd: float(v)
            for dd, v in pairs}


def filled(start_days_ago, n, mood):
    """连续 n 天的常值序列。"""
    return {TODAY - dt.timedelta(days=start_days_ago + i): float(mood) for i in range(n)}


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

class ParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        p = os.path.join(self.dir, "moods.tsv")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_normal_rows_and_daily_mean(self):
        p = self.write("2026-09-01\t08:00\t2\t\t早\n"
                       "2026-09-01\t22:00\t4\t\t晚\n"
                       "2026-09-02\t\t3\t\t\n")
        entries = mb.load_moods(p, TODAY)
        s = mb.daily_series(entries)
        self.assertEqual(s[dt.date(2026, 9, 1)], 3.0)  # 日内两条取均值
        self.assertEqual(s[dt.date(2026, 9, 2)], 3.0)

    def test_events_split_and_blank(self):
        p = self.write("2026-09-01\t\t2\tconflict, deadline ,\tnote\n")
        entries = mb.load_moods(p, TODAY)
        self.assertEqual(entries[0].events, ["conflict", "deadline"])
        p2 = self.write("2026-09-01\t\t3\t\t\n")
        self.assertEqual(mb.load_moods(p2, TODAY)[0].events, [])

    def test_mood_out_of_range_rejected(self):
        for bad in ("0", "6", "3.5", "-1"):
            p = self.write(f"2026-09-01\t\t{bad}\t\t\n")
            with self.assertRaises(mb.UsageError):
                mb.load_moods(p, TODAY)

    def test_mood_non_numeric_rejected(self):
        p = self.write("2026-09-01\t\t还行\t\t\n")
        with self.assertRaises(mb.UsageError):
            mb.load_moods(p, TODAY)

    def test_bad_date_rejected(self):
        p = self.write("2026/09/01\t\t3\t\t\n")
        with self.assertRaises(mb.UsageError):
            mb.load_moods(p, TODAY)

    def test_future_entry_rejected(self):
        p = self.write("2026-09-10\t\t3\t\t\n")
        with self.assertRaises(mb.UsageError):
            mb.load_moods(p, TODAY)

    def test_bad_time_rejected(self):
        p = self.write("2026-09-01\t25:00\t3\t\t\n")
        with self.assertRaises(mb.UsageError):
            mb.load_moods(p, TODAY)

    def test_wrong_column_count_rejected(self):
        p = self.write("2026-09-01\t\t3\t\n")
        with self.assertRaises(mb.UsageError):
            mb.load_moods(p, TODAY)

    def test_comments_and_blank_skipped(self):
        p = self.write("# header\n\n2026-09-01\t\t3\t\t\n")
        self.assertEqual(len(mb.load_moods(p, TODAY)), 1)

    def test_empty_ledger_refused(self):
        p = self.write("# nothing\n")
        with self.assertRaises(mb.Refusal):
            mb.load_moods(p, TODAY)

    def test_missing_file(self):
        with self.assertRaises(mb.UsageError):
            mb.load_moods("/nonexistent.tsv", TODAY)


# ---------------------------------------------------------------------------
# 基线与节律
# ---------------------------------------------------------------------------

class BaselineTests(unittest.TestCase):
    def test_median_baseline_even_days(self):
        s = series(("2026-08-01", 2), ("2026-08-02", 4))
        self.assertEqual(mb.baseline_of(s), 3.0)

    def test_median_resists_outlier(self):
        # 10 天 3 分 + 1 天 1 分：中位数不动——单日崩溃绑架不了基线
        s = filled(0, 10, 3)
        s[d(15)] = 1.0
        self.assertEqual(mb.baseline_of(s), 3.0)


class WeekdayTests(unittest.TestCase):
    def test_monday_blues_detected(self):
        # 5 个周一全 2，5 个周二全 4，其他天 3 → 中位基线 3.0
        s = {}
        base = dt.date(2026, 6, 1)  # 周一
        for i in range(0, 70, 7):
            s[base + dt.timedelta(days=i)] = 2.0       # 周一
            s[base + dt.timedelta(days=i + 1)] = 4.0   # 周二
            for j in range(2, 7):
                s[base + dt.timedelta(days=i + j)] = 3.0
        base_line = mb.baseline_of(s)
        self.assertEqual(base_line, 3.0)
        offs = {wd: off for wd, off, _ in mb.weekday_offsets(s, base_line)}
        self.assertAlmostEqual(offs[0], -1.0)  # 周一显著低
        self.assertAlmostEqual(offs[1], +1.0)  # 周二显著高
        ranked = mb.weekday_offsets(s, base_line)
        self.assertEqual(ranked[0][0], 0)
        self.assertEqual(ranked[-1][0], 1)

    def test_thin_weekday_not_judged(self):
        s = filled(0, 10, 3)  # 全是同一批星期几，其余样本 <4
        base_line = mb.baseline_of(s)
        judged = mb.weekday_offsets(s, base_line)
        self.assertLessEqual(len(judged), 3)  # 10 天最多覆盖 2-3 个星期几


# ---------------------------------------------------------------------------
# 事件账单
# ---------------------------------------------------------------------------

class EventTests(unittest.TestCase):
    def _ledger(self):
        """60 天：基线 4；conflict 5 次、每次后 3 天低到 2；social 5 次、
        事件日避开 conflict 窗口；lonely 3 次（<5，不判）。"""
        entries = []
        start = TODAY - dt.timedelta(days=59)
        conflict_days = {5, 15, 25, 35, 45}
        social_days = {8, 18, 28, 38, 48}
        lonely_days = {9, 19, 29}
        for i in range(60):
            day = start + dt.timedelta(days=i)
            mood = 4
            tags = []
            if i in conflict_days or any((i - c) in (1, 2, 3) for c in conflict_days):
                mood = 2
                if i in conflict_days:
                    tags.append("conflict")
            if i in social_days:
                tags.append("social")
            if i in lonely_days:
                tags.append("lonely")
            entries.append(mb.Entry(day, None, mood, tags, "", 1))
        return entries

    def test_conflict_costs_most_and_lonely_thin(self):
        s = mb.daily_series(self._ledger())
        base_line = mb.baseline_of(s)
        costs = mb.event_costs(self._ledger(), s, base_line, TODAY)
        tags = {t: c for t, c, _ in costs}
        self.assertNotIn("lonely", tags)           # 3 次 < 5：THIN 不判
        self.assertLessEqual(tags["conflict"], -1.0)  # 冲突后窗口显著低于基线
        self.assertGreater(tags["social"], tags["conflict"])
        self.assertLess(costs[0][1], costs[-1][1])  # 按成本升序

    def test_events_command_thin_refusal(self):
        # <21 个记录日 → events 拒绝
        entries = [mb.Entry(TODAY - dt.timedelta(days=i), None, 3, [], "", 1)
                   for i in range(10)]
        with self.assertRaises(mb.Refusal):
            mb.report_events(entries, TODAY)


# ---------------------------------------------------------------------------
# 回弹与滞留
# ---------------------------------------------------------------------------

class ReboundTests(unittest.TestCase):
    def test_recovery_days_measured(self):
        s = filled(0, 40, 4)                     # 基线 4
        s[d(20)] = 2.0                           # 低点
        s[d(19)] = 2.5                           # 仍在低段（合并）
        s[d(18)] = 3.0                           # 仍在爬（< 基线−0.5）
        s[d(17)] = 4.0                           # 第 3 天回到基线
        history, pending = mb.rebound_history(s, 4.0, TODAY)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0][1], 3)        # d(20) → d(17) = 3 天
        self.assertIsNone(pending)

    def test_unrecovered_tail_is_pending(self):
        s = filled(0, 40, 4)
        for i in range(4):
            s[d(i)] = 2.0
        history, pending = mb.rebound_history(s, 4.0, TODAY)
        self.assertEqual(history[-1][1], None)
        self.assertIsNotNone(pending)
        self.assertEqual(pending[1], 3)           # d(3) 距今 3 天
        self.assertEqual(len(history), 1)         # 连续低点合并为一段

    def test_median_rebound(self):
        s = filled(0, 60, 4)
        # 三次低点：恢复期 2/2/4 天 → 中位 2
        for low_ago, n_low in ((50, 2), (40, 2), (30, 4)):
            for k in range(n_low):
                s[d(low_ago - k)] = 2.0
        history, _ = mb.rebound_history(s, 4.0, TODAY)
        self.assertEqual([r for _, r in history], [2, 2, 4])
        self.assertEqual(mb.rebound_median(history), 2.0)

    def test_no_lows_no_pending(self):
        s = filled(0, 30, 4)
        history, pending = mb.rebound_history(s, 4.0, TODAY)
        self.assertEqual(history, [])
        self.assertIsNone(pending)


# ---------------------------------------------------------------------------
# 气候漂移与门禁
# ---------------------------------------------------------------------------

class DriftTests(unittest.TestCase):
    def test_downward_drift_detected(self):
        s = {}
        s.update(filled(30, 30, 4.0))   # 前 30 天（30-59 天前）
        s.update(filled(0, 30, 3.0))    # 近 30 天
        recent, prev, delta = mb.climate_drift(s, TODAY)
        self.assertEqual((prev, recent), (4.0, 3.0))
        self.assertAlmostEqual(delta, -1.0)

    def test_insufficient_cover_refuses(self):
        s = filled(0, 10, 3.0)
        self.assertEqual(mb.climate_drift(s, TODAY), (None, None, None))


class GateTests(unittest.TestCase):
    """70 天整数 fixture，手工演算过：
    - d(69)..d(30) 全 4.0（40 天）→ 前窗中位 4.0
    - d(29)..d(12)：3 次低点各占 2 天（d24/d23, d20/d19, d16/d15 = 2.0），
      其余 12 天 4.0；近 30 天 = 18 天 2.0（含尾部 12 天）+ 12 天 4.0 → 中位 2.0
    - d(11)..d(0) 全 2.0 → 滞留段，so_far = 11 天
    - 基线：52 天 4.0 + 18 天 2.0 → 中位 4.0
    - 三次恢复各 2 天 → 中位回弹 2.0，滞留 11 > 2×2 → 双信号成立
    """

    def _series(self, strand=True):
        s = filled(30, 40, 4.0)                      # d(69)..d(30)
        s.update(filled(12, 18, 4.0))                # d(29)..d(12) 底色
        for low, mid in ((24, 23), (20, 19), (16, 15)):
            s[d(low)] = 2.0
            s[d(mid)] = 2.0
        if strand:
            s.update(filled(0, 12, 2.0))             # d(11)..d(0) 滞留段
        else:
            # 3.5 下沉近窗（中位 3.5 → 漂移 −0.5 成立），但 > 基线−1 → 不算低点
            s.update(filled(0, 12, 3.5))
        return s

    def test_both_signals_light_red(self):
        s = self._series()
        base_line = mb.baseline_of(s)
        self.assertEqual(base_line, 4.0)
        dx = mb.diagnose(s, base_line, TODAY)
        self.assertTrue(dx.drifting)
        self.assertTrue(dx.stranded)
        # 数字复核
        recent, prev, delta = mb.climate_drift(s, TODAY)
        self.assertEqual((prev, recent), (4.0, 2.0))

    def test_drift_alone_no_gate(self):
        s = self._series(strand=False)
        dx = mb.diagnose(s, mb.baseline_of(s), TODAY)
        self.assertTrue(dx.drifting)
        self.assertFalse(dx.stranded)

    def test_stable_climate_green(self):
        s = filled(0, 70, 4.0)
        dx = mb.diagnose(s, mb.baseline_of(s), TODAY)
        self.assertFalse(dx.drifting)
        self.assertFalse(dx.stranded)


# ---------------------------------------------------------------------------
# CLI 层
# ---------------------------------------------------------------------------

def ledger_text(rows):
    return "# date\ttime\tmood\tevents\tnote\n" + "".join(rows) + "\n"


class CliBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        p = os.path.join(self.dir, "moods.tsv")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, CLI, *argv],
                              capture_output=True, text=True)


class CliGateTests(CliBase):
    def _thin_ledger(self):
        rows = [f"{(TODAY - dt.timedelta(days=i)).isoformat()}\t\t3\t\t\n" for i in range(10)]
        return self.write(ledger_text(rows))

    def test_climate_thin_refused_exit_3(self):
        r = self.run_cli("climate", self._thin_ledger(), "--today", "2026-09-04")
        self.assertEqual(r.returncode, 3)
        self.assertIn("21", r.stderr)

    def test_events_thin_refused_exit_3(self):
        r = self.run_cli("events", self._thin_ledger(), "--today", "2026-09-04")
        self.assertEqual(r.returncode, 3)

    def test_weather_works_on_thin_ledger(self):
        r = self.run_cli("weather", self._thin_ledger(), "--today", "2026-09-04")
        self.assertEqual(r.returncode, 0)
        self.assertIn("基线收集中", r.stdout)

    def _rich_ledger(self, recent_mood="4"):
        """前 30 天 4 分，近 30+1 天 recent_mood 分。"""
        rows = [f"{(TODAY - dt.timedelta(days=i)).isoformat()}\t\t4\t\t\n"
                for i in range(60, 30, -1)]
        rows += [f"{(TODAY - dt.timedelta(days=i)).isoformat()}\t\t{recent_mood}\t\t\n"
                 for i in range(30, -1, -1)]
        return self.write(ledger_text(rows))

    def test_stable_climate_exit_zero(self):
        r = self.run_cli("climate", self._rich_ledger(), "--today", "2026-09-04")
        self.assertEqual(r.returncode, 0)
        self.assertIn("气候稳定", r.stdout)

    def test_drift_and_strand_exit_four(self):
        # 与 GateTests._series(strand=True) 相同的 70 天演算，走 CLI
        rows = [f"{(TODAY - dt.timedelta(days=i)).isoformat()}\t\t4\t\t\n"
                for i in range(69, 11, -1)]
        for low in (24, 23, 20, 19, 16, 15, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0):
            rows.append(f"{d(low).isoformat()}\t\t2\t\t\n")
        ledger = self.write(ledger_text(rows))
        r = self.run_cli("climate", ledger, "--today", "2026-09-04")
        self.assertEqual(r.returncode, 4)
        self.assertIn("气候在变", r.stdout + r.stderr)

    def test_drift_alone_exit_zero(self):
        r = self.run_cli("climate", self._rich_ledger(recent_mood="3"), "--today", "2026-09-04")
        self.assertEqual(r.returncode, 0)
        self.assertIn("漂移成立", r.stdout)

    def test_log_command(self):
        r = self.run_cli("log")
        self.assertEqual(r.returncode, 0)
        self.assertIn("量表锚点", r.stdout)


class CliParseTests(CliBase):
    def test_mood_out_of_range_exit_2(self):
        p = self.write(ledger_text(["2026-09-01\t\t6\t\t\n"]))
        r = self.run_cli("weather", p, "--today", "2026-09-04")
        self.assertEqual(r.returncode, 2)
        self.assertIn("越界", r.stderr)

    def test_future_entry_exit_2(self):
        p = self.write(ledger_text(["2026-09-10\t\t3\t\t\n"]))
        r = self.run_cli("weather", p, "--today", "2026-09-04")
        self.assertEqual(r.returncode, 2)

    def test_missing_file_exit_2(self):
        r = self.run_cli("weather", "/nonexistent.tsv", "--today", "2026-09-04")
        self.assertEqual(r.returncode, 2)

    def test_empty_ledger_exit_3(self):
        p = self.write("# empty\n")
        r = self.run_cli("weather", p, "--today", "2026-09-04")
        self.assertEqual(r.returncode, 3)


class CliDeterminismTests(CliBase):
    def test_same_input_same_bytes(self):
        rows = [f"{(TODAY - dt.timedelta(days=i)).isoformat()}\t\t{3 + (i % 2)}\t\t\n"
                for i in range(30)]
        p = self.write(ledger_text(rows))
        argv = ["weather", p, "--today", "2026-09-04"]
        r1 = self.run_cli(*argv)
        r2 = self.run_cli(*argv)
        self.assertEqual(r1.stdout, r2.stdout)

    def test_weather_shows_offset_vs_baseline(self):
        rows = [f"{(TODAY - dt.timedelta(days=i)).isoformat()}\t\t4\t\t\n" for i in range(30)]
        rows += [f"{(TODAY - dt.timedelta(days=i)).isoformat()}\t\t2\t\t\n" for i in range(3)]
        p = self.write(ledger_text(rows))
        r = self.run_cli("weather", p, "--today", "2026-09-04")
        self.assertEqual(r.returncode, 0)
        self.assertIn("vs 基线", r.stdout)
        self.assertIn("滞留计时", r.stdout)


if __name__ == "__main__":
    unittest.main()
