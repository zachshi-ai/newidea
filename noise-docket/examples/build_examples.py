#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the noise-docket example ledger deterministically.

小陈's story (31 天账本 2026-07-06 → 2026-08-05):
  - 常态: 楼上孩子的跑跳与拖桌椅, 晚间为主, 偶尔深夜(22:47 两次惊醒);
  - 07-11 起隔壁装修: 工作日上午合法施工, 但三个休息日(7-11/7-18/7-25)照干
    不误, 7-16 与 7-24 两个夜里还有电钻 —— 法定禁令时段五次在册;
  - 07-27 凌晨楼下棋牌室散场喧哗;
  - 08-01 物业上门调解, 楼上加装隔音垫, 之后骤减(2 次/27 分钟);
  - 近窗(最后 14 天)判级 SEVERE exit 4 —— 投诉正当其时;
  - verify 以 08-01 为界: 分钟天率 31.9 → 5.4, 降幅 83.1% IMPROVED。

Run from anywhere:
  python3 noise-docket/examples/build_examples.py           # write the TSV
  python3 noise-docket/examples/build_examples.py --check    # verify bytes
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# date, start (HH:MM), mins, source, strength (1-5), rec (Y/文件名/-), note
EVENTS = [
    ("2026-07-06", "19:40", "25", "脚步", "3", "-", "晚饭后孩子跑跳"),
    ("2026-07-08", "20:15", "30", "脚步", "3", "-", "晚间跑跳"),
    ("2026-07-09", "22:47", "44", "拖动", "4", "Y", "深夜拖桌椅 惊醒"),
    ("2026-07-11", "09:40", "95", "装修", "5", "Y", "隔壁开工 第一个休息日也在施工"),
    ("2026-07-13", "10:05", "100", "装修", "4", "-", "工作日上午 合法时段"),
    ("2026-07-15", "23:50", "30", "拖动", "4", "Y", "跨午夜 结束于次日 00:20 归属开始日"),
    ("2026-07-16", "22:30", "35", "装修", "4", "Y", "夜间电钻"),
    ("2026-07-18", "09:40", "70", "装修", "5", "Y", "又一个休息日 上午电钻"),
    ("2026-07-20", "10:10", "90", "装修", "3", "-", "工作日上午 合法时段"),
    ("2026-07-21", "22:47", "44", "拖动", "4", "-", "深夜拖桌椅"),
    ("2026-07-23", "19:50", "30", "脚步", "3", "-", "晚间跑跳"),
    ("2026-07-24", "22:05", "40", "装修", "5", "Y", "晚上电钻 夜间+禁令时段"),
    ("2026-07-25", "09:40", "60", "装修", "5", "Y", "周六上午电钻"),
    ("2026-07-27", "10:00", "45", "装修", "3", "-", "工作日上午 合法时段"),
    ("2026-07-27", "23:30", "40", "棋牌", "4", "-", "楼下棋牌室散场喧哗"),
    ("2026-07-28", "19:30", "12", "脚步", "2", "-", "晚间跑跳 较轻"),
    ("2026-07-30", "22:47", "40", "拖动", "4", "Y", "深夜拖桌椅"),
    ("2026-08-01", "11:20", "12", "宠物", "2", "-", "物业上门调解 楼上加装隔音垫 当日仅此动静"),
    ("2026-08-03", "21:30", "15", "脚步", "2", "-", "隔音垫后 唯一一次晚间跑动"),
]

HEADER = ["date", "start", "mins", "source", "strength", "rec", "note"]


def build_tsv(header, rows):
    lines = ["\t".join(header)]
    for r in rows:
        lines.append("\t".join(r))
    return "\n".join(lines) + "\n"


def render():
    return build_tsv(HEADER, [tuple(r) for r in EVENTS])


def main(argv):
    path = os.path.join(HERE, "events.tsv")
    data = render()
    if "--check" in argv:
        with open(path, "rb") as f:
            current = f.read().decode("utf-8")
        if current != data:
            sys.stderr.write("examples/events.tsv is stale; run build_examples.py\n")
            return 1
        print("examples/events.tsv byte-exact")
        return 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(data)
    print("wrote examples/events.tsv (%d events)" % len(EVENTS))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
