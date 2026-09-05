#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate (or byte-verify) the mute-levy example snapshots.

Run from the repository root:
    python3 mute-levy/examples/build_examples.py           # regenerate
    python3 mute-levy/examples/build_examples.py --check   # CI gate

The demo ledger is a red-lamp story on purpose (a job-hopper who owed
2,520 at reconciliation, and two unclaimed deductions worth 2,680 that
flip it into a 160 refund), so gate exits are expected output, not build
failures: every snapshot records the exit code next to stdout.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "snapshots")
CLI = os.path.join(HERE, "..", "mute_levy.py")

BASE = ["--payslips", os.path.join(HERE, "payslips.tsv"),
        "--claims", os.path.join(HERE, "claims.tsv")]

RUNS = [
    (BASE, ["report"], "report.txt"),
    (BASE, ["settle"], "settle.txt"),
    (BASE + ["--eligibles", os.path.join(HERE, "eligibles.tsv")], ["gap"], "gap.txt"),
    (BASE, ["bonus", "--amount", "36000"], "bonus.txt"),
    (BASE, ["validate"], "validate.txt"),
]


def one(global_args, args):
    cmd = [sys.executable, CLI] + global_args + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return "exit code: %d\n\n%s%s" % (r.returncode, r.stdout, r.stderr)


def main():
    check = "--check" in sys.argv
    os.makedirs(SNAP, exist_ok=True)
    bad = []
    for global_args, args, name in RUNS:
        want_path = os.path.join(SNAP, name)
        text = one(global_args, args)
        if check:
            with open(want_path, encoding="utf-8") as fh:
                have = fh.read()
            if have != text:
                bad.append(name)
                print("DRIFT: %s" % want_path)
        else:
            with open(want_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            print("wrote %s" % want_path)
    if check:
        if bad:
            print("snapshot drift in %d file(s); regenerate and commit"
                  % len(bad))
            return 1
        print("snapshots byte-identical (%d files)" % len(RUNS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
