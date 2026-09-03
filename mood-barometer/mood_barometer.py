#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mood-barometer · 阴晴表 —— 情绪的气候学.

问题：情绪数据每天都在产生，但没有任何账本记录它。于是模式永远看不见：
「我最近状态不好」说不清是从哪天开始、比平时低多少、有没有在恢复；心理咨询
师问「最近怎么样」，大脑只诚实记得最近三天；周日晚的颓、和某类人聊完的空、
一次冲突后爬不出来的天数——全部发生在体感里，从未发生在纸面上。

阴晴表把手写的情绪记录（TSV：日期/时间/心情1-5/事件标签/备注）读成一本
气象记录，用你对自己的历史算出四样感觉永远不会给你的东西：

  * climate   气候报告：基线（中位数）、天气（近 7 天对账）、星期节律、
              事件账单（哪类场合你最付不起）、回弹力（低点后几天回基线）、
              气候漂移（近 30 天 vs 前 30 天）——门禁 exit 4
  * weather   最近 7 天的天气视角：今天比你的气候低多少、是季节还是异动、
              滞留计时（这个低点已经持续几天 / 你的中位回弹是几天）
  * events    事件成本排行：每类标签的「情绪账单」（事件当天+后 2 天相对
              基线的偏移中位）——「内向所以社交累」这类自我叙事第一次
              可以对账
  * log       记录格式与量表锚点（1/3/5 的行为锚定——主观量表不锚定，
              记录本身就是噪声）

方法论骨架：单日心情是天气（波动大、无预测力），滑动窗口才是气候（有
基线、有节律、有趋势）。所以一切判定都用中位数（抗单日极端）、都要求
样本下限（不足即 THIN 拒判）、都对照你自己的基线（永远不说「正常人」）。

门禁语义：气候漂移（近 30 天中位比前 30 天低 ≥0.5）**且** 当前滞留
（低点后超过 2× 个人中位回弹期仍未回基线）同时成立才亮红灯——一个坏
季节人人都有，两个信号同时成立才是「气候在变」。红灯文案永远指向
专业帮助，不做诊断，不下病理结论。

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
「今天」默认真实当下，`--today` 钉死即逐字节可复现。

用法：
  python3 mood_barometer.py climate moods.tsv --today 2026-09-04
  python3 mood_barometer.py weather moods.tsv --today 2026-09-04
  python3 mood_barometer.py events  moods.tsv --today 2026-09-04
  python3 mood_barometer.py log

Exit codes:
  0  report produced（含绿灯）
  2  usage error / 账本缺失 / 坏行 / 越界 mood / 未来记录
  3  refusal: 样本不足（气候、事件账需要 ≥21 个记录日；事件标签需要 ≥5 次）
  4  gate: 气候漂移 ∧ 滞留 同时成立——「这不是天气，是气候在变」
"""

from __future__ import annotations

import argparse
import datetime as dt
import statistics
import sys
from typing import Dict, List, Optional, Tuple

PROG = "mood-barometer"
VERSION = "1.0.0"

MIN_DAYS = 21          # 气候/事件账的最低记录日数：不足 → THIN 拒判
MIN_EVENT_N = 5        # 单个事件标签的最低次数：不足 → 不进成本排行
MIN_WEEKDAY_N = 4      # 单个星期几的最低样本：不足 → 不判节律
MIN_REBOUND_N = 3      # 推滞留所需的最低回弹样本：不足 → 不判滞留
RECENT_WINDOW = 7      # 天气窗口
DRIFT_WINDOW = 30      # 气候漂移窗口
DRIFT_MIN_COVER = 14   # 漂移窗口最低覆盖天数
LOW_DELTA = 1.0        # mood ≤ 基线 − 1.0 记为低点
BACK_DELTA = 0.5       # mood ≥ 基线 − 0.5 记为回到基线
DRIFT_THRESHOLD = 0.5  # 近 30 天中位比前 30 天低 ≥0.5 → 气候漂移
REBOUND_MULT = 2.0     # 超过 2× 中位回弹期仍未回 → 滞留

MOOD_MIN, MOOD_MAX = 1, 5

MOOD_ANCHORS = {
    5: "高涨：好事发生，或纯粹的没来由的轻快",
    4: "不错：平稳偏上，有精力做计划外的事",
    3: "平：说不上好说不上坏——大多数日子的诚实答案",
    2: "低：提不起劲，靠惯性撑完一天",
    1: "谷底：只想消失，或已经哭过/失控",
}

MOOD_WORD = {5: "高涨", 4: "不错", 3: "平", 2: "低", 1: "谷底"}
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class UsageError(Exception):
    """exit 2：参数或账本错误。"""


class Refusal(Exception):
    """exit 3：样本不足，拒绝下结论。"""


class RedLight(Exception):
    """exit 4：门禁触发（气候漂移 ∧ 滞留）。"""


# ---------------------------------------------------------------------------
# 账本解析
# ---------------------------------------------------------------------------

class Entry:
    def __init__(self, date: dt.date, time: Optional[str], mood: float,
                 events: List[str], note: str, lineno: int):
        self.date = date
        self.time = time
        self.mood = mood
        self.events = events
        self.note = note
        self.lineno = lineno


def parse_tsv(path: str) -> List[Tuple[int, List[str]]]:
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.readlines()
    except FileNotFoundError:
        raise UsageError(f"账本不存在：{path}")
    rows: List[Tuple[int, List[str]]] = []
    for lineno, line in enumerate(raw, 1):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 5:
            raise UsageError(f"{path} 第 {lineno} 行：应有 5 列（Tab 分隔），实际 {len(fields)} 列")
        rows.append((lineno, [f.strip() for f in fields]))
    return rows


def load_moods(path: str, today: dt.date) -> List[Entry]:
    entries: List[Entry] = []
    for lineno, (date_s, time_s, mood_s, events_s, note) in parse_tsv(path):
        try:
            d = dt.date.fromisoformat(date_s)
        except ValueError:
            raise UsageError(f"moods.tsv 第 {lineno} 行：日期「{date_s}」不是 YYYY-MM-DD")
        if d > today:
            raise UsageError(f"moods.tsv 第 {lineno} 行：记录日期 {d} 在未来——账本不收预言")
        t: Optional[str] = None
        if time_s:
            try:
                hh, mm = time_s.split(":")
                if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                    raise ValueError
            except ValueError:
                raise UsageError(f"moods.tsv 第 {lineno} 行：时间「{time_s}」不是 HH:MM")
            t = time_s
        try:
            mood = float(mood_s)
        except ValueError:
            raise UsageError(f"moods.tsv 第 {lineno} 行：心情「{mood_s}」不是数字")
        if mood != int(mood) or not (MOOD_MIN <= mood <= MOOD_MAX):
            raise UsageError(
                f"moods.tsv 第 {lineno} 行：心情 {mood} 越界——量表是 {MOOD_MIN}-{MOOD_MAX} 的整数"
                "（锚点见 log 命令，锚定过的量表才有跨日可比性）")
        events = [e for e in (x.strip() for x in events_s.split(",")) if e] if events_s else []
        entries.append(Entry(d, t, int(mood), events, note, lineno))
    if not entries:
        raise Refusal("账本是空的——先记 21 天再回来谈气候；"
                      "前 21 天什么都不判，只积累你自己的基线")
    return entries


# ---------------------------------------------------------------------------
# 核心计算：一切以「日」为单位
# ---------------------------------------------------------------------------

def daily_series(entries: List[Entry]) -> Dict[dt.date, float]:
    """日内多条记录取日均值：之后的所有统计都是日度序列。"""
    buckets: Dict[dt.date, List[float]] = {}
    for e in entries:
        buckets.setdefault(e.date, []).append(e.mood)
    return {d: statistics.mean(v) for d, v in buckets.items()}


def baseline_of(series: Dict[dt.date, float]) -> float:
    return statistics.median(series.values())


def round1(x: float) -> str:
    return f"{x:+.1f}" if x < 0 else (f" {x:.1f}" if x > 0 else " 0.0")


def signed(x: float) -> str:
    return f"{x:+.1f}"


def window_median(series: Dict[dt.date, float], end: dt.date, days: int) -> Optional[float]:
    vals = [v for d, v in series.items() if end - dt.timedelta(days=days - 1) <= d <= end]
    return statistics.median(vals) if vals else None


def weather_now(series: Dict[dt.date, float], today: dt.date) -> Tuple[List[Tuple[dt.date, Optional[float]]], Optional[float]]:
    """最近 7 天逐日（缺记日为 None）+ 7 日均值。"""
    out: List[Tuple[dt.date, Optional[float]]] = []
    vals: List[float] = []
    for i in range(RECENT_WINDOW - 1, -1, -1):
        d = today - dt.timedelta(days=i)
        v = series.get(d)
        out.append((d, v))
        if v is not None:
            vals.append(v)
    return out, (statistics.mean(vals) if vals else None)


def weekday_offsets(series: Dict[dt.date, float], baseline: float) -> List[Tuple[int, float, int]]:
    """[(weekday, 偏移, 样本数)]，样本 ≥ MIN_WEEKDAY_N 才算。"""
    acc: Dict[int, List[float]] = {}
    for d, v in series.items():
        acc.setdefault(d.weekday(), []).append(v)
    out = []
    for wd in range(7):
        vals = acc.get(wd, [])
        if len(vals) >= MIN_WEEKDAY_N:
            out.append((wd, statistics.mean(vals) - baseline, len(vals)))
    out.sort(key=lambda t: t[1])
    return out


def event_costs(entries: List[Entry], series: Dict[dt.date, float],
                baseline: float, today: dt.date) -> List[Tuple[str, float, int]]:
    """事件账单：事件当天+后 2 天窗口均值 − 基线，按次数取中位。
    次数 < MIN_EVENT_N 的标签不判（返回列表里不出现）。"""
    occurrences: Dict[str, List[dt.date]] = {}
    for e in entries:
        for tag in e.events:
            occurrences.setdefault(tag, []).append(e.date)
    costs: List[Tuple[str, float, int]] = []
    for tag, dates in occurrences.items():
        if len(dates) < MIN_EVENT_N:
            continue
        per = []
        for d in sorted(set(dates)):
            vals = [series[x] for x in (d, d + dt.timedelta(days=1), d + dt.timedelta(days=2))
                    if x in series and x <= today]
            if vals:
                per.append(statistics.mean(vals) - baseline)
        if per:
            costs.append((tag, statistics.median(per), len(dates)))
    costs.sort(key=lambda t: t[1])
    return costs


def rebound_history(series: Dict[dt.date, float], baseline: float,
                    today: dt.date) -> Tuple[List[Tuple[dt.date, Optional[int]]],
                                             Optional[Tuple[dt.date, int]]]:
    """回弹史 + 当前滞留。

    低点日 = mood ≤ 基线 − 1.0；连续低点合并为一段（取段首）。
    恢复日 = 之后首个 mood ≥ 基线 − 0.5 的日期。
    返回 ([(低点日, 恢复天数|None)], (滞留低点日, 已滞留天数)|None)。
    """
    days_sorted = sorted(series)
    lows: List[dt.date] = []
    prev_low: Optional[dt.date] = None
    for d in days_sorted:
        if series[d] <= baseline - LOW_DELTA:
            if prev_low is None or (d - prev_low).days > 1:
                lows.append(d)
            prev_low = d
        else:
            prev_low = None
    history: List[Tuple[dt.date, Optional[int]]] = []
    pending: Optional[Tuple[dt.date, int]] = None
    for i, low in enumerate(lows):
        recovered = None
        for d in days_sorted:
            if d <= low:
                continue
            if series[d] >= baseline - BACK_DELTA:
                recovered = (d - low).days
                break
        history.append((low, recovered))
        if recovered is None and (i == len(lows) - 1):
            pending = (low, (today - low).days)
    return history, pending


def rebound_median(history: List[Tuple[dt.date, Optional[int]]]) -> Optional[float]:
    vals = [r for _, r in history if r is not None]
    return statistics.median(vals) if vals else None


def climate_drift(series: Dict[dt.date, float], today: dt.date) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """近 30 天中位 vs 前 30 天中位。任一窗口覆盖 < 14 天不判。"""
    recent = window_median(series, today, DRIFT_WINDOW)
    prev = window_median(series, today - dt.timedelta(days=DRIFT_WINDOW), DRIFT_WINDOW)
    recent_cover = sum(1 for d in series if today - dt.timedelta(days=DRIFT_WINDOW - 1) <= d <= today)
    prev_cover = sum(1 for d in series
                     if today - dt.timedelta(days=2 * DRIFT_WINDOW - 1) <= d < today - dt.timedelta(days=DRIFT_WINDOW - 1))
    if recent is None or prev is None or recent_cover < DRIFT_MIN_COVER or prev_cover < DRIFT_MIN_COVER:
        return None, None, None
    return recent, prev, recent - prev


class Diagnosis:
    def __init__(self):
        self.drifting = False          # 气候漂移成立
        self.stranded = False          # 滞留成立
        self.drift_detail = ""         # 报告用
        self.strand_detail = ""


def diagnose(series: Dict[dt.date, float], baseline: float, today: dt.date) -> Diagnosis:
    dx = Diagnosis()
    _, _, delta = climate_drift(series, today)
    if delta is not None and delta <= -DRIFT_THRESHOLD:
        dx.drifting = True
        dx.drift_detail = f"近 {DRIFT_WINDOW} 天中位比前 {DRIFT_WINDOW} 天低 {abs(delta):.1f}"
    history, pending = rebound_history(series, baseline, today)
    med = rebound_median(history)
    if pending and med is not None and len([1 for _, r in history if r is not None]) >= MIN_REBOUND_N:
        low, so_far = pending
        if so_far > REBOUND_MULT * med:
            dx.stranded = True
            dx.strand_detail = (f"{low.isoformat()} 的低点已 {so_far} 天没回到基线"
                                f"（你的中位回弹是 {med:.0f} 天，2× 是 {REBOUND_MULT * med:.0f} 天）")
    return dx


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def _mood_bar(v: float) -> str:
    """mood 值的简易条形：1-5。"""
    filled = int(round(v))
    return "▁▃▅▆█"[filled - 1] if 1 <= filled <= 5 else "?"


def report_climate(entries: List[Entry], today: dt.date) -> Tuple[str, Diagnosis, float]:
    series = daily_series(entries)
    n_days = len(series)
    if n_days < MIN_DAYS:
        raise Refusal(f"记录日 {n_days} 天 < {MIN_DAYS} 天——气候无法与噪声区分，"
                      "先记满 21 天（期间 weather 命令照常可用）")
    baseline = baseline_of(series)
    lines: List[str] = []
    lines.append(f"═══ 阴晴表 · 气候报告（截至 {today.isoformat()}）═══")
    lines.append(f"记录 {len(entries)} 条 / {n_days} 天。你的气候基线：{baseline:.1f}（{MOOD_WORD[round(baseline)]}）")
    lines.append("")
    lines.append("── 天气 · 近 7 天对账 ──")
    days, avg = weather_now(series, today)
    for d, v in days:
        mark = "（未记录）" if v is None else f"{_mood_bar(v)} {v:.1f}  {signed(v - baseline)} vs 基线"
        lines.append(f"  {d.isoformat()}  {mark}")
    if avg is not None:
        lines.append(f"  7 日均值 {avg:.1f}（比基线 {signed(avg - baseline)}）")
    lines.append("")
    lines.append("── 节律 · 星期效应（样本 ≥4 的才判）──")
    offs = weekday_offsets(series, baseline)
    if not offs:
        lines.append("  每个星期几的样本都还不足，节律不判。")
    for wd, off, n in offs:
        tag = "  ← 统计上存在" if abs(off) >= 0.5 else ""
        lines.append(f"  {WEEKDAY_NAMES[wd]}  均值比基线 {signed(off)}（{n} 个记录日）{tag}")
    lines.append("")
    lines.append("── 事件账单 · 哪类场合你最付不起 ──")
    costs = event_costs(entries, series, baseline, today)
    if not costs:
        lines.append(f"  还没有任何标签攒够 {MIN_EVENT_N} 次——继续记，标签见 log。")
    for tag, cost, n in costs:
        lines.append(f"  {tag:<14} 成本 {signed(cost)}（{n} 次，事件当天+后 2 天均值 vs 基线）")
    lines.append("")
    lines.append("── 回弹 · 你的恢复力 ──")
    history, pending = rebound_history(series, baseline, today)
    med = rebound_median(history)
    if not history:
        lines.append("  还没有出现过低点——这本身就是气象记录里最稀有的天气。")
    else:
        for low, r in history[-5:]:
            desc = f"{r} 天回到基线" if r is not None else "未回到基线"
            lines.append(f"  低点 {low.isoformat()}（{_mood_bar(series[low])}）→ {desc}")
        if med is not None:
            lines.append(f"  中位回弹期：{med:.0f} 天")
    lines.append("")
    lines.append("── 气候漂移 · 近 30 天 vs 前 30 天 ──")
    recent, prev, delta = climate_drift(series, today)
    if delta is None:
        lines.append("  窗口覆盖不足（两窗各需 ≥14 个记录日），漂移不判。")
    else:
        verdict = "在漂移 ↓" if delta <= -DRIFT_THRESHOLD else ("在回暖 ↑" if delta >= DRIFT_THRESHOLD else "稳定")
        lines.append(f"  前 30 天中位 {prev:.1f} → 近 30 天中位 {recent:.1f}（{signed(delta)}，{verdict}）")
    dx = diagnose(series, baseline, today)
    lines.append("")
    lines.append("── 门禁 ──")
    if dx.drifting and dx.stranded:
        lines.append(f"  气候漂移 ∧ 滞留，两个信号同时成立：")
        lines.append(f"    · {dx.drift_detail}")
        lines.append(f"    · {dx.strand_detail}")
        lines.append("  这不是天气，是气候在变。天气等得起，气候值得让专业的人参与——")
        lines.append("  这份报告可以直接带进咨询室，它比「最近有点丧」诚实得多。")
    elif dx.drifting:
        lines.append(f"  漂移成立（{dx.drift_detail}）但未滞留——先当坏季节对待，继续记。")
    elif dx.stranded:
        lines.append(f"  滞留成立（{dx.strand_detail}）但无漂移——盯着这一个低点即可。")
    else:
        lines.append("  气候稳定，无滞留。灯是绿的，继续记。")
    return "\n".join(lines), dx, baseline


def report_weather(entries: List[Entry], today: dt.date) -> str:
    series = daily_series(entries)
    n_days = len(series)
    lines: List[str] = []
    lines.append(f"═══ 阴晴表 · 天气（截至 {today.isoformat()}）═══")
    if n_days < MIN_DAYS:
        lines.append(f"基线收集中（{n_days}/{MIN_DAYS} 天）——以下是原始天气，没有气候可对照。")
        baseline: Optional[float] = None
    else:
        baseline = baseline_of(series)
        lines.append(f"你的气候基线：{baseline:.1f}（{MOOD_WORD[round(baseline)]}）")
    lines.append("")
    days, avg = weather_now(series, today)
    for d, v in days:
        mark = "（未记录）" if v is None else f"{_mood_bar(v)} {v:.1f}"
        if v is not None and baseline is not None:
            mark += f"  {signed(v - baseline)} vs 基线"
        lines.append(f"  {d.isoformat()}（{WEEKDAY_NAMES[d.weekday()]}）  {mark}")
    if avg is not None:
        rel = f"（比基线 {signed(avg - baseline)}）" if baseline is not None else ""
        lines.append(f"  7 日均值 {avg:.1f}{rel}")
    if baseline is not None:
        history, pending = rebound_history(series, baseline, today)
        med = rebound_median(history)
        if pending:
            low, so_far = pending
            if med is not None:
                lines.append(f"  滞留计时：{low.isoformat()} 的低点已 {so_far} 天，"
                             f"你的中位回弹是 {med:.0f} 天，2× 红线 {REBOUND_MULT * med:.0f} 天。")
            else:
                lines.append(f"  滞留计时：{low.isoformat()} 的低点已 {so_far} 天未回基线"
                             "——回弹样本不足，暂无中位可对照。")
        else:
            latest = max(series)
            if series[latest] >= baseline - BACK_DELTA:
                lines.append("  当前不在低点。天气正常。")
    if n_days < MIN_DAYS:
        lines.append(f"  还差 {MIN_DAYS - n_days} 个记录日，气候报告解锁。")
    return "\n".join(lines)


def report_events(entries: List[Entry], today: dt.date) -> str:
    series = daily_series(entries)
    n_days = len(series)
    if n_days < MIN_DAYS:
        raise Refusal(f"记录日 {n_days} 天 < {MIN_DAYS} 天——事件成本需要基线，先记满 21 天")
    baseline = baseline_of(series)
    lines: List[str] = []
    lines.append(f"═══ 阴晴表 · 事件账单（截至 {today.isoformat()}，基线 {baseline:.1f}）═══")
    costs = event_costs(entries, series, baseline, today)
    if not costs:
        lines.append(f"没有任何标签攒够 {MIN_EVENT_N} 次。给你自己的标签一点耐心——")
        lines.append("事件的成本是统计出来的，不是感觉出来的。")
        return "\n".join(lines)
    lines.append("成本 = 事件当天+后 2 天的均值相对基线的偏移（按次取中位）。")
    lines.append("正数是充电场合，负数是耗电场合——你的自我叙事在这里对账：")
    lines.append("")
    n_pos = sum(1 for _, c, _ in costs if c > 0)
    lines.append(f"  充电场合 {n_pos} 类，耗电场合 {len(costs) - n_pos} 类")
    lines.append("")
    for tag, cost, n in costs:
        if cost <= -0.5:
            verdict = "重耗电"
        elif cost < 0:
            verdict = "轻耗电"
        elif cost < 0.5:
            verdict = "中性"
        else:
            verdict = "充电"
        lines.append(f"  {tag:<14} {signed(cost)}  [{verdict}]  {n} 次")
    top = costs[0]
    if top[1] <= -0.5:
        lines.append("")
        lines.append(f"  「{top[0]}」是你的头号耗电场合：平均把你拖到基线以下 {abs(top[1]):.1f} 分。")
        lines.append("  它不值得消灭（多数是责任），但值得在它前后各留一天的恢复预算。")
    return "\n".join(lines)


def report_log() -> str:
    lines: List[str] = []
    lines.append("═══ 阴晴表 · 记录格式 ══")
    lines.append("moods.tsv，Tab 分隔 5 列，# 开头为注释，一天可记多条（当天取均值）：")
    lines.append("")
    lines.append("  date\ttime\tmood\tevents\tnote")
    lines.append("  2026-09-01\t21:30\t2\tconflict,deadline\t和甲方吵完回来")
    lines.append("  2026-09-02\t\t4\t\t")
    lines.append("")
    lines.append("time 可空（不填则该条不参与小时段分析）。events 逗号分隔，标签自定义，")
    lines.append("同一个标签攒够 5 次就会出现在事件账单里。常用的：")
    lines.append("  work / deadline / conflict / social / family / exercise / sick / travel")
    lines.append("")
    lines.append("── 量表锚点（1-5 整数）──")
    lines.append("主观量表不锚定就是噪声：同一天的心情，早上记是 3、晚上记可能是 2。")
    lines.append("锚定到「行为」而不是「感觉」，跨日才可比：")
    for m in (5, 4, 3, 2, 1):
        lines.append(f"  {m}  {MOOD_ANCHORS[m]}")
    lines.append("")
    lines.append("记 21 天后才解锁气候报告——前 21 天不是白记，是基线本身。")
    lines.append("一天最要紧的只有一行；漏记不要补（补的是记忆不是记录）。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG, description="阴晴表 —— 情绪的气候学")
    parser.add_argument("--version", action="version", version=f"{PROG} {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_cli = sub.add_parser("climate", help="气候报告 + 门禁")
    p_cli.add_argument("ledger", help="moods.tsv")
    p_cli.add_argument("--today", default=None, help="钉死今天（YYYY-MM-DD）")

    p_wea = sub.add_parser("weather", help="近 7 天天气 + 滞留计时")
    p_wea.add_argument("ledger", help="moods.tsv")
    p_wea.add_argument("--today", default=None, help="钉死今天（YYYY-MM-DD）")

    p_eve = sub.add_parser("events", help="事件成本排行")
    p_eve.add_argument("ledger", help="moods.tsv")
    p_eve.add_argument("--today", default=None, help="钉死今天（YYYY-MM-DD）")

    sub.add_parser("log", help="记录格式与量表锚点")

    args = parser.parse_args(argv)

    try:
        if args.command == "log":
            print(report_log())
            return 0
        today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
        entries = load_moods(args.ledger, today)
        if args.command == "climate":
            text, dx, _ = report_climate(entries, today)
            print(text)
            if dx.drifting and dx.stranded:
                raise RedLight("气候漂移 ∧ 滞留同时成立——这不是天气，是气候在变（exit 4）")
            return 0
        if args.command == "weather":
            print(report_weather(entries, today))
            return 0
        if args.command == "events":
            print(report_events(entries, today))
            return 0
        parser.error(f"未知命令：{args.command}")
        return 2
    except UsageError as e:
        print(f"{PROG}: usage error: {e}", file=sys.stderr)
        return 2
    except Refusal as e:
        print(f"{PROG}: refusal: {e}", file=sys.stderr)
        return 3
    except RedLight as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
