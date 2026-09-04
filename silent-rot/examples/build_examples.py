#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the silent-rot example ledger deterministically.

小陈's story (34 岁, ledger 2016-2026):
  - 2016: 46 (右下第一磨牙) 隐裂劈裂拔除 —— 他第一次知道牙会「没了」,
    然后把这件事忘了八年;
  - 2018: 36 (左下第一磨牙) 补牙 ¥280 —— 保持类投资的最后一年;
  - 2019: 38 (左下智齿) 阻生, 医嘱观察, 观察了 688 天, 三次冠周炎后拔除;
  - 2020: 唯一一次洗牙, 之后是长达五年的护理空白;
  - 2022-11-05: 单位体检口腔科一天记下两颗观察牙 —— 16 咬合面浅龋建议
    充填、36 充填体边缘欠密合建议观察, 两条医嘱都在, 人没有再出现;
  - 2025-10-02: 16 深夜痛醒, 牙髓炎, 浅龋拖成根管 —— 账面价差 ¥4,480;
  - 2026-03-14: 时隔 1,946 天第二次洗牙 (医嘱复查 36 仍未处理);
  - 2026-08-30: 体检又在 47 咬合面发现可疑浅龋 —— 新的观察挂上了.

Run from anywhere:
  python3 silent-rot/examples/build_examples.py           # write the TSV
  python3 silent-rot/examples/build_examples.py --check    # verify bytes
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# date, tooth (FDI; empty = full-mouth care event), event, cost, note
LEDGER = [
    ("2016-03-12", "46", "extract", "300", "隐裂劈裂 拔除"),
    ("2018-04-21", "36", "fill", "280", "远中颌面龋 树脂充填"),
    ("2019-06-20", "38", "found", "30", "阻生智齿 医嘱观察"),
    ("2020-11-15", "", "scaling", "300", "洗牙 抛光"),
    ("2021-05-08", "38", "extract", "800", "冠周炎第三次发作 拔除"),
    ("2022-11-05", "", "check", "0", "单位体检口腔科"),
    ("2022-11-05", "16", "found", "0", "咬合面浅龋 建议充填"),
    ("2022-11-05", "36", "found", "0", "充填体边缘欠密合 建议观察"),
    ("2023-08-19", "48", "found", "30", "垂直阻生 无症状 观察"),
    ("2024-01-15", "46", "implant", "8000", "种植一期 植体植入"),
    ("2024-06-28", "46", "implant", "4000", "种植二期 冠修复"),
    ("2025-10-02", "16", "rootcanal", "1200", "夜间痛确诊牙髓炎 根管治疗"),
    ("2025-11-20", "16", "crown", "3600", "根管后氧化锆全冠"),
    ("2026-03-14", "", "scaling", "350", "洗牙"),
    ("2026-03-14", "", "check", "50", "复查 医嘱:36 尽早充填"),
    ("2026-08-30", "47", "found", "30", "体检 咬合面可疑浅龋 医嘱观察"),
]


def build_tsv(header, rows):
    lines = ["\t".join(header)]
    for r in rows:
        lines.append("\t".join(r))
    return "\n".join(lines) + "\n"


def render():
    return build_tsv(
        ["date", "tooth", "event", "cost", "note"],
        [tuple(r) for r in LEDGER])


def main():
    check = "--check" in sys.argv
    content = render()
    target = os.path.join(HERE, "ledger.tsv")
    if check:
        if not os.path.exists(target):
            print("example ledger drift: ledger.tsv missing", file=sys.stderr)
            return 1
        with open(target, encoding="utf-8") as fh:
            got = fh.read()
        if got != content:
            print("example ledger drift: ledger.tsv", file=sys.stderr)
            return 1
        print("example ledger byte-identical")
        return 0
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
    print("wrote %s" % os.path.basename(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
