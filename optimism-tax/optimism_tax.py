#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""optimism-tax — 乐观税 / Optimism Tax

Your "three days" has never been three days. Every estimate you give is a
prediction, and every prediction you never audit stays optimistic forever:
you estimated 3 and delivered 5, then next sprint you said 3 again — and
believed it. Planning fallacy is not an incurable disease; it is a disease
nobody reconciles. optimism-tax keeps the ledger: each task you finish is
one (estimate, actual) receipt, and the ledger computes your personal
optimism tax rate — the median by how much the work outgrew the estimate —
plus a P80 "safe quote", per-tag distortion accounts, a calibration trend,
and the running total of days you have already paid in tax.

  * record  — append one receipt: what you promised, what it actually took
  * report  — the full audit: tax rate, tax bracket, per-tag ledger,
              trend, red flags, and total tax paid to date
  * quote   — price the next promise: given an estimate, what will it
              really cost, at your own track record's confidence levels

Method in one line: r = actual / estimate per record; the tax rate is the
median r (robust to the one project that exploded); the safe quote uses
the P80 of r (you will be late 1 time in 5, not 1 time in 2); tags split
"you are not miscalibrated in general, you are miscalibrated on research".

Estimation is not commitment — it is prophecy. Unaudited prophecy is
always optimistic. Zero dependencies: Python 3.8+ standard library only.
MIT License (c) 2026
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

__version__ = "1.0.0"

DEFAULT_LEDGER = "records.jsonl"

# Minimum records before the tool will calibrate a quote at all. Below
# this the median is noise pretending to be a track record — quoting on
# it would be lending the tool's authority to a coin flip.
MIN_RECORDS_FOR_QUOTE = 8
# Minimum records for a per-tag tax rate inside `report`. A tag with 2
# records gets shown, marked thin, and never used for calibration.
MIN_RECORDS_FOR_TAG_RATE = 3
# How many most-recent records form the "recent" side of the trend.
TREND_WINDOW = 10
# Fewer than this many records before the window → no trend verdict.
MIN_RECORDS_FOR_TREND = 5

# Tax brackets, judged on the median inflation ratio. These are promise-
# consumption boundaries, not statistics: at ≤1.1 what you say is what
# will happen; at >2.0 your "X days" means "2X days" to everyone who
# schedules against your words.
BRACKETS: Tuple[Tuple[float, str, str], ...] = (
    (1.1, "calibrated", "OK calibrated   — what you say is what ships"),
    (1.5, "mild",       "~ mild tax      — plan a little slack"),
    (2.0, "standard",   "~~ standard tax — your estimates mean +50-100%"),
    (float("inf"), "heavy", "!! HEAVY TAX    — your 'X days' means '2X days'"),
)

# Red-flag thresholds.
SPREAD_FLAG_RATIO = 2.5    # p80/median above this: several tax rates, not one
WORSE_TREND_RATIO = 1.5    # recent median / prior median above this: worsening
BETTER_TREND_RATIO = 0.67  # below this: calibrating down
SANDBAG_SHARE = 0.40       # >40% of records finished early: hiding buffer


class LedgerError(Exception):
    """Fatal problem with the ledger or its arguments."""


class QuoteRefused(Exception):
    """The ledger refuses to calibrate — too few records."""


# ---------------------------------------------------------------------------
# Records

@dataclass
class Record:
    estimate: float
    actual: float
    tag: str
    note: str
    date: str
    line: int  # 1-based line number in the ledger, for error messages

    @property
    def ratio(self) -> float:
        return self.actual / self.estimate


def parse_record(obj: dict, line: int) -> Record:
    """Validate one parsed JSONL object into a Record. Raises LedgerError."""
    if not isinstance(obj, dict):
        raise LedgerError(f"line {line}: not a JSON object")
    for key in ("estimate", "actual"):
        if key not in obj:
            raise LedgerError(f"line {line}: missing '{key}'")
    estimate, actual = obj["estimate"], obj["actual"]
    for name, val in (("estimate", estimate), ("actual", actual)):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise LedgerError(f"line {line}: '{name}' must be a number")
    if estimate <= 0:
        raise LedgerError(f"line {line}: estimate must be > 0 (got {estimate})")
    if actual < 0:
        raise LedgerError(f"line {line}: actual must be >= 0 (got {actual})")
    tag = obj.get("tag") or "untagged"
    note = obj.get("note") or ""
    day = obj.get("date") or date.today().isoformat()
    if not isinstance(tag, str) or not isinstance(note, str) or not isinstance(day, str):
        raise LedgerError(f"line {line}: tag/note/date must be strings")
    return Record(float(estimate), float(actual), tag, note, day, line)


def load_ledger(path: str) -> Tuple[List[Record], int]:
    """Parse the JSONL ledger. Returns (records, skipped_bad_lines)."""
    import os
    if not os.path.exists(path):
        raise LedgerError(
            f"ledger not found: {path} (record something first: "
            f"optimism_tax.py record --estimate 3 --actual 5)"
        )
    records: List[Record] = []
    skipped = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                skipped += 1
                continue
            try:
                records.append(parse_record(obj, line_no))
            except LedgerError:
                skipped += 1
    return records, skipped


def sort_key(rec: Record) -> Tuple[str, int]:
    # Order by date, then ledger line (stable for same-day records).
    return (rec.date, rec.line)


# ---------------------------------------------------------------------------
# Statistics

def quantile(sorted_vals: List[float], q: float) -> float:
    """Linear-interpolation quantile on a pre-sorted list. 0 <= q <= 1."""
    if not sorted_vals:
        raise ValueError("quantile of empty list")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def ratios_of(records: List[Record]) -> List[float]:
    return [rec.ratio for rec in records]


def median(vals: List[float]) -> float:
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def bracket_for(median_ratio: float) -> Tuple[str, str]:
    for bound, name, label in BRACKETS:
        if median_ratio <= bound:
            return name, label
    return BRACKETS[-1][1], BRACKETS[-1][2]  # pragma: no cover


@dataclass
class TagAccount:
    tag: str
    records: List[Record]
    median_ratio: Optional[float]  # None when the bucket is too thin

    @property
    def thin(self) -> bool:
        return len(self.records) < MIN_RECORDS_FOR_TAG_RATE


def tag_accounts(records: List[Record]) -> List[TagAccount]:
    buckets: Dict[str, List[Record]] = {}
    for rec in records:
        buckets.setdefault(rec.tag, []).append(rec)
    accounts = []
    for tag, recs in buckets.items():
        recs.sort(key=sort_key)
        rate = median(ratios_of(recs)) if len(recs) >= MIN_RECORDS_FOR_TAG_RATE else None
        accounts.append(TagAccount(tag, recs, rate))
    accounts.sort(key=lambda a: (-len(a.records), a.tag))
    return accounts


@dataclass
class Trend:
    recent_median: float
    prior_median: Optional[float]
    verdict: str  # "worsening" | "improving" | "flat" | "unknown"


def calibration_trend(records: List[Record]) -> Trend:
    recs = sorted(records, key=sort_key)
    ratios = ratios_of(recs)
    recent = ratios[-TREND_WINDOW:]
    recent_median = median(recent)
    prior = ratios[:-TREND_WINDOW] if len(ratios) > TREND_WINDOW else []
    if len(prior) < MIN_RECORDS_FOR_TREND:
        return Trend(recent_median, None, "unknown")
    prior_median = median(prior)
    if prior_median == 0:
        return Trend(recent_median, prior_median, "unknown")
    change = recent_median / prior_median
    if change > WORSE_TREND_RATIO:
        verdict = "worsening"
    elif change < BETTER_TREND_RATIO:
        verdict = "improving"
    else:
        verdict = "flat"
    return Trend(recent_median, prior_median, verdict)


# ---------------------------------------------------------------------------
# Audit

@dataclass
class Audit:
    records: List[Record]
    skipped: int
    tax_rate: float            # median ratio
    p80_ratio: float
    spread_ratio: float        # p80 / median
    bracket: str
    bracket_label: str
    tax_paid: float            # total days paid to optimism, sum(actual-estimate)
    early_share: float         # share of records with ratio < 1
    accounts: List[TagAccount]
    trend: Trend
    flags: List[str]

    @property
    def quotable(self) -> bool:
        return len(self.records) >= MIN_RECORDS_FOR_QUOTE


def audit_ledger(records: List[Record], skipped: int) -> Audit:
    if not records:
        raise LedgerError("ledger has no valid records")
    ratios = sorted(ratios_of(records))
    tax_rate = median(ratios)
    p80 = quantile(ratios, 0.8)
    spread = (p80 / tax_rate) if tax_rate > 0 else float("inf")
    bracket, label = bracket_for(tax_rate)
    tax_paid = sum(rec.actual - rec.estimate for rec in records)
    early_share = sum(1 for r in ratios if r < 1.0) / len(ratios)
    accounts = tag_accounts(records)
    trend = calibration_trend(records)

    flags: List[str] = []
    if not audit_quotable(len(records)):
        flags.append(
            f"TOO FEW RECORDS ({len(records)} < {MIN_RECORDS_FOR_QUOTE}) — "
            f"quotes refused: a median of {len(records)} coin flips is still a coin flip"
        )
    if len(records) >= MIN_RECORDS_FOR_QUOTE and spread > SPREAD_FLAG_RATIO:
        flags.append(
            f"FRAGMENTED CALIBRATION (p80/median = {spread:.2f}x > {SPREAD_RATIO_TXT}) — "
            f"you are not one tax rate, you are several: tag your tasks and read per-tag"
        )
    if trend.verdict == "worsening":
        flags.append(
            f"CALIBRATION WORSENING (recent {trend.recent_median:.2f}x vs prior "
            f"{trend.prior_median:.2f}x) — the tax is going up, not down"
        )
    if len(records) >= MIN_RECORDS_FOR_QUOTE and early_share > SANDBAG_SHARE:
        flags.append(
            f"SANDBAGGING SUSPECTED ({early_share * 100:.0f}% of work finished early) — "
            f"your numbers hide buffer; your quotes are padded, your sprint tails idle"
        )
    return Audit(records, skipped, tax_rate, p80, spread, bracket, label,
                 tax_paid, early_share, accounts, trend, flags)


SPREAD_RATIO_TXT = f"{SPREAD_FLAG_RATIO:.1f}"


def audit_quotable(n: int) -> bool:
    return n >= MIN_RECORDS_FOR_QUOTE


# ---------------------------------------------------------------------------
# Output

def fmt_days(x: float) -> str:
    return f"{x:.1f}"


def build_report(audit: Audit, ledger_path: str) -> str:
    lines: List[str] = []
    n = len(audit.records)
    lines.append(f"-- Optimism Tax ledger: {ledger_path}")
    if audit.skipped:
        lines.append(f"   (warning: {audit.skipped} unreadable line(s) skipped)")
    lines.append(f"  records                 : {n}")
    lines.append(
        f"  median inflation        : {audit.tax_rate:.2f}x   <- your optimism tax rate"
    )
    lines.append(f"  p80 inflation           : {audit.p80_ratio:.2f}x   (the 1-in-5 late quote)")
    lines.append(f"  bracket                 : {audit.bracket_label}")
    lines.append(
        f"  total tax paid          : {fmt_days(audit.tax_paid)} days "
        f"(sum of actual - estimate across {n} tasks)"
    )
    early_pct = audit.early_share * 100
    lines.append(f"  finished early          : {early_pct:.0f}% of records (ratio < 1)")

    lines.append("")
    lines.append("  per-tag distortion ledger (typical inflation by task type):")
    for acc in audit.accounts:
        if acc.median_ratio is None:
            lines.append(
                f"    {acc.tag:<16} n={len(acc.records):<3}  thin "
                f"(< {MIN_RECORDS_FOR_TAG_RATE} records: no rate yet)"
            )
        else:
            lines.append(
                f"    {acc.tag:<16} n={len(acc.records):<3}  {acc.median_ratio:.2f}x median"
            )

    lines.append("")
    if audit.trend.verdict == "unknown":
        lines.append(
            f"  trend                   : recent {audit.trend.recent_median:.2f}x "
            f"(need {MIN_RECORDS_FOR_TREND}+ older records for a verdict)"
        )
    else:
        verb = {
            "worsening": "WORSENING — tax rising",
            "improving": "improving — you are calibrating down",
            "flat": "flat — stable tax rate",
        }[audit.trend.verdict]
        lines.append(
            f"  trend                   : recent {audit.trend.recent_median:.2f}x vs "
            f"prior {audit.trend.prior_median:.2f}x — {verb}"
        )

    if audit.flags:
        lines.append("")
        lines.append("  red flags:")
        for flag in audit.flags:
            lines.append(f"    * {flag}")
    else:
        lines.append("")
        lines.append("  no red flags — ledger is quotable and stable")

    lines.append("")
    if audit.quotable:
        lines.append(
            f"  next time you say 'X days': X x {audit.tax_rate:.2f} = what you mean, "
            f"X x {audit.p80_ratio:.2f} = what you should promise"
        )
    else:
        lines.append(
            f"  quotes refused until {MIN_RECORDS_FOR_QUOTE} records — "
            f"finish more work first"
        )
    return "\n".join(lines)


def build_quote(audit: Audit, estimate: float, tag: Optional[str]) -> str:
    """Calibrated price for a promise. Raises QuoteRefused when unquotable."""
    basis_records = audit.records
    basis_note = "whole ledger"
    if tag is not None:
        acc = next((a for a in audit.accounts if a.tag == tag), None)
        if acc is None:
            raise QuoteRefused(
                f"no records tagged '{tag}' — nothing to calibrate against"
            )
        if len(acc.records) < MIN_RECORDS_FOR_QUOTE:
            basis_records = audit.records
            basis_note = (
                f"whole ledger (only {len(acc.records)} record(s) tagged "
                f"'{tag}' — below the {MIN_RECORDS_FOR_QUOTE} needed to "
                f"calibrate a tag rate)"
            )
        else:
            basis_records = acc.records
            basis_note = f"{len(basis_records)} records tagged '{tag}'"
    if len(audit.records) < MIN_RECORDS_FOR_QUOTE:
        raise QuoteRefused(
            f"only {len(audit.records)} record(s) in the ledger — "
            f"{MIN_RECORDS_FOR_QUOTE} needed before any quote is honest"
        )
    ratios = sorted(ratios_of(basis_records))
    med = median(ratios)
    p80 = quantile(ratios, 0.8)
    lines = [
        f"  estimate: {fmt_days(estimate)} days"
        + (f", tag={tag}" if tag else ""),
        f"  basis   : {basis_note}",
    ]
    lines.append(f"  median quote (P50): {fmt_days(estimate * med)} days  "
                 f"({fmt_days(estimate)} x {med:.2f})")
    lines.append(f"  safe quote    (P80): {fmt_days(estimate * p80)} days  "
                 f"({fmt_days(estimate)} x {p80:.2f}) — late 1 time in 5")
    lines.append("  estimation is prophecy; this is what your own prophecy is worth.")
    return "\n".join(lines)


def audit_to_json(audit: Audit, ledger_path: str) -> dict:
    return {
        "ledger": ledger_path,
        "records": len(audit.records),
        "skipped": audit.skipped,
        "tax_rate": round(audit.tax_rate, 4),
        "p80_ratio": round(audit.p80_ratio, 4),
        "spread": round(audit.spread_ratio, 4),
        "bracket": audit.bracket,
        "tax_paid_days": round(audit.tax_paid, 2),
        "early_share": round(audit.early_share, 4),
        "tags": [
            {
                "tag": a.tag,
                "n": len(a.records),
                "median_ratio": round(a.median_ratio, 4) if a.median_ratio else None,
                "thin": a.thin,
            }
            for a in audit.accounts
        ],
        "trend": {
            "recent_median": round(audit.trend.recent_median, 4),
            "prior_median": round(audit.trend.prior_median, 4)
            if audit.trend.prior_median is not None else None,
            "verdict": audit.trend.verdict,
        },
        "flags": audit.flags,
        "quotable": audit.quotable,
    }


# ---------------------------------------------------------------------------
# Commands

def cmd_record(args: argparse.Namespace) -> int:
    import os
    path = args.file
    rec = parse_record(
        {
            "estimate": args.estimate,
            "actual": args.actual,
            "tag": args.tag,
            "note": args.note,
            "date": args.date,
        },
        0,
    )
    new_line = json.dumps(
        {
            "date": rec.date,
            "estimate": rec.estimate,
            "actual": rec.actual,
            "tag": rec.tag,
            "note": rec.note,
        },
        ensure_ascii=False,
    )
    existed = os.path.exists(path)
    if existed:
        records, _ = load_ledger(path)
    else:
        records = []
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(new_line + "\n")
    print(
        f"  recorded: r = {rec.ratio:.2f}x  (est {fmt_days(rec.estimate)} -> "
        f"act {fmt_days(rec.actual)}"
        + (f", {rec.tag}" if rec.tag != "untagged" else "")
        + f")  ledger now has {len(records) + 1} record(s)"
    )
    if not audit_quotable(len(records) + 1):
        print(
            f"  (quotes unlock at {MIN_RECORDS_FOR_QUOTE} records — "
            f"{MIN_RECORDS_FOR_QUOTE - len(records) - 1} to go)"
        )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    records, skipped = load_ledger(args.file)
    audit = audit_ledger(records, skipped)
    if args.format == "json":
        print(json.dumps(audit_to_json(audit, args.file), ensure_ascii=False, indent=2))
    else:
        print(build_report(audit, args.file))
    if args.fail_under is not None and audit.tax_rate > args.fail_under:
        print(
            f"  gate: tax rate {audit.tax_rate:.2f}x exceeds --fail-under "
            f"{args.fail_under:.2f}x",
            file=sys.stderr,
        )
        return 4
    return 0


def cmd_quote(args: argparse.Namespace) -> int:
    records, skipped = load_ledger(args.file)
    if skipped:
        print(
            f"  (warning: {skipped} unreadable line(s) skipped)",
            file=sys.stderr,
        )
    audit = audit_ledger(records, skipped)
    try:
        text = build_quote(audit, args.estimate, args.tag)
    except QuoteRefused as exc:
        print(f"  QUOTE REFUSED: {exc}", file=sys.stderr)
        return 3
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="optimism_tax",
        description="乐观税 — audit your own estimates against what actually happened",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser(
        "record", help="append one (estimate, actual) receipt to the ledger"
    )
    p_record.add_argument("--estimate", type=float, required=True,
                          help="what you promised, in days (must be > 0)")
    p_record.add_argument("--actual", type=float, required=True,
                          help="what it actually took, in days (>= 0)")
    p_record.add_argument("--tag", default=None,
                          help="task type, e.g. research / feature / bugfix")
    p_record.add_argument("--note", default=None, help="one line of context")
    p_record.add_argument("--date", default=None,
                          help="ISO date (default: today)")
    p_record.add_argument("--file", default=DEFAULT_LEDGER,
                          help=f"ledger path (default: {DEFAULT_LEDGER})")
    p_record.set_defaults(func=cmd_record)

    p_report = sub.add_parser("report", help="the full optimism tax audit")
    p_report.add_argument("--file", default=DEFAULT_LEDGER,
                          help=f"ledger path (default: {DEFAULT_LEDGER})")
    p_report.add_argument("--format", choices=("text", "json"), default="text")
    p_report.add_argument("--fail-under", type=float, default=None, metavar="X",
                          help="exit 4 if the tax rate exceeds X")
    p_report.set_defaults(func=cmd_report)

    p_quote = sub.add_parser(
        "quote", help="price the next promise with your own track record"
    )
    p_quote.add_argument("estimate", type=float,
                         help="the number of days you were about to say")
    p_quote.add_argument("--tag", default=None,
                         help="calibrate against this tag when it has enough records")
    p_quote.add_argument("--file", default=DEFAULT_LEDGER,
                         help=f"ledger path (default: {DEFAULT_LEDGER})")
    p_quote.set_defaults(func=cmd_quote)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LedgerError as exc:
        print(f"  error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
