#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""card-tax acceptance tests.

Every headline number is hand-computed first and pinned here; if the CLI
disagrees with arithmetic done on paper, the test wins.

Demo ledger, as-of 2026-06-30 (the ledger's own anchor):

  yuedong  悦动健身年卡  pay 3650  2025-09-01..2026-08-31  time card
           units = 52 weeks x 1/week = 52; 11 visits
           rate 11/52 = 21.15% · tax 3650 - 11x90 = 2660
           gaps median 10.5 -> cliff line max(21, 45) = 45
           silence 140d (2026-02-10) -> cliff; rate < 50% -> DEAD
           pace window 2026-05-06..06-30: 0 visits -> pace 0.00
           62 days left -> +0 projected -> evaporation 41x90 = 3690
           per-redeemed 3650/11 = 331.82 · breakeven 3650/90 = 40.56
  jingjing 菁菁英语课包  pay 4000  20 units  list 260  no expiry
           9 visits: rate 45.0% · tax 4000 - 9x260 = 1660 -> DEAD
           silence 94d > max(14,45) -> cliff
  xingge   型格理发卡    pay 1000  10 units  list 78  no expiry
           7 visits: rate 70.0% · tax 1000 - 7x78 = 454 -> ON TRACK
           gaps all ~28 -> cliff line 56; silence 0
  fresh    轻醒瑜伽次卡  pay 680   10 units  list 68  bought 2026-06-20
           1 visit: tax 612; held 10 days < 28 -> THIN (never graded)

  total: paid 9330 - redeemed 3944 = tax 5386; 2 DEAD -> exit 4
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
CLI = os.path.join(ROOT, "card-tax", "card_tax.py")

CARDS = "\n".join([
    "card\tname\tpay\tbuy\tuntil\tunits\tlist\ttarget",
    "yuedong\t悦动健身年卡\t3650\t2025-09-01\t2026-08-31\t\t90\t1",
    "jingjing\t菁菁英语课包\t4000\t2025-11-15\t\t20\t260\t",
    "xingge\t型格理发卡\t1000\t2026-01-10\t\t10\t78\t",
    "fresh\t轻醒瑜伽次卡\t680\t2026-06-20\t\t10\t68\t",
])

VISITS = "\n".join(
    ["card\tdate\tnote"]
    + ["\t".join(row) for row in (
        [["yuedong", d, ""] for d in (
            "2025-09-02", "2025-09-06", "2025-09-09", "2025-09-13",
            "2025-10-04", "2025-10-11", "2025-10-18", "2025-11-08",
            "2025-11-22", "2025-12-06", "2026-02-10")]
        + [["jingjing", d, ""] for d in (
            "2025-11-22", "2025-11-29", "2025-12-06", "2025-12-13",
            "2025-12-20", "2026-01-10", "2026-01-17", "2026-03-07",
            "2026-03-28")]
        + [["xingge", d, ""] for d in (
            "2026-01-25", "2026-02-22", "2026-03-22", "2026-04-19",
            "2026-05-17", "2026-06-07", "2026-06-30")]
        + [["fresh", "2026-06-21", ""]])])


class CardTaxTestCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cardtax-")
        self.cards = self.write("cards.tsv", CARDS)
        self.visits = self.write("visits.tsv", VISITS)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        return path

    def cli(self, *argv):
        proc = subprocess.run([sys.executable, CLI] + [str(a) for a in argv],
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def run_cli(self, *argv):
        """For commands/ledgers where exit 0 is the expectation
        (validate, simulate, green ledgers)."""
        code, out, err = self.cli(*argv)
        self.assertEqual(code, 0, "exit %d: %s" % (code, err))
        return out

    # ------------------------------------------------------------------
    # report

    def test_report_headline(self):
        code, out, _ = self.cli("report", self.cards, self.visits)
        self.assertEqual(code, 4)
        self.assertIn("cards.tsv + visits.tsv", out)   # basename only
        self.assertIn("as-of : 2026-06-30", out)
        self.assertIn("cards : 4   visits: 28", out)
        self.assertIn("11/52", out)
        self.assertIn("21.2%", out)
        self.assertIn("2,660", out)                    # 3650 - 11x90
        self.assertIn("悦动健身年卡", out)
        self.assertIn("9/20", out)
        self.assertIn("45.0%", out)
        self.assertIn("1,660", out)                    # 4000 - 9x260
        self.assertIn("7/10", out)
        self.assertIn("70.0%", out)
        self.assertIn("454", out)                      # 1000 - 7x78
        self.assertIn("612", out)                      # 680 - 1x68
        self.assertIn("5,386", out)                    # total bill
        self.assertIn("DEAD", out)
        self.assertIn("ON TRACK", out)
        self.assertIn("THIN", out)

    def test_report_identity(self):
        code, out, _ = self.cli("report", self.cards, self.visits)
        self.assertIn("paid 9,330 - redeemed 3,944 = tax 5,386", out)

    def test_report_red_names_every_light(self):
        _, out, _ = self.cli("report", self.cards, self.visits)
        self.assertIn("悦动健身年卡:DEAD", out)
        self.assertIn("悦动健身年卡:BLEED", out)
        self.assertIn("菁菁英语课包:DEAD", out)

    def test_thin_card_is_never_graded(self):
        # rate 10% < 50% but held 10 days: arithmetic stands, no DEAD
        _, out, _ = self.cli("report", self.cards, self.visits)
        self.assertNotIn("轻醒瑜伽次卡:DEAD", out)
        self.assertIn("held 10 days (< 28)", out)

    def test_report_asof_cut(self):
        # pinned replay: visits after 2026-06-07 do not exist yet
        code, out, _ = self.cli("report", "--as-of", "2026-06-07",
                                self.cards, self.visits)
        self.assertEqual(code, 4)
        self.assertIn("as-of : 2026-06-07", out)
        self.assertIn("6/10", out)
        self.assertIn("532", out)                      # 1000 - 6x78
        self.assertNotIn("612", out)                   # fresh visit cut away

    def test_report_asof_expired(self):
        code, out, _ = self.cli("report", "--as-of", "2026-09-30",
                                self.cards, self.visits)
        self.assertEqual(code, 4)
        self.assertIn("EXPIRED", out)                  # yuedong lapsed 08-31
        self.assertIn("ASLEEP", out)                   # xingge silence 92 > 56
        self.assertIn("轻醒瑜伽次卡:DEAD", out)      # now old enough to grade

    def test_report_all_green_exit0(self):
        cards = self.write("g.tsv", "\n".join([
            "card\tname\tpay\tbuy\tuntil\tunits\tlist\ttarget",
            "a\t卡A\t780\t2026-01-05\t\t10\t78\t",
        ]))
        visits = self.write("v.tsv", "\n".join(
            ["card\tdate"]
            + ["a\t" + d for d in (
                "2026-01-10", "2026-02-10", "2026-03-10", "2026-04-10",
                "2026-05-10", "2026-06-10", "2026-07-10", "2026-08-10",
                "2026-09-10", "2026-10-10")]))
        out = self.run_cli("report", cards, visits)
        self.assertIn("DONE", out)
        self.assertIn("10/10", out)

    def test_report_global_thin_exit3(self):
        cards = self.write("t.tsv", "\n".join([
            "card\tname\tpay\tbuy\tunits\tlist",
            "a\t卡A\t780\t2026-01-05\t10\t78",
        ]))
        visits = self.write("v.tsv", "card\tdate\na\t2026-01-10\n"
                                     "a\t2026-01-11\n")
        code, out, err = self.cli("report", cards, visits)
        self.assertEqual(code, 3)
        self.assertIn("624", out)                      # 780 - 2x78, stands
        self.assertIn("STATISTICS REFUSED", out)

    def test_report_json(self):
        _, out, _ = self.cli("report", "--format", "json",
                             self.cards, self.visits)
        data = json.loads(out)
        self.assertEqual(data["total_tax"], 5386.0)
        self.assertEqual(data["verdict"], "RED")
        by = {c["card"]: c for c in data["cards"]}
        self.assertEqual(by["悦动健身年卡"]["used"], 11)
        self.assertEqual(by["悦动健身年卡"]["lights"], ["DEAD", "BLEED"])
        self.assertEqual(by["型格理发卡"]["lights"], ["ON TRACK"])

    def test_output_has_no_absolute_paths(self):
        _, out, _ = self.cli("report", self.cards, self.visits)
        self.assertNotIn(self.dir, out)

    def test_deterministic_bytes(self):
        a = self.cli("report", self.cards, self.visits)
        b = self.cli("report", self.cards, self.visits)
        self.assertEqual(a, b)

    # ------------------------------------------------------------------
    # pace

    def test_pace_numbers(self):
        code, out, _ = self.cli("pace", self.cards, self.visits)
        self.assertEqual(code, 4)
        self.assertIn("pace 0.00/week", out)           # nothing in 8 weeks
        self.assertIn("8.9 weeks left", out)           # 62/7 = 8.857
        self.assertIn("+0 projected", out)
        self.assertIn("3,690", out)                    # 41 x 90
        self.assertIn("silence 140d vs cliff line 45d -> CLIFF", out)
        self.assertIn("pace 0.38/week", out)           # xingge: 3 visits/8wk

    def test_pace_no_expiry_line(self):
        _, out, _ = self.cli("pace", self.cards, self.visits)
        self.assertIn("no expiry on file", out)

    # ------------------------------------------------------------------
    # cost

    def test_cost_numbers(self):
        _, out, _ = self.cli("cost", self.cards, self.visits)
        self.assertIn("331.82", out)                   # 3650/11
        self.assertIn("444.44", out)                   # 4000/9
        self.assertIn("142.86", out)                   # 1000/7
        self.assertIn("40.6", out)                     # 3650/90
        self.assertIn("15.4", out)                     # 4000/260
        self.assertIn("12.8", out)                     # 1000/78
        self.assertIn("27.1%", out)                    # 11/40.56
        self.assertIn("58.5%", out)                    # 9/15.38
        self.assertIn("54.6%", out)                    # 7/12.82

    # ------------------------------------------------------------------
    # offer

    def test_offer_court_blocks(self):
        code, out, _ = self.cli(
            "offer", "--pay", "3000", "--units", "50", "--list", "88",
            "--until", "2027-06-30", self.cards, self.visits)
        self.assertEqual(code, 4)
        self.assertIn("0.27/week", out)                # 27 visits / 700d
        self.assertIn("14 of 50", out)                 # floor(0.27 x 52.14)
        self.assertIn("1,768", out)                    # 3000 - 14x88
        self.assertIn("58.9%", out)
        self.assertIn("old cards still on the table", out)
        self.assertIn("悦动健身年卡 (21.2% used, 41 left)", out)

    def test_offer_green_history(self):
        # a member who actually shows up: 18/20 redeemed, fortnightly
        cards = self.write("g.tsv", "\n".join([
            "card\tname\tpay\tbuy\tunits\tlist",
            "a\t卡A\t4000\t2025-11-15\t20\t260",
        ]))
        days = ("2025-11-20", "2025-12-04", "2025-12-18", "2026-01-01",
                "2026-01-15", "2026-01-29", "2026-02-12", "2026-02-26",
                "2026-03-12", "2026-03-26", "2026-04-09", "2026-04-23",
                "2026-05-07", "2026-05-21", "2026-06-04", "2026-06-18",
                "2026-07-02", "2026-07-16")
        visits = self.write("v.tsv", "\n".join(
            ["card\tdate"] + ["a\t" + d for d in days]))
        # pace = 18 visits / 243d = 0.52/wk -> 27 of 10 units redeem:
        # projected tax is negative, well under the 30% line
        code, out, _ = self.cli(
            "offer", "--pay", "1000", "--units", "10", "--list", "88",
            "--until", "2027-06-30", cards, visits)
        self.assertEqual(code, 0, out)
        self.assertIn("under the 30% line", out)

    def test_offer_requires_term(self):
        code, _, err = self.cli("offer", "--pay", "100", "--units", "10",
                                "--list", "12", self.cards, self.visits)
        self.assertEqual(code, 2)

    # ------------------------------------------------------------------
    # simulate

    def test_simulate_all_cards(self):
        code, out, _ = self.cli("simulate", "--weekly", "3",
                                self.cards, self.visits)
        self.assertEqual(code, 0)                      # sandboxes enforce not
        self.assertIn("26 feasible, 26 rescued (2,340 back at list), 15 still"
                      " on the table", out)
        self.assertIn("11 rescued (2,860 back at list)", out)
        self.assertIn("3 rescued (234 back at list)", out)
        self.assertIn("5,434", out)                    # 2340 + 2860 + 234

    def test_simulate_single_card(self):
        out = self.run_cli("simulate", "--weekly", "2", "--card", "xingge",
                           self.cards, self.visits)
        self.assertIn("3 rescued (234 back at list)", out)
        self.assertNotIn("悦动", out)                 # filtered out

    def test_simulate_unknown_card(self):
        code, _, _ = self.cli("simulate", "--card", "nope",
                              self.cards, self.visits)
        self.assertEqual(code, 2)

    def test_simulate_identity_rescue_plus_left(self):
        out = self.run_cli("simulate", "--weekly", "1", "--card", "yuedong",
                           self.cards, self.visits)
        # 8.86 weeks x 1 = 8 feasible; 8 rescued + 33 left = 41 was left
        self.assertIn("8 feasible, 8 rescued (720 back at list), 33 still"
                      " on the table", out)

    # ------------------------------------------------------------------
    # validate

    def test_validate_ok(self):
        code, out, _ = self.cli("validate", self.cards, self.visits)
        self.assertEqual(code, 0)
        self.assertIn("ALL OK", out)
        self.assertIn("5,386", out)

    def test_validate_over_redemption(self):
        visits = self.write("v2.tsv", VISITS
                            + "\nxingge\t2026-07-05\n"
                            + "\nxingge\t2026-07-06\n"
                            + "\nxingge\t2026-07-07\n"
                            + "\nxingge\t2026-07-08\n")
        code, out, _ = self.cli("validate", self.cards, visits)
        self.assertEqual(code, 2)
        self.assertIn("over-redeemed", out)

    def test_validate_unknown_card_reference(self):
        visits = self.write("v2.tsv", VISITS + "\nghost\t2026-07-01\n")
        code, _, err = self.cli("report", self.cards, visits)
        self.assertEqual(code, 2)
        self.assertIn("unknown card", err)

    def test_visit_predates_purchase(self):
        visits = self.write("v2.tsv", VISITS + "\nxingge\t2025-12-31\n")
        code, _, err = self.cli("report", self.cards, visits)
        self.assertEqual(code, 2)
        self.assertIn("predates", err)

    # ------------------------------------------------------------------
    # ledger parsing

    def test_bad_date_exit2(self):
        visits = self.write("v2.tsv", VISITS + "\nxingge\t2026-13-40\n")
        code, _, _ = self.cli("report", self.cards, visits)
        self.assertEqual(code, 2)

    def test_missing_column_exit2(self):
        cards = self.write("c2.tsv",
                           "card\tname\tpay\tbuy\tunits\na\t卡A\t1\t"
                           "2026-01-01\t5\n")
        code, _, _ = self.cli("report", cards, self.visits)
        self.assertEqual(code, 2)

    def test_duplicate_card_id_exit2(self):
        cards = self.write("c2.tsv", CARDS + "\nx2\tdup\t100\t2026-01-01\t"
                                                  "5\t20\n")
        visits = self.write("v2.tsv", VISITS + "\nx2\t2026-02-01\n")
        code, _, _ = self.cli("report", cards, visits)
        self.assertEqual(code, 2)

    def test_time_card_needs_until(self):
        cards = self.write("c2.tsv", "\n".join([
            "card\tname\tpay\tbuy\tlist",
            "a\t卡A\t365\t2026-01-01\t90",
        ]))
        code, _, err = self.cli("report", cards, self.visits)
        self.assertEqual(code, 2)
        self.assertIn("needs units or until", err)

    def test_comment_lines_skipped(self):
        cards = self.write("c2.tsv",
                           "# my cards\n" + CARDS + "\n# end\n")
        visits = self.write("v2.tsv", "# visits\n" + VISITS)
        code, out, _ = self.cli("report", cards, visits)
        self.assertEqual(code, 4)
        self.assertIn("5,386", out)

    def test_chinese_column_aliases(self):
        cards = self.write("c2.tsv", "\n".join([
            "卡\t名称\t实付\t购买日\t到期日\t次数\t单次价",
            "yuedong\t悦动健身年卡\t3650\t2025-09-01\t2026-08-31\t\t90",
        ]))
        visits = self.write("v2.tsv", "\n".join([
            "卡\t日期",
            "yuedong\t2025-09-02",
            "yuedong\t2025-09-06",
            "yuedong\t2025-09-09",
        ]))
        out = self.run_cli("report", cards, visits)
        self.assertIn("3/52", out)
        self.assertIn("3,380", out)                    # 3650 - 3x90

    def test_card_id_normalization(self):
        # 'GYM-01' and 'gym 01' are the same card
        cards = self.write("c2.tsv", "\n".join([
            "card\tname\tpay\tbuy\tunits\tlist",
            "GYM-01\t卡A\t780\t2026-01-05\t10\t78",
        ]))
        visits = self.write("v2.tsv", "\n".join([
            "card\tdate",
            "gym 01\t2026-01-20",
            "gym 01\t2026-02-10",
            "gym 01\t2026-03-01",
        ]))
        out = self.run_cli("report", cards, visits)
        self.assertIn("3/10", out)

    # ------------------------------------------------------------------
    # priors are adjustable

    def test_asleep_floor_flag(self):
        # widen the cliff line beyond 140d: yuedong is no longer DEAD,
        # but the pace race still bleeds
        _, out, _ = self.cli("report", "--asleep-days", "200",
                             self.cards, self.visits)
        self.assertNotIn("悦动健身年卡:DEAD", out)
        self.assertIn("悦动健身年卡:BLEED", out)

    def test_bleed_floor_flag(self):
        _, out, _ = self.cli("report", "--bleed-floor", "10000",
                             self.cards, self.visits)
        self.assertNotIn("悦动健身年卡:BLEED", out)
        self.assertIn("悦动健身年卡:DEAD", out)

    def test_red_floor_flag(self):
        code, out, _ = self.cli("report", "--as-of", "2026-09-30",
                                "--red-floor", "100000",
                                self.cards, self.visits)
        self.assertEqual(code, 4)
        self.assertNotIn("EXPIRED", out)
        self.assertIn("DEAD", out)

    def test_target_prior_moves_units(self):
        # a time card's units are weeks x target: 52 x 2 = 104
        cards = self.write("c2.tsv", CARDS.replace("\t90\t1", "\t90\t2"))
        _, out, _ = self.cli("report", cards, self.visits)
        self.assertIn("11/104", out)
        self.assertIn("10.6%", out)                    # 11/104

    # ------------------------------------------------------------------
    # aliases

    def test_aliases(self):
        a = self.cli("report", self.cards, self.visits)
        b = self.cli("status", self.cards, self.visits)
        self.assertEqual(a, b)
        c = self.run_cli("check", self.cards, self.visits)
        d = self.run_cli("validate", self.cards, self.visits)
        self.assertEqual(c, d)
        e = self.cli("sim", "--weekly", "3", self.cards, self.visits)
        f = self.cli("simulate", "--weekly", "3", self.cards, self.visits)
        self.assertEqual(e, f)

    def test_no_subcommand_exit2(self):
        code, _, _ = self.cli()
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
