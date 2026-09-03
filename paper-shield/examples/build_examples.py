#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 paper-shield 全部样例输出（钉死 --today，逐字节可复现）。"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "paper_shield.py")
TARGETS = os.path.join(HERE, "targets.tsv")
EVENTS = os.path.join(HERE, "events.tsv")
TODAY = "2026-09-04"

CASES = [
    ("sample-audit.txt", ["audit", TARGETS, EVENTS]),
    ("sample-fresh.txt", ["fresh", TARGETS, EVENTS]),
    ("sample-simulate-disk.txt", ["simulate", TARGETS, EVENTS, "dead", "disk"]),
    ("sample-simulate-cloud.txt", ["simulate", TARGETS, EVENTS, "dead", "cloud"]),
    ("sample-drills.txt", ["drills", TARGETS, EVENTS]),
    ("sample-validate.txt", ["validate", TARGETS, EVENTS]),
]


def main() -> int:
    for name, args in CASES:
        proc = subprocess.run(
            [sys.executable, CLI] + args + ["--today", TODAY],
            capture_output=True, text=True)
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(proc.stdout)
        marker = "（exit 4）" if proc.returncode == 4 else f"（exit {proc.returncode}）"
        print(f"{name} {marker}")
    print(f"重建 {len(CASES)} 份样例（--today {TODAY} 钉死）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
