#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smooth-sailing · 旱涝保收 —— 不规律收入的现金流平滑引擎.

问题：自由职业者的进账按项目来，生活却按月来——两个节奏差就是过山车
本身。四万的项目款到账那个月，生活方式悄悄升级；连续三个月没单，信用
卡开始流转；年底税务局一次性收走没预留的税；「这个月敢花多少」全凭焦
虑投票。记账 App 只回答「花了多少」，从不回答「敢花多少」——因为它们
按月孤立记账，从不把「钱的节奏」和「生活的节奏」放在同一本账上对时。

smooth-sailing 从一本手编的月度现金流账（TSV：月份/进账/支出/月底现
金/实缴税）确定性算出六本账：

  * report    全账本体检：进账分布 P10/P50/P90、波动率 CV、丰饥比、
              烧钱率（trailing median，尖峰月不代表性）、跑道
              runway = 现金 ÷ 烧钱率（3 个月死亡线 exit 4）、现金
              对账恒等式逐月核差
  * paycheck  月俸引擎：下月该给自己发的虚拟工资——自动基线 =
              trailing 收入中位 × 提取率，再过三重 clamp（基线 →
              现金可支撑 → 死水位），发不足时如实说明被谁卡住
  * simulate  反事实重放：如果过去 N 个月一直用月俸法，消费波动会从
              多少降到多少、最惨月的生活水平被垫高多少、丰水罐最低
              见过底没有——平滑的代价与收益，一次演完
  * tax       税罐：每笔进账先按预提率划一角进罐。应提 − 已缴 = 罐
              欠账，名义现金 − 罐欠 = 真实可支配——你以为有的钱里，
              有一部分从来就是税务局的
  * stress    压力测试：断粮情景（未来进账 = 0）与腰斩情景（进账只
              剩一半）各能撑几个月，哪个月现金见底
  * validate  账本体检：格式、月份连续性（断月披露不插补）、现金
              恒等式逐月对账——账对不上，先修账再谈结论

立场：收入的旱涝是天意，生活的旱涝是机制。工具不发钱、不理财，
它只造一台「虚拟发薪机」——把按项目到账的现金折成按月发放的月俸，
丰月自动蓄水，饥月自动放水。账本只拒绝让生活跟着进账坐过山车，
发多少俸、接不接低价单仍是人的决定。
"""

from __future__ import annotations

import argparse
import math
import sys
from statistics import mean, median, pstdev

VERSION = "1.0.0"

WINDOW = 6            # trailing months for burn rate / auto baseline
PAY_RATE = 0.90       # auto baseline = median(trailing income) * PAY_RATE
TAX_RATE = 0.10       # default set-aside rate per yuan of income
FLOAT_MONTHS = 1.0    # dead-water floor = FLOAT_MONTHS * burn
RED_RUNWAY = 3.0      # runway red line, in months
MIN_WAVE = 6          # months required before a volatility verdict
MIN_BASE = 3          # months required before an auto baseline
CLIFF = 0.30          # tax debt above this share of cash => cliff lamp
RECON_TOL = 0.01      # per-month cash identity tolerance (yuan)
RECON_SHARE = 0.02    # cumulative drift above this share of income => exit 2
STRESS_HORIZON = 12   # months to project in stress scenarios

EXIT_OK = 0
EXIT_DATA = 2
EXIT_THIN = 3
EXIT_RED = 4

USAGE = """usage: smooth_sailing.py <command> ledger.tsv [options]

commands:
  report   <ledger.tsv> [--window N] [--red-runway MONTHS]   full audit: income spread, CV, burn, runway, cash reconciliation
  paycheck <ledger.tsv> [--salary X] [--rate R] [--float M] [--month YYYY-MM]
                                                             next month's self-paid salary (three-clamp engine)
  simulate <ledger.tsv> [--salary X] [--tax-rate R] [--start-cash X]
                                                             replay history under a fixed salary: CV before/after
  tax      <ledger.tsv> [--rate R] [--cliff S]               tax jar: owed, real disposable cash, cliff lamp
  stress   <ledger.tsv> [--red-runway MONTHS] [--horizon N]  dry (zero income) & half-income survival months
  validate <ledger.tsv>                                      ledger checkup: gaps, ordering, cash identity

ledger.tsv: TSV with header `month<TAB>income<TAB>spend<TAB>cash<TAB>tax_paid`,
            one row per month, ascending, `#` lines are comments; tax_paid defaults to 0.

exit codes: 0 ok · 2 bad data / reconciliation broken · 3 evidence too thin
            4 red line (runway / tax cliff)
"""


class LedgerError(Exception):
    """Bad ledger: unparseable rows, bad months, broken ordering."""


class ThinLedger(Exception):
    """Not enough evidence to publish the requested verdict."""


# ---------------------------------------------------------------- parsing

MONTH_COLS = ("month", "income", "spend", "cash")


class Row(object):
    __slots__ = ("month", "income", "spend", "cash", "tax_paid")

    def __init__(self, month, income, spend, cash, tax_paid):
        self.month = month
        self.income = income
        self.spend = spend
        self.cash = cash
        self.tax_paid = tax_paid


def parse_month(text):
    parts = text.split("-")
    if len(parts) != 2:
        raise LedgerError("month %r is not YYYY-MM" % text)
    try:
        y, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise LedgerError("month %r is not YYYY-MM" % text)
    if not (1 <= m <= 12) or y < 1900:
        raise LedgerError("month %r out of range" % text)
    return y, m


def month_index(text):
    y, m = parse_month(text)
    return y * 12 + (m - 1)


def month_label(idx):
    return "%04d-%02d" % (idx // 12, idx % 12 + 1)


def parse_float(text, field, minimum=None):
    try:
        value = float(text)
    except ValueError:
        raise LedgerError("%s %r is not a number" % (field, text))
    if math.isnan(value) or math.isinf(value):
        raise LedgerError("%s %r is not finite" % (field, text))
    if minimum is not None and value < minimum:
        raise LedgerError("%s %r below minimum %s" % (field, text, minimum))
    return value


def read_ledger(path):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cols = line.split("\t")
            if cols and cols[0].strip() == "month":
                missing = [c for c in MONTH_COLS if c not in [c.strip() for c in cols]]
                if missing:
                    raise LedgerError("header missing columns: %s" % ", ".join(missing))
                continue
            if len(cols) < 4:
                raise LedgerError("line %d: expected >=4 columns, got %d" % (lineno, len(cols)))
            idx = month_index(cols[0].strip())
            rows.append(Row(
                month_label(idx),
                parse_float(cols[1], "income", minimum=0.0),
                parse_float(cols[2], "spend", minimum=0.0),
                parse_float(cols[3], "cash"),
                parse_float(cols[4], "tax_paid", minimum=0.0) if len(cols) > 4 and cols[4].strip() else 0.0,
            ))
    if not rows:
        raise LedgerError("no data rows in %s" % path)
    seen = set()
    prev = None
    for row in rows:
        idx = month_index(row.month)
        if idx in seen:
            raise LedgerError("duplicate month %s" % row.month)
        if prev is not None and idx <= prev:
            raise LedgerError("month %s breaks ascending order" % row.month)
        seen.add(idx)
        prev = idx
    return rows


# ------------------------------------------------------------- statistics

def pctl(sorted_values, q):
    if not sorted_values:
        raise ThinLedger("no values for a percentile")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def cv(values):
    avg = mean(values)
    if avg == 0:
        return 0.0
    return pstdev(values) / avg


def trailing(rows, field, window):
    chunk = rows[-window:] if window and window < len(rows) else rows
    return [getattr(r, field) for r in chunk]


def burn_rate(rows, window):
    """Burn = trailing median spend: a spike month must not set the dial."""
    return median(trailing(rows, "spend", window))


def vol_grade(coef):
    if coef < 0.25:
        return "STEADY"
    if coef < 0.50:
        return "CHOPPY"
    return "WILD"


def money(value):
    if value >= 0:
        return "%s" % format(round(value, 2), ",.2f")
    return "-%s" % format(round(-value, 2), ",.2f")


def pct(value):
    return "%.1f%%" % (value * 100.0)


def recon_drifts(rows):
    """cash[t] = cash[t-1] + income[t] - spend[t], adjacent months only.

    A gap in month continuity means months are missing from the book —
    the identity cannot hold across a hole, so those seams are skipped
    and disclosed, never treated as corruption.
    Returns (drifts, skipped_seams).
    """
    drifts = []
    skipped = 0
    for i in range(1, len(rows)):
        if month_index(rows[i].month) != month_index(rows[i - 1].month) + 1:
            skipped += 1
            continue
        expect = rows[i - 1].cash + rows[i].income - rows[i].spend
        drifts.append((rows[i].month, rows[i].cash - expect))
    return drifts, skipped


def implied_start_cash(rows):
    first = rows[0]
    return first.cash - (first.income - first.spend)


def runway_months(rows, window):
    burn = burn_rate(rows, window)
    if burn <= 0:
        return float("inf"), burn
    return rows[-1].cash / burn, burn


# --------------------------------------------------------------- commands

def cmd_report(args):
    rows = read_ledger(args.ledger)
    incomes = [r.income for r in rows]
    spends = [r.spend for r in rows]
    n = len(rows)

    srt = sorted(incomes)
    p10, p50, p90 = pctl(srt, 0.10), pctl(srt, 0.50), pctl(srt, 0.90)
    avg = mean(incomes)
    coef = cv(incomes)
    famine = sum(1 for v in incomes if v < p50)
    runway, burn = runway_months(rows, args.window)

    print("smooth-sailing report · %d months · %s ~ %s" % (n, rows[0].month, rows[-1].month))
    print("")
    print("income  mean %s · P10 %s · P50 %s · P90 %s · P90/P50 %.2fx" % (
        money(avg), money(p10), money(p50), money(p90), (p90 / p50) if p50 else float("inf")))
    print("        best %s (%s) · worst %s (%s) · famine months (income<P50) %d/%d" % (
        money(max(incomes)), max(rows, key=lambda r: r.income).month,
        money(min(incomes)), min(rows, key=lambda r: r.income).month,
        famine, n))
    print("        CV %.1f%% -> %s" % (coef * 100.0, vol_grade(coef)))
    print("")
    print("burn    trailing %d-month median spend = %s/mo (mean spend %s)" % (
        args.window, money(burn), money(mean(spends))))
    print("cash    %s at %s (implied start %s, net %s over %d months)" % (
        money(rows[-1].cash), rows[-1].month, money(implied_start_cash(rows)),
        money(rows[-1].cash - implied_start_cash(rows)), n))
    if math.isinf(runway):
        print("runway  burn is zero: runway unlimited (go see a doctor, not a budget)")
    else:
        lamp = "RED" if runway < args.red_runway else "OK"
        print("runway  %s / %s = %.1f months  [%s] (red line %.1f)" % (
            money(rows[-1].cash), money(burn), runway, lamp, args.red_runway))

    drifts, seams = recon_drifts(rows)
    total_drift = sum(abs(d) for _, d in drifts)
    total_income = sum(incomes)
    worst = max(drifts, key=lambda t: abs(t[1])) if drifts else None
    seam_note = " (%d seam(s) across gaps skipped)" % seams if seams else ""
    print("recon   %d months checked%s, cumulative |drift| %s (%.2f%% of income)" % (
        len(drifts), seam_note, money(total_drift), total_drift / total_income * 100.0 if total_income else 0.0))
    if worst and abs(worst[1]) > RECON_TOL:
        print("        worst month %s off by %s" % (worst[0], money(worst[1])))

    if total_income > 0 and total_drift > RECON_SHARE * total_income:
        print("")
        print("VERDICT: ledger does not reconcile (%s > %s of income). Fix the book first."
              % (money(total_drift), pct(RECON_SHARE)))
        return EXIT_DATA
    if n < MIN_WAVE:
        print("")
        print("VERDICT: %d months is too thin for a volatility verdict (need %d). Keep recording."
              % (n, MIN_WAVE))
        return EXIT_THIN
    print("")
    verdict = ("life is riding the income roller coaster 1:1" if coef >= 0.50
               else "income wobbles but life can hold a line" if coef >= 0.25
               else "income is effectively salaried already")
    print("VERDICT: %s | runway %s" % (
        verdict,
        ("BELOW %s-month death line" % ("%g" % args.red_runway)) if runway < args.red_runway
        else "%.1f months, above the line" % runway))
    return EXIT_RED if runway < args.red_runway else EXIT_OK


def resolve_salary(rows, args):
    """Return (salary, source): explicit --salary or auto baseline."""
    if args.salary is not None:
        if args.salary < 0:
            raise LedgerError("--salary must be >= 0")
        return args.salary, "explicit"
    if len(rows) < MIN_BASE:
        return None, "thin"
    base = median(trailing(rows, "income", args.window)) * args.rate
    return base, "auto median(trailing %d income) x %.2f" % (args.window, args.rate)


def next_month_label(rows):
    return month_label(month_index(rows[-1].month) + 1)


def cmd_paycheck(args):
    rows = read_ledger(args.ledger)
    salary, source = resolve_salary(rows, args)
    if salary is None:
        print("paycheck: only %d months on record; an auto baseline needs %d." % (len(rows), MIN_BASE))
        print("Pass --salary to pay yourself by hand, or keep recording.")
        return EXIT_THIN
    burn = burn_rate(rows, args.window)
    floor = args.float * burn
    headroom = rows[-1].cash - floor
    target = month = args.month or next_month_label(rows)
    paid = min(salary, headroom)
    print("smooth-sailing paycheck · %s" % target)
    print("")
    print("baseline  %s (%s)" % (money(salary), source))
    print("cash      %s at %s · dead-water floor %s (= %.1f x burn %s)" % (
        money(rows[-1].cash), rows[-1].month, money(floor), args.float, money(burn)))
    print("headroom  %s" % money(headroom))
    print("")
    if headroom <= 0:
        print("PAY: 0.00  [FLOODED] cash is already at/below the dead-water floor.")
        print("A salary is a withdrawal, not a wish: refill the reservoir first.")
        return EXIT_RED
    if paid < salary - RECON_TOL:
        print("PAY: %s  [CLAMPED by cash] baseline %s, but the floor takes priority." % (
            money(paid), money(salary)))
        print("Paying the full %s would drop the reservoir %s below the floor." % (
            money(salary), money(salary - paid)))
        return EXIT_RED
    print("PAY: %s  [OK] no clamp hit; the reservoir can carry it." % money(paid))
    return EXIT_OK


def simulate(rows, salary, tax_rate, start_cash, window, float_months):
    """Replay history under a fixed monthly salary. Returns a dict."""
    burn = burn_rate(rows, window)
    floor = float_months * burn
    pool = start_cash
    jar = 0.0
    sim_spend = []
    breaches = 0
    min_pool = pool
    for row in rows:
        pool += row.income
        jar += row.income * tax_rate
        pool -= row.income * tax_rate
        paid = min(salary, max(0.0, pool - floor))
        if paid < salary - RECON_TOL:
            breaches += 1
        pool -= paid
        sim_spend.append(paid)
        min_pool = min(min_pool, pool)
    identity = (start_cash + sum(r.income for r in rows)
                - (sum(sim_spend) + jar + pool))
    return {
        "sim_spend": sim_spend,
        "breaches": breaches,
        "min_pool": min_pool,
        "pool": pool,
        "jar": jar,
        "identity": identity,
        "floor": floor,
    }


def cmd_simulate(args):
    rows = read_ledger(args.ledger)
    if len(rows) < MIN_BASE:
        print("simulate: %d months is too thin to replay (need %d)." % (len(rows), MIN_BASE))
        return EXIT_THIN
    salary, source = resolve_salary(rows, args)
    if salary is None:
        print("simulate: too few months for an auto baseline; pass --salary.")
        return EXIT_THIN
    start = implied_start_cash(rows) if args.start_cash is None else args.start_cash
    if start < 0:
        print("note: implied start cash is %s; clamped to 0." % money(start))
        start = 0.0
    sim = simulate(rows, salary, args.tax_rate, start, args.window, FLOAT_MONTHS)

    actual = [r.spend for r in rows]
    srt = sorted(r.income for r in rows)
    p50 = pctl(srt, 0.50)
    cv_before = cv(actual)
    cv_after = cv(sim["sim_spend"])
    famine_idx = [i for i, r in enumerate(rows) if r.income < salary]
    famine_actual = median([actual[i] for i in famine_idx]) if famine_idx else None
    famine_sim = median([sim["sim_spend"][i] for i in famine_idx]) if famine_idx else None
    famine_paygo = median([rows[i].income for i in famine_idx]) if famine_idx else None

    print("smooth-sailing simulate · %d months replayed at salary %s (%s)" % (
        len(rows), money(salary), source))
    print("")
    print("consumption CV   before %.1f%% -> after %.1f%%  (life smoothed by %.1f pp)" % (
        cv_before * 100.0, cv_after * 100.0, (cv_before - cv_after) * 100.0))
    if famine_idx:
        print("famine months    %d/%d months earn below the salary" % (len(famine_idx), len(rows)))
        print("                 pay-as-you-go floor: those months would live on median income %s — salaried %s lifts them %+.1f%%" % (
            money(famine_paygo), money(famine_sim),
            (famine_sim / famine_paygo - 1.0) * 100.0 if famine_paygo else 0.0))
        print("                 your actual spend in those months: median %s — the wallet was already smoothing, by hand" % (
            money(famine_actual)))
    print("reservoir        min balance %s · end %s · tax jar %s" % (
        money(sim["min_pool"]), money(sim["pool"]), money(sim["jar"])))
    print("salary breaches  %d/%d months the engine could not pay in full" % (
        sim["breaches"], len(rows)))
    print("identity         start %s + income %s = paid %s + pool %s + jar %s (residual %.2e)" % (
        money(start), money(sum(r.income for r in rows)),
        money(sum(sim["sim_spend"])), money(sim["pool"]), money(sim["jar"]), sim["identity"]))
    print("")
    if salary <= p50 and sim["breaches"] == 0 and cv_after > cv_before + 1e-9:
        print("VERDICT: smoothing made life MORE volatile -- that is a bug, not an opinion.")
        return EXIT_DATA
    if sim["breaches"] == 0:
        print("VERDICT: this salary is affordable across the whole book; the reservoir never breached the floor.")
    elif sim["breaches"] <= len(rows) // 4:
        print("VERDICT: affordable with scuffs: %d breach month(s); consider a lower salary or a fatter starting cushion."
              % sim["breaches"])
    else:
        print("VERDICT: this salary outruns the income: breached %d/%d months. It is a wish, not a payroll." % (
            sim["breaches"], len(rows)))
        return EXIT_RED
    return EXIT_OK


def cmd_tax(args):
    rows = read_ledger(args.ledger)
    total_income = sum(r.income for r in rows)
    total_paid = sum(r.tax_paid for r in rows)
    due = total_income * args.rate - total_paid
    cash = rows[-1].cash
    real = cash - due
    cliff = due > args.cliff * cash
    print("smooth-sailing tax jar · %.0f%% set-aside · %d months" % (args.rate * 100, len(rows)))
    print("")
    print("set aside   %s (= %.0f%% of income %s)" % (money(total_income * args.rate), args.rate * 100, money(total_income)))
    print("paid        %s across %d month(s) with a payment" % (
        money(total_paid), sum(1 for r in rows if r.tax_paid > 0)))
    print("jar owed    %s" % money(due))
    print("cash        %s -> real disposable %s" % (money(cash), money(real)))
    print("")
    if due < -RECON_TOL:
        print("LAMP: REFUND — the jar is overfunded by %s; that surplus is yours to deploy." % money(-due))
        return EXIT_OK
    if cliff:
        print("LAMP: CLIFF — the jar is owed %s, %.0f%% of your cash (line %.0f%%)." % (
            money(due), due / cash * 100.0, CLIFF * 100.0))
        print("Part of the cash you are spending is the tax bureau's money on loan.")
        return EXIT_RED
    if len(rows) < MIN_BASE:
        print("VERDICT: %d months is thin for a jar verdict (need %d), but the arithmetic above stands." % (
            len(rows), MIN_BASE))
        return EXIT_THIN
    print("LAMP: OK — jar owed %s is %.0f%% of cash, under the %.0f%% cliff line." % (
        money(due), due / cash * 100.0, CLIFF * 100.0))
    return EXIT_OK


def cmd_stress(args):
    rows = read_ledger(args.ledger)
    burn = burn_rate(rows, args.window)
    cash = rows[-1].cash
    avg_income = mean(r.income for r in rows)
    print("smooth-sailing stress · from %s, burn %s/mo (trailing %d median)" % (
        next_month_label(rows), money(burn), args.window))
    print("")
    label = next_month_label(rows)
    # dry: zero income from next month on
    left = cash
    dry_month = None
    for i in range(args.horizon):
        left -= burn
        if left <= 0:
            dry_month = month_label(month_index(label) + i)
            break
    runway_dry = cash / burn if burn > 0 else float("inf")
    if math.isinf(runway_dry):
        print("dry (income = 0)    burn is zero; unlimited runway.")
    else:
        fate = "cash hits zero in %s" % dry_month if dry_month else "survives the whole %d-month horizon" % args.horizon
        lamp = "RED" if runway_dry < args.red_runway else "OK"
        print("dry (income = 0)    runway %.1f months  [%s] — %s" % (runway_dry, lamp, fate))
    # half: income drops to half its historical mean
    half_net = burn - avg_income * 0.5
    if half_net <= 0:
        print("half (income /2)    net cash flow %s/mo — sustainable forever; income still outruns burn." % money(-half_net))
    else:
        runway_half = cash / half_net
        lamp = "RED" if runway_half < args.red_runway else "OK"
        left = cash
        half_month = None
        for i in range(args.horizon):
            left -= half_net
            if left <= 0:
                half_month = month_label(month_index(label) + i)
                break
        fate = "cash hits zero in %s" % half_month if half_month else "survives the whole %d-month horizon" % args.horizon
        print("half (income /2)    net burn %s/mo, runway %.1f months  [%s] — %s" % (
            money(half_net), runway_half, lamp, fate))
    print("")
    print("assumptions: burn frozen at today's trailing median; no new borrowing;")
    print("             no cutting of spend. Real you can do better on all three.")
    if not math.isinf(runway_dry) and runway_dry < args.red_runway:
        print("")
        print("VERDICT: dry runway %.1f months is under the %s-month death line — the reservoir is a puddle." % (
            runway_dry, "%g" % args.red_runway))
        return EXIT_RED
    print("")
    print("VERDICT: dry runway above the %s-month death line." % "%g" % args.red_runway)
    return EXIT_OK


def cmd_validate(args):
    rows = read_ledger(args.ledger)  # raises LedgerError on format problems
    print("smooth-sailing validate · %d months · %s ~ %s" % (len(rows), rows[0].month, rows[-1].month))
    problems = 0
    gaps = []
    for i in range(1, len(rows)):
        if month_index(rows[i].month) != month_index(rows[i - 1].month) + 1:
            gaps.append("%s -> %s" % (rows[i - 1].month, rows[i].month))
    if gaps:
        problems += 1
        print("gap      %d break(s) in month continuity: %s — disclosed, never interpolated." % (
            len(gaps), "; ".join(gaps)))
    else:
        print("months   continuous, ascending, no duplicates")
    drifts, seams = recon_drifts(rows)
    bad = [(m, d) for m, d in drifts if abs(d) > RECON_TOL]
    total_drift = sum(abs(d) for _, d in drifts)
    total_income = sum(r.income for r in rows)
    if gaps:
        print("recon    %d seam(s) across gaps skipped; %d adjacent months checked:" % (seams, len(drifts)))
    else:
        print("recon    %d months checked against the cash identity:" % len(drifts))
    if bad:
        print("           cash identity cash[t]=cash[t-1]+income-spend broken in %d/%d:" % (len(bad), len(drifts)))
        for m, d in bad[:5]:
            print("           %s off by %s" % (m, money(d)))
    else:
        print("           all %d reconcile (tol %s)" % (len(drifts), money(RECON_TOL)))
    if total_income > 0 and total_drift > RECON_SHARE * total_income:
        problems += 1
        print("verdict  BROKEN: cumulative drift %s > %s of income. Fix the book before trusting any verdict." % (
            money(total_drift), pct(RECON_SHARE)))
        return EXIT_DATA
    if problems:
        print("verdict  usable with disclosed gaps.")
        return EXIT_OK
    print("verdict  clean.")
    return EXIT_OK


# ------------------------------------------------------------------ main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="smooth_sailing.py", description="smooth-sailing · pay yourself a steady salary from an unsteady income")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("report", help="full audit: spread, CV, burn, runway, reconciliation")
    p.add_argument("ledger")
    p.add_argument("--window", type=int, default=WINDOW)
    p.add_argument("--red-runway", type=float, default=RED_RUNWAY)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("paycheck", help="next month's self-paid salary")
    p.add_argument("ledger")
    p.add_argument("--salary", type=float, default=None)
    p.add_argument("--rate", type=float, default=PAY_RATE)
    p.add_argument("--float", type=float, default=FLOAT_MONTHS)
    p.add_argument("--window", type=int, default=WINDOW)
    p.add_argument("--month", default=None)
    p.set_defaults(func=cmd_paycheck)

    p = sub.add_parser("simulate", help="replay history under a fixed salary")
    p.add_argument("ledger")
    p.add_argument("--salary", type=float, default=None)
    p.add_argument("--rate", type=float, default=PAY_RATE)
    p.add_argument("--tax-rate", type=float, default=TAX_RATE)
    p.add_argument("--start-cash", type=float, default=None)
    p.add_argument("--window", type=int, default=WINDOW)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("tax", help="tax jar: owed, real disposable, cliff lamp")
    p.add_argument("ledger")
    p.add_argument("--rate", type=float, default=TAX_RATE)
    p.add_argument("--cliff", type=float, default=CLIFF)
    p.set_defaults(func=cmd_tax)

    p = sub.add_parser("stress", help="dry / half-income survival months")
    p.add_argument("ledger")
    p.add_argument("--window", type=int, default=WINDOW)
    p.add_argument("--red-runway", type=float, default=RED_RUNWAY)
    p.add_argument("--horizon", type=int, default=STRESS_HORIZON)
    p.set_defaults(func=cmd_stress)

    p = sub.add_parser("validate", help="ledger checkup: gaps, ordering, cash identity")
    p.add_argument("ledger")
    p.set_defaults(func=cmd_validate)

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write(USAGE)
        return EXIT_DATA
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_DATA
    if not getattr(args, "func", None):
        sys.stderr.write(USAGE)
        return EXIT_DATA
    try:
        return args.func(args)
    except LedgerError as exc:
        sys.stderr.write("data error: %s\n" % exc)
        return EXIT_DATA
    except ThinLedger as exc:
        sys.stderr.write("thin ledger: %s\n" % exc)
        return EXIT_THIN
    except OSError as exc:
        sys.stderr.write("io error: %s\n" % exc)
        return EXIT_DATA


if __name__ == "__main__":
    sys.exit(main())
