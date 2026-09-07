# -*- coding: utf-8 -*-
"""same-frame acceptance tests.

Fixture numbers are hand-computed and pinned as literals: the Chen family
ledger has 13 gatherings / 7 members, Σattendance 69 = Σwho 69, 21 pairs with
Σco-appearances 162 = ΣC(k,2) 162, grandpa's gap 652 days (streak 6) and the
last full house 697 days before the ledger's own last date. One hand value
(698) was corrected by the arithmetic itself — August has 31 days.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import same_frame  # noqa: E402

EXAMPLE_LEDGER = os.path.join(HERE, "..", "examples", "family.tsv")

HEADER = "date\tevent\twho"

SAMPLE = "\n".join([
    HEADER,
    "2023-01-22\t春节全家福\t爷爷,奶奶,爸,妈,大姐,二哥,小妹",
    "2023-05-02\t大姐婚礼\t爷爷,奶奶,爸,妈,大姐,二哥,小妹",
    "2023-09-29\t中秋\t爷爷,奶奶,爸,妈,二哥",
    "2024-02-10\t春节\t爷爷,奶奶,爸,妈,大姐,二哥,小妹",
    "2024-06-08\t端午\t爸,妈,二哥,爷爷",
    "2024-10-02\t国庆\t爷爷,奶奶,爸,妈,大姐,二哥,小妹",
    "2024-11-16\t爷爷住院复查\t爸,大姐,爷爷",
    "2025-01-29\t春节\t奶奶,爸,妈,大姐,二哥,小妹",
    "2025-05-11\t母亲节\t妈,大姐,小妹",
    "2025-10-04\t国庆\t奶奶,爸,妈,大姐,二哥,小妹",
    "2026-02-16\t春节\t奶奶,爸,妈,大姐,小妹",
    "2026-05-31\t小妹搬家\t妈,大姐,小妹,二哥",
    "2026-08-30\t奶奶生日\t奶奶,爸,妈,大姐,小妹",
])


class TempLedgerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "family.tsv")

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = same_frame.main(list(argv))
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
        return code, out.getvalue(), err.getvalue()


class SampleLedgerTest(TempLedgerCase):
    """the shipped Chen-family example: hand-computed values pinned."""

    def test_report_numbers(self):
        code, out, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(code, 4)  # FADED + DRIFT, both by design
        for needle in ("13 gatherings · 7 members · as-of 2026-08-30",
                       "Σattendance" if False else "last: 2024-10-02 — 697 days ago",
                       "4 of 13 gatherings had everyone"):
            self.assertIn(needle, out)
        # grandpa: 7 of 13, 53.8%, 652 days, tail streak 6
        self.assertIn("53.8%", out)
        self.assertIn("652", out)
        self.assertIn("🔴 FADED — 爷爷 last appeared 652 days ago (2024-11-16).", out)
        self.assertIn("🔴 DRIFT — everyone in one frame: 4 times, last on 2024-10-02.", out)

    def test_member_rows(self):
        code, out, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(code, 4)
        # 妈 attended 12 (92.3%), present at the last row, gap 0, streak 0
        self.assertIn("92.3%", out)
        # 二哥 last seen 2026-05-31, gap 91, streak 1
        self.assertIn("69.2%", out)
        self.assertIn("91", out)

    def test_pairs_matrix(self):
        code, out, _ = self.cli("pairs", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(code, 4)
        for needle in ("小妹–爷爷  4      2024-10-02  697",
                       "奶奶–爷爷  5      2024-10-02  697",
                       "爷爷–爸    7      2024-11-16  652",
                       "二哥–奶奶  7      2025-10-04  330",
                       "妈–爸      10     2026-08-30  0",
                       "← over full-line"):
            self.assertIn(needle, out)

    def test_time_machine_20251004(self):
        code, out, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER, "--as-of", "2025-10-04")
        self.assertEqual(code, 4)  # full-house drift just crossed (367 > 365)
        self.assertIn("last: 2024-10-02 — 367 days ago", out)
        self.assertIn("🔴 DRIFT", out)
        self.assertNotIn("🔴 FADED", out)  # grandpa at 322 days, line not reached yet
        self.assertIn("10 gatherings · 7 members", out)

    def test_time_machine_20250901_still_quiet(self):
        code, out, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER, "--as-of", "2025-09-01")
        self.assertEqual(code, 0)  # full house 334d, grandpa 289d — both under the line
        self.assertNotIn("🔴", out)
        self.assertIn("DRIFT: last full house 334 days ago (line 365d)", out)

    def test_validate_identity(self):
        code, out, _ = self.cli("validate", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(code, 0)
        self.assertIn("rows: 13 gatherings · 7 members · Σattendance 69 = Σwho 69", out)
        self.assertIn("pairs: 21 registered · Σco-appearances 162 = ΣC(k,2) 162", out)
        self.assertIn("ledger is sound", out)

    def test_byte_reproducible(self):
        _, first, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER)
        _, second, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER)
        self.assertEqual(first, second)

    def test_no_absolute_path(self):
        _, out, _ = self.cli("report", "--ledger", EXAMPLE_LEDGER)
        self.assertNotIn(EXAMPLE_LEDGER, out)
        self.assertIn("family.tsv", out)


class BrokenLedgerTest(TempLedgerCase):
    def expect_broken(self, text, needle, cmd="report"):
        self.write(text)
        code, _, err = self.cli(cmd, "--ledger", self.path)
        self.assertEqual(code, 2, err)
        self.assertIn(needle, err)

    def test_bad_header(self):
        self.expect_broken("date\twho\n", "bad header")

    def test_missing_column(self):
        self.expect_broken(HEADER + "\n2023-01-22\t春节\n", "want 3 tab-separated fields, got 2")

    def test_extra_column_beyond_tail_tolerated(self):
        self.write(SAMPLE + "\t\t\n")  # pasted with trailing tabs
        code, _, err = self.cli("report", "--ledger", self.path)
        self.assertNotEqual(code, 2, err)

    def test_nonzero_padded_date(self):
        self.expect_broken(HEADER + "\n2023-1-22\t\t爷爷\n", "bad date '2023-1-22'")

    def test_impossible_calendar_date(self):
        self.expect_broken(HEADER + "\n2023-02-30\t\t爷爷\n", "impossible calendar date")

    def test_empty_who(self):
        self.expect_broken(HEADER + "\n2023-01-22\t春节\t\n", "who is empty")

    def test_duplicate_member_in_row(self):
        self.expect_broken(HEADER + "\n2023-01-22\t春节\t爷爷,爷爷\n", "duplicate member")

    def test_alias_bad_format(self):
        self.write(SAMPLE)
        code, _, err = self.cli("report", "--ledger", self.path, "--alias", "爷爷")
        self.assertEqual(code, 2)
        self.assertIn("bad --alias", err)

    def test_alias_collapse_creates_duplicate(self):
        self.write(HEADER + "\n2023-01-22\t\t爷爷,爷\n2024-02-10\t\t奶奶\n")
        code, _, err = self.cli("report", "--ledger", self.path, "--alias", "爷=爷爷")
        self.assertEqual(code, 2)
        self.assertIn("collapsed distinct members", err)

    def test_alias_self_mapping_idempotent(self):
        self.write(SAMPLE)
        _, plain, _ = self.cli("report", "--ledger", self.path)
        _, aliased, _ = self.cli("report", "--ledger", self.path, "--alias", "爷爷=爷爷")
        self.assertEqual(plain, aliased)

    def test_alias_merges_names(self):
        self.write(HEADER + "\n2023-01-22\t\t爷,奶\n2025-06-01\t\t爷\n")
        code, out, _ = self.cli("report", "--ledger", self.path, "--alias", "爷=爷爷")
        self.assertEqual(code, 4)  # 爷爷 gap > line, and the pair never full
        self.assertIn("爷爷", out)


class EmptyLedgerTest(TempLedgerCase):
    def expect_decline(self, text=None, missing=False):
        if not missing:
            self.write(text)
        code, _, err = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 3, err)

    def test_zero_bytes(self):
        self.expect_decline("")

    def test_blank_lines_only(self):
        self.expect_decline("\n \n")

    def test_header_no_rows(self):
        self.expect_decline(HEADER + "\n")

    def test_comments_only(self):
        self.expect_decline("# nothing\n")

    def test_missing_file(self):
        self.expect_decline(missing=True)

    def test_asof_before_everything(self):
        self.write(SAMPLE)
        code, _, err = self.cli("report", "--ledger", self.path, "--as-of", "2022-01-01")
        self.assertEqual(code, 3)
        self.assertIn("nothing on or before", err)


class ThinLedgerTest(TempLedgerCase):
    def test_one_row_declines_but_shows_members(self):
        self.write(HEADER + "\n2023-01-22\t春节\t爷爷,奶奶\n")
        code, out, _ = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 3)
        self.assertIn("DECLINE", out)
        self.assertIn("an interval needs at least two", out)
        self.assertIn("爷爷", out)  # member table still true
        self.assertNotIn("🔴", out)

    def test_one_row_pairs_also_declines(self):
        self.write(HEADER + "\n2023-01-22\t春节\t爷爷,奶奶\n")
        code, out, _ = self.cli("pairs", "--ledger", self.path)
        self.assertEqual(code, 3)
        self.assertIn("DECLINE", out)


class GateThresholdTest(TempLedgerCase):
    """line semantics: gap == line is quiet, gap == line + 1 alarms.

    fixture: full house on 2023-01-01, then grandpa alone on 2023-06-01.
    2023 is not a leap year, so as-of 2024-01-01 puts both the full-house
    gap and grandma's gap at exactly 365; one day later it is 366.
    """

    def fixture(self):
        return HEADER + "\n2023-01-01\t\t爷爷,奶奶\n2023-06-01\t\t爷爷\n"

    def test_exactly_on_both_lines_is_quiet(self):
        self.write(self.fixture())
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2024-01-01")
        self.assertEqual(code, 0)
        self.assertIn("FADED: nobody beyond 365d without a frame", out)
        self.assertIn("DRIFT: last full house 365 days ago (line 365d)", out)

    def test_line_plus_one_alarms_both(self):
        self.write(self.fixture())
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2024-01-02")
        self.assertEqual(code, 4)
        self.assertIn("🔴 FADED — 奶奶 last appeared 366 days ago (2023-01-01).", out)
        self.assertIn("366 days ago", out)

    def test_fade_line_flag_overrides(self):
        self.write(self.fixture())
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2024-01-02",
                                "--fade-line", "400", "--full-line", "400")
        self.assertEqual(code, 0)
        self.assertNotIn("FADED —", out)

    def test_full_line_flag_overrides(self):
        self.write(self.fixture())
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2024-01-02",
                                "--full-line", "400", "--fade-line", "400")
        self.assertEqual(code, 0)

    def test_never_full_house_is_drift(self):
        # 妈 registers and never stands in a frame with everyone else
        text = "\n".join([
            HEADER,
            "2024-01-01\t\t爷爷,奶奶",
            "2024-06-01\t\t爷爷,爸",
        ]) + "\n"
        self.write(text)
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2024-06-01")
        self.assertEqual(code, 4)
        self.assertIn("no gathering on record ever had everyone", out)
        self.assertIn("never", out.lower() or out)  # full-house section says never

    def test_never_full_with_faded_member(self):
        text = "\n".join([
            HEADER,
            "2024-01-01\t\t爷爷,奶奶",
            "2024-03-01\t\t爷爷,爸",
        ]) + "\n"
        self.write(text)
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2025-06-01")
        self.assertEqual(code, 4)
        self.assertIn("🔴 FADED — 奶奶", out)
        self.assertIn("no gathering on record ever had everyone", out)

    def test_only_first_row_full_anchors_full_house_to_it(self):
        text = "\n".join([
            HEADER,
            "2023-01-01\t\t爷爷,奶奶",
            "2023-03-01\t\t爷爷",
            "2024-02-02\t\t爷爷",
        ]) + "\n"
        self.write(text)
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2024-02-02")
        self.assertEqual(code, 4)
        self.assertIn("1 of 3 gatherings had everyone. last: 2023-01-01", out)
        self.assertIn("🔴 FADED — 奶奶 last appeared 397 days ago (2023-01-01).", out)

    def test_member_who_never_appears_after_registration_counts_in_full(self):
        # 奶奶 appears only in row 1, so 'everyone in one frame' can only be row 1
        text = "\n".join([
            HEADER,
            "2024-01-01\t\t爷爷,奶奶",
            "2024-03-01\t\t爷爷",
            "2024-05-01\t\t爷爷",
        ]) + "\n"
        self.write(text)
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2024-05-01")
        self.assertEqual(code, 0)  # 121 days: under both lines, but anchored to row 1
        self.assertIn("last: 2024-01-01 — 121 days ago", out)


class OrderingTest(TempLedgerCase):
    def test_rows_sorted_by_date_not_file_order(self):
        text = "\n".join([
            HEADER,
            "2025-06-01\tlater\t爷爷,奶奶",
            "2024-01-01\tearlier\t爷爷,奶奶",
        ]) + "\n"
        self.write(text)
        code, out, _ = self.cli("report", "--ledger", self.path)
        self.assertEqual(code, 0)
        # last full house = 2025-06-01 regardless of file order
        self.assertIn("last: 2025-06-01", out)

    def test_streak_counts_tail_misses_only(self):
        text = "\n".join([
            HEADER,
            "2024-01-01\t\t爷爷,奶奶",
            "2024-03-01\t\t爷爷",
            "2024-05-01\t\t爷爷",
        ]) + "\n"
        self.write(text)
        code, out, _ = self.cli("report", "--ledger", self.path, "--as-of", "2024-05-01")
        self.assertEqual(code, 0)  # 121d: under both lines
        # 奶奶 missed the last two gatherings in a row -> streak 2
        grandma = [ln for ln in out.splitlines() if ln.startswith("奶奶")][0]
        self.assertEqual(grandma.split()[-1], "2")


class IdentityTest(TempLedgerCase):
    def test_validate_small_ledger(self):
        text = "\n".join([
            HEADER,
            "2024-01-01\t\t爷爷,奶奶,爸",
            "2024-06-01\t\t爷爷,爸",
            "2024-09-01\t\t妈",
        ]) + "\n"
        self.write(text)
        code, out, _ = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0)
        # Σwho = 3+2+1 = 6; pairs per row C(3,2)+C(2,2)+C(1,2)=3+1+0=4
        self.assertIn("Σattendance 6 = Σwho 6", out)
        self.assertIn("Σco-appearances 4 = ΣC(k,2) 4", out)
        self.assertIn("ledger is sound", out)


class CliSurfaceTest(TempLedgerCase):
    def test_who_separators(self):
        text = "\n".join([
            HEADER,
            "2024-01-01\t\t爷爷、奶奶、爸",
            "2024-06-01\t\t爷爷 奶奶 爸",
            "2024-09-01\t\t爷爷;奶奶;爸",
        ]) + "\n"
        self.write(text)
        code, out, _ = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0, out)
        code, out, _ = self.cli("report", "--ledger", self.path)
        self.assertIn("3 members", out)  # separators all recognized

    def test_empty_event_ok(self):
        self.write(HEADER + "\n2024-01-01\t\t爷爷,奶奶\n2024-06-01\t\t爷爷,奶奶\n")
        code, _, err = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0, err)

    def test_case_insensitive_header(self):
        self.write("Date\tEvent\tWho\n2024-01-01\t\t爷爷\n2024-06-01\t\t爷爷\n")
        code, _, _ = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0)

    def test_comments_and_blanks_skipped(self):
        text = "# a note\n\n" + HEADER + "\n2024-01-01\t\t爷爷\n2024-06-01\t\t爷爷\n\n# tail\n"
        self.write(text)
        code, _, _ = self.cli("validate", "--ledger", self.path)
        self.assertEqual(code, 0)

    def test_asof_must_be_strict(self):
        self.write(SAMPLE)
        code, _, err = self.cli("report", "--ledger", self.path, "--as-of", "2025-6-1")
        self.assertEqual(code, 2)
        self.assertIn("bad date", err)

    def test_cjk_member_column_alignment(self):
        self.write(HEADER + "\n2024-01-01\t\t爷爷,奶奶\n2024-06-01\t\t爷爷,奶奶\n")
        code, out, _ = self.cli("report", "--ledger", self.path)
        member_lines = [ln for ln in out.splitlines() if ln.startswith(("爷爷", "奶奶"))]
        self.assertEqual(len(member_lines), 2)
        self.assertEqual(len(member_lines[0]), len(member_lines[1]))


if __name__ == "__main__":
    unittest.main()
