#!/usr/bin/env python3
"""Deterministically rebuild job-funnel's example artifacts.

Generates examples/applications.csv — Li Mo's 11-week job hunt after a
layoff: 69 applications across four channels (board, referral, recruiter,
careers), 55 decided, 12 pending (7 of them past the silence line),
2 withdrawn, 1 offer — then re-renders the four sample reports through
the same code path the CLI uses, with --as-of pinned to 2025-12-01.

Run with --check to verify the five files byte-match a fresh rebuild (CI
uses this). Fixed dates, no "today", no randomness.
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import job_funnel as jf  # noqa: E402

LEDGER = HERE / "applications.csv"
SAMPLE_FUNNEL = HERE / "sample-funnel.txt"
SAMPLE_CHANNELS = HERE / "sample-channels.txt"
SAMPLE_AGING = HERE / "sample-aging.txt"
SAMPLE_SHOW = HERE / "sample-show.txt"

AS_OF = date(2025, 12, 1)

# applied, company, role, channel, outcome, replied
LEDGER_ROWS = [
    # --- referral: small, slow, and the only proven channel ---
    ("2025-09-19", "Meld Bank", "Backend Engineer", "referral",
     "rejected", "2025-10-01"),
    ("2025-09-12", "Cloudveil", "Backend Engineer", "referral",
     "rejected", ""),
    ("2025-10-09", "Portmill Logistics", "Backend Engineer", "referral",
     "response", "2025-10-15"),
    ("2025-10-20", "Cratewise", "Backend Engineer", "referral",
     "response", "2025-10-24"),
    ("2025-10-20", "Corvid Systems", "Backend Engineer", "referral",
     "interview", "2025-10-23"),
    ("2025-10-27", "Baize AI", "Platform Engineer", "referral",
     "interview", "2025-10-30"),
    ("2025-10-27", "Thousand Sail", "Data Engineer", "referral",
     "rejected", "2025-11-13"),
    ("2025-11-03", "Northstar Nav", "Data Platform Engineer", "referral",
     "rejected", "2025-11-05"),
    ("2025-11-03", "Hexagram Tech", "Senior Backend Engineer", "referral",
     "offer", "2025-11-06"),
    ("2025-11-05", "Umbral Insurance", "Backend Engineer", "referral",
     "rejected", "2025-11-06"),
    ("2025-10-31", "Hexagram Tech", "Staff Engineer", "referral",
     "withdrawn", ""),
    ("2025-11-24", "Forge Works", "Embedded Backend Engineer", "referral",
     "pending", ""),
    # --- recruiter: three calls, thin as it gets ---
    ("2025-09-22", "Northwind", "Platform Engineer", "recruiter",
     "interview", "2025-09-26"),
    ("2025-10-06", "Atlas Retail", "Senior Backend Engineer", "recruiter",
     "response", "2025-10-16"),
    ("2025-11-17", "Halcyon Health", "Backend Engineer", "recruiter",
     "pending", ""),
    # --- board: two thirds of the effort, the least proven channel ---
    ("2025-09-29", "BlueCrane", "Backend Engineer", "board",
     "interview", "2025-10-04"),
    ("2025-10-13", "Cedarstone Data", "Senior Backend Engineer", "board",
     "interview", "2025-10-20"),
    ("2025-09-10", "Quadranet", "Backend Engineer", "board",
     "response", "2025-09-18"),
    ("2025-10-08", "FarGaze Tech", "Backend Engineer", "board",
     "response", "2025-10-22"),
    ("2025-10-22", "Changfeng Info", "Backend Engineer", "board",
     "response", "2025-10-28"),
    ("2025-11-12", "Meridian", "Platform Engineer", "board",
     "response", "2025-11-14"),
    ("2025-09-12", "Quartzline", "Backend Engineer", "board",
     "rejected", "2025-10-05"),
    ("2025-09-24", "Fleetwise", "Backend Engineer", "board",
     "rejected", "2025-10-13"),
    ("2025-10-15", "Datong Securities", "Quant Developer", "board",
     "rejected", "2025-10-24"),
    ("2025-10-30", "Tangerine Interactive", "Backend Engineer", "board",
     "rejected", "2025-11-06"),
    ("2025-09-08", "Deepgaze", "Backend Engineer", "board", "rejected", ""),
    ("2025-09-09", "Ninefold Cloud", "Backend Engineer", "board", "rejected", ""),
    ("2025-09-11", "Azure Tide", "Backend Engineer", "board", "rejected", ""),
    ("2025-09-15", "Starloom", "Senior Backend Engineer", "board", "rejected", ""),
    ("2025-09-16", "Flywheel Soft", "Backend Engineer", "board", "rejected", ""),
    ("2025-09-17", "Bedrock Systems", "Backend Engineer", "board", "rejected", ""),
    ("2025-09-18", "Greenwing Net", "Platform Engineer", "board", "rejected", ""),
    ("2025-09-20", "Playlight Games", "Backend Engineer", "board", "rejected", ""),
    ("2025-09-21", "Hoshi Tech", "Backend Engineer", "board", "rejected", ""),
    ("2025-09-23", "Chengtian Data", "Data Engineer", "board", "rejected", ""),
    ("2025-09-25", "Lucid Cloud", "Backend Engineer", "board", "rejected", ""),
    ("2025-09-28", "Curvature Compute", "Backend Engineer", "board", "rejected", ""),
    ("2025-09-30", "Bamboo Net", "Backend Engineer", "board", "rejected", ""),
    ("2025-10-06", "Lantern Works", "Backend Engineer", "board", "rejected", ""),
    ("2025-10-07", "Iron Peak", "Site Reliability Engineer", "board", "rejected", ""),
    ("2025-10-09", "Sable Analytics", "Backend Engineer", "board", "rejected", ""),
    ("2025-10-10", "Kite & Anchor", "Backend Engineer", "board", "rejected", ""),
    ("2025-10-14", "Redwood Ops", "Platform Engineer", "board", "rejected", ""),
    ("2025-10-16", "Nimbus Nine", "Backend Engineer", "board", "rejected", ""),
    ("2025-10-18", "Parallel Ports", "Backend Engineer", "board", "rejected", ""),
    ("2025-10-21", "Quanta Bloom", "Data Engineer", "board", "rejected", ""),
    ("2025-10-24", "Riverbend Systems", "Backend Engineer", "board", "rejected", ""),
    ("2025-10-29", "Sableframe", "Senior Backend Engineer", "board", "rejected", ""),
    ("2025-11-01", "Tidewell", "Backend Engineer", "board", "rejected", ""),
    ("2025-11-04", "Umber Labs", "Backend Engineer", "board", "rejected", ""),
    ("2025-11-08", "Vantile", "Backend Engineer", "board", "rejected", ""),
    ("2025-11-11", "Wrenfield", "Backend Engineer", "board", "rejected", ""),
    ("2025-11-15", "Xenon Forge", "Backend Engineer", "board", "rejected", ""),
    ("2025-10-21", "Solango", "Backend Engineer", "board", "pending", ""),
    ("2025-10-28", "Clearharbor", "Senior Backend Engineer", "board",
     "pending", ""),
    ("2025-11-03", "Gale Studio", "Backend Engineer", "board", "pending", ""),
    ("2025-11-05", "Yearbase", "Backend Engineer", "board", "pending", ""),
    ("2025-11-13", "Slowbull Finance", "Risk Data Engineer", "board",
     "pending", ""),
    ("2025-11-21", "Forager Community", "Backend Engineer", "board",
     "pending", ""),
    ("2025-11-26", "Stargaze Observatory", "Backend Engineer", "board",
     "pending", ""),
    # --- careers pages: the same door, knocked on quietly ---
    ("2025-09-16", "Auroracloud", "Backend Engineer", "careers",
     "rejected", ""),
    ("2025-09-30", "Auroracloud", "Senior Backend Engineer", "careers",
     "rejected", ""),
    ("2025-10-16", "Obsidian Energy", "Backend Engineer", "careers",
     "rejected", ""),
    ("2025-10-25", "Auroracloud", "Platform Engineer", "careers",
     "rejected", ""),
    ("2025-11-06", "Auroracloud", "Backend Engineer", "careers",
     "response", "2025-11-13"),
    ("2025-11-08", "Auroracloud", "Site Reliability Engineer", "careers",
     "pending", ""),
    ("2025-11-10", "Auroracloud", "Data Engineer", "careers",
     "pending", ""),
    ("2025-11-19", "Obsidian Energy", "Backend Engineer", "careers",
     "pending", ""),
    ("2025-11-28", "Auroracloud", "Senior Platform Engineer", "careers",
     "withdrawn", ""),
]

ARGS = SimpleNamespace(as_of=AS_OF, redact=False, format="text", top=15,
                       min_n=jf.DEFAULT_MIN_N, endpoint="response",
                       default_deadline=jf.DEFAULT_DEADLINE)


def ledger_text():
    lines = ["applied,company,role,channel,outcome,replied"]
    lines += [",".join(row) for row in LEDGER_ROWS]
    return "\n".join(lines) + "\n"


def rebuild_reports():
    """Re-render the four sample reports from the ledger on disk."""
    os.chdir(HERE)  # ledger path in reports stays relative
    ledger = jf.read_ledger("applications.csv")

    funnel = jf.funnel_report(ledger, ARGS.min_n)
    funnel["as_of"] = AS_OF
    funnel_text = jf.render_funnel_text(funnel, ledger, ARGS) + "\n"

    chans = jf.channels_report(ledger, ARGS.endpoint, ARGS.min_n)
    chans["as_of"] = AS_OF
    channels_text = jf.render_channels_text(chans, ARGS) + "\n"

    aging = jf.aging_report(ledger, AS_OF, ARGS.default_deadline)
    aging["as_of"] = AS_OF
    aging_text = jf.render_aging_text(aging, ARGS) + "\n"

    hits = jf.find_rows(ledger, "Hexagram Tech Senior")
    assert len(hits) == 1, "demo query 'Hexagram Tech Senior' must be unique"
    deadline = jf.silence_deadline(ledger, ARGS.default_deadline)[0]
    chan = next(c for c in chans["rows"]
                if c["channel"].lower() == hits[0]["channel"].lower())
    show_text = jf.render_show_text(hits[0], chan, AS_OF, deadline, ARGS) + "\n"
    return funnel_text, channels_text, aging_text, show_text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed artifacts match a fresh rebuild")
    args = ap.parse_args()

    previous = os.getcwd()
    LEDGER.write_text(ledger_text(), encoding="utf-8")
    try:
        funnel, channels, aging, show = rebuild_reports()
    finally:
        os.chdir(previous)

    artifacts = ((LEDGER, ledger_text()),
                 (SAMPLE_FUNNEL, funnel), (SAMPLE_CHANNELS, channels),
                 (SAMPLE_AGING, aging), (SAMPLE_SHOW, show))
    if args.check:
        for path, content in artifacts:
            if path.read_text(encoding="utf-8") != content:
                print("MISMATCH: %s does not match a fresh rebuild" % path.name,
                      file=sys.stderr)
                return 1
        print("examples in sync")
        return 0

    for path, content in artifacts:
        path.write_text(content, encoding="utf-8")
    print("wrote %s and 4 sample reports" % LEDGER.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
