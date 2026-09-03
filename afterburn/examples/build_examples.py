#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 examples/ 下全部样例输出（钉死 --now，逐字节可复现）。

用法：python3 examples/build_examples.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "afterburn.py")
LEDGER = os.path.join(HERE, "week.tsv")

LEDGER_ROWS = """\
# afterburn 示例账本：开发者小张的一周（就寝 23:30）
# 列：日期  时间  饮品  [毫克覆盖]
2026-08-28\t08:40\tdrip
2026-08-28\t15:30\tlatte
2026-08-29\t10:15\tmilk-tea\t90
2026-08-30\t09:00\tdrip
2026-08-31\t08:40\tdrip
2026-08-31\t15:30\tlatte
2026-09-01\t08:40\tdrip
2026-09-01\t15:30\tlatte
2026-09-01\t20:10\tcola
2026-09-02\t08:40\tdrip
2026-09-03\t08:40\tamericano
2026-09-03\t15:30\tlatte
2026-09-03\t20:10\tcola
2026-09-04\t08:40\tdrip
2026-09-04\t15:30\tmilk-tea\t120
"""

CASES = [
    ("sample-now.txt",
     ["now", LEDGER, "--now", "2026-09-04 16:00"]),
    ("sample-bedtime-red.txt",
     ["bedtime", LEDGER, "--at", "23:30", "--date", "2026-09-04"]),
    ("sample-bedtime-green.txt",
     ["bedtime", LEDGER, "--at", "23:30", "--date", "2026-09-02"]),
    ("sample-cutoff.txt",
     ["cutoff", LEDGER, "--at", "23:30", "--drink", "latte",
      "--date", "2026-09-04", "--now", "2026-09-04 14:00"]),
    ("sample-cutoff-halflife.txt",
     ["cutoff", LEDGER, "--at", "23:30", "--drink", "latte",
      "--date", "2026-09-04", "--now", "2026-09-04 14:00",
      "--half-life", "8"]),
    ("sample-day.txt",
     ["day", LEDGER, "--date", "2026-09-03"]),
    ("sample-week.txt",
     ["week", LEDGER, "--end", "2026-09-04", "--at", "23:30"]),
    ("sample-steady.txt",
     ["steady", "08:40", "drip", "15:30", "latte"]),
    ("sample-wean.txt",
     ["wean", LEDGER, "--now", "2026-09-04 21:00"]),
    ("sample-drinks.txt",
     ["drinks"]),
    ("sample-validate.txt",
     ["validate", LEDGER]),
]


def main() -> int:
    with open(LEDGER, "w", encoding="utf-8") as fh:
        fh.write(LEDGER_ROWS + "\n")
    for name, argv in CASES:
        proc = subprocess.run([sys.executable, CLI] + argv,
                              capture_output=True, text=True)
        expected_code = 4 if "bedtime-red" in name else 0
        if proc.returncode != expected_code:
            print("!! %s 退出码 %d（期望 %d）\n%s" % (
                name, proc.returncode, expected_code, proc.stderr), file=sys.stderr)
            return 1
        out = proc.stdout
        # 把绝对路径换成相对路径，样例在谁的机器上都长得一样
        out = out.replace(LEDGER, "examples/week.tsv").replace(CLI, "afterburn.py")
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(out)
        print("ok %s (exit %d)" % (name, proc.returncode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
