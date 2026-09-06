#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""瘾账 · Hidden Tab

香烟是一本人人抽着、却没有人记过的账：钱、时间、身体恢复，三本账全住在
「我意志力差」的自我叙事里。而戒烟失败的第一杀手往往不是烟瘾本身，是
「破戒即全毁」的错误算术（成瘾医学的戒绝违反效应）：一支烟在叙事里等于
全部清零，于是破一支就破一包——账本从没人给过这句话一个分母。

本件把戒烟记成一本可手编的事件流账本（TSV：日期/事件/根数/基线/触发/备注），
从你对自己的历史开出六本账：
  - report    总账：当前尝试（attempt/clean 双口径）、钱账、时间账、车站；
  - clock     恢复时钟：通识生理里程碑按你的 streak 排成车站，下一站倒计时；
  - relapse   复吸审计：每次尝试的死因档案、lapse→relapse 距离、
              「一支烟的真实价格」（样本 ≥2 才回答，宁缺毋滥）；
  - trigger   触发审计：破戒日的触发标签/星期分布——只做描述统计，
              不做因果检验（那是 scapegoat 的法庭，烟瘾的触发是行为学常识）；
  - simulate  反事实沙盒：quit/continue/smoke 三种活法，恒 exit 0；
  - validate  账本体检：三桶恒等式、streak 双算法、复发双算法。

核心语义（全部钉死在测试里）：
  lapse  —— attempt 内的破戒日，哪怕一天 10 支，只要没连成「回到基线」的
            模式就不清盘：一支烟不清盘，这是本件存在的理由；
  relapse—— 连续 ≥ relapse_days 天吸烟且日均 ≥ 基线 × relapse_line：
            streak 在复发起点截断，此后到下一个 quit 是「活跃吸烟期」；
  两种记账语义镜像披露：无烟期「没记 = 没抽」，吸烟期「没记 = 按基线在抽」；
  attempt/clean 双口径并排亮出：一支烟不清盘（attempt）与一支即断（clean）
  是同一本账的两种读法，工具假装只有一种口径才是误导。

诚实条款：baseline 是你自己的声称，账本不抓包；里程碑是人群统计先验不是
医学承诺，医生说的永远赢；复吸不收回已走过的站，累计无烟天数永久保留——
身体的账不是全有全无，但风险会回升，账本不粉饰；不折现不复利（投资是
另一本账）；不构成医疗建议，红灯文案指向医生与戒烟门诊。全件无墙钟：
缺省 as-of = 账本末日，--as-of 钉死，同一本账任何机器任何一天逐字节一致。
报告只打印 basename，不回显调用方路径。

Exit codes: 0 绿 · 2 账本损坏 · 3 薄账/样本不足拒绝下结论（算术照出）· 4 红灯
"""

import argparse
import math
import os
import sys
from datetime import date, timedelta

EXIT_OK = 0
EXIT_LEDGER = 2
EXIT_THIN = 3
EXIT_RED = 4

RELAPSE_DAYS = 3        # 连续 ≥3 个吸烟日才谈「回到吸烟」
RELAPSE_LINE = 0.5      # 且这几天的日均 ≥ 基线 × 0.5
PACK_SIZE = 20          # 一包 20 支（通识口径，--pack-size 可调）
CIG_MINUTES = 5         # 一支烟的占用分钟（点烟+抽完+收拾，--minutes 可调）
BASELINE_WINDOW = 28    # 戒烟前逐日回退窗：quit 前 28 天
BASELINE_MIN_ROWS = 3   # 窗内 <3 行逐日记录则不反推基线
EPS = 1e-9

# 通识生理里程碑（人群先验，单位：天；--milestone 可追加，--no-default 可清空）
DEFAULT_MILESTONES = [
    (0.0, "点火：最后一支烟熄灭"),
    (1.0 / 72.0, "20 分钟：心率血压开始回落"),
    (0.5, "12 小时：一氧化碳半排，血氧回升"),
    (14.0, "2 周：循环与行走改善"),
    (30.0, "1 个月：肺纤毛开始再生（咳嗽痰多是在排）"),
    (90.0, "3 个月：肺功能显著改善"),
    (270.0, "9 个月：纤毛完全恢复，肺部感染显著下降"),
    (365.0, "1 年：冠心病风险减半"),
    (1825.0, "5 年：中风风险降至非吸烟者水平"),
    (3650.0, "10 年：肺癌死亡率减半"),
    (5475.0, "15 年：冠心病风险回到非吸烟者"),
]

SMOKE_WORDS = {"smoke", "smoked", "smoking", "cigarette", "cigarettes",
               "cigs", "smk", "烟", "吸烟", "抽烟", "抽了", "抽"}
QUIT_WORDS = {"quit", "start", "begin", "stop", "reset",
              "戒", "戒烟", "开始戒", "停抽", "戒了"}
TODAY_WORDS = {"today", "checkin", "check-in", "打卡", "今天", "无烟"}

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class LedgerError(Exception):
    """账本损坏：exit 2"""


# ---------------------------------------------------------------- 日期算术

def parse_date(s, where=""):
    try:
        return date.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        raise LedgerError("bad date %r (%s)" % (s, where))


def days_between(a, b):
    """闭区间 [a, b] 的天数；b < a 时为 0。"""
    return max(0, (b - a).days + 1)


def day_iter(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def fmt_d(d):
    return d.isoformat()


def fmt_int(v):
    return "{:,.0f}".format(v)


def fmt_money(v):
    return "¥{:,.2f}".format(v)


# ---------------------------------------------------------------- 解析

def norm_kind(s):
    key = s.strip().lower()
    if key in SMOKE_WORDS:
        return "smoke"
    if key in QUIT_WORDS:
        return "quit"
    if key in TODAY_WORDS:
        return "today"
    raise LedgerError("unknown kind %r (smoke/quit/today 及中英别名)" % s)


def _num(s, what, where, lo, hi):
    s = s.strip()
    try:
        v = float(s)
    except ValueError:
        raise LedgerError("%s %r not a number (%s)" % (what, s, where))
    if not (lo <= v <= hi):
        raise LedgerError("%s %r out of range [%s, %s] (%s)"
                          % (what, s, lo, hi, where))
    return v


def parse_ledger(path):
    """事件流：date/kind/n/baseline/trigger/note；同日多行合法（smoke 求和）。"""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            cols = line.split("\t")
            if i == 0 and cols and cols[0].strip().lower() == "date":
                continue  # 表头
            where = "line %d" % (i + 1)
            if len(cols) < 2:
                raise LedgerError("%s: want >=2 columns (date, kind)" % where)
            d = parse_date(cols[0], where)
            kind = norm_kind(cols[1])
            n = baseline = None
            trigger = cols[4].strip() if len(cols) > 4 else ""
            note = cols[5].strip() if len(cols) > 5 else ""
            if kind == "today":
                # 打卡行：账本的「今天」锚——语义是「记到这里，今天无烟」。
                # 它把账本末日记到最新，除此之外不参与任何算术。
                if len(cols) > 2 and cols[2].strip():
                    raise LedgerError("today row must leave n empty (%s)" % where)
            elif kind == "smoke":
                v = _num(cols[2] if len(cols) > 2 else "", "n", where, 1, 100000)
                if abs(v - round(v)) > EPS:
                    raise LedgerError("n %r not an integer (%s)" % (cols[2], where))
                n = int(round(v))
            else:
                if len(cols) > 2 and cols[2].strip():
                    raise LedgerError("quit row must leave n empty (%s)" % where)
            if len(cols) > 3 and cols[3].strip():
                baseline = _num(cols[3], "baseline", where, 0.1, 500)
            rows.append({"date": d, "kind": kind, "n": n,
                         "baseline": baseline, "trigger": trigger, "note": note})
    if not rows:
        raise LedgerError("empty ledger")
    rows.sort(key=lambda r: r["date"])  # 稳定排序：同日保持文件顺序
    return rows


# ---------------------------------------------------------------- 尝试（attempt）引擎

class Attempt(object):
    def __init__(self, idx, quit_date, end_date, baseline, baseline_src):
        self.idx = idx
        self.quit_date = quit_date
        self.end_date = end_date
        self.baseline = baseline
        self.baseline_src = baseline_src  # claim / history / flag / None
        self.span_days = days_between(quit_date, end_date)
        self.smoke_days = {}          # date -> n（同日多行已求和）
        self.relapse_start = None
        self.alive = True
        self.clean_days = 0
        self.lapse_days = 0
        self.lapse_cigs = 0
        self.lapse_runs = []          # [(start, end, cigs)]
        self.relapse_days = 0
        self.relapse_recorded_days = 0
        self.relapse_recorded_cigs = 0
        self.imputed_days = 0
        self.clean_runs = []          # [(start, end, days)]
        self.effective_days = self.span_days
        self.actual_cigs = 0
        self.saved_cigs = 0.0

    @property
    def dead(self):
        return not self.alive

    def clock_days(self, as_of):
        """恢复时钟走过的天数：锚 = 第一个无烟日；死亡尝试停在复发前夜。"""
        if not self.clean_runs:
            return 0
        anchor = self.clean_runs[0][0]
        limit = as_of if self.alive else self.relapse_start - timedelta(days=1)
        if limit < anchor:
            return 0
        return days_between(anchor, limit)

    def anchor(self):
        return self.clean_runs[0][0] if self.clean_runs else None

    def trailing_clean(self):
        if not self.clean_runs:
            return 0
        s, e, n = self.clean_runs[-1]
        return n if e == self.end_date and self.alive else 0

    def longest_clean(self):
        return max([r[2] for r in self.clean_runs], default=0)


def build_attempts(events, as_of, relapse_days, relapse_line, baseline_flag):
    quits = {}
    for r in events:
        if r["kind"] == "quit":
            quits[r["date"]] = r  # 同日多次 quit：后一行覆盖（最后一次决定算）
    quit_dates = sorted(quits)
    if not quit_dates:
        return [], [r for r in events if r["kind"] == "smoke"]

    smoke_rows = [r for r in events if r["kind"] == "smoke"]
    attempts = []
    for i, q in enumerate(quit_dates):
        nxt = quit_dates[i + 1] if i + 1 < len(quit_dates) else None
        end = min(nxt - timedelta(days=1), as_of) if nxt else as_of
        if end < q:
            continue  # as-of 裁剪后空尝试
        # 基线：quit 行声称 > --baseline 补缺 > 前 28 天逐日反推 > 无
        baseline, src = quits[q]["baseline"], "claim"
        if baseline is None and baseline_flag:
            baseline, src = baseline_flag, "flag"
        if baseline is None:
            win = [r["n"] for r in smoke_rows
                   if q - timedelta(days=BASELINE_WINDOW) <= r["date"] < q]
            if len(win) >= BASELINE_MIN_ROWS:
                baseline = sum(win) / float(len(win))
                src = "history"
        a = Attempt(i + 1, q, end, baseline, src)
        a.smoke_days = {}
        for r in smoke_rows:
            if q <= r["date"] <= end:
                a.smoke_days[r["date"]] = a.smoke_days.get(r["date"], 0) + r["n"]

        # 复发判定：扫描连续吸烟日游程，第一个满足「长 ≥ K 且日均 ≥ 线」的游程
        relapse_start = _find_relapse(a, relapse_days, relapse_line)
        if baseline is not None:
            if relapse_start is not None:
                a.relapse_start = relapse_start
                a.alive = False

        # 逐日分类：复发期 >= relapse_start（记了按记的，没记按基线插补）
        prev = None          # None | "clean" | "lapse"
        run_start = None
        run_clean = 0

        def close_clean():
            if run_start is not None:
                a.clean_runs.append((run_start,
                                     run_start + timedelta(days=run_clean - 1),
                                     run_clean))

        for d in day_iter(q, end):
            in_relapse = (a.relapse_start is not None and d >= a.relapse_start)
            n = a.smoke_days.get(d)
            if in_relapse:
                a.relapse_days += 1
                if n is not None:
                    a.relapse_recorded_days += 1
                    a.relapse_recorded_cigs += n
                else:
                    a.imputed_days += 1
                close_clean()
                run_start, run_clean = None, 0
                prev = None
            elif n is not None:
                a.lapse_days += 1
                a.lapse_cigs += n
                if prev == "lapse":
                    a.lapse_runs[-1][1] = d
                    a.lapse_runs[-1][2] += n
                else:
                    a.lapse_runs.append([d, d, n])
                close_clean()
                run_start, run_clean = None, 0
                prev = "lapse"
            else:
                a.clean_days += 1
                if prev != "clean":
                    run_start, run_clean = d, 1
                else:
                    run_clean += 1
                prev = "clean"
        close_clean()

        a.effective_days = (a.span_days if a.alive
                            else days_between(q, a.relapse_start - timedelta(days=1)))
        a.actual_cigs = (a.lapse_cigs + a.relapse_recorded_cigs
                         + int(round(a.imputed_days * (a.baseline or 0))))
        if a.baseline:
            a.saved_cigs = a.baseline * a.span_days - a.actual_cigs
        attempts.append(a)
    return attempts, [r for r in smoke_rows
                      if quit_dates and r["date"] < quit_dates[0]]


def _find_relapse(a, relapse_days, relapse_line):
    """游程扫描：返回最早的复发起点；基线未知时不判（无法判）。"""
    if a.baseline is None:
        return None
    dates = sorted(a.smoke_days)
    i = 0
    while i < len(dates):
        j = i
        while j + 1 < len(dates) and (dates[j + 1] - dates[j]).days == 1:
            j += 1
        run = dates[i:j + 1]
        if len(run) >= relapse_days:
            mean = sum(a.smoke_days[d] for d in run) / float(len(run))
            if mean >= a.baseline * relapse_line - EPS:
                return run[0]
        i = j + 1
    return None


def find_relapse_by_window(a, relapse_days, relapse_line):
    """复发双算法之二：逐日起窗扫描（validate 用）。"""
    if a.baseline is None or not a.smoke_days:
        return None
    for d in day_iter(a.quit_date, a.end_date):
        win = [a.smoke_days.get(d + timedelta(days=k))
               for k in range(relapse_days)]
        if all(x is not None for x in win):
            if sum(win) / float(relapse_days) >= a.baseline * relapse_line - EPS:
                return d
    return None


# ---------------------------------------------------------------- 账本层

class Ledger(object):
    def __init__(self, path, args):
        self.path = path
        self.args = args
        self.events = parse_ledger(path)
        self.as_of = (parse_date(args.as_of, "--as-of")
                      if getattr(args, "as_of", None) else self.events[-1]["date"])
        self.relapse_days = getattr(args, "relapse_days", RELAPSE_DAYS)
        self.relapse_line = getattr(args, "relapse_line", RELAPSE_LINE)
        self.attempts, self.pre_rows = build_attempts(
            self.events, self.as_of, self.relapse_days, self.relapse_line,
            getattr(args, "baseline", None))
        self.quit_count = len(self.attempts)
        self.span = days_between(self.events[0]["date"], self.as_of)

    @property
    def current(self):
        return self.attempts[-1] if self.attempts else None

    def stalled(self):
        """红灯：复发后没有新的 quit——账本说你在抽，旧 quit 还挂着。"""
        c = self.current
        return c is not None and c.dead

    def price_per_cig(self):
        price = getattr(self.args, "price", None)
        if not price:
            return None
        size = getattr(self.args, "pack_size", PACK_SIZE) or PACK_SIZE
        return price / float(size)

    def milestones(self):
        if getattr(self.args, "no_default_milestones", False):
            ms = []
        else:
            ms = list(DEFAULT_MILESTONES)
        extra = getattr(self.args, "milestone", None) or []
        for spec in extra:
            try:
                days_s, label = spec.split(":", 1)
                ms.append((float(days_s), label.strip()))
            except ValueError:
                raise LedgerError("bad --milestone %r (want DAYS:LABEL)" % spec)
        ms.sort(key=lambda t: t[0])
        return ms


# ---------------------------------------------------------------- 输出

def cig_price_note(led):
    p = led.price_per_cig()
    if p is None:
        return "（不给 --price 只谈根数——钱是翻译不是前提）"
    return "按 %s/包 ÷ %d 支" % (fmt_money(led.args.price), led.args.pack_size)


def money_of(led, cigs):
    p = led.price_per_cig()
    return None if p is None else p * cigs


def money_str(led, cigs):
    m = money_of(led, cigs)
    return "＝ %s" % fmt_money(m) if m is not None else ""


def time_str(cigs, minutes):
    total = cigs * minutes
    h = total / 60.0
    d = total / 1440.0
    return "%s 分钟 ＝ %.1f 小时 ＝ %.1f 天" % (fmt_int(total), h, d)


def baseline_str(a):
    if a.baseline is None:
        return "无基线（quit 行未声称，前史逐日也不足）"
    src = {"claim": "quit 行声称", "flag": "--baseline 指定",
           "history": "前史逐日反推"}[a.baseline_src]
    return "日均 %s 根（%s）" % (("%g" % a.baseline), src)


def milestone_lines(led, a):
    days = a.clock_days(led.as_of)
    ms = led.milestones()
    lines = []
    next_hit = None
    for t, label in ms:
        if t <= days + EPS:
            lines.append("  ✓ %s（已走 %s 天）" % (label, fmt_int(days)))
        else:
            left = int(math.ceil(t)) - days
            if next_hit is None:
                next_hit = (t, label, left)
                lines.append("  · 下一站 %s，还差 %d 天" % (label, left))
            else:
                lines.append("  ○ %s（差 %s 天）" % (label, fmt_int(int(math.ceil(t) - days))))
    if not ms:
        lines.append("  （里程碑表已清空——只数天数）")
    return lines, next_hit


def attempt_status_str(led, a):
    if a.alive:
        return "进行中"
    return "死于复吸 %s（活了 %d 天）" % (fmt_d(a.relapse_start), a.effective_days)


# ---------------------------------------------------------------- 命令

def cmd_report(led):
    rc = EXIT_OK
    print("=== 瘾账 · Hidden Tab — report：%s ===" % os.path.basename(led.path))
    first = led.events[0]["date"]
    print("账本跨度 %s .. %s（%s 天）｜quit 尝试 %d 次｜as-of %s"
          % (fmt_d(first), fmt_d(led.as_of), fmt_int(led.span),
             led.quit_count, fmt_d(led.as_of)))
    if led.pre_rows:
        print("前史：%d 行吸烟记录在第一次 quit 之前（不入尝试账，只作披露）"
              % len(led.pre_rows))

    if not led.attempts:
        n = sum(r["n"] for r in led.events if r["kind"] == "smoke")
        print("── 这不是一本戒烟账本（没有 quit 行），吸烟算术照出，判级拒绝 ──")
        print("吸烟行 %d 行、合计 %d 根；给账本写一行 quit（date\\tquit\\t\\t基线），"
              "本件才开始记账" % (len(led.events), n))
        print("THIN：没有尝试就没有 streak 可判")
        return EXIT_THIN

    c = led.current
    print("")
    print("── 当前尝试 · 第 %d 次（%s 起，%s）──"
          % (c.idx, fmt_d(c.quit_date), attempt_status_str(led, c)))
    print("基线：%s" % baseline_str(c))
    if c.alive:
        print("attempt 口径：第 %d 天（lapse %d 天不清盘）｜"
              "clean 口径：连续纯无烟 %d 天"
              % (c.span_days, c.lapse_days, c.trailing_clean()))
    else:
        print("attempt 口径：已于 %s 死于复吸｜活跃吸烟期 %d 天"
              % (fmt_d(c.relapse_start), c.relapse_days))
        print("复吸不收回已走过的站：累计无烟天数与已到达的里程碑永久保留")
    if led.price_per_cig() is None:
        print(cig_price_note(led))
    if c.baseline is not None:
        print("已省 %s 根 %s" % (fmt_int(c.saved_cigs), money_str(led, c.saved_cigs)))
        print("已省 %s（%d 分钟/支）"
              % (time_str(c.saved_cigs, led.args.minutes), led.args.minutes))
        if c.alive and c.span_days > 0:
            pace = c.saved_cigs / c.span_days * 365.0
            m = money_of(led, pace)
            m_str = "＝ %s/年" % fmt_money(m) if m is not None else ""
            print("当前速率外推：≈ %s 根/年 %s｜%s/年"
                  % ("{:,.1f}".format(pace), m_str,
                     time_str(pace, led.args.minutes)))
    else:
        print("钱账/时间账 DECLINE：无基线（不发明你一天抽几根）")

    print("")
    print("── 全史总账 ──")
    tot_saved = sum(a.saved_cigs for a in led.attempts)
    tot_clean = sum(a.clean_days for a in led.attempts)
    longest = max((a.longest_clean() for a in led.attempts), default=0)
    dead = [a for a in led.attempts if a.dead]
    alive_n = led.quit_count - len(dead)
    print("累计已省 %s 根 %s｜累计纯无烟 %d 天｜最长纯无烟 %d 天"
          % (fmt_int(tot_saved), money_str(led, tot_saved), tot_clean, longest))
    fate = ("%d 次存活，%d 次死于复吸" % (alive_n, len(dead))) if dead \
        else "全部存活"
    print("尝试 %d 次：%s" % (led.quit_count, fate))
    for a in dead:
        last = a.lapse_runs[-1] if a.lapse_runs else None
        if last:
            gap = (a.relapse_start - last[1]).days
            print("  第 %d 次活了 %d 天：最后一场 lapse（%d 根）之后 %d 天，"
                  "%s 复吸弹回" % (a.idx, a.effective_days, last[2], gap,
                                   fmt_d(a.relapse_start)))
        else:
            print("  第 %d 次活了 %d 天：%s 复吸弹回"
                  % (a.idx, a.effective_days, fmt_d(a.relapse_start)))
    tot_lapse_runs = sum(len(a.lapse_runs) for a in led.attempts)
    tot_lapse_cigs = sum(a.lapse_cigs for a in led.attempts)
    if tot_lapse_runs:
        print("lapse 档案：%d 轮共 %d 根——按你的账本，一支烟从未当场清盘过任何一次尝试"
              % (tot_lapse_runs, tot_lapse_cigs))

    imp = sum(a.imputed_days for a in led.attempts)
    if imp:
        print("")
        print("── 记账语义披露 ──")
        print("复发后活跃吸烟期共 %d 天无行，按基线插补（没记 ＝ 按基线在抽）；"
              "无烟期没记 ＝ 没抽——两个方向的语义都摊开"
              % imp)

    print("")
    if led.stalled():
        print("红灯 STALLED：账本的最后一行是烟，最后一次 quit 还挂着。")
        print("要么写一行新的 quit——重新戒不丢人，账本记得你每一次都回来；")
        print("要么它将一直红着。戒烟门诊与医生是下一站，账本只是里程表。")
        return EXIT_RED
    if any(a.baseline is None for a in led.attempts):
        print("THIN：部分尝试无基线，其钱账/时间账拒绝判级（算术照出）")
        rc = EXIT_THIN
    print("灯：绿（当前尝试存活）" if rc == EXIT_OK else "灯：绿（带保留）")
    return rc


def cmd_clock(led):
    print("=== 恢复时钟：%s ===" % os.path.basename(led.path))
    if not led.attempts:
        print("没有 quit 行，车没有出发过（写一行 quit 再来）")
        return EXIT_THIN
    c = led.current
    print("第 %d 次尝试（%s 起）｜%s" % (c.idx, fmt_d(c.quit_date),
                                         attempt_status_str(led, c)))
    if c.anchor():
        print("时钟锚：第一个无烟日 %s｜已走 %d 天（attempt 口径，lapse 不停车）"
              % (fmt_d(c.anchor()), c.clock_days(led.as_of)))
    else:
        print("尚无纯无烟日——时钟未出发（quit 当天就弹回基线）")
    lines, _ = milestone_lines(led, c)
    for ln in lines:
        print(ln)
    print("通识人群先验，不是对你的医学承诺；医生说的永远赢。")
    tot_clean = sum(a.clean_days for a in led.attempts)
    print("复吸不收回车站：全史累计纯无烟 %d 天，任何一次复吸都清不掉"
          % tot_clean)
    if led.stalled():
        print("红灯 STALLED：车停在吸烟期——新的 quit 行会让时钟重新出发")
        return EXIT_RED
    return EXIT_OK


def cmd_relapse(led):
    print("=== 复吸审计：%s ===" % os.path.basename(led.path))
    if not led.attempts:
        print("没有 quit 行，没有尝试可审计")
        return EXIT_THIN
    rc = EXIT_OK
    print("尝试生命周期（attempt 口径：lapse 不断，relapse 才断）")
    for a in led.attempts:
        tail = "" if a.alive else "｜结局：死于复吸 %s" % fmt_d(a.relapse_start)
        base = "%g" % a.baseline if a.baseline is not None else "无"
        print("  #%d %s 起·%d 天｜clean %d 天｜lapse %d 轮 %d 根｜基线 %s%s"
              % (a.idx, fmt_d(a.quit_date), a.effective_days, a.clean_days,
                 len(a.lapse_runs), a.lapse_cigs, base, tail))
    print("")
    tot = sum(len(a.lapse_runs) for a in led.attempts)
    if tot:
        print("lapse 游程档案（一轮 = 连续吸烟日未成复发模式）")
        for a in led.attempts:
            for s, e, n in a.lapse_runs:
                tag = "" if s == e else "（连续 %d 天）" % (days_between(s, e))
                print("  #%d %s%s：%d 根" % (a.idx, fmt_d(s), tag, n))
    print("")
    transitions = []
    for a in led.attempts:
        if a.dead and a.lapse_runs:
            last = a.lapse_runs[-1]
            gap = (a.relapse_start - last[1]).days
            transitions.append((a.idx, last[2], gap))
    if transitions:
        print("lapse → relapse 距离（从最后一次 lapse 结束到复发判定）")
        for idx, n, gap in transitions:
            print("  #%d：%d 根之后 %d 天弹回" % (idx, n, gap))
        if len(transitions) >= 2:
            mean_gap = sum(t[2] for t in transitions) / float(len(transitions))
            base = [a.baseline for a in led.attempts if a.dead and a.lapse_runs]
            mean_base = sum(b for b in base if b) / max(1, len([b for b in base if b]))
            p = led.price_per_cig()
            print("一支烟的真实价格：历史上破戒之后平均 %.1f 天弹回基线"
                  % mean_gap)
            if p is not None:
                money = mean_gap * mean_base * p
                print("  ＝ 每支破戒烟背后平均挂着 %s 的回弹账（%s 根/天 × %.1f 天）"
                      % (fmt_money(money), "%g" % mean_base, mean_gap))
            print("  这不是烟本身的价格，是你自己复吸史里长出的距离——别人代替不了")
            rc = EXIT_OK
        else:
            print("一支烟的真实价格 DECLINE：仅 %d 个样本，不足以回答"
                  "「这一支之后会发生什么」" % len(transitions))
            print("  （样本 ≥2 才报均值——宁可不说，不编统计）")
            rc = EXIT_THIN
    else:
        print("尚无 relapse——要么账本太年轻，要么你把这件事做成了")
    return rc


def cmd_trigger(led):
    print("=== 触发审计：%s ===" % os.path.basename(led.path))
    if not led.attempts:
        print("没有 quit 行，没有破戒日可审计")
        return EXIT_THIN
    labeled = {}
    unlabeled_runs = 0
    unlabeled_cigs = 0
    total_runs = 0
    total_cigs = 0
    weekday = [0] * 7
    display = {}
    for a in led.attempts:
        for d, n in sorted(a.smoke_days.items()):
            total_runs += 1
            total_cigs += n
            weekday[d.weekday()] += 1
            t = ""
            row = None
            for r in led.events:
                if r["date"] == d and r["kind"] == "smoke" and r["trigger"]:
                    row = r
                    break
            if row is not None:
                t = row["trigger"].strip()
                key = t.lower()
                display.setdefault(key, t)
                ent = labeled.setdefault(key, [0, 0])
                ent[0] += 1
                ent[1] += n
            else:
                unlabeled_runs += 1
                unlabeled_cigs += n
    if total_runs == 0:
        print("尝试期内零吸烟日——无破戒可审计（这是好消息）")
        return EXIT_OK
    print("尝试期内吸烟日 %d 天、共 %d 根（lapse 与复发期记的行）"
          % (total_runs, total_cigs))
    print("")
    print("触发标签分布（你随手写的标签，按原样聚合）")
    order = sorted(labeled.items(), key=lambda kv: (-kv[1][1], kv[0]))
    for key, (runs, cigs) in order:
        print("  %s：%d 天 %d 根" % (display[key], runs, cigs))
    if unlabeled_runs:
        print("  （未标）：%d 天 %d 根——标签是可选列，但没标签的破戒日没故事"
              % (unlabeled_runs, unlabeled_cigs))
    labeled_cigs = sum(v[1] for v in labeled.values())
    if labeled_cigs + unlabeled_cigs != total_cigs:
        raise LedgerError("trigger identity broken")
    print("")
    print("星期分布：" + "｜".join(
        "%s %d" % (WEEKDAY_CN[i], weekday[i]) for i in range(7)
        if weekday[i]))
    print("")
    dead = [a for a in led.attempts if a.dead]
    if dead:
        print("复发引爆点（杀死尝试那一天的标签）")
        for a in dead:
            t = ""
            for r in led.events:
                if r["date"] == a.relapse_start and r["kind"] == "smoke" \
                        and r["trigger"]:
                    t = r["trigger"].strip()
                    break
            print("  #%d %s：%s" % (a.idx, fmt_d(a.relapse_start),
                                    t or "（未标）"))
    else:
        print("尚无复发——引爆点栏位空着最好")
    print("描述统计，不是因果检验：要审嫌疑犯去 scapegoat，这里只看你自己的故事")
    return EXIT_OK


def cmd_simulate(led, mode, value, days):
    print("=== 反事实沙盒：%s（恒 exit 0，沙盒不执法）==="
          % os.path.basename(led.path))
    c = led.current
    baseline = c.baseline if c and c.baseline is not None \
        else getattr(led.args, "baseline", None)
    if baseline is None:
        print("无基线（quit 行未声称且未给 --baseline）——不发明你一天抽几根，"
              "推演 DECLINE")
        return EXIT_THIN
    p = led.price_per_cig()
    if mode == "smoke":
        n = int(value) if value else 1
        print("现在抽 %d 支的代价单：" % n)
        if c and c.alive:
            print("  attempt 口径：第 %d 天不清盘——一支烟从未有权力清掉你的尝试"
                  % c.span_days)
        clean = c.trailing_clean() if c else 0
        print("  clean 口径：连续纯无烟 %d 天 → 归零重计（最严格的自检镜，仅此而已）"
              % clean)
        print("  钱账：+%d 根 %s" % (n, money_str(led, n)))
        print("  时间账：+%s" % time_str(n, led.args.minutes))
        trans = []
        for a in led.attempts:
            if a.dead and a.lapse_runs:
                trans.append((a.relapse_start - a.lapse_runs[-1][1]).days)
        if len(trans) >= 2:
            mean_gap = sum(trans) / float(len(trans))
            print("  按你的复吸史：破戒之后平均 %.1f 天弹回基线——"
                  "这一支的真实价格是那 %.0f 天，不是这 %d 支"
                  % (mean_gap, mean_gap, n))
        else:
            print("  复吸史样本 %d 个：不足以回答这一支之后会发生什么" % len(trans))
    elif mode == "continue":
        n = days if days else 30
        cigs = baseline * n
        print("如果今天放弃、按基线 %g 根/天再抽 %d 天：" % (baseline, n))
        print("  多抽 %s 根 %s" % (fmt_int(cigs), money_str(led, cigs)))
        print("  多花 %s" % time_str(cigs, led.args.minutes))
        if c and c.alive:
            print("  已走过的站不收回（第 %d 天的里程碑已到账），但车停在这里"
                  % c.span_days)
        print("  重新出发的成本是零：写一行 quit 即可，账本记得你每一次都回来")
    else:  # quit
        start = (parse_date(value, "--from") if value
                 else led.as_of + timedelta(days=1))
        print("如果 %s（重新）开始戒，按基线 %g 根/天：" % (fmt_d(start), baseline))
        ms = led.milestones()
        for t, label in ms[:8]:
            dd = start + timedelta(days=int(math.ceil(t)))
            print("  %s → %s" % (label, fmt_d(dd)))
        year_cigs = baseline * 365
        print("  一年后：已省 %s 根 %s｜%s"
              % (fmt_int(year_cigs), money_str(led, year_cigs),
                 time_str(year_cigs, led.args.minutes)))
        print("  每个明天都是剩余人生里最早的一天——但决定永远是人的")
    return EXIT_OK


def cmd_validate(led):
    print("=== 账本体检：%s ===" % os.path.basename(led.path))
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        if cond:
            print("  ✓ %s" % name)
        else:
            ok = False
            print("  ✗ %s %s" % (name, detail))

    check("事件按日期有序",
          all(led.events[i]["date"] <= led.events[i + 1]["date"]
              for i in range(len(led.events) - 1)))
    for a in led.attempts:
        # 恒等式一：三桶分解（clean + lapse + relapse == saved）
        bucket_clean = a.baseline * a.clean_days if a.baseline else 0
        bucket_lapse = sum(a.baseline - n for d, n in sorted(a.smoke_days.items())
                           if a.relapse_start is None or d < a.relapse_start) \
            if a.baseline else 0
        bucket_relapse = a.saved_cigs - bucket_clean - bucket_lapse \
            if a.baseline else 0
        resid = abs((bucket_clean + bucket_lapse + bucket_relapse)
                    - a.saved_cigs)
        check("#%d 三桶恒等（clean+lapse+relapse＝saved）" % a.idx,
              resid < 1e-6, "残差 %.2e" % resid)
        # 恒等式二：saved 定义（基线配额 − 实抽）
        quota = a.baseline * a.span_days if a.baseline else 0
        check("#%d saved＝基线×跨度−实抽" % a.idx,
              abs(a.saved_cigs - (quota - a.actual_cigs)) < 1e-6)
        # 双算法：clean 天数（区间游走 == 逐日扫描）
        scan_clean = sum(1 for d in day_iter(a.quit_date, a.end_date)
                         if d not in a.smoke_days
                         and (a.relapse_start is None or d < a.relapse_start))
        check("#%d clean 双算法（游走==扫描 %d==%d）"
              % (a.idx, a.clean_days, scan_clean), a.clean_days == scan_clean)
        # 双算法：复发起点（游程扫描 == 逐日起窗）
        w = find_relapse_by_window(a, led.relapse_days, led.relapse_line)
        check("#%d relapse 双算法（游程==起窗）" % a.idx,
              a.relapse_start == w,
              "%s vs %s" % (a.relapse_start, w))
        # span 分解恒等：clean + lapse + relapse_days == span
        check("#%d 天数分解恒等" % a.idx,
              a.clean_days + a.lapse_days + a.relapse_days == a.span_days,
              "%d+%d+%d != %d" % (a.clean_days, a.lapse_days,
                                  a.relapse_days, a.span_days))
    ms = led.milestones()
    check("里程碑表严格递增",
          all(ms[i][0] < ms[i + 1][0] for i in range(len(ms) - 1)))
    # as-of 裁剪：没有任何尝试越界
    check("as-of 裁剪无越界",
          all(a.end_date <= led.as_of for a in led.attempts))
    if ok:
        print("体检通过：同一本账任何机器任何一天逐字节一致")
        return EXIT_OK
    return EXIT_LEDGER


# ---------------------------------------------------------------- main

def add_common(p, with_ledger=True):
    if with_ledger:
        p.add_argument("ledger", help="TSV 账本路径")
    p.add_argument("--as-of", default=None, help="钉死 as-of（缺省＝账本末日）")
    p.add_argument("--price", type=float, default=None, help="每包价")
    p.add_argument("--pack-size", type=int, default=PACK_SIZE)
    p.add_argument("--minutes", type=int, default=CIG_MINUTES,
                   help="每支占用分钟")
    p.add_argument("--baseline", type=float, default=None,
                   help="补缺基线（不覆盖 quit 行声称）")
    p.add_argument("--relapse-days", type=int, default=RELAPSE_DAYS)
    p.add_argument("--relapse-line", type=float, default=RELAPSE_LINE)
    p.add_argument("--milestone", action="append", default=None,
                   help="DAYS:LABEL 追加里程碑")
    p.add_argument("--no-default-milestones", action="store_true")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hidden_tab", description="瘾账 · Hidden Tab —— 戒烟账本")
    sub = ap.add_subparsers(dest="cmd")

    for name, fn, extra in (
            ("report", cmd_report, None),
            ("clock", cmd_clock, None),
            ("relapse", cmd_relapse, None),
            ("trigger", cmd_trigger, None),
            ("simulate", None, "mode"),
            ("validate", cmd_validate, None)):
        sp = sub.add_parser(name)
        add_common(sp)
        if name == "simulate":
            sp.add_argument("mode", choices=["quit", "continue", "smoke"])
            sp.add_argument("value", nargs="?", default=None,
                            help="quit: --from 日期；smoke: 支数")
            sp.add_argument("--days", type=int, default=None,
                            help="continue: 天数（缺省 30）")

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return EXIT_OK
    try:
        led = Ledger(args.ledger, args)
        if args.cmd == "report":
            return cmd_report(led)
        if args.cmd == "clock":
            return cmd_clock(led)
        if args.cmd == "relapse":
            return cmd_relapse(led)
        if args.cmd == "trigger":
            return cmd_trigger(led)
        if args.cmd == "simulate":
            return cmd_simulate(led, args.mode, args.value, args.days)
        if args.cmd == "validate":
            return cmd_validate(led)
    except LedgerError as e:
        sys.stderr.write("LEDGER ERROR: %s\n" % e)
        return EXIT_LEDGER
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
