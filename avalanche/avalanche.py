#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""雪崩 · Avalanche — spaced-repetition backlog ledger (zero-dependency CLI).

复习积压是每天自动加息的债：今天没碰的卡，明天连本带息回到队列。
App 只肯给你看「今日到期」一个数；这本账把债的存量、利差、崩盘日、
惯犯卡算出来——崩盘不是遗忘曲线的错，是排程的错。

Ledger (reviews.tsv, hand-copied daily from any spaced-repetition app):
    date<TAB>due<TAB>done<TAB>again<TAB>new
      due    cards the app shows due today (overdue re-queued; new excluded)
      done   reviews completed today (new-card learning excluded)
      again  of `done`, cards answered wrong (forgotten)
      new    new cards learned today

Leeches census (leeches.tsv, optional, complete lapse history):
    card<TAB>lapses

No wall clock anywhere: default as-of = max ledger date; --as-of pins a
historical replay. Same ledger, any machine, any day -> byte-identical.

Exit codes: 0 ok | 2 broken ledger | 3 thin ledger (statistics declined)
            4 gate red (OVERFLOW / AVALANCHE / LEVERAGED / MATH-DEAD / KILL-LIST)
"""

import argparse
import math
import os
import sys
from datetime import date, timedelta

EXIT_OK, EXIT_BROKEN, EXIT_THIN, EXIT_GATE = 0, 2, 3, 4
THIN_ROWS = 7
BLOCKS = "▁▂▃▄▅▆▇█"
COLS = ["date", "due", "done", "again", "new"]


class LedgerError(Exception):
    pass


# ---------------------------------------------------------------- parsing

def display_width(s):
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def pad(s, width):
    return s + " " * max(0, width - display_width(s))


def _to_int(s, what, rowno):
    try:
        v = int(s)
    except ValueError:
        raise LedgerError("row %d: %s is not an integer: %r" % (rowno, what, s))
    if v < 0:
        raise LedgerError("row %d: %s is negative: %d" % (rowno, what, v))
    return v


def _to_date(s, what, rowno):
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise LedgerError("row %d: %s is not a valid date: %r" % (rowno, what, s))


def read_tsv(path, cols, what):
    """Parse a TSV; first non-comment, non-blank line is the header."""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise LedgerError("cannot read %s file: %s" % (what, exc))
    header = None
    out = []
    for raw in lines:
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        if header is None:
            if line.lstrip().startswith("#"):
                continue
            header = [c.strip().lower() for c in line.split("\t")]
            missing = [c for c in cols if c not in header]
            if missing:
                raise LedgerError(
                    "%s: header missing column(s): %s (got: %s)"
                    % (what, ", ".join(missing), "\t".join(header)))
            continue
        if line.lstrip().startswith("#"):
            continue
        out.append(dict(zip(header, [c.strip() for c in line.split("\t")])))
    if header is None:
        raise LedgerError("%s: no header row found (expected: %s)"
                          % (what, "\t".join(cols)))
    return out


def load_reviews(path, as_of=None):
    raw = read_tsv(path, COLS, "ledger")
    rows = []
    prev = None
    for i, r in enumerate(raw, 1):
        d = _to_date(r["date"], "date", i)
        if prev is not None and d <= prev:
            raise LedgerError("row %d: date %s not strictly after previous %s"
                              % (i, d.isoformat(), prev.isoformat()))
        prev = d
        vals = {k: _to_int(r[k], k, i) for k in ("due", "done", "again", "new")}
        if vals["again"] > vals["done"]:
            raise LedgerError("row %d (%s): again %d > done %d"
                              % (i, d.isoformat(), vals["again"], vals["done"]))
        if as_of is not None and d > as_of:
            continue  # --as-of is truncation-replay: later rows are excluded,
                      # not errors (a flow ledger's future simply has not happened yet)
        row = {"date": d}
        row.update(vals)
        rows.append(row)
    return rows


def load_leeches(path):
    raw = read_tsv(path, ["card", "lapses"], "leeches")
    seen = {}
    for i, r in enumerate(raw, 1):
        card = r["card"]
        if not card:
            raise LedgerError("row %d: empty card id" % i)
        lapses = _to_int(r["lapses"], "lapses", i)
        if lapses < 1:
            raise LedgerError("row %d: lapses must be >= 1 (a card with no "
                              "lapse does not belong in the census)" % i)
        if card in seen:
            raise LedgerError("row %d: duplicate card %r" % (i, card))
        seen[card] = lapses
    return seen


# ---------------------------------------------------------------- metrics

def lower_median(vals):
    s = sorted(vals)
    return s[(len(s) - 1) // 2]


def carried_seq(rows):
    return [max(0, r["due"] - r["done"]) for r in rows]


def compute(rows, opt):
    n = len(rows)
    carr = carried_seq(rows)
    debt = sum(carr)
    backlog = carr[-1]
    paid_ahead = sum(1 for r in rows if r["done"] > r["due"])
    forgiven = []
    for i in range(1, n):
        if rows[i]["due"] < carr[i - 1]:
            forgiven.append(rows[i]["date"].isoformat())
    w = min(opt.window, n)
    start = n - w
    D = lower_median([rows[i]["due"] for i in range(start, n)])
    C = lower_median([rows[i]["done"] for i in range(start, n)])
    fresh = []
    f_forgiven = 0
    for i in range(start, n):
        f = rows[i]["due"] - (carr[i - 1] if i > 0 else 0)
        if f >= 0:
            fresh.append(f)
        else:
            f_forgiven += 1
    F = lower_median(fresh) if fresh else 0
    again_sum = sum(rows[i]["again"] for i in range(start, n))
    done_sum = sum(rows[i]["done"] for i in range(start, n))
    forget = (again_sum / done_sum) if done_sum else None
    spread = D - C
    line = opt.doom_line if opt.doom_line is not None else 3 * C
    return {
        "n": n, "window": w, "backlog": backlog, "debt": debt,
        "paid_ahead": paid_ahead, "forgiven": forgiven, "f_forgiven": f_forgiven,
        "D": D, "C": C, "F": F, "spread": spread,
        "structural": F - C, "forget": forget, "line": line,
        "again_sum": again_sum, "done_sum": done_sum,
        "dates0": rows[0]["date"], "dates1": rows[-1]["date"],
    }


def project_days(backlog, spread, line):
    """Days until backlog crosses `line` at a constant `spread`; None if never."""
    if spread <= 0 or backlog >= line:
        return None
    return (line - backlog + spread - 1) // spread


def verdict_of(m, opt, asof):
    if m["backlog"] >= m["line"]:
        if m["spread"] < 0:
            trend = "shrinking %+d/day" % m["spread"]
        elif m["spread"] == 0:
            trend = "flat"
        else:
            trend = "still growing +%d/day" % m["spread"]
        return ("OVERFLOW", EXIT_GATE,
                "backlog %d >= doom line %d -- already crossed (%s)"
                % (m["backlog"], m["line"], trend))
    k = project_days(m["backlog"], m["spread"], m["line"])
    if k is not None:
        doom = asof + timedelta(days=k)
        if k <= opt.doom_window:
            return ("AVALANCHE", EXIT_GATE,
                    "backlog %d + %d/day crosses the doom line %d in %d day(s) "
                    "-> %s (inside the %d-day window)"
                    % (m["backlog"], m["spread"], m["line"], k,
                       doom.isoformat(), opt.doom_window))
        return ("ACCRUING", EXIT_OK,
                "backlog %d + %d/day crosses the doom line only on %s "
                "(+%d days, beyond the %d-day window)"
                % (m["backlog"], m["spread"], doom.isoformat(), k,
                   opt.doom_window))
    if m["spread"] == 0:
        return ("TREADING", EXIT_OK,
                "spread 0 -- capacity matches pressure; backlog %d, debt flat"
                % m["backlog"])
    return ("HARVEST", EXIT_OK,
            "spread %+d/day -- capacity outruns pressure; backlog %d shrinking"
            % (m["spread"], m["backlog"]))


def _level(v, mx):
    if v <= 0:
        return 0
    if mx <= 1:
        return 7
    return min(7, 1 + (v - 1) * 7 // (mx - 1))


def sparkline(carr, width=120):
    vals = list(carr)
    if len(vals) > width:
        stride = int(math.ceil(len(vals) / float(width)))
        vals = vals[::stride]
        vals[-1] = carr[-1]
    mx = max(vals) if vals else 0
    return "".join(BLOCKS[_level(v, mx)] for v in vals)


def lineout(label, value, note=""):
    txt = "  " + pad(label, 20) + value
    if note:
        txt += "   " + note
    print(txt)


def _parse_asof(s):
    if s is None:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise LedgerError("--as-of is not a valid date: %r" % s)


def _header(name, rows, as_of):
    asof = (as_of if as_of is not None else rows[-1]["date"]).isoformat()
    print("ledger: %s   rows: %d   span: %s .. %s   as-of: %s"
          % (name, len(rows), rows[0]["date"].isoformat(),
             rows[-1]["date"].isoformat(), asof))
    idle = (rows[-1]["date"] - rows[0]["date"]).days + 1 - len(rows)
    if idle:
        print("idle days (no rows): %d -- card-days accrue on recorded days "
              "only; the true debt is larger" % idle)
    return asof


# ---------------------------------------------------------------- commands

def cmd_report(opt):
    as_of = _parse_asof(opt.as_of)
    rows = load_reviews(opt.ledger, as_of)
    name = os.path.basename(opt.ledger)
    print("=== Avalanche · spaced-repetition backlog ledger ===")
    if not rows:
        print("ledger: %s   rows: 0" % name)
        print("declining: no rows on or before as-of %s"
              % (as_of.isoformat() if as_of else "-"))
        return EXIT_THIN
    m = compute(rows, opt)
    asof = _header(name, rows, as_of)

    print()
    print("-- stock (as of %s) --" % m["dates1"].isoformat())
    lineout("backlog now:", "%d cards" % m["backlog"],
            "(last day: due %d - done %d)"
            % (rows[-1]["due"], rows[-1]["done"]))
    lineout("debt so far:", "%d card-days" % m["debt"],
            "(sum of daily backlog)")
    lineout("paid-ahead rows:", str(m["paid_ahead"]),
            "(done > due: future maturities paid early)")
    lineout("forgiven rows:", str(len(m["forgiven"])),
            "(due < carried: cards left the deck off-book)")
    print("  backlog curve (older -> newer):")
    print("  " + sparkline(carried_seq(rows)))

    if m["n"] < THIN_ROWS:
        print()
        print("declining: %d review-days < %d -- flow statistics and the "
              "verdict need at least %d recorded days"
              % (m["n"], THIN_ROWS, THIN_ROWS))
        return EXIT_THIN

    print()
    print("-- flow (trailing %d review-days) --" % m["window"])
    lineout("due pressure D:", "%d/day" % m["D"])
    lineout("capacity C:", "%d/day" % m["C"])
    lineout("surface spread:", "%+d/day" % m["spread"], "(D - C: today's bleed)")
    lineout("fresh inflow F:", "%d/day" % m["F"],
            "(matured cards returning; carried backlog excluded%s)"
            % (", %d forgiven row(s) excluded" % m["f_forgiven"]
               if m["f_forgiven"] else ""))
    lineout("structural spread:", "%+d/day" % m["structural"],
            "(F - C: the deck cannot self-heal while this is positive)")
    if m["forget"] is None:
        lineout("forgetting rate:", "n/a", "(no reviews in the window)")
    else:
        lineout("forgetting rate:", "%.1f%%" % (100.0 * m["forget"]),
                "(again / done, trailing window)")

    print()
    print("-- doom --")
    if opt.doom_line is not None:
        lineout("doom line:", "%d cards" % m["line"], "(--doom-line override)")
    else:
        lineout("doom line:", "%d cards" % m["line"],
                "(3 x C; override with --doom-line)")
    vname, vexit, vmsg = verdict_of(m, opt, rows[-1]["date"])
    print("projection: %s" % vmsg)
    print("verdict: %s [exit %d]" % (vname, vexit))
    return vexit


def cmd_add(opt):
    as_of = _parse_asof(opt.as_of)
    rows = load_reviews(opt.ledger, as_of)
    name = os.path.basename(opt.ledger)
    print("=== Avalanche · new-card quota gate ===")
    if not rows or len(rows) < THIN_ROWS:
        print("ledger: %s   rows: %d" % (name, len(rows)))
        print("declining: %d review-days < %d -- the quota needs flow "
              "statistics" % (len(rows), THIN_ROWS))
        return EXIT_THIN
    m = compute(rows, opt)
    asof = _header(name, rows, as_of)
    quota = max(0, m["C"] - m["D"])
    pipeline = sum(r["new"] for r in rows[len(rows) - m["window"]:])

    print()
    lineout("due pressure D:", "%d/day" % m["D"])
    lineout("capacity C:", "%d/day" % m["C"])
    lineout("surface spread:", "%+d/day" % m["spread"])
    lineout("quota:", "%d new cards" % quota, "(max(0, C - D): today's spare capacity)")
    print("  requested: %d" % opt.n)
    lineout("recent pipeline:", "%d new cards" % pipeline,
            "(added in the trailing window; still maturing into future due)")

    print()
    if opt.n <= quota:
        print("verdict: PASS [exit %d] -- %d <= quota %d: today's flow can "
              "carry them" % (EXIT_OK, opt.n, quota))
        return EXIT_OK
    print("verdict: LEVERAGED [exit %d] -- %d > quota %d: every new card "
          "starts a lifetime due stream; adding them today borrows capacity "
          "you do not have" % (EXIT_GATE, opt.n, quota))
    print("  freeze new cards or clear the backlog first; the quota is "
          "today's spare capacity, not a lifetime allowance")
    return EXIT_GATE


def cmd_simulate(opt):
    as_of = _parse_asof(opt.as_of)
    rows = load_reviews(opt.ledger, as_of)
    name = os.path.basename(opt.ledger)
    print("=== Avalanche · catch-up simulation ===")
    if not rows or len(rows) < THIN_ROWS:
        print("ledger: %s   rows: %d" % (name, len(rows)))
        print("declining: %d review-days < %d -- scenarios need flow "
              "statistics" % (len(rows), THIN_ROWS))
        return EXIT_THIN
    m = compute(rows, opt)
    asof = _header(name, rows, as_of)
    B, C, F, s, line = m["backlog"], m["C"], m["F"], m["spread"], m["line"]

    print()
    print("state: backlog %d, capacity %d/day, fresh inflow %d/day, "
          "surface spread %+d/day, doom line %d"
          % (B, C, F, s, line))
    print("assumptions: rates held constant; days are calendar days (daily "
          "practice assumed); F held constant -- cards cleared today start")
    print("returning after their intervals, so freeze/accelerate clear "
          "dates are the EARLIEST possible (override inflow: --freeze-inflow)")

    gate = False
    print()
    print("as-is          : keep doing what you do")
    k = project_days(B, s, line)
    if B >= line:
        print("                 backlog %d >= doom line %d now (OVERFLOW)"
              % (B, line))
        gate = True
    elif k is not None:
        doom = rows[-1]["date"] + timedelta(days=k)
        inside = k <= opt.doom_window
        gate = gate or inside
        print("                 spread %+d/day -> backlog %d + %d x t crosses "
              "%d in %d day(s) -> %s%s"
              % (s, B, s, line, k, doom.isoformat(),
                 "" if inside else " (beyond the %d-day window)"
                 % opt.doom_window))
    else:
        print("                 spread %+d/day -> no crossing; backlog %d %s"
              % (s, B, "shrinking" if s < 0 else "flat"))

    print()
    fin = opt.freeze_inflow if opt.freeze_inflow is not None else F
    net = C - fin
    print("freeze         : new = 0 from today, capacity %d/day, inflow %d/day"
          % (C, fin))
    if B == 0:
        print("                 backlog 0 -- nothing to clear")
    elif net > 0:
        days = int(math.ceil(B / float(net)))
        clear = rows[-1]["date"] + timedelta(days=days)
        full, last = divmod(B, net)
        print("                 net %+d/day -> clears the %d-card backlog in "
              "%d review-day(s), earliest clear date %s"
              % (net, B, days, clear.isoformat()))
        print("                 repayment check: %d x %d + %d = %d == backlog "
              "(last day partial)" % (full, net, last, B))
    else:
        print("                 net %+d/day -> NEVER clears" % net)
        print("                 verdict: MATH-DEAD [exit %d] -- even with zero "
              "new cards the matured deck returns at least as fast as you "
              "clear; cutting the deck or adding time are the only exits"
              % EXIT_GATE)
        gate = True

    print()
    c2 = C * opt.accelerate
    neta = c2 - fin
    print("accelerate x%g  : capacity %.1f/day, inflow %d/day"
          % (opt.accelerate, c2, fin))
    if B == 0:
        print("                 backlog 0 -- nothing to clear")
    elif neta > 0:
        days = int(math.ceil(B / float(neta)))
        clear = rows[-1]["date"] + timedelta(days=days)
        full, last = divmod(B, int(math.floor(neta))) if neta >= 1 else (0, B)
        print("                 net %+.1f/day -> clears the %d-card backlog in "
              "%d review-day(s), earliest clear date %s"
              % (neta, B, days, clear.isoformat()))
        if neta >= 1:
            print("                 repayment check: %d x %d + %d = %d == "
                  "backlog (last day partial)" % (full, int(math.floor(neta)),
                                                  last, B))
    else:
        print("                 net %+.1f/day -> NEVER clears" % neta)
        print("                 verdict: MATH-DEAD [exit %d] -- x%g is not "
              "enough; the fresh inflow alone outruns doubled capacity"
              % (EXIT_GATE, opt.accelerate))
        gate = True

    print()
    if gate:
        print("verdict: GATE RED [exit %d] -- at least one scenario is "
              "mathematically dead or the doom date is inside the window"
              % EXIT_GATE)
        return EXIT_GATE
    print("verdict: FEASIBLE [exit %d] -- a path out exists on paper; the "
          "walking is yours" % EXIT_OK)
    return EXIT_OK


def cmd_leeches(opt):
    as_of = _parse_asof(opt.as_of)
    if opt.leeches is None:
        raise LedgerError("leeches command needs --leeches FILE")
    all_rows = load_reviews(opt.ledger)  # full range: the date ceiling
    if not all_rows:
        raise LedgerError("ledger has no rows on or before as-of")
    full_max = all_rows[-1]["date"]
    rows = [r for r in all_rows if as_of is None or r["date"] <= as_of]
    leech = load_leeches(opt.leeches)
    name = os.path.basename(opt.ledger)
    lname = os.path.basename(opt.leeches)
    print("=== Avalanche · leech census ===")
    print("ledger: %s   rows: %d   table: %s   cards: %d"
          % (name, len(rows), lname, len(leech)))
    if not rows:
        print("declining: no rows on or before as-of")
        return EXIT_THIN

    items = sorted(leech.items(), key=lambda kv: (-kv[1], kv[0]))
    total = sum(v for _, v in items)
    print("lapses total: %d" % total)
    full_range = as_of is None or as_of >= full_max
    again_total = sum(r["again"] for r in rows)
    if full_range:
        print("parity vs ledger: lapses %d == again %d %s"
              % (total, again_total, "OK" if total == again_total else "MISMATCH"))
    else:
        print("parity vs ledger: n/a (--as-of truncation; the census has no dates)")

    thin = len(rows) < THIN_ROWS
    if not thin and total:
        top_n = max(1, int(math.ceil(0.2 * len(items))))
        top_share = 100.0 * sum(v for _, v in items[:top_n]) / total
        print("forgetting concentration: top 20%% of cards (%d) hold %.1f%% "
              "of all lapses" % (top_n, top_share))

    print()
    print("busiest cards:")
    for card, lapses in items[:15]:
        print("  %s   %d" % (pad(card, 24), lapses))
    if len(items) > 15:
        print("  ... and %d more rows" % (len(items) - 15))

    kill = [(c, v) for c, v in items if v >= opt.leech_line]
    print()
    if kill:
        kill_lapses = sum(v for _, v in kill)
        print("kill list (lapses >= %d): %d card(s), %d lapses (%.1f%% of all "
              "forgetting)" % (opt.leech_line, len(kill), kill_lapses,
                               100.0 * kill_lapses / total if total else 0.0))
        if not thin:
            relief = kill_lapses / float(min(opt.window, len(rows)))
            print("suspending the kill list removes at least %.1f due/day "
                  "(lower bound = their past lapses / %d review-days)"
                  % (relief, min(opt.window, len(rows))))
        print("verdict: KILL-LIST [exit %d] -- these cards are the avalanche's "
              "core sample; suspension is a decision, not an action"
              % EXIT_GATE)
        return EXIT_GATE
    print("kill list (lapses >= %d): empty" % opt.leech_line)
    print("verdict: CLEAN [exit %d] -- no card has lapsed past the line"
          % EXIT_OK)
    return EXIT_OK


def cmd_validate(opt):
    as_of = _parse_asof(opt.as_of)
    all_rows = load_reviews(opt.ledger)  # full range: the date ceiling
    if not all_rows:
        raise LedgerError("ledger has no rows")
    full_max = all_rows[-1]["date"]
    rows = [r for r in all_rows if as_of is None or r["date"] <= as_of]
    name = os.path.basename(opt.ledger)
    print("=== Avalanche · ledger check ===")
    if not rows:
        print("ledger: %s   rows: 0" % name)
        print("verdict: EMPTY [exit %d] -- nothing to check" % EXIT_OK)
        return EXIT_OK
    m = None  # validate is integrity-only: no flow statistics needed
    carr = carried_seq(rows)
    paid_ahead = sum(1 for r in rows if r["done"] > r["due"])
    forgiven = [rows[i]["date"].isoformat() for i in range(1, len(rows))
                if rows[i]["due"] < carr[i - 1]]
    _header(name, rows, as_of)
    print("columns and values (non-negative integers, again <= done) .. OK")
    print("dates strictly ascending, unique, valid calendar .. OK")
    print("paid-ahead rows (done > due): %d .. disclosed, not an error"
          % paid_ahead)
    if forgiven:
        print("forgiven rows (due < carried): %d on %s .. cards left the deck "
              "off-book" % (len(forgiven), ", ".join(forgiven)))
    else:
        print("carried continuity: 0 rows with due < previous carried .. OK")
    if opt.leeches is not None:
        leech = load_leeches(opt.leeches)
        total = sum(leech.values())
        again_total = sum(r["again"] for r in rows)
        if as_of is not None and as_of < full_max:
            print("leech parity: skipped (--as-of truncation; the census has "
                  "no dates)")
        elif total == again_total:
            print("leech parity: lapses %d == again %d .. OK" % (total, again_total))
        else:
            raise LedgerError("leech parity broken: lapses %d != again %d "
                              "(the census must be the complete lapse history)"
                              % (total, again_total))
    print("verdict: LEDGER OK [exit %d]" % EXIT_OK)
    return EXIT_OK


# ---------------------------------------------------------------- cli

def _pos_int(s):
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("not an integer: %r" % s)
    if v < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return v


def _nonneg_int(s):
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("not an integer: %r" % s)
    if v < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return v


def build_parser():
    p = argparse.ArgumentParser(
        prog="avalanche.py",
        description="雪崩 · Avalanche -- spaced-repetition backlog ledger")
    sub = p.add_subparsers(dest="cmd")

    def common(sp, stats=True):
        sp.add_argument("ledger", help="reviews.tsv (date/due/done/again/new)")
        sp.add_argument("--leeches", help="leeches.tsv (card/lapses)")
        sp.add_argument("--as-of", dest="as_of",
                        help="pin the replay date (default: max ledger date)")
        if stats:
            sp.add_argument("--window", type=_pos_int, default=28,
                            help="trailing review-days for flow statistics")
            sp.add_argument("--doom-line", type=_pos_int, dest="doom_line",
                            help="backlog level that means reviews have degraded")
            sp.add_argument("--doom-window", type=_pos_int, dest="doom_window",
                            default=42,
                            help="a projected crossing within this many days is AVALANCHE")
            sp.add_argument("--leech-line", type=_pos_int, dest="leech_line",
                            default=8, help="lapse count that puts a card on the kill list")

    sp = sub.add_parser("report", help="debt stock, flow spread, doom projection")
    common(sp)
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("add", help="new-card quota gate: may I add N cards today?")
    common(sp)
    sp.add_argument("n", type=_nonneg_int, help="new cards you want to add today")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("simulate", help="as-is / freeze / accelerate catch-up scenarios")
    common(sp)
    sp.add_argument("--accelerate", type=float, default=2.0,
                    help="capacity multiplier for the accelerate scenario")
    sp.add_argument("--freeze-inflow", type=_pos_int, dest="freeze_inflow",
                    help="override F for the freeze/accelerate projections")
    sp.set_defaults(func=cmd_simulate)

    sp = sub.add_parser("leeches", help="lapse census: concentration, kill list")
    common(sp)
    sp.set_defaults(func=cmd_leeches)

    sp = sub.add_parser("validate", help="ledger integrity checks")
    common(sp, stats=False)
    sp.set_defaults(func=cmd_validate)
    return p


def main(argv=None):
    opt = build_parser().parse_args(argv)
    if not hasattr(opt, "func"):
        build_parser().print_help()
        return EXIT_OK
    try:
        return opt.func(opt)
    except LedgerError as exc:
        sys.stderr.write("avalanche: %s\n" % exc)
        return EXIT_BROKEN


if __name__ == "__main__":
    sys.exit(main())
