#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the unvested example ledgers + snapshots (byte-reproducible).

`python3 build_examples.py`         -> (re)write the TSVs and every snapshot
`python3 build_examples.py --check` -> verify each file matches, byte for byte

The snapshots are produced by the CLI itself. There is no wall clock anywhere:
as-of defaults to the latest date on file, and every snapshot pins its own
--as-of / --date, so the same ledgers yield the same bytes on any machine,
on any day. The sample story's red lamps (exit 4) are the story — expected
output, not an error.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(os.path.dirname(HERE), "unvested.py")

GRANTS = """\
# 未兑现 · 授予账:一行一份授予(同公司多份授予合法,top-up)
# 列: company/kind/grant_date/shares/strike/vest_years/cliff_months/interval/
#     status/end_date/window_days/latest_price/price_date/note
# kind: option 期权(行权价 strike 必填,有行权窗口) | rsu 限制性股票(strike 填 0,无窗口)
# interval: monthly | quarterly | annual(归属频率)
# status: active 在职 | left 已离职(end_date=离职日,必填) | dead 已清算/关闭(end_date 必填)
# window_days: 离职后行权窗口(仅 option,缺省 90 天;rsu 留空)
# latest_price + price_date: 最新一轮/回购价及其日期——要么都填要么都不填,不填只数股份
company\tkind\tgrant_date\tshares\tstrike\tvest_years\tcliff_months\tinterval\tstatus\tend_date\twindow_days\tlatest_price\tprice_date\tnote
星尘科技\toption\t2022-03-01\t48000\t1.20\t4\t12\tquarterly\tleft\t2024-06-30\t90\t8.50\t2024-07-15\t2022 年加入的创业公司;2024 年年中裁员离开,90 天窗口没行权
巨潮科技\trsu\t2023-07-01\t24000\t0\t4\t12\tquarterly\tactive\t\t\t32.00\t2026-06-30\t现东家;按最近回购价记账
青苔智能\toption\t2024-09-20\t10000\t0.80\t4\t12\tmonthly\tactive\t\t\t\t\t天使轮,没有可参照的价格
深流科技\toption\t2025-10-01\t16000\t2.00\t4\t12\tquarterly\tactive\t\t\t6.00\t2026-04-01\t2025 年跳槽的新东家,pre-A 轮价
"""

EVENTS = """\
# 未兑现 · 事件账:一行一次行权/变现(可缺席=无事件)
# 列: date/company/event/shares/price/note
# event: exercise 行权(不填 price——行权价是授予条款 strike) | tender 变现落袋(price 必填)
# 作废不用记——离职/窗口关闭是算出来的,不是你填出来的
date\tcompany\tevent\tshares\tprice\tnote
2025-12-15\t巨潮科技\ttender\t2000\t31.00\t年度回购窗口卖了一批
2026-03-15\t青苔智能\texercise\t1000\t\t掏了 800 元行权,拿住不动
"""

SNAPSHOTS = [
    # (文件名, 命令, 允许的退出码集合)
    ("report.txt",
     ["report"],
     {4}),   # 星尘 BLOWN-WINDOW 红灯——这就是故事本身
    ("report-asof-20240910.txt",
     ["report", "--as-of", "2024-09-10"],
     {4}),   # 时间机器:窗口还剩 18 天,WINDOW-CLOSING 正在响
    ("exit.txt",
     ["exit"],
     {0}),
    ("exit-20261231.txt",
     ["exit", "--date", "2026-12-31"],
     {0}),
    ("clock.txt",
     ["clock"],
     {0}),
    ("validate.txt",
     ["validate"],
     {0}),
]


def build():
    for fname, content in (("grants.tsv", GRANTS), ("events.tsv", EVENTS)):
        with open(os.path.join(HERE, fname), "w", encoding="utf-8") as f:
            f.write(content)
    for fname, cmd, allowed in SNAPSHOTS:
        proc = subprocess.run([sys.executable, CLI] + cmd + ["--dir", HERE],
                              capture_output=True, text=True)
        if proc.returncode not in allowed:
            raise SystemExit("%s exited %d (expected one of %s)\n%s%s"
                             % (" ".join(cmd), proc.returncode, sorted(allowed),
                                proc.stdout, proc.stderr))
        with open(os.path.join(HERE, fname), "w", encoding="utf-8") as f:
            f.write(proc.stdout)
    print("examples rebuilt: 2 ledgers + %d snapshots" % len(SNAPSHOTS))


def check():
    ok = True
    for fname, content in (("grants.tsv", GRANTS), ("events.tsv", EVENTS)):
        path = os.path.join(HERE, fname)
        with open(path, encoding="utf-8") as f:
            actual = f.read()
        if actual != content:
            ok = False
            print("MISMATCH %s" % fname)
    for fname, cmd, allowed in SNAPSHOTS:
        path = os.path.join(HERE, fname)
        proc = subprocess.run([sys.executable, CLI] + cmd + ["--dir", HERE],
                              capture_output=True, text=True)
        with open(path, encoding="utf-8") as f:
            actual = f.read()
        if proc.returncode not in allowed:
            ok = False
            print("EXIT %s: got %d, expected one of %s"
                  % (fname, proc.returncode, sorted(allowed)))
        if proc.stdout != actual:
            ok = False
            print("MISMATCH %s" % fname)
    print("snapshot check: %s" % ("OK" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv[1:] else build())
