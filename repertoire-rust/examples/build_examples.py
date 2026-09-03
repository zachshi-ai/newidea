#!/usr/bin/env python3
"""Deterministically rebuild repertoire-rust's example artifacts.

Generates examples/gig-ledger.jsonl — Lena Torres's guitar practice
ledger: eight months of sessions across nine pieces on the road to an
open-mic slot on 2026-09-12. One piece is performed muscle (Blackbird),
one is fresh tonight and gone by the gig (Firefly), one collapses twice
and never sticks (Romance), one sits archived, and the keep-alive bill
for the whole book runs at three times what Lena has been paying.

Then re-renders the four sample reports through the same code path the
CLI uses, with --as-of pinned to 2026-08-31. Run with --check to verify
the five files byte-match a fresh rebuild (CI uses this). Fixed dates,
no "today", no randomness.
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import repertoire_rust as rr  # noqa: E402

LEDGER = HERE / "gig-ledger.jsonl"
SAMPLE_FRESH = HERE / "sample-fresh.txt"
SAMPLE_GIG = HERE / "sample-gig.txt"
SAMPLE_PLAN = HERE / "sample-plan.txt"
SAMPLE_SHOW = HERE / "sample-show.txt"

AS_OF = date(2026, 8, 31)
GIG_DATE = date(2026, 9, 12)
PLAN_MINUTES = 45

# piece, date, kind, quality, minutes
SESSIONS = [
    # Blackbird — performed muscle: months of steady maintenance and two
    # real gigs built a half-life the ledger can trust.
    ("Blackbird", "2026-03-03", "learn", 3, 35),
    ("Blackbird", "2026-03-17", "learn", 4, 30),
    ("Blackbird", "2026-04-01", "maintain", 4, 25),
    ("Blackbird", "2026-04-15", "maintain", 5, 25),
    ("Blackbird", "2026-05-01", "maintain", 5, 20),
    ("Blackbird", "2026-05-16", "perform", 5, 15),
    ("Blackbird", "2026-06-02", "maintain", 5, 20),
    ("Blackbird", "2026-06-17", "maintain", 4, 20),
    ("Blackbird", "2026-07-03", "perform", 5, 15),
    ("Blackbird", "2026-07-18", "maintain", 5, 15),
    ("Blackbird", "2026-08-03", "maintain", 4, 15),
    ("Blackbird", "2026-08-24", "maintain", 5, 10),
    # Wish You Were Here — the second soldier: steady, durable, ready.
    ("Wish You Were Here", "2026-04-07", "learn", 4, 30),
    ("Wish You Were Here", "2026-04-21", "maintain", 4, 25),
    ("Wish You Were Here", "2026-05-05", "maintain", 5, 25),
    ("Wish You Were Here", "2026-05-26", "maintain", 5, 20),
    ("Wish You Were Here", "2026-06-16", "maintain", 4, 20),
    ("Wish You Were Here", "2026-07-07", "maintain", 5, 20),
    ("Wish You Were Here", "2026-07-28", "maintain", 4, 15),
    ("Wish You Were Here", "2026-08-18", "maintain", 4, 15),
    # More Than Words — touched monthly; the ledger is losing patience.
    ("More Than Words", "2026-05-06", "learn", 4, 30),
    ("More Than Words", "2026-05-20", "maintain", 4, 25),
    ("More Than Words", "2026-06-10", "maintain", 3, 20),
    ("More Than Words", "2026-07-08", "maintain", 4, 20),
    ("More Than Words", "2026-08-12", "maintain", 3, 15),
    # Fast Car — one collapse on August 4th: the ledger said 61%, the
    # hands said no. Lena wants it at the open mic. The ledger disagrees.
    ("Fast Car", "2026-04-14", "learn", 4, 35),
    ("Fast Car", "2026-04-28", "learn", 5, 30),
    ("Fast Car", "2026-05-19", "maintain", 5, 25),
    ("Fast Car", "2026-06-09", "maintain", 4, 25),
    ("Fast Car", "2026-06-30", "maintain", 5, 20),
    ("Fast Car", "2026-08-04", "maintain", 2, 20),
    ("Fast Car", "2026-08-15", "maintain", 3, 15),
    # Romance — never stuck: two collapses, two rebuilds, and the
    # durability needle never stays up. Maintenance is theater here.
    ("Romance", "2026-01-10", "learn", 4, 30),
    ("Romance", "2026-01-24", "learn", 5, 25),
    ("Romance", "2026-02-08", "maintain", 5, 20),
    ("Romance", "2026-02-22", "maintain", 4, 20),
    ("Romance", "2026-03-08", "maintain", 5, 20),
    ("Romance", "2026-03-22", "maintain", 4, 20),
    ("Romance", "2026-04-26", "maintain", 2, 20),
    ("Romance", "2026-05-17", "learn", 5, 30),
    ("Romance", "2026-06-07", "maintain", 5, 20),
    ("Romance", "2026-06-28", "maintain", 4, 20),
    ("Romance", "2026-08-02", "maintain", 1, 15),
    # Classical Gas — learned in spring, abandoned since May 2nd.
    ("Classical Gas", "2026-03-09", "learn", 3, 40),
    ("Classical Gas", "2026-03-30", "learn", 4, 35),
    ("Classical Gas", "2026-04-20", "learn", 4, 30),
    ("Classical Gas", "2026-05-02", "maintain", 3, 25),
    # Hotel California Solo — attempted in June, never left learn phase.
    ("Hotel California Solo", "2026-06-14", "learn", 2, 30),
    ("Hotel California Solo", "2026-06-28", "learn", 3, 25),
    # Firefly — Lena's own song, fresh tonight (81%), dead by the gig.
    ("Firefly", "2026-08-08", "learn", 3, 30),
    ("Firefly", "2026-08-12", "learn", 2, 25),
    ("Firefly", "2026-08-19", "learn", 4, 30),
    ("Firefly", "2026-08-23", "learn", 3, 25),
    ("Firefly", "2026-08-28", "learn", 5, 30),
    # Landslide — untouched since November; out of the repertoire's
    # operating theater and into the archive.
    ("Landslide", "2025-09-14", "learn", 4, 30),
    ("Landslide", "2025-10-05", "maintain", 4, 25),
    ("Landslide", "2025-11-02", "maintain", 3, 20),
    ("Landslide", "2025-11-30", "maintain", 4, 20),
]

ARGS = SimpleNamespace(as_of=AS_OF, line=70, rebuild_line=40, format="text")


def ledger_text():
    lines = []
    for piece, d, kind, quality, minutes in SESSIONS:
        lines.append(json.dumps(
            {"piece": piece, "date": d, "kind": kind, "quality": quality,
             "minutes": minutes}, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def rebuild_reports():
    """Re-render the four sample reports from the ledger on disk."""
    records = rr.read_ledger("gig-ledger.jsonl")
    states, future = rr.replay(records, AS_OF)
    assert future == 0, "demo ledger must not contain future sessions"

    rep = rr.build_report(states, future, records, AS_OF, 70, 40, True)
    fresh_text = rr.render_fresh_text(rep, ARGS) + "\n"

    gig = rr.build_gig(states, AS_OF, GIG_DATE, 70, 40)
    gate, _ = rr.gate_report(gig, 3, ["Blackbird", "Fast Car"])
    gig_text = rr.render_gig_text(gig, ARGS)
    gig_text += "\n\n  gate: %s\n" % gate

    plan = rr.build_plan(states, AS_OF, PLAN_MINUTES, 70, 40)
    plan_text = rr.render_plan_text(plan, ARGS) + "\n"

    st = rr.find_piece(states, "Romance")
    fallback = rr.global_cost(states)
    view = {"state": st, "view": rr.state_view(st, AS_OF, 70, 40, fallback)}
    show_text = rr.render_show_text(view, ARGS) + "\n"
    return fresh_text, gig_text, plan_text, show_text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed artifacts match a fresh rebuild")
    args = ap.parse_args()

    import os
    previous = os.getcwd()
    LEDGER.write_text(ledger_text(), encoding="utf-8")
    os.chdir(HERE)                      # ledger path in reports stays relative
    try:
        fresh, gig, plan, show = rebuild_reports()
    finally:
        os.chdir(previous)

    artifacts = ((LEDGER, ledger_text()), (SAMPLE_FRESH, fresh),
                 (SAMPLE_GIG, gig), (SAMPLE_PLAN, plan),
                 (SAMPLE_SHOW, show))
    if args.check:
        for path, content in artifacts:
            if path.read_text(encoding="utf-8") != content:
                print("MISMATCH: %s does not match a fresh rebuild"
                      % path.name, file=sys.stderr)
                return 1
        print("examples in sync")
        return 0

    for path, content in artifacts:
        path.write_text(content, encoding="utf-8")
    print("wrote %s, %s, %s, %s, %s" % tuple(p.name for p, _ in artifacts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
