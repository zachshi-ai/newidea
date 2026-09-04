#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timezone-tax · 时区税 —— 把跨时区会议的代价变成一本账.

问题：分布式团队的例会时间由日历工具决定，它们只优化「重叠最大」，
从不回答「代价由谁承担」。于是同一个时区长期在 23:00 开会，
不公平是累积的、隐形的，也没有任何账本可以拿来讨论轮换。

timezone-tax 把每次会议按成员本地挂钟折算成税点：
  黄金时段 09:00–17:59 = 0    傍晚 18:00–21:59 = 1
  清晨 07:00–08:59 = 1.5      深夜 22:00–06:59 = 3
再累积成税负账本，算缴税基尼，并在可行槽里做补偿式轮换——
如果候选槽里不存在能改变缴税人的格子，就诚实判定「结构性失衡」。

  inspect   一次会议的税单：谁在几点、落在哪条税带、缴多少
  plan      未来 N 周的轮换计划（补偿式选择 + DST 自适应）
  simulate  固定 UTC 时间 × N 周的公平性推演（夏令时漂移可见）
  record    把一次真实会议的税单写入账本
  report    账本汇总：累计税负 / 缴税基尼 / 最惨比率 / 失衡告警
  validate  团队与账本文件体检

零依赖：Python 3.8+ 标准库。夏令时由配置驱动（MM-DD 年度规则或
YYYY-MM-DD 绝对规则），不读系统时区表——换谁跑结果都一样。

用法：
  python3 timezone_tax.py inspect examples/team-global.json --utc 2026-09-10T15:00
  python3 timezone_tax.py plan examples/team-global.json --start 2026-09-07 --weeks 12
  python3 timezone_tax.py simulate examples/team-global.json --utc 15:00 --start 2026-09-07 --weeks 52
  python3 timezone_tax.py record examples/ledger-halfyear.json examples/team-global.json --utc 2026-09-14T15:00 --note "周会"
  python3 timezone_tax.py report examples/ledger-halfyear.json --team examples/team-global.json
  python3 timezone_tax.py validate examples/team-global.json examples/ledger-halfyear.json
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------------------
# 常量与税带

WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

BAND_ZH = {
    "prime": "黄金",
    "early": "清晨",
    "evening": "傍晚",
    "night": "深夜",
}

# 默认税率（税点）。深夜重罚的依据见 METHODOLOGY.md：睡眠剥夺不可妥协，
# 清早次之，傍晚只是打扰，黄金时段免费。
DEFAULT_WEIGHTS = {"prime": 0.0, "early": 1.5, "evening": 1.0, "night": 3.0}

DEFAULT_WAKING = ("07:00", "24:00")
DEFAULT_WORKDAYS = [0, 1, 2, 3, 4]
DEFAULT_GRID_MIN = 30

# 公平告警阈值：缴税基尼与最惨比率（max/min）
GINI_WARN = 0.3
GINI_ALARM = 0.5
RATIO_WARN = 2.0
RATIO_ALARM = 4.0

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ALARM = 3


class TaxError(Exception):
    """配置 / 账本 / 参数错误。message 面向用户，一次报全。"""


# ---------------------------------------------------------------------------
# 时间原语


def parse_hhmm(text, allow_24=False):
    """'HH:MM' -> 当日分钟数。allow_24 时接受 24:00（=1440，排他上界）。"""
    parts = str(text).split(":")
    if len(parts) != 2:
        raise TaxError("时间 %r 应为 HH:MM" % text)
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise TaxError("时间 %r 不是数字" % text)
    limit = 24 if allow_24 else 23
    if not (0 <= hour <= limit and 0 <= minute < 60):
        raise TaxError("时间 %r 越界" % text)
    if hour == 24 and minute != 0:
        raise TaxError("时间 %r：24:00 只能整点" % text)
    return hour * 60 + minute


def parse_utc_datetime(text):
    """'YYYY-MM-DDTHH:MM' 或 'YYYY-MM-DD HH:MM'（UTC）-> naive datetime。"""
    cleaned = str(text).strip().replace(" ", "T")
    try:
        return datetime.strptime(cleaned, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise TaxError("UTC 时间 %r 应为 YYYY-MM-DDTHH:MM" % text)


def parse_rule_date(text):
    """夏令时规则端点：'MM-DD' 年度循环 或 'YYYY-MM-DD' 绝对日期。"""
    parts = str(text).split("-")
    try:
        if len(parts) == 2:
            month, day = int(parts[0]), int(parts[1])
            if not (1 <= month <= 12 and 1 <= day <= 31):
                raise ValueError
            return ("yearly", (month, day))
        if len(parts) == 3:
            return ("fixed", date(int(parts[0]), int(parts[1]), int(parts[2])))
    except ValueError:
        raise TaxError("夏令时日期 %r 应为 MM-DD 或 YYYY-MM-DD" % text)
    raise TaxError("夏令时日期 %r 应为 MM-DD 或 YYYY-MM-DD" % text)


def _rule_key(parsed, year):
    """MM-DD 端点折算成某年的 day-of-year（2/29 自动收敛到月末）。"""
    month, day = parsed[1]
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last)).timetuple().tm_yday


def rule_applies(day, rule):
    """区间语义：from <= day < to。
    两端同为 MM-DD：按 day 所在年度展开，from > to 视为跨年环绕（南半球）；
    两端同为 YYYY-MM-DD：按绝对日期比较。混用两种写法是配置错误。"""
    frm = parse_rule_date(rule["from"])
    to = parse_rule_date(rule["to"])
    if frm[0] == "fixed":
        if to[0] != "fixed":
            raise TaxError("dst 规则 from/to 需同为 MM-DD 或同为 YYYY-MM-DD")
        return frm[1] <= day < to[1]
    if to[0] != "yearly":
        raise TaxError("dst 规则 from/to 需同为 MM-DD 或同为 YYYY-MM-DD")
    a = _rule_key(frm, day.year)
    b = _rule_key(to, day.year)
    k = day.timetuple().tm_yday
    if a <= b:
        return a <= k < b
    return k >= a or k < b


def effective_offset_min(member, on_date):
    """成员在 on_date 的有效偏移：标准偏移，落在任一 DST 规则区间则取规则偏移。"""
    offset = member["offset_min"]
    for rule in member.get("dst", []):
        if rule_applies(on_date, rule):
            return rule["offset_min"]
    return offset


def utc_to_local(utc_dt, member):
    """UTC naive datetime -> (本地 date, 本地分钟数)。DST 查表先用 UTC 日期，
    若换用本地日期后偏移变化，再做一次修正（收敛即停）。"""
    offset = effective_offset_min(member, utc_dt.date())
    total = utc_dt.hour * 60 + utc_dt.minute + offset
    shift = total // 1440
    local_date = utc_dt.date() + timedelta(days=shift)
    local_min = total - shift * 1440
    refined = effective_offset_min(member, local_date)
    if refined != offset:
        total = utc_dt.hour * 60 + utc_dt.minute + refined
        shift = total // 1440
        local_date = utc_dt.date() + timedelta(days=shift)
        local_min = total - shift * 1440
    return local_date, local_min


def fmt_local(local_date, local_min):
    return "%s %02d:%02d" % (WEEKDAY_ZH[local_date.weekday()],
                             local_min // 60, local_min % 60)


def fmt_tax(x):
    return ("%.2f" % x).rstrip("0").rstrip(".") or "0"


# ---------------------------------------------------------------------------
# 团队模型


def load_json(path, what):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise TaxError("读不了%s文件 %s：%s" % (what, path, exc))
    except ValueError as exc:
        raise TaxError("%s文件 %s 不是合法 JSON：%s" % (what, path, exc))


def load_team(path):
    team = load_json(path, "团队配置")
    validate_team(team, source=path)
    return team


def _validate_dst_rules(member_name, rules, problems):
    if not isinstance(rules, list):
        problems.append("成员 %s 的 dst 应为列表" % member_name)
        return
    for rule in rules:
        if not isinstance(rule, dict) or \
           not {"from", "to", "offset_min"} <= set(rule):
            problems.append("成员 %s 的 dst 规则需含 from/to/offset_min" % member_name)
            continue
        try:
            frm = parse_rule_date(rule["from"])
            to = parse_rule_date(rule["to"])
        except TaxError as exc:
            problems.append("成员 %s：%s" % (member_name, exc))
            continue
        if frm[0] != to[0]:
            problems.append("成员 %s 的 dst 规则 from/to 需同为 MM-DD "
                            "或同为 YYYY-MM-DD" % member_name)
        elif frm == to:
            problems.append("成员 %s 的 dst 规则 from 与 to 相同" % member_name)
        if not isinstance(rule["offset_min"], int):
            problems.append("成员 %s 的 dst offset_min 应为整数分钟" % member_name)


def validate_team(team, source="team"):
    problems = []
    if not isinstance(team, dict):
        raise TaxError("%s：顶层应为 JSON 对象" % source)
    members = team.get("members")
    if not isinstance(members, list) or not members:
        problems.append("%s：members 必须是非空列表" % source)
        members = []
    names = set()
    for member in members:
        if not isinstance(member, dict) or "name" not in member or \
           "offset_min" not in member:
            problems.append("%s：每个成员需含 name 与 offset_min" % source)
            continue
        name = member["name"]
        if name in names:
            problems.append("%s：成员名重复：%s" % (source, name))
        names.add(name)
        offset = member["offset_min"]
        if not isinstance(offset, int) or not -14 * 60 <= offset <= 14 * 60:
            problems.append("%s：成员 %s 的 offset_min 应为 ±14h 内的整数" % (source, name))
        if "dst" in member:
            _validate_dst_rules(name, member["dst"], problems)
    weights = team.get("weights", {})
    if not isinstance(weights, dict):
        problems.append("%s：weights 应为对象" % source)
        weights = {}
    for band in BAND_ZH:
        value = weights.get(band, DEFAULT_WEIGHTS[band])
        if not isinstance(value, (int, float)) or value < 0:
            problems.append("%s：weights.%s 应为非负数字" % (source, band))
    waking = team.get("waking", {})
    if not isinstance(waking, dict):
        problems.append("%s：waking 应为对象" % source)
        waking = {}
    start = parse_hhmm(waking.get("start", DEFAULT_WAKING[0]))
    end = parse_hhmm(waking.get("end", DEFAULT_WAKING[1]), allow_24=True)
    if start >= end:
        problems.append("%s：waking.start 必须早于 waking.end" % source)
    workdays = team.get("workdays", DEFAULT_WORKDAYS)
    if (not isinstance(workdays, list) or
            any(not isinstance(d, int) or not 0 <= d <= 6 for d in workdays)):
        problems.append("%s：workdays 应为 0–6 的整数列表（0=周一）" % source)
    grid = team.get("grid_min", DEFAULT_GRID_MIN)
    if not isinstance(grid, int) or not 1 <= grid <= 1440:
        problems.append("%s：grid_min 应为 1–1440 的整数分钟" % source)
    if problems:
        raise TaxError("\n".join(problems))


def team_weights(team):
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(team.get("weights", {}))
    return weights


def team_waking(team):
    waking = team.get("waking", {})
    start = parse_hhmm(waking.get("start", DEFAULT_WAKING[0]))
    end = parse_hhmm(waking.get("end", DEFAULT_WAKING[1]), allow_24=True)
    return start, end


def team_grid(team):
    return team.get("grid_min", DEFAULT_GRID_MIN)


# ---------------------------------------------------------------------------
# 税带与税单


def classify_band(local_min, weights):
    """本地分钟 -> (税带名, 税点)。区间：黄金 [09:00,18:00)、傍晚 [18:00,22:00)、
    清晨 [07:00,09:00)、深夜其余。"""
    if 540 <= local_min < 1080:
        return "prime", weights["prime"]
    if 1080 <= local_min < 1320:
        return "evening", weights["evening"]
    if 420 <= local_min < 540:
        return "early", weights["early"]
    return "night", weights["night"]


def bill_at_utc(team, utc_dt):
    """一次会议的税单。返回：
    {utc, rows: [{name, local, band, tax, feasible, reason}], total,
     max_payer, feasible}
    成员不可行（睡梦中或非工作日）时照常计税并给出原因，feasible=False。
    """
    weights = team_weights(team)
    wake_start, wake_end = team_waking(team)
    workdays = set(team.get("workdays", DEFAULT_WORKDAYS))
    rows = []
    for member in team["members"]:
        local_date, local_min = utc_to_local(utc_dt, member)
        band, tax = classify_band(local_min, weights)
        feasible, reason = True, ""
        if local_date.weekday() not in workdays:
            feasible, reason = False, "非工作日"
        elif not wake_start <= local_min < wake_end:
            feasible, reason = False, "睡眠时段"
        rows.append({
            "name": member["name"],
            "local": fmt_local(local_date, local_min),
            "band": band,
            "tax": tax,
            "feasible": feasible,
            "reason": reason,
        })
    total = sum(row["tax"] for row in rows)
    max_payer = None
    if rows:
        max_payer = max(rows, key=lambda row: (row["tax"],))["name"] \
            if any(row["tax"] > 0 for row in rows) else None
    return {
        "utc": utc_dt.strftime("%Y-%m-%d %H:%M"),
        "rows": rows,
        "total": total,
        "max_payer": max_payer,
        "feasible": all(row["feasible"] for row in rows),
    }


def bill_bills(bill):
    """税单 -> {成员名: 税点}，成员顺序保持团队配置顺序。"""
    return dict((row["name"], row["tax"]) for row in bill["rows"])


def payer_signature(bill):
    """缴税人集合（税点 > 0 的成员），判断轮换有没有改变缴税人。"""
    return frozenset(row["name"] for row in bill["rows"] if row["tax"] > 0)


# ---------------------------------------------------------------------------
# 公平度量


def gini(values):
    """基尼系数 = Σ|xi−xj| / (2·n²·mean)。全零 / 单人 / 空 -> 0。"""
    xs = [float(v) for v in values]
    n = len(xs)
    if n < 2:
        return 0.0
    mean = sum(xs) / n
    if mean <= 0:
        return 0.0
    total_diff = sum(abs(a - b) for a in xs for b in xs)
    return total_diff / (2.0 * n * n * mean)


def burden_ratio(values):
    """最惨比率 = max/min。min 为 0 且 max > 0 -> None（视为无穷）。"""
    xs = [float(v) for v in values]
    if not xs:
        return 1.0
    lo, hi = min(xs), max(xs)
    if hi <= 0:
        return 1.0
    if lo <= 0:
        return None
    return hi / lo


def fairness_verdict(totals, gini_warn=GINI_WARN, gini_alarm=GINI_ALARM,
                     ratio_warn=RATIO_WARN, ratio_alarm=RATIO_ALARM):
    """累计税负 -> (level: ok|warn|alarm, 理由列表)。"""
    values = list(totals.values())
    if len(values) < 2:
        return "ok", ["成员不足 2 人，谈公平还太早"]
    if max(values) <= 0:
        return "ok", ["全员零税：没有人在夜里或凌晨为这个会买单"]
    level, reasons = "ok", []
    g = gini(values)
    ratio = burden_ratio(values)
    never = [name for name, v in totals.items() if v <= 0]
    if g >= gini_alarm:
        level = "alarm"
        reasons.append("缴税基尼 %.2f ≥ 警戒线 %.2f：税负高度集中" % (g, gini_alarm))
    elif g > gini_warn:
        level = max(level, "warn")
        reasons.append("缴税基尼 %.2f > 预警线 %.2f：税负偏斜" % (g, gini_warn))
    if ratio is None:
        level = "alarm"
        reasons.append("最惨比率为无穷：%s 从未缴税，而有人每周在付"
                       % "、".join(never))
    elif ratio >= ratio_alarm:
        level = "alarm"
        reasons.append("最惨比率 %.1f ≥ %.1f：最惨成员的税负是最闲成员的数倍"
                       % (ratio, ratio_alarm))
    elif ratio > ratio_warn:
        level = max(level, "warn")
        reasons.append("最惨比率 %.1f > %.1f：分摊开始偏斜" % (ratio, ratio_warn))
    if not reasons:
        reasons.append("税负分摊看起来健康：基尼 %.2f，最惨比率 %.1f"
                       % (g, ratio))
    return level, reasons


# ---------------------------------------------------------------------------
# 账本


def empty_ledger():
    return {"meetings": []}


def validate_ledger(ledger, source="ledger"):
    problems = []
    if not isinstance(ledger, dict) or not isinstance(ledger.get("meetings"), list):
        raise TaxError("%s：顶层应含 meetings 列表" % source)
    for i, meeting in enumerate(ledger["meetings"], 1):
        if not isinstance(meeting, dict) or "utc" not in meeting or \
           not isinstance(meeting.get("bills"), dict):
            problems.append("%s：第 %d 条会议需含 utc 与 bills 对象" % (source, i))
            continue
        try:
            parse_utc_datetime(meeting["utc"])
        except TaxError as exc:
            problems.append("%s：第 %d 条会议 %s" % (source, i, exc))
            continue
        for name, tax in meeting["bills"].items():
            if not isinstance(tax, (int, float)):
                problems.append("%s：第 %d 条会议 %s 的税点应为数字" % (source, i, name))
    if problems:
        raise TaxError("\n".join(problems))


def load_ledger(path):
    ledger = load_json(path, "账本")
    validate_ledger(ledger, source=path)
    return ledger


def append_meeting(ledger, utc_dt, bills, note=""):
    ledger["meetings"].append({
        "utc": utc_dt.strftime("%Y-%m-%dT%H:%M"),
        "note": note,
        "bills": dict((name, tax) for name, tax in bills.items()),
    })
    return ledger


def summarize_ledger(ledger, team=None):
    """账本 -> {成员名: 累计税点}。给 team 时，没出现过账本的成员补 0。"""
    totals = {}
    for meeting in ledger["meetings"]:
        for name, tax in meeting["bills"].items():
            totals[name] = totals.get(name, 0.0) + tax
    if team:
        for member in team["members"]:
            totals.setdefault(member["name"], 0.0)
    return totals


# ---------------------------------------------------------------------------
# 候选槽枚举与轮换


def feasible_slots(team, utc_day):
    """枚举 utc_day 当天所有可行槽（全员醒着且为工作日）。
    返回 [(utc 分钟, 税单)]，按 UTC 分钟升序。"""
    grid = team_grid(team)
    slots = []
    for minute in range(0, 1440, grid):
        utc_dt = datetime(utc_day.year, utc_day.month, utc_day.day) \
            + timedelta(minutes=minute)
        bill = bill_at_utc(team, utc_dt)
        if bill["feasible"]:
            slots.append((minute, bill))
    return slots


def choose_slot(team, cum, utc_day, slots=None):
    """补偿式选择：在可行槽里选「选完之后累计税负的最大值最小」的一格，
    并列比总税，再并列取 UTC 更早——完全确定性。
    slots 可注入预计算的 [(utc 分钟, 税单)]（测试与复用）；无可行槽返回 None。"""
    if slots is None:
        slots = feasible_slots(team, utc_day)
    best_key, best = None, None
    for minute, bill in slots:
        after = dict((name, cum.get(name, 0.0) + tax)
                     for name, tax in bill_bills(bill).items())
        key = (round(max(after.values()), 6),
               round(sum(after.values()), 6),
               minute)
        if best_key is None or key < best_key:
            best_key, best = key, bill
    return best


def plan_rotation(team, start_date, weeks):
    """未来 N 周轮换计划。返回：
    {entries: [{week, utc_day, bill}], cum, structural, signatures, infeasible_weeks}
    structural=True 表示所有可行周的缴税人集合完全相同——轮换无法改变谁缴税。
    """
    weekday = start_date.weekday()
    entries, infeasible_weeks = [], []
    signatures = set()
    cum = dict((m["name"], 0.0) for m in team["members"])
    for week in range(weeks):
        utc_day = start_date + timedelta(days=7 * week)
        bill = choose_slot(team, cum, utc_day)
        if bill is None:
            infeasible_weeks.append(week + 1)
            continue
        entries.append({"week": week + 1, "utc_day": utc_day, "bill": bill})
        signatures.add(payer_signature(bill))
        for name, tax in bill_bills(bill).items():
            cum[name] = cum.get(name, 0.0) + tax
    structural = len(entries) >= 2 and len(signatures) == 1
    return {
        "entries": entries,
        "cum": cum,
        "structural": structural,
        "signatures": signatures,
        "infeasible_weeks": infeasible_weeks,
    }


def simulate_fixed(team, utc_minute, start_date, weeks):
    """固定 UTC 时间 × N 周：返回每周税单与累计，夏令时漂移一目了然。"""
    hour, minute = divmod(utc_minute, 60)
    entries, cum = [], dict((m["name"], 0.0) for m in team["members"])
    infeasible_weeks = []
    for week in range(weeks):
        utc_day = start_date + timedelta(days=7 * week)
        utc_dt = datetime(utc_day.year, utc_day.month, utc_day.day,
                          hour, minute)
        bill = bill_at_utc(team, utc_dt)
        entries.append({"week": week + 1, "utc_day": utc_day, "bill": bill})
        if not bill["feasible"]:
            infeasible_weeks.append(week + 1)
        for name, tax in bill_bills(bill).items():
            cum[name] = cum.get(name, 0.0) + tax
    return {"entries": entries, "cum": cum, "infeasible_weeks": infeasible_weeks}


# ---------------------------------------------------------------------------
# 输出渲染


def _pad(text, width):
    visible = sum(2 if ord(ch) > 127 else 1 for ch in text)
    return text + " " * max(1, width - visible)


def render_bill(bill, title=None):
    lines = []
    if title:
        lines.append(title)
    lines.append("  %s%s%s%s" % (_pad("成员", 20), _pad("本地时刻", 14),
                                 _pad("税带", 8), "税点"))
    for row in bill["rows"]:
        flag = "" if row["feasible"] else "（%s，不可行）" % row["reason"]
        lines.append("  %s%s%s%s%s" % (
            _pad(row["name"], 20), _pad(row["local"], 14),
            _pad(BAND_ZH[row["band"]], 8), fmt_tax(row["tax"]), flag))
    lines.append("  合计 %s 税点 · 最惨成员：%s" % (
        fmt_tax(bill["total"]),
        bill["max_payer"] or "无人（零税槽）"))
    return "\n".join(lines)


def render_verdict(level, reasons):
    badge = {"ok": "健康", "warn": "预警", "alarm": "警报"}[level]
    lines = ["【判定】%s" % badge]
    for reason in reasons:
        lines.append("  · %s" % reason)
    return "\n".join(lines)


def _member_local_segments(entries, name):
    """把成员在 N 周里的本地时刻压缩成连续段：[(local串, 起周, 止周)]。"""
    segments = []
    for entry in entries:
        row = next(r for r in entry["bill"]["rows"] if r["name"] == name)
        local = row["local"].split(" ", 1)[1]
        if segments and segments[-1][0] == local:
            segments[-1][2] = entry["week"]
        else:
            segments.append([local, entry["week"], entry["week"]])
    return segments


def render_segments(segments):
    parts = []
    for local, first, last in segments:
        if first == last:
            parts.append("%s（第%d周）" % (local, first))
        else:
            parts.append("%s（第%d–%d周）" % (local, first, last))
    return " → ".join(parts)


# ---------------------------------------------------------------------------
# 子命令实现


def cmd_inspect(args):
    team = load_team(args.team)
    utc_dt = parse_utc_datetime(args.utc)
    bill = bill_at_utc(team, utc_dt)
    print("【税单】%s UTC · %s" % (bill["utc"], team.get("name", "")))
    print(render_bill(bill))
    if not bill["feasible"]:
        print("  ⚠ 该时刻有成员不可行（睡眠时段/非工作日），不适合开会")
    return EXIT_OK


def cmd_plan(args):
    team = load_team(args.team)
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    result = plan_rotation(team, start, args.weeks)
    print("【轮换计划】%s · %s 起共 %d 周 · 会议日=每周%s（UTC 视角）"
          % (team.get("name", ""), args.start, args.weeks,
             WEEKDAY_ZH[start.weekday()]))
    for entry in result["entries"]:
        bill = entry["bill"]
        payers = " / ".join(
            "%s %s" % (row["name"], fmt_tax(row["tax"]))
            for row in bill["rows"] if row["tax"] > 0) or "无人"
        print("  第%2d 周 %s · %02d:%02d UTC · 税单 %s · 缴税：%s"
              % (entry["week"], bill["utc"][:10],
                 int(bill["utc"][11:13]), int(bill["utc"][14:16]),
                 fmt_tax(bill["total"]), payers))
    for week in result["infeasible_weeks"]:
        print("  第%2d 周：无解——没有任何时刻让全员都醒着且在工作日" % week)
    print()
    cum = result["cum"]
    ranked = sorted(cum.items(), key=lambda kv: (-kv[1], kv[0]))
    print("【计划期末税负】%s" % " · ".join(
        "%s %s" % (name, fmt_tax(tax)) for name, tax in ranked))
    print(render_verdict(*plan_verdict(result, team)))
    if args.save:
        ledger = empty_ledger()
        for entry in result["entries"]:
            append_meeting(ledger,
                           parse_utc_datetime(entry["bill"]["utc"]
                                              .replace(" ", "T")),
                           bill_bills(entry["bill"]))
        with open(args.save, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("  计划账本已写入 %s" % args.save)
    return EXIT_OK


def plan_verdict(result, team):
    if result["infeasible_weeks"]:
        return "alarm", [
            "有 %d 周无解：这批人之间不存在全员醒着的工作日时刻。" % len(result["infeasible_weeks"]),
            "这不是排会问题，是组织分布问题——拆会 / 降频 / 异步化，三选一。",
        ]
    if not result["entries"]:
        return "warn", ["没有可行周，无从谈公平"]
    if result["structural"]:
        payers = sorted(next(iter(result["signatures"])))
        taxed = [p for p in payers if result["cum"].get(p, 0) > 0]
        if not taxed:
            return "ok", ["每周都选中零税槽：这个会对所有人都免费，定死即可"]
        return "alarm", [
            "结构性失衡：%s 周周缴税，且候选槽里不存在能改变缴税人的格子——"
            "轮换无效，这是结构性税负。" % "、".join(taxed),
            "日历工具没告诉你的真相：重叠最大的一格 ≠ 代价为零的一格。",
            "出路不在排会，在组织：拆会 / 降频 / 异步化。",
        ]
    return "ok", ["轮换生效：%d 周里缴税人发生过变化，税负被摊开了"
                  % len(result["entries"])]


def cmd_simulate(args):
    team = load_team(args.team)
    utc_minute = parse_hhmm(args.utc)
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    result = simulate_fixed(team, utc_minute, start, args.weeks)
    end_day = start + timedelta(days=7 * (args.weeks - 1))
    print("【固定槽模拟】每周%s %s UTC × %d 周（%s → %s）· %s"
          % (WEEKDAY_ZH[start.weekday()], args.utc, args.weeks,
             start, end_day, team.get("name", "")))
    if result["infeasible_weeks"]:
        print("  ⚠ %d 周不可行（夏令时把某成员推进睡眠时段）：%s"
              % (len(result["infeasible_weeks"]),
                 "、".join("第%d周" % w for w in result["infeasible_weeks"][:8])
                 + ("…" if len(result["infeasible_weeks"]) > 8 else "")))
    print()
    for member in team["members"]:
        segments = _member_local_segments(result["entries"], member["name"])
        total = result["cum"].get(member["name"], 0.0)
        weeks_paid = sum(1 for entry in result["entries"]
                         if bill_bills(entry["bill"]).get(member["name"], 0) > 0)
        print("  %s  %s · 缴 %s（%d/%d 周在缴）"
              % (_pad(member["name"], 20),
                 render_segments(segments), fmt_tax(total),
                 weeks_paid, len(result["entries"])))
    print()
    ranked = sorted(result["cum"].items(), key=lambda kv: (-kv[1], kv[0]))
    values = list(result["cum"].values())
    g = gini(values)
    ratio = burden_ratio(values)
    print("【累计税负】%s" % " · ".join(
        "%s %s" % (name, fmt_tax(tax)) for name, tax in ranked))
    print("  缴税基尼 %.2f · 最惨比率 %s"
          % (g, "∞" if ratio is None else "%.1f" % ratio))
    print(render_verdict(*fairness_verdict(result["cum"], 
                                           args.gini_warn, args.gini_alarm,
                                           args.ratio_warn, args.ratio_alarm)))
    return EXIT_OK


def cmd_record(args):
    team = load_team(args.team)
    ledger = load_ledger(args.ledger) if not args.init else empty_ledger()
    utc_dt = parse_utc_datetime(args.utc)
    bill = bill_at_utc(team, utc_dt)
    append_meeting(ledger, utc_dt, bill_bills(bill), note=args.note or "")
    with open(args.ledger, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("【记账】%s UTC · %s" % (bill["utc"], args.note or "（无备注）"))
    print(render_bill(bill))
    print("  已写入 %s（现共 %d 条会议）" % (args.ledger, len(ledger["meetings"])))
    return EXIT_OK


def cmd_report(args):
    ledger = load_ledger(args.ledger)
    team = load_team(args.team) if args.team else None
    totals = summarize_ledger(ledger, team=team)
    print("【税负账本】%s · %d 条会议" % (args.ledger, len(ledger["meetings"])))
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    grand = sum(totals.values())
    for name, tax in ranked:
        share = (tax / grand * 100.0) if grand > 0 else 0.0
        print("  %s  累计 %s 税点（占 %.0f%%）"
              % (_pad(name, 20), fmt_tax(tax), share))
    print()
    g = gini(list(totals.values()))
    ratio = burden_ratio(list(totals.values()))
    print("  缴税基尼 %.2f · 最惨比率 %s"
          % (g, "∞" if ratio is None else "%.1f" % ratio))
    level, reasons = fairness_verdict(totals, args.gini_warn, args.gini_alarm,
                                      args.ratio_warn, args.ratio_alarm)
    print(render_verdict(level, reasons))
    return EXIT_ALARM if level == "alarm" else EXIT_OK


def cmd_validate(args):
    problems = []
    for path in args.paths:
        data = load_json(path, "文件")
        if isinstance(data, dict) and "meetings" in data:
            try:
                validate_ledger(data, source=path)
                meetings = len(data["meetings"])
                print("  ✓ %s：账本合法（%d 条会议）" % (path, meetings))
            except TaxError as exc:
                problems.append(str(exc))
        else:
            try:
                validate_team(data, source=path)
                print("  ✓ %s：团队配置合法（%d 名成员）"
                      % (path, len(data.get("members", []))))
            except TaxError as exc:
                problems.append(str(exc))
    if problems:
        print("【体检】发现问题", file=sys.stderr)
        for problem in problems:
            print("  ✗ %s" % problem, file=sys.stderr)
        return EXIT_ERROR
    print("【体检】全部通过")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI


def build_parser():
    parser = argparse.ArgumentParser(
        prog="timezone_tax.py",
        description="时区税 · Timezone Tax —— 把跨时区会议的代价变成一本账")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("inspect", help="一次会议的税单：谁在几点、缴多少")
    p.add_argument("team")
    p.add_argument("--utc", required=True, help="会议开始时刻（UTC，YYYY-MM-DDTHH:MM）")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("plan", help="未来 N 周的补偿式轮换计划")
    p.add_argument("team")
    p.add_argument("--start", required=True, help="第一周日期（YYYY-MM-DD）")
    p.add_argument("--weeks", type=int, default=8, help="计划周数（默认 8）")
    p.add_argument("--save", help="把计划写成账本 JSON，供 report 消费")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("simulate", help="固定 UTC 时间 × N 周的公平性推演")
    p.add_argument("team")
    p.add_argument("--utc", required=True, help="固定的 UTC 时刻（HH:MM）")
    p.add_argument("--start", required=True, help="第一周日期（YYYY-MM-DD）")
    p.add_argument("--weeks", type=int, default=52, help="推演周数（默认 52）")
    p.add_argument("--gini-warn", type=float, default=GINI_WARN)
    p.add_argument("--gini-alarm", type=float, default=GINI_ALARM)
    p.add_argument("--ratio-warn", type=float, default=RATIO_WARN)
    p.add_argument("--ratio-alarm", type=float, default=RATIO_ALARM)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("record", help="把一次真实会议的税单写入账本")
    p.add_argument("ledger")
    p.add_argument("team")
    p.add_argument("--utc", required=True, help="会议开始时刻（UTC）")
    p.add_argument("--note", default="", help="备注，例如会议名")
    p.add_argument("--init", action="store_true", help="忽略已有账本，从零开始")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("report", help="账本汇总与失衡告警（警报时退出码 3）")
    p.add_argument("ledger")
    p.add_argument("--team", help="团队配置：把从未缴税的成员也计入分母")
    p.add_argument("--gini-warn", type=float, default=GINI_WARN)
    p.add_argument("--gini-alarm", type=float, default=GINI_ALARM)
    p.add_argument("--ratio-warn", type=float, default=RATIO_WARN)
    p.add_argument("--ratio-alarm", type=float, default=RATIO_ALARM)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("validate", help="团队 / 账本文件体检")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_validate)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_ERROR
    try:
        return args.func(args)
    except TaxError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
