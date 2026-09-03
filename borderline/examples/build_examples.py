#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 borderline 的全部示例输出（钉死 --today，逐字节可复现）.

用法：
  python3 borderline/examples/build_examples.py           # 重建全部样例
  python3 borderline/examples/build_examples.py --check   # CI 逐字节校验，不写盘
"""

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import borderline  # noqa: E402

TODAY = "2026-09-04"
LEDGER = os.path.join(HERE, "ledger.tsv")

# (输出文件, argv, 预期 exit code)
CASES = [
    ("sample-panel-red.txt", ["panel", LEDGER, "--today", TODAY], 4),
    ("sample-trend-uric.txt",
     ["trend", LEDGER, "--marker", "uric-acid", "--today", TODAY], 0),
    ("sample-trend-glucose.txt",
     ["trend", LEDGER, "--marker", "fasting-glucose", "--today", TODAY], 0),
    ("sample-next.txt", ["next", LEDGER, "--today", TODAY], 0),
    ("sample-validate.txt", ["validate", LEDGER, "--today", TODAY], 0),
    ("sample-markers.txt", ["markers"], 0),
]


def main() -> int:
    check = "--check" in sys.argv[1:]
    for filename, argv, expected in CASES:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = borderline.main(list(argv))
        assert code == expected, f"{filename}: exit {code} != {expected}"
        text = out.getvalue()
        path = os.path.join(HERE, filename)
        if check:
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() != text:
                    print(f"MISMATCH {filename}", file=sys.stderr)
                    return 1
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        print(f"{'checked' if check else 'wrote'} {filename} (exit {code})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
