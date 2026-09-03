#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 examples/ 下全部样例输出（日期全部钉死，逐字节可复现）。

用法：python3 examples/build_examples.py
每次运行会覆盖 8 份 sample-*.txt；CI 里由测试套件校验账本可解析。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "borrowed_silence.py")
LEDGER = os.path.join(HERE, "week.tsv")

COMMUTE = [
    # 通勤模式：地铁 ×2 + 盖噪耳机 1 小时 + 回家路上正常音量 45 分钟
    "2026-08-31\t07:50\tmetro\t0:50",
    "2026-08-31\t08:45\theadphone-loud\t1:00",
    "2026-08-31\t18:10\tmetro\t0:50",
    "2026-08-31\t19:05\theadphone-normal\t0:45",
]

LEDGER_ROWS = """\
# borrowed-silence 示例账本：地铁通勤耳机党小陈的一个月
# 列：日期  时间  声源  时长  [dB覆盖]  [耳塞NRR]
# symptom 行：日期  时间  symptom  症状名 —— 不计剂量，是身体开出的对账单
2026-08-12\t07:50\tmetro\t0:50
2026-08-12\t08:45\theadphone-loud\t1:00
2026-08-12\t18:10\tmetro\t0:50
2026-08-12\t19:05\theadphone-normal\t0:45
2026-08-13\t07:50\tmetro\t0:50
2026-08-13\t08:45\theadphone-loud\t1:00
2026-08-13\t18:10\tmetro\t0:50
2026-08-13\t19:05\theadphone-normal\t0:45
2026-08-15\t20:30\tktv\t2:30
2026-08-15\t23:00\tsymptom\tmuffled
2026-08-17\t07:50\tmetro\t0:50
2026-08-17\t08:45\theadphone-loud\t1:00
2026-08-17\t18:10\tmetro\t0:50
2026-08-17\t19:05\theadphone-normal\t0:45
2026-08-18\t07:50\tmetro\t0:50
2026-08-18\t08:45\theadphone-loud\t1:00
2026-08-18\t18:10\tmetro\t0:50
2026-08-18\t19:05\theadphone-normal\t0:45
2026-08-19\t07:50\tmetro\t0:50
2026-08-19\t08:45\theadphone-loud\t1:00
2026-08-19\t18:10\tmetro\t0:50
2026-08-19\t19:05\theadphone-normal\t0:45
2026-08-20\t07:50\tmetro\t0:50
2026-08-20\t08:45\theadphone-loud\t1:00
2026-08-20\t18:10\tmetro\t0:50
2026-08-20\t19:05\theadphone-normal\t0:45
2026-08-21\t07:50\tmetro\t0:50
2026-08-21\t08:45\theadphone-loud\t1:00
2026-08-21\t18:10\tmetro\t0:50
2026-08-21\t19:05\theadphone-normal\t0:45
2026-08-22\t20:30\tlivehouse\t2:30
2026-08-22\t23:50\tsymptom\ttinnitus
2026-08-24\t07:50\tmetro\t0:50
2026-08-24\t08:45\theadphone-loud\t1:00
2026-08-24\t18:10\tmetro\t0:50
2026-08-24\t19:05\theadphone-normal\t0:45
2026-08-25\t07:50\tmetro\t0:50
2026-08-25\t08:45\theadphone-loud\t1:00
2026-08-25\t18:10\tmetro\t0:50
2026-08-25\t19:05\theadphone-normal\t0:45
2026-08-26\t07:50\tmetro\t0:50
2026-08-26\t08:45\theadphone-loud\t1:00
2026-08-26\t18:10\tmetro\t0:50
2026-08-26\t19:05\theadphone-normal\t0:45
2026-08-27\t07:50\tmetro\t0:50
2026-08-27\t08:45\theadphone-loud\t1:00
2026-08-27\t18:10\tmetro\t0:50
2026-08-27\t19:05\theadphone-normal\t0:45
2026-08-28\t07:50\tmetro\t0:50
2026-08-28\t08:45\theadphone-loud\t1:00
2026-08-28\t18:10\tmetro\t0:50
2026-08-28\t19:05\theadphone-normal\t0:45
2026-08-30\t14:00\tcafe\t2:00
2026-08-31\t07:50\tmetro\t0:50
2026-08-31\t08:45\theadphone-loud\t1:00
2026-08-31\t18:10\tmetro\t0:50
2026-08-31\t19:05\theadphone-normal\t0:45
2026-09-01\t07:50\tmetro\t0:50
2026-09-01\t08:45\theadphone-loud\t1:00
2026-09-01\t18:10\tmetro\t0:50
2026-09-01\t19:05\theadphone-normal\t0:45
2026-09-02\t07:50\tmetro\t0:50
2026-09-02\t08:45\theadphone-loud\t1:00
2026-09-02\t18:10\tmetro\t0:50
2026-09-02\t19:05\theadphone-normal\t0:45
2026-09-03\t07:50\tmetro\t0:50
2026-09-03\t08:45\theadphone-loud\t1:00
2026-09-03\t18:10\tmetro\t0:50
2026-09-03\t19:05\theadphone-normal\t0:45
2026-09-04\t07:50\tmetro\t0:50
2026-09-04\t08:45\theadphone-loud\t1:00
2026-09-04\t18:10\tmetro\t0:50
2026-09-04\t19:05\theadphone-normal\t0:45
2026-09-05\t20:30\tlivehouse\t2:30
2026-09-05\t23:40\tsymptom\ttinnitus
2026-09-06\t14:00\tcafe\t1:30
"""

# (文件名, 参数, 预期退出码) —— 退出码写进 README 的样例表
CASES = [
    ("sample-day-red.txt",
     ["day", LEDGER, "--date", "2026-09-05"], 4),
    ("sample-day-green.txt",
     ["day", LEDGER, "--date", "2026-09-06"], 0),
    ("sample-week.txt",
     ["week", LEDGER, "--end", "2026-09-06"], 4),
    ("sample-plan-plugs.txt",
     ["plan", LEDGER, "livehouse", "2:30", "--week-of", "2026-09-10"], 4),
    ("sample-plan-fits.txt",
     ["plan", LEDGER, "gym-class", "1:00", "--week-of", "2026-09-10"], 0),
    ("sample-lifetime.txt",
     ["lifetime", LEDGER], 0),
    ("sample-sources.txt",
     ["sources"], 0),
    ("sample-validate.txt",
     ["validate", LEDGER], 0),
]


def main() -> int:
    with open(LEDGER, "w", encoding="utf-8") as fh:
        fh.write(LEDGER_ROWS)
    for name, argv, expected in CASES:
        proc = subprocess.run([sys.executable, CLI] + argv,
                              capture_output=True, text=True)
        if proc.returncode != expected:
            print("FAIL %s: exit %d (expected %d)\n%s"
                  % (name, proc.returncode, expected, proc.stderr), file=sys.stderr)
            return 1
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(proc.stdout)
        print("ok %s (exit %d)" % (name, proc.returncode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
