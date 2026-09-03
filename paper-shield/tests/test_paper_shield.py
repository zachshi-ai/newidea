#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper-shield 验收测试：README 验收标准 A1-J3 全部转成自动化测试。"""

import contextlib
import datetime as dt
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paper_shield  # noqa: E402

EX_T = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "examples", "targets.tsv")
EX_E = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "examples", "events.tsv")
TODAY = "2026-09-04"


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = paper_shield.main(argv)
    return out.getvalue(), code


class Tmp:
    """临时双账本构建器。"""

    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.targets: list = []
        self.events: list = []

    def t(self, name, scope, medium, place, cadence="7"):
        self.targets.append(f"{name}\t{scope}\t{medium}\t{place}\t{cadence}")
        return self

    def e(self, date, target, kind, note=""):
        cols = [str(date), target, kind, note]
        self.events.append("\t".join(cols))
        return self

    @property
    def paths(self):
        tp = os.path.join(self.dir, "targets.tsv")
        ep = os.path.join(self.dir, "events.tsv")
        with open(tp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(self.targets) + "\n")
        with open(ep, "w", encoding="utf-8") as fh:
            fh.write("\n".join(self.events) + "\n")
        return tp, ep

    def raw_targets(self, lines):
        self.targets = lines
        return self

    def raw_events(self, lines):
        self.events = lines
        return self


def green_tmp():
    """全绿账本：photos 三副本三介质含异地，全部昨天 backup+verify+drill。"""
    t = Tmp()
    t.t("甲", "photos", "disk", "home", "7")
    t.t("乙", "photos", "nas", "home", "7")
    t.t("丙", "photos", "cloud", "cloud", "7")
    for name in ("甲", "乙", "丙"):
        t.e("2026-09-03", name, "backup")
        t.e("2026-09-03", name, "verify")
    t.e("2026-09-03", "丙", "drill")
    return t


# ---------------------------------------------------------------------------
# A 账本解析：坏行带行号 exit 2
# ---------------------------------------------------------------------------

class TestParsing(unittest.TestCase):
    def test_a01_targets_missing(self):
        _, code = run(["audit", "/nonexistent.tsv", "/nonexistent2.tsv", "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a02_targets_too_few_cols(self):
        _, code = run(["audit", *Tmp().raw_targets(["甲\tphotos\tdisk"]).paths, "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a03_duplicate_target(self):
        t = Tmp().raw_targets(["甲\tphotos\tdisk\thome\t7", "甲\tart\tnas\thome\t7"])
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a04_bad_place(self):
        t = Tmp().raw_targets(["甲\tphotos\tdisk\tbasement\t7"])
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a05_bad_cadence(self):
        for bad in ("abc", "0", "-7"):
            t = Tmp().raw_targets([f"甲\tphotos\tdisk\thome\t{bad}"])
            _, code = run(["audit", *t.paths, "--today", TODAY])
            self.assertEqual(code, 2, bad)

    def test_a06_cadence_blank_allowed(self):
        t = Tmp().raw_targets(["甲\tphotos\tdisk\thome\t-"])
        t.e("2026-09-01", "甲", "backup")
        t.e("2026-09-01", "甲", "verify")
        text, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 4)  # 从未验证之外：不判新鲜度但 3-2-1 不达标
        self.assertIn("UNKNOWN", text)

    def test_a07_events_missing(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7")
        _, code = run(["audit", t.paths[0], "/nonexistent.tsv", "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a08_events_too_few_cols(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7").raw_events(["2026-09-01\t甲"])
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a09_bad_event_date(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7").raw_events(["2026-09\t甲\tbackup"])
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a10_future_event_date(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7").raw_events(["2027-01-01\t甲\tbackup"])
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a11_unknown_target_in_event(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7").raw_events(["2026-09-01\t乙\tbackup"])
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a12_bad_event_kind(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7").raw_events(["2026-09-01\t甲\tsync"])
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 2)

    def test_a13_empty_targets_exit3(self):
        t = Tmp().raw_targets(["# 注释"]).e("2026-09-01", "甲", "backup")
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 3)

    def test_a14_empty_events_exit3(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7").raw_events(["# 只有注释"])
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 3)

    def test_a15_comments_and_blank_skipped(self):
        t = Tmp().raw_targets(["# 注释", "", "甲\tphotos\tdisk\thome\t7"])
        t.raw_events(["", "# 注释", "2026-09-01\t甲\tbackup", "2026-09-01\t甲\tverify"])
        _, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 4)  # 单副本不达标
        self.assertIn("photos", run(["fresh", *t.paths, "--today", TODAY])[0])


# ---------------------------------------------------------------------------
# B 新鲜度：FRESH / STALE / ROTTEN / UNKNOWN
# ---------------------------------------------------------------------------

class TestFreshness(unittest.TestCase):
    def grade_for(self, days, cadence="7"):
        t = Tmp().t("甲", "photos", "disk", "home", cadence)
        t.e(f"2026-09-04" if days == 0 else
            dt.date(2026, 9, 4) - dt.timedelta(days=days), "甲", "backup")
        t.e("2026-09-03", "甲", "verify")
        tp, ep = t.paths
        targets = paper_shield.load_targets(tp)
        events = paper_shield.load_events(ep, targets, dt.date(2026, 9, 4))
        return paper_shield.freshness(
            paper_shield.latest_event(events, "甲", "backup"),
            targets["甲"], dt.date(2026, 9, 4))

    def test_b01_fresh(self):
        self.assertEqual(self.grade_for(3)[0], "FRESH")

    def test_b02_stale(self):
        self.assertEqual(self.grade_for(10)[0], "STALE")

    def test_b03_rotten(self):
        self.assertEqual(self.grade_for(26)[0], "ROTTEN")

    def test_b04_boundaries(self):
        self.assertEqual(self.grade_for(7)[0], "FRESH")     # 恰 1× 周期
        self.assertEqual(self.grade_for(8)[0], "STALE")
        self.assertEqual(self.grade_for(14)[0], "STALE")    # 恰 2× 周期
        self.assertEqual(self.grade_for(15)[0], "ROTTEN")

    def test_b05_unknown(self):
        # 无周期不判
        t = Tmp().t("甲", "photos", "disk", "home", "-")
        t.e("2026-01-01", "甲", "backup")
        t.e("2026-09-01", "甲", "verify")
        tp, ep = t.paths
        targets = paper_shield.load_targets(tp)
        events = paper_shield.load_events(ep, targets, dt.date(2026, 9, 4))
        grade, d = paper_shield.freshness(
            paper_shield.latest_event(events, "甲", "backup"),
            targets["甲"], dt.date(2026, 9, 4))
        self.assertEqual(grade, "UNKNOWN")
        self.assertEqual(d, 246)
        # 无 backup 事件不判
        t2 = Tmp().t("乙", "art", "disk", "home", "7")
        t2.e("2026-09-01", "乙", "verify")
        tp, ep = t2.paths
        targets = paper_shield.load_targets(tp)
        events = paper_shield.load_events(ep, targets, dt.date(2026, 9, 4))
        grade, d = paper_shield.freshness(
            paper_shield.latest_event(events, "乙", "backup"),
            targets["乙"], dt.date(2026, 9, 4))
        self.assertEqual(grade, "UNKNOWN")
        self.assertIsNone(d)


# ---------------------------------------------------------------------------
# C 3-2-1 审计：副本 / 介质 / 异地
# ---------------------------------------------------------------------------

class TestThree21(unittest.TestCase):
    def audit_one(self, rows, event_rows=None):
        t = Tmp().raw_targets(rows)
        t.raw_events(event_rows or ["2026-09-03\t甲\tbackup", "2026-09-03\t甲\tverify",
                                    "2026-09-03\t乙\tbackup", "2026-09-03\t乙\tverify",
                                    "2026-09-03\t丙\tbackup", "2026-09-03\t丙\tverify"])
        tp, ep = t.paths
        targets = paper_shield.load_targets(tp)
        events = paper_shield.load_events(ep, targets, dt.date(2026, 9, 4))
        return paper_shield.audit_scope(targets, events, "photos", dt.date(2026, 9, 4))

    def test_c01_copies_and_media_and_offsite(self):
        a = self.audit_one([
            "甲\tphotos\tdisk\thome\t7", "乙\tphotos\tnas\thome\t7",
            "丙\tphotos\tcloud\tcloud\t7"])
        self.assertEqual(a["copies"], 3)
        self.assertEqual(a["media"], ["cloud", "disk", "nas"])
        self.assertEqual(a["offsite"], 1)
        self.assertTrue(a["ok_321"])

    def test_c02_same_media_is_fake_redundancy(self):
        a = self.audit_one([
            "甲\tphotos\tdisk\thome\t7", "乙\tphotos\tdisk\toffsite\t7",
            "丙\tphotos\tdisk\tcloud\t7"])
        # cloud 上的也叫 disk 介质：介质单一 → 不达标
        self.assertEqual(len(a["media"]), 1)
        self.assertFalse(a["ok_321"])

    def test_c03_office_is_not_offsite(self):
        a = self.audit_one([
            "甲\tphotos\tdisk\thome\t7", "乙\tphotos\tnas\toffice\t7",
            "丙\tphotos\ttape\toffice\t7"])
        self.assertEqual(a["offsite"], 0)
        self.assertFalse(a["ok_321"])

    def test_c04_offsite_and_cloud_both_count(self):
        a = self.audit_one([
            "甲\tphotos\tdisk\thome\t7", "乙\tphotos\tnas\toffsite\t7",
            "丙\tphotos\ttape\tcloud\t7"])
        self.assertEqual(a["offsite"], 2)
        self.assertTrue(a["ok_321"])


# ---------------------------------------------------------------------------
# D 验证与演练信用
# ---------------------------------------------------------------------------

class TestCredit(unittest.TestCase):
    def load(self, t):
        tp, ep = t.paths
        targets = paper_shield.load_targets(tp)
        events = paper_shield.load_events(ep, targets, dt.date(2026, 9, 4))
        return targets, events

    def test_d01_never_verified_listed(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7").e("2026-09-01", "甲", "backup")
        targets, events = self.load(t)
        a = paper_shield.audit_scope(targets, events, "photos", dt.date(2026, 9, 4))
        self.assertEqual(a["never_verified"], ["甲"])
        self.assertTrue(a["unverified_any"])

    def test_d02_verified_has_record(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7")
        t.e("2026-09-01", "甲", "backup").e("2026-06-01", "甲", "verify")
        targets, events = self.load(t)
        a = paper_shield.audit_scope(targets, events, "photos", dt.date(2026, 9, 4))
        self.assertEqual(a["never_verified"], [])
        self.assertEqual(a["verified"], ["甲"])

    def test_d03_drilled_count(self):
        t = green_tmp()
        targets, events = self.load(t)
        a = paper_shield.audit_scope(targets, events, "photos", dt.date(2026, 9, 4))
        self.assertEqual(a["drilled"], 1)


# ---------------------------------------------------------------------------
# E audit 命令：门禁与文案
# ---------------------------------------------------------------------------

class TestAuditCommand(unittest.TestCase):
    def test_e01_red_exit4_with_all_three_reasons(self):
        text, code = run(["audit", EX_T, EX_E, "--today", TODAY])
        self.assertEqual(code, 4)
        self.assertIn("ROTTEN", text)
        self.assertIn("从未验证", text)
        self.assertIn("3-2-1 不达标", text)
        self.assertIn("静默断链", text)

    def test_e02_green_exit0(self):
        t = green_tmp()
        text, code = run(["audit", *t.paths, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("GREEN", text)

    def test_e03_disclaimer_always_present(self):
        for t in (Tmp().t("甲", "x", "disk", "home", "7").e("2026-09-01", "甲", "backup"),):
            text, _ = run(["audit", *t.paths, "--today", TODAY])
            self.assertIn("不扫描磁盘", text)
        text, _ = run(["audit", EX_T, EX_E, "--today", TODAY])
        self.assertIn("不扫描磁盘", text)


# ---------------------------------------------------------------------------
# F simulate dead：灾难推演
# ---------------------------------------------------------------------------

class TestSimulate(unittest.TestCase):
    def test_f01_rpo_pinned(self):
        text, code = run(["simulate", EX_T, EX_E, "dead", "disk", "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("最坏丢最近 2 天（RPO）", text)    # photos：照片云 2 天前
        self.assertIn("最坏丢最近 26 天（RPO）", text)   # art：NAS·作品 26 天前
        self.assertIn("最坏丢最近 5 天（RPO）", text)    # docs：NAS·文档 5 天前
        self.assertIn("从未验证：照片云", text)
        self.assertIn("工位冷备盘", text)                 # 被推掉的目标被点名

    def test_f02_total_loss(self):
        t = Tmp().t("孤本", "photos", "disk", "home", "7")
        t.t("另盘", "art", "nas", "home", "7")
        t.e("2026-09-01", "孤本", "backup").e("2026-09-01", "另盘", "backup")
        t.e("2026-09-01", "孤本", "verify")
        text, code = run(["simulate", *t.paths, "dead", "disk", "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("全灭", text)
        self.assertIn("单点不叫备份，叫侥幸", text)

    def test_f03_unknown_medium_exit3(self):
        _, code = run(["simulate", EX_T, EX_E, "dead", "tape", "--today", TODAY])
        self.assertEqual(code, 3)

    def test_f04_bad_scenario_exit2(self):
        _, code = run(["simulate", EX_T, EX_E, "flood", "disk", "--today", TODAY])
        self.assertEqual(code, 2)


# ---------------------------------------------------------------------------
# G drills：演练史
# ---------------------------------------------------------------------------

class TestDrills(unittest.TestCase):
    def test_g01_no_drill_ever(self):
        t = Tmp().t("甲", "photos", "disk", "home", "7").e("2026-09-01", "甲", "backup")
        text, code = run(["drills", *t.paths, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("第一次彩排排在灾难当天", text)

    def test_g02_drill_counted(self):
        text, code = run(["drills", EX_T, EX_E, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("1/8", text)
        self.assertIn("107 天前", text)  # 文档云的 drill


# ---------------------------------------------------------------------------
# H validate / terms
# ---------------------------------------------------------------------------

class TestMeta(unittest.TestCase):
    def test_h01_validate_counts(self):
        text, code = run(["validate", EX_T, EX_E, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("8 个目标", text)
        self.assertIn("13 条事件", text)
        self.assertIn("backup ×8", text)
        self.assertIn("drill ×1", text)

    def test_h02_terms(self):
        text, code = run(["terms"])
        self.assertEqual(code, 0)
        for term in ("3-2-1", "RPO", "RTO", "verify", "drill", "ROTTEN", "异地"):
            self.assertIn(term, text)


# ---------------------------------------------------------------------------
# I 可复现性与版本
# ---------------------------------------------------------------------------

class TestRepro(unittest.TestCase):
    def test_i01_today_pins_output(self):
        argv = ["audit", EX_T, EX_E, "--today", TODAY]
        r1 = run(argv)
        r2 = run(argv)
        self.assertEqual(r1, r2)

    def test_i02_version(self):
        with self.assertRaises(SystemExit) as cm:
            run(["--version"])
        self.assertEqual(cm.exception.code, 0)


# ---------------------------------------------------------------------------
# J 示例账本端到端（阿May：8 目标 3 内容域 13 条事件）
# ---------------------------------------------------------------------------

class TestExample(unittest.TestCase):
    def test_j01_photos_looks_safe_but_is_red(self):
        text, code = run(["audit", EX_T, EX_E, "--today", TODAY])
        self.assertEqual(code, 4)
        # photos 3-2-1 达标（3 副本 3 介质含异地）却仍 RED：ROTTEN + 云从未验证
        self.assertIn("ROTTEN（NAS·照片 静默断链）", text)
        self.assertIn("从未验证（照片云）", text)
        self.assertIn("判定  RED", text)

    def test_j02_fresh_grades_all_present(self):
        text, _ = run(["fresh", EX_T, EX_E, "--today", TODAY])
        self.assertIn("ROTTEN", text)
        self.assertIn("STALE", text)
        self.assertIn("FRESH", text)
        self.assertIn("26 天前（周期 7）", text)
        self.assertIn("170 天前（周期 90）", text)

    def test_j03_drill_story(self):
        text, _ = run(["drills", EX_T, EX_E, "--today", TODAY])
        self.assertIn("1/8", text)          # 只有文档云演练过
        self.assertIn("107 天前", text)     # 文档云的 drill 距今


if __name__ == "__main__":
    unittest.main()
