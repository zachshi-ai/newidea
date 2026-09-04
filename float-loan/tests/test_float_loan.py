# -*- coding: utf-8 -*-
"""float-loan 验收测试：账本解析 / 三态与恒等式 / 分位数 / 门禁与拒答."""

import ast
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import float_loan  # noqa: E402

GOOD_LEDGER = (
    "date\titem\tamount\trepaid\tcategory\tnote\n"
    "2026-03-02\t差旅-杭州投标\t2860\t2026-03-20\t差旅\n"
    "2026-03-18\t团建-部门聚餐\t1120\t2026-04-10\t团建\n"
    "2026-04-03\t差旅-深圳客户\t3415\t2026-04-24\t差旅\n"
    "2026-04-03\t出租车-超标\t287\t0\t差旅\t财务驳回\n"
    "2026-04-22\t采购-测试耗材\t960\t2026-05-18\t采购\n"
    "2026-05-06\t差旅-成都巡检\t4230\t2026-05-27\t差旅\n"
    "2026-05-19\t差旅-北京展会\t5118\t2026-06-24\t差旅\n"
    "2026-06-05\t采购-办公椅\t1350\t2026-07-01\t采购\n"
    "2026-06-20\t差旅-广州交付\t3870\t2026-07-15\t差旅\n"
    "2026-07-08\t采购-项目服务器\t3280\t\t采购\t发票重开后无音讯\n"
    "2026-08-13\t差旅-西安验收\t2750\t\t差旅\n"
    "2026-08-26\t团建-季度下午茶\t386\t\t团建\n"
)

TODAY = "2026-09-04"
# 手算常量（--today 2026-09-04）：
#   回款 8 笔 22,923 + 在途 3 笔 6,416 + 自担 1 笔 287 = 29,626
#   周期排序 [18,21,21,23,25,26,26,36] → P50 24.0 · P90 29.0（催办线）
#   在途账龄：服务器 58（超线 29）、西安 22、下午茶 9
#   浮存金（apr 3%）：Σ金额×天数×0.03/365 = 833,057 × 0.03/365 = 68.470438…
#   回款速率 22,923/135 = 169.8/天 → 排空 6,416/169.8 = 37.8 → 38 天


def run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = float_loan.main(argv)
    return code, buf.getvalue()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ledger = os.path.join(self.dir.name, "floats.tsv")
        self.write(GOOD_LEDGER)

    def write(self, text, name="floats.tsv"):
        path = os.path.join(self.dir.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _d(self, s):
        import datetime as dt
        return dt.date.fromisoformat(s)


class TestParsing(Fixture):
    def test_a1_parse_fields_and_states(self):
        rows = float_loan.parse_ledger(self.ledger, self._d(TODAY))
        self.assertEqual(len(rows), 12)
        states = [r.state for r in rows]
        self.assertEqual(states.count(float_loan.REPAID), 8)
        self.assertEqual(states.count(float_loan.OUTSTANDING), 3)
        self.assertEqual(states.count(float_loan.EATEN), 1)

    def test_a2_header_comment_blank_skipped(self):
        text = "# 注释\n\ndate\titem\tamount\trepaid\n" \
               "2026-01-01\t甲\t100\t\t\n# 尾注\n"
        rows = float_loan.parse_ledger(self.write(text), self._d(TODAY))
        self.assertEqual(len(rows), 1)

    def test_a3_without_category_defaults_other(self):
        text = "date\titem\tamount\trepaid\n2026-01-01\t甲\t100\t\t\n"
        rows = float_loan.parse_ledger(self.write(text), self._d(TODAY))
        self.assertEqual(rows[0].category, "other")

    def test_a4_dash_category_becomes_other(self):
        text = "date\titem\tamount\trepaid\tcategory\n" \
               "2026-01-01\t甲\t100\t\t-\n"
        rows = float_loan.parse_ledger(self.write(text), self._d(TODAY))
        self.assertEqual(rows[0].category, "other")

    def test_a5_bad_columns_exit2(self):
        with self.assertRaisesRegex(float_loan.LedgerError, "4-6 列"):
            float_loan.parse_ledger(
                self.write("2026-01-01\t甲\t100\n"), self._d(TODAY))

    def test_a6_empty_item_exit2(self):
        with self.assertRaisesRegex(float_loan.LedgerError, "事项为空"):
            float_loan.parse_ledger(
                self.write("2026-01-01\t\t100\t\t\n"), self._d(TODAY))

    def test_a7_bad_date_exit2(self):
        with self.assertRaisesRegex(float_loan.LedgerError, "YYYY-MM-DD"):
            float_loan.parse_ledger(
                self.write("2026/01/01\t甲\t100\t\t\n"), self._d(TODAY))

    def test_a8_future_advance_exit2(self):
        with self.assertRaisesRegex(float_loan.LedgerError, "垫付不能预记"):
            float_loan.parse_ledger(
                self.write("2026-09-05\t甲\t100\t\t\n"), self._d(TODAY))

    def test_a9_bad_amount_exit2(self):
        with self.assertRaisesRegex(float_loan.LedgerError, "不是数字"):
            float_loan.parse_ledger(
                self.write("2026-01-01\t甲\tmany\t\t\n"), self._d(TODAY))

    def test_a10_nonpositive_amount_exit2(self):
        with self.assertRaisesRegex(float_loan.LedgerError, "> 0"):
            float_loan.parse_ledger(
                self.write("2026-01-01\t甲\t0\t\t\n"), self._d(TODAY))

    def test_a11_bad_repaid_exit2(self):
        with self.assertRaisesRegex(float_loan.LedgerError, "回款列"):
            float_loan.parse_ledger(
                self.write("2026-01-01\t甲\t100\tsoon\t\n"), self._d(TODAY))

    def test_a12_repaid_before_advance_exit2(self):
        with self.assertRaisesRegex(float_loan.LedgerError, "时间不允许倒流"):
            float_loan.parse_ledger(
                self.write("2026-01-05\t甲\t100\t2026-01-01\t\n"),
                self._d(TODAY))

    def test_a13_repaid_in_future_exit2(self):
        with self.assertRaisesRegex(float_loan.LedgerError, "到账不能预记"):
            float_loan.parse_ledger(
                self.write("2026-01-01\t甲\t100\t2026-09-05\t\n"),
                self._d(TODAY))

    def test_a14_same_day_multiple_advances_legal(self):
        text = ("date\titem\tamount\trepaid\n"
                "2026-01-01\t甲\t100\t\n"
                "2026-01-01\t乙\t200\t2026-01-10\n")
        rows = float_loan.parse_ledger(self.write(text), self._d(TODAY))
        self.assertEqual(len(rows), 2)

    def test_a15_missing_file_exit2(self):
        with self.assertRaises(float_loan.LedgerError):
            float_loan.parse_ledger(
                os.path.join(self.dir.name, "nope.tsv"), self._d(TODAY))

    def _d(self, s):
        import datetime as dt
        return dt.date.fromisoformat(s)


class TestMath(Fixture):
    def rows(self):
        return float_loan.parse_ledger(self.ledger, self._d(TODAY))

    def test_b1_percentile_hand_table(self):
        p = float_loan.percentile
        self.assertAlmostEqual(p([10, 20, 30, 40], 0.5), 25.0, places=9)
        self.assertAlmostEqual(p([10, 20, 30, 40], 0.9), 37.0, places=9)
        self.assertAlmostEqual(p([5.0], 0.9), 5.0, places=9)
        self.assertEqual(p([], 0.5), 0.0)

    def test_b2_cycles_exact(self):
        cs = sorted(float_loan.cycles(
            [r for r in self.rows() if r.state == float_loan.REPAID]))
        self.assertEqual(cs, [18, 21, 21, 23, 25, 26, 26, 36])

    def test_b3_nudge_line_is_p90(self):
        _, repaid, _ = float_loan.split(self.rows())
        self.assertAlmostEqual(float_loan.nudge_line(repaid), 29.0, places=9)

    def test_b4_nudge_line_thin(self):
        rows = float_loan.parse_ledger(self.write(
            "date\titem\tamount\trepaid\n"
            "2026-01-01\t甲\t100\t2026-01-10\n"
            "2026-02-01\t乙\t100\t2026-02-20\n"), self._d(TODAY))
        _, repaid, _ = float_loan.split(rows)
        self.assertIsNone(float_loan.nudge_line(repaid))

    def test_b5_three_state_identity(self):
        rows = self.rows()
        outstanding, repaid, eaten = float_loan.split(rows)
        total = sum(r.amount for r in rows)
        self.assertAlmostEqual(
            sum(r.amount for r in outstanding)
            + sum(r.amount for r in repaid)
            + sum(r.amount for r in eaten), total, places=6)
        self.assertAlmostEqual(total, 29626.0, places=6)
        self.assertAlmostEqual(
            sum(r.amount for r in outstanding), 6416.0, places=6)

    def test_b6_float_cost_per_row_exact(self):
        rows = self.rows()
        today = self._d(TODAY)
        first = rows[0]  # 2860 × 18 天
        self.assertAlmostEqual(
            float_loan.float_cost(first, today, 3.0),
            2860 * 18 * 0.03 / 365, places=9)
        eaten = [r for r in rows if r.state == float_loan.EATEN][0]
        self.assertEqual(float_loan.float_cost(eaten, today, 3.0), 0.0)
        server = [r for r in rows if r.item == "采购-项目服务器"][0]
        self.assertAlmostEqual(
            float_loan.float_cost(server, today, 3.0),
            3280 * 58 * 0.03 / 365, places=9)

    def test_b7_float_total_identity(self):
        rows = self.rows()
        today = self._d(TODAY)
        total = sum(float_loan.float_cost(r, today, 3.0) for r in rows)
        self.assertAlmostEqual(total, 833057 * 0.03 / 365, places=9)
        self.assertAlmostEqual(total, 68.470438, places=4)

    def test_b8_throughput_and_drain(self):
        _, repaid, _ = float_loan.split(self.rows())
        rate = float_loan.throughput(repaid)
        self.assertAlmostEqual(rate, 22923.0 / 135.0, places=6)
        outstanding = 6416.0
        self.assertAlmostEqual(outstanding / rate, 6416.0 * 135.0 / 22923.0,
                               places=9)
        self.assertAlmostEqual(outstanding / rate, 37.78, places=1)

    def test_b9_throughput_thin(self):
        rows = float_loan.parse_ledger(self.write(
            "date\titem\tamount\trepaid\n"
            "2026-01-01\t甲\t100\t2026-01-10\n"), self._d(TODAY))
        _, repaid, _ = float_loan.split(rows)
        self.assertIsNone(float_loan.throughput(repaid))

    def test_b10_apr_scales_linearly(self):
        rows = self.rows()
        today = self._d(TODAY)
        low = sum(float_loan.float_cost(r, today, 3.0) for r in rows)
        high = sum(float_loan.float_cost(r, today, 6.0) for r in rows)
        self.assertAlmostEqual(high, low * 2, places=9)


class TestCommands(Fixture):
    def test_c1_pipeline_red_exit4(self):
        code, out = run(["pipeline", self.ledger, "--today", TODAY])
        self.assertEqual(code, 4)
        self.assertIn("在途管道 · 3 笔 ¥6,416", out)
        self.assertIn("催办线 29.0 天", out)
        self.assertIn("✗ 超催办线 29 天", out)
        self.assertIn("判定 RED", out)

    def test_c2_pipeline_green_when_no_outstanding(self):
        text = ("date\titem\tamount\trepaid\n"
                "2026-01-01\t甲\t100\t2026-01-10\n"
                "2026-02-01\t乙\t200\t2026-02-20\n"
                "2026-03-01\t丙\t300\t2026-03-25\n")
        self.write(text)
        code, out = run(["pipeline", self.ledger, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("管道空", out)
        self.assertIn("无息贷款余额 ¥0", out)

    def test_c3_pipeline_thin_sorts_without_line(self):
        text = ("date\titem\tamount\trepaid\n"
                "2026-06-01\t甲\t100\t2026-06-10\n"
                "2026-08-01\t乙\t200\t\t\n")
        self.write(text)
        code, out = run(["pipeline", self.ledger, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("催办线：未标定", out)
        self.assertIn("判定 GREEN", out)

    def test_c4_stats_identity_and_distribution(self):
        code, out = run(["stats", self.ledger, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("回款 ¥22,923（8 笔） + 在途 ¥6,416（3 笔）"
                      " + 自担 ¥287（1 笔） = ¥29,626", out)
        self.assertIn("残差 0.000000", out)
        self.assertIn("P50 24.0 天 · P90 29.0 天", out)
        self.assertIn("排空在途约 38 天", out)
        self.assertIn("被财务的「不符合规定」吃掉", out)

    def test_c5_stats_category_identity(self):
        _, out = run(["stats", self.ledger, "--today", TODAY])
        self.assertIn("差旅             ¥22,530  76.0%", out)
        self.assertIn("加总 ¥29,626 = 总垫付 ¥29,626", out)

    def test_c6_float_rows_and_eaten_exclusion(self):
        code, out = run(["float", self.ledger, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("¥68.47 利息", out)
        self.assertIn("¥15.64", out)          # 服务器 3280×58 天
        self.assertIn("—（自担）", out)        # 出租车不入浮存
        self.assertIn("它不是占款，是损失", out)
        self.assertIn("遗忘才是灾难", out)

    def test_c7_float_apr_override(self):
        _, out = run(["float", self.ledger, "--apr", "18",
                      "--today", TODAY])
        self.assertIn("年化 18%", out)
        # 68.470438 × 6 = 410.82
        self.assertIn("¥410.82 利息", out)

    def test_c8_nudge_exit4_with_detail(self):
        code, out = run(["nudge", self.ledger, "--today", TODAY])
        self.assertEqual(code, 4)
        self.assertIn("催办单 · 催办线 29.0 天", out)
        self.assertIn("已 58 天，超线 29 天（垫付 2026-07-08）", out)
        self.assertIn("合计 ¥3,280 在被遗忘", out)

    def test_c9_nudge_green_when_all_inline(self):
        text = ("date\titem\tamount\trepaid\n"
                "2026-01-01\t甲\t100\t2026-01-10\n"
                "2026-02-01\t乙\t100\t2026-02-20\n"
                "2026-03-01\t丙\t100\t2026-03-25\n"
                "2026-08-20\t丁\t100\t\t\n")
        self.write(text)
        code, out = run(["nudge", self.ledger, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("无单可开", out)

    def test_c10_nudge_thin_exit3(self):
        text = ("date\titem\tamount\trepaid\n"
                "2026-01-01\t甲\t100\t2026-01-10\n"
                "2026-08-01\t乙\t200\t\t\n")
        self.write(text)
        code, _ = run(["nudge", self.ledger, "--today", TODAY])
        self.assertEqual(code, 3)

    def test_c11_validate_summary(self):
        code, out = run(["validate", self.ledger, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("12 笔垫付", out)
        self.assertIn("在途 3 笔 ¥6,416", out)
        self.assertIn("催办线 29.0 天", out)
        self.assertIn("品类 3 个：团建 · 差旅 · 采购", out)
        self.assertIn("不替你催", out)


class TestCLIAndRepro(Fixture):
    def test_d1_empty_ledger_exit3(self):
        self.write("date\titem\tamount\trepaid\n")
        for cmd in ("pipeline", "stats", "float", "nudge", "validate"):
            code, _ = run([cmd, self.ledger, "--today", TODAY])
            self.assertEqual(code, 3, cmd)

    def test_d2_missing_file_exit2(self):
        code, _ = run(["stats", os.path.join(self.dir.name, "no.tsv")])
        self.assertEqual(code, 2)

    def test_d3_future_rows_rejected_by_today(self):
        # --today 提前到 8 月 20 日：8-26 的下午茶变成「未来垫付」
        code, _ = run(["stats", self.ledger, "--today", "2026-08-20"])
        self.assertEqual(code, 2)

    def test_d4_ages_track_today(self):
        # today 提前到 8 月 5 日：8 月的两笔成为未来（须先移除），
        # 服务器账龄 58→28，回到催办线 29 之内 → GREEN
        self.write(GOOD_LEDGER
                   .replace("2026-08-13\t差旅-西安验收\t2750\t\t差旅\n", "")
                   .replace("2026-08-26\t团建-季度下午茶\t386\t\t团建\n", ""))
        code, out = run(["pipeline", self.ledger, "--today", "2026-08-05"])
        self.assertEqual(code, 0)
        self.assertIn("判定 GREEN", out)
        self.assertIn("28天", out)

    def test_d5_version_and_noargs(self):
        with self.assertRaises(SystemExit) as cm:
            run(["--version"])
        self.assertEqual(cm.exception.code, 0)
        with self.assertRaises(SystemExit) as cm:
            run([])
        self.assertEqual(cm.exception.code, 2)

    def test_d6_unknown_command_exit2(self):
        with self.assertRaises(SystemExit):
            run(["verdicts", self.ledger])

    def test_d7_deterministic_output(self):
        _, out1 = run(["pipeline", self.ledger, "--today", TODAY])
        _, out2 = run(["pipeline", self.ledger, "--today", TODAY])
        self.assertEqual(out1, out2)

    def test_d8_examples_ledger_matches_fixture_math(self):
        base = os.path.join(os.path.dirname(__file__), "..", "examples")
        ledger = os.path.join(base, "floats.tsv")
        rows = float_loan.parse_ledger(ledger, self._d(TODAY))
        self.assertEqual(len(rows), 12)
        total = sum(r.amount for r in rows)
        self.assertAlmostEqual(total, 29626.0, places=6)
        _, repaid, _ = float_loan.split(rows)
        self.assertAlmostEqual(float_loan.nudge_line(repaid), 29.0,
                               places=9)

    def test_d9_stdlib_only(self):
        src = os.path.join(os.path.dirname(__file__), "..", "float_loan.py")
        with open(src, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        allowed = {"__future__", "argparse", "datetime", "re", "sys",
                   "unicodedata", "collections", "typing"}
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


if __name__ == "__main__":
    unittest.main()
