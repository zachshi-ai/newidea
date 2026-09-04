#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""暗蛀 · Silent Rot 验收测试。

验收标准全部转成自动化测试：样例账本（小陈 2016-2026）钉死全部关键数字，
合成账本钉死棘轮合法性、判级边界、薄账分层与零锚定语义。
"""

import io
import atexit
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import silent_rot as sr  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "ledger.tsv")

_TMP = []


@atexit.register
def _cleanup_tmp():
    for p in _TMP:
        try:
            os.unlink(p)
        except OSError:
            pass


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = sr.main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0
    return code, out.getvalue() + err.getvalue()


def write_ledger(rows, header=("date", "tooth", "event", "cost", "note")):
    lines = ["\t".join(header)]
    for r in rows:
        cells = [cell if cell is not None else "" for cell in r]
        lines.append("\t".join(cells))
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    _TMP.append(path)
    return path


# ---------------------------------------------------------------- 样例钉值

class ExampleLedgerPins(unittest.TestCase):
    """小陈的账本：全部关键数字逐位钉死。"""

    def test_total_and_class_waterfall(self):
        code, out = run(["cost", EXAMPLE])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("¥18,970.00", out)
        self.assertIn("KEEP     ¥790.00", out)
        self.assertIn("FIX      ¥280.00", out)
        self.assertIn("REBUILD  ¥17,900.00", out)
        self.assertIn("恒等式 KEEP+FIX+REBUILD = 总额 ¥18,970.00 ✓", out)
        self.assertIn("16.73x", out)

    def test_report_lamps(self):
        code, out = run(["report", EXAMPLE])
        self.assertEqual(code, sr.EXIT_GATE)
        self.assertIn("WATCH-HOLD", out)
        self.assertIn("SILENT", out)
        self.assertIn("CARE-GAP", out)
        self.assertNotIn("NO-CROWN", out.split("-- 判级 --")[1])
        self.assertNotIn("NEVER-SEEN", out.split("-- 判级 --")[1])
        self.assertIn("灯 3 盏：CARE-GAP / SILENT / WATCH-HOLD", out)

    def test_report_ratchet_distribution(self):
        code, out = run(["report", EXAMPLE])
        self.assertIn("untracked 2 · replaced 1 · filled 1 · missing 1 · "
                      "crowned 1", out)
        self.assertIn("全史投入 ¥18,970.00", out)

    def test_watch_hold_days(self):
        code, out = run(["report", EXAMPLE])
        self.assertIn("36  since 2022-11-05  挂起 1394 天 ⚑超线", out)
        self.assertIn("48  since 2023-08-19  挂起 1107 天 ⚑超线", out)
        self.assertIn("47  since 2026-08-30  挂起 0 天", out)

    def test_silent_loop_pins(self):
        code, out = run(["silent", EXAMPLE])
        self.assertEqual(code, sr.EXIT_GATE)
        self.assertIn("16  2022-11-05 发现 → 2025-10-02 rootcanal  "
                      "拖延 1062 天  跨级+3  账面价差 +4,480", out)
        # 处理链含冠：根管 1200 + 冠 3600 = 4800
        self.assertIn("发现级处理价签 ¥320.00 vs 实际 ¥4,800.00", out)
        # 拔除是终点：价差语义不适用
        self.assertIn("38  2019-06-20 发现 → 2021-05-08 extract  "
                      "拖延 688 天", out)
        self.assertIn("账面价差 —", out)
        self.assertIn("拖延中位 875 天 · 最长 1062 天 · 合计 1750 天", out)

    def test_pending_watches_in_silent(self):
        code, out = run(["silent", EXAMPLE])
        self.assertIn("36  since 2022-11-05  已挂 1394 天", out)
        self.assertIn("48  since 2023-08-19  已挂 1107 天", out)

    def test_edentulous_days(self):
        code, out = run(["cost", EXAMPLE])
        self.assertIn("46  无牙 2865 天（7.8 年）已重建", out)
        self.assertIn("38  无牙 1940 天（5.3 年）至今缺席", out)

    def test_tooth_cost_ranking(self):
        code, out = run(["cost", EXAMPLE])
        self.assertIn("46    ¥12,300.00    replaced", out)
        self.assertIn("16    ¥4,800.00     crowned", out)

    def test_ratchet_pins(self):
        code, out = run(["ratchet", EXAMPLE])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("46  6  replaced      ¥12,300.00", out)
        self.assertIn("16  4  crowned       ¥4,800.00", out)
        self.assertIn("36  2  filled        ¥280.00", out)
        self.assertIn("38  5  missing       ¥830.00", out)
        self.assertIn("全史重建类投入 ¥17,900.00", out)
        # 价签牌
        self.assertIn("下一级价签 ¥1,200.00 ⚑挂起", out)     # 36 filled
        self.assertIn("下一级价签 ¥12,000.00", out)           # 38 missing
        self.assertIn("46  6  replaced      ¥12,300.00", out)

    def test_due_pins(self):
        code, out = run(["due", EXAMPLE])
        self.assertEqual(code, sr.EXIT_GATE)
        self.assertIn("watch 36 观察复查", out)
        self.assertIn("逾期 1304 天", out)
        self.assertIn("watch 48 观察复查", out)
        self.assertIn("逾期 1017 天", out)
        self.assertIn("implant 46 种植年检", out)
        self.assertIn("逾期 428 天", out)
        self.assertIn("crown 16 冠随访", out)
        self.assertIn("还剩 82 天  DUE-SOON", out)
        self.assertIn("watch 47 观察复查", out)
        self.assertIn("还剩 90 天  DUE-SOON", out)   # 恰 90 含边界
        self.assertIn("scaling 洗牙", out)
        self.assertIn("还剩 196 天  OK", out)
        self.assertIn("check 口腔检查", out)
        self.assertIn("还剩 561 天  OK", out)

    def test_validate_ok(self):
        code, out = run(["validate", EXAMPLE])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("validate: OK", out)
        self.assertIn("双算法重放一致", out)
        self.assertIn("棘轮合法", out)

    def test_asof_default_is_ledger_max_date(self):
        _, want = run(["report", EXAMPLE])
        code, got = run(["report", EXAMPLE, "--as-of", "2026-08-30"])
        self.assertEqual(code, sr.EXIT_GATE)
        self.assertEqual(want, got)

    def test_asof_time_machine(self):
        # 钉回 2022-12-31：38 的拖延已经红着，16/36 才刚挂起 56 天
        code, out = run(["report", EXAMPLE, "--as-of", "2022-12-31"])
        self.assertEqual(code, sr.EXIT_GATE)
        self.assertIn("全史投入 ¥1,710.00", out)     # 截断回放，不是全史
        self.assertIn("16  since 2022-11-05  挂起 56 天", out)
        self.assertIn("38  2019-06-20 → 2021-05-08(extract)  拖延 688 天",
                      out)
        self.assertIn("灯 2 盏：CARE-GAP / SILENT", out)
        # rootcanal（2025-10-02）在回放里不存在
        self.assertNotIn("rootcanal", out)


# ---------------------------------------------------------------- 棘轮

def T(date, tooth, event, cost="0", note=""):
    return (date, tooth, event, cost, note)


class RatchetRules(unittest.TestCase):
    """治疗棘轮：等级只升不降，种植体上什么都不会再发生。"""

    def setUp(self):
        self.self = self

    def test_full_ladder_legal(self):
        path = write_ledger([
            T("2024-01-10", "16", "found"),
            T("2024-02-01", "16", "fill", "320"),
            T("2024-06-01", "16", "rootcanal", "1200"),
            T("2024-07-01", "16", "crown", "3600"),
        ])
        code, out = run(["validate", path])
        self.assertEqual(code, sr.EXIT_OK)
        code, out = run(["ratchet", path])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("16  4  crowned", out)

    def test_downgrade_rejected(self):
        path = write_ledger([
            T("2024-01-10", "16", "crown", "3600"),
            T("2024-02-01", "16", "fill", "320"),
        ])
        code, out = run(["validate", path])
        self.assertEqual(code, sr.EXIT_LEDGER)
        self.assertIn("ratchet violation", out)

    def test_missing_tooth_cannot_be_filled(self):
        path = write_ledger([
            T("2024-01-10", "46", "extract", "800"),
            T("2024-02-01", "46", "fill", "320"),
        ])
        code, out = run(["validate", path])
        self.assertEqual(code, sr.EXIT_LEDGER)

    def test_double_extract_rejected(self):
        path = write_ledger([
            T("2024-01-10", "46", "extract", "800"),
            T("2024-02-01", "46", "extract", "800"),
        ])
        code, out = run(["validate", path])
        self.assertEqual(code, sr.EXIT_LEDGER)
        self.assertIn("extracted twice", out)

    def test_implant_after_missing_legal(self):
        path = write_ledger([
            T("2016-01-10", "46", "extract", "300"),
            T("2024-01-10", "46", "implant", "8000"),
        ])
        code, out = run(["ratchet", path])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("46  6  replaced", out)

    def test_implant_staged_accumulates(self):
        path = write_ledger([
            T("2024-01-10", "46", "extract", "300"),
            T("2024-02-01", "46", "implant", "8000"),
            T("2024-08-01", "46", "implant", "4000"),
        ])
        code, out = run(["cost", path])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("46    ¥12,300.00    replaced", out)

    def test_no_caries_on_implant(self):
        path = write_ledger([
            T("2024-01-10", "46", "implant", "12000"),
            T("2025-01-10", "46", "found"),
        ])
        code, out = run(["validate", path])
        self.assertEqual(code, sr.EXIT_LEDGER)
        self.assertIn("no caries to watch", out)

    def test_no_treatment_on_implant(self):
        path = write_ledger([
            T("2024-01-10", "46", "implant", "12000"),
            T("2025-01-10", "46", "fill", "320"),
        ])
        code, out = run(["validate", path])
        self.assertEqual(code, sr.EXIT_LEDGER)

    def test_refound_after_fill_is_secondary_caries(self):
        # 继发龋：补过的牙也会再坏——found 浮动旗标可重新挂起
        path = write_ledger([
            T("2018-01-10", "36", "fill", "280"),
            T("2022-11-05", "36", "found"),
        ])
        code, out = run(["ratchet", path])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("36  2  filled", out)
        self.assertIn("⚑挂起", out)

    def test_refill_same_level_legal(self):
        path = write_ledger([
            T("2018-01-10", "36", "fill", "280"),
            T("2022-11-05", "36", "found"),
            T("2023-01-05", "36", "fill", "400"),
        ])
        code, out = run(["validate", path])
        self.assertEqual(code, sr.EXIT_OK)

    def test_treatment_consumes_watch(self):
        # found 挂起被治疗消化：16 闭环后不再是挂起
        code, out = run(["report", EXAMPLE])
        body = out.split("-- 观察挂起")[1].split("--")[0]
        self.assertNotIn("16", body)


# ---------------------------------------------------------------- 语法

class LedgerSyntax(unittest.TestCase):
    def _expect_ledger_error(self, rows, needle=None):
        path = write_ledger(rows)
        code, out = run(["report", path])
        self.assertEqual(code, sr.EXIT_LEDGER)
        if needle:
            self.assertIn(needle, out)

    def test_missing_file(self):
        code, out = run(["report", "/nonexistent/nope.tsv"])
        self.assertEqual(code, sr.EXIT_LEDGER)
        self.assertIn("nope.tsv", out)          # 只打印 basename
        self.assertNotIn("/nonexistent", out)

    def test_bad_tooth_number(self):
        for tooth in ("19", "49", "50", "86", "9", "abc", "161"):
            self._expect_ledger_error(
                [T("2024-01-10", tooth, "fill", "320")])

    def test_deciduous_tooth_legal(self):
        path = write_ledger([
            T("2025-12-01", "54", "found"),
            T("2026-02-10", "54", "fill", "200"),
        ])
        code, out = run(["ratchet", path])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("54  2  filled", out)

    def test_unknown_event(self):
        self._expect_ledger_error(
            [T("2024-01-10", "16", "whitening", "2000")],
            "unknown event")

    def test_negative_cost(self):
        self._expect_ledger_error(
            [T("2024-01-10", "16", "fill", "-320")])

    def test_bad_date(self):
        self._expect_ledger_error(
            [T("2024-13-10", "16", "fill", "320")])

    def test_missing_column(self):
        path = write_ledger([("2024-01-10", "16", "fill")],
                            header=("date", "tooth", "event", "cost", "note"))
        code, out = run(["report", path])
        self.assertEqual(code, sr.EXIT_LEDGER)

    def test_empty_ledger(self):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("date\ttooth\tevent\tcost\tnote\n")
        self.addCleanup(os.unlink, path)
        code, out = run(["report", path])
        self.assertEqual(code, sr.EXIT_LEDGER)

    def test_scaling_is_fullmouth(self):
        self._expect_ledger_error(
            [T("2024-01-10", "16", "scaling", "300")],
            "full-mouth")

    def test_found_needs_tooth(self):
        self._expect_ledger_error(
            [T("2024-01-10", "", "found", "0")])

    def test_cjk_aliases_normalized(self):
        path = write_ledger([
            T("2018-04-21", "36", "补牙", "280", "树脂充填"),
            T("2020-11-15", "", "洗牙", "300"),
            T("2021-05-08", "38", "拔除", "800"),
            T("2022-11-05", "16", "观察", "0"),
            T("2025-10-02", "16", "根管治疗", "1200"),
        ])
        code, out = run(["ratchet", path])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("16  3  root-canaled", out)
        self.assertIn("38  5  missing", out)
        self.assertIn("36  2  filled", out)

    def test_check_allows_tooth_or_fullmouth(self):
        path = write_ledger([
            T("2022-11-05", "", "check", "0"),
            T("2022-11-05", "16", "check", "0"),
        ])
        code, out = run(["validate", path])
        self.assertEqual(code, sr.EXIT_OK)


# ---------------------------------------------------------------- 判级线

class LinesAndGates(unittest.TestCase):
    def test_watch_line_widened(self):
        # --watch-line 2000：36(1394)/48(1107) 都回绿，其余灯不变
        code, out = run(["report", EXAMPLE, "--watch-line", "2000"])
        self.assertEqual(code, sr.EXIT_GATE)
        body = out.split("-- 判级 --")[1]
        self.assertNotIn("WATCH-HOLD", body)
        self.assertIn("CARE-GAP", body)
        self.assertIn("SILENT", body)

    def test_all_green_with_wide_lines(self):
        code, out = run(["report", EXAMPLE, "--watch-line", "2000",
                         "--silent-line", "2000"])
        body = out.split("-- 判级 --")[1]
        self.assertNotIn("SILENT", body)
        self.assertIn("CARE-GAP", body)          # 1709 天的空白还在
        self.assertEqual(code, sr.EXIT_GATE)

    def test_silent_line_boundary_exact(self):
        # 拖延恰 365 天：不超线（合成账本，两条闭环绕开薄账）
        path = write_ledger([
            T("2024-08-30", "16", "found"),
            T("2025-08-30", "16", "fill", "320"),       # 恰 365
            T("2024-08-30", "26", "found"),
            T("2025-08-30", "26", "fill", "320"),       # 恰 365
        ])
        code, out = run(["silent", path])
        self.assertEqual(code, sr.EXIT_OK)
        # +1 天即超线
        path = write_ledger([
            T("2024-08-30", "16", "found"),
            T("2025-08-31", "16", "fill", "320"),       # 366
            T("2024-08-30", "26", "found"),
            T("2025-08-30", "26", "fill", "320"),       # 365
        ])
        code, out = run(["silent", path])
        self.assertEqual(code, sr.EXIT_GATE)

    def test_no_crown_gate_synthetic(self):
        # 根管后 221 天无冠：亮 NO-CROWN（账本带 check 行，NEVER-SEEN 不抢戏）
        path = write_ledger([
            T("2025-01-01", "16", "rootcanal", "1200"),
            T("2025-07-01", "", "check", "0"),
        ])
        code, out = run(["report", path, "--as-of", "2025-08-10"])
        body = out.split("-- 判级 --")[1]
        self.assertIn("NO-CROWN", body)
        self.assertEqual(code, sr.EXIT_GATE)

    def test_crown_line_boundary_exact(self):
        # 根管后恰 180 天戴冠：NO-CROWN 不亮
        path = write_ledger([
            T("2026-03-03", "16", "rootcanal", "1200"),
            T("2026-08-30", "16", "crown", "3600"),     # 180 天闭环
            T("2026-08-30", "", "check", "0"),
        ])
        code, out = run(["report", path])
        body = out.split("-- 判级 --")[1]
        self.assertNotIn("NO-CROWN", body)
        self.assertEqual(code, sr.EXIT_OK)

    def test_never_seen_synthetic(self):
        path = write_ledger([
            T("2020-01-10", "16", "fill", "320"),
        ])
        code, out = run(["report", path])
        body = out.split("-- 判级 --")[1]
        self.assertIn("NEVER-SEEN", body)
        self.assertEqual(code, sr.EXIT_GATE)

    def test_price_override(self):
        code, out = run(["silent", EXAMPLE, "--price", "fill=480"])
        self.assertIn("账面价差 +4,320", out)       # 4800-480
        self.assertEqual(code, sr.EXIT_GATE)

    def test_duesoon_boundary_inclusive(self):
        # 恰 90 天 → DUE-SOON（含边界），91 天 → OK
        self.assertIn("还剩 90 天  DUE-SOON", run(["due", EXAMPLE])[1])


# ---------------------------------------------------------------- 薄账

class ThinLedger(unittest.TestCase):
    def test_single_loop_declines_stats_but_keeps_arithmetic(self):
        path = write_ledger([
            T("2020-01-10", "16", "found"),
            T("2024-01-10", "16", "rootcanal", "1200"),   # 拖 1461 天
        ])
        code, out = run(["silent", path])
        self.assertEqual(code, sr.EXIT_GATE)              # 灯照亮（算术）
        self.assertIn("THIN", out)
        self.assertIn("拖延 1461 天", out)                # 逐条账照出
        self.assertIn("SILENT", out)

    def test_single_short_loop_declines_only(self):
        path = write_ledger([
            T("2026-01-10", "16", "found"),
            T("2026-03-01", "16", "fill", "320"),         # 拖 50 天
        ])
        code, out = run(["silent", path])
        self.assertEqual(code, sr.EXIT_DECLINE)
        self.assertIn("THIN", out)

    def test_report_arithmetic_survives_thin(self):
        path = write_ledger([
            T("2026-01-10", "16", "found"),
            T("2026-03-01", "16", "fill", "320"),
        ])
        code, out = run(["cost", path])
        self.assertEqual(code, sr.EXIT_OK)
        self.assertIn("¥320.00", out)


# ---------------------------------------------------------------- 接口

class Interface(unittest.TestCase):
    def test_report_only_basename_on_error(self):
        code, out = run(["report", "/nonexistent/deep/dir/x.tsv"])
        self.assertNotIn("deep", out)

    def test_no_wall_clock_in_source(self):
        with open(os.path.join(ROOT, "silent_rot.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("date.today", "datetime.now", "time.time",
                       "datetime.utcnow"):
            self.assertNotIn(banned, src)

    def test_examples_byte_identical(self):
        import subprocess
        proc = subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "examples", "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("byte-identical", proc.stdout)


if __name__ == "__main__":
    unittest.main()
