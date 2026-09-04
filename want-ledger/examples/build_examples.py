#!/usr/bin/env python3
"""Render the demo reports from the demo ledger.

The examples are the dogfood: every report is rendered by the delivered CLI
walking the exact same code path a user would run, with --as-of / --today
pinned. `--check` re-renders and fails on any byte drift.

Note: two of the four snapshots intentionally end in a gate verdict —
`report` ends REGRET-HEAVY and `check --seeded 2026-09-01` ends STILL
COOLING (both exit 4). The exit code is part of the demo, so those two are
recorded with their exit code while `--check` compares stdout bytes only.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLI = ROOT / "want_ledger.py"

AS_OF = "2026-09-04"
TODAY = "2026-09-04"

REPORTS = [
    ("sample-report.txt", ["report", "--as-of", AS_OF], True),
    ("sample-doctor.txt", ["doctor"], False),
    ("sample-check-cooling.txt",
     ["check", "--item", "机械键盘", "--price", "899", "--tag", "数码",
      "--seeded", "2026-09-01", "--today", TODAY], True),
    ("sample-check-decide.txt",
     ["check", "--item", "机械键盘", "--price", "899", "--tag", "数码",
      "--seeded", "2026-08-10", "--today", TODAY], False),
]


def render(args):
    return subprocess.run(
        [sys.executable, str(CLI)] + args + [str(HERE / "grass.csv")],
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
