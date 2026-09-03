#!/usr/bin/env python3
"""Acceptance tests for 求职漏斗 · Job Funnel.

Every acceptance criterion in README.md is a test here. Synthetic
ledgers are written to temp dirs; the dogfood suite regenerates the
committed examples and byte-compares them.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import job_funnel as jf  # noqa: E402

AS_OF = date(2025, 12, 1)


def run_main(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = jf.main(argv)
    return code, out.getvalue()


class LedgerTestCase(unittest.TestCase):
    def write_ledger(self, text):
        tmp = tempfile.mkdtemp(prefix="jobfunnel-test-")
        path = os.path.join(tmp, "ledger.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(lambda: None)  # temp dirs are left to the OS
        return path

    def ledger_path(self, rows, header="applied,company,role,channel,outcome,replied"):
        return self.write_ledger(header + "\n" + "\n".join(rows) + "\n")


class ParserTests(LedgerTestCase):
    def test_minimal_three_columns(self):
        path = self.ledger_path(
            ["2025-10-01,Acme,board"],
            header="applied,company,channel")
        rows = jf.read_ledger(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "pending")
        self.assertEqual(rows[0]["role"], "")

    def test_chinese_header_aliases(self):
        path = self.ledger_path(
            ["2025-10-01,极光云,后端工程师,内推,面试,2025-10-05"],
            header="投递日,公司,职位,渠道,状态,回复日")
        rows = jf.read_ledger(path)
        self.assertEqual(rows[0]["company"], "极光云")
        self.assertEqual(rows[0]["channel"], "内推")
        self.assertEqual(rows[0]["outcome"], "interview")

    def test_bom_and_blank_lines(self):
        path = self.write_ledger(
            "\ufeffapplied,company,role,channel,outcome,replied\n"
            "\n"
            "2025-10-01,Acme,Backend,board,rejected,\n"
            "\n")
        self.assertEqual(len(jf.read_ledger(path)), 1)

    def test_date_formats(self):
        rows = jf.read_ledger(self.ledger_path([
            "2025/10/01,A,_,x,,", "2025.10.02,B,_,x,,",
            "2025年10月3日,C,_,x,,", "20251004,D,_,x,,",
        ]))
        self.assertEqual([r["applied"] for r in rows],
                         [date(2025, 10, d) for d in (1, 2, 3, 4)])

    def test_outcome_aliases_and_default(self):
        rows = jf.read_ledger(self.ledger_path([
            "2025-10-01,A,_,x,拒,,", "2025-10-01,B,_,x,面试,,",
            "2025-10-01,C,_,x,录用,,", "2025-10-01,D,_,x,撤回,,",
            "2025-10-01,E,_,x,,", "2025-10-01,F,_,x,waiting,,",
        ]))
        self.assertEqual([r["outcome"] for r in rows],
                         ["rejected", "interview", "offer", "withdrawn",
                          "pending", "pending"])

    def test_unknown_outcome_reports_line(self):
        path = self.ledger_path([
            "2025-10-01,A,_,x,rejected,",
            "2025-10-02,B,_,x,ghosted,",
        ])
        with self.assertRaises(jf.ParseError) as ctx:
            jf.read_ledger(path)
        self.assertIn("line 3", str(ctx.exception))
        self.assertIn("ghosted", str(ctx.exception))

    def test_replied_before_applied_reports_line(self):
        path = self.ledger_path(["2025-10-05,A,_,x,response,2025-10-01"])
        with self.assertRaises(jf.ParseError) as ctx:
            jf.read_ledger(path)
        self.assertIn("line 2", str(ctx.exception))
        self.assertIn("before", str(ctx.exception))

    def test_empty_company_reports_line(self):
        path = self.ledger_path(["2025-10-05,,_,x,rejected,"])
        with self.assertRaises(jf.ParseError) as ctx:
            jf.read_ledger(path)
        self.assertIn("company is empty", str(ctx.exception))

    def test_empty_channel_reports_line(self):
        path = self.ledger_path(["2025-10-05,Acme,_,,rejected,"])
        with self.assertRaises(jf.ParseError) as ctx:
            jf.read_ledger(path)
        self.assertIn("channel is empty", str(ctx.exception))

    def test_no_header_error(self):
        path = self.ledger_path(["2025-10-05,Acme,_,board,rejected,"],
                                header="day,firm,what,src,result,back")
        with self.assertRaises(jf.ParseError) as ctx:
            jf.read_ledger(path)
        self.assertIn("no header row found", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(jf.ParseError):
            jf.read_ledger("/nonexistent/jobfunnel-ledger.csv")


class WilsonTests(unittest.TestCase):
    def test_zero_successes_is_zero(self):
        self.assertEqual(jf.wilson_lb(0, 12), 0.0)
        self.assertEqual(jf.wilson_lb(0, 0), 0.0)

    def test_known_values(self):
        self.assertAlmostEqual(jf.wilson_lb(6, 12), 0.2538, places=3)
        self.assertAlmostEqual(jf.wilson_lb(1, 6), 0.0300, places=3)
        self.assertAlmostEqual(jf.wilson_lb(8, 10), 0.4902, places=3)

    def test_lower_bound_is_below_raw_rate(self):
        for k, n in ((6, 12), (14, 55), (2, 3)):
            self.assertLess(jf.wilson_lb(k, n), k / float(n))

    def test_more_successes_never_lower_bound(self):
        for n in (8, 30, 200):
            self.assertGreaterEqual(jf.wilson_lb(4, n), jf.wilson_lb(2, n))

    def test_same_ratio_bigger_sample_tighter_bound(self):
        # 40/80 and 4/8 are both 50%, but only the big sample can prove it
        self.assertGreater(jf.wilson_lb(40, 80), jf.wilson_lb(4, 8))

    def test_percentile_nearest_rank(self):
        values = [1, 2, 2, 3, 3, 3, 4, 4, 5, 6, 6, 7, 7, 7, 8, 9, 10,
                  12, 14, 17, 19, 23]
        self.assertEqual(jf.percentile_nearest_rank(values, 0.9), 17)
        self.assertEqual(jf.percentile_nearest_rank([5], 0.9), 5)


class FunnelTests(LedgerTestCase):
    def made_ledger(self):
        return self.ledger_path([
            # 10 decided: 5 silent rejects, 2 responses, 2 interviews, 1 offer
            "2025-09-01,A,_,board,rejected,",
            "2025-09-02,B,_,board,rejected,",
            "2025-09-03,C,_,board,rejected,",
            "2025-09-04,D,_,board,rejected,",
            "2025-09-05,E,_,board,rejected,",
            "2025-09-06,F,_,board,response,2025-09-10",
            "2025-09-07,G,_,board,response,2025-09-12",
            "2025-09-08,H,_,referral,interview,2025-09-12",
            "2025-09-09,I,_,referral,interview,2025-09-13",
            "2025-09-10,J,_,referral,offer,2025-09-14",
            # not in the funnel denominators
            "2025-09-11,K,_,board,pending,",
            "2025-09-12,L,_,board,withdrawn,",
        ])

    def test_counts_exclude_pending_and_withdrawn(self):
        report = jf.funnel_report(jf.read_ledger(self.made_ledger()))
        self.assertEqual(report["total"], 12)
        self.assertEqual(report["decided"], 10)
        self.assertEqual(report["pending"], 1)
        self.assertEqual(report["withdrawn"], 1)
        self.assertEqual([s["passes"] for s in report["stages"]],
                         [5, 3, 1])
        self.assertEqual(report["offers"], 1)

    def test_rates(self):
        report = jf.funnel_report(jf.read_ledger(self.made_ledger()))
        self.assertAlmostEqual(report["stages"][0]["rate"], 0.5)
        self.assertAlmostEqual(report["stages"][1]["rate"], 0.6)
        self.assertAlmostEqual(report["stages"][2]["rate"], 1 / 3.0)

    def test_leak_is_lowest_lower_bound(self):
        report = jf.funnel_report(jf.read_ledger(self.made_ledger()))
        self.assertIsNotNone(report["leak"])
        proven = [s for s in report["stages"] if not s["thin"]]
        floor = min(s["lb"] for s in proven)
        self.assertAlmostEqual(report["leak"]["lb"], floor)

    def test_thin_stage_never_becomes_leak(self):
        # at min-n=4 the thin stage 3 owns the lowest bound of all (n=3),
        # yet the leak must come from the proven stages instead
        report = jf.funnel_report(jf.read_ledger(self.made_ledger()), min_n=4)
        self.assertIsNotNone(report["leak"])
        self.assertFalse(report["leak"]["thin"])
        self.assertEqual((report["leak"]["from"], report["leak"]["to"]),
                         ("response", "interview"))

    def test_thin_tagging(self):
        report = jf.funnel_report(jf.read_ledger(self.made_ledger()), min_n=10)
        # stage n: 10, 5, 3 -> only the first clears min-n=10
        self.assertEqual([s["thin"] for s in report["stages"]],
                         [False, True, True])
        report = jf.funnel_report(jf.read_ledger(self.made_ledger()), min_n=4)
        self.assertEqual([s["thin"] for s in report["stages"]],
                         [False, False, True])

    def test_sample_starvation(self):
        report = jf.funnel_report(jf.read_ledger(self.made_ledger()), min_n=11)
        self.assertTrue(report["starving"])
        self.assertIsNone(report["leak"])

    def test_empty_decided(self):
        rows = jf.read_ledger(self.ledger_path([
            "2025-10-01,A,_,board,pending,",
            "2025-10-02,B,_,board,withdrawn,",
        ]))
        report = jf.funnel_report(rows)
        self.assertTrue(report["starving"])
        self.assertIsNone(report["leak"])
        self.assertEqual(report["decided"], 0)

    def test_json_payload(self):
        code, out = run_main(["funnel", self.made_ledger(),
                              "--as-of", "2025-12-01", "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["decided"], 10)
        self.assertEqual(payload["pending"], 1)
        self.assertEqual(len(payload["stages"]), 3)
        self.assertEqual(payload["leak"]["from"], "applied")


class ChannelTests(LedgerTestCase):
    def made_ledger(self):
        return self.ledger_path([
            # referral: 5 applications, 3 responses — proven (n>=4)
            "2025-09-01,R1,_,referral,response,2025-09-05",
            "2025-09-02,R2,_,referral,response,2025-09-06",
            "2025-09-03,R3,_,referral,response,2025-09-07",
            "2025-09-04,R4,_,referral,rejected,",
            "2025-09-05,R5,_,referral,rejected,",
            # board: 9 applications, 1 response — big but weak
            "2025-09-01,B1,_,board,response,2025-09-30",
            "2025-09-02,B2,_,board,rejected,",
            "2025-09-03,B3,_,board,rejected,",
            "2025-09-04,B4,_,board,rejected,",
            "2025-09-05,B5,_,board,rejected,",
            "2025-09-06,B6,_,board,rejected,",
            "2025-09-07,B7,_,board,rejected,",
            "2025-09-08,B8,_,board,rejected,",
            "2025-09-09,B9,_,board,rejected,",
            # recruiter: 2 lucky responses — thin, must not be proven best
            "2025-09-01,C1,_,recruiter,response,2025-09-02",
            "2025-09-02,C2,_,recruiter,response,2025-09-03",
            # pending/withdrawn still count as attempts in n
            "2025-09-10,P1,_,board,pending,",
            "2025-09-11,W1,_,board,withdrawn,",
        ])

    def test_grouping_and_counts(self):
        report = jf.channels_report(jf.read_ledger(self.made_ledger()))
        by_name = {r["channel"]: r for r in report["rows"]}
        self.assertEqual(by_name["referral"]["n"], 5)
        self.assertEqual(by_name["referral"]["success"], 3)
        # 9 closed + 1 pending + 1 withdrawn: attempts, not just closes
        self.assertEqual(by_name["board"]["n"], 11)
        self.assertEqual(by_name["board"]["success"], 1)
        self.assertEqual(by_name["board"]["pending"], 1)

    def test_thin_channel_tops_table_but_not_proven(self):
        # at min-n=5: recruiter (2/2) has the highest bound and tops the
        # table but is thin — the proven best is referral, the strongest
        # sample that can actually prove something
        report = jf.channels_report(jf.read_ledger(self.made_ledger()),
                                    min_n=5)
        self.assertEqual(report["rows"][0]["channel"], "recruiter")
        self.assertTrue(report["rows"][0]["thin"])
        self.assertEqual(report["proven_best"]["channel"], "referral")

    def test_proven_best_skips_thin(self):
        report = jf.channels_report(jf.read_ledger(self.made_ledger()), min_n=4)
        self.assertEqual(report["proven_best"]["channel"], "referral")
        thin = {r["channel"] for r in report["rows"] if r["thin"]}
        self.assertIn("recruiter", thin)

    def test_endpoint_switching(self):
        rows = jf.read_ledger(self.made_ledger())
        resp = {r["channel"]: r for r in
                jf.channels_report(rows, "response")["rows"]}
        offer = {r["channel"]: r for r in
                 jf.channels_report(rows, "offer")["rows"]}
        self.assertEqual(resp["referral"]["success"], 3)
        self.assertEqual(offer["referral"]["success"], 0)

    def test_effort_champion_and_mismatch(self):
        report = jf.channels_report(jf.read_ledger(self.made_ledger()), min_n=4)
        self.assertEqual(report["effort_champ"]["channel"], "board")
        self.assertEqual(report["proven_best"]["channel"], "referral")
        code, out = run_main(["channels", self.made_ledger(), "--min-n", "4",
                              "--as-of", "2025-12-01"])
        self.assertEqual(code, 0)
        self.assertIn("effort champion : board", out)
        self.assertIn("proven champion : referral", out)
        self.assertIn("mismatch", out)

    def test_champions_aligned(self):
        # referral is both the biggest bet and the proven best
        rows = self.ledger_path(
            ["2025-09-01,R%d,_,referral,%s,2025-09-05" % (i, outcome)
             for i, outcome in enumerate(
                 ["offer", "response", "response", "rejected", "rejected",
                  "rejected", "rejected", "rejected", "rejected",
                  "rejected"], start=1)]
            + ["2025-09-0%d,B%d,_,board,rejected," % (i, i)
               for i in range(1, 6)])
        code, out = run_main(["channels", rows, "--as-of", "2025-12-01"])
        self.assertEqual(code, 0)
        self.assertIn("champions aligned", out)

    def test_no_proven_channel(self):
        rows = self.ledger_path([
            "2025-09-01,A,_,board,rejected,",
            "2025-09-02,B,_,referral,pending,",
        ])
        code, out = run_main(["channels", rows, "--as-of", "2025-12-01"])
        self.assertEqual(code, 0)
        self.assertIn("proven champion : none yet", out)

    def test_json_payload(self):
        code, out = run_main(["channels", self.made_ledger(), "--min-n", "5",
                              "--as-of", "2025-12-01", "--format", "json"])
        payload = json.loads(out)
        self.assertEqual(payload["endpoint"], "response")
        self.assertEqual(payload["proven_champion"]["channel"], "referral")
        self.assertEqual(payload["effort_champion"]["channel"], "board")


class AgingTests(LedgerTestCase):
    def made_ledger(self):
        # 5 answered applications set the P90 line at 30d:
        # latencies 2,3,5,7,30 -> ceil(0.9*5)=5th value = 30
        return self.ledger_path([
            "2025-09-01,A1,_,board,response,2025-09-03",
            "2025-09-02,A2,_,board,response,2025-09-05",
            "2025-09-03,A3,_,board,response,2025-09-08",
            "2025-09-04,A4,_,board,response,2025-09-11",
            "2025-09-05,A5,_,board,rejected,2025-10-05",
            # pending: age == deadline is alive, age == deadline+1 is expired
            "2025-10-31,Old1,_,board,pending,",   # age 31 -> expired
            "2025-10-26,Old2,_,board,pending,",   # age 36 -> expired
            "2025-11-01,Edge,_,board,pending,",   # age 30 -> alive
            "2025-11-05,Young,_,board,pending,",  # age 26 -> alive
        ])

    def test_deadline_from_own_latencies(self):
        report = jf.aging_report(jf.read_ledger(self.made_ledger()), AS_OF)
        self.assertEqual(report["deadline"], 30)
        self.assertFalse(report["borrowed"])
        self.assertEqual(report["samples"], 5)

    def test_fallback_deadline_is_borrowed(self):
        rows = self.ledger_path([
            "2025-09-01,A,_,board,response,2025-09-05",
            "2025-10-01,P,_,board,pending,",
        ])
        report = jf.aging_report(jf.read_ledger(rows), AS_OF)
        self.assertEqual(report["deadline"], jf.DEFAULT_DEADLINE)
        self.assertTrue(report["borrowed"])

    def test_boundary_age_is_alive_strictly_past_is_expired(self):
        report = jf.aging_report(jf.read_ledger(self.made_ledger()), AS_OF)
        by_company = {x["row"]["company"]: x for x in report["rows"]}
        self.assertFalse(by_company["Edge"]["expired"])   # exactly 30d
        self.assertTrue(by_company["Old1"]["expired"])    # 31d
        self.assertEqual(report["expired"], 2)
        self.assertEqual(report["alive"], 2)

    def test_sorted_by_age_desc(self):
        report = jf.aging_report(jf.read_ledger(self.made_ledger()), AS_OF)
        ages = [x["age"] for x in report["rows"]]
        self.assertEqual(ages, sorted(ages, reverse=True))

    def test_rate_recalc_when_expired_closed(self):
        report = jf.aging_report(jf.read_ledger(self.made_ledger()), AS_OF)
        # 4 responses / 5 decided = 80%; +2 expired as dead -> 4/7
        self.assertAlmostEqual(report["rate_before"], 0.8)
        self.assertAlmostEqual(report["rate_after"], 4 / 7.0)

    def test_exit_code_4_when_expired(self):
        code, out = run_main(["aging", self.made_ledger(),
                              "--as-of", "2025-12-01"])
        self.assertEqual(code, 4)
        self.assertIn("gate: ACTION", out)
        self.assertIn("80.0% -> 57.1%", out)

    def test_exit_code_0_when_all_alive(self):
        rows = self.ledger_path([
            "2025-09-01,A,_,board,response,2025-09-05",
            "2025-12-20,P,_,board,pending,",
        ])
        code, out = run_main(["aging", rows, "--as-of", "2025-12-21"])
        self.assertEqual(code, 0)
        self.assertIn("gate: CLEAR", out)

    def test_aging_output_mentions_origin_of_deadline(self):
        code, out = run_main(["aging", self.made_ledger(),
                              "--as-of", "2025-12-01"])
        self.assertIn("P90 of 5 applications", out)
        rows = self.ledger_path([
            "2025-09-01,A,_,board,response,2025-09-05",
            "2025-10-01,P,_,board,pending,",
        ])
        code, out = run_main(["aging", rows, "--as-of", "2025-12-01"])
        self.assertIn("borrowed default", out)

    def test_json_payload(self):
        code, out = run_main(["aging", self.made_ledger(), "--as-of",
                              "2025-12-01", "--format", "json"])
        payload = json.loads(out)
        self.assertEqual(payload["deadline_days"], 30)
        self.assertEqual(payload["expired"], 2)
        self.assertAlmostEqual(payload["response_rate_if_closed"]["after"],
                               0.5714, places=3)


class ShowTests(LedgerTestCase):
    def made_ledger(self):
        return self.ledger_path([
            "2025-10-01,Acme,Backend Engineer,referral,response,2025-10-06",
            "2025-10-02,Acme,Staff Engineer,board,rejected,",
            "2025-10-03,Beta LLC,Backend Engineer,board,pending,",
            "2025-09-01,A1,_,board,response,2025-09-03",
            "2025-09-02,A2,_,board,response,2025-09-05",
            "2025-09-03,A3,_,board,response,2025-09-08",
            "2025-09-04,A4,_,board,response,2025-09-11",
            "2025-09-05,A5,_,board,rejected,2025-10-05",
        ])

    def test_unique_substring_match(self):
        code, out = run_main(["show", self.made_ledger(), "Acme Backend",
                              "--as-of", "2025-12-01"])
        self.assertEqual(code, 0)
        self.assertIn("Acme · Backend Engineer", out)
        self.assertIn("first reply 2025-10-06 (5d", out)

    def test_exact_company_of_one(self):
        code, out = run_main(["show", self.made_ledger(), "Beta LLC",
                              "--as-of", "2025-12-01"])
        self.assertEqual(code, 0)
        self.assertIn("pending", out)

    def test_pending_show_reports_waiting_verdict(self):
        code, out = run_main(["show", self.made_ledger(), "Beta LLC",
                              "--as-of", "2026-01-15"])  # age 104 > 30
        self.assertIn("EXPIRED", out)
        self.assertIn("statistically already dead", out)

    def test_pending_inside_the_line_is_alive(self):
        code, out = run_main(["show", self.made_ledger(), "Beta LLC",
                              "--as-of", "2025-10-20"])  # age 17 <= 30
        self.assertIn("alive —", out)

    def test_channel_snapshot_line(self):
        code, out = run_main(["show", self.made_ledger(), "Acme Backend",
                              "--as-of", "2025-12-01"])
        self.assertIn("referral · 1 application, 100.0% response", out)

    def test_ambiguous_query_exit_3(self):
        code, out = run_main(["show", self.made_ledger(), "Acme",
                              "--as-of", "2025-12-01"])
        self.assertEqual(code, 3)

    def test_no_match_exit_3(self):
        code, out = run_main(["show", self.made_ledger(), "Nowhere Inc",
                              "--as-of", "2025-12-01"])
        self.assertEqual(code, 3)

    def test_redact_hashes_company(self):
        code, out = run_main(["show", self.made_ledger(), "Acme Backend",
                              "--as-of", "2025-12-01", "--redact"])
        self.assertNotIn("Acme", out)
        self.assertIn("anon-", out)


class CliTests(LedgerTestCase):
    SMALL = ("applied,company,role,channel,outcome,replied\n"
             "2025-10-01,Acme,Backend,board,response,2025-10-06\n")

    def test_no_args_exit_2(self):
        code, out = run_main([])
        self.assertEqual(code, 2)

    def test_bad_as_of_exit_3(self):
        code, out = run_main(["funnel", self.write_ledger(self.SMALL),
                              "--as-of", "not-a-date"])
        self.assertEqual(code, 3)

    def test_as_of_defaults_to_today(self):
        code, out = run_main(["funnel", self.write_ledger(self.SMALL)])
        self.assertEqual(code, 0)
        self.assertIn(date.today().isoformat(), out)

    def test_redact_on_aging_table(self):
        # the funnel table names no companies at all — nothing to redact
        rows = self.ledger_path([
            "2025-10-01,SecretCorp,_,board,rejected,",
            "2025-10-02,SecretCorp,_,board,rejected,",
            "2025-10-03,SecretCorp,_,board,rejected,",
        ])
        code, out = run_main(["funnel", rows, "--as-of", "2025-12-01"])
        self.assertNotIn("SecretCorp", out)
        code, out = run_main(["aging", self.ledger_path([
            "2025-11-01,SecretCorp,_,board,pending,",
            "2025-09-01,A,_,board,response,2025-09-05",
            "2025-09-02,B,_,board,response,2025-09-05",
            "2025-09-03,C,_,board,response,2025-09-05",
            "2025-09-04,D,_,board,response,2025-09-05",
            "2025-09-05,E,_,board,response,2025-09-05",
        ]), "--as-of", "2025-12-01", "--redact"])
        self.assertNotIn("SecretCorp", out)
        self.assertIn("anon-", out)

    def test_subprocess_exit_codes(self):
        path = self.ledger_path([
            "2025-11-01,SecretCorp,_,board,pending,",
            "2025-09-01,A,_,board,response,2025-09-05",
            "2025-09-02,B,_,board,response,2025-09-05",
            "2025-09-03,C,_,board,response,2025-09-05",
            "2025-09-04,D,_,board,response,2025-09-05",
            "2025-09-05,E,_,board,response,2025-09-05",
        ])
        aging = subprocess.run(
            [sys.executable, str(ROOT / "job_funnel.py"), "aging", path,
             "--as-of", "2025-12-01"],
            capture_output=True, text=True)
        self.assertEqual(aging.returncode, 4)
        missing = subprocess.run(
            [sys.executable, str(ROOT / "job_funnel.py"), "funnel",
             "/nonexistent/ledger.csv"],
            capture_output=True, text=True)
        self.assertEqual(missing.returncode, 3)


class DogfoodTests(unittest.TestCase):
    def test_examples_rebuild_byte_identical(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "examples" / "build_examples.py"),
             "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("examples in sync", proc.stdout)

    def test_sample_funnel_tells_the_story(self):
        text = (ROOT / "examples" / "sample-funnel.txt").read_text("utf-8")
        self.assertIn("69 applications · 55 decided · 12 pending · "
                      "2 withdrawn · 1 offer", text)
        self.assertIn("applied -> response       55      14    25.5%",
                      text)
        self.assertIn("<- weakest proven stage", text)
        self.assertIn("(n=6 < 10)", text)

    def test_committed_ledger_cross_check(self):
        ledger = jf.read_ledger(str(ROOT / "examples" / "applications.csv"))
        self.assertEqual(len(ledger), 69)
        report = jf.funnel_report(ledger)
        self.assertEqual(report["decided"], 55)
        self.assertEqual(report["offers"], 1)
        aging = jf.aging_report(ledger, AS_OF)
        self.assertEqual((aging["deadline"], aging["expired"], aging["alive"]),
                         (17, 7, 5))


if __name__ == "__main__":
    unittest.main()
