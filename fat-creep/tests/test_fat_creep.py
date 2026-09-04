# -*- coding: utf-8 -*-
"""缓胖 · Fat Creep 验收测试。

锚点数字全部先手算再钉死（胖橘 4.10→4.86 跨 427 天 = +0.0534 kg/月 = +1.10%/月；
体外驱虫 2026-07-25+30 = 2026-08-24，as-of 2026-09-03 剩 −10 天 OVERDUE；
胖橘开销 5159/354d = 437.20/月 = 5246.44/年，医疗 3440 = 66.7%）。
"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "fat_creep.py")
EX = os.path.join(ROOT, "examples")
sys.path.insert(0, ROOT)
import fat_creep as fc  # noqa: E402

PY = sys.executable or "python3"
DEMO_W = os.path.join(EX, "weights.tsv")
DEMO_E = os.path.join(EX, "events.tsv")


def run(argv):
    p = subprocess.run([PY, CLI] + argv, capture_output=True, text=True, encoding="utf-8")
    return p.stdout, p.stderr, p.returncode


class TempLedgerCase(unittest.TestCase):
    """临时账本基类：写两本 TSV、跑命令、不留路径于输出。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="fatcreep-test-")
        self.w = os.path.join(self.dir, "weights.tsv")
        self.e = os.path.join(self.dir, "events.tsv")

    def write(self, rows_w=(), rows_e=(), header_w=None, header_e=None):
        hw = header_w if header_w is not None else "date\tpet\tweight_kg\tnote"
        he = header_e if header_e is not None else "date\tpet\tkind\titem\tamount\tnote"
        with open(self.w, "w", encoding="utf-8") as f:
            f.write(hw + "\n")
            for r in rows_w:
                f.write("\t".join(str(c) for c in r) + "\n")
        with open(self.e, "w", encoding="utf-8") as f:
            f.write(he + "\n")
            for r in rows_e:
                f.write("\t".join(str(c) for c in r) + "\n")

    def cli(self, args):
        return run(args + [self.w, self.e])


# ---------------- 归一与分类（单元级） ----------------

class TestNormalize(unittest.TestCase):
    def test_alias_convergence(self):
        for a, b in [("狂犬", "rabies"), ("狂犬疫苗", "RABIES"), ("猫 三联", "fvrhc"),
                     ("体外驱虫", "flea"), ("check-up", "体检"), ("体内驱虫", "拜宠清")]:
            self.assertEqual(fc.match_item(a), fc.match_item(b), (a, b))

    def test_match_item_keys(self):
        self.assertEqual(fc.match_item("狂犬"), "vaccine_rabies")
        self.assertEqual(fc.match_item("妙三多"), "vaccine_fvrhc")
        self.assertEqual(fc.match_item("卫佳伍"), "vaccine_dhpp")
        self.assertIsNone(fc.match_item("全身按摩"))

    def test_cost_cat_priority_rx_over_food(self):
        self.assertEqual(fc.cost_cat("处方罐头 x6"), "medical")
        self.assertEqual(fc.cost_cat("处方粮"), "medical")
        self.assertEqual(fc.cost_cat("渴望鸡猫粮 6kg"), "food")
        self.assertEqual(fc.cost_cat("猫砂 4 袋"), "supply")
        self.assertEqual(fc.cost_cat("洗澡美容"), "groom")
        self.assertEqual(fc.cost_cat("尿闭住院 4 天"), "medical")
        self.assertEqual(fc.cost_cat("神秘物品"), "other")

    def test_norm_folds_punct_and_case(self):
        self.assertEqual(fc.norm("Check-Up!"), fc.norm("checkup"))
        self.assertEqual(fc.norm("  狂犬  "), "狂犬")


class TestRateOf(unittest.TestCase):
    def test_full_span_anchor(self):
        import datetime
        pairs = [(datetime.date(2025, 7, 1), 4.10), (datetime.date(2026, 9, 1), 4.86)]
        kg_mo, pct, span = fc.rate_of(pairs)
        self.assertEqual(span, 427)
        self.assertAlmostEqual(kg_mo, 0.0534, places=4)
        self.assertAlmostEqual(pct, 1.10, places=2)

    def test_zero_span_safe(self):
        import datetime
        d = datetime.date(2026, 1, 1)
        kg_mo, pct, span = fc.rate_of([(d, 4.0), (d, 5.0)])
        self.assertEqual((kg_mo, pct, span), (0.0, 0.0, 0))


# ---------------- 解析与账坏 ----------------

class TestParseErrors(TempLedgerCase):
    def test_bad_header_missing_cols(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0")], header_w="date\tpet\tgrams")
        out, err, code = self.cli(["trend"])
        self.assertEqual(code, 2)
        self.assertIn("missing", err)

    def test_bad_date(self):
        self.write(rows_w=[("2026-13-01", "A", "4.0"), ("2026-02-01", "A", "4.0"), ("2026-03-01", "A", "4.1")])
        _, err, code = self.cli(["trend"])
        self.assertEqual(code, 2)
        self.assertIn("impossible date", err)  # 13 月过得了正则过不了日历

    def test_negative_amount(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0"), ("2026-02-01", "A", "4.0"), ("2026-03-01", "A", "4.1")],
                   rows_e=[("2026-01-05", "A", "cost", "猫粮", "-10")])
        _, err, code = self.cli(["cost"])
        self.assertEqual(code, 2)
        self.assertIn("negative amount", err)

    def test_unknown_kind(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0"), ("2026-02-01", "A", "4.0"), ("2026-03-01", "A", "4.1")],
                   rows_e=[("2026-01-05", "A", "赠送", "猫粮", "10")])
        _, err, code = self.cli(["cost"])
        self.assertEqual(code, 2)
        self.assertIn("unknown kind", err)

    def test_unknown_care_item_hints_interval(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0"), ("2026-02-01", "A", "4.0"), ("2026-03-01", "A", "4.1")],
                   rows_e=[("2026-01-05", "A", "care", "全身按摩")])
        _, err, code = self.cli(["due"])
        self.assertEqual(code, 2)
        self.assertIn("--interval", err)

    def test_free_column_order(self):
        self.write(rows_w=[("A", "4.0", "x", "2026-01-01"), ("A", "4.0", "", "2026-02-01"), ("A", "4.1", "", "2026-03-01")],
                   header_w="pet\tweight_kg\tnote\tdate")
        _, _, code = self.cli(["trend"])
        self.assertEqual(code, 0)

    def test_comments_and_blank_lines_skipped(self):
        with open(self.w, "w", encoding="utf-8") as f:
            f.write("# 注释\n\n date\tpet\tweight_kg\tnote\n2026-01-01\tA\t4.00\t\n2026-02-01\tA\t4.00\t\n2026-03-01\tA\t4.01\t\n")
        with open(self.e, "w", encoding="utf-8") as f:
            f.write("date\tpet\tkind\titem\tamount\tnote\n")
        out, _, code = self.cli(["trend"])
        self.assertEqual(code, 0)
        self.assertIn("A", out)


# ---------------- trend：蠕涨判级 ----------------

class TestTrend(TempLedgerCase):
    def test_demo_anchors(self):
        out, _, code = run(["trend", DEMO_W, DEMO_E])
        self.assertEqual(code, 4)  # 胖橘 CREEP
        self.assertIn("+0.0534", out)
        self.assertIn("+1.10", out)
        self.assertIn("+1.68", out)   # 90d preview
        self.assertIn("CREEP", out)
        self.assertIn("STEADY", out)
        self.assertIn("+0.06", out)   # 豆包
        self.assertIn("DECLINE", out) # 糯米
        self.assertIn("+5.33", out)   # 糯米速率照出

    def test_decline_does_not_gate_exit(self):
        out, _, code = run(["trend", DEMO_W, DEMO_E, "--pet", "糯米"])
        self.assertEqual(code, 0)  # DECLINE 不是红灯
        self.assertIn("DECLINE", out)

    def test_replay_march_was_green(self):
        out, _, code = run(["trend", DEMO_W, DEMO_E, "--as-of", "2026-03-20"])
        self.assertEqual(code, 0)
        self.assertIn("+0.97", out)   # 胖橘三月全期 0.97%
        self.assertIn("STEADY", out)

    def test_creep_line_override(self):
        _, _, code = run(["trend", DEMO_W, DEMO_E, "--creep-line", "2.0"])
        self.assertEqual(code, 0)  # 1.10 < 2.0 翻案
        out, _, code = run(["trend", DEMO_W, DEMO_E, "--creep-line", "0.5"])
        self.assertEqual(code, 4)  # 1.10 > 0.5 更严

    def test_90d_is_preview_not_gate(self):
        # 全期 0.74% STEADY，近 90 天 1.32% —— 预警展示但不挂 exit
        self.write(rows_w=[("2026-01-01", "A", "4.00"), ("2026-04-01", "A", "4.07"),
                           ("2026-07-01", "A", "4.14"), ("2026-09-03", "A", "4.26")],
                   rows_e=[("2026-01-01", "A", "care", "狂犬疫苗", "80")])
        out, _, code = self.cli(["trend", "--as-of", "2026-09-03"])
        self.assertEqual(code, 0)
        self.assertIn("STEADY", out)
        self.assertIn("+1.32", out)

    def test_exactly_one_pct_is_steady(self):
        # 3.60→4.00 跨 300 天 = 恰 1.00%/月，> 才红灯
        self.write(rows_w=[("2025-11-08", "A", "3.60"), ("2026-02-08", "A", "3.80"), ("2026-09-04", "A", "4.00")])
        out, _, code = self.cli(["trend", "--as-of", "2026-09-04"])
        self.assertEqual(code, 0)
        self.assertIn("STEADY", out)

    def test_thin_span_boundary_59_vs_60(self):
        self.write(rows_w=[("2026-06-06", "A", "4.00"), ("2026-07-06", "A", "4.00"), ("2026-08-04", "A", "4.00")])
        out, _, code = self.cli(["trend", "--as-of", "2026-08-04"])
        self.assertEqual(code, 0)
        self.assertIn("DECLINE", out)  # 59 天 < 60
        self.write(rows_w=[("2026-06-05", "A", "4.00"), ("2026-07-06", "A", "4.00"), ("2026-08-04", "A", "4.00")])
        out, _, code = self.cli(["trend", "--as-of", "2026-08-04"])
        self.assertEqual(code, 0)
        self.assertNotIn("DECLINE", out)  # 60 天恰过线

    def test_two_obs_declines_even_if_long_span(self):
        self.write(rows_w=[("2025-07-01", "A", "4.00"), ("2026-09-01", "A", "5.00")])
        out, _, code = self.cli(["trend"])
        self.assertEqual(code, 0)
        self.assertIn("DECLINE", out)


# ---------------- due：免疫日历 ----------------

class TestDue(TempLedgerCase):
    def test_demo_anchors(self):
        out, _, code = run(["due", DEMO_W, DEMO_E])
        self.assertEqual(code, 4)
        self.assertIn("体外驱虫", out)
        self.assertIn("2026-08-24", out)
        self.assertIn("OVERDUE", out)
        self.assertIn("DUE-SOON", out)
        self.assertIn("NEVER-SEEN", out)

    def test_due_soon_only_is_green(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0"), ("2026-02-01", "A", "4.0"), ("2026-03-01", "A", "4.1")],
                   rows_e=[("2026-06-10", "A", "care", "体内驱虫", "40")])
        out, _, code = self.cli(["due", "--as-of", "2026-09-03"])  # next 09-08 剩 5 天
        self.assertEqual(code, 0)
        self.assertIn("DUE-SOON", out)
        self.assertNotIn("OVERDUE", out)

    def test_interval_override_flips_overdue(self):
        _, _, code = run(["due", DEMO_W, DEMO_E])
        self.assertEqual(code, 4)
        out, _, code = run(["due", DEMO_W, DEMO_E, "--interval", "体外驱虫=45"])
        self.assertEqual(code, 0)  # next 09-08 剩 5 → DUE-SOON，翻案
        self.assertIn("2026-09-08", out)
        self.assertNotIn("OVERDUE", out)

    def test_interval_accepts_alias(self):
        out, _, code = run(["due", DEMO_W, DEMO_E, "--interval", "flea=45"])
        self.assertEqual(code, 0)  # flea ≡ 体外驱虫

    def test_due_today_boundary(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0"), ("2026-02-01", "A", "4.0"), ("2026-03-01", "A", "4.1")],
                   rows_e=[("2025-09-03", "A", "care", "狂犬疫苗", "80")])
        out, _, code = self.cli(["due", "--as-of", "2026-09-03"])  # next = as-of 当天
        self.assertEqual(code, 0)
        self.assertIn("DUE-TODAY", out)

    def test_soon_window_boundary_14_vs_15(self):
        # A: 体内驱虫 2026-06-19 + 90 = 09-17，as-of 09-03 剩恰 14 → DUE-SOON（含 14）
        # B: 体检 2025-09-18 + 365 = 2026-09-18，剩恰 15 → OK（>14 才 OK）
        base_w = [("2026-01-01", "A", "4.0"), ("2026-02-01", "A", "4.0"), ("2026-03-01", "A", "4.1"),
                  ("2026-01-01", "B", "4.0"), ("2026-02-01", "B", "4.0"), ("2026-03-01", "B", "4.1")]
        self.write(rows_w=base_w,
                   rows_e=[("2026-06-19", "A", "care", "体内驱虫", ""),
                           ("2025-09-18", "B", "care", "体检", "")])
        out, _, code = self.cli(["due", "--as-of", "2026-09-03"])
        self.assertEqual(code, 0)
        a_line = [l for l in out.splitlines() if l.startswith("A") and "体内驱虫" in l][0]
        b_line = [l for l in out.splitlines() if l.startswith("B") and "体检" in l][0]
        self.assertIn("DUE-SOON", a_line)
        self.assertIn("OK", b_line)
        self.assertIn("2026-09-17", out)
        self.assertIn("2026-09-18", out)
        self.assertNotIn("OVERDUE", out)

    def test_never_seen_species_aware(self):
        out, _, code = run(["due", DEMO_W, DEMO_E, "--pet", "豆包"])
        self.assertEqual(code, 0)
        self.assertIn("NEVER-SEEN", out)
        self.assertIn("体外驱虫", out)
        self.assertNotIn("猫三联", out)  # 物种感知：狗不点猫疫苗

    def test_never_seen_unknown_species(self):
        # 只有过体检的宠：物种 unknown → 只点 both 品目，不点猫犬专属
        self.write(rows_w=[("2026-01-01", "A", "4.0"), ("2026-02-01", "A", "4.0"), ("2026-03-01", "A", "4.1")],
                   rows_e=[("2025-12-01", "A", "care", "体检", "280")])
        out, _, code = self.cli(["due"])
        self.assertIn("NEVER-SEEN", out)
        self.assertIn("狂犬疫苗", out)
        self.assertNotIn("猫三联", out)
        self.assertNotIn("犬四联", out)

    def test_empty_care_is_thin(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0")], rows_e=[("2026-01-05", "A", "cost", "猫粮", "20")])
        _, err, code = self.cli(["due"])
        self.assertEqual(code, 3)
        self.assertIn("STATISTICS REFUSED", err)

    def test_english_aliases_same_result(self):
        out_cn, _, _ = run(["due", DEMO_W, DEMO_E, "--pet", "胖橘"])
        self.write(rows_w=[(d, p, w) for d, p, w in [
            ("2025-07-01", "胖橘", "4.10"), ("2025-08-02", "胖橘", "4.15"), ("2025-09-03", "胖橘", "4.19"),
            ("2025-09-15", "胖橘", "4.20"), ("2026-01-13", "胖橘", "4.37"), ("2026-05-25", "胖橘", "4.62"),
            ("2026-07-30", "胖橘", "4.75"), ("2026-09-01", "胖橘", "4.86")]],
            rows_e=[("2025-09-15", "胖橘", "care", "rabies", "80"),
                    ("2025-09-15", "胖橘", "care", "fvrhc", "180"),
                    ("2025-09-20", "胖橘", "care", "check-up", "300"),
                    ("2026-07-25", "胖橘", "care", "flea", "60"),
                    ("2026-06-10", "胖橘", "care", "deworm_int", "40")])
        out_en, _, code = self.cli(["due", "--as-of", "2026-09-03"])
        self.assertEqual(code, 4)
        for anchor in ("2026-08-24", "2026-09-15", "2026-09-08", "2026-09-20", "OVERDUE"):
            self.assertIn(anchor, out_en)
        # 中文原账同样的到期日集合
        for anchor in ("2026-08-24", "2026-09-15", "2026-09-08", "2026-09-20"):
            self.assertIn(anchor, out_cn)


# ---------------- cost：铲屎官年账 ----------------

class TestCost(TempLedgerCase):
    def test_demo_anchors(self):
        out, _, code = run(["cost", DEMO_W, DEMO_E])
        self.assertEqual(code, 0)
        self.assertIn("5159.00", out)
        self.assertIn("354d", out)
        self.assertIn("437.20", out)
        self.assertIn("5246.44", out)
        self.assertIn("66.7%", out)
        self.assertIn("1695.00", out)
        self.assertIn("2276.87", out)
        self.assertIn("57.5%", out)
        self.assertIn("6854.00", out)
        self.assertIn("7523.31", out)  # 先各自 round 后相加
        self.assertIn("myth", out)     # 医疗才是大头
        self.assertIn("top category: food", out)  # 豆包是粮

    def test_category_identity_holds(self):
        out, _, code = run(["cost", DEMO_W, DEMO_E])
        self.assertEqual(code, 0)
        # 胖橘分类行之和 = 总额（恒等式）
        seg = out.split("[胖橘]")[1].split("[豆包]")[0]
        total = 1554.00 + 3440.00 + 165.00
        cats = sum(float(l.split()[1]) for l in seg.splitlines() if l.strip() and l.split()[0] in ("food", "medical", "supply", "groom", "other"))
        self.assertAlmostEqual(cats, total, places=9)

    def test_care_amount_counts_once_not_twice(self):
        # 只有 care 行金额：total = 疫苗价，没有双记
        self.write(rows_w=[("2026-01-01", "A", "4.0")],
                   rows_e=[("2026-01-05", "A", "care", "狂犬疫苗", "80")])
        out, _, code = self.cli(["cost", "--as-of", "2026-09-03"])
        self.assertEqual(code, 0)
        self.assertIn("80.00", out)
        self.assertNotIn("160.00", out)

    def test_thin_coverage_refuses_annualization(self):
        out, _, code = run(["cost", DEMO_W, DEMO_E, "--as-of", "2025-10-01"])  # 胖橘覆盖 17 天
        self.assertEqual(code, 3)
        self.assertIn("annualization refused", out)
        self.assertIn("560.00", out)  # 算术照出：狂犬80+三联180+体检300（10-12 的粮被剪切）

    def test_coverage_boundary_30d(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0")],
                   rows_e=[("2026-08-05", "A", "cost", "猫粮", "100")])
        out, _, code = self.cli(["cost", "--as-of", "2026-09-03"])  # cov = 30 恰过线
        self.assertEqual(code, 0)
        self.assertIn("yearly", out)

    def test_uncategorized_banner(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0")],
                   rows_e=[("2026-08-05", "A", "cost", "神秘物品", "100"),
                           ("2026-08-06", "A", "cost", "猫粮", "50")])
        out, _, code = self.cli(["cost", "--as-of", "2026-09-03"])
        self.assertEqual(code, 0)
        self.assertIn("UNCATEGORIZED", out)
        self.assertIn("skin in the game", out)

    def test_pet_filter_and_weight_rows_ignored(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0")],
                   rows_e=[("2026-08-05", "A", "cost", "猫粮", "100"),
                           ("2026-08-06", "A", "weight", "称重记录", "999")])
        out, _, code = self.cli(["cost", "--as-of", "2026-09-03"])
        self.assertEqual(code, 0)
        self.assertIn("100.00", out)
        self.assertNotIn("999", out)

    def test_no_cost_rows_thin(self):
        self.write(rows_w=[("2026-01-01", "A", "4.0")], rows_e=[("2026-01-05", "A", "care", "狂犬疫苗")])
        _, err, code = self.cli(["cost"])
        self.assertEqual(code, 3)


# ---------------- diet：减肥投影 ----------------

class TestDiet(TempLedgerCase):
    def test_demo_projection(self):
        out, _, code = run(["diet", DEMO_W, DEMO_E, "--pet", "胖橘", "--target", "4.40"])
        self.assertEqual(code, 0)
        self.assertIn("0.46 kg", out)
        self.assertIn("9.47 raw-weeks", out)
        self.assertIn("10 weeks", out)
        self.assertIn("2026-11-12", out)
        self.assertIn("never fast", out)

    def test_rate_two_percent(self):
        out, _, code = run(["diet", DEMO_W, DEMO_E, "--pet", "胖橘", "--target", "4.40", "--rate", "2"])
        self.assertEqual(code, 0)
        self.assertIn("5 weeks", out)          # 4.734 → ceil 5
        self.assertIn("2026-10-08", out)       # 09-03 + 35d

    def test_deadline_red_line(self):
        out, _, code = run(["diet", DEMO_W, DEMO_E, "--pet", "胖橘", "--target", "4.40", "--deadline", "2026-09-25"])
        self.assertEqual(code, 4)
        self.assertIn("3.01%/wk", out)
        self.assertIn("lipidosis", out)

    def test_deadline_far_is_ok(self):
        out, _, code = run(["diet", DEMO_W, DEMO_E, "--pet", "胖橘", "--target", "4.40", "--deadline", "2026-11-12"])
        self.assertEqual(code, 0)
        self.assertIn("within the hard line", out)

    def test_target_at_or_above_current(self):
        out, _, code = run(["diet", DEMO_W, DEMO_E, "--pet", "胖橘", "--target", "4.86"])
        self.assertEqual(code, 0)
        self.assertIn("nothing to lose", out)
        out, _, code = run(["diet", DEMO_W, DEMO_E, "--pet", "胖橘", "--target", "5.50"])
        self.assertEqual(code, 0)
        self.assertIn("nothing to lose", out)

    def test_missing_target_is_ledger_error(self):
        _, _, code = run(["diet", DEMO_W, DEMO_E, "--pet", "胖橘"])
        self.assertEqual(code, 2)

    def test_unknown_pet(self):
        _, _, code = run(["diet", DEMO_W, DEMO_E, "--pet", "不存在", "--target", "4.0"])
        self.assertEqual(code, 2)


# ---------------- validate：账本体检 ----------------

class TestValidate(TempLedgerCase):
    def test_demo_clean(self):
        out, _, code = run(["validate", DEMO_W, DEMO_E])
        self.assertEqual(code, 0)
        self.assertIn("clean", out)

    def test_single_day_jump_broken(self):
        self.write(rows_w=[("2026-07-01", "A", "4.00"), ("2026-07-02", "A", "5.50")])
        out, _, code = self.cli(["validate", "--as-of", "2026-09-03"])
        self.assertEqual(code, 2)
        self.assertIn("mathematically impossible", out)

    def test_exactly_ten_pct_jump_ok(self):
        self.write(rows_w=[("2026-07-01", "A", "4.00"), ("2026-07-02", "A", "4.40")])
        out, _, code = self.cli(["validate", "--as-of", "2026-09-03"])
        self.assertEqual(code, 0)
        self.assertIn("clean", out)

    def test_unit_mixup_suspect(self):
        self.write(rows_w=[("2026-07-01", "A", "4.40"), ("2026-07-15", "A", "4.50"), ("2026-08-01", "A", "9.92")])
        out, _, code = self.cli(["validate", "--as-of", "2026-09-03"])
        self.assertEqual(code, 2)
        self.assertIn("SUSPECT-UNIT", out)
        self.assertIn("kg/lb", out)

    def test_future_rows_broken_when_pinned(self):
        self.write(rows_w=[("2026-07-01", "A", "4.00"), ("2026-07-15", "A", "4.05"), ("2026-09-10", "A", "4.10")],
                   rows_e=[("2026-09-20", "A", "cost", "猫粮", "50")])
        out, _, code = self.cli(["validate", "--as-of", "2026-09-03"])
        self.assertEqual(code, 2)
        self.assertIn("future weight row", out)
        self.assertIn("future cost row", out)

    def test_future_rows_fine_when_anchored(self):
        # 缺省 as-of = 账本末日，未来行就是末日本身 → 不报
        self.write(rows_w=[("2026-07-01", "A", "4.00"), ("2026-07-15", "A", "4.05"), ("2026-09-10", "A", "4.10")],
                   rows_e=[("2026-09-20", "A", "cost", "猫粮", "50")])
        out, _, code = self.cli(["validate"])
        self.assertEqual(code, 0)

    def test_negative_weight(self):
        self.write(rows_w=[("2026-07-01", "A", "-4.0")])
        _, _, code = self.cli(["validate"])
        self.assertEqual(code, 2)

    def test_duplicate_date(self):
        self.write(rows_w=[("2026-07-01", "A", "4.00"), ("2026-07-01", "A", "4.02")])
        out, _, code = self.cli(["validate"])
        self.assertEqual(code, 2)
        self.assertIn("duplicate", out)


# ---------------- report：总览与聚合 ----------------

class TestReport(TempLedgerCase):
    def test_demo_report_red(self):
        out, _, code = run(["report", DEMO_W, DEMO_E, "--as-of", "2026-09-03"])
        self.assertEqual(code, 4)
        for anchor in ("[糯米]", "[胖橘]", "[豆包]", "CREEP", "OVERDUE", "never seen",
                       "5246.44", "2276.87", "RED present"):
            self.assertIn(anchor, out)

    def test_demo_report_replay_green(self):
        out, _, code = run(["report", DEMO_W, DEMO_E, "--as-of", "2026-03-20"])
        self.assertEqual(code, 0)
        self.assertIn("no red lights", out)
        self.assertIn("STEADY", out)

    def test_pet_filter(self):
        out, _, code = run(["report", DEMO_W, DEMO_E, "--pet", "豆包"])
        self.assertEqual(code, 0)
        self.assertIn("[豆包]", out)
        self.assertNotIn("[胖橘]", out)

    def test_all_weights_cut_is_thin(self):
        _, _, code = run(["report", DEMO_W, DEMO_E, "--as-of", "2025-06-01"])
        self.assertEqual(code, 3)


# ---------------- 可复现性与隐私 ----------------

class TestRepro(TempLedgerCase):
    def test_byte_identical_reruns(self):
        a = run(["report", DEMO_W, DEMO_E])
        b = run(["report", DEMO_W, DEMO_E])
        self.assertEqual(a[0], b[0])

    def test_default_asof_is_ledger_end(self):
        out, _, _ = run(["trend", DEMO_W, DEMO_E])
        self.assertIn("2026-09-03 (ledger-anchored)", out)
        out, _, _ = run(["trend", DEMO_W, DEMO_E, "--as-of", "2026-09-03"])
        self.assertIn("2026-09-03 (pinned)", out)

    def test_reports_never_echo_paths(self):
        for argv in (["report", "--as-of", "2026-09-03"], ["trend"], ["due"], ["cost"], ["validate"]):
            out, err, _ = run(argv + [DEMO_W, DEMO_E])
            self.assertNotIn(EX, out, argv)
            self.assertNotIn(EX, err, argv)

    def test_exit_code_constants(self):
        self.assertEqual((fc.EXIT_OK, fc.EXIT_LEDGER, fc.EXIT_THIN, fc.EXIT_RED), (0, 2, 3, 4))


if __name__ == "__main__":
    unittest.main()
