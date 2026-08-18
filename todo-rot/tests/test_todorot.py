#!/usr/bin/env python3
"""Acceptance tests for todo-rot (承诺锈蚀).

All acceptance criteria from README.md are pinned here as unittest cases.
Git integration tests build real temporary repositories with pinned dates
(deterministic commit hashes, deterministic ages via --as-of). Parser and
unit tests run against fixture strings and pure functions — no git needed.

Run:  python3 -m unittest discover -s todo-rot/tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

import todo_rot as tr  # noqa: E402

CLI = (sys.executable, str(ROOT / "todo_rot.py"))

ALICE = ("Alice Chen", "alice@corp.dev")
BOB = ("Bob Lin", "bob@corp.dev")
CHEN = ("Chen Wu", "chen@corp.dev")


# ---------------------------------------------------------------------------
# Git fixture helpers


class GitRepo:
    def __init__(self, td, name):
        self.path = os.path.join(td, name)
        os.makedirs(self.path)
        self.git("init", "-q")

    def git(self, *args, env=None):
        proc = subprocess.run(["git", "-C", self.path] + list(args),
                              capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise AssertionError("git %s: %s" % (args, proc.stderr))
        return proc.stdout

    def commit(self, files, author, when, msg, mv=None):
        """files: {relpath: content|None(delete)}; when: ISO with offset."""
        for rel, content in files.items():
            full = os.path.join(self.path, rel)
            if content is None:
                os.remove(full)
                continue
            d = os.path.dirname(full)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(full, "w") as fh:
                fh.write(content)
        if mv:
            d = os.path.dirname(os.path.join(self.path, mv[1]))
            if d:
                os.makedirs(d, exist_ok=True)
            self.git("mv", mv[0], mv[1])
        env = dict(os.environ,
                   GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1],
                   GIT_COMMITTER_NAME=author[0], GIT_COMMITTER_EMAIL=author[1],
                   GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg, env=env)

    def write(self, rel, content):
        """Working-tree edit without committing (uncommitted scenarios)."""
        full = os.path.join(self.path, rel)
        d = os.path.dirname(full)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)

    def run(self, *args):
        proc = subprocess.run(list(CLI) + list(args), cwd=self.path,
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr


AS_OF = "2026-08-18"


def ledger_json(repo, *extra):
    led = tr.build_report(repo.path, [], date.fromisoformat(AS_OF))
    return led


# ---------------------------------------------------------------------------
# Pure functions


class NormTests(unittest.TestCase):
    def test_strips_owner_parens(self):
        self.assertEqual(tr.normalize_text("TODO", "(alice): fix it"),
                         tr.normalize_text("TODO", ": fix it"))

    def test_strips_issue_and_date(self):
        self.assertEqual(tr.normalize_text("TODO", "fix x (see #12, due 2024-02-03)"),
                         tr.normalize_text("TODO", "fix x"))

    def test_normalizes_punct_and_case(self):
        self.assertEqual(tr.normalize_text("FIXME", ":  Race on   REFUND."),
                         tr.normalize_text("FIXME", "race on refund"))

    def test_strips_c_comment_tail(self):
        self.assertEqual(tr.normalize_text("TODO", "handle null */"),
                         tr.normalize_text("TODO", "handle null"))

    def test_marker_kept_in_key(self):
        self.assertNotEqual(tr.normalize_text("TODO", "fix x"),
                            tr.normalize_text("FIXME", "fix x"))

    def test_length_capped(self):
        self.assertLessEqual(len(tr.normalize_text("TODO", "x" * 500)), 140)

    def test_marker_weights(self):
        self.assertEqual(tr.MARKER_WEIGHTS,
                         {"TODO": 1, "XXX": 2, "HACK": 3, "FIXME": 4})

    def test_bucket_boundaries(self):
        for age, want in [(0, "FRESH"), (29, "FRESH"), (30, "AGING"),
                          (179, "AGING"), (180, "STALE"), (364, "STALE"),
                          (365, "ANCIENT"), (99999, "ANCIENT")]:
            self.assertEqual(tr.bucket_of(age), want, "age %d" % age)

    def test_rot_score(self):
        self.assertEqual(tr.rot_score(4, 365), 4.0)
        self.assertEqual(tr.rot_score(1, 73), 0.2)
        self.assertEqual(tr.rot_score(2, 0), 0.0)

    def test_zombie_threshold(self):
        self.assertIsNone(tr.zombie_threshold(None))
        self.assertEqual(tr.zombie_threshold(100), 200)
        self.assertEqual(tr.zombie_threshold(5), tr.ZOMBIE_FLOOR_DAYS)

    def test_parse_iso_offset_and_z(self):
        self.assertEqual(tr.parse_iso("2024-01-10T09:00:00+08:00").hour, 9)
        self.assertEqual(tr.parse_iso("2024-01-10T09:00:00Z").hour, 9)


# ---------------------------------------------------------------------------
# Working-tree scan (no git)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="tr-scan-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def write(self, rel, content, binary=False):
        full = os.path.join(self.td, rel)
        os.makedirs(os.path.dirname(full) or self.td, exist_ok=True)
        if binary:
            content = content.encode("utf-8") if isinstance(content, str) else content
            with open(full, "wb") as fh:
                fh.write(content)
        else:
            with open(full, "w") as fh:
                fh.write(content)

    def test_finds_all_markers_with_location(self):
        self.write("a.py", "# TODO: one\nx = 1  # FIXME two\n# HACK three\n# XXX four\n")
        self.write("sub/b.js", "// TODO: nested\n")
        hits = tr.scan_tree(self.td, [])
        self.assertEqual([(h.marker, h.path, h.line) for h in hits], [
            ("TODO", "a.py", 1), ("FIXME", "a.py", 2),
            ("HACK", "a.py", 3), ("XXX", "a.py", 4),
            ("TODO", "sub/b.js", 1)])

    def test_no_lowercase_or_plural_matches(self):
        self.write("es.txt", "todo listo\nmuchos todos\nTODOS everywhere\n")
        self.assertEqual(tr.scan_tree(self.td, []), [])

    def test_owner_issue_date_extraction(self):
        self.write("a.py", "# TODO(alice): metrics #42 by 2024-01-01\n")
        h = tr.scan_tree(self.td, [])[0]
        self.assertEqual((h.owner, h.issue, h.declared), ("alice", "42", "2024-01-01"))

    def test_binary_skipped_by_ext_and_content(self):
        self.write("img.png", "TODO: hidden", binary=True)
        self.write("blob.txt", b"# TODO: null\x00byte\n", binary=True)
        self.assertEqual(tr.scan_tree(self.td, []), [])

    def test_skips_git_dir_and_exclude_prefix(self):
        self.write(".git/config", "# TODO: never\n")
        self.write("vendor/lib.py", "# TODO: vendored\n")
        self.write("app.py", "# TODO: kept\n")
        hits = tr.scan_tree(self.td, ["vendor"])
        self.assertEqual([h.path for h in hits], ["app.py"])

    def test_hit_dict_shape(self):
        self.write("a.py", "# FIXME(zach): crash #7\n")
        d = tr.scan_tree(self.td, [])[0].as_dict()
        self.assertEqual(d["weight"], 4)
        self.assertEqual(d["owner"], "zach")
        self.assertEqual(d["issue"], "#7")
        self.assertNotIn("declared_date", d)

    def test_empty_tree_renders(self):
        self.assertIn("0 promise markers", tr.render_scan(tr.scan_tree(self.td, [])))


# ---------------------------------------------------------------------------
# git log diff parsing (fixture strings, no git)


SAMPLE_LOG = (
    "\x1esha9\x1f2026-08-01T09:00:00+08:00\x1fChen\x1fchen@x.dev\n"
    "\n"
    "diff --git a/billing.py b/src/billing.py\n"
    "similarity index 100%\n"
    "rename from billing.py\n"
    "rename to src/billing.py\n"
    "diff --git a/flags.py b/flags.py\n"
    "new file mode 100644\n"
    "index 0000000..1111111\n"
    "--- /dev/null\n"
    "+++ b/flags.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+# XXX: temp flag\n"
    "+FLAG = True\n"
    "\x1esha1\x1f2024-01-10T09:00:00+08:00\x1fAlice\x1falice@x.dev\n"
    "\n"
    "diff --git a/app.py b/app.py\n"
    "deleted file mode 100644\n"
    "--- a/app.py\n"
    "+++ /dev/null\n"
    "@@ -1,2 +0,0 @@\n"
    "-# TODO: dying\n"
    "-x()\n"
    "diff --git a/b.py b/b.py\n"
    "index 111..222 100644\n"
    "--- a/b.py\n"
    "+++ b/b.py\n"
    "@@ -1 +1 @@\n"
    "-# TODO: old wording\n"
    "+# TODO: new wording\n"
)


class ParserTests(unittest.TestCase):
    def test_records_and_order(self):
        commits = tr.parse_log(SAMPLE_LOG)
        self.assertEqual([c.sha for c in commits], ["sha1", "sha9"])  # oldest first
        self.assertEqual(commits[0].author, "Alice")
        self.assertEqual(commits[-1].date.hour, 9)

    def test_rename_detected(self):
        fd = tr.parse_log(SAMPLE_LOG)[1].files[0]
        self.assertEqual((fd.status, fd.old_path, fd.path), ("R", "billing.py", "src/billing.py"))

    def test_new_and_deleted_files(self):
        files = tr.parse_log(SAMPLE_LOG)[1].files
        self.assertEqual(files[1].status, "A")
        self.assertEqual(files[1].plus, ["# XXX: temp flag", "FLAG = True"])
        self.assertEqual(tr.parse_log(SAMPLE_LOG)[0].files[0].status, "D")

    def test_hunk_lines_without_diff_headers(self):
        files = tr.parse_log(SAMPLE_LOG)[0].files
        self.assertEqual(files[1].minus, ["# TODO: old wording"])
        self.assertEqual(files[1].plus, ["# TODO: new wording"])
        # the +++/--- header lines must never leak into plus/minus
        self.assertNotIn("--- a/app.py", files[0].minus)

    def test_path_b_plain_and_quoted(self):
        self.assertEqual(tr._path_b("diff --git a/x.py b/src/x.py"), "src/x.py")
        self.assertEqual(tr._path_b('diff --git a/a b/"weird name.py"'), "weird name.py")

    def test_marker_events(self):
        ev = tr.marker_events(["# TODO(alice): fix x #1", "plain line"])
        self.assertEqual(len(ev), 1)
        marker, norm, raw = ev[0]
        self.assertEqual(marker, "TODO")
        self.assertEqual(norm, tr.normalize_text("TODO", "(alice): fix x #1"))

    def test_lines_before_first_hunk_ignored(self):
        diff = ("diff --git a/a b/a\nindex 1..2\n--- a/a\n+++ b/a\n"
                "@@ -1 +1 @@\n++# TODO: real\n")
        fd = tr.parse_diff(diff)[0]
        self.assertEqual(fd.plus, ["+# TODO: real"])


# ---------------------------------------------------------------------------
# Ledger replay on synthetic events (no git)


def synth_commit(when, author, files):
    c = tr.Commit(sha=when + author, date=tr.parse_iso(when),
                  author=author, email=author + "@x.dev")
    for path, minus, plus, status, old in files:
        c.files.append(tr.FileDiff(path=path, minus=list(minus),
                                   plus=list(plus), status=status,
                                   old_path=old or ""))
    return c


class LedgerUnitTests(unittest.TestCase):
    def replay(self, *commits):
        led = tr.Ledger()
        for c in commits:
            tr._apply(led, c)
        return led

    def test_add_then_pending(self):
        led = self.replay(synth_commit("2024-01-01T00:00:00+00:00", "A", [
            ("f.py", [], ["# TODO: x"], "M", "")]))
        cur = led.current([])
        self.assertEqual(len(cur), 1)
        self.assertEqual(cur[0].author, "A")
        self.assertEqual(cur[0].weight, 1)

    def test_remove_pays_with_lifetime(self):
        led = self.replay(
            synth_commit("2024-01-01T00:00:00+00:00", "A", [("f.py", [], ["# TODO: x"], "M", "")]),
            synth_commit("2024-02-01T00:00:00+00:00", "B", [("f.py", ["# TODO: x"], [], "M", "")]))
        self.assertEqual(led.current([]), [])
        self.assertEqual(len(led.paid), 1)
        self.assertEqual(led.paid[0].lifetime_days, 31)
        self.assertEqual(led.paid[0].promise.author, "A")  # promiser, not payer

    def test_remove_without_intro_is_orphan(self):
        led = self.replay(synth_commit("2024-01-01T00:00:00+00:00", "A", [
            ("f.py", ["# TODO: ghost"], [], "M", "")]))
        self.assertEqual((led.paid, led.orphan_removals), ([], 1))

    def test_same_commit_resite_keeps_intro(self):
        led = self.replay(
            synth_commit("2024-01-01T00:00:00+00:00", "A", [("old.py", [], ["# TODO: x"], "M", "")]),
            synth_commit("2025-01-01T00:00:00+00:00", "B", [
                ("old.py", ["# TODO: x"], [], "M", ""),
                ("new.py", [], ["# TODO: x"], "M", "")]))
        cur = led.current([])
        self.assertEqual(len(cur), 1)
        self.assertEqual((cur[0].path, cur[0].intro_date.year), ("new.py", 2024))
        self.assertEqual((led.moves, led.paid), (1, []))

    def test_resite_without_history_falls_back_to_new_promise(self):
        led = self.replay(synth_commit("2024-01-01T00:00:00+00:00", "A", [
            ("old.py", ["# TODO: x"], [], "M", ""),
            ("new.py", [], ["# TODO: x"], "M", "")]))
        # must not lose the promise just because it never existed before
        self.assertEqual(len(led.current([])), 1)
        self.assertEqual(led.moves, 0)

    def test_deleted_file_kills_promises(self):
        led = self.replay(
            synth_commit("2024-01-01T00:00:00+00:00", "A", [("f.py", [], ["# TODO: x"], "M", "")]),
            synth_commit("2025-01-01T00:00:00+00:00", "A", [("f.py", [], [], "D", "")]))
        self.assertEqual(led.current([]), [])
        self.assertEqual((led.paid, len(led.died)), ([], 1))

    def test_text_edit_counts_as_pay_plus_new(self):
        led = self.replay(
            synth_commit("2024-01-01T00:00:00+00:00", "A", [("f.py", [], ["# TODO: old"], "M", "")]),
            synth_commit("2024-03-01T00:00:00+00:00", "A", [
                ("f.py", ["# TODO: old"], ["# TODO: new"], "M", "")]))
        self.assertEqual(len(led.paid), 1)
        self.assertEqual([p.norm for p in led.current([])],
                         [tr.normalize_text("TODO", "new")])

    def test_rename_rekeys_queue_and_path_attr(self):
        led = self.replay(
            synth_commit("2024-01-01T00:00:00+00:00", "A", [("a.py", [], ["# TODO: x"], "M", "")]),
            synth_commit("2025-01-01T00:00:00+00:00", "A", [("b.py", [], [], "R", "a.py")]))
        cur = led.current([])
        self.assertEqual((cur[0].path, cur[0].intro_date.year), ("b.py", 2024))

    def test_half_life_median_and_excludes(self):
        led = tr.Ledger()
        base = tr.Promise("keep.py", "TODO", "todo x", "x",
                          tr.parse_iso("2024-01-01T00:00:00+00:00"), "s", "A", "a@x")
        vend = tr.Promise("vendor/v.py", "TODO", "todo y", "y",
                          tr.parse_iso("2024-01-01T00:00:00+00:00"), "s", "A", "a@x")
        led.paid = [
            tr.Paid(base, tr.parse_iso("2024-01-11T00:00:00+00:00"), "s1", 10),
            tr.Paid(vend, tr.parse_iso("2024-03-01T00:00:00+00:00"), "s2", 60),
        ]
        self.assertEqual(led.half_life_days([]), 35.0)
        self.assertEqual(led.half_life_days(["vendor"]), 10.0)

    def test_no_paid_no_half_life(self):
        led = self.replay(synth_commit("2024-01-01T00:00:00+00:00", "A", [
            ("f.py", [], ["# TODO: x"], "M", "")]))
        self.assertIsNone(led.half_life_days([]))


# ---------------------------------------------------------------------------
# End-to-end with real git repositories


class GitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="tr-git-")
        self.repo = GitRepo(self.td, "r")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def ledger(self, *excludes, as_of=AS_OF):
        return tr.build_report(
            self.repo.path, list(excludes),
            date.fromisoformat(as_of) if as_of else None)

    def test_root_commit_promise_dated_and_authored(self):
        self.repo.commit({"a.py": "# TODO: from day one\n"}, ALICE,
                         "2024-01-10T09:00:00+08:00", "init")
        r = self.ledger()
        self.assertEqual(len(r.promises), 1)
        p = r.promises[0]
        self.assertEqual(p["intro_date"], "2024-01-10")
        self.assertEqual(p["age_days"], 951)
        self.assertTrue(p["author"].startswith("Alice Chen"))

    def test_paid_lifetime_exact(self):
        self.repo.commit({"a.py": "# TODO: x\n"}, ALICE,
                         "2024-01-10T09:00:00+08:00", "init")
        self.repo.commit({"a.py": "no promises\n"}, BOB,
                         "2024-03-01T09:00:00+08:00", "pay")
        r = self.ledger()
        self.assertEqual((r.paid, r.promises), (1, []))
        self.assertEqual(r.paid_lifetimes, [51])

    def test_half_life_median_of_three(self):
        self.repo.commit({"a.py": "# TODO: one\n# TODO: two\n# TODO: three\n"}, ALICE,
                         "2024-01-01T09:00:00+08:00", "init")
        self.repo.commit({"a.py": "# TODO: two\n# TODO: three\n"}, BOB,
                         "2024-01-11T09:00:00+08:00", "pay 1 (10d)")
        self.repo.commit({"a.py": "# TODO: three\n"}, BOB,
                         "2024-03-01T09:00:00+08:00", "pay 2 (60d)")
        self.repo.commit({"a.py": "clean\n"}, BOB,
                         "2025-01-01T09:00:00+08:00", "pay 3 (366d)")
        r = self.ledger()
        self.assertEqual(r.half_life, 60)

    def test_zombie_requires_half_life_and_threshold(self):
        self.repo.commit({"a.py": "# TODO: paid fast\n# FIXME: forever\n"}, ALICE,
                         "2024-01-01T09:00:00+08:00", "init")
        self.repo.commit({"a.py": "# FIXME: forever\n"}, BOB,
                         "2024-01-31T09:00:00+08:00", "pay (30d)")
        # half-life 30 -> threshold 60; FIXME is 960 days old by AS_OF
        self.repo.commit({"a.py": "# FIXME: forever\n# TODO: middle-aged\n"}, ALICE,
                         "2026-08-01T09:00:00+08:00", "young promise (17d)")
        r = self.ledger()
        self.assertEqual(r.half_life, 30)
        z = [p for p in r.promises if p.get("zombie")]
        self.assertEqual([p["marker"] for p in z], ["FIXME"])
        self.assertNotIn("zombie", r.promises[0] if r.promises[0]["marker"] == "TODO" else {})

    def test_no_paid_promises_no_zombie_flags(self):
        self.repo.commit({"a.py": "# TODO: never paid anything\n"}, ALICE,
                         "2020-01-01T09:00:00+08:00", "init")
        r = self.ledger()
        self.assertIsNone(r.half_life)
        self.assertNotIn("zombie", r.promises[0])
        txt = tr.render_halflife(r)
        self.assertIn("ever been paid", txt)

    def test_git_mv_preserves_age_and_path(self):
        self.repo.commit({"billing.py": "# FIXME: race\n"}, ALICE,
                         "2024-01-10T09:00:00+08:00", "init")
        self.repo.commit({}, CHEN, "2025-05-01T09:00:00+08:00", "mv",
                         mv=("billing.py", "src/billing.py"))
        r = self.ledger()
        self.assertEqual(len(r.promises), 1)
        self.assertEqual((r.promises[0]["file"], r.promises[0]["age_days"]),
                         ("src/billing.py", 951))

    def test_file_deletion_kills_promise(self):
        self.repo.commit({"legacy.py": "# TODO: shim\n"}, ALICE,
                         "2024-01-01T09:00:00+08:00", "init")
        self.repo.commit({"legacy.py": None, "keep.py": "x\n"}, CHEN,
                         "2026-08-01T09:00:00+08:00", "delete legacy")
        r = self.ledger()
        self.assertEqual((r.promises, r.paid, r.died), ([], 0, 1))

    def test_per_author_economics(self):
        self.repo.commit({"a.py": "# TODO: one\n# TODO: two\n"}, ALICE,
                         "2024-01-01T09:00:00+08:00", "alice promises")
        self.repo.commit({"a.py": "# TODO: two\n"}, BOB,
                         "2024-02-01T09:00:00+08:00", "bob pays one of alice's")
        self.repo.commit({"a.py": "# TODO: two\n# TODO: bob's own\n"}, BOB,
                         "2025-01-01T09:00:00+08:00", "bob promises")
        r = self.ledger()
        per = {a["author"]: a for a in r.per_author}
        self.assertEqual(per["Alice Chen"]["issued"], 2)
        self.assertEqual(per["Alice Chen"]["paid"], 1)
        self.assertEqual(per["Bob Lin"]["outstanding"], 1)
        self.assertAlmostEqual(per["Alice Chen"]["unpaid_rate"], 0.5)

    def test_exclude_prefix_drops_promises_and_history(self):
        self.repo.commit({"app.py": "# TODO: kept\n", "vendor/v.py": "# TODO: vendored\n"},
                         ALICE, "2024-01-01T09:00:00+08:00", "init")
        self.repo.commit({"vendor/v.py": "clean\n"}, BOB,
                         "2024-02-01T09:00:00+08:00", "pay vendored")
        r = self.ledger("vendor")
        self.assertEqual([p["file"] for p in r.promises], ["app.py"])
        self.assertEqual(r.paid, 0)      # excluded payment leaves half-life alone
        self.assertIsNone(r.half_life)

    def test_as_of_stops_replay(self):
        self.repo.commit({"a.py": "# TODO: early\n"}, ALICE,
                         "2024-01-01T09:00:00+08:00", "early")
        self.repo.commit({"a.py": "# TODO: early\n# TODO: late\n"}, BOB,
                         "2026-08-10T09:00:00+08:00", "late")
        r = self.ledger(as_of="2025-01-01")
        self.assertEqual([p["text"] for p in r.promises], ["# TODO: early"])
        self.assertEqual(r.promises[0]["age_days"], 366)  # 2024-01-01 -> 2025-01-01

    def test_working_tree_join_counts(self):
        self.repo.commit({"a.py": "# TODO: committed\n"}, ALICE,
                         "2024-01-01T09:00:00+08:00", "init")
        self.repo.write("b.py", "# TODO: not yet committed\n")       # uncommitted add
        self.repo.write("a.py", "clean\n")                            # uncommitted removal
        r = tr.build_report(self.repo.path, [], None)                 # live join
        self.assertEqual(r.uncommitted, 1)
        self.assertEqual(r.dropped, 1)
        self.assertEqual(len(r.promises), 0)

    def test_duplicate_norm_markers_pair_one_by_one(self):
        self.repo.commit({"a.py": "# TODO: same\ndef x():\n    # TODO: same\n    pass\n"},
                         ALICE, "2024-01-01T09:00:00+08:00", "two identical")
        self.repo.commit({"a.py": "# TODO: same\ndef x():\n    pass\n"}, BOB,
                         "2024-02-01T09:00:00+08:00", "pay one of them")
        r = tr.build_report(self.repo.path, [], None)   # live join for line numbers
        self.assertEqual((len(r.promises), r.paid), (1, 1))
        self.assertEqual(r.promises[0]["line"], 1)   # working-tree line number

    def test_total_rot(self):
        self.repo.commit({"a.py": "# FIXME: x\n# TODO: y\n"}, ALICE,
                         "2025-08-18T09:00:00+08:00", "init")  # 365d at AS_OF
        r = self.ledger()
        self.assertEqual(r.total_rot, 5.0)  # 4*1.0 + 1*1.0


# ---------------------------------------------------------------------------
# Rendering and summary


class RenderTests(unittest.TestCase):
    def test_empty_book(self):
        r = tr.Report(as_of=date(2026, 8, 18), promises=[], half_life=None,
                      paid=0, died=0, moves=0, orphans=0, per_author=[])
        txt = tr.render_ledger(r, top=5)
        self.assertIn("No outstanding promises", txt)
        self.assertIn("half-life", txt)

    def test_summary_and_zombies(self):
        r = tr.Report(as_of=date(2026, 8, 18), half_life=100.0, paid=2, died=0,
                      moves=0, orphans=0, per_author=[], promises=[
                          {"rot": 5.0, "bucket": "ANCIENT", "zombie": True},
                          {"rot": 1.0, "bucket": "FRESH"},
                          {"rot": 1.0, "bucket": "ANCIENT"},
                      ])
        s = r.summary()
        self.assertEqual(s["by_bucket"], {"FRESH": 1, "AGING": 0, "STALE": 0, "ANCIENT": 2})
        self.assertEqual(len(r.zombies), 1)
        self.assertEqual(s["half_life_days"], 100.0)
        txt = tr.render_ledger(r, top=3)
        self.assertIn("ZOMBIE", txt)
        self.assertIn("5.0", txt)

    def test_halflife_render_table(self):
        r = tr.Report(as_of=date(2026, 8, 18), half_life=50.0, paid=3,
                      died=0, moves=0, orphans=0, promises=[],
                      paid_lifetimes=[10, 50, 90],
                      per_author=[{"author": "Alice Chen", "issued": 4, "paid": 2,
                                   "outstanding": 2, "unpaid_rate": 0.5}])
        txt = tr.render_halflife(r)
        self.assertIn("median lifetime  : 50 days", txt)
        self.assertIn("mean / max       : 50 / 90 days", txt)
        self.assertIn("Alice Chen", txt)
        self.assertIn("50%", txt)


# ---------------------------------------------------------------------------
# CLI (subprocess)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="tr-cli-")
        self.repo = GitRepo(self.td, "r")
        self.repo.commit({"a.py": "# FIXME: ancient\n"}, ALICE,
                         "2024-01-10T09:00:00+08:00", "init")
        self.repo.commit({"a.py": "clean\n", "b.py": "# TODO: fresh\n"}, BOB,
                         "2026-08-01T09:00:00+08:00", "pay ancient, promise fresh")
        # lifetime = 2026-08-01 - 2024-01-10 = 934d; threshold 1868d -> no zombie
        # a second repo with a real zombie: TODO paid in 30 days (half-life 30,
        # threshold 60), FIXME unpaid for 960 days by AS_OF
        self.zrepo = GitRepo(self.td, "z")
        self.zrepo.commit({"a.py": "# TODO: quick\n# FIXME: forever\n"}, ALICE,
                          "2024-01-01T09:00:00+08:00", "init")
        self.zrepo.commit({"a.py": "# FIXME: forever\n"}, BOB,
                          "2024-01-31T09:00:00+08:00", "pay quick (30d)")
        self.plain = tempfile.mkdtemp(prefix="tr-plain-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)
        shutil.rmtree(self.plain, ignore_errors=True)

    def test_scan_text_and_json(self):
        code, out, _ = self.repo.run("scan")
        self.assertEqual(code, 0)
        self.assertIn("promise markers", out)
        code, out, _ = self.repo.run("scan", "--format", "json")
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["hits"][0]["marker"], "TODO")

    def test_scan_works_without_git(self):
        with open(os.path.join(self.plain, "x.py"), "w") as fh:
            fh.write("# TODO: gitless\n")
        proc = subprocess.run(list(CLI) + ["scan"], cwd=self.plain,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("gitless", proc.stdout)

    def test_ledger_text_and_json(self):
        code, out, _ = self.repo.run("ledger", "--as-of", AS_OF)
        self.assertEqual(code, 0)
        self.assertIn("Promise book", out)
        self.assertIn("TODO", out)
        code, out, _ = self.repo.run("ledger", "--as-of", AS_OF, "--format", "json")
        payload = json.loads(out)
        self.assertEqual(payload["summary"]["promises"], 1)
        self.assertEqual(payload["promises"][0]["age_days"], 17)

    def test_halflife(self):
        code, out, _ = self.repo.run("halflife", "--as-of", AS_OF)
        self.assertEqual(code, 0)
        self.assertIn("median lifetime  : 934 days", out)
        code, out, _ = self.repo.run("halflife", "--as-of", AS_OF, "--format", "json")
        self.assertEqual(json.loads(out)["summary"]["paid_promises"], 1)

    def test_audit_clean_repo_passes(self):
        code, out, _ = self.repo.run("audit", "--as-of", AS_OF)
        self.assertEqual(code, 0)
        self.assertTrue(out.strip().startswith("audit: PASS"))
        code, out, _ = self.repo.run("audit", "--as-of", AS_OF, "--format", "json")
        self.assertEqual(json.loads(out)["verdict"], "PASS")

    def test_audit_zombie_breach(self):
        code, out, _ = self.zrepo.run("audit", "--as-of", AS_OF)
        self.assertEqual(code, 1)
        self.assertIn("zombies 1 > budget 0", out)
        code, out, _ = self.zrepo.run("audit", "--as-of", AS_OF, "--max-zombies", "1")
        self.assertEqual(code, 0)

    def test_audit_rot_and_ancient_budgets(self):
        code, out, _ = self.zrepo.run("audit", "--as-of", AS_OF,
                                      "--max-zombies", "9", "--max-rot", "1")
        self.assertEqual(code, 1)
        self.assertIn("total rot", out)
        code, out, _ = self.zrepo.run("audit", "--as-of", AS_OF,
                                      "--max-zombies", "9", "--max-ancient", "0")
        self.assertEqual(code, 1)
        self.assertIn("ANCIENT", out)

    def test_ledger_requires_git(self):
        proc = subprocess.run(list(CLI) + ["ledger"], cwd=self.plain,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a git repository", proc.stderr)

    def test_no_subcommand_prints_help(self):
        proc = subprocess.run(list(CLI), cwd=self.repo.path,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)

    def test_global_options_after_subcommand(self):
        code, out, _ = self.repo.run("ledger", "--as-of", AS_OF, "--top", "1")
        self.assertEqual(code, 0)


# ---------------------------------------------------------------------------
# Committed samples never rot


class ExamplesSyncTests(unittest.TestCase):
    def test_samples_and_demo_tree_in_sync(self):
        sys.path.insert(0, str(ROOT / "examples"))
        import build_examples as be
        code = 0
        try:
            be.main(["--check"])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        self.assertEqual(code, 0)

    def test_demo_tree_matches_builder(self):
        sys.path.insert(0, str(ROOT / "examples"))
        import build_examples as be
        import shutil
        tmp = tempfile.mkdtemp(prefix="tr-demo-")
        try:
            repo = be.build_repo(os.path.join(tmp, "r"))
            built = sorted(str(p.relative_to(repo)) for p in Path(repo).rglob("*")
                           if p.is_file() and ".git" not in p.parts)
            committed = sorted(str(p.relative_to(be.DEMO))
                               for p in be.DEMO.rglob("*") if p.is_file())
            self.assertEqual(built, committed)
            for rel in built:
                self.assertEqual((Path(repo) / rel).read_text(),
                                 (be.DEMO / rel).read_text(), rel)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Dogfood: the tool must survive its own repository


class DogfoodTests(unittest.TestCase):
    def test_ledger_on_newidea(self):
        proc = subprocess.run(list(CLI) + ["ledger", "--format", "json"],
                              cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        s = payload["summary"]
        self.assertEqual(s["promises"], sum(s["by_bucket"].values()))
        self.assertGreaterEqual(s["zombies"], 0)
        # join invariant: scan hits == promises + uncommitted
        scan = subprocess.run(list(CLI) + ["scan", "--format", "json"],
                              cwd=REPO_ROOT, capture_output=True, text=True)
        hits = json.loads(scan.stdout)["count"]
        self.assertEqual(hits, s["promises"] + s["uncommitted_promises"])

    def test_halflife_on_newidea(self):
        proc = subprocess.run(list(CLI) + ["halflife"],
                              cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
