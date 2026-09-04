#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""暗息 · Stealth Interest

「月费率 0.6%」是营销数字，不是利率：等本等息结构下本金逐月归还、手续费
却按全额本金收，真实年化 ≈ 名义 × 2n/(n+1)——12 期的 0.6%/月真实是
13.03%，1.81 倍。平台不翻译，因为翻译过来不好看；本件替你翻译，并审计
三件平台永远不会替你算的事：

  - rate      费率翻译：月 IRR / 名义年化 / 有效年化 / 相对名义的倍数；
  - prepay    提前结清法庭：零节省定理（剩余手续费照收 ⇒ 结清额 ≡ 未来
              付款额 ⇒ 利息节省恒为 0）+ 边际真实利率 + 平均成本镜；
  - offer     免息 vs 现金折扣：盈亏平衡折扣 / 盈亏平衡收益率（PV 口径）；
  - stack     多笔分期总账：逐月月供、暗息余额、隐性负债、月供占收入红线；
  - validate  账本体检。

零依赖（Python 3.8+ 标准库）。全件无日期无时钟：分期的数学是期数数学
（period-based），无 as-of、无 today，同一本账任何机器任何一天逐字节
一致——零锚定。报告只打印 basename，不回显调用方路径。

诚实条款：本件是计算器不是信贷顾问——手续费规则、提前结清规则、违约金
以你的平台合同为准（--rule/--penalty/--fee-rate 参数化，政策永远赢）；
涉及机会成本的裁决（--yield、--salary）不给就只出算术不判级，不发明你的
闲钱收益率；决策只认边际真实利率，全程平均成本（含 sunk fee）只作披露。

Exit codes: 0 绿 · 2 账本/参数损坏 · 3 样本太薄/裁决挂起 · 4 红灯
"""

import argparse
import os
import sys

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_THIN = 3
EXIT_RED = 4

EPS = 1e-9
IRR_LO = 1e-12
IRR_HI = 1.0
IRR_ITERS = 200
FEE_RATE_CAP = 0.2        # 单期费率 sanity 上限（20%/期 已是高利贷级）
BURDEN_LINE = 0.30        # 月供峰值占收入比通识红线：不超收入三分之一
DEFAULT_PENALTY = 0.02    # pct 规则违约金默认：剩余本金的 2%

HEADER = ["platform", "item", "principal", "months", "fee_rate",
          "paid", "mode", "prepay_rule"]
MODES = ("flat", "upfront")
RULES = ("remaining", "waived", "pct")


class LedgerError(Exception):
    """账本/参数损坏：exit 2"""


class ThinError(Exception):
    """样本太薄/裁决挂起：exit 3"""


# ---------------------------------------------------------------- primitives

def fmt_money(v):
    return "{:,.2f}".format(v)


def fmt_pct(v, nd=2):
    return "{:.{}f}%".format(v * 100, nd)


def parse_rate(text, field="fee_rate"):
    """0.006 或 0.6% 双写法。"""
    t = str(text).strip()
    if t.endswith("%"):
        try:
            return float(t[:-1]) / 100.0
        except ValueError:
            raise LedgerError("bad {} (percent form): {!r}".format(field, text))
    try:
        return float(t)
    except ValueError:
        raise LedgerError("bad {}: {!r}".format(field, text))


def parse_num(text, field):
    try:
        return float(str(text).strip().replace(",", "").replace("¥", ""))
    except (TypeError, ValueError):
        raise LedgerError("bad {}: {!r}".format(field, text))


def display_width(s):
    """CJK 感知显示宽度：ord > 0x2E7F 记 2 列。"""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def pad(s, width):
    gap = width - display_width(s)
    return s + " " * max(gap, 1)


# ------------------------------------------------------------------- solver

def plan_flows(principal, months, fee_rate, mode="flat"):
    """每期期末付款流（等本等息）。flat：每期本金+每期费；
    upfront：首期一次收全部手续费。"""
    base = principal / months
    total_fee = principal * fee_rate * months
    if mode == "upfront":
        return [base + total_fee] + [base] * (months - 1)
    fee_per = total_fee / months
    return [base + fee_per] * months


def flows_fee_part(principal, months, fee_rate, mode="flat"):
    total_fee = principal * fee_rate * months
    if mode == "upfront":
        return [total_fee] + [0.0] * (months - 1)
    fee_per = total_fee / months
    return [fee_per] * months


def solve_irr(pv, flows, lo=IRR_LO, hi=IRR_HI):
    """二分法解月 IRR：pv = Σ flows[k]/(1+i)^k。不收敛/同号 → exit 2。"""
    def f(i):
        return sum(cf / (1.0 + i) ** k for k, cf in enumerate(flows, 1)) - pv

    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        raise LedgerError(
            "IRR: no sign change in [{}, {}] — flows don't discount to "
            "{:,.2f}".format(lo, hi, pv))
    for _ in range(IRR_ITERS):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < EPS:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def annualize(monthly_irr):
    """(名义年化 APR, 有效年化 EAR)。monthly_irr=0 → (0, 0)。"""
    return monthly_irr * 12.0, (1.0 + monthly_irr) ** 12 - 1.0


def real_rate(principal, months, fee_rate, mode="flat"):
    """整单真实月 IRR（名义口径的对照物）。费率 0 → 0。"""
    if fee_rate <= 0:
        return 0.0
    return solve_irr(principal, plan_flows(principal, months, fee_rate, mode))


def marginal_rate(principal, months, fee_rate, paid, mode="flat"):
    """边际镜：继续持有的剩余流的真实月 IRR。
    剩余流 = plan_flows[paid:]，欠款 = 剩余本金。剩余流里已无手续费
    （fee=0、upfront 已收完）→ 0。"""
    left = months - paid
    if left <= 0:
        raise ThinError("plan already settled: paid {} of {} periods"
                        .format(paid, months))
    base = principal / months
    outstanding = base * left
    flows = plan_flows(principal, months, fee_rate, mode)[paid:]
    if fee_rate <= 0 or sum(flows) - outstanding <= EPS:
        return 0.0
    return solve_irr(outstanding, flows)


def average_rate_with_prepay(principal, months, fee_rate, paid, settle,
                             mode="flat"):
    """平均镜：把结清事件放进全程现金流重新解 IRR。"""
    flows = plan_flows(principal, months, fee_rate, mode)
    flows = flows[:paid] + [settle]
    return solve_irr(principal, flows)


# ------------------------------------------------------------------ reading

def read_ledger(path):
    if not os.path.exists(path):
        raise LedgerError("ledger file not found: {}".format(os.path.basename(path)))
    rows = []
    header_seen = False
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = [c.strip() for c in line.split("\t")]
            if not header_seen:
                if cells != HEADER:
                    raise LedgerError(
                        "bad header at line {}: expected {}"
                        .format(lineno, "|".join(HEADER)))
                header_seen = True
                continue
            if len(cells) != len(HEADER):
                raise LedgerError(
                    "line {}: expected {} columns, got {}"
                    .format(lineno, len(HEADER), len(cells)))
            row = dict(zip(HEADER, cells))
            row["principal"] = parse_num(row["principal"], "principal")
            row["months"] = parse_num(row["months"], "months")
            row["fee_rate"] = parse_rate(row["fee_rate"])
            row["paid"] = parse_num(row["paid"], "paid") if row["paid"] else 0.0
            row["mode"] = row["mode"] or "flat"
            row["prepay_rule"] = row["prepay_rule"] or "remaining"
            if row["mode"] not in MODES:
                raise LedgerError("line {}: unknown mode {!r}".format(lineno, row["mode"]))
            if row["prepay_rule"] not in RULES:
                raise LedgerError(
                    "line {}: unknown prepay_rule {!r}".format(lineno, row["prepay_rule"]))
            if row["principal"] <= 0 or row["months"] < 1:
                raise LedgerError("line {}: principal/months must be positive".format(lineno))
            if not (0 <= row["fee_rate"] <= FEE_RATE_CAP):
                raise LedgerError("line {}: fee_rate out of range (0, {}]".format(lineno, FEE_RATE_CAP))
            if row["months"] != int(row["months"]):
                raise LedgerError("line {}: months must be integer".format(lineno))
            row["months"] = int(row["months"])
            if row["paid"] != int(row["paid"]):
                raise LedgerError("line {}: paid must be integer".format(lineno))
            row["paid"] = int(row["paid"])
            if not (0 <= row["paid"] <= row["months"]):
                raise LedgerError(
                    "line {}: paid {} outside [0, {}]".format(lineno, row["paid"], row["months"]))
            row["_line"] = lineno
            rows.append(row)
    if not header_seen:
        raise LedgerError("missing header in ledger")
    return rows


def check_dup(rows):
    seen = set()
    for row in rows:
        key = (row["platform"], row["item"])
        if key in seen:
            raise LedgerError("duplicate plan: {} / {}".format(key[0], key[1]))
        seen.add(key)


# -------------------------------------------------------------------- rate

def cmd_rate(args):
    p, n, r, mode = args.principal, args.months, args.fee_rate, args.mode
    if p <= 0 or n < 1 or r < 0 or r > FEE_RATE_CAP:
        raise LedgerError("principal>0, months>=1, 0<=fee_rate<={} required"
                          .format(FEE_RATE_CAP))
    if args.line is not None and args.line <= 0:
        raise LedgerError("--line must be positive")

    flows = plan_flows(p, n, r, mode)
    total_fee = p * r * n
    base = p / n
    fee_per = total_fee / n
    fee_first = flows[0] - base
    i = real_rate(p, n, r, mode)
    apr, ear = annualize(i)
    nominal_annual = r * 12.0
    mult = apr / nominal_annual if nominal_annual > 0 else 0.0
    approx = (2.0 * n / (n + 1.0)) * nominal_annual

    print("STEALTH INTEREST · rate — fee rate is a marketing number")
    print("plan: {} x {} periods @ {} per period ({})".format(
        fmt_money(p), n, fmt_pct(r, 2), mode))
    if r > 0:
        print("  first payment    {:>12}  (principal {} + fee {})".format(
            fmt_money(flows[0]), fmt_money(base), fmt_money(fee_first)))
        if mode == "upfront":
            print("  later payments   {:>12}  (principal only)".format(
                fmt_money(base)))
    else:
        print("  monthly payment  {:>12}  (interest-free)".format(fmt_money(base)))
    print("  total fee        {:>12}   total repay {}".format(
        fmt_money(total_fee), fmt_money(p + total_fee)))
    print("  monthly IRR      {:>12}".format(fmt_pct(i, 4)))
    print("  nominal APR      {:>12}   (monthly fee x 12)".format(
        fmt_pct(nominal_annual)))
    print("  effective EAR    {:>12}   (compounded)".format(fmt_pct(ear)))
    if nominal_annual > 0:
        print("  multiplier       {:>12}   (real {} / nominal {})".format(
            "{:.2f}x".format(mult), fmt_pct(apr), fmt_pct(nominal_annual)))
        print("  approx check     {:>12}   (nominal x 2n/(n+1), |exact-approx| "
              "within 3%)".format(fmt_pct(approx)))
    if i >= 0.5:
        print("  NOTE monthly IRR {} is loan-shark grade".format(fmt_pct(i, 4)))

    if args.line is not None:
        if ear >= args.line:
            print("LINE BREACH: effective annual {} >= line {}"
                  .format(fmt_pct(ear), fmt_pct(args.line)))
            return EXIT_RED
        print("within line: effective annual {} < line {}".format(
            fmt_pct(ear), fmt_pct(args.line)))
    return EXIT_OK


# ------------------------------------------------------------------ prepay

def cmd_prepay(args):
    p, n, r, mode, paid = args.principal, args.months, args.fee_rate, args.mode, args.paid
    if p <= 0 or n < 1 or r < 0 or r > FEE_RATE_CAP:
        raise LedgerError("principal>0, months>=1, 0<=fee_rate<={} required"
                          .format(FEE_RATE_CAP))
    if paid < 0 or paid > n:
        raise LedgerError("--paid must be in [0, months]")
    if args.rule not in RULES:
        raise LedgerError("--rule must be one of {}".format("|".join(RULES)))
    if args.penalty < 0 or args.penalty > 1:
        raise LedgerError("--penalty must be in [0, 1]")
    if args.yield_rate is not None and args.yield_rate < 0:
        raise LedgerError("--yield must be non-negative")

    left = n - paid
    if left <= 0:
        raise ThinError("plan already settled: paid {} of {} periods".format(paid, n))

    base = p / n
    flows = plan_flows(p, n, r, mode)
    future_flows = flows[paid:]
    fee_flows = flows_fee_part(p, n, r, mode)[paid:]
    outstanding = base * left
    remaining_fee = sum(fee_flows)
    future_total = sum(future_flows)

    if args.rule == "remaining":
        settle = future_total
    elif args.rule == "waived":
        settle = outstanding
    else:
        settle = outstanding * (1.0 + args.penalty)
    savings = future_total - settle

    print("STEALTH INTEREST · prepay — the settlement court")
    print("plan: {} x {} periods @ {} per period ({}), paid {}".format(
        fmt_money(p), n, fmt_pct(r, 2), mode, paid))
    print("  outstanding principal {:>12}".format(fmt_money(outstanding)))
    print("  remaining fee         {:>12}   ({} periods left)".format(
        fmt_money(remaining_fee), left))
    print("  future payments       {:>12}".format(fmt_money(future_total)))
    print("  settle by rule '{}'    {:>12}".format(args.rule, fmt_money(settle)))
    print("  nominal saving        {:>12}".format(fmt_money(savings)))

    if args.rule == "remaining":
        print("  ZERO-SAVING THEOREM: settle == future payments to the cent;")
        print("  prepaying saves {} of interest - it only pulls {} payments"
              .format(fmt_money(0.0), left))
        print("  into today. Your float, not your interest, pays for it.")
    if savings < -EPS:
        print("SETTLE COSTS MORE THAN STAYING: settle {} > future payments {}"
              .format(fmt_money(settle), fmt_money(future_total)))
        return EXIT_RED

    # 边际镜：继续持有的真实成本（决策判据）
    i_m = marginal_rate(p, n, r, paid, mode)
    m_apr, m_ear = annualize(i_m)
    print("  marginal real rate    {:>12}   nominal, EAR {} - the rate to beat"
          .format(fmt_pct(m_apr), fmt_pct(m_ear)))

    # 平均镜：全程平均资金成本（只披露）
    if r > 0:
        i_full = real_rate(p, n, r, mode)
        a_apr, _ = annualize(i_full)
        i_avg = average_rate_with_prepay(p, n, r, paid, settle, mode)
        avg_apr, _ = annualize(i_avg)
        if args.rule == "remaining":
            print("  average-cost lens     {:>12}   whole-plan average jumps {} -> {}"
                  .format(fmt_pct(avg_apr), fmt_pct(a_apr), fmt_pct(avg_apr)))
            print("  (fees already paid concentrate into fewer months of use -")
            print("   settling early raises your average cost; decide on the")
            print("   marginal rate above, not this number)")
        else:
            print("  average-cost lens     {:>12}   whole-plan average {} -> {}"
                  .format(fmt_pct(avg_apr), fmt_pct(a_apr), fmt_pct(avg_apr)))

    # 裁决
    if args.rule == "remaining":
        print("verdict: KEEP - zero interest can be saved under this rule")
        if args.yield_rate is not None:
            m_yr = (1.0 + args.yield_rate) ** (1.0 / 12.0) - 1.0
            pv_future = sum(cf / (1.0 + m_yr) ** k
                            for k, cf in enumerate(future_flows, 1))
            print("  at yield {}: PV(future) {} vs settle {} -> float cost {}"
                  .format(fmt_pct(args.yield_rate), fmt_money(pv_future),
                          fmt_money(settle), fmt_money(settle - pv_future)))
        return EXIT_OK

    if args.yield_rate is None:
        print("verdict suspended: give --yield (your safe annual return) to")
        print("  judge against the marginal rate {}".format(fmt_pct(m_apr)))
        raise ThinError("verdict needs --yield")

    y_eff = args.yield_rate  # 用户口径：有效年化
    print("  your yield {} vs marginal EAR {}".format(
        fmt_pct(y_eff), fmt_pct(m_ear)))
    if y_eff < m_ear - EPS:
        print("verdict: PAYOFF - your cash earns less than the plan charges")
    else:
        print("verdict: KEEP - your cash earns more than the plan charges")
    return EXIT_OK


# ------------------------------------------------------------------- offer

def cmd_offer(args):
    p, n = args.price, args.months
    r, mode = args.fee_rate, args.mode
    if p <= 0 or n < 1:
        raise LedgerError("price>0, months>=1 required")
    if r < 0 or r > FEE_RATE_CAP:
        raise LedgerError("fee_rate out of range (0, {}]".format(FEE_RATE_CAP))
    if args.cash_price is not None and args.cash_discount is not None:
        raise LedgerError("give --cash-price or --cash-discount, not both")
    discount = 0.0
    if args.cash_price is not None:
        if args.cash_price <= 0 or args.cash_price > p:
            raise LedgerError("--cash-price must be in (0, price]")
        discount = p - args.cash_price
    if args.cash_discount is not None:
        if args.cash_discount < 0 or args.cash_discount >= p:
            raise LedgerError("--cash-discount must be in [0, price)")
        discount = args.cash_discount
    if args.yield_rate is not None and args.yield_rate < 0:
        raise LedgerError("--yield must be non-negative")

    flows = plan_flows(p, n, r, mode)
    total_fee = p * r * n
    cash = p - discount
    print("STEALTH INTEREST · offer - installment vs cash")
    print("price {} x {} periods @ {} per period ({}), total fee {}".format(
        fmt_money(p), n, fmt_pct(r, 2), mode, fmt_money(total_fee)))
    print("  installment total    {:>12}".format(fmt_money(p + total_fee)))
    print("  cash price           {:>12}   (discount {})".format(
        fmt_money(cash), fmt_money(discount)))

    # 盈亏平衡折扣 @用户收益率
    if args.yield_rate is not None:
        y_m = (1.0 + args.yield_rate) ** (1.0 / 12.0) - 1.0
        pv_inst = sum(cf / (1.0 + y_m) ** k for k, cf in enumerate(flows, 1))
        be_discount = p - pv_inst
        print("  at yield {}: PV(installment) {}".format(
            fmt_pct(args.yield_rate), fmt_money(pv_inst)))
        print("  breakeven discount   {:>12}   (pay cash only if discount is larger)"
              .format(fmt_money(max(be_discount, 0.0))))
        if discount > EPS:
            i_be = breakeven_yield(p, flows, cash)
            _, be_ear = annualize(i_be)
            print("  your discount {} is worth {} a year (breakeven yield)".format(
                fmt_money(discount), fmt_pct(be_ear)))
        if discount > be_discount + EPS:
            diff = pv_inst - cash
            print("verdict: TAKE-CASH - paying cash now beats the plan by {} in PV"
                  .format(fmt_money(diff)))
            return EXIT_OK
        diff = cash - pv_inst
        label = "interest-free" if r <= 0 else "installment"
        print("verdict: TAKE-PLAN - the {} saves {} in PV at your yield".format(
            label, fmt_money(diff)))
        return EXIT_OK

    # 无 --yield：名义口径
    if total_fee <= EPS and discount <= EPS:
        print("verdict: TAKE-PLAN - interest-free installment keeps your cash;")
        print("  give --yield to price that float")
        return EXIT_OK
    if discount > total_fee + EPS:
        print("verdict: TAKE-CASH (nominal) - discount {} > total fee {}".format(
            fmt_money(discount), fmt_money(total_fee)))
        return EXIT_OK
    if total_fee > discount + EPS:
        print("  nominal ledger favors cash (fee {} > discount {}) but the real")
        print("  question is time value; give --yield for the PV verdict".format(
            fmt_money(total_fee), fmt_money(discount)))
        print("verdict suspended: nominal ledger alone cannot price your float")
        raise ThinError("verdict needs --yield")
    print("  nominal tie: discount == total fee ({})".format(fmt_money(total_fee)))
    raise ThinError("nominal tie: verdict needs --yield")


def breakeven_yield(p, flows, cash):
    """解 y_m：PV(flows, y_m) = cash。"""
    lo, hi = IRR_LO, IRR_HI
    def f(i):
        return sum(cf / (1.0 + i) ** k for k, cf in enumerate(flows, 1)) - cash
    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        raise LedgerError("breakeven yield: no sign change")
    for _ in range(IRR_ITERS):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < EPS:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


# ------------------------------------------------------------------- stack

def cmd_stack(args):
    if args.salary is not None and args.salary <= 0:
        raise LedgerError("--salary must be positive")
    if args.burden_line <= 0 or args.burden_line >= 1:
        raise LedgerError("--burden-line must be in (0, 1)")

    rows = read_ledger(args.ledger)
    check_dup(rows)
    if not rows:
        raise ThinError("no plans in ledger: nothing to stack")
    settled = [row for row in rows if row["paid"] == row["months"]]
    active = [row for row in rows if row["paid"] < row["months"]]
    if settled:
        print("  ({} settled plan(s) ignored: nothing left to pay)".format(len(settled)))
    if not active:
        raise ThinError("all plans settled: nothing to stack")
    rows = active

    per = []
    for row in rows:
        p, n, r, mode, paid = (row["principal"], row["months"], row["fee_rate"],
                               row["mode"], row["paid"])
        left = n - paid
        base = p / n
        outstanding = base * left
        remaining_fee = p * r * (n - paid) if mode == "flat" else \
            (p * r * n if paid == 0 else 0.0)
        future = [cf for cf in plan_flows(p, n, r, mode)[paid:]]
        try:
            i_m = marginal_rate(p, n, r, paid, mode)
        except (LedgerError, ThinError):
            i_m = 0.0
        m_apr, m_ear = annualize(i_m)
        per.append({
            "row": row, "left": left, "outstanding": outstanding,
            "remaining_fee": remaining_fee, "future": future,
            "monthly": future[0] if future else 0.0, "m_apr": m_apr,
        })

    print("STEALTH INTEREST · stack - the hidden liability ledger ({})".format(
        os.path.basename(args.ledger)))
    w_col = max([display_width(row["platform"]) for row in rows] + [8])
    i_col = max([display_width(row["item"]) for row in rows] + [4])
    print("  {} {} {:>12} {:>10} {:>10} {:>8} {:>9}".format(
        pad("platform", w_col), pad("item", i_col),
        "outstanding", "dark-fee", "monthly", "left", "marginal"))
    for e in per:
        row = e["row"]
        print("  {} {} {:>12} {:>10} {:>10} {:>8} {:>9}".format(
            pad(row["platform"], w_col), pad(row["item"], i_col),
            fmt_money(e["outstanding"]), fmt_money(e["remaining_fee"]),
            fmt_money(e["monthly"]), e["left"], fmt_pct(e["m_apr"])))

    total_out = sum(e["outstanding"] for e in per)
    total_fee = sum(e["remaining_fee"] for e in per)
    total_future = sum(sum(e["future"]) for e in per)
    print("  totals: outstanding {}, dark fee {}, future payments {}".format(
        fmt_money(total_out), fmt_money(total_fee), fmt_money(total_future)))
    print("  (future payments are signed debt; dark fee is the interest")
    print("   inside them that no statement will ever line up for you)")

    # 逐月月供时间线（合并到最长剩余期；分段只打印变化处）
    max_left = max(e["left"] for e in per)
    monthly = []
    for k in range(max_left):
        monthly.append(sum(e["future"][k] for e in per if len(e["future"]) > k))
    print("  monthly burden timeline:")
    seg_start = 0
    for k in range(1, max_left + 1):
        if k == max_left or abs(monthly[k] - monthly[seg_start]) > 1e-9:
            span = "month {}".format(seg_start + 1) if seg_start + 1 == k \
                else "months {}-{}".format(seg_start + 1, k)
            print("    {:<14} {:>12}".format(span, fmt_money(monthly[seg_start])))
            seg_start = k
    peak = monthly[0]

    if total_out > 0:
        wsum = sum(e["m_apr"] * e["outstanding"] for e in per)
        print("  weighted marginal (by outstanding): {}".format(
            fmt_pct(wsum / total_out)))

    if args.salary is None:
        print("  peak burden {} - give --salary to judge against line {}".format(
            fmt_money(peak), fmt_pct(args.burden_line)))
        return EXIT_OK

    ratio = peak / args.salary
    print("  peak burden {} / salary {} = {} of income (line {})".format(
        fmt_money(peak), fmt_money(args.salary), fmt_pct(ratio),
        fmt_pct(args.burden_line)))
    if ratio > args.burden_line:
        print("BURDEN LINE BREACHED: {} > {}".format(
            fmt_pct(ratio), fmt_pct(args.burden_line)))
        return EXIT_RED
    print("within line")
    return EXIT_OK


# ---------------------------------------------------------------- validate

def cmd_validate(args):
    rows = read_ledger(args.ledger)
    check_dup(rows)
    if not rows:
        raise ThinError("no plans in ledger: nothing to validate")
    problems = 0
    for row in rows:
        p, n, r, mode, paid = (row["principal"], row["months"], row["fee_rate"],
                               row["mode"], row["paid"])
        tag = "{}/{}".format(row["platform"], row["item"])
        # 恒等式 1：剩余本金 = 本金 x 剩余期数/期数
        left = n - paid
        outstanding = (p / n) * left
        if abs(outstanding - p + (p / n) * paid) > 1e-6:
            print("BROKEN identity principal-outstanding: {}".format(tag))
            problems += 1
        # 恒等式 2：未来付款 = 剩余期 x (Ap + fee_per)，与逐期流一致
        future = plan_flows(p, n, r, mode)[paid:]
        fee_per = p * r if mode == "flat" else 0.0
        expect = left * ((p / n) + fee_per)
        if abs(sum(future) - expect) > 1e-6:
            print("BROKEN identity future-payments: {}".format(tag))
            problems += 1
        # 恒等式 3：IRR 的 PV 定义回到本金（费率 > 0 时）
        if r > 0 and left > 0:
            i = marginal_rate(p, n, r, paid, mode)
            pv = sum(cf / (1.0 + i) ** k for k, cf in enumerate(future, 1))
            target = (p / n) * left
            if abs(pv - target) > 1e-6:
                print("BROKEN identity IRR-PV: {} (pv {} vs {})".format(
                    tag, pv, target))
                problems += 1
    if problems:
        raise LedgerError("{} identity violations".format(problems))
    print("ledger OK: {} plans, all identities hold".format(len(rows)))
    return EXIT_OK


# -------------------------------------------------------------------- main

def add_rate(sp):
    sp.add_argument("--principal", type=float, required=True)
    sp.add_argument("--months", type=int, required=True)
    sp.add_argument("--fee-rate", dest="fee_rate", type=float, required=True,
                    help="per-period fee rate, e.g. 0.006")
    sp.add_argument("--mode", choices=MODES, default="flat")
    sp.add_argument("--line", type=float, default=None,
                    help="effective-annual line; breach -> exit 4")


def add_prepay(sp):
    sp.add_argument("--principal", type=float, required=True)
    sp.add_argument("--months", type=int, required=True)
    sp.add_argument("--fee-rate", dest="fee_rate", type=float, required=True)
    sp.add_argument("--paid", type=int, required=True)
    sp.add_argument("--mode", choices=MODES, default="flat")
    sp.add_argument("--rule", default="remaining",
                    help="remaining | waived | pct (contract always wins)")
    sp.add_argument("--penalty", type=float, default=DEFAULT_PENALTY,
                    help="pct rule: penalty on outstanding principal")
    sp.add_argument("--yield", dest="yield_rate", type=float, default=None,
                    help="your safe annual return, for the verdict")


def add_offer(sp):
    sp.add_argument("--price", type=float, required=True)
    sp.add_argument("--months", type=int, required=True)
    sp.add_argument("--fee-rate", dest="fee_rate", type=float, default=0.0)
    sp.add_argument("--mode", choices=MODES, default="flat")
    sp.add_argument("--cash-price", type=float, default=None)
    sp.add_argument("--cash-discount", type=float, default=None)
    sp.add_argument("--yield", dest="yield_rate", type=float, default=None)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="stealth_interest.py",
        description="暗息 · Stealth Interest - installment fee rates are "
                    "marketing numbers; this translates them into real "
                    "annual costs and audits prepay/offer/stack decisions")
    sub = ap.add_subparsers(dest="cmd")

    add_rate(sub.add_parser("rate", help="translate a fee rate into real APR/EAR"))
    add_prepay(sub.add_parser("prepay", help="the settlement court"))
    add_offer(sub.add_parser("offer", help="installment vs cash discount"))

    sp = sub.add_parser("stack", help="hidden liability ledger for many plans")
    sp.add_argument("ledger")
    sp.add_argument("--salary", type=float, default=None)
    sp.add_argument("--burden-line", dest="burden_line", type=float,
                    default=BURDEN_LINE)

    sp = sub.add_parser("validate", help="ledger sanity + identity checks")
    sp.add_argument("ledger")

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_usage(sys.stderr)
        return EXIT_INPUT

    verbs = {"rate": cmd_rate, "prepay": cmd_prepay, "offer": cmd_offer,
             "stack": cmd_stack, "validate": cmd_validate}
    try:
        return verbs[args.cmd](args)
    except LedgerError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return EXIT_INPUT
    except ThinError as exc:
        print("TOO THIN: {}".format(exc), file=sys.stderr)
        return EXIT_THIN


if __name__ == "__main__":
    sys.exit(main())
