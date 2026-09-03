#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""full-house · 包场 —— 会议人时账本.

问题：日历只显示时间，不显示价格。一场 8 人 1 小时的会，按人均时薪
150 元就是一次 ¥1,200 的采购——而且每周都买，一年买 52 次，从没有
一张账单；「顺便拉齐一下」的 4 人 30 分钟看起来免费，其实每人每次
都在被包场。会议是职场里最大的一笔隐形开支，它隐形的原因很简单：
日历的单位是分钟，工资的单位是钱，两本账从来没有人对过时。

full-house 把「包场」补进账本。每场会记一行（TSV 手编：日期/开始/
时长/人数/主题/类型/产出），确定性算出八本账：

  * bill      总账单：人时是硬通货、钱是翻译——没给时薪照样出全部
              人时账；给了时薪才有账单、周均与年化；周红线 exit 4
  * top       单场最贵排行：谁在包最大的场
  * recurring 周期会年化：同名聚类出频次与间隔，「这场周会一年 =
              多少人时 / 多少钱」
  * density   日历形状：最贵的日子、会议三明治（两场之间 <15 分钟
              的假空档）、最长连轴链、无会工作日占比
  * outcome   产出账：决策/行动项的自报记录，每做出一个决定平均
              花掉多少人时；无产出的人时烧在哪里
  * simulate  反事实：砍掉或减频某场周期会，一年省下多少
  * gate      门禁：排期中的会与历史周均对着人时红线过闸，击穿
              exit 4——开不开仍是人的决定，它只拒绝继续免费
  * validate  账本体检：字段/重复行/分段（历史 vs 排期）披露

诚实条款：账本只记日历上的事实；缺席、迟到、走神不建模；统一时薪
是刻意简化（个人时薪不采集）；产出是自报的，工具不判定一场会该不
该开——它只把价格挂出来。
"""

from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from datetime import date, datetime, timedelta

VERSION = "1.0.0"

COLUMNS = ("date", "start", "duration_min", "attendees", "subject", "kind", "outcome")
OUTCOMES = ("decision", "action", "none")
SANDWICH_GAP = 15.0     # minutes; a shorter gap is a meeting sandwich
CHAIN_GAP = 5.0         # minutes; gaps this small chain into a marathon
WEEKLY_CAP_PH = 40.0    # default red line: person-hours/week = one full-time
                        # week of rented attention burned in meetings
SINGLE_CAP_PH = 16.0    # default red line: person-hours in one meeting
MIN_MEETINGS = 5        # refuse conclusions below this many past meetings
SANDWICH_TOP = 5        # densest days shown by `density`
ANNUAL_WEEKS = 52.0

EXIT_OK = 0
EXIT_DATA = 2
EXIT_THIN = 3
EXIT_RED = 4

USAGE = """usage: full_house.py <command> [args]

commands:
  bill      <meetings.tsv> [--rate R | --salary S --hours H]  total bill
  top       <meetings.tsv> [-n N] [--rate R]                  priciest meetings
  recurring <meetings.tsv> [--rate R]                         annualized series
  density   <meetings.tsv>                                    calendar shape
  outcome   <meetings.tsv> [--rate R]                         outcome accounting
  simulate  <meetings.tsv> cancel --match NAME [--every K]    counterfactual
  gate      <meetings.tsv> [--rate R] [--weekly-cap H] [--single-cap H]
  validate  <meetings.tsv>                                    ledger health

ledger columns (tab separated, one row per meeting):
  date  start  duration_min  attendees  subject  kind  outcome
  start is HH:MM; attendees is a positive integer;
  outcome is decision|action|none (blank = none, disclosed).
  Rows dated in the future are scheduled meetings: reports skip them
  (and say so), `gate` audits them.
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


def parse_start(text, field):
    try:
        return datetime.strptime(text.strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        raise LedgerError("bad start %r in field %r (want HH:MM)" % (text, field))


def parse_positive_int(text, field):
    try:
        value = int(text.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad integer %r in field %r" % (text, field))
    if value <= 0:
        raise LedgerError("field %r must be a positive integer, got %d" % (field, value))
    return value


def parse_positive_float(text, field):
    try:
        value = float(text.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad number %r in field %r" % (text, field))
    if value <= 0:
        raise LedgerError("field %r must be > 0, got %s" % (field, value))
    return value


def norm_subject(text):
    return " ".join(str(text).split()).casefold()


class Meeting(object):
    __slots__ = ("day", "start", "minutes", "attendees", "subject",
                 "slug", "kind", "outcome", "line", "outcome_defaulted")

    def __init__(self, day, start, minutes, attendees, subject, kind,
                 outcome, line, outcome_defaulted):
        self.day = day
        self.start = start
        self.minutes = minutes
        self.attendees = attendees
        self.subject = subject
        self.slug = norm_subject(subject)
        self.kind = kind
        self.outcome = outcome
        self.line = line
        self.outcome_defaulted = outcome_defaulted

    @property
    def person_hours(self):
        return self.minutes * self.attendees / 60.0

    @property
    def end(self):
        """End time as minutes from midnight (may pass 24h for late ends)."""
        return self.start.hour * 60 + self.start.minute + self.minutes


def read_ledger(path):
    """Parse the meetings TSV into a list sorted by (day, start)."""
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
            if header[:5] != list(COLUMNS[:5]):
                raise LedgerError(
                    "line 1 must be the header row with columns %s (got %r)"
                    % (" | ".join(COLUMNS), raw))
            seen_header = True
            continue
        if len(cells) < 6:
            raise LedgerError("line %d: expected 6-7 columns, got %d" % (lineno, len(cells)))
        day = parse_date(cells[0], "date (line %d)" % lineno)
        start = parse_start(cells[1], "start (line %d)" % lineno)
        minutes = parse_positive_float(cells[2], "duration_min (line %d)" % lineno)
        attendees = parse_positive_int(cells[3], "attendees (line %d)" % lineno)
        subject = cells[4].strip()
        if not subject:
            raise LedgerError("line %d: subject must not be empty" % lineno)
        kind = cells[5].strip() or "unlabeled"
        # a missing (6-column) or blank outcome cell defaults to 'none',
        # and the defaulting is disclosed in reports
        outcome = cells[6].strip().casefold() if len(cells) > 6 else ""
        defaulted = False
        if not outcome:
            outcome, defaulted = "none", True
        if outcome not in OUTCOMES:
            raise LedgerError("line %d: outcome must be one of %s, got %r"
                              % (lineno, "|".join(OUTCOMES), (cells[6] if len(cells) > 6 else "").strip()))
        key = (day, start.hour, start.minute, norm_subject(subject))
        if key in seen_keys:
            raise LedgerError("line %d: duplicate meeting (same date/start/subject) %r"
                              % (lineno, subject))
        seen_keys.add(key)
        rows.append(Meeting(day, start, minutes, attendees, subject, kind,
                            outcome, lineno, defaulted))
    if not seen_header:
        raise LedgerError("missing header row with columns %s" % " | ".join(COLUMNS))
    rows.sort(key=lambda m: (m.day, m.start.hour, m.start.minute, m.line))
    return rows


# ------------------------------------------------------------- finance

def resolve_rate(args):
    """Person-hour price in yuan, or None for the unpriced (honest) mode."""
    salary, hours = getattr(args, "salary", None), getattr(args, "hours", None)
    if getattr(args, "rate", None) is not None:
        if args.rate <= 0:
            raise LedgerError("--rate must be > 0")
        if salary is not None or hours is not None:
            raise LedgerError("give either --rate or --salary/--hours, not both")
        return float(args.rate)
    if salary is not None or hours is not None:
        if salary is None or hours is None:
            raise LedgerError("--salary needs --hours (and vice versa)")
        if salary <= 0 or hours <= 0:
            raise LedgerError("--salary and --hours must be > 0")
        return float(salary) / float(hours)
    return None


def money(amount):
    return "¥{:,.2f}".format(amount)


def phours(value):
    return "{:,.1f}".format(value)


def pct(value):
    return "{:.1f}%".format(value * 100.0)


def split_past_future(meetings, today):
    past = [m for m in meetings if m.day <= today]
    future = [m for m in meetings if m.day > today]
    return past, future


def week_bounds(day):
    """(Monday, Sunday) of the week containing `day`."""
    monday = day - timedelta(days=day.weekday())
    sunday = day + timedelta(days=6 - day.weekday())
    return monday, sunday


def week_span_days(meetings):
    """Covered span in days: Monday of the first meeting's week through
    Sunday of the last meeting's week. Pinned and tested."""
    first_monday, last_sunday = week_bounds(meetings[0].day)[0], week_bounds(meetings[-1].day)[1]
    return (last_sunday - first_monday).days + 1


def week_buckets(meetings):
    """Ordered ISO-week -> list of meetings."""
    buckets = OrderedDict()
    for m in meetings:
        monday = m.day - timedelta(days=m.day.weekday())
        buckets.setdefault(monday, []).append(m)
    return buckets


def summarize(meetings, rate):
    total_ph = sum(m.person_hours for m in meetings)
    total_cost = total_ph * rate if rate is not None else None
    return total_ph, total_cost


# ------------------------------------------------------------- commands

def require_history(past):
    if len(past) < MIN_MEETINGS:
        raise ThinLedger("%d past meetings is below the %d-meeting floor; "
                         "keep logging, no conclusions yet"
                         % (len(past), MIN_MEETINGS))


def report_footer(skipped_future, unpriced):
    if skipped_future:
        print("")
        print("NOTE  %d scheduled meeting(s) dated in the future skipped here; "
              "`gate` audits them." % skipped_future)
    if unpriced:
        print("")
        print("NOTE  unpriced mode: give --rate (or --salary with --hours) and "
              "every person-hour figure gets its bill.")


def cmd_bill(args):
    rate = resolve_rate(args)
    meetings = read_ledger(args.ledger)
    today = args.today
    past, future = split_past_future(meetings, today)
    require_history(past)

    total_ph, total_cost = summarize(past, rate)
    span = week_span_days(past)
    weeks = span / 7.0
    weekly_ph = total_ph / weeks
    weekly_cost = total_cost / weeks if total_cost is not None else None

    print("== bill · 包场总账 ==")
    print("meetings: %d  (span %d days = %.1f weeks)" % (len(past), span, weeks))
    print("person-hours: %s h total   %s h/week average" % (phours(total_ph), phours(weekly_ph)))
    if total_cost is not None:
        print("bill: %s total   %s/week   annualized %s"
              % (money(total_cost), money(weekly_cost), money(total_cost / weeks * ANNUAL_WEEKS)))
        print("money identity: Σ cost == person-hours × rate  →  %s h × %s = %s"
              % ("{:,.2f}".format(total_ph), money(rate), money(total_ph * rate)))
    defaulted = sum(1 for m in past if m.outcome_defaulted)
    if defaulted:
        print("outcome defaulted to 'none' on %d row(s); recording them sharpens "
              "the outcome ledger" % defaulted)
    if weekly_ph > args.weekly_cap:
        over = weekly_ph - args.weekly_cap
        print("")
        print("RED LINE  %s meeting-hours/week over the %s h cap (%s h) — exit 4"
              % (phours(weekly_ph), phours(args.weekly_cap), phours(over)))
        if total_cost is not None:
            print("          that is %s/year of rented attention over the line."
                  % money(over * ANNUAL_WEEKS * rate))
        return EXIT_RED
    print("")
    print("weekly load %s h is within the %s h cap. exit 0"
          % (phours(weekly_ph), phours(args.weekly_cap)))
    report_footer(len(future), rate is None)
    return EXIT_OK


def cmd_top(args):
    rate = resolve_rate(args)
    meetings = read_ledger(args.ledger)
    today = args.today
    past, future = split_past_future(meetings, today)
    require_history(past)

    ranked = sorted(past, key=lambda m: -m.person_hours)[:args.n]
    print("== top · 最贵的 %d 场（按人时） ==" % len(ranked))
    for i, m in enumerate(ranked, 1):
        line = "%2d. %s %s  %-14s %4d min × %2d = %s h" % (
            i, m.day.isoformat(), m.start.strftime("%H:%M"),
            m.subject[:14], m.minutes, m.attendees, phours(m.person_hours))
        if rate is not None:
            line += "  %s" % money(m.person_hours * rate)
        print(line)
    share = sum(m.person_hours for m in ranked) / sum(m.person_hours for m in past)
    print("")
    print("these %d meetings are %s of all rented attention."
          % (len(ranked), pct(share)))
    report_footer(len(future), rate is None)
    return EXIT_OK


def recurring_groups(past):
    groups = OrderedDict()
    for m in past:
        groups.setdefault(m.slug, []).append(m)
    return groups


def cmd_recurring(args):
    rate = resolve_rate(args)
    meetings = read_ledger(args.ledger)
    today = args.today
    past, future = split_past_future(meetings, today)
    require_history(past)

    groups = recurring_groups(past)
    series, singles = [], []
    for slug, ms in groups.items():
        if len(ms) < 2:
            singles.append(ms[0])
            continue
        days = sorted(m.day for m in ms)
        gaps = sorted((b - a).days for a, b in zip(days, days[1:]))
        median_gap = gaps[len(gaps) // 2] if len(gaps) % 2 else (gaps[len(gaps)//2 - 1] + gaps[len(gaps)//2]) / 2.0
        series.append((slug, ms, median_gap))

    series.sort(key=lambda item: -sum(m.person_hours for m in item[1]))
    weeks = week_span_days(past) / 7.0
    print("== recurring · 周期会年化 ==")
    for slug, ms, gap in series:
        mean_ph = sum(m.person_hours for m in ms) / len(ms)
        count = len(ms)
        print("")
        print("· %s — %d times, median gap %s day(s), mean %s h/meeting"
              % (ms[0].subject, count, ("%.1f" % gap) if gap % 1 else str(int(gap)),
                 phours(mean_ph)))
        if gap <= 0:
            print("  same-day repeats: annualization undefined (median gap = 0)")
            continue
        # empirical cadence: observed frequency over the covered weeks,
        # projected to a year. Holidays and skipped weeks dilute it the
        # way they dilute real calendars — the interval median is shown
        # for rhythm, but the money uses what actually happened.
        per_year = count / weeks * ANNUAL_WEEKS
        annual_ph = per_year * mean_ph
        if rate is not None:
            print("  annualized: %.0f meetings/year = %s h = %s"
                  % (per_year, phours(annual_ph), money(annual_ph * rate)))
        else:
            print("  annualized: %.0f meetings/year = %s h  (unpriced)"
                  % (per_year, phours(annual_ph)))
    if singles:
        print("")
        print("one-off meetings (no repeat observed): %d — listed by `top`, "
              "not annualized" % len(singles))
    report_footer(len(future), rate is None)
    return EXIT_OK


def cmd_density(args):
    meetings = read_ledger(args.ledger)
    today = args.today
    past, future = split_past_future(meetings, today)
    require_history(past)

    by_day = OrderedDict()
    for m in past:
        by_day.setdefault(m.day, []).append(m)

    day_load = sorted(((d, sum(m.person_hours for m in ms))
                       for d, ms in by_day.items()),
                      key=lambda t: (-t[1], t[0]))
    sandwiches, longest_chain, overlaps = [], 0, 0
    for d, ms in by_day.items():
        ms = sorted(ms, key=lambda m: (m.start.hour, m.start.minute))
        chain = 1
        for a, b in zip(ms, ms[1:]):
            gap = (b.start.hour * 60 + b.start.minute) - a.end
            if gap < 0:
                overlaps += 1
            if 0 <= gap < SANDWICH_GAP:
                sandwiches.append((d, a.subject, b.subject, gap))
            # a chain extends only through true back-to-back gaps; an
            # overlap (gap < 0) is a scheduling accident, not a chain.
            if 0 <= gap <= CHAIN_GAP:
                chain += 1
                longest_chain = max(longest_chain, chain)
            else:
                chain = 1

    first_monday = week_bounds(past[0].day)[0]
    last_sunday = week_bounds(past[-1].day)[1]
    weekdays = []
    d = first_monday
    while d <= last_sunday:
        if d.weekday() < 5:
            weekdays.append(d)
        d += timedelta(days=1)
    clean = [d for d in weekdays if d not in by_day]

    print("== density · 日历形状 ==")
    print("busiest days (person-hours rented):")
    for d, load in day_load[:SANDWICH_TOP]:
        print("  %s (%s)  %s h" % (d.isoformat(), "MTWTFSS"[d.weekday()], phours(load)))
    print("")
    print("meeting sandwiches (gap < %g min between two meetings): %d"
          % (SANDWICH_GAP, len(sandwiches)))
    for d, a, b, gap in sandwiches[:SANDWICH_TOP]:
        print("  %s  %s → %s  (%g min gap)" % (d.isoformat(), a, b, gap))
    if longest_chain:
        print("longest back-to-back chain (gap ≤ %g min): %d meetings" % (CHAIN_GAP, longest_chain))
    if overlaps:
        print("overlapping meetings on the books: %d" % overlaps)
    print("")
    print("clean weekdays: %d of %d (%s) had zero meetings"
          % (len(clean), len(weekdays), pct(len(clean) / len(weekdays) if weekdays else 0.0)))
    weekend = sum(1 for m in past if m.day.weekday() >= 5)
    if weekend:
        print("weekend meetings on record: %d — the calendar does not rest." % weekend)
    report_footer(len(future), False)
    return EXIT_OK


def cmd_outcome(args):
    rate = resolve_rate(args)
    meetings = read_ledger(args.ledger)
    today = args.today
    past, future = split_past_future(meetings, today)
    require_history(past)

    total_ph, total_cost = summarize(past, rate)
    decisions = [m for m in past if m.outcome == "decision"]
    actions = [m for m in past if m.outcome == "action"]
    bare = [m for m in past if m.outcome == "none"]
    bare_ph = sum(m.person_hours for m in bare)

    print("== outcome · 产出账 ==")
    print("recorded: %d decision · %d action · %d none  (%s of person-hours "
          "went to meetings with no recorded outcome)"
          % (len(decisions), len(actions), len(bare),
             pct(bare_ph / total_ph if total_ph else 0.0)))
    print("")
    if decisions:
        ph_per = total_ph / len(decisions)
        if total_cost is not None:
            print("decision cost: %s h per decision  (%s each)"
                  % (phours(ph_per), money(ph_per * rate)))
        else:
            print("decision cost: %s h per decision  (unpriced)" % phours(ph_per))
    else:
        print("decision cost: n/a — zero recorded decisions; the ledger refuses "
              "to divide by nothing")
    if total_cost is not None:
        print("no-outcome bill: %s of %s (%s)"
              % (money(bare_ph * rate), money(total_cost),
                 pct(bare_ph / total_ph if total_ph else 0.0)))

    kinds = OrderedDict()
    for m in past:
        kinds.setdefault(m.kind, []).append(m)
    print("")
    print("by kind (kind · meetings · person-hours · no-outcome share):")
    for kind, ms in sorted(kinds.items(), key=lambda kv: -sum(m.person_hours for m in kv[1])):
        kph = sum(m.person_hours for m in ms)
        knone = sum(m.person_hours for m in ms if m.outcome == "none")
        print("  %-12s %3d  %s h  %s" % (kind[:12], len(ms), phours(kph),
                                         pct(knone / kph if kph else 0.0)))
    report_footer(len(future), rate is None)
    return EXIT_OK


def cmd_simulate(args):
    rate = resolve_rate(args)
    meetings = read_ledger(args.ledger)
    today = args.today
    past, future = split_past_future(meetings, today)
    require_history(past)
    if not args.match:
        raise LedgerError("--match needs a subject substring to cancel")
    needle = norm_subject(args.match)
    hits = [m for m in past if needle in m.slug]
    if not hits:
        raise LedgerError("no past meeting subject matches %r" % args.match)

    weeks = week_span_days(past) / 7.0
    cut_ph = sum(m.person_hours for m in hits)
    total_ph = sum(m.person_hours for m in past)
    # every=1 cancels the whole series; every=K thins it to 1-in-K.
    keep_every = (1.0 / args.every) if args.every > 1 else 0.0
    saved_ph = cut_ph * (1.0 - keep_every)
    saved_weekly = saved_ph / weeks
    print("== simulate · 反事实：少开这些会 ==")
    print("match %r: %d meeting(s), %s h rented in the window"
          % (args.match, len(hits), phours(cut_ph)))
    if args.every > 1:
        print("thinned to every %d-th occurrence: you keep %s of the series"
              % (args.every, pct(keep_every)))
    print("")
    print("weekly load: %s h → %s h  (−%s h/week)"
          % (phours(total_ph / weeks), phours((total_ph - saved_ph) / weeks),
             phours(saved_weekly)))
    print("annualized saving: %s h" % phours(saved_weekly * ANNUAL_WEEKS))
    if rate is not None:
        print("annualized saving: %s" % money(saved_weekly * ANNUAL_WEEKS * rate))
        print("that is %s of the total bill" % pct(saved_ph / total_ph if total_ph else 0.0))
    else:
        print("(unpriced: add --rate to see the money)")
    print("")
    print("the ledger does not claim the meeting was worthless — it prices "
          "the option you are not taking.")
    report_footer(len(future), rate is None)
    return EXIT_OK


def cmd_gate(args):
    rate = resolve_rate(args)
    meetings = read_ledger(args.ledger)
    today = args.today
    past, future = split_past_future(meetings, today)
    if not past and not future:
        raise ThinLedger("empty ledger: nothing to gate")

    breaches = []
    if past:
        weeks = week_span_days(past) / 7.0
        weekly_ph = sum(m.person_hours for m in past) / weeks
        cap = args.weekly_cap
        if weekly_ph > cap:
            breaches.append("weekly average %s h/week over the %s h cap"
                            % (phours(weekly_ph), phours(cap)))
    upcoming = sorted(future, key=lambda m: (m.day, m.start.hour, m.start.minute))
    for m in upcoming:
        if m.person_hours > args.single_cap:
            breaches.append("%s %s %r rents %s h in one room, over the %s h single cap"
                            % (m.day.isoformat(), m.start.strftime("%H:%M"),
                               m.subject, phours(m.person_hours), phours(args.single_cap)))

    print("== gate · 排期门禁 ==")
    print("caps: %s h/week · %s h/single meeting%s"
          % (phours(args.weekly_cap), phours(args.single_cap),
             " · rate %s/person-hour" % money(rate) if rate is not None else " · unpriced"))
    print("scheduled ahead: %d meeting(s)%s"
          % (len(upcoming), " (nothing dated in the future — gate checked the "
                            "weekly average only)" if not upcoming else ""))
    if not breaches:
        print("")
        print("VERDICT: PASS — nothing over the caps. exit 0")
        return EXIT_OK
    print("")
    for b in breaches:
        print("BREACH  %s" % b)
    print("")
    print("VERDICT: %d breach(es). exit 4 — shrink the room, the minutes, "
          "or the series before it books itself." % len(breaches))
    return EXIT_RED


def cmd_validate(args):
    rate = resolve_rate(args)
    meetings = read_ledger(args.ledger)
    today = args.today
    past, future = split_past_future(meetings, today)

    total_ph = sum(m.person_hours for m in meetings)
    defaulted = sum(1 for m in meetings if m.outcome_defaulted)
    kinds = sorted(set(m.kind for m in meetings))
    subjects = sorted(set(m.subject for m in meetings))

    print("== validate · 账本体检 ==")
    print("rows: %d  (past %d · scheduled %d)" % (len(meetings), len(past), len(future)))
    print("person-hours identity: Σ per-meeting h == total h  →  %.9f == %.9f"
          % (total_ph, sum(m.person_hours for m in meetings)))
    if rate is not None:
        per_meeting_cost = sum(m.person_hours * rate for m in meetings)
        lump_cost = total_ph * rate
        print("money identity: Σ (h×rate) == total h × rate  →  %.6f == %.6f "
              "(drift %.2e)"
              % (per_meeting_cost, lump_cost, abs(per_meeting_cost - lump_cost)))
    if defaulted:
        print("outcome defaulted to 'none': %d row(s) — optional to fix, disclosed either way" % defaulted)
    if future:
        print("scheduled rows dated after %s: %d — reports skip them, gate audits them"
              % (today.isoformat(), len(future)))
    print("kinds observed: %s" % ", ".join(kinds))
    print("distinct subjects: %d" % len(subjects))
    if len(past) < MIN_MEETINGS:
        print("")
        print("THIN: %d past meeting(s) < %d — reports will refuse to conclude (exit 3)"
              % (len(past), MIN_MEETINGS))
    else:
        print("")
        print("ledger healthy. exit 0")
    return EXIT_OK


# ------------------------------------------------------------------ main

def add_rate_args(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--rate", type=float, default=None, metavar="R",
                   help="yuan per person-hour")
    g.add_argument("--salary", type=float, default=None, metavar="S",
                   help="monthly salary; needs --hours")
    p.add_argument("--hours", type=float, default=None, metavar="H",
                   help="monthly working hours; needs --salary")


def add_common(p):
    add_rate_args(p)
    p.add_argument("ledger")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="full_house.py",
        description="full-house · Full House — the meeting-rental ledger")
    parser.add_argument("--version", action="version",
                        version="full-house %s" % VERSION)
    parser.add_argument("--today", default=None, metavar="YYYY-MM-DD",
                        help="pin 'today' for the past/scheduled split "
                             "(defaults to the real clock; pin it for "
                             "reproducible reports)")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("bill", help="total bill: person-hours, money, weekly cap")
    add_common(p)
    p.add_argument("--weekly-cap", type=float, default=WEEKLY_CAP_PH, metavar="H",
                   help="red line in person-hours/week (default %g)" % WEEKLY_CAP_PH)
    p.set_defaults(func=cmd_bill)

    p = sub.add_parser("top", help="priciest single meetings")
    add_common(p)
    p.add_argument("-n", type=int, default=5)
    p.set_defaults(func=cmd_top)

    p = sub.add_parser("recurring", help="annualize repeated series by subject")
    add_common(p)
    p.set_defaults(func=cmd_recurring)

    p = sub.add_parser("density", help="calendar shape: busiest days, sandwiches, chains")
    add_common(p)
    p.set_defaults(func=cmd_density)

    p = sub.add_parser("outcome", help="outcome accounting: cost per decision")
    add_common(p)
    p.set_defaults(func=cmd_outcome)

    p = sub.add_parser("simulate", help="counterfactual: cancel or thin a series")
    add_common(p)
    p.add_argument("action", choices=["cancel"])
    p.add_argument("--match", required=True, help="subject substring to cancel")
    p.add_argument("--every", type=int, default=1, metavar="K",
                   help="keep only every K-th occurrence (default: cancel all)")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("gate", help="audit the schedule against person-hour caps")
    add_common(p)
    p.add_argument("--weekly-cap", type=float, default=WEEKLY_CAP_PH, metavar="H")
    p.add_argument("--single-cap", type=float, default=SINGLE_CAP_PH, metavar="H")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("validate", help="ledger health check")
    add_common(p)
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
        # produce byte-identical reports on any machine, any day (the past/
        # scheduled split and the snapshots depend on it).
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
