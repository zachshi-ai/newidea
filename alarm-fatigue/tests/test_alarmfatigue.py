#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance suite for alarm-fatigue.

Every acceptance criterion from the README maps to tests here.  Git-level
tests build throwaway repositories with GIT_AUTHOR_DATE / GIT_COMMITTER_DATE
pinned, so patch timelines (and their credits) are exact.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # alarm-fatigue/
REPO_ROOT = os.path.dirname(ROOT)            # the newidea repo (dogfood)

sys.path.insert(0, ROOT)
import alarm_fatigue as af  # noqa: E402

CLI = os.path.join(ROOT, "alarm_fatigue.py")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, CLI] + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


class RepoCase(unittest.TestCase):
    """Test case with a throwaway git repo and time-pinned commits."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="af-test-")
        self.repo = os.path.join(self.tmp, "r")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        # Repo-local identity so commits work on CI runners without a
        # global git config.
        subprocess.run(["git", "-C", self.repo, "config", "user.name",
                        "Tester"], check=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.email",
                        "tester@x.io"], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit(self, when, msg, files, author="Dev <dev@x.io>"):
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
             "-c", "user.name=" + name, "-c", "user.email=" + mail[:-1],
             "commit", "-q", "-m", msg],
            env=env, check=True)

    def audit(self, **kw):
        return af.analyze(self.repo, **kw)

    def report(self, path):
        result = self.audit()
        for f in result.files + result.graveyard:
            if f.path == path:
                return f
        raise AssertionError("no report for %s" % path)


# ---------------------------------------------------------------------------
# Pure helpers: test-file patterns


class FilePatternTests(unittest.TestCase):
    def test_python_test_names(self):
        self.assertTrue(af.is_test_path("tests/test_cart.py"))
        self.assertTrue(af.is_test_path("pkg/login_test.py"))

    def test_other_languages(self):
        for p in ("pkg/http_test.go", "src/CartTests.java",
                  "app/components/cart.test.tsx", "spec/models/user_spec.rb",
                  "StringTests.swift", "src/lib_test.rs", "map_test.c",
                  "handler_test.cc", "MyTests.kt", "sum.test.mjs",
                  "worker_test.exs", "parser_spec.js"):
            self.assertTrue(af.is_test_path(p), p)

    def test_helpers_are_not_alarms(self):
        for p in ("tests/conftest.py", "src/cart.py", "tests/helpers.py",
                  "test_utils/README.md", "testdata/app.py",
                  "src/testdata.py", "tests/factories/base.py"):
            self.assertFalse(af.is_test_path(p), p)

    def test_extra_globs_extend_the_definition(self):
        self.assertFalse(af.is_test_path("qa/checks.py"))
        self.assertTrue(af.is_test_path("qa/checks.py", ["qa/*.py"]))


# ---------------------------------------------------------------------------
# Pure helpers: flaky vocabulary


class SignalTests(unittest.TestCase):
    def test_english_flaky_vocabulary(self):
        for msg in ("fix flaky payment test on CI",
                    "stabilize login assertions",
                    "checkout test is intermittent on CI",
                    "rerun failed job",
                    "fix the test for search",
                    "test fix: retry the flaky bit",
                    "upload looks unstable in CI"):
            self.assertRegex(msg, af.DEFAULT_SIGNAL_REGEX, msg)

    def test_chinese_flaky_vocabulary(self):
        for msg in ("修复偶现失败的测试", "这个用例随机失败", "修测试",
                    "重跑一下", "登录用例飘了"):
            self.assertRegex(msg, af.DEFAULT_SIGNAL_REGEX, msg)

    def test_honest_work_is_not_vocabulary(self):
        for msg in ("add cart feature", "docs: update readme",
                    "retry uploads with backoff",
                    "skip ci for docs-only change",
                    "bump dependency to 2.1"):
            self.assertNotRegex(msg, af.DEFAULT_SIGNAL_REGEX, msg)

    def test_custom_signal_regex(self):
        custom = r"(?i)\bmake\w*\b.*\bgreen\b"
        self.assertRegex("make the build green again", custom)
        self.assertNotRegex("fix flaky login test", custom)


# ---------------------------------------------------------------------------
# Pure helpers: diff marks, credit, burst


class MarkDetectionTests(unittest.TestCase):
    def test_mute_marks_on_added_lines(self):
        patch = ("@@ -1 +1 @@\n"
                 "-class PaymentTest(unittest.TestCase):\n"
                 "+@unittest.skip(\"flaky on CI\")\n"
                 "+class PaymentTest(unittest.TestCase):\n")
        self.assertEqual(af.classify_added_lines(af.added_lines_of(patch)),
                         {"mute"})

    def test_xfail_skip_and_focus_marks(self):
        lines = ["    @pytest.mark.xfail(reason=\"old\")",
                 "    @Disabled(\"on linux\")",
                 "    it.skip(\"race\")",
                 "    it.only(\"the one that matters\")",
                 "  focus: true"]
        marks = af.classify_added_lines(lines)
        self.assertIn("mute", marks)
        self.assertIn("focus", marks)

    def test_retry_marks(self):
        for line in ("        retries = 3",
                     "    @pytest.mark.flaky(reruns=2)",
                     "  flaky(flaky_retires=5)",
                     "@retry(stop=after_attempt(3))"):
            self.assertIn("retry", af.classify_added_lines([line]), line)

    def test_removed_marks_do_not_count(self):
        # un-muting is a repair, never a charge
        patch = ("@@ -1 +1 @@\n"
                 "-@unittest.skip(\"flaky\")\n"
                 "+class PaymentTest(unittest.TestCase):\n")
        self.assertEqual(af.classify_added_lines(af.added_lines_of(patch)),
                         set())

    def test_ordinary_edits_hit_nothing(self):
        lines = ["        self.assertEqual(3, len(cart))",
                 "        # wider window, CI runners are slower"]
        self.assertEqual(af.classify_added_lines(lines), set())


class CreditTests(unittest.TestCase):
    def test_weights_are_ordered(self):
        self.assertEqual(af.heaviest({"mute", "solo"}), "mute")
        self.assertEqual(af.heaviest({"focus", "retry"}), "focus")
        self.assertEqual(af.heaviest({"retry", "signal", "solo"}), "retry")
        self.assertEqual(af.heaviest({"signal", "solo"}), "signal")
        self.assertEqual(af.heaviest({"solo"}), "solo")

    def test_clean_file_keeps_100(self):
        self.assertEqual(af.credit_of([], burst=False), 100)
        self.assertEqual(af.grade_of(100), "trusted")

    def test_grade_boundaries(self):
        self.assertEqual(af.grade_of(80), "trusted")
        self.assertEqual(af.grade_of(79), "shaky")
        self.assertEqual(af.grade_of(60), "shaky")
        self.assertEqual(af.grade_of(59), "habitual")
        self.assertEqual(af.grade_of(40), "habitual")
        self.assertEqual(af.grade_of(39), "deaf")
        self.assertEqual(af.grade_of(0), "deaf")

    def test_credit_bottoms_at_zero(self):
        self.assertEqual(af.credit_of(["mute"] * 5, burst=True), 0)

    def test_burst_charges_on_top(self):
        kinds = ["signal", "signal", "signal"]
        self.assertEqual(af.credit_of(kinds, burst=False), 70)
        self.assertEqual(af.credit_of(kinds, burst=True), 60)

    def test_each_event_charged_once(self):
        # tags ride along; only the heaviest kind is charged
        self.assertEqual(af.credit_of(["signal"], burst=False), 90)


class BurstTests(unittest.TestCase):
    def test_three_patches_inside_the_window(self):
        days = ["2026-01-12T21:10:00+08:00",
                "2026-01-15T19:55:00+08:00",
                "2026-01-20T20:05:00+08:00"]
        self.assertEqual(af.burst_window(days, 14, 3),
                         ("2026-01-12", "2026-01-20"))

    def test_scattered_patches_are_not_a_burst(self):
        days = ["2026-01-12T21:10:00+08:00",
                "2026-02-15T19:55:00+08:00",
                "2026-03-20T20:05:00+08:00"]
        self.assertIsNone(af.burst_window(days, 14, 3))

    def test_window_and_minimum_are_tunable(self):
        days = ["2026-01-01T09:00:00+08:00",
                "2026-01-04T09:00:00+08:00"]
        self.assertEqual(af.burst_window(days, 5, 2),
                         ("2026-01-01", "2026-01-04"))
        self.assertIsNone(af.burst_window(days, 5, 3))
        self.assertIsNone(af.burst_window(days, 2, 2))


# ---------------------------------------------------------------------------
# Git integration: the whole attribution chain


class GitIntegrationTests(RepoCase):
    PAY_V1 = ["import unittest", "", "",
              "class PaymentTest(unittest.TestCase):",
              "    def test_ok(self):",
              "        self.assertTrue(True)", ""]

    def test_birth_is_not_a_patch(self):
        # TDD: a test being born is clean, even with flaky vocabulary
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py": self.PAY_V1})
        f = self.report("tests/test_payment.py")
        self.assertEqual(f.events, [])
        self.assertEqual(f.credit, 100)

    def test_flaky_subject_with_solo_is_one_signal_charge(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py": self.PAY_V1})
        self.commit("2026-01-02T10:00:00+08:00", "fix flaky payment test",
                    {"tests/test_payment.py":
                     self.PAY_V1[:4] + ["        # settle"] + self.PAY_V1[4:]})
        f = self.report("tests/test_payment.py")
        self.assertEqual(len(f.events), 1)
        self.assertEqual(f.events[0].kind, "signal")
        self.assertEqual(sorted(f.events[0].tags), ["signal", "solo"])
        self.assertEqual(f.credit, 90)      # solo rides along, no double charge

    def test_mute_diff_charges_thirty(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py": self.PAY_V1})
        self.commit("2026-01-02T10:00:00+08:00", "hold payment test for now",
                    {"tests/test_payment.py":
                     ["import unittest", "", "",
                      "@unittest.skip(\"flaky on CI\")",
                      "class PaymentTest(unittest.TestCase):",
                      "    def test_ok(self):",
                      "        self.assertTrue(True)", ""]})
        f = self.report("tests/test_payment.py")
        self.assertEqual(f.events[0].kind, "mute")
        self.assertEqual(f.credit, 70)
        self.assertEqual(f.grade, "shaky")

    def test_retry_and_focus_diffs(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py": self.PAY_V1})
        self.commit("2026-01-02T10:00:00+08:00", "widen tolerance",
                    {"tests/test_payment.py":
                     self.PAY_V1[:5] + ["        retries = 3"] +
                     self.PAY_V1[5:]})
        self.commit("2026-02-02T10:00:00+08:00", "narrow the run locally",
                    {"tests/test_payment.py":
                     ["import unittest", "", "",
                      "class PaymentTest(unittest.TestCase):",
                      "    def test_ok(self):", "",
                      "    def test_only_this(self):",
                      "        self.assertTrue(self.only(True))", ""]})
        f = self.report("tests/test_payment.py")
        self.assertEqual([e.kind for e in f.events], ["retry", "focus"])
        self.assertEqual(f.credit, 100 - 20 - 25)

    def test_solo_test_only_commit(self):
        self.commit("2026-01-01T10:00:00+08:00", "add search test",
                    {"tests/test_search.py":
                     ["class SearchTest:", "    def test_rank(self):",
                      "        assert sorted([3, 1, 2]) == [1, 2, 3]", ""]})
        self.commit("2026-01-02T10:00:00+08:00",
                    "adjust search test for the new ranking",
                    {"tests/test_search.py":
                     ["class SearchTest:", "    def test_rank(self):",
                      "        assert sorted([1, 2, 3]) == [1, 2, 3]", ""]})
        f = self.report("tests/test_search.py")
        self.assertEqual(f.events[0].kind, "solo")
        self.assertEqual(f.credit, 95)

    def test_solo_not_charged_when_impl_changes_same_commit(self):
        self.commit("2026-01-01T10:00:00+08:00", "add search",
                    {"src/search.py": ["def rank(items):",
                                       "    return sorted(items)", ""],
                     "tests/test_search.py":
                     ["class SearchTest:", "    def test_rank(self):",
                      "        assert rank([3, 1]) == [1, 3]", ""]})
        # "stabilize" IS vocabulary — the event stays — but solo does not
        # ride along, because the implementation changed in the same commit.
        self.commit("2026-01-02T10:00:00+08:00", "stabilize ranking",
                    {"src/search.py": ["def rank(items):",
                                       "    return sorted(items, reverse=True)",
                                       ""],
                     "tests/test_search.py":
                     ["class SearchTest:", "    def test_rank(self):",
                      "        assert rank([1, 3]) == [3, 1]", ""]})
        f = self.report("tests/test_search.py")
        self.assertEqual([e.kind for e in f.events], ["signal"])
        self.assertEqual([e.tags for e in f.events], [["signal"]])

    def test_burst_e2e(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py": self.PAY_V1})
        for i, day in enumerate(("2026-01-02", "2026-01-05", "2026-01-09")):
            self.commit(day + "T10:00:00+08:00",
                        "fix flaky payment test #%d" % (i + 1),
                        {"tests/test_payment.py":
                         self.PAY_V1[:4] + ["        # take %d" % i] +
                         self.PAY_V1[4:]})
        f = self.report("tests/test_payment.py")
        self.assertIsNotNone(f.burst)
        self.assertEqual(f.burst, ("2026-01-02", "2026-01-09"))
        self.assertEqual(f.credit, 100 - 3 * 10 - 10)

    def test_deleted_test_lands_in_the_graveyard(self):
        self.commit("2026-01-01T10:00:00+08:00", "add legacy test",
                    {"tests/test_legacy.py": self.PAY_V1})
        self.commit("2026-01-02T10:00:00+08:00", "mark legacy as expected",
                    {"tests/test_legacy.py":
                     ["import pytest", "", "",
                      "class TestLegacy:",
                      "    @pytest.mark.xfail(reason=\"old\")",
                      "    def test_old(self):", "        assert False", ""]})
        self.commit("2026-01-03T10:00:00+08:00", "remove dead legacy test",
                    {"tests/test_legacy.py": None})
        result = self.audit()
        self.assertEqual([f.path for f in result.files], [])
        self.assertEqual(len(result.graveyard), 1)
        grave = result.graveyard[0]
        self.assertEqual(grave.deleted, "2026-01-03")
        self.assertEqual(grave.credit, 70)   # mute charged before death

    def test_renamed_test_does_not_crash(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py": self.PAY_V1})
        os.rename(os.path.join(self.repo, "tests/test_payment.py"),
                  os.path.join(self.repo, "tests/test_payments.py"))
        subprocess.run(["git", "-C", self.repo, "add", "-A"], check=True)
        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = "2026-01-02T10:00:00+08:00"
        env["GIT_COMMITTER_DATE"] = "2026-01-02T10:00:00+08:00"
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m",
                        "rename for clarity"], env=env, check=True)
        result = self.audit()
        paths = [f.path for f in result.files] + \
                [f.path for f in result.graveyard]
        self.assertIn("tests/test_payments.py", paths)
        self.assertIn("tests/test_payment.py", paths)  # old path: dead

    def test_since_window_can_repay_credit(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py": self.PAY_V1})
        self.commit("2026-01-02T10:00:00+08:00", "fix flaky payment test",
                    {"tests/test_payment.py":
                     self.PAY_V1[:4] + ["        # settle"] + self.PAY_V1[4:]})
        self.commit("2026-06-01T10:00:00+08:00", "touch readme",
                    {"README.md": ["hello", ""]})
        fresh = af.analyze(self.repo, since="2026-05-01")
        payment = next(f for f in fresh.files
                       if f.path == "tests/test_payment.py")
        self.assertEqual(payment.events, [])
        self.assertEqual(payment.credit, 100)

    def test_diff_budget_degrades_to_message_only(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py": self.PAY_V1})
        self.commit("2026-01-02T10:00:00+08:00", "hold payment test for now",
                    {"tests/test_payment.py":
                     ["import unittest", "", "",
                      "@unittest.skip(\"flaky on CI\")",
                      "class PaymentTest(unittest.TestCase):",
                      "    def test_ok(self):",
                      "        self.assertTrue(True)", ""]})
        capped = af.analyze(self.repo, max_diff_commits=0)
        self.assertTrue(capped.diff_budget_hit)
        payment = next(f for f in capped.files
                       if f.path == "tests/test_payment.py")
        # the mute lives only in the diff: capped, it goes unseen — but
        # solo survives, it needs just the file list
        self.assertEqual([e.kind for e in payment.events], ["solo"])
        self.assertEqual(payment.credit, 95)
        self.assertIn("capped", capped.to_json()["notes"][0])


# ---------------------------------------------------------------------------
# End-to-end: demo scenario through the analyzer


class ScenarioTests(RepoCase):
    def build_demo(self):
        self.commit("2026-01-05T10:03:00+08:00", "skeleton with cart test",
                    {"tests/test_cart.py": ["class CartTest:",
                                            "    def test_add(self):",
                                            "        assert True", ""]},
                    author="Dana Dev <dana@x.io>")
        self.commit("2026-01-08T11:20:00+08:00", "payments with test",
                    {"src/payment.py": ["def charge():", "    return True", ""],
                     "tests/test_payment.py":
                     ["class PaymentTest:",
                      "    def test_ok(self):", "        assert True", ""]},
                    author="Eva Edge <eva@x.io>")
        self.commit("2026-01-12T21:10:00+08:00",
                    "fix flaky payment test on CI",
                    {"tests/test_payment.py":
                     ["class PaymentTest:",
                      "    def test_ok(self):", "        import time",
                      "        time.sleep(0.05)", "        assert True", ""]},
                    author="Eva Edge <eva@x.io>")
        self.commit("2026-01-15T19:55:00+08:00",
                    "stabilize payment assertions",
                    {"tests/test_payment.py":
                     ["class PaymentTest:",
                      "    def test_ok(self):", "        import time",
                      "        time.sleep(0.2)", "        assert True", ""]},
                    author="Eva Edge <eva@x.io>")

    def test_suite_numbers(self):
        self.build_demo()
        result = self.audit()
        data = result.to_json()
        self.assertEqual(data["suite"]["test_files"], 2)
        self.assertEqual(data["suite"]["patched"], 1)
        self.assertEqual(data["suite"]["total_patch_events"], 2)
        # alive credits: cart 100, payment 80 -> median 90
        self.assertEqual(data["suite"]["median_credit"], 90)
        payment = next(f for f in result.files
                       if f.path == "tests/test_payment.py")
        self.assertEqual(payment.credit, 80)
        self.assertIsNone(payment.burst)   # only 2 patches: burst needs 3

    def test_json_shape(self):
        self.build_demo()
        data = self.audit().to_json()
        for key in ("repo", "window", "suite", "files", "graveyard", "notes"):
            self.assertIn(key, data)
        for key in ("test_files", "patched", "patch_ratio",
                    "total_patch_events", "median_credit", "deaf"):
            self.assertIn(key, data["suite"])
        for key in ("path", "credit", "grade", "patches", "burst", "signals",
                    "first_patch", "last_patch"):
            self.assertIn(key, data["files"][0])


# ---------------------------------------------------------------------------
# CLI


class CliTests(RepoCase):
    def test_audit_text_mentions_deaf_and_graveyard(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py":
                     ["class PaymentTest:", "    def test_ok(self):",
                      "        assert True", ""]})
        out = run_cli("audit", self.repo)
        self.assertEqual(out.returncode, 0)
        text = out.stdout.decode()
        self.assertIn("-- Alarm Fatigue audit:", text)
        self.assertIn("suite alarm credit", text)
        self.assertIn("tests/test_payment.py", text)

    def test_audit_json_roundtrip(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py":
                     ["class PaymentTest:", "    def test_ok(self):",
                      "        assert True", ""]})
        out = run_cli("audit", self.repo, "--format", "json")
        self.assertEqual(out.returncode, 0)
        data = json.loads(out.stdout.decode())
        self.assertEqual(data["suite"]["test_files"], 1)

    def test_explain_timeline_and_json(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py":
                     ["class PaymentTest:", "    def test_ok(self):",
                      "        assert True", ""]})
        self.commit("2026-01-02T10:00:00+08:00", "fix flaky payment test",
                    {"tests/test_payment.py":
                     ["class PaymentTest:", "    def test_ok(self):",
                      "        assert True  # settled", ""]})
        out = run_cli("explain", "tests/test_payment.py", self.repo)
        text = out.stdout.decode()
        self.assertIn("signal", text)
        self.assertIn("final: credit 90", text)

        js = run_cli("explain", "tests/test_payment.py", self.repo,
                     "--format", "json")
        data = json.loads(js.stdout.decode())
        self.assertEqual(data["timeline"][0]["kind"], "signal")
        self.assertEqual(data["timeline"][0]["running_credit"], 90)

    def test_explain_unknown_file_exits_3(self):
        out = run_cli("explain", "tests/nope_test.py", self.repo)
        self.assertEqual(out.returncode, 3)

    def test_not_a_git_repo_exits_3(self):
        empty = tempfile.mkdtemp(prefix="af-empty-")
        try:
            out = run_cli("audit", empty)
            self.assertEqual(out.returncode, 3)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_no_subcommand_exits_2(self):
        out = run_cli()
        self.assertEqual(out.returncode, 2)

    def test_fail_under_gates_the_suite(self):
        self.commit("2026-01-01T10:00:00+08:00", "add payment test",
                    {"tests/test_payment.py":
                     ["class PaymentTest:", "    def test_ok(self):",
                      "        assert True", ""]})
        self.commit("2026-01-02T10:00:00+08:00", "fix flaky payment test",
                    {"tests/test_payment.py":
                     ["class PaymentTest:", "    def test_ok(self):",
                      "        assert True  # settled", ""]})
        # median is 90: gate at 95 fails, gate at 80 passes
        strict = run_cli("audit", self.repo, "--fail-under", "95")
        self.assertEqual(strict.returncode, 4)
        loose = run_cli("audit", self.repo, "--fail-under", "80")
        self.assertEqual(loose.returncode, 0)

    def test_top_hides_rows(self):
        for i in range(5):
            self.commit("2026-01-0%dT10:00:00+08:00" % (i + 1),
                        "add module %d with test" % i,
                        {"src/m%d.py" % i: ["x = %d" % i, ""],
                         "tests/test_m%d.py" % i:
                         ["class M%dTest:" % i, "    def test_x(self):",
                          "        assert True", ""]})
        out = run_cli("audit", self.repo, "--top", "2")
        text = out.stdout.decode()
        self.assertIn("and 3 more", text)


# ---------------------------------------------------------------------------
# Dogfood: the tool on its own birthplace


class DogfoodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = af.analyze(REPO_ROOT)

    def test_audit_of_newidea_does_not_crash(self):
        self.assertGreater(self.result.commits_scanned, 0)

    def test_all_credits_in_range_and_graded(self):
        for f in self.result.files + self.result.graveyard:
            self.assertGreaterEqual(f.credit, 0)
            self.assertLessEqual(f.credit, 100)
            self.assertEqual(f.grade, af.grade_of(f.credit))

    def test_explain_some_real_test_file(self):
        if self.result.files:
            path = self.result.files[0].path
            out = run_cli("explain", path, REPO_ROOT)
            self.assertEqual(out.returncode, 0)
            self.assertIn("final: credit", out.stdout.decode())


# ---------------------------------------------------------------------------
# Examples: rebuildable, byte-identical


class ExamplesSyncTests(unittest.TestCase):
    def test_examples_in_sync(self):
        out = subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "examples", "build_examples.py"), "--check"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.assertEqual(out.returncode, 0, out.stdout.decode())


if __name__ == "__main__":
    unittest.main()
