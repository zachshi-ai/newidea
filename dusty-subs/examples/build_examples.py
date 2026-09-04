#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild the dusty-subs demo data: three years of one person's statement
(2023-09 .. 2026-08, every date and amount pinned) plus the sample reports
generated from it, so the committed CSVs and the committed samples always
reproduce byte for byte.

The story — Lin, an urban knowledge worker, statement in a Chinese bank's
export shape (日期,摘要,金额,类型):

  * netflix    monthly 62 -> 70 (a +12.9% hike in month 25), descriptor
               mangled by a different reference number each cycle — the
               normalization's daily bread. 45 uses/yr -> WATCH.
  * spotify    monthly 38, 300 uses/yr -> KEEP (the cheap thing you live in).
  * icloud+    monthly 6, 365 uses/yr -> KEEP (a photo library's rent).
  * notion     first month 4, then 36 — the promo trap. 6 uses/yr -> CUT.
  * office365  annual 398, 20 uses/yr -> WATCH (annual sub, 3 hits).
  * 超级猩猩月卡  monthly 299, 2 uses/yr — the gym card. CUT at ~1,819/use.
  * 平安车险   semi-annual 2,200 — the car was sold in 2024; the premium
               kept renewing. 0 uses/yr -> pure dust.
  * 爱奇艺季卡  quarterly 78, 30 uses/yr -> KEEP.
  * 房租       monthly 5,200 — detected too, because rent IS a periodic
               commitment; the sample report excludes it with --ignore.
  * noise      盒马鲜生 bulk runs (regular gaps, scattered amounts -> the
               amount check rejects them), 滴滴出行 (irregular gaps ->
               the gap check rejects them), one 8,999 iPhone (a one-off,
               below the radar), a duplicated row (dropped, noted), and a
               salary (type=收入, skipped).

Run `python3 examples/build_examples.py` to rebuild `examples/demo-data/`
and regenerate `examples/sample-*.txt`. Run with `--check` to verify the
committed files still match a fresh rebuild (used by the acceptance suite).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # dusty-subs/

sys.path.insert(0, ROOT)
import dusty_subs as ds  # noqa: E402


def add_months(day: date, n: int) -> date:
    return ds.add_months(day, n)


def month_span(start: date, end: date, day: int) -> list:
    """The `day`-th of every month from start to end, inclusive."""
    out = []
    cur = date(start.year, start.month, day)
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def build_bank_rows() -> list:
    """(日期, 摘要, 金额, 类型) rows, in no particular order; the writer
    sorts by (day, desc)."""
    end = date(2026, 8, 25)
    rows = []

    # gym: monthly 299 on the 3rd, three years, almost never used
    for d in month_span(date(2023, 9, 3), end, 3):
        rows.append((d, "超级猩猩月卡", 299, "支出"))

    # netflix: monthly on the 12th; +12.9% hike from 2025-09; descriptor
    # carries a different reference number every cycle (18/9/9 split pins
    # the display label to the first form)
    netflix_descs = ["NETFLIX.COM 8665797172",
                     "NETFLIX.COM 4029357733",
                     "NETFLIX.COM 3928471923"]
    days = month_span(date(2023, 9, 12), end, 12)
    for i, d in enumerate(days):
        amount = 62 if d < date(2025, 9, 1) else 70
        desc = (netflix_descs[0] if i < 18 else
                netflix_descs[1] if i < 27 else netflix_descs[2])
        rows.append((d, desc, amount, "支出"))

    # spotify: monthly 38 on the 20th
    for d in month_span(date(2023, 9, 20), end, 20):
        rows.append((d, "P9RSK SPOTIFY STOCKHOLM SE", 38, "支出"))

    # icloud+: monthly 6 on the 25th — also the statement's last debit
    for d in month_span(date(2023, 9, 25), end, 25):
        rows.append((d, "ICLOUD+ STORAGE 50GB", 6, "支出"))

    # notion: promo first month 4, then 36 on the 5th
    rows.append((date(2023, 9, 5), "NOTION LABS INC", 4, "支出"))
    for d in month_span(date(2023, 10, 5), end, 5):
        rows.append((d, "NOTION LABS INC", 36, "支出"))

    # office 365: annual 398, joined 2024-03
    for d in (date(2024, 3, 15), date(2025, 3, 15), date(2026, 3, 15)):
        rows.append((d, "OFFICE 365 HOME (MSFT)", 398, "支出"))

    # iqiyi: quarterly 78 on the 8th
    d = date(2023, 10, 8)
    while d <= end:
        rows.append((d, "爱奇艺季卡-自动续费", 78, "支出"))
        d = add_months(d, 3)

    # car insurance: semi-annual 2,200 — the car was sold in early 2024
    d = date(2023, 9, 20)
    while d <= end:
        rows.append((d, "平安车险-自动续保", 2200, "支出"))
        d = d + timedelta(days=182)

    # rent: monthly 5,200 on the 1st — a periodic commitment you live in
    for d in month_span(date(2023, 9, 1), end, 1):
        rows.append((d, "房租", 5200, "支出"))

    # salary: income rows the tool must skip
    for d in month_span(date(2023, 9, 10), end, 10):
        rows.append((d, "工资-招行代发", 23800, "收入"))

    # hema bulk runs: perfectly regular gaps, scattered amounts — the
    # amount-consistency check's job
    hema_days = [date(2023, 9, 9) + timedelta(days=84 * i) for i in range(12)]
    hema_amounts = [231.5, 89.0, 402.3, 156.8, 521.0, 78.9,
                    344.6, 99.9, 267.4, 61.2, 489.9, 145.0]
    for d, a in zip(hema_days, hema_amounts):
        rows.append((d, "盒马鲜生", a, "支出"))

    # didi: irregular gaps — the gap-regularity check's job
    didi = [(date(2023, 9, 15), 23.5), (date(2023, 10, 2), 41.0),
            (date(2023, 11, 20), 18.6), (date(2024, 1, 5), 66.2),
            (date(2024, 2, 1), 29.9), (date(2024, 6, 10), 54.3)]
    for d, a in didi:
        rows.append((d, "滴滴出行", a, "支出"))
    rows.append((date(2023, 10, 2), "滴滴出行", 41.0, "支出"))  # duplicate

    # the one-off: an iPhone nobody's ledger should ingest
    rows.append((date(2025, 6, 1), "苹果专卖店", 8999, "支出"))

    return rows


BANK_HEADER = "日期,摘要,金额,类型"

USAGE_CSV = """商户,年使用次数
NETFLIX.COM,45
SPOTIFY,300
超级猩猩,2
iCloud,365
notion,6
OFFICE,20
爱奇艺,30
平安车险,0
"""


def build_data(target_dir: str) -> None:
    os.makedirs(target_dir, exist_ok=True)
    rows = build_bank_rows()
    rows.sort(key=lambda r: (r[0], r[1]))
    lines = [BANK_HEADER] + [
        "%s,%s,%s,%s" % (d.isoformat(), desc, (int(a) if float(a).is_integer()
                                               else a), typ)
        for d, desc, a, typ in rows
    ]
    with open(os.path.join(target_dir, "bank.csv"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(target_dir, "usage.csv"), "w",
              encoding="utf-8") as fh:
        fh.write(USAGE_CSV)


def render_reports(data_dir: str) -> dict:
    """Sample outputs, rendered through the real CLI entry points against
    the freshly built data (paths inside show bare basenames)."""
    bank = os.path.join(data_dir, "bank.csv")
    usage = os.path.join(data_dir, "usage.csv")

    scan = ds.analyze(ds.read_statement(bank))
    scan["statement"]["path"] = "bank.csv"
    report = ds.apply_usage(
        ds.analyze(ds.read_statement(bank), ignore=["房租"]),
        ds.read_usage(usage), ds.DEFAULT_MPU)
    report["statement"]["path"] = "bank.csv"
    explained = next(s for s in report["subscriptions"]
                     if "超级猩猩" in s["merchant"])
    explain = ds.render_explain(explained, report,
                                usage=ds.read_usage(usage),
                                mpu=ds.DEFAULT_MPU,
                                source=bank)
    return {
        "sample-scan.txt": ds.render_scan(scan) + "\n",
        "sample-report.txt": ds.render_report(report) + "\n",
        "sample-explain.txt": explain + "\n",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify committed data + samples match a rebuild")
    args = ap.parse_args(argv)

    data_dir = os.path.join(HERE, "demo-data")
    tmp = tempfile.mkdtemp(prefix="dusty-demo-")
    try:
        build_data(os.path.join(tmp, "demo-data"))
        reports = render_reports(os.path.join(tmp, "demo-data"))

        if args.check:
            checks = [("demo-data/bank.csv", None),
                      ("demo-data/usage.csv", None)]
            for name, _ in checks:
                path = os.path.join(HERE, name)
                fresh = os.path.join(tmp, name)
                if not os.path.exists(path):
                    print("%s missing; run without --check first" % name)
                    return 1
                with open(path, encoding="utf-8") as fh:
                    have = fh.read()
                with open(fresh, encoding="utf-8") as fh:
                    if fh.read() != have:
                        print("%s out of sync; rebuild examples" % name)
                        return 1
            for name, want in reports.items():
                path = os.path.join(HERE, name)
                if not os.path.exists(path):
                    print("%s missing" % name)
                    return 1
                with open(path, encoding="utf-8") as fh:
                    if fh.read() != want:
                        print("%s out of sync; rebuild examples" % name)
                        return 1
            print("examples in sync")
            return 0

        if os.path.isdir(data_dir):
            shutil.rmtree(data_dir)
        shutil.copytree(os.path.join(tmp, "demo-data"), data_dir)
        for name, text in reports.items():
            with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        print("rebuilt examples/demo-data + 3 sample reports")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
