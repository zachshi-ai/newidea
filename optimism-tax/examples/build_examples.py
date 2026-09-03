#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild the optimism-tax example ledger and sample outputs, from zero.

Three teammates, one shared ledger, four months (2026-05 .. 2026-08),
every number pinned. The story the data tells:

  * dana   — builds features, estimates are mildly optimistic (1.0-1.5x)
  * eva    — owns research spikes, estimates are a tax shelter in
             reverse: the work outgrows her estimates 3.2-4.5x, every time
  * frank  — runs ops/migrations and hides buffer: he finishes early,
             every time (0.6-0.75x)

Run:  python3 examples/build_examples.py
Regenerates records.jsonl, sample-report.txt and sample-quote.txt inside
examples/. Deterministic: the ledger is fully pinned, the tool prints no
wall-clock dates, so outputs are byte-stable across machines.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "optimism_tax.py")

# (date, estimate, actual, tag, note) — every row pinned.
RECORDS = [
    # dana, features: honest work, mildly optimistic
    ("2026-05-06", 3, 3.5, "feature", "cart promo rules"),
    ("2026-05-19", 2, 2.0, "feature", "pagination cleanup"),
    ("2026-06-03", 5, 7.0, "feature", "checkout refactor"),
    ("2026-06-17", 3, 3.0, "feature", "webhook retries"),
    ("2026-07-01", 2, 2.5, "feature", "settings page split"),
    ("2026-07-15", 4, 6.0, "feature", "search relevance v1"),
    ("2026-07-29", 3, 4.0, "feature", "audit log viewer"),
    ("2026-08-12", 2, 2.0, "feature", "rate limit headers"),
    ("2026-08-26", 3, 3.5, "feature", "onboarding checklist"),
    # eva, research: every spike outgrows its estimate, every time
    ("2026-05-11", 2, 6.4, "research", "OAuth provider spike"),
    ("2026-05-27", 3, 9.9, "research", "vendor API evaluation"),
    ("2026-06-10", 2, 6.8, "research", "search engine bake-off"),
    ("2026-06-24", 3, 10.5, "research", "schema migration path"),
    ("2026-07-08", 2, 7.2, "research", "ML ranking feasibility"),
    ("2026-07-22", 3, 11.4, "research", "multi-tenant isolation"),
    ("2026-08-05", 2, 8.0, "research", "streaming pipeline PoC"),
    ("2026-08-19", 3, 13.5, "research", "offline sync design"),
    # bugfix: small, well understood, mostly on the money
    ("2026-05-22", 1, 1.0, "bugfix", "duplicate charge guard"),
    ("2026-06-30", 1, 1.5, "bugfix", "timezone off-by-one"),
    ("2026-08-03", 0.5, 0.5, "bugfix", "404 on empty cart"),
    ("2026-08-28", 1, 0.8, "bugfix", "double-submit on quote"),
    # frank, ops: early every time — buffer hidden in the estimate
    ("2026-06-08", 3, 2.0, "ops", "postgres minor upgrade"),
    ("2026-07-06", 5, 3.0, "ops", "log pipeline cutover"),
    ("2026-08-10", 2, 1.5, "ops", "cert rotation drill"),
    ("2026-08-31", 4, 3.0, "ops", "backup restore drill"),
]

# One half-written receipt, the way they actually pile up on the fridge:
# the estimate went in, the actual never did. The tool skips and counts it.
BAD_LINE = {"date": "2026-09-01", "estimate": 2, "note": "draft: invoice batching"}


def build_ledger() -> str:
    lines = []
    for day, est, act, tag, note in RECORDS:
        lines.append(json.dumps(
            {"date": day, "estimate": est, "actual": act, "tag": tag,
             "note": note}, ensure_ascii=False))
    lines.append(json.dumps(BAD_LINE, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def run(args: list) -> int:
    result = subprocess.run(
        [sys.executable, TOOL] + args,
        cwd=HERE, capture_output=True, text=True,
    )
    return result


def main() -> int:
    ledger = os.path.join(HERE, "records.jsonl")
    with open(ledger, "w", encoding="utf-8") as fh:
        fh.write(build_ledger())
    print(f"wrote {ledger} ({len(RECORDS)} records + 1 half-written line)")

    jobs = [
        (["report", "--file", "records.jsonl"], "sample-report.txt"),
        (["quote", "3", "--file", "records.jsonl"], "sample-quote.txt"),
        (["quote", "3", "--tag", "research", "--file", "records.jsonl"],
         "sample-quote-research.txt"),
    ]
    for args, out_name in jobs:
        result = run(args)
        if result.returncode != 0:
            print(f"FAILED: {' '.join(args)} -> exit {result.returncode}")
            print(result.stdout)
            print(result.stderr)
            return 1
        out_path = os.path.join(HERE, out_name)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(result.stdout)
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
