#!/usr/bin/env python3
"""Deterministically rebuild drift-apart's example artifacts.

Writes examples/roster.csv + examples/interactions.csv — eight虚构 friends
covering every band (GONE / OVERDUE / FRESH / NEVER, one birthday door, one
lengthening slope, two unilateral balances) — then re-renders the three
sample reports through the same code path the CLI uses, with --as-of pinned
to 2025-12-01.

Run with --check to verify the committed artifacts byte-match a fresh
rebuild (CI uses this). Fixed dates, no "today", no randomness.
"""

import argparse
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import drift_apart as da  # noqa: E402

ROSTER_CSV = HERE / "roster.csv"
INTERACTIONS_CSV = HERE / "interactions.csv"
SAMPLE_LEDGER = HERE / "sample-ledger.txt"
SAMPLE_REPAIR = HERE / "sample-repair.txt"
SAMPLE_SHOW = HERE / "sample-show.txt"

AS_OF = date(2025, 12, 1)

ROSTER_ROWS = [
    # name, circle, birthday, cadence
    ("陈默", "inner", "05-12", ""),
    ("林小满", "close", "12-05", ""),
    ("苏黎", "close", "03-08", ""),
    ("王一帆", "active", "", ""),
    ("赵砚", "active", "", ""),
    ("老周", "outer", "07-19", ""),
    ("何朗", "outer", "", ""),
    ("唐薏", "close", "12-10", ""),
]

INTERACTION_ROWS = [
    # name, date, initiator — 陈默: gaps 30/28/60/55/130, all me
    ("陈默", "2024-01-10", "我"),
    ("陈默", "2024-02-09", "我"),
    ("陈默", "2024-03-08", "我"),
    ("陈默", "2024-05-07", "我"),
    ("陈默", "2024-07-01", "我"),
    ("陈默", "2024-11-08", "我"),
    # 林小满: one nudge, then 103d of silence; birthday door opens in 4d
    ("林小满", "2025-08-20", "我"),
    # 苏黎: they reached out last
    ("苏黎", "2025-08-01", "对方"),
    ("王一帆", "2025-11-10", "我"),
    ("赵砚", "2025-10-20", "对方"),
    # 老周: new-year-call rhythm (358d, 380d) that died after 2021
    ("老周", "2019-02-05", "我"),
    ("老周", "2020-01-29", "我"),
    ("老周", "2021-02-12", "我"),
    ("唐薏", "2025-09-30", "对方"),
    # 何朗: on the roster, never contacted
]

ARGS = SimpleNamespace(as_of=AS_OF, circle=None, top=None, redact=False,
                       format="text")


def roster_text():
    lines = ["姓名,圈层,生日"]
    lines += [",".join(row) for row in ROSTER_ROWS]
    return "\n".join(lines) + "\n"


def interactions_text():
    lines = ["姓名,日期,发起者"]
    lines += [",".join(row) for row in INTERACTION_ROWS]
    return "\n".join(lines) + "\n"


def rebuild_reports():
    """Re-render the three sample reports from the ledgers on disk."""
    report = da.load_ledger("roster.csv", "interactions.csv", AS_OF, {})
    ledger_text = da.render_ledger_text(report, ARGS) + "\n"

    ordered = da.repair_list(report, None)
    repair_text = da.render_repair_text(report, ARGS, ordered) + "\n"

    hits = [r for r in report["relations"] if r["name"] == "陈默"]
    assert len(hits) == 1, "demo query '陈默' must be unique"
    show_text = da.render_show_text(hits[0], report, ARGS) + "\n"
    return ledger_text, repair_text, show_text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed artifacts match a fresh rebuild")
    args = ap.parse_args()

    import os
    previous = os.getcwd()
    ROSTER_CSV.write_text(roster_text(), encoding="utf-8")
    INTERACTIONS_CSV.write_text(interactions_text(), encoding="utf-8")
    os.chdir(HERE)                      # ledger paths in reports stay relative
    try:
        ledger, repair, show = rebuild_reports()
    finally:
        os.chdir(previous)

    if args.check:
        for path, content in ((ROSTER_CSV, roster_text()),
                              (INTERACTIONS_CSV, interactions_text()),
                              (SAMPLE_LEDGER, ledger),
                              (SAMPLE_REPAIR, repair),
                              (SAMPLE_SHOW, show)):
            if path.read_text(encoding="utf-8") != content:
                print("MISMATCH: %s does not match a fresh rebuild" % path.name,
                      file=sys.stderr)
                return 1
        print("examples in sync")
        return 0

    SAMPLE_LEDGER.write_text(ledger, encoding="utf-8")
    SAMPLE_REPAIR.write_text(repair, encoding="utf-8")
    SAMPLE_SHOW.write_text(show, encoding="utf-8")
    print("wrote %s, %s, %s, %s, %s" % (
        ROSTER_CSV.name, INTERACTIONS_CSV.name, SAMPLE_LEDGER.name,
        SAMPLE_REPAIR.name, SAMPLE_SHOW.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
