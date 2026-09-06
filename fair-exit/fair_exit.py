#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fair-exit — 明白账 / Fair Exit

The separation settlement sheet is the only contract most people ever
sign that was drafted, priced and audited by the other side alone.
HR hands over "N+1, sign today", and nobody re-checks the arithmetic:
the severance base is legally the AVERAGE GROSS of the last 12 months
(bonuses and allowances included), not the "base salary" line; untaken
annual leave converts at 2x the daily wage and usually vanishes from
the sheet entirely; non-compete clauses are signed with duties on one
side and no compensation on the other; and the "full and final
settlement" clause is not just about this number — it closes the
one-year arbitration clock on everything the sheet forgot.

fair-exit keeps that ledger by hand (tenure + monthly payslips + leave
+ unpaid overtime, four TSV files) and answers, before the ink:

  * report    — the statutory entitlement list: severance N months
                (anniversary walk with the 6-full-month boundary), the
                12-month average base, untaken-leave conversion year by
                year, unpaid overtime, and the identity that the items
                sum to the total (residual pinned at 0)
  * check     — the signature gate: HR's offer vs the statutory total,
                shortfall priced to the cent; a positive shortfall
                exits 4 — every yuan you sign away should be seen
  * clock     — the one-year arbitration countdown from the termination
                date; a closing window is a banner, expired is told as
                it is (the ledger is not an ambulance)
  * worlds    — three settlement worlds side by side: HR's sheet, the
                statutory negotiation world, and the 2N illegal-
                termination world — whose door is exactly what the
                "full and final" clause closes
  * validate  — ledger hygiene + identities: the anniversary walk vs a
                closed-form month arithmetic on a boundary grid, base
                sums, leave round-down boundaries (0.66 days pays
                nothing), calendar cross-check on claimed weekend
                overtime

Verdict posture: the ledger never rules your severance legal or fair —
it publishes the statutory arithmetic as common-knowledge priors, all
overridable by flags, and the local arbitration committee and your
lawyer always win. Signing or not signing is a human decision; the
ledger only refuses to let "I didn't do the math" sign for you.

Zero wall clock: the ledger anchors itself (as-of = latest date in the
ledger), --as-of pins it back, and the same files always yield the
same bytes. The ledger stays local on purpose.

Exit codes: 0 green · 2 ledger broken · 3 too thin to grade · 4 red light

Zero dependencies: Python 3.8+ standard library.
MIT License (c) 2026
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Parameters (common-knowledge priors; flags always win)

LEAVE_RATE = 2.0          # untaken-leave extra multiple: statutory 300%
                          # includes the 100% already paid as wages
LEAVE_DEFAULT = 5         # entitled days default (1-10y seniority tier)
PAY_DAYS = 21.75          # paid days per month: (365 - 104) / 12
NONCOMP_RATE = 0.30       # non-compete monthly floor (30% of avg wage)
NONCOMP_CAP = 24          # non-compete statutory duration cap (months)
LIMIT_DAYS = 365          # arbitration statute of limitation (1 year)
CAUTION_DAYS = 60         # clock banner when the window is closing
CAP_SOC_X = 3.0           # double cap: base <= 3x local social avg wage
CAP_YEARS = 12            # double cap: severance years <= 12
OT_MULT = {"workday": 1.5, "weekend": 2.0, "holiday": 3.0}
TOLERANCE = 0.00          # check: a one-cent shortfall is still a shortfall

MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

EXIT_OK, EXIT_BROKEN, EXIT_THIN, EXIT_RED = 0, 2, 3, 4


class LedgerError(Exception):
    """账坏 exit 2：缺列、坏日期、越界、重复——抄录错误挡在算术前面。"""


# ---------------------------------------------------------------------------
# formatting helpers

def money(x: float) -> str:
    return "{:,.2f}".format(x)


def signed_money(x: float) -> str:
    return ("+" if x > 0 else "") + money(x)


def month_of(d: date) -> Tuple[int, int]:
    return (d.year, d.month)


def month_str(m: Tuple[int, int]) -> str:
    return "%04d-%02d" % m


# ---------------------------------------------------------------------------
# date / month arithmetic (anniversary walk with end-of-month clamping)

def days_in_month(y: int, m: int) -> int:
    if m == 2 and (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)):
        return 29
    return MONTH_DAYS[m - 1]


def add_months_clamped(d: date, k: int) -> date:
    idx = d.year * 12 + (d.month - 1) + k
    y, m0 = divmod(idx, 12)
    return date(y, m0 + 1, min(d.day, days_in_month(y, m0 + 1)))


def add_years_clamped(d: date, k: int) -> date:
    y = d.year + k
    return date(y, d.month, min(d.day, days_in_month(y, d.month)))


def add_days(d: date, k: int) -> date:
    return d + timedelta(days=k)


def severance_months(start: date, end: date) -> float:
    """经济补偿年限：每满一年 1 个月；剩余 6 个整月以上按 1 年；
    不满 6 个月按半个月；恰满整年周年日解除不多算（余量为 0 不触发半月的
    「不满六个月」条款）；0 天即解除仍按不满六个月 → 0.5（法条原文口径）。"""
    years = 0
    while add_years_clamped(start, years + 1) <= end:
        years += 1
    ann = add_years_clamped(start, years)
    if end == ann:
        return float(years) if years > 0 else 0.5
    months = 0
    while add_months_clamped(ann, months + 1) <= end:
        months += 1
    return years + (1.0 if months >= 6 else 0.5)


def severance_months_fast(start: date, end: date) -> float:
    """validate 的闭式第二算法——必须与逐日游走在同一张边界网格上相等。"""
    years = 0
    while add_years_clamped(start, years + 1) <= end:
        years += 1
    ann = add_years_clamped(start, years)
    if end == ann:
        return float(years) if years > 0 else 0.5
    m = (end.year - ann.year) * 12 + (end.month - ann.month)
    ann_day = min(ann.day, days_in_month(end.year, end.month))
    if end.day < ann_day:
        m -= 1
    return years + (1.0 if m >= 6 else 0.5)


def month_add(m: Tuple[int, int], k: int) -> Tuple[int, int]:
    idx = m[0] * 12 + (m[1] - 1) + k
    y, m0 = divmod(idx, 12)
    return (y, m0 + 1)


def month_index(m: Tuple[int, int]) -> int:
    return m[0] * 12 + (m[1] - 1)


def month_end_date(m: Tuple[int, int]) -> date:
    return date(m[0], m[1], days_in_month(m[0], m[1]))


def month_diff(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    """整月数 b − a（≥0）。"""
    return month_index(b) - month_index(a)


# ---------------------------------------------------------------------------
# TSV loading (BOM, # comments, CN/EN column aliases)

TenureCols = {
    "employer": ["employer", "单位", "公司"],
    "start": ["start", "入职", "入职日", "入职日期"],
    "end": ["end", "解除", "解除日", "解除日期", "离职", "离职日"],
    "kind": ["kind", "类型", "解除类型"],
    "offer": ["offer", "报价", "报价总额", "hr报价"],
    "notice": ["notice", "代通知金", "代通知金已付", "通知金"],
    "noncomp_months": ["noncomp_months", "竞业月数", "竞业限制月数"],
    "noncomp_monthly": ["noncomp_monthly", "竞业月补", "竞业补偿"],
}
PayslipCols = {
    "month": ["month", "月份", "工资月"],
    "gross": ["gross", "应发", "应发工资", "税前"],
    "overtime": ["overtime", "加班费", "加班"],
    "note": ["note", "备注"],
}
LeaveCols = {
    "year": ["year", "年度", "年份"],
    "entitled": ["entitled", "应享", "应享天", "应休", "应休天"],
    "used": ["used", "已休", "已休天"],
    "note": ["note", "备注"],
}
OvertimeCols = {
    "date": ["date", "日期"],
    "hours": ["hours", "小时", "时长"],
    "kind": ["kind", "类型", "倍数", "口径"],
    "note": ["note", "备注"],
}

KIND_TENURE = {
    "mutual": "mutual", "协商": "mutual", "协商解除": "mutual",
    "nofault": "nofault", "无过失": "nofault", "无过失辞退": "nofault",
    "expiry": "expiry", "到期": "expiry", "到期不续": "expiry", "到期终止": "expiry",
    "resign": "resign", "辞职": "resign", "主动辞职": "resign",
    "illegal": "illegal", "违法": "illegal", "违法解除": "illegal",
}
KIND_TENURE_LABEL = {
    "mutual": "协商解除",
    "nofault": "无过失性辞退",
    "expiry": "合同到期终止",
    "resign": "主动辞职",
    "illegal": "违法解除(主张中)",
}
KIND_OT = {"workday": "workday", "工作日": "workday",
           "weekend": "weekend", "周末": "weekend", "休息日": "weekend",
           "holiday": "holiday", "节假日": "holiday", "法定节假日": "holiday"}
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def load_tsv(path: str, cols: Dict[str, List[str]]) -> List[Dict[str, str]]:
    """读 TSV：跳过空行与 # 注释，BOM 容忍，中英列名同效。缺必填列 = 账坏。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            lines = [ln.rstrip("\n").rstrip("\r") for ln in fh]
    except OSError as exc:
        raise LedgerError("%s 无法读取: %s" % (path, exc))
    rows_raw = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not rows_raw:
        return []
    header = [c.strip() for c in rows_raw[0].split("\t")]
    canon: Dict[str, str] = {}
    for key, aliases in cols.items():
        lowered = [a.lower() for a in aliases]
        for h in header:
            if h.lower() in lowered:
                canon[h] = key
                break
    for key in cols:
        if key == "note":
            continue
        if key not in canon.values():
            raise LedgerError("%s 缺列: %s（需要 %s 之一）"
                              % (path, key, "/".join(cols[key])))
    out: List[Dict[str, str]] = []
    for ln in rows_raw[1:]:
        parts = [p.strip() for p in ln.split("\t")]
        row: Dict[str, str] = {}
        for h, key in canon.items():
            i = header.index(h)
            row[key] = parts[i] if i < len(parts) else ""
        out.append(row)
    return out


def parse_date(s: str, what: str, allow_blank: bool = False) -> Optional[date]:
    s = (s or "").strip()
    if not s:
        if allow_blank:
            return None
        raise LedgerError("%s 为空" % what)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if not m:
        raise LedgerError("%s 不是日期: %r（要 YYYY-MM-DD）" % (what, s))
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise LedgerError("%s 不是真实日期: %r" % (what, s))


def parse_month(s: str, what: str) -> Tuple[int, int]:
    m = re.match(r"^(\d{4})-(\d{1,2})$", (s or "").strip())
    if not m:
        raise LedgerError("%s 不是月份: %r（要 YYYY-MM）" % (what, s))
    y, mo = int(m.group(1)), int(m.group(2))
    if not 1 <= mo <= 12:
        raise LedgerError("%s 月份越界: %r" % (what, s))
    return (y, mo)


def parse_num(s: str, what: str, allow_blank: bool = False) -> Optional[float]:
    s = (s or "").strip().replace(",", "")
    if not s:
        if allow_blank:
            return None
        raise LedgerError("%s 为空" % what)
    try:
        v = float(s)
    except ValueError:
        raise LedgerError("%s 不是数字: %r" % (what, s))
    if v < 0:
        raise LedgerError("%s 为负数: %r" % (what, s))
    return v


# ---------------------------------------------------------------------------
# ledger model

@dataclass
class Tenure:
    employer: str
    start: date
    end: Optional[date]
    kind: str                       # canonical key
    offer: Optional[float]
    notice: str                     # '' | 'y' | 'n'
    noncomp_months: Optional[float]
    noncomp_monthly: Optional[float]


@dataclass
class Payslip:
    month: Tuple[int, int]
    gross: float
    overtime: float
    note: str


@dataclass
class LeaveYear:
    year: int
    entitled: Optional[float]       # None -> prior default, ASSUMED
    used: float
    note: str


@dataclass
class OvertimeRow:
    day: date
    hours: float
    kind: str
    mult: float
    note: str


@dataclass
class Ledger:
    tenure: Tenure
    payslips: List[Payslip] = field(default_factory=list)
    leaves: List[LeaveYear] = field(default_factory=list)
    overtimes: List[OvertimeRow] = field(default_factory=list)
    as_of: date = field(default=date(1970, 1, 1))
    as_of_pinned: bool = False
    excluded_months: List[str] = field(default_factory=list)
    excluded_ot: List[str] = field(default_factory=list)
    excluded_years: List[str] = field(default_factory=list)


def build_ledger(tenure_path: str, payslip_path: str, leave_path: str,
                 ot_path: Optional[str], as_of_pin: Optional[str],
                 leave_default: float) -> Ledger:
    # ---- tenure: exactly one row
    rows = load_tsv(tenure_path, TenureCols)
    if len(rows) != 1:
        raise LedgerError("tenure 应恰好 1 行（一次离职只有一个本单位），现在 %d 行"
                          % len(rows))
    r = rows[0]
    if not r["employer"]:
        raise LedgerError("tenure.employer 为空")
    start = parse_date(r["start"], "tenure.start")
    end = parse_date(r["end"], "tenure.end", allow_blank=True)
    if end is not None and end < start:
        raise LedgerError("tenure: 解除日 %s 早于入职日 %s" % (end, start))
    kind_raw = (r["kind"] or "").strip().lower() or "mutual"
    if kind_raw not in KIND_TENURE:
        raise LedgerError("tenure.kind 未知: %r（%s）" % (
            r["kind"], "/".join(sorted(KIND_TENURE))))
    offer = parse_num(r["offer"], "tenure.offer", allow_blank=True)
    notice = (r["notice"] or "").strip().lower()
    if notice not in ("", "y", "n"):
        raise LedgerError("tenure.notice 只认 y/n/空: %r" % r["notice"])
    nc_m = parse_num(r["noncomp_months"], "tenure.noncomp_months", allow_blank=True)
    nc_pay = parse_num(r["noncomp_monthly"], "tenure.noncomp_monthly", allow_blank=True)
    led = Ledger(tenure=Tenure(r["employer"], start, end, KIND_TENURE[kind_raw],
                               offer, notice, nc_m, nc_pay))
    tenure = led.tenure

    # ---- payslips
    for i, row in enumerate(load_tsv(payslip_path, PayslipCols), 2):
        m = parse_month(row["month"], "payslips 第 %d 行 month" % i)
        gross = parse_num(row["gross"], "payslips 第 %d 行 gross" % i) or 0.0
        ot = parse_num(row["overtime"], "payslips 第 %d 行 overtime" % i,
                       allow_blank=True) or 0.0
        led.payslips.append(Payslip(m, gross, ot, row.get("note", "")))
    seen = set()
    for p in led.payslips:
        if p.month in seen:
            raise LedgerError("payslips 月份重复: %s" % month_str(p.month))
        seen.add(p.month)
        if month_index(p.month) < month_index(month_of(tenure.start)):
            raise LedgerError("payslips 月份 %s 早于入职月 %s" % (
                month_str(p.month), month_str(month_of(tenure.start))))
        if tenure.end is not None and month_index(p.month) > month_index(month_of(tenure.end)):
            raise LedgerError("payslips 月份 %s 晚于解除月 %s——补发请并入解除当月并在备注披露"
                              % (month_str(p.month), month_str(month_of(tenure.end))))

    # ---- leave
    for i, row in enumerate(load_tsv(leave_path, LeaveCols), 2):
        ym = re.match(r"^(\d{4})$", (row["year"] or "").strip())
        if not ym:
            raise LedgerError("leave 第 %d 行 year 不是年份: %r" % (i, row["year"]))
        y = int(ym.group(1))
        entitled = parse_num(row["entitled"], "leave 第 %d 行 entitled" % i,
                             allow_blank=True)
        used = parse_num(row["used"], "leave 第 %d 行 used" % i) or 0.0
        led.leaves.append(LeaveYear(y, entitled, used, row.get("note", "")))
    seeny = set()
    for lv in led.leaves:
        if lv.year in seeny:
            raise LedgerError("leave 年度重复: %d" % lv.year)
        seeny.add(lv.year)
        if lv.year < tenure.start.year or (
                tenure.end is not None and lv.year > tenure.end.year):
            raise LedgerError("leave 年度 %d 在任期之外" % lv.year)
        # entitled 留空 = 用先验缺省（engine 里标 ASSUMED），这里不替用户发明

    # ---- overtime (optional file)
    if ot_path:
        for i, row in enumerate(load_tsv(ot_path, OvertimeCols), 2):
            d = parse_date(row["date"], "overtime 第 %d 行 date" % i)
            hours = parse_num(row["hours"], "overtime 第 %d 行 hours" % i)
            if hours is None or hours <= 0:
                raise LedgerError("overtime 第 %d 行 hours 必须为正" % i)
            k = (row["kind"] or "").strip().lower()
            if k not in KIND_OT:
                raise LedgerError("overtime 第 %d 行 kind 未知: %r（%s）" % (
                    i, row["kind"], "/".join(sorted(KIND_OT))))
            kind = KIND_OT[k]
            # 日历对质：weekend/workday 与真实星期对质；holiday 调休复杂不发明
            wd = d.weekday()
            if kind == "weekend" and wd < 5:
                raise LedgerError("overtime %s 声称休息日，但那天是 %s——日历对质失败"
                                  % (d, WEEKDAY_CN[wd]))
            if kind == "workday" and wd >= 5:
                raise LedgerError("overtime %s 声称工作日，但那天是 %s——日历对质失败"
                                  % (d, WEEKDAY_CN[wd]))
            led.overtimes.append(OvertimeRow(d, hours, kind, OT_MULT[kind],
                                             row.get("note", "")))

    # ---- as-of anchor: the latest date the ledger itself knows
    cands: List[date] = []
    if tenure.end is not None:
        cands.append(tenure.end)
    for p in led.payslips:
        cands.append(month_end_date(p.month))
    for o in led.overtimes:
        cands.append(o.day)
    led.as_of = max(cands) if cands else tenure.start
    if as_of_pin:
        led.as_of = parse_date(as_of_pin, "--as-of")
        led.as_of_pinned = True

    # ---- as-of shearing: rows after the pin are the not-yet-written future
    if led.as_of_pinned:
        keep: List[Payslip] = []
        for p in led.payslips:
            if month_end_date(p.month) > led.as_of:
                led.excluded_months.append(month_str(p.month))
            else:
                keep.append(p)
        led.payslips = keep
        keep_ot: List[OvertimeRow] = []
        for o in led.overtimes:
            if o.day > led.as_of:
                led.excluded_ot.append(str(o.day))
            else:
                keep_ot.append(o)
        led.overtimes = keep_ot
        keep_lv: List[LeaveYear] = []
        for lv in led.leaves:
            if lv.year > led.as_of.year:
                led.excluded_years.append(str(lv.year))
            else:
                keep_lv.append(lv)
        led.leaves = keep_lv
    return led


# ---------------------------------------------------------------------------
# engine

@dataclass
class LeaveItem:
    year: int
    entitled: float
    entitled_assumed: bool
    days_worked: Optional[int]      # None = 整年
    rounded: float                  # 折算应休（舍尾）
    used: float
    unused: float
    amount: float
    note: str


@dataclass
class Engine:
    led: Ledger
    working: bool                   # 在职视角（解除日未知或晚于 as-of）
    end: date                       # 结算锚日（解除日或 as-of）
    n_months: float                 # 账面 N（illegal 显示 2N 前的 N）
    comp_years: float               # comp_amount 实际使用的年限（封顶翻案后）
    used_base: float                # comp_amount 实际使用的基数（封顶翻案后）
    comp_base: float                # 经济补偿基数（应发平均，默认含加班费）
    leave_base: float               # 年假口径基数（剔加班费）
    base_rows: int
    base_expected: int
    window: Tuple[str, str]
    comp_amount: float
    comp_label: str
    notice_amount: float
    notice_note: str
    leave_items: List[LeaveItem]
    leave_total: float
    leave_days: float
    day_rate: float
    ot_total: float
    hard_total: float
    noncomp_claim: float
    noncomp_note: str
    noncomp_missing: bool
    noncomp_capped: bool
    doubled: bool
    cap_note: str
    banners: List[str]
    thin: bool
    thin_reason: str


def engine(led: Ledger, exclude_ot: bool, leave_rate: float,
           soc_avg: Optional[float], noncomp_rate: float,
           min_wage: Optional[float], leave_default: float) -> Engine:
    t = led.tenure
    working = t.end is None or t.end > led.as_of
    end = t.end if (t.end is not None and t.end <= led.as_of) else led.as_of

    # ---- base window: the last 12 eligible months ending at `end`
    end_m = month_of(end)
    start_m = month_of(t.start)
    expected = min(12, month_diff(start_m, end_m) + 1) if end_m >= start_m else 0
    win_from = month_add(end_m, -11) if expected >= 12 else start_m
    rows = [p for p in led.payslips
            if month_index(win_from) <= month_index(p.month) <= month_index(end_m)]
    n = len(rows)
    sum_gross = sum(p.gross for p in rows)
    sum_ot = sum(p.overtime for p in rows)
    comp_base = ((sum_gross + sum_ot) if not exclude_ot else sum_gross) / n if n else 0.0
    leave_base = sum_gross / n if n else 0.0

    n_months = severance_months(t.start, end)

    # ---- double cap (3x social average wage, 12 years) + minimum wage floor
    doubled = False
    cap_note = ""
    used_base = comp_base
    used_years = n_months
    if min_wage is not None and 0 < comp_base < min_wage:
        used_base = min_wage
        cap_note = "基数低于当地最低工资，按最低工资 %.2f 计" % min_wage
        doubled = True
    if soc_avg is not None and comp_base > CAP_SOC_X * soc_avg:
        doubled = True
        used_base = CAP_SOC_X * soc_avg
        if n_months > CAP_YEARS:
            used_years = float(CAP_YEARS)
            cap_note = "基数按社平 3 倍封顶且年限按 %d 年封顶" % CAP_YEARS
        else:
            cap_note = "基数按社平 3 倍封顶（年限未触 %d 年封顶）" % CAP_YEARS

    # ---- severance amount by kind
    if t.kind == "resign":
        comp_amount = 0.0
        comp_label = "主动辞职无经济补偿（年假与加班费照算——那些与辞职理由无关）"
        n_months = 0.0
    elif t.kind == "illegal":
        comp_amount = 2.0 * used_years * used_base
        comp_label = "违法解除赔偿金 2N（×%s）" % money(used_base)
        n_months = used_years
    else:
        comp_amount = used_years * used_base
        comp_label = "经济补偿 %.1f 个月 × %s" % (used_years, money(used_base))

    # ---- statutory notice pay (+1) — only 无过失性辞退
    notice_amount = 0.0
    notice_note = ""
    if t.kind == "nofault":
        if t.notice == "y":
            notice_note = "代通知金已单独支付，账面记 0"
        elif rows:
            last = max(rows, key=lambda p: month_index(p.month))
            notice_amount = last.gross + last.overtime
            notice_note = "法定 +1（按 %s 应发 %s）" % (month_str(last.month),
                                                      money(notice_amount))
        else:
            notice_note = "无工资流水，代通知金无法计价（+1 按上月应发）"
    elif t.kind == "mutual":
        notice_note = "协商解除，法定无 +1——HR 若给，那是谈判不是义务"
    elif t.kind == "expiry":
        notice_note = "到期终止无法定 +1（维持或提高条件而拒绝续订的除外——简化披露）"
    elif t.kind == "illegal":
        notice_note = "违法解除路径无 +1（赔偿金 2N 已含惩罚）"

    # ---- untaken-leave conversion
    day_rate = leave_base / PAY_DAYS
    leave_items: List[LeaveItem] = []
    for lv in led.leaves:
        assumed = lv.entitled is None
        ent = float(lv.entitled) if lv.entitled is not None else float(leave_default)
        if lv.year == end.year:
            d0 = max(date(lv.year, 1, 1), t.start)
            days = max(0, (end - d0).days + 1)
            prorated = ent * days / 365.0
            rounded = float(int(prorated + 1e-9))  # 不足 1 整天不支付
            note = "折算 %g×%d/365 → %g" % (ent, days, rounded)
        else:
            days = None
            prorated = None
            rounded = ent
            note = "整年"
        unused = max(0.0, rounded - lv.used)
        if lv.used > rounded:
            note += "；已休多于折算，不再扣回"
        amount = unused * day_rate * leave_rate
        leave_items.append(LeaveItem(lv.year, ent, assumed, days,
                                     rounded, lv.used, unused, amount, note))
    have_years = {lv.year for lv in led.leaves}
    years_expected = [y for y in range(t.start.year, end.year + 1)
                      if y <= led.as_of.year]
    missing_years = [y for y in years_expected if y not in have_years]
    leave_total = sum(it.amount for it in leave_items)
    leave_days = sum(it.unused for it in leave_items)

    # ---- unpaid overtime (hourly off the leave-excluded base, 21.75/8)
    ot_total = sum(o.hours * o.mult * (leave_base / PAY_DAYS / 8.0)
                   for o in led.overtimes)

    hard_total = comp_amount + notice_amount + leave_total + ot_total

    # ---- non-compete audit (conditional claim, never in the hard total)
    noncomp_claim = 0.0
    noncomp_note = ""
    noncomp_missing = False
    noncomp_capped = False
    if t.noncomp_months:
        cap_m = t.noncomp_months
        if cap_m > NONCOMP_CAP:
            cap_m = NONCOMP_CAP
            noncomp_capped = True
        line = noncomp_rate * comp_base
        if t.noncomp_monthly is None:
            noncomp_missing = True
            noncomp_claim = line * cap_m
            noncomp_note = "未约定补偿 ≠ 不用守：履行义务后可按 %.0f%% 线按月主张" % (
                noncomp_rate * 100)
        elif t.noncomp_monthly < line - 1e-9:
            noncomp_claim = (line - t.noncomp_monthly) * cap_m
            noncomp_note = "月补 %s 低于 %.0f%% 线 %s——可主张补差" % (
                money(t.noncomp_monthly), noncomp_rate * 100, money(line))
        else:
            noncomp_note = "月补已达标（≥ %.0f%% 线）" % (noncomp_rate * 100)

    # ---- banners
    banners: List[str] = []
    if working:
        banners.append("DECLINED 解除日未知（在职或晚于 as-of）——判级拒绝，档案照出")
    elif n == 0:
        banners.append("DECLINED 工资流水 0 行——基数与金额判不了，年假与加班同样无处落脚")
    if n > 0 and n < expected:
        banners.append("ASSUMED 基数窗口应有 %d 个月，账面 %d 行——缺的月份没有发明，"
                       "平均按你交的算（补上流水，口径自动变严）" % (expected, n))
    if doubled:
        banners.append("DOUBLE-CAP %s" % cap_note)
    if soc_avg is None and comp_base > 0 and t.kind != "resign":
        banners.append("NO-SOC 未给 --soc-avg：双封顶不启用——高薪者请带上当地社平月工资")
    if noncomp_capped:
        banners.append("LEGAL-CAP 竞业月数超 %d 个月上限，超出部分无效，按 %d 算"
                       % (NONCOMP_CAP, NONCOMP_CAP))
    if missing_years:
        years_txt = "、".join(str(y) for y in missing_years)
        banners.append("LEAVE-GAP %d 个年度没有年假行（%s）——没记 ≠ 没有，"
                       "这些年的折算没有计入" % (len(missing_years), years_txt))
    if led.excluded_months:
        banners.append("AS-OF 剪除工资月 %s（晚于 as-of 的整月，不是账坏）"
                       % ",".join(led.excluded_months))
    if led.excluded_ot:
        banners.append("AS-OF 剪除加班行 %s" % ",".join(led.excluded_ot))
    if led.excluded_years:
        banners.append("AS-OF 剪除年假年度 %s" % ",".join(led.excluded_years))

    thin = working or n == 0
    thin_reason = "解除日未知" if working else ("工资流水 0 行" if n == 0 else "")
    return Engine(led, working, end, n_months, used_years, used_base,
                  comp_base, leave_base,
                  n, expected, (month_str(win_from), month_str(end_m)),
                  comp_amount, comp_label, notice_amount, notice_note,
                  leave_items, leave_total, leave_days, day_rate, ot_total,
                  hard_total, noncomp_claim, noncomp_note, noncomp_missing,
                  noncomp_capped, doubled, cap_note, banners, thin, thin_reason)


# ---------------------------------------------------------------------------
# output

def header(cmd: str, as_of: date, paths: List[str]) -> List[str]:
    names = " + ".join(os.path.basename(p) for p in paths)
    return ["-- Fair Exit %s: %s" % (cmd, names),
            "  as-of : %s   anchor: 应发工资，不是基本工资" % as_of]


def render_report(eng: Engine, paths: List[str], leave_rate: float,
                  exclude_ot: bool) -> List[str]:
    t = eng.led.tenure
    out = header("report", eng.led.as_of, paths)
    out.append("")
    span_end = str(t.end) if t.end else "在职"
    out.append("  档案   %s  %s → %s  %s" % (t.employer, t.start, span_end,
                                             KIND_TENURE_LABEL[t.kind]))
    out.append("  基数   窗口 %s..%s 共 %d 行（应有 %d 个月）" % (
        eng.window[0], eng.window[1], eng.base_rows, eng.base_expected))
    out.append("         经济补偿基数 %s（应发平均，%s）" % (
        money(eng.comp_base), "剔加班费" if exclude_ot else "含加班费"))
    out.append("         年假口径基数 %s（剔加班费）→ 日薪 %s（÷21.75）" % (
        money(eng.leave_base), money(eng.day_rate)))
    if t.kind == "resign":
        out.append("  N      —（主动辞职：补偿为 0，但应得清单照开）")
    else:
        out.append("  N      %.1f 个月（逐日游走：每满一年 +1；余 ≥6 整月 +1；不满 +0.5）"
                   % eng.n_months)
    out.append("")
    out.append("  应得清单")
    if t.kind == "resign":
        out.append("    经济补偿          0.00   %s" % eng.comp_label)
    elif t.kind == "illegal":
        out.append("    经济补偿          2 × %.1f × %s = %s   [%s]" % (
            eng.comp_years, money(eng.used_base), money(eng.comp_amount),
            eng.comp_label))
    else:
        out.append("    经济补偿          %.1f × %s = %s" % (
            eng.comp_years, money(eng.used_base), money(eng.comp_amount)))
    if t.kind == "nofault":
        out.append("    代通知金          %s   %s" % (money(eng.notice_amount),
                                                      eng.notice_note))
    else:
        out.append("    代通知金          —   %s" % eng.notice_note)
    if eng.leave_items:
        out.append("    未休年假折算      %g 天 × %s × %.0f%% = %s" % (
            eng.leave_days, money(eng.day_rate), leave_rate * 100,
            money(eng.leave_total)))
        for it in eng.leave_items:
            star = "*" if it.entitled_assumed else ""
            out.append("      %d: 应享 %g%s 已休 %g → %g 天   (%s)" % (
                it.year, it.entitled, star, it.used, it.unused, it.note))
    else:
        out.append("    未休年假折算      年假账为空——这一列没有计入，别让「没记」变成「没有」")
    if eng.led.overtimes:
        out.append("    欠付加班费        %d 笔 = %s" % (len(eng.led.overtimes),
                                                        money(eng.ot_total)))
        for o in eng.led.overtimes:
            out.append("      %s %g h × %.1f× = %s   %s" % (
                o.day, o.hours, o.mult,
                money(o.hours * o.mult * eng.day_rate / 8.0), o.note or ""))
    else:
        out.append("    欠付加班费        无流水（有未付的加班？写进 overtime.tsv 再算）")
    out.append("    ──────────────────────────────")
    out.append("    硬应得合计                          %s" % money(eng.hard_total))
    resid = abs((eng.comp_amount + eng.notice_amount + eng.leave_total +
                 eng.ot_total) - eng.hard_total)
    out.append("    恒等式 Σ分项 ≡ 合计   残差 %.2e" % resid)
    if t.noncomp_months:
        out.append("")
        out.append("  条件主张（不进合计——账本不裁决，履行与举证是前提）")
        out.append("    竞业限制补偿      %s   %s" % (
            money(eng.noncomp_claim) if eng.noncomp_claim else "—",
            eng.noncomp_note))
    if not eng.working and eng.led.tenure.kind != "resign":
        w2 = 2.0 * eng.comp_years * eng.used_base + eng.leave_total + eng.ot_total
        out.append("    违法解除 2N 世界   %s   需举证；worlds 对照" % money(w2))
    out.append("")
    if not eng.working and t.end is not None:
        deadline = add_days(eng.end, LIMIT_DAYS)
        left = (deadline - eng.led.as_of).days
        out.append("  时效   仲裁时效 1 年 → %s（剩 %d 天）" % (deadline, left))
    for b in eng.banners:
        out.append("  • " + b)
    return out


def render_check(eng: Engine, paths: List[str], tol: float) -> Tuple[List[str], int]:
    t = eng.led.tenure
    out = header("check", eng.led.as_of, paths)
    out.append("")
    out.append("  法定硬应得    %s" % money(eng.hard_total))
    if t.offer is None:
        out.append("  HR 报价       （账本未记 offer）")
        out.append("")
        out.append("  DECLINED 没有报价，无从对质——先谈出一个数，再谈签不签")
        return out, EXIT_THIN
    gap = eng.hard_total - t.offer
    out.append("  HR 报价       %s" % money(t.offer))
    out.append("  差额          %s" % signed_money(gap))
    out.append("")
    if gap > tol + 1e-9:
        out.append("  判级  ✗ SHORTFALL——你每签一次名，都在把 %s 捐回去" % money(gap))
        out.append("")
        out.append("  这一笔常被整行略去的小项：")
        if eng.leave_total:
            out.append("    未休年假折算 %s——法条口径 300%%（含已发工资，额外 200%%），"
                       "结算单上最常消失的一行" % money(eng.leave_total))
        if eng.ot_total:
            out.append("    欠付加班费 %s——只算你写下的，举证责任在你" % money(eng.ot_total))
        out.append("    最后一个月工资不属于「结算让步」，必须足额——不在对质范围")
        out.append("")
        out.append("  「一次性了结」条款关掉的不只是这张单子，是 clock 里那扇门")
        return out, EXIT_RED
    out.append("  判级  ✓ 报价不低于法定账面硬应得（容忍 ≤ %s）" % money(tol))
    out.append("  谈判空间与条件主张（worlds）不归账本管——签不签仍是你的决定")
    return out, EXIT_OK


def render_clock(eng: Engine, paths: List[str]) -> Tuple[List[str], int]:
    out = header("clock", eng.led.as_of, paths)
    out.append("")
    if eng.led.tenure.end is None:
        out.append("  DECLINED 解除日未知——时效尚未起算（在职视角）")
        return out, EXIT_THIN
    deadline = add_days(eng.end, LIMIT_DAYS)
    left = (deadline - eng.led.as_of).days
    out.append("  解除日        %s" % eng.end)
    out.append("  时效届满      %s（%d 天）" % (deadline, LIMIT_DAYS))
    out.append("  距今          %d 天" % left)
    out.append("")
    if left < 0:
        out.append("  EXPIRED 已过时效 %d 天——账本不装救护车，过期如实说" % (-left))
        out.append("  （拖欠劳动报酬在职期间不受 1 年限制；结算项自解除日起算——通识口径，法庭永远赢）")
    elif left <= CAUTION_DAYS:
        out.append("  CAUTION 窗口只剩 %d 天——证据（工资条/聊天记录/协议草稿）今天开始归档" % left)
    else:
        out.append("  绿灯 %d 天——但「一次性了结」条款签下之时，这扇门就关了" % left)
    return out, EXIT_OK


def render_worlds(eng: Engine, paths: List[str]) -> Tuple[List[str], int]:
    t = eng.led.tenure
    out = header("worlds", eng.led.as_of, paths)
    out.append("")
    if t.offer is None:
        out.append("  DECLINED 无报价——HR 世界无法定价（check 同理）")
        return out, EXIT_THIN
    base = eng.used_base
    n = eng.comp_years
    notice_in_n = eng.notice_amount if t.kind == "nofault" else 0.0
    w_n = n * base + notice_in_n + eng.leave_total + eng.ot_total
    if t.kind == "resign":
        w_2n = None
    else:
        w_2n = 2.0 * n * base + eng.leave_total + eng.ot_total
    if t.kind == "illegal":
        rows = [("HR 世界", t.offer, "签字后定格；「再无其他争议」随之生效"),
                ("你主张的世界", eng.hard_total, "违法解除 2N（主张中）"),
                ("协商退让世界", w_n, "若退回协商解除——底线在哪")]
    elif t.kind == "resign":
        rows = [("HR 世界", t.offer, "签字后定格"),
                ("法定世界", eng.hard_total, "辞职也该结的账：年假 + 加班费"),
                ("违法解除世界", None, "主动辞职没有这扇门——账本不发明")]
    else:
        rows = [("HR 世界", t.offer, "签字后定格；「再无其他争议」随之生效"),
                ("法定协商世界", eng.hard_total, "谈判桌的锚——check 的对价"),
                ("违法解除世界", w_2n, "需举证违法解除；签字关掉的正是这扇门")]
    out.append("  %-10s %14s   %s" % ("世界", "结算总额", "语义"))
    for name, amt, note in rows:
        out.append("  %-10s %14s   %s" % (
            name, money(amt) if amt is not None else "—", note))
    out.append("")
    hard_name = "你主张的世界" if t.kind == "illegal" else "法定协商世界"
    if t.kind != "resign":
        out.append("  恒等式  %s − HR 世界 ≡ check 差额 %s" % (
            hard_name, signed_money(eng.hard_total - t.offer)))
        if w_2n is not None and t.kind in ("mutual", "expiry"):
            out.append("  2N 世界 − 法定协商世界 = %s ≡ 经济补偿本身——关门关掉的就是它"
                       % money(w_2n - eng.hard_total))
    for b in eng.banners:
        out.append("  • " + b)
    return out, EXIT_OK


# ---------------------------------------------------------------------------
# validate

def render_validate(eng: Engine, paths: List[str]) -> Tuple[List[str], int]:
    led = eng.led
    t = led.tenure
    out = header("validate", led.as_of, paths)
    out.append("")
    problems: List[str] = []

    # 1) N 双算法：真实任期 + 边界网格
    if t.end is not None and t.kind != "resign":
        a = severance_months(t.start, t.end)
        b = severance_months_fast(t.start, t.end)
        if abs(a - b) > 1e-9:
            problems.append("N 双算法不一致: %s vs %s" % (a, b))
        else:
            out.append("  ✓ N 双算法一致: 逐日游走 = 闭式月差（%.1f 个月）" % a)
    grid = 0
    bad_grid = 0
    for base_d in (date(2020, 1, 31), date(2021, 3, 15), date(2019, 2, 28)):
        for k in range(0, 40):
            for delta in (-1, 0, 1, 182, 183, 184):
                d2 = add_days(add_months_clamped(base_d, k), delta)
                if d2 < base_d:
                    continue
                grid += 1
                if abs(severance_months(base_d, d2) -
                       severance_months_fast(base_d, d2)) > 1e-9:
                    bad_grid += 1
                    problems.append("N 边界网格不一致: %s → %s" % (base_d, d2))
    if not bad_grid:
        out.append("  ✓ N 边界网格 %d 点全等（3 个起步日 × ±1 天/半年/闰月钳位）" % grid)

    # 2) 年假舍尾边界（已知真值往返）
    cases = [(10, 243, 6.0), (5, 73, 1.0), (10, 7, 0.0), (15, 365, 15.0),
             (10, 182, 4.0), (10, 186, 5.0)]
    for ent, days, want in cases:
        got = float(int(ent * days / 365.0 + 1e-9))
        if got != want:
            problems.append("年假折算边界: entitled %d × %d/365 → %s 期望 %s"
                            % (ent, days, got, want))
    if not [p for p in problems if "年假" in p]:
        out.append("  ✓ 年假舍尾边界 %d 例已知真值往返通过（不足 1 整天不支付）" % len(cases))

    # 3) 基数恒等式：窗口行求和 == 分子（含/剔加班费两口径自洽）
    sum_g = sum(p.gross for p in led.payslips)
    sum_o = sum(p.overtime for p in led.payslips)
    if eng.base_rows:
        rebuilt = (sum_g + sum_o) / eng.base_rows
        if abs(rebuilt - eng.comp_base) > 1e-6:
            problems.append("基数恒等式破坏: 重建 %s vs 引擎 %s"
                            % (money(rebuilt), money(eng.comp_base)))
        else:
            out.append("  ✓ 基数恒等式: (%s + %s) ÷ %d 行 = %s" % (
                money(sum_g), money(sum_o), eng.base_rows, money(eng.comp_base)))

    # 4) 应得恒等式
    resid = abs((eng.comp_amount + eng.notice_amount + eng.leave_total +
                 eng.ot_total) - eng.hard_total)
    if resid > 1e-6:
        problems.append("应得恒等式残差 %s" % resid)
    else:
        out.append("  ✓ 应得恒等式 Σ分项 ≡ 合计   残差 %.2e" % resid)

    # 5) 2N 世界 − 法定世界 ≡ 经济补偿（协商解除、无代通知金、未触发封顶时）
    if (t.end is not None and t.kind in ("mutual", "expiry")
            and eng.notice_amount == 0 and not eng.doubled):
        n = severance_months(t.start, eng.end)
        left = 2.0 * n * eng.used_base + eng.leave_total + eng.ot_total
        gap = left - eng.hard_total
        want = n * eng.used_base
        if abs(gap - want) > 1e-6:
            problems.append("2N 世界差额恒等式: %s vs %s" % (gap, want))
        else:
            out.append("  ✓ 2N 世界差额 ≡ 经济补偿本身（%s）" % money(want))

    if problems:
        out.append("")
        out.append("  ✗ %d 处体检失败:" % len(problems))
        for p in problems:
            out.append("    " + p)
        return out, EXIT_BROKEN
    out.append("")
    out.append("  ✓ 全部体检通过")
    return out, EXIT_OK


# ---------------------------------------------------------------------------
# main

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="fair_exit",
        description="明白账 · Fair Exit — 离职结算对账账本（零依赖）")
    ap.add_argument("command", help="report | check(sign) | clock(deadline) | "
                                    "worlds(scenarios) | validate(verify)")
    ap.add_argument("tenure", help="tenure.tsv（一行一段任期）")
    ap.add_argument("payslips", help="payslips.tsv（一行一个月度应发）")
    ap.add_argument("leave", help="leave.tsv（一行一个年度年假）")
    ap.add_argument("overtime", nargs="?", default=None,
                    help="overtime.tsv 可选（一行一笔未付加班）")
    ap.add_argument("--as-of", dest="as_of", default=None,
                    help="钉回过去（缺省 = 账本最大日期自锚定）")
    ap.add_argument("--soc-avg", dest="soc_avg", type=float, default=None,
                    help="当地上年度职工月平均工资（双封顶用）")
    ap.add_argument("--min-wage", dest="min_wage", type=float, default=None,
                    help="当地最低月工资（基数下限，缺省不启用）")
    ap.add_argument("--exclude-overtime", dest="exclude_ot", action="store_true",
                    help="经济补偿基数剔除加班费（部分地区司法口径）")
    ap.add_argument("--leave-rate", dest="leave_rate", type=float, default=LEAVE_RATE,
                    help="未休年假倍数，缺省 2.0（法条 300%% 含已发 100%%）")
    ap.add_argument("--leave-default", dest="leave_default", type=float,
                    default=LEAVE_DEFAULT, help="entitled 缺省天数（缺省 5）")
    ap.add_argument("--noncomp-rate", dest="noncomp_rate", type=float,
                    default=NONCOMP_RATE, help="竞业补偿通识线（缺省 0.30）")
    ap.add_argument("--tolerance", dest="tolerance", type=float, default=TOLERANCE,
                    help="check 容忍差额（缺省 0：差一分也点名）")
    args = ap.parse_args(argv)

    cmd = args.command.lower()
    aliases = {"statement": "report", "sign": "check", "deadline": "clock",
               "scenarios": "worlds", "verify": "validate"}
    cmd = aliases.get(cmd, cmd)
    if cmd not in ("report", "check", "clock", "worlds", "validate"):
        ap.error("未知命令: %s" % args.command)

    paths = [args.tenure, args.payslips, args.leave] + (
        [args.overtime] if args.overtime else [])

    try:
        led = build_ledger(args.tenure, args.payslips, args.leave,
                           args.overtime, args.as_of, args.leave_default)
        eng = engine(led, args.exclude_ot, args.leave_rate,
                     args.soc_avg, args.noncomp_rate, args.min_wage,
                     args.leave_default)
    except LedgerError as exc:
        print("-- Fair Exit: 账坏")
        print("  %s" % exc)
        return EXIT_BROKEN

    if cmd == "report":
        lines = render_report(eng, paths, args.leave_rate, args.exclude_ot)
        code = EXIT_THIN if eng.thin else EXIT_OK
    elif cmd == "check":
        lines, code = render_check(eng, paths, args.tolerance)
    elif cmd == "clock":
        lines, code = render_clock(eng, paths)
    elif cmd == "worlds":
        lines, code = render_worlds(eng, paths)
    else:
        lines, code = render_validate(eng, paths)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
