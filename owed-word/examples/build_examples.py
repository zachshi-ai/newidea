#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_examples · 生成/校验 examples/ 下的字节级快照.

主账本 words.tsv(老蒋的应承,as-of 2026-02-10)+ 全绿对照小账本
clean.tsv(当周答应、当周结清)。所有快照用显式 --as-of 钉死,同账
任何机器任何一天逐字节一致;--check 重新生成并逐一比对,漂移即 exit 1。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable or "python3"

AS_OF = "2026-02-10"
TM_AS_OF = "2025-12-15"

CLEAN_TSV = """who\twhat\tdate\tstate\tnote
同事阿岚\t看她改过的简历再给一轮意见\t2026-02-02\tdid\tdone:2026-02-07 周六视频过了一遍
大学室友老凯\t帮他抢演出票\t2026-02-04\tdeclined\t当天回了抢不到,他自己在蹲
小组学妹\t讲一次转正答辩的经验\t2026-02-08\topen\t约了下周三午饭
"""

SNAPSHOTS = [
    ("sample-report.txt", ["report", "words.tsv", "--as-of", AS_OF], 4),
    ("sample-next.txt", ["next", "words.tsv", "--as-of", AS_OF], 4),
    ("sample-settled.txt", ["settled", "words.tsv", "--as-of", AS_OF], 4),
    ("sample-validate.txt", ["validate", "words.tsv"], 0),
    ("sample-report-timemachine.txt",
     ["report", "words.tsv", "--as-of", TM_AS_OF], 4),
    ("sample-report-clean.txt", ["report", "clean.tsv", "--as-of", AS_OF], 0),
    ("sample-next-clean.txt", ["next", "clean.tsv", "--as-of", AS_OF], 0),
]


def build_clean():
    p = os.path.join(HERE, "clean.tsv")
    with open(p, "w", encoding="utf-8") as f:
        f.write(CLEAN_TSV)
    return len(CLEAN_TSV.strip().split("\n"))


def run(cmd):
    r = subprocess.run([PY, os.path.join(ROOT, "owed_word.py")] + cmd,
                       cwd=HERE, capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode


def main():
    check = "--check" in sys.argv
    build_clean()
    failures = 0
    for fname, cmd, want_code in SNAPSHOTS:
        out, err, code = run(cmd)
        path = os.path.join(HERE, fname)
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
    if failures:
        sys.exit(1)
    print("快照全部" + ("校验通过" if check else "生成"))


if __name__ == "__main__":
    main()
