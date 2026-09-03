#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild the contribution-gap example ledger and sample outputs, from zero.

One household, two people, eight weeks (2026-07-06 .. 2026-08-30),
100 chore entries + 2 claims, every row pinned. The story the data tells:

  * the total is fair — maya 53.3% / noor 46.7%, gini 0.067 (balanced)
  * the house is split into fiefdoms — maya owns the kitchen (dishes,
    cooking), noor owns the outside (groceries, trash, fixing)
  * both self-images overshoot — maya claims 70%, noor claims 60%,
    together 130% of one household (perception surplus +30)
  * the split is sliding — 28-day gini went 0.040 -> 0.107: noor's weeks
    got lighter, and the last dish/cooking sessions are all maya

Run:  python3 examples/build_examples.py
Regenerates ledger.jsonl, sample-report.txt and sample-report-window.txt
inside examples/. Deterministic: the ledger is fully pinned and the tool
prints no wall-clock dates, so outputs are byte-stable across machines.

Check: python3 examples/build_examples.py --check
Rebuilds into a temp dir and byte-compares against the committed files
(the mode CI runs). Exits 0 when everything matches.
"""

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "contribution_gap.py")

WEEK1_MONDAY = dt.date(2026, 7, 6)
WEEKS = 8

# Person per week (index 0 = week of 2026-07-06) for the rotating slots.
# Week 5 (index 4) is where the slide begins: noor hands his last cooking
# slot back and never picks up a new one.
COOKING_THU = ["maya", "noor", "maya", "noor", "maya", "maya", "maya", "maya"]
LAUNDRY_SAT = ["maya", "noor", "maya", "maya", "maya", "noor", "maya", "maya"]
CLEANING_WED = ["maya", "noor", "maya", "noor", "maya", "noor", "maya", "noor"]
CLEANING_SAT = ["maya", "maya", "noor", "noor", "maya", "noor", "maya", "maya"]
GROCERIES_SUN = ["noor", "noor", "noor", "noor", "noor", "noor", "maya", "noor"]
TRASH_FRI = ["noor", "maya", "noor", "noor", "noor", "maya", "noor", "noor"]
ERRANDS_SUN = ["noor", "noor", "maya", "noor", "noor", "maya", "noor", "noor"]
FIXING_WEEKS = [1, 3, 5, 7]

CLAIMS = [
    # the two self-images: together 130% of one household
    ("2026-08-24", "maya", 70),
    ("2026-08-25", "noor", 60),
]


def entries_for_week(week: int):
    """Yield (date, person, chore, minutes) for one pinned week."""
    monday = WEEK1_MONDAY + dt.timedelta(days=7 * week)
    day = lambda wd: (monday + dt.timedelta(days=wd)).isoformat()  # noqa: E731

    yield (day(0), "maya", "dishes", 20)      # dishes: maya owns the kitchen
    yield (day(2), "maya", "dishes", 20)
    yield (day(4), "maya" if week >= 4 else "noor", "dishes", 20)
    yield (day(1), "maya", "cooking", 40)
    yield (day(3), COOKING_THU[week], "cooking", 40)
    yield (day(5), LAUNDRY_SAT[week], "laundry", 50)
    yield (day(2), CLEANING_WED[week], "cleaning", 90)
    yield (day(5), CLEANING_SAT[week], "cleaning", 90)
    yield (day(6), GROCERIES_SUN[week], "groceries", 60)
    yield (day(1), "noor", "trash", 10)       # trash: noor owns the outside
    yield (day(4), TRASH_FRI[week], "trash", 10)
    yield (day(6), ERRANDS_SUN[week], "errands", 45)
    if week in FIXING_WEEKS:
        yield (day(6), "noor", "fixing", 60)


def build_rows():
    rows = []
    for week in range(WEEKS):
        for date, person, chore, minutes in sorted(entries_for_week(week)):
            rows.append({"kind": "chore", "date": date, "person": person,
                         "chore": chore, "minutes": minutes})
    for date, person, pct in CLAIMS:
        rows.append({"kind": "claim", "date": date, "person": person,
                     "pct": pct})
    return rows


def render(samples_dir: str):
    """Write ledger + both sample reports into samples_dir; return paths."""
    ledger = os.path.join(samples_dir, "ledger.jsonl")
    with open(ledger, "w", encoding="utf-8") as fh:
        for row in build_rows():
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = os.path.join(samples_dir, "sample-report.txt")
    window = os.path.join(samples_dir, "sample-report-window.txt")
    for path, extra in [(report, []), (window, ["--window", "28"])]:
        proc = subprocess.run(
            [sys.executable, TOOL, "report", "--file", ledger] + extra,
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit("report failed: %s" % proc.stderr)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(proc.stdout)
    return [ledger, report, window]


NAMES = ["ledger.jsonl", "sample-report.txt", "sample-report-window.txt"]


def main():
    if "--check" in sys.argv[1:]:
        tmp = tempfile.mkdtemp(prefix="contribution-gap-examples-")
        try:
            ok = True
            for name, built in zip(NAMES, render(tmp)):
                with open(built, "rb") as fh:
                    built_bytes = fh.read()
                committed = os.path.join(HERE, name)
                with open(committed, "rb") as fh:
                    live_bytes = fh.read()
                if built_bytes != live_bytes:
                    ok = False
                    print("OUT OF SYNC: examples/%s "
                          "(run build_examples.py to regenerate)" % name)
            if ok:
                print("examples in sync: ledger + 2 sample reports")
            return 0 if ok else 1
        finally:
            shutil.rmtree(tmp)
    for path in render(HERE):
        print("wrote %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
