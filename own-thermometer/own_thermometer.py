#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冷暖自知 · Own Thermometer — 体感穿衣账本（zero-dependency CLI）.

天气预报只播空气的温度，通用穿衣表写的是「平均人」的刻度；而你每次出门后的
冷热后悔从不被记录，同样的错年年重演。本件把手编体感账本（TSV：日期/预报
低温/高温/天气/穿着/体感 −2..+2）读成一本皮肤账，从你自己的历史里长出四样
没人替你算过的东西：个人舒适带、单品实测温区、组合胜率、失误解剖——以及
明晨出门前的一次裁决。

账本自锚定：所有「今天」都以账本末日为锚（可用 --today 显式钉死），同一本
账在任何机器任何时间跑出逐字节一致的结果。

Exit codes: 0 OK · 1 RISKY · 2 账本损坏 · 3 THIN/拒答 · 4 红线（DEAD/WASTELAND/连败）
"""

import argparse
import math
import os
import sys
from datetime import date, datetime, timedelta

FEEL_MIN, FEEL_MAX = -2, 2
FEEL_LABEL = {-2: "很冷", -1: "偏冷", 0: "刚好", 1: "偏热", 2: "很热"}
CONDS = ("", "sunny", "cloudy", "rain", "snow")
HEADER = "date\ttmin\ttmax\tcond\toutfit\tfeel"
PROG = "冷暖自知 · Own Thermometer"


class LedgerError(Exception):
    """账本损坏：解析层拒绝，exit 2。"""


class Day(object):
    __slots__ = ("d", "tmin", "tmax", "cond", "outfit", "feel", "tmean")

    def __init__(self, d, tmin, tmax, cond, outfit, feel):
        self.d = d
        self.tmin = tmin
        self.tmax = tmax
        self.cond = cond
        self.outfit = outfit          # list[str]
        self.feel = feel              # int −2..+2
        self.tmean = (tmin + tmax) / 2.0

    @property
    def combo(self):
        return "+".join(self.outfit)


# ------------------------------------------------------------------ parsing

def _parse_date(text, lineno):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise LedgerError("第 %d 行: 日期无法解析: %r" % (lineno, text))


def _parse_float(text, lineno, what):
    try:
        v = float(text)
    except ValueError:
        raise LedgerError("第 %d 行: %s 不是数字: %r" % (lineno, what, text))
    if math.isnan(v) or math.isinf(v):
        raise LedgerError("第 %d 行: %s 非法: %r" % (lineno, what, text))
    return v


def load_ledger(path):
    """读入体感账本。返回 (days, ledger_end)。账本末日即自锚定的「今天」。"""
    if not os.path.exists(path):
        raise LedgerError("找不到账本: %s" % path)
    days = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line == HEADER or line.startswith("date\t"):
                continue  # 表头行，宽容跳过
            cols = line.split("\t")
            if len(cols) != 6:
                raise LedgerError("第 %d 行: 应为 6 列 %r，实得 %d 列"
                                  % (lineno, HEADER, len(cols)))
            d = _parse_date(cols[0].strip(), lineno)
            tmin = _parse_float(cols[1], lineno, "tmin")
            tmax = _parse_float(cols[2], lineno, "tmax")
            cond = cols[3].strip()
            if cond not in CONDS:
                raise LedgerError("第 %d 行: cond 只允许 %s，实得 %r"
                                  % (lineno, "|".join(c or "(空)" for c in CONDS), cond))
            if tmin > tmax:
                raise LedgerError("第 %d 行: tmin %g > tmax %g，预报不会倒着下"
                                  % (lineno, tmin, tmax))
            outfit = [p.strip() for p in cols[4].strip().split("+")]
            if not outfit or any(not p for p in outfit):
                raise LedgerError("第 %d 行: outfit 为空或含空单品（用 + 连接）" % lineno)
            feel_text = cols[5].strip()
            try:
                feel = int(feel_text)
            except ValueError:
                raise LedgerError("第 %d 行: feel 必须是整数 −2..+2，实得 %r"
                                  % (lineno, feel_text))
            if not FEEL_MIN <= feel <= FEEL_MAX:
                raise LedgerError("第 %d 行: feel 越界 %d（允许 −2..+2）"
                                  % (lineno, feel))
            days.append(Day(d, tmin, tmax, cond, outfit, feel))
    if not days:
        raise LedgerError("账本为空: %s" % path)
    seen = set()
    for day in days:
        if day.d in seen:
            raise LedgerError("日期重复: %s——一天只有一个早晨" % day.d.isoformat())
        seen.add(day.d)
    days.sort(key=lambda x: x.d)
    return days, days[-1].d


def resolve_today(days, today_text):
    if today_text:
        try:
            return datetime.strptime(today_text, "%Y-%m-%d").date()
        except ValueError:
            raise LedgerError("--today 无法解析: %r" % today_text)
    return days[-1].d


# ------------------------------------------------------------------ stats

def percentile(sorted_vals, p):
    """线性插值分位数（与教科书定义一致），输入必须已排序。"""
    if not sorted_vals:
        raise ValueError("percentile of empty")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return float(sorted_vals[int(k)])
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def tmeans(days):
    return sorted(d.tmean for d in days)


def win_rate(records):
    """feel=0 占比；空列表返回 None。"""
    if not records:
        return None
    return sum(1 for r in records if r.feel == 0) / float(len(records))


def group_combo(days):
    table = {}
    for d in days:
        table.setdefault(d.combo, []).append(d)
    return table


def group_garment(days):
    table = {}
    for d in days:
        for name in d.outfit:
            table.setdefault(name, []).append(d)
    return table


def month_key(d):
    return d.d.strftime("%Y-%m")


def tail_streak(records, min_streak):
    """按日期排序后，末尾连续 |feel|>=1 且同向的长度；达到 min_streak 才返回长度。"""
    if not records:
        return 0
    seq = sorted(records, key=lambda x: x.d)
    sign = None
    n = 0
    for r in reversed(seq):
        if r.feel == 0:
            break
        s = 1 if r.feel > 0 else -1
        if sign is None:
            sign = s
            n = 1
        elif s == sign:
            n += 1
        else:
            break
    return n if n >= min_streak else 0


def bucket_of(tmean, width=3.0):
    return int(math.floor(tmean / width)) * width


# ------------------------------------------------------------------ report

def cmd_report(args):
    days, end = load_ledger(args.ledger)
    lname = os.path.basename(args.ledger)
    today = resolve_today(days, args.today)
    if len(days) < args.min_days:
        print("THIN：账本只有 %d 天（门槛 %d）——样本不足，拒绝给一个没有分母的舒适带。"
              % (len(days), args.min_days))
        print("继续记：每天一行（预报温度 + 穿了什么 + 冷热感受），满 %d 天再来。"
              % args.min_days)
        return 3
    n = len(days)
    ok_days = [d for d in days if d.feel == 0]
    miss_days = [d for d in days if d.feel != 0]
    cold = [d for d in miss_days if d.feel < 0]
    hot = [d for d in miss_days if d.feel > 0]
    span0, span1 = days[0].d.isoformat(), days[-1].d.isoformat()

    print("%s — 体感总账 report" % PROG)
    print("账本 %s · 记录 %d 天 · 跨度 %s → %s · --today %s%s"
          % (lname, n, span0, span1, today.isoformat(),
             "" if args.today else "（账本末日锚定）"))
    print("温度口径 = 出门前抄的预报 (tmin+tmax)/2；体感 = 你的主报告 −2..+2，账本只把它当声称")
    print()

    # §1 温度地形：失误率按 3°C 桶分布
    print("§1 温度地形 —— 失误率按 3°C 桶分布（桶 n≥%d 才判）" % args.min_bucket)
    b3 = {}
    for d in days:
        b3.setdefault(bucket_of(d.tmean), []).append(d)
    judged_b = []
    for lo in sorted(b3):
        rec = b3[lo]
        rate = sum(1 for x in rec if x.feel != 0) / float(len(rec))
        judged_b.append((lo, len(rec), rate))
    comfort_line, mine_line = 0.20, 0.5
    comfort_run = best_comfort = []
    mine_run = best_mine = []
    for lo, cnt, rate in judged_b:
        if cnt < args.min_bucket:
            if len(comfort_run) > len(best_comfort):
                best_comfort = comfort_run
            if len(mine_run) > len(best_mine):
                best_mine = mine_run
            comfort_run, mine_run = [], []
            continue
        if rate <= comfort_line:
            comfort_run.append(lo)
        else:
            if len(comfort_run) > len(best_comfort):
                best_comfort = comfort_run
            comfort_run = []
        if rate >= mine_line:
            mine_run.append(lo)
        else:
            if len(mine_run) > len(best_mine):
                best_mine = mine_run
            mine_run = []
    if len(comfort_run) > len(best_comfort):
        best_comfort = comfort_run
    if len(mine_run) > len(best_mine):
        best_mine = mine_run
    for lo, cnt, rate in judged_b:
        if cnt < args.min_bucket:
            print("  [%3.0f,%3.0f)  (n=%2d)  THIN 不判" % (lo, lo + 3.0, cnt))
            continue
        bar = "█" * int(round(rate * 8))
        tag = ""
        if best_mine and lo in best_mine:
            tag = "  ← 雷区"
        elif best_comfort and lo in best_comfort:
            tag = "  ← 舒适段"
        print("  [%3.0f,%3.0f)  (n=%2d)  %-8s %5.1f%%%s" % (lo, lo + 3.0, cnt, bar, rate * 100.0, tag))
    if best_comfort:
        print("  舒适段 [%.0f, %.0f)°C：连续 %d 桶失误率 ≤%d%% —— 这段温度你闭眼穿都对"
              % (best_comfort[0], best_comfort[-1] + 3.0, len(best_comfort), comfort_line * 100))
    else:
        print("  没有舒适段——没有任何连续温带失误率 ≤%d%%，你的账本还没有稳态" % (comfort_line * 100))
    if best_mine:
        print("  雷区 [%.0f, %.0f)°C：连续 %d 桶失误率 ≥%d%% —— 这个温度带你的衣柜没有答案"
              % (best_mine[0], best_mine[-1] + 3.0, len(best_mine), mine_line * 100))
    else:
        print("  没有雷区（失误率 ≥%d%% 的连续温带）——没有哪个温度带在系统性地收拾你" % (mine_line * 100))
    print()

    # §2 失误账
    print("§2 失误账 —— 冷热后悔第一次有了分母")
    miss_rate = len(miss_days) / float(n)
    ratio = (len(cold) / float(len(hot)) if hot else float("inf"))
    if not hot:
        tendency = "你从没热过——衣柜全线偏薄"
    elif len(cold) > len(hot) * 1.25:
        tendency = "穿少的乐观税"
    elif len(hot) > len(cold) * 1.25:
        tendency = "穿多的怕冷税"
    else:
        tendency = "冷热两线开花：失误不在方向，在温度带"
    print("  失误 %d/%d = %.1f%%（冷 %d · 热 %d，冷:热 = %s —— %s）"
          % (len(miss_days), n, miss_rate * 100.0, len(cold), len(hot),
             ("%.1f:1" % ratio) if hot else "∞:1", tendency))
    buckets = {f: sum(1 for d in days if d.feel == f) for f in range(FEEL_MIN, FEEL_MAX + 1)}
    print("  %s（桶和 %d = 记录 %d ✓）"
          % (" · ".join("%d %s %d" % (f, FEEL_LABEL[f], buckets[f])
                        for f in range(FEEL_MIN, FEEL_MAX + 1)),
             sum(buckets.values()), n))
    rain = [d for d in days if d.cond == "rain"]
    dry = [d for d in days if d.cond != "rain"]
    if len(rain) >= 5 and len(dry) >= 5:
        r_rate = sum(1 for d in rain if d.feel != 0) / float(len(rain))
        d_rate = sum(1 for d in dry if d.feel != 0) / float(len(dry))
        print("  雨天失误率 %.1f%%（n=%d）vs 干天 %.1f%%（n=%d）→ 湿冷/湿闷多罚 %+.1fpp"
              % (r_rate * 100.0, len(rain), d_rate * 100.0, len(dry),
                 (r_rate - d_rate) * 100.0))
    else:
        print("  雨天对照：n<5 不比（rain=%d）——宁可沉默，不比没有分母的天" % len(rain))
    print()

    # §3 换季惯性：骤变日 vs 渐变日
    print("§3 换季惯性 —— 你按昨天的体感穿今天的衣服（骤变 = 与上一记录日温差 |Δt|≥%.0f°C）" % args.steep)
    seq = sorted(days, key=lambda x: x.d)
    steep_recs, mild_recs = [], []
    for prev, cur in zip(seq, seq[1:]):
        delta = cur.tmean - prev.tmean
        (steep_recs if abs(delta) >= args.steep else mild_recs).append(cur)
    if len(steep_recs) >= 5 and len(mild_recs) >= 5:
        s_rate = sum(1 for d in steep_recs if d.feel != 0) / float(len(steep_recs))
        m_rate = sum(1 for d in mild_recs if d.feel != 0) / float(len(mild_recs))
        s_cold = sum(1 for d in steep_recs if d.feel < 0)
        print("  骤变日失误率 %.1f%%（n=%d，其中偏冷 %d）vs 渐变日 %.1f%%（n=%d）"
              % (s_rate * 100.0, len(steep_recs), s_cold, m_rate * 100.0, len(mild_recs)))
        print("  → 骤变日失误率是渐变日的 %.1f 倍%s"
              % (s_rate / m_rate if m_rate else float("inf"),
                 "——温度跳水的早晨，你的衣柜还停在昨天" if s_rate > m_rate * 1.5 else ""))
    else:
        print("  样本不足（骤变 n=%d · 渐变 n=%d，各需 ≥5）——不比没有分母的天" % (len(steep_recs), len(mild_recs)))
    print()

    # §4 换季解剖
    print("§4 换季解剖 —— 失误住在月份里（月 n≥%d 才判）" % args.min_month)
    months = {}
    for d in days:
        months.setdefault(month_key(d), []).append(d)
    seasons = 0
    for mk in sorted(months):
        rec = months[mk]
        if len(rec) < args.min_month:
            print("  %s  （n=%d THIN 不判）" % (mk, len(rec)))
            continue
        rate = sum(1 for d in rec if d.feel != 0) / float(len(rec))
        bar = "█" * int(round(rate * 10))
        flag = "  ← 换季月" if rate >= 0.30 else ""
        if rate >= 0.30:
            seasons += 1
        print("  %s  %-10s %5.1f%%  (n=%d)%s" % (mk, bar, rate * 100.0, len(rec), flag))
    if seasons:
        print("  %d 个换季月（失误率 ≥30%%）：失误不住在深冬，住在温度正在换挡的地方" % seasons)
    else:
        print("  没有换季月（失误率 ≥30%%）——你的失误不跟着季节走")
    print()

    # §5 近 30 天
    print("§5 近 30 天（截至 %s）" % today.isoformat())
    recent = [d for d in days if (today - d.d).days <= 30]
    if len(recent) < 5:
        print("  n=%d THIN 不判——账本还没长到能谈「最近」。" % len(recent))
    else:
        r = sum(1 for d in recent if d.feel != 0) / float(len(recent))
        print("  n=%d，失误率 %.1f%% vs 全史 %.1f%%（%s）"
              % (len(recent), r * 100.0, miss_rate * 100.0,
                 "最近正在变糟" if r > miss_rate + 0.10 else
                 ("最近正在变好" if r < miss_rate - 0.10 else "与全史持平")))
    return 0


# ------------------------------------------------------------------ garments

def cmd_garments(args):
    days, end = load_ledger(args.ledger)
    lname = os.path.basename(args.ledger)
    today = resolve_today(days, args.today)
    if len(days) < args.min_days:
        print("THIN：账本只有 %d 天（门槛 %d）——单品温区拒绝在噪声上立碑。" % (len(days), args.min_days))
        return 3
    ok_days = [d for d in days if d.feel == 0]
    if not ok_days:
        print("THIN：没有一天「刚好」，舒适带无从谈起。")
        return 3
    band_lo = percentile(tmeans(ok_days), 10)
    band_hi = percentile(tmeans(ok_days), 90)

    print("%s — 单品温区 garments" % PROG)
    print("账本 %s · 记录 %d 天 · --today %s" % (lname, len(days), today.isoformat()))
    print("判决：GOOD win≥%.2f · MIXED %.2f–%.2f · POOR <%.2f（≥%d 次才判，不足 THIN）"
          % (args.good, args.good, args.poor, args.poor, args.min_wears))
    print("舒适带 [%.1f, %.1f]（feel=0 的 P10–P90）" % (band_lo, band_hi))
    print()
    table = group_garment(days)
    order = sorted(table, key=lambda k: (-len(table[k]), k))
    print("  %-10s %4s %6s %6s %6s %6s  %s" % ("单品", "n", "P10", "P50", "P90", "win", "判决"))
    orphans = []
    for name in order:
        rec = table[name]
        vals = sorted(x.tmean for x in rec)
        p10, p50, p90 = percentile(vals, 10), percentile(vals, 50), percentile(vals, 90)
        w = win_rate(rec)
        if len(rec) < args.min_wears:
            verdict = "THIN"
        else:
            if w >= args.good:
                verdict = "GOOD"
            elif w >= args.poor:
                verdict = "MIXED"
            else:
                verdict = "POOR"
                if len(rec) >= 5:
                    orphans.append(name)
        print("  %-10s %4d %6.1f %6.1f %6.1f %6s  %s%s"
              % (name, len(rec), p10, p50, p90,
                 ("%.2f" % w) if w is not None else "—", verdict,
                 "  ← 孤儿温区：%d 穿 %d 冷热，它从没稳过" % (len(rec), sum(1 for x in rec if x.feel != 0))
                 if verdict == "POOR" and len(rec) >= 5 else ""))
    print()

    # 断档：舒适带内连续 ≥ gap_line 的 1.5°C 档，无任何单品「实测穿对」覆盖。
    # 穿过 ≠ 穿对：覆盖只认 feel=0 的实测记录（档内 ≥2 次），不做插值外推——
    # 18 度穿对过不代表 20 度有答案，三次零星成功撑出来的「温区」是假的。
    print("温度断档（舒适带内连续 ≥%.1f°C 的 1.5°C 档无实测覆盖；覆盖 = 该档内某单品穿对"
          "（feel=0）≥2 次，穿对 ≥2 次且出现 ≥%d 次的单品才有资格）"
          % (args.gap_line, args.min_wears))
    qualified = {}
    for k, rec in table.items():
        ok = [x for x in rec if x.feel == 0]
        if len(rec) >= args.min_wears and len(ok) >= 2:
            qualified[k] = ok
    band_lo = percentile(tmeans(ok_days), 10)
    band_hi = percentile(tmeans(ok_days), 90)
    STEP = 1.5
    first_b = int(math.floor(band_lo / STEP)) * STEP
    gaps = []
    run = []
    b = first_b
    while b <= band_hi + 1e-9:
        covered = any(sum(1 for x in ok_rec if b <= x.tmean < b + STEP) >= 2
                      for ok_rec in qualified.values())
        if not covered:
            run.append(b)
        else:
            if run:
                gaps.append((run[0], run[-1] + STEP))
            run = []
        b += STEP
    if run:
        gaps.append((run[0], run[-1] + STEP))
    gaps = [(a, b2) for (a, b2) in gaps if b2 - a >= args.gap_line - 1e-9]
    if not gaps:
        print("  无断档——你的衣柜在温度轴上无缝覆盖舒适带 ✓")
        return 0
    exit_code = 0
    for a, b2 in gaps:
        wounded = [d for d in days if a <= d.tmean < b2]
        print("  ⚠ %.0f–%.0f°C（%.0f 度）：%s"
              % (a, b2, b2 - a,
                 "没有任何单品在这个温度带穿对过 ≥2 次"))
        if wounded:
            cold_n = sum(1 for d in wounded if d.feel < 0)
            hot_n = sum(1 for d in wounded if d.feel > 0)
            print("    且该段有 %d 天出门硬扛记录（冷 %d · 热 %d）—— 带伤口的断档，每年换季都在这里栽"
                  % (len(wounded), cold_n, hot_n))
            exit_code = 4
        else:
            print("    暂无出门记录落网——但你迟早会在某个 20 度的早晨想起它")
    if exit_code == 4:
        print("  → exit 4：断档里你已经付过体感学费，补一件中间层，或者继续硬扛——决定在你")
    return exit_code


# ------------------------------------------------------------------ combos

def cmd_combos(args):
    days, end = load_ledger(args.ledger)
    lname = os.path.basename(args.ledger)
    today = resolve_today(days, args.today)
    if len(days) < args.min_days:
        print("THIN：账本只有 %d 天（门槛 %d）——组合胜率拒绝在噪声上排名次。" % (len(days), args.min_days))
        return 3
    table = group_combo(days)
    print("%s — 组合胜率 combos" % PROG)
    print("账本 %s · 记录 %d 天 · --today %s" % (lname, len(days), today.isoformat()))
    print("win = 该组合 feel=0 占比；n≥%d 才判，不足 THIN" % args.min_wears)
    judged = []
    thin = []
    for combo, rec in table.items():
        w = win_rate(rec)
        if len(rec) >= args.min_wears:
            judged.append((combo, len(rec), w))
        else:
            thin.append((combo, len(rec), w))
    judged.sort(key=lambda x: (-x[2], -x[1], x[0]))
    good = [x for x in judged if x[2] >= args.good]
    bad = [x for x in judged if x[2] < args.poor]
    mid = [x for x in judged if args.poor <= x[2] < args.good]
    print()
    print("★ 闭眼穿（win≥%.2f）：" % args.good)
    if not good:
        print("  （无——你的账本里还没有常胜组合，或样本还薄）")
    for combo, cnt, w in good:
        print("  %-16s %3d 次 win %.2f" % (combo, cnt, w))
    print("◐ 看情况（%.2f ≤ win < %.2f）：" % (args.poor, args.good))
    if not mid:
        print("  （无）")
    for combo, cnt, w in mid:
        print("  %-16s %3d 次 win %.2f" % (combo, cnt, w))
    print("✗ 该退役（win<%.2f）：" % args.poor)
    if not bad:
        print("  （无——没有组合在你身上稳定翻车，好事）")
    for combo, cnt, w in bad:
        rec = table[combo]
        misses = [x for x in rec if x.feel != 0]
        last = sorted(misses, key=lambda x: x.d)[-1]
        print("  %-16s %3d 次 win %.2f   最近一次失误 %s %+d（%s）"
              % (combo, cnt, w, last.d.isoformat(), last.feel, FEEL_LABEL[last.feel]))
    if thin:
        print("? 样本不足（THIN，不判）：")
        for combo, cnt, w in sorted(thin, key=lambda x: -x[1]):
            print("  %-16s %3d 次（继续攒）" % (combo, cnt))
    return 0


# ------------------------------------------------------------------ plan

def _neighbors(days, tmean, window):
    return [d for d in days if abs(d.tmean - tmean) <= window + 1e-9]


def cmd_plan(args):
    days, end = load_ledger(args.ledger)
    lname = os.path.basename(args.ledger)
    today = resolve_today(days, args.today)
    tmean = (args.tmin + args.tmax) / 2.0
    if args.tmin > args.tmax:
        print("账本损坏：--tmin > --tmax，预报不会倒着下。")
        return 2
    if len(days) < args.min_days:
        print("THIN：账本只有 %d 天（门槛 %d）——明晨裁决拒绝从噪声里抽签。" % (len(days), args.min_days))
        return 3
    near = _neighbors(days, tmean, args.window)
    print("%s — 明晨裁决 plan" % PROG)
    print("目标日以 --today %s 计 · 预报 %g~%g°C（均值 %.1f°C）· 近邻带 ±%.1f°C"
          % (today.isoformat(), args.tmin, args.tmax, tmean, args.window))
    print("近邻 %d 天（%s）"
          % (len(near),
             "→".join(x.d.isoformat() for x in (near[:2] + near[-2:])) if len(near) >= 4 else
             "、".join(x.d.isoformat() for x in near) or "无"))
    if len(near) < args.min_near:
        print("UNKNOWN：近邻不足 %d 天——这段温度你没走过几次，账本拒绝编建议（exit 3）。"
              % args.min_near)
        print("先把这一温区穿出来记下来，账本才有资格替你投票。")
        return 3

    table = group_combo(days)
    if not args.wear:
        winners = {}
        for d in near:
            if d.feel == 0:
                winners[d.combo] = winners.get(d.combo, 0) + 1
        if not winners:
            print("WASTELAND：近邻 %d 天里你没有一次「刚好」（0/%d）——这段温度是你的账本荒地（exit 4）。"
                  % (len(near), len(near)))
            print("衣柜里可能缺一件这个温度的衣服；补一件，或者继续硬扛——决定在你。")
            return 4
        ranked = sorted(winners.items(), key=lambda x: (-x[1], x[0]))
        print("近邻战绩：%d 好 · %d 失误" % (sum(winners.values()), len(near) - sum(winners.values())))
        print("推荐（近邻内 feel=0 的组合，按次数）：")
        for i, (combo, cnt) in enumerate(ranked[:3], 1):
            rec = [d for d in near if d.combo == combo]
            print("  %d. %-16s 近邻 %d 次 win %.2f" % (i, combo, cnt, win_rate(rec)))
        best = ranked[0][0]
        best_rec = [d for d in near if d.combo == best]
        print("裁决：SAFE —— 按你的账本，「%s」在这段温度 %d 次 %d 好；出门吧（exit 0）"
              % (best, len(best_rec), len([d for d in best_rec if d.feel == 0])))
        return 0

    # 指定组合过闸
    combo = args.wear
    near_rec = [d for d in near if d.combo == combo]
    scope, rec = "近邻", near_rec
    if len(near_rec) < args.min_near and len(table.get(combo, [])) >= args.min_all:
        scope, rec = "全史兜底", table[combo]
    if len(rec) < args.min_near:
        print("UNKNOWN：组合「%s」%s 只有 %d 次记录（门槛 %d）——账本拒绝下结论（exit 3）。"
              % (combo, scope, len(rec), args.min_near))
        return 3
    w = win_rate(rec)
    if w >= args.safe:
        verdict, code = "SAFE", 0
    elif w >= args.risky:
        verdict, code = "RISKY", 1
    else:
        verdict, code = "DEAD", 4
    streak = tail_streak(rec, 3)
    demoted = ""
    if streak and verdict != "DEAD":
        verdict = "RISKY" if verdict == "SAFE" else "DEAD"
        code = 1 if verdict == "RISKY" else 4
        demoted = "（连败降档：最近 %d 次连续同向失误，STREAK 署名）" % streak
    ok = sum(1 for d in rec if d.feel == 0)
    print("指定组合：%s（%s 口径，n=%d）" % (combo, scope, len(rec)))
    print("  %d 好 · %d 失误 · win %.2f" % (ok, len(rec) - ok, w))
    if verdict == "SAFE":
        print("裁决：SAFE —— 按你的账本，这套在这个温度 %d 次 %d 好；出门吧（exit 0）" % (len(rec), ok))
    elif verdict == "RISKY":
        print("裁决：RISKY —— 这套半数靠运气；加一件或换一套（exit 1）%s" % demoted)
    else:
        last = sorted(rec, key=lambda x: x.d)[-1]
        print("裁决：DEAD —— 这套在你身上 %d 穿 %d 冷热（最近 %s %+d），别再给它机会（exit 4）"
              % (len(rec), len(rec) - ok, last.d.isoformat(), last.feel))
    return code


# ------------------------------------------------------------------ autopsy

def cmd_autopsy(args):
    days, end = load_ledger(args.ledger)
    lname = os.path.basename(args.ledger)
    today = resolve_today(days, args.today)
    if len(days) < args.min_days:
        print("THIN：账本只有 %d 天（门槛 %d）——失误解剖拒绝在薄账本上开庭。" % (len(days), args.min_days))
        return 3
    miss = [d for d in days if d.feel != 0]
    print("%s — 失误解剖 autopsy" % PROG)
    print("账本 %s · 记录 %d 天 · 失误 %d 天 · --today %s"
          % (lname, len(days), len(miss), today.isoformat()))
    print("受审资格：同温带（±%.1f°C，不含当天）至少 %d 天历史——没有对照臂的失误不予受理"
          % (args.window, args.min_near))
    if not miss:
        print("没有失误——要么你在撒谎，要么你已经毕业。")
        return 0
    table = group_combo(days)
    solvable = []
    unsolvable = []
    unjudgeable = []
    for d in miss:
        band = [x for x in days if x is not d and abs(x.tmean - d.tmean) <= args.window + 1e-9]
        if len(band) < args.min_near:
            unjudgeable.append(d)
            continue
        cands = []
        for combo, rec in table.items():
            in_band = [x for x in rec if x is not d and abs(x.tmean - d.tmean) <= args.window + 1e-9]
            if len(in_band) >= args.min_near:
                w = win_rate(in_band)
                if w >= args.solvable:
                    cands.append((combo, len(in_band), w))
        if cands:
            cands.sort(key=lambda x: (-x[2], -x[1], x[0]))
            solvable.append((d, cands[0]))
        else:
            unsolvable.append(d)
    n = len(miss)
    print("  有解 %d 天（%.1f%%）：答案就在柜子里，那天没穿它"
          % (len(solvable), len(solvable) / float(n) * 100.0))
    demo = sorted(solvable, key=lambda x: x[0].d)[:3]
    for d, (combo, cnt, w) in demo:
        print("    例：%s（%.1f°C）穿 %s → %+d；同温带答案：%s（%d 次 win %.2f）"
              % (d.d.isoformat(), d.tmean, d.combo, d.feel, combo, cnt, w))
    print("  无解 %d 天（%.1f%%）：同温带没有任何 ≥%.0f%% 胜率组合 —— 衣柜的锅"
          % (len(unsolvable), len(unsolvable) / float(n) * 100.0, args.solvable * 100.0))
    print("  不可判 %d 天（%.1f%%）：同温带历史 <%d 天，拒绝下结论"
          % (len(unjudgeable), len(unjudgeable) / float(n) * 100.0, args.min_near))
    print("  恒等式：%d + %d + %d = %d ✓"
          % (len(solvable), len(unsolvable), len(unjudgeable), n))
    print()

    # 连败线：3°C 固定桶内，末尾连续 ≥ streak 次同向失误
    print("连败线（%.0f°C 桶内最近连续 ≥%d 次同向失误）" % (3.0, args.streak))
    buckets = {}
    for d in days:
        buckets.setdefault(bucket_of(d.tmean), []).append(d)
    strikes = []
    for lo in sorted(buckets):
        s = tail_streak(buckets[lo], args.streak)
        if s:
            seq = sorted(buckets[lo], key=lambda x: x.d)[-s:]
            sign = "偏冷" if seq[-1].feel < 0 else "偏热"
            strikes.append((lo, seq, sign))
    if not strikes:
        print("  无——没有任何温度带正在连败（exit 0）")
        return 0
    code = 0
    for lo, seq, sign in strikes:
        print("  ⚠ [%.0f, %.0f)°C 桶：%s → %s 连续 %d 天%s —— 你的账本在报警"
              % (lo, lo + 3.0, seq[0].d.isoformat(), seq[-1].d.isoformat(), len(seq), sign))
        code = 4
    print("  → exit 4：这段温度该补一件衣服（或换一套组合），而不是继续硬扛——决定在你")
    return code


# ------------------------------------------------------------------ validate

def cmd_validate(args):
    days, end = load_ledger(args.ledger)
    lname = os.path.basename(args.ledger)
    today = resolve_today(days, args.today)
    errs = []
    for d in days:
        if d.d > today:
            errs.append("%s：日期晚于 --today %s——未来还没有体感" % (d.d.isoformat(), today.isoformat()))
    seen = set()
    for d in days:
        if d.d in seen:
            errs.append("%s：日期重复" % d.d.isoformat())
        seen.add(d.d)
    n = len(days)
    buckets = {f: sum(1 for d in days if d.feel == f) for f in range(FEEL_MIN, FEEL_MAX + 1)}
    if sum(buckets.values()) != n:
        errs.append("恒等式 V3 破：体感桶和 %d ≠ 记录数 %d" % (sum(buckets.values()), n))
    miss = [d for d in days if d.feel != 0]
    cold = sum(1 for d in miss if d.feel < 0)
    hot = sum(1 for d in miss if d.feel > 0)
    if cold + hot != len(miss):
        errs.append("恒等式 V4 破：冷 %d + 热 %d ≠ 失误 %d" % (cold, hot, len(miss)))
    garment_total = sum(len(d.outfit) for d in days)
    if garment_total < n:
        errs.append("恒等式 V5 破：单品出场 %d < 记录数 %d（每行至少一件）" % (garment_total, n))
    ok_days = [d for d in days if d.feel == 0]
    if ok_days:
        band_lo = percentile(tmeans(ok_days), 10)
        band_hi = percentile(tmeans(ok_days), 90)
        all_vals = tmeans(days)
        if not (all_vals[0] - 1e-9 <= band_lo and band_hi <= all_vals[-1] + 1e-9):
            errs.append("恒等式 V6 破：舒适带 [%.1f, %.1f] 逃出了温度范围 [%.1f, %.1f]"
                        % (band_lo, band_hi, all_vals[0], all_vals[-1]))
    print("%s — 账本体检 validate" % PROG)
    print("账本 %s · 记录 %d 天 · --today %s" % (lname, n, today.isoformat()))
    if errs:
        for e in errs:
            print("  ✗ %s" % e)
        print("→ exit 2：账本损坏，先修账再说话。")
        return 2
    print("  V1 行级（日期/温度/cond/outfit/feel 值域）✓")
    print("  V2 日期唯一 ✓")
    print("  V3 体感桶和 = 记录数（%d）✓" % n)
    print("  V4 冷(%d) + 热(%d) = 失误(%d) ✓" % (cold, hot, len(miss)))
    print("  V5 单品出场 %d ≥ 记录数 %d ✓" % (garment_total, n))
    if ok_days:
        print("  V6 舒适带 ⊆ 温度范围 ✓")
    print("→ exit 0：账本干净。")
    return 0


# ------------------------------------------------------------------ main

def build_parser():
    p = argparse.ArgumentParser(prog="own_thermometer", description=PROG)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, need_min_days=True):
        sp.add_argument("ledger", help="体感账本 TSV（date/tmin/tmax/cond/outfit/feel）")
        sp.add_argument("--today", help="锚定「今天」（缺省=账本末日）")
        if need_min_days:
            sp.add_argument("--min-days", type=int, default=20, help="样本下限（默认 20）")
        sp.add_argument("--window", type=float, default=1.5, help="温度近邻带半径 °C（默认 1.5）")
        sp.add_argument("--min-near", type=int, default=3, help="近邻/对照臂样本下限（默认 3）")

    sp = sub.add_parser("report", help="体感总账：温度地形/失误账/换季惯性/换季解剖")
    common(sp)
    sp.add_argument("--min-bucket", type=int, default=5, help="温度桶判定的样本下限（默认 5）")
    sp.add_argument("--steep", type=float, default=3.0, help="骤变日的温差阈值 °C（默认 3.0）")
    sp.add_argument("--min-month", type=int, default=5, help="月度判定的每月样本下限（默认 5）")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("garments", help="单品温区 + 孤儿点名 + 温度断档")
    common(sp)
    sp.add_argument("--min-wears", type=int, default=3, help="单品/覆盖判定的最少出场（默认 3）")
    sp.add_argument("--good", type=float, default=0.75, help="GOOD 门槛（默认 0.75）")
    sp.add_argument("--poor", type=float, default=0.50, help="POOR 门槛（默认 0.50）")
    sp.add_argument("--gap-line", type=float, default=2.0, help="断档门槛 °C（默认 2.0）")
    sp.set_defaults(func=cmd_garments)

    sp = sub.add_parser("combos", help="组合胜率排行：闭眼穿/看情况/该退役")
    common(sp)
    sp.add_argument("--min-wears", type=int, default=3, help="组合判定的最少出场（默认 3）")
    sp.add_argument("--good", type=float, default=0.75, help="GOOD 门槛（默认 0.75）")
    sp.add_argument("--poor", type=float, default=0.50, help="POOR 门槛（默认 0.50）")
    sp.set_defaults(func=cmd_combos)

    sp = sub.add_parser("plan", help="明晨裁决：输入预报温度，近邻战绩投票")
    common(sp, need_min_days=False)
    sp.add_argument("--tmin", type=float, required=True, help="明日预报低温")
    sp.add_argument("--tmax", type=float, required=True, help="明日预报高温")
    sp.add_argument("--wear", help="指定组合过闸（+ 连接）；缺省只推荐")
    sp.add_argument("--min-days", type=int, default=20, help="样本下限（默认 20）")
    sp.add_argument("--min-all", type=int, default=5, help="全史兜底的样本下限（默认 5）")
    sp.add_argument("--safe", type=float, default=0.70, help="SAFE 门槛（默认 0.70）")
    sp.add_argument("--risky", type=float, default=0.40, help="RISKY 下限（默认 0.40）")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("autopsy", help="失误解剖：怪衣柜还是怪手 + 连败线")
    common(sp)
    sp.add_argument("--solvable", type=float, default=0.80, help="有解组合的胜率门槛（默认 0.80）")
    sp.add_argument("--streak", type=int, default=3, help="连败长度门槛（默认 3）")
    sp.set_defaults(func=cmd_autopsy)

    sp = sub.add_parser("validate", help="账本体检：行级 + 恒等式 V1–V6")
    common(sp, need_min_days=False)
    sp.add_argument("--min-days", type=int, default=1, help="兼容占位")
    sp.set_defaults(func=cmd_validate)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LedgerError as e:
        print("账本损坏：%s" % e)
        print("→ exit 2：先修账再说话。")
        return 2


if __name__ == "__main__":
    sys.exit(main())
