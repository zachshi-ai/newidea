#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""borderline · 贴线 —— 体检指标的纵向趋势账本.

问题：体检报告是快照思维——本年数值 vs 参考区间，输出「正常/偏高」的二元
结论。但健康风险住在趋势里：尿酸 421 → 432 连年爬坡，年年「正常」，比一次
485 危险得多，却永远不会被报告点名。「正常」是区间，不是方向；跨线是结果，
爬坡才是过程。报告抓得到已经越线的，抓不到正在赶来的。

borderline 把散在每年报告里的检验值抄成一本可手编的纵向账本（TSV：
指标/日期/数值/单位/参考区间），用你自己对自己的历史算出：

  * panel     全指标面板：Theil-Sen 斜率、余量年数、状态阶梯，门禁 exit 4
  * trend     单指标全史：逐年数值、对上限百分比、首次越线年份
  * next      复查节奏：专项复查 / 半年加测 / 年度照旧 / 继续攒
  * validate  账本体检：点数、跨度、区间变更、新鲜度
  * markers   常见指标说明：单位、惯犯清单、该挂哪个科

状态阶梯：OVER（已越线）> BORDERLINE（在爬且余量 ≤ 3 年）> WATCH（在爬，
余量尚足）> STEADY（没在爬）> THIN（不足 3 次，拒判）。门禁语义是「还在爬
的都要有个说法」：BORDERLINE 与越线仍在爬的亮红灯——越线但已企稳的说明有
人在管，不进门禁。

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
「今天」默认真实当下，`--today` 钉死即逐字节可复现。

用法：
  python3 borderline.py panel ledger.tsv --today 2026-09-04
  python3 borderline.py trend ledger.tsv --marker uric-acid
  python3 borderline.py next ledger.tsv --today 2026-09-04
  python3 borderline.py validate ledger.tsv --today 2026-09-04
  python3 borderline.py markers

Exit codes:
  0  report produced（含绿灯）
  2  usage error / 账本缺失 / 坏行 / 单位冲突 / 未来体检
  3  refusal: nothing to compute (空账本、指定指标不在账本中)
  4  gate: 存在 BORDERLINE 或越线仍在爬的指标
"""

from __future__ import annotations

import argparse
import datetime as dt
import statistics
import sys
from typing import Dict, List, Optional, Tuple

PROG = "borderline"
VERSION = "1.0.0"

MIN_POINTS = 3          # 少于 3 次测量 → THIN，不判趋势
NOISE_FLOOR = 0.10      # 净涨幅 < 参考区间宽度的 10% → 化验噪声，不算在爬
BORDERLINE_YEARS = 3.0  # 余量 ≤ 3 年 → BORDERLINE（下一轮三年内必然面对这条线）
STALE_MONTHS = 15.0     # 距上次体检 > 15 个月 → 账本过期提示

# 常见指标：中文名 / 单位 / 惯犯清单 / 科室。账本里的指标名自由，
# 不在此表的照常计算，只是没有惯犯与科室提示。
MARKERS = {
    "uric-acid": ("尿酸", "µmol/L",
                  "高嘌呤饮食（内脏/浓肉汤/啤酒）、含糖饮料、饮水少、体检前剧烈运动",
                  "内分泌 / 风湿免疫"),
    "fasting-glucose": ("空腹血糖", "mmol/L",
                        "精制碳水、含糖饮料、久坐、连续熬夜",
                        "内分泌"),
    "ldl": ("低密度脂蛋白胆固醇", "mmol/L",
            "反式脂肪、膳食纤维不足、运动少",
            "心内科"),
    "bmi": ("体重指数", "kg/m²",
            "热量盈余、久坐、睡眠不足",
            "营养科 / 内分泌"),
    "sbp": ("收缩压", "mmHg",
            "钠、酒精、压力、睡眠呼吸暂停",
            "心内科"),
    "alt": ("丙氨酸氨基转移酶", "U/L",
            "酒精、脂肪肝、药物、熬夜",
            "消化内科 / 肝病科"),
    "creatinine": ("肌酐", "µmol/L",
                   "脱水、高蛋白饮食、肾功能",
                   "肾内科"),
    "hemoglobin": ("血红蛋白", "g/L",
                   "缺铁、慢性失血",
                   "血液科"),
    "tsh": ("促甲状腺激素", "mIU/L",
            "碘摄入波动、昼夜节律紊乱",
            "内分泌"),
}


class UsageError(Exception):
    """exit 2：参数或账本错误。"""


class Refusal(Exception):
    """exit 3：无可计算。"""


class RedLight(Exception):
    """exit 4：门禁触发（存在 BORDERLINE 或越线仍在爬）。携带报告文本。"""


# ---------------------------------------------------------------------------
# 账本解析
# ---------------------------------------------------------------------------

class Row:
    def __init__(self, marker: str, date: dt.date, value: float, unit: str,
                 ref_low: Optional[float], ref_high: float, note: str, lineno: int):
        self.marker = marker
        self.date = date
        self.value = value
        self.unit = unit
        self.ref_low = ref_low
        self.ref_high = ref_high
        self.note = note
        self.lineno = lineno


def parse_date(text: str, lineno: int) -> dt.date:
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise UsageError(f"第 {lineno} 行：日期「{text}」不是 YYYY-MM-DD")


def parse_float(text: str, lineno: int, what: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise UsageError(f"第 {lineno} 行：{what}「{text}」不是数字")


def fnum(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def fmt_range(ref_low: Optional[float], ref_high: float) -> str:
    if ref_low is None:
        return f"≤ {fnum(ref_high)}"
    return f"{fnum(ref_low)}-{fnum(ref_high)}"


def load_ledger(path: str, today: dt.date) -> Dict[str, List[Row]]:
    """读指标账本，按指标分组、按日期排序。坏行带行号 exit 2。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        raise UsageError(f"账本文件不存在：{path}")
    rows: List[Row] = []
    seen: set = set()
    units: Dict[str, Tuple[str, int]] = {}
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        if len(cols) < 6:
            raise UsageError(f"第 {lineno} 行：需要至少 6 列"
                             f"（指标/日期/数值/单位/参考下限/参考上限），得到 {len(cols)} 列")
        marker = cols[0]
        if not marker:
            raise UsageError(f"第 {lineno} 行：指标名为空")
        date = parse_date(cols[1], lineno)
        if date > today:
            raise UsageError(f"第 {lineno} 行：体检日期 {cols[1]} 在今天之后")
        value = parse_float(cols[2], lineno, "数值")
        if value <= 0:
            raise UsageError(f"第 {lineno} 行：数值必须 > 0，得到 {value}")
        unit = cols[3]
        if not unit:
            raise UsageError(f"第 {lineno} 行：单位为空")
        ref_low: Optional[float]
        if cols[4] == "-":
            ref_low = None
        else:
            ref_low = parse_float(cols[4], lineno, "参考下限")
        ref_high = parse_float(cols[5], lineno, "参考上限")
        if ref_high <= 0:
            raise UsageError(f"第 {lineno} 行：参考上限必须 > 0，得到 {ref_high}")
        if ref_low is not None and ref_high <= ref_low:
            raise UsageError(f"第 {lineno} 行：参考上限 {fnum(ref_high)} 必须 > 参考下限 {fnum(ref_low)}")
        note = cols[6] if len(cols) > 6 else ""
        key = (marker, date)
        if key in seen:
            raise UsageError(f"第 {lineno} 行：{marker} 在 {cols[1]} 重复记账")
        seen.add(key)
        if marker in units and units[marker][0] != unit:
            raise UsageError(f"第 {lineno} 行：{marker} 的单位是「{unit}」，"
                             f"与第 {units[marker][1]} 行的「{units[marker][0]}」冲突——"
                             f"换医院单位变了请先折算成同一单位再入账")
        units.setdefault(marker, (unit, lineno))
        rows.append(Row(marker, date, value, unit, ref_low, ref_high, note, lineno))
    if not rows:
        raise Refusal(f"账本是空的：{path}")
    grouped: Dict[str, List[Row]] = {}
    for r in rows:
        grouped.setdefault(r.marker, []).append(r)
    for marker in grouped:
        grouped[marker].sort(key=lambda r: r.date)
    return grouped


# ---------------------------------------------------------------------------
# 趋势引擎
# ---------------------------------------------------------------------------

def decimal_year(d: dt.date) -> float:
    return d.year + (d.timetuple().tm_yday - 1) / 365.0


def theil_sen_slope(rows: List[Row]) -> float:
    """成对斜率的中位数。3-7 个点的年代，OLS 会被一次化验失误绑架
    （抽血前没空腹、体检前打了一场球），中位斜率对单点离群免疫。"""
    xs = [decimal_year(r.date) for r in rows]
    ys = [r.value for r in rows]
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
              for i in range(len(rows)) for j in range(i + 1, len(rows))]
    return statistics.median(slopes)


def analyze(rows: List[Row]) -> dict:
    """单指标全史分析：斜率、净涨幅、余量、状态阶梯。

    状态阶梯与门禁：
      THIN        n < 3，拒判（任何两点都完美共线，斜率无意义）
      OVER        最新值 > 最新参考上限；「仍在爬」= climbing
      BORDERLINE  未越线但在爬，余量 ≤ BORDERLINE_YEARS —— 门禁
      WATCH       在爬但余量 > BORDERLINE_YEARS
      STEADY      没在爬（斜率 ≤ 0，或净涨幅低于噪声地板）
    门禁 = BORDERLINE，或 OVER 且 climbing——越线但已企稳的有人在管。
    """
    latest = rows[-1]
    n = len(rows)
    slope = theil_sen_slope(rows)
    over = latest.value > latest.ref_high
    first_cross = next((r for r in rows if r.value > r.ref_high), None)
    over_count = sum(1 for r in rows if r.value > r.ref_high)
    width = latest.ref_high - (latest.ref_low if latest.ref_low is not None else 0.0)
    net = latest.value - rows[0].value
    range_changed = len({(r.ref_low, r.ref_high) for r in rows}) > 1
    floor = NOISE_FLOOR * width
    climbing = n >= MIN_POINTS and slope > 1e-12 and net >= floor
    runway = (latest.ref_high - latest.value) / slope if slope > 1e-12 else None
    down = (not climbing) and slope < -1e-12 and -net >= floor
    if n < MIN_POINTS:
        status = "THIN"
    elif over:
        status = "OVER"
    elif climbing and runway is not None and runway <= BORDERLINE_YEARS:
        status = "BORDERLINE"
    elif climbing:
        status = "WATCH"
    else:
        status = "STEADY"
    gate = status == "BORDERLINE" or (status == "OVER" and climbing)
    return {"n": n, "latest": latest, "slope": slope, "net": net, "width": width,
            "floor": floor, "climbing": climbing, "runway": runway, "over": over,
            "first_cross": first_cross, "over_count": over_count,
            "range_changed": range_changed, "down": down, "status": status,
            "gate": gate}


def display_name(marker: str) -> str:
    return MARKERS[marker][0] if marker in MARKERS else marker


def unit_of(marker: str) -> str:
    return MARKERS[marker][1] if marker in MARKERS else "单位"


STATUS_TAG = {"OVER": "✗ OVER", "BORDERLINE": "▲ BORDER", "WATCH": "○ WATCH",
              "STEADY": "· STEADY", "THIN": "◌ THIN"}
STATUS_ORDER = {"OVER": 0, "BORDERLINE": 1, "WATCH": 2, "STEADY": 3, "THIN": 4}


def panel_sort_key(marker: str, a: dict):
    """OVER 按首越日期（最早的排最前），BORDERLINE 按余量（最短的排最前），
    其余按指标名字母序——同组内确定性排序。"""
    st = a["status"]
    if st == "OVER":
        return (STATUS_ORDER[st], a["first_cross"].date if a["first_cross"] else a["latest"].date, marker)
    if st == "BORDERLINE":
        return (STATUS_ORDER[st], a["runway"] if a["runway"] is not None else 0.0, marker)
    return (STATUS_ORDER[st], dt.date.min, marker)


def runway_text(a: dict) -> str:
    if a["status"] == "OVER" or (a["latest"].value > a["latest"].ref_high):
        return "已越线"
    if a["runway"] is None or not a["climbing"]:
        return "—"
    return f"{a['runway']:.1f} 年"


def slope_text(a: dict) -> str:
    if a["n"] < MIN_POINTS:
        return "—"
    return f"{a['slope']:+.2f}/年"


def status_note(marker: str, a: dict) -> str:
    st = a["status"]
    if st == "THIN":
        note = f"n={a['n']}，满 {MIN_POINTS} 次才判趋势"
        if a["over"]:
            note = "已越线，但" + note
        return note
    if st == "OVER":
        first = a["first_cross"].date.year if a["first_cross"] else a["latest"].date.year
        if a["climbing"]:
            return f"{first} 首越 · 线上 {a['over_count']} 次 · 仍在爬"
        return f"{first} 首越 · 已企稳/在管"
    if st == "BORDERLINE":
        return f"贴线爬坡 · 距线 {a['runway']:.1f} 年"
    if st == "WATCH":
        return f"在爬 · 余量 {a['runway']:.1f} 年"
    if a["down"]:
        return "▽ 在降"
    if a["net"] < a["floor"]:
        return "化验噪声内"
    return ""


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def stale_months(latest_date: dt.date, today: dt.date) -> float:
    return (today - latest_date).days / 30.44


def stale_warning(stale: float) -> str:
    return (f"⚠ 距上次体检已 {stale:.0f} 个月（> {STALE_MONTHS:.0f}）：账本过期，"
            "斜率会低估爬速——先去体检，再回来记账。")


def cmd_panel(ledger: Dict[str, List[Row]], today: dt.date) -> Tuple[str, int]:
    latest_checkup = max(r.date for rows in ledger.values() for r in rows)
    total = sum(len(rows) for rows in ledger.values())
    first_checkup = min(r.date for rows in ledger.values() for r in rows)
    stale = stale_months(latest_checkup, today)
    header = (f"贴线面板 · 最新体检 {latest_checkup.isoformat()}（距今 {stale:.0f} 个月）"
              f" · {len(ledger)} 项指标 · {total} 次测量 · {first_checkup.year} 年起")
    lines = [header, ""]
    if stale > STALE_MONTHS:
        lines.append(stale_warning(stale))
        lines.append("")
    lines.append("  状态       指标                最新      参考区间        余量       斜率       备注")
    entries = [(m, analyze(rows)) for m, rows in ledger.items()]
    entries.sort(key=lambda pair: panel_sort_key(pair[0], pair[1]))
    gates = []
    changed = []
    for marker, a in entries:
        if a["gate"]:
            gates.append((marker, a))
        rng = fmt_range(a["latest"].ref_low, a["latest"].ref_high)
        if a["range_changed"]:
            rng += " *"
            changed.append(marker)
        lines.append(f"  {STATUS_TAG[a['status']]:<10s} {marker:<18s} {fnum(a['latest'].value):>7s}"
                     f"   {rng:<12s} {runway_text(a):>6s}   {slope_text(a):>9s}   {status_note(marker, a)}")
    if changed:
        lines.append("")
        for m in changed:
            rows = ledger[m]
            latest_rng = (rows[-1].ref_low, rows[-1].ref_high)
            old = next(r for r in rows if (r.ref_low, r.ref_high) != latest_rng)
            since = next(r for r in rows if (r.ref_low, r.ref_high) == latest_rng)
            lines.append(f"  * {m} 的参考区间自 {since.date.isoformat()} 起变更"
                         f"（{fmt_range(old.ref_low, old.ref_high)} → "
                         f"{fmt_range(rows[-1].ref_low, rows[-1].ref_high)}）：余量按最新区间算")
    lines.append("")
    if not gates:
        lines.append("判定  GREEN —— 没有一项在爬。「正常」不是运气，是这本账在盯。")
        return "\n".join(lines) + "\n", 0
    overs = [m for m, a in gates if a["status"] == "OVER"]
    borders = sorted((m for m, a in gates if a["status"] == "BORDERLINE"),
                     key=lambda m: ledger[m] and analyze(ledger[m])["runway"])
    parts = []
    if overs:
        parts.append("越线的还在爬（" + "、".join(overs) + "）")
    if borders:
        parts.append("贴线的快到线（" + "、".join(borders) + "）")
    lines.append(f"判定  RED —— {len(gates)} 项在爬：{'；'.join(parts)}")
    lines.append("")
    lines.append("报告抓得到已经越线的，抓不到正在赶来的。跨线是结果，爬坡才是过程——")
    lines.append("「正常」是区间，不是方向。带着 next 的清单去复查。")
    return "\n".join(lines) + "\n", 4


def cmd_trend(ledger: Dict[str, List[Row]], marker: str) -> Tuple[str, int]:
    if marker not in ledger:
        raise Refusal(f"账本里没有「{marker}」这个指标。现有的：{'、'.join(sorted(ledger))}")
    rows = ledger[marker]
    a = analyze(rows)
    latest = rows[-1]
    name = display_name(marker)
    lines = [f"{marker} · {name} 全史 · {a['n']} 次测量 · {latest.unit}"
             f" · 参考 {fmt_range(latest.ref_low, latest.ref_high)}"
             + ("（区间有过变更，见下）" if a["range_changed"] else ""), ""]
    lines.append("  日期        数值    对上限   状态")
    over_seen = 0
    for r in rows:
        pct = r.value / r.ref_high * 100
        if r.value > r.ref_high:
            over_seen += 1
            mark = f"✗ 越线（第 {over_seen} 次）" if over_seen > 1 else "✗ 越线（首次）"
        else:
            mark = "· 正常"
        lines.append(f"  {r.date.isoformat()}  {fnum(r.value):>6s}   {pct:3.0f}%   {mark}")
    lines.append("")
    if a["n"] < MIN_POINTS:
        lines.append(f"  n={a['n']} < {MIN_POINTS}：趋势判定拒判——点数不足时任何斜率都是过拟合。")
        lines.append("  越线是事实、照旧显示；但「在不在爬」要等第 3 次测量才肯说。")
        return "\n".join(lines) + "\n", 0
    pairs = a["n"] * (a["n"] - 1) // 2
    lines.append(f"  Theil-Sen 斜率   {a['slope']:+.2f} /年（{a['n']} 次测量 · {pairs} 对斜率取中位）")
    share = a["net"] / a["width"] * 100 if a["width"] else 0.0
    verdict = "高于 10% 噪声地板 → 判定「在爬」" if a["climbing"] else \
              ("低于 10% 噪声地板 → 判定「化验噪声」" if a["net"] >= 0 else "净值为负 → 未在爬")
    lines.append(f"  净涨幅           {a['net']:+g}（区间宽度的 {share:.0f}%，{verdict}）")
    if a["runway"] is not None and not a["over"]:
        if a["climbing"]:
            lines.append(f"  余量             按当前斜率 {a['runway']:.1f} 年到线"
                         f"（上限 {fnum(latest.ref_high)}，最新 {fnum(latest.value)}）")
        else:
            lines.append("  余量             没在爬——斜率不足或方向向下，余量不设限")
    elif a["over"]:
        first = a["first_cross"].date.year if a["first_cross"] else "?"
        still = "，且仍在爬——门禁 RED" if a["climbing"] else "，已企稳/在管——不进门禁"
        lines.append(f"  余量             已越线：{first} 年首次越线，线上 {a['over_count']} 次{still}")
    if a["down"]:
        lines.append(f"  ▽ 方向向下：净跌 {-a['net']:+g}，占区间宽度 {-a['net'] / a['width'] * 100:.0f}%——如果是干预的功劳，账本记得它")
    if a["range_changed"]:
        latest_rng = (latest.ref_low, latest.ref_high)
        old = next(r for r in rows if (r.ref_low, r.ref_high) != latest_rng)
        since = next(r for r in rows if (r.ref_low, r.ref_high) == latest_rng)
        lines.append(f"  * 参考区间自 {since.date.isoformat()} 起变更："
                     f"{fmt_range(old.ref_low, old.ref_high)}"
                     f" → {fmt_range(latest.ref_low, latest.ref_high)}"
                     f"（换医院/方法很常见）；越线史按当年区间记，余量按最新区间算")
    return "\n".join(lines) + "\n", 0


def cmd_next(ledger: Dict[str, List[Row]], today: dt.date) -> Tuple[str, int]:
    latest_checkup = max(r.date for rows in ledger.values() for r in rows)
    stale = stale_months(latest_checkup, today)
    lines = ["复查节奏 · 按「还在爬」排序（这是带去见医生的问题清单，不是诊断）", ""]
    entries = [(m, analyze(rows)) for m, rows in ledger.items()]
    gates = sorted((e for e in entries if e[1]["gate"]), key=lambda e: panel_sort_key(e[0], e[1]))
    rest = sorted((e for e in entries if not e[1]["gate"]),
                  key=lambda e: (STATUS_ORDER[e[1]["status"]], e[0]))
    for marker, a in gates + rest:
        dept = f"（{MARKERS[marker][3]}）" if marker in MARKERS else ""
        if a["status"] == "OVER" and a["climbing"]:
            action = f"专项复查：越线 {a['over_count']} 次仍在爬，年度节奏追不上它——建议 3-6 个月内复测{dept}"
        elif a["status"] == "BORDERLINE":
            action = f"半年加测：按当前斜率 {a['runway']:.1f} 年到线——下次体检季就到，先加测一次{dept}"
        elif a["status"] == "OVER":
            action = f"年度照旧：已越线但未在爬——带着这本账与医生确认控制方案是否起效{dept}"
        elif a["status"] == "WATCH":
            action = f"年度照旧：在爬但余量 {a['runway']:.1f} 年——下次体检把 {marker} 列为重点{dept}"
        elif a["status"] == "THIN":
            over_note = "已越线但点数不足——下次体检必测" if a["over"] else "下次体检必测"
            action = f"继续攒：{over_note}，满 {MIN_POINTS} 次测量即可判趋势{dept}"
        elif a["down"]:
            action = f"年度照旧：▽ 在降，方向是对的——保持现在的生活方式{dept}"
        else:
            action = f"年度照旧{dept}"
        lines.append(f"  {STATUS_TAG[a['status']]:<10s} {marker:<18s} {action}")
    lines.append("")
    if stale > STALE_MONTHS:
        lines.append(stale_warning(stale))
    else:
        lines.append(f"距上次体检 {stale:.0f} 个月，账本新鲜。节奏：越线在爬的 3-6 个月，"
                     "贴线的半年，其余跟着年度体检走。")
    return "\n".join(lines) + "\n", 0


def cmd_validate(ledger: Dict[str, List[Row]], today: dt.date) -> Tuple[str, int]:
    total = sum(len(rows) for rows in ledger.values())
    lines = [f"账本体检 · {len(ledger)} 个指标 · {total} 次测量", ""]
    for marker in sorted(ledger):
        rows = ledger[marker]
        a = analyze(rows)
        thin = f"（THIN，不足 {MIN_POINTS} 次）" if a["n"] < MIN_POINTS else ""
        changed = "（区间有变更）" if a["range_changed"] else ""
        span = f"{rows[0].date.isoformat()} → {rows[-1].date.isoformat()}"
        lines.append(f"  {marker:<18s} {a['n']:>2} 次  {span}  {rows[0].unit}{thin}{changed}")
    latest_checkup = max(r.date for rows in ledger.values() for r in rows)
    stale = stale_months(latest_checkup, today)
    lines.append("")
    lines.append("账本干净：日期合法、无重复记录、无未来体检、数值均为正、单位一致。")
    if stale > STALE_MONTHS:
        lines.append(stale_warning(stale))
    else:
        lines.append(f"账本新鲜：距上次体检 {stale:.0f} 个月。")
    return "\n".join(lines) + "\n", 0


def cmd_markers() -> Tuple[str, int]:
    lines = ["常见指标（账本里的指标名自由，不在此表照常计算）：", ""]
    for slug, (name, unit, culprits, dept) in MARKERS.items():
        lines.append(f"  {slug:<16s} {name} · {unit}")
        lines.append(f"                   惯犯：{culprits}")
        lines.append(f"                   科室：{dept}")
    lines.append("")
    lines.append("参考区间因医院/方法/人群而异——抄你自己的报告，别抄网上的。")
    lines.append("贴线不是诊断工具：它读的是「你对你自己的历史」，裁决在医生与复查。")
    return "\n".join(lines) + "\n", 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description="borderline · 贴线 —— 体检指标的纵向趋势账本")
    p.add_argument("--version", action="version", version=f"{PROG} {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("ledger", help="指标账本 TSV：指标/日期/数值/单位/参考下限/参考上限/备注")
        sp.add_argument("--today", default=None, help="钉死「今天」为 YYYY-MM-DD（默认真实当下）")

    common(sub.add_parser("panel", help="全指标面板与判灯（门禁）"))
    t = sub.add_parser("trend", help="单指标全史趋势")
    common(t)
    t.add_argument("--marker", required=True, help="指标名（如 uric-acid）")
    common(sub.add_parser("next", help="复查节奏清单"))
    common(sub.add_parser("validate", help="账本体检"))
    sub.add_parser("markers", help="常见指标说明")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "markers":
            text, code = cmd_markers()
            print(text, end="")
            return code
        today = (dt.datetime.strptime(args.today, "%Y-%m-%d").date()
                 if getattr(args, "today", None) else dt.date.today())
        ledger = load_ledger(args.ledger, today)
        if args.cmd == "panel":
            text, code = cmd_panel(ledger, today)
        elif args.cmd == "trend":
            text, code = cmd_trend(ledger, args.marker)
        elif args.cmd == "next":
            text, code = cmd_next(ledger, today)
        elif args.cmd == "validate":
            text, code = cmd_validate(ledger, today)
        else:  # pragma: no cover
            raise UsageError(f"未知子命令：{args.cmd}")
        print(text, end="")
        return code
    except UsageError as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 2
    except Refusal as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 3
    except RedLight as e:
        print(str(e), end="")
        return 4


if __name__ == "__main__":
    sys.exit(main())
