#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the full-house example ledger and report snapshots.

The demo ledger is one team's 8 weeks of meetings (2026-07-06 to
2026-08-28, plus the September schedule already on the books): 88
meetings, a weekly all-hands rhythm of standups, a Monday series, a
Tuesday review + "quick sync" sandwich, a protected no-meeting
Wednesday that keeps getting punctured, two 32-person all-hands, and
a schedule ahead that already books the next 48-person-hour room.

All commands are pinned to --today 2026-08-31 so the past/scheduled
split — and therefore every snapshot — is byte-reproducible.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "full_house.py")
TODAY = "2026-08-31"

HEADER = "date\tstart\tduration_min\tattendees\tsubject\tkind\toutcome\n"

MONDAYS = ["2026-07-06", "2026-07-13", "2026-07-20", "2026-07-27",
           "2026-08-03", "2026-08-10", "2026-08-17", "2026-08-24"]


def build_ledger():
    rows = []

    def add(day, start, minutes, attendees, subject, kind, outcome=""):
        rows.append("\t".join([day, start, str(minutes), str(attendees),
                               subject, kind, outcome]))

    for i, monday in enumerate(MONDAYS):
        d0 = date.fromisoformat(monday)
        day = {k: (d0 + timedelta(days=k)).isoformat() for k in range(5)}
        add(day[0], "09:30", 15, 5, "站会", "sync", "none")
        add(day[0], "10:00", 60, 8, "周例会", "sync", "action")
        add(day[1], "09:30", 15, 5, "站会", "sync", "none")
        # the Tuesday review series: decisions recorded every other week only
        add(day[1], "14:00", 90, 6, "评审会", "review",
            "decision" if i % 2 == 0 else "none")
        # ... and the 10-minute gap that makes it a sandwich
        add(day[1], "15:40", 30, 4, "顺便对齐", "sync", "none")
        # Wednesday is the no-meeting day — when nothing punctures it
        add(day[3], "09:30", 15, 5, "站会", "sync", "none")
        add(day[3], "15:00", 60, 4, "需求对齐", "sync", "none")
        add(day[4], "09:30", 15, 5, "站会", "sync", "none")
        add(day[4], "16:30", 30, 3, "周复盘", "sync", "action")

    # specials that puncture the quiet Wednesday
    add("2026-07-15", "14:00", 120, 9, "故障复盘-0712", "review", "decision")
    add("2026-07-22", "10:00", 60, 3, "面试-后端", "interview", "decision")
    add("2026-08-05", "10:00", 60, 3, "面试-前端", "interview", "decision")
    # Monday all-hands: 32 people, 90 minutes, no recorded outcome
    add("2026-07-20", "16:00", 90, 32, "全员会", "all-hands", "none")
    add("2026-08-17", "16:00", 90, 32, "全员会", "all-hands", "none")
    # a Thursday with a true back-to-back chain into the standing alignment
    add("2026-08-06", "11:00", 60, 5, "客户汇报", "review", "decision")
    add("2026-08-13", "14:30", 30, 4, "临时拉齐-数据口径", "sync", "none")
    add("2026-08-27", "15:00", 60, 6, "复盘-项目M", "review", "action")

    # already on the books for September (scheduled; gate audits these)
    add("2026-09-02", "09:30", 15, 5, "站会", "sync", "none")
    add("2026-09-07", "10:00", 60, 8, "周例会", "sync", "action")
    add("2026-09-08", "14:00", 90, 6, "评审会", "review", "none")
    add("2026-09-10", "15:00", 60, 4, "需求对齐", "sync", "none")
    add("2026-09-14", "16:00", 90, 32, "全员会", "all-hands", "none")

    rows.sort(key=lambda r: (r.split("\t")[0], r.split("\t")[1]))
    return HEADER + "\n".join(rows) + "\n"


SNAPSHOTS = [
    (["bill", "meetings.tsv", "--salary", "26000", "--hours", "173"], "sample-bill.txt"),
    (["top", "meetings.tsv", "--salary", "26000", "--hours", "173", "-n", "5"], "sample-top.txt"),
    (["recurring", "meetings.tsv", "--salary", "26000", "--hours", "173"], "sample-recurring.txt"),
    (["density", "meetings.tsv"], "sample-density.txt"),
    (["outcome", "meetings.tsv", "--salary", "26000", "--hours", "173"], "sample-outcome.txt"),
    (["simulate", "meetings.tsv", "cancel", "--match", "周例会",
      "--salary", "26000", "--hours", "173"], "sample-simulate.txt"),
    (["gate", "meetings.tsv", "--salary", "26000", "--hours", "173"], "sample-gate.txt"),
    (["validate", "meetings.tsv"], "sample-validate.txt"),
]


def resolve(arg):
    """File-name args refer to files in HERE; resolve them absolutely so the
    command works from any working directory (CI runs from the repo root)."""
    path = os.path.join(HERE, arg)
    return path if os.path.exists(path) else arg


def main():
    check = "--check" in sys.argv
    ledger_path = os.path.join(HERE, "meetings.tsv")
    ledger_text = build_ledger()

    if check:
        with open(ledger_path, "r", encoding="utf-8") as fh:
            if fh.read() != ledger_text:
                print("MISMATCH: %s differs from build_examples.py" % ledger_path)
                return 1
    else:
        with open(ledger_path, "w", encoding="utf-8") as fh:
            fh.write(ledger_text)

    status = 0
    for args, name in SNAPSHOTS:
        path = os.path.join(HERE, name)
        proc = subprocess.run([sys.executable, CLI, "--today", TODAY]
                              + [resolve(a) for a in args],
                              capture_output=True, text=True)
        out = proc.stdout
        if proc.returncode not in (0, 4):
            print("CLI %s failed: %s" % (args, proc.stderr))
            return 1
        if check:
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() != out:
                    print("MISMATCH: %s is stale (regenerate snapshots)" % name)
                    status = 1
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(out)
            print("wrote %s (exit %d)" % (name, proc.returncode))
    return status


if __name__ == "__main__":
    sys.exit(main())
