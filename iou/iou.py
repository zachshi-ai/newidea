#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iou · 欠条 —— 亲友借贷的债权人账本.

问题:借出去的钱没有欠条。微信转账救急、饭局上开口、住院押金周转,
转账那一刻没有凭证、没有期限、没有利息,三个月后开始尴尬,一年后连
细节都要翻聊天记录,三年后连法律都不再保护——民间借贷的通识诉讼时效
是三年,而没有人记得自己最后一次催讨是哪天。外面飘着多少钱、哪笔拖
太久、该不该开口、这个人还能不能借,全凭感觉和脸皮。

iou 把每一笔借出与回款记成一行事件流(TSV:date/kind/who/amount/
note/promised,kind ∈ lend 借出 / repay 回款 / chase 催讨 / forgive
销账),对同一本账开五本账:report 总账(敞口恒等式+判级)、book 人均
明细(FIFO 逐笔未清+时效起算日)、nudge 催收单(事实底稿)、should
借出前门卫(用你自己的历史回答「还能不能借他」)、validate 账本体检。

三条设计立场:
  * 催收线优先用你自己的回款史标定(P90),样本不足退通识 90 天并披露
    ——民间借贷没有 SLA 文化,拒绝服务比通识垫底更不诚实;
  * chase(催讨)续命时效:通识口径下催讨自主张日重新起算三年,账本
    自动维护时效起算日——法律不保护躺在权利上睡觉的人,账本不让你
    睡过头;
  * forgive(销账)是诚实条款:有些借出去的钱,社会角色最终就是赠与
    ——人情化率把这件事从「心里硌一下」变成有分母的数。

零依赖:Python 3.8+ 标准库。「今天」缺省锚定账本最大日期(零墙钟),
`--as-of` 钉死即逐字节可复现。

Exit codes:
  0  report produced   2  usage/账本缺失/坏行/事件非法
  3  refusal: 账本空    4  gate: 超催收线或时效危险的未清欠账
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import unicodedata
from collections import OrderedDict, namedtuple
from typing import Dict, List, Optional, Tuple

PROG = "iou"
VERSION = "1.0.0"

FOLK_GRACE = 90             # 通识催收线(天):回款样本不足时的垫底线
THIN_REPAID = 3             # 回款样本 < 3 笔 → P90 不标定,退通识线
DEFAULT_STATUTE_YEARS = 3   # 民间借贷通识诉讼时效(年),参数不是法律意见
DEFAULT_STATUTE_WARN = 90   # 时效余量 ≤ 90 天进入危险区
DEFAULT_EXPOSE_MONTHS = 2.0  # 敞口 ≥ N 个月生活费挂 EXPOSED 横幅
DEFAULT_SOFT_LINE = 0.5     # 人情化率 > 50% 挂 SOFT-HEARTED 横幅

LEND = "LEND"
REPAY = "REPAY"
CHASE = "CHASE"
FORGIVE = "FORGIVE"

KIND_ALIASES = {
    "lend": LEND, "借出": LEND, "借": LEND,
    "repay": REPAY, "回款": REPAY, "还款": REPAY, "还": REPAY,
    "chase": CHASE, "催讨": CHASE, "催": CHASE,
    "forgive": FORGIVE, "销账": FORGIVE, "销": FORGIVE, "送": FORGIVE,
}

KIND_LABEL = {LEND: "借出", REPAY: "回款", CHASE: "催讨", FORGIVE: "销账"}

Ev = namedtuple("Ev", "date kind who amount note promised line")

# FIFO 队列里的一笔借出(orig=原始金额,remaining=未清)
Open = namedtuple("Open", "date promised orig remaining line note"
                          " base deadline base_kind")

Person = namedtuple(
    "Person",
    "name lent repaid forgiven lends repays chases forgives "
    "cycles chase_dates queue opens")


class LedgerError(Exception):
    """账本打不开或行级/重放级坏账,一律 exit 2。"""


class Refusal(Exception):
    """账本不足以出报告,exit 3。"""


# ---------------------------------------------------------------- parse


def normalize_who(name: str) -> str:
    """人名规范化:去首尾空白、小写、内部空白折叠;空名是账坏。"""
    name = re.sub(r"\s+", " ", name.strip().lower())
    if not name:
        raise LedgerError("人名为空")
    return name


def _norm_kind(word: str, lineno: int) -> str:
    word = re.sub(r"\s+", "", word.strip().lower())
    if word not in KIND_ALIASES:
        raise LedgerError(
            f"第 {lineno} 行:kind 只允许 lend/repay/chase/forgive"
            f"(借出/还款/催讨/销账),实得 {word!r}")
    return KIND_ALIASES[word]


def parse_ledger(path: str) -> List[Ev]:
    """解析借贷事件流:date/kind/who/amount[/note[/promised]]。

    同日多事件合法——借贷不是日记,是事件流;载入即按(日期, 行序)排序。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise LedgerError(f"账本打不开:{path}({exc})")
    evs: List[Ev] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if cols and cols[0].strip().lower() in ("date", "日期"):
            continue  # 表头
        if len(cols) not in (4, 5, 6):
            raise LedgerError(
                f"第 {lineno} 行:需要 4-6 列"
                f"(date/kind/who/amount[/note[/promised]]),"
                f"实得 {len(cols)} 列")
        date_s, kind_s, who_s, amount_s = (c.strip() for c in cols[:4])
        note = cols[4].strip() if len(cols) >= 5 else ""
        promised_s = cols[5].strip() if len(cols) == 6 else ""
        try:
            day = dt.date.fromisoformat(date_s)
        except ValueError:
            raise LedgerError(
                f"第 {lineno} 行:日期不是 YYYY-MM-DD:{date_s!r}")
        kind = _norm_kind(kind_s, lineno)
        try:
            who = normalize_who(who_s)
        except LedgerError:
            raise LedgerError(f"第 {lineno} 行:人名为空")
        try:
            amount = float(amount_s)
        except ValueError:
            raise LedgerError(
                f"第 {lineno} 行:金额不是数字:{amount_s!r}")
        if kind == CHASE:
            if amount_s not in ("", "-") and amount != 0:
                raise LedgerError(
                    f"第 {lineno} 行:催讨行不带金额(amount 填 0 或留空),"
                    f"实得 {amount_s!r}")
            amount = 0.0
        elif amount <= 0:
            raise LedgerError(
                f"第 {lineno} 行:{KIND_LABEL[kind]}金额必须 > 0,"
                f"实得 {amount_s!r}")
        promised: Optional[dt.date] = None
        if promised_s and promised_s != "-":
            if kind != LEND:
                raise LedgerError(
                    f"第 {lineno} 行:约定日只对借出行有意义,"
                    f"{KIND_LABEL[kind]}行不该填")
            try:
                promised = dt.date.fromisoformat(promised_s)
            except ValueError:
                raise LedgerError(
                    f"第 {lineno} 行:约定日不是 YYYY-MM-DD:{promised_s!r}")
            if promised < day:
                raise LedgerError(
                    f"第 {lineno} 行:约定日 {promised_s} 早于借出日 "
                    f"{date_s}——约定不能穿越")
        evs.append(Ev(day, kind, who, amount, note, promised, lineno))
    evs.sort(key=lambda e: (e.date, e.line))
    return evs


def cutoff(evs: List[Ev], asof: dt.date) -> List[Ev]:
    """as-of 剪切:晚于 as-of 的事件被排除(含边界日 ≤)。

    晚于它的事件是「还没写下的未来」——排除不是账坏,这是时间机器。
    """
    return [e for e in evs if e.date <= asof]


# ---------------------------------------------------------------- replay


def replay(evs: List[Ev]) -> "OrderedDict[str, Person]":
    """按(日期, 行序)重放事件流,开出人均 FIFO 账。

    重放体检(全部 exit 2):回款/销账超过该人未清余额或该人从无借出;
    催讨时该人名下没有未清余额(无从催起)。

    每笔 repay 事件产生一个回款周期样本 = 回款日 − 抵扣起点队头借出日
    (FIFO:亲友回款从不指定冲哪笔,最老先清是会计默认)。
    """
    people: "OrderedDict[str, dict]" = OrderedDict()
    for e in evs:
        p = people.setdefault(e.who, {
            "name": e.who, "lent": 0.0, "repaid": 0.0, "forgiven": 0.0,
            "lends": 0, "repays": 0, "chases": 0, "forgives": 0,
            "cycles": [], "chase_dates": [],
            # queue item: [date, promised, orig, remaining, line, note]
            "queue": [],
        })
        q = p["queue"]
        if e.kind == LEND:
            p["lent"] += e.amount
            p["lends"] += 1
            q.append([e.date, e.promised, e.amount, e.amount, e.line,
                      e.note])
        elif e.kind in (REPAY, FORGIVE):
            outstanding = sum(item[3] for item in q)
            if not p["lends"] or e.amount > outstanding + 1e-6:
                verb = "回款" if e.kind == REPAY else "销账"
                if not p["lends"]:
                    raise LedgerError(
                        f"第 {e.line} 行:{verb} ¥{e.amount:g} 但「{e.who}」"
                        f"从无借出——时间不允许倒流,人名也可能记错了")
                raise LedgerError(
                    f"第 {e.line} 行:{verb} ¥{e.amount:g} 超过「{e.who}」"
                    f"名下未清 ¥{outstanding:g}——请检查是否记错人或记错账")
            if e.kind == REPAY:
                p["repaid"] += e.amount
                p["repays"] += 1
                head = next(item for item in q if item[3] > 0)
                p["cycles"].append((e.date - head[0]).days)
            else:
                p["forgiven"] += e.amount
                p["forgives"] += 1
            rest = e.amount
            for item in q:
                if rest <= 0:
                    break
                take = min(rest, item[3])
                item[3] -= take
                rest -= take
        else:  # CHASE
            outstanding = sum(item[3] for item in q)
            if outstanding <= 0:
                raise LedgerError(
                    f"第 {e.line} 行:催讨「{e.who}」时名下没有未清余额"
                    f"——无从催起")
            p["chases"] += 1
            p["chase_dates"].append(e.date)
    out: "OrderedDict[str, Person]" = OrderedDict()
    for name, p in people.items():
        out[name] = Person(
            name=name, lent=p["lent"], repaid=p["repaid"],
            forgiven=p["forgiven"], lends=p["lends"], repays=p["repays"],
            chases=p["chases"], forgives=p["forgives"],
            cycles=tuple(p["cycles"]), chase_dates=tuple(p["chase_dates"]),
            queue=tuple((d, pr, og, rm, ln, nt)
                        for d, pr, og, rm, ln, nt in p["queue"]),
            opens=())
    return out


# ---------------------------------------------------------------- math


def percentile(sorted_vals: List[float], q: float) -> float:
    """线性插值分位数(numpy 默认口径):pos = (n−1)×q。空表 → 0。"""
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def due_line(cycles: Tuple[int, ...], grace: float) -> Tuple[float, str]:
    """催收线:回款 ≥3 笔用自己历史的 P90;不足退通识垫底线。

    返回 (线, 来源),来源 ∈ {"P90", "folk"}——来源必须随报告披露,
    通识线顶班时报告要说实话。
    """
    cs = sorted(cycles)
    if len(cs) >= THIN_REPAID:
        return percentile(cs, 0.9), "P90"
    return float(grace), "folk"


def add_years(d: dt.date, years: int) -> dt.date:
    """整 N 年后;2 月 29 日滚到 3 月 1 日(平年没有的那天向后让)。"""
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 2/29
        return dt.date(d.year + years, 3, 1)


def statute_base(lend_date: dt.date, promised: Optional[dt.date],
                 chase_dates: Tuple[dt.date, ...]) -> Tuple[dt.date, str]:
    """时效起算日 = max(约定日或借出日, 全部催讨日),附起算口径名。"""
    base = promised if promised is not None else lend_date
    kind = "约定日" if promised is not None else "借出日"
    for d in chase_dates:
        if d > base:
            base = d
            kind = "催讨重置"
    return base, kind


def build_opens(person: Person, statute_years: int) -> Tuple[Open, ...]:
    """把 FIFO 队列展开成未清笔,逐笔钉上时效起算日与届满日。

    催讨重置该人全部未清账的起算日(通识先验);已清的笔不谈时效。
    """
    opens: List[Open] = []
    for d, promised, orig, remaining, line, note in person.queue:
        if remaining <= 0:
            continue
        base, base_kind = statute_base(d, promised, person.chase_dates)
        opens.append(Open(date=d, promised=promised, orig=orig,
                          remaining=remaining, line=line, note=note,
                          base=base, deadline=add_years(base, statute_years),
                          base_kind=base_kind))
    return tuple(opens)


def attach_opens(people: "OrderedDict[str, Person]",
                 statute_years: int) -> "OrderedDict[str, Person]":
    return OrderedDict(
        (name, p._replace(opens=build_opens(p, statute_years)))
        for name, p in people.items())


# ---------------------------------------------------------------- fmt


def dw(s: str) -> int:
    """终端显示宽度:中日韩全角按 2 计。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in s)


def pad(s: str, w: int) -> str:
    return s + " " * max(0, w - dw(s))


def padl(s: str, w: int) -> str:
    return " " * max(0, w - dw(s)) + s


def yen(x: float) -> str:
    return f"¥{x:,.0f}"


def days_in(n: int) -> str:
    return f"{n:,}天"


def rate_txt(person: Person) -> str:
    if person.lent <= 0:
        return "—"
    return f"{person.repaid / person.lent * 100:.1f}%"


def _asof(evs: List[Ev], args) -> dt.date:
    if args.as_of:
        try:
            return dt.date.fromisoformat(args.as_of)
        except ValueError:
            raise LedgerError(
                f"--as-of 不是 YYYY-MM-DD:{args.as_of!r}")
    if not evs:
        raise Refusal("账本是空的——先记第一笔借出,欠条才有正文。")
    return max(e.date for e in evs)


def _load(path: str, asof: dt.date,
          statute_years: int) -> Tuple[List[Ev],
                                       "OrderedDict[str, Person]"]:
    evs = cutoff(parse_ledger(path), asof)
    if not evs:
        raise Refusal(
            f"as-of {asof} 之前没有任何事件——时间机器开到了账本开始之前。")
    return evs, attach_opens(replay(evs), statute_years)


def _line_and_cycles(people, grace):
    cycles = tuple(c for p in people.values() for c in p.cycles)
    return due_line(cycles, grace)


# ---------------------------------------------------------------- judge

CLEAR, OK, STALE, SOON, PASSED = "CLEAR", "OK", "STALE", "SOON", "PASSED"

LAMP = {
    CLEAR: "· 清",
    OK: "○ 线内",
    STALE: "✗ 超催收线",
    SOON: "⚠ 时效将满",
    PASSED: "✗ 时效已过",
}

VERDICT_ORDER = (PASSED, SOON, STALE, OK, CLEAR)


def judge_opens(opens: Tuple[Open, ...], asof: dt.date,
                line: float, warn_days: int) -> str:
    """单人判级:PASSED > SOON > STALE > OK;无未清 → CLEAR。

    时效线是硬线:届满当日即算已过——法律红线宁早一日,不晚一日。
    """
    if not opens:
        return CLEAR
    min_left = min((o.deadline - asof).days for o in opens)
    if min_left <= 0:
        return PASSED
    if min_left <= warn_days:
        return SOON
    head_age = (asof - opens[0].date).days
    if head_age > line:
        return STALE
    return OK


def global_verdict(people, asof, line, warn_days) -> Tuple[str, List[str]]:
    """汇总判级与点名名单(按 PASSED > SOON > STALE 优先级)。"""
    worst, named = OK, []
    for p in people.values():
        st = judge_opens(p.opens, asof, line, warn_days)
        if VERDICT_ORDER.index(st) < VERDICT_ORDER.index(worst):
            worst = st
        if st in (PASSED, SOON, STALE):
            named.append(p.name)
    return worst, named


def stale_opens(person: Person, asof: dt.date, line: float) -> List[Open]:
    return [o for o in person.opens if (asof - o.date).days > line]


# ---------------------------------------------------------------- commands


def cmd_report(args) -> int:
    asof = _asof(parse_ledger(args.ledger), args)
    evs, people = _load(args.ledger, asof, args.statute_years)
    line, source = _line_and_cycles(people, args.grace_days)
    lent = sum(p.lent for p in people.values())
    repaid = sum(p.repaid for p in people.values())
    forgiven = sum(p.forgiven for p in people.values())
    exposure = lent - repaid - forgiven
    balances = sum(sum(o.remaining for o in p.opens)
                   for p in people.values())
    n_lend = sum(p.lends for p in people.values())
    n_repay = sum(p.repays for p in people.values())
    n_forgive = sum(p.forgives for p in people.values())
    span0, span1 = min(e.date for e in evs), max(e.date for e in evs)
    anchor = "显式钉死" if args.as_of else "账本末日"
    print(f"欠条总账 · {len(evs)} 笔事件({span0} → {span1})"
          f" · as-of {asof}({anchor}) · 账本 {os.path.basename(args.ledger)}")
    print(f"  借出 {yen(lent)}({n_lend} 笔) − 回款 {yen(repaid)}"
          f"({n_repay} 笔) − 销账 {yen(forgiven)}({n_forgive} 笔)"
          f" = 敞口 {yen(exposure)}")
    print(f"  恒等式核验:Σ人均余额 = 敞口,残差 "
          f"{abs(balances - exposure):.6f}——一笔不多,一笔不少")
    all_cycles = sorted(c for p in people.values() for c in p.cycles)
    if all_cycles:
        print(f"  回款周期:P50 {percentile(all_cycles, 0.5):.1f} 天 · "
              f"P90 {percentile(all_cycles, 0.9):.1f} 天"
              f"({len(all_cycles)} 笔样本)")
    if source == "folk":
        print(f"  催收线 {line:.1f} 天(通识垫底——回款 {len(all_cycles)} 笔"
              f" < {THIN_REPAID} 笔,先攒样本,你的 P90 会取代它)")
    else:
        print(f"  催收线 {line:.1f} 天(自己回款史的 P90)"
              f"——超过它,这不是慢,是忘了")
    if args.monthly_spend:
        months = exposure / args.monthly_spend
        tag = " ⚠ EXPOSED" if months >= args.expose_months else ""
        print(f"  敞口翻译:{yen(exposure)} = {months:.1f} 个月生活费"
              f"(月支出 {yen(args.monthly_spend)}){tag}——"
              f"金额大不是对方的错,是你的风险敞口,横幅不进门禁")
    if n_forgive:
        soft = forgiven / lent if lent else 0.0
        mark = (" ⚠ SOFT-HEARTED"
                if soft > args.soft_line and n_forgive >= 1 else "")
        print(f"  人情化率:{yen(forgiven)} ÷ {yen(lent)} = "
              f"{soft * 100:.1f}% 的借出最终成了赠送{mark}"
              f"——不是指责,是下次开口前的数字")
    print()
    print(f"  {pad('人', 14)}{padl('余额', 10)}{padl('队头账龄', 9)}"
          f"{padl('时效余量', 9)}{padl('回款率', 8)}  状态")
    ordered = sorted(people.values(),
                     key=lambda p: (-sum(o.remaining for o in p.opens),
                                    p.name))
    for p in ordered:
        bal = sum(o.remaining for o in p.opens)
        if bal <= 0:
            print(f"  {pad(p.name, 14)}{padl('¥0', 10)}{padl('—', 9)}"
                  f"{padl('—', 9)}{padl(rate_txt(p), 8)}  {LAMP[CLEAR]}")
            continue
        st = judge_opens(p.opens, asof, line, args.statute_warn)
        age = (asof - p.opens[0].date).days
        left = min((o.deadline - asof).days for o in p.opens)
        print(f"  {pad(p.name, 14)}{padl(yen(bal), 10)}"
              f"{padl(days_in(age), 9)}{padl(days_in(left), 9)}"
              f"{padl(rate_txt(p), 8)}  {LAMP[st]}")
    verdict, named = global_verdict(people, asof, line, args.statute_warn)
    if verdict == PASSED:
        print(f"\n判定 STATUTE —— {'、'.join(named)} 的欠账已过通识时效:"
              f"法律不保护躺在权利上睡觉的人,赶紧主张并把催讨记进账本。")
        return 4
    if verdict == SOON:
        print(f"\n判定 STATUTE-SOON —— {'、'.join(named)} 的欠账时效将在 "
              f"{args.statute_warn} 天内届满:过时不候,先催后记 chase。")
        return 4
    if verdict == STALE:
        stale_sum = sum(o.remaining for p in people.values()
                        for o in stale_opens(p, asof, line))
        print(f"\n判定 STALE —— {len(named)} 人未清超催收线,"
              f"{yen(stale_sum)} 在沉默里免息续借。nudge 看催收单,"
              f"should 查下次借不借。")
        return 4
    print("\n判定 GREEN —— 无超龄、无时效危险(催不催仍是人的决定,"
          "账本只拒绝让你忘了)。")
    return 0


def cmd_book(args) -> int:
    asof = _asof(parse_ledger(args.ledger), args)
    evs, people = _load(args.ledger, asof, args.statute_years)
    line, source = _line_and_cycles(people, args.grace_days)
    src_txt = ("自己回款史的 P90" if source == "P90"
               else f"通识垫底(回款样本 <{THIN_REPAID} 笔)")
    print(f"人均明细 · as-of {asof} · 催收线 {line:.1f} 天({src_txt})"
          f" · 账本 {os.path.basename(args.ledger)}")
    ordered = sorted(people.values(),
                     key=lambda p: (-sum(o.remaining for o in p.opens),
                                    p.name))
    for p in ordered:
        bal = sum(o.remaining for o in p.opens)
        if bal <= 0:
            cycles = "/".join(str(c) for c in p.cycles) or "—"
            print(f"\n「{p.name}」已清 · {p.lends} 借 {p.repays} 还"
                  f" {yen(p.lent)} · 周期 {cycles} 天"
                  f" · 回款率 {rate_txt(p)} · {LAMP[CLEAR]}")
            continue
        st = judge_opens(p.opens, asof, line, args.statute_warn)
        print(f"\n「{p.name}」未清 {yen(bal)} · 借出 {p.lends} 笔"
              f" {yen(p.lent)} · 回款 {yen(p.repaid)} · 销账 "
              f"{yen(p.forgiven)} · 回款率 {rate_txt(p)} · {LAMP[st]}")
        for i, o in enumerate(p.opens, 1):
            age = (asof - o.date).days
            mark = f"超线 {age - line:.0f} 天" if age > line else "线内"
            promised = f",约定 {o.promised}" if o.promised else ""
            note = f" · {o.note}" if o.note else ""
            left = (o.deadline - asof).days
            print(f"  #{i} {o.date} 借出 {yen(o.orig)}{promised}{note}")
            print(f"     未清 {yen(o.remaining)} · 已 {days_in(age)}"
                  f"({mark}) · 时效起算 {o.base}({o.base_kind})"
                  f" → {o.deadline} 前主张有效 · 余 {days_in(left)}")
    return 0


def cmd_nudge(args) -> int:
    asof = _asof(parse_ledger(args.ledger), args)
    evs, people = _load(args.ledger, asof, args.statute_years)
    line, source = _line_and_cycles(people, args.grace_days)
    src_txt = ("P90" if source == "P90"
               else f"通识垫底,回款样本 <{THIN_REPAID} 笔")
    stale = [(p, o) for p in people.values()
             for o in stale_opens(p, asof, line)]
    if not stale:
        print(f"催收单 · 催收线 {line:.1f} 天({src_txt})"
              f" · as-of {asof} · 全部未清线内——无单可开")
        return 0
    total = sum(o.remaining for _, o in stale)
    names = sorted({p.name for p, _ in stale})
    print(f"催收单 · 催收线 {line:.1f} 天({src_txt}) · as-of {asof}"
          f" · {len(names)} 人 {len(stale)} 笔超线 {yen(total)}")
    by_person: Dict[str, List[Open]] = OrderedDict()
    for p, o in stale:
        by_person.setdefault(p.name, []).append(o)
    for name, opens in by_person.items():
        person = people[name]
        print(f"\n给「{name}」的事实底稿(照着说,只说事实):")
        for o in opens:
            age = (asof - o.date).days
            promised = f",说好 {o.promised} 还" if o.promised else ""
            left = (o.deadline - asof).days
            print(f"  {o.date} 借出 {yen(o.orig)}{promised}"
                  f"——未清 {yen(o.remaining)},已 {days_in(age)};"
                  f"时效起算 {o.base}({o.base_kind}),"
                  f"{o.deadline} 前主张有效(余 {days_in(left)})")
        if person.chase_dates:
            print(f"  催讨记录:{'、'.join(str(d) for d in person.chase_dates)}"
                  f"——主张过 {person.chases} 次,起算日被它续过命")
        else:
            print(f"  从未催讨过——每拖一天都在消耗法律留给你的窗口")
    print(f"\n合计 {yen(total)} 在沉默里免息续借。")
    print(f"催完记得记一行 chase——它把时效起算日续到新的一天;"
          f"催不催、怎么说,是人的决定,账本只拒绝让你忘了。")
    return 4


def cmd_should(args) -> int:
    asof = _asof(parse_ledger(args.ledger), args)
    evs, people = _load(args.ledger, asof, args.statute_years)
    line, source = _line_and_cycles(people, args.grace_days)
    if args.amount <= 0:
        raise LedgerError("拟借金额必须 > 0")
    who = normalize_who(args.who)
    print(f"借出前门卫 · 「{who}」 · 拟借 {yen(args.amount)}"
          f" · as-of {asof} · 账本 {os.path.basename(args.ledger)}")
    p = people.get(who)
    if p is None:
        print("  账本里没有这个名字——第一笔是信任,也是样本:")
        print("  借出当天记 lend,回款当天记 repay,你的历史才有资格回答"
              "「还能不能借他」。")
        print("判定 FIRST —— 无历史,不冤枉新朋友。要不要借,你的决定。")
        return 0
    bal = sum(o.remaining for o in p.opens)
    print(f"  名下未清 {yen(bal)}")
    print(f"  历史借出 {yen(p.lent)}({p.lends} 笔)· 回款 {yen(p.repaid)}"
          f" · 金额回款率 {rate_txt(p)}")
    if p.opens:
        head_age = (asof - p.opens[0].date).days
        left = min((o.deadline - asof).days for o in p.opens)
        over = head_age - line
        mark = f"超催收线 {over:.0f} 天" if over > 0 else "催收线内"
        print(f"  最老一笔已 {days_in(head_age)}({mark});"
              f"时效余量最紧 {days_in(left)}")
        if p.chase_dates:
            print(f"  催讨 {p.chases} 次,最后一次 {max(p.chase_dates)}"
                  f"——时效被它续过命")
    if bal > 0 and p.lent > 0 and p.repaid / p.lent < DEFAULT_SOFT_LINE:
        print(f"\n判定 CAUTION —— 历史回款率 {rate_txt(p)} 且旧账 "
              f"{yen(bal)} 未清:这 {yen(args.amount)} 是新的信任投票,"
              f"上一次的投票结果还在账上。借不借你决定,但先看看历史。")
        return 4
    print(f"\n判定 GREEN —— 历史上说话算话,账本不拦。要不要借,"
          f"你的决定。")
    return 0


def statute_stream(evs: List[Ev]) -> Dict[Tuple[str, int], dt.date]:
    """时效起算的独立算法:逐事件流式扫描。

    lend 入账时起算 = 约定日或借出日;chase 发生时把该人全部在账笔的
    起算抬升到主张日。与 build_opens 的全局 max 扫描殊途同归,
    validate 用两者的差验账。
    """
    live: Dict[Tuple[str, int], dt.date] = {}
    for e in evs:
        if e.kind == LEND:
            live[(e.who, e.line)] = e.promised or e.date
        elif e.kind == CHASE:
            for (who, _line), base in list(live.items()):
                if who == e.who and base < e.date:
                    live[(who, _line)] = e.date
    return live


def cmd_validate(args) -> int:
    asof = _asof(parse_ledger(args.ledger), args)
    evs, people = _load(args.ledger, asof, args.statute_years)
    line, source = _line_and_cycles(people, args.grace_days)
    n = {k: sum(1 for e in evs if e.kind == k)
         for k in (LEND, REPAY, CHASE, FORGIVE)}
    lent = sum(p.lent for p in people.values())
    repaid = sum(p.repaid for p in people.values())
    forgiven = sum(p.forgiven for p in people.values())
    exposure = lent - repaid - forgiven
    balances = sum(sum(o.remaining for o in p.opens)
                   for p in people.values())
    print(f"账本体检 · {len(evs)} 笔事件(借出 {n[LEND]} · 回款 {n[REPAY]}"
          f" · 催讨 {n[CHASE]} · 销账 {n[FORGIVE]}) · as-of {asof}"
          f" · 账本 {os.path.basename(args.ledger)}")
    print(f"  恒等式:借出 {yen(lent)} − 回款 {yen(repaid)} − 销账 "
          f"{yen(forgiven)} = 敞口 {yen(exposure)};"
          f"Σ人均余额 = {yen(balances)}"
          f"(残差 {abs(balances - exposure):.6f})")
    agg = {name: p.lent - p.repaid - p.forgiven
           for name, p in people.items()}
    fifo = {name: sum(o.remaining for o in p.opens)
            for name, p in people.items()}
    drift = max(abs(agg[k] - fifo[k]) for k in agg) if agg else 0.0
    print(f"  FIFO 双算法:逐事件游走 == 总额聚合"
          f"(最大漂移 {drift:.6f}——回款不指定冲哪笔,最老先清)")
    cycles = sorted(c for p in people.values() for c in p.cycles)
    if source == "P90":
        print(f"  回款周期样本 {len(cycles)} 笔:P50 "
              f"{percentile(cycles, 0.5):.1f} · P90 "
              f"{percentile(cycles, 0.9):.1f} → 催收线 {line:.1f} 天(P90)")
    else:
        print(f"  回款周期样本 {len(cycles)} 笔(<{THIN_REPAID} 笔)"
              f"→ 催收线 {line:.1f} 天(通识垫底)")
    stream = statute_stream(evs)
    checked, mismatch = 0, 0
    for p in people.values():
        for o in p.opens:
            checked += 1
            if (stream.get((p.name, o.line)) != o.base
                    or add_years(o.base, args.statute_years) != o.deadline):
                mismatch += 1
    print(f"  时效双算法:流式扫描 == 全局 max({checked} 笔未清,"
          f"{mismatch} 笔不一致)——催讨重置起算日是通识先验,"
          f"不是法律意见")
    soft = forgiven / lent if lent else 0.0
    print(f"  人情化率 {soft * 100:.1f}%({yen(forgiven)} ÷ {yen(lent)})"
          f" · 敞口 {yen(exposure)}")
    print("  诚实条款:账本只记你声称的事实;chase 记的是你主张过,"
          "不是对方认过——已读不回的催讨在法庭上未必续命,账本只负责"
          "让你别睡过;不外连、不查征信,「他会不会还」只有你的历史能回答。")
    return 0


# ---------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="欠条 —— 亲友借贷的债权人账本")
    parser.add_argument("--version", action="version",
                        version=f"{PROG} {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p, need_asof_opts=True):
        p.add_argument("ledger", help="借贷事件账本 TSV")
        p.add_argument("--as-of", dest="as_of",
                       help="钉死「今天」(YYYY-MM-DD;缺省=账本最大日期)")
        p.add_argument("--grace-days", type=float, default=FOLK_GRACE,
                       help=f"通识催收线(天,默认 {FOLK_GRACE})")
        p.add_argument("--statute-years", type=int,
                       default=DEFAULT_STATUTE_YEARS,
                       help="通识诉讼时效(年,默认 3;参数不是法律意见)")
        p.add_argument("--statute-warn", type=int,
                       default=DEFAULT_STATUTE_WARN,
                       help=f"时效余量 ≤ N 天进危险区(默认 {DEFAULT_STATUTE_WARN})")

    for name, func, help_ in (
            ("report", cmd_report, "总账:敞口恒等式+判级(红灯 exit 4)"),
            ("book", cmd_book, "人均明细:FIFO 逐笔未清+时效起算日"),
            ("nudge", cmd_nudge, "催收单:超线逐笔点名+事实底稿"),
            ("should", cmd_should, "借出前门卫:历史回款率与旧账"),
            ("validate", cmd_validate, "账本体检:恒等式+双算法")):
        p = sub.add_parser(name, help=help_)
        common(p)
        if name == "report":
            p.add_argument("--monthly-spend", type=float, default=None,
                           help="月支出(元):给了才做敞口翻译")
            p.add_argument("--expose-months", type=float,
                           default=DEFAULT_EXPOSE_MONTHS,
                           help="敞口 ≥ N 个月生活费挂横幅(默认 2)")
            p.add_argument("--soft-line", type=float,
                           default=DEFAULT_SOFT_LINE,
                           help="人情化率横幅线(默认 0.5)")
        if name == "should":
            p.add_argument("--who", required=True, help="要查的人名")
            p.add_argument("--amount", type=float, required=True,
                           help="拟借金额(元)")
        p.set_defaults(func=func)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LedgerError as exc:
        print(f"账本拒收:{exc}", file=sys.stderr)
        return 2
    except Refusal as exc:
        print(f"拒绝出账:{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
