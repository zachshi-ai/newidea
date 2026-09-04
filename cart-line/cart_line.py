#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cart-line · 凑单线 —— 满减凑单的决策线与幻觉审计.

问题：结算页只展示一个数字——「已为你节省 ¥X」，而凑单决策的四个变量
（购物车小计、满减门槛、优惠额、凑单价）一个都不出现在那行字里。直觉
算得出门槛，算不出白赚区间；月底的战报记得优惠额，从不记得你为凑单
加购的每一件「顺手买了」；为凑单买的东西到家后的命运，没有任何账本
记录。于是每年两场大促成了全民数学考试，而所有人只对答案的第一行。

cart-line 把这道题拆成几本账：

  * judge    结算页裁决：缺口 g 与优惠 d 之比定生死——g ≤ d 存在白赚
             区间 [g, d]（凑单额落区内实付必降），g > d 判凑不平
             （NOT_WORTH，exit 4）——放弃满减是数学最优；候选凑单品
             逐件裁决 + 最优组合枚举
  * audit    订单审计：每单净收益 = 优惠 − 凑单额；幻觉差 = 平台口径
             − 真实净收益 ≡ 凑单总额（代数恒等式，钉 9 位小数）——
             平台每省略你花掉的凑单钱，差的就是那笔钱本身
  * fate     命运对账：凑单品垃圾率 vs 计划商品垃圾率——促销诱发的
             购买是不是更容易吃灰，第一次有了行为证据
  * simulate 决策回放：每单对着「最优卡线」重放，凑超/硬凑/过线手贱
             三种错误逐一定价；回放是镜子不是法官，红线在 audit
  * validate 账本自检：全部恒等式复算

诚实条款：filler（凑单）是动机不是商品属性，只有你自己知道哪件是
顺手买的——账本记的是你申报的动机；它不连任何商城接口、不算红包
叠加、不预测价格，judge 只回答「这一单数学上怎么走」。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from itertools import combinations

VERSION = "1.0.0"

RED_LINE = 0.30           # filler ratio red line (discount eaten by fillers)
MIN_ORDERS = 5            # refuse ledger-wide conclusions below this
MIN_FILLER_SETTLED = 5    # refuse fate verdicts below this many settled fillers
FATE_COVER_MIN = 0.50     # min filler-value coverage for a fate verdict
FATE_RED = 0.50           # filler junk-rate red line
MAX_COMBO_ITEMS = 15      # subset enumeration guard for judge combos
EPS = 1e-9

EXIT_OK = 0
EXIT_DATA = 2
EXIT_THIN = 3
EXIT_RED = 4

USAGE = """usage: cart_line.py <command> [args]

commands:
  judge    --subtotal S --rule R [--fill C]...   checkout verdict: the line,
                                                 each candidate, best combo
  audit    <orders.tsv>                          promo-season audit: net gain,
                                                 illusion identity, filler ratio
  fate     <orders.tsv> <items.tsv>              filler fate vs planned fate
  simulate <orders.tsv>                       decision replay against the line
  validate <orders.tsv> [items.tsv]              re-check every identity

orders.tsv columns (tab separated, one row per order):
  date  order  rule  planned  filler  discount  paid
  rule: every:M:D | full:M:D | none
  planned  = what you were going to buy anyway (list prices, this order)
  filler   = what you added only to cross the line
  discount = promotion actually granted (threshold math only)
  paid     = what you actually paid

items.tsv columns (one row per item whose fate you care about):
  date  order  name  price  filler  fate  fate_date
  filler: 0|1    fate: used | idle | trashed | open
"""


class LedgerError(Exception):
    """Bad ledger row or usage — exit 2."""


class ThinLedger(Exception):
    """Not enough evidence to conclude — exit 3."""


# ---------------------------------------------------------------- parsing

def parse_date(text, field):
    try:
        return date.fromisoformat(text.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad date %r in field %r (want YYYY-MM-DD)" % (text, field))


def parse_money(text, field, allow_zero=True):
    try:
        value = float(text.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad number %r in field %r" % (text, field))
    if value < 0 or (value == 0 and not allow_zero):
        raise LedgerError("field %r must be %s, got %s"
                          % (field, ">= 0" if allow_zero else "> 0", value))
    return value


def parse_rule(text):
    """`every:M:D` / `full:M:D` / `none` -> (kind, m, d)."""
    raw = text.strip()
    if raw == "none":
        return ("none", 0.0, 0.0)
    parts = raw.split(":")
    if len(parts) != 3 or parts[0] not in ("every", "full"):
        raise LedgerError("bad rule %r (want every:M:D | full:M:D | none)" % text)
    try:
        m = float(parts[1])
        d = float(parts[2])
    except ValueError:
        raise LedgerError("bad rule numbers in %r" % text)
    if m <= 0 or d <= 0 or d >= m:
        raise LedgerError("rule %r needs 0 < d < m" % text)
    return (parts[0], m, d)


def read_tsv(path, ncols):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise LedgerError("cannot read %s: %s" % (path, exc))
    rows = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip("\n")
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            continue
        cells = stripped.split("\t")
        if len(cells) < ncols:
            raise LedgerError("%s line %d: want %d columns, got %d"
                              % (path, i, ncols, len(cells)))
        rows.append((i, cells))
    return rows


class Order(object):
    __slots__ = ("date", "oid", "rule", "planned", "filler", "discount",
                 "paid", "line")


class Item(object):
    __slots__ = ("date", "oid", "name", "price", "filler", "fate",
                 "fate_date", "line")


FATES = ("used", "idle", "trashed", "open")


def load_orders(path):
    orders = []
    for lineno, c in read_tsv(path, 7):
        if c[0].strip() == "date":          # header
            continue
        o = Order()
        o.line = lineno
        o.date = parse_date(c[0], "date")
        o.oid = c[1].strip()
        if not o.oid:
            raise LedgerError("%s line %d: empty order id" % (path, lineno))
        o.rule = parse_rule(c[2])
        o.planned = parse_money(c[3], "planned")
        o.filler = parse_money(c[4], "filler")
        o.discount = parse_money(c[5], "discount")
        o.paid = parse_money(c[6], "paid")
        check_consistency(o, path)
        orders.append(o)
    if not orders:
        raise LedgerError("%s: no orders loaded" % path)
    return orders


def check_consistency(o, path):
    """Two hard identities every order must satisfy (exit 2 otherwise)."""
    where = "%s line %d (%s)" % (path, o.line, o.oid)
    granted = rule_discount(o.rule, o.planned + o.filler)
    if abs(granted - o.discount) > 0.005:
        raise LedgerError("%s: discount %s does not match rule %s on total %s"
                          " (rule grants %s) — the ledger only records"
                          " threshold math"
                          % (where, money(o.discount), rule_name(o.rule),
                             money(o.planned + o.filler), money(granted)))
    if abs(o.planned + o.filler - o.discount - o.paid) > 0.01:
        raise LedgerError("%s: paid %s != planned + filler - discount = %s"
                          % (where, money(o.paid),
                             money(o.planned + o.filler - o.discount)))


def load_items(path, orders=None):
    items = []
    known = {o.oid for o in orders} if orders is not None else None
    for lineno, c in read_tsv(path, 7):
        if c[0].strip() == "date":          # header
            continue
        it = Item()
        it.line = lineno
        it.date = parse_date(c[0], "date")
        it.oid = c[1].strip()
        it.name = c[2].strip()
        if not it.name:
            raise LedgerError("%s line %d: empty name" % (path, lineno))
        it.price = parse_money(c[3], "price")
        if c[4].strip() not in ("0", "1"):
            raise LedgerError("%s line %d: filler must be 0 or 1, got %r"
                              % (path, lineno, c[4]))
        it.filler = int(c[4].strip())
        it.fate = c[5].strip()
        if it.fate not in FATES:
            raise LedgerError("%s line %d: fate must be one of %s, got %r"
                              % (path, lineno, "|".join(FATES), c[5]))
        it.fate_date = parse_date(c[6], "fate_date") if c[6].strip() else None
        if it.fate == "open":
            if it.fate_date is not None:
                raise LedgerError("%s line %d: open rows leave fate_date empty"
                                  % (path, lineno))
        else:
            if it.fate_date is None:
                raise LedgerError("%s line %d: settled rows need a fate_date"
                                  % (path, lineno))
            if it.fate_date < it.date:
                raise LedgerError("%s line %d: fate_date before buy date"
                                  % (path, lineno))
        if known is not None and it.oid not in known:
            raise LedgerError("%s line %d: order %r is not in the order ledger"
                              % (path, lineno, it.oid))
        items.append(it)
    return items


# ------------------------------------------------------------ rule math
#
# Two real-world threshold shapes, one decision line:
#   full:M:D   one-shot  — total >= M grants D, once
#   every:M:D  stacking  — each full M of total grants D
# Unified: let g be the gap from the cart to the next grant.
#   g <= D  -> a win zone [g, D] exists (fill anywhere inside, you pay less)
#   g >  D  -> NOT_WORTH: every filler either misses the line (pays +C)
#              or crosses it paying +C-D > 0. Walking away is optimal.
# Already past the line (full) or resting exactly on it (every) -> line 0.

def rule_discount(rule, total):
    kind, m, d = rule
    if kind == "none" or total <= 0:
        return 0.0
    if kind == "full":
        return d if total >= m - EPS else 0.0
    # every: guard the floor against float dust (299.999999...)
    return d * int(total / m + EPS)


def rule_name(rule):
    kind, m, d = rule
    if kind == "none":
        return "none"
    return "%s:%g:%g" % (kind, m, d)


def rule_line(rule, subtotal):
    """The decision line for a cart of `subtotal` under `rule`.

    Returns (kind, gap, d): kind in NO_NEED / FILLABLE / NOT_WORTH;
    gap = money missing to the next grant (None when nothing to chase).
    """
    kind, m, d = rule
    if kind == "none":
        return ("NO_NEED", None, 0.0)
    if kind == "full":
        if subtotal >= m - EPS:
            return ("NO_NEED", None, d)
        gap = m - subtotal
    else:  # every
        rest = subtotal - m * int(subtotal / m + EPS)
        if rest <= EPS:
            return ("NO_NEED", None, d)
        gap = m - rest
    if gap <= d + EPS:
        return ("FILLABLE", gap, d)
    return ("NOT_WORTH", gap, d)


# ------------------------------------------------------------ formatting

def money(x):
    return (u"¥" if x >= 0 else u"-¥") + "%.2f" % abs(x)


def pct(x):
    return "%.1f%%" % (100.0 * x)


def span_weeks(orders):
    days = (max(o.date for o in orders) - min(o.date for o in orders)).days
    return max(days / 7.0, 1.0)


def per_order_facts(o):
    """Derived per-order quantities; each one has a pinned identity."""
    free = rule_discount(o.rule, o.planned)          # grant without any filler
    earned = o.discount - free                       # bought with fillers
    net = o.discount - o.filler                      # real net gain of the order
    bare = o.planned - free                          # never-filler checkout
    return free, earned, net, bare


# ------------------------------------------------------------------ judge

def candidate_verdict(rule, subtotal, c):
    """delta = what the candidate changes in what you pay."""
    delta = c - (rule_discount(rule, subtotal + c) - rule_discount(rule, subtotal))
    if delta < -EPS:
        return ("FILL", delta)
    if delta <= EPS:
        return ("FLAT", delta)
    return ("OVERPAY", delta)


def best_combo(rule, subtotal, candidates):
    """Cheapest subset that lands inside the win zone [gap, d]."""
    kind, gap, d = rule_line(rule, subtotal)
    if kind != "FILLABLE" or not candidates:
        return None
    best = None
    cands = candidates[:MAX_COMBO_ITEMS]
    for n in range(1, len(cands) + 1):
        for combo in combinations(range(len(cands)), n):
            total = sum(cands[i] for i in combo)
            if total >= gap - EPS and total <= d + EPS:
                if best is None or total < best[0] - EPS:
                    best = (total, combo)
    return best


def cmd_judge(args):
    rule = parse_rule(args.rule)
    if args.subtotal < 0:
        raise LedgerError("--subtotal must be >= 0")
    kind, gap, d = rule_line(rule, args.subtotal)

    print("== cart-line · the line ==")
    print("rule %s, subtotal %s" % (rule_name(rule), money(args.subtotal)))

    candidates = args.fill or []
    for c in candidates:
        if c < 0:
            raise LedgerError("--fill values must be >= 0")

    if kind == "NO_NEED":
        print("line: nothing to chase — the cart already holds the grant.")
        print("      any filler now pays +C, pure loss. Keep the checkout as is.")
        return EXIT_OK if not candidates else EXIT_OK
    if kind == "NOT_WORTH":
        print("line: gap %s > discount %s — NO winning fill exists." % (money(gap), money(d)))
        print("      any filler either misses the line (pays +C) or crosses it")
        print("      paying +%s at best. The cheapest way through this checkout" % money(gap - d))
        print("      is to buy nothing extra.")
        if candidates:
            print("")
            print("candidates (for the record):")
            for c in candidates:
                verdict, delta = candidate_verdict(rule, args.subtotal, c)
                sign = "+" if delta > 0 else ""
                print("  %7s  %-7s pays %s%s" % (money(c), verdict, sign, money(delta)))
        print("")
        print("VERDICT: NOT_WORTH — the discount is priced out of reach. exit 4")
        return EXIT_RED

    print("line: gap %s, win zone [%s, %s], max gain %s"
          % (money(gap), money(gap), money(d), money(d - gap)))
    print("      (fill exactly %s and pay %s instead of %s)"
          % (money(gap), money(args.subtotal - d + gap), money(args.subtotal)))

    if candidates:
        print("")
        print("candidates:")
        for c in candidates:
            verdict, delta = candidate_verdict(rule, args.subtotal, c)
            note = ""
            if verdict == "FILL":
                note = "  (net gain %s)" % money(-delta)
            elif verdict == "FLAT":
                note = "  (free item, same total)"
            else:
                note = "  (overpays %s)" % money(delta)
            sign = "+" if delta > 0 else ""
            print("  %7s  %-7s pays %s%s%s" % (money(c), verdict, sign, money(delta), note))
        fills = [c for c in candidates
                 if candidate_verdict(rule, args.subtotal, c)[0] == "FILL"]
        print("")
        if fills:
            best_single = min(fills, key=lambda c: candidate_verdict(
                rule, args.subtotal, c)[1])
            print("best single pick: %s (gain %s)" % (money(best_single),
                  money(-candidate_verdict(rule, args.subtotal, best_single)[1])))
        else:
            print("best single pick: none — every candidate overpays.")
        best = best_combo(rule, args.subtotal, candidates)
        if best:
            total, combo = best
            names = " + ".join(money(candidates[i]) for i in combo)
            print("best combo: %s (%s, %d item(s), gain %s)"
                  % (money(total), names, len(combo), money(d - total)))
        else:
            print("best combo: none — no subset of your candidates lands in"
                  " the win zone [%s, %s]" % (money(gap), money(d)))
        any_fill = any(candidate_verdict(rule, args.subtotal, c)[0] == "FILL"
                       for c in candidates)
        if not any_fill and best is None:
            print("")
            print("VERDICT: nothing in the cart list wins. exit 4")
            return EXIT_RED
    return EXIT_OK


# ------------------------------------------------------------------ audit

def cmd_audit(args):
    orders = load_orders(args.ledger)
    if len(orders) < MIN_ORDERS:
        raise ThinLedger("%d orders is too few for a season verdict"
                         " (need >= %d)" % (len(orders), MIN_ORDERS))
    total_discount = sum(o.discount for o in orders)
    if total_discount <= EPS:
        raise ThinLedger("no threshold discount anywhere in this ledger —"
                         " nothing to audit")

    filler = sum(o.filler for o in orders)
    planned = sum(o.planned for o in orders)
    paid = sum(o.paid for o in orders)
    net = total_discount - filler
    ratio = filler / total_discount
    free = sum(per_order_facts(o)[0] for o in orders)
    earned = total_discount - free
    cash_diff = filler - earned                  # == paid - sum(bare)
    weeks = span_weeks(orders)
    yearly = cash_diff / weeks * 52.0
    losers = [o for o in orders if o.discount - o.filler < -EPS]

    print("== cart-line · order audit ==")
    print("%d orders, %s → %s (%.1f weeks)"
          % (len(orders), min(o.date for o in orders),
             max(o.date for o in orders), weeks))
    print("planned %s | filler %s | discount %s | paid %s"
          % (money(planned), money(filler), money(total_discount), money(paid)))
    print("")
    print("the platform says:  \"you saved %s\"" % money(total_discount))
    print("the ledger says:    you really kept %s  (net = discount - filler)"
          % money(net))
    print("the difference %s is EXACTLY the filler total — to the last cent,"
          % money(filler))
    print("by algebra: every yuan of filler you paid is a yuan the banner"
          " never mentions.")
    print("")
    print("where the discount came from:")
    print("  free   %s  (planned alone already crossed the line — no filler needed)"
          % money(free))
    print("  earned %s  (bought with %s of fillers -> cash diff +%s)"
          % (money(earned), money(filler), money(cash_diff)))
    identity = total_discount - net - filler
    print("")
    print("illusion identity: discount - net - filler = %.9f" % identity)
    print("filler ratio: %s of the discount was eaten by fillers (red line %s)"
          % (pct(ratio), pct(args.red_line)))

    code = EXIT_OK
    if ratio > args.red_line:
        code = EXIT_RED
        print("  -> VERDICT: RED, exit 4 — the promotion is mostly a mirror"
              " of your own spending.")
    else:
        print("  -> VERDICT: GREEN")

    if losers:
        print("")
        print("overpaid orders (net < 0 — paid more than bare-buy):")
        for o in sorted(losers, key=lambda o: o.discount - o.filler):
            kind, gap, d = rule_line(o.rule, o.planned)
            why = ""
            if kind == "NOT_WORTH":
                why = " — gap %s > d %s, unwinnable" % (money(gap), money(d))
            elif kind == "FILLABLE":
                why = " — line was %s, you filled %s" % (money(gap), money(o.filler))
            else:
                why = " — the grant was already yours before any filler"
            print("  %-7s net %s  (filler %s for a %s discount%s)"
                  % (o.oid, money(o.discount - o.filler), money(o.filler),
                     money(o.discount), why))

    print("")
    print("at this pace the promo season taxes %s/year in filler cash"
          % money(yearly))
    print("(promo pace is not the year's pace — same-ruler reading only.)")
    return code


# ------------------------------------------------------------------- fate

def cmd_fate(args):
    orders = load_orders(args.orders)
    items = load_items(args.items, orders)
    order_filler = sum(o.filler for o in orders)
    if order_filler <= EPS:
        raise ThinLedger("the order ledger has no fillers — no fate to settle")

    filler_rows = [it for it in items if it.filler == 1]
    covered = sum(it.price for it in filler_rows)
    cover = covered / order_filler
    settled_f = [it for it in filler_rows if it.fate != "open"]
    junk_f = [it for it in settled_f if it.fate in ("idle", "trashed")]
    planned_rows = [it for it in items if it.filler == 0]
    settled_p = [it for it in planned_rows if it.fate != "open"]
    junk_p = [it for it in settled_p if it.fate in ("idle", "trashed")]

    print("== cart-line · filler fate ==")
    print("coverage: filler items %s of %s (%s)%s"
          % (money(covered), money(order_filler), pct(cover),
             "" if cover >= FATE_COVER_MIN else "  <-- BELOW %s: verdict withheld"
             % pct(FATE_COVER_MIN)))
    if not settled_f:
        raise ThinLedger("no settled filler rows — nothing to judge yet")
    if len(settled_f) < MIN_FILLER_SETTLED:
        raise ThinLedger("%d settled filler rows is too few for a fate verdict"
                         " (need >= %d)" % (len(settled_f), MIN_FILLER_SETTLED))

    def stats(rows):
        settled = [it for it in rows if it.fate != "open"]
        junk = [it for it in settled if it.fate in ("idle", "trashed")]
        used = [it for it in settled if it.fate == "used"]
        cost = sum(it.price for it in settled)
        junk_cost = sum(it.price for it in junk)
        rate = junk_cost / cost if cost > EPS else None
        crate = len(junk) / len(settled) if settled else None
        return (len(rows), len(settled), len(used), len(junk), junk_cost,
                rate, crate)

    fs = stats(filler_rows)
    ps = stats(planned_rows)
    print("")
    print("%-14s %5s %8s %6s %8s %10s %8s %12s"
          % ("", "rows", "settled", "used", "junk(n)", "junk(¥)", "junk(%)", ""))
    for label, s in (("filler items", fs), ("planned items", ps)):
        nrows, nsettled, nused, njunk, junk_cost, rate, crate = s
        lamp = ""
        if label == "filler items" and rate is not None:
            lamp = "  <-- RED" if rate > FATE_RED else "  <-- ok"
        print("%-14s %5d %8d %6d %8d %10s %8s %s"
              % (label, nrows, nsettled, nused, njunk, money(junk_cost),
                 pct(crate) if crate is not None else "n/a", lamp))

    fr = fs[5]
    pr = ps[5]
    print("")
    if cover < FATE_COVER_MIN:
        print("filler coverage %s is below %s — the sample is too partial to"
              " judge (banners withheld)." % (pct(cover), pct(FATE_COVER_MIN)))
        return EXIT_OK
    if fr is not None and fr > FATE_RED:
        print("filler junk rate %s — more than half of what you bought for the"
              % pct(fr))
        print("line gathers dust. The discount was never the point; the point")
        print("was the line.")
        print("-> VERDICT: RED, exit 4")
        code = EXIT_RED
    else:
        print("filler junk rate %s (red line %s)" % (pct(fr) if fr is not None else "n/a",
                                                     pct(FATE_RED)))
        code = EXIT_OK
    if fr is not None and pr is not None and pr > EPS:
        print("vs planned items %s — fillers die %.1fx faster."
              % (pct(pr), fr / pr))
    print("")
    print("(the filler tag is a motive, not a product property — only you")
    print(" know which purchase was yours and which was the threshold's.)")
    return code


# --------------------------------------------------------------- simulate

def replay_order(o):
    """Best achievable checkout for this order, and the name of the mistake."""
    free = rule_discount(o.rule, o.planned)
    bare = o.planned - free
    kind, gap, d = rule_line(o.rule, o.planned)
    if kind == "FILLABLE":
        at_line = o.planned + gap - rule_discount(o.rule, o.planned + gap)
        best = min(bare, at_line)
    else:
        at_line = None
        best = bare
    overpay = o.paid - best
    mistake = None
    if overpay > 0.005:
        if kind == "NOT_WORTH" and o.filler > EPS:
            mistake = "FORCED"
        elif kind == "NO_NEED" and o.filler > EPS:
            mistake = "GRATUITY"
        elif kind == "FILLABLE" and o.filler > gap + EPS:
            mistake = "OVERFILLED"
        elif kind == "FILLABLE":
            mistake = "UNDERSHOT"
        else:
            mistake = "MIXED"
    return bare, at_line, best, overpay, mistake


def cmd_simulate(args):
    orders = load_orders(args.ledger)
    print("== cart-line · decision replay ==")
    print("%-7s %-13s %9s %9s %9s %8s  %s"
          % ("order", "rule", "actual", "bare-buy", "best", "overpay", "verdict"))
    sum_actual = sum_bare = sum_best = 0.0
    over_total = 0.0
    mistakes = {"FORCED": [], "OVERFILLED": [], "GRATUITY": [],
                "UNDERSHOT": [], "MIXED": []}
    winners = []
    for o in orders:
        bare, at_line, best, overpay, mistake = replay_order(o)
        sum_actual += o.paid
        sum_bare += bare
        sum_best += best
        over_total += max(overpay, 0.0)
        if mistake:
            mistakes[mistake].append(o)
        elif o.filler > EPS:
            winners.append((o, best))
        if mistake is None:
            kind, gap, d = rule_line(o.rule, o.planned)
            if o.filler > EPS and kind == "FILLABLE" and abs(o.filler - gap) <= EPS:
                why = "optimal (filled the line at %s)" % money(gap)
            elif o.filler > EPS:
                why = "optimal (gain %s)" % money(o.discount - o.filler)
            else:
                why = "optimal" if kind != "NOT_WORTH" \
                    else "optimal (unwinnable gap %s > %s — walked away)" % (money(gap), money(d))
        elif mistake == "FORCED":
            kind, gap, d = rule_line(o.rule, o.planned)
            why = "FORCED (unwinnable gap %s > %s, filled %s anyway)" \
                % (money(gap), money(d), money(o.filler))
        elif mistake == "OVERFILLED":
            kind, gap, d = rule_line(o.rule, o.planned)
            why = "OVERFILLED (line %s, filled %s — +%s past the line)" \
                % (money(gap), money(o.filler), money(o.filler - gap))
        elif mistake == "UNDERSHOT":
            kind, gap, d = rule_line(o.rule, o.planned)
            why = "UNDERSHOT (line %s, filled only %s — never crossed)" \
                % (money(gap), money(o.filler))
        elif mistake == "GRATUITY":
            why = "GRATUITY (already past the line, filled %s anyway)" % money(o.filler)
        else:
            why = "MIXED"
        print("%-7s %-13s %9s %9s %9s %8s  %s"
              % (o.oid, rule_name(o.rule), money(o.paid), money(bare),
                 money(best), money(overpay), why))

    print("")
    print("three ledgers of the same promo:")
    print("  best decision      %s" % money(sum_best))
    print("  never any filler   %s" % money(sum_bare))
    print("  what you paid      %s" % money(sum_actual))
    if over_total > EPS:
        print("you paid %s more than the best replay:" % money(over_total))
        for name, label in (("FORCED", "forcing a fill on an unwinnable order"),
                            ("GRATUITY", "touching the cart after the line"),
                            ("OVERFILLED", "overshooting a winnable line"),
                            ("UNDERSHOT", "filling below the line, never crossing"),
                            ("MIXED", "mixed misses")):
            got = mistakes[name]
            if got:
                amount = sum(replay_order(o)[3] for o in got)
                print("  %9s  %s  (%s)" % (money(amount), label,
                                           "/".join(o.oid for o in got)))
    if winners:
        print("your winning fills (%s) were real — the tax lives in the others."
              % "/".join(o.oid for o, _ in winners))
    print("")
    print("(replay is a mirror, not a verdict — exit 0 by design;")
    print(" the red line lives in audit.)")
    return EXIT_OK


# --------------------------------------------------------------- validate

def cmd_validate(args):
    orders = load_orders(args.ledger)
    granted = sum(rule_discount(o.rule, o.planned + o.filler) for o in orders)
    paid_eq = sum(o.planned + o.filler - o.discount - o.paid for o in orders)
    filler = sum(o.filler for o in orders)
    discount = sum(o.discount for o in orders)
    net = discount - filler
    free = sum(per_order_facts(o)[0] for o in orders)
    earned = discount - free
    bare = sum(per_order_facts(o)[3] for o in orders)

    print("== cart-line · validate ==")
    print("orders loaded:                     %d" % len(orders))
    print("I1 rule recompute residual:        %.9f" % (granted - discount))
    print("I2 paid = planned+filler-discount: %.9f" % paid_eq)
    print("I3 illusion gap == filler total:   %.9f" % (discount - net - filler))
    print("I4 free + earned == discount:      %.9f" % (free + earned - discount))
    print("I5 cash diff == filler - earned:   %.9f"
          % ((sum(o.paid for o in orders) - bare) - (filler - earned)))
    print("I6 net == free - cash diff:        %.9f"
          % (net - (free - (sum(o.paid for o in orders) - bare))))
    worst = max(abs(granted - discount), abs(paid_eq), abs(discount - net - filler),
                abs(free + earned - discount))
    status = "OK" if worst <= 0.01 else "BROKEN"
    print("worst residual:                    %.9f  -> %s" % (worst, status))

    if args.items:
        items = load_items(args.items, orders)
        cover = sum(it.price for it in items if it.filler == 1) / filler \
            if filler > EPS else 0.0
        pcover = sum(it.price for it in items if it.filler == 0) \
            / sum(o.planned for o in orders)
        print("items loaded:                      %d" % len(items))
        print("filler value coverage:             %s" % pct(cover))
        print("planned value coverage:            %s" % pct(pcover))
    return EXIT_OK if worst <= 0.01 else EXIT_DATA


# ------------------------------------------------------------------- main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="cart_line.py",
        description="cart-line · Cart Line — the checkout line and the"
                    " savings-illusion audit")
    parser.add_argument("--version", action="version",
                        version="cart-line %s" % VERSION)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("judge", help="checkout verdict for a cart + candidates")
    p.add_argument("--subtotal", type=float, required=True)
    p.add_argument("--rule", default="every:300:50")
    p.add_argument("--fill", type=float, action="append", default=[])
    p.set_defaults(func=cmd_judge)

    p = sub.add_parser("audit", help="promo-season audit")
    p.add_argument("ledger")
    p.add_argument("--red-line", type=float, default=RED_LINE)
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("fate", help="filler fate vs planned fate")
    p.add_argument("orders")
    p.add_argument("items")
    p.set_defaults(func=cmd_fate)

    p = sub.add_parser("simulate", help="decision replay against the line")
    p.add_argument("ledger")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("validate", help="re-check every identity")
    p.add_argument("ledger")
    p.add_argument("items", nargs="?")
    p.set_defaults(func=cmd_validate)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        print(USAGE)
        return EXIT_DATA
    try:
        return args.func(args)
    except LedgerError as exc:
        sys.stderr.write("data error (exit 2): %s\n" % exc)
        return EXIT_DATA
    except ThinLedger as exc:
        sys.stderr.write("too thin to conclude (exit 3): %s\n" % exc)
        return EXIT_THIN


if __name__ == "__main__":
    sys.exit(main())
