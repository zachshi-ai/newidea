#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope-creep — 增项镜 / Renovation Scope-Creep Ledger

A renovation quote is sold to the home you intend to have; the settlement
bill is paid for the home you actually got. Between the two lives the
change order — and the trade knows it: a trade that is absent from the
quote is not a trade that will not happen, it is a trade that has not
been priced yet. Every single add-on sounds reasonable on the day it is
proposed ("no waterproofing and the downstairs neighbor drowns"); the
runaway is only visible at settlement, when the money is already spent.

scope-creep keeps that ledger by hand (three TSV files):

  quote.tsv    the contract quote, one row per line item
               (category/item/unit/qty/price/amount)
  changes.tsv  the change-order stream (date/type/category/item/amount/
               who/reason); an empty date = a PENDING order shouted on
               site but not yet signed
  meta.tsv     key/value: mode (full/half/clean), start, plan, settle,
               settle_amount

Five commands:

  report    — the settlement ledger: contract vs settlement, the change
              rate verdict (HEALTHY / CREEP / AMBUSH), the
              contractor-proposed share of gross positive changes
              (LOWBALL lamp: a cheap contract paid in installments),
              the re-audit share (quantity under-estimation at quote
              time), monthly drift, and the in-progress projection
              ("day 61 of 101, change budget 10.5% spent, on this pace
              settlement lands at 17.4%")
  census    — the pre-signature scan: the standard trade list your mode
              implies, checked against what the quote actually prices.
              An absent trade is not missing data — it is a liability
              that has not been priced yet. HIGH absences (waterproofing,
              debris haul-away, management fee) exit 4.
  court     — the change-order court: signed orders attributed by WHO
              proposed them, then every pending order judged with
              evidence (absence record + projected rate after signing):
              ACCEPT / NEGOTIATE / REDO.
  compare   — the two-bid translator: bids are only comparable on the
              trades BOTH bids price; a bid that omits a trade is not
              cheap on that trade. Both sides get the census scan.
  validate  — ledger identity checks: settlement identity, line-item
              arithmetic, deduct/reaudit must reference quoted trades,
              date order, dual-algorithm replays.

Exit codes: 0 green/yellow · 2 broken ledger · 3 thin ledger (the
arithmetic is still printed) · 4 gate lamp (AMBUSH / LOWBALL /
FORESHADOW / HIGH absence / REDO).

Zero anchoring: with no --as-of the ledger anchors itself to the latest
date it knows (latest change date, or settle — settle is a fact the
ledger declares). No wall clock anywhere; the same ledger, on any
machine, on any day, prints byte-identical reports.

Method in one line: the change rate is (settlement - contract) /
contract; the projection multiplies it by total_days / elapsed_days;
the lowball lamp is the contractor's share of gross positive changes.

Honesty clauses: the tool never says whether an add-on is *needed* —
waterproofing really is mandatory; it says who proposed it, whether it
was in the quote, and what it does to the ledger. --extend teaches the
census your own must-check trades; local knowledge always wins. This is
not legal advice and it does not negotiate for you — it puts the
evidence on the table, the signature is still yours.
"""

import argparse
import os
import random
import sys
from datetime import date, timedelta

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_THIN = 3
EXIT_GATE = 4

# ---------------------------------------------------------------- text

CANON_TRADES = [
    "拆改", "水电", "防水", "瓦工", "木工", "油漆", "吊顶",
    "瓷砖", "地板", "室内门", "橱柜", "卫浴洁具", "灯具开关", "五金",
    "封窗", "美缝", "保洁", "垃圾清运", "管理费", "监理", "其他",
]

TRADE_ALIASES = {}
for _t in CANON_TRADES:
    TRADE_ALIASES[_t] = _t
TRADE_ALIASES.update({
    "拆除": "拆改", "demolition": "拆改",
    "水电改造": "水电", "水路电路": "水电", "plumbing": "水电", "electrical": "水电",
    "waterproofing": "防水", "闭水": "防水",
    "泥工": "瓦工", "泥瓦工": "瓦工", "贴砖": "瓦工", "tiling": "瓦工",
    "carpentry": "木工",
    "乳胶漆": "油漆", "涂装": "油漆", "painting": "油漆",
    "ceiling": "吊顶",
    "tiles": "瓷砖",
    "flooring": "地板",
    "门": "室内门", "doors": "室内门",
    "柜": "橱柜", "cabinet": "橱柜",
    "卫浴": "卫浴洁具", "洁具": "卫浴洁具", "bathroom": "卫浴洁具",
    "灯具": "灯具开关", "灯": "灯具开关", "lighting": "灯具开关",
    "hardware": "五金",
    "windows": "封窗",
    "grout": "美缝",
    "cleaning": "保洁",
    "清运": "垃圾清运", "渣土清运": "垃圾清运", "trash": "垃圾清运",
    "管理": "管理费", "management": "管理费",
    "supervision": "监理",
    "other": "其他",
})

TYPE_ALIASES = {}
for _t in ("add", "deduct", "upgrade", "reaudit"):
    TYPE_ALIASES[_t] = _t
TYPE_ALIASES.update({
    "新增": "add", "增项": "add", "加项": "add",
    "减项": "deduct", "扣除": "deduct", "取消": "deduct",
    "升级": "upgrade", "主材升级": "upgrade", "换新": "upgrade",
    "重算": "reaudit", "复核": "reaudit", "按实结算": "reaudit",
    "工程量重算": "reaudit",
})

WHO_ALIASES = {}
for _w in ("owner", "contractor"):
    WHO_ALIASES[_w] = _w
WHO_ALIASES.update({
    "业主": "owner", "我": "owner", "self": "owner",
    "施工方": "contractor", "工长": "contractor", "装修公司": "contractor",
    "builder": "contractor",
})

# census prior: trades any mode implies (the crew must be on site)
PRIOR_BASE = {
    "拆改": "LOW", "水电": "LOW", "防水": "HIGH", "瓦工": "LOW",
    "木工": "LOW", "油漆": "LOW", "吊顶": "LOW",
    "垃圾清运": "HIGH", "保洁": "LOW",
}
# mains: only a full (labor+materials) contract promises these
PRIOR_MAINS = {
    "瓷砖": "LOW", "地板": "LOW", "室内门": "LOW", "橱柜": "LOW",
    "卫浴洁具": "LOW", "灯具开关": "LOW", "封窗": "LOW", "美缝": "LOW",
}
# management: a full contract bills these; half/clean = you are the PM
PRIOR_MGMT_FULL = {"管理费": "HIGH", "监理": "LOW"}

CREEP_LINE = 5.0      # % of contract: above this, watch the ledger
AMBUSH_LINE = 15.0    # % of contract: lowball ambush territory
LOWBALL_LINE = 50.0   # contractor share of gross positive changes, %
IDENTITY_TOL = 1.0    # hand-copied money: 1 yuan absorbs cent rounding
THIN_QUOTE_ROWS = 5
THIN_CHANGE_ROWS = 3


class LedgerError(Exception):
    """Broken ledger — exit 2."""


class ThinError(Exception):
    """Thin ledger — statistics decline, arithmetic already printed."""


# ------------------------------------------------------------ helpers

def dw(s):
    """Display width: CJK counts 2 columns."""
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def pad(s, w):
    return s + " " * max(0, w - dw(s))


def money(x):
    return ("-" if x < -1e-9 else "") + "{:,.2f}".format(abs(x))


def pct(x):
    return "{:.2f}%".format(x)


def canon_trade(raw):
    t = (raw or "").strip().lower()
    return TRADE_ALIASES.get(t, (raw or "").strip()), \
        (raw or "").strip().lower() in TRADE_ALIASES


def canon_type(raw):
    t = (raw or "").strip().lower()
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]
    raise LedgerError("unknown change type %r (add/deduct/upgrade/reaudit)"
                      % raw)


def canon_who(raw):
    t = (raw or "").strip().lower()
    if t in WHO_ALIASES:
        return WHO_ALIASES[t]
    raise LedgerError("unknown proposer %r (owner/contractor)" % raw)


def parse_date(raw, what):
    s = (raw or "").strip()
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        raise LedgerError("bad date %r in %s (want YYYY-MM-DD)" % (raw, what))


def parse_amount(raw, what):
    s = (raw or "").strip().replace(",", "")
    try:
        v = float(s)
    except ValueError:
        raise LedgerError("bad amount %r in %s" % (raw, what))
    return v


def read_tsv(path, columns, what):
    """Read a TSV; '#' lines are comments; first non-comment row is the
    header. Returns a list of dicts. Strict on missing columns."""
    if not os.path.exists(path):
        raise LedgerError("%s not found: %s" % (what, path))
    with open(path, encoding="utf-8") as fh:
        rows = [ln.rstrip("\n") for ln in fh if ln.strip()
                and not ln.lstrip().startswith("#")]
    if not rows:
        raise LedgerError("%s is empty: %s" % (what, path))
    header = [c.strip().lower() for c in rows[0].split("\t")]
    missing = [c for c in columns if c not in header]
    if missing:
        raise LedgerError("%s: missing column(s) %s (header: %s)"
                          % (what, ",".join(missing), "/".join(header)))
    out = []
    for ln in rows[1:]:
        cells = ln.split("\t")
        if len(cells) < len(header):
            raise LedgerError("%s: row has %d cells, header has %d: %r"
                              % (what, len(cells), len(header), ln))
        out.append({c: cells[i].strip() for i, c in enumerate(header)})
    return out


def load_meta(path):
    meta = {}
    if not os.path.exists(path):
        return meta
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            cells = ln.split("\t")
            if len(cells) < 2:
                raise LedgerError("meta: want key<TAB>value, got %r" % ln)
            meta[cells[0].strip().lower()] = cells[1].strip()
    for k in meta:
        if k not in ("mode", "start", "plan", "settle", "settle_amount"):
            raise LedgerError("meta: unknown key %r" % k)
    return meta


# ------------------------------------------------------------- ledger

def load_ledger(quote_p, changes_p, meta_p, as_of):
    """Parse + truncate the ledger at as_of. Returns a state dict.
    A missing changes.tsv is legal: before signature there are no
    change orders yet, and the census must still run."""
    qrows = read_tsv(quote_p, ["category", "item", "unit", "qty", "price",
                               "amount"], "quote")
    if os.path.exists(changes_p):
        crows = read_tsv(changes_p, ["date", "type", "category", "item",
                                     "amount", "who", "reason"], "changes")
    else:
        crows = []
    meta = load_meta(meta_p)

    mode = (meta.get("mode") or "full").strip().lower()
    if mode not in ("full", "half", "clean"):
        raise LedgerError("meta mode %r not in full/half/clean" % mode)

    # ---- quote
    quote = []
    per_trade = {}
    for r in qrows:
        cat, known = canon_trade(r["category"])
        amt = parse_amount(r["amount"], "quote")
        if amt <= 0:
            raise LedgerError("quote amount must be positive, got %s (%s)"
                              % (r["amount"], r["item"]))
        qty = parse_amount(r["qty"], "quote")
        price = parse_amount(r["price"], "quote")
        quote.append(dict(trade=cat, known=known, item=r["item"],
                          unit=r["unit"], qty=qty, price=price, amount=amt))
        per_trade[cat] = per_trade.get(cat, 0.0) + amt
    quote_total = sum(q["amount"] for q in quote)
    if quote_total <= 0:
        raise LedgerError("quote total is zero — nothing to audit")

    # ---- meta dates
    start = parse_date(meta["start"], "meta start") if meta.get("start") \
        else None
    plan = parse_date(meta["plan"], "meta plan") if meta.get("plan") else None
    settle = parse_date(meta["settle"], "meta settle") if meta.get("settle") \
        else None
    settle_amount = parse_amount(meta["settle_amount"], "meta settle_amount") \
        if meta.get("settle_amount") else None
    if plan and start and plan <= start:
        raise LedgerError("meta plan (%s) must be after start (%s)"
                          % (plan, start))
    if settle and start and settle < start:
        raise LedgerError("meta settle (%s) before start (%s)"
                          % (settle, start))

    # ---- default as-of: the latest fact the ledger declares
    all_dates = [parse_date(r["date"], "changes") for r in crows
                 if r["date"].strip()]
    if settle:
        all_dates.append(settle)
    if not as_of:
        as_of = max(all_dates) if all_dates else None

    # ---- changes
    changes, pending, future = [], [], 0
    for r in crows:
        typ = canon_type(r["type"])
        who = canon_who(r["who"])
        cat, known = canon_trade(r["category"])
        amt = parse_amount(r["amount"], "changes")
        d = r["date"].strip()
        if not d:
            pending.append(dict(type=typ, who=who, trade=cat, known=known,
                                item=r["item"], amount=amt,
                                reason=r["reason"]))
            continue
        dt = parse_date(d, "changes")
        if settle and dt > settle:
            raise LedgerError("change dated %s is after settle (%s) — "
                              "nothing moves after settlement" % (dt, settle))
        if as_of and dt > as_of:
            future += 1
            continue
        signed = amt
        if typ in ("add", "upgrade"):
            if amt <= 0:
                raise LedgerError("%s amount must be positive (%s)"
                                  % (typ, r["item"]))
            signed = amt
        elif typ == "deduct":
            if amt <= 0:
                raise LedgerError("deduct amount must be positive, direction "
                                  "comes from type (%s)" % r["item"])
            signed = -amt
        else:  # reaudit: signed money, an over-charge can come back
            signed = amt
        changes.append(dict(date=dt, type=typ, who=who, trade=cat,
                            known=known, item=r["item"], amount=amt,
                            signed=signed, reason=r["reason"]))
    changes.sort(key=lambda c: c["date"])

    st = dict(quote=quote, per_trade=per_trade, quote_total=quote_total,
              changes=changes, pending=pending, future=future,
              meta=meta, mode=mode, start=start, plan=plan, settle=settle,
              settle_amount=settle_amount, as_of=as_of)
    _derive(st)
    return st


def _derive(st):
    ch = st["changes"]
    s_add = sum(c["signed"] for c in ch if c["type"] == "add")
    s_upg = sum(c["signed"] for c in ch if c["type"] == "upgrade")
    s_rea = sum(c["signed"] for c in ch if c["type"] == "reaudit")
    s_ded = sum(c["signed"] for c in ch if c["type"] == "deduct")
    net = s_add + s_upg + s_rea + s_ded  # s_ded is already negative
    gross_pos = sum(c["amount"] for c in ch if c["signed"] > 0)
    con_pos = sum(c["amount"] for c in ch
                  if c["signed"] > 0 and c["who"] == "contractor")
    rea_pos = sum(c["amount"] for c in ch
                  if c["type"] == "reaudit" and c["signed"] > 0)
    monthly = {}
    for c in ch:
        key = "%04d-%02d" % (c["date"].year, c["date"].month)
        monthly[key] = monthly.get(key, 0.0) + c["signed"]

    st.update(s_add=s_add, s_upg=s_upg, s_rea=s_rea, s_ded=s_ded, net=net,
              gross_pos=gross_pos, con_pos=con_pos, rea_pos=rea_pos,
              monthly=monthly)
    st["rate"] = net / st["quote_total"] * 100.0
    st["passive"] = (con_pos / gross_pos * 100.0) if gross_pos > 0 else None
    st["rea_share"] = (rea_pos / gross_pos * 100.0) if gross_pos > 0 else None
    st["settlement"] = st["quote_total"] + net
    if st["start"] and st["plan"]:
        total = (st["plan"] - st["start"]).days
        elapsed = (st["as_of"] - st["start"]).days if st["as_of"] else 0
        st["total_days"], st["elapsed_days"] = total, max(elapsed, 0)
        st["progress"] = (min(max(elapsed, 0), total) / total * 100.0) \
            if total > 0 else None
        # projection only exists while the site is still running: before
        # settle, and never past the plan horizon (overtime doesn't
        # multiply the change budget)
        live = st["as_of"] and elapsed > 0 \
            and not (st["settle"] and st["as_of"] >= st["settle"])
        st["projection"] = (st["rate"] * total / min(elapsed, total)) \
            if live else None
    else:
        st["total_days"] = st["elapsed_days"] = None
        st["progress"] = st["projection"] = None
    st["final"] = bool(st["settle"] and st["as_of"]
                       and st["as_of"] >= st["settle"])


# ------------------------------------------------------------ census

def prior_table(mode, extend):
    table = dict(PRIOR_BASE)
    if mode == "full":
        table.update(PRIOR_MAINS)
        table.update(PRIOR_MGMT_FULL)
    for spec in extend or []:
        parts = spec.split(":")
        trade, known = canon_trade(parts[0].strip())
        sev = "LOW"
        if len(parts) > 1 and parts[1].strip().upper() == "HIGH":
            sev = "HIGH"
        if not known:
            print("census: extend trade %r is not a known trade word — "
                  "added as a free must-check" % trade)
        table[trade] = sev
    return table


def census_scan(st, extend):
    """Returns (absent_high, absent_low, unknown_quoted)."""
    table = prior_table(st["mode"], extend)
    present = set(st["per_trade"])
    absent_high = sorted(t for t, s in table.items()
                         if s == "HIGH" and t not in present)
    absent_low = sorted(t for t, s in table.items()
                        if s == "LOW" and t not in present)
    unknown = sorted(t for t, k in ((q["trade"], q["known"])
                                    for q in st["quote"]) if not k)
    return absent_high, absent_low, unknown


# ------------------------------------------------------------ report

def _verdict_lines(st, creep, ambush, lowball):
    lines, gate = [], False
    rate, proj = st["rate"], st["projection"]
    worst = max(rate, proj) if proj is not None else rate
    if st["final"]:
        if rate > ambush + 1e-9:
            lines.append("VERDICT: AMBUSH — settlement runs %s over "
                         "contract (ambush line %s)."
                         % (pct(rate), pct(ambush)))
            gate = True
        elif rate > creep + 1e-9:
            lines.append("VERDICT: CREEP — %s over contract, common but "
                         "worth a post-mortem (creep line %s)."
                         % (pct(rate), pct(creep)))
        else:
            lines.append("VERDICT: HEALTHY — %s over contract (creep line "
                         "%s)." % (pct(rate), pct(creep)))
    else:
        if proj is not None:
            lines.append("PROJECTION: at this pace settlement lands at %s "
                         "over contract (now %s, day %s of %s)."
                         % (pct(proj), pct(rate), st["elapsed_days"],
                            st["total_days"]))
        if worst > ambush + 1e-9:
            lines.append("VERDICT: FORESHADOW — the ambush is visible "
                         "BEFORE settlement; renegotiate now, not at the "
                         "settlement table (line %s)." % pct(ambush))
            gate = True
        elif worst > creep + 1e-9:
            lines.append("VERDICT: CREEP AHEAD — %s over contract already "
                         "(creep line %s)." % (pct(rate), pct(creep)))
        else:
            lines.append("VERDICT: HEALTHY SO FAR — %s over contract."
                         % pct(rate))
    if st["passive"] is not None:
        if st["passive"] > lowball + 1e-9:
            lines.append("LOWBALL LAMP: %s of gross positive changes were "
                         "proposed by the contractor (line %s) — a cheap "
                         "contract is bought on installments."
                         % (pct(st["passive"]), pct(lowball)))
            gate = True
        else:
            lines.append("contractor share of gross positive changes: %s "
                         "(lowball line %s)."
                         % (pct(st["passive"]), pct(lowball)))
    return lines, gate


def cmd_report(args, st):
    q = st["quote"]
    head = "=== scope-creep · report ==="
    print(head)
    phase = ("FINAL AUDIT" if st["final"]
             else "IN PROGRESS" if st["as_of"] else "STATIC")
    print("ledger: %s + %s (mode %s%s, as-of %s, %s)"
          % (os.path.basename(args.quote), os.path.basename(args.changes),
             st["mode"],
             "" if "mode" in st["meta"] else " assumed",
             st["as_of"] or "n/a", phase))
    print("")
    print("contract quote          ¥%s  (%d line items)"
          % (money(st["quote_total"]), len(q)))
    w = max(dw(t) for t in st["per_trade"]) + 2
    for t in sorted(st["per_trade"],
                    key=lambda k: -st["per_trade"][k]):
        print("  %s ¥%s" % (pad(t, w), money(st["per_trade"][t])))
    print("")
    n_settled, n_pend = len(st["changes"]), len(st["pending"])
    print("change orders: %d settled, %d pending (excluded), %d after as-of"
          % (n_settled, n_pend, st["future"]))
    print("  add +¥%s / upgrade +¥%s / reaudit %s / deduct %s"
          % (money(st["s_add"]), money(st["s_upg"]),
             money(st["s_rea"]), money(st["s_ded"])))
    print("net change              +¥%s  (%s of contract)"
          % (money(st["net"]), pct(st["rate"])))
    print("settlement              ¥%s" % money(st["settlement"]))
    if st["rea_share"] is not None and st["rea_share"] > 0:
        print("reaudit share of gross positive changes: %s%s"
              % (pct(st["rea_share"]),
                 "  <- quantity under-estimated at quote time"
                 if st["rea_share"] >= 25.0 else ""))
    if st["monthly"]:
        peak = max(st["monthly"], key=lambda k: st["monthly"][k])
        chain = " / ".join("%s %s%s" % (k, "+" if v >= 0 else "-",
                                        "{:,.0f}".format(abs(v)))
                           for k, v in sorted(st["monthly"].items()))
        print("monthly net: %s   (peak %s — the trade phase where change "
              "orders cluster)" % (chain, peak))
    if st["settle"]:
        late = (st["settle"] - st["plan"]).days if st["plan"] else None
        tail = (" — %d days past plan" % late) if late and late > 0 else ""
        print("settlement date %s%s" % (st["settle"], tail))
    if st["settle_amount"] is not None and st["final"]:
        resid = abs(st["settle_amount"] - st["settlement"])
        flag = "" if resid <= IDENTITY_TOL else \
            "  (!! settlement identity broken by ¥%s — run validate)" \
            % money(resid)
        print("declared settlement    ¥%s%s"
              % (money(st["settle_amount"]), flag))
    print("")
    thin = len(q) < THIN_QUOTE_ROWS or n_settled < THIN_CHANGE_ROWS
    if thin:
        print("THIN: %d quote rows / %d settled changes — the statistics "
              "decline to grade; the arithmetic above stands."
              % (len(q), n_settled))
        return EXIT_THIN
    lines, gate = _verdict_lines(st, args.creep_line, args.ambush_line,
                                 args.lowball_line)
    for ln in lines:
        print(ln)
    return EXIT_GATE if gate else EXIT_OK


# ------------------------------------------------------------- census

def cmd_census(args, st):
    print("=== scope-creep · census ===")
    print("ledger: %s (mode %s%s) — pre-signature scan of the quote"
          % (os.path.basename(args.quote), st["mode"],
             "" if "mode" in st["meta"] else " assumed"))
    ah, al, unknown = census_scan(st, args.extend)
    print("quote prices %d trades: %s"
          % (len(st["per_trade"]),
             ", ".join(sorted(st["per_trade"])) or "(none)"))
    print("")
    if unknown:
        print("free trades not in the standard list (not graded): %s"
              % ", ".join(unknown))
        print("")
    if not ah and not al:
        print("no absence found — every trade this mode implies is priced.")
        return EXIT_OK
    if al:
        print("LOW absence (reminders — some owners self-buy these):")
        for t in al:
            print("  - %s" % t)
        print("")
    if ah:
        print("HIGH absence — a trade that will almost surely happen is "
              "not in the quote:")
        for t in ah:
            print("  ! %s — absent from the quote is not absent from the "
                  "site; it comes back as a change order, priced by the "
                  "crew that lowballed you." % t)
        print("")
        print("VERDICT: AMBUSH PRE-LOADED — %d high-risk trade(s) missing. "
              "Before signing: have them written into the contract price, "
              "or get a written 'not included' and price them yourself."
              % len(ah))
        return EXIT_GATE
    print("no HIGH absence — quote covers the risky trades.")
    return EXIT_OK


# -------------------------------------------------------------- court

def cmd_court(args, st):
    print("=== scope-creep · court ===")
    print("ledger: %s + %s (as-of %s)"
          % (os.path.basename(args.quote), os.path.basename(args.changes),
             st["as_of"] or "n/a"))
    print("")
    ch = st["changes"]
    print("signed change orders, attributed by who proposed them:")
    for who in ("contractor", "owner"):
        amt = sum(c["amount"] for c in ch
                  if c["signed"] > 0 and c["who"] == who)
        cnt = sum(1 for c in ch if c["signed"] > 0 and c["who"] == who)
        mark = ""
        if who == "contractor" and st["passive"] is not None \
                and st["passive"] > args.lowball_line + 1e-9:
            mark = "  <- LOWBALL: majority of the add-ons are theirs"
        print("  %-10s +%s across %d positive order(s)%s"
              % (who, money(amt), cnt, mark))
    neg = sum(1 for c in ch if c["signed"] < 0)
    if neg:
        print("  (%d deduct(s) excluded from attribution)" % neg)
    if st["rea_share"] is not None and st["rea_share"] >= 25.0:
        print("  reaudit share %s — 'settle by actual quantity' is the "
              "quote's escape hatch; re-read the estimate."
              % pct(st["rea_share"]))
    print("")
    if not st["pending"]:
        print("no pending change orders — nothing to judge today.")
        return EXIT_OK if ch else EXIT_THIN
    ah, al, _u = census_scan(st, args.extend)
    thin = len(st["quote"]) < THIN_QUOTE_ROWS
    gate = False
    print("pending order(s): %d" % len(st["pending"]))
    run_net = st["net"]
    for i, p in enumerate(st["pending"], 1):
        run_net += p["amount"]
        after = run_net / st["quote_total"] * 100.0
        proj = after * st["total_days"] / st["elapsed_days"] \
            if st["projection"] is not None else None
        worst = max(after, proj) if proj is not None else after
        if worst > args.ambush_line + 1e-9:
            verdict = "REDO"
        elif worst > args.creep_line + 1e-9:
            verdict = "NEGOTIATE"
        else:
            verdict = "ACCEPT"
        if verdict == "REDO":
            gate = True
        print("  #%d %s [%s] %s%s (proposed by %s)"
              % (i, p["item"], p["trade"], "+" if p["amount"] >= 0 else "-",
                 money(abs(p["amount"])), p["who"]))
        if p["reason"]:
            print("     says: \"%s\"" % p["reason"])
        if p["trade"] in ah:
            print("     evidence: %s is HIGH-absent from the quote — this "
                  "is the ambush arriving on schedule; fold it into the "
                  "contract price, not a change order." % p["trade"])
        elif p["trade"] in al:
            print("     evidence: %s was LOW-absent from the quote." % p["trade"])
        else:
            print("     evidence: %s is priced in the quote." % p["trade"])
        tail = (" → projection %s" % pct(proj)) if proj is not None else ""
        print("     after signing: %s over contract%s (lines %s/%s)"
              % (pct(after), tail, pct(args.creep_line),
                 pct(args.ambush_line)))
        print("     verdict: %s" % {
            "ACCEPT": "ACCEPT — within the creep line; sign if the work "
                      "is real",
            "NEGOTIATE": "NEGOTIATE — survivable, but the rate is yours "
                         "to argue down",
            "REDO": "REDO — this order pushes the projected settlement "
                    "past the ambush line; cut it or trade something "
                    "off the table"}[verdict])
        print("")
    if thin:
        print("THIN: %d quote rows — grading declines; the evidence above "
              "stands." % len(st["quote"]))
        return EXIT_THIN
    if gate:
        print("gate: at least one pending order verdicts REDO (exit 4).")
        return EXIT_GATE
    return EXIT_OK


# ------------------------------------------------------------ compare

def cmd_compare(args, st):
    if not args.quote2:
        raise LedgerError("compare needs --quote2 BID.tsv")
    q2 = read_tsv(args.quote2, ["category", "item", "unit", "qty", "price",
                                "amount"], "quote2")
    b = {}
    b_unknown = []
    for r in q2:
        cat, known = canon_trade(r["category"])
        if not known:
            b_unknown.append(cat)
        b[cat] = b.get(cat, 0.0) + parse_amount(r["amount"], "quote2")
    a = st["per_trade"]
    total_a, total_b = st["quote_total"], sum(b.values())
    common = sorted(set(a) & set(b))
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))

    print("=== scope-creep · compare ===")
    print("bid A: %s  ¥%s" % (os.path.basename(args.quote),
                              money(total_a)))
    print("bid B: %s  ¥%s" % (os.path.basename(args.quote2),
                              money(total_b)))
    print("headline gap: B − A = %s (%s of A)"
          % (money(total_b - total_a),
             pct((total_b - total_a) / total_a * 100.0)))
    print("")
    print("common trades (%d) — the only comparable rows:" % len(common))
    w = max([dw(t) for t in common] or [4]) + 2
    diff_common = 0.0
    for t in common:
        d = b[t] - a[t]
        diff_common += d
        print("  %s A ¥%s  B ¥%s  %s%s"
              % (pad(t, w), money(a[t]), money(b[t]),
                 "+" if d > 0 else ("-" if d < 0 else " "),
                 money(abs(d))))
    print("  common subtotal gap: %s" % money(diff_common))
    print("")
    if only_a:
        print("only A prices (B is silent on these — check B's census "
              "below, not B's total): %s" % ", ".join(only_a))
    if only_b:
        print("only B prices: %s  ¥%s"
              % (", ".join(only_b),
                 money(sum(b[t] for t in only_b))))
    if only_b:
        print("  of the headline gap %s, %s is simply trades A left out — "
              "A is not cheaper there, A is silent there."
              % (money(total_b - total_a), money(sum(b[t] for t in only_b))))
    print("")
    ah2, al2, _u = census_scan(_alt_state(st, b, total_b), args.extend)
    print("census of bid B (mode %s):" % st["mode"])
    if ah2:
        for t in ah2:
            print("  ! HIGH absence: %s" % t)
    if al2:
        for t in al2:
            print("  - LOW absence: %s" % t)
    if not ah2 and not al2:
        print("  no absence — every trade this mode implies is priced.")
    if b_unknown:
        print("  free trades on B's sheet (not graded): %s"
              % ", ".join(sorted(set(b_unknown))))
    print("")
    if st["final"]:
        over = st["settlement"] - total_b
        if over > 0:
            print("REALITY CHECK: A's realized settlement is ¥%s — %s "
                  "ABOVE bid B's quote. A's lowball was paid back in "
                  "change orders."
                  % (money(st["settlement"]), money(over)))
        else:
            print("REALITY CHECK: A's realized settlement is ¥%s, %s under "
                  "bid B's quote — but B's settlement is unknown; B could "
                  "run its own change orders."
                  % (money(st["settlement"]), money(-over)))
        if st["passive"] is not None and st["passive"] > 50.0:
            print("  and %s of A's add-ons were proposed by the crew — "
                  "the omission was systematic, not a slip."
                  % pct(st["passive"]))
        return EXIT_GATE if over > 0 else EXIT_OK
    print("REALITY CHECK unlocks at settlement (set meta settle / "
          "settle_amount) — until then compare is a pre-signature lens.")
    return EXIT_GATE if ah2 else EXIT_OK


def _alt_state(st, per_trade, total):
    """A minimal state clone for scanning bid B with the same priors."""
    clone = dict(st)
    clone["per_trade"] = per_trade
    clone["quote_total"] = total
    clone["quote"] = [dict(trade=t, known=True) for t in per_trade]
    return clone


# ----------------------------------------------------------- validate

def cmd_validate(args, st):
    print("=== scope-creep · validate ===")
    print("ledger: %s + %s + %s (as-of %s)"
          % (os.path.basename(args.quote), os.path.basename(args.changes),
             os.path.basename(args.meta), st["as_of"] or "n/a"))
    fails = []

    def check(name, ok, detail=""):
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               (" — " + detail) if detail else ""))
        if not ok:
            fails.append(name)

    # 1. settlement identity (declared settlement == quote + net)
    if st["settle_amount"] is not None:
        resid = abs(st["settle_amount"] - st["settlement"])
        check("settlement identity  quote+net == declared (resid ¥%s ≤ ¥%s)"
              % (money(resid), money(IDENTITY_TOL)),
              resid <= IDENTITY_TOL)
    else:
        print("  [SKIP] settlement identity — meta settle_amount not set")

    # 2. line-item arithmetic qty*price == amount
    bad = []
    for q in st["quote"]:
        if abs(q["qty"] * q["price"] - q["amount"]) > 0.01:
            bad.append(q["item"])
    check("line arithmetic  qty×price == amount on all %d rows"
            % len(st["quote"]), not bad,
            "off: %s" % ", ".join(bad) if bad else "")

    # 3. deduct/reaudit must reference a quoted trade
    quoted = set(st["per_trade"])
    bad = sorted({c["trade"] for c in st["changes"]
                  if c["type"] in ("deduct", "reaudit")
                  and c["trade"] not in quoted})
    check("deduct/reaudit reference quoted trades", not bad,
          "unquoted: %s" % ", ".join(bad) if bad else "")

    # 4. date order: changes not before start, not after settle
    bad = [str(c["date"]) for c in st["changes"]
           if st["start"] and c["date"] < st["start"]]
    check("no change order before start", not bad,
          "early: %s" % ", ".join(bad) if bad else "")

    # 5. dual algorithm: net by rows == net by groups
    by_rows = sum(c["signed"] for c in st["changes"])
    by_groups = st["s_add"] + st["s_upg"] + st["s_rea"] + st["s_ded"]
    check("dual algorithm  net by rows == net by groups (¥%s)"
          % money(by_rows), abs(by_rows - by_groups) < 1e-9)

    # 6. dual algorithm: day counts via timedelta vs ordinals, 50 pairs
    rng = random.Random(20261001)
    ok = True
    for _ in range(50):
        d1 = date(2025, 1, 1) + timedelta(days=rng.randrange(0, 700))
        d2 = date(2025, 1, 1) + timedelta(days=rng.randrange(0, 700))
        ok = ok and (d2 - d1).days == (d2.toordinal() - d1.toordinal())
    check("dual algorithm  timedelta == ordinal difference (50 pairs)", ok)

    # 7. monthly ledger sums to net
    check("monthly split sums to net (¥%s)"
          % money(sum(st["monthly"].values())),
          abs(sum(st["monthly"].values()) - st["net"]) < 1e-9)

    print("")
    if fails:
        print("BROKEN: %d check(s) failed: %s"
              % (len(fails), "; ".join(fails)))
        return EXIT_INPUT
    print("ledger checks out — %d settled rows, %d pending, quote ¥%s."
          % (len(st["changes"]), len(st["pending"]),
             money(st["quote_total"])))
    return EXIT_OK


# --------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(
        prog="scope_creep.py",
        description="增项镜 · Scope Creep — renovation change-order ledger")

    def add_common(sp, suppress=False):
        # mounted on every subcommand too (argparse drops global options
        # written after the subcommand); the subparser side uses SUPPRESS
        # so it never clobbers a value the global parser already set
        dflt = argparse.SUPPRESS if suppress else None
        sp.add_argument("--quote", default="quote.tsv" if not suppress
                        else dflt)
        sp.add_argument("--changes", default="changes.tsv" if not suppress
                        else dflt)
        sp.add_argument("--meta", default="meta.tsv" if not suppress
                        else dflt)
        sp.add_argument("--as-of", dest="as_of", default=dflt)
        return sp

    add_common(p)
    sub = p.add_subparsers(dest="command", required=True)

    r = add_common(sub.add_parser("report", help="settlement ledger + verdict"),
                   suppress=True)
    r.add_argument("--creep-line", dest="creep_line", type=float,
                   default=CREEP_LINE)
    r.add_argument("--ambush-line", dest="ambush_line", type=float,
                   default=AMBUSH_LINE)
    r.add_argument("--lowball-line", dest="lowball_line", type=float,
                   default=LOWBALL_LINE)

    c = add_common(sub.add_parser("census", help="pre-signature absence scan"),
                   suppress=True)
    c.add_argument("--extend", action="append", default=[],
                   help="extra must-check trade, TRADE[:HIGH|LOW]")

    k = add_common(sub.add_parser("court", help="pending change-order court"),
                   suppress=True)
    k.add_argument("--creep-line", dest="creep_line", type=float,
                   default=CREEP_LINE)
    k.add_argument("--ambush-line", dest="ambush_line", type=float,
                   default=AMBUSH_LINE)
    k.add_argument("--lowball-line", dest="lowball_line", type=float,
                   default=LOWBALL_LINE)
    k.add_argument("--extend", action="append", default=[])

    m = add_common(sub.add_parser("compare", help="two-bid translator"),
                   suppress=True)
    m.add_argument("--quote2", default=None)
    m.add_argument("--extend", action="append", default=[])

    add_common(sub.add_parser("validate", help="ledger identity checks"),
               suppress=True)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        as_of = parse_date(args.as_of, "--as-of") if args.as_of else None
        st = load_ledger(args.quote, args.changes, args.meta, as_of)
        if args.command == "report":
            return cmd_report(args, st)
        if args.command == "census":
            return cmd_census(args, st)
        if args.command == "court":
            return cmd_court(args, st)
        if args.command == "compare":
            return cmd_compare(args, st)
        if args.command == "validate":
            return cmd_validate(args, st)
        raise LedgerError("unknown command %r" % args.command)
    except LedgerError as e:
        print("ledger error: %s" % e, file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":
    sys.exit(main())
