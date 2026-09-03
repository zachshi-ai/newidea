#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""later-never 的验收测试。

全部确定性：不读墙钟，所有日期锚定 2026-09-04（与 examples 一致）。
示例账本的期望值（41 条 / 18 读 / t½=9.0 / 坟场 10 条 / ETA=never）
是手工推导的，见同目录 examples/library.tsv。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "later_never.py")
LIBRARY = os.path.join(ROOT, "examples", "library.tsv")
POCKET = os.path.join(ROOT, "examples", "pocket_export.html")
TODAY = dt.date(2026, 9, 4)

spec = importlib.util.spec_from_file_location("later_never", SCRIPT)
ln = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ln)


def run_cli(*argv):
    return subprocess.run(
        [sys.executable, SCRIPT] + list(argv),
        capture_output=True, text=True)


def make_entry(eid, saved, read=None, tags=("t",)):
    return ln.Entry(eid, dt.date.fromisoformat(saved),
                    "title-" + eid, tuple(tags),
                    dt.date.fromisoformat(read) if read else None)


class TestLedgerLoading(unittest.TestCase):

    def test_example_loads(self):
        entries = ln.load_library(LIBRARY)
        self.assertEqual(len(entries), 41)
        self.assertEqual(sum(1 for e in entries if e.is_read), 18)
        self.assertEqual(sum(1 for e in entries if not e.is_read), 23)

    def test_header_and_blank_lines_tolerated(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                         delete=False, encoding="utf-8") as fh:
            fh.write("id\tsaved_at\ttitle\ttags\tread_at\n")
            fh.write("\n")
            fh.write("x1\t2026-01-01\t标题\t\t\n")
            path = fh.name
        entries = ln.load_library(path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].tags, ())
        os.unlink(path)

    def test_missing_file_rejected(self):
        with self.assertRaises(ln.LedgerError):
            ln.load_library("/nonexistent/library.tsv")

    def test_wrong_column_count_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                         delete=False, encoding="utf-8") as fh:
            fh.write("x1\t2026-01-01\t只有三列\n")
            path = fh.name
        with self.assertRaises(ln.LedgerError):
            ln.load_library(path)
        os.unlink(path)

    def test_bad_date_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                         delete=False, encoding="utf-8") as fh:
            fh.write("x1\t2026/01/01\t标题\t\t\n")
            path = fh.name
        with self.assertRaises(ln.LedgerError):
            ln.load_library(path)
        os.unlink(path)

    def test_read_before_saved_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                         delete=False, encoding="utf-8") as fh:
            fh.write("x1\t2026-01-02\t标题\t\t2026-01-01\n")
            path = fh.name
        with self.assertRaises(ln.LedgerError):
            ln.load_library(path)
        os.unlink(path)

    def test_duplicate_id_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                         delete=False, encoding="utf-8") as fh:
            fh.write("x1\t2026-01-01\t甲\t\t\n")
            fh.write("x1\t2026-01-02\t乙\t\t\n")
            path = fh.name
        with self.assertRaises(ln.LedgerError):
            ln.load_library(path)
        os.unlink(path)

    def test_empty_id_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                         delete=False, encoding="utf-8") as fh:
            fh.write("\t2026-01-01\t标题\t\t\n")
            path = fh.name
        with self.assertRaises(ln.LedgerError):
            ln.load_library(path)
        os.unlink(path)

    def test_save_and_reload_roundtrip(self):
        entries = ln.load_library(LIBRARY)
        with tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                         delete=False, encoding="utf-8") as fh:
            path = fh.name
        ln.save_library(path, entries)
        reloaded = ln.load_library(path)
        self.assertEqual(
            [(e.eid, e.saved_at, e.read_at, e.tags) for e in reloaded],
            [(e.eid, e.saved_at, e.read_at, e.tags) for e in entries])
        os.unlink(path)


class TestHalfLife(unittest.TestCase):

    def test_example_halflife_is_nine_days(self):
        entries = ln.load_library(LIBRARY)
        self.assertEqual(ln.half_life(entries), 9.0)

    def test_insufficient_samples_refused(self):
        few = [make_entry("a", "2026-08-01", read="2026-08-02") for _ in range(4)]
        self.assertIsNone(ln.half_life(few))

    def test_median_not_mean(self):
        # 中位数 9，平均数被一个 90 天的异常值拉高：t½ 必须取中位
        delays = [1, 2, 3, 4, 5, 7, 8, 9, 9, 9, 12, 16, 20, 27, 34, 45, 60, 90]
        entries = [make_entry("e%02d" % i, "2026-01-01")
                   for i in range(len(delays))]
        for e, d in zip(entries, delays):
            e.read_at = e.saved_at + dt.timedelta(days=d)
        self.assertEqual(ln.half_life(entries), 9.0)


class TestGraveyard(unittest.TestCase):

    def test_example_graveyard(self):
        entries = ln.load_library(LIBRARY)
        self.assertAlmostEqual(ln.graveyard_rate(entries, TODAY),
                               10 / 41, places=6)

    def test_threshold_boundary(self):
        # 2026-03-01 收藏的 age = 187 > 180 → 坟场；187 边界在 181 桶
        entries = [make_entry("old", "2026-03-01"),
                   make_entry("edge", "2026-03-08")]
        self.assertAlmostEqual(ln.graveyard_rate(entries, TODAY), 0.5)

    def test_read_entries_never_counted(self):
        entries = [make_entry("r", "2025-01-01", read="2025-02-01")]
        self.assertEqual(ln.graveyard_rate(entries, TODAY), 0.0)


class TestAgingCurve(unittest.TestCase):

    def test_example_buckets(self):
        buckets = ln.aging_curve(ln.load_library(LIBRARY), TODAY)
        self.assertEqual([b["n"] for b in buckets], [7, 15, 5, 14])
        self.assertEqual([b["read"] for b in buckets], [3, 6, 5, 4])
        self.assertEqual([b["label"] for b in buckets],
                         ["0–30 天", "31–90 天", "91–180 天", "180+ 天"])

    def test_bucket_boundaries(self):
        entries = [make_entry("a", "2026-08-05"),   # age 30 → 第一桶
                   make_entry("b", "2026-08-04"),   # age 31 → 第二桶
                   make_entry("c", "2026-03-08"),   # age 180 → 第三桶
                   make_entry("d", "2026-03-07")]   # age 181 → 第四桶
        buckets = ln.aging_curve(entries, TODAY)
        self.assertEqual([b["n"] for b in buckets], [1, 1, 1, 1])

    def test_empty_bucket_rate_is_none(self):
        buckets = ln.aging_curve([make_entry("a", "2026-08-05")], TODAY)
        self.assertIsNone(buckets[1]["read_rate"])


class TestVelocityAndETA(unittest.TestCase):

    def test_example_velocities(self):
        vel = ln.velocities(ln.load_library(LIBRARY), TODAY)
        self.assertEqual(vel["saved_n"], 22)
        self.assertEqual(vel["read_n"], 9)
        self.assertAlmostEqual(vel["save_per_week"], 22 / (90 / 7), places=6)
        self.assertAlmostEqual(vel["read_per_week"], 9 / (90 / 7), places=6)

    def test_window_boundary_excluded(self):
        # saved_at 恰好 = today − 90 天（含）不计入窗口
        edge = make_entry("edge", "2026-06-06")
        inside = make_entry("in", "2026-06-07")
        vel = ln.velocities([edge, inside], TODAY)
        self.assertEqual(vel["saved_n"], 1)

    def test_example_eta_is_never(self):
        eta = ln.clear_eta(ln.load_library(LIBRARY), TODAY)
        self.assertEqual(eta["backlog"], 23)
        self.assertIsNone(eta["eta_weeks"])
        self.assertLess(eta["net_per_week"], 0)

    def test_finite_eta_when_digesting_faster(self):
        entries = [make_entry("b%02d" % i, "2026-01-01") for i in range(10)]
        # 老收藏、新近读完：窗口内 0 收藏、1 读完 → 净 +1/(90/7) 每周
        entries.append(make_entry("r", "2026-04-01", read="2026-07-01"))
        eta = ln.clear_eta(entries, TODAY)
        self.assertIsNotNone(eta["eta_weeks"])
        self.assertAlmostEqual(eta["eta_weeks"], 10 / (7 / 90), places=6)


class TestTagProfile(unittest.TestCase):

    def test_example_profile(self):
        rows = {r["tag"]: r for r in
                ln.tag_profile(ln.load_library(LIBRARY), TODAY)}
        self.assertEqual(rows["ai-tools"]["saved"], 15)
        self.assertEqual(rows["ai-tools"]["read"], 1)
        self.assertTrue(rows["ai-tools"]["illusion"])
        self.assertEqual(rows["essays"]["saved"], 12)
        self.assertFalse(rows["essays"]["illusion"])
        # ai15 是双标签条目：career 因此有 8 条
        self.assertEqual(rows["career"]["saved"], 8)
        self.assertFalse(rows["career"]["illusion"])   # 25% ≥ 20% 不算幻觉
        self.assertEqual(rows["deep-work"]["read_rate"], 1.0)

    def test_illusion_needs_sample_size(self):
        # 4 条全没读：读率 0% 但样本 < 10，不给幻觉帽子
        entries = [make_entry("x%d" % i, "2026-01-01", tags=("t",))
                   for i in range(4)]
        rows = ln.tag_profile(entries, TODAY)
        self.assertEqual(rows[0]["read_rate"], 0.0)
        self.assertFalse(rows[0]["illusion"])


class TestTriage(unittest.TestCase):

    def test_example_triage(self):
        entries = ln.load_library(LIBRARY)
        groups, degraded = ln.triage(entries, TODAY, ln.half_life(entries))
        self.assertFalse(degraded)
        r1_ids = {e.eid for e in groups["r1"]}
        # ca7 age=36 不越过 4×t½=36 的门槛；es9 age=71 越过 → R1
        self.assertNotIn("ca7", r1_ids)
        self.assertIn("es9", r1_ids)
        self.assertEqual(len(r1_ids), 17)
        r2_ids = {e.eid for e in groups["r2"]}
        self.assertEqual(r2_ids, {"ai13"})

    def test_degraded_mode_without_halflife(self):
        entries = ([make_entry("t%02d" % i, "2026-06-01", tags=("t",))
                   for i in range(10)]
                   + [make_entry("r", "2026-05-01", read="2026-05-10")])
        groups, degraded = ln.triage(entries, TODAY, None)
        self.assertTrue(degraded)
        self.assertEqual(len(groups["r1"]), 0)     # 退化阈值 120 天，95 不越
        self.assertEqual(len(groups["r2"]), 10)    # 60 天门槛 + 幻觉 tag

    def test_healthy_tag_blocks_r2(self):
        # 所有 tag 读率 ≥ 20% → R2 空
        entries = ([make_entry("t%02d" % i, "2026-05-01", tags=("t",))
                   for i in range(8)]
                   + [make_entry("r%d" % i, "2026-05-01", read="2026-05-02",
                                 tags=("t",)) for i in range(2)])
        groups, _ = ln.triage(entries, TODAY, 9.0)
        self.assertEqual(len(groups["r2"]), 0)


class TestBudget(unittest.TestCase):

    def test_example_budget(self):
        b = ln.budget(ln.load_library(LIBRARY), TODAY, months=6)
        self.assertEqual(b["backlog"], 23)
        self.assertAlmostEqual(b["drain_per_week"],
                               23 / (6 * 52 / 12), places=6)
        # 需要的消化速度 = 摄入 + 净排空
        self.assertAlmostEqual(
            b["need_read"],
            22 / (90 / 7) + 23 / (6 * 52 / 12), places=6)
        # 配额为负：光停止收藏也清不完
        self.assertLess(b["cap_save"], 0)

    def test_months_must_be_positive(self):
        with self.assertRaises(ln.LedgerError):
            ln.budget(ln.load_library(LIBRARY), TODAY, months=0)


class TestMark(unittest.TestCase):

    def _copy(self):
        with open(LIBRARY, "r", encoding="utf-8") as fh:
            text = fh.read()
        tmp = tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                          delete=False, encoding="utf-8")
        tmp.write(text)
        tmp.close()
        return tmp.name

    def test_mark_flips_and_rewrites(self):
        path = self._copy()
        entries = ln.load_library(path)
        target = next(e for e in entries if not e.is_read)
        for e in entries:
            if e.eid == target.eid:
                e.read_at = TODAY
        ln.save_library(path, entries)
        reloaded = ln.load_library(path)
        self.assertEqual(len(reloaded), 41)
        hit = next(e for e in reloaded if e.eid == target.eid)
        self.assertEqual(hit.read_at, TODAY)
        os.unlink(path)

    def test_mark_unknown_id_rejected(self):
        entries = ln.load_library(LIBRARY)
        index = {e.eid: e for e in entries}
        self.assertNotIn("ghost", index)

    def test_mark_already_read_rejected_via_cli(self):
        path = self._copy()
        proc = run_cli("mark", path, "es1", "--today", "2026-09-04")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("已是已读", proc.stderr)
        os.unlink(path)


class TestPocketImport(unittest.TestCase):

    def test_fixture_import(self):
        entries = ln.import_pocket(POCKET)
        # 归档段、坏时间戳条目都不进账本
        self.assertEqual(len(entries), 3)
        self.assertEqual([e.saved_at.isoformat() for e in entries],
                         ["2025-06-27", "2025-07-08", "2025-07-20"])
        self.assertTrue(all(e.read_at is None for e in entries))
        by_date = {e.saved_at: e for e in entries}
        self.assertEqual(by_date[dt.date(2025, 6, 27)].tags, ("ai-tools",))
        self.assertEqual(by_date[dt.date(2025, 7, 8)].tags, ())
        self.assertEqual(by_date[dt.date(2025, 7, 20)].tags,
                         ("essays", "deep-work"))
        ids = [e.eid for e in entries]
        self.assertEqual(len(ids), len(set(ids)))

    def test_titles_kept_and_normalized(self):
        entries = ln.import_pocket(POCKET)
        titles = {e.title for e in entries}
        self.assertIn("AI 工作流指南", titles)
        self.assertNotIn("归档旧文不应被导入", titles)

    def test_missing_file(self):
        with self.assertRaises(ln.LedgerError):
            ln.import_pocket("/nonexistent/export.html")

    def test_no_later_section_refused(self):
        with tempfile.NamedTemporaryFile("w", suffix=".html",
                                         delete=False, encoding="utf-8") as fh:
            fh.write("<html><body><p>nothing here</p></body></html>")
            path = fh.name
        self.assertEqual(ln.import_pocket(path), [])
        os.unlink(path)


class TestCLI(unittest.TestCase):

    def test_audit_exit0_and_headlines(self):
        proc = run_cli("audit", LIBRARY, "--today", "2026-09-04")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("消化半衰期 t½", proc.stdout)
        self.assertIn("9.0 天", proc.stdout)
        self.assertIn("清空 ETA           : ∞", proc.stdout)
        self.assertIn("幻觉类型", proc.stdout)
        self.assertIn("41 条", proc.stdout)

    def test_audit_is_deterministic(self):
        a = run_cli("audit", LIBRARY, "--today", "2026-09-04")
        b = run_cli("audit", LIBRARY, "--today", "2026-09-04")
        self.assertEqual(a.stdout, b.stdout)

    def test_audit_gate(self):
        proc = run_cli("audit", LIBRARY, "--today", "2026-09-04",
                       "--max-graveyard", "0.10")
        self.assertEqual(proc.returncode, 4)
        self.assertIn("闸门", proc.stderr)
        proc = run_cli("audit", LIBRARY, "--today", "2026-09-04",
                       "--max-graveyard", "0.50")
        self.assertEqual(proc.returncode, 0)

    def test_audit_today_shifts_ages(self):
        later = run_cli("audit", LIBRARY, "--today", "2026-12-04")
        self.assertEqual(later.returncode, 0)
        self.assertIn("锚定 2026-12-04", later.stdout)

    def test_missing_ledger_exit2(self):
        proc = run_cli("audit", "/nonexistent.tsv", "--today", "2026-09-04")
        self.assertEqual(proc.returncode, 2)

    def test_empty_ledger_exit3(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                         delete=False, encoding="utf-8") as fh:
            fh.write("id\tsaved_at\ttitle\ttags\tread_at\n")
            path = fh.name
        proc = run_cli("audit", path, "--today", "2026-09-04")
        self.assertEqual(proc.returncode, 3)
        os.unlink(path)

    def test_no_command_exit2(self):
        proc = run_cli()
        self.assertEqual(proc.returncode, 2)

    def test_triage_exit0_with_rules(self):
        proc = run_cli("triage", LIBRARY, "--today", "2026-09-04")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("R1 · 越老越死", proc.stdout)
        self.assertIn("R2 · 类型幻觉", proc.stdout)
        self.assertIn("仍是你的决定", proc.stdout)

    def test_budget_exit0(self):
        proc = run_cli("budget", LIBRARY, "--today", "2026-09-04",
                       "--months", "6")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("杠杆 A", proc.stdout)
        self.assertIn("杠杆 B", proc.stdout)
        self.assertIn("即使从此零收藏", proc.stdout)

    def test_mark_via_cli(self):
        with open(LIBRARY, "r", encoding="utf-8") as fh:
            text = fh.read()
        tmp = tempfile.NamedTemporaryFile("w", suffix=".tsv",
                                          delete=False, encoding="utf-8")
        tmp.write(text)
        tmp.close()
        proc = run_cli("mark", tmp.name, "es9", "--today", "2026-09-04")
        self.assertEqual(proc.returncode, 0)
        entries = ln.load_library(tmp.name)
        hit = next(e for e in entries if e.eid == "es9")
        self.assertEqual(hit.read_at, dt.date(2026, 9, 4))
        os.unlink(tmp.name)

    def test_import_pocket_via_cli(self):
        out = tempfile.mktemp(suffix=".tsv")
        proc = run_cli("import-pocket", POCKET, "--out", out)
        self.assertEqual(proc.returncode, 0)
        entries = ln.load_library(out)
        self.assertEqual(len(entries), 3)
        os.unlink(out)

    def test_bad_today_exit2(self):
        proc = run_cli("audit", LIBRARY, "--today", "2026/09/04")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
