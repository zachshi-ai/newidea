#!/usr/bin/env python3
"""
Generate deterministic example artifacts for churn-hotspot.

Builds examples/demo-repo/ — a real temporary git repo whose history is
engineered to hit every trend class:

    checkout/flow.py      7 touches across the whole window, 300+ lines
                          -> PERSISTENT (the ever-bleeding core)
    pay/api.py            1 old touch + 4 recent, 200+ lines
                          -> EMERGING (a new fire, still cheap to fix)
    search/legacy_index.py 4 old touches + 1 recent, 250 lines
                          -> COOLING (legacy debt healing on its own)
    util.py               3 touches, warm in both halves -> STABLE
    migrations/001_init.sql  400 lines, written once (creation, not debt)
    pay/refund.py         renamed from pay/rename_me.py, then touched twice
                          -> rename chain keeps churn on the live path
    package-lock.json     5 touches -> excluded by default (dependency noise)
    logo.png              3 touches -> skipped (binary)

then runs the real CLI (as_of pinned to 2026-08-24, window 180d) and writes:

    examples/sample-report.txt    (scan, text)
    examples/sample-trend.txt     (trend, text)

Every important number is re-asserted from JSON output at the end — the
script fails loudly if metrics drift, so the samples can never silently rot.

Run:  python3 examples/build_examples.py
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EX = ROOT / "examples"
DEMO = EX / "demo-repo"
AS_OF = "2026-08-24"                    # pinned so reports never change
WINDOW = "180"

CLI = [sys.executable, str(ROOT / "churn_hotspot.py")]


def filler(n, seed=0):
    return "".join("line {0} seed {1} {2}\n".format(i, seed, "z" * 30)
                   for i in range(n))


def append(content, n, seed=0):
    return content + filler(n, seed)


def git(*args, env=None):
    proc = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                          cwd=DEMO, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise SystemExit("git {0} failed:\n{1}".format(args, proc.stderr))


def commit(files, when, message):
    for rel, content in files.items():
        full = DEMO / rel
        os.makedirs(full.parent, exist_ok=True)
        with open(full, "w", newline="") as fh:
            fh.write(content)
    git("add", "-A", ".")
    stamp = "{0}T12:00:00".format(when)
    git("commit", "-q", "-m", message,
        env=dict(os.environ, GIT_AUTHOR_DATE=stamp,
                 GIT_COMMITTER_DATE=stamp))


def build_demo():
    if DEMO.exists():
        shutil.rmtree(DEMO)
    os.makedirs(DEMO)
    git("init", "-q")
    git("config", "user.name", "Demo Team")
    git("config", "user.email", "team@shop.dev")

    # -- PERSISTENT: the checkout core, bleeding since day one ----------
    flow = {"checkout/flow.py": filler(300)}
    commit(flow, "2026-03-15", "checkout flow v0")
    for day in ("2026-04-01", "2026-04-20"):           # old half
        flow["checkout/flow.py"] = append(flow["checkout/flow.py"], 3)
        commit(flow, day, "fix edge cases")
    for day in ("2026-07-01", "2026-07-10", "2026-07-22", "2026-08-05"):
        flow["checkout/flow.py"] = append(flow["checkout/flow.py"], 3)
        commit(flow, day, "promo rules, again")

    # -- EMERGING: new pay API, suddenly hot ----------------------------
    api = {"pay/api.py": filler(220)}
    commit(api, "2026-04-02", "pay api v0")
    for day in ("2026-07-05", "2026-07-18", "2026-07-30", "2026-08-08"):
        api["pay/api.py"] = append(api["pay/api.py"], 2)
        commit(api, day, "add endpoint")

    # -- COOLING: legacy search index, abandoned ------------------------
    idx = {"search/legacy_index.py": filler(250)}
    commit(idx, "2026-03-02", "legacy index import")
    for day in ("2026-03-18", "2026-04-05", "2026-05-10"):
        idx["search/legacy_index.py"] = append(idx["search/legacy_index.py"], 2)
        commit(idx, day, "tune index")
    idx["search/legacy_index.py"] = append(idx["search/legacy_index.py"], 2, 9)
    commit(idx, "2026-06-20", "final tweak before freeze")

    # -- STABLE + ONESHOT + noise ---------------------------------------
    util = {"util.py": filler(80)}
    commit(util, "2026-03-05", "utils")
    util["util.py"] = append(util["util.py"], 2)
    commit(util, "2026-05-02", "helper")
    util["util.py"] = append(util["util.py"], 2)
    commit(util, "2026-07-18", "helper again")

    commit({"migrations/001_init.sql": filler(400, 7)}, "2026-03-20",
           "initial schema")

    # rename chain: churn follows the live path
    commit({"pay/rename_me.py": filler(100, 9)}, "2026-04-12", "add refunds")
    git("mv", "pay/rename_me.py", "pay/refund.py")
    commit({}, "2026-05-04", "rename to refund.py")
    ref = {"pay/refund.py": filler(100, 9)}
    ref["pay/refund.py"] = append(ref["pay/refund.py"], 5, 1)
    commit(ref, "2026-06-30", "partial refunds")
    ref["pay/refund.py"] = append(ref["pay/refund.py"], 5, 2)
    commit(ref, "2026-07-20", "refund limits")

    for i in range(5):
        commit({"package-lock.json": filler(40, i) + "\n"},
               "2026-0{0}-11".format(3 + i), "deps")

    logo = DEMO / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00fake")
    git("add", "-A", ".")
    git("commit", "-q", "-m", "logo",
        env=dict(os.environ, GIT_AUTHOR_DATE="2026-04-02T12:00:00",
                 GIT_COMMITTER_DATE="2026-04-02T12:00:00"))
    for day in ("2026-05-03", "2026-06-15"):
        with open(logo, "ab") as fh:
            fh.write(b"\x00more")
        git("add", "-A", ".")
        git("commit", "-q", "-m", "logo churn",
            env=dict(os.environ, GIT_AUTHOR_DATE=day + "T12:00:00",
                     GIT_COMMITTER_DATE=day + "T12:00:00"))

    with open(DEMO / "README.md", "w", newline="") as fh:
        fh.write(
            "# demo-repo\n\nGenerated by `examples/build_examples.py` —"
            " do not edit.\nA miniature e-commerce backend engineered to"
            " contain one file per trend class\n(persistent / emerging /"
            " cooling / stable), a rename chain, lockfile noise and a"
            " binary.\n")
    git("add", "-A", ".")
    git("commit", "-q", "-m", "explain demo repo",
        env=dict(os.environ, GIT_AUTHOR_DATE="2026-08-10T12:00:00",
                 GIT_COMMITTER_DATE="2026-08-10T12:00:00"))


def run(*args):
    proc = subprocess.run(CLI + list(args), cwd=DEMO,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("CLI {0} failed:\n{1}".format(args, proc.stderr))
    return proc.stdout


def expect(cond, what):
    if not cond:
        raise SystemExit("sample assertion failed: {0}".format(what))


def write_sample(path, text):
    with open(path, "w", newline="") as fh:
        fh.write(text)


def main():
    build_demo()
    write_sample(EX / "sample-report.txt",
                 run("scan", "--as-of", AS_OF, "--window", WINDOW))
    write_sample(EX / "sample-trend.txt",
                 run("trend", "--as-of", AS_OF, "--window", WINDOW))

    # -- assertions: the samples can never silently rot ------------------
    data = json.loads(run("scan", "--format", "json",
                          "--as-of", AS_OF, "--window", WINDOW))
    by = {f["path"]: f for f in data["files"]}
    expect("checkout/flow.py" in by, "flow.py measured")
    flow = by["checkout/flow.py"]
    expect(flow["churn"] == 7, "flow churn 7, got {0}".format(flow["churn"]))
    expect(flow["trend"] == "persistent", "flow persistent")
    expect(flow["level"] == "RED", "flow RED")

    api = by["pay/api.py"]
    expect(api["churn"] == 5, "api churn 5")
    expect(api["trend"] == "emerging", "api emerging")

    idx = by["search/legacy_index.py"]
    expect(idx["churn"] == 5, "idx churn 5")
    expect(idx["trend"] == "cooling", "idx cooling")

    refund = by["pay/refund.py"]
    expect(refund["churn"] == 4, "refund churn 4 (rename chain kept it)")
    expect("pay/rename_me.py" not in by, "old path gone")

    expect(by["util.py"]["trend"] == "stable", "util stable")
    expect(by["migrations/001_init.sql"]["trend"] == "-", "oneshot no trend")
    expect("package-lock.json" not in by, "lockfile excluded")
    expect("logo.png" not in by, "binary skipped")
    expect(data["summary"]["red"] == 1, "exactly one RED")

    print("OK: demo repo rebuilt, samples written, all numbers asserted.")
    print("  examples/sample-report.txt")
    print("  examples/sample-trend.txt")


if __name__ == "__main__":
    main()
