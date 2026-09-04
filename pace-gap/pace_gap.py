#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""赶考线 · Pace Gap — 备考进度对账账本

学习 App 记的全是投入（打卡天数、专注分钟、连击 streak），考试只按产出付钱
（大纲覆盖、章节闭）。两本账之间没有人对账：87 天连击可以同时是 40% 进度，
「来得及吗」永远是感觉，不是数字。督学营每周收你几百块干的也就是这道算术——
本件把它变成一条命令：

  - report      覆盖总账：每科 闭/开/未动/总章、匀速应到位置与落后章数、
                时长账与章/小时汇率（前后窗对比只披露不判级）；
  - pace        速率法庭：required（剩余÷剩余天）vs proven（近 28 天实测）
                vs peak（历史最好 28 天窗）——赶考倍数判级
                ON-PACE / STRETCH / REDLINE / MATH-DEAD；
  - allocation  错配账：科目时长占比 vs 分值权重占比，每小时期望分，
                TILTED 超投 / STARVED 饿着 / NEVER 从未开工点名；
  - simulate    反事实：--rate 正推完成日（BEFORE/AFTER 考日），
                --finish-by 反解所需速率并对照 proven/peak；
  - validate    账本体检：章节守恒、幽灵章引用、权重口径、日期语法。

诚实条款：exam-date 不给就不判级（数字自己会说话，不发明考日）；
权重不给就只出时长分布（不发明权重）；薄账拒统计判级（3 天的速率
不是速率是噪声），但「考日已到还有剩章」是纯日历算术，再薄也裁决。
全部本地计算、不连任何接口；as-of 缺省=账本最大日期，同一本账
任何机器任何一天逐字节一致。赶不赶、换不换目标，永远是人的决定。
"""

import argparse
import math
import os
import sys
from datetime import date, timedelta

EXIT_OK = 0
EXIT_LEDGER = 2
EXIT_DECLINE = 3
EXIT_GATE = 4

TOL = 1e-9


class LedgerError(Exception):
    """账本坏了：语法/引用/口径，exit 2。"""


class Decline(Exception):
    """账太薄或有缺口：统计判级拒答，算术照出，exit 3。"""


class Gate(Exception):
    """门禁红灯：判级不通过或错配亮灯，exit 4。"""


# ---------------------------------------------------------------- TSV

def read_tsv(path, kind):
    if not os.path.exists(path):
        raise LedgerError("missing file: %s" % os.path.basename(path))
    rows = []
    header = None
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                continue
            cols = line.split("\t")
            if header is None:
                header = [c.strip().lower() for c in cols]
                continue
            if len(cols) != len(header):
                raise LedgerError(
                    "%s line %d: expected %d columns, got %d"
                    % (kind, lineno, len(header), len(cols)))
            row = dict(zip(header, [c.strip() for c in cols]))
            row["_line"] = lineno
            rows.append(row)
    if header is None:
        raise LedgerError("%s: empty ledger (no header row)" % kind)
    return rows


def need(row, col, kind):
    val = row.get(col, "")
    if val == "":
        raise LedgerError("%s line %d: missing %s" % (kind, row["_line"], col))
    return val


def parse_date(val, kind, lineno):
    try:
        parts = val.split("-")
        if len(parts) != 3:
            raise ValueError
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise LedgerError("%s line %d: bad date %r (want YYYY-MM-DD)"
                          % (kind, lineno, val))


def parse_int(val, kind, lineno):
    try:
        num = int(val)
    except ValueError:
        raise LedgerError("%s line %d: bad integer %r" % (kind, lineno, val))
    if num <= 0:
        raise LedgerError("%s line %d: order must be >= 1, got %d"
                          % (kind, lineno, num))
    return num


def parse_float(val, kind, lineno, field, minimum=None):
    try:
        num = float(val)
    except ValueError:
        raise LedgerError("%s line %d: bad number %r for %s"
                          % (kind, lineno, val, field))
    if minimum is not None and num < minimum:
        raise LedgerError("%s line %d: %s must be >= %s, got %s"
                          % (kind, lineno, field, minimum, val))
    return num


# ------------------------------------------------------------ syllabus

def load_syllabus(path):
    rows = read_tsv(path, "syllabus")
    if not rows:
        raise LedgerError("syllabus: no chapter rows")
    chapters = {}     # (subject, order) -> dict
    subjects = []     # keeps first-seen order
    for row in rows:
        subject = need(row, "subject", "syllabus")
        order = parse_int(need(row, "order", "syllabus"), "syllabus", row["_line"])
        name = row.get("chapter", "")
        weight_raw = row.get("weight", "")
        weight = None
        if weight_raw != "":
            weight = parse_float(weight_raw, "syllabus", row["_line"], "weight", 0.0)
        key = (subject, order)
        if key in chapters:
            raise LedgerError(
                "syllabus line %d: duplicate chapter %s #%d"
                % (row["_line"], subject, order))
        if subject not in subjects:
            subjects.append(subject)
        chapters[key] = {"subject": subject, "order": order,
                         "name": name, "weight": weight}
    # 权重口径：全体科目全给或全不给；同科目内混给 = 账坏
    with_w = set()
    for (subject, _order), ch in chapters.items():
        if ch["weight"] is not None:
            with_w.add(subject)
    if with_w and len(with_w) != len(subjects):
        missing = [s for s in subjects if s not in with_w]
        raise LedgerError(
            "weight scope: subjects %s have no weight while %s do — "
            "weight every subject or none (the ledger does not invent weights)"
            % (",".join(missing), ",".join(sorted(with_w))))
    intra = [s for s in subjects
             if any(ch["weight"] is None for (sub, _o), ch in chapters.items()
                    if sub == s) and s in with_w]
    if intra:
        raise LedgerError(
            "syllabus: subject %s mixes weighted and unweighted chapters "
            "— weight scope must be consistent" % ",".join(intra))
    return {"chapters": chapters, "subjects": subjects,
            "weighted": len(with_w) == len(subjects)}


# --------------------------------------------------------------- study

def load_study(path, syllabus):
    rows = read_tsv(path, "study")
    chapters = syllabus["chapters"]
    sessions = []
    for row in rows:
        day = parse_date(need(row, "date", "study"), "study", row["_line"])
        subject = need(row, "subject", "study")
        order = parse_int(need(row, "order", "study"), "study", row["_line"])
        if (subject, order) not in chapters:
            raise LedgerError(
                "study line %d: ghost chapter %s #%d (not in syllabus)"
                % (row["_line"], subject, order))
        minutes_raw = row.get("minutes", "")
        minutes = 0.0
        if minutes_raw != "":
            minutes = parse_float(minutes_raw, "study", row["_line"],
                                  "minutes", 0.0)
        status = (row.get("status", "") or "done").lower()
        if status not in ("done", "open"):
            raise LedgerError(
                "study line %d: status must be done|open, got %r"
                % (row["_line"], status))
        sessions.append({"date": day, "subject": subject, "order": order,
                         "minutes": minutes, "status": status})
    sessions.sort(key=lambda s: s["date"])
    return sessions


# ------------------------------------------------------------- chapter

def chapter_state(syllabus, sessions):
    """(subject, order) -> {closed, close_date, minutes, opened, touched}"""
    state = {key: {"closed": False, "close_date": None, "minutes": 0.0,
                   "opened": False, "name": ch["name"],
                   "subject": ch["subject"], "order": ch["order"]}
             for key, ch in syllabus["chapters"].items()}
    for ses in sessions:
        key = (ses["subject"], ses["order"])
        st = state[key]
        st["opened"] = True
        st["minutes"] += ses["minutes"]
        if ses["status"] == "done":
            if st["close_date"] is None or ses["date"] > st["close_date"]:
                st["close_date"] = ses["date"]
            st["closed"] = True
    return state


def close_counts(state, as_of):
    """闭章日 -> 当日闭章数（close_date > as_of 的不算）。"""
    counts = {}
    for st in state.values():
        if st["closed"] and st["close_date"] <= as_of:
            counts[st["close_date"]] = counts.get(st["close_date"], 0) + 1
    return counts


def window_closes(counts, end, width):
    total = 0
    for i in range(width):
        total += counts.get(end - timedelta(days=i), 0)
    return total


def proven_rate(counts, as_of, width):
    return window_closes(counts, as_of, width) / float(width)


def peak_rate(counts, first_date, as_of, width):
    """任意 width 天滑动窗的最大闭章数 / width（历史证明过的可维持速率）。"""
    span = (as_of - first_date).days + 1
    if span < width:
        width = span
    if width <= 0:
        return 0.0
    best = 0
    best_end = None
    for end in [first_date + timedelta(days=w - 1)
                for w in range(width, span + 1)]:
        total = window_closes(counts, end, width)
        if total > best:
            best = total
            best_end = end
    return best / float(width), best_end, width, best


# ------------------------------------------------------------ formatting

def display_width(text):
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def pad(text, width):
    gap = width - display_width(text)
    return text + " " * max(0, gap)


def pct(x):
    return "%.1f%%" % (x * 100)


def rate_str(x):
    return "%.4f ch/day" % x


# ------------------------------------------------------------ commands

def add_common(p):
    p.add_argument("--as-of", dest="as_of", default=None,
                   help="anchor date YYYY-MM-DD (default: last study date)")
    p.add_argument("--exam-date", dest="exam_date", default=None,
                   help="exam date YYYY-MM-DD (needed for pace verdicts)")
    p.add_argument("--start", dest="start", default=None,
                   help="plan start date (default: first study date)")
    p.add_argument("--peak-window", dest="peak_window", type=int, default=28,
                   help="sliding window for peak rate, days (default 28)")
    p.add_argument("--stretch-line", dest="stretch_line", type=float,
                   default=1.5,
                   help="multiple above which pace enters REDLINE (default 1.5)")
    p.add_argument("--min-days", dest="min_days", type=int, default=7,
                   help="min distinct study days before pace verdicts (default 7)")
    p.add_argument("--tilt-line", dest="tilt_line", type=float, default=0.15,
                   help="share gap (pp fraction) that lights allocation (default 0.15)")


def load_all(args):
    syllabus = load_syllabus(args.syllabus)
    if args.study:
        sessions = load_study(args.study, syllabus)
    else:
        sessions = load_study(
            os.path.join(os.path.dirname(args.syllabus), "study.tsv"),
            syllabus)
    return syllabus, sessions


def resolve_anchor(sessions, args):
    if args.as_of:
        return parse_date(args.as_of, "args", 0)
    if not sessions:
        raise LedgerError("empty ledger: no study rows and no --as-of")
    return sessions[-1]["date"]


def resolve_exam(args):
    if not args.exam_date:
        return None
    return parse_date(args.exam_date, "args", 0)


def resolve_start(sessions, args):
    if args.start:
        return parse_date(args.start, "args", 0)
    return sessions[0]["date"]


def totals(syllabus):
    total = len(syllabus["chapters"])
    weight = sum((ch["weight"] or 0.0) for ch in syllabus["chapters"].values())
    return total, weight


def thin_check(sessions, state, args):
    days = len({s["date"] for s in sessions})
    closed = sum(1 for st in state.values() if st["closed"])
    return days < args.min_days or closed < 3


def verdict_line(grade, multiple, required, peak):
    if grade == "ON-PACE":
        return ("ON-PACE — current speed clears the exam calendar "
                "(multiple %.2fx)" % multiple)
    if grade == "STRETCH":
        return ("STRETCH — need %.2fx your recent speed; effort-sized, "
                "not luck-sized" % multiple)
    if grade == "REDLINE":
        if multiple == float("inf"):
            return ("REDLINE — your recent window closed nothing; the peak "
                    "%.4f still clears required %.4f, but every remaining "
                    "week must be a peak week" % (peak, required))
        return ("REDLINE — need %.2fx your recent speed; peak %.4f barely "
                "clears required %.4f, every remaining week must be a peak "
                "week" % (multiple, peak, required))
    return ("MATH-DEAD — required %.4f ch/day exceeds your proven peak "
            "%.4f: the calendar, not your willpower, is the bottleneck now"
            % (required, peak))


def grade_pace(remaining, days_left, required, proven, peak, stretch_line):
    """returns (grade, multiple)"""
    if remaining <= 0:
        return "DONE", 0.0
    if days_left <= 0:
        return "MATH-DEAD", float("inf")
    if required > peak + TOL:
        return "MATH-DEAD", float("inf")
    if proven <= TOL:
        return "REDLINE", float("inf")
    multiple = required / proven
    if multiple <= 1.0 + TOL:
        return "ON-PACE", multiple
    if multiple <= stretch_line + TOL:
        return "STRETCH", multiple
    return "REDLINE", multiple


def cmd_report(args):
    syllabus, sessions = load_all(args)
    if not sessions:
        raise LedgerError("empty ledger: study.tsv has no rows")
    state = chapter_state(syllabus, sessions)
    as_of = resolve_anchor(sessions, args)
    exam = resolve_exam(args)
    start = resolve_start(sessions, args)
    total, _weight = totals(syllabus)

    print("== Pace Gap · coverage ledger ==")
    print("ledger: %s    as-of: %s    subjects: %d    chapters: %d"
          % (os.path.basename(args.study), as_of.isoformat(),
             len(syllabus["subjects"]), total))

    per_subject = {}
    for st in state.values():
        row = per_subject.setdefault(
            st["subject"], {"total": 0, "closed": 0, "opened": 0,
                            "minutes": 0.0})
        row["total"] += 1
        row["minutes"] += st["minutes"]
        if st["closed"]:
            row["closed"] += 1
        elif st["opened"]:
            row["opened"] += 1

    print()
    print(pad("subject", 14) + pad("closed", 8) + pad("open", 6)
          + pad("untouched", 11) + pad("total", 7) + pad("coverage", 10)
          + pad("hours", 8) + "ch/hour")
    for subject in syllabus["subjects"]:
        row = per_subject[subject]
        cov = row["closed"] / float(row["total"])
        hours = row["minutes"] / 60.0
        chph = ("%.2f" % (row["closed"] / hours)) if hours > TOL else "-"
        print(pad(subject, 14) + pad(str(row["closed"]), 8)
              + pad(str(row["opened"]), 6) + pad(str(row["total"] - row["closed"] - row["opened"]), 11)
              + pad(str(row["total"]), 7) + pad(pct(cov), 10)
              + pad("%.2f" % hours, 8) + chph)
    closed_all = sum(r["closed"] for r in per_subject.values())
    minutes_all = sum(r["minutes"] for r in per_subject.values())
    hours_all = minutes_all / 60.0
    print(pad("TOTAL", 14) + pad(str(closed_all), 8) + pad("-", 6)
          + pad(str(total - closed_all), 11) + pad(str(total), 7)
          + pad(pct(closed_all / float(total)), 10)
          + pad("%.2f" % hours_all, 8)
          + (("%.2f" % (closed_all / hours_all)) if hours_all > TOL else "-"))

    if exam is not None:
        if exam < start:
            raise LedgerError("exam-date %s is before plan start %s"
                              % (exam.isoformat(), start.isoformat()))
        span = (exam - start).days
        elapsed = (as_of - start).days
        planned = total * elapsed / float(span) if span > 0 else float(total)
        lag = planned - closed_all
        print()
        print("== uniform plan line ==")
        print("start %s -> exam %s (%d days); elapsed %d days (%s of the plan)"
              % (start.isoformat(), exam.isoformat(), span, elapsed,
                 pct(elapsed / float(span))))
        print("should have closed %.1f chapters by uniform pace; "
              "actually closed %d -> lag %.1f chapters"
              % (planned, closed_all, lag))
    print()
    print("== effort vs yield (disclosure only) ==")
    half = 28
    counts = close_counts(state, as_of)
    recent = window_closes(counts, as_of, half)
    prior_end = as_of - timedelta(days=half)
    prior = window_closes(counts, prior_end, half)
    print("chapters closed: last 28d %d, prior 28d %d" % (recent, prior))
    if hours_all > TOL:
        print("overall yield: %.2f chapters per 100 hours invested"
              % (closed_all / hours_all * 100))
    for subject in syllabus["subjects"]:
        row = per_subject[subject]
        if row["minutes"] > TOL and row["closed"] > 0:
            print("  %s: %.2f ch / %.1f h = %.2f ch per 100 h"
                  % (subject, row["closed"], row["minutes"] / 60.0,
                     row["closed"] / (row["minutes"] / 60.0) * 100))
    print("(yield is what your minutes bought; pace judges whether it "
          "clears the calendar)")
    return EXIT_OK


def cmd_pace(args):
    syllabus, sessions = load_all(args)
    if not sessions:
        raise LedgerError("empty ledger: study.tsv has no rows")
    state = chapter_state(syllabus, sessions)
    as_of = resolve_anchor(sessions, args)
    exam = resolve_exam(args)
    total, _weight = totals(syllabus)
    counts = close_counts(state, as_of)
    closed_all = sum(counts.values())
    remaining = total - closed_all
    first_date = sessions[0]["date"]

    print("== Pace Gap · pace court ==")
    print("ledger: %s    as-of: %s" % (os.path.basename(args.study),
                                       as_of.isoformat()))
    print("chapters: %d total, %d closed, %d remaining"
          % (total, closed_all, remaining))

    pw = max(1, args.peak_window)
    proven = proven_rate(counts, as_of, pw)
    peak, peak_end, peak_w, peak_n = peak_rate(counts, first_date, as_of, pw)
    print()
    print("== three speeds (window %d days) ==" % pw)
    print("proven  %s   (last %dd window: %d chapters, trailing speed)"
          % (pad(rate_str(proven), 16), pw,
             window_closes(counts, as_of, pw)))
    if peak_end is not None:
        w0 = peak_end - timedelta(days=peak_w - 1)
        print("peak    %s   (best %dd window %s..%s: %d chapters — "
              "the speed you have proven)"
              % (pad(rate_str(peak), 16), peak_w, w0.isoformat(),
                 peak_end.isoformat(), peak_n))
    else:
        print("peak    %s   (no closed chapter yet)"
              % pad(rate_str(0.0), 16))

    if exam is None:
        print()
        print("no --exam-date: the three speeds stand on their own; "
              "give the exam date and the court will rule "
              "(the ledger does not invent deadlines)")
        return EXIT_OK

    days_left = (exam - as_of).days
    print("exam %s: %d days left from as-of" % (exam.isoformat(), days_left))
    if remaining <= 0:
        print()
        print("DONE — every chapter closed before the bell; "
              "the ledger has nothing left to warn about")
        return EXIT_OK

    required = remaining / float(days_left) if days_left > 0 else float("inf")
    print("required %s   (%d remaining / %d days)"
          % (pad(rate_str(required) if days_left > 0 else "inf ch/day", 16),
             remaining, max(0, days_left)))

    thin = thin_check(sessions, state, args)
    if days_left <= 0:
        raise Gate("MATH-DEAD — exam date %s has arrived with %d chapters "
                   "still open; calendar arithmetic, not statistics: "
                   "no thin-ledger mercy applies"
                   % (exam.isoformat(), remaining))
    if thin:
        raise Decline(
            "ledger too thin for a pace verdict (%d distinct days, %d "
            "closed; need >= %d days and >= 3 closed) — coverage and "
            "hours above are still facts" % (
                len({s["date"] for s in sessions}),
                closed_all, args.min_days))

    grade, multiple = grade_pace(remaining, days_left, required,
                                 proven, peak, args.stretch_line)
    print()
    print("multiple required/proven = %s" % ("inf" if multiple == float("inf")
                                             else "%.2fx" % multiple))
    if grade == "REDLINE" and peak > TOL:
        days_at_peak = int(math.ceil(remaining / peak - TOL))
        print("at peak speed the remaining %d chapters need %d more days; "
              "the calendar gives %d" % (remaining, days_at_peak, days_left))
    print(verdict_line(grade, multiple, required, peak))
    if grade in ("REDLINE", "MATH-DEAD"):
        raise Gate(grade)
    return EXIT_OK


def cmd_allocation(args):
    syllabus, sessions = load_all(args)
    if not sessions:
        raise LedgerError("empty ledger: study.tsv has no rows")
    state = chapter_state(syllabus, sessions)
    as_of = resolve_anchor(sessions, args)
    total, weight_total = totals(syllabus)

    print("== Pace Gap · allocation court ==")
    print("ledger: %s    as-of: %s" % (os.path.basename(args.study),
                                       as_of.isoformat()))

    per = {}
    for st in state.values():
        row = per.setdefault(st["subject"],
                             {"minutes": 0.0, "closed": 0, "weight": 0.0,
                              "total": 0})
        row["minutes"] += st["minutes"]
        row["total"] += 1
        if st["closed"]:
            row["closed"] += 1
    for subject in syllabus["subjects"]:
        per[subject]["weight"] = sum(
            (ch["weight"] or 0.0) for (s, _o), ch in syllabus["chapters"].items()
            if s == subject)
    minutes_all = sum(r["minutes"] for r in per.values())

    print()
    if not syllabus["weighted"]:
        print("no weights in syllabus: printing time and coverage shares "
              "only — the ledger does not invent exam weights")
        print()
        print(pad("subject", 14) + pad("hours", 9) + pad("time-share", 12)
              + pad("closed", 8) + "chapters")
        for subject in syllabus["subjects"]:
            row = per[subject]
            share = (row["minutes"] / minutes_all) if minutes_all > TOL else 0.0
            print(pad(subject, 14) + pad("%.2f" % (row["minutes"] / 60.0), 9)
                  + pad(pct(share), 12) + pad(str(row["closed"]), 8)
                  + "%d/%d" % (row["closed"], row["total"]))
        return EXIT_OK

    tilted, starved, never = [], [], []
    print(pad("subject", 14) + pad("hours", 8) + pad("time", 8)
          + pad("weight", 8) + pad("gap", 9) + pad("ch/h", 7)
          + pad("closed", 8) + "pts/hour")
    ranked = []
    for subject in syllabus["subjects"]:
        row = per[subject]
        hours = row["minutes"] / 60.0
        time_share = (row["minutes"] / minutes_all) if minutes_all > TOL else 0.0
        weight_share = (row["weight"] / weight_total) if weight_total > TOL else 0.0
        gap = time_share - weight_share
        pts_per_h = (row["weight"] / hours) if hours > TOL else None
        if pts_per_h is not None:
            ranked.append((pts_per_h, subject))
        if row["minutes"] <= TOL:
            never.append((subject, weight_share))
        elif gap >= args.tilt_line - TOL:
            tilted.append((subject, gap, weight_share))
        elif -gap >= args.tilt_line - TOL:
            starved.append((subject, -gap, weight_share))
        print(pad(subject, 14)
              + pad("%.2f" % hours, 8)
              + pad(pct(time_share), 8)
              + pad(pct(weight_share), 8)
              + pad("%+.1fpp" % (gap * 100), 9)
              + pad(("%.1f" % pts_per_h) if pts_per_h is not None else "-", 7)
              + pad("%d/%d" % (row["closed"], row["total"]), 8)
              + (("%.1f" % pts_per_h) if pts_per_h is not None else "inf"))
    ranked.sort(reverse=True)
    print()
    if ranked:
        top = ranked[0]
        top_row = per[top[1]]
        share = (top_row["minutes"] / minutes_all) if minutes_all > TOL else 0.0
        print("highest points-per-hour subject: %s (%.1f pts/hour) — "
              "it holds %.1f%% of your logged time"
              % (top[1], top[0], share * 100))
    for subject, gap, wshare in tilted:
        print("TILTED  %s — time share exceeds weight share by %.1fpp; "
              "the exam pays by weight, comfort does not score"
              % (subject, gap * 100))
    for subject, gap, wshare in starved:
        print("STARVED %s — weight share exceeds time share by %.1fpp; "
              "the highest-yield chapters are waiting" % (subject, gap * 100))
    for subject, wshare in never:
        print("NEVER   %s — %.1f%% of the exam's weight, zero minutes "
              "logged; an untouched subject is not a strategy, "
              "it is a blank" % (subject, wshare * 100))
    if tilted or starved or never:
        raise Gate("allocation gate: %d tilted, %d starved, %d never-started"
                   % (len(tilted), len(starved), len(never)))
    print("allocation balanced: no subject exceeds the %.0fpp tilt line"
          % (args.tilt_line * 100))
    return EXIT_OK


def cmd_simulate(args):
    if args.rate is None and args.finish_by is None:
        raise LedgerError("simulate needs --rate CH/DAY or --finish-by DATE")
    if args.rate is not None and args.finish_by:
        raise LedgerError("give --rate or --finish-by, not both")
    syllabus, sessions = load_all(args)
    if not sessions:
        raise LedgerError("empty ledger: study.tsv has no rows")
    state = chapter_state(syllabus, sessions)
    as_of = resolve_anchor(sessions, args)
    exam = resolve_exam(args)
    total, _weight = totals(syllabus)
    counts = close_counts(state, as_of)
    closed_all = sum(counts.values())
    remaining = total - closed_all

    print("== Pace Gap · simulate ==")
    print("ledger: %s    as-of: %s    remaining %d of %d chapters"
          % (os.path.basename(args.study), as_of.isoformat(),
             remaining, total))

    finish_by = None
    if args.finish_by:
        finish_by = parse_date(args.finish_by, "args", 0)
        days = (finish_by - as_of).days
        if days < 0:
            raise LedgerError("--finish-by %s is before as-of %s"
                              % (finish_by.isoformat(), as_of.isoformat()))
        if args.rate is None:
            if remaining <= 0:
                print("DONE — nothing left to schedule")
                return EXIT_OK
            needed = remaining / float(days) if days > 0 else float("inf")
            print("finish-by %s: %d days from as-of -> required %s"
                  % (finish_by.isoformat(), days,
                     rate_str(needed) if days > 0 else "inf"))
            return run_verdict(args, sessions, state, as_of, exam,
                               remaining, days, needed, counts)
        rate = args.rate

    else:
        rate = args.rate
        if rate <= 0:
            raise LedgerError("--rate must be > 0, got %s" % args.rate)
        if remaining <= 0:
            print("DONE — nothing left to schedule")
            return EXIT_OK
        days = int(math.ceil(remaining / rate - TOL))
        finish = as_of + timedelta(days=days)
        print("at %.2f ch/day the remaining %d chapters close in %d days "
              "-> %s" % (rate, remaining, days, finish.isoformat()))
        target = finish_by or exam
        if target is None:
            print("no --exam-date/--finish-by: completion date only — "
                  "the ledger does not invent deadlines")
            return EXIT_OK
        slack = (target - finish).days
        if slack >= 0:
            print("BEFORE the %s deadline by %d days — arithmetic clears it"
                  % (target.isoformat(), slack))
            return EXIT_OK
        print("AFTER the %s deadline by %d days — at this rate you arrive "
              "to an exam that already happened"
              % (target.isoformat(), -slack))
        raise Gate("simulate: %d chapters at %.2f/day finish after %s"
                   % (remaining, rate, target.isoformat()))


def run_verdict(args, sessions, state, as_of, exam, remaining, days, needed,
                counts):
    pw = max(1, args.peak_window)
    proven = proven_rate(counts, as_of, pw)
    first_date = sessions[0]["date"]
    peak, peak_end, peak_w, peak_n = peak_rate(counts, first_date, as_of, pw)
    print("proven %s   peak %s" % (rate_str(proven), rate_str(peak)))
    thin = thin_check(sessions, state, args)
    if days <= 0 and remaining > 0:
        raise Gate("MATH-DEAD — the finish line is behind you with %d "
                   "chapters open" % remaining)
    if thin:
        raise Decline(
            "ledger too thin for a verdict (%d distinct days, %d closed; "
            "need >= %d days and >= 3 closed)" % (
                len({s["date"] for s in sessions}),
                sum(counts.values()), args.min_days))
    grade, multiple = grade_pace(remaining, days, needed, proven, peak,
                                 args.stretch_line)
    print(verdict_line(grade, multiple, needed, peak))
    if grade in ("REDLINE", "MATH-DEAD"):
        raise Gate(grade)
    return EXIT_OK


def cmd_validate(args):
    syllabus, sessions = load_all(args)
    if not sessions:
        raise LedgerError("empty ledger: study.tsv has no rows")
    state = chapter_state(syllabus, sessions)
    total, weight_total = totals(syllabus)
    closed = sum(1 for st in state.values() if st["closed"])
    opened_only = sum(1 for st in state.values()
                      if st["opened"] and not st["closed"])
    untouched = total - closed - opened_only
    minutes_all = sum(st["minutes"] for st in state.values())

    print("== Pace Gap · validate ==")
    print("ledger: %s" % os.path.basename(args.study))
    ok = True

    identity = (closed + opened_only + untouched) - total
    print("conservation: closed %d + opened-only %d + untouched %d = %d, "
          "syllabus total %d (residual %d)"
          % (closed, opened_only, untouched,
             closed + opened_only + untouched, total, identity))
    if identity != 0:
        ok = False
    minutes_identity = sum(st["minutes"] for st in state.values()) - minutes_all
    print("minutes identity: per-chapter sum == ledger sum (residual %.2f)"
          % minutes_identity)
    if abs(minutes_identity) > TOL:
        ok = False
    subjects = syllabus["subjects"]
    print("subjects: %d (%s), weights %s"
          % (len(subjects), ", ".join(subjects),
             "present, total %g" % weight_total if syllabus["weighted"]
             else "absent (disclosure-only allocation)"))
    if closed == 0:
        print("no closed chapter: pace verdicts would decline (thin ledger)")
    else:
        print("pace gate armed: %d closed chapters on record" % closed)
    if ok:
        print("validate: PASS")
        return EXIT_OK
    raise Gate("validate: FAIL")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pace_gap.py",
        description="赶考线 · Pace Gap — exam-prep progress vs calendar audit")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("report", help="coverage / lag / effort ledger")
    p.add_argument("syllabus")
    p.add_argument("study")
    add_common(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("pace", help="required vs proven vs peak, verdict")
    p.add_argument("syllabus")
    p.add_argument("study")
    add_common(p)
    p.set_defaults(func=cmd_pace)

    p = sub.add_parser("allocation", help="time share vs exam weight share")
    p.add_argument("syllabus")
    p.add_argument("study")
    add_common(p)
    p.set_defaults(func=cmd_allocation)

    p = sub.add_parser("simulate", help="--rate forward / --finish-by inverse")
    p.add_argument("syllabus")
    p.add_argument("study")
    p.add_argument("--rate", type=float, default=None,
                   help="assumed speed in chapters/day")
    p.add_argument("--finish-by", dest="finish_by", default=None,
                   help="target date YYYY-MM-DD (inverse solve)")
    add_common(p)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("validate", help="conservation + reference checks")
    p.add_argument("syllabus")
    p.add_argument("study")
    add_common(p)
    p.set_defaults(func=cmd_validate)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return EXIT_LEDGER
    try:
        return args.func(args)
    except LedgerError as exc:
        print("ledger error: %s" % exc, file=sys.stderr)
        return EXIT_LEDGER
    except Decline as exc:
        print("declined: %s" % exc, file=sys.stderr)
        return EXIT_DECLINE
    except Gate as exc:
        print("GATE: %s" % exc, file=sys.stderr)
        return EXIT_GATE


if __name__ == "__main__":
    sys.exit(main())
