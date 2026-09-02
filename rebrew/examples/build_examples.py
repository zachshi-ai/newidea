#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 rebrew 示例冲煮日志（固定 seed，可重建）。

realistic.tsv —— 59 条真实感合成数据，埋入两个已知效应 + σ≈0.5 噪声：
  * 水温每 +2°C 评分 +0.9（埃塞豆的主效应，dogfood 断言它应登顶旋钮排行）
  * 研磨每 +2 档评分 -0.36（越细越过萃）
  * 15:16 粉水比略差于 1:15（-0.5），1:14 更差
  判定工具是否"挖得出真因果"，就看它能否恢复这些方向。
minimal.tsv —— 3 条记录，其中 2 条同配方，最小可用地演示复现半径。

运行：python3 rebrew/examples/build_examples.py
"""

import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent
RNG = random.Random(20260902)

HEADER = ["date", "bean", "dose_g", "water_g", "temp_c",
          "grind", "time_s", "rating", "notes"]


def clamp_rating(x):
    return round(max(0.0, min(10.0, x)), 1)


def ethiopia_true(temp, grind, water):
    """埃塞豆的"真实"评分函数（工具不知道，dogfood 靠它校准断言）。"""
    base = 6.2
    base += 0.45 * (temp - 90)          # 水温主效应：+0.9 分 / 2°C
    base -= 0.18 * (grind - 4)          # 研磨副作用：-0.36 分 / 2 档
    if water == 225:
        base += 0.5                     # 1:15 是这支豆的最优比例
    else:
        base -= 0.5
    return base


def gen_ethiopia(start):
    """49 条埃塞记录：参数散开探索 + 若干同配方重复组。"""
    rows = []
    day = start
    # 1) 散开探索：40 条，配方随机游走
    for _ in range(40):
        temp = RNG.choice([90, 92, 94, 96])
        grind = RNG.choice([4, 6, 8, 10])
        water = RNG.choice([210, 225, 240])
        time_s = RNG.choice([135, 140, 145, 150, 155])
        rating = clamp_rating(ethiopia_true(temp, grind, water)
                              + RNG.gauss(0, 0.5))
        rows.append((day, "Ethiopia Chelbesa", 15, water, temp,
                     grind, time_s, rating, "探索"))
        day += timedelta(days=1 + RNG.randrange(2))
    # 2) 同配方重复组：复现半径的数据来源
    repeats = [
        (94, 6, 225, 3),   # 用户反复回到的高分配方
        (92, 8, 225, 2),
        (90, 6, 210, 2),
        (96, 8, 240, 2),
    ]
    for temp, grind, water, n in repeats:
        for _ in range(n):
            time_s = RNG.choice([140, 145, 150])
            rating = clamp_rating(ethiopia_true(temp, grind, water)
                                  + RNG.gauss(0, 0.5))
            rows.append((day, "Ethiopia Chelbesa", 15, water, temp,
                         grind, time_s, rating, "复冲"))
            day += timedelta(days=1)
    return rows


def gen_colombia(start):
    """10 条哥伦比亚记录：另一支豆，证明主域自动选择会避开它。"""
    rows = []
    day = start
    for _ in range(10):
        temp = RNG.choice([88, 90, 92])
        grind = RNG.choice([6, 8])
        water = RNG.choice([225, 240])
        time_s = RNG.choice([140, 150, 160])
        rating = clamp_rating(6.0 - 0.10 * (temp - 88) + RNG.gauss(0, 0.6))
        rows.append((day, "Colombia Huila", 15, water, temp,
                     grind, time_s, rating, ""))
        day += timedelta(days=2)
    return rows


def write_tsv(path, rows, comment):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# %s\n" % comment)
        fh.write("\t".join(HEADER) + "\n")
        for row in rows:
            d, bean, dose, water, temp, grind, time_s, rating, notes = row
            fh.write("\t".join([
                d.isoformat(), bean, "%g" % dose, "%g" % water,
                "%g" % temp, "%g" % grind, "%g" % time_s,
                "%.1f" % rating, notes]) + "\n")
    print("wrote %s (%d rows)" % (path, len(rows)))


def main():
    ethiopia = gen_ethiopia(date(2026, 3, 1))
    colombia = gen_colombia(date(2026, 3, 20))
    rows = sorted(ethiopia + colombia, key=lambda r: r[0].isoformat())
    write_tsv(OUT / "realistic.tsv", rows,
              "示例冲煮日志（合成，seed=20260902）：埃塞 49 条埋水温+/研磨- 效应，σ≈0.5")

    minimal = [
        (date(2026, 8, 1), "Ethiopia Chelbesa", 15, 225, 93, 6, 145, 7.0, "酸质明亮"),
        (date(2026, 8, 2), "Ethiopia Chelbesa", 15, 225, 93, 6, 150, 8.0, "第二天更稳"),
        (date(2026, 8, 3), "Ethiopia Chelbesa", 15, 225, 95, 6, 148, 7.5, "水温+2 试试"),
    ]
    write_tsv(OUT / "minimal.tsv", minimal,
              "最小可用日志：3 条，其中 2 条同配方——复现半径由此而来")


if __name__ == "__main__":
    main()
