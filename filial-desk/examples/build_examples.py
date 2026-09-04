#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the filial-desk example ledger and report snapshots.

The demo ledger is one year (52.0 ledger weeks, 2025-09-01 Monday ->
2026-08-30 Sunday) of one son's unpaid IT department service for two
parents and three devices: 21 tickets, 505 minutes.  A 弹广告 chain on
 Dad's aging 红米 9A that relapsed four times and never got taught; a
WiFi chain where the "taught" claim did not survive 38 days; a 话费
case that relapsed exactly 90 days later (on the window line); three
claims that held and were verified; two claims still too young to
judge; and one ticket that ended "我直接替她调好了" — fixed, not taught.

All windows are anchored to the ledger itself — no --today, no wall
clock — so every snapshot is byte-reproducible on any machine, any day.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "filial_desk.py")
LEDGER = os.path.join(HERE, "ledger.tsv")
TUTORIALS = os.path.join(HERE, "tutorials.txt")

HEADER = "date\tparent\tdevice\ttopic\tminutes\tmode\ttaught\tclock\tnote\n"

# (date, parent, device, topic, minutes, mode, taught, clock, note)
ROWS = [
    ("2025-09-01", "爸", "红米 9A", "手机弹广告", "35", "视频", "no", "",
     "点开了一条「领红包」链接，满屏弹窗"),
    ("2025-09-28", "妈", "iPhone 12", "字体太小", "15", "视频", "yes", "",
     "教了辅助功能里的更大字体，妈说记住了"),
    ("2025-10-02", "爸", "红米 9A", "拍照糊", "15", "电话", "no", "",
     "教了点按对焦，爸说是镜头脏了擦擦"),
    ("2025-10-13", "妈", "iPhone 12", "WiFi 断网", "25", "视频", "yes", "",
     "教了重启路由器，妈说这有什么难的"),
    ("2025-11-03", "爸", "红米 9A", "手机弹广告", "25", "远程", "no", "",
     "又中招了，这次装了个拦截工具"),
    ("2025-11-11", "妈", "iPhone 12", "抢红包手慢", "12", "视频", "yes", "",
     "双十一前教了清后台，手速上来了"),
    ("2025-11-20", "妈", "iPhone 12", "WiFi 断网", "20", "电话", "no", "21:40",
     "又断了，这回远程没搞定，运营商上门"),
    ("2025-12-08", "爸", "红米 9A", "话费莫名变多", "45", "电话", "no", "19:05",
     "查出一个定制包月，退订了"),
    ("2026-01-12", "爸", "红米 9A", "手机弹广告", "40", "电话", "no", "07:30",
     "早上一睁眼就打来，通勤路上指导卸载"),
    ("2026-01-20", "妈", "iPad Air", "电池掉得快", "25", "远程", "", "",
     "电池老化，如实告知，这个没得教"),
    ("2026-02-08", "妈", "iPhone 12", "WiFi 断网", "30", "现场", "no", "",
     "回家现场处理，路由器老化换新"),
    ("2026-02-25", "爸", "红米 9A", "手机内存满", "40", "视频", "no", "",
     "教了半天清理，最后还是远程替他清的"),
    ("2026-03-08", "爸", "红米 9A", "话费莫名变多", "30", "现场", "no", "",
     "又多了，现场查：他又顺手点订了包月"),
    ("2026-04-02", "爸", "红米 9A", "手机弹广告", "30", "视频", "no", "23:10",
     "深夜来电，拦截工具早被他自己卸了"),
    ("2026-04-15", "爸", "红米 9A", "手环同步失败", "20", "远程", "no", "",
     "蓝牙重配对，手环说明书没带在身边"),
    ("2026-05-06", "妈", "iPhone 12", "验证码收不到", "15", "电话", "yes", "09:15",
     "教了短信拦截设置，这次真学会了"),
    ("2026-05-20", "爸", "红米 9A", "来电没声音", "10", "电话", "yes", "08:00",
     "静音拨片——物理开关，教一遍就会"),
    ("2026-06-18", "爸", "红米 9A", "手机弹广告", "25", "远程", "no", "14:45",
     "会议间隙处理的，拦截工具又没了"),
    ("2026-06-30", "妈", "iPhone 12", "手机存储满", "18", "视频", "yes", "",
     "教了照片删重，当场学会"),
    ("2026-07-01", "妈", "iPhone 12", "微信视频没声音", "20", "视频", "yes", "12:30",
     "教了静音开关，占用午休时间"),
    ("2026-08-30", "妈", "iPhone 12", "字体太小", "10", "电话", "no", "",
     "大半年过去又忘了，直接远程替她调好——修好不是教会"),
]

TUTORIALS_TEXT = """# 写过的图文教程（一行一个，题材名与账本归一化后需一致）
手机弹广告
"""

SNAPSHOTS = [
    ("sample-report.txt",
     ["report", "filial-desk/examples/ledger.tsv"]),
    ("sample-report-hourly.txt",
     ["report", "filial-desk/examples/ledger.tsv", "--hourly", "50"]),
    ("sample-relapse.txt",
     ["relapse", "filial-desk/examples/ledger.tsv"]),          # exit 0
    ("sample-fleet.txt",
     ["fleet", "filial-desk/examples/ledger.tsv",
      "--residual", "红米 9A:200", "--hourly", "50"]),          # exit 4: SUNK
    ("sample-curriculum.txt",
     ["curriculum", "filial-desk/examples/ledger.tsv"]),
    ("sample-curriculum-debt.txt",
     ["curriculum", "filial-desk/examples/ledger.tsv",
      "--tutorials", "filial-desk/examples/tutorials.txt"]),    # exit 4: debt
    ("sample-simulate.txt",
     ["simulate", "filial-desk/examples/ledger.tsv", "cure",
      "--topic", "手机弹广告", "--hourly", "50"]),
    ("sample-simulate-retire.txt",
     ["simulate", "filial-desk/examples/ledger.tsv", "retire",
      "--device", "红米 9A", "--hourly", "50"]),
    ("sample-validate.txt",
     ["validate", "filial-desk/examples/ledger.tsv"]),
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
        with open(TUTORIALS, "w", encoding="utf-8") as fh:
            fh.write(TUTORIALS_TEXT)
    else:
        if open(LEDGER, encoding="utf-8").read() != text:
            failures.append("ledger.tsv drifted from the generator")
        if open(TUTORIALS, encoding="utf-8").read() != TUTORIALS_TEXT:
            failures.append("tutorials.txt drifted from the generator")

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
