#!/usr/bin/env python3
"""
Generate deterministic example artifacts for doc-drift.

Builds examples/demo-repo/ — a tiny fixture repo whose markdown contains
deliberate drift (broken paths, a broken link, a missing symbol, an expired
freshness stamp, a future-dated stamp) alongside valid references — then
scans it with the real tool (as_of pinned to 2026-08-16) and writes:
    examples/expected-report.txt   (root line normalised to <root>)

Run:  python3 examples/build_examples.py
"""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import doc_drift as dd  # noqa: E402

EX = ROOT / "examples"
DEMO = EX / "demo-repo"
AS_OF = date(2026, 8, 16)          # pinned so the report never changes

README = """\
# demo-repo

A tiny fixture repo for doc-drift's examples and tests — it contains
deliberate drift on purpose (each bad line is marked DRIFT below).

<!-- verified: 2026-01-05; ttl: 90d -->                      <- DRIFT: stale (WARN)

Quick start — read the [guide](docs/guide.md), then:

```bash
python3 src/live.py --config config.toml
```

The entry point is `src/live.py::run_checks`.
Legacy rules used to live in `src/gone.py`.                 <- DRIFT: missing file
Older notes are in `old_notes.txt`.                         <- DRIFT: missing file
See the [FAQ](docs/missing.md) for details.                 <- DRIFT: missing link
Fallback entry: `src/live.py::gone_fn`.                     <- DRIFT: missing symbol
The archived `legacy/old_path.py` moved.  <!-- dd:ignore: kept for history -->
<!-- verified: 2026-12-01 -->                                <- DRIFT: future date
"""

GUIDE = """\
# Guide

Back to the [README](../README.md).

Config comes from `config.toml`.

The checks in src/live.py cover the basics.

Full options: [config guide](../docs/config-guide.md).      <- DRIFT: missing link
"""


def run():
    (DEMO / "src").mkdir(parents=True, exist_ok=True)
    (DEMO / "docs").mkdir(parents=True, exist_ok=True)
    (DEMO / "README.md").write_text(README, encoding="utf-8")
    (DEMO / "docs" / "guide.md").write_text(GUIDE, encoding="utf-8")
    (DEMO / "src" / "live.py").write_text(
        "def run_checks():\n    return 'ok'\n", encoding="utf-8")
    (DEMO / "config.toml").write_text("debug = false\n", encoding="utf-8")

    result = dd.run_scan([str(DEMO)], excludes=[], today=AS_OF,
                         default_ttl=dd.DEFAULT_TTL_DAYS)
    report = dd.report_text(result).replace(str(DEMO), "<root>")
    (EX / "expected-report.txt").write_text(report + "\n", encoding="utf-8")

    print("wrote demo-repo/ (4 files)")
    print("wrote expected-report.txt  (%d errors, %d warnings, %d refs checked)"
          % (result["errors"], result["warnings"], result["refs_checked"]))
    if (result["errors"], result["warnings"]) != (6, 1):
        print("WARNING: planted drift counts changed — update tests!",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
