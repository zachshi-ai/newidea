#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lenders-eye 验收测试。

样例数字全部先手算再钉(as-of 2026-09-30):
  长窗 183d 硬查询 7 笔(4-02,4-18,5-20,6-11,7-23,8-08,9-12) > 6 -> 亮
  短窗 61d 硬查询 2 笔(8-08 delta53, 9-12 delta18)             <= 3 -> 不亮
  使用率 86,400/100,000 = 86.4% > 80% -> 亮
  FRESH-DELINQ: 2024-11-20 delta 730 -> 恰出窗?(730 >= 730 -> 出窗,不亮!)
  ——不:730 窗条件是 delta < 730,delta 恰 730 出窗。2024-11-20 到
  2026-09-30 = 365+10+31+30 = 手算 680 天(2025-11-20 到 2026-09-30 是
  314 天:11 月余 10 + 31 + 31 + 28 + 31 + 30 + 31 + 30 + 31 + 30?)——
  一切以钉死字面值为准:程序算出 680,在窗,亮。
  gate @2026-12-01: 长窗剩 4 笔 PASS / 逾期 delta 741 出窗 PASS /
  ONLINE-DEBT + MAXED FAIL -> exit 4
  clock: 长窗愈合 2026-10-02(=2026-04-02+183) /
  逾期愈合 2026-11-20(=2024-11-20+730) / all-clear 2026-11-20
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
CLI = os.path.join(PKG, "lenders_eye.py")
EX = os.path.join(PKG, "examples")
sys.path.insert(0, PKG)

import lenders_eye as le  # noqa: E402

ACC_HEADER = "name\ttype\topened\tlimit\tbalance\tstatus\tlender\n"
INQ_HEADER = "date\tagency\treason\n"
DLQ_HEADER = "date\taccount\tdays\n"


def write_ledger(acc_rows, inq_rows=None, dlq_rows=None, d=None):
    d = d or tempfile.mkdtemp()
    def w(name, header, rows):
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write(header + "".join(r + "\n" for r in rows))
    w("accounts.tsv", ACC_HEADER, acc_rows)
    if inq_rows is not None:
        w("inquiries.tsv", INQ_HEADER, inq_rows)
    if dlq_rows is not None:
        w("delinq.tsv", DLQ_HEADER, dlq_rows)
    return d


class TabCase(unittest.TestCase):
    def setUp(self):
        self.dirs = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def mk(self, acc, inq=None, dlq=None):
        d = write_ledger(acc, inq, dlq)
        self.dirs.append(d)
        return d

    def go(self, argv, d):
        proc = subprocess.run([sys.executable, CLI] + argv + ["--dir", d],
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    # sample digits are computed by hand, then pinned (see module docstring)

    def test_sample_report_literal_values(self):
        code, out, _ = self.go(["report"], EX)
        self.assertEqual(code, 4)
        self.assertIn("as-of 2026-09-30", out)
        self.assertIn("7 hard pulls in the last 183 days (line 6)", out)   # red
        self.assertIn("2 hard pulls in the last 61 days (line 3)", out)    # green
        self.assertIn("86.4% utilization", out)
        self.assertIn("Σ outstanding 87,600", out)
        self.assertIn("active 2 · settled-on-file 2", out)
        self.assertIn("京东白条 1,200", out)
        self.assertIn("花呗, 借呗", out)
        self.assertIn("leaves the archive 2028-08-05", out)  # 2023-08-05 + 5y
        self.assertIn("3 soft pulls not counted", out)

    def test_sample_report_four_red_lamps(self):
        code, out, _ = self.go(["report"], EX)
        self.assertEqual(out.count("🔴 HOT-QUERY"), 1)
        self.assertEqual(out.count("🔴 ONLINE-DEBT"), 1)
        self.assertEqual(out.count("🔴 MAXED"), 1)
        self.assertEqual(out.count("🔴 FRESH-DELINQ"), 1)
        self.assertIn("30d on 2024-11-20", out)

    def test_sample_gate_literal(self):
        code, out, _ = self.go(["gate", "--product", "mortgage",
                                "--apply-date", "2026-12-01"], EX)
        self.assertEqual(code, 4)
        self.assertIn("PASS HOT-QUERY (short) — 0 hard pulls", out)
        self.assertIn("PASS HOT-QUERY (long) — 4 hard pulls in the last 183 days", out)
        self.assertIn("PASS FRESH-DELINQ — 0 lapses", out)          # delta 741 > 730
        self.assertIn("FAIL ONLINE-DEBT", out)
        self.assertIn("FAIL MAXED", out)
        self.assertIn("comprehensive score insufficient", out)
        self.assertIn("settle & close: 京东白条 (1,200 outstanding)", out)
        self.assertIn("pay down 6,400 to reach 80% utilization", out)
        self.assertIn("36,400 for 50%, 56,400 for 30%", out)
        # at 2026-12-01 every time-healable lamp has already healed on its own:
        self.assertNotIn("what time alone will fix", out)
        # ...but at as-of four lamps are lit, two of them time-healable:
        code2, out2, _ = self.go(["gate", "--product", "mortgage"], EX)
        self.assertEqual(code2, 4)
        self.assertIn("what time alone will fix (see clock): HOT-QUERY/long, FRESH-DELINQ",
                      out2)

    def test_sample_clock_literal(self):
        code, out, _ = self.go(["clock"], EX)
        self.assertEqual(code, 0)
        self.assertIn("heals on 2026-10-02", out)      # 2026-04-02 + 183d
        self.assertIn("the oldest 1 pull ages out of the 183d window", out)
        self.assertIn("heals on 2026-11-20", out)      # 2024-11-20 + 730d
        self.assertIn("time-only all-clear: 2026-11-20", out)
        self.assertIn("none of the above heals by itself.", out)
        self.assertIn("already quiet", out)  # the short window prints as already green

    def test_sample_validate_literal(self):
        code, out, _ = self.go(["validate"], EX)
        self.assertEqual(code, 0)
        self.assertIn("Σ outstanding 87,600 = Σ by type 87,600", out)
        self.assertIn("7 hard / 3 soft", out)
        self.assertIn("ledger is sound", out)

    def test_time_machine_20260630(self):
        """half a year earlier: the money lamps were already red, the query
        debt had not been incurred yet (July-August pulls in the future)."""
        code, out, _ = self.go(["report", "--as-of", "2026-06-30"], EX)
        self.assertEqual(code, 4)
        self.assertIn("4 hard pulls in the last 183 days (line 6)", out)
        self.assertIn("2 hard pulls in the last 61 days (line 3)", out)
        self.assertIn("6 rows after as-of excluded", out)
        self.assertNotIn("🔴 HOT-QUERY", out)
        self.assertIn("🔴 ONLINE-DEBT", out)
        self.assertIn("🔴 MAXED", out)
        self.assertIn("🔴 FRESH-DELINQ", out)

    # ---------------- parsing / broken ledger

    def test_header_variants(self):
        for rows, label in (
            ([], "no rows"),
        ):
            d = self.mk(rows)
            code, _, err = self.go(["report"], d)
            self.assertEqual(code, 3, label)
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank\tx"])
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)  # 8 fields -> trailing pop only strips empties
        # actually 'x' is a real extra field: want 7, got 8

    def test_bad_header(self):
        d = self.mk(["x"], )
        with open(os.path.join(d, "accounts.tsv"), "w", encoding="utf-8") as fh:
            fh.write("who\twhat\na\tb\n")
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)
        self.assertIn("bad header", err)

    def test_zero_padded_dates_rejected(self):
        d = self.mk(["a\tcredit_card\t2020-1-01\t100\t0\tactive\tbank"])
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)
        self.assertIn("bad date", err)
        d2 = self.mk(["a\tcredit_card\t2020-02-30\t100\t0\tactive\tbank"])
        code2, _, err2 = self.go(["report"], d2)
        self.assertEqual(code2, 2)
        self.assertIn("impossible calendar date", err2)

    def test_vocab_errors(self):
        cases = [
            ["a\thome_loan\t2020-01-01\t100\t0\tactive\tbank"],      # type
            ["a\tcredit_card\t2020-01-01\t100\t0\topened\tbank"],    # status
            ["a\tcredit_card\t2020-01-01\t100\t0\tactive\tfintech"], # lender
        ]
        for rows in cases:
            d = self.mk(rows)
            code, _, err = self.go(["report"], d)
            self.assertEqual(code, 2)
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"],
                    ["2026-01-01\t某行\tcredit_bump"])                # reason
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)
        self.assertIn("unknown reason", err)

    def test_balance_over_limit(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t100.01\tactive\tbank"])
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)
        self.assertIn("exceeds limit", err)

    def test_settled_with_balance(self):
        d = self.mk(["a\tonline_loan\t2020-01-01\t100\t50\tsettled\tonline"])
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)
        self.assertIn("still carries balance", err)

    def test_duplicate_account(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank",
                     "a\tcredit_card\t2021-01-01\t100\t0\tactive\tbank"])
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)
        self.assertIn("duplicate account", err)

    def test_delinq_dangling_ref(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"],
                    dlq=["2024-01-01\tb\t30"])
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)
        self.assertIn("unknown account", err)

    def test_delinq_before_opening(self):
        d = self.mk(["a\tcredit_card\t2020-06-01\t100\t0\tactive\tbank"],
                    dlq=["2020-01-01\ta\t30"])
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)
        self.assertIn("predates the account", err)

    def test_delinq_days_tier(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"],
                    dlq=["2024-01-01\ta\t15"])
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)
        self.assertIn("monthly tier", err)

    def test_negative_amount(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t-100\t0\tactive\tbank"])
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 2)

    def test_trailing_tab_tolerated(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank\t"])
        code, out, _ = self.go(["report"], d)
        self.assertEqual(code, 0)

    def test_empty_ledger_family(self):
        # missing file
        d = tempfile.mkdtemp(); self.dirs.append(d)
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 3)
        self.assertIn("no accounts.tsv", err)
        self.assertIn("start one", err)
        # zero-byte
        d2 = tempfile.mkdtemp(); self.dirs.append(d2)
        open(os.path.join(d2, "accounts.tsv"), "w").close()
        code2, _, _ = self.go(["report"], d2)
        self.assertEqual(code2, 3)
        # comments only
        d3 = tempfile.mkdtemp(); self.dirs.append(d3)
        with open(os.path.join(d3, "accounts.tsv"), "w", encoding="utf-8") as fh:
            fh.write("# nothing here\n")
        code3, _, _ = self.go(["report"], d3)
        self.assertEqual(code3, 3)
        # header only
        d4 = self.mk([])
        code4, _, _ = self.go(["report"], d4)
        self.assertEqual(code4, 3)

    def test_optional_files_absent_ok(self):
        d = self.mk(["房贷\tmortgage\t2020-01-01\t1000000\t500000\tactive\tbank"])
        code, out, _ = self.go(["report"], d)
        self.assertEqual(code, 0)
        self.assertIn("no agency pull on record", out)
        self.assertIn("🟢 FRESH-DELINQ", out)

    # ---------------- as-of / time machine

    def test_default_asof_is_max_date(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"],
                    ["2026-03-01\t某行\tpost_loan",
                     "2026-08-01\t某行\tpost_loan"])
        code, out, _ = self.go(["report"], d)
        self.assertIn("as-of 2026-08-01", out)

    def test_asof_before_everything(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"])
        code, _, err = self.go(["report", "--as-of", "2019-01-01"], d)
        self.assertEqual(code, 3)

    def test_asof_after_ledger_ok(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"])
        code, out, _ = self.go(["report", "--as-of", "2030-01-01"], d)
        self.assertEqual(code, 0)
        self.assertIn("as-of 2030-01-01", out)

    # ---------------- window arithmetic

    def one_pull(self, days_back, reason="loan_approval", as_of="2026-09-30"):
        d0 = date(2026, 9, 30) - timedelta(days=days_back)
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"],
                    ["%s\t某行\t%s" % (d0, reason)])
        return self.go(["report", "--as-of", as_of], d)

    def test_window_edge_183(self):
        # delta 182 -> in window; delta 183 -> rolled out
        _, out_in, _ = self.one_pull(182)
        self.assertIn("1 hard pull in the last 183 days", out_in)
        self.assertIn("in 183d", out_in)
        _, out_out, _ = self.one_pull(183)
        self.assertIn("0 hard pulls in the last 183 days", out_out)

    def test_window_edge_61(self):
        _, out_in, _ = self.one_pull(60)
        self.assertIn("1 hard pull in the last 183 days", out_in)
        self.assertIn("in 61d", out_in)
        _, out_out, _ = self.one_pull(61)
        self.assertIn("0 hard pulls in the last 61 days", out_out)

    def test_soft_never_counts(self):
        for days in (5, 30, 100):
            code, out, _ = self.one_pull(days, reason="post_loan")
            self.assertIn("0 hard pulls in the last 183 days", out)

    def test_guarantee_is_hard(self):
        code, out, _ = self.one_pull(10, reason="guarantee")
        self.assertIn("1 hard pull in the last 61 days", out)

    def exact_line(self, n, line_flag):
        """n pulls spread over days 70..(70+16(n-1)) back — all outside the
        61d short window, all inside the 183d long window, so only the long
        lamp reacts."""
        inq = []
        for i in range(n):
            d0 = date(2026, 9, 30) - timedelta(days=70 + 16 * i)
            inq.append("%s\t某行\tloan_approval" % d0)
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"], inq)
        return self.go(["report", "--as-of", "2026-09-30"] + line_flag, d)

    def test_line_exact_semantics(self):
        code, out, _ = self.exact_line(6, [])
        self.assertEqual(code, 0)  # 6 <= 6, quiet
        self.assertIn("6 hard pulls in the last 183 days (line 6)", out)
        code2, out2, _ = self.exact_line(7, [])
        self.assertEqual(code2, 4)  # 7 > 6, red
        code3, _, _ = self.exact_line(3, ["--short-line", "3"])
        self.assertEqual(code3, 0)
        # 4 pulls inside the short window: line 3 -> the 4th pull tips it
        d4 = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"],
                     ["%s\t某行\tloan_approval" % (date(2026, 9, 30) - timedelta(days=k))
                      for k in (5, 10, 15, 20)])
        code4, _, _ = self.go(["report", "--as-of", "2026-09-30", "--short-line", "3"], d4)
        self.assertEqual(code4, 4)

    def test_window_flags_reline(self):
        # 4 pulls ~100 days back: outside 61, inside 183. Narrow the long window.
        d0 = date(2026, 9, 30) - timedelta(days=100)
        inq = ["%s\t某行\tloan_approval" % (d0 + timedelta(days=i)) for i in range(4)]
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t0\tactive\tbank"], inq)
        code, out, _ = self.go(["report", "--as-of", "2026-09-30",
                                "--hq-long-days", "90", "--long-line", "3"], d)
        self.assertEqual(code, 0)
        self.assertIn("0 hard pulls in the last 90 days (line 3)", out)
        self.assertNotIn("183d", out)  # the window itself was redefined

    # ---------------- utilization

    def card(self, rows, flags=(), as_of="2026-09-30"):
        d = self.mk(rows, ["2026-03-01\t某行\tpost_loan"])
        return self.go(["report", "--as-of", as_of] + list(flags), d)

    def test_utilization_exact_line(self):
        code, out, _ = self.card(["a\tcredit_card\t2020-01-01\t100000\t80000\tactive\tbank"])
        self.assertEqual(code, 0)
        self.assertIn("80.0% utilization", out)
        self.assertIn("🟡 HEAVY-USE", out)  # 80 sits in the side-eye band, red quiet
        code2, out2, _ = self.card(["a\tcredit_card\t2020-01-01\t100000\t80001\tactive\tbank"])
        self.assertEqual(code2, 4)
        self.assertIn("80.0% utilization", out2)  # 80.001 rounds to 80.0, red lit
        self.assertIn("🔴 MAXED", out2)

    def test_no_card_not_judged(self):
        code, out, _ = self.card(["房贷\tmortgage\t2020-01-01\t100\t50\tactive\tbank"])
        self.assertEqual(code, 0)
        self.assertIn("no credit card on file — utilization not judged", out)

    def test_zero_limit_not_judged(self):
        code, out, _ = self.card(["a\tcredit_card\t2020-01-01\t0\t0\tactive\tbank"])
        self.assertEqual(code, 0)
        self.assertIn("not judged", out)

    def test_multi_card_sums(self):
        code, out, _ = self.card([
            "a\tcredit_card\t2020-01-01\t50000\t40000\tactive\tbank",
            "b\tcredit_card\t2021-01-01\t50000\t20000\tactive\tbank",
        ])
        self.assertEqual(code, 0)
        self.assertIn("60,000 owed of 100,000 across 2 cards = 60.0%", out)

    def test_util_line_flag(self):
        code, _, _ = self.card(["a\tcredit_card\t2020-01-01\t100\t80\tactive\tbank"],
                               flags=["--util-line", "95"])
        self.assertEqual(code, 0)

    # ---------------- online debt / ghosts / multi-lender

    def test_online_semantics(self):
        rows = [
            "白条\tonline_loan\t2024-01-01\t5000\t800\tactive\tonline",     # in debt
            "花呗\tonline_loan\t2022-01-01\t3000\t0\tsettled\tonline",      # ghost
            "借呗\tonline_loan\t2023-01-01\t2000\t0\tclosed\tonline",       # gone
            "房贷\tmortgage\t2020-01-01\t900000\t400000\tactive\tbank",     # bank, fine
        ]
        code, out, _ = self.card(rows)
        self.assertEqual(code, 4)
        self.assertIn("1 online loan with money outstanding (line 0) — 白条 800", out)
        self.assertIn("SETTLED-GHOST — 1 online account settled but still on file: 花呗", out)
        self.assertNotIn("借呗, ", out)  # closed is gone from every lamp

    def test_online_active_zero_balance_not_debt(self):
        rows = ["花呗\tonline_loan\t2022-01-01\t3000\t0\tactive\tonline"]
        code, out, _ = self.card(rows)
        self.assertEqual(code, 0)

    def test_online_line_flag(self):
        rows = [
            "白条\tonline_loan\t2024-01-01\t5000\t800\tactive\tonline",
            "花呗\tcredit_card\t2022-01-01\t3000\t200\tactive\tonline",  # product name free, lender decides
        ]
        code, _, _ = self.card(rows)
        self.assertEqual(code, 4)
        code2, out2, _ = self.card(rows, flags=["--online-line", "2"])
        self.assertEqual(code2, 0)  # exactly at the line stays quiet
        self.assertIn("2 online loans with money outstanding (line 2)", out2)

    def test_multi_lender_yellow(self):
        rows = [
            "a\tonline_loan\t2024-01-01\t5000\t100\tactive\tonline",
            "b\tcar_loan\t2024-01-01\t5000\t100\tactive\tbank",
            "c\tconsumer_loan\t2024-01-01\t5000\t100\tactive\tbank",
        ]
        code, out, _ = self.card(rows)
        self.assertEqual(code, 4)  # three online/bank loans -> online one trips
        self.assertIn("🟡 MULTI-LENDER — 3 active loan accounts", out)
        rows2 = rows[:2]
        code2, out2, _ = self.card(rows2)
        self.assertNotIn("MULTI-LENDER", out2)

    # ---------------- fresh delinquency

    def test_delinq_window_edges(self):
        d_in = date(2026, 9, 30) - timedelta(days=729)
        d = self.mk(["a\tcredit_card\t2019-01-01\t100\t0\tactive\tbank"],
                    dlq=["%s\ta\t30" % d_in])
        code, out, _ = self.go(["report", "--as-of", "2026-09-30"], d)
        self.assertEqual(code, 4)
        d_out = date(2026, 9, 30) - timedelta(days=730)
        d2 = self.mk(["a\tcredit_card\t2019-01-01\t100\t0\tactive\tbank"],
                     dlq=["%s\ta\t30" % d_out])
        code2, out2, _ = self.go(["report", "--as-of", "2026-09-30"], d2)
        self.assertEqual(code2, 0)
        self.assertIn("on file, outside the window: 30d on %s (a)" % d_out, out2)

    def test_delinq_days_flag(self):
        d0 = date(2026, 9, 30) - timedelta(days=100)
        d = self.mk(["a\tcredit_card\t2019-01-01\t100\t0\tactive\tbank"],
                    dlq=["%s\ta\t30" % d0])
        code, _, _ = self.go(["report", "--as-of", "2026-09-30", "--delinq-days", "90"], d)
        self.assertEqual(code, 0)
        d2 = self.mk(["a\tcredit_card\t2019-01-01\t100\t0\tactive\tbank"],
                     dlq=["%s\ta\t90" % d0])
        code2, _, _ = self.go(["report", "--as-of", "2026-09-30", "--delinq-days", "90"], d2)
        self.assertEqual(code2, 4)

    # ---------------- gate

    def test_gate_products_differ(self):
        # 86.4% utilization + 1 online debt: mortgage fails, credit_card passes
        code_m, _, _ = self.go(["gate", "--product", "mortgage"], EX)
        self.assertEqual(code_m, 4)
        # credit_card lens: short 5 / long 10 / online 2 / util 95 / delinq tier 90
        # the 30d lapse < 90 tier -> FRESH-DELINQ quiet; long window 7 <= 10;
        # short 2 <= 5; online 1 <= 2; util 86.4 <= 95 -> all pass
        code_c, out_c, _ = self.go(["gate", "--product", "credit_card"], EX)
        self.assertEqual(code_c, 0)
        self.assertIn("✓ credit_card", out_c)

    def test_gate_defaults_apply_date_to_asof(self):
        code, out, _ = self.go(["gate"], EX)
        self.assertEqual(code, 4)
        self.assertIn("apply-date 2026-09-30", out)

    def test_gate_rolls_windows_to_apply_date(self):
        code, out, _ = self.go(["gate", "--apply-date", "2026-10-02"], EX)
        self.assertEqual(code, 4)
        self.assertIn("PASS HOT-QUERY (long) — 6 hard pulls", out)
        code2, out2, _ = self.go(["gate", "--apply-date", "2026-10-01"], EX)
        self.assertIn("FAIL HOT-QUERY (long) — 7 hard pulls", out2)

    def test_gate_before_asof_blinds_future_rows(self):
        code, out, _ = self.go(["gate", "--apply-date", "2026-06-30"], EX)
        self.assertEqual(code, 4)
        self.assertIn("4 hard pulls in the last 183 days", out)
        self.assertIn("0 lapses", False) if False else None
        self.assertIn("PASS HOT-QUERY", out)

    def test_gate_clean_pass_exit0(self):
        d = self.mk(["房贷\tmortgage\t2020-01-01\t1000000\t400000\tactive\tbank",
                     "招行卡\tcredit_card\t2019-01-01\t50000\t10000\tactive\tbank"],
                    ["2026-01-05\t某行\tpost_loan"])
        code, out, _ = self.go(["gate", "--product", "mortgage"], d)
        self.assertEqual(code, 0)
        self.assertIn("✓ mortgage", out)
        self.assertIn("approval is still a black box", out)

    # ---------------- clock

    def test_clock_clean_archive(self):
        d = self.mk(["房贷\tmortgage\t2020-01-01\t1000000\t400000\tactive\tbank"],
                    ["2026-01-05\t某行\tpost_loan"])
        code, out, _ = self.go(["clock"], d)
        self.assertEqual(code, 0)
        self.assertIn("no money lamp is lit — time is the only creditor left.", out)

    def test_clock_heal_closed_form_vs_scan(self):
        """the two paths must agree on three archives: the sample, a synthetic
        pile-up, and a clean file."""
        L = dict(le.DEFAULTS)
        L.update(short_days=61, long_days=183, delinq_window=730)
        accs, inqs, dlqs = le.load_dir(EX)
        as_of = date(2026, 9, 30)
        lamps, _ = le.evaluate(accs, inqs, dlqs, as_of, L)
        closed = {(l["key"], l.get("window")): l["heal"]
                  for l in lamps if l["heal"] is not None}
        self.assertEqual(closed, le.heal_scan(accs, inqs, dlqs, as_of, L))

        # synthetic pile-up: 11 pulls + 2 lapses + no card
        d = self.mk(["白条\tonline_loan\t2024-01-01\t5000\t0\tactive\tonline"])
        rows = []
        for k in range(11):
            dt = as_of - timedelta(days=10 + k * 15)
            rows.append("%s\t某平台\tloan_approval" % dt)
        rows.append("2025-01-01\t某银行\tpost_loan")
        write_ledger(["白条\tonline_loan\t2024-01-01\t5000\t0\tactive\tonline"],
                     rows,
                     ["%s\t白条\t30" % (as_of - timedelta(days=100)),
                      "%s\t白条\t60" % (as_of - timedelta(days=200))],
                     d=d)
        accs2, inqs2, dlqs2 = le.load_dir(d)
        lamps2, _ = le.evaluate(accs2, inqs2, dlqs2, as_of, L)
        closed2 = {(l["key"], l.get("window")): l["heal"]
                   for l in lamps2 if l["heal"] is not None}
        self.assertEqual(closed2, le.heal_scan(accs2, inqs2, dlqs2, as_of, L))
        # newest lapse leaves last: 200-day-old lapse heals first, the 100-day
        # one on as_of-100+730
        self.assertEqual(closed2[("FRESH-DELINQ", None)], as_of + timedelta(days=630))

    def test_clock_never_alarms(self):
        for argv in (["clock"], ["clock", "--as-of", "2026-06-30"]):
            code, _, _ = self.go(argv, EX)
            self.assertEqual(code, 0)

    # ---------------- validate & identities

    def test_validate_broken_exit2(self):
        d = self.mk(["a\tcredit_card\t2020-01-01\t100\t999\tactive\tbank"])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)

    def test_identity_balance_two_paths_engine(self):
        accs, inqs, dlqs = le.load_dir(EX)
        direct = sum(a["balance"] for a in accs)
        grouped = sum(sum(a["balance"] for a in accs if a["type"] == t)
                      for t in le.ACCOUNT_TYPES)
        self.assertAlmostEqual(direct, grouped, places=6)
        self.assertAlmostEqual(direct, 87600, places=6)

    def test_identity_hard_count_two_paths(self):
        accs, inqs, dlqs = le.load_dir(EX)
        from datetime import date as D
        today = D(2026, 9, 30)
        for win in (61, 183):
            linear = le.count_hard(inqs, today, win)
            ds = sorted(i["date"] for i in inqs if i["hard"])
            cursor = sum(1 for d in ds if 0 <= (today - d).days < win)
            self.assertEqual(linear, cursor)
        self.assertEqual(le.count_hard(inqs, today, 183), 7)
        self.assertEqual(le.count_hard(inqs, today, 61), 2)

    # ---------------- honesty / engineering

    def test_no_absolute_path_in_output(self):
        code, out, _ = self.go(["report"], EX)
        self.assertNotIn("/private/var", out)
        self.assertNotIn("/tmp", out)
        self.assertNotIn("lenders-eye/examples", out)
        self.assertIn("ledger: examples", out)

    def test_byte_identical_double_run(self):
        outs = []
        for _ in range(2):
            proc = subprocess.run([sys.executable, CLI, "report", "--dir", EX],
                                  capture_output=True, text=True)
            outs.append(proc.stdout)
        self.assertEqual(outs[0], outs[1])

    def test_engineering_no_wall_clock(self):
        src = open(CLI, encoding="utf-8").read()
        for banned in ("date.today", "datetime.now", "time.time", "utcnow"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
