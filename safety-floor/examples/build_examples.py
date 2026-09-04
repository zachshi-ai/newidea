#!/usr/bin/env python3
"""Render the demo reports from the demo ledgers.

The examples are the dogfood: every report is rendered by the delivered CLI
walking the exact same code path a user would run, with --expense pinned.
`--check` re-renders and fails on any byte drift. The demo report ends
EXPOSED (exit 4) by design — the exit code is part of the demo.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLI = ROOT / "safety_floor.py"

EXPENSE = "200000"

REPORTS = [
    ("sample-report.txt", ["report", "--expense", EXPENSE], True),
    ("sample-gaps.txt", ["gaps", "--expense", EXPENSE], False),
    ("sample-premium.txt", ["premium"], False),
]


def render(args):
    return subprocess.run(
        [sys.executable, str(CLI)] + args
        + [str(HERE / "family.csv"), str(HERE / "policies.csv")],
        capture_output=True, text=True, check=False,
    )


def main():
    check = "--check" in sys.argv
    failures = 0
    for name, args, gate in REPORTS:
        result = render(args)
        text = result.stdout
        target = HERE / name
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                print("%s DRIFT" % name)
                failures += 1
            else:
                print("%s in sync" % name)
        else:
            target.write_text(text, encoding="utf-8")
            note = " [gate exit %d — intended demo verdict]" % result.returncode if gate else ""
            print("%s written (exit %d)%s" % (name, result.returncode, note))
    if failures:
        print("examples out of sync — run: python3 examples/build_examples.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
