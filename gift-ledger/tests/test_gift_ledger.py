#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gift-ledger 验收测试：README 验收标准表 A1–A13 逐条对应。"""

import contextlib
import datetime as dt
import io
import math
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gift_ledger as gl  # noqa: E402

AS_OF_TEXT = "2026-09-04"
AS_OF = dt.date(2026, 9, 4)
INFL = 0.05

# 13 笔 / 6 人的完整账本（与 examples/gifts.tsv 同源）
FIXTURE = "\n".join([
    "# 列：date direction party relation occasion amount [note]",
    "date\tdirection\tparty\trelation\toccasion\tamount\tnote",
    "2019-10-01\tin\t表妹\tclose-friend\twedding\t500\t我婚礼表妹随的",
    "2020-05-01\tout\t小林\tclose-friend\thousewarming\t300\t小林乔迁",
    "2020-06-06\tout\t老周\tcolleague\twedding\t500\t老周婚礼",
    "2021-10-02\tout\t表哥\tfamily\twedding\t800\t表哥婚礼",
    "2022-04-30\tout\t小林\tclose-friend\twedding\t600\t小林婚礼",
    "2022-10-01\tout\t老周\tcolleague\twedding\t600\t老周再婚",
    "2023-05-01\tin\t表哥\tfamily\twedding\t600\t我婚礼表哥随的",
    "2023-05-20\tout\t老周\tcolleague\tbaby\t400\t老周家满月",
    "2023-10-01\tin\t姑姑\tfamily\twedding\t2000\t我婚礼姑姑随的",
    "2024-06-15\tout\t姑姑\tfamily\thousewarming\t600\t姑姑乔迁",
    "2025-02-10\tin\t姑姑\tfamily\tbaby\t800\t我家满月",
    "2026-03-15\tin\t小林\tclose-friend\tbaby\t1150\t我家满月小林随的",
    "2026-08-01\tin\t阿凯\tdistant\twedding\t300\t老同学补的礼",
]) + "\n"


def money(x):
    return "%.0f" % x


def adj(amount, ymd, as_of=AS_OF, infl=INFL):
    """测试侧独立重算的折算闭式（规格镜像，不调用实现）。"""
    date = dt.datetime.strptime(ymd, "%Y-%m-%d").date()
    return amount * math.pow(1 + infl, (as_of - date).days / 365.25)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="gift-ledger-test-")
        self.ledger = os.path.join(self.dir, "gifts.tsv")
        with open(self.ledger, "w", encoding="utf-8") as fh:
            fh.write(FIXTURE)

    def write(self, text):
        path = os.path.join(self.dir, "case.tsv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gl.main(list(argv))
        return code, out.getvalue(), err.getvalue()


def row(date="2024-01-01", direction="out", party="某人", relation="friend",
        occasion="wedding", amount="600", note=""):
    return "\t".join([date, direction, party, relation, occasion, amount, note])


# ---------------------------------------------------------------------------
# A1 购买力折算
# ---------------------------------------------------------------------------

class TestA1Adjust(Base):
    def test_a1_identity_at_zero_inflation(self):
        self.assertAlmostEqual(
            gl.adjust(600, dt.date(2010, 1, 1), AS_OF, 0.0), 600.0)

    def test_a1_closed_form(self):
        expected = 500 * math.pow(1.05, 2530 / 365.25)  # 表妹 2019-10-01 那笔
        self.assertAlmostEqual(
            gl.adjust(500, dt.date(2019, 10, 1), AS_OF, 0.05), expected)

    def test_a1_older_money_counts_for_more(self):
        older = gl.adjust(600, AS_OF - dt.timedelta(days=2000), AS_OF, 0.05)
        newer = gl.adjust(600, AS_OF - dt.timedelta(days=100), AS_OF, 0.05)
        self.assertGreater(older, newer)

    def test_a1_negative_inflation_shrinks(self):
        self.assertLess(
            gl.adjust(600, AS_OF - dt.timedelta(days=3650), AS_OF, -0.5), 600)


# ---------------------------------------------------------------------------
# A2 系数表与账本校验
# ---------------------------------------------------------------------------

class TestA2TablesAndValidation(Base):
    def test_a2_relation_table(self):
        self.assertEqual({k: v[0] for k, v in gl.RELATIONS.items()},
                         {"family": 1.5, "close-friend": 1.2, "friend": 1.0,
                          "colleague": 0.7, "distant": 0.5})

    def test_a2_occasion_table(self):
        self.assertEqual({k: v[0] for k, v in gl.OCCASIONS.items()},
                         {"wedding": 1.0, "funeral": 1.0, "baby": 0.6,
                          "housewarming": 0.5, "birthday": 0.4, "illness": 0.4})

    def expect_usage(self, *argv):
        code, _, err = self.run_cli(*argv)
        self.assertEqual(code, 2)
        self.assertIn("用法错误", err)
        return err

    def test_a2_unknown_direction(self):
        path = self.write(row(direction="sideways"))
        err = self.expect_usage("ledger", path, "--as-of", AS_OF_TEXT)
        self.assertIn("direction", err)

    def test_a2_unknown_relation(self):
        path = self.write(row(relation="boss"))
        err = self.expect_usage("ledger", path, "--as-of", AS_OF_TEXT)
        self.assertIn("未知关系", err)

    def test_a2_unknown_occasion(self):
        path = self.write(row(occasion="graduation"))
        err = self.expect_usage("ledger", path, "--as-of", AS_OF_TEXT)
        self.assertIn("未知场合", err)

    def test_a2_bad_date(self):
        path = self.write(row(date="2024-02-30"))
        self.expect_usage("ledger", path, "--as-of", AS_OF_TEXT)

    def test_a2_future_date(self):
        path = self.write(row(date="2026-09-05"))
        err = self.expect_usage("ledger", path, "--as-of", AS_OF_TEXT)
        self.assertIn("未来的随礼不算随礼", err)

    def test_a2_amount_must_be_positive(self):
        for bad in ("0", "-1", "abc"):
            path = self.write(row(amount=bad))
            self.expect_usage("ledger", path, "--as-of", AS_OF_TEXT)

    def test_a2_too_few_columns(self):
        path = self.write("2024-01-01\tout\t某人\tfriend\twedding\n")
        err = self.expect_usage("ledger", path, "--as-of", AS_OF_TEXT)
        self.assertIn("第 1 行", err)

    def test_a2_missing_file(self):
        self.expect_usage("ledger", os.path.join(self.dir, "nope.tsv"))

    def test_a2_bad_inflation_rejected(self):
        self.expect_usage("ledger", self.ledger, "--as-of", AS_OF_TEXT,
                          "--inflation", "-1.5")

    def test_a2_header_row_skipped(self):
        # FIXTURE 自带表头行，能正常解析即表头被跳过
        code, out, _ = self.run_cli("ledger", self.ledger, "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("13 笔", out)


# ---------------------------------------------------------------------------
# A3 净余额
# ---------------------------------------------------------------------------

class TestA3Balance(Base):
    def test_a3_formula_in_minus_out_adjusted(self):
        # 表哥：in 600 @2023-05-01，out 800 @2021-10-02
        expected = adj(600, "2023-05-01") - adj(800, "2021-10-02")
        self.assertAlmostEqual(gl.balance_of(
            [gl.Event(dt.date(2023, 5, 1), "in", "表哥", "family", "wedding",
                      600, [], 1),
             gl.Event(dt.date(2021, 10, 2), "out", "表哥", "family", "wedding",
                      800, [], 2)], AS_OF, 0.05), expected)

    def test_a3_positive_balance_means_you_owe(self):
        code, out, _ = self.run_cli("balance", self.ledger, "姑姑",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("你欠人情", out)
        self.assertIn("正 = 你欠着人情", out)

    def test_a3_negative_balance_means_they_owe(self):
        code, out, _ = self.run_cli("balance", self.ledger, "表哥",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("他欠人情", out)
        expected = money(adj(600, "2023-05-01") - adj(800, "2021-10-02"))
        self.assertIn(expected, out)

    def test_a3_zero_inflation_uses_raw_sums(self):
        # 姑姑：in 2000+800 = 2800，out 600 → 余额 2200
        code, out, _ = self.run_cli("balance", self.ledger, "姑姑",
                                    "--as-of", AS_OF_TEXT, "--inflation", "0")
        self.assertEqual(code, 0)
        self.assertIn("2200", out)

    def test_a3_per_event_today_values_listed(self):
        code, out, _ = self.run_cli("balance", self.ledger, "小林",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("1150", out)
        self.assertIn("今日值", out)


# ---------------------------------------------------------------------------
# A4 基线
# ---------------------------------------------------------------------------

class TestA4Baseline(Base):
    def test_a4_baseline_formula(self):
        self.assertAlmostEqual(gl.baseline(600, "family", "baby"), 540.0)
        self.assertAlmostEqual(gl.baseline(600, "colleague", "wedding"), 420.0)
        self.assertAlmostEqual(gl.baseline(800, "distant", "illness"), 160.0)

    def test_a4_base_flag_scales(self):
        code, out, _ = self.run_cli("suggest", self.ledger, "表妹",
                                    "--occasion", "wedding",
                                    "--as-of", AS_OF_TEXT, "--base", "800")
        self.assertEqual(code, 0)
        # 骨架 = 800 × 1.2 × 1.0 = 960
        self.assertIn("960", out)


# ---------------------------------------------------------------------------
# A5 对价锚
# ---------------------------------------------------------------------------

class TestA5Anchor(Base):
    def build_pool(self):
        return gl.pick_party(gl.parse_ledger(self.ledger), "表妹")

    def test_a5_anchor_is_latest_same_occasion_in(self):
        pool = self.build_pool()
        pair = gl.price_anchor(pool, "wedding", AS_OF, 0.05)
        self.assertIsNotNone(pair)
        self.assertAlmostEqual(pair[0], adj(500, "2019-10-01"))
        self.assertEqual(pair[1].date, dt.date(2019, 10, 1))

    def test_a5_no_anchor_without_in_history(self):
        pool = gl.pick_party(gl.parse_ledger(self.ledger), "老周")
        self.assertIsNone(gl.price_anchor(pool, "wedding", AS_OF, 0.05))

    def test_a5_funeral_never_has_anchor(self):
        path = self.write(row(direction="in", party="堂叔", relation="family",
                              occasion="funeral", amount="500",
                              date="2020-01-01"))
        pool = gl.pick_party(gl.parse_ledger(path), "堂叔")
        self.assertIsNone(gl.price_anchor(pool, "funeral", AS_OF, 0.05))
        code, out, _ = self.run_cli("suggest", path, "堂叔",
                                    "--occasion", "funeral",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("白事不讲对价", out)


# ---------------------------------------------------------------------------
# A6 建议区间
# ---------------------------------------------------------------------------

class TestA6Suggest(Base):
    def test_a6_cousin_wedding_band(self):
        # 表妹 wedding：B=720，anchor=adj(500)≈701，D=701 → [710, 1080]
        anchor = adj(500, "2019-10-01")
        self.assertGreater(anchor, 576)  # anchor > 0.8B，锚真的托底
        code, out, _ = self.run_cli("suggest", self.ledger, "表妹",
                                    "--occasion", "wedding",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("建议区间   710 – 1080 元", out)
        self.assertIn("今日对价 %s 元" % money(anchor), out)

    def test_a6_large_debt_capped_at_double_baseline(self):
        # 姑姑 baby：B=540，D≈2502 > 2B → 计入 1080；anchor≈863 → lower=1080
        code, out, _ = self.run_cli("suggest", self.ledger, "姑姑",
                                    "--occasion", "baby", "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("建议区间   1080 – 1350 元", out)
        self.assertIn("大额旧账只还一半", out)

    def test_a6_new_relation_uses_skeleton(self):
        # 老周 wedding：D=0（他欠你）、无锚 → lower = 0.8×420 = 336 → 340
        code, out, _ = self.run_cli("suggest", self.ledger, "老周",
                                    "--occasion", "wedding",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("建议区间   340 – 630 元", out)

    def test_a6_owed_lifts_floor(self):
        # 阿凯：只 in 300（今日 ≈301）→ housewarming lower = min(D, 2B=300)
        code, out, _ = self.run_cli("suggest", self.ledger, "阿凯",
                                    "--occasion", "housewarming",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("建议区间   300 – 370 元", out)
        self.assertIn("未平余额", out)

    def test_a6_unknown_party_refused(self):
        code, _, err = self.run_cli("suggest", self.ledger, "陌生人",
                                    "--occasion", "wedding",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 3)
        self.assertIn("查无此人", err)

    def test_a6_rounding_to_tens(self):
        self.assertEqual(gl.ceil10(701.1), 710)
        self.assertEqual(gl.floor10(1080.0), 1080)
        self.assertEqual(gl.floor10(1087.0), 1080)


# ---------------------------------------------------------------------------
# A7 礼崩
# ---------------------------------------------------------------------------

class TestA7Blackhole(Base):
    def test_a7_oldzhou_is_blackhole(self):
        events = gl.parse_ledger(self.ledger)
        pool = gl.pick_party(events, "老周")
        # bal = −(三笔折算)，最后往来 2023-05-20 距今 > 3 年，无 in
        self.assertTrue(gl.is_blackhole(pool, AS_OF, 0.05, 3.0, 1000.0))

    def test_a7_condition_balance_below_red_line(self):
        path = self.write(row(date="2020-01-01", party="甲", amount="400"))
        pool = gl.pick_party(gl.parse_ledger(path), "甲")
        self.assertFalse(gl.is_blackhole(pool, AS_OF, 0.05, 3.0, 1000.0))

    def test_a7_condition_recent_contact_blocks(self):
        path = self.write(row(date="2026-01-01", party="乙", amount="2000"))
        pool = gl.pick_party(gl.parse_ledger(path), "乙")
        self.assertFalse(gl.is_blackhole(pool, AS_OF, 0.05, 3.0, 1000.0))

    def test_a7_condition_inflow_over_half_blocks(self):
        # 他也随过你一半以上，就算久未往来也不算礼崩
        path = self.write("\n".join([
            row(date="2020-01-01", direction="out", party="丙", amount="2000"),
            row(date="2020-06-01", direction="in", party="丙", amount="1500"),
        ]))
        pool = gl.pick_party(gl.parse_ledger(path), "丙")
        self.assertFalse(gl.is_blackhole(pool, AS_OF, 0.05, 3.0, 1000.0))

    def test_a7_book_exit4_and_listing(self):
        code, out, _ = self.run_cli("book", self.ledger, "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 4)
        self.assertIn("礼崩", out)
        self.assertIn("老周", out)
        self.assertIn("只拒绝假装没看见", out)

    def test_a7_red_amount_flag_relaxes_gate(self):
        code, out, _ = self.run_cli("book", self.ledger, "--as-of", AS_OF_TEXT,
                                    "--red-amount", "5000")
        self.assertEqual(code, 0)
        self.assertIn("礼崩 0", out)
        self.assertNotIn("只拒绝假装没看见", out)
        self.assertNotIn("再无往来", out)

    def test_a7_book_sorted_you_owe_first(self):
        code, out, _ = self.run_cli("book", self.ledger, "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 4)
        # 姑姑（+2502，你欠）在最上，老周（−1875，礼崩）在最下
        self.assertLess(out.index("姑姑"), out.index("表妹"))
        self.assertLess(out.index("表妹"), out.index("阿凯"))
        self.assertLess(out.index("小林"), out.index("表哥"))
        self.assertLess(out.index("表哥"), out.rindex("老周"))

    def test_a7_balance_shows_risk_note(self):
        code, out, _ = self.run_cli("balance", self.ledger, "老周",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("礼崩风险", out)


# ---------------------------------------------------------------------------
# A8 通胀自证
# ---------------------------------------------------------------------------

class TestA8Inflation(Base):
    def test_a8_geo_rate_from_two_years(self):
        # 2020 中位 500（300/500 取上中位）→ 2022 中位 600 → √(6/5)−1
        expected = math.pow(600 / 500, 1 / 2) - 1
        code, out, _ = self.run_cli("inflation", self.ledger,
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("自证年化   %.1f%%" % (expected * 100), out)

    def test_a8_mismatch_suggests_rerun(self):
        code, out, _ = self.run_cli("inflation", self.ledger,
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("--inflation 0.10", out)

    def test_a8_agreement_when_close(self):
        code, out, _ = self.run_cli("inflation", self.ledger,
                                    "--as-of", AS_OF_TEXT,
                                    "--inflation", "0.10")
        self.assertEqual(code, 0)
        self.assertIn("站得住", out)

    def test_a8_too_few_outs_refused(self):
        path = self.write("\n".join([
            row(date="2020-01-01"), row(date="2021-01-01"),
            row(date="2022-01-01"),
            row(date="2023-01-01", direction="in")]))
        code, _, err = self.run_cli("inflation", path, "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 3)
        self.assertIn("至少 4 笔", err)

    def test_a8_needs_two_years_with_pairs(self):
        path = self.write("\n".join([
            row(date="2020-01-01"), row(date="2020-06-01"),
            row(date="2020-10-01"), row(date="2021-01-01")]))
        code, _, err = self.run_cli("inflation", path, "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 3)
        self.assertIn("两个各含 2 笔", err)


# ---------------------------------------------------------------------------
# A9 simulate
# ---------------------------------------------------------------------------

class TestA9Simulate(Base):
    def test_a9_new_balance_and_future_anchor(self):
        code, out, _ = self.run_cli("simulate", self.ledger, "老周",
                                    "--amount", "300", "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        new_bal = -(adj(500, "2020-06-06") + adj(600, "2022-10-01")
                    + adj(400, "2023-05-20")) - 300
        self.assertIn("→ %s 元" % money(new_bal), out)
        self.assertIn("对价锚将变成 %s 元" % money(300 * 1.05 ** 2), out)  # 331

    def test_a9_owed_case_warns_about_grudge(self):
        code, out, _ = self.run_cli("simulate", self.ledger, "姑姑",
                                    "--amount", "500", "--occasion", "baby",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("别怪对方记仇", out)

    def test_a9_low_amount_neutral_note_when_they_owe(self):
        code, out, _ = self.run_cli("simulate", self.ledger, "老周",
                                    "--amount", "300", "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("场面骨架要求更多", out)

    def test_a9_amount_must_be_positive(self):
        for bad in ("0", "-5"):
            code, _, err = self.run_cli("simulate", self.ledger, "老周",
                                        "--amount", bad, "--as-of", AS_OF_TEXT)
            self.assertEqual(code, 2)

    def test_a9_unknown_occasion(self):
        code, _, err = self.run_cli("simulate", self.ledger, "老周",
                                    "--amount", "300", "--occasion", " gradu",
                                    "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 2)


# ---------------------------------------------------------------------------
# A10 普查
# ---------------------------------------------------------------------------

class TestA10Ledger(Base):
    def test_a10_census(self):
        code, out, _ = self.run_cli("ledger", self.ledger, "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("13 笔 / 6 人", out)
        self.assertIn("in 6 · out 7", out)
        self.assertIn("总余额", out)

    def test_a10_coefficient_tables(self):
        code, out, _ = self.run_cli("ledger", self.ledger, "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("family 1.5", out)
        self.assertIn("wedding 1.0", out)
        self.assertIn("funeral 1.0", out)

    def test_a10_empty_ledger_refused(self):
        path = self.write("# 只有注释\n")
        code, _, err = self.run_cli("ledger", path, "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 3)
        self.assertIn("拒算", err)


# ---------------------------------------------------------------------------
# A11 exit codes 与确定性
# ---------------------------------------------------------------------------

class TestA11ExitsAndDeterminism(Base):
    def test_a11_exit_code_table(self):
        cases = [
            (("ledger", self.ledger, "--as-of", AS_OF_TEXT), 0),
            (("balance", self.ledger, "小林", "--as-of", AS_OF_TEXT), 0),
            (("suggest", self.ledger, "表妹", "--occasion", "wedding",
              "--as-of", AS_OF_TEXT), 0),
            (("book", self.ledger, "--as-of", AS_OF_TEXT), 4),
            (("inflation", self.ledger, "--as-of", AS_OF_TEXT), 0),
            (("simulate", self.ledger, "老周", "--amount", "300",
              "--as-of", AS_OF_TEXT), 0),
            (("balance", self.ledger, "路人", "--as-of", AS_OF_TEXT), 3),
        ]
        for argv, expected in cases:
            code, _, _ = self.run_cli(*argv)
            self.assertEqual(code, expected, msg=str(argv))

    def test_a11_no_command_prints_help(self):
        code, _, _ = self.run_cli()
        self.assertEqual(code, 2)

    def test_a11_same_args_same_bytes(self):
        _, out1, _ = self.run_cli("book", self.ledger, "--as-of", AS_OF_TEXT)
        _, out2, _ = self.run_cli("book", self.ledger, "--as-of", AS_OF_TEXT)
        self.assertEqual(out1, out2)

    def test_a11_default_asof_is_today(self):
        code, out, _ = self.run_cli("ledger", self.ledger)
        self.assertEqual(code, 0)
        self.assertIn(dt.date.today().isoformat(), out)

    def test_a11_verdict_band_semantics(self):
        # band = max(200, 15%×flow)：小林双向几乎打平 → balanced
        events = gl.parse_ledger(self.ledger)
        pool = gl.pick_party(events, "小林")
        bal = gl.balance_of(pool, AS_OF, 0.05)
        self.assertEqual(gl.verdict_of(bal, pool, AS_OF, 0.05), "balanced")
        # 人造小额账本：flow≈627 → band=200，余额 −259 → 他欠人情
        path = self.write("\n".join([
            row(date="2025-01-01", direction="out", party="丁", amount="600"),
            row(date="2026-06-01", direction="in", party="丁", amount="300"),
        ]))
        code, out, _ = self.run_cli("balance", path, "丁", "--as-of", AS_OF_TEXT)
        self.assertEqual(code, 0)
        self.assertIn("他欠人情", out)


# ---------------------------------------------------------------------------
# A12 examples：重建逐字节一致
# ---------------------------------------------------------------------------

class TestA12Examples(unittest.TestCase):
    def test_a12_examples_byte_identical(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(root, "examples", "build_examples.py")
        proc = subprocess.run([sys.executable, script, "--check"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         "examples 与重建结果不一致：\n%s%s"
                         % (proc.stdout, proc.stderr))


if __name__ == "__main__":
    unittest.main()
