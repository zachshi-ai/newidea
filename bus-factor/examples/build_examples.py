#!/usr/bin/env python3
"""
Generate deterministic example artifacts for bus-factor.

Builds examples/demo-repo/ — a real temporary git repo whose history is
engineered to hit every risk bucket:

    alice  120-line auth.py (sole guardian), 60% of billing/charge.py,
           pairs with bob on util.py (Co-Authored-By), co-writes shared.py
    bob    40% of charge.py, sole author of search/index.py, shared.py
    chen   200-line payments/webhook.py — nobody else ever touched it
    bot    one dependabot commit (ignored by default)

plus a `git mv lib.py core/lib.py` so rename-chain resolution is exercised,
then runs the real CLI (as_of pinned to 2026-08-16) and writes:

    examples/sample-report.txt    (scan --format text, root normalised)
    examples/sample-radius.txt    (radius chen)

Every important number is re-asserted from JSON output at the end — the
script fails loudly if metrics drift, so the sample can never silently rot.

Run:  python3 examples/build_examples.py
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bus_factor as bf  # noqa: E402

EX = ROOT / "examples"
DEMO = EX / "demo-repo"
AS_OF = "2026-08-16"                    # pinned so reports never change

ALICE = ("Alice Chen", "alice@corp.dev")
BOB = ("Bob Lin", "bob@corp.dev")
CHEN = ("Chen Wu", "chen@corp.dev")
BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")


def filler(n, seed=0):
    return "".join("line {0} seed {1} {2}\n".format(i, seed, "z" * 30)
                   for i in range(n))


def append(content, n, seed=0):
    return content + filler(n, seed)


def git(cwd, *args, env=None):
    proc = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                          cwd=cwd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise SystemExit("git {0} failed:\n{1}".format(args, proc.stderr))
    return proc.stdout


def commit(repo, files, author, when, message, coauthors=()):
    for rel, content in files.items():
        full = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)
    git(repo, "add", "-A", ".")
    body = message + "".join(
        "\n\nCo-Authored-By: {0} <{1}>".format(*ca) for ca in coauthors)
    env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    git(repo, "commit", "-q", "-m", body,
        "--author={0} <{1}>".format(*author), env=env)


def build_demo():
    if DEMO.exists():
        subprocess.run(["rm", "-rf", str(DEMO)], check=True)
    DEMO.mkdir(parents=True)
    git(DEMO, "init", "-q")
    git(DEMO, "config", "user.name", "Demo Committer")
    git(DEMO, "config", "user.email", "committer@corp.dev")

    base = datetime(2026, 1, 5, 9, 0, 0)
    d = lambda day: (  # noqa: E731
        base + timedelta(days=day - 5)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    # -- RED: sole knowledge ------------------------------------------------
    commit(DEMO, {"payments/webhook.py": filler(200)}, CHEN, d(5),
           "feat: payment webhook (no one else knows this)")
    commit(DEMO, {"auth.py": filler(120)}, ALICE, d(6), "feat: auth module")

    # -- RED via 50% rule: full rewrite, 60/40 split ------------------------
    commit(DEMO, {"billing/charge.py": filler(60)}, ALICE, d(7),
           "feat: charge")
    charge = append(filler(60), 40, 1)
    commit(DEMO, {"billing/charge.py": charge}, BOB, d(8),
           "fix: charge retries")

    # -- AMBER: three-way spread, no one reaches 50% -------------------------
    shared = filler(40)
    commit(DEMO, {"shared.py": shared}, ALICE, d(9), "feat: shared util")
    shared = append(shared, 35, 2)
    commit(DEMO, {"shared.py": shared}, BOB, d(10), "fix: shared util")
    commit(DEMO, {"shared.py": append(shared, 25, 3)}, CHEN, d(11),
           "chore: shared cleanup")

    # -- pair programming credit: 50/50 via Co-Authored-By -------------------
    commit(DEMO, {"util.py": filler(50)}, ALICE, d(12),
           "feat: util (pairing with bob)", coauthors=[BOB])

    # -- rename chain: history must follow the move ---------------------------
    commit(DEMO, {"lib.py": filler(80)}, ALICE, d(13), "feat: lib core")
    os.rename(DEMO / "lib.py", DEMO / "core.py")
    git(DEMO, "add", "-A", ".")
    env = dict(os.environ, GIT_AUTHOR_DATE=d(14), GIT_COMMITTER_DATE=d(14))
    git(DEMO, "commit", "-q", "-m", "refactor: move lib to core", env=env)

    # -- bot commit: ignored by default ---------------------------------------
    commit(DEMO, {"requirements.txt": "flask==3.0.0\n"}, BOT, d(15),
           "chore(deps): bump flask")
    commit(DEMO, {"README.md": "# demo-repo\n\nbus-factor fixture.\n"},
           ALICE, d(16), "docs: readme")


def run_cli(*args):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bus_factor.py")] + list(args),
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("CLI {0} failed:\n{1}".format(args, proc.stderr))
    return proc.stdout


def main():
    build_demo()

    report = run_cli("-p", str(DEMO), "scan", "--as-of", AS_OF,
                     "--min-lines", "20", "--top", "8")
    radius = run_cli("-p", str(DEMO), "radius", "chen",
                     "--as-of", AS_OF, "--min-lines", "20")
    # normalise machine-specific paths so the sample is stable
    report = report.replace(str(DEMO), "<demo-repo>")
    (EX / "sample-report.txt").write_text(report)
    (EX / "sample-radius.txt").write_text(radius)
    print("wrote sample-report.txt / sample-radius.txt")

    # -- hard assertions: the sample can never silently rot -----------------
    payload = json.loads(run_cli("-p", str(DEMO), "scan", "--as-of", AS_OF,
                                 "--format", "json", "--min-lines", "20"))
    by_path = {f["path"]: f for f in payload["files"]}

    def check(cond, what):
        if not cond:
            raise SystemExit("ASSERTION FAILED: {0}\npayload: {1}".format(
                what, json.dumps(payload, indent=2)))

    check(len(payload["authors"]) == 3,
          "3 human authors (bot ignored), got {0}".format(payload["authors"]))
    check(by_path["payments/webhook.py"]["tf"] == 1
          and by_path["payments/webhook.py"]["guardian"] == "Chen Wu"
          and by_path["payments/webhook.py"]["risk"] == "RED",
          "webhook.py is Chen's solo RED file")
    check(by_path["shared.py"]["tf"] == 2
          and by_path["shared.py"]["risk"] == "AMBER",
          "shared.py 40/35/25 spread is AMBER TF 2")
    check(by_path["billing/charge.py"]["tf"] == 1
          and by_path["billing/charge.py"]["guardian"] is None,
          "charge.py 60/40 is RED but nobody guards 80%")
    check(by_path["auth.py"]["guardian"] == "Alice Chen",
          "auth.py guarded by Alice")
    util = by_path["util.py"]["shares"]
    check(abs(util["Alice Chen"] - 0.5) < 1e-6
          and abs(util["Bob Lin"] - 0.5) < 1e-6,
          "pair credit splits util.py 50/50")
    check("core.py" in by_path and "lib.py" not in by_path,
          "rename chain moved lib.py history onto core.py")
    check(by_path["core.py"]["tf"] == 1, "core.py keeps Alice's history")
    check("Chen Wu" in payload["guardians"], "guardians lists Chen")
    check(payload["summary"]["RED"]["files"] >= 4, "several RED files")
    # surname ambiguity: 'chen' must resolve to Chen Wu (email match),
    # not to Alice Chen (whose display name contains 'chen')
    check(radius.splitlines()[0].endswith("if Chen Wu leaves tomorrow"),
          "radius chen resolves to Chen Wu, not Alice Chen: "
          + radius.splitlines()[0])
    print("all hard assertions passed — sample is in sync")


if __name__ == "__main__":
    main()
