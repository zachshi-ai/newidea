#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""filial-desk · 孝心工单 —— 给爸妈做数字支持的工单账本.

问题：你在异地，爸妈的手机坏了就打给你。每通「帮我看看手机」
10 到 40 分钟，修完就挂，没有任何账本。四本账从来没人记过：

  * 支持税   一年到底花了多少小时在当爸妈的免费 IT 部
  * 教会率   修好不是教会——上次教过的东西复发了吗？
  * 设备经济 哪台设备是无底洞：年支持时间 vs 设备残值
  * 教程债   复发两次以上的题材，写一次图文教程永久摊销

filial-desk 把每次求助记成一行工单（TSV 手编，一行一事件），
确定性开出六本账：

  report     总账：支持税年化、按人/设备/题材分解、教会率、复发率、
             夜间求助占比（clock 列可选）——算术照常出账，统计薄账拒判
  relapse    复发审计：同一 (人, 题材) 在 --window 天内再犯 = 复发链；
             上次标过 taught=yes 还复发 = TAUGHT-BUT-BACK（教学伪证）；
             复发率超线 / 伪证 ≥2 → exit 4
  fleet      设备经济：每台设备的票数、分钟、间隔中位；给了
             --hourly + --residual 才有钱账——年支持成本 > 残值 = SUNK
             exit 4（这台机器比你为它花的时间便宜）
  curriculum 教程债：题材级复发 ≥2 = 该写的图文教程；给了 --tutorials
             清单还盖不住 → 欠账 exit 4
  simulate   反事实：cure（教程治好某题材的全部复发）/ retire（换掉某台
             设备）重放账本——kept + removed == total 恒等式，恒 exit 0
  validate   体检：字段守卫、重复行、三重恒等式（按人/按设备/按题材
             分钟加总 == 总分钟）

诚实条款：taught 是自报声称，复发才是唯一审计证据——声称没机会被
检验的（--window 天内无后续）单列 OPEN，不冒充已教会；复发不是爸妈
笨，是上次教学的失败证据，责任在教的人；不给 --hourly 只报小时，
永不发明钱；账本自锚定——缺省 as-of = 账本末日，--as-of 可钉死，
同一本账任何机器任何一天跑出的结果逐字节一致；账本是你的运维台账，
不是爸妈的成绩单，它只拒绝「修好就算完」继续免费。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import OrderedDict
from datetime import date, timedelta

VERSION = "1.0.0"

COLUMNS = ("date", "parent", "device", "topic", "minutes",
           "mode", "taught", "clock", "note")
MODES = {"电话": "phone", "视频": "video", "远程": "remote", "现场": "onsite",
         "phone": "phone", "video": "video", "remote": "remote", "onsite": "onsite"}
TAUGHT_MAP = {"yes": "yes", "是": "yes", "y": "yes",
              "no": "no", "否": "no", "n": "no"}

RELAPSE_WINDOW_DAYS = 90  # a chain continues while gaps stay within this
RELAPSE_RATE_LINE = 0.5   # relapse rate above this -> exit 4
BACK_LINE = 2             # taught-but-back relapses at/above this -> exit 4
FREQ_LINE_DAYS = 21       # median gap below this -> HIGH-FREQ device
NIGHT_START = 22          # 22:00-07:59 counts as night
NIGHT_END = 8
ANNUAL_WEEKS = 52.0
MIN_EVENTS = 8            # refuse statistical verdicts below this
MIN_COVERAGE_DAYS = 90    # one relapse window of observation, at least
CURRICULUM_MIN_RELAPSES = 2  # topic-level relapses to become tutorial debt

EXIT_OK = 0
EXIT_DATA = 2
EXIT_THIN = 3
EXIT_RED = 4

USAGE = """usage: filial_desk.py <command> [args]

commands:
  report     <ledger.tsv> [--hourly W] [--as-of DATE]   the annualized tax
  relapse    <ledger.tsv> [--window D] [--rate-line F] [--back-line N]
  fleet      <ledger.tsv> [--hourly W] [--residual DEV:AMT]... [--freq-line D]
  curriculum <ledger.tsv> [--tutorials FILE]
  simulate   <ledger.tsv> cure --topic T | retire --device D  [--hourly W]
  validate   <ledger.tsv>

ledger columns (tab separated, one ticket per row):
  date  parent  device  topic  minutes  [mode  [taught  [clock  [note]]]]
  date    YYYY-MM-DD
  parent  妈 / 爸 / 岳母 ... (who called)
  device  iPhone 12 / 红米 9A ... (what broke)
  topic   WiFi 断网 / 手机弹广告 ... (normalized: case & punctuation folded)
  minutes minutes >= 1 the ticket cost you
  mode    电话|视频|远程|现场 (or phone|video|remote|onsite), optional
  taught  yes|是 = the ticket ended by TEACHING, not just fixing (self-
          claimed, audited by relapse); no|否; empty = unknown
  clock   HH:MM the call arrived, optional (feeds the night-call share)
  All windows anchor to the ledger itself — default as-of is the last
  ticket's date, no wall clock: the same ledger yields byte-identical
  reports on any machine, any day.
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


def topic_key(topic):
    """Normalized topic: lowercase, whitespace & punctuation folded away.

    'WiFi 断网' and 'wifi断网' are the same problem; the tutorial you
    write against one must cover the other.
    """
    return "".join(ch for ch in topic.strip().lower() if ch.isalnum())


def parse_clock(text, lineno):
    text = text.strip()
    if not text:
        return None
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not match:
        raise LedgerError("line %d: bad clock %r (want HH:MM)" % (lineno, text))
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise LedgerError("line %d: clock out of range: %s" % (lineno, text))
    return "%02d:%02d" % (hour, minute)


def parse_ledger(path):
    """Read the ticket ledger. Deterministic: sorted by (date, row#)."""
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
        if len(parts) < 5 or len(parts) > 9:
            raise LedgerError(
                "line %d: want 5-9 columns (date parent device topic minutes "
                "[mode taught clock note]), got %d" % (lineno, len(parts)))
        fields = [p.strip() for p in parts] + [""] * (9 - len(parts))
        date_s, parent, device, topic, minutes_s, mode_s, taught_s, clock_s, note = fields
        day = parse_date(date_s, "date (line %d)" % lineno)
        if not parent:
            raise LedgerError("line %d: parent must not be empty" % lineno)
        if not device:
            raise LedgerError("line %d: device must not be empty" % lineno)
        if not topic:
            raise LedgerError("line %d: topic must not be empty" % lineno)
        try:
            minutes = int(minutes_s)
        except ValueError:
            raise LedgerError("line %d: bad minutes %r (want integer >= 1)"
                              % (lineno, minutes_s))
        if minutes <= 0:
            raise LedgerError("line %d: minutes must be >= 1, got %d"
                              % (lineno, minutes))
        mode = ""
        if mode_s:
            mode = MODES.get(mode_s)
            if mode is None:
                raise LedgerError("line %d: mode must be one of %s, got %r"
                                  % (lineno, "/".join(MODES), mode_s))
        taught = "na"
        if taught_s:
            taught = TAUGHT_MAP.get(taught_s.lower() if taught_s.isascii() else taught_s)
            if taught is None:
                raise LedgerError("line %d: taught must be yes|是|no|否 or empty, got %r"
                                  % (lineno, taught_s))
        clock = parse_clock(clock_s, lineno)
        key = (day, parent, device, topic, minutes, mode, taught, clock, note)
        if key in seen:
            raise LedgerError("line %d: exact duplicate ticket %s" % (lineno, key))
        seen.add(key)
        rows.append(OrderedDict([
            ("date", day), ("parent", parent), ("device", device),
            ("topic", topic), ("tkey", topic_key(topic)), ("minutes", minutes),
            ("mode", mode), ("taught", taught), ("clock", clock),
            ("note", note), ("line", lineno),
        ]))
    if not header_seen:
        raise LedgerError("no header row starting with 'date' found")
    if not rows:
        raise LedgerError("ledger has no tickets")
    rows.sort(key=lambda r: (r["date"], r["line"]))
    return rows


def apply_as_of(rows, as_of):
    """The as-of cut: later tickets never happened (yet)."""
    return [r for r in rows if r["date"] <= as_of]


# ---------------------------------------------------------------- chains

def build_chains(rows, window_days):
    """(parent, tkey) -> list of chains; a chain continues while consecutive
    gaps stay <= window_days. Each ticket after the head is a relapse,
    classified by the PREVIOUS ticket's taught claim:
      taught=yes -> TAUGHT-BUT-BACK (教学伪证：声称教会了，账本说没有)
      otherwise  -> UNTAUGHT (预期复发，教程债的原料)
    """
    grouped = OrderedDict()
    for row in rows:
        grouped.setdefault((row["parent"], row["tkey"]), []).append(row)
    chains = []
    for _key, tickets in sorted(grouped.items()):
        chain = []
        for ticket in tickets:
            if chain and (ticket["date"] - chain[-1]["date"]).days <= window_days:
                chain.append(OrderedDict(ticket, relapse=True,
                                         back=chain[-1]["taught"] == "yes"))
            else:
                if chain:
                    chains.append(chain)
                chain = [OrderedDict(ticket, relapse=False, back=False)]
        if chain:
            chains.append(chain)
    return chains


def relapse_rows(chains):
    return [t for chain in chains for t in chain if t["relapse"]]


def falsified_claim_lines(chains):
    """Lines of tickets whose taught=yes claim a later relapse audited
    and broke. 1:1 with TAUGHT-BUT-BACK relapses, but the blame sits on
    the ticket that MADE the claim, not the one that broke it."""
    out = set()
    for chain in chains:
        for prev, ticket in zip(chain, chain[1:]):
            if ticket["relapse"] and ticket["back"]:
                out.add(prev["line"])
    return out


# ------------------------------------------------------------- hourly (honesty)

def resolve_hourly(args):
    """Hourly rate or None. Unpriced ledgers still get every minute."""
    hourly = getattr(args, "hourly", None)
    if hourly is not None and hourly <= 0:
        raise LedgerError("--hourly must be > 0, got %s" % hourly)
    return hourly


# ---------------------------------------------------------------- stats

class Stats(object):
    """Deterministic aggregates over the as-of cut of the ledger."""

    def __init__(self, rows):
        self.rows = rows
        self.first = rows[0]["date"]
        self.last = rows[-1]["date"]
        self.span_days = (self.last - self.first).days + 1
        first_monday = self.first - timedelta(days=self.first.weekday())
        last_sunday = self.last + timedelta(days=6 - self.last.weekday())
        self.weeks = ((last_sunday - first_monday).days + 1) / 7.0
        self.total_minutes = sum(r["minutes"] for r in rows)
        self.total_events = len(rows)

    def check_thin(self):
        if self.total_events < MIN_EVENTS:
            raise ThinLedger("only %d tickets (need >= %d) — start logging, "
                             "come back when the ledger has room to speak"
                             % (self.total_events, MIN_EVENTS))
        if self.span_days < MIN_COVERAGE_DAYS:
            raise ThinLedger("coverage %d days (need >= %d — one relapse "
                             "window of observation)"
                             % (self.span_days, MIN_COVERAGE_DAYS))

    def annual_minutes(self):
        return self.total_minutes / self.weeks * ANNUAL_WEEKS

    def per_parent(self):
        return self._per("parent")

    def per_device(self):
        return self._per("device")

    def per_topic(self):
        """tkey -> (count, minutes, display name of first occurrence)."""
        out = OrderedDict()
        for row in self.rows:
            count, mins, _display = out.get(row["tkey"], (0, 0, row["topic"]))
            out[row["tkey"]] = (count + 1, mins + row["minutes"], _display)
        return OrderedDict(sorted(out.items(), key=lambda kv: (-kv[1][1], kv[0])))

    def _per(self, key, label=None):
        out = OrderedDict()
        for row in self.rows:
            name = row[key]
            count, mins = out.get(name, (0, 0))
            out[name] = (count + 1, mins + row["minutes"])
        return OrderedDict(sorted(out.items(), key=lambda kv: (-kv[1][1], kv[0])))

    def taught_book(self, as_of, window_days, back_lines):
        """Account every taught=yes claim by what the ledger did with it:
        verified (old enough, never relapsed) / taught-but-back (audited
        and falsified) / open (too young to judge — a claim is not credit).
        """
        claimed = [r for r in self.rows if r["taught"] == "yes"]
        judged = [r for r in self.rows if r["taught"] in ("yes", "no")]
        verified = [r for r in claimed
                    if (as_of - r["date"]).days >= window_days
                    and r["line"] not in back_lines]
        open_claims = [r for r in claimed
                       if (as_of - r["date"]).days < window_days]
        return {
            "claimed": len(claimed),
            "judged": len(judged),
            "verified": len(verified),
            "open": open_claims,
            "rate": len(claimed) / float(len(judged)) if judged else None,
        }

    def night_book(self):
        """Share of night calls among tickets that recorded a clock."""
        timed = [r for r in self.rows if r["clock"]]
        if not timed:
            return {"covered": 0, "night": 0, "share": None}
        night = [r for r in timed
                 if int(r["clock"][:2]) >= NIGHT_START
                 or int(r["clock"][:2]) < NIGHT_END]
        return {"covered": len(timed), "night": len(night),
                "share": len(night) / float(len(timed))}

    def mode_book(self):
        counts = OrderedDict()
        for row in self.rows:
            if row["mode"]:
                counts[row["mode"]] = counts.get(row["mode"], 0) + 1
        return OrderedDict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def median(values):
    values = sorted(values)
    n = len(values)
    mid = n // 2
    if n % 2:
        return float(values[mid])
    return (values[mid - 1] + values[mid]) / 2.0


# ---------------------------------------------------------------- commands

def cmd_report(args):
    hourly = resolve_hourly(args)
    rows = parse_ledger(args.ledger)
    as_of = parse_date(args.as_of, "--as-of") if args.as_of else rows[-1]["date"]
    rows = apply_as_of(rows, as_of)
    if not rows:
        raise LedgerError("--as-of %s cuts away every ticket" % as_of)
    stats = Stats(rows)
    chains = build_chains(rows, args.window)
    relapses = relapse_rows(chains)
    backs = [r for r in relapses if r["back"]]
    taught_book = stats.taught_book(as_of, args.window,
                                    falsified_claim_lines(chains))
    night_book = stats.night_book()

    print("FILIAL DESK · 孝心工单 report")
    print("ledger: %s  tickets: %d  as-of: %s%s"
          % (os.path.basename(args.ledger), stats.total_events, as_of,
             "" if args.as_of else " (ledger end)"))
    print("coverage: %s -> %s  (%d days, %.1f ledger weeks)"
          % (stats.first, stats.last, stats.span_days, stats.weeks))
    print("")
    print("support time: %d min total | annualized %.0f min = %.1f h/yr"
          % (stats.total_minutes, stats.annual_minutes(),
             stats.annual_minutes() / 60.0))
    print("  ^ the support tax: %.1f hours a year spent being your "
          "parents' IT department" % (stats.annual_minutes() / 60.0))
    print("")
    print("by parent:")
    for parent, (count, mins) in stats.per_parent().items():
        print("  %-10s x%2d tickets  %4d min" % (parent, count, mins))
    print("by device:")
    for device, (count, mins) in stats.per_device().items():
        print("  %-14s x%2d tickets  %4d min" % (device, count, mins))
    print("most supported topics (by minutes):")
    for _tkey, (count, mins, display) in list(stats.per_topic().items())[: args.top]:
        print("  %-16s x%d tickets  %4d min" % (display, count, mins))
    print("")
    print("teaching: %d claimed / %d judged -> claimed-taught rate %s"
          % (taught_book["claimed"], taught_book["judged"],
             "%.1f%%" % (100.0 * taught_book["rate"]) if taught_book["rate"] is not None
             else "n/a"))
    print("  verified %d | open %d (no chance to relapse yet, claims not credit) "
          "| taught-but-back %d"
          % (taught_book["verified"], len(taught_book["open"]), len(backs)))
    print("relapse: %d of %d tickets were a relapse (%.1f%%)"
          % (len(relapses), stats.total_events,
             100.0 * len(relapses) / stats.total_events))
    if night_book["covered"]:
        print("rhythm: clock on %d tickets; night calls (%02d:00-%02d:00): "
              "%d (%.1f%% of timed)"
              % (night_book["covered"], NIGHT_START, NIGHT_END,
                 night_book["night"], 100.0 * night_book["share"]))
    modes = stats.mode_book()
    if modes:
        print("modes: " + "  ".join("%s x%d" % (m, c) for m, c in modes.items()))
    if hourly is not None:
        print("at %.2f/h: the support tax is %.2f/yr — an unpaid salary "
              "nobody budgeted" % (hourly,
                                   hourly * stats.annual_minutes() / 60.0))
    else:
        print("NOTE unpriced: minutes are the hard currency; add --hourly "
              "to translate the tax into money.")

    try:
        stats.check_thin()
    except ThinLedger as exc:
        print("")
        print("STATISTICS REFUSED (exit 3): %s" % exc)
        print("(the totals above are arithmetic facts; the annualized tax "
              "and rates need a fuller ledger)")
        raise
    return EXIT_OK


def cmd_relapse(args):
    rows = parse_ledger(args.ledger)
    as_of = rows[-1]["date"]
    rows = apply_as_of(rows, as_of)
    chains = build_chains(rows, args.window)
    relapses = relapse_rows(chains)
    backs = [r for r in relapses if r["back"]]

    print("RELAPSE AUDIT · 复发审计 (window %d days, rolling chains)" % args.window)
    for chain in chains:
        rel = [t for t in chain if t["relapse"]]
        if not rel:
            continue
        parent, tkey = chain[0]["parent"], chain[0]["tkey"]
        print("")
        print("  %s / %s — %d ticket(s), %d relapse(s)"
              % (parent, chain[0]["topic"], len(chain), len(rel)))
        prev = None
        for ticket in chain:
            if ticket["relapse"]:
                kind = ("TAUGHT-BUT-BACK" if ticket["back"] else "UNTAUGHT")
                gap = (ticket["date"] - prev["date"]).days
                if ticket["back"]:
                    verdict = ("the taught=yes claim on %s did not hold"
                               % prev["date"])
                else:
                    verdict = ("previous ticket (%s) ended fixed, not taught"
                               % prev["date"])
                print("    %s  relapse (%s, +%dd)  %s"
                      % (ticket["date"], kind, gap, verdict))
            else:
                print("    %s  ticket  %3d min  taught=%s"
                      % (ticket["date"], ticket["minutes"], ticket["taught"]))
            prev = ticket
    if not relapses:
        print("  no (parent, topic) pair relapsed within %d days" % args.window)

    print("")
    print("relapse rate: %d of %d tickets (%.1f%%); taught-but-back %d"
          % (len(relapses), len(rows), 100.0 * len(relapses) / len(rows)
             if rows else 0.0, len(backs)))

    stats = Stats(rows)
    try:
        stats.check_thin()
    except ThinLedger as exc:
        print("")
        print("VERDICT REFUSED (exit 3): %s" % exc)
        print("(chains above are ledger facts; the rate verdict needs a "
              "fuller ledger)")
        raise

    if len(backs) >= args.back_line:
        print("")
        print("RED LINE: %d taught-but-back relapses (line %d). A 'yes' on a "
              "ticket is a claim; the ledger just audited it. Re-teach, or "
              "write the tutorial." % (len(backs), args.back_line))
        return EXIT_RED
    if len(relapses) / float(len(rows)) > args.rate_line:
        print("")
        print("RED LINE: relapse rate %.1f%% is over the %.0f%% line. Fixing "
              "is pain relief; teaching is the cure — and the cure is not "
              "being delivered." % (100.0 * len(relapses) / len(rows),
                                    100.0 * args.rate_line))
        return EXIT_RED
    print("")
    print("verdict: under both lines — but every UNTAUGHT relapse above is "
          "tutorial debt taking interest (`curriculum`).")
    return EXIT_OK


def cmd_fleet(args):
    hourly = resolve_hourly(args)
    rows = parse_ledger(args.ledger)
    as_of = rows[-1]["date"]
    rows = apply_as_of(rows, as_of)
    stats = Stats(rows)
    try:
        stats.check_thin()
        thin = None
    except ThinLedger as exc:
        thin = str(exc)

    residuals = OrderedDict()
    for chunk in args.residual or []:
        if ":" not in chunk:
            raise LedgerError("--residual wants DEV:AMT, got %r" % chunk)
        dev, _, amount = chunk.partition(":")
        try:
            value = float(amount)
        except ValueError:
            raise LedgerError("--residual amount must be a number, got %r" % amount)
        if value < 0:
            raise LedgerError("--residual amount must be >= 0")
        residuals[dev.strip()] = value

    print("FLEET · 设备经济 (annualized over %d ledger weeks)"
          % stats.weeks)
    print("")
    print("  %-14s %6s %7s %11s %7s  %s"
          % ("device", "ticks", "min", "median-gap", "h/yr", "verdict"))
    sunk = []
    hot = []
    per_device = stats.per_device()
    device_rows = OrderedDict()
    for row in rows:
        device_rows.setdefault(row["device"], []).append(row)
    for device, (count, mins) in per_device.items():
        tickets = device_rows[device]
        if len(tickets) >= 2:
            gaps = [(b["date"] - a["date"]).days
                    for a, b in zip(tickets, tickets[1:])]
            gap = median(gaps)
            gap_text = "%.1fd" % gap
        else:
            gap, gap_text = None, "-"
        annual_min = mins / stats.weeks * ANNUAL_WEEKS
        if thin:
            annual_text = "refused"
            verdict = "annualization refused (thin ledger)"
        else:
            annual_text = "%.1f" % (annual_min / 60.0)
            if gap is not None and gap < args.freq_line:
                verdict = "HIGH-FREQ (median gap < %dd)" % args.freq_line
                hot.append(device)
            elif device in residuals and hourly is not None:
                cost = hourly * annual_min / 60.0
                verdict = "annual support %.2f vs residual %.0f" % (cost, residuals[device])
                if cost > residuals[device]:
                    verdict += " -> SUNK"
                    sunk.append((device, cost, residuals[device]))
            elif device in residuals:
                verdict = "residual on file, add --hourly to price the hours"
            else:
                verdict = "no residual on file (hours only)"
        print("  %-14s x%-4d %7d %11s %7s  %s"
              % (device, count, mins, gap_text, annual_text, verdict))
    print("")
    if thin:
        print("VERDICT REFUSED (exit 3): %s" % thin)
        raise ThinLedger(thin)
    if sunk:
        device, cost, residual = sunk[0]
        print("RED LINE: SUNK — %s costs %.2f/yr in your hours against a "
              "residual of %.0f. The phone is cheaper than the time you "
              "spend on it; replacing it is not extravagance, it is "
              "amortization." % (device, cost, residual))
        return EXIT_RED
    if hot:
        print("RED LINE: HIGH-FREQ — %s breaks faster than every %d days. "
              "A device on this cadence is not having incidents, it is "
              "having a schedule." % ("/".join(hot), args.freq_line))
        return EXIT_RED
    print("fleet verdict: every device is cheaper than the hours it "
          "costs — for now.")
    return EXIT_OK


def cmd_curriculum(args):
    rows = parse_ledger(args.ledger)
    as_of = rows[-1]["date"]
    rows = apply_as_of(rows, as_of)
    chains = build_chains(rows, args.window)

    topic_relapses = OrderedDict()
    topic_info = {}
    for chain in chains:
        rel = [t for t in chain if t["relapse"]]
        tkey = chain[0]["tkey"]
        chain_last = max(t["date"] for t in chain)
        count, last = topic_relapses.get(tkey, (0, None))
        topic_relapses[tkey] = (count + len(rel),
                                chain_last if last is None else max(last, chain_last))
        topic_info.setdefault(tkey, chain[0]["topic"])

    covered = set()
    if args.tutorials:
        try:
            with open(args.tutorials, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError as exc:
            raise LedgerError("cannot read tutorials: %s" % exc)
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                covered.add(topic_key(line))

    print("CURRICULUM · 教程债 (a topic becomes debt at %d topic-level "
          "relapses; a tutorial amortizes forever)" % CURRICULUM_MIN_RELAPSES)
    print("")
    candidates = []
    watchers = []
    for tkey, (count, last) in sorted(topic_relapses.items(),
                                      key=lambda kv: (-kv[1][0], kv[0])):
        if count == 0:
            continue
        name = topic_info[tkey]
        if count >= CURRICULUM_MIN_RELAPSES:
            status = ("covered by your tutorials" if tkey in covered
                      else "UNCOVERED DEBT")
            candidates.append((tkey, name, count, status))
            print("  %-16s x%d relapse(s), last %s  ->  %s"
                  % (name, count, last, status))
        else:
            watchers.append((name, count))
            print("  %-16s x%d relapse(s), last %s  ->  watch "
                  "(one relapse may be luck; two is a pattern)"
                  % (name, count, last))
    if not candidates and not watchers:
        print("  no topic ever relapsed — either you teach well or the "
          "ledger is young (`relapse` to check).")
    if args.tutorials and covered:
        print("")
        print("tutorial file: %d entries loaded" % len(covered))
    if candidates and not args.tutorials:
        print("")
        print("write the %d tutorial(s) above; pass --tutorials FILE (one "
              "topic per line) to audit coverage." % len(candidates))

    uncovered = [c for c in candidates if c[3] == "UNCOVERED DEBT"]
    if args.tutorials and uncovered:
        print("")
        print("RED LINE: %d uncovered tutorial debt(s): %s. Each relapse is "
              "a rerun you are paying for by hand; write it once."
              % (len(uncovered), ", ".join(c[1] for c in uncovered)))
        return EXIT_RED
    return EXIT_OK


def cmd_simulate(args):
    hourly = resolve_hourly(args)
    rows = parse_ledger(args.ledger)
    as_of = rows[-1]["date"]
    rows = apply_as_of(rows, as_of)
    chains = build_chains(rows, args.window)

    if args.action == "cure":
        tkey = topic_key(args.topic)
        chains_of_topic = [chain for chain in chains if chain[0]["tkey"] == tkey]
        if not chains_of_topic:
            raise LedgerError("topic %r has no tickets in the ledger" % args.topic)
        removed_lines = {t["line"] for chain in chains_of_topic
                         for t in chain if t["relapse"]}
        label = "cure '%s': every relapse this topic ever caused is healed" % args.topic
    else:  # retire
        if not any(r["device"] == args.device for r in rows):
            raise LedgerError("device %r has no tickets in the ledger" % args.device)
        removed_lines = {r["line"] for r in rows if r["device"] == args.device}
        label = "retire '%s': the device (and every ticket it caused) is gone" % args.device

    removed = [r for r in rows if r["line"] in removed_lines]
    kept = [r for r in rows if r["line"] not in removed_lines]
    # identity: kept + removed == total, pinned
    assert len(kept) + len(removed) == len(rows)
    kept_minutes = sum(r["minutes"] for r in kept)
    removed_minutes = sum(r["minutes"] for r in removed)
    assert kept_minutes + removed_minutes == sum(r["minutes"] for r in rows)

    kept_chains = build_chains(kept, args.window)
    kept_relapses = relapse_rows(kept_chains)
    before_rate = 100.0 * len(relapse_rows(chains)) / len(rows)
    after_rate = (100.0 * len(kept_relapses) / len(kept)) if kept else 0.0

    stats = Stats(rows)
    before_annual = stats.annual_minutes()
    after_annual = kept_minutes / stats.weeks * ANNUAL_WEEKS

    print("SIMULATE · 反事实 (exit 0 always; red lines live in "
          "relapse/fleet)")
    print(label)
    print("tickets: %d -> %d (removed %d, %d min)"
          % (len(rows), len(kept), len(removed), removed_minutes))
    print("support tax: %.0f min/yr -> %.0f min/yr (-%.0f min = -%.1f h)"
          % (before_annual, after_annual, before_annual - after_annual,
             (before_annual - after_annual) / 60.0))
    print("relapse rate: %.1f%% -> %.1f%%" % (before_rate, after_rate))
    if hourly is not None:
        print("at %.2f/h: saves %.2f/yr"
              % (hourly, hourly * (before_annual - after_annual) / 60.0))
    else:
        print("NOTE unpriced: add --hourly to translate minutes into money.")
    print("")
    print("counterfactual replay — the tutorial/retirement is still your "
          "move. (`cure` removes relapses only; the head ticket remains — "
          "teaching once is assumed to take.)")
    return EXIT_OK


def cmd_validate(args):
    rows = parse_ledger(args.ledger)
    stats = Stats(rows)

    print("VALIDATE · 账本体检")
    print("tickets: %d" % len(rows))
    print("coverage: %s -> %s (%d days)"
          % (stats.first, stats.last, stats.span_days))

    total = stats.total_minutes
    per_parent = sum(mins for _c, mins in stats.per_parent().values())
    per_device = sum(mins for _c, mins in stats.per_device().values())
    per_topic = sum(mins for _c, mins, _d in stats.per_topic().values())
    ok = (per_parent == total and per_device == total and per_topic == total)
    print("identity minutes: parent %d | device %d | topic %d == total %d  [%s]"
          % (per_parent, per_device, per_topic, total, "OK" if ok else "BROKEN"))

    taught_na = [r for r in rows if r["taught"] == "na"]
    clocked = [r for r in rows if r["clock"]]
    print("disclosures: taught unrecorded on %d ticket(s); clock recorded "
          "on %d of %d" % (len(taught_na), len(clocked), len(rows)))
    dup_days = OrderedDict()
    for row in rows:
        dup_days[row["date"]] = dup_days.get(row["date"], 0) + 1
    busiest = max(dup_days.items(), key=lambda kv: kv[1])
    if busiest[1] > 1:
        print("busiest day: %s x%d tickets (同日多工单合法，完全相同行已拒绝)"
              % (busiest[0], busiest[1]))

    if not ok:
        print("")
        print("LEDGER BROKEN: identities failed — fix before drawing "
              "conclusions.")
        return EXIT_DATA
    print("")
    print("ledger healthy.")
    return EXIT_OK


# ---------------------------------------------------------------- parser

def add_ledger_arg(parser):
    parser.add_argument("ledger", help="TSV ledger path")


def add_window_arg(parser):
    parser.add_argument("--window", type=int, default=RELAPSE_WINDOW_DAYS,
                        metavar="DAYS")
    parser.add_argument("--rate-line", type=float, default=RELAPSE_RATE_LINE,
                        metavar="F")
    parser.add_argument("--back-line", type=int, default=BACK_LINE, metavar="N")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="filial_desk.py", description="filial-desk · 孝心工单",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=USAGE)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("report", help="annualized support tax, decompositions, teaching")
    add_ledger_arg(p)
    p.add_argument("--hourly", type=float, metavar="W")
    p.add_argument("--as-of", metavar="DATE")
    add_window_arg(p)
    p.add_argument("-n", "--top", type=int, default=5)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("relapse", help="relapse chains and the teaching audit")
    add_ledger_arg(p)
    add_window_arg(p)
    p.set_defaults(func=cmd_relapse)

    p = sub.add_parser("fleet", help="per-device economics")
    add_ledger_arg(p)
    p.add_argument("--hourly", type=float, metavar="W")
    p.add_argument("--residual", action="append", metavar="DEV:AMT")
    p.add_argument("--freq-line", type=int, default=FREQ_LINE_DAYS, metavar="DAYS")
    p.set_defaults(func=cmd_fleet)

    p = sub.add_parser("curriculum", help="tutorial debt backlog")
    add_ledger_arg(p)
    add_window_arg(p)
    p.add_argument("--tutorials", metavar="FILE")
    p.set_defaults(func=cmd_curriculum)

    p = sub.add_parser("simulate", help="counterfactual replay")
    add_ledger_arg(p)
    p.add_argument("action", choices=["cure", "retire"])
    p.add_argument("--topic")
    p.add_argument("--device")
    p.add_argument("--hourly", type=float, metavar="W")
    p.add_argument("--window", type=int, default=RELAPSE_WINDOW_DAYS, metavar="DAYS")
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
    if args.command == "simulate":
        if args.action == "cure" and not args.topic:
            parser.error("simulate cure needs --topic")
        if args.action == "retire" and not args.device:
            parser.error("simulate retire needs --device")
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
