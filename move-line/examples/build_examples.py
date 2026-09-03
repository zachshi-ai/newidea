#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the move-line example ledgers and report snapshots.

The demo is one tenant's renewal season (2026-08-30): three years in
梧桐里 at ¥4,500/month, a 25-minute commute, and a landlord asking
+12% (¥5,040). Two candidates are on the table: 同小区两期B (same
commute, ¥4,590) and 滨江壹号A (¥700 cheaper but 50 minutes out).
One-time moving costs total ¥5,220 — deliberately missing three common
categories so the toll checklist banner fires.

The numbers the margins are tuned to tell: blind line +3.2%, real line
+5.2% at a 3-year horizon (judged MOVE, exit 4) but +11.7% at 1 year
(same offer becomes a coin toss) — the answer depends on how long you
plan to stay, not on how angry you are.

  python3 build_examples.py            # write ledgers + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "move_line.py")

HOMES = """\
# 住处账本 · name/rent(月租元)/commute(单程分钟)/role/note
# role: current=现居(恰好一个) candidate=候选
name	rent	commute	role	note
梧桐里	4500	25	current	住了三年的两居 · 2026-08-30 收到 +12% 续租通知
同小区两期B	4590	25	candidate	隔壁期房 · 同通勤 · 中介称「房东急租」
滨江壹号A	3800	50	candidate	名义便宜 ¥700/月 · 通勤翻倍
"""

MOVE = """\
# 搬家一次性成本账本 · item/amount(元)/note
# 押金可退不算成本；起租重叠按多付的日租金记
item	amount	note
中介费	2250	半月租 · 本城惯例
搬家公司	1200	两车 · 含人工
家具拆装	600	床+沙发+空调
宽带迁移与换锁	350	移机 200 + 换锁 150
新家开荒保洁	400	65㎡
请假误工	420	半天调休折价
"""

LEDGERS = [("homes.tsv", HOMES), ("move.tsv", MOVE)]

SNAPSHOTS = [
    ("sample-cap.txt", ["cap"]),
    ("sample-judge.txt", ["judge", "--offer", "5040"], 4),
    ("sample-judge-1y.txt", ["judge", "--offer", "5040", "--years", "1"], 0),
    ("sample-compare.txt", ["compare", "--offer", "5040"]),
    ("sample-toll.txt", ["toll"]),
    ("sample-sensitivity.txt", ["sensitivity", "--offer", "5040"]),
    ("sample-validate.txt", ["validate"]),
]


def main():
    if "--check" in sys.argv:
        for fname, want in LEDGERS:
            with open(os.path.join(HERE, fname), encoding="utf-8") as fh:
                if fh.read() != want:
                    sys.exit(f"{fname} 与构建器不一致："
                             f"请重新运行 build_examples.py")
    else:
        for fname, content in LEDGERS:
            with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
                fh.write(content)
    for spec in SNAPSHOTS:
        fname, argv = spec[0], spec[1]
        want_code = spec[2] if len(spec) > 2 else 0
        run = [sys.executable, CLI] + argv + [
            os.path.join(HERE, "homes.tsv"), os.path.join(HERE, "move.tsv")]
        done = subprocess.run(run, capture_output=True, text=True)
        if done.returncode != want_code:
            sys.exit(f"{fname}: 期望 exit {want_code}，实得 {done.returncode}"
                     f"\n{done.stdout}{done.stderr}")
        with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
            fh.write(done.stdout)
        print(f"wrote {fname} (exit {done.returncode})")
    print("OK")


if __name__ == "__main__":
    main()
