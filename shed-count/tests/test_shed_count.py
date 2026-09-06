# -*- coding: utf-8 -*-
"""秋毫 · Shed Count 验收测试。

间隔归一（根/天 = 根数÷距上次同口径天数）、GAP 断记剔除（恰 45 天入池 /
46 天剔除）、绝对判级恰线（恰 100=OK 宁可少亮灯）、相对基线（头 90 天
中位对率，<3 对不装知道）、干预三庭（起效潜伏窗外才开 after 窗 /
RESPONDING 含 0.30 边界 / WORSE 与 REBOUND 恰 0.15 不亮 / 同药事件在场
判 VOID / 潜伏期混药 CONFOUNDED 回归）、口径门（wash 与 comb 永不混算、
表外口径点名不入统计）、别名归一幂等、间隔与池化双算法、exit code 行为
真值与 as-of 确定性（缺省=账本最大日期，同账同 as-of 逐字节一致）全部钉死。

Exit codes: 0 绿 · 2 账本/参数损坏 · 3 样本太薄/统计拒绝 · 4 超生理线红灯。
"""

import datetime as dt
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
IDEA = os.path.dirname(HERE)
CLI = os.path.join(IDEA, "shed_count.py")
EXAMPLES = os.path.join(IDEA, "examples", "sheds.tsv")

_spec = importlib.util.spec_from_file_location("shed_count", CLI)
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

D = dt.date.fromisoformat


def go(*args):
    """跑 CLI 子进程，返回 (stdout, stderr, exit_code)。"""
    r = subprocess.run([sys.executable, CLI] + list(args),
                       capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode


def write_ledger(rows, tmpdir, name="sheds.tsv"):
    """rows: (date, kind, count, event, note) 五元组列表。"""
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("date\tkind\tcount\tevent\tnote\n")
        for r in rows:
            cells = list(r) + [""] * (5 - len(r))
            f.write("\t".join(str(c) for c in cells) + "\n")
    return path


def wseq(start, counts, step=1, kind="wash", event="", note=""):
    """等间隔计数行：返回 [(date, kind, count, event, note), ...]。"""
    out = []
    d = D(start) if isinstance(start, str) else start
    for i, c in enumerate(counts):
        out.append(((d + dt.timedelta(days=i * step)).isoformat(), kind,
                    str(c), event if i == 0 and event else "", note))
    return out


# ------------------------------------------------------------ fixture 级
class TestFixture(unittest.TestCase):
    def test_report_red_exit4(self):
        out, err, code = go("report", EXAMPLES)
        self.assertEqual(code, 4)
        self.assertIn("SHED", out)
        self.assertIn("101.3", out)

    def test_report_pinned_literals(self):
        out, _, _ = go("report", EXAMPLES)
        self.assertIn("全期       OK     91.8", out)
        self.assertIn("近30d     SHED   101.3", out)
        self.assertIn("基线     127.5", out)
        self.assertIn("近窗/基线 = 0.79", out)
        self.assertIn("as-of 2026-07-24", out)
        self.assertIn("覆盖率 83.4%", out)
        self.assertIn("wash 对 143", out)
        self.assertIn("comb 行 3", out)
        self.assertIn("干预事件 3", out)

    def test_report_anchors_self_no_clock(self):
        out, _, _ = go("report", EXAMPLES)
        self.assertIn("缺省=账本最大日期", out)
        self.assertNotIn("examples/", out)          # 只打印 basename

    def test_asof_default_equals_explicit_max(self):
        a, _, ca = go("report", EXAMPLES)
        b, _, cb = go("report", EXAMPLES, "--as-of", "2026-07-24")
        self.assertEqual(ca, 4)
        self.assertEqual(cb, 4)
        self.assertEqual(a, b)                      # 逐字节一致

    def test_asof_truncation_turns_green(self):
        out, _, code = go("report", EXAMPLES, "--as-of", "2025-12-31")
        self.assertEqual(code, 0)                   # 12月还是 ~73 OK
        self.assertIn("近30d     OK", out)
        self.assertNotIn("REBOUND", out)            # 2026 的停药事件不在场

    def test_asof_excludes_future_rows(self):
        # 截断回放：2025-05-11 时第二行还没写下——排除，不是账坏
        out, _, code = go("report", EXAMPLES, "--as-of", "2025-05-11")
        self.assertEqual(code, 3)                      # 只有首行，统计拒绝
        self.assertIn("as-of 2025-05-11", out)
        self.assertNotIn("252", out)                   # 05-12 的行不在场

    def test_intervention_three_courts(self):
        out, _, code = go("intervention", EXAMPLES)
        self.assertEqual(code, 0)
        self.assertIn("RESPONDING", out)
        self.assertIn("drop 43.2%", out)
        self.assertIn("CONFOUNDED 窗含 start finasteride", out)
        self.assertIn("判决 VOID — after 窗含同药 stop", out)
        self.assertIn("CONFOUNDED 窗含 start minoxidil", out)
        self.assertIn("REBOUND", out)
        self.assertIn("rise 23.9%", out)
        self.assertIn("反弹线 15%，恰线不亮", out)

    def test_lag_override_shifts_after_window(self):
        a, _, _ = go("intervention", EXAMPLES)
        b, _, code = go("intervention", EXAMPLES, "--lag", "minoxidil=60")
        self.assertEqual(code, 0)
        self.assertIn("after  2025-08-13", b)       # 06-14 + 60d
        self.assertNotEqual(a, b)
        c, _, _ = go("intervention", EXAMPLES, "--lag", "米诺地尔=60")
        self.assertEqual(c, b)                      # 中英别名同一翻案

    def test_rate_exit0_and_gap_tagged(self):
        out, _, code = go("rate", EXAMPLES)
        self.assertEqual(code, 0)
        self.assertIn("2026-03-30    231    72     3.2   GAP", out)
        self.assertIn("comb（3 行，2 对）", out)
        self.assertIn("池化 91.8 根/天（33779 根 / 368 天，142 对）", out)

    def test_validate_green_on_fixture(self):
        out, _, code = go("validate", EXAMPLES)
        self.assertEqual(code, 0)
        self.assertIn("✓ 间隔双算法 timedelta==ordinal × 143 对", out)
        self.assertIn("✓ 池化双算法 累加==过滤求和 × 3 窗", out)
        self.assertIn("✓ GAP 剔除完备", out)
        self.assertIn("✓ 口径门 147 数据行不重不漏", out)
        self.assertIn("✓ 判级恰线", out)
        self.assertIn("✓ as-of 确定性", out)
        self.assertIn("✓ 分母守恒 观测天 368 ≤ 跨度 441", out)

    def test_season_fixture(self):
        out, _, code = go("season", EXAMPLES)
        self.assertEqual(code, 0)
        self.assertIn("2025-09     77.7", out)
        self.assertIn("SEASON", out)
        self.assertIn("同月同比 05 月：2025 127.5 → 2026 85.3（-33.0%）", out)
        out2, _, code2 = go("season", EXAMPLES, "--season-months", "5")
        self.assertEqual(code2, 0)
        self.assertEqual(out2.count("SEASON"), 2)   # 2025-05 与 2026-05
        self.assertIn("2026-05", out2)

    def test_determinism_two_runs_byte_identical(self):
        a, _, _ = go("report", EXAMPLES)
        b, _, _ = go("report", EXAMPLES)
        self.assertEqual(a, b)

    def test_missing_ledger_exit2(self):
        _, err, code = go("report", "/nonexistent/sheds.tsv")
        self.assertEqual(code, 2)
        self.assertIn("ledger not found", err)


# ------------------------------------------------------------ 判级与归一
class TestTiersAndRates(unittest.TestCase):
    def setUp(self):
        self._saved = (sc.SHED_LINE, sc.FLOOD_LINE, sc.ELEVATE_LINE)

    def tearDown(self):
        sc.SHED_LINE, sc.FLOOD_LINE, sc.ELEVATE_LINE = self._saved

    def test_abs_tier_boundary_at_line_is_ok(self):
        sc.SHED_LINE, sc.FLOOD_LINE = 100.0, 200.0
        self.assertEqual(sc.abs_tier(100.0), "OK")       # 恰线=OK 宁可少亮灯
        self.assertEqual(sc.abs_tier(100.0 + 1e-6), "SHED")
        self.assertEqual(sc.abs_tier(150.0), "SHED")
        self.assertEqual(sc.abs_tier(200.0), "SHED")     # 恰急性线仍 SHED
        self.assertEqual(sc.abs_tier(200.0 + 1e-6), "FLOOD")
        self.assertIsNone(sc.abs_tier(None))

    def test_gap_dual_algorithm(self):
        d1, d2 = D("2025-05-10"), D("2025-07-24")
        self.assertEqual(sc.gap_days(d2, d1), sc.gap_days_alt(d2, d1))
        self.assertEqual(sc.gap_days(d2, d1), 75)

    def test_normalization_per_day(self):
        rows = [dict(date=D("2025-05-10"), count=100, note=""),
                dict(date=D("2025-05-12"), count=240, note="")]
        pairs = sc.build_pairs(rows, 45)
        self.assertEqual(len(pairs), 1)
        self.assertAlmostEqual(pairs[0]["rate"], 120.0)   # 240/2

    def test_gap_cap_boundary_45_in_46_out(self):
        rows = [dict(date=D("2025-05-01"), count=100, note=""),
                dict(date=D("2025-06-15"), count=100, note="")]
        pairs = sc.build_pairs(rows, 45)
        self.assertNotIn("GAP", pairs[0]["tags"])         # 恰 45 入池
        rows2 = [rows[0], dict(date=D("2025-06-16"), count=100, note="")]
        pairs2 = sc.build_pairs(rows2, 45)
        self.assertIn("GAP", pairs2[0]["tags"])           # 46 剔除
        self.assertEqual(sc.pool(pairs2)["days"], 0)      # 不进分母

    def test_pool_excludes_gap_and_windows_by_wash_date(self):
        rows = [dict(date=D("2025-01-01"), count=100, note=""),
                dict(date=D("2025-01-02"), count=100, note=""),
                dict(date=D("2025-01-31"), count=100, note=""),
                dict(date=D("2025-02-01"), count=200, note="")]
        pairs = sc.build_pairs(rows, 45)                  # 31d 间隔入池
        p = sc.pool(pairs, lo=D("2025-02-01"))
        self.assertEqual(p["counts"], 200)
        self.assertEqual(p["days"], 1)
        self.assertAlmostEqual(p["rate"], 200.0)

    def test_pool_dual_algorithm_identical(self):
        ld = sc.load_ledger(EXAMPLES, D("2026-07-24"))
        pairs = sc.build_pairs(ld["kinds"]["wash"], 45)
        for lo, hi in ((None, None), (D("2026-04-26"), D("2026-07-24")),
                       (D("2026-06-25"), D("2026-07-24"))):
            a = sc.pool(pairs, lo=lo, hi=hi)
            b = sc.pool_alt(pairs, lo=lo, hi=hi)
            self.assertEqual(a["counts"], b["counts"])
            self.assertEqual(a["days"], b["days"])
            if a["rate"] is not None:
                self.assertAlmostEqual(a["rate"], b["rate"], places=12)

    def test_baseline_needs_three_pairs(self):
        rows = wseq("2025-05-01", [100, 100], 1)
        with tempfile.TemporaryDirectory() as t:
            path = write_ledger(rows, t)
            ld = sc.load_ledger(path, D("2025-05-02"))
            pairs = sc.build_pairs(ld["kinds"]["wash"], 45)
            self.assertIsNone(sc.baseline_of(pairs, ld["min_date"], 90))
            rows2 = wseq("2025-05-01", [100, 100, 100, 100], 1)
            path2 = write_ledger(rows2, t, "b.tsv")
            ld2 = sc.load_ledger(path2, D("2025-05-04"))
            pairs2 = sc.build_pairs(ld2["kinds"]["wash"], 45)
            self.assertAlmostEqual(
                sc.baseline_of(pairs2, ld2["min_date"], 90), 100.0)


# ------------------------------------------------------------ 干预三庭
def build_court(tmpdir, name, after_rate, event, before=100, extra=()):
    """标准开庭构造（日历链条：每段 ≤46 天，唯一长段被 GAP 剔除）。

    账本语义：count = 本行与其前一行之间掉的根数，rate = count/gap。
      X-3..X-1  每天 before 根（gap 1）      → before 窗两对，池=before
      X         事件行
      X+45      before 根                    → 与 X-1 的 gap=46 → GAP 剔除
      X+80      after_rate×35 根             → gap 35 落在潜伏期不入窗
      X+90      after_rate×10 根             → gap 10，rate=after_rate，入窗
      X+91      after_rate 根                → gap 1，rate=after_rate，入窗
    after 池 = (10·r + r) / (10+1) = r，分毫不差。
    """
    X = "2025-01-11"
    rows = wseq("2025-01-08", [before] * 3, 1)
    rows.append((X, "", "", event, ""))
    rows.append(("2025-02-25", "wash", str(before), "", ""))
    rows.append(("2025-04-01", "wash", str(int(after_rate * 35)), "", ""))
    rows.append(("2025-04-11", "wash", str(int(after_rate * 10)), "", ""))
    rows.append(("2025-04-12", "wash", str(after_rate), "", ""))
    rows += list(extra)
    return write_ledger(rows, tmpdir, name)


class TestIntervention(unittest.TestCase):
    def setUp(self):
        self._saved = (sc.RESPOND_LINE, sc.WORSE_LINE, sc.REBOUND_LINE)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        sc.RESPOND_LINE, sc.WORSE_LINE, sc.REBOUND_LINE = self._saved
        self.tmp.cleanup()

    def test_responding_at_exact_boundary(self):
        sc.RESPOND_LINE = 0.30
        path = build_court(self.tmp.name, "a.tsv", 70, "start minoxidil")
        out, _, code = go("intervention", path)
        self.assertEqual(code, 0)
        self.assertIn("RESPONDING", out)                  # drop 0.30 含边界
        self.assertIn("after  2025-04-11..2025-07-09：70.0 根/天", out)
        self.assertIn("潜伏窗 90d", out)

    def test_nochange_just_below_boundary(self):
        sc.RESPOND_LINE = 0.30
        path = build_court(self.tmp.name, "a.tsv", 71, "start minoxidil")
        out, _, _ = go("intervention", path)
        self.assertIn("NO-CHANGE", out)                   # drop 0.29
        self.assertNotIn("RESPONDING", out)

    def test_latent_window_keeps_early_data_out(self):
        # 潜伏期内(第10天)就降速也不算数：after 窗从 X+90 起才开
        rows = wseq("2025-01-08", [100, 100, 100], 1)
        rows.append(("2025-01-11", "", "", "start minoxidil", ""))
        rows += wseq("2025-01-21", [10, 11], 1)           # 潜伏期内假下降
        rows.append(("2025-02-25", "wash", "100", "", ""))
        rows.append(("2025-04-01", "wash", "2450", "", ""))
        rows.append(("2025-04-11", "wash", "700", "", ""))
        rows.append(("2025-04-12", "wash", "70", "", ""))
        path = write_ledger(rows, self.tmp.name)
        out, _, _ = go("intervention", path)
        self.assertIn("RESPONDING", out)                  # 只看 X+90 之后
        self.assertIn("after  2025-04-11..2025-07-09：70.0", out)

    def test_worse_boundary_at_line_not_lit(self):
        sc.WORSE_LINE = 0.15
        path = build_court(self.tmp.name, "a.tsv", 115, "start minoxidil")
        out, _, _ = go("intervention", path)
        self.assertIn("NO-CHANGE", out)                   # rise 恰 0.15 不亮
        path2 = build_court(self.tmp.name, "b.tsv", 116, "start minoxidil")
        out2, _, _ = go("intervention", path2)
        self.assertIn("WORSE", out2)                      # rise 0.16 亮

    def test_rebound_boundary_at_line_not_lit(self):
        sc.REBOUND_LINE = 0.15
        path = build_court(self.tmp.name, "a.tsv", 115, "stop finasteride")
        out, _, _ = go("intervention", path)
        self.assertIn("NO-CHANGE", out)
        path2 = build_court(self.tmp.name, "b.tsv", 116, "stop finasteride")
        out2, _, _ = go("intervention", path2)
        self.assertIn("REBOUND", out2)

    def test_void_same_drug_stop_inside_after(self):
        path = build_court(self.tmp.name, "a.tsv", 70, "start finasteride",
                           extra=[("2025-04-20", "", "", "stop finasteride",
                                   "中途停")])
        out, _, _ = go("intervention", path)
        self.assertIn("判决 VOID — after 窗含同药 stop", out)
        self.assertIn("药未全程在场", out)
        self.assertIn("before 2024-10-13", out)           # 算术照出

    def test_confounded_other_drug_in_latent_window(self):
        # 回归：混药常在潜伏期内开始，只扫两窗会漏——从事件日扫到窗尾
        path = build_court(
            self.tmp.name, "a.tsv", 70, "start minoxidil",
            extra=[("2025-01-25", "", "", "start finasteride", "潜伏期加药")])
        out, _, _ = go("intervention", path)
        self.assertIn("CONFOUNDED 窗含 start finasteride", out)
        self.assertIn("RESPONDING", out)                  # 算术成立但功劳存疑

    def test_void_same_drug_start_inside_before(self):
        rows = [("2024-12-01", "wash", "100", "", "")]
        rows.append(("2024-12-21", "", "", "start finasteride", ""))  # 窗内既有
        rows += wseq("2025-01-08", [100, 100, 100], 1)
        rows.append(("2025-01-11", "", "", "start finasteride", "重开"))
        rows.append(("2025-02-25", "wash", "100", "", ""))
        rows.append(("2025-04-01", "wash", "2450", "", ""))
        rows.append(("2025-04-11", "wash", "700", "", ""))
        rows.append(("2025-04-12", "wash", "70", "", ""))
        path = write_ledger(rows, self.tmp.name)
        out, _, _ = go("intervention", path)
        self.assertIn("基线不干净", out)

    def test_lag_unknown_drug(self):
        path = build_court(self.tmp.name, "a.tsv", 70, "start 生发梳")
        out, _, code = go("intervention", path)
        self.assertEqual(code, 0)
        self.assertIn("LAG-UNKNOWN", out)                 # 不装知道潜伏窗
        self.assertIn("--lag 可翻案", out)

    def test_insufficient_window_thin(self):
        rows = wseq("2025-01-08", [100, 100, 100], 1)
        rows.append(("2025-01-11", "", "", "start minoxidil", ""))
        rows.append(("2025-02-25", "wash", "100", "", ""))
        rows.append(("2025-04-11", "wash", "70", "", ""))  # after 仅 1 对
        path = write_ledger(rows, self.tmp.name)
        out, _, code = go("intervention", path)
        self.assertEqual(code, 3)
        self.assertIn("INSUFFICIENT-WINDOW", out)


# ------------------------------------------------------------ 账坏与别名
class TestBrokenLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_date_kind_exit2(self):
        rows = wseq("2025-01-01", [100, 100], 1)
        rows.append(("2025-01-02", "wash", "120", "", ""))
        path = write_ledger(rows, self.tmp.name)
        _, err, code = go("report", path)
        self.assertEqual(code, 2)
        self.assertIn("duplicate", err)

    def test_negative_count_exit2(self):
        rows = wseq("2025-01-01", [100, -5], 1)
        path = write_ledger(rows, self.tmp.name)
        _, err, code = go("report", path)
        self.assertEqual(code, 2)
        self.assertIn("negative", err)

    def test_noninteger_count_exit2(self):
        rows = wseq("2025-01-01", [100, "12.5"], 1)
        path = write_ledger(rows, self.tmp.name)
        _, _, code = go("report", path)
        self.assertEqual(code, 2)

    def test_bad_date_exit2(self):
        rows = [("2025-13-01", "wash", "100", "", "")]
        path = write_ledger(rows, self.tmp.name)
        _, _, code = go("report", path)
        self.assertEqual(code, 2)

    def test_missing_date_exit2(self):
        rows = [("", "wash", "100", "", "")]
        path = write_ledger(rows, self.tmp.name)
        _, _, code = go("report", path)
        self.assertEqual(code, 2)

    def test_count_without_kind_exit2(self):
        rows = [("2025-01-01", "", "100", "", "孤儿根数")]
        path = write_ledger(rows, self.tmp.name)
        _, err, code = go("report", path)
        self.assertEqual(code, 2)
        self.assertIn("count without kind", err)

    def test_bad_event_verb_exit2(self):
        rows = [("2025-01-01", "", "", "refill minoxidil", "")]
        path = write_ledger(rows, self.tmp.name)
        _, err, code = go("report", path)
        self.assertEqual(code, 2)
        self.assertIn("bad event", err)

    def test_empty_ledger_thin(self):
        path = os.path.join(self.tmp.name, "e.tsv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("date\tkind\tcount\tevent\tnote\n")
        _, err, code = go("report", path)
        self.assertEqual(code, 3)
        self.assertIn("too thin", err)

    def test_unsorted_rows_get_sorted(self):
        # 手编账本不按时间抄也行：载入即按日期排序，最早的 01-04 成为首行
        rows = wseq("2025-01-05", [100, 100], 1)
        rows.append(("2025-01-04", "wash", "90", "", ""))
        path = write_ledger(rows, self.tmp.name)
        out, _, code = go("rate", path)
        self.assertEqual(code, 3)                      # 2 对，基线不足
        self.assertIn("2025-01-05    100     1   100.0", out)
        self.assertNotIn("90.0", out)                  # 首行只当基线锚不入对


# ------------------------------------------------------------ 别名与口径门
class TestAliasesAndKindGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _base_rows(self, kind="wash"):
        return wseq("2025-01-01", [100, 200, 100], 1, kind=kind)

    def test_kind_alias_same_pooled_rate(self):
        a_path = write_ledger(self._base_rows("wash"), self.tmp.name, "a.tsv")
        b_path = write_ledger(self._base_rows("洗头"), self.tmp.name, "b.tsv")
        a, _, _ = go("rate", a_path)
        b, _, _ = go("rate", b_path)
        self.assertIn("池化 150.0 根/天", a)
        self.assertEqual(a.replace("a.tsv", "x"), b.replace("b.tsv", "x"))

    def test_event_alias_parse(self):
        self.assertEqual(sc.parse_event("start minoxidil"),
                         ("start", "minoxidil"))
        self.assertEqual(sc.parse_event("start-minoxidil"),
                         ("start", "minoxidil"))
        self.assertEqual(sc.parse_event("开始米诺地尔"),
                         ("start", "minoxidil"))
        self.assertEqual(sc.parse_event("停非那雄胺"),
                         ("stop", "finasteride"))
        self.assertEqual(sc.parse_event("stop 螺内酯"),
                         ("stop", "spironolactone"))
        with self.assertRaises(sc.LedgerError):
            sc.parse_event("refill minoxidil")

    def test_comb_never_mixed_into_wash_pools(self):
        wash_only = write_ledger(self._base_rows("wash"), self.tmp.name,
                                 "a.tsv")
        with_comb = write_ledger(
            self._base_rows("wash") +
            [("2025-01-04", "comb", "27", "", ""),
             ("2025-01-05", "comb", "31", "", "")],
            self.tmp.name, "b.tsv")
        a, _, _ = go("rate", wash_only)
        b, _, _ = go("rate", with_comb)
        self.assertIn("wash（3 行，2 对）", a)
        self.assertIn("wash（3 行，2 对）", b)            # comb 不动 wash 池
        self.assertIn("comb（2 行，1 对）", b)
        self.assertIn("池化 150.0 根/天", b.split("comb")[0])

    def test_unknown_kind_named_not_stats(self):
        rows = wseq("2025-01-01", [100, 200, 100, 200, 100], 1) + \
            [("2025-01-06", "剪发", "1", "", "理发不算掉发")]
        path = write_ledger(rows, self.tmp.name)
        out, _, code = go("rate", path)
        self.assertEqual(code, 0)
        self.assertIn("表外口径", out)
        self.assertIn("剪发 × 1 行", out)
        self.assertIn("没有先验就不换算", out)
        self.assertIn("wash（5 行，4 对）", out)       # 剪发行不进 wash

    def test_alias_idempotent(self):
        for raw in ("wash", "洗头", "60秒", "comb"):
            once = sc.canon_kind(raw)
            self.assertEqual(sc.canon_kind(once), once)


# ------------------------------------------------------------ 薄账分层
class TestThinLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_row_stats_decline_but_record_shown(self):
        rows = wseq("2025-01-01", [142], 1)
        path = write_ledger(rows, self.tmp.name)
        out, _, code = go("report", path)
        self.assertEqual(code, 3)
        self.assertIn("DECLINE", out)
        self.assertIn("wash 对 0", out)
        out2, _, code2 = go("rate", path)
        self.assertEqual(code2, 3)
        self.assertIn("0 对", out2)

    def test_events_only_thin(self):
        rows = [("2025-01-01", "", "", "start minoxidil", "")]
        path = write_ledger(rows, self.tmp.name)
        _, _, code = go("rate", path)
        self.assertEqual(code, 3)
        out, _, code = go("intervention", path)
        self.assertEqual(code, 3)                        # 无数据的庭=样本不足
        self.assertIn("开始 minoxidil", out)              # 事件档案照出
        self.assertIn("INSUFFICIENT-WINDOW", out)

    def test_no_baseline_decline(self):
        rows = wseq("2025-01-01", [100, 100], 1)
        path = write_ledger(rows, self.tmp.name)
        out, _, code = go("rate", path)
        self.assertEqual(code, 3)
        self.assertIn("基线 不足样本 — DECLINE", out)


# ------------------------------------------------------------ 参数化与确定性
class TestFlagsAndDeterminism(unittest.TestCase):
    def test_shed_line_override_reframes_verdict(self):
        a, _, ca = go("report", EXAMPLES)
        self.assertEqual(ca, 4)                          # 101.3 > 100
        b, _, cb = go("report", EXAMPLES, "--shed-line", "110")
        self.assertEqual(cb, 0)                          # 101.3 ≤ 110
        self.assertIn("近30d     OK", b)

    def test_gap_cap_override_includes_long_gap(self):
        a, _, _ = go("rate", EXAMPLES)
        self.assertIn("GAP", a)                          # 72 天断记默认剔除
        b, _, _ = go("rate", EXAMPLES, "--gap-cap", "90")
        # cap=90 下 72d 断记入池：该行不再带 GAP 签，全期池重算 77.3
        self.assertIn("2026-03-30    231    72     3.2", b)
        self.assertNotIn("   GAP", b)
        self.assertIn("池化 77.3 根/天（34010 根 / 440 天，143 对）", b)

    def test_byte_identical_across_runs_and_cwd(self):
        a, _, _ = go("report", EXAMPLES)
        r = subprocess.run([sys.executable, CLI, "report", EXAMPLES],
                           capture_output=True, text=True,
                           cwd=os.path.dirname(IDEA))
        self.assertEqual(r.returncode, 4)
        self.assertEqual(a, r.stdout)                    # 与 cwd 无关

    def test_report_basename_only(self):
        out, _, _ = go("report", EXAMPLES)
        self.assertIn("sheds.tsv", out)
        self.assertNotIn("shed-count/", out)

    def test_window_boundary_inclusive(self):
        # 近30d 窗 [as_of−29, as_of]：恰在 lo 的对入窗
        as_of = D("2025-03-01")
        lo, _ = sc.window_bounds(as_of, 30)
        self.assertEqual(lo, D("2025-01-31"))
        rows = [dict(date=D("2025-01-30"), count=100, note=""),
                dict(date=D("2025-01-31"), count=300, note=""),
                dict(date=D("2025-03-01"), count=100, note="")]
        pairs = sc.build_pairs(rows, 45)
        p = sc.pool(pairs, lo=lo, hi=as_of)
        self.assertEqual(p["counts"], 400)               # 01-31 与 03-01 两对
        self.assertEqual(p["days"], 30)


if __name__ == "__main__":
    unittest.main()
