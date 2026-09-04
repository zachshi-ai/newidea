#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the own-thermometer example ledger and report snapshots.

The demo ledger is one person's autumn-winter-spring season (2025-10-01 to
2026-04-12, 95 days of leaving the house and being honest about it). It
carries four load-bearing stories, all of which the CLI must rediscover
from raw rows:

  1. a personal comfort band noticeably colder than the 20°C "average
     person" anchor (deviation ≈ −3.5°C),
  2. a switch-season disaster in November and a mirror-image one in March,
     with cold misses outnumbering hot misses ~2:1 (the optimism tax of
     dressing light),
  3. a garment dead zone around 19–22°C — hoodie tops out at ~17.5,
     long-sleeve tee only starts winning at ~22 — that the wardrobe
     quietly punishes every year,
  4. a light-down jacket that has never once been right (orphan window),
     a "hoodie alone" combo that keeps losing (RISKY/DEAD), and a three-day
     cold streak in early March that trips the strike line (exit 4).

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "own_thermometer.py")

# date, tmin, tmax, cond, outfit, feel
HEADER = "date\ttmin\ttmax\tcond\toutfit\tfeel"

ROWS = """
2025-10-01	21	27	sunny	短袖T	0
2025-10-02	22	28	sunny	短袖T	0
2025-10-03	20	26	cloudy	短袖T	0
2025-10-07	21	26	sunny	衬衫	0
2025-10-08	21	26	cloudy	衬衫	0
2025-10-09	17	23	sunny	长袖T	+1
2025-10-10	18	24	sunny	风衣+长袖T	+1
2025-10-13	17	23	cloudy	风衣+长袖T	+1
2025-10-14	16	22	sunny	长袖T	+1
2025-10-15	15	21	cloudy	风衣+长袖T	0
2025-10-16	14	19	sunny	风衣+卫衣	0
2025-10-17	14	20	cloudy	风衣+卫衣	0
2025-10-20	14	21	rain	风衣+卫衣	0
2025-10-21	13	20	cloudy	风衣+卫衣	0
2025-10-22	13	21	sunny	卫衣	0
2025-10-23	12	19	cloudy	风衣+卫衣	0
2025-10-24	12	20	rain	风衣+卫衣	0
2025-10-27	11	18	cloudy	卫衣	0
2025-10-28	10	18	sunny	风衣+卫衣	0
2025-10-29	10	17	rain	卫衣	-1
2025-10-30	9	16	cloudy	风衣+卫衣	0
2025-10-31	9	17	sunny	卫衣	-1
2025-11-03	9	16	sunny	风衣+卫衣	0
2025-11-04	8	15	cloudy	风衣+卫衣	0
2025-11-05	4	10	rain	卫衣	-1
2025-11-06	6	12	cloudy	轻型羽绒+长袖T	-1
2025-11-07	7	13	sunny	毛衣+风衣	0
2025-11-10	6	13	sunny	毛衣+风衣	0
2025-11-11	6	12	cloudy	卫衣	-1
2025-11-12	6	13	rain	毛衣+风衣	0
2025-11-13	4	9	cloudy	轻型羽绒+长袖T	-1
2025-11-14	5	10	sunny	毛衣+风衣	0
2025-11-17	4	10	cloudy	轻型羽绒+长袖T	-1
2025-11-18	4	9	sunny	毛衣+大衣	0
2025-11-19	3	9	cloudy	毛衣+风衣	0
2025-11-20	2	8	rain	轻型羽绒+长袖T	-1
2025-11-21	2	7	cloudy	毛衣+大衣	0
2025-11-24	1	7	sunny	厚羽绒+毛衣	0
2025-11-25	0	6	cloudy	厚羽绒+毛衣	0
2025-11-26	1	7	rain	轻型羽绒+长袖T	-2
2025-11-27	0	5	sunny	毛衣+大衣	0
2025-11-28	-1	5	cloudy	厚羽绒+毛衣	0
2025-12-01	-1	5	cloudy	厚羽绒+毛衣	0
2025-12-02	-2	4	sunny	厚羽绒+毛衣	0
2025-12-03	-2	3	rain	厚羽绒+毛衣	0
2025-12-04	-3	3	sunny	厚羽绒+毛衣	0
2025-12-05	-3	2	cloudy	厚羽绒+毛衣	0
2025-12-08	-4	2	sunny	厚羽绒+毛衣	0
2025-12-09	-4	1	cloudy	厚羽绒+毛衣	0
2025-12-10	-3	2	rain	厚羽绒+毛衣	0
2025-12-11	-2	3	cloudy	大衣+毛衣	0
2025-12-12	-2	4	sunny	厚羽绒+毛衣	+1
2025-12-15	-1	4	cloudy	大衣+毛衣	0
2025-12-16	-1	5	sunny	大衣+毛衣	0
2025-12-17	0	5	rain	厚羽绒+毛衣	0
2025-12-18	0	6	cloudy	大衣+毛衣	0
2025-12-19	1	6	sunny	大衣+毛衣	0
2025-12-22	1	7	cloudy	厚羽绒+毛衣	0
2025-12-23	2	7	sunny	大衣+毛衣	0
2025-12-24	2	8	rain	厚羽绒+毛衣	0
2025-12-25	2	8	cloudy	厚羽绒+毛衣	0
2025-12-26	3	9	sunny	大衣+毛衣	0
2025-12-29	3	8	cloudy	大衣+毛衣	0
2025-12-30	3	9	sunny	大衣+毛衣	0
2025-12-31	4	9	rain	大衣+毛衣	0
2026-01-05	4	10	sunny	毛衣+风衣	0
2026-01-06	3	9	cloudy	厚羽绒+毛衣	0
2026-01-07	3	10	rain	毛衣+风衣	0
2026-01-08	4	10	sunny	毛衣+风衣	0
2026-01-09	5	11	cloudy	毛衣+风衣	0
2026-01-12	5	10	sunny	毛衣+风衣	0
2026-01-13	6	11	cloudy	毛衣+风衣	0
2026-01-14	6	12	rain	毛衣+风衣	0
2026-01-15	5	11	sunny	毛衣+风衣	0
2026-01-16	6	12	cloudy	毛衣+风衣	0
2026-01-19	7	13	sunny	毛衣+风衣	0
2026-01-20	7	12	cloudy	毛衣+风衣	0
2026-01-21	8	13	rain	毛衣+风衣	0
2026-01-22	8	14	sunny	毛衣+风衣	0
2026-01-23	9	14	cloudy	毛衣+风衣	0
2026-02-02	6	11	sunny	毛衣+风衣	0
2026-02-03	5	10	cloudy	毛衣+风衣	0
2026-02-04	4	9	rain	毛衣+风衣	-1
2026-02-05	4	10	sunny	毛衣+风衣	0
2026-02-09	7	13	sunny	风衣+卫衣	0
2026-02-10	8	14	cloudy	风衣+卫衣	0
2026-02-11	9	15	rain	风衣+卫衣	0
2026-02-12	10	16	sunny	风衣+卫衣	0
2026-02-25	12	20	sunny	风衣+卫衣	0
2026-02-26	13	19	cloudy	风衣+卫衣	0
2026-03-02	4	9	sunny	轻型羽绒+长袖T	-1
2026-03-03	4	8	cloudy	轻型羽绒+长袖T	-1
2026-03-04	4	8	rain	轻型羽绒+长袖T	-1
2026-03-05	2	7	sunny	厚羽绒+毛衣	0
2026-03-09	8	14	sunny	毛衣+风衣	0
2026-03-10	9	15	cloudy	毛衣+风衣	0
2026-03-11	10	16	rain	毛衣+风衣	0
2026-03-16	14	20	sunny	风衣+卫衣	0
2026-03-17	15	21	cloudy	风衣+卫衣	0
2026-03-18	16	22	sunny	风衣+卫衣	+1
2026-03-23	18	24	sunny	卫衣	+2
2026-03-24	19	25	sunny	卫衣	+1
2026-03-25	20	26	cloudy	长袖T	0
2026-03-26	20	27	sunny	长袖T	0
2026-03-30	21	27	sunny	衬衫	0
2026-03-31	22	28	sunny	衬衫	0
2026-04-01	22	28	cloudy	衬衫	+1
2026-04-07	23	29	sunny	短袖T	0
2026-04-08	24	30	sunny	短袖T	0
2026-04-09	23	29	rain	短袖T	0
2026-04-12	22	28	cloudy	衬衫	+1
""".strip()

LEDGER = HEADER + "\n" + ROWS + "\n"

SNAPSHOTS = [
    (["report", "ledger.tsv"], "sample-report.txt", 0),
    (["garments", "ledger.tsv"], "sample-garments.txt", 4),
    (["combos", "ledger.tsv"], "sample-combos.txt", 0),
    (["plan", "ledger.tsv", "--tmin", "7", "--tmax", "13"], "sample-plan.txt", 0),
    (["plan", "ledger.tsv", "--tmin", "7", "--tmax", "13",
      "--wear", "轻型羽绒+长袖T"], "sample-plan-dead.txt", 4),
    (["plan", "ledger.tsv", "--tmin", "18", "--tmax", "23"], "sample-plan-wasteland.txt", 4),
    (["autopsy", "ledger.tsv"], "sample-autopsy.txt", 4),
    (["validate", "ledger.tsv"], "sample-validate.txt", 0),
]


def resolve(arg):
    """File-name args refer to files in HERE; resolve them absolutely so the
    command works from any working directory (CI runs from the repo root)."""
    path = os.path.join(HERE, arg)
    return path if os.path.exists(path) else arg


def main():
    check = "--check" in sys.argv
    path = os.path.join(HERE, "ledger.tsv")
    if check:
        with open(path, "r", encoding="utf-8") as fh:
            if fh.read() != LEDGER:
                print("MISMATCH: ledger.tsv differs from build_examples.py")
                return 1
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(LEDGER)

    status = 0
    for args, name, want_code in SNAPSHOTS:
        path = os.path.join(HERE, name)
        proc = subprocess.run([sys.executable, CLI] + [resolve(a) for a in args],
                              capture_output=True, text=True)
        out = proc.stdout
        if proc.returncode != want_code:
            print("CLI %s exited %d (want %d): %s"
                  % (args, proc.returncode, want_code, proc.stderr))
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
