# -*- coding: utf-8 -*-
"""暗基数 · Shadow Base —— 验收标准全部转成自动化测试。"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "shadow_base.py")
SAMPLE = os.path.join(ROOT, "examples", "ledger.tsv")
WAGES = os.path.join(ROOT, "examples", "wages.tsv")

sys.path.insert(0, ROOT)
import shadow_base as sb  # noqa: E402


def write_ledger(rows, header=True):
    """rows: [(month, scheme, base|None, personal, company|None, note|None)]"""
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        if header:
            f.write("month\tscheme\tbase\tpersonal\tcompany\tnote\n")
        for r in rows:
            month, scheme, base, personal, company = r[:5]
            note = r[5] if len(r) > 5 else ""
            f.write("%s\t%s\t%s\t%s\t%s\t%s\n" % (
                month, scheme,
                "" if base is None else base, personal,
                "" if company is None else company, note or ""))
    return path


def write_wages(rows, header=True):
    """rows: [(month, gross)]"""
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        if header:
            f.write("month\tgross\tnote\n")
        for month, gross in rows:
            f.write("%s\t%s\t\n" % (month, gross))
    return path


def run_cli(*argv):
    p = subprocess.run(
        [sys.executable, CLI] + list(argv),
        capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def months(start, n):
    """('2024-10', 23) -> ['2024-10', ...]"""
    y, m = int(start[:4]), int(start[5:7])
    out = []
    for _ in range(n):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# ------------------------------------------------------------ 月份算术

class MonthMathTests(unittest.TestCase):
    def test_ym_add_across_year(self):
        self.assertEqual(sb.ym_add((2024, 11), 3), (2025, 2))
        self.assertEqual(sb.ym_add((2024, 1), -1), (2023, 12))

    def test_ym_sub(self):
        self.assertEqual(sb.ym_sub((2026, 8), (2024, 10)), 22)
        self.assertEqual(sb.ym_sub((2024, 10), (2026, 8)), -22)
        self.assertEqual(sb.ym_sub((2026, 5), (2026, 5)), 0)

    def test_ym_seq_inclusive(self):
        seq = sb.ym_seq((2025, 11), (2026, 2))
        self.assertEqual(seq, [(2025, 11), (2025, 12),
                               (2026, 1), (2026, 2)])
        self.assertEqual(sb.ym_seq((2026, 5), (2026, 1)), [])

    def test_ym_parse_rejects_bad(self):
        for bad in ("2026-13", "2026-00", "202610", "2026", "x", ""):
            with self.assertRaises(sb.LedgerError):
                sb.ym_parse(bad)


# ------------------------------------------------------------ 解析与归一

class ParseTests(unittest.TestCase):
    def test_scheme_alias_cn_en(self):
        self.assertEqual(sb.norm_scheme("社保"), "social")
        self.assertEqual(sb.norm_scheme("五险"), "social")
        self.assertEqual(sb.norm_scheme("Social"), "social")
        self.assertEqual(sb.norm_scheme("公积金"), "fund")
        self.assertEqual(sb.norm_scheme("GJJ"), "fund")

    def test_scheme_unknown_rejected(self):
        with self.assertRaises(sb.LedgerError):
            sb.norm_scheme("税")

    def test_duplicate_month_scheme_exit2(self):
        path = write_ledger([
            ("2026-01", "fund", "5500", "660", "660", ""),
            ("2026-01", "fund", "5500", "660", "660", ""),
        ])
        rc, _, err = run_cli("report", path)
        self.assertEqual(rc, 2)
        self.assertIn("duplicate", err)

    def test_bad_header_exit2(self):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("date\tkg\tkcal\n2026-01\t70\t1500\n")
        rc, _, err = run_cli("report", path)
        self.assertEqual(rc, 2)
        self.assertIn("header", err)

    def test_negative_personal_exit2(self):
        path = write_ledger([("2026-01", "fund", "5500", "-1", "660", "")])
        rc, _, err = run_cli("report", path)
        self.assertEqual(rc, 2)
        self.assertIn("out of range", err)

    def test_unknown_scheme_row_exit2(self):
        path = write_ledger([("2026-01", "税", "5500", "660", "660", "")])
        rc, _, _ = run_cli("report", path)
        self.assertEqual(rc, 2)

    def test_bad_month_exit2(self):
        path = write_ledger([("2026-1", "fund", "5500", "660", "660", "")])
        rc, _, err = run_cli("report", path)
        self.assertEqual(rc, 2)
        self.assertIn("bad month", err)

    def test_missing_file_exit2(self):
        rc, _, err = run_cli("report", "/nonexistent/ledger.tsv")
        self.assertEqual(rc, 2)
        self.assertIn("ledger error", err)

    def test_as_of_before_first_exit2(self):
        rc, _, err = run_cli("report", SAMPLE, "--as-of", "2024-01")
        self.assertEqual(rc, 2)
        self.assertIn("as-of", err)

    def test_wage_file_bad_header_exit2(self):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("month\tmoney\n2026-01\t100\n")
        rc, _, err = run_cli("report", SAMPLE, "--wages", path)
        self.assertEqual(rc, 2)
        self.assertIn("wages header", err)

    def test_backfill_flag(self):
        row = sb.Row(sb.ym_parse("2026-05"), "social", 5500.0, 577.5, None,
                     "2026-07 补缴 5 月")
        self.assertTrue(row.backfill)
        row2 = sb.Row(sb.ym_parse("2026-06"), "fund", 15000.0, 1800, 1800,
                      "入职 B 公司")
        self.assertFalse(row2.backfill)


# ------------------------------------------------------------ 核心恒等式（构造已知真值）

def synth(shaved_months, full_months=3, salary="15000", shaved_base="5500",
          full_base="15000", gap=None, backfill=None):
    """构造账本：前 shaved_months 个月按 shaved_base，之后按 full_base。
    gap = 空档月序号（0 起），backfill = True 时该月 social 补缴、fund 缺席。"""
    ms = months("2024-10", shaved_months + full_months + (1 if gap is not None
                                                           else 0))
    rows = []
    for i, m in enumerate(ms):
        if gap is not None and i == gap:
            if backfill:
                rows.append((m, "social", shaved_base, "577.50", "",
                             "补缴"))
                # fund 缺席
            continue
        base = shaved_base if i < shaved_months else full_base
        sp = round(float(base) * 0.105, 2)
        fp = round(float(base) * 0.12, 2)
        rows.append((m, "social", base, "%.2f" % sp, "", ""))
        rows.append((m, "fund", base, "%.2f" % fp, "%.2f" % fp, ""))
    return rows, ms


class IdentityTests(unittest.TestCase):
    """构造已知真值的合成账本必须被精确复原。"""

    def setUp(self):
        # 19 个月按下限 5500 + 3 个月足额 15000，无断月
        rows, self.ms = synth(19, 3)
        self.led = write_ledger(rows)
        self.wag = write_wages([(m, "15000") for m in self.ms])

    def tearDown(self):
        for p in (self.led, self.wag):
            os.unlink(p)

    def test_shadow_identity(self):
        # 低报 19 个月：fund (15000-5500)*0.24=2280/月, pension 760/月
        # 足额 3 个月：0
        rc, out, _ = run_cli("compare", self.led, "--wages", self.wag)
        self.assertEqual(rc, 4)
        self.assertIn("43,320.00", out)      # fund 低报 19×2280
        self.assertIn("14,440.00", out)      # pension 低报 19×760
        self.assertIn("57,760.00", out)      # 合计
        self.assertIn("断缴缺席（整月无行，一分没进）: 0.00", out)

    def test_shadow_decomposition(self):
        rc, out, _ = run_cli("validate", self.led, "--wages", self.wag)
        self.assertEqual(rc, 0)
        self.assertIn("fund 暗折分解恒等: 43320.00 == 43320.00 + 0.00",
                      out)

    def test_two_world_difference(self):
        # 足额世界 fund = 22×15000×0.24 = 79,200；账本世界 = 19×5500×0.24
        # + 3×15000×0.24 = 25,080 + 10,800 = 35,880；差 43,320
        rc, out, _ = run_cli("compare", self.led, "--wages", self.wag)
        self.assertIn("79,200.00", out)
        self.assertIn("35,880.00", out)


class SolveTests(unittest.TestCase):
    """base 列留空时按 personal÷个人比例反解。"""

    def test_solve_base_and_company(self):
        rows = [("2026-01", "fund", "", "660.00", "", ""),
                ("2026-02", "fund", "", "660.00", "", ""),
                ("2026-03", "fund", "", "660.00", "", ""),
                ("2026-04", "fund", "", "660.00", "", ""),
                ("2026-05", "fund", "", "660.00", "", ""),
                ("2026-06", "fund", "", "660.00", "", "")]
        led = write_ledger(rows)
        wag = write_wages([(m, "15000") for m in months("2026-01", 6)])
        rc, out, _ = run_cli("audit", led, "--wages", wag)
        self.assertEqual(rc, 4)
        self.assertIn("base 5,500.00", out)
        self.assertIn("ratio 0.3667", out)
        rc, out, _ = run_cli("validate", led, "--wages", wag)
        self.assertIn("基数反解行 6", out)
        # 公司列反解 5500×0.12=660，口径 OK
        self.assertIn("公积金公司缴额口径: OK", out)
        for p in (led, wag):
            os.unlink(p)

    def test_fund_company_override_changes_solve(self):
        rows = [("2026-0%d" % i, "fund", "", "275.00", "", "")
                for i in range(1, 7)]
        led = write_ledger(rows)
        wag = write_wages([("2026-0%d" % i, "10000") for i in
                           range(1, 7)])
        # --fund-personal 0.05: base = 275/0.05 = 5500, ratio 0.55 → SHAVED
        rc, out, _ = run_cli("audit", led, "--wages", wag,
                             "--fund-personal", "0.05")
        self.assertEqual(rc, 4)
        self.assertIn("base 5,500.00", out)
        self.assertIn("ratio 0.5500", out)
        for p in (led, wag):
            os.unlink(p)

    def test_company_mismatch_disclosed(self):
        rows = [("2026-0%d" % i, "fund", "5000", "600.00", "900.00", "")
                for i in range(1, 7)]
        led = write_ledger(rows)
        rc, out, _ = run_cli("validate", led)
        self.assertEqual(rc, 0)
        self.assertIn("口径不符 6 行", out)
        self.assertIn("--fund-company 覆盖", out)
        os.unlink(led)


class BandBoundaryTests(unittest.TestCase):
    def make(self, base, salary="10000"):
        rows = [("2026-0%d" % i, "fund", base, "660.00", "660.00", "")
                for i in range(1, 7)]
        led = write_ledger(rows)
        wag = write_wages([("2026-0%d" % i, salary) for i in range(1, 7)])
        return led, wag

    def test_ratio_exactly_floor_is_lag_not_shaved(self):
        led, wag = self.make("6000")  # 6000/10000 = 0.60 → LAG
        rc, out, _ = run_cli("audit", led, "--wages", wag)
        self.assertEqual(rc, 0)
        self.assertIn("LAG 合法滞后带", out)
        self.assertNotIn("SHAVED 不足额", out)
        for p in (led, wag):
            os.unlink(p)

    def test_ratio_just_below_floor_is_shaved(self):
        led, wag = self.make("5900")  # 0.59 → SHAVED
        rc, out, _ = run_cli("audit", led, "--wages", wag)
        self.assertEqual(rc, 4)
        self.assertIn("SHAVED 不足额", out)
        for p in (led, wag):
            os.unlink(p)

    def test_ratio_exactly_lag_line_is_full(self):
        led, wag = self.make("9000")  # 0.90 → FULL
        rc, out, _ = run_cli("audit", led, "--wages", wag)
        self.assertEqual(rc, 0)
        self.assertIn("FULL 口径内足额", out)
        self.assertNotIn("SHAVED 不足额", out)
        for p in (led, wag):
            os.unlink(p)

    def test_floor_pay_fingerprint_needs_floor_value(self):
        led, wag = self.make("5500", salary="15000")  # 0.3667
        rc, out, _ = run_cli("report", led, "--wages", wag)
        self.assertEqual(rc, 4)
        self.assertNotIn("FLOOR-PAY", out)
        rc, out, _ = run_cli("report", led, "--wages", wag,
                             "--floor-value", "5500")
        self.assertIn("FLOOR-PAY", out)
        self.assertIn("6 个月实缴基数 == 当地下限", out)
        for p in (led, wag):
            os.unlink(p)

    def test_lag_soft_money_not_lamped(self):
        # 双账本全程 ratio 0.75（LAG 滞后带）：少缴是真的但口径存疑——
        # 计入暗折总额，不当 SHADOW MONTHS 灯，audit exit 0
        rows = []
        for i in range(1, 7):
            m = "2026-0%d" % i
            rows.append((m, "social", "7500", "787.50", "", ""))
            rows.append((m, "fund", "7500", "900.00", "900.00", ""))
        led = write_ledger(rows)
        wag = write_wages([("2026-0%d" % i, "10000") for i in range(1, 7)])
        rc, out, _ = run_cli("compare", led, "--wages", wag)
        self.assertEqual(rc, 0)
        self.assertIn("滞后带少缴（LAG/FULL 月，上年月均口径下可能合法，"
                      "不当灯）: 4,800.00", out)
        self.assertIn("确凿暗折 0.00 未及一个月工资参照线", out)
        self.assertNotIn("LAMP", out)
        rc, out, _ = run_cli("audit", led, "--wages", wag)
        self.assertEqual(rc, 0)
        for p in (led, wag):
            os.unlink(p)

    def test_floor_pay_not_fired_when_wage_below_floor(self):
        # 工资本来就低于下限：按下限交是合法的，不是指纹
        led, wag = self.make("5500", salary="5000")
        rc, out, _ = run_cli("report", led, "--wages", wag,
                             "--floor-value", "5500")
        self.assertNotIn("FLOOR-PAY", out)
        for p in (led, wag):
            os.unlink(p)

    def test_lag_line_must_exceed_base_floor(self):
        led, wag = self.make("6000")
        rc, _, err = run_cli("audit", led, "--wages", wag,
                             "--base-floor", "0.9", "--lag-line", "0.6")
        self.assertEqual(rc, 2)
        for p in (led, wag):
            os.unlink(p)


# ------------------------------------------------------------ 连续账

class StreakTests(unittest.TestCase):
    def test_demo_streaks_two_schemes(self):
        rc, out, _ = run_cli("streak", SAMPLE)
        self.assertEqual(rc, 0)
        # fund: 19 连 + 断 2026-05 + 3 连
        self.assertIn("fund   ■■■■■■■■■■■■■■■■■■■·■■■", out)
        self.assertIn("social ■■■■■■■■■■■■■■■■■■■~■■■", out)
        self.assertIn("fund 断月: 2026-05", out)
        self.assertIn("social 断月: none", out)
        self.assertIn("strict 断点(缺行∪补缴): 2026-05", out)

    def test_demo_strict_vs_calendar(self):
        rows, ms = synth(19, 3, gap=19, backfill=True)
        led = write_ledger(rows)
        rc, out, _ = run_cli("streak", led)
        # social 补缴行: calendar 当前 4(含 20-23)，strict 当前 3
        self.assertIn("social", out)
        rc, out, _ = run_cli("streak", led, "--require", "3")
        self.assertIn("social: 已达成", out)
        os.unlink(led)

    def test_require_countdown(self):
        rc, out, _ = run_cli("streak", SAMPLE, "--require", "12")
        self.assertIn("fund: 还差 9 个月（当前 3），预计 2027-05 达成", out)
        self.assertIn("social: 已达成（当前 23）", out)

    def test_require_achieved_strict_differs(self):
        rc, out, _ = run_cli("streak", SAMPLE, "--require", "23")
        # calendar: social 23 达成; strict: 3 → 预计不同
        self.assertIn("social: 已达成（当前 23）", out)

    def test_no_require_hint(self):
        rc, out, _ = run_cli("streak", SAMPLE)
        self.assertIn("--require N 可加资格倒计时", out)

    def test_strict_flag_switches_countdown(self):
        rc, out, _ = run_cli("streak", SAMPLE, "--require", "23",
                             "--strict")
        self.assertIn("还差 20 个月（当前 3）", out)

    def test_unit_achievement_gap_resets(self):
        args = type("A", (), {})()
        rows, _ = synth(19, 3, gap=19, backfill=True)
        led = write_ledger(rows)
        parsed = sb.load_ledger(led)
        args.salary = 15000
        args.wages = None
        args.wages_path = None
        args.as_of = None
        args.social_personal = sb.SOCIAL_PERSONAL
        args.fund_personal = sb.FUND_PERSONAL
        args.fund_company = sb.FUND_COMPANY
        args.pension = sb.PENSION
        args.base_floor = sb.BAND_FLOOR
        args.lag_line = sb.BAND_LAG
        args.floor_value = None
        f = sb.Facts(parsed, args)
        # 无断档: fund streak 3 → need 9 → last(2026-08)+9 = 2027-05
        ach, done = f.achievement("fund", 12)
        self.assertEqual((ach, done), ((2027, 5), False))
        # 断档 1 个月: 连续清零，从续缴月起整段 require → last+1+12
        ach2, done2 = f.achievement("fund", 12, gap=1)
        self.assertEqual((ach2, done2), ((2027, 9), False))
        # 断档 0 但已达成
        ach3, done3 = f.achievement("fund", 3)
        self.assertEqual((ach3, done3), (f.last, True))
        os.unlink(led)

    def test_gap_month_effective_base_zero(self):
        rows, ms = synth(2, 2, gap=2, backfill=False)
        led = write_ledger(rows)
        args = type("A", (), {})()
        args.salary = 15000
        args.wages = None
        args.wages_path = None
        args.as_of = None
        args.social_personal = sb.SOCIAL_PERSONAL
        args.fund_personal = sb.FUND_PERSONAL
        args.fund_company = sb.FUND_COMPANY
        args.pension = sb.PENSION
        args.base_floor = sb.BAND_FLOOR
        args.lag_line = sb.BAND_LAG
        args.floor_value = None
        f = sb.Facts(sb.load_ledger(led), args)
        # 断缴月 fund effective_base = 0，暗折 = 15000×0.24 = 3600
        self.assertEqual(f.effective_base("fund", (2024, 12)), 0.0)
        self.assertEqual(round(f.shadow("fund", (2024, 12)), 2), 3600.0)
        os.unlink(led)


# ------------------------------------------------------------ 反事实

class SimulateTests(unittest.TestCase):
    def test_quit_pushback(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "quit", "1",
                             "--require", "12")
        self.assertEqual(rc, 0)
        self.assertIn("原节奏 2027-05 达成 → 断档后 2027-09 达成，"
                      "推迟 4 个月", out)
        self.assertIn("医保：断档月次月起多数城市停止报销", out)

    def test_quit_strict_pushback(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "quit", "2",
                             "--require", "60", "--strict")
        self.assertEqual(rc, 0)
        # strict: social 当前 3 → 原 2031-05；断档后 last+2+60 = 2031-10
        self.assertIn("原节奏 2031-05 达成 → 断档后 2031-10 达成，"
                      "推迟 5 个月", out)

    def test_quit_no_require(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "quit", "1")
        self.assertEqual(rc, 0)
        self.assertIn("断档后月历口径归零重计", out)
        self.assertIn("--require N 可加资格倒计时推演", out)

    def test_quit_needs_sub(self):
        rc, _, _ = run_cli("simulate", SAMPLE)
        self.assertEqual(rc, 2)

    def test_bridge_no_pushback(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "bridge", "1",
                             "--require", "12")
        self.assertEqual(rc, 0)
        self.assertIn("预计 2027-05 达成——架桥后月历口径不推迟", out)
        self.assertIn("政策永远赢", out)
        self.assertIn("本件不发明你的钱", out)

    def test_quit_zero_gap(self):
        rc, out, _ = run_cli("simulate", SAMPLE, "quit", "0",
                             "--require", "12")
        self.assertEqual(rc, 0)
        self.assertIn("推迟 0 个月", out)  # gap 0 = 无断档，节奏不变


# ------------------------------------------------------------ as-of 与薄账

class AsOfTests(unittest.TestCase):
    def test_as_of_2025_12(self):
        rc, out, _ = run_cli("report", SAMPLE, "--wages", WAGES,
                             "--as-of", "2025-12")
        self.assertEqual(rc, 4)
        self.assertIn("span: 2024-10 .. 2025-12 (15 months)", out)
        self.assertIn("45,600.00", out)   # 15×3040
        self.assertIn("3.04 个月工资", out)
        self.assertNotIn("2026-05", out.split("\n")[1])

    def test_as_of_2026_04_no_gap(self):
        rc, out, _ = run_cli("report", SAMPLE, "--wages", WAGES,
                             "--as-of", "2026-04")
        self.assertEqual(rc, 4)
        self.assertIn("(19 months)", out)
        self.assertIn("57,760.00", out)   # 19×3040
        self.assertIn("3.85 个月工资", out)
        self.assertIn("fund 断月: none", out)

    def test_as_of_wages_truncated(self):
        rc, out, _ = run_cli("compare", SAMPLE, "--wages", WAGES,
                             "--as-of", "2025-12")
        self.assertIn("45,600.00", out)


class ThinTests(unittest.TestCase):
    def make_thin(self):
        rows, ms = synth(3, 1)  # 4 个月 < 6
        led = write_ledger(rows)
        wag = write_wages([(m, "15000") for m in ms])
        return led, wag

    def test_thin_report_exit3(self):
        led, wag = self.make_thin()
        rc, out, _ = run_cli("report", led, "--wages", wag)
        self.assertEqual(rc, 3)
        self.assertIn("thin ledger", out)
        self.assertIn("SHAVED", out)  # 灯照印，判级拒绝
        for p in (led, wag):
            os.unlink(p)

    def test_thin_audit_exit3(self):
        led, wag = self.make_thin()
        rc, out, _ = run_cli("audit", led, "--wages", wag)
        self.assertEqual(rc, 3)
        self.assertIn("DECLINED", out)
        for p in (led, wag):
            os.unlink(p)

    def test_thin_compare_exit3(self):
        led, wag = self.make_thin()
        rc, out, _ = run_cli("compare", led, "--wages", wag)
        self.assertEqual(rc, 3)
        self.assertIn("算术照出", out)
        # 3 个低报月 × 3040 = 9,120，无缺席
        self.assertIn("9,120.00", out)
        for p in (led, wag):
            os.unlink(p)

    def test_thin_streak_still_works(self):
        led, wag = self.make_thin()
        rc, out, _ = run_cli("streak", led)
        self.assertEqual(rc, 0)
        self.assertIn("月历", out)
        for p in (led, wag):
            os.unlink(p)

    def test_thin_validate_still_works(self):
        led, wag = self.make_thin()
        rc, out, _ = run_cli("validate", led)
        self.assertEqual(rc, 0)
        self.assertIn("ledger OK", out)
        for p in (led, wag):
            os.unlink(p)


class NoRefTests(unittest.TestCase):
    def test_report_without_wage_ref(self):
        rc, out, _ = run_cli("report", SAMPLE)
        self.assertIn("基数审计: skipped", out)
        self.assertIn("没有参照就没有水位", out)
        # 连续账与断月是纯月历算术，照出
        self.assertIn("fund 断月: 2026-05", out)

    def test_audit_without_wage_ref_exit3(self):
        rc, out, _ = run_cli("audit", SAMPLE)
        self.assertEqual(rc, 3)
        self.assertIn("declined", out)
        self.assertIn("只出基数表", out)
        self.assertIn("base 5,500.00", out)  # 基数表照出

    def test_compare_without_wage_ref_exit3(self):
        rc, out, _ = run_cli("compare", SAMPLE)
        self.assertEqual(rc, 3)
        self.assertIn("declined", out)

    def test_salary_scalar_fallback(self):
        rc, out, _ = run_cli("compare", SAMPLE, "--salary", "15000")
        self.assertEqual(rc, 4)
        self.assertIn("62,120.00", out)
        self.assertIn("--salary 15000.00 (flat)", out)


# ------------------------------------------------------------ 工资逐月参照

class WageTests(unittest.TestCase):
    def test_per_month_wage_overrides(self):
        # 全程 15000，除第 4 月为 30000：该月 B 公司基数 15000 → ratio 0.5
        rows, ms = synth(0, 7)  # 7 个月全足额（> 6 个月薄账线）
        led = write_ledger(rows)
        wag = write_wages([(m, "30000" if m == ms[3] else "15000")
                           for m in ms])
        rc, out, _ = run_cli("audit", led, "--wages", wag)
        self.assertEqual(rc, 4)
        self.assertIn("ratio 0.5000", out)
        for p in (led, wag):
            os.unlink(p)

    def test_absent_wage_month_no_shadow(self):
        rows, ms = synth(2, 1)
        led = write_ledger(rows)
        wag = write_wages([(ms[0], "15000"), (ms[1], "15000")])  # 缺 ms[2]
        rc, out, _ = run_cli("compare", led, "--wages", wag)
        # 2 个有参照的低报月: 2×3040 = 6080；第 3 月无参照不发明
        self.assertIn("6,080.00", out)
        for p in (led, wag):
            os.unlink(p)


# ------------------------------------------------------------ 样例叙事

class SampleStoryTests(unittest.TestCase):
    def test_report_full_story(self):
        rc, out, _ = run_cli("report", SAMPLE, "--wages", WAGES,
                             "--require", "12", "--floor-value", "5500")
        self.assertEqual(rc, 4)
        self.assertIn("span: 2024-10 .. 2026-08 (23 months)", out)
        self.assertIn("Σ个人 16,275.00", out)          # social
        self.assertIn("17,940.00  + Σ公司 17,940.00", out)  # fund
        self.assertIn("暗折: 公积金 46,920.00（低报 43,320.00 + "
                      "断缴缺席 3,600.00） + 养老个人账户 15,200.00 "
                      "= 62,120.00 ≈ 4.14 个月工资", out)
        self.assertIn("LAMP SHAVED — 最低缴费水位 0.3667 @ 2024-10 social",
                      out)
        self.assertIn("LAMP FLOOR-PAY — 39 个月实缴基数 == 当地下限", out)
        self.assertIn("LAMP SHADOW MONTHS — 确凿暗折 62,120.00 ≥ "
                      "1 个月工资——你被偷走了 4.14 个月的工资", out)
        self.assertIn("还差 9 个月，按月历连续缴预计 2027-05 达成", out)
        self.assertIn("strict 口径当前 3（断点: 2026-05）", out)

    def test_compare_story(self):
        rc, out, _ = run_cli("compare", SAMPLE, "--wages", WAGES)
        self.assertEqual(rc, 4)
        self.assertIn("social 账本世界 12,400.00   足额世界 27,600.00"
                      "   差 15,200.00", out)
        self.assertIn("fund   账本世界 35,880.00   足额世界 82,800.00"
                      "   差 46,920.00", out)
        self.assertIn("低报暗折（SHAVED 月，基数缩水但月月在缴）: 58,520.00",
                      out)
        self.assertIn("断缴缺席（整月无行，一分没进）: 3,600.00", out)
        self.assertIn("合计 62,120.00", out)
        self.assertIn("LAMP SHADOW MONTHS — 确凿暗折 62,120.00 ≈ "
                      "4.14 个月工资", out)

    def test_audit_story(self):
        rc, out, _ = run_cli("audit", SAMPLE, "--wages", WAGES,
                             "--floor-value", "5500")
        self.assertEqual(rc, 4)
        self.assertIn("2024-10..2026-05 (20m)   base 5,500.00"
                      "  ratio 0.3667  SHAVED 不足额(红灯)"
                      "  FLOOR-PAY指纹  暗折 760.00/月", out)
        self.assertIn("2026-05..2026-05 (1m)   断月（无行）", out)
        self.assertIn("暗折 2,280.00/月", out)

    def test_validate_story(self):
        rc, out, _ = run_cli("validate", SAMPLE, "--wages", WAGES)
        self.assertEqual(rc, 0)
        self.assertIn("fund 暗折分解恒等: 46920.00 == 43320.00 + 3600.00",
                      out)
        self.assertIn("ledger OK", out)

    def test_shaved_water_line_translation(self):
        # 5500/15000 = 0.3667 —— 「公司在按 36.7% 的你交社保」
        args = type("A", (), {})()
        args.salary = 15000
        args.wages = None
        args.wages_path = None
        args.as_of = None
        args.social_personal = sb.SOCIAL_PERSONAL
        args.fund_personal = sb.FUND_PERSONAL
        args.fund_company = sb.FUND_COMPANY
        args.pension = sb.PENSION
        args.base_floor = sb.BAND_FLOOR
        args.lag_line = sb.BAND_LAG
        args.floor_value = None
        f = sb.Facts(sb.load_ledger(SAMPLE), args)
        band, r = f.band("fund", sb.ym_parse("2024-10"))
        self.assertEqual(band, "SHAVED")
        self.assertAlmostEqual(r, 5500.0 / 15000.0, places=6)


# ------------------------------------------------------------ 可复现与隐私

class ReproTests(unittest.TestCase):
    def test_byte_identical(self):
        argv = ["report", SAMPLE, "--wages", WAGES, "--require", "12",
                "--floor-value", "5500"]
        _, out1, _ = run_cli(*argv)
        _, out2, _ = run_cli(*argv)
        self.assertEqual(out1, out2)

    def test_basename_only(self):
        rc, out, _ = run_cli("report", SAMPLE, "--wages", WAGES)
        self.assertIn("ledger: ledger.tsv", out)
        self.assertIn("payroll wages.tsv", out)
        self.assertNotIn(ROOT, out)
        self.assertNotIn("/examples/", out)

    def test_all_commands_reproducible(self):
        for argv in (
            ["audit", SAMPLE, "--wages", WAGES],
            ["streak", SAMPLE, "--require", "12"],
            ["compare", SAMPLE, "--wages", WAGES],
            ["validate", SAMPLE],
            ["simulate", SAMPLE, "quit", "1", "--require", "12"],
            ["simulate", SAMPLE, "bridge", "2"],
        ):
            _, o1, _ = run_cli(*argv)
            _, o2, _ = run_cli(*argv)
            self.assertEqual(o1, o2, msg="not byte-identical: %s" % argv)


if __name__ == "__main__":
    unittest.main()
