#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""afterburn · 余燃 —— 咖啡因残留账本.

问题：那杯拿铁下午三点就喝完了，火到半夜还没熄。咖啡因按半衰期消除
（健康成人约 5 小时），下午的摄入到就寝时血液里还剩三分之一以上——
但直觉把咖啡因当成「饮用事件」，身体把它当成「持续存在的浓度」。
决策（15:30）与代价（23:30）相隔八小时，直觉无法把两者连起来，
于是每个睡不着的夜晚都以「我今天也没喝多少啊」结案。

afterburn 从一本可手编的摄入账本（TSV：日期 / 时间 / 饮品 / 可选毫克
覆盖）确定性算出：

  * now       此刻血液里还剩多少毫克——那杯下午的拿铁还烧着百分之几
  * bedtime   就寝时刻的残留预测与判灯：越过阈值红灯 exit 4
  * cutoff    今天最晚几点前还能喝这一杯（反解，不是查表）
  * day       当天的残留曲线（文本图）+ 逐小时浓度
  * week      近 7 天每天的就寝残留：红灯是常态还是偶然
  * steady    每日固定节奏的稳态：你醒来时带着谁的余燃
  * wean      戒断推演：停喝后残留何时归零、症状窗在几点
  * drinks    内置饮品咖啡因缺省表（均可用行级毫克覆盖）
  * validate  账本体检

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
「今天」默认真实当下，`--now` 钉死即逐字节可复现。

用法：
  python3 afterburn.py now ledger.tsv --now "2026-09-03 21:00"
  python3 afterburn.py bedtime ledger.tsv --at 23:30 --date 2026-09-03
  python3 afterburn.py cutoff ledger.tsv --at 23:30 --drink latte
  python3 afterburn.py week ledger.tsv --end 2026-09-04 --at 23:30
  python3 afterburn.py steady 08:30 drip 15:30 latte
  python3 afterburn.py wean ledger.tsv --now "2026-09-04 08:00"

Exit codes:
  0  report produced（含绿灯）
  2  usage error / ledger missing / malformed row / unknown drink without mg
  3  refusal: nothing to compute (empty ledger, no records in window)
  4  gate: bedtime residual above threshold（红灯）
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from typing import List, Optional, Tuple

PROG = "afterburn"
VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# 饮品缺省表：粗略中位（mg/份），波动区间与方法论见 METHODOLOGY.md。
# 行级第 4 列永远可以覆盖。宁可贵在覆盖，不贵在精确。
# ---------------------------------------------------------------------------
DRINKS = {
    "espresso": 63,          # 单份浓缩 ~30ml
    "espresso-double": 126,  # 双份浓缩
    "americano": 126,        # 连锁美式（双 shot）
    "drip": 95,              # 手冲 / 滴滤 ~240ml
    "cold-brew": 155,        # 冷萃 ~355ml
    "instant": 60,           # 速溶一勺 ~240ml
    "latte": 126,            # 拿铁（双 shot，国内门店常见）
    "cappuccino": 63,        # 卡布奇诺（单 shot）
    "mocha": 90,             # 摩卡
    "black-tea": 47,         # 红茶 ~240ml
    "green-tea": 28,         # 绿茶 ~240ml
    "matcha": 70,            # 抹茶一份
    "milk-tea": 50,          # 奶茶一杯（波动 20-100+，务必覆盖）
    "cola": 34,              # 可乐 330ml 罐
    "energy-drink": 80,      # 功能饮料 250ml
    "energy-can": 160,       # 功能饮料 500ml 罐
    "dark-chocolate": 20,    # 黑巧克力 ~40g
}

DEFAULT_HALF_LIFE = 5.0   # 小时；范围与个体差异见 METHODOLOGY.md
DEFAULT_THRESHOLD = 50.0  # 就寝残留 mg 判灯阈值；保守缺省，可调
DEFAULT_QUIET = 10.0      # wean 的「安静」线 mg
LOOKBACK_HOURS = 72.0     # 残留计算只回看 72h：exp(-72k) 截断误差 < 0.01mg
LOOKBACK_TERMS = 31       # steady 几何级数截断项数（30 天衰减已 < 1e-18）


class UsageError(Exception):
    """exit 2：参数或账本错误。"""


class Refusal(Exception):
    """exit 3：无可计算。"""


class RedLight(Exception):
    """exit 4：就寝残留越线。携带报告文本。"""


# ---------------------------------------------------------------------------
# 时间解析
# ---------------------------------------------------------------------------

def parse_hhmm(text: str) -> float:
    """'23:30' -> 23.5 小时。非法即 UsageError。"""
    try:
        hh, mm = text.split(":")
        h, m = int(hh), int(mm)
    except ValueError:
        raise UsageError("时间应为 HH:MM，得到 %r" % text)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise UsageError("时间超出范围: %r" % text)
    return h + m / 60.0


def parse_date(text: str) -> dt.date:
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise UsageError("日期应为 YYYY-MM-DD，得到 %r" % text)


def parse_datetime(text: str) -> dt.datetime:
    """'2026-09-03 21:00'（空格或 T 分隔）。"""
    parts = text.replace("T", " ").split()
    if len(parts) != 2:
        raise UsageError('--now 应为 "YYYY-MM-DD HH:MM"，得到 %r' % text)
    d = parse_date(parts[0])
    return dt.datetime.combine(d, dt.time(0)) + dt.timedelta(hours=parse_hhmm(parts[1]))


def fmt_hhmm(hours: float) -> str:
    h = int(hours) % 24
    m = int(round((hours - int(hours)) * 60))
    if m == 60:
        h, m = h + 1, 0
    return "%02d:%02d" % (h % 24, m)


def fmt_dt(x: dt.datetime) -> str:
    return x.strftime("%Y-%m-%d %H:%M")


def hours_between(early: dt.datetime, late: dt.datetime) -> float:
    return (late - early).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# 账本
# ---------------------------------------------------------------------------

class Entry:
    __slots__ = ("when", "drink", "mg", "lineno")

    def __init__(self, when: dt.datetime, drink: str, mg: float, lineno: int):
        self.when = when
        self.drink = drink
        self.mg = mg
        self.lineno = lineno


def normalize_drink(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(" ", "-")


def parse_ledger(path: str) -> List[Entry]:
    """TSV：date  time  drink  [mg]。# 注释与空行忽略；坏行带行号 exit 2。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise UsageError("无法读取账本 %s: %s" % (path, exc))

    entries: List[Entry] = []
    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t") if c.strip()]
        if len(cols) < 3:
            raise UsageError("第 %d 行：至少需要 3 列（日期/时间/饮品）" % idx)
        d = parse_date(cols[0])
        hh = parse_hhmm(cols[1])
        drink = normalize_drink(cols[2])
        when = dt.datetime.combine(d, dt.time(0)) + dt.timedelta(hours=hh)
        if len(cols) >= 4:
            if not _is_number(cols[3]):
                raise UsageError("第 %d 行：第 4 列应为毫克数，得到 %r" % (idx, cols[3]))
            mg = float(cols[3])
            if mg < 0:
                raise UsageError("第 %d 行：毫克数不能为负" % idx)
        else:
            if drink not in DRINKS:
                raise UsageError(
                    "第 %d 行：未知饮品 %r（饮品表见 `drinks`，或加第 4 列毫克覆盖）"
                    % (idx, cols[2])
                )
            mg = float(DRINKS[drink])
        entries.append(Entry(when, drink, mg, idx))
    return entries


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# 药代核心：单室一级消除 + 线性叠加
# ---------------------------------------------------------------------------

def decay_constant(half_life: float) -> float:
    if half_life <= 0:
        raise UsageError("--half-life 必须为正")
    return math.log(2.0) / half_life


def residual(dose: float, hours: float, k: float) -> float:
    """hours < 0（还没喝）贡献为 0。"""
    if hours < 0:
        return 0.0
    return dose * math.exp(-k * hours)


def concentration(entries: List[Entry], at: dt.datetime, k: float,
                  lookback: float = LOOKBACK_HOURS) -> float:
    total = 0.0
    for e in entries:
        h = hours_between(e.when, at)
        if 0 <= h <= lookback:
            total += residual(e.mg, h, k)
    return total


def contributions(entries: List[Entry], at: dt.datetime, k: float
                  ) -> List[Tuple[Entry, float]]:
    """每条摄入在 at 时刻的贡献，降序。只保留 >= 0.1mg 的有形贡献。"""
    pairs = []
    for e in entries:
        h = hours_between(e.when, at)
        c = residual(e.mg, h, k)
        if c >= 0.1:
            pairs.append((e, c))
    pairs.sort(key=lambda p: -p[1])
    return pairs


def solve_cutoff(entries: List[Entry], bedtime: dt.datetime, dose: float,
                 k: float, threshold: float) -> Optional[dt.datetime]:
    """最晚饮用时刻 t*：追加 dose 后就寝残留恰好等于阈值。

    t* = b + ln((threshold - C_rest)/dose)/k
    返回 None 表示额度已尽（现在喝就越线，或就寝前已超标）。
    """
    rest = concentration(entries, bedtime, k)
    budget = threshold - rest
    if budget <= 0:
        return None  # 还没喝就已经越线
    if dose <= 0:
        raise UsageError("--mg 必须为正")
    ratio = budget / dose
    if ratio >= 1.0:
        # 就寝当口喝全额都不越线：cutoff 即就寝时刻本身
        return bedtime
    return bedtime + dt.timedelta(hours=math.log(ratio) / k)


def steady_state(schedule: List[Tuple[float, float]], at_hour: float,
                 k: float) -> float:
    """每日重复节奏在 at_hour（天内小时）的稳态浓度。

    C = Σ_i D_i · Σ_{n>=0} exp(-k·(((at_hour - t_i) mod 24) + 24n))
    """
    total = 0.0
    for t_i, dose in schedule:
        lag = (at_hour - t_i) % 24.0
        geo = sum(math.exp(-k * (lag + 24 * n)) for n in range(LOOKBACK_TERMS))
        total += dose * geo
    return total


def quiet_crossing(entries: List[Entry], last: dt.datetime, k: float,
                   quiet: float) -> Optional[dt.datetime]:
    """停止摄入后，总残留首次降到 quiet 以下的时刻（逐分钟扫描，分钟粒度）。

    lookback 必须敞开：扫描终点本身就可能超过 72h，若沿用默认截断，
    边界处的浓度会突降为 0、把「还没安静」误判成「已经安静」。
    """
    t = last
    end = last + dt.timedelta(hours=72)
    while t <= end:
        if concentration(entries, t, k, lookback=float("inf")) <= quiet:
            return t
        t += dt.timedelta(minutes=1)
    return None


# ---------------------------------------------------------------------------
# 文本渲染
# ---------------------------------------------------------------------------

def bar(value: float, scale: float, width: int = 24) -> str:
    n = int(round(value / scale * width)) if scale > 0 else 0
    n = max(0, min(width, n))
    return "█" * n + "·" * (width - n)


def verdict(residual_mg: float, threshold: float) -> str:
    if residual_mg > threshold:
        return "RED   越线 %.0f%%" % (residual_mg / threshold * 100 - 100)
    if residual_mg > threshold * 0.7:
        return "AMBER 接近阈值（>70%）"
    return "GREEN"


def header(ledger: str, half_life: float, threshold: float, entries: List[Entry]) -> str:
    span = ""
    if entries:
        span = " / %s → %s" % (fmt_dt(entries[0].when), fmt_dt(entries[-1].when))
    return "\n".join([
        "余燃 · Afterburn — 咖啡因残留账本 v%s" % VERSION,
        "账本 %s（%d 条%s）  半衰期 %.1fh  阈值 %.0fmg" % (
            ledger, len(entries), span, half_life, threshold),
        "",
    ])


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def cmd_now(args) -> str:
    entries = parse_ledger(args.ledger)
    if not entries:
        raise Refusal("账本是空的：先记一笔（date  time  drink）再来看余燃")
    k = decay_constant(args.half_life)
    now = parse_datetime(args.now) if args.now else dt.datetime.now()
    live = [e for e in entries if e.when <= now]
    if not live:
        raise Refusal("%s 之前账本里没有任何摄入" % fmt_dt(now))
    c = concentration(live, now, k)
    parts = [header(args.ledger, args.half_life, args.threshold, entries)]
    parts.append("此刻 %s" % fmt_dt(now))
    parts.append("血液残留  %.1f mg   %s" % (c, bar(c, max(args.threshold * 2, c))))
    parts.append("")
    parts.append("谁在烧：")
    for e, contrib in contributions(live, now, k)[:5]:
        age = hours_between(e.when, now)
        parts.append("  %s  %-14s %5.0f mg → 还剩 %5.1f mg（%.0f%%）"
                     % (fmt_dt(e.when), e.drink, e.mg, contrib,
                        contrib / e.mg * 100 if e.mg else 0))
    parts.append("")
    parts.append("半衰期 %.1fh：上面的火每隔 %.1f 小时减半，直到你感觉不到它。" % (
        args.half_life, args.half_life))
    return "\n".join(parts)


def cmd_bedtime(args) -> str:
    entries = parse_ledger(args.ledger)
    if not entries:
        raise Refusal("账本是空的：bedtime 需要当天的摄入记录")
    k = decay_constant(args.half_life)
    now = parse_datetime(args.now) if args.now else dt.datetime.now()
    day = parse_date(args.date) if args.date else now.date()
    bed_hour = parse_hhmm(args.at)
    # 00:00-05:59 视为次日凌晨就寝
    bedtime = dt.datetime.combine(day, dt.time(0)) + dt.timedelta(hours=bed_hour)
    if bed_hour < 6.0:
        bedtime += dt.timedelta(days=1)
    day_entries = [e for e in entries if e.when.date() == day]
    if not day_entries:
        raise Refusal("%s 当天没有任何摄入记录——这天本来就该是绿灯" % day)
    c = concentration([e for e in entries if e.when <= bedtime], bedtime, k)
    v = verdict(c, args.threshold)
    parts = [header(args.ledger, args.half_life, args.threshold, entries)]
    parts.append("就寝 %s（%s）" % (fmt_dt(bedtime), args.at))
    parts.append("就寝残留  %.1f mg   %s" % (c, bar(c, max(args.threshold * 2, c))))
    parts.append("判定      %s（阈值 %.0fmg）" % (v, args.threshold))
    parts.append("")
    parts.append("谁在烧：")
    for e, contrib in contributions([e for e in entries if e.when <= bedtime], bedtime, k)[:5]:
        parts.append("  %s  %-14s 还剩 %5.1f mg" % (fmt_dt(e.when), e.drink, contrib))
    if c > args.threshold:
        parts.append("")
        parts.append("红灯的意思：不是今晚别睡，是明天这杯往前挪。")
        parts.append("  python3 afterburn.py cutoff %s --at %s --drink <饮品>" % (
            args.ledger, args.at))
        text = "\n".join(parts)
        raise RedLight(text)
    return "\n".join(parts)


def cmd_cutoff(args) -> str:
    entries = parse_ledger(args.ledger)
    if not entries:
        raise Refusal("账本是空的：cutoff 需要已摄入的记录来算余额")
    k = decay_constant(args.half_life)
    now = parse_datetime(args.now) if args.now else dt.datetime.now()
    day = parse_date(args.date) if args.date else now.date()
    bed_hour = parse_hhmm(args.at)
    bedtime = dt.datetime.combine(day, dt.time(0)) + dt.timedelta(hours=bed_hour)
    if bed_hour < 6.0:
        bedtime += dt.timedelta(days=1)
    drink = normalize_drink(args.drink)
    if args.mg:
        dose = args.mg
    elif drink in DRINKS:
        dose = float(DRINKS[drink])
    else:
        raise UsageError("未知饮品 %r：--mg 指定毫克，或用饮品表里的名字" % args.drink)
    past = [e for e in entries if e.when <= now]
    if not past:
        raise Refusal("现在之前没有任何摄入，额度是满的：随便喝")
    t_star = solve_cutoff(past, bedtime, dose, k, args.threshold)
    rest = concentration(past, bedtime, k)
    budget = args.threshold - rest
    parts = [header(args.ledger, args.half_life, args.threshold, entries)]
    parts.append("就寝 %s   目标饮品 %-14s %5.0f mg" % (fmt_dt(bedtime), drink, dose))
    parts.append("不喝这杯，就寝底座也已有 %.1f mg → 剩余额度 %.1f mg" % (rest, budget))
    parts.append("")
    if t_star is None:
        parts.append("额度已尽：这一杯此刻喝就越线（甚至不喝都已越线）。")
        parts.append("要喝，就接受红灯；要绿灯，今天到此为止。")
        return "\n".join(parts)
    if t_star >= bedtime:
        parts.append("随时：就寝当口喝全额都不越线——它根本够不着你的睡眠。")
        return "\n".join(parts)
    parts.append("最晚 %s 喝完这一杯。" % fmt_dt(t_star))
    if t_star < now:
        parts.append("")
        parts.append("  ——但现在已经 %s，窗口已经关了。这杯留给明天上午。" % fmt_dt(now))
    else:
        margin = hours_between(now, t_star)
        parts.append("距窗口关闭还有 %.1f 小时。" % margin)
    return "\n".join(parts)


def cmd_day(args) -> str:
    entries = parse_ledger(args.ledger)
    if not entries:
        raise Refusal("账本是空的：day 需要记录才能画曲线")
    k = decay_constant(args.half_life)
    now = parse_datetime(args.now) if args.now else dt.datetime.now()
    day = parse_date(args.date) if args.date else now.date()
    day_entries = [e for e in entries if e.when.date() == day]
    if not day_entries:
        raise Refusal("%s 当天没有任何摄入" % day)
    start = dt.datetime.combine(day, dt.time(0))
    end = start + dt.timedelta(days=1)
    cups = {}
    for e in day_entries:
        cups[round(hours_between(start, e.when))] = (e.drink, e.mg)
    samples = []
    peak = 0.0
    t = start
    while t <= end:
        c = concentration([e for e in entries if e.when <= t], t, k)
        hour = int(hours_between(start, t))
        samples.append((hour, c, cups.get(hour)))
        peak = max(peak, c)
        t += dt.timedelta(hours=1)
    scale = max(peak, 10.0)
    parts = [header(args.ledger, args.half_life, args.threshold, entries)]
    parts.append("%s 的残留曲线（0 点的底座是昨天的余燃；每格 %.0f mg）" % (
        day, scale / 24.0))
    parts.append("")
    for hour, c, cup in samples:
        label = "24:00" if hour == 24 else "%02d:00" % hour
        marker = "  ← %s %.0fmg" % (cup[0], cup[1]) if cup else ""
        parts.append("  %s  %6.1f mg  %s%s" % (label, c, bar(c, scale), marker))
    return "\n".join(parts)


def cmd_week(args) -> str:
    entries = parse_ledger(args.ledger)
    if not entries:
        raise Refusal("账本是空的：week 需要至少一天的记录")
    k = decay_constant(args.half_life)
    now = parse_datetime(args.now) if args.now else dt.datetime.now()
    end_day = parse_date(args.end) if args.end else now.date()
    bed_hour = parse_hhmm(args.at)
    parts = [header(args.ledger, args.half_life, args.threshold, entries)]
    parts.append("近 7 天就寝残留（就寝 %s）" % args.at)
    parts.append("")
    parts.append("  日期         摄入  最后一杯       就寝残留   判定")
    reds = 0
    for offset in range(6, -1, -1):
        day = end_day - dt.timedelta(days=offset)
        day_entries = [e for e in entries if e.when.date() == day]
        bedtime = dt.datetime.combine(day, dt.time(0)) + dt.timedelta(hours=bed_hour)
        if bed_hour < 6.0:
            bedtime += dt.timedelta(days=1)
        pool = [e for e in entries if e.when <= bedtime]
        c = concentration(pool, bedtime, k)
        total_mg = sum(e.mg for e in day_entries)
        last_cup = fmt_dt(day_entries[-1].when)[-5:] if day_entries else "--:--"
        v = verdict(c, args.threshold)
        if c > args.threshold:
            reds += 1
        parts.append("  %s   %3d mg  %s      %6.1f mg  %s" % (
            day, total_mg, last_cup, c, v.split()[0]))
    parts.append("")
    parts.append("7 晚里 %d 晚红灯。红灯是常态还是偶然，答案就在上面。" % reds)
    return "\n".join(parts)


def cmd_steady(args) -> str:
    tokens = args.schedule
    if len(tokens) < 2 or len(tokens) % 2 != 0:
        raise UsageError("steady 需要 HH:MM drink 成对出现，如：steady 08:30 drip 15:30 latte")
    k = decay_constant(args.half_life)
    schedule = []
    names = []
    for i in range(0, len(tokens), 2):
        t = parse_hhmm(tokens[i])
        drink = normalize_drink(tokens[i + 1])
        if drink not in DRINKS:
            raise UsageError("未知饮品 %r（用饮品表名字，steady 不支持行级覆盖，"
                             "请用 now/bedtime 的账本路线）" % tokens[i + 1])
        schedule.append((t, float(DRINKS[drink])))
        names.append("%s %s" % (fmt_hhmm(t), drink))
    daily = sum(d for _, d in schedule)
    parts = [
        "余燃 · Afterburn — 稳态推演 v%s" % VERSION,
        "每日节奏 %s（共 %.0f mg/天）  半衰期 %.1fh  阈值 %.0fmg" % (
            " + ".join(names), daily, args.half_life, args.threshold),
        "",
        "假如天天照这个节奏喝，稳态下一天内的浓度曲线：",
        "",
    ]
    peak = max(steady_state(schedule, h / 2.0, k) for h in range(48))
    scale = max(peak, 10.0)
    for h in range(0, 24, 2):
        c = steady_state(schedule, float(h), k)
        parts.append("  %02d:00  %6.1f mg  %s" % (h, c, bar(c, scale)))
    parts.append("")
    morning = steady_state(schedule, (min(t for t, _ in schedule) - 0.5) % 24.0, k)
    parts.append("首杯前半小时，你已经带着 %.1f mg 醒来——那是昨天的余燃。" % morning)
    parts.append("它们不叫「睡不着」，叫「没醒透」。")
    return "\n".join(parts)


def cmd_wean(args) -> str:
    entries = parse_ledger(args.ledger)
    if not entries:
        raise Refusal("账本是空的：wean 需要历史摄入来定位戒断起点")
    k = decay_constant(args.half_life)
    now = parse_datetime(args.now) if args.now else dt.datetime.now()
    stop_at = parse_datetime(args.stop) if args.stop else now
    past = [e for e in entries if e.when <= stop_at]
    if not past:
        raise Refusal("%s 之前没有任何摄入" % fmt_dt(stop_at))
    last = max(e.when for e in past)
    quiet_t = quiet_crossing(past, stop_at, k, args.quiet)
    parts = [header(args.ledger, args.half_life, args.threshold, entries)]
    parts.append("从 %s 起一滴不喝：" % fmt_dt(stop_at))
    parts.append("  最后一杯   %s" % fmt_dt(last))
    parts.append("  停喝时残留 %.1f mg" % concentration(past, stop_at, k))
    if quiet_t is not None:
        parts.append("  安静线 %.0fmg  %s 达到（残留降到安静线以下）" % (
            args.quiet, fmt_dt(quiet_t)))
    else:
        parts.append("  72h 内残留未降到安静线以下（半衰期过长？--half-life 检查）")
    parts.append("")
    parts.append("文献戒断窗（Juliano & Griffiths 2004 综述，是标注不是计算）：")
    onset = last + dt.timedelta(hours=12)
    peak_a, peak_b = last + dt.timedelta(hours=20), last + dt.timedelta(hours=51)
    ease_a, ease_b = last + dt.timedelta(hours=48), last + timedelta_days(9)
    parts.append("  12–24h 症状起病  %s 前后" % onset.strftime("%m-%d %H:%M"))
    parts.append("  20–51h 头痛达峰  %s → %s" % (peak_a.strftime("%m-%d %H:%M"),
                                                 peak_b.strftime("%m-%d %H:%M")))
    parts.append("  2–9 天消退       %s → %s" % (ease_a.strftime("%m-%d %H:%M"),
                                                 ease_b.strftime("%m-%d %H:%M")))
    parts.append("")
    parts.append("戒断不是意志力问题，是时间表问题：把达峰安排在周末，")
    parts.append("工作日的你就只是「有点困」，不是「裂开」。")
    return "\n".join(parts)


def timedelta_days(n: float) -> dt.timedelta:
    return dt.timedelta(days=n)


def cmd_drinks(args) -> str:
    parts = [
        "余燃 · Afterburn — 饮品缺省表 v%s" % VERSION,
        "",
        "  名字               mg/份     说明",
        "  " + "-" * 56,
    ]
    notes = {
        "espresso": "单份浓缩 ~30ml",
        "espresso-double": "双份浓缩",
        "americano": "连锁美式（双 shot）",
        "drip": "手冲 / 滴滤 ~240ml",
        "cold-brew": "冷萃 ~355ml",
        "instant": "速溶一勺 ~240ml",
        "latte": "拿铁（双 shot）",
        "cappuccino": "卡布奇诺（单 shot）",
        "mocha": "摩卡",
        "black-tea": "红茶 ~240ml",
        "green-tea": "绿茶 ~240ml",
        "matcha": "抹茶一份",
        "milk-tea": "奶茶（波动 20–100+，务必覆盖）",
        "cola": "可乐 330ml 罐",
        "energy-drink": "功能饮料 250ml",
        "energy-can": "功能饮料 500ml 罐",
        "dark-chocolate": "黑巧克力 ~40g",
    }
    for name, mg in DRINKS.items():
        parts.append("  %-18s %5d     %s" % (name, mg, notes.get(name, "")))
    parts.append("")
    parts.append("缺省是粗略中位，来源与波动见 METHODOLOGY.md。")
    parts.append("账本第 4 列永远可以覆盖：`2026-09-03  15:30  milk-tea  120`")
    return "\n".join(parts)


def cmd_validate(args) -> str:
    entries = parse_ledger(args.ledger)  # 坏行在这里就抛 UsageError
    if not entries:
        raise Refusal("账本是空的：没有任何可校验的行")
    entries_sorted = sorted(entries, key=lambda e: e.when)
    dup = 0
    seen = set()
    for e in entries_sorted:
        key = (e.when, e.drink)
        if key in seen:
            dup += 1
        seen.add(key)
    unordered = 0
    for a, b in zip(entries, entries[1:]):
        if a.when > b.when:
            unordered += 1
    by_drink = {}
    for e in entries:
        by_drink[e.drink] = by_drink.get(e.drink, 0) + 1
    parts = [
        "余燃 · Afterburn — 账本体检 v%s" % VERSION,
        "",
        "  行数       %d" % len(entries),
        "  跨度       %s → %s" % (fmt_dt(entries_sorted[0].when),
                                   fmt_dt(entries_sorted[-1].when)),
        "  乱序行     %d（不影响计算，只影响可读性）" % unordered,
        "  完全重复   %d（同刻同饮品，可能是手滑）" % dup,
        "  饮品分布   %s" % ", ".join("%s×%d" % kv for kv in
                                        sorted(by_drink.items(),
                                               key=lambda p: -p[1])),
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command")

    def add_common(sp, ledger=True):
        if ledger:
            sp.add_argument("ledger")
        sp.add_argument("--half-life", type=float, default=DEFAULT_HALF_LIFE,
                        help="咖啡因消除半衰期（小时，缺省 %.1f）" % DEFAULT_HALF_LIFE)
        sp.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="就寝残留判灯阈值 mg（缺省 %.0f）" % DEFAULT_THRESHOLD)
        sp.add_argument("--now", default=None,
                        help='钉死"现在"："YYYY-MM-DD HH:MM"，用于复现')

    sp = sub.add_parser("now", help="此刻血液残留")
    add_common(sp)

    sp = sub.add_parser("bedtime", help="就寝残留预测与判灯（越线 exit 4）")
    add_common(sp)
    sp.add_argument("--at", required=True, help="就寝时间 HH:MM（00:00–05:59 视为次日凌晨）")
    sp.add_argument("--date", default=None, help="YYYY-MM-DD，缺省今天")

    sp = sub.add_parser("cutoff", help="今天最晚几点前喝完这一杯")
    add_common(sp)
    sp.add_argument("--at", required=True, help="就寝时间 HH:MM")
    sp.add_argument("--drink", required=True, help="饮品名（饮品表）")
    sp.add_argument("--mg", type=float, default=None, help="覆盖剂量 mg")
    sp.add_argument("--date", default=None, help="YYYY-MM-DD，缺省今天")

    sp = sub.add_parser("day", help="当天残留曲线（文本图）")
    add_common(sp)
    sp.add_argument("--date", default=None, help="YYYY-MM-DD，缺省今天")

    sp = sub.add_parser("week", help="近 7 天就寝残留与判灯")
    add_common(sp)
    sp.add_argument("--at", default="23:30", help="就寝时间 HH:MM（缺省 23:30）")
    sp.add_argument("--end", default=None, help="窗口末日 YYYY-MM-DD，缺省今天")

    sp = sub.add_parser("steady", help="每日固定节奏的稳态推演（无需账本）")
    add_common(sp, ledger=False)
    sp.add_argument("schedule", nargs="+", metavar="HH:MM drink",
                    help='如 08:30 drip 15:30 latte')

    sp = sub.add_parser("wean", help="戒断推演：归零时刻 + 文献症状窗")
    add_common(sp)
    sp.add_argument("--stop", default=None, help='戒断起点 "YYYY-MM-DD HH:MM"，缺省 --now')
    sp.add_argument("--quiet", type=float, default=DEFAULT_QUIET,
                    help="安静线 mg（缺省 %.0f）" % DEFAULT_QUIET)

    sub.add_parser("drinks", help="饮品缺省表")

    sp = sub.add_parser("validate", help="账本体检")
    sp.add_argument("ledger")

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    handlers = {
        "now": cmd_now,
        "bedtime": cmd_bedtime,
        "cutoff": cmd_cutoff,
        "day": cmd_day,
        "week": cmd_week,
        "steady": cmd_steady,
        "wean": cmd_wean,
        "drinks": cmd_drinks,
        "validate": cmd_validate,
    }
    try:
        text = handlers[args.command](args)
    except UsageError as exc:
        print("用法错误：%s" % exc, file=sys.stderr)
        return 2
    except Refusal as exc:
        print("拒算：%s" % exc, file=sys.stderr)
        return 3
    except RedLight as exc:
        print(exc)
        return 4
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
