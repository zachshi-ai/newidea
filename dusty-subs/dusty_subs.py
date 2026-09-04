#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dusty-subs — 吃灰订阅 / Dusty Subs

A subscription bills you by the month; your life happens by the use. The
30-yuan membership feels free right up until you divide one year of charges
by the four times you actually opened the app. The subscription industry
optimizes for you forgetting; the counter-weapon is a ledger.

dusty-subs rebuilds that ledger from a plain bank-statement CSV:

  * scan     — find the periodic debits hiding among one-off purchases
               (merchant normalization, interval regularity, amount
               consistency) and annualize each one
  * report   — the full picture: annualized ranking, the next-12-months
               payment calendar (how much of your future is already
               committed), price hikes, promo traps, and — given a small
               hand-kept usage file — cost per use with keep/watch/cut
               verdicts
  * explain  — one subscription's complete debit timeline plus its
               predicted future charges

Method in one line: group debits by normalized merchant name, keep the
groups whose gaps are regular (CV <= 0.35) and whose amounts are
consistent (>= 60% within +/-20% of the median), then translate the
median gap and last amount into an annualized price — the only price you
can compare against your life.

Nothing here touches the network or the wall clock: predictions are
anchored to the last date in the statement, so the same CSV always
yields the same report. Bank data is the most personal data there is;
the tool stays local on purpose.

Zero dependencies: Python 3.8+ standard library.
MIT License (c) 2026
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median, mean, pstdev
from typing import Dict, List, Optional, Tuple

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Detection parameters


DEFAULT_MIN_HITS = 3        # fewer charges than this: a one-off, not a sub
DEFAULT_GAP_CV = 0.35       # max coefficient of variation of the gaps
DEFAULT_GAP_OUTLIER = 2.05  # a gap over 2.05x the median breaks the cycle
                            # (one missed month survives; two do not)
DEFAULT_AMOUNT_TOL = 0.20   # price-consistency band: median +/- 20%
DEFAULT_AMOUNT_MIN = 0.60   # at least 60% of hits inside the band
DEFAULT_MPU = 15.0          # max price per use: above 3x this is dust
DEFAULT_HORIZON = 365       # days of future charges to project
HIKE_RATIO = 1.10           # last charge >= median(previous) * 1.10
DROP_RATIO = 0.90           # last charge <= median(previous) * 0.90
PROMO_RATIO = 0.80          # first charge <= 0.80 * median(rest): trial price

# cycle buckets by median gap, in days
CYCLE_BUCKETS: Tuple[Tuple[int, int, str], ...] = (
    (5, 10, "weekly"),
    (25, 35, "monthly"),
    (70, 110, "quarterly"),
    (300, 400, "annual"),
)

DEBIT_WORDS = ("支出", "支付", "消费", "转出", "借记", "debit", "expense", "dr")

DATE_COLS = ("date", "日期", "交易日期", "交易时间", "时间")
DESC_COLS = ("description", "desc", "摘要", "描述", "商户", "商户名",
             "交易对方", "备注")
AMT_COLS = ("amount", "金额", "交易金额", "扣款金额")
TYPE_COLS = ("type", "类型", "收支", "收支类型", "记账方向", "方向", "收/支")
USAGE_NAME_COLS = ("merchant", "商户", "商户名", "name")
USAGE_USES_COLS = ("uses_per_year", "年使用次数", "uses", "使用次数", "次数")

VERDICT_TAGS = {
    "keep": "OK keep",
    "watch": "~ watch",
    "cut": "!! CUT",
}


class StatementError(Exception):
    """Unreadable or unparseable statement (CLI maps this to exit 3)."""


# ---------------------------------------------------------------------------
# Small pure helpers


def fmt_money(x: float) -> str:
    """1234.0 -> '1,234'; 73.25 -> '73.25'. No currency symbol: statements
    speak every currency and the tool stays agnostic."""
    if abs(x - round(x)) < 0.005:
        return "{:,}".format(int(round(x)))
    return "{:,.2f}".format(x)


def fmt_pct(x: float) -> str:
    return "%+.0f%%" % (100.0 * x)


def parse_date(s: str) -> Optional[str]:
    """Accept ISO, slashed, dotted and compact dates; return ISO or None."""
    t = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return date(*[int(p) for p in
                          _strptime_parts(t, fmt)]).isoformat()
        except ValueError:
            continue
    return None


def _strptime_parts(t: str, fmt: str) -> List[int]:
    if fmt == "%Y%m%d":
        if not re.fullmatch(r"\d{8}", t):
            raise ValueError(t)
        return [int(t[:4]), int(t[4:6]), int(t[6:8])]
    parts = re.split(r"[-./]", t)
    if len(parts) != 3:
        raise ValueError(t)
    return [int(p) for p in parts]


def parse_amount(s: str) -> Optional[float]:
    """'¥1,234.50' -> 1234.5; 'n/a' -> None."""
    t = s.strip().lstrip("¥$€£￥").replace(",", "").replace(" ", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def normalize(desc: str) -> str:
    """The merchant key behind a raw descriptor.

    Lowercase; drop digit runs of 2+ (order ids, phone numbers, card
    tails, '12月' month stamps); punctuation to spaces; collapse. 'NETFLIX.COM
    866-579-7172' and 'netflix.com 4029357733' land on the same key.
    """
    t = desc.strip().lower()
    t = re.sub(r"\d{2,}", " ", t)
    t = t.replace("*", " ")
    t = re.sub(r"[^\w\s]+", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def add_months(day: date, n: int) -> date:
    y = day.year + (day.month - 1 + n) // 12
    m = (day.month - 1 + n) % 12 + 1
    return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def next_charge_day(day: date, gap: int) -> date:
    """One step forward. Month-like gaps step month-wise so the 3rd of the
    month stays the 3rd; anything else just adds the median gap in days."""
    if 25 <= gap <= 35:
        return add_months(day, 1)
    if 70 <= gap <= 110:
        return add_months(day, 3)
    if 300 <= gap <= 400:
        return add_months(day, 12)
    return day + timedelta(days=gap)


def cycle_label(gap: float) -> str:
    for lo, hi, name in CYCLE_BUCKETS:
        if lo <= gap <= hi:
            return name
    return "%dd" % round(gap)


def gap_cv(gaps: List[int]) -> float:
    m = mean(gaps)
    if m == 0:
        return float("inf")
    return pstdev(gaps) / m


def price_moves(amounts: List[float]) -> Dict[str, tuple]:
    """Flags readable off the amount history, in charge order."""
    flags: Dict[str, tuple] = {}
    if len(amounts) >= 2:
        prev = amounts[:-1]
        m = median(prev)
        if amounts[-1] >= m * HIKE_RATIO:
            flags["hike"] = ((amounts[-1] - m) / m, amounts[-1], m)
        elif amounts[-1] <= m * DROP_RATIO:
            flags["drop"] = ((m - amounts[-1]) / m, amounts[-1], m)
        rest = amounts[1:]
        m2 = median(rest)
        if amounts[0] <= PROMO_RATIO * m2:
            flags["promo"] = (amounts[0], m2)
    return flags


# ---------------------------------------------------------------------------
# Statement parsing


@dataclass
class Debit:
    day: str            # ISO date
    desc: str           # original description
    amount: float       # positive number


@dataclass
class Statement:
    path: str
    rows: int
    debits: List[Debit] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def first_day(self) -> Optional[str]:
        return self.debits[0].day if self.debits else None

    @property
    def last_day(self) -> Optional[str]:
        return self.debits[-1].day if self.debits else None


def _col(header: List[str], names: Tuple[str, ...]) -> int:
    for i, h in enumerate(header):
        if h.strip().lower() in names:
            return i
    return -1


def read_statement(path: str) -> Statement:
    if not os.path.exists(path):
        raise StatementError("no such file: %s" % path)
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    if not lines:
        raise StatementError("empty file: %s" % path)

    first = lines[0]
    delim = max((",", "\t", ";"), key=first.count)
    rows = list(csv.reader(lines, delimiter=delim))
    header = [h.strip().lower() for h in rows[0]]
    i_day, i_desc = _col(header, DATE_COLS), _col(header, DESC_COLS)
    i_amt, i_type = _col(header, AMT_COLS), _col(header, TYPE_COLS)
    missing = [n for n, i in (("date", i_day), ("description", i_desc),
                              ("amount", i_amt)) if i < 0]
    if missing:
        raise StatementError(
            "cannot find %s column(s) in %s (header: %s)"
            % ("/".join(missing), os.path.basename(path), ",".join(header)))

    typed = i_type >= 0
    body = rows[1:]
    parsed: List[Tuple[str, str, float]] = []
    bad = 0
    for row in body:
        if len(row) <= max(i_day, i_desc, i_amt, typed and i_type or 0):
            bad += 1
            continue
        day = parse_date(row[i_day])
        amount = parse_amount(row[i_amt])
        if day is None or amount is None:
            bad += 1
            continue
        if typed:
            t = row[i_type].strip().lower()
            if not (t.startswith("支") or t in DEBIT_WORDS):
                continue          # income, refunds: not subscription land
        parsed.append((day, row[i_desc].strip(), amount))

    notes: List[str] = []
    if not typed:
        if any(a < 0 for _, _, a in parsed):
            debits3 = [(d, s, -a) for d, s, a in parsed if a < 0]
            notes.append("negative amounts treated as debits; credits skipped")
        else:
            debits3 = parsed
            notes.append("no type column and no negative amounts: every row "
                         "assumed to be a debit")
    else:
        debits3 = parsed
    if bad:
        notes.append("%d malformed row(s) skipped" % bad)

    debits3.sort(key=lambda t: (t[0], t[1], t[2]))
    seen = set()
    debits: List[Debit] = []
    dups = 0
    for day, desc, amount in debits3:
        sig = (day, desc, amount)
        if sig in seen:
            dups += 1
            continue
        seen.add(sig)
        debits.append(Debit(day=day, desc=desc, amount=amount))
    if dups:
        notes.append("%d duplicate row(s) dropped" % dups)
    return Statement(path=path, rows=len(body), debits=debits, notes=notes)


# ---------------------------------------------------------------------------
# Detection


@dataclass
class Sub:
    """One evaluated merchant group."""
    key: str
    label: str                      # most common raw descriptor
    debits: List[Debit]

    @property
    def days(self) -> List[str]:
        return [d.day for d in self.debits]

    @property
    def amounts(self) -> List[float]:
        return [d.amount for d in self.debits]

    @property
    def gaps(self) -> List[int]:
        """Gaps between distinct charge days (same-day repeats don't bend
        the interval)."""
        uniq = sorted(set(self.days))
        return [(date.fromisoformat(b) - date.fromisoformat(a)).days
                for a, b in zip(uniq, uniq[1:])]

    @property
    def median_gap(self) -> float:
        return float(median(self.gaps)) if self.gaps else 0.0

    @property
    def median_amount(self) -> float:
        return float(median(self.amounts))

    @property
    def last_amount(self) -> float:
        return self.amounts[-1]

    @property
    def cycle(self) -> str:
        return cycle_label(self.median_gap)

    @property
    def annualized(self) -> float:
        gap = self.median_gap
        return self.last_amount * 365.0 / gap if gap > 0 else self.last_amount

    @property
    def flags(self) -> Dict[str, tuple]:
        return price_moves(self.amounts)

    @property
    def span_days(self) -> int:
        uniq = sorted(set(self.days))
        return (date.fromisoformat(uniq[-1])
                - date.fromisoformat(uniq[0])).days

    def predict(self, horizon_end: date) -> List[Tuple[str, float]]:
        """Future charges, anchored to the last real debit — never to the
        wall clock, so a statement always predicts the same future."""
        out: List[Tuple[str, float]] = []
        cur = date.fromisoformat(self.days[-1])
        while True:
            nxt = next_charge_day(cur, round(self.median_gap))
            if nxt > horizon_end:
                return out
            out.append((nxt.isoformat(), self.last_amount))
            cur = nxt


@dataclass
class Reject:
    key: str
    label: str
    hits: int
    median_gap: float
    reason: str


def evaluate_group(key: str, label: str, debits: List[Debit],
                   min_hits: int, gap_cv_max: float, amount_tol: float,
                   amount_min: float,
                   gap_outlier: float = DEFAULT_GAP_OUTLIER
                   ) -> Tuple[Optional[Sub], Optional[Reject]]:
    if len(debits) < min_hits:
        return None, None          # a one-off: below the ledger's radar
    sub = Sub(key=key, label=label, debits=debits)
    gaps = sub.gaps
    if len(gaps) < 2:
        return None, Reject(key, label, len(debits), 0.0,
                            "all charges on fewer than 3 distinct days")
    med_gap = sub.median_gap
    worst = max(gaps)
    if med_gap > 0 and worst > gap_outlier * med_gap:
        return None, Reject(key, label, len(debits), med_gap,
                            "gap %dd is a %.1fx outlier against median %dd"
                            % (worst, worst / med_gap, round(med_gap)))
    cv = gap_cv(gaps)
    if cv > gap_cv_max:
        return None, Reject(key, label, len(debits), med_gap,
                            "gaps too jittery (cv %.2f > %.2f)"
                            % (cv, gap_cv_max))
    amounts = sub.amounts
    med = median(amounts)
    in_band = sum(1 for a in amounts if abs(a - med) <= amount_tol * med)
    ratio = in_band / len(amounts)
    if ratio < amount_min:
        return None, Reject(key, label, len(debits), sub.median_gap,
                            "amounts too scattered (%d%% within +/-%d%% of "
                            "%s)" % (round(100 * ratio),
                                     round(100 * amount_tol),
                                     fmt_money(med)))
    return sub, None


def analyze(stmt: Statement, min_hits: int = DEFAULT_MIN_HITS,
            gap_cv_max: float = DEFAULT_GAP_CV,
            amount_tol: float = DEFAULT_AMOUNT_TOL,
            amount_min: float = DEFAULT_AMOUNT_MIN,
            ignore: Optional[List[str]] = None,
            horizon: int = DEFAULT_HORIZON,
            gap_outlier: float = DEFAULT_GAP_OUTLIER) -> dict:
    """Group, evaluate and project. Returns the full analysis dict."""
    groups: "OrderedDict[str, List[Debit]]" = OrderedDict()
    labels: Dict[str, Counter] = {}
    for d in stmt.debits:
        key = normalize(d.desc)
        groups.setdefault(key, []).append(d)
        labels.setdefault(key, Counter())[d.desc] += 1

    ignore = ignore or []
    subs: List[Sub] = []
    rejects: List[Reject] = []
    ignored: List[str] = []
    singles = 0
    for key, debits in groups.items():
        if any(re.search(rx, key) for rx in ignore):
            ignored.append(key)
            continue
        # stable sort: ties keep first-seen order, so the label is the
        # descriptor the statement used most (and earliest)
        label = sorted(labels[key].items(), key=lambda kv: -kv[1])[0][0]
        sub, rej = evaluate_group(key, label, debits, min_hits,
                                  gap_cv_max, amount_tol, amount_min,
                                  gap_outlier)
        if sub is not None:
            subs.append(sub)
        elif rej is not None:
            rejects.append(rej)
        else:
            singles += 1

    subs.sort(key=lambda s: (-s.annualized, s.key))
    rejects.sort(key=lambda r: (-r.hits, r.key))

    last_day = date.fromisoformat(stmt.last_day) if stmt.last_day \
        else date(1970, 1, 1)
    horizon_end = last_day + timedelta(days=horizon)

    subs_json = []
    for s in subs:
        predicted = s.predict(horizon_end)
        fl = s.flags
        subs_json.append({
            "merchant": s.key,
            "label": s.label,
            "hits": len(s.debits),
            "cycle": cycle_label(s.median_gap),
            "median_gap": round(s.median_gap, 2),
            "gap_cv": round(gap_cv(s.gaps), 3),
            "first": s.days[0],
            "last": s.days[-1],
            "median_amount": round(s.median_amount, 2),
            "last_amount": round(s.last_amount, 2),
            "annualized": round(s.annualized, 2),
            "locked_next_year": round(sum(a for _, a in predicted), 2),
            "predicted": [{"day": d, "amount": round(a, 2)}
                          for d, a in predicted],
            "flags": {
                "hike": ({"pct": round(fl["hike"][0], 4),
                          "last": round(fl["hike"][1], 2),
                          "was": round(fl["hike"][2], 2)}
                         if "hike" in fl else None),
                "drop": ({"pct": round(fl["drop"][0], 4),
                          "last": round(fl["drop"][1], 2),
                          "was": round(fl["drop"][2], 2)}
                         if "drop" in fl else None),
                "promo": ({"first": round(fl["promo"][0], 2),
                           "real": round(fl["promo"][1], 2)}
                          if "promo" in fl else None),
            },
        })

    by_month: "OrderedDict[str, List[float]]" = OrderedDict()
    for s in subs:
        for d, a in s.predict(horizon_end):
            by_month.setdefault(d[:7], []).append(a)
    calendar_rows = [{"month": m, "total": round(sum(amts), 2),
                      "charges": len(amts)}
                     for m, amts in sorted(by_month.items())]

    return {
        "statement": {
            "path": stmt.path,
            "rows": stmt.rows,
            "debits": len(stmt.debits),
            "merchants": len(groups),
            "window": {"first": stmt.first_day, "last": stmt.last_day},
            "horizon_end": horizon_end.isoformat(),
            "notes": stmt.notes,
        },
        "subscriptions": subs_json,
        "annualized_total": round(sum(s["annualized"] for s in subs_json), 2),
        "next_year_locked": round(sum(s["locked_next_year"]
                                      for s in subs_json), 2),
        "calendar": calendar_rows,
        "rejected": [{
            "merchant": r.key, "label": r.label, "hits": r.hits,
            "median_gap": round(r.median_gap, 2), "reason": r.reason,
        } for r in rejects],
        "ignored": sorted(ignored),
        "one_off_merchants": singles,
    }


# ---------------------------------------------------------------------------
# Usage & cost per use


@dataclass
class UsageRow:
    raw: str
    uses: float


def read_usage(path: str) -> List[UsageRow]:
    if not os.path.exists(path):
        raise StatementError("no such file: %s" % path)
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    if not lines:
        return []
    delim = max((",", "\t", ";"), key=lines[0].count)
    rows = list(csv.reader(lines, delimiter=delim))
    start = 0
    i_name, i_uses = 0, 1
    if len(rows[0]) >= 2 and parse_amount(rows[0][1]) is None:
        header = [h.strip().lower() for h in rows[0]]
        i_name = _col(header, USAGE_NAME_COLS)
        i_uses = _col(header, USAGE_USES_COLS)
        if i_name < 0 or i_uses < 0:
            raise StatementError(
                "usage file needs a merchant and a uses column (header: %s)"
                % ",".join(header))
        start = 1
    out = []
    for row in rows[start:]:
        if len(row) <= max(i_name, i_uses):
            continue
        uses = parse_amount(row[i_uses])
        if uses is None or not row[i_name].strip():
            continue
        out.append(UsageRow(raw=row[i_name].strip(), uses=uses))
    return out


def match_usage(name: str, keys: List[str]) -> Optional[str]:
    """Exact normalized match, else the unique substring match in either
    direction. Ambiguity refuses to guess."""
    want = normalize(name)
    if want in keys:
        return want
    hits = [k for k in keys if want in k or k in want]
    return hits[0] if len(hits) == 1 else None


def verdict_of(cost_per_use: Optional[float], mpu: float) -> str:
    if cost_per_use is None:
        return "unknown"
    if cost_per_use <= mpu:
        return "keep"
    if cost_per_use <= 3 * mpu:
        return "watch"
    return "cut"


def apply_usage(analysis: dict, usage: List[UsageRow],
                mpu: float) -> dict:
    """Join the hand-kept usage file onto the ledger and translate every
    subscription into the only price life actually pays: cost per use."""
    subs = analysis["subscriptions"]
    keys = [s["merchant"] for s in subs]
    verdicts, missing = [], []
    matched: Dict[str, float] = {}
    unmatched = []
    for row in usage:
        key = match_usage(row.raw, keys)
        if key is None:
            unmatched.append({"name": row.raw, "uses": row.uses})
        else:
            matched[key] = row.uses

    cut_refund = 0.0
    for s in subs:
        uses = matched.pop(s["merchant"], None)
        if uses is None:
            missing.append(s["merchant"])
            cpu = None
            verdict = "unknown"
        elif uses <= 0:
            cpu = None
            verdict = "cut"
        else:
            cpu = s["annualized"] / uses
            verdict = verdict_of(cpu, mpu)
        if verdict == "cut":
            cut_refund += s["annualized"]
        verdicts.append({
            "merchant": s["merchant"],
            "annualized": s["annualized"],
            "uses_per_year": uses,
            "cost_per_use": (round(cpu, 2) if cpu is not None else None),
            "verdict": verdict,
        })

    analysis["usage"] = {
        "mpu": mpu,
        "verdicts": verdicts,
        "missing": missing,
        "unmatched": unmatched,
        "cut_refund": round(cut_refund, 2),
    }
    return analysis


# ---------------------------------------------------------------------------
# Rendering


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


def _flag_tags(s: dict) -> List[str]:
    tags = []
    fl = s["flags"]
    if fl["hike"]:
        tags.append("hike %s (%s -> %s)" % (fmt_pct(fl["hike"]["pct"]),
                                            fmt_money(fl["hike"]["was"]),
                                            fmt_money(fl["hike"]["last"])))
    if fl["drop"]:
        tags.append("drop %s" % fmt_pct(-fl["drop"]["pct"]))
    if fl["promo"]:
        tags.append("promo %s first, real %s" % (fmt_money(fl["promo"]["first"]),
                                                 fmt_money(fl["promo"]["real"])))
    return tags


def render_head(analysis: dict, title: str) -> List[str]:
    st = analysis["statement"]
    lines = [
        "-- Dusty Subs %s: %s" % (title, os.path.basename(st["path"])),
        "  window                 : %s .. %s (%d rows, %d debits, %d merchants)"
        % (st["window"]["first"] or "-", st["window"]["last"] or "-",
           st["rows"], st["debits"], st["merchants"]),
        "  subscriptions found    : %d   annualized total : %s"
        % (len(analysis["subscriptions"]),
           fmt_money(analysis["annualized_total"])),
        "  next year already locked: %s (through %s)"
        % (fmt_money(analysis["next_year_locked"]), st["horizon_end"]),
    ]
    for note in st["notes"]:
        lines.append("  · %s" % note)
    for key in analysis["ignored"]:
        lines.append("  · ignored by --ignore: %s" % key)
    return lines


def render_scan(analysis: dict) -> str:
    lines = render_head(analysis, "scan")
    lines.append("")
    subs = analysis["subscriptions"]
    if subs:
        width = max([24] + [len(s["label"]) for s in subs])
        lines.append("  %-*s  %4s  %-10s  %8s  %10s  %s"
                     % (width, "merchant", "hits", "cycle", "last",
                        "annualized", "flags"))
        for s in subs:
            tags = _flag_tags(s) or ["-"]
            lines.append("  %-*s  %4d  %-10s  %8s  %10s  %s"
                         % (width, _clip(s["label"], width),
                            s["hits"], s["cycle"],
                            fmt_money(s["last_amount"]),
                            fmt_money(s["annualized"]),
                            " · ".join(tags)))
    else:
        lines.append("  (no periodic debits found — nothing to grade)")
    if analysis["rejected"]:
        lines.append("")
        lines.append("  periodic-looking, but failed the checks:")
        for r in analysis["rejected"]:
            lines.append("    %-26s  %2d hits ~every %dd · %s"
                         % (_clip(r["label"], 26), r["hits"],
                            round(r["median_gap"]), r["reason"]))
    lines.append("")
    return "\n".join(lines)


def render_report(analysis: dict) -> str:
    lines = render_head(analysis, "report")
    subs = analysis["subscriptions"]
    lines.append("")
    lines.append("  ledger (annualized, worst first):")
    if subs:
        width = max([24] + [len(s["label"]) for s in subs])
        lines.append("    %-*s  %4s  %-10s  %8s  %10s  %11s  %s"
                     % (width, "merchant", "hits", "cycle", "last",
                        "per-year", "locked-1yr", "flags"))
        for s in subs:
            tags = _flag_tags(s) or ["-"]
            lines.append("    %-*s  %4d  %-10s  %8s  %10s  %11s  %s"
                         % (width, _clip(s["label"], width), s["hits"],
                            s["cycle"], fmt_money(s["last_amount"]),
                            fmt_money(s["annualized"]),
                            fmt_money(s["locked_next_year"]),
                            " · ".join(tags)))
    lines.append("")
    lines.append("  next-12-months calendar (your future, already sold):")
    for row in analysis["calendar"]:
        lines.append("    %s    %10s   (%d charge(s))"
                     % (row["month"], fmt_money(row["total"]),
                        row["charges"]))
    if not analysis["calendar"]:
        lines.append("    (nothing projected)")
    lines.append("    %-11s %10s" % ("TOTAL", fmt_money(
        analysis["next_year_locked"])))

    moves = [s for s in subs if any(s["flags"][k] for k in s["flags"])]
    if moves:
        lines.append("")
        lines.append("  price moves worth a second look:")
        for s in moves:
            lines.append("    %-26s  %s" % (_clip(s["label"], 26),
                                            " · ".join(_flag_tags(s))))

    if analysis["rejected"]:
        lines.append("")
        lines.append("  periodic-looking, but failed the checks:")
        for r in analysis["rejected"]:
            lines.append("    %-26s  %2d hits ~every %dd · %s"
                         % (_clip(r["label"], 26), r["hits"],
                            round(r["median_gap"]), r["reason"]))

    usage = analysis.get("usage")
    if usage is not None:
        lines.append("")
        lines.append("  cost per use (annualized / uses-per-year, mpu %s;"
                     " >3x mpu is dust):" % fmt_money(usage["mpu"]))
        for v in usage["verdicts"]:
            if v["uses_per_year"] is not None and v["uses_per_year"] <= 0:
                cpu = "pure dust"
            elif v["cost_per_use"] is None:
                cpu = "n/a"
            else:
                cpu = "%s/use" % fmt_money(v["cost_per_use"])
            lines.append("    %s  %-14s %s"
                         % (VERDICT_TAGS[v["verdict"]], cpu,
                            _clip(v["merchant"], 30)))
        for key in usage["missing"]:
            lines.append("    ?? no usage data for %s — add it to the usage"
                         " file" % key)
        for row in usage["unmatched"]:
            lines.append("    ?? usage row matched nothing: %s (%s uses/yr)"
                         % (row["name"], fmt_money(row["uses"])))
        if usage["cut_refund"] > 0:
            lines.append("")
            lines.append("  cutting the dust refunds %s a year. The gym is"
                         " not judging; the ledger is."
                         % fmt_money(usage["cut_refund"]))
    lines.append("")
    return "\n".join(lines)


def render_explain(sub: dict, analysis: dict,
                   usage: Optional[List[UsageRow]] = None,
                   mpu: float = DEFAULT_MPU,
                   source: Optional[str] = None) -> str:
    """`source` is the path to re-read the raw timeline from; it defaults
    to the recorded statement path, which may be a bare basename when the
    analysis was relabelled for display."""
    lines = [
        "-- Dusty Subs explain: %s (%s)"
        % (sub["label"], os.path.basename(analysis["statement"]["path"])),
        "  key              : %s" % sub["merchant"],
        "  hits             : %d charges over %s .. %s"
        % (sub["hits"], sub["first"], sub["last"]),
        "  cycle            : %s (median gap %sd, spread cv %.2f)"
        % (sub["cycle"], sub["median_gap"], sub["gap_cv"]),
        "  amounts          : median %s · last %s"
        % (fmt_money(sub["median_amount"]), fmt_money(sub["last_amount"])),
        "  annualized       : %s · locked next year: %s"
        % (fmt_money(sub["annualized"]), fmt_money(sub["locked_next_year"])),
    ]
    tags = _flag_tags(sub)
    lines.append("  flags            : %s" % (" · ".join(tags) if tags
                                              else "none — steady as it goes"))
    if usage is not None:
        row = next((u for u in usage
                    if match_usage(u.raw, [sub["merchant"]]) is not None),
                   None)
        if row is None:
            lines.append("  usage            : not recorded — add it to the"
                         " usage file to price a use")
        elif row.uses <= 0:
            lines.append("  usage            : %s uses/yr -> pure dust"
                         % fmt_money(row.uses))
        else:
            cpu = sub["annualized"] / row.uses
            lines.append("  usage            : %s uses/yr -> %s per use (%s)"
                         % (fmt_money(row.uses), fmt_money(cpu),
                            verdict_of(cpu, mpu)))
    lines.append("")
    lines.append("  timeline:")
    timeline = []
    for d in _statement_debits(source or analysis["statement"]["path"],
                               sub["merchant"]):
        timeline.append("    %s  %s  %s" % (d.day, _clip(d.desc, 34),
                                            fmt_money(d.amount)))
    lines.extend(timeline if timeline else ["    (details unavailable)"])
    lines.append("")
    lines.append("  predicted (anchored to %s, no wall clock involved):"
                 % sub["last"])
    for row in sub["predicted"]:
        lines.append("    %s  %s" % (row["day"], fmt_money(row["amount"])))
    if not sub["predicted"]:
        lines.append("    (nothing inside the horizon)")
    lines.append("")
    return "\n".join(lines)


def _statement_debits(path: str, key: str) -> List[Debit]:
    """Re-read the statement for one merchant's raw timeline (explain only;
    cheap, local, and keeps the Debit records out of the analysis dict)."""
    try:
        stmt = read_statement(path)
    except StatementError:
        return []
    return [d for d in stmt.debits if normalize(d.desc) == key]


# ---------------------------------------------------------------------------
# CLI


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dusty_subs.py",
        description="Dusty Subs: the subscription ledger hiding in your"
                    " bank statement.",
    )
    sub = parser.add_subparsers(dest="cmd")

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--min-hits", type=int, default=DEFAULT_MIN_HITS,
                       help="charges before a merchant can be a sub"
                            " (default %d)" % DEFAULT_MIN_HITS)
        p.add_argument("--gap-cv", type=float, default=DEFAULT_GAP_CV,
                       help="max gap coefficient of variation"
                            " (default %s)" % DEFAULT_GAP_CV)
        p.add_argument("--gap-outlier", type=float,
                       default=DEFAULT_GAP_OUTLIER,
                       help="a gap beyond this multiple of the median gap"
                            " breaks the cycle (default %s)"
                            % DEFAULT_GAP_OUTLIER)
        p.add_argument("--amount-tol", type=float,
                       default=DEFAULT_AMOUNT_TOL,
                       help="price band around the median amount"
                            " (default %s)" % DEFAULT_AMOUNT_TOL)
        p.add_argument("--amount-min", type=float, default=DEFAULT_AMOUNT_MIN,
                       help="min share of charges inside the band"
                            " (default %s)" % DEFAULT_AMOUNT_MIN)
        p.add_argument("--horizon", type=int, default=DEFAULT_HORIZON,
                       help="days of future charges to project"
                            " (default %d)" % DEFAULT_HORIZON)
        p.add_argument("--ignore", action="append", default=[], metavar="RX",
                       help="skip merchants whose key matches this regex"
                            " (repeatable), e.g. --ignore 房租")
        p.add_argument("--format", choices=("text", "json"), default="text")

    p_scan = sub.add_parser("scan",
                            help="find the periodic debits and annualize")
    p_scan.add_argument("statement", help="bank statement CSV")
    _common(p_scan)

    p_report = sub.add_parser(
        "report", help="full report: ledger, calendar, moves, cost per use")
    p_report.add_argument("statement", help="bank statement CSV")
    p_report.add_argument("--usage", default=None,
                          help="usage CSV: merchant,uses_per_year")
    p_report.add_argument("--mpu", type=float, default=DEFAULT_MPU,
                          help="max price per use; dust is >3x this"
                               " (default %s)" % DEFAULT_MPU)
    p_report.add_argument("--fail-over", type=float, default=None,
                          metavar="AMOUNT",
                          help="exit 4 if next-year locked total > AMOUNT")
    _common(p_report)

    p_explain = sub.add_parser(
        "explain", help="one subscription's timeline and predicted future")
    p_explain.add_argument("merchant", help="merchant name (raw or key)")
    p_explain.add_argument("statement", help="bank statement CSV")
    p_explain.add_argument("--usage", default=None,
                           help="usage CSV: merchant,uses_per_year")
    p_explain.add_argument("--mpu", type=float, default=DEFAULT_MPU,
                           help="max price per use (default %s)" % DEFAULT_MPU)
    _common(p_explain)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_usage(sys.stderr)
        return 2
    try:
        stmt = read_statement(args.statement)
    except StatementError as exc:
        print("dusty-subs: %s" % exc, file=sys.stderr)
        return 3

    if args.cmd == "scan":
        analysis = analyze(stmt, min_hits=args.min_hits,
                           gap_cv_max=args.gap_cv, amount_tol=args.amount_tol,
                           amount_min=args.amount_min, ignore=args.ignore,
                           horizon=args.horizon,
                           gap_outlier=args.gap_outlier)
        if args.format == "json":
            print(json.dumps(analysis, indent=2, ensure_ascii=False))
        else:
            print(render_scan(analysis))
        return 0

    if args.cmd == "report":
        analysis = analyze(stmt, min_hits=args.min_hits,
                           gap_cv_max=args.gap_cv, amount_tol=args.amount_tol,
                           amount_min=args.amount_min, ignore=args.ignore,
                           horizon=args.horizon,
                           gap_outlier=args.gap_outlier)
        usage: Optional[List[UsageRow]] = None
        if args.usage:
            try:
                usage = read_usage(args.usage)
            except StatementError as exc:
                print("dusty-subs: %s" % exc, file=sys.stderr)
                return 3
            analysis = apply_usage(analysis, usage, args.mpu)
        if args.format == "json":
            print(json.dumps(analysis, indent=2, ensure_ascii=False))
        else:
            print(render_report(analysis))
        if args.fail_over is not None \
                and analysis["next_year_locked"] > args.fail_over:
            print("dusty-subs: next year is already committed to %s, over"
                  " your line of %s" % (fmt_money(analysis["next_year_locked"]),
                                        fmt_money(args.fail_over)),
                  file=sys.stderr)
            return 4
        return 0

    # explain
    analysis = analyze(stmt, min_hits=args.min_hits,
                       gap_cv_max=args.gap_cv, amount_tol=args.amount_tol,
                       amount_min=args.amount_min, ignore=args.ignore,
                       horizon=args.horizon, gap_outlier=args.gap_outlier)
    want = normalize(args.merchant)
    target = next((s for s in analysis["subscriptions"]
                   if s["merchant"] == want or s["label"] == args.merchant
                   or want in s["merchant"]),
                  None)
    if target is None:
        print("dusty-subs: no subscription found for: %s" % args.merchant,
              file=sys.stderr)
        return 3
    usage_rows: Optional[List[UsageRow]] = None
    if args.usage:
        try:
            usage_rows = read_usage(args.usage)
        except StatementError as exc:
            print("dusty-subs: %s" % exc, file=sys.stderr)
            return 3
    if args.format == "json":
        data = dict(target)
        data["statement"] = analysis["statement"]
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(render_explain(target, analysis, usage=usage_rows, mpu=args.mpu))
    return 0


if __name__ == "__main__":
    sys.exit(main())
