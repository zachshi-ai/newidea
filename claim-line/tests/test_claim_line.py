# -*- coding: utf-8 -*-
"""报险线 · Claim Line 验收测试。

数值真值（自费线、隐身保费、恢复期路径）按 NCD 表手工推演后以字面量钉死，
CLI 输出必须复现它们；行为真值（exit code / verdict 词）钉死在子进程断言里。
两条核心恒等式——两世界必平、边际可加——用独立构造的路径求和对拍。

Exit codes: 0 绿 · 2 账本损坏 · 3 薄账/挂起 · 4 红灯（CASH / OVERCLAIM）。
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
IDEA = os.path.dirname(HERE)
CLI = os.path.join(IDEA, "claim_line.py")
EXAMPLES = os.path.join(IDEA, "examples")
POLICIES = os.path.join(EXAMPLES, "policies.tsv")
CLAIMS = os.path.join(EXAMPLES, "claims.tsv")

_spec = importlib.util.spec_from_file_location("claim_line", CLI)
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)


def go(*args):
    """跑 CLI 子进程，返回 (stdout, stderr, exit_code)。"""
    proc = subprocess.run(
        [sys.executable, CLI] + list(args),
        capture_output=True, text=True)
    return proc.stdout, proc.stderr, proc.returncode


SUR = cl.DEFAULT_NCD_SUR
DIS = cl.DEFAULT_NCD_DIS
NCD = cl.SurDis(SUR, DIS, "NCD")
CTP = cl.SurDis(cl.DEFAULT_CTP_SUR, cl.DEFAULT_CTP_DIS, "CTP")

SAMPLE_POLICIES = [
    {"start": date(2023, 9, 15), "premium": 4200.0, "ncd": 0.70, "note": ""},
    {"start": date(2024, 9, 15), "premium": 6000.0, "ncd": None, "note": ""},
    {"start": date(2025, 9, 15), "premium": 5100.0, "ncd": None, "note": ""},
]
SAMPLE_CLAIMS = [
    {"date": date(2024, 6, 3), "fault": "mine", "channel": "own",
     "cost": 600.0, "note": ""},
    {"date": date(2025, 1, 20), "fault": "other", "channel": "other",
     "cost": 2300.0, "note": ""},
    {"date": date(2026, 3, 11), "fault": "mine", "channel": "own",
     "cost": 12000.0, "note": ""},
]


def write_ledger(tmp, policies, claims):
    ppath = os.path.join(tmp, "policies.tsv")
    cpath = os.path.join(tmp, "claims.tsv")
    with open(ppath, "w", encoding="utf-8") as fh:
        fh.write("start\tpremium\tncd\tnote\n")
        for p in policies:
            fh.write("{}\t{}\t{}\t{}\n".format(
                p["start"].isoformat(), fmt_num(p["premium"]),
                "" if p["ncd"] is None else p["ncd"], p.get("note", "")))
    with open(cpath, "w", encoding="utf-8") as fh:
        fh.write("date\tfault\tchannel\tcost\tnote\n")
        for c in claims:
            fh.write("{}\t{}\t{}\t{}\t{}\n".format(
                c["date"].isoformat(), c["fault"], c["channel"],
                fmt_num(c["cost"]), c.get("note", "")))
    return ppath, cpath


def fmt_num(v):
    return str(int(v)) if float(v) == int(v) else str(v)


# ---------------------------------------------------------------- tables

class TestTables(unittest.TestCase):
    def test_surcharge_ladder(self):
        self.assertEqual(NCD.lookup(0, 1), 1.00)
        self.assertEqual(NCD.lookup(0, 2), 1.25)
        self.assertEqual(NCD.lookup(0, 3), 1.50)
        self.assertEqual(NCD.lookup(0, 4), 1.75)
        self.assertEqual(NCD.lookup(0, 5), 2.00)
        self.assertEqual(NCD.lookup(0, 6), 2.00)      # 封顶

    def test_discount_ladder(self):
        self.assertEqual(NCD.lookup(0, 0), 0.85)      # 出险次年，连无赔 1
        self.assertEqual(NCD.lookup(1, 0), 0.70)
        self.assertEqual(NCD.lookup(2, 0), 0.60)
        self.assertEqual(NCD.lookup(3, 0), 0.50)
        self.assertEqual(NCD.lookup(9, 0), 0.50)      # 封顶

    def test_rollover(self):
        self.assertEqual(NCD.rollover((2, 0)), (3, 0))
        self.assertEqual(NCD.rollover((2, 1)), (0, 0))   # 出险断 streak
        self.assertEqual(NCD.rollover((4, 0)), (4, 0))   # 封顶

    def test_reverse_mapping(self):
        """系数 → 续保时点状态（claims = 上年 own 赔案数）。"""
        self.assertEqual(NCD.reverse(1.00), (0, 1))   # sur 表首档
        self.assertEqual(NCD.reverse(1.25), (0, 2))
        self.assertEqual(NCD.reverse(1.50), (0, 3))
        self.assertEqual(NCD.reverse(1.75), (0, 4))
        self.assertEqual(NCD.reverse(2.00), (0, 5))
        self.assertEqual(NCD.reverse(0.85), (1, 0))
        self.assertEqual(NCD.reverse(0.70), (2, 0))
        self.assertEqual(NCD.reverse(0.60), (3, 0))
        self.assertEqual(NCD.reverse(0.50), (4, 0))   # 封顶语义

    def test_anchor_reproduces_next_renewal(self):
        """锚定语义自洽：锚 0.70（连无赔 2）→ 干净走一年续保 = 0.60。"""
        clean = NCD.reverse(0.70)[0]
        self.assertEqual(NCD.lookup(clean, 0), 0.60)
        clean = NCD.reverse(0.85)[0]
        self.assertEqual(NCD.lookup(clean, 0), 0.70)

    def test_reverse_rejects_off_table(self):
        with self.assertRaises(cl.LedgerError):
            NCD.reverse(0.92)

    def test_table_monotonicity_enforced(self):
        with self.assertRaises(cl.LedgerError):
            cl.SurDis((1.0, 1.0, 1.5, 1.75, 2.0), DIS)
        with self.assertRaises(cl.LedgerError):
            cl.SurDis(SUR, (0.85, 0.85, 0.60, 0.50))


# ---------------------------------------------------------------- the line

class TestTheLine(unittest.TestCase):
    """自费线 = Σ(报险路径 − 无赔路径) × 基准；手工推演钉值。"""

    def test_first_claim_burns_the_discount(self):
        bill, diffs, horizon = NCD.hidden_bill((2, 0), 6000)
        self.assertAlmostEqual(bill, 6300.0, places=6)
        self.assertEqual([round(d, 9) for d in diffs],
                         [0.40, 0.35, 0.20, 0.10])
        self.assertEqual(horizon, 4)

    def test_deeper_position_costs_more(self):
        # 连无赔 3：下一档就是地板 0.50，烧掉的更多
        bill, diffs, _ = NCD.hidden_bill((3, 0), 6000)
        self.assertAlmostEqual(bill, 6900.0, places=6)
        self.assertEqual([round(d, 9) for d in diffs],
                         [0.50, 0.35, 0.20, 0.10])

    def test_subsequent_claims_are_flat_surtax(self):
        for state in ((1, 1), (0, 2), (0, 3), (0, 4)):
            bill, diffs, horizon = NCD.hidden_bill(state, 6000)
            self.assertAlmostEqual(bill, 1500.0, places=6, msg=str(state))
            self.assertEqual([round(d, 9) for d in diffs], [0.25])
            self.assertEqual(horizon, 1)

    def test_sixth_claim_in_a_year_is_free(self):
        # 出险满 5 次已在 2.0 封顶：第 6 笔的边际隐身保费 = 0
        bill, diffs, _ = NCD.hidden_bill((0, 5), 6000)
        self.assertEqual(bill, 0.0)
        self.assertEqual(diffs, [])

    def test_second_claim_after_recovery_is_pricier(self):
        # 等一年再报：从 (0,0) 出发，折扣重新攒起来了，全价翻倍
        bill, _, _ = NCD.hidden_bill((0, 0), 6000)
        self.assertAlmostEqual(bill, 3000.0, places=6)
        self.assertGreater(bill, 1500.0)

    def test_trailing_zero_trimmed(self):
        _, diffs, _ = NCD.hidden_bill((3, 0), 6000)
        self.assertNotAlmostEqual(diffs[-1], 0.0)

    def test_two_worlds_meet_at_the_line(self):
        """两世界必平：维修费恰 = 自费线时，报险总账 ≡ 自掏总账。"""
        for state in ((2, 0), (1, 1), (3, 0), (0, 0)):
            base = 6000.0
            bill, _, hz = NCD.hidden_bill(state, base)
            claim = sum(base * n for n in NCD.project((state[0], state[1] + 1), hz))
            clean = sum(base * n for n in NCD.project(state, hz))
            self.assertAlmostEqual(claim - clean, bill, places=6,
                                   msg=str(state))

    def test_line_flips_the_winner(self):
        """线下一分钱自掏赢，线上一分钱报险赢——自费线真的是线。"""
        state, base = (2, 0), 6000.0
        line, _, hz = NCD.hidden_bill(state, base)
        claim = sum(base * n for n in NCD.project((state[0], state[1] + 1), hz))
        clean = sum(base * n for n in NCD.project(state, hz))
        self.assertLess(line - 0.01 + clean, claim)     # cost 略低于线
        self.assertGreater(line + 0.01 + clean, claim)  # 略高于线就翻转

    def test_marginals_telescope(self):
        """边际可加：连报 4 笔的边际之和 = 两路径直接作差（钉到 1e-6）。"""
        base, st, total = 6000.0, (2, 0), 0.0
        for _ in range(4):
            total += NCD.hidden_bill(st, base)[0]
            st = (st[0], st[1] + 1)
        clean = NCD.project((2, 0), cl.RECOVERY_CAP)
        claim = NCD.project((2, 4), cl.RECOVERY_CAP)
        direct = sum((a - b) * base for a, b in zip(claim, clean))
        self.assertAlmostEqual(total, direct, places=6)

    def test_ctp_small_price(self):
        bill, diffs, _ = CTP.hidden_bill((3, 0), 950.0)
        self.assertAlmostEqual(bill, 570.0, places=6)   # 0.30+0.20+0.10 × 950
        self.assertEqual([round(d, 9) for d in diffs], [0.30, 0.20, 0.10])


# ---------------------------------------------------------------- replay

class TestReplay(unittest.TestCase):
    def test_anchor_from_ncd_column(self):
        years = cl.walk(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD)
        self.assertAlmostEqual(years[0]["ncd"], 0.70)
        self.assertAlmostEqual(years[0]["base"], 6000.0)

    def test_replayed_ncd_from_claims(self):
        years = cl.walk(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD)
        # 2023-24 年 1 笔 own → 2024 续保 sur[1] = 1.00；2024-25 无赔 → 0.85
        self.assertAlmostEqual(years[1]["ncd"], 1.00)
        self.assertAlmostEqual(years[2]["ncd"], 0.85)

    def test_clean_world_ignores_own_claims(self):
        clean = cl.walk(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD, with_own=False)
        self.assertAlmostEqual(clean[1]["ncd"], 0.60)   # 连无赔 3
        self.assertAlmostEqual(clean[2]["ncd"], 0.50)   # 连无赔 4 地板

    def test_not_at_fault_never_enters_the_ledger(self):
        claims = [c for c in SAMPLE_CLAIMS if c["channel"] == "own"]
        years_all = cl.walk(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD)
        years_own = cl.walk(SAMPLE_POLICIES, claims, NCD)
        for a, b in zip(years_all, years_own):
            self.assertAlmostEqual(a["ncd"], b["ncd"])

    def test_new_policy_anchor_defaults_to_100(self):
        policies = [{"start": date(2025, 1, 10), "premium": 5000.0,
                     "ncd": None, "note": ""}]
        years = cl.walk(policies, [], NCD)
        self.assertAlmostEqual(years[0]["ncd"], 1.00)

    def test_current_state_at_ledger_end(self):
        state, idx = cl.current_state(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD,
                                      date(2026, 3, 11))
        self.assertEqual(state, (1, 1))
        self.assertEqual(idx, 2)

    def test_current_state_mid_year(self):
        state, idx = cl.current_state(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD,
                                      date(2025, 9, 20))
        self.assertEqual(state, (1, 0))
        self.assertEqual(idx, 2)

    def test_claim_state_before(self):
        state, idx = cl.claim_state_before(SAMPLE_POLICIES, SAMPLE_CLAIMS,
                                           NCD, 0)
        self.assertEqual(state, (2, 0))
        self.assertEqual(idx, 0)
        state, idx = cl.claim_state_before(SAMPLE_POLICIES, SAMPLE_CLAIMS,
                                           NCD, 2)
        self.assertEqual(state, (1, 0))
        self.assertEqual(idx, 2)

    def test_full_prices_on_sample(self):
        prices = cl.full_prices(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD,
                                date(2026, 3, 11))
        self.assertAlmostEqual(prices[0]["bill"], 6300.0, places=6)
        self.assertAlmostEqual(prices[1]["bill"], 5100.0, places=6)

    def test_realized_plus_tail_equals_sum_of_full_prices(self):
        """费用守恒：已付隐身 + 恢复期尾款 = Σ 逐笔全价（基准一致时）。"""
        years = cl.walk(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD)
        clean = cl.walk(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD, with_own=False)
        realized, _ = cl.realized_hidden(years, clean)
        state, idx = cl.current_state(SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD,
                                      date(2026, 3, 11))
        tail, _ = cl.tail_bill(NCD, years[idx]["base"], SAMPLE_POLICIES,
                               state, idx)
        full = sum(p["bill"] for p in cl.full_prices(
            SAMPLE_POLICIES, SAMPLE_CLAIMS, NCD, date(2026, 3, 11)))
        self.assertAlmostEqual(realized + tail, full, places=6)


# ---------------------------------------------------------------- sample CLI

class TestSampleLedger(unittest.TestCase):
    """示例账本的钉值：三个保单年、两笔 own（一笔冤案一笔值回）、
    一笔无责免费修。所有数字手工推演过。"""

    def test_report_exit4_overclaim(self):
        out, err, code = go("report", POLICIES, CLAIMS)
        self.assertEqual(code, 4)
        self.assertIn("OVERCLAIM", out)
        self.assertIn("6,300.00", out)
        self.assertIn("10.50x", out)

    def test_report_pricing_table(self):
        out, _, _ = go("report", POLICIES, CLAIMS)
        self.assertIn("2024-06-03", out)
        self.assertIn("连无赔2·本年0", out)
        self.assertIn("5,100.00", out)          # 12000 大修的全价
        self.assertIn("0.42x", out)
        self.assertIn("不占赔款次数", out)        # 2300 无责免费修

    def test_report_realized_totals(self):
        out, _, _ = go("report", POLICIES, CLAIMS)
        self.assertIn("实缴保费 15,300.00", out)
        self.assertIn("无赔世界 10,800.00", out)
        self.assertIn("已付隐身 4,500.00", out)
        self.assertIn("恢复期尾款 6,900.00", out)

    def test_report_current_line(self):
        out, _, _ = go("report", POLICIES, CLAIMS)
        self.assertIn("连无赔1 · 本年own赔案1", out)
        self.assertIn("1,500.00（0.25 × 基准 6,000.00）", out)
        self.assertIn("3,000.00", out)          # 等一年翻倍

    def test_report_marginal_table(self):
        out, _, _ = go("report", POLICIES, CLAIMS)
        self.assertIn("第 1 笔：1,500.00（累计 1,500.00）", out)
        self.assertIn("第 3 笔：1,500.00（累计 4,500.00）", out)

    def test_renewal_projection(self):
        out, _, code = go("renewal", POLICIES, CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("2026-09-15", out)
        self.assertIn("NCD 1.00 → 保费预估 6,000.00", out)
        self.assertIn("多付 1,800.00", out)
        self.assertIn("NCD-BURN", out)
        self.assertIn("← 2026-03-11 12,000.00", out)

    def test_renewal_roadmap_rejoins(self):
        out, _, _ = go("renewal", POLICIES, CLAIMS)
        self.assertIn("2030-09-15 续保：0.50（3,000.00）", out)
        self.assertIn("与从未出险重合", out)

    def test_simulate_never_claim(self):
        out, _, code = go("simulate", "never-claim", "--policies", POLICIES,
                          "--claims", CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("已付隐身 4,500.00", out)
        self.assertIn("12,600.00", out)         # 600 + 12000 维修现金
        self.assertIn("8,100.00", out)          # 12600 - 4500

    def test_simulate_claim_worth_it(self):
        out, _, code = go("simulate", "claim", "12000",
                          "--policies", POLICIES, "--claims", CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("报险便宜 10,500.00", out)

    def test_simulate_cash_saves_300(self):
        out, _, code = go("simulate", "cash", "1200",
                          "--policies", POLICIES, "--claims", CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("自掏便宜 300.00", out)     # 线 1500 - cost 1200

    def test_simulate_ctp_three_paths(self):
        out, _, code = go("simulate", "ctp", "1200", "--target", "other",
                          "--policies", POLICIES, "--claims", CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("交强 6,570.00 · 自掏 7,200.00 · 商业险 7,500.00", out)
        self.assertIn("最便宜：CTP", out)

    def test_simulate_ctp_rejects_own_car(self):
        _, err, code = go("simulate", "ctp", "1200", "--target", "own",
                          "--policies", POLICIES, "--claims", CLAIMS)
        self.assertEqual(code, 2)

    def test_validate_all_green(self):
        out, _, code = go("validate", POLICIES, CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("体检通过", out)
        self.assertIn("两世界必平", out)
        self.assertIn("边际可加", out)
        self.assertIn("已付隐身 4,500.00（0.00e+00）", out)
        self.assertIn("一致 ✓", out)


# ---------------------------------------------------------------- decide

class TestDecide(unittest.TestCase):
    """裁决法庭：五种活法、exit code、掷币带、免赔额、手动模式。"""

    def test_cash_red_light(self):
        out, _, code = go("decide", "1200", "--policies", POLICIES,
                          "--claims", CLAIMS)
        self.assertEqual(code, 4)
        self.assertIn("裁决 CASH", out)
        self.assertIn("1.25x", out)

    def test_claim_green(self):
        out, _, code = go("decide", "1800", "--policies", POLICIES,
                          "--claims", CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("裁决 CLAIM", out)

    def test_tie_band(self):
        out, _, code = go("decide", "1550", "--policies", POLICIES,
                          "--claims", CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("裁决 TIE", out)

    def test_band_edges(self):
        _, _, lo = go("decide", "1349", "--policies", POLICIES,
                      "--claims", CLAIMS)
        _, _, mid_lo = go("decide", "1350", "--policies", POLICIES,
                          "--claims", CLAIMS)
        _, _, mid_hi = go("decide", "1650", "--policies", POLICIES,
                          "--claims", CLAIMS)
        _, _, hi = go("decide", "1651", "--policies", POLICIES,
                      "--claims", CLAIMS)
        self.assertEqual(lo, 4)
        self.assertEqual(mid_lo, 0)
        self.assertEqual(mid_hi, 0)
        self.assertEqual(hi, 0)

    def test_not_at_fault_is_others(self):
        out, _, code = go("decide", "9800", "--fault", "other",
                          "--policies", POLICIES, "--claims", CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("OTHERS", out)
        self.assertIn("代位追偿", out)

    def test_ctp_cheapest_for_small_third_party_damage(self):
        out, _, code = go("decide", "1200", "--target", "other",
                          "--policies", POLICIES, "--claims", CLAIMS)
        self.assertEqual(code, 0)
        self.assertIn("裁决 CTP", out)
        self.assertIn("570.00", out)

    def test_tiny_damage_cash_beats_ctp(self):
        out, _, code = go("decide", "300", "--target", "other",
                          "--policies", POLICIES, "--claims", CLAIMS)
        self.assertEqual(code, 4)
        self.assertIn("裁决 CASH", out)

    def test_deductible_raises_the_line(self):
        # 线 1500：无免赔 1600 → CLAIM；免赔 500 → 实际线 2000 → CASH
        _, _, plain = go("decide", "1600", "--policies", POLICIES,
                         "--claims", CLAIMS)
        out, _, ded = go("decide", "1600", "--deductible", "500",
                         "--policies", POLICIES, "--claims", CLAIMS)
        self.assertEqual(plain, 0)
        self.assertEqual(ded, 4)
        self.assertIn("实际线 2,000.00", out)

    def test_manual_mode_no_ledger(self):
        out, _, code = go("decide", "5000", "--base", "6000",
                          "--clean", "3", "--claims-ytd", "0")
        self.assertEqual(code, 4)
        self.assertIn("裁决 CASH", out)
        self.assertIn("6,900.00", out)

    def test_manual_mode_hint_without_base(self):
        _, err, code = go("decide", "1200")
        self.assertEqual(code, 3)
        self.assertIn("--base", err)

    def test_manual_deep_discount_line(self):
        out, _, code = go("decide", "8000", "--base", "6000",
                          "--clean", "3", "--claims-ytd", "0")
        self.assertEqual(code, 0)
        self.assertIn("自费线 = 6,900.00", out)
        self.assertIn("裁决 CLAIM", out)


# ---------------------------------------------------------------- ledger

class TestLedgerErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def feed(self, policies, claims):
        return write_ledger(self.tmp.name, policies, claims)

    def test_bad_header_exit2(self):
        ppath, cpath = self.feed(SAMPLE_POLICIES, SAMPLE_CLAIMS)
        with open(ppath, "w", encoding="utf-8") as fh:
            fh.write("start\tamount\tncd\tnote\n")
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_unknown_channel_exit2(self):
        bad = SAMPLE_CLAIMS + [{"date": date(2025, 5, 1), "fault": "mine",
                                "channel": "friend", "cost": 100.0}]
        ppath, cpath = self.feed(SAMPLE_POLICIES, bad)
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_unknown_fault_exit2(self):
        bad = SAMPLE_CLAIMS + [{"date": date(2025, 5, 1), "fault": "both",
                                "channel": "own", "cost": 100.0}]
        ppath, cpath = self.feed(SAMPLE_POLICIES, bad)
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_nonpositive_cost_exit2(self):
        bad = SAMPLE_CLAIMS + [{"date": date(2025, 5, 1), "fault": "mine",
                                "channel": "own", "cost": 0}]
        ppath, cpath = self.feed(SAMPLE_POLICIES, bad)
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_bad_date_exit2(self):
        ppath, cpath = self.feed(SAMPLE_POLICIES, SAMPLE_CLAIMS)
        with open(ppath, encoding="utf-8") as fh:
            body = fh.read().replace("2024-09-15", "2024/09/15")
        with open(ppath, "w", encoding="utf-8") as fh:
            fh.write(body)
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_claim_before_first_policy_exit2(self):
        bad = [{"date": date(2023, 1, 5), "fault": "mine", "channel": "own",
                "cost": 500.0}] + SAMPLE_CLAIMS
        ppath, cpath = self.feed(SAMPLE_POLICIES, bad)
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_claim_beyond_last_year_exit2(self):
        bad = SAMPLE_CLAIMS + [{"date": date(2026, 10, 1), "fault": "mine",
                                "channel": "own", "cost": 500.0}]
        ppath, cpath = self.feed(SAMPLE_POLICIES, bad)
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_claim_after_asof_is_truncated_not_error(self):
        """--as-of 是截断语义：账针拨回 2026-01-01，3 月的大险不可见；
        600 冤案仍在场 → exit 4。"""
        out, _, code = go("report", "--as-of", "2026-01-01", POLICIES, CLAIMS)
        self.assertEqual(code, 4)
        self.assertIn("as-of 2026-01-01", out)
        self.assertNotIn("12,000.00", out)      # 定价单里没有它
        self.assertIn("连无赔1 · 本年own赔案0", out)

    def test_policy_gap_too_short_exit2(self):
        policies = [SAMPLE_POLICIES[0],
                    {"start": date(2024, 3, 1), "premium": 6000.0,
                     "ncd": None, "note": ""}]
        ppath, cpath = self.feed(policies, [])
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_policy_gap_too_long_exit2(self):
        policies = [SAMPLE_POLICIES[0],
                    {"start": date(2025, 3, 1), "premium": 6000.0,
                     "ncd": None, "note": ""}]
        ppath, cpath = self.feed(policies, [])
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_ncd_off_table_exit2(self):
        policies = [{"start": date(2023, 9, 15), "premium": 4200.0,
                     "ncd": 0.92, "note": ""}]
        ppath, cpath = self.feed(policies, [])
        _, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 2)

    def test_thin_report_exit3(self):
        policies = [{"start": date(2025, 1, 10), "premium": 5000.0,
                     "ncd": 0.85, "note": "新保后首个续保年"}]
        claims = [{"date": date(2025, 6, 1), "fault": "mine",
                   "channel": "own", "cost": 800.0, "note": "小蹭"}]
        ppath, cpath = self.feed(policies, claims)
        out, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 3)
        self.assertIn("DECLINE", out)
        # 基准 5000/0.85 = 5882.35，(1,0) 全价 0.85 × 5882.35 = 5000 → 6.25x
        self.assertIn("6.25x", out)

    def test_clean_life_exit0(self):
        ppath, cpath = self.feed(SAMPLE_POLICIES, [])
        out, _, code = go("report", ppath, cpath)
        self.assertEqual(code, 0)
        self.assertIn("没有 own 赔案", out)


# ---------------------------------------------------------------- hygiene

class TestHygiene(unittest.TestCase):
    def test_byte_reproducible(self):
        a = go("report", POLICIES, CLAIMS)[0]
        b = go("report", POLICIES, CLAIMS)[0]
        self.assertEqual(a, b)

    def test_report_prints_basename_only(self):
        out, _, _ = go("report", POLICIES, CLAIMS)
        self.assertIn("policies.tsv", out)
        self.assertNotIn("examples", out)

    def test_asof_pin_changes_state(self):
        # as-of 回看：状态与自费线按当时点重算；600 冤案在场 → exit 4
        out, _, code = go("report", "--as-of", "2025-09-20", POLICIES, CLAIMS)
        self.assertEqual(code, 4)
        self.assertIn("as-of 2025-09-20", out)
        self.assertIn("连无赔1 · 本年own赔案0", out)
        # (1,0) 的自费线 = (1.0−0.7)+(0.85−0.6)+(0.7−0.5)+(0.6−0.5) × 6000
        self.assertIn("5,100.00（0.30+0.25+0.20+0.10 × 基准 6,000.00）", out)

    def test_ratio_percent_dual_form(self):
        self.assertEqual(cl.parse_ratio("70%", "ncd"), 0.70)
        self.assertEqual(cl.parse_ratio("0.70", "ncd"), 0.70)

    def test_add_years_leap_safe(self):
        self.assertEqual(cl.add_years(date(2024, 2, 29), 1),
                         date(2025, 2, 28))
        self.assertEqual(cl.add_years(date(2023, 9, 15), 1),
                         date(2024, 9, 15))

    def test_missing_file_exit2(self):
        _, err, code = go("report", "nope.tsv", "nope2.tsv")
        self.assertEqual(code, 2)
        self.assertIn("nope.tsv", err)


# ---------------------------------------------------------------- disclose

class TestDisclosure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_ncd_column_mismatch_is_surfaced(self):
        """保单列说 0.85、出险史说 1.00：保单永远赢，但账要亮出来。"""
        policies = [
            SAMPLE_POLICIES[0],
            {"start": date(2024, 9, 15), "premium": 5100.0, "ncd": 0.85,
             "note": ""},
            SAMPLE_POLICIES[2],
        ]
        ppath, cpath = write_ledger(self.tmp.name, policies, SAMPLE_CLAIMS)
        out, _, code = go("validate", ppath, cpath)
        self.assertEqual(code, 0)
        self.assertIn("保单列 0.85 vs 重放 1.00", out)

    def test_wild_base_banner(self):
        """隐含基准 6000 → 7000：保费变动不只来自 NCD，横幅点名。"""
        policies = [
            SAMPLE_POLICIES[0],
            {"start": date(2024, 9, 15), "premium": 7000.0, "ncd": None,
             "note": ""},
        ]
        ppath, cpath = write_ledger(self.tmp.name, policies, SAMPLE_CLAIMS[:1])
        out, _, code = go("validate", ppath, cpath)
        self.assertEqual(code, 0)
        self.assertIn("WILD-BASE", out)

    def test_custom_ncd_table(self):
        """整表覆盖：把地板改成 0.55，(2,0) 的自费线随之变化——先验可调。"""
        out, _, code = go("decide", "4000", "--base", "6000",
                          "--clean", "2", "--claims-ytd", "0",
                          "--ncd-dis", "0.85,0.70,0.60,0.55")
        self.assertEqual(code, 4)
        # 0.40+0.30+0.15+0.05 = 0.90 × 6000 = 5400，4000 < 5400−band
        self.assertIn("自费线 = 5,400.00", out)
        self.assertIn("裁决 CASH", out)


if __name__ == "__main__":
    unittest.main()
