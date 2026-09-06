#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the fair-exit demo ledger and regenerate the example snapshots.

Usage:
    python3 examples/build_examples.py          # write ledger + snapshots
    python3 examples/build_examples.py --check  # verify snapshots byte-for-byte

The demo ledger is deliberately small and hand-checkable: 老周, five and a
half years at 星云科技, walked out with a "N+1 based on base salary" sheet.
All headline numbers are hand-computed in tests. The overtime dates are
verified against the real calendar (the CLI refuses a claimed weekend on a
Wednesday) — the build script re-checks them here so the sample can never
silently rot.
"""

import difflib
import os
import subprocess
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "fair_exit.py")
DATA = os.path.join(HERE, "demo-data")


def _tsv(header, rows):
    out = ["\t".join(header)]
    for row in rows:
        out.append("\t".join("" if c is None else str(c) for c in row))
    return "\n".join(out) + "\n"


TENURE = _tsv(
    ["employer", "start", "end", "kind", "offer", "notice",
     "noncomp_months", "noncomp_monthly"],
    [["星云科技", "2021-03-15", "2026-08-31", "协商", 105000, "y", 6, None]])

_MONTHS = ["2025-%02d" % m for m in (9, 10, 11, 12)] \
    + ["2026-%02d" % m for m in range(1, 9)]


def _gross(m):
    if m == "2026-01":
        return 66000     # 24000 月薪 + 42000 年终奖——奖金进应发平均
    return 24000


PAYSLIPS = _tsv(
    ["month", "gross", "overtime", "note"],
    [[m, _gross(m), 3000 if m == "2026-05" else None,
      "含年终奖" if m == "2026-01" else
      ("含已付加班费" if m == "2026-05" else None)] for m in _MONTHS])

LEAVE = _tsv(
    ["year", "entitled", "used", "note"],
    [[2025, 10, 8, "累计工龄 12 年 → 10 天档"],
     [2026, 10, 1, "离职当年按日历折算"]])

# 周末对质：2026-06-13 与 2026-08-08 必须是周六，2026-07-28 必须是工作日
_OVERTIME = [
    ("2026-06-13", 6, "weekend", "周六上线"),
    ("2026-07-28", 3, "workday", "工作日赶版"),
    ("2026-08-08", 4, "weekend", "周六压测"),
]
for d, _h, kind, _n in _OVERTIME:
    y, m, dd = (int(x) for x in d.split("-"))
    wd = date(y, m, dd).weekday()
    if kind == "weekend" and wd < 5:
        raise SystemExit("sample bug: %s is not a weekend" % d)
    if kind == "workday" and wd >= 5:
        raise SystemExit("sample bug: %s is not a workday" % d)

OVERTIME = _tsv(
    ["date", "hours", "kind", "note"],
    [[d, h, k, n] for d, h, k, n in _OVERTIME])

SNAPSHOTS = [
    ("sample-report.txt", ["report", "@TENURE@", "@PAYSLIPS@", "@LEAVE@",
                           "@OT@"]),
    ("sample-check.txt", ["check", "@TENURE@", "@PAYSLIPS@", "@LEAVE@",
                          "@OT@"]),
    ("sample-clock.txt", ["clock", "@TENURE@", "@PAYSLIPS@", "@LEAVE@",
                          "@OT@"]),
    ("sample-worlds.txt", ["worlds", "@TENURE@", "@PAYSLIPS@", "@LEAVE@",
                           "@OT@"]),
    ("sample-validate.txt", ["validate", "@TENURE@", "@PAYSLIPS@", "@LEAVE@",
                             "@OT@"]),
    ("sample-report-asof.txt",
     ["report", "--as-of", "2026-06-30", "@TENURE@", "@PAYSLIPS@", "@LEAVE@",
      "@OT@"]),
]


def main() -> int:
    check = "--check" in sys.argv[1:]
    os.makedirs(DATA, exist_ok=True)
    files = {
        "tenure.tsv": TENURE,
        "payslips.tsv": PAYSLIPS,
        "leave.tsv": LEAVE,
        "overtime.tsv": OVERTIME,
    }
    for name, text in files.items():
        path = os.path.join(DATA, name)
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
            if part == "@TENURE@":
                argv.append(os.path.join(DATA, "tenure.tsv"))
            elif part == "@PAYSLIPS@":
                argv.append(os.path.join(DATA, "payslips.tsv"))
            elif part == "@LEAVE@":
                argv.append(os.path.join(DATA, "leave.tsv"))
            elif part == "@OT@":
                argv.append(os.path.join(DATA, "overtime.tsv"))
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
