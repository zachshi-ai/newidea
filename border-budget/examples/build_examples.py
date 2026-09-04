#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the border-budget example ledger and report snapshots.

The demo ledger is one traveller's 2026 in the Schengen area: six closed
stays that currently fill 83 of the 90 rolling days, plus one booked
autumn trip (Oct 2-15) that rides the window to 89/90 — one day of
margin. The `check` snapshot also audits the greedy version of that
autumn plan (43 days) and shows it going over by 14 with the latest
legal exit spelled out.

All commands are pinned to --today 2026-09-06 so every snapshot is
byte-reproducible.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "border_budget.py")
TODAY = "2026-09-06"

LEDGER = """\
entry\texit\tregion\tnote
2026-03-15\t2026-03-22\tschengen\tspring
2026-04-20\t2026-05-03\tschengen\tclients
2026-05-28\t2026-06-10\tschengen\tearly summer
2026-07-02\t2026-07-22\tschengen\tjuly long stay
2026-08-10\t2026-08-30\tschengen\taugust long stay
2026-09-01\t2026-09-05\tschengen\ttop-up
2026-10-02\t2026-10-15\tschengen\tbooked autumn
"""

SNAPSHOTS = [
    (["balance", "trips.tsv"], "sample-balance.txt"),
    (["check", "trips.tsv", "--entry", "2026-10-02", "--exit", "2026-10-15"], "sample-check-safe.txt"),
    (["check", "trips.tsv", "--entry", "2026-10-02", "--exit", "2026-11-13"], "sample-check-over.txt"),
    (["when", "trips.tsv", "--days", "30"], "sample-when.txt"),
    (["gate", "trips.tsv"], "sample-gate.txt"),
    (["history", "trips.tsv"], "sample-history.txt"),
    (["simulate", "trips.tsv", "cancel", "--match", "autumn"], "sample-simulate.txt"),
    (["validate", "trips.tsv"], "sample-validate.txt"),
]


def resolve(arg):
    """File-name args refer to files in HERE; resolve them absolutely so the
    command works from any working directory (CI runs from the repo root)."""
    path = os.path.join(HERE, arg)
    return path if os.path.exists(path) else arg


def main():
    check = "--check" in sys.argv
    ledger_path = os.path.join(HERE, "trips.tsv")

    if check:
        with open(ledger_path, "r", encoding="utf-8") as fh:
            if fh.read() != LEDGER:
                print("MISMATCH: %s differs from build_examples.py" % ledger_path)
                return 1
    else:
        with open(ledger_path, "w", encoding="utf-8") as fh:
            fh.write(LEDGER)

    status = 0
    for args, name in SNAPSHOTS:
        path = os.path.join(HERE, name)
        proc = subprocess.run([sys.executable, CLI, "--today", TODAY]
                              + [resolve(a) for a in args],
                              capture_output=True, text=True)
        out = proc.stdout
        if proc.returncode not in (0, 3, 4):
            print("CLI %s failed: %s" % (args, proc.stderr))
            return 1
        if check:
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() != out:
                    print("MISMATCH: %s is stale (regenerate snapshots)" % name)
                    status = 1
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(out)
            print("wrote %s (exit %d)" % (name, proc.returncode))
    return status


if __name__ == "__main__":
    sys.exit(main())
