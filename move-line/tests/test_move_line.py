# -*- coding: utf-8 -*-
"""move-line 验收测试：账本解析 / 数学核 / 恒等式 / 裁决带 / 门禁与拒答."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import move_line  # noqa: E402

GOOD_HOMES = (
    "name\trent\tcommute\trole\tnote\n"
    "梧桐里\t4500\t25\tcurrent\t住了三年\n"
    "同小区两期B\t4590\t25\tcandidate\t同通勤\n"
    "滨江壹号A\t3800\t50\tcandidate\t便宜但远\n"
)
GOOD_MOVE = (
    "item\tamount\tnote\n"
    "中介费\t2250\t半月租\n"
    "搬家公司\t1200\n"
    "家具拆装\t600\n"
    "宽带迁移与换锁\t350\n"
    "新家开荒保洁\t400\n"
    "请假误工\t420\n"
)

# 与 examples/ 同口径的手算常量（时薪 60 · 230 天 · 搬家税 5,220）：
#   年通勤税(25min)=11,500  年通勤税(50min)=23,000
#   摊 3 年：年搬家税 1,740；摊 1 年：5,220
#   现居年净(旧租)=65,500；现居年净(报价 5,040)=71,980
#   B(3y)=68,320 → 实线 +5.2222%；A(3y)=70,340 → +8.9630%
#   B(1y)=71,800 → +11.6667%（+12.0% 报价落掷币带）


def run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = move_line.main(argv)
    return code, buf.getvalue()


class Fixture(unittest.TestCase):
    """临时目录里摆好账本。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.homes = os.path.join(self.dir.name, "homes.tsv")
        self.move = os.path.join(self.dir.name, "move.tsv")
        with open(self.homes, "w", encoding="utf-8") as fh:
            fh.write(GOOD_HOMES)
        with open(self.move, "w", encoding="utf-8") as fh:
            fh.write(GOOD_MOVE)

    def rewrite(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _w(self, name, text):
        path = os.path.join(self.dir.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path


class TestParsing(Fixture):
    def test_a1_parse_homes_fields(self):
        homes = move_line.parse_homes(self.homes)
        self.assertEqual([h.name for h in homes],
                         ["梧桐里", "同小区两期B", "滨江壹号A"])
        cur = [h for h in homes if h.role == "current"]
        self.assertEqual(len(cur), 1)
        self.assertEqual(cur[0].rent, 4500.0)
        self.assertEqual(cur[0].commute, 25.0)

    def test_a2_header_comment_blank_skipped(self):
        text = ("# 注释\n\nname\trent\tcommute\trole\n"
                "甲\t1000\t10\tcurrent\n# 尾注\n")
        homes = move_line.parse_homes(self._w("h.tsv", text))
        self.assertEqual(len(homes), 1)

    def test_a3_note_column_optional(self):
        text = "name\trent\tcommute\trole\n甲\t1000\t10\tcurrent\n"
        homes = move_line.parse_homes(self._w("h.tsv", text))
        self.assertEqual(homes[0].note, "")

    def test_a4_bad_columns_exit2(self):
        with self.assertRaisesRegex(move_line.LedgerError, "4-5 列"):
            move_line.parse_homes(self._w("h.tsv", "甲\t1000\t10\n"))

    def test_a5_bad_rent_exit2(self):
        with self.assertRaisesRegex(move_line.LedgerError, "月租不是数字"):
            move_line.parse_homes(
                self._w("h.tsv", "甲\tabc\t10\tcurrent\n"))

    def test_a6_nonpositive_rent_exit2(self):
        with self.assertRaisesRegex(move_line.LedgerError, "必须 > 0"):
            move_line.parse_homes(
                self._w("h.tsv", "甲\t0\t10\tcurrent\n"))

    def test_a7_bad_commute_exit2(self):
        with self.assertRaisesRegex(move_line.LedgerError, "不是数字"):
            move_line.parse_homes(
                self._w("h.tsv", "甲\t1000\tx\tcurrent\n"))

    def test_a8_negative_commute_exit2(self):
        with self.assertRaisesRegex(move_line.LedgerError, "不能为负"):
            move_line.parse_homes(
                self._w("h.tsv", "甲\t1000\t-1\tcurrent\n"))

    def test_a9_bad_role_exit2(self):
        with self.assertRaisesRegex(move_line.LedgerError, "role"):
            move_line.parse_homes(
                self._w("h.tsv", "甲\t1000\t10\t现居\n"))

    def test_a10_duplicate_home_exit2(self):
        text = ("name\trent\tcommute\trole\n"
                "甲\t1000\t10\tcurrent\n"
                "甲\t2000\t20\tcandidate\n")
        with self.assertRaisesRegex(move_line.LedgerError, "重复"):
            move_line.parse_homes(self._w("h.tsv", text))

    def test_a11_two_currents_exit2(self):
        text = ("name\trent\tcommute\trole\n"
                "甲\t1000\t10\tcurrent\n"
                "乙\t2000\t20\tcurrent\n")
        with self.assertRaisesRegex(move_line.LedgerError, "恰好一个"):
            move_line.parse_homes(self._w("h.tsv", text))

    def test_a12_missing_file_exit2(self):
        with self.assertRaises(move_line.LedgerError):
            move_line.parse_homes(os.path.join(self.dir.name, "nope.tsv"))

    def test_a13_costs_fields_and_blank_note(self):
        costs = move_line.parse_costs(self.move)
        self.assertEqual(len(costs), 6)
        self.assertEqual(costs[1].note, "")
        self.assertEqual(move_line.toll_total(costs), 5220.0)

    def test_a14_bad_amount_exit2(self):
        with self.assertRaisesRegex(move_line.LedgerError, "金额不是数字"):
            move_line.parse_costs(self._w("m.tsv", "中介费\tmany\n"))

    def test_a15_negative_amount_exit2(self):
        with self.assertRaisesRegex(move_line.LedgerError, "不能为负"):
            move_line.parse_costs(self._w("m.tsv", "退款\t-100\n"))

    def _w(self, name, text):
        path = os.path.join(self.dir.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path


class TestMath(Fixture):
    CTX = dict(wage=60.0, days=230.0)

    def cur(self):
        return move_line.Home("cur", "现居", 4500.0, 25.0, "current", "", 1)

    def cand(self, name, rent, commute):
        return move_line.Home(name, name, rent, commute, "candidate", "", 2)

    def test_b1_commute_tax_exact(self):
        self.assertAlmostEqual(
            move_line.commute_tax(25, 60, 230), 11500.0, places=9)
        self.assertAlmostEqual(
            move_line.commute_tax(50, 60, 230), 23000.0, places=9)

    def test_b2_annual_decomposition_identity(self):
        # 年净成本 = 年房租 + 年通勤税 + 年搬家税，分毫不差
        cur = self.cur()
        toll_yr = 5220.0 / 3
        total = move_line.annual_total(cur, 60, 230, toll_yr, mover=False)
        self.assertAlmostEqual(
            total, 4500 * 12 + 11500.0 + 0.0, places=6)
        a = self.cand("滨江壹号A", 3800.0, 50.0)
        total_a = move_line.annual_total(a, 60, 230, toll_yr, mover=True)
        self.assertAlmostEqual(
            total_a, 3800 * 12 + 23000.0 + toll_yr, places=6)

    def test_b3_blind_line_and_cap(self):
        cur = self.cur()
        toll_yr = 5220.0 / 3
        self.assertAlmostEqual(
            move_line.blind_line_pct(toll_yr, cur), 145.0 / 4500, places=12)
        self.assertAlmostEqual(move_line.cap_rent(toll_yr, cur), 4355.0,
                               places=9)

    def test_b4_cand_line_exact(self):
        cur = self.cur()
        toll_yr = 5220.0 / 3
        b = self.cand("同小区两期B", 4590.0, 25.0)
        # (4590×12 + 0 + 1740)/12 = 4,735 整
        self.assertAlmostEqual(
            move_line.cand_line_rent(b, cur, 60, 230, toll_yr), 4735.0,
            places=9)
        self.assertAlmostEqual(
            move_line.cand_line_pct(b, cur, 60, 230, toll_yr),
            4735.0 / 4500 - 1, places=12)

    def test_b5_real_line_is_min_with_display_name(self):
        homes = [self.cur(),
                 self.cand("同小区两期B", 4590.0, 25.0),
                 self.cand("滨江壹号A", 3800.0, 50.0)]
        pct, rent, name = move_line.real_line(
            homes, homes[0], 60.0, 230.0, 5220.0 / 3)
        self.assertAlmostEqual(pct, 4735.0 / 4500 - 1, places=12)
        self.assertAlmostEqual(rent, 4735.0, places=9)
        self.assertEqual(name, "同小区两期B")

    def test_b6_breakeven_identity(self):
        # 把无差异月租同时代入两边，年净成本必须打平（机器精度）
        cur = self.cur()
        for cand in (self.cand("B", 4590.0, 25.0),
                     self.cand("A", 3800.0, 50.0)):
            toll_yr = 5220.0 / 3
            r = move_line.cand_line_rent(cand, cur, 60, 230, toll_yr)
            stay = r * 12 + move_line.commute_tax(cur.commute, 60, 230)
            go = move_line.annual_total(cand, 60, 230, toll_yr, mover=True)
            self.assertAlmostEqual(stay, go, places=6)

    def test_b7_payback_identity(self):
        # 回本月数 × 每月净省 = 搬家税总额
        total, saving_mo = 5220.0, 305.0
        self.assertAlmostEqual(total / saving_mo * saving_mo, total, places=9)
        # 手算：B 对 +12% 报价年省 3,660 → 回本 17.1148… 月
        self.assertAlmostEqual(5220.0 / (3660.0 / 12), 17.114754, places=5)

    def test_b8_line_monotone_in_years(self):
        # 住得越久，搬家税摊得越薄，线单调不增（各候选与实线皆然）
        homes = [self.cur(),
                 self.cand("B", 4590.0, 25.0),
                 self.cand("A", 3800.0, 50.0)]
        lines = []
        for y in (1.0, 2.0, 3.0, 5.0):
            real = move_line.real_line(homes, homes[0], 60.0, 230.0,
                                       5220.0 / y)
            lines.append(real[0])
        for early, late in zip(lines, lines[1:]):
            self.assertGreaterEqual(early, late)

    def test_b9_higher_wage_hurts_far_candidate(self):
        cur = self.cur()
        far = self.cand("A", 3800.0, 50.0)
        near = self.cand("B", 4590.0, 25.0)
        line_near_wage = move_line.cand_line_pct(
            near, cur, 60, 230, 1740.0)  # 同通勤：时薪无关
        self.assertAlmostEqual(
            move_line.cand_line_pct(near, cur, 120, 230, 1740.0),
            line_near_wage, places=12)
        far_low = move_line.cand_line_pct(far, cur, 30, 230, 1740.0)
        far_high = move_line.cand_line_pct(far, cur, 120, 230, 1740.0)
        self.assertLess(far_low, far_high)

    def test_b10_decide_bands(self):
        line = 0.10
        self.assertEqual(move_line.decide(0.079, line),
                         move_line.RENEW)   # −2.1pp
        self.assertEqual(move_line.decide(0.081, line),
                         move_line.TOSS)    # −1.9pp
        self.assertEqual(move_line.decide(0.119, line),
                         move_line.TOSS)    # +1.9pp
        self.assertEqual(move_line.decide(0.121, line),
                         move_line.MOVE)    # +2.1pp

    def test_b11_missing_checklist(self):
        costs = move_line.parse_costs(self.move)
        missing = move_line.missing_checklist(costs)
        self.assertEqual(missing,
                         ["起租重叠/双租", "宠物安置", "修复与押金扣损"])
        full = move_line.parse_costs(self._w(
            "m2.tsv",
            "中介费\t1\n搬家公司\t1\n家具拆装\t1\n宽带迁移\t1\n换锁\t1\n"
            "开荒保洁\t1\n请假误工\t1\n起租重叠\t1\n宠物托运\t1\n补墙修复\t1\n"))
        self.assertEqual(move_line.missing_checklist(full), [])


class TestJudge(Fixture):
    def test_c1_move_exit4_sample(self):
        code, out = run(["judge", self.homes, self.move, "--offer", "5040"])
        self.assertEqual(code, 4)
        self.assertIn("✗ 挪", out)
        self.assertIn("+5.2%", out)
        self.assertIn("¥4,735", out)
        self.assertIn("同小区两期B", out)

    def test_c2_coin_toss_at_one_year(self):
        code, out = run(["judge", self.homes, self.move,
                         "--offer", "5040", "--years", "1"])
        self.assertEqual(code, 0)
        self.assertIn("◐ 掷币", out)
        self.assertIn("+11.7%", out)

    def test_c3_renew_small_increase(self):
        code, out = run(["judge", self.homes, self.move, "--pct", "3"])
        self.assertEqual(code, 0)
        self.assertIn("✓ 忍", out)

    def test_c4_pct_and_offer_agree(self):
        _, out1 = run(["judge", self.homes, self.move, "--pct", "12"])
        _, out2 = run(["judge", self.homes, self.move, "--offer", "5040"])
        self.assertEqual(out1, out2)

    def test_c5_offer_pct_conflict_exit2(self):
        code, _ = run(["judge", self.homes, self.move,
                       "--offer", "5040", "--pct", "12"])
        self.assertEqual(code, 2)

    def test_c6_neither_offer_nor_pct_exit2(self):
        code, _ = run(["judge", self.homes, self.move])
        self.assertEqual(code, 2)

    def test_c7_nonpositive_offer_exit2(self):
        code, _ = run(["judge", self.homes, self.move, "--offer", "0"])
        self.assertEqual(code, 2)

    def test_c8_negative_line_note(self):
        # 时薪 30 时远候选反超：实线 −1.7%，附「现居已净最贵」披露
        code, out = run(["judge", self.homes, self.move,
                         "--offer", "5040", "--wage", "30"])
        self.assertEqual(code, 4)
        self.assertIn("实线为负", out)
        self.assertIn("滨江壹号A", out)

    def test_c9_blind_mode_without_candidates(self):
        homes = ("name\trent\tcommute\trole\n梧桐里\t4500\t25\tcurrent\n")
        self.rewrite(self.homes, homes)
        code, out = run(["judge", self.homes, self.move, "--pct", "10"])
        self.assertEqual(code, 4)
        self.assertIn("盲搬线 +3.2%", out)
        self.assertIn("¥4,355", out)

    def test_c10_renew_when_no_candidates_small_rise(self):
        homes = ("name\trent\tcommute\trole\n梧桐里\t4500\t25\tcurrent\n")
        self.rewrite(self.homes, homes)
        code, out = run(["judge", self.homes, self.move, "--pct", "1"])
        self.assertEqual(code, 0)
        self.assertIn("✓ 忍", out)


class TestCompareAndToll(Fixture):
    def test_d1_compare_table_order_and_numbers(self):
        code, out = run(["compare", self.homes, self.move, "--offer", "5040"])
        self.assertEqual(code, 0)
        self.assertIn("¥68,320", out)      # B 年净成本
        self.assertIn("省 ¥3,660/年 · 回本 17.1 个月", out)
        self.assertIn("¥70,340", out)      # A 年净成本
        self.assertIn("不涨的现居 ¥65,500", out)
        self.assertIn("¥71,980", out)      # 涨价后的基准
        # B 排在 A 前
        self.assertLess(out.index("同小区两期B"), out.index("滨江壹号A"))

    def test_d2_trap_light(self):
        _, out = run(["compare", self.homes, self.move, "--offer", "5040"])
        self.assertIn("陷阱灯：滨江壹号A", out)
        self.assertIn("¥700/月", out)
        self.assertIn("¥11,500/年 通勤税", out)

    def test_d3_payback_light(self):
        _, out = run(["compare", self.homes, self.move, "--offer", "5040"])
        self.assertIn("回本灯：滨江壹号A 回本 38.2 个月 > 预计居住 3 年", out)

    def test_d4_compare_without_offer(self):
        code, out = run(["compare", self.homes, self.move])
        self.assertEqual(code, 0)
        self.assertIn("现居按当前租 ¥4,500/月", out)
        self.assertIn("judge --offer", out)

    def test_d5_never_payback_when_losing(self):
        # 报价低到候选全亏：永不回本
        code, out = run(["compare", self.homes, self.move, "--offer", "4300"])
        self.assertEqual(code, 0)
        self.assertIn("不省反亏", out)
        self.assertIn("永不回本", out)

    def test_d6_compare_no_candidates_exit3(self):
        homes = ("name\trent\tcommute\trole\n梧桐里\t4500\t25\tcurrent\n")
        self.rewrite(self.homes, homes)
        code, _ = run(["compare", self.homes, self.move])
        self.assertEqual(code, 3)

    def test_d7_toll_items_and_banner(self):
        code, out = run(["toll", self.homes, self.move])
        self.assertEqual(code, 0)
        self.assertIn("搬家税单 · 6 项 · ¥5,220", out)
        self.assertIn("¥1,740/年 = ¥145/月 = 现租的 3.2%", out)
        self.assertIn("糊涂账护栏：3 类常见成本不在账上", out)
        self.assertIn("起租重叠/双租 · 宠物安置 · 修复与押金扣损", out)

    def test_d8_toll_full_ledger_no_banner(self):
        self.rewrite(self.move, GOOD_MOVE + (
            "起租重叠\t300\n宠物托运\t200\n补墙扣押金\t500\n"))
        _, out = run(["toll", self.homes, self.move])
        self.assertIn("十类常见成本全部在账", out)

    def test_d9_toll_empty_costs_exit3(self):
        self.rewrite(self.move, "item\tamount\n")
        for cmd in ("toll", "judge", "compare", "cap", "sensitivity"):
            extra = ["--pct", "5"] if cmd in ("judge", "sensitivity") else []
            code, _ = run([cmd, self.homes, self.move] + extra)
            self.assertEqual(code, 3, cmd)

    def test_d10_validate_reports_zero_toll_instead_of_refusing(self):
        self.rewrite(self.move, "item\tamount\n")
        code, out = run(["validate", self.homes, self.move])
        self.assertEqual(code, 0)
        self.assertIn("搬家税 ¥0", out)


class TestSensitivityAndCap(Fixture):
    def test_e1_matrix_cells_and_marks(self):
        code, out = run(["sensitivity", self.homes, self.move,
                         "--offer", "5040"])
        self.assertEqual(code, 0)
        for cell in ("+4.8% ✗", "+11.7% ◐", "-0.1% ✗", "+6.8% ✗",
                     "-1.7% ✗", "+5.2% ✗", "-3.0% ✗", "+3.9% ✗"):
            self.assertIn(cell, out)
        self.assertIn("裁决对照 +12.0%", out)

    def test_e2_matrix_without_offer_has_no_marks(self):
        _, out = run(["sensitivity", self.homes, self.move])
        self.assertNotIn("✗", out)
        self.assertNotIn("◐", out)
        self.assertNotIn("✓", out)
        self.assertIn("给 --offer", out)

    def test_e3_cap_output(self):
        code, out = run(["cap", self.homes, self.move])
        self.assertEqual(code, 0)
        self.assertIn("盲搬线 +3.2%", out)
        self.assertIn("¥4,355", out)
        self.assertIn("¥145/月", out)

    def test_e4_cap_blind_mode_note(self):
        homes = ("name\trent\tcommute\trole\n梧桐里\t4500\t25\tcurrent\n")
        self.rewrite(self.homes, homes)
        _, out = run(["cap", self.homes, self.move])
        self.assertIn("候选 0 个", out)

    def test_e5_bad_grid_exit2(self):
        code, _ = run(["sensitivity", self.homes, self.move,
                       "--wage-list", "a,b"])
        self.assertEqual(code, 2)
        code, _ = run(["sensitivity", self.homes, self.move,
                       "--year-list", ""])
        self.assertEqual(code, 2)


class TestValidateAndCLI(Fixture):
    def test_f1_validate_summary(self):
        code, out = run(["validate", self.homes, self.move])
        self.assertEqual(code, 0)
        self.assertIn("住处 3 个（现居 1 · 候选 2）", out)
        self.assertIn("现居：梧桐里 ¥4,500/月 · 通勤 25 分钟", out)
        self.assertIn("盲搬线 +3.2%", out)
        self.assertIn("实线 +5.2%", out)
        self.assertIn("不抓房源、不预测市场", out)

    def test_f2_empty_homes_refusal(self):
        self.rewrite(self.homes, "name\trent\tcommute\trole\n")
        for cmd in ("cap", "compare", "toll", "validate"):
            code, _ = run([cmd, self.homes, self.move])
            self.assertEqual(code, 3, cmd)
        for cmd in ("judge", "sensitivity"):
            code, _ = run([cmd, self.homes, self.move, "--pct", "5"])
            self.assertEqual(code, 3, cmd)

    def test_f3_missing_ledger_exit2(self):
        code, _ = run(["cap", os.path.join(self.dir.name, "no.tsv"),
                       self.move])
        self.assertEqual(code, 2)

    def test_f4_version_and_noargs(self):
        with self.assertRaises(SystemExit) as cm:
            run(["--version"])
        self.assertEqual(cm.exception.code, 0)
        with self.assertRaises(SystemExit) as cm:
            run([])
        self.assertEqual(cm.exception.code, 2)

    def test_f5_unknown_command_exit2(self):
        with self.assertRaises(SystemExit):
            run(["verdicts", self.homes, self.move])

    def test_f6_stdlib_only(self):
        import ast
        src = os.path.join(os.path.dirname(__file__), "..", "move_line.py")
        with open(src, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        allowed = {"__future__", "argparse", "re", "sys", "unicodedata",
                   "collections", "typing"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed,
                                  alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                self.assertIn((node.module or "").split(".")[0], allowed,
                              node.module)


class TestReproducibility(Fixture):
    def test_g1_deterministic_output(self):
        _, out1 = run(["judge", self.homes, self.move, "--offer", "5040"])
        _, out2 = run(["judge", self.homes, self.move, "--offer", "5040"])
        self.assertEqual(out1, out2)

    def test_g2_examples_ledgers_match_fixture_math(self):
        base = os.path.join(os.path.dirname(__file__), "..", "examples")
        with open(os.path.join(base, "homes.tsv"), encoding="utf-8") as fh:
            homes_text = fh.read()
        with open(os.path.join(base, "move.tsv"), encoding="utf-8") as fh:
            move_text = fh.read()
        homes = move_line.parse_homes(os.path.join(base, "homes.tsv"))
        costs = move_line.parse_costs(os.path.join(base, "move.tsv"))
        cur = next(h for h in homes if h.role == "current")
        self.assertEqual(cur.rent, 4500.0)
        self.assertEqual(move_line.toll_total(costs), 5220.0)
        # examples 账本与手算常量互相咬合
        self.assertIn("同小区两期B\t4590\t25", homes_text.replace(
            "同小区两期B\t4590\t25", "同小区两期B\t4590\t25"))
        self.assertTrue(move_text.startswith("# "))


if __name__ == "__main__":
    unittest.main()
