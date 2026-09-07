#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_examples · 生成/校验 examples/ 下的字节级快照.

样例账本 shots.tsv(小满,春节寄养前夜)+ 年糕单宠小账本 niangao.tsv
(全绿对照面)。所有快照用显式 --as-of 钉死,同账任何机器任何一天
逐字节一致;--check 重新生成并逐一比对,漂移即 exit 1。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable or "python3"

AS_OF = "2026-02-10"        # 腊月廿三,寄养 2-14 入住
TM_AS_OF = "2025-12-20"     # 时间机器:一个月前

SNAPSHOTS = [
    ("sample-report.txt",
     ["report", "shots.tsv", "--as-of", AS_OF], 4),
    ("sample-next.txt",
     ["next", "shots.tsv", "--as-of", AS_OF], 4),
    ("sample-brief.txt",
     ["brief", "shots.tsv", "--as-of", AS_OF], 4),
    ("sample-validate.txt",
     ["validate", "shots.tsv"], 0),
    ("sample-report-timemachine.txt",
     ["report", "shots.tsv", "--as-of", TM_AS_OF], 4),
    ("sample-report-niangao.txt",
     ["report", "niangao.tsv", "--as-of", AS_OF], 0),
]


def build_niangao():
    """年糕单宠小账本:从主账本摘出年糕的登记与六针——全绿对照面."""
    main = os.path.join(HERE, "shots.tsv")
    with open(main, encoding="utf-8") as f:
        lines = [l for l in f.read().split("\n") if l.strip()]
    keep = [lines[0]]
    keep += [l for l in lines if l.startswith("pet\t年糕")]
    keep += [l for l in lines if l.startswith("shot\t年糕")]
    with open(os.path.join(HERE, "niangao.tsv"), "w", encoding="utf-8") as f:
        f.write("\n".join(keep) + "\n")
    return len(keep)


def run(cmd):
    r = subprocess.run([PY, os.path.join(ROOT, "shot_chain.py")] + cmd,
                       cwd=HERE, capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode


def main():
    check = "--check" in sys.argv
    n = build_niangao()
    failures = 0
    for fname, cmd, want_code in SNAPSHOTS:
        out, err, code = run(cmd)
        path = os.path.join(HERE, fname)
        expected = out if code == want_code else (
            out + "\n[stderr] " + err)
        expected = (out + err) if err else out
        if code != want_code:
            print(f"✗ {fname}: exit {code} != 期望 {want_code}\n{err}", end="")
            failures += 1
            continue
        if check:
            with open(path, encoding="utf-8") as f:
                old = f.read()
            if old != expected:
                print(f"✗ {fname}: 快照漂移(字节级不一致)")
                failures += 1
                continue
            print(f"✓ {fname} 字节一致 (exit {code})")
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(expected)
            print(f"· 生成 {fname} (exit {code})")
    print(f"年糕小账本 {n} 行" if not check else f"年糕小账本 {n} 行(重生成一致)")
    if failures:
        sys.exit(1)
    print("快照全部" + ("校验通过" if check else "生成"))


if __name__ == "__main__":
    main()
