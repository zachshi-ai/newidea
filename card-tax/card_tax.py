#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""card-tax — 卡税 / Card Tax

A prepaid card is sold to the person you intend to become; it is consumed
by the person you actually are. The gap between the two is silent: no
statement arrives, the balance never ages out loud, and the last visit is
always "recent enough" in memory. The unused share is not a roundoff — it
is a tax you paid for the fantasy regular, priced at the walk-in rate you
were trying to avoid.

card-tax keeps that ledger by hand (two TSV files, one row per visit):

  * report    — per-card burn-up: used/units, rate, realized tax
                (paid - used x list price), verdict lights, and the
                total bill
  * pace      — the race your visits are losing: last-8-weeks pace vs
                the expiry clock, projected burn-down, money about to
                evaporate
  * cost      — the break-even ledger: cost per redeemed visit vs the
                list price, the break-even count, how far along you are
  * offer     — the renewal court: "recharge 3000 get 200 free" is
                projected against YOUR OWN historical redemption pace —
                history is the best predictor of the member you are,
                not the member you were when you signed
  * simulate  — a counterfactual sandbox: "what if I went N times a
                week" — how much walks back from the dead; always
                exit 0, sandboxes don't enforce
  * validate  — ledger identity checks (used + remaining == units,
                per-card taxes sum to the total bill)

Method in one line: tax = paid - used x list. A positive tax is what the
fantasy cost you; a negative one is the discount you only earn by showing
up. The list (walk-in) price is the anchor — without it, "paid" and
"used" are just two numbers that never have to face each other.

Verdict lights, worst first:
  EXPIRED  the card lapsed with visits still on the table (tax frozen)
  DEAD     redeem rate < 50% and the current silence broke the cliff line
  BLEED    at your last-8-weeks pace, most of the card dies at expiry
  ASLEEP   rate is salvageable but you have gone quiet past the line
  THIN     held < 28 days — arithmetic yes, verdicts later
  ON TRACK none of the above
  DONE     fully redeemed

Nothing here touches the network or the wall clock: the ledger anchors
itself (as-of = latest date in the ledger), --as-of pins it, and the same
two files always yield the same bytes. The ledger stays local on purpose.

Exit codes: 0 green · 2 ledger broken · 3 too thin to grade · 4 red light

Zero dependencies: Python 3.8+ standard library.
MIT License (c) 2026
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Dict, List, Optional, Tuple

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Parameters (common-knowledge priors; flags always win)

ASLEEP_FLOOR = 45      # days: silence beyond max(2 x median gap, this) = cliff
PACE_WINDOW = 8.0      # weeks: redemption pace window
THIN_DAYS = 28         # days: a card held shorter than this gets no verdict
STIFF_RATE = 0.50      # redeem rate below this + cliff = DEAD
SALVAGE_RATE = 0.50    # projected redeem rate below this = BLEED
BLEED_FLOOR = 100.0    # projected evaporation below this is not a BLEED light
RED_FLOOR = 100.0      # expired leftovers below this are not an EXPIRED light
STIFF_OLD = 0.60       # offer court: old cards under this rate block a new one
NEW_TAX_LINE = 0.30    # offer court: projected tax above this share = exit 4
SIM_WEEKS = 26.0       # default sandbox horizon for cards without an expiry

EXIT_OK = 0
EXIT_LEDGER = 2
EXIT_THIN = 3
EXIT_RED = 4

# verdict priority (worst first); a card shows its worst light
LIGHT_RANK = {"EXPIRED": 0, "DEAD": 1, "BLEED": 2, "ASLEEP": 3,
              "THIN": 4, "ON TRACK": 5, "DONE": 6}

# ---------------------------------------------------------------------------
# Column aliases (Chinese-first ledgers are first-class)

CARD_COLS = ("card", "id", "卡", "卡号")
NAME_COLS = ("name", "名称", "名字")
PAY_COLS = ("pay", "amount", "实付", "金额", "实付金额")
BUY_COLS = ("buy", "purchased", "购卡日", "购买日", "购于")
UNTIL_COLS = ("until", "expires", "expiry", "到期", "到期日", "有效期至")
UNITS_COLS = ("units", "total", "次数", "总次数", "总量")
LIST_COLS = ("list", "retail", "single", "散买价", "单次价", "单次")
TARGET_COLS = ("target", "weekly", "每周目标", "每周", "周频")

VCARD_COLS = CARD_COLS
VDATE_COLS = ("date", "日期", "核销日", "核销日期", "时间")
VNOTE_COLS = ("note", "备注", "说明", "notes")

DATE_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")


class LedgerError(Exception):
    """Broken ledger: exit 2."""


# ---------------------------------------------------------------------------
# Small pure helpers


def fmt_money(x: float) -> str:
    """1234.0 -> '1,234'; 73.25 -> '73.25'. No currency symbol: ledgers
    speak every currency and the tool stays agnostic."""
    if abs(x - round(x)) < 0.005:
        return "{:,}".format(int(round(x)))
    return "{:,.2f}".format(x)


def parse_date(s: str) -> Optional[date]:
    t = s.strip()
    m = DATE_RE.match(t)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_amount(s: str) -> Optional[float]:
    t = s.strip().lstrip("¥$€£￥").replace(",", "").replace(" ", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def normalize(key: str) -> str:
    """The ledger key behind a raw card id: lowercase, punctuation and
    whitespace folded. 'GYM-01' and 'gym 01' are the same card."""
    t = key.strip().lower()
    t = re.sub(r"[^\w\s]+", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def display_width(s: str) -> int:
    """Terminal cell width: CJK ideographs take two cells."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - display_width(s))


# ---------------------------------------------------------------------------
# Ledger parsing


@dataclass
class Card:
    key: str            # normalized id
    name: str           # display name
    pay: float          # what you actually paid
    buy: date           # purchase day
    until: Optional[date]  # expiry, if any
    units: float        # total redeemable units (visits)
    unit_type: str      # "count" | "time"
    list_price: float   # walk-in price per visit — the tax anchor
    target: float       # time cards: expected visits per week


@dataclass
class Visit:
    key: str            # normalized card id
    day: date
    note: str


@dataclass
class Ledger:
    cards_path: str
    visits_path: str
    cards: List[Card] = field(default_factory=list)
    visits: List[Visit] = field(default_factory=list)

    @property
    def anchor(self) -> date:
        """Ledger self-anchoring: the latest date written into it."""
        days = [c.buy for c in self.cards] + [v.day for v in self.visits]
        return max(days)

    def visits_for(self, key: str, as_of: date) -> List[Visit]:
        return sorted((v for v in self.visits
                       if v.key == key and v.day <= as_of),
                      key=lambda v: v.day)


def _read_rows(path: str) -> Tuple[str, List[List[str]]]:
    if not os.path.exists(path):
        raise LedgerError("no such file: %s" % path)
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    if not lines:
        raise LedgerError("empty file: %s" % path)
    body = [ln for ln in lines if not ln.lstrip().startswith("#")]
    if not body:
        raise LedgerError("only comments in file: %s" % os.path.basename(path))
    delim = max(("\t", ",", ";"), key=body[0].count)
    rows = list(csv.reader(body, delimiter=delim))
    return os.path.basename(path), rows


def _col(header: List[str], names: Tuple[str, ...]) -> int:
    for i, h in enumerate(header):
        if h.strip().lower() in names:
            return i
    return -1


def _cells(header: List[str], row: List[str],
           spec: List[Tuple[int, bool]]) -> Optional[List[str]]:
    """Pull columns by index; short rows fail only on required cells."""
    out = []
    for idx, required in spec:
        if idx < 0:
            out.append("")
            continue
        if idx >= len(row) or not row[idx].strip():
            if required:
                return None
            out.append("")
            continue
        out.append(row[idx].strip())
    return out


def read_cards(path: str) -> List[Card]:
    fname, rows = _read_rows(path)
    header = [h.strip().lower() for h in rows[0]]
    idx = {
        "card": _col(header, CARD_COLS),
        "name": _col(header, NAME_COLS),
        "pay": _col(header, PAY_COLS),
        "buy": _col(header, BUY_COLS),
        "until": _col(header, UNTIL_COLS),
        "units": _col(header, UNITS_COLS),
        "list": _col(header, LIST_COLS),
        "target": _col(header, TARGET_COLS),
    }
    missing = [n for n, i in (("card", idx["card"]), ("pay", idx["pay"]),
                              ("buy", idx["buy"]), ("list", idx["list"]))
               if i < 0]
    if missing:
        raise LedgerError(
            "cannot find %s column(s) in %s (header: %s)"
            % ("/".join(missing), fname, ",".join(header)))

    cards: List[Card] = []
    seen: Dict[str, str] = {}
    for row in rows[1:]:
        cells = _cells(header, row, [
            (idx["card"], True), (idx["name"], False), (idx["pay"], True),
            (idx["buy"], True), (idx["until"], False), (idx["units"], False),
            (idx["list"], True), (idx["target"], False)])
        if cells is None:
            raise LedgerError("%s: row missing a required column: %s"
                              % (fname, ",".join(row)))
        key = normalize(cells[0])
        if not key:
            continue
        pay = parse_amount(cells[2])
        buy = parse_date(cells[3])
        lst = parse_amount(cells[6])
        if pay is None or buy is None or lst is None:
            raise LedgerError("%s: bad pay/buy/list in row: %s"
                              % (fname, ",".join(row)))
        if lst <= 0:
            raise LedgerError("%s: list price must be > 0 for %s"
                              % (fname, cells[0]))
        if key in seen:
            raise LedgerError("%s: duplicate card id: %s" % (fname, cells[0]))
        seen[key] = cells[0]
        until = parse_date(cells[4]) if cells[4] else None
        if cells[4] and until is None:
            raise LedgerError("%s: bad until date: %s" % (fname, cells[4]))
        target = parse_amount(cells[7]) if cells[7] else None
        if cells[7] and (target is None or target <= 0):
            raise LedgerError("%s: target must be > 0 for %s"
                              % (fname, cells[0]))
        tgt = target if target is not None else 1.0
        if cells[5]:
            units = parse_amount(cells[5])
            if units is None or units <= 0:
                raise LedgerError("%s: units must be > 0 for %s"
                                  % (fname, cells[0]))
            unit_type = "count"
        else:
            if until is None:
                raise LedgerError(
                    "%s: %s needs units or until (a time card is measured"
                    " by its expiry)" % (fname, cells[0]))
            weeks = max((until - buy).days, 0) / 7.0
            units = weeks * tgt
            unit_type = "time"
        if until is not None and until < buy:
            raise LedgerError("%s: until %s is before buy %s for %s"
                              % (fname, until, buy, cells[0]))
        cards.append(Card(key=key, name=cells[1] or cells[0], pay=pay,
                          buy=buy, until=until, units=units,
                          unit_type=unit_type, list_price=lst, target=tgt))
    if not cards:
        raise LedgerError("%s: no card rows" % fname)
    return cards


def read_visits(path: str) -> List[Visit]:
    fname, rows = _read_rows(path)
    header = [h.strip().lower() for h in rows[0]]
    i_card = _col(header, VCARD_COLS)
    i_day = _col(header, VDATE_COLS)
    i_note = _col(header, VNOTE_COLS)
    missing = [n for n, i in (("card", i_card), ("date", i_day)) if i < 0]
    if missing:
        raise LedgerError(
            "cannot find %s column(s) in %s (header: %s)"
            % ("/".join(missing), fname, ",".join(header)))
    out: List[Visit] = []
    for row in rows[1:]:
        cells = _cells(header, row, [(i_card, True), (i_day, True),
                                     (i_note, False)])
        if cells is None:
            raise LedgerError("%s: row missing card/date: %s"
                              % (fname, ",".join(row)))
        day = parse_date(cells[1])
        if day is None:
            raise LedgerError("%s: bad date: %s" % (fname, cells[1]))
        out.append(Visit(key=normalize(cells[0]), day=day, note=cells[2]))
    return out


def load_ledger(cards_path: str, visits_path: str) -> Ledger:
    cards = read_cards(cards_path)
    visits = read_visits(visits_path)
    known = {c.key for c in cards}
    for v in visits:
        if v.key not in known:
            raise LedgerError(
                "%s: visit on unknown card: %s" % (
                    os.path.basename(visits_path), v.key))
    for c in cards:
        for v in visits:
            if v.key == c.key and v.day < c.buy:
                raise LedgerError(
                    "%s: visit on %s predates the purchase (%s < %s)"
                    % (os.path.basename(visits_path), c.name, v.day, c.buy))
    return Ledger(cards_path=cards_path, visits_path=visits_path,
                  cards=cards, visits=visits)


# ---------------------------------------------------------------------------
# Per-card evaluation


@dataclass
class CardEval:
    card: Card
    used: int
    remaining: float
    rate: float                 # used / units
    tax: float                  # paid - used * list (negative = credit)
    value_left: float           # remaining * list
    per_used: Optional[float]   # paid / used
    breakeven: float            # paid / list (visits to break even)
    progress: float             # used / breakeven
    held: int                   # days since purchase (as-of anchored)
    last_day: Optional[date]
    silence: Optional[int]      # days since last visit (as-of anchored)
    median_gap: Optional[float]
    cliff_line: Optional[int]   # max(2 * median gap, asleep floor)
    on_cliff: bool
    pace: Optional[float]       # visits/week over the pace window
    weeks_left: Optional[float]
    projected: Optional[int]    # projected extra redemptions by expiry
    projected_rate: Optional[float]
    evaporation: Optional[float]  # projected value left on the table
    lights: List[str]
    thin: bool


def evaluate(ledger: Ledger, as_of: date, asleep_floor: int,
             bleed_floor: float, red_floor: float,
             pace_card: Optional[str] = None) -> List[CardEval]:
    out: List[CardEval] = []
    window_start = as_of - timedelta(days=int(round(PACE_WINDOW * 7 - 1)))
    for card in ledger.cards:
        visits = ledger.visits_for(card.key, as_of)
        used = len(visits)
        remaining = max(card.units - used, 0.0)
        rate = used / card.units if card.units > 0 else 0.0
        tax = card.pay - used * card.list_price
        value_left = remaining * card.list_price
        per_used = card.pay / used if used > 0 else None
        breakeven = card.pay / card.list_price
        progress = used / breakeven if breakeven > 0 else 0.0
        last_day = visits[-1].day if visits else None
        silence = (as_of - last_day).days if last_day else \
            (as_of - card.buy).days
        gaps = [int((b.day - a.day).days)
                for a, b in zip(visits, visits[1:])]
        med_gap = float(median(gaps)) if gaps else None
        line: Optional[int] = None
        if med_gap is not None:
            line = int(max(round(2 * med_gap), asleep_floor))
        else:
            line = asleep_floor
        on_cliff = silence > line
        in_window = [v for v in visits if v.day >= window_start]
        pace = len(in_window) / PACE_WINDOW

        weeks_left: Optional[float] = None
        projected: Optional[int] = None
        projected_rate: Optional[float] = None
        evaporation: Optional[float] = None
        if card.until is not None:
            weeks_left = max((card.until - as_of).days, 0) / 7.0
            projected = int(pace * weeks_left)  # floor: no fractional visits
            projected_rate = (used + projected) / card.units
            evaporation = max(card.units - used - projected, 0.0) \
                * card.list_price

        lights: List[str] = []
        held = max((as_of - card.buy).days, 0)
        thin = held < THIN_DAYS
        if used >= card.units:
            lights.append("DONE")
        if thin:
            lights.append("THIN")
        if card.until is not None and card.until < as_of and remaining > 0:
            if value_left >= red_floor:
                lights.append("EXPIRED")
        if rate < STIFF_RATE and on_cliff and not thin:
            lights.append("DEAD")
        elif rate >= STIFF_RATE and on_cliff and not thin:
            lights.append("ASLEEP")
        if projected_rate is not None and projected_rate < SALVAGE_RATE \
                and not thin:
            if evaporation is not None and evaporation >= bleed_floor:
                lights.append("BLEED")
        if not lights:
            lights.append("ON TRACK")

        out.append(CardEval(
            card=card, used=used, remaining=remaining, rate=rate, tax=tax,
            value_left=value_left, per_used=per_used, breakeven=breakeven,
            progress=progress, last_day=last_day, silence=silence,
            median_gap=med_gap, cliff_line=line, on_cliff=on_cliff,
            pace=pace, weeks_left=weeks_left, projected=projected,
            projected_rate=projected_rate, evaporation=evaporation,
            lights=lights, thin=thin, held=held))
    return out


def worst_light(lights: List[str]) -> str:
    return sorted(lights, key=lambda l: LIGHT_RANK.get(l, 99))[0]


def ledger_verdict(evals: List[CardEval]) -> Tuple[str, List[str]]:
    """Global verdict: worst light across gradable cards + exit code."""
    red = []
    for e in evals:
        for light in e.lights:
            if light in ("EXPIRED", "DEAD", "BLEED"):
                red.append("%s:%s" % (e.card.name, light))
    if red:
        return "RED", red
    return "GREEN", []


# ---------------------------------------------------------------------------
# Commands


def _json_evals(evals: List[CardEval], as_of: date, total_tax: float,
                verdict: str, red: List[str]) -> dict:
    return {
        "as_of": as_of.isoformat(),
        "cards": [{
            "card": e.card.name,
            "pay": round(e.card.pay, 2),
            "list": round(e.card.list_price, 2),
            "units": round(e.card.units, 2),
            "used": e.used,
            "remaining": round(e.remaining, 2),
            "rate": round(e.rate, 4),
            "tax": round(e.tax, 2),
            "value_left": round(e.value_left, 2),
            "per_used": (round(e.per_used, 2)
                         if e.per_used is not None else None),
            "breakeven": round(e.breakeven, 2),
            "progress": round(e.progress, 4),
            "silence_days": e.silence,
            "pace_per_week": round(e.pace, 3),
            "until": (e.card.until.isoformat()
                      if e.card.until else None),
            "projected": e.projected,
            "evaporation": (round(e.evaporation, 2)
                            if e.evaporation is not None else None),
            "lights": e.lights,
        } for e in evals],
        "total_tax": round(total_tax, 2),
        "verdict": verdict,
        "red": red,
    }


def cmd_report(ledger: Ledger, as_of: date, asleep_floor: int,
               bleed_floor: float, red_floor: float,
               as_json: bool) -> int:
    evals = evaluate(ledger, as_of, asleep_floor, bleed_floor, red_floor)
    total_tax = sum(e.tax for e in evals)
    total_pay = sum(e.card.pay for e in evals)
    total_redeemed = sum(e.used * e.card.list_price for e in evals)
    thin_global = sum(e.used for e in evals) < 3
    verdict, red = ledger_verdict(evals)

    if as_json:
        print(json.dumps(_json_evals(evals, as_of, total_tax, verdict, red),
                        indent=2, ensure_ascii=False))
    else:
        lines = [
            "-- Card Tax report: %s + %s" % (
                os.path.basename(ledger.cards_path),
                os.path.basename(ledger.visits_path)),
            "  as-of : %s (ledger-anchored; --as-of pins it)"
            % as_of.isoformat(),
            "  cards : %d   visits: %d   paid: %s   redeemed at list: %s"
            % (len(evals), sum(e.used for e in evals),
               fmt_money(total_pay), fmt_money(total_redeemed)),
            "",
            "  card ledger (tax, worst first):",
        ]
        width = max([10] + [display_width(e.card.name) for e in evals])
        lines.append("    %s  %11s  %6s  %5s  %10s  %s"
                     % (pad("card", width), "used/units", "rate", "left",
                        "tax", "verdict"))
        for e in sorted(evals, key=lambda e: (-e.tax, e.card.key)):
            lines.append("    %s  %11s  %5.1f%%  %5s  %10s  %s"
                         % (pad(e.card.name, width),
                            "%d/%s" % (e.used, _fmt_units(e.card.units)),
                            100.0 * e.rate, _fmt_units(e.remaining),
                            fmt_money(e.tax), worst_light(e.lights)))
        lines.append("    %s  %11s  %6s  %5s  %10s"
                     % (pad("TOTAL", width), "", "", "",
                        fmt_money(total_tax)))
        lines.append("")
        lines.append("  tax identity: paid %s - redeemed %s = tax %s"
                     % (fmt_money(total_pay), fmt_money(total_redeemed),
                        fmt_money(total_tax)))
        lines.append("  a positive tax is what the no-show version of you"
                     " paid; negative is the")
        lines.append("  discount you only earn by showing up.")
        if thin_global:
            lines.append("")
            lines.append("  STATISTICS REFUSED: fewer than 3 visits in the"
                         " whole ledger — arithmetic above stands,"
                         " no verdicts yet")
        for e in evals:
            for extra in e.lights:
                if extra in ("THIN",):
                    lines.append("  · %s held %d days (< %d): light not"
                                 " graded yet" % (e.card.name, e.held,
                                                  THIN_DAYS))
        if red:
            lines.append("")
            lines.append("  RED: %s — the fantasy regular is paying dues"
                         % ", ".join(red))
        lines.append("")
        print("\n".join(lines))

    if thin_global:
        return EXIT_THIN
    if verdict == "RED":
        return EXIT_RED
    return EXIT_OK


def _fmt_units(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return "%.1f" % x


def cmd_pace(ledger: Ledger, as_of: date, asleep_floor: int,
             bleed_floor: float, red_floor: float, as_json: bool) -> int:
    evals = evaluate(ledger, as_of, asleep_floor, bleed_floor, red_floor)
    verdict, red = ledger_verdict(evals)

    if as_json:
        print(json.dumps(_json_evals(evals, as_of, sum(e.tax for e in evals),
                                     verdict, red),
                        indent=2, ensure_ascii=False))
    else:
        lines = [
            "-- Card Tax pace: %s + %s" % (
                os.path.basename(ledger.cards_path),
                os.path.basename(ledger.visits_path)),
            "  as-of : %s   pace window: trailing %g weeks"
            % (as_of.isoformat(), PACE_WINDOW),
            "",
        ]
        for e in evals:
            c = e.card
            lines.append("  %s" % c.name)
            if e.thin:
                lines.append("    held %d days (< %d): pace not graded yet"
                             % (e.held, THIN_DAYS))
                lines.append("")
                continue
            lines.append(
                "    used %s of %s (%.1f%%) · pace %.2f/week"
                % (_fmt_units(e.used), _fmt_units(c.units), 100.0 * e.rate,
                   e.pace))
            if c.until is not None and e.weeks_left is not None:
                lines.append(
                    "    expiry %s: %.1f weeks left -> +%s projected"
                    % (c.until.isoformat(), e.weeks_left,
                       _fmt_units(e.projected or 0)))
                lines.append(
                    "    projected rate %.1f%% · evaporation %s (at list %s)"
                    % (100.0 * (e.projected_rate or 0.0),
                       fmt_money(e.evaporation or 0.0),
                       fmt_money(c.list_price)))
            else:
                lines.append("    no expiry on file: the race never ends,"
                             " only the silence does")
            lines.append(
                "    last visit %s · silence %dd vs cliff line %dd -> %s"
                % (e.last_day.isoformat() if e.last_day else "-",
                   e.silence, e.cliff_line or 0,
                   "CLIFF" if e.on_cliff else "ok"))
            lines.append("    lights: %s" % ", ".join(e.lights))
            lines.append("")
        if red:
            lines.append("  RED: %s" % ", ".join(red))
            lines.append("")
        print("\n".join(lines))

    if verdict == "RED":
        return EXIT_RED
    return EXIT_OK


def cmd_cost(ledger: Ledger, as_of: date, asleep_floor: int,
             bleed_floor: float, red_floor: float, as_json: bool) -> int:
    evals = evaluate(ledger, as_of, asleep_floor, bleed_floor, red_floor)
    verdict, red = ledger_verdict(evals)

    if as_json:
        print(json.dumps(_json_evals(evals, as_of, sum(e.tax for e in evals),
                                     verdict, red),
                        indent=2, ensure_ascii=False))
    else:
        lines = [
            "-- Card Tax cost: %s + %s" % (
                os.path.basename(ledger.cards_path),
                os.path.basename(ledger.visits_path)),
            "  as-of : %s   anchor: the walk-in (list) price you were"
            " avoiding" % as_of.isoformat(),
            "",
        ]
        width = max([10] + [display_width(e.card.name) for e in evals])
        lines.append("    %s  %11s  %11s  %9s  %9s  %s"
                     % (pad("card", width), "per redeemed", "list",
                        "breakeven", "progress", "tax"))
        for e in sorted(evals, key=lambda e: (-e.tax, e.card.key)):
            per = fmt_money(e.per_used) if e.per_used is not None else "n/a"
            lines.append("    %s  %11s  %11s  %9s  %8.1f%%  %10s"
                         % (pad(e.card.name, width), per,
                            fmt_money(e.card.list_price),
                            _fmt_units(e.breakeven), 100.0 * e.progress,
                            fmt_money(e.tax)))
        lines.append("")
        lines.append("  per-redeemed > list means every past visit is still"
                     " paying for the ones")
        lines.append("  you never made. breakeven = paid / list: the visit"
                     " count where the card stops")
        lines.append("  being a bet and becomes a discount.")
        lines.append("")
        print("\n".join(lines))

    if verdict == "RED":
        return EXIT_RED
    return EXIT_OK


def cmd_offer(ledger: Ledger, as_of: date, asleep_floor: int,
              bleed_floor: float, red_floor: float, pay: float,
              units: float, list_price: float, until: Optional[date],
              days: Optional[int], as_json: bool) -> int:
    evals = evaluate(ledger, as_of, asleep_floor, bleed_floor, red_floor)
    gradable = [e for e in evals if not e.thin]

    # historical redemption pace over every gradable card's coverage
    cov_days = 0
    cov_used = 0
    for e in gradable:
        end = as_of
        if e.card.until is not None:
            end = min(end, e.card.until)
        span = (end - e.card.buy).days
        cov_days += max(span, 1)
        cov_used += e.used
    pace = cov_used / cov_days * 7.0 if cov_days > 0 else 0.0

    if until is not None:
        weeks = max((until - as_of).days, 0) / 7.0
    else:
        weeks = days / 7.0
    blocked_old = [e for e in gradable
                   if e.remaining > 0 and e.rate < STIFF_OLD]

    projected: Optional[int] = None
    new_tax: Optional[float] = None
    new_tax_share: Optional[float] = None
    if weeks is not None:
        projected = int(pace * weeks)
        new_tax = pay - projected * list_price
        new_tax_share = new_tax / pay if pay > 0 else 0.0

    red = False
    reasons: List[str] = []
    if blocked_old:
        red = True
        reasons.append("old cards still on the table: %s"
                       % ", ".join("%s (%.1f%% used, %s left)"
                                   % (e.card.name, 100.0 * e.rate,
                                      _fmt_units(e.remaining))
                                   for e in blocked_old))
    if new_tax_share is not None and new_tax_share > NEW_TAX_LINE:
        red = True
        reasons.append("at your own pace (%.2f/week over %d visits / %dd)"
                       " only %s of %s units redeem inside the term ->"
                       " projected tax %s (%.1f%% of what you'd pay)"
                       % (pace, cov_used, cov_days,
                          _fmt_units(projected or 0), _fmt_units(units),
                          fmt_money(new_tax or 0.0),
                          100.0 * new_tax_share))
    if new_tax_share is not None and not red:
        reasons.append("at your own pace %.2f/week: %s of %s units redeem,"
                       " projected tax %s (%.1f%%) — under the %d%% line"
                       % (pace, _fmt_units(projected or 0),
                          _fmt_units(units), fmt_money(new_tax or 0.0),
                          100.0 * new_tax_share, round(100 * NEW_TAX_LINE)))

    if as_json:
        print(json.dumps({
            "as_of": as_of.isoformat(),
            "history_pace_per_week": round(pace, 3),
            "history_visits": cov_used,
            "history_days": cov_days,
            "new_card": {"pay": pay, "units": units,
                         "list": list_price,
                         "weeks": round(weeks, 2) if weeks is not None
                         else None},
            "projected_redeem": projected,
            "projected_tax": (round(new_tax, 2)
                              if new_tax is not None else None),
            "blocked_by_old": [e.card.name for e in blocked_old],
            "verdict": "RED" if red else "GREEN",
            "reasons": reasons,
        }, indent=2, ensure_ascii=False))
    else:
        lines = [
            "-- Card Tax offer court: %s + %s" % (
                os.path.basename(ledger.cards_path),
                os.path.basename(ledger.visits_path)),
            "  as-of : %s" % as_of.isoformat(),
            "  proposed card: pay %s · %s units · list %s · term %s"
            % (fmt_money(pay), _fmt_units(units), fmt_money(list_price),
               "%.1f weeks" % weeks),
            "",
        ]
        for r in reasons:
            lines.append("  · %s" % r)
        lines.append("")
        lines.append("  history is the best predictor of the member you"
                     " are, not the member you")
        lines.append("  were on signing day.")
        lines.append("")
        print("\n".join(lines))

    if red:
        return EXIT_RED
    return EXIT_OK


def cmd_simulate(ledger: Ledger, as_of: date, asleep_floor: int,
                 bleed_floor: float, red_floor: float, weekly: float,
                 card_key: Optional[str], weeks_cap: Optional[float],
                 as_json: bool) -> int:
    evals = evaluate(ledger, as_of, asleep_floor, bleed_floor, red_floor)
    if card_key is not None:
        want = normalize(card_key)
        evals = [e for e in evals if e.card.key == want]
        if not evals:
            print("card-tax: no such card: %s" % card_key, file=sys.stderr)
            return EXIT_LEDGER

    rows = []
    total_rescue = 0.0
    for e in evals:
        if e.thin:
            continue
        if e.card.until is not None and e.weeks_left is not None:
            horizon = e.weeks_left
        else:
            horizon = weeks_cap if weeks_cap is not None else SIM_WEEKS
        feasible = int(weekly * horizon)
        rescue_n = min(float(feasible), e.remaining)
        rescue_value = rescue_n * e.card.list_price
        left_after = e.remaining - rescue_n
        rows.append({
            "card": e.card.name, "horizon_weeks": round(horizon, 2),
            "feasible": feasible, "rescue": rescue_n,
            "rescue_value": round(rescue_value, 2),
            "left_after": round(left_after, 2),
            "was_left": round(e.remaining, 2),
        })
        total_rescue += rescue_value

    if as_json:
        print(json.dumps({
            "as_of": as_of.isoformat(), "weekly": weekly,
            "rows": rows, "total_rescue_value": round(total_rescue, 2),
        }, indent=2, ensure_ascii=False))
    else:
        lines = [
            "-- Card Tax sandbox: %s + %s" % (
                os.path.basename(ledger.cards_path),
                os.path.basename(ledger.visits_path)),
            "  as-of : %s   counterfactual: %s visits/week"
            % (as_of.isoformat(), ("%g" % weekly)),
            "",
        ]
        width = max([10] + [display_width(r["card"]) for r in rows]) \
            if rows else 10
        for r in rows:
            lines.append("  %s" % r["card"])
            lines.append(
                "    %g weeks -> %s feasible, %s rescued (%s back at list),"
                " %s still on the table"
                % (r["horizon_weeks"], _fmt_units(r["feasible"]),
                   _fmt_units(r["rescue"]), fmt_money(r["rescue_value"]),
                   _fmt_units(r["left_after"])))
            assert abs(r["rescue"] + r["left_after"] - r["was_left"]) < 1e-9
        lines.append("")
        lines.append("  total walk-back: %s — sandboxes don't enforce;"
                     " calendars do." % fmt_money(total_rescue))
        lines.append("")
        print("\n".join(lines))
    return EXIT_OK


def cmd_validate(ledger: Ledger, as_of: date, asleep_floor: int,
                 bleed_floor: float, red_floor: float) -> int:
    problems: List[str] = []
    evals = evaluate(ledger, as_of, asleep_floor, bleed_floor, red_floor)

    # identity 1: used + remaining == units, per card
    for e in evals:
        if abs(e.used + e.remaining - e.card.units) > 1e-9:
            problems.append("%s: used %s + remaining %s != units %s"
                            % (e.card.name, e.used,
                               _fmt_units(e.remaining),
                               _fmt_units(e.card.units)))

    # identity 2: per-card taxes sum to the total bill
    per_card = sum(e.tax for e in evals)
    total_pay = sum(e.card.pay for e in evals)
    total_redeemed = sum(e.used * e.card.list_price for e in evals)
    bill = total_pay - total_redeemed
    if abs(per_card - bill) > 1e-6:
        problems.append("tax identity broken: per-card %s vs paid-redeemed"
                        " %s" % (fmt_money(per_card), fmt_money(bill)))

    # identity 3: time-card units == weeks x target
    for e in evals:
        c = e.card
        if c.unit_type == "time" and c.until is not None:
            weeks = max((c.until - c.buy).days, 0) / 7.0
            if abs(c.units - weeks * c.target) > 1e-9:
                problems.append("%s: time units %s != %g weeks x %g/week"
                                % (c.name, _fmt_units(c.units), weeks,
                                   c.target))

    # identity 4: no over-redemption anywhere
    for e in evals:
        if e.used > e.card.units + 1e-9:
            problems.append("%s: over-redeemed (%d > %s)"
                            % (e.card.name, e.used, _fmt_units(e.card.units)))

    lines = [
        "-- Card Tax validate: %s + %s" % (
            os.path.basename(ledger.cards_path),
            os.path.basename(ledger.visits_path)),
        "  as-of : %s" % as_of.isoformat(),
    ]
    if problems:
        lines.append("  BROKEN (%d):" % len(problems))
        for p in problems:
            lines.append("    · %s" % p)
        print("\n".join(lines))
        return EXIT_LEDGER
    lines.append("  identities: used+remaining==units · Σtax==paid-redeemed"
                 " (%s) · time units==weeks×target · no over-redemption"
                 % fmt_money(bill))
    lines.append("  ALL OK")
    print("\n".join(lines))
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI


def _as_of_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                   help="pin the ledger clock (default: latest ledger date)")


def _light_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--asleep-days", type=int, default=ASLEEP_FLOOR,
                   metavar="D",
                   help="silence floor for the cliff line (default %d)"
                        % ASLEEP_FLOOR)
    p.add_argument("--bleed-floor", type=float, default=BLEED_FLOOR,
                   metavar="AMT",
                   help="projected evaporation below this is no BLEED light"
                        " (default %s)" % BLEED_FLOOR)
    p.add_argument("--red-floor", type=float, default=RED_FLOOR,
                   metavar="AMT",
                   help="expired leftovers below this are no EXPIRED light"
                        " (default %s)" % RED_FLOOR)
    p.add_argument("--format", choices=("text", "json"), default="text")


ALIASES = {
    "report": "report", "status": "report",
    "pace": "pace",
    "cost": "cost",
    "offer": "offer", "upgrade": "offer",
    "simulate": "simulate", "sim": "simulate",
    "validate": "validate", "check": "validate",
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="card_tax.py",
        description="Card Tax: the prepaid-card ledger — what the"
                    " no-show version of you paid.",
    )
    sub = parser.add_subparsers(dest="cmd")

    def _base(p: argparse.ArgumentParser) -> None:
        p.add_argument("cards", help="cards TSV: card,name,pay,buy,until,"
                                     "units,list,target")
        p.add_argument("visits", help="visits TSV: card,date,note")

    def _wire_common(p: argparse.ArgumentParser) -> None:
        _base(p)
        _as_of_arg(p)
        _light_args(p)

    # register every surface name (aliases share the same wiring)
    for name, help_text in (("report", "per-card burn-up and tax bill"),
                            ("status", "alias of report"),
                            ("pace", "visits vs the expiry clock"),
                            ("cost", "break-even ledger vs list price")):
        p = sub.add_parser(name, help=help_text)
        _wire_common(p)

    for name in ("offer", "upgrade"):
        p = sub.add_parser(
            name, help="court a renewal against your own history"
            if name == "offer" else "alias of offer")
        _wire_common(p)
        p.add_argument("--pay", type=float, required=True,
                       help="price of the card you are being offered")
        p.add_argument("--units", type=float, required=True,
                       help="units it advertises")
        p.add_argument("--list", dest="list_price", type=float,
                       required=True, help="walk-in price per visit")
        term = p.add_mutually_exclusive_group(required=True)
        term.add_argument("--until", default=None, metavar="YYYY-MM-DD",
                          help="the offered card's expiry")
        term.add_argument("--days", type=int, default=None, metavar="D",
                          help="term length in days"
                               " (alternative to --until)")

    for name in ("simulate", "sim"):
        p = sub.add_parser(
            name, help="counterfactual: what if you went N times a week"
            if name == "simulate" else "alias of simulate")
        _wire_common(p)
        p.add_argument("--weekly", type=float, default=1.0,
                       help="assumed visits per week (default 1)")
        p.add_argument("--card", default=None,
                       help="limit the sandbox to one card")
        p.add_argument("--weeks", type=float, default=None, metavar="W",
                       help="horizon for cards without an expiry"
                            " (default %g)" % SIM_WEEKS)

    for name in ("validate", "check"):
        p = sub.add_parser(name, help="ledger identity checks"
                           if name == "validate" else "alias of validate")
        _wire_common(p)

    args = parser.parse_args(argv)
    cmd = ALIASES.get(args.cmd or "", "")
    if not cmd:
        parser.print_usage(sys.stderr)
        return EXIT_LEDGER

    try:
        ledger = load_ledger(args.cards, args.visits)
    except LedgerError as exc:
        print("card-tax: %s" % exc, file=sys.stderr)
        return EXIT_LEDGER

    as_of = ledger.anchor if args.as_of is None else parse_date(args.as_of)
    if as_of is None:
        print("card-tax: bad --as-of: %s" % args.as_of, file=sys.stderr)
        return EXIT_LEDGER

    if cmd == "report":
        return cmd_report(ledger, as_of, args.asleep_days, args.bleed_floor,
                          args.red_floor, args.format == "json")
    if cmd == "pace":
        return cmd_pace(ledger, as_of, args.asleep_days, args.bleed_floor,
                        args.red_floor, args.format == "json")
    if cmd == "cost":
        return cmd_cost(ledger, as_of, args.asleep_days, args.bleed_floor,
                        args.red_floor, args.format == "json")
    if cmd == "offer":
        until = parse_date(args.until) if args.until else None
        if args.until and until is None:
            print("card-tax: bad --until: %s" % args.until, file=sys.stderr)
            return EXIT_LEDGER
        return cmd_offer(ledger, as_of, args.asleep_days, args.bleed_floor,
                         args.red_floor, args.pay, args.units,
                         args.list_price, until, args.days,
                         args.format == "json")
    if cmd == "simulate":
        return cmd_simulate(ledger, as_of, args.asleep_days,
                            args.bleed_floor, args.red_floor, args.weekly,
                            args.card, args.weeks, args.format == "json")
    return cmd_validate(ledger, as_of, args.asleep_days, args.bleed_floor,
                        args.red_floor)


if __name__ == "__main__":
    sys.exit(main())
