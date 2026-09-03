#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""加量红线 · Redline —— 给训练负荷装一个转速表。

伤病不住在跑量里，住在跑量的斜率里。本工具从训练日志（日期/分钟/RPE）
计算 session-RPE 负荷、急性/慢性负荷比（ACWR）、EWMA 变体、单调性与应变，
识别伤停并给出归队爬坡阶梯，还能在你出门之前模拟「按这个计划下周转速多少」。

零依赖：Python 3.8+ 标准库。数据就是一个可手编的 TSV 文件。
"""

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from statistics import mean, pstdev

VERSION = "1.0.0"

# ---------------------------------------------------------------- 常量（方法论默认值，全部可用 CLI 覆盖）
COLS = ["date", "activity", "minutes", "rpe", "notes"]
ACUTE_DAYS = 7            # 急性窗口：最近 7 天
CHRONIC_DAYS = 28         # 慢性窗口：最近 28 天（除以 4 = 平均周负荷，稳定态比率 1.0）
CALIBRATION_DAYS = 21     # 慢性基线校准线：首练不足 21 天拒绝红区判定
LAYOFF_DAYS = 14          # 连续空窗 ≥14 天记一次伤停
FREEZE_DAYS = CHRONIC_DAYS  # 归队后比率判据冻结期（新基线未成形，ACWR 只展示不判区）
ZONE_LOW, ZONE_HIGH, ZONE_RED = 0.8, 1.3, 1.5   # Gabbett 甜区/加速区/红线
MONOTONY_FLAG = 2.0       # Foster 单调性警戒线
EWMA_A = 2.0 / (ACUTE_DAYS + 1)
EWMA_C = 2.0 / (CHRONIC_DAYS + 1)
REBUILD_LADDER = [0.40, 0.60, 0.80, 1.00]  # 归队四周阶梯（占伤前周负荷比例）

ZONE_LABEL = {
    "gray":   "○ 校准/归零",
    "blue":   "🔵 退训区（慢性在流失）",
    "green":  "🟢 甜区",
    "amber":  "🟡 加速区（可以，但别再踩）",
    "red":    "🔴 红线（爆缸风险）",
}


# ---------------------------------------------------------------- 日志解析
class LogError(Exception):
    pass


def parse_session_file(path):
    """解析训练日志 TSV/CSV。返回 (sessions, warnings)。

    会话 = {date, activity, minutes, rpe, notes, load}，load = minutes × rpe。
    表头校验严格（date/minutes/rpe 必需），数据行宽容：坏行汇总一次报全。
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        raise LogError("日志文件是空的：至少需要表头 date/minutes/rpe 和一行记录")
    lines = text.splitlines()
    # 表头所在行决定分隔符：含制表符用 TSV，否则 CSV
    header_line_idx = 0
    for i, ln in enumerate(lines):
        if ln.strip() and not ln.lstrip().startswith("#"):
            header_line_idx = i
            break
    delim = "\t" if "\t" in lines[header_line_idx] else ","
    # 保留真实文件行号（注释/空行不占警告行号）
    kept = [(i, ln) for i, ln in enumerate(lines)
            if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.reader([ln for _i, ln in kept], delimiter=delim)
    try:
        header = next(reader)
    except StopIteration:
        raise LogError("日志文件是空的：至少需要表头 date/minutes/rpe 和一行记录")
    header = [h.strip().lower() for h in header]
    missing = [c for c in ("date", "minutes", "rpe") if c not in header]
    if missing:
        raise LogError("表头缺少必需列：%s（需要 date/minutes/rpe，可选 activity/notes）"
                       % ", ".join(missing))
    idx = {c: (header.index(c) if c in header else None)
           for c in COLS}
    sessions, warnings = [], []
    for row_i, row in enumerate(reader, start=1):
        lineno = kept[row_i][0] + 1        # 1-based 文件行号
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) < len([c for c in idx.values() if c is not None]):
            warnings.append("第 %d 行：列数不足，已跳过" % lineno)
            continue

        def cell(name):
            i = idx[name]
            return row[i].strip() if i is not None and i < len(row) else ""

        try:
            d = date.fromisoformat(cell("date"))
        except ValueError:
            warnings.append("第 %d 行：日期 %r 不是 ISO 格式（YYYY-MM-DD），已跳过"
                            % (lineno, cell("date")))
            continue
        try:
            minutes = float(cell("minutes"))
            rpe = float(cell("rpe"))
        except ValueError:
            warnings.append("第 %d 行：minutes/rpe 不是数字，已跳过" % lineno)
            continue
        if minutes < 0 or rpe < 0 or rpe > 10:
            warnings.append("第 %d 行：minutes 不能为负、rpe 须在 0–10，已跳过" % lineno)
            continue
        if minutes == 0 or rpe == 0:
            warnings.append("第 %d 行：minutes/rpe 为 0，该行不产生负荷，已跳过" % lineno)
            continue
        sessions.append({
            "date": d,
            "activity": cell("activity") or "训练",
            "minutes": minutes,
            "rpe": rpe,
            "notes": cell("notes"),
            "load": minutes * rpe,
        })
    if not sessions:
        raise LogError("日志里没有可用会话（%d 条警告）" % len(warnings))
    sessions.sort(key=lambda s: s["date"])
    return sessions, warnings


def daily_loads(sessions):
    """按日聚合负荷（同日多练相加，double 日常见）。"""
    daily = {}
    for s in sessions:
        daily[s["date"]] = daily.get(s["date"], 0.0) + s["load"]
    return daily


# ---------------------------------------------------------------- 负荷数学
def window_sum(daily, end_d, n):
    """[end_d-n+1, end_d] 内的总负荷（缺勤日 = 0）。"""
    return sum(daily.get(end_d - timedelta(days=k), 0.0) for k in range(n))


def acute_at(daily, d):
    return window_sum(daily, d, ACUTE_DAYS)


def chronic_weekly_at(daily, d):
    """慢性负荷 = 最近 28 天总负荷 ÷ 4（平均周负荷，与急性同量纲，稳定态比率 1.0）。"""
    return window_sum(daily, d, CHRONIC_DAYS) / (CHRONIC_DAYS / ACUTE_DAYS)


def acwr_at(daily, d):
    """返回 (acute, chronic_weekly, acwr or None)。慢性为 0 → None（归零）。"""
    a = acute_at(daily, d)
    c = chronic_weekly_at(daily, d)
    return a, c, (a / c if c > 0 else None)


def zone_of(acwr, calibrated=True, frozen=False):
    if acwr is None:
        return "gray"
    if not calibrated or frozen:
        return "gray"
    if acwr > ZONE_RED:
        return "red"
    if acwr > ZONE_HIGH:
        return "amber"
    if acwr >= ZONE_LOW:
        return "green"
    return "blue"


def ewma_series(daily, end_d):
    """Williams et al. 2017 的 EWMA 变体。

    从首练日起逐日迭代：ewma_t = λ·load_t + (1-λ)·ewma_{t-1}，初值 = 首日负荷。
    返回 {date: (ewma_acute, ewma_chronic)}，键只覆盖有负荷或有迭代的每一天。
    """
    if not daily:
        return {}
    first = min(daily)
    ew_a = ew_c = None
    out = {}
    d = first
    while d <= end_d:
        load = daily.get(d, 0.0)
        if ew_a is None:
            ew_a = ew_c = load
        else:
            ew_a = EWMA_A * load + (1 - EWMA_A) * ew_a
            ew_c = EWMA_C * load + (1 - EWMA_C) * ew_c
        out[d] = (ew_a, ew_c)
        d += timedelta(days=1)
    return out


def monotony_strain(daily_loads_of_week):
    """Foster 单调性 = 周内日负荷均值/标准差；应变 = 周总量 × 单调性。

    标准差为 0 且均值 > 0（每天一模一样）→ 单调性无穷大，返回 (inf, inf)。
    """
    loads = list(daily_loads_of_week)
    total = sum(loads)
    if total <= 0:
        return 0.0, 0.0
    sd = pstdev(loads) if len(loads) > 1 else 0.0
    if sd == 0:
        return float("inf"), float("inf")
    mon = mean(loads) / sd
    return mon, total * mon


# ---------------------------------------------------------------- 伤停与归队
def find_layoffs(daily, layoff_days=LAYOFF_DAYS):
    """连续空窗 ≥ layoff_days 记一次伤停。返回 [(last_active_before, first_active_after)]。"""
    active = sorted(daily)
    if len(active) < 2:
        return []
    gaps = []
    for prev, nxt in zip(active, active[1:]):
        gap = (nxt - prev).days - 1
        if gap >= layoff_days:
            gaps.append((prev, nxt))
    return gaps


def rebuild_ladder(pre_chronic_weekly):
    """归队四周阶梯：40/60/80/100% × 伤前慢性周负荷。

    伤停后慢性基线已流失，任何比率判据都会数学性爆表——所以重建期不用 ACWR，
    用绝对阶梯，四周后新基线成形、判据恢复。
    """
    rows = []
    for i, pct in enumerate(REBUILD_LADDER, start=1):
        rows.append({
            "week": i,
            "pct": pct,
            "week_load": pre_chronic_weekly * pct,
        })
    return rows


def freeze_until(layoffs):
    """最近一次伤停归队日的判据冻结截止日（无伤停则 None）。"""
    if not layoffs:
        return None
    return max(ret for _prev, ret in layoffs) + timedelta(days=FREEZE_DAYS - 1)


def is_frozen(d, layoffs):
    """d 落在任一次归队后的判据冻结窗口内（归队日 .. 归队+FREEZE_DAYS-1）。"""
    for _prev, ret in layoffs:
        if ret <= d <= ret + timedelta(days=FREEZE_DAYS - 1):
            return True
    return False


# ---------------------------------------------------------------- 报告
def _fmt(x, nd=0):
    if x == float("inf"):
        return "∞"
    return ("%." + str(nd) + "f") % x


def iso_week_monday(d):
    return d - timedelta(days=d.weekday())


def weekly_rows(daily, first_d, as_of):
    """ISO 周表：周负荷/日均/单调性/应变/周末 ACWR/区。"""
    if not daily:
        return []
    weeks = []
    mon = iso_week_monday(first_d)
    last_mon = iso_week_monday(as_of)
    while mon <= last_mon:
        sun = mon + timedelta(days=6)
        eff_end = min(sun, as_of)
        days = [mon + timedelta(days=k) for k in range((eff_end - mon).days + 1)]
        loads = [daily.get(x, 0.0) for x in days]
        total = sum(loads)
        mony, strain = monotony_strain(loads)
        end_d = eff_end
        a, c, ratio = acwr_at(daily, end_d)
        weeks.append({
            "monday": mon, "sunday": sun, "effective_end": end_d,
            "elapsed_days": len(days),
            "total": total,
            "daily_avg": total / len(days) if days else 0.0,
            "monotony": mony, "strain": strain,
            "acute": a, "chronic": c, "acwr": ratio,
        })
        mon += timedelta(days=7)
    return weeks


def build_report(daily, warnings=(), as_of=None):
    sessions_days = sorted(daily)
    first_d, last_d = sessions_days[0], sessions_days[-1]
    as_of = as_of or last_d
    layoffs = find_layoffs(daily)
    calibrated = (as_of - first_d).days >= CALIBRATION_DAYS
    frozen_end = freeze_until(layoffs)
    frozen_now = is_frozen(as_of, layoffs)

    a, c, ratio = acwr_at(daily, as_of)
    zone = zone_of(ratio, calibrated=calibrated, frozen=frozen_now)
    ew = ewma_series(daily, as_of).get(as_of, (0.0, 0.0))
    ew_ratio = ew[0] / ew[1] if ew[1] > 0 else None
    ew_zone = zone_of(ew_ratio, calibrated=calibrated, frozen=frozen_now)

    weeks = weekly_rows(daily, first_d, as_of)
    for w in weeks:
        w["calibrated"] = (w["effective_end"] - first_d).days >= CALIBRATION_DAYS
        w["frozen"] = is_frozen(w["effective_end"], layoffs)
        w["zone"] = zone_of(w["acwr"], calibrated=w["calibrated"],
                            frozen=w["frozen"])
        flags = []
        if w["zone"] == "red":
            flags.append("🔴 ACWR %.2f 超红线（>%.1f）" % (w["acwr"], ZONE_RED))
        elif w["zone"] == "amber":
            flags.append("🟡 ACWR %.2f 进入加速区" % w["acwr"])
        if w["monotony"] == float("inf"):
            flags.append("⚠️ 单调性 ∞（每天一模一样，无恢复差异）")
        elif w["monotony"] > MONOTONY_FLAG:
            flags.append("⚠️ 单调性 %.1f > %.1f（高单调=低 variation，恢复被吃掉）"
                         % (w["monotony"], MONOTONY_FLAG))
        if w["frozen"] and w["effective_end"] >= (layoffs[-1][1] if layoffs else first_d):
            flags.append("⏳ 重建期：比率判据冻结，只看绝对量")
        w["flags"] = flags

    rebuild = None
    if layoffs:
        last_prev, last_ret = layoffs[-1]
        # 锚点 = 伤停前最后一次训练日：那时的慢性基线才是「伤前水平」
        pre_c = chronic_weekly_at(daily, last_prev)
        # 伤前慢性周负荷取伤停前最近一个有数据的整周更稳：直接用 28 天窗均值
        rebuild = {
            "layoffs": [{"last_active": p.isoformat(), "returned": r.isoformat(),
                         "days": (r - p).days - 1}
                        for p, r in layoffs],
            "pre_chronic_weekly": pre_c,
            "ladder": rebuild_ladder(pre_c),
            "freeze_until": (last_ret + timedelta(days=FREEZE_DAYS - 1)).isoformat(),
        }

    return {
        "as_of": as_of.isoformat(),
        "first_day": first_d.isoformat(),
        "days_covered": (as_of - first_d).days + 1,
        "sessions": len([d for d in sessions_days if d <= as_of]),
        "calibrated": calibrated,
        "calibration_shortfall": max(0, CALIBRATION_DAYS - (as_of - first_d).days),
        "current": {"acute": a, "chronic": c, "acwr": ratio, "zone": zone,
                    "ewma_acute": ew[0], "ewma_chronic": ew[1],
                    "ewma_acwr": ew_ratio, "ewma_zone": ew_zone,
                    "frozen": frozen_now,
                    "freeze_until": frozen_end.isoformat() if frozen_end else None},
        "weeks": weeks,
        "layoffs": [{"last_active": p.isoformat(), "returned": r.isoformat(),
                     "days": (r - p).days - 1} for p, r in layoffs],
        "rebuild": rebuild,
        "warnings": list(warnings),
    }


def render_report(rep):
    out = []
    p = out.append
    p("加量红线 · Redline v%s —— 训练负荷转速表" % VERSION)
    p("=" * 56)
    p("")
    if not rep["calibrated"]:
        p("【校准状态】⏳ 未校准")
        p("首次记录 %s，数据截至 %s（%d 天）。慢性基线需要 ≥%d 天才可信，"
          "还差 %d 天——这段时间的 ACWR 只展示、不判区。"
          % (rep["first_day"], rep["as_of"], rep["days_covered"],
             CALIBRATION_DAYS, rep["calibration_shortfall"]))
    else:
        p("【校准状态】✓ 慢性基线已校准（首练 %s，跨度 %d 天 ≥ %d 天）"
          % (rep["first_day"], rep["days_covered"], CALIBRATION_DAYS))
    p("")
    cur = rep["current"]
    p("【当前转速】（截至 %s）" % rep["as_of"])
    if cur["acwr"] is None:
        p("慢性负荷为 0：身体已归零。这不是比率问题，是重启问题——看下方重建阶梯。")
    else:
        if cur["frozen"]:
            cur_label = "⏳ 重建期（判据冻结）"
        elif not rep["calibrated"]:
            cur_label = "… 校准中（不判区）"
        else:
            cur_label = ZONE_LABEL[cur["zone"]]
        p("急性负荷(7天) %s ｜ 慢性负荷(28天均值/周) %s ｜ ACWR = %.2f → %s"
          % (_fmt(cur["acute"]), _fmt(cur["chronic"]), cur["acwr"], cur_label))
        if not rep["calibrated"]:
            p("（未校准：以上数字仅供参考，不做红区判定）")
        if cur["frozen"] and cur.get("freeze_until"):
            p("（重建期冻结中：比率判据在 %s 前不判区，只看绝对负荷）"
              % cur["freeze_until"])
    if cur["ewma_chronic"] > 0 and cur["ewma_acwr"] is not None:
        ew_label = ("⏳ 重建期" if cur["frozen"]
                    else "… 校准中" if not rep["calibrated"]
                    else ZONE_LABEL[cur["ewma_zone"]])
        p("EWMA 变体：急性 %s / 慢性 %s / ACWR = %.2f → %s"
          % (_fmt(cur["ewma_acute"]), _fmt(cur["ewma_chronic"]),
             cur["ewma_acwr"], ew_label))
        if (not cur["frozen"] and rep["calibrated"] and cur["acwr"] is not None
                and cur["ewma_acwr"] - cur["acwr"] > 0.15):
            p("⚠️ EWMA 显著高于滚动均值：最近几天在急踩油门。")
    p("")
    p("【周表】（ISO 周；单调性/应变按已过天数；ACWR 在周末结算）")
    p("%-16s %8s %6s %7s %8s %7s  %s"
      % ("周", "周负荷", "日均", "单调性", "应变", "ACWR", "区"))
    for w in rep["weeks"]:
        mon_s = w["monday"].strftime("%m/%d")
        sun_s = w["sunday"].strftime("%m/%d")
        acwr_s = "%.2f" % w["acwr"] if w["acwr"] is not None else "—"
        if w["frozen"]:
            acwr_s += "*"      # 判据冻结：新基线未成形
            zone_s = "⏳"
        elif not w["calibrated"]:
            acwr_s += "?"      # 基线校准中
            zone_s = "…"
        else:
            zone_s = ZONE_LABEL[w["zone"]].split()[0]
        p("%s–%s %8s %6s %7s %8s %7s  %s"
          % (mon_s, sun_s,
             _fmt(w["total"]), _fmt(w["daily_avg"]),
             _fmt(w["monotony"], 1), _fmt(w["strain"]),
             acwr_s, zone_s))
    p("  （? = 基线校准中不判区；* = 重建期判据冻结；🔵🟢🟡🔴 = 退训/甜区/加速/红线）")
    p("")
    flags = [(w, f) for w in rep["weeks"] for f in w["flags"]]
    if flags:
        p("【旗帜】")
        for w, f in flags:
            p("  %s–%s  %s"
              % (w["monday"].strftime("%m/%d"), w["sunday"].strftime("%m/%d"), f))
        p("")
    if rep["rebuild"]:
        rb = rep["rebuild"]
        p("【伤停与归队】")
        for lo in rb["layoffs"]:
            p("  检测到伤停：%s 之后空窗 %d 天，%s 归队"
              % (lo["last_active"], lo["days"], lo["returned"]))
        p("  伤前慢性周负荷 ≈ %s。伤停后基线已流失，比率判据（ACWR）会数学性爆表，"
          % _fmt(rb["pre_chronic_weekly"]))
        p("  所以重建期不用比率，用绝对阶梯（占伤前周负荷）：")
        for r in rb["ladder"]:
            p("    第 %d 周 %3.0f%% → 周负荷 ≈ %s" % (r["week"], r["pct"] * 100,
                                                      _fmt(r["week_load"])))
        p("  判据恢复日：%s（归队 + %d 天，新基线成形）"
          % (rb["freeze_until"], FREEZE_DAYS))
        p("")
    p("【建议】")
    for line in advice_lines(rep):
        p("  · %s" % line)
    if rep["warnings"]:
        p("")
        p("【日志警告】%d 条" % len(rep["warnings"]))
        for w in rep["warnings"]:
            p("  - %s" % w)
    return "\n".join(out)


def advice_lines(rep):
    cur = rep["current"]
    lines = []
    if not rep["calibrated"]:
        lines.append("基线未校准：保持当前节奏 %d 天，让四周基线成形，再谈加量。"
                     % rep["calibration_shortfall"])
        return lines
    if cur["frozen"]:
        rb = rep["rebuild"]
        if rb:
            lines.append("重建期：按阶梯走，本周绝对负荷别超过上一周太多；"
                         "判据 %s 恢复后再看 ACWR。" % rb["freeze_until"])
        else:
            lines.append("重建期：先用绝对量控制节奏，比率判据即将恢复。")
        return lines
    if cur["acwr"] is None:
        lines.append("慢性负荷归零：从伤前周负荷的 40% 重新起步，四周阶梯见上。")
    elif cur["zone"] == "red":
        lines.append("本周已在红线上：把剩余计划砍到只保留恢复性训练，"
                     "让急性负荷落回甜区。")
    elif cur["zone"] == "amber":
        lines.append("加速区：本周到此为止，下周回甜区再谈加量——加量是周的尺度，"
                     "不是天的冲动。")
    elif cur["zone"] == "blue":
        lines.append("退训区：慢性负荷在流失。温和回升到甜区（ACWR ≥ %.1f），"
                     "别一步跳回去。" % ZONE_LOW)
    else:
        lines.append("甜区：这是可以持续变强的区间。下周加量幅度 ≤ 10%% 仍会留在甜区。")
    top = [w for w in rep["weeks"] if w["zone"] == "red"]
    if top:
        w = top[-1]
        lines.append("历史红线周 %s–%s（ACWR %.2f）：如果那之后有伤病/停训，"
                     "它就是你的个人证据。"
                     % (w["monday"].strftime("%m/%d"), w["sunday"].strftime("%m/%d"),
                        w["acwr"]))
    hi_mon = [w for w in rep["weeks"]
              if w["monotony"] not in (0.0, float("inf"))
              and w["monotony"] > MONOTONY_FLAG]
    if hi_mon:
        lines.append("最近存在高单调周（>%.1f）：一样的负荷、一样的节奏 = 恢复被吃掉，"
                     "穿插一个真正的轻松日。" % MONOTONY_FLAG)
    return lines


# ---------------------------------------------------------------- 计划模拟
def parse_plan_sessions(specs):
    """--session "YYYY-MM-DD,minutes,rpe[,activity]" 列表 → 会话列表。"""
    out = []
    for spec in specs:
        parts = [p.strip() for p in spec.split(",")]
        if len(parts) < 3:
            raise LogError("plan 会话格式：\"YYYY-MM-DD,分钟,RPE[,项目]\"，收到：%r" % spec)
        d = date.fromisoformat(parts[0])          # 让 ValueError 冒泡成可读报错
        minutes = float(parts[1])
        rpe = float(parts[2])
        if minutes <= 0 or not (0 < rpe <= 10):
            raise LogError("plan 会话需要 分钟>0、0<RPE≤10：%r" % spec)
        out.append({"date": d, "activity": parts[3] if len(parts) > 3 else "计划",
                    "minutes": minutes, "rpe": rpe, "notes": "",
                    "load": minutes * rpe})
    out.sort(key=lambda s: s["date"])
    return out


def headroom_exact(daily, d, cap=ZONE_HIGH):
    """在 d 结算时还能加多少负荷而 ACWR 不超 cap（把额外负荷同时计入急/慢性）。

    (A+X) / ((S28+X)/4) ≤ cap  →  X = (cap·S28 − 4A) / (4 − cap)
    """
    a = acute_at(daily, d)
    s28 = window_sum(daily, d, CHRONIC_DAYS)
    denom = 4 - cap
    if denom <= 0:
        return None
    x = (cap * s28 - 4 * a) / denom
    return max(0.0, x)


def build_plan(daily_plan, first_d, sessions_planned, layoffs=()):
    # 计划负荷自己合并（调用者传纯日志日负荷即可），末日余额在合并后计算
    daily = dict(daily_plan)
    for s in sessions_planned:
        daily[s["date"]] = daily.get(s["date"], 0.0) + s["load"]
    rows = []
    for s in sessions_planned:
        d = s["date"]
        a, c, ratio = acwr_at(daily, d)
        calibrated = (d - first_d).days >= CALIBRATION_DAYS
        frozen = is_frozen(d, layoffs)
        rows.append({
            "date": d, "activity": s["activity"],
            "minutes": s["minutes"], "rpe": s["rpe"], "load": s["load"],
            "acute": a, "chronic": c, "acwr": ratio,
            "zone": zone_of(ratio, calibrated=calibrated, frozen=frozen),
            "calibrated": calibrated, "frozen": frozen,
        })
    final = rows[-1]["date"] if rows else None
    head = headroom_exact(daily, final) if final else None
    return {"rows": rows, "headroom": head, "final_day": final.isoformat() if final else None}


def render_plan(plan, warnings=()):
    out = []
    p = out.append
    p("加量红线 · 计划模拟 —— 先看转速，再出门")
    p("=" * 56)
    p("")
    p("%-12s %-10s %6s %4s %8s %8s %7s  %s"
      % ("日期", "项目", "分钟", "RPE", "急性", "慢性", "ACWR", "判定"))
    for r in plan["rows"]:
        acwr_s = "%.2f" % r["acwr"] if r["acwr"] is not None else "—"
        if r["frozen"]:
            acwr_s += "*"
            zone_s = "⏳"
        elif not r["calibrated"]:
            acwr_s += "?"
            zone_s = "…"
        else:
            zone_s = ZONE_LABEL[r["zone"]].split()[0]
        p("%-12s %-10s %6s %4s %8s %8s %7s  %s"
          % (r["date"].isoformat(), r["activity"], _fmt(r["minutes"]),
             _fmt(r["rpe"], 1), _fmt(r["acute"]), _fmt(r["chronic"]),
             acwr_s, zone_s))
    p("")
    reds = [r for r in plan["rows"] if r["zone"] == "red"]
    ambers = [r for r in plan["rows"] if r["zone"] == "amber"]
    uncal = [r for r in plan["rows"] if not r["calibrated"] and not r["frozen"]]
    frozen = [r for r in plan["rows"] if r["frozen"]]
    if frozen:
        p("⏳ 有 %d 个计划日落在重建期冻结窗内：比率判据不判区，按绝对阶梯控制量。"
          % len(frozen))
    if uncal:
        p("⚠️ 有 %d 个计划日仍在基线校准期：ACWR 只展示、不判区（带 ? 的行）。"
          % len(uncal))
    if reds:
        p("🔴 这份计划有 %d 天踩红线（ACWR > %.1f）。把它拆了："
          "砍掉一场或把长课换短课，别用意志力和统计作对。" % (len(reds), ZONE_RED))
    elif ambers:
        p("🟡 计划落在加速区但没有踩线：只保留一个刺激课，其余照常。")
    else:
        p("🟢 计划全程在甜区：按表执行。")
    h = plan["headroom"]
    if h is not None:
        if h <= 0:
            p("余额：0。这份计划已经把甜区用满了，一点都别再加。")
        else:
            p("余额：到期末还能再加 ≤ %.0f 负荷单位（如按 RPE 6 约 %.0f 分钟）而 ACWR 仍 ≤ %.1f。"
              % (h, h / 6.0, ZONE_HIGH))
    if warnings:
        p("")
        p("【日志警告】")
        for w in warnings:
            p("  - %s" % w)
    return "\n".join(out)


# ---------------------------------------------------------------- 校验
def cmd_validate(args):
    try:
        sessions, warnings = parse_session_file(args.log)
    except (LogError, OSError) as e:
        print("✗ %s" % e)
        return 1
    daily = daily_loads(sessions)
    days = sorted(daily)
    span = (days[-1] - days[0]).days + 1
    print("✓ 日志可用：%d 条会话 / %d 个训练日，跨度 %d 天（%s → %s）"
          % (len(sessions), len(days), span, days[0], days[-1]))
    total = sum(daily.values())
    print("  总负荷 %s（分钟×RPE）；日均 %s" % (_fmt(total), _fmt(total / span)))
    for w in warnings:
        print("  警告：%s" % w)
    if warnings:
        print("  坏行已跳过、不影响分析；修好它们能让历史更完整。")
    return 0


def cmd_report(args):
    try:
        sessions, warnings = parse_session_file(args.log)
    except (LogError, OSError) as e:
        print("✗ %s" % e, file=sys.stderr)
        return 1
    daily = daily_loads(sessions)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    rep = build_report(daily, warnings=warnings, as_of=as_of)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2,
                         default=lambda o: o.isoformat()))
    else:
        print(render_report(rep))
    if args.strict:
        reds = [w for w in rep["weeks"] if w["zone"] == "red"]
        cur_red = rep["current"]["zone"] == "red"
        if reds or cur_red:
            print("strict：存在红线周，退出码 2", file=sys.stderr)
            return 2
    return 0


def cmd_plan(args):
    try:
        sessions, warnings = parse_session_file(args.log)
        planned = parse_plan_sessions(args.session)
    except (LogError, OSError, ValueError) as e:
        print("✗ %s" % e, file=sys.stderr)
        return 1
    daily = daily_loads(sessions)
    layoffs = find_layoffs(daily)
    first_d = min(sorted(daily))
    plan = build_plan(daily, first_d, planned, layoffs=layoffs)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2,
                         default=lambda o: o.isoformat()))
    else:
        print(render_plan(plan, warnings))
    if args.strict and any(r["zone"] == "red" for r in plan["rows"]):
        print("strict：计划踩红线，退出码 2", file=sys.stderr)
        return 2
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="redline",
        description="加量红线 · Redline —— 训练负荷转速表（伤病不住在跑量里，住在斜率里）")
    ap.add_argument("--version", action="version", version="redline " + VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_rep = sub.add_parser("report", help="训练负荷转速报告（ACWR/EWMA/单调性/伤停重建）")
    ap_rep.add_argument("log", help="训练日志 TSV/CSV（date/minutes/rpe 必需）")
    ap_rep.add_argument("--as-of", help="把分析截止到指定日期（默认最后一条记录）")
    ap_rep.add_argument("--json", action="store_true", help="输出 JSON")
    ap_rep.add_argument("--strict", action="store_true",
                        help="存在红线周时退出码 2（供自动化闸门）")
    ap_rep.set_defaults(func=cmd_report)

    ap_plan = sub.add_parser("plan", help="出门之前：模拟未来会话对转速的影响")
    ap_plan.add_argument("log", help="训练日志 TSV/CSV")
    ap_plan.add_argument("--session", action="append", default=[],
                         metavar='"YYYY-MM-DD,分钟,RPE[,项目]"',
                         help="计划会话，可重复多次")
    ap_plan.add_argument("--json", action="store_true", help="输出 JSON")
    ap_plan.add_argument("--strict", action="store_true",
                         help="计划踩红线时退出码 2")
    ap_plan.set_defaults(func=cmd_plan)

    ap_val = sub.add_parser("validate", help="日志格式体检")
    ap_val.add_argument("log", help="训练日志 TSV/CSV")
    ap_val.set_defaults(func=cmd_validate)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
