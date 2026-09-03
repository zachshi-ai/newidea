#!/usr/bin/env python3
"""绝活生锈 · Repertoire Rust.

A freshness ledger for the repertoire that rusts silently: the songs,
pieces and party tricks you once learned and quietly assumed you still
own. Practice time is scarce, so a repertoire always lives on a budget —
learning the new piece starves an old one, and rust makes no sound of
its own until the night you play in front of people.

This tool keeps a plain JSONL practice ledger and turns it into:
  * earned durability — a per-piece half-life that good recalls lengthen
    and botched ones shorten (your own decay curve, not a textbook one)
  * a freshness score with a gig line, and the date each piece drops
    below it
  * a gig gate — what will still be playable on the night (exit 4 when
    the night you booked is not covered)
  * a tonight plan — how to spend a minute budget where rust bites first
  * a keep-alive budget — the minutes/week it costs to hold the whole
    book above the line, and whether you have been paying it

Zero dependency: Python 3.8+ standard library only. Everything local.
"""

import argparse
import json
import math
import os
import sys
from collections import OrderedDict
from datetime import date, timedelta

PROG = "repertoire_rust.py"

# Session kinds. learn = still building the piece; maintain = a rehearsal
# of something already playable; perform = played for real, in front of
# people.
KINDS = ("learn", "maintain", "perform")

# Durability model. Every piece's memory has a half-life h (days): after
# each honest run-through at quality q, h is multiplied by GROWTH[q] —
# fluent recalls earn a longer half-life, botched ones shrink it (the
# piece was rustier than the ledger believed). Performing for real adds
# a consolidation bonus. A new piece starts fragile at H0.
H0 = 7.0
H_MIN, H_MAX = 1.0, 365.0
GROWTH = OrderedDict([(1, 0.5), (2, 0.7), (3, 1.0), (4, 1.3), (5, 1.6)])
PERFORM_BONUS = 1.25
DEFAULT_QUALITY = 3

# Freshness decays 100 -> 50 in h days: F = 100 * 0.5^(gap/h). Bands are
# behavior, not statistics: FRESH means you could take it tonight,
# RUSTING means touch it this week, RUSTED means rebuild territory.
DEFAULT_LINE = 70           # the gig line
DEFAULT_REBUILD_LINE = 40   # below this, maintenance is wasted motion
COLLAPSE_LINE = 60          # a failure above this line is a *surprise*
COLLAPSE_MIN_GAP = 7        # rust needs at least a week to form
COLLAPSE_CAP = 21.0         # a collapse caps durability: the "durable
                            # memory" hypothesis is falsified for now
NO_TOUCH_LINE = 95          # the plan does not polish chrome
FRAGILE_H = 14.0            # fresh but one missed week from gone
PERMA_COLLAPSES = 2         # collapses before "never stuck"

# A piece untouched this long has left the maintained repertoire.
ARCHIVE_DAYS = 180

# Keep-alive budget: cost per touch, and the window actual practice is
# measured over.
DEFAULT_MINUTES = 20
REBUILD_MIN_MINUTES = 30
BUDGET_WINDOW_DAYS = 28


class ParseError(Exception):
    """Ledger cannot be parsed; message is user-facing."""


def plural(n, noun):
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")


def fit(text, width):
    text = str(text)
    return text if len(text) <= width else text[:width - 1] + "…"


def parse_date(text):
    s = str(text).strip()
    normalized = s.replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace(".", "-").replace("/", "-").strip("-")
    parts = [p for p in normalized.split("-") if p != ""]
    if len(parts) == 3:
        try:
            return date(*(int(p) for p in parts))
        except ValueError:
            pass
    raise ParseError("bad date %r (want YYYY-MM-DD)" % text)


def read_ledger(path):
    """Parse a JSONL practice ledger into validated session records."""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            raw_lines = fh.read().splitlines()
    except OSError as exc:
        raise OSError("cannot read ledger: %s" % exc)
    records = []
    for line_no, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ParseError("line %d: not valid JSON (%s)" % (line_no, exc))
        if not isinstance(row, dict):
            raise ParseError("line %d: expected a JSON object" % line_no)
        piece = row.get("piece")
        if not isinstance(piece, str) or not piece.strip():
            raise ParseError("line %d: missing \"piece\"" % line_no)
        if "date" not in row:
            raise ParseError("line %d: missing \"date\"" % line_no)
        try:
            when = parse_date(row["date"])
        except ParseError as exc:
            raise ParseError("line %d: %s" % (line_no, exc))
        kind = row.get("kind")
        if kind not in KINDS:
            raise ParseError("line %d: unknown kind %r (want one of %s)"
                             % (line_no, kind, "/".join(KINDS)))
        quality = row.get("quality", DEFAULT_QUALITY)
        if isinstance(quality, float) and quality.is_integer():
            quality = int(quality)
        if not isinstance(quality, int) or isinstance(quality, bool) \
                or not 1 <= quality <= 5:
            raise ParseError("line %d: quality must be an integer 1-5, got %r"
                             % (line_no, row.get("quality")))
        minutes = row.get("minutes", 0)
        if isinstance(minutes, float) and minutes.is_integer():
            minutes = int(minutes)
        if not isinstance(minutes, int) or isinstance(minutes, bool) \
                or minutes < 0:
            raise ParseError("line %d: minutes must be a non-negative "
                             "integer, got %r" % (line_no, row.get("minutes")))
        records.append({"piece": piece.strip(), "date": when, "kind": kind,
                        "quality": quality, "minutes": minutes,
                        "line_no": line_no})
    if not records:
        raise ParseError("ledger has no records")
    return records


def freshness(h, last, at):
    """Freshness 0-100 of a memory with half-life h last played `last`."""
    if h <= 0:
        return 0.0
    gap = (at - last).days
    if gap <= 0:
        return 100.0
    return 100.0 * math.pow(0.5, gap / float(h))


def half_life_after(h, kind, quality):
    h = h * GROWTH[quality]
    if kind == "perform":
        h *= PERFORM_BONUS
    return min(H_MAX, max(H_MIN, h))


def touch_interval(h, line):
    """Days a piece stays above the line after a touch (100 -> line)."""
    return h * math.log(100.0 / line, 2)


def touch_by(h, last, line):
    return last + timedelta(days=touch_interval(h, line))


def band_of(f, line, rebuild_line):
    if f >= line:
        return "FRESH"
    if f >= rebuild_line:
        return "RUSTING"
    return "RUSTED"


def median(values):
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return float(xs[mid])
    return (xs[mid - 1] + xs[mid]) / 2.0


def replay(records, as_of):
    """Rebuild per-piece state by replaying sessions up to as_of."""
    by_piece = OrderedDict()
    future = 0
    for rec in records:
        if rec["date"] > as_of:
            future += 1
            continue
        by_piece.setdefault(rec["piece"], []).append(rec)

    states = OrderedDict()
    for name in sorted(by_piece, key=str.lower):
        sessions = sorted(by_piece[name], key=lambda r: (r["date"], r["line_no"]))
        h = H0
        last = None
        last_kind = None
        collapses = []
        trace = []
        cost_minutes = []
        total_minutes = 0
        learn_sessions = 0
        for s in sessions:
            gap = (s["date"] - last).days if last else None
            f_before = freshness(h, last, s["date"]) if last else None
            is_collapse = (s["kind"] in ("maintain", "perform")
                           and s["quality"] <= 2
                           and f_before is not None
                           and f_before >= COLLAPSE_LINE
                           and gap >= COLLAPSE_MIN_GAP)
            if is_collapse:
                collapses.append({"date": s["date"], "quality": s["quality"],
                                  "fresh_before": round(f_before),
                                  "half_life_before": round(h, 1)})
            h = half_life_after(h, s["kind"], s["quality"])
            if is_collapse:
                h = min(h, COLLAPSE_CAP)
            if s["kind"] == "learn":
                learn_sessions += 1
            if s["minutes"] > 0 and s["kind"] in ("maintain", "perform"):
                cost_minutes.append(s["minutes"])
            total_minutes += s["minutes"]
            trace.append({"date": s["date"], "kind": s["kind"],
                          "quality": s["quality"], "minutes": s["minutes"],
                          "fresh_before": (None if f_before is None
                                           else round(f_before)),
                          "half_life_after": round(h, 1),
                          "collapse": is_collapse})
            last = s["date"]
            last_kind = s["kind"]
        states[name] = {
            "name": name, "sessions": sessions, "trace": trace,
            "half_life": h, "last": last, "last_kind": last_kind,
            "collapses": collapses, "cost_minutes": cost_minutes,
            "total_minutes": total_minutes, "learn_sessions": learn_sessions,
        }
    return states, future


def touch_cost(state, fallback):
    return median(state["cost_minutes"]) or fallback


def global_cost(states):
    pooled = []
    for st in states.values():
        pooled.extend(st["cost_minutes"])
    return median(pooled) or DEFAULT_MINUTES


def state_view(state, as_of, line, rebuild_line, fallback_cost):
    f = freshness(state["half_life"], state["last"], as_of)
    archived = (as_of - state["last"]).days > ARCHIVE_DAYS
    flags = []
    if len(state["collapses"]) >= PERMA_COLLAPSES:
        flags.append("never stuck (%d collapses)" % len(state["collapses"]))
    elif state["collapses"]:
        flags.append("1 collapse")
    cost = touch_cost(state, fallback_cost)
    return {
        "name": state["name"],
        "fresh": f,
        "fresh_pct": int(round(f)),
        "half_life": state["half_life"],
        "half_life_d": int(round(state["half_life"])),
        "last": state["last"],
        "last_kind": state["last_kind"],
        "touch_by": touch_by(state["half_life"], state["last"], line),
        "interval": touch_interval(state["half_life"], line),
        "cost": cost,
        "rebuild_cost": max(REBUILD_MIN_MINUTES, int(cost * 1.5)),
        "band": band_of(f, line, rebuild_line),
        "archived": archived,
        "collapses": state["collapses"],
        "flags": flags,
    }


def budget_of(states, records, as_of, line):
    required = 0.0
    pooled = []
    active = 0
    fallback = global_cost(states)
    for st in states.values():
        pooled.extend(st["cost_minutes"])
        if (as_of - st["last"]).days > ARCHIVE_DAYS:
            continue
        active += 1
        interval = touch_interval(st["half_life"], line)
        required += touch_cost(st, fallback) * 7.0 / interval
    window_start = as_of - timedelta(days=BUDGET_WINDOW_DAYS - 1)
    actual_sum = sum(r["minutes"] for r in records
                     if window_start <= r["date"] <= as_of)
    actual = actual_sum / (BUDGET_WINDOW_DAYS / 7.0)
    if required <= 0:
        return {"required": 0.0, "actual": actual, "active": 0,
                "ratio": None, "verdict": None}
    ratio = actual / required
    verdict = "underfunded" if ratio < 0.8 else "holding"
    return {"required": required, "actual": actual, "active": active,
            "ratio": ratio, "verdict": verdict}


def build_report(states, future, records, as_of, line, rebuild_line, pinned):
    fallback = global_cost(states)
    views = [state_view(st, as_of, line, rebuild_line, fallback)
             for st in states.values()]
    archived = sorted([v for v in views if v["archived"]],
                      key=lambda v: v["name"].lower())
    active = sorted([v for v in views if not v["archived"]],
                    key=lambda v: (v["fresh"], v["name"].lower()))
    counts = {"FRESH": 0, "RUSTING": 0, "RUSTED": 0}
    for v in active:
        counts[v["band"]] += 1
    perma = [v for v in views if len(v["collapses"]) >= PERMA_COLLAPSES]
    next_to_drop = None
    fresh_views = [v for v in active if v["band"] == "FRESH"]
    if fresh_views:
        candidate = min(fresh_views, key=lambda v: (v["touch_by"],
                                                    v["name"].lower()))
        if candidate["touch_by"] > as_of:
            next_to_drop = {"name": candidate["name"],
                            "date": candidate["touch_by"].isoformat()}
    return {
        "as_of": as_of, "pinned": pinned, "line": line,
        "rebuild_line": rebuild_line, "tracked": len(views),
        "counts": counts, "archived_count": len(archived),
        "items": active, "archived": archived, "perma": perma,
        "first_to_rust": (active[0]["name"] if active else None),
        "next_to_drop": next_to_drop,
        "budget": budget_of(states, records, as_of, line),
        "future_ignored": future,
    }


def build_gig(states, as_of, at, line, rebuild_line):
    fallback = global_cost(states)
    ready, missed = [], []
    for st in states.values():
        v = state_view(st, as_of, line, rebuild_line, fallback)
        if v["archived"]:
            continue
        f_night = freshness(v["half_life"], v["last"], at)
        row = dict(v)
        row["fresh_night"] = f_night
        row["fresh_night_pct"] = int(round(f_night))
        row["ready"] = f_night >= line
        (ready if row["ready"] else missed).append(row)
    ready.sort(key=lambda r: (-r["fresh_night"], r["name"].lower()))
    missed.sort(key=lambda r: (-r["fresh_night"], r["name"].lower()))
    return {"as_of": as_of, "date": at, "line": line,
            "days_out": (at - as_of).days, "ready": ready, "missed": missed}


def build_plan(states, as_of, budget, line, rebuild_line):
    fallback = global_cost(states)
    views = [state_view(st, as_of, line, rebuild_line, fallback)
             for st in states.values()]
    active = [v for v in views if not v["archived"]]
    candidates = sorted([v for v in active if v["fresh"] < NO_TOUCH_LINE],
                        key=lambda v: (v["touch_by"], v["name"].lower()))
    skipped = sorted([v for v in active if v["fresh"] >= NO_TOUCH_LINE],
                     key=lambda v: v["name"].lower())
    steps, deferred = [], []
    used = 0
    rebuilds_taken = 0
    blocked = None
    for v in candidates:
        is_rebuild = v["band"] == "RUSTED"
        if is_rebuild:
            if rebuilds_taken >= 1:
                deferred.append(v["name"])
                continue
            cost = v["rebuild_cost"]
        else:
            cost = v["cost"]
        if used + cost > budget:
            if blocked is None:
                blocked = (v["name"], cost)
            continue
        used += cost
        if is_rebuild:
            rebuilds_taken += 1
        steps.append({"name": v["name"], "kind": "rebuild" if is_rebuild
                      else "maintain", "minutes": cost,
                      "fresh_pct": v["fresh_pct"], "fresh": v["fresh"],
                      "holds": v["interval"],
                      "perma": len(v["collapses"]) >= PERMA_COLLAPSES})
    return {"as_of": as_of, "budget": budget, "used": used,
            "left": budget - used, "steps": steps, "deferred": deferred,
            "skipped": [v["name"] for v in skipped], "blocked": blocked}


def gate_report(gig, need, musts):
    """Evaluate the gig gate; returns (gate text, fail reasons)."""
    reasons = []
    ready_names = {v["name"].lower() for v in gig["ready"]}
    if len(gig["ready"]) < need:
        reasons.append("need %d ready, have %d" % (need, len(gig["ready"])))
    for name in musts:
        if name.lower() not in ready_names:
            reasons.append('must-have "%s" not ready' % name)
    if reasons:
        text = "FAIL — " + " · ".join(reasons)
    else:
        text = "PASS — need %d ready, have %d" % (need, len(gig["ready"]))
        if musts:
            text += " · must-have ok"
    return text, reasons


def find_piece(states, query):
    q = query.strip().lower()
    exact = [st for name, st in states.items() if name.lower() == q]
    if len(exact) == 1:
        return exact[0]
    hits = [st for name, st in states.items() if q in name.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise LookupError("no piece matches %r" % query)
    raise LookupError("ambiguous query %r matches: %s"
                      % (query, ", ".join(s["name"] for s in hits)))


# ---------------------------------------------------------------- renders

def render_fresh_text(rep, args):
    out = []
    c = rep["counts"]
    bits = ["%s" % plural(rep["tracked"] - rep["archived_count"], "active piece"),
            "%d fresh" % c["FRESH"], "%d rusting" % c["RUSTING"],
            "%d rusted" % c["RUSTED"]]
    if rep["archived_count"]:
        bits.append("%d archived" % rep["archived_count"])
    if rep["perma"]:
        bits.append("%d never stuck" % len(rep["perma"]))
    out.append("  repertoire    : %s" % " · ".join(bits))
    out.append("  as of         : %s (%s)" % (rep["as_of"].isoformat(),
               "pinned" if rep["pinned"] else "today"))
    if rep["first_to_rust"]:
        v = rep["items"][0]
        out.append("  first to rust : %s — fresh %d%%, %dd past its touch-by date"
                   % (v["name"], v["fresh_pct"],
                      (rep["as_of"] - v["touch_by"]).days))
    if rep["next_to_drop"]:
        out.append("  next to drop  : %s falls below the %d line on %s"
                   % (rep["next_to_drop"]["name"], rep["line"],
                      rep["next_to_drop"]["date"]))
    if rep["future_ignored"]:
        out.append("  note          : %d session(s) after the as-of date ignored"
                   % rep["future_ignored"])
    out.append("")
    out.append("  %-22s %5s %7s %12s %12s  %s"
               % ("piece", "fresh", "h", "last", "touch-by", "status"))
    for v in rep["items"]:
        marks = {"FRESH": "   ", "RUSTING": "!  ", "RUSTED": "!! "}[v["band"]]
        status = marks + v["band"]
        for flag in v["flags"]:
            status += " · " + flag
        if v["band"] == "FRESH" and v["half_life"] <= FRAGILE_H:
            status += " · fragile (h %dd)" % v["half_life_d"]
        out.append("  %-22s %4d%% %6dd %12s %12s  %s"
                   % (fit(v["name"], 22), v["fresh_pct"], v["half_life_d"],
                      v["last"].isoformat(), v["touch_by"].isoformat(),
                      status))
    for v in rep["archived"]:
        out.append("  · archived (>%dd untouched): %s — last %s"
                   % (ARCHIVE_DAYS, v["name"], v["last"].isoformat()))
    b = rep["budget"]
    out.append("")
    if b["verdict"] is None:
        out.append("  keep-alive budget : nothing active to maintain")
    else:
        out.append("  keep-alive budget : %d min/wk holds %s above the %d line"
                   % (round(b["required"]), plural(b["active"], "piece"),
                      rep["line"]))
        out.append("  actual (last 4wk) : %d min/wk — %s (%d%% of budget)"
                   % (round(b["actual"]), b["verdict"],
                      round(100 * b["ratio"])))
    return "\n".join(out)


def render_gig_text(gig, args):
    out = []
    when = "tonight" if gig["days_out"] == 0 else "%dd out" % gig["days_out"]
    out.append("  gig on %s · %s · line %d"
               % (gig["date"].isoformat(), when, gig["line"]))
    out.append("")
    out.append("  ready on the night (%d):" % len(gig["ready"]))
    for v in gig["ready"]:
        out.append("  ✓ %-22s %3d%% on the night · %3d%% today · half-life %dd"
                   % (fit(v["name"], 22), v["fresh_night_pct"],
                      v["fresh_pct"], v["half_life_d"]))
    if not gig["ready"]:
        out.append("  (nothing)")
    out.append("")
    out.append("  won't make it (%d):" % len(gig["missed"]))
    for v in gig["missed"]:
        note = ""
        if v["fresh_pct"] >= gig["line"]:
            note = " — fresh today is not ready on the night"
        out.append("  ✗ %-22s %3d%% on the night · %3d%% today · half-life %dd%s"
                   % (fit(v["name"], 22), v["fresh_night_pct"],
                      v["fresh_pct"], v["half_life_d"], note))
    if not gig["missed"]:
        out.append("  (nothing)")
    return "\n".join(out)


def render_plan_text(plan, args):
    out = []
    out.append("  tonight · %d min budget · as of %s"
               % (plan["budget"], plan["as_of"].isoformat()))
    out.append("")
    for i, s in enumerate(plan["steps"], 1):
        out.append("  %d. %-22s %-8s %2d min  %3d%% → 100%% · holds ~%dd above the line"
                   % (i, fit(s["name"], 22), s["kind"], s["minutes"],
                      s["fresh_pct"], round(s["holds"])))
        if s["perma"]:
            out.append("       never stuck — slow practice to depth, or retire it")
    if not plan["steps"]:
        out.append("  (nothing to practice — the book is above the line)")
    if plan["deferred"]:
        out.append("")
        out.append("  one rebuild per sitting — deferred: %s"
                   % ", ".join(plan["deferred"]))
    out.append("")
    if plan["left"] > 0:
        tail = "everything else is fresh enough or does not fit"
        if plan["blocked"]:
            tail = "%s needs %d min" % (plan["blocked"][0], plan["blocked"][1])
        elif plan["skipped"]:
            tail = "untouched (fresh ≥ %d): %s" % (NO_TOUCH_LINE,
                   ", ".join("%s" % n for n in plan["skipped"]))
        out.append("  budget left: %d min — %s" % (plan["left"], tail))
    elif plan["skipped"]:
        out.append("  untouched (fresh ≥ %d): %s"
                   % (NO_TOUCH_LINE, ", ".join(plan["skipped"])))
    return "\n".join(out)


def render_show_text(view, args):
    out = []
    st = view["state"]
    v = view["view"]
    marks = {"FRESH": "   ", "RUSTING": "!  ", "RUSTED": "!! "}[v["band"]]
    status = "%s%s · fresh %d%% · half-life %dd" % (marks, v["band"],
                                                    v["fresh_pct"],
                                                    v["half_life_d"])
    if len(st["collapses"]) >= PERMA_COLLAPSES:
        status += " · never stuck (%d collapses)" % len(st["collapses"])
    elif st["collapses"]:
        status += " · 1 collapse"
    out.append("  %s" % st["name"])
    out.append("  status: %s" % status)
    out.append("  hold above the %d line: touch every ~%dd (~%d min a touch)"
               % (args.line, round(v["interval"]), v["cost"]))
    out.append("")
    out.append("  %-12s %-8s %2s %4s %8s %13s  %s"
               % ("date", "kind", "q", "min", "h-after", "fresh-before",
                  "note"))
    for t in st["trace"]:
        note = "← COLLAPSE (ledger said %d%%, hands said no)" % t["fresh_before"] \
            if t["collapse"] else ""
        out.append("  %-12s %-8s %2d %4d %8.1f %13s  %s"
                   % (t["date"].isoformat(), t["kind"], t["quality"],
                      t["minutes"], t["half_life_after"],
                      ("—" if t["fresh_before"] is None
                       else "%d%%" % t["fresh_before"]), note))
    return "\n".join(out)


def _iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else d


def render_fresh_json(rep, args):
    def row(v):
        return {"name": v["name"], "fresh_pct": v["fresh_pct"],
                "half_life": round(v["half_life"], 1), "last": _iso(v["last"]),
                "touch_by": _iso(v["touch_by"]), "band": v["band"],
                "flags": v["flags"], "collapses": len(v["collapses"])}
    payload = {
        "as_of": _iso(rep["as_of"]), "pinned": rep["pinned"],
        "line": rep["line"], "rebuild_line": rep["rebuild_line"],
        "tracked": rep["tracked"], "counts": rep["counts"],
        "archived_count": rep["archived_count"],
        "first_to_rust": rep["first_to_rust"],
        "next_to_drop": rep["next_to_drop"],
        "items": [row(v) for v in rep["items"]],
        "archived": [row(v) for v in rep["archived"]],
        "perma": [v["name"] for v in rep["perma"]],
        "budget": {k: (round(x, 1) if isinstance(x, float) else x)
                   for k, x in rep["budget"].items()},
        "future_ignored": rep["future_ignored"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_gig_json(gig, args):
    def row(v):
        return {"name": v["name"], "today_pct": v["fresh_pct"],
                "night_pct": v["fresh_night_pct"], "ready": v["ready"],
                "half_life": round(v["half_life"], 1)}
    return json.dumps({
        "as_of": _iso(gig["as_of"]), "date": _iso(gig["date"]),
        "days_out": gig["days_out"], "line": gig["line"],
        "ready": [row(v) for v in gig["ready"]],
        "missed": [row(v) for v in gig["missed"]],
    }, ensure_ascii=False, indent=2)


def render_plan_json(plan, args):
    return json.dumps({
        "as_of": _iso(plan["as_of"]), "budget": plan["budget"],
        "used": plan["used"], "left": plan["left"],
        "steps": [{"name": s["name"], "kind": s["kind"],
                   "minutes": s["minutes"], "fresh_pct": s["fresh_pct"],
                   "holds_days": round(s["holds"], 1), "perma": s["perma"]}
                  for s in plan["steps"]],
        "deferred": plan["deferred"], "skipped": plan["skipped"],
        "blocked": ({"name": plan["blocked"][0],
                     "minutes": plan["blocked"][1]} if plan["blocked"] else None),
    }, ensure_ascii=False, indent=2)


def render_show_json(view, args):
    st = view["state"]
    v = view["view"]
    return json.dumps({
        "name": st["name"], "fresh_pct": v["fresh_pct"],
        "half_life": round(st["half_life"], 1), "band": v["band"],
        "last": _iso(st["last"]), "touch_by": _iso(v["touch_by"]),
        "collapses": [{"date": _iso(c["date"]), "quality": c["quality"],
                       "fresh_before": c["fresh_before"]}
                      for c in st["collapses"]],
        "sessions": [{"date": _iso(t["date"]), "kind": t["kind"],
                      "quality": t["quality"], "minutes": t["minutes"],
                      "fresh_before": t["fresh_before"],
                      "half_life_after": t["half_life_after"],
                      "collapse": t["collapse"]} for t in st["trace"]],
    }, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------- CLI

def build_parser():
    ap = argparse.ArgumentParser(
        prog=PROG, description="绝活生锈 · Repertoire Rust — a freshness "
        "ledger for the repertoire that rusts silently.")
    sub = ap.add_subparsers(dest="cmd", metavar="{fresh,gig,plan,show}")
    sub.required = True

    def common(p):
        p.add_argument("ledger", help="practice ledger (JSONL)")
        p.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                       help="evaluate as of this date (default: today)")
        p.add_argument("--line", type=int, default=DEFAULT_LINE,
                       help="gig line, 1-99 (default %d)" % DEFAULT_LINE)
        p.add_argument("--rebuild-line", type=int,
                       default=DEFAULT_REBUILD_LINE,
                       help="below this a piece is rebuild territory "
                            "(default %d)" % DEFAULT_REBUILD_LINE)
        p.add_argument("--format", choices=("text", "json"), default="text")

    pf = sub.add_parser("fresh", help="freshness ranking of the repertoire")
    common(pf)

    pg = sub.add_parser("gig", help="what survives to the gig date")
    common(pg)
    pg.add_argument("--date", required=True, metavar="YYYY-MM-DD",
                    help="the night it matters")
    pg.add_argument("--need", type=int, default=0, metavar="N",
                    help="gate: fail unless at least N pieces are ready")
    pg.add_argument("--must", action="append", default=[], metavar="NAME",
                    help="gate: this piece must be ready (repeatable)")

    pp = sub.add_parser("plan", help="tonight's practice, minute-budgeted")
    common(pp)
    pp.add_argument("--minutes", type=int, default=45, metavar="N",
                    help="practice budget in minutes (default 45)")

    ps = sub.add_parser("show", help="one piece's full session history")
    common(ps)
    ps.add_argument("piece", help="piece name (exact or unique substring)")
    return ap


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if not (1 <= args.line <= 99):
            parser.error("--line must be 1-99")
        if not (1 <= args.rebuild_line <= 99):
            parser.error("--rebuild-line must be 1-99")
        if args.rebuild_line >= args.line:
            parser.error("--rebuild-line must be below --line")
        if args.cmd == "plan" and not (5 <= args.minutes <= 600):
            parser.error("--minutes must be 5-600")
        if args.cmd == "gig" and args.need < 0:
            parser.error("--need must be >= 0")

        if args.as_of is None:
            as_of = date.today()
            pinned = False
        else:
            try:
                as_of = parse_date(args.as_of)
            except ParseError:
                print("%s: error: bad --as-of %r" % (PROG, args.as_of),
                      file=sys.stderr)
                return 3
            pinned = True

        records = read_ledger(args.ledger)
        states, future = replay(records, as_of)

        if args.cmd == "fresh":
            rep = build_report(states, future, records, as_of, args.line,
                               args.rebuild_line, pinned)
            text = (render_fresh_json(rep, args) if args.format == "json"
                    else render_fresh_text(rep, args))
            print(text)
            return 0

        if args.cmd == "gig":
            gig_date = parse_date(args.date)
            if args.must:
                resolved = []
                for name in args.must:
                    try:
                        resolved.append(find_piece(states, name)["name"])
                    except LookupError as exc:
                        print("%s: error: must-have %s" % (PROG, exc),
                              file=sys.stderr)
                        return 3
                args.must = resolved
            gig = build_gig(states, as_of, gig_date, args.line,
                            args.rebuild_line)
            if args.format == "json":
                print(render_gig_json(gig, args))
            else:
                print(render_gig_text(gig, args))
            if args.need or args.must:
                gate, reasons = gate_report(gig, args.need, args.must)
                print("")
                print("  gate: %s" % gate)
                return 4 if reasons else 0
            return 0

        if args.cmd == "plan":
            plan = build_plan(states, as_of, args.minutes, args.line,
                              args.rebuild_line)
            print(render_plan_json(plan, args) if args.format == "json"
                  else render_plan_text(plan, args))
            return 0

        if args.cmd == "show":
            try:
                st = find_piece(states, args.piece)
            except LookupError as exc:
                print("%s: error: %s" % (PROG, exc), file=sys.stderr)
                return 3
            fallback = global_cost(states)
            view = {"state": st,
                    "view": state_view(st, as_of, args.line,
                                       args.rebuild_line, fallback)}
            print(render_show_json(view, args) if args.format == "json"
                  else render_show_text(view, args))
            return 0

        parser.error("unknown command")
    except ParseError as exc:
        print("%s: error: %s" % (PROG, exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print("%s: error: %s" % (PROG, exc), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
