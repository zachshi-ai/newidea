#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the smooth-sailing example ledger and report snapshots.

The demo book is one freelancer's 24 months of cash flow (2024-10 to
2026-09): income CV 57.9% (WILD), a best month of 23,800 against a worst
of 2,900, an iPad month, a Spring-Festival double hole, a 7,800 tax bill
paid from unreserved cash, and — by September 2026 — a runway of 2.7
months, under the 3-month death line.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "smooth_sailing.py")

LEDGER = """\
# 小满 · 自由插画师 · 月度现金流账本（2024-10 ~ 2026-09，共 24 个月）
# 列: month 收入月份 / income 当月总进账(税前) / spend 当月总生活支出 / cash 月底现金余额 / tax_paid 当月实际缴税
# 收入结构: 专栏稿费 ~2800/月(稳定小流) + 平台约稿(波动中额) + 出版/品牌项目(不定期尖峰)
# 剧情线: 2025-06 买 iPad+笔 9200(设备尖峰月)；2026-05 补缴上年税 7800(税没预留的痛)；
#         2024-11/2025-10 电商旺季大单；2025-01/2026-01 春节双空窗(收入 3600/3400, 支出反高)
month	income	spend	cash	tax_paid
2024-10	9600	8900	18700	0
2024-11	21400	9400	30700	0
2024-12	17800	12200	36300	0
2025-01	3600	9800	30100	0
2025-02	3200	8100	25200	0
2025-03	12600	8600	29200	0
2025-04	9400	8200	30400	0
2025-05	6800	8900	28300	0
2025-06	15600	17800	26100	0
2025-07	8200	8300	26000	0
2025-08	4400	8500	21900	0
2025-09	18900	8700	32100	0
2025-10	23800	9600	46300	0
2025-11	11200	9200	48300	0
2025-12	8600	13800	43100	0
2026-01	3400	10400	36100	0
2026-02	2900	7800	31200	0
2026-03	15200	8400	38000	0
2026-04	7600	8900	36700	0
2026-05	5800	16600	25900	7800
2026-06	13400	9100	30200	0
2026-07	6200	8700	27700	0
2026-08	4300	8900	23100	0
2026-09	10800	9200	24700	0
"""

SNAPSHOTS = [
    (["report", "ledger.tsv"], "sample-report.txt"),
    (["paycheck", "ledger.tsv"], "sample-paycheck.txt"),
    (["paycheck", "ledger.tsv", "--salary", "9000"], "sample-paycheck-9000.txt"),
    (["simulate", "ledger.tsv", "--salary", "9000"], "sample-simulate-9000.txt"),
    (["simulate", "ledger.tsv", "--salary", "15000"], "sample-simulate-15000.txt"),
    (["tax", "ledger.tsv"], "sample-tax.txt"),
    (["stress", "ledger.tsv"], "sample-stress.txt"),
    (["validate", "ledger.tsv"], "sample-validate.txt"),
]


def resolve(arg):
    """File-name args refer to files in HERE; resolve them absolutely so the
    command works from any working directory (CI runs from the repo root)."""
    path = os.path.join(HERE, arg)
    return path if os.path.exists(path) else arg


def main():
    check = "--check" in sys.argv
    ledger_path = os.path.join(HERE, "ledger.tsv")

    if check:
        with open(ledger_path, "r", encoding="utf-8") as fh:
            if fh.read() != LEDGER:
                print("MISMATCH: %s differs from build_examples.py" % ledger_path)
                return 1
    else:
        with open(ledger_path, "w", encoding="utf-8") as fh:
            fh.write(LEDGER)

    status = 0
    for args, name in SNAPSHOTS:
        path = os.path.join(HERE, name)
        proc = subprocess.run([sys.executable, CLI] + [resolve(a) for a in args],
                              capture_output=True, text=True)
        out = proc.stdout
        if proc.returncode not in (0, 4):
            print("CLI %s failed: %s" % (args, proc.stderr))
            return 1
        if check:
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() != out:
                    print("MISMATCH: %s is stale (regenerate snapshots)" % name)
                    status = 1
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(out)
            print("wrote %s (exit %d)" % (name, proc.returncode))
    return status


if __name__ == "__main__":
    sys.exit(main())
