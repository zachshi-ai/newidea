#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the card-tax demo ledger and regenerate the example snapshots.

Usage:
    python3 examples/build_examples.py          # write ledger + snapshots
    python3 examples/build_examples.py --check  # verify snapshots byte-for-byte

The ledger is deliberately small and hand-checkable: three cards past
their honeymoon (a lapsed gym annual, a half-finished tutoring package, a
barbershop card still alive) plus a brand-new yoga card too young to
grade. All headline numbers are hand-computed in tests.
"""

import difflib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "card_tax.py")
DATA = os.path.join(HERE, "demo-data")


def _tsv(header, rows):
    out = ["\t".join(header)]
    for row in rows:
        out.append("\t".join("" if c is None else str(c) for c in row))
    return "\n".join(out) + "\n"


CARDS = _tsv(
    ["card", "name", "pay", "buy", "until", "units", "list", "target"],
    [
        # time card: units = 52 weeks x 1/week = 52
        ["yuedong", "悦动健身年卡", 3650, "2025-09-01", "2026-08-31",
         None, 90, 1],
        ["jingjing", "菁菁英语课包", 4000, "2025-11-15", None, 20, 260, None],
        ["xingge", "型格理发卡", 1000, "2026-01-10", None, 10, 78, None],
        ["fresh", "轻醒瑜伽次卡", 680, "2026-06-20", None, 10, 68, None],
    ])

_Y = [("2025-09-02", "练背"), ("2025-09-06", "腿日"),
      ("2025-09-09", "游泳"), ("2025-09-13", "练背"),
      ("2025-10-04", "力量"), ("2025-10-11", "有氧"),
      ("2025-10-18", "力量"), ("2025-11-08", "腿日"),
      ("2025-11-22", "游泳"), ("2025-12-06", "力量"),
      ("2026-02-10", "新年第一次")]
_J = [("2025-11-22", "试听后的第一节"), ("2025-11-29", None),
      ("2025-12-06", None), ("2025-12-13", None), ("2025-12-20", None),
      ("2026-01-10", None), ("2026-01-17", None), ("2026-03-07", "复课"),
      ("2026-03-28", None)]
_X = [("2026-01-25", "剪发"), ("2026-02-22", "剪发"),
      ("2026-03-22", "剪发"), ("2026-04-19", "剪发"),
      ("2026-05-17", "剪发"), ("2026-06-07", "剪发"),
      ("2026-06-30", "剪发")]

VISITS = _tsv(
    ["card", "date", "note"],
    [["yuedong", d, n] for d, n in _Y]
    + [["jingjing", d, n] for d, n in _J]
    + [["xingge", d, n] for d, n in _X]
    + [["fresh", "2026-06-21", "体验课"]])

SNAPSHOTS = [
    ("sample-report.txt", ["report", "@CARDS@", "@VISITS@"]),
    ("sample-report-expired.txt",
     ["report", "--as-of", "2026-09-30", "@CARDS@", "@VISITS@"]),
    ("sample-pace.txt", ["pace", "@CARDS@", "@VISITS@"]),
    ("sample-cost.txt", ["cost", "@CARDS@", "@VISITS@"]),
    ("sample-offer.txt",
     ["offer", "--pay", "3000", "--units", "50", "--list", "88",
      "--until", "2027-06-30", "@CARDS@", "@VISITS@"]),
    ("sample-simulate.txt",
     ["simulate", "--weekly", "3", "@CARDS@", "@VISITS@"]),
    ("sample-validate.txt", ["validate", "@CARDS@", "@VISITS@"]),
]


def main() -> int:
    check = "--check" in sys.argv[1:]
    os.makedirs(DATA, exist_ok=True)
    cards_path = os.path.join(DATA, "cards.tsv")
    visits_path = os.path.join(DATA, "visits.tsv")
    for path, text in ((cards_path, CARDS), (visits_path, VISITS)):
        if not check:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        elif not os.path.exists(path):
            print("missing demo ledger: %s" % path, file=sys.stderr)
            return 1

    failures = 0
    for fname, template in SNAPSHOTS:
        argv = [sys.executable, CLI]
        for part in template:
            if part == "@CARDS@":
                argv.append(cards_path)
            elif part == "@VISITS@":
                argv.append(visits_path)
            else:
                argv.append(part)
        proc = subprocess.run(argv, capture_output=True, text=True)
        out = proc.stdout
        if proc.returncode != 0:
            out += "\n[exit %d] %s" % (proc.returncode, proc.stderr)
        out_path = os.path.join(HERE, fname)
        if check:
            with open(out_path, encoding="utf-8") as fh:
                want = fh.read()
            if want != out:
                failures += 1
                print("DRIFT: %s" % fname, file=sys.stderr)
                for ln in list(difflib.unified_diff(
                        want.splitlines(), out.splitlines(),
                        "snapshot", "now", lineterm=""))[:40]:
                    print(ln, file=sys.stderr)
        else:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(out)
            print("wrote %s (exit %d)" % (fname, proc.returncode))
    if check:
        if failures:
            print("%d snapshot(s) drifted" % failures, file=sys.stderr)
            return 1
        print("all snapshots byte-identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
