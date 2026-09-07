#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the lenders-eye example ledgers + snapshots (byte-reproducible).

`python3 build_examples.py`         -> (re)write the three TSVs and every snapshot
`python3 build_examples.py --check` -> verify each file matches, byte for byte

The snapshots are produced by the CLI itself. There is no wall clock anywhere:
as-of defaults to the latest date on file, and every snapshot pins its own
--as-of / --apply-date, so the same ledgers yield the same bytes on any
machine, on any day. The sample story's four red lamps (exit 4) are the
story — expected output, not an error.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

ACCOUNTS = """\
# 银行眼 · 账户账:一行一个账户(含已结清/已关闭——它们仍在档案上)
# 列: name/type/opened/limit/balance/status/lender
# type: mortgage|car_loan|credit_card|online_loan|consumer_loan|other_loan
# status: active 在贷 | settled 结清未销户(档案上的僵尸) | closed 已销户
# lender: bank | online(花呗/白条/借呗/月付/消费金融都算 online)
# 信用卡 balance=当前账单欠额;贷款 balance=剩余本金
name\ttype\topened\tlimit\tbalance\tstatus\tlender
招行信用卡\tcredit_card\t2019-03-15\t100000\t86400\tactive\tbank
花呗\tonline_loan\t2022-01-10\t30000\t0\tsettled\tonline
借呗\tonline_loan\t2023-05-01\t20000\t0\tsettled\tonline
京东白条\tonline_loan\t2024-11-15\t8000\t1200\tactive\tonline
"""

INQUIRIES = """\
# 银行眼 · 查询账:一行一次机构查询(自查不记——个人自查不进任何窗口)
# 列: date/agency/reason
# 硬查询(审批敏感): loan_approval 贷款审批 | card_approval 信用卡审批 | guarantee 担保资格审查
# 软查询(不进窗口): post_loan 贷后管理 | personal 个人自查 | periodic 异议/定期
# hard 不用你填——reason 决定软硬,报告写了什么就是什么
date\tagency\treason
2026-04-02\t某消费金融\tloan_approval
2026-04-18\t某银行\tloan_approval
2026-05-20\t某银行信用卡中心\tcard_approval
2026-06-11\t某消费金融\tloan_approval
2026-07-03\t某银行\tpost_loan
2026-07-23\t某互金平台\tloan_approval
2026-08-08\t某消费金融\tloan_approval
2026-09-05\t某银行\tpost_loan
2026-09-12\t某电商平台\tcard_approval
2026-09-30\t某银行\tpost_loan
"""

DELINQ = """\
# 银行眼 · 逾期账:一行一次逾期(征信只记月档,1-29 天不上账本)
# 列: date/account/days(30|60|90)
date\taccount\tdays
2024-11-20\t招行信用卡\t30
2023-08-05\t借呗\t60
"""

LEDGERS = {
    "accounts.tsv": ACCOUNTS,
    "inquiries.tsv": INQUIRIES,
    "delinq.tsv": DELINQ,
}

# (snapshot filename, argv; --dir appended last)
SNAPSHOTS = [
    ("report.txt", ["report"]),
    ("report-asof-20260630.txt", ["report", "--as-of", "2026-06-30"]),
    ("gate-mortgage-20261201.txt", ["gate", "--product", "mortgage",
                                    "--apply-date", "2026-12-01"]),
    ("clock.txt", ["clock"]),
    ("validate.txt", ["validate"]),
]


def build_snapshots():
    """snapshot subprocesses must run against the freshly written ledgers,
    so the caller has to write them first."""
    out = {}
    cli = os.path.join(HERE, "..", "lenders_eye.py")
    for name, argv in SNAPSHOTS:
        proc = subprocess.run(
            [sys.executable, cli] + argv + ["--dir", HERE],
            capture_output=True, text=True)
        body = proc.stdout
        if proc.returncode not in (0, 4):  # 4 = a lamp is lit; that IS the story
            body += proc.stderr
        out[name] = body + ("[exit %d]\n" % proc.returncode)
    return out


def main():
    check = "--check" in sys.argv[1:]
    if not check:
        for name, text in LEDGERS.items():
            with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        print("wrote %d ledgers" % len(LEDGERS))
    files = dict(LEDGERS)
    files.update(build_snapshots())
    failures = 0
    for name, content in files.items():
        path = os.path.join(HERE, name)
        try:
            with open(path, "rb") as fh:
                current = fh.read()
        except OSError:
            current = None
        if current == content.encode("utf-8"):
            if name not in LEDGERS or check:
                print("ok  %s" % name)
            continue
        if check:
            print("DRIFT %s" % name)
            failures += 1
        else:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            print("wrote %s" % name)
    if check and failures:
        print("%d snapshot(s) drifted — rerun build_examples.py without --check and commit"
              % failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
