#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iou · 欠条 —— 验收测试.

每一条验收标准都钉成测试:解析体检(行号 exit 2)、FIFO 重放体检
(回款/销账/催讨越界)、恒等式与双算法、P90 标定与通识垫底、时效
起算与催讨续命、判级阶梯恰线语义、as-of 时间机器、薄账分层、
零墙钟逐字节复现、纯标准库。

样例账本常量(as-of 2026-05-20,手算钉死):
  借出 36,300(7) − 回款 15,800(5) − 销账 1,000(1) = 敞口 19,500
  周期样本 [28, 32, 118, 179, 376] → P50 118.0 · P90 297.2
  表哥·阿伟 余额 16,000(#1 未清 12,000 已 1320 天;#2 4,000 已 171 天)
    时效:#1 起算 2025-08-15(催讨重置)→ 2028-08-15(余 818)
         #2 起算 2025-11-30(借出日)→ 2028-11-30(余 925)
  发小·强子 余额 2,000 · 起算 2025-01-20 → 2028-01-20(余 610)
  前室友·阿凯 余额 1,500 · 从未催讨 → 2027-08-02(余 439)
  小蔡 周期 32/179 · 静静 周期 28 · 均已清
"""

import ast
import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.abspath(__file__)), ".."))
import iou  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "..", "examples", "iou.tsv")
ASOF = ["--as-of", "2026-05-20"]


def run(argv):
    """跑 CLI,返回 (exit_code, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = iou.main(argv)
    return code, out.getvalue(), err.getvalue()


class TmpMixin:
    def ledger(self, text):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.unlink, path)
        return path


# ================================================================ A 解析


class ParseTests(TmpMixin, unittest.TestCase):
    def test_a1_sample_counts(self):
        evs = iou.parse_ledger(SAMPLE)
        kinds = [e.kind for e in evs]
        self.assertEqual(kinds.count(iou.LEND), 7)
        self.assertEqual(kinds.count(iou.REPAY), 5)
        self.assertEqual(kinds.count(iou.CHASE), 2)
        self.assertEqual(kinds.count(iou.FORGIVE), 1)
        self.assertEqual(len(evs), 15)

    def test_a2_header_and_comments_skipped(self):
        path = self.ledger(
            "# 注释行\ndate\tkind\twho\tamount\n\n"
            "2026-01-01\tlend\t甲\t100\n")
        self.assertEqual(len(iou.parse_ledger(path)), 1)

    def test_a3_four_and_five_col_rows(self):
        path = self.ledger(
            "2026-01-01\tlend\t甲\t100\n"
            "2026-01-02\tlend\t乙\t200\t有备注无约定\n")
        evs = iou.parse_ledger(path)
        self.assertEqual([e.note for e in evs], ["", "有备注无约定"])
        self.assertTrue(all(e.promised is None for e in evs))

    def test_a4_col_count_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\n")])
        self.assertEqual(code, 2)
        self.assertIn("需要 4-6 列", err)

    def test_a5_bad_date_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026/01/01\tlend\t甲\t100\n")])
        self.assertEqual(code, 2)
        self.assertIn("YYYY-MM-DD", err)

    def test_a6_unknown_kind_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tborrow\t甲\t100\n")])
        self.assertEqual(code, 2)
        self.assertIn("kind", err)

    def test_a7_empty_who_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tlend\t   \t100\n")])
        self.assertEqual(code, 2)
        self.assertIn("人名", err)

    def test_a8_non_numeric_amount_exit2(self):
        code, _, _ = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t很多\n")])
        self.assertEqual(code, 2)

    def test_a9_nonpositive_lend_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t0\n")])
        self.assertEqual(code, 2)
        self.assertIn("借出", err)

    def test_a10_chase_with_amount_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t100\n"
            "2026-02-01\tchase\t甲\t50\n")])
        self.assertEqual(code, 2)
        self.assertIn("催讨行不带金额", err)

    def test_a11_chase_zero_ok(self):
        path = self.ledger(
            "2026-01-01\tlend\t甲\t100\n"
            "2026-02-01\tchase\t甲\t0\t提了一嘴\n")
        evs = iou.parse_ledger(path)
        self.assertEqual(evs[1].amount, 0.0)

    def test_a12_forgive_nonpositive_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t100\n"
            "2026-02-01\tforgive\t甲\t0\n")])
        self.assertEqual(code, 2)
        self.assertIn("销账", err)

    def test_a13_promised_on_non_lend_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t100\n"
            "2026-02-01\trepay\t甲\t100\t\t2026-03-01\n")])
        self.assertEqual(code, 2)
        self.assertIn("只对借出行", err)

    def test_a14_promised_before_lend_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t100\t\t2025-12-01\n")])
        self.assertEqual(code, 2)
        self.assertIn("约定不能穿越", err)

    def test_a15_promised_bad_format_exit2(self):
        code, _, _ = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t100\t\t过年前\n")])
        self.assertEqual(code, 2)

    def test_a16_repay_without_lend_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\trepay\t甲\t100\n")])
        self.assertEqual(code, 2)
        self.assertIn("从无借出", err)

    def test_a17_repay_exceeds_outstanding_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t100\n"
            "2026-02-01\trepay\t甲\t150\n")])
        self.assertEqual(code, 2)
        self.assertIn("超过", err)
        self.assertIn("未清", err)

    def test_a18_forgive_exceeds_outstanding_exit2(self):
        code, _, _ = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t100\n"
            "2026-02-01\tforgive\t甲\t120\n")])
        self.assertEqual(code, 2)

    def test_a19_chase_without_outstanding_exit2(self):
        code, _, err = run(["report", self.ledger(
            "2026-01-01\tlend\t甲\t100\n"
            "2026-02-01\trepay\t甲\t100\n"
            "2026-03-01\tchase\t甲\t0\n")])
        self.assertEqual(code, 2)
        self.assertIn("无从催起", err)

    def test_a20_same_day_events_ok(self):
        path = self.ledger(
            "2026-01-01\tlend\t甲\t100\n"
            "2026-01-01\trepay\t甲\t100\n")
        self.assertEqual(len(iou.parse_ledger(path)), 2)

    def test_a21_out_of_order_sorted(self):
        path = self.ledger(
            "2026-03-01\tlend\t乙\t100\n"
            "2026-01-01\tlend\t甲\t100\n")
        evs = iou.parse_ledger(path)
        self.assertEqual([e.who for e in evs], ["甲", "乙"])

    def test_a22_who_normalized(self):
        path = self.ledger(
            "2026-01-01\tlend\t  Alice  \t100\n"
            "2026-02-01\trepay\talice\t100\n")
        people = iou.replay(iou.parse_ledger(path))
        self.assertIn("alice", people)
        self.assertEqual(len(people), 1)

    def test_a23_chinese_kind_aliases(self):
        path = self.ledger(
            "2026-01-01\t借出\t甲\t100\n"
            "2026-02-01\t还款\t甲\t60\n"
            "2026-03-01\t催讨\t甲\t0\n"
            "2026-04-01\t销账\t甲\t40\n")
        evs = iou.parse_ledger(path)
        self.assertEqual([e.kind for e in evs],
                         [iou.LEND, iou.REPAY, iou.CHASE, iou.FORGIVE])

    def test_a24_missing_file_exit2(self):
        code, _, err = run(["report", "/nonexistent/iou.tsv"])
        self.assertEqual(code, 2)
        self.assertIn("打不开", err)

    def test_a25_dash_note_treated_as_empty_promised(self):
        path = self.ledger("2026-01-01\tlend\t甲\t100\t备注\t-\n")
        evs = iou.parse_ledger(path)
        self.assertEqual(evs[0].promised, None)
        self.assertEqual(evs[0].note, "备注")


# ================================================================ B 数学


class MathTests(TmpMixin, unittest.TestCase):
    def test_b1_percentile_hand_check(self):
        self.assertEqual(iou.percentile([10, 20, 30, 40], 0.5), 25.0)
        self.assertEqual(iou.percentile([10, 20, 30, 40], 0.9), 37.0)
        self.assertEqual(iou.percentile([7], 0.9), 7.0)
        self.assertEqual(iou.percentile([], 0.9), 0.0)

    def test_b2_sample_cycles_exact(self):
        _, people = iou._load(SAMPLE, date(2026, 5, 20), 3)
        cycles = sorted(c for p in people.values() for c in p.cycles)
        self.assertEqual(cycles, [28, 32, 118, 179, 376])

    def test_b3_p50_p90_and_line(self):
        _, people = iou._load(SAMPLE, date(2026, 5, 20), 3)
        cycles = tuple(c for p in people.values() for c in p.cycles)
        line, source = iou.due_line(cycles, 90)
        self.assertEqual(source, "P90")
        self.assertAlmostEqual(line, 297.2, places=6)
        line2, source2 = iou.due_line(cycles[:2], 90)
        self.assertEqual((line2, source2), (90.0, "folk"))
        line3, source3 = iou.due_line((), 45)
        self.assertEqual((line3, source3), (45.0, "folk"))

    def test_b4_exposure_identity(self):
        _, people = iou._load(SAMPLE, date(2026, 5, 20), 3)
        lent = sum(p.lent for p in people.values())
        repaid = sum(p.repaid for p in people.values())
        forgiven = sum(p.forgiven for p in people.values())
        exposure = lent - repaid - forgiven
        self.assertAlmostEqual(lent, 36300.0, places=6)
        self.assertAlmostEqual(repaid, 15800.0, places=6)
        self.assertAlmostEqual(forgiven, 1000.0, places=6)
        self.assertAlmostEqual(exposure, 19500.0, places=6)
        balances = sum(sum(o.remaining for o in p.opens)
                       for p in people.values())
        self.assertAlmostEqual(balances, exposure, places=6)

    def test_b5_fifo_partial_and_second_lend(self):
        _, people = iou._load(SAMPLE, date(2026, 5, 20), 3)
        wei = people["表哥·阿伟"]
        self.assertAlmostEqual(wei.lent, 24000.0, places=6)
        self.assertAlmostEqual(wei.repaid, 8000.0, places=6)
        self.assertAlmostEqual(wei.opens[0].remaining, 12000.0, places=6)
        self.assertAlmostEqual(wei.opens[1].remaining, 4000.0, places=6)

    def test_b6_fifo_drain_and_overflow(self):
        path = self.ledger(
            "2026-01-01\tlend\t甲\t3000\n"
            "2026-02-01\trepay\t甲\t1000\n"
            "2026-03-01\trepay\t甲\t1000\n"
            "2026-04-01\trepay\t甲\t1000\n")
        people = iou.replay(iou.parse_ledger(path))
        self.assertEqual(len(people["甲"].opens), 0)
        # 周期口径 = 距最老未清借出日(三笔回款都在清同一笔借出)
        self.assertEqual(people["甲"].cycles, (31, 59, 90))
        path_bad = self.ledger(
            "2026-01-01\tlend\t甲\t3000\n"
            "2026-04-01\trepay\t甲\t3000\n"
            "2026-05-01\trepay\t甲\t1\n")
        with self.assertRaises(iou.LedgerError):
            iou.replay(iou.parse_ledger(path_bad))

    def test_b7_statute_base_rules(self):
        _, people = iou._load(SAMPLE, date(2026, 5, 20), 3)
        wei = people["表哥·阿伟"]
        # #1:chase 2025-08-15 晚于约定日 → 催讨重置
        self.assertEqual(wei.opens[0].base, date(2025, 8, 15))
        self.assertEqual(wei.opens[0].base_kind, "催讨重置")
        self.assertEqual(wei.opens[0].deadline, date(2028, 8, 15))
        # #2:chase 早于借出日 → 抬不动,落在借出日
        self.assertEqual(wei.opens[1].base, date(2025, 11, 30))
        self.assertEqual(wei.opens[1].base_kind, "借出日")
        # 无约定日 + 从未催讨 → 借出日起算(阿凯)
        kai = people["前室友·阿凯"]
        self.assertEqual(kai.opens[0].base, date(2024, 8, 2))
        self.assertEqual(kai.opens[0].deadline, date(2027, 8, 2))
        # 有约定日 + 催讨更早 → 约定日起算
        base, kind = iou.statute_base(
            date(2024, 1, 1), date(2024, 6, 1), (date(2024, 3, 1),))
        self.assertEqual((base, kind), (date(2024, 6, 1), "约定日"))

    def test_b8_add_years_leap(self):
        self.assertEqual(iou.add_years(date(2024, 2, 29), 1),
                         date(2025, 3, 1))
        self.assertEqual(iou.add_years(date(2024, 2, 29), 4),
                         date(2028, 2, 29))
        self.assertEqual(iou.add_years(date(2022, 10, 8), 3),
                         date(2025, 10, 8))

    def test_b9_days_left_hand_check(self):
        _, people = iou._load(SAMPLE, date(2026, 5, 20), 3)
        wei = people["表哥·阿伟"]
        self.assertEqual((wei.opens[0].deadline - date(2026, 5, 20)).days,
                         818)
        self.assertEqual((wei.opens[1].deadline - date(2026, 5, 20)).days,
                         925)
        qiang = people["发小·强子"]
        self.assertEqual((qiang.opens[0].deadline - date(2026, 5, 20)).days,
                         610)
        kai = people["前室友·阿凯"]
        self.assertEqual((kai.opens[0].deadline - date(2026, 5, 20)).days,
                         439)

    def test_b10_repay_rates(self):
        _, people = iou._load(SAMPLE, date(2026, 5, 20), 3)
        self.assertAlmostEqual(people["表哥·阿伟"].repaid
                               / people["表哥·阿伟"].lent, 8000 / 24000)
        self.assertEqual(people["前室友·阿凯"].repaid, 0.0)
        self.assertEqual(people["同事·小蔡"].repaid,
                         people["同事·小蔡"].lent)

    def test_b11_statute_double_algorithm(self):
        evs = iou.parse_ledger(SAMPLE)
        evs = iou.cutoff(evs, date(2026, 5, 20))
        people = iou.attach_opens(iou.replay(evs), 3)
        stream = iou.statute_stream(evs)
        for p in people.values():
            for o in p.opens:
                self.assertEqual(stream[(p.name, o.line)], o.base)
                self.assertEqual(iou.add_years(o.base, 3), o.deadline)

    def test_b12_judge_boundaries(self):
        asof = date(2026, 1, 1)
        line, warn = 100.0, 90

        def mk(deadline, lend_date):
            return (iou.Open(date=lend_date, promised=None, orig=1000,
                             remaining=1000, line=1, note="",
                             base=lend_date, deadline=deadline,
                             base_kind="借出日"),)

        self.assertEqual(iou.judge_opens(mk(asof, asof), asof, line, warn),
                         iou.PASSED)
        self.assertEqual(
            iou.judge_opens(
                mk(date(2025, 12, 25), date(2025, 10, 3)),
                asof, line, warn),
            iou.PASSED)  # 已过届满日
        self.assertEqual(
            iou.judge_opens(
                mk(date(2026, 4, 1), date(2025, 10, 1)), asof, line, warn),
            iou.SOON)  # 余 90 恰入危险区
        self.assertEqual(
            iou.judge_opens(
                mk(date(2026, 4, 2), date(2025, 9, 23)), asof, line, warn),
            iou.OK)  # 余 91,恰线外;账龄 100 恰线内
        self.assertEqual(
            iou.judge_opens(
                mk(date(2026, 4, 2), date(2025, 9, 22)), asof, line, warn),
            iou.STALE)  # 账龄 101 > 100
        self.assertEqual(iou.judge_opens((), asof, line, warn), iou.CLEAR)

    def test_b13_exposure_translation(self):
        code, out, _ = run(["report", SAMPLE] + ASOF
                           + ["--monthly-spend", "6000"])
        self.assertEqual(code, 4)
        self.assertIn("3.2 个月生活费", out)
        self.assertIn("EXPOSED", out)
        code, out, _ = run(["report", SAMPLE] + ASOF
                           + ["--monthly-spend", "12000"])
        self.assertNotIn("EXPOSED", out)
        self.assertIn("1.6 个月", out)


# ================================================================ C 命令


class CommandTests(TmpMixin, unittest.TestCase):
    def test_c1_report_stale_exit4(self):
        code, out, _ = run(["report", SAMPLE] + ASOF)
        self.assertEqual(code, 4)
        self.assertIn("敞口 ¥19,500", out)
        self.assertIn("残差 0.000000", out)
        self.assertIn("催收线 297.2 天", out)
        self.assertIn("P90 297.2 天", out)
        self.assertIn("判定 STALE", out)
        self.assertIn("¥16,000", out)
        self.assertIn("33.3%", out)

    def test_c2_report_green(self):
        path = self.ledger(
            "2026-01-01\tlend\t甲\t1000\n"
            "2026-02-01\trepay\t甲\t1000\n")
        code, out, _ = run(["report", path, "--as-of", "2026-03-01"])
        self.assertEqual(code, 0)
        self.assertIn("判定 GREEN", out)
        self.assertIn("催收线 90.0 天(通识垫底", out)

    def test_c3_report_statute_time_machine(self):
        code, out, _ = run(["report", SAMPLE,
                            "--as-of", "2028-09-01"])
        self.assertEqual(code, 4)
        self.assertIn("判定 STATUTE", out)
        self.assertIn("时效已过", out)
        self.assertIn("睡觉", out)

    def test_c4_report_statute_soon(self):
        # --statute-years 2:阿凯 2026-08-02 届满,余 74 天 ≤ 90
        code, out, _ = run(["report", SAMPLE] + ASOF
                           + ["--statute-years", "2"])
        self.assertEqual(code, 4)
        self.assertIn("判定 STATUTE-SOON", out)
        self.assertIn("前室友·阿凯", out)

    def test_c5_report_banners(self):
        code, out, _ = run(["report", SAMPLE] + ASOF)
        self.assertNotIn("EXPOSED", out)  # 没给 --monthly-spend 不谈钱
        code, out, _ = run(["report", SAMPLE] + ASOF
                           + ["--monthly-spend", "6000"])
        self.assertIn("EXPOSED", out)

    def test_c6_soft_hearted_banner(self):
        path = self.ledger(
            "2025-01-01\tlend\t甲\t2000\n"
            "2025-01-01\tlend\t乙\t500\n"
            "2025-06-01\tforgive\t甲\t1500\n")
        code, out, _ = run(["report", path, "--as-of", "2025-07-01"])
        self.assertIn("人情化率", out)
        self.assertIn("60.0%", out)
        self.assertIn("SOFT-HEARTED", out)

    def test_c7_book_details(self):
        code, out, _ = run(["book", SAMPLE] + ASOF)
        self.assertEqual(code, 0)
        self.assertIn("「表哥·阿伟」未清 ¥16,000", out)
        self.assertIn("#1 2022-10-08 借出 ¥20,000,约定 2023-02-01",
                      out)
        self.assertIn("未清 ¥12,000 · 已 1,320天(超线 1023 天)", out)
        self.assertIn("催讨重置", out)
        self.assertIn("「同事·小蔡」已清 · 2 借 2 还 ¥5,000 · 周期 32/179 天",
                      out)
        self.assertIn("「前室友·阿凯」未清 ¥1,500", out)

    def test_c8_nudge_exit4_and_sheets(self):
        code, out, _ = run(["nudge", SAMPLE] + ASOF)
        self.assertEqual(code, 4)
        self.assertIn("催收线 297.2 天(P90)", out)
        self.assertIn("3 人 3 笔超线 ¥15,500", out)
        self.assertIn("给「表哥·阿伟」的事实底稿", out)
        self.assertIn("说好 2023-02-01 还", out)
        self.assertIn("催讨记录:2025-08-15", out)
        self.assertIn("从未催讨过", out)
        self.assertIn("记一行 chase", out)

    def test_c9_nudge_clean_exit0(self):
        path = self.ledger(
            "2026-05-01\tlend\t甲\t1000\n"
            "2026-06-01\trepay\t甲\t1000\n"
            "2026-06-02\tlend\t乙\t500\n")
        code, out, _ = run(["nudge", path, "--as-of", "2026-06-10"])
        self.assertEqual(code, 0)
        self.assertIn("无单可开", out)

    def test_c10_should_caution(self):
        code, out, _ = run(["should", SAMPLE, "--who", "表哥·阿伟",
                            "--amount", "4000", "--as-of", "2025-11-29"])
        self.assertEqual(code, 4)
        self.assertIn("判定 CAUTION", out)
        self.assertIn("40.0%", out)
        self.assertIn("¥12,000 未清", out)
        self.assertIn("1,148天", out)

    def test_c11_should_green_and_first(self):
        code, out, _ = run(["should", SAMPLE, "--who", "同事·小蔡",
                            "--amount", "3000", "--as-of", "2024-06-01"])
        self.assertEqual(code, 0)
        self.assertIn("判定 GREEN", out)
        code, out, _ = run(["should", SAMPLE, "--who", "老王",
                            "--amount", "5000"] + ASOF)
        self.assertEqual(code, 0)
        self.assertIn("判定 FIRST", out)
        self.assertIn("没有这个名字", out)

    def test_c12_should_exactly_half_no_alarm(self):
        # 恰 50% 回款率:宁少报,不亮 CAUTION(仓库恰线语义)
        path = self.ledger(
            "2025-01-01\tlend\t甲\t2000\n"
            "2025-02-01\trepay\t甲\t1000\n")
        code, out, _ = run(["should", path, "--who", "甲",
                            "--amount", "1000",
                            "--as-of", "2025-06-01"])
        self.assertEqual(code, 0)
        self.assertIn("判定 GREEN", out)
        self.assertIn("50.0%", out)

    def test_c13_should_bad_amount_exit2(self):
        code, _, err = run(["should", SAMPLE, "--who", "老王",
                            "--amount", "0"] + ASOF)
        self.assertEqual(code, 2)
        self.assertIn("> 0", err)

    def test_c14_validate_clean(self):
        code, out, _ = run(["validate", SAMPLE] + ASOF)
        self.assertEqual(code, 0)
        self.assertIn("借出 7 · 回款 5 · 催讨 2 · 销账 1", out)
        self.assertIn("残差 0.000000", out)
        self.assertIn("最大漂移 0.000000", out)
        self.assertIn("4 笔未清,0 笔不一致", out)
        self.assertIn("通识先验", out)
        self.assertIn("人情化率 2.8%", out)

    def test_c15_asof_cut_semantics(self):
        # as-of 剪切含边界 ≤:恰当日事件仍在账
        code, out, _ = run(["report", SAMPLE, "--as-of", "2026-05-20"])
        self.assertIn("15 笔事件", out)
        # 剪掉 forgive 与最后笔 → 敞口变化(时间机器回放)
        code, out, _ = run(["report", SAMPLE, "--as-of", "2026-05-19"])
        self.assertIn("14 笔事件", out)
        self.assertIn("敞口 ¥20,500", out)  # 强子的 1000 销账消失
        # 早于首笔 → 拒答 exit 3
        code, _, err = run(["report", SAMPLE, "--as-of", "2022-01-01"])
        self.assertEqual(code, 3)
        self.assertIn("时间机器", err)

    def test_c16_default_asof_is_ledger_end(self):
        code, out, _ = run(["report", SAMPLE])
        self.assertIn("as-of 2026-05-20(账本末日)", out)

    def test_c17_bad_asof_format_exit2(self):
        code, _, err = run(["report", SAMPLE, "--as-of", "2026/05/20"])
        self.assertEqual(code, 2)
        self.assertIn("--as-of", err)

    def test_c18_empty_ledger_refusal(self):
        path = self.ledger("# 只有注释\n")
        code, _, err = run(["report", path])
        self.assertEqual(code, 3)
        self.assertIn("账本是空的", err)

    def test_c19_version_and_usage(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stdout(out):
                iou.main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("iou 1.0.0", out.getvalue())
        for argv in ([], ["no-such-cmd"], ["report"]):
            err = io.StringIO()
            with self.assertRaises(SystemExit) as cm:
                with contextlib.redirect_stderr(err):
                    iou.main(argv)
            self.assertEqual(cm.exception.code, 2)


# ================================================================ D 工程


class EngineeringTests(TmpMixin, unittest.TestCase):
    def test_d1_byte_reproducible(self):
        a = run(["report", SAMPLE] + ASOF)
        b = run(["report", SAMPLE] + ASOF)
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1], b[1])
        for cmd in (["book"], ["nudge"], ["validate"]):
            x = run(cmd + [SAMPLE] + ASOF)
            y = run(cmd + [SAMPLE] + ASOF)
            self.assertEqual(x, y)

    def test_d2_basename_only(self):
        code, out, _ = run(["report", SAMPLE] + ASOF)
        self.assertIn("账本 iou.tsv", out)
        self.assertNotIn("examples", out)

    def test_d3_examples_constants(self):
        with open(SAMPLE, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("2022-10-08\tlend\t表哥·阿伟\t20000", text)
        self.assertIn("2026-05-20\tforgive\t发小·强子\t1000", text)
        self.assertEqual(len([ln for ln in text.splitlines()
                              if ln and not ln.startswith("#")
                              and ln.split("\t")[0] != "date"]), 15)

    def test_d4_stdlib_only(self):
        allowed = {"argparse", "datetime", "os", "re", "sys",
                   "unicodedata", "collections", "typing", "__future__"}
        src = os.path.join(HERE, "..", "iou.py")
        with open(src, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed,
                                  f"非标准库导入:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                self.assertIn((node.module or "").split(".")[0], allowed,
                              f"非标准库导入:{node.module}")

    def test_d5_no_wall_clock(self):
        with open(os.path.join(HERE, "..", "iou.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("date.today()", src)
        self.assertNotIn("datetime.now()", src)
        self.assertNotIn("time.time", src)

    def test_d6_zero_balance_person_not_in_nudge(self):
        # 已清的人不该出现在催收单,哪怕曾经超龄
        path = self.ledger(
            "2025-01-01\tlend\t甲\t1000\n"
            "2025-01-02\tchase\t甲\t0\n"
            "2025-12-01\trepay\t甲\t1000\n")
        code, out, _ = run(["nudge", path, "--as-of", "2025-12-15"])
        self.assertEqual(code, 0)
        self.assertIn("无单可开", out)

    def test_d7_chase_extends_statute(self):
        # 借出 2024-08-02:无 chase 时 2027-08-02 届满(余 53 天);
        # 2026-06-01 补一行 chase,起算重置 → 2029-06-01(余 722 天)
        base = "2024-08-02\tlend\t甲\t1500\n"
        late = "2026-06-01\tchase\t甲\t0\n"
        p1 = self.ledger(base)
        p2 = self.ledger(base + late)
        code1, out1, _ = run(["report", p1, "--as-of", "2027-06-10",
                              "--statute-warn", "365"])
        code2, out2, _ = run(["report", p2, "--as-of", "2027-06-10",
                              "--statute-warn", "365"])
        self.assertEqual(code1, 4)  # 余 53 天 ≤ 365 → 危险
        self.assertIn("时效将满", out1)
        self.assertEqual(code2, 4)  # 续命后余 722 天,退出危险区
        self.assertIn("超催收线", out2)
        self.assertNotIn("时效将满", out2)
        # 催收线放宽到通识 1100 天后,连超龄灯也熄了
        code3, out3, _ = run(["report", p2, "--as-of", "2027-06-10",
                              "--grace-days", "1100"])
        self.assertEqual(code3, 0)
        self.assertIn("判定 GREEN", out3)


if __name__ == "__main__":
    unittest.main()
