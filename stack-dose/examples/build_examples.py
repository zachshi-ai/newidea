#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the stack-dose example ledger and report snapshots.

The demo is one flu week of one patient (小陈, 2026-01-05 → 2026-01-09):
19 dose events across 10 well-known OTC names — every single one taken
exactly as its own label says, and yet the acetaminophen daily total
walks 1,050 → 2,540 → 4,405 mg across the week because the drugs stack:
name differs, ingredient is the same. Day 3 adds the interval failure
(Tylenol 3h after 泰诺林, q4h violated); day 5 the clinic's unmarked
white-bottle drug joins via a custom meds table (the ledger never
invents a drug it was not taught).

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "stack_dose.py")
MEDS = os.path.join(HERE, "meds_custom.tsv")
ASOF = "2026-01-09"

LEDGER = """\
# stack-dose 样例账本 · 小陈的感冒周(2026-01-05 → 2026-01-09)
# 一行一次服药:date/time/drug/qty[/note]
#每一种都按各自的说明书吃——叠起来是同一成分的第两遍、第三遍
date\ttime\tdrug\tqty\tnote
2026-01-05\t08:00\t泰诺\t1\t感冒第一天,按说明书来
2026-01-05\t13:00\t999感冒灵\t2\t中午冲两袋
2026-01-05\t21:30\t白加黑夜片\t1\t睡前一片,睡个好觉
2026-01-06\t08:00\t泰诺\t1\t烧起来了
2026-01-06\t12:30\t999感冒灵\t2\t
2026-01-06\t15:00\t维C银翘片\t3\t换一种试试
2026-01-06\t19:00\t泰诺林\t2\t退烧药加量
2026-01-06\t22:00\t散利痛\t2\t还是疼,再来一种
2026-01-07\t08:00\t泰诺林\t1\t
2026-01-07\t11:00\t泰诺\t1\t才隔三小时,忍不住
2026-01-07\t20:00\t999感冒灵\t2\t
2026-01-08\t07:30\t泰诺林\t2\t高烧不退,全家把药箱端来了
2026-01-08\t10:00\t散利痛\t4\t
2026-01-08\t13:00\t999感冒灵\t4\t
2026-01-08\t16:00\t维C银翘片\t6\t
2026-01-08\t19:30\t泰诺\t2\t
2026-01-08\t22:30\t白加黑夜片\t1\t
2026-01-09\t09:00\t诊所白瓶药\t2\t去医院,医生开的(自定义药表)
2026-01-09\t21:00\t999感冒灵\t1\t
"""

CUSTOM_MEDS = """\
# 自定义药表:药表里没有的药,自己教给账本(说明书永远赢)
# name/ingredient/mg/unit —— 同名药多行=多成分;同名整药替换内置
name\tingredient\tmg\tunit
诊所白瓶药\t对乙酰氨基酚\t300\t片
"""

# (filename, argv, expected exit, append_ledger)
SNAPSHOTS = [
    ("sample-report.txt", ["report", "--meds", MEDS], 4, True),
    ("sample-report-day1.txt",
     ["report", "--meds", MEDS, "--as-of", "2026-01-05"], 0, True),
    ("sample-combo.txt",
     ["combo", "--drugs", "泰诺,999感冒灵,维C银翘片", "--times", "4"], 4, False),
    ("sample-interval.txt", ["interval", "--meds", MEDS], 4, True),
    ("sample-share.txt", ["share", "--ingredient", "对乙酰氨基酚"], 0, False),
    ("sample-validate.txt", ["validate", "--meds", MEDS], 0, True),
]


def main():
    ledger_path = os.path.join(HERE, "doses.tsv")
    meds_path = MEDS
    if "--check" in sys.argv:
        for path, want in ((ledger_path, LEDGER), (meds_path, CUSTOM_MEDS)):
            with open(path, encoding="utf-8") as fh:
                if fh.read() != want:
                    sys.exit(f"{os.path.basename(path)} 与构建器不一致:"
                             f"请重新运行 build_examples.py")
    else:
        with open(ledger_path, "w", encoding="utf-8") as fh:
            fh.write(LEDGER)
        with open(meds_path, "w", encoding="utf-8") as fh:
            fh.write(CUSTOM_MEDS)
    for fname, argv, want_code, with_ledger in SNAPSHOTS:
        run = [sys.executable, CLI] + argv
        if with_ledger:
            run += [ledger_path]
            if "--as-of" not in argv:
                run += ["--as-of", ASOF]
        done = subprocess.run(run, capture_output=True, text=True)
        if done.returncode != want_code:
            sys.exit(f"{fname}: 期望 exit {want_code},"
                     f"实得 {done.returncode}\n{done.stdout}{done.stderr}")
        path = os.path.join(HERE, fname)
        if "--check" in sys.argv:
            with open(path, encoding="utf-8") as fh:
                if fh.read() != done.stdout:
                    sys.exit(f"{fname} 与重新生成的输出不一致:"
                             f"请重新运行 build_examples.py")
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(done.stdout)
        print(f"checked {fname} (exit {done.returncode})"
              if "--check" in sys.argv else f"wrote {fname} (exit {done.returncode})")
    print("OK")


if __name__ == "__main__":
    main()
