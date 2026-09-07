#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the cry-wolf example ledger + snapshots (byte-reproducible).

`python3 build_examples.py`         -> (re)write worries.tsv and every snapshot
`python3 build_examples.py --check` -> verify each file matches, byte for byte

The snapshots are produced by the CLI itself, so what CI checks is exactly
what a reader gets. Same ledger, same bytes, any machine, any day — the CLI
has no wall clock: as-of defaults to the ledger's own last date.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "worries.tsv")

LEDGER_ROWS = [
    "# cry-wolf 账本 · 小周的灾难想象对账(2026 流感季到 Q3)",
    "#",
    "# 列: date/type/topic/fear/due/nights/ref/outcome",
    "# fear 行: 入账一场担忧。fear 写到能检验(谁/会出什么事),due 是你答应自己",
    "#          回来看结果的日期,nights 是为它失眠的夜数(可空,空=没记按 0 算)。",
    "# check 行: 到期结案。outcome: hit=核心灾难真发生 partial=沾边但轻/变形 miss=虚惊一场",
    "# ref 指向 fear 行的物理行号(含注释与表头,编辑器可直达)。一场担忧只结案一次;",
    "# 同一主题再担心 = 另起一行入账,重播链(wolves)会替你把它串起来。",
    "date\ttype\ttopic\tfear\tdue\tnights\tref\toutcome",
    "2026-03-02\tfear\tchild-health\tkindergarten flu season: his cough turns into pneumonia and a hospital stay\t2026-03-16\t2\t\t",
    "2026-03-16\tcheck\t\t\t\t\t10\tmiss",
    "2026-03-05\tfear\tjob\tthe project gets cut in the Q2 reorg and the whole team goes with it\t2026-06-30\t1\t\t",
    "2026-06-30\tcheck\t\t\t\t\t12\tmiss",
    "2026-03-20\tfear\thealth\tthe thyroid nodule (TI-RADS 3) has already turned malignant\t2026-06-01\t3\t\t",
    "2026-06-01\tcheck\t\t\t\t\t14\tmiss",
    "2026-04-10\tfear\tmoney\tthe April pullback margin-calls the position\t2026-05-10\t0\t\t",
    "2026-05-10\tcheck\t\t\t\t\t16\tpartial",
    "2026-05-08\tfear\tchild-health\tsame cough again — pneumonia this time for sure\t2026-05-22\t1\t\t",
    "2026-05-22\tcheck\t\t\t\t\t18\tmiss",
    "2026-06-15\tfear\tjob\tthe key client churns at renewal and my Q3 number is dead\t2026-06-30\t1\t\t",
    "2026-06-30\tcheck\t\t\t\t\t20\thit",
    "2026-07-06\tfear\tchild-health\tthird cough of the year, the doctor hears wheezing\t2026-07-20\t2\t\t",
    "2026-07-20\tcheck\t\t\t\t\t22\tmiss",
    "2026-08-14\tfear\tjob\tQ3 restructuring: my name is on the list this time\t2026-08-31\t2\t\t",
    "2026-09-01\tfear\tparents\tthey will need a big sum someday and nobody has a plan\t\t\t\t",
    "2026-09-05\tfear\tchild-health\tnew semester, flu round two, back in the hospital ward\t2026-09-19\t0\t\t",
]

# (snapshot filename, argv after the ledger path)
SNAPSHOTS = [
    ("report.txt", ["report"]),
    ("wolves.txt", ["wolves"]),
    ("due.txt", ["due"]),
    ("validate.txt", ["validate"]),
    ("report-asof-0523.txt", ["report", "--as-of", "2026-05-23"]),
    ("wolves-asof-0523.txt", ["wolves", "--as-of", "2026-05-23"]),
]


def build():
    ledger_text = "\n".join(LEDGER_ROWS) + "\n"
    out = {"worries.tsv": ledger_text}
    for name, argv in SNAPSHOTS:
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "..", "cry_wolf.py")] + argv + ["--ledger", LEDGER],
            capture_output=True, text=True)
        body = proc.stdout
        if proc.returncode not in (0, 4):  # 4 = an alarm is lit; that IS the story
            body += proc.stderr
        out[name] = body + ("[exit %d]\n" % proc.returncode)
    return out


def main():
    check = "--check" in sys.argv[1:]
    failures = 0
    for name, content in build().items():
        path = os.path.join(HERE, name)
        try:
            with open(path, "rb") as fh:
                current = fh.read()
        except OSError:
            current = None
        if current == content.encode("utf-8"):
            print("ok  %s" % name)
            continue
        if check:
            print("DRIFT %s" % name)
            failures += 1
        else:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            print("wrote %s" % name)
    if check and failures:
        print("%d snapshot(s) drifted — rerun build_examples.py without --check and commit"
              % failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
