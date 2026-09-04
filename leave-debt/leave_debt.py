#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""欠休 · Leave Debt —— 年假债权账本.

年假是工资的一部分，却是唯一不发对账单的工资：月薪迟到一分钟你都知道，
三天年假作废一分钱声音都没有。HR 系统只给你一个余额数字，不给批次、
不给到期日、不给「按你自己的休假节奏，年底会有几天蒸发」的预测；
碎片化的假（休了 9 天、最长连休 1 天）和真休了假，在 HR 报表里长得一模一样。

本件把年假当成**按批次计息的债权**来记账（两本可手编 TSV）：
  grants.tsv —— 批次授权：哪天授予、几天、哪天清零（结转规则从此白箱）；
  leave.tsv  —— 休假流水：哪天开始、几天、annual 消耗额度 / other 额度外。
工具重放出五本账：
  批次账   FIFO 先到期先消耗，作废在到期日**终了**入账（当天还能用）；
  损失账   作废天数 × 日薪（--daily-rate 或 --monthly-salary ÷ 月计薪天数；
           不给工资就不折钱——不发明你的收入）；
  节奏账   时间进度 vs 消耗进度，burn（已休 ÷ 覆盖天数）线性外推将来作废；
  形状账   连休段 = 极大连续「自由日」区间（自由日 = 休假 ∪ 周末 ∪
           --holidays 法定日），拼假杠杆 = 段跨度 ÷ 段内年假天数——
           9/29 休是 1.0，9/30 休是 9.0，桥就一板之隔；
  还款计划 把余额按周窗口摊到各自到期日；常态节奏（--pace-cap）装不下时
           如实说「注定作废 X 天」——休息是工资，不休假是自愿降薪。

设计立场：
  「今天」绝不取自系统时钟 —— 缺省 as-of = 账本最大日期（含批次到期日：
  作废也是事件），--as-of 显式钉死，同一本账任何机器逐字节一致。
  算术门禁不拒答，统计门禁拒薄账 —— 批次临期是账本事实，账再薄也爆灯；
  节奏外推是统计推断，覆盖 < 60 天或年假行 < 3 时如实 DECLINE exit 3。
  拒答优先 —— 宁可不说，不编一个判决。

零依赖：Python 3.8+ 纯标准库。MIT © 2026
"""

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

EXIT_OK = 0
EXIT_BROKEN = 2      # 账本结构性损坏
EXIT_DECLINE = 3     # 样本不足，拒绝统计判决
EXIT_REDLINE = 4     # 红线：临期作废 / 节奏性作废 / 计划装不下

WARN_DAYS = 45         # 批次临期门禁：余额 > 0 且 45 天内清零 → exit 4
FORECAST_LINE = 0.15   # 节奏门禁：预测作废 > 总授予 × 15% → exit 4
PACE_CAP = 1.0         # 还款计划默认常态节奏：1.0 天/周
PAY_DAYS = 21.75       # 月计薪天数（(365-104)/12，中国劳动法口径，可 --pay-days 覆盖）
MIN_SPAN_DAYS = 60     # 覆盖 < 60 天：节奏外推拒判
MIN_TAKES = 3          # 年假行 < 3：节奏外推拒判
LEVER_SMART = 2.0      # 杠杆 >= 2.0 聪明假（借来的时间 >= 付出的额度）
LEVER_FULL = 1.5       # 杠杆 < 1.5 全价假（1 天额度买 1 天，中间无桥）
FRAG_SPAN = 2          # 段跨度 < 2 = 碎片段（没吃到任何桥）

WEEKDAY_CN = ("一", "二", "三", "四", "五", "六", "日")


def fmt_days(v: float) -> str:
    return "%.1f" % v


def fmt_money(v: float) -> str:
    return "¥" + format(round(v, 2), ",.2f")


class LedgerBroken(Exception):
    pass


# ---------------------------------------------------------------- 日期工具

def parse_date(s: str, where: str, lineno: int) -> date:
    try:
        y, m, d = s.strip().split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        raise LedgerBroken("%s 第 %s 行: 坏日期 %r（要 ISO 的 YYYY-MM-DD）" % (where, lineno, s))


def parse_half(s: str, where: str, lineno: int, col: str) -> float:
    try:
        v = float(s.strip())
    except Exception:
        raise LedgerBroken("%s 第 %d 行: %s 不是数字 %r" % (where, lineno, col, s))
    if v <= 0:
        raise LedgerBroken("%s 第 %d 行: %s 必须 > 0，实得 %g" % (where, lineno, col, v))
    if abs(v * 2 - round(v * 2)) > 1e-9:
        raise LedgerBroken("%s 第 %d 行: %s 必须 0.5 步进，实得 %g" % (where, lineno, col, v))
    return v


# ---------------------------------------------------------------- 账本模型

@dataclass
class Grant:
    """一批假期债权：授予日生效、到期日终了清零（到期当天还能用）。"""
    lineno: int
    granted: date
    days: float
    expires: date
    note: str
    used: float = 0.0
    voided: float = 0.0

    @property
    def balance(self) -> float:
        return round(self.days - self.used - self.voided, 6)

    @property
    def span(self) -> int:
        return max(1, (self.expires - self.granted).days)


@dataclass
class Take:
    """一次休假。annual 消耗额度；other（调休/病假/事假）额度外。"""
    lineno: int
    start: date
    days: float
    kind: str
    note: str
    charges: List[Tuple[int, float]] = field(default_factory=list)  # (grant 序号, 天数)


@dataclass
class Ledger:
    grants: List[Grant]
    takes: List[Take]          # 全部流水（结构校验用）
    live_takes: List[Take]     # as-of 截断后参与重放的流水
    future_takes: List[Take]   # 被截断的未来流水
    holidays: List[Tuple[date, date]]
    makeup_days: List[date]    # 调休补班日：本该休息的周末要上班
    as_of: date
    as_of_source: str

    def is_free_day(self, d: date) -> bool:
        """自由日：周末 ∪ 法定节假日 − 调休补班日（中国假期的真实结构）。"""
        if d in self.makeup_days:
            return False
        if d.weekday() >= 5:
            return True
        for a, b in self.holidays:
            if a <= d <= b:
                return True
        return False


# ---------------------------------------------------------------- 解析

def read_tsv(path: str, needed: Tuple[str, ...]) -> List[Dict[str, str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as e:
        raise LedgerBroken("读不了 %s: %s" % (path, e))
    header = None
    rows = []
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        if header is None:
            header = [c.strip() for c in cells]
            missing = [c for c in needed if c not in header]
            if missing:
                raise LedgerBroken("%s 表头缺列: %s（要 %s）"
                                   % (path, ",".join(missing), ",".join(needed)))
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append({"_lineno": i, **dict(zip(header, [c.strip() for c in cells]))})
    if header is None:
        raise LedgerBroken("%s 是空的（连表头都没有）" % path)
    return rows


def parse_holidays(path: str) -> Tuple[List[Tuple[date, date]], List[date]]:
    """返回（法定假日区间, 调休补班日）。

    语法：`2025-10-01..2025-10-08` 或 `2025-01-01` 为假日；
    `!2025-09-28` 为调休补班日——那个周日要上班，从周末里扣掉。
    """
    out: List[Tuple[date, date]] = []
    makeup: List[date] = []
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as e:
        raise LedgerBroken("读不了 %s: %s" % (path, e))
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for tok in line.replace("，", ",").split(","):
            tok = tok.strip()
            if not tok:
                continue
            if tok.startswith("!"):
                makeup.append(parse_date(tok[1:], path, i))
                continue
            if ".." in tok:
                a, b = tok.split("..", 1)
                d0 = parse_date(a, path, i)
                d1 = parse_date(b, path, i)
                if d1 < d0:
                    raise LedgerBroken("%s 第 %d 行: 区间反了 %s" % (path, i, tok))
                out.append((d0, d1))
            else:
                d = parse_date(tok, path, i)
                out.append((d, d))
    return out, makeup


def load_ledger(grants_path: str, leave_path: str,
                holidays_path: Optional[str], as_of: Optional[str]) -> Ledger:
    grants = []
    for r in read_tsv(grants_path, ("grant_date", "days", "expires")):
        g = Grant(
            lineno=r["_lineno"],
            granted=parse_date(r["grant_date"], grants_path, r["_lineno"]),
            days=parse_half(r["days"], grants_path, r["_lineno"], "days"),
            expires=parse_date(r["expires"], grants_path, r["_lineno"]),
            note=r.get("note", ""),
        )
        if g.expires <= g.granted:
            raise LedgerBroken("%s 第 %d 行: expires (%s) 必须晚于 grant_date (%s)"
                               % (grants_path, g.lineno, g.expires, g.granted))
        grants.append(g)
    if not grants:
        raise LedgerBroken("%s 没有任何批次行——没有债权，谈何欠休" % grants_path)
    grants.sort(key=lambda g: (g.granted, g.expires, g.lineno))

    takes = []
    for r in read_tsv(leave_path, ("date", "days", "type")):
        kind = r.get("type", "").strip()
        if kind not in ("annual", "other"):
            raise LedgerBroken("%s 第 %d 行: type 只能 annual/other，实得 %r"
                               % (leave_path, r["_lineno"], kind))
        takes.append(Take(
            lineno=r["_lineno"],
            start=parse_date(r["date"], leave_path, r["_lineno"]),
            days=parse_half(r["days"], leave_path, r["_lineno"], "days"),
            kind=kind,
            note=r.get("note", ""),
        ))
    takes.sort(key=lambda t: (t.start, t.lineno))

    holidays, makeup = parse_holidays(holidays_path) if holidays_path else ([], [])

    # 缺省 as-of = 账本最大日期（含批次到期日：作废也是事件）
    all_dates = ([g.granted for g in grants] + [g.expires for g in grants]
                 + [t.start for t in takes])
    if as_of:
        as_of_d = parse_date(as_of, "--as-of", 0)
        src = "--as-of %s" % as_of
    else:
        as_of_d = max(all_dates)
        src = "账本末日"
    live = [t for t in takes if t.start <= as_of_d]
    future = [t for t in takes if t.start > as_of_d]
    return Ledger(grants, takes, live, future, holidays, makeup, as_of_d, src)


# ---------------------------------------------------------------- FIFO 重放

def replay(led: Ledger, trunc_for_validate: bool = True) -> None:
    """休假按日期 FIFO 消耗：先到期先消耗（到期日当天可用）。

    - 批次在 d 当天可用 ⇔ granted <= d <= expires 且当日余额 > 0；
    - 同到期日按授予日早的先用，再按账本行序；
    - 无批可扣 = 预支（休在全部授予前）或透支（额度不够）→ exit 2；
    - 作废：as-of 晚于到期日时，到期日终了还挂着的就是作废。
    """
    pool = led.live_takes if trunc_for_validate else led.takes
    for t in pool:
        need = t.days
        if t.kind != "annual":
            continue
        cands = [g for g in led.grants if g.granted <= t.start <= g.expires]
        if not cands:
            raise LedgerBroken("leave.tsv 第 %d 行: %s 休在全部批次覆盖之外"
                               "（授予前预支或授予后远期）" % (t.lineno, t.start))
        cands.sort(key=lambda g: (g.expires, g.granted, g.lineno))
        for g in cands:
            room = round(g.days - g.used - g.voided, 6)
            if room <= 1e-9:
                continue
            use = min(room, need)
            g.used = round(g.used + use, 6)
            t.charges.append((led.grants.index(g), use))
            need = round(need - use, 6)
            if need <= 1e-9:
                break
        if need > 1e-9:
            raise LedgerBroken("leave.tsv 第 %d 行: %s 休 %s 天，当时可用余额不足——透支"
                               % (t.lineno, t.start, fmt_days(t.days)))
    for g in led.grants:
        if led.as_of > g.expires:
            used_by = sum(u for t in pool if t.kind == "annual"
                          for idx, u in t.charges
                          if led.grants[idx] is g and t.start <= g.expires)
            g.voided = round(g.days - used_by, 6)


def totals(led: Ledger) -> Dict[str, float]:
    granted = sum(g.days for g in led.grants)
    used = sum(t.days for t in led.live_takes if t.kind == "annual")
    voided = sum(g.voided for g in led.grants)
    balance = sum(max(0.0, g.balance) for g in led.grants)
    return {"granted": granted, "used": used, "voided": voided, "balance": balance}


def daily_rate(args) -> Optional[float]:
    if getattr(args, "daily_rate", None):
        return args.daily_rate
    if getattr(args, "monthly_salary", None):
        pay_days = getattr(args, "pay_days", None) or PAY_DAYS
        return args.monthly_salary / pay_days
    return None


def rate_note(args) -> str:
    if getattr(args, "daily_rate", None):
        return "日薪 %s（--daily-rate）" % fmt_money(args.daily_rate)
    if getattr(args, "monthly_salary", None):
        return "日薪 %s（月薪 %s ÷ 月计薪 %.2f）" % (
            fmt_money(daily_rate(args)), fmt_money(args.monthly_salary),
            getattr(args, "pay_days", None) or PAY_DAYS)
    return "未给工资参数，损失只按天数计（--monthly-salary 或 --daily-rate 可折钱）"


def cover_days(led: Ledger) -> int:
    firsts = [g.granted for g in led.grants]
    firsts += [t.start for t in led.live_takes] or [led.as_of]
    return (led.as_of - min(firsts)).days + 1


def thin(led: Ledger) -> bool:
    n_annual = len([t for t in led.live_takes if t.kind == "annual"])
    return cover_days(led) < MIN_SPAN_DAYS or n_annual < MIN_TAKES


def forecast_void(led: Ledger, burn: float) -> float:
    """对每个在架批次线性外推：预测作废 = 余额 − burn × 剩余窗口。"""
    total = 0.0
    for g in led.grants:
        if g.balance <= 1e-9 or g.expires <= led.as_of:
            continue
        window = (g.expires - led.as_of).days
        total += max(0.0, g.balance - burn * window)
    return total


# ---------------------------------------------------------------- 形状：连休段

@dataclass
class Segment:
    start: date
    end: date
    span: int
    annual: float
    other: float

    @property
    def lever(self) -> Optional[float]:
        if self.annual <= 0:
            return None
        return self.span / self.annual

    @property
    def grade(self) -> str:
        lv = self.lever
        if lv is None:
            return "额度外"
        if lv >= LEVER_SMART:
            return "聪明假"
        if lv >= LEVER_FULL:
            return "平价假"
        return "全价假"


def occupancy(led: Ledger) -> Dict[date, Tuple[float, float]]:
    """date -> (该日消耗的年假, 该日的额度外假)。0.5 天按半天累计。"""
    occ: Dict[date, Tuple[float, float]] = {}
    for t in led.live_takes:
        d, left = t.start, t.days
        while left > 1e-9:
            day = min(1.0, left)
            a, o = occ.get(d, (0.0, 0.0))
            if t.kind == "annual":
                occ[d] = (round(a + day, 6), o)
            else:
                occ[d] = (a, round(o + day, 6))
            left -= day
            d += timedelta(days=1)
    return occ


def segments(led: Ledger) -> List[Segment]:
    """连休段 = 从占用日向两端扩展到「工作日边界」的极大连续自由日区间。

    自由日 = 休假占用 ∪ 周末 ∪ 法定节假日。头尾桥都吃：周五休 1 天的段
    一直延到下周一前（span 3）；国庆后第一天休 1 天的段向前吃到 10/1
    （span 9）。悬在周中、前后都是工作日的假，span 就是它自己——全价假。
    """
    occ = occupancy(led)
    if not occ:
        return []
    segs: List[Segment] = []
    assigned: Dict[date, bool] = {}
    for seed in sorted(occ):
        if assigned.get(seed):
            continue
        s = e = seed
        one = timedelta(days=1)
        while True:
            prev = s - one
            if prev in occ or led.is_free_day(prev):
                s = prev
            else:
                break
        while True:
            nxt = e + one
            if nxt in occ or led.is_free_day(nxt):
                e = nxt
            else:
                break
        annual = sum(a for d, (a, _) in occ.items() if s <= d <= e)
        other = sum(o for d, (_, o) in occ.items() if s <= d <= e)
        segs.append(Segment(s, e, (e - s).days + 1, annual, other))
        d = s
        while d <= e:
            if d in occ:
                assigned[d] = True
            d += timedelta(days=1)
    segs.sort(key=lambda x: x.start)
    return segs


# ---------------------------------------------------------------- 命令

def cmd_report(led: Ledger, args) -> int:
    replay(led)
    tot = totals(led)
    rate = daily_rate(args)
    warn_days = getattr(args, "warn_days", WARN_DAYS)
    forecast_line = getattr(args, "forecast_line", FORECAST_LINE)
    code = EXIT_OK
    out = []
    out.append("== 欠休 · report (as-of %s, %s) ==" % (led.as_of, led.as_of_source))
    out.append(rate_note(args))
    out.append("")
    out.append("批次账（FIFO：先到期先消耗；到期日当天可用、日终清零）")
    out.append("  grant        days  expires      used  voided  balance  状态")
    for g in led.grants:
        if g.expires <= led.as_of:
            st = ("已清零：%s 作废 %s 天" % (g.expires, fmt_days(g.voided))
                  if g.voided > 0 else "已清零：休满归零")
        else:
            st = "在架 · %d 天倒计时（%s 清零）" % ((g.expires - led.as_of).days, g.expires)
        out.append("  %s  %4s  %s  %4s  %6s  %7s  %s"
                   % (g.granted, fmt_days(g.days), g.expires, fmt_days(g.used),
                      fmt_days(g.voided), fmt_days(g.balance), st))
    resid = tot["granted"] - tot["used"] - tot["voided"] - tot["balance"]
    out.append("守恒: %s = %s 已休 + %s 作废 + %s 余额 (残差 %.2e)"
               % (fmt_days(tot["granted"]), fmt_days(tot["used"]),
                  fmt_days(tot["voided"]), fmt_days(tot["balance"]), abs(resid)))
    if led.future_takes:
        out.append("披露: %d 行未来休假（%s 起）被 --as-of 截断，未入账"
                   % (len(led.future_takes), led.future_takes[0].start))
    out.append("")
    if tot["voided"] > 0:
        loss = "作废 %s 天" % fmt_days(tot["voided"])
        if rate:
            loss += " = %s（日薪 %s × %s 天）" % (fmt_money(tot["voided"] * rate),
                                                 fmt_money(rate), fmt_days(tot["voided"]))
        out.append("损失账: %s —— 已经蒸发的工资，没有人给你发对账单" % loss)
        out.append("")
    n_other = sum(t.days for t in led.live_takes if t.kind == "other")
    if n_other > 0:
        out.append("额度外休息: %s 天（调休/病假/事假）——它们也是休息，但不救年假的命"
                   % fmt_days(n_other))

    # 节奏账（统计推断，薄账拒判）
    cov = cover_days(led)
    out.append("")
    if thin(led):
        out.append("节奏账: DECLINE —— 覆盖 %d 天 < %d 天或年假行 < %d，"
                   "统计上连你自己的节奏都还没长出来，外推是编数（exit 3）"
                   % (cov, MIN_SPAN_DAYS, MIN_TAKES))
        code = EXIT_DECLINE
    else:
        burn = tot["used"] / cov
        out.append("节奏账: 覆盖 %d 天 · 年假已休 %s 天 · burn %.4f 天/天"
                   % (cov, fmt_days(tot["used"]), burn))
        for g in led.grants:
            if g.balance <= 1e-9 or g.expires <= led.as_of:
                continue
            t_prog = min(1.0, max(0.0, (led.as_of - g.granted).days / g.span))
            c_prog = min(1.0, g.used / g.days)
            out.append("  批次(%s 清零): 时间进度 %.1f%% vs 消耗进度 %.1f%% → 落后 %.1fpp"
                       % (g.expires, t_prog * 100, c_prog * 100,
                          max(0.0, (t_prog - c_prog) * 100)))
        fv = forecast_void(led, burn)
        if fv > 1e-9:
            msg = "外推: 按你的节奏，将来将作废 %s 天" % fmt_days(fv)
            if rate:
                msg += " = %s" % fmt_money(fv * rate)
            out.append("  " + msg)
        else:
            out.append("  外推: 按你的节奏，在架余额来得及休完——如果你保持这个节奏的话")

    # 门禁：L1 临期（算术事实，薄账也爆）+ L2 节奏性作废（统计推断，薄账拒判）
    gates = []
    for g in led.grants:
        if g.balance > 1e-9 and led.as_of < g.expires <= led.as_of + timedelta(days=warn_days):
            gates.append("✗ 临期作废: %s 天将在 %d 天后（%s）清零 —— 排假，否则它们不是你的"
                         % (fmt_days(g.balance), (g.expires - led.as_of).days, g.expires))
    if not thin(led):
        burn = tot["used"] / cov
        fv = forecast_void(led, burn)
        if tot["granted"] > 0 and fv / tot["granted"] > forecast_line:
            gates.append("✗ 节奏性作废: 预测作废 %s 天占授予 %.1f%% > %.0f%% 线"
                         " —— 按你自己的节奏，要有 %s 天直接蒸发"
                         % (fmt_days(fv), fv / tot["granted"] * 100, forecast_line * 100,
                            fmt_days(fv)))
    out.append("")
    if gates:
        out.append("门禁:")
        for gmsg in gates:
            out.append("  " + gmsg)
        out.append("  休息是工资，不休假是自愿降薪（exit 4）")
        code = EXIT_REDLINE
    else:
        out.append("门禁: 暂无红线（临期线 %d 天 / 预测线 %.0f%%）"
                   % (warn_days, forecast_line * 100))
    print("\n".join(out))
    return code


def cmd_shape(led: Ledger, args) -> int:
    replay(led)
    segs = segments(led)
    out = []
    hol_n = sum((b - a).days + 1 for a, b in led.holidays)
    out.append("== 欠休 · shape (as-of %s) ==" % led.as_of)
    out.append("连休段 = 极大连续自由日区间（自由日 = 休假 ∪ 周末 ∪ 法定日 %s − 调休补班日 %s）；"
               "杠杆 = 段跨度 ÷ 段内年假" % (
                   "%d 天" % hol_n if hol_n else "未提供",
                   ("%d 天" % len(led.makeup_days)) if led.makeup_days else "未提供"))
    out.append("")
    out.append("  start        end          span  annual  other  lever  判级")
    for s in segs:
        lv = s.lever
        out.append("  %s  %s  %4d  %6s  %5s  %5s  %s"
                   % (s.start, s.end, s.span, fmt_days(s.annual), fmt_days(s.other),
                      ("%.2f" % lv) if lv is not None else "—", s.grade))
    annual_segs = [s for s in segs if s.annual > 0]
    if not annual_segs:
        out.append("（没有消耗年假的休假——额度原封不动，欠休满血）")
        print("\n".join(out))
        return EXIT_OK
    if len([t for t in led.live_takes if t.kind == "annual"]) < MIN_TAKES:
        # 段落是日历算术，总可以看；判级与比率是统计，薄账拒判
        out.append("")
        out.append("形状统计: DECLINE —— 年假行 < %d，聪明/全价比率与碎片率不成立（exit 3）"
                   % MIN_TAKES)
        print("\n".join(out))
        return EXIT_DECLINE
    longest = max(annual_segs, key=lambda s: s.span)
    avg_lever = sum(s.span for s in annual_segs) / sum(s.annual for s in annual_segs)
    frags = [s for s in annual_segs if s.span < FRAG_SPAN]
    smart = [s for s in annual_segs if s.lever is not None and s.lever >= LEVER_SMART]
    fullp = [s for s in annual_segs if s.lever is not None and s.lever < LEVER_FULL]
    out.append("")
    out.append("形状账: %d 个含年假段 · 最长连休 %d 天（%s 起）· 平均杠杆 %.2fx（年假加权 Σspan ÷ Σannual）"
               % (len(annual_segs), longest.span, longest.start, avg_lever))
    if frags:
        out.append("  碎片段 %d/%d（span < %d 天，没吃到任何桥）: %s"
                   % (len(frags), len(annual_segs), FRAG_SPAN,
                      " · ".join("%s（%s 天）" % (s.start, fmt_days(s.annual)) for s in frags)))
        out.append("  —— 碎片假消耗额度却几乎不产出恢复：HR 报表里它们和连休长得一模一样")
    out.append("  聪明假 %d 段（杠杆 ≥ %.1f）· 全价假 %d 段（杠杆 < %.1f）"
               % (len(smart), LEVER_SMART, len(fullp), LEVER_FULL))
    if fullp:
        worst = min(fullp, key=lambda s: s.lever)
        out.append("  最亏的一笔: %s（周%s）span %d 天花掉 %s 天额度，杠杆 %.2f"
                   % (worst.start, WEEKDAY_CN[worst.start.weekday()],
                      worst.span, fmt_days(worst.annual), worst.lever))
        out.append("  —— 桥就一板之隔：挨着桥是 ≥%.1fx，悬在周中是 %.2fx"
                   % (LEVER_SMART, worst.lever))
    n_other = sum(s.other for s in segs)
    if n_other > 0:
        out.append("  额度外段 %d 个（%s 天）：调休/病假也是休息，但救不了年假的命"
                   % (len([s for s in segs if s.other > 0]), fmt_days(n_other)))
    print("\n".join(out))
    return EXIT_OK


def cmd_plan(led: Ledger, args) -> int:
    replay(led)
    cap = args.pace_cap
    rate = daily_rate(args)
    code = EXIT_OK
    out = []
    out.append("== 欠休 · plan (as-of %s, pace-cap %s 天/周) ==" % (led.as_of, fmt_days(cap)))
    open_grants = [g for g in led.grants if g.balance > 1e-9 and g.expires > led.as_of]
    if not open_grants:
        out.append("在架债权: 0 天 —— 无债可还（要么休完了，要么已经全蒸发了）。")
        print("\n".join(out))
        return code
    out.append("")
    infeasible = False
    for g in sorted(open_grants, key=lambda x: x.expires):
        left = (g.expires - led.as_of).days
        n_win = max(1, -(-left // 7))  # ceil：周窗口数
        need_rate = g.balance / (left / 7.0)
        out.append("在架债权: %s 天（%s 授予）· %s 清零 · 剩 %d 天 ≈ %d 窗 · 需 %.2f 天/周"
                   % (fmt_days(g.balance), g.granted, g.expires, left, n_win, need_rate))
        if g.balance > cap * n_win + 1e-9:
            infeasible = True
            gap = round(g.balance - cap * n_win, 6)
            msg = "  ✗ INFEASIBLE —— %d 窗 × %.1f 天 = %s < %s 天：常态节奏装不下，" \
                  "注定作废 %s 天" % (n_win, cap, fmt_days(cap * n_win),
                                     fmt_days(g.balance), fmt_days(gap))
            if rate:
                msg += "（%s）" % fmt_money(gap * rate)
            out.append(msg)
            out.append("    建议: 尾部几窗连起来休（连休不受周 cap 约束），"
                       "或接受作废并提前写进心理账户")
        else:
            out.append("  ✓ FEASIBLE —— 每周 %.2f 天即可全部落袋（这是最早到期的一座，先还它）"
                       % need_rate)
        out.append("")
        out.append("  周窗口计划（每窗 ≤ %s 天，先到期先还）:" % fmt_days(cap))
        remaining = g.balance
        win_start = led.as_of
        w = 0
        while remaining > 1e-9 and win_start < g.expires:
            w += 1
            win_end = min(win_start + timedelta(days=6), g.expires)
            take = min(cap, remaining)
            remaining = round(remaining - take, 6)
            mark = ""
            if remaining > 1e-9 and win_end == g.expires:
                mark = "  ← 超 cap:此窗实际需休 %s 天（连休/破例），否则 %s 天作废" \
                       % (fmt_days(take + remaining), fmt_days(remaining))
            elif take < cap - 1e-9:
                mark = "  ← 尾窗清零"
            out.append("    W%d  %s ~ %s   休 %s  → 余 %s%s"
                       % (w, win_start, win_end, fmt_days(take),
                          fmt_days(max(0.0, remaining)), mark))
            win_start += timedelta(days=7)
        out.append("")
    if infeasible:
        out.append("休息是工资，不休假是自愿降薪（exit 4）。")
        code = EXIT_REDLINE
    else:
        out.append("按这张表休，每一分假期都落袋。")
    print("\n".join(out))
    return code


def cmd_simulate(led: Ledger, args) -> int:
    replay(led)
    rate = daily_rate(args)
    on = parse_date(args.on, "--on", 0)
    take = args.take
    code = EXIT_OK
    out = []
    out.append("== 欠休 · simulate: %s 休 %s 天 (as-of %s) ==" % (on, fmt_days(take), led.as_of))
    if on <= led.as_of:
        out.append("DECLINE —— %s 不在 as-of %s 之后：模拟的是过去，过去不用模拟（exit 3）"
                   % (on, led.as_of))
        print("\n".join(out))
        return EXIT_DECLINE
    cands = [g for g in led.grants if g.granted <= on <= g.expires and g.balance > 1e-9]
    cands.sort(key=lambda g: (g.expires, g.granted))
    if not cands:
        out.append("DECLINE —— %s 没有可用批次（授予前/已清零/余额 0），查无此债（exit 3）" % on)
        print("\n".join(out))
        return EXIT_DECLINE
    avail = sum(g.balance for g in cands)
    if take > avail + 1e-9:
        out.append("透支 —— 想休 %s 天，%s 当天可用只有 %s 天：模拟跑不下去（exit 2）"
                   % (fmt_days(take), on, fmt_days(avail)))
        print("\n".join(out))
        return EXIT_BROKEN
    g = cands[0]
    before_bal = g.balance
    after_bal = round(before_bal - take, 6)
    out.append("过闸: 动用「%s 清零」批次（FIFO 最先到期）" % g.expires)
    out.append("  该批次 %s → %s · 距清零 %d 天" % (fmt_days(before_bal), fmt_days(after_bal),
                                                   (g.expires - on).days))
    if thin(led):
        out.append("预测: DECLINE —— 账太薄（覆盖 < %d 天或年假行 < %d），外推不成立（exit 3）"
                   % (MIN_SPAN_DAYS, MIN_TAKES))
        print("\n".join(out))
        return EXIT_DECLINE
    burn = totals(led)["used"] / cover_days(led)
    void_before = max(0.0, before_bal - burn * (g.expires - led.as_of).days)
    void_after = max(0.0, after_bal - burn * (g.expires - on).days)
    msg = "预测(线性 burn %.4f): 该批次预计作废 %.2f → %.2f 天" % (burn, void_before, void_after)
    if rate:
        msg += "（%s → %s）" % (fmt_money(void_before * rate), fmt_money(void_after * rate))
    out.append("  " + msg)
    granted = totals(led)["granted"]
    after_ratio = void_after / granted if granted > 0 else 0.0
    if after_ratio > FORECAST_LINE + 1e-9:
        out.append("判决: ✗ 这一笔之后仍超 %.0f%% 线（%.2f/%s = %.1f%%）"
                   " —— 一发入魂救不了，要的是节奏（exit 4）"
                   % (FORECAST_LINE * 100, void_after, fmt_days(granted), after_ratio * 100))
        code = EXIT_REDLINE
    else:
        out.append("判决: ✓ 这一笔把该批次的预计作废压回 %.0f%% 线内（%.1f%%）—— 保持住"
                   % (FORECAST_LINE * 100, after_ratio * 100))
    print("\n".join(out))
    return code


def cmd_validate(led: Ledger, args) -> int:
    replay(led)
    tot = totals(led)
    resid = tot["granted"] - tot["used"] - tot["voided"] - tot["balance"]
    out = []
    out.append("== 欠休 · validate (as-of %s, %s) ==" % (led.as_of, led.as_of_source))
    out.append("grants: %d 个批次 · 授予 %s 天 · expires 全部晚于 grant_date ✓"
               % (len(led.grants), fmt_days(tot["granted"])))
    n_annual = len([t for t in led.live_takes if t.kind == "annual"])
    n_other = len([t for t in led.live_takes if t.kind == "other"])
    out.append("leave: %d 行入账（年假 %d 行 %s 天 + 额度外 %d 行）"
               " · 0.5 步进 ✓ 预支/透支 ✓" % (len(led.live_takes), n_annual,
                                              fmt_days(tot["used"]), n_other))
    if led.future_takes:
        out.append("披露: %d 行未来休假（%s 起）被 as-of 截断，未入账"
                   % (len(led.future_takes), led.future_takes[0].start))
    hol_n = sum((b - a).days + 1 for a, b in led.holidays)
    out.append("holidays: %s（%d 个法定日 + %d 个调休补班日）—— 没有它，长假桥不生效，形状账会看短"
               % ("%d 个区间" % len(led.holidays) if led.holidays else "未提供",
                  hol_n, len(led.makeup_days)))
    out.append("守恒恒等式: %s = %s 已休 + %s 作废 + %s 余额 (残差 %.2e) ✓"
               % (fmt_days(tot["granted"]), fmt_days(tot["used"]), fmt_days(tot["voided"]),
                  fmt_days(tot["balance"]), abs(resid)))
    out.append("OK (exit 0)")
    print("\n".join(out))
    return EXIT_OK


# ---------------------------------------------------------------- main

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="leave-debt",
                                 description="欠休 · Leave Debt —— 年假债权账本")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("grants", help="批次授权 TSV（grant_date/days/expires/note）")
        p.add_argument("leave", help="休假流水 TSV（date/days/type/note）")
        p.add_argument("--as-of", help="钉死 as-of（缺省 = 账本最大日期，含批次到期日）")
        p.add_argument("--holidays", help="法定节假日表（一行一个 ISO 日期或 a..b 区间）")
        p.add_argument("--daily-rate", type=float, help="日薪（元）——损失折钱用")
        p.add_argument("--monthly-salary", type=float, help="月薪（元），日薪 = 月薪 ÷ 月计薪天数")
        p.add_argument("--pay-days", type=float, default=PAY_DAYS,
                       help="月计薪天数（缺省 21.75，中国劳动法口径）")

    for name, fn in (("report", cmd_report), ("shape", cmd_shape),
                     ("plan", cmd_plan), ("simulate", cmd_simulate),
                     ("validate", cmd_validate)):
        p = sub.add_parser(name, help=fn.__doc__)
        common(p)
        if name == "report":
            p.add_argument("--warn-days", type=int, default=WARN_DAYS,
                           help="批次临期门禁天数（缺省 %d）" % WARN_DAYS)
            p.add_argument("--forecast-line", type=float, default=FORECAST_LINE,
                           help="预测作废红线（占授予比例，缺省 %.2f）" % FORECAST_LINE)
        if name == "plan":
            p.add_argument("--pace-cap", type=float, default=PACE_CAP,
                           help="常态节奏上限（天/周，缺省 %.1f）" % PACE_CAP)
        if name == "simulate":
            p.add_argument("--take", type=float, required=True, help="模拟休假天数（0.5 步进）")
            p.add_argument("--on", required=True, help="模拟休假开始日期")
        p.set_defaults(fn=fn)

    args = ap.parse_args(argv)
    try:
        led = load_ledger(args.grants, args.leave, args.holidays, args.as_of)
        return args.fn(led, args)
    except LedgerBroken as e:
        print("账本损坏（exit 2）: %s" % e, file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    sys.exit(main())
