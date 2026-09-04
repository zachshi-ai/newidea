#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the float-loan example ledger and report snapshots.

The demo is one engineer's six months of advancing money for work
(2026-03-02 to 2026-08-26, pinned --today 2026-09-04): 12 advances
totalling ¥29,626 — 8 repaid (¥22,923), 3 outstanding (¥6,416), 1 eaten
by finance (¥287, rejected taxi). The margins the story is tuned to
tell: repayment cycles P50 24.0 days / P90 29.0 days → the nudge line;
the ¥3,280 project server advance sits 58 days past due (exit 4); the
float at 3% apr is ¥68.47 — a joke of interest, which is exactly the
point: the real cost is the outstanding principal nobody is watching.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "float_loan.py")
TODAY = "2026-09-04"

LEDGER = """\
# 垫付账本 · date/item/amount(元)/repaid/category[/note]
# repaid 三态：留空=在途 · 0=自担（被拒/超标） · YYYY-MM-DD=回款日
date	item	amount	repaid	category	note
2026-03-02	差旅-杭州投标	2860	2026-03-20	差旅	机票+酒店+高铁
2026-03-18	团建-部门聚餐	1120	2026-04-10	团建	垫店主微信
2026-04-03	差旅-深圳客户	3415	2026-04-24	差旅	与上次同流程
2026-04-03	出租车-超标	287	0	差旅	财务驳回：无发票抬头
2026-04-22	采购-测试耗材	960	2026-05-18	采购	淘宝企业代付
2026-05-06	差旅-成都巡检	4230	2026-05-27	差旅	正常周期
2026-05-19	差旅-北京展会	5118	2026-06-24	差旅	遇五一顺延
2026-06-05	采购-办公椅	1350	2026-07-01	采购	行政让先垫
2026-06-20	差旅-广州交付	3870	2026-07-15	差旅	正常周期
2026-07-08	采购-项目服务器	3280		采购	财务说发票抬头错了重开，之后石沉大海
2026-08-13	差旅-西安验收	2750		差旅	已提单待审
2026-08-26	团建-季度下午茶	386		团建	刚提交
"""

SNAPSHOTS = [
    ("sample-pipeline.txt", ["pipeline"], 4),
    ("sample-stats.txt", ["stats"]),
    ("sample-float.txt", ["float"]),
    ("sample-nudge.txt", ["nudge"], 4),
    ("sample-validate.txt", ["validate"]),
]


def main():
    ledger_path = os.path.join(HERE, "floats.tsv")
    if "--check" in sys.argv:
        with open(ledger_path, encoding="utf-8") as fh:
            if fh.read() != LEDGER:
                sys.exit("floats.tsv 与构建器不一致："
                         "请重新运行 build_examples.py")
    else:
        with open(ledger_path, "w", encoding="utf-8") as fh:
            fh.write(LEDGER)
    for fname, argv, *rest in SNAPSHOTS:
        want_code = rest[0] if rest else 0
        run = [sys.executable, CLI] + argv + [ledger_path, "--today", TODAY]
        done = subprocess.run(run, capture_output=True, text=True)
        if done.returncode != want_code:
            sys.exit(f"{fname}: 期望 exit {want_code}，实得 {done.returncode}"
                     f"\n{done.stdout}{done.stderr}")
        with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
            fh.write(done.stdout)
        print(f"wrote {fname} (exit {done.returncode})")
    print("OK")


if __name__ == "__main__":
    main()
