#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the lowball example report snapshots.

The demo is one 89㎡ full-package renovation told twice. Company A quotes
¥93,002 "全包拎包入住" — bait-priced open plumbing (¥38/m vs. a ¥45–90
common range), no waterproofing, no levelling, no debris removal, no
management fee, no tax invoice in the quote. Company B quotes ¥130,012
for the same flat and gets dismissed as expensive. Twelve signed change
orders later, A settles at ¥144,238: the upgrade column the owner chose,
the forced column the quote "forgot", an open-item quantity that exploded
2.19x, and the padded column every competitor includes for free.

The numbers the margins are tuned to tell: change-order rate +55.1%
(red line 30%), hallucination index 28.3% (real floor ¥119,324), two
kill prices (levelling 1.58x, hauling 2.40x above the range ceiling),
and one bait×open kill combo. Company B's judge verdict: clean, exit 0 —
the expensive quote was the cheap one.

The ledgers themselves (quote.tsv / addons.tsv / quote-good.tsv) are the
source of truth and are NOT rewritten here; this script runs every demo
command, asserts its exit code, and snapshots stdout. With --check it
additionally byte-compares every snapshot — CI runs this.

  python3 build_examples.py            # run commands, (re)write snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "lowball.py")

SNAPSHOTS = [
    ("sample-audit.txt", ["audit", "quote.tsv", "addons.tsv"], 4),
    ("sample-gaps.txt", ["gaps", "quote.tsv"], 4),
    ("sample-judge.txt", ["judge", "quote.tsv"], 4),
    ("sample-judge-good.txt", ["judge", "quote-good.tsv"], 0),
    ("sample-gaps-good.txt", ["gaps", "quote-good.tsv"], 0),
    ("sample-prices.txt", ["prices", "quote.tsv", "addons.tsv"], 4),
    ("sample-sign-kill.txt",
     ["sign", "--item", "墙面找平(误差超范围)", "--qty", "96",
      "--price", "95", "--unit", "元/㎡", "quote.tsv"], 4),
    ("sample-sign-ok.txt",
     ["sign", "--item", "卫生间防水(两遍)", "--qty", "14",
      "--price", "70", "--unit", "元/㎡", "quote.tsv"], 0),
    ("sample-validate.txt", ["validate", "quote.tsv", "addons.tsv"], 0),
]


def run_snapshot(fname, argv, want_code, check):
    run = [sys.executable, CLI] + [os.path.join(HERE, a) if a.endswith(".tsv") else a
                                   for a in argv]
    done = subprocess.run(run, capture_output=True, text=True)
    if done.returncode != want_code:
        sys.exit(f"{fname}: 期望 exit {want_code},实得 {done.returncode}\n{done.stdout}")
    path = os.path.join(HERE, fname)
    if check:
        with open(path, encoding="utf-8") as fh:
            if fh.read() != done.stdout:
                sys.exit(f"{fname} 与当前输出不一致:请重新运行 build_examples.py")
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(done.stdout)
        print(f"  {fname}  (exit {done.returncode})")


def main():
    check = "--check" in sys.argv
    for fname, argv, want_code in SNAPSHOTS:
        run_snapshot(fname, argv, want_code, check)
    if not check:
        print(f"已生成 {len(SNAPSHOTS)} 份快照(exit code 全部符合设计)")


if __name__ == "__main__":
    main()
