#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wilting-point · 凋萎点 —— 植物不是在你发现那天死的，是在凋萎线被越过那一刻就注定死的.

问题：室内植物的头号死因不是虫不是病，是「忘了浇水」和「浇水太勤」。
花市 App 只会说「该浇花啦」，从不回答三件事：还有几天可以拖？十盆里谁
最危险？以及最重要的——「我到底适不适合养这种植物」？这个问题其实
你的浇水日志早就回答了：你的实际浇水间隔中位数就是你的植物主人性格，
而每盆植物的安全线（耐旱下限）和凋萎线（耐旱上限）是写在品种里的。
两边一对账，「这段姻缘能不能成」不再是玄学。

wilting-point 从两份可手编的 TSV（植物台账 + 浇水日志）确定性算出：

  * 水位计    每盆植物的剩余天数与四档状态 OK / DUE / PARCHED / WILTED
  * 凋萎点    越过耐旱上限的那一刻，损伤即不可逆——倒计时到天
  * 失调账本  哪些品种在你的照顾下反复越线（≥2 次 → 再购黑名单）
  * 过度关怀  最近两次间隔都短于安全线一半 → 烂根灯（多肉第一死因）
  * 主人画像  你的中位浇水间隔，以及收藏里多少盆比你想象的勤快
  * 出差推演  trip N：不浇走 vs 浇完走，谁撑不到你回来
  * 购入门卫  advice 物种：你的性格 × 它的安全线 = 三档判决

零依赖：Python 3.8+ 标准库。账本留在本地，时钟默认取账本最大日期，
--today 可拨表——账本是确定性的，时钟也是。拔不拔那盆蕨是你的决定；
但没有倒计时，阳台永远死于「下周一定浇」。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date as _date, timedelta
from typing import Dict, List, Optional, Tuple

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_GATE = 4

WINDOW_SHARE = 0.7     # DUE band opens at 70% of the safe line
OVERWATER_SHARE = 0.5  # rot lamp: gap < 50% of safe line, twice in a row
SEASON_FACTOR = {"summer": 0.7, "winter": 1.3}
CADENCE_MARGIN = 1.5   # COMPATIBLE needs safe line >= 1.5 × your cadence
BLACKLIST_AT = 2       # species misses >= 2 -> rebuy blacklist

OK, DUE, PARCHED, WILTED = "OK", "DUE", "PARCHED", "WILTED"
BAND_ORDER = (WILTED, PARCHED, DUE, OK)


# ---------------------------------------------------------------------------
# built-in species table (days you can forget it: safe line / wilting point)
# ---------------------------------------------------------------------------

SPECIES: Tuple[Tuple[str, str, int, int, str], ...] = (
    ("boston-fern", "波士顿蕨", 4, 8, "feathered humidity lover, dries out in days"),
    ("nerve-plant", "网纹草", 4, 7, "windowsill jewel, forgives nothing"),
    ("calathea", "竹芋", 5, 9, "prays at night, drinks at dawn"),
    ("peace-lily", "白鹤芋", 5, 9, "the dramatic fainter, revives if you are quick"),
    ("ivy", "常春藤", 5, 10, "fast vines, fast thirst"),
    ("orchid", "蝴蝶兰", 7, 14, "rot kills it faster than drought ever will"),
    ("monstera", "龟背竹", 7, 14, "forgiving until it isn't"),
    ("pothos", "绿萝", 7, 15, "the office survivor"),
    ("rubber-plant", "橡皮树", 10, 21, "sturdy tree, slow clock"),
    ("haworthia", "玉露", 10, 21, "succulent that still likes a sip"),
    ("jade-plant", "玉树", 14, 30, "stores water, resents attention"),
    ("aloe", "芦荟", 14, 30, "first-aid kit that hates wet feet"),
    ("succulent", "多肉(通用)", 14, 30, "drought is its native weather"),
    ("snake-plant", "虎皮兰", 21, 45, "nearly unkillable, rots if loved"),
    ("zz-plant", "金钱树", 21, 45, "the rhizome remembers"),
    ("cactus", "仙人掌", 21, 45, "a month of neglect is its comfort zone"),
)
SPECIES_BY_KEY = {row[0]: row for row in SPECIES}


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

class LedgerError(ValueError):
    """A bad ledger/log file; message carries the 1-based line number."""


@dataclass
class Plant:
    name: str
    species: str
    dry_min: float
    dry_max: float
    acquired: str
    notes: str
    line: int


@dataclass
class Watering:
    date: str
    plant: str
    note: str
    line: int


@dataclass
class Shelf:
    plants: List[Plant]
    log: List[Watering]
    by_plant: Dict[str, List[str]] = field(default_factory=dict)

    def log_dates(self, name: str) -> List[str]:
        return self.by_plant.get(name, [])


def parse_iso(text: str, what: str, line: int) -> str:
    try:
        _date.fromisoformat(text)
    except ValueError:
        raise LedgerError("line %d: bad %s %r (want YYYY-MM-DD)"
                          % (line, what, text))
    return text


def _read_rows(path: str) -> List[List[str]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw_lines = fh.read().splitlines()
    except OSError as exc:
        raise LedgerError("cannot read file: %s" % exc)
    rows: List[List[str]] = []
    for idx, raw in enumerate(raw_lines, start=1):
        line = raw.rstrip("\r").rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rows.append([c.strip() for c in line.split("\t")] + [idx])
    return rows


def read_ledger(path: str) -> List[Plant]:
    plants: List[Plant] = []
    saw_header = False
    for cols in _read_rows(path):
        idx = cols[-1]
        cols = cols[:-1]
        if cols[0] == "plant":
            if saw_header or plants:
                raise LedgerError("line %d: duplicate header row" % idx)
            saw_header = True
            continue
        if len(cols) < 5:
            raise LedgerError("line %d: want plant/species/dry_min/dry_max/"
                              "acquired[/notes], got %d column(s)"
                              % (idx, len(cols)))
        name, species = cols[0], cols[1]
        try:
            dry_min, dry_max = float(cols[2]), float(cols[3])
        except ValueError:
            raise LedgerError("line %d: dry lines must be numbers, got %r/%r"
                              % (idx, cols[2], cols[3]))
        if dry_min <= 0 or dry_max <= 0:
            raise LedgerError("line %d: dry lines must be positive" % idx)
        if dry_min > dry_max:
            raise LedgerError("line %d: safe line %g d exceeds wilting point %g d"
                              % (idx, dry_min, dry_max))
        if any(p.name == name for p in plants):
            raise LedgerError("line %d: duplicate plant %r" % (idx, name))
        plants.append(Plant(name, species, dry_min, dry_max,
                            parse_iso(cols[4], "acquired", idx),
                            cols[5] if len(cols) > 5 else "", idx))
    if not plants:
        raise LedgerError("ledger has no plants")
    return plants


def read_log(path: str, plants: List[Plant]) -> List[Watering]:
    names = {p.name for p in plants}
    acquired = {p.name: p.acquired for p in plants}
    events: List[Watering] = []
    saw_header = False
    seen: set = set()
    for cols in _read_rows(path):
        idx = cols[-1]
        cols = cols[:-1]
        if cols and cols[0] == "date":
            if saw_header or events:
                raise LedgerError("line %d: duplicate header row" % idx)
            saw_header = True
            continue
        if len(cols) < 2:
            raise LedgerError("line %d: want date/plant[/note], got %d column(s)"
                              % (idx, len(cols)))
        when = parse_iso(cols[0], "date", idx)
        name = cols[1]
        if name not in names:
            raise LedgerError("line %d: plant %r is not in the ledger" % (idx, name))
        if when < acquired[name]:
            raise LedgerError("line %d: %s watered %s before it was acquired %s"
                              % (idx, name, when, acquired[name]))
        key = (name, when)
        if key in seen:
            raise LedgerError("line %d: duplicate watering of %s on %s"
                              % (idx, name, when))
        seen.add(key)
        events.append(Watering(when, name,
                               cols[2] if len(cols) > 2 else "", idx))
    return events


def index_log(log: List[Watering]) -> Dict[str, List[str]]:
    by_plant: Dict[str, List[str]] = {}
    for ev in log:
        by_plant.setdefault(ev.plant, []).append(ev.date)
    for dates in by_plant.values():
        dates.sort()
    return by_plant


def load_shelf(ledger_path: str, log_path: str) -> Shelf:
    plants = read_ledger(ledger_path)
    log = read_log(log_path, plants)
    return Shelf(plants, log, index_log(log))


def as_of_date(shelf: Shelf, today_override: Optional[str]) -> _date:
    if today_override is not None:
        try:
            return _date.fromisoformat(today_override)
        except ValueError:
            raise LedgerError("bad --today %r (want YYYY-MM-DD)" % today_override)
    latest = max(p.acquired for p in shelf.plants)
    if shelf.log:
        latest = max(latest, max(ev.date for ev in shelf.log))
    return _date.fromisoformat(latest)


# ---------------------------------------------------------------------------
# waterline model
# ---------------------------------------------------------------------------

@dataclass
class Reading:
    plant: Plant
    last_watered: Optional[str]   # None = never watered on record -> falls back to acquired
    never_watered: bool
    days_dry: int
    safe: float                   # effective safe line (season-adjusted)
    wilt: float                   # effective wilting point (season-adjusted)
    band: str
    misses: int                   # historical gaps beyond the safe line
    worst_overshoot: float        # worst gap minus safe line, days
    overwater: bool
    overwater_gaps: Tuple[float, float]


def fmt_days(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else "%.1f" % x


def median(xs: List[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        raise ValueError("median of empty list")
    mid = n // 2
    if n % 2:
        return float(xs[mid])
    return (xs[mid - 1] + xs[mid]) / 2.0


def intervals_of(dates: List[str]) -> List[float]:
    days = [_date.fromisoformat(d) for d in sorted(dates)]
    return [(b - a).days for a, b in zip(days, days[1:])]


def profile(shelf: Shelf) -> Tuple[Optional[float], List[float]]:
    """Your watering cadence: the median of every gap you ever left, any plant."""
    gaps: List[float] = []
    for p in shelf.plants:
        gaps.extend(intervals_of(shelf.log_dates(p.name)))
    return (median(gaps), gaps) if gaps else (None, gaps)


def read_shelf_state(shelf: Shelf, as_of: _date,
                     season: Optional[str]) -> Tuple[List[Reading], Dict[str, object]]:
    factor = SEASON_FACTOR.get(season or "", 1.0)
    cadence, _ = profile(shelf)

    readings: List[Reading] = []
    miss_by_species: Dict[str, int] = {}
    for p in sorted(shelf.plants, key=lambda x: x.line):
        dates = shelf.log_dates(p.name)
        never = not dates
        last = dates[-1] if dates else p.acquired
        d = (as_of - _date.fromisoformat(last)).days
        if d < 0:
            raise LedgerError("plant %s has log dates after as-of %s"
                              % (p.name, as_of.isoformat()))
        safe, wilt = p.dry_min * factor, p.dry_max * factor

        gaps = intervals_of(dates)
        misses = sum(1 for g in gaps if g > p.dry_min)
        worst = max([g - p.dry_min for g in gaps if g > p.dry_min] or [0.0])
        miss_by_species[p.species] = miss_by_species.get(p.species, 0) + misses

        half = p.dry_min * OVERWATER_SHARE
        over_gaps: Tuple[float, float] = (0.0, 0.0)
        over = False
        if len(gaps) >= 2 and gaps[-1] < half and gaps[-2] < half:
            over = True
            over_gaps = (gaps[-2], gaps[-1])

        if d >= wilt:
            band = WILTED
        elif d >= safe:
            band = PARCHED
        elif d >= safe * WINDOW_SHARE:
            band = DUE
        else:
            band = OK
        readings.append(Reading(p, last if dates else None, never, d,
                                safe, wilt, band, misses, worst, over, over_gaps))

    stats: Dict[str, object] = {
        "cadence": cadence,
        "misses_by_species": miss_by_species,
        "season_factor": factor,
    }
    return readings, stats


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _band_row(r: Reading) -> str:
    name, sp = "%-12s" % r.plant.name[:12], "%-14s" % r.plant.species[:14]
    lines = "safe %sd  wilt %sd" % (fmt_days(r.safe), fmt_days(r.wilt))
    if r.band == WILTED:
        tail = "dry %dd ago · past wilt line by %sd" % (r.days_dry, fmt_days(r.days_dry - r.wilt))
    elif r.band == PARCHED:
        tail = "dry %dd ago · wilt line in %sd (%sd past safe)" % (
            r.days_dry, fmt_days(r.wilt - r.days_dry), fmt_days(r.days_dry - r.safe))
    elif r.band == DUE:
        tail = "dry %dd ago · safe line in %sd" % (r.days_dry, fmt_days(r.safe - r.days_dry))
    else:
        tail = "dry %dd ago · window opens in %sd" % (r.days_dry, fmt_days(r.safe * WINDOW_SHARE - r.days_dry))
    flags = ""
    if r.overwater:
        flags = "  OVERWATER(rot lamp: last gaps %sd,%sd < %sd half-line)" % (
            fmt_days(r.overwater_gaps[0]), fmt_days(r.overwater_gaps[1]),
            fmt_days(r.plant.dry_min * OVERWATER_SHARE))
    if r.never_watered:
        flags += "  NEVER-WATERED since purchase"
    return "  %s %s  %s  %s%s" % (name, sp, lines, tail, flags)


def render_report(shelf: Shelf, as_of: _date, season: Optional[str]) -> str:
    readings, stats = read_shelf_state(shelf, as_of, season)
    cadence = stats["cadence"]
    counts = {b: sum(1 for r in readings if r.band == b) for b in BAND_ORDER}
    out: List[str] = []
    header = "wilting-point · 凋萎点 — as of %s · ledger %d plants · log %d events" % (
        as_of.isoformat(), len(shelf.plants), len(shelf.log))
    if season:
        header += " · season %s (lines ×%g)" % (season, stats["season_factor"])
    out.append(header)
    out.append("")
    out.append("  bands           : " + " · ".join(
        "%d %s" % (counts[b], b) for b in (OK, DUE, PARCHED, WILTED)))

    rot = [r for r in readings if r.overwater]
    if rot:
        out.append("  overwater       : %d flagged — %s (rot kills faster than drought)" % (
            len(rot), ", ".join(r.plant.name for r in rot)))
    else:
        out.append("  overwater       : 0 — no plant is being loved to death")

    if cadence is not None:
        out.append("  cadence         : %sd median gap between your waterings" % fmt_days(cadence))
        tight = [r for r in readings if r.plant.dry_min < cadence]
        out.append("  mismatch        : %d of %d plants have a safe line shorter than your cadence" % (
            len(tight), len(readings)))
        total_misses = sum(r.misses for r in readings)
        neglecting = sorted({r.plant.name for r in readings if r.misses > 0})
        blacklist = sorted(s for s, m in stats["misses_by_species"].items() if m >= BLACKLIST_AT)
        out.append("  neglect ledger  : %d misses on %d plant(s)%s" % (
            total_misses, len(neglecting),
            "" if neglecting else " — a clean record"))
        if blacklist:
            out.append("  blacklist       : %d species (≥%d misses) — stop rebuying: %s" % (
                len(blacklist), BLACKLIST_AT, ", ".join(blacklist)))
        greens = sorted(r.plant.name for r in readings
                        if r.misses == 0 and not r.never_watered
                        and r.band not in (PARCHED, WILTED))
        out.append("  green teammates : %d — %s" % (
            len(greens), ", ".join(greens) if greens else "none yet"))
    else:
        out.append("  cadence         : n/a — no watering gaps on record yet")
        out.append("  mismatch        : n/a")
        out.append("  neglect ledger  : n/a")
        out.append("  green teammates : 0")
    out.append("")

    for band in BAND_ORDER:
        rows = [r for r in readings if r.band == band]
        if not rows:
            continue
        title = {
            WILTED: "WILTED — past the wilting point: damage is no longer reversible",
            PARCHED: "PARCHED — in the damage zone: water today, not tonight",
            DUE: "DUE — the watering window is open",
            OK: "OK — soil still holds",
        }[band]
        out.append(title)
        for r in sorted(rows, key=lambda r: (-(r.days_dry - r.wilt) if band == WILTED
                                             else r.wilt - r.days_dry if band == PARCHED
                                             else r.safe - r.days_dry if band == DUE
                                             else -r.days_dry)):
            out.append(_band_row(r))
        out.append("")

    if counts[WILTED]:
        out.append("verdict: %d plant(s) crossed the wilting point on your watch — "
                   "triage the PARCHED ones today; the wilted are a lesson, not a guilt trip" % counts[WILTED])
    elif counts[PARCHED]:
        out.append("verdict: %d plant(s) in the damage zone — today is a watering day" % counts[PARCHED])
    elif counts[DUE]:
        out.append("verdict: window open on %d plant(s) — water today or put it on the calendar" % counts[DUE])
    else:
        out.append("verdict: all green — your cadence and your shelf agree with each other")
    return "\n".join(out)


def report_json(shelf: Shelf, as_of: _date, season: Optional[str]) -> str:
    readings, stats = read_shelf_state(shelf, as_of, season)
    cadence = stats["cadence"]
    payload = {
        "as_of": as_of.isoformat(),
        "season_factor": stats["season_factor"],
        "cadence": cadence,
        "plants": [
            {
                "name": r.plant.name,
                "species": r.plant.species,
                "dry_min": r.plant.dry_min,
                "dry_max": r.plant.dry_max,
                "acquired": r.plant.acquired,
                "last_watered": r.last_watered,
                "never_watered": r.never_watered,
                "days_dry": r.days_dry,
                "effective": {"safe": r.safe, "wilt": r.wilt},
                "band": r.band,
                "misses": r.misses,
                "worst_overshoot": r.worst_overshoot,
                "overwater": r.overwater,
            }
            for r in readings
        ],
        "blacklist": sorted(s for s, m in stats["misses_by_species"].items() if m >= BLACKLIST_AT),
        "misses_by_species": stats["misses_by_species"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def render_due(shelf: Shelf, as_of: _date, season: Optional[str]) -> str:
    readings, _ = read_shelf_state(shelf, as_of, season)
    rank = {
        WILTED: (0, lambda r: -(r.days_dry - r.wilt)),
        PARCHED: (1, lambda r: (r.wilt - r.days_dry)),
        DUE: (2, lambda r: (r.safe - r.days_dry)),
        OK: (3, lambda r: -(r.days_dry)),
    }
    ordered = sorted(readings, key=lambda r: (rank[r.band][0], rank[r.band][1](r)))
    out = ["wilting-point · due — as of %s · a countdown, not a reminder" % as_of.isoformat()]
    for i, r in enumerate(ordered, 1):
        if r.band == WILTED:
            tail = "past wilt line by %sd" % fmt_days(r.days_dry - r.wilt)
        elif r.band == PARCHED:
            tail = "wilt line in %sd" % fmt_days(r.wilt - r.days_dry)
        elif r.band == DUE:
            tail = "safe line in %sd" % fmt_days(r.safe - r.days_dry)
        else:
            tail = "window opens in %sd" % fmt_days(r.safe * WINDOW_SHARE - r.days_dry)
        out.append("  %2d. %-12s %-8s %s" % (i, r.plant.name[:12], r.band, tail))
    return "\n".join(out)


def render_simulate(shelf: Shelf, as_of: _date, season: Optional[str], trip: int) -> str:
    readings, _ = read_shelf_state(shelf, as_of, season)
    back = as_of + timedelta(days=trip)

    def dies_by(r: Reading, from_day: str) -> str:
        return (_date.fromisoformat(from_day) + timedelta(days=r.wilt)).isoformat()

    nobody = [(r, dies_by(r, r.last_watered or r.plant.acquired)) for r in readings]
    at_risk = sorted([(r, db) for r, db in nobody if _date.fromisoformat(db) <= back],
                     key=lambda t: t[1])
    soak = [r for r in readings if r.wilt <= trip]

    out = ["wilting-point · simulate trip %d — away %s → back %s" % (
        trip, as_of.isoformat(), back.isoformat()), ""]
    out.append("  nobody waters          : %d of %d cross a line before you are back" % (
        len(at_risk), len(readings)))
    for r, db in at_risk:
        already = " already past" if r.band == WILTED else ""
        out.append("    %-12s dies by %s  (safe %sd / wilt %sd)%s" % (
            r.plant.name[:12], db, fmt_days(r.safe), fmt_days(r.wilt), already))
    if soak:
        out.append("  water everything and go: %d of %d still cross — %s" % (
            len(soak), len(readings),
            ", ".join("%s (wilt %sd ≤ trip %dd)" % (r.plant.name[:12], fmt_days(r.wilt), trip)
                      for r in sorted(soak, key=lambda x: x.wilt))))
    else:
        out.append("  water everything and go: 0 of %d — one pre-departure soak covers the whole trip" % len(readings))
    out.append("")
    out.append("  verdict: %s" % (
        ("hand %s to a friend before you leave; everyone else survives one soak"
         % ", ".join(r.plant.name for r in sorted(soak, key=lambda x: x.wilt))) if soak
        else "the trip is survivable: water before you leave and forget the guilt"))
    return "\n".join(out)


def render_advice(shelf: Shelf, as_of: _date, key: str) -> Tuple[str, bool]:
    row = SPECIES_BY_KEY[key]
    _, zh, dry_min, dry_max, note = row
    cadence, _ = profile(shelf)
    out = ["wilting-point · advice — %s (%s, safe %dd / wilt %dd)" % (key, zh, dry_min, dry_max)]
    out.append("  temperament  : %s" % note)
    if cadence is None:
        out.append("  your cadence : n/a — water something for a month first, then ask again")
        return "\n".join(out), False
    out.append("  your cadence : %sd median gap between your waterings" % fmt_days(cadence))
    incompatible = dry_min < cadence
    risky = (not incompatible) and dry_min < cadence * CADENCE_MARGIN
    if incompatible:
        verdict = ("INCOMPATIBLE — its safe line (%dd) is shorter than your natural "
                   "cadence (%sd): your ordinary rhythm is already its drought" % (dry_min, fmt_days(cadence)))
    elif risky:
        verdict = ("RISKY — one late watering puts it in the damage zone "
                   "(safe %dd vs your %sd cadence)" % (dry_min, fmt_days(cadence)))
    else:
        verdict = ("COMPATIBLE — it tolerates your cadence with room to spare "
                   "(safe %dd ≥ 1.5 × %sd); water it on your rhythm and it lives" % (
                       dry_min, fmt_days(cadence)))
    out.append("  verdict      : %s" % verdict)
    evidence = [x for x in read_shelf_state(shelf, as_of, None)[0]
                if x.plant.species == key and x.misses > 0]
    if evidence:
        out.append("  evidence     : your %s already missed its line %d time(s) in your own log"
                   % (evidence[0].plant.name, evidence[0].misses))
    return "\n".join(out), incompatible


def render_species() -> str:
    out = ["wilting-point · species table — days you can forget it (safe / wilt)"]
    for key, zh, mn, mx, note in SPECIES:
        out.append("  %-14s %s  %2dd / %2dd  %s" % (key, zh, mn, mx, note))
    return "\n".join(out)


def render_validate(shelf: Shelf, as_of: _date) -> str:
    never = [p.name for p in shelf.plants if not shelf.log_dates(p.name)]
    single = [p.name for p in shelf.plants if len(shelf.log_dates(p.name)) == 1]
    events = len(shelf.log)
    gaps = sum(len(intervals_of(shelf.log_dates(p.name))) for p in shelf.plants)
    out = ["wilting-point · validate",
           "  plants        : %d" % len(shelf.plants),
           "  log events    : %d (yielding %d gaps)" % (events, gaps),
           "  as_of         : %s (max of ledger/log; --today to override)" % as_of.isoformat(),
           "  never watered : %s" % (", ".join(never) if never else "none"),
           "  single record : %s" % (", ".join(single) if single else "none")]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wilting_point.py",
        description="凋萎点 · Wilting Point — a countdown for every plant you keep forgetting.")
    sub = ap.add_subparsers(dest="cmd")

    def add_common(p, need_paths=True):
        if need_paths:
            p.add_argument("ledger")
            p.add_argument("log")
        p.add_argument("--today", help="override the clock (YYYY-MM-DD)")
        p.add_argument("--season", choices=sorted(SEASON_FACTOR),
                       help="adjust dry lines for transpiration (summer ×0.7, winter ×1.3)")

    p_report = sub.add_parser("report", help="waterline for every plant + your profile")
    add_common(p_report)
    p_report.add_argument("--format", choices=("text", "json"), default="text")
    p_report.add_argument("--fail-wilted", type=int, metavar="K", default=None,
                          help="exit 4 if WILTED >= K")

    p_due = sub.add_parser("due", help="who needs water first, as a countdown")
    add_common(p_due)
    p_due.add_argument("--fail-wilted", type=int, metavar="K", default=None)

    p_sim = sub.add_parser("simulate", help="trip N: who survives your vacation")
    add_common(p_sim)
    p_sim.add_argument("what", choices=("trip",))
    p_sim.add_argument("days", type=int)

    p_adv = sub.add_parser("advice", help="should you buy this species? your log answers")
    p_adv.add_argument("ledger")
    p_adv.add_argument("log")
    p_adv.add_argument("species")
    p_adv.add_argument("--today")

    sub.add_parser("species", help="built-in species table")

    p_val = sub.add_parser("validate", help="ledger + log sanity check")
    p_val.add_argument("ledger")
    p_val.add_argument("log")
    p_val.add_argument("--today")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return EXIT_USAGE
    if args.cmd == "species":
        print(render_species())
        return EXIT_OK

    try:
        return _dispatch(args)
    except LedgerError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_INPUT


def _dispatch(args) -> int:
    shelf = load_shelf(args.ledger, args.log)
    as_of = as_of_date(shelf, args.today)

    if args.cmd == "validate":
        print(render_validate(shelf, as_of))
        return EXIT_OK

    if args.cmd == "due":
        print(render_due(shelf, as_of, args.season))
        if args.fail_wilted is not None:
            readings, _ = read_shelf_state(shelf, as_of, args.season)
            if sum(1 for r in readings if r.band == WILTED) >= args.fail_wilted:
                return EXIT_GATE
        return EXIT_OK

    if args.cmd == "simulate":
        if args.days < 0:
            print("error: trip days must be >= 0", file=sys.stderr)
            return EXIT_USAGE
        print(render_simulate(shelf, as_of, args.season, args.days))
        return EXIT_OK

    if args.cmd == "advice":
        if args.species not in SPECIES_BY_KEY:
            print("error: unknown species %r — pick one of:\n%s"
                  % (args.species, ", ".join(row[0] for row in SPECIES)),
                  file=sys.stderr)
            return EXIT_USAGE
        text, incompatible = render_advice(shelf, as_of, args.species)
        print(text)
        return EXIT_GATE if incompatible else EXIT_OK

    # report
    if args.format == "json":
        print(report_json(shelf, as_of, args.season))
    else:
        print(render_report(shelf, as_of, args.season))
    if args.fail_wilted is not None:
        readings, _ = read_shelf_state(shelf, as_of, args.season)
        if sum(1 for r in readings if r.band == WILTED) >= args.fail_wilted:
            return EXIT_GATE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
