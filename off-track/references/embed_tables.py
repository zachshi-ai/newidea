#!/usr/bin/env python3
"""One-off: generate embedded LMS constants for the CLI from references/."""
import csv

hfa, bmi = [], []
with open('lenageinf.csv') as fh:
    for r in csv.DictReader(fh):
        if float(r['Agemos']) <= 24.0:
            hfa.append((int(r['Sex']), float(r['Agemos']), float(r['L']), float(r['M']), float(r['S'])))
with open('statage.csv') as fh:
    for r in csv.DictReader(fh):
        if float(r['Agemos']) > 24.0:
            hfa.append((int(r['Sex']), float(r['Agemos']), float(r['L']), float(r['M']), float(r['S'])))
with open('bmiagerev.csv') as fh:
    for r in csv.DictReader(fh):
        bmi.append((int(r['Sex']), float(r['Agemos']), float(r['L']), float(r['M']), float(r['S'])))

hfa.sort(key=lambda t: (t[0], t[1]))
bmi.sort(key=lambda t: (t[0], t[1]))

def fmt(x):
    return repr(x)

def dump(tbl):
    return '\n'.join(f'{s} {fmt(m)} {fmt(L)} {fmt(M)} {fmt(S)}' for s, m, L, M, S in tbl)

out = ('HFA_DATA = """\\\n' + dump(hfa) + '\n"""\n\n'
       'BMI_DATA = """\\\n' + dump(bmi) + '\n"""\n')
open('/tmp/embedded_tables.py', 'w').write(out)
print('hfa nodes:', len(hfa), ' bmi nodes:', len(bmi), ' bytes:', len(out))
