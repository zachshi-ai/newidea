#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate the example ledgers and their snapshot outputs.

The ledgers are synthesized on the exact percentile bands they claim to
ride (P60 for xiaoman, P75->P10 descent for xiaozhou, P10 for xiaoshu),
so every sample number is derivable from the embedded reference tables.
Snapshots are the stdout of the real CLI over these ledgers; `--check`
re-runs everything and compares byte-for-byte (CI gate).

Run from anywhere: paths are resolved relative to this file.
"""
import math
import os
import subprocess
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import off_track as T  # noqa: E402

LEDGERS = ('xiaoman', 'xiaozhou', 'xiaoshu', 'xiaodou')
SNAP_DIR = os.path.join(HERE, 'snapshots')

HEADER = 'date\tchild\tborn\tsex\theight_cm\tweight_kg\n'


def birthday_rows(born, child, sex, month_heights, month_bmis):
    rows = [HEADER]
    for mo in sorted(month_heights):
        d = born + timedelta(days=math.ceil(mo * T.MONTH))
        h = month_heights[mo]
        if month_bmis is None:
            w = ''
        else:
            w = '%.2f' % (month_bmis[mo] * (h / 100.0) ** 2)
        rows.append('%s\t%s\t%s\t%s\t%.1f\t%s\n'
                    % (d, child, born, sex, h, w))
    return ''.join(rows)


def build_ledgers():
    # xiaoman: a girl riding her P60 height band, BMI ~P55 — the healthy
    # green ledger. Every percentile is exact by construction.
    born = date(2018, 3, 15)
    months = (24, 36, 48, 60, 72, 84, 96)
    man = birthday_rows(born, 'xiaoman', 'F',
                        {mo: T.value_at_percentile('HFA', 2, mo, 60.0) for mo in months},
                        {mo: T.value_at_percentile('BMI', 2, mo, 55.0) for mo in months})
    # xiaozhou: a boy whose visits each look individually unremarkable.
    # Height descends P75 -> P10 over five years (every single window
    # crosses at most one band), while BMI climbs P25 -> P90. This is the
    # ledger the tool exists for: five green stamps, one red track.
    born = date(2011, 7, 2)
    months = (48, 60, 72, 84, 96, 108)
    start_pct, end_pct = 75.0, 10.0
    heights = {}
    bmis = {}
    for i, mo in enumerate(months):
        p = start_pct + (end_pct - start_pct) * i / (len(months) - 1)
        heights[mo] = T.value_at_percentile('HFA', 1, mo, p)
        bmis[mo] = T.value_at_percentile('BMI', 1, mo, 25.0 + (90.0 - 25.0) * i / (len(months) - 1))
    zhou = birthday_rows(born, 'xiaozhou', 'M', heights, bmis)
    # xiaoshu: a boy holding P10 through the pubertal window with velocity
    # intact, below his mid-parental target — the constitutional-delay
    # portrait (bone age is the referee; this ledger only sets the stage).
    born = date(2012, 5, 20)
    months = (144, 156, 168)
    shu = birthday_rows(born, 'xiaoshu', 'M',
                        {mo: T.value_at_percentile('HFA', 1, mo, 10.0) for mo in months},
                        None)
    # xiaodou: a toddler with two infant rows — position is published, the
    # track grading declines. Thin ledgers are honest, not broken.
    dou = (HEADER
           + '2026-01-10\txiaodou\t2025-02-10\tF\t76.2\t9.6\n'
           + '2026-04-10\txiaodou\t2025-02-10\tF\t78.5\t10.4\n')
    return {'xiaoman': man, 'xiaozhou': zhou, 'xiaoshu': shu, 'xiaodou': dou}


SNAPSHOT_COMMANDS = {
    'xiaoman': [
        ['report', 'LEDGER', '--mom', '160', '--dad', '172'],
        ['track', 'LEDGER'],
        ['velocity', 'LEDGER'],
        ['next', 'LEDGER', '--next-at', '2026-09-15'],
        ['validate', 'LEDGER'],
    ],
    'xiaozhou': [
        ['report', 'LEDGER'],
        ['track', 'LEDGER'],
        ['velocity', 'LEDGER'],
        ['next', 'LEDGER', '--next-at', '2021-01-15'],
        ['validate', 'LEDGER'],
    ],
    'xiaoshu': [
        ['report', 'LEDGER', '--mom', '168', '--dad', '180', '--family-late-bloomer'],
        ['target', 'LEDGER', '--mom', '168', '--dad', '180'],
        ['validate', 'LEDGER'],
    ],
    'xiaodou': [
        ['report', 'LEDGER'],
        ['next', 'LEDGER'],
        ['validate', 'LEDGER'],
    ],
}


def cli_path():
    return os.path.join(ROOT, 'off_track.py')


def run_snapshots(ledgers, check=False):
    ok = True
    for child in LEDGERS:
        led = os.path.join(HERE, '%s.tsv' % child)
        for i, cmd in enumerate(SNAPSHOT_COMMANDS[child], 1):
            argv = [sys.executable, cli_path()] + [led if a == 'LEDGER' else a for a in cmd]
            proc = subprocess.run(argv, capture_output=True, text=True)
            name = '%s.%d.out' % (child, i)
            path = os.path.join(SNAP_DIR, name)
            produced = proc.stdout
            if proc.returncode not in (0, 4):  # green and red lights are both valid snapshots
                print('%s: CLI exit %d (stderr: %s)' % (name, proc.returncode,
                                                        proc.stderr.strip()[:200]))
                ok = False
            if check:
                with open(path) as fh:
                    expected = fh.read()
                if produced != expected:
                    ok = False
                    print('SNAPSHOT MISMATCH: %s' % name)
                    for j, (a, b) in enumerate(zip(expected.splitlines(), produced.splitlines())):
                        if a != b:
                            print('  first diff at line %d:\n   expected: %r\n   actual:   %r'
                                  % (j + 1, a, b))
                            break
                    if len(expected.splitlines()) != len(produced.splitlines()):
                        print('  line count %d -> %d' % (len(expected.splitlines()),
                                                         len(produced.splitlines())))
            else:
                with open(path, 'w') as fh:
                    fh.write(produced)
                print('wrote %s (exit %d)' % (os.path.relpath(path, HERE), proc.returncode))
    return ok


def main():
    check = '--check' in sys.argv
    os.makedirs(SNAP_DIR, exist_ok=True)
    ledgers = build_ledgers()
    for child, text in ledgers.items():
        path = os.path.join(HERE, '%s.tsv' % child)
        if check:
            with open(path) as fh:
                if fh.read() != text:
                    print('LEDGER MISMATCH: %s.tsv (regenerate without --check)' % child)
                    return 1
        else:
            with open(path, 'w') as fh:
                fh.write(text)
    if run_snapshots(ledgers, check=check):
        print('check: all snapshots byte-identical' if check else 'snapshots regenerated')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
