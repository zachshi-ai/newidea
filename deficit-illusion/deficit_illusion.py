#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""赤字幻觉 · Deficit Illusion

把「自报摄入」和「实测体重」两本账放在能量守恒的天平上对账：
  7700 kcal/kg × ΔW = Σ摄入 − TDEE × 天数

你的秤不会说谎，但你的饮食日记会——营养学的铁律是自报摄入系统性低估
20–40%，而单日体重波动（水、钠、糖原、肠道内容物，±1–2 kg）会把真实
趋势（每天 −0.05 kg 量级）完全淹没。本件从两本可手编的账反解出：

  - 表观 TDEE：把自报摄入当真时，你的身体「必须」在烧的热量——
    烧得比昏迷还低时，不是代谢坏了，是账本在漏；
  - 漏记系数：真实消耗先验 ÷ 表观消耗，1.37 = 你记 3 顿、身体收到 4 顿；
  - 水重分离：脂肪在数学上不可能一天 +1 kg（需要单日净余 7700 kcal）；
  - 平台期法庭：吃得「更少」却停了，是记录劣化还是代谢适应；
  - 速率门禁：>1% 体重/周的猛掉，掉的不全是脂肪。

零依赖（Python 3.8+ 标准库），账本自锚定：缺省 as-of = 账本末日，
--as-of 钉死；同一本账任何机器任何一天跑出的结果逐字节一致。

Exit codes: 0 绿 · 2 账本损坏 · 3 样本太薄拒绝判级 · 4 红灯
"""

import argparse
import datetime
import math
import os
import sys

EXIT_OK = 0
EXIT_LEDGER = 2
EXIT_THIN = 3
EXIT_RED = 4

KCAL_PER_KG_DEFAULT = 7700.0
MIN_WEIGHT, MAX_WEIGHT = 20.0, 350.0
MIN_KCAL, MAX_KCAL = 0.0, 10000.0
THIN_DAYS = 10          # 体重记录 < 10 天 → 统计判级拒绝
THIN_SPAN = 21          # 账本跨度 < 21 天 → 对账/推演拒绝
MIN_RECON_SPAN = 21     # ΔW 至少要 3 周才可信
COV_MIN = 0.50          # 摄入覆盖率下限
GAP_RED = 1.25          # 漏记系数红线
GAP_WATCH = 1.10        # 漏记系数黄线
SPIKE_KG = 0.8          # 假反弹日环比阈值
SPIKE_SHADOW_UP = 14    # 涨 spike 后差分豁免天数
SPIKE_SHADOW_DOWN = 6   # 跌 spike 后差分豁免天数（只豁假负差分）
RATE_PCT = 1.0          # 速率红线（% 体重/周）
FLAT = 0.18             # 平台判级 |差分| 上限 kg/周
PLATEAU_MIN_RUN = 5     # 平台段最短连续天数
DEFICIT_LINE = 300.0    # 平台期自报赤字线 kcal/天（需先验才可判）


class LedgerError(Exception):
    """账本损坏：exit 2"""


class ThinError(Exception):
    """样本太薄：exit 3（统计判级拒绝）"""


# ---------------------------------------------------------------- 解析

def parse_date(s):
    try:
        return datetime.datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise LedgerError("bad date %r (want YYYY-MM-DD)" % s)


def parse_float(s, lo, hi, what, where):
    s = s.strip()
    if s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        raise LedgerError("%s %r not a number (%s)" % (what, s, where))
    if v < lo or v > hi:
        raise LedgerError("%s %r out of range [%s, %s] (%s)"
                          % (what, s, lo, hi, where))
    return v


class Day(object):
    __slots__ = ("date", "kg", "kcal", "note")

    def __init__(self, date, kg, kcal, note):
        self.date = date
        self.kg = kg
        self.kcal = kcal
        self.note = note


def load_ledger(path):
    """ledger.tsv: date<TAB>kg<TAB>kcal[<TAB>note]，kg/kcal 可留空。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    lines = [ln for ln in raw.split("\n") if ln.strip() != ""]
    if not lines:
        raise LedgerError("empty ledger")
    head = lines[0].split("\t")
    if [h.strip() for h in head[:3]] != ["date", "kg", "kcal"]:
        raise LedgerError("header must be date/kg/kcal/note, got %r" % head)
    days = {}
    order = []
    for ln in lines[1:]:
        cols = ln.split("\t")
        where = "row %r" % cols[0]
        if len(cols) < 3:
            raise LedgerError("need >=3 columns: %r" % ln)
        d = parse_date(cols[0])
        if d in days:
            raise LedgerError("duplicate date %s" % d)
        kg = parse_float(cols[1], MIN_WEIGHT, MAX_WEIGHT, "kg", where)
        kcal = parse_float(cols[2], MIN_KCAL, MAX_KCAL, "kcal", where)
        note = cols[3].strip() if len(cols) > 3 else ""
        days[d] = Day(d, kg, kcal, note)
        order.append(d)
    order.sort()
    if not order:
        raise LedgerError("no data rows")
    return [days[d] for d in order]


def apply_as_of(days, as_of):
    if as_of is None:
        return days
    kept = [d for d in days if d.date <= as_of]
    if not kept:
        raise LedgerError("as-of %s before first row %s" % (as_of, days[0].date))
    return kept


# ---------------------------------------------------------------- 统计核

class Facts(object):
    """从账本长出来的全部算术事实。"""

    def __init__(self, days, kcal_per_kg, spike_kg=SPIKE_KG):
        self.days = days
        self.kpk = kcal_per_kg
        self.spike_kg = spike_kg
        self.first = days[0].date
        self.last = days[-1].date
        self.span = (self.last - self.first).days + 1
        self.by_date = dict((d.date, d) for d in days)
        self.kg_days = [d for d in days if d.kg is not None]
        self.kcal_days = [d for d in days if d.kcal is not None]
        self.kg_cov = len(self.kg_days) / float(self.span)
        self.kcal_cov = len(self.kcal_days) / float(self.span)
        self.kg_series = [(d.date, d.kg) for d in self.kg_days]
        self.kcal_total = sum(d.kcal for d in self.kcal_days)
        # 日历序列（含缺席日，缺席=None）
        self.calendar = []
        for i in range(self.span):
            dt = self.first + datetime.timedelta(days=i)
            self.calendar.append(self.by_date.get(dt))
        self.mw = self._moving_avg()
        self.spikes = self._spikes()
        self.diffs = self._diffs()

    # ---- 7 日滑动均重：窗内至少 5 天有读数才有效 ----
    def _moving_avg(self):
        out = []  # (end_date, value|None)
        for i in range(self.span):
            win = self.calendar[max(0, i - 6):i + 1]
            vals = [c.kg for c in win if c is not None and c.kg is not None]
            if len(win) == 7 and len(vals) >= 5:
                out.append((self.first + datetime.timedelta(days=i),
                            sum(vals) / 7.0))
            else:
                out.append((self.first + datetime.timedelta(days=i), None))
        return out

    def mw_at(self, i):
        return self.mw[i][1]

    # ---- 假反弹（spike）：日环比 |Δ| ≥ 阈值 ----
    def _spikes(self):
        out = []
        kg_prev = None
        for c in self.days:
            if c.kg is None:
                continue
            if kg_prev is not None and abs(c.kg - kg_prev[1]) >= self.spike_kg:
                out.append((c.date, c.kg - kg_prev[1]))
            kg_prev = (c.date, c.kg)
        return out  # [(date, delta)]

    def spike_shadow(self, d):
        """日期 d 是否落在某个 spike 的差分污染窗内。"""
        for s, delta in self.spikes:
            if delta > 0:
                if s - datetime.timedelta(days=1) <= d <= \
                        s + datetime.timedelta(days=SPIKE_SHADOW_UP):
                    return s, delta
            else:
                if s <= d <= s + datetime.timedelta(days=SPIKE_SHADOW_DOWN):
                    return s, delta
        return None

    # ---- 速率差分：以 e 结尾的 7 日均重 − 7 天前的 7 日均重 ----
    def _diffs(self):
        out = []
        for i in range(self.span):
            e = self.first + datetime.timedelta(days=i)
            if i >= 13:
                a, b = self.mw_at(i), self.mw_at(i - 7)
                if a is not None and b is not None:
                    shadow = self.spike_shadow(e)
                    out.append((e, a - b, shadow is not None))
            # i < 13：双满窗还不存在
        return out  # [(end_date, kg/week, conflicted)]

    # ---- 先验 TDEE ----
    def prior_tdee(self, args):
        if args.tdee is not None:
            return args.tdee, "given --tdee"
        if args.sex is not None and args.age is not None \
                and args.height is not None:
            base_w = self.first_week_weight()
            if base_w is None:
                return None, None
            s = 5.0 if args.sex in ("m", "male", "男") else -161.0
            bmr = 10.0 * base_w + 6.25 * args.height - 5.0 * args.age + s
            act = min(max(args.activity, 1.2), 1.9)
            return bmr * act, ("Mifflin-St Jeor BMR %.0f × activity %.2f "
                               "(weight from first 7d avg %.2f)"
                               % (bmr, act, base_w))
        return None, None

    def first_week_weight(self):
        vals = [d.kg for d in self.kg_days
                if d.date <= self.first + datetime.timedelta(days=6)]
        if not vals:
            return None
        return sum(vals) / float(len(vals))

    # ---- 核心对账（窗口对齐口径）----
    # ΔW = 末窗均重 − 首窗均重，两个 7 日窗的中心相隔 span-7 天；
    # 恒等式必须在同一窗口上成立：摄入窗口 = [first+3, last-4]（共
    # span-7 个摄入日），身体变化窗口 = 同一时长。掐头去尾是窗平滑的
    # 代价——换来的是摄入、消耗、体重三项严格同窗，构造真值可精确复原。
    def win_days(self):
        if self.span < MIN_RECON_SPAN:
            return None
        n = self.span - 7
        a = self.first + datetime.timedelta(days=3)
        b = self.first + datetime.timedelta(days=3 + n - 1)
        return a, b, n

    def win_kcal(self):
        w = self.win_days()
        if w is None:
            return None
        a, b, n = w
        s = 0.0
        for i in range(n):
            dt = a + datetime.timedelta(days=i)
            c = self.by_date.get(dt)
            if c is not None and c.kcal is not None:
                s += c.kcal
        return s

    def dw(self):
        """末窗均重 − 首窗均重；窗不足则 None。"""
        firsts = [v for (_, v) in self.mw[:7] if v is not None]
        lasts = [v for (_, v) in self.mw[-7:] if v is not None]
        if len(self.mw) < MIN_RECON_SPAN or not firsts or not lasts:
            return None
        return lasts[-1] - firsts[0]

    def apparent_tdee(self):
        dw = self.dw()
        w = self.win_days()
        if dw is None or w is None:
            return None
        n = w[2]
        return self.win_kcal() / float(n) - self.kpk * dw / float(n)

    def rep_avg_win(self):
        w = self.win_days()
        if w is None:
            return None
        return self.win_kcal() / float(w[2])

    def thin(self):
        return len(self.kg_days) < THIN_DAYS or self.span < THIN_SPAN

    def week_table(self):
        """ISO 周（自 first 的整周切分）：[(idx, start, end, avg|None, n)]"""
        out = []
        w = 0
        while True:
            s = self.first + datetime.timedelta(days=7 * w)
            e = s + datetime.timedelta(days=6)
            if s > self.last:
                break
            ee = min(e, self.last)
            vals = [self.by_date[d].kg for d in daterange(s, ee)
                    if d in self.by_date and self.by_date[d].kg is not None]
            out.append((w + 1, s, ee,
                        sum(vals) / len(vals) if len(vals) >= 5 else None,
                        len(vals)))
            w += 1
        return out


def daterange(a, b):
    for i in range((b - a).days + 1):
        yield a + datetime.timedelta(days=i)


# ---------------------------------------------------------------- 输出

def banner(text):
    print("!! " + text)


def lamp(name, detail):
    print("LAMP %s — %s" % (name, detail))


def head(f, title, ledger_path, args):
    print("== 赤字幻觉 · Deficit Illusion — %s" % title)
    print("ledger: %s   span: %s .. %s (%d days)   as-of: %s"
          % (os.path.basename(ledger_path), f.first, f.last, f.span,
             args.as_of if args.as_of else f.last))
    print("weight days: %d/%d (%.1f%%)   intake days: %d/%d (%.1f%%)"
          % (len(f.kg_days), f.span, 100 * f.kg_cov,
             len(f.kcal_days), f.span, 100 * f.kcal_cov))


def fmt_date(d):
    return d.isoformat()


def avg_kcal(f):
    return f.kcal_total / float(f.span)


# ---------------------------------------------------------------- 命令

def cmd_trend(f, ledger_path, args):
    head(f, "趋势账", ledger_path, args)
    print("")
    if f.thin():
        print("thin ledger (%d weight days, %d-day span): "
              "arithmetic only, statistics DECLINED"
              % (len(f.kg_days), f.span))
    wtab = f.week_table()
    print("-- ISO 周均重（7 日滑动窗口的周视图）--")
    for idx, s, e, avg, n in wtab:
        if avg is None:
            print("W%-2d %s..%s   (thin, n=%d)" % (idx, s, e, n))
            continue
        spike_hit = [sp for sp, _ in f.spikes if s <= sp <= e]
        flag = "  <- spike week, 均重不可单独解读" if spike_hit else ""
        print("W%-2d %s..%s   %6.2f kg  (n=%d)%s"
              % (idx, s, e, avg, n, flag))
    print("")
    print("-- 速率差分（以 e 结尾的 7 日均重 − 一周前的 7 日均重，kg/周）--")
    shown = 0
    for e, d, conf in f.diffs:
        if abs(d) >= 0.30:
            tag = "  CONFOUNDED(spike shadow)" if conf else ""
            print("%s   %+0.2f%s" % (e, d, tag))
            shown += 1
    if shown == 0:
        print("(no |diff| >= 0.30 kg/week)")
    clean = [abs(d) for (_, d, c) in f.diffs if not c]
    if clean:
        print("max |diff| (unconfounded): %.2f kg/week" % max(clean))
    print("")
    print("-- 假反弹（日环比 ≥ %.1f kg）--" % f.spike_kg)
    if not f.spikes:
        print("(none)")
    for s, delta in f.spikes:
        kcal = abs(delta) * f.kpk
        print("%s   %+0.1f kg   需要%s %.0f kcal 的单日净%s —— "
              "脂肪在数学上不可能，是水、钠与糖原在演戏"
              % (s, delta,
                 "净余" if delta > 0 else "净亏", kcal,
                 "盈余" if delta > 0 else "缺口"))
        if f.note_on(s):
            print("        note: %s" % f.note_on(s))
    return EXIT_OK


def note_on(self, d):
    c = self.by_date.get(d)
    return c.note if c else ""


Facts.note_on = note_on


def cmd_reconcile(f, ledger_path, args):
    head(f, "赤字对账", ledger_path, args)
    print("")
    if f.thin() or f.span < MIN_RECON_SPAN or f.dw() is None:
        print("thin ledger: 对账需要 ≥%d 天跨度与足够的体重读数，"
              "现在 %d 天 / %d 个体重读数 — DECLINED"
              % (MIN_RECON_SPAN, f.span, len(f.kg_days)))
        return EXIT_THIN
    dw = f.dw()
    n_win = f.win_days()[2]
    rep_avg = f.rep_avg_win()
    apparent = f.apparent_tdee()
    wa, wb, _ = f.win_days()
    print("-- 两本账（对账窗口 %s .. %s，%d 天，掐头去尾各 3 天与均重窗对齐）--"
          % (wa, wb, n_win))
    print("自报摄入: 窗内 Σ %.0f kcal = %.1f kcal/天 "
          "(缺席日按没记录处理，不假装你那天绝食)"
          % (f.win_kcal(), rep_avg))
    print("实测体重: 首窗均重 −> 末窗均重 = ΔW %+.2f kg "
          "= 脂肪当量 %+.0f kcal 累计"
          % (dw, dw * f.kpk))
    print("")
    print("-- 表观 TDEE（把自报摄入当真时，你「必须」在烧的热量）--")
    print("apparent TDEE = %.1f − (%.0f × %+.2f)/%d = %.1f kcal/天"
          % (rep_avg, f.kpk, dw, n_win, apparent))
    prior, why = f.prior_tdee(args)
    if prior is None:
        print("")
        print("declined: 漏记账需要消耗先验 — add --tdee N, "
              "or --sex/--age/--height[--activity] for Mifflin-St Jeor")
        return EXIT_OK
    if f.kcal_cov < COV_MIN or f.kcal_total <= 0:
        print("")
        print("declined: 摄入覆盖率 %.0f%% < %.0f%%（或全空），"
              "漏记账会系统性失真 — 先补记录"
              % (100 * f.kcal_cov, 100 * COV_MIN))
        return EXIT_THIN
    print("")
    print("-- 漏记账（先验: %s）--" % why)
    gap = prior - apparent
    i_true = prior + f.kpk * dw / n_win
    coef = i_true / rep_avg if rep_avg > 0 else float("inf")
    print("真实摄入均值 = %.1f + (%.0f × %+.2f)/%d = %.1f kcal/天"
          % (prior, f.kpk, dw, n_win, i_true))
    print("漏记 = 先验 − 表观 = %.1f − %.1f = %.1f kcal/天" % (prior, apparent, gap))
    print("漏记系数 = %.1f / %.1f = %.3f  (1.00 = 你是神；文献里的普通人 1.2–1.4)"
          % (i_true, rep_avg, coef))
    print("敏感性: TDEE ±15%% → 漏记 %.0f .. %.0f kcal/天 "
          "(即使按对你最有利的消耗，每天仍漏 %.0f)"
          % (0.85 * prior - apparent, 1.15 * prior - apparent,
             max(0.85 * prior - apparent, 0.0)))
    print("")
    print("-- 账面 vs 秤 --")
    paper = (prior - rep_avg) * n_win / f.kpk
    print("按先验与自报，账面赤字 %.0f/天 → %d 天『该』减 %.2f kg；"
          "秤上实际 %+.2f kg"
          % (prior - rep_avg, n_win, paper, dw))
    print("差额 %.2f kg = %.0f kcal/天 × %d 天 ÷ %.0f —— "
          "不是代谢奇迹，是没被记下来的那部分生活"
          % (paper + dw, gap, n_win, f.kpk))
    if coef >= GAP_RED:
        lamp("RECORD GAP", "漏记系数 %.3f ≥ %.2f：你记 %d，身体收到 %d "
              "—— %.0f%% 的摄入是隐形的（每 3 顿饭约少记 1 顿）"
              % (coef, GAP_RED, round(rep_avg), round(i_true),
                 100 * (1.0 - 1.0 / coef)))
        return EXIT_RED
    if coef >= GAP_WATCH:
        lamp("WATCH", "漏记系数 %.3f ∈ [%.2f, %.2f)：留意调料、饮料与周末"
              % (coef, GAP_WATCH, GAP_RED))
        return EXIT_OK
    lamp("HONEST", "漏记系数 %.3f < %.2f：你的记录配得上你的秤"
         % (coef, GAP_WATCH))
    if apparent > prior * 1.15:
        print("  (你的表观消耗明显高于先验——先验保守了，参考 --tdee)")
    return EXIT_OK


def cmd_rate(f, ledger_path, args):
    head(f, "速率门禁", ledger_path, args)
    print("")
    if f.thin() or len(f.diffs) < PLATEAU_MIN_RUN:
        print("thin ledger: 速率需要 ≥%d 个差分日与 ≥%d 天跨度，"
              "现在 %d 个 / %d 天 — DECLINED"
              % (PLATEAU_MIN_RUN, THIN_SPAN, len(f.diffs), f.span))
        return EXIT_THIN
    print("红线: |差分| ≥ %.1f%% × 当窗体重/周（猛掉的不全是脂肪，"
          "肌肉与水都在陪跑）" % args.rate_pct)
    print("")
    worst = None
    hit = False
    for e, d, conf in f.diffs:
        if conf:
            continue
        w = f.mw_end(e)
        line = args.rate_pct / 100.0 * (w if w else 65.0)
        if abs(d) >= line:
            hit = True
            if worst is None or abs(d) > abs(worst[1]):
                worst = (e, d, line)
    n_conf = sum(1 for (_, _, c) in f.diffs if c)
    if n_conf:
        print("(spike shadow 豁免 %d 个差分日——水重退潮会伪造速率)" % n_conf)
    if worst:
        print("max |diff| (unconfounded): %+.2f kg/week @ %s "
              "(line %.2f)" % (worst[1], worst[0], worst[2]))
        lamp("MUSCLE RISK",
             "%s 的 %+.2f kg/周 越过 %.1f%% 线（%.2f）："
             "代餐与断食的猛亏里，肌肉在陪葬——把速率压回线内"
             % (worst[0], worst[1], args.rate_pct, worst[2]))
        return EXIT_RED
    clean = [abs(d) for (_, d, c) in f.diffs if not c]
    print("max |diff| (unconfounded): %.2f kg/week — 线内" % max(clean))
    return EXIT_OK


def mw_end(self, e):
    for d, v in self.mw:
        if d == e:
            return v
    return None


Facts.mw_end = mw_end


def cmd_plateau(f, ledger_path, args):
    head(f, "平台期法庭", ledger_path, args)
    print("")
    if len(f.diffs) < PLATEAU_MIN_RUN + 1:
        print("thin ledger: 平台判定需要差分序列，现在 %d 个 — DECLINED"
              % len(f.diffs))
        return EXIT_THIN
    # 平台段：连续 ≥ N 个非冲突差分日 |d| ≤ FLAT
    runs = []
    cur = []
    for e, d, conf in f.diffs:
        if conf:
            if len(cur) >= PLATEAU_MIN_RUN:
                runs.append(cur)
            cur = []
            continue
        if abs(d) <= args.flat:
            cur.append((e, d))
        else:
            if len(cur) >= PLATEAU_MIN_RUN:
                runs.append(cur)
            cur = []
    if len(cur) >= PLATEAU_MIN_RUN:
        runs.append(cur)
    if not runs:
        print("(no plateau: 无连续 ≥%d 天的 |差分| ≤ %.2f kg/周 段)"
              % (PLATEAU_MIN_RUN, args.flat))
        print("你感觉的『卡住了』在均重口径下可能不存在——"
              "先看 trend 的差分表，再谈平台")
    for run in runs:
        s, e = run[0][0], run[-1][0]
        slope = sum(d for _, d in run) / len(run)
        print("平台段 %s .. %s (%d days, 平均差分 %+.2f kg/周)"
              % (s, e, len(run), slope))
        verdict, seg_avg, pre_avg = plateau_verdict(f, s, e)
        active = e >= f.last - datetime.timedelta(days=7)
        if verdict == "ROT":
            tag = "ACTIVE" if active else "PASSED"
            print("  证据: 段内自报 %.0f vs 段前 %.0f kcal/天" % (seg_avg, pre_avg))
            print("  裁决: RECORD-OR-ADAPT (%s) —— 吃得没多却停了："
                  "要么漏记在扩大，要么代谢在适应；先修记录 14 天，再谈代谢" % tag)
        else:
            print("  证据: 段内自报 %.0f vs 段前 %.0f kcal/天" % (seg_avg, pre_avg))
            print("  裁决: BEHAVIOR —— 这段你吃了回来，账本先于体重看见")
    # 末端现状
    tail = [d for e, d, c in f.diffs[-7:] if not c]
    active_runs = [r for r in runs
                   if r[-1][0] >= f.last - datetime.timedelta(days=7)]
    if active_runs:
        print("末端: 你正在平台期上（最近平台段至 %s）"
              % active_runs[-1][-1][0])
    elif tail:
        m = max(abs(t) for t in tail)
        if m <= args.flat:
            print("末端: 近 7 个差分日 max|d|=%.2f ≤ %.2f —— "
                  "你正在平台期上" % (m, args.flat))
        else:
            print("末端: 近 7 个差分日 max|d|=%.2f —— 当前不在平台期" % m)
    red = any(
        plateau_verdict(f, r[0][0], r[-1][0])[0] == "ROT"
        and r[-1][0] >= f.last - datetime.timedelta(days=7)
        for r in runs)
    if red:
        return EXIT_RED
    return EXIT_OK


def plateau_verdict(f, s, e):
    """平台段裁决：段内自报 vs 段前同长窗口自报。返回 (verdict, seg_avg, pre_avg)。"""
    n = (e - s).days + 1
    seg = [f.by_date[d].kcal for d in daterange(s, e)
           if d in f.by_date and f.by_date[d].kcal is not None]
    pre_s = s - datetime.timedelta(days=n)
    pre = [f.by_date[d].kcal for d in daterange(pre_s, s - datetime.timedelta(days=1))
           if d in f.by_date and f.by_date[d].kcal is not None]
    if not seg or not pre:
        return "NONE", 0.0, 0.0
    a = sum(seg) / float(len(seg))
    b = sum(pre) / float(len(pre))
    if a >= b + 100.0:
        return "BEHAVIOR", a, b
    return "ROT", a, b  # 吃得没多（甚至更少）却停了——RECORD-OR-ADAPT


def cmd_report(f, ledger_path, args):
    head(f, "总账", ledger_path, args)
    print("")
    rc = EXIT_OK
    lamps = []
    if f.thin():
        print("thin ledger (%d weight days / %d-day span): "
              "统计判级 DECLINED（exit 3），算术照常——账本再薄也如实出数"
              % (len(f.kg_days), f.span))
        rc = EXIT_THIN
    # 趋势
    dw = f.dw()
    if dw is not None:
        print("体重: 首窗均重 −> 末窗均重 = %+.2f kg（7 日均重口径，"
              "单日读数不进结论）" % dw)
        tail = [d for e, d, c in f.diffs[-7:] if not c]
        if tail:
            print("近端速率: 最近 7 个差分日均值 %+.2f kg/周"
                  % (sum(tail) / len(tail)))
    # 对账
    prior, why = f.prior_tdee(args)
    apparent = f.apparent_tdee()
    if apparent is not None:
        print("表观 TDEE: %.1f kcal/天（自报 %.1f × 秤上 %+.2f kg 反解，"
              "窗口对齐口径）" % (apparent, f.rep_avg_win(), dw))
    if prior is not None and apparent is not None \
            and f.span >= MIN_RECON_SPAN and f.kcal_cov >= COV_MIN:
        gap = prior - apparent
        i_true = prior + f.kpk * dw / f.win_days()[2]
        coef = i_true / f.rep_avg_win()
        print("漏记账: 先验 %.1f − 表观 %.1f = 漏记 %.1f kcal/天，"
              "系数 %.3f（先验: %s）" % (prior, apparent, gap, coef, why))
        if coef >= GAP_RED:
            lamps.append(("RECORD GAP", "系数 %.3f ≥ %.2f——记 3 顿收 4 顿"
                          % (coef, GAP_RED)))
        elif coef >= GAP_WATCH:
            lamps.append(("WATCH", "系数 %.3f——调料、饮料、周末在漏"
                          % coef))
        else:
            lamps.append(("HONEST", "系数 %.3f——记录配得上体重" % coef))
    elif prior is None:
        print("漏记账: skipped — add --tdee 或 --sex/--age/--height "
              "以拆出漏记")
    # 假反弹
    for s, delta in f.spikes:
        lamps.append(("PHANTOM", "%s %+0.1f kg——%.0f kcal 的单日净%s"
                      "不可能，是水在演戏"
                      % (s, delta, abs(delta) * f.kpk,
                         "盈余" if delta > 0 else "缺口")))
    # 速率
    worst = None
    for e, d, conf in f.diffs:
        if conf:
            continue
        w = f.mw_end(e)
        line = args.rate_pct / 100.0 * (w if w else 65.0)
        if abs(d) >= line and (worst is None or abs(d) > abs(worst[1])):
            worst = (e, d, line)
    if worst:
        lamps.append(("MUSCLE RISK", "%s %+.2f kg/周 越过 %.1f%% 线"
                      % (worst[0], worst[1], args.rate_pct)))
    # goal
    if args.goal is not None and dw is not None:
        tail = [d for e, d, c in f.diffs[-7:] if not c]
        if tail:
            rate = sum(tail) / len(tail) / 7.0  # kg/天
            cur = [v for (_, v) in f.mw[-7:] if v is not None][-1]
            if rate < -1e-6 and cur > args.goal:
                eta = (cur - args.goal) / (-rate)
                print("目标: 距 %.1f kg 还差 %.2f kg，按近端节奏约 %d 天"
                      % (args.goal, cur - args.goal, int(math.ceil(eta))))
            elif cur <= args.goal:
                print("目标: 末窗均重 %.2f 已在 %.1f kg 之下" % (cur, args.goal))
            else:
                print("目标: 近端速率为 0 或在涨——按当前节奏到不了 %.1f kg"
                      % args.goal)
    print("")
    if f.thin():
        for name, detail in lamps:
            print("lamp %s — %s" % (name, detail))
        return rc
    if not lamps:
        print("no lamps. 账本与秤互相作证。")
        return EXIT_OK
    for name, detail in lamps:
        lamp(name, detail)
    reds = {"RECORD GAP", "MUSCLE RISK"}
    if any(n in reds for n, _ in lamps):
        return EXIT_RED
    return EXIT_OK


def cmd_simulate(f, ledger_path, args):
    head(f, "反事实", ledger_path, args)
    print("")
    dw = f.dw()
    if dw is None or f.span < MIN_RECON_SPAN:
        print("thin ledger: 推演需要 ≥%d 天的体重账 — DECLINED"
              % MIN_RECON_SPAN)
        return EXIT_THIN
    cur = [v for (_, v) in f.mw[-7:] if v is not None][-1]
    tail = [d for e, d, c in f.diffs[-7:] if not c]
    if args.sim == "continue":
        if not tail:
            print("declined: 近端差分全在 spike shadow 里，没有合法速率")
            return EXIT_THIN
        rate_wk = sum(tail) / len(tail)
        print("假设: 你的吃法和你记账的毛病都原样保持")
        print("近端节奏 %+.2f kg/周（实测外推，不经过任何公式）" % rate_wk)
        for wks in (4, 8, 12):
            print("  +%2d 周 → %.2f kg（±0.5 水重带）"
                  % (wks, cur + rate_wk * wks))
        if args.goal is not None:
            if rate_wk < -1e-6 and cur > args.goal:
                days = (cur - args.goal) / (-rate_wk / 7.0)
                eta = f.last + datetime.timedelta(days=int(math.ceil(days)))
                print("按这个节奏到 %.1f kg: %s（%d 天后）——"
                      "前提是你的吃法真的不变"
                      % (args.goal, eta, int(math.ceil(days))))
            else:
                print("到 %.1f kg: 按当前节奏永远到不了——先改行为，"
                      "再谈目标" % args.goal)
        return EXIT_OK
    # intake N
    prior, why = f.prior_tdee(args)
    if prior is None:
        print("declined: intake 推演需要消耗先验 — add --tdee 或 "
              "--sex/--age/--height")
        return EXIT_THIN
    rate_wk = (args.intake - prior) / f.kpk * 7.0
    print("假设: 真实摄入 = %.0f kcal/天（称过、记全的真实值），"
          "消耗 ≈ 先验 %.1f（%s）" % (args.intake, prior, why))
    print("节奏 %+.2f kg/周" % rate_wk)
    for wks in (4, 8, 12):
        print("  +%2d 周 → %.2f kg" % (wks, cur + rate_wk * wks))
    if args.goal is not None:
        if rate_wk < -1e-6 and cur > args.goal:
            days = (cur - args.goal) / (-rate_wk / 7.0)
            eta = f.last + datetime.timedelta(days=int(math.ceil(days)))
            print("到 %.1f kg: %s（%d 天后）" % (args.goal, eta,
                                                int(math.ceil(days))))
        else:
            print("到 %.1f kg: 这个吃法到不了" % args.goal)
    print("对照: 你的自报是 %.0f 却瘦不动；把真实吃量压到 %.0f 并如实"
          "记录，才拿得到账面应有的速度" % (avg_kcal(f), args.intake))
    return EXIT_OK


def cmd_validate(f, ledger_path, args):
    head(f, "账本体检", ledger_path, args)
    print("")
    ok = True
    # 1. Σkcal 复算
    s2 = sum(d.kcal for d in f.kcal_days)
    print("Σkcal 复算: %d == %d %s" % (s2, f.kcal_total,
                                       "OK" if s2 == f.kcal_total else "FAIL"))
    ok &= (s2 == f.kcal_total)
    # 2. 表观恒等式反代（窗口对齐口径）
    dw = f.dw()
    if dw is not None:
        apparent = f.apparent_tdee()
        n_win = f.win_days()[2]
        resid = (apparent * n_win + f.kpk * dw) - f.win_kcal()
        print("表观反代: apparent×win + kpk×ΔW − Σwin_kcal = %.6f %s"
              % (resid, "OK" if abs(resid) < 1e-6 * max(1, n_win) else "FAIL"))
        ok &= abs(resid) < 1e-6 * max(1, n_win)
    # 3. 首窗均重重算
    fw = f.first_week_weight()
    print("首窗均重重算: %.2f %s" % (fw, "OK" if fw is not None else "N/A"))
    # 4. 覆盖披露
    print("体重覆盖 %d/%d (%.1f%%)、摄入覆盖 %d/%d (%.1f%%)"
          % (len(f.kg_days), f.span, 100 * f.kg_cov,
             len(f.kcal_days), f.span, 100 * f.kcal_cov))
    holes = []
    run = None
    for i in range(f.span):
        dt = f.first + datetime.timedelta(days=i)
        if dt not in f.by_date:
            if run is None:
                run = [dt, dt]
            else:
                run[1] = dt
        else:
            if run is not None:
                holes.append(run)
                run = None
    if run is not None:
        holes.append(run)
    if holes:
        print("账本空洞（没记的日子不算失败，但不进任何分母）:")
        for a, b in holes:
            print("  %s .. %s (%d days)" % (a, b, (b - a).days + 1))
    else:
        print("账本空洞: none")
    print("")
    print("ledger OK" if ok else "ledger BROKEN")
    return EXIT_OK if ok else EXIT_LEDGER


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(
        prog="deficit_illusion.py",
        description="赤字幻觉 · Deficit Illusion —— 自报摄入 × 实测体重 "
                    "的能量对账")
    p.add_argument("cmd", choices=[
        "report", "trend", "reconcile", "plateau", "rate",
        "simulate", "validate"])
    p.add_argument("ledger", help="ledger.tsv (date/kg/kcal/note)")
    p.add_argument("--as-of", dest="as_of", default=None,
                   help="截断账本到该日（含当日），YYYY-MM-DD")
    p.add_argument("--goal", type=float, default=None,
                   help="目标体重 kg（report/simulate 的 ETA 用）")
    p.add_argument("--kcal-per-kg", dest="kcal_per_kg", type=float,
                   default=KCAL_PER_KG_DEFAULT)
    p.add_argument("--tdee", type=float, default=None,
                   help="消耗先验 kcal/天（体脂秤/教练/公式均可）")
    p.add_argument("--sex", default=None, help="m|f（公式先验用）")
    p.add_argument("--age", type=float, default=None)
    p.add_argument("--height", type=float, default=None, help="cm")
    p.add_argument("--activity", type=float, default=1.4,
                   help="活动系数 1.2–1.9（默认 1.4）")
    p.add_argument("--rate-pct", dest="rate_pct", type=float,
                   default=RATE_PCT, help="速率红线 %%体重/周（默认 1.0）")
    p.add_argument("--flat", type=float, default=FLAT,
                   help="平台判级 |差分| 上限 kg/周（默认 0.18）")
    p.add_argument("--spike", type=float, default=SPIKE_KG,
                   help="假反弹日环比阈值 kg（默认 0.8）")
    p.add_argument("extra", nargs="*", default=[],
                   help="simulate 子命令: continue | intake <kcal>")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        as_of = parse_date(args.as_of) if args.as_of else None
        days = apply_as_of(load_ledger(args.ledger), as_of)
        args.as_of = fmt_date(as_of) if as_of else None
        f = Facts(days, args.kcal_per_kg, args.spike)
        if args.cmd == "trend":
            return cmd_trend(f, args.ledger, args)
        if args.cmd == "reconcile":
            return cmd_reconcile(f, args.ledger, args)
        if args.cmd == "rate":
            return cmd_rate(f, args.ledger, args)
        if args.cmd == "plateau":
            return cmd_plateau(f, args.ledger, args)
        if args.cmd == "report":
            return cmd_report(f, args.ledger, args)
        if args.cmd == "simulate":
            if not args.extra:
                print("simulate needs: continue | intake <kcal>")
                return EXIT_LEDGER
            if args.extra[0] == "continue":
                args.sim = "continue"
                return cmd_simulate(f, args.ledger, args)
            if args.extra[0] == "intake" and len(args.extra) >= 2:
                args.sim = "intake"
                try:
                    args.intake = float(args.extra[1])
                except ValueError:
                    print("intake needs a number")
                    return EXIT_LEDGER
                return cmd_simulate(f, args.ledger, args)
            print("simulate needs: continue | intake <kcal>")
            return EXIT_LEDGER
        if args.cmd == "validate":
            return cmd_validate(f, args.ledger, args)
        return EXIT_LEDGER
    except LedgerError as e:
        print("ledger error: %s" % e, file=sys.stderr)
        return EXIT_LEDGER


if __name__ == "__main__":
    sys.exit(main())
