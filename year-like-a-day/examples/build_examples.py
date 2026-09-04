#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the year-like-a-day example ledger and report snapshots.

The demo ledger is one person's 2026 so far (2026-01-01 to 2026-08-31,
pinned to --today 2026-08-31): 16 firsts. A lively January, a project
crunch that greys out February to April (the 62-day streak), a May Day
trip to Quanzhou and Dongshan that bursts the ledger open (8 firsts,
7 of them with A-Fang), a slow summer slide back into the routine, and
a 57-day current streak — the climate-greying gate (exit 4) is live on
this ledger, on purpose: the snapshot shows what a red line looks like.

All commands are pinned to --today 2026-08-31 so coverage, streaks and
verdicts — and therefore every snapshot — are byte-reproducible.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "year_like_a_day.py")
TODAY = "2026-08-31"

ROWS = [
    ("2026-01-01", "event",  "元旦第一次看海上日出", ""),
    ("2026-01-10", "place",  "第一次去市图书馆新馆", ""),
    ("2026-01-17", "person", "经老周介绍认识阿芳", "阿芳"),
    ("2026-01-24", "skill",  "第一次上陶艺课，拉了个歪杯子", ""),
    ("2026-01-31", "food",   "第一次吃酸汤牛肉", ""),
    ("2026-02-08", "person", "生日局认识阿芳的朋友小柯", "阿芳、小柯"),
    ("2026-04-12", "place",  "第一次去老周的新房子", "老周"),
    ("2026-05-01", "place",  "第一次到泉州（和阿芳）", "阿芳"),
    ("2026-05-02", "place",  "第一次看蟳埔簪花围", "阿芳"),
    ("2026-05-03", "food",   "第一次吃面线糊配油条", "阿芳"),
    ("2026-05-05", "event",  "第一次看高甲戏", "阿芳"),
    ("2026-05-07", "place",  "第一次到东山岛环岛", "阿芳"),
    ("2026-05-09", "food",   "第一次喝单丛鸭屎香", "阿芳"),
    ("2026-05-12", "skill",  "第一次浮潜", "阿芳"),
    ("2026-05-30", "skill",  "第一次自己补自行车胎", ""),
    ("2026-07-05", "event",  "第一次看露天话剧", "老周"),
]

REPORTS = [
    ("sample-report.txt",   ["report"]),
    ("sample-months.txt",   ["months"]),
    ("sample-streaks.txt",  ["streaks"]),
    ("sample-sources.txt",  ["sources"]),
    ("sample-simulate.txt", ["simulate"]),
    ("sample-today.txt",    ["today"]),
    ("sample-gate.txt",     ["gate"]),
    ("sample-validate.txt", ["validate"]),
]


def build_ledger():
    lines = ["date\tcategory\tnote\tpeople\n"]
    for day, cat, note, people in ROWS:
        lines.append("\t".join([day, cat, note, people]) + "\n")
    with open(os.path.join(HERE, "firsts.tsv"), "w", encoding="utf-8") as fh:
        fh.write("".join(lines))


def main():
    check = "--check" in sys.argv[1:]
    if not check:
        build_ledger()
    failed = False
    for name, cmd in REPORTS:
        argv = [sys.executable, CLI, "--today", TODAY] + cmd + \
               [os.path.join(HERE, "firsts.tsv")]
        proc = subprocess.run(argv, capture_output=True, text=True)
        expected_path = os.path.join(HERE, name)
        if check:
            with open(expected_path, "r", encoding="utf-8") as fh:
                expected = fh.read()
            if proc.stdout != expected:
                failed = True
                sys.stderr.write("snapshot drift: %s\n" % name)
        else:
            with open(expected_path, "w", encoding="utf-8") as fh:
                fh.write(proc.stdout)
            sys.stdout.write("wrote %s (exit %d)\n" % (name, proc.returncode))
    if check:
        if failed:
            sys.stderr.write("MISMATCH: run build_examples.py without --check to refresh\n")
            return 1
        sys.stdout.write("all %d snapshots byte-identical\n" % len(REPORTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
