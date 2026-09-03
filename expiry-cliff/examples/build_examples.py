#!/usr/bin/env python3
"""Deterministically rebuild expiry-cliff's example artifacts.

Generates examples/family-registry.csv — the Zhang household's validity
ledger: two passports (one with renewal history), a driver license, car
insurance (two annual periods), a domain, a TLS cert, a gym membership and
a work visa — then re-renders the three sample reports through the same
code path the CLI uses, with --as-of pinned to 2025-12-01.

Run with --check to verify the four files byte-match a fresh rebuild (CI
uses this). Fixed dates, no "today", no randomness.
"""

import argparse
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import expiry_cliff as ec  # noqa: E402

REGISTRY = HERE / "family-registry.csv"
SAMPLE_HORIZON = HERE / "sample-horizon.txt"
SAMPLE_TRIP = HERE / "sample-trip.txt"
SAMPLE_SHOW = HERE / "sample-show.txt"

AS_OF = date(2025, 12, 1)
TRIP_START = date(2026, 4, 30)
TRIP_END = date(2026, 5, 8)

REGISTRY_ROWS = [
    # name, category, start, end, margin, holder
    ("Passport", "passport", "2006-03-01", "2016-03-01", "", "Aya Zhang"),
    ("Passport", "passport", "2016-01-15", "2026-03-01", "180", "Aya Zhang"),
    ("Passport", "passport", "2021-06-10", "2031-06-10", "180", "Wei Zhang"),
    ("DriverLicense", "driver_license", "2020-05-20", "2026-02-28", "60", "Aya Zhang"),
    ("CarInsurance", "insurance", "2024-01-10", "2025-01-10", "", "Aya Zhang"),
    ("CarInsurance", "insurance", "2025-01-05", "2026-01-10", "", "Aya Zhang"),
    ("FamilyDomain", "domain", "2024-02-01", "2026-02-01", "", "Zhang Family"),
    ("HomeTLS", "tls_cert", "2025-09-15", "2026-01-04", "", "Zhang Family"),
    ("GymMembership", "membership", "2025-03-01", "2026-03-01", "", "Aya Zhang"),
    ("WorkVisa", "visa", "2025-08-01", "2027-08-01", "90", "Wei Zhang"),
]

ARGS = SimpleNamespace(as_of=AS_OF, category_margin=None, top=15, redact=False,
                       format="text")


def registry_text():
    lines = ["name,category,start,end,margin,holder"]
    lines += [",".join(row) for row in REGISTRY_ROWS]
    return "\n".join(lines) + "\n"


def rebuild_reports():
    """Re-render the three sample reports from the registry on disk."""
    horizon = ec.horizon("family-registry.csv", ARGS)
    horizon_text = ec.render_horizon_text(horizon, ARGS) + "\n"

    trip_args = SimpleNamespace(as_of=AS_OF, category_margin=None, top=15,
                                redact=False, format="text",
                                trip_start=TRIP_START, trip_end=TRIP_END)
    gated = ec.trip_gate("family-registry.csv", trip_args)
    trip_text = ec.render_trip_text(gated, trip_args) + "\n"

    hits = ec.find_item(horizon, "Passport Aya")
    assert len(hits) == 1, "demo query 'Passport Aya' must be unique"
    show_text = ec.render_show_text(horizon, hits[0], ARGS) + "\n"
    return horizon_text, trip_text, show_text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed artifacts match a fresh rebuild")
    args = ap.parse_args()

    import os
    previous = os.getcwd()
    REGISTRY.write_text(registry_text(), encoding="utf-8")
    os.chdir(HERE)                      # registry path in reports stays relative
    try:
        horizon, trip, show = rebuild_reports()
    finally:
        os.chdir(previous)

    if args.check:
        for path, content in ((REGISTRY, registry_text()),
                              (SAMPLE_HORIZON, horizon),
                              (SAMPLE_TRIP, trip), (SAMPLE_SHOW, show)):
            if path.read_text(encoding="utf-8") != content:
                print("MISMATCH: %s does not match a fresh rebuild" % path.name,
                      file=sys.stderr)
                return 1
        print("examples in sync")
        return 0

    SAMPLE_HORIZON.write_text(horizon, encoding="utf-8")
    SAMPLE_TRIP.write_text(trip, encoding="utf-8")
    SAMPLE_SHOW.write_text(show, encoding="utf-8")
    print("wrote %s, %s, %s, %s" % (REGISTRY.name, SAMPLE_HORIZON.name,
                                    SAMPLE_TRIP.name, SAMPLE_SHOW.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
