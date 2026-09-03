#!/usr/bin/env python3
"""渐行渐远 · Drift Apart.

A decay ledger for the friendships that fail silently: no alarm rings when a
friendship cools — the dates between conversations just keep stretching. This
tool keeps two plain ledgers (a roster of who matters, and an interaction
log of every real two-way contact), then measures, per relation:

  * arrears   — days past *your own* cadence for that circle (inner 30 /
                close 90 / active 180 / outer 365), not past a universal guilt
  * slope     — whether the gaps between contacts are stretching (growth =
                last gap vs. the median before it); lengthening is the leading
                indicator, it fires half a year before "we haven't talked
                since March" becomes true
  * balance   — the unilateral index: if you initiated ~all of the last K
                contacts, the relation stops the moment you stop
  * occasions — birthdays are the one rehearsal-free door: miss it and the
                next one is a year away

It ranks who is drifting farthest, prints a repair list (who to reach out to
today, birthday doors first), and files a full dossier per person. Reaching
out stays a human decision; the ledger only refuses to stay silent.

Zero dependency: Python 3.8+ standard library only. Everything stays local —
a friendships ledger is the most sensitive file you will ever keep.
"""

import argparse
import csv
import hashlib
import json
import sys
import unicodedata
from collections import Counter, OrderedDict
from datetime import date, timedelta

PROG = "drift_apart.py"

# Per-circle cadence: the longest natural gap before "we're overdue" — the
# rhythm of that circle, not a universal guilt clock. Rows may override via a
# cadence column; --circle-cadence overrides these.
DEFAULT_CADENCES = OrderedDict([
    ("inner", 30),
    ("close", 90),
    ("active", 180),
    ("outer", 365),
])
CIRCLE_ALIASES = {
    "inner": "inner", "core": "inner", "核心": "inner",
    "close": "close", "亲密": "close",
    "active": "active", "有效": "active",
    "outer": "outer", "社交": "outer",
}
CIRCLE_RANK = {"inner": 0, "close": 1, "active": 2, "outer": 3}
CIRCLE_LABEL = {"inner": "inner 核心", "close": "close 亲密",
                "active": "active 有效", "outer": "outer 社交"}

# elapsed / cadence → band. The multiples are deliberately *your own* rhythm:
# OVERDUE means one cadence missed (a nudge is enough), DRIFTING means the
# conversation now needs a reason, GONE means the silence has outlived your
# rhythm four times over — reopening it needs an occasion, not a message.
BANDS = OrderedDict([
    ("FRESH", 1.0),
    ("OVERDUE", 2.0),
    ("DRIFTING", 4.0),
    ("GONE", None),
])

# Unilateral index over the last K contacts: fraction you initiated.
UNILATERAL_K = 5
UNILATERAL_THRESHOLD = 0.8

# Silence slope: last gap vs. the median of the gaps before it.
SLOPE_SAMPLES = 2          # need >= 2 gaps (3 contacts) to speak
SLOPE_STRETCH = 2.0        # growth >= 2  → LENGTHENING
SLOPE_WARM = 0.5           # growth <= .5 → WARMING

OCCASION_WINDOW = 7        # days ahead a birthday becomes a repair door

NAME_ALIASES = {"name", "who", "姓名", "名字", "朋友"}
CIRCLE_ALIASES_H = {"circle", "ring", "圈层", "圈子", "层"}
BIRTHDAY_ALIASES = {"birthday", "bday", "生日"}
CADENCE_ALIASES = {"cadence", "rhythm", "节奏", "周期"}
IDATE_ALIASES = {"date", "when", "日期", "时间", "哪天"}
INIT_ALIASES = {"initiator", "by", "from", "发起者", "发起人", "谁发起"}


class ParseError(Exception):
    """Ledger cannot be parsed; message is user-facing."""


def plural(n, noun):
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")


def redact(text):
    return "anon-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def disp_width(text):
    """Terminal cell width so CJK names align with ASCII ones."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in text)


def pad(text, width):
    return text + " " * max(0, width - disp_width(text))


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
    if len(parts) == 1 and len(parts[0]) == 8 and parts[0].isdigit():
        try:
            return date(int(parts[0][:4]), int(parts[0][4:6]), int(parts[0][6:8]))
        except ValueError:
            pass
    raise ParseError("unrecognized date: %r" % text)


def parse_monthday(text):
    """A yearly occasion: MM-DD (year optional, and irrelevant)."""
    s = str(text).strip()
    normalized = s.replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace(".", "-").replace("/", "-").strip("-")
    parts = [p for p in normalized.split("-") if p != ""]
    if len(parts) == 2:
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            pass
    try:
        d = parse_date(text)
        return (d.month, d.day)
    except ParseError:
        pass
    raise ParseError("unrecognized birthday (want MM-DD or a full date): %r" % text)


def next_occasion(monthday, as_of):
    """Days until the next occurrence of a (month, day) from as_of."""
    month, day = monthday
    for year in (as_of.year, as_of.year + 1):
        try:
            cand = date(year, month, day)
        except ValueError:               # Feb 29 — celebrate Mar 1
            cand = date(year, 3, 1)
        if cand >= as_of:
            return cand
    return None                            # unreachable


def _clean_header(cell):
    return str(cell or "").strip().lstrip("\ufeff").strip().lower()


def _find_header(rows, needed, optional):
    """Locate the header row holding all `needed` column aliases."""
    best = None
    for idx, cells in enumerate(rows[:50]):
        lowered = [_clean_header(c) for c in cells]
        found = {}
        for i, h in enumerate(lowered):
            for key, aliases in list(optional.items()) + list(needed.items()):
                if key not in found and h in aliases:
                    found[key] = i
        if all(k in found for k in needed):
            best = (idx, found)
            break
    if best is None:
        raise ParseError(
            "no header row found: need %s columns (%s); optional: %s" % (
                " + ".join(sorted(needed)),
                "; ".join("%s: %s" % (k, "/".join(sorted(v)[:3]))
                          for k, v in sorted(needed.items())),
                "; ".join("%s: %s" % (k, "/".join(sorted(v)[:2]))
                          for k, v in sorted(optional.items()))))
    return best


def read_csv_rows(path, needed, optional):
    """Shared CSV reader: sniff the header, map aliases, keep line numbers."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            raw = list(csv.reader(fh))
    except OSError as exc:
        raise ParseError("cannot read %s: %s" % (path, exc))
    except UnicodeDecodeError:
        raise ParseError("%s is not valid UTF-8" % path)
    rows = [r for r in raw if any(str(c).strip() for c in r)]
    if not rows:
        raise ParseError("%s: no data rows" % path)
    header_idx, cols = _find_header(rows, needed, optional)
    out = []
    for lineno, cells in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        row = {}
        for key, idx in cols.items():
            row[key] = (cells[idx].strip()
                        if idx is not None and idx < len(cells) else "")
        row["line"] = lineno
        out.append(row)
    return out


def read_roster(path):
    """Parse the roster CSV: one row per relation."""
    rows = read_csv_rows(path, {"name": NAME_ALIASES, "circle": CIRCLE_ALIASES_H},
                         {"birthday": BIRTHDAY_ALIASES, "cadence": CADENCE_ALIASES})
    roster = OrderedDict()
    for row in rows:
        name = row["name"]
        if not name:
            raise ParseError("%s line %d: name is empty" % (path, row["line"]))
        circle_raw = row["circle"].lower()
        circle = CIRCLE_ALIASES.get(circle_raw)
        if circle is None:
            raise ParseError(
                "%s line %d: unknown circle %r (want one of %s)" % (
                    path, row["line"], row["circle"],
                    "/".join(DEFAULT_CADENCES)))
        if name in roster:
            raise ParseError("%s line %d: duplicate name %r" % (path, row["line"], name))
        cadence = None
        if row.get("cadence"):
            try:
                cadence = int(row["cadence"])
            except ValueError:
                raise ParseError("%s line %d: cadence must be an integer, got %r" % (
                    path, row["line"], row["cadence"]))
            if cadence <= 0:
                raise ParseError("%s line %d: cadence must be positive" % (
                    path, row["line"]))
        birthday = None
        if row.get("birthday"):
            try:
                birthday = parse_monthday(row["birthday"])
            except ParseError as exc:
                raise ParseError("%s line %d: %s" % (path, row["line"], exc))
        roster[name] = {
            "name": name, "circle": circle, "cadence": cadence,
            "birthday": birthday, "line": row["line"],
        }
    if not roster:
        raise ParseError("%s: header found but no data rows" % path)
    return roster


def read_interactions(path):
    """Parse the interactions CSV: one row per real two-way contact."""
    rows = read_csv_rows(path, {"name": NAME_ALIASES, "date": IDATE_ALIASES,
                                "initiator": INIT_ALIASES}, {})
    interactions = {}
    for row in rows:
        name = row["name"]
        if not name:
            raise ParseError("%s line %d: name is empty" % (path, row["line"]))
        try:
            when = parse_date(row["date"])
        except ParseError as exc:
            raise ParseError("%s line %d: %s" % (path, row["line"], exc))
        init_raw = row["initiator"].lower()
        initiator = {"me": "me", "them": "them", "我": "me", "对方": "them"}.get(init_raw)
        if initiator is None:
            raise ParseError("%s line %d: unknown initiator %r (want me/them/我/对方)" % (
                path, row["line"], row["initiator"]))
        interactions.setdefault(name, []).append(
            {"date": when, "initiator": initiator, "line": row["line"]})
    for name, events in interactions.items():
        events.sort(key=lambda e: e["date"])
    return interactions


def resolve_cadence(person, circle_overrides):
    if person["cadence"] is not None:
        return person["cadence"]
    if person["circle"] in circle_overrides:
        return circle_overrides[person["circle"]]
    return DEFAULT_CADENCES[person["circle"]]


def median(values):
    vs = sorted(values)
    n = len(vs)
    mid = n // 2
    return vs[mid] if n % 2 else (vs[mid - 1] + vs[mid]) / 2.0


def silence_slope(events):
    """growth = last gap vs. median of the gaps before it.

    A lengthening gap is the leading indicator of drift: it fires while the
    ledger still looks merely "overdue", months before the silence itself
    becomes historic.
    """
    if len(events) < SLOPE_SAMPLES + 1:
        return {"slope": "UNKNOWN", "growth": None,
                "median_gap": None, "last_gap": None}
    dates = [e["date"] for e in events]
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    prefix = median(gaps[:-1])
    growth = (gaps[-1] / prefix) if prefix > 0 else None
    if growth is None:
        slope = "UNKNOWN"
    elif growth >= SLOPE_STRETCH:
        slope = "LENGTHENING"
    elif growth <= SLOPE_WARM:
        slope = "WARMING"
    else:
        slope = "STEADY"
    return {"slope": slope, "growth": growth,
            "median_gap": prefix, "last_gap": gaps[-1]}


def unilateral_index(events):
    """Fraction of the last K contacts that you initiated."""
    if len(events) < 2:
        return None
    recent = events[-UNILATERAL_K:]
    mine = sum(1 for e in recent if e["initiator"] == "me")
    return mine / float(len(recent))


def band_of(ratio):
    for name, upper in BANDS.items():
        if upper is None or ratio <= upper:
            return name
    return "GONE"


# Ledger ordering severity: how much attention a band demands. NEVER has no
# history to weigh, so it sinks below every band that has one.
SORT_RANK = {"GONE": 4, "DRIFTING": 3, "OVERDUE": 2, "FRESH": 1, "NEVER": 0}


def build_relation(person, events, as_of, circle_overrides):
    events = sorted(events or [], key=lambda e: e["date"])
    cadence = resolve_cadence(person, circle_overrides)
    relation = {
        "name": person["name"],
        "circle": person["circle"],
        "cadence": cadence,
        "birthday": person["birthday"],
        "contacts": len(events),
        "first": events[0]["date"] if events else None,
        "last_contact": events[-1]["date"] if events else None,
        "events": events,
    }
    if not events:
        relation.update({"elapsed": None, "ratio": None, "arrears": None,
                         "band": "NEVER", "slope": silence_slope(events),
                         "unilateral": unilateral_index(events),
                         "days_to_occasion": None})
        return relation
    elapsed = (as_of - events[-1]["date"]).days
    ratio = elapsed / float(cadence)
    relation.update({
        "elapsed": elapsed,
        "ratio": ratio,
        "arrears": elapsed - cadence,
        "band": band_of(ratio),
        "slope": silence_slope(events),
        "unilateral": unilateral_index(events),
    })
    if person["birthday"]:
        nxt = next_occasion(person["birthday"], as_of)
        relation["days_to_occasion"] = (nxt - as_of).days if nxt else None
    else:
        relation["days_to_occasion"] = None
    return relation


def load_ledger(roster_path, interactions_path, as_of, circle_overrides):
    roster = read_roster(roster_path)
    interactions = read_interactions(interactions_path)
    ghosts = sorted(set(interactions) - set(roster))
    if ghosts:
        raise ParseError(
            "interactions mention people absent from the roster: %s — add them "
            "to %s first (a ledger of unregistered contacts is not a ledger)" % (
                ", ".join(ghosts), roster_path))
    relations = [build_relation(p, interactions.get(n), as_of, circle_overrides)
                 for n, p in roster.items()]
    # Most drifted first: GONE above OVERDUE above FRESH; NEVER (no history
    # to weigh) sinks below everything.
    relations.sort(key=lambda r: (-SORT_RANK[r["band"]],
                                  -(r["ratio"] if r["ratio"] is not None else -1.0),
                                  CIRCLE_RANK[r["circle"]], r["name"]))
    counts = Counter(r["band"] for r in relations)
    return {"roster_path": roster_path, "interactions_path": interactions_path,
            "as_of": as_of, "relations": relations, "counts": counts,
            "tracked": len(relations)}


# ---------------------------------------------------------------------------
# repair list
# ---------------------------------------------------------------------------

REPAIR_ADVICE = {
    "NEVER": "on the roster but never contacted — first words need a reason, pick one",
    "GONE": "silence this old needs an occasion (a birthday, a shared memory) — a bare 'hi' will stall",
    "DRIFTING": "the conversation needs a reason now — bring one specific thing you'd have told them anyway",
    "OVERDUE": "one message is enough — a nudge inside your rhythm reopens it",
    "FRESH": "fresh — nothing to repair",
}


def occasion_flag(relation):
    dt = relation["days_to_occasion"]
    return dt is not None and dt <= OCCASION_WINDOW and relation["band"] != "FRESH"


def repair_list(report, within):
    due = [r for r in report["relations"] if r["band"] != "FRESH"]
    doors, rest = [], []
    for r in due:
        (doors if occasion_flag(r) else rest).append(r)
    doors.sort(key=lambda r: (r["days_to_occasion"],
                              -(r["ratio"] or 0.0), CIRCLE_RANK[r["circle"]]))
    rest.sort(key=lambda r: (-(r["ratio"] or 0.0), CIRCLE_RANK[r["circle"]], r["name"]))
    ordered = doors + rest
    return ordered[:within] if within is not None else ordered


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

BAND_MARKS = {
    "NEVER": "?? NEVER",
    "GONE": "!! GONE",
    "DRIFTING": "! DRIFTING",
    "OVERDUE": "~ OVERDUE",
    "FRESH": "OK FRESH",
}

SLOPE_MARKS = {
    "LENGTHENING": "⚠",   # gaps stretching — leading indicator
    "UNILATERAL": "↺",    # you carry every conversation
    "OCCASION": "★",      # birthday door open
}


def relation_flags(relation):
    flags = ""
    if relation["slope"]["slope"] == "LENGTHENING":
        flags += SLOPE_MARKS["LENGTHENING"]
    if relation["unilateral"] is not None and \
            relation["unilateral"] >= UNILATERAL_THRESHOLD:
        flags += SLOPE_MARKS["UNILATERAL"]
    if occasion_flag(relation):
        flags += SLOPE_MARKS["OCCASION"]
    return flags


def days_label(n):
    if n is None:
        return "—"
    return "%+dd" % n if n < 0 else "%dd" % n


def render_ledger_text(report, args):
    out = []
    counts = report["counts"]
    out.append("-- Drift Apart ledger: %s (as of %s)" % (
        report["roster_path"], report["as_of"].isoformat()))
    out.append("  relations     : %s" % plural(report["tracked"], "relation"))
    out.append("  bands         : %d fresh · %d overdue · %d drifting · %d gone · %d never contacted" % (
        counts["FRESH"], counts["OVERDUE"], counts["DRIFTING"],
        counts["GONE"], counts["NEVER"]))
    stretching = [r for r in report["relations"]
                  if r["slope"]["slope"] == "LENGTHENING"]
    carrying = [r for r in report["relations"]
                if r["unilateral"] is not None and
                r["unilateral"] >= UNILATERAL_THRESHOLD]
    out.append("  signals       : %d stretching gaps (⚠) · %d unilateral (↺) · %d birthday door open (★)" % (
        len(stretching), len(carrying),
        sum(1 for r in report["relations"] if occasion_flag(r))))
    drifted = [r for r in report["relations"] if r["band"] != "FRESH"]
    worst = max(drifted, key=lambda r: (SORT_RANK[r["band"]],
                                        r["ratio"] or 0.0)) if drifted else None
    if worst:
        worst_name = redact(worst["name"]) if args.redact else worst["name"]
        if worst["band"] == "NEVER":
            head = "%s (never contacted — decide: reach out or take off the roster)" % worst_name
        else:
            head = "%s (silent %s · %.1f× your %dd rhythm)" % (
                worst_name, days_label(worst["elapsed"]),
                worst["ratio"], worst["cadence"])
        out.append("  farthest gone : %s" % head)
    out.append("")

    header = "  %-16s %-13s %10s %7s %8s  %s" % (
        "name", "circle", "last", "cadence", "silent", "band")
    out.append(header)
    for r in report["relations"]:
        if args.circle and r["circle"] != args.circle:
            continue
        name = r["name"]
        if args.redact:
            name = redact(name)
        row = "  %s %s %10s %7s %8s  %s%s" % (
            pad(name, 16), pad(CIRCLE_LABEL[r["circle"]], 13),
            r["last_contact"].isoformat() if r["last_contact"] else "—",
            "%dd" % r["cadence"],
            days_label(r["elapsed"]),
            BAND_MARKS[r["band"]], relation_flags(r))
        out.append(row)
    return "\n".join(out)


def render_repair_text(report, args, ordered):
    out = []
    out.append("-- Drift Apart repair list: %s (as of %s)" % (
        report["roster_path"], report["as_of"].isoformat()))
    if not ordered:
        out.append("  every relation is inside its rhythm — nothing to repair")
        out.append("  gate: PASS")
        return "\n".join(out)
    doors = [r for r in ordered if occasion_flag(r)]
    if doors:
        out.append("  birthday doors open now (miss one and the next is a year away):")
        for r in doors:
            out.append("  ★ %s — birthday in %dd" % (r["name"], r["days_to_occasion"]))
        out.append("")
    out.append("  today's order (birthday doors first, then farthest gone):")
    for r in ordered:
        name = redact(r["name"]) if args.redact else r["name"]
        marks = relation_flags(r)
        out.append("  %s %-16s %s · silent %s · %s" % (
            BAND_MARKS[r["band"]][:2].strip(), pad(name, 16),
            CIRCLE_LABEL[r["circle"]], days_label(r["elapsed"]),
            REPAIR_ADVICE[r["band"]]))
        if marks:
            why = []
            if "⚠" in marks:
                why.append("gaps stretching (%.1f× the old median)" %
                           r["slope"]["growth"])
            if "↺" in marks:
                recent_n = min(UNILATERAL_K, r["contacts"])
                why.append("you initiated %d of the last %d" % (
                    round((r["unilateral"] or 0.0) * recent_n), recent_n))
            if why:
                out.append("      ↳ %s" % "; ".join(why))
    out.append("  gate: FAIL — %s still outside their rhythm" % plural(len(ordered), "relation"))
    return "\n".join(out)


def render_show_text(relation, report, args):
    out = []
    name = redact(relation["name"]) if args.redact else relation["name"]
    out.append("-- Drift Apart dossier: %s (as of %s)" % (
        name, report["as_of"].isoformat()))
    out.append("  circle         : %s · cadence %dd" % (
        CIRCLE_LABEL[relation["circle"]], relation["cadence"]))
    out.append("  band           : %s" % BAND_MARKS[relation["band"]])
    if relation["band"] == "NEVER":
        out.append("  contacts       : none on record — the roster is a promise, this one is unkept")
        if relation["birthday"]:
            out.append("  next occasion  : in %dd (%02d-%02d)" % (
                relation["days_to_occasion"], relation["birthday"][0],
                relation["birthday"][1]))
        return "\n".join(out)
    out.append("  last contact   : %s (silent %s · arrears %dd)" % (
        relation["last_contact"].isoformat(), days_label(relation["elapsed"]),
        relation["arrears"] or 0))
    slope = relation["slope"]
    if slope["slope"] == "UNKNOWN":
        out.append("  silence slope  : unknown — %s on record, need %d+ gaps" % (
            plural(relation["contacts"], "contact"), SLOPE_SAMPLES))
    else:
        out.append("  silence slope  : %s — last gap %dd vs. median %sd (%.2f×)" % (
            slope["slope"], slope["last_gap"], slope["median_gap"], slope["growth"]))
        due_by_history = relation["last_contact"] + timedelta(days=slope["last_gap"])
        if report["as_of"] > due_by_history:
            out.append("      ↳ overdue even by your own history: %s past %s" % (
                days_label((report["as_of"] - due_by_history).days),
                due_by_history.isoformat()))
    if relation["unilateral"] is None:
        out.append("  balance        : unknown — need 2+ contacts")
    else:
        recent = relation["events"][-UNILATERAL_K:]
        mine = sum(1 for e in recent if e["initiator"] == "me")
        out.append("  balance        : you initiated %d of the last %d%s" % (
            mine, len(recent),
            " — UNILATERAL: it stops the moment you do"
            if relation["unilateral"] >= UNILATERAL_THRESHOLD else ""))
    if relation["birthday"]:
        out.append("  next occasion  : in %dd (%02d-%02d)%s" % (
            relation["days_to_occasion"], relation["birthday"][0],
            relation["birthday"][1],
            " — a rehearsal-free door" if occasion_flag(relation) else ""))
    out.append("  history        : %s" % " → ".join(
        "%s(%s)" % (e["date"].isoformat(), "me" if e["initiator"] == "me" else "them")
        for e in relation["events"]))
    return "\n".join(out)


def ledger_json(report, args):
    def rel(r):
        d = {
            "name": redact(r["name"]) if args.redact else r["name"],
            "circle": r["circle"], "cadence": r["cadence"],
            "last_contact": r["last_contact"].isoformat() if r["last_contact"] else None,
            "elapsed": r["elapsed"], "ratio": r["ratio"],
            "arrears": r["arrears"], "band": r["band"],
            "slope": r["slope"],
            "unilateral": r["unilateral"],
            "days_to_occasion": r["days_to_occasion"],
            "occasion_flag": occasion_flag(r),
            "flags": relation_flags(r),
        }
        return d
    counts = report["counts"]
    return {
        "roster": report["roster_path"],
        "interactions": report["interactions_path"],
        "as_of": report["as_of"].isoformat(),
        "tracked": report["tracked"],
        "counts": {k: counts[k] for k in
                   ("FRESH", "OVERDUE", "DRIFTING", "GONE", "NEVER")},
        "relations": [rel(r) for r in report["relations"]],
    }


def repair_json(report, ordered, redact_names):
    return {
        "as_of": report["as_of"].isoformat(),
        "gate": "PASS" if not ordered else "FAIL",
        "due": len(ordered),
        "list": [{
            "name": redact(r["name"]) if redact_names else r["name"],
            "circle": r["circle"], "band": r["band"],
            "elapsed": r["elapsed"], "ratio": r["ratio"],
            "days_to_occasion": r["days_to_occasion"],
            "advice": REPAIR_ADVICE[r["band"]],
        } for r in ordered],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_kv(pairs, what):
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ParseError("--%s wants k=v, got %r" % (what, pair))
        key, _, value = pair.partition("=")
        key = key.strip().lower()
        if key not in DEFAULT_CADENCES:
            raise ParseError("unknown circle %r (want one of %s)" % (
                key, "/".join(DEFAULT_CADENCES)))
        try:
            value = int(value)
        except ValueError:
            raise ParseError("--%s value must be an integer, got %r" % (what, value))
        if value <= 0:
            raise ParseError("--%s value must be positive" % what)
        out[key] = value
    return out


def as_of_arg(text):
    """argparse type adapter: ParseError → clean usage error, no traceback."""
    try:
        return parse_date(text)
    except ParseError as exc:
        raise ValueError(str(exc))       # argparse turns this into exit 2


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="渐行渐远 · Drift Apart — a decay ledger for friendships "
                    "that fail silently.")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("ledger", help="arrears ranking: who is drifting farthest")
    p.add_argument("roster")
    p.add_argument("interactions")
    p.add_argument("--as-of", type=as_of_arg, default=None)
    p.add_argument("--circle", default=None)
    p.add_argument("--circle-cadence", action="append", default=None)
    p.add_argument("--top", type=int, default=None)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--redact", action="store_true")

    p = sub.add_parser("repair", help="who to reach out to today")
    p.add_argument("roster")
    p.add_argument("interactions")
    p.add_argument("--as-of", type=as_of_arg, default=None)
    p.add_argument("--circle-cadence", action="append", default=None)
    p.add_argument("--within", type=int, default=None)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--redact", action="store_true")

    p = sub.add_parser("show", help="one relation's full dossier")
    p.add_argument("roster")
    p.add_argument("interactions")
    p.add_argument("name")
    p.add_argument("--as-of", type=as_of_arg, default=None)
    p.add_argument("--circle-cadence", action="append", default=None)
    p.add_argument("--redact", action="store_true")
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    if getattr(args, "as_of", None) is None:
        args.as_of = date.today()
    try:
        overrides = parse_kv(args.circle_cadence, "circle-cadence") \
            if args.circle_cadence else {}
        if args.command == "ledger":
            report = load_ledger(args.roster, args.interactions,
                                 args.as_of, overrides)
            if args.circle and args.circle not in CIRCLE_RANK:
                raise ParseError("unknown circle %r (want one of %s)" % (
                    args.circle, "/".join(CIRCLE_RANK)))
            if args.circle:
                report["relations"] = [r for r in report["relations"]
                                       if r["circle"] == args.circle]
                report["counts"] = Counter(
                    r["band"] for r in report["relations"])
                report["tracked"] = len(report["relations"])
            if args.format == "json":
                print(json.dumps(ledger_json(report, args),
                                 ensure_ascii=False, indent=2))
                return 0
            print(render_ledger_text(report, args))
            return 0
        if args.command == "repair":
            report = load_ledger(args.roster, args.interactions,
                                 args.as_of, overrides)
            ordered = repair_list(report, args.within)
            if args.format == "json":
                payload = repair_json(report, ordered, args.redact)
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 4 if ordered else 0
            print(render_repair_text(report, args, ordered))
            return 4 if ordered else 0
        if args.command == "show":
            report = load_ledger(args.roster, args.interactions,
                                 args.as_of, overrides)
            matches = [r for r in report["relations"] if r["name"] == args.name]
            if not matches:
                close = [r["name"] for r in report["relations"]
                         if (args.name and r["name"] and
                             args.name[0] == r["name"][0]) or
                            args.name.lower() in r["name"].lower()]
                hint = (" — did you mean: %s" % ", ".join(close[:3])) if close else ""
                raise ParseError("no relation named %r in %s%s" % (
                    args.name, args.roster, hint))
            print(render_show_text(matches[0], report, args))
            return 0
    except ParseError as exc:
        print("%s: error: %s" % (PROG, exc), file=sys.stderr)
        return 3
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
