#!/usr/bin/env python3
"""Acceptance tests for churn-hotspot (变更热点).

Every acceptance criterion from README.md is pinned here. Git integration
tests build real temporary repositories with pinned dates, so all churn
numbers, halves and levels are deterministic. Pure-function tests run
against the model without touching git.

Run:  python3 -m unittest discover -s churn-hotspot/tests -v
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

import churn_hotspot as ch  # noqa: E402

CLI = sys.executable, str(ROOT / "churn_hotspot.py")
AS_OF = "2026-08-24"                       # pinned "today"
SINCE = date(2026, 2, 25)                  # AS_OF - 180d
MID = date(2026, 5, 26)                    # SINCE + 90d: window midpoint

OLD_DAY = "2026-04-10"                     # safely inside the old half
RECENT_DAY = "2026-07-10"                  # safely inside the recent half


def filler(n, seed=0):
    return "".join("line {0} seed {1} {2}\n".format(i, seed, "z" * 30)
                   for i in range(n))


def append(content, n, seed=0):
    return content + filler(n, seed)


class GitRepo:
    """A real throwaway repository with pinned commit dates."""

    def __init__(self, td, name="repo"):
        self.path = os.path.join(td, name)
        os.makedirs(self.path)
        self.git("init", "-q")
        self.git("config", "user.name", "Test Committer")
        self.git("config", "user.email", "committer@corp.dev")

    def git(self, *args, env=None):
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false"] + list(args),
            cwd=self.path, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise AssertionError(
                "git {0} failed:\n{1}".format(args, proc.stderr))
        return proc.stdout

    def commit(self, files, when, message="work"):
        """files: {relpath: content}; content None -> delete."""
        for rel, content in files.items():
            if content is None:
                self.git("rm", "-q", "--ignore-unmatch", rel)
                continue
            full = os.path.join(self.path, rel)
            os.makedirs(os.path.dirname(full) or self.path, exist_ok=True)
            with open(full, "w", newline="") as fh:
                fh.write(content)
        self.git("add", "-A", ".")
        stamp = "{0}T12:00:00".format(when)
        env = dict(os.environ, GIT_AUTHOR_DATE=stamp,
                   GIT_COMMITTER_DATE=stamp)
        self.git("commit", "-q", "-m", message, env=env)


def cli(repo, *args):
    proc = subprocess.run(list(CLI) + list(args), cwd=repo,
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def make_repo_with_hotspots(td):
    """The canonical fixture: one file per trend class + noise.

    persistent.py  6 touches (3 old + 3 recent), 300 lines -> PERSISTENT
    emerging.py    4 touches (1 old + 3 recent), 200 lines -> EMERGING
    cooling.py     4 touches (3 old + 1 recent), 250 lines -> COOLING
    stable.py      3 touches, never hot in one half  -> STABLE
    oneshot.py     1 touch, 400 lines                -> created, not debt
    deleted.py     2 touches, then deleted           -> must not appear
    package-lock.json  5 touches                     -> excluded by default
    logo.png       3 touches (binary)                -> must not appear
    """
    repo = GitRepo(td)
    c = {"persistent.py": filler(300)}
    repo.commit(c, OLD_DAY, "seed")
    for i, day in enumerate(("2026-04-01", "2026-04-20", "2026-04-28")):
        c["persistent.py"] = append(c["persistent.py"], 3, i)
        repo.commit(c, day, "polish")
    for i, day in enumerate(("2026-07-01", "2026-07-15", "2026-07-25")):
        c["persistent.py"] = append(c["persistent.py"], 3, 10 + i)
        repo.commit(c, day, "polish")

    repo.commit({"emerging.py": filler(200)}, OLD_DAY, "seed")
    for i, day in enumerate(("2026-07-05", "2026-07-12", "2026-08-01")):
        repo.commit({"emerging.py": append(filler(200, 5), 2, i)}, day, "hot")

    repo.commit({"cooling.py": filler(250)}, "2026-03-01", "seed")
    for i, day in enumerate(("2026-03-20", "2026-04-05", "2026-05-01")):
        repo.commit({"cooling.py": append(filler(250, 6), 2, i)}, day, "old")
    repo.commit({"cooling.py": append(filler(250, 7), 2, 9)}, RECENT_DAY,
                "last touch")

    repo.commit({"stable.py": filler(80, 3)}, "2026-03-05", "seed")
    repo.commit({"stable.py": append(filler(80, 3), 2, 1)}, "2026-05-02", "x")
    repo.commit({"stable.py": append(filler(80, 4), 2, 2)}, "2026-07-18", "y")

    repo.commit({"oneshot.py": filler(400, 8)}, RECENT_DAY, "big bang")

    repo.commit({"deleted.py": filler(60, 9)}, OLD_DAY, "seed")
    repo.commit({"deleted.py": append(filler(60, 9), 2, 1)}, OLD_DAY, "x2")
    repo.commit({"deleted.py": None}, "2026-06-01", "remove")

    for i in range(5):
        repo.commit({"package-lock.json": filler(40, i) + "\n"},
                    "2026-0{0}-11".format(3 + i), "deps")

    logo = os.path.join(repo.path, "logo.png")
    with open(logo, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    repo.git("add", "-A", ".")
    repo.git("commit", "-q", "-m", "asset",
             env=dict(os.environ, GIT_AUTHOR_DATE="2026-04-02T12:00:00",
                      GIT_COMMITTER_DATE="2026-04-02T12:00:00"))
    for day in ("2026-05-03", "2026-06-15"):
        with open(logo, "ab") as fh:
            fh.write(b"\x00more")
        repo.git("add", "-A", ".")
        repo.git("commit", "-q", "-m", "asset churn",
                 env=dict(os.environ, GIT_AUTHOR_DATE=day + "T12:00:00",
                          GIT_COMMITTER_DATE=day + "T12:00:00"))
    return repo


def scan_json(repo, *extra):
    code, out, err = cli(repo, "scan", "--format", "json",
                         "--as-of", AS_OF, *extra)
    assert code == 0, err
    return json.loads(out)


# ---------------------------------------------------------------------------
# Pure model tests (no git)


class TestScoreAndTrend(unittest.TestCase):
    def test_score_is_churn_times_lines(self):
        h = ch.Hotspot("a.py", churn=7, lines=40, old_churn=3, recent_churn=4)
        self.assertEqual(h.score, 280)

    def test_trend_persistent(self):
        h = ch.Hotspot("a.py", 6, 10, 3, 3)
        self.assertEqual(h.trend, ch.TREND_PERSISTENT)

    def test_trend_emerging(self):
        h = ch.Hotspot("a.py", 4, 10, 1, 3)
        self.assertEqual(h.trend, ch.TREND_EMERGING)

    def test_trend_cooling(self):
        h = ch.Hotspot("a.py", 4, 10, 3, 1)
        self.assertEqual(h.trend, ch.TREND_COOLING)

    def test_trend_stable_when_warm_both_halves(self):
        h = ch.Hotspot("a.py", 4, 10, 2, 2)      # churn >= 3, neither extreme
        self.assertEqual(h.trend, ch.TREND_STABLE)

    def test_trend_no_signal_below_hot_churn(self):
        h = ch.Hotspot("a.py", 2, 10, 1, 1)      # churn < 3: creation, not debt
        self.assertEqual(h.trend, ch.WORSENING_NONE)


class TestLevels(unittest.TestCase):
    def mk(self, churn, lines):
        return ch.Hotspot("f{0}-{1}.py".format(churn, lines), churn, lines,
                          churn // 2, churn - churn // 2)

    def test_churn_below_3_never_earns_red_or_amber(self):
        hs = [self.mk(2, 10000), self.mk(1, 5000)]
        hs += [self.mk(4, 100 * i) for i in range(1, 8)]
        ch.assign_levels(hs)
        for h in hs[:2]:
            self.assertEqual(h.level, ch.LEVEL_GREEN)

    def test_percentiles_on_large_repos(self):
        # 10 eligible files, scores 400..4000 step 400
        hs = [self.mk(4, 100 * (i + 1)) for i in range(10)]
        ch.assign_levels(hs)
        reds = [h for h in hs if h.level == ch.LEVEL_RED]
        ambers = [h for h in hs if h.level == ch.LEVEL_AMBER]
        # nearest-rank P90 = 9th of 10 = 3600 -> 3600 and 4000 are RED
        self.assertEqual(len(reds), 2)
        self.assertEqual(sorted(h.score for h in reds), [3600, 4000])
        # P75 = 8th of 10 = 3200 -> only 3200 sits between P75 and P90
        self.assertEqual(len(ambers), 1)
        self.assertEqual(ambers[0].score, 3200)

    def test_small_repo_worst_eligible_is_red(self):
        hs = [self.mk(3, 50), self.mk(4, 200), self.mk(5, 100)]
        ch.assign_levels(hs)
        by_score = sorted(hs, key=lambda h: -h.score)
        self.assertEqual(by_score[0].level, ch.LEVEL_RED)
        for h in by_score[1:]:
            self.assertEqual(h.level, ch.LEVEL_AMBER)

    def test_no_eligible_no_levels(self):
        hs = [self.mk(1, 100), self.mk(2, 200)]
        ch.assign_levels(hs)
        self.assertTrue(all(h.level == ch.LEVEL_GREEN for h in hs))


class TestQuantile(unittest.TestCase):
    def test_nearest_rank(self):
        self.assertEqual(ch.quantile([1, 2, 3, 4, 5], 0.9), 5)
        self.assertEqual(ch.quantile([1, 2, 3, 4, 5], 0.75), 4)
        self.assertEqual(ch.quantile([10], 0.9), 10)
        self.assertEqual(ch.quantile([], 0.9), 0)


class TestExcludes(unittest.TestCase):
    def test_basename_glob(self):
        self.assertTrue(ch.excluded("web/package-lock.json",
                                    ch.DEFAULT_EXCLUDES))
        self.assertTrue(ch.excluded("api/yarn.lock", ch.DEFAULT_EXCLUDES))

    def test_path_segment_directory(self):
        self.assertTrue(ch.excluded("web/node_modules/left-pad/index.js",
                                    ch.DEFAULT_EXCLUDES))
        self.assertTrue(ch.excluded("third_party/lib.c", ch.DEFAULT_EXCLUDES))

    def test_generated_patterns(self):
        self.assertTrue(ch.excluded("app.min.js", ch.DEFAULT_EXCLUDES))
        self.assertTrue(ch.excluded("pb/user_pb2.py", ch.DEFAULT_EXCLUDES))
        self.assertTrue(ch.excluded("x/mocks.generated.ts",
                                    ch.DEFAULT_EXCLUDES))

    def test_normal_source_is_not_excluded(self):
        self.assertFalse(ch.excluded("src/app.py", ch.DEFAULT_EXCLUDES))
        self.assertFalse(ch.excluded("docs/README.md", ch.DEFAULT_EXCLUDES))

    def test_slash_pattern_matches_whole_path(self):
        self.assertTrue(ch.excluded("docs/draft.md", ("docs/draft.md",)))
        self.assertFalse(ch.excluded("docs/other.md", ("docs/draft.md",)))


class TestBinaryAndLines(unittest.TestCase):
    def test_binary_detection(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as fh:
            fh.write(b"text ok\nthen \x00 nul")
            path = fh.name
        try:
            self.assertTrue(ch.is_binary(path))
        finally:
            os.unlink(path)

    def test_text_file_is_not_binary(self):
        with tempfile.NamedTemporaryFile("w", delete=False,
                                         newline="") as fh:
            fh.write("plain\ncode\n")
            path = fh.name
        try:
            self.assertFalse(ch.is_binary(path))
            self.assertEqual(ch.count_lines(path), 2)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Git integration tests


class ScanAcceptance(unittest.TestCase):
    """`scan` against the canonical fixture repo."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo_with_hotspots(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def files_by_path(self, *extra):
        data = scan_json(self.repo.path, *extra)
        return {f["path"]: f for f in data["files"]}, data

    def test_scan_tables_have_score_churn_lines_sorted_desc(self):
        code, out, _ = cli(self.repo.path, "scan", "--as-of", AS_OF)
        self.assertEqual(code, 0)
        self.assertIn("churn", out)
        self.assertIn("score", out)
        self.assertIn("Summary:", out)
        data = scan_json(self.repo.path)
        scores = [f["score"] for f in data["files"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for f in data["files"]:
            self.assertEqual(f["score"], f["churn"] * f["lines"])

    def test_deleted_files_never_appear(self):
        files, _ = self.files_by_path()
        self.assertNotIn("deleted.py", files)

    def test_binary_files_never_appear(self):
        files, _ = self.files_by_path()
        self.assertNotIn("logo.png", files)

    def test_lockfile_excluded_by_default_but_counted(self):
        files, data = self.files_by_path()
        self.assertNotIn("package-lock.json", files)
        self.assertGreaterEqual(data["excluded"], 1)
        wide, _ = self.files_by_path("--no-default-excludes")
        self.assertIn("package-lock.json", wide)

    def test_extra_exclude_flag(self):
        files, _ = self.files_by_path("--exclude", "cooling.py")
        self.assertNotIn("cooling.py", files)
        self.assertIn("persistent.py", files)

    def test_trend_classes_are_classified(self):
        files, _ = self.files_by_path()
        self.assertEqual(files["persistent.py"]["trend"], "persistent")
        self.assertEqual(files["emerging.py"]["trend"], "emerging")
        self.assertEqual(files["cooling.py"]["trend"], "cooling")
        self.assertEqual(files["stable.py"]["trend"], "stable")
        self.assertEqual(files["oneshot.py"]["trend"], "-")

    def test_trend_halves_sum_to_churn(self):
        files, _ = self.files_by_path()
        f = files["persistent.py"]
        self.assertEqual(f["old_churn"] + f["recent_churn"], f["churn"])

    def test_window_filters_old_commits(self):
        # 60-day window (since 2026-06-25): only July/August touches count.
        files, _ = self.files_by_path("--window", "60")
        self.assertEqual(files["persistent.py"]["churn"], 3)
        # cooling.py was last touched 2026-07-10 -> present, but barely alive
        self.assertEqual(files["cooling.py"]["churn"], 1)

    def test_min_lines_filters_small_files(self):
        files, _ = self.files_by_path("--min-lines", "150")
        for path in files:
            self.assertGreaterEqual(files[path]["lines"], 150)

    def test_top_truncates_json_and_text(self):
        data = scan_json(self.repo.path, "--top", "2")
        self.assertEqual(len(data["files"]), 2)
        self.assertEqual(data["files"][0]["rank"], 1)
        self.assertEqual(data["files"][1]["rank"], 2)

    def test_red_amber_survive_top_cut_in_text(self):
        # small repo: persistent.py is RED, the other eligible files are
        # AMBER; with --top 1 they must still be appended to the table
        code, out, _ = cli(self.repo.path, "scan", "--as-of", AS_OF,
                           "--top", "1")
        self.assertEqual(code, 0)
        for name in ("persistent.py", "emerging.py", "cooling.py"):
            self.assertIn(name, out)

    def test_summary_counts_add_up(self):
        _, data = self.files_by_path()
        s = data["summary"]
        measured = len([1 for _ in data["files"]])
        self.assertEqual(s["red"] + s["amber"] + s["green"],
                         data["measured"])
        self.assertLessEqual(measured, data["measured"])

    def test_as_of_is_reproducible(self):
        a = scan_json(self.repo.path)
        b = scan_json(self.repo.path)
        self.assertEqual(a, b)
        self.assertEqual(a["as_of"], AS_OF)
        self.assertEqual(a["window_days"], 180)

    def test_fail_on_red_exits_1_when_red_exists(self):
        # fixture has eligible hotspots on a small repo -> at least one RED
        code, _, _ = cli(self.repo.path, "scan", "--as-of", AS_OF,
                         "--fail-on", "red")
        self.assertEqual(code, 1)

    def test_fail_on_passes_when_no_hotspots(self):
        # window too small to contain any commit: nothing is measured
        code, out, _ = cli(self.repo.path, "scan", "--as-of", "2020-01-01",
                           "--window", "30", "--fail-on", "red")
        self.assertEqual(code, 0)
        data = json.loads(cli(self.repo.path, "scan", "--format", "json",
                              "--as-of", "2020-01-01", "--window", "30")[1])
        self.assertEqual(data["measured"], 0)

    def test_common_flags_work_before_subcommand(self):
        code, out, _ = cli(self.repo.path, "--top", "3", "--as-of", AS_OF,
                           "scan", "--format", "json")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["files"]), 3)


class TrendCommand(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo_with_hotspots(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_trend_text_groups_with_advice(self):
        code, out, _ = cli(self.repo.path, "trend", "--as-of", AS_OF)
        self.assertEqual(code, 0)
        for token in ("PERSISTENT", "EMERGING", "COOLING",
                      "do NOT spend refactor budget here"):
            self.assertIn(token, out)
        self.assertIn("persistent.py", out)
        self.assertIn("emerging.py", out)
        self.assertIn("cooling.py", out)
        # oneshot.py never reaches churn >= 3 -> no trend row
        self.assertNotIn("oneshot.py", out)

    def test_trend_json_groups(self):
        code, out, _ = cli(self.repo.path, "trend", "--format", "json",
                           "--as-of", AS_OF)
        self.assertEqual(code, 0)
        data = json.loads(out)
        names = {k: [f["path"] for f in v] for k, v in data["groups"].items()}
        self.assertIn("persistent.py", names["persistent"])
        self.assertIn("emerging.py", names["emerging"])
        self.assertIn("cooling.py", names["cooling"])


class FileCommand(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo_with_hotspots(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_file_profile_with_histogram(self):
        code, out, _ = cli(self.repo.path, "file", "persistent.py",
                           "--as-of", AS_OF)
        self.assertEqual(code, 0)
        self.assertIn("churn 7", out)           # seed + 6 edits... see fixture
        self.assertIn("score", out)
        self.assertIn("weekly touches", out)
        self.assertIn("#", out)                 # histogram bars

    def test_file_json_rank(self):
        code, out, _ = cli(self.repo.path, "file", "persistent.py",
                           "--format", "json", "--as-of", AS_OF)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("rank", data)
        self.assertGreaterEqual(data["churn"], 6)

    def test_unknown_file_exits_2(self):
        code, _, err = cli(self.repo.path, "file", "nope.py",
                           "--as-of", AS_OF)
        self.assertEqual(code, 2)
        self.assertIn("no history", err)


class RenameChain(unittest.TestCase):
    def test_rename_keeps_churn_on_live_path(self):
        with tempfile.TemporaryDirectory() as td:
            repo = GitRepo(td)
            repo.commit({"a.py": filler(100)}, OLD_DAY, "create a")
            repo.git("mv", "a.py", "b.py")
            repo.commit({}, "2026-05-02", "rename")   # R100 a.py b.py
            repo.commit({"b.py": append(filler(100), 5, 1)}, "2026-06-01",
                        "touch 1")
            repo.commit({"b.py": append(filler(100, 1), 5, 2)}, "2026-06-15",
                        "touch 2")
            data = scan_json(repo.path)
            paths = {f["path"]: f for f in data["files"]}
            self.assertIn("b.py", paths)
            self.assertNotIn("a.py", paths)
            # create(1) + rename(1) + touch(2) all land on the live path
            self.assertEqual(paths["b.py"]["churn"], 4)


if __name__ == "__main__":
    unittest.main()
