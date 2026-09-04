# -*- coding: utf-8 -*-
"""超役 · Past Prime 验收测试。

判级边界（730/365/0 天）、到站日日历口径（2/29 落 2/28）、先验三源覆盖
（gb17905 / assoc2020 / folk / --life / --priors / 行内 life_years）、
池构成与月摊 fen 级恒等、退休潮 730 天聚簇划分、突击回放、双算法、
exit code 行为真值与 as-of 确定性全部钉死。

Exit codes: 0 绿 · 2 账本/参数损坏 · 3 样本太薄 · 4 超役红灯。
"""

import datetime as dt
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
IDEA = os.path.dirname(HERE)
CLI = os.path.join(IDEA, "past_prime.py")
EXAMPLES = os.path.join(IDEA, "examples", "fleet.tsv")

_spec = importlib.util.spec_from_file_location("past_prime", CLI)
pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pp)


def go(*args):
    """跑 CLI 子进程，返回 (stdout, stderr, exit_code)。"""
    r = subprocess.run([sys.executable, CLI] + list(args),
                       capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode


def write_ledger(rows, tmpdir, name="fleet.tsv"):
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("item\tcategory\tbuy_date\tprice\treplace_cost\tretired_date"
                "\tkwh_month\tlife_years\tnote\n")
        for r in rows:
            cells = [r.get(c, "") for c in ("item", "category", "buy_date",
                                            "price", "replace_cost",
                                            "retired_date", "kwh_month",
                                            "life_years", "note")]
            f.write("\t".join(str(c) for c in cells) + "\n")
    return path


def load_example():
    return pp.load_ledger(EXAMPLES, dt.date(2026, 9, 5), {}, [], {}, None)


class TestPrimitives(unittest.TestCase):
    def test_tier_boundaries_days(self):
        # OK 严格大于 730；WATCH (365,730]；DUE-SOON (0,365]；OVERDUE ≤0
        self.assertEqual(pp.tier_of(731), "OK")
        self.assertEqual(pp.tier_of(730), "WATCH")
        self.assertEqual(pp.tier_of(366), "WATCH")
        self.assertEqual(pp.tier_of(365), "DUE-SOON")
        self.assertEqual(pp.tier_of(1), "DUE-SOON")
        self.assertEqual(pp.tier_of(0), "OVERDUE")
        self.assertEqual(pp.tier_of(-1), "OVERDUE")

    def test_add_years_calendar_semantics(self):
        # 判废年限是日历口径：8 年就是第 8 个周年，不是 2922 天的近似
        self.assertEqual(pp.add_years(dt.date(2017, 6, 10), 8),
                         dt.date(2025, 6, 10))
        # 2/29 购入，平年落 2/28
        self.assertEqual(pp.add_years(dt.date(2024, 2, 29), 1),
                         dt.date(2025, 2, 28))

    def test_remaining_days_dual_algorithms(self):
        for _ in range(50):
            a = dt.date(2015, 1, 1) + dt.timedelta(days=hash(_) % 4000)
            b = a + dt.timedelta(days=hash(_ * 7) % 3000)
            self.assertEqual(pp.remaining_days(b, a),
                             pp.remaining_days_alt(b, a))

    def test_alias_normalization(self):
        for alias in ("燃气热水器", "gas_water_heater", "Gas Water Heater",
                      "燃气式热水器"):
            self.assertEqual(pp.canon_category(alias), "燃气热水器")
        self.assertEqual(pp.canon_category("gas stove"), "燃气灶")
        # 先验表外原样通过（NEVER-PRIOR 点名，不猜）
        self.assertEqual(pp.canon_category("空气炸锅"), "空气炸锅")

    def test_money(self):
        self.assertEqual(pp.money(26800), "¥26,800")
        self.assertEqual(pp.money(1162.5), "¥1,162.50")
        self.assertEqual(pp.money(0), "¥0")

    def test_monthly_split_fen_exact(self):
        # 分级最大余数法：Σ逐月 == 总额，一分不差
        for total in (13950.0, 100.01, 0.03, 7.0, 99999.99):
            months = pp.monthly_split(total, 12)
            self.assertEqual(sum(months), int(round(total * 100)))
            self.assertLessEqual(max(months) - min(months), 1)


class TestExampleFleet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (cls.active, cls.retired, cls.never_dated, cls.never_prior,
         cls.max_date, _priors) = load_example()

    def by_name(self, name):
        return {a["name"]: a for a in self.active}[name]

    def test_load_counts(self):
        self.assertEqual(len(self.active), 14)
        self.assertEqual(len(self.retired), 3)
        self.assertEqual(len(self.never_dated), 1)
        self.assertEqual(len(self.never_prior), 0)
        self.assertEqual(self.max_date, dt.date(2026, 1, 15))

    def test_tier_counts(self):
        cnt = {t: 0 for t in pp.TIER_ORDER}
        for a in self.active:
            cnt[a["tier"]] += 1
        self.assertEqual((cnt["OVERDUE"], cnt["DUE-SOON"], cnt["WATCH"],
                          cnt["OK"]), (4, 3, 5, 2))

    def test_pinned_remaining_days(self):
        # 示例账本的判级全部钉死（as-of 2026-09-05）
        pinned = {
            "厨房燃气热水器": -452, "厨房燃气灶": -452, "吸油烟机": -447,
            "滚筒洗衣机": -430, "电热毯": 61, "厨下净水机": 220,
            "对开门电冰箱": 318, "客厅电视": 432, "电饭煲": 560,
            "主卧挂机": 664, "客厅挂机": 664, "扫地机器人": 715,
            "卧室加湿器": 1593, "微波炉": 1718,
        }
        for name, rem in pinned.items():
            self.assertEqual(self.by_name(name)["rem"], rem, name)

    def test_source_labels(self):
        self.assertEqual(self.by_name("厨房燃气热水器")["source"], "gb17905")
        self.assertEqual(self.by_name("对开门电冰箱")["source"], "assoc2020")
        self.assertEqual(self.by_name("微波炉")["source"], "folk")

    def test_safe_classification(self):
        safe_over = {a["name"] for a in self.active
                     if a["tier"] == "OVERDUE" and a["safe"]}
        self.assertEqual(safe_over, {"厨房燃气热水器", "厨房燃气灶"})
        # 电热毯：贴身电加热，DUE-SOON 也在涉险名单上
        self.assertTrue(self.by_name("电热毯")["safe"])
        self.assertFalse(self.by_name("对开门电冰箱")["safe"])

    def test_cost_explicit_wins_and_assumed_marked(self):
        self.assertEqual(self.by_name("厨房燃气热水器")["cost"], 2500.0)
        self.assertFalse(self.by_name("厨房燃气热水器")["cost_assumed"])
        # 没抄换新价的台用先验中位垫底，并标 assumed
        self.assertEqual(self.by_name("微波炉")["cost"], 500.0)
        self.assertTrue(self.by_name("微波炉")["cost_assumed"])
        self.assertEqual(self.by_name("电热毯")["cost"], 250.0)
        self.assertTrue(self.by_name("电热毯")["cost_assumed"])

    def test_waves_partition_and_pinned(self):
        ws = pp.waves(self.active)
        self.assertEqual([len(w) for w in ws], [6, 6, 2])
        self.assertEqual((ws[0][0]["due"], ws[0][-1]["due"]),
                         (dt.date(2025, 6, 10), dt.date(2027, 4, 13)))
        covered = sum(len(w) for w in ws)
        self.assertEqual(covered, 14)          # 本例无单飞：3 潮覆盖全部

    def test_fund_pool_composition(self):
        pool, fast, total = pp.fund_pool(self.active)
        self.assertEqual(len(pool), 7)
        self.assertEqual(len(fast), 4)
        self.assertEqual(total, 13950.0)

    def test_burst_year_2017(self):
        b = pp.burst_year(self.retired)
        self.assertIsNotNone(b)
        self.assertEqual(b["year"], 2017)
        self.assertAlmostEqual(b["amount"], 7898.0, places=2)
        self.assertAlmostEqual(b["share"], 7898.0 / 8498.0, places=9)

    def test_burst_needs_two_years(self):
        # 只有一年有退役支出：单年就是全史，谈不上「突击」
        rows = [dict(item="旧A", category="洗衣机", buy_date="2000-01-01",
                     retired_date="2010-01-01", replace_cost="1000")]
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger(rows, d)
            st = pp.load_ledger(p, dt.date(2026, 9, 5), {}, [], {}, None)
            self.assertIsNone(pp.burst_year(st[1]))

    def test_retired_service_years(self):
        svcs = sorted(round((r["retd"] - r["buy"]).days / 365.25, 1)
                      for r in self.retired)
        self.assertEqual(svcs, [8.3, 10.0, 10.9])
        self.assertAlmostEqual(pp.median(svcs), 10.0, places=9)

    def test_monotonic_tier_under_time(self):
        # 时间只往前走，判级永不回绿
        nxt = dt.date(2026, 9, 6)
        for a in self.active:
            t0 = pp.TIER_ORDER[a["tier"]]
            t1 = pp.TIER_ORDER[pp.tier_of(pp.remaining_days(a["due"], nxt))]
            self.assertGreaterEqual(t1, t0, a["name"])

    def test_never_dated_safe_hint(self):
        nd = self.never_dated[0]
        self.assertEqual(nd["name"], "父母房电热水器")
        self.assertTrue(nd["safe"])


class TestOverrides(unittest.TestCase):
    def test_life_override_flag(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="电热水器",
                                   buy_date="2015-01-01")], d)
            st = pp.load_ledger(p, dt.date(2026, 9, 5), {"电热水器": 12},
                                [], {}, None)
            a = st[0][0]
            self.assertEqual(a["life"], 12)
            self.assertEqual(a["source"], "user")
            self.assertEqual(a["due"], dt.date(2027, 1, 1))

    def test_row_life_wins_over_everything(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="电热水器",
                                   buy_date="2015-01-01",
                                   life_years="15")], d)
            st = pp.load_ledger(p, dt.date(2026, 9, 5), {"电热水器": 12},
                                [], {}, None)
            self.assertEqual(st[0][0]["life"], 15)
            self.assertEqual(st[0][0]["source"], "manual")

    def test_price_override_flips_assumed(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="微波炉",
                                   buy_date="2021-05-20")], d)
            st = pp.load_ledger(p, dt.date(2026, 9, 5), {}, [],
                                {"微波炉": 666}, None)
            a = st[0][0]
            self.assertEqual(a["cost"], 666.0)
            self.assertFalse(a["cost_assumed"])

    def test_safe_extra_flag(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="空气炸锅",
                                   buy_date="2020-01-01",
                                   life_years="5")], d)
            st = pp.load_ledger(p, dt.date(2026, 9, 5), {}, ["空气炸锅"],
                                {}, None)
            self.assertTrue(st[0][0]["safe"])

    def test_priors_file_override(self):
        with tempfile.TemporaryDirectory() as d:
            pf = os.path.join(d, "priors.tsv")
            with open(pf, "w", encoding="utf-8") as f:
                f.write("category\tlife_years\treplace_cost\tnew_kwh_month"
                        "\tsafe\n")
                f.write("空气炸锅\t4\t299\t\t\n")
            p = write_ledger([dict(item="A", category="空气炸锅",
                                   buy_date="2020-01-01")], d)
            st = pp.load_ledger(p, dt.date(2026, 9, 5), {}, [], {}, pf)
            a = st[0][0]
            self.assertEqual(a["life"], 4)
            self.assertEqual(a["cost"], 299.0)

    def test_unknown_category_is_never_prior(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="空气炸锅",
                                   buy_date="2020-01-01")], d)
            st = pp.load_ledger(p, dt.date(2026, 9, 5), {}, [], {}, None)
            self.assertEqual(len(st[0]), 0)        # 不进判级
            self.assertEqual(len(st[3]), 1)        # NEVER-PRIOR 点名


class TestWavesSynthetic(unittest.TestCase):
    def _waves_for(self, buys):
        rows = [dict(item="T%d" % i, category="微波炉", buy_date=b)
                for i, b in enumerate(buys)]
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger(rows, d)
            st = pp.load_ledger(p, dt.date(2030, 1, 1), {}, [], {}, None)
            return pp.waves(st[0])

    def test_730_days_joins_731_splits(self):
        # 恰 730 天：同一波
        ws = self._waves_for(["2020-01-01", "2022-01-01"])
        self.assertEqual([len(w) for w in ws], [2])
        # 731 天：裂开成两个单飞（waves 只返回 ≥2 台的潮，单飞由划分计数）
        ws = self._waves_for(["2020-01-01", "2022-01-02"])
        self.assertEqual(ws, [])
        # 三台里前两台 730 天内、第三台 731 天：贪心聚簇 [2] + 1 单飞
        ws = self._waves_for(["2020-01-01", "2022-01-01", "2022-01-02",
                              "2026-01-01"])
        self.assertEqual([len(w) for w in ws], [2])


class TestCliExample(unittest.TestCase):
    def test_report_exit4_and_key_lines(self):
        out, err, code = go("report", EXAMPLES, "--as-of", "2026-09-05")
        self.assertEqual(code, 4, err)
        for s in ("OVERDUE-SAFE ×2", "超役 452 天（判废 8 年·gb17905）",
                  "合计 14 台：OVERDUE 4 · DUE-SOON 3 · WATCH 5 · OK 2",
                  "潮① 2025-06-10 ~ 2027-04-13（672 天）6 台到站，其中涉险 3 台",
                  "潮② 2027-07-20 ~ 2028-08-20（397 天）6 台到站",
                  "潮③ 2031-01-15 ~ 2031-05-20（125 天）2 台到站",
                  "2017 批次 5 台：4 台已超役、1 台 DUE-SOON",
                  "个人节奏：中位服役 10.0 年",
                  "突击回放：2017 年退役支出 ¥7,898（2 台），占全史 92.9%",
                  "NEVER-DATED（1 台）", "涉险品类，优先考古这张",
                  "exit 4：超役 4 台（涉险 2）",
                  "换与不换是人的决定"):
            self.assertIn(s, out, s)

    def test_report_default_asof_is_ledger_max(self):
        out, _, code = go("report", EXAMPLES)
        self.assertEqual(code, 4)
        self.assertIn("as-of: 2026-01-15（缺省=账本最大日期", out)
        self.assertIn("超役 219 天（判废 8 年·gb17905）", out)

    def test_explicit_asof_same_day_annotated(self):
        out, _, _ = go("report", EXAMPLES, "--as-of", "2026-01-15")
        self.assertIn("as-of: 2026-01-15（--as-of 显式钉死）", out)

    def test_determinism_byte_identical(self):
        a = go("report", EXAMPLES, "--as-of", "2026-09-05")
        b = go("report", EXAMPLES, "--as-of", "2026-09-05")
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[2], b[2])

    def test_report_prints_basename_only(self):
        out, _, _ = go("report", EXAMPLES, "--as-of", "2026-09-05")
        self.assertIn("账本: fleet.tsv", out)
        self.assertNotIn(IDEA, out)
        self.assertNotIn(os.sep + "examples", out)

    def test_queue_conservation(self):
        out, _, code = go("queue", EXAMPLES, "--as-of", "2026-09-05")
        self.assertEqual(code, 0)
        self.assertIn("立即预算 ¥7,900", out)
        self.assertIn("2027: 厨下净水机 ¥2,200 · 对开门电冰箱 ¥3,600 · "
                      "客厅电视 ¥3,500   年预算 ¥9,300", out)
        self.assertIn("2028: 电饭煲 ¥350 · 主卧挂机 ¥3,200 · "
                      "客厅挂机 ¥3,200 · 扫地机器人 ¥1,800   年预算 ¥8,550", out)
        self.assertIn("horizon 合计 ¥26,800（14 台）", out)
        self.assertIn("全池 ¥26,800 == 全部在役换新参考之和（守恒）", out)

    def test_fund_pool_and_monthly(self):
        out, _, code = go("fund", EXAMPLES, "--as-of", "2026-09-05")
        self.assertEqual(code, 0)
        self.assertIn("未来 12 个月池 ¥13,950（7 台，其中超役快速入池 4 台）",
                      out)
        self.assertIn("每月存 ¥1,162.50", out)
        self.assertIn("快速通道（超役台不等你攒，先入池 ¥7,900）", out)
        self.assertIn("电热毯 ¥250* 2026-11-05（61 天后到站）", out)

    def test_simulate_replace_all_conservation(self):
        out, _, code = go("simulate", EXAMPLES, "replace-all",
                          "--as-of", "2026-09-05")
        self.assertEqual(code, 0)
        self.assertIn("A. 今天全换：14 台一次性 ¥26,800", out)
        self.assertIn("守恒：A == B == 全池 ¥26,800", out)
        self.assertIn("12 个月内相继到站", out)

    def test_simulate_keep_future_state(self):
        out, _, code = go("simulate", EXAMPLES, "keep", "厨房燃气热水器",
                          "--years", "3", "--as-of", "2026-09-05")
        self.assertEqual(code, 0)
        self.assertIn("到 2029-09-05，这台已 12.2 岁", out)
        self.assertIn("判级 OVERDUE", out)
        self.assertIn("推迟不是豁免", out)

    def test_simulate_keep_unknown_item_exit2(self):
        _, err, code = go("simulate", EXAMPLES, "keep", "不存在",
                          "--as-of", "2026-09-05")
        self.assertEqual(code, 2)
        self.assertIn("ledger error", err)

    def test_energy_computed(self):
        out, _, code = go("energy", EXAMPLES, "--as-of", "2026-09-05")
        self.assertEqual(code, 0)
        self.assertIn("对开门电冰箱（9 年机）52 kWh/月 → ¥28.60/月", out)
        self.assertIn("多付 ¥15.40/月 · 年化 ¥184.80", out)
        self.assertIn("年化 ¥184.80（五年 ¥924）", out)

    def test_energy_decline_without_kwh(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="微波炉",
                                   buy_date="2021-01-01")], d)
            out, _, code = go("energy", p)
            self.assertEqual(code, 0)
            self.assertIn("DECLINE", out)
            self.assertIn("不发明你的用电量", out)

    def test_validate_ok_on_example(self):
        out, _, code = go("validate", EXAMPLES, "--as-of", "2026-09-05")
        self.assertEqual(code, 0)
        self.assertIn("validate: OK", out)
        self.assertIn("Σ四档 = 在役 14", out)
        self.assertIn("池构成双算法一致（7 台 ¥13,950）", out)
        self.assertIn("判级单调（as-of+1 天不回绿）✓", out)
        self.assertIn("退休潮聚簇构成划分（3 潮 + 0 单飞 = 14 台）✓", out)

    def test_other_commands_exit0_on_example(self):
        for cmd in ("queue", "fund", "energy", "validate"):
            _, err, code = go(cmd, EXAMPLES, "--as-of", "2026-09-05")
            self.assertEqual(code, 0, (cmd, err))


class TestCliEdge(unittest.TestCase):
    def test_young_ledger_exit0(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="微波炉",
                                   buy_date="2025-01-01"),
                              dict(item="B", category="电饭煲",
                                   buy_date="2025-06-01")], d)
            out, _, code = go("report", p)
            self.assertEqual(code, 0)
            self.assertIn("全部在役期内", out)
            self.assertIn("最近到站 2030-06-01", out)

    def test_thin_no_active_exit3(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="旧A", category="洗衣机",
                                   buy_date="2000-01-01",
                                   retired_date="2010-01-01")], d)
            out, _, code = go("report", p)
            self.assertEqual(code, 3)
            self.assertIn("THIN", out)
            self.assertIn("在役 0 台", out)

    def test_thin_1_to_4_active_still_judged(self):
        # 算术不因薄账沉默：1 台超役照样亮灯，个人节奏才要 ≥3 台
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="燃气热水器",
                                   buy_date="2017-01-01"),
                              dict(item="B", category="微波炉",
                                   buy_date="2024-01-01"),
                              dict(item="旧C", category="微波炉",
                                   buy_date="2010-01-01",
                                   retired_date="2020-01-01")], d)
            out, _, code = go("report", p, "--as-of", "2026-09-05")
            self.assertEqual(code, 4)
            self.assertIn("超役", out)
            self.assertIn("个人节奏：THIN", out)

    def test_retired_history_thin_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([
                dict(item="A", category="微波炉", buy_date="2024-01-01"),
                dict(item="旧B", category="洗衣机", buy_date="2010-01-01",
                     retired_date="2020-01-01"),
                dict(item="旧C", category="微波炉", buy_date="2010-01-01",
                     retired_date="2020-01-01"),
            ], d)
            out, _, code = go("report", p)
            self.assertEqual(code, 0)
            self.assertIn("个人节奏：THIN（<3 台）", out)

    def test_future_buy_exit2(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="微波炉",
                                   buy_date="2030-01-01")], d)
            _, err, code = go("report", p, "--as-of", "2026-09-05")
            self.assertEqual(code, 2)
            self.assertIn("in the future", err)

    def test_retired_before_buy_exit2(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="微波炉",
                                   buy_date="2020-01-01",
                                   retired_date="2019-01-01")], d)
            _, err, code = go("report", p)
            self.assertEqual(code, 2)
            self.assertIn("retired before buy", err)

    def test_duplicate_item_exit2(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="微波炉",
                                   buy_date="2020-01-01"),
                              dict(item="A", category="电饭煲",
                                   buy_date="2021-01-01")], d)
            _, err, code = go("report", p)
            self.assertEqual(code, 2)
            self.assertIn("duplicate item", err)

    def test_bad_date_exit2(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="微波炉",
                                   buy_date="2020-13-01")], d)
            _, err, code = go("report", p)
            self.assertEqual(code, 2)
            self.assertIn("bad buy_date", err)

    def test_life_out_of_range_exit2(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="微波炉",
                                   buy_date="2020-01-01",
                                   life_years="80")], d)
            _, err, code = go("report", p)
            self.assertEqual(code, 2)
            self.assertIn("sane range", err)

    def test_bad_flags_exit2(self):
        for flag in ("--life", "--price"):
            _, err, code = go("report", EXAMPLES, flag, "燃气热水器")
            self.assertEqual(code, 2)
            self.assertIn("want CAT=", err)
        _, err, code = go("report", EXAMPLES, "--as-of", "2026-13-01")
        self.assertEqual(code, 2)
        self.assertIn("bad --as-of", err)
        _, err, code = go("report", "/nonexistent/fleet.tsv")
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_report_unaffected_by_never_prior(self):
        # 先验表外品类点名但不猜寿命：全部不可判级时 THIN，点名照出
        with tempfile.TemporaryDirectory() as d:
            p = write_ledger([dict(item="A", category="空气炸锅",
                                   buy_date="2020-01-01")], d)
            out, _, code = go("report", p)
            self.assertEqual(code, 3)
            self.assertIn("NEVER-PRIOR（1 台）", out)
            self.assertIn("--life 空气炸锅=年 翻案", out)
            self.assertIn("THIN", out)


if __name__ == "__main__":
    unittest.main()
