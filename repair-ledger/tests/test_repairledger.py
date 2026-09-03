"""Acceptance tests for 续命账 · Repair Ledger.

Every acceptance criterion from the README lives here: ledger parsing and
validation, service-year and sunk-cost math, the repair trail (actual vs
claimed, censoring, failed repairs), the global pie factor, diminishing
return detection, the FIX / REPLACE / SCRAP verdict with its exit codes,
CLI behavior — plus dogfood runs against the repo's own example home
ledger with the observation date pinned for byte-identical rebuilds.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
REPO = PROJECT.parent
sys.path.insert(0, str(PROJECT))

import repair_ledger as rl  # noqa: E402

CLI = str(PROJECT / "repair_ledger.py")
HOME = PROJECT / "examples" / "home.json"
AS_OF = "2026-09-04"
AS_OF_D = date(2026, 9, 4)


def item(**over):
    base = dict(id="x", name="X", purchased="2020-01-01", price=1000,
                expected_life_years=8, repairs=[])
    base.update(over)
    return base


def repair(**over):
    base = dict(date="2023-01-01", symptom="symptom", cost=100,
                outcome="fixed", claimed_years=3.0)
    base.update(over)
    return base


class CliMixin:
    def run_cli(self, *argv):
        return subprocess.run([sys.executable, CLI] + list(argv),
                              capture_output=True, encoding="utf-8")

    def write_ledger(self, payload):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        self.addCleanup(os.unlink, path)
        return path


# ---------------------------------------------------------------------------
# 账本校验:坏数据必须 exit 2,不许带病计算
# ---------------------------------------------------------------------------

class LedgerValidationTestCase(CliMixin, unittest.TestCase):
    def test_missing_file_exit_2(self):
        proc = self.run_cli("report", "/nonexistent/ledger.json")
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("不存在", proc.stderr)

    def test_invalid_json_exit_2(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.addCleanup(os.unlink, path)
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("JSON", proc.stderr)

    def test_wrong_toplevel_type_exit_2(self):
        path = self.write_ledger({"nope": 1})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("items", proc.stderr)

    def test_missing_required_field_exit_2(self):
        path = self.write_ledger({"items": [{"id": "a", "name": "A"}]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("缺少字段", proc.stderr)

    def test_duplicate_id_exit_2(self):
        path = self.write_ledger({"items": [item(), item()]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("重复", proc.stderr)

    def test_negative_price_exit_2(self):
        path = self.write_ledger({"items": [item(price=-1)]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("price", proc.stderr)

    def test_bad_expected_life_exit_2(self):
        path = self.write_ledger({"items": [item(expected_life_years=0)]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("expected_life_years", proc.stderr)

    def test_bad_date_exit_2(self):
        path = self.write_ledger({"items": [item(purchased="2020-13-40")]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("日期不合法", proc.stderr)

    def test_repair_before_purchase_exit_2(self):
        path = self.write_ledger({"items": [
            item(purchased="2022-01-01", repairs=[repair(date="2021-06-01")])]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("乱序或早于购入", proc.stderr)

    def test_repairs_out_of_order_exit_2(self):
        path = self.write_ledger({"items": [item(repairs=[
            repair(date="2024-01-01"), repair(date="2023-01-01")])]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)

    def test_negative_cost_exit_2(self):
        path = self.write_ledger({"items": [item(repairs=[repair(cost=-5)])]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("cost", proc.stderr)

    def test_invalid_outcome_exit_2(self):
        path = self.write_ledger({"items": [item(repairs=[repair(outcome="maybe")])]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("outcome", proc.stderr)

    def test_nonpositive_claimed_years_exit_2(self):
        path = self.write_ledger({"items": [item(repairs=[repair(claimed_years=0)])]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("claimed_years", proc.stderr)

    def test_retired_before_last_repair_exit_2(self):
        path = self.write_ledger({"items": [item(
            repairs=[repair(date="2024-01-01")],
            retired={"date": "2023-06-01", "salvage": 0})]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("报废日", proc.stderr)

    def test_negative_salvage_exit_2(self):
        path = self.write_ledger({"items": [item(
            retired={"date": "2025-01-01", "salvage": -10})]})
        proc = self.run_cli("report", path)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("salvage", proc.stderr)

    def test_no_command_exit_2(self):
        proc = self.run_cli()
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)


# ---------------------------------------------------------------------------
# 计算核心:服务年数 / 沉没成本 / 续命轨迹
# ---------------------------------------------------------------------------

class CoreMathTestCase(unittest.TestCase):
    def test_service_years_active_runs_to_as_of(self):
        washing = item(purchased="2020-01-01")
        self.assertAlmostEqual(rl.service_years(washing, date(2022, 1, 1)), 2.0, places=2)

    def test_service_years_retired_frozen(self):
        gone = item(purchased="2020-01-01",
                    retired={"date": "2023-01-01", "salvage": 0})
        self.assertAlmostEqual(rl.service_years(gone, date(2030, 1, 1)), 3.0, places=2)

    def test_service_years_before_purchase_clamped_zero(self):
        baby = item(purchased="2020-01-01")
        self.assertEqual(rl.service_years(baby, date(2019, 1, 1)), 0.0)

    def test_sunk_cost_net_of_salvage(self):
        gone = item(price=1000, repairs=[repair(cost=100), repair(date="2024-01-01", cost=50)],
                    retired={"date": "2025-01-01", "salvage": 200})
        self.assertAlmostEqual(rl.sunk_cost(gone), 950.0)

    def test_trail_fixed_runs_to_next_repair(self):
        two = item(repairs=[repair(date="2023-01-01"),
                            repair(date="2024-01-01", symptom="again")])
        trail = rl.repair_trail(two, AS_OF_D)
        self.assertAlmostEqual(trail[0]["actual"], 365 / 365.25, places=3)
        self.assertTrue(trail[0]["completed"])

    def test_trail_fixed_runs_to_retirement(self):
        gone = item(repairs=[repair(date="2023-01-01")],
                    retired={"date": "2024-06-01", "salvage": 0})
        trail = rl.repair_trail(gone, AS_OF_D)
        self.assertAlmostEqual(trail[0]["actual"], 517 / 365.25, places=3)
        self.assertTrue(trail[0]["completed"])

    def test_trail_censored_when_no_next_event(self):
        fresh = item(repairs=[repair(date="2025-01-01")])
        trail = rl.repair_trail(fresh, AS_OF_D)
        self.assertFalse(trail[0]["completed"])
        self.assertGreater(trail[0]["actual"], 1.6)

    def test_trail_failed_costs_money_adds_zero_life(self):
        bad = item(repairs=[repair(date="2024-01-01", outcome="failed")])
        trail = rl.repair_trail(bad, AS_OF_D)
        self.assertTrue(trail[0]["completed"])
        self.assertEqual(trail[0]["actual"], 0.0)
        self.assertEqual(trail[0]["cost"], 100.0)

    def test_pie_factor_empty_ledger_defaults_to_one(self):
        factor, samples = rl.pie_factor([item()], AS_OF_D)
        self.assertEqual(factor, 1.0)
        self.assertEqual(samples, 0)

    def test_pie_factor_median_of_ratios(self):
        # 0.5 与 0.75 → 中位 0.625;删失样本不进中位数
        two = item(repairs=[
            repair(date="2021-01-01", claimed_years=4.0),   # → 2023-01-01, actual 2y, ratio 0.5
            repair(date="2023-01-01", claimed_years=4.0),   # → retired, actual 3y, ratio 0.75
        ], retired={"date": "2026-01-01", "salvage": 0})
        solo = item(id="y", repairs=[repair(date="2025-01-01")])  # 删失
        factor, samples = rl.pie_factor([two, solo], AS_OF_D)
        self.assertAlmostEqual(factor, 0.625, places=3)
        self.assertEqual(samples, 2)

    def test_pie_factor_not_clamped_above_one(self):
        honest = [item(repairs=[repair(date="2021-01-01", claimed_years=1.0)],
                       retired={"date": "2025-01-01", "salvage": 0})]
        # actual 4 年 / claimed 1 年 → ratio 4.0:师傅保守不被惩罚性压回 1.0,
        # 后续裁决会因此更倾向修 —— 保守是一种可积累的信用
        factor, samples = rl.pie_factor(honest, date(2025, 6, 1))
        self.assertAlmostEqual(factor, 4.0, places=3)
        self.assertEqual(samples, 1)

    def test_diminishing_detected(self):
        fading = item(repairs=[
            repair(date="2020-01-01", claimed_years=4.0),
            repair(date="2022-01-01", claimed_years=4.0),   # actual 2.0y
            repair(date="2023-01-01", claimed_years=3.0),   # actual 0.5y
        ], retired={"date": "2023-07-01", "salvage": 0})
        actuals, diminishing = rl.diminishing_trail(fading, AS_OF_D)
        self.assertEqual(len(actuals), 3)
        self.assertTrue(diminishing)

    def test_diminishing_not_flagged_when_flat_or_single(self):
        steady = item(repairs=[
            repair(date="2020-01-01", claimed_years=4.0),
            repair(date="2023-01-01", claimed_years=4.0),   # actual 3y
            repair(date="2026-01-01", claimed_years=4.0),   # actual 3y
        ])
        _, diminishing = rl.diminishing_trail(steady, AS_OF_D)
        self.assertFalse(diminishing)
        solo = item(repairs=[repair()])
        _, diminishing = rl.diminishing_trail(solo, AS_OF_D)
        self.assertFalse(diminishing)

    def test_diminishing_ignores_failed_entries(self):
        mixed = item(repairs=[
            repair(date="2022-01-01", claimed_years=3.0),
            repair(date="2024-01-01", claimed_years=3.0),   # actual 2y
            repair(date="2025-01-01", outcome="failed"),
        ])
        actuals, _ = rl.diminishing_trail(mixed, AS_OF_D)
        self.assertEqual(len(actuals), 2)


# ---------------------------------------------------------------------------
# 裁决:FIX / REPLACE / SCRAP 与门槛参数
# ---------------------------------------------------------------------------

class JudgeTestCase(unittest.TestCase):
    def ledger(self, **over):
        base = item(id="washer", name="Washer", purchased="2016-08-01",
                    price=3200, expected_life_years=10, **over)
        return [base]

    def judge(self, items, quote, claimed, new_price, new_life, **kw):
        return rl.judge(items, items[0], quote, claimed, new_price, new_life,
                        AS_OF_D, **kw)

    def test_fix_when_marginal_cheaper_than_new(self):
        # 报价 240 买 2 年 = 120/年;新机 3600/12 = 300/年 → FIX
        result = self.judge(self.ledger(), 240, 2.0, 3600, 12.0)
        self.assertEqual(result["verdict"], "FIX")
        self.assertEqual(result["exit_code"], rl.EXIT_FIX)

    def test_replace_when_marginal_loses(self):
        # 报价 900 买 1 年 = 900/年;新机 300/年 → REPLACE
        result = self.judge(self.ledger(), 900, 1.0, 3600, 12.0)
        self.assertEqual(result["verdict"], "REPLACE")
        self.assertEqual(result["exit_code"], rl.EXIT_REPLACE)

    def test_scrap_when_repairs_reach_price(self):
        heavy = self.ledger(repairs=[repair(date="2024-01-01", cost=2000)])
        # (2000 + 1200) / 3200 = 1.0 ≥ 1.0 且边际不占优 → SCRAP
        result = self.judge(heavy, 1200, 1.0, 3000, 10.0)
        self.assertEqual(result["verdict"], "SCRAP")
        self.assertEqual(result["exit_code"], rl.EXIT_SCRAP)

    def test_scrap_not_triggered_when_marginal_wins(self):
        heavy = self.ledger(repairs=[repair(date="2024-01-01", cost=2000)])
        # 维修占比超线,但边际大占优(10/年 vs 300/年)→ 仍然 FIX
        result = self.judge(heavy, 50, 5.0, 3000, 10.0)
        self.assertEqual(result["verdict"], "FIX")

    def test_pie_factor_discounts_claimed_years(self):
        # 构造画饼 0.625:宣称 4 实际 2(ratio 0.5)+ 宣称 4 实际 3(ratio 0.75)
        strict = [item(id="mentor", repairs=[
            repair(date="2021-01-01", claimed_years=4.0),
            repair(date="2023-01-01", claimed_years=4.0),
        ], retired={"date": "2026-01-01", "salvage": 0})]
        result = self.judge(strict, 480, 4.0, 5200, 14.0)
        self.assertAlmostEqual(result["pie_factor"], 0.625, places=3)
        self.assertAlmostEqual(result["credited_years"], 2.5, places=3)
        self.assertAlmostEqual(result["marginal_fix"], 192.0, places=1)
        self.assertEqual(result["verdict"], "FIX")

    def test_zero_pie_factor_pushes_to_replace(self):
        # 全部 failed → 画饼 0 → 诚实续命 0 → 边际无穷 → REPLACE
        cursed = [item(id="cursed", repairs=[
            repair(date="2024-01-01", outcome="failed"),
            repair(date="2025-01-01", outcome="failed"),
        ])]
        result = self.judge(cursed, 300, 3.0, 3000, 10.0)
        self.assertEqual(result["pie_factor"], 0.0)
        self.assertEqual(result["verdict"], "REPLACE")

    def test_tolerance_lets_marginal_premium_pass(self):
        # 450/年 vs 300/年 = 1.5;默认容忍 1.0 → REPLACE;放宽到 2.0 → FIX
        self.assertEqual(self.judge(self.ledger(), 450, 1.0, 3600, 12.0,
                                    tolerance=1.0)["verdict"], "REPLACE")
        self.assertEqual(self.judge(self.ledger(), 450, 1.0, 3600, 12.0,
                                    tolerance=2.0)["verdict"], "FIX")

    def test_scrap_ratio_threshold_configurable(self):
        heavy = self.ledger(repairs=[repair(date="2024-01-01", cost=2000)])
        # 占比 1.0:阈值 1.0 → SCRAP;阈值 1.5 → REPLACE
        scrap = self.judge(heavy, 1200, 1.0, 3000, 10.0, scrap_ratio=1.0)
        self.assertEqual(scrap["verdict"], "SCRAP")
        mild = self.judge(heavy, 1200, 1.0, 3000, 10.0, scrap_ratio=1.5)
        self.assertEqual(mild["verdict"], "REPLACE")

    def test_free_gift_has_no_repair_ratio(self):
        gift = [item(price=0, repairs=[repair(cost=999)])]
        # 赠品没有购价,维修占比无从谈起 → SCRAP 门槛不适用,只按边际裁决:
        # 3000 买 1 年 vs 新机 300/年 → REPLACE(而非 SCRAP)
        result = self.judge(gift, 3000, 1.0, 3000, 10.0)
        self.assertIsNone(result["repair_ratio"])
        self.assertEqual(result["verdict"], "REPLACE")


# ---------------------------------------------------------------------------
# CLI:report / show / history 的输出契约
# ---------------------------------------------------------------------------

class ReportCliTestCase(CliMixin, unittest.TestCase):
    def test_text_report_lists_every_item(self):
        proc = self.run_cli("report", str(HOME), "--as-of", AS_OF)
        self.assertEqual(proc.returncode, 0)
        for token in ("washer", "fridge", "laptop", "heater", "microwave",
                      "画饼系数", "▼递减", "已结案", "服役中"):
            self.assertIn(token, proc.stdout)

    def test_json_report_fields_and_cpy_ranking(self):
        proc = self.run_cli("report", str(HOME), "--as-of", AS_OF, "--format", "json")
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["as_of"], AS_OF)
        self.assertEqual(payload["pie_samples"], 9)
        self.assertAlmostEqual(payload["pie_factor"], 0.487, places=2)
        ids = [row["id"] for row in payload["items"]]
        self.assertEqual(ids[0], "laptop")  # 每服务年最高者排第一
        cpys = [row["cost_per_year"] for row in payload["items"]]
        self.assertEqual(cpys, sorted(cpys, reverse=True))

    def test_json_report_value_contracts(self):
        proc = self.run_cli("report", str(HOME), "--as-of", AS_OF, "--format", "json")
        rows = {row["id"]: row for row in json.loads(proc.stdout)["items"]}
        self.assertAlmostEqual(rows["laptop"]["service_years"], 6.82, places=1)
        self.assertAlmostEqual(rows["laptop"]["sunk"], 10400.0)
        self.assertAlmostEqual(rows["heater"]["cost_per_year"], 375.1, places=0)
        self.assertAlmostEqual(rows["microwave"]["repair_to_price"], 0.7143, places=3)
        self.assertTrue(rows["washer"]["diminishing"])
        self.assertFalse(rows["microwave"]["diminishing"])
        self.assertEqual(rows["fridge"]["status"], "active")

    def test_pinned_date_rebuilds_byte_identical(self):
        first = self.run_cli("report", str(HOME), "--as-of", AS_OF)
        second = self.run_cli("report", str(HOME), "--as-of", AS_OF)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.returncode, second.returncode)

    def test_empty_ledger_reports_zero_items(self):
        path = self.write_ledger({"items": []})
        proc = self.run_cli("report", path, "--as-of", AS_OF, "--format", "json")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["items"], [])

    def test_zero_service_years_shows_dash_not_crash(self):
        path = self.write_ledger({"items": [item(purchased=AS_OF)]})
        proc = self.run_cli("report", path, "--as-of", AS_OF, "--format", "json")
        self.assertEqual(proc.returncode, 0)
        self.assertIsNone(json.loads(proc.stdout)["items"][0]["cost_per_year"])


class ShowHistoryCliTestCase(CliMixin, unittest.TestCase):
    def test_show_lists_claimed_vs_actual_per_repair(self):
        proc = self.run_cli("show", str(HOME), "heater", "--as-of", AS_OF)
        self.assertEqual(proc.returncode, 0)
        for token in ("宣称续命", "实际续命", "兑现率", "51%", "40%", "49%",
                      "▼ 续命递减", "每服务年 ¥375"):
            self.assertIn(token, proc.stdout)

    def test_show_accepts_exact_name(self):
        proc = self.run_cli("show", str(HOME), "洗衣机", "--as-of", AS_OF)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("服役中", proc.stdout)

    def test_show_unknown_item_exit_2(self):
        proc = self.run_cli("show", str(HOME), "teleporter", "--as-of", AS_OF)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("没有物品", proc.stderr)

    def test_history_shows_global_pie_and_failed_zero(self):
        proc = self.run_cli("history", str(HOME), "--as-of", AS_OF)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("全局画饼系数 0.49", proc.stdout)
        self.assertIn("0%", proc.stdout)        # 磁控管那笔 failed
        self.assertIn("删失", proc.stdout)       # 还没坏的如实标注
        self.assertIn("没修好", proc.stdout)

    def test_history_empty_ledger(self):
        path = self.write_ledger({"items": [item()]})
        proc = self.run_cli("history", path, "--as-of", AS_OF)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("还没有维修记录", proc.stdout)

    def test_history_pinned_date_rebuilds_identical(self):
        first = self.run_cli("history", str(HOME), "--as-of", AS_OF)
        second = self.run_cli("history", str(HOME), "--as-of", AS_OF)
        self.assertEqual(first.stdout, second.stdout)


# ---------------------------------------------------------------------------
# CLI:verdict 的裁决、exit code 与护栏
# ---------------------------------------------------------------------------

class VerdictCliTestCase(CliMixin, unittest.TestCase):
    WASHER = ("verdict", str(HOME), "washer", "--quote", "700",
              "--claimed-years", "3", "--new-price", "3500", "--new-life", "12",
              "--as-of", AS_OF)
    FRIDGE = ("verdict", str(HOME), "fridge", "--quote", "480",
              "--claimed-years", "4", "--new-price", "5200", "--new-life", "14",
              "--as-of", AS_OF)
    MICROWAVE = ("verdict", str(HOME), "microwave", "--quote", "350",
                 "--claimed-years", "2", "--new-price", "800", "--new-life", "8",
                 "--as-of", AS_OF)

    def test_fridge_fix_exit_0(self):
        proc = self.run_cli(*self.FRIDGE)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("修 FIX", proc.stdout)
        self.assertIn("¥246/服务年", proc.stdout)
        self.assertIn("比值 0.66", proc.stdout)

    def test_washer_replace_exit_3_with_diminishing_note(self):
        proc = self.run_cli(*self.WASHER)
        self.assertEqual(proc.returncode, rl.EXIT_REPLACE)
        self.assertIn("换新 REPLACE", proc.stdout)
        self.assertIn("续命递减警示", proc.stdout)
        self.assertIn("购价的 62%", proc.stdout)

    def test_microwave_scrap_exit_4(self):
        proc = self.run_cli(*self.MICROWAVE)
        self.assertEqual(proc.returncode, rl.EXIT_SCRAP)
        self.assertIn("报废 SCRAP", proc.stdout)
        self.assertIn("121%", proc.stdout)

    def test_verdict_json_contract(self):
        proc = self.run_cli(*self.WASHER, "--format", "json")
        self.assertEqual(proc.returncode, rl.EXIT_REPLACE)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["verdict"], "REPLACE")
        self.assertAlmostEqual(payload["pie_factor"], 0.487, places=2)
        self.assertAlmostEqual(payload["credited_years"], 1.46, places=1)
        self.assertAlmostEqual(payload["ratio"], 1.64, places=1)

    def test_tolerance_widening_flips_washer_to_fix(self):
        proc = self.run_cli(*self.WASHER, "--tolerance", "2.0")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("修 FIX", proc.stdout)

    def test_scrap_ratio_loosening_downgrades_to_replace(self):
        proc = self.run_cli(*self.MICROWAVE, "--scrap-ratio", "2.0")
        self.assertEqual(proc.returncode, rl.EXIT_REPLACE)
        self.assertIn("换新 REPLACE", proc.stdout)

    def test_retired_item_refused_exit_2(self):
        proc = self.run_cli("verdict", str(HOME), "laptop", "--quote", "100",
                            "--claimed-years", "2", "--new-price", "5000",
                            "--new-life", "5", "--as-of", AS_OF)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("结案", proc.stderr)

    def test_unknown_item_exit_2(self):
        proc = self.run_cli("verdict", str(HOME), "spaceship", "--quote", "100",
                            "--claimed-years", "2", "--new-price", "5000",
                            "--new-life", "5", "--as-of", AS_OF)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)

    def test_nonpositive_quote_exit_2(self):
        proc = self.run_cli("verdict", str(HOME), "washer", "--quote", "0",
                            "--claimed-years", "2", "--new-price", "5000",
                            "--new-life", "5", "--as-of", AS_OF)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("--quote", proc.stderr)

    def test_nonpositive_claimed_years_exit_2(self):
        proc = self.run_cli("verdict", str(HOME), "washer", "--quote", "100",
                            "--claimed-years", "0", "--new-price", "5000",
                            "--new-life", "5", "--as-of", AS_OF)
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("--claimed-years", proc.stderr)

    def test_bad_as_of_exit_2(self):
        proc = self.run_cli("report", str(HOME), "--as-of", "2026-02-30")
        self.assertEqual(proc.returncode, rl.EXIT_ERROR)
        self.assertIn("--as-of", proc.stderr)


# ---------------------------------------------------------------------------
# Dogfood:样例账本的三条裁决故事,数值全部可复算
# ---------------------------------------------------------------------------

class DogfoodTestCase(CliMixin, unittest.TestCase):
    """examples/home.json 是一份完整叙事:同一画饼系数 0.49 下,
    冰箱值得修、洗衣机该换新、微波炉该报废——三条路由账本分岔。"""

    def test_three_verdicts_diverge_on_one_pie_factor(self):
        cases = {
            "fridge": (480, 4, 5200, 14, 0),
            "washer": (700, 3, 3500, 12, rl.EXIT_REPLACE),
            "microwave": (350, 2, 800, 8, rl.EXIT_SCRAP),
        }
        for target, (quote, claimed, new_price, new_life, expected) in cases.items():
            proc = self.run_cli("verdict", str(HOME), target,
                                "--quote", str(quote), "--claimed-years", str(claimed),
                                "--new-price", str(new_price), "--new-life", str(new_life),
                                "--as-of", AS_OF)
            self.assertEqual(proc.returncode, expected, target)
            self.assertIn("画饼系数 0.49", proc.stdout, target)

    def test_home_ledger_math_is_self_consistent(self):
        """沉没 = 购价 + 维修 − 回收;每服务年 = 沉没 / 服役年数(逐件核对).

        JSON 报告里三者都已四舍五入到分位,重算允许 ±1 的舍入差。
        """
        proc = self.run_cli("report", str(HOME), "--as-of", AS_OF, "--format", "json")
        rows = {row["id"]: row for row in json.loads(proc.stdout)["items"]}
        for row in rows.values():
            with self.subTest(item=row["id"]):
                self.assertAlmostEqual(
                    row["cost_per_year"],
                    row["sunk"] / row["service_years"], delta=1.0)

    def test_washer_actuals_shrink_across_repairs(self):
        """续命递减的原始证据:1.7 → 0.8,下一笔还在删失观察中."""
        proc = self.run_cli("show", str(HOME), "washer", "--as-of", AS_OF)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("55%", proc.stdout)
        self.assertIn("26%", proc.stdout)
        self.assertIn("≥1.0", proc.stdout)
        self.assertIn("▼ 续命递减", proc.stdout)

    def test_example_ledger_itself_passes_validation(self):
        data = rl.load_ledger(str(HOME))
        self.assertEqual(len(data["items"]), 5)


if __name__ == "__main__":
    unittest.main()
