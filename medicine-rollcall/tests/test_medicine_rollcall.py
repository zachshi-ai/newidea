#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""medicine-rollcall 验收测试.

覆盖 README 全部验收标准 A1-A10：
双钟模型 / 判决阶梯与恒等式 / 场景矩阵 / 半夜测试 / 囤积质证 /
存放审计 / 衰减推演 / THIN 拒答 / 结构护栏 / 逐字节可复现。
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "medicine_rollcall.py")
EXAMPLE = os.path.join(ROOT, "examples", "medicine_cabinet.tsv")
AS_OF = "2026-09-04"

_spec = importlib.util.spec_from_file_location("mrc", CLI)
mrc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mrc)

HEAD = ("name\trole\tform\tkids\tqty\tunit\texpiry\topened\tlocation"
        "\topen_days\tnote\n")


def row(name="测试药", role="antipyretic", form="blister", kids="",
        qty="9", unit="片", expiry="2027-01-01", opened="",
        location="卧室抽屉", open_days="", note=""):
    return "\t".join([name, role, form, kids, qty, unit, expiry, opened,
                      location, open_days, note]) + "\n"


def ledger(*rows):
    return HEAD + "".join(rows)


def run(tsv_text, *args):
    """写临时账本，跑 CLI，返回 CompletedProcess。"""
    f = tempfile.NamedTemporaryFile(
        "w", suffix=".tsv", delete=False, encoding="utf-8")
    f.write(tsv_text)
    f.close()
    try:
        return subprocess.run(
            [sys.executable, CLI] + list(args) + [f.name],
            capture_output=True, text=True)
    finally:
        os.unlink(f.name)


def run_example(*args):
    return subprocess.run(
        [sys.executable, CLI] + list(args) + [EXAMPLE],
        capture_output=True, text=True)


def box(**kw):
    d = dict(lineno=1, name="测试药", role="antipyretic", form="syrup",
             kids=False, qty=10, unit="ml", expiry=date(2027, 1, 1),
             opened=None, location="", open_days=None, note="")
    d.update(kw)
    return mrc.Box(**d)


# ---------------------------------------------------------------- A1 双钟

class TestDualClock(unittest.TestCase):
    def test_min_clock_open_deadline_wins(self):
        # 开封 2026-03-14 + 30 天 = 04-13，包装 2027-06-30 —— 开封钟先死
        b = box(opened=date(2026, 3, 14), expiry=date(2027, 6, 30))
        self.assertEqual(b.deadline(), date(2026, 4, 13))
        self.assertEqual(b.verdict(date(2026, 9, 4)), "OPENED_OUT")

    def test_min_clock_expiry_wins(self):
        # 包装 2025-12-31 先于开封钟（2026-08-09+28=09-06）
        b = box(opened=date(2026, 8, 9), expiry=date(2025, 12, 31))
        self.assertEqual(b.deadline(), date(2025, 12, 31))
        self.assertEqual(b.verdict(date(2026, 9, 4)), "EXPIRED")

    def test_blister_has_no_open_clock(self):
        b = box(form="blister", opened=date(2020, 1, 1))
        self.assertIsNone(b.open_deadline())
        self.assertEqual(b.verdict(date(2026, 9, 4)), "READY")

    def test_open_days_override_default(self):
        # 眼药水默认 28 天；说明书 7 天则 7 天说了算
        b = box(form="eyedrops", opened=date(2026, 8, 1), open_days=7)
        self.assertEqual(b.deadline(), date(2026, 8, 8))
        self.assertEqual(b.verdict(date(2026, 9, 4)), "OPENED_OUT")
        b2 = box(form="eyedrops", opened=date(2026, 8, 1), open_days=90)
        self.assertEqual(b2.verdict(date(2026, 9, 4)), "READY")

    def test_expiry_day_boundary_in_period(self):
        # 到期日当天算在期内（expiry < as_of 才判 EXPIRED）
        b = box(form="blister", expiry=date(2026, 9, 4))
        self.assertEqual(b.verdict(date(2026, 9, 4)), "READY")
        self.assertEqual(b.verdict(date(2026, 9, 5)), "EXPIRED")

    def test_open_deadline_day_boundary_in_period(self):
        # 开封钟当天到期算在期内（眼药水 08-09 开封 + 28 天 = 09-06）
        b = box(form="eyedrops", opened=date(2026, 8, 9),
                expiry=date(2027, 1, 1))
        self.assertEqual(b.verdict(date(2026, 9, 6)), "READY")
        self.assertEqual(b.verdict(date(2026, 9, 7)), "OPENED_OUT")

    def test_form_default_open_clocks(self):
        self.assertIsNone(mrc.OPEN_CLOCK["blister"])
        self.assertEqual(mrc.OPEN_CLOCK["eyedrops"], 28)
        self.assertEqual(mrc.OPEN_CLOCK["syrup"], 30)
        self.assertEqual(mrc.OPEN_CLOCK["bottle"], 180)


# ---------------------------------------------------------------- A2 判决阶梯

class TestVerdictLadder(unittest.TestCase):
    def test_expired_beats_opened_out(self):
        # 两口钟都死 → 归 EXPIRED（包装钟已过是法律意义上的死亡）
        b = box(expiry=date(2025, 6, 30), opened=date(2025, 1, 1))
        self.assertEqual(b.verdict(date(2026, 9, 4)), "EXPIRED")

    def test_low_line_custom(self):
        b = box(form="blister", qty=5)
        self.assertEqual(b.verdict(date(2026, 9, 4), low_line=3), "READY")
        self.assertEqual(b.verdict(date(2026, 9, 4), low_line=5), "LOW")
        self.assertEqual(b.verdict(date(2026, 9, 4), low_line=4), "READY")

    def test_identity_exact_on_example(self):
        out = run_example("report", "--as-of", AS_OF).stdout
        self.assertIn("恒等式：10 + 3 + 4 + 6 = 23 ✓", out)
        self.assertIn("10/23 = 43.5%", out)

    def test_verdicts_mutually_exclusive_sum(self):
        led = ledger(
            row("A", qty="9"), row("B", qty="2"),                       # READY, LOW
            row("C", form="syrup", opened="2026-01-01"),                # OPENED_OUT
            row("D", form="syrup", opened="2026-01-01", expiry="2026-01-01"),
            row("E", expiry="2020-01-01"), row("F", qty="9"))           # EXPIRED×2
        out = run(led, "report", "--as-of", AS_OF).stdout
        # A READY, B LOW, C OPENED_OUT, D EXPIRED, E EXPIRED, F READY
        self.assertIn("恒等式：2 + 1 + 1 + 2 = 6 ✓", out)


# ---------------------------------------------------------------- A3 场景矩阵

class TestCoverage(unittest.TestCase):
    def test_example_has_red_and_kids_banner(self):
        p = run_example("coverage", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 4)
        self.assertIn("RED  BARE", p.stdout)
        self.assertIn("儿童栏全灭", p.stdout)
        self.assertIn("GREEN", p.stdout)

    def test_thin_exit_3(self):
        led = ledger(row("A"), row("B"), row("C"), row("D"))
        p = run(led, "coverage", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 3)
        self.assertIn("THIN", p.stdout)

    def test_all_green_exit_0(self):
        led = ledger(
            row("退烧药", role="antipyretic", qty="9"),
            row("蒙脱散", role="antidiarrheal", qty="9"),
            row("碘伏", role="disinfectant", qty="9"),
            row("氯雷他定", role="antihistamine", qty="9"),
            row("钙片", role="supplement", qty="9"))
        p = run(led, "coverage", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.count("GREEN"), 4)

    def test_ammo_identity_ready_plus_low(self):
        # 场景可用 = READY + LOW：一个 LOW 弹药仍计入可用
        led = ledger(
            row("退烧药1", role="antipyretic", qty="9"),
            row("退烧药2", role="antipyretic", qty="2"),
            row("蒙脱散", role="antidiarrheal", qty="9"),
            row("碘伏", role="disinfectant", qty="9"),
            row("氯雷他定", role="antihistamine", qty="9"))
        out = run(led, "coverage", "--as-of", AS_OF).stdout
        self.assertIn("2/2 盒可用", out)   # fever: READY + LOW 都算接得住


# ---------------------------------------------------------------- A4 半夜测试

class TestNight(unittest.TestCase):
    def test_kid_bare_exit_4(self):
        p = run_example("night", "--scene", "fever", "--who", "kid",
                        "--as-of", AS_OF)
        self.assertEqual(p.returncode, 4)
        self.assertIn("判决：BARE", p.stdout)

    def test_all_ok_exit_0_with_kids_banner(self):
        p = run_example("night", "--scene", "fever", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 0)
        self.assertIn("判决：OK", p.stdout)
        self.assertIn("儿童栏：全灭", p.stdout)
        self.assertIn("孩子的药箱比大人的先阵亡", p.stdout)

    def test_wound_bare_with_aux_dressing(self):
        p = run_example("night", "--scene", "wound", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 4)
        self.assertIn("辅助弹药", p.stdout)
        self.assertIn("创可贴", p.stdout)

    def test_gut_ok(self):
        p = run_example("night", "--scene", "gut", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 0)

    def test_unknown_scene_exit_2(self):
        p = run_example("night", "--scene", "hangover", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 2)

    def test_ammo_low_yellow_exit_0(self):
        # 场景只有一盒 LOW 弹药：接得住但见底
        led = ledger(
            row("退烧药", role="antipyretic", qty="1"),
            row("蒙脱散", role="antidiarrheal", qty="9"),
            row("碘伏", role="disinfectant", qty="9"),
            row("氯雷他定", role="antihistamine", qty="9"),
            row("钙片", role="supplement", qty="9"))
        p = run(led, "night", "--scene", "fever", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 0)
        self.assertIn("AMMO-LOW", p.stdout)

    def test_night_never_thin(self):
        # 4 盒的小药箱：report 拒判，night 恒开庭
        led = ledger(row("A"), row("B"), row("C"), row("D"))
        p_rep = run(led, "report", "--as-of", AS_OF)
        self.assertEqual(p_rep.returncode, 3)
        p_night = run(led, "night", "--scene", "fever", "--as-of", AS_OF)
        self.assertIn(p_night.returncode, (0, 4))
        self.assertIn("样本薄", p_night.stdout)

    def test_scene_without_any_ammo(self):
        led = ledger(row("钙片", role="supplement", qty="9"),
                     row("维C", role="supplement", qty="9"),
                     row("蒙脱散", role="antidiarrheal", qty="9"),
                     row("碘伏", role="disinfectant", qty="9"),
                     row("氯雷他定", role="antihistamine", qty="9"))
        p = run(led, "night", "--scene", "fever", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 4)
        self.assertIn("没有任何弹药记录", p.stdout)


# ---------------------------------------------------------------- A5 囤积质证

class TestHoard(unittest.TestCase):
    def test_example_assembly_line_exit_4(self):
        p = run_example("hoard", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 4)
        self.assertIn("报废流水线", p.stdout)
        self.assertIn("4 盒里 3 盒在 90 天内到期", p.stdout)

    def test_two_boxes_not_hoard(self):
        led = ledger(row("感冒灵", qty="9"), row("感冒灵", qty="9"),
                     row("蒙脱散", role="antidiarrheal", qty="9"),
                     row("碘伏", role="disinfectant", qty="9"),
                     row("氯雷他定", role="antihistamine", qty="9"))
        p = run(led, "hoard", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 0)
        self.assertIn("无囤积可质证", p.stdout)

    def test_hoard_named_but_long_life_exit_0(self):
        led = ledger(
            row("感冒灵", qty="9", expiry="2029-01-01"),
            row("感冒灵", qty="9", expiry="2029-01-01"),
            row("感冒灵", qty="9", expiry="2029-02-01"),
            row("蒙脱散", role="antidiarrheal", qty="9"),
            row("氯雷他定", role="antihistamine", qty="9"))
        p = run(led, "hoard", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 0)
        self.assertIn("囤积点名", p.stdout)
        self.assertIn("还没过半", p.stdout)

    def test_expired_members_counted_separately(self):
        led = ledger(
            row("感冒灵", qty="9", expiry="2026-11-15"),
            row("感冒灵", qty="9", expiry="2026-11-15"),
            row("感冒灵", qty="9", expiry="2020-01-01"),   # 已过期
            row("蒙脱散", role="antidiarrheal", qty="9"),
            row("氯雷他定", role="antihistamine", qty="9"))
        out = run(led, "hoard", "--as-of", AS_OF).stdout
        self.assertIn("另有 1 盒已过期", out)
        self.assertIn("2 盒里 2 盒在 90 天内到期", out)  # 分母只算未过期


# ---------------------------------------------------------------- A6 存放审计

class TestStash(unittest.TestCase):
    def test_example_bathroom_warnings_exit_0(self):
        p = run_example("stash")
        self.assertEqual(p.returncode, 0)
        self.assertIn("布洛芬混悬液", p.stdout)
        self.assertIn("温湿敏感", p.stdout)

    def test_blister_bathroom_immune(self):
        led = ledger(row("感冒灵", form="blister", location="浴室镜柜",
                         role="other"))
        out = run(led, "stash").stdout
        self.assertIn("免疫", out)
        self.assertNotIn("温湿敏感", out)

    def test_heat_sensitive_in_car_exit_4(self):
        led = ledger(row("退热栓", form="suppository", kids="y",
                         location="车内储物格", role="antipyretic"))
        p = run(led, "stash")
        self.assertEqual(p.returncode, 4)
        self.assertIn("比 栓剂 的熔点热", p.stdout)

    def test_heat_blister_only_warning(self):
        led = ledger(row("感冒灵", form="blister", location="车后座",
                         role="other"))
        p = run(led, "stash")
        self.assertEqual(p.returncode, 0)
        self.assertIn("高温位置", p.stdout)

    def test_clean_cabinet_silent_green(self):
        led = ledger(row("感冒灵", form="blister", location="北卧阴面抽屉",
                         role="other"))
        p = run(led, "stash")
        self.assertEqual(p.returncode, 0)
        self.assertIn("安静通过", p.stdout)


# ---------------------------------------------------------------- A7 衰减推演

class TestSimulate(unittest.TestCase):
    def test_day0_identity_with_report(self):
        out = run_example("simulate", "--days", "90", "--as-of", AS_OF).stdout
        self.assertIn("day 0 战备率 10/23 = 43.5%", out)
        self.assertIn("同一把尺子 ✓", out)

    def test_curve_monotone_and_endpoint(self):
        out = run_example("simulate", "--days", "90", "--as-of", AS_OF).stdout
        rates = []
        for line in out.splitlines():
            if line.strip().startswith("day "):
                rates.append(int(line.split("[")[1].split("]")[0].count("#")))
        self.assertEqual(rates, sorted(rates, reverse=True))   # 单调不增
        self.assertIn("day 90", out)
        self.assertIn("6/23 = 26.1%", out)

    def test_flip_dates_exact(self):
        out = run_example("simulate", "--days", "90", "--as-of", AS_OF).stdout
        self.assertIn("2026-09-07  左西替利嗪滴剂", out)   # 开封钟 09-06 死
        self.assertIn("2026-09-21  蒙脱石散", out)         # 包装钟 09-20 死
        self.assertIn("感冒灵颗粒", out)
        self.assertIn("2026-11-16", out)

    def test_days_30_checkpoints(self):
        out = run_example("simulate", "--days", "30", "--as-of", AS_OF).stdout
        for day in ("day 0", "day 10", "day 20", "day 30"):
            self.assertIn(day, out)
        self.assertNotIn("day 90", out)

    def test_thin_exit_3(self):
        led = ledger(row("A"), row("B"), row("C"), row("D"))
        p = run(led, "simulate", "--days", "90", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 3)


# ---------------------------------------------------------------- A8 THIN 拒答

class TestThin(unittest.TestCase):
    def test_report_thin_exit_3(self):
        led = ledger(row("A"), row("B"), row("C"), row("D"))
        p = run(led, "report", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 3)
        self.assertIn("THIN", p.stdout)
        self.assertIn("逐盒点名 rollcall 仍可用", p.stdout)

    def test_rollcall_works_below_thin(self):
        led = ledger(row("A", expiry="2020-01-01"),
                     row("B", expiry="2020-01-01"))
        p = run(led, "rollcall", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 0)
        self.assertIn("包装钟", p.stdout)


# ---------------------------------------------------------------- A9 结构护栏

class TestGuards(unittest.TestCase):
    def test_bad_date_exit_2(self):
        led = ledger(row("A", expiry="2027/01/01"))
        p = run(led, "report", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 2)
        self.assertIn("日期无法解析", p.stdout)

    def test_qty_zero_exit_2(self):
        led = ledger(row("A", qty="0"))
        self.assertEqual(run(led, "report", "--as-of", AS_OF).returncode, 2)

    def test_qty_negative_exit_2(self):
        led = ledger(row("A", qty="-3"))
        self.assertEqual(run(led, "report", "--as-of", AS_OF).returncode, 2)

    def test_unknown_role_exit_2(self):
        led = ledger(row("A", role="vitamin"))
        p = run(led, "report", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 2)
        self.assertIn("未知角色", p.stdout)

    def test_unknown_form_exit_2(self):
        led = ledger(row("A", form="ampoule"))
        self.assertEqual(run(led, "report", "--as-of", AS_OF).returncode, 2)

    def test_bad_kids_exit_2(self):
        led = ledger(row("A", kids="Y?"))
        self.assertEqual(run(led, "report", "--as-of", AS_OF).returncode, 2)

    def test_bad_open_days_exit_2(self):
        led = ledger(row("A", form="syrup", opened="2026-08-01",
                         open_days="一个月"))
        self.assertEqual(run(led, "report", "--as-of", AS_OF).returncode, 2)

    def test_short_row_exit_2(self):
        led = HEAD + "阿司匹林\tantipyretic\tblister\t\t9\n"
        self.assertEqual(run(led, "report", "--as-of", AS_OF).returncode, 2)

    def test_bad_header_exit_2(self):
        led = "drug\trole\nA\tx\n"
        self.assertEqual(run(led, "report", "--as-of", AS_OF).returncode, 2)

    def test_missing_file_exit_2(self):
        p = subprocess.run(
            [sys.executable, CLI, "report", "--as-of", AS_OF,
             "/nonexistent/cabinet.tsv"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("不存在", p.stdout)

    def test_opened_after_asof_exit_2(self):
        led = ledger(row("A", form="syrup", opened="2026-09-10"))
        p = run(led, "report", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 2)
        self.assertIn("未来开封", p.stdout)

    def test_opened_after_expiry_validate_warns_exit_0(self):
        led = ledger(
            row("A", form="syrup", expiry="2026-08-01", opened="2026-08-02"),
            row("B"), row("C"), row("D"), row("E"))
        p = run(led, "validate", "--as-of", AS_OF)
        self.assertEqual(p.returncode, 0)
        self.assertIn("开封那天药已过期", p.stdout)

    def test_duplicate_rows_validate_warns(self):
        led = ledger(row("感冒灵", qty="9", expiry="2026-11-15"),
                     row("感冒灵", qty="7", expiry="2026-11-15"),
                     row("C"), row("D"), row("E"))
        out = run(led, "validate", "--as-of", AS_OF).stdout
        self.assertIn("疑似重复录入", out)


# ---------------------------------------------------------------- A10 可复现

class TestReproducible(unittest.TestCase):
    def test_default_asof_is_last_opened(self):
        # 缺省 as-of = max(opened) = 2026-08-09（西替利嗪的开封日），
        # 报告必须披露这个选择，绝不偷用系统时钟
        p = run_example("report")
        self.assertIn("缺省=最近开封日", p.stdout)
        self.assertIn("2026-08-09", p.stdout)

    def test_no_opened_requires_explicit_asof(self):
        led = ledger(row("A"), row("B"), row("C"), row("D"), row("E"))
        p = run(led, "report")
        self.assertEqual(p.returncode, 2)
        self.assertIn("--as-of", p.stdout)

    def test_byte_identical_two_runs(self):
        a = run_example("report", "--as-of", AS_OF)
        b = run_example("report", "--as-of", AS_OF)
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(a.returncode, b.returncode)

    def test_bad_explicit_asof_exit_2(self):
        p = run_example("report", "--as-of", "2026/09/04")
        self.assertEqual(p.returncode, 2)


# ---------------------------------------------------------------- 快照字节校验

class TestSnapshots(unittest.TestCase):
    def test_build_examples_check_byte_exact(self):
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, "examples",
                                          "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
