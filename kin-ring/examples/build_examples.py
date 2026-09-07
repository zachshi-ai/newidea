#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the kin-ring example ledger and snapshots.

The demo is 老周 (43 岁) — his brother was diagnosed with type-2
diabetes at 42, and last month the brother turned 47 while 老周 turned
43. At his own birthday dinner he realized: he is now older than his
brother was on diagnosis day. Nobody in the family can answer the
doctor's routine question "any family history?" beyond a vague
"grandpa's stomach was bad".

His 6 people / 6 conditions tell the whole anatomy of a family-history
ledger:

  * two REACHED — the brother's diabetes at 42 (老周 is 43 now), and…
  * three NEAR — father's hypertension at 46 (Δ+3), father's diabetes
    at 48 (Δ+5, exactly on the band edge), aunt's breast cancer at 47
    (Δ+4). The band is where "worth mentioning at your next checkup"
    lives;
  * one CLUSTER — 2型糖尿病 ×2 (father 48 + brother 42), both first-
    degree: the evidence chain you carry to the doctor;
  * one UNDATABLE — grandpa's stroke, year unknown. The man who could
    answer (grandpa) is gone; the man who might remember (father)
    still isn't;
  * mother at 71 has zero rows — really nothing, or never asked?
  * 老周's own thyroid cancer (2024) sits in the SELF lane: his own
    history is data, but it doesn't align against his own clock.

Time machine: --as-of 2012 rewinds to when 老周 was 29 — the brother's
2021 diagnosis is a "后视" row (honestly shown, alignment skipped, and
it drops out of the cluster), every gate goes dark. The rings were
always there; the needle just hadn't reached them.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "kin_ring.py")

LEDGER = """\
# kin-ring 样例账本 · 老周的家(43 岁生日那天,意识到自己已比哥哥确诊时更老)
# 一行一人 / 一病一行:person(key/rel/birth/status) dx(key/dx/dxyr)
# 哥哥 2021 年确诊那天 42 岁;今年老周 43——年轮的指针扫过了这道年纪
# as-of: 2026-09-07
type	key	rel	birth	status	dx	dxyr	note
person	老周	me	1983	alive
person	父亲	parent	1952	alive			家族里唯一可能记得上一辈病史的人
person	母亲	parent	1955	alive
person	哥哥	sibling	1979	alive
person	姑妈	uncle-aunt	1948	dead:2015		父亲胞姐
person	爷爷	grandparent	1925	dead:1998
dx	老周				甲状腺癌	2024	微小癌,术后复查稳定——本人病史,不对齐自己
dx	父亲				高血压	1998	体检发现,服药至今
dx	父亲				2型糖尿病	2000
dx	哥哥				2型糖尿病	2021	42 岁确诊,体检空腹血糖爆表
dx	姑妈				乳腺癌	1995	55 岁走的;生前说她姑妈当年也是「瘤子」——口传,入不了账
dx	爷爷				卒中	?	脑溢血走的,哪一年父亲也记不清
"""

SNAPSHOTS = [
    # (输出文件, 命令(账本路径由 build 追加), 期望退出码)
    ("sample-report.txt",
     ["report"], 4),
    ("sample-kin.txt",
     ["kin"], 0),
    ("sample-ask.txt",
     ["ask"], 0),
    ("sample-validate.txt",
     ["validate"], 0),
    ("sample-report-asof-2012.txt",
     ["report", "--as-of", "2012-06-01"], 0),
]


def build(check: bool) -> int:
    ledger_path = os.path.join(HERE, "kin.tsv")
    if check:
        with open(ledger_path, "r", encoding="utf-8") as fh:
            if fh.read() != LEDGER:
                print("MISMATCH: kin.tsv 与 build_examples.py 内嵌账本不一致")
                return 1
    else:
        with open(ledger_path, "w", encoding="utf-8") as fh:
            fh.write(LEDGER)

    rc_all = 0
    for fname, args, want_rc in SNAPSHOTS:
        proc = subprocess.run(
            [sys.executable, CLI] + args + [os.path.join(HERE, "kin.tsv")],
            capture_output=True, text=True)
        out = proc.stdout
        if proc.returncode != want_rc:
            print("EXIT MISMATCH: %s → rc=%d (want %d)\n%s"
                  % (args, proc.returncode, want_rc, proc.stderr))
            rc_all = 1
            continue
        out_path = os.path.join(HERE, fname)
        if check:
            with open(out_path, "r", encoding="utf-8") as fh:
                if fh.read() != out:
                    print("MISMATCH: %s 与当前输出不一致(跑一次不带 --check 重新生成)"
                          % fname)
                    rc_all = 1
        else:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(out)
            print("wrote %s (rc=%d)" % (fname, proc.returncode))
    if not check:
        print("done")
    return rc_all


if __name__ == "__main__":
    sys.exit(build(check="--check" in sys.argv))
