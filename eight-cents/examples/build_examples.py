#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成/校验 examples 快照。

用法:
  python3 build_examples.py           # 重新生成全部快照(样例账本改动后跑)
  python3 build_examples.py --check   # 重新生成并逐字节比对,不一致 exit 1(CI 用)

注意: report 快照的 exit 4(李家 profile 的 PENNY-MYTH 红灯)与 breakeven 快照的
exit 4(李家 19.7 年追不平)是样例故事本该亮的红灯——快照只存 stdout,
exit code 由验收测试断言,快照本身是 advisory。
"""

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import eight_cents  # noqa: E402

SNAPSHOTS = [
    ("report.txt", ["report"]),
    ("breakeven.txt", ["breakeven", "--years", "8"]),
    ("report-li.txt", ["report", "--profile", "li"]),
    ("breakeven-wang.txt", ["breakeven", "--profile", "wang", "--years", "8"]),
    ("validate.txt", ["validate"]),
]


def render(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        eight_cents.main(argv + ["--dir", HERE])
    return buf.getvalue()


def build(check=False):
    diffs = []
    for name, argv in SNAPSHOTS:
        content = render(argv)
        path = os.path.join(HERE, name)
        if check:
            with open(path, encoding="utf-8") as f:
                old = f.read()
            if old != content:
                diffs.append(name)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  写 {name} ({len(content)} 字节)")
    if check:
        if diffs:
            print("快照不一致: " + "、".join(diffs))
            return 1
        print(f"快照逐字节一致 ({len(SNAPSHOTS)} 份) ✓")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(build(check="--check" in sys.argv[1:]))
