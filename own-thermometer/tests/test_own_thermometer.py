# -*- coding: utf-8 -*-
"""own-thermometer acceptance tests: the skin ledger, the terrain, the gates.

Every acceptance criterion in README.md lands here. The statistics are
pinned by hand-computed values; the verdicts are pinned by exit code; the
identities are pinned exactly. Snapshot byte-equality is verified against
examples/sample-*.txt via build_examples.py --check.
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import own_thermometer as ot  # noqa: E402

EXAMPLES = os.path.join(ROOT, "examples")
LEDGER = os.path.join(EXAMPLES, "ledger.tsv")

HEADER = "date\ttmin\ttmax\tcond\toutfit\tfeel"


def run_cli(*argv):
    """Run the CLI in-process; return (exit_code, stdout)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = ot.main(list(argv))
    return code, buf.getvalue()


def write_tsv(rows, header=HEADER):
    body = "\n".join([header] + rows)
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body + "\n")
    return path


# ------------------------------------------------------------------ A. parsing

class ParsingTest(unittest.TestCase):
    def test_demo_ledger_loads(self):
        days, end = ot.load_ledger(LEDGER)
        self.assertEqual(len(days), 111)
        self.assertEqual(end.isoformat(), "2026-04-12")

    def test_header_comments_blank_skipped(self):
        path = write_tsv(["# a comment", "", "2025-11-13\t4\t9\tcloudy\t卫衣\t-1"])
        try:
            days, _ = ot.load_ledger(path)
            self.assertEqual(len(days), 1)
        finally:
            os.unlink(path)

    def test_wrong_column_count_exit2(self):
        path = write_tsv(["2025-11-13\t4\t9\tcloudy\t卫衣"])
        try:
            with self.assertRaises(ot.LedgerError):
                ot.load_ledger(path)
        finally:
            os.unlink(path)

    def test_feel_out_of_range_exit2(self):
        path = write_tsv(["2025-11-13\t4\t9\tcloudy\t卫衣\t3"])
        try:
            with self.assertRaises(ot.LedgerError):
                ot.load_ledger(path)
        finally:
            os.unlink(path)

    def test_feel_non_integer_exit2(self):
        path = write_tsv(["2025-11-13\t4\t9\tcloudy\t卫衣\t0.5"])
        try:
            with self.assertRaises(ot.LedgerError):
                ot.load_ledger(path)
        finally:
            os.unlink(path)

    def test_tmin_gt_tmax_exit2(self):
        path = write_tsv(["2025-11-13\t9\t4\tcloudy\t卫衣\t0"])
        try:
            with self.assertRaises(ot.LedgerError):
                ot.load_ledger(path)
        finally:
            os.unlink(path)

    def test_bad_cond_exit2(self):
        path = write_tsv(["2025-11-13\t4\t9\twindy\t卫衣\t0"])
        try:
            with self.assertRaises(ot.LedgerError):
                ot.load_ledger(path)
        finally:
            os.unlink(path)

    def test_empty_cond_ok(self):
        path = write_tsv(["2025-11-13\t4\t9\t\t卫衣\t0"])
        try:
            days, _ = ot.load_ledger(path)
            self.assertEqual(days[0].cond, "")
        finally:
            os.unlink(path)

    def test_empty_outfit_exit2(self):
        path = write_tsv(["2025-11-13\t4\t9\tcloudy\t\t0"])
        try:
            with self.assertRaises(ot.LedgerError):
                ot.load_ledger(path)
        finally:
            os.unlink(path)

    def test_empty_garment_in_outfit_exit2(self):
        path = write_tsv(["2025-11-13\t4\t9\tcloudy\t卫衣+\t0"])
        try:
            with self.assertRaises(ot.LedgerError):
                ot.load_ledger(path)
        finally:
            os.unlink(path)

    def test_duplicate_date_exit2(self):
        path = write_tsv(["2025-11-13\t4\t9\tcloudy\t卫衣\t0",
                          "2025-11-13\t5\t9\tcloudy\t毛衣\t0"])
        try:
            with self.assertRaises(ot.LedgerError) as cm:
                ot.load_ledger(path)
            self.assertIn("日期重复", str(cm.exception))
        finally:
            os.unlink(path)

    def test_bad_date_exit2(self):
        path = write_tsv(["2025-13-40\t4\t9\tcloudy\t卫衣\t0"])
        try:
            with self.assertRaises(ot.LedgerError):
                ot.load_ledger(path)
        finally:
            os.unlink(path)

    def test_cli_reports_exit2(self):
        path = write_tsv(["2025-11-13\t4\t9\tcloudy\t卫衣\t7"])
        try:
            code, out = run_cli("report", path)
            self.assertEqual(code, 2)
            self.assertIn("账本损坏", out)
        finally:
            os.unlink(path)

    def test_missing_file_exit2(self):
        code, out = run_cli("report", "/nonexistent/ledger.tsv")
        self.assertEqual(code, 2)


# ------------------------------------------------------------------ B. report

class ReportTest(unittest.TestCase):
    def test_exit0_and_sections(self):
        code, out = run_cli("report", LEDGER)
        self.assertEqual(code, 0)
        for key in ("§1 温度地形", "§2 失误账", "§3 换季惯性", "§4 换季解剖", "§5 近 30 天"):
            self.assertIn(key, out)

    def test_terrain_comfort_and_mine(self):
        code, out = run_cli("report", LEDGER)
        self.assertEqual(code, 0)
        self.assertIn("舒适段 [9, 18)", out)
        self.assertIn("雷区 [18, 21)", out)
        self.assertIn("66.7%", out)

    def test_miss_account_numbers(self):
        code, out = run_cli("report", LEDGER)
        self.assertIn("失误 23/111 = 20.7%", out)
        self.assertIn("冷 13 · 热 10", out)
        self.assertIn("穿少的乐观税", out)

    def test_feel_bucket_sum_identity(self):
        code, out = run_cli("report", LEDGER)
        self.assertIn("（桶和 111 = 记录 111 ✓）", out)

    def test_rain_vs_dry(self):
        code, out = run_cli("report", LEDGER)
        self.assertIn("雨天失误率 30.0%（n=20）vs 干天 18.7%（n=91）", out)
        self.assertIn("+11.3pp", out)

    def test_rain_thin_not_compared(self):
        rows = ["2025-11-%02d\t4\t9\train\t卫衣\t0" % d for d in range(1, 4)]
        rows += ["2025-12-%02d\t4\t9\t\t毛衣\t0" % d for d in range(1, 21)]
        path = write_tsv(rows)
        try:
            code, out = run_cli("report", path)
            self.assertEqual(code, 0)
            self.assertIn("n<5 不比", out)
        finally:
            os.unlink(path)

    def test_steep_vs_mild(self):
        code, out = run_cli("report", LEDGER)
        self.assertIn("骤变日失误率 44.4%（n=9，其中偏冷 3）vs 渐变日 18.8%（n=101）", out)
        self.assertIn("2.4 倍", out)

    def test_steep_thin_not_compared(self):
        # 单调升账本：无骤变日
        rows = []
        for i, d in enumerate(range(1, 21)):
            rows.append("2025-11-%02d\t%d\t%d\tsunny\t毛衣\t0" % (d, 4 + i * 0.2, 6 + i * 0.2))
        path = write_tsv(rows)
        try:
            code, out = run_cli("report", path)
            self.assertIn("样本不足", out)
        finally:
            os.unlink(path)

    def test_season_months_flagged(self):
        code, out = run_cli("report", LEDGER)
        self.assertEqual(out.count("← 换季月"), 3)
        self.assertIn("3 个换季月", out)

    def test_month_thin_skipped(self):
        code, out = run_cli("report", LEDGER)
        # [-3,0) 桶 n=4、[27,30) 桶 n=1 都不足门槛，不判
        self.assertIn("(n= 4)  THIN 不判", out)
        self.assertIn("(n= 1)  THIN 不判", out)

    def test_recent30_window(self):
        code, out = run_cli("report", LEDGER)
        self.assertIn("n=14，失误率 35.7% vs 全史 20.7%", out)
        self.assertIn("最近正在变糟", out)

    def test_recent30_moves_with_today(self):
        code, out = run_cli("report", LEDGER, "--today", "2026-01-15")
        self.assertIn("n=%d" % 15, out)  # 1 月窗口内 15 条
        self.assertNotIn("35.7%", out)

    def test_thin_exit3(self):
        path = write_tsv(["2025-11-%02d\t4\t9\t\t卫衣\t0" % d for d in range(1, 11)])
        try:
            code, out = run_cli("report", path)
            self.assertEqual(code, 3)
            self.assertIn("THIN", out)
        finally:
            os.unlink(path)

    def test_default_today_is_ledger_end(self):
        code, out = run_cli("report", LEDGER)
        self.assertIn("--today 2026-04-12（账本末日锚定）", out)

    def test_explicit_today_shown(self):
        code, out = run_cli("report", LEDGER, "--today", "2026-04-13")
        self.assertIn("--today 2026-04-13\n", out.replace("计）", "计）\n"))
        self.assertIn("2026-04-13", out)


# ------------------------------------------------------------------ C. garments

class GarmentsTest(unittest.TestCase):
    def test_exit4_with_wounded_gap(self):
        code, out = run_cli("garments", LEDGER)
        self.assertEqual(code, 4)
        self.assertIn("带伤口的断档", out)

    def test_gap_location(self):
        code, out = run_cli("garments", LEDGER)
        self.assertIn("20–22°C（3 度）", out)
        self.assertIn("5 天出门硬扛记录（冷 0 · 热 5）", out)

    def test_orphans_named(self):
        code, out = run_cli("garments", LEDGER)
        self.assertIn("轻型羽绒", out)
        self.assertIn("8 穿 8 冷热", out)
        self.assertIn("长袖T", out)
        self.assertIn("15 穿 12 冷热", out)
        self.assertEqual(out.count("孤儿温区"), 2)

    def test_garment_windows_sorted(self):
        code, out = run_cli("garments", LEDGER)
        # 毛衣 n=57 排第一
        self.assertLess(out.index("毛衣"), out.index("风衣"))
        self.assertIn("0.96", out)
        self.assertIn("0.00", out)

    def test_thin_garment_not_judged(self):
        path = write_tsv([
            "2025-11-13\t4\t9\t\t毛衣+围巾\t0",
            "2025-11-14\t4\t9\t\t毛衣+围巾\t0",
        ] + ["2025-12-%02d\t0\t5\t\t厚羽绒+毛衣\t0" % d for d in range(1, 21)])
        try:
            code, out = run_cli("garments", path)
            self.assertIn("围巾", out)
            self.assertIn("THIN", out)
        finally:
            os.unlink(path)

    def test_gapless_ledger_exit0(self):
        # 每个温度档都有穿对记录 → 无断档
        rows = []
        t = -2.0
        day = 1
        for month in (11, 12, 1, 2, 3):
            while t <= 26.0 and day <= 28:
                rows.append("2025-%02d-%02d\t%.1f\t%.1f\t\t羽绒服\t0" % (month, day, t - 2, t + 2)
                            if month >= 11 else
                            "2026-%02d-%02d\t%.1f\t%.1f\t\t羽绒服\t0" % (month, day, t - 2, t + 2))
                t += 1.0
                day += 1
        path = write_tsv(rows)
        try:
            code, out = run_cli("garments", path)
            self.assertEqual(code, 0)
            self.assertIn("无断档", out)
        finally:
            os.unlink(path)

    def test_no_interp_extrapolation(self):
        # C4 回归：3 次零星成功（18/23/23.5）不得覆盖 19.5–21.5 段。
        # 装备 A 出现 8 次但只成功 3 次（18.0、23.0、23.5），其余全失误且落在 20 度档。
        rows = [
            "2025-11-03\t16\t20\t\t夹克A\t0",    # tmean 18.0 成功
            "2025-11-04\t21\t25\t\t夹克A\t0",    # tmean 23.0 成功
            "2025-11-05\t21.5\t25.5\t\t夹克A\t0",  # tmean 23.5 成功
            "2025-11-06\t18\t22\t\t夹克A\t1",    # tmean 20.0 热失误
            "2025-11-07\t18\t22\t\t夹克A\t2",    # 20.0 热失误
            "2025-11-10\t18\t22\t\t夹克A\t1",    # 20.0
            "2025-11-11\t18\t22\t\t夹克A\t1",    # 20.0
        ] + ["2025-12-%02d\t-5\t-1\t\t厚羽绒\t0" % d for d in range(1, 16)]
        path = write_tsv(rows)
        try:
            code, out = run_cli("garments", path)
            self.assertEqual(code, 4)
            self.assertIn("断档", out)
        finally:
            os.unlink(path)

    def test_thin_ledger_exit3(self):
        path = write_tsv(["2025-11-%02d\t4\t9\t\t卫衣\t0" % d for d in range(1, 11)])
        try:
            code, out = run_cli("garments", path)
            self.assertEqual(code, 3)
        finally:
            os.unlink(path)

    def test_path_printed_as_basename(self):
        code, out = run_cli("garments", LEDGER)
        self.assertIn("账本 ledger.tsv", out)
        self.assertNotIn(EXAMPLES, out)


# ------------------------------------------------------------------ D. combos

class CombosTest(unittest.TestCase):
    def test_three_tiers(self):
        code, out = run_cli("combos", LEDGER)
        self.assertEqual(code, 0)
        self.assertIn("★ 闭眼穿", out)
        self.assertIn("◐ 看情况", out)
        self.assertIn("✗ 该退役", out)

    def test_star_combo(self):
        code, out = run_cli("combos", LEDGER)
        self.assertIn("毛衣+风衣", out)
        self.assertIn("26 次 win 0.96", out)

    def test_dead_combo_last_miss(self):
        code, out = run_cli("combos", LEDGER)
        self.assertIn("轻型羽绒+长袖T", out)
        self.assertIn("8 次 win 0.00", out)
        self.assertIn("最近一次失误 2026-03-04 -1", out)

    def test_thin_combos_listed(self):
        # 组合 <3 次不判，进 THIN 名单
        rows = ["2025-11-13\t4\t9\t\t毛衣+围巾\t0",
                "2025-11-14\t4\t9\t\t毛衣+围巾\t0"]
        rows += ["2025-12-%02d\t0\t5\t\t厚羽绒+毛衣\t0" % d for d in range(1, 21)]
        path = write_tsv(rows)
        try:
            code, out = run_cli("combos", path)
            self.assertEqual(code, 0)
            self.assertIn("? 样本不足（THIN，不判）：", out)
            self.assertIn("毛衣+围巾", out)
            self.assertIn("2 次（继续攒）", out)
        finally:
            os.unlink(path)

    def test_thin_ledger_exit3(self):
        path = write_tsv(["2025-11-%02d\t4\t9\t\t卫衣\t0" % d for d in range(1, 11)])
        try:
            code, out = run_cli("combos", path)
            self.assertEqual(code, 3)
        finally:
            os.unlink(path)


# ------------------------------------------------------------------ E. plan

class PlanTest(unittest.TestCase):
    def test_recommend_safe(self):
        code, out = run_cli("plan", LEDGER, "--tmin", "7", "--tmax", "13")
        self.assertEqual(code, 0)
        self.assertIn("近邻 18 天", out)
        self.assertIn("毛衣+风衣", out)
        self.assertIn("近邻 13 次 win 1.00", out)
        self.assertIn("裁决：SAFE", out)

    def test_wasteland_exit4(self):
        code, out = run_cli("plan", LEDGER, "--tmin", "18", "--tmax", "23")
        self.assertEqual(code, 4)
        self.assertIn("WASTELAND", out)
        self.assertIn("0/7", out)

    def test_dead_via_all_season_fallback(self):
        code, out = run_cli("plan", LEDGER, "--tmin", "7", "--tmax", "13",
                            "--wear", "轻型羽绒+长袖T")
        self.assertEqual(code, 4)
        self.assertIn("全史兜底", out)
        self.assertIn("0 好 · 8 失误 · win 0.00", out)
        self.assertIn("裁决：DEAD", out)

    def test_unknown_no_neighbors_exit3(self):
        code, out = run_cli("plan", LEDGER, "--tmin", "40", "--tmax", "45")
        self.assertEqual(code, 3)
        self.assertIn("UNKNOWN", out)

    def test_unknown_combo_exit3(self):
        code, out = run_cli("plan", LEDGER, "--tmin", "7", "--tmax", "13",
                            "--wear", "婚纱")
        self.assertEqual(code, 3)
        self.assertIn("UNKNOWN", out)

    def test_nearby_combo_beats_fallback(self):
        # 近邻 ≥3 次时必须用近邻口径，即使全史口径会给出不同（更宽恕的）裁决：
        # 组合 X 近邻 3 次（0,-1,-1 → win 0.33 RISKY），全史 9 次（7 好 → win 0.78 SAFE）
        rows = [
            "2025-11-01\t8\t12\t\t组合X\t-1",
            "2025-11-02\t8\t12\t\t组合X\t0",
            "2025-11-03\t8\t12\t\t组合X\t-1",
            "2025-11-04\t8\t12\t\t组合X\t0",
            "2025-11-05\t8\t12\t\t组合X\t-1",
            "2025-06-01\t18\t22\t\t组合X\t0",
            "2025-06-02\t18\t22\t\t组合X\t0",
            "2025-06-03\t18\t22\t\t组合X\t0",
            "2025-07-01\t18\t22\t\t组合X\t0",
        ] + ["2026-01-%02d\t0\t5\t\t厚羽绒\t0" % d for d in range(4, 20)]
        path = write_tsv(rows)
        try:
            code, out = run_cli("plan", path, "--tmin", "8", "--tmax", "12",
                                "--wear", "组合X", "--safe", "0.7", "--risky", "0.4")
            self.assertEqual(code, 1)
            self.assertIn("（近邻 口径，n=5）", out)
            self.assertIn("裁决：RISKY", out)
        finally:
            os.unlink(path)

    def test_tmin_gt_tmax_exit2(self):
        code, out = run_cli("plan", LEDGER, "--tmin", "13", "--tmax", "7")
        self.assertEqual(code, 2)

    def test_thin_ledger_exit3(self):
        path = write_tsv(["2025-11-%02d\t4\t9\t\t卫衣\t0" % d for d in range(1, 11)])
        try:
            code, out = run_cli("plan", path, "--tmin", "4", "--tmax", "9")
            self.assertEqual(code, 3)
        finally:
            os.unlink(path)

    def test_streak_demotes_safe_to_risky(self):
        # 构造组合全史 win=1.00 但末尾连续 3 次同向失误 —— 连败降档 STREAK。
        # win 1.00 与「末尾 3 连失误」矛盾，故用精确边界：win 刚好 SAFE 线上(0.70)，
        # 末尾连败把 SAFE 拉到 RISKY。
        rows = []
        # 组合 X：10 次记录 7 好 3 失误（win 0.70 → SAFE），最后 3 次连续 -1
        seq = [0, 0, 0, 0, 0, 0, 0, -1, -1, -1]
        days = ["2025-11-%02d" % d for d in range(1, 9)] + ["2025-12-%02d" % d for d in range(1, 4)]
        for d, f in zip(days, seq):
            rows.append("%s\t8\t12\t\t组合X\t%d" % (d, f))
        rows += ["2026-01-%02d\t0\t5\t\t厚羽绒\t0" % d for d in range(4, 20)]
        path = write_tsv(rows)
        try:
            code, out = run_cli("plan", path, "--tmin", "8", "--tmax", "12",
                                "--wear", "组合X", "--risky", "0.4", "--safe", "0.7")
            self.assertEqual(code, 1)
            self.assertIn("STREAK", out)
        finally:
            os.unlink(path)

    def test_no_streak_no_demotion(self):
        rows = []
        seq = [0, 0, 0, 0, 0, 0, 0, -1, 0, -1]
        days = ["2025-11-%02d" % d for d in range(1, 9)] + ["2025-12-%02d" % d for d in range(1, 4)]
        for d, f in zip(days, seq):
            rows.append("%s\t8\t12\t\t组合Y\t%d" % (d, f))
        rows += ["2026-01-%02d\t0\t5\t\t厚羽绒\t0" % d for d in range(4, 20)]
        path = write_tsv(rows)
        try:
            code, out = run_cli("plan", path, "--tmin", "8", "--tmax", "12",
                                "--wear", "组合Y", "--risky", "0.4", "--safe", "0.7")
            self.assertEqual(code, 0)
            self.assertNotIn("STREAK", out)
            self.assertIn("裁决：SAFE", out)
        finally:
            os.unlink(path)


# ------------------------------------------------------------------ F. autopsy

class AutopsyTest(unittest.TestCase):
    def test_exit4_strike(self):
        code, out = run_cli("autopsy", LEDGER)
        self.assertEqual(code, 4)
        self.assertIn("[6, 9)°C 桶：2026-03-02 → 2026-03-04 连续 3 天偏冷", out)

    def test_split_and_identity(self):
        code, out = run_cli("autopsy", LEDGER)
        self.assertIn("有解 16 天（69.6%）", out)
        self.assertIn("无解 7 天（30.4%）", out)
        self.assertIn("不可判 0 天", out)
        self.assertIn("恒等式：16 + 7 + 0 = 23 ✓", out)

    def test_solvable_example_line(self):
        code, out = run_cli("autopsy", LEDGER)
        self.assertIn("2025-10-29（13.5°C）穿 卫衣 → -1；同温带答案：风衣+卫衣（5 次 win 1.00）", out)

    def test_unjudgeable_requires_control_arm(self):
        # 失误日落在温度带边缘，同温带（±1.5°C，不含当天）不足 3 天 → 不可判
        rows = [
            "2025-11-01\t4\t9\t\t卫衣\t0",
            "2025-11-02\t4\t9\t\t卫衣\t0",
            "2025-11-03\t0\t5\t\t卫衣\t-2",   # tmean 2.5，近邻 [1.0,4.0) 内无其他记录
        ] + ["2025-12-%02d\t20\t26\t\t衬衫\t0" % d for d in range(1, 21)]
        path = write_tsv(rows)
        try:
            code, out = run_cli("autopsy", path)
            self.assertEqual(code, 0)
            self.assertIn("不可判 1 天", out)
            self.assertIn("恒等式：0 + 0 + 1 = 1 ✓", out)
        finally:
            os.unlink(path)

    def test_no_strike_exit0(self):
        # 深冬稳态账本：有失误但不连败
        rows = []
        feel_seq = [0, 0, -1, 0, 0, 0, -1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 0, -1, 0, 0]
        for i, f in enumerate(feel_seq):
            d = 1 + i
            rows.append("2025-12-%02d\t-2\t4\t\t厚羽绒+毛衣\t%d" % (d, f))
        path = write_tsv(rows)
        try:
            code, out = run_cli("autopsy", path)
            self.assertEqual(code, 0)
            self.assertIn("没有任何温度带正在连败", out)
        finally:
            os.unlink(path)

    def test_thin_ledger_exit3(self):
        path = write_tsv(["2025-11-%02d\t4\t9\t\t卫衣\t-1" % d for d in range(1, 11)])
        try:
            code, out = run_cli("autopsy", path)
            self.assertEqual(code, 3)
        finally:
            os.unlink(path)

    def test_perfect_ledger_exit0(self):
        path = write_tsv(["2025-11-%02d\t4\t9\t\t卫衣\t0" % d for d in range(1, 25)])
        try:
            code, out = run_cli("autopsy", path)
            self.assertEqual(code, 0)
            self.assertIn("没有失误", out)
        finally:
            os.unlink(path)


# ------------------------------------------------------------------ G. validate

class ValidateTest(unittest.TestCase):
    def test_clean_ledger_exit0(self):
        code, out = run_cli("validate", LEDGER)
        self.assertEqual(code, 0)
        for key in ("V1", "V2", "V3", "V4", "V5", "V6"):
            self.assertIn(key, out)
        self.assertIn("账本干净", out)

    def test_future_date_exit2(self):
        # 未来检测相对显式 --today；缺省锚 = 账本末日（自锚定），见下一条
        path = write_tsv(["2037-01-01\t4\t9\t\t卫衣\t0"])
        try:
            code, out = run_cli("validate", path, "--today", "2026-04-12")
            self.assertEqual(code, 2)
            self.assertIn("未来还没有体感", out)
        finally:
            os.unlink(path)

    def test_default_anchor_makes_latest_row_today(self):
        # 自锚定：无 --today 时账本末日即今天，末日行不算未来
        path = write_tsv(["2026-04-12\t4\t9\t\t卫衣\t0"])
        try:
            code, out = run_cli("validate", path)
            self.assertEqual(code, 0)
        finally:
            os.unlink(path)

    def test_future_date_pinned_by_today_ok(self):
        path = write_tsv(["2037-01-01\t4\t9\t\t卫衣\t0"])
        try:
            code, out = run_cli("validate", path, "--today", "2037-01-02")
            self.assertEqual(code, 0)
        finally:
            os.unlink(path)

    def test_garment_total_identity(self):
        # V5：每行至少一件 —— 单行账本不可能破（解析层已拦空 outfit），恒等式永远过
        code, out = run_cli("validate", LEDGER)
        self.assertIn("V5 单品出场", out)


# ------------------------------------------------------------------ H. determinism

class DeterminismTest(unittest.TestCase):
    def test_run_twice_byte_identical(self):
        _, out1 = run_cli("report", LEDGER)
        _, out2 = run_cli("report", LEDGER)
        self.assertEqual(out1, out2)
        _, out3 = run_cli("plan", LEDGER, "--tmin", "7", "--tmax", "13")
        _, out4 = run_cli("plan", LEDGER, "--tmin", "7", "--tmax", "13")
        self.assertEqual(out3, out4)

    def test_today_changes_output(self):
        _, out_default = run_cli("report", LEDGER)
        _, out_pinned = run_cli("report", LEDGER, "--today", "2026-02-15")
        self.assertNotEqual(out_default, out_pinned)

    def test_percentile_hand_computed(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        self.assertEqual(ot.percentile(vals, 0), 1.0)
        self.assertEqual(ot.percentile(vals, 100), 10.0)
        self.assertEqual(ot.percentile(vals, 50), 5.5)
        self.assertAlmostEqual(ot.percentile(vals, 10), 1.9)
        self.assertAlmostEqual(ot.percentile(vals, 90), 9.1)
        self.assertEqual(ot.percentile([42.0], 37), 42.0)

    def test_snapshots_byte_exact(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(EXAMPLES, "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         "snapshot mismatch:\n%s%s" % (proc.stdout, proc.stderr))

    def test_snapshot_exit_codes(self):
        expectations = {
            "sample-report.txt": 0,
            "sample-garments.txt": 4,
            "sample-combos.txt": 0,
            "sample-plan.txt": 0,
            "sample-plan-dead.txt": 4,
            "sample-plan-wasteland.txt": 4,
            "sample-autopsy.txt": 4,
            "sample-validate.txt": 0,
        }
        for name, want in expectations.items():
            path = os.path.join(EXAMPLES, name)
            self.assertTrue(os.path.exists(path), name)
        # 每张快照都要有实质内容（防止空文件冒充快照）
        for name in expectations:
            with open(os.path.join(EXAMPLES, name), encoding="utf-8") as fh:
                self.assertGreater(len(fh.read()), 50, name)


# ------------------------------------------------------------------ units

class UnitTest(unittest.TestCase):
    def test_tail_streak(self):
        def mk(feels):
            from datetime import date as D
            return [ot.Day(D(2025, 11, 1 + i), 4, 9, "", ["x"], f) for i, f in enumerate(feels)]

        self.assertEqual(ot.tail_streak(mk([0, -1, -1, -1]), 3), 3)
        self.assertEqual(ot.tail_streak(mk([0, -1, -1, -1]), 4), 0)   # 不足门槛返回 0
        self.assertEqual(ot.tail_streak(mk([0, -1, 1, -1]), 2), 0)    # 方向变了，末尾同向只有 1 < 门槛
        self.assertEqual(ot.tail_streak(mk([0, -1, 1, 1]), 2), 2)     # 换向后重新起算
        self.assertEqual(ot.tail_streak(mk([0, -1, -1, 0]), 1), 0)    # 末尾是 0
        self.assertEqual(ot.tail_streak(mk([]), 1), 0)

    def test_bucket_of(self):
        self.assertEqual(ot.bucket_of(-1.0), -3.0)
        self.assertEqual(ot.bucket_of(0.0), 0.0)
        self.assertEqual(ot.bucket_of(2.9), 0.0)
        self.assertEqual(ot.bucket_of(3.0), 3.0)
        self.assertEqual(ot.bucket_of(19.0), 18.0)

    def test_tmean(self):
        from datetime import date as D
        d = ot.Day(D(2025, 11, 13), 4, 9, "", ["卫衣"], -1)
        self.assertEqual(d.tmean, 6.5)
        self.assertEqual(d.combo, "卫衣")

    def test_win_rate(self):
        from datetime import date as D
        recs = [ot.Day(D(2025, 11, 1), 4, 9, "", ["x"], 0),
                ot.Day(D(2025, 11, 2), 4, 9, "", ["x"], -1),
                ot.Day(D(2025, 11, 3), 4, 9, "", ["x"], 0)]
        self.assertAlmostEqual(ot.win_rate(recs), 2.0 / 3.0)
        self.assertIsNone(ot.win_rate([]))


if __name__ == "__main__":
    unittest.main()
