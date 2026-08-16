#!/usr/bin/env python3
"""
Generate deterministic example artifacts for gitweek.

Builds a realistic throwaway workspace (two active repos + one idle repo)
with scripted commits at fixed dates, runs the REAL CLI via subprocess,
and writes:
    examples/sample-report.txt    (text report)
    examples/sample-report.md     (paste-ready weekly draft)

Run:  python3 examples/build_examples.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "gitweek.py"
EX = ROOT / "examples"

IDENTITY = ("Ava Lin", "ava@example.com")


def git(repo: Path, *args, env=None):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, env=env)


def write(repo: Path, fname, lines):
    f = repo / fname
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(l + "\n" for l in lines), encoding="utf-8")


def commit_at(repo: Path, when, subject):
    env = dict(os.environ,
               GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when,
               GIT_AUTHOR_NAME=IDENTITY[0], GIT_AUTHOR_EMAIL=IDENTITY[1],
               GIT_COMMITTER_NAME=IDENTITY[0], GIT_COMMITTER_EMAIL=IDENTITY[1])
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", subject, env=env)


def make_repo(base: Path, name: str) -> Path:
    repo = base / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.name", IDENTITY[0])
    git(repo, "config", "user.email", IDENTITY[1])
    return repo


def build_api(ws: Path):
    """Backend repo: 6 commits in-window + uncommitted WIP."""
    repo = make_repo(ws, "api")

    write(repo, "src/pricing.py", [f"rule_{i}" for i in range(60)])
    commit_at(repo, "2026-08-08T10:00:00", "feat: pricing endpoint")

    # v2: drop rule_0..3, add 12 guard lines -> +12/-4
    write(repo, "src/pricing.py",
          [f"rule_{i}" for i in range(4, 60)] + [f"guard_{i}" for i in range(12)])
    commit_at(repo, "2026-08-10T09:00:00", "fix: null discount crash")

    write(repo, "tests/pricing_test.py",
          [f"case_discount_{i}" for i in range(45)])
    commit_at(repo, "2026-08-10T11:00:00", "test: cover discount edge cases")

    write(repo, "requirements.txt", ["flask==3.1", "gunicorn==23.0"])
    commit_at(repo, "2026-08-11T14:00:00", "chore: bump flask to 3.1")

    # extract 18 lines out of pricing.py into tax.py -> +30/-18
    write(repo, "src/tax.py", [f"tax_rule_{i}" for i in range(30)])
    write(repo, "src/pricing.py",
          [f"rule_{i}" for i in range(4, 42)] + [f"guard_{i}" for i in range(12)])
    commit_at(repo, "2026-08-12T10:00:00", "refactor: extract tax calc")

    write(repo, "docs/runbook.md", [f"deploy step {i}" for i in range(15)])
    commit_at(repo, "2026-08-13T16:00:00", "docs: update deploy runbook")

    # WIP: uncommitted tweak (+8/-1) and one untracked scratch file
    lines = (repo / "src/pricing.py").read_text().splitlines()
    lines[0] = "rule_4  # patched locally"
    lines += [f"experiment_{i}" for i in range(8)]
    write(repo, "src/pricing.py", lines)
    write(repo, "scratch.py", ["# spike: cache warmup"])
    return repo


def build_web(ws: Path):
    """Frontend repo: 4 commits in-window."""
    repo = make_repo(ws, "web")

    write(repo, "src/Pricing.tsx", [f"<row {i}/>" for i in range(80)])
    write(repo, "src/utils.ts", [f"util_{i}" for i in range(10)])
    commit_at(repo, "2026-08-09T15:00:00", "feat: pricing table component")

    # utils.ts v2: drop util_7..9, add fix_0..9 -> +10/-3
    write(repo, "src/utils.ts",
          [f"util_{i}" for i in range(7)] + [f"fix_{i}" for i in range(10)])
    commit_at(repo, "2026-08-12T11:00:00", "fix: currency rounding")

    write(repo, "src/utils.test.ts", [f"rounding case {i}" for i in range(25)])
    commit_at(repo, "2026-08-12T11:30:00", "test: rounding cases")

    # lint: swap first two lines in each file -> +2/-2 per file, +6/-6 total
    for fname in ("src/Pricing.tsx", "src/utils.ts", "src/utils.test.ts"):
        lines = (repo / fname).read_text().splitlines()
        lines[0], lines[1] = f"/* linted */ {lines[0]}", f"/* linted */ {lines[1]}"
        write(repo, fname, lines)
    commit_at(repo, "2026-08-14T17:00:00", "style: lint fixes")
    return repo


def build_infra(ws: Path):
    """Idle repo: last touched before the window."""
    repo = make_repo(ws, "infra")
    write(repo, "main.tf", ["provider \"aws\" {}", "region = \"ap-northeast-1\""])
    commit_at(repo, "2026-07-30T10:00:00", "chore: init terraform")
    return repo


def run():
    tmp = Path(tempfile.mkdtemp(prefix="gitweek-examples-"))
    try:
        ws = tmp / "dev"
        ws.mkdir()
        build_api(ws)
        build_web(ws)
        build_infra(ws)

        base = [sys.executable, str(CLI), "report", "--scan", "-p", str(ws),
                "--as-of", "2026-08-14"]

        for fmt, dest in (("text", "sample-report.txt"), ("md", "sample-report.md")):
            proc = subprocess.run(base + ["--format", fmt],
                                  capture_output=True, text=True, check=True)
            (EX / dest).write_text(proc.stdout, encoding="utf-8")
            print(f"wrote {EX / dest}  ({fmt}, {len(proc.stdout)} bytes)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n--- preview (text) ---")
    print((EX / "sample-report.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    run()
