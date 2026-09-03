#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scapegoat · 替罪羊 — 验收测试.

验收标准（全部转成自动化测试）：
  A1  账本解析：坏行带行号 exit 2（列数/日期/attack 非法/未来日期/重复记账/文件缺失）
  A2  表头、注释行（#）与空行跳过
  A3  诚实条款：无记录日不进任何分母（对照臂 = 记录日 − 暴露日，缺席日不存在）
  A4  恒等式：每个嫌疑人 a_e + a_u = 总发作数，一天不多一天不少（示例账本全员核对）
  A5  lift 精确：rate_e ÷ rate_u；rate_u = 0 → ∞；双零 → 不显示
  A6  Fisher 精确检验：与手算超几何对表；p ∈ (0, 1]
  A7  THIN：任一臂 < 3 天 → 在逃，永不定罪也永不平反；全员在逃 → exit 3
  A8  平反门槛：暴露 ≥ 6 天且 lift ≤ 1.15 才平反；5 天清白不够格（监视名单·偏无辜）
  A9  定罪门禁：lift ≥ 2 且 p < 0.05/k → RED exit 4
  A10 Bonferroni / 唯一嫌疑人偏见：同一份证据，单独受审定罪（k=1），
      加 11 名陪审后 p 不再过家族线 → TENTATIVE，不触发门禁 exit 0
  A11 lift 达定罪线但 p 不显著 → 监视名单，不定罪
  A12 归因发作 = a_e − E×rate_u（示例缺睡 +6.3；平反者可为负）
  A13 无暴露发作占比：发作但零暴露的日子单独点名（示例 4/17）
  A14 judge：未知嫌疑人 exit 3（从未到庭）；平反卷宗含「在场未作案」
  A15 acquitted：示例 4 人含红酒；无人可平反时诚实输出 exit 0
  A16 case：案发夜点名定罪者；无发作日进分母；无暴露发作指向名单外；
      缺席日期 exit 3；坏日期 exit 2
  A17 simulate：定罪可推演且含诚实条款；THIN/监视名单/平反/未知 → exit 3
  A18 combo：共暴露 < 5 天不判；线索永不触发门禁
  A19 verdicts 排序确定（判决优先级 → 归因降序 → 名字）；零发作 exit 3；空账本 exit 3
  A20 --today 钉死逐字节可复现；未来日期拒收
  A21 零发作账本：judge/case/simulate/combo 一律 exit 3 拒绝
  A22 validate：覆盖率、缺席条款、暴露最多排行
  A23 嫌疑人名规范化：大小写/空白折叠；中英文逗号与顿号都作分隔
  A24 零依赖：只 import 标准库
"""

import contextlib
import io
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scapegoat as sg  # noqa: E402

TODAY = "2026-08-24"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(BASE, "examples", "diary.tsv")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sg.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def dates(n, start=(2026, 1, 1)):
    import datetime as dt
    d0 = dt.date(*start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write(self, text, name="d.tsv"):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path


class ParsingTests(LedgerTestCase):
    # A1 坏行
    def test_missing_file_exit_2(self):
        code, _, err = run_cli("verdicts", "/nonexistent/d.tsv", "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("打不开", err)

    def test_bad_column_count_exit_2(self):
        path = self.write("2026-01-01\t0\n")
        code, _, err = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("第 1 行", err)

    def test_bad_date_exit_2(self):
        path = self.write("2026-1-1\t0\t-\n")
        code, _, err = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("YYYY-MM-DD", err)

    def test_bad_attack_exit_2(self):
        path = self.write("2026-01-01\tyes\t-\n")
        code, _, err = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("0/1", err)

    def test_future_date_exit_2(self):
        path = self.write("2026-01-01\t0\t-\n2026-12-31\t0\t-\n")
        code, _, err = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("预写", err)

    def test_duplicate_date_exit_2(self):
        path = self.write("2026-01-01\t0\t-\n2026-01-01\t1\t缺睡\n")
        code, _, err = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("重复记账", err)

    # A2 表头/注释/空行
    def test_header_comments_blank_skipped(self):
        text = ("date\tattack\ttriggers\n"
                "# 一段备注\n"
                "\n"
                "2026-01-01\t0\t缺睡\n"
                "2026-01-02\t1\t缺睡\n")
        path = self.write(text)
        code, out, _ = run_cli("validate", path, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("2 个记录日", out)

    # A23 名字规范化与分隔
    def test_name_normalization_and_separators(self):
        text = ("2026-01-01\t0\t Latte 、红酒\n"
                "2026-01-02\t1\tlatte，RED WINE\n")
        path = self.write(text)
        entries = sg.parse_ledger(path, sg._today(type("A", (), {"today": None})()))
        self.assertEqual(entries[0].triggers, ("latte", "红酒"))
        self.assertEqual(entries[1].triggers, ("latte", "red wine"))

    def test_dash_and_empty_mean_no_exposure(self):
        path = self.write("2026-01-01\t0\t-\n2026-01-02\t0\t\n")
        entries = sg.parse_ledger(path, sg._today(type("A", (), {"today": None})()))
        self.assertEqual(entries[0].triggers, ())
        self.assertEqual(entries[1].triggers, ())


class StatsTests(LedgerTestCase):
    def ledger_12(self):
        # 12 个记录日：缺睡 3 天全发作，其余 9 天 1 次发作。
        d = dates(12)
        rows = []
        for i, day in enumerate(d):
            if i < 3:
                rows.append(f"{day}\t1\t缺睡")
            elif i == 3:
                rows.append(f"{day}\t1\t-")
            else:
                rows.append(f"{day}\t0\t-")
        return self.write("\n".join(rows) + "\n")

    # A3 无记录日不进分母
    def test_absent_days_not_in_denominator(self):
        d = dates(10)
        rows = [f"{d[i]}\t{1 if i == 0 else 0}\t{'缺睡' if i in (0, 1) else '-'}"
                for i in range(10) if i not in (8, 9)]  # 后两天缺席
        path = self.write("\n".join(rows) + "\n")
        entries = sg.parse_ledger(path, sg.dt.date(2026, 1, 10))
        suspects, _ = sg.prepare(entries)
        s = suspects["缺睡"]
        self.assertEqual(s.e, 2)
        self.assertEqual(s.u, 6)  # 8 个记录日 − 2 个暴露日；缺席两天不进对照

    # A4 恒等式
    def test_identity_attacks_split(self):
        entries = sg.parse_ledger(EXAMPLE, sg.dt.date(2026, 8, 24))
        attacks = sum(e.attack for e in entries)
        suspects, _ = sg.prepare(entries)
        for s in suspects.values():
            self.assertEqual(s.a_e + s.a_u, attacks)

    # A5 lift
    def test_lift_exact_and_infinite(self):
        entries = sg.parse_ledger(self.ledger_12(), sg.dt.date(2026, 1, 12))
        suspects, _ = sg.prepare(entries)
        s = suspects["缺睡"]
        self.assertAlmostEqual(s.rate_e, 1.0)
        self.assertAlmostEqual(s.rate_u, 1 / 9)
        self.assertAlmostEqual(s.lift, 9.0)
        # 造一本对照臂零发作的账：lift = ∞
        d = dates(10)
        rows = [f"{d[0]}\t1\tT"] + [f"{day}\t0\t-" for day in d[1:]]
        entries = sg.parse_ledger(self.write("\n".join(rows) + "\n"),
                                  sg.dt.date(2026, 1, 10))
        suspects, _ = sg.prepare(entries)
        self.assertEqual(suspects["t"].lift, math.inf)

    # A6 Fisher 精确
    def test_fisher_hand_computed(self):
        # a_e=3,E=3, a_u=1,U=9：P(X≥3) = C(4,3)C(8,0)/C(12,3) = 4/220
        p = sg.fisher_right(3, 3, 1, 9)
        self.assertAlmostEqual(p, 4 / 220)
        # a_e=2,E=5, a_u=4,U=5：p = 1 − C(6,1)C(4,4)/C(10,5) = 246/252
        p = sg.fisher_right(2, 5, 4, 5)
        self.assertAlmostEqual(p, 246 / 252)

    def test_fisher_bounds(self):
        self.assertEqual(sg.fisher_right(0, 5, 3, 5), 1.0)
        for args in ((3, 3, 1, 9), (1, 2, 16, 86), (8, 14, 9, 74)):
            p = sg.fisher_right(*args)
            self.assertTrue(0 < p <= 1.0)


class VerdictTests(LedgerTestCase):
    # A7 THIN
    def test_thin_never_convicted_never_acquitted(self):
        d = dates(20)
        rows = []
        for i, day in enumerate(d):
            trig = "奶酪" if i < 2 else "-"
            rows.append(f"{day}\t{1 if i in (0, 5) else 0}\t{trig}")
        path = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 3)  # 唯一嫌疑人在逃 → 全员 THIN，拒绝开庭
        self.assertIn("◌ 在逃", out)
        self.assertNotIn("✗ 定罪", out)
        self.assertNotIn("✓ 平反", out)
        entries = sg.parse_ledger(path, sg.dt.date(2026, 1, 20))
        suspects, _ = sg.prepare(entries)
        self.assertEqual(suspects["奶酪"].verdict, sg.SUSPECT)

    def test_all_thin_refuses_exit_3(self):
        d = dates(10)
        rows = [f"{d[i]}\t{1 if i == 0 else 0}\t{'A' if i in (0, 1) else '-'}"
                for i in range(10)]
        path = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("REFUSE", out)

    # A8 平反门槛
    def test_acquittal_needs_six_exposures(self):
        d = dates(20)
        rows = []
        for i, day in enumerate(d):
            trig = "巧克力" if i < 5 else "-"          # 5 天清白：不够格
            rows.append(f"{day}\t{1 if i == 10 else 0}\t{trig}")
        five = self.write("\n".join(rows) + "\n")
        entries = sg.parse_ledger(five, sg.dt.date(2026, 1, 20))
        suspects, _ = sg.prepare(entries)
        self.assertEqual(suspects["巧克力"].verdict, sg.WATCHLIST)
        self.assertIn("偏无辜", suspects["巧克力"].verdict_note)
        rows2 = []
        for i, day in enumerate(dates(20)):
            trig = "巧克力" if i < 6 else "-"          # 6 天清白：平反
            rows2.append(f"{day}\t{1 if i == 10 else 0}\t{trig}")
        entries = sg.parse_ledger(self.write("\n".join(rows2) + "\n"),
                                  sg.dt.date(2026, 1, 20))
        suspects, _ = sg.prepare(entries)
        self.assertEqual(suspects["巧克力"].verdict, sg.ACQUITTED)

    # A10 唯一嫌疑人偏见
    def conviction_ledger(self, extra_suspects):
        # 晚睡 3 天暴露全发作，对照 21 天 2 次发作：p = 10/2024 ≈ 0.00494
        d = dates(24)
        rows = []
        for i, day in enumerate(d):
            trigs = []
            if i < 3:
                trigs.append("晚睡")
            extra = sorted(f"替身{c:02d}" for c in range(extra_suspects))
            for j, name in enumerate(extra):
                if (i + j) % 8 == 0:
                    trigs.append(name)
            attack = "1" if i in (0, 1, 2, 12, 18) else "0"
            rows.append(f"{day}\t{attack}\t{','.join(trigs) if trigs else '-'}")
        return self.write("\n".join(rows) + "\n")

    def test_bonferroni_same_evidence_verdict_depends_on_jury(self):
        # k=1：门槛 0.05，p=0.00494 → 定罪 exit 4
        path = self.conviction_ledger(extra_suspects=0)
        code, out, _ = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("✗ 定罪        晚睡", out)
        # k=13：门槛 0.05/13≈0.00385 < p → 嫌疑重大，不触发门禁
        path = self.conviction_ledger(extra_suspects=12)
        code, out, _ = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("▲ 嫌疑重大", out)
        self.assertIn("GREEN", out)

    def test_tentative_is_labeled_not_convicted(self):
        path = self.conviction_ledger(extra_suspects=12)
        code, out, _ = run_cli("verdicts", path, "--today", TODAY)
        self.assertIn("过单人线", out)
        self.assertNotIn("判定 RED", out)

    # A11 lift 达线但不显著
    def test_lift_without_significance_watches(self):
        # 味精式：2/5 vs 15/83，lift 2.21 但 p≈0.246
        d = dates(88)
        rows = []
        attack_at = {0, 1, 10, 20, 30, 40, 50, 60, 70, 80, 12, 22, 32, 42, 52, 62, 72}
        msg_at = {0, 1, 3, 4, 5}
        for i, day in enumerate(d):
            trig = "味精" if i in msg_at else "-"
            rows.append(f"{day}\t{1 if i in attack_at else 0}\t{trig}")
        path = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("lift 2.21 达定罪线但 p=", out)
        self.assertIn("更像巧合", out)
        self.assertNotIn("✗ 定罪", out)

    # A12 归因发作
    def test_attributable_formula(self):
        entries = sg.parse_ledger(EXAMPLE, sg.dt.date(2026, 8, 24))
        suspects, _ = sg.prepare(entries)
        s = suspects["缺睡"]
        self.assertAlmostEqual(s.attributable, 8 - 14 * (9 / 74), places=6)
        self.assertAlmostEqual(s.attributable, 6.30, places=1)
        wine = suspects["红酒"]
        self.assertLess(wine.attributable, 0)

    # A13 无暴露发作
    def test_unexposed_attacks_reported(self):
        code, out, _ = run_cli("verdicts", EXAMPLE, "--today", TODAY)
        self.assertIn("无暴露发作 4/17（23.5%）", out)

    # A9/A19 示例账本门禁与排序
    def test_example_verdicts_gate_and_order(self):
        code, out, _ = run_cli("verdicts", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("判定 RED —— 1 名定罪：缺睡", out)
        lines = [l for l in out.splitlines() if "  " in l and
                 any(t in l for t in ("✗", "▲", "○", "◌", "✓"))]
        names = [l.split()[2] for l in lines]
        self.assertEqual(names[0], "缺睡")
        self.assertEqual(names[-1], "红酒")
        self.assertIn("陈年奶酪", out)

    def test_example_acquittal_quartet(self):
        code, out, _ = run_cli("acquitted", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 0)
        for name in ("红酒", "巧克力", "咖啡因", "长屏幕"):
            self.assertIn(name, out)


class CommandTests(LedgerTestCase):
    # A14 judge
    def test_judge_unknown_suspect_exit_3(self):
        code, _, err = run_cli("judge", EXAMPLE, "--trigger", "燕麦奶",
                               "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("从未到庭", err)

    def test_judge_acquittal_dossier(self):
        code, out, _ = run_cli("judge", EXAMPLE, "--trigger", "红酒",
                               "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("在场未作案 9 次", out)
        self.assertIn("账目吻合", out)

    def test_judge_conviction_dossier(self):
        code, out, _ = run_cli("judge", EXAMPLE, "--trigger", "缺睡",
                               "--today", TODAY)
        self.assertIn("Bonferroni 门槛 0.05/11=0.0045", out)
        self.assertIn("p=5.94e-04", out)

    # A15 acquitted 空名单
    def test_acquitted_empty_list_honest(self):
        d = dates(20)
        rows = []
        for i, day in enumerate(d):
            rows.append(f"{day}\t{1 if i < 4 else 0}\t{'晚睡' if i < 6 else '-'}")
        path = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("acquitted", path, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("没有可平反", out)

    # A16 case
    def test_case_night_names_convict(self):
        code, out, _ = run_cli("case", EXAMPLE, "--date", "2026-05-07",
                               "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("本案可以结了：缺睡", out)
        self.assertIn("红酒", out)

    def test_case_single_acquitted_presence(self):
        # 2026-05-19：缺睡+巧克力发作；另一晚只有平反者在场
        code, out, _ = run_cli("case", EXAMPLE, "--date", "2026-06-05",
                               "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("巧克力", out)

    def test_case_clean_day_feeds_denominator(self):
        code, out, _ = run_cli("case", EXAMPLE, "--date", "2026-05-11",
                               "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("发作：无", out)
        self.assertIn("未发作分母", out)

    def test_case_unexposed_attack_points_outside(self):
        code, out, _ = run_cli("case", EXAMPLE, "--date", "2026-05-27",
                               "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("名单之外", out)

    def test_case_absent_date_exit_3(self):
        code, _, err = run_cli("case", EXAMPLE, "--date", "2026-05-09",
                               "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("没有记录", err)

    def test_case_bad_date_exit_2(self):
        code, _, _ = run_cli("case", EXAMPLE, "--date", "2026/05/07",
                             "--today", TODAY)
        self.assertEqual(code, 2)

    # A17 simulate
    def test_simulate_convicted_with_honesty_clause(self):
        code, out, _ = run_cli("simulate", EXAMPLE, "--avoid", "缺睡",
                               "--months", "3", "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("至多少发", out)
        self.assertIn("相关性的上限", out)

    def test_simulate_refuses_thin(self):
        code, _, err = run_cli("simulate", EXAMPLE, "--avoid", "陈年奶酪",
                               "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("空气里做手术", err)

    def test_simulate_refuses_watchlist(self):
        code, _, err = run_cli("simulate", EXAMPLE, "--avoid", "压力",
                               "--today", TODAY)
        self.assertEqual(code, 3)

    def test_simulate_refuses_acquitted(self):
        code, _, err = run_cli("simulate", EXAMPLE, "--avoid", "红酒",
                               "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("无辜者", err)

    def test_simulate_unknown_exit_3(self):
        code, _, _ = run_cli("simulate", EXAMPLE, "--avoid", "燕麦奶",
                             "--today", TODAY)
        self.assertEqual(code, 3)

    # A18 combo
    def test_combo_thin_pairs_skipped_never_gates(self):
        code, out, _ = run_cli("combo", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("样本不足不判", out)
        self.assertIn("永不据此定罪", out)

    # A19 零发作/空账本
    def zero_attack(self):
        d = dates(10)
        return self.write(
            "\n".join(f"{day}\t0\t{'缺睡' if i % 2 else '-'}"
                      for i, day in enumerate(dates(10))) + "\n")

    def test_zero_attack_refuses_everywhere(self):
        path = self.zero_attack()
        for argv in (("verdicts", path), ("judge", path, "--trigger", "缺睡"),
                     ("acquitted", path), ("case", path, "--date", "2026-01-01"),
                     ("simulate", path, "--avoid", "缺睡"), ("combo", path)):
            code, _, err = run_cli(*argv, "--today", TODAY)
            self.assertEqual(code, 3, argv)
            self.assertTrue(err.strip(), argv)

    def test_empty_ledger_exit_3(self):
        path = self.write("")
        code, _, _ = run_cli("verdicts", path, "--today", TODAY)
        self.assertEqual(code, 3)
        code, _, _ = run_cli("validate", path, "--today", TODAY)
        self.assertEqual(code, 3)

    def test_single_suspect_combo_exit_3(self):
        path = self.write("2026-01-01\t0\t缺睡\n")
        code, _, _ = run_cli("combo", path, "--today", TODAY)
        self.assertEqual(code, 3)


class ReproTests(LedgerTestCase):
    # A20 可复现
    def test_today_pins_byte_identical_output(self):
        a = run_cli("verdicts", EXAMPLE, "--today", TODAY)
        b = run_cli("verdicts", EXAMPLE, "--today", TODAY)
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1], b[1])

    def test_example_future_dates_rejected_with_early_today(self):
        code, _, err = run_cli("verdicts", EXAMPLE, "--today", "2026-01-01")
        self.assertEqual(code, 2)
        self.assertIn("预写", err)

    # A19 排序确定性
    def test_sort_deterministic(self):
        outs = {run_cli("verdicts", EXAMPLE, "--today", TODAY)[1] for _ in range(3)}
        self.assertEqual(len(outs), 1)

    # A22 validate
    def test_validate_coverage_and_absence(self):
        code, out, _ = run_cli("validate", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("88 个记录日", out)
        self.assertIn("覆盖率 80.0%", out)
        self.assertIn("缺席 22 天", out)
        self.assertIn("咖啡因 25 天", out)

    # A24 零依赖
    def test_stdlib_only_imports(self):
        import scapegoat
        allowed = {"argparse", "datetime", "math", "re", "sys",
                   "unicodedata", "collections", "typing", "__future__"}
        mods = {m.split(".")[0] for m in sys.modules
                if not m.startswith("_")}
        third = {m for m in mods if m not in allowed and not m.startswith(
            ("encodings", "os", "io", "abc", "types", "copyreg", "linecache",
             "functools", "collections.abc", "re._compiler", "re._parser",
             "re._constants", "re._casefix", "genericpath", "posixpath",
             "stat", "codecs", "enum", "sre_compile", "sre_parse",
             "sre_constants", "_collections_abc", "sitecustomize"))}
        # 环境注入的模块不追责，只盯 scapegoat 自己的 import
        self.assertTrue(scapegoat.argparse and scapegoat.math and scapegoat.re)


if __name__ == "__main__":
    unittest.main()
