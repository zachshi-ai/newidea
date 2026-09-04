#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the leave-debt example ledgers and snapshots.

The demo is one employee's 2025 leave ledger (as-of 2025-11-28):
13 granted days across two batches — 3 days carried over from 2024
(deadline 3/31) and 10 days for 2025 (deadline 12/31).

  结转批次  2/14 与 3/28 各休 1 天,3/31 日终作废 1 天 = ¥600（蒸发,无声）;
  年度批次  4/30 吃五一桥（span 6）、10/9 吃整座国庆桥（span 9）,
            但 6/4 与 9/29 悬在周中（杠杆 1.0 全价假）,
            11/28 时还剩 5.5 天、33 天倒计时——按他自己的节奏
            （burn 0.0196/天）年底要蒸发 4.9 天 ≈ ¥2,912,
            常态节奏（1 天/周）装不下,连休或放弃,二选一。

All snapshots are rendered with an explicit --as-of: the same ledgers
reproduce byte-for-byte on any machine, any clock.

  python3 build_examples.py            # write ledgers + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "leave_debt.py")
AS_OF = "2025-11-28"

GRANTS = """\
# 批次授权账本 · grant_date/days/expires/note
# 一行一批假期债权：哪天授予、几天、哪天清零。到期日当天可用、日终作废。
grant_date	days	expires	note
2025-01-01	3	2025-03-31	2024 年结转，3 月底清零
2025-01-01	10	2025-12-31	2025 年度额度（司龄 3 年档）
"""

LEAVE = """\
# 休假流水 · date/days/type/note
# type: annual（消耗年假额度）/ other（调休、病假、事假——额度外，不救年假）
date	days	type	note
2025-02-14	1	annual	周五错峰，搭了个周末
2025-03-28	1	annual	又是周五，结转批的最后一口气
2025-04-30	1	annual	五一前一天，桥值 6 天
2025-06-04	1	annual	周三单飞，全价假
2025-08-20	0.5	annual	周三下午体检，半天也悬在周中
2025-09-29	1	annual	国庆前两天……休早了一天
2025-10-09	1	annual	假期最后一天补一刀，吃到整座国庆桥
2025-12-24	1	other	调休一天，额度外
"""

HOLIDAYS = """\
# 2025 法定节假日与调休补班（只用于连休桥接；一行一个 ISO 日期或 a..b 区间）
# `!日期` = 调休补班日：本该休息的周末要上班，从自由日里扣掉
2025-01-01
2025-01-28..2025-02-04
!2025-01-26
!2025-02-08
2025-04-04..2025-04-06
!2025-04-27
2025-05-01..2025-05-05
2025-05-31..2025-06-02
2025-10-01..2025-10-08
!2025-09-28
!2025-10-11
"""

LEDGERS = [("grants.tsv", GRANTS), ("leave.tsv", LEAVE), ("holidays.txt", HOLIDAYS)]

COMMON = ["--holidays", os.path.join(HERE, "holidays.txt")]
SALARY = ["--monthly-salary", "13050"]

SNAPSHOTS = [
    ("sample-report.txt", "report", ["--as-of", AS_OF] + COMMON + SALARY, 4),
    ("sample-shape.txt", "shape", ["--as-of", AS_OF] + COMMON, 0),
    ("sample-plan.txt", "plan", ["--as-of", AS_OF], 4),
    ("sample-simulate-clear.txt", "simulate",
     ["--as-of", AS_OF, "--take", "5.5", "--on", "2025-12-01"] + SALARY, 0),
    ("sample-simulate-partial.txt", "simulate",
     ["--as-of", AS_OF, "--take", "1.5", "--on", "2025-12-08"] + SALARY, 4),
    ("sample-validate.txt", "validate", COMMON, 0),
]


def main():
    checking = "--check" in sys.argv
    for fname, want in LEDGERS:
        if checking:
            with open(os.path.join(HERE, fname), encoding="utf-8") as fh:
                if fh.read() != want:
                    sys.exit("%s 与构建器不一致：请重新运行 build_examples.py" % fname)
        else:
            with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
                fh.write(want)
            print("wrote %s" % fname)
    for fname, cmd, extra, want_code in SNAPSHOTS:
        run = [sys.executable, CLI, cmd,
               os.path.join(HERE, "grants.tsv"), os.path.join(HERE, "leave.tsv")] + extra
        done = subprocess.run(run, capture_output=True, text=True)
        if done.returncode != want_code:
            sys.exit("%s: 期望 exit %d，实得 %d\n%s%s"
                     % (fname, want_code, done.returncode, done.stdout, done.stderr))
        if checking:
            with open(os.path.join(HERE, fname), encoding="utf-8") as fh:
                if fh.read() != done.stdout:
                    sys.exit("%s 与重渲染不一致：请重新运行 build_examples.py" % fname)
        else:
            with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
                fh.write(done.stdout)
            print("wrote %s (exit %d)" % (fname, done.returncode))
    print("OK")


if __name__ == "__main__":
    main()
