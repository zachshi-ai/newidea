#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""哑税 · Mute Levy — 个税预扣对账账本 (zero-dependency CLI).

个税是唯一一笔你每月都在缴、却几乎没有人核对过的钱：预扣制下每月代
扣的是"当时的估算"，错了没有任何人通知你；专项附加扣除的默认状态是
空白——你不申报它就不生效，每一项空白都在按你的边际税率按月征一笔
哑巴亏。汇算清缴（次年 3 月 1 日–6 月 30 日）是税法留给个人的唯一一
次总对账窗口，窗口一关，多缴的税就永远留在了国库里。

本件把一年的工资条抄成可手编的账本（payslibs.tsv + claims.tsv +
eligibles.tsv），开出五本账：
  report   逐月累计预扣法重放——每个雇主"都扣对了"，加总却注定有差
  settle   年度汇算模拟——应退 / 应补（BALANCE-DUE 灯）
  gap      哑税审计——有资格却没申报的扣除，每一项按月计价
  bonus    年终奖二选一——单独计税 vs 并入综合（36000 悬崖）
  validate 恒等式体检

诚实条款：只建模"单一性质工资薪金 + 标准申报"；劳务报酬、稿酬、股
权激励、经营所得、汇算之外的补缴不进。全件无墙钟——账本即全年事实，
同一本账任何机器任何一天跑出的结果逐字节一致。它不是税务建议，申报
不申报、退不退税，永远是人的决定。
"""

import argparse
import os
import re
import sys

TOL = 1e-9          # 恒等式浮点容差
CENT = 0.011        # 分位容差（重算 vs 账本实缴；错一分钱以上才算对不上）

EXEMPTION_MONTHLY = 5000.00   # 减除费用：5000/月

# 综合所得年度税率表（= 工资薪金累计预扣率表，按累计应纳税所得额）
ANNUAL_BRACKETS = [
    (36000.00, 0.03, 0.00),
    (144000.00, 0.10, 2520.00),
    (300000.00, 0.20, 16920.00),
    (420000.00, 0.25, 31920.00),
    (660000.00, 0.30, 52920.00),
    (960000.00, 0.35, 85920.00),
    (float("inf"), 0.45, 181920.00),
]

# 按月换算后的月度税率表——仅用于年终奖单独计税（奖金÷12 找档）
MONTHLY_BRACKETS = [
    (3000.00, 0.03, 0.00),
    (12000.00, 0.10, 210.00),
    (25000.00, 0.20, 1410.00),
    (35000.00, 0.25, 2660.00),
    (55000.00, 0.30, 4410.00),
    (80000.00, 0.35, 7160.00),
    (float("inf"), 0.45, 15160.00),
]

# 专项附加扣除全国统一标准先验（月扣除额）。--rent-tier 切租金档，
# 非独生赡养分摊上限 1500（--elderly-monthly 覆盖）。申报过的以账本为准。
PRIORS = {
    "housing": 1000.00,     # 房贷利息（首套，最长 240 月）
    "rent": 1500.00,        # 住房租金（直辖市/省会/计划单列档）
    "child": 2000.00,       # 子女教育（每孩）
    "infant": 2000.00,      # 3 岁以下婴幼儿照护（每孩）
    "elderly": 3000.00,     # 赡养老人（独生子女口径）
    "continuing": 400.00,   # 学历继续教育（职业资格 3600/年，请显式填月额）
}

# 别名归一：规范词必须映射到自身（否则规范拼写自身反而不识别）
ALIASES = {
    "housing": "housing", "房贷": "housing", "房贷利息": "housing",
    "mortgage": "housing",
    "rent": "rent", "租房": "rent", "住房租金": "rent",
    "child": "child", "子女": "child", "子女教育": "child",
    "infant": "infant", "婴幼儿": "infant", "婴幼儿照护": "infant",
    "elderly": "elderly", "赡养": "elderly", "赡养老人": "elderly",
    "continuing": "continuing", "继续教育": "continuing",
    "medical": "medical", "大病": "medical", "大病医疗": "medical",
}

EN_NAMES = {
    "housing": "housing loan", "rent": "rent", "child": "child edu",
    "infant": "infant care", "elderly": "elderly support",
    "continuing": "continuing edu", "medical": "major medical",
}


class LedgerError(Exception):
    """账坏：结构/算术问题，exit 2。"""


class ThinLedger(Exception):
    """薄账：统计判级拒绝，exit 3。"""


def norm_item(name):
    key = (name or "").strip()
    if key in ALIASES:
        return ALIASES[key]
    raise LedgerError("unknown claim item: %r (known: %s)"
                      % (name, ", ".join(sorted(set(ALIASES.values())))))


def r2(x):
    v = round(x + 0.0, 2)
    return 0.0 if v == 0 else v  # 归一 -0.0 与浮点尘埃


def fmt(x):
    v = x + 0.0
    if v == 0:
        v = 0.0  # 归一 -0.0
    return "{:,.2f}".format(v)


def display_width(s):
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def pad(s, width):
    s = str(s)
    return s + " " * max(0, width - display_width(s))


def read_tsv(path, required_cols, optional_cols=()):
    """读 TSV：# 注释行跳过，首条非注释行必须是表头。"""
    if not os.path.exists(path):
        raise LedgerError("ledger file not found: %s" % os.path.basename(path))
    rows = []
    header = None
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                continue
            cells = [c.strip() for c in line.split("\t")]
            if header is None:
                header = cells
                continue
            if len(cells) == 1 and cells[0] == "":
                continue
            rec = {}
            for i, col in enumerate(header):
                rec[col] = cells[i] if i < len(cells) else ""
            rows.append((lineno, rec))
    if header is None:
        raise LedgerError("%s: empty ledger (no header row)" % os.path.basename(path))
    for col in required_cols:
        if col not in header:
            raise LedgerError("%s: missing column %r (header: %s)"
                              % (os.path.basename(path), col, "|".join(header)))
    for col in optional_cols:
        if col not in header:
            for _, rec in rows:
                rec[col] = ""
    return rows


def parse_num(rec, col, path, lineno, default=None, minimum=None):
    raw = (rec.get(col) or "").strip()
    if raw == "":
        if default is None:
            raise LedgerError("%s line %d: column %r is empty" % (path, lineno, col))
        return default
    try:
        val = float(raw)
    except ValueError:
        raise LedgerError("%s line %d: %r is not a number" % (path, raw, col))
    if minimum is not None and val < minimum - TOL:
        raise LedgerError("%s line %d: %s=%s below minimum %s"
                          % (os.path.basename(path), lineno, col, raw, minimum))
    return val


YM_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_ym(s, path, lineno):
    m = YM_RE.match((s or "").strip())
    if not m:
        raise LedgerError("%s line %d: bad month %r (expect YYYY-MM)"
                          % (os.path.basename(path), lineno, s))
    y, mo = int(m.group(1)), int(m.group(2))
    if not (2000 <= y <= 2100 and 1 <= mo <= 12):
        raise LedgerError("%s line %d: month out of range: %s" % (path, lineno, s))
    return y * 12 + mo


def ym_label(code):
    mo = (code - 1) % 12 + 1
    y = (code - mo) // 12
    return "%04d-%02d" % (y, mo)


def bracket_of(amount, brackets):
    for cap, rate, quick in brackets:
        if amount <= cap + TOL:
            return rate, quick
    return brackets[-1][1], brackets[-1][2]


def tax_annual(taxable):
    if taxable <= 0:
        return 0.0
    rate, quick = bracket_of(taxable, ANNUAL_BRACKETS)
    return taxable * rate - quick


def tax_solo(bonus):
    if bonus <= 0:
        return 0.0
    rate, quick = bracket_of(bonus / 12.0, MONTHLY_BRACKETS)
    return bonus * rate - quick


class Ledger(object):
    def __init__(self, payslips_path, claims_path, eligibles_path=None,
                 rent_tier=1500.00, elderly_monthly=3000.00):
        self.payslips_path = payslips_path
        self.claims_path = claims_path
        self.eligibles_path = eligibles_path
        self.prior_overrides = {"rent": rent_tier, "elderly": elderly_monthly}
        self._load_payslips()
        self._load_claims()
        self._load_eligibles()

    # ---------------- payslips ----------------
    def _load_payslips(self):
        rows = read_tsv(self.payslips_path,
                        ["month", "employer", "gross", "social", "fund",
                         "other_exempt", "tax_paid"])
        self.salaries = []
        seen = set()
        for lineno, rec in rows:
            mcode = parse_ym(rec["month"], self.payslips_path, lineno)
            emp = (rec["employer"] or "").strip()
            if not emp:
                raise LedgerError("%s line %d: employer is empty"
                                  % (os.path.basename(self.payslips_path), lineno))
            gross = parse_num(rec, "gross", self.payslips_path, lineno, minimum=0.01)
            social = parse_num(rec, "social", self.payslips_path, lineno, minimum=0.0)
            fund = parse_num(rec, "fund", self.payslips_path, lineno, minimum=0.0)
            other = parse_num(rec, "other_exempt", self.payslips_path, lineno,
                              default=0.0, minimum=0.0)
            paid = parse_num(rec, "tax_paid", self.payslips_path, lineno, minimum=0.0)
            if social + fund + other > gross + TOL:
                raise LedgerError("%s line %d: social+fund+other %.2f exceeds gross %.2f"
                                  % (os.path.basename(self.payslips_path), lineno,
                                     social + fund + other, gross))
            key = (emp, mcode)
            if key in seen:
                raise LedgerError("%s: duplicate salary row for %s %s (split the month, do not repeat it)"
                                  % (os.path.basename(self.payslips_path), emp, ym_label(mcode)))
            seen.add(key)
            self.salaries.append({"m": mcode, "emp": emp, "gross": gross,
                                  "social": social, "fund": fund,
                                  "other": other, "paid": paid})
        if not self.salaries:
            raise LedgerError("%s: no salary rows" % os.path.basename(self.payslips_path))
        self.salaries.sort(key=lambda r: (r["m"], r["emp"]))
        years = set((r["m"] - 1) // 12 for r in self.salaries)
        if len(years) > 1:
            raise LedgerError("%s: ledger spans %d calendar years (%s..%s) -- annual reconciliation is per-year, split the ledger"
                              % (os.path.basename(self.payslips_path), len(years),
                                 ym_label(min(r["m"] for r in self.salaries)),
                                 ym_label(max(r["m"] for r in self.salaries))))
        self.year = min(years) * 12 // 12
        self.months = sorted(set(r["m"] for r in self.salaries))
        self.employers = sorted(set(r["emp"] for r in self.salaries))

    # ---------------- claims / eligibles ----------------
    def _parse_deduction_rows(self, path):
        rows = read_tsv(path, ["item", "from", "to", "monthly"])
        out = []
        for lineno, rec in rows:
            item = norm_item(rec["item"])
            start = parse_ym(rec["from"], path, lineno)
            end_raw = (rec["to"] or "").strip()
            end = parse_ym(end_raw, path, lineno) if end_raw else None
            raw_m = (rec.get("monthly") or "").strip()
            if raw_m == "":
                monthly = self.prior_overrides.get(item, PRIORS.get(item))
                if monthly is None:
                    raise LedgerError("%s line %d: item %r has no monthly amount and no prior -- fill the column"
                                      % (os.path.basename(path), lineno, item))
            else:
                monthly = parse_num(rec, "monthly", path, lineno, minimum=0.0)
            note = (rec.get("note") or "").strip()
            out.append({"item": item, "start": start, "end": end,
                        "monthly": monthly, "note": note,
                        "line": lineno, "path": os.path.basename(path)})
        return out

    def _load_claims(self):
        self.claims = self._parse_deduction_rows(self.claims_path)

    def _load_eligibles(self):
        self.eligibles = []
        if self.eligibles_path:
            self.eligibles = self._parse_deduction_rows(self.eligibles_path)

    # ---------------- derived ----------------
    def coverage_end(self):
        return max(self.months)

    def row_months(self, row):
        end = row["end"] if row["end"] is not None else self.coverage_end()
        if end < row["start"]:
            raise LedgerError("%s line %d: item %s ends (%s) before it starts (%s)"
                              % (row["path"], row["line"], row["item"],
                                 ym_label(end), ym_label(row["start"])))
        return set(range(row["start"], end + 1))

    def claims_by_month(self, extra=None):
        """返回 {month_code: monthly_deduction}（限定账本覆盖月）。"""
        by_month = {}
        for row in self.claims:
            for m in self.row_months(row):
                if m in self.months:
                    by_month[m] = by_month.get(m, 0.0) + row["monthly"]
        if extra:
            for m, amount in extra.items():
                if m in self.months:
                    by_month[m] = by_month.get(m, 0.0) + amount
        return by_month

    def claim_coverage_by_item(self):
        cov = {}
        for row in self.claims:
            cov.setdefault(row["item"], set()).update(self.row_months(row))
        return cov

    def totals(self, claims_by_month):
        t = {
            "gross": sum(r["gross"] for r in self.salaries),
            "social": sum(r["social"] for r in self.salaries),
            "fund": sum(r["fund"] for r in self.salaries),
            "other": sum(r["other"] for r in self.salaries),
            "paid": sum(r["paid"] for r in self.salaries),
        }
        t["insurance"] = t["social"] + t["fund"] + t["other"]
        t["exemption"] = EXEMPTION_MONTHLY * len(self.months)
        t["claims"] = sum(claims_by_month.get(m, 0.0) for m in self.months)
        t["taxable"] = (t["gross"] - t["exemption"] - t["insurance"]
                        - t["claims"])
        return t

    def replay(self, claims_by_month):
        """按雇主分组重放累计预扣法。返回逐月行 + 雇主小结。"""
        rows = []
        for emp in self.employers:
            emp_rows = [r for r in self.salaries if r["emp"] == emp]
            k = 0            # 任职月序（减除费用按任职月数）
            cum_taxable = 0.0
            cum_due = 0.0    # 累计应预扣（可为负，负数挂账后续回补）
            for r in emp_rows:
                k += 1
                deduction = claims_by_month.get(r["m"], 0.0)
                cum_taxable += r["gross"] - EXEMPTION_MONTHLY - r["social"] \
                    - r["fund"] - r["other"] - deduction
                rate, quick = bracket_of(max(cum_taxable, 0.0), ANNUAL_BRACKETS)
                cum_due_new = max(cum_taxable, 0.0) * rate - quick
                if cum_taxable <= 0:
                    cum_due_new = 0.0
                due_this = max(0.0, cum_due_new - cum_due)
                cum_due = cum_due_new
                diff = r["paid"] - due_this
                rows.append({
                    "m": r["m"], "emp": emp, "cum": cum_taxable,
                    "rate": rate, "due": due_this, "paid": r["paid"],
                    "diff": diff,
                })
        return rows


def month_span_codes(codes):
    return "%s..%s (%d)" % (ym_label(min(codes))[5:], ym_label(max(codes))[5:],
                            len(codes))


# --------------------------- commands ---------------------------

def cmd_report(led, args):
    cbm = led.claims_by_month()
    rows = led.replay(cbm)
    tot = led.totals(cbm)
    out = []
    out.append("=== Mute Levy · Withholding Reconciliation %d ===" % led.year)
    out.append("ledger %s: %d salary rows, %d employer(s), %d months (%s..%s)"
               % (os.path.basename(led.payslips_path), len(led.salaries),
                  len(led.employers), len(led.months),
                  ym_label(led.months[0]), ym_label(led.months[-1])))
    out.append("claims %s: %d item(s), %d covered month-amounts"
               % (os.path.basename(led.claims_path), len(led.claims), len(cbm)))
    out.append("")
    out.append("-- monthly replay (cumulative withholding method) --")
    hdr = ("month", "employer", "cum-taxable", "bracket", "due-this",
           "paid-this", "diff")
    widths = [5, 10, 12, 6, 9, 9, 8]
    out.append("  ".join(pad(h, w) for h, w in zip(hdr, widths)))
    mism = 0
    for r in rows:
        flag = "*" if abs(r["diff"]) > CENT else " "
        if flag == "*":
            mism += 1
        out.append("  ".join([
            pad(ym_label(r["m"])[5:], 5),
            pad(r["emp"], 10),
            pad(fmt(r["cum"]), 12),
            pad("%d%%" % round(r["rate"] * 100), 6),
            pad(fmt(r["due"]), 9),
            pad(fmt(r["paid"]), 9),
            pad("%s%s" % (fmt(r["diff"]), flag), 8),
        ]))
    out.append("")
    for emp in led.employers:
        er = [r for r in rows if r["emp"] == emp]
        out.append("emp %s: withheld %s, paid %s"
                   % (pad(emp, 10), fmt(sum(r["due"] for r in er)),
                      fmt(sum(r["paid"] for r in er))))
    due_sum = sum(r["due"] for r in rows)
    paid_sum = sum(r["paid"] for r in rows)
    out.append("year total: withheld %s, paid %s, diff %s"
               % (fmt(due_sum), fmt(paid_sum), fmt(paid_sum - due_sum)))
    if mism:
        out.append("HIDDEN-ITEM: %d month(s) paid != replayed due -- usually a "
                   "bonus inside the salary line or an undisclosed deduction; "
                   "the ledger only sees what you write into it" % mism)
    out.append("")
    if abs(paid_sum - due_sum) <= CENT and len(led.employers) > 1:
        out.append("every employer withheld correctly -- the gap is structural, "
                   "not clerical: two cumulative ladders both starting from zero "
                   "do not add up to one year.")
    print("\n".join(out))
    return 0


def settle_of(led, extra_claims=None):
    cbm = led.claims_by_month(extra=extra_claims)
    tot = led.totals(cbm)
    annual = r2(tax_annual(tot["taxable"]))
    due = r2(annual - tot["paid"])
    return {"tot": tot, "annual": annual, "due": due, "cbm": cbm}


def render_settle(led, st, title):
    tot = st["tot"]
    rate, quick = bracket_of(max(tot["taxable"], 0.0), ANNUAL_BRACKETS)
    out = []
    out.append(title)
    out.append("coverage %d/12 months" % len(led.months))
    out.append("gross %s - exemption %s (%d x %s) - social+fund+other %s"
               % (fmt(tot["gross"]), fmt(tot["exemption"]), len(led.months),
                  fmt(EXEMPTION_MONTHLY), fmt(tot["insurance"])))
    out.append("     - special additional claims %s = taxable income %s"
               % (fmt(tot["claims"]), fmt(tot["taxable"])))
    out.append("bracket %d%% (quick deduction %s) -> annual tax %s"
               % (round(rate * 100), fmt(quick), fmt(st["annual"])))
    out.append("prepaid through withholding: %s" % fmt(tot["paid"]))
    if st["due"] > TOL:
        out.append("BALANCE-DUE %s -- the withholding was an estimate; the "
                   "reconciliation is the audit" % fmt(st["due"]))
    elif st["due"] < -TOL:
        out.append("REFUND %s -- money parked at the treasury with your name "
                   "on it; claim it inside the window" % fmt(-st["due"]))
    else:
        out.append("SETTLED: prepaid == annual tax, to the cent")
    out.append("window: Mar 1 - Jun 30 of the following year; after it closes "
               "a due stays due (with late-payment surcharge), a refund stays "
               "unclaimed.")
    return out


def cmd_settle(led, args):
    st = settle_of(led)
    out = []
    out.append("=== Mute Levy · Annual Reconciliation (settle) %d ===" % led.year)
    out.extend(render_settle(led, st, "-- as booked (claims you actually filed) --"))
    print("\n".join(out))
    if st["due"] > args.due_line + CENT / 2:
        return 4
    return 0


def cmd_gap(led, args):
    if not led.eligibles:
        raise ThinLedger("no eligibles.tsv (--eligibles): without a list of "
                         "what you QUALIFY for, silence cannot be priced -- "
                         "the ledger will not invent eligibility")
    cov = led.claim_coverage_by_item()
    gaps = []  # (row, gap_months)
    for row in led.eligibles:
        allm = set(m for m in led.row_months(row) if m in led.months)
        claimed = set(m for m in cov.get(row["item"], set()) if m in led.months)
        miss = sorted(allm - claimed)
        if miss:
            gaps.append((row, miss))
    before = settle_of(led)
    extra = {}
    for row, miss in gaps:
        for m in miss:
            extra[m] = extra.get(m, 0.0) + row["monthly"]
    after = settle_of(led, extra_claims=extra)

    out = []
    out.append("=== Mute Levy · Unclaimed Deduction Audit (gap) %d ===" % led.year)
    out.append("eligible items %d, claimed-overlapped %d, with silent months: %d"
               % (len(led.eligibles),
                  len(led.eligibles) - len(gaps), len(gaps)))
    if not gaps:
        out.append("every eligible month is claimed -- nothing mute this year")
        print("\n".join(out))
        return 0
    rate, _ = bracket_of(max(before["tot"]["taxable"], 0.0), ANNUAL_BRACKETS)
    out.append("")
    out.append("-- silent months, priced --")
    w = (18, 14, 11, 12)
    out.append("  ".join(pad(h, x) for h, x in
                         zip(("item", "silent months", "deduction",
                              "approx-tax"), w)))
    total_ded = 0.0
    total_tax = 0.0
    for row, miss in gaps:
        ded = row["monthly"] * len(miss)
        total_ded += ded
        total_tax += ded * rate
        out.append("  ".join([
            pad(EN_NAMES.get(row["item"], row["item"]), w[0]),
            pad(month_span_codes(miss), w[1]),
            pad(fmt(ded), w[2]),
            pad(fmt(ded * rate), w[3]),
        ]))
    total_tax = r2(total_tax)
    out.append("  ".join([
        pad("mute levy total", w[0]), pad("", w[1]),
        pad(fmt(total_ded), w[2]), pad(fmt(total_tax), w[3]),
    ]))
    out.append("(approx-tax at the current %d%% marginal bracket; the exact "
               "figure is the settle delta below)" % round(rate * 100))
    delta = after["due"] - before["due"]
    out.append("")
    out.extend(render_settle(led, before, "-- settle as booked --"))
    out.append("")
    out.extend(render_settle(led, after, "-- settle after refilling every gap --"))
    out.append("")
    out.append("refilling flips the bottom line by %s == mute levy exact total"
               % fmt(abs(delta)))
    if total_tax > args.mute_line + CENT / 2:
        out.append("MUTE-LIT: silent deductions cost you %s this year (line %s) "
                   "-- nobody warned you because nobody has to" % (fmt(total_tax), fmt(args.mute_line)))
    print("\n".join(out))
    if total_tax > args.mute_line + CENT / 2:
        return 4
    return 0


def cmd_bonus(led, args):
    amount = args.amount
    if amount <= 0:
        raise LedgerError("--amount must be positive")
    st = settle_of(led)
    base_taxable = st["tot"]["taxable"]
    base_tax = st["annual"]
    solo = r2(tax_solo(amount))
    solo_total = r2(base_tax + solo)
    merged_total = r2(tax_annual(base_taxable + amount))
    diff = r2(merged_total - solo_total)
    rate, quick = bracket_of(amount / 12.0, MONTHLY_BRACKETS)
    out = []
    out.append("=== Mute Levy · Bonus Bracket Choice (bonus %s) ===" % fmt(amount))
    out.append("comprehensive taxable income (from settle): %s -> annual tax %s"
               % (fmt(base_taxable), fmt(base_tax)))
    out.append("")
    out.append("solo : %s / 12 = %s -> %d%% bracket (quick %s) -> bonus tax %s"
               % (fmt(amount), fmt(amount / 12.0), round(rate * 100),
                  fmt(quick), fmt(solo)))
    out.append("       total tax %s + %s = %s"
               % (fmt(base_tax), fmt(solo), fmt(solo_total)))
    out.append("merge: %s + %s = %s -> annual tax %s (total %s)"
               % (fmt(base_taxable), fmt(amount), fmt(base_taxable + amount),
                  fmt(merged_total), fmt(merged_total)))
    out.append("")
    if diff > TOL:
        out.append("SOLO saves %s -- merging pushes the whole year across a "
                   "bracket line" % fmt(diff))
        verdict_saves = "SOLO"
    elif diff < -TOL:
        out.append("MERGE saves %s -- low comprehensive income means the solo "
                   "table taxes the bonus harder than the empty bracket does"
                   % fmt(-diff))
        verdict_saves = "MERGE"
    else:
        out.append("EVEN: both routes land on the same total to the cent")
        verdict_saves = "EVEN"
    solo_up = tax_solo(amount + 0.01)
    if solo_up - solo > TOL:
        out.append("cliff: at %s the solo tax jumps to %s (+%s) -- the monthly "
                   "table has hard edges, a 1-yuan raise can cost thousands"
                   % (fmt(amount + 0.01), fmt(solo_up), fmt(solo_up - solo)))
    out.append("solo-taxation relief currently runs through Dec 2027; the "
               "choice is yours, the cliff is not.")
    print("\n".join(out))
    return 0


def cmd_validate(led, args):
    cbm = led.claims_by_month()
    tot = led.totals(cbm)
    rows = led.replay(cbm)
    st = settle_of(led)
    out = []
    out.append("=== Mute Levy · Ledger Integrity (validate) %d ===" % led.year)
    failures = 0

    # id1: 逐月增量求和 == 聚合公式（应纳税所得额分解恒等，两条路径）
    incr = 0.0
    for emp in led.employers:
        k = 0
        for r in [x for x in led.salaries if x["emp"] == emp]:
            k += 1
            incr += (r["gross"] - EXEMPTION_MONTHLY - r["social"]
                     - r["fund"] - r["other"] - cbm.get(r["m"], 0.0))
    ok1 = abs(incr - tot["taxable"]) < 1e-6
    out.append("[%s] identity: per-employer incremental taxable == aggregate "
               "decomposition (%.6f)" % ("ok" if ok1 else "BROKEN",
                                         abs(incr - tot["taxable"])))
    failures += 0 if ok1 else 1

    # id2: settle 应补 == 年度应纳 - Σ实缴（定义恒等的复算路径）
    ok2 = abs((st["annual"] - tot["paid"]) - st["due"]) < 1e-6
    out.append("[%s] identity: reconcile due == annual tax - total prepaid"
               % ("ok" if ok2 else "BROKEN"))
    failures += 0 if ok2 else 1

    # id3: 逐月重放合计 == 全年聚合（无 MISMATCH 时两条口径应同额）
    mism = [r for r in rows if abs(r["diff"]) > CENT]
    ok3 = not mism
    out.append("[%s] replay: all %d months paid == replayed due (%d hidden-item month(s))"
               % ("ok" if ok3 else "DISCLOSED", len(rows), len(mism)))

    # id4: 月终奖悬崖钉值（内置自检，不依赖账本）
    c1 = abs(tax_solo(36000.00) - 1080.00) < 1e-6
    c2 = abs(tax_solo(36001.00) - 3390.10) < 1e-6
    ok4 = c1 and c2
    out.append("[%s] cliff: solo tax 36000->%s, 36001->%s"
               % ("ok" if ok4 else "BROKEN", fmt(tax_solo(36000.00)),
                  fmt(tax_solo(36001.00))))
    failures += 0 if ok4 else 1

    # id5: claims 覆盖月全部落在账本覆盖月内（超出部分被截断，须披露）
    clipped = 0
    for row in led.claims:
        clipped += len(set(range(row["start"], (row["end"] or max(
            row["start"], led.coverage_end())) + 1)) - set(led.months))
    out.append("[%s] claims: %d month(s) outside the ledger were clipped"
               % ("ok" if clipped == 0 else "DISCLOSED", clipped))

    out.append("")
    if failures:
        out.append("%d identity broken -- fix the ledger or the tariff table" % failures)
        print("\n".join(out))
        return 2
    out.append("all identities green")
    print("\n".join(out))
    return 0


# ----------------------------- main -----------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="mute_levy.py",
        description="哑税 · Mute Levy — 个税预扣对账账本")
    p.add_argument("--payslips", required=True, help="工资条 TSV（月/雇主/应发/社保/公积金/其他免税扣除/实缴个税）")
    p.add_argument("--claims", required=True, help="已申报的专项附加扣除 TSV")
    p.add_argument("--eligibles", default=None, help="资格清单 TSV（gap 哑税审计需要）")
    p.add_argument("--due-line", type=float, default=0.0,
                   help="settle 应补亮灯线（默认 0：任何应补都值得知道）")
    p.add_argument("--mute-line", type=float, default=500.0,
                   help="gap 哑税亮灯线，元/年（默认 500）")
    p.add_argument("--rent-tier", type=float, default=1500.0,
                   choices=[800.0, 1100.0, 1500.0],
                   help="住房租金先验档（默认 1500：直辖市/省会/计划单列）")
    p.add_argument("--elderly-monthly", type=float, default=3000.0,
                   help="赡养老人月扣除先验（非独生分摊上限 1500）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report", help="逐月累计预扣法重放对账")
    sub.add_parser("settle", help="年度汇算模拟（应退/应补）")
    sub.add_parser("gap", help="哑税审计（需 --eligibles）")
    bp = sub.add_parser("bonus", help="年终奖二选一：单独计税 vs 并入综合")
    bp.add_argument("--amount", type=float, required=True, help="年终奖金额")
    sub.add_parser("validate", help="恒等式体检")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        led = Ledger(args.payslips, args.claims, args.eligibles,
                     rent_tier=args.rent_tier,
                     elderly_monthly=args.elderly_monthly)
        if args.cmd == "report":
            return cmd_report(led, args)
        if args.cmd == "settle":
            return cmd_settle(led, args)
        if args.cmd == "gap":
            return cmd_gap(led, args)
        if args.cmd == "bonus":
            return cmd_bonus(led, args)
        if args.cmd == "validate":
            return cmd_validate(led, args)
    except ThinLedger as exc:
        print("DECLINE: %s" % exc, file=sys.stderr)
        print("(refusing to conclude on a thin/absent ledger; arithmetic "
              "screens above still stand)", file=sys.stderr)
        return 3
    except LedgerError as exc:
        print("LEDGER BROKEN: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
