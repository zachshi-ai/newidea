#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the same-frame example ledger + snapshots (byte-reproducible).

`python3 build_examples.py`         -> (re)write family.tsv and every snapshot
`python3 build_examples.py --check` -> verify each file matches, byte for byte

The snapshots are produced by the CLI itself. The ledger has no wall clock:
as-of defaults to the ledger's own last date, so the same file yields the
same bytes on any machine, any day.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "family.tsv")

LEDGER_ROWS = [
    "# 同框账本 · 陈家的聚齐记录(爷奶在老家,三兄妹在城里)",
    "# 列: date/event/who",
    "# date=聚齐那天 event=场合(可空) who=在场成员(逗号分隔,首见即注册)",
    "# 拍完照随手记一行——账本只数「已经空了多久」,不数「还剩几次」",
    "date\tevent\twho",
    "2023-01-22\t春节全家福\t爷爷,奶奶,爸,妈,大姐,二哥,小妹",
    "2023-05-02\t大姐婚礼\t爷爷,奶奶,爸,妈,大姐,二哥,小妹",
    "2023-09-29\t中秋\t爷爷,奶奶,爸,妈,二哥",
    "2024-02-10\t春节\t爷爷,奶奶,爸,妈,大姐,二哥,小妹",
    "2024-06-08\t端午\t爸,妈,二哥,爷爷",
    "2024-10-02\t国庆\t爷爷,奶奶,爸,妈,大姐,二哥,小妹",
    "2024-11-16\t爷爷住院复查\t爸,大姐,爷爷",
    "2025-01-29\t春节\t奶奶,爸,妈,大姐,二哥,小妹",
    "2025-05-11\t母亲节\t妈,大姐,小妹",
    "2025-10-04\t国庆\t奶奶,爸,妈,大姐,二哥,小妹",
    "2026-02-16\t春节\t奶奶,爸,妈,大姐,小妹",
    "2026-05-31\t小妹搬家\t妈,大姐,小妹,二哥",
    "2026-08-30\t奶奶生日\t奶奶,爸,妈,大姐,小妹",
]

# (snapshot filename, argv after the subcommand; ledger appended last)
SNAPSHOTS = [
    ("report.txt", ["report"]),
    ("pairs.txt", ["pairs"]),
    ("validate.txt", ["validate"]),
    ("report-asof-20251004.txt", ["report", "--as-of", "2025-10-04"]),
]


def build_snapshots():
    """snapshot subprocesses must run against the freshly written family.tsv,
    so the caller has to write the ledger first."""
    out = {}
    cli = os.path.join(HERE, "..", "same_frame.py")
    for name, argv in SNAPSHOTS:
        proc = subprocess.run(
            [sys.executable, cli] + argv + ["--ledger", LEDGER],
            capture_output=True, text=True)
        body = proc.stdout
        if proc.returncode not in (0, 4):  # 4 = an alarm is lit; that IS the story
            body += proc.stderr
        out[name] = body + ("[exit %d]\n" % proc.returncode)
    return out


def main():
    check = "--check" in sys.argv[1:]
    ledger_text = "\n".join(LEDGER_ROWS) + "\n"
    ledger_path = os.path.join(HERE, "family.tsv")
    if not check:
        with open(ledger_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(ledger_text)
        print("wrote family.tsv")
    files = {"family.tsv": ledger_text}
    files.update(build_snapshots())
    failures = 0
    for name, content in files.items():
        path = os.path.join(HERE, name)
        try:
            with open(path, "rb") as fh:
                current = fh.read()
        except OSError:
            current = None
        if current == content.encode("utf-8"):
            if name != "family.tsv" or check:
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
