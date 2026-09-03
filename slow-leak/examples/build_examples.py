#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 slow-leak 的全部示例输出（钉死 --today，逐字节可复现）.

用法：python3 slow-leak/examples/build_examples.py
"""

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import slow_leak  # noqa: E402

TODAY = "2026-09-04"
LEDGER = os.path.join(HERE, "ledger.tsv")

# (输出文件, argv, 预期 exit code)
CASES = [
    ("sample-check-red.txt", ["check", LEDGER, "--today", TODAY], 4),
    ("sample-trend-electric.txt",
     ["trend", LEDGER, "--utility", "electric", "--today", TODAY], 0),
    ("sample-detect.txt", ["detect", LEDGER, "--today", TODAY], 0),
    ("sample-floor.txt", ["floor", LEDGER, "--today", TODAY], 0),
    ("sample-validate.txt", ["validate", LEDGER, "--today", TODAY], 0),
    ("sample-utilities.txt", ["utilities"], 0),
]


def main() -> int:
    for filename, argv, expected in CASES:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = slow_leak.main(list(argv))
        assert code == expected, f"{filename}: exit {code} != {expected}"
        with open(os.path.join(HERE, filename), "w", encoding="utf-8") as fh:
            fh.write(out.getvalue())
        print(f"wrote {filename} (exit {code})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
