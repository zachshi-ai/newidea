#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
未兑现 · Unvested / 期权与 RSU 的归属账本。

股权是工资之外的另一半报酬,却是唯一没有人替你记账的报酬:授予协议 PDF 躺进
邮箱的那天之后,再没有任何日历提醒归属节点——cliff 是悬崖(悬崖前离职一分不
得),未归属的股份在你提离职那天整体作废,而已归属未行权的期权通常只有几十天
行权窗口,窗口一关,连已经「挣到手」的部分也归零。平台只给一张日程表:不给作
废倒计时、不给行权现金需求、不给「纸面 ≠ 到手 ≠ 落袋」的翻译,更没有一本把
换过的每家公司并排的总账。星尘的教训写在样例账本里:27,000 股已归属,90 天窗
口没行权,净代价 ¥197,100——这笔损失无人替你记账。

本件把授予条款抄成可手编账本,开出四本账:

  report   归属总账——三种形态(在册纸面/已落袋/已作废)+ 灯
  exit     离职推演——到 --date 那天带走多少、作废多少、行权要掏多少现金
  clock    倒计时与归属日历——下一个节点、cliff、行权窗口、期权大限
  validate 恒等式与账本体检——总股数 ≡ 六桶之和,双路径对拍

诚实条款:纸面市值按 latest_price(最新一轮/回购价)计算,未上市股份没有流动
性,优先股价格和你的普通股之间隔着清算优先权;归属/行权的税务不建模;加速条
款(single/double trigger)不在公式里——授予协议永远赢,律所永远赢。它不建
议你走或不走、行权或放弃,日历只摆事实,决定是人的。

零墙钟: as-of 缺省 = 三本账所有日期的最大值;同一本账任何机器任何一天逐字节
一致。股权是最敏感的财产数据:不连任何接口,不上传任何字节,报告只打印账本
目录名。

账本(--dir 目录下三份 TSV):
  grants.tsv   company/kind/grant_date/shares/strike/vest_years/cliff_months/
               interval/status/end_date/window_days/latest_price/price_date/note
               (核心账,必需;同公司多份授予合法——top-up,事件按授予日 FIFO)
  events.tsv   date/company/event/shares/price/note
               (可缺席=无事件;exercise 行权 | tender 变现落袋)
  schedule.tsv company/date/shares
               (可缺席=按公式;出现即整表覆盖该公司的公式日程——授予协议永远
                赢过公式,performance vest 抄这里)
"""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

GRANT_COLS = ("company", "kind", "grant_date", "shares", "strike", "vest_years",
              "cliff_months", "interval", "status", "end_date", "window_days",
              "latest_price", "price_date", "note")
EVENT_COLS = ("date", "company", "event", "shares", "price", "note")
SCHED_COLS = ("company", "date", "shares")

KINDS = ("option", "rsu")
STATUSES = ("active", "left", "dead")
INTERVALS = {"monthly": 1, "quarterly": 3, "annual": 12}
EVENTS = ("exercise", "tender")

# 通识先验,全部 -- 可翻案;条款以授予协议为准,律所永远赢。
DEF_VEST_YEARS = 4        # 最常见的 4 年归属
DEF_CLIFF_MONTHS = 12     # 最常见的 1 年悬崖
DEF_INTERVAL = "quarterly"
DEF_WINDOW_DAYS = 90      # 离职后行权窗口的通识口径(30–90 天都常见)
DEF_TERM_YEARS = 10       # 期权有效期大限(授予日起 10 年)
DEF_WARN_DAYS = 30        # 窗口剩余 < 此线且未行权 → 🔴(恰线不亮)
DEF_STALE_DAYS = 548      # 价格老于此线(≈18 个月)→ 🟡 STALE-PRICE 旧地图
DEF_CLIFF_DAYS = 180      # cliff 落在此窗内 → 🟡 CLIFF-AHEAD
DEF_CLIFF_MIN_PCT = 0.10  # cliff 股数占授予 ≥ 10% 才点名
DEF_MONTHS = 12           # clock 归属日历的展望窗


class LedgerError(Exception):
    """账坏——数据自相矛盾或引用悬空,拒绝载入(exit 2)。"""


class EmptyLedger(Exception):
    """空账——第一次打开,教建第一行(exit 3)。"""


# ---------------------------------------------------------------- 基础工具

def parse_date(s, what):
    if not DATE_RE.match(s or ""):
        raise LedgerError("%s 日期必须是补零的 YYYY-MM-DD: %r" % (what, s))
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise LedgerError("%s 不是存在的日历日: %s" % (what, s))


def fmt_d(d):
    return d.strftime("%Y-%m-%d")


def add_months(d, n):
    """加 n 个自然月,月末钳制(01-31 加 1 个月 = 02-28)。"""
    total = (d.year * 12 + d.month - 1) + n
    y, m0 = divmod(total, 12)
    m = m0 + 1
    day = d.day
    while day > 28:
        try:
            return d.replace(year=y, month=m, day=day)
        except ValueError:
            day -= 1
    return d.replace(year=y, month=m, day=day)


def read_tsv(path, cols, name):
    """读 TSV,返回 (rows, exists)。缺文件返回 ([], False)——缺席是否合法由调用方定。"""
    if not os.path.exists(path):
        return [], False
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    body = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not body:
        return [], True
    header = [h.strip() for h in body[0].split("\t")]
    if header != list(cols):
        raise LedgerError("%s 表头必须是: %s(实为 %s)"
                          % (name, "/".join(cols), "/".join(header)))
    rows = []
    for i, ln in enumerate(body[1:], start=2):
        parts = ln.split("\t")
        if len(parts) > len(cols) and any(p.strip() for p in parts[len(cols):]):
            raise LedgerError("%s 第 %d 行列数超出表头" % (name, i))
        parts += [""] * (len(cols) - len(parts))
        rows.append(dict(zip(cols, [p.strip() for p in parts])))
    return rows, True


def fmt_shares(n):
    return "{:,}".format(int(n))


def fmt_money(x):
    x = round(x + 0.0, 2)
    if abs(x - round(x)) < 1e-9:
        return "¥{:,.0f}".format(int(round(x)))
    return "¥{:,.2f}".format(x)


def fmt_pct(x):
    return "{:.1f}%".format(x * 100)


def fmt_days(n):
    if n == 0:
        return "就是今天"
    if n == 1:
        return "明天"
    return "%d 天" % n


def fmt_after(n):
    if n == 0:
        return "就是今天"
    if n == 1:
        return "明天"
    return "%d 天后" % n


def blank(v):
    return v == "" or v is None


def to_int(v, what):
    if blank(v):
        return None
    try:
        return int(v)
    except ValueError:
        raise LedgerError("%s 必须是整数: %r" % (what, v))


def to_float(v, what):
    if blank(v):
        return None
    try:
        return float(v)
    except ValueError:
        raise LedgerError("%s 必须是数字: %r" % (what, v))


# ---------------------------------------------------------------- 账本载入

class Grant(object):
    __slots__ = ("company", "kind", "grant_date", "shares", "strike", "vest_years",
                 "cliff_months", "interval", "status", "end_date", "window_days",
                 "latest_price", "price_date", "note", "row", "nodes", "total_months")

    def __init__(self, row):
        self.row = row
        self.company = row["company"]
        if not self.company:
            raise LedgerError("company 不能为空")
        self.kind = row["kind"]
        if self.kind not in KINDS:
            raise LedgerError("未知 kind %r(option|rsu): %s" % (self.kind, self.company))
        self.grant_date = parse_date(row["grant_date"], "%s grant_date" % self.company)
        self.shares = to_int(row["shares"], "%s shares" % self.company)
        if self.shares is None or self.shares <= 0:
            raise LedgerError("%s shares 必须是正整数: %r" % (self.company, row["shares"]))
        self.strike = to_float(row["strike"], "%s strike" % self.company)
        if self.kind == "option":
            if self.strike is None:
                raise LedgerError("%s 是 option,strike(行权价)不能不填——它是期权变成你的价格;rsu 填 0"
                                  % self.company)
            if self.strike < 0:
                raise LedgerError("%s strike 不能为负" % self.company)
        else:
            if not blank(row["strike"]) and self.strike != 0:
                raise LedgerError("%s 是 rsu,没有行权价,strike 应填 0 或留空" % self.company)
            self.strike = 0.0
        self.vest_years = to_float(row["vest_years"], "%s vest_years" % self.company)
        if self.vest_years is None:
            self.vest_years = DEF_VEST_YEARS
        if self.vest_years <= 0:
            raise LedgerError("%s vest_years 必须为正" % self.company)
        self.total_months = int(round(self.vest_years * 12))
        if self.total_months < 1:
            raise LedgerError("%s vest_years 太短,不足一个月" % self.company)
        self.cliff_months = to_int(row["cliff_months"], "%s cliff_months" % self.company)
        if self.cliff_months is None:
            self.cliff_months = DEF_CLIFF_MONTHS
        if self.cliff_months < 0 or self.cliff_months > self.total_months:
            raise LedgerError("%s cliff_months 必须在 0..%d 之间: %s"
                              % (self.company, self.total_months, self.cliff_months))
        self.interval = row["interval"] or DEF_INTERVAL
        if self.interval not in INTERVALS:
            raise LedgerError("未知 interval %r(monthly|quarterly|annual): %s"
                              % (self.interval, self.company))
        self.status = row["status"]
        if self.status not in STATUSES:
            raise LedgerError("未知 status %r(active|left|dead): %s" % (self.status, self.company))
        self.end_date = None
        if self.status in ("left", "dead"):
            if blank(row["end_date"]):
                raise LedgerError("%s status=%s 时 end_date 不能不填——账本不替你猜公司哪天离开/死掉"
                                  % (self.company, self.status))
            self.end_date = parse_date(row["end_date"], "%s end_date" % self.company)
            if self.end_date < self.grant_date:
                raise LedgerError("%s end_date(%s)早于 grant_date(%s)"
                                  % (self.company, row["end_date"], row["grant_date"]))
        elif not blank(row["end_date"]):
            raise LedgerError("%s status=active 时 end_date 应留空" % self.company)
        if self.kind == "rsu" and not blank(row["window_days"]):
            raise LedgerError("%s 是 rsu,没有行权窗口,window_days 应留空" % self.company)
        self.window_days = to_int(row["window_days"], "%s window_days" % self.company)
        if self.window_days is None:
            self.window_days = DEF_WINDOW_DAYS if self.kind == "option" else None
        elif self.window_days <= 0:
            raise LedgerError("%s window_days 必须为正整数" % self.company)
        self.latest_price = to_float(row["latest_price"], "%s latest_price" % self.company)
        self.price_date = (parse_date(row["price_date"], "%s price_date" % self.company)
                           if not blank(row["price_date"]) else None)
        if (self.latest_price is None) != (self.price_date is None):
            raise LedgerError("%s latest_price 与 price_date 必须同填同空——没有日期的价格不是价格"
                              % self.company)
        if self.latest_price is not None and self.latest_price <= 0:
            raise LedgerError("%s latest_price 必须为正" % self.company)
        self.note = row["note"]
        self.nodes = None  # lazy


class Event(object):
    __slots__ = ("date", "company", "event", "shares", "price", "note", "row")

    def __init__(self, row, companies):
        self.row = row
        self.date = parse_date(row["date"], "events date")
        self.company = row["company"]
        if self.company not in companies:
            raise LedgerError("events 引用了不存在的公司 %r(悬空引用)" % self.company)
        self.event = row["event"]
        if self.event not in EVENTS:
            raise LedgerError("未知 event %r(exercise|tender): %s" % (self.event, self.company))
        self.shares = to_int(row["shares"], "event shares")
        if self.shares is None or self.shares <= 0:
            raise LedgerError("%s 事件 shares 必须是正整数" % self.company)
        self.price = to_float(row["price"], "event price")
        if self.event == "tender" and (self.price is None or self.price <= 0):
            raise LedgerError("%s tender 必须带正的 price(成交价)——落袋账没有价格就不是账" % self.company)
        if self.event == "exercise" and not blank(row["price"]) and self.price:
            raise LedgerError("%s exercise 不填 price——行权价是授予条款(strike),不是事件属性" % self.company)
        self.note = row["note"]


class Ledger(object):
    def __init__(self, dirpath):
        self.dir = dirpath
        gp, ep, sp = (os.path.join(dirpath, f) for f in
                      ("grants.tsv", "events.tsv", "schedule.tsv"))
        grows, g_exists = read_tsv(gp, GRANT_COLS, "grants.tsv")
        if not g_exists or not grows:
            raise EmptyLedger(grants_empty_msg(g_exists))
        self.grants = [Grant(r) for r in grows]
        # 同公司多份授予合法(top-up);kind 必须一致;公司按文件首现顺序
        self.by_company = {}
        self.companies = []
        seen_kind = {}
        for g in self.grants:
            if g.company not in self.by_company:
                self.by_company[g.company] = []
                self.companies.append(g.company)
                seen_kind[g.company] = g.kind
            elif seen_kind[g.company] != g.kind:
                raise LedgerError("%s 同公司 kind 必须一致(%s vs %s)——期权和 rsu 不混账"
                                  % (g.company, seen_kind[g.company], g.kind))
            self.by_company[g.company].append(g)
        for comp in self.companies:
            self.by_company[comp].sort(key=lambda g: g.grant_date)  # FIFO 按授予日
        erows, _ = read_tsv(ep, EVENT_COLS, "events.tsv")
        self.events = sorted((Event(r, set(self.companies)) for r in erows),
                             key=lambda e: (e.date, e.company, e.event))
        srows, _ = read_tsv(sp, SCHED_COLS, "schedule.tsv")
        self.schedules = {}
        for r in srows:
            comp = r["company"]
            if comp not in self.by_company:
                raise LedgerError("schedule 引用了不存在的公司 %r(悬空引用)" % comp)
            d = parse_date(r["date"], "schedule date")
            n = to_int(r["shares"], "schedule shares")
            if n is None or n <= 0:
                raise LedgerError("schedule %s shares 必须是正整数" % comp)
            if d < self.by_company[comp][0].grant_date:
                raise LedgerError("schedule %s 日期 %s 早于授予日" % (comp, r["date"]))
            self.schedules.setdefault(comp, []).append((d, n))
        for comp, nodes in self.schedules.items():
            if len(self.by_company[comp]) > 1:
                raise LedgerError("schedule 按公司整表覆盖,%s 有 %d 份授予,无法对应——拆成两家或改用公式"
                                  % (comp, len(self.by_company[comp])))
            nodes.sort()
            total = sum(n for _, n in nodes)
            g = self.by_company[comp][0]
            if total != g.shares:
                raise LedgerError("schedule %s Σshares=%s ≠ 授予股数 %s——日程表和授予对不上"
                                  % (comp, fmt_shares(total), fmt_shares(g.shares)))

    def max_date(self):
        ds = []
        for g in self.grants:
            ds.append(g.grant_date)
            if g.end_date:
                ds.append(g.end_date)
            if g.price_date:
                ds.append(g.price_date)
        ds += [e.date for e in self.events]
        for nodes in self.schedules.values():
            ds += [d for d, _ in nodes]
        return max(ds)

    # ------------------------------------------------------- 归属日程

    def nodes_of(self, g):
        """归属节点: [(date, shares, is_cliff, is_final)],schedule 覆盖优先于公式。"""
        if g.nodes is not None:
            return g.nodes
        if g.company in self.schedules:
            lst = self.schedules[g.company]
            g.nodes = [(d, n, False, i == len(lst) - 1)
                       for i, (d, n) in enumerate(lst)]
            return g.nodes
        M, c, step = g.total_months, g.cliff_months, INTERVALS[g.interval]
        if c == M:  # 全程悬崖:一次性归属
            g.nodes = [(add_months(g.grant_date, M), g.shares, True, True)]
            return g.nodes
        months = ([c] if c > 0 else [0]) + [m for m in range(c + step, M, step)]
        if months[-1] != M:
            months.append(M)
        cliff_shares = g.shares * c // M
        rest = g.shares - cliff_shares
        nodes = []
        if c > 0:
            # 首节点=悬崖,其余 len(months)-1 个节点分摊剩余
            k = len(months) - 1
            base, extra = (rest // k, rest % k) if k > 0 else (0, 0)
            for i, m in enumerate(months):
                d = add_months(g.grant_date, m)
                if i == 0:
                    if cliff_shares > 0:
                        nodes.append((d, cliff_shares, True, m == M))
                else:
                    n = base + (extra if i == len(months) - 1 else 0)
                    if n > 0:
                        nodes.append((d, n, False, m == M))
        else:
            # 无悬崖:全部节点(含授予日当天的首节点)平摊总股数
            k = len(months)
            base, extra = g.shares // k, g.shares % k
            for i, m in enumerate(months):
                d = add_months(g.grant_date, m)
                n = base + (extra if i == len(months) - 1 else 0)
                if n > 0:
                    nodes.append((d, n, False, m == M))
        g.nodes = nodes
        return g.nodes

    def vested_on(self, g, d):
        """到 d 日(含)已归属股数;归属同时被 end_date 截断——离开/清算日之后不再归属。"""
        cutoff = d
        if g.end_date and g.end_date < cutoff:
            cutoff = g.end_date
        return sum(n for nd, n, _, _ in self.nodes_of(g) if nd <= cutoff)

    def vested_forward(self, g, d):
        """路径 A:按节点时序累加(与 vested_on 的判定式互为独立路径)。"""
        cutoff = d
        if g.end_date and g.end_date < cutoff:
            cutoff = g.end_date
        acc = 0
        for nd, n, _, _ in self.nodes_of(g):
            if nd > cutoff:
                break
            acc += n
        return acc

    def vested_complement(self, g, d):
        """路径 B:总股数 − 截断日之后仍归属不到的股数(补集)。"""
        cutoff = d
        if g.end_date and g.end_date < cutoff:
            cutoff = g.end_date
        return g.shares - sum(n for nd, n, _, _ in self.nodes_of(g) if nd > cutoff)

    # ------------------------------------------------------- 事件校验与分摊

    def company_events(self, comp, upto=None):
        return [e for e in self.events
                if e.company == comp and (upto is None or e.date <= upto)]

    def check_events(self, term_years):
        """事件合法性:悬空/早于授予/超池/行权窗口与大限/rsu 行权——账本层一次算清。"""
        for comp, grants in self.by_company.items():
            first = grants[0]
            kind = first.kind
            exercised = 0
            tendered = 0
            for e in self.company_events(comp):
                if e.date < first.grant_date:
                    raise LedgerError("%s 事件 %s 早于最早授予日 %s"
                                      % (comp, fmt_d(e.date), fmt_d(first.grant_date)))
                vested = sum(self.vested_on(g, e.date) for g in grants)
                if e.event == "exercise":
                    if kind != "option":
                        raise LedgerError("%s 是 rsu,没有行权这件事(exercise)" % comp)
                    tend_max = max(add_months(g.grant_date,
                                              int(round(term_years * 12)))
                                   for g in grants)
                    if e.date > tend_max:
                        raise LedgerError("%s 行权日 %s 晚于期权大限 %s——期权过期,账本拒载"
                                          % (comp, fmt_d(e.date), fmt_d(tend_max)))
                    ok_window = any(
                        (g.status != "left")
                        or (g.status == "left"
                            and e.date <= g.end_date + timedelta(days=g.window_days))
                        for g in grants)
                    if not ok_window:
                        g0 = [g for g in grants if g.status == "left"][0]
                        wend = g0.end_date + timedelta(days=g0.window_days)
                        raise LedgerError("%s 行权日 %s 晚于行权窗口截止 %s——窗口关了,账本拒载"
                                          % (comp, fmt_d(e.date), fmt_d(wend)))
                    if exercised + e.shares > vested:
                        raise LedgerError("%s 行权 %s 股超过当日已归属 %s 股——不能行权还没归属的股份"
                                          % (comp, fmt_shares(e.shares), fmt_shares(vested)))
                    exercised += e.shares
                else:  # tender
                    if kind == "option":
                        if tendered + e.shares > exercised:
                            raise LedgerError("%s 变现 %s 股超过已行权持有 %s 股——卖出不存在的股份"
                                              % (comp, fmt_shares(e.shares),
                                                 fmt_shares(exercised - tendered)))
                    else:
                        if tendered + e.shares > vested:
                            raise LedgerError("%s 变现 %s 股超过当日已归属 %s 股"
                                              % (comp, fmt_shares(e.shares), fmt_shares(vested)))
                    tendered += e.shares

    def alloc_events(self, comp, upto):
        """把公司事件按授予日 FIFO 分摊到各授予。
        返回 {grant: {"ex": [(date, shares)...], "ex_total": n, "td": n}}。
        分摊不下(事件超过全部池)直接抛——宁可拒绝,不静默吞掉超额事件。"""
        grants = self.by_company[comp]
        alloc = {id(g): {"ex": [], "ex_total": 0, "td": 0} for g in grants}
        for e in self.company_events(comp, upto):
            for g in grants:
                a = alloc[id(g)]
                if e.event == "exercise":
                    room = self.vested_on(g, e.date) - a["ex_total"]
                    if room >= e.shares:
                        a["ex"].append((e.date, e.shares))
                        a["ex_total"] += e.shares
                        break
                else:
                    if g.kind == "option":
                        room = a["ex_total"] - a["td"]
                    else:
                        room = self.vested_on(g, e.date) - a["td"]
                    if room >= e.shares:
                        a["td"] += e.shares
                        break
            else:
                raise LedgerError("%s 事件 %s(%s %s 股)分摊不进任何授予——超额事件拒绝入账"
                                  % (comp, fmt_d(e.date), e.event,
                                     fmt_shares(e.shares)))
        return alloc

    # ------------------------------------------------------- as-of 状态

    def state(self, as_of, term_years):
        """as-of 视角下每家公司的六桶状态(股数口径)。
        UNVESTED 未归属 | AVAILABLE 已归属在册(option 可行权/rsu 已到手)|
        EXERCISED 已行权仍持有 | TENDERED 已落袋 |
        F_UNVEST 离职/清算作废(未归属部分) | F_WIN 窗口/大限作废(已归属未行权)
        """
        out = {}
        for comp, grants in self.by_company.items():
            alloc = self.alloc_events(comp, as_of)
            st = dict(comp=comp, kind=grants[0].kind,
                      UNVESTED=0, AVAILABLE=0, EXERCISED=0, TENDERED=0,
                      F_UNVEST=0, F_WIN=0, rows=[], dead=False, has_future=False)
            for g in grants:
                if as_of < g.grant_date:
                    st["rows"].append(dict(g=g, future=True))
                    st["has_future"] = True
                    continue
                a = alloc[id(g)]
                ex_total = a["ex_total"]
                td = a["td"]
                vest_now = self.vested_on(g, as_of)
                row = dict(g=g, future=False, vested=vest_now, ex_total=ex_total,
                           td=td, window_end=None, window_left=None, blown=False,
                           term_end=None, term_blown=False, departed=False,
                           f_unvest=0, f_win=0)
                if g.kind == "option":
                    row["term_end"] = add_months(g.grant_date,
                                                 int(round(term_years * 12)))
                departed = g.status in ("left", "dead") and as_of >= g.end_date
                row["departed"] = departed
                if departed:
                    vest_at_end = self.vested_on(g, g.end_date)
                    row["f_unvest"] = g.shares - vest_at_end
                if g.kind == "option" and g.status == "left" and departed:
                    wend = g.end_date + timedelta(days=g.window_days)
                    row["window_end"] = wend
                    row["window_left"] = (wend - as_of).days
                    ex_in_win = sum(s for d, s in a["ex"] if d <= wend)
                    if as_of > wend and vest_at_end > ex_in_win:
                        row["blown"] = True
                        row["f_win"] = vest_at_end - ex_in_win
                elif g.kind == "option" and not departed and as_of > row["term_end"]:
                    if vest_now > ex_total:
                        row["term_blown"] = True
                        row["f_win"] = vest_now - ex_total
                st["UNVESTED"] += (0 if departed else g.shares - vest_now)
                st["F_UNVEST"] += row["f_unvest"]
                st["F_WIN"] += row["f_win"]
                if g.kind == "option":
                    available = vest_now - ex_total - row["f_win"]
                    st["AVAILABLE"] += available
                    st["EXERCISED"] += ex_total - td
                    st["TENDERED"] += td
                else:
                    st["AVAILABLE"] += vest_now - td
                    st["TENDERED"] += td
                if g.status == "dead":
                    st["dead"] = True
                st["rows"].append(row)
            out[comp] = st
        return out

    def priced_grant(self, comp, as_of):
        """公司级估值来源:price_date ≤ as-of 中最新的一份授予行。"""
        priced = [g for g in self.by_company[comp]
                  if g.latest_price is not None and g.price_date <= as_of]
        return max(priced, key=lambda g: g.price_date) if priced else None

    def next_node(self, g, after):
        """after 之后(不含)的下一个归属节点。"""
        for nd, n, cliff, final in self.nodes_of(g):
            if nd > after:
                return dict(date=nd, shares=n, cliff=cliff, final=final)
        return None


def grants_empty_msg(exists):
    cols = "/".join(GRANT_COLS)
    if not exists:
        return ("grants.tsv 不存在。第一行抄这里(列: %s):\n"
                "  巨潮科技\trsu\t2023-07-01\t24000\t0\t4\t12\tquarterly\tactive\t\t\t32.00\t2026-06-30\t最早的一份授予"
                % cols)
    return ("grants.tsv 存在但没有一行授予(零字节/纯注释/只有表头)。\n"
            "  第一行抄这里(列: %s)" % cols)


# ---------------------------------------------------------------- report

def render_report(ledger, as_of, p):
    st_all = ledger.state(as_of, p.term_years)
    L = []
    app = L.append
    name = os.path.basename(os.path.abspath(ledger.dir))
    app("未兑现 · Unvested —— 期权/RSU 归属账本(%s)" % name)
    anchor = "" if as_of == ledger.max_date() else \
        "(时间机器;账本最大日期 %s)" % fmt_d(ledger.max_date())
    app("as-of %s %s" % (fmt_d(as_of), anchor))
    app("")
    live = [g for g in ledger.grants if as_of >= g.grant_date]
    app("== 授予总账(%d 份授予 / %d 家公司,未来授予 %d 份)=="
        % (len(ledger.grants), len(ledger.companies),
           len(ledger.grants) - len(live)))
    app("%-10s  %-6s  %-10s  %10s  %10s  %10s  %s"
        % ("公司", "kind", "授予日", "总股数", "已归属", "未归属", "状态"))
    tot = dict(shares=0, vested=0)
    for g in ledger.grants:
        if as_of < g.grant_date:
            app("%-10s  %-6s  %-10s  %10s  %10s  %10s  %s"
                % (g.company, g.kind, fmt_d(g.grant_date), fmt_shares(g.shares),
                   "—", "—", "future(后视行)"))
            continue
        vested = ledger.vested_on(g, as_of)
        if g.status == "left":
            status = "left " + fmt_d(g.end_date)
        elif g.status == "dead":
            status = "dead " + fmt_d(g.end_date)
        else:
            status = "active"
        app("%-10s  %-6s  %-10s  %10s  %10s  %10s  %s"
            % (g.company, g.kind, fmt_d(g.grant_date), fmt_shares(g.shares),
               fmt_shares(vested), fmt_shares(g.shares - vested), status))
        tot["shares"] += g.shares
        tot["vested"] += vested
    app("%-10s  %-6s  %-10s  %10s  %10s  %10s  %s"
        % ("合计", "", "", fmt_shares(tot["shares"]), fmt_shares(tot["vested"]),
           fmt_shares(tot["shares"] - tot["vested"]), ""))
    app("")
    app("== 钱的三种形态:纸面 ≠ 到手 ≠ 落袋 ==")
    tot_paper = tot_strike = tot_tender = tot_lost = 0.0
    any_price = False
    for comp in ledger.companies:
        st = st_all[comp]
        if st["has_future"] and not any(not r["future"] for r in st["rows"]):
            app("%-8s  授予尚未开始(as-of 之后)——后视行不进总账" % comp)
            continue
        if st["dead"]:
            app("%-8s  已清算/关闭——全部价值按 0 计,账上的股数是档案不是钱" % comp)
            continue
        pg = ledger.priced_grant(comp, as_of)
        in_stock = st["UNVESTED"] + st["AVAILABLE"]
        if pg is None:
            app("%-8s  在册 %s 股(已归属 %s / 未归属 %s)——无价格,只数股份,不发明估值"
                % (comp, fmt_shares(in_stock), fmt_shares(st["AVAILABLE"]),
                   fmt_shares(st["UNVESTED"])))
            if st["kind"] == "option" and ledger.by_company[comp][0].strike > 0 \
                    and in_stock > 0:
                strike = ledger.by_company[comp][0].strike
                strike_cash = in_stock * strike
                tot_strike += strike_cash
                app("%s  其中行权要先掏 %s(strike %s)——没有估值,行权要掏的现金是确定的"
                    % (" " * 10, fmt_money(strike_cash),
                       ("%.2f" % strike).rstrip("0").rstrip(".")))
        else:
            any_price = True
            stale = (as_of - pg.price_date).days
            stamp = ""
            if stale > p.stale_days:
                stamp = "(旧价:上一轮是 %d 天前的事)" % stale
            paper = in_stock * pg.latest_price
            tot_paper += paper
            if in_stock > 0:
                line = "%-8s  在册纸面 %s(%s 股 × %s@%s)%s" % (
                    comp, fmt_money(paper), fmt_shares(in_stock),
                    ("%.2f" % pg.latest_price).rstrip("0").rstrip("."),
                    fmt_d(pg.price_date), stamp)
                if st["kind"] == "option" and pg.strike > 0:
                    strike_cash = in_stock * pg.strike
                    tot_strike += strike_cash
                    line += "\n%s  其中行权要先掏 %s(strike %s × %s 股)——不掏,纸面永远不是你的" % (
                        " " * 10, fmt_money(strike_cash),
                        ("%.2f" % pg.strike).rstrip("0").rstrip("."),
                        fmt_shares(in_stock))
                app(line)
            else:
                app("%-8s  在册 0 股——纸面清零,剩下的见「已作废」" % comp)
        if st["TENDERED"] > 0:
            tend_ev = [e for e in ledger.company_events(comp, as_of) if e.event == "tender"]
            got = sum(e.shares * e.price for e in tend_ev)
            tot_tender += got
            app("%-8s  已落袋 %s(%s 笔变现,%s 股)——这是唯一离开纸面的钱"
                % ("", fmt_money(got), len(tend_ev), fmt_shares(st["TENDERED"])))
        if st["F_WIN"] > 0 or st["F_UNVEST"] > 0:
            parts = []
            if st["F_WIN"] > 0:
                if pg is not None and st["kind"] == "option":
                    lost = st["F_WIN"] * (pg.latest_price - pg.strike)
                    parts.append("窗口/大限作废 %s 股——净代价 %s(按%s)"
                                 % (fmt_shares(st["F_WIN"]), fmt_money(lost),
                                    "旧价记忆" if (as_of - pg.price_date).days > p.stale_days else "最后一轮价"))
                    tot_lost += lost
                else:
                    parts.append("窗口/大限作废 %s 股" % fmt_shares(st["F_WIN"]))
            if st["F_UNVEST"] > 0:
                if pg is not None:
                    lost2 = st["F_UNVEST"] * pg.latest_price
                    parts.append("离职/清算作废 %s 股——纸面 %s(按%s)"
                                 % (fmt_shares(st["F_UNVEST"]), fmt_money(lost2),
                                    "旧价记忆" if (as_of - pg.price_date).days > p.stale_days else "最后一轮价"))
                    tot_lost += lost2
                else:
                    parts.append("离职/清算作废 %s 股" % fmt_shares(st["F_UNVEST"]))
            app("%-8s  已作废:%s——这笔损失无人替你记账,账本记" % ("", ";".join(parts)))
    if any_price or tot_tender:
        app("%-8s  合计:在册纸面 %s · 行权现金 %s · 已落袋 %s · 作废记忆 %s"
            % ("", fmt_money(tot_paper), fmt_money(tot_strike),
               fmt_money(tot_tender), fmt_money(tot_lost)))
    app("")
    app("== 下一个归属节点 ==")
    any_next = False
    for g in ledger.grants:
        if as_of < g.grant_date:
            continue
        if g.status in ("left", "dead") and as_of >= g.end_date:
            continue
        nxt = ledger.next_node(g, as_of)
        if not nxt:
            continue
        any_next = True
        pg = ledger.priced_grant(g.company, as_of)
        val = ""
        if pg is not None:
            net = nxt["shares"] * (pg.latest_price - (pg.strike or 0))
            val = "(%s)" % fmt_money(net)
        cum = ledger.vested_on(g, nxt["date"])
        tag = "CLIFF " if nxt["cliff"] else ""
        fin = ",全部归属完成" if nxt["final"] else ""
        app("%-8s  %s  %s+%s 股 %s(累计 %s)%s —— %s"
            % (g.company, fmt_d(nxt["date"]), tag, fmt_shares(nxt["shares"]),
               val, fmt_pct(float(cum) / g.shares), fin,
               fmt_after((nxt["date"] - as_of).days)))
    if not any_next:
        app("(没有待来的归属节点——该到的都到了)")
    app("")
    lamps = collect_lamps(ledger, st_all, as_of, p)
    app("== 灯 ==")
    if lamps:
        for head, detail in lamps:
            app("%s" % head)
            if detail:
                app("%s" % detail)
    else:
        app("(无)")
    app("")
    app("纸面不是口袋:未上市股份没有流动性,latest_price 是上一轮的优先股价格,和你的普通股")
    app("之间隔着清算优先权;行权要先掏现金;税另算。条款以授予协议为准——律所永远赢。")
    text = "\n".join(L)
    code = 4 if any(h.startswith("🔴") for h, _ in lamps) else 0
    return text, code


def collect_lamps(ledger, st_all, as_of, p):
    lamps = []
    for comp in ledger.companies:
        st = st_all[comp]
        pg = ledger.priced_grant(comp, as_of)
        for r in st["rows"]:
            if r["future"]:
                continue
            g = r["g"]
            if r["blown"]:
                lamps.append(("🔴 BLOWN-WINDOW  %s:行权窗口 %s 已关,%s 股未行权,归零"
                              % (comp, fmt_d(r["window_end"]),
                                 fmt_shares(r["f_win"])),
                              "           净代价 %s(按旧价记忆)——这笔损失无人替你记账,账本记"
                              % fmt_money(r["f_win"] * (pg.latest_price - pg.strike))
                              if pg is not None else ""))
            elif (r["window_end"] is not None and r["window_left"] is not None
                  and 0 <= r["window_left"] < p.warn_days
                  and r["vested"] - r["ex_total"] > 0):
                lamps.append(("🔴 WINDOW-CLOSING  %s:行权窗口 %s 截止,只剩 %s,%s 股未行权"
                              % (comp, fmt_d(r["window_end"]),
                                 fmt_days(r["window_left"]),
                                 fmt_shares(r["vested"] - r["ex_total"])),
                              "           行权需掏 %s——不掏,窗口一关全部归零"
                              % fmt_money((r["vested"] - r["ex_total"]) * g.strike)
                              if g.strike > 0 else ""))
            if r["term_blown"]:
                lamps.append(("🔴 TERM-EXPIRED  %s:期权大限 %s 已过,%s 股未行权,作废"
                              % (comp, fmt_d(r["term_end"]),
                                 fmt_shares(r["f_win"])), ""))
        # CLIFF-AHEAD:活跃授予的未来 cliff
        for g in ledger.by_company[comp]:
            if as_of < g.grant_date:
                continue
            if g.status in ("left", "dead") and as_of >= g.end_date:
                continue
            nxt = ledger.next_node(g, as_of)
            if nxt and nxt["cliff"] and (nxt["date"] - as_of).days <= p.cliff_days \
                    and nxt["shares"] >= g.shares * DEF_CLIFF_MIN_PCT:
                lamps.append(("🟡 CLIFF-AHEAD  %s:cliff %s(%s,%s 股 = %s)"
                              % (comp, fmt_d(nxt["date"]),
                                 fmt_after((nxt["date"] - as_of).days),
                                 fmt_shares(nxt["shares"]),
                                 fmt_pct(float(nxt["shares"]) / g.shares)),
                              "           最大的一笔还在悬崖对面——动离职念头之前先看这行"))
        if pg is not None and (as_of - pg.price_date).days > p.stale_days:
            lamps.append(("🟡 STALE-PRICE  %s:价格是 %d 天前的旧地图(%s@%s)"
                          % (comp, (as_of - pg.price_date).days,
                             ("%.2f" % pg.latest_price).rstrip("0").rstrip("."),
                             fmt_d(pg.price_date)),
                          "           上一轮融资是上个周期的事,按它算的市值是按旧地图算的路程"))
        if st["dead"]:
            lamps.append(("🟡 DEAD-STAKE  %s:已清算/关闭,全部价值按 0 计" % comp, ""))
    return lamps


# ---------------------------------------------------------------- exit

def render_exit(ledger, as_of, exit_date, p):
    st_all = ledger.state(as_of, p.term_years)
    L = []
    app = L.append
    name = os.path.basename(os.path.abspath(ledger.dir))
    app("未兑现 · exit —— 假设 %s 离职(as-of %s,%s)"
        % (fmt_d(exit_date), fmt_d(as_of),
           "时间机器" if as_of != ledger.max_date() else "账本最大日期"))
    app("")
    for comp in ledger.companies:
        st = st_all[comp]
        grants = [r for r in st["rows"] if not r["future"]]
        if not grants:
            app("%-8s  授予在 as-of 之后——后视行不推演" % comp)
            app("")
            continue
        gone = all(r["departed"] for r in grants)
        if gone:
            app("%-8s  已于 %s %s——命运已入账(见 report),不再推演"
                % (comp, fmt_d(grants[0]["g"].end_date),
                   "离职" if grants[0]["g"].status == "left" else "清算/关闭"))
            app("")
            continue
        pg = ledger.priced_grant(comp, as_of)
        price = pg.latest_price if pg is not None else None
        # strike 是授予条款,与有没有估值无关——没价格也有行权现金需求
        strike = grants[0]["g"].strike if st["kind"] == "option" else 0.0
        vest_d = 0
        shares_d = 0
        for r in grants:
            g = r["g"]
            vest_d += ledger.vested_on(g, exit_date)
            shares_d += g.shares
        forfeit = shares_d - vest_d
        ex_already = sum(r["ex_total"] for r in grants)
        if st["kind"] == "option":
            avail_d = max(0, vest_d - ex_already)
            cash = avail_d * strike
            wend = exit_date + timedelta(days=grants[0]["g"].window_days)
            head = ("%s  option:到那天已归属 %s 股(%s),未归属 %s 股作废"
                    % (comp, fmt_shares(vest_d),
                       fmt_pct(float(vest_d) / shares_d) if shares_d else "—",
                       fmt_shares(forfeit)))
            app(head)
            if price is not None:
                keep = avail_d * (price - strike)
                app("%s  可带走纸面 %s,作废纸面代价 %s"
                    % (" " * 10, fmt_money(keep), fmt_money(forfeit * price)))
            app("%s  行权窗口至 %s:未行权 %s 股需掏 %s——窗口一关,没行权的归零"
                % (" " * 10, fmt_d(wend), fmt_shares(avail_d), fmt_money(cash)))
        else:
            head = ("%s  rsu:到那天已归属 %s 股(%s),未归属 %s 股作废"
                    % (comp, fmt_shares(vest_d),
                       fmt_pct(float(vest_d) / shares_d) if shares_d else "—",
                       fmt_shares(forfeit)))
            app(head)
            if price is not None:
                app("%s  可带走纸面 %s,作废纸面代价 %s;已归属部分自动到手(税另算)"
                    % (" " * 10, fmt_money(vest_d * price),
                       fmt_money(forfeit * price)))
        # 下一节点:差一天多一千股的那一行
        nxts = []
        for r in grants:
            g = r["g"]
            if g.status == "active" or exit_date < g.end_date:
                nn = ledger.next_node(g, exit_date)
                if nn:
                    nxts.append((nn, g))
        if nxts:
            nn, g = min(nxts, key=lambda t: t[0]["date"])
            gap = (nn["date"] - exit_date).days
            val = ""
            if price is not None:
                val = "(%s)" % fmt_money(nn["shares"] * (price - strike))
            tag = "CLIFF " if nn["cliff"] else ""
            app("%s  下一节点 %s(%s):%s+%s 股 %s——差这一下,%s 股留在悬崖对面"
                % (" " * 10, fmt_d(nn["date"]), fmt_after(gap), tag,
                   fmt_shares(nn["shares"]), val, fmt_shares(nn["shares"])))
        app("")
    app("推演是事实不是建议:走不走、哪天走,永远是人的决定;加速条款(trigger)不在公式里,")
    app("授予协议写的才算。")
    return "\n".join(L), 0


# ---------------------------------------------------------------- clock

def render_clock(ledger, as_of, p):
    L = []
    app = L.append
    name = os.path.basename(os.path.abspath(ledger.dir))
    app("未兑现 · clock —— 倒计时与归属日历(as-of %s,%s)"
        % (fmt_d(as_of), "时间机器" if as_of != ledger.max_date() else "账本最大日期"))
    app("")
    app("== 倒计时(升序)==")
    items = []
    for g in ledger.grants:
        if as_of < g.grant_date:
            continue
        departed = g.status in ("left", "dead") and as_of >= g.end_date
        if not departed:
            nxt = ledger.next_node(g, as_of)
            if nxt:
                items.append((nxt["date"], g.company,
                              ("CLIFF +%s 股(%s)" if nxt["cliff"] else "下一归属节点 +%s 股(%s)")
                              % (fmt_shares(nxt["shares"]),
                                 fmt_pct(float(ledger.vested_on(g, nxt["date"])) / g.shares))))
            last = ledger.nodes_of(g)[-1]
            items.append((last[0], g.company, "全部归属完成"))
        if g.kind == "option":
            tend = add_months(g.grant_date, int(round(p.term_years * 12)))
            if tend > as_of:
                items.append((tend, g.company, "期权 %g 年大限" % p.term_years))
            if g.status == "left" and as_of >= g.end_date:
                wend = g.end_date + timedelta(days=g.window_days)
                if wend > as_of:
                    items.append((wend, g.company, "行权窗口截止(剩 %s)"
                                  % fmt_days((wend - as_of).days)))
    if items:
        for d, comp, label in sorted(items):
            app("%s  %-8s  %s(%s)" % (fmt_d(d), comp, label,
                                      fmt_after((d - as_of).days)))
    else:
        app("(没有待来的时间点)")
    app("")
    horizon = add_months(as_of, p.months)
    app("== 未来 %d 个月归属日历(至 %s)==" % (p.months, fmt_d(horizon)))
    rows = []
    for g in ledger.grants:
        if as_of < g.grant_date:
            continue
        if g.status in ("left", "dead") and as_of >= g.end_date:
            continue
        for nd, n, cliff, final in ledger.nodes_of(g):
            if as_of < nd <= horizon:
                rows.append((nd, g.company, n, cliff))
    if rows:
        for d, comp, n, cliff in sorted(rows):
            app("%s  %-8s  +%s 股%s" % (fmt_d(d), comp, fmt_shares(n),
                                        "(CLIFF)" if cliff else ""))
    else:
        app("(展望窗内没有归属节点)")
    app("")
    app("日历只摆事实,不裁决「该不该等」——走不走、行不行权,永远是人的决定。")
    return "\n".join(L), 0


# ---------------------------------------------------------------- validate

def render_validate(ledger, as_of, p):
    st_all = ledger.state(as_of, p.term_years)
    L = []
    app = L.append
    name = os.path.basename(os.path.abspath(ledger.dir))
    app("未兑现 · validate —— 恒等式与账本体检(%s,as-of %s)" % (name, fmt_d(as_of)))
    app("")
    app("== 恒等式:总股数 ≡ 未归属+在册+已行权+已落袋+作废(未归属)+作废(窗口/大限)==")
    bad = False
    g_tot = [0] * 6
    s_tot = 0
    for comp in ledger.companies:
        st = st_all[comp]
        shares = sum(g.shares for g in ledger.by_company[comp])
        buckets = [st["UNVESTED"], st["AVAILABLE"], st["EXERCISED"],
                   st["TENDERED"], st["F_UNVEST"], st["F_WIN"]]
        resid = shares - sum(buckets)
        for i in range(6):
            g_tot[i] += buckets[i]
        s_tot += shares
        if resid != 0:
            bad = True
        app("%-10s  %8s ≡ %s   %s 残差 %+.2e"
            % (comp, fmt_shares(shares), "+".join(fmt_shares(b) for b in buckets),
               "✓" if resid == 0 else "✗", float(resid)))
    resid = s_tot - sum(g_tot)
    if resid != 0:
        bad = True
    app("%-10s  %8s ≡ %s   %s 残差 %+.2e"
        % ("合计", fmt_shares(s_tot), "+".join(fmt_shares(b) for b in g_tot),
           "✓" if resid == 0 else "✗", float(resid)))
    app("")
    app("== 双路径对拍 ==")
    n1 = n2 = 0
    ok1 = ok2 = True
    for g in ledger.grants:
        if as_of < g.grant_date:
            continue
        a = ledger.vested_forward(g, as_of)
        b = ledger.vested_complement(g, as_of)
        c = ledger.vested_on(g, as_of)
        n1 += 1
        if not (a == b == c):
            ok1 = False
    for comp in ledger.companies:
        if not ledger.company_events(comp):
            continue
        grants = ledger.by_company[comp]
        # 路径 C:进水(归属节点)与出水(行权/变现)按时间归并重放水池;
        # 同日先归属后行权/变现(当天归属当天行权合法)。
        stream = []
        for g in grants:
            for nd, n, _, _ in ledger.nodes_of(g):
                if nd <= as_of and (g.end_date is None or nd <= g.end_date):
                    stream.append((nd, 0, n))
        for e in ledger.company_events(comp, as_of):
            kind = 1 if e.event == "exercise" else 2
            stream.append((e.date, kind, -e.shares))
        pool = 0
        for _, _, delta in sorted(stream, key=lambda t: (t[0], t[1])):
            pool += delta
        expect = (sum(ledger.vested_on(g, as_of) for g in grants)
                  - sum(e.shares for e in ledger.company_events(comp, as_of)
                        if e.event in ("exercise", "tender")))
        n2 += 1
        if pool != expect:
            ok2 = False
    app("归属重放:  逐节点前向累加 == 补集 == 判定式         %s(%d 份授予)"
        % ("✓" if ok1 else "✗", n1))
    app("事件重放:  时间归并水池 == 直接公式(归属−行权−变现)  %s(%d 家公司)"
        % ("✓" if ok2 else "✗", n2))
    app("日程覆盖:  schedule Σshares == 授予股数(载入层强制)   ✓(%d 行覆盖)"
        % sum(len(v) for v in ledger.schedules.values()))
    app("")
    if bad or not (ok1 and ok2):
        app("账本有问题——恒等式或对拍未过。")
        return "\n".join(L), 2
    app("账本健康。")
    return "\n".join(L), 0


# ---------------------------------------------------------------- 命令入口

def report_cmd(args):
    ledger = Ledger(args.dir)
    as_of = parse_date(args.as_of, "--as-of") if args.as_of else ledger.max_date()
    ledger.check_events(args.term_years)
    text, code = render_report(ledger, as_of, args)
    print(text)
    return code


def exit_cmd(args):
    ledger = Ledger(args.dir)
    as_of = parse_date(args.as_of, "--as-of") if args.as_of else ledger.max_date()
    exit_date = parse_date(args.date, "--date") if args.date else as_of
    ledger.check_events(args.term_years)
    text, code = render_exit(ledger, as_of, exit_date, args)
    print(text)
    return code


def clock_cmd(args):
    ledger = Ledger(args.dir)
    as_of = parse_date(args.as_of, "--as-of") if args.as_of else ledger.max_date()
    ledger.check_events(args.term_years)
    text, code = render_clock(ledger, as_of, args)
    print(text)
    return code


def validate_cmd(args):
    ledger = Ledger(args.dir)
    as_of = parse_date(args.as_of, "--as-of") if args.as_of else ledger.max_date()
    ledger.check_events(args.term_years)
    text, code = render_validate(ledger, as_of, args)
    print(text)
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(description="未兑现 · Unvested —— 期权/RSU 归属账本")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--dir", default=".", help="账本目录(缺省当前目录)")
        sp.add_argument("--as-of", default=None, help="时间机器(缺省=账本最大日期)")
        sp.add_argument("--term-years", type=float, default=DEF_TERM_YEARS,
                        help="期权有效期大限(年,缺省 10)")

    r = sub.add_parser("report", help="归属总账+三种形态+灯")
    common(r)
    r.add_argument("--warn-days", type=int, default=DEF_WARN_DAYS)
    r.add_argument("--stale-days", type=int, default=DEF_STALE_DAYS)
    r.add_argument("--cliff-days", type=int, default=DEF_CLIFF_DAYS)

    e = sub.add_parser("exit", help="假设 --date 离职:带走/作废/行权现金")
    common(e)
    e.add_argument("--date", default=None, help="假设离职日(缺省=as-of)")

    c = sub.add_parser("clock", help="倒计时与归属日历")
    common(c)
    c.add_argument("--months", type=int, default=DEF_MONTHS)

    v = sub.add_parser("validate", help="恒等式与账本体检")
    common(v)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "report":
            return report_cmd(args)
        if args.cmd == "exit":
            return exit_cmd(args)
        if args.cmd == "clock":
            return clock_cmd(args)
        if args.cmd == "validate":
            return validate_cmd(args)
    except LedgerError as exc:
        print("账坏(exit 2):%s" % exc, file=sys.stderr)
        return 2
    except EmptyLedger as exc:
        print("空账(exit 3):%s" % exc, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
