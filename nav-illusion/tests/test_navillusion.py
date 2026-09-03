#!/usr/bin/env python3
"""Acceptance tests for 净值幻觉 · NAV Illusion.

Every acceptance criterion in README.md maps to a test class here.
Synthetic ledgers are written to a temp dir; the demo reports are the
dogfood and are byte-checked against the delivered CLI. Key demo numbers
(XIRR, TWR, market value) were cross-checked with an independent Newton
solver and are pinned with tolerances.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import nav_illusion as ni  # noqa: E402

CLI = ROOT / "nav_illusion.py"
EXAMPLES = ROOT / "examples"
FLOWS = str(EXAMPLES / "flows.csv")
NAVS = str(EXAMPLES / "navs.csv")
AS_OF = "2026-06-30"

DEMO_NAVS = [
    ("2024-01-01", "1.0000"),
    ("2024-04-01", "1.0800"),
    ("2024-07-01", "1.1500"),
    ("2024-10-01", "0.9800"),
    ("2025-01-01", "1.0500"),
    ("2025-04-01", "1.1800"),
    ("2025-07-01", "1.2600"),
    ("2025-10-01", "1.2200"),
    ("2026-01-01", "1.3000"),
    ("2026-04-01", "1.3300"),
    ("2026-06-30", "1.3500"),
]

# Independently computed (Newton solver, see README acceptance table).
DEMO_XIRR = 0.064599
DEMO_TWR = 0.127767
DEMO_MV = 29036.29


def write_ledger(tmp, flow_rows, nav_rows,
                 flow_name="flows.csv", nav_name="navs.csv"):
    flow_path = os.path.join(tmp, flow_name)
    with open(flow_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(flow_rows) + "\n")
    nav_path = os.path.join(tmp, nav_name)
    with open(nav_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(nav_rows) + "\n")
    return flow_path, nav_path


def demo_nav_rows():
    return ["日期,净值"] + ["%s,%s" % p for p in DEMO_NAVS]


def run_cli(argv):
    result = subprocess.run(
        [sys.executable, str(CLI)] + argv, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def call_main(argv):
    """Run main() in-process; returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ni.main(argv)
    return code, out.getvalue(), err.getvalue()


TMP = None


def scratch():
    global TMP
    if TMP is None:
        TMP = tempfile.mkdtemp()
    return TMP


def make_flows(rows, name="flows.csv"):
    path = os.path.join(scratch(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return path


def make_navs(rows, name="navs.csv"):
    path = os.path.join(scratch(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return path


# ---------------------------------------------------------------- parsing

class ParserTests(unittest.TestCase):

    def test_chinese_headers_and_actions(self):
        flows = ni.parse_flows(FLOWS)
        self.assertEqual([f.action for f in flows],
                         ["BUY", "BUY", "SELL", "BUY", "BUY"])
        self.assertEqual(flows[0].amount, 5000.0)
        self.assertEqual(flows[0].nav, 1.0018)

    def test_english_headers(self):
        path = make_flows(["date,action,amount",
                           "2024-01-03,buy,5000",
                           "2024-10-08,sell,2000",
                           "2025-01-06,dividend,120"])
        flows = ni.parse_flows(path)
        self.assertEqual([f.action for f in flows], ["BUY", "SELL", "DIV"])

    def test_action_alias_lu_e_hua(self):
        path = make_flows(["日期,动作,金额", "2024-01-03,买入,100",
                           "2024-06-01,卖出,50", "2024-09-01,派息,5"])
        self.assertEqual([f.action for f in ni.parse_flows(path)],
                         ["BUY", "SELL", "DIV"])

    def test_date_formats(self):
        path = make_flows(["日期,动作,金额", "2024-01-03,申购,100",
                           "2024/06/01,申购,100", "2024.09.01,申购,100"])
        days = [f.date for f in ni.parse_flows(path)]
        self.assertEqual(days, [date(2024, 1, 3), date(2024, 6, 1),
                                date(2024, 9, 1)])

    def test_optional_nav_column_may_be_absent(self):
        path = make_flows(["日期,动作,金额,备注", "2024-01-03,申购,5000,试水"])
        flows = ni.parse_flows(path)
        self.assertIsNone(flows[0].nav)
        self.assertEqual(flows[0].note, "试水")

    def test_bad_action_reports_line(self):
        path = make_flows(["日期,动作,金额", "2024-01-03,梭哈,100"])
        with self.assertRaises(ni.Refuse) as ctx:
            ni.parse_flows(path)
        self.assertIn("line 2", str(ctx.exception))
        self.assertIn("梭哈", str(ctx.exception))

    def test_bad_amount_reports_line(self):
        path = make_flows(["日期,动作,金额", "2024-01-03,申购,-5"])
        with self.assertRaises(ni.Refuse) as ctx:
            ni.parse_flows(path)
        self.assertIn("> 0", str(ctx.exception))

    def test_missing_header(self):
        path = make_flows(["日期,动作", "2024-01-03,申购"])
        with self.assertRaises(ni.Refuse) as ctx:
            ni.parse_flows(path)
        self.assertIn("amount", str(ctx.exception))

    def test_blank_rows_tolerated(self):
        path = make_flows(["日期,动作,金额", "", "2024-01-03,申购,100", "  "])
        self.assertEqual(len(ni.parse_flows(path)), 1)

    def test_duplicate_nav_date_refused(self):
        path = make_navs(["日期,净值", "2024-01-01,1.0", "2024-01-01,1.1"])
        with self.assertRaises(ni.Refuse) as ctx:
            ni.parse_navs(path)
        self.assertIn("duplicate", str(ctx.exception))

    def test_nav_alias_fuquan(self):
        path = make_navs(["日期,复权净值", "2024-01-01,1.0",
                          "2025-01-01,1.2"])
        series = ni.parse_navs(path)
        self.assertEqual(len(series.points), 2)


# ------------------------------------------------------------- interpolation

class InterpTests(unittest.TestCase):

    def setUp(self):
        self.series = ni.parse_navs(make_navs(demo_nav_rows()))

    def test_exact_day_hits_grid(self):
        self.assertAlmostEqual(self.series.nav_at(date(2024, 4, 1)), 1.08)

    def test_linear_by_days(self):
        # 2024-01-01 → 2024-04-01 spans 91 days (leap year), +0.08 total.
        got = self.series.nav_at(date(2024, 1, 31))
        self.assertAlmostEqual(got, 1.0 + 0.08 * 30 / 91.0, places=10)

    def test_out_of_range_refused(self):
        with self.assertRaises(ni.Refuse):
            self.series.nav_at(date(2023, 12, 31))
        with self.assertRaises(ni.Refuse):
            self.series.nav_at(date(2026, 7, 1))

    def test_interp_disclosed_in_report(self):
        code, out, _ = call_main(["report", FLOWS, NAVS, "--as-of", AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("4 nav(s) interpolated", out)

    def test_explicit_navs_skip_interp(self):
        rows = ["日期,动作,金额,净值", "2024-01-03,申购,5000,1.0018",
                "2024-07-15,申购,20000,1.1241", "2024-10-08,赎回,12000,0.9853",
                "2025-03-20,申购,8000,1.1627", "2025-08-10,申购,5000,1.2426"]
        path = make_flows(rows, "explicit-flows.csv")
        code, out, _ = call_main(["report", path, NAVS, "--as-of", AS_OF,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertEqual(data["interpolated_flows"], 0)
        self.assertAlmostEqual(data["market_value"], DEMO_MV, delta=0.05)


# -------------------------------------------------------------- share ledger

class ShareLedgerTests(unittest.TestCase):

    def test_dividend_never_touches_shares(self):
        flows = [
            ni.Flow(date(2024, 1, 3), "BUY", 1000.0, 1.0, "", 2),
            ni.Flow(date(2024, 6, 1), "DIV", 50.0, None, "", 3),
        ]
        navs = ni.parse_navs(make_navs(demo_nav_rows()))
        ledger = ni.build_share_ledger(flows, navs, date(2026, 6, 30))
        self.assertAlmostEqual(ledger["shares"], 1000.0, places=6)
        self.assertAlmostEqual(ledger["div_total"], 50.0)
        self.assertEqual(ledger["divs"], 1)

    def test_market_value_is_shares_times_asof_nav(self):
        flows = [ni.Flow(date(2024, 1, 3), "BUY", 1000.0, 1.0, "", 2)]
        navs = ni.parse_navs(make_navs(demo_nav_rows()))
        ledger = ni.build_share_ledger(flows, navs, date(2026, 6, 30))
        self.assertAlmostEqual(ledger["market_value"], 1000.0 * 1.35, places=6)

    def test_oversell_refused(self):
        path = make_flows(["日期,动作,金额", "2024-01-03,申购,1000",
                           "2024-10-08,赎回,2000"])
        code, out, err = call_main(["report", path, NAVS, "--as-of", AS_OF])
        self.assertEqual(code, 3)
        self.assertIn("over-draws", err)

    def test_flow_after_asof_refused(self):
        path = make_flows(["日期,动作,金额", "2026-07-01,申购,1000"])
        code, _, err = call_main(["report", path, NAVS, "--as-of", AS_OF])
        self.assertEqual(code, 3)
        self.assertIn("after as-of", err)

    def test_flow_before_nav_range_refused(self):
        path = make_flows(["日期,动作,金额", "2023-12-01,申购,1000"])
        code, _, err = call_main(["report", path, NAVS, "--as-of", AS_OF])
        self.assertEqual(code, 3)
        self.assertIn("outside the nav range", err)

    def test_demo_reconciliation(self):
        flows = ni.parse_flows(FLOWS)
        navs = ni.parse_navs(NAVS)
        ledger = ni.build_share_ledger(flows, navs, date(2026, 6, 30))
        self.assertAlmostEqual(ledger["shares"], 21508.3633, places=3)
        self.assertAlmostEqual(ledger["market_value"], DEMO_MV, places=1)
        self.assertAlmostEqual(ledger["net_invested"], 26000.0, places=6)


# --------------------------------------------------------------------- XIRR

class XirrTests(unittest.TestCase):

    def test_double_in_two_years(self):
        # 2025-01-01 → 2027-01-01 is exactly 730 days (no leap year).
        legs = [(date(2025, 1, 1), -10000.0), (date(2027, 1, 1), 20000.0)]
        rate = ni.xirr(legs, date(2027, 1, 1))
        self.assertAlmostEqual(rate, 2.0 ** 0.5 - 1.0, places=6)

    def test_flat_year_is_zero(self):
        legs = [(date(2025, 1, 1), -10000.0), (date(2026, 1, 1), 10000.0)]
        self.assertAlmostEqual(ni.xirr(legs, date(2026, 1, 1)), 0.0, places=6)

    def test_loss_is_negative(self):
        legs = [(date(2025, 1, 1), -10000.0), (date(2026, 1, 1), 8000.0)]
        self.assertAlmostEqual(ni.xirr(legs, date(2026, 1, 1)), -0.20, places=6)

    def test_demo_xirr_matches_independent_solver(self):
        legs = [(date(2024, 1, 3), -5000.0), (date(2024, 7, 15), -20000.0),
                (date(2024, 10, 8), 12000.0), (date(2025, 3, 20), -8000.0),
                (date(2025, 8, 10), -5000.0), (date(2026, 6, 30), DEMO_MV)]
        self.assertAlmostEqual(ni.xirr(legs, date(2026, 6, 30)),
                               DEMO_XIRR, places=4)

    def test_one_signed_refused(self):
        legs = [(date(2025, 1, 1), 100.0), (date(2025, 6, 1), 100.0)]
        with self.assertRaises(ni.Refuse):
            ni.xirr(legs, date(2025, 12, 31))

    def test_too_few_legs_refused(self):
        legs = [(date(2025, 1, 1), -100.0)]
        with self.assertRaises(ni.Refuse):
            ni.xirr(legs, date(2025, 12, 31))


# ---------------------------------------------------------------------- TWR

class TwrTests(unittest.TestCase):

    def setUp(self):
        self.navs = ni.parse_navs(make_navs(demo_nav_rows()))

    def test_total_and_annual(self):
        total, annual = ni.twr(self.navs)
        self.assertAlmostEqual(total, 0.35, places=10)
        self.assertAlmostEqual(annual, DEMO_TWR, places=4)

    def test_short_span_refused(self):
        path = make_navs(["日期,净值", "2026-01-01,1.0", "2026-03-01,1.1"])
        with self.assertRaises(ni.Refuse) as ctx:
            ni.twr(ni.parse_navs(path))
        self.assertIn("180", str(ctx.exception))

    def test_single_point_refused(self):
        path = make_navs(["日期,净值", "2026-01-01,1.0"])
        with self.assertRaises(ni.Refuse):
            ni.twr(ni.parse_navs(path))


# --------------------------------------------------------------- gap verdict

class GapTests(unittest.TestCase):

    def test_gap_is_xirr_minus_twr(self):
        code, out, _ = call_main(["report", FLOWS, NAVS, "--as-of", AS_OF,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertAlmostEqual(data["gap_pp"],
                               (data["xirr"] - data["twr_annual"]) * 100,
                               places=3)
        self.assertAlmostEqual(data["gap_pp"], -6.3168, places=3)

    def test_bleeding_exits_4(self):
        code, out, _ = call_main(["report", FLOWS, NAVS, "--as-of", AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("BLEEDING", out)

    def test_beat_when_only_bought_the_bottom(self):
        flows = make_flows(["日期,动作,金额", "2024-10-01,申购,10000"])
        code, out, _ = call_main(["report", flows, NAVS])
        self.assertEqual(code, 0)
        self.assertIn("BEAT", out)

    def test_drag_when_only_bought_the_top(self):
        flows = make_flows(["日期,动作,金额", "2024-07-01,申购,10000"])
        code, out, _ = call_main(["report", flows, NAVS])
        self.assertEqual(code, 0)
        self.assertIn("DRAG", out)
        self.assertNotIn("BLEEDING", out)

    def test_gap_line_override_relaxes_gate(self):
        code, out, _ = call_main(["report", FLOWS, NAVS, "--as-of", AS_OF,
                                  "--gap-line", "-10"])
        self.assertEqual(code, 0)
        self.assertIn("DRAG", out)

    def test_gap_line_tightens_gate(self):
        code, _, _ = call_main(["report", FLOWS, NAVS, "--as-of", AS_OF,
                                "--gap-line", "-1"])
        self.assertEqual(code, 4)


# ------------------------------------------------------- positions and panic

class PercentileTests(unittest.TestCase):

    def test_demo_positions(self):
        flows = ni.parse_flows(FLOWS)
        navs = ni.parse_navs(NAVS)
        rows, weighted = ni.audit_flows(flows, navs, date(2026, 6, 30))
        by_date = {r["flow"].date.isoformat(): r for r in rows}
        self.assertIsNone(by_date["2024-01-03"]["pos"])  # no history yet
        self.assertAlmostEqual(by_date["2024-07-15"]["pos"], 0.8275, places=3)
        self.assertAlmostEqual(by_date["2025-03-20"]["pos"], 1.0, places=6)
        self.assertAlmostEqual(by_date["2025-08-10"]["pos"], 0.9379, places=3)
        self.assertAlmostEqual(weighted, 0.8864, places=3)

    def test_labels(self):
        code, out, _ = call_main(["flows", FLOWS, NAVS, "--as-of", AS_OF])
        self.assertIn("FIRST BUYS", out)
        self.assertEqual(out.count("CHASE-HI"), 3)
        self.assertIn("CHASING", out)

    def test_bottom_fishing_label(self):
        flows = make_flows(["日期,动作,金额", "2024-01-05,申购,1000",
                            "2024-10-01,申购,10000"])
        code, out, _ = call_main(["flows", flows, NAVS])
        self.assertIn("BOTTOM-LO", out)
        self.assertIn("BOTTOM-FISHING", out)

    def test_clamped_to_unit_range(self):
        navs = ni.parse_navs(make_navs(demo_nav_rows()))
        pos = ni.price_position(navs, date(2025, 3, 20), 1.1626667)
        self.assertAlmostEqual(pos, 1.0, places=6)
        self.assertTrue(0.0 <= pos <= 1.0)


class PanicTests(unittest.TestCase):

    def test_demo_panic_sell(self):
        flows = ni.parse_flows(FLOWS)
        navs = ni.parse_navs(NAVS)
        rows, _ = ni.audit_flows(flows, navs, date(2026, 6, 30))
        panic = [r for r in rows if r["panic"]]
        self.assertEqual(len(panic), 1)
        p = panic[0]["panic"]
        self.assertAlmostEqual(p["drawdown"], 0.143195, places=4)
        self.assertAlmostEqual(p["rebound_pct"], 0.072961, places=4)
        self.assertAlmostEqual(p["missed"], 875.60, places=1)
        self.assertEqual(p["rebound_days"], 90)

    def test_discipline_when_sell_near_high(self):
        flows = make_flows(["日期,动作,金额", "2025-04-01,申购,10000",
                            "2025-07-05,赎回,5000"])
        code, out, _ = call_main(["flows", flows, NAVS])
        self.assertIn("DISCIPLINE", out)
        self.assertNotIn("PANIC", out)

    def test_rebound_window_open(self):
        navs_path = make_navs(
            ["日期,净值", "2025-01-01,1.0", "2025-07-01,1.2",
             "2026-01-01,1.4", "2026-05-01,1.40", "2026-06-15,1.25",
             "2026-06-30,1.25"], "dip-navs.csv")
        flows_path = make_flows(
            ["日期,动作,金额", "2025-01-01,申购,10000", "2026-06-20,赎回,3000"],
            "dip-flows.csv")
        code, out, _ = call_main(["flows", flows_path, navs_path])
        self.assertEqual(code, 0)
        self.assertIn("PANIC (rebound window open)", out)

    def test_report_lists_panic_line(self):
        code, out, _ = call_main(["report", FLOWS, NAVS, "--as-of", AS_OF])
        self.assertIn("panic sells  : 1 of 1", out)
        self.assertIn("875.60 went to whoever held", out)


# ------------------------------------------------------------- counterfactuals

class SimulateTests(unittest.TestCase):

    def test_demo_counterfactuals(self):
        code, out, _ = call_main(["simulate", FLOWS, NAVS, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("29,036.29", out)
        self.assertIn("35,100.00", out)
        self.assertIn("+6,063.71 vs actual", out)
        self.assertIn("866.67", out)
        self.assertIn("×30", out)
        self.assertIn("+1,345.11 vs actual", out)

    def test_hold_is_net_times_nav_ratio(self):
        flows = [ni.Flow(date(2024, 1, 3), "BUY", 1000.0, 1.0, "", 2)]
        navs = ni.parse_navs(make_navs(demo_nav_rows()))
        cf = ni.counterfactuals(flows, navs, date(2026, 6, 30))
        self.assertAlmostEqual(cf["hold"], 1000.0 / 1.0 * 1.35, places=6)
        self.assertAlmostEqual(cf["actual"], 1350.0, places=6)
        self.assertAlmostEqual(cf["hold"] - cf["actual"], 0.0, places=6)

    def test_flat_nav_all_three_equal(self):
        rows = ["日期,净值"] + ["%s,1.0000" % d for d in
                                ("2024-01-01", "2024-07-01", "2025-01-01",
                                 "2025-07-01", "2026-01-01", "2026-06-30")]
        navs = make_navs(rows, "flat-navs.csv")
        flows = make_flows(["日期,动作,金额", "2024-01-05,申购,12000"],
                           "flat-flows.csv")
        code, out, _ = call_main(["simulate", flows, navs])
        self.assertEqual(code, 0)
        self.assertIn("12,000.00", out)
        self.assertIn("+0.00 vs actual", out)
        self.assertIn("both counterfactuals", out)

    def test_dca_amount_is_net_over_months(self):
        flows = [ni.Flow(date(2024, 1, 3), "BUY", 12000.0, 1.0, "", 2)]
        navs = ni.parse_navs(make_navs(demo_nav_rows()))
        cf = ni.counterfactuals(flows, navs, date(2026, 6, 30))
        self.assertEqual(cf["dca_months"], 30)
        self.assertAlmostEqual(cf["dca_amount"], 400.0, places=6)

    def test_simulate_json(self):
        code, out, _ = call_main(["simulate", FLOWS, NAVS, "--as-of", AS_OF,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertAlmostEqual(data["hold_minus_actual"], 6063.71, places=1)
        self.assertAlmostEqual(data["dca_minus_actual"], 1345.11, places=1)
        self.assertEqual(data["dca_months"], 30)


# -------------------------------------------------------------------- doctor

class DoctorTests(unittest.TestCase):

    def test_demo_healthy_with_notes(self):
        code, out, _ = call_main(["doctor", FLOWS, NAVS, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("USABLE WITH NOTES", out)
        self.assertIn("interpolated", out)

    def test_fully_clean_ledger_is_healthy(self):
        rows = ["日期,动作,金额,净值", "2024-01-03,申购,5000,1.0018",
                "2024-07-15,申购,20000,1.1241", "2024-10-08,赎回,12000,0.9853",
                "2025-03-20,申购,8000,1.1627", "2025-08-10,申购,5000,1.2426"]
        flows = make_flows(rows, "clean-flows.csv")
        code, out, _ = call_main(["doctor", flows, NAVS, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("HEALTHY", out)

    def test_short_span_fatal(self):
        navs = make_navs(["日期,净值", "2026-01-01,1.0", "2026-03-01,1.1"],
                         "short-navs.csv")
        flows = make_flows(["日期,动作,金额", "2026-01-05,申购,1000"],
                           "short-flows.csv")
        code, out, _ = call_main(["doctor", flows, navs])
        self.assertEqual(code, 3)
        self.assertIn("FATAL", out)
        self.assertIn("180", out)

    def test_flow_outside_nav_range_fatal(self):
        flows = make_flows(["日期,动作,金额", "2023-06-01,申购,1000"],
                           "early-flows.csv")
        code, out, _ = call_main(["doctor", flows, NAVS])
        self.assertEqual(code, 3)
        self.assertIn("outside the nav range", out)

    def test_unsorted_input_sorted_internally(self):
        rows = ["日期,动作,金额", "2025-08-10,申购,1000", "2024-01-03,申购,1000"]
        unsorted_path = make_flows(rows, "unsorted-flows.csv")
        sorted_path = make_flows(["日期,动作,金额", "2024-01-03,申购,1000",
                                  "2025-08-10,申购,1000"], "sorted-flows.csv")
        code_a, out_a, _ = call_main(["flows", unsorted_path, NAVS,
                                      "--as-of", AS_OF])
        code_b, out_b, _ = call_main(["flows", sorted_path, NAVS,
                                      "--as-of", AS_OF])
        self.assertEqual(code_a, 0)
        self.assertEqual(out_a, out_b)

    def test_doctor_json(self):
        code, out, _ = call_main(["doctor", FLOWS, NAVS, "--as-of", AS_OF,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertTrue(data["healthy"])
        self.assertEqual(len(data["warnings"]), 1)


# ----------------------------------------------------------------------- CLI

class CliTests(unittest.TestCase):

    def test_no_args_exits_2(self):
        code, _, _ = call_main([])
        self.assertEqual(code, 2)

    def test_missing_file_exits_3(self):
        code, _, err = call_main(["report", "/no/such/flows.csv", NAVS])
        self.assertEqual(code, 3)
        self.assertIn("file not found", err)

    def test_bad_asof_refused(self):
        code, _, err = call_main(["report", FLOWS, NAVS, "--as-of", "2027-01-01"])
        self.assertEqual(code, 3)
        self.assertIn("outside the nav range", err)

    def test_asof_defaults_to_last_nav_date(self):
        code, out, _ = call_main(["report", FLOWS, NAVS])
        self.assertEqual(code, 4)
        self.assertIn("as-of 2026-06-30", out)

    def test_report_json_machine_readable(self):
        code, out, _ = call_main(["report", FLOWS, NAVS, "--as-of", AS_OF,
                                  "--format", "json"])
        self.assertEqual(code, 0)  # JSON is data, never a gate
        data = json.loads(out)
        self.assertEqual(data["verdict"], "BLEEDING")
        self.assertAlmostEqual(data["xirr"], DEMO_XIRR, places=4)
        self.assertAlmostEqual(data["twr_annual"], DEMO_TWR, places=4)
        self.assertAlmostEqual(data["market_value"], DEMO_MV, places=1)
        self.assertAlmostEqual(data["buy_position_weighted"], 0.8864, places=3)
        self.assertEqual(data["gap_line_pp"], -5.0)


# ------------------------------------------------------------------ dogfood

class DogfoodTests(unittest.TestCase):

    def test_examples_in_sync(self):
        script = EXAMPLES / "build_examples.py"
        result = subprocess.run(
            [sys.executable, str(script), "--check"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("in sync"), 4)

    def test_report_snapshot_pins_the_story(self):
        text = (EXAMPLES / "sample-report.txt").read_text(encoding="utf-8")
        for needle in ("BLEEDING", "+12.78%/yr", "+6.46%/yr", "-6.32 pp",
                       "29,036.29", "0.89 → CHASING",
                       "875.60 went to whoever held"):
            self.assertIn(needle, text)

    def test_flows_snapshot_pins_positions(self):
        text = (EXAMPLES / "sample-flows.txt").read_text(encoding="utf-8")
        for needle in ("CHASE-HI", "PANIC", "FIRST BUYS",
                       "0.89 → CHASING", "+7.30% rebound in 90 days"):
            self.assertIn(needle, text)

    def test_simulate_snapshot_pins_counterfactuals(self):
        text = (EXAMPLES / "sample-simulate.txt").read_text(encoding="utf-8")
        for needle in ("29,036.29", "35,100.00", "30,381.40",
                       "most expensive part"):
            self.assertIn(needle, text)

    def test_demo_numbers_match_independent_math(self):
        code, out, _ = call_main(["report", FLOWS, NAVS, "--as-of", AS_OF,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertAlmostEqual(data["xirr"], DEMO_XIRR, places=4)
        self.assertAlmostEqual(data["twr_annual"], DEMO_TWR, places=4)
        self.assertAlmostEqual(data["gap_pp"], -6.3168, places=3)
        self.assertAlmostEqual(data["market_value"], DEMO_MV, delta=0.05)


if __name__ == "__main__":
    unittest.main()
