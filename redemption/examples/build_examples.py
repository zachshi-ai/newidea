#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the redemption example ledgers and report snapshots.

The demo is one household's 2026 prepayment season: a hangzhou combo
loan started 2021-03-01 (commercial ¥1,400,000 @ 4.2% + housing fund
¥600,000 @ 3.1%, both 30y annuity). Two prepays already happened:
¥200,000 term on the commercial loan (2024 bonus) and ¥100,000
payment-mode on it (2025 bonus, easing cash flow). Today the household
has ¥500,000 idle and the deposit rate just fell again.

The numbers the margins are tuned to tell: prepaying ¥500,000 term-mode
on the commercial loan saves ~¥330k interest and pulls payoff forward
~11 years; the same money in a 2.3% deposit loses to the loan's 4.28%
true annual rate (exit 4); paying the housing-fund loan first fires the
wrong-target light (exit 4); and the two-world check is flat to ~1e-15
when the investment rate equals the contract rate — the equivalence
theorem, numerically.

  python3 build_examples.py            # write ledgers + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "redemption.py")
TODAY = ["--today", "2026-09-04"]

LOANS = """\
# 贷款账本 · name/principal(本金元)/rate(执行年利率%)/years(年)/start(首期还款日)/method/note
# method: annuity=等额本息 linear=等额本金；rate 抄合同当前执行值——本件不预测 LPR
# start 按首期还款日口径；最多 4 笔（组合贷）
name	principal	rate	years	start	method	note
商贷	1400000	4.2	30	2021-03-01	annuity	2024-10 存量房贷利率调整后执行值
公积金	600000	3.1	30	2021-03-01	annuity	5 年期以上首套
"""

PREPAYS = """\
# 预付历史 · date(生效日)/amount(元)/target(具体贷款名)/mode/note
# mode: term=缩期(月供不变期限变短) payment=减供(期限不变月供变低)
# target 不收 ALL——历史要记到具体账上；预付 ≥ 届时余额是结清，不进本账本
date	amount	target	mode	note
2024-01-15	200000	商贷	term	2023 年终奖
2025-01-10	100000	商贷	payment	2024 年终奖改减月供，缓解现金流
"""

LEDGERS = [("loans.tsv", LOANS), ("prepays.tsv", PREPAYS)]

# (文件名, 参数, 期望 exit)；stderr 一并入快照（拒答/亮灯的话都写在里面）
SNAPSHOTS = [
    ("sample-plan.txt", ["plan"]),
    ("sample-plan-years.txt", ["plan", "--years-detail"]),
    ("sample-position.txt", ["position"]),
    ("sample-prepay-term.txt", ["prepay", "--amount", "500000"]),
    ("sample-prepay-payment.txt",
     ["prepay", "--amount", "500000", "--mode", "payment"]),
    ("sample-prepay-target.txt",
     ["prepay", "--amount", "300000", "--target", "公积金"], 4),
    ("sample-compare.txt", ["compare", "--amount", "500000"]),
    ("sample-myth.txt", ["myth"]),
    ("sample-vsinvest.txt",
     ["vsinvest", "--amount", "500000", "--yield", "2.3"], 4),
    ("sample-vsinvest-none.txt", ["vsinvest", "--amount", "500000"], 3),
    ("sample-batch.txt", ["batch", "--total", "500000", "--parts", "5"]),
    ("sample-validate.txt", ["validate"]),
]


def main():
    if "--check" in sys.argv:
        for fname, want in LEDGERS:
            with open(os.path.join(HERE, fname), encoding="utf-8") as fh:
                if fh.read() != want:
                    sys.exit(f"{fname} 与构建器不一致："
                             f"请重新运行 build_examples.py")
    else:
        for fname, content in LEDGERS:
            with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
                fh.write(content)
    for spec in SNAPSHOTS:
        fname, argv = spec[0], spec[1]
        want_code = spec[2] if len(spec) > 2 else 0
        run = [sys.executable, CLI] + argv + [
            os.path.join(HERE, "loans.tsv"),
            os.path.join(HERE, "prepays.tsv")] + TODAY
        done = subprocess.run(run, capture_output=True, text=True)
        if done.returncode != want_code:
            sys.exit(f"{fname}: 期望 exit {want_code}，实得 {done.returncode}"
                     f"\n{done.stdout}{done.stderr}")
        out = done.stdout + done.stderr
        with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
            fh.write(out)
        print(f"wrote {fname} (exit {done.returncode})")
    print("OK")


if __name__ == "__main__":
    main()
