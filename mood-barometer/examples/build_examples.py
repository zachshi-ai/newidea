#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 mood-barometer 的全部示例输出（钉死 --today，逐字节可复现）.

用法：
  python3 mood-barometer/examples/build_examples.py           # 重建全部样例
  python3 mood-barometer/examples/build_examples.py --check   # CI 逐字节校验，不写盘
"""

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mood_barometer  # noqa: E402

TODAY = "2026-09-04"
LEDGER = os.path.join(HERE, "moods.tsv")

# (输出文件, argv, 预期 exit code)
CASES = [
    ("sample-climate-red.txt", ["climate", LEDGER, "--today", TODAY], 4),
    ("sample-weather.txt", ["weather", LEDGER, "--today", TODAY], 0),
    ("sample-events.txt", ["events", LEDGER, "--today", TODAY], 0),
    ("sample-log.txt", ["log"], 0),
]


def main() -> int:
    check = "--check" in sys.argv[1:]
    failed = 0
    for filename, argv, expected in CASES:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mood_barometer.main(list(argv))
        text = out.getvalue()
        assert code == expected, f"{filename}: exit {code} != 预期 {expected}"
        path = os.path.join(HERE, filename)
        if check:
            with open(path, encoding="utf-8") as f:
                if f.read() != text:
                    print(f"DRIFT: {filename} 与账本现状不一致（重建后提交）")
                    failed += 1
                else:
                    print(f"OK {filename}")
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"wrote {filename} (exit {code})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
