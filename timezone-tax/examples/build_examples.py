#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 timezone-tax 的示例数据（确定性，无随机数）.

产出：
  team-global.json      旧金山/柏林/班加罗尔/上海 四地团队（含真实夏令时规则）
  team-impossible.json  旧金山/柏林/奥克兰 + 09:00–18:00 核心时段 → 无解团队
  ledger-halfyear.json  team-global 固定 15:00 UTC 周会 × 52 周的税负账本
                        （2026-09-07 起，含两次夏令时切换）

用法：
  python3 examples/build_examples.py [输出目录]   # 缺省写回 examples/
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import timezone_tax as tzt  # noqa: E402

START_MONDAY = "2026-09-07"
SIMULATE_UTC = "15:00"
WEEKS = 52


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def build_team_global():
    return {
        "name": "Global Pod",
        "members": [
            {
                "name": "Alice · 旧金山",
                "offset_min": -480,
                "dst": [{"from": "03-08", "to": "11-01", "offset_min": -420}],
            },
            {
                "name": "Bruno · 柏林",
                "offset_min": 60,
                "dst": [{"from": "03-29", "to": "10-25", "offset_min": 120}],
            },
            {"name": "Chitra · 班加罗尔", "offset_min": 330},
            {"name": "Dawei · 上海", "offset_min": 480},
        ],
        "workdays": [0, 1, 2, 3, 4],
        "waking": {"start": "07:00", "end": "24:00"},
        "grid_min": 30,
    }


def build_team_impossible():
    return {
        "name": "Impossible Pod",
        "members": [
            {
                "name": "Alice · 旧金山",
                "offset_min": -480,
                "dst": [{"from": "03-08", "to": "11-01", "offset_min": -420}],
            },
            {
                "name": "Bruno · 柏林",
                "offset_min": 60,
                "dst": [{"from": "03-29", "to": "10-25", "offset_min": 120}],
            },
            {
                "name": "Ella · 奥克兰",
                "offset_min": 720,
                "dst": [{"from": "09-27", "to": "04-05", "offset_min": 780}],
            },
        ],
        "workdays": [0, 1, 2, 3, 4],
        "waking": {"start": "09:00", "end": "18:00"},
        "grid_min": 30,
    }


def build_ledger_halfyear(team):
    start = datetime.strptime(START_MONDAY, "%Y-%m-%d").date()
    utc_minute = tzt.parse_hhmm(SIMULATE_UTC)
    result = tzt.simulate_fixed(team, utc_minute, start, WEEKS)
    ledger = tzt.empty_ledger()
    for entry in result["entries"]:
        utc_dt = datetime.strptime(entry["bill"]["utc"], "%Y-%m-%d %H:%M")
        tzt.append_meeting(ledger, utc_dt,
                           tzt.bill_bills(entry["bill"]),
                           note="周一例会")
    return ledger


def main(outdir=None):
    outdir = outdir or os.path.dirname(os.path.abspath(__file__))
    team_global = build_team_global()
    write_json(os.path.join(outdir, "team-global.json"), team_global)
    write_json(os.path.join(outdir, "team-impossible.json"),
               build_team_impossible())
    write_json(os.path.join(outdir, "ledger-halfyear.json"),
               build_ledger_halfyear(team_global))
    print("示例已写入 %s" % outdir)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
