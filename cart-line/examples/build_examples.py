#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the cart-line example ledgers and report snapshots.

The demo ledger is one person's single big-promo season (2026-10-21 to
2026-11-11): 8 orders, a platform banner claiming "you saved ¥460", and
a filler total of ¥232 that the banner never mentions — an illusion gap
that equals the filler total to the last cent, by algebra. Two orders
overpaid (one of them forcing a fill on an unwinnable line), the
replay finds ¥117 of avoidable spending, and the fate ledger shows
filler items dying 3.5x faster than planned ones.

  python3 build_examples.py            # write ledgers + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "cart_line.py")

ORDERS = """\
date	order	rule	planned	filler	discount	paid
2026-10-21	O-101	every:300:50	268.0	32.0	50.0	250.0
2026-10-23	O-102	full:99:20	88.0	34.0	20.0	102.0
2026-10-26	O-103	full:99:20	61.0	0.0	0.0	61.0
2026-10-28	O-104	every:300:50	555.0	45.0	100.0	500.0
2026-11-01	O-105	every:300:50	1280.0	0.0	200.0	1080.0
2026-11-05	O-106	full:99:20	45.0	88.0	20.0	113.0
2026-11-08	O-107	full:300:50	320.0	25.0	50.0	295.0
2026-11-11	O-108	full:99:20	92.0	8.0	20.0	80.0
"""

ITEMS = """\
date	order	name	price	filler	fate	fate_date
2026-10-21	O-101	手机支架	32.0	1	idle	2026-12-30
2026-10-21	O-101	洗衣液	89.0	0	used	2027-01-15
2026-10-21	O-101	抽纸	79.0	0	used	2026-12-28
2026-10-21	O-101	沐浴露	100.0	0	used	2027-03-01
2026-10-23	O-102	数据线	8.9	1	used	2026-12-14
2026-10-23	O-102	数据线	8.9	1	used	2027-01-20
2026-10-23	O-102	桌面收纳盒	16.2	1	idle	2027-02-10
2026-10-23	O-102	洗发水	55.0	0	used	2027-02-20
2026-10-23	O-102	肥皂	33.0	0	used	2027-01-10
2026-10-26	O-103	生抽	61.0	0	used	2027-01-25
2026-10-28	O-104	挂耳咖啡	45.0	1	used	2026-12-05
2026-10-28	O-104	大米	59.9	0	used	2027-01-08
2026-10-28	O-104	酱油	23.9	0	used	2026-12-30
2026-10-28	O-104	拖把	89.9	0	used	2027-02-15
2026-10-28	O-104	保温杯	129.0	0	used	2027-03-10
2026-10-28	O-104	维生素C	152.3	0	used	2027-02-28
2026-10-28	O-104	电池	100.0	0	used	2027-03-20
2026-11-01	O-105	空气炸锅	599.0	0	used	2027-02-25
2026-11-01	O-105	坚果礼盒	281.0	0	idle	2027-03-01
2026-11-01	O-105	年货腊肉	400.0	0	used	2027-02-10
2026-11-05	O-106	长柄锅刷	19.9	1	trashed	2026-11-20
2026-11-05	O-106	搞怪袜子	29.8	1	idle	2027-01-05
2026-11-05	O-106	桌面桌垫	38.3	1	idle	2027-02-15
2026-11-05	O-106	牙膏	25.0	0	used	2027-02-01
2026-11-05	O-106	洗碗布	20.0	0	used	2027-01-30
2026-11-08	O-107	桌面垃圾桶	25.0	1	idle	2027-01-30
2026-11-08	O-107	抽纸	95.0	0	used	2027-01-20
2026-11-08	O-107	毛巾	100.0	0	trashed	2026-12-10
2026-11-08	O-107	香皂	125.0	0	used	2027-03-05
2026-11-11	O-108	备用牙刷	8.0	1	used	2027-02-01
2026-11-11	O-108	牛奶	92.0	0	used	2026-11-20
"""

SNAPSHOTS = [
    (["judge", "--subtotal", "268", "--rule", "every:300:50",
      "--fill", "15", "--fill", "32", "--fill", "49"], "sample-judge.txt"),
    (["judge", "--subtotal", "45", "--rule", "full:99:20",
      "--fill", "30", "--fill", "54"], "sample-judge-unworth.txt"),
    (["audit", "orders.tsv"], "sample-audit.txt"),
    (["fate", "orders.tsv", "items.tsv"], "sample-fate.txt"),
    (["simulate", "orders.tsv"], "sample-simulate.txt"),
    (["validate", "orders.tsv", "items.tsv"], "sample-validate.txt"),
]


def resolve(arg):
    """File-name args refer to files in HERE; resolve them absolutely so the
    command works from any working directory (CI runs from the repo root)."""
    path = os.path.join(HERE, arg)
    return path if os.path.exists(path) else arg


def main():
    check = "--check" in sys.argv
    for name, text in (("orders.tsv", ORDERS), ("items.tsv", ITEMS)):
        path = os.path.join(HERE, name)
        if check:
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() != text:
                    print("MISMATCH: %s differs from build_examples.py" % path)
                    return 1
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    status = 0
    for args, name in SNAPSHOTS:
        path = os.path.join(HERE, name)
        proc = subprocess.run([sys.executable, CLI] + [resolve(a) for a in args],
                              capture_output=True, text=True)
        out = proc.stdout
        if proc.returncode not in (0, 4):
            print("CLI %s failed (exit %d): %s"
                  % (args, proc.returncode, proc.stderr))
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
