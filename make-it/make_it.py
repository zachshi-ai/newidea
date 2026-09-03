#!/usr/bin/env python3
"""来得及 · Make It.

A distribution ledger for the daily commute. Commute time is not a
duration, it is a distribution — and the navigation app's "40 min" is a
median, not a promise. Whoever leaves the door budgeting the median has
pre-ordered roughly a coin flip on being late. This tool keeps one row
per commute (date, route, depart, arrive, target) and turns the pile
into five honest answers:

  * stats    - per-route portrait: P50/P80/P90/worst duration, on-time
               rate, close calls, and the late-departure inflation
               (what leaving 15+ minutes later actually costs).
  * now      - "if I walk out now, do I make it?" — the empirical
               probability of on-time arrival on this route at this
               departure window, with SAFE / RISKY / DEAD verdicts.
  * leave    - the inverse: "when is the last departure that still
               makes 09:00 at my confidence bar?" — solved against the
               route's own distribution, window closed reported honestly.
  * routes   - routes ranked at your punctile quantile (default P80),
               not the mean, so the flashy-fast-but-jittery route
               finally loses to the boring steady one.
  * late     - the lateness ledger: repeat offenders by route x weekday,
               close calls, and how concentrated your lateness really is.
  * simulate - what leaving N minutes earlier would have changed over
               the observed span, annualized.

Verdicts are refused, not faked: a route with fewer than MIN_NOW_N
trips exits 3 (THIN) instead of inventing a probability.

Zero dependency: Python 3.8+ standard library only. Everything stays
local; --as-of / --at pin the clock so reports replay byte for byte.
"""

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, timedelta

PROG = "make_it.py"

# Confidence bar for "on time" (empirical share of historical durations
# that fit the remaining time). --want raises or lowers the bar.
DEFAULT_WANT = 0.90
# A route needs at least this many trips before a probability verdict is
# honest; below it the tool refuses (exit 3) instead of inventing one.
MIN_NOW_N = 8
# Route x departure-window buckets below this fall back to route-only
# durations (and say so in the report).
MIN_BUCKET_N = 5
# A route tagged THIN below this many trips in ranking tables.
DEFAULT_MIN_N = 10
# Arrival margins in [0, CLOSE_CALL_MIN] minutes count as close calls.
CLOSE_CALL_MIN = 5
# simulate: if the post-shift lateness rate is still at/above this, the
# honest advice is "earlier alone will not fix it" (advisory exit 4).
LATE_RATE_RED = 0.10
# stats: departures from this clock on split the window used for the
# late-departure inflation line (--peak-split moves it).
DEFAULT_PEAK_SPLIT = "08:15"
DEFAULT_QUANTILE = 0.80

# The two departure windows every comparison is made in. Hand-edited
# ledgers are dense around the morning peak and thin elsewhere; five
# bands would be five rumors, two windows are two samples.
EARLY = "before split"
LATE = "from split"

VERDICTS = {
    "SAFE": 0,
    "RISKY": 4,
    "DEAD": 5,
    "THIN": 3,
}

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

DATE_ALIASES = {"date", "day", "日期"}
ROUTE_ALIASES = {"route", "line", "路线", "线路"}
DEPART_ALIASES = {"depart", "departure", "leave", "出发", "出门"}
ARRIVE_ALIASES = {"arrive", "arrival", "到达", "到"}
TARGET_ALIASES = {"target", "deadline", "by", "目标", "应到", "打卡"}


class ParseError(ValueError):
    """Bad ledger row or bad argument; maps to exit 2."""


def parse_clock(text, what="time"):
    """'08:31' -> minutes since midnight. Strict HH:MM."""
    parts = text.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() and len(p) == 2 for p in parts):
        raise ParseError("%s must be HH:MM (24h), got %r" % (what, text))
    h, m = int(parts[0]), int(parts[1])
    if h > 23 or m > 59:
        raise ParseError("%s out of range: %r" % (what, text))
    return h * 60 + m


def fmt_clock(minutes):
    minutes = int(round(minutes))
    return "%02d:%02d" % (minutes // 60 % 24, minutes % 60)


def fmt_min(minutes, signed=False):
    minutes = int(round(minutes))
    if signed and minutes > 0:
        return "+%dm" % minutes
    return "%dm" % minutes


def fmt_pct(x):
    return "n/a" if x is None else "%.1f%%" % (100.0 * x)


def parse_date(text):
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ParseError("date must be YYYY-MM-DD, got %r" % text)


def quantile(values, q):
    """Nearest-rank quantile on an ascending list. q=0.5 -> P50."""
    if not values:
        raise ValueError("quantile of empty list")
    idx = max(0, math.ceil(q * len(values)) - 1)
    return values[min(idx, len(values) - 1)]


def median(values):
    return quantile(sorted(values), 0.5)


def read_ledger(path):
    """Read the commute CSV into row dicts; validate aggressively."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ParseError("empty ledger: %s" % path)
        headers = {h.strip().lower(): h for h in reader.fieldnames}

        def col(aliases):
            for a in aliases:
                if a in headers:
                    return headers[a]
            return None

        c_date, c_route = col(DATE_ALIASES), col(ROUTE_ALIASES)
        c_dep, c_arr = col(DEPART_ALIASES), col(ARRIVE_ALIASES)
        c_tgt = col(TARGET_ALIASES)
        missing = [name for name, c in (("date", c_date), ("route", c_route),
                                        ("depart", c_dep), ("arrive", c_arr))
                   if c is None]
        if missing:
            raise ParseError("ledger is missing columns: %s"
                             % ", ".join(missing))

        rows = []
        for lineno, raw in enumerate(reader, start=2):
            if not any((v or "").strip() for v in raw.values()):
                continue  # blank line
            d = parse_date(raw[c_date])
            route = (raw[c_route] or "").strip()
            if not route:
                raise ParseError("row %d: empty route" % lineno)
            dep = parse_clock(raw[c_dep], "depart (row %d)" % lineno)
            arr = parse_clock(raw[c_arr], "arrive (row %d)" % lineno)
            if arr <= dep:
                raise ParseError(
                    "row %d: arrive (%s) must be after depart (%s); "
                    "same-day trips only — the ledger is not a night bus"
                    % (lineno, raw[c_arr], raw[c_dep]))
            tgt_text = (raw.get(c_tgt) or "").strip() if c_tgt else ""
            tgt = parse_clock(tgt_text, "target (row %d)" % lineno) \
                if tgt_text else None
            rows.append({
                "date": d,
                "weekday": WEEKDAYS[d.weekday()],
                "route": route,
                "depart": dep,
                "arrive": arr,
                "target": tgt,
                "duration": arr - dep,
                "timed": tgt is not None,
                "margin": (tgt - arr) if tgt is not None else None,
            })
    if not rows:
        raise ParseError("ledger has no data rows: %s" % path)
    return rows


def routes_in(rows):
    return sorted({r["route"] for r in rows})


def route_rows(rows, route):
    return [r for r in rows if r["route"] == route]


def durations(rows):
    return sorted(r["duration"] for r in rows)


def depart_window(depart, split_min):
    return EARLY if depart < split_min else LATE


def window_durations(rrows, split_min, window):
    return sorted(r["duration"] for r in rrows
                  if depart_window(r["depart"], split_min) == window)


def window_label(window, split_min):
    edge = fmt_clock(split_min)
    return ("departures from %s" if window == LATE
            else "departures before %s") % edge


def duration_source(rrows, depart_min, q, split_min):
    """Route-level quantile refined by the departure window when the
    window bucket has enough samples. One refinement pass, deterministic.

    Returns (minutes, n, source_label)."""
    all_d = durations(rrows)
    base = quantile(all_d, q)
    window = depart_window(depart_min, split_min)
    bucket = window_durations(rrows, split_min, window)
    if len(bucket) >= MIN_BUCKET_N:
        return (quantile(bucket, q), len(bucket),
                window_label(window, split_min))
    return base, len(all_d), "route overall (window bucket thin)"


def p_on_time(rrows, depart_min, remaining, split_min):
    """Empirical P(duration <= remaining). The share IS the quantile:
    P = 62% means the time you have is your P62 commute."""
    all_d = durations(rrows)
    window = depart_window(depart_min, split_min)
    bucket = window_durations(rrows, split_min, window)
    if len(bucket) >= MIN_BUCKET_N:
        pool = bucket
        label = window_label(window, split_min)
    else:
        pool, label = all_d, "route overall (window bucket thin)"
    p = sum(1 for d in pool if d <= remaining) / float(len(pool))
    return p, len(pool), label, pool


def on_time_stats(rows):
    timed = [r for r in rows if r["timed"]]
    n = len(timed)
    if not n:
        return None
    late = sum(1 for r in timed if r["margin"] < 0)
    close = sum(1 for r in timed if 0 <= r["margin"] <= CLOSE_CALL_MIN)
    return {"n": n, "late": late, "close": close,
            "on_time_rate": (n - late) / float(n)}


def ledger_header(rows, as_of):
    routes = routes_in(rows)
    timed = sum(1 for r in rows if r["timed"])
    span = "%s .. %s" % (min(r["date"] for r in rows).isoformat(),
                         max(r["date"] for r in rows).isoformat())
    return ("-- Make It: commute distribution ledger (as of %s)\n"
            "  ledger    : %d commutes · %d routes · %s · %d timed\n"
            % (as_of.isoformat(), len(rows), len(routes), span, timed))


def require_route(rows, route):
    known = routes_in(rows)
    if route not in known:
        raise ParseError("unknown route %r (ledger has: %s)"
                         % (route, ", ".join(known)))
    return route_rows(rows, route)


# ---------------------------------------------------------------- stats

def stats_report(rows, as_of, route, min_n, split_min):
    if route:
        selected = [(route, require_route(rows, route))]
    else:
        selected = [(name, route_rows(rows, name)) for name in routes_in(rows)]
    per_route = []
    for name, rrows in selected:
        d = durations(rrows)
        ot = on_time_stats(rrows)
        early = window_durations(rrows, split_min, EARLY)
        late_w = window_durations(rrows, split_min, LATE)
        inflation = None
        if len(early) >= MIN_BUCKET_N and len(late_w) >= MIN_BUCKET_N:
            inflation = median(late_w) / float(median(early)) - 1.0
        per_route.append({
            "route": name,
            "n": len(rrows),
            "p50": median(d),
            "p80": quantile(d, 0.8),
            "p90": quantile(d, 0.9),
            "worst": max(d),
            "on_time": ot,
            "split_min": split_min,
            "early_n": len(early),
            "early_median": median(early) if early else None,
            "late_n": len(late_w),
            "late_median": median(late_w) if late_w else None,
            "inflation": inflation,
            "thin": len(rrows) < min_n,
        })
    return {"rows": per_route, "as_of": as_of,
            "route": route, "min_n": min_n, "split_min": split_min}


def render_stats_text(rep, rows):
    split = fmt_clock(rep["split_min"])
    lines = [ledger_header(rows, rep["as_of"]).rstrip("\n")]
    lines.append("")
    lines.append("  route          n   P50   P80   P90  worst  on-time  close")
    for r in rep["rows"]:
        ot = r["on_time"]
        lines.append("  %-13s %3d %4sm %4sm %4sm %5sm  %7s  %5s%s"
                     % (r["route"], r["n"], r["p50"], r["p80"], r["p90"],
                        r["worst"],
                        fmt_pct(ot["on_time_rate"]) if ot else "n/a",
                        ot["close"] if ot else "-",
                        "  (thin: n=%d < %d)" % (r["n"], rep["min_n"])
                        if r["thin"] else ""))
        if r["inflation"] is not None:
            lines.append("    ^ departures before vs from %s: median %dm (n=%d)"
                         " vs %dm (n=%d) — leaving later costs %+.1f%%"
                         % (split, r["early_median"], r["early_n"],
                            r["late_median"], r["late_n"],
                            100.0 * r["inflation"]))
    thin = [r for r in rep["rows"] if r["thin"]]
    if thin:
        lines.append("  thin routes: %s — their numbers are portraits, not verdicts"
                     % ", ".join(r["route"] for r in thin))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ now

def now_report(rows, as_of, route, at, by, want, split_min):
    rrows = require_route(rows, route)
    n = len(rrows)
    if n < MIN_NOW_N:
        return {"verdict": "THIN", "code": VERDICTS["THIN"], "route": route,
                "n": n, "need": MIN_NOW_N, "at": at, "by": by,
                "as_of": as_of, "want": want}
    remaining = by - at
    if remaining <= 0:
        return {"verdict": "DEAD", "code": VERDICTS["DEAD"], "route": route,
                "n": n, "at": at, "by": by, "remaining": remaining,
                "late": by - at, "expected_late": by - at,
                "as_of": as_of, "want": want,
                "note": "the deadline has already passed — this is no "
                        "longer about the commute"}
    p, src_n, label, pool = p_on_time(rrows, at, remaining, split_min)
    worst = max(pool)
    base = {"route": route, "n": n, "at": at, "by": by, "remaining": remaining,
            "p": p, "source": label, "src_n": src_n, "worst": worst,
            "as_of": as_of, "want": want}
    if p >= want:
        base.update(verdict="SAFE", code=VERDICTS["SAFE"],
                    slack=remaining - worst)
        return base
    if p >= 0.5:
        base.update(verdict="RISKY", code=VERDICTS["RISKY"],
                    shortfall=worst - remaining)
        return base
    p50 = median(pool)
    expected_late = at + p50 - by
    base.update(verdict="DEAD", code=VERDICTS["DEAD"],
                expected_late=max(0, expected_late))
    return base


def render_now_text(rep, rows):
    head = ledger_header(rows, rep["as_of"]).rstrip("\n")
    q = rep["route"]
    if rep["verdict"] == "THIN":
        return (head + "\n"
                "  now       : %s — only %d trips on record (need %d)\n"
                "  verdict   : THIN (exit 3) — a probability over %d trips is\n"
                "              invention, not statistics. Log more commutes first.\n"
                % (q, rep["n"], rep["need"], rep["n"]))
    if rep["remaining"] <= 0:
        return (head + "\n"
                "  now       : leave %s, arrive by %s — you are %s past the target\n"
                "  verdict   : DEAD (exit 5) — %s\n"
                % (fmt_clock(rep["at"]), fmt_clock(rep["by"]),
                   fmt_min(-rep["remaining"]), rep["note"]))
    line1 = ("  now       : leave %s, arrive by %s on %s — %s of margin left\n"
             % (fmt_clock(rep["at"]), fmt_clock(rep["by"]), rep["route"],
                fmt_min(rep["remaining"])))
    line2 = ("  evidence  : P(on time) = %.0f%% over %s (n=%d) — the margin you have\n"
             "              is your P%.0f ride; worst day on record %s\n"
             % (100.0 * rep["p"], rep["source"], rep["src_n"],
                100.0 * rep["p"], fmt_min(rep["worst"])))
    if rep["verdict"] == "SAFE":
        verdict = ("  verdict   : SAFE (exit 0) — even your worst recorded day fits,\n"
                   "              with %s to spare. Walk.\n" % fmt_min(rep["slack"]))
    elif rep["verdict"] == "RISKY":
        verdict = ("  verdict   : RISKY (exit 4) — the median day fits, your worst day\n"
                   "              overruns by %s. At P%.0f you lose this bet %s of weeks.\n"
                   % (fmt_min(rep["shortfall"]), 100.0 * rep["p"],
                      "1 in 2" if rep["p"] < 0.75 else "1 in 4"))
    else:
        verdict = ("  verdict   : DEAD (exit 5) — the median day already misses by %s.\n"
                   "              Reschedule, warn ahead, or accept the lateness.\n"
                   % fmt_min(rep["expected_late"]))
    return head + "\n" + line1 + line2 + verdict


# ---------------------------------------------------------------- leave

def leave_report(rows, as_of, route, by, want, at, split_min):
    rrows = require_route(rows, route)
    n = len(rrows)
    if n < MIN_NOW_N:
        return {"verdict": "THIN", "code": VERDICTS["THIN"], "route": route,
                "n": n, "need": MIN_NOW_N, "by": by, "want": want,
                "as_of": as_of, "at": at}
    # Solve for the departure whose own window reproduces it: start from
    # the route-wide quantile, refine against the departure window, and
    # iterate. Windows are discrete, so the iteration can oscillate
    # (early P90 sends you later, which lands in the late window whose
    # P90 sends you earlier); when there is no fixed point within three
    # passes, take the earliest candidate — the conservative answer.
    all_d = durations(rrows)
    dur = quantile(all_d, want)
    label = "route overall (window bucket thin)"
    src_n = len(all_d)
    leave_by = by - dur
    candidates = []
    for _ in range(3):
        window = depart_window(leave_by, split_min)
        bucket = window_durations(rrows, split_min, window)
        if len(bucket) >= MIN_BUCKET_N:
            dur = quantile(bucket, want)
            label = window_label(window, split_min)
            src_n = len(bucket)
        else:
            dur = quantile(all_d, want)
            label = "route overall (window bucket thin)"
            src_n = len(all_d)
        leave_by = by - dur
        candidates.append((leave_by, dur, label, src_n))
        if depart_window(leave_by, split_min) == window:
            break
    else:
        leave_by, dur, label, src_n = min(candidates)
    rep = {"route": route, "by": by, "want": want, "at": at, "as_of": as_of,
           "duration": dur, "source": label, "src_n": src_n,
           "leave_by": leave_by, "budget": by - leave_by,
           "verdict": "GO", "code": 0}
    if at is not None and at > leave_by:
        p50_now, _, _ = duration_source(rrows, at, 0.5, split_min)
        rep.update(verdict="CLOSED", code=VERDICTS["DEAD"],
                   expected_late=max(0, at + p50_now - by), p50_now=p50_now)
    return rep


def render_leave_text(rep, rows):
    head = ledger_header(rows, rep["as_of"]).rstrip("\n")
    if rep["verdict"] == "THIN":
        return (head + "\n"
                "  leave     : %s — only %d trips on record (need %d)\n"
                "  verdict   : THIN (exit 3) — no departure line is honest over %d trips\n"
                % (rep["route"], rep["n"], rep["need"], rep["n"]))
    lines = [head, ""]
    lines.append("  target    : arrive by %s on %s at P%.0f confidence"
             % (fmt_clock(rep["by"]), rep["route"], 100.0 * rep["want"]))
    lines.append("  solve     : leave at %s — budget %s (%s ride, %s, n=%d)"
             % (fmt_clock(rep["leave_by"]), fmt_min(rep["budget"]),
                fmt_min(rep["duration"]), rep["source"], rep["src_n"]))
    if rep["verdict"] == "GO":
        if rep["at"] is not None:
            lines.append("  verdict   : GO (exit 0) — it is %s now, %s of margin"
                         % (fmt_clock(rep["at"]),
                            fmt_min(rep["leave_by"] - rep["at"])))
        else:
            lines.append("  verdict   : GO (exit 0) — later than this and you are gambling")
    else:
        lines.append("  verdict   : WINDOW CLOSED (exit 5) — it is %s; leaving now\n"
                     "              arrives %s at the median (%s late). Warn, reschedule,\n"
                     "              or accept it: the ledger cannot stop the clock."
                     % (fmt_clock(rep["at"]), fmt_clock(rep["at"] + rep["p50_now"]),
                        fmt_min(rep["expected_late"], signed=True)))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- routes

def routes_report(rows, as_of, q, min_n):
    per = []
    for name in routes_in(rows):
        rrows = route_rows(rows, name)
        d = durations(rrows)
        ot = on_time_stats(rrows)
        per.append({"route": name, "n": len(rrows),
                    "p50": median(d), "q": quantile(d, q), "worst": max(d),
                    "on_time_rate": ot["on_time_rate"] if ot else None,
                    "thin": len(rrows) < min_n})
    per.sort(key=lambda r: (r["q"], r["route"]))
    crown = next((r["route"] for r in per if not r["thin"]), None)
    return {"rows": per, "q": q, "min_n": min_n, "as_of": as_of,
            "crown": crown}


def render_routes_text(rep, rows):
    label = "P%d" % round(rep["q"] * 100)
    lines = [ledger_header(rows, rep["as_of"]).rstrip("\n"), ""]
    lines.append("  ranked by %s duration — the mean hides jitter, the %s does not"
                 % (label, label))
    lines.append("")
    lines.append("  route          n   P50    %s  worst  on-time" % label)
    for r in rep["rows"]:
        mark = ""
        if rep["crown"] and r["route"] == rep["crown"]:
            mark = "  <- proven steadiest at %s" % label
        elif r["thin"]:
            mark = "  (thin: n=%d < %d, never crowned)" % (r["n"], rep["min_n"])
        lines.append("  %-13s %3d %4sm  %4sm %5sm  %7s%s"
                     % (r["route"], r["n"], r["p50"], r["q"], r["worst"],
                        fmt_pct(r["on_time_rate"]), mark))
    if rep["crown"] is None:
        lines.append("  no route is proven yet — every line is thin; collect samples first")
    else:
        lines.append("  the mean can flatter a jittery route: rank at your real bar, not at luck")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------- late

def late_report(rows, as_of):
    timed = [r for r in rows if r["timed"]]
    late = [r for r in timed if r["margin"] < 0]
    close = [r for r in timed if 0 <= r["margin"] <= CLOSE_CALL_MIN]
    by_route, by_weekday = [], []
    for name in routes_in(rows):
        sub = [r for r in timed if r["route"] == name]
        if not sub:
            continue
        lates = [r for r in sub if r["margin"] < 0]
        by_route.append({
            "route": name, "n": len(sub), "late": len(lates),
            "rate": len(lates) / float(len(sub)) if sub else None,
            "median_late": median([-r["margin"] for r in lates]) if lates else None,
            "worst": max([-r["margin"] for r in lates]) if lates else None,
        })
    for i, wd in enumerate(WEEKDAYS):
        sub = [r for r in timed if r["date"].weekday() == i]
        if not sub:
            continue
        lates = sum(1 for r in sub if r["margin"] < 0)
        by_weekday.append({"weekday": wd, "n": len(sub), "late": lates,
                           "rate": lates / float(len(sub))})
    offender, share = None, 0.0
    if late:
        combos = {}
        for r in late:
            key = (r["route"], r["weekday"])
            combos[key] = combos.get(key, 0) + 1
        best = max(sorted(combos.items()), key=lambda kv: kv[1])
        offender, share = "%s on %s" % (best[0][0], best[0][1]), \
            best[1] / float(len(late))
    return {"as_of": as_of, "n_timed": len(timed), "late_n": len(late),
            "close_n": len(close),
            "late_rate": len(late) / float(len(timed)) if timed else None,
            "by_route": by_route, "by_weekday": by_weekday,
            "offender": offender, "offender_share": share}


def render_late_text(rep, rows):
    lines = [ledger_header(rows, rep["as_of"]).rstrip("\n"), ""]
    lines.append("  late      : %d late trips in %d timed (%s) · %d close calls"
             % (rep["late_n"], rep["n_timed"], fmt_pct(rep["late_rate"]),
                rep["close_n"]))
    lines.append("")
    lines.append("  route          n  late   rate  median-late  worst")
    for r in rep["by_route"]:
        lines.append("  %-13s %3d   %3d  %6s  %11s  %5s"
                     % (r["route"], r["n"], r["late"], fmt_pct(r["rate"]),
                        fmt_min(r["median_late"]) if r["median_late"] is not None
                        else "-",
                        fmt_min(r["worst"]) if r["worst"] is not None else "-"))
    lines.append("")
    lines.append("  weekday        n  late   rate")
    for r in rep["by_weekday"]:
        lines.append("  %-13s %3d   %3d  %6s"
                     % (r["weekday"], r["n"], r["late"], fmt_pct(r["rate"])))
    lines.append("")
    if rep["offender"]:
        lines.append("  repeat offender : %s — %d%% of all lateness (%.0f%% share)"
                     % (rep["offender"], round(100.0 * rep["offender_share"]),
                        100.0 * rep["offender_share"]))
        lines.append("  lateness is not weather, it is a schedule: fix the one combo first")
    else:
        lines.append("  no late trips on record — the ledger has nothing to confess")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- simulate

def simulate_report(rows, as_of, earlier, route, split_min=None):
    timed = [r for r in rows if r["timed"]]
    if route:
        rrows = require_route(rows, route)
        timed = [r for r in rrows if r["timed"]]
    n = len(timed)
    if not n:
        raise ParseError("no timed commutes to simulate" +
                         (" on route %r" % route if route else ""))

    def summarize(ms):
        late = [m for m in ms if m < 0]
        return {"n": n, "late": len(late),
                "on_time_rate": (n - len(late)) / float(n),
                "late_minutes": sum(-m for m in late)}
    before = summarize([r["margin"] for r in timed])
    after = summarize([r["margin"] + earlier for r in timed])
    span = (max(r["date"] for r in timed) - min(r["date"] for r in timed)).days + 1
    factor = 365.25 / span
    rep = {"as_of": as_of, "earlier": earlier, "n": n,
           "span_days": span, "before": before, "after": after,
           "annual_late_trips_before": before["late"] * factor,
           "annual_late_trips_after": after["late"] * factor,
           "annual_late_minutes_before": before["late_minutes"] * factor,
           "annual_late_minutes_after": after["late_minutes"] * factor}
    rep["code"] = VERDICTS["RISKY"] if after["late"] / float(n) >= LATE_RATE_RED else 0
    return rep


def render_simulate_text(rep, rows):
    head = ledger_header(rows, rep["as_of"]).rstrip("\n")
    b, a = rep["before"], rep["after"]
    lines = [head, ""]
    lines.append("  counterfactual : every timed commute leaves %d minutes earlier (n=%d, %d days)"
                 % (rep["earlier"], rep["n"], rep["span_days"]))
    lines.append("")
    lines.append("                 before   after")
    lines.append("  on-time      %6s  %6s" % (fmt_pct(b["on_time_rate"]),
                                             fmt_pct(a["on_time_rate"])))
    lines.append("  late trips   %6d  %6d" % (b["late"], a["late"]))
    lines.append("  late minutes %6d  %6d" % (b["late_minutes"], a["late_minutes"]))
    lines.append("")
    lines.append("  annualized    : %.0f -> %.0f late trips a year, %.0f -> %.0f late minutes"
                 % (rep["annual_late_trips_before"], rep["annual_late_trips_after"],
                    rep["annual_late_minutes_before"], rep["annual_late_minutes_after"]))
    if rep["code"] == VERDICTS["RISKY"]:
        lines.append("  verdict       : STILL LATE (exit 4) — even %d earlier minutes leave a %.0f%%\n"
                     "                  lateness rate; the problem is the route or the bar, not the clock"
                     % (rep["earlier"], 100.0 * a["late"] / float(a["n"])))
    else:
        lines.append("  verdict       : FIXED BY CLOCK (exit 0) — %d minutes of earlier alarm buys this much year"
                     % rep["earlier"])
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- render json

# rep fields that hold minutes-since-midnight; JSON renders them HH:MM
CLOCK_JSON_KEYS = ("at", "by", "leave_by")


def to_json(rep):
    def clean(o, key=None):
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, dict):
            return {k: clean(v, k) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        if key in CLOCK_JSON_KEYS and isinstance(o, int):
            return fmt_clock(o)
        return o
    return json.dumps(clean(rep), indent=2) + "\n"


# ------------------------------------------------------------------ main

def add_common(ap, needs_at=False):
    ap.add_argument("ledger", help="commute CSV (date,route,depart,arrive[,target])")
    ap.add_argument("--as-of", type=parse_date, default=date.today(),
                    help="pin 'today' for a byte-reproducible report")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    if needs_at:
        ap.add_argument("--at", type=parse_clock, required=True,
                        help="your clock right now, HH:MM (pins the verdict)")


def build_parser():
    ap = argparse.ArgumentParser(prog=PROG, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("stats", help="per-route distribution portrait")
    s.add_argument("--route")
    s.add_argument("--min-n", type=int, default=DEFAULT_MIN_N)
    s.add_argument("--peak-split", type=parse_clock, default=parse_clock(DEFAULT_PEAK_SPLIT))
    add_common(s)

    s = sub.add_parser("now", help="if I walk out now, do I make it?")
    s.add_argument("--route", required=True)
    s.add_argument("--by", type=parse_clock, required=True)
    s.add_argument("--want", type=float, default=DEFAULT_WANT)
    s.add_argument("--peak-split", type=parse_clock, default=parse_clock(DEFAULT_PEAK_SPLIT))
    add_common(s, needs_at=True)

    s = sub.add_parser("leave", help="last departure that still makes it")
    s.add_argument("--route", required=True)
    s.add_argument("--by", type=parse_clock, required=True)
    s.add_argument("--want", type=float, default=DEFAULT_WANT)
    s.add_argument("--peak-split", type=parse_clock, default=parse_clock(DEFAULT_PEAK_SPLIT))
    s.add_argument("--at", type=parse_clock, default=None,
                   help="check the window against this clock (optional)")
    add_common(s)

    s = sub.add_parser("routes", help="rank routes at a punctile quantile")
    s.add_argument("--quantile", type=float, default=DEFAULT_QUANTILE)
    s.add_argument("--min-n", type=int, default=DEFAULT_MIN_N)
    add_common(s)

    s = sub.add_parser("late", help="the lateness ledger")
    add_common(s)

    s = sub.add_parser("simulate", help="what leaving N minutes earlier changes")
    s.add_argument("--earlier", type=int, required=True)
    s.add_argument("--route")
    add_common(s)
    return ap


def run(args):
    rows = read_ledger(args.ledger)
    as_of = args.as_of
    if args.cmd == "stats":
        rep = stats_report(rows, as_of, args.route, args.min_n, args.peak_split)
        text = render_stats_text(rep, rows)
    elif args.cmd == "now":
        if not 0.5 < args.want <= 1.0:
            raise ParseError("--want must be in (0.5, 1.0]")
        rep = now_report(rows, as_of, args.route, args.at, args.by,
                         args.want, args.peak_split)
        text = render_now_text(rep, rows)
    elif args.cmd == "leave":
        if not 0.5 < args.want <= 1.0:
            raise ParseError("--want must be in (0.5, 1.0]")
        rep = leave_report(rows, as_of, args.route, args.by, args.want,
                           args.at, args.peak_split)
        text = render_leave_text(rep, rows)
    elif args.cmd == "routes":
        if not 0.5 <= args.quantile <= 0.99:
            raise ParseError("--quantile must be in [0.5, 0.99]")
        rep = routes_report(rows, as_of, args.quantile, args.min_n)
        text = render_routes_text(rep, rows)
    elif args.cmd == "late":
        rep = late_report(rows, as_of)
        text = render_late_text(rep, rows)
    elif args.cmd == "simulate":
        if args.earlier <= 0:
            raise ParseError("--earlier must be a positive number of minutes")
        rep = simulate_report(rows, as_of, args.earlier, args.route)
        text = render_simulate_text(rep, rows)
    else:
        raise ParseError("unknown command %r" % args.cmd)
    return rep, text


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd is None:
        build_parser().print_help()
        return 2
    try:
        rep, text = run(args)
    except ParseError as exc:
        print("%s: error: %s" % (PROG, exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(to_json(rep), end="")
    else:
        print(text, end="")
    return rep.get("code", 0)


if __name__ == "__main__":
    sys.exit(main())
