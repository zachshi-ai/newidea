#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""border-budget · 窗期 —— 滚动停留额度账本（申根 90/180 口径）.

问题：短期签证的停留规则是一条滚动窗口——任意回看的 180 天里，
累计停留不得超过 90 天，入境日和离境日都算。这是一笔每天都在花费、
每天都在缓慢回血的预算，但护照上只有章：没有余额、没有恢复日程、
没有「最晚离境日」。凭感觉订票的人（「上次才去两周，这次一个月应
该没事」）就是在掷骰子，而掷输的代价是当场拒入境。

border-budget 把「窗期」补进账本。每次停留记一行（TSV 手编：入境/
离境/区域/备注，离境留空 = 仍在区内），确定性算出七本账：

  * balance   今日余额：窗口已用/剩余额度、今天就走最多能连住几天、
              接下来的额度释放日程（哪天回血几天）
  * check     行程过闸：给定入境/离境日，逐日核对窗口占用峰值，
              超限 exit 4；装不下时给出最晚离境日而不是一句「不行」
  * when      反解：想要 N 天完整额度，最早哪天出发；顺带回答
              「180 天内根本没有这样的日子」而不是硬给一个日期
  * gate      全部在途与已订行程逐段过闸 + 未来一年的窗口峰值预演
  * history   停留档案：每次行程天数、当时的窗口占用、全史峰值
              （你离超限最近的那一天）
  * simulate  反事实：取消/推迟某次行程后，余额与峰值怎么变
  * validate  账本体检：日期倒挂、同一区域重叠停留、未闭合行程
              披露、逐日法与裁剪法双算法恒等式对账

口径与诚实条款：入境日与离境日均计为停留日（申根规则）；窗口参数
可调（--window/--quota），有的地区口径不同；已订的未来行程同样占
额度（票已买，窗口不赊账）；离境留空的未闭合行程只计到 --today
为止，并在 validate 里披露；工具是计算器不是律师，逾期后果不建模。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

VERSION = "1.0.0"

COLUMNS = ("entry", "exit", "region", "note")
DEFAULT_WINDOW = 180
DEFAULT_QUOTA = 90
PROJECTION_DAYS = 365     # how far balance/gate look ahead
WHEN_HORIZON = 730        # how far `when` searches for a feasible start
OPEN_DISCLOSURE = True

EXIT_OK = 0
EXIT_DATA = 2
EXIT_THIN = 3
EXIT_RED = 4

USAGE = """usage: border_budget.py <command> [args]

commands:
  balance   <trips.tsv> [--region R] [--window W] [--quota Q]   today's balance
  check     <trips.tsv> --entry D --exit D [--region R]         gate one trip
  when      <trips.tsv> --days N [--from D] [--region R]        earliest start
  gate      <trips.tsv> [--region R]                            audit all booked trips
  history   <trips.tsv> [--region R]                            stay archive + peak
  simulate  <trips.tsv> cancel --match TEXT [--region R]        counterfactual
  validate  <trips.tsv>                                         ledger health

ledger columns (tab separated, one row per stay):
  entry  exit  region  note
  dates are YYYY-MM-DD; an empty exit means the stay is still open
  (counted up to --today only, disclosed by validate);
  region defaults to 'schengen' when the column is blank.
  All commands accept --today YYYY-MM-DD to pin 'today'.
"""


class LedgerError(Exception):
    """Bad ledger row or usage — exit 2."""


class ThinLedger(Exception):
    """Request cannot be answered honestly — exit 3."""


# ---------------------------------------------------------------- parsing

def parse_date(text, field):
    try:
        return date.fromisoformat(text.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad date %r in field %r (want YYYY-MM-DD)" % (text, field))


def norm_region(text):
    return (text or "").strip().casefold() or "schengen"


class Stay(object):
    __slots__ = ("entry", "exit", "region", "note", "line")

    def __init__(self, entry, exit_, region, note, line):
        self.entry = entry
        self.exit = exit_
        self.region = region
        self.note = note
        self.line = line


def read_ledger(path):
    """Parse trips.tsv into a list sorted by (entry, line)."""
    stays = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise LedgerError("cannot read ledger: %s" % exc)
    seen_header = False
    for lineno, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        cells = raw.split("\t")
        if not seen_header:
            header = [c.strip().casefold() for c in cells]
            if header[:2] != list(COLUMNS[:2]):
                raise LedgerError("line 1 must be a header row starting with "
                                  "%s (got %r)" % (" | ".join(COLUMNS), raw))
            seen_header = True
            continue
        if len(cells) < 2:
            raise LedgerError("line %d: expected 2-4 columns, got %d" % (lineno, len(cells)))
        entry = parse_date(cells[0], "entry (line %d)" % lineno)
        exit_text = cells[1].strip() if len(cells) > 1 else ""
        exit_ = parse_date(exit_text, "exit (line %d)" % lineno) if exit_text else None
        if exit_ is not None and exit_ < entry:
            raise LedgerError("line %d: exit %s is before entry %s"
                              % (lineno, exit_.isoformat(), entry.isoformat()))
        region = norm_region(cells[2]) if len(cells) > 2 else "schengen"
        note = cells[3].strip() if len(cells) > 3 else ""
        stays.append(Stay(entry, exit_, region, note, lineno))
    if not seen_header:
        raise LedgerError("missing header row with columns %s" % " | ".join(COLUMNS))
    stays.sort(key=lambda s: (s.entry, s.line))
    return stays


# ------------------------------------------------------------ window math

def stay_days_in_window(stay, win_start, win_end, today):
    """Days of this stay inside [win_start, win_end] (inclusive, both
    entry and exit days count). Open stays only count up to `today`."""
    end = stay.exit if stay.exit is not None else today
    lo = max(stay.entry, win_start)
    hi = min(end, win_end)
    if hi < lo:
        return 0
    return (hi - lo).days + 1


def occupied_days(stays, region, today, horizon_start, horizon_end):
    """Set of days occupied by any stay of `region`, clipped to
    [horizon_start, horizon_end]. Open stays count to `today` only."""
    days = set()
    for s in stays:
        if s.region != region:
            continue
        end = s.exit if s.exit is not None else today
        d = max(s.entry, horizon_start)
        end = min(end, horizon_end)
        while d <= end:
            days.add(d)
            d += timedelta(days=1)
    return days


def used_on(day, occ, window):
    """Window usage on `day`: occupied days inside [day-window+1, day]."""
    start = day - timedelta(days=window - 1)
    return sum(1 for d in occ if start <= d <= day)


def used_clipped(day, stays, region, today, window):
    """Same number via per-stay clipping — the identity twin of used_on."""
    win_start = day - timedelta(days=window - 1)
    return sum(stay_days_in_window(s, win_start, day, today)
               for s in stays if s.region == region)


def longest_feasible_from(start, stays, region, today, window, quota, limit):
    """Greedy: max n such that staying [start, start+n-1] keeps every
    day's window usage <= quota. The hypothetical stay itself occupies
    its days — the window charges you from the day you land."""
    occ = occupied_days(stays, region, today,
                        start - timedelta(days=window),
                        start + timedelta(days=limit))
    n = 0
    while n < limit:
        day = start + timedelta(days=n)
        occ.add(day)
        if used_on(day, occ, window) > quota:
            break
        n += 1
    return n


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# --------------------------------------------------------------- commands

def fmt(d):
    return d.isoformat() if d else "open"


def pick(args, stays):
    region = args.region.casefold()
    subset = [s for s in stays if s.region == region]
    if not subset and stays:
        regions = sorted(set(s.region for s in stays))
        raise LedgerError("no stays for region %r (ledger has: %s)"
                          % (region, ", ".join(regions)))
    return subset


def cmd_balance(args):
    stays = pick(args, read_ledger(args.ledger))
    today = args.today
    occ = occupied_days(stays, args.region.casefold(), today,
                        today - timedelta(days=args.window + PROJECTION_DAYS),
                        today + timedelta(days=PROJECTION_DAYS))
    used = used_on(today, occ, args.window)
    spare = args.quota - used

    print("== balance · 窗口余额 (%s, %d/%d) ==" % (args.region, args.window, args.quota))
    print("window on %s: [%s .. %s]" % (today.isoformat(),
                                        (today - timedelta(days=args.window - 1)).isoformat(),
                                        today.isoformat()))
    print("used %d of %d day(s) — spare quota %d day(s)" % (used, args.quota, spare))
    if used > args.quota:
        print("")
        print("RED LINE  window usage %d already exceeds the quota %d — exit 4"
              % (used, args.quota))
        return EXIT_RED

    walk = longest_feasible_from(today, stays, args.region.casefold(),
                                 today, args.window, args.quota, PROJECTION_DAYS)
    print("leave today, stay at most %d more day(s) (latest exit %s)"
          % (walk, (today + timedelta(days=walk - 1)).isoformat() if walk else "n/a"))

    # release schedule: aggregate runs of days where usage drops going forward
    daily = []
    prev = used
    for d in daterange(today + timedelta(days=1), today + timedelta(days=PROJECTION_DAYS)):
        u = used_on(d, occ, args.window)
        daily.append((d, prev - u, u))
        prev = u
    drops = [(d, delta, u) for d, delta, u in daily if delta > 0]
    if drops:
        print("")
        print("upcoming releases (day quota flows back in):")
        run_start, run_delta, run_end, last_u = drops[0][0], drops[0][1], drops[0][0], drops[0][2]
        runs = []
        for d, delta, u in drops[1:]:
            if d - run_end == timedelta(days=1) and delta == run_delta:
                run_end, last_u = d, u
                continue
            runs.append((run_start, run_end, run_delta, last_u))
            run_start, run_delta, run_end, last_u = d, delta, d, u
        runs.append((run_start, run_end, run_delta, last_u))
        for rs, re_, delta, u in runs[:8]:
            span = rs.isoformat() if rs == re_ else "%s .. %s" % (rs.isoformat(), re_.isoformat())
            print("  %s  +%d/day -> spare %d by the end" % (span, delta, args.quota - u))
    else:
        print("")
        print("no release within %d days: the window stays at %d used."
              % (PROJECTION_DAYS, used))
    return EXIT_OK


def check_trip(stays, region, entry, exit_, today, window, quota):
    """Audit one trip against the ledger (the trip itself included).
    Returns (peak_day, peak_used, worst_ratio_day, latest_ok_exit)."""
    occ = occupied_days(stays + [Stay(entry, exit_, region, "", 0)], region, today,
                        entry - timedelta(days=window), exit_ + timedelta(days=1))
    peak_day, peak_used, breach = entry, -1, None
    for d in daterange(entry, exit_):
        u = used_on(d, occ, window)
        if u > peak_used:
            peak_day, peak_used = d, u
        if u > quota and breach is None:
            breach = d
    latest = (breach - timedelta(days=1)) if breach else exit_
    return peak_day, peak_used, breach, latest


def cmd_check(args):
    stays = pick(args, read_ledger(args.ledger))
    today = args.today
    entry, exit_ = args.entry, args.exit_
    if entry < today - timedelta(days=args.window):
        raise LedgerError("--entry %s is older than one window; audit history "
                          "with `history` instead" % entry.isoformat())

    peak_day, peak_used, breach, latest = check_trip(
        stays, args.region.casefold(), entry, exit_, today, args.window, args.quota)
    days = (exit_ - entry).days + 1

    print("== check · 行程过闸 (%s) ==" % args.region)
    clash = [s for s in stays if s.entry <= exit_ and (s.exit or today) >= entry]
    if clash:
        print("NOTE  trip overlaps %d booked stay(s): shared days count once "
              "(rebooking semantics), not twice" % len(clash))
    print("trip %s .. %s = %d day(s) (entry and exit days both count)"
          % (entry.isoformat(), exit_.isoformat(), days))
    print("window usage peaks %d/%d on %s" % (peak_used, args.quota, peak_day.isoformat()))
    if breach is None:
        margin = args.quota - peak_used
        print("VERDICT: SAFE — %d day(s) of margin. exit 0" % margin)
        return EXIT_OK
    print("VERDICT: OVER by %d day(s) on %s — exit 4" % (peak_used - args.quota,
                                                         breach.isoformat()))
    legal = (latest - entry).days + 1
    if legal >= 1:
        print("shortest fix: exit by %s (a %d-day stay still fits)"
              % (latest.isoformat(), legal))
    else:
        print("even one day does not fit: earliest possible entry is a "
              "different day — see `when`.")
    return EXIT_RED


def cmd_when(args):
    stays = pick(args, read_ledger(args.ledger))
    today = args.today
    if args.days > args.quota:
        raise LedgerError("--days %d can never fit a quota of %d"
                          % (args.days, args.quota))
    occ = occupied_days(stays, args.region.casefold(), today,
                        today - timedelta(days=args.window),
                        today + timedelta(days=WHEN_HORIZON))
    start_from = args.from_date or today
    horizon_end = today + timedelta(days=WHEN_HORIZON)
    limit = (horizon_end - start_from).days + 1

    best = None
    for offset in range(0, max(1, limit - args.days)):
        s = start_from + timedelta(days=offset)
        fit = longest_feasible_from(s, stays, args.region.casefold(),
                                    today, args.window, args.quota, args.days)
        if fit >= args.days:
            best = s
            break
    print("== when · 最早出发日 (%s, want %d day(s)) ==" % (args.region, args.days))
    if best is None:
        raise ThinLedger("no start within %d days affords %d consecutive "
                         "day(s); consider shrinking the trip or see the "
                         "release schedule in `balance`" % (WHEN_HORIZON, args.days))
    print("earliest start: %s -> %s (%d day(s), every day within quota)"
          % (best.isoformat(), (best + timedelta(days=args.days - 1)).isoformat(),
             args.days))
    wait = (best - start_from).days
    if wait > 0:
        print("that is %d day(s) of waiting from %s — the window is the "
              "wait." % (wait, start_from.isoformat()))
    return EXIT_OK


def cmd_gate(args):
    stays_all = read_ledger(args.ledger)
    stays = pick(args, stays_all)
    today = args.today
    region = args.region.casefold()
    upcoming = [s for s in stays if (s.exit is None and s.entry >= today)
                or (s.exit is not None and s.entry >= today)]
    open_stays = [s for s in stays if s.exit is None]

    print("== gate · 已订行程门禁 (%s, %d/%d) ==" % (region, args.window, args.quota))
    print("booked trips ahead: %d%s" % (len(upcoming),
                                        "  (open stay(s): %d)" % len(open_stays)
                                        if open_stays else ""))
    if not upcoming and not open_stays:
        print("")
        print("nothing booked ahead — gate has nothing to refuse. exit 0")
        return EXIT_OK

    breaches = []
    occ = occupied_days(stays, region, today,
                        today - timedelta(days=args.window),
                        today + timedelta(days=WHEN_HORIZON))
    for s in sorted(upcoming, key=lambda s: s.entry):
        exit_ = s.exit or today
        if exit_ < s.entry:
            continue
        _, peak_used, breach, latest = check_trip(
            stays, region, s.entry, exit_, today, args.window, args.quota)
        label = s.note or "%s.." % s.entry.isoformat()
        if breach is not None:
            breaches.append("%s .. %s %r peaks %d/%d on %s (latest exit %s)"
                            % (s.entry.isoformat(), fmt(s.exit), label, peak_used,
                               args.quota, breach.isoformat(), latest.isoformat()))
    # forward projection of the daily window usage
    proj_end = today + timedelta(days=PROJECTION_DAYS)
    peak_day, peak_used = today, used_on(today, occ, args.window)
    for d in daterange(today + timedelta(days=1), proj_end):
        u = used_on(d, occ, args.window)
        if u > peak_used:
            peak_day, peak_used = d, u
    print("projected window peak: %d/%d on %s"
          % (peak_used, args.quota, peak_day.isoformat()))
    if peak_used > args.quota:
        breaches.append("projection: usage %d exceeds quota on %s"
                        % (peak_used, peak_day.isoformat()))
    if open_stays:
        for s in open_stays:
            u = used_on(today, occ, args.window)
            if u > args.quota:
                breaches.append("open stay since %s already pushes usage %d "
                                "over quota" % (s.entry.isoformat(), u))
    if breaches:
        print("")
        for b in breaches:
            print("BREACH  %s" % b)
        print("")
        print("VERDICT: %d breach(es). exit 4 — move the entry, cut the days, "
              "or split the trip before the border does it for you."
              % len(breaches))
        return EXIT_RED
    print("")
    print("VERDICT: SAFE — every booked trip fits, peak %d/%d. exit 0"
          % (peak_used, args.quota))
    return EXIT_OK


def cmd_history(args):
    stays = pick(args, read_ledger(args.ledger))
    today = args.today
    region = args.region.casefold()
    past = [s for s in stays if s.exit is not None and s.exit <= today]
    occ = occupied_days(stays, region, today,
                        today - timedelta(days=args.window + PROJECTION_DAYS), today)

    print("== history · 停留档案 (%s) ==" % region)
    if not past:
        print("no closed stays on record yet — the window starts empty.")
        return EXIT_OK
    total = 0
    for s in past:
        days = (s.exit - s.entry).days + 1
        total += days
        at_exit = used_on(s.exit, occ, args.window)
        print("  %s .. %s  %3d day(s)  window %d/%d at exit  %s"
              % (s.entry.isoformat(), s.exit.isoformat(), days, at_exit,
                 args.quota, s.note or ""))
    print("")
    print("%d trip(s), %d day(s) on record" % (len(past), total))
    # all-time closest approach to the quota
    peak_day, peak_used = None, -1
    for d in daterange(past[0].entry, today):
        u = used_on(d, occ, args.window)
        if u > peak_used:
            peak_day, peak_used = d, u
    print("all-time window peak: %d/%d on %s — closest you ever came to the line"
          % (peak_used, args.quota, peak_day.isoformat()))
    return EXIT_OK


def cmd_simulate(args):
    stays_all = read_ledger(args.ledger)
    stays = pick(args, stays_all)
    today = args.today
    if not args.match:
        raise LedgerError("--match needs a note/date substring to cancel")
    needle = args.match.strip().casefold()
    hits = [s for s in stays if needle in (s.note or "").casefold()
            or needle in s.entry.isoformat()]
    if not hits:
        raise LedgerError("no stay matches %r by note or entry date" % args.match)

    region = args.region.casefold()
    occ_with = occupied_days(stays, region, today,
                             today - timedelta(days=args.window),
                             today + timedelta(days=WHEN_HORIZON))
    remaining = [s for s in stays if s not in hits]
    occ_without = occupied_days(remaining, region, today,
                                today - timedelta(days=args.window),
                                today + timedelta(days=WHEN_HORIZON))
    used_now = used_on(today, occ_with, args.window)
    used_after = used_on(today, occ_without, args.window)

    print("== simulate · 反事实：不去了 ==")
    for s in hits:
        print("cancelled: %s .. %s  %s" % (s.entry.isoformat(), fmt(s.exit),
                                           s.note or "(no note)"))
    print("")
    print("balance today: %d/%d -> %d/%d (spare %d -> %d)"
          % (used_now, args.quota, used_after, args.quota,
             args.quota - used_now, args.quota - used_after))

    def peak_of(group):
        occ = occupied_days(group, region, today,
                            today - timedelta(days=args.window),
                            today + timedelta(days=WHEN_HORIZON))
        best = used_on(today, occ, args.window)
        for d in daterange(today + timedelta(days=1),
                           today + timedelta(days=PROJECTION_DAYS)):
            u = used_on(d, occ, args.window)
            if u > best:
                best = u
        return best

    print("projected %d-day peak: %d/%d -> %d/%d"
          % (PROJECTION_DAYS, peak_of(stays), args.quota,
             peak_of(remaining), args.quota))
    walk = longest_feasible_from(today, remaining, region, today,
                                 args.window, args.quota, PROJECTION_DAYS)
    walk_now = longest_feasible_from(today, stays, region, today,
                                     args.window, args.quota, PROJECTION_DAYS)
    print("leave today: could stay %d day(s) instead of %d%s"
          % (walk, walk_now,
             "" if walk != walk_now else "  (the cancelled trip was in the "
             "future — today's walk is unchanged)"))
    print("")
    print("the ledger does not judge the trip — it prices the days it "
          "hands back to the window.")
    return EXIT_OK


def cmd_validate(args):
    stays = read_ledger(args.ledger)
    today = args.today
    open_stays = [s for s in stays if s.exit is None]
    future = [s for s in stays if s.exit is not None and s.entry > today]

    # overlap check per region (two stays in one region cannot overlap)
    by_region = {}
    for s in stays:
        by_region.setdefault(s.region, []).append(s)
    overlaps = []
    for region, group in by_region.items():
        group = sorted(group, key=lambda s: s.entry)
        for a, b in zip(group, group[1:]):
            a_end = a.exit or today
            if b.entry <= a_end:
                overlaps.append("%s: %s..%s overlaps %s" %
                                (region, a.entry.isoformat(), fmt(a.exit),
                                 b.entry.isoformat()))

    # double-algorithm identity on a probe day (today), per region
    identities = []
    for region in sorted(by_region):
        occ = occupied_days(by_region[region], region, today,
                            today - timedelta(days=DEFAULT_WINDOW + 1), today)
        a = used_on(today, occ, DEFAULT_WINDOW)
        b = used_clipped(today, by_region[region], region, today, DEFAULT_WINDOW)
        identities.append((region, a, b))

    print("== validate · 账本体检 ==")
    print("stays: %d  (open %d · future %d)" % (len(stays), len(open_stays), len(future)))
    for region, a, b in identities:
        print("identity (%s): day-by-day == per-stay clipping  ->  %d == %d"
              % (region, a, b))
    if overlaps:
        for o in overlaps:
            print("OVERLAP  %s — one person cannot be inside twice (exit 2)"
                  % o)
    if open_stays:
        print("open stay(s): %s — counted up to %s only, close them when you "
              "land back home" % (", ".join(s.entry.isoformat() for s in open_stays),
                                  today.isoformat()))
    if overlaps:
        return EXIT_DATA
    print("")
    print("ledger healthy. exit 0")
    return EXIT_OK


# ------------------------------------------------------------------ main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="border_budget.py",
        description="border-budget · Border Budget — the rolling-stay ledger")
    parser.add_argument("--version", action="version",
                        version="border-budget %s" % VERSION)
    parser.add_argument("--today", default=None, metavar="YYYY-MM-DD",
                        help="pin 'today' (defaults to the real clock; pin it "
                             "for reproducible reports)")
    sub = parser.add_subparsers(dest="command")

    def common(p, need_region=True):
        p.add_argument("ledger")
        if need_region:
            p.add_argument("--region", default="schengen")
        p.add_argument("--window", type=int, default=DEFAULT_WINDOW)
        p.add_argument("--quota", type=int, default=DEFAULT_QUOTA)
        return p

    p = common(sub.add_parser("balance", help="today's spare days + release schedule"))
    p.set_defaults(func=cmd_balance)

    p = common(sub.add_parser("check", help="gate one trip"))
    p.add_argument("--entry", required=True)
    p.add_argument("--exit", dest="exit_", required=True)
    p.set_defaults(func=cmd_check)

    p = common(sub.add_parser("when", help="earliest start for N full days"))
    p.add_argument("--days", type=int, required=True)
    p.add_argument("--from", dest="from_date", default=None)
    p.set_defaults(func=cmd_when)

    p = common(sub.add_parser("gate", help="audit all booked trips"))
    p.set_defaults(func=cmd_gate)

    p = common(sub.add_parser("history", help="stay archive + all-time peak"))
    p.set_defaults(func=cmd_history)

    p = common(sub.add_parser("simulate", help="counterfactual: cancel a stay"))
    p.add_argument("action", choices=["cancel"])
    p.add_argument("--match", required=True)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("validate", help="ledger health check")
    p.add_argument("ledger")
    p.set_defaults(func=cmd_validate)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_DATA
    try:
        # 'Today' is a parameter, not a clock reading: the same ledger must
        # produce byte-identical reports on any machine, any day.
        if getattr(args, "today", None) is None:
            args.today = date.today()
        else:
            args.today = parse_date(args.today, "--today")
        if hasattr(args, "window"):
            if args.window <= 0 or args.quota <= 0:
                raise LedgerError("--window and --quota must be positive")
        for opt in ("entry", "exit_", "from_date"):
            raw = getattr(args, opt, None)
            if raw is not None:
                setattr(args, opt, parse_date(raw, "--%s" % opt.rstrip("_")))
        return args.func(args)
    except LedgerError as exc:
        sys.stderr.write("data error (exit 2): %s\n" % exc)
        return EXIT_DATA
    except ThinLedger as exc:
        sys.stderr.write("cannot answer honestly (exit 3): %s\n" % exc)
        return EXIT_THIN


if __name__ == "__main__":
    sys.exit(main())
