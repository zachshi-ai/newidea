#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redemption · 赎契 —— 房贷摊销解构与提前还款决策.

问题：银行 App 只给三个数——剩余本金、月供、已还期数，从不给你看
贷款的时间结构：已还的钱里利息占多少、累计利息到哪一年过半、这贷款
的出厂价是多少。「提前还贷划不划算」被流行说法统治：「等额本息还到
一半利息早还完了，再还不划算」（数学谬误）、「提前还款会减月供」（错
——银行默认缩期）、「缩期减供差不多」——没有一种说法替你算过账。
组合贷家庭不知道该先还商贷还是公积金贷；「还贷 vs 投资」的等效线
没人肯给。

redemption 把贷款抄成可手编的账本（loans.tsv：1-4 笔；prepays.tsv：
已发生的提前还款历史，target 必须落到具体贷款），对闲钱开庭：

  * plan       摊销总账解构：利息/本金比、利息半程点、真实利率、双倍房灯
  * position   贷款位置单：三种进度（期数/本金/利息）、今天结清的代价
  * prepay     提前还款模拟：省息、缩期/降供、等效收益率定理、先还高息
  * compare    缩期 vs 减供对决：两本账并排 + 判据（不替你选）
  * myth       谬误法庭：「利息早还完了」当庭对质——省息公式里没有已还进度
  * vsinvest   还贷 vs 投资：两世界终值模拟，m=合同时必平（等效定理）
  * batch      一次 vs 分批：时间在钱前面，流动性有价但不定价
  * validate   恒等式体检：逐期拆分、本金回归、期末归零、等效定理数值面

核心定理（测试钉死）：提前还款是一笔年化恰等于合同利率的无风险、
税后投资——月复利口径 (1+i)^12−1。组合贷的钱该先去利率最高的债上：
每 1 元预付的省息与被还贷款的利率成正比。

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
本件不预测 LPR、不算违约金、不构成理财建议——它只把契约的形状摆上台面，
赎与不赎，人的决定。

用法：
  python3 redemption.py plan loans.tsv prepays.tsv --today 2026-09-04
  python3 redemption.py position loans.tsv prepays.tsv --today 2026-09-04
  python3 redemption.py prepay loans.tsv prepays.tsv --amount 500000 --mode term
  python3 redemption.py compare loans.tsv prepays.tsv --amount 500000
  python3 redemption.py myth loans.tsv prepays.tsv
  python3 redemption.py vsinvest loans.tsv prepays.tsv --amount 500000 --yield 2.3
  python3 redemption.py batch loans.tsv prepays.tsv --total 500000 --parts 5
  python3 redemption.py validate loans.tsv prepays.tsv

Exit codes:
  0  report produced
  2  usage error / 账本缺失 / 坏行 / 贷款超 4 笔 / target 不存在 / 历史结清
  3  refusal: 账本是空的 / 预付 ≥ 余额（那是结清）/ vsinvest 未给收益率
  4  gate: 利息追平本金（双倍房灯）/ 钱去错了债（先还低息灯）/ 投资跑输等效线
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import math
import re
import sys
import unicodedata
from collections import namedtuple
from typing import Dict, List, Optional, Tuple

PROG = "redemption"
VERSION = "1.0.0"

MAX_LOANS = 4
EPS = 0.005            # 余额EPS：小于半分钱即视为还清
GATE_DOUBLE = 1.0      # 双倍房灯：出厂总利息 ≥ 本金 × 100% 亮灯
GATE_WRONG = 0.005     # 先还低息灯：目标利率低于在册最高利率 0.5pp
GATE_INVEST = 0.005    # 投资跑输/跑赢等效线 0.5pp 之外才表态
MIN_PREPAY_NOTE = 10000.0   # 低于此金额挂「银行有最低额」横幅（不拒绝）
MYTH_FLOOR = 1000.0    # 谬误法庭对质金额下限

MODE_TERM = "term"
MODE_PAYMENT = "payment"
MODE_LABEL = {MODE_TERM: "缩期（月供不变、期限变短）",
              MODE_PAYMENT: "减供（期限不变、月供变低）"}

Loan = namedtuple("Loan", "key name principal rate years start method note line")
Prepay = namedtuple("Prepay", "date amount target mode note line")
Row = namedtuple("Row", "k date interest principal payment balance")
Event = namedtuple("Event", "k date amount mode n_before n_after "
                            "pay_before pay_after")

METHOD_ALIASES = {"annuity": "annuity", "等额本息": "annuity",
                  "linear": "linear", "等额本金": "linear"}


class LedgerError(Exception):
    """账本打不开或行级坏账，一律 exit 2。"""


class Refusal(Exception):
    """账本不足以出报告，exit 3。"""


class Gate(Exception):
    """门禁亮灯：账本说出了亮灯的事实，exit 4。"""


# ---------------------------------------------------------------- dates


def parse_date(s: str, lineno: int, what: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(s.strip())
    except ValueError:
        raise LedgerError(f"第 {lineno} 行：{what}日期不是 YYYY-MM-DD：{s!r}")


def parse_today(s: Optional[str]) -> datetime.date:
    if s is None:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(s.strip())
    except ValueError:
        raise LedgerError(f"--today 不是 YYYY-MM-DD：{s!r}")


def add_months(d: datetime.date, k: int) -> datetime.date:
    """d 之后第 k 个月；月末钳制（1-31 → 2-28）。k=0 返回 d。"""
    y = d.year + (d.month - 1 + k) // 12
    m = (d.month - 1 + k) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return datetime.date(y, m, day)


def months_done(start: datetime.date, day: datetime.date) -> int:
    """截至 day 已完成的整期数。第 k 期还款日 = start+(k-1) 月；还款日
    落在比 start 晚的月份时，若当月没有 start 的「日」则钳到月末（31→28）。
    早于 start 记 0。"""
    if day < start:
        return 0
    eff = min(start.day, calendar.monthrange(day.year, day.month)[1])
    mo = (day.year - start.year) * 12 + (day.month - start.month)
    done = mo + 1 if day.day >= eff else mo
    return max(0, done)


# ---------------------------------------------------------------- parsing


def _read_rows(path: str, what: str) -> List[Tuple[int, List[str]]]:
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise LedgerError(f"{what}账本打不开：{path}（{exc}）")
    rows: List[Tuple[int, List[str]]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rows.append((lineno, line.split("\t")))
    return rows


def normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def parse_loans(path: str) -> List[Loan]:
    """解析贷款账本：name/principal/rate/years/start/method[/note]。

    1 到 MAX_LOANS 笔；名字规范化后唯一；method 支持中英文写法。
    start = 首期还款日。
    """
    loans: List[Loan] = []
    seen: Dict[str, int] = {}
    for lineno, cols in _read_rows(path, "贷款"):
        if len(cols) >= 6 and cols[0].strip().lower() == "name":
            continue  # 表头
        if len(cols) not in (6, 7):
            raise LedgerError(
                f"第 {lineno} 行：需要 6-7 列"
                f"（name/principal/rate/years/start/method[/note]），"
                f"实得 {len(cols)} 列")
        name_s, prin_s, rate_s, years_s, start_s, method_s = (
            c.strip() for c in cols[:6])
        note = cols[6].strip() if len(cols) == 7 else ""
        if not name_s:
            raise LedgerError(f"第 {lineno} 行：贷款名为空")
        try:
            principal = float(prin_s)
        except ValueError:
            raise LedgerError(f"第 {lineno} 行：本金不是数字：{prin_s!r}")
        if principal <= 0:
            raise LedgerError(f"第 {lineno} 行：本金必须 > 0，实得 {prin_s!r}")
        try:
            rate = float(rate_s)
        except ValueError:
            raise LedgerError(f"第 {lineno} 行：年利率不是数字：{rate_s!r}")
        if not (0 < rate < 100):
            raise LedgerError(
                f"第 {lineno} 行：年利率应为 0-100 的百分数（如 4.2），"
                f"实得 {rate_s!r}")
        try:
            years = float(years_s)
        except ValueError:
            raise LedgerError(f"第 {lineno} 行：期限不是数字：{years_s!r}")
        n = round(years * 12)
        if n < 1 or n > 1200:
            raise LedgerError(f"第 {lineno} 行：期限超出 1 期-100 年：{years_s!r}")
        start = parse_date(start_s, lineno, "首期")
        method = METHOD_ALIASES.get(method_s.lower()) or METHOD_ALIASES.get(method_s)
        if method is None:
            raise LedgerError(
                f"第 {lineno} 行：还款方式只允许 annuity/等额本息、"
                f"linear/等额本金，实得 {method_s!r}")
        key = normalize(name_s)
        if key in seen:
            raise LedgerError(
                f"第 {lineno} 行：贷款「{name_s}」重复记账"
                f"（首次在第 {seen[key]} 行）")
        seen[key] = lineno
        loans.append(Loan(key, name_s, principal, rate, years, start,
                          method, note, lineno))
    if len(loans) > MAX_LOANS:
        raise LedgerError(
            f"贷款 {len(loans)} 笔，超过 {MAX_LOANS} 笔——"
            f"消费贷置换房貸之类的腾挪不进本账本")
    return loans


def parse_prepays(path: Optional[str]) -> List[Prepay]:
    """解析预付历史：date/amount/target/mode[/note]。文件可缺省。

    target 必须是具体贷款名——历史要记到具体账上，不收 ALL。
    """
    if path is None:
        return []
    try:
        rows = _read_rows(path, "预付历史")
    except LedgerError:
        return []  # 历史账本允许不存在
    prepays: List[Prepay] = []
    for lineno, cols in rows:
        if len(cols) >= 4 and cols[0].strip().lower() == "date":
            continue  # 表头
        if len(cols) not in (4, 5):
            raise LedgerError(
                f"第 {lineno} 行：需要 4-5 列（date/amount/target/mode[/note]），"
                f"实得 {len(cols)} 列")
        date = parse_date(cols[0], lineno, "还款")
        amount_s, target_s, mode_s = (c.strip() for c in cols[1:4])
        note = cols[4].strip() if len(cols) == 5 else ""
        try:
            amount = float(amount_s)
        except ValueError:
            raise LedgerError(f"第 {lineno} 行：金额不是数字：{amount_s!r}")
        if amount <= 0:
            raise LedgerError(f"第 {lineno} 行：金额必须 > 0，实得 {amount_s!r}")
        mode = mode_s.lower()
        if mode not in (MODE_TERM, MODE_PAYMENT):
            raise LedgerError(
                f"第 {lineno} 行：mode 只允许 term(缩期)/payment(减供)，"
                f"实得 {mode_s!r}")
        if target_s.lower() == "all" or not target_s:
            raise LedgerError(
                f"第 {lineno} 行：target 要写具体贷款名——历史要记到具体账上"
                f"（当时还的哪笔，position 能帮你对出来）")
        prepays.append(Prepay(date, amount, normalize(target_s), mode, note,
                              lineno))
    prepays.sort(key=lambda p: (p.date, p.line))
    return prepays


def load(path_loans: str, path_prepays: Optional[str]):
    loans = parse_loans(path_loans)
    if not loans:
        raise Refusal("贷款账本是空的——先抄进你的契约，再来赎。")
    prepays = parse_prepays(path_prepays)
    known = {l.key for l in loans}
    for p in prepays:
        if p.target not in known:
            raise LedgerError(
                f"第 {p.line} 行：target「{p.target}」不在贷款账本里"
                f"（在册：{'、'.join(l.name for l in loans)}）")
    return loans, prepays


# ---------------------------------------------------------------- annuity math


def month_rate(rate_pct: float) -> float:
    return rate_pct / 1200.0


def true_annual(rate_pct: float) -> float:
    """名义年利率的月复利口径——「4.2%」的真实价格是 4.28%。"""
    return (1.0 + month_rate(rate_pct)) ** 12 - 1.0


def annuity_payment(principal: float, i: float, n: int) -> float:
    g = (1.0 + i) ** n
    return principal * i * g / (g - 1.0)


def annuity_periods(bal: float, i: float, pay: float) -> int:
    """余额 bal、每期供 pay（> bal·(1+i)）下的清偿期数（向上取整）。"""
    if pay <= bal * i:
        raise LedgerError(f"月供 {pay:.2f} 盖不住月息 {bal * i:.2f}——贷款永不结清")
    n_exact = math.log(pay / (pay - bal * i)) / math.log(1.0 + i)
    return max(1, math.ceil(n_exact - 1e-9))


def schedule_rows(bal: float, i: float, method: str, n: int,
                  pay: Optional[float], pp: Optional[float],
                  first_k: int, first_date: datetime.date) -> List[Row]:
    """从余额 bal 起生成 n 期计划；annuity 给每期供 pay、linear 给每期
    本金 pp。末期自动收缩：余额不足整期时按实际余额结清（末期供更小）。
    """
    rows: List[Row] = []
    b = bal
    for t in range(1, n + 1):
        interest = b * i
        if t == n:
            principal = b
        elif method == "annuity":
            principal = pay - interest
        else:
            principal = pp
        b -= principal
        rows.append(Row(first_k + t - 1, add_months(first_date, t - 1),
                        interest, principal, interest + principal, max(b, 0.0)))
    return rows


def term_periods(bal: float, method: str, i: float, pay: float,
                 pp: float) -> int:
    """缩期解的新期数：供额（或每期本金）不变。"""
    if method == "annuity":
        return annuity_periods(bal, i, pay)
    return max(1, math.ceil(bal / pp - 1e-9))


# ---------------------------------------------------------------- replay


def effective_k(start: datetime.date, date: datetime.date) -> int:
    """预付生效期界：第 p 期还款后、第 p+1 期计息前。"""
    return months_done(start, date)


def loan_prepays(loan: Loan, prepays: List[Prepay]) -> List[Prepay]:
    return [p for p in prepays if p.target == loan.key]


def replay(loan: Loan, prepays: List[Prepay]) -> Tuple[List[Row], List[Event]]:
    """重放一笔贷款的完整时间线：正常摊销 + 预付事件即时重算剩余计划。

    预付在第 p 期还款后生效，下一期利息按新余额计。term 保持供额解新
    期数；payment 保持期数解新供额。预付 ≥ 届时余额 = 结清，exit 2。
    """
    i = month_rate(loan.rate)
    n0 = round(loan.years * 12)
    bal = loan.principal
    pay = annuity_payment(bal, i, n0) if loan.method == "annuity" else None
    pp = bal / n0 if loan.method == "linear" else None
    end_k = n0
    rows: List[Row] = []
    events: List[Event] = []
    by_k: Dict[int, List[Prepay]] = {}
    for p in prepays:
        by_k.setdefault(effective_k(loan.start, p.date), []).append(p)
    k = 0
    while k < end_k and bal > EPS:
        k += 1
        interest = bal * i
        if k == end_k:
            principal = bal
        elif loan.method == "annuity":
            principal = pay - interest
        else:
            principal = pp
        payment = interest + principal
        bal -= principal
        rows.append(Row(k, add_months(loan.start, k - 1), interest, principal,
                        payment, max(bal, 0.0)))
        for p in by_k.get(k, ()):
            if bal <= EPS or p.amount >= bal - EPS:
                raise LedgerError(
                    f"第 {p.line} 行：预付 ¥{p.amount:,.0f} ≥ 届时余额"
                    f"——那是结清，不进本账本（本件只管「还一部分」）")
            n_before = end_k - k
            pay_before = rows[-1].payment
            bal -= p.amount
            if p.mode == MODE_TERM:
                n_new = min(term_periods(bal, loan.method, i, pay, pp),
                            end_k - k)
                end_k = k + n_new
            else:
                n_new = end_k - k
                if loan.method == "annuity":
                    pay = annuity_payment(bal, i, n_new)
                else:
                    pp = bal / n_new
            pay_after = pay if loan.method == "annuity" else bal / n_new + bal * i
            events.append(Event(k, rows[-1].date, p.amount, p.mode,
                                n_before, n_new, pay_before, pay_after))
            rows[-1] = rows[-1]._replace(balance=max(bal, 0.0))
    return rows, events


def ledger_positions(loans: List[Loan], prepays: List[Prepay],
                     today: datetime.date):
    """每笔贷款：截至 today 的 (已还rows, 剩余计划rows, 事件)。"""
    out = []
    for loan in loans:
        rows, events = replay(loan, loan_prepays(loan, prepays))
        done = min(months_done(loan.start, today), len(rows))
        out.append((loan, rows[:done], rows[done:], events))
    return out


def allocate(amount: float, caps: List[Tuple[Loan, float]]):
    """组合贷分配：利率降序（同利率按上限降序）依次填装，封顶按余额。

    返回 [(loan, share)]；总额会分完（caps 合计 < amount 时截尾并披露）。
    """
    out = []
    rest = amount
    for loan, cap in sorted(caps, key=lambda t: (-t[0].rate, -t[1])):
        if rest <= EPS:
            break
        take = min(rest, cap)
        if take > EPS:
            out.append((loan, take))
            rest -= take
    return out


# ---------------------------------------------------------------- savings


def total_interest(rows: List[Row]) -> float:
    return sum(r.interest for r in rows)


def simulate_prepay(future_rows: List[Row], method: str, i: float,
                    amount: float, mode: str):
    """在 future_rows 首期之前预付 amount（预付即时生效），返回新计划。

    返回 (n_new, new_rows, saving)；saving = 原剩余利息 − 新剩余利息。
    amount ≥ 余额 = 结清，拒绝（Refusal 由调用方翻译）。
    """
    bal0 = future_rows[0].balance + future_rows[0].principal
    # 期初口径：Row.balance 是该期还款后余额；预付在首期之前生效，
    # 首期利息按 (期初 − 预付) 计，与 replay 的「整期后生效」口径同相。
    n_rem = len(future_rows)
    first_k, first_date = future_rows[0].k, future_rows[0].date
    if amount >= bal0 - EPS:
        raise Refusal(
            f"预付 ¥{amount:,.0f} ≥ 余额 ¥{bal0:,.0f}——那是结清："
            f"本件只管「还一部分」，结清走银行柜台")
    new_bal = bal0 - amount
    if mode == MODE_TERM:
        if method == "annuity":
            pay = future_rows[0].payment
            n_new = min(term_periods(new_bal, method, i, pay, 0.0), n_rem)
            if n_new < 2:
                raise Refusal(
                    f"预付 ¥{amount:,.0f} 之后只剩 {n_new} 期——银行柜台会把"
                    f"它办成结清：本件只管「还一部分」，把尾款留给它")
            new_rows = schedule_rows(new_bal, i, method, n_new, pay, None,
                                     first_k, first_date)
        else:
            pp = future_rows[0].principal
            n_new = min(term_periods(new_bal, method, i, 0.0, pp), n_rem)
            if n_new < 2:
                raise Refusal(
                    f"预付 ¥{amount:,.0f} 之后只剩 {n_new} 期——银行柜台会把"
                    f"它办成结清：本件只管「还一部分」，把尾款留给它")
            new_rows = schedule_rows(new_bal, i, method, n_new, None, pp,
                                     first_k, first_date)
    else:
        n_new = n_rem
        if method == "annuity":
            new_rows = schedule_rows(new_bal, i, method, n_rem,
                                     annuity_payment(new_bal, i, n_rem), None,
                                     first_k, first_date)
        else:
            new_rows = schedule_rows(new_bal, i, method, n_rem, None,
                                     new_bal / n_rem, first_k, first_date)
    return n_new, new_rows, total_interest(future_rows) - total_interest(new_rows)


# ---------------------------------------------------------------- two worlds


def world_wealth(pay_stream: List[float], invest0: float, m: float,
                 wage: float) -> float:
    """期末现金流惯例：第 t 期末 w = w·(1+m) + (工资−月供)。

    期初在场的钱滚整期利息（与银行计息同相），当期结余期末进账、
    下期起息。invest0 是第 0 期末已在账户里的钱；pay_stream 逐期月供，
    还清后的期数 pay=0（结余全进投资）。"""
    w = invest0
    for pay in pay_stream:
        w = w * (1.0 + m) + (wage - pay)
    return w


def equivalent_check(future_rows: List[Row], method: str, i: float,
                     amount: float, mode: str, m: float,
                     wage: float) -> Tuple[float, float]:
    """两世界终值：A 今天预付 amount 按新计划走；B 把 amount 拿去投资、
    原计划照走。两世界工资相同、原计划末日同时点结账。

    m = 月合同时两世界必平——「提前还款 = 无风险税后投资，收益率 =
    合同利率」定理的数值面。返回 (wealth_payoff, wealth_invest)。
    """
    _, new_rows, _ = simulate_prepay(future_rows, method, i, amount, mode)
    n_orig = len(future_rows)
    pay_orig = [r.payment for r in future_rows]
    pay_new = [r.payment for r in new_rows] + [0.0] * (n_orig - len(new_rows))
    return (world_wealth(pay_new, 0.0, m, wage),
            world_wealth(pay_orig, amount, m, wage))


# ---------------------------------------------------------------- fmt


def dw(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s: str, w: int) -> str:
    return s + " " * max(0, w - dw(s))


def yen(x: float) -> str:
    return f"¥{x:,.0f}"


def yen2(x: float) -> str:
    return f"¥{x:,.2f}"


def pct_s(p: float, digits: int = 1) -> str:
    return f"{p * 100:.{digits}f}%"


def method_txt(method: str) -> str:
    return "等额本息" if method == "annuity" else "等额本金"


def factory_rows(loan: Loan) -> List[Row]:
    """出厂口径：无任何预付的全期计划。"""
    i = month_rate(loan.rate)
    n0 = round(loan.years * 12)
    pay = annuity_payment(loan.principal, i, n0) if loan.method == "annuity" else None
    pp = loan.principal / n0 if loan.method == "linear" else None
    return schedule_rows(loan.principal, i, loan.method, n0, pay, pp,
                         1, loan.start)


# ---------------------------------------------------------------- commands


def cmd_plan(args) -> int:
    loans, prepays = load(args.loans, args.prepays)
    today = parse_today(args.today)
    parts = ledger_positions(loans, prepays, today)
    print(f"赎契总账 · {len(loans)} 笔贷款 · 截至 {today.isoformat()}")
    tot_int = tot_prin = 0.0
    for loan, done, fut, events in parts:
        if not fut:
            print(f"  {loan.name}：已于历史中结清（含预付重放）——不再计息")
            continue
        i = month_rate(loan.rate)
        n0 = round(loan.years * 12)
        pay0 = (annuity_payment(loan.principal, i, n0)
                if loan.method == "annuity" else None)
        rows0 = factory_rows(loan)
        f_int = total_interest(rows0)
        tot_int += f_int
        tot_prin += loan.principal
        pay_now = fut[0].payment if not events or loan.method == "linear" \
            else rows0[0].payment
        print(f"  {pad(loan.name, 10)}本金 {yen(loan.principal)} @ "
              f"{loan.rate:.2f}% {loan.years:g} 年 {method_txt(loan.method)}"
              f" · 月供 {yen2(pay_now)} · {loan.start.isoformat()} 首期")
        cum = 0.0
        half_k = None
        for r in rows0:
            cum += r.interest
            if half_k is None and cum >= f_int / 2.0:
                half_k = r.k
        print(
            f"    出厂口径（未计预付）：{n0} 期 · 总利息 {yen(f_int)} = "
            f"本金的 {pct_s(f_int / loan.principal)} · 利息半程点 第 "
            f"{half_k}/{n0} 期（{pct_s(half_k / n0)} 处）——前期利息重是"
            f"摊销的形状，不是阴谋")
        if events:
            alive_int = total_interest(done) + total_interest(fut)
            print(
                f"    计入 {len(events)} 笔预付后的实际口径：全周期利息 "
                f"{yen(alive_int)}（已省 {yen(f_int - alive_int)}）"
                f" · 剩余利息 {yen(total_interest(fut))}")
        print(
            f"    真实利率：{loan.rate:.2f}% 是名义口径，月复利计的真实价格 "
            f"{true_annual(loan.rate) * 100:.2f}%")
    ratio = tot_int / tot_prin
    pays = [fut[0].payment for _l, _d, fut, _e in parts if fut]
    print(f"  组合月供合计 {yen2(sum(pays))}/月"
          f"（本期口径：linear 逐月递减）")
    print(f"  组合出厂总利息 {yen(tot_int)} / 本金 {yen(tot_prin)} = "
          f"{pct_s(ratio)}")
    if ratio >= GATE_DOUBLE:
        print(
            f"  双倍房灯 ✗ 出厂利息追平本金——这套房按出厂口径要付 "
            f"{pct_s(1 + ratio)} 的价：期限与利率是价格的两个把手，"
            f"预付是第三个（exit 4）")
        return 4
    print(f"  双倍房灯未亮（出厂利息 < 本金；≥ {pct_s(GATE_DOUBLE, 0)} 亮）")
    if args.years_detail:
        print("  年度移交表（计入预付重放：各笔当年利息/本金合计）：")
        horizon = max(round(l.years * 12) for l in loans)
        for y in range(1, horizon // 12 + 1):
            i_y = p_y = 0.0
            for loan, _done, _fut, _ev in parts:
                rows_all, _ = replay(loan, loan_prepays(loan, prepays))
                seg = rows_all[(y - 1) * 12:y * 12]
                i_y += sum(r.interest for r in seg)
                p_y += sum(r.principal for r in seg)
            if i_y == 0 and p_y == 0:
                continue
            tag = " ← 本金反超利息" if p_y > i_y else ""
            print(f"    第 {y:2d} 年 利息 {yen(i_y):>10}  本金 {yen(p_y):>10}{tag}")
    print("  诚实条款：出厂口径不含预付；LPR 变动、违约金、税务不建模。")
    return 0


def cmd_position(args) -> int:
    loans, prepays = load(args.loans, args.prepays)
    today = parse_today(args.today)
    parts = ledger_positions(loans, prepays, today)
    print(f"贷款位置单 · 截至 {today.isoformat()}")
    any_alive = False
    tot_done_pay = tot_done_int = tot_plan_int = tot_bal = 0.0
    tot_done_k = tot_n0 = 0
    payoff_total = 0.0
    for loan, done, fut, events in parts:
        n0 = round(loan.years * 12)
        if not fut:
            print(f"  {loan.name}：已结清（{len(done)} 期）")
            continue
        any_alive = True
        bal = fut[0].balance
        done_int = total_interest(done)
        done_pay = sum(r.payment for r in done)
        fut_int = total_interest(fut)
        payoff_total += bal
        tot_bal += bal
        tot_done_pay += done_pay
        tot_done_int += done_int
        tot_plan_int += done_int + fut_int
        tot_done_k += len(done)
        tot_n0 += len(done) + len(fut)
        n_total = len(done) + len(fut)
        n_txt = f"{len(done)}/{n_total}"
        n_extra = f"（出厂 {n0}，预付已缩）" if n_total != n0 else ""
        ev_txt = ""
        if events:
            last_ev = events[-1]
            ev_txt = (f" · 最近预付 第{last_ev.k}期 {yen(last_ev.amount)}"
                      f"（{'缩期' if last_ev.mode == MODE_TERM else '减供'}）")
        print(
            f"  {pad(loan.name, 10)}已还 {n_txt} 期{n_extra}"
            f"（{pct_s(len(done) / n_total)}）· 余额 {yen(bal)}"            f"（本金的 {pct_s(bal / loan.principal)}）· 剩余利息 {yen(fut_int)}"
            f" · 第 {fut[0].k} 期 {fut[0].date.isoformat()} 到期{ev_txt}")
        if done:
            print(
                f"    已还合计 {yen(done_pay)}，其中利息 {yen(done_int)}"
                f"（{pct_s(done_int / done_pay)}）——这是过去 "
                f"{len(done) / 12:.1f} 年租钱的价格")
    if not any_alive:
        print("  没有在还的贷款——账本可以归档了。")
        return 0
    prin_pct = 1.0 - tot_bal / sum(l.principal for l in loans)
    int_pct = tot_done_int / tot_plan_int if tot_plan_int else 0.0
    print(
        f"  三种进度：期数 {pct_s(tot_done_k / tot_n0)} · 本金 "
        f"{pct_s(prin_pct)} · 利息 {pct_s(int_pct)}"
        f"——你在契约里的位置不是一个数")
    print(
        f"  今天一次结清全部代价：{yen(payoff_total)}"
        f"（余额合计，不含当期已计未付利息）")
    print("  诚实条款：start 按首期还款日口径；--today 之前的整期计「已还」。")
    return 0


def cmd_prepay(args) -> int:
    loans, prepays = load(args.loans, args.prepays)
    today = parse_today(args.today)
    at = parse_date(args.at, 0, "预付") if args.at else today
    parts = ledger_positions(loans, prepays, at)
    if args.target and normalize(args.target) != "all":
        chosen = [(l, f) for l, _d, f, _e in parts
                  if l.key == normalize(args.target)]
        if not chosen:
            raise LedgerError(
                f"target「{args.target}」不在贷款账本里"
                f"（在册：{'、'.join(l.name for l in loans)}、ALL）")
    else:
        chosen = [(l, f) for l, _d, f, _e in parts if f]
    alive = [(l, f) for l, f in chosen if f]
    if not alive:
        raise Refusal("目标贷款已全部结清——预付没有标的。")
    # 先还低息灯：指定了具体贷款而更高利率的贷款在册（扫全部在册，不只目标）
    hi_alive = max((l.rate for l, _d, f, _e in parts if f), default=0.0)
    specific = args.target and normalize(args.target) != "all"
    tgt = None
    if specific:
        tgt = next(l for l, _f in alive if l.key == normalize(args.target))
    n_alive = sum(1 for _l, _d, f, _e in parts if f)
    if specific and n_alive > 1 and hi_alive - tgt.rate > GATE_WRONG:
            best = max((l for l, _d, f, _e in parts if f),
                       key=lambda l: l.rate)
            print(
                f"先还低息灯 ✗ 「{tgt.name}」{tgt.rate:.2f}% 而"
                f"「{best.name}」{best.rate:.2f}% 在册——同样的钱放在高息债上"
                f"省息更多（每 1 元年租差 {best.rate - tgt.rate:.2f} 个点）"
                f"（exit 4）", file=sys.stderr)
            print("（反平反条款：若高息债在违约金锁定期内、或日后想转贷，"
                  "这条灯可以平反——付违约金前先读合同）", file=sys.stderr)
            return 4
    # 拟议分配：ALL 走利率降序；指定贷款拿全额
    if specific:
        plan_shares = [(tgt, args.amount)]
    else:
        plan_shares = allocate(args.amount,
                               [(l, f[0].balance + f[0].principal)
                                for l, f in alive])
        if not plan_shares:
            raise Refusal("闲钱足以结清全部贷款——那是另一道题，本件只管「还一部分」。")
        eaten = sum(s for _l, s in plan_shares)
        if eaten < args.amount - 0.01:
            print(f"  横幅：闲钱 {yen(args.amount)} 超过在册余额合计，"
                  f"只吃下 {yen(eaten)}——剩的请走结清柜台")
    print(f"提前还款模拟 · 拟还 {yen(args.amount)} · 模式 {MODE_LABEL[args.mode]}"
          f" · 生效 {at.isoformat()}")
    total_saving = 0.0
    for loan, share in plan_shares:
        fut = next(f for l, f in alive if l.key == loan.key)
        i = month_rate(loan.rate)
        n_new, new_rows, saving = simulate_prepay(fut, loan.method, i,
                                                  share, args.mode)
        total_saving += saving
        if args.mode == MODE_TERM:
            print(
                f"  {loan.name}：预付 {yen(share)}（余额 {yen(fut[0].balance)}）"
                f"→ 省息 {yen(saving)} · 期限 {len(fut)}→{n_new} 期"
                f"（提前 {(len(fut) - n_new) / 12:.1f} 年脱契）"
                f" · 月供不变 {yen2(fut[0].payment)}")
        else:
            old_pay = fut[0].payment
            new_pay = new_rows[0].payment
            print(
                f"  {loan.name}：预付 {yen(share)}（余额 {yen(fut[0].balance)}）"
                f"→ 省息 {yen(saving)} · 月供 {yen2(old_pay)}→{yen2(new_pay)}"
                f"（−{yen2(old_pay - new_pay)}/月）· 期限不变")
        if share < MIN_PREPAY_NOTE:
            print("    横幅：金额低于 1 万——多数银行设提前还款最低额与"
                  "预约门槛，先问贷款行")
    if not specific and len(plan_shares) > 1:
        print("  组合贷分配（利率降序，每 1 元先去最贵的债上）："
              + " · ".join(f"{l.name} {yen(s)}" for l, s in plan_shares))
    top_rate = max(l.rate for l, _s in plan_shares)
    print(f"  合计省息 {yen(total_saving)}")
    print(
        f"  等效收益率定理：这些钱等于一笔年化 {top_rate:.2f}%"
        f"（月复利 {true_annual(top_rate) * 100:.2f}%）的无风险、税后投资"
        f"——没有第二个免费午餐")
    print("  诚实条款：不算违约金（头 1-3 年多数银行收 1%）；不预测 LPR；"
          "赎与不赎，人的决定。")
    return 0


def cmd_compare(args) -> int:
    loans, prepays = load(args.loans, args.prepays)
    today = parse_today(args.today)
    at = parse_date(args.at, 0, "预付") if args.at else today
    parts = ledger_positions(loans, prepays, at)
    alive = [(l, f) for l, _d, f, _e in parts if f]
    if not alive:
        raise Refusal("没有在还的贷款——compare 无从比起。")
    shares = allocate(args.amount,
                      [(l, f[0].balance + f[0].principal) for l, f in alive])
    if not shares:
        raise Refusal("闲钱足以结清全部贷款——那是另一道题，本件只管「还一部分」。")
    print(f"缩期 vs 减供 · 同样拟还 {yen(args.amount)} · 生效 {at.isoformat()}")
    tot_term = tot_pay = 0.0
    for loan, share in shares:
        fut = next(f for l, f in alive if l.key == loan.key)
        i = month_rate(loan.rate)
        n_t, rows_t, save_t = simulate_prepay(fut, loan.method, i, share,
                                              MODE_TERM)
        _n_p, rows_p, save_p = simulate_prepay(fut, loan.method, i, share,
                                               MODE_PAYMENT)
        tot_term += save_t
        tot_pay += save_p
        old_pay = fut[0].payment
        new_pay_p = rows_p[0].payment
        print(f"  {loan.name}（{loan.rate:.2f}%，余额 {yen(fut[0].balance)}，"
              f"拟投 {yen(share)}）：")
        print(
            f"    缩期：省息 {yen(save_t)} · 月供不变 {yen2(old_pay)} · "
            f"{len(fut)}→{n_t} 期（提前 {(len(fut) - n_t) / 12:.1f} 年）")
        print(
            f"    减供：省息 {yen(save_p)} · 月供 →{yen2(new_pay_p)}"
            f"（−{yen2(old_pay - new_pay_p)}/月）· 期限不变")
    diff = tot_term - tot_pay
    if diff > 0:
        print(
            f"  省息差：缩期多省 {yen(diff)}"
            f"（+{pct_s(diff / tot_pay if tot_pay else 0.0)}）——"
            f"钱离场得更早，利息就更少")
    else:
        print(f"  省息差：{yen(diff)}")
    print(
        "  判据（不替你选）：现金流有余选缩期吃满利差；月供已贴着收入红线，"
        "减供买的是每个月的呼吸空间——两种都是赎，方向不同")
    return 0


def cmd_myth(args) -> int:
    loans, prepays = load(args.loans, args.prepays)
    today = parse_today(args.today)
    parts = ledger_positions(loans, prepays, today)
    alive = [(l, _d, f) for l, _d, f, _e in parts if f]
    if not alive:
        raise Refusal("没有在还的贷款——谬误法庭休庭。")
    loan, done, fut = max(alive, key=lambda t: t[0].rate)
    bal_now = fut[0].balance
    amt = args.amount if args.amount else min(100000.0, bal_now * 0.25)
    amt = min(amt, bal_now * 0.5)
    if amt < MYTH_FLOOR:
        amt = max(MYTH_FLOOR, bal_now * 0.01)
    i = month_rate(loan.rate)
    n_rem = len(fut)
    print("谬误法庭 ·「等额本息还到一半，利息早还完了，再还不划算」——当庭对质")
    print("  嫌疑：把「已还的钱里利息占多数」当成了「以后还的都不划算」")
    if done:
        done_int = total_interest(done)
        done_pay = sum(r.payment for r in done)
        print(
            f"  先看账：{loan.name} 已还 {len(done)} 期，已还利息 "
            f"{yen(done_int)} 占已还总额 {pct_s(done_int / done_pay)}"
            f"——直觉的来源是真的")
    marks = []
    for t, label in ((12, "刚起步（第 12 期后）"),
                     (max(1, n_rem // 2), "剩余半程（中点后）"),
                     (max(1, int(n_rem * 0.85)), "临近尾声（85% 处）")):
        t = max(1, min(t, n_rem - 1))
        bal_t = fut[t - 1].balance
        if bal_t <= amt * 1.05:
            continue
        pay = fut[0].payment if loan.method == "annuity" else None
        pp = fut[0].principal if loan.method == "linear" else None
        base = schedule_rows(bal_t, i, loan.method, n_rem - t, pay, pp,
                             t + 1, fut[t].date)
        n_new = min(term_periods(bal_t - amt, loan.method, i, pay or 0.0,
                                 pp or 0.0), n_rem - t)
        new_rows = schedule_rows(bal_t - amt, i, loan.method, n_new, pay, pp,
                                 t + 1, fut[t].date)
        saving = total_interest(base) - total_interest(new_rows)
        marks.append((label, saving, (n_rem - t - n_new) / 12.0))
    print(f"  再对质：同样还 {yen(amt)}（缩期），在不同进度下省息：")
    for label, saving, yrs in marks:
        print(f"    {label}：省 {yen(saving)}（提前 {yrs:.1f} 年）")
    if len(marks) >= 2:
        print(
            "  省息公式里没有「已还进度」这个变量：省息 = 本金 × "
            "((1+i)^提前期数 − 1)——越早还省得越多、越晚省得越少、永不为负")
        print(
            "    不存在「不划算期」，只存在「早还更划算期」；已还的利息是"
            "过去租钱的租金，不改变下一元钱的租金率")
    print(
        "  并案谬误二：「提前还款会减月供」——错。银行默认缩期：月供不动、"
        "期限缩短；只有主动选「减供」月供才降")
    print("  本庭不判还与不还，只判说法的真伪。")
    return 0


def cmd_vsinvest(args) -> int:
    loans, prepays = load(args.loans, args.prepays)
    today = parse_today(args.today)
    parts = ledger_positions(loans, prepays, today)
    alive = [(l, _d, f) for l, _d, f, _e in parts if f]
    if not alive:
        raise Refusal("没有在还的贷款——还贷 vs 投资无从比起。")
    loan, _done, fut = max(alive, key=lambda t: t[0].rate)
    i = month_rate(loan.rate)
    eq = true_annual(loan.rate)
    if args.yield_ is None:
        raise Refusal(
            "没有 --yield 就拒绝对比——不给你的实绩收益率，本件不发明一个。"
            f"保本等效线先给你：还贷的等效年化 = {eq * 100:.2f}%"
            f"（月复利口径），投资实绩税后跑不赢它，钱就该去债上")
    amt = min(args.amount, fut[0].balance)
    m = month_rate(args.yield_)
    gap = args.yield_ / 100.0 - eq
    # 等效定理数值面：m 取合同时两世界终值必平
    wage = 3.0 * fut[0].payment
    w_eq_pay, w_eq_inv = equivalent_check(fut, loan.method, i, amt,
                                          args.mode, i, wage)
    drift = abs(w_eq_pay - w_eq_inv) / max(w_eq_pay, w_eq_inv, 1.0)
    w_pay, w_inv = equivalent_check(fut, loan.method, i, amt, args.mode,
                                    m, wage)
    print(f"还贷 vs 投资 · 拟还 {yen(amt)}"
          f"（{MODE_LABEL[args.mode].split('（')[0]}） · 对质贷款 "
          f"{loan.name}（{loan.rate:.2f}%，在册最高）")
    print(f"  你的收益率 {args.yield_:.2f}%/年——如实声明：请用历史实绩，"
          f"不用预期")
    print(
        f"  还贷等效年化（无风险·税后）= 合同 {loan.rate:.2f}% = "
        f"月复利口径 {eq * 100:.2f}%")
    print(f"  世界A 还贷：今天付 {yen(amt)}，此后省下的月供流按 "
          f"{args.yield_:.2f}% 复利到原计划末日")
    print(f"  世界B 投资：{yen(amt)} 按 {args.yield_:.2f}% 复利，"
          f"月供照旧从工资出")
    print(
        f"  原计划末日（{fut[-1].date.isoformat()}）财富：A {yen2(w_pay)} vs "
        f"B {yen2(w_inv)} → {'还贷' if w_pay > w_inv else '投资'}世界多 "
        f"{yen2(abs(w_pay - w_inv))}")
    print(f"  等效校验：m=合同时两世界终值差 {drift:.1e}（应为 0）")
    if gap < -GATE_INVEST:
        print(
            f"  跑输灯 ✗ 实绩 {args.yield_:.2f}% 跑输等效线 "
            f"{eq * 100:.2f}%（{gap * 100:+.2f}pp）——这笔钱在债上更值钱；"
            f"先还后投不是保守，是套利方向的纠正（exit 4）")
        print("  诚实条款：以税后实绩为准；未来的收益不是实绩的担保。")
        return 4
    if gap > GATE_INVEST:
        print(
            f"  投资灯 ✓ 实绩 {args.yield_:.2f}% 跑赢等效线 "
            f"{gap * 100:+.2f}pp——但先确认它是税后、可复制的实绩；"
            f"波动率没有进这道账")
        return 0
    print(
        f"  掷币带 ±0.5pp：{args.yield_:.2f}% 与等效线分不出胜负——"
        f"流动性偏好（手里留现金）本身就是一个正当理由")
    return 0


def cmd_batch(args) -> int:
    loans, prepays = load(args.loans, args.prepays)
    today = parse_today(args.today)
    at = parse_date(args.at, 0, "预付") if args.at else today
    parts = ledger_positions(loans, prepays, at)
    alive = [(l, _d, f) for l, _d, f, _e in parts if f]
    if not alive:
        raise Refusal("没有在还的贷款——一次与分批无从比起。")
    if args.parts < 2:
        raise LedgerError("--parts 至少 2 批，否则就是一次（用 prepay）")
    if args.total / args.parts < MIN_PREPAY_NOTE:
        print("  横幅：每批低于 1 万——多数银行设提前还款最低额，先问贷款行")

    def remaining_int(extra_prepays):
        """各贷款按（历史+extra）重放后，at 之后的剩余利息合计。"""
        total = 0.0
        for loan in loans:
            rows, _ = replay(loan, loan_prepays(loan, prepays)
                             + [p for p in extra_prepays
                                if p.target == loan.key])
            k = min(months_done(loan.start, at), len(rows))
            total += total_interest(rows[k:])
        return total

    base_int = remaining_int([])
    per = args.total / args.parts
    # 一次：今天 allocate 到各贷款
    caps_now = []
    for loan in loans:
        rows, _ = replay(loan, loan_prepays(loan, prepays))
        k = min(months_done(loan.start, at), len(rows))
        if k < len(rows):
            caps_now.append((loan, rows[k].balance + rows[k].principal))
    once_prepays = [Prepay(at, s, l.key, MODE_TERM, "once", 0)
                    for l, s in allocate(args.total, caps_now)]
    save_once = base_int - remaining_int(once_prepays)
    # 分批：每年今天 allocate 到届时余额
    multi_prepays: List[Prepay] = []
    for j in range(args.parts):
        year_at = add_months(at, 12 * j)
        caps_j = []
        for loan in loans:
            rows, _ = replay(loan, loan_prepays(loan, prepays) + multi_prepays)
            k = min(months_done(loan.start, year_at), len(rows))
            if k < len(rows):
                caps_j.append((loan, rows[k].balance + rows[k].principal))
        shares = allocate(per, caps_j)
        if not shares:
            break
        multi_prepays += [Prepay(year_at, s, l.key, MODE_TERM, "batch", 0)
                          for l, s in shares]
    save_multi = base_int - remaining_int(multi_prepays)
    print(f"一次 vs 分批 · 共 {yen(args.total)} · 分 {args.parts} 批"
          f"每年一批每批 {yen(per)}（首批 {at.isoformat()}） · 模式 缩期")
    print(f"  一次还清 {yen(args.total)}：省息 {yen(save_once)}")
    print(f"  分 {args.parts}×{yen(per)}：省息 {yen(save_multi)}"
          f"（少省 {yen(save_once - save_multi)}）")
    if save_once > save_multi:
        top = max(l.rate for l, _d, _f in alive)
        print(
            f"  时间在钱前面：后 {args.parts - 1} 批在场外多待 1-"
            f"{args.parts - 1} 年，每年按 {top:.2f}% 付机会成本")
    print(
        "  但分批保留的流动性不是免费的错——应急现金的价值本账本不定价；"
        "两个都是对的，看你睡得着哪边")
    return 0


def cmd_validate(args) -> int:
    loans, prepays = load(args.loans, args.prepays)
    today = parse_today(args.today)
    print(f"账本体检 · {len(loans)} 笔贷款 · {len(prepays)} 条预付历史 · "
          f"--today {today.isoformat()}")
    worst_split = worst_return = worst_zero = 0.0
    for loan in loans:
        mine = loan_prepays(loan, prepays)
        rows, _events = replay(loan, mine)
        for r in rows:
            worst_split = max(worst_split, abs(r.payment - r.interest
                                               - r.principal))
        worst_return = max(worst_return, abs(sum(r.principal for r in rows)
                                              + sum(p.amount for p in mine)
                                              - loan.principal))
        worst_zero = max(worst_zero, rows[-1].balance if rows else 0.0)
        if loan.method == "annuity":
            full_pay = annuity_payment(loan.principal, month_rate(loan.rate),
                                       round(loan.years * 12))
            over = [r for r in rows if r.payment > full_pay + 0.01]
            if over:
                raise Gate(f"「{loan.name}」出现超过常规月供的期（第 "
                           f"{over[0].k} 期 {yen2(over[0].payment)}）"
                           f"——缩期解错了")
    print(f"  逐期拆分恒等式：payment−interest−principal 最大残差 "
          f"{worst_split:.2e}")
    print(f"  本金回归：Σ本金+Σ预付−初始本金 最大残差 {worst_return:.2e}"
          f"（末期半分钱内的舍入属正常）")
    print(f"  期末余额归零：最大残差 {worst_zero:.2e}")
    parts = ledger_positions(loans, prepays, today)
    alive = [(l, f) for l, _d, f, _e in parts if f]
    if alive:
        loan, fut = max(alive, key=lambda t: t[0].rate)
        i = month_rate(loan.rate)
        amt = min(fut[0].balance * 0.2, 300000.0)
        wage = 3.0 * fut[0].payment
        w1, w2 = equivalent_check(fut, loan.method, i, amt, MODE_TERM, i, wage)
        rel = abs(w1 - w2) / max(abs(w1), 1.0)
        print(f"  等效定理（m=合同利率两世界终值必平）：相对差 {rel:.2e}")
        if rel > 1e-6:
            raise Gate(f"等效定理数值校验失败：相对差 {rel}")
        if len(alive) > 1:
            shares = allocate(100000.0, [(l, f[0].balance) for l, f in alive])
            if abs(sum(s for _l, s in shares) - 100000.0) > 0.01:
                raise Gate("分配恒等式失败：allocate 没把钱分完")
            print("  分配恒等式：allocate 合计 = 预付额 ✓")
    print("  口径披露：start=首期还款日；预付在整期还款后、次期计息前生效；"
          "LPR/违约金/税务不建模")
    print("  账本只记你抄进来的事实：它不连银行、不猜利率、不替你赎契。")
    return 0


# ---------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="赎契 —— 房贷摊销解构与提前还款决策")
    parser.add_argument("--version", action="version",
                        version=f"{PROG} {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("loans", help="贷款账本 TSV")
        p.add_argument("prepays", nargs="?", default=None,
                       help="预付历史 TSV（可选）")
        p.add_argument("--today", default=None, help="口径日 YYYY-MM-DD")

    for name, func, helptext in (
            ("plan", cmd_plan, "摊销总账解构（双倍房灯）"),
            ("position", cmd_position, "贷款位置单：三种进度+结清代价"),
            ("prepay", cmd_prepay, "提前还款模拟（等效收益率定理）"),
            ("compare", cmd_compare, "缩期 vs 减供对决"),
            ("myth", cmd_myth, "谬误法庭：利息早还完了？"),
            ("vsinvest", cmd_vsinvest, "还贷 vs 投资两世界"),
            ("batch", cmd_batch, "一次 vs 分批"),
            ("validate", cmd_validate, "恒等式体检")):
        p = sub.add_parser(name, help=helptext)
        common(p)
        if name == "plan":
            p.add_argument("--years-detail", action="store_true",
                           help="显示年度移交表")
        if name in ("prepay", "compare", "vsinvest"):
            p.add_argument("--amount", type=float, required=True,
                           help="拟预付金额（元）")
            p.add_argument("--mode", default=MODE_TERM,
                           choices=[MODE_TERM, MODE_PAYMENT],
                           help="term 缩期 / payment 减供（默认 term）")
            p.add_argument("--at", default=None,
                           help="预付生效日（默认 --today）")
        if name == "prepay":
            p.add_argument("--target", default="all",
                           help="还哪笔贷款：名字或 ALL（默认 ALL，利率降序）")
        if name == "vsinvest":
            p.add_argument("--yield", dest="yield_", type=float, default=None,
                           help="你的投资年化 %%（历史实绩；不给则拒绝对比）")
        if name == "myth":
            p.add_argument("--amount", type=float, default=None,
                           help="对质用金额（默认 10 万与余额 1/4 取小）")
        if name == "batch":
            p.add_argument("--total", type=float, required=True,
                           help="累计预付总额（元）")
            p.add_argument("--parts", type=int, default=5,
                           help="分几批（默认 5，每年一批）")
            p.add_argument("--at", default=None, help="首批生效日（默认 --today）")
        p.set_defaults(func=func)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LedgerError as exc:
        print(f"账本拒收：{exc}", file=sys.stderr)
        return 2
    except Refusal as exc:
        print(f"拒绝裁决：{exc}", file=sys.stderr)
        return 3
    except Gate as exc:
        print(f"门禁亮灯：{exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
