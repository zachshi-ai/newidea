#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recoup · 回血 —— 二手闲置变现账本.

卖不掉不是因为行情差，是你的锚还停在原价。
把闲置处置记成一本事件流账本（list/price/ask/sold/gave/trash/pull），
工具从你自己的成交史算出清算回血率、询价漏斗、降价弹性，
并给每件在架闲置两个判决：
  出手线（offer line）—— 有真实出价 >= 80% 挂价还捏着不卖，钱包在敲门；
  白送线（white-gift line）—— 零询价超过品类白送线，市场已宣判残余价值 ≈ 0，
                                继续挂只亏空间。

设计立场：
  先验只是垫底 —— 品类默认表是常识值不是平台数据；你自己的成交样本 >= 3
  时，你的账本就是你的手册。
  「今天」绝不取自系统时钟 —— 缺省 as-of = 账本最大事件日期，同一本账任何
  机器任何时间跑出的结果逐字节一致。
  拒答优先 —— 挂单周期 < 3、账龄 < 28 天、降价事件 < 3：如实拒判 exit 3。

零依赖：Python 3.8+ 纯标准库。MIT © 2026
"""

import argparse
import csv
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

EXIT_OK = 0
EXIT_BROKEN = 2      # 账本结构性损坏
EXIT_DECLINE = 3     # 样本不足/查无此物，拒绝裁决
EXIT_REDLINE = 4     # 红线：恋物警报 / 锚税超线

OFFER_LINE_RATIO = 0.80   # 出手线：max_offer >= 80% 挂价仍未成交
YELLOW_FRACTION = 0.50    # 挂龄达白送线一半 → 黄灯
WHITE_GIFT_MULT = 2.0     # 白送线 2 倍 → 恋物警报
ANCHOR_GAP_LINE = 0.30    # 锚税 > 30pp → 红线
MIN_LOTS = 3              # 少于 3 个挂单周期不出判决指标
MIN_SPAN_DAYS = 28        # 账龄不足 28 天不出白送线灯
MIN_REDUCTIONS = 3        # 降价事件不足 3 次不判弹性
ELASTIC_WINDOW = 14       # 降价弹性观察窗（天）

# 品类先验（常识值，非平台数据）：中位成交天数, 白送线天数, 先验回血率。
# 只在该品类你自己的成交样本 < 3 时垫底。
CATEGORY_PRIOR = {
    "electronics": (28, 84, 0.45),
    "appliance":   (35, 98, 0.40),
    "furniture":   (42, 112, 0.30),
    "apparel":     (21, 56, 0.25),
    "book":        (28, 70, 0.35),
    "toy":         (35, 84, 0.40),
    "other":       (35, 91, 0.35),
}

COLUMNS = ["date", "item", "action", "amount", "paid", "category", "note"]
ACTIONS = ("list", "price", "ask", "sold", "gave", "trash", "pull")
CLOSE_ACTIONS = ("sold", "gave", "trash", "pull")


# ---------------------------------------------------------------- 账本模型

@dataclass
class Event:
    lineno: int
    d: date
    item: str
    action: str
    amount: Optional[float]
    paid: Optional[float]
    category: Optional[str]
    note: str


@dataclass
class Lot:
    """一个挂单周期：list 开周期，sold/gave/trash/pull 结周期。"""
    item: str
    category: str
    paid: float
    listed: date
    prices: List[Tuple[date, float]] = field(default_factory=list)
    asks: List[Tuple[date, Optional[float]]] = field(default_factory=list)
    closed: Optional[Tuple[date, str, Optional[float]]] = None

    @property
    def current_price(self) -> float:
        return self.prices[-1][1]

    @property
    def n_asks(self) -> int:
        return len(self.asks)

    @property
    def max_offer(self) -> Optional[float]:
        offers = [a for _, a in self.asks if a is not None]
        return max(offers) if offers else None

    @property
    def reductions(self) -> List[Tuple[date, float, float]]:
        out = []
        for i in range(1, len(self.prices)):
            d0, p0 = self.prices[i - 1]
            d1, p1 = self.prices[i]
            if p1 < p0:
                out.append((d1, p0, p1))
        return out

    def age(self, as_of: date) -> int:
        return (as_of - self.listed).days

    def implied_ratio(self) -> float:
        return self.current_price / self.paid if self.paid > 0 else 0.0


@dataclass
class Ledger:
    lots: List[Lot]
    open_lots: List[Lot]
    as_of: date
    ignored_events: int
    errors: List[str]


class Broken(Exception):
    """账本结构性损坏（exit 2）。"""


def parse_date(text: str, lineno: int) -> date:
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise Broken("line %d: bad date %r (want YYYY-MM-DD)" % (lineno, text))


def parse_money(text: Optional[str], lineno: int, what: str,
                required: bool) -> Optional[float]:
    text = (text or "").strip()
    if text == "":
        if required:
            raise Broken("line %d: missing %s" % (lineno, what))
        return None
    try:
        value = float(text)
    except ValueError:
        raise Broken("line %d: %s is not a number: %r" % (lineno, what, text))
    if value <= 0:
        raise Broken("line %d: %s must be positive, got %g" % (lineno, what, value))
    return value


def load_ledger(path: str, as_of: Optional[date],
                cats: Dict[str, Tuple[int, int, float]]) -> Ledger:
    """解析事件流 TSV 并重放出挂单周期。结构性错误一律 Broken(exit 2)。"""
    category_table = dict(CATEGORY_PRIOR)
    category_table.update(cats or {})

    try:
        with open(path, "r", encoding="utf-8") as fh:
            rows = list(csv.reader(fh, delimiter="\t"))
    except OSError as exc:
        raise Broken("cannot read ledger: %s" % exc)
    if not rows:
        raise Broken("ledger is empty")
    header_at = None
    for i, row in enumerate(rows):
        if row and any(cell.strip() for cell in row) \
                and not row[0].lstrip().startswith("#"):
            header_at = i
            break
    if header_at is None:
        raise Broken("ledger has no header row")
    header = [h.strip() for h in rows[header_at]]
    for col in COLUMNS:
        if col not in header:
            raise Broken("ledger header missing column %r" % col)
    idx = {name: header.index(name) for name in COLUMNS}

    events: List[Event] = []
    errors: List[str] = []
    for lineno, row in enumerate(rows[header_at + 1:], start=header_at + 2):
        if not row or all(not cell.strip() for cell in row):
            continue
        cells = list(row) + [""] * (len(header) + 1 - len(row))
        if cells[idx["date"]].lstrip().startswith("#"):
            continue
        d = parse_date(cells[idx["date"]], lineno)
        item = cells[idx["item"]].strip()
        action = cells[idx["action"]].strip().lower()
        if not item:
            raise Broken("line %d: empty item" % lineno)
        if action not in ACTIONS:
            raise Broken("line %d: unknown action %r (want %s)"
                         % (lineno, action, "/".join(ACTIONS)))
        amount = parse_money(cells[idx["amount"]], lineno, "amount",
                             required=action in ("list", "price", "sold"))
        if action in ("gave", "trash", "pull") and amount is not None:
            raise Broken("line %d: %r takes no amount (it recovers nothing)"
                         % (lineno, action))
        paid = parse_money(cells[idx["paid"]], lineno, "paid",
                           required=action == "list")
        category = cells[idx["category"]].strip().lower() or None
        if action == "list":
            if category is None:
                raise Broken("line %d: list needs a category (have: %s)"
                             % (lineno, ", ".join(sorted(category_table))))
            if category not in category_table:
                raise Broken("line %d: unknown category %r (have: %s; "
                             "extend with --cat name:sell:dead:ratio)"
                             % (lineno, category, ", ".join(sorted(category_table))))
        note = cells[idx["note"]].strip()
        events.append(Event(lineno, d, item, action, amount, paid, category, note))

    if not events:
        raise Broken("ledger has no events")

    ledger_max = max(ev.d for ev in events)
    if as_of is None:
        as_of = ledger_max
    pending = [ev for ev in events if ev.d > as_of]
    usable = [ev for ev in events if ev.d <= as_of]
    if not usable:
        raise Broken("no events on or before as-of %s" % as_of.isoformat())

    lots: List[Lot] = []
    open_by_item: Dict[str, Lot] = {}
    for ev in usable:
        if ev.action == "list":
            if ev.item in open_by_item:
                errors.append("line %d: %r listed again while a lot is open"
                              % (ev.lineno, ev.item))
                continue
            lot = Lot(ev.item, ev.category, ev.paid, ev.d)
            lot.prices.append((ev.d, ev.amount))
            open_by_item[ev.item] = lot
            lots.append(lot)
            continue
        lot = open_by_item.get(ev.item)
        if lot is None:
            errors.append("line %d: %r event %r before any list"
                          % (ev.lineno, ev.item, ev.action))
            continue
        if ev.action == "price":
            lot.prices.append((ev.d, ev.amount))
        elif ev.action == "ask":
            lot.asks.append((ev.d, ev.amount))
        else:  # sold / gave / trash / pull
            if ev.action == "sold":
                lot.closed = (ev.d, ev.action, ev.amount)
            else:
                lot.closed = (ev.d, ev.action, None)
            del open_by_item[ev.item]

    if errors:
        raise Broken("%d structural error(s):\n  %s"
                     % (len(errors), "\n  ".join(errors)))

    return Ledger(lots=lots, open_lots=list(open_by_item.values()),
                  as_of=as_of, ignored_events=len(pending), errors=[])


# ---------------------------------------------------------------- 先验与统计

@dataclass
class CatStats:
    name: str
    sold_amount: float = 0.0
    paid_amount: float = 0.0
    n_sold: int = 0
    durations: List[int] = field(default_factory=list)

    def realized(self) -> Optional[float]:
        if self.n_sold == 0:
            return None
        return self.sold_amount / self.paid_amount


def category_stats(ledger: Ledger) -> Dict[str, CatStats]:
    stats: Dict[str, CatStats] = {}
    for lot in ledger.lots:
        st = stats.setdefault(lot.category, CatStats(lot.category))
        if lot.closed and lot.closed[1] == "sold":
            st.n_sold += 1
            st.sold_amount += lot.closed[2]
            st.paid_amount += lot.paid
            st.durations.append((lot.closed[0] - lot.listed).days)
    return stats


def baseline_ratio(cat: str, stats: Dict[str, CatStats],
                   table: Dict[str, Tuple[int, int, float]]) -> Tuple[float, bool]:
    """该品类的参照回血率：自己的成交 >= 3 笔用实证，否则用先验垫底。"""
    st = stats.get(cat)
    if st and st.n_sold >= MIN_LOTS:
        return st.realized(), False
    return table[cat][2], True


def light_for(lot: Lot, as_of: date,
              table: Dict[str, Tuple[int, int, float]]) -> Tuple[str, str]:
    """在架挂单的四灯状态机。返回 (灯, 判词)。"""
    dead_days = table[lot.category][1]
    age = lot.age(as_of)
    if lot.max_offer is not None and lot.max_offer >= OFFER_LINE_RATIO * lot.current_price:
        return ("RED", "offer line: wallet is knocking (%s >= 80%% of ask)"
                % yuan(lot.max_offer))
    if lot.n_asks == 0:
        if age >= dead_days:
            return ("DEAD", "white-gift line crossed: zero asks in %dd, verdict ~ 0"
                    % age)
        if age >= YELLOW_FRACTION * dead_days:
            return ("YELLOW", "cooling: %dd silent, white-gift line at %dd"
                    % (age, dead_days))
        return ("GREEN", "market still looking (%dd / %dd line)" % (age, dead_days))
    if age >= dead_days:
        return ("RED", "fantasy price: real ask %s parked %dd past line"
                % (yuan(lot.max_offer), age))
    return ("YELLOW", "interest exists but price not aligned (top offer %s)"
            % yuan(lot.max_offer))


def yuan(value: float) -> str:
    return "\u00a5" + format(round(value), ",")


def pct(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "-"
    return "%.*f%%" % (digits, 100.0 * value)


def fmt_date(d: date) -> str:
    return d.isoformat()


def percentile(sorted_values: List[int], q: float) -> Optional[int]:
    if not sorted_values:
        return None
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return int(round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac))


# ---------------------------------------------------------------- 命令

def load_category_overrides(values: Optional[List[str]]) -> Dict[str, Tuple[int, int, float]]:
    out: Dict[str, Tuple[int, int, float]] = {}
    for raw in values or []:
        parts = raw.split(":")
        if len(parts) != 4:
            raise SystemExit("bad --cat %r, want name:sell_days:dead_days:prior_ratio" % raw)
        try:
            out[parts[0].strip().lower()] = (int(parts[1]), int(parts[2]), float(parts[3]))
        except ValueError:
            raise SystemExit("bad --cat %r, want name:sell_days:dead_days:prior_ratio" % raw)
    return out


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("ledger", help="events.tsv path")
    common.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                        help="cut-off date (default: ledger's latest event date)")
    common.add_argument("--cat", action="append", default=[], metavar="NAME:SELL:DEAD:RATIO",
                        help="add/override a category prior")

    ap = argparse.ArgumentParser(prog="recoup", description="recoup · cash-out ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("report", "stale", "elastic", "simulate", "categories", "validate"):
        sub.add_parser(name, parents=[common])
    v = sub.add_parser("verdict", parents=[common])
    v.add_argument("item", help="item name to judge")
    return ap


def decline(msg: str) -> int:
    print("DECLINE — %s" % msg)
    return EXIT_DECLINE


def redline(msg: str) -> int:
    print("REDLINE — %s" % msg)
    return EXIT_REDLINE


def span_days(ledger: Ledger) -> int:
    first = min(lot.listed for lot in ledger.lots)
    return (ledger.as_of - first).days


def cmd_report(ledger: Ledger, table) -> int:
    lots, opens = ledger.lots, ledger.open_lots
    print("== RECOUP · cash-out ledger ==")
    print("as-of %s (ledger end)   %d lots (%d open)   span %dd"
          % (fmt_date(ledger.as_of), len(lots), len(opens), span_days(ledger)))
    if ledger.ignored_events:
        print("note: %d event(s) after as-of ignored" % ledger.ignored_events)
    print()

    if len(lots) < MIN_LOTS:
        return decline("only %d listing cycle(s), need >= %d for verdict metrics"
                       % (len(lots), MIN_LOTS))
    if span_days(ledger) < MIN_SPAN_DAYS:
        return decline("ledger span %dd < %dd: lines not yet meaningful"
                       % (span_days(ledger), MIN_SPAN_DAYS))

    closed = [lot for lot in lots if lot.closed]
    sold_lots = [lot for lot in closed if lot.closed[1] == "sold"]
    tally = {}
    for lot in closed:
        tally[lot.closed[1]] = tally.get(lot.closed[1], 0) + 1
    cash_in = sum(lot.closed[2] for lot in sold_lots)
    paid_sold = sum(lot.paid for lot in sold_lots)
    realized = (cash_in / paid_sold) if paid_sold else None

    print("REALIZED")
    print("  sold %d lots   cash-in %s   paid-in %s   realized ratio %s"
          % (len(sold_lots), yuan(cash_in), yuan(paid_sold), pct(realized)))
    print("  closed otherwise: " + ("  ".join("%s %d" % kv for kv in sorted(tally.items())
                                            if kv[0] != "sold") or "none"))
    print()

    asked_lots = [lot for lot in lots if lot.n_asks > 0]
    print("FUNNEL")
    print("  listed %d -> asked %d (%s) -> sold %d (%s of listed, %s of asked)"
          % (len(lots), len(asked_lots), pct(len(asked_lots) / len(lots)),
             len(sold_lots), pct(len(sold_lots) / len(lots)),
             pct(len(sold_lots) / len(asked_lots)) if asked_lots else "-"))
    print()

    lights = {}
    for lot in opens:
        light, _ = light_for(lot, ledger.as_of, table)
        lights[light] = lights.get(light, 0) + 1
    print("OPEN POSITIONS (%d)" % len(opens))
    for light in ("DEAD", "RED", "YELLOW", "GREEN"):
        if light in lights:
            print("  %-7s %d" % (light, lights[light]))
    print()

    red = EXIT_OK
    focus = [lot for lot in opens if lot.n_asks == 0
             and lot.age(ledger.as_of) >= WHITE_GIFT_MULT * table[lot.category][1]]
    if opens:
        implied = statistics.median([lot.implied_ratio() for lot in opens])
        stats = category_stats(ledger)
        bases = [baseline_ratio(lot.category, stats, table)[0] for lot in opens]
        base_med = statistics.median(bases)
        gap = implied - base_med
        print("ANCHOR GAP (open lots)")
        print("  implied ratio median (ask/paid)   %s" % pct(implied))
        print("  category baseline median           %s" % pct(base_med))
        print("  anchor gap                         %+.1fpp   [%s]"
              % (100.0 * gap, "ALARM" if gap > ANCHOR_GAP_LINE else "ok"))
        if gap > ANCHOR_GAP_LINE:
            red = EXIT_REDLINE

    if focus:
        print()
        print("REDLINE — %d lot(s) >= %gx white-gift line with zero asks: "
              "hoarding alarm — give away, reclaim the space"
              % (len(focus), WHITE_GIFT_MULT))
        return EXIT_REDLINE
    if red:
        print()
        print("REDLINE — anchor gap %.1fpp > %.0fpp: the shelf is priced on "
              "memories, not on your own realized band"
              % (100.0 * gap, 100.0 * ANCHOR_GAP_LINE))
        return EXIT_REDLINE
    return EXIT_OK


def cmd_stale(ledger: Ledger, table) -> int:
    opens = sorted(ledger.open_lots, key=lambda lot: lot.age(ledger.as_of), reverse=True)
    print("== RECOUP · open positions (stale check) ==")
    print("as-of %s   %d open   span %dd"
          % (fmt_date(ledger.as_of), len(opens), span_days(ledger)))
    if ledger.ignored_events:
        print("note: %d event(s) after as-of ignored" % ledger.ignored_events)
    print()
    if not opens:
        print("nothing on the shelf.")
        return EXIT_OK
    if span_days(ledger) < MIN_SPAN_DAYS:
        return decline("ledger span %dd < %dd: lights not yet meaningful"
                       % (span_days(ledger), MIN_SPAN_DAYS))

    print("%-12s %-12s %5s %4s %8s %8s %6s  %s"
          % ("item", "category", "age", "ask", "price", "max/off", "ratio", "light"))
    worst = None
    for lot in opens:
        light, why = light_for(lot, ledger.as_of, table)
        dead_days = table[lot.category][1]
        age = lot.age(ledger.as_of)
        if lot.n_asks == 0 and age >= WHITE_GIFT_MULT * dead_days:
            worst = worst or lot
        print("%-12s %-12s %4dd %4d %8s %8s %6s  %s"
              % (lot.item[:12], lot.category[:12], age, lot.n_asks,
                 yuan(lot.current_price),
                 yuan(lot.max_offer) if lot.max_offer is not None else "-",
                 pct(lot.implied_ratio(), 0), light))
    print()
    for lot in opens:
        light, why = light_for(lot, ledger.as_of, table)
        print("  %-12s %s — %s" % (lot.item[:12], light, why))
    if worst:
        print()
        return redline("%r is %dd silent on a %dd white-gift line (>= %gx): "
                       "hoarding alarm — give away, reclaim the space"
                       % (worst.item, worst.age(ledger.as_of),
                          table[worst.category][1], WHITE_GIFT_MULT))
    return EXIT_OK


def cmd_elastic(ledger: Ledger, table) -> int:
    print("== RECOUP · price elasticity of reductions ==")
    print("as-of %s   window %dd" % (fmt_date(ledger.as_of), ELASTIC_WINDOW))
    print()
    rows = []
    for lot in ledger.lots:
        prices = lot.prices
        for i in range(1, len(prices)):
            d1, p0 = prices[i - 1][0], prices[i - 1][1]
            d1, p1 = prices[i]
            if p1 >= p0:
                continue
            pre_start = max(lot.listed, d1 - timedelta(days=ELASTIC_WINDOW))
            pre_days = (d1 - pre_start).days
            post_end = min(d1 + timedelta(days=ELASTIC_WINDOW),
                           ledger.as_of + timedelta(days=1))
            post_days = (post_end - d1).days
            if pre_days <= 0 or post_days <= 0:
                continue
            pre_asks = sum(1 for ad, _ in lot.asks if pre_start <= ad < d1)
            post_asks = sum(1 for ad, _ in lot.asks if d1 <= ad < post_end)
            rows.append((lot.item, d1, (p0 - p1) / p0, pre_asks, pre_days,
                         post_asks, post_days))
    if len(rows) < MIN_REDUCTIONS:
        return decline("only %d observable reduction(s), need >= %d to judge "
                       "elasticity" % (len(rows), MIN_REDUCTIONS))

    print("%-12s %-11s %6s  %s" % ("item", "date", "cut", "asks/day before -> after"))
    pre_rates, post_rates = [], []
    for item, d1, cut, pre, pre_days, post, post_days in rows:
        pre_rate, post_rate = pre / pre_days, post / post_days
        pre_rates.append(pre_rate)
        post_rates.append(post_rate)
        print("%-12s %-11s %5.1f%%  %.3f -> %.3f  (%d->%d asks)"
              % (item[:12], fmt_date(d1), 100.0 * cut, pre_rate, post_rate,
                 pre, post))
    mean_pre = statistics.mean(pre_rates)
    mean_post = statistics.mean(post_rates)
    print()
    print("  mean ask rate  %.3f -> %.3f per day" % (mean_pre, mean_post))
    if mean_pre > 0:
        ratio = mean_post / mean_pre
        print("  response ratio  %.2fx" % ratio)
    else:
        ratio = float("inf") if mean_post > 0 else 0.0
        print("  response ratio  %s (no baseline asks)"
              % ("inf" if ratio == float("inf") else "0.00"))
    if mean_post == 0:
        verdict = "NO-RESPONSE — cutting does not summon asks; the market is not looking. Re-list, re-word, or head for the white-gift line."
    elif ratio >= 2.0:
        verdict = "RESPONSIVE — the market is watching, the price was wrong. Keep cutting toward the realized band."
    else:
        verdict = "WEAK — some response, not enough to believe in the tag."
    print("  verdict: %s" % verdict)
    return EXIT_OK


def cmd_verdict(ledger: Ledger, table, item: str) -> int:
    match = [lot for lot in ledger.lots if lot.item.lower() == item.lower()]
    if not match:
        known = sorted({lot.item for lot in ledger.lots})
        return decline("unknown item %r (ledger has: %s)"
                       % (item, ", ".join(known)))
    lot = match[-1]
    print("== RECOUP · verdict: %s ==" % lot.item)
    if ledger.ignored_events:
        print("note: %d event(s) after as-of ignored" % ledger.ignored_events)
    print()
    if lot.closed:
        action, amount = lot.closed[1], lot.closed[2]
        if action == "sold":
            print("closed SOLD %s on %s  (paid %s, recovered %s, ratio %s)"
                  % (yuan(amount), fmt_date(lot.closed[0]), yuan(lot.paid),
                     yuan(amount), pct(amount / lot.paid)))
        else:
            print("closed %s on %s  (paid %s stays sunk — recorded, not recovered)"
                  % (action.upper(), fmt_date(lot.closed[0]), yuan(lot.paid)))
        return EXIT_OK
    if len(ledger.lots) < MIN_LOTS:
        return decline("only %d listing cycle(s): verdicts not yet meaningful"
                       % len(ledger.lots))

    dead_days = table[lot.category][1]
    age = lot.age(ledger.as_of)
    light, why = light_for(lot, ledger.as_of, table)
    base, prior = baseline_ratio(lot.category, category_stats(ledger), table)
    progress = min(999, int(100.0 * age / dead_days))
    print("  listed %s   age %dd / white-gift line %dd (%d%%)"
          % (fmt_date(lot.listed), age, dead_days, progress))
    print("  paid %s   ask %s   implied ratio %s   baseline %s%s"
          % (yuan(lot.paid), yuan(lot.current_price), pct(lot.implied_ratio()),
             pct(base), " (prior: own sales < 3)" if prior else ""))
    print("  asks %d   top offer %s   reductions %d"
          % (lot.n_asks, yuan(lot.max_offer) if lot.max_offer is not None else "-",
             len(lot.reductions)))
    print()
    print("  %s — %s" % (light, why))
    if light == "RED" and lot.max_offer is not None \
            and lot.max_offer >= OFFER_LINE_RATIO * lot.current_price:
        print("  action: accept around %s, or reprice below it. An offer at the "
              "line is the market paying you respect — meet it."
              % yuan(lot.max_offer))
        return EXIT_REDLINE
    if light == "DEAD":
        print("  action: give away / donate and reclaim the space. Keeping it "
              "listed is negative carry — the shelf bills you daily, the tag pays nothing.")
        if age >= WHITE_GIFT_MULT * dead_days:
            return EXIT_REDLINE
        return EXIT_OK
    if light == "RED":
        print("  action: cut the tag to the realized band (%s). Hope is not a "
              "pricing strategy." % pct(base))
        return EXIT_OK
    if light == "YELLOW":
        print("  action: reprice into the realized band before the line at %dd."
              % dead_days)
        return EXIT_OK
    print("  action: hold. Watch for the cooling mark at %dd." %
          int(YELLOW_FRACTION * dead_days))
    return EXIT_OK


def cmd_simulate(ledger: Ledger, table) -> int:
    opens = ledger.open_lots
    print("== RECOUP · simulate: open-book recovery window ==")
    print("as-of %s   %d open lots" % (fmt_date(ledger.as_of), len(opens)))
    if ledger.ignored_events:
        print("note: %d event(s) after as-of ignored" % ledger.ignored_events)
    print()
    if not opens:
        print("nothing on the shelf — no fantasy exposure.")
        return EXIT_OK
    if len(ledger.lots) < MIN_LOTS:
        return decline("only %d listing cycle(s): recovery window not yet meaningful"
                       % len(ledger.lots))
    if span_days(ledger) < MIN_SPAN_DAYS:
        return decline("ledger span %dd < %dd: recovery window not yet meaningful"
                       % (span_days(ledger), MIN_SPAN_DAYS))

    stats = category_stats(ledger)
    upper = 0.0
    lower = 0.0
    dead_paid = 0.0
    for lot in opens:
        base, _ = baseline_ratio(lot.category, stats, table)
        upper += lot.paid * base
        light, _ = light_for(lot, ledger.as_of, table)
        if light == "DEAD":
            dead_paid += lot.paid
        else:
            lower += lot.paid * base
    paid_total = sum(lot.paid for lot in opens)
    carried = sum(lot.age(ledger.as_of) for lot in opens)
    print("  paid-in on open lots   %s" % yuan(paid_total))
    print("  upper bound            %s  (everything recovers at category baseline)"
          % yuan(upper))
    print("  lower bound            %s  (DEAD lots = 0, the rest recovers)"
          % yuan(lower))
    print("  fantasy exposure       %s  — money you are still dreaming about"
          % yuan(upper - lower))
    print("  carried                %d lot-days on the shelf since listing" % carried)
    return EXIT_OK


def cmd_categories(ledger: Ledger, table) -> int:
    print("== RECOUP · category calibration ==")
    print("as-of %s   baseline rule: your own sales >= %d, else prior"
          % (fmt_date(ledger.as_of), MIN_LOTS))
    print()
    if len(ledger.lots) < MIN_LOTS:
        return decline("only %d listing cycle(s): calibration not yet meaningful"
                       % len(ledger.lots))
    stats = category_stats(ledger)
    names = sorted({lot.category for lot in ledger.lots})
    print("%-12s %4s %4s %4s %5s %4s %4s  %9s  %6s %6s  %6s"
          % ("category", "lot", "sold", "gave", "trsh", "pull", "open",
             "realized", "P50d", "P90d", "asked"))
    total_cash = 0.0
    for name in names:
        st = stats.get(name, CatStats(name))
        lots_c = [lot for lot in ledger.lots if lot.category == name]
        tally = {"sold": 0, "gave": 0, "trash": 0, "pull": 0}
        for lot in lots_c:
            if lot.closed:
                tally[lot.closed[1]] += 1
        opens_c = sum(1 for lot in lots_c if not lot.closed)
        asked = sum(1 for lot in lots_c if lot.n_asks > 0)
        durations = sorted(st.durations)
        ratio, prior = baseline_ratio(name, stats, table)
        own = st.realized()
        cash = st.sold_amount
        total_cash += cash
        ratio_cell = pct(ratio, 1) + ("*" if prior else "")
        print("%-12s %4d %4d %4d %5d %4d %4d  %9s  %6s %6s  %3d/%d"
              % (name, len(lots_c), tally["sold"], tally["gave"], tally["trash"],
                 tally["pull"], opens_c, ratio_cell,
                 str(percentile(durations, 0.5) or "-"),
                 str(percentile(durations, 0.9) or "-"),
                 asked, len(lots_c)))
        if prior and own is not None:
            print("%-12s   own sales: %s recovered / %s paid = %s (n=%d, below prior gate)"
                  % ("", yuan(st.sold_amount), yuan(st.paid_amount), pct(own), st.n_sold))
    print()
    print("  * prior fallback (own sales < %d) — the ledger, not the table, is the manual." % MIN_LOTS)
    print("  cash-in check: %s across categories" % yuan(total_cash))
    return EXIT_OK


def cmd_validate(ledger: Ledger, table) -> int:
    print("== RECOUP · validate ==")
    print("account clean: %d lots, %d open, span %dd, as-of %s"
          % (len(ledger.lots), len(ledger.open_lots), span_days(ledger),
             fmt_date(ledger.as_of)))
    if ledger.ignored_events:
        print("note: %d event(s) after as-of ignored (future-dated)" % ledger.ignored_events)
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        as_of = (datetime.strptime(args.as_of, "%Y-%m-%d").date()
                 if args.as_of else None)
        table = dict(CATEGORY_PRIOR)
        table.update(load_category_overrides(args.cat))
        ledger = load_ledger(args.ledger, as_of, table)
    except Broken as exc:
        print("BROKEN — %s" % exc)
        return EXIT_BROKEN

    if args.cmd == "report":
        return cmd_report(ledger, table)
    if args.cmd == "stale":
        return cmd_stale(ledger, table)
    if args.cmd == "elastic":
        return cmd_elastic(ledger, table)
    if args.cmd == "verdict":
        return cmd_verdict(ledger, table, args.item)
    if args.cmd == "simulate":
        return cmd_simulate(ledger, table)
    if args.cmd == "categories":
        return cmd_categories(ledger, table)
    if args.cmd == "validate":
        return cmd_validate(ledger, table)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
