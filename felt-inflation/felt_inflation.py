#!/usr/bin/env python3
"""felt-inflation · 体感通胀 / Felt Inflation

The official CPI says everything is calm; your receipts say otherwise.
The gap is not a feeling problem, it is a measurement problem: the
official basket (housing, cars, education weights) is not YOUR basket,
and official index practice absorbs the cheap swaps you were forced into,
which is exactly why the published number always feels too gentle.

felt-inflation turns a hand-kept receipts ledger (TSV) into four accounts:

  rate    your personal inflation: Laspeyres (fixed basket = "keep buying
          exactly the same stuff"), Paasche, Fisher, cumulative and
          annualized, with coverage and imputation disclosed in full
  board   contribution decomposition: which items are driving your
          inflation, in percentage points, red and black list
  drift   trade-down detection: base items that quietly vanished from
          your cart, the cheaper same-category newcomers that replaced
          them, and the concession gap between your basket and your bill
  power   the same basket translated into money: extra cost per month,
          per year, and how much basket 100 yuan still buys
  months  ledger density map, to pick a sane base month

Zero dependency: Python 3.8+ standard library only. Receipts are
consumption privacy — nothing leaves this machine.

Ledger format (TSV, one purchase line per row):
    date        YYYY-MM-DD
    item        stable item slug you keep consistent over time
    category    free-form group (grocery / transport / dining ...)
    qty         units bought in this line (> 0)
    price       total paid for this line (> 0)
    store       optional free text

Lines starting with '#' are comments. Malformed rows are skipped and
counted, never fatal.
"""

import argparse
import io
import json
import math
import os
import sys
from collections import defaultdict

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_TOO_THIN = 3
EXIT_RED_LINE = 4

LEDGER_COLUMNS = ("date", "item", "category", "qty", "price", "store")


# ---------------------------------------------------------------- months

def month_index(ym):
    y, m = ym
    return y * 12 + (m - 1)


def month_str(ym):
    return "%04d-%02d" % ym


def parse_month(text):
    parts = text.split("-")
    if len(parts) != 2:
        raise ValueError("month must look like YYYY-MM: %r" % text)
    y, m = int(parts[0]), int(parts[1])
    if not (1 <= m <= 12):
        raise ValueError("month out of range: %r" % text)
    return (y, m)


def shift_month(ym, k):
    idx = month_index(ym) + k
    return (idx // 12, idx % 12 + 1)


def month_range_inclusive(start_ym, end_ym):
    out = []
    cur = start_ym
    while month_index(cur) <= month_index(end_ym):
        out.append(cur)
        cur = shift_month(cur, 1)
    return out


# ---------------------------------------------------------------- ledger

class Row(object):
    __slots__ = ("date", "month", "item", "category", "qty", "price", "store", "line_no")

    def __init__(self, date, month, item, category, qty, price, store, line_no):
        self.date = date
        self.month = month
        self.item = item
        self.category = category
        self.qty = qty
        self.price = price
        self.store = store
        self.line_no = line_no

    @property
    def unit_price(self):
        return self.price / self.qty


def parse_ledger(path):
    """Parse a receipts TSV. Returns (rows, skipped) with rows sorted by date."""
    rows, skipped = [], []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 1 and parts[0].strip().lower() == "date":
                continue  # header line
            if len(parts) != 6:
                skipped.append((line_no, "expected 6 columns, got %d" % len(parts)))
                continue
            date_s, item, category, qty_s, price_s, store = (p.strip() for p in parts)
            try:
                y, m, d = date_s.split("-")
                month = (int(y), int(m))
                date_key = (int(y), int(m), int(d))
                if not (1 <= month[1] <= 12) or not (1 <= date_key[2] <= 31):
                    raise ValueError(date_s)
            except ValueError:
                skipped.append((line_no, "bad date %r" % date_s))
                continue
            try:
                qty = float(qty_s)
                price = float(price_s)
            except ValueError:
                skipped.append((line_no, "bad qty/price %r %r" % (qty_s, price_s)))
                continue
            if not item:
                skipped.append((line_no, "empty item name"))
                continue
            if qty <= 0 or price <= 0:
                skipped.append((line_no, "qty and price must be > 0"))
                continue
            rows.append(Row(date_key, month, item, category or "uncategorized",
                            qty, price, store, line_no))
    rows.sort(key=lambda r: r.date)
    return rows, skipped


def monthly_unit_prices(rows):
    """item -> month -> unit price (monthly total spend / total qty)."""
    acc = defaultdict(lambda: [0.0, 0.0])  # (item, month) -> [qty, spend]
    for r in rows:
        cell = acc[(r.item, r.month)]
        cell[0] += r.qty
        cell[1] += r.price
    out = defaultdict(dict)
    for (item, month), (qty, spend) in acc.items():
        out[item][month] = spend / qty
    return out


def monthly_qty(rows):
    acc = defaultdict(lambda: defaultdict(float))  # item -> month -> qty
    for r in rows:
        acc[r.item][r.month] += r.qty
    return acc


def month_spend(rows):
    acc = defaultdict(float)
    for r in rows:
        acc[r.month] += r.price
    return acc


def data_months(rows):
    return sorted({r.month for r in rows})


# ------------------------------------------------------------ index core

class Basket(object):
    """The base-period basket and everything measurable about it.

    base basket : items purchased in the base month, base qty x base unit
                  price as weights (Laspeyres).
    evaluable   : base items with at least one purchase in (base, period].
                  Only these get a period price (exact or carried forward);
                  the rest are "uncovered" and reported, never silently
                  dropped.
    imputed     : evaluable items whose period price is a carry-forward of
                  their last observed price, not a period-month purchase.
    """

    def __init__(self, rows, base, period):
        self.base = base
        self.period = period
        self.units = monthly_unit_prices(rows)
        self.qtys = monthly_qty(rows)
        base_rows = [r for r in rows if r.month == base]
        counts = defaultdict(float)
        for r in base_rows:
            counts[r.item] += r.qty
        self.base_items = sorted(counts)
        self.base_qty = {i: counts[i] for i in self.base_items}
        self.base_price = {i: self.units[i][base] for i in self.base_items}
        self.category = {}
        for r in rows:
            self.category.setdefault(r.item, r.category)

        after = month_range_inclusive(shift_month(base, 1), period)
        self.evaluable, self.uncovered = [], []
        for item in self.base_items:
            if any(m in self.units[item] for m in after):
                self.evaluable.append(item)
            else:
                self.uncovered.append(item)

        self.period_price, self.imputed = {}, []
        for item in self.evaluable:
            observed = self.units[item]
            if period in observed:
                self.period_price[item] = observed[period]
            else:
                past = [m for m in observed if month_index(m) < month_index(period)
                        and month_index(m) > month_index(base)]
                last = max(past)
                self.period_price[item] = observed[last]
                self.imputed.append(item)

    # -- indexes over the evaluable set -----------------------------------
    def cost(self, price_map):
        return sum(price_map[i] * self.base_qty[i] for i in self.evaluable)

    @property
    def laspeyres(self):
        return self.cost(self.period_price) / self.cost(self.base_price)

    def paasche(self):
        common = [i for i in self.evaluable if self.period in self.units[i]]
        if not common:
            return None
        num = sum(self.units[i][self.period] * self.qtys[i][self.period] for i in common)
        den = sum(self.base_price[i] * self.qtys[i][self.period] for i in common)
        return num / den

    def fisher(self):
        p = self.paasche()
        return math.sqrt(self.laspeyres * p) if p else None

    def annualized(self, cumulative):
        n = month_index(self.period) - month_index(self.base)
        return (1.0 + cumulative) ** (12.0 / n) - 1.0

    def contributions(self):
        """Per-item contribution to Laspeyres inflation, in percentage points.

        (p1 - p0) * q0 / sum(p0 * q0). The contributions over the
        evaluable set sum exactly to (L - 1) * 100 — decomposition identity.
        """
        den = self.cost(self.base_price)
        out = []
        for i in self.evaluable:
            contrib = (self.period_price[i] - self.base_price[i]) * self.base_qty[i] / den
            out.append((i, contrib * 100.0))
        return out


def resolve_window(rows, base, period):
    """Default base/period from the ledger; validate against data range."""
    months = data_months(rows)
    if not months:
        raise SystemExitUsage("ledger has no usable rows")
    lo, hi = months[0], months[-1]
    b = base if base else lo
    b = base if base else lo
    p = period if period else hi
    if month_index(b) < month_index(lo) or month_index(b) > month_index(hi):
        raise SystemExitUsage("base %s outside ledger range %s..%s"
                              % (month_str(b), month_str(lo), month_str(hi)))
    if month_index(p) > month_index(hi) or month_index(p) < month_index(lo):
        raise SystemExitUsage("period %s outside ledger range %s..%s"
                              % (month_str(p), month_str(lo), month_str(hi)))
    if month_index(p) <= month_index(b):
        raise SystemExitUsage("period must be strictly after base (%s vs %s)"
                              % (month_str(p), month_str(b)))
    return b, p


class SystemExitUsage(SystemExit):
    def __init__(self, message):
        super(SystemExitUsage, self).__init__(EXIT_USAGE, "error: %s" % message)


# ------------------------------------------------------------- formatting

def fmt_money(x):
    return "\u00a5%s" % format(round(x, 2), ",.2f")


def fmt_pct(x, digits=2):
    return "%+.*f%%" % (digits, x)


def fmt_pp(x):
    return "%+.2fpp" % x


def fmt_month(ym):
    return month_str(ym)


# ---------------------------------------------------------------- reports

def render_rate(basket, rows, red_line, ledger_path):
    cum = (basket.laspeyres - 1.0) * 100.0
    annual = basket.annualized(basket.laspeyres - 1.0) * 100.0
    paasche = basket.paasche()
    fisher = basket.fisher()
    n = len(basket.base_items)
    coverage = len(basket.evaluable) / float(n) * 100.0
    lines = []
    lines.append("FELT INFLATION \u00b7 rate")
    lines.append("=" * 60)
    lines.append("ledger          %s" % os.path.basename(ledger_path))
    lines.append("base period     %s (basket %d items, %d evaluated, %s / month)"
                 % (fmt_month(basket.base), n, len(basket.evaluable),
                    fmt_money(basket.cost(basket.base_price))))
    lines.append("test period     %s" % fmt_month(basket.period))
    lines.append("span            %d months"
                 % (month_index(basket.period) - month_index(basket.base)))
    lines.append("")
    lines.append("BASKET INTEGRITY")
    lines.append("-" * 60)
    lines.append("base basket     %d items" % n)
    lines.append("evaluated       %d (coverage %.1f%%)"
                 % (len(basket.evaluable), coverage))
    if basket.uncovered:
        lines.append("uncovered       %d  %s"
                     % (len(basket.uncovered), ", ".join(basket.uncovered)))
    lines.append("imputed prices  %d of %d (carried forward from last purchase)"
                 % (len(basket.imputed), len(basket.evaluable)))
    if basket.imputed:
        lines.append("                %s" % ", ".join(basket.imputed))
    if coverage < 60.0:
        lines.append("THIN: coverage under 60%% - the index below leans on")
        lines.append("      stale prices; collect more receipts before quoting it.")
    lines.append("")
    lines.append('PRICE INDEX (fixed basket = "keep buying exactly the same stuff")')
    lines.append("-" * 60)
    lines.append("Laspeyres       %s cumulative   %s annualized"
                 % (fmt_pct(cum), fmt_pct(annual)))
    if paasche is not None:
        lines.append("Paasche         %s cumulative   (current quantities)"
                     % fmt_pct((paasche - 1.0) * 100.0))
    if fisher is not None:
        lines.append("Fisher          %s cumulative   (sqrt of the two)"
                     % fmt_pct((fisher - 1.0) * 100.0))
    lines.append("red line        %.1f%% annualized" % red_line)
    lines.append("")
    extra = fmt_money(basket.cost(basket.period_price) - basket.cost(basket.base_price))
    if annual >= red_line:
        lines.append("verdict         OVER THE RED LINE - your prices rose %s"
                     % fmt_pct(annual))
        lines.append("                annualized; the identical basket now costs %s"
                     % extra)
        lines.append("                more per month. The official average is not")
        lines.append("                your average.")
    else:
        lines.append("verdict         WITHIN THE RED LINE - %s annualized, %s"
                     % (fmt_pct(annual), extra))
        lines.append("                extra per month for the identical basket.")
    return "\n".join(lines)


def render_board(basket, top_n):
    contribs = basket.contributions()
    rows = sorted(contribs, key=lambda t: (-t[1], t[0]))
    total = (basket.laspeyres - 1.0) * 100.0
    lines = []
    lines.append("PRICE BOARD \u00b7 who is driving your inflation")
    lines.append("=" * 60)
    lines.append("base %s \u2192 period %s   total fixed-basket inflation %s"
                 % (fmt_month(basket.base), fmt_month(basket.period), fmt_pct(total)))
    lines.append("")
    lines.append("%-24s %-13s %9s %9s %8s %10s" %
                 ("item", "category", "p0", "p1", "delta", "contribution"))
    for rank, (item, pp) in enumerate(rows[:top_n]):
        p0, p1 = basket.base_price[item], basket.period_price[item]
        delta = (p1 / p0 - 1.0) * 100.0
        mark = ""
        if pp > 0 and rank == 0:
            mark = "  <- driver #1"
        elif pp < 0:
            mark = "  (cooling)"
        lines.append("%-24s %-13s %9s %9s %7.1f%% %10s%s"
                     % (item, basket.category.get(item, "-")[:13],
                        "%.2f" % p0, "%.2f" % p1, delta, fmt_pp(pp), mark))
    shown = sum(pp for _, pp in rows[:top_n])
    lines.append("")
    positive = [pp for _, pp in rows if pp > 0]
    if len(positive) >= 3:
        top2 = sum(sorted(positive, reverse=True)[:2])
        if total > 0:
            lines.append("top-2 concentration: %s of %s (%.1f%%) - %s"
                         % (fmt_pp(top2), fmt_pp(total), top2 / total * 100.0,
                            "half your inflation comes from two items"
                            if top2 / total >= 0.5 else
                            "your inflation is broad-based"))
    flat = [i for i, pp in rows if abs(pp) < 0.005]
    if flat:
        lines.append("flat (no push): %s" % ", ".join(flat))
    return "\n".join(lines)


def render_drift(basket, rows, window):
    win_months = month_range_inclusive(shift_month(basket.period, -(window - 1)),
                                       basket.period)
    win_set = set(win_months)
    win_items = defaultdict(float)   # item -> qty seen in window
    for r in rows:
        if r.month in win_set:
            win_items[r.item] += r.qty

    abandoned = [i for i in basket.base_items if win_items[i] == 0.0]
    newcomers = [i for i in sorted(win_items) if i not in basket.base_items]

    def window_unit_price(item):
        months = [m for m in basket.units[item] if m in win_set]
        if not months:
            return None
        q = sum(basket.qtys[item][m] for m in months)
        s = sum(basket.units[item][m] * basket.qtys[item][m] for m in months)
        return s / q

    def last_price(item):
        past = [m for m in basket.units[item]
                if month_index(m) <= month_index(basket.period)]
        return basket.units[item][max(past)]

    lines = []
    lines.append("TRADE-DOWN LEDGER \u00b7 did you quietly switch to cheaper stuff?")
    lines.append("=" * 60)
    lines.append("window: last %d months before/at %s (%s)"
                 % (window, fmt_month(basket.period),
                    " \u2192 ".join([fmt_month(win_months[0]), fmt_month(win_months[-1])])))
    lines.append("")
    lines.append("abandoned (base-basket items absent from the window):")
    if abandoned:
        for i in sorted(abandoned, key=last_price, reverse=True):
            lines.append("  %-24s last bought at %s" % (i, fmt_money(last_price(i))))
    else:
        lines.append("  none - you still buy everything you bought in %s"
                     % fmt_month(basket.base))
    lines.append("")

    pairs, used = [], set()
    for old in sorted(abandoned, key=last_price, reverse=True):
        old_p = last_price(old)
        cands = [(abs(window_unit_price(nw) - old_p), nw)
                 for nw in newcomers if nw not in used
                 and basket.category.get(nw) == basket.category.get(old)
                 and window_unit_price(nw) is not None
                 and window_unit_price(nw) < old_p]
        if cands:
            _, nw = min(cands)
            used.add(nw)
            pairs.append((old, nw, old_p, window_unit_price(nw)))

    lines.append("trade-down pairs (same category, cheaper newcomer):")
    if pairs:
        for old, nw, old_p, new_p in pairs:
            lines.append("  %-24s %s -> %-24s %s  (%s)"
                         % (old, fmt_money(old_p), nw, fmt_money(new_p),
                            fmt_pct((new_p / old_p - 1.0) * 100.0)))
    else:
        lines.append("  none")
    unpaired = [n for n in newcomers if n not in used]
    if unpaired:
        lines.append("newcomers with no abandoned partner: %s" % ", ".join(unpaired))
    lines.append("")

    spends = month_spend(rows)
    win_spend_avg = sum(spends[m] for m in win_months) / float(len(win_months))
    base_spend = spends[basket.base]
    actual = (win_spend_avg / base_spend - 1.0) * 100.0
    fixed = (basket.laspeyres - 1.0) * 100.0
    gap = fixed - actual
    lines.append("THE CONCESSION GAP")
    lines.append("-" * 60)
    lines.append("fixed-basket inflation (keep the old cart):  %s" % fmt_pct(fixed))
    lines.append("actual bill growth  (%s/mo vs base %s/mo): %s"
                 % (fmt_money(win_spend_avg), fmt_money(base_spend), fmt_pct(actual)))
    lines.append("concession gap (fixed - actual):             %s" % fmt_pp(gap))
    lines.append("")
    if gap > 0.5:
        lines.append("verdict  Your bill rose less than your basket - the %s"
                     % fmt_pp(gap))
        lines.append("         difference is the concession you already made:")
        lines.append("         cheaper swaps and smaller cart. The published")
        lines.append("         average absorbs this; here it has a name.")
    elif gap < -0.5:
        lines.append("verdict  Your bill rose MORE than your basket - you are")
        lines.append("         buying more/better, not less. No downgrade here.")
    else:
        lines.append("verdict  Bill and basket move together - no measurable")
        lines.append("         trade-down in this window.")
    return "\n".join(lines)


def render_power(basket, cash):
    c0 = basket.cost(basket.base_price)
    c1 = basket.cost(basket.period_price)
    delta = c1 - c0
    cum = (basket.laspeyres - 1.0) * 100.0
    lines = []
    lines.append("PURCHASING POWER \u00b7 the same basket, translated into money")
    lines.append("=" * 60)
    lines.append("basket month cost  %s -> %s  (%d items, base %s)"
                 % (fmt_money(c0), fmt_money(c1), len(basket.evaluable),
                    fmt_month(basket.base)))
    lines.append("extra cost         %s per month   %s per year"
                 % (fmt_money(delta), fmt_money(delta * 12.0)))
    lines.append("cash purchasing power: %s in %s buys what %s bought in %s"
                 % (fmt_money(cash), fmt_month(basket.period),
                    fmt_money(cash * basket.laspeyres ** -1.0), fmt_month(basket.base)))
    lines.append("cumulative inflation over the span: %s" % fmt_pct(cum))
    return "\n".join(lines)


def render_months(rows):
    spends = month_spend(rows)
    items = defaultdict(set)
    counts = defaultdict(int)
    for r in rows:
        items[r.month].add(r.item)
        counts[r.month] += 1
    lines = []
    lines.append("LEDGER DENSITY \u00b7 pick a base month you actually recorded well")
    lines.append("=" * 60)
    for m in data_months(rows):
        lines.append("%s   %3d rows  %2d items  %s"
                     % (fmt_month(m), counts[m], len(items[m]), fmt_money(spends[m])))
    return "\n".join(lines)


# ------------------------------------------------------------------ json

def rate_json(basket, red_line):
    cum = (basket.laspeyres - 1.0) * 100.0
    annual = basket.annualized(basket.laspeyres - 1.0) * 100.0
    paasche = basket.paasche()
    fisher = basket.fisher()
    return {
        "base": month_str(basket.base),
        "period": month_str(basket.period),
        "span_months": month_index(basket.period) - month_index(basket.base),
        "basket_size": len(basket.base_items),
        "evaluated": len(basket.evaluable),
        "coverage_pct": round(len(basket.evaluable) / len(basket.base_items) * 100.0, 2),
        "imputed": basket.imputed,
        "uncovered": basket.uncovered,
        "laspeyres_cum_pct": round(cum, 4),
        "paasche_cum_pct": round((paasche - 1.0) * 100.0, 4) if paasche else None,
        "fisher_cum_pct": round((fisher - 1.0) * 100.0, 4) if fisher else None,
        "annualized_pct": round(annual, 4),
        "red_line_pct": red_line,
        "over_red_line": annual >= red_line,
        "basket_cost_base": round(basket.cost(basket.base_price), 2),
        "basket_cost_period": round(basket.cost(basket.period_price), 2),
    }


# ------------------------------------------------------------------- cli

def build_basket(rows, args):
    try:
        base = parse_month(args.base) if getattr(args, "base", None) else None
        period = parse_month(args.period) if getattr(args, "period", None) else None
    except ValueError as exc:
        raise SystemExitUsage(str(exc))
    b, p = resolve_window(rows, base, period)
    return Basket(rows, b, p)


def cmd_rate(args, out):
    rows, skipped = parse_ledger(args.ledger)
    if skipped:
        print("note: skipped %d malformed rows" % len(skipped), file=sys.stderr)
    basket = build_basket(rows, args)
    red_line = args.red_line
    n = len(basket.base_items)
    coverage = len(basket.evaluable) / float(n)
    if n < 5 or coverage < 0.5:
        print(render_rate(basket, rows, red_line, args.ledger), file=out)
        print("", file=out)
        print("REFUSED: %s - a conclusion from this ledger would be"
              % ("base basket under 5 items" if n < 5
                 else "coverage %.0f%% is below 50%%" % (coverage * 100.0)),
              file=out)
        print("statistics, not insight. Record more months first.", file=out)
        return EXIT_TOO_THIN
    print(render_rate(basket, rows, red_line, args.ledger), file=out)
    annual = basket.annualized(basket.laspeyres - 1.0) * 100.0
    return EXIT_RED_LINE if annual >= red_line else EXIT_OK


def cmd_board(args, out):
    rows, _ = parse_ledger(args.ledger)
    basket = build_basket(rows, args)
    print(render_board(basket, args.top), file=out)
    return EXIT_OK


def cmd_drift(args, out):
    rows, _ = parse_ledger(args.ledger)
    basket = build_basket(rows, args)
    print(render_drift(basket, rows, args.window), file=out)
    return EXIT_OK


def cmd_power(args, out):
    rows, _ = parse_ledger(args.ledger)
    basket = build_basket(rows, args)
    print(render_power(basket, args.cash), file=out)
    return EXIT_OK


def cmd_months(args, out):
    rows, _ = parse_ledger(args.ledger)
    print(render_months(rows), file=out)
    return EXIT_OK


def emit_json(payload, out):
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="felt_inflation.py",
        description="Felt Inflation - your receipts, your own CPI.")
    sub = parser.add_subparsers(dest="command")

    def add_common(sp, needs_ledger=True):
        sp.add_argument("ledger", nargs="?" if not needs_ledger else None,
                        help="receipts ledger TSV (date/item/category/qty/price/store)")
        sp.add_argument("--base", help="base month YYYY-MM (default: first month in ledger)")
        sp.add_argument("--period", help="test month YYYY-MM (default: last month in ledger)")
        sp.add_argument("--format", choices=["text", "json"], default="text")

    p_rate = sub.add_parser("rate", help="personal inflation index (exit 4 over red line)")
    add_common(p_rate)
    p_rate.add_argument("--red-line", type=float, default=5.0,
                        help="annualized red line in %% (default 5.0)")
    p_rate.set_defaults(fn=cmd_rate)

    p_board = sub.add_parser("board", help="contribution red/black list")
    add_common(p_board)
    p_board.add_argument("--top", type=int, default=12)
    p_board.set_defaults(fn=cmd_board)

    p_drift = sub.add_parser("drift", help="trade-down detection + concession gap")
    add_common(p_drift)
    p_drift.add_argument("--window", type=int, default=3,
                         help="recent months defining 'still buying' (default 3)")
    p_drift.set_defaults(fn=cmd_drift)

    p_power = sub.add_parser("power", help="translate inflation into yuan")
    add_common(p_power)
    p_power.add_argument("--cash", type=float, default=100.0,
                         help="cash amount to translate (default 100)")
    p_power.set_defaults(fn=cmd_power)

    p_months = sub.add_parser("months", help="ledger density map")
    p_months.add_argument("ledger")
    p_months.add_argument("--format", choices=["text", "json"], default="text")
    p_months.set_defaults(fn=cmd_months, needs_ledger=True)

    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help()
        return EXIT_USAGE
    if not args.ledger:
        print("error: ledger path required", file=sys.stderr)
        return EXIT_USAGE

    out = io.StringIO()
    fmt = getattr(args, "format", "text")
    code = EXIT_OK
    try:
        if fmt == "json" and args.command == "rate":
            rows, _ = parse_ledger(args.ledger)
            basket = build_basket(rows, args)
            payload = rate_json(basket, args.red_line)
            n = len(basket.base_items)
            coverage = len(basket.evaluable) / float(n)
            code = EXIT_TOO_THIN if (n < 5 or coverage < 0.5) else (
                EXIT_RED_LINE if payload["over_red_line"] else EXIT_OK)
            payload["exit_code"] = code
            emit_json(payload, out)
        elif fmt == "json":
            rows, _ = parse_ledger(args.ledger)
            basket = build_basket(rows, args)
            if args.command == "board":
                total = (basket.laspeyres - 1.0) * 100.0
                payload = {
                    "base": month_str(basket.base), "period": month_str(basket.period),
                    "total_cum_pct": round(total, 4),
                    "items": [
                        {"item": i, "category": basket.category.get(i),
                         "p0": round(basket.base_price[i], 4),
                         "p1": round(basket.period_price[i], 4),
                         "contribution_pp": round(pp, 4)}
                        for i, pp in basket.contributions()],
                }
                emit_json(payload, out)
            elif args.command == "drift":
                text = io.StringIO()
                code = cmd_drift(args, text)
                emit_json({"exit_code": code, "report": text.getvalue()}, out)
            elif args.command == "months":
                spends = month_spend(rows)
                per_month_items = defaultdict(set)
                per_month_rows = defaultdict(int)
                for r in rows:
                    per_month_items[r.month].add(r.item)
                    per_month_rows[r.month] += 1
                emit_json({
                    "months": [
                        {"month": month_str(m), "rows": per_month_rows[m],
                         "items": len(per_month_items[m]),
                         "spend": round(spends[m], 2)}
                        for m in data_months(rows)],
                }, out)
            else:
                c0, c1 = basket.cost(basket.base_price), basket.cost(basket.period_price)
                emit_json({
                    "base": month_str(basket.base), "period": month_str(basket.period),
                    "basket_cost_base": round(c0, 2), "basket_cost_period": round(c1, 2),
                    "delta_month": round(c1 - c0, 2), "delta_year": round((c1 - c0) * 12.0, 2),
                    "cash": args.cash,
                    "cash_equivalent_at_base": round(args.cash / basket.laspeyres, 4),
                }, out)
        else:
            code = args.fn(args, out)
    except OSError as exc:
        print("error: cannot read ledger: %s" % exc, file=sys.stderr)
        return EXIT_USAGE

    sys.stdout.write(out.getvalue())
    return code


if __name__ == "__main__":
    sys.exit(main())
