#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the search-tax example ledger and report snapshots.

The demo ledger is one household's 8 ledger weeks (2026-06-30 to
2026-08-21): a 门禁卡 that kept vanishing until it got a tray by the
door, a 剪刀 family that has quietly reached three, charging cables
bought twice because the first one "was lost" (it was in the sofa),
and a 指甲刀 whose fixed home is too new to judge. 28 rows: 21 hunts
(96 minutes), 5 duplicate buys (¥126.60), 2 fix rows.

All windows are anchored to the ledger itself — no --today, no wall
clock — so every snapshot is byte-reproducible on any machine, any day.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "search_tax.py")
LEDGER = os.path.join(HERE, "lostfound.tsv")
WAGE = ["--wage", "40"]

HEADER = "date\tevent\titem\tminutes\tplace\tamount\tnote\n"

# (date, event, item, minutes, place, amount, note)
ROWS = [
    ("2026-06-30", "search", "户口本", "12", "五斗柜最底层", "", "办护照前夜"),
    ("2026-07-01", "search", "剪刀", "3", "抽屉", "", ""),
    ("2026-07-02", "search", "门禁卡", "5", "沙发缝", "", ""),
    ("2026-07-05", "search", "雨伞", "6", "阳台角落", "", ""),
    ("2026-07-08", "search", "充电线", "10", "-", "", "出门前找，没找到"),
    ("2026-07-08", "buy", "充电线", "", "", "29.9", "网上再买一根"),
    ("2026-07-09", "search", "门禁卡", "3", "包侧袋", "", ""),
    ("2026-07-11", "search", "灭火器", "8", "-", "", "物业查消防前夜"),
    ("2026-07-12", "search", "灭火器", "1", "储物箱底", "", "第二天搬箱子找到"),
    ("2026-07-15", "search", "门禁卡", "7", "-", "", "迟到 20 分钟"),
    ("2026-07-15", "buy", "门禁卡", "", "", "30", "去物业补办"),
    ("2026-07-16", "search", "门禁卡", "1", "外套口袋", "", "旧卡自己现形，白补办了"),
    ("2026-07-19", "search", "剪刀", "6", "-", "", "拆快递找不到剪刀"),
    ("2026-07-19", "buy", "剪刀", "", "", "19.9", "找不到就下了单"),
    ("2026-07-20", "search", "剪刀", "1", "抽屉", "", "新剪刀还没到，旧的现形"),
    ("2026-07-20", "fix", "门禁卡", "", "玄关托盘", "", "口袋不配拥有它"),
    ("2026-07-22", "search", "充电线", "2", "床头柜", "", ""),
    ("2026-07-25", "search", "指甲刀", "4", "药盒", "", ""),
    ("2026-07-28", "search", "老花镜", "5", "头顶", "", "找了半天在自己头上"),
    ("2026-08-02", "search", "保温杯盖", "5", "碗架", "", ""),
    ("2026-08-05", "buy", "充电线", "", "", "29.9", "又以为丢了，再买一根"),
    ("2026-08-08", "search", "门禁卡", "2", "玄关托盘", "", "它真在托盘里"),
    ("2026-08-10", "buy", "卷尺", "", "", "16.9", "工具箱常备第二把，无寻物史"),
    ("2026-08-12", "search", "剪刀", "4", "抽屉", "", ""),
    ("2026-08-16", "search", "保温杯盖", "2", "-", "", ""),
    ("2026-08-18", "search", "指甲刀", "3", "药盒", "", ""),
    ("2026-08-20", "fix", "指甲刀", "", "药盒挂钩", "", ""),
    ("2026-08-21", "search", "充电线", "6", "沙发缝", "", "第一根，一直都在"),
]

SNAPSHOTS = [
    ("sample-report.txt",
     ["report", "search-tax/examples/lostfound.tsv"]),
    ("sample-report-wage.txt",
     ["report", "search-tax/examples/lostfound.tsv", "--wage", "40"]),
    ("sample-repeat.txt",
     ["repeat", "search-tax/examples/lostfound.tsv"]),     # exit 4: 3 offenders
    ("sample-dup.txt",
     ["dup", "search-tax/examples/lostfound.tsv"]),
    ("sample-place.txt",
     ["place", "search-tax/examples/lostfound.tsv"]),
    ("sample-simulate.txt",
     ["simulate", "search-tax/examples/lostfound.tsv", "fix", "--item", "剪刀", "--wage", "40"]),
    ("sample-validate.txt",
     ["validate", "search-tax/examples/lostfound.tsv"]),
]


def ledger_text():
    lines = [HEADER]
    for row in ROWS:
        lines.append("\t".join(row) + "\n")
    return "".join(lines)


def run_cli(argv):
    proc = subprocess.run([sys.executable, CLI] + argv,
                          capture_output=True, text=True,
                          cwd=os.path.join(HERE, "..", ".."))
    return proc.stdout, proc.returncode


def main():
    check = "--check" in sys.argv
    text = ledger_text()
    failures = []
    if not check:
        with open(LEDGER, "w", encoding="utf-8") as fh:
            fh.write(text)
    elif open(LEDGER, encoding="utf-8").read() != text:
        failures.append("lostfound.tsv drifted from the generator")

    for name, argv in SNAPSHOTS:
        out, code = run_cli(argv)
        expected = out + ("[exit %d]\n" % code if code != 0 else "")
        path = os.path.join(HERE, name)
        if check:
            with open(path, encoding="utf-8") as fh:
                if fh.read() != expected:
                    failures.append("%s drifted" % name)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(expected)

    if failures:
        for line in failures:
            print("DRIFT: %s" % line)
        return 1
    print("examples %s" % ("verified byte-exact" if check else "rebuilt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
