#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contribution-gap — turn "I always do the dishes" into a ledger.

In every shared household, both partners honestly believe they do more:
the two self-reported shares routinely sum to well over 100% (Ross &
Sicoly 1979). Feelings cannot be argued with; a ledger can. This tool
keeps a tiny JSONL chore ledger and answers four questions the argument
never can:

  * shares    — who actually did how much (by minutes, not by guessing)
  * gini      — how unequal the split is, on a 0..1 scale
  * fiefdoms  — chores monopolised by one person even when the total
                looks fair ("she owns the kitchen, he owns the bins")
  * perception— each person's claimed share vs the ledger's measured
                share, and the household's perception surplus

Zero dependencies: Python 3.8+ standard library only.

Exit codes:
  0  report produced
  2  usage error / ledger file missing / malformed CLI values
  3  refusal: nothing to audit (empty ledger, empty window)
  4  gate: --fail-under exceeded (gini above the fairness ceiling)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

DEFAULT_LEDGER = "ledger.jsonl"
ISO = "%Y-%m-%d"

# Monopoly detection: a chore counts as a fiefdom when one person holds
# at least this fraction of its minutes, and the chore has enough total
# minutes to be a real department (not one forgotten 5-minute entry).
MONOPOLY_SHARE = 0.8
MONOPOLY_MIN_MINUTES = 60.0

# Streak detection: same person, most recent entries of one chore.
STREAK_MIN_RUN = 3
STREAK_LOOKBACK = 6

# Perception thresholds (percentage points).
SURPLUS_FLAG = 20.0        # sum of claims minus 100
OVERCLAIM_FLAG = 15.0      # one person's claim minus their actual share

# Trend: the gini of the last 28 days vs the prior 28. Month scale, not
# week scale — a single week without groceries looks like a revolution,
# while a month always contains the whole chore mix.
TREND_DAYS = 28
TREND_MIN_CHORES = 6       # a 28-day half with fewer entries is too thin
TREND_DELTA = 0.05

# Fairness bands for the household gini. Conventions, not laws of nature:
# for two people gini = |2p-1| / 2, so 60/40 -> 0.10 and 70/30 -> 0.20,
# which is where the cut points come from (n > 2 households: the scale
# compresses toward (n-1)/n; read the bands as calibrated for couples).
BAND_BALANCED = 0.10
BAND_TILTED = 0.20


class LedgerError(Exception):
    """Fatal ledger problem (missing file, nothing to audit)."""


@dataclass
class Chore:
    date: dt.date
    person: str
    chore: str
    minutes: float
    note: str
    line: int


@dataclass
class Claim:
    date: dt.date
    person: str
    pct: float
    line: int


# ---------------------------------------------------------------------------
# ledger parsing

def _is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _clean_name(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    name = value.strip().lower()
    return name or None


def _parse_date(value) -> Optional[dt.date]:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.strptime(value.strip(), ISO).date()
    except ValueError:
        return None


def parse_record(obj, line: int):
    """Return a Chore, a Claim, or None when the line is broken."""
    if not isinstance(obj, dict):
        return None
    kind = obj.get("kind")
    date = _parse_date(obj.get("date"))
    person = _clean_name(obj.get("person"))
    if date is None or person is None:
        return None
    if kind == "chore":
        chore = _clean_name(obj.get("chore"))
        minutes = obj.get("minutes")
        if chore is None or not _is_num(minutes) or minutes <= 0:
            return None
        note = obj.get("note", "")
        if not isinstance(note, str):
            note = ""
        return Chore(date, person, chore, float(minutes), note, line)
    if kind == "claim":
        pct = obj.get("pct")
        if not _is_num(pct) or pct < 0 or pct > 100:
            return None
        return Claim(date, person, float(pct), line)
    return None


def load_ledger(path: str) -> Tuple[List[Chore], List[Claim], int]:
    """Read the JSONL ledger. Broken lines are skipped and counted."""
    if not os.path.exists(path):
        raise LedgerError("ledger file not found: %s (log or claim first)" % path)
    chores: List[Chore] = []
    claims: List[Claim] = []
    broken = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, 1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                broken += 1
                continue
            rec = parse_record(obj, line_no)
            if rec is None:
                broken += 1
            elif isinstance(rec, Chore):
                chores.append(rec)
            else:
                claims.append(rec)
    if not chores:
        raise LedgerError(
            "no chore entries in %s — nothing to audit" % path)
    chores.sort(key=lambda c: (c.date, c.line))
    return chores, claims, broken


# ---------------------------------------------------------------------------
# metrics

def gini(values: List[float]) -> float:
    """Gini coefficient of a minute distribution (0 = even, 1 = one person)."""
    vals = sorted(float(v) for v in values)
    n = len(vals)
    total = sum(vals)
    if n < 2 or total <= 0:
        return 0.0
    spread = sum(abs(a - b) for a in vals for b in vals)
    return spread / (2.0 * n * total)


def gini_band(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if value <= BAND_BALANCED:
        return "balanced"
    if value <= BAND_TILTED:
        return "tilted"
    return "lopsided"


def shares_of(chores: List[Chore]) -> List[dict]:
    per: Dict[str, dict] = {}
    for c in chores:
        slot = per.setdefault(c.person, {"person": c.person, "minutes": 0.0,
                                         "chores": 0})
        slot["minutes"] += c.minutes
        slot["chores"] += 1
    total = sum(s["minutes"] for s in per.values()) or 1.0
    rows = sorted(per.values(), key=lambda s: (-s["minutes"], s["person"]))
    for row in rows:
        row["pct"] = round(row["minutes"] / total * 100.0, 1)
    return rows


def monopolies_of(chores: List[Chore]) -> List[dict]:
    per: Dict[str, Dict[str, float]] = {}
    total_per_chore: Dict[str, float] = {}
    counts: Dict[str, Dict[str, int]] = {}
    for c in chores:
        total_per_chore[c.chore] = total_per_chore.get(c.chore, 0.0) + c.minutes
        per.setdefault(c.chore, {})
        per[c.chore][c.person] = per[c.chore].get(c.person, 0.0) + c.minutes
        counts.setdefault(c.chore, {})
        counts[c.chore][c.person] = counts[c.chore].get(c.person, 0) + 1
    items = []
    for chore, total in total_per_chore.items():
        if total < MONOPOLY_MIN_MINUTES:
            continue
        owner, minutes = max(per[chore].items(), key=lambda kv: (kv[1], kv[0]))
        share = minutes / total
        if share >= MONOPOLY_SHARE:
            items.append({
                "chore": chore,
                "owner": owner,
                "share": round(share, 3),
                "minutes": round(minutes, 1),
                "total": round(total, 1),
            })
    items.sort(key=lambda it: (-it["total"], it["chore"]))
    return items


def streaks_of(chores: List[Chore]) -> List[dict]:
    by_chore: Dict[str, List[Chore]] = {}
    for c in chores:
        by_chore.setdefault(c.chore, []).append(c)
    items = []
    for chore, entries in by_chore.items():
        tail = entries[-STREAK_LOOKBACK:]
        if not tail:
            continue
        person = tail[-1].person
        run = 0
        for entry in reversed(tail):
            if entry.person != person:
                break
            run += 1
        if run >= STREAK_MIN_RUN:
            items.append({"chore": chore, "person": person, "run": run,
                          "of": len(tail)})
    items.sort(key=lambda it: (-it["run"], it["chore"]))
    return items


def window_gini(chores: List[Chore], start: dt.date, end: dt.date) -> Optional[float]:
    """Gini of one calendar window; None when the window is too thin."""
    people: Dict[str, float] = {}
    count = 0
    for c in chores:
        if start <= c.date <= end:
            people[c.person] = people.get(c.person, 0.0) + c.minutes
            count += 1
    if count < TREND_MIN_CHORES or len(people) < 2:
        return None
    return round(gini(list(people.values())), 3)


def trend_of(chores: List[Chore], anchor: dt.date) -> dict:
    recent_start = anchor - dt.timedelta(days=TREND_DAYS - 1)
    prior_end = recent_start - dt.timedelta(days=1)
    prior_start = prior_end - dt.timedelta(days=TREND_DAYS - 1)
    recent = window_gini(chores, recent_start, anchor)
    prior = window_gini(chores, prior_start, prior_end)
    if recent is None or prior is None:
        return {"status": "unknown", "recent": recent, "prior": prior,
                "delta": None,
                "reason": "not enough logged days on both sides — each "
                          "28-day half needs >= %d entries from >= 2 people"
                          % TREND_MIN_CHORES}
    delta = round(recent - prior, 3)
    if delta > TREND_DELTA:
        status = "worsening"
    elif delta < -TREND_DELTA:
        status = "improving"
    else:
        status = "flat"
    return {"status": status, "recent": recent, "prior": prior,
            "delta": delta}


def audit_perception(claims: List[Claim], chores: List[Chore]) -> dict:
    """Latest claim per person vs their measured share in the window."""
    latest: Dict[str, Claim] = {}
    for claim in sorted(claims, key=lambda c: (c.date, c.line)):
        latest[claim.person] = claim
    measured = {row["person"]: row["pct"] for row in shares_of(chores)}
    audited, unaudited = [], []
    for person, claim in latest.items():
        if person in measured:
            gap = round(claim.pct - measured[person], 1)
            audited.append({
                "person": person,
                "claim": round(claim.pct, 1),
                "actual": measured[person],
                "gap": gap,
                "overclaim": gap > OVERCLAIM_FLAG,
                "date": claim.date.isoformat(),
            })
        else:
            unaudited.append({
                "person": person,
                "claim": round(claim.pct, 1),
                "date": claim.date.isoformat(),
            })
    audited.sort(key=lambda a: (-a["claim"], a["person"]))
    unaudited.sort(key=lambda a: (-a["claim"], a["person"]))
    surplus = None
    if len(audited) >= 2:
        surplus = round(sum(a["claim"] for a in audited) - 100.0, 1)
    return {"audit": audited, "unaudited": unaudited, "surplus": surplus}


# ---------------------------------------------------------------------------
# report assembly

def build_report(chores: List[Chore], claims: List[Claim], broken: int,
                 window_days: Optional[int] = None) -> dict:
    anchor = max(c.date for c in chores)
    if window_days is not None:
        start = anchor - dt.timedelta(days=window_days - 1)
        window = [c for c in chores if c.date >= start]
        if not window:
            raise LedgerError(
                "no chore entries within the last %d days (anchor %s)"
                % (window_days, anchor.isoformat()))
    else:
        start = None
        window = chores

    rows = shares_of(window)
    persons = [r["person"] for r in rows]
    solo = len(rows) < 2
    gini_value = None if solo else round(gini([r["minutes"] for r in rows]), 3)
    fiefs = [] if solo else monopolies_of(window)
    streaks = streaks_of(window)
    perception = audit_perception(claims, window)
    trend = trend_of(chores, anchor)

    report = {
        "ledger": {"chores": len(chores), "claims": len(claims),
                   "broken": broken},
        "window": {"days": window_days,
                   "start": start.isoformat() if start else None,
                   "end": anchor.isoformat()},
        "shares": rows,
        "gini": {"value": gini_value, "band": gini_band(gini_value),
                 "persons": len(rows)},
        "monopolies": {"threshold": MONOPOLY_SHARE,
                       "min_minutes": MONOPOLY_MIN_MINUTES, "items": fiefs},
        "streaks": {"min_run": STREAK_MIN_RUN, "items": streaks},
        "perception": perception,
        "trend": trend,
    }
    report["red_flags"] = red_flags(report, solo)
    return report


def red_flags(report: dict, solo: bool) -> List[dict]:
    flags: List[dict] = []
    if solo:
        flags.append({
            "code": "SOLE PLAYER",
            "message": "only one person logged chores in this window — "
                       "either the household has one member, or the ledger "
                       "only hears one side",
        })
        return flags

    perception = report["perception"]
    surplus = perception["surplus"]
    if surplus is not None and surplus > SURPLUS_FLAG:
        flags.append({
            "code": "PERCEPTION SURPLUS",
            "message": "claimed shares sum to %.1f%% of one household — the "
                       "self-images do not fit in one reality, so the "
                       "argument is not about chores, it is about which "
                       "household you each live in" % (100.0 + surplus),
        })
    for row in perception["audit"]:
        if row["overclaim"]:
            flags.append({
                "code": "OVERCLAIM",
                "message": "%s claims %s%%, the ledger measures %s%% "
                           "(%s pts) — most likely availability bias, not "
                           "bad faith: frequent visible chores are easier to "
                           "remember than long invisible ones"
                           % (row["person"], fmt_pct(row["claim"]),
                              fmt_pct(row["actual"]), fmt_pts(row["gap"])),
            })

    fiefs = report["monopolies"]["items"]
    if len(fiefs) >= 2:
        detail = ", ".join("%s -> %s" % (f["chore"], f["owner"])
                           for f in fiefs[:4])
        tail = " (and %d more)" % (len(fiefs) - 4) if len(fiefs) > 4 else ""
        masking = ""
        if report["gini"]["value"] is not None \
                and report["gini"]["value"] <= BAND_TILTED:
            masking = " The balanced total is masking it: fair in aggregate, " \
                      "monopolised by department."
        flags.append({
            "code": "FIEFDOM HOUSE",
            "message": "%d chores are >= %d%% in one person's hands: %s%s.%s"
                       % (len(fiefs), int(MONOPOLY_SHARE * 100), detail, tail,
                          masking),
        })

    for streak in report["streaks"]["items"]:
        flags.append({
            "code": "STREAK",
            "message": "%s: last %d sessions in a row by %s — rotation has "
                       "stopped; whoever holds a chore, owns it"
                       % (streak["chore"], streak["run"], streak["person"]),
        })

    trend = report["trend"]
    if trend["status"] == "worsening":
        flags.append({
            "code": "WORSENING TREND",
            "message": "28-day gini drifted from %s to %s — the split is "
                       "diverging, not converging; this is the slide "
                       "arguments usually notice last"
                       % (fmt_g(trend["prior"]), fmt_g(trend["recent"])),
        })
    return flags


# ---------------------------------------------------------------------------
# rendering

def fmt_pct(value: float) -> str:
    return ("%g" % value) if float(value).is_integer() else ("%.1f" % value)


def fmt_pts(value: float) -> str:
    return "%+.1f" % value


def fmt_g(value: Optional[float]) -> str:
    return "n/a" if value is None else "%.3f" % value


def fmt_min(value: float) -> str:
    return "%g" % value if float(value).is_integer() else "%.1f" % value


def render_text(report: dict) -> str:
    out: List[str] = []
    ledger = report["ledger"]
    window = report["window"]
    out.append("contribution gap · household audit")
    out.append("  ledger              : %d chores, %d claims, %d broken lines skipped"
               % (ledger["chores"], ledger["claims"], ledger["broken"]))
    if window["days"] is None:
        out.append("  window              : all time (anchor %s)" % window["end"])
    else:
        out.append("  window              : last %d days (%s .. %s)"
                   % (window["days"], window["start"], window["end"]))

    out.append("")
    out.append("shares (by minutes):")
    for row in report["shares"]:
        out.append("  %-22s: %5s%%  %s min / %d chores"
                   % (row["person"], fmt_pct(row["pct"]),
                      fmt_min(row["minutes"]), row["chores"]))

    out.append("")
    gini = report["gini"]
    if gini["value"] is None:
        out.append("  gini                : n/a — only one person in this "
                   "window, nothing to split")
    else:
        out.append("  gini                : %s  %s"
                   % (fmt_g(gini["value"]), gini["band"]))
    fiefs = report["monopolies"]["items"]
    out.append("  chore monopolies    : %s"
               % ("none — no chore is >= %d%% one person"
                  % int(MONOPOLY_SHARE * 100)
                  if not fiefs else
                  "%d fiefdoms (>= %d%% of a chore in one pair of hands)"
                  % (len(fiefs), int(MONOPOLY_SHARE * 100))))
    for f in fiefs:
        out.append("    %-14s -> %-10s %s%% of %s min"
                   % (f["chore"], f["owner"], fmt_pct(round(f["share"] * 100, 1)),
                      fmt_min(f["total"])))
    streaks = report["streaks"]["items"]
    out.append("  streaks             : %s"
               % ("none — rotation is alive"
                  if not streaks else
                  "; ".join("%s: last %d in a row by %s"
                            % (s["chore"], s["run"], s["person"])
                            for s in streaks)))

    trend = report["trend"]
    if trend["status"] == "unknown":
        out.append("  trend               : unknown — %s" % trend["reason"])
    else:
        out.append("  trend               : %s — 28-day gini %s vs %s (prior 28 days)"
                   % (trend["status"], fmt_g(trend["recent"]),
                      fmt_g(trend["prior"])))

    out.append("")
    out.append("perception audit (latest claim vs the ledger):")
    perception = report["perception"]
    if not perception["audit"] and not perception["unaudited"]:
        out.append("  (no claims on file — run 'claim' to record a self-image)")
    for row in perception["audit"]:
        marker = "   <- overclaim" if row["overclaim"] else ""
        out.append("  %-22s: claims %s%%   actual %s%%   gap %s pts%s"
                   % (row["person"], fmt_pct(row["claim"]),
                      fmt_pct(row["actual"]), fmt_pts(row["gap"]), marker))
    for row in perception["unaudited"]:
        out.append("  %-22s: claims %s%%   actual — (no chores logged in window)"
                   % (row["person"], fmt_pct(row["claim"])))
    if perception["surplus"] is not None:
        out.append("  perception surplus  : %s pts — together you claim %s%% of one household"
                   % (fmt_pts(perception["surplus"]),
                      fmt_pct(100.0 + perception["surplus"])))

    out.append("")
    flags = report["red_flags"]
    if not flags:
        out.append("red flags: none — ledger and self-images basically agree (rare, enjoy it)")
    else:
        out.append("red flags:")
        for flag in flags:
            out.append("  * %s — %s" % (flag["code"], flag["message"]))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contribution_gap",
        description="Household chore ledger: real shares, fairness gini, "
                    "chore monopolies and a perception audit.")
    parser.add_argument("--file", default=DEFAULT_LEDGER,
                        help="ledger path (default: %(default)s)")

    def add_file(p):
        # Accept --file after the subcommand too; SUPPRESS keeps the
        # top-level value when the subcommand omits it.
        p.add_argument("--file", default=argparse.SUPPRESS,
                       help="ledger path (overrides the global --file)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_log = sub.add_parser("log", help="log a chore session")
    add_file(p_log)
    p_log.add_argument("--person", required=True)
    p_log.add_argument("--chore", required=True)
    p_log.add_argument("--minutes", required=True, type=float)
    p_log.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    p_log.add_argument("--note", default="")

    p_claim = sub.add_parser("claim", help="record a self-image: 'I do X%%'")
    add_file(p_claim)
    p_claim.add_argument("--person", required=True)
    p_claim.add_argument("--pct", required=True, type=float)
    p_claim.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    p_claim.add_argument("--note", default="")

    p_rep = sub.add_parser("report", help="audit the ledger")
    add_file(p_rep)
    p_rep.add_argument("--window", type=int, default=None, metavar="DAYS",
                       help="scope shares/gini/monopolies to the last N days")
    p_rep.add_argument("--format", choices=["text", "json"], default="text")
    p_rep.add_argument("--fail-under", dest="fail_under", type=float,
                       default=None, metavar="G",
                       help="exit 4 when the gini exceeds G (fairness gate)")
    return parser


def _resolve_date(raw: Optional[str]) -> dt.date:
    if raw is None:
        return dt.date.today()
    parsed = _parse_date(raw)
    if parsed is None:
        raise ValueError("bad date %r — expected YYYY-MM-DD" % raw)
    return parsed


def _read_counts(path: str) -> Tuple[int, int]:
    try:
        chores, claims, _ = load_ledger(path)
        return len(chores), len(claims)
    except LedgerError:
        return 0, 0


def cmd_log(args) -> int:
    try:
        when = _resolve_date(args.date)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if not _is_num(args.minutes) or args.minutes <= 0:
        print("error: --minutes must be a positive number", file=sys.stderr)
        return 2
    person = _clean_name(args.person)
    chore = _clean_name(args.chore)
    if not person or not chore:
        print("error: --person and --chore must be non-empty", file=sys.stderr)
        return 2
    row = {"kind": "chore", "date": when.isoformat(), "person": person,
           "chore": chore, "minutes": args.minutes}
    if args.note:
        row["note"] = args.note
    with open(args.file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    n_chores, n_claims = _read_counts(args.file)
    print("logged: %s %s %s %s min (ledger now: %d chores, %d claims)"
          % (when.isoformat(), person, chore, fmt_min(args.minutes),
             n_chores, n_claims))
    return 0


def cmd_claim(args) -> int:
    try:
        when = _resolve_date(args.date)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if not _is_num(args.pct) or not 0 <= args.pct <= 100:
        print("error: --pct must be between 0 and 100", file=sys.stderr)
        return 2
    person = _clean_name(args.person)
    if not person:
        print("error: --person must be non-empty", file=sys.stderr)
        return 2
    row = {"kind": "claim", "date": when.isoformat(), "person": person,
           "pct": args.pct}
    if args.note:
        row["note"] = args.note
    with open(args.file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    n_chores, n_claims = _read_counts(args.file)
    print("claimed: %s says they do %s%% of the work (ledger now: %d chores, %d claims)"
          % (person, fmt_pct(args.pct), n_chores, n_claims))
    return 0


def cmd_report(args) -> int:
    if not os.path.exists(args.file):
        print("error: ledger file not found: %s (log or claim first)"
              % args.file, file=sys.stderr)
        return 2
    try:
        chores, claims, broken = load_ledger(args.file)
        report = build_report(chores, claims, broken, args.window)
    except LedgerError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 3
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    if args.fail_under is not None:
        value = report["gini"]["value"]
        if value is not None and value > args.fail_under:
            print("gate: gini %s > fail-under %s"
                  % (fmt_g(value), fmt_g(args.fail_under)), file=sys.stderr)
            return 4
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "log":
        return cmd_log(args)
    if args.command == "claim":
        return cmd_claim(args)
    return cmd_report(args)


if __name__ == "__main__":
    sys.exit(main())
