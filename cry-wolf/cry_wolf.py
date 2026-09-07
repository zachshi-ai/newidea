#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cry-wolf · 虚惊 / 灾难想象对账账本。

担忧是想象力的副作用:它只在脑内播放、从不对账。同一主题的灾难想象月月
重播,每一次都像头一次一样真实——因为从没有人记得它上几次的检验结果。
「90% 的担心不会发生」是鸡汤统计,不是你的统计;警报响的时候永远像第一次。

本件把每场担忧抄成一行可检验的预测(fear 行: 内容/检验日/熬夜数),到期
回来对账(check 行: hit / partial / miss),把同主题的重播串成链:

  alarm record  个人警报器的误报率——你写下的灾难,几件真的发生了
  wolf chains   重播惯犯链 + 每次重播入账时点的既有战绩(狼来了的数位版)
  nights bill   为没发生的狼熬的夜 vs 为真火熬的夜——虚惊第一次有了价格

诚实条款:本件不诊断焦虑、不做治疗建议,红灯文案永远指向专业帮助;狼链
3:0 降低的是先验,不是免检通行证——真实的危险警报仍然值得真实的检查。
账本只存本地、零墙钟(as-of 缺省 = 账本最大日期),同一本账任何机器任何
一天跑出的结果逐字节一致。

账本 TSV,8 列: date/type/topic/fear/due/nights/ref/outcome
  fear 行  date topic fear due [nights]   —— 入账一场担忧;due 空 = open-ended
  check 行 date ref  outcome             —— 到期结案: hit | partial | miss
ref 是 fear 行的物理行号(1-based, 含表头与注释行, 编辑器可直达)。
规则: 一场担忧只结案一次(同主题再来 = 新一场, 重播链负责点名)。

命令: report / wolves / due / validate
退出码: 0 绿 · 2 账坏 · 3 空账或薄账拒判 · 4 账面红灯
"""

import argparse
import os
import re
import sys
from datetime import datetime

COLS = ("date", "type", "topic", "fear", "due", "nights", "ref", "outcome")
TYPE_ALIASES = {
    "fear": "fear", "f": "fear", "worry": "fear",
    "check": "check", "c": "check", "resolved": "check", "verdict": "check",
}
OUTCOME_ALIASES = {
    "hit": "hit", "true": "hit", "happened": "hit",
    "partial": "partial", "half": "partial",
    "miss": "miss", "false": "miss", "no": "miss",
}
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

EXIT_OK, EXIT_BROKEN, EXIT_DECLINE, EXIT_ALARM = 0, 2, 3, 4
THIN_CHECKED = 5          # fewer checked fears than this -> refuse the alarm-rate verdict
WOLF_MIN = 3              # a chain needs this many checked fears before it can be a wolf
OVERDUE_LOUD_DAYS = 30    # a verdict this late is systemic self-deception -> alarm
OPENENDED_LOUD_N = 5      # this many undated worries -> alarm

WOLF_VERDICT = (
    "🔴 WOLF — this alarm has cried {n} times and the wolf never came once.\n"
    "  history lowers the prior, it does not close the ward: the next real\n"
    "  danger still deserves a real check. what the chain retires is the replay,\n"
    "  not the vigilance."
)


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


# ---------------------------------------------------------------- parsing

def strict_date(s, where):
    if not DATE_RE.fullmatch(s):
        raise LedgerError("%s: bad date '%s' (want YYYY-MM-DD, zero-padded)" % (where, s))
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise LedgerError("%s: impossible calendar date '%s'" % (where, s))


def load(path):
    """parse + validate the whole ledger. broken is broken even under --as-of."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raise EmptyLedger("no ledger at '%s' yet — start one: a header line, "
                          "then one fear row per worry" % path)
    except OSError as exc:
        raise LedgerError("cannot read ledger: %s" % exc)
    if not raw.strip():
        raise EmptyLedger("ledger is empty")

    fears, checks = [], []
    header_seen = False
    for i, line in enumerate(raw.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        while len(cells) > len(COLS) and cells[-1] == "":
            cells.pop()  # trailing tabs come free with hand-pasted spreadsheets
        where = "line %d" % i
        if not header_seen:
            header_seen = True
            if tuple(c.strip().lower() for c in cells) != COLS:
                raise LedgerError("%s: bad header, want %s" % (where, "/".join(COLS)))
            continue
        if len(cells) != len(COLS):
            raise LedgerError("%s: want %d tab-separated fields, got %d"
                              % (where, len(COLS), len(cells)))
        cells = [c.strip() for c in cells]
        date_s, type_s, topic, fear, due_s, nights_s, ref_s, outcome_s = cells
        d = strict_date(date_s, where)
        kind = TYPE_ALIASES.get(type_s.lower())
        if kind is None:
            raise LedgerError("%s: unknown type '%s' (fear|check)" % (where, type_s))
        if kind == "fear":
            if not topic:
                raise LedgerError("%s: fear row needs a topic" % where)
            if not fear:
                raise LedgerError("%s: fear row needs the feared outcome" % where)
            due = strict_date(due_s, where + " (due)") if due_s else None
            nights = 0
            if nights_s:
                if not re.fullmatch(r"\d+", nights_s):
                    raise LedgerError("%s: nights must be a non-negative integer, got '%s'"
                                      % (where, nights_s))
                nights = int(nights_s)
            fears.append(dict(line=i, date=d, topic=topic, fear=fear,
                              due=due, nights=nights, check=None, nights_unrecorded=not nights_s))
        else:
            if not ref_s or not re.fullmatch(r"\d+", ref_s):
                raise LedgerError("%s: check row needs an integer ref (physical line of its fear)" % where)
            outcome = OUTCOME_ALIASES.get(outcome_s.lower())
            if outcome is None:
                raise LedgerError("%s: unknown outcome '%s' (hit|partial|miss)" % (where, outcome_s))
            checks.append(dict(line=i, date=d, ref=int(ref_s), outcome=outcome))

    if not header_seen:
        raise EmptyLedger("ledger has no header row")
    if not fears and not checks:
        raise EmptyLedger("ledger has a header but no rows")

    by_line = {f["line"]: f for f in fears}
    for c in checks:
        f = by_line.get(c["ref"])
        if f is None:
            raise LedgerError("line %d: ref %d does not point at a fear row" % (c["line"], c["ref"]))
        if f["check"] is not None:
            raise LedgerError("line %d: fear at line %d was already checked at line %d"
                              % (c["line"], c["ref"], f["check"]["line"]))
        if c["date"] < f["date"]:
            raise LedgerError("line %d: verdict %s predates its fear %s"
                              % (c["line"], c["date"], f["date"]))
        f["check"] = c
    return fears


def apply_alias(fears, pairs):
    mapping = {}
    for p in pairs:
        if "=" not in p:
            raise LedgerError("bad --alias '%s' (want FROM=TO, e.g. 娃咳嗽=孩子健康)" % p)
        src, dst = p.split("=", 1)
        src, dst = src.strip(), dst.strip()
        if not src or not dst:
            raise LedgerError("bad --alias '%s' (want FROM=TO, e.g. 娃咳嗽=孩子健康)" % p)
        mapping[src] = dst
    for f in fears:
        f["topic"] = mapping.get(f["topic"], f["topic"])


def as_of_default(fears):
    latest = max(f["date"] for f in fears)
    for f in fears:
        if f["check"] is not None:
            latest = max(latest, f["check"]["date"])
    return latest


def clip(fears, as_of):
    """replay semantics: rows after as-of are excluded, not an error."""
    views = []
    for f in fears:
        if f["date"] > as_of:
            continue
        g = dict(f)
        if g["check"] is not None and g["check"]["date"] > as_of:
            g["check"] = None
        views.append(g)
    if not views:
        raise EmptyLedger("nothing on or before --as-of %s" % as_of)
    return views


# ---------------------------------------------------------------- aggregation

def audit(views, as_of):
    aud = {
        "as_of": as_of,
        "fears": len(views),
        "checked": [f for f in views if f["check"] is not None],
        "unchecked": [f for f in views if f["check"] is None],
    }
    aud["n_checked"] = len(aud["checked"])
    aud["n_hit"] = sum(1 for f in aud["checked"] if f["check"]["outcome"] == "hit")
    aud["n_partial"] = sum(1 for f in aud["checked"] if f["check"]["outcome"] == "partial")
    aud["n_miss"] = sum(1 for f in aud["checked"] if f["check"]["outcome"] == "miss")

    overdue, openended, clock = [], [], []
    for f in aud["unchecked"]:
        if f["due"] is None:
            openended.append(f)
        elif f["due"] < as_of:
            overdue.append((f, (as_of - f["due"]).days))
        else:
            clock.append((f, (f["due"] - as_of).days))
    aud["overdue"], aud["openended"], aud["clock"] = overdue, openended, clock

    aud["nights_wolf"] = sum(f["nights"] for f in aud["checked"] if f["check"]["outcome"] == "miss")
    aud["nights_half"] = sum(f["nights"] for f in aud["checked"] if f["check"]["outcome"] == "partial")
    aud["nights_fire"] = sum(f["nights"] for f in aud["checked"] if f["check"]["outcome"] == "hit")
    aud["nights_open"] = sum(f["nights"] for f in aud["unchecked"])
    aud["nights_unrecorded"] = sum(1 for f in views if f["nights_unrecorded"])

    aud["chains"] = chains(views)
    aud["wolves"] = [c for c in aud["chains"]
                     if c["n_checked"] >= WOLF_MIN and c["n_hit"] == 0 and c["n_partial"] == 0]
    aud["overdue_loud"] = any(days > OVERDUE_LOUD_DAYS for _, days in aud["overdue"])
    aud["openended_loud"] = len(aud["openended"]) >= OPENENDED_LOUD_N
    aud["alarm"] = bool(aud["wolves"] or aud["overdue_loud"] or aud["openended_loud"])
    return aud


def chains(views):
    """one row per topic: filed/checked counts, H/P/M record, and for every
    filing the record this topic already held at that moment."""
    out = []
    for topic in sorted({f["topic"] for f in views}):
        rows = sorted([f for f in views if f["topic"] == topic], key=lambda f: (f["date"], f["line"]))
        seen = []  # earlier filings in this chain, in filing order
        items = []
        for k, f in enumerate(rows, start=1):
            prior = [g for g in seen if g["check"] is not None and g["check"]["date"] <= f["date"]]
            rec = (sum(1 for g in prior if g["check"]["outcome"] == "hit"),
                   sum(1 for g in prior if g["check"]["outcome"] == "partial"),
                   sum(1 for g in prior if g["check"]["outcome"] == "miss"))
            items.append(dict(f=f, k=k, record=rec))
            seen.append(f)
        n_checked = sum(1 for f in rows if f["check"] is not None)
        n_hit = sum(1 for f in rows if f["check"] and f["check"]["outcome"] == "hit")
        n_partial = sum(1 for f in rows if f["check"] and f["check"]["outcome"] == "partial")
        n_miss = sum(1 for f in rows if f["check"] and f["check"]["outcome"] == "miss")
        out.append(dict(topic=topic, rows=rows, items=items, n_filed=len(rows),
                        n_checked=n_checked, n_hit=n_hit, n_partial=n_partial, n_miss=n_miss))
    return out


# ---------------------------------------------------------------- rendering

FEAR_W, TOPIC_W = 46, 14


def fear_cell(f):
    return pad(f["fear"], FEAR_W)


def outcome_tag(f):
    return {"hit": "HIT", "partial": "HALF", "miss": "MISS"}[f["check"]["outcome"]]


def fmt_record(rec):
    return "%dH/%dP/%dM" % rec


def render_header(title, path, aud):
    print("== Cry Wolf · %s ==" % title)
    print("ledger: %s · %d fears · as-of %s (ledger self-anchored)"
          % (os.path.basename(path), aud["fears"], aud["as_of"]))


def render_ledger_block(aud):
    print()
    print("-- outcome ledger --")
    print("checked %d = hit %d + partial %d + miss %d        identity OK"
          % (aud["n_checked"], aud["n_hit"], aud["n_partial"], aud["n_miss"]))
    print("unchecked %d = overdue %d · open-ended %d · on the clock %d"
          % (len(aud["unchecked"]), len(aud["overdue"]),
             len(aud["openended"]), len(aud["clock"])))


def render_alarm_record(aud):
    print()
    print("-- alarm record (checked fears only) --")
    n = aud["n_checked"]
    if n < THIN_CHECKED:
        print("DECLINE: only %d fear%s checked so far — under %d a verdict would be\n"
              "your alarm's mood, not its character. the case lights above still\n"
              "stand; come back after %d verdicts."
              % (n, "" if n == 1 else "s", THIN_CHECKED, THIN_CHECKED))
    else:
        print("false alarms: %d/%d (%.1f%%) never happened"
              % (aud["n_miss"], n, 100.0 * aud["n_miss"] / n))
        print("counting half-hits as not-fully-true: %d/%d (%.1f%%)"
              % (aud["n_miss"] + aud["n_partial"], n,
                 100.0 * (aud["n_miss"] + aud["n_partial"]) / n))
    total = aud["nights_wolf"] + aud["nights_half"] + aud["nights_fire"] + aud["nights_open"]
    print("nights: %d total = %d for wolves that never came · %d for half-wolves\n"
          "        · %d for real fires · %d still on unchecked fears"
          % (total, aud["nights_wolf"], aud["nights_half"],
             aud["nights_fire"], aud["nights_open"]))
    if aud["nights_unrecorded"]:
        print("nights not recorded on %d fear%s, counted as 0"
              % (aud["nights_unrecorded"], "" if aud["nights_unrecorded"] == 1 else "s"))


def render_cases(aud):
    fires = [f for f in aud["checked"] if f["check"]["outcome"] in ("hit", "partial")]
    misses = [f for f in aud["checked"] if f["check"]["outcome"] == "miss"]
    for title, rows, tag in (("real fires (the alarm was right)", fires, True),
                             ("wolves that never came", misses, False)):
        print()
        print("-- %s --" % title)
        if not rows:
            print("(none)" if tag else "(none yet — even a broken alarm is right sometimes)")
        for f in sorted(rows, key=lambda f: (f["date"], f["line"])):
            rec = None
            for c in aud["chains"]:
                if c["topic"] != f["topic"]:
                    continue
                for it in c["items"]:
                    if it["f"] is f:
                        rec = it["record"]
            print("#%-3d %s  %s  %s  %-7s nights %d  (chain at filing %s)"
                  % (f["line"], f["date"], pad(f["topic"], TOPIC_W),
                     fear_cell(f), outcome_tag(f), f["nights"], fmt_record(rec)))

    print()
    print("-- unchecked: OVERDUE-CHECK (a verdict past due — the loop keeps replaying) --")
    if not aud["overdue"]:
        print("(none)")
    for f, days in sorted(aud["overdue"], key=lambda t: (-t[1], t[0]["line"])):
        print("#%-3d %s  %s  %s  due %s  %dd overdue  nights %d"
              % (f["line"], f["date"], pad(f["topic"], TOPIC_W), fear_cell(f),
                 f["due"], days, f["nights"]))

    print()
    print("-- unchecked: OPEN-ENDED (a worry with no test date is a loop with no exit) --")
    if not aud["openended"]:
        print("(none)")
    for f in sorted(aud["openended"], key=lambda f: (f["date"], f["line"])):
        print("#%-3d %s  %s  %s  no due date  open %dd  nights %d"
              % (f["line"], f["date"], pad(f["topic"], TOPIC_W), fear_cell(f),
                 (aud["as_of"] - f["date"]).days, f["nights"]))

    print()
    print("-- unchecked: on the clock (not yet due — let it play out) --")
    if not aud["clock"]:
        print("(none)")
    for f, days in sorted(aud["clock"], key=lambda t: (t[1], t[0]["line"])):
        print("#%-3d %s  %s  %s  due %s  %dd left  nights %d"
              % (f["line"], f["date"], pad(f["topic"], TOPIC_W), fear_cell(f),
                 f["due"], days, f["nights"]))


def render_gates(aud):
    print()
    print("-- gates --")
    if aud["wolves"]:
        for c in aud["wolves"]:
            print(WOLF_VERDICT.format(n=c["n_checked"]))
            print("  chain: %s — %d checked, record %dH/%dP/%dM"
                  % (c["topic"], c["n_checked"], c["n_hit"], c["n_partial"], c["n_miss"]))
    else:
        print("WOLF: no chain (needs >=%d checked filings, all miss)" % WOLF_MIN)
    monitors = [c for c in aud["chains"]
                if c["n_checked"] >= 2 and c["n_hit"] == 0 and c["n_partial"] == 0
                and c not in aud["wolves"]]
    for c in monitors:
        print("monitor: %s — %d checks, no hit yet (quiet until %d)" % (c["topic"], c["n_checked"], WOLF_MIN))
    if aud["overdue"]:
        oldest = max(days for _, days in aud["overdue"])
        note = "SYSTEMIC — verdicts >%dd old" % OVERDUE_LOUD_DAYS if aud["overdue_loud"] \
            else "silent until a verdict is %dd late" % OVERDUE_LOUD_DAYS
        print("OVERDUE-CHECK: %d case%s, oldest %dd (%s)"
              % (len(aud["overdue"]), "" if len(aud["overdue"]) == 1 else "s", oldest, note))
    else:
        print("OVERDUE-CHECK: none")
    if aud["openended"]:
        note = "ALARM — %d+ undated worries" % OPENENDED_LOUD_N if aud["openended_loud"] \
            else "silent until %d undated worries" % OPENENDED_LOUD_N
        print("OPEN-ENDED: %d case%s (%s)"
              % (len(aud["openended"]), "" if len(aud["openended"]) == 1 else "s", note))
    else:
        print("OPEN-ENDED: none")


def render_report(path, aud):
    render_header("worry-outcome audit", path, aud)
    render_ledger_block(aud)
    render_alarm_record(aud)
    render_cases(aud)
    render_gates(aud)


def render_wolves(path, aud):
    render_header("repeat-offender chains", path, aud)
    print()
    live = [c for c in aud["chains"] if c["n_filed"] >= 2]
    if not live:
        print("no chain yet — a topic becomes a chain at its 2nd filing.")
        return
    print("a chain is the same topic filing again. the (record at filing) column\n"
          "is what this topic already knew when the fear came back — and you\n"
          "filed it anyway. that is what a replay is.")
    for c in sorted(live, key=lambda c: (-c["n_filed"], c["topic"])):
        print()
        is_wolf = c in aud["wolves"]
        verdict = "🔴 WOLF" if is_wolf else ("▲ monitor" if (c["n_checked"] >= 2 and c["n_hit"] == 0 and c["n_partial"] == 0) else "○")
        print("%s  %s   filed %d · checked %d · record %s"
              % (verdict, c["topic"], c["n_filed"], c["n_checked"],
                 fmt_record((c["n_hit"], c["n_partial"], c["n_miss"]))))
        for it in c["items"]:
            f = it["f"]
            if f["check"] is not None:
                state = "checked %s %s" % (f["check"]["date"], outcome_tag(f))
            elif f["due"] is None:
                state = "open-ended"
            elif f["due"] < aud["as_of"]:
                state = "OVERDUE since %s" % f["due"]
            else:
                state = "on the clock, due %s" % f["due"]
            print("  #%-3d %s  %s  %s  nights %d"
                  % (f["line"], f["date"], pad(state, 30), fmt_record(it["record"]), f["nights"]))
        if is_wolf:
            print(WOLF_VERDICT.format(n=c["n_checked"]))


def render_due(path, aud):
    render_header("check-up docket", path, aud)
    waiting = len(aud["overdue"]) + len(aud["clock"]) + len(aud["openended"])
    print()
    if not waiting:
        print("nothing awaiting a verdict — every filed fear has its date in front\n"
              "of it. file the next one when the alarm rings.")
        return
    print("%d fear%s awaiting their verdict. a verdict you keep not writing is a\n"
          "loop your brain keeps replaying." % (waiting, "" if waiting == 1 else "s"))
    if aud["overdue"]:
        print()
        print("OVERDUE (past the date you promised yourself):")
        for f, days in sorted(aud["overdue"], key=lambda t: (-t[1], t[0]["line"])):
            print("  #%-3d due %s  %3dd overdue  %s  %s"
                  % (f["line"], f["due"], days, pad(f["topic"], TOPIC_W), fear_cell(f)))
    if aud["clock"]:
        print()
        print("ON THE CLOCK:")
        for f, days in sorted(aud["clock"], key=lambda t: (t[1], t[0]["line"])):
            print("  #%-3d due %s  %3dd left    %s  %s"
                  % (f["line"], f["due"], days, pad(f["topic"], TOPIC_W), fear_cell(f)))
    if aud["openended"]:
        print()
        print("NO DATE AT ALL (give it one — even a generous one):")
        for f in sorted(aud["openended"], key=lambda f: (f["date"], f["line"])):
            print("  #%-3d filed %s  %s  %s"
                  % (f["line"], f["date"], pad(f["topic"], TOPIC_W), fear_cell(f)))


def render_validate(path, fears):
    print("== Cry Wolf · ledger audit ==")
    print("ledger: %s" % os.path.basename(path))
    n_fear = len(fears)
    n_check = sum(1 for f in fears if f["check"] is not None)
    unresolved = sum(1 for f in fears if f["check"] is None)
    print("rows: %d fear + %d check · refs resolve %d/%d · %d fear(s) still open"
          % (n_fear, n_check, n_check, n_check, unresolved))

    # identity, recomputed through an independent path
    buckets = {"hit": 0, "partial": 0, "miss": 0}
    nights = {"wolf": 0, "half": 0, "fire": 0, "open": 0}
    for f in fears:
        if f["check"] is None:
            nights["open"] += f["nights"]
            continue
        outcome = f["check"]["outcome"]
        buckets[outcome] += 1
        nights[{"miss": "wolf", "partial": "half", "hit": "fire"}[outcome]] += f["nights"]
    total = buckets["hit"] + buckets["partial"] + buckets["miss"]
    assert total == n_check
    nights_total = sum(f["nights"] for f in fears)
    assert nights_total == sum(nights.values())
    print("identity: checked = hit %d + partial %d + miss %d = %d" % (buckets["hit"], buckets["partial"], buckets["miss"], total))
    print("nights:   %d total = wolves %d + half %d + fires %d + unchecked %d"
          % (nights_total, nights["wolf"], nights["half"], nights["fire"], nights["open"]))
    print("ledger is sound")


# ---------------------------------------------------------------- commands

def prepare(args):
    fears = load(args.ledger)
    if getattr(args, "alias", None):
        apply_alias(fears, args.alias)
    if args.as_of:
        as_of = strict_date(args.as_of, "--as-of")
    else:
        as_of = as_of_default(fears)
    views = clip(fears, as_of)
    return fears, views, audit(views, as_of)


def cmd_report(args):
    _, _, aud = prepare(args)
    render_report(args.ledger, aud)
    if aud["alarm"]:
        return EXIT_ALARM
    if aud["n_checked"] < THIN_CHECKED:
        return EXIT_DECLINE
    return EXIT_OK


def cmd_wolves(args):
    _, _, aud = prepare(args)
    render_wolves(args.ledger, aud)
    return EXIT_ALARM if aud["wolves"] else EXIT_OK


def cmd_due(args):
    _, _, aud = prepare(args)
    render_due(args.ledger, aud)
    return EXIT_OK


def cmd_validate(args):
    fears = load(args.ledger)
    render_validate(args.ledger, fears)
    return EXIT_OK


def build_parser():
    p = argparse.ArgumentParser(
        prog="cry_wolf.py",
        description="cry-wolf · 虚惊 — audit your brain's false alarms: file each worry "
                    "as a testable fear, come back on the due date, settle it hit/partial/miss.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, alias=True):
        sp.add_argument("--ledger", default="worries.tsv", help="ledger TSV path")
        sp.add_argument("--as-of", dest="as_of", default=None,
                        help="replay the ledger as of YYYY-MM-DD (default: ledger's own last date)")
        if alias:
            sp.add_argument("--alias", action="append", default=[], metavar="FROM=TO",
                            help="normalize a topic into a chain (repeatable)")

    common(sub.add_parser("report", help="full audit: alarm record, nights bill, case lights"))
    common(sub.add_parser("wolves", help="repeat-offender chains with at-filing records"))
    common(sub.add_parser("due", help="the docket: verdicts you owe yourself"))
    common(sub.add_parser("validate", help="ledger health + identity checks"), alias=False)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {"report": cmd_report, "wolves": cmd_wolves, "due": cmd_due, "validate": cmd_validate}
    try:
        return handlers[args.cmd](args)
    except LedgerError as exc:
        sys.stderr.write("cry-wolf: broken ledger: %s\n" % exc)
        return EXIT_BROKEN
    except EmptyLedger as exc:
        sys.stderr.write("cry-wolf: %s\n" % exc)
        return EXIT_DECLINE


if __name__ == "__main__":
    sys.exit(main())
