"""
Automated acceptance tests for decision-debt.

Covers the published acceptance criteria (formula + every command) using the
stdlib `unittest`, so the suite runs with `python -m unittest` and no extras.
All scoring tests are deterministic thanks to the injected `as_of` date.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import decision_debt as dd  # noqa: E402


def ledgpath(tmp: Path) -> Path:
    return tmp / "ledger.json"


class FormulaTests(unittest.TestCase):
    """Acceptance: the debt score is deterministic and matches the documented formula."""

    def D(self, opened="2026-08-01", reviewed="2026-08-01", reopens=0, weight=3, status="open"):
        return dd.Decision(
            id="x", title="t", context="", options=[], weight=weight,
            opened=opened, last_reviewed=reviewed, reopens=reopens,
            status=status, outcome=None, closed=None,
        )

    def test_brand_new_decision_has_zero_debt(self):
        # AC: a decision opened today has age 0 -> debt 0
        today = date(2026, 8, 12)
        d = self.D(opened="2026-08-12", reviewed="2026-08-12")
        self.assertEqual(dd.compute_debt(d, today), 0.0)

    def test_simple_aging(self):
        # AC: weight 3, age 10, reviewed today, no reopens -> 3*10*1*1 = 30.0
        today = date(2026, 8, 11)
        d = self.D(opened="2026-08-01", reviewed="2026-08-11")
        self.assertEqual(dd.compute_debt(d, today), 30.0)

    def test_staleness_raises_debt(self):
        # AC: unreviewed decisions cost more. age 10, unreviewed 10d -> 3*10*(1+10/14)
        today = date(2026, 8, 11)
        d = self.D(opened="2026-08-01", reviewed="2026-08-01")
        expected = round(3 * 10 * 1.0 * (1 + 10 / 14), 1)  # 51.4
        self.assertEqual(dd.compute_debt(d, today), expected)

    def test_reopen_raises_interest_rate(self):
        # AC: each reopen adds 50% to rate. 2 reopens -> base_interest 2.0
        today = date(2026, 8, 11)
        d = self.D(opened="2026-08-01", reviewed="2026-08-11", reopens=2)
        self.assertEqual(dd.compute_debt(d, today), 3 * 10 * 2.0 * 1.0)  # 60.0

    def test_staleness_is_capped(self):
        # AC: very old review caps staleness at 1 + STALENESS_CAP (=6)
        today = date(2026, 12, 1)
        d = self.D(opened="2026-01-01", reviewed="2026-01-01", weight=5)
        age = (today - date(2026, 1, 1)).days
        staleness = 1 + dd.STALENESS_CAP  # 6.0
        expected = round(5 * age * 1.0 * staleness, 1)
        self.assertEqual(dd.compute_debt(d, today), expected)

    def test_closed_decisions_have_zero_debt(self):
        today = date(2026, 12, 1)
        d = self.D(opened="2026-01-01", reviewed="2026-01-01", status="committed")
        self.assertEqual(dd.compute_debt(d, today), 0.0)

    def test_debt_ranking_sorted_desc(self):
        today = date(2026, 8, 12)
        old = self.D(opened="2026-07-01", reviewed="2026-07-01")           # high
        new = self.D(opened="2026-08-01", reviewed="2026-08-01", weight=1)  # low
        closed = self.D(opened="2026-07-01", status="committed")           # excluded
        ranked = dd.debt_ranking([new, old, closed], today)
        self.assertEqual([d.id for d, _ in ranked], [old.id, new.id])
        self.assertTrue(ranked[0][1] > ranked[1][1])


class CommandTests(unittest.TestCase):
    """Acceptance: each CLI command behaves correctly, deterministically."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = ledgpath(Path(self.tmp.name))
        dd.cmd_init(self.path)
        self.as_of = date(2026, 8, 12)

    def tearDown(self):
        self.tmp.cleanup()

    # init -----------------------------------------------------------------
    def test_init_is_idempotent_protected(self):
        # AC: re-running init refuses to overwrite without --force
        with self.assertRaises(SystemExit):
            dd.cmd_init(self.path)
        dd.cmd_init(self.path, force=True)  # ok with force

    # add ------------------------------------------------------------------
    def test_add_creates_correct_decision(self):
        dd.cmd_add(self.path, title="Pick auth provider", context="Need SSO",
                   options=["Auth0", "Clerk"], weight=4, as_of=date(2026, 8, 1))
        ledg = dd.load_ledger(self.path)
        self.assertEqual(len(ledg["decisions"]), 1)
        d = ledg["decisions"][0]
        self.assertEqual(d.id, "pick-auth-provider")
        self.assertEqual(d.weight, 4)
        self.assertEqual(d.status, "open")
        self.assertEqual(d.opened, "2026-08-01")
        self.assertEqual(d.last_reviewed, "2026-08-01")
        self.assertEqual(d.reopens, 0)
        self.assertEqual(d.options, ["Auth0", "Clerk"])

    def test_add_unique_id_on_duplicate_slug(self):
        dd.cmd_add(self.path, title="Hire", as_of=date(2026, 8, 1))
        dd.cmd_add(self.path, title="Hire", as_of=date(2026, 8, 1))
        ledg = dd.load_ledger(self.path)
        ids = sorted(d.id for d in ledg["decisions"])
        self.assertEqual(ids, ["hire", "hire-2"])

    def test_add_rejects_invalid_weight(self):
        with self.assertRaises(SystemExit):
            dd.cmd_add(self.path, title="x", weight=7, as_of=self.as_of)

    def test_add_rejects_duplicate_explicit_id(self):
        dd.cmd_add(self.path, title="A", did="dup", as_of=self.as_of)
        with self.assertRaises(SystemExit):
            dd.cmd_add(self.path, title="B", did="dup", as_of=self.as_of)

    # list -----------------------------------------------------------------
    def test_list_sorted_by_debt_desc(self):
        dd.cmd_add(self.path, title="Old", as_of=date(2026, 7, 1))   # 504.0
        dd.cmd_add(self.path, title="New", as_of=date(2026, 8, 1))   # ~58.9
        out = dd.cmd_list(self.path, status="open", as_of=self.as_of)
        self.assertIn("Old", out.splitlines()[2])
        lines = [l for l in out.splitlines() if l.startswith("old") or l.startswith("new")]
        self.assertEqual(lines[0][:3], "old")

    def test_list_json_is_valid(self):
        dd.cmd_add(self.path, title="A", as_of=date(2026, 8, 1))
        out = dd.cmd_list(self.path, as_of=self.as_of, as_json=True)
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertIn("debt", data[0])

    # review ---------------------------------------------------------------
    def test_review_top_n_and_empty(self):
        for i in range(7):
            dd.cmd_add(self.path, title=f"D{i}", as_of=date(2026, 8, 1))
        out = dd.cmd_review(self.path, top=3, as_of=self.as_of)
        # header + blank + 3 blocks + blank + ritual lines
        blocks = [l for l in out.splitlines() if l.startswith("  1.") or l.startswith("  2.") or l.startswith("  3.")]
        self.assertEqual(len(blocks), 3)
        # empty case (must init a fresh ledger first)
        empty_tmp = Path(tempfile.mkdtemp())
        empty_path = ledgpath(empty_tmp)
        dd.cmd_init(empty_path)
        empty = dd.cmd_review(empty_path, as_of=self.as_of)
        self.assertIn("debt-free", empty)

    # touch ----------------------------------------------------------------
    def test_touch_resets_staleness_and_lowers_debt(self):
        dd.cmd_add(self.path, title="X", as_of=date(2026, 7, 1))  # opened & reviewed 7/1
        before = dd.compute_debt(dd.load_ledger(self.path)["decisions"][0], self.as_of)
        dd.cmd_touch(self.path, "x", as_of=self.as_of)            # reviewed today
        after = dd.compute_debt(dd.load_ledger(self.path)["decisions"][0], self.as_of)
        self.assertEqual(dd.load_ledger(self.path)["decisions"][0].last_reviewed, "2026-08-12")
        self.assertLess(after, before)
        # 504 -> 126 for weight 3, age 42
        self.assertEqual(after, 3 * 42 * 1.0 * 1.0)  # 126.0

    # commit / abandon / reopen -------------------------------------------
    def test_commit_closes_and_records_outcome(self):
        dd.cmd_add(self.path, title="X", as_of=date(2026, 8, 1))
        dd.cmd_commit(self.path, "x", outcome="Go with Auth0", as_of=self.as_of)
        d = dd.load_ledger(self.path)["decisions"][0]
        self.assertEqual(d.status, "committed")
        self.assertEqual(d.outcome, "Go with Auth0")
        self.assertEqual(d.closed, "2026-08-12")
        # excluded from open list
        self.assertEqual(dd.debt_ranking([d], self.as_of), [])

    def test_abandon_closes(self):
        dd.cmd_add(self.path, title="X", as_of=date(2026, 8, 1))
        dd.cmd_abandon(self.path, "x", reason="No longer needed", as_of=self.as_of)
        d = dd.load_ledger(self.path)["decisions"][0]
        self.assertEqual(d.status, "abandoned")
        self.assertEqual(d.outcome, "No longer needed")

    def test_reopen_increments_and_raises_rate(self):
        dd.cmd_add(self.path, title="X", as_of=date(2026, 8, 1))
        dd.cmd_commit(self.path, "x", outcome="A", as_of=self.as_of)
        dd.cmd_reopen(self.path, "x", as_of=self.as_of)
        d = dd.load_ledger(self.path)["decisions"][0]
        self.assertEqual(d.status, "open")
        self.assertEqual(d.reopens, 1)
        # reopen resets last_reviewed to today -> staleness 1, base_interest 1.5
        self.assertEqual(d.last_reviewed, "2026-08-12")
        self.assertEqual(dd.compute_debt(d, self.as_of), round(3 * 11 * 1.5 * 1.0, 1))  # 49.5

    def test_reopen_open_decision_errors(self):
        dd.cmd_add(self.path, title="X", as_of=date(2026, 8, 1))
        with self.assertRaises(SystemExit):
            dd.cmd_reopen(self.path, "x", as_of=self.as_of)

    # report ---------------------------------------------------------------
    def test_report_counts_and_totals(self):
        dd.cmd_add(self.path, title="A", as_of=date(2026, 7, 1))   # 504.0 open
        dd.cmd_add(self.path, title="B", as_of=date(2026, 8, 1))   # open
        dd.cmd_commit(self.path, "b", outcome="done", as_of=self.as_of)
        out = dd.cmd_report(self.path, as_of=self.as_of)
        self.assertIn("open        : 1", out)
        self.assertIn("committed   : 1", out)
        self.assertIn("Total open debt: 504.0", out)
        self.assertIn("Hottest: a = 504.0", out)

    # export ---------------------------------------------------------------
    def test_export_markdown_decision_log(self):
        dd.cmd_add(self.path, title="Pick framework", context="perf",
                   options=["A", "B"], weight=4, as_of=date(2026, 8, 1))
        dd.cmd_commit(self.path, "pick-framework", outcome="Use A", as_of=self.as_of)
        dd.cmd_add(self.path, title="Dead end", as_of=date(2026, 8, 1))
        dd.cmd_abandon(self.path, "dead-end", reason="moot", as_of=self.as_of)
        out = dd.cmd_export(self.path, as_of=self.as_of)
        self.assertIn("# Decision Log", out)
        self.assertIn("## Committed", out)
        self.assertIn("pick-framework", out)
        self.assertIn("Use A", out)
        self.assertIn("## Abandoned", out)
        self.assertIn("dead-end", out)


class CliSmokeTests(unittest.TestCase):
    """Acceptance: the CLI entrypoint runs end-to-end on macOS python3 stdlib."""

    def test_full_workflow_via_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledg = os.path.join(tmp, "ledger.json")
            py = [sys.executable, str(ROOT / "decision_debt.py"), "--ledger", ledg]

            def run(*args):
                return subprocess.run(py + list(args), capture_output=True, text=True)

            r = run("init"); self.assertEqual(r.returncode, 0, r.stderr)
            r = run("add", "--title", "Decide on CI provider", "--option", "GitHub Actions",
                    "--option", "CircleCI", "--weight", "4")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run("list"); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Decide on CI provider", r.stdout)
            r = run("review", "--top", "3"); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("hottest", r.stdout.lower())
            r = run("touch", "decide-on-ci-provider"); self.assertEqual(r.returncode, 0, r.stderr)
            r = run("commit", "decide-on-ci-provider", "--outcome", "GitHub Actions")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run("report"); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Decision Debt Report", r.stdout)
            r = run("export"); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("# Decision Log", r.stdout)
            self.assertIn("GitHub Actions", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
