#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""borrowed-silence · 预支安静 —— 噪音剂量账本.

问题：听力损伤是唯一没有「后悔药」的慢性消耗——耳蜗毛细胞死于噪音后
不再生，而剂量本身不疼不痒、完全不可感知。地铁上为听清播客把耳机推到
100dB 的人，每个通勤日吃掉 4 个安全日（85dB×8h = 1.0）；一场不戴耳塞的
livehouse（105dB×2.5h）= 31.8 个安全日，是一周额度的 6 倍。直觉把音量
当成「舒服不舒服」的事，身体把它当成**永不代谢的累积账**：咖啡因按半衰
期消除，跑步超量会超量恢复，唯独噪音——额度按周重置，损伤只增不减。

borrowed-silence 从一本可手编的暴露账本（TSV：日期 / 时间 / 声源 / 时长
/ 可选 dB 覆盖 / 可选耳塞 NRR）按 NIOSH 3dB 交换率确定性算出：

  * day       当日剂量分解与判灯：谁最贵、Leq(8h)、耳鸣回执
  * week      近 7 天的额度账：周额度 5.0 安全日，超支倍数与声源排行
  * plan      把一个计划事件对所在周的余量过闸：裸奔 / 戴耳塞两条命
  * lifetime  终身账：只增不减的安全日总量、声源分布、年化外推
  * sources   内置声源缺省表（dBA 中位 + 1 小时价值）
  * validate  账本体检

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
日期一律用 --date / --end / --week-of 钉死，逐字节可复现。

用法：
  python3 borrowed_silence.py day ledger.tsv --date 2026-09-05
  python3 borrowed_silence.py week ledger.tsv --end 2026-09-06
  python3 borrowed_silence.py plan ledger.tsv livehouse 2:30 --week-of 2026-09-07
  python3 borrowed_silence.py lifetime ledger.tsv
  python3 borrowed_silence.py sources
  python3 borrowed_silence.py validate ledger.tsv

Exit codes:
  0  report produced（含绿灯 / FITS）
  2  usage error / ledger missing / malformed row / unknown source without dB
  3  refusal: nothing to compute (empty ledger, no records in window)
  4  gate: 日剂量越线 / 周额度超支 / 计划装不进余量（PLUGS / OVER）
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from typing import List, Optional, Tuple

PROG = "borrowed-silence"
VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# 剂量学常量（NIOSH 1998 REL）
# ---------------------------------------------------------------------------
REF_LEVEL = 85.0   # dB(A)：参考声级（8 小时 TWA = 1.0 安全日）
REF_HOURS = 8.0    # 参考时长（小时）
EXCHANGE = 3.0     # 交换率 dB：每 +3dB，允许时长减半（能量上自洽）
WEEK_BUDGET_SD = 5.0   # 周额度：5 个安全日 = 40h @ 85dB（职业一周上限）
PLUG_DEFAULT_NRR = 32  # plan 的默认耳塞（市面泡沫耳塞常见档）
WEEKDAYS_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 声源缺省表：dBA 中位数。波动区间与出处见 METHODOLOGY.md。
# 第 5 列 dB 永远可以按行覆盖；未知声源 + 有覆盖 = 自定义声源，合法。
SOURCES = {
    "home-quiet":       40,  # 安静的家里
    "library":          45,
    "office":           55,  # 开放办公室
    "conversation":     60,  # 正常交谈
    "cafe":             70,  # 咖啡馆
    "hairdryer":        70,
    "restaurant":       75,  # 热闹餐厅
    "bus":              75,
    "street":           80,  # 临街人行道
    "metro":            85,  # 地铁车厢（80-95，拥挤线路更高）
    "airplane-cabin":   85,
    "cinema":           85,  # 影院动作片峰值段
    "headphone-normal": 85,  # 安静环境里的耳机中等音量
    "earbuds-street":   95,  # 街上为盖噪推高的入耳式
    "lawnmower":        90,
    "motorcycle":       95,
    "gym-class":        95,  # 健身团课（音响为了氛围）
    "construction":     95,
    "bar-club":         95,
    "headphone-loud":   100,  # 通勤耳机盖噪档（常见！）
    "ktv":              100,
    "headphone-max":    105,
    "livehouse":        105,  # Livehouse 站前排 / 演出厅
    "concert":          110,  # 演唱会 / 音乐节主音响区
}


class UsageError(Exception):
    """exit 2：参数或账本错误。"""


class Refusal(Exception):
    """exit 3：无可计算。"""


# ---------------------------------------------------------------------------
# 剂量学核心：全部是闭式算术，确定性可测
# ---------------------------------------------------------------------------

def safe_days(level_db: float, hours: float) -> float:
    """NIOSH 剂量（安全日单位）：85dB×8h = 1.0，每 +3dB 时长减半。

    sd = hours × 2^((L-85)/3) / 8
    """
    if hours < 0:
        raise UsageError("时长不能为负: %r" % hours)
    return hours * (2.0 ** ((level_db - REF_LEVEL) / EXCHANGE)) / REF_HOURS


def plug_derate(nrr: float) -> float:
    """NIOSH 耳塞折减：实际减免 = (NRR − 7) / 2 dB。

    厂商标称 NRR 是实验室理想值，NIOSH 建议按此式折半再用——
    戴法歪一点、头发夹一点，减免就打对折，折减式是给「真人」的。
    """
    if nrr <= 0:
        raise UsageError("NRR 应为正数: %r" % nrr)
    return (nrr - 7.0) / 2.0


def effective_level(level_db: float, nrr: Optional[float]) -> float:
    """戴耳塞后的耳内有效声级。"""
    if nrr is None:
        return level_db
    return level_db - plug_derate(nrr)


def leq8h(total_sd: float) -> float:
    """把一段暴露折成 8 小时等效连续声级：Leq = 85 + 10·log10(总安全日)。

    0 安全日在对数域无定义，返回 0（静默）。
    """
    if total_sd <= 0:
        return 0.0
    return REF_LEVEL + 10.0 * math.log10(total_sd)


# ---------------------------------------------------------------------------
# 账本解析
# ---------------------------------------------------------------------------

def parse_duration(text: str) -> float:
    """时长 → 小时。接受 `0:45` / `2:30` / `2h` / `45m` / `2h30m`。"""
    text = text.strip()
    if not text:
        raise UsageError("时长不能为空")
    if ":" in text:
        try:
            hh, mm = text.split(":", 1)
            h, m = int(hh), int(mm)
        except ValueError:
            raise UsageError("时长 H:MM 格式不对: %r" % text)
        if m >= 60 or h < 0 or (h == 0 and m == 0):
            raise UsageError("时长 H:MM 超出范围: %r" % text)
        return h + m / 60.0
    hours, minutes, total = 0.0, 0.0, 0.0
    rest = text
    while rest:
        if rest[0] in "0123456789.":
            # 数字段
            i = 0
            while i < len(rest) and (rest[i] in "0123456789."):
                i += 1
            num_text, rest = rest[:i], rest[i:]
            try:
                num = float(num_text)
            except ValueError:
                raise UsageError("时长格式不对: %r" % text)
            if rest[:1] == "h":
                hours, rest = num, rest[1:]
            elif rest[:1] == "m":
                minutes, rest = num, rest[1:]
            else:
                raise UsageError("时长需要 h/m 单位: %r" % text)
        else:
            raise UsageError("时长格式不对: %r" % text)
    total = hours + minutes / 60.0
    if total <= 0:
        raise UsageError("时长必须为正: %r" % text)
    return total


def fmt_duration(hours: float) -> str:
    """小时 → `H:MM`。"""
    total_min = int(round(hours * 60))
    return "%d:%02d" % (total_min // 60, total_min % 60)


def parse_date(text: str) -> dt.date:
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise UsageError("日期应为 YYYY-MM-DD，得到 %r" % text)


class Event:
    """一条暴露事件。symptom 行是「身体的对账单」，不计剂量。"""

    __slots__ = ("date", "minutes_of_day", "source", "hours", "db_override",
                 "nrr", "is_symptom", "symptom", "lineno")

    def __init__(self, date, minutes_of_day, source, hours, db_override,
                 nrr, is_symptom, symptom, lineno):
        self.date = date
        self.minutes_of_day = minutes_of_day
        self.source = source
        self.hours = hours
        self.db_override = db_override
        self.nrr = nrr
        self.is_symptom = is_symptom
        self.symptom = symptom
        self.lineno = lineno

    @property
    def clock(self) -> str:
        return "%02d:%02d" % (self.minutes_of_day // 60, self.minutes_of_day % 60)

    def level_db(self) -> float:
        if self.db_override is not None:
            return self.db_override
        if self.source in SOURCES:
            return float(SOURCES[self.source])
        raise UsageError("第 %d 行：未知声源 %r 且无 dB 覆盖" % (self.lineno, self.source))

    def safe_days(self) -> float:
        if self.is_symptom:
            return 0.0
        return safe_days(effective_level(self.level_db(), self.nrr), self.hours)


def parse_ledger(path: str) -> List[Event]:
    """读 TSV 账本。列：日期/时间/声源/时长/[dB]/[NRR]；symptom 行第 4 列为症状名。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise UsageError("读不了账本 %s: %s" % (path, exc))
    events: List[Event] = []
    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in raw.split("\t")]
        if len(cols) < 4:
            raise UsageError("第 %d 行：至少需要 日期/时间/声源/时长 4 列（symptom 行 3 列）: %r"
                             % (idx, raw))
        date = parse_date(cols[0])
        try:
            hh, mm = cols[1].split(":")
            minutes_of_day = int(hh) * 60 + int(mm)
            if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                raise ValueError
        except ValueError:
            raise UsageError("第 %d 行：时间应为 HH:MM: %r" % (idx, cols[1]))
        source = cols[2]
        nrr = None
        if len(cols) >= 6 and cols[5]:
            try:
                nrr = float(cols[5])
            except ValueError:
                raise UsageError("第 %d 行：NRR 应为数字: %r" % (idx, cols[5]))
            if not (0 < nrr <= 40):
                raise UsageError("第 %d 行：NRR 超出合理范围 0-40: %r" % (idx, cols[5]))
        db_override = None
        if len(cols) >= 5 and cols[4]:
            try:
                db_override = float(cols[4])
            except ValueError:
                raise UsageError("第 %d 行：dB 覆盖应为数字: %r" % (idx, cols[4]))
            if not (30.0 <= db_override <= 140.0):
                raise UsageError("第 %d 行：dB 超出合理范围 30-140: %r" % (idx, cols[4]))
        if source == "symptom":
            if cols[3] == "":
                raise UsageError("第 %d 行：symptom 行第 4 列应为症状名（如 tinnitus / muffled）" % idx)
            events.append(Event(date, minutes_of_day, source, 0.0, None, None,
                                True, cols[3], idx))
            continue
        if source != "symptom" and source not in SOURCES and db_override is None:
            raise UsageError("第 %d 行：未知声源 %r（第 5 列给 dB 覆盖可自定义声源）"
                             % (idx, source))
        hours = parse_duration(cols[3])
        events.append(Event(date, minutes_of_day, source, hours, db_override,
                            nrr, False, None, idx))
    return events


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------

def events_on_day(events: List[Event], day: dt.date) -> List[Event]:
    return [e for e in events if e.date == day]


def day_dose(events: List[Event], day: dt.date) -> float:
    return sum(e.safe_days() for e in events_on_day(events, day)
               if not e.is_symptom)


def week_window(end: dt.date) -> Tuple[dt.date, dt.date]:
    return end - dt.timedelta(days=6), end


def week_of(day: dt.date) -> Tuple[dt.date, dt.date]:
    """包含 day 的自然周（周一 → 周日）。"""
    monday = day - dt.timedelta(days=day.weekday())
    return monday, monday + dt.timedelta(days=6)


def week_dose(events: List[Event], start: dt.date, end: dt.date) -> float:
    return sum(e.safe_days() for e in events
               if not e.is_symptom and start <= e.date <= end)


def fmt_sd(sd: float) -> str:
    if sd >= 10:
        return "%.1f" % sd
    return "%.2f" % sd


def bar(frac: float, width: int = 24) -> str:
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return "█" * filled + "·" * (width - filled)


def source_breakdown(events: List[Event], start: dt.date, end: dt.date):
    """声源 → (总安全日, 占比)。按贡献降序。"""
    totals = {}
    for e in events:
        if e.is_symptom or not (start <= e.date <= end):
            continue
        totals[e.source] = totals.get(e.source, 0.0) + e.safe_days()
    grand = sum(totals.values())
    ordered = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return ordered, grand


def symptom_lines(events: List[Event], start: dt.date, end: dt.date) -> List[Event]:
    return [e for e in events if e.is_symptom and start <= e.date <= end]


# ---------------------------------------------------------------------------
# 命令：day
# ---------------------------------------------------------------------------

def cmd_day(args) -> int:
    events = parse_ledger(args.ledger)
    if not events:
        raise Refusal("账本里没有任何记录。")
    day = parse_date(args.date)
    day_events = events_on_day(events, day)
    if not day_events:
        raise Refusal("%s 没有任何记录（账本跨度 %s → %s）。"
                      % (day, min(e.date for e in events), max(e.date for e in events)))
    dose = day_dose(events, day)
    lines: List[str] = []
    lines.append("%s %s" % (day.isoformat(), WEEKDAYS_CN[day.weekday()]))
    verdict = "RED" if dose > 1.0 else "GREEN"
    lines.append("日剂量  %s 安全日  %s (%.0f%% of 1.0)   %s"
                 % (fmt_sd(dose), bar(min(dose, 1.0)),
                    dose * 100, verdict))
    if dose > 0:
        lines.append("Leq(8h)  %.1f dB(A)  折成 8 小时连续暴露的等效声级" % leq8h(dose))
    lines.append("")
    lines.append("事件分解（最贵的在上）：")
    ranked = sorted([e for e in day_events if not e.is_symptom],
                    key=lambda e: -e.safe_days())
    for e in ranked:
        lvl = effective_level(e.level_db(), e.nrr)
        plug_note = "（戴 NRR%s 耳塞）" % fmt_num(e.nrr) if e.nrr else ""
        lines.append("  %s  %-18s %5s  %5.1f dB → %6s sd%s"
                     % (e.clock, e.source, fmt_duration(e.hours),
                        lvl, fmt_sd(e.safe_days()), plug_note))
    sympt = [e for e in day_events if e.is_symptom]
    if sympt:
        lines.append("")
        for e in sympt:
            lines.append("⚠ 身体的对账单：%s 记录 %s——耳鸣/耳闷是超载的回执，"
                         "建议次日保持 <70dB（cafe 以下）" % (e.clock, e.symptom))
    text = "\n".join(lines)
    print(text)
    return 4 if dose > 1.0 else 0


def fmt_num(x: Optional[float]) -> str:
    if x is None:
        return "-"
    if float(x).is_integer():
        return str(int(x))
    return "%.1f" % x


# ---------------------------------------------------------------------------
# 命令：week
# ---------------------------------------------------------------------------

def cmd_week(args) -> int:
    events = parse_ledger(args.ledger)
    if not events:
        raise Refusal("账本里没有任何记录。")
    end = parse_date(args.end)
    start, _ = week_window(end)
    budget = args.budget if args.budget is not None else WEEK_BUDGET_SD
    in_window = [e for e in events if start <= e.date <= end]
    if not in_window:
        raise Refusal("窗口 %s → %s 没有任何记录（账本跨度 %s → %s）。"
                      % (start, end, min(e.date for e in events), max(e.date for e in events)))
    total = week_dose(events, start, end)
    lines: List[str] = []
    lines.append("近 7 天  %s → %s" % (start, end))
    lines.append("")
    lines.append("每日剂量（1.0 安全日 = 85dB × 8h）：")
    d = start
    while d <= end:
        dd = day_dose(events, d)
        n_ev = len(events_on_day(events, d))
        marker = ""
        if dd > 1.0:
            marker = "  RED"
        elif n_ev:
            marker = "  ok"
        lines.append("  %s %s  %7s sd  %s%s"
                     % (d.strftime("%m-%d"), WEEKDAYS_CN[d.weekday()],
                        fmt_sd(dd), bar(min(dd, 8.0) / 8.0, 16), marker))
        d += dt.timedelta(days=1)
    lines.append("")
    frac = total / budget
    lines.append("周总剂量  %s 安全日   %s (%.0f%% of 周额度 %s)"
                 % (fmt_sd(total), bar(min(frac, 1.0)), frac * 100, fmt_sd(budget)))
    text = "\n".join(lines)
    ordered, grand = source_breakdown(events, start, end)
    if ordered:
        lines.append("")
        lines.append("最贵的声源（本周）：")
        for src, sd in ordered[:5]:
            lines.append("  %-18s %7s sd  %3.0f%%"
                         % (src, fmt_sd(sd), 100.0 * sd / grand if grand else 0.0))
    sympt = symptom_lines(events, start, end)
    if sympt:
        lines.append("")
        lines.append("身体的对账单：本周 %d 次症状记录（%s）——"
                     "耳鸣不是「睡一觉就好」的小事，是耳蜗在报警"
                     % (len(sympt), ", ".join(e.symptom for e in sympt)))
    if total > budget:
        text += "\n" + "\n".join([
            "",
            "超支  %s 安全日 —— 你这周借走了 %.1f 周的安静" % (fmt_sd(total - budget), frac),
            "额度按周一重置，损伤不重置：终身账 lifetime 只增不减。",
        ])
        print(text)
        return 4
    print(text)
    return 0


# ---------------------------------------------------------------------------
# 命令：plan
# ---------------------------------------------------------------------------

def cmd_plan(args) -> int:
    events = parse_ledger(args.ledger)
    hours = parse_duration(args.duration)
    anchor = parse_date(args.week_of)
    ws, we = week_of(anchor)
    budget = args.budget if args.budget is not None else WEEK_BUDGET_SD
    used = week_dose(events, ws, we)
    remaining = budget - used
    level = args.db if args.db is not None else (
        float(SOURCES[args.source]) if args.source in SOURCES else None)
    if level is None:
        raise UsageError("未知声源 %r 且未给 --db" % args.source)
    if level <= 0:
        raise UsageError("--db 应为正数")
    nrr = args.plug

    bare_sd = safe_days(level, hours)
    plugged_sd = safe_days(effective_level(level, nrr), hours) if nrr else None

    lines: List[str] = []
    lines.append("计划事件  %s %s @ %.1f dB(A)%s"
                 % (args.source, args.duration, level,
                    "（声源缺省，--db 可覆盖）" if args.db is None else "（行级覆盖）"))
    lines.append("所在周    %s → %s   额度 %s sd，已用 %s，余量 %s"
                 % (ws, we, fmt_sd(budget), fmt_sd(used), fmt_sd(max(remaining, 0.0))))
    lines.append("")
    lines.append("  不戴耳塞        %6.1f dB → %7s sd" % (level, fmt_sd(bare_sd)))
    if plugged_sd is not None:
        lines.append("  戴 NRR%s 耳塞     %6.1f dB → %7s sd（折减 %.1f dB）"
                     % (fmt_num(nrr), effective_level(level, nrr), fmt_sd(plugged_sd),
                        plug_derate(nrr)))
    lines.append("")
    fits_bare = bare_sd <= remaining
    fits_plug = plugged_sd is not None and plugged_sd <= remaining
    if fits_bare:
        verdict = "FITS"
        lines.append("裁决  FITS —— 裸奔也装得进本周余量（用掉 %s，剩 %s）。"
                     % (fmt_sd(bare_sd), fmt_sd(remaining - bare_sd)))
        exit_code = 0
    elif fits_plug:
        verdict = "PLUGS"
        lines.append("裁决  PLUGS —— 裸奔超余量 %.1f 倍，戴上 NRR%s 后只花 %s sd，"
                     "装得下（剩 %s）。" % (bare_sd / max(remaining, 1e-9), fmt_num(nrr),
                                           fmt_sd(plugged_sd),
                                           fmt_sd(remaining - plugged_sd)))
        lines.append("同一晚的两种活法差 %.1f 倍：耳塞不是懦弱，是打折券。" % (bare_sd / plugged_sd))
        exit_code = 4
    else:
        verdict = "OVER"
        lines.append("裁决  OVER —— 戴上 NRR%s 也装不进本周余量（需 %s sd，只剩 %s）。"
                     % (fmt_num(nrr), fmt_sd(plugged_sd if plugged_sd else bare_sd),
                        fmt_sd(max(remaining, 0.0))))
        if plugged_sd:
            lines.append("这周已经借得太多，把演出改到下周，或换一场更安静的。")
        exit_code = 4
    text = "\n".join(lines)
    print(text)
    return exit_code


# ---------------------------------------------------------------------------
# 命令：lifetime
# ---------------------------------------------------------------------------

def cmd_lifetime(args) -> int:
    events = parse_ledger(args.ledger)
    real = [e for e in events if not e.is_symptom]
    if not real:
        raise Refusal("账本里没有任何暴露事件（symptom 行不计剂量）。")
    first, last = min(e.date for e in real), max(e.date for e in real)
    span_days = (last - first).days + 1
    total_sd = sum(e.safe_days() for e in real)
    ordered, _ = source_breakdown(real, first, last)
    sympt = [e for e in events if e.is_symptom]
    annualized = total_sd / span_days * 365.0
    lines: List[str] = []
    lines.append("账本跨度  %s → %s（%d 天）" % (first, last, span_days))
    lines.append("终身累计  %s 安全日 = %.0f 等效 85dB 小时"
                 % (fmt_sd(total_sd), total_sd * 8.0))
    lines.append("")
    lines.append("这些能量若摊成 85dB 连续暴露，相当于 %.1f 个完整工作日（8h）在轰鸣中度过。"
                 % total_sd)
    lines.append("按账本跨度线性外推：约 %.0f 安全日/年（样本越短越粗）。" % annualized)
    lines.append("")
    lines.append("声源分布（终身）：")
    for src, sd in ordered[:8]:
        lines.append("  %-18s %7s sd  %3.0f%%"
                     % (src, fmt_sd(sd), 100.0 * sd / total_sd if total_sd else 0.0))
    if sympt:
        lines.append("")
        lines.append("身体的对账单：共 %d 次症状记录（%s）。"
                     % (len(sympt), ", ".join(e.symptom for e in sympt)))
    lines.append("")
    lines.append("额度按周重置，损伤不重置：安全日清零重来，终身账只增不减。")
    lines.append("本账本只记物理剂量，不预言具体听阈——那是耳科医生和听力计的事。")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# 命令：sources / validate
# ---------------------------------------------------------------------------

def cmd_sources(args) -> int:
    lines: List[str] = []
    lines.append("声源缺省表（dBA 中位；账本第 5 列 dB 永远可以按行覆盖）：")
    lines.append("")
    lines.append("  %-18s %5s   %10s" % ("声源", "dB", "1 小时"))
    for src, lvl in sorted(SOURCES.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append("  %-18s %5.0f   %7s sd" % (src, lvl, fmt_sd(safe_days(float(lvl), 1.0))))
    lines.append("")
    lines.append("1 小时 @110dB = %s 个安全日：世界上没有「就听一小会儿」的 110dB。"
                 % fmt_sd(safe_days(110.0, 1.0)))
    print("\n".join(lines))
    return 0


def cmd_validate(args) -> int:
    events = parse_ledger(args.ledger)
    if not events:
        raise Refusal("账本里没有任何记录。")
    real = [e for e in events if not e.is_symptom]
    sympt = [e for e in events if e.is_symptom]
    custom = sorted({e.source for e in real if e.db_override is not None
                     and e.source not in SOURCES})
    overridden = sorted({e.source for e in real if e.db_override is not None
                         and e.source in SOURCES})
    plugged = [e for e in real if e.nrr is not None]
    lines: List[str] = []
    lines.append("账本体检：%d 条事件，%d 条症状记录" % (len(real), len(sympt)))
    if real:
        lines.append("日期跨度 %s → %s" % (min(e.date for e in real),
                                           max(e.date for e in real)))
    lines.append("自定义声源（表外，靠 dB 覆盖成立）：%s"
                 % (", ".join(custom) if custom else "无"))
    lines.append("声源表覆盖（行级 dB 改写缺省）：%s"
                 % (", ".join(overridden) if overridden else "无"))
    lines.append("戴耳塞的行：%d 条" % len(plugged))
    total_sd = sum(e.safe_days() for e in real)
    lines.append("全账本总剂量：%s 安全日" % fmt_sd(total_sd))
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description="预支安静 · 噪音剂量账本")
    p.add_argument("--version", action="version", version="%s %s" % (PROG, VERSION))
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("day", help="当日剂量分解与判灯")
    sp.add_argument("ledger")
    sp.add_argument("--date", required=True)
    sp.set_defaults(func=cmd_day)

    sp = sub.add_parser("week", help="近 7 天额度账")
    sp.add_argument("ledger")
    sp.add_argument("--end", required=True, help="窗口最后一天（含）")
    sp.add_argument("--budget", type=float, default=None,
                    help="周额度安全日数（缺省 %.1f）" % WEEK_BUDGET_SD)
    sp.set_defaults(func=cmd_week)

    sp = sub.add_parser("plan", help="把计划事件对所在周余量过闸")
    sp.add_argument("ledger")
    sp.add_argument("source")
    sp.add_argument("duration")
    sp.add_argument("--db", type=float, default=None, help="覆盖声源缺省 dB")
    sp.add_argument("--plug", type=float, default=PLUG_DEFAULT_NRR,
                    help="耳塞 NRR（0 关闭耳塞对比；缺省 NRR%s）" % PLUG_DEFAULT_NRR)
    sp.add_argument("--week-of", required=True, help="计划落在的某一天")
    sp.add_argument("--budget", type=float, default=None, help="周额度覆盖")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("lifetime", help="终身账（只增不减）")
    sp.add_argument("ledger")
    sp.set_defaults(func=cmd_lifetime)

    sp = sub.add_parser("sources", help="声源缺省表")
    sp.set_defaults(func=cmd_sources)

    sp = sub.add_parser("validate", help="账本体检")
    sp.add_argument("ledger")
    sp.set_defaults(func=cmd_validate)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except (UsageError, Refusal) as exc:
        print(str(exc), file=sys.stderr)
        return 3 if isinstance(exc, Refusal) else 2


if __name__ == "__main__":
    sys.exit(main())
