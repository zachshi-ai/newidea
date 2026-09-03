#!/usr/bin/env python3
"""到期悬崖 · Expiry Cliff.

A validity ledger for the credentials that fail silently: passports, driver
licenses, insurance policies, domains, TLS certs, memberships.

The nominal expiry date lies — a passport with 5 months left is already
unusable for most international travel (the six-month rule). This tool
measures the *margin-adjusted* horizon (expiry minus required lead time),
ranks what falls off the cliff first, gates a trip window against every
credential at once, and mines renewal history for your own renewal rhythm.

Zero dependency: Python 3.8+ standard library only. Everything stays local.
"""

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, OrderedDict
from datetime import date, timedelta

PROG = "expiry_cliff.py"

# Category defaults for the lead time a credential must still have on it to
# be usable (the "six-month rule" family). Rows may override via a margin
# column; --category-margin overrides these.
DEFAULT_MARGINS = OrderedDict([
    ("passport", 180),
    ("visa", 90),
    ("driver_license", 60),
    ("id_card", 30),
    ("domain", 30),
    ("tls_cert", 21),
    ("warranty", 14),
    ("membership", 7),
    ("insurance", 0),
])
UNKNOWN_CATEGORY_MARGIN = 0

# Margin-adjusted days left → band. Bands are consumption behavior, not
# statistics: OVERDUE means already unusable, CLIFF means act now,
# CAUTION means this quarter, CLEAR means forget about it.
BANDS = OrderedDict([
    ("OVERDUE", 0),
    ("CLIFF", 30),
    ("CAUTION", 90),
    ("CLEAR", None),        # everything above 90
])

DATE_ALIASES = {"start", "begin", "生效日", "起始日", "开始日", "起期"}
END_ALIASES = {"end", "expiry", "expires", "到期日", "失效日", "止期", "止日"}
NAME_ALIASES = {"name", "item", "名称", "项目", "条目"}
CATEGORY_ALIASES = {"category", "type", "类别", "类型"}
MARGIN_ALIASES = {"margin", "margin_days", "lead_days", "提前量", "提前天数"}
HOLDER_ALIASES = {"holder", "owner", "who", "持有人", "持有人", "归属"}


class ParseError(Exception):
    """Registry cannot be parsed; message is user-facing."""


def plural(n, noun):
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")


def redact(text):
    return "anon-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


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


def _clean_header(cell):
    return str(cell or "").strip().lstrip("\ufeff").strip().lower()


def _find_header(rows):
    """Locate the header row and the name/category/start/end/margin columns."""
    best = None
    for idx, cells in enumerate(rows[:50]):
        lowered = [_clean_header(c) for c in cells]
        di = ei = ni = ci = mi = hi = None
        for i, h in enumerate(lowered):
            if di is None and h in DATE_ALIASES:
                di = i
            elif ei is None and h in END_ALIASES:
                ei = i
            elif ni is None and h in NAME_ALIASES:
                ni = i
            elif ci is None and h in CATEGORY_ALIASES:
                ci = i
            elif mi is None and h in MARGIN_ALIASES:
                mi = i
            elif hi is None and h in HOLDER_ALIASES:
                hi = i
        if di is not None and ei is not None and ni is not None:
            best = (idx, ni, ci, di, ei, mi, hi)
            break
    if best is None:
        raise ParseError(
            "no header row found: need name (%s), start (%s) and end (%s) "
            "columns; category (%s) and margin (%s) optional" % (
                "/".join(sorted(NAME_ALIASES)[:3]),
                "/".join(sorted(DATE_ALIASES)[:3]),
                "/".join(sorted(END_ALIASES)[:3]),
                "/".join(sorted(CATEGORY_ALIASES)[:2]),
                "/".join(sorted(MARGIN_ALIASES)[:2])))
    return best


def read_registry(path):
    """Parse the registry CSV into a list of period rows."""
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

    header_idx, ni, ci, di, ei, mi, hi = _find_header(rows)
    periods = []
    for lineno, cells in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        def cell(i):
            return cells[i].strip() if i is not None and i < len(cells) else ""
        try:
            start = parse_date(cell(di))
            end = parse_date(cell(ei))
        except ParseError as exc:
            raise ParseError("%s line %d: %s" % (path, lineno, exc))
        if end < start:
            raise ParseError("%s line %d: ends %s before it starts %s" % (
                path, lineno, end.isoformat(), start.isoformat()))
        margin_text = cell(mi)
        margin = None
        if margin_text:
            try:
                margin = int(margin_text)
            except ValueError:
                raise ParseError("%s line %d: margin must be an integer, got %r" % (
                    path, lineno, margin_text))
            if margin < 0:
                raise ParseError("%s line %d: margin cannot be negative" % (path, lineno))
        periods.append({
            "name": cell(ni), "category": cell(ci).lower(),
            "start": start, "end": end, "margin": margin,
            "holder": cell(hi),
            "line": lineno,
        })
    if not periods:
        raise ParseError("%s: header found but no data rows" % path)
    return periods


def resolve_margin(row, category_overrides):
    if row["margin"] is not None:
        return row["margin"]
    if row["category"] in category_overrides:
        return category_overrides[row["category"]]
    return DEFAULT_MARGINS.get(row["category"], UNKNOWN_CATEGORY_MARGIN)


# ---------------------------------------------------------------------------
# horizon model
# ---------------------------------------------------------------------------

def band_of(days_left):
    for name, upper in BANDS.items():
        if upper is None or days_left < upper:
            return name
    return "CLEAR"


def build_item(key, periods, as_of, category_overrides):
    """One credential = all periods sharing (name, holder, category)."""
    periods = sorted(periods, key=lambda p: (p["start"], p["end"]))
    current = max(periods, key=lambda p: (p["end"], p["start"]))
    margin = resolve_margin(current, category_overrides)
    effective_end = current["end"] - timedelta(days=margin)
    left = (effective_end - as_of).days
    nominal_left = (current["end"] - as_of).days
    band = "FUTURE" if current["start"] > as_of else band_of(left)
    item = {
        "key": key,
        "name": current["name"],
        "holder": current["holder"],
        "category": current["category"] or "uncategorized",
        "start": current["start"],
        "end": current["end"],
        "margin": margin,
        "effective_end": effective_end,
        "left": left,               # margin-adjusted days left
        "nominal_left": nominal_left,
        "band": band,
        "periods": len(periods),
    }
    if len(periods) >= 2:
        item["rhythm"] = renewal_rhythm(periods)
        habit = item["rhythm"]["lead_days"]
        if habit > 0 and left <= habit:
            item["renewal_window"] = True
    return item


def renewal_rhythm(periods):
    """From renewal history: typical period length and how early you renew."""
    lens = [(p["end"] - p["start"]).days for p in periods]
    leads = []
    for a, b in zip(periods, periods[1:]):
        leads.append((a["end"] - b["start"]).days)
    return {
        "period_days": median(lens),
        "lead_days": max(0, median(leads)),
        "samples": len(periods),
    }


def median(values):
    vs = sorted(values)
    n = len(vs)
    mid = n // 2
    return vs[mid] if n % 2 else (vs[mid - 1] + vs[mid]) / 2.0


def horizon(registry_path, args):
    periods = read_registry(registry_path)
    overrides = dict(args.category_margin or {})
    grouped = OrderedDict()
    for p in periods:
        key = (p["name"].strip().lower(), p["holder"].strip().lower(),
               p["category"])
        grouped.setdefault(key, []).append(p)
    items = [build_item(k, ps, args.as_of, overrides)
             for k, ps in grouped.items()]
    items.sort(key=lambda i: (i["band"] == "FUTURE", i["left"]))
    counts = Counter(i["band"] for i in items)
    return {
        "path": registry_path,
        "as_of": args.as_of,
        "items": items,
        "counts": counts,
        "tracked": len(items),
        "_periods": grouped,        # period history, used by `show`
    }


def trip_gate(registry_path, args):
    report = horizon(registry_path, args)
    failed = []
    for item in report["items"]:
        if item["band"] == "FUTURE":
            ok = item["start"] <= args.trip_start
        else:
            ok = (item["effective_end"] >= args.trip_end and
                  item["start"] <= args.trip_start)
        if not ok:
            failed.append(item)
    report["trip"] = {
        "start": args.trip_start, "end": args.trip_end,
        "checked": len(report["items"]), "failed": failed,
        "passed": not failed,
    }
    return report


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

BAND_MARKS = {
    "OVERDUE": "!! OVERDUE",
    "CLIFF": "! CLIFF",
    "CAUTION": "~ CAUTION",
    "CLEAR": "OK CLEAR",
    "FUTURE": "·· FUTURE",
}


def fmt_date(d):
    return d.isoformat()


def days_label(n):
    return "%+dd" % n if n < 0 else "%dd" % n


def display(item, args):
    name = item["name"] or "(unnamed)"
    holder = item["holder"]
    if args.redact:
        if holder:
            holder = redact(holder)
    return name, holder


def render_horizon_text(report, args):
    out = []
    out.append("-- Expiry Cliff horizon: %s (as of %s)" % (
        report["path"], fmt_date(report["as_of"])))
    c = report["counts"]
    out.append("  credentials    : %s · %s overdue · %s in the cliff band · "
               "%s cautioning · %s clear%s" % (
                   plural(report["tracked"], "credential"),
                   c.get("OVERDUE", 0), c.get("CLIFF", 0),
                   c.get("CAUTION", 0), c.get("CLEAR", 0),
                   " · %s not yet valid" % c.get("FUTURE", 0)
                   if c.get("FUTURE") else ""))
    ranked = [i for i in report["items"] if i["band"] != "FUTURE"]
    if ranked:
        first = ranked[0]
        name, holder = display(first, args)
        out.append("  first to fall  : %s%s (effective %s, %s behind you)" % (
            name, " · %s" % holder if holder else "",
            fmt_date(first["effective_end"]), days_label(first["left"])))
    out.append("")
    out.append("  %-16s %-12s %-14s %-12s %6s %9s  band" % (
        "name", "holder", "category", "ends", "margin", "left(eff)"))
    for item in report["items"][:args.top]:
        name, holder = display(item, args)
        out.append("  %-16s %-12s %-14s %-12s %6s %9s  %s" % (
            name[:16], holder[:12], item["category"][:14],
            fmt_date(item["end"]), item["margin"],
            days_label(item["left"]), BAND_MARKS[item["band"]]))
    if len(report["items"]) > args.top:
        out.append("  … and %d more" % (len(report["items"]) - args.top))
    windows = [i for i in report["items"] if i.get("renewal_window")]
    if windows:
        out.append("")
        out.append("  inside your usual renewal window (history says you renew early):")
        for item in windows:
            name, holder = display(item, args)
            r = item["rhythm"]
            out.append("  ↻ %-16s you usually renew ~%dd early · every %s" % (
                name[:16], r["lead_days"], human_days(r["period_days"])))
    return "\n".join(out)


def human_days(n):
    n = int(n)
    if n >= 328:
        return "~%dy" % max(1, round(n / 365.25))
    return "%dd" % n


def render_trip_text(report, args):
    trip = report["trip"]
    out = []
    out.append("-- Expiry Cliff trip: %s .. %s (as of %s)" % (
        fmt_date(trip["start"]), fmt_date(trip["end"]), fmt_date(report["as_of"])))
    out.append("  %s checked, %d fail the gate:" % (
        plural(trip["checked"], "credential"), len(trip["failed"])))
    for item in trip["failed"]:
        name, holder = display(item, args)
        if item["band"] == "FUTURE":
            reason = "does not start until %s" % fmt_date(item["start"])
        else:
            reason = "effective %s — dead %s before you return" % (
                fmt_date(item["effective_end"]),
                days_label((trip["end"] - item["effective_end"]).days))
        out.append("  ! %-16s ends %s · margin %3d · %s" % (
            name[:16], fmt_date(item["end"]), item["margin"], reason))
    out.append("")
    out.append("  gate: %s" % ("PASS — every credential outlives your return"
                                if trip["passed"] else "FAIL"))
    return "\n".join(out)


def render_show_text(report, item, args):
    name, holder = display(item, args)
    out = []
    out.append("-- Expiry Cliff: %s%s" % (
        name, " · %s" % holder if holder else ""))
    out.append("  category %s · margin %dd · current period %s .. %s" % (
        item["category"], item["margin"],
        fmt_date(item["start"]), fmt_date(item["end"])))
    out.append("  effective horizon: %s (%s, %s)" % (
        fmt_date(item["effective_end"]), item["band"], days_label(item["left"])))
    if item.get("rhythm"):
        r = item["rhythm"]
        out.append("  renewal rhythm: every %s · you renew ~%dd early (%s)" % (
            human_days(r["period_days"]), r["lead_days"],
            plural(r["samples"] - 1, "renewal")))
    out.append("")
    out.append("  periods on record:")
    periods = sorted(report["_periods"][item["key"]], key=lambda p: p["start"])
    prev_end = None
    for p in periods:
        gap = ""
        if prev_end is not None:
            lead = (prev_end - p["start"]).days
            if lead > 0:
                gap = "   <- renewed %dd before previous expiry" % lead
            elif (p["start"] - prev_end).days > 0:
                gap = "   <- lapsed %dd" % (p["start"] - prev_end).days
        out.append("    %s .. %s%s" % (fmt_date(p["start"]), fmt_date(p["end"]), gap))
        prev_end = p["end"]
    return "\n".join(out)


def render_horizon_json(report, args):
    payload = {
        "registry": report["path"],
        "as_of": fmt_date(report["as_of"]),
        "tracked": report["tracked"],
        "counts": {k: report["counts"].get(k, 0)
                   for k in ("OVERDUE", "CLIFF", "CAUTION", "CLEAR", "FUTURE")},
        "items": [item_json(i, args) for i in report["items"]],
    }
    if "trip" in report:
        trip = report["trip"]
        payload["trip"] = {
            "start": fmt_date(trip["start"]),
            "end": fmt_date(trip["end"]),
            "checked": trip["checked"],
            "passed": trip["passed"],
            "failed": [item_json(i, args) for i in trip["failed"]],
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def item_json(item, args):
    name, holder = display(item, args)
    d = {
        "name": name, "holder": holder, "category": item["category"],
        "start": fmt_date(item["start"]), "end": fmt_date(item["end"]),
        "margin": item["margin"],
        "effective_end": fmt_date(item["effective_end"]),
        "days_left": item["left"], "nominal_days_left": item["nominal_left"],
        "band": item["band"],
    }
    if item.get("rhythm"):
        d["rhythm"] = {
            "period_days": item["rhythm"]["period_days"],
            "lead_days": item["rhythm"]["lead_days"],
            "renewal_window": bool(item.get("renewal_window")),
        }
    return d


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_as_of(text):
    try:
        return parse_date(text)
    except ParseError:
        raise ParseError("--as-of must be a date (YYYY-MM-DD), got %r" % text)


def build_parser():
    p = argparse.ArgumentParser(
        prog=PROG,
        description="A validity ledger for credentials that fail silently "
                    "(zero dependency, fully local).")
    sub = p.add_subparsers(dest="cmd")

    def common(pa):
        pa.add_argument("registry", help="registry CSV "
                        "(name/category/start/end[/margin/holder])")
        pa.add_argument("--as-of", default=None, metavar="DATE",
                        help="reference date (default: today)")
        pa.add_argument("--category-margin", action="append", default=None,
                        metavar="CAT=DAYS",
                        help="override a category's default lead time")

    ph = sub.add_parser("horizon", help="rank credentials by margin-adjusted "
                                        "time left before the cliff")
    common(ph)
    ph.add_argument("--format", choices=("text", "json"), default="text")
    ph.add_argument("--top", type=int, default=15, metavar="N")
    ph.add_argument("--redact", action="store_true",
                    help="hash holder names in the report")

    pt = sub.add_parser("trip", help="gate a travel window against every "
                                     "credential (exit 4 on failure)")
    common(pt)
    pt.add_argument("--end", required=True, metavar="DATE",
                    help="the day you return — every credential must still "
                         "be effective then")
    pt.add_argument("--start", default=None, metavar="DATE",
                    help="departure day (default: same as --end)")
    pt.add_argument("--format", choices=("text", "json"), default="text")
    pt.add_argument("--redact", action="store_true")

    ps = sub.add_parser("show", help="one credential's full period history")
    common(ps)
    ps.add_argument("name", help="credential name (exact or unique substring)")
    ps.add_argument("--format", choices=("text", "json"), default="text")
    ps.add_argument("--redact", action="store_true")
    return p


def find_item(report, query):
    q = query.strip().lower()
    exact = [i for i in report["items"] if i["name"].strip().lower() == q]
    if len(exact) == 1:
        return exact
    hits = [i for i in report["items"]
            if q and q in ("%s %s" % (i["name"], i["holder"])).lower()]
    if len(hits) == 1:
        return hits
    return exact or hits


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd not in ("horizon", "trip", "show"):
        parser.print_usage(sys.stderr)
        return 2
    try:
        args.as_of = parse_as_of(args.as_of) if args.as_of else date.today()
        if getattr(args, "category_margin", None):
            overrides = {}
            for spec in args.category_margin:
                if "=" not in spec:
                    raise ParseError("--category-margin expects CAT=DAYS, got %r" % spec)
                cat, _, days = spec.partition("=")
                try:
                    overrides[cat.strip().lower()] = int(days)
                except ValueError:
                    raise ParseError("--category-margin expects CAT=DAYS, got %r" % spec)
            args.category_margin = overrides

        if args.cmd == "trip":
            args.trip_end = parse_as_of(args.end)
            args.trip_start = parse_as_of(args.start) if args.start else args.trip_end
            if args.trip_end < args.trip_start:
                raise ParseError("trip ends %s before it starts %s" % (
                    args.end, args.start))
            report = trip_gate(args.registry, args)
            print(render_horizon_json(report, args) if args.format == "json"
                  else render_trip_text(report, args))
            return 0 if report["trip"]["passed"] else 4

        report = horizon(args.registry, args)

        if args.cmd == "horizon":
            print(render_horizon_json(report, args) if args.format == "json"
                  else render_horizon_text(report, args))
            return 0

        hits = find_item(report, args.name)
        if not hits:
            sys.stderr.write("error: no credential matches %r\n" % args.name)
            return 3
        if len(hits) > 1:
            def label(i):
                return i["name"] + (" · " + i["holder"] if i["holder"] else "")
            sys.stderr.write("error: %r is ambiguous: %s\n" % (
                args.name, ", ".join(sorted(label(i) for i in hits))))
            return 3
        item = hits[0]
        if args.format == "json":
            payload = item_json(item, args)
            payload["periods"] = [
                {"start": fmt_date(p["start"]), "end": fmt_date(p["end"])}
                for p in report["_periods"][item["key"]]]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_show_text(report, item, args))
        return 0
    except ParseError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
