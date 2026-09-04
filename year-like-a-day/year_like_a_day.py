#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""year-like-a-day · 度年如日 —— 给「第一次」记账的体感时间账本.

问题：「时间越过越快」是成年人最普遍的抱怨，却没有任何账本记录它。
日历记录你要去哪，日记记录你感觉如何，待办记录你要做什么——没有一
本账记录「第一次遇见什么」。而记忆恰恰是用第一次计时的：认知科学里
回忆时长正比于新异事件的密度，routine 压缩记忆，于是一年过起来像一
天——度日如年的反面，度年如日。

year-like-a-day 把「初事」（第一次的经历）补进账本。每记一行（TSV
手编：日期/品类/一句话/同行人），确定性算出六本账：

  * report   总账：日均密度与年化、中位数月基线、近 30/60/90 天窗口、
             灰条纹、回忆月、品类结构——最后过变灰门禁
  * months   月历：每月初事数与密度，LIVE（追平你自己的记忆密度）/ BLUR
  * streaks  灰条纹清单：连续零初事的天数——回忆里「糊成一片」的那段，
             第一次有了边界和长度
  * sources  供新结构：品类排行、消费型 vs 成长型、供新者（同行人）、
             各品类断供天数
  * simulate 反事实：`--every N` 给历史的每段灰条纹按每 N 天一个初事
             重放——密度、最长条纹、回忆月怎么变，守恒恒等式钉死
  * today    今天要不要造一个初事：当前条纹、断供最久的品类、门禁灯
  * gate     门禁：气候性变灰（密度塌方 ∧ 当前条纹超线，双信号）与
             绝对沙漠（单信号）——击穿 exit 4
  * validate 账本体检：恒等式、口径披露、缺省披露

诚实条款：账本只管新，不管甜——破财也是初事，好坏归阴晴表；初事是
自报的，补记允许（记忆重构），漏记会让条纹虚长——初事账只认写下的；
供新者是共同出现统计，不是「多约谁就一定有新意」的承诺；它不下价值
判断，制造不制造初事，仍是人的决定。
"""

from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from datetime import date, timedelta

VERSION = "1.0.0"

COLUMNS = ("date", "category", "note", "people")
CATEGORIES = ("place", "person", "skill", "food", "event", "media", "other")
CATEGORY_ZH = {
    "place": "地点", "person": "人", "skill": "技艺", "food": "味道",
    "event": "事件", "media": "作品", "other": "其他",
}
CONSUMER = ("food", "media")           # 买来的新意：新馆子、新剧
GROWTH = ("place", "person", "skill", "event")  # 走出去的新意
SIM_TAG = "synthetic"

MIN_COVER_DAYS = 60     # refuse conclusions below this much covered time
MIN_FIRSTS = 5          # refuse conclusions below this many firsts
LOOKBACK = 90           # days in the collapse window
COLLAPSE_RATIO = 0.5    # recent density under baseline × this = collapse
STREAK_CAP = 21         # current grey streak over this = one live signal
DESERT_CAP = 60         # current grey streak over this = absolute desert
STREAK_LIST_MIN = 14    # `streaks` lists streaks at least this long
SIM_EVERY = 7           # default: one first a week in the counterfactual

EXIT_OK = 0
EXIT_DATA = 2
EXIT_THIN = 3
EXIT_RED = 4

USAGE = """usage: year_like_a_day.py <command> [args]

commands:
  report   <firsts.tsv> [--collapse-ratio R] [--streak-cap D]     the ledger
  months   <firsts.tsv>                                            month calendar
  streaks  <firsts.tsv> [--min N]                                 grey streaks
  sources  <firsts.tsv>                                           who feeds the new
  simulate <firsts.tsv> [--every N]                               counterfactual
  today    <firsts.tsv> [--streak-cap D] [--desert-cap D]         act today
  gate     <firsts.tsv> [--collapse-ratio R] [--streak-cap D] [--desert-cap D]
  validate <firsts.tsv>                                           ledger health

ledger columns (tab separated, one row per first):
  date  category  note  people
  date is YYYY-MM-DD; category is place|person|skill|food|event|media|other;
  note is one line; people is optional (、 or , separated co-occurrences).
  Rows dated after --today are refused: a first cannot happen tomorrow.
"""


class LedgerError(Exception):
    """Bad ledger row or usage — exit 2."""


class ThinLedger(Exception):
    """Not enough evidence to conclude — exit 3."""


# ---------------------------------------------------------------- parsing

def parse_date(text, field):
    try:
        return date.fromisoformat(text.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad date %r in field %r (want YYYY-MM-DD)" % (text, field))


def split_people(text):
    """Co-occurrence names from one cell: 、 , ; / and & all separate."""
    names, seen = [], set()
    for part in str(text).replace("、", ",").replace("；", ",").replace(";", ",").replace("/", ",").replace("&", ",").split(","):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


class First(object):
    __slots__ = ("day", "category", "note", "people", "line")

    def __init__(self, day, category, note, people, line):
        self.day = day
        self.category = category
        self.note = note
        self.people = people
        self.line = line


def read_ledger(path, today=None):
    """Parse the firsts TSV into a list sorted by (day, line)."""
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise LedgerError("cannot read ledger: %s" % exc)
    seen_header = False
    seen_keys = set()
    for lineno, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        cells = raw.split("\t")
        if not seen_header:
            header = [c.strip().casefold() for c in cells]
            if header[:3] != list(COLUMNS[:3]):
                raise LedgerError(
                    "line 1 must be the header row with columns %s (got %r)"
                    % (" | ".join(COLUMNS), raw))
            seen_header = True
            continue
        if len(cells) < 3:
            raise LedgerError("line %d: expected 3-4 columns, got %d" % (lineno, len(cells)))
        day = parse_date(cells[0], "date (line %d)" % lineno)
        if today is not None and day > today:
            raise LedgerError("line %d: a first cannot happen in the future (%s > today %s)"
                              % (lineno, day.isoformat(), today.isoformat()))
        category = cells[1].strip().casefold()
        if category not in CATEGORIES:
            raise LedgerError("line %d: category must be one of %s, got %r"
                              % (lineno, "|".join(CATEGORIES), cells[1].strip()))
        note = cells[2].strip()
        if not note:
            raise LedgerError("line %d: note must not be empty — a first you cannot "
                              "describe is a first you will not remember" % lineno)
        people = split_people(cells[3]) if len(cells) > 3 else []
        key = (day, category, " ".join(note.split()).casefold())
        if key in seen_keys:
            raise LedgerError("line %d: duplicate first (same date/category/note)" % lineno)
        seen_keys.add(key)
        rows.append(First(day, category, note, people, lineno))
    if not seen_header:
        raise LedgerError("missing header row with columns %s" % " | ".join(COLUMNS))
    rows.sort(key=lambda f: (f.day, f.line))
    return rows


# ------------------------------------------------------------ core math

def coverage(firsts, today):
    """The ledger watches every day from the first entry to today: a day
    without a first is still a day you lived, it just left no anchor."""
    return firsts[0].day, today, (today - firsts[0].day).days + 1


def month_table(firsts, start, end):
    """Ordered (YYYY-MM, n_firsts, days_covered_in_month) for natural months
    clipped to the coverage window."""
    buckets = OrderedDict()
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        key = "%04d-%02d" % (cursor.year, cursor.month)
        next_month = date(cursor.year + (cursor.month == 12),
                          (cursor.month % 12) + 1, 1)
        lo, hi = max(cursor, start), min(next_month - timedelta(days=1), end)
        buckets.setdefault(key, [0, (hi - lo).days + 1])
        cursor = next_month
    for f in firsts:
        buckets["%04d-%02d" % (f.day.year, f.day.month)][0] += 1
    return buckets


def median(values):
    xs = sorted(values)
    n = len(xs)
    if not xs:
        return 0.0
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def baseline_density(months):
    """Median of per-month densities: a travel burst moves the mean, not
    the median — the baseline is your ordinary month, not your best one."""
    return median([n / days for n, days in months.values() if days > 0])


def window_density(firsts, today, days):
    """Firsts per day in the last `days` days, inclusive of today."""
    lo = today - timedelta(days=days - 1)
    n = sum(1 for f in firsts if lo <= f.day <= today)
    return n / float(days)


def grey_streaks(firsts, start, end):
    """Every run of zero-first days in the coverage window as
    (start, end, length); first-days themselves are not grey."""
    first_days = set(f.day for f in firsts)
    streaks = []
    run_start = None
    d = start
    while d <= end:
        if d not in first_days:
            if run_start is None:
                run_start = d
        elif run_start is not None:
            streaks.append((run_start, d - timedelta(days=1), (d - run_start).days))
            run_start = None
        d += timedelta(days=1)
    if run_start is not None:
        streaks.append((run_start, end, (end - run_start).days + 1))
    return streaks


def remembered_floor(total, covered_days):
    """Firsts in a month needed to keep pace with your own average density.
    Below the floor a month leaves fewer anchors than your ordinary day-
    to-day life — it will not be a chapter, it will be a sentence."""
    import math
    return max(1, int(math.ceil(total / float(covered_days) * 30.0)))


def category_stats(firsts, today, start):
    """(category, count, days_since_last | None) sorted by recency gap."""
    stats = OrderedDict()
    for cat in CATEGORIES:
        stats[cat] = [0, None]
    for f in firsts:
        stats[f.category][0] += 1
        if stats[f.category][1] is None or f.day > stats[f.category][1]:
            stats[f.category][1] = f.day
    out = []
    for cat in CATEGORIES:
        n, last = stats[cat]
        since = (today - last).days if last is not None else (today - start).days + 1
        out.append((cat, n, last, since))
    return out


def supplier_counts(firsts):
    counts = OrderedDict()
    for f in firsts:
        for name in f.people:
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def gate_verdict(firsts, today, start, end, collapse_ratio, streak_cap, desert_cap):
    """Two doors, both with exit 4: climate greying needs BOTH the density
    collapse and a live over-cap streak (a busy month can hide one, a long
    streak can be one); the absolute desert trips on its own."""
    months = month_table(firsts, start, end)
    baseline = baseline_density(months)
    recent = window_density(firsts, today, LOOKBACK)
    streaks = grey_streaks(firsts, start, end)
    current = 0
    if streaks and streaks[-1][1] == end:
        current = streaks[-1][2]
    collapse = recent < baseline * collapse_ratio
    over = current >= streak_cap
    greying = collapse and over
    desert = current >= desert_cap
    return {
        "baseline": baseline, "recent": recent, "current": current,
        "collapse": collapse, "over": over, "greying": greying,
        "desert": desert, "breach": greying or desert,
    }


# -------------------------------------------------------------- output

def streak_line(s, current=False):
    a, b, n = s
    tag = "  ← current" if current else ""
    return "  %s → %s  %s day(s)%s" % (a.isoformat(), b.isoformat(), n, tag)


# ------------------------------------------------------------- commands

def require_history(firsts, start, end):
    covered = (end - start).days + 1
    if covered < MIN_COVER_DAYS or len(firsts) < MIN_FIRSTS:
        raise ThinLedger("%d first(s) over %d day(s) is below the floor "
                         "(%d firsts over %d days); keep logging, no conclusions yet"
                         % (len(firsts), covered, MIN_FIRSTS, MIN_COVER_DAYS))


def cmd_report(args):
    firsts = read_ledger(args.ledger, args.today)
    start, end, covered = coverage(firsts, args.today)
    require_history(firsts, start, end)
    total = len(firsts)
    daily = total / float(covered)

    months = month_table(firsts, start, end)
    baseline = baseline_density(months)
    w30 = window_density(firsts, args.today, 30)
    w60 = window_density(firsts, args.today, 60)
    w90 = window_density(firsts, args.today, LOOKBACK)
    streaks = grey_streaks(firsts, start, end)
    longest = max(streaks, key=lambda s: (s[2], s[0]))
    current = streaks[-1][2] if streaks and streaks[-1][1] == end else 0
    floor = remembered_floor(total, covered)
    live = [k for k, (n, _) in months.items() if n >= floor]
    cats = category_stats(firsts, args.today, start)
    cats_sorted = sorted(cats, key=lambda c: -c[1])
    suppliers = supplier_counts(firsts)

    print("== report · 度年如日总账 ==")
    print("ledger: %d first(s) over %d day(s) (%s → %s)"
          % (total, covered, start.isoformat(), end.isoformat()))
    print("daily density: %.4f firsts/day  (annualized %.1f/year)"
          % (daily, daily * 365.0))
    print("baseline (median month): %.4f firsts/day — the ordinary month, "
          "immune to your best one" % baseline)
    print("recent windows: 30d %.4f · 60d %.4f · %dd %.4f firsts/day"
          % (w30, w60, LOOKBACK, w90))
    print("")
    print("grey streaks: longest %d day(s) (%s → %s) · current %d day(s)"
          % (longest[2], longest[0].isoformat(), longest[1].isoformat(), current))
    print("remembered months: %d of %d at or above the floor of %d firsts/month "
          "— the rest will blur into a sentence"
          % (len(live), len(months), floor))
    print("")
    print("categories: %s" % " · ".join(
        "%s %d (%.1f%%)" % (c, n, 100.0 * n / total) for c, n, _, _ in cats_sorted if n))
    consumer = sum(n for c, n, _, _ in cats if c in CONSUMER)
    growth = sum(n for c, n, _, _ in cats if c in GROWTH)
    print("novelty diet: %.1f%% bought (%s) · %.1f%% walked into (%s)"
          % (100.0 * consumer / total, "/".join(CONSUMER),
             100.0 * growth / total, "/".join(GROWTH)))
    if suppliers:
        top_name, top_n = suppliers[0]
        print("top supplier: %s was there for %d of %d firsts (%.1f%%)"
              % (top_name, top_n, total, 100.0 * top_n / total))

    verdict = gate_verdict(firsts, args.today, start, end,
                           args.collapse_ratio, args.streak_cap, args.desert_cap)
    return finish_gate(verdict, args, report=True)


def cmd_months(args):
    firsts = read_ledger(args.ledger, args.today)
    start, end, covered = coverage(firsts, args.today)
    require_history(firsts, start, end)
    months = month_table(firsts, start, end)
    floor = remembered_floor(len(firsts), covered)
    print("== months · 月历（floor = %d firsts/month） ==" % floor)
    for key, (n, days) in months.items():
        density = n / float(days) if days else 0.0
        verdict = "LIVE " if n >= floor else "BLUR"
        bar = "#" * n
        print("  %s  %2d  %6.4f/day  %s  %s" % (key, n, density, verdict, bar))
    live = sum(1 for n, _ in months.values() if n >= floor)
    print("")
    print("the calendar turned %d pages; memory bound %d of them." % (len(months), live))
    return EXIT_OK


def cmd_streaks(args):
    firsts = read_ledger(args.ledger, args.today)
    start, end, covered = coverage(firsts, args.today)
    require_history(firsts, start, end)
    streaks = grey_streaks(firsts, start, end)
    big = [s for s in streaks if s[2] >= args.min]
    longest = max(streaks, key=lambda s: (s[2], s[0]))
    current = streaks[-1][2] if streaks and streaks[-1][1] == end else 0
    grey_days = sum(s[2] for s in streaks)
    print("== streaks · 灰条纹（≥ %d 天才上榜） ==" % args.min)
    for s in big:
        print(streak_line(s, current=(s is streaks[-1] and s[1] == end)))
    if not big:
        print("  (none — no grey streak reached %d days)" % args.min)
    print("")
    print("longest: %d day(s) · current: %d day(s) · grey days total: %d of %d (%.1f%%)"
          % (longest[2], current, grey_days, covered, 100.0 * grey_days / covered))
    print("a streak is the unit of forgetting: inside one, days trade places "
          "and none of them happened.")
    return EXIT_OK


def cmd_sources(args):
    firsts = read_ledger(args.ledger, args.today)
    start, end, covered = coverage(firsts, args.today)
    require_history(firsts, start, end)
    total = len(firsts)
    cats = category_stats(firsts, args.today, start)
    print("== sources · 供新结构 ==")
    print("by category (count · share · last one):")
    for cat, n, last, since in sorted(cats, key=lambda c: -c[1]):
        zh = CATEGORY_ZH[cat]
        last_s = "%s, %d day(s) ago" % (last.isoformat(), since) if last else "never in this ledger"
        print("  %-7s %s  %2d  %5.1f%%  last %s"
              % (cat, zh, n, 100.0 * n / total, last_s))
    consumer = sum(n for c, n, _, _ in cats if c in CONSUMER)
    growth = sum(n for c, n, _, _ in cats if c in GROWTH)
    print("")
    print("novelty diet: %.1f%% bought (%s) vs %.1f%% walked into (%s)"
          % (100.0 * consumer / total, "/".join(CONSUMER),
             100.0 * growth / total, "/".join(GROWTH)))
    if consumer / float(total) > 0.7:
        print("  cheap-novelty dependence: over 70%% of your firsts can be bought — "
              "the walkable categories are starving.")
    suppliers = supplier_counts(firsts)
    alone = sum(1 for f in firsts if not f.people)
    print("")
    if suppliers:
        print("suppliers (co-occurrence, correlation not causation):")
        for name, n in suppliers[:5]:
            print("  %-10s %d first(s) (%.1f%%)" % (name, n, 100.0 * n / total))
    print("solitary firsts: %d of %d (%.1f%%) — fine either way, the ledger does not grade company."
          % (alone, total, 100.0 * alone / total))
    tried = [c for c in cats if c[1] > 0]
    untouched = [c for c in cats if c[1] == 0]
    if tried:
        hungriest = sorted(tried, key=lambda c: (-c[3], c[0]))[0]
        print("")
        print("hungriest tried category: %s (%s) — %d day(s) since its last first."
              % (hungriest[0], CATEGORY_ZH[hungriest[0]], hungriest[3]))
    if untouched:
        print("untouched categories: %s — a whole blank category is the largest "
              "first on the shelf." % ", ".join(c[0] for c in untouched))
    return EXIT_OK


def simulate_inserts(firsts, start, end, every):
    """Counterfactual firsts: inside every grey streak of length >= `every`,
    drop one first every `every` days (streak day `every`, 2×every, …)."""
    streaks = grey_streaks(firsts, start, end)
    inserts = []
    for a, b, n in streaks:
        k = every
        while k <= n:
            inserts.append(a + timedelta(days=k - 1))
            k += every
    return inserts


def cmd_simulate(args):
    firsts = read_ledger(args.ledger, args.today)
    start, end, covered = coverage(firsts, args.today)
    require_history(firsts, start, end)
    every = args.every
    if every < 1:
        raise LedgerError("--every must be >= 1")
    total = len(firsts)
    inserts = simulate_inserts(firsts, start, end, every)

    streaks = grey_streaks(firsts, start, end)
    old_longest = max(streaks, key=lambda s: (s[2], s[0]))[2] if streaks else 0
    months_old = month_table(firsts, start, end)
    floor_old = remembered_floor(total, covered)
    live_old = sum(1 for n, _ in months_old.values() if n >= floor_old)

    new_days = set(f.day for f in firsts) | set(inserts)
    new_streaks, run_start = [], None
    d = start
    while d <= end:
        if d not in new_days:
            if run_start is None:
                run_start = d
        elif run_start is not None:
            new_streaks.append((run_start, d - timedelta(days=1), (d - run_start).days))
            run_start = None
        d += timedelta(days=1)
    if run_start is not None:
        new_streaks.append((run_start, end, (end - run_start).days + 1))
    new_longest = max(new_streaks, key=lambda s: (s[2], s[0]))[2] if new_streaks else 0
    new_total = total + len(inserts)
    months_new = month_table(firsts, start, end)
    for d in inserts:
        months_new["%04d-%02d" % (d.year, d.month)][0] += 1
    # the floor is pinned to the REAL ledger's pace: the counterfactual asks
    # how many months would have cleared the bar your actual life set — not
    # a bar that rises with every first we imagine for you.
    live_new = sum(1 for n, _ in months_new.values() if n >= floor_old)

    print("== simulate · 反事实：每周（每 %d 天）一个初事 ==" % every)
    print("inserted %d synthetic first(s) into the grey streaks of the past "
          "%d day(s)" % (len(inserts), covered))
    print("")
    print("total firsts: %d → %d  (conservation: %d + %d = %d)"
          % (total, new_total, total, len(inserts), new_total))
    print("daily density: %.4f → %.4f firsts/day  (annualized %.1f → %.1f)"
          % (total / float(covered), new_total / float(covered),
             total / float(covered) * 365.0, new_total / float(covered) * 365.0))
    print("longest grey streak: %d → %d day(s)" % (old_longest, new_longest))
    print("remembered months: %d → %d of %d  (floor pinned at %d/month — "
          "your real pace, not the counterfactual's)"
          % (live_old, live_new, len(months_old), floor_old))
    print("")
    print("identity: new total == old total + inserted  →  %d == %d + %d (exact)"
          % (new_total, total, len(inserts)))
    print("the ledger cannot send you back; it can only price the firsts you "
          "did not spend — and remind you that the next one is still available.")
    return EXIT_OK


def cmd_today(args):
    firsts = read_ledger(args.ledger, args.today)
    start, end, covered = coverage(firsts, args.today)
    if len(firsts) < MIN_FIRSTS:
        raise ThinLedger("only %d first(s) on record; keep logging before the "
                         "daily brief means anything" % len(firsts))
    streaks = grey_streaks(firsts, start, end)
    current = streaks[-1][2] if streaks and streaks[-1][1] == end else 0
    last_first = max(f.day for f in firsts)
    cats = category_stats(firsts, args.today, start)
    tried = [c for c in cats if c[1] > 0]
    untouched = [c for c in cats if c[1] == 0]

    print("== today · %s ==" % args.today.isoformat())
    print("last first: %s (%s: %s) — %d day(s) ago"
          % (last_first.isoformat(),
             CATEGORY_ZH[[f for f in firsts if f.day == last_first][0].category],
             [f for f in firsts if f.day == last_first][0].note,
             (args.today - last_first).days))
    print("current grey streak: %d day(s)%s"
          % (current, "  (you are standing in one)" if current else ""))
    if tried:
        hungry = sorted(tried, key=lambda c: (-c[3], c[0]))[0]
        print("hungriest tried category: %s (%s), %d day(s) — the shortest path "
              "back to a remembered month is usually a first where you have not "
              "had one in the longest."
              % (hungry[0], CATEGORY_ZH[hungry[0]], hungry[3]))
    if untouched:
        print("untouched categories: %s — the whole shelf is unspent."
              % ", ".join(c[0] for c in untouched))

    verdict = gate_verdict(firsts, args.today, start, end,
                           args.collapse_ratio, args.streak_cap, args.desert_cap)
    return finish_gate(verdict, args, report=False)


def cmd_gate(args):
    firsts = read_ledger(args.ledger, args.today)
    start, end, covered = coverage(firsts, args.today)
    require_history(firsts, start, end)
    verdict = gate_verdict(firsts, args.today, start, end,
                           args.collapse_ratio, args.streak_cap, args.desert_cap)
    print("== gate · 变灰门禁 ==")
    print("caps: collapse < baseline × %.2f over %dd · streak cap %dd · desert cap %dd"
          % (args.collapse_ratio, LOOKBACK, args.streak_cap, args.desert_cap))
    print("baseline %.4f/day · last-%dd %.4f/day · current streak %d day(s)"
          % (verdict["baseline"], LOOKBACK, verdict["recent"], verdict["current"]))
    print("")
    if not verdict["collapse"] and not verdict["over"] and not verdict["desert"]:
        print("signals: density ok · streak ok · no desert")
    else:
        print("signals: density collapse %s · streak over cap %s · desert %s"
              % ("YES" if verdict["collapse"] else "no",
                 "YES" if verdict["over"] else "no",
                 "YES" if verdict["desert"] else "no"))
    return finish_gate(verdict, args, report=False)


def finish_gate(verdict, args, report=True):
    print("")
    if verdict["breach"]:
        if verdict["greying"]:
            print("RED LINE  climate greying: last-%dd density %.4f < baseline %.4f × %.2f, "
                  "AND the current streak is %d day(s) (cap %d) — exit 4"
                  % (LOOKBACK, verdict["recent"], verdict["baseline"],
                     args.collapse_ratio, verdict["current"], args.streak_cap))
        if verdict["desert"]:
            print("RED LINE  absolute desert: %d straight day(s) without a first "
                  "(cap %d) — exit 4, no second signal needed"
                  % (verdict["current"], args.desert_cap))
        print("          a grey year is not a verdict on your life; it is a "
              "queue of firsts you have not spent yet.")
        return EXIT_RED
    print("VERDICT: no greying signal — density %.4f vs baseline %.4f, current "
          "streak %d day(s). exit 0" % (verdict["recent"], verdict["baseline"],
                                        verdict["current"]))
    return EXIT_OK


def cmd_validate(args):
    firsts = read_ledger(args.ledger, args.today)
    start, end, covered = coverage(firsts, args.today)
    total = len(firsts)

    months = month_table(firsts, start, end)
    by_month = sum(n for n, _ in months.values())
    cats = category_stats(firsts, args.today, start)
    by_cat = sum(n for _, n, _, _ in cats)
    no_people = sum(1 for f in firsts if not f.people)
    present = sorted(set(c for c, n, _, _ in cats if n))
    suppliers = supplier_counts(firsts)

    print("== validate · 账本体检 ==")
    print("rows: %d  (coverage %s → %s, %d day(s); future rows are refused at parse time)"
          % (total, start.isoformat(), end.isoformat(), covered))
    print("count identity: Σ months == Σ categories == total  →  %d == %d == %d"
          % (by_month, by_cat, total))
    print("density identity: total ÷ covered days  →  %d ÷ %d = %.9f"
          % (total, covered, total / float(covered)))
    print("rows without people: %d (fine — solitary firsts count the same)" % no_people)
    print("categories present: %s" % ", ".join(present))
    if suppliers:
        print("suppliers named: %s" % ", ".join(name for name, _ in suppliers))
    if covered < MIN_COVER_DAYS or total < MIN_FIRSTS:
        print("")
        print("THIN: %d first(s) over %d day(s) < %d over %d — reports refuse to "
              "conclude (exit 3)" % (total, covered, MIN_FIRSTS, MIN_COVER_DAYS))
    else:
        print("")
        print("ledger healthy. exit 0")
    return EXIT_OK


# ------------------------------------------------------------------ main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="year_like_a_day.py",
        description="year-like-a-day · Year Like a Day — the first-times ledger")
    parser.add_argument("--version", action="version",
                        version="year-like-a-day %s" % VERSION)
    parser.add_argument("--today", default=None, metavar="YYYY-MM-DD",
                        help="pin 'today' for coverage and streaks (defaults "
                             "to the real clock; pin it for reproducible reports)")
    sub = parser.add_subparsers(dest="command")

    def common(p):
        p.add_argument("ledger")

    p = sub.add_parser("report", help="the whole ledger, gated")
    common(p)
    p.add_argument("--collapse-ratio", type=float, default=COLLAPSE_RATIO)
    p.add_argument("--streak-cap", type=int, default=STREAK_CAP)
    p.add_argument("--desert-cap", type=int, default=DESERT_CAP)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("months", help="month calendar: LIVE or BLUR")
    common(p)
    p.set_defaults(func=cmd_months)

    p = sub.add_parser("streaks", help="grey streaks at or above a length")
    common(p)
    p.add_argument("--min", type=int, default=STREAK_LIST_MIN)
    p.set_defaults(func=cmd_streaks)

    p = sub.add_parser("sources", help="categories, suppliers, hunger")
    common(p)
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("simulate", help="counterfactual: one first every N days")
    common(p)
    p.add_argument("--every", type=int, default=SIM_EVERY, metavar="N",
                   help="insert one first every N days inside grey streaks "
                        "(default %d)" % SIM_EVERY)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("today", help="the daily brief: streak, hunger, gate")
    common(p)
    p.add_argument("--collapse-ratio", type=float, default=COLLAPSE_RATIO)
    p.add_argument("--streak-cap", type=int, default=STREAK_CAP)
    p.add_argument("--desert-cap", type=int, default=DESERT_CAP)
    p.set_defaults(func=cmd_today)

    p = sub.add_parser("gate", help="the greying gate only")
    common(p)
    p.add_argument("--collapse-ratio", type=float, default=COLLAPSE_RATIO)
    p.add_argument("--streak-cap", type=int, default=STREAK_CAP)
    p.add_argument("--desert-cap", type=int, default=DESERT_CAP)
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("validate", help="ledger health check")
    common(p)
    p.set_defaults(func=cmd_validate)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_DATA
    try:
        # "Today" is a parameter, not a clock reading: the same ledger must
        # produce byte-identical reports on any machine, any day (coverage,
        # streaks and the snapshots depend on it).
        if getattr(args, "today", None) is None:
            args.today = date.today()
        else:
            args.today = parse_date(args.today, "--today")
        return args.func(args)
    except LedgerError as exc:
        sys.stderr.write("data error (exit 2): %s\n" % exc)
        return EXIT_DATA
    except ThinLedger as exc:
        sys.stderr.write("too thin to conclude (exit 3): %s\n" % exc)
        return EXIT_THIN


if __name__ == "__main__":
    sys.exit(main())
