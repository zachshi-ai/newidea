#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""left-behind · 漏带时刻 —— 行李装箱的错题本.

问题：通用打包清单是「平均人」的清单——它不知道你总漏充电头，
也不知道那把伞陪你去过三个城市、淋过零场雨。漏带的懊恼和悔带的
重量从未被结构化记录，于是同一个错误以稳定的概率反复发生：
清单从不学习，全靠大脑硬扛。

left-behind 把每次行程记成「物品 × 行程」事件账本（TSV）：
  analyze   错题本报告：总览 / 盲区 / 品类分布 / 幽灵货物 / 补救账单 / 收敛趋势
  pack      生成下一张装箱清单：基线缩放 + 盲区置顶 + 常备物品 + 幽灵降级
  validate  账本格式体检

零依赖：Python 3.8+ 标准库。

用法：
  python3 left_behind.py analyze examples/realistic.tsv
  python3 left_behind.py pack examples/realistic.tsv --type business --days 3
  python3 left_behind.py validate examples/realistic.tsv
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import date

# ---------------------------------------------------------------------------
# 数据模型与常量

REQUIRED_COLUMNS = [
    "date", "trip_id", "trip_type", "days", "item", "category",
    "event", "cost", "weight_g", "notes",
]
EVENTS = ("left", "ghost", "used")

# 同一物品漏带 ≥2 次 → 盲区：漏一次是意外，漏两次是模式。详见 METHODOLOGY.md。
BLIND_SPOT_AT = 2
# 同一物品白扛 ≥2 次 → 清单降级「想清楚再带」：一次可能是天气意外，两次是系统性高估。
GHOST_DEMOTE_AT = 2
# 收敛趋势评估的最少行程数：趋势线至少要几个点才值得画。
CONVERGENCE_MIN_TRIPS = 4
# 「你的常备」入选线：该类型行程中出现 ≥2 次的「带了且用了」物品。
PACK_USED_MIN = 2
# 消耗品按天数缩放：装 days+1 份，封顶 10（长行程不必背一个月的内裤）。
SCALE_EXTRA = 1
SCALE_CAP = 10
# 基线模板：品类 → [(物品, 是否按天数缩放)]。它是「平均人」的清单——
# 个人修正（盲区/常备/幽灵）由账本在其上叠加，这正是本工具存在的理由。
BASE_LIST = [
    ("证件文档", [("身份证/护照", False), ("钱包/卡包", False), ("钥匙", False)]),
    ("电子设备", [("手机充电头", False), ("手机充电线", False), ("耳机", False),
                  ("笔记本电脑+电源", False), ("转换插头", False)]),
    ("洗漱护肤", [("牙刷", False), ("牙膏(旅行装)", False), ("洗面奶(旅行装)", False),
                  ("剃须刀", False), ("防晒", False)]),
    ("衣物", [("内裤", True), ("袜子", True), ("T恤/衬衫", True), ("外套", False)]),
    ("健康药品", [("常用药", False), ("创可贴", False)]),
    ("其他", [("水杯", False), ("雨伞", False)]),
]


class ParseError(Exception):
    """账本解析失败。message 汇总所有坏行，便于一次报全。"""


class Event(object):
    __slots__ = ["lineno", "date", "trip_id", "trip_type", "days",
                 "item", "category", "event", "cost", "weight_g", "notes"]

    def __init__(self, **kwargs):
        for key in self.__slots__:
            setattr(self, key, kwargs[key])


class Trip(object):
    """一次行程：共享 trip_id 的事件聚合 + 行程元数据。"""
    __slots__ = ["trip_id", "date", "trip_type", "days", "events"]

    def __init__(self, trip_id, date, trip_type, days, events):
        self.trip_id = trip_id
        self.date = date
        self.trip_type = trip_type
        self.days = days
        self.events = events

    @property
    def sort_key(self):
        return (self.date, self.trip_id)


# ---------------------------------------------------------------------------
# 解析

def _to_positive_int(value, lineno, column):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("第 %d 行 %s=%r 不是整数" % (lineno, column, value))
    if number < 1:
        raise ValueError("第 %d 行 %s=%s 必须 ≥1" % (lineno, column, value))
    return number


def _to_nonneg_float(value, lineno, column):
    """可空的非负数。空串返回 None（未记录）。"""
    if not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("第 %d 行 %s=%r 不是数字" % (lineno, column, value))
    if number < 0:
        raise ValueError("第 %d 行 %s=%s 不能为负" % (lineno, column, value))
    return number


def parse_events(text):
    """解析 TSV 文本为 Event 列表。坏行汇总后一次抛 ParseError。"""
    lines = text.splitlines()
    # 前导注释/空行之后的第一行才是表头
    start = 0
    while start < len(lines) and (
            not lines[start].strip() or lines[start].lstrip().startswith("#")):
        start += 1
    lines = lines[start:]
    if not lines:
        raise ParseError("账本为空")
    header = [c.strip() for c in lines[0].split("\t")]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ParseError("表头缺少列: %s" % ", ".join(missing))
    index = {c: i for i, c in enumerate(header)}

    events, errors = [], []
    for lineno, raw in enumerate(lines[1:], start=2):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cells = raw.split("\t")
        row = {c: (cells[index[c]].strip() if index[c] < len(cells) else "")
               for c in header}
        try:
            day = date.fromisoformat(row["date"])
        except ValueError:
            errors.append("第 %d 行 date=%r 不是合法日期（YYYY-MM-DD）"
                          % (lineno, row["date"]))
            continue
        if not row["trip_id"] or not row["item"] or not row["category"]:
            errors.append("第 %d 行: trip_id/item/category 不能为空" % lineno)
            continue
        if row["event"] not in EVENTS:
            errors.append("第 %d 行 event=%r 必须是 %s 之一"
                          % (lineno, row["event"], "/".join(EVENTS)))
            continue
        try:
            days = _to_positive_int(row["days"], lineno, "days")
            cost = _to_nonneg_float(row["cost"], lineno, "cost")
            weight = _to_nonneg_float(row["weight_g"], lineno, "weight_g")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        events.append(Event(
            lineno=lineno, date=day, trip_id=row["trip_id"],
            trip_type=row["trip_type"], days=days, item=row["item"],
            category=row["category"], event=row["event"], cost=cost,
            weight_g=weight, notes=row.get("notes", "")))

    if errors:
        raise ParseError("\n".join(errors))
    # 空账本（只有表头）在此合法：analyze 会拒绝它，pack 要靠它出第一张基线清单
    errors = _check_trip_consistency(events)
    if errors:
        raise ParseError("\n".join(errors))
    return events


def _check_trip_consistency(events):
    """同一 trip_id 的 date/trip_type/days 必须一致——行程是聚合键，
    元数据打架说明记串了账，宁拒收不猜。"""
    seen = {}
    errors = []
    for ev in events:
        meta = (ev.date, ev.trip_type, ev.days)
        if ev.trip_id in seen and seen[ev.trip_id] != meta:
            first = seen[ev.trip_id]
            errors.append(
                "第 %d 行 trip_id=%s 的行程元数据与之前不一致："
                "%s/%s/%d 天 vs %s/%s/%d 天（同一行程的 date/trip_type/days 必须一致）"
                % (ev.lineno, ev.trip_id, ev.date, ev.trip_type, ev.days,
                   first[0], first[1], first[2]))
        seen.setdefault(ev.trip_id, meta)
    return errors


def read_events(path):
    with open(path, encoding="utf-8") as fh:
        return parse_events(fh.read())


# ---------------------------------------------------------------------------
# 行程账本

def aggregate_trips(events):
    """按 trip_id 聚合为 Trip 列表，按出发日期排序（同日按 trip_id）。"""
    groups = defaultdict(list)
    for ev in events:
        groups[ev.trip_id].append(ev)
    trips = [Trip(tid, evs[0].date, evs[0].trip_type, evs[0].days, evs)
             for tid, evs in groups.items()]
    trips.sort(key=lambda t: t.sort_key)
    return trips


def select_trips(trips, trip_type=None):
    """限定画像域：--type 过滤；缺省用全部。"""
    if trip_type is None:
        return trips
    return [t for t in trips if t.trip_type == trip_type]


def blind_spots(events):
    """盲区：同一物品漏带 ≥ BLIND_SPOT_AT 次。

    返回 [(item, category, count, total_cost, last_date, last_trip_id)]，
    按（次数降序, 累计成本降序, 物品名）排序。
    """
    stats = {}
    for ev in events:
        if ev.event != "left":
            continue
        s = stats.setdefault(ev.item, {"category": ev.category, "count": 0,
                                       "cost": 0.0, "last_date": ev.date,
                                       "last_trip": ev.trip_id})
        s["count"] += 1
        if ev.cost is not None:
            s["cost"] += ev.cost
        if (ev.date, ev.trip_id) > (s["last_date"], s["last_trip"]):
            s["last_date"], s["last_trip"] = ev.date, ev.trip_id
    found = [(item, s["category"], s["count"], s["cost"],
              s["last_date"], s["last_trip"])
             for item, s in stats.items() if s["count"] >= BLIND_SPOT_AT]
    found.sort(key=lambda row: (-row[2], -row[3], row[0]))
    return found


def category_rank(events):
    """漏带按品类聚合：[(category, count, total_cost, unpriced)]，
    按（次数降序, 成本降序, 品类名）排序。"""
    stats = defaultdict(lambda: {"count": 0, "cost": 0.0, "unpriced": 0})
    for ev in events:
        if ev.event != "left":
            continue
        s = stats[ev.category]
        s["count"] += 1
        if ev.cost is None:
            s["unpriced"] += 1
        else:
            s["cost"] += ev.cost
    ranked = [(cat, s["count"], s["cost"], s["unpriced"])
              for cat, s in stats.items()]
    ranked.sort(key=lambda row: (-row[1], -row[2], row[0]))
    return ranked


def ghost_cargo(events):
    """幽灵货物：ghost 事件按物品聚合。

    返回 [(item, count, total_weight, unweighted)]，
    按（次数降序, 累计重量降序, 物品名）排序。
    """
    stats = defaultdict(lambda: {"count": 0, "weight": 0.0, "unweighted": 0})
    for ev in events:
        if ev.event != "ghost":
            continue
        s = stats[ev.item]
        s["count"] += 1
        if ev.weight_g is None:
            s["unweighted"] += 1
        else:
            s["weight"] += ev.weight_g
    ranked = [(item, s["count"], s["weight"], s["unweighted"])
              for item, s in stats.items()]
    ranked.sort(key=lambda row: (-row[1], -row[2], row[0]))
    return ranked


def salvage_bill(events):
    """补救账单：Σ left 事件成本。返回 (total, unpriced_count)。"""
    total, unpriced = 0.0, 0
    for ev in events:
        if ev.event != "left":
            continue
        if ev.cost is None:
            unpriced += 1
        else:
            total += ev.cost
    return total, unpriced


def convergence(trips):
    """收敛趋势：前半程 vs 后半程的漏带率（件/次）。

    行程按出发日期排序；奇数时中位行程不参与任何半程（诚实的中点处理）。
    行程数 < CONVERGENCE_MIN_TRIPS 时返回 None——拒绝画两点趋势线。

    返回 dict(before, after, before_n, after_n, direction)，
    direction ∈ improving / worsening / flat。
    """
    ordered = sorted(trips, key=lambda t: t.sort_key)
    n = len(ordered)
    if n < CONVERGENCE_MIN_TRIPS:
        return None
    half = n // 2
    lefts = [sum(1 for ev in t.events if ev.event == "left") for t in ordered]
    before_rate = sum(lefts[:half]) / half
    # 奇数时中位行程（index half）不参与任何半程
    after_rate = sum(lefts[n - half:]) / half
    if after_rate < before_rate:
        direction = "improving"
    elif after_rate > before_rate:
        direction = "worsening"
    else:
        direction = "flat"
    return {"before": before_rate, "after": after_rate,
            "before_n": half, "after_n": half, "direction": direction}


def profiles(events):
    """行程画像：按 trip_type 聚合行程数与三类事件数。"""
    stats = defaultdict(lambda: {"trips": set(), "left": 0, "ghost": 0, "used": 0})
    for ev in events:
        s = stats[ev.trip_type]
        s["trips"].add(ev.trip_id)
        s[ev.event] += 1
    return {t: {"trips": len(s["trips"]), "left": s["left"],
                "ghost": s["ghost"], "used": s["used"]}
            for t, s in stats.items()}


def staples(events, trip_type, min_count=PACK_USED_MIN):
    """「你的常备」：该类型行程中出现 ≥min_count 次的 used 物品。

    返回 [(item, count, total_trips)]，按（次数降序, 物品名）排序。
    used 记录是可选的画像数据——没记就没有常备区，工具会如实说明。
    """
    total_trips = sum(1 for t in {ev.trip_id for ev in events}
                      if _trip_type_of(events, t) == trip_type)
    counts = Counter(ev.item for ev in events
                     if ev.event == "used" and ev.trip_type == trip_type)
    found = [(item, count, total_trips) for item, count in counts.items()
             if count >= min_count]
    found.sort(key=lambda row: (-row[1], row[0]))
    return found


def _trip_type_of(events, trip_id):
    for ev in events:
        if ev.trip_id == trip_id:
            return ev.trip_type
    return None


# ---------------------------------------------------------------------------
# 清单生成：基线 → 盲区置顶 → 常备 → 幽灵降级

def baseline_quantity(scales, days):
    """消耗品按天数缩放：days + SCALE_EXTRA，封顶 SCALE_CAP；耐用品恒为 1。"""
    if not scales:
        return 1
    return min(SCALE_CAP, days + SCALE_EXTRA)


def default_trip_type(trips):
    """行程数最多的类型（并列取字典序最小）。空账本返回 None。"""
    counts = Counter(t.trip_type for t in trips)
    if not counts:
        return None
    return min(counts, key=lambda t: (-counts[t], t))


def default_days(trips, trip_type):
    """该类型历史行程的天数均值取整；无历史返回 None（调用方回退默认值）。"""
    relevant = [t.days for t in trips if t.trip_type == trip_type]
    if not relevant:
        return None
    return int(round(sum(relevant) / len(relevant)))


def build_pack(events, trips, trip_type=None, days=None, all_ghosts=False):
    """组装 pack 结果 dict。

    返回 dict(trip_type, days, days_source, has_data, warnings=[...],
              blindspots=[...], staples=[...], demoted=[...], baseline=True)
    """
    result = {"has_data": bool(trips)}
    warnings = []

    # 类型与天数：显式参数 > 账本证据 > 诚实回退
    if trip_type is None:
        trip_type = default_trip_type(trips)
        if trip_type is not None:
            warnings.append("未指定 --type：按行程数最多的类型 %s 生成" % trip_type)
        else:
            warnings.append("账本还是空的：以下是没有你的数据的「平均人」清单，"
                            "个人修正为零——从下次行程开始记错题本")
    result["trip_type"] = trip_type
    if days is None:
        if trip_type is None:  # 空账本
            days, result["days_source"] = 3, "默认（账本里还没有行程）"
        else:
            inferred = default_days(trips, trip_type)
            if inferred is None:
                days = 3
                result["days_source"] = "默认（账本里没有 %s 行程的历史）" % trip_type
            else:
                days = inferred
                result["days_source"] = "账本中 %s 行程的天数均值" % trip_type
    else:
        result["days_source"] = "命令行指定"
    result["days"] = days

    # 盲区置顶（全域统计——盲区是个人属性，不分行程类型）
    result["blindspots"] = blind_spots(events)

    # 常备：限定该类型历史
    result["staples"] = staples(events, trip_type)
    if not result["staples"] and trips:
        warnings.append("账本里没有 %s 类行程的 used 记录（used 是可选画像数据），"
                        "「你的常备」区为空" % trip_type)

    # 幽灵降级（全域统计）
    demoted = [(item, count, weight)
               for item, count, weight, _ in ghost_cargo(events)
               if count >= GHOST_DEMOTE_AT]
    result["demoted"] = [] if all_ghosts else demoted
    result["demoted_full"] = demoted
    return result


# ---------------------------------------------------------------------------
# 报告

def _fmt_money(amount):
    return "¥%g" % amount


def _fmt_kg(weight_g):
    if weight_g >= 1000:
        return "%.1f kg" % (weight_g / 1000.0)
    return "%g g" % weight_g


def build_report(events, trip_type=None):
    """组装 analyze 的文本报告。"""
    trips = select_trips(aggregate_trips(events), trip_type)
    lines = []
    lines.append("漏带时刻 · Left Behind 错题本报告")
    lines.append("=" * 46)
    if not trips:
        lines.append("没有类型为 %r 的行程。" % trip_type)
        return "\n".join(lines)
    note = "" if trip_type is None else "（仅限 %s 行程）" % trip_type
    types = Counter(t.trip_type for t in trips)
    type_text = "、".join("%s×%d" % kv for kv in sorted(types.items()))
    dates = sorted(t.date for t in trips)
    lines.append("数据：%d 次行程、%d 条事件（%s）%s"
                 % (len(trips), sum(len(t.events) for t in trips),
                    type_text, note))
    lines.append("日期：%s ~ %s" % (dates[0], dates[-1]))

    lines.append("")
    lines.append("【总览】你的错题本")
    left_n = sum(1 for ev in _domain_events(trips) if ev.event == "left")
    ghost_n = sum(1 for ev in _domain_events(trips) if ev.event == "ghost")
    total, unpriced = salvage_bill(_domain_events(trips))
    lines.append("漏带率 %.2f 件/次（%d 件）；幽灵率 %.2f 件/次（%d 件）"
                 % (left_n / len(trips), left_n, ghost_n / len(trips), ghost_n))
    ghost_weight = sum(ev.weight_g or 0 for ev in _domain_events(trips)
                       if ev.event == "ghost")
    if ghost_n:
        lines.append("幽灵货物累计白扛 %s" % _fmt_kg(ghost_weight))
    if left_n:
        bill_text = _fmt_money(total)
        if unpriced:
            bill_text += "（另 %d 件漏带未记价，不进账单但计入漏带数）" % unpriced
        lines.append("补救账单 %s" % bill_text)

    lines.append("")
    lines.append("【盲区】漏一次是意外，漏两次是模式")
    spots = blind_spots(_domain_events(trips))
    if not spots:
        lines.append("没有盲区——目前还没有物品漏到 2 次。保持记账。")
    for i, (item, cat, count, cost, last_date, last_trip) in enumerate(spots, 1):
        marker = "  ← 重犯" if i == 1 else ""
        lines.append("%2d. %s（%s）：漏带 %d 次，累计 %s%s"
                     % (i, item, cat, count, _fmt_money(cost) if cost else "—", marker))
        lines.append("    上次：%s（%s）" % (last_date, last_trip))

    lines.append("")
    lines.append("【品类分布】漏带重灾区")
    rank = category_rank(_domain_events(trips))
    if not rank:
        lines.append("没有漏带记录。")
    max_count = max((r[1] for r in rank), default=1)
    for cat, count, cost, unpriced in rank:
        bar = "█" * max(1, round(12 * count / max_count))
        suffix = "，%d 件未记价" % unpriced if unpriced else ""
        lines.append(" %-12s %s %d（%s%s）"
                     % (cat, bar, count,
                        _fmt_money(cost) if cost else "未记价", suffix))

    lines.append("")
    lines.append("【幽灵货物】原样往返的重量")
    cargo = ghost_cargo(_domain_events(trips))
    if not cargo:
        lines.append("没有白扛记录——要么你 Packing 极准，要么还没开始记。")
    unweighted_total = sum(row[3] for row in cargo)
    for item, count, weight, unweighted in cargo:
        note = ("，其中 %d 次未记重" % unweighted) if unweighted else ""
        lines.append("· %s：%d 次白扛（%s）%s"
                     % (item, count, _fmt_kg(weight), note))
    if unweighted_total:
        lines.append("（%d 条 ghost 事件没记 weight_g：不猜重量，只报次数）"
                     % unweighted_total)

    lines.append("")
    lines.append("【收敛】清单在迭代吗")
    conv = convergence(trips)
    if conv is None:
        lines.append("行程数不足 %d 次：拒绝评估趋势——两点不成趋势线，"
                     "先攒行程。" % CONVERGENCE_MIN_TRIPS)
    else:
        text = {"improving": "在改善——你的清单正在从错误里学习",
                "worsening": "不降反升：清单没有在迭代，下次装箱先读一遍盲区",
                "flat": "持平——稳定，但没有进步"}[conv["direction"]]
        lines.append("前 %d 次行程漏带率 %.2f 件/次 → 后 %d 次 %.2f 件/次：%s"
                     % (conv["before_n"], conv["before"],
                        conv["after_n"], conv["after"], text))

    lines.append("")
    lines.append("【行程画像】")
    for t, s in sorted(profiles(_domain_events(trips)).items(),
                       key=lambda kv: (-kv[1]["trips"], kv[0])):
        lines.append("· %s：%d 次行程，漏 %d 件 / 白扛 %d 件 / 用了 %d 件"
                     % (t, s["trips"], s["left"], s["ghost"], s["used"]))

    lines.append("")
    lines.append("【下一步】运行 python3 left_behind.py pack --type %s --days N 生成下次装箱清单"
                 % types.most_common(1)[0][0])
    return "\n".join(lines)


def _domain_events(trips):
    """限定域内的事件平铺（报告各节共用）。"""
    return [ev for t in trips for ev in t.events]


def build_pack_text(pack):
    """组装 pack 的文本输出。"""
    label = pack["trip_type"] if pack["trip_type"] else "首次出发"
    lines = []
    lines.append("装箱清单 · %s · %d 天" % (label, pack["days"]))
    lines.append("=" * 46)
    for warning in pack.get("warnings", []):
        lines.append("※ %s" % warning)
    if pack["has_data"]:
        lines.append("天数：%d（%s）" % (pack["days"], pack["days_source"]))

    lines.append("")
    lines.append("【先摸口袋】你的盲区——装箱前最后一次确认")
    if not pack["blindspots"]:
        lines.append("没有盲区。继续保持记账，漏一次就记一次。")
    for item, cat, count, cost, last_date, last_trip in pack["blindspots"]:
        lines.append("⚠ %s（%s）：已漏带 %d 次，上次 %s（%s）——现在就把它放进包里"
                     % (item, cat, count, last_date, last_trip))

    lines.append("")
    lines.append("【基线】平均人的清单（消耗品已按 %d 天缩放）" % pack["days"])
    for cat, items in BASE_LIST:
        rendered = []
        for item, scales in items:
            n = baseline_quantity(scales, pack["days"])
            rendered.append(item if n == 1 else "%s×%d" % (item, n))
        lines.append("· %s：%s" % (cat, "、".join(rendered)))

    lines.append("")
    lines.append("【你的常备】这些跟过你 %d 次以上（按 %s 行程的账本）"
                 % (PACK_USED_MIN, pack["trip_type"]))
    flagged = {row[0] for row in pack["blindspots"]}
    shown = 0
    for item, count, total in pack["staples"]:
        if item in flagged:
            continue  # 已在盲区置顶，不重复列
        lines.append("· %s（%d/%d 次）" % (item, count, total))
        shown += 1
    if not shown:
        lines.append("（暂无——used 记录攒到 %d 次的物品会出现在这里）" % PACK_USED_MIN)

    lines.append("")
    lines.append("【想清楚再带】反复白扛的重灾区（按你全部行程的账本）")
    if pack["demoted"]:
        for item, count, weight in pack["demoted"]:
            weight_text = "，累计白扛 %s" % _fmt_kg(weight) if weight else ""
            lines.append("· %s：%d 次原样往返%s——这次真的会用到吗？"
                         % (item, count, weight_text))
    elif pack["demoted_full"]:
        lines.append("（--all 已生效：以下惯犯按你的要求恢复进清单）")
        for item, count, weight in pack["demoted_full"]:
            lines.append("· %s：%d 次原样往返——账本记得，别怪它念叨" % (item, count))
    else:
        lines.append("没有反复白扛的物品。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI

def _load(path):
    try:
        return read_events(path)
    except ParseError as exc:
        print("账本解析失败：\n%s" % exc, file=sys.stderr)
        raise SystemExit(2)
    except OSError as exc:
        print("无法读取 %s：%s" % (path, exc), file=sys.stderr)
        raise SystemExit(2)


def cmd_analyze(args):
    events = _load(args.tsv)
    if not events:
        print("账本里没有任何事件：没东西可分析。先从下次行程开始记。", file=sys.stderr)
        return 1
    if args.type is not None:
        trips = select_trips(aggregate_trips(events), args.type)
        if not trips:
            print("没有类型为 %r 的行程" % args.type, file=sys.stderr)
            return 1
    print(build_report(events, args.type))
    return 0


def cmd_pack(args):
    events = _load(args.tsv)
    trips = aggregate_trips(events)
    if args.type is not None and not select_trips(trips, args.type):
        print("没有类型为 %r 的行程：清单将回退基线，但你要知道账本里没有这类行程"
              % args.type, file=sys.stderr)
    pack = build_pack(events, trips, args.type, args.days, args.all)
    print(build_pack_text(pack))
    return 0


def cmd_validate(args):
    try:
        events = read_events(args.tsv)
    except ParseError as exc:
        print("✗ 账本有问题：\n%s" % exc)
        return 1
    except OSError as exc:
        print("✗ 无法读取 %s：%s" % (args.tsv, exc))
        return 1
    trips = aggregate_trips(events)
    types = Counter(t.trip_type for t in trips)
    print("✓ %d 次行程、%d 条事件有效（%s）"
          % (len(trips), len(events),
             "、".join("%s×%d" % kv for kv in sorted(types.items()))))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="left-behind", description="漏带时刻：行李装箱的错题本")
    sub = parser.add_subparsers(dest="command", metavar="{analyze,pack,validate}")

    p_an = sub.add_parser("analyze", help="错题本报告")
    p_an.add_argument("tsv")
    p_an.add_argument("--type", default=None, help="限定分析域的行程类型")
    p_an.set_defaults(func=cmd_analyze)

    p_pk = sub.add_parser("pack", help="生成下次装箱清单")
    p_pk.add_argument("tsv")
    p_pk.add_argument("--type", default=None, help="行程类型（缺省取行程数最多的）")
    p_pk.add_argument("--days", type=int, default=None, help="行程天数（缺省取该类型历史均值）")
    p_pk.add_argument("--all", action="store_true",
                      help="不降级幽灵物品（惯犯也列进清单）")
    p_pk.set_defaults(func=cmd_pack)

    p_vd = sub.add_parser("validate", help="账本格式体检")
    p_vd.add_argument("tsv")
    p_vd.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
