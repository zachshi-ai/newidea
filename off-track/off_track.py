#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""off-track — 掉带 / Off Track

"Is my child short?" is a question about POSITION — where the child sits
among peers. "Is my child still ON HIS TRACK?" is a question about
DIRECTION — whether he is still riding the percentile band he has always
ridden. Pediatrics grades direction, and parents keep staring at position:
the well-child visit says "normal" twice a year, grandma says the neighbor's
boy is half a head taller, and nobody connects the measurements into a
track. Growth faltering is defined as CROSSING TWO MAJOR PERCENTILE BANDS —
a signal that only exists when measurements are strung together: every
single visit can look unremarkable while the five-year path slides from
P75 to P10. The same machinery run upward is the earliest signature of
childhood obesity.

off-track keeps that ledger by hand (one row per measurement, copied from
the well-child booklet), and grades the TRACK, not the position:

  report    — full read: position percentile, band path with drift/window
              grades, segment velocity vs age floors, mid-parental target
              height, BMI track
  track     — the measurement-by-measurement band ledger
  velocity  — per-window growth velocity against age-segment floors
  target    — mid-parental target height page (--mom/--dad required)
  next      — the safe corridor for the NEXT measurement; bring it to the
              well-child visit
  validate  — engine self-checks and ledger identity checks

Exit codes: 0 on-track, or thin ledger with the arithmetic still printed
(position is always published; only track grading is declined) / 4 red
light — a REASON TO SEE A PEDIATRIC ENDOCRINOLOGIST, not a diagnosis / 2
broken ledger or usage. This tool gives no medical advice; it refuses to
invent bone age, the only referee of the "late bloomer" question.

Reference data: CDC 2000 growth charts LMS parameters (stature-for-age and
BMI-for-age, 2-20y) and WHO 2006 child growth standards (length-for-age,
0-24m), as published in the CDC percentile data files
(https://www.cdc.gov/growthcharts/percentile_data_files.htm). The embedded
tables are a verbatim subset (Sex, Agemos, L, M, S) of those files, pinned
by off-track/references/*.csv; regenerate with references/embed_tables.py.
Every threshold below is a prior, and every prior is a -- flag.
"""

import argparse
import math
import os
import sys
from datetime import date, datetime, timedelta
from statistics import NormalDist

PROG = 'off-track'
VERSION = '1.0'
MONTH = 30.4375          # CDC "medial month" used for fractional ages
BANDS = (3.0, 10.0, 25.0, 50.0, 75.0, 90.0, 97.0)   # major percentile lines
INFANT_FREE_MONTHS = 24.0    # <24mo: physiologic band drift, never graded
MIN_GRADE_SPAN_DAYS = 120    # two measurements closer than this: no crossing grade
ADULT_MONTHS = 240.5         # top of reference tables
HEIGHT_REGRESSION_CM = 1.0   # taller children never shrink; >1cm regression is a typo
EXIT_OK, EXIT_BROKEN, EXIT_RED = 0, 2, 4

# Default velocity floors in cm/yr by age segment (mid-window age, months).
# Common screening priors: <5 cm/yr between age 4 and puberty, faster floors
# for toddlers, and a relaxed floor inside the pubertal window.
VELOCITY_SEGMENTS = (
    (24.0, 36.0, 7.0),
    (36.0, 48.0, 6.0),
    (48.0, 240.5, 5.0),
)
VELOCITY_PUBERTAL_FLOOR = 4.0   # applies from puberty start (girl 10y / boy 12y)

BAND_NAMES = ('<P3', 'P3-P10', 'P10-P25', 'P25-P50', 'P50-P75', 'P75-P90', 'P90-P97', '>P97')

LEDGER_COMMENT = """\
# off-track measurement ledger — one row per well-child measurement.
# born/sex are repeated per row on purpose: the booklet has them printed
# on every page, and a mismatch between rows is a transcription bug.
#date        child     born        sex  height_cm  weight_kg
"""


# ---------------------------------------------------------------------------
# LMS engine (tables appended at the bottom of this file by embed_tables.py)
# ---------------------------------------------------------------------------

def _parse_table(text):
    table = {}
    for line in text.strip().splitlines():
        s, m, L, M, S = line.split()
        table.setdefault(int(s), []).append((float(m), float(L), float(M), float(S)))
    for sex in table:
        table[sex].sort()
    return table


TABLES = {}


def lms_at(table, sex, agemo):
    """Linear interpolation between semiannual LMS nodes."""
    nodes = TABLES[table][sex]
    if agemo < nodes[0][0] or agemo > nodes[-1][0]:
        raise OutOfRange('age %.1f months outside reference table (%.1f-%.1f)'
                         % (agemo, nodes[0][0], nodes[-1][0]))
    i = bisect_left_node(nodes, agemo)
    m0, l0, mm0, s0 = nodes[i]
    if agemo == m0:
        return l0, mm0, s0
    m1, l1, mm1, s1 = nodes[i + 1]
    t = (agemo - m0) / (m1 - m0)
    return (l0 + (l1 - l0) * t, mm0 + (mm1 - mm0) * t, s0 + (s1 - s0) * t)


def bisect_left_node(nodes, agemo):
    lo, hi = 0, len(nodes) - 1
    if agemo >= nodes[-1][0]:
        return len(nodes) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if nodes[mid][0] < agemo:
            lo = mid + 1
        else:
            hi = mid
    if nodes[lo][0] > agemo:
        lo -= 1
    return lo


def lms_z(L, M, S, x):
    if L == 0:
        return math.log(x / M) / S
    return ((x / M) ** L - 1.0) / (L * S)


def z_to_pct(z):
    return 100.0 * NormalDist().cdf(z)


def pct_to_z(p):
    return NormalDist().inv_cdf(p / 100.0)


def percentile_of(table, sex, agemo, x):
    L, M, S = lms_at(table, sex, agemo)
    return z_to_pct(lms_z(L, M, S, x))


def value_at_percentile(table, sex, agemo, p):
    L, M, S = lms_at(table, sex, agemo)
    z = pct_to_z(p)
    if L == 0:
        return M * math.exp(S * z)
    return M * (1.0 + L * S * z) ** (1.0 / L)


def band_of(pct):
    """Index into BAND_NAMES. A percentile sitting exactly on a band line
    counts as the higher band: P10 is the floor of the P10-P25 band."""
    for i, hi in enumerate(BANDS):
        if pct < hi:
            return i
    return 7


def band_floor_value(table, sex, agemo, band):
    """Smallest value still inside `band` at this age (its lower line)."""
    if band <= 0:
        return None
    return value_at_percentile(table, sex, agemo, BANDS[band - 1])


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

SEX_ALIASES = {'m': 'M', 'male': 'M', 'boy': 'M', '1': 'M', '男': 'M', '男孩': 'M',
               'f': 'F', 'female': 'F', 'girl': 'F', '2': 'F', '女': 'F', '女孩': 'F'}

COLUMN_ALIASES = {
    'date': 'date', '日期': 'date',
    'child': 'child', 'name': 'child', '孩子': 'child', '姓名': 'child',
    'born': 'born', 'birthday': 'born', '生日': 'born', '出生': 'born',
    'sex': 'sex', 'gender': 'sex', '性别': 'sex',
    'height_cm': 'height', 'height': 'height', 'cm': 'height', '身高': 'height',
    'weight_kg': 'weight', 'weight': 'weight', 'kg': 'weight', '体重': 'weight',
}


class OutOfRange(Exception):
    pass


class LedgerError(Exception):
    def __init__(self, line_no, msg):
        super().__init__('line %d: %s' % (line_no, msg))
        self.line_no = line_no


def parse_date(text, line_no, what='date'):
    try:
        return datetime.strptime(text.strip(), '%Y-%m-%d').date()
    except ValueError:
        raise LedgerError(line_no, 'bad %s %r (want YYYY-MM-DD)' % (what, text))


class Measure(object):
    __slots__ = ('line_no', 'child', 'born', 'sex', 'height', 'weight', 'date', 'agemo')

    def __init__(self, line_no, child, born, sex, height, weight, dt):
        self.line_no = line_no
        self.child = child
        self.born = born
        self.sex = sex
        self.height = height
        self.weight = weight
        self.date = dt
        days = (dt - born).days
        self.agemo = days / MONTH

    @property
    def bmi(self):
        if self.weight is None:
            return None
        return self.weight / (self.height / 100.0) ** 2

    def pct(self, bmi_mode=False):
        table = 'BMI' if bmi_mode else 'HFA'
        value = self.bmi if bmi_mode else self.height
        try:
            return percentile_of(table, 1 if self.sex == 'M' else 2, self.agemo, value)
        except OutOfRange:
            # BMI reference starts at 24 months; rows below that are
            # height-tracked only. HFA out-of-range is already rejected
            # by check_ledger, so this only fires for infant BMI rows.
            if bmi_mode:
                return None
            raise


def read_ledger(path):
    if not os.path.exists(path):
        raise LedgerError(0, 'file not found: %s' % path)
    rows = []
    header = None
    with open(path, encoding='utf-8') as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            cells = line.split('\t')
            if header is None:
                header = []
                for c in cells:
                    key = COLUMN_ALIASES.get(c.strip().lower())
                    if key is None:
                        raise LedgerError(line_no, 'unknown column %r' % c)
                    header.append(key)
                for required in ('date', 'born', 'sex', 'height'):
                    if required not in header:
                        raise LedgerError(line_no, 'missing required column %r' % required)
                continue
            if len(cells) > len(header):
                raise LedgerError(line_no, 'row has more cells than header')
            rec = dict(zip(header, cells))
            dt = parse_date(rec['date'], line_no)
            born = parse_date(rec['born'], line_no, 'born')
            sex = SEX_ALIASES.get(rec['sex'].strip().lower())
            if sex is None:
                raise LedgerError(line_no, 'unknown sex %r' % rec['sex'])
            child = rec.get('child', '').strip() or 'default'
            try:
                height = float(rec['height'])
            except ValueError:
                raise LedgerError(line_no, 'bad height %r' % rec['height'])
            weight = None
            if rec.get('weight', '').strip():
                try:
                    weight = float(rec['weight'])
                except ValueError:
                    raise LedgerError(line_no, 'bad weight %r' % rec['weight'])
            rows.append(Measure(line_no, child, born, sex, height, weight, dt))
    if header is None:
        raise LedgerError(0, 'no header row found')
    return rows


def check_ledger(rows, as_of):
    """Structural checks. Raises LedgerError with exit-2 semantics."""
    if not rows:
        raise LedgerError(0, 'no measurement rows as-of %s' % as_of)
    seen = {}
    for m in rows:
        if m.height <= 0 or m.height > 200:
            raise LedgerError(m.line_no, 'height %.1f outside plausible cm range (0,200]' % m.height)
        if m.weight is not None and (m.weight <= 0 or m.weight > 200):
            raise LedgerError(m.line_no, 'weight %.1f outside plausible kg range (0,200]' % m.weight)
        if m.agemo < 0:
            raise LedgerError(m.line_no, 'born %s is after measurement %s' % (m.born, m.date))
        if m.agemo > ADULT_MONTHS:
            raise LedgerError(m.line_no, 'age %.1f months beyond reference tables' % m.agemo)
        key = (m.child, m.date)
        if key in seen:
            raise LedgerError(m.line_no, 'duplicate measurement for %s on %s (line %d)'
                              % (m.child, m.date, seen[key].line_no))
        seen[key] = m
    by_child = group_by_child(rows)
    for child, ms in by_child.items():
        borns = set(m.born for m in ms)
        if len(borns) > 1:
            raise LedgerError(ms[1].line_no, 'child %r has two birthdays: %s and %s'
                              % (child, ms[0].born, ms[1].born))
        sexes = set(m.sex for m in ms)
        if len(sexes) > 1:
            raise LedgerError(ms[1].line_no, 'child %r has conflicting sexes' % child)
        for prev, cur in zip(ms, ms[1:]):
            if cur.height < prev.height - HEIGHT_REGRESSION_CM:
                raise LedgerError(cur.line_no, 'child %r shrank %.1f cm between %s and %s'
                                  % (child, prev.height - cur.height, prev.date, cur.date))


def group_by_child(rows):
    out = {}
    for m in rows:
        out.setdefault(m.child, []).append(m)
    for ms in out.values():
        ms.sort(key=lambda m: (m.date, m.line_no))
    return out


# ---------------------------------------------------------------------------
# Track engine: bands, crossings, velocity
# ---------------------------------------------------------------------------

class Window(object):
    __slots__ = ('a', 'b', 'drift', 'velocity', 'floor', 'ok')

    def __init__(self, a, b, drift, velocity, floor):
        self.a, self.b = a, b
        self.drift = drift
        self.velocity = velocity
        self.floor = floor
        self.ok = velocity is None or floor is None or velocity >= floor - 1e-9


def velocity_floor(sex, agemo, opts):
    if opts.velocity_floor is not None:
        return opts.velocity_floor
    pub = opts.puberty_girl if sex == 'F' else opts.puberty_boy
    if agemo >= pub * 12:
        return VELOCITY_PUBERTAL_FLOOR
    for lo, hi, floor in VELOCITY_SEGMENTS:
        if lo <= agemo < hi:
            return floor
    return VELOCITY_SEGMENTS[-1][2]


def windows(ms, bmi_mode, opts):
    """Adjacent-pair windows over gradable measurements (age >= 24mo)."""
    table = 'BMI' if bmi_mode else 'HFA'
    sex_code = 2 if ms[0].sex == 'F' else 1
    sex = ms[0].sex
    pts = []
    for m in ms:
        if m.agemo < INFANT_FREE_MONTHS:
            continue
        value = m.bmi if bmi_mode else m.height
        if value is None:
            continue
        if bmi_mode and not (8.0 <= m.bmi <= 40.0):
            continue  # unit-suspect, disclosed by report
        pts.append((m, percentile_of(table, sex_code, m.agemo, value)))
    out = []
    for (a, pa), (b, pb) in zip(pts, pts[1:]):
        span_days = (b.date - a.date).days
        if span_days < MIN_GRADE_SPAN_DAYS:
            continue
        floor = None if bmi_mode else velocity_floor(sex, (a.agemo + b.agemo) / 2.0, opts)
        velocity = None if bmi_mode else (b.height - a.height) / (span_days / 365.25)
        out.append(Window(a, b, band_of(pb) - band_of(pa), velocity, floor))
    return pts, out


def grade_track(pts, wins, cross_bands):
    """Returns (band_path, drift, max_window, red_reasons)."""
    path = [band_of(p) for _, p in pts]
    drift = path[-1] - path[0] if len(path) >= 2 else 0
    max_win = max((abs(w.drift) for w in wins), default=0)
    reds = []
    if len(path) >= 2 and abs(drift) >= cross_bands:
        reds.append(('DRIFT', drift))
    if max_win >= cross_bands:
        reds.append(('WINDOW', max_win))
    return path, drift, max_win, reds


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

def add_common(p):
    p.add_argument('--as-of', dest='as_of', default=None, metavar='YYYY-MM-DD',
                   help='pin the audit date (default: last ledger date)')
    p.add_argument('--mom', type=float, default=None, metavar='CM', help="mother's height")
    p.add_argument('--dad', type=float, default=None, metavar='CM', help="father's height")
    p.add_argument('--family-late-bloomer', action='store_true',
                   help='family history of constitutional delay')
    p.add_argument('--cross-bands', type=float, default=2.0, metavar='N',
                   help='band crossings that pull the red light (default 2)')
    p.add_argument('--velocity-floor', type=float, default=None, metavar='CM/YR',
                   help='override all age-segment velocity floors')
    p.add_argument('--target-spread', type=float, default=8.5, metavar='CM',
                   help='mid-parental target half-width (default 8.5)')
    p.add_argument('--puberty-girl', type=float, default=10.0, metavar='YRS')
    p.add_argument('--puberty-boy', type=float, default=12.0, metavar='YRS')


def base_parser():
    ap = argparse.ArgumentParser(prog=PROG, description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd')

    for name, help_text in (
            ('report', 'full track read'),
            ('track', 'measurement-by-measurement band ledger'),
            ('velocity', 'per-window velocity vs age floors'),
            ('target', 'mid-parental target height page'),
            ('next', 'safe corridor for the next measurement'),
            ('validate', 'engine self-checks and ledger identities')):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument('ledger', help='path to the TSV ledger')
        add_common(sp)
        if name == 'next':
            sp.add_argument('--next-at', dest='next_at', default=None, metavar='YYYY-MM-DD',
                            help='planned next measurement date (default: last + 6 months)')
    return ap


class UsageError(Exception):
    pass


def load(path, as_of_text):
    rows = read_ledger(path)
    if as_of_text:
        as_of = parse_date(as_of_text, 0, 'as-of')
    else:
        as_of = max(m.date for m in rows)
    # as-of is a time machine, not a validator: rows after it are the not-
    # yet-happened future ("was he green last year?"), so they are excluded
    # from the computation, never flagged as broken
    rows = [m for m in rows if m.date <= as_of]
    if not rows:
        raise LedgerError(0, 'no measurement rows on or before as-of %s' % as_of)
    check_ledger(rows, as_of)
    return rows, as_of


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def fmt_pct(p):
    return 'P%.1f' % p


def target_range(opts, sex):
    if opts.mom is None or opts.dad is None:
        return None
    # CM'TH mid-parental: boy = (dad+mom+13)/2, girl = (dad+mom-13)/2
    off = 13.0 if sex == 'M' else -13.0
    mid = (opts.dad + opts.mom + off) / 2.0
    return mid, mid - opts.target_spread, mid + opts.target_spread


def late_bloomer_portrait(child_ms, opts, vel_wins):
    """Constitutional-delay portrait: below target, in the pubertal window,
    family history positive, and no velocity failure. Portrait only — the
    tool refuses to invent bone age, the only referee."""
    tgt = target_range(opts, child_ms[-1].sex)
    if tgt is None or not opts.family_late_bloomer:
        return None
    mid, lo, hi = tgt
    if child_ms[-1].height >= lo:
        return None
    pub = opts.puberty_girl if child_ms[-1].sex == 'F' else opts.puberty_boy
    if child_ms[-1].agemo < pub * 12:
        return None
    if any(not w.ok for w in vel_wins):
        return None
    return mid, lo, hi


def child_report(ms, opts, as_of, out):
    sex = ms[0].sex
    sex_code = 1 if sex == 'M' else 2
    last = ms[-1]
    out.append('child %s  (%s, born %s)' % (last.child, sex, last.born))
    out.append('')
    out.append('LAST MEASUREMENT  %s  height %.1f cm  age %.1f mo  %s  band %d (%s)'
               % (last.date, last.height, last.agemo,
                  fmt_pct(last.pct()), band_of(last.pct()), BAND_NAMES[band_of(last.pct())]))
    if last.weight is not None:
        bmi_pct = last.pct(bmi_mode=True)
        if bmi_pct is None:
            out.append('                  weight %.1f kg  BMI %.1f  (no BMI reference below 24 months)'
                       % (last.weight, last.bmi))
        else:
            out.append('                  weight %.1f kg  BMI %.1f  %s  band %d (%s)'
                       % (last.weight, last.bmi, fmt_pct(bmi_pct),
                          band_of(bmi_pct), BAND_NAMES[band_of(bmi_pct)]))
    out.append('')

    # ---- height track ----
    pts, wins = windows(ms, bmi_mode=False, opts=opts)
    out.append('HEIGHT TRACK (%d gradable measurements age>=24mo)' % len(pts))
    if len(pts) < 2 or (pts[-1][0].date - pts[0][0].date).days < MIN_GRADE_SPAN_DAYS:
        out.append('  DECLINED  need >=2 measurements aged >=24mo spanning >=%d days'
                   % MIN_GRADE_SPAN_DAYS)
        out.append('  position is still printed above; the track needs more book.')
        reds = []
        vel_reds = []
        path = []
        drift = 0
    else:
        path, drift, max_win, reds = grade_track(pts, wins, opts.cross_bands)
        out.append('  band path:   %s' % ' '.join(str(b) for b in path))
        out.append('  drift %d band(s) over the whole track; steepest single window %d'
               % (drift, max_win))
        vel_reds = [(w.a, w.b) for w in wins if not w.ok]
        infant = [m for m in ms if m.agemo < INFANT_FREE_MONTHS]
        if infant:
            out.append('  (%d infant rows <24mo excluded from grading: physiologic band drift)'
                       % len(infant))
    out.append('')

    # ---- velocity ----
    out.append('VELOCITY (age-segment floors in cm/yr)')
    if wins:
        for w in wins:
            tag = 'OK' if w.ok else 'BELOW FLOOR'
            out.append('  %s -> %s  %5.1f cm/yr  (floor %.1f)  %s'
                       % (w.a.date, w.b.date, w.velocity, w.floor, tag))
        total_days = sum((w.b.date - w.a.date).days for w in wins)
        total_cm = sum((w.b.height - w.a.height) for w in wins)
        whole = total_cm / (total_days / 365.25)
        out.append('  whole-span %.1f cm/yr over %d days (sum of windows, weighted identity)'
                   % (whole, total_days))
    else:
        out.append('  DECLINED  no gradable window')
    out.append('')

    # ---- target height ----
    tgt = target_range(opts, sex)
    below_target = False
    if tgt is None:
        out.append('TARGET HEIGHT  add --mom and --dad to open this page')
    else:
        mid, lo, hi = tgt
        proj = value_at_percentile('HFA', sex_code, 240.0, last.pct())
        out.append('TARGET HEIGHT (mid-parental)  %.1f cm, range [%.1f, %.1f]' % (mid, lo, hi))
        out.append('  last height rides %s -> projects to ~%.1f cm at age 20 on the same band'
                   % (fmt_pct(last.pct()), proj))
        if proj < lo:
            out.append('  projection is BELOW target range')
            below_target = True
        elif proj > hi:
            out.append('  projection is ABOVE target range (no worry direction)')
        else:
            out.append('  projection is inside the range')
    out.append('')

    # ---- BMI track ----
    bpts, bwins = windows(ms, bmi_mode=True, opts=opts)
    bmi_skipped = sum(1 for m in ms if m.weight is not None and m.agemo >= INFANT_FREE_MONTHS
                      and not (8.0 <= m.bmi <= 40.0))
    if bmi_skipped:
        out.append('BMI TRACK  (%d weight row(s) outside plausible BMI 8-40: unit suspect, skipped)'
                   % bmi_skipped)
    out.append('BMI TRACK (%d gradable rows)' % len(bpts))
    if len(bpts) >= 2 and (bpts[-1][0].date - bpts[0][0].date).days >= MIN_GRADE_SPAN_DAYS:
        bpath, bdrift, bmax, breds = grade_track(bpts, bwins, opts.cross_bands)
        out.append('  band path:   %s' % ' '.join(str(b) for b in bpath))
        out.append('  drift %d band(s); steepest single window %d' % (bdrift, bmax))
        if bdrift > 0 or bmax > 0:
            out.append('  upward BMI drift is the earliest signature of childhood'
                       ' obesity (grades at %g bands)' % opts.cross_bands)
        if abs(bdrift) >= opts.cross_bands:
            reds.append(('BMI-DRIFT', bdrift))
        if bmax >= opts.cross_bands:
            reds.append(('BMI-WINDOW', bmax))
    else:
        out.append('  DECLINED  need >=2 rows with weight, age>=24mo, spanning >=%d days'
                   % MIN_GRADE_SPAN_DAYS)
    out.append('')

    # ---- verdict ----
    exit_code = EXIT_OK
    out.append('VERDICT')
    if len(pts) < 2 or (pts[-1][0].date - pts[0][0].date).days < MIN_GRADE_SPAN_DAYS:
        out.append('  thin ledger: grading declined (exit 0), position only')
        return EXIT_OK, out
    red = False
    for kind, n in reds:
        if kind in ('DRIFT',):
            direction = 'DOWN' if n < 0 else 'UP'
            out.append('  RED  height track drifted %d band(s) %s (>= %g): '
                       'growth%s question' % (abs(n), direction, opts.cross_bands,
                                              ' faltering' if n < 0 else ' acceleration'))
            red = True
        elif kind == 'WINDOW':
            out.append('  RED  a single window crossed %d band(s) (>= %g)' % (n, opts.cross_bands))
            red = True
        elif kind == 'BMI-DRIFT':
            direction = 'UP' if n > 0 else 'DOWN'
            out.append('  RED  BMI track drifted %d band(s) %s (>= %g)' % (abs(n), direction,
                                                                           opts.cross_bands))
            red = True
        elif kind == 'BMI-WINDOW':
            out.append('  RED  BMI crossed %d band(s) in one window (>= %g)' % (n, opts.cross_bands))
            red = True
    if vel_reds:
        red = True
        out.append('  RED  %d velocity window(s) below the age floor' % len(vel_reds))
    if red:
        exit_code = EXIT_RED
        out.append('  A red light is a reason to see a pediatric endocrinologist,')
        out.append('  not a diagnosis. Bring this ledger and the well-child booklet.')
    else:
        out.append('  GREEN  on-track: no band-crossing or velocity signal')
    portrait = late_bloomer_portrait(ms, opts, wins)
    if below_target and not red:
        if portrait:
            out.append('  PORTRAIT  below target + family late-bloomer history + pubertal age')
            out.append('  + velocity intact = consistent with constitutional delay.')
            out.append('  This is a picture, not an exemption: bone age is the only referee,')
            out.append('  and this tool refuses to invent it.')
        else:
            out.append('  NOTE  below target range: worth measuring, not yet a signal')
    return exit_code, out


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_track(opts):
    rows, as_of = load(opts.ledger, opts.as_of)
    code = EXIT_OK
    out = ['== %s track — %s (as-of %s) ==' % (PROG, os.path.basename(opts.ledger), as_of)]
    for child, ms in sorted(group_by_child(rows).items()):
        out.append('')
        out.append('child %s  (%s)' % (child, ms[0].sex))
        out.append('  %-11s %-9s %-8s %-7s %s' % ('date', 'age/mo', 'height', 'pct', 'band'))
        pts, wins = windows(ms, False, opts)
        gradable = {id(m) for m, _ in pts}
        for m in ms:
            p = m.pct()
            b = band_of(p)
            mark = '' if m.agemo >= INFANT_FREE_MONTHS else '  (infant: not graded)'
            out.append('  %-11s %-9.1f %-8.1f %-7s %d %s%s'
                       % (m.date, m.agemo, m.height, fmt_pct(p), b, BAND_NAMES[b], mark))
        if len(pts) >= 2:
            path, drift, max_win, _ = grade_track(pts, wins, opts.cross_bands)
            out.append('  drift %d, steepest window %d' % (drift, max_win))
            if abs(drift) >= opts.cross_bands or max_win >= opts.cross_bands:
                code = EXIT_RED
    print('\n'.join(out))
    return code


def cmd_velocity(opts):
    rows, as_of = load(opts.ledger, opts.as_of)
    code = EXIT_OK
    out = ['== %s velocity — %s (as-of %s) ==' % (PROG, os.path.basename(opts.ledger), as_of)]
    for child, ms in sorted(group_by_child(rows).items()):
        out.append('')
        out.append('child %s  (%s)' % (child, ms[0].sex))
        pts, wins = windows(ms, False, opts)
        if not wins:
            out.append('  DECLINED  no gradable window (need two rows >=24mo, >=%d days apart)'
                       % MIN_GRADE_SPAN_DAYS)
            continue
        out.append('  %-11s %-11s %-10s %-10s %s' % ('from', 'to', 'cm/yr', 'floor', 'verdict'))
        for w in wins:
            out.append('  %-11s %-11s %-10.1f %-10.1f %s'
                       % (w.a.date, w.b.date, w.velocity, w.floor, 'OK' if w.ok else 'BELOW'))
        if any(not w.ok for w in wins):
            code = EXIT_RED
        total_days = sum((w.b.date - w.a.date).days for w in wins)
        total_cm = sum(w.b.height - w.a.height for w in wins)
        out.append('  identity: sum(window days)=%d  sum(window cm)=%.1f  whole=%.1f cm/yr'
                   % (total_days, total_cm, total_cm / (total_days / 365.25)))
    print('\n'.join(out))
    return code


def cmd_target(opts):
    rows, as_of = load(opts.ledger, opts.as_of)
    if opts.mom is None or opts.dad is None:
        raise UsageError('target needs --mom and --dad')
    out = ['== %s target — %s (as-of %s) ==' % (PROG, os.path.basename(opts.ledger), as_of)]
    code = EXIT_OK
    for child, ms in sorted(group_by_child(rows).items()):
        sex = ms[0].sex
        mid, lo, hi = target_range(opts, sex)
        last = ms[-1]
        out.append('')
        out.append('child %s  (%s)' % (child, sex))
        out.append('  mid-parental target  %.1f cm  range [%.1f, %.1f]  (spread %.1f)'
                   % (mid, lo, hi, opts.target_spread))
        p = last.pct()
        proj = value_at_percentile('HFA', 1 if sex == 'M' else 2, 240.0, p)
        out.append('  last height %.1f cm at %s = %.1f cm at age 20 on the same band'
                   % (last.height, fmt_pct(p), proj))
        if proj < lo:
            out.append('  BELOW range: track the height band and velocity, and mention')
            out.append('  this ledger to the pediatrician — below target alone is a')
            out.append('  picture, not a diagnosis')
        elif proj > hi:
            out.append('  ABOVE range: no worry direction for stature')
        else:
            out.append('  inside range')
    print('\n'.join(out))
    return code


def cmd_next(opts):
    rows, as_of = load(opts.ledger, opts.as_of)
    out = ['== %s next — %s (as-of %s) ==' % (PROG, os.path.basename(opts.ledger), as_of)]
    code = EXIT_OK
    for child, ms in sorted(group_by_child(rows).items()):
        sex = ms[0].sex
        sex_code = 1 if sex == 'M' else 2
        last = ms[-1]
        if opts.next_at:
            nxt = parse_date(opts.next_at, 0, 'next-at')
        else:
            nxt = last.date + timedelta(days=182)
        nxt_agemo = (nxt - last.born).days / MONTH
        if nxt_agemo > ADULT_MONTHS:
            raise UsageError('next-at %s is beyond the reference tables for %s' % (nxt, child))
        out.append('')
        out.append('child %s  (%s)  next visit %s (age %.1f mo)'
                   % (child, sex, nxt, nxt_agemo))
        if last.agemo < INFANT_FREE_MONTHS:
            out.append('  note: last row is <24mo; band grading starts at 24mo,')
            out.append('  infant drift is physiologic — corridor below is advisory only')
        b = band_of(last.pct())
        cur_lo = band_floor_value('HFA', sex_code, nxt_agemo, b)
        redline = band_floor_value('HFA', sex_code, nxt_agemo, b - 1) if b >= 2 else None
        red_up = value_at_percentile('HFA', sex_code, nxt_agemo,
                                     BANDS[min(int(b + opts.cross_bands) - 1, 6)])
        if cur_lo is not None:
            out.append('  stay on band %d (%s):   height >= %.1f cm' % (b, BAND_NAMES[b], cur_lo))
        elif b == 0:
            out.append('  already below P3: the velocity floor below guards the bottom')
        if redline is not None:
            out.append('  1-band-down watch:     [%.1f, %.1f) cm  (crossing one band,'
                       ' not yet an alarm)' % (redline, cur_lo))
            out.append('  RED LINE (%g bands down): height <  %.1f cm' % (opts.cross_bands, redline))
        else:
            out.append('  no red line below: already in the second-lowest band;')
            out.append('  the velocity floor is the remaining guard down here')
        out.append('  upward watch line:     height >  %.1f cm' % red_up)
        wins = windows(ms, False, opts)[1]
        if wins and wins[-1].ok:
            projected = last.height + wins[-1].velocity * ((nxt - last.date).days / 365.25)
            out.append('  if last velocity (%.1f cm/yr) holds: ~%.1f cm' % (wins[-1].velocity, projected))
        out.append('  bring this line and the booklet to the visit; measuring technique')
        out.append('  matters — same measurer, shoes off, morning if possible')
    print('\n'.join(out))
    return code


def cmd_validate(opts):
    rows, as_of = load(opts.ledger, opts.as_of)
    out = ['== %s validate — %s ==' % (PROG, os.path.basename(opts.ledger))]
    failures = []

    def check(name, ok, detail=''):
        out.append('  [%s] %s %s' % ('OK' if ok else 'FAIL', name, detail))
        if not ok:
            failures.append(name)

    # engine self-checks
    bad_nodes = 0
    for sex in (1, 2):
        for agemo, L, M, S in TABLES['HFA'][sex]:
            if abs(value_at_percentile('HFA', sex, agemo, 50.0) - M) > 1e-6 * max(1.0, M):
                bad_nodes += 1
            if abs(percentile_of('HFA', sex, agemo, M) - 50.0) > 1e-6:
                bad_nodes += 1
    check('LMS round-trip at every node (pct(M)==50, value(P50)==M)', bad_nodes == 0,
          '%d bad node(s)' % bad_nodes)
    mono_bad = 0
    for sex in (1, 2):
        for agemo in (0.0, 6.0, 24.0, 60.0, 120.0, 200.0, 240.0):
            vals = [value_at_percentile('HFA', sex, agemo, p) for p in (1.0, 3.0, 10.0, 25.0,
                                                                       50.0, 75.0, 90.0, 97.0, 99.0)]
            if any(b <= a for a, b in zip(vals, vals[1:])):
                mono_bad += 1
    check('value_at_percentile strictly increasing in p', mono_bad == 0)
    expect = {0.5: 0, 5.0: 1, 15.0: 2, 30.0: 3, 60.0: 4, 80.0: 5, 95.0: 6, 98.0: 7}
    band_bad = sum(1 for p, b in expect.items() if band_of(p) != b)
    check('band_of mapping on both sides of every line', band_bad == 0)
    edge_bad = sum(1 for line in BANDS
                   if band_of(line) != sum(1 for t in BANDS if line >= t))
    check('band edge convention: a percentile on a line belongs to the higher band', edge_bad == 0)

    # ledger identities
    for child, ms in sorted(group_by_child(rows).items()):
        pts, wins = windows(ms, False, opts)
        if len(pts) >= 2:
            signed = [w.drift for w in wins]
            # band index telescoping: sum of signed window drifts == last-first
            path = [band_of(p) for _, p in pts]
            check('%s: band drift telescoping (sum windows == whole path)'
                  % child, sum(signed) == path[-1] - path[0])
            if wins:
                total_days = sum((w.b.date - w.a.date).days for w in wins)
                total_cm = sum(w.b.height - w.a.height for w in wins)
                recomposed = sum(((w.b.date - w.a.date).days / 365.25) * w.velocity for w in wins)
                check('%s: velocity weighted identity (sum w*days == sum cm)'
                      % child, abs(recomposed - total_cm) < 1e-6,
                      '(%.6f vs %.6f)' % (recomposed, total_cm))
        check('%s: BMI recomputation identity (weight/height^2)' % child,
              all(abs(m.bmi - m.weight / (m.height / 100.0) ** 2) < 1e-9
                  for m in ms if m.weight is not None))
    print('\n'.join(out))
    if failures:
        print('validate: %d FAILURE(S): %s' % (len(failures), ', '.join(failures)), file=sys.stderr)
        return EXIT_BROKEN
    print('validate: all checks OK')
    return EXIT_OK


def cmd_report(opts):
    rows, as_of = load(opts.ledger, opts.as_of)
    out = ['== %s report — %s (as-of %s) ==' % (PROG, os.path.basename(opts.ledger), as_of)]
    out.append('')
    out.append('ledger: %d measurement row(s), %d child(ren)'
               % (len(rows), len(group_by_child(rows))))
    out.append('"short" is a position; "off-track" is a direction. This report grades direction.')
    out.append('')
    code = EXIT_OK
    for child, ms in sorted(group_by_child(rows).items()):
        code_child, lines = child_report(ms, opts, as_of, [])
        out.extend(lines)
        if code_child == EXIT_RED:
            code = EXIT_RED
        out.append('')
    out.append('Not medical advice. Thresholds are common priors and every one of them')
    out.append('is a -- flag; the pediatrician and the booklet win over this tool.')
    print('\n'.join(out))
    return code


COMMANDS = {'report': cmd_report, 'track': cmd_track, 'velocity': cmd_velocity,
            'target': cmd_target, 'next': cmd_next, 'validate': cmd_validate}


def main(argv=None):
    ap = base_parser()
    opts = ap.parse_args(argv)
    if not opts.cmd:
        ap.print_help()
        return EXIT_BROKEN
    try:
        return COMMANDS[opts.cmd](opts)
    except LedgerError as e:
        print('%s: broken ledger: %s' % (PROG, e), file=sys.stderr)
        return EXIT_BROKEN
    except UsageError as e:
        print('%s: %s' % (PROG, e), file=sys.stderr)
        return EXIT_BROKEN


# --------------------------------------------------------------------------
# Embedded LMS reference tables (Sex, Agemos, L, M, S). Verbatim subset of
# the CDC percentile data files: HFA = WHO 2006 length-for-age (0-24m) +
# CDC 2000 stature-for-age (24.5-240.5m); BMI = CDC 2000 BMI-for-age.
# Pinned by references/*.csv; regenerate via references/embed_tables.py.
# --------------------------------------------------------------------------

HFA_DATA = """\
1 0.0 1.267004226 49.98888408 0.053112191
1 0.5 0.511237696 52.6959753 0.048692684
1 1.5 -0.45224446 56.62842855 0.04411683
1 2.5 -0.990594599 59.60895343 0.041795583
1 3.5 -1.285837689 62.07700027 0.040454126
1 4.5 -1.43031238 64.2168641 0.039633879
1 5.5 -1.47657547 66.1253149 0.039123813
1 6.5 -1.456837849 67.8601799 0.038811994
1 7.5 -1.391898768 69.45908458 0.038633209
1 8.5 -1.29571459 70.94803912 0.038546833
1 9.5 -1.177919048 72.34586111 0.038526262
1 10.5 -1.045326049 73.6666541 0.038553387
1 11.5 -0.902800887 74.92129717 0.038615501
1 12.5 -0.753908107 76.11837536 0.038703461
1 13.5 -0.601263523 77.26479911 0.038810557
1 14.5 -0.446805039 78.36622309 0.038931784
1 15.5 -0.291974772 79.4273405 0.039063356
1 16.5 -0.13784767 80.45209492 0.039202382
1 17.5 0.014776155 81.44383603 0.039346629
1 18.5 0.165304169 82.40543643 0.039494365
1 19.5 0.313301809 83.33938063 0.039644238
1 20.5 0.458455471 84.24783394 0.039795189
1 21.5 0.600544631 85.13269658 0.039946388
1 22.5 0.739438953 85.9956488 0.040097181
1 23.5 0.875000447 86.8381751 0.04024706
1 24.5 1.00720807 86.86160934 0.040395626
1 25.5 0.837251351 87.65247282 0.040577525
1 26.5 0.681492975 88.42326434 0.040723122
1 27.5 0.538779654 89.17549228 0.040833194
1 28.5 0.407697153 89.91040853 0.040909059
1 29.5 0.286762453 90.62907762 0.040952433
1 30.5 0.174489485 91.33242379 0.04096533
1 31.5 0.069444521 92.02127167 0.040949976
1 32.5 -0.029720564 92.69637946 0.040908737
1 33.5 -0.124251789 93.35846546 0.040844062
1 34.5 -0.215288396 94.00822923 0.040758431
1 35.5 -0.30385434 94.64636981 0.040654312
1 36.5 -0.390918369 95.27359106 0.04053412
1 37.5 -0.254801167 95.91474929 0.040572876
1 38.5 -0.125654535 96.54734328 0.04061691
1 39.5 -0.00316735 97.17191309 0.040666414
1 40.5 0.11291221 97.78897727 0.040721467
1 41.5 0.222754969 98.3990283 0.040782045
1 42.5 0.326530126 99.00254338 0.040848042
1 43.5 0.42436156 99.599977 0.040919281
1 44.5 0.516353108 100.191764 0.040995524
1 45.5 0.602595306 100.7783198 0.041076485
1 46.5 0.683170764 101.3600411 0.041161838
1 47.5 0.758158406 101.9373058 0.041251224
1 48.5 0.827636736 102.5104735 0.041344257
1 49.5 0.891686306 103.0798852 0.041440534
1 50.5 0.95039153 103.645864 0.041539635
1 51.5 1.003830006 104.208713 0.041641136
1 52.5 1.05213569 104.7687256 0.041744602
1 53.5 1.0953669 105.3261638 0.041849607
1 54.5 1.133652119 105.8812823 0.041955723
1 55.5 1.167104213 106.4343146 0.042062532
1 56.5 1.195845353 106.9854769 0.042169628
1 57.5 1.220004233 107.534968 0.042276619
1 58.5 1.239715856 108.0829695 0.042383129
1 59.5 1.255121285 108.6296457 0.042488804
1 60.5 1.266367398 109.1751441 0.042593311
1 61.5 1.273606657 109.7195954 0.042696342
1 62.5 1.276996893 110.2631136 0.042797615
1 63.5 1.276701119 110.8057967 0.042896877
1 64.5 1.272887366 111.3477265 0.042993904
1 65.5 1.265728536 111.8889694 0.043088503
1 66.5 1.255402281 112.4295761 0.043180513
1 67.5 1.242090871 112.9695827 0.043269806
1 68.5 1.225981067 113.5090108 0.043356287
1 69.5 1.207263978 114.0478678 0.043439893
1 70.5 1.186140222 114.5861486 0.043520597
1 71.5 1.162796198 115.1238315 0.043598407
1 72.5 1.137442868 115.6608862 0.043673359
1 73.5 1.110286487 116.1972691 0.043745523
1 74.5 1.081536236 116.732925 0.043815003
1 75.5 1.05140374 117.2677879 0.043881929
1 76.5 1.020102497 117.8017819 0.043946461
1 77.5 0.987847213 118.3348215 0.044008785
1 78.5 0.954853043 118.8668123 0.044069112
1 79.5 0.921334742 119.397652 0.044127675
1 80.5 0.887505723 119.9272309 0.044184725
1 81.5 0.85357703 120.455433 0.044240532
1 82.5 0.819756239 120.9821362 0.044295379
1 83.5 0.786246296 121.5072136 0.044349559
1 84.5 0.753244292 122.0305342 0.044403374
1 85.5 0.720940222 122.5519634 0.04445713
1 86.5 0.689515708 123.0713645 0.044511135
1 87.5 0.659142731 123.588599 0.044565693
1 88.5 0.629997853 124.1035312 0.044621104
1 89.5 0.602203984 124.6160161 0.044677662
1 90.5 0.575908038 125.1259182 0.044735646
1 91.5 0.55123134 125.6331012 0.044795322
1 92.5 0.528279901 126.1374319 0.044856941
1 93.5 0.507143576 126.6387804 0.04492073
1 94.5 0.487895344 127.1370217 0.044986899
1 95.5 0.470590753 127.6320362 0.045055632
1 96.5 0.455267507 128.1237104 0.045127088
1 97.5 0.441945241 128.6119383 0.045201399
1 98.5 0.430625458 129.096622 0.045278671
1 99.5 0.421291648 129.5776723 0.045358979
1 100.5 0.413909588 130.0550101 0.045442372
1 101.5 0.408427813 130.5285669 0.045528869
1 102.5 0.404778262 130.9982857 0.045618459
1 103.5 0.402877077 131.4641218 0.045711105
1 104.5 0.402625561 131.9260439 0.045806742
1 105.5 0.40391127 132.3840348 0.045905281
1 106.5 0.406609232 132.838092 0.046006604
1 107.5 0.410583274 133.2882291 0.046110573
1 108.5 0.415687443 133.7344759 0.046217028
1 109.5 0.421767514 134.1768801 0.04632579
1 110.5 0.428662551 134.6155076 0.046436662
1 111.5 0.436206531 135.0504433 0.04654943
1 112.5 0.44423 135.4817925 0.046663871
1 113.5 0.45256176 135.9096813 0.046779748
1 114.5 0.461030578 136.3342577 0.046896817
1 115.5 0.469466904 136.7556923 0.047014827
1 116.5 0.477704608 137.1741794 0.047133525
1 117.5 0.48558272 137.5899378 0.047252654
1 118.5 0.492947182 138.0032114 0.047371961
1 119.5 0.499652617 138.4142703 0.047491194
1 120.5 0.505564115 138.8234114 0.047610108
1 121.5 0.510559047 139.2309592 0.047728463
1 122.5 0.514528903 139.6372663 0.04784603
1 123.5 0.517381177 140.042714 0.047962592
1 124.5 0.519041285 140.4477127 0.048077942
1 125.5 0.519454524 140.8527022 0.048191889
1 126.5 0.518588072 141.2581515 0.048304259
1 127.5 0.516433004 141.6645592 0.048414893
1 128.5 0.513006312 142.072452 0.048523648
1 129.5 0.508352901 142.4823852 0.048630402
1 130.5 0.502547502 142.8949403 0.04873505
1 131.5 0.495696454 143.3107241 0.048837504
1 132.5 0.487939275 143.7303663 0.048937694
1 133.5 0.479449924 144.1545167 0.049035564
1 134.5 0.470437652 144.5838414 0.049131073
1 135.5 0.461147305 145.0190192 0.049224189
1 136.5 0.451858946 145.4607359 0.049314887
1 137.5 0.442886661 145.9096784 0.049403145
1 138.5 0.434576385 146.3665278 0.049488934
1 139.5 0.427302633 146.8319513 0.049572216
1 140.5 0.421464027 147.3065929 0.049652935
1 141.5 0.417477538 147.7910635 0.049731004
1 142.5 0.415771438 148.2859294 0.0498063
1 143.5 0.416777012 148.7917006 0.04987865
1 144.5 0.420919142 149.3088178 0.049947823
1 145.5 0.428606007 149.8376391 0.050013518
1 146.5 0.440218167 150.3784267 0.050075353
1 147.5 0.456097443 150.9313331 0.050132858
1 148.5 0.476536014 151.4963887 0.050185471
1 149.5 0.501766234 152.0734897 0.050232532
1 150.5 0.531951655 152.6623878 0.050273285
1 151.5 0.567179725 153.2626819 0.050306885
1 152.5 0.607456565 153.8738124 0.050332406
1 153.5 0.652704121 154.495058 0.05034886
1 154.5 0.702759868 155.1255365 0.050355216
1 155.5 0.757379106 155.7642086 0.050350423
1 156.5 0.816239713 156.4098858 0.050333444
1 157.5 0.878947416 157.0612415 0.050303283
1 158.5 0.945053486 157.7168289 0.050259018
1 159.5 1.014046108 158.3750929 0.050199837
1 160.5 1.085383319 159.034399 0.050125062
1 161.5 1.158487278 159.6930501 0.05003418
1 162.5 1.232768816 160.3493168 0.049926861
1 163.5 1.307628899 161.0014586 0.049802977
1 164.5 1.382473225 161.6477515 0.04966261
1 165.5 1.456720479 162.2865119 0.049506051
1 166.5 1.529810247 162.9161202 0.049333801
1 167.5 1.601219573 163.535045 0.049146553
1 168.5 1.670433444 164.1418486 0.04894519
1 169.5 1.736995571 164.7352199 0.048730749
1 170.5 1.800483802 165.3139755 0.048504404
1 171.5 1.860518777 165.8770715 0.048267442
1 172.5 1.916765525 166.4236087 0.04802123
1 173.5 1.968934444 166.9528354 0.047767192
1 174.5 2.016781776 167.4641466 0.047506783
1 175.5 2.060109658 167.9570814 0.047241456
1 176.5 2.098765817 168.4313175 0.04697265
1 177.5 2.132642948 168.8866644 0.046701759
1 178.5 2.16167779 169.3230548 0.046430122
1 179.5 2.185849904 169.7405351 0.046159004
1 180.5 2.205180153 170.139255 0.045889585
1 181.5 2.219728869 170.5194567 0.045622955
1 182.5 2.2295937 170.881464 0.045360101
1 183.5 2.234907144 171.2256717 0.045101913
1 184.5 2.235833767 171.5525345 0.044849174
1 185.5 2.232567138 171.8625576 0.044602566
1 186.5 2.2253265 172.1562865 0.044362674
1 187.5 2.214353232 172.4342983 0.044129985
1 188.5 2.199905902 172.6971935 0.043904897
1 189.5 2.182262864 172.9455898 0.043687723
1 190.5 2.161704969 173.180112 0.043478698
1 191.5 2.138524662 173.4013896 0.043277987
1 192.5 2.113023423 173.6100518 0.043085685
1 193.5 2.085490286 173.8067179 0.042901835
1 194.5 2.0562195 173.9919998 0.042726424
1 195.5 2.025496648 174.1664951 0.042559396
1 196.5 1.993598182 174.3307855 0.042400652
1 197.5 1.960789092 174.4854344 0.042250063
1 198.5 1.927320937 174.6309856 0.042107465
1 199.5 1.89343024 174.7679617 0.041972676
1 200.5 1.859337259 174.8968634 0.041845488
1 201.5 1.825245107 175.0181691 0.041725679
1 202.5 1.791339209 175.1323345 0.041613015
1 203.5 1.757787065 175.2397926 0.041507249
1 204.5 1.724738292 175.340954 0.041408129
1 205.5 1.692324905 175.4362071 0.041315398
1 206.5 1.660661815 175.5259191 0.041228796
1 207.5 1.629847495 175.6104358 0.04114806
1 208.5 1.599964788 175.690083 0.041072931
1 209.5 1.571081817 175.7651671 0.04100315
1 210.5 1.543252982 175.8359757 0.040938463
1 211.5 1.516519998 175.9027788 0.040878617
1 212.5 1.490912963 175.9658293 0.040823368
1 213.5 1.466451429 176.0253641 0.040772475
1 214.5 1.44314546 176.081605 0.040725706
1 215.5 1.420996665 176.1347593 0.040682834
1 216.5 1.399999187 176.1850208 0.04064364
1 217.5 1.380140651 176.2325707 0.040607913
1 218.5 1.361403047 176.2775781 0.040575448
1 219.5 1.343763564 176.3202008 0.040546051
1 220.5 1.327195355 176.3605864 0.040519532
1 221.5 1.311668242 176.3988725 0.040495713
1 222.5 1.297149359 176.4351874 0.040474421
1 223.5 1.283603728 176.469651 0.040455493
1 224.5 1.270994782 176.5023751 0.040438773
1 225.5 1.25928483 176.533464 0.040424111
1 226.5 1.248435461 176.5630153 0.040411366
1 227.5 1.23840791 176.5911197 0.040400405
1 228.5 1.229163362 176.6178621 0.040391101
1 229.5 1.220663228 176.6433219 0.040383334
1 230.5 1.212869374 176.6675729 0.04037699
1 231.5 1.20574431 176.6906844 0.040371962
1 232.5 1.199251356 176.712721 0.040368149
1 233.5 1.19335477 176.733743 0.040365456
1 234.5 1.188019859 176.753807 0.040363795
1 235.5 1.183213059 176.7729657 0.04036308
1 236.5 1.178901998 176.7912687 0.040363233
1 237.5 1.175055543 176.8087622 0.040364179
1 238.5 1.171643828 176.8254895 0.04036585
1 239.5 1.16863827 176.8414914 0.04036818
1 240.0 1.167279219 176.8492322 0.040369574
2 0.0 -1.295960857 49.28639612 0.05008556
2 0.5 -0.809249882 51.68358057 0.046818545
2 1.5 -0.050782985 55.28612813 0.0434439
2 2.5 0.476851407 58.09381906 0.041716103
2 3.5 0.843299612 60.45980763 0.040705173
2 4.5 1.097562257 62.53669656 0.040079765
2 5.5 1.272509641 64.40632762 0.039686845
2 6.5 1.390428859 66.11841553 0.039444555
2 7.5 1.466733925 67.70574419 0.039304738
2 8.5 1.512301976 69.19123614 0.03923711
2 9.5 1.534950767 70.59163924 0.039221665
2 10.5 1.540390875 71.91961673 0.039244672
2 11.5 1.532852892 73.1850104 0.03929642
2 12.5 1.51550947 74.39564379 0.039369875
2 13.5 1.490765028 75.5578544 0.039459832
2 14.5 1.460458255 76.67685871 0.039562382
2 15.5 1.426006009 77.75700986 0.039674542
2 16.5 1.388507095 78.80198406 0.03979401
2 17.5 1.348818127 79.81491852 0.039918994
2 18.5 1.307609654 80.79851532 0.040048084
2 19.5 1.265408149 81.75512092 0.040180162
2 20.5 1.222627732 82.6867881 0.04031434
2 21.5 1.179594365 83.59532461 0.040449904
2 22.5 1.136564448 84.48233206 0.040586283
2 23.5 1.093731947 85.34923624 0.040723015
2 24.5 1.051272912 85.3973169 0.040859727
2 25.5 1.041951175 86.29026318 0.041142161
2 26.5 1.012592236 87.15714182 0.041349399
2 27.5 0.970541909 87.9960184 0.041500428
2 28.5 0.921129988 88.8055115 0.041610508
2 29.5 0.868221392 89.58476689 0.041691761
2 30.5 0.81454413 90.33341722 0.04175368
2 31.5 0.761957977 91.0515436 0.041803562
2 32.5 0.711660228 91.7396352 0.041846882
2 33.5 0.664323379 92.39854429 0.041887626
2 34.5 0.620285102 93.02945392 0.041928568
2 35.5 0.57955631 93.63382278 0.041971514
2 36.5 0.54198094 94.21335709 0.042017509
2 37.5 0.511429832 94.79643239 0.042104522
2 38.5 0.482799937 95.37391918 0.042199507
2 39.5 0.455521041 95.94692677 0.042300333
2 40.5 0.429150288 96.51644912 0.042405225
2 41.5 0.403351725 97.08337211 0.042512706
2 42.5 0.377878239 97.6484807 0.042621565
2 43.5 0.352555862 98.21246579 0.042730809
2 44.5 0.327270297 98.77593069 0.042839638
2 45.5 0.301955463 99.33939735 0.042947412
2 46.5 0.276583851 99.9033122 0.043053626
2 47.5 0.251158446 100.4680516 0.043157889
2 48.5 0.225705996 101.033927 0.043259907
2 49.5 0.20027145 101.6011898 0.043359463
2 50.5 0.174913356 102.1700358 0.043456406
2 51.5 0.149700081 102.7406094 0.043550638
2 52.5 0.12470671 103.3130077 0.043642107
2 53.5 0.100012514 103.8872839 0.043730791
2 54.5 0.075698881 104.4634511 0.043816701
2 55.5 0.051847635 105.0414853 0.043899867
2 56.5 0.02853967 105.6213287 0.043980337
2 57.5 0.005853853 106.2028921 0.044058171
2 58.5 -0.016133871 106.7860583 0.04413344
2 59.5 -0.037351181 107.3706841 0.044206218
2 60.5 -0.057729947 107.9566031 0.044276588
2 61.5 -0.077206672 108.5436278 0.044344632
2 62.5 -0.09572283 109.1315521 0.044410436
2 63.5 -0.113225128 109.7201531 0.044474084
2 64.5 -0.129665689 110.3091934 0.044535662
2 65.5 -0.145002179 110.8984228 0.044595254
2 66.5 -0.159197885 111.4875806 0.044652942
2 67.5 -0.172221748 112.0763967 0.044708809
2 68.5 -0.184048358 112.6645943 0.044762936
2 69.5 -0.194660215 113.2518902 0.044815402
2 70.5 -0.204030559 113.8380006 0.044866288
2 71.5 -0.212174408 114.4226317 0.044915672
2 72.5 -0.219069129 115.0054978 0.044963636
2 73.5 -0.224722166 115.5863089 0.045010259
2 74.5 -0.229140412 116.1647782 0.045055624
2 75.5 -0.232335686 116.7406221 0.045099817
2 76.5 -0.234324563 117.3135622 0.045142924
2 77.5 -0.235128195 117.8833259 0.045185036
2 78.5 -0.234772114 118.4496481 0.045226249
2 79.5 -0.233286033 119.0122722 0.045266662
2 80.5 -0.230703633 119.5709513 0.045306383
2 81.5 -0.227062344 120.1254495 0.045345524
2 82.5 -0.222403111 120.6755427 0.045384203
2 83.5 -0.216770161 121.22102 0.045422551
2 84.5 -0.210210748 121.7616844 0.045460702
2 85.5 -0.202774891 122.2973542 0.045498803
2 86.5 -0.194515104 122.827864 0.045537012
2 87.5 -0.185486099 123.3530652 0.045575495
2 88.5 -0.175744476 123.8728276 0.045614432
2 89.5 -0.165348396 124.38704 0.045654016
2 90.5 -0.15435722 124.8956114 0.04569445
2 91.5 -0.142831123 125.398472 0.045735953
2 92.5 -0.130830669 125.895574 0.045778759
2 93.5 -0.118416354 126.3868929 0.045823114
2 94.5 -0.105648092 126.8724284 0.04586928
2 95.5 -0.092584657 127.3522056 0.045917535
2 96.5 -0.079283065 127.8262759 0.045968169
2 97.5 -0.065797888 128.2947187 0.04602149
2 98.5 -0.0521805 128.757642 0.046077818
2 99.5 -0.03847825 129.2151839 0.046137487
2 100.5 -0.024733545 129.6675143 0.046200842
2 101.5 -0.010982868 130.1148354 0.04626824
2 102.5 0.002744306 130.5573839 0.046340046
2 103.5 0.016426655 130.995432 0.046416629
2 104.5 0.030052231 131.4292887 0.046498361
2 105.5 0.043619747 131.8593015 0.046585611
2 106.5 0.05713988 132.2858574 0.046678741
2 107.5 0.070636605 132.7093845 0.046778099
2 108.5 0.08414848 133.1303527 0.04688401
2 109.5 0.097729873 133.5492749 0.046996769
2 110.5 0.111452039 133.9667073 0.047116633
2 111.5 0.125404005 134.3832499 0.047243801
2 112.5 0.13969316 134.7995463 0.047378413
2 113.5 0.154445482 135.2162826 0.047520521
2 114.5 0.169805275 135.634186 0.047670085
2 115.5 0.185934346 136.0540223 0.047826946
2 116.5 0.203010488 136.4765925 0.04799081
2 117.5 0.2212252 136.9027281 0.048161228
2 118.5 0.240780542 137.3332846 0.04833757
2 119.5 0.261885086 137.7691339 0.048519011
2 120.5 0.284748919 138.2111552 0.048704503
2 121.5 0.309577733 138.6602228 0.048892759
2 122.5 0.336566048 139.1171933 0.049082239
2 123.5 0.365889711 139.5828898 0.049271137
2 124.5 0.397699038 140.0580848 0.049457371
2 125.5 0.432104409 140.5434787 0.049638596
2 126.5 0.46917993 141.0396832 0.049812203
2 127.5 0.508943272 141.5471945 0.049975355
2 128.5 0.551354277 142.0663731 0.050125012
2 129.5 0.596307363 142.59742 0.050257992
2 130.5 0.643626542 143.1403553 0.050371024
2 131.5 0.693062173 143.6949981 0.050460835
2 132.5 0.744289752 144.2609497 0.050524236
2 133.5 0.79691098 144.8375809 0.050558224
2 134.5 0.85045728 145.4240246 0.050560083
2 135.5 0.904395871 146.0191748 0.050527494
2 136.5 0.958138449 146.621692 0.050458634
2 137.5 1.011054559 147.2300177 0.050352269
2 138.5 1.062474568 147.8423918 0.050207825
2 139.5 1.111727029 148.4568879 0.050025434
2 140.5 1.158135105 149.0714413 0.049805967
2 141.5 1.201050821 149.6838943 0.049551023
2 142.5 1.239852328 150.2920328 0.049262895
2 143.5 1.274006058 150.8936469 0.048944504
2 144.5 1.303044695 151.4865636 0.048599314
2 145.5 1.326605954 152.0686985 0.048231224
2 146.5 1.344443447 152.6380955 0.047844442
2 147.5 1.356437773 153.1929631 0.047443362
2 148.5 1.362602695 153.7317031 0.04703243
2 149.5 1.363085725 154.2529332 0.046616026
2 150.5 1.358162799 154.755501 0.046198356
2 151.5 1.348227142 155.2384904 0.04578335
2 152.5 1.333772923 155.7012216 0.045374597
2 153.5 1.315374704 156.1432438 0.044975281
2 154.5 1.293664024 156.564323 0.044588148
2 155.5 1.269304678 156.9644258 0.044215488
2 156.5 1.242968236 157.3436995 0.043859135
2 157.5 1.21531127 157.7024507 0.04352048
2 158.5 1.186955477 158.0411233 0.043200497
2 159.5 1.158471522 158.3602756 0.042899776
2 160.5 1.130367088 158.6605588 0.042618565
2 161.5 1.103079209 158.9426964 0.042356812
2 162.5 1.076970655 159.2074654 0.042114211
2 163.5 1.052329922 159.455679 0.041890247
2 164.5 1.029374161 159.688172 0.04168424
2 165.5 1.008254396 159.9057871 0.041495379
2 166.5 0.989062282 160.1093647 0.041322765
2 167.5 0.971837799 160.299733 0.041165437
2 168.5 0.95657215 160.4776996 0.041022401
2 169.5 0.94324228 160.6440526 0.040892651
2 170.5 0.931767062 160.7995428 0.040775193
2 171.5 0.922058291 160.9448916 0.040669052
2 172.5 0.914012643 161.0807857 0.040573288
2 173.5 0.907516917 161.2078755 0.040487005
2 174.5 0.902452436 161.3267744 0.040409354
2 175.5 0.898698641 161.4380593 0.040339537
2 176.5 0.896143482 161.5422726 0.040276811
2 177.5 0.894659668 161.639917 0.040220488
2 178.5 0.89413892 161.7314645 0.040169932
2 179.5 0.894475371 161.8173534 0.040124562
2 180.5 0.895569834 161.8979913 0.040083845
2 181.5 0.897330209 161.9737558 0.040047295
2 182.5 0.899671635 162.0449969 0.040014473
2 183.5 0.902516442 162.1120386 0.03998498
2 184.5 0.905793969 162.17518 0.039958458
2 185.5 0.909440266 162.2346979 0.039934584
2 186.5 0.913397733 162.2908474 0.039913066
2 187.5 0.91761471 162.343864 0.039893644
2 188.5 0.922045055 162.3939652 0.039876087
2 189.5 0.926647697 162.4413513 0.039860185
2 190.5 0.931386217 162.4862071 0.039845754
2 191.5 0.93622842 162.5287029 0.039832629
2 192.5 0.941145943 162.5689958 0.039820663
2 193.5 0.94611388 162.6072309 0.039809725
2 194.5 0.95111043 162.6435418 0.0397997
2 195.5 0.956116576 162.6780519 0.039790485
2 196.5 0.961115792 162.7108751 0.039781991
2 197.5 0.966093766 162.7421168 0.039774136
2 198.5 0.971038162 162.7718741 0.03976685
2 199.5 0.975938391 162.8002371 0.03976007
2 200.5 0.980785418 162.8272889 0.039753741
2 201.5 0.985571579 162.8531067 0.039747815
2 202.5 0.99029042 162.8777619 0.039742249
2 203.5 0.994936555 162.9013208 0.039737004
2 204.5 0.999505539 162.9238449 0.039732048
2 205.5 1.003993753 162.9453912 0.039727352
2 206.5 1.0083983 162.9660131 0.03972289
2 207.5 1.012716921 162.9857599 0.03971864
2 208.5 1.016947912 163.0046776 0.039714581
2 209.5 1.021090055 163.0228094 0.039710697
2 210.5 1.025142554 163.0401953 0.039706971
2 211.5 1.029104983 163.0568727 0.039703391
2 212.5 1.032977233 163.0728768 0.039699945
2 213.5 1.036759475 163.0882404 0.039696623
2 214.5 1.040452117 163.1029943 0.039693415
2 215.5 1.044055774 163.1171673 0.039690313
2 216.5 1.047571238 163.1307866 0.039687311
2 217.5 1.050999451 163.1438776 0.039684402
2 218.5 1.054341482 163.1564644 0.039681581
2 219.5 1.057598512 163.1685697 0.039678842
2 220.5 1.060771808 163.1802146 0.039676182
2 221.5 1.063862715 163.1914194 0.039673596
2 222.5 1.066872639 163.202203 0.039671082
2 223.5 1.069803036 163.2125835 0.039668635
2 224.5 1.072655401 163.2225779 0.039666254
2 225.5 1.075431258 163.2322024 0.039663936
2 226.5 1.078132156 163.2414722 0.039661679
2 227.5 1.080759655 163.2504019 0.039659481
2 228.5 1.083315329 163.2590052 0.039657339
2 229.5 1.085800751 163.2672954 0.039655252
2 230.5 1.088217496 163.2752848 0.039653218
2 231.5 1.090567133 163.2829854 0.039651237
2 232.5 1.092851222 163.2904086 0.039649306
2 233.5 1.095071313 163.297565 0.039647424
2 234.5 1.097228939 163.304465 0.039645591
2 235.5 1.099325619 163.3111185 0.039643804
2 236.5 1.101362852 163.3175349 0.039642063
2 237.5 1.103342119 163.3237231 0.039640367
2 238.5 1.105264876 163.3296918 0.039638715
2 239.5 1.107132561 163.3354491 0.039637105
2 240.0 1.108046193 163.338251 0.039636316
"""

BMI_DATA = """\
1 24.0 -2.01118107 16.57502768 0.080592465
1 24.5 -1.982373595 16.54777487 0.080127429
1 25.5 -1.924100169 16.49442763 0.079233994
1 26.5 -1.86549793 16.44259552 0.078389356
1 27.5 -1.807261899 16.3922434 0.077593501
1 28.5 -1.750118905 16.34333654 0.076846462
1 29.5 -1.69481584 16.29584097 0.076148308
1 30.5 -1.642106779 16.24972371 0.075499126
1 31.5 -1.592744414 16.20495268 0.074898994
1 32.5 -1.547442391 16.16149871 0.074347997
1 33.5 -1.506902601 16.11933258 0.073846139
1 34.5 -1.471770047 16.07842758 0.07339337
1 35.5 -1.442628957 16.03875896 0.072989551
1 36.5 -1.419991255 16.00030401 0.072634432
1 37.5 -1.404277619 15.96304277 0.072327649
1 38.5 -1.39586317 15.92695418 0.07206864
1 39.5 -1.394935252 15.89202582 0.071856805
1 40.5 -1.401671596 15.85824093 0.071691278
1 41.5 -1.416100312 15.82558822 0.071571093
1 42.5 -1.438164899 15.79405728 0.071495113
1 43.5 -1.467669032 15.76364255 0.071462106
1 44.5 -1.504376347 15.73433668 0.071470646
1 45.5 -1.547942838 15.70613566 0.071519218
1 46.5 -1.597896397 15.67904062 0.071606277
1 47.5 -1.653732283 15.65305192 0.071730167
1 48.5 -1.714869347 15.62817269 0.071889214
1 49.5 -1.780673181 15.604408 0.072081737
1 50.5 -1.850468473 15.58176458 0.072306081
1 51.5 -1.923551865 15.56025067 0.072560637
1 52.5 -1.999220429 15.5398746 0.07284384
1 53.5 -2.076707178 15.52064993 0.073154324
1 54.5 -2.155348017 15.50258427 0.073490667
1 55.5 -2.234438552 15.48568973 0.073851672
1 56.5 -2.313321723 15.46997718 0.074236235
1 57.5 -2.391381273 15.45545692 0.074643374
1 58.5 -2.468032491 15.44213961 0.075072264
1 59.5 -2.542781541 15.43003207 0.075522104
1 60.5 -2.61516595 15.41914163 0.07599225
1 61.5 -2.684789516 15.40947356 0.076482128
1 62.5 -2.751316949 15.40103139 0.076991232
1 63.5 -2.81445945 15.39381785 0.077519149
1 64.5 -2.87402476 15.38783094 0.07806539
1 65.5 -2.92984048 15.38306945 0.078629592
1 66.5 -2.981796828 15.37952958 0.079211369
1 67.5 -3.029831343 15.37720582 0.079810334
1 68.5 -3.073924224 15.37609107 0.080426086
1 69.5 -3.114093476 15.37617677 0.081058206
1 70.5 -3.15039004 15.37745304 0.081706249
1 71.5 -3.182893018 15.37990886 0.082369741
1 72.5 -3.21170511 15.38353217 0.083048178
1 73.5 -3.23694834 15.38831005 0.083741021
1 74.5 -3.25876011 15.39422883 0.0844477
1 75.5 -3.277281546 15.40127496 0.085167651
1 76.5 -3.292683774 15.40943252 0.085900184
1 77.5 -3.305124073 15.41868691 0.086644667
1 78.5 -3.314768951 15.42902273 0.087400421
1 79.5 -3.321785992 15.44042439 0.088166744
1 80.5 -3.326345795 15.45287581 0.088942897
1 81.5 -3.328602731 15.46636218 0.089728202
1 82.5 -3.328725277 15.48086704 0.090521875
1 83.5 -3.32687018 15.49637465 0.091323162
1 84.5 -3.323188896 15.51286936 0.092131305
1 85.5 -3.317827016 15.53033563 0.092945544
1 86.5 -3.310923871 15.54875807 0.093765118
1 87.5 -3.302612272 15.56812143 0.09458927
1 88.5 -3.293018361 15.58841065 0.095417247
1 89.5 -3.282260813 15.60961101 0.096248301
1 90.5 -3.270454609 15.63170735 0.097081694
1 91.5 -3.257703616 15.65468563 0.097916698
1 92.5 -3.244108214 15.67853139 0.098752593
1 93.5 -3.229761713 15.70323052 0.099588675
1 94.5 -3.214751287 15.72876911 0.100424251
1 95.5 -3.199158184 15.75513347 0.101258643
1 96.5 -3.18305795 15.78231007 0.102091189
1 97.5 -3.166520664 15.8102856 0.102921245
1 98.5 -3.1496103 15.83904708 0.103748189
1 99.5 -3.132389637 15.86858123 0.104571386
1 100.5 -3.114911153 15.89887562 0.105390269
1 101.5 -3.097226399 15.92991765 0.106204258
1 102.5 -3.079383079 15.96169481 0.107012788
1 103.5 -3.061423765 15.99419489 0.107815327
1 104.5 -3.043386071 16.02740607 0.108611374
1 105.5 -3.025310003 16.0613159 0.109400388
1 106.5 -3.007225737 16.09591292 0.110181915
1 107.5 -2.989164598 16.13118532 0.110955478
1 108.5 -2.971148225 16.16712234 0.111720691
1 109.5 -2.953208047 16.20371168 0.112477059
1 110.5 -2.935363951 16.24094239 0.1132242
1 111.5 -2.917635157 16.27880346 0.113961734
1 112.5 -2.900039803 16.31728385 0.114689291
1 113.5 -2.882593796 16.35637267 0.115406523
1 114.5 -2.865311266 16.39605916 0.116113097
1 115.5 -2.848204697 16.43633265 0.116808702
1 116.5 -2.831285052 16.47718256 0.117493042
1 117.5 -2.81456189 16.51859843 0.11816584
1 118.5 -2.79804347 16.56056987 0.118826835
1 119.5 -2.781736856 16.60308661 0.119475785
1 120.5 -2.765648008 16.64613844 0.120112464
1 121.5 -2.749782197 16.68971518 0.120736656
1 122.5 -2.734142443 16.73380695 0.121348181
1 123.5 -2.718732873 16.77840363 0.121946849
1 124.5 -2.703555506 16.82349538 0.122532501
1 125.5 -2.688611957 16.86907238 0.123104991
1 126.5 -2.673903164 16.91512487 0.123664186
1 127.5 -2.659429443 16.96164317 0.124209969
1 128.5 -2.645190534 17.00861766 0.124742239
1 129.5 -2.631185649 17.05603879 0.125260905
1 130.5 -2.617413511 17.10389705 0.125765895
1 131.5 -2.603872392 17.15218302 0.126257147
1 132.5 -2.590560148 17.20088732 0.126734613
1 133.5 -2.577474253 17.25000062 0.12719826
1 134.5 -2.564611831 17.29951367 0.127648067
1 135.5 -2.551969684 17.34941726 0.128084023
1 136.5 -2.539539972 17.39970308 0.128506192
1 137.5 -2.527325681 17.45036072 0.128914497
1 138.5 -2.515320235 17.50138161 0.129309001
1 139.5 -2.503519447 17.55275674 0.129689741
1 140.5 -2.491918934 17.60447714 0.130056765
1 141.5 -2.480514136 17.6565339 0.130410133
1 142.5 -2.469300331 17.70891811 0.130749913
1 143.5 -2.458272656 17.76162094 0.131076187
1 144.5 -2.447426113 17.81463359 0.131389042
1 145.5 -2.436755595 17.86794729 0.131688579
1 146.5 -2.426255887 17.92155332 0.131974905
1 147.5 -2.415921689 17.97544299 0.132248138
1 148.5 -2.405747619 18.02960765 0.132508403
1 149.5 -2.395728233 18.08403868 0.132755834
1 150.5 -2.385858029 18.1387275 0.132990575
1 151.5 -2.376131459 18.19366555 0.133212776
1 152.5 -2.366542942 18.24884431 0.133422595
1 153.5 -2.357086871 18.3042553 0.133620197
1 154.5 -2.347757625 18.35989003 0.133805756
1 155.5 -2.338549576 18.41574009 0.133979452
1 156.5 -2.3294571 18.47179706 0.13414147
1 157.5 -2.320474586 18.52805255 0.134292005
1 158.5 -2.311596446 18.5844982 0.134431256
1 159.5 -2.302817124 18.64112567 0.134559427
1 160.5 -2.294131107 18.69792663 0.134676731
1 161.5 -2.285532933 18.75489278 0.134783385
1 162.5 -2.277017201 18.81201584 0.134879611
1 163.5 -2.268578584 18.86928753 0.134965637
1 164.5 -2.260211837 18.92669959 0.135041695
1 165.5 -2.251911809 18.98424378 0.135108024
1 166.5 -2.243673453 19.04191185 0.135164867
1 167.5 -2.235491842 19.09969557 0.135212469
1 168.5 -2.227362173 19.15758672 0.135251083
1 169.5 -2.21927979 19.21557707 0.135280963
1 170.5 -2.211240187 19.27365839 0.135302371
1 171.5 -2.203239029 19.33182247 0.135315568
1 172.5 -2.195272161 19.39006106 0.135320824
1 173.5 -2.187335625 19.44836594 0.135318407
1 174.5 -2.179425674 19.50672885 0.135308594
1 175.5 -2.171538789 19.56514153 0.135291662
1 176.5 -2.163671689 19.62359571 0.135267891
1 177.5 -2.155821357 19.6820831 0.135237567
1 178.5 -2.147985046 19.74059538 0.135200976
1 179.5 -2.140160305 19.7991242 0.135158409
1 180.5 -2.132344989 19.85766121 0.135110159
1 181.5 -2.124537282 19.916198 0.135056522
1 182.5 -2.116735712 19.97472615 0.134997797
1 183.5 -2.108939167 20.03323719 0.134934285
1 184.5 -2.10114692 20.09172262 0.134866291
1 185.5 -2.093358637 20.15017387 0.134794121
1 186.5 -2.085574403 20.20858236 0.134718085
1 187.5 -2.077794735 20.26693944 0.134638494
1 188.5 -2.070020599 20.32523642 0.134555663
1 189.5 -2.062253431 20.38346455 0.13446991
1 190.5 -2.054495145 20.44161501 0.134381553
1 191.5 -2.046748156 20.49967894 0.134290916
1 192.5 -2.039015385 20.5576474 0.134198323
1 193.5 -2.031300282 20.6155114 0.134104101
1 194.5 -2.023606828 20.67326189 0.134008581
1 195.5 -2.015942013 20.73088905 0.133912066
1 196.5 -2.008305745 20.7883851 0.133814954
1 197.5 -2.000706389 20.84574003 0.133717552
1 198.5 -1.993150137 20.90294449 0.1336202
1 199.5 -1.985643741 20.95998909 0.133523244
1 200.5 -1.97819451 21.01686433 0.133427032
1 201.5 -1.970810308 21.07356067 0.133331914
1 202.5 -1.96349954 21.1300685 0.133238245
1 203.5 -1.956271141 21.18637813 0.133146383
1 204.5 -1.949134561 21.24247982 0.13305669
1 205.5 -1.942099744 21.29836376 0.132969531
1 206.5 -1.935177101 21.35402009 0.132885274
1 207.5 -1.92837748 21.40943891 0.132804292
1 208.5 -1.921712136 21.46461026 0.132726962
1 209.5 -1.915192685 21.51952414 0.132653664
1 210.5 -1.908831065 21.57417053 0.132584784
1 211.5 -1.902639482 21.62853937 0.132520711
1 212.5 -1.896630358 21.68262062 0.132461838
1 213.5 -1.890816268 21.73640419 0.132408563
1 214.5 -1.885209876 21.78988003 0.132361289
1 215.5 -1.879823505 21.84303819 0.132320427
1 216.5 -1.874670324 21.8958685 0.132286382
1 217.5 -1.869760299 21.94836168 0.1322596
1 218.5 -1.865113245 22.00050569 0.132240418
1 219.5 -1.860734944 22.05229242 0.13222933
1 220.5 -1.85663384 22.10371305 0.132226801
1 221.5 -1.852827186 22.15475603 0.132233201
1 222.5 -1.849323204 22.20541249 0.132248993
1 223.5 -1.846131607 22.255673 0.132274625
1 224.5 -1.843261294 22.30552831 0.132310549
1 225.5 -1.840720248 22.3549693 0.132357221
1 226.5 -1.83851544 22.40398706 0.132415103
1 227.5 -1.83665586 22.45257182 0.132484631
1 228.5 -1.835138046 22.50071778 0.132566359
1 229.5 -1.833972004 22.54841437 0.132660699
1 230.5 -1.833157751 22.59565422 0.132768153
1 231.5 -1.83269562 22.64242956 0.132889211
1 232.5 -1.832584342 22.68873292 0.133024368
1 233.5 -1.832820974 22.73455713 0.133174129
1 234.5 -1.833400825 22.7798953 0.133338999
1 235.5 -1.834317405 22.82474087 0.133519496
1 236.5 -1.83555752 22.86908912 0.133716192
1 237.5 -1.837119466 22.91293151 0.133929525
1 238.5 -1.838987063 22.95626373 0.134160073
1 239.5 -1.841146139 22.99908062 0.134408381
1 240.0 -1.84233016 23.02029424 0.134539365
1 240.5 -1.843580575 23.04137734 0.134675001
2 24.0 -0.98660853 16.42339664 0.085451785
2 24.5 -1.024496827 16.38804056 0.085025838
2 25.5 -1.102698353 16.3189719 0.084214052
2 26.5 -1.18396635 16.25207985 0.083455124
2 27.5 -1.268071036 16.18734669 0.082748284
2 28.5 -1.354751525 16.12475448 0.082092737
2 29.5 -1.443689692 16.06428762 0.081487717
2 30.5 -1.53454192 16.00593001 0.080932448
2 31.5 -1.626928093 15.94966631 0.080426175
2 32.5 -1.720434829 15.89548197 0.079968176
2 33.5 -1.814635262 15.84336179 0.079557735
2 34.5 -1.909076262 15.79329146 0.079194187
2 35.5 -2.003296102 15.7452564 0.078876895
2 36.5 -2.096828937 15.69924188 0.078605255
2 37.5 -2.189211877 15.65523282 0.078378696
2 38.5 -2.279991982 15.61321371 0.078196674
2 39.5 -2.368732949 15.57316843 0.078058667
2 40.5 -2.455021314 15.53508019 0.077964169
2 41.5 -2.538471972 15.49893145 0.077912684
2 42.5 -2.618732901 15.46470384 0.077903716
2 43.5 -2.695488973 15.43237817 0.077936763
2 44.5 -2.768464816 15.40193436 0.078011309
2 45.5 -2.837426693 15.37335154 0.078126817
2 46.5 -2.902178205 15.34660842 0.078282739
2 47.5 -2.962580386 15.32168181 0.078478449
2 48.5 -3.018521987 15.29854897 0.078713325
2 49.5 -3.069936555 15.27718618 0.078986694
2 50.5 -3.116795864 15.2575692 0.079297841
2 51.5 -3.159107331 15.23967338 0.079646006
2 52.5 -3.196911083 15.22347371 0.080030389
2 53.5 -3.230276759 15.20894491 0.080450145
2 54.5 -3.259300182 15.19606152 0.080904391
2 55.5 -3.284099963 15.18479799 0.081392203
2 56.5 -3.30481415 15.17512871 0.081912623
2 57.5 -3.321596954 15.16702811 0.082464661
2 58.5 -3.334615646 15.16047068 0.083047295
2 59.5 -3.344047622 15.15543107 0.083659478
2 60.5 -3.35007771 15.15188405 0.084300139
2 61.5 -3.352893805 15.14980479 0.0849682
2 62.5 -3.352691376 15.14916825 0.085662539
2 63.5 -3.34966438 15.14994984 0.086382035
2 64.5 -3.343998803 15.15212585 0.087125591
2 65.5 -3.335889574 15.15567186 0.087892047
2 66.5 -3.325522491 15.16056419 0.088680264
2 67.5 -3.31307846 15.16677947 0.089489106
2 68.5 -3.298732648 15.17429464 0.090317434
2 69.5 -3.282653831 15.18308694 0.091164117
2 70.5 -3.265003896 15.1931339 0.092028028
2 71.5 -3.245937506 15.20441335 0.092908048
2 72.5 -3.225606516 15.21690296 0.093803033
2 73.5 -3.204146115 15.2305815 0.094711916
2 74.5 -3.181690237 15.24542745 0.095633595
2 75.5 -3.158363475 15.26141966 0.096566992
2 76.5 -3.134282833 15.27853728 0.097511046
2 77.5 -3.109557879 15.29675967 0.09846471
2 78.5 -3.084290931 15.31606644 0.099426955
2 79.5 -3.058577292 15.33643745 0.100396769
2 80.5 -3.032505499 15.35785274 0.101373159
2 81.5 -3.0061576 15.38029261 0.10235515
2 82.5 -2.979609448 15.40373754 0.103341788
2 83.5 -2.952930993 15.42816819 0.104332139
2 84.5 -2.926186592 15.45356545 0.105325289
2 85.5 -2.899435307 15.47991037 0.106320346
2 86.5 -2.872731211 15.50718419 0.10731644
2 87.5 -2.846123683 15.53536829 0.108312721
2 88.5 -2.819657704 15.56444426 0.109308364
2 89.5 -2.793374145 15.5943938 0.110302563
2 90.5 -2.767310047 15.6251988 0.111294537
2 91.5 -2.741498897 15.65684126 0.112283526
2 92.5 -2.715970894 15.68930333 0.113268793
2 93.5 -2.690753197 15.7225673 0.114249622
2 94.5 -2.665870146 15.75661555 0.115225321
2 95.5 -2.641343436 15.79143062 0.116195218
2 96.5 -2.617192204 15.82699517 0.117158667
2 97.5 -2.593430614 15.86329241 0.118115073
2 98.5 -2.570076037 15.90030484 0.119063807
2 99.5 -2.547141473 15.93801545 0.12000429
2 100.5 -2.524635245 15.97640787 0.120935994
2 101.5 -2.502569666 16.01546483 0.121858355
2 102.5 -2.48095189 16.05516984 0.12277087
2 103.5 -2.459785573 16.09550688 0.123673085
2 104.5 -2.439080117 16.13645881 0.124564484
2 105.5 -2.418838304 16.17800955 0.125444639
2 106.5 -2.399063683 16.22014281 0.126313121
2 107.5 -2.379756861 16.26284277 0.127169545
2 108.5 -2.360920527 16.30609316 0.128013515
2 109.5 -2.342557728 16.34987759 0.128844639
2 110.5 -2.324663326 16.39418118 0.129662637
2 111.5 -2.307240716 16.43898741 0.130467138
2 112.5 -2.290287663 16.48428082 0.131257852
2 113.5 -2.273803847 16.53004554 0.132034479
2 114.5 -2.257782149 16.57626713 0.132796819
2 115.5 -2.242227723 16.62292864 0.133544525
2 116.5 -2.227132805 16.67001572 0.134277436
2 117.5 -2.212495585 16.71751288 0.134995324
2 118.5 -2.19831275 16.76540496 0.135697996
2 119.5 -2.184580762 16.81367689 0.136385276
2 120.5 -2.171295888 16.86231366 0.137057004
2 121.5 -2.158454232 16.91130036 0.137713039
2 122.5 -2.146051754 16.96062216 0.138353254
2 123.5 -2.134084303 17.0102643 0.138977537
2 124.5 -2.122547629 17.06021213 0.139585795
2 125.5 -2.111437411 17.11045106 0.140177947
2 126.5 -2.100749266 17.16096656 0.140753927
2 127.5 -2.090478774 17.21174424 0.141313686
2 128.5 -2.080621484 17.26276973 0.141857186
2 129.5 -2.071172932 17.31402878 0.142384404
2 130.5 -2.062128649 17.3655072 0.142895332
2 131.5 -2.053484173 17.4171909 0.143389972
2 132.5 -2.045235058 17.46906585 0.143868341
2 133.5 -2.03737688 17.52111811 0.144330469
2 134.5 -2.029906684 17.57333347 0.144776372
2 135.5 -2.022817914 17.62569869 0.145206138
2 136.5 -2.016107084 17.67819987 0.145619819
2 137.5 -2.009769905 17.7308234 0.146017491
2 138.5 -2.003802134 17.78355575 0.146399239
2 139.5 -1.998199572 17.83638347 0.146765161
2 140.5 -1.992958064 17.88929321 0.147115364
2 141.5 -1.988073505 17.94227168 0.147449967
2 142.5 -1.983541835 17.9953057 0.147769097
2 143.5 -1.979359041 18.04838216 0.148072891
2 144.5 -1.975521156 18.10148804 0.148361495
2 145.5 -1.972024258 18.15461039 0.148635067
2 146.5 -1.968864465 18.20773639 0.148893769
2 147.5 -1.966037938 18.26085325 0.149137776
2 148.5 -1.963540872 18.31394832 0.14936727
2 149.5 -1.961369499 18.36700902 0.149582439
2 150.5 -1.959520079 18.42002284 0.149783482
2 151.5 -1.9579889 18.47297739 0.149970604
2 152.5 -1.956772271 18.52586035 0.15014402
2 153.5 -1.95586652 18.57865951 0.15030395
2 154.5 -1.955267984 18.63136275 0.150450621
2 155.5 -1.954973011 18.68395801 0.15058427
2 156.5 -1.954977947 18.73643338 0.150705138
2 157.5 -1.955279136 18.788777 0.150813475
2 158.5 -1.955872909 18.84097713 0.150909535
2 159.5 -1.956755579 18.89302212 0.150993582
2 160.5 -1.957923436 18.94490041 0.151065883
2 161.5 -1.959372737 18.99660055 0.151126714
2 162.5 -1.9610997 19.04811118 0.151176355
2 163.5 -1.963100496 19.09942105 0.151215094
2 164.5 -1.96537124 19.15051899 0.151243223
2 165.5 -1.967907983 19.20139397 0.151261042
2 166.5 -1.970706706 19.25203503 0.151268855
2 167.5 -1.973763307 19.30243131 0.151266974
2 168.5 -1.977073595 19.35257209 0.151255713
2 169.5 -1.980633277 19.40244671 0.151235395
2 170.5 -1.984437954 19.45204465 0.151206347
2 171.5 -1.988483106 19.50135548 0.151168902
2 172.5 -1.992764085 19.55036888 0.151123398
2 173.5 -1.997276103 19.59907464 0.15107018
2 174.5 -2.002014224 19.64746266 0.151009595
2 175.5 -2.00697335 19.69552294 0.150942
2 176.5 -2.012148213 19.7432456 0.150867753
2 177.5 -2.017533363 19.79062086 0.150787221
2 178.5 -2.023123159 19.83763907 0.150700774
2 179.5 -2.028911755 19.88429066 0.150608788
2 180.5 -2.034893091 19.9305662 0.150511645
2 181.5 -2.041060881 19.97645636 0.150409731
2 182.5 -2.047408604 20.02195192 0.15030344
2 183.5 -2.05392949 20.06704377 0.150193169
2 184.5 -2.060616513 20.11172291 0.150079322
2 185.5 -2.067462375 20.15598047 0.149962308
2 186.5 -2.074459502 20.19980767 0.14984254
2 187.5 -2.081600029 20.24319586 0.149720441
2 188.5 -2.088875793 20.28613648 0.149596434
2 189.5 -2.096278323 20.32862109 0.149470953
2 190.5 -2.103798828 20.37064138 0.149344433
2 191.5 -2.111428194 20.41218911 0.149217319
2 192.5 -2.119156972 20.45325617 0.14909006
2 193.5 -2.126975375 20.49383457 0.14896311
2 194.5 -2.134873266 20.5339164 0.148836931
2 195.5 -2.142840157 20.57349387 0.148711989
2 196.5 -2.150865204 20.61255929 0.148588757
2 197.5 -2.158937201 20.65110506 0.148467715
2 198.5 -2.167044578 20.6891237 0.148349348
2 199.5 -2.175176987 20.72660728 0.14823412
2 200.5 -2.183317362 20.76355011 0.148122614
2 201.5 -2.191457792 20.79994337 0.148015249
2 202.5 -2.199583649 20.83578051 0.147912564
2 203.5 -2.207681525 20.87105449 0.147815078
2 204.5 -2.215737645 20.90575839 0.147723315
2 205.5 -2.223739902 20.93988477 0.147637768
2 206.5 -2.231667995 20.97342858 0.147559083
2 207.5 -2.239511942 21.00638171 0.147487716
2 208.5 -2.247257081 21.0387374 0.14742421
2 209.5 -2.254885145 21.07048996 0.147369174
2 210.5 -2.26238209 21.10163241 0.147323144
2 211.5 -2.269731517 21.13215845 0.147286698
2 212.5 -2.276917229 21.16206171 0.147260415
2 213.5 -2.283925442 21.1913351 0.147244828
2 214.5 -2.290731442 21.21997472 0.147240683
2 215.5 -2.29732427 21.24797262 0.147248467
2 216.5 -2.303687802 21.27532239 0.14726877
2 217.5 -2.309799971 21.30201933 0.147302299
2 218.5 -2.315651874 21.32805489 0.147349514
2 219.5 -2.32121731 21.35342563 0.147411215
2 220.5 -2.326481911 21.37812462 0.147487979
2 221.5 -2.331428139 21.40214589 0.147580453
2 222.5 -2.336038473 21.42548351 0.147689289
2 223.5 -2.34029545 21.44813156 0.14781515
2 224.5 -2.344181703 21.47008412 0.147958706
2 225.5 -2.34768 21.49133529 0.148120633
2 226.5 -2.350773286 21.51187918 0.148301619
2 227.5 -2.353444725 21.53170989 0.148502355
2 228.5 -2.355677743 21.55082155 0.148723546
2 229.5 -2.35745607 21.56920824 0.148965902
2 230.5 -2.358763788 21.58686406 0.149230142
2 231.5 -2.359585369 21.60378309 0.149516994
2 232.5 -2.359905726 21.61995939 0.149827195
2 233.5 -2.359710258 21.635387 0.150161492
2 234.5 -2.358980464 21.65006126 0.150520734
2 235.5 -2.357714508 21.6639727 0.150905439
2 236.5 -2.355892424 21.67711736 0.151316531
2 237.5 -2.353501353 21.68948935 0.151754808
2 238.5 -2.350528726 21.70108288 0.152221086
2 239.5 -2.346962247 21.71189225 0.152716206
2 240.0 -2.34495843 21.71699934 0.152974718
2 240.5 -2.342796948 21.72190973 0.153240872
"""

TABLES = {
    'HFA': _parse_table(HFA_DATA),
    'BMI': _parse_table(BMI_DATA),
}


if __name__ == '__main__':
    sys.exit(main())
