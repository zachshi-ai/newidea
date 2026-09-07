#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the due-dose example ledgers + snapshots (byte-reproducible).

`python3 build_examples.py`         -> (re)write the TSVs and every snapshot
`python3 build_examples.py --check` -> verify each file matches, byte for byte

The snapshots are produced by the CLI itself. There is no wall clock anywhere:
as-of defaults to the latest date on file, and every snapshot pins its own
--as-of / --by, so the same ledgers yield the same bytes on any machine, on
any day. The sample story's red lamp (exit 4 = 搬家丢的两针已经超龄 13 个月)
is the story — expected output, not an error.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(os.path.dirname(HERE), "due_dose.py")

KIDS = """\
# 欠针 · 孩子名册:一行一个孩子(接种记录跟着人走)
# 列: kid/birth/note
kid\tbirth\tnote
小满\t2023-03-15\t2023 年春出生;2024 年秋从杭州搬到成都
"""

DOSES = """\
# 欠针 · 接种账:一行一针,产品名照本子抄(词表自动归一,五联=百白破+脊灰+hib)
# 列: date/kid/product/price/note
# price 留空 = 一类(免费);填了 = 自费,进 paid 账——价签就是分类
date\tkid\tproduct\tprice\tnote
2023-03-15\t小满\t乙肝疫苗\t\t出生第一针,产科打的
2023-03-15\t小满\t卡介苗\t\t同天,左臂
2023-04-18\t小满\t乙肝疫苗\t\t1 月龄
2023-05-20\t小满\t五联疫苗\t628\t自费选了五联,一顶三
2023-06-20\t小满\t五联疫苗\t628\t第 2 针
2023-07-21\t小满\t五联疫苗\t628\t第 3 针
2023-09-20\t小满\t乙肝疫苗\t\t6 月龄
2023-09-25\t小满\tA群流脑多糖疫苗\t\t6 月龄流脑
2023-11-17\t小满\t麻腮风疫苗\t\t8 月龄,与乙脑同天两针
2023-11-17\t小满\t乙脑减毒活疫苗\t\t同天另一条胳膊
2023-11-25\t小满\tEV71疫苗\t268\t手足口第 1 剂,第 2 剂一直没约上
2023-12-22\t小满\tA群流脑多糖疫苗\t\t9 月龄流脑
2024-03-20\t小满\t水痘减毒活疫苗\t172\t1 岁水痘第 1 剂
2024-05-21\t小满\t五联疫苗\t628\t18 月龄第 4 针——这支把 4 岁那剂口服脊灰也换掉了
2024-10-09\t小满\t流感疫苗\t159\t当年秋天的流感针
2025-03-20\t小满\t乙脑减毒活疫苗\t\t2 岁乙脑,成都社区打的
2025-10-10\t小满\t流感疫苗\t168\t今年的流感针
"""

SNAPSHOTS = [
    # (文件名, 命令, 允许的退出码集合)
    ("report.txt",
     ["report"],
     {4}),   # 麻腮风/甲肝超龄欠针——搬家丢的两针,这就是故事本身
    ("gaps.txt",
     ["gaps"],
     {4}),
    ("catchup.txt",
     ["catchup", "--by", "2026-08-31", "--label", "幼儿园入园查验"],
     {0}),   # 排得下: 欠的三剂并种两次,余量 169 天
    ("paid.txt",
     ["paid"],
     {0}),   # EV71 半程黄灯
    ("report-asof-20240801.txt",
     ["report", "--as-of", "2024-08-01"],
     {0}),   # 时间机器:搬家前一个月,一针不欠——欠账是搬家搬丢的
    ("validate.txt",
     ["validate"],
     {0}),
]


def build():
    for fname, content in (("kids.tsv", KIDS), ("doses.tsv", DOSES)):
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
    for fname, content in (("kids.tsv", KIDS), ("doses.tsv", DOSES)):
        with open(os.path.join(HERE, fname), encoding="utf-8") as f:
            if f.read() != content:
                ok = False
                print("MISMATCH %s" % fname)
    for fname, cmd, allowed in SNAPSHOTS:
        proc = subprocess.run([sys.executable, CLI] + cmd + ["--dir", HERE],
                              capture_output=True, text=True)
        with open(os.path.join(HERE, fname), encoding="utf-8") as f:
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
