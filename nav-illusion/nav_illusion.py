#!/usr/bin/env python3
"""净值幻觉 · NAV Illusion.

A behavior audit for fund investors. The NAV page prints the fund's
time-weighted return (TWR) — the fund's report card, which pretends your
money was in the whole time. Your money-weighted return (XIRR) remembers
every chase and every panic sell. The difference between the two is the
behavior gap: a tuition bill nobody has ever itemized.

nav-illusion reads two hand-kept ledgers:

  flows.csv — 日期,动作,金额[,净值][,备注]   动作 ∈ 申购/赎回/分红
  navs.csv  — 日期,净值                       复权净值（分红再投口径）

and reports four ledgers of its own:

  report    share-ledger reconciliation + XIRR vs TWR + behavior gap
            verdict (BEAT / DRAG / BLEEDING, exit 4 on BLEEDING)
  flows     flow-by-flow audit: 365d price position per buy, panic
            sells with the 90-day rebound they missed
  simulate  same money, three pairs of hands: actual vs one-shot hold
            vs blind monthly dca
  doctor    data physical exam before you trust any of the above

Honesty clauses: no market APIs — every NAV is user-supplied (use the
fund's 复权净值); T+1 confirmation and fee schedules are not modeled —
record post-fee amounts; dividends are cash in pocket (DIV rows), they
never silently inflate shares; when the data is too thin or pathological
the tool refuses (exit 3) instead of printing a confident nonsense.
This tool audits the past. It is not investment advice.

Zero dependency: Python 3.8+ standard library only. Everything stays local.
"""

import argparse
import csv
import sys
from datetime import date, timedelta

PROG = "nav_illusion.py"

# Verdict thresholds, in percentage points of annualized behavior gap.
DEFAULT_GAP_LINE = -5.0
GAP_BEAT = 0.0

# A buy whose price sits in the top 15% of its trailing-365d range is a
# chase; the bottom 35% is bottom-fishing; between is mid-range.
CHASE_LINE = 0.65
BOTTOM_LINE = 0.35

# A sell during a drawdown deeper than this vs the trailing-180d high is
# a panic sell.
PANIC_DRAWDOWN = 0.10

# Minimum data for any verdict at all.
MIN_NAV_POINTS = 2
MIN_SPAN_DAYS = 180
MIN_XIRR_LEGS = 2

POSITION_WINDOW_DAYS = 365
DRAWDOWN_WINDOW_DAYS = 180
REBOUND_WINDOW_DAYS = 90

ACTION_BUY, ACTION_SELL, ACTION_DIV = "BUY", "SELL", "DIV"
ACTION_ALIASES = {
    "申购": ACTION_BUY, "买入": ACTION_BUY, "买": ACTION_BUY, "buy": ACTION_BUY,
    "赎回": ACTION_SELL, "卖出": ACTION_SELL, "卖": ACTION_SELL, "sell": ACTION_SELL,
    "分红": ACTION_DIV, "派息": ACTION_DIV, "div": ACTION_DIV, "dividend": ACTION_DIV,
}

FLOW_COLUMNS = {
    "date": ("日期", "date"),
    "action": ("动作", "类型", "action"),
    "amount": ("金额", "数额", "amount"),
    "nav": ("净值", "单位净值", "确认净值", "nav"),
    "note": ("备注", "说明", "note"),
}
NAV_COLUMNS = {
    "date": ("日期", "date"),
    "nav": ("净值", "单位净值", "复权净值", "累计净值", "nav"),
}


class Refuse(Exception):
    """Data too thin or pathological to answer — exit 3, never a guess."""


# ---------------------------------------------------------------- parsing

def parse_date(text, where=""):
    s = (text or "").strip()
    for sep in ("-", "/", "."):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    return date(int(parts[0]), int(parts[1]), int(parts[2]))
                except ValueError:
                    break
    raise Refuse("bad date %r%s (want YYYY-MM-DD)" % (text, where))


def parse_amount(text, where):
    s = (text or "").strip().replace(",", "").replace("，", "")
    try:
        value = float(s)
    except ValueError:
        raise Refuse("bad number %r%s" % (text, where))
    if value <= 0:
        raise Refuse("amount must be > 0, got %s%s" % (text, where))
    return value


def parse_nav_value(text, where):
    s = (text or "").strip()
    try:
        value = float(s)
    except ValueError:
        raise Refuse("bad nav %r%s" % (text, where))
    if value <= 0:
        raise Refuse("nav must be > 0, got %s%s" % (text, where))
    return value


def _read_rows(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            return [row for row in csv.reader(fh)
                    if any((cell or "").strip() for cell in row)]
    except FileNotFoundError:
        raise Refuse("file not found: %s" % path)


def _find_columns(header, needed, optional, path):
    cols = {}
    for name in header:
        key = (name or "").strip().lower()
        for canon, aliases in needed.items():
            if key in aliases and canon not in cols:
                cols[canon] = header.index(name)
        for canon, aliases in optional.items():
            if key in aliases and canon not in cols:
                cols[canon] = header.index(name)
    missing = [c for c in needed if c not in cols]
    if missing:
        raise Refuse("%s: missing column(s) %s — headers seen: %s"
                     % (path, "/".join(missing), ",".join(h or "" for h in header)))
    return cols


class Flow(object):
    __slots__ = ("date", "action", "amount", "nav", "note", "line")

    def __init__(self, date, action, amount, nav, note, line):
        self.date = date
        self.action = action
        self.amount = amount
        self.nav = nav
        self.note = note
        self.line = line


def parse_flows(path):
    rows = _read_rows(path)
    if not rows:
        raise Refuse("%s: empty ledger" % path)
    cols = _find_columns(rows[0],
                         {"date": FLOW_COLUMNS["date"],
                          "action": FLOW_COLUMNS["action"],
                          "amount": FLOW_COLUMNS["amount"]},
                         {"nav": FLOW_COLUMNS["nav"],
                          "note": FLOW_COLUMNS["note"]},
                         path)
    flows = []
    for i, row in enumerate(rows[1:], start=2):
        where = " (%s line %d)" % (path, i)
        fdate = parse_date(row[cols["date"]], where)
        raw_action = (row[cols["action"]] or "").strip().lower()
        action = ACTION_ALIASES.get(raw_action)
        if action is None:
            raise Refuse("%s: unknown action %r (want 申购/赎回/分红)" % (where, row[cols["action"]]))
        amount = parse_amount(row[cols["amount"]], where)
        nav = None
        if "nav" in cols and (row[cols["nav"]] or "").strip():
            nav = parse_nav_value(row[cols["nav"]], where)
        note = ""
        if "note" in cols and cols["note"] < len(row):
            note = (row[cols["note"]] or "").strip()
        flows.append(Flow(fdate, action, amount, nav, note, i))
    flows.sort(key=lambda f: f.date)
    return flows


class NavSeries(object):
    """Sorted (date, nav) points with linear interpolation by day."""

    def __init__(self, points, path):
        self.points = points
        self.path = path
        self.interpolated_used = 0

    @property
    def first_date(self):
        return self.points[0][0]

    @property
    def last_date(self):
        return self.points[-1][0]

    @property
    def span_days(self):
        return (self.last_date - self.first_date).days

    def nav_at(self, day):
        pts = self.points
        if day < pts[0][0] or day > pts[-1][0]:
            raise Refuse("%s: %s is outside the nav range %s → %s"
                         % (self.path, day.isoformat(),
                            pts[0][0].isoformat(), pts[-1][0].isoformat()))
        lo, hi = 0, len(pts) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if pts[mid][0] < day:
                lo = mid + 1
            else:
                hi = mid
        if pts[lo][0] == day:
            return pts[lo][1]
        right = lo
        left = lo - 1
        d0, v0 = pts[left]
        d1, v1 = pts[right]
        frac = (day - d0).days / float((d1 - d0).days)
        self.interpolated_used += 1
        return v0 + (v1 - v0) * frac

    def window_high_low(self, day, lookback_days):
        """(hi, lo) of nav points within [day-lookback, day]; None if <2 points."""
        start = day - timedelta(days=lookback_days)
        values = [v for d, v in self.points if start <= d <= day]
        if len(values) < 2:
            return None
        return max(values), min(values)


def parse_navs(path):
    rows = _read_rows(path)
    if not rows:
        raise Refuse("%s: empty ledger" % path)
    cols = _find_columns(rows[0],
                         {"date": NAV_COLUMNS["date"],
                          "nav": NAV_COLUMNS["nav"]},
                         {},
                         path)
    points = {}
    order = []
    for i, row in enumerate(rows[1:], start=2):
        where = " (%s line %d)" % (path, i)
        day = parse_date(row[cols["date"]], where)
        nav = parse_nav_value(row[cols["nav"]], where)
        if day in points:
            raise Refuse("%s: duplicate nav date %s (lines %d and %d)"
                         % (path, day.isoformat(), points[day], i))
        points[day] = i
        order.append((day, nav))
    order.sort(key=lambda p: p[0])
    return NavSeries(order, path)


# ------------------------------------------------------------------ math

def build_share_ledger(flows, navs, as_of):
    """Replay BUY/SELL through the nav series. Returns reconciliation."""
    shares = 0.0
    buys = sells = divs = 0
    buy_total = sell_total = div_total = 0.0
    min_shares = None
    interp_flows = 0
    navs.interpolated_used = 0
    for f in flows:
        if f.date > as_of:
            raise Refuse("flow on %s is after as-of %s — ledger and as-of disagree"
                         % (f.date.isoformat(), as_of.isoformat()))
        nav = f.nav
        if nav is None:
            nav = navs.nav_at(f.date)
            interp_flows += 1
        if f.action == ACTION_BUY:
            shares += f.amount / nav
            buys += 1
            buy_total += f.amount
        elif f.action == ACTION_SELL:
            shares -= f.amount / nav
            sells += 1
            sell_total += f.amount
            if shares < -1e-6:
                raise Refuse("sell on %s over-draws the ledger "
                             "(shares would be %.4f) — check amounts and navs"
                             % (f.date.isoformat(), shares))
        else:
            divs += 1
            div_total += f.amount
        min_shares = shares if min_shares is None else min(min_shares, shares)
    market_value = shares * navs.nav_at(as_of)
    return {
        "shares": shares,
        "market_value": market_value,
        "buys": buys,
        "sells": sells,
        "divs": divs,
        "buy_total": buy_total,
        "sell_total": sell_total,
        "div_total": div_total,
        "net_invested": buy_total - sell_total,
        "min_shares": min_shares or 0.0,
        "interpolated_flows": interp_flows,
    }


def xirr(legs, as_of):
    """Solve annualized IRR of [(date, amount), ...] by bisection.

    BUY is negative, SELL/DIV/market-value positive. Returns the annual
    rate, or raises Refuse when no root is bracketed in [-99.99%, 1000%].
    """
    legs = [(d, a) for d, a in legs if abs(a) > 0.005]
    if len(legs) < MIN_XIRR_LEGS:
        raise Refuse("only %d cash legs (incl. market value) — not enough to "
                     "solve an IRR" % len(legs))
    d0 = min(d for d, _ in legs)
    has_neg = any(a < 0 for _, a in legs)
    has_pos = any(a > 0 for _, a in legs)
    if not (has_neg and has_pos):
        raise Refuse("cash flows are one-signed — no IRR exists")

    def npv(rate):
        base = 1.0 + rate
        total = 0.0
        for d, a in legs:
            total += a * base ** (-(d - d0).days / 365.0)
        return total

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        raise Refuse("IRR does not bracket a root in [-99.99%%, 1000%%] — "
                     "the cash-flow pattern is pathological")
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9 or (hi - lo) < 1e-12:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2.0


def twr(navs):
    """The fund's own report card: first→last nav, total and annualized."""
    if len(navs.points) < MIN_NAV_POINTS:
        raise Refuse("nav series has %d points — need at least %d"
                     % (len(navs.points), MIN_NAV_POINTS))
    if navs.span_days < MIN_SPAN_DAYS:
        raise Refuse("nav series spans only %d days — need at least %d to "
                     "annualize honestly" % (navs.span_days, MIN_SPAN_DAYS))
    v0, v1 = navs.points[0][1], navs.points[-1][1]
    total = v1 / v0 - 1.0
    years = navs.span_days / 365.0
    annual = (1.0 + total) ** (1.0 / years) - 1.0
    return total, annual


def price_position(navs, day, nav_value):
    """Where this price sits in the trailing-365d high-low range: 0=low.

    None when the window holds fewer than 2 nav points (no history yet).
    Clamped to [0, 1] — buying above the trailing high IS a chase (1.0).
    """
    hl = navs.window_high_low(day, POSITION_WINDOW_DAYS)
    if hl is None:
        return None
    hi, lo = hl
    if hi <= lo:
        return 0.5
    pos = (nav_value - lo) / (hi - lo)
    return max(0.0, min(1.0, pos))


def sell_drawdown(navs, day, nav_value):
    """Drawdown vs the trailing-180d high: (high, drawdown) or None."""
    hl = navs.window_high_low(day, DRAWDOWN_WINDOW_DAYS)
    if hl is None:
        return None
    hi, _ = hl
    if hi <= 0:
        return None
    return hi, 1.0 - nav_value / hi


def audit_flows(flows, navs, as_of):
    """Per-flow position/panic table plus the buy-side aggregate."""
    rows = []
    buy_positions = []
    for f in flows:
        row = {"flow": f, "nav": None, "pos": None, "label": "", "panic": None}
        if f.date > as_of:
            continue
        nav = f.nav if f.nav is not None else navs.nav_at(f.date)
        row["nav"] = nav
        if f.action == ACTION_DIV:
            row["label"] = "CASH IN POCKET"
        elif f.action == ACTION_BUY:
            pos = price_position(navs, f.date, nav)
            row["pos"] = pos
            if pos is None:
                row["label"] = "FIRST BUYS (no 365d history)"
            elif pos >= CHASE_LINE:
                row["label"] = "CHASE-HI"
            elif pos <= BOTTOM_LINE:
                row["label"] = "BOTTOM-LO"
            else:
                row["label"] = "MID-RANGE"
            if pos is not None:
                buy_positions.append((f.amount, pos))
        else:
            dd = sell_drawdown(navs, f.date, nav)
            if dd is not None and dd[1] > PANIC_DRAWDOWN:
                row["label"] = "PANIC"
                row["panic"] = {
                    "high": dd[0],
                    "drawdown": dd[1],
                    "shares": f.amount / nav,
                    "rebound_days": None,
                    "rebound_pct": None,
                    "missed": None,
                }
                rebound_day = f.date + timedelta(days=REBOUND_WINDOW_DAYS)
                cap = min(rebound_day, as_of)
                nav_later = navs.nav_at(cap)
                row["panic"]["rebound_pct"] = nav_later / nav - 1.0
                row["panic"]["missed"] = (f.amount / nav) * (nav_later - nav)
                row["panic"]["rebound_days"] = (cap - f.date).days
                if rebound_day > as_of:
                    row["label"] = "PANIC (rebound window open)"
            else:
                row["label"] = "DISCIPLINE"
        rows.append(row)
    weighted = None
    if buy_positions:
        weighted = (sum(a * p for a, p in buy_positions)
                    / sum(a for a, _ in buy_positions))
    return rows, weighted


def counterfactuals(flows, navs, as_of):
    """Same money, three pairs of hands: actual / hold / dca."""
    ledger = build_share_ledger(flows, navs, as_of)
    actual = ledger["market_value"]
    net = ledger["net_invested"]
    first_nav = navs.points[0][1]
    last_nav = navs.points[-1][1]

    hold_value = 0.0
    if net > 0:
        hold_value = net / first_nav * last_nav

    dca_value = 0.0
    dca_months = 0
    dca_amount = 0.0
    buys = [f for f in flows if f.action == ACTION_BUY and f.date <= as_of]
    if buys and net > 0:
        start_month = (buys[0].date.year, buys[0].date.month)
        end_month = (as_of.year, as_of.month)
        months = (end_month[0] - start_month[0]) * 12 + (end_month[1] - start_month[1]) + 1
        if months > 0:
            dca_amount = net / months
            day = date(start_month[0], start_month[1], 1)
            for _ in range(months):
                probe = max(day, navs.first_date)
                if probe <= as_of:
                    dca_value += dca_amount / navs.nav_at(probe)
                    dca_months += 1
                if day.month == 12:
                    day = date(day.year + 1, 1, 1)
                else:
                    day = date(day.year, day.month + 1, 1)
            dca_value *= last_nav
    return {
        "actual": actual,
        "hold": hold_value,
        "dca": dca_value,
        "dca_amount": dca_amount,
        "dca_months": dca_months,
        "net_invested": net,
        "ledger": ledger,
    }


# --------------------------------------------------------------- verdict

def verdict_of(gap, gap_line):
    if gap >= GAP_BEAT:
        return "BEAT"
    if gap <= gap_line:
        return "BLEEDING"
    return "DRAG"


# -------------------------------------------------------------- formatting

def fmt_money(v, signed=False):
    text = "{:,.2f}".format(abs(v))
    if v < 0:
        return "-" + text
    return ("+" + text) if signed else text


def fmt_pct(v, signed=True):
    return "{:+,.2f}%".format(v * 100) if signed else "{:,.2f}%".format(v * 100)


def fmt_pp(v):
    return "%+.2f pp" % v


# --------------------------------------------------------------- renders

def render_report(flows, navs, as_of, ledger, twr_total, twr_annual,
                  xirr_rate, gap, gap_line, rows, weighted, fmt):
    verdict = verdict_of(gap, gap_line)
    if fmt == "json":
        import json
        panic_rows = [
            {
                "date": r["flow"].date.isoformat(),
                "amount": r["flow"].amount,
                "nav": round(r["nav"], 6),
                "drawdown": round(r["panic"]["drawdown"], 6),
                "high": round(r["panic"]["high"], 6),
                "shares": round(r["panic"]["shares"], 4),
                "rebound_days": r["panic"]["rebound_days"],
                "rebound_pct": (round(r["panic"]["rebound_pct"], 6)
                                if r["panic"]["rebound_pct"] is not None else None),
                "missed": (round(r["panic"]["missed"], 2)
                           if r["panic"]["missed"] is not None else None),
            }
            for r in rows if r["panic"]
        ]
        return json.dumps({
            "as_of": as_of.isoformat(),
            "nav_points": len(navs.points),
            "span_days": navs.span_days,
            "flows": len(flows),
            "interpolated_flows": ledger["interpolated_flows"],
            "shares": round(ledger["shares"], 4),
            "market_value": round(ledger["market_value"], 2),
            "net_invested": round(ledger["net_invested"], 2),
            "div_total": round(ledger["div_total"], 2),
            "twr_total": round(twr_total, 6),
            "twr_annual": round(twr_annual, 6),
            "xirr": round(xirr_rate, 6),
            "gap_pp": round(gap * 100, 4),
            "gap_line_pp": gap_line * 100,
            "verdict": verdict,
            "buy_position_weighted": (round(weighted, 4) if weighted is not None else None),
            "panic_sells": panic_rows,
        }, ensure_ascii=False, indent=2, sort_keys=True)

    lines = []
    lines.append("NAV ILLUSION · behavior audit — as-of %s" % as_of.isoformat())
    lines.append("")
    lines.append("ledger")
    lines.append("  navs         : %d points · %s → %s (%d days)"
                 % (len(navs.points), navs.first_date.isoformat(),
                    navs.last_date.isoformat(), navs.span_days))
    lines.append("  flows        : %d (buy %d · sell %d · div %d) · %d nav(s) interpolated"
                 % (len(flows), ledger["buys"], ledger["sells"], ledger["divs"],
                    ledger["interpolated_flows"]))
    lines.append("  shares now   : %s" % "{:,.4f}".format(ledger["shares"]))
    lines.append("  net invested : %s   (buys %s − sells %s)"
                 % (fmt_money(ledger["net_invested"]),
                    fmt_money(ledger["buy_total"]), fmt_money(ledger["sell_total"])))
    profit = ledger["market_value"] - ledger["net_invested"]
    lines.append("  market value : %s   profit %s on net"
                 % (fmt_money(ledger["market_value"]), fmt_money(profit, signed=True)))
    if ledger["divs"]:
        lines.append("  dividends    : %s in pocket (outside the share ledger)"
                     % fmt_money(ledger["div_total"]))
    lines.append("")
    lines.append("two clocks of return")
    lines.append("  fund TWR     : %s/yr   the fund's report card (nav %s → %s, %s total)"
                 % (fmt_pct(twr_annual),
                    "{:,.4f}".format(navs.points[0][1]),
                    "{:,.4f}".format(navs.points[-1][1]),
                    fmt_pct(twr_total)))
    lines.append("  your XIRR    : %s/yr   what your money actually earned"
                 % fmt_pct(xirr_rate))
    lines.append("  behavior gap : %s/yr   XIRR − TWR" % fmt_pp(gap * 100))
    lines.append("")
    lines.append("behavior profile")
    if weighted is None:
        lines.append("  buy price position (365d, amount-weighted): — (no history yet)")
    else:
        label = ("CHASING" if weighted >= CHASE_LINE
                 else "BOTTOM-FISHING" if weighted <= BOTTOM_LINE else "MID-RANGE")
        lines.append("  buy price position (365d, amount-weighted): %.2f → %s"
                     % (weighted, label))
    panic_rows = [r for r in rows if r["panic"]]
    if panic_rows:
        worst = max(panic_rows, key=lambda r: r["panic"]["drawdown"])
        line = ("  panic sells  : %d of %d — worst sold in a %s drawdown "
                "(180d high %.4f)"
                % (len(panic_rows), ledger["sells"],
                   fmt_pct(-worst["panic"]["drawdown"]), worst["panic"]["high"]))
        lines.append(line)
        for r in panic_rows:
            p = r["panic"]
            tail = ("next %d days paid %s back: %s went to whoever held"
                    % (p["rebound_days"], fmt_pct(p["rebound_pct"]),
                       fmt_money(p["missed"])))
            lines.append("                 %s — %s"
                         % (r["flow"].date.isoformat(), tail))
    elif ledger["sells"]:
        lines.append("  panic sells  : 0 of %d — every exit was calm, or too "
                     "recent to judge" % ledger["sells"])
    lines.append("")
    if verdict == "BEAT":
        lines.append("verdict: BEAT — gap %s. You out-timed your own fund; "
                     "one ledger proves it." % fmt_pp(gap * 100))
        exit_code = 0
    elif verdict == "DRAG":
        lines.append("verdict: DRAG — gap %s is inside the %s line, but the "
                     "direction is the fund's friend, not yours."
                     % (fmt_pp(gap * 100), fmt_pp(gap_line * 100)))
        exit_code = 0
    else:
        lines.append("verdict: BLEEDING — gap %s <= %s line. The fund earned; "
                     "your hands paid the difference."
                     % (fmt_pp(gap * 100), fmt_pp(gap_line * 100)))
        exit_code = 4
    return "\n".join(lines), exit_code


def render_flows(flows, navs, as_of, rows, weighted, ledger, fmt):
    if fmt == "json":
        import json
        return json.dumps({
            "as_of": as_of.isoformat(),
            "buy_position_weighted": (round(weighted, 4)
                                      if weighted is not None else None),
            "flows": [
                {
                    "date": r["flow"].date.isoformat(),
                    "action": r["flow"].action,
                    "amount": r["flow"].amount,
                    "nav": (round(r["nav"], 6) if r["nav"] is not None else None),
                    "position": (round(r["pos"], 4) if r["pos"] is not None else None),
                    "label": r["label"],
                }
                for r in rows
            ],
        }, ensure_ascii=False, indent=2, sort_keys=True), 0

    lines = []
    lines.append("flow-by-flow audit — as-of %s" % as_of.isoformat())
    lines.append("")
    lines.append("date        action  amount        nav@date  pos-365  label")
    for r in rows:
        f = r["flow"]
        pos_text = "     —" if r["pos"] is None else "%7.2f" % r["pos"]
        lines.append("%s  %-5s  %12s  %9s  %s  %s"
                     % (f.date.isoformat(), f.action,
                        "{:,.2f}".format(f.amount),
                        ("{:,.4f}".format(r["nav"]) if r["nav"] is not None else "—"),
                        pos_text, r["label"]))
        if r["panic"] and r["panic"]["missed"] is not None:
            lines.append("                                          └ %s rebound in %d days → %s "
                         "went to whoever held"
                         % (fmt_pct(r["panic"]["rebound_pct"]),
                            r["panic"]["rebound_days"],
                            fmt_money(r["panic"]["missed"])))
    lines.append("")
    if weighted is None:
        lines.append("buy-side amount-weighted position: — (no history yet)")
    else:
        label = ("CHASING" if weighted >= CHASE_LINE
                 else "BOTTOM-FISHING" if weighted <= BOTTOM_LINE else "MID-RANGE")
        lines.append("buy-side amount-weighted position: %.2f → %s" % (weighted, label))
    return "\n".join(lines), 0


def render_simulate(flows, navs, as_of, cf, fmt):
    if fmt == "json":
        import json
        return json.dumps({
            "as_of": as_of.isoformat(),
            "net_invested": round(cf["net_invested"], 2),
            "actual": round(cf["actual"], 2),
            "hold": round(cf["hold"], 2),
            "dca": round(cf["dca"], 2),
            "dca_amount": round(cf["dca_amount"], 2),
            "dca_months": cf["dca_months"],
            "hold_minus_actual": round(cf["hold"] - cf["actual"], 2),
            "dca_minus_actual": round(cf["dca"] - cf["actual"], 2),
        }, ensure_ascii=False, indent=2, sort_keys=True), 0

    lines = []
    lines.append("counterfactuals — same money, three pairs of hands "
                 "(as-of %s)" % as_of.isoformat())
    lines.append("")
    lines.append("  actual  your hands, as lived        %14s"
                 % fmt_money(cf["actual"]))
    lines.append("  hold    one shot on day one         %14s   %s vs actual"
                 % (fmt_money(cf["hold"]),
                    fmt_money(cf["hold"] - cf["actual"], signed=True)))
    if cf["dca_months"]:
        lines.append("  dca     blind monthly %8s ×%-3d %14s   %s vs actual"
                     % ("{:,.2f}".format(cf["dca_amount"]), cf["dca_months"],
                        fmt_money(cf["dca"]),
                        fmt_money(cf["dca"] - cf["actual"], signed=True)))
    lines.append("")
    best = max(cf["hold"], cf["dca"]) if cf["dca_months"] else cf["hold"]
    if best > cf["actual"]:
        lines.append("holding still beat your hands by %s; your timing was "
                     "the most expensive part of this fund."
                     % fmt_money(best - cf["actual"]))
    else:
        lines.append("your hands beat both counterfactuals — documented, "
                     "this time.")
    return "\n".join(lines), 0


def render_doctor(flows, navs, as_of, ledger, problems, fmt):
    fatal = [p for p in problems if p[0] == "FATAL"]
    warns = [p for p in problems if p[0] == "WARN"]
    if fmt == "json":
        import json
        return json.dumps({
            "nav_points": len(navs.points),
            "span_days": navs.span_days,
            "flows": len(flows),
            "min_shares": (round(ledger["min_shares"], 4)
                           if ledger is not None else None),
            "fatal": [m for _, m in fatal],
            "warnings": [m for _, m in warns],
            "healthy": not fatal,
        }, ensure_ascii=False, indent=2, sort_keys=True), 0

    lines = []
    lines.append("doctor — data physical exam")
    lines.append("")
    lines.append("  navs   : %d rows · span %d days (need >= %d)"
                 % (len(navs.points), navs.span_days, MIN_SPAN_DAYS))
    lines.append("  flows  : %d rows (buy %d · sell %d · div %d)"
                 % (len(flows), ledger["buys"], ledger["sells"], ledger["divs"])
                 if ledger is not None else
                 "  flows  : %d rows (replay not reachable — fix fatal rows)"
                 % len(flows))
    if ledger is not None:
        lines.append("  replay : min shares %s (negative = over-sell)"
                     % "{:,.4f}".format(ledger["min_shares"]))
    for _, msg in warns:
        lines.append("  warn   : %s" % msg)
    for _, msg in fatal:
        lines.append("  FATAL  : %s" % msg)
    lines.append("")
    if fatal:
        lines.append("verdict: UNHEALTHY — fix the FATAL rows before trusting "
                     "any audit.")
        return "\n".join(lines), 3
    if warns:
        lines.append("verdict: USABLE WITH NOTES — the audit will disclose "
                     "each note.")
        return "\n".join(lines), 0
    lines.append("verdict: HEALTHY — these two ledgers deserve the audit.")
    return "\n".join(lines), 0


def doctor_problems(flows, navs, as_of):
    """Structural checks that need no share replay. Ledger faults (over-sell,
    pricing failures) are appended by cmd_doctor from the replay itself."""
    problems = []
    nav_dates = [d for d, _ in navs.points]
    if len(navs.points) < MIN_NAV_POINTS:
        problems.append(("FATAL", "nav series needs >= %d points, has %d"
                         % (MIN_NAV_POINTS, len(navs.points))))
    if navs.span_days < MIN_SPAN_DAYS:
        problems.append(("FATAL", "nav span %d days < %d — annualizing this "
                         "would be fiction" % (navs.span_days, MIN_SPAN_DAYS)))
    if len(set(nav_dates)) != len(nav_dates):
        problems.append(("FATAL", "duplicate nav dates"))
    if nav_dates != sorted(nav_dates):
        problems.append(("FATAL", "nav dates not ascending"))
    out_of_range = [f for f in flows
                    if f.date < navs.first_date or f.date > navs.last_date]
    if out_of_range:
        problems.append(("FATAL", "%d flow(s) outside the nav range "
                         "(first: %s)"
                         % (len(out_of_range),
                            out_of_range[0].date.isoformat())))
    after_asof = [f for f in flows if f.date > as_of]
    if after_asof:
        problems.append(("FATAL", "%d flow(s) after as-of %s"
                         % (len(after_asof), as_of.isoformat())))
    return problems


# ------------------------------------------------------------------ main

def resolve_as_of(navs, as_of_text):
    if as_of_text is None:
        return navs.last_date
    day = parse_date(as_of_text, " (--as-of)")
    if day < navs.first_date or day > navs.last_date:
        raise Refuse("--as-of %s is outside the nav range %s → %s"
                     % (day.isoformat(), navs.first_date.isoformat(),
                        navs.last_date.isoformat()))
    return day


def build_context(args):
    navs = parse_navs(args.navs)
    flows = parse_flows(args.flows)
    as_of = resolve_as_of(navs, args.as_of)
    return flows, navs, as_of


def cmd_report(args):
    flows, navs, as_of = build_context(args)
    ledger = build_share_ledger(flows, navs, as_of)
    twr_total, twr_annual = twr(navs)
    legs = [(f.date, -f.amount if f.action == ACTION_BUY else f.amount)
            for f in flows if f.date <= as_of]
    legs.append((as_of, ledger["market_value"]))
    rate = xirr(legs, as_of)
    gap = rate - twr_annual
    rows, weighted = audit_flows(flows, navs, as_of)
    out = render_report(flows, navs, as_of, ledger, twr_total, twr_annual,
                        rate, gap, args.gap_line / 100.0, rows, weighted,
                        args.format)
    if args.format == "json":
        print(out)
        return 0
    text, code = out
    print(text)
    return code


def cmd_flows(args):
    flows, navs, as_of = build_context(args)
    ledger = build_share_ledger(flows, navs, as_of)
    rows, weighted = audit_flows(flows, navs, as_of)
    out = render_flows(flows, navs, as_of, rows, weighted, ledger, args.format)
    text, code = out
    print(text)
    return code


def cmd_simulate(args):
    flows, navs, as_of = build_context(args)
    cf = counterfactuals(flows, navs, as_of)
    out = render_simulate(flows, navs, as_of, cf, args.format)
    text, code = out
    print(text)
    return code


def cmd_doctor(args):
    flows, navs, as_of = build_context(args)
    problems = doctor_problems(flows, navs, as_of)
    try:
        ledger = build_share_ledger(flows, navs, as_of)
    except Refuse as exc:
        problems.append(("FATAL", str(exc)))
        ledger = None
    else:
        if ledger["min_shares"] < -1e-6:
            problems.append(("FATAL", "share ledger goes negative"))
        if ledger["interpolated_flows"]:
            problems.append(("WARN", "%d flow(s) priced by interpolated navs — "
                             "disclosed in every report"
                             % ledger["interpolated_flows"]))
    out = render_doctor(flows, navs, as_of, ledger, problems, args.format)
    text, code = out
    print(text)
    return code


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="净值幻觉 · NAV Illusion — audit the gap between the "
                    "fund's TWR and your XIRR.")
    sub = parser.add_subparsers(dest="command")

    def add_common(p):
        p.add_argument("flows", help="flows CSV (日期,动作,金额[,净值][,备注])")
        p.add_argument("navs", help="nav series CSV (日期,净值) — 复权净值")
        p.add_argument("--as-of", dest="as_of", default=None,
                       help="audit date YYYY-MM-DD (default: last nav date)")
        p.add_argument("--format", choices=("text", "json"), default="text")

    p = sub.add_parser("report", help="XIRR vs TWR + behavior gap verdict")
    add_common(p)
    p.add_argument("--gap-line", dest="gap_line", type=float,
                   default=DEFAULT_GAP_LINE,
                   help="BLEEDING threshold in pp (default %.1f)" % DEFAULT_GAP_LINE)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("flows", help="flow-by-flow audit: positions + panic sells")
    add_common(p)
    p.set_defaults(func=cmd_flows)

    p = sub.add_parser("simulate", help="actual vs one-shot hold vs blind dca")
    add_common(p)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("doctor", help="data physical exam")
    add_common(p)
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except Refuse as exc:
        print("refuse: %s" % exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
