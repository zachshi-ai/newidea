#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
银行眼 · Lender's Eye / 征信档案的审批视角翻译器。

征信报告是唯一决定银行敢借你多少钱的档案,但报告印给你的是流水,银行读到的
是风险——同一份档案两种读法,中间没有翻译:「我都结清了」在银行眼里是「他
借过网贷(结清的记录也还在)」,「我就点点看额度」是你亲手按下的硬查询扣分
键,「每月正常还款」背后 86% 的额度使用率写着「这人缺钱」。被拒通知只有
「综合评分不足」六个字的黑箱,而所有修复手段都吃时间——等看见问题时,房
子往往已经看好了。

本件把央行自查报告抄成三本可手编账,用审批的通识口径(全部 -- 可调,信贷
经理永远赢)把档案重读一遍:

  report  银行眼快照——账户结构 + 全部信号灯(以 as-of 为「今天」)
  gate    假设 --apply-date 那天申请指定产品,窗口随申请日滚动,逐灯 PASS/FAIL
  clock   把修复拆成两半:时间能治的给愈合日历,必须动手的给清单
  validate 恒等式与账本体检

诚实条款:阈值是通识垫底不是审批标准,审批是收入/流水/社保/房屋本身的多变
量黑箱,本件只翻译档案侧看得见的部分;它不预测审批结果,不构成贷款建议。
征信是最敏感的数据:不连任何接口,不上传任何字节,报告只打印账本文件名。

零墙钟: as-of 缺省 = 三本账所有日期的最大值;同一本账任何机器任何一天逐字
节一致。

账本(--dir 目录下三份 TSV):
  accounts.tsv   name/type/opened/limit/balance/status/lender   (核心账,必需)
  inquiries.tsv  date/agency/reason                             (可缺席=无记录)
  delinq.tsv     date/account/days                              (可缺席=无记录)
"""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

ACCOUNT_COLS = ("name", "type", "opened", "limit", "balance", "status", "lender")
INQUIRY_COLS = ("date", "agency", "reason")
DELINQ_COLS = ("date", "account", "days")

ACCOUNT_TYPES = ("mortgage", "car_loan", "credit_card",
                 "online_loan", "consumer_loan", "other_loan")
STATUSES = ("active", "settled", "closed")
LENDERS = ("bank", "online")
LOAN_TYPES = ("mortgage", "car_loan", "online_loan", "consumer_loan", "other_loan")
# 硬查询(审批敏感):贷款审批/信用卡审批/担保资格审查。
# 软查询(不进窗口):贷后管理/个人自查/异议处理——由 reason 推导,不设 hard 列,
# 报告写了什么就是什么,用户少填一处就少错一处。
HARD_REASONS = ("loan_approval", "card_approval", "guarantee")
SOFT_REASONS = ("post_loan", "personal", "periodic")
REASONS = HARD_REASONS + SOFT_REASONS
DELINQ_TIERS = (30, 60, 90)   # 征信只记月档,1-29 天不上账本

ARCHIVE_YEARS = 5             # 不良信息自终止之日起留档 5 年(政策口径)

EXIT_OK, EXIT_BROKEN, EXIT_DECLINE, EXIT_ALARM = 0, 2, 3, 4

# 产品先验:通识垫底,银行间口径不一,信贷经理永远赢(-- 旗标整表可翻案)
PRODUCTS = {
    "mortgage":    dict(short_line=3, long_line=6, online_line=0,
                        util_line=80.0, delinq_days=30),
    "car_loan":    dict(short_line=4, long_line=8, online_line=1,
                        util_line=90.0, delinq_days=30),
    "credit_card": dict(short_line=5, long_line=10, online_line=2,
                        util_line=95.0, delinq_days=90),
}
DEFAULTS = PRODUCTS["mortgage"]
DEFAULT_SHORT_DAYS = 61    # 「近两个月」
DEFAULT_LONG_DAYS = 183    # 「近半年」
DEFAULT_DELINQ_WINDOW = 730  # 「近两年无 30+ 天逾期」——房贷审批的通识敏感窗
CLOCK_HORIZON = 730        # clock 往前看两年,再远的时间债必须动手


class LedgerError(Exception):
    """exit 2 — the ledger itself is broken."""


class EmptyLedger(Exception):
    """exit 3 — nothing to audit."""


# ---------------------------------------------------------------- text utils

def dw(s):
    """display width: CJK and friends count 2 terminal columns."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def pad(s, width):
    s = str(s)
    if dw(s) <= width:
        return s + " " * (width - dw(s))
    out, used = "", 0
    for ch in s:
        w = 2 if ord(ch) > 0x2E7F else 1
        if used + w > width - 1:
            break
        out += ch
        used += w
    return out + "…"


def money(x):
    return "{:,}".format(int(round(x)))


def strict_date(s, where):
    if not DATE_RE.fullmatch(s):
        raise LedgerError("%s: bad date '%s' (want YYYY-MM-DD, zero-padded)" % (where, s))
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise LedgerError("%s: impossible calendar date '%s'" % (where, s))


def parse_amount(s, where, field):
    try:
        v = float(s)
    except ValueError:
        raise LedgerError("%s: %s is not a number: '%s'" % (where, field, s))
    if v < 0:
        raise LedgerError("%s: %s is negative — debts are not negative in this "
                          "ledger, they live in the balance column" % (where, field))
    return v


def plus_years(d, years):
    """archive math; Feb 29 falls back to Mar 1."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, month=3, day=1)


# ---------------------------------------------------------------- parsing

def read_tsv(path, cols, label, required=True):
    """load one ledger TSV; returns (header, rows-as-dict-list).
    missing file: required -> EmptyLedger, optional -> ([], [])."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        if required:
            raise EmptyLedger("no %s at '%s' yet — start one: a header line "
                              "(%s), then one row per account" % (label, path, "/".join(cols)))
        return []
    except OSError as exc:
        raise LedgerError("cannot read %s: %s" % (label, exc))
    if not raw.strip():
        if required:
            raise EmptyLedger("%s is empty" % label)
        return [], []

    rows = []
    header_seen = False
    for i, line in enumerate(raw.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        while len(cells) > len(cols) and cells[-1] == "":
            cells.pop()  # trailing tabs come free with hand-pasted spreadsheets
        where = "%s line %d" % (label, i)
        if not header_seen:
            header_seen = True
            if tuple(c.strip().lower() for c in cells) != cols:
                raise LedgerError("%s: bad header, want %s" % (where, "/".join(cols)))
            continue
        if len(cells) != len(cols):
            raise LedgerError("%s: want %d tab-separated fields, got %d"
                              % (where, len(cols), len(cells)))
        rows.append(dict(line=i, where=where,
                         **{k: v.strip() for k, v in zip(cols, cells)}))
    if not header_seen:
        raise EmptyLedger("%s has no header row" % label)
    return rows


def load_accounts(path):
    rows = read_tsv(path, ACCOUNT_COLS, "accounts.tsv")
    accounts = []
    names = set()
    for r in rows:
        w = r["where"]
        name = r["name"]
        if not name:
            raise LedgerError("%s: account name is empty" % w)
        if name in names:
            raise LedgerError("%s: duplicate account name '%s'" % (w, name))
        names.add(name)
        if r["type"] not in ACCOUNT_TYPES:
            raise LedgerError("%s: unknown type '%s' (want one of %s)"
                              % (w, r["type"], "|".join(ACCOUNT_TYPES)))
        if r["status"] not in STATUSES:
            raise LedgerError("%s: unknown status '%s' (want one of %s)"
                              % (w, r["status"], "|".join(STATUSES)))
        if r["lender"] not in LENDERS:
            raise LedgerError("%s: unknown lender '%s' (want bank|online)" % (w, r["lender"]))
        opened = strict_date(r["opened"], w)
        limit = parse_amount(r["limit"], w, "limit")
        balance = parse_amount(r["balance"], w, "balance")
        if balance > limit + 1e-6:
            raise LedgerError("%s: balance %s exceeds limit %s on '%s'"
                              % (w, r["balance"], r["limit"], name))
        if r["status"] in ("settled", "closed") and balance > 1e-6:
            raise LedgerError("%s: '%s' is %s but still carries balance %s — "
                              "settled/closed means the debt is gone"
                              % (w, name, r["status"], r["balance"]))
        accounts.append(dict(line=r["line"], name=name, type=r["type"], opened=opened,
                             limit=limit, balance=balance, status=r["status"],
                             lender=r["lender"]))
    if not accounts:
        raise EmptyLedger("accounts.tsv has a header but no rows — an empty file "
                          "is an empty archive; add the first card or loan")
    return accounts


def load_inquiries(path):
    rows = read_tsv(path, INQUIRY_COLS, "inquiries.tsv", required=False)
    inquiries = []
    for r in rows:
        w = r["where"]
        if r["reason"] not in REASONS:
            raise LedgerError("%s: unknown reason '%s' (hard: %s; soft: %s)"
                              % (w, r["reason"], "|".join(HARD_REASONS), "|".join(SOFT_REASONS)))
        inquiries.append(dict(line=r["line"], date=strict_date(r["date"], w),
                              agency=r["agency"] or "(unnamed agency)", reason=r["reason"],
                              hard=r["reason"] in HARD_REASONS))
    return inquiries


def load_delinq(path, accounts):
    rows = read_tsv(path, DELINQ_COLS, "delinq.tsv", required=False)
    by_name = {a["name"]: a for a in accounts}
    delinqs = []
    for r in rows:
        w = r["where"]
        if r["account"] not in by_name:
            raise LedgerError("%s: delinquency references unknown account '%s'"
                              % (w, r["account"]))
        acc = by_name[r["account"]]
        d = strict_date(r["date"], w)
        if d < acc["opened"]:
            raise LedgerError("%s: delinquency on %s predates the account (opened %s)"
                              % (w, r["account"], acc["opened"]))
        if r["days"] not in ("30", "60", "90"):
            raise LedgerError("%s: days must be a monthly tier 30/60/90, got '%s' "
                              "(1-29 day lapses never reach the archive)" % (w, r["days"]))
        delinqs.append(dict(line=r["line"], date=d, account=r["account"],
                            days=int(r["days"])))
    return delinqs


def load_dir(directory):
    accounts = load_accounts(os.path.join(directory, "accounts.tsv"))
    inquiries = load_inquiries(os.path.join(directory, "inquiries.tsv"))
    delinqs = load_delinq(os.path.join(directory, "delinq.tsv"), accounts)
    return accounts, inquiries, delinqs


def clip(items, as_of):
    """event-stream semantics: rows after as-of are the unwritten future —
    excluded, not an error."""
    return [x for x in items if x["date"] <= as_of]


# ---------------------------------------------------------------- the lender's eye

def in_window(d, today, window_days):
    return 0 <= (today - d).days < window_days


def count_hard(inqs, today, window_days):
    return sum(1 for i in inqs if i["hard"] and in_window(i["date"], today, window_days))


def card_utilization(accounts):
    cards = [a for a in accounts if a["type"] == "credit_card"]
    limit = sum(a["limit"] for a in cards)
    balance = sum(a["balance"] for a in cards)
    if limit <= 0:
        return None, None, None, 0
    return balance / limit, balance, limit, len(cards)


def online_debts(accounts):
    """online-lender money still outstanding — the lender column is the claim,
    not the product name: whatever an online platform holds is online debt."""
    return [a for a in accounts
            if a["lender"] == "online" and a["status"] == "active"
            and a["balance"] > 1e-6]


def settled_ghosts(accounts):
    return [a for a in accounts
            if a["lender"] == "online" and a["status"] == "settled"]


def active_loan_lenders(accounts):
    return [a for a in accounts if a["type"] in LOAN_TYPES and a["status"] == "active"]


def fresh_delinqs(delinqs, today, window_days, tier_days=30):
    return [d for d in delinqs
            if d["days"] >= max(30, tier_days)
            and in_window(d["date"], today, window_days)]


def archive_delinqs(delinqs, today, window_days):
    """in the 5-year archive but outside the approval window — disclosure only."""
    out = []
    for d in delinqs:
        if d["days"] < 30 or in_window(d["date"], today, window_days):
            continue
        if (today - d["date"]).days < ARCHIVE_YEARS * 365 + 1:
            out.append(d)
    return out


def evaluate(accounts, inquiries, delinqs, today, L):
    """the lender's-eye reading at `today`. L carries all thresholds.
    returns list of lamp dicts: red lamps gate, yellow lamps only talk."""
    lamps = []
    notes = []

    # -- hard-pull windows (red) --
    for label, key in (("short", "short_days"), ("long", "long_days")):
        n_days = L[key]
        count = count_hard(inquiries, today, n_days)
        line = L[key.replace("days", "line")]
        lamps.append(dict(
            key="HOT-QUERY", window=label, days=n_days, count=count, line=line,
            lit=count > line,
            detail="%d hard pull%s in the last %d days (line %d)"
                   % (count, "" if count == 1 else "s", n_days, line),
            heal=heal_query_day(inquiries, today, n_days, line),
        ))

    # -- online loans (red) --
    debts = online_debts(accounts)
    lamps.append(dict(
        key="ONLINE-DEBT", count=len(debts), line=L["online_line"], lit=len(debts) > L["online_line"],
        detail="%d online loan%s with money outstanding (line %d) — %s"
               % (len(debts), "" if len(debts) == 1 else "s", L["online_line"],
                  ", ".join("%s %s" % (a["name"], money(a["balance"])) for a in debts) or "none"),
        heal=None,  # money, not time
    ))

    # -- utilization (red above util_line, yellow above 50) --
    util, bal, lim, ncards = card_utilization(accounts)
    if util is None:
        lamps.append(dict(key="MAXED", count=0, line=L["util_line"], lit=False,
                          detail="no credit card on file — utilization not judged",
                          heal=None))
    else:
        pct = 100.0 * util
        lamps.append(dict(
            key="MAXED", count=pct, line=L["util_line"], lit=pct > L["util_line"] + 1e-9,
            detail="utilization %.1f%% of %s across %d card%s (line %.0f%%)"
                   % (pct, money(lim), ncards, "" if ncards == 1 else "s", L["util_line"]),
            heal=None,  # money, not time
        ))
        if L["util_line"] >= 50.0 and 50.0 < pct <= L["util_line"] + 1e-9:
            notes.append("🟡 HEAVY-USE — utilization %.1f%% sits in the bank's "
                         "side-eye band (50–%.0f%%)" % (pct, L["util_line"]))

    # -- fresh delinquency (red) --
    fresh = fresh_delinqs(delinqs, today, L["delinq_window"], L["delinq_days"])
    detail = "%d lapse%s of 30+ days in the last %d days" % (
        len(fresh), "" if len(fresh) == 1 else "s", L["delinq_window"])
    for d in fresh:
        detail += "\n    %s  %sd on %s" % (d["account"], d["days"], d["date"])
    lamps.append(dict(
        key="FRESH-DELINQ", count=len(fresh), line=0, lit=bool(fresh),
        days=L["delinq_window"],
        detail=detail,
        heal=heal_delinq_day(delinqs, today, L["delinq_window"], L["delinq_days"]),
    ))

    # -- yellow / disclosure rows --
    ghosts = settled_ghosts(accounts)
    if ghosts:
        notes.append("🟡 SETTLED-GHOST — %d online account%s settled but still on "
                     "file: %s. settled is not gone; ask the platform to close them"
                     % (len(ghosts), "" if len(ghosts) == 1 else "s",
                        ", ".join(a["name"] for a in ghosts)))
    multi = active_loan_lenders(accounts)
    if len(multi) >= 3:
        notes.append("🟡 MULTI-LENDER — %d active loan accounts (%s): three or more "
                     "open debts reads as 'spread thin'" % (len(multi), ", ".join(a["name"] for a in multi)))
    for d in archive_delinqs(delinqs, today, L["delinq_window"]):
        leaves = plus_years(d["date"], ARCHIVE_YEARS)
        notes.append("    on file, outside the window: %sd on %s (%s) — leaves the "
                     "archive %s" % (d["days"], d["date"], d["account"], leaves))

    return lamps, notes


# ---------------------------------------------------------------- healing math (closed-form)

def heal_query_day(inquiries, today, window_days, line):
    """earliest day the window holds <= line hard pulls, by time alone.
    only pulls inside today's window matter: the oldest (count-line) of them
    must age out, so heal = (the excess-th oldest in-window pull) + window."""
    ds = sorted(i["date"] for i in inquiries
                if i["hard"] and in_window(i["date"], today, window_days))
    excess = len(ds) - line
    if excess <= 0:
        return today  # already green
    culprit = ds[excess - 1]
    return max(culprit + timedelta(days=window_days), today)


def heal_delinq_day(delinqs, today, window_days, tier_days):
    """earliest day no in-window lapse of >= tier days remains. the lamp says
    'exists in window', so the window must empty out — and the NEWEST lapse
    leaves last (older ones cross the 730-day line first)."""
    ds = sorted(x["date"] for x in delinqs
                if x["days"] >= max(30, tier_days)
                and in_window(x["date"], today, window_days))
    if not ds:
        return today
    return max(ds[-1] + timedelta(days=window_days), today)


def heal_scan(accounts, inquiries, delinqs, today, L):
    """brute-force replay of the same question, one day at a time — the
    independent path validate/tests use to check the closed form."""
    out = {}
    lamps, _ = evaluate(accounts, inquiries, delinqs, today, L)
    for lamp in lamps:
        if lamp["heal"] is None:
            continue
        if not lamp["lit"]:
            out[(lamp["key"], lamp.get("window"))] = today  # already green
            continue
        found = None
        for step in range(1, CLOCK_HORIZON + 1):
            d = today + timedelta(days=step)
            l2, _ = evaluate(accounts, inquiries, delinqs, d, L)
            twin = next(x for x in l2 if x["key"] == lamp["key"]
                        and x.get("window") == lamp.get("window"))
            if not twin["lit"]:
                found = d
                break
        out[(lamp["key"], lamp.get("window"))] = found
    return out


def todo_list(accounts, L):
    """the money half: what time will never fix."""
    items = []
    for a in online_debts(accounts):
        items.append("settle & close: %s (%s outstanding)" % (a["name"], money(a["balance"])))
    ghosts = settled_ghosts(accounts)
    if ghosts:
        items.append("close on file: %s — settled is not gone" % ", ".join(a["name"] for a in ghosts))
    util, bal, lim, _ = card_utilization(accounts)
    if util is not None and 100.0 * util > L["util_line"] + 1e-9:
        pay80 = max(0, bal - L["util_line"] / 100.0 * lim)
        pay50 = max(0, bal - 0.50 * lim)
        pay30 = max(0, bal - 0.30 * lim)
        items.append("pay down %s to reach %.0f%% utilization (now %.1f%%); %s for 50%%, %s for 30%%"
                     % (money(pay80), L["util_line"], 100.0 * util, money(pay50), money(pay30)))
    return items


# ---------------------------------------------------------------- rendering

def lamps_ok(lamps):
    return not any(l["lit"] for l in lamps)


def render_header(title, directory, as_of, extra=""):
    print("== Lender's Eye · %s ==" % title)
    print("ledger: %s · as-of %s (ledger self-anchored)%s"
          % (os.path.basename(os.path.normpath(directory)), as_of, extra))


def render_lamp(lamp):
    mark = "🔴" if lamp["lit"] else "🟢"
    win = " (%s)" % lamp["window"] if lamp.get("window") else ""
    print("%s %s%s — %s" % (mark, lamp["key"], win, lamp["detail"]))


def render_report(directory, accounts, inquiries, delinqs, as_of, L, clipped_n):
    render_header("as the bank reads it", directory, as_of,
                  " · %d account%s" % (len(accounts), "" if len(accounts) == 1 else "s"))
    print()
    print("-- accounts --  (settled = paid off but still on file)")
    print("%s  %s  %s  %s  %s  %s  %s" % (pad("name", 14), pad("type", 13), pad("opened", 10),
                                          pad("limit", 10), pad("balance", 10),
                                          pad("status", 8), pad("lender", 7)))
    for a in sorted(accounts, key=lambda x: (x["status"] != "active", x["opened"])):
        print("%s  %s  %s  %s  %s  %s  %s" % (
            pad(a["name"], 14), pad(a["type"], 13), pad(str(a["opened"]), 10),
            pad(money(a["limit"]), 10), pad(money(a["balance"]), 10),
            pad(a["status"], 8), pad(a["lender"], 7)))
    outstanding = sum(a["balance"] for a in accounts)
    util, bal, lim, ncards = card_utilization(accounts)
    print("Σ outstanding %s · active %d · settled-on-file %d"
          % (money(outstanding),
             sum(1 for a in accounts if a["status"] == "active"),
             sum(1 for a in accounts if a["status"] == "settled")))
    if util is not None:
        print("credit cards: %s owed of %s across %d card%s = %.1f%% utilization"
              % (money(bal), money(lim), ncards, "" if ncards == 1 else "s", 100 * util))

    print()
    print("-- hard pulls --  (each one was pressed by your own hand)")
    hard = sorted((i for i in inquiries if i["hard"]), key=lambda x: x["date"])
    soft = [i for i in inquiries if not i["hard"]]
    for i in hard:
        mark = "in 183d" if in_window(i["date"], as_of, L["long_days"]) else "rolled"
        mark2 = "in %dd" % L["short_days"] if in_window(i["date"], as_of, L["short_days"]) else ""
        print("  %s  %s  %s  %s %s" % (pad(str(i["date"]), 10), pad(i["agency"], 16),
                                       pad(i["reason"], 14), mark, mark2))
    if not hard and not soft:
        print("  no agency pull on record")
    if soft:
        print("  (%d soft pull%s not counted: %s)"
              % (len(soft), "" if len(soft) == 1 else "s",
                 ", ".join(i["reason"] for i in soft)))
    if clipped_n:
        print("  (%d row%s after as-of excluded — the unwritten future)"
              % (clipped_n, "" if clipped_n == 1 else "s"))

    print()
    print("-- the bank's read --")
    lamps, notes = evaluate(accounts, inquiries, delinqs, as_of, L)
    for lamp in lamps:
        render_lamp(lamp)
    for n in notes:
        print(n)
    if lamps_ok(lamps) and not notes:
        print("nothing on this archive smells of risk — as far as these windows can see")
    return lamps, notes


def render_gate(directory, accounts, inquiries, delinqs, as_of, apply_date, product, L):
    render_header("gate · %s" % product, directory, as_of,
                  " · apply-date %s (windows roll to that day)" % apply_date)
    print()
    lamps, notes = evaluate(accounts, inquiries, delinqs, apply_date, L)
    for lamp in lamps:
        verdict = "FAIL" if lamp["lit"] else "PASS"
        win = " (%s)" % lamp["window"] if lamp.get("window") else ""
        print("%s %s%s — %s" % (verdict, lamp["key"], win, lamp["detail"]))
    for n in notes:
        print(n)
    fails = [l for l in lamps if l["lit"]]
    print()
    if fails:
        print("✗ %s — %d lamp%s lit as of %s. the bank's usual translation: "
              "comprehensive score insufficient."
              % (product, len(fails), "" if len(fails) == 1 else "s", apply_date))
        items = todo_list(accounts, L)
        if items:
            print("what time will not fix:")
            for it in items:
                print("  - %s" % it)
        timed = [l for l in fails if l["heal"] is not None]
        if timed:
            print("what time alone will fix (see clock): %s"
                  % ", ".join(l["key"] + ("/" + l["window"] if l.get("window") else "") for l in timed))
        return EXIT_ALARM
    print("✓ %s — nothing on this archive trips the common-sense lines as of %s."
          % (product, apply_date))
    print("  approval is still a black box (income, flows, the property itself);")
    print("  this gate only says the archive side is quiet.")
    return EXIT_OK


def render_clock(directory, accounts, inquiries, delinqs, as_of, L):
    render_header("healing calendar", directory, as_of,
                  " · horizon %d days" % CLOCK_HORIZON)
    print()
    print("time can heal three of these lamps; money must heal the rest.")
    print()
    lamps, _ = evaluate(accounts, inquiries, delinqs, as_of, L)
    timed = [l for l in lamps if l["heal"] is not None]
    latest = as_of
    any_timed_red = False
    for lamp in timed:
        if not lamp["lit"]:
            print("🟢 %s%s — already quiet (line %s)"
                  % (lamp["key"], " (%s)" % lamp["window"] if lamp.get("window") else "", lamp["line"]))
            continue
        any_timed_red = True
        heal = lamp["heal"]
        latest = max(latest, heal)
        if lamp["key"] == "HOT-QUERY":
            n_out = lamp["count"] - lamp["line"]
            why = "the oldest %d pull%s age%s out of the %dd window" % (
                n_out, "" if n_out == 1 else "s",
                "s" if n_out == 1 else "", lamp["days"])
        else:
            why = "the newest 30+ day lapse leaves the %dd window (older ones left first)" % lamp["days"]
        print("⏳ %s%s — heals on %s: %s"
              % (lamp["key"], " (%s)" % lamp["window"] if lamp.get("window") else "", heal, why))
    if not timed or not any_timed_red:
        print("(no time-healable lamp is lit)")
    if any_timed_red:
        print()
        print("time-only all-clear: %s — after that day, every window is quiet on its own."
              % latest)
    items = todo_list(accounts, L)
    print()
    if items:
        print("-- to-do (money, not time) --")
        for it in items:
            print("  - %s" % it)
        print("none of the above heals by itself.")
    else:
        print("no money lamp is lit — time is the only creditor left.")
    return EXIT_OK


def render_validate(directory, accounts, inquiries, delinqs):
    print("== Lender's Eye · ledger audit ==")
    print("ledger: %s" % os.path.basename(os.path.normpath(directory)))
    # identity 1: outstanding balance, two paths
    direct = sum(a["balance"] for a in accounts)
    grouped = sum(sum(a["balance"] for a in accounts if a["type"] == t) for t in ACCOUNT_TYPES)
    assert abs(direct - grouped) < 1e-6, (direct, grouped)
    # identity 2: hard pulls inside every window, two paths
    all_dates = [i["date"] for i in inquiries if i["hard"]]
    for today in sorted({i["date"] for i in inquiries} | {a["opened"] for a in accounts})[-1:]:
        linear = sum(1 for d in all_dates if 0 <= (today - d).days < DEFAULT_LONG_DAYS)
        srt = sorted(all_dates, reverse=True)
        cursor = 0
        while cursor < len(srt) and (today - srt[cursor]).days >= DEFAULT_LONG_DAYS:
            cursor += 1
        cursor_end = cursor
        while cursor_end < len(srt) and (today - srt[cursor_end]).days >= 0:
            cursor_end += 1
        assert linear == cursor_end - cursor, (linear, cursor_end - cursor)
    # identity 3: every delinquency maps to a live account (load already enforces;
    # re-check independently by name set)
    names = {a["name"] for a in accounts}
    for d in delinqs:
        assert d["account"] in names
    # identity 4: status x balance matrix
    for a in accounts:
        if a["status"] in ("settled", "closed"):
            assert a["balance"] <= 1e-6
    print("accounts: %d · Σ outstanding %s = Σ by type %s"
          % (len(accounts), money(direct), money(grouped)))
    print("inquiries: %d (%d hard / %d soft)"
          % (len(inquiries), sum(1 for i in inquiries if i["hard"]),
             sum(1 for i in inquiries if not i["hard"])))
    print("delinquencies: %d (all reference live accounts)"
          % len(delinqs))
    print("ledger is sound")
    return EXIT_OK


# ---------------------------------------------------------------- commands

def prepare(args):
    accounts, inquiries, delinqs = load_dir(args.dir)
    every_date = ([a["opened"] for a in accounts]
                  + [i["date"] for i in inquiries]
                  + [d["date"] for d in delinqs])
    if not every_date:
        raise EmptyLedger("no dated row anywhere in %s" % args.dir)
    as_of = strict_date(args.as_of, "--as-of") if args.as_of else max(every_date)
    n_after = (sum(1 for a in accounts if a["opened"] > as_of)
               + sum(1 for i in inquiries if i["date"] > as_of)
               + sum(1 for d in delinqs if d["date"] > as_of))
    accounts = clip(accounts, as_of, key="opened")
    inquiries = clip(inquiries, as_of)
    delinqs = clip(delinqs, as_of)
    if not accounts:
        raise EmptyLedger("no account exists on or before --as-of %s — the "
                          "archive had not started yet" % as_of)
    return accounts, inquiries, delinqs, as_of, n_after


def clip(items, as_of, key="date"):
    return [x for x in items if x[key] <= as_of]


def resolve_lines(args):
    L = dict(DEFAULTS)
    L["short_days"] = args.hq_short_days
    L["long_days"] = args.hq_long_days
    L["delinq_window"] = args.delinq_window
    if getattr(args, "product", None) and args.product in PRODUCTS:
        L.update(PRODUCTS[args.product])
    for key in ("short_line", "long_line", "online_line", "util_line", "delinq_days"):
        v = getattr(args, key, None)
        if v is not None:
            L[key] = v
    return L


def cmd_report(args):
    accounts, inquiries, delinqs, as_of, n_after = prepare(args)
    L = resolve_lines(args)
    lamps, _ = render_report(args.dir, accounts, inquiries, delinqs, as_of, L, n_after)
    return EXIT_ALARM if not lamps_ok(lamps) else EXIT_OK


def cmd_gate(args):
    accounts, inquiries, delinqs, as_of, n_after = prepare(args)
    L = resolve_lines(args)
    apply_date = strict_date(args.apply_date, "--apply-date") if args.apply_date else as_of
    # windows roll to the apply-date: anything after that day is not yet seen
    accounts = clip(accounts, apply_date, key="opened")
    inquiries = clip(inquiries, apply_date)
    delinqs = clip(delinqs, apply_date)
    if not accounts:
        raise EmptyLedger("no account exists on or before --apply-date %s" % apply_date)
    return render_gate(args.dir, accounts, inquiries, delinqs, as_of,
                       apply_date, args.product, L)


def cmd_clock(args):
    accounts, inquiries, delinqs, as_of, n_after = prepare(args)
    L = resolve_lines(args)
    return render_clock(args.dir, accounts, inquiries, delinqs, as_of, L)


def cmd_validate(args):
    accounts, inquiries, delinqs = load_dir(args.dir)
    return render_validate(args.dir, accounts, inquiries, delinqs)


def build_parser():
    p = argparse.ArgumentParser(
        prog="lenders_eye.py",
        description="银行眼 · Lender's Eye — translate your credit file from "
                    "statement-speak into approval-speak: hard-pull windows, "
                    "online-loan ghosts, utilization, and what time can still heal.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--dir", default=".", metavar="DIR",
                        help="ledger directory holding accounts.tsv / inquiries.tsv / delinq.tsv")
        sp.add_argument("--as-of", dest="as_of", default=None,
                        help="replay the archive as of YYYY-MM-DD (default: latest date on file)")
        sp.add_argument("--hq-short-days", type=int, default=DEFAULT_SHORT_DAYS,
                        help="short hard-pull window in days (default 61)")
        sp.add_argument("--hq-long-days", type=int, default=DEFAULT_LONG_DAYS,
                        help="long hard-pull window in days (default 183)")
        sp.add_argument("--short-line", type=int, default=None,
                        help="alarm when short-window hard pulls exceed N")
        sp.add_argument("--long-line", type=int, default=None,
                        help="alarm when long-window hard pulls exceed N")
        sp.add_argument("--online-line", type=int, default=None,
                        help="alarm when outstanding online loans exceed N")
        sp.add_argument("--util-line", type=float, default=None,
                        help="alarm when card utilization exceeds N%%")
        sp.add_argument("--delinq-window", type=int, default=DEFAULT_DELINQ_WINDOW,
                        help="fresh-delinquency window in days (default 730)")
        sp.add_argument("--delinq-days", type=int, default=None,
                        help="alarm when a lapse of >= N days sits in the window")

    common(sub.add_parser("report", help="the bank's-eye snapshot of your archive"))
    g = sub.add_parser("gate", help="would this archive pass on --apply-date, for --product?")
    common(g)
    g.add_argument("--product", choices=sorted(PRODUCTS), default="mortgage",
                   help="which approval lens to borrow (default mortgage)")
    g.add_argument("--apply-date", dest="apply_date", default=None,
                   help="assume you apply on YYYY-MM-DD (default: as-of)")
    common(sub.add_parser("clock", help="what time heals, and the to-do list it never will"))
    common(sub.add_parser("validate", help="ledger health + identity checks"))
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {"report": cmd_report, "gate": cmd_gate,
                "clock": cmd_clock, "validate": cmd_validate}
    try:
        return handlers[args.cmd](args)
    except LedgerError as exc:
        sys.stderr.write("lenders-eye: broken ledger: %s\n" % exc)
        return EXIT_BROKEN
    except EmptyLedger as exc:
        sys.stderr.write("lenders-eye: %s\n" % exc)
        return EXIT_DECLINE


if __name__ == "__main__":
    sys.exit(main())
