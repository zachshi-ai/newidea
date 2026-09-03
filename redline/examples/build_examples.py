#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 redline/examples/ 下的示例日志。

完全确定性（无随机数）：同样的代码永远产出 byte 相同的文件。
boombust.tsv 埋入的故事线（供 dogfood 测试作为已知答案）：

  第 1–8 周   稳定打底：周负荷 +2%/周，全落甜区（前三周基线校准中，不判区）
  第 9 周     报名比赛上头：再 +8%
  第 10 周    爆缸：周负荷翻倍（2550），ACWR ≈ 1.85 → 必须被标红
  第 11 周    疼痛减量：只剩一场轻松跑，ACWR 跌进退训区
  第 12 周    伤停开始：整周空白
  2026-07-21 之后空窗 15 天 → 工具必须检出一次伤停
  第 14–17 周 归队爬坡 ≈ 伤前周负荷的 40/60/80%，判据冻结期内不判区
"""

import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
START = __import__("datetime").date(2026, 5, 4)   # 周一


def d(week, weekday):
    """第 week 周（0 起）的 weekday（0=周一）。"""
    return START + __import__("datetime").timedelta(weeks=week, days=weekday)


def rows_for_week(week, mult, sessions):
    """sessions: [(weekday, minutes_base, rpe, name)]，按 mult 缩放分钟。"""
    out = []
    for wd, mins, rpe, name in sessions:
        m = int(round(mins * mult))
        if m <= 0:
            continue
        out.append((d(week, wd).isoformat(), name, m, rpe))
    return out


BASE = [(1, 45, 4, "轻松跑"),      # 周二
        (3, 40, 6, "节奏跑"),      # 周四
        (5, 75, 5, "长距离"),      # 周六
        (6, 30, 3, "恢复跑")]      # 周日

rows = []
# 第 1–8 周（w0–w7）：+2%/周
for w in range(8):
    rows += rows_for_week(w, 1.00 + 0.02 * w, BASE)
# 第 9 周（w8）：报名比赛，再 +8%
rows += rows_for_week(8, (1.00 + 0.02 * 7) * 1.08, BASE)
# 第 10 周（w9）：爆缸周 —— 硬拉到 2550 负荷
BOOM = [(1, 50, 6, "轻松跑"),
        (2, 70, 8, "间歇课"),
        (3, 60, 7, "节奏跑"),
        (5, 130, 7, "超长距离"),
        (6, 60, 6, "配速跑")]
rows += [(d(9, wd).isoformat(), name, mins, rpe)
         for wd, mins, rpe, name in BOOM]
# 第 11 周（w10）：疼痛减量
PAIN = [(1, 40, 5, "轻松跑"), (3, 30, 5, "恢复跑"), (5, 45, 5, "长距离")]
rows += [(d(10, wd).isoformat(), name, mins, rpe)
         for wd, mins, rpe, name in PAIN]
# 第 12 周（w11）：只剩周二一场，之后开始伤停
rows.append((d(11, 1).isoformat(), "轻松跑", 30, 3))
# w12 整周空白；2026-08-06（w13 周四）归队
rows.append((d(13, 3).isoformat(), "恢复跑", 35, 3))
# 第 15–17 周（w14–w16）：归队爬坡 ≈ 40/60/80% 伤前周负荷
REBUILD = {14: [(1, 40, 4, "轻松跑"), (3, 35, 4, "轻松跑"),
                (5, 45, 4, "长距离慢")],
           15: [(1, 45, 4, "轻松跑"), (3, 50, 5, "节奏跑"),
                (5, 70, 4, "长距离"), (6, 30, 3, "恢复跑")],
           16: [(1, 50, 4, "轻松跑"), (3, 55, 5, "节奏跑"),
                (5, 95, 5, "长距离"), (6, 35, 3, "恢复跑")]}
for w, sess in REBUILD.items():
    rows += [(d(w, wd).isoformat(), name, mins, rpe)
             for wd, mins, rpe, name in sess]


def write_log(path, rows):
    rows = sorted(rows)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("date\tactivity\tminutes\trpe\tnotes\n")
        for date_s, name, mins, rpe in rows:
            f.write("%s\t%s\t%d\t%d\t\n" % (date_s, name, mins, rpe))


def main():
    write_log(os.path.join(HERE, "boombust.tsv"), rows)
    minimal = [
        ("2026-08-03", "轻松跑", 40, 4),
        ("2026-08-05", "节奏跑", 35, 6),
        ("2026-08-08", "长距离", 70, 5),
        ("2026-08-10", "轻松跑", 45, 4),
        ("2026-08-12", "节奏跑", 40, 6),
        ("2026-08-15", "长距离", 80, 5),
    ]
    write_log(os.path.join(HERE, "minimal.tsv"), minimal)
    print("wrote boombust.tsv (%d rows) and minimal.tsv (%d rows)"
          % (len(rows), len(minimal)))


if __name__ == "__main__":
    main()
