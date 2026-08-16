"""
Automated acceptance tests for gitweek.

Builds real throwaway git repos with deterministic commit dates (via
GIT_AUTHOR_DATE / GIT_COMMITTER_DATE), then drives both the library
functions and the CLI subprocess. Covers the published acceptance
criteria: window math, classification, authorship, stats aggregation,
WIP detection, workspace scan, all three output formats, and error
paths. Stdlib `unittest` + a `git` binary; no network, no fixtures.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gitweek as gw  # noqa: E402

AS_OF = date(2026, 8, 14)          # a Friday
SINCE = date(2026, 8, 8)           # default window: Sat .. Fri, inclusive
OUTSIDE = "2026-08-01T10:00:00"    # well before the window

GIT = shutil.which("git")


def commit(repo: Path, fname, content, subject, when, author=None):
    """Write a file and commit it at a fixed datetime (author+committer)."""
    f = repo / fname
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    env = dict(os.environ,
               GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when,
               GIT_AUTHOR_NAME="Ava Lin", GIT_AUTHOR_EMAIL="ava@example.com",
               GIT_COMMITTER_NAME="Ava Lin", GIT_COMMITTER_EMAIL="ava@example.com")
    if author:
        env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True,
                   capture_output=True)
    args = ["git", "-C", str(repo), "commit", "-q", "-m", subject]
    if author:
        args += ["--author", f"{author[0]} <{author[1]}>"]
    subprocess.run(args, check=True, capture_output=True, env=env)


def make_repo(base: Path, name: str, with_identity=True) -> Path:
    repo = base / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True,
                   capture_output=True)
    if with_identity:
        subprocess.run(["git", "-C", str(repo), "config", "user.name",
                        "Ava Lin"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email",
                        "ava@example.com"], check=True, capture_output=True)
    return repo


@unittest.skipUnless(GIT, "git binary required")
class WindowTests(unittest.TestCase):
    """AC: default window is [as_of-6, as_of] inclusive; explicit dates win."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.repo = make_repo(self.tmp, "win")
        commit(self.repo, "a.py", "x=1\n", "feat: seeded", OUTSIDE)

    def test_default_window_is_seven_inclusive_days(self):
        self.assertEqual(gw.default_window(AS_OF), (SINCE, AS_OF))
        self.assertEqual((AS_OF - SINCE).days + 1, 7)
        out = gw.cmd_report(paths=[str(self.repo)], as_of=AS_OF)
        self.assertIn("Period : 2026-08-08 .. 2026-08-14 (7 days)", out)

    def test_explicit_window_and_validation(self):
        out = gw.cmd_report(paths=[str(self.repo)],
                            since=date(2026, 1, 1), until=date(2026, 1, 2))
        self.assertIn("Period : 2026-01-01 .. 2026-01-02 (2 days)", out)
        with self.assertRaises(gw.GitweekError):
            gw.cmd_report(paths=[str(self.repo)],
                          since=date(2026, 1, 3), until=date(2026, 1, 2))


class ClassifyTests(unittest.TestCase):
    """AC: deterministic 3-layer classification (prefix → keywords → paths)."""

    def test_conventional_prefix(self):
        for subj, cat in [("feat(api): add endpoint", "feat"),
                          ("fix: null pointer", "fix"),
                          ("chore(deps): bump", "chore"),
                          ("TEST: more coverage", "test"),
                          ("refactor!: split module", "refactor")]:
            self.assertEqual(gw.classify(subj, []), cat, subj)

    def test_keyword_fallback_ordering(self):
        # "add tests" must be test, not the generic feat keyword "add"
        self.assertEqual(gw.classify("add tests for parser", []), "test")
        self.assertEqual(gw.classify("update README", []), "docs")
        self.assertEqual(gw.classify("修复登录崩溃", []), "fix")
        self.assertEqual(gw.classify("bump deps to flask 3", []), "chore")
        self.assertEqual(gw.classify("重构了支付模块", []), "refactor")

    def test_no_substring_false_positives(self):
        # regression: "decision" must not contain "ci", "address" not "add"
        self.assertEqual(gw.classify("决策债务 / Decision Debt: methodology", []),
                         "other")
        self.assertEqual(gw.classify("address parser feedback", []), "other")
        self.assertEqual(gw.classify("prefix the log lines", []), "other")
        # word-bounded short tokens still match when used as words
        self.assertEqual(gw.classify("add CI config", []), "ci")
        self.assertEqual(gw.classify("fix CI pipeline", []), "fix")

    def test_path_fallback(self):
        self.assertEqual(gw.classify("wip", ["src/parser_test.py"]), "test")
        self.assertEqual(gw.classify("misc", ["docs/guide.md"]), "docs")
        self.assertEqual(gw.classify("misc", ["yarn.lock"]), "chore")

    def test_other(self):
        self.assertEqual(gw.classify("did stuff", ["src/main.py"]), "other")

    def test_visible_vs_invisible_sets_are_disjoint(self):
        self.assertEqual(set(gw.VISIBLE_CATEGORIES)
                         & set(gw.INVISIBLE_CATEGORIES), set())


@unittest.skipUnless(GIT, "git binary required")
class CollectTests(unittest.TestCase):
    """AC: authorship, window filtering, stats, WIP, idle repos, --scan."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.repo = make_repo(self.tmp, "api")

    def collect(self, **kw):
        return gw.collect_repo(self.repo, kw.pop("since", SINCE),
                               kw.pop("until", AS_OF), **kw)

    # -- authorship --------------------------------------------------------
    def test_default_author_is_repo_identity(self):
        commit(self.repo, "a.py", "x=1\n", "feat: one", "2026-08-10T10:00:00")
        commit(self.repo, "b.py", "y=1\n", "feat: by bob", "2026-08-11T10:00:00",
               author=("Bob Xu", "bob@example.com"))
        commits = self.collect().commits
        self.assertEqual([c.subject for c in commits], ["feat: one"])

    def test_author_override(self):
        commit(self.repo, "b.py", "y=1\n", "feat: by bob", "2026-08-11T10:00:00",
               author=("Bob Xu", "bob@example.com"))
        commits = self.collect(author="Bob").commits
        self.assertEqual([c.subject for c in commits], ["feat: by bob"])

    def test_missing_identity_requires_author(self):
        repo = make_repo(self.tmp, "anon", with_identity=False)
        commit(repo, "a.py", "x=1\n", "feat: one", "2026-08-10T10:00:00")
        # Hide the machine's global/system identity so "no identity anywhere"
        # is reproducible on any developer box.
        with unittest.mock.patch.dict(os.environ,
                                      GIT_CONFIG_GLOBAL="/dev/null",
                                      GIT_CONFIG_SYSTEM="/dev/null"):
            with self.assertRaises(gw.GitweekError):
                gw.collect_repo(repo, SINCE, AS_OF)
            # an explicit --author still works without any configured identity
            res = gw.collect_repo(repo, SINCE, AS_OF, author="Ava")
            self.assertEqual(len(res.commits), 1)

    # -- window filtering ----------------------------------------------------
    def test_window_is_inclusive_and_filters_outside(self):
        commit(self.repo, "old.py", "o=1\n", "feat: too old", OUTSIDE)
        commit(self.repo, "in1.py", "i=1\n", "feat: edge start",
               "2026-08-08T00:30:00")
        commit(self.repo, "in2.py", "i=2\n", "feat: edge end",
               "2026-08-14T23:30:00")
        commit(self.repo, "new.py", "n=1\n", "feat: too new",
               "2026-08-15T09:00:00")
        commits = self.collect().commits
        self.assertEqual([c.subject for c in commits],
                         ["feat: edge start", "feat: edge end"])

    # -- stats ---------------------------------------------------------------
    def test_stats_aggregate_from_numstat(self):
        commit(self.repo, "src/a.py", "l\n" * 10, "feat: add a",
               "2026-08-10T10:00:00")           # a.py  +10/-0
        commit(self.repo, "src/a.py", "l\n" * 12, "feat: extend a",
               "2026-08-11T10:00:00")           # a.py   +2/-0
        commit(self.repo, "src/b.py", "l\n" * 4, "feat: add b",
               "2026-08-12T10:00:00")           # b.py   +4/-0
        s = gw.summarize([self.collect()])
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["files_touched"], 2)
        self.assertEqual(s["insertions"], 16)
        self.assertEqual(s["deletions"], 0)
        self.assertEqual(s["active_days"], 3)

    def test_invisible_ratio(self):
        subjects = ["feat: a", "fix: b", "test: c", "docs: d", "chore: e",
                    "refactor: f"]
        days = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13",
                "2026-08-14", "2026-08-14"]
        for i, (subj, day) in enumerate(zip(subjects, days)):
            commit(self.repo, f"f{i}.py", "x\n", subj, f"{day}T10:00:00")
        s = gw.summarize([self.collect()])
        self.assertEqual(s["total"], 6)
        self.assertEqual(s["invisible"], 4)
        self.assertEqual(s["cat_counts"]["other"], 0)
        self.assertAlmostEqual(s["invisible_ratio"], 4 / 6)

    # -- WIP -------------------------------------------------------------------
    def test_wip_detected(self):
        commit(self.repo, "a.py", "x=1\n", "feat: one", "2026-08-10T10:00:00")
        (self.repo / "a.py").write_text("x=1\ny=2\nz=3\n")     # +2/-0 unstaged
        (self.repo / "scratch.py").write_text("wip\n")          # untracked
        wip = self.collect().wip
        self.assertEqual(wip["files"], 1)
        self.assertEqual(wip["insertions"], 2)
        self.assertEqual(wip["untracked"], 1)

    def test_clean_repo_has_no_wip(self):
        commit(self.repo, "a.py", "x=1\n", "feat: one", "2026-08-10T10:00:00")
        self.assertIsNone(self.collect().wip)

    def test_no_status_skips_wip(self):
        commit(self.repo, "a.py", "x=1\n", "feat: one", "2026-08-10T10:00:00")
        (self.repo / "a.py").write_text("x=1\ny=2\n")
        self.assertIsNone(self.collect(no_status=True).wip)

    # -- idle / empty / scan ----------------------------------------------------
    def test_idle_and_empty_repos(self):
        commit(self.repo, "old.py", "o=1\n", "feat: too old", OUTSIDE)
        idle = self.collect()
        self.assertEqual(idle.note, "idle")
        self.assertEqual(idle.commits, [])
        empty = make_repo(self.tmp, "empty")
        result = gw.collect_repo(empty, SINCE, AS_OF)
        self.assertEqual(result.note, "no commits yet")

    def test_scan_finds_nested_repos_and_plain_dir_rejected(self):
        ws = self.tmp / "ws"
        ws.mkdir()
        make_repo(ws, "api")
        make_repo(ws, "web")
        (ws / "notes").mkdir()
        repos = gw.find_repos([ws], scan=True)
        self.assertEqual(sorted(r.name for r in repos), ["api", "web"])
        with self.assertRaises(gw.GitweekError):
            gw.find_repos([ws / "notes"])

    def test_report_survives_partial_failure(self):
        ws = self.tmp / "ws"
        ws.mkdir()
        good = make_repo(ws, "good")
        commit(good, "a.py", "x\n", "feat: ok", "2026-08-10T10:00:00")
        bad = make_repo(ws, "bad")
        commit(bad, "b.py", "y\n", "feat: anon", "2026-08-10T11:00:00")
        for key in ("user.name", "user.email"):
            subprocess.run(["git", "-C", str(bad), "config", "--unset", key],
                           capture_output=True)
        out = gw.cmd_report(paths=[str(ws)], scan=True, as_of=AS_OF)
        self.assertIn("feat: ok", out)
        self.assertIn("[skipped]", out)


@unittest.skipUnless(GIT, "git binary required")
class FormatTests(unittest.TestCase):
    """AC: text / md / json outputs carry the required sections and numbers."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        repo = make_repo(self.tmp, "api")
        commit(repo, "src/handler.py", "l\n" * 20, "feat: pricing endpoint",
               "2026-08-10T10:00:00")
        commit(repo, "tests/handler_test.py", "l\n" * 12, "test: cover parser",
               "2026-08-11T10:00:00")
        commit(repo, "docs/guide.md", "l\n" * 6, "docs: setup guide",
               "2026-08-12T10:00:00")
        commit(repo, "src/handler.py", "l\n" * 22, "fix: null in pricing",
               "2026-08-13T10:00:00")
        self.repo = repo
        self.out = gw.cmd_report(paths=[str(repo)], as_of=AS_OF)
        self.md = gw.cmd_report(paths=[str(repo)], as_of=AS_OF, fmt="md")
        self.js = gw.cmd_report(paths=[str(repo)], as_of=AS_OF, fmt="json")

    def test_text_report_sections(self):
        for section in ["Overview", "Work shape", "Invisible work",
                        "Daily activity", "Hottest files", "All commits",
                        "invisible share"]:
            self.assertIn(section, self.out, section)
        self.assertIn("← invisible", self.out)   # invisible rows are marked

    def test_md_is_paste_ready_draft(self):
        for piece in ["# 周报草稿", "## 本周概览", "## 主要成果",
                      "## 不可见工作", "## 下周计划", "test: cover parser"]:
            self.assertIn(piece, self.md, piece)

    def test_json_is_valid_and_complete(self):
        data = json.loads(self.js)
        self.assertEqual(data["period"]["since"], "2026-08-08")
        self.assertEqual(data["period"]["until"], "2026-08-14")
        self.assertEqual(data["summary"]["commits"], 4)
        self.assertEqual(data["summary"]["category_counts"]["test"], 1)
        self.assertEqual(len(data["repos"][0]["commits"]), 4)
        self.assertEqual(data["hot_files"][0]["path"], "src/handler.py")

    def test_empty_week_is_graceful(self):
        repo = make_repo(self.tmp, "fresh")
        commit(repo, "old.py", "o=1\n", "feat: ancient", OUTSIDE)
        out = gw.cmd_report(paths=[str(repo)], as_of=AS_OF)
        self.assertIn("No commits in this window", out)


@unittest.skipUnless(GIT, "git binary required")
class CliSmokeTests(unittest.TestCase):
    """AC: the CLI entrypoint runs end-to-end with --scan and every format."""

    def test_full_workflow_via_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            repo = make_repo(ws, "api")
            commit(repo, "src/a.py", "l\n" * 5, "feat: alpha",
                   "2026-08-10T10:00:00")
            commit(repo, "src/a_test.py", "l\n" * 3, "test: alpha",
                   "2026-08-11T10:00:00")
            repo2 = make_repo(ws, "web")
            commit(repo2, "app.js", "l\n" * 2, "chore: bump deps",
                   "2026-08-12T10:00:00")

            py = [sys.executable, str(ROOT / "gitweek.py")]

            def run(*args):
                return subprocess.run(
                    py + ["report", "--scan", "-p", str(ws), "--as-of",
                          "2026-08-14"] + list(args),
                    capture_output=True, text=True)

            r = run()
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Period : 2026-08-08 .. 2026-08-14", r.stdout)
            self.assertIn("feat: alpha", r.stdout)
            self.assertIn("test: alpha", r.stdout)    # cross-repo invisible work
            self.assertIn("chore: bump deps", r.stdout)

            r = run("--format", "md")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("## 不可见工作", r.stdout)

            r = run("--format", "json")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(json.loads(r.stdout)["repos"]), 2)

            r = run("--author", "nobody-here")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("No commits in this window", r.stdout)

    def test_error_exit_code_on_bad_path(self):
        r = subprocess.run([sys.executable, str(ROOT / "gitweek.py"), "report",
                            "-p", "/definitely/not/a/repo"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("error", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
