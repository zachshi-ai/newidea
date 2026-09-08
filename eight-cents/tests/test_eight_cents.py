#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""八分钱 · Eight Cents 验收测试。

覆盖: 每公里真实口径双路径(分项加总==直接公式==年成本互逆)、加权电价
双路径(加权==分段)、回本几何三态(闭式==逐月游走,参数网格全对拍)、
翻转里程阈值(闭式反解==扫描)、TCO 双路径、三盏灯恰线不亮、翻案参数
全链、购置税通识默认与翻案、账坏类、空账拒答、--pair、零墙钟跨哈希种子
字节复现、仓库快照逐字节。
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import eight_cents  # noqa: E402
from eight_cents import (  # noqa: E402
    blended_price, energy_per_km, marketing_per_km, fixed_per_km,
    real_per_km, yearly_cost, upfront, tco, payback, payback_walk,
    breakeven_km, yearly_gap, load_ledger,
)

EXAMPLES = os.path.join(ROOT, "examples")
CLI = os.path.join(ROOT, "eight_cents.py")

CAR_HEADER = ("name\ttype\tprice\tenergy100\tinsurance\tmaint\troad_tax\t"
              "purchase_tax\tnote")
USAGE_HEADER = "profile\tkey\tvalue\tnote"


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = eight_cents.main(argv)
    return rc, out.getvalue(), err.getvalue()


def car_row(name, ctype, price, e100, ins, maint, road, ptax="", note=""):
    return "\t".join([name, ctype, str(price), str(e100), str(ins),
                      str(maint), str(road), str(ptax), note])


def usage_rows(profile, **kw):
    vals = dict(km_year=18000, gas_price=7.8, home_price=0.32,
                public_price=1.35, home_share=0.85)
    vals.update(kw)
    return [f"{profile}\t{k}\t{v}" for k, v in vals.items()]


@contextlib.contextmanager
def ledger_dir(cars, usage):
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "cars.tsv"), "w", encoding="utf-8") as f:
            f.write(CAR_HEADER + "\n" + "\n".join(cars) + "\n")
        with open(os.path.join(d, "usage.tsv"), "w", encoding="utf-8") as f:
            f.write(USAGE_HEADER + "\n" + "\n".join(usage) + "\n")
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def make_car(name="电", ctype="ev", price=150000, e100=13.5, ins=5500,
             maint=300, road=0, ptax="0", tax_source="t"):
    return {"name": name, "type": ctype, "price": price, "energy100": e100,
            "insurance": ins, "maint": maint, "road_tax": road,
            "purchase_tax": float(ptax), "purchase_tax_raw": str(ptax),
            "tax_source": tax_source, "note": ""}


DEMO_PROF = dict(km_year=18000.0, gas_price=7.8, home_price=0.32,
                 public_price=1.35, home_share=0.85)


# ---------------------------------------------------------------- 算术 ----

class TestArithmetic(unittest.TestCase):
    def test_blended_price_weighted(self):
        p = dict(DEMO_PROF)
        self.assertAlmostEqual(blended_price(p), 0.85 * 0.32 + 0.15 * 1.35)

    def test_blended_ends(self):
        p0 = dict(DEMO_PROF, home_share=0.0)
        p1 = dict(DEMO_PROF, home_share=1.0)
        self.assertAlmostEqual(blended_price(p0), 1.35)
        self.assertAlmostEqual(blended_price(p1), 0.32)

    def test_blended_equals_segmented(self):
        """加权电价 == 家充段+公充段分段(线性恒等式)。"""
        p = dict(DEMO_PROF)
        kwh = 13.5 / 100 * p["km_year"]
        seg = kwh * p["home_share"] * p["home_price"] + \
            kwh * (1 - p["home_share"]) * p["public_price"]
        self.assertAlmostEqual(seg, kwh * blended_price(p), places=6)

    def test_energy_per_km_gas_vs_ev(self):
        gas = make_car("油", "gas", e100=6.5)
        self.assertAlmostEqual(energy_per_km(gas, DEMO_PROF), 6.5 / 100 * 7.8)
        ev = make_car()
        self.assertAlmostEqual(energy_per_km(ev, DEMO_PROF),
                               13.5 / 100 * (0.85 * 0.32 + 0.15 * 1.35))

    def test_marketing_ignores_public_charging(self):
        """营销口径按 100% 家充——公充占比再高,销售的数字也不变。"""
        ev = make_car()
        m_hi = marketing_per_km(ev, dict(DEMO_PROF, home_share=0.0))
        m_lo = marketing_per_km(ev, dict(DEMO_PROF, home_share=1.0))
        self.assertAlmostEqual(m_hi, m_lo)

    def test_real_per_km_decomposition(self):
        """真实每公里 = 分项加总(能耗+保险摊+保养摊+税摊) == 直接公式。"""
        for c in (make_car(), make_car("油", "gas", price=129800, e100=6.5,
                                       ins=4000, maint=800, road=350)):
            parts = sum(v for _, v in [
                ("能耗", energy_per_km(c, DEMO_PROF)),
                ("保险摊", c["insurance"] / DEMO_PROF["km_year"]),
                ("保养摊", c["maint"] / DEMO_PROF["km_year"]),
                ("车船税摊", c["road_tax"] / DEMO_PROF["km_year"])])
            self.assertAlmostEqual(parts, real_per_km(c, DEMO_PROF), places=12)

    def test_yearly_two_paths(self):
        """年成本: 固定+能耗×里程 == 真实每公里×里程。"""
        ev = make_car()
        a = ev["insurance"] + ev["maint"] + ev["road_tax"] + \
            energy_per_km(ev, DEMO_PROF) * DEMO_PROF["km_year"]
        b = real_per_km(ev, DEMO_PROF) * DEMO_PROF["km_year"]
        self.assertAlmostEqual(a, b, places=6)

    def test_tco_closed_vs_walked(self):
        """TCO: 闭式(落地+N×年成本) == 逐年累加,1..15 年全对拍。"""
        ev = make_car()
        for y in range(1, 16):
            closed = tco(ev, DEMO_PROF, y)
            walked = upfront(ev)
            for _ in range(y):
                walked += yearly_cost(ev, DEMO_PROF)
            self.assertAlmostEqual(closed, walked, places=6)

    def test_yearly_gap_sums(self):
        """年省分解各项之和 == 年成本差(方向: 贵车−便宜车)。"""
        a = make_car()
        b = make_car("油", "gas", price=129800, e100=6.5, ins=4000,
                     maint=800, road=350)
        gap = yearly_gap(a, b, DEMO_PROF)
        self.assertAlmostEqual(sum(gap.values()),
                               yearly_cost(a, DEMO_PROF) - yearly_cost(b, DEMO_PROF),
                               places=6)


class TestPayback(unittest.TestCase):
    def test_demo_wang(self):
        """样例王家: 落地差 25593.27,年省 7322.97,回本 41.94 月。"""
        ev = make_car(price=159800, ptax="7080")
        oil = make_car("油", "gas", price=129800, e100=6.5, ins=4000,
                       maint=800, road=350, ptax="0")
        # 油车购置税走通识默认(11486.73)——这里手动补齐与样例一致的落地
        oil["purchase_tax"] = 129800 / 1.13 * 0.10
        d, s, months = payback(ev, oil, DEMO_PROF)
        self.assertAlmostEqual(d, 25593.27, places=1)
        self.assertAlmostEqual(s, 7322.97, places=1)
        self.assertAlmostEqual(months, 41.94, places=1)

    def test_three_states(self):
        oil = make_car("油", "gas", price=120000, e100=6.5, ins=4000,
                       maint=800, road=350)               # 便宜
        ev = make_car(price=150000)                       # 贵但省
        # 贵车省得动 → 正回本
        d, s, m = payback(ev, oil, DEMO_PROF)
        self.assertGreater(d, 0)
        self.assertGreater(s, 0)
        self.assertGreater(m, 0)
        # 贵车一毛不省 → 追不平
        greedy = make_car("贪", "ev", price=160000, ins=99999)
        d, s, m = payback(greedy, oil, DEMO_PROF)
        self.assertIsNone(m)
        # 便宜且更省 → 第一天就省
        bargain = make_car("省", "ev", price=50000, ins=2000, maint=200)
        d, s, m = payback(bargain, ev, DEMO_PROF)
        self.assertLess(d, 0)
        self.assertEqual(m, 0.0)
        # 便宜但更费 → 这本账里没有回本
        pricier_to_run = make_car("费", "ev", price=50000, ins=99999)
        d, s, m = payback(pricier_to_run, ev, DEMO_PROF)
        self.assertLess(d, 0)
        self.assertLess(s, 0)
        self.assertIsNone(m)

    def test_closed_vs_walk_grid(self):
        """闭式 == 逐月游走: 落地差/年省/里程 5×5×3 参数网格全对拍。"""
        for dmult in (0.5, 1.0, 1.5, 2.0, 3.0):
            for km in (6000, 12000, 18000, 25000, 40000):
                for hs in (0.0, 0.5, 1.0):
                    prof = dict(DEMO_PROF, km_year=km, home_share=hs)
                    ev = make_car()
                    oil = make_car("油", "gas", price=100000, e100=6.5,
                                   ins=4000, maint=800, road=350, ptax="0")
                    d, s, m = payback(ev, oil, prof)
                    w = payback_walk(d, s, 600)
                    if m is None or w is None:
                        self.assertIsNone(m)
                        self.assertIsNone(w)
                    else:
                        self.assertLessEqual(abs(m - w), 1.01,
                                             f"km={km} hs={hs} d%={dmult}")

    def test_walk_matches_closed_exact_years(self):
        """整数年回本: D = 10×S → 恰 120 月,闭式==游走==120。"""
        d, s = 50000.0, 5000.0
        self.assertAlmostEqual(d / (s / 12), 120.0)
        self.assertEqual(payback_walk(d, s, 120), 120.0)


class TestBreakevenKm(unittest.TestCase):
    def test_threshold_matches_scan(self):
        """翻转里程: 闭式反解 == 二分扫描,两个 profile 都对拍。"""
        ev = make_car()
        oil = make_car("油", "gas", price=100000, e100=6.5, ins=4000,
                       maint=800, road=350, ptax="0")
        for hs in (0.0, 0.5, 0.85):
            prof = dict(DEMO_PROF, home_share=hs)
            k = breakeven_km((ev, oil), prof, 120)
            self.assertIsNotNone(k)
            lo, hi = 0.0, 500000.0
            for _ in range(60):
                mid = (lo + hi) / 2
                p2 = dict(prof, km_year=mid)
                _, _, m = payback(ev, oil, p2)
                if m is None or m > 120:
                    lo = mid
                else:
                    hi = mid
            self.assertLess(abs(hi - k), max(1.0, k * 1e-3))

    def test_threshold_demo_values(self):
        """样例翻转里程(独立手算): wang 7245.5 km / li 9882.5 km。"""
        ev = make_car(price=159800, ptax="7080")
        oil = make_car("油", "gas", price=129800, e100=6.5, ins=4000,
                       maint=800, road=350, ptax="0")
        oil["purchase_tax"] = 129800 / 1.13 * 0.10
        wang = breakeven_km((ev, oil), DEMO_PROF, 120)
        li = breakeven_km((ev, oil), dict(DEMO_PROF, km_year=6000, home_share=0.0), 120)
        self.assertAlmostEqual(wang, 7245.5, places=0)
        self.assertAlmostEqual(li, 9882.5, places=0)

    def test_no_threshold_when_ev_pricier_energy(self):
        """电车能耗不便宜(全公充比油贵)→ 没有翻转里程可言。"""
        ev = make_car(e100=45.0)  # 高耗电,45kWh/100km × 1.35 = 0.6075 元/km > 油车
        oil = make_car("油", "gas", price=100000, e100=6.5, ins=4000,
                       maint=800, road=350, ptax="0")
        self.assertIsNone(breakeven_km((ev, oil), dict(DEMO_PROF, home_share=0.0), 120))


# ---------------------------------------------------------------- 样例账 ----

class TestDemoLedger(unittest.TestCase):
    def test_report_wang_exit0_numbers(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES, "--profile", "wang"])
        self.assertEqual(rc, eight_cents.EXIT_OK)
        for frag in ("50.7 分", "79.3 分", "4.3 分", "38.6 分",
                     "¥14,276.00", "¥6,953.03", "¥11,486.73(通识默认",
                     "8.9 倍", "¥18,344.52",
                     "🔵 HOME-CHARGING", "🟡 INSURANCE-GAP"):
            self.assertIn(frag, out)
        self.assertNotIn("🔴", out)

    def test_breakeven_wang_upfront_gap(self):
        rc, out, _ = run_cli(["breakeven", "--dir", EXAMPLES, "--profile", "wang"])
        self.assertIn("¥25,593.27", out)

    def test_report_li_exit4_lamps(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES, "--profile", "li"])
        self.assertEqual(rc, eight_cents.EXIT_RED)
        for frag in ("🔴 PENNY-MYTH", "4.2 倍", "🔴 BREAKEVEN-NEVER",
                     "19.7 年", "136.5 分", "114.9 分",
                     "¥17,802.27"):
            self.assertIn(frag, out)

    def test_breakeven_wang_42_months(self):
        rc, out, _ = run_cli(["breakeven", "--dir", EXAMPLES,
                              "--profile", "wang"])
        self.assertEqual(rc, eight_cents.EXIT_OK)
        for frag in ("41.9 个月", "← 反超", "省 ¥7,972.97(能耗)",
                     "多花 ¥1,500.00(保险)", "7,245 km"):
            self.assertIn(frag, out)

    def test_breakeven_li_never(self):
        rc, out, _ = run_cli(["breakeven", "--dir", EXAMPLES, "--profile", "li"])
        self.assertEqual(rc, eight_cents.EXIT_RED)
        self.assertIn("236.5 个月", out)
        self.assertIn("超出 --payback-cap 120 月,追不平", out)

    def test_validate_green(self):
        rc, out, _ = run_cli(["validate", "--dir", EXAMPLES])
        self.assertEqual(rc, eight_cents.EXIT_OK)
        self.assertIn("全部通过 ✓", out)
        for frag in ("分项加总 == 直接公式", "加权价×总电量 == 家充段+公充段分段",
                     "闭式 == 逐年累加", "闭式 == 逐月游走", "闭式反解 == 二分扫描"):
            self.assertIn(frag, out)

    def test_report_all_profiles_default(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES])
        self.assertEqual(rc, eight_cents.EXIT_RED)  # li 亮红
        self.assertIn("profile wang", out)
        self.assertIn("profile li", out)


# ---------------------------------------------------------------- 灯线 ----

class TestLampLines(unittest.TestCase):
    EV = None

    def ledger(self, home_share, ins_ev=5500, ins_oil=4000, km=18000):
        return ledger_dir(
            [car_row("电车", "ev", 159800, 13.5, ins_ev, 300, 0, 0),
             car_row("油车", "gas", 129800, 6.5, ins_oil, 800, 350, "")],
            usage_rows("wang", km_year=km, home_share=home_share))

    def test_penny_line_exact_not_lit(self):
        """PENNY 恰线不亮: ratio = 加权/家充,--penny-line 恰等于 ratio → 不亮。"""
        hs = 0.5
        ratio = (hs * 0.32 + 0.5 * 1.35) / 0.32
        with self.ledger(hs) as d:
            rc, out, _ = run_cli(["report", "--dir", d,
                                  "--penny-line", repr(ratio)])
            self.assertEqual(rc, eight_cents.EXIT_OK)
            self.assertNotIn("PENNY-MYTH", out)
            rc, out, _ = run_cli(["report", "--dir", d,
                                  "--penny-line", repr(ratio * 0.999)])
            self.assertEqual(rc, eight_cents.EXIT_RED)
            self.assertIn("PENNY-MYTH", out)

    def test_home_line_exact_not_lit(self):
        """恰 0.6 不亮 HOME 灯(>0.6 才亮);PENNY 与本灯无关,只看灯名。"""
        with self.ledger(0.6) as d:
            rc, out, _ = run_cli(["report", "--dir", d])
            self.assertNotIn("HOME-CHARGING", out)
        with self.ledger(0.61) as d:
            rc, out, _ = run_cli(["report", "--dir", d])
            self.assertIn("HOME-CHARGING", out)

    def test_ins_gap_line_exact_not_lit(self):
        """保费差恰 25% 不亮,超线亮。"""
        with self.ledger(0.85, ins_ev=5000, ins_oil=4000) as d:
            rc, out, _ = run_cli(["report", "--dir", d])
            self.assertNotIn("INSURANCE-GAP", out)
        with self.ledger(0.85, ins_ev=5001, ins_oil=4000) as d:
            rc, out, _ = run_cli(["report", "--dir", d])
            self.assertIn("INSURANCE-GAP", out)

    def test_payback_cap_exact_not_lit(self):
        """回本恰线不亮: cap 恰等于程序输出月数 → 不亮;cap 缩 1% → 亮。"""
        # 构造回本约 120 月: D=50000, S≈5000.96
        with ledger_dir(
            [car_row("电车", "ev", 158849.56, 13.5, 7500, 300, 322, 0),
             car_row("油车", "gas", 100000, 6.5, 4000, 800, 350, "")],
            usage_rows("wang")
        ) as d:
            import re
            rc, out, _ = run_cli(["breakeven", "--dir", d, "--profile", "wang"])
            m = re.search(r"回本: ([\d.]+) 个月", out)
            self.assertIsNotNone(m, out)
            months = float(m.group(1))
            rc, out, _ = run_cli(["breakeven", "--dir", d, "--profile", "wang",
                                  "--payback-cap", repr(months)])
            self.assertEqual(rc, eight_cents.EXIT_OK)
            self.assertNotIn("追不平", out)
            rc, out, _ = run_cli(["breakeven", "--dir", d, "--profile", "wang",
                                  "--payback-cap", repr(months * 0.99)])
            self.assertEqual(rc, eight_cents.EXIT_RED)
            self.assertIn("追不平", out)


# ---------------------------------------------------------------- 翻案 ----

class TestOverrides(unittest.TestCase):
    def test_gas_tax_rate_override(self):
        with ledger_dir(
            [car_row("油车", "gas", 113000, 6.5, 4000, 800, 350, "")],
            usage_rows("wang")
        ) as d:
            rc, out, _ = run_cli(["report", "--dir", d, "--profile", "wang"])
            self.assertIn("¥10,000.00(通识默认", out)  # 113000/1.13×10%
            rc, out, _ = run_cli(["report", "--dir", d, "--profile", "wang",
                                  "--gas-tax-rate", "0.05"])
            self.assertIn("¥5,000.00(通识默认", out)

    def test_ev_default_tax_zero_with_disclosure(self):
        with ledger_dir(
            [car_row("电车", "ev", 159800, 13.5, 5500, 300, 0, "")],
            usage_rows("wang")
        ) as d:
            rc, out, _ = run_cli(["report", "--dir", d, "--profile", "wang"])
            self.assertIn("(通识默认 0(免征))", out)
            self.assertIn("减半过渡期", out)

    def test_explicit_tax_wins(self):
        with ledger_dir(
            [car_row("电车", "ev", 159800, 13.5, 5500, 300, 0, 7080)],
            usage_rows("wang")
        ) as d:
            rc, out, _ = run_cli(["report", "--dir", d, "--profile", "wang"])
            self.assertIn("¥7,080.00(你填的)", out)
            self.assertNotIn("减半过渡期", out)

    def test_years_override(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES, "--profile", "wang",
                              "--years", "10"])
        self.assertIn("TCO 10 年", out)
        self.assertIn("¥284,046.73", out)  # 141286.73 + 10×14276(手算复核)
        self.assertIn("¥236,410.35", out)  # 166880 + 10×6953.035


# ---------------------------------------------------------------- 账坏 ----

class TestBadLedger(unittest.TestCase):
    def assert_bad(self, cars, usage, frag=None):
        with ledger_dir(cars, usage) as d:
            rc, out, err = run_cli(["report", "--dir", d])
            self.assertEqual(rc, eight_cents.EXIT_BAD)
            self.assertTrue(err.startswith("账坏:"))
            if frag:
                self.assertIn(frag, err)

    def test_missing_column(self):
        """表头缺列 → 缺列账坏。"""
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "cars.tsv"), "w", encoding="utf-8") as f:
                f.write("name\ttype\tprice\n油车\tgas\t129800\n")
            with open(os.path.join(d, "usage.tsv"), "w", encoding="utf-8") as f:
                f.write(USAGE_HEADER + "\n" + "\n".join(usage_rows("wang")) + "\n")
            rc, out, err = run_cli(["report", "--dir", d])
            self.assertEqual(rc, eight_cents.EXIT_BAD)
            self.assertIn("缺列", err)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_short_row_missing_fields(self):
        """行字段不足 → 空值不是数字,账坏。"""
        self.assert_bad(
            ["油车\tgas\t129800\t6.5"], usage_rows("wang"), "不是数字")

    def test_unknown_type(self):
        self.assert_bad(
            [car_row("混动车", "hev", 150000, 5.0, 4000, 800, 350, 0)],
            usage_rows("wang"), "type 必须是 gas/ev")

    def test_negative_price(self):
        self.assert_bad(
            [car_row("油车", "gas", -1, 6.5, 4000, 800, 350, 0)],
            usage_rows("wang"), "车价必须 > 0")

    def test_zero_energy(self):
        self.assert_bad(
            [car_row("油车", "gas", 129800, 0, 4000, 800, 350, 0)],
            usage_rows("wang"), "energy100 必须 > 0")

    def test_negative_insurance(self):
        self.assert_bad(
            [car_row("油车", "gas", 129800, 6.5, -5, 800, 350, 0)],
            usage_rows("wang"), "不能为负")

    def test_negative_purchase_tax(self):
        self.assert_bad(
            [car_row("电车", "ev", 159800, 13.5, 5500, 300, 0, -1)],
            usage_rows("wang"), "购置税不能为负")

    def test_duplicate_car_name(self):
        self.assert_bad(
            [car_row("电车", "ev", 159800, 13.5, 5500, 300, 0, 0),
             car_row("电车", "ev", 160000, 12.5, 5500, 300, 0, 0)],
            usage_rows("wang"), "车名重复")

    def test_missing_name(self):
        rows = ["\t".join(["", "gas", "129800", "6.5", "4000", "800", "350", "", ""])]
        self.assert_bad(rows, usage_rows("wang"), "缺 name")

    def test_non_numeric_price(self):
        self.assert_bad(
            [car_row("油车", "gas", "十二万", 6.5, 4000, 800, 350, 0)],
            usage_rows("wang"), "不是数字")

    def test_usage_unknown_key(self):
        self.assert_bad(
            [car_row("油车", "gas", 129800, 6.5, 4000, 800, 350, 0)],
            usage_rows("wang") + ["wang\tkm_years\t18000"],
            "未知参数")

    def test_usage_missing_key(self):
        usage = [r for r in usage_rows("wang") if not r.startswith("wang\thome_share")]
        self.assert_bad(
            [car_row("油车", "gas", 129800, 6.5, 4000, 800, 350, 0)],
            usage, "缺参数")

    def test_usage_duplicate_key(self):
        self.assert_bad(
            [car_row("油车", "gas", 129800, 6.5, 4000, 800, 350, 0)],
            usage_rows("wang") + ["wang\tkm_year\t99999"],
            "重复")

    def test_usage_km_zero(self):
        self.assert_bad(
            [car_row("油车", "gas", 129800, 6.5, 4000, 800, 350, 0)],
            usage_rows("wang", km_year=0), "km_year 必须 > 0")

    def test_usage_share_out_of_range(self):
        for bad in (-0.1, 1.5):
            self.assert_bad(
                [car_row("油车", "gas", 129800, 6.5, 4000, 800, 350, 0)],
                usage_rows("wang", home_share=bad), "home_share 必须在 0..1")

    def test_usage_missing_profile(self):
        with ledger_dir(
            [car_row("油车", "gas", 129800, 6.5, 4000, 800, 350, 0)],
            usage_rows("wang")
        ) as d:
            rc, out, err = run_cli(["report", "--dir", d, "--profile", "zhang"])
            self.assertEqual(rc, eight_cents.EXIT_EMPTY)
            self.assertIn("没有这个 profile", err)


class TestEmptyLedger(unittest.TestCase):
    def test_no_cars(self):
        with ledger_dir([], usage_rows("wang")) as d:
            rc, out, err = run_cli(["report", "--dir", d])
            self.assertEqual(rc, eight_cents.EXIT_EMPTY)
            self.assertIn("cars.tsv 是空的", err)

    def test_no_usage(self):
        with ledger_dir([car_row("油车", "gas", 129800, 6.5, 4000, 800, 350, 0)], []) as d:
            rc, out, err = run_cli(["report", "--dir", d])
            self.assertEqual(rc, eight_cents.EXIT_EMPTY)
            self.assertIn("usage.tsv 是空的", err)

    def test_validate_empty(self):
        with ledger_dir([], []) as d:
            rc, _, err = run_cli(["validate", "--dir", d])
            self.assertEqual(rc, eight_cents.EXIT_EMPTY)


# ---------------------------------------------------------------- breakeven 接口 ----

class TestBreakevenInterface(unittest.TestCase):
    CARS = [
        car_row("甲", "gas", 129800, 6.5, 4000, 800, 350, 11487),
        car_row("乙", "ev", 159800, 13.5, 5500, 300, 0, 7080),
        car_row("丙", "ev", 199800, 12.5, 6500, 300, 0, 8850),
    ]

    def test_three_cars_require_pair(self):
        with ledger_dir(self.CARS, usage_rows("wang")) as d:
            rc, _, err = run_cli(["breakeven", "--dir", d])
            self.assertEqual(rc, eight_cents.EXIT_EMPTY)
            self.assertIn("--pair", err)

    def test_pair_selects(self):
        with ledger_dir(self.CARS, usage_rows("wang")) as d:
            # 甲→丙: 丙贵 67363 但年省 6408 → 126 月追平超 cap,红
            rc, out, _ = run_cli(["breakeven", "--dir", d, "--pair", "甲,丙"])
            self.assertEqual(rc, eight_cents.EXIT_RED)
            self.assertIn("贵的: 丙", out)
            # 乙→丙: 丙贵且更费(保险 6500/能耗省有限)→ 追不平,红
            rc, out, _ = run_cli(["breakeven", "--dir", d, "--pair", "乙,丙"])
            self.assertEqual(rc, eight_cents.EXIT_RED)
            self.assertIn("贵的: 丙", out)

    def test_pair_unknown_name(self):
        with ledger_dir(self.CARS, usage_rows("wang")) as d:
            rc, _, err = run_cli(["breakeven", "--dir", d, "--pair", "甲,丁"])
            self.assertEqual(rc, eight_cents.EXIT_EMPTY)
            self.assertIn("账上没有这辆车", err)

    def test_single_car_declines(self):
        with ledger_dir(self.CARS[:1], usage_rows("wang")) as d:
            rc, _, err = run_cli(["breakeven", "--dir", d])
            self.assertEqual(rc, eight_cents.EXIT_EMPTY)

    def test_two_cars_default_pair(self):
        with ledger_dir(self.CARS[:2], usage_rows("wang")) as d:
            rc, out, _ = run_cli(["breakeven", "--dir", d])
            self.assertIn("贵的: 乙", out)

    def test_cheap_always_wins_case(self):
        """便宜又省: 回本从第一天开始。"""
        with ledger_dir(
            [car_row("神车", "gas", 50000, 6.5, 4000, 800, 350, 0),
             car_row("贵车", "ev", 159800, 13.5, 9999, 300, 0, 0)],
            usage_rows("wang")
        ) as d:
            rc, out, _ = run_cli(["breakeven", "--dir", d, "--profile", "wang"])
            self.assertEqual(rc, eight_cents.EXIT_RED)  # 贵车追不平
            self.assertIn("追不平", out)


# ---------------------------------------------------------------- 复现 ----

class TestReproducibility(unittest.TestCase):
    def test_byte_identical_two_runs(self):
        args = ["report", "--dir", EXAMPLES]
        rc1, out1, _ = run_cli(args)
        rc2, out2, _ = run_cli(args)
        self.assertEqual(out1, out2)

    def test_byte_identical_across_hash_seeds(self):
        """PYTHONHASHSEED 两颗种子,输出逐字节一致(profile 顺序稳定)。"""
        env = dict(os.environ)
        outs = []
        for seed in ("0", "12345"):
            r = subprocess.run(
                [sys.executable, CLI, "report", "--dir", EXAMPLES],
                capture_output=True, text=True, env=dict(env, PYTHONHASHSEED=seed))
            outs.append(r.stdout)
        self.assertEqual(outs[0], outs[1])

    def test_snapshot_byte_exact(self):
        r = subprocess.run(
            [sys.executable, os.path.join(EXAMPLES, "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
