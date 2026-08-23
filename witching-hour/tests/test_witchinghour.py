#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance suite for witching-hour.

Every acceptance criterion from the README maps to tests here.  Git-level
tests build throwaway repositories with GIT_AUTHOR_DATE / GIT_COMMITTER_DATE
pinned, so wall-clock hours (including timezone offsets) are exact.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # witching-hour/
REPO_ROOT = os.path.dirname(ROOT)            # the newidea repo (dogfood)

sys.path.insert(0, ROOT)
import witching_hour as wh  # noqa: E402

CLI = os.path.join(ROOT, "witching_hour.py")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, CLI] + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


class RepoCase(unittest.TestCase):
    """Test case with a throwaway git repo and time-pinned commits."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wh-test-")
        self.repo = os.path.join(self.tmp, "r")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        # Repo-local identity so merges/commits work on CI runners without
        # a global git config.
        subprocess.run(["git", "-C", self.repo, "config", "user.name",
                        "Tester"], check=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.email",
                        "tester@x.io"], check=True)
        self.main_branch = subprocess.run(
            ["git", "-C", self.repo, "symbolic-ref", "--short", "HEAD"],
            stdout=subprocess.PIPE, check=True).stdout.decode().strip()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit(self, when, msg, files, author="Dev <dev@x.io>", branch=None):
        if branch:
            subprocess.run(["git", "-C", self.repo, "checkout", "-q", branch],
                           check=True)
        for rel, lines in files.items():
            path = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(path) or self.repo, exist_ok=True)
            if lines is None:                      # deletion sentinel
                os.remove(path)
                continue
            with open(path, "w") as fh:
                fh.write("\n".join(lines) + "\n")
        subprocess.run(["git", "-C", self.repo, "add", "-A"], check=True)
        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
        name, mail = author.split(" <")
        subprocess.run(
            ["git", "-C", self.repo,
             "-c", "user.name=" + name,
             "-c", "user.email=" + mail[:-1],
             "commit", "-q", "-m", msg],
            env=env, check=True)


# ---------------------------------------------------------------------------
# Pure helpers: wall clock, windows, buckets


class HourTests(unittest.TestCase):
    def test_hour_of_author_wall_clock(self):
        self.assertEqual(wh.hour_of("2026-03-10T02:47:00+08:00"), 2)

    def test_hour_of_utc_evening_stays_utc_evening(self):
        # 18:47 UTC is 02:47 next day in +08 — we must NOT convert.
        self.assertEqual(wh.hour_of("2026-03-10T18:47:00+00:00"), 18)

    def test_weekday_of(self):
        self.assertEqual(wh.weekday_of("2026-03-02T10:00:00+08:00"), 0)  # Mon
        self.assertEqual(wh.weekday_of("2026-03-07T23:00:00+08:00"), 5)  # Sat

    def test_bucket_labels(self):
        self.assertEqual(wh.bucket_label(3),
                         ["00-03", "03-06", "06-09", "09-12",
                          "12-15", "15-18", "18-21", "21-24"])

    def test_bucket_hours_must_divide_24(self):
        with self.assertRaises(ValueError):
            wh.bucket_label(5)

    def test_danger_window_wraps_midnight(self):
        self.assertTrue(wh.in_danger_window(2, 22, 6))
        self.assertTrue(wh.in_danger_window(23, 22, 6))
        self.assertFalse(wh.in_danger_window(9, 22, 6))
        self.assertTrue(wh.in_danger_window(10, 9, 17))
        self.assertFalse(wh.in_danger_window(8, 9, 17))

    def test_ratio_share_zero_denominator(self):
        self.assertEqual(wh.ratio_share(3, 0), 0.0)
        self.assertAlmostEqual(wh.ratio_share(1, 4), 0.25)


# ---------------------------------------------------------------------------
# Pure parsers: unified diff and blame porcelain


DIFF = """diff --git a/app.py b/app.py
index 111..222 100644
--- a/app.py
+++ b/app.py
@@ -3,2 +3,2 @@
 context
-old line
+new line
@@ -10 +10 @@
-more
+else
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+alpha
+beta
"""


class DiffParserTests(unittest.TestCase):
    def test_collects_old_line_numbers(self):
        got = wh.parse_hunks(DIFF)
        self.assertEqual(got["app.py"], [3, 4, 10])

    def test_pure_additions_yield_nothing(self):
        self.assertNotIn("new.py", wh.parse_hunks(DIFF))

    def test_count_omitted_means_one_line(self):
        # Without a --- header the hunk belongs to no file: dropped safely.
        self.assertEqual(wh.parse_hunks("@@ -7 +7 @@\n-x\n+y\n"), {})


_SHA1 = "abc" + "1" * 37
_SHA2 = "def" + "2" * 37
BLAME = """%s 3 3 1
author Bob Li
author-mail <b@x>
author-time 1740000000
author-tz +0800
summary night work
\tline three
%s 4 4
author Alice
\tline four
""" % (_SHA1, _SHA2)


class BlameParserTests(unittest.TestCase):
    def test_line_to_sha(self):
        # blame_lines shells out to git; exercise its header regex directly.
        out = {}
        for line in BLAME.split("\n"):
            m = wh.BLAME_HEADER_RE.match(line)
            if m:
                out[int(m.group(3))] = m.group(1)
        self.assertEqual(out[3], "abc" + "1" * 37)
        self.assertEqual(out[4], "def" + "2" * 37)
        # metadata lines and tab-prefixed content must not match
        self.assertNotIn(1, out)
        self.assertEqual(len(out), 2)


# ---------------------------------------------------------------------------
# Statistics: verdicts and risk ratios


class StatsTests(unittest.TestCase):
    def test_verdict_no_work(self):
        self.assertEqual(wh.verdict_of(None, 5, 5, 1.5), "-")

    def test_verdict_low_sample(self):
        self.assertEqual(wh.verdict_of(3.0, 4, 5, 1.5), "low-n")

    def test_verdict_danger_and_ok(self):
        self.assertEqual(wh.verdict_of(1.5, 6, 5, 1.5), "DANGER")
        self.assertEqual(wh.verdict_of(1.49, 6, 5, 1.5), "ok")

    def test_bucket_rows_rr(self):
        defect = Counter({2: 9, 10: 3})     # 75% / 25%
        work = Counter({2: 10, 10: 30})     # 25% / 75%
        rows = wh.bucket_rows(defect, work, 3, 3, 1.5)
        by = {r.window: r for r in rows}
        self.assertAlmostEqual(by["00-03"].rr, 3.0)
        self.assertEqual(by["00-03"].verdict, "DANGER")
        self.assertAlmostEqual(by["09-12"].rr, 1 / 3)
        self.assertEqual(by["09-12"].verdict, "ok")
        # untouched window: no work, no defects -> "-" not a division error
        self.assertIsNone(by["21-24"].rr)


# ---------------------------------------------------------------------------
# Git integration: the whole attribution chain


class GitIntegrationTests(RepoCase):
    def test_attribution_end_to_end(self):
        self.commit("2026-01-05T10:00:00+08:00", "feat: start",
                   {"app.py": ["one", "two"]})
        self.commit("2026-01-06T02:47:00+08:00", "wip: night",
                   {"app.py": ["one", "two", "night bug", "night ok"]})
        self.commit("2026-01-07T11:00:00+08:00", "fix: night bug",
                   {"app.py": ["one", "two", "daylight fix", "night ok"]})
        res = wh.scan_repo(self.repo)
        self.assertEqual(res.defect_lines, 1)
        self.assertEqual(res.defect_by_hour.get(2), 1)   # born at 02:47
        self.assertEqual(res.authors_of_defects.get("Dev"), 1)

    def test_timezone_uses_author_wall_clock(self):
        # The same instant written in two timezones lands in two buckets.
        self.commit("2026-01-05T18:47:00+00:00", "feat: utc evening",
                   {"a.py": ["x", "utc bug"]})
        self.commit("2026-01-05T02:47:00+08:00", "wip: shanghai night",
                   {"b.py": ["y", "cn bug"]})
        self.commit("2026-01-06T10:00:00+08:00", "fix: both",
                   {"a.py": ["x"], "b.py": ["y"]})
        res = wh.scan_repo(self.repo)
        self.assertEqual(res.defect_by_hour.get(18), 1)  # UTC wall clock
        self.assertEqual(res.defect_by_hour.get(2), 1)   # +08 wall clock

    def test_merge_commits_excluded_from_fix_matching(self):
        self.commit("2026-01-05T10:00:00+08:00", "feat: base",
                   {"f.txt": ["base"]})
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "side"],
                       check=True)
        self.commit("2026-01-05T11:00:00+08:00", "feat: side",
                   {"side.txt": ["side"]})
        subprocess.run(["git", "-C", self.repo, "checkout", "-q",
                        self.main_branch], check=True)
        self.commit("2026-01-05T12:00:00+08:00", "feat: main",
                   {"f.txt": ["main"]})
        subprocess.run(["git", "-C", self.repo, "merge", "-q", "--no-ff",
                        "-m", "fix: merge side in", "side"],
                       check=True)
        commits = wh.load_log(self.repo)
        self.assertEqual(len(commits), 3)                # merge invisible
        res = wh.scan_repo(self.repo)
        self.assertEqual(res.fix_commits, 0)

    def test_merge_resolution_lines_count_as_unborn(self):
        # A conflict resolution lives only in a merge commit, which the log
        # (correctly) does not carry: its lines have no birth certificate.
        self.commit("2026-01-05T10:00:00+08:00", "feat: base",
                   {"f.txt": ["base"]})
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "side"],
                       check=True)
        self.commit("2026-01-05T11:00:00+08:00", "feat: side",
                   {"f.txt": ["side"]})
        subprocess.run(["git", "-C", self.repo, "checkout", "-q",
                        self.main_branch], check=True)
        self.commit("2026-01-05T12:00:00+08:00", "feat: main",
                   {"f.txt": ["main"]})
        subprocess.run(["git", "-C", self.repo, "merge", "side"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(os.path.join(self.repo, "f.txt"), "w") as fh:
            fh.write("main\nresolved by hand\nside\n")
        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = "2026-01-05T13:00:00+08:00"
        env["GIT_COMMITTER_DATE"] = "2026-01-05T13:00:00+08:00"
        subprocess.run(["git", "-C", self.repo, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q",
                        "-m", "Merge branch 'side'"], env=env, check=True)
        self.commit("2026-01-06T10:00:00+08:00", "fix: drop resolution",
                   {"f.txt": ["main", "side"]})
        res = wh.scan_repo(self.repo)
        self.assertEqual(res.defect_lines, 0)
        self.assertEqual(res.unborn_lines, 1)

    def test_purely_added_lines_in_a_fix_are_not_attributed(self):
        self.commit("2026-01-05T02:00:00+08:00", "wip: night file",
                   {"n.py": ["a"]})
        self.commit("2026-01-06T10:00:00+08:00", "fix: add guard",
                   {"n.py": ["a", "guard"]})           # addition only
        res = wh.scan_repo(self.repo)
        self.assertEqual(res.defect_lines, 0)

    def test_rename_still_attributes_to_original_birth(self):
        self.commit("2026-01-05T03:30:00+08:00", "wip: early file",
                   {"old.py": ["keep", "renamed bug"]})
        subprocess.run(["git", "-C", self.repo, "mv", "old.py", "new.py"],
                       check=True)
        self.commit("2026-01-05T09:00:00+08:00", "chore: rename", {})
        self.commit("2026-01-06T10:00:00+08:00", "fix: renamed bug",
                   {"new.py": ["keep", "clean"]})
        res = wh.scan_repo(self.repo)
        self.assertEqual(res.defect_by_hour.get(3), 1)

    def test_root_commit_fix_does_not_crash(self):
        # A repo whose very first commit is a "fix" has no parent to diff.
        self.commit("2026-01-05T10:00:00+08:00", "fix: initial",
                   {"a.py": ["x"]})
        res = wh.scan_repo(self.repo)
        self.assertEqual(res.defect_lines, 0)

    def test_max_fix_commits_keeps_newest(self):
        for i in range(5):
            self.commit("2026-01-0%dT10:00:00+08:00" % (i + 1),
                        "fix: #%d" % i, {"a.py": ["v%d" % i]})
        res = wh.scan_repo(self.repo, max_fix=2)
        self.assertEqual(res.fix_commits, 2)
        self.assertEqual(res.fix_skipped, 3)

    def test_author_filter(self):
        self.commit("2026-01-05T02:00:00+08:00", "wip: night",
                   {"a.py": ["x", "bug"]}, author="Bob <bob@x.io>")
        self.commit("2026-01-06T10:00:00+08:00", "fix: bug",
                    {"a.py": ["x"]}, author="Bob <bob@x.io>")
        res = wh.scan_repo(self.repo, author="Bob")
        self.assertEqual(res.defect_by_hour.get(2), 1)
        res_other = wh.scan_repo(self.repo, author="Alice")
        self.assertEqual(res_other.commits_scanned, 0)

    def test_chinese_fix_messages_match(self):
        self.commit("2026-01-05T10:00:00+08:00", "feat: base",
                   {"a.py": ["x", "bug"]})
        self.commit("2026-01-06T10:00:00+08:00", "修复: 登录问题",
                    {"a.py": ["x"]})
        res = wh.scan_repo(self.repo)
        self.assertEqual(res.fix_commits, 1)

    def test_no_fix_commits_reports_insufficient(self):
        self.commit("2026-01-05T10:00:00+08:00", "feat: only",
                   {"a.py": ["x"]})
        res = wh.scan_repo(self.repo)
        self.assertTrue(res.insufficient)
        self.assertEqual(res.defect_lines, 0)

    def test_churn_baseline_counts_added_and_deleted(self):
        self.commit("2026-01-05T10:00:00+08:00", "feat: base",
                   {"a.py": ["one", "two", "three"]})
        self.commit("2026-01-06T10:00:00+08:00", "feat: edit",
                   {"a.py": ["one", "TWO", "three", "four"]})
        commits = wh.load_log(self.repo)
        # second commit: two->TWO (1 del + 1 add) plus new line "four"
        self.assertEqual(sum(c.churn for c in commits), 3 + 3)


# ---------------------------------------------------------------------------
# CLI surface


class CliTests(RepoCase):
    def test_scan_text_and_json(self):
        self.commit("2026-01-05T02:47:00+08:00", "wip: night",
                   {"a.py": ["x", "bug"]})
        self.commit("2026-01-06T10:00:00+08:00", "fix: bug",
                    {"a.py": ["x"]})
        out = run_cli("scan", self.repo)
        self.assertEqual(out.returncode, 0)
        text = out.stdout.decode()
        self.assertIn("Witching Hour scan", text)
        js = run_cli("scan", self.repo, "--format", "json")
        data = json.loads(js.stdout.decode())
        self.assertEqual(data["defect_lines"], 1)
        self.assertEqual(data["buckets"][0]["window"], "00-03")

    def test_rhythm_json(self):
        self.commit("2026-01-05T10:00:00+08:00", "feat: base", {"a.py": ["x"]})
        data = json.loads(
            run_cli("rhythm", self.repo, "--format", "json").stdout.decode())
        self.assertEqual(data["by_hour"]["10"], 1)
        self.assertEqual(data["by_weekday"]["Mon"], 1)

    def test_birth_flags_witching_lines(self):
        self.commit("2026-01-04T10:00:00+08:00", "feat: day",
                   {"a.py": ["day"]})
        self.commit("2026-01-05T02:47:00+08:00", "wip: night",
                   {"a.py": ["day", "night line"]})
        out = run_cli("birth", self.repo, "a.py").stdout.decode()
        self.assertIn("02:47", out)
        self.assertIn("<- witching hour", out)
        only = run_cli("birth", self.repo, "a.py", "--danger-only")
        lines = only.stdout.decode().splitlines()
        shown = [ln for ln in lines if ln.strip().startswith("L")]
        self.assertEqual(len(shown), 1)

    def test_birth_json(self):
        self.commit("2026-01-04T10:00:00+08:00", "feat: day",
                   {"a.py": ["day"]})
        self.commit("2026-01-05T02:47:00+08:00", "wip: night",
                   {"a.py": ["day", "night line"]})
        data = json.loads(
            run_cli("birth", self.repo, "a.py", "--format", "json")
            .stdout.decode())
        self.assertEqual(data["danger_count"], 1)
        self.assertEqual(data["lines"][1]["danger"], True)

    def test_not_a_git_repo_exits_3(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.assertEqual(run_cli("scan", plain).returncode, 3)

    def test_no_subcommand_exits_2(self):
        self.assertEqual(run_cli().returncode, 2)

    def test_flags_after_positional(self):
        self.commit("2026-01-05T10:00:00+08:00", "feat: base", {"a.py": ["x"]})
        self.assertEqual(
            run_cli("scan", self.repo, "--format", "json").returncode, 0)


# ---------------------------------------------------------------------------
# Committed examples stay reproducible


class ExamplesSyncTests(unittest.TestCase):
    def test_demo_tree_and_reports_in_sync(self):
        out = subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "examples", "build_examples.py"), "--check"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(out.returncode, 0, out.stdout.decode())

    def test_sample_report_contains_danger(self):
        with open(os.path.join(ROOT, "examples", "sample-scan.txt")) as fh:
            text = fh.read()
        self.assertIn("DANGER", text)
        self.assertIn("00-03", text)


# ---------------------------------------------------------------------------
# Dogfood: the tool must survive its own birthplace


class DogfoodTests(unittest.TestCase):
    def test_scan_on_newidea_itself(self):
        res = wh.scan_repo(REPO_ROOT)
        # A young repo: whatever it finds, it must not crash, and the
        # numbers must be internally consistent.
        self.assertGreaterEqual(res.commits_scanned, 0)
        self.assertEqual(
            res.defect_lines,
            sum(res.defect_by_hour.values()))

    def test_cli_rhythm_on_newidea(self):
        out = run_cli("rhythm", REPO_ROOT)
        self.assertEqual(out.returncode, 0)
        self.assertIn("Coding clock", out.stdout.decode())


if __name__ == "__main__":
    unittest.main()
