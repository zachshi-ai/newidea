#!/usr/bin/env python3
"""
Generate deterministic example artifacts for decision-debt.

Builds a realistic Decision Ledger by driving the real command functions
(with injected as_of dates so output is stable), then writes:
    examples/sample-ledger.json
    examples/sample-report.txt
    examples/sample-export.md

Run:  python3 examples/build_examples.py
"""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import decision_debt as dd  # noqa: E402

EX = ROOT / "examples"
LP = EX / "sample-ledger.json"


def run():
    if LP.exists():
        LP.unlink()
    # Build a startup-team ledger in chronological order ---------------------
    dd.cmd_init(LP)

    dd.cmd_add(LP, title="CI provider", options=["GitHub Actions", "CircleCI", "Jenkins"],
               weight=4, as_of=date(2026, 7, 20))
    dd.cmd_commit(LP, "ci-provider", outcome="GitHub Actions", as_of=date(2026, 8, 5))

    dd.cmd_add(LP, title="Pricing model", context="Per-seat vs usage vs flat tier",
               options=["Per-seat", "Usage", "Flat tier"], weight=5, as_of=date(2026, 7, 15))
    dd.cmd_touch(LP, "pricing-model", as_of=date(2026, 8, 10))

    dd.cmd_add(LP, title="Primary database", options=["Postgres", "MySQL", "DynamoDB"],
               weight=4, as_of=date(2026, 8, 1))
    dd.cmd_commit(LP, "primary-database", outcome="Postgres", as_of=date(2026, 8, 3))
    dd.cmd_reopen(LP, "primary-database", as_of=date(2026, 8, 9))  # got cold feet

    dd.cmd_add(LP, title="Hire engineer #2", context="Backend vs frontend first",
               weight=3, as_of=date(2026, 7, 28))  # never touched -> going stale

    dd.cmd_add(LP, title="Logo color", weight=1, as_of=date(2026, 7, 25))
    dd.cmd_abandon(LP, "logo-color", reason="Designer will pick; not my call", as_of=date(2026, 8, 2))

    dd.cmd_add(LP, title="Launch date", context="Soft launch timing before the demo day",
               weight=5, as_of=date(2026, 7, 30))
    dd.cmd_touch(LP, "launch-date", as_of=date(2026, 8, 11))

    dd.cmd_add(LP, title="Feature-flag tool", options=["LaunchDarkly", "Unleash", "DIY"],
               weight=2, as_of=date(2026, 8, 10))

    # Render artifacts as of the "today" of the example ----------------------
    as_of = date(2026, 8, 12)
    (EX / "sample-report.txt").write_text(dd.cmd_report(LP, as_of=as_of) + "\n", encoding="utf-8")
    (EX / "sample-export.md").write_text(dd.cmd_export(LP, as_of=as_of) + "\n", encoding="utf-8")
    # The ledger is already written by the commands; report it.
    print(f"wrote {LP} and report/export artifacts (as_of={as_of.isoformat()})")
    print()
    print(dd.cmd_report(LP, as_of=as_of))


if __name__ == "__main__":
    run()
