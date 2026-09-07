#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the flat-split example snapshots.

The demo is one shared flat, twelve months (2025-03 → 2026-03):
three roommates move in on the same day, buy a washing machine, a
router and a sofa together; the summer AC season pushes the common-area
meter loss past the tolerance line; three months in a row one person
pays every bill; in January 小马 leaves for another city — and the
usage charges he never paid leave with him, because allocations only
reach current residents. In February 阿花 moves in and the per-day
weights catch her mid-month. One ledger, four commands.

  python3 build_examples.py            # regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "flat_split.py")
ROOT = HERE
ASOF = "2026-03-10"

# (filename, argv, expected exit)
SNAPSHOTS = [
    ("sample-report.txt", ["report"], 4),
    ("sample-report-may.txt", ["report", "--as-of", "2025-05-31"], 0),
    ("sample-settle.txt", ["settle"], 0),
    ("sample-settle-feb.txt", ["settle", "--month", "2026-02"], 0),
    ("sample-assets.txt", ["assets"], 4),
    ("sample-assets-may.txt", ["assets", "--as-of", "2025-05-31"], 0),
    ("sample-validate.txt", ["validate"], 0),
]


def main():
    check = "--check" in sys.argv
    for fname, argv, want_code in SNAPSHOTS:
        run = [sys.executable, CLI] + argv + [ROOT]
        if "--as-of" not in argv:
            run += ["--as-of", ASOF]
        done = subprocess.run(run, capture_output=True, text=True)
        if done.returncode != want_code:
            sys.exit(f"{fname}: 期望 exit {want_code},"
                     f"实得 {done.returncode}\n{done.stdout}{done.stderr}")
        path = os.path.join(HERE, fname)
        if check:
            with open(path, encoding="utf-8") as fh:
                if fh.read() != done.stdout:
                    sys.exit(f"{fname} 与重新生成的输出不一致:"
                             f"请重新运行 build_examples.py")
            print(f"checked {fname} (exit {done.returncode})")
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(done.stdout)
            print(f"wrote {fname} (exit {done.returncode})")
    print("OK")


if __name__ == "__main__":
    main()
