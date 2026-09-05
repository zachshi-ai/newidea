#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate (or byte-verify) the avalanche example ledger and snapshots.

Run from the repository root:
    python3 avalanche/examples/build_examples.py           # regenerate
    python3 avalanche/examples/build_examples.py --check   # CI gate

The demo ledger is a red-lamp story on purpose (OVERFLOW + AVALANCHE replay
+ MATH-DEAD freeze + KILL-LIST), so gate exits are expected output, not
build failures: every snapshot records the exit code next to stdout.

The story (Xiao Lin, 120 days of a postgraduate English deck):
  days   1-28  honey moon   -- 30 new cards/day, vacation capacity covers
                              everything; the trap is loaded 30 cards at a time
  days  29-120  term time   -- capacity drops to a constant 60/day
  days  49-75  exam month   -- capacity 12/day: he still opens the app every
                              day, 12 reviews are all he can pay; the queue
                              piles up and gets STALE
  days  76-120  recovery     -- back to 60/day, but stale reviews fail at a
                              much higher rate (the forgetting curve): the
                              recycles alone now outrun the pipe
  days  40-42  skipped      -- three days the app was not even opened
  day  20      paid ahead   -- enthusiasm: 12 future cards pulled early

He never freezes the pipeline and never runs the numbers: by day 120 the
backlog is four figures and freezing alone can no longer save the deck
(fresh inflow > capacity -- MATH-DEAD). The avalanche was schedulable in
the first week of term.
The generator is a deterministic interval-ladder simulation (no random
module): a pure-arithmetic hash decides lapses, hardness is fixed per card
(every 7th hard). Deterministic on any machine, any Python.
"""

import os
import subprocess
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "snapshots")
CLI = os.path.join(HERE, "..", "avalanche.py")

D0 = date(2025, 9, 1)
DAYS = 120
TIERS = [1, 3, 7, 14, 30, 60, 120]

NEW_PER_DAY = 30     # the pipeline never stops -- that IS the avalanche
CRACK_AT = 28        # t >= CRACK_AT  -> capacity 60/day
EXAM_AT = 48         # t >= EXAM_AT    -> capacity 12/day (the break)
RECOVER_AT = 75      # t >= RECOVER_AT -> capacity 60/day again
SKIP = {39, 40, 41}  # the drawer days: no app, no row
AHEAD_DAY = 19       # paid-ahead burst: +12 future cards pulled early
AHEAD_N = 12


def hash01(a, b):
    x = (a * 2654435761 + b * 40503 + 97) % 1000003
    return x / 1000003.0


def lapse_p(idx):
    if idx % 7 == 0:
        return 0.30
    if idx % 3 == 1:
        return 0.12
    return 0.05


def new_per_day(t):
    return NEW_PER_DAY


def capacity(t):
    if t < CRACK_AT:
        return 10 ** 9
    if t < EXAM_AT:
        return 60
    if t < RECOVER_AT:
        return 12
    return 60


class Card(object):
    __slots__ = ("cid", "idx", "due", "tier", "lapses")

    def __init__(self, idx, t):
        self.idx = idx
        self.cid = "w-%04d" % idx
        self.due = t + 1
        self.tier = 0
        self.lapses = 0

    def p_lapse(self):
        return lapse_p(self.idx)


def generate():
    cards = []
    rows = []
    for t in range(DAYS):
        if t in SKIP:
            continue
        due_cards = [c for c in cards if c.due <= t]
        due_cards.sort(key=lambda c: (c.due, c.idx))
        cap = capacity(t)
        n_done = min(len(due_cards), cap)
        future = []
        if t == AHEAD_DAY and cap > len(due_cards) + AHEAD_N:
            future = sorted((c for c in cards if c.due > t),
                            key=lambda c: (c.due, c.idx))[:AHEAD_N]
            n_done = len(due_cards) + len(future)
        again = 0
        reviewed = due_cards[:n_done] + future
        for c in reviewed:
            # the avalanche engine: an overdue review fails more often --
            # delay itself is what makes later reviews stick worse
            delay = max(0, t - c.due)
            p_eff = min(0.85, c.p_lapse() + 0.04 * delay)
            if hash01(c.idx, t) < p_eff:
                c.lapses += 1
                c.tier = 0
                c.due = t + TIERS[0]
                again += 1
            else:
                c.tier = min(c.tier + 1, len(TIERS) - 1)
                c.due = t + TIERS[c.tier]
        n_new = new_per_day(t)
        for j in range(n_new):
            cards.append(Card(len(cards) + 1, t))
        rows.append({
            "date": (D0 + timedelta(days=t)).isoformat(),
            "due": len(due_cards),
            "done": n_done,
            "again": again,
            "new": n_new,
        })
    leeches = {c.cid: c.lapses for c in cards if c.lapses >= 1}
    return rows, leeches


def tsv(rows):
    lines = ["date\tdue\tdone\tagain\tnew"]
    for r in rows:
        lines.append("%s\t%d\t%d\t%d\t%d" % (r["date"], r["due"], r["done"],
                                             r["again"], r["new"]))
    return "\n".join(lines) + "\n"


def leech_tsv(leeches):
    lines = ["card\tlapses"]
    for cid in sorted(leeches):
        lines.append("%s\t%d" % (cid, leeches[cid]))
    return "\n".join(lines) + "\n"


RUNS = [
    (["report"], "report.txt"),
    (["report", "--as-of", "2025-10-05"], "report_inprogress.txt"),
    (["add", "30"], "add.txt"),
    (["simulate"], "simulate.txt"),
    (["leeches", "--leeches", "leeches.tsv"], "leeches.txt"),
    (["validate", "--leeches", "leeches.tsv"], "validate.txt"),
]


def one(args):
    args = [os.path.join(HERE, a) if a == "leeches.tsv" else a for a in args]
    # subcommand first, then the ledger (first positional), then flags/args
    cmd = ([sys.executable, CLI, args[0], os.path.join(HERE, "reviews.tsv")]
           + args[1:])
    r = subprocess.run(cmd, capture_output=True, text=True)
    return "exit code: %d\n\n%s%s" % (r.returncode, r.stdout, r.stderr)


def main():
    check = "--check" in sys.argv
    os.makedirs(SNAP, exist_ok=True)
    rows, leeches = generate()
    reviews_text = tsv(rows)
    leeches_text = leech_tsv(leeches)
    reviews_path = os.path.join(HERE, "reviews.tsv")
    leeches_path = os.path.join(HERE, "leeches.tsv")
    bad = []

    def want(path, text):
        if check:
            with open(path, encoding="utf-8") as fh:
                have = fh.read()
            if have != text:
                bad.append(os.path.basename(path))
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    want(reviews_path, reviews_text)
    want(leeches_path, leeches_text)
    for args, name in RUNS:
        want(os.path.join(SNAP, name), one(args))

    if check:
        if bad:
            print("SNAPSHOT DRIFT in: %s" % ", ".join(bad))
            print("rerun build_examples.py without --check to regenerate")
            return 1
        print("all snapshots byte-identical")
        return 0
    print("regenerated: reviews.tsv, leeches.tsv and %d snapshots" % len(RUNS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
