#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""暗基数 · Shadow Base

工资条和社保系统是两本从没人对过的账：缴费基数决定你的养老金个人账户、
公积金和医保，但它从不出现在工资条上——你从没见过它，更没拿它对你的工资。
公司按当地下限交基数是普遍操作（省下的钱一半本来是你自己的公积金），
发现的唯一途径是自己逐月对账；而换工作那一个月的断缴，可能让攒了几年的
购房/落户资格一夜清零。官方 App 只显示流水与余额，零计算：不预警断月、
不对账基数、不倒计时资格、不模拟离职。

本件从可手编的缴纳账（社保/公积金逐月流水 + 可选工资账）开出六本账：
  - audit    基数对账：实缴基数 ÷ 工资 = 缴费水位，按下限交法的指纹；
  - compare  暗折账：低报部分 + 断缴缺席部分，逐月有主，折算成月份工资；
  - streak   连续账：断月清单、当前连续、资格倒计时（月历/严格两口径）；
  - simulate 反事实：离职空档的资格推迟、自缴过桥的口径边界；
  - report   总账；validate 恒等式体检。

零依赖（Python 3.8+ 标准库），账本自锚定：缺省 as-of = 账本末月，
--as-of 钉死；同一本账任何机器任何一天跑出的结果逐字节一致。

诚实条款：本件是计算器不是律师——比例、下限、资格月数全是参数，
政策永远赢；统筹部分是共济不是你的钱，不定价；失业月没有工资参照，
不发明暗折。

Exit codes: 0 绿 · 2 账本损坏 · 3 样本太薄/缺工资参照拒绝判级 · 4 红灯
"""

import argparse
import os
import re
import sys

EXIT_OK = 0
EXIT_LEDGER = 2
EXIT_THIN = 3
EXIT_RED = 4

THIN_MONTHS = 6          # 账本跨度 < 6 个月 → 统计判级拒绝（算术照出）
BAND_FLOOR = 0.60        # 缴费水位 < 0.6 → SHAVED 红灯
BAND_LAG = 0.90          # [0.6, 0.9) = 合法滞后带（上年月均口径），≥0.9 足额
SOCIAL_PERSONAL = 0.105  # 社保个人比例通识简化：养老 8% + 医疗 2% + 失业 0.5%
PENSION = 0.08           # 养老个人账户划入比例（统筹是共济，不定价）
FUND_PERSONAL = 0.12     # 公积金个人比例
FUND_COMPANY = 0.12      # 公积金公司比例（两半都是你的钱）
COMPANY_TOL = 0.05       # 显式公司缴额与反解值的口径披露线
EPS = 0.01

SCHEME_ALIAS = {
    "social": "social", "si": "social", "sb": "social", "社保": "social",
    "五险": "social", "社保账": "social",
    "fund": "fund", "gjj": "fund", "housing": "fund",
    "公积金": "fund", "公积金账": "fund",
}

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


class LedgerError(Exception):
    """账本损坏：exit 2"""


# ---------------------------------------------------------------- 月份算术

def ym_parse(s):
    m = MONTH_RE.match(s.strip())
    if not m:
        raise LedgerError("bad month %r (want YYYY-MM)" % s)
    y, mm = int(m.group(1)), int(m.group(2))
    if not (2000 <= y <= 2100 and 1 <= mm <= 12):
        raise LedgerError("month %r out of range" % s)
    return (y, mm)


def ym_fmt(ym):
    return "%04d-%02d" % ym


def ym_add(ym, k):
    y, m = ym
    t = y * 12 + (m - 1) + k
    return (t // 12, t % 12 + 1)


def ym_sub(a, b):
    """a - b 的月数（a 在后为正）。"""
    return (a[0] * 12 + a[1]) - (b[0] * 12 + b[1])


def ym_seq(a, b):
    """闭区间 [a, b] 的月份序列；b < a 时为空。"""
    out = []
    cur = a
    while ym_sub(b, cur) >= 0:
        out.append(cur)
        cur = ym_add(cur, 1)
    return out


# ---------------------------------------------------------------- 解析

def parse_money(s, what, where, lo, hi, allow_empty=False):
    s = s.strip()
    if s == "":
        if allow_empty:
            return None
        raise LedgerError("%s empty (%s)" % (what, where))
    try:
        v = float(s)
    except ValueError:
        raise LedgerError("%s %r not a number (%s)" % (what, s, where))
    if v < lo or v > hi:
        raise LedgerError("%s %r out of range [%s, %s] (%s)"
                          % (what, s, lo, hi, where))
    return v


def norm_scheme(s):
    key = s.strip().lower()
    if key not in SCHEME_ALIAS:
        raise LedgerError("unknown scheme %r (want social/社保 or fund/公积金)"
                          % s)
    return SCHEME_ALIAS[key]


class Row(object):
    __slots__ = ("month", "scheme", "base", "personal", "company",
                 "note", "backfill")

    def __init__(self, month, scheme, base, personal, company, note):
        self.month = month
        self.scheme = scheme
        self.base = base
        self.personal = personal
        self.company = company
        self.note = note
        self.backfill = "补缴" in note


def load_ledger(path):
    """ledger.tsv: month<TAB>scheme<TAB>base<TAB>personal<TAB>company[<TAB>note]
    base/company 可留空（反解）。month+scheme 全账唯一。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    lines = [ln for ln in raw.split("\n") if ln.strip() != ""]
    if not lines:
        raise LedgerError("empty ledger")
    head = [h.strip() for h in lines[0].split("\t")]
    if head[:2] != ["month", "scheme"] or len(head) < 5:
        raise LedgerError("header must be month/scheme/base/personal/company/"
                          "note, got %r" % head)
    rows = {"social": {}, "fund": {}}
    for ln in lines[1:]:
        cols = ln.split("\t")
        where = "row %r" % cols[0]
        if len(cols) < 5:
            raise LedgerError("need >=5 columns: %r" % ln)
        month = ym_parse(cols[0])
        scheme = norm_scheme(cols[1])
        base = parse_money(cols[2], "base", where, 0.0, 500000.0,
                           allow_empty=True)
        personal = parse_money(cols[3], "personal", where, 0.0, 200000.0)
        company = parse_money(cols[4], "company", where, 0.0, 200000.0,
                              allow_empty=True)
        note = cols[5].strip() if len(cols) > 5 else ""
        if month in rows[scheme]:
            raise LedgerError("duplicate %s %s" % (scheme, ym_fmt(month)))
        rows[scheme][month] = Row(month, scheme, base, personal, company, note)
    if not rows["social"] and not rows["fund"]:
        raise LedgerError("no data rows")
    return rows


def load_wages(path):
    """wages.tsv: month<TAB>gross[<TAB>note]"""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    lines = [ln for ln in raw.split("\n") if ln.strip() != ""]
    if not lines:
        raise LedgerError("empty wages")
    head = [h.strip() for h in lines[0].split("\t")]
    if head[:2] != ["month", "gross"]:
        raise LedgerError("wages header must be month/gross/note, got %r"
                          % head)
    out = {}
    for ln in lines[1:]:
        cols = ln.split("\t")
        where = "wage row %r" % cols[0]
        month = ym_parse(cols[0])
        gross = parse_money(cols[1], "gross", where, 0.0, 500000.0)
        if month in out:
            raise LedgerError("duplicate wage month %s" % ym_fmt(month))
        out[month] = gross
    if not out:
        raise LedgerError("no wage rows")
    return out


def apply_as_of(rows, as_of):
    if as_of is None:
        return rows
    kept = {"social": {}, "fund": {}}
    for scheme, table in rows.items():
        for month, row in table.items():
            if ym_sub(month, as_of) <= 0:
                kept[scheme][month] = row
    if not kept["social"] and not kept["fund"]:
        raise LedgerError("as-of %s before first row" % ym_fmt(as_of))
    return kept


# ---------------------------------------------------------------- 事实核

class Facts(object):
    def __init__(self, rows, args):
        self.rows = rows
        self.args = args
        all_months = sorted(set(rows["social"]) | set(rows["fund"]))
        self.first = all_months[0]
        self.last = all_months[-1]
        self.span = ym_sub(self.last, self.first) + 1
        self.months = ym_seq(self.first, self.last)
        self.wages = getattr(args, "wages", None)
        # 覆盖与断月
        self.present = {}
        self.gaps = {}
        self.backfill_months = {}
        for scheme in ("social", "fund"):
            table = rows[scheme]
            self.present[scheme] = [m for m in self.months if m in table]
            self.gaps[scheme] = [m for m in self.months if m not in table]
            self.backfill_months[scheme] = [
                m for m, r in table.items() if r.backfill and
                ym_sub(self.last, m) >= 0]
        self.wage_ref_desc = self._wage_desc()

    # ---- 工资参照 ----
    def _wage_desc(self):
        if self.wages is not None:
            return "payroll %s (per-month)" % (
                os.path.basename(self.args.wages_path) if
                getattr(self.args, "wages_path", None) else "tsv")
        if self.args.salary is not None:
            return "--salary %.2f (flat)" % self.args.salary
        return "none"

    def wage(self, month):
        if self.wages is not None:
            return self.wages.get(month)
        if self.args.salary is not None:
            return self.args.salary
        return None

    def has_wage_ref(self):
        return self.args.salary is not None or self.wages is not None

    # ---- 基数与反解 ----
    def personal_rate(self, scheme):
        return (self.args.social_personal if scheme == "social"
                else self.args.fund_personal)

    def total_rate(self, scheme):
        if scheme == "fund":
            return self.args.fund_personal + self.args.fund_company
        return self.args.pension

    def effective_base(self, scheme, month):
        """实缴基数：行缺 → 0.0；base 空 → personal ÷ 个人比例反解。"""
        row = self.rows[scheme].get(month)
        if row is None:
            return 0.0
        if row.base is not None:
            return row.base
        rate = self.personal_rate(scheme)
        if rate <= 0:
            return 0.0
        return row.personal / rate

    def base_source(self, scheme, month):
        row = self.rows[scheme].get(month)
        if row is None:
            return "absent"
        return "given" if row.base is not None else "solved"

    def shadow_split(self, scheme, month):
        """暗折分解：返回 (低报部分, 缺席部分)。无工资参照 → None。"""
        ref = self.wage(month)
        if ref is None:
            return None
        row = self.rows[scheme].get(month)
        rate = self.total_rate(scheme)
        base = self.effective_base(scheme, month)
        under = max(ref - base, 0.0)
        if row is None:
            return 0.0, under * rate
        return under * rate, 0.0

    def shadow(self, scheme, month):
        s = self.shadow_split(scheme, month)
        return None if s is None else s[0] + s[1]

    def month_is_certain(self, scheme, month):
        """确凿暗折月 = SHAVED 月或整月缺席；LAG/FULL 月的少缴可能是
        上年月均口径的合法滞后，计入总额但不当灯。"""
        row = self.rows[scheme].get(month)
        if row is None:
            return True
        band, _ = self.band(scheme, month)
        return band == "SHAVED"

    def ratio(self, scheme, month):
        ref = self.wage(month)
        if ref is None or ref <= 0:
            return None
        return self.effective_base(scheme, month) / ref

    def band(self, scheme, month):
        r = self.ratio(scheme, month)
        if r is None:
            return "NO-REF", None
        if r < self.args.base_floor - 1e-9:
            return "SHAVED", r
        if r < self.args.lag_line - 1e-9:
            return "LAG", r
        return "FULL", r

    def floor_pay(self, scheme, month):
        """按下限交法指纹：基数 ≤ --floor-value 且工资高于下限。"""
        fv = self.args.floor_value
        if fv is None:
            return False
        ref = self.wage(month)
        if ref is None:
            return False
        row = self.rows[scheme].get(month)
        if row is None or row.base is None:
            return False
        return row.base <= fv + EPS and ref > fv + EPS

    # ---- 连续账 ----
    def _current_streak(self, scheme, strict):
        cur = self.last
        n = 0
        table = self.rows[scheme]
        while ym_sub(cur, self.first) >= 0:
            row = table.get(cur)
            if row is None:
                break
            if strict and row.backfill:
                break
            n += 1
            cur = ym_add(cur, -1)
        return n

    def _longest_streak(self, scheme, strict):
        best = 0
        run = 0
        for m in self.months:
            row = self.rows[scheme].get(m)
            ok = row is not None and not (strict and row.backfill)
            run = run + 1 if ok else 0
            best = max(best, run)
        return best

    def streaks(self, scheme):
        return {
            "current": self._current_streak(scheme, strict=False),
            "current_strict": self._current_streak(scheme, strict=True),
            "longest": self._longest_streak(scheme, strict=False),
            "longest_strict": self._longest_streak(scheme, strict=True),
        }

    def strict_gaps(self, scheme):
        """严格口径的断点 = 缺行月 ∪ 补缴月。"""
        return sorted(set(self.gaps[scheme]) |
                      set(self.backfill_months[scheme]))

    def achievement(self, scheme, require, strict=False, gap=0):
        """(达成月, 已达成?)。gap = 账本末月后的空档月数。
        空档会打断连续性：旧连续清零，从续缴月起重数完整的 require 个月。"""
        if gap > 0:
            return ym_add(self.last, gap + require), False
        s = self._current_streak(scheme, strict=strict)
        if s >= require:
            return self.last, True
        return ym_add(self.last, require - s), False

    def thin(self):
        return self.span < THIN_MONTHS


# ---------------------------------------------------------------- 输出

def banner(text):
    print("!! " + text)


def lamp(name, detail):
    print("LAMP %s — %s" % (name, detail))


def money(v):
    return "{:,.2f}".format(v)


def head(f, title, ledger_path, args):
    print("== 暗基数 · Shadow Base — %s" % title)
    print("ledger: %s   span: %s .. %s (%d months)   as-of: %s"
          % (os.path.basename(ledger_path), ym_fmt(f.first), ym_fmt(f.last),
             f.span, ym_fmt(f.last) if args.as_of is None else args.as_of))
    print("wage ref: %s" % f.wage_ref_desc)


BAND_TAG = {
    "SHAVED": "SHAVED 不足额(红灯)",
    "LAG": "LAG 合法滞后带",
    "FULL": "FULL 口径内足额",
    "NO-REF": "NO-REF 无工资参照",
}


def run_groups(f, scheme):
    """把连续且 (band, 基数, ratio) 相同的月份折叠成段。"""
    out = []
    cur = None
    for m in f.months:
        row = f.rows[scheme].get(m)
        if row is None:
            key = ("absent", None, None)
        else:
            b, r = f.band(scheme, m)
            key = (b, round(f.effective_base(scheme, m), 2),
                   None if r is None else round(r, 4))
        if cur is not None and cur["key"] == key:
            cur["end"] = m
            cur["n"] += 1
        else:
            if cur is not None:
                out.append(cur)
            cur = {"key": key, "start": m, "end": m, "n": 1}
    if cur is not None:
        out.append(cur)
    return out


# ---------------------------------------------------------------- 命令

def cmd_report(f, ledger_path, args):
    head(f, "总账", ledger_path, args)
    print("")
    rc = EXIT_OK
    lamps = []
    if f.thin():
        print("thin ledger (span %d months < %d): 统计判级 DECLINED "
              "(exit 3)，算术照常——账本再薄也如实出数"
              % (f.span, THIN_MONTHS))
        rc = EXIT_THIN
    # 双账本合计
    sums = {}
    for scheme in ("social", "fund"):
        table = f.rows[scheme]
        p = sum(r.personal for r in table.values())
        c = sum(r.company for r in table.values() if r.company is not None)
        sums[scheme] = (p, c)
        line = "%s: 覆盖 %d/%d 月" % (scheme, len(f.present[scheme]), f.span)
        if f.backfill_months[scheme]:
            line += "（补缴 %d 行: %s）" % (
                len(f.backfill_months[scheme]),
                " ".join(ym_fmt(m) for m in sorted(
                    f.backfill_months[scheme])))
        print(line)
        print("    Σ个人 %s%s" % (money(p),
              ("  + Σ公司 %s  = 合计 %s" % (money(c), money(p + c)))
              if c else ""))
    print("")
    # 断月与连续
    for scheme in ("social", "fund"):
        st = f.streaks(scheme)
        gaps = f.gaps[scheme]
        if gaps:
            print("%s 断月: %s" % (scheme, " ".join(ym_fmt(m) for m in gaps)))
        else:
            print("%s 断月: none" % scheme)
        sg = f.strict_gaps(scheme)
        extra = ("   strict 口径当前 %d（断点: %s）"
                 % (st["current_strict"],
                    " ".join(ym_fmt(m) for m in sg))) \
            if sg and st["current_strict"] != st["current"] else ""
        print("    连续: 当前 %d · 最长 %d%s"
              % (st["current"], st["longest"], extra))
        if gaps and scheme == "social":
            banner("social 存在断月：多数城市断缴次月起停止医保报销，"
                   "续缴后恢复期各异——以当地口径为准")
    print("")
    # 资格倒计时（月历算术，不需要工资参照）
    if args.require is not None:
        for scheme in ("social", "fund"):
            st = f.streaks(scheme)
            if st["current"] >= args.require:
                print("require %d (%s): 已达成（当前连续 %d）——"
                      "断缴即可能清零，资格窗口以当地口径为准"
                      % (args.require, scheme, st["current"]))
            else:
                ach, _ = f.achievement(scheme, args.require)
                print("require %d (%s): 未达成——还差 %d 个月，"
                      "按月历连续缴预计 %s 达成"
                      % (args.require, scheme,
                         args.require - st["current"], ym_fmt(ach)))
    # 基数审计汇总
    if not f.has_wage_ref():
        print("基数审计: skipped — 无工资参照（--salary 或 payroll.tsv），"
              "没有参照就没有水位")
    else:
        worst = None
        fp_months = []
        shadow_tot = {"social": 0.0, "fund": 0.0}
        shadow_has = False
        for scheme in ("social", "fund"):
            for m in f.months:
                b, r = f.band(scheme, m)
                # 断缴缺席月不是「水位低」，是「压根没缴」——归缺席账管
                if b == "SHAVED" and m in f.rows[scheme] \
                        and (worst is None or r < worst[2]):
                    worst = (scheme, m, r)
                if f.floor_pay(scheme, m):
                    fp_months.append((scheme, m))
                sh = f.shadow(scheme, m)
                if sh is not None:
                    shadow_has = True
                    shadow_tot[scheme] += sh
        if worst:
            lamps.append(("SHAVED", "最低缴费水位 %.4f @ %s %s —— "
                          "公司在按另一个收入的你交社保"
                          % (worst[2], ym_fmt(worst[1]), worst[0])))
        if fp_months:
            lamps.append(("FLOOR-PAY",
                          "%d 个月实缴基数 == 当地下限（按下限交法的指纹）"
                          % len(fp_months)))
        if shadow_has:
            total = shadow_tot["fund"] + shadow_tot["social"]
            last_ref = f.wage(f.last)
            mult = total / last_ref if last_ref else 0.0
            fu = sum((f.shadow_split("fund", m) or (0, 0))[0]
                     for m in f.months)
            fa = sum((f.shadow_split("fund", m) or (0, 0))[1]
                     for m in f.months)
            split = ("（低报 %s + 断缴缺席 %s）" % (money(fu), money(fa))
                     if fa > 0 else "")
            print("暗折: 公积金 %s%s + 养老个人账户 %s = %s ≈ %.2f 个月工资"
                  % (money(shadow_tot["fund"]), split,
                     money(shadow_tot["social"]), money(total), mult))
            certain = sum(f.shadow(scheme, m) or 0.0
                          for scheme in ("social", "fund")
                          for m in f.months
                          if f.shadow(scheme, m) is not None
                          and f.month_is_certain(scheme, m))
            if last_ref and certain >= last_ref:
                lamps.append(("SHADOW MONTHS",
                              "确凿暗折 %s ≥ 1 个月工资——你被偷走了 %.2f 个"
                              "月的工资，以福利的名义"
                              % (money(certain), certain / last_ref)))
    print("")
    if not lamps:
        if rc == EXIT_OK:
            print("no lamps. 两本账对得上。")
        return rc
    for name, detail in lamps:
        lamp(name, detail)
    if rc == EXIT_THIN:
        return rc
    if any(n in ("SHAVED", "FLOOR-PAY", "SHADOW MONTHS")
           for n, _ in lamps):
        return EXIT_RED
    return EXIT_OK


def cmd_audit(f, ledger_path, args):
    head(f, "基数对账", ledger_path, args)
    print("")
    if f.span < THIN_MONTHS:
        print("thin ledger: 对账需要 ≥%d 个月跨度，现在 %d — 算术照出，"
              "判级 DECLINED" % (THIN_MONTHS, f.span))
    print("水位 = 实缴基数 ÷ 工资参照。判级: SHAVED < %.2f ≤ LAG < %.2f ≤ "
          "FULL（LAG 是上年月均口径的合法滞后带，不亮灯但值得知道）"
          % (args.base_floor, args.lag_line))
    if not f.has_wage_ref():
        print("")
        print("declined: 无工资参照（--salary 或 payroll.tsv），"
              "只出基数表，不出水位与暗折")
        rc = EXIT_THIN
    else:
        rc = EXIT_OK
    print("")
    red = False
    for scheme in ("social", "fund"):
        print("-- %s --" % scheme)
        rate = f.total_rate(scheme)
        prate = f.personal_rate(scheme)
        if scheme == "fund":
            print("   暗折费率: 个人 %.1f%% + 公司 %.1f%% = %.1f%%"
                  "（两半都是你的钱；反解用个人 %.1f%%）"
                  % (prate * 100, (rate - prate) * 100, rate * 100,
                     prate * 100))
        else:
            print("   暗折费率: 养老个人账户划入 %.1f%%"
                  "（医保统筹是共济不是你的钱，不定价；反解用个人 %.1f%%）"
                  % (rate * 100, prate * 100))
        groups = run_groups(f, scheme)
        for g in groups:
            key = g["key"]
            span_s = ym_fmt(g["start"])
            span_e = ym_fmt(g["end"])
            months_tag = "%s..%s (%dm)" % (span_s, span_e, g["n"])
            if key[0] == "absent":
                print("  %s   断月（无行）——缺席月不假装你在缴费" % months_tag)
                continue
            base, r = key[1], key[2]
            tag = BAND_TAG[key[0]]
            fp = "  FLOOR-PAY指纹" if f.floor_pay(scheme, g["start"]) else ""
            sh = f.shadow(scheme, g["start"])
            sh_m = "  暗折 %s/月" % money(sh) if sh is not None and sh > 0 \
                else ""
            print("  %s   base %s  ratio %s  %s%s%s"
                  % (months_tag, money(base),
                     "%.4f" % r if r is not None else "  n/a", tag, fp, sh_m))
            if key[0] == "SHAVED":
                red = True
        print("")
    if rc == EXIT_THIN:
        return rc
    if red:
        lamp("SHAVED", "存在不足额月份——缩水的基数正在给你的养老金、"
             "公积金和医保打折")
        return EXIT_THIN if f.thin() else EXIT_RED
    print("水位全部在口径内（LAG/FULL），无 SHAVED 月份。")
    return EXIT_THIN if f.thin() else EXIT_OK


def cmd_streak(f, ledger_path, args):
    head(f, "连续账", ledger_path, args)
    print("")
    print("月历（■=缴纳 ·=断月 ~=补缴；span %d 个月）" % f.span)
    for scheme in ("social", "fund"):
        marks = []
        for m in f.months:
            row = f.rows[scheme].get(m)
            if row is None:
                marks.append("·")
            elif row.backfill:
                marks.append("~")
            else:
                marks.append("■")
        st = f.streaks(scheme)
        print("%-6s %s  当前 %d · 最长 %d | strict 当前 %d · 最长 %d"
              % (scheme, "".join(marks), st["current"], st["longest"],
                 st["current_strict"], st["longest_strict"]))
    print("")
    for scheme in ("social", "fund"):
        gaps = f.gaps[scheme]
        sg = f.strict_gaps(scheme)
        print("%s 断月: %s   strict 断点(缺行∪补缴): %s"
              % (scheme,
                 " ".join(ym_fmt(m) for m in gaps) if gaps else "none",
                 " ".join(ym_fmt(m) for m in sg) if sg else "none"))
    print("")
    if args.require is None:
        print("(--require N 可加资格倒计时：购房/落户/公积金贷款的连续月数"
              "要求——它是你的参数，政策永远赢)")
        return EXIT_OK
    print("require %d 连续月（月历口径；--strict 换补缴断链口径）:"
          % args.require)
    for scheme in ("social", "fund"):
        st = f.streaks(scheme)
        ach, done = f.achievement(scheme, args.require, strict=args.strict)
        strict_ach, strict_done = f.achievement(scheme, args.require,
                                                strict=True)
        if (args.strict and strict_done) or (not args.strict and done):
            print("  %s: 已达成（当前 %d）——断缴即可能清零，以当地口径为准"
                  % (scheme, st["current_strict"] if args.strict
                     else st["current"]))
            continue
        cur = st["current_strict"] if args.strict else st["current"]
        print("  %s: 还差 %d 个月（当前 %d），预计 %s 达成"
              % (scheme, args.require - cur, cur, ym_fmt(ach)))
        if strict_ach != ach:
            print("        strict 口径: 预计 %s 达成（补缴月断链）"
                  % ym_fmt(strict_ach))
    print("")
    for scheme in ("social", "fund"):
        if f.gaps[scheme]:
            banner("%s 账本内存在断月：%s" % (
                scheme, " ".join(ym_fmt(m) for m in f.gaps[scheme])))
    return EXIT_OK


def cmd_compare(f, ledger_path, args):
    head(f, "暗折账（反事实：账本世界 vs 足额世界）", ledger_path, args)
    print("")
    if not f.has_wage_ref():
        print("declined: 暗折需要工资参照（--salary 或 payroll.tsv）"
              "——没有参照，就不知道「足额」长什么样")
        return EXIT_THIN
    if f.span < THIN_MONTHS:
        print("thin ledger: 暗折判级需要 ≥%d 个月，现在 %d — 算术照出，"
              "判级 DECLINED" % (THIN_MONTHS, f.span))
    world_a = {"social": 0.0, "fund": 0.0}
    world_b = {"social": 0.0, "fund": 0.0}
    under = {"social": 0.0, "fund": 0.0}
    soft = {"social": 0.0, "fund": 0.0}
    absent = {"social": 0.0, "fund": 0.0}
    for scheme in ("social", "fund"):
        rate = f.total_rate(scheme)
        for m in f.months:
            ref = f.wage(m)
            if ref is None:
                continue
            eb = f.effective_base(scheme, m)
            world_a[scheme] += eb * rate
            world_b[scheme] += ref * rate
            s = f.shadow_split(scheme, m)
            if f.month_is_certain(scheme, m):
                under[scheme] += s[0]
            else:
                soft[scheme] += s[0]
            absent[scheme] += s[1]
    print("两世界对照（暗折费率 = 个人 + 公司划入你名下的部分；"
          "统筹是共济不定价）:")
    for scheme in ("social", "fund"):
        print("  %-6s 账本世界 %s   足额世界 %s   差 %s"
              % (scheme, money(world_a[scheme]), money(world_b[scheme]),
                 money(world_b[scheme] - world_a[scheme])))
    print("")
    total_under = under["fund"] + under["social"]
    total_soft = soft["fund"] + soft["social"]
    total_absent = absent["fund"] + absent["social"]
    grand = total_under + total_soft + total_absent
    print("暗折账:")
    print("  低报暗折（SHAVED 月，基数缩水但月月在缴）: %s"
          % money(total_under))
    print("    其中 公积金 %s ＋ 养老个人账户 %s"
          % (money(under["fund"]), money(under["social"])))
    if total_soft > 0:
        print("  滞后带少缴（LAG/FULL 月，上年月均口径下可能合法，"
              "不当灯）: %s" % money(total_soft))
    print("  断缴缺席（整月无行，一分没进）: %s" % money(total_absent))
    print("  合计 %s" % money(grand))
    rc = EXIT_OK
    last_ref = f.wage(f.last)
    certain = total_under + total_absent
    if f.thin():
        rc = EXIT_THIN
    elif last_ref and certain >= last_ref:
        lamp("SHADOW MONTHS",
             "确凿暗折 %s ≈ %.2f 个月工资（参照 %s/月）——"
             "这笔钱以福利的名义从你名下流走"
             % (money(certain), certain / last_ref, money(last_ref)))
        rc = EXIT_RED
    else:
        print("确凿暗折 %s 未及一个月工资参照线（%s）——灯不亮，账照记"
              % (money(certain), money(last_ref or 0.0)))
    return rc


def cmd_simulate(f, ledger_path, args):
    head(f, "反事实", ledger_path, args)
    print("")
    if args.sim == "quit":
        gap = args.gap
        resume = ym_add(f.last, gap + 1)
        gap_months = [ym_add(f.last, k) for k in range(1, gap + 1)]
        print("假设: 账本末月 %s 之后空档 %d 个月（%s），%s 起新公司续缴"
              % (ym_fmt(f.last), gap,
                 " ".join(ym_fmt(m) for m in gap_months), ym_fmt(resume)))
        print("失业月没有工资，也没有工资参照——不发明暗折，只推演资格。")
        print("")
        rc = EXIT_OK
        for scheme in ("social", "fund"):
            st = f.streaks(scheme)
            if args.require is None:
                print("  %s: 当前连续 %d，断档后月历口径归零重计（strict 口径"
                      "当前已是 %d）" % (scheme, st["current"],
                                        st["current_strict"]))
                continue
            ach, done = f.achievement(scheme, args.require,
                                      strict=args.strict)
            ach2, _ = f.achievement(scheme, args.require, strict=args.strict,
                                    gap=gap)
            if done:
                print("  %s: 已达成（连续 %d）——断档后资格可能清零，"
                      "%s 起重攒，%s 才重新达成（政策永远赢）"
                      % (scheme, st["current"], ym_fmt(resume), ym_fmt(ach2)))
            else:
                print("  %s: 原节奏 %s 达成 → 断档后 %s 达成，推迟 %d 个月"
                      % (scheme, ym_fmt(ach), ym_fmt(ach2),
                         ym_sub(ach2, ach)))
        if args.require is None:
            print("")
            print("(--require N 可加资格倒计时推演)")
            return rc
        print("")
        banner("医保：断档月次月起多数城市停止报销——空窗 %d 个月，"
               "期间的就医安排自己掂量" % gap)
        return rc
    # bridge
    gap = args.gap
    resume = ym_add(f.last, gap + 1)
    gap_months = [ym_add(f.last, k) for k in range(1, gap + 1)]
    print("假设: 空档 %d 个月（%s）由你自缴架桥（灵活就业/代缴），%s 起新"
          "公司续缴" % (gap, " ".join(ym_fmt(m) for m in gap_months),
                        ym_fmt(resume)))
    print("")
    for scheme in ("social", "fund"):
        st = f.streaks(scheme)
        if args.require is None:
            print("  %s: 当前连续 %d——架桥后月历不断" % (scheme, st["current"]))
            continue
        ach, done = f.achievement(scheme, args.require)
        if done:
            print("  %s: 已达成（连续 %d），架桥后月历口径不受影响"
                  % (scheme, st["current"]))
        else:
            print("  %s: 预计 %s 达成——架桥后月历口径不推迟" %
                  (scheme, ym_fmt(ach)))
        print("        strict 口径: 自缴月算不算连续，各地资格口径不同——"
              "本件按月历计，政策永远赢")
    print("")
    print("自缴金额以当地灵活就业口径为准，本件不发明你的钱。")
    return EXIT_OK


def cmd_validate(f, ledger_path, args):
    head(f, "账本体检", ledger_path, args)
    print("")
    ok = True
    # 1. Σ 复算
    for scheme in ("social", "fund"):
        table = f.rows[scheme]
        p2 = sum(r.personal for r in table.values())
        p1 = sum(r.personal for r in
                 [table[m] for m in sorted(table)])
        ok &= (p2 == p1)
        print("Σ%s 个人复算: %s == %s %s" % (scheme, money(p2), money(p1),
                                             "OK" if p2 == p1 else "FAIL"))
    # 2. 断月双算法：月历游走 vs 行集合差
    gaps_a = {}
    gaps_b = {}
    for scheme in ("social", "fund"):
        walk = []
        cur = f.first
        table = f.rows[scheme]
        while ym_sub(f.last, cur) >= 0:
            if cur not in table:
                walk.append(cur)
            cur = ym_add(cur, 1)
        gaps_a[scheme] = walk
        gaps_b[scheme] = [m for m in f.months if m not in table]
        same = gaps_a[scheme] == gaps_b[scheme]
        ok &= same
        print("%s 断月双算法: %d == %d %s" % (
            scheme, len(gaps_a[scheme]), len(gaps_b[scheme]),
            "OK" if same else "FAIL"))
    # 3. 连续双算法：向后游走 vs 正向扫描
    for scheme in ("social", "fund"):
        for strict in (False, True):
            backward = f._current_streak(scheme, strict=strict)
            forward = 0
            run = 0
            for m in reversed(f.months):
                row = f.rows[scheme].get(m)
                ok_m = row is not None and not (strict and row.backfill)
                if ok_m:
                    run += 1
                    forward = max(forward, run)
                else:
                    break
            same = backward == forward
            ok &= same
            print("%s 当前连续(strict=%s) 双算法: %d == %d %s"
                  % (scheme, strict, backward, forward,
                     "OK" if same else "FAIL"))
    # 4. 公司缴额口径披露（显式值 vs 反解）
    mism = []
    for scheme in ("social", "fund"):
        if scheme != "fund":
            continue  # social 公司比例各险种杂，不做反解披露
        for m, row in sorted(f.rows[scheme].items()):
            if row.company is None or row.base is None:
                continue
            expect = row.base * f.args.fund_company
            if abs(row.company - expect) > COMPANY_TOL * max(expect, 1.0):
                mism.append((m, row.company, expect))
    if mism:
        print("公积金公司缴额与基数×%.0f%% 口径不符 %d 行（比例非默认？"
              "--fund-company 覆盖）:" % (f.args.fund_company * 100,
                                         len(mism)))
        for m, got, exp in mism:
            print("  %s 实记 %s vs 口径 %s" % (ym_fmt(m), money(got),
                                               money(exp)))
    else:
        print("公积金公司缴额口径: OK")
    # 5. 覆盖披露
    for scheme in ("social", "fund"):
        n_bf = len(f.backfill_months[scheme])
        print("%s 覆盖 %d/%d 月，补缴行 %d" % (
            scheme, len(f.present[scheme]), f.span, n_bf))
    solved = sum(1 for scheme in ("social", "fund")
                 for m in f.rows[scheme]
                 if f.base_source(scheme, m) == "solved")
    if solved:
        print("基数反解行 %d（base 列留空由 personal÷个人比例反解）" % solved)
    else:
        print("基数反解行 0（全部显式给出）")
    # 6. 暗折分解恒等：fund 暗折 == 低报 + 缺席
    if f.has_wage_ref():
        tot = sum(f.shadow("fund", m) or 0.0 for m in f.months)
        u = sum(f.shadow_split("fund", m)[0] for m in f.months
                if f.shadow_split("fund", m) is not None)
        a = sum(f.shadow_split("fund", m)[1] for m in f.months
                if f.shadow_split("fund", m) is not None)
        resid = abs(tot - (u + a))
        ok &= resid < 1e-6
        print("fund 暗折分解恒等: %.2f == %.2f + %.2f (残差 %.1e) %s"
              % (tot, u, a, resid, "OK" if resid < 1e-6 else "FAIL"))
    print("")
    print("ledger OK" if ok else "ledger BROKEN")
    return EXIT_OK if ok else EXIT_LEDGER


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(
        prog="shadow_base.py",
        description="暗基数 · Shadow Base —— 工资条 × 社保系统的"
                    "五险一金对账")
    p.add_argument("cmd", choices=[
        "report", "audit", "streak", "compare", "simulate", "validate"])
    p.add_argument("ledger", help="ledger.tsv (month/scheme/base/personal/"
                                  "company/note)")
    p.add_argument("--wages", dest="wages_path", default=None,
                   help="wages.tsv (month/gross)——逐月工资参照")
    p.add_argument("--salary", type=float, default=None,
                   help="工资参照（全期常数；payroll.tsv 优先）")
    p.add_argument("--as-of", dest="as_of", default=None,
                   help="截断账本到该月（含当月），YYYY-MM")
    p.add_argument("--require", type=int, default=None,
                   help="资格所需连续缴纳月数（购房/落户/公积金贷款；"
                        "你的参数，政策永远赢）")
    p.add_argument("--strict", action="store_true",
                   help="严格口径：补缴月也断链")
    p.add_argument("--base-floor", dest="base_floor", type=float,
                   default=BAND_FLOOR,
                   help="SHAVED 红线：水位低于此判不足额（默认 0.60）")
    p.add_argument("--lag-line", dest="lag_line", type=float,
                   default=BAND_LAG,
                   help="LAG 滞后带上沿（默认 0.90）")
    p.add_argument("--floor-value", dest="floor_value", type=float,
                   default=None,
                   help="当地社保基数下限（绝对值）——给出才启用 "
                        "FLOOR-PAY 指纹")
    p.add_argument("--social-personal", dest="social_personal",
                   type=float, default=SOCIAL_PERSONAL,
                   help="社保个人比例（默认 0.105）")
    p.add_argument("--fund-personal", dest="fund_personal", type=float,
                   default=FUND_PERSONAL, help="公积金个人比例（默认 0.12）")
    p.add_argument("--fund-company", dest="fund_company", type=float,
                   default=FUND_COMPANY, help="公积金公司比例（默认 0.12）")
    p.add_argument("--pension", type=float, default=PENSION,
                   help="养老个人账户划入比例（默认 0.08）")
    p.add_argument("extra", nargs="*", default=[],
                   help="simulate 子命令: quit [gap_months] | "
                        "bridge [gap_months]（空档月数默认 1）")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        as_of = ym_parse(args.as_of) if args.as_of else None
        rows = apply_as_of(load_ledger(args.ledger), as_of)
        if args.wages_path:
            args.wages = apply_as_of_wages(load_wages(args.wages_path),
                                           as_of)
        else:
            args.wages = None
        f = Facts(rows, args)
        if args.lag_line <= args.base_floor:
            print("--lag-line must be > --base-floor", file=sys.stderr)
            return EXIT_LEDGER
        if args.cmd == "report":
            return cmd_report(f, args.ledger, args)
        if args.cmd == "audit":
            return cmd_audit(f, args.ledger, args)
        if args.cmd == "streak":
            return cmd_streak(f, args.ledger, args)
        if args.cmd == "compare":
            return cmd_compare(f, args.ledger, args)
        if args.cmd == "simulate":
            sub = args.extra[0] if args.extra else None
            if sub not in ("quit", "bridge"):
                print("simulate needs: quit [gap_months] | bridge [gap_months]")
                return EXIT_LEDGER
            gap = 1
            if len(args.extra) >= 2:
                try:
                    gap = int(args.extra[1])
                except ValueError:
                    print("gap_months needs an integer")
                    return EXIT_LEDGER
            if gap < 0:
                print("gap_months must be >= 0")
                return EXIT_LEDGER
            args.gap = gap
            args.sim = sub
            return cmd_simulate(f, args.ledger, args)
        if args.cmd == "validate":
            return cmd_validate(f, args.ledger, args)
        return EXIT_LEDGER
    except LedgerError as e:
        print("ledger error: %s" % e, file=sys.stderr)
        return EXIT_LEDGER
    except OSError as e:
        print("ledger error: %s" % e, file=sys.stderr)
        return EXIT_LEDGER


def apply_as_of_wages(wages, as_of):
    if as_of is None:
        return wages
    return {m: v for m, v in wages.items() if ym_sub(m, as_of) <= 0}


if __name__ == "__main__":
    sys.exit(main())
