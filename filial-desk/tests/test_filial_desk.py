#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""filial-desk acceptance tests.

Hand-computed pins come from the demo ledger (21 tickets, 505 minutes,
2025-09-01 Monday -> 2026-08-30 Sunday = 52.0 ledger weeks):
  support tax 505 min/yr = 8.4 h/yr; taught rate 7/20 = 35.0%;
  relapse rate 7/21 = 33.3%; verified 4 + open 2 + taught-but-back 1;
  night calls 2/8 = 25.0%; 红米 9A median gap 31.5d, 315 min/yr = 5.25 h
  -> at 50/h = 262.50 vs residual 200 -> SUNK.
"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLI = os.path.join(REPO, "filial_desk.py")
DEMO = os.path.join(REPO, "examples", "ledger.tsv")
TUTORIALS = os.path.join(REPO, "examples", "tutorials.txt")

HEADER = "date\tparent\tdevice\ttopic\tminutes\tmode\ttaught\tclock\tnote\n"


def run(argv):
    proc = subprocess.run([sys.executable, CLI] + argv,
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def write_ledger(rows, header=True):
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        if header:
            fh.write(HEADER)
        for row in rows:
            fh.write("\t".join(row) + "\n")
    return path


def demo_row(date, parent, device, topic, minutes, mode="", taught="",
             clock="", note=""):
    return (date, parent, device, topic, minutes, mode, taught, clock, note)


class Parsing(unittest.TestCase):
    def test_demo_ledger_parses_21_tickets(self):
        code, out, _ = run(["validate", DEMO])
        self.assertEqual(code, 0)
        self.assertIn("tickets: 21", out)

    def test_missing_header_exit_2(self):
        path = write_ledger([demo_row("2026-01-01", "妈", "iPhone", "x", "5")],
                            header=False)
        code, _out, err = run(["validate", path])
        self.assertEqual(code, 2)
        self.assertIn("header", err)

    def test_too_few_columns_exit_2(self):
        path = write_ledger([("2026-01-01", "妈", "iPhone", "x")])
        code, _out, err = run(["validate", path])
        self.assertEqual(code, 2)
        self.assertIn("columns", err)

    def test_too_many_columns_exit_2(self):
        row = demo_row("2026-01-01", "妈", "iPhone", "x", "5") + ("extra",)
        path = write_ledger([row])
        code, _out, err = run(["validate", path])
        self.assertEqual(code, 2)

    def test_bad_date_exit_2(self):
        path = write_ledger([demo_row("2026-13-01", "妈", "iPhone", "x", "5")])
        code, _out, err = run(["validate", path])
        self.assertEqual(code, 2)
        self.assertIn("bad date", err)

    def test_empty_parent_exit_2(self):
        path = write_ledger([demo_row("2026-01-01", "", "iPhone", "x", "5")])
        self.assertEqual(run(["validate", path])[0], 2)

    def test_empty_device_exit_2(self):
        path = write_ledger([demo_row("2026-01-01", "妈", "", "x", "5")])
        self.assertEqual(run(["validate", path])[0], 2)

    def test_empty_topic_exit_2(self):
        path = write_ledger([demo_row("2026-01-01", "妈", "iPhone", "", "5")])
        self.assertEqual(run(["validate", path])[0], 2)

    def test_bad_minutes_exit_2(self):
        for bad in ("0", "-3", "2.5", "abc", ""):
            path = write_ledger([demo_row("2026-01-01", "妈", "iPhone",
                                          "x", bad)])
            self.assertEqual(run(["validate", path])[0], 2, bad)

    def test_bad_mode_exit_2(self):
        path = write_ledger([demo_row("2026-01-01", "妈", "iPhone", "x", "5",
                                      " pigeon ")])
        code, _out, err = run(["validate", path])
        self.assertEqual(code, 2)
        self.assertIn("mode", err)

    def test_bad_taught_exit_2(self):
        path = write_ledger([demo_row("2026-01-01", "妈", "iPhone", "x", "5",
                                      "", "maybe")])
        code, _out, err = run(["validate", path])
        self.assertEqual(code, 2)
        self.assertIn("taught", err)

    def test_bad_clock_format_exit_2(self):
        path = write_ledger([demo_row("2026-01-01", "妈", "iPhone", "x", "5",
                                      "", "", "7:0")])
        self.assertEqual(run(["validate", path])[0], 2)

    def test_clock_out_of_range_exit_2(self):
        path = write_ledger([demo_row("2026-01-01", "妈", "iPhone", "x", "5",
                                      "", "", "24:00")])
        self.assertEqual(run(["validate", path])[0], 2)

    def test_exact_duplicate_row_exit_2(self):
        row = demo_row("2026-01-01", "妈", "iPhone", "x", "5", "视频", "yes")
        path = write_ledger([row, row])
        code, _out, err = run(["validate", path])
        self.assertEqual(code, 2)
        self.assertIn("duplicate", err)

    def test_comments_and_blank_lines_skipped(self):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("# a comment\n\n")
            fh.write(HEADER)
            fh.write("# another\n")
            fh.write("\t".join(demo_row("2026-01-01", "妈", "iPhone",
                                        "x", "5")) + "\n")
        self.assertEqual(run(["validate", path])[0], 0)

    def test_minimal_five_columns_ok(self):
        path = write_ledger([demo_row("2026-01-01", "妈", "iPhone",
                                      "x", "5")])
        code, out, _ = run(["validate", path])
        self.assertEqual(code, 0)
        self.assertIn("taught unrecorded on 1", out)

    def test_chinese_aliases_normalized(self):
        rows = [demo_row("2026-01-01", "妈", "iPhone", "x", "5",
                         "视频", "是", "07:30"),
                demo_row("2026-02-01", "妈", "iPhone", "x", "5",
                         "电话", "否", "23:00"),
                demo_row("2026-03-01", "妈", "iPhone", "x", "5",
                         "远程", "", "08:00"),
                demo_row("2026-04-01", "妈", "iPhone", "x", "5",
                         "现场", "", "22:00")]
        path = write_ledger(rows)
        # 4 tickets is a thin ledger: statistics refused, but the mode and
        # night counts above are arithmetic facts and must still print.
        code, out, _err = run(["report", path])
        self.assertEqual(code, 3)
        self.assertIn("modes: onsite x1  phone x1  remote x1  video x1", out)
        self.assertIn("night calls (22:00-08:00): 3 (75.0% of timed)", out)
        self.assertIn("STATISTICS REFUSED", out)

    def test_unreadable_file_exit_2(self):
        self.assertEqual(run(["validate", "no/such/file.tsv"])[0], 2)

    def test_topic_key_folding(self):
        sys.path.insert(0, REPO)
        import filial_desk
        self.assertEqual(filial_desk.topic_key("WiFi 断网"), "wifi断网")
        self.assertEqual(filial_desk.topic_key("手机弹广告"), "手机弹广告")
        self.assertEqual(filial_desk.topic_key("  Wi-Fi，断网! "),
                         filial_desk.topic_key("wifi断网"))


class Chains(unittest.TestCase):
    def _chains(self, rows, window=90):
        sys.path.insert(0, REPO)
        import filial_desk
        return filial_desk.build_chains(
            filial_desk.parse_ledger(write_ledger(rows)), window)

    def test_gap_exactly_window_is_relapse(self):
        chains = self._chains([
            demo_row("2026-01-10", "妈", "iPhone", "断网", "10", "", "no"),
            demo_row("2026-04-10", "妈", "iPhone", "断网", "10", "", "no")])
        relapses = [t for c in chains for t in c if t["relapse"]]
        self.assertEqual(len(relapses), 1)

    def test_gap_window_plus_one_is_new_chain(self):
        chains = self._chains([
            demo_row("2026-01-09", "妈", "iPhone", "断网", "10", "", "yes"),
            demo_row("2026-04-10", "妈", "iPhone", "断网", "10", "", "no")])
        relapses = [t for c in chains for t in c if t["relapse"]]
        self.assertEqual(len(relapses), 0)
        self.assertEqual(len(chains), 2)

    def test_same_topic_different_parent_not_a_chain(self):
        chains = self._chains([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10", "", "no"),
            demo_row("2026-01-15", "爸", "红米", "断网", "10", "", "no")])
        relapses = [t for c in chains for t in c if t["relapse"]]
        self.assertEqual(len(relapses), 0)
        self.assertEqual(len(chains), 2)

    def test_normalized_topic_joins_chain(self):
        chains = self._chains([
            demo_row("2026-01-01", "妈", "iPhone", "WiFi 断网", "10", "", "no"),
            demo_row("2026-02-01", "妈", "iPhone", "wifi断网", "10", "", "no")])
        relapses = [t for c in chains for t in c if t["relapse"]]
        self.assertEqual(len(relapses), 1)

    def test_taught_but_back_classification(self):
        chains = self._chains([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10", "", "yes"),
            demo_row("2026-02-01", "妈", "iPhone", "断网", "10", "", "no")])
        relapses = [t for c in chains for t in c if t["relapse"]]
        self.assertEqual(len(relapses), 1)
        self.assertTrue(relapses[0]["back"])

    def test_untaught_relapse_not_back(self):
        chains = self._chains([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10", "", "no"),
            demo_row("2026-02-01", "妈", "iPhone", "断网", "10", "", "no")])
        relapses = [t for c in chains for t in c if t["relapse"]]
        self.assertFalse(relapses[0]["back"])

    def test_back_blames_the_claim_ticket_not_the_relapse(self):
        sys.path.insert(0, REPO)
        import filial_desk
        rows = filial_desk.parse_ledger(write_ledger([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10", "", "yes"),
            demo_row("2026-02-01", "妈", "iPhone", "断网", "10", "", "no")]))
        chains = filial_desk.build_chains(rows, 90)
        falsified = filial_desk.falsified_claim_lines(chains)
        self.assertEqual(falsified, {rows[0]["line"]})

    def test_rolling_chain_extends(self):
        chains = self._chains([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10", "", "no"),
            demo_row("2026-02-01", "妈", "iPhone", "断网", "10", "", "no"),
            demo_row("2026-03-20", "妈", "iPhone", "断网", "10", "", "no")])
        self.assertEqual(len(chains), 1)
        self.assertEqual(len([t for t in chains[0] if t["relapse"]]), 2)


class Report(unittest.TestCase):
    def test_demo_headline_numbers(self):
        code, out, _ = run(["report", DEMO])
        self.assertEqual(code, 0)
        self.assertIn("tickets: 21", out)
        self.assertIn("505 min total | annualized 505 min = 8.4 h/yr", out)
        self.assertIn("364 days, 52.0 ledger weeks", out)

    def test_demo_decomposition_identities(self):
        _code, out, _ = run(["report", DEMO])
        self.assertIn("爸", out)
        self.assertIn("x11 tickets   315 min", out)
        self.assertIn("x10 tickets   190 min", out)
        self.assertIn("iPhone 12", out)
        self.assertIn("165 min", out)
        self.assertIn("WiFi 断网", out)          # display name, not tkey
        self.assertNotIn("wifi断网", out)        # normalized key never shown

    def test_demo_teaching_and_relapse(self):
        _code, out, _ = run(["report", DEMO])
        self.assertIn("7 claimed / 20 judged -> claimed-taught rate 35.0%", out)
        self.assertIn("verified 4", out)
        self.assertIn("open 2", out)
        self.assertIn("taught-but-back 1", out)
        self.assertIn("relapse: 7 of 21 tickets were a relapse (33.3%)", out)

    def test_demo_rhythm_and_modes(self):
        _code, out, _ = run(["report", DEMO])
        self.assertIn("clock on 8 tickets; night calls (22:00-08:00): 2 "
                      "(25.0% of timed)", out)
        self.assertIn("modes: video x8  phone x7  remote x4  onsite x2", out)

    def test_unpriced_has_no_money_line(self):
        _code, out, _ = run(["report", DEMO])
        self.assertIn("NOTE unpriced", out)
        self.assertNotIn("/yr", out.split("NOTE")[0].splitlines()[-1])
        self.assertNotIn("at 50.00/h", out)

    def test_hourly_translates_tax(self):
        _code, out, _ = run(["report", DEMO, "--hourly", "50"])
        self.assertIn("at 50.00/h: the support tax is 420.83/yr", out)
        self.assertNotIn("NOTE unpriced", out)

    def test_hourly_rejected_if_not_positive(self):
        code, _out, err = run(["report", DEMO, "--hourly", "0"])
        self.assertEqual(code, 2)
        self.assertIn("--hourly", err)

    def test_as_of_cuts_the_ledger(self):
        code, out, _ = run(["report", DEMO, "--as-of", "2026-01-20"])
        self.assertEqual(code, 0)
        self.assertIn("tickets: 10", out)
        self.assertIn("257 min total | annualized 636 min", out)
        self.assertIn("21.0 ledger weeks", out)
        self.assertIn("as-of: 2026-01-20", out)
        self.assertNotIn("ledger end", out)

    def test_as_of_before_first_ticket_exit_2(self):
        code, _out, err = run(["report", DEMO, "--as-of", "2025-08-31"])
        self.assertEqual(code, 2)
        self.assertIn("cuts away", err)

    def test_as_of_boundary_inclusive(self):
        _code, out, _ = run(["report", DEMO, "--as-of", "2026-01-12"])
        self.assertIn("tickets: 9", out)   # the 01-12 ticket itself is in

    def test_thin_ledger_prints_arithmetic_then_refuses(self):
        path = write_ledger([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10", "", "yes"),
            demo_row("2026-02-01", "妈", "iPhone", "断网", "10", "", "no"),
            demo_row("2026-03-01", "爸", "红米", "弹广告", "20", "", "no")])
        code, out, err = run(["report", path])
        self.assertEqual(code, 3)
        self.assertIn("support time: 40 min", out)     # arithmetic survived
        self.assertIn("by parent:", out)
        self.assertIn("STATISTICS REFUSED", out)
        self.assertIn("too thin", err)

    def test_byte_identical_reruns(self):
        _c1, out1, _ = run(["report", DEMO])
        _c2, out2, _ = run(["report", DEMO])
        self.assertEqual(out1, out2)


class Relapse(unittest.TestCase):
    def test_demo_chains(self):
        code, out, _ = run(["relapse", DEMO])
        self.assertEqual(code, 0)
        self.assertIn("妈 / WiFi 断网 — 3 ticket(s), 2 relapse(s)", out)
        self.assertIn("TAUGHT-BUT-BACK, +38d", out)
        self.assertIn("爸 / 手机弹广告 — 5 ticket(s), 4 relapse(s)", out)
        self.assertIn("relapse (UNTAUGHT, +90d)", out)   # window boundary
        self.assertIn("relapse rate: 7 of 21 tickets (33.3%)", out)
        self.assertIn("under both lines", out)

    def test_rate_line_lowered_fires(self):
        code, out, _ = run(["relapse", DEMO, "--rate-line", "0.3"])
        self.assertEqual(code, 4)
        self.assertIn("over the 30% line", out)

    def test_back_line_one_fires_on_single_pseudology(self):
        code, out, _ = run(["relapse", DEMO, "--back-line", "1"])
        self.assertEqual(code, 4)
        self.assertIn("1 taught-but-back relapses", out)

    def test_thin_ledger_shows_chains_refuses_verdict(self):
        path = write_ledger([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10", "", "no"),
            demo_row("2026-02-01", "妈", "iPhone", "断网", "10", "", "no")])
        code, out, err = run(["relapse", path])
        self.assertEqual(code, 3)
        self.assertIn("2 ticket(s), 1 relapse(s)", out)   # facts survive
        self.assertIn("VERDICT REFUSED", out)
        self.assertIn("too thin", err)

    def test_no_relapse_clean_verdict(self):
        path = write_ledger([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10", "", "yes"),
            demo_row("2026-04-15", "妈", "iPhone", "弹广告", "10", "", "no"),
            demo_row("2026-05-01", "妈", "iPhone", "字体", "10", "", "no"),
            demo_row("2026-05-15", "妈", "iPhone", "内存", "10", "", "no"),
            demo_row("2026-06-01", "妈", "iPhone", "电池", "10", "", "no"),
            demo_row("2026-06-15", "妈", "iPhone", "信号", "10", "", "no"),
            demo_row("2026-07-01", "妈", "iPhone", "充电", "10", "", "no"),
            demo_row("2026-07-15", "妈", "iPhone", "摔了", "10", "", "no")])
        code, out, _ = run(["relapse", path])
        self.assertEqual(code, 0)
        self.assertIn("no (parent, topic) pair relapsed", out)


class Fleet(unittest.TestCase):
    def test_demo_table(self):
        _code, out, _ = run(["fleet", DEMO])
        self.assertIn("红米 9A", out)
        self.assertIn("31.5d", out)
        self.assertIn("42.0d", out)
        self.assertIn("no residual on file (hours only)", out)

    def test_sunk_red_line(self):
        code, out, _ = run(["fleet", DEMO, "--residual", "红米 9A:200",
                            "--hourly", "50"])
        self.assertEqual(code, 4)
        self.assertIn("SUNK", out)
        self.assertIn("annual support 262.50 vs residual 200", out)
        self.assertIn("it is amortization", out)

    def test_residual_without_hourly_never_invents_money(self):
        code, out, _ = run(["fleet", DEMO, "--residual", "红米 9A:200"])
        self.assertEqual(code, 0)
        self.assertIn("add --hourly to price the hours", out)
        self.assertNotIn("SUNK", out)

    def test_cheap_hours_no_red_line(self):
        code, out, _ = run(["fleet", DEMO, "--residual", "红米 9A:200",
                            "--hourly", "30"])
        self.assertEqual(code, 0)
        self.assertNotIn("SUNK", out)

    def test_high_freq_line(self):
        code, out, _ = run(["fleet", DEMO, "--freq-line", "40",
                            "--residual", "红米 9A:200", "--hourly", "50"])
        self.assertEqual(code, 4)
        self.assertIn("HIGH-FREQ", out)     # precedence over SUNK

    def test_freq_line_default_not_hit(self):
        code, out, _ = run(["fleet", DEMO, "--residual", "红米 9A:200",
                            "--hourly", "50"])
        self.assertNotIn("HIGH-FREQ", out)  # 31.5d >= 21d default

    def test_bad_residual_format_exit_2(self):
        code, _out, err = run(["fleet", DEMO, "--residual", "红米 9A"])
        self.assertEqual(code, 2)
        self.assertIn("DEV:AMT", err)

    def test_thin_ledger_refuses_annualization(self):
        path = write_ledger([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10"),
            demo_row("2026-02-01", "妈", "iPhone", "断网", "10")])
        code, out, err = run(["fleet", path])
        self.assertEqual(code, 3)
        self.assertIn("refused", out)
        self.assertIn("x2", out)            # arithmetic table still printed
        self.assertIn("too thin", err)      # and stderr keeps the convention


class Curriculum(unittest.TestCase):
    def test_demo_backlog(self):
        code, out, _ = run(["curriculum", DEMO])
        self.assertEqual(code, 0)
        self.assertIn("手机弹广告            x4 relapse(s)", out)
        self.assertIn("WiFi 断网          x2 relapse(s)", out)
        self.assertIn("话费莫名变多           x1 relapse(s)", out)
        self.assertIn("watch", out)
        self.assertIn("write the 2 tutorial(s) above", out)

    def test_full_coverage_no_debt(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("手机弹广告\nwifi 断网\n")   # normalization folds case
        code, out, _ = run(["curriculum", DEMO, "--tutorials", path])
        self.assertEqual(code, 0)
        self.assertIn("covered by your tutorials", out)
        self.assertNotIn("UNCOVERED DEBT", out)

    def test_partial_coverage_exit_4(self):
        code, out, _ = run(["curriculum", DEMO, "--tutorials", TUTORIALS])
        self.assertEqual(code, 4)
        self.assertIn("1 uncovered tutorial debt(s): WiFi 断网", out)

    def test_no_relapses_no_debt(self):
        path = write_ledger([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10"),
            demo_row("2026-02-01", "妈", "iPhone", "弹广告", "10")])
        code, out, _ = run(["curriculum", path])
        self.assertEqual(code, 0)
        self.assertIn("no topic ever relapsed", out)


class Simulate(unittest.TestCase):
    def test_cure_pinned_replay(self):
        code, out, _ = run(["simulate", DEMO, "cure",
                            "--topic", "手机弹广告", "--hourly", "50"])
        self.assertEqual(code, 0)
        self.assertIn("tickets: 21 -> 17 (removed 4, 120 min)", out)
        self.assertIn("505 min/yr -> 385 min/yr (-120 min = -2.0 h)", out)
        self.assertIn("relapse rate: 33.3% -> 17.6%", out)
        self.assertIn("saves 100.00/yr", out)

    def test_retire_pinned_replay(self):
        code, out, _ = run(["simulate", DEMO, "retire",
                            "--device", "红米 9A", "--hourly", "50"])
        self.assertEqual(code, 0)
        self.assertIn("tickets: 21 -> 10 (removed 11, 315 min)", out)
        self.assertIn("505 min/yr -> 190 min/yr (-315 min = -5.2 h)", out)
        self.assertIn("relapse rate: 33.3% -> 20.0%", out)

    def test_kept_plus_removed_identity(self):
        sys.path.insert(0, REPO)
        import filial_desk
        rows = filial_desk.parse_ledger(DEMO)
        chains = filial_desk.build_chains(rows, 90)
        tkey = filial_desk.topic_key("手机弹广告")
        removed = {t["line"] for chain in chains if chain[0]["tkey"] == tkey
                   for t in chain if t["relapse"]}
        self.assertEqual(len(removed) + (len(rows) - len(removed)), len(rows))
        kept_minutes = sum(r["minutes"] for r in rows
                           if r["line"] not in removed)
        removed_minutes = sum(r["minutes"] for r in rows
                              if r["line"] in removed)
        self.assertEqual(kept_minutes + removed_minutes, 505)

    def test_unknown_topic_exit_2(self):
        code, _out, err = run(["simulate", DEMO, "cure", "--topic", "不存在"])
        self.assertEqual(code, 2)
        self.assertIn("no tickets", err)

    def test_unknown_device_exit_2(self):
        code, _out, err = run(["simulate", DEMO, "retire",
                               "--device", "诺基亚"])
        self.assertEqual(code, 2)

    def test_cure_keeps_head_ticket(self):
        _code, out, _ = run(["simulate", DEMO, "cure",
                             "--topic", "手机弹广告"])
        self.assertIn("head ticket remains", out)


class Validate(unittest.TestCase):
    def test_demo_healthy(self):
        code, out, _ = run(["validate", DEMO])
        self.assertEqual(code, 0)
        self.assertIn("parent 505 | device 505 | topic 505 == total 505  [OK]",
                      out)
        self.assertIn("taught unrecorded on 1 ticket(s)", out)
        self.assertIn("clock recorded on 8 of 21", out)
        self.assertIn("ledger healthy", out)

    def test_busiest_day_disclosed(self):
        path = write_ledger([
            demo_row("2026-01-01", "妈", "iPhone", "断网", "10"),
            demo_row("2026-01-01", "妈", "iPhone", "弹广告", "10")])
        _code, out, _ = run(["validate", path])
        self.assertIn("busiest day: 2026-01-01 x2", out)

    def test_empty_ledger_exit_2(self):
        path = write_ledger([])
        code, _out, err = run(["validate", path])
        self.assertEqual(code, 2)
        self.assertIn("no tickets", err)


class ExitSemantics(unittest.TestCase):
    def test_no_command_shows_help_exit_2(self):
        code, out, _err = run([])
        self.assertEqual(code, 2)
        self.assertIn("usage:", out)

    def test_simulate_cure_requires_topic(self):
        _code, _out, err = run(["simulate", DEMO, "cure"])
        self.assertIn("--topic", err)

    def test_simulate_retire_requires_device(self):
        _code, _out, err = run(["simulate", DEMO, "retire"])
        self.assertIn("--device", err)


if __name__ == "__main__":
    unittest.main()
