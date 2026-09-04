#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search-tax · 寻物税 —— 找不到东西的时间与重购账本.

问题：寻物时间没有账单。每次找不到钥匙的五分钟都感觉是运气差，
年化下来却是九个小时——一个工作日。更疼的那半笔藏在消费记录里：
「找不到 → 再买一个」的重购，买完第二天旧的原形毕露。翻找的时
间、重复购置的钱、反复失踪的惯犯、设了固定位置却没人回访的疗效，
四本账从来没有人记过。

search-tax 把「又没找到」补进账本。每次翻找记一行（TSV 手编，
三种事件），确定性算出五本账：

  * report   总账：寻物分钟 → 周均 → 年化寻物税；惯犯排行；
             寻获地分布（找回来时都在哪）；给了时薪才有钱账
  * repeat   惯犯审计：窗口内寻物 ≥3 次的点 REPEAT OFFENDER
             exit 4——灯亮在你再去配一把钥匙之前
  * dup      重购税：每笔「再买一个」对账寻物史——有寻史的
             坐实为找不到导致（CONFIRMED），无寻史的如实披露
  * place    固定位置处方与回访：寻获地众数告诉你该在哪儿给它
             安家；设位前后各 30 天的寻物频次对比——疗效实测，
             不发明治愈率
  * simulate 反事实：给某件惯犯设固定位置能省多少——治愈率只
             从账本内部的 fix 回访实测，没有内部证据就拒绝外推
  * validate 体检：分型字段守卫、重复行、恒等式（分物品分钟
             划分 == 总分钟；分型计数 == 总行数）

诚实条款：翻找时长是回忆值，不建模秒表（±2 分钟足够，精确是
幻觉）；账本自锚定——所有窗口都钉在账本日期上，不读墙上的钟，
同一本账任何机器任何一天跑出的结果逐字节一致；漏记只会低估税
额，宁可低估不虚报；工具不替你设位置，它只拒绝「再买一个」
继续免费。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, OrderedDict
from datetime import date, timedelta

VERSION = "1.0.0"

COLUMNS = ("date", "event", "item", "minutes", "place", "amount", "note")
EVENTS = ("search", "buy", "fix")
NOT_FOUND = ("", "-", "?")

REPEAT_WINDOW_DAYS = 90   # repeat-offender lookback, anchored at ledger end
REPEAT_HITS = 3           # searches within the window → REPEAT OFFENDER
WATCH_HITS = 2            # one below the offender line → WATCH
PLACE_MODE_MIN = 2        # a place must recur this often to be a prescription
FIX_WINDOW_DAYS = 30      # pre/post fix review window
POST_MIN_DAYS = 7         # less observed post-fix coverage → too early to judge
WORKING_FACTOR = 0.5      # post rate ≤ pre rate × factor → the fix is working
ANNUAL_WEEKS = 52.0
MIN_SEARCH_EVENTS = 8     # refuse conclusions below this many searches
MIN_COVERAGE_DAYS = 14

EXIT_OK = 0
EXIT_DATA = 2
EXIT_THIN = 3
EXIT_RED = 4

USAGE = """usage: search_tax.py <command> [args]

commands:
  report   <ledger.tsv> [--wage W | --salary S --hours H]  the annualized tax
  repeat   <ledger.tsv> [--window DAYS] [--hits N]         repeat offenders
  dup      <ledger.tsv>                                    duplicate-buy audit
  place    <ledger.tsv> [--days D]                         prescriptions & reviews
  simulate <ledger.tsv> fix --item NAME [--cure F] [--wage W]
  validate <ledger.tsv>                                    ledger health

ledger columns (tab separated, one row per event):
  date  event  item  minutes  place  amount  note
  event is search | buy | fix; item is the lost thing's name.
  search: minutes >= 1, place = where it turned up (blank/- = never found).
  buy:    amount > 0 (a replacement bought because the old one was lost).
  fix:    place = the fixed home assigned to the item.
  All windows are anchored to the ledger itself — no wall clock, no --today:
  the same ledger yields byte-identical reports on any machine, any day.
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


def parse_positive_int(text, field):
    try:
        value = int(text.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad integer %r in field %r" % (text, field))
    if value <= 0:
        raise LedgerError("field %r must be a positive integer, got %d" % (field, value))
    return value


def parse_amount(text, field):
    try:
        value = float(text.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad amount %r in field %r" % (text, field))
    if value <= 0:
        raise LedgerError("field %r must be > 0, got %s" % (field, value))
    return value


def _clean(text):
    return text.strip() if text else ""


def parse_ledger(path):
    """Read the event-stream ledger. Deterministic: sorted by (date, row#)."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise LedgerError("cannot read ledger: %s" % exc)

    rows = []
    seen = set()
    header_seen = False
    for lineno, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if not header_seen and parts[0].strip() == "date":
            header_seen = True
            continue
        if len(parts) < 6 or len(parts) > 7:
            raise LedgerError(
                "line %d: want 6-7 columns (date event item minutes place "
                "amount note), got %d" % (lineno, len(parts)))
        date_s, event, item, minutes_s, place_s, amount_s = (_clean(p) for p in parts[:6])
        note = _clean(parts[6]) if len(parts) == 7 else ""
        day = parse_date(date_s, "date (line %d)" % lineno)
        if event not in EVENTS:
            raise LedgerError("line %d: event must be one of %s, got %r"
                              % (lineno, "/".join(EVENTS), event))
        if not item:
            raise LedgerError("line %d: item must not be empty" % lineno)
        minutes = place = None
        amount = None
        if event == "search":
            if minutes_s:
                minutes = parse_positive_int(minutes_s, "minutes (line %d)" % lineno)
            else:
                raise LedgerError("line %d: search rows need minutes >= 1" % lineno)
            if amount_s:
                raise LedgerError("line %d: a search row must not carry an amount" % lineno)
            place = "" if place_s in NOT_FOUND else place_s
        elif event == "buy":
            if not amount_s:
                raise LedgerError("line %d: buy rows need amount > 0" % lineno)
            amount = parse_amount(amount_s, "amount (line %d)" % lineno)
            if minutes_s or place_s:
                raise LedgerError("line %d: a buy row must not carry minutes/place" % lineno)
        else:  # fix
            if not place_s:
                raise LedgerError("line %d: fix rows need place (the new home)" % lineno)
            place = place_s
            if minutes_s or amount_s:
                raise LedgerError("line %d: a fix row must not carry minutes/amount" % lineno)
        key = (day, event, item, minutes, place, amount)
        if key in seen:
            raise LedgerError("line %d: exact duplicate row %s" % (lineno, key))
        seen.add(key)
        rows.append(OrderedDict([
            ("date", day), ("event", event), ("item", item),
            ("minutes", minutes), ("place", place), ("amount", amount),
            ("note", note), ("line", lineno),
        ]))
    if not header_seen:
        raise LedgerError("no header row starting with 'date' found")
    if not rows:
        raise LedgerError("ledger has no events")
    rows.sort(key=lambda r: (r["date"], r["line"]))
    return rows


# ------------------------------------------------------------- wage (honesty)

def resolve_wage(args):
    """Hourly wage or None. Unpriced ledgers still get every minute."""
    wage = getattr(args, "wage", None)
    salary = getattr(args, "salary", None)
    hours = getattr(args, "hours", None)
    if wage is not None and (salary is not None or hours is not None):
        raise LedgerError("--wage and --salary/--hours are mutually exclusive")
    if salary is not None or hours is not None:
        if salary is None or hours is None:
            raise LedgerError("--salary needs --hours (monthly pay, monthly hours)")
        if salary <= 0 or hours <= 0:
            raise LedgerError("--salary/--hours must be > 0")
        return salary / hours
    if wage is not None:
        if wage <= 0:
            raise LedgerError("--wage must be > 0")
        return wage
    return None


# ------------------------------------------------------------- aggregations

class Stats(object):
    """Deterministic aggregates over the whole ledger."""

    def __init__(self, rows):
        self.rows = rows
        self.searches = [r for r in rows if r["event"] == "search"]
        self.buys = [r for r in rows if r["event"] == "buy"]
        self.fixes = [r for r in rows if r["event"] == "fix"]
        self.first = rows[0]["date"]
        self.last = rows[-1]["date"]
        self.span_days = (self.last - self.first).days + 1
        # ledger weeks: first Monday on/before the first event → last Sunday
        first_monday = self.first - timedelta(days=self.first.weekday())
        last_sunday = self.last + timedelta(days=6 - self.last.weekday())
        self.weeks = ((last_sunday - first_monday).days + 1) / 7.0
        self.total_minutes = sum(r["minutes"] for r in self.searches)

    def check_thin(self):
        if len(self.searches) < MIN_SEARCH_EVENTS:
            raise ThinLedger("only %d search events (need >= %d) — start logging, "
                             "come back when the ledger has room to speak"
                             % (len(self.searches), MIN_SEARCH_EVENTS))
        if self.span_days < MIN_COVERAGE_DAYS:
            raise ThinLedger("coverage %d days (need >= %d)" % (self.span_days, MIN_COVERAGE_DAYS))

    def per_item(self):
        """item → (search count, minutes, places where found)."""
        out = OrderedDict()
        for row in self.searches:
            count, mins, places = out.get(row["item"], (0, 0, []))
            if row["place"]:
                places.append(row["place"])
            out[row["item"]] = (count + 1, mins + row["minutes"], places)
        return OrderedDict(sorted(out.items(), key=lambda kv: (-kv[1][1], kv[0])))

    def searched_items(self):
        return set(r["item"] for r in self.searches)

    def annual_minutes(self):
        return self.total_minutes / self.weeks * ANNUAL_WEEKS

    def place_histogram(self):
        counter = Counter(r["place"] for r in self.searches if r["place"])
        return counter.most_common()

    def repeat_window_start(self, window_days):
        return self.last - timedelta(days=window_days - 1)

    def searches_in(self, item, start, end):
        return [r for r in self.searches
                if r["item"] == item and start <= r["date"] <= end]

    def fix_review(self, fix_row, window_days):
        """Pre/post hunt rates per observed day (windows clamp to the ledger)."""
        item = fix_row["item"]
        pre_start = max(fix_row["date"] - timedelta(days=window_days - 1), self.first)
        pre_end = fix_row["date"]
        post_start = fix_row["date"] + timedelta(days=1)
        post_end = min(fix_row["date"] + timedelta(days=window_days), self.last)
        pre = self.searches_in(item, pre_start, pre_end)
        post = self.searches_in(item, post_start, post_end)
        pre_days = (pre_end - pre_start).days + 1
        post_days = (post_end - post_start).days + 1 if post_end >= post_start else 0
        return {
            "pre_n": len(pre), "pre_days": pre_days,
            "pre_rate": len(pre) / float(pre_days),
            "post_n": len(post), "post_days": post_days,
            "post_rate": len(post) / float(post_days) if post_days else 0.0,
        }

    def observed_cure(self, window_days):
        """Median measured reduction across judgable fix rows, or None."""
        reductions = []
        for fix_row in self.fixes:
            review = self.fix_review(fix_row, window_days)
            if review["post_days"] < POST_MIN_DAYS:
                continue  # the ledger ended too soon after the fix
            if review["pre_rate"] == 0:
                reductions.append(1.0 if review["post_rate"] == 0 else 0.0)
                continue
            reductions.append(max(0.0, min(1.0, 1.0 - review["post_rate"] / review["pre_rate"])))
        if not reductions:
            return None
        reductions.sort()
        n = len(reductions)
        mid = n // 2
        return reductions[mid] if n % 2 else (reductions[mid - 1] + reductions[mid]) / 2.0


def mode_place(places):
    """The recurring hiding spot, if one dominates. None → it wanders."""
    if not places:
        return None, 0, False
    counter = Counter(places)
    top = counter.most_common()
    best_count = top[0][1]
    if best_count < PLACE_MODE_MIN:
        return None, best_count, False
    winners = sorted(p for p, c in top if c == best_count)
    return (winners[0], best_count, len(winners) > 1)


# ---------------------------------------------------------------- commands

def _money(wage, minutes):
    return wage * minutes / 60.0


def cmd_report(args):
    wage = resolve_wage(args)
    rows = parse_ledger(args.ledger)
    stats = Stats(rows)
    stats.check_thin()

    weekly = stats.total_minutes / stats.weeks
    annual = stats.annual_minutes()
    per_item = stats.per_item()

    print("SEARCH TAX · 寻物税 report")
    print("ledger: %s  events: %d search / %d buy / %d fix"
          % (args.ledger, len(stats.searches), len(stats.buys), len(stats.fixes)))
    print("coverage: %s -> %s  (%d days, %.0f ledger weeks)"
          % (stats.first, stats.last, stats.span_days, stats.weeks))
    print("")
    print("hunt time: %d min total | %.1f min/week | annualized %.0f min = %.1f h/yr"
          % (stats.total_minutes, weekly, annual, annual / 60.0))
    print("  ^ the search tax: %.1f hours a year spent finding things you own"
          % (annual / 60.0))
    print("")
    print("most hunted (by minutes):")
    for item, (count, mins, _places) in list(per_item.items())[: args.top]:
        print("  %-14s %2d hunts  %3d min  (avg %.1f min/hunt)"
              % (item, count, mins, mins / float(count)))
    histogram = stats.place_histogram()
    if histogram:
        print("")
        print("where they turn up (found-in-place counts):")
        for place, count in histogram[: args.top]:
            print("  %-14s x%d" % (place, count))
    buys_total = sum(r["amount"] for r in stats.buys)
    if stats.buys:
        print("")
        print("duplicate buys: %d rows, %.2f total (see `dup` for the audit)"
              % (len(stats.buys), buys_total))
    if wage is None:
        print("")
        print("NOTE unpriced: minutes are the hard currency; add --wage (or "
              "--salary/--hours) to translate the tax into money.")
    else:
        hunt_money = _money(wage, annual)
        print("")
        print("at %.2f/h: search tax %.2f/yr + duplicate buys %.2f = %.2f/yr"
              % (wage, hunt_money, buys_total, hunt_money + buys_total))
    return EXIT_OK


def cmd_repeat(args):
    rows = parse_ledger(args.ledger)
    stats = Stats(rows)
    stats.check_thin()
    window_start = stats.repeat_window_start(args.window)

    print("REPEAT OFFENDERS · 惯犯审计 (window %d days: %s -> %s)"
          % (args.window, window_start, stats.last))
    offenders = []
    watchers = []
    for item in sorted(stats.searched_items()):
        found = stats.searches_in(item, window_start, stats.last)
        count = len(found)
        if count == 0:
            continue
        mode, mode_count, tie = mode_place([r["place"] for r in found if r["place"]])
        mins = sum(r["minutes"] for r in found)
        verdict = "REPEAT OFFENDER" if count >= args.hits else "WATCH"
        if verdict == "REPEAT OFFENDER":
            offenders.append(item)
        else:
            watchers.append(item)
        line = "  %-14s x%d hunts  %3d min in window  %s" % (item, count, mins, verdict)
        spots = sorted({r["place"] for r in found if r["place"]})
        if mode and not tie:
            line += "  -> prescription: fixed home at '%s' (x%d)" % (mode, mode_count)
        elif mode and tie:
            line += "  -> wanders between %s (no single home to assign)" % "/".join(spots)
        else:
            line += "  -> no recurring hiding spot yet"
        print(line)
    if not offenders and not watchers:
        print("  no item hunted more than once in the window")
    elif watchers:
        print("  (WATCH = one hunt below the offender line)")
    if offenders:
        print("")
        print("RED LINE: %d repeat offender(s). Before you buy a replacement, "
              "give these a fixed home (`place` for prescriptions)." % len(offenders))
        return EXIT_RED
    return EXIT_OK


def cmd_dup(args):
    rows = parse_ledger(args.ledger)
    stats = Stats(rows)
    if not stats.buys:
        raise ThinLedger("no `buy` rows in the ledger — nothing to audit")

    print("DUPLICATE-BUY AUDIT · 重购税对账")
    history = stats.searched_items()
    per_buy_item = OrderedDict()
    for row in stats.buys:
        amount, count = per_buy_item.get(row["item"], (0.0, 0))
        per_buy_item[row["item"]] = (amount + row["amount"], count + 1)
    per_buy_item = OrderedDict(sorted(per_buy_item.items(), key=lambda kv: (-kv[1][0], kv[0])))

    confirmed_items = 0
    total = 0.0
    for item, (amount, count) in per_buy_item.items():
        has_history = item in history
        if has_history:
            confirmed_items += 1
        total += amount
        verdict = "CONFIRMED (hunt history: lost it, then bought it twice)" \
            if has_history else "UNEXPLAINED (no hunt on record — why did you rebuy?)"
        print("  %-14s x%d buy  %8.2f  %s" % (item, count, amount, verdict))
    print("")
    print("duplicate-buy total: %.2f across %d item(s); "
          "confirmation rate %d/%d = %.1f%%"
          % (total, len(per_buy_item), confirmed_items, len(per_buy_item),
             100.0 * confirmed_items / len(per_buy_item)))
    print("  CONFIRMED rows are the price of not knowing where things live;")
    print("  UNEXPLAINED rows are for you to explain — the ledger only asks.")
    return EXIT_OK


def cmd_place(args):
    rows = parse_ledger(args.ledger)
    stats = Stats(rows)
    stats.check_thin()

    print("FIXED-HOME CLINIC · 固定位置处方与回访 (review window %d days)"
          % args.days)
    fixed_items = set(f["item"] for f in stats.fixes)
    print("")
    print("prescriptions (items still unfixed, hunted in a recurring spot):")
    prescribed = 0
    for item, (count, mins, places) in stats.per_item().items():
        if item in fixed_items:
            continue
        mode, mode_count, tie = mode_place(places)
        if mode and not tie:
            prescribed += 1
            print("  %-14s x%d hunts -> give it a home at '%s' (found there x%d)"
                  % (item, count, mode, mode_count))
        elif tie:
            spots = "/".join(sorted(set(places)))
            print("  %-14s wanders between %s — watch it before prescribing" % (item, spots))
    if not prescribed:
        print("  (no single-spot wanderers left to prescribe)")

    print("")
    print("reviews (fix rows, %d-day before/after rates per observed day):" % args.days)
    judgable = 0
    for fix_row in stats.fixes:
        review = stats.fix_review(fix_row, args.days)
        if review["post_days"] < POST_MIN_DAYS:
            print("  %-14s fixed at '%s' on %s -> TOO EARLY (only %d of %d post days "
                  "in the ledger; come back when it had chances to wander)"
                  % (fix_row["item"], fix_row["place"], fix_row["date"],
                     review["post_days"], args.days))
            continue
        judgable += 1
        if review["pre_rate"] == 0 and review["post_rate"] == 0:
            verdict = "QUIET (no hunts on either side of the fix)"
        elif review["pre_rate"] > 0 and review["post_rate"] <= review["pre_rate"] * WORKING_FACTOR:
            verdict = "WORKING (post %.3f/day vs pre %.3f/day)" % (review["post_rate"], review["pre_rate"])
        else:
            verdict = "NO-CURE (post %.3f/day vs pre %.3f/day — wrong home, " \
                      "or the home is not the habit)" % (review["post_rate"], review["pre_rate"])
        print("  %-14s fixed at '%s' on %s -> %s"
              % (fix_row["item"], fix_row["place"], fix_row["date"], verdict))
    if not stats.fixes:
        print("  (no fix rows yet)")
    if judgable:
        print("")
        print("measured cure rate feeds `simulate fix` — the ledger is the lab.")
    return EXIT_OK


def cmd_simulate(args):
    wage = resolve_wage(args)
    rows = parse_ledger(args.ledger)
    stats = Stats(rows)
    window_start = stats.repeat_window_start(REPEAT_WINDOW_DAYS)
    found = stats.searches_in(args.item, window_start, stats.last)
    if not found:
        raise LedgerError("item %r has no search events in the %d-day window "
                          "(ledger ends %s)" % (args.item, REPEAT_WINDOW_DAYS, stats.last))
    if args.cure is not None and not (0.0 < args.cure < 1.0):
        raise LedgerError("--cure must be strictly between 0 and 1, got %s" % args.cure)

    if args.cure is not None:
        cure = args.cure
        source = "assumed (--cure given; external assumption, treat with suspicion)"
    else:
        cure = stats.observed_cure(FIX_WINDOW_DAYS)
        if cure is None:
            raise ThinLedger(
                "no judgable fix rows to measure a cure rate from — the ledger "
                "refuses to invent one. Fix something, watch it for %d days, "
                "or pass --cure explicitly." % FIX_WINDOW_DAYS)
        source = "measured from this ledger's fix reviews (median reduction)"

    avg_min = sum(r["minutes"] for r in found) / float(len(found))
    rate_per_day = len(found) / float(REPEAT_WINDOW_DAYS)
    saved_min_yr = rate_per_day * cure * 365.0 * avg_min
    current_min_yr = rate_per_day * 365.0 * avg_min

    print("SIMULATE · 反事实 (exit 0 always; red lines live in `repeat`)")
    print("item: %s | window %d days: %d hunts, %.1f min avg"
          % (args.item, REPEAT_WINDOW_DAYS, len(found), avg_min))
    print("cure rate: %.0f%% (%s)" % (cure * 100.0, source))
    print("")
    print("as-is:    %.0f min/yr hunted for this item" % current_min_yr)
    print("fixed:    %.0f min/yr (-%.0f min/yr)"
          % (current_min_yr - saved_min_yr, saved_min_yr))
    total_annual = stats.annual_minutes()
    print("ledger-wide annual hunt: %.0f min -> would drop to %.0f min"
          % (total_annual, total_annual - saved_min_yr))
    if wage is not None:
        print("at %.2f/h: saves %.2f/yr" % (wage, _money(wage, saved_min_yr)))
    else:
        print("NOTE unpriced: add --wage to translate minutes into money.")
    print("")
    print("counterfactual replay — assigning the home is still your move.")
    return EXIT_OK


def cmd_validate(args):
    rows = parse_ledger(args.ledger)
    stats = Stats(rows)

    print("VALIDATE · 账本体检")
    print("rows: %d (%d search / %d buy / %d fix)"
          % (len(rows), len(stats.searches), len(stats.buys), len(stats.fixes)))
    print("coverage: %s -> %s (%d days)"
          % (stats.first, stats.last, stats.span_days))

    type_sum = len(stats.searches) + len(stats.buys) + len(stats.fixes)
    ok1 = type_sum == len(rows)
    print("identity rows: %d + %d + %d == %d  [%s]"
          % (len(stats.searches), len(stats.buys), len(stats.fixes),
             len(rows), "OK" if ok1 else "BROKEN"))

    per_item_minutes = 0
    for _item, (_count, mins, _places) in stats.per_item().items():
        per_item_minutes += mins
    ok2 = per_item_minutes == stats.total_minutes
    print("identity minutes: per-item sum %d == total %d  [%s]"
          % (per_item_minutes, stats.total_minutes, "OK" if ok2 else "BROKEN"))

    dup_dates = Counter(r["date"] for r in rows)
    busiest = dup_dates.most_common(1)
    if busiest and busiest[0][1] > 1:
        print("busiest day: %s x%d events (同日多事件合法，完全相同行已拒绝)"
              % (busiest[0][0], busiest[0][1]))

    suspects = []
    for row in rows:
        if row["event"] == "search" and row["place"] == "":
            suspects.append("line %d: search of '%s' never found (no place)"
                            % (row["line"], row["item"]))
    if suspects:
        print("")
        print("disclosures:")
        for line in suspects:
            print("  %s" % line)
    broken = not (ok1 and ok2)
    if broken:
        print("")
        print("LEDGER BROKEN: identities failed — fix before drawing conclusions.")
        return EXIT_DATA
    print("")
    print("ledger healthy.")
    return EXIT_OK


# ---------------------------------------------------------------- parser

def add_ledger_arg(parser):
    parser.add_argument("ledger", help="TSV ledger path")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="search_tax.py", description="search-tax · 寻物税",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=USAGE)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("report", help="annualized search tax, most hunted, places")
    add_ledger_arg(p)
    p.add_argument("--wage", type=float, metavar="W")
    p.add_argument("--salary", type=float, metavar="S")
    p.add_argument("--hours", type=float, metavar="H")
    p.add_argument("-n", "--top", type=int, default=5)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("repeat", help="repeat offenders within the window")
    add_ledger_arg(p)
    p.add_argument("--window", type=int, default=REPEAT_WINDOW_DAYS, metavar="DAYS")
    p.add_argument("--hits", type=int, default=REPEAT_HITS, metavar="N")
    p.set_defaults(func=cmd_repeat)

    p = sub.add_parser("dup", help="duplicate-buy audit against hunt history")
    add_ledger_arg(p)
    p.set_defaults(func=cmd_dup)

    p = sub.add_parser("place", help="fixed-home prescriptions and fix reviews")
    add_ledger_arg(p)
    p.add_argument("--days", type=int, default=FIX_WINDOW_DAYS, metavar="DAYS")
    p.set_defaults(func=cmd_place)

    p = sub.add_parser("simulate", help="counterfactual: fix an item's home")
    add_ledger_arg(p)
    p.add_argument("action", choices=["fix"])
    p.add_argument("--item", required=True)
    p.add_argument("--cure", type=float, metavar="F",
                   help="assumed hunt-avoidance rate; ledger-measured if omitted")
    p.add_argument("--wage", type=float, metavar="W")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("validate", help="ledger health check")
    add_ledger_arg(p)
    p.set_defaults(func=cmd_validate)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_DATA
    try:
        return args.func(args)
    except LedgerError as exc:
        sys.stderr.write("data error (exit 2): %s\n" % exc)
        return EXIT_DATA
    except ThinLedger as exc:
        sys.stderr.write("too thin to conclude (exit 3): %s\n" % exc)
        return EXIT_THIN


if __name__ == "__main__":
    sys.exit(main())
