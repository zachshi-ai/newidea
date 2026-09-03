#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fridge-void · 冰箱黑洞 —— 食材结局账本.

问题：浪费是一个家里唯一不被记账的经济活动。账单记下了每一次买进，
没有任何账本记下结局——那袋蔫掉的青菜、过期一周的酸奶、冰箱最深处
发现时已经变质的半根萝卜，在 0.5 秒的内疚之后被盖上垃圾桶盖子，从
统计上蒸发。于是月底只有一句「这个月买菜花了一千八」，永远没有另一
句「其中三百块直接进了垃圾桶」；更没有「为什么扔」——买多了、忘了
吃、还是不爱吃，同样的浪费每周原样重演，因为它从不留痕。

fridge-void 把「结局」补进账本。每一份食材记一行（TSV 手编：买进日
期/品名/品类/数量/金额/结局/死因），确定性算出：

  * ledger   全账本体检：浪费率（金额+重量双口径）、结局分布、年化
             「扔掉税」、红线 exit 4 / 样本不足 exit 3
  * board    品类红黑榜：每个品类对总浪费率的贡献分解，加总恒等于
             总浪费率（恒等式），点名重灾区
  * cause    死因结构：spoiled 放坏 / expired 过期 / rejected 不爱吃
             / leftover 做多了 / forgot 冰箱深处——死因决定对策
  * tax      浪费税：吃进嘴的每 1 元菜实际花了多少钱——你自己的
             个人通胀，与 CPI 无关
  * pantry   在库盘点：还没结局的食材按在库天数排行，谁快烂了
  * item     单品全史：这个品名买过几次、吃掉几次、扔掉几次
  * plan     采购过闸：购物车逐条过你自己的浪费史——试过扔掉过的
             精确品名直接拦截（exit 4），重灾区品类挂横幅

账本只陈述结局，扔不扔、买不买仍是人的决定；它拒绝的是让同样的
浪费继续隐形。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

VERSION = "1.0.0"

OUTCOMES = ("open", "ate", "tossed", "gave")
CAUSES = ("spoiled", "expired", "rejected", "leftover", "forgot")

RED_LINE = 0.15          # waste rate red line (default)
MIN_ENTRIES = 20         # refuse conclusions below this many entries
DISASTER_LINE = 0.30     # category disaster threshold
DISASTER_MIN = 5         # min settled entries for a category verdict
PANTRY_DUE_DAYS = 7      # open-item days before the DUE lamp
CART_SPIKE = 1.5         # cart total vs weekly average buying rate
WEEKS_FLOOR = 1.0        # minimum span in weeks for annualization

EXIT_OK = 0
EXIT_DATA = 2
EXIT_THIN = 3
EXIT_RED = 4

USAGE = """usage: fridge_void.py <command> [args]

commands:
  ledger <ledger.tsv>                 full audit: waste rate, outcomes, annualized void
  board  <ledger.tsv> [--top N]       category red/black board (contribution decomposition)
  cause  <ledger.tsv>                 cause-of-death structure of the tossed
  tax    <ledger.tsv>                 waste tax: real cost per yuan actually eaten
  pantry <ledger.tsv>                 open items by days on board, DUE lamps
  item   <ledger.tsv> <name>          full history of one item name
  plan   <ledger.tsv> <cart.tsv>      gate the shopping cart against your waste history

ledger columns (tab separated, one row per item batch):
  bought  name  category  qty  unit  cost  outcome  outcome_date  cause
  outcome: open|ate|tossed|gave    cause (tossed only):
           spoiled|expired|rejected|leftover|forgot
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


def parse_float(text, field, minimum=None):
    try:
        value = float(text.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad number %r in field %r" % (text, field))
    if minimum is not None and value < minimum:
        raise LedgerError("field %r must be >= %s, got %s" % (field, minimum, value))
    return value


def norm_name(text):
    return " ".join(str(text).split()).casefold()


class Entry(object):
    __slots__ = ("bought", "name", "slug", "category", "qty", "unit",
                 "cost", "outcome", "outcome_date", "cause", "line")

    def __init__(self, bought, name, category, qty, unit, cost,
                 outcome, outcome_date, cause, line):
        self.bought = bought
        self.name = name
        self.slug = norm_name(name)
        self.category = category
        self.qty = qty
        self.unit = unit
        self.cost = cost
        self.outcome = outcome
        self.outcome_date = outcome_date
        self.cause = cause
        self.line = line

    @property
    def kg(self):
        """Weight in kg for g/kg rows; None for ml/L/count units."""
        if self.unit in ("g",):
            return self.qty / 1000.0
        if self.unit in ("kg",):
            return self.qty
        return None


def read_tsv(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError as exc:
        raise LedgerError("cannot read %s: %s" % (path, exc))
    for lineno, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        cells = raw.split("\t")
        if len(cells) < 9:
            raise LedgerError("line %d: want 9 columns, got %d"
                              % (lineno, len(cells)))
        rows.append((lineno, [c.strip() for c in cells[:9]]))
    return rows


def load_ledger(path):
    entries = []
    for lineno, (bought, name, category, qty, unit, cost,
                 outcome, outcome_date, cause) in read_tsv(path):
        if bought == "bought":      # header row
            continue
        if not name:
            raise LedgerError("line %d: empty name" % lineno)
        if not category:
            raise LedgerError("line %d: empty category" % lineno)
        bought_on = parse_date(bought, "bought")
        ended_on = None if outcome_date == "" else \
            parse_date(outcome_date, "outcome_date")
        if outcome not in OUTCOMES:
            raise LedgerError("line %d: outcome %r not in %s"
                              % (lineno, outcome, "/".join(OUTCOMES)))
        if outcome == "open":
            if ended_on is not None:
                raise LedgerError("line %d: open rows must leave outcome_date empty"
                                  % lineno)
        else:
            if ended_on is None:
                raise LedgerError("line %d: settled rows need outcome_date" % lineno)
            if ended_on < bought_on:
                raise LedgerError("line %d: outcome_date before bought" % lineno)
        if outcome == "tossed":
            if cause not in CAUSES:
                raise LedgerError("line %d: tossed needs cause in %s"
                                  % (lineno, "/".join(CAUSES)))
        elif cause:
            raise LedgerError("line %d: cause only allowed on tossed rows" % lineno)
        entries.append(Entry(bought_on, name, category,
                             parse_float(qty, "qty", minimum=0.0),
                             unit or "-",
                             parse_float(cost, "cost", minimum=0.0),
                             outcome, ended_on, cause, lineno))
    if not entries:
        raise LedgerError("empty ledger: %s" % path)
    return entries


def load_cart(path):
    carts = []
    for lineno, cells in read_tsv(path):
        if cells[0] == "name":      # header row
            continue
        name, category, qty, unit, cost = cells[:5]
        if not name:
            raise LedgerError("line %d: empty name" % lineno)
        carts.append({"name": name, "slug": norm_name(name),
                      "category": category, "qty": parse_float(qty, "qty", 0.0),
                      "unit": unit or "-", "cost": parse_float(cost, "cost", 0.0),
                      "line": lineno})
    if not carts:
        raise LedgerError("empty cart: %s" % path)
    return carts


# ------------------------------------------------------------- accounting

def split(entries):
    settled = [e for e in entries if e.outcome != "open"]
    open_items = [e for e in entries if e.outcome == "open"]
    ate = [e for e in settled if e.outcome == "ate"]
    tossed = [e for e in settled if e.outcome == "tossed"]
    gave = [e for e in settled if e.outcome == "gave"]
    return settled, open_items, ate, tossed, gave


def money(value):
    return u"¥{:,.2f}".format(value)


def pct(value):
    return "{:.1f}%".format(value * 100.0)


def waste_rate(settled_cost, tossed_cost):
    if settled_cost <= 0:
        return None
    return tossed_cost / settled_cost


def category_board(entries, settled, tossed):
    """Per-category waste rate + contribution to the global rate."""
    settled_cost = sum(e.cost for e in settled)
    tossed_cost = sum(e.cost for e in tossed)
    board = []
    for cat in sorted({e.category for e in entries}):
        c_settled = [e for e in settled if e.category == cat]
        c_tossed = [e for e in tossed if e.category == cat]
        cs = sum(e.cost for e in c_settled)
        ct = sum(e.cost for e in c_tossed)
        board.append({
            "category": cat,
            "entries": len([e for e in entries if e.category == cat]),
            "settled_n": len(c_settled),
            "settled_cost": cs,
            "tossed_cost": ct,
            "rate": (ct / cs) if cs > 0 else None,
            "contribution": (ct / settled_cost) if settled_cost > 0 else None,
        })
    return board, settled_cost, tossed_cost


def cause_structure(tossed):
    total = sum(e.cost for e in tossed)
    rows = []
    for cause in CAUSES:
        rows_c = [e for e in tossed if e.cause == cause]
        cost_c = sum(e.cost for e in rows_c)
        if not rows_c:
            continue
        worst = max(rows_c, key=lambda e: e.cost)
        rows.append({
            "cause": cause, "n": len(rows_c), "cost": cost_c,
            "share": (cost_c / total) if total > 0 else None,
            "worst": worst,
        })
    return rows, total


def annualize(entries, tossed_cost):
    days = (max(e.bought for e in entries) - min(e.bought for e in entries)).days
    weeks = max(days / 7.0, WEEKS_FLOOR)
    return tossed_cost / weeks * 52.0, weeks


def per_week(entries, cost):
    days = (max(e.bought for e in entries) - min(e.bought for e in entries)).days
    weeks = max(days / 7.0, WEEKS_FLOOR)
    return cost / weeks


# ------------------------------------------------------------- reporting

def require_evidence(entries, settled):
    if len(entries) < MIN_ENTRIES:
        raise ThinLedger("only %d entries, need >= %d to conclude (exit 3)"
                         % (len(entries), MIN_ENTRIES))
    if not settled or sum(e.cost for e in settled) <= 0:
        raise ThinLedger("no settled cost in the ledger — nothing to audit (exit 3)")


def cmd_ledger(args):
    entries = load_ledger(args.ledger)
    settled, open_items, ate, tossed, gave = split(entries)
    require_evidence(entries, settled)

    settled_cost = sum(e.cost for e in settled)
    tossed_cost = sum(e.cost for e in tossed)
    rate = tossed_cost / settled_cost
    bought_cost = sum(e.cost for e in entries)

    weight_rows = [e for e in settled if e.kg is not None]
    weight_cover = len(weight_rows) / float(len(settled)) if settled else 0.0
    weight_tossed = sum(e.kg for e in weight_rows if e.outcome == "tossed")
    weight_total = sum(e.kg for e in weight_rows)
    weight_rate = (weight_tossed / weight_total) if weight_total > 0 else None

    tax_mult = 1.0 / (1.0 - rate)
    yearly_void, weeks = annualize(entries, tossed_cost)

    print("== fridge-void · full audit ==")
    print("entries: %d (%d settled, %d open)   span: %s -> %s (%.1f weeks)"
          % (len(entries), len(settled), len(open_items),
             min(e.bought for e in entries), max(e.bought for e in entries), weeks))
    print("bought in: %s   settled: %s   open: %s"
          % (money(bought_cost), money(settled_cost),
             money(bought_cost - settled_cost)))

    print("")
    print("-- outcome distribution (by cost) --")
    for label, rows, note in (
            ("ate", ate, ""),
            ("gave", gave, "  (a gift is not waste)"),
            ("tossed", tossed, "  <-- the void")):
        cost_c = sum(e.cost for e in rows)
        print("%-6s %s  %s%s" % (label, money(cost_c),
                                 pct(cost_c / settled_cost), note))

    print("")
    print("-- waste rate --")
    print("by cost:   %s  (red line %s)" % (pct(rate), pct(args.red_line)))
    if weight_rate is not None:
        print("by weight: %s   (weight coverage of settled rows: %s)"
              % (pct(weight_rate), pct(weight_cover)))
    else:
        print("by weight: n/a (no g/kg rows)")

    print("")
    print("-- waste tax --")
    print("every yuan you actually eat cost you %.3f yuan at the till (%+.1f%%)"
          % (tax_mult, (tax_mult - 1.0) * 100.0))

    print("")
    print("-- annualized void --")
    print("at this pace you throw %s of food into the bin every year" % money(yearly_void))

    if rate >= args.red_line:
        print("")
        print("VERDICT: RED — waste rate %s crosses the %s red line. exit 4"
              % (pct(rate), pct(args.red_line)))
        return EXIT_RED
    print("")
    print("VERDICT: OK — waste rate %s under the %s red line." % (pct(rate), pct(args.red_line)))
    return EXIT_OK


def cmd_board(args):
    entries = load_ledger(args.ledger)
    settled, _open_items, _ate, tossed, _gave = split(entries)
    require_evidence(entries, settled)
    board, settled_cost, tossed_cost = category_board(entries, settled, tossed)
    rate = tossed_cost / settled_cost

    rows = [b for b in board if b["settled_n"] > 0 or b["tossed_cost"] > 0]
    rows.sort(key=lambda b: (b["tossed_cost"], b["rate"] or 0.0), reverse=True)

    print("== fridge-void · category board ==")
    print("global waste rate %s   (settled %s, tossed %s)"
          % (pct(rate), money(settled_cost), money(tossed_cost)))
    print("")
    print("%-10s %9s %9s %8s %10s" % ("category", "bought", "tossed", "rate", "share"))
    for b in rows[:args.top]:
        rate_text = pct(b["rate"]) if b["rate"] is not None else "n/a"
        share_text = pct(b["contribution"]) if b["contribution"] is not None else "n/a"
        lamp = " <-- disaster" if (b["rate"] is not None
                                   and b["rate"] >= DISASTER_LINE
                                   and b["settled_n"] >= DISASTER_MIN) else ""
        print("%-10s %9s %9s %8s %10s%s"
              % (b["category"], money(b["settled_cost"]), money(b["tossed_cost"]),
                 rate_text, share_text, lamp))
    identity = sum(b["contribution"] for b in board if b["contribution"] is not None)
    print("")
    print("contributions add up to the global rate: %s + unlisted = %.9f"
          % (pct(rate), identity))

    disasters = [b for b in board if b["rate"] is not None and b["rate"] >= DISASTER_LINE
                 and b["settled_n"] >= DISASTER_MIN]
    return EXIT_RED if disasters else EXIT_OK


def cmd_cause(args):
    entries = load_ledger(args.ledger)
    settled, _open, _ate, tossed, _gave = split(entries)
    require_evidence(entries, settled)
    rows, total = cause_structure(tossed)
    if not rows:
        raise ThinLedger("nothing was ever tossed — no cause structure to show (exit 3)")

    print("== fridge-void · cause of death ==")
    print("tossed total: %s across %d rows" % (money(total), len(tossed)))
    print("")
    notes = {
        "spoiled":  "bought too much to finish in time — a QUANTITY problem",
        "expired":  "sat past its date untouched — a MOMENTUM problem",
        "rejected": "tried, disliked — a BLACKLIST problem, plan() will block it",
        "leftover": "cooked too much — a PORTION problem",
        "forgot":   "found too late in the back — a VISIBILITY problem",
    }
    for r in sorted(rows, key=lambda r: r["cost"], reverse=True):
        print("%-9s %s  %s  (%d rows)   %s"
              % (r["cause"], money(r["cost"]), pct(r["share"]), r["n"], notes[r["cause"]]))
        print("           worst single loss: %s %s %s on %s (%s)"
              % (money(r["worst"].cost), r["worst"].qty, r["worst"].unit,
                 r["worst"].name, r["worst"].bought))
    identity = sum(r["share"] for r in rows)
    print("")
    print("cause shares add up to 1: %.9f" % identity)
    return EXIT_OK


def cmd_tax(args):
    entries = load_ledger(args.ledger)
    settled, _open, ate, tossed, gave = split(entries)
    require_evidence(entries, settled)
    rate = sum(e.cost for e in tossed) / sum(e.cost for e in settled)
    mult = 1.0 / (1.0 - rate)
    eaten = sum(e.cost for e in ate) + sum(e.cost for e in gave)

    print("== fridge-void · waste tax ==")
    print("waste rate %s -> every yuan actually eaten cost %s at the till"
          % (pct(rate), u"¥{:.3f}".format(mult)))
    print("tax paid on this ledger: %s you bought but never ate"
          % money(sum(e.cost for e in tossed)))
    print("")
    print("per-category real price of food you eat:")
    board, _sc, _tc = category_board(entries, settled, tossed)
    for b in sorted(board, key=lambda b: b["settled_cost"], reverse=True):
        if b["settled_n"] == 0 or b["rate"] is None:
            continue
        if b["rate"] >= 1.0:
            print("  %-10s rate 100.0%% -> every gram of %s you ever bought"
                  % (b["category"], b["category"]))
            print("             ended in the bin. Price per yuan eaten: INFINITE. Stop buying it.")
            continue
        cat_mult = 1.0 / (1.0 - b["rate"])
        print("  %-10s rate %s  ->  ¥1 of %s eaten really costs ¥%.2f"
              % (b["category"], pct(b["rate"]), b["category"], cat_mult))
    print("")
    print("CPI does not know this tax exists. It is entirely yours.")
    return EXIT_OK


def cmd_pantry(args):
    entries = load_ledger(args.ledger)
    _settled, open_items, _a, _t, _g = split(entries)
    if not open_items:
        print("== fridge-void · pantry ==")
        print("pantry is empty — every row in the ledger is settled.")
        return EXIT_OK
    anchor = max(e.bought for e in entries)
    rows = sorted(open_items, key=lambda e: (anchor - e.bought).days, reverse=True)
    total_open = sum(e.cost for e in rows)

    print("== fridge-void · pantry (ledger today = %s) ==" % anchor)
    print("%d open items worth %s on the shelves" % (len(rows), money(total_open)))
    print("")
    due = 0
    for e in rows:
        days = (anchor - e.bought).days
        lamp = "DUE" if days > PANTRY_DUE_DAYS else "   "
        if days > PANTRY_DUE_DAYS:
            due += 1
        print("%s  %3dd  %-12s %-8s %s %s  %s"
              % (lamp, days, e.bought, e.category, money(e.cost), e.name, e.unit))
    print("")
    if due:
        print("%d item(s) past the %d-day DUE line — eat them first, buy nothing new."
              % (due, PANTRY_DUE_DAYS))
        return EXIT_RED
    print("nothing past the %d-day DUE line." % PANTRY_DUE_DAYS)
    return EXIT_OK


def cmd_item(args):
    entries = load_ledger(args.ledger)
    slug = norm_name(args.name)
    rows = [e for e in entries if e.slug == slug]
    if not rows:
        raise ThinLedger("no rows for item %r in the ledger (exit 3)" % args.name)
    settled, open_items, ate, tossed, gave = split(rows)
    bought_cost = sum(e.cost for e in rows)
    tossed_cost = sum(e.cost for e in tossed)
    rate = tossed_cost / sum(e.cost for e in settled) if settled else None

    print("== fridge-void · item history: %s ==" % args.name)
    print("batches: %d bought, %d settled, %d still open"
          % (len(rows), len(settled), len(open_items)))
    print("money: %s bought | ate %s | gave %s | tossed %s"
          % (money(bought_cost),
             money(sum(e.cost for e in ate)),
             money(sum(e.cost for e in gave)),
             money(tossed_cost)))
    if rate is not None:
        print("item waste rate: %s" % pct(rate))
    print("")
    for e in sorted(rows, key=lambda e: e.bought):
        end = e.outcome_date if e.outcome_date else "-"
        why = " (%s)" % e.cause if e.cause else ""
        print("  bought %s  %s %s  %s  -> %s %s%s"
              % (e.bought, e.qty, e.unit, money(e.cost), e.outcome, end, why))
    causes = [e.cause for e in tossed]
    if causes:
        top = max(set(causes), key=causes.count)
        print("")
        print("dominant cause: %s (%d of %d tosses)" % (top, causes.count(top), len(causes)))
    return EXIT_OK


def cmd_plan(args):
    entries = load_ledger(args.ledger)
    settled, _open, _ate, tossed, _gave = split(entries)
    require_evidence(entries, settled)

    blacklist = {e.slug for e in tossed if e.cause == "rejected"}
    board, _sc, _tc = category_board(entries, settled, tossed)
    disasters = {}
    for b in board:
        if b["rate"] is not None and b["rate"] >= DISASTER_LINE \
                and b["settled_n"] >= DISASTER_MIN:
            disasters[norm_name(b["category"])] = b
    weekly_buy = per_week(entries, sum(e.cost for e in entries))

    cart = load_cart(args.cart)
    cart_total = sum(c["cost"] for c in cart)

    print("== fridge-void · shopping cart gate ==")
    print("cart: %d lines, %s   |   your history: %s/week bought, waste rate history below"
          % (len(cart), money(cart_total), money(weekly_buy)))
    print("")

    blocked = 0
    warnings = 0
    for c in cart:
        slug = c["slug"]
        if slug in blacklist:
            blocked += 1
            print("BLOCKED  %-12s %s — you bought this before, tossed it as"
                  % (c["name"], money(c["cost"])))
            print("         rejected (tried, disliked). The blacklist is your own history.")
            continue
        lamp = "ok      "
        note = ""
        dis = disasters.get(norm_name(c["category"]))
        if dis is not None:
            lamp = "WARNING "
            warnings += 1
            note = ("disaster zone: you toss %s of everything you buy in %s"
                    % (pct(dis["rate"]), dis["category"]))
        print("%s %-12s %s  %s" % (lamp, c["name"], money(c["cost"]), note))

    if cart_total > CART_SPIKE * weekly_buy:
        warnings += 1
        print("")
        print("WARNING  cart total %s is %.1fx your weekly average (%s) —"
              % (money(cart_total), cart_total / weekly_buy, money(weekly_buy)))
        print("         the fridge is a shelf, not a vault. Bulk greens die young.")

    print("")
    if blocked:
        print("VERDICT: BLOCKED — %d line(s) on your own rejected blacklist. exit 4"
              % blocked)
        print("(drop them or overrule consciously; the ledger only refuses to stay silent.)")
        return EXIT_RED
    print("VERDICT: PASS — nothing blocked. %d warning(s) attached." % warnings)
    return EXIT_OK


# ------------------------------------------------------------------ main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="fridge_void.py",
        description="fridge-void · Fridge Void — the food-fate ledger")
    parser.add_argument("--version", action="version",
                        version="fridge-void %s" % VERSION)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("ledger", help="full audit")
    p.add_argument("ledger")
    p.add_argument("--red-line", type=float, default=RED_LINE)
    p.set_defaults(func=cmd_ledger)

    p = sub.add_parser("board", help="category contribution board")
    p.add_argument("ledger")
    p.add_argument("--top", type=int, default=8)
    p.set_defaults(func=cmd_board)

    p = sub.add_parser("cause", help="cause-of-death structure")
    p.add_argument("ledger")
    p.set_defaults(func=cmd_cause)

    p = sub.add_parser("tax", help="real cost of food actually eaten")
    p.add_argument("ledger")
    p.set_defaults(func=cmd_tax)

    p = sub.add_parser("pantry", help="open items by days on board")
    p.add_argument("ledger")
    p.set_defaults(func=cmd_pantry)

    p = sub.add_parser("item", help="history of one item name")
    p.add_argument("ledger")
    p.add_argument("name")
    p.set_defaults(func=cmd_item)

    p = sub.add_parser("plan", help="gate a shopping cart")
    p.add_argument("ledger")
    p.add_argument("cart")
    p.set_defaults(func=cmd_plan)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
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
