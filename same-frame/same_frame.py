#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同框 · Same Frame / 家庭同框间隔账本。

日历记你要去哪,相册记你拍过什么——没有任何一本账记录「全到齐」这件事
的间隔。缺席是渐进的:先缺席聚会,再缺席照片,最后只剩空位;人眼对月尺度
的渐进彻底失明,「下次再拍」的下次从不来。爷爷的照片越来越少,而没有人说
得出「上一张有他的照片是哪天」。

本件把每次聚齐抄成一行可手编的事件(日期/场合/在场成员),从同一本账开出
三本账:

  full house  全体同框的次数与间隔——「全家到齐已经 698 天」
  members     每个人的在场率、上次在场、缺席 streak——谁正从账本里退出去
  pairs       成对同框矩阵——「你和小妹同框只有 2 次,上次还是三年前」

账本不预测寿命、不数「还能同框几次」——那是算命加卖焦虑;它只数已经空了
多久。缺席的原因千种(穷/忙/病/远/怨),账本只记事实不归因;修复永远是
人的决定。

账本 TSV,3 列: date/event/who
  date  YYYY-MM-DD(聚齐的那天,合影当天最好)
  event 场合,可空(「春节」「爷爷生日」)
  who   在场成员,逗号/顿号分隔,首见即注册——「在场」是你声称的事实

命令: report / pairs / validate
退出码: 0 绿 · 2 账坏 · 3 空账或薄账拒判 · 4 账面红灯
零墙钟: as-of 缺省 = 账本自身最大日期;同一本账任何机器任何一天逐字节一致。
"""

import argparse
import os
import re
import sys
from datetime import datetime

COLS = ("date", "event", "who")
WHO_SPLIT = re.compile(r"[,，、;；/\s]+")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

EXIT_OK, EXIT_BROKEN, EXIT_DECLINE, EXIT_ALARM = 0, 2, 3, 4
DEFAULT_FULL_LINE = 365   # days since the last all-members gathering
DEFAULT_FADE_LINE = 365   # days since a member last appeared at all
THIN_ROWS = 2             # fewer gatherings than this -> no interval exists

FADED_VERDICT = (
    "🔴 FADED — {member} last appeared {days} days ago ({date}).\n"
    "  the ledger does not count how many frames are left; it only counts\n"
    "  how long the frame has been empty. absence has a thousand reasons and\n"
    "  this is none of them — it is just the number nobody was keeping."
)
DRIFT_VERDICT = (
    "🔴 DRIFT — everyone in one frame: {n} times, last on {date}.\n"
    "  that was {days} days ago. \"next time\" is not on any calendar; it\n"
    "  only ever happens on a day somebody actually books."
)
DRIFT_NEVER = (
    "🔴 DRIFT — no gathering on record ever had everyone in one frame.\n"
    "  \"all of us together\" has been a plan for as long as this ledger goes\n"
    "  back, and the plan has never once happened. that is the number."
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


def parse_who(raw, where):
    names = [n.strip() for n in WHO_SPLIT.split(raw) if n.strip()]
    if not names:
        raise LedgerError("%s: who is empty — a gathering needs at least one member" % where)
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise LedgerError("%s: duplicate member(s) in who: %s" % (where, ", ".join(dupes)))
    return names


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raise EmptyLedger("no ledger at '%s' yet — start one: a header line, then one "
                          "row per gathering (date/event/who)" % path)
    except OSError as exc:
        raise LedgerError("cannot read ledger: %s" % exc)
    if not raw.strip():
        raise EmptyLedger("ledger is empty")

    rows = []
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
        date_s, event, who_raw = (c.strip() for c in cells)
        d = strict_date(date_s, where)
        who = parse_who(who_raw, where)
        rows.append(dict(line=i, date=d, event=event, who=who))

    if not header_seen:
        raise EmptyLedger("ledger has no header row")
    if not rows:
        raise EmptyLedger("ledger has a header but no rows")
    return rows


def apply_alias(rows, pairs):
    mapping = {}
    for p in pairs:
        if "=" not in p:
            raise LedgerError("bad --alias '%s' (want FROM=TO, e.g. 爷=爷爷)" % p)
        src, dst = p.split("=", 1)
        src, dst = src.strip(), dst.strip()
        if not src or not dst:
            raise LedgerError("bad --alias '%s' (want FROM=TO, e.g. 爷=爷爷)" % p)
        mapping[src] = dst
    for r in rows:
        r["who"] = [mapping.get(n, n) for n in r["who"]]
        dupes = sorted({n for n in r["who"] if r["who"].count(n) > 1})
        if dupes:
            raise LedgerError("--alias collapsed distinct members into one on line %d: %s"
                              % (r["line"], ", ".join(dupes)))


def clip(rows, as_of):
    kept = [r for r in rows if r["date"] <= as_of]
    if not kept:
        raise EmptyLedger("nothing on or before --as-of %s" % as_of)
    return kept


# ---------------------------------------------------------------- aggregation

def audit(rows, as_of):
    members = sorted({n for r in rows for n in r["who"]})
    n = len(rows)
    members_att = {}
    for m in members:
        att = [r for r in rows if m in r["who"]]
        last = max(r["date"] for r in att)
        idx = max(i for i, r in enumerate(rows) if r["date"] <= as_of and m in r["who"])
        members_att[m] = dict(
            count=len(att),
            rate=len(att) / n,
            last=last,
            gap=(as_of - last).days,
            streak=sum(1 for r in rows[idx + 1:] if m not in r["who"]),
        )

    full = [r for r in rows if set(r["who"]) == set(members)]
    if full:
        last_full = max(r["date"] for r in full)
        full_gap = (as_of - last_full).days
    else:
        last_full, full_gap = None, None

    pairs = {}
    for r in rows:
        names = sorted(r["who"])
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                key = (names[i], names[j])
                times, prev = pairs.get(key, (0, None))
                pairs[key] = (times + 1, r["date"] if prev is None else max(prev, r["date"]))

    return dict(
        as_of=as_of, rows=rows, n=n, members=members, members_att=members_att,
        full=full, last_full=last_full, full_gap=full_gap, pairs=pairs,
    )


def compute_gates(aud, full_line, fade_line):
    faded = [m for m in aud["members"] if aud["members_att"][m]["gap"] > fade_line]
    # never-once-all-together is the loudest version of drift: it IS the alarm
    drift = aud["full_gap"] is None or aud["full_gap"] > full_line
    aud["faded"] = faded
    aud["drift"] = drift
    aud["alarm"] = bool(faded) or drift
    return aud


def pairs_of(rows):
    """(a,b) -> (times, last date); recomputed independently for validate."""
    out = {}
    for r in rows:
        names = sorted(set(r["who"]))
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                t, last = out.get((names[i], names[j]), (0, None))
                out[(names[i], names[j])] = (t + 1, r["date"] if last is None else max(last, r["date"]))
    return out


# ---------------------------------------------------------------- rendering

MEM_W = 10


def render_header(title, path, aud):
    print("== Same Frame · %s ==" % title)
    print("ledger: %s · %d gatherings · %d members · as-of %s (ledger self-anchored)"
          % (os.path.basename(path), aud["n"], len(aud["members"]), aud["as_of"]))


def render_members(aud):
    print()
    print("-- members --  (streak = consecutive gatherings missed at the tail)")
    print("%s  %s  %s  %s  %s  %s" % (pad("member", MEM_W), pad("attended", 8),
                                      pad("rate", 6), pad("last seen", 10),
                                      pad("gap(d)", 6), pad("streak", 6)))
    for m in aud["members"]:
        a = aud["members_att"][m]
        print("%s  %s  %s  %s  %s  %s"
              % (pad(m, MEM_W), pad(a["count"], 8), pad("%.1f%%" % (100 * a["rate"]), 6),
                 pad(str(a["last"]), 10), pad(a["gap"], 6), pad(a["streak"], 6)))


def render_full(aud):
    print()
    print("-- full house (every registered member in one frame) --")
    if not aud["full"]:
        print("never — no gathering on record had everyone. that is a number too.")
        return
    print("%d of %d gatherings had everyone. last: %s — %d days ago."
          % (len(aud["full"]), aud["n"], aud["last_full"], aud["full_gap"]))
    for r in aud["full"]:
        print("  #%d  %s  %s" % (r["line"], r["date"], r["event"] or "(gathering)"))


def render_pairs(aud, full_line):
    print()
    print("-- pairs --  (sorted by how long it has been; a pair is 'together' only in the same frame)")
    items = []
    for (a, b), (times, last) in aud["pairs"].items():
        items.append((a, b, times, last, (aud["as_of"] - last).days))
    items.sort(key=lambda t: (-t[4], t[2], t[0], t[1]))
    w = max((dw("%s–%s" % (a, b)) for a, b, *_ in items), default=8)
    for a, b, times, last, gap in items:
        mark = " ← over full-line" if gap > full_line else ""
        print("%s  %s  %s  %s%s" % (pad("%s–%s" % (a, b), w), pad(str(times), 5),
                                    pad(str(last), 10), pad(gap, 6), mark))


def render_gates(aud, full_line, fade_line):
    print()
    print("-- gates --")
    for m in sorted(aud["faded"], key=lambda m: -aud["members_att"][m]["gap"]):
        a = aud["members_att"][m]
        print(FADED_VERDICT.format(member=m, days=a["gap"], date=a["last"]))
    if aud["full_gap"] is None:
        print(DRIFT_NEVER)
    elif aud["drift"]:
        print(DRIFT_VERDICT.format(n=len(aud["full"]), date=aud["last_full"], days=aud["full_gap"]))
    if not aud["faded"] and not aud["alarm"]:
        print("FADED: nobody beyond %dd without a frame" % fade_line)
        print("DRIFT: last full house %d days ago (line %dd)" % (aud["full_gap"], full_line))


def render_report(path, aud, full_line, fade_line):
    render_header("together-audit", path, aud)
    render_members(aud)
    render_full(aud)
    render_gates(aud, full_line, fade_line)


def render_pairs_cmd(path, aud, full_line, fade_line):
    render_header("pair matrix", path, aud)
    render_pairs(aud, full_line)
    render_gates(aud, full_line, fade_line)


def render_thin(path, aud):
    render_header("together-audit", path, aud)
    print()
    print("DECLINE: %d gathering%s on record — an interval needs at least two.\n"
          "the member table below is still true; the gates need one more row."
          % (aud["n"], "" if aud["n"] == 1 else "s"))
    render_members(aud)


def render_validate(path, rows):
    print("== Same Frame · ledger audit ==")
    print("ledger: %s" % os.path.basename(path))
    n_rows = len(rows)
    members = sorted({n_ for r in rows for n_ in r["who"]})
    sum_att = sum(len(r["who"]) for r in rows)
    sum_members = sum(1 for m in members for r in rows if m in r["who"])
    assert sum_att == sum_members
    n_pairs = sum(len(set(r["who"])) * (len(set(r["who"])) - 1) // 2 for r in rows)
    p2 = pairs_of(rows)
    assert sum(t for t, _ in p2.values()) == n_pairs
    print("rows: %d gatherings · %d members · Σattendance %d = Σwho %d"
          % (n_rows, len(members), sum_members, sum_att))
    print("pairs: %d registered · Σco-appearances %d = ΣC(k,2) %d"
          % (len(p2), sum(t for t, _ in p2.values()), n_pairs))
    print("ledger is sound")


# ---------------------------------------------------------------- commands

def prepare(args):
    rows = load(args.ledger)
    if getattr(args, "alias", None):
        apply_alias(rows, args.alias)
    as_of = strict_date(args.as_of, "--as-of") if args.as_of else max(r["date"] for r in rows)
    views = clip(rows, as_of)
    views.sort(key=lambda r: (r["date"], r["line"]))
    aud = compute_gates(audit(views, as_of), args.full_line, args.fade_line)
    return aud


def gate_exit(aud):
    if aud["alarm"]:
        return EXIT_ALARM
    if aud["n"] < THIN_ROWS:
        return EXIT_DECLINE
    return EXIT_OK


def cmd_report(args):
    aud = prepare(args)
    if aud["n"] < THIN_ROWS:
        render_thin(args.ledger, aud)
        return EXIT_DECLINE
    render_report(args.ledger, aud, args.full_line, args.fade_line)
    return gate_exit(aud)


def cmd_pairs(args):
    aud = prepare(args)
    if aud["n"] < THIN_ROWS:
        render_thin(args.ledger, aud)
        return EXIT_DECLINE
    render_pairs_cmd(args.ledger, aud, args.full_line, args.fade_line)
    return gate_exit(aud)


def cmd_validate(args):
    rows = load(args.ledger)
    if getattr(args, "alias", None):
        apply_alias(rows, args.alias)
    render_validate(args.ledger, rows)
    return EXIT_OK


def build_parser():
    p = argparse.ArgumentParser(
        prog="same_frame.py",
        description="同框 · Same Frame — the ledger of 'everyone made it into one frame': "
                    "full-house intervals, who is fading out of the photos, and which two "
                    "people never seem to be together anymore.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, alias=True, lines=True):
        sp.add_argument("--ledger", default="family.tsv", help="ledger TSV path")
        sp.add_argument("--as-of", dest="as_of", default=None,
                        help="replay the ledger as of YYYY-MM-DD (default: ledger's own last date)")
        if lines:
            sp.add_argument("--full-line", type=int, default=DEFAULT_FULL_LINE,
                            help="alarm when the last all-members gathering is older than N days")
            sp.add_argument("--fade-line", type=int, default=DEFAULT_FADE_LINE,
                            help="alarm when a member has not appeared for N days")
        if alias:
            sp.add_argument("--alias", action="append", default=[], metavar="FROM=TO",
                            help="normalize a member name into another (repeatable)")

    common(sub.add_parser("report", help="full audit: members, full house, gates"))
    common(sub.add_parser("pairs", help="pair co-appearance matrix"))
    common(sub.add_parser("validate", help="ledger health + identity checks"), alias=True, lines=False)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {"report": cmd_report, "pairs": cmd_pairs, "validate": cmd_validate}
    try:
        return handlers[args.cmd](args)
    except LedgerError as exc:
        sys.stderr.write("same-frame: broken ledger: %s\n" % exc)
        return EXIT_BROKEN
    except EmptyLedger as exc:
        sys.stderr.write("same-frame: %s\n" % exc)
        return EXIT_DECLINE


if __name__ == "__main__":
    sys.exit(main())
