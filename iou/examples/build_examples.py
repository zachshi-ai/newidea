#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the iou example ledger and report snapshots.

The demo is one lender's four years of informal personal loans
(2022-10-08 to 2026-05-20, pinned --as-of 2026-05-20): 15 events across
5 people — ¥36,300 lent out, ¥15,800 repaid, ¥1,000 forgiven, leaving a
¥19,500 exposure nobody but the ledger can see. The margins the story is
tuned to tell: repayment cycles [28, 32, 118, 179, 376] days → P90
297.2 becomes the chase line; three open balances (¥15,500) sit past it
(exit 4, STALE); the 表哥·阿伟 statute of limitations was reset by the
2025-08-15 chase — the one line that keeps the law on your side; and
`should` on the night of 2025-11-29 says CAUTION (40.0% historic repay
rate, ¥12,000 still open) — 老周 didn't listen, and lent 4,000 more.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "iou.py")
ASOF = "2026-05-20"

LEDGER = """\
# iou 样例账本 · 老周的欠条(2022-10 → 2026-05)
# 一行一事件:date/kind/who/amount[/note[/promised]]
# kind:lend 借出 · repay 回款 · chase 催讨(不带金额) · forgive 销账
date\tkind\twho\tamount\tnote\tpromised
2022-10-08\tlend\t表哥·阿伟\t20000\t装修周转,说好过年还\t2023-02-01
2023-02-03\trepay\t表哥·阿伟\t8000\t过年回了个零头
2023-05-11\tlend\t同事·小蔡\t3000\t换手机,说下月发工资还\t2023-06-15
2023-06-12\trepay\t同事·小蔡\t3000\t发工资当天就转来了
2023-09-08\tlend\t同事·小蔡\t2000\t家里急用
2024-01-18\tlend\t发小·强子\t5000\t住院押金
2024-03-05\trepay\t同事·小蔡\t2000\t拖了半年,但还了
2024-08-02\tlend\t前室友·阿凯\t1500\t房租周转,月底还
2025-01-20\tchase\t发小·强子\t0\t去病房看他,提了一句
2025-01-28\trepay\t发小·强子\t2000\t催了之后一周,回了 2000
2025-04-11\tlend\t表姐·静静\t800\t网购代付,发工资就还
2025-05-09\trepay\t表姐·静静\t800\t28 天,说到做到
2025-08-15\tchase\t表哥·阿伟\t0\t微信上提了一嘴,回了个「嗯」
2025-11-30\tlend\t表哥·阿伟\t4000\t又开口,没顶住
2026-05-20\tforgive\t发小·强子\t1000\t病还没好利索,这 1000 不要了
"""

SNAPSHOTS = [
    ("sample-report.txt", ["report"], 4),
    ("sample-book.txt", ["book"], 0),
    ("sample-nudge.txt", ["nudge"], 4),
    ("sample-should.txt",
     ["should", "--who", "表哥·阿伟", "--amount", "4000",
      "--as-of", "2025-11-29"], 4),
    ("sample-validate.txt", ["validate"], 0),
]


def main():
    ledger_path = os.path.join(HERE, "iou.tsv")
    if "--check" in sys.argv:
        with open(ledger_path, encoding="utf-8") as fh:
            if fh.read() != LEDGER:
                sys.exit("iou.tsv 与构建器不一致:"
                         "请重新运行 build_examples.py")
    else:
        with open(ledger_path, "w", encoding="utf-8") as fh:
            fh.write(LEDGER)
    for fname, argv, *rest in SNAPSHOTS:
        want_code = rest[0] if rest else 0
        if "--as-of" not in argv:
            argv = argv + ["--as-of", ASOF]
        run = [sys.executable, CLI] + argv + [ledger_path]
        done = subprocess.run(run, capture_output=True, text=True)
        if done.returncode != want_code:
            sys.exit(f"{fname}: 期望 exit {want_code},"
                     f"实得 {done.returncode}\n{done.stdout}{done.stderr}")
        with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
            fh.write(done.stdout)
        print(f"wrote {fname} (exit {done.returncode})")
    print("OK")


if __name__ == "__main__":
    main()
