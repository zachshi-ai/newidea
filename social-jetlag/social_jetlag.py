#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""social-jetlag · 社交时差 —— 把「困」拆成两本账：睡眠债与生物钟错位.

问题：你的语言里只有一个「困」，但睡眠健康有两个独立变量——睡了多久
（债）和睡在钟面哪里（相）。周一早上的难受多半不是缺觉，是社交时差：
生物钟在自由日被推后，周一被闹钟硬拽回来，每周两次自己给自己倒时差。
药方「早点上床」治的是债，治不了钟——尝试失败一次，人就放弃一次。

social-jetlag 从一本可手编的睡眠日志（TSV：日期 / 入睡 / 醒来 /
工作日或自由日）确定性算出：

  * MSW / MSF   工作日与自由日的睡眠中点——你的社交钟 vs 生物钟
  * SJL         社交时差 = MSF − MSW，|SJL| ≥ 2h 是流行病学红线
  * MSFsc       扣掉自由日「还债式超睡」后的校正中点
  * 睡眠债      每个工作日欠多少、每周欠多少、年化多少
  * 还债率      周末超睡到底够不够还工作日的账
  * simulate    反事实：周末不再补觉（flat）、自由日整体平移（anchor）、
                把时差压到目标需要移动多久（target）

零依赖：Python 3.8+ 标准库。数据就是一个可手编的 TSV，一切留在本地。
本工具回答的是账本问题，不提供医疗建议。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date as _date
from typing import List, Optional

MINUTES_PER_DAY = 1440
YELLOW_LINE_MIN = 60    # |SJL| >= 1h   -> drifting
RED_LINE_MIN = 120      # |SJL| >= 2h   -> high (epidemiological red line)
MIN_WORK_DAYS_WARN = 3
MIN_FREE_DAYS_WARN = 3
MIN_SPAN_DAYS_WARN = 14
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_GATE = 4


# ---------------------------------------------------------------------------
# clock arithmetic
# ---------------------------------------------------------------------------

def parse_hhmm(text: str) -> int:
    """Parse strict HH:MM into minutes from midnight."""
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError("expected HH:MM, got %r" % text)
    hh, mm = parts[0], parts[1]
    if len(hh) != 2 or len(mm) != 2 or not hh.isdigit() or not mm.isdigit():
        raise ValueError("expected zero-padded HH:MM, got %r" % text)
    h, m = int(hh), int(mm)
    if h > 23 or m > 59:
        raise ValueError("out-of-range time %r" % text)
    return h * 60 + m


def fmt_clock(minutes: float) -> str:
    """Minutes-from-midnight -> HH:MM (wraps around the 24h clock)."""
    m = int(round(minutes)) % MINUTES_PER_DAY
    return "%02d:%02d" % (m // 60, m % 60)


def fmt_dur(minutes: float) -> str:
    m = int(round(minutes))
    return "%dh%02dm" % (m // 60, m % 60)


def fmt_signed(minutes: float) -> str:
    m = int(round(minutes))
    sign = "+" if m >= 0 else "-"
    m = abs(m)
    return "%s%dh%02dm" % (sign, m // 60, m % 60)


# ---------------------------------------------------------------------------
# log parsing
# ---------------------------------------------------------------------------

@dataclass
class Night:
    date: str
    sleep: int          # minutes from midnight, may be past 24h boundary
    wake: int
    kind: str           # "work" | "free"
    line: int
    alarm: str = ""     # optional 5th column, kept verbatim for future use

    @property
    def duration(self) -> int:
        return (self.wake - self.sleep) % MINUTES_PER_DAY

    @property
    def midpoint(self) -> float:
        return (self.sleep + self.duration / 2.0) % MINUTES_PER_DAY


class LogError(ValueError):
    """A bad log file; message carries the 1-based line number."""


def read_log(path: str) -> List[Night]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw_lines = fh.read().splitlines()
    except OSError as exc:
        raise LogError("cannot read log file: %s" % exc)

    nights: List[Night] = []
    seen_dates = {}
    saw_header = False
    for idx, raw in enumerate(raw_lines, start=1):
        line = raw.strip("\r").rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        if cols and cols[0] == "date":
            if saw_header or nights:
                raise LogError("line %d: duplicate header row" % idx)
            saw_header = True
            continue
        if len(cols) < 4:
            raise LogError(
                "line %d: expected 4 tab-separated columns "
                "(date sleep wake kind), got %d" % (idx, len(cols)))
        date_str, sleep_s, wake_s, kind = cols[0], cols[1], cols[2], cols[3]
        try:
            _date.fromisoformat(date_str)
        except ValueError:
            raise LogError("line %d: bad date %r (want YYYY-MM-DD)" % (idx, date_str))
        try:
            sleep_m = parse_hhmm(sleep_s)
            wake_m = parse_hhmm(wake_s)
        except ValueError as exc:
            raise LogError("line %d: %s" % (idx, exc))
        if kind not in ("work", "free"):
            raise LogError("line %d: kind must be 'work' or 'free', got %r"
                           % (idx, kind))
        if sleep_m == wake_m:
            raise LogError(
                "line %d: sleep and wake are the same minute (%s) — "
                "cannot tell 0h from 24h" % (idx, sleep_s))
        if date_str in seen_dates:
            raise LogError("line %d: duplicate date %s (first seen on line %d)"
                           % (idx, date_str, seen_dates[date_str]))
        seen_dates[date_str] = idx
        nights.append(Night(date=date_str, sleep=sleep_m, wake=wake_m,
                            kind=kind, line=idx,
                            alarm=cols[4] if len(cols) > 4 else ""))
    if not nights:
        raise LogError("no data rows found (lines starting with '#' are "
                       "comments; the first row may be a 'date' header)")
    return nights


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def median(values: List[float]) -> float:
    vs = sorted(values)
    n = len(vs)
    if n % 2 == 1:
        return vs[n // 2]
    return (vs[n // 2 - 1] + vs[n // 2]) / 2.0


def center(values: List[float], use_mean: bool) -> float:
    """Median by default (robust to one party night); --mean for the
    original MCTQ questionnaire convention."""
    if use_mean:
        return sum(values) / len(values)
    return median(values)


@dataclass
class Metrics:
    n_work: int
    n_free: int
    span_days: int
    first_date: str
    last_date: str
    sd_work: float            # median (or mean) work-night duration, minutes
    sd_free: float
    msw: float                # work-night sleep midpoint
    msf: float                # free-night sleep midpoint
    sd_week: float            # week-average duration, actual work/free ratio
    msf_sc: float             # MSF corrected for repayment oversleep
    sjl: float                # msf - msw (minutes; positive = owl side)
    sjl_sc: float
    bd_day: float             # sleep debt per work night (median basis)
    bd_week: float            # x weekly work-night share
    bd_year: float            # x 52 weeks
    work_per_week: float
    free_per_week: float
    repay_owed: float         # total work-night shortfall vs SDf
    repay_paid: float         # total free-night oversleep vs SDw
    repay_rate: float         # paid / owed, or -1.0 when nothing is owed

    @property
    def grade(self) -> str:
        return grade_of(self.sjl)

    @property
    def grade_sc(self) -> str:
        return grade_of(self.sjl_sc)

    def warnings(self) -> List[str]:
        out = []
        if self.n_work < MIN_WORK_DAYS_WARN:
            out.append("only %d work nights logged — MSW and the debt "
                       "account are unstable" % self.n_work)
        if self.n_free < MIN_FREE_DAYS_WARN:
            out.append("only %d free nights logged — MSF is unstable; "
                       "log more free days" % self.n_free)
        if self.span_days < MIN_SPAN_DAYS_WARN:
            out.append("log spans %d days — two full weeks is the minimum "
                       "for a stable read" % self.span_days)
        return out


def grade_of(sjl: float) -> str:
    sjl = abs(sjl)
    if sjl >= RED_LINE_MIN:
        return "HIGH"
    if sjl >= YELLOW_LINE_MIN:
        return "DRIFTING"
    return "ALIGNED"


def grade_mark(grade: str) -> str:
    return {"HIGH": "!!", "DRIFTING": "~~", "ALIGNED": "OK"}[grade]


def compute_metrics(nights: List[Night], use_mean: bool = False) -> Metrics:
    work = [n for n in nights if n.kind == "work"]
    free = [n for n in nights if n.kind == "free"]
    if not work or not free:
        raise LogError(
            "log has %d work / %d free nights — SJL needs at least one of "
            "each (free = no alarm, no forced schedule)" % (len(work), len(free)))

    dates = sorted(n.date for n in nights)
    span = (_date.fromisoformat(dates[-1]) - _date.fromisoformat(dates[0])).days + 1

    sd_work = center([float(n.duration) for n in work], use_mean)
    sd_free = center([float(n.duration) for n in free], use_mean)
    msw = center([n.midpoint for n in work], use_mean)
    msf = center([n.midpoint for n in free], use_mean)

    n_total = len(nights)
    sd_week = (sd_work * len(work) + sd_free * len(free)) / n_total
    # MCTQ-style correction: free-day oversleep beyond the week average is
    # assumed to be half debt repayment, and repayment happens on the
    # morning side — so pull the free midpoint back by half of it.
    oversleep = max(0.0, sd_free - sd_week)
    msf_sc = msf - oversleep / 2.0

    sjl = msf - msw
    sjl_sc = msf_sc - msw

    bd_day = max(0.0, sd_free - sd_work)
    work_per_week = len(work) * 7.0 / n_total
    free_per_week = len(free) * 7.0 / n_total
    bd_week = bd_day * work_per_week
    bd_year = bd_week * 52.0

    repay_owed = sum(max(0.0, sd_free - n.duration) for n in work)
    repay_paid = sum(max(0.0, n.duration - sd_work) for n in free)
    repay_rate = (repay_paid / repay_owed) if repay_owed > 0 else -1.0

    return Metrics(
        n_work=len(work), n_free=len(free), span_days=span,
        first_date=dates[0], last_date=dates[-1],
        sd_work=sd_work, sd_free=sd_free, msw=msw, msf=msf, sd_week=sd_week,
        msf_sc=msf_sc, sjl=sjl, sjl_sc=sjl_sc,
        bd_day=bd_day, bd_week=bd_week, bd_year=bd_year,
        work_per_week=work_per_week, free_per_week=free_per_week,
        repay_owed=repay_owed, repay_paid=repay_paid, repay_rate=repay_rate,
    )


# ---------------------------------------------------------------------------
# narratives
# ---------------------------------------------------------------------------

def jetlag_sentence(m: Metrics) -> List[str]:
    """The verdict block: deterministic English, no medical advice."""
    lag = int(round(abs(m.sjl)))
    lines = []
    if abs(m.sjl) < YELLOW_LINE_MIN:
        lines.append("No meaningful jetlag: your biological and social clocks")
        lines.append("agree. If mornings still hurt, look at the debt account.")
        if m.bd_day > 0:
            lines.append("Yours says %s per work night — that is the one to fix."
                         % fmt_dur(m.bd_day))
        return lines
    if m.sjl > 0:
        lines.append("Your free nights end %s later on the clock than your work"
                     % fmt_dur(lag))
        lines.append("nights. Every week you fly twice: forward every free day,")
        lines.append("back with every alarm day — the commute your bed makes.")
    else:
        lines.append("Your free nights end %s earlier on the clock than your"
                     % fmt_dur(lag))
        lines.append("work nights (lark or shift pattern). The mismatch is the")
        lines.append("mirror image of the owl's, and it bills the same way.")
    if m.repay_rate < 0:
        pass
    elif m.repay_rate < 1.0:
        lines.append("The free-day oversleep repays only %d%% of the work debt —"
                     % int(round(m.repay_rate * 100)))
        lines.append("you are paying jetlag for a loan you are not repaying.")
    else:
        lines.append("The oversleep does repay the debt (%d%%) — but the fare is"
                     % int(round(m.repay_rate * 100)))
        lines.append("crossing your own time zone twice a week, every week.")
    return lines


def repay_text(m: Metrics) -> str:
    if m.repay_rate < 0:
        return "n/a (no positive work-night debt)"
    return "%d%%  (%d repaid of %d owed)" % (
        int(round(m.repay_rate * 100)),
        int(round(m.repay_paid)), int(round(m.repay_owed)))


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def report_text(path: str, m: Metrics) -> str:
    warn = m.warnings()
    lines = [
        "-- Social Jetlag report: %s" % path,
        "  nights logged          : %d  (%d work / %d free · %s .. %s)"
        % (m.n_work + m.n_free, m.n_work, m.n_free, m.first_date, m.last_date),
        "  sleep duration         : work %s · free %s"
        % (fmt_dur(m.sd_work), fmt_dur(m.sd_free)),
        "  sleep midpoint         : work %s (MSW) · free %s (MSF)"
        % (fmt_clock(m.msw), fmt_clock(m.msf)),
        "  MSFsc (debt-corrected) : %s" % fmt_clock(m.msf_sc),
        "  social jetlag          : %s   %s %s   (red line = 2h)"
        % (fmt_signed(m.sjl), grade_mark(m.grade), m.grade),
        "  debt-corrected SJL     : %s   %s %s"
        % (fmt_signed(m.sjl_sc), grade_mark(m.grade_sc), m.grade_sc),
        "  sleep debt             : %s per work night · %s per week · %s per year"
        % (fmt_dur(m.bd_day), fmt_dur(m.bd_week), fmt_dur(m.bd_year)),
        "  weekend repay rate     : %s" % repay_text(m),
        "  warnings               : %s" % ("; ".join(warn) if warn else "none"),
        "",
    ]
    lines += jetlag_sentence(m)
    return "\n".join(lines) + "\n"


def report_json(path: str, m: Metrics) -> str:
    doc = {
        "file": path,
        "n_nights": m.n_work + m.n_free,
        "n_work": m.n_work,
        "n_free": m.n_free,
        "span_days": m.span_days,
        "first_date": m.first_date,
        "last_date": m.last_date,
        "sd_work_min": m.sd_work,
        "sd_free_min": m.sd_free,
        "msw_min": m.msw,
        "msf_min": m.msf,
        "msf_sc_min": m.msf_sc,
        "sjl_min": m.sjl,
        "sjl_sc_min": m.sjl_sc,
        "grade": m.grade,
        "grade_debt_corrected": m.grade_sc,
        "bd_day_min": m.bd_day,
        "bd_week_min": m.bd_week,
        "bd_year_min": m.bd_year,
        "work_per_week": m.work_per_week,
        "free_per_week": m.free_per_week,
        "repay_rate": m.repay_rate,
        "repay_owed_min": m.repay_owed,
        "repay_paid_min": m.repay_paid,
        "warnings": m.warnings(),
        "verdict": " ".join(jetlag_sentence(m)),
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# simulations
# ---------------------------------------------------------------------------

def simulate_flat(nights: List[Night], m: Metrics, use_mean: bool) -> Metrics:
    """Free nights keep their bedtime but drop to the work-median duration:
    no oversleep. Phase (bedtime) is held fixed — that is the point: it
    separates the debt account from the phase account."""
    free = [n for n in nights if n.kind == "free"]
    shifted = [Night(date=n.date, sleep=n.sleep,
                     wake=(n.sleep + int(round(m.sd_work))) % MINUTES_PER_DAY,
                     kind="free", line=n.line) for n in free]
    work = [n for n in nights if n.kind == "work"]
    return compute_metrics(work + shifted, use_mean)


def simulate_anchor(nights: List[Night], shift_min: float, use_mean: bool) -> Metrics:
    """Shift every free night by shift_min minutes (positive = earlier):
    bedtime and wake move together, duration is unchanged."""
    moved = [Night(date=n.date,
                   sleep=(n.sleep - int(round(shift_min))) % MINUTES_PER_DAY,
                   wake=(n.wake - int(round(shift_min))) % MINUTES_PER_DAY,
                   kind=n.kind, line=n.line) if n.kind == "free" else n
             for n in nights]
    return compute_metrics(moved, use_mean)


def simulate_report(scenario: str, path: str, base: Metrics,
                    sim: Metrics, extra: Optional[dict] = None,
                    debt_line: Optional[str] = None) -> str:
    header = "-- Simulation (%s): %s" % (scenario, path)
    if debt_line is None:
        debt_line = ("  weekly sleep debt     : %s -> %s  (repay %s)"
                     % (fmt_dur(base.bd_week), fmt_dur(sim.bd_week),
                        repay_text(sim)))
    lines = [
        header,
        "  midpoint free         : %s -> %s (MSF)"
        % (fmt_clock(base.msf), fmt_clock(sim.msf)),
        "  social jetlag         : %s -> %s  (%s %s -> %s %s)"
        % (fmt_signed(base.sjl), fmt_signed(sim.sjl),
           grade_mark(base.grade), base.grade,
           grade_mark(sim.grade), sim.grade),
        debt_line,
    ]
    if extra:
        lines = lines[:1] + extra + lines[1:]
    return "\n".join(lines) + "\n"


def flat_debt_line(base: Metrics) -> str:
    return ("  weekly sleep debt     : %s per week (unchanged — flat closes the\n"
            "                          account, not the debt: the need goes "
            "unmeasured)" % fmt_dur(base.bd_week))


def flat_verdict(base: Metrics, sim: Metrics) -> List[str]:
    delta = max(0.0, base.sjl - sim.sjl)
    lines = []
    if delta > 0.5:
        lines.append("  verdict: killing the oversleep removes %s of jetlag and"
                     % fmt_dur(delta))
        lines.append("  stops the repayment entirely. Whatever jetlag remains")
        lines.append("  is phase, not debt — 'just stop sleeping in' does not")
        lines.append("  fix a chronotype, it only starves the ledger.")
    else:
        lines.append("  verdict: going flat removes no jetlag at all — this")
        lines.append("  mismatch is pure phase, not debt. The oversleep was")
        lines.append("  never the disease; it was the receipt.")
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def validate_text(path: str, nights: List[Night]) -> str:
    work = [n for n in nights if n.kind == "work"]
    free = [n for n in nights if n.kind == "free"]
    dates = sorted(n.date for n in nights)
    span = (_date.fromisoformat(dates[-1]) - _date.fromisoformat(dates[0])).days + 1
    warns = []
    if len(work) < MIN_WORK_DAYS_WARN:
        warns.append("only %d work nights" % len(work))
    if len(free) < MIN_FREE_DAYS_WARN:
        warns.append("only %d free nights" % len(free))
    if span < MIN_SPAN_DAYS_WARN:
        warns.append("span of %d days is short" % span)
    long_nights = [n for n in nights if n.duration > 16 * 60]
    if long_nights:
        warns.append("%d night(s) over 16h — check for typos (%s...)"
                     % (len(long_nights), long_nights[0].date))
    lines = [
        "-- Log check: %s" % path,
        "  rows parsed           : %d  (%d work / %d free · %s .. %s)"
        % (len(nights), len(work), len(free), dates[0], dates[-1]),
        "  SJL computable        : %s"
        % ("yes" if (work and free) else "no — need at least one night of each kind"),
        "  warnings              : %s" % ("; ".join(warns) if warns else "none"),
    ]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="social_jetlag.py",
        description="social-jetlag · turn a hand-kept sleep log into the two "
                    "accounts 'tired' conflates: sleep debt and social jetlag.")
    sub = parser.add_subparsers(dest="cmd")

    p_report = sub.add_parser(
        "report", help="MSW / MSF / SJL / debt ledger from a sleep log")
    p_report.add_argument("log", help="TSV: date, sleep HH:MM, wake HH:MM, kind")
    p_report.add_argument("--format", choices=("text", "json"), default="text")
    p_report.add_argument("--mean", action="store_true",
                          help="use means instead of medians (MCTQ convention)")
    p_report.add_argument("--fail-over", type=int, default=None, metavar="MIN",
                          help="exit 4 when |SJL| exceeds MIN minutes")

    p_sim = sub.add_parser(
        "simulate", help="counterfactuals: flat / anchor MIN / target MIN")
    p_sim.add_argument("log", help="TSV sleep log")
    p_sim.add_argument("scenario", choices=("flat", "anchor", "target"))
    p_sim.add_argument("value", nargs="?", type=int, default=None,
                       help="minutes: anchor shift (+ = earlier) or |SJL| target")
    p_sim.add_argument("--mean", action="store_true")

    p_val = sub.add_parser("validate", help="parse check + sample-size warnings")
    p_val.add_argument("log", help="TSV sleep log")

    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return EXIT_USAGE

    try:
        nights = read_log(args.log)
    except LogError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_INPUT

    if args.cmd == "validate":
        print(validate_text(args.log, nights), end="")
        return EXIT_OK

    use_mean = getattr(args, "mean", False)
    try:
        base = compute_metrics(nights, use_mean)
        if args.cmd == "report":
            out = (report_json(args.log, base) if args.format == "json"
                   else report_text(args.log, base))
            print(out, end="")
            if args.fail_over is not None and abs(base.sjl) > args.fail_over:
                print("gate: |SJL| %s exceeds --fail-over %dm"
                      % (fmt_signed(base.sjl), args.fail_over), file=sys.stderr)
                return EXIT_GATE
            return EXIT_OK

        scenario = args.scenario
        if scenario == "flat":
            sim = simulate_flat(nights, base, use_mean)
            print(simulate_report("flat", args.log, base, sim,
                                  debt_line=flat_debt_line(base)), end="")
            print("\n".join(flat_verdict(base, sim)), end="\n")
            return EXIT_OK
        if args.value is None:
            print("error: '%s' needs a minute value" % scenario,
                  file=sys.stderr)
            return EXIT_USAGE
        if scenario == "anchor":
            sim = simulate_anchor(nights, args.value, use_mean)
            direction = "EARLIER" if args.value >= 0 else "LATER"
            extra = [
                "  assumption            : free nights shift %d min %s "
                "(both ends, duration kept)" % (abs(args.value), direction),
            ]
            print(simulate_report("anchor", args.log, base, sim, extra), end="")
            return EXIT_OK
        # target: shift free nights toward the work midpoint until |SJL| <= goal
        goal = args.value
        gap = abs(base.sjl) - goal
        if gap <= 0:
            extra = [
                "  goal                  : |SJL| <= %d min (already %s)"
                % (goal, fmt_signed(base.sjl)),
                "  required shift        : none — already at or below target",
            ]
            print(simulate_report("target", args.log, base, base, extra), end="")
            return EXIT_OK
        # positive anchor shift = earlier; move the free midpoint toward MSW
        shift = gap if base.sjl > 0 else -gap
        sim = simulate_anchor(nights, shift, use_mean)
        arrow = "EARLIER" if base.sjl > 0 else "LATER"
        reached = abs(sim.sjl) <= goal + 1e-9
        extra = [
            "  goal                  : |SJL| <= %d min (from %s)"
            % (goal, fmt_signed(base.sjl)),
            "  required shift        : free nights %d min %s (both ends, "
            "duration kept)" % (int(round(gap)), arrow),
        ]
        print(simulate_report("target", args.log, base, sim, extra), end="")
        lines = [
            "  verdict: moving your free nights %s by %s lands at %s —"
            % (arrow, fmt_dur(gap), fmt_signed(sim.sjl)),
            "  reached: %s" % ("yes" if reached else "no"),
        ]
        print("\n".join(lines))
        return EXIT_OK
    except LogError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":
    sys.exit(main())
