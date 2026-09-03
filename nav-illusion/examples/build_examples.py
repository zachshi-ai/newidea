#!/usr/bin/env python3
"""Render the demo reports from the demo ledgers.

The examples are the dogfood: every report is rendered by the delivered CLI
walking the exact same code path a user would run, with --as-of pinned.
`--check` re-renders and fails on any byte drift.

Note: the demo ledger IS the cautionary tale — the report gate intentionally
ends BLEEDING (exit 4). The exit code is part of the demo, so `report` is
recorded with its exit code while `--check` compares stdout bytes only.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLI = ROOT / "nav_illusion.py"

AS_OF = "2026-06-30"

REPORTS = [
    ("sample-report.txt", ["report", "--as-of", AS_OF], True),
    ("sample-flows.txt", ["flows", "--as-of", AS_OF], False),
    ("sample-simulate.txt", ["simulate", "--as-of", AS_OF], False),
    ("sample-doctor.txt", ["doctor", "--as-of", AS_OF], False),
]


def render(args):
    return subprocess.run(
        [sys.executable, str(CLI)] + args
        + [str(HERE / "flows.csv"), str(HERE / "navs.csv")],
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
