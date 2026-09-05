#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate (or byte-verify) the scope-creep example snapshots.

Run from the repository root:
    python3 scope-creep/examples/build_examples.py           # regenerate
    python3 scope-creep/examples/build_examples.py --check   # CI gate

The demo ledger is a red-lamp story on purpose (AMBUSH + LOWBALL +
REDO on the settlement table), so gate exits are expected output, not
build failures: every snapshot records the exit code next to stdout.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "snapshots")
CLI = os.path.join(HERE, "..", "scope_creep.py")

RUNS = [
    (["report"], "report_final.txt"),
    (["report", "--as-of", "2025-12-01"], "report_inprogress.txt"),
    (["census"], "census.txt"),
    (["court"], "court.txt"),
    (["compare", "--quote2", "quote2.tsv"], "compare.txt"),
    (["validate"], "validate.txt"),
]


def one(args):
    cmd = [sys.executable, CLI, "--quote", os.path.join(HERE, "quote.tsv"),
           "--changes", os.path.join(HERE, "changes.tsv"),
           "--meta", os.path.join(HERE, "meta.tsv")] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return "exit code: %d\n\n%s%s" % (r.returncode, r.stdout, r.stderr)


def main():
    check = "--check" in sys.argv
    os.makedirs(SNAP, exist_ok=True)
    bad = []
    for args, name in RUNS:
        want_path = os.path.join(SNAP, name)
        text = one(args)
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
