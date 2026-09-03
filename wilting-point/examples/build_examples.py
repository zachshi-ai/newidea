#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-pin every wilting-point sample output from the committed ledgers.

Two shelves, two opposite verdicts (both "as of" their own last log date —
the clock is part of the ledger, never the wall):

  * che — ten plants watered "whenever it comes to mind": two plants past
    their wilting point (Fern by 7d, NervePlant by 0d), the orchid
    simultaneously over-loved and forgotten, the four-year jade one day
    from its line, and a species blacklist the log itself wrote.
  * tang — the control: five drought-tolerant plants on a Sunday routine.
    Every band OK, zero misses, zero mismatch — yet the rot lamp still
    flags the two 21-day plants: a uniform schedule taxes the tolerant end.

The four TSV files are hand-written on purpose (their comments are the
story); this script only re-runs the real CLI code paths over them and
pins the results:

    python3 examples/build_examples.py           # (re)write sample outputs
    python3 examples/build_examples.py --check   # byte-identical? (tests use this)
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # wilting-point/

sys.path.insert(0, ROOT)
import wilting_point as wp  # noqa: E402

# (sample file, argv, allowed exit codes)
PINS = [
    ("sample-report-che.txt", ["report", "che-ledger.tsv", "che-log.tsv"],
     (wp.EXIT_OK,)),
    ("sample-due-che.txt", ["due", "che-ledger.tsv", "che-log.tsv"],
     (wp.EXIT_OK,)),
    ("sample-simulate-che.txt",
     ["simulate", "che-ledger.tsv", "che-log.tsv", "trip", "7"],
     (wp.EXIT_OK,)),
    ("sample-advice-fern.txt",
     ["advice", "che-ledger.tsv", "che-log.tsv", "boston-fern"],
     (wp.EXIT_GATE,)),
    ("sample-advice-snake.txt",
     ["advice", "che-ledger.tsv", "che-log.tsv", "snake-plant"],
     (wp.EXIT_OK,)),
    ("sample-report-tang.txt", ["report", "tang-ledger.tsv", "tang-log.tsv"],
     (wp.EXIT_OK,)),
    ("sample-simulate-tang.txt",
     ["simulate", "tang-ledger.tsv", "tang-log.tsv", "trip", "7"],
     (wp.EXIT_OK,)),
]


def sample_outputs() -> dict:
    """The pinned outputs, produced by the real CLI code paths.
    Runs with CWD=examples so the pinned ledger names are bare file
    names — stable across machines."""
    out = {}
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        for name, argv, allowed in PINS:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = wp.main(argv)
            assert code in allowed, (name, code, allowed)
            out[name] = buf.getvalue()
    finally:
        os.chdir(cwd)
    return out


def write_all(files: dict) -> None:
    for name, content in files.items():
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(content)


def read_one(name: str) -> str:
    with open(os.path.join(HERE, name), "r", encoding="utf-8") as fh:
        return fh.read()


def check() -> int:
    bad = []
    fresh = sample_outputs()
    for name, content in sorted(fresh.items()):
        if read_one(name) != content:
            bad.append(name)
    if bad:
        print("out of sync: %s" % ", ".join(bad))
        print("run: python3 examples/build_examples.py")
        return 1
    print("all %d example files in sync" % len(fresh))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify committed files match a fresh rebuild")
    args = ap.parse_args()
    if args.check:
        return check()
    files = sample_outputs()
    write_all(files)
    print("wrote %d files:" % len(files))
    for name in sorted(files):
        print("  %s" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
