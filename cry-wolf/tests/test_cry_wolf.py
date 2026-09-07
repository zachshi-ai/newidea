# -*- coding: utf-8 -*-
"""cry-wolf acceptance tests.

Hand-computed fixture numbers are pinned as literals: the sample ledger's
7 verdicts (1 hit + 1 partial + 5 miss), 12 nights (9 wolf + 1 fire + 2
unchecked) and the child-health chain's at-filing records (0M, 1M, 2M)
were computed by hand before the CLI ran — a mismatch means the code or
the reading is wrong, and the arithmetic decides which.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import cry_wolf  # noqa: E402

EXAMPLE_LEDGER = os.path.join(HERE, "..", "examples", "worries.tsv")

HEADER = "date\ttype\ttopic\tfear\tdue\tnights\tref\toutcome"

SAMPLE = "\n".join([
    HEADER,
    "2026-03-02\tfear\tchild-health\tcough turns into pneumonia\t2026-03-16\t2\t\t",
    "2026-03-16\tcheck\t\t\t\t\t2\tmiss",
    "2026-03-20\tfear\thealth\tnodule turns malignant\t2026-06-01\t3\t\t",
    "2026-06-01\tcheck\t\t\t\t\t4\tmiss",
    "2026-04-10\tfear\tmoney\tpullback margin-calls the position\t2026-05-10\t0\t\t",
    "2026-05-10\tcheck\t\t\t\t\t6\tpartial",
    "2026-05-08\tfear\tchild-health\tpneumonia this time for sure\t2026-05-22\t1\t\t",
    "2026-05-22\tcheck\t\t\t\t\t8\tmiss",
    "2026-07-06\tfear\tchild-health\tthird cough, wheezing\t2026-07-20\t2\t\t",
    "2026-07-20\tcheck\t\t\t\t\t10\tmiss",
])


class TempLedgerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "worries.tsv")

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def cli(self, *argv):
        """run the CLI; returns (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cry_wolf.main(list(argv))
            except SystemExit as exc:  # argparse errors
                code = exc.code if isinstance(exc.code, int) else 2
        return code, out.getvalue(), err.getvalue()


class SampleLedgerTest(TempLedgerCase):
    """the shipped example: hand-computed numbers pinned as literals."""

    def test_report_numbers(self):
        code, out, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(code, 4)  # WOLF is lit; that is the story
        for needle in ("checked 7 = hit 1 + partial 1 + miss 5",
                       "unchecked 3 = overdue 1 · open-ended 1 · on the clock 1",
                       "false alarms: 5/7 (71.4%) never happened",
                       "counting half-hits as not-fully-true: 6/7 (85.7%)",
                       "nights: 12 total = 9 for wolves that never came · 0 for half-wolves",
                       "· 1 for real fires · 2 still on unchecked fears",
                       "chain: child-health — 3 checked, record 0H/0P/3M",
                       "oldest 5d",
                       "as-of 2026-09-05"):
            self.assertIn(needle, out)

    def test_at_filing_records_replay_forward(self):
        code, out, _ = self.cli("wolves", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(code, 4)
        self.assertIn("0H/0P/0M", out)
        self.assertIn("0H/0P/1M", out)
        self.assertIn("0H/0P/2M", out)
        self.assertIn("0H/0P/3M", out)  # the 4th filing saw 3 misses already

    def test_time_machine_0523(self):
        code, out, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER, "--as-of", "2026-05-23")
        self.assertEqual(code, 3)  # thin then: only 3 verdicts on file
        self.assertIn("checked 3 = hit 0 + partial 1 + miss 2", out)
        self.assertIn("DECLINE", out)
        self.assertIn("5 fears", out)

    def test_time_machine_wolves_monitor_not_wolf(self):
        code, out, _ = self.cli("wolves", "--ledger", EXAMPLE_LEDGER, "--as-of", "2026-05-23")
        self.assertEqual(code, 0)
        self.assertIn("▲ monitor", out)
        self.assertNotIn("WOLF", out.replace("wolves", "").replace("repeat-offender", ""))

    def test_duet_lists_three_cases(self):
        code, out, _ = self.cli("due", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(code, 0)
        self.assertIn("3 fears awaiting their verdict", out)
        self.assertIn("5d overdue", out)
        self.assertIn("14d left", out)
        self.assertIn("NO DATE AT ALL", out)

    def test_validate_identity(self):
        code, out, _ = self.cli("validate", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(code, 0)
        self.assertIn("refs resolve 7/7", out)
        self.assertIn("nights:   12 total = wolves 9 + half 0 + fires 1 + unchecked 2", out)
        self.assertIn("ledger is sound", out)

    def test_byte_reproducible(self):
        _, first, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER)
        _, second, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(first, second)

    def test_no_absolute_path_in_report(self):
        _, out, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER)
        self.assertNotIn(EXAMPLE_LEDGER, out)
        self.assertIn("worries.tsv", out)


class BrokenLedgerTest(TempLedgerCase):
    def expect_broken(self, text, needle):
        self.write(text)
        code, _, err = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 2, err)
        self.assertIn(needle, err)

    def test_bad_header(self):
        self.expect_broken("a\tb\tc\n", "bad header")

    def test_missing_column(self):
        self.expect_broken(HEADER + "\n2026-03-02\tfear\tt\tf\t2026-03-16\t1\n",
                           "want 8 tab-separated fields, got 6")

    def test_trailing_tab_from_paste_is_tolerated(self):
        self.write(SAMPLE + "\t\t\t\n")
        code, _, err = self.cli("report", "--ledger", self.path)
        self.assertNotEqual(code, 2, err)

    def test_nonzero_padded_date(self):
        self.expect_broken(HEADER + "\n2026-3-2\tfear\tt\tf\t2026-03-16\t\t\t\n",
                           "bad date '2026-3-2'")

    def test_impossible_calendar_date(self):
        self.expect_broken(HEADER + "\n2026-02-30\tfear\tt\tf\t2026-03-16\t\t\t\n",
                           "impossible calendar date")

    def test_bad_due_date(self):
        self.expect_broken(HEADER + "\n2026-03-02\tfear\tt\tf\t2026-13-01\t\t\t\n",
                           "impossible calendar date '2026-13-01'")

    def test_unknown_type(self):
        self.expect_broken(HEADER + "\n2026-03-02\twish\tt\tf\t2026-03-16\t\t\t\n",
                           "unknown type 'wish'")

    def test_unknown_outcome(self):
        self.expect_broken(SAMPLE.replace("2026-03-16\tcheck\t\t\t\t\t2\tmiss",
                                          "2026-03-16\tcheck\t\t\t\t\t2\tmaybe"),
                           "unknown outcome 'maybe'")

    def test_fear_needs_topic(self):
        self.expect_broken(HEADER + "\n2026-03-02\tfear\t\tf\t2026-03-16\t\t\t\n",
                           "needs a topic")

    def test_fear_needs_text(self):
        self.expect_broken(HEADER + "\n2026-03-02\tfear\tt\t\t2026-03-16\t\t\t\n",
                           "needs the feared outcome")

    def test_negative_nights(self):
        self.expect_broken(HEADER + "\n2026-03-02\tfear\tt\tf\t2026-03-16\t-1\t\t\n",
                           "non-negative integer")

    def test_fractional_nights(self):
        self.expect_broken(HEADER + "\n2026-03-02\tfear\tt\tf\t2026-03-16\t1.5\t\t\n",
                           "non-negative integer")

    def test_dangling_ref(self):
        self.expect_broken(HEADER + "\n2026-03-16\tcheck\t\t\t\t\t99\tmiss\n",
                           "does not point at a fear row")

    def test_ref_at_check_row(self):
        text = SAMPLE + "\n2026-08-01\tcheck\t\t\t\t\t3\tmiss\n"
        self.expect_broken(text, "does not point at a fear row")

    def test_double_verdict(self):
        text = SAMPLE + "\n2026-08-01\tcheck\t\t\t\t\t2\thit\n"
        self.expect_broken(text, "already checked at line 3")

    def test_verdict_predates_fear(self):
        self.expect_broken(HEADER + "\n2026-03-02\tfear\tt\tf\t2026-06-01\t\t\t\n"
                                    "2026-03-01\tcheck\t\t\t\t\t2\tmiss\n",
                           "predates its fear")

    def test_alias_bad_format(self):
        self.write(SAMPLE)
        code, _, err = self.cli("report", "--ledger", self.path, "--alias", "noequals")
        self.assertEqual(code, 2)
        self.assertIn("bad --alias", err)


class EmptyLedgerTest(TempLedgerCase):
    def expect_decline(self, text=None, missing=False):
        if not missing:
            self.write(text)
        code, _, err = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 3, err)

    def test_zero_bytes(self):
        self.expect_decline("")

    def test_blank_lines_only(self):
        self.expect_decline("\n\n  \n")

    def test_header_no_rows(self):
        self.expect_decline(HEADER + "\n")

    def test_comments_only(self):
        self.expect_decline("# nothing here\n# still nothing\n")

    def test_missing_file(self):
        self.expect_decline(missing=True)

    def test_asof_before_everything(self):
        self.write(SAMPLE)
        code, _, err = self.cli("report", "--ledger", self.path, "--as-of", "2026-01-01")
        self.assertEqual(code, 3)
        self.assertIn("nothing on or before", err)


class WolfChainTest(TempLedgerCase):
    def ledger_with_chain(self, outcomes, topic="kid"):
        rows = [HEADER]
        lines = {}
        dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
        for i, outcome in enumerate(outcomes):
            fear_date = dates[i]
            due = fear_date[:8] + "15"
            rows.append("%s\tfear\t%s\tfear no.%d\t%s\t1\t\t" % (fear_date, topic, i + 1, due))
            lines[i] = len(rows)
            rows.append("%s\tcheck\t\t\t\t\t%d\t%s" % (due, lines[i], outcome))
        return "\n".join(rows) + "\n"

    def test_two_misses_are_monitor_not_wolf(self):
        self.write(self.ledger_with_chain(["miss", "miss"]))
        code, out, _ = self.cli("wolves", "--ledger", self.path)
        self.assertEqual(code, 0)
        self.assertIn("▲ monitor", out)
        self.assertNotIn("🔴 WOLF", out)

    def test_three_misses_light_wolf(self):
        self.write(self.ledger_with_chain(["miss", "miss", "miss"]))
        code, out, _ = self.cli("wolves", "--ledger", self.path)
        self.assertEqual(code, 4)
        self.assertIn("🔴 WOLF", out)
        self.assertIn("cried 3 times", out)

    def test_hit_breaks_the_chain(self):
        self.write(self.ledger_with_chain(["miss", "miss", "hit"]))
        code, out, _ = self.cli("wolves", "--ledger", self.path)
        self.assertEqual(code, 0)
        self.assertNotIn("🔴 WOLF", out)

    def test_partial_breaks_the_chain(self):
        self.write(self.ledger_with_chain(["miss", "miss", "partial"]))
        code, _, _ = self.cli("wolves", "--ledger", self.path)
        self.assertEqual(code, 0)

    def test_four_with_one_hit_not_wolf(self):
        self.write(self.ledger_with_chain(["miss", "miss", "miss", "hit"]))
        code, _, _ = self.cli("wolves", "--ledger", self.path)
        self.assertEqual(code, 0)

    def test_unchecked_filings_do_not_count_into_wolf(self):
        rows = [HEADER]
        rows.append("2026-01-01\tfear\tkid\tone\t2026-01-15\t\t\t")
        rows.append("2026-01-15\tcheck\t\t\t\t\t2\tmiss")
        rows.append("2026-02-01\tfear\tkid\ttwo\t2026-02-15\t\t\t")
        rows.append("2026-02-15\tcheck\t\t\t\t\t4\tmiss")
        rows.append("2026-03-01\tfear\tkid\tthree\t2026-04-15\t\t\t")  # unchecked
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("wolves", "--ledger", self.path)
        self.assertEqual(code, 0)
        self.assertIn("▲ monitor", out)
        self.assertNotIn("🔴 WOLF", out)

    def test_at_filing_record_ignores_later_verdicts(self):
        """the 2nd filing must not see a verdict written after it."""
        rows = [HEADER]
        rows.append("2026-01-01\tfear\tkid\tone\t2026-03-15\t\t\t")
        rows.append("2026-03-15\tcheck\t\t\t\t\t2\tmiss")      # verdict after 2nd filing
        rows.append("2026-02-01\tfear\tkid\ttwo\t2026-02-15\t\t\t")
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("wolves", "--ledger", self.path)
        self.assertEqual(code, 0)
        self.assertIn("0H/0P/0M", out)

    def test_alias_merges_chains(self):
        text = self.ledger_with_chain(["miss", "miss", "miss"], topic="娃咳嗽")
        self.write(text)
        code, _, _ = self.cli("wolves", "--ledger", self.path, "--alias", "娃咳嗽=child-health")
        self.assertEqual(code, 4)
        _, out, _ = self.cli("wolves", "--ledger", self.path, "--alias", "娃咳嗽=child-health")
        self.assertIn("child-health", out)

    def test_alias_self_mapping_is_idempotent(self):
        self.write(SAMPLE)
        code_plain, out_plain, _ = self.cli("report", "--ledger", self.path)
        code_alias, out_alias, _ = self.cli("report", "--ledger", self.path, "--alias", "job=job")
        self.assertEqual(code_plain, code_alias)
        self.assertEqual(out_plain, out_alias)


class GateThresholdTest(TempLedgerCase):
    def fear_row(self, date, topic="t", due="", nights="", fear_text="f"):
        return "%s\tfear\t%s\t%s\t%s\t%s\t\t" % (date, topic, fear_text, due, nights)

    def test_overdue_same_day_not_overdue(self):
        rows = [HEADER, self.fear_row("2026-03-01", due="2026-03-10")]
        rows.append("2026-03-10\tcheck\t\t\t\t\t2\tmiss")
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2026-03-10")
        # the checked case settles its own fear; nothing is overdue at due-day
        self.assertNotIn("overdue 1", out)

    def test_overdue_30d_silent_31d_loud(self):
        from datetime import date as _d, timedelta as _t
        for days, expect_alarm in ((30, False), (31, True)):
            rows = [HEADER, self.fear_row("2026-01-01", due="2026-01-10")]
            self.write("\n".join(rows) + "\n")
            anchor = _d(2026, 1, 10) + _t(days=days)
            code, _, _ = self.cli("report", "--ledger", self.path,
                                  "--as-of", anchor.isoformat())
            if expect_alarm:
                self.assertEqual(code, 4)
            else:
                self.assertEqual(code, 3)  # thin (0 checked) but not loud

    def test_openended_five_loud_four_silent(self):
        rows = [HEADER] + [self.fear_row("2026-03-0%d" % (i + 1)) for i in range(4)]
        self.write("\n".join(rows) + "\n")
        code, _, _ = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 3)  # thin, not loud
        rows = [HEADER] + [self.fear_row("2026-03-0%d" % (i + 1)) for i in range(5)]
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 4)
        self.assertIn("OPEN-ENDED: 5 cases (ALARM — 5+ undated worries)", out)

    def test_thin_report_declines_rate_but_keeps_lights(self):
        rows = [HEADER]
        rows.append(self.fear_row("2026-01-01", due="2026-01-15"))
        rows.append("2026-01-15\tcheck\t\t\t\t\t2\tmiss")
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 3)
        self.assertIn("DECLINE", out)
        self.assertIn("checked 1 = hit 0 + partial 0 + miss 1", out)
        self.assertNotIn("false alarms:", out)

    def test_thin_but_wolf_still_loud(self):
        # drop the health pair from SAMPLE: 4 checked (<5) while the
        # child-health chain keeps its 3 misses — thin AND loud.
        thin = "\n".join([
            HEADER,
            "2026-03-02\tfear\tchild-health\tcough turns into pneumonia\t2026-03-16\t2\t\t",
            "2026-03-16\tcheck\t\t\t\t\t2\tmiss",
            "2026-04-10\tfear\tmoney\tpullback margin-calls the position\t2026-05-10\t0\t\t",
            "2026-05-10\tcheck\t\t\t\t\t4\tpartial",
            "2026-05-08\tfear\tchild-health\tpneumonia this time for sure\t2026-05-22\t1\t\t",
            "2026-05-22\tcheck\t\t\t\t\t6\tmiss",
            "2026-07-06\tfear\tchild-health\tthird cough, wheezing\t2026-07-20\t2\t\t",
            "2026-07-20\tcheck\t\t\t\t\t8\tmiss",
        ])
        self.write(thin)
        code, out, _ = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 4)
        self.assertIn("DECLINE", out)
        self.assertIn("🔴 WOLF", out)

    def test_thin_wolves_still_judges_chains(self):
        self.write(SAMPLE)
        code, out, _ = self.cli("wolves", "--ledger", self.path)
        self.assertEqual(code, 4)
        self.assertNotIn("DECLINE", out)  # wolves has no global thin gate

    def test_wolves_no_chain_yet(self):
        rows = [HEADER, self.fear_row("2026-03-01", due="2026-03-15")]
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("wolves", "--ledger", self.path)
        self.assertEqual(code, 0)
        self.assertIn("no chain yet", out)

    def test_overdue_named_even_when_silent(self):
        rows = [HEADER]
        rows.append(self.fear_row("2026-01-01", topic="job", due="2026-01-05"))
        rows.append("2026-01-03\tcheck\t\t\t\t\t2\tmiss")
        rows.append(self.fear_row("2026-02-01", topic="t2", due="2026-02-05"))
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2026-02-08")
        self.assertIn("OVERDUE-CHECK: 1 case, oldest 3d", out)


class IdentityTest(TempLedgerCase):
    def test_full_ledger_validate_sound(self):
        self.write(SAMPLE)
        code, out, _ = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0)
        self.assertIn("ledger is sound", out)

    def test_nights_identity_with_unchecked(self):
        rows = [HEADER]
        rows.append("2026-01-01\tfear\ta\tone\t2026-01-10\t3\t\t")
        rows.append("2026-01-10\tcheck\t\t\t\t\t2\tmiss")
        rows.append("2026-01-02\tfear\tb\ttwo\t2026-01-12\t4\t\t")
        rows.append("2026-01-12\tcheck\t\t\t\t\t4\thit")
        rows.append("2026-01-03\tfear\tc\tthree\t2026-01-20\t5\t\t")  # unchecked
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0)
        self.assertIn("12 total = wolves 3 + half 0 + fires 4 + unchecked 5", out)
        code, out, _ = self.cli("report", "--ledger", self.path)
        self.assertIn("nights: 12 total = 3 for wolves that never came · 0 for half-wolves\n"
                      "        · 4 for real fires · 5 still on unchecked fears", out)

    def test_empty_nights_counts_zero_but_is_disclosed(self):
        rows = [HEADER]
        rows.append("2026-01-01\tfear\ta\tone\t2026-01-10\t\t\t")
        rows.append("2026-01-10\tcheck\t\t\t\t\t2\tmiss")
        rows.append("2026-01-02\tfear\tb\ttwo\t2026-01-12\t2\t\t")
        rows.append("2026-01-12\tcheck\t\t\t\t\t4\tmiss")
        rows.append("2026-01-03\tfear\tc\tthree\t2026-01-20\t\t\t")
        rows.append("2026-01-20\tcheck\t\t\t\t\t6\tmiss")
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 3)  # thin
        self.assertIn("nights not recorded on 2 fears, counted as 0", out)

    def test_check_on_filing_day_is_legal(self):
        rows = [HEADER]
        rows.append("2026-01-01\tfear\ta\tone\t2026-01-01\t\t\t")
        rows.append("2026-01-01\tcheck\t\t\t\t\t2\thit")
        self.write("\n".join(rows) + "\n")
        code, _, err = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0, err)


class CliSurfaceTest(TempLedgerCase):
    def test_type_aliases(self):
        rows = [HEADER]
        rows.append("2026-01-01\tworry\ta\tone\t2026-01-10\t\t\t")
        rows.append("2026-01-10\tresolved\t\t\t\t\t2\tmiss")
        self.write("\n".join(rows) + "\n")
        code, _, err = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0, err)

    def test_outcome_aliases(self):
        rows = [HEADER]
        rows.append("2026-01-01\tfear\ta\tone\t2026-01-10\t\t\t")
        rows.append("2026-01-10\tcheck\t\t\t\t\t2\tno")
        self.write("\n".join(rows) + "\n")
        code, _, _ = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0)

    def test_asof_must_be_strict(self):
        self.write(SAMPLE)
        code, _, err = self.cli("report", "--ledger", self.path, "--as-of", "2026-5-1")
        self.assertEqual(code, 2)
        self.assertIn("bad date", err)

    def test_comments_and_blank_lines_skipped(self):
        # ref is a PHYSICAL line number: comments and blanks still count rows.
        text = "\n".join([
            "# a note",
            "",
            HEADER,
            "2026-01-01\tfear\ta\tone\t2026-01-10\t\t\t",
            "2026-01-10\tcheck\t\t\t\t\t4\tmiss",
            "# mid note",
            "2026-02-01\tfear\tb\ttwo\t2026-02-15\t\t\t",
            "2026-02-15\tcheck\t\t\t\t\t7\tmiss",
            "",
            "# trailing note",
        ])
        self.write(text)
        code, _, err = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0, err)

    def test_case_insensitive_header(self):
        self.write(SAMPLE.replace("date\ttype\ttopic", "Date\tType\tTopic", 1))
        code, _, _ = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0)

    def test_cjk_fear_text_renders_aligned(self):
        rows = [HEADER]
        rows.append("2026-01-01\tfear\t孩子健康\t咳嗽拖成肺炎住院\t2026-01-15\t2\t\t")
        rows.append("2026-01-15\tcheck\t\t\t\t\t2\tmiss")
        rows.append("2026-02-01\tfear\ta\tshort\t2026-02-15\t1\t\t")
        rows.append("2026-02-15\tcheck\t\t\t\t\t4\tmiss")
        self.write("\n".join(rows) + "\n")
        code, out, _ = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 3)
        self.assertIn("咳嗽拖成肺炎住院", out)
        for line in out.splitlines():
            if line.startswith("#"):
                self.assertIn("nights", line)


if __name__ == "__main__":
    unittest.main()
