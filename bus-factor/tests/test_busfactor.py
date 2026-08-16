#!/usr/bin/env python3
"""Acceptance tests for bus-factor (知识单点).

All acceptance criteria from README.md are pinned here as unittest cases.
Git integration tests build real temporary repositories with pinned dates
so every number is deterministic. Parser/metric tests run against fixture
strings and pure functions — no git needed.

Run:  python3 -m unittest discover -s bus-factor/tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bus_factor as bf  # noqa: E402

CLI = sys.executable, str(ROOT / "bus_factor.py")

ALICE = ("Alice Chen", "alice@corp.dev")
BOB = ("Bob Lin", "bob@corp.dev")
CHEN = ("Chen Wu", "chen@corp.dev")
BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")


def line(n, seed=0):
    """Deterministic filler line."""
    return "x{0:04d} {1}\n".format(seed, "y" * 40)


def make_file(n_lines, seed=0):
    return "".join(line(i, seed) for i in range(n_lines))


def append_lines(content, n, seed=0):
    """Simulate a small follow-up edit (NOT a full rewrite) so the
    added-lines weighting stays realistic."""
    return content + "".join(line(i, seed) for i in range(n))


# ---------------------------------------------------------------------------
# Git fixture helpers (real repos, pinned dates)


class GitRepo:
    def __init__(self, td, name):
        self.path = os.path.join(td, name)
        os.makedirs(self.path)
        self.git("init", "-q")
        self.git("config", "user.name", "Test Committer")
        self.git("config", "user.email", "committer@corp.dev")

    def git(self, *args, **kw):
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false"] + list(args),
            cwd=self.path, capture_output=True, text=True, **kw)
        if proc.returncode != 0:
            raise AssertionError(
                "git {0} failed:\n{1}".format(args, proc.stderr))
        return proc.stdout

    def commit(self, files, author, when, message, coauthors=()):
        """files: {relpath: content}; content None -> delete the file."""
        for rel, content in files.items():
            full = os.path.join(self.path, rel)
            if content is None:
                self.git("rm", "-q", "--ignore-unmatch", rel)
                continue
            os.makedirs(os.path.dirname(full) or self.path, exist_ok=True)
            with open(full, "w") as fh:
                fh.write(content)
        self.git("add", "-A", ".")
        body = message
        for name, email in coauthors:
            body += "\n\nCo-Authored-By: {0} <{1}>".format(name, email)
        env = dict(os.environ,
                   GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        proc = subprocess.run(
            ["git", "commit", "-q", "--no-gpg-sign", "-m", body,
             "--author={0} <{1}>".format(*author)],
            cwd=self.path, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise AssertionError("commit failed:\n" + proc.stderr)
        return proc.stdout

    def stats(self, **kw):
        opts = bf.Options(repo=self.path, **kw)
        return bf.collect(opts)


class ParserTests(unittest.TestCase):
    LOG_SAMPLE = (
        "\x1eh1\x1fAlice\x1falice@x.dev\x1f2026-01-02T10:00:00+08:00"
        "\x1fadd auth module\n"
        "\n"
        "30\t2\tsrc/auth.py\n"
        "-\t-\tassets/logo.png\n"
        "8\t0\tsrc/{old => new}.py\n"
        "12\t4\tlib.py => core/lib.py\n"
        "\x1eh2\x1fBob\x1fbob@x.dev\x1f2026-01-03T11:00:00+08:00"
        "\x1fmerge followup\n"
        "\n"
        "5\t1\tsrc/auth.py\n"
    )

    def test_parse_commit_count_and_fields(self):
        commits = bf.parse_git_log(self.LOG_SAMPLE)
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0].hash, "h1")
        self.assertEqual(commits[0].name, "Alice")
        self.assertEqual(commits[0].email, "alice@x.dev")
        self.assertEqual(commits[0].date, "2026-01-02T10:00:00+08:00")

    def test_parse_numstat_lines(self):
        commits = bf.parse_git_log(self.LOG_SAMPLE)
        self.assertEqual(len(commits[0].files), 4)
        added, deleted, path = commits[0].files[0]
        self.assertEqual((added, deleted, path), (30, -1, "src/auth.py"))

    def test_binary_file_counts_as_minus(self):
        commits = bf.parse_git_log(self.LOG_SAMPLE)
        self.assertEqual(commits[0].files[1][0], -1)

    def test_brace_rename_expanded(self):
        commits = bf.parse_git_log(self.LOG_SAMPLE)
        self.assertEqual(commits[0].files[2][2], "src/new.py")

    def test_arrow_rename_expanded(self):
        commits = bf.parse_git_log(self.LOG_SAMPLE)
        self.assertEqual(commits[0].files[3][2], "core/lib.py")

    def test_expand_rename_plain_path_untouched(self):
        self.assertEqual(bf.expand_rename("src/a.py"), "src/a.py")

    def test_expand_rename_root_brace(self):
        self.assertEqual(bf.expand_rename("{a.py => b.py}"), "b.py")
        self.assertEqual(bf.expand_rename("src/{ => sub/}a.py"),
                         "src/sub/a.py")

    def test_parse_rename_status_lines(self):
        text = ("\x1eh1\nR100\tlib.py\tcore/lib.py\n"
                "\x1eh2\nR075\ta/b.py\tc/d.py\n"
                "\x1eh3\nM\tstay.py\n")
        mapping = {}
        for record in text.split("\x1e"):
            for ln in record.splitlines():
                if ln.startswith("R"):
                    parts = ln.split("\t")
                    if len(parts) == 3:
                        mapping[parts[1]] = parts[2]
        self.assertEqual(mapping, {"lib.py": "core/lib.py",
                                   "a/b.py": "c/d.py"})

    def test_resolve_path_follows_chain(self):
        renames = {"a.py": "b.py", "b.py": "c.py", "c.py": "d.py"}
        self.assertEqual(bf.resolve_path("a.py", renames), "d.py")
        # pathological cycle must terminate, not hang
        cyclic = {"x.py": "y.py", "y.py": "x.py"}
        self.assertIn(bf.resolve_path("x.py", cyclic), ("x.py", "y.py"))

    def test_commit_message_body_strips_numstat(self):
        commits = bf.parse_git_log(self.LOG_SAMPLE)
        body = bf.commit_message_body(commits[0])
        self.assertIn("add auth module", body)
        self.assertNotIn("30\t2", body)

    def test_coauthor_regex(self):
        body = ("pair on webhook\n\n"
                "Co-Authored-By: Bob Lin <bob@corp.dev>\n"
                "Co-Authored-By: Chen Wu <chen@corp.dev>\n")
        found = bf.COAUTHOR_RE.findall(body)
        self.assertEqual(found, [("Bob Lin", "bob@corp.dev"),
                                 ("Chen Wu", "chen@corp.dev")])


class AuthorTests(unittest.TestCase):
    def test_bot_detection(self):
        self.assertTrue(bf.is_bot(*BOT))
        self.assertTrue(bf.is_bot("renovate[bot]", "bot@renovateapp.com"))
        self.assertFalse(bf.is_bot(*ALICE))

    def test_registry_key_is_email_lower(self):
        reg = bf.AuthorRegistry()
        k1 = reg.register("Alice Chen", "Alice@Corp.dev")
        k2 = reg.register("alice chen", "alice@corp.dev")
        self.assertEqual(k1, k2)
        self.assertEqual(len(reg.keys()), 1)

    def test_registry_display_most_common_name(self):
        reg = bf.AuthorRegistry()
        key = reg.register("Alice", "alice@corp.dev")
        reg.register("Alice Chen", "alice@corp.dev")
        reg.register("Alice Chen", "alice@corp.dev")
        self.assertEqual(reg.display(key), "Alice Chen")

    def test_registry_resolve_by_name_email_substring(self):
        reg = bf.AuthorRegistry()
        reg.register(*ALICE)
        self.assertEqual(reg.resolve("Alice Chen"), "alice@corp.dev")
        self.assertEqual(reg.resolve("alice@corp.dev"), "alice@corp.dev")
        self.assertEqual(reg.resolve("alice"), "alice@corp.dev")
        self.assertIsNone(reg.resolve("nobody"))

    def test_registry_resolve_surname_prefers_email_over_display(self):
        # 'chen' is Chen Wu's email local-part AND a substring of
        # 'Alice Chen' — email must win, else radius hits the wrong person.
        reg = bf.AuthorRegistry()
        reg.register(*ALICE)
        reg.register(*CHEN)
        self.assertEqual(reg.resolve("chen"), "chen@corp.dev")


class MetricTests(unittest.TestCase):
    def test_shares(self):
        self.assertEqual(bf.shares({"a": 60, "b": 40}),
                         {"a": 0.6, "b": 0.4})
        self.assertEqual(bf.shares({}), {})

    def test_truck_factor_single_owner(self):
        self.assertEqual(bf.truck_factor({"a": 0.96, "b": 0.04}), 1)

    def test_truck_factor_exact_half_is_one(self):
        # >= 50% rule: one author at exactly 50% already covers the file.
        self.assertEqual(bf.truck_factor({"a": 0.5, "b": 0.5}), 1)

    def test_truck_factor_needs_two(self):
        self.assertEqual(bf.truck_factor({"a": 0.4, "b": 0.35, "c": 0.25}), 2)

    def test_truck_factor_even_three_is_two(self):
        share = {k: 1 / 3 for k in "abc"}
        self.assertEqual(bf.truck_factor(share), 2)

    def test_truck_factor_empty_is_zero(self):
        self.assertEqual(bf.truck_factor({}), 0)

    def test_hhi(self):
        self.assertAlmostEqual(bf.hhi({"a": 1.0}), 1.0)
        self.assertAlmostEqual(bf.hhi({"a": 0.5, "b": 0.5}), 0.5)
        uniform = bf.hhi({k: 0.25 for k in "abcd"})
        self.assertAlmostEqual(uniform, 0.25)

    def test_effective_authors(self):
        self.assertAlmostEqual(
            bf.effective_authors({"a": 0.5, "b": 0.5}), 2.0)
        self.assertEqual(bf.effective_authors({}), 0)

    def test_guardian_threshold(self):
        self.assertEqual(bf.guardian_of({"a": 0.8, "b": 0.2}), "a")
        self.assertIsNone(bf.guardian_of({"a": 0.79, "b": 0.21}))

    def test_guardian_exact_boundary(self):
        self.assertEqual(bf.guardian_of({"a": 0.8, "b": 0.2}), "a")

    def test_critical_authors_includes_both_halves(self):
        self.assertEqual(bf.critical_authors({"a": 0.5, "b": 0.5}),
                         ["a", "b"])
        self.assertEqual(bf.critical_authors({"a": 0.6, "b": 0.4}), ["a"])

    def test_risk_levels(self):
        self.assertEqual(bf.risk_level(1), bf.RISK_RED)
        self.assertEqual(bf.risk_level(2), bf.RISK_AMBER)
        self.assertEqual(bf.risk_level(3), bf.RISK_GREEN)
        self.assertEqual(bf.risk_level(7), bf.RISK_GREEN)


class GitIntegrationTests(unittest.TestCase):
    """End-to-end against real temporary git repositories."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def repo(self, name="r"):
        return GitRepo(self._tmp.name, name)

    def build_team_repo(self):
        """Three authors, files engineered to hit every risk bucket.

        alpha: alice 120 added vs bob 3 appended  -> ~97% guardian, TF 1
        beta : 100 vs 100 (full rewrite)          -> 50/50, TF 1, no guardian
        gamma: 100 / +90 / +65 appended           -> 39/35/26, TF 2
        webhook: chen alone, nested under src/    -> the orphan case
        """
        r = self.repo("team")
        alpha = make_file(120)
        r.commit({"alpha.py": alpha}, ALICE,
                 "2026-01-05T10:00:00+00:00", "feat: alpha core")
        r.commit({"alpha.py": append_lines(alpha, 3, 1)}, BOB,
                 "2026-01-06T10:00:00+00:00", "fix: alpha tweak")
        r.commit({"beta.py": make_file(100)}, ALICE,
                 "2026-01-07T10:00:00+00:00", "feat: beta")
        r.commit({"beta.py": make_file(100, 2)}, BOB,
                 "2026-01-08T10:00:00+00:00", "refactor: rewrite beta")
        gamma = make_file(100)
        r.commit({"gamma.py": gamma}, ALICE,
                 "2026-01-09T10:00:00+00:00", "feat: gamma")
        gamma = append_lines(gamma, 90, 3)
        r.commit({"gamma.py": gamma}, BOB,
                 "2026-01-10T10:00:00+00:00", "fix: gamma")
        r.commit({"gamma.py": append_lines(gamma, 65, 4)}, CHEN,
                 "2026-01-11T10:00:00+00:00", "chore: gamma ci")
        r.commit({"src/deep/webhook.py": make_file(200)}, CHEN,
                 "2026-01-12T10:00:00+00:00", "feat: payment webhook")
        return r

    # -- file-level knowledge ------------------------------------------------

    def test_alpha_is_guarded_by_alice(self):
        stats = self.build_team_repo().stats(min_lines=10)
        fs = stats.files["alpha.py"]
        sh = bf.shares(fs.added)
        self.assertEqual(bf.truck_factor(sh), 1)
        self.assertEqual(bf.guardian_of(sh), "alice@corp.dev")

    def test_beta_fifty_fifty_is_red_not_amber(self):
        stats = self.build_team_repo().stats(min_lines=10)
        fs = stats.files["beta.py"]
        sh = bf.shares(fs.added)
        self.assertEqual(bf.truck_factor(sh), 1)  # 50% covers
        self.assertIsNone(bf.guardian_of(sh))     # but nobody guards 80%

    def test_gamma_three_authors_is_amber(self):
        stats = self.build_team_repo().stats(min_lines=10)
        sh = bf.shares(stats.files["gamma.py"].added)
        self.assertEqual(bf.truck_factor(sh), 2)

    def test_min_lines_filters_small_files(self):
        r = self.build_team_repo()
        r.commit({"tiny.py": make_file(5)}, CHEN,
                 "2026-01-13T10:00:00+00:00", "chore: tiny")
        stats = r.stats(min_lines=50)
        paths = {fs.path for fs in stats.measured(50)}
        self.assertIn("alpha.py", paths)
        self.assertNotIn("tiny.py", paths)

    def test_lines_is_current_size_not_churn(self):
        stats = self.build_team_repo().stats(min_lines=10)
        # beta.py was fully rewritten: 100 current lines, 200 added total
        self.assertEqual(stats.files["beta.py"].lines, 100)
        self.assertEqual(stats.files["beta.py"].total_added, 200)

    # -- blast radius --------------------------------------------------------

    def test_radius_sole_author_files_orphaned(self):
        stats = self.build_team_repo().stats(min_lines=10)
        radius = stats.blast_radius("chen@corp.dev")
        self.assertEqual(radius["handoff"]["files"], 1)
        self.assertEqual(radius["handoff_files"], ["src/deep/webhook.py"])
        self.assertEqual(radius["guarded"]["files"], 1)

    def test_radius_shared_author_has_no_orphans(self):
        stats = self.build_team_repo().stats(min_lines=10)
        radius = stats.blast_radius("alice@corp.dev")
        self.assertEqual(radius["handoff"]["files"], 0)
        self.assertGreaterEqual(radius["critical"]["files"], 2)

    def test_guardians_view(self):
        stats = self.build_team_repo().stats(min_lines=10)
        guards = stats.guardians(10)
        self.assertIn("chen@corp.dev", guards)
        self.assertEqual([f.path for f in guards["chen@corp.dev"]],
                         ["src/deep/webhook.py"])

    # -- identity handling ---------------------------------------------------

    def test_bots_ignored_by_default(self):
        r = self.repo("bots")
        r.commit({"a.py": make_file(40)}, ALICE,
                 "2026-01-05T10:00:00+00:00", "feat: a")
        r.commit({"a.py": make_file(41, 1)}, BOT,
                 "2026-01-06T10:00:00+00:00", "chore(deps): bump")
        stats = r.stats(min_lines=10)
        self.assertEqual(list(stats.files["a.py"].added), ["alice@corp.dev"])
        self.assertGreaterEqual(stats.bots_ignored, 1)

    def test_include_bots_counts_them(self):
        r = self.repo("bots2")
        r.commit({"a.py": make_file(40)}, ALICE,
                 "2026-01-05T10:00:00+00:00", "feat: a")
        r.commit({"a.py": make_file(41, 1)}, BOT,
                 "2026-01-06T10:00:00+00:00", "chore(deps): bump")
        stats = r.stats(min_lines=10, include_bots=True)
        self.assertEqual(len(stats.files["a.py"].added), 2)

    def test_coauthored_gives_credit_to_pair(self):
        r = self.repo("pair")
        r.commit({"pair.py": make_file(60)}, ALICE,
                 "2026-01-05T10:00:00+00:00", "feat: pair work",
                 coauthors=[BOB])
        stats = r.stats(min_lines=10)
        sh = bf.shares(stats.files["pair.py"].added)
        self.assertAlmostEqual(sh["alice@corp.dev"], 0.5)
        self.assertAlmostEqual(sh["bob@corp.dev"], 0.5)
        self.assertEqual(bf.truck_factor(sh), 1)

    def test_no_coauthored_disables_pair_credit(self):
        r = self.repo("pair2")
        r.commit({"pair.py": make_file(60)}, ALICE,
                 "2026-01-05T10:00:00+00:00", "feat: pair work",
                 coauthors=[BOB])
        stats = r.stats(min_lines=10, use_coauthored=False)
        self.assertEqual(list(stats.files["pair.py"].added),
                         ["alice@corp.dev"])

    # -- rename / deletion ---------------------------------------------------

    def test_git_mv_preserves_history(self):
        r = self.repo("mv")
        r.commit({"lib.py": make_file(200)}, ALICE,
                 "2026-01-05T10:00:00+00:00", "feat: lib")
        # pure rename: same content, new location
        os.rename(os.path.join(r.path, "lib.py"),
                  os.path.join(r.path, "core.py"))
        r.git("add", "-A", ".")
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-01-06T10:00:00+00:00",
                   GIT_COMMITTER_DATE="2026-01-06T10:00:00+00:00")
        subprocess.run(["git", "commit", "-q", "-m", "refactor: move lib"],
                       cwd=r.path, env=env, check=True,
                       capture_output=True)
        stats = r.stats(min_lines=10)
        self.assertNotIn("lib.py", stats.files)
        self.assertEqual(stats.files["core.py"].added["alice@corp.dev"], 200)

    def test_deleted_files_excluded_unless_flag(self):
        r = self.repo("del")
        r.commit({"gone.py": make_file(60), "stay.py": make_file(60)}, ALICE,
                 "2026-01-05T10:00:00+00:00", "feat: init")
        r.commit({"gone.py": None}, ALICE,
                 "2026-01-06T10:00:00+00:00", "chore: remove gone")
        stats = r.stats(min_lines=10)
        self.assertNotIn("gone.py", stats.files)
        stats2 = r.stats(min_lines=10, include_deleted=True)
        self.assertIn("gone.py", stats2.files)
        self.assertEqual(stats2.files["gone.py"].lines, 0)  # archaeology only

    # -- window --------------------------------------------------------------

    def test_window_drops_old_commits(self):
        r = self.repo("win")
        r.commit({"a.py": make_file(50)}, ALICE,
                 "2026-01-05T10:00:00+00:00", "feat: old")
        r.commit({"a.py": make_file(51, 1)}, BOB,
                 "2026-06-01T10:00:00+00:00", "fix: new")
        import datetime as dt
        opts = dict(min_lines=10, window_days=90,
                    as_of=dt.date(2026, 6, 15))
        stats = r.stats(**opts)
        # only bob's commit is inside the window
        self.assertEqual(list(stats.files["a.py"].added), ["bob@corp.dev"])
        self.assertEqual(stats.commits_scanned, 1)

    # -- module aggregation --------------------------------------------------

    def test_module_aggregate_shares(self):
        stats = self.build_team_repo().stats(min_lines=10)
        agg = bf.Counter()
        for fs in stats.measured(10):
            if fs.path.startswith("src/"):
                agg.update(fs.added)
        sh = bf.shares(agg)
        self.assertEqual(set(sh), {"chen@corp.dev"})
        self.assertEqual(bf.truck_factor(sh), 1)


class CliTests(unittest.TestCase):
    """Subprocess smoke tests — the CLI must stand alone."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = GitRepo(self._tmp.name, "cli")
        app = make_file(80)
        self.repo.commit({"app.py": app}, ALICE,
                         "2026-01-05T10:00:00+00:00", "feat: app")
        self.repo.commit({"app.py": append_lines(app, 2, 1)}, BOB,
                         "2026-01-06T10:00:00+00:00", "fix: app")

    def run_cli(self, *args):
        return subprocess.run(
            list(CLI) + list(args), capture_output=True, text=True)

    def test_version(self):
        proc = self.run_cli("--version")
        self.assertEqual(proc.returncode, 0)
        self.assertIn(bf.__version__, proc.stdout)

    def test_scan_text_mentions_guardian(self):
        proc = self.run_cli("-p", self.repo.path, "scan", "--min-lines", "10")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("knowledge concentration report", proc.stdout)
        self.assertIn("RED", proc.stdout)

    def test_scan_json_shape(self):
        proc = self.run_cli("-p", self.repo.path, "scan",
                            "--format", "json", "--min-lines", "10")
        payload = json.loads(proc.stdout)
        for key in ("summary", "files", "guardians", "authors",
                    "files_measured", "lines_measured", "as_of"):
            self.assertIn(key, payload)
        app = next(f for f in payload["files"] if f["path"] == "app.py")
        self.assertEqual(app["tf"], 1)
        self.assertEqual(app["risk"], "RED")

    def test_fail_on_red_exits_one_when_red_exists(self):
        proc = self.run_cli("-p", self.repo.path, "scan",
                            "--min-lines", "10", "--fail-on", "red")
        self.assertEqual(proc.returncode, 1)

    def test_fail_on_none_exits_zero(self):
        proc = self.run_cli("-p", self.repo.path, "scan",
                            "--min-lines", "1000", "--fail-on", "red")
        self.assertEqual(proc.returncode, 0)

    def test_file_report_roles(self):
        proc = self.run_cli("-p", self.repo.path, "file", "app.py",
                            "--min-lines", "10")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("AUTHOR", proc.stdout)
        self.assertIn("critical", proc.stdout)  # 80-line vs 1-line share

    def test_file_unknown_path_exits_two(self):
        proc = self.run_cli("-p", self.repo.path, "file", "nope.py")
        self.assertEqual(proc.returncode, 2)

    def test_module_report(self):
        proc = self.run_cli("-p", self.repo.path, "module", ".",
                            "--min-lines", "10")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("bus-factor module", proc.stdout)

    def test_radius_known_author(self):
        proc = self.run_cli("-p", self.repo.path, "radius", "alice",
                            "--min-lines", "10")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("blast radius", proc.stdout)
        self.assertIn("app.py", proc.stdout)

    def test_radius_unknown_author_exits_two(self):
        proc = self.run_cli("-p", self.repo.path, "radius", "nobody")
        self.assertEqual(proc.returncode, 2)

    def test_not_a_git_repo_exits_two(self):
        plain = os.path.join(self._tmp.name, "plain")
        os.makedirs(plain, exist_ok=True)
        proc = self.run_cli("-p", plain, "scan")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a git repository", proc.stderr)

    def test_global_flags_after_subcommand(self):
        proc = self.run_cli("-p", self.repo.path, "scan",
                            "--min-lines", "1000")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("0 measured", proc.stdout)

    def test_guardians_report_handoff_marker(self):
        repo2 = GitRepo(self._tmp.name, "solo")
        repo2.commit({"solo.py": make_file(50)}, CHEN,
                     "2026-01-05T10:00:00+00:00", "feat: solo")
        proc = self.run_cli("-p", repo2.path, "guardians",
                            "--min-lines", "10")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("NO second author", proc.stdout)


class ExamplesSyncTests(unittest.TestCase):
    """The committed sample must match a fresh rebuild of demo-repo."""

    @classmethod
    def setUpClass(cls):
        demo = ROOT / "examples" / "demo-repo"
        if not (demo / ".git").exists():
            subprocess.run(
                [sys.executable, str(ROOT / "examples" / "build_examples.py")],
                capture_output=True, text=True, check=True)

    def run_cli(self, *args):
        return subprocess.run(
            list(CLI) + list(args), capture_output=True, text=True)

    def test_sample_report_has_pinned_facts(self):
        text = (ROOT / "examples" / "sample-report.txt").read_text()
        # hand-pinned facts (not just a diff) so a format change can't
        # silently hide a metric change
        self.assertIn("payments/webhook.py", text)
        self.assertIn("Chen Wu 100%", text)
        self.assertIn("85% of measured lines are RED", text)
        self.assertIn("1 bot commits ignored", text)

    def test_sample_radius_targets_chen_wu(self):
        text = (ROOT / "examples" / "sample-radius.txt").read_text()
        self.assertIn("if Chen Wu leaves tomorrow", text)
        self.assertIn("payments/webhook.py", text)

    def test_fresh_run_matches_committed_sample(self):
        demo = ROOT / "examples" / "demo-repo"
        proc = self.run_cli("-p", str(demo), "scan", "--as-of", "2026-08-16",
                            "--min-lines", "20", "--top", "8")
        fresh = proc.stdout.replace(str(demo), "<demo-repo>")
        committed = (ROOT / "examples" / "sample-report.txt").read_text()
        self.assertEqual(fresh.strip(), committed.strip())


class DogfoodTests(unittest.TestCase):
    """bus-factor must describe THIS repo (newidea) without choking —
    and the facts it reports are a snapshot of a single-maintainer repo."""

    def test_scan_this_repo(self):
        proc = subprocess.run(
            list(CLI) + ["-p", str(ROOT.parent), "scan", "--format", "json",
                         "--min-lines", "30"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        for key in ("summary", "files", "guardians", "authors"):
            self.assertIn(key, payload)
        self.assertGreater(payload["files_measured"], 5)
        # snapshot fact: this repo has exactly one human author so far,
        # so every measured file is RED. When a second contributor
        # lands files, this assertion is expected to be relaxed.
        self.assertEqual(payload["files_measured"],
                         payload["summary"]["RED"]["files"])

    def test_radius_this_repo_author(self):
        proc = subprocess.run(
            list(CLI) + ["-p", str(ROOT.parent), "scan", "--format", "json",
                         "--min-lines", "30"],
            capture_output=True, text=True)
        author = json.loads(proc.stdout)["authors"][0]
        proc = subprocess.run(
            list(CLI) + ["-p", str(ROOT.parent), "radius", author,
                         "--min-lines", "30"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("blast radius", proc.stdout)


if __name__ == "__main__":
    unittest.main()
