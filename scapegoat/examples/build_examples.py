#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the scapegoat example diary and report snapshots.

The demo diary is one person's 16 weeks of migraine bookkeeping
(2026-05-04 to 2026-08-23): 88 recorded days out of 112, 17 attacks
(4 of them with no recorded exposure), 12 suspects. The story the
margins are tuned to tell: one conviction (缺睡), one near-conviction
that Bonferroni blocks (空腹), five suspects on the watchlist, one
still at large (陈年奶酪, exposed twice), and four acquittals led by
red-wine — the suspect that intuition convicted on a single night.

  python3 build_examples.py            # write diary + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import datetime as dt
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "scapegoat.py")
DIARY = os.path.join(HERE, "diary.tsv")
TODAY = "2026-08-24"

FIRST = dt.date(2026, 5, 4)
LAST = dt.date(2026, 8, 23)

# 17 个发作日：13 个带暴露，4 个无暴露发作（名单外的凶手）。
ATTACK_DAYS = {
    "2026-05-07": "缺睡,红酒",
    "2026-05-13": "缺睡,空腹,压力",
    "2026-05-19": "缺睡,巧克力",
    "2026-05-25": "缺睡,压力,长屏幕",
    "2026-05-27": "-",
    "2026-05-30": "缺睡,空腹,脱水,咖啡因",
    "2026-06-05": "缺睡,巧克力,味精",
    "2026-06-11": "缺睡,天气骤变,压力",
    "2026-06-16": "缺睡,空腹,味精,加工肉",
    "2026-06-24": "空腹,天气骤变",
    "2026-06-29": "-",
    "2026-07-02": "压力,咖啡因",
    "2026-07-10": "巧克力,长屏幕,咖啡因",
    "2026-07-21": "压力,咖啡因",
    "2026-07-26": "-",
    "2026-08-02": "陈年奶酪,咖啡因",
    "2026-08-14": "-",
}
ATTACK_NOTES = {
    "2026-05-07": "先兆：闪光 20 分钟",
    "2026-08-02": "夜里痛醒",
}

# 24 个无记录日：账本只记声称的事实，缺席不进任何分母。
ABSENT_DAYS = {
    "2026-05-09", "2026-05-10", "2026-05-17", "2026-05-24",
    "2026-05-31", "2026-06-07", "2026-06-14", "2026-06-15",
    "2026-06-21", "2026-06-28", "2026-07-05", "2026-07-06",
    "2026-07-12", "2026-07-19", "2026-07-20", "2026-07-27",
    "2026-08-03", "2026-08-04", "2026-08-09", "2026-08-10",
    "2026-08-16", "2026-08-17", "2026-08-22", "2026-08-23",
}

# 对照日（无发作）的补货配额：与攻击日的暴露合并后恰为目标边际。
# 目标 2×2（暴露天数, 暴露日发作）见下方 EXPECTED。
CLEAN_QUOTA = {
    "缺睡": 6,
    "空腹": 4,
    "压力": 13,
    "味精": 3,
    "天气骤变": 5,
    "脱水": 3,
    "红酒": 9,
    "巧克力": 13,
    "咖啡因": 20,
    "长屏幕": 10,
    "陈年奶酪": 1,
    "加工肉": 2,
}

# 目标边际：trigger -> (E 暴露天数, a_e 暴露日发作)。构建后逐一断言。
EXPECTED = {
    "缺睡": (14, 8),      # ✗ 定罪：57.1% vs 12.2%，lift 4.70
    "空腹": (8, 4),       # ▲ 嫌疑重大：过单人线，Bonferroni 拦下
    "压力": (18, 5),      # ○ 监视名单：lift 1.6 不显著
    "味精": (5, 2),       # ○ 监视名单：lift 2.2 达线但 p 不显著
    "天气骤变": (7, 2),   # ○ 监视名单
    "脱水": (4, 1),       # ○ 监视名单：样本薄
    "加工肉": (3, 1),     # ○ 监视名单：样本薄
    "陈年奶酪": (2, 1),   # ◌ 在逃：暴露 <3 天，拒判
    "红酒": (10, 1),      # ✓ 平反：lift 0.49，还带保护色
    "巧克力": (16, 3),    # ✓ 平反：lift 0.96，撤诉黑名单
    "咖啡因": (25, 5),    # ✓ 平反：lift 1.05
    "长屏幕": (12, 2),    # ✓ 平反：lift 0.85
}


def build_rows():
    assert not (set(ATTACK_DAYS) & ABSENT_DAYS), "缺席日与发作日冲突"
    clean = {}   # date -> [triggers]
    quota = dict(CLEAN_QUOTA)
    day = FIRST
    while day <= LAST:
        key = day.isoformat()
        if key in ABSENT_DAYS or key in ATTACK_DAYS:
            day += dt.timedelta(days=1)
            continue
        picks = []
        while len(picks) < 2:
            rest = sorted((-n, name) for name, n in quota.items()
                          if n > 0 and name not in picks)
            if not rest:
                break
            name = rest[0][1]
            picks.append(name)
            quota[name] -= 1
        clean[key] = picks
        day += dt.timedelta(days=1)
    assert not any(quota.values()), f"配额没发完：{quota}"

    rows = ["date\tattack\ttriggers\tnote"]
    day = FIRST
    while day <= LAST:
        key = day.isoformat()
        if key in ABSENT_DAYS:
            day += dt.timedelta(days=1)
            continue
        if key in ATTACK_DAYS:
            attack, triggers = "1", ATTACK_DAYS[key]
            note = ATTACK_NOTES.get(key, "")
        else:
            attack, triggers, note = "0", ",".join(clean[key]), ""
        rows.append("\t".join([key, attack, triggers, note] if note
                              else [key, attack, triggers]))
        day += dt.timedelta(days=1)
    return "\n".join(rows) + "\n"


def verify_margins():
    """独立核对账本边际与 EXPECTED 一致（不 import 主程序）。"""
    e_cnt, ae_cnt = {}, {}
    attacks = 0
    empty = 0
    for line in build_rows().splitlines()[1:]:
        cols = line.split("\t")
        triggers = (list(dict.fromkeys(t for t in cols[2].split(",") if t))
                    if cols[2] not in ("", "-") else [])
        if cols[1] == "1":
            attacks += 1
            if not triggers:
                empty += 1
            for t in triggers:
                ae_cnt[t] = ae_cnt.get(t, 0) + 1
        for t in triggers:
            e_cnt[t] = e_cnt.get(t, 0) + 1
    assert attacks == 17 and empty == 4, (attacks, empty)
    for name, (e, ae) in EXPECTED.items():
        got = (e_cnt.get(name, 0), ae_cnt.get(name, 0))
        assert got == (e, ae), f"{name}: {got} != {(e, ae)}"


SNAPSHOTS = [
    ("sample-verdicts.txt", ["verdicts", "diary.tsv"]),
    ("sample-judge-late-sleep.txt", ["judge", "diary.tsv", "--trigger", "缺睡"]),
    ("sample-judge-red-wine.txt", ["judge", "diary.tsv", "--trigger", "红酒"]),
    ("sample-acquitted.txt", ["acquitted", "diary.tsv"]),
    ("sample-case.txt", ["case", "diary.tsv", "--date", "2026-05-07"]),
    ("sample-case-clean.txt", ["case", "diary.tsv", "--date", "2026-05-11"]),
    ("sample-simulate.txt", ["simulate", "diary.tsv", "--avoid", "缺睡",
                             "--months", "3"]),
    ("sample-combo.txt", ["combo", "diary.tsv"]),
    ("sample-validate.txt", ["validate", "diary.tsv"]),
]


def main():
    if "--check" in sys.argv:
        with open(DIARY, encoding="utf-8") as fh:
            want = fh.read()
        have = build_rows()
        if want != have:
            sys.exit("diary.tsv 与构建器不一致：请重新运行 build_examples.py")
    else:
        verify_margins()
        with open(DIARY, "w", encoding="utf-8") as fh:
            fh.write(build_rows())
    for fname, argv in SNAPSHOTS:
        out = os.path.join(HERE, fname)
        run = [sys.executable, CLI] + argv
        if "diary.tsv" in argv:
            run[run.index("diary.tsv")] = DIARY
        run += ["--today", TODAY]
        done = subprocess.run(run, capture_output=True, text=True)
        if fname == "sample-verdicts.txt" and done.returncode != 4:
            sys.exit(f"verdicts 应因定罪 exit 4，实得 {done.returncode}")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(done.stdout)
        print(f"wrote {fname} (exit {done.returncode})")
    print("OK")


if __name__ == "__main__":
    main()
