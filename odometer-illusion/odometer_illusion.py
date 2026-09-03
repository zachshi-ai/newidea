#!/usr/bin/env python3
"""里程错觉 · Odometer Illusion.

A twin-clock maintenance ledger for cars. Every service item ages on two
clocks at once — the mileage clock (wear per km driven) and the calendar
clock (decay per day parked) — and the first clock to run out wins. The
odometer only shows the first clock, so low-mileage drivers get the
illusion that a rarely-driven car is a young car, while oil oxidizes,
rubber cracks, brake fluid absorbs water and batteries die on the
calendar clock, invisible to the odometer.

Zero dependency: Python 3.8+ standard library only. Everything stays local.
"""

import argparse
import csv
import sys
from collections import OrderedDict
from datetime import date

PROG = "odometer_illusion.py"

# Default service periods: (calendar_days, mileage_km). A 0 means the item
# does not age on that clock (wipers and batteries are calendar-bound;
# nothing here is mileage-only by default, but a row may set days=0).
# These are conservative common-knowledge values, not any manufacturer's
# schedule — the vehicle manual always wins; override via --period.
DEFAULT_PERIODS = OrderedDict([
    ("engine_oil", (180, 5000)),
    ("oil_filter", (180, 5000)),
    ("air_filter", (365, 12000)),
    ("cabin_filter", (365, 12000)),
    ("brake_fluid", (730, 40000)),
    ("coolant", (730, 40000)),
    ("brake_pads", (1825, 40000)),
    ("tires", (2190, 60000)),
    ("wipers", (365, 0)),
    ("battery", (1095, 0)),
    ("spark_plugs", (1825, 40000)),
])

# Chinese aliases accepted in the service log's item column.
ITEM_ALIASES = OrderedDict([
    ("engine_oil", ("机油", "引擎油", "oil")),
    ("oil_filter", ("机滤", "机油滤芯", "机油滤清器")),
    ("air_filter", ("空气滤芯", "空滤")),
    ("cabin_filter", ("空调滤芯", "空调滤")),
    ("brake_fluid", ("刹车油", "制动液")),
    ("coolant", ("冷却液", "防冻液")),
    ("brake_pads", ("刹车片", "刹车皮", "制动片")),
    ("tires", ("轮胎", "tyre", "tire")),
    ("wipers", ("雨刮", "雨刮器", "雨刷", "雨刷器")),
    ("battery", ("电瓶", "蓄电池", "电池")),
    ("spark_plugs", ("火花塞", "火咀")),
])

ITEM_NAMES_ZH = OrderedDict([
    ("engine_oil", "机油"),
    ("oil_filter", "机滤"),
    ("air_filter", "空气滤芯"),
    ("cabin_filter", "空调滤芯"),
    ("brake_fluid", "刹车油"),
    ("coolant", "冷却液"),
    ("brake_pads", "刹车片"),
    ("tires", "轮胎"),
    ("wipers", "雨刮"),
    ("battery", "电瓶"),
    ("spark_plugs", "火花塞"),
])

# progress → band. Bands are aging stages, not statistics: OVERDUE means the
# item is past at least one of its clocks, DUE means inside the last 15%,
# SOON inside the last 30%, OK means forget about it.
BANDS = OrderedDict([
    ("OVERDUE", (1.00, "!!")),
    ("DUE", (0.85, "!")),
    ("SOON", (0.70, "~")),
    ("OK", (None, ".")),
])

# A profile needs at least this many due items before we label the driver.
PROFILE_MIN_DUE = 2
PROFILE_CALENDAR_SHARE = 0.6

CAR_NAME_ALIASES = {"name", "car", "vehicle", "名称", "车名", "车辆"}
BOUGHT_DATE_ALIASES = {"bought_date", "bought", "purchase_date", "购入日期", "提车日期", "购车日期", "购入"}
BOUGHT_KM_ALIASES = {"bought_km", "purchase_km", "购入里程", "提车里程", "购车里程", "购入公里"}
DATE_ALIASES = {"date", "日期", "完工日期", "施工日期"}
KM_ALIASES = {"km", "mileage", "odometer", "里程", "公里数", "里程数"}
ITEM_COL_ALIASES = {"item", "service", "项目", "品目", "保养项目"}
COST_ALIASES = {"cost", "fee", "amount", "费用", "金额", "花费"}
NOTE_ALIASES = {"note", "notes", "备注", "说明"}


class ParseError(Exception):
    """Ledger cannot be parsed; message is user-facing."""


class UsageError(Exception):
    """CLI arguments are wrong; message is user-facing."""


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
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            pass
    raise ParseError("unrecognized date: %r" % text)


def parse_km(text):
    s = str(text).strip().replace(",", "").replace("，", "").replace(" ", "")
    try:
        km = int(s)
    except ValueError:
        raise ParseError("unrecognized odometer reading: %r" % text)
    if km < 0:
        raise ParseError("odometer reading must be >= 0, got %r" % text)
    return km


def parse_cost(text, row_no):
    s = str(text).strip()
    if s == "":
        return None
    s = s.replace(",", "").replace("，", "").replace("¥", "").replace("￥", "").strip()
    try:
        value = float(s)
    except ValueError:
        raise ParseError("row %d: unrecognized cost %r" % (row_no, text))
    if value < 0:
        raise ParseError("row %d: cost must be >= 0" % row_no)
    return value


def canonical_item(text):
    s = str(text).strip().lower()
    if s in DEFAULT_PERIODS:
        return s
    for key, aliases in ITEM_ALIASES.items():
        if s in aliases:
            return key
    return None


def _clean_header(cell):
    return str(cell or "").strip().lstrip("\ufeff").strip().lower()


def _read_rows(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            return [row for row in csv.reader(fh) if any(str(c).strip() for c in row)]
    except FileNotFoundError:
        raise ParseError("file not found: %s" % path)
    except OSError as exc:
        raise ParseError("cannot read %s: %s" % (path, exc))


def _find_columns(rows, needed, optional, path):
    """Locate the header row; needed/optional are alias-set → slot maps."""
    for idx, cells in enumerate(rows[:50]):
        lowered = [_clean_header(c) for c in cells]
        slots = {}
        for slot, aliases in list(needed.items()) + list(optional.items()):
            for i, h in enumerate(lowered):
                if h in aliases and slot not in slots:
                    slots[slot] = i
        if all(slot in slots for slot in needed):
            return idx, slots
    raise ParseError(
        "no header row found in %s: need %s columns (optional: %s)" % (
            path,
            ", ".join(needed),
            ", ".join(sorted(set().union(*optional.values())) if optional else "none"),
        )
    )


def parse_car(path):
    rows = _read_rows(path)
    hdr_idx, slots = _find_columns(
        rows,
        {"name": CAR_NAME_ALIASES, "bought_date": BOUGHT_DATE_ALIASES, "bought_km": BOUGHT_KM_ALIASES},
        {},
        path,
    )
    if len(rows) <= hdr_idx + 1:
        raise ParseError("car registry %s has a header but no car row" % path)
    cells = rows[hdr_idx + 1]
    name = str(cells[slots["name"]]).strip()
    if not name:
        raise ParseError("car registry %s: car name is empty" % path)
    bought_date = parse_date(cells[slots["bought_date"]])
    bought_km = parse_km(cells[slots["bought_km"]])
    return {"name": name, "bought_date": bought_date, "bought_km": bought_km}


def parse_service(path):
    rows = _read_rows(path)
    hdr_idx, slots = _find_columns(
        rows,
        {"date": DATE_ALIASES, "km": KM_ALIASES, "item": ITEM_COL_ALIASES},
        {"cost": COST_ALIASES, "note": NOTE_ALIASES},
        path,
    )
    events = []
    for row_no, cells in enumerate(rows[hdr_idx + 1:], start=hdr_idx + 2):
        when = parse_date(cells[slots["date"]])
        km = parse_km(cells[slots["km"]])
        raw_item = cells[slots["item"]]
        item = canonical_item(raw_item)
        cost = parse_cost(cells[slots["cost"]], row_no) if "cost" in slots else None
        note = str(cells[slots["note"]]).strip() if "note" in slots and slots["note"] < len(cells) else ""
        events.append({
            "date": when,
            "km": km,
            "item": item,
            "raw_item": str(raw_item).strip(),
            "cost": cost,
            "note": note,
            "row": row_no,
        })
    return events


def parse_periods(specs):
    """--period engine_oil=365,10000 (days,km); 0 = item does not age on that clock."""
    periods = {}
    for spec in specs or []:
        if "=" not in spec:
            raise UsageError("--period expects item=days,km, got %r" % spec)
        key, value = spec.split("=", 1)
        key = canonical_item(key.strip())
        if key is None:
            raise UsageError("unknown item %r in --period" % spec.split("=", 1)[0])
        parts = value.split(",")
        if len(parts) != 2:
            raise UsageError("--period expects item=days,km, got %r" % spec)
        try:
            days, km = int(parts[0]), parse_km(parts[1])
        except (ValueError, ParseError) as exc:
            raise UsageError("--period expects item=days,km, got %r (%s)" % (spec, exc))
        if days < 0 or (days == 0 and km == 0):
            raise UsageError("--period: days must be >= 0 and at least one clock must be > 0 in %r" % spec)
        periods[key] = (days, km)
    return periods


def compute_state(car, events, periods, as_of, km_now=None):
    """Merge registry + service log + period table into per-item clock state."""
    all_periods = OrderedDict(DEFAULT_PERIODS)
    for key, value in periods.items():
        all_periods[key] = value

    known_events = [e for e in events if e["item"] is not None]
    unknown_items = sorted({e["raw_item"] for e in events if e["item"] is None})

    odometer = car["bought_km"]
    for e in events:
        odometer = max(odometer, e["km"])
    if km_now is not None:
        odometer = max(odometer, km_now)

    items = []
    for key, (days, km_period) in all_periods.items():
        history = [e for e in known_events if e["item"] == key]
        if history:
            last = max(history, key=lambda e: (e["date"], e["km"]))
            start_date, start_km, assumed = last["date"], last["km"], False
        else:
            start_date, start_km, assumed = car["bought_date"], car["bought_km"], True
        entry = {
            "item": key,
            "days": days,
            "km_period": km_period,
            "last_date": start_date,
            "last_km": start_km,
            "assumed": assumed,
            "services": len(history),
        }
        mileage_progress = None
        if km_period > 0:
            mileage_progress = (odometer - start_km) / float(km_period)
        calendar_progress = None
        if days > 0:
            calendar_progress = (as_of - start_date).days / float(days)
        progress_values = [p for p in (mileage_progress, calendar_progress) if p is not None]
        progress = max(progress_values)
        if calendar_progress is not None and (mileage_progress is None or calendar_progress >= mileage_progress):
            binding = "calendar"
        else:
            binding = "mileage"
        entry.update({
            "mileage_progress": mileage_progress,
            "calendar_progress": calendar_progress,
            "progress": progress,
            "binding": binding,
            "band": band_of(progress),
        })
        items.append(entry)

    items.sort(key=lambda it: (-it["progress"], it["item"]))
    return {
        "items": items,
        "odometer": odometer,
        "unknown_items": unknown_items,
        "events": events,
    }


def band_of(progress):
    if progress >= BANDS["OVERDUE"][0]:
        return "OVERDUE"
    if progress >= BANDS["DUE"][0]:
        return "DUE"
    if progress >= BANDS["SOON"][0]:
        return "SOON"
    return "OK"


def band_mark(band):
    return dict((b, m) for b, (_t, m) in BANDS.items())[band]


def car_age_years(car, as_of):
    return max((as_of - car["bought_date"]).days, 0) / 365.25


def km_per_year(car, state, as_of):
    age = car_age_years(car, as_of)
    if age <= 0:
        return None
    return (state["odometer"] - car["bought_km"]) / age


def build_profile(car, state, as_of):
    due = [it for it in state["items"] if it["band"] in ("OVERDUE", "DUE")]
    profile = {
        "due_count": len(due),
        "calendar_bound": sum(1 for it in due if it["binding"] == "calendar"),
        "mileage_bound": sum(1 for it in due if it["binding"] == "mileage"),
        "label": None,
        "km_per_year": km_per_year(car, state, as_of),
    }
    if profile["due_count"] >= PROFILE_MIN_DUE:
        if profile["calendar_bound"] >= PROFILE_CALENDAR_SHARE * profile["due_count"]:
            profile["label"] = "calendar"
        elif profile["mileage_bound"] >= PROFILE_CALENDAR_SHARE * profile["due_count"]:
            profile["label"] = "mileage"
        else:
            profile["label"] = "mixed"
    return profile


def fmt_pct(value):
    return "%.0f%%" % (value * 100)


def fmt_km(km):
    return "{:,}".format(km)


def render_status(car, state, as_of, profile):
    lines = []
    counts = {band: 0 for band in BANDS}
    for it in state["items"]:
        counts[it["band"]] += 1
    tracked = len(state["items"])

    lines.append("car       : %s · bought %s @ %s km" % (
        car["name"], car["bought_date"].isoformat(), fmt_km(car["bought_km"])))
    age = car_age_years(car, as_of)
    kpy = profile["km_per_year"]
    lines.append("clock     : %s · %s km on the odometer · %.1f y old · %s" % (
        as_of.isoformat(), fmt_km(state["odometer"]), age,
        ("%s km/y" % fmt_km(int(round(kpy)))) if kpy is not None else "age <= 0, no annual rate"))
    lines.append("items     : %d tracked · %d OVERDUE · %d DUE · %d SOON · %d OK" % (
        tracked, counts["OVERDUE"], counts["DUE"], counts["SOON"], counts["OK"]))
    lines.append("")
    lines.append("  item            last done         mileage  calendar  progress  band")
    for it in state["items"]:
        last = "assumed factory" if it["assumed"] else it["last_date"].isoformat()
        mileage = fmt_pct(it["mileage_progress"]) if it["mileage_progress"] is not None else "—"
        calendar = fmt_pct(it["calendar_progress"]) if it["calendar_progress"] is not None else "—"
        mark = band_mark(it["band"])
        lines.append("  %-15s %-17s %8s %9s %9s  %s %s" % (
            it["item"], last, mileage, calendar, fmt_pct(it["progress"]), mark, it["band"]))
    lines.append("")

    due = [it for it in state["items"] if it["band"] in ("OVERDUE", "DUE")]
    if profile["label"] and profile["km_per_year"] is not None:
        lines.append("  binding clocks of the %d due items: %d calendar · %d mileage" % (
            profile["due_count"], profile["calendar_bound"], profile["mileage_bound"]))
        kpy = int(round(profile["km_per_year"]))
        if profile["label"] == "calendar":
            lines.append("  you are a calendar-bound driver: %s km/y means the odometer" % fmt_km(kpy))
            lines.append("  barely moves — this car is aging in the garage, not on the road.")
        elif profile["label"] == "mileage":
            lines.append("  you are a mileage-bound driver: %s km/y burns through service" % fmt_km(kpy))
            lines.append("  intervals faster than the calendar — \"done last year\" no longer counts.")
        else:
            lines.append("  your due items split between both clocks — check each row above.")

    if state["unknown_items"]:
        lines.append("")
        lines.append("  items in the log with no known period (not judged): %s" %
                     ", ".join(state["unknown_items"]))
    return "\n".join(lines)


def render_trip(car, state, as_of, trip_km, trip_days):
    return_date = as_of.fromordinal(as_of.toordinal() + trip_days)
    return_km = state["odometer"] + trip_km
    lines = []
    lines.append("trip gate : depart %s · + %s km / %d days" % (
        as_of.isoformat(), fmt_km(trip_km), trip_days))
    lines.append("return    : %s @ %s km" % (return_date.isoformat(), fmt_km(return_km)))
    fails, warns = [], []
    projections = []
    for it in state["items"]:
        values = []
        if it["km_period"] > 0:
            values.append((return_km - it["last_km"]) / float(it["km_period"]))
        if it["days"] > 0:
            values.append((return_date - it["last_date"]).days / float(it["days"]))
        progress = max(values)
        if it["calendar_progress"] is not None and (
                it["mileage_progress"] is None or
                (return_date - it["last_date"]).days / float(it["days"]) >= (return_km - it["last_km"]) / float(it["km_period"])):
            binding = "calendar"
        else:
            binding = "mileage"
        projections.append((it, progress, binding))
        if progress >= 1.0:
            fails.append((it, progress, binding))
        elif progress >= 0.85:
            warns.append((it, progress, binding))
    lines.append("")
    if fails:
        lines.append("  %d of %d items cross the line mid-trip:" % (len(fails), len(state["items"])))
        for it, progress, binding in fails:
            lines.append("  ! %-13s %8s at return (%s clock) — service before you leave" % (
                it["item"], fmt_pct(progress), binding))
    else:
        lines.append("  no item crosses its line mid-trip.")
    if warns:
        lines.append("")
        for it, progress, binding in warns:
            lines.append("  ~ %-13s enters the DUE band mid-trip (%s, %s clock) — check it" % (
                it["item"], fmt_pct(progress), binding))
    lines.append("")
    lines.append("gate: %s" % ("FAIL" if fails else "PASS"))
    return "\n".join(lines), len(fails)


def render_cost(car, state, as_of):
    events = state["events"]
    priced = [e for e in events if e["cost"] is not None]
    lines = []
    if not priced:
        lines.append("cost ledger: no cost column (or no priced entries) in the service log —")
        lines.append("the money account stays honest by being absent: add the invoice")
        lines.append("amounts and re-run, this tool will not invent them.")
        return "\n".join(lines)
    total = sum(e["cost"] for e in priced)
    span_km = state["odometer"] - min([car["bought_km"]] + [e["km"] for e in events])
    age = car_age_years(car, as_of)
    lines.append("cost ledger : %d priced entries · ¥%s total" % (len(priced), fmt_km(int(round(total)))))
    if span_km > 0:
        lines.append("per km      : ¥%.3f / km over %s km on the ledger" % (
            total / span_km, fmt_km(span_km)))
    if age > 0:
        lines.append("per year    : ¥%s / y over %.1f y of car age" % (
            fmt_km(int(round(total / age))), age))
    costliest = max(priced, key=lambda e: e["cost"])
    lines.append("costliest   : %s %s ¥%s" % (
        costliest["date"].isoformat(),
        costliest["item"] or costliest["raw_item"],
        fmt_km(int(round(costliest["cost"])))))
    by_item = OrderedDict()
    for e in priced:
        key = e["item"] or e["raw_item"]
        by_item[key] = by_item.get(key, 0.0) + e["cost"]
    parts = []
    for key, amount in sorted(by_item.items(), key=lambda kv: -kv[1]):
        share = amount / total * 100
        label = key if key in ITEM_NAMES_ZH else key
        parts.append("%s ¥%s (%.1f%%)" % (label, fmt_km(int(round(amount))), share))
    lines.append("by item     : " + " · ".join(parts))
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Twin-clock maintenance ledger: mileage clock vs calendar clock, first clock out wins.")
    sub = parser.add_subparsers(dest="command")

    def add_common(p):
        p.add_argument("car", help="car registry CSV (name, bought_date, bought_km)")
        p.add_argument("service", help="service log CSV (date, km, item, [cost], [note])")
        p.add_argument("--as-of", dest="as_of", default=None,
                       help="pin 'today' for reproducible reports (default: actual today)")
        p.add_argument("--km-now", dest="km_now", default=None, type=int,
                       help="pin the current odometer reading (default: max of the ledger)")
        p.add_argument("--period", dest="periods", action="append", default=[],
                       metavar="ITEM=DAYS,KM", help="override a service period; 0 = item does not age on that clock")
        p.add_argument("--format", choices=("text", "json"), default="text")

    add_common(sub.add_parser("status", help="twin-clock dashboard: what has aged out first"))
    p_trip = sub.add_parser("trip", help="gate a planned trip against every item's clocks")
    add_common(p_trip)
    p_trip.add_argument("--km", dest="trip_km", type=int, required=True, help="planned trip distance in km")
    p_trip.add_argument("--days", dest="trip_days", type=int, default=7, help="planned trip duration in days (default 7)")
    add_common(sub.add_parser("cost", help="the money account: total, per km, per year, by item"))
    return parser


def load_context(args):
    if args.as_of:
        as_of = parse_date(args.as_of)
    else:
        as_of = date.today()
    car = parse_car(args.car)
    events = parse_service(args.service)
    periods = parse_periods(args.periods)
    km_now = args.km_now
    if km_now is not None and km_now < 0:
        raise UsageError("--km-now must be >= 0")
    state = compute_state(car, events, periods, as_of, km_now)
    return car, state, as_of


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        car, state, as_of = load_context(args)
        if args.command == "status":
            profile = build_profile(car, state, as_of)
            output = render_status(car, state, as_of, profile)
        elif args.command == "trip":
            if args.trip_km < 0:
                raise UsageError("--km must be >= 0")
            if args.trip_days <= 0:
                raise UsageError("--days must be > 0")
            output, fails = render_trip(car, state, as_of, args.trip_km, args.trip_days)
        else:
            output = render_cost(car, state, as_of)
    except (ParseError, UsageError) as exc:
        print("%s: error: %s" % (PROG, exc), file=sys.stderr)
        return 3
    if args.format == "json":
        import json as _json
        payload = {"car": car["name"], "as_of": as_of.isoformat(), "odometer": state["odometer"]}
        payload["items"] = [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v)
             for k, v in it.items() if k != "services"}
            for it in state["items"]
        ]
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(output)
    return 4 if (args.command == "trip" and fails) else 0


if __name__ == "__main__":
    sys.exit(main())
