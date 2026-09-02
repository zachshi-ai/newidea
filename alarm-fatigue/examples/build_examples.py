#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild the alarm-fatigue demo repository: one month of a three-person
team and the four ways a CI alarm loses its credibility, every author and
both git timestamps pinned, so commit hashes and sample reports reproduce
across machines.

The story (all +08:00 wall clock, January-February 2026):

  * dana keeps her alarms honest — except the legacy one she first mutes
    (@pytest.mark.xfail), then deletes outright. The graveyard row.
  * eva fights the payment alarm: three "flaky" patches inside eight days
    (a burst), then a retry, then a skip. Credit 20 — the deaf zone.
  * frank tunes a test once, alone, with no flaky vocabulary. A single
    solo -5: honest maintenance, small tax.

Run `python3 examples/build_examples.py` to rebuild `examples/demo-repo/`
(working tree only, .git stripped) and regenerate `examples/sample-*.txt`.
Run with `--check` to verify the committed tree and reports still match a
fresh rebuild (used by the acceptance suite).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # alarm-fatigue/

sys.path.insert(0, ROOT)
import alarm_fatigue as af  # noqa: E402


def write(repo: str, rel: str, lines) -> None:
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path) or repo, exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def remove(repo: str, rel: str) -> None:
    os.remove(os.path.join(repo, rel))


def commit(repo: str, author: str, when: str, subject: str) -> None:
    name, mail = {"dana": ("Dana Dev", "dana@x.io"),
                  "eva": ("Eva Edge", "eva@x.io"),
                  "frank": ("Frank Fix", "frank@x.io")}[author]
    env = dict(os.environ)
    env["GIT_AUTHOR_DATE"] = when
    env["GIT_COMMITTER_DATE"] = when
    subprocess.run(
        ["git", "-C", repo,
         "-c", "user.name=" + name, "-c", "user.email=" + mail,
         "commit", "-q", "--allow-empty", "-m", subject],
        check=True, env=env, stdout=subprocess.DEVNULL,
    )


def build(repo: str) -> None:
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name",
                    "Dana Dev"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email",
                    "dana@x.io"], check=True)

    # -- d0 2026-01-05: the skeleton. Alarms born armed.
    write(repo, "README.md", [
        "# payshop", "",
        "A three-person shop: carts, payments, search.", "",
    ])
    write(repo, "src/cart.py", [
        "def add(cart, item, price):",
        "    cart.append((item, price))",
        "    return cart", "",
    ])
    write(repo, "tests/test_cart.py", [
        "import unittest", "",
        "from src.cart import add", "",
        "",
        "class CartTest(unittest.TestCase):",
        "    def test_add_appends(self):",
        "        cart = []",
        "        add(cart, 'mug', 12)",
        "        self.assertEqual(cart, [('mug', 12)])", "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "dana", "2026-01-05T10:03:00+08:00",
           "skeleton: cart module with first alarm")

    # -- d1 2026-01-08: payment + search alarms born (A state is clean).
    write(repo, "src/payment.py", [
        "def charge(card, amount):",
        "    \"\"\"Charge a card. The gateway hiccups under load.\"\"\"",
        "    return {\"ok\": True, \"amount\": amount}", "",
    ])
    write(repo, "tests/test_payment.py", [
        "import unittest", "",
        "from src.payment import charge", "",
        "",
        "class PaymentTest(unittest.TestCase):",
        "    def test_charge_ok(self):",
        "        self.assertTrue(charge(\"4242\", 100)[\"ok\"])",
        "",
        "    def test_charge_retries_transient(self):",
        "        seen = [charge(\"4242\", 5)[\"ok\"] for _ in range(3)]",
        "        self.assertTrue(any(seen))", "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "eva", "2026-01-08T11:20:00+08:00",
           "payments: charge endpoint with tests")

    write(repo, "src/search.py", [
        "def rank(items):",
        "    return sorted(items, reverse=True)", "",
    ])
    write(repo, "tests/test_search.py", [
        "import unittest", "",
        "",
        "class SearchTest(unittest.TestCase):",
        "    def test_ranking(self):",
        "        self.assertEqual([1, 2, 3], sorted([3, 1, 2]))", "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "frank", "2026-01-08T16:45:00+08:00",
           "search: naive ranking with a test")

    # -- d2 2026-01-10: a legacy alarm is born (also clean).
    write(repo, "tests/test_legacy.py", [
        "import unittest", "",
        "",
        "class LegacyImportTest(unittest.TestCase):",
        "    def test_old_fixture_path(self):",
        "        self.assertTrue(True)", "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "dana", "2026-01-10T09:30:00+08:00",
           "keep the legacy import test around for now")

    # -- d3 2026-01-12: first false alarm. Subject admits it: signal.
    write(repo, "tests/test_payment.py", [
        "import unittest", "",
        "from src.payment import charge", "",
        "",
        "class PaymentTest(unittest.TestCase):",
        "    def test_charge_ok(self):",
        "        # give the fake gateway a beat to settle on loaded CI",
        "        import time",
        "        time.sleep(0.05)",
        "        self.assertTrue(charge(\"4242\", 100)[\"ok\"])",
        "",
        "    def test_charge_retries_transient(self):",
        "        seen = [charge(\"4242\", 5)[\"ok\"] for _ in range(3)]",
        "        self.assertTrue(any(seen))", "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "eva", "2026-01-12T21:10:00+08:00",
           "fix flaky payment test on CI")

    # -- d4 2026-01-15: second patch. Subject admits it again.
    write(repo, "tests/test_payment.py", [
        "import unittest", "",
        "from src.payment import charge", "",
        "",
        "class PaymentTest(unittest.TestCase):",
        "    def test_charge_ok(self):",
        "        # settle window widened: CI runners are slower than laptops",
        "        import time",
        "        time.sleep(0.2)",
        "        self.assertTrue(charge(\"4242\", 100)[\"ok\"])",
        "",
        "    def test_charge_retries_transient(self):",
        "        seen = [charge(\"4242\", 5)[\"ok\"] for _ in range(3)]",
        "        self.assertTrue(any(seen))", "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "eva", "2026-01-15T19:55:00+08:00",
           "stabilize payment assertions")

    # -- d5 2026-01-20: third patch in 8 days = burst. And it is a retry.
    write(repo, "tests/test_payment.py", [
        "import unittest", "",
        "from src.payment import charge", "",
        "",
        "class PaymentTest(unittest.TestCase):",
        "    def test_charge_ok(self):",
        "        import time",
        "        time.sleep(0.2)",
        "        self.assertTrue(charge(\"4242\", 100)[\"ok\"])",
        "",
        "    def test_charge_retries_transient(self):",
        "        retries = 3",
        "        seen = [charge(\"4242\", 5)[\"ok\"] for _ in range(retries)]",
        "        self.assertTrue(any(seen))", "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "eva", "2026-01-20T20:05:00+08:00",
           "make payment test tolerant on loaded CI")

    # -- d6 2026-01-25: dana mutes the legacy alarm instead of fixing it.
    write(repo, "tests/test_legacy.py", [
        "import pytest", "",
        "",
        "class TestLegacyImport:",
        "    @pytest.mark.xfail(reason=\"old fixture, kept for archaeology\")",
        "    def test_old_fixture_path(self):",
        "        assert False", "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "dana", "2026-01-25T14:40:00+08:00",
           "mark legacy test as expected failure")

    # -- d7 2026-01-30: frank tunes a test once, alone, no drama: solo.
    write(repo, "tests/test_search.py", [
        "import unittest", "",
        "",
        "class SearchTest(unittest.TestCase):",
        "    def test_ranking(self):",
        "        self.assertEqual([3, 2, 1], sorted([1, 2, 3], reverse=True))",
        "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "frank", "2026-01-30T10:15:00+08:00",
           "adjust search test for the new ranking")

    # -- d8 2026-02-02: the battery comes out. @unittest.skip lands.
    write(repo, "tests/test_payment.py", [
        "import unittest", "",
        "from src.payment import charge", "",
        "",
        "",
        "@unittest.skip(\"flaky on CI, ticket PAY-331\")",
        "class PaymentTest(unittest.TestCase):",
        "    def test_charge_ok(self):",
        "        import time",
        "        time.sleep(0.2)",
        "        self.assertTrue(charge(\"4242\", 100)[\"ok\"])",
        "",
        "    def test_charge_retries_transient(self):",
        "        retries = 3",
        "        seen = [charge(\"4242\", 5)[\"ok\"] for _ in range(retries)]",
        "        self.assertTrue(any(seen))", "",
    ])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "eva", "2026-02-02T22:30:00+08:00",
           "hold payment test on CI for now")

    # -- d9 2026-02-05: the legacy alarm is removed, not fixed.
    remove(repo, "tests/test_legacy.py")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    commit(repo, "dana", "2026-02-05T15:00:00+08:00",
           "remove dead legacy test")


def render_reports(repo: str) -> dict:
    result = af.analyze(repo)
    result.repo = "demo-repo"  # pin the label: tmp paths must not leak
    payment = next(f for f in result.files
                   if f.path == "tests/test_payment.py")
    return {
        "sample-audit.txt": af.render_audit(result) + "\n",
        "sample-explain.txt": af.render_explain(payment, "demo-repo") + "\n",
    }


def tree_diff(a: str, b: str) -> bool:
    """True when the working trees (ignoring .git) are identical."""
    out = subprocess.run(
        ["diff", "-r", "-x", ".git", a, b],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if out.returncode != 0:
        sys.stderr.write(out.stdout.decode("utf-8", "replace"))
        return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify committed demo tree + reports match a rebuild")
    args = ap.parse_args(argv)

    demo = os.path.join(HERE, "demo-repo")
    tmp = tempfile.mkdtemp(prefix="af-demo-")
    try:
        build(os.path.join(tmp, "demo-repo"))
        reports = render_reports(os.path.join(tmp, "demo-repo"))

        if args.check:
            if not os.path.isdir(demo):
                print("demo-repo/ missing; run without --check first")
                return 1
            if not tree_diff(demo, os.path.join(tmp, "demo-repo")):
                return 1
            for name, want in reports.items():
                path = os.path.join(HERE, name)
                if not os.path.exists(path):
                    print("%s missing" % name)
                    return 1
                with open(path) as fh:
                    if fh.read() != want:
                        print("%s out of sync; rebuild examples" % name)
                        return 1
            print("examples in sync")
            return 0

        if os.path.isdir(demo):
            shutil.rmtree(demo)
        shutil.copytree(os.path.join(tmp, "demo-repo"), demo,
                        ignore=shutil.ignore_patterns(".git"))
        for name, text in reports.items():
            with open(os.path.join(HERE, name), "w") as fh:
                fh.write(text)
        print("rebuilt examples/demo-repo + 2 sample reports")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
