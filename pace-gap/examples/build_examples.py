#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the pace-gap example ledger deterministically.

小北's story (考研, exam 2026-12-19):
  - March honeymoon: 8 chapters closed in 28 days (his proven peak),
  - April-July collapse: 2 chapters in three and a half months,
  - late-August wake-up: 3 chapters in the last 28 days,
  - english over-fed (56% of minutes, 20% of weight), politics never
    started, two stalled (open) chapters in math and major.

Run from anywhere:
  python3 pace-gap/examples/build_examples.py           # write the TSVs
  python3 pace-gap/examples/build_examples.py --check    # verify bytes
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# subject, order, chapter, weight (weights sum to the exam's 500 points)
SYLLABUS = [
    ("math", 1, "高数-函数极限", "12.5"),
    ("math", 2, "高数-一元微分", "12.5"),
    ("math", 3, "高数-一元积分", "12.5"),
    ("math", 4, "高数-微分方程", "12.5"),
    ("math", 5, "高数-多元微分", "12.5"),
    ("math", 6, "高数-重积分", "12.5"),
    ("math", 7, "高数-级数", "12.5"),
    ("math", 8, "线代-矩阵", "12.5"),
    ("math", 9, "线代-向量组", "12.5"),
    ("math", 10, "概率-随机变量", "12.5"),
    ("math", 11, "概率-数字特征", "12.5"),
    ("math", 12, "概率-大数定律", "12.5"),
    ("english", 1, "词汇基础", "10"),
    ("english", 2, "长难句", "10"),
    ("english", 3, "阅读方法论", "10"),
    ("english", 4, "阅读真题基础", "10"),
    ("english", 5, "阅读真题强化", "10"),
    ("english", 6, "写作框架", "10"),
    ("english", 7, "翻译", "10"),
    ("english", 8, "完形填空", "10"),
    ("english", 9, "新题型", "10"),
    ("english", 10, "整卷模拟", "10"),
    ("politics", 1, "马原-唯物辩证法", "10"),
    ("politics", 2, "马原-认识论", "10"),
    ("politics", 3, "毛中特-理论体系", "10"),
    ("politics", 4, "毛中特-新时代", "10"),
    ("politics", 5, "史纲-旧民主主义", "10"),
    ("politics", 6, "史纲-新民主主义", "10"),
    ("politics", 7, "思修-理想信念", "10"),
    ("politics", 8, "思修-法治观", "10"),
    ("politics", 9, "时政-上半年", "10"),
    ("politics", 10, "时政-全年盘点", "10"),
    ("major", 1, "数据结构-线性表", "18.75"),
    ("major", 2, "数据结构-树与图", "18.75"),
    ("major", 3, "组成原理-CPU", "18.75"),
    ("major", 4, "组成原理-存储", "18.75"),
    ("major", 5, "操作系统-进程", "18.75"),
    ("major", 6, "操作系统-内存", "18.75"),
    ("major", 7, "网络-TCP", "18.75"),
    ("major", 8, "网络-路由", "18.75"),
]

# date, subject, order, minutes, status (open = stalled chapter, never done)
STUDY = [
    # -- March honeymoon: math ch1-5 + english ch1-3 close in 28 days
    ("2026-03-02", "math", 1, "140", "done"),
    ("2026-03-03", "english", 1, "160", ""),
    ("2026-03-04", "math", 1, "150", "done"),
    ("2026-03-05", "math", 2, "130", ""),
    ("2026-03-06", "english", 1, "170", "done"),
    ("2026-03-07", "math", 2, "160", "done"),
    ("2026-03-09", "math", 3, "150", ""),
    ("2026-03-09", "english", 2, "165", ""),
    ("2026-03-11", "math", 3, "140", "done"),
    ("2026-03-12", "english", 2, "175", "done"),
    ("2026-03-12", "math", 4, "150", ""),
    ("2026-03-14", "english", 3, "170", ""),
    ("2026-03-14", "math", 4, "155", "done"),
    ("2026-03-16", "math", 5, "140", ""),
    ("2026-03-18", "english", 3, "180", ""),
    ("2026-03-18", "math", 5, "145", ""),
    ("2026-03-21", "math", 5, "150", "done"),
    ("2026-03-24", "english", 3, "165", "done"),
    # -- April-July collapse: english ch4-5 only, math ch7 stalls open
    ("2026-04-20", "english", 4, "175", ""),
    ("2026-05-06", "english", 4, "170", "done"),
    ("2026-05-18", "english", 5, "180", ""),
    ("2026-06-02", "english", 5, "175", "done"),
    ("2026-06-15", "math", 7, "90", "open"),
    ("2026-06-22", "math", 7, "60", "open"),
    # -- late-August wake-up: english ch6-7 + math ch6 close
    ("2026-08-03", "english", 6, "170", ""),
    ("2026-08-10", "major", 1, "40", "open"),
    ("2026-08-12", "english", 6, "180", "done"),
    ("2026-08-15", "math", 6, "120", ""),
    ("2026-08-17", "major", 1, "30", "open"),
    ("2026-08-20", "math", 6, "135", "done"),
    ("2026-08-22", "english", 7, "175", ""),
    ("2026-08-24", "major", 2, "45", "open"),
    ("2026-08-26", "english", 7, "170", ""),
    ("2026-08-30", "english", 7, "165", "done"),
    # -- September 5th evening: he opens the ledger
    ("2026-09-05", "math", 7, "50", "open"),
]


def build_tsv(header, rows):
    lines = ["\t".join(header)]
    lines.extend("\t".join(r) for r in rows)
    return "\n".join(lines) + "\n"


def render():
    syl = build_tsv(
        ["subject", "order", "chapter", "weight"],
        [(s, str(o), name, w) for s, o, name, w in SYLLABUS])
    study = build_tsv(
        ["date", "subject", "order", "minutes", "status"],
        [(d, s, str(o), m, st) for d, s, o, m, st in STUDY])
    return syl, study


def main():
    check = "--check" in sys.argv
    syl, study = render()
    targets = {
        os.path.join(HERE, "syllabus.tsv"): syl,
        os.path.join(HERE, "study.tsv"): study,
    }
    if check:
        bad = []
        for path, want in targets.items():
            if not os.path.exists(path):
                bad.append("%s missing" % path)
                continue
            with open(path, encoding="utf-8") as fh:
                got = fh.read()
            if got != want:
                bad.append("%s drifted" % path)
        if bad:
            print("example ledger drift: %s" % "; ".join(bad),
                  file=sys.stderr)
            return 1
        print("example ledger byte-identical")
        return 0
    for path, content in targets.items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        print("wrote %s" % os.path.basename(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
