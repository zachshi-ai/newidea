#!/usr/bin/env python3
"""Deterministically rebuild make-it's example artifacts.

Generates examples/commutes.csv — Chen Yu's six-month commute ledger
(2026-03-02 .. 2026-08-28, Mon/Wed/Fri office days): 55 trips on his
main metro line, 12 on the flashier bus backup, 4 untimed summer bike
rides. The bus wins the mean and the P50 but loses at P80 — the
ledger is built so the routes ranking flips with the quantile.

All six sample reports are re-rendered through the same code path the
CLI uses, with --as-of pinned to 2026-08-29 and --at pinned per report.
Run with --check to verify the files byte-match a fresh rebuild (CI
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

import make_it as mi  # noqa: E402

LEDGER = HERE / "commutes.csv"
SAMPLES = ("sample-stats.txt", "sample-now.txt", "sample-leave.txt",
           "sample-routes.txt", "sample-late.txt", "sample-simulate.txt")

AS_OF = date(2026, 8, 29)
SPLIT = mi.parse_clock("08:15", "peak-split")

# date, route, depart, arrive, target (empty target = untimed ride)
LEDGER_ROWS = [
    # --- metro-line2: the workhorse. Early departures run 36-45 min;
    #     departures from 08:15 inflate to a 44 min median, and every
    #     one of his four metro lateness events is a Friday.
    ("2026-03-02", "metro-line2", "07:58", "08:37", "09:00"),
    ("2026-03-04", "metro-line2", "08:15", "08:56", "09:00"),
    ("2026-03-06", "bus-73", "08:04", "08:34", "09:00"),
    ("2026-03-09", "metro-line2", "08:02", "08:42", "09:00"),
    ("2026-03-11", "metro-line2", "07:55", "08:33", "09:00"),
    ("2026-03-13", "metro-line2", "08:16", "08:57", "09:00"),
    ("2026-03-16", "metro-line2", "08:04", "08:45", "09:00"),
    ("2026-03-18", "metro-line2", "07:52", "08:29", "09:00"),
    ("2026-03-20", "metro-line2", "08:17", "08:58", "09:00"),
    ("2026-03-23", "metro-line2", "08:06", "08:48", "09:00"),
    ("2026-03-25", "metro-line2", "08:18", "08:59", "09:00"),
    ("2026-03-27", "metro-line2", "08:15", "08:57", "09:00"),
    ("2026-03-30", "bus-73", "08:12", "09:08", "09:00"),
    ("2026-04-01", "metro-line2", "07:56", "08:34", "09:00"),
    ("2026-04-03", "metro-line2", "08:15", "08:57", "09:00"),
    ("2026-04-13", "metro-line2", "08:01", "08:40", "09:00"),
    ("2026-04-15", "bus-73", "07:58", "08:30", "09:00"),
    ("2026-04-17", "metro-line2", "08:22", "09:08", "09:00"),
    ("2026-04-20", "metro-line2", "08:05", "08:47", "09:00"),
    ("2026-04-22", "metro-line2", "08:16", "08:58", "09:00"),
    ("2026-04-24", "bus-73", "08:16", "08:51", "09:00"),
    ("2026-04-27", "metro-line2", "07:57", "08:41", "09:00"),
    ("2026-04-29", "metro-line2", "07:54", "08:30", "09:00"),
    ("2026-05-04", "metro-line2", "08:03", "08:43", "09:00"),
    ("2026-05-06", "metro-line2", "08:17", "08:59", "09:00"),
    ("2026-05-08", "bus-73", "08:07", "09:07", "09:00"),
    ("2026-05-11", "metro-line2", "07:57", "08:35", "09:00"),
    ("2026-05-13", "metro-line2", "08:00", "08:39", "09:00"),
    ("2026-05-15", "metro-line2", "08:15", "08:58", "09:00"),
    ("2026-05-18", "metro-line2", "08:08", "08:49", "09:00"),
    ("2026-05-20", "bus-73", "08:20", "08:49", "09:00"),
    ("2026-05-22", "metro-line2", "08:24", "09:13", "09:00"),
    ("2026-05-25", "metro-line2", "07:59", "08:38", "09:00"),
    ("2026-05-27", "metro-line2", "08:15", "08:58", "09:00"),
    ("2026-05-29", "metro-line2", "08:15", "08:58", "09:00"),
    ("2026-06-01", "metro-line2", "08:02", "08:42", "09:00"),
    ("2026-06-03", "metro-line2", "08:16", "08:59", "09:00"),
    ("2026-06-05", "bus-73", "08:02", "08:43", "09:00"),
    ("2026-06-08", "metro-line2", "07:55", "08:32", "09:00"),
    ("2026-06-10", "metro-line2", "08:07", "08:49", "09:00"),
    ("2026-06-12", "bus-73", "08:14", "08:48", "09:00"),
    ("2026-06-15", "metro-line2", "07:53", "08:29", "09:00"),
    ("2026-06-17", "metro-line2", "08:04", "08:44", "09:00"),
    ("2026-06-19", "metro-line2", "08:21", "09:08", "09:00"),
    ("2026-06-26", "metro-line2", "08:15", "08:59", "09:00"),
    ("2026-06-29", "bus-73", "08:22", "09:12", "09:00"),
    ("2026-07-01", "metro-line2", "08:15", "08:59", "09:00"),
    ("2026-07-03", "metro-line2", "08:15", "08:59", "09:00"),
    ("2026-07-06", "metro-line2", "08:00", "08:39", "09:00"),
    ("2026-07-08", "bus-73", "08:06", "08:42", "09:00"),
    ("2026-07-10", "metro-line2", "08:16", "09:00", "09:00"),
    ("2026-07-13", "metro-line2", "08:05", "08:49", "09:00"),
    ("2026-07-15", "bike", "08:25", "08:52", ""),
    ("2026-07-17", "metro-line2", "08:16", "09:00", "09:00"),
    ("2026-07-20", "metro-line2", "07:58", "08:37", "09:00"),
    ("2026-07-22", "bike", "08:25", "08:49", ""),
    ("2026-07-24", "bus-73", "08:18", "09:02", "09:00"),
    ("2026-07-27", "metro-line2", "08:03", "08:44", "09:00"),
    ("2026-07-29", "metro-line2", "07:56", "08:34", "09:00"),
    ("2026-07-31", "metro-line2", "08:19", "09:07", "09:00"),
    ("2026-08-03", "metro-line2", "08:01", "08:41", "09:00"),
    ("2026-08-05", "bike", "08:25", "08:54", ""),
    ("2026-08-07", "metro-line2", "08:15", "09:00", "09:00"),
    ("2026-08-10", "metro-line2", "08:06", "08:48", "09:00"),
    ("2026-08-12", "bus-73", "08:22", "09:00", "09:00"),
    ("2026-08-17", "metro-line2", "08:05", "08:50", "09:00"),
    ("2026-08-19", "bike", "08:25", "08:56", ""),
    ("2026-08-21", "metro-line2", "08:15", "09:00", "09:00"),
    ("2026-08-24", "metro-line2", "07:54", "08:31", "09:00"),
    ("2026-08-26", "metro-line2", "08:15", "09:00", "09:00"),
    ("2026-08-28", "metro-line2", "08:15", "09:00", "09:00"),
]

ARGS = SimpleNamespace(as_of=AS_OF, format="text")


def ledger_text():
    lines = ["date,route,depart,arrive,target"]
    lines += [",".join(row) for row in LEDGER_ROWS]
    return "\n".join(lines) + "\n"


def rebuild_reports():
    """Re-render the six sample reports from the ledger on disk."""
    os.chdir(HERE)  # ledger path in reports stays relative
    rows = mi.read_ledger("commutes.csv")

    stats = mi.stats_report(rows, AS_OF, None, mi.DEFAULT_MIN_N, SPLIT)
    stats_text = mi.render_stats_text(stats, rows)

    now = mi.now_report(rows, AS_OF, "metro-line2",
                        mi.parse_clock("08:24", "clock"), mi.parse_clock("09:00", "clock"),
                        mi.DEFAULT_WANT, SPLIT)
    now_text = mi.render_now_text(now, rows)

    leave = mi.leave_report(rows, AS_OF, "metro-line2",
                            mi.parse_clock("09:00", "clock"), mi.DEFAULT_WANT,
                            mi.parse_clock("08:05", "clock"), SPLIT)
    leave_text = mi.render_leave_text(leave, rows)

    rt = mi.routes_report(rows, AS_OF, mi.DEFAULT_QUANTILE, mi.DEFAULT_MIN_N)
    routes_text = mi.render_routes_text(rt, rows)

    late = mi.late_report(rows, AS_OF)
    late_text = mi.render_late_text(late, rows)

    sim = mi.simulate_report(rows, AS_OF, 10, None)
    simulate_text = mi.render_simulate_text(sim, rows)

    return (stats_text, now_text, leave_text, routes_text, late_text,
            simulate_text)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed artifacts match a fresh rebuild")
    args = ap.parse_args()

    previous = os.getcwd()
    LEDGER.write_text(ledger_text(), encoding="utf-8")
    try:
        reports = rebuild_reports()
    finally:
        os.chdir(previous)

    artifacts = [(LEDGER, ledger_text())]
    artifacts += [(HERE / name, text)
                  for name, text in zip(SAMPLES, reports)]
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
    print("wrote %s and %d sample reports" % (LEDGER.name, len(SAMPLES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
