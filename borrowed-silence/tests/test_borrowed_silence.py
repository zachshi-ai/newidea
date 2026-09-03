#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""borrowed-silence · 预支安静 — 验收测试.

验收标准（全部转成自动化测试）：
  A1  NIOSH 剂量公式：85dB×8h = 88dB×4h = 100dB×15min = 1.0 安全日（3dB 交换率）
  A2  线性叠加：日剂量 = 各事件安全日之和，跨声源、跨时段
  A3  耳塞折减：NRR32 @105dB → (32−7)/2 = 12.5 → 92.5dB；2.5h 从 31.75 sd 跌到 1.77 sd
  A4  日判灯：>1.0 sd → RED + exit 4；≤1.0 → GREEN + exit 0
  A5  周额度：>5.0 sd → 超支文案 + exit 4；≤5.0 → exit 0；--budget 可调
  A6  Leq(8h)：85 + 10·log10(总安全日)，与闭式手算一致
  A7  symptom 行不计剂量，但出现在 day/week 报告里（身体的对账单）
  A8  行级 dB 覆盖优先于声源表；第 6 列 NRR 与其可组合
  A9  plan 三态：FITS exit 0 / PLUGS exit 4（裸超、塞后装得下）/ OVER exit 4（塞了也超）
  A10 时长解析：`0:45` / `2h` / `2h30m` / `45m` 全部归一；非法 exit 2
  A11 坏行带行号 exit 2；未知声源无覆盖 exit 2；空账本 / 窗口无记录 exit 3
  A12 终身账 = 全事件求和（symptom 除外）；声源分布与年化可复核
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
import borrowed_silence as bs  # noqa: E402


def run_cli(*argv):
    """调用 main，返回 (exit_code, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = bs.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def write_ledger(rows):
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return path


class TempLedgerCase(unittest.TestCase):
    """写临时账本跑 CLI，结束即清理。"""

    def setUp(self):
        self.paths = []

    def tearDown(self):
        for p in self.paths:
            os.unlink(p)

    def ledger(self, rows):
        path = write_ledger(rows)
        self.paths.append(path)
        return path


class TestDoseMath(unittest.TestCase):
    """A1：NIOSH 剂量公式。"""

    def test_a1_reference_doses_are_one_safe_day(self):
        self.assertAlmostEqual(bs.safe_days(85.0, 8.0), 1.0, places=9)
        self.assertAlmostEqual(bs.safe_days(88.0, 4.0), 1.0, places=9)
        self.assertAlmostEqual(bs.safe_days(91.0, 2.0), 1.0, places=9)
        self.assertAlmostEqual(bs.safe_days(94.0, 1.0), 1.0, places=9)
        self.assertAlmostEqual(bs.safe_days(100.0, 0.25), 1.0, places=9)

    def test_a1_exchange_rate_doubling(self):
        # 每多 3dB，同样时长剂量翻倍
        self.assertAlmostEqual(bs.safe_days(88.0, 1.0) / bs.safe_days(85.0, 1.0),
                               2.0, places=9)
        # 105dB 2.5h ≈ 31.75 安全日（README 的招牌数字）
        self.assertAlmostEqual(bs.safe_days(105.0, 2.5), 31.75, places=2)

    def test_a1_leq_closed_form(self):
        # 1.0 安全日折回 Leq(8h) = 85.0；2.0 → 85 + 10·log10(2) = 88.0103
        self.assertAlmostEqual(bs.leq8h(1.0), 85.0, places=9)
        self.assertAlmostEqual(bs.leq8h(2.0), 88.0103, places=3)
        self.assertEqual(bs.leq8h(0.0), 0.0)

    def test_a1_plug_derate(self):
        # NIOSH 折减：(NRR − 7) / 2
        self.assertAlmostEqual(bs.plug_derate(32.0), 12.5, places=9)
        self.assertAlmostEqual(bs.effective_level(105.0, 32.0), 92.5, places=9)


class TestSuperposition(TempLedgerCase):
    """A2/A7/A8：叠加、symptom、行级覆盖。"""

    def test_a2_day_dose_is_sum_of_events(self):
        # 85dB 1h (0.125) + 100dB 1h (4.0) = 4.125
        path = self.ledger([
            "2026-09-01\t09:00\tmetro\t1:00",
            "2026-09-01\t21:00\theadphone-loud\t1:00",
        ])
        events = bs.parse_ledger(path)
        self.assertAlmostEqual(bs.day_dose(events, dt.date(2026, 9, 1)),
                               4.125, places=9)

    def test_a2_cross_day_isolation(self):
        path = self.ledger([
            "2026-09-01\t09:00\theadphone-loud\t1:00",
            "2026-09-02\t09:00\theadphone-loud\t1:00",
        ])
        events = bs.parse_ledger(path)
        for d in (dt.date(2026, 9, 1), dt.date(2026, 9, 2)):
            self.assertAlmostEqual(bs.day_dose(events, d), 4.0, places=9)

    def test_a7_symptom_counts_zero_dose_but_shows_up(self):
        path = self.ledger([
            "2026-09-05\t21:00\tlivehouse\t2:30",
            "2026-09-05\t23:40\tsymptom\ttinnitus",
        ])
        events = bs.parse_ledger(path)
        self.assertEqual(len(events), 2)
        dose = bs.day_dose(events, dt.date(2026, 9, 5))
        self.assertAlmostEqual(dose, 31.75, places=2)  # 只有演出那行
        code, out, _ = run_cli("day", path, "--date", "2026-09-05")
        self.assertEqual(code, 4)
        self.assertIn("tinnitus", out)
        self.assertIn("身体的对账单", out)

    def test_a8_row_db_override_beats_table(self):
        path = self.ledger(["2026-09-01\t12:00\tcafe\t1:00\t94"])
        events = bs.parse_ledger(path)
        # 表里 cafe=70，行覆盖 94：94dB 1h = 2^3/8 = 1.0
        self.assertAlmostEqual(events[0].safe_days(), 1.0, places=9)

    def test_a8_custom_source_with_override(self):
        # 表外声源 + dB 覆盖 = 自定义声源，合法
        path = self.ledger(["2026-09-01\t14:00\tcar-horn-riot\t0:10\t100"])
        events = bs.parse_ledger(path)
        self.assertAlmostEqual(events[0].safe_days(),
                               bs.safe_days(100.0, 1.0 / 6.0), places=9)

    def test_a8_plug_column_combines_with_override(self):
        # 105dB（覆盖）+ NRR32 → 92.5dB 2.5h = 1.7678
        path = self.ledger(["2026-09-05\t20:00\tbar-club\t2:30\t105\t32"])
        events = bs.parse_ledger(path)
        self.assertAlmostEqual(events[0].safe_days(), 1.7678, places=3)


class TestGates(TempLedgerCase):
    """A4/A5/A9：三道门（日灯、周额度、plan 过闸）。"""

    def test_a4_day_green_exit0(self):
        path = self.ledger(["2026-09-01\t09:00\tmetro\t1:00"])
        code, out, _ = run_cli("day", path, "--date", "2026-09-01")
        self.assertEqual(code, 0)
        self.assertIn("GREEN", out)

    def test_a4_day_red_exit4(self):
        # 100dB 1h = 4.0 sd > 1.0
        path = self.ledger(["2026-09-01\t08:45\theadphone-loud\t1:00"])
        code, out, _ = run_cli("day", path, "--date", "2026-09-01")
        self.assertEqual(code, 4)
        self.assertIn("RED", out)

    def test_a4_day_exactly_one_is_green(self):
        # 94dB 1h 恰好 = 1.0（浮点边缘必须落在绿灯侧）
        path = self.ledger(["2026-09-01\t12:00\tcafe\t1:00\t94"])
        code, _, _ = run_cli("day", path, "--date", "2026-09-01")
        self.assertEqual(code, 0)

    def test_a5_week_over_budget_exit4(self):
        rows = []
        for d in ("2026-09-01", "2026-09-02", "2026-09-03"):
            rows.append("%s\t08:45\theadphone-loud\t1:00" % d)  # 4.0 × 3 = 12 > 5
        path = self.ledger(rows)
        code, out, _ = run_cli("week", path, "--end", "2026-09-06")
        self.assertEqual(code, 4)
        self.assertIn("超支", out)
        self.assertIn("借走", out)

    def test_a5_week_within_budget_exit0(self):
        rows = ["2026-09-0%d\t08:00\tmetro\t0:50" % d for d in (1, 2, 3, 4, 5)]
        path = self.ledger(rows)  # 5 × 0.104 = 0.52 sd
        code, out, _ = run_cli("week", path, "--end", "2026-09-06")
        self.assertEqual(code, 0)

    def test_a5_budget_flag_tightens(self):
        path = self.ledger(["2026-09-03\t08:45\theadphone-loud\t1:00"])  # 4.0
        code, out, _ = run_cli("week", path, "--end", "2026-09-06", "--budget", "2")
        self.assertEqual(code, 4)
        code, out, _ = run_cli("week", path, "--end", "2026-09-06", "--budget", "4")
        self.assertEqual(code, 0)

    def test_a9_plan_fits_exit0(self):
        # 安静一周 + cafe 1.5h（0.006 sd）：余量充足，livehouse 裸奔 31.75 也装不下……
        # 所以 FITS 用小事件：metro 50min（0.104 sd）
        path = self.ledger([])
        os.unlink(path)
        self.paths.pop()
        path = self.ledger(["2026-09-08\t07:50\tmetro\t0:50"])
        code, out, _ = run_cli("plan", path, "metro", "0:50", "--week-of", "2026-09-08")
        self.assertEqual(code, 0)
        self.assertIn("FITS", out)

    def test_a9_plan_plugs_exit4_with_discount_note(self):
        # 空周余量 5.0；livehouse 2.5h 裸奔 31.75 > 5；NRR32 → 1.77 ≤ 5 → PLUGS
        path = self.ledger(["2026-09-08\t09:00\tcafe\t1:00"])
        code, out, _ = run_cli("plan", path, "livehouse", "2:30", "--week-of", "2026-09-10")
        self.assertEqual(code, 4)
        self.assertIn("PLUGS", out)
        self.assertIn("打折券", out)
        self.assertIn("18.0", out)  # 两种活法的倍数（%.1f 口径）

    def test_a9_plan_over_exit4(self):
        # 这周已经超支：余量为负，戴耳塞也救不回
        path = self.ledger([
            "2026-09-08\t08:45\theadphone-loud\t1:00",   # 4.0
            "2026-09-09\t20:00\tlivehouse\t2:30",        # 31.75
        ])
        code, out, _ = run_cli("plan", path, "livehouse", "2:30", "--week-of", "2026-09-10")
        self.assertEqual(code, 4)
        self.assertIn("OVER", out)
        self.assertIn("改到下周", out)

    def test_a9_plan_plug_zero_disables_comparison(self):
        # --plug 0：不显示耳塞路线，livehouse 只能 OVER
        path = self.ledger([])
        os.unlink(path)
        self.paths.pop()
        path = self.ledger(["2026-09-08\t09:00\tcafe\t1:00"])
        code, out, _ = run_cli("plan", path, "livehouse", "2:30",
                               "--week-of", "2026-09-10", "--plug", "0")
        self.assertEqual(code, 4)
        self.assertIn("OVER", out)
        self.assertNotIn("打折券", out)


class TestWeekAndLifetime(TempLedgerCase):
    """A6/A12：Leq 展示、终身账完整性。"""

    def test_a6_day_reports_leq(self):
        # 4.125 sd → 85 + 10log10(4.125) = 91.15
        path = self.ledger([
            "2026-09-01\t09:00\tmetro\t1:00",
            "2026-09-01\t21:00\theadphone-loud\t1:00",
        ])
        code, out, _ = run_cli("day", path, "--date", "2026-09-01")
        self.assertEqual(code, 4)
        self.assertIn("Leq(8h)", out)
        self.assertIn("91.2", out)

    def test_a12_lifetime_sums_everything(self):
        path = self.ledger([
            "2026-08-31\t07:50\tmetro\t0:50",
            "2026-08-31\t08:45\theadphone-loud\t1:00",
            "2026-09-05\t20:00\tlivehouse\t2:30",
            "2026-09-05\t23:40\tsymptom\ttinnitus",
            "2026-09-06\t14:00\tcafe\t1:30",
        ])
        events = bs.parse_ledger(path)
        expected = (bs.safe_days(85.0, 50 / 60) + bs.safe_days(100.0, 1.0)
                    + bs.safe_days(105.0, 2.5) + bs.safe_days(70.0, 1.5))
        total = sum(e.safe_days() for e in events)
        self.assertAlmostEqual(total, expected, places=9)
        code, out, _ = run_cli("lifetime", path)
        self.assertEqual(code, 0)
        self.assertIn("只增不减", out)
        self.assertIn("1 次症状记录", out)
        # 年化 = 总量 / 7 天 × 365
        self.assertIn(str(int(round(expected / 7 * 365))), out)

    def test_a12_lifetime_breakdown_percentages(self):
        path = self.ledger([
            "2026-09-01\t08:45\theadphone-loud\t1:00",  # 4.0
            "2026-09-05\t20:00\tlivehouse\t2:30",       # 31.75
        ])
        code, out, _ = run_cli("lifetime", path)
        self.assertEqual(code, 0)
        # livehouse 占 31.75/35.75 ≈ 89%
        self.assertIn("89%", out)

    def test_a12_sources_table_one_hour_values(self):
        code, out, _ = run_cli("sources")
        self.assertEqual(code, 0)
        # 1h@100dB = 4.00 sd；1h@105 = 12.7；1h@110 = 40.3
        self.assertIn("4.00", out)
        self.assertIn("12.7", out)
        self.assertIn("40.3", out)
        self.assertIn("就听一小会儿", out)


class TestParsing(TempLedgerCase):
    """A10/A11：时长归一与账本卫生。"""

    def test_a10_duration_forms(self):
        for text, hours in [("0:45", 0.75), ("2:30", 2.5), ("2h", 2.0),
                            ("45m", 0.75), ("2h30m", 2.5), ("8:00", 8.0)]:
            self.assertAlmostEqual(bs.parse_duration(text), hours, places=9,
                                   msg=text)

    def test_a10_duration_formatting(self):
        self.assertEqual(bs.fmt_duration(0.75), "0:45")
        self.assertEqual(bs.fmt_duration(2.5), "2:30")

    def test_a10_bad_duration_rejected(self):
        for bad in ("", "abc", "1:75", "-2h", "0:00", "2x", "h30"):
            with self.assertRaises(bs.UsageError, msg=bad):
                bs.parse_duration(bad)

    def test_a11_malformed_row_has_lineno(self):
        path = self.ledger(["2026-09-01\t08:00\tmetro"])
        code, _, err = run_cli("day", path, "--date", "2026-09-01")
        self.assertEqual(code, 2)
        self.assertIn("第 1 行", err)

    def test_a11_unknown_source_without_db(self):
        path = self.ledger(["2026-09-01\t08:00\tchainsaw-massif\t0:30"])
        code, _, err = run_cli("day", path, "--date", "2026-09-01")
        self.assertEqual(code, 2)
        self.assertIn("chainsaw-massif", err)
        self.assertIn("dB 覆盖", err)

    def test_a11_db_out_of_range(self):
        path = self.ledger(["2026-09-01\t08:00\tmetro\t0:30\t160"])
        code, _, err = run_cli("day", path, "--date", "2026-09-01")
        self.assertEqual(code, 2)
        self.assertIn("30-140", err)

    def test_a11_symptom_without_name(self):
        path = self.ledger(["2026-09-01\t23:00\tsymptom\t"])
        code, _, err = run_cli("day", path, "--date", "2026-09-01")
        self.assertEqual(code, 2)
        self.assertIn("症状名", err)

    def test_a11_empty_ledger_exit3(self):
        path = self.ledger([])
        code, _, err = run_cli("day", path, "--date", "2026-09-01")
        self.assertEqual(code, 3)

    def test_a11_comments_only_is_empty(self):
        path = self.ledger(["# 只有注释", ""])
        code, _, _ = run_cli("week", path, "--end", "2026-09-06")
        self.assertEqual(code, 3)

    def test_a11_window_without_records_exit3(self):
        path = self.ledger(["2026-01-01\t08:00\tmetro\t0:30"])
        code, _, err = run_cli("week", path, "--end", "2026-09-06")
        self.assertEqual(code, 3)
        self.assertIn("没有", err)

    def test_a11_missing_ledger_exit2(self):
        code, _, err = run_cli("day", "/nonexistent/ledger.tsv", "--date", "2026-09-01")
        self.assertEqual(code, 2)

    def test_a11_validate_reports_custom_sources(self):
        path = self.ledger([
            "2026-09-01\t08:00\tmetro\t0:30",
            "2026-09-01\t12:00\tice-cream-truck\t0:20\t88",
            "2026-09-01\t23:00\tsymptom\tmuffled",
        ])
        code, out, _ = run_cli("validate", path)
        self.assertEqual(code, 0)
        self.assertIn("ice-cream-truck", out)
        self.assertIn("1 条症状", out)


class TestReproducibility(TempLedgerCase):
    """同参数两次运行逐字节一致（无时钟依赖）。"""

    def test_day_is_byte_stable(self):
        path = self.ledger(["2026-09-05\t20:00\tlivehouse\t2:30"])
        _, out1, _ = run_cli("day", path, "--date", "2026-09-05")
        _, out2, _ = run_cli("day", path, "--date", "2026-09-05")
        self.assertEqual(out1, out2)


EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "examples")
sys.path.insert(0, EXAMPLES_DIR)
import build_examples as be  # noqa: E402


class TestDogfood(unittest.TestCase):
    """示例账本与仓库样例的同步门：叙事数字漂移或样例过期即红灯。"""

    def test_demo_ledger_parses_and_narrative_holds(self):
        events = bs.parse_ledger(be.LEDGER)
        total = sum(e.safe_days() for e in events)
        # 小陈的账：26 天借走 ~146.6 个安全日（README/METHODOLOGY 的叙事数字）
        self.assertAlmostEqual(total, 146.65, places=1)
        sympt = [e for e in events if e.is_symptom]
        self.assertEqual(len(sympt), 3)

    def test_samples_are_byte_synced_with_cli(self):
        for name, argv, expected in be.CASES:
            with self.subTest(sample=name):
                code, out, _ = run_cli(*argv)
                self.assertEqual(code, expected)
                with open(os.path.join(EXAMPLES_DIR, name),
                          encoding="utf-8") as fh:
                    self.assertEqual(out, fh.read())


if __name__ == "__main__":
    unittest.main()
