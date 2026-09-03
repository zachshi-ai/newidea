#!/usr/bin/env python3
"""Render the demo reports from the demo ledgers.

The examples are the dogfood: every report is rendered by the delivered CLI
walking the exact same code path a user would run, with --as-of and --km-now
pinned. `--check` re-renders and fails on any byte drift.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLI = ROOT / "odometer_illusion.py"

AS_OF = "2025-12-01"
KM_NOW = "21400"

REPORTS = [
    ("sample-status.txt", ["status", "--as-of", AS_OF, "--km-now", KM_NOW]),
    ("sample-trip.txt", ["trip", "--as-of", AS_OF, "--km-now", KM_NOW,
                         "--km", "2600", "--days", "12"]),
    ("sample-cost.txt", ["cost", "--as-of", AS_OF, "--km-now", KM_NOW]),
]


def render(args):
    result = subprocess.run(
        [sys.executable, str(CLI)] + args
        + [str(HERE / "family-car.csv"), str(HERE / "service-log.csv")],
        capture_output=True, text=True, check=False,
    )
    return result


def main():
    check = "--check" in sys.argv
    failures = 0
    for name, args in REPORTS:
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
            print("%s written (exit %d)" % (name, result.returncode))
    if failures:
        print("examples out of sync — run: python3 examples/build_examples.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
