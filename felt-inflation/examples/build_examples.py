#!/usr/bin/env python3
"""Deterministically rebuild felt-inflation's example artifacts.

Generates examples/ledger.tsv — Lin Xiao's 18-month receipt ledger as a
single person in Shanghai (2025-01 .. 2026-06, 11 base-basket items,
2 newcomers) — then re-renders the four sample reports through the same
code path the CLI uses, with --base/--period pinned to 2025-01/2026-06.

The story the ledger tells: fixed-basket inflation runs at +12.88%
(+8.93% annualized, over the 5% red line -> exit 4), takeaway lunches
and coffee beans alone contribute more than half of it; the actual bill
grew only +3.18% because Lin Xiao already traded down (cheaper shampoo,
fewer takeaways), which drift reports as a +9.70pp concession gap.

Run with --check to verify the five files byte-match a fresh rebuild
(CI uses this). Fixed prices, fixed dates, no "today", no randomness.
"""

import argparse
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import felt_inflation as fi  # noqa: E402

LEDGER = HERE / "ledger.tsv"
SAMPLES = {
    "rate": HERE / "sample-rate.txt",
    "board": HERE / "sample-board.txt",
    "drift": HERE / "sample-drift.txt",
    "power": HERE / "sample-power.txt",
}

BASE = (2025, 1)
PERIOD = (2026, 6)
MONTHS = fi.month_range_inclusive(BASE, PERIOD)

# item, category, store, base day-of-month, qty per month, price steps
# ((start month index, unit price), ...); month index counted from BASE.
ITEMS = [
    ("eggs-30pc",          "grocery",       "Freshmart",   3,  2,
     [(0, 25.0), (12, 28.0), (15, 32.0)]),
    ("milk-1l",            "grocery",       "Freshmart",   5,  6,
     [(0, 12.0), (9, 12.8)]),
    ("rice-5kg",           "grocery",       "Freshmart",   7,  1,
     [(0, 42.0)]),
    ("coffee-beans-250g",  "grocery",       "Roastery",    9,  2,
     [(0, 48.0), (6, 52.0), (13, 58.0)]),
    ("chicken-breast-500g", "grocery",      "Freshmart",   11, 4,
     [(0, 13.5), (16, 15.0)]),
    ("shampoo-a-400ml",    "grocery",       "Freshmart",   13, 1,
     [(0, 39.0), (9, 45.0)]),
    ("metro-pass",         "transport",     "MetroCard",   15, 1,
     [(0, 100.0)]),
    ("takeaway-lunch",     "dining",        "DeliveryApp", 17, None,
     [(0, 22.0), (5, 24.0), (12, 26.0)]),
    ("streaming-vip",      "entertainment", "AppStore",    19, 1,
     [(0, 25.0), (10, 30.0)]),
    ("gym-monthly",        "health",        "FitClub",     21, 1,
     [(0, 150.0), (14, 165.0)]),
    ("dish-soap",          "grocery",       "Freshmart",   23, 1,
     [(0, 12.5)]),
]

# takeaway qty: cut from 10 to 8/month from 2026-01 (index 12) — the
# concession that shows up in the drift report.
def takeaway_qty(month_index):
    return 8 if month_index >= 12 else 10


def unit_price(steps, month_index):
    price = steps[0][1]
    for start, p in steps:
        if month_index >= start:
            price = p
    return price


def item_rows(item, category, store, day, qty, steps, month_index):
    year, month = fi.shift_month(BASE, month_index)
    if item == "dish-soap" and month % 2 == 0:      # bought on odd months
        return []
    if item == "shampoo-a-400ml" and month_index > 11:  # abandoned in 2026
        return []
    if qty is None:
        qty = takeaway_qty(month_index)
    date = "%04d-%02d-%02d" % (year, month, day)
    price = round(unit_price(steps, month_index) * qty, 2)
    return ["\t".join([date, item, category, str(qty),
                       "%.2f" % price, store])]


NEWCOMERS = [
    ("oat-milk-1l",     "grocery", "Freshmart", 25, 2,
     [(8, 19.5)]),          # from 2025-09 (index 8)
    ("shampoo-b-500ml", "grocery", "Freshmart", 27, 1,
     [(12, 22.9)]),         # from 2026-01 (index 12): the trade-down
]


def newcomer_rows(item, category, store, day, qty, steps, month_index):
    start = steps[0][0]
    if month_index < start:
        return []
    year, month = fi.shift_month(BASE, month_index)
    date = "%04d-%02d-%02d" % (year, month, day)
    price = round(unit_price(steps, month_index) * qty, 2)
    return ["\t".join([date, item, category, str(qty),
                       "%.2f" % price, store])]


def build_ledger():
    lines = ["#\tfelt-inflation demo ledger \u00b7 Lin Xiao, single-person",
             "#\thousehold in Shanghai, 2025-01 .. 2026-06.",
             "#\tprice is the line total; unit price = price / qty.",
             "date\titem\tcategory\tqty\tprice\tstore"]
    for idx in range(len(MONTHS)):
        for spec in ITEMS:
            lines.extend(item_rows(*spec, idx))
        for spec in NEWCOMERS:
            lines.extend(newcomer_rows(*spec, idx))
    return "\n".join(lines) + "\n"


def render_sample(ledger_path, command, extra):
    out = io.StringIO()
    argv = [command, ledger_path,
            "--base", "2025-01", "--period", "2026-06"] + extra
    with redirect_stdout(out):
        fi.main(argv)
    return out.getvalue()


def rebuild():
    """Render the ledger and reports in memory.

    Reports are rendered against a temp copy of the ledger so --check
    never needs the committed files to exist first; the report only
    shows the ledger's basename, so the bytes are path-independent.
    """
    ledger_text = build_ledger()
    tmp = tempfile.mkdtemp(prefix="feltinflation-build-")
    tmp_ledger = os.path.join(tmp, "ledger.tsv")
    with open(tmp_ledger, "w", encoding="utf-8") as fh:
        fh.write(ledger_text)
    reports = {
        "rate": render_sample(tmp_ledger, "rate", []),
        "board": render_sample(tmp_ledger, "board", []),
        "drift": render_sample(tmp_ledger, "drift", []),
        "power": render_sample(tmp_ledger, "power", []),
    }
    return ledger_text, reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify committed files byte-match a rebuild")
    args = parser.parse_args()

    ledger_text, reports = rebuild()
    targets = dict(SAMPLES)
    payloads = dict(reports, ledger=ledger_text)

    if args.check:
        ok = True
        expected = {"ledger": LEDGER}
        expected.update(SAMPLES)
        for name, path in expected.items():
            want = payloads[name]
            if not path.exists():
                print("MISSING  %s" % path.name)
                ok = False
                continue
            with open(path, encoding="utf-8") as fh:
                have = fh.read()
            if have == want:
                print("OK       %s" % path.name)
            else:
                print("DRIFTED  %s (rerun build_examples.py to rebuild)"
                      % path.name)
                ok = False
        if not ok:
            return 1
        print("all example artifacts are in sync")
        return 0

    with open(LEDGER, "w", encoding="utf-8") as fh:
        fh.write(ledger_text)
    for name, path in SAMPLES.items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(reports[name])
    print("rebuilt %s and %d sample reports"
          % (LEDGER.name, len(SAMPLES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
