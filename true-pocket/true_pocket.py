#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实掏 · True Pocket — 医保结算单口袋账

医保结算单印了五个数：总费用、统筹支付、个人账户支付、现金支付、自费、
自付——从没有一行加总告诉你「这一年看病，真正从你口袋里出去的钱是多少」。
你的钱分两批被掏走：一批当场掏（现金支付），一批从你自己攒的卡里掏
（个人账户支付——那是你工资里逐月扣来的钱，只是先被圈存进了卡）；
而「自付」与「自费」是两个不同的词（自付 = 目录内报销后的个人分担，
自费 = 目录外全额），全民混淆第一名词，商业险理赔拆单的经典翻车点。

本件把全家结算单抄成一本可手编账（TSV：一行一张结算单），开出六本账：

  report     年度总账：逐笔解剖（三支付恒等校验）+ 实掏两口径
             （真口袋 = 现金 + 个账；严格口袋 = 纯现金）+ 自付/自费分列
             + WHO 灾难性卫生支出线判级（自付卫生支出 > 家庭支付能力
             40% —— 通识红线，--income 不给不判，不发明你的收入）；
  progress   门诊起付线进度条：目录内费用年累计 vs 起付线，还差多少、
             跨线是哪一笔（线前/线后金额切分）——按成员各爬各的线，
             种植牙那 8,600 自费推不动进度条一分一毫；
  deduce     个税大病医疗抵扣凭证：目录内自付年累计 > 15,000 的部分
             （限额 80,000）据实扣除——多数家庭白白放弃的年度退税；
             未达线时如实说差多少，绝不倒推一个数；
  claim      商业险拆单：把指定结算单拆出「目录内自付」（百万医疗险
             常赔的正是这个数）——已拆用声明、半拆用反解、未拆给上界
             并显著标注 assumed；只拆数，不构成理赔承诺；
  family     家庭合并账：按成员分列，全家实掏 = Σ成员实掏（恒等钉死），
             「谁的卡在付谁的账」——共济时代个账消耗逐成员点名；
  validate   账本体检：三支付恒等逐行、分担交叉验证
             （自付 + 自费 = 个账 + 现金）、反解一致性、未来行拒绝。

诚实条款：结算单只印事实，账本只抄事实；政策参数全部 -- 可调
（起付线、报销比例、抵扣线），政策永远赢，本件是计算器不是医保局；
未拆目录外的行按「全目录内」估算抵扣/进度并显著披露 assumed——
给的是上界，不是断言；as-of 缺省 = 账本最大日期，--as-of 钉回过去
即时间剪切，同一本账任何机器任何一天逐字节一致。报告只打印 basename，
本地计算不连任何接口。看不看病、填不填报销，永远是人的决定。
"""

import argparse
import os
import sys
from datetime import date, datetime

EXIT_OK = 0
EXIT_LEDGER = 2
EXIT_DECLINE = 3
EXIT_GATE = 4

EPS = 0.01      # 金额容差：结算单只有两位小数
TOL = 1e-9      # 比率/边界容差

DEFAULT_CAT_LINE = 0.40        # WHO 灾难性卫生支出通识线
DEFAULT_DEDUCT_LINE = 15000.0  # 个税大病医疗起抵线（全国统一政策）
DEFAULT_DEDUCT_CAP = 80000.0   # 个税大病医疗扣除限额

CAT_ALIAS = {
    "门诊": "门诊", "op": "门诊", "outpatient": "门诊", "opd": "门诊",
    "op": "门诊", "clinic": "门诊",
    "住院": "住院", "ip": "住院", "inpatient": "住院", "hosp": "住院",
}


class LedgerError(Exception):
    """账本坏了：语法/恒等破裂/引用/口径，exit 2。"""


class Decline(Exception):
    """账太薄或年份无行：统计判级拒答，算术照出，exit 3。"""


class Gate(Exception):
    """门禁红灯：灾难性卫生支出越线，exit 4。"""


# ---------------------------------------------------------------- 解析

def parse_money(s, what, where, allow_empty=False):
    s = (s or "").strip()
    if s == "":
        if allow_empty:
            return None
        raise LedgerError("%s 为空 (%s)" % (what, where))
    try:
        v = float(s)
    except ValueError:
        raise LedgerError("%s %r 不是数字 (%s)" % (what, s, where))
    if v < -TOL:
        raise LedgerError("%s %r 为负数——退款不建模，删掉重记 (%s)"
                          % (what, s, where))
    if v > 5000000.0:
        raise LedgerError("%s %r 超出结算单量级上限 (%s)" % (what, s, where))
    return round(v, 2)


def parse_date(s, where):
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise LedgerError("日期 %r 不是 YYYY-MM-DD (%s)" % (s, where))


def norm_category(s, where):
    key = (s or "").strip().lower()
    if key not in CAT_ALIAS:
        raise LedgerError("未知类型 %r（want 门诊/OP 或 住院/IP）(%s)"
                          % (s, where))
    return CAT_ALIAS[key]


class Row(object):
    __slots__ = ("date", "hospital", "member", "category", "total", "pool",
                 "acct", "cash", "own", "cat_out", "note", "line")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    # 个账 + 现金 = 结算单上「从你这里拿走」的全部
    @property
    def pocket(self):
        return self.acct + self.cash

    # 目录外已拆？（自费列给了值）
    @property
    def split_out(self):
        return self.cat_out is not None

    # 目录内分担已拆或可反解：反解口径 own = pocket - cat_out
    @property
    def own_eff(self):
        if self.own is not None:
            return self.own, "stated"
        if self.cat_out is not None:
            return round(self.pocket - self.cat_out, 2), "derived"
        return self.pocket, "assumed"

    # 目录内费用：total - 目录外；未拆时按全额估算（assumed）
    @property
    def in_catalog(self):
        return self.total - (self.cat_out if self.cat_out is not None else 0.0)

    @property
    def in_catalog_assumed(self):
        return self.cat_out is None


def read_ledger(path, as_of):
    if not os.path.exists(path):
        raise LedgerError("缺文件: %s" % os.path.basename(path))
    rows = []
    header = None
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cols = line.split("\t")
            if header is None:
                header = [c.strip().lower() for c in cols]
                continue
            if len(cols) != len(header):
                raise LedgerError("%s 第 %d 行: 应 %d 列，实 %d 列"
                                  % (os.path.basename(path), lineno,
                                     len(header), len(cols)))
            r = dict(zip(header, [c.strip() for c in cols]))
            where = "%s 第 %d 行" % (os.path.basename(path), lineno)
            d = parse_date(r.get("date"), where)
            if as_of is not None and d > as_of:
                continue  # --as-of 时间剪切：钉回过去的回放不看不未来的行
            row = Row(
                date=d,
                hospital=r.get("hospital") or "",
                member=(r.get("member") or "").strip() or "本人",
                category=norm_category(r.get("category"), where),
                total=parse_money(r.get("total"), "total 总费用", where),
                pool=parse_money(r.get("pool"), "pool 统筹支付", where),
                acct=parse_money(r.get("acct"), "acct 个人账户支付", where),
                cash=parse_money(r.get("cash"), "cash 现金支付", where),
                own=parse_money(r.get("own"), "own 自付", where,
                                allow_empty=True),
                cat_out=parse_money(r.get("cat_out"), "cat_out 自费", where,
                                    allow_empty=True),
                note=r.get("note") or "",
                line=lineno,
            )
            check_row(row, where)
            rows.append(row)
    if header is None:
        raise LedgerError("%s: 空账本（无表头行）" % os.path.basename(path))
    if not rows:
        raise LedgerError("%s: 剪切后无结算行（as-of 早于全部结算日？）"
                          % os.path.basename(path))
    rows.sort(key=lambda r: (r.date, r.line))
    return rows


def check_row(row, where):
    # 恒等式一（三支付）：total = pool + acct + cash
    if abs(row.total - (row.pool + row.acct + row.cash)) > EPS:
        raise LedgerError(
            "三支付恒等破裂: total %.2f ≠ 统筹 %.2f + 个账 %.2f + 现金 %.2f"
            " (差 %.2f) (%s)" % (row.total, row.pool, row.acct, row.cash,
                                 row.total - row.pool - row.acct - row.cash,
                                 where))
    # 恒等式二（分担交叉，两列都拆时）：own + cat_out = acct + cash
    if row.own is not None and row.cat_out is not None:
        lhs = row.own + row.cat_out
        if abs(lhs - row.pocket) > EPS:
            raise LedgerError(
                "分担交叉恒等破裂: 自付 %.2f + 自费 %.2f = %.2f ≠ 个账+现金"
                " %.2f (差 %.2f) (%s)"
                % (row.own, row.cat_out, lhs, row.pocket, lhs - row.pocket,
                   where))
    if row.own is not None and row.own > row.pocket + EPS:
        raise LedgerError("自付 %.2f > 个账+现金 %.2f (%s)"
                          % (row.own, row.pocket, where))
    if row.cat_out is not None and row.cat_out > row.total + EPS:
        raise LedgerError("自费 %.2f > 总费用 %.2f (%s)"
                          % (row.cat_out, row.total, where))


# ---------------------------------------------------------------- 聚合

def load(args):
    as_of = parse_date(args.as_of, "--as-of") if args.as_of else None
    return read_ledger(args.ledger, as_of)


def resolve_as_of(args, rows):
    if args.as_of:
        return parse_date(args.as_of, "--as-of")
    return max(r.date for r in rows)


def year_of(args, as_of):
    if args.year:
        try:
            return int(args.year)
        except ValueError:
            raise LedgerError("--year %r 不是年份" % args.year)
    return as_of.year


def year_rows(rows, year):
    return [r for r in rows if r.date.year == year]


def sums(rows):
    s = {"n": len(rows), "total": 0.0, "pool": 0.0, "acct": 0.0,
         "cash": 0.0, "own": 0.0, "cat_out": 0.0, "n_split_out": 0,
         "op_n": 0, "op_total": 0.0, "ip_n": 0, "ip_total": 0.0}
    by_member = {}
    for r in rows:
        s["total"] += r.total
        s["pool"] += r.pool
        s["acct"] += r.acct
        s["cash"] += r.cash
        if r.own is not None:
            s["own"] += r.own
        if r.cat_out is not None:
            s["cat_out"] += r.cat_out
            s["n_split_out"] += 1
        if r.category == "门诊":
            s["op_n"] += 1
            s["op_total"] += r.total
        else:
            s["ip_n"] += 1
            s["ip_total"] += r.total
        m = by_member.setdefault(r.member, {"n": 0, "total": 0.0, "pool": 0.0,
                                            "pocket": 0.0, "own": 0.0,
                                            "cat_out": 0.0, "acct": 0.0})
        m["n"] += 1
        m["total"] += r.total
        m["pool"] += r.pool
        m["pocket"] += r.pocket
        m["acct"] += r.acct
        if r.own is not None:
            m["own"] += r.own
        if r.cat_out is not None:
            m["cat_out"] += r.cat_out
    s["by_member"] = by_member
    s["pocket"] = s["acct"] + s["cash"]
    return s


def money(v):
    return "{:,.2f}".format(v)


def pct(v):
    return "%.1f%%" % (v * 100.0)


def head(cmd_title, ledger_path, as_of, year, rows, extra=""):
    span = "%s .. %s" % (rows[0].date.isoformat(), rows[-1].date.isoformat()) \
        if rows else "（无行）"
    print("== 实掏 · True Pocket — %s" % cmd_title)
    print("ledger: %s   年度: %d   结算 %d 笔   %s   as-of: %s%s"
          % (os.path.basename(ledger_path), year, len(rows), span,
             as_of.isoformat(), ("   " + extra) if extra else ""))


def require_year(rows, year):
    yr = year_rows(rows, year)
    if not yr:
        raise Decline("%d 年度无结算行——没有算术，也没有判级" % year)
    return yr


# ---------------------------------------------------------------- 命令

def cmd_report(args):
    rows = load(args)
    as_of = resolve_as_of(args, rows)
    year = year_of(args, as_of)
    yr = require_year(rows, year)
    s = sums(yr)

    head("年度总账", args.ledger, as_of, year, yr,
         "口径: 真口袋 = 现金 + 个账")
    print()
    print("【逐笔解剖】")
    print("  %-11s %-4s %-10s %12s %12s %12s %10s %10s" %
          ("日期", "成员", "类型", "总费用", "统筹支付", "实掏", "自付", "自费"))
    for r in yr:
        print("  %-11s %-4s %-10s %12s %12s %12s %10s %10s" %
              (r.date.isoformat(), r.member, r.category, money(r.total),
               money(r.pool), money(r.pocket),
               money(r.own) if r.own is not None else "—",
               money(r.cat_out) if r.cat_out is not None else "—"))
    print()
    print("【年度总账 %d】" % year)
    print("  总费用        %s   （统筹支付 %s = %.1f%% 接住了）"
          % (money(s["total"]), money(s["pool"]),
             s["pool"] / s["total"] * 100.0))
    print("  实掏·真口袋   %s   （现金 %s + 个账 %s）"
          % (money(s["pocket"]), money(s["cash"]), money(s["acct"])))
    print("  实掏·严格口径 %s   （只算当场掏的现金；个账也是你的钱，"
          "只是先圈存在卡里）" % money(s["cash"]))
    print("  自付（目录内分担） %s / 自费（目录外） %s   ——两个词，不是一回事"
          % (money(s["own"]), money(s["cat_out"])))
    if s["n_split_out"] < s["n"]:
        print("  ⚠ %d/%d 笔未拆目录外列：自付按「个账+现金」反解、"
              "目录内费用按全额估算（assumed 上界）"
              % (s["n"] - s["n_split_out"], s["n"]))
    print("  类型分布: 门诊 %d 笔 %s / 住院 %d 笔 %s"
          % (s["op_n"], money(s["op_total"]), s["ip_n"], money(s["ip_total"])))
    members = sorted(s["by_member"].items(), key=lambda kv: -kv[1]["pocket"])
    print("  谁在花钱: " + " · ".join(
        "%s %s" % (m, money(v["pocket"])) for m, v in members))

    # 灾难性卫生支出线（WHO 通识：自付卫生支出 > 家庭支付能力 40%）
    print()
    if args.income is None:
        print("LAMP 未判 — 未给 --income，灾难线不判（不发明你的收入）")
        return EXIT_OK
    income = args.income
    if income <= 0:
        raise LedgerError("--income 必须为正")
    ratio = s["pocket"] / income
    print("【灾难线】实掏 %s ÷ 年收入 %s = %s（WHO 通识红线 %.0f%%，"
          "--cat-line 可调）" % (money(s["pocket"]), money(income),
                                 pct(ratio), args.cat_line * 100.0))
    n_rows = s["n"]
    span_days = (yr[-1].date - yr[0].date).days
    if n_rows < 3 or span_days < 30:
        print("【薄账】%d 笔 / 跨度 %d 天——统计判级拒答，算术照出"
              % (n_rows, span_days))
        raise Decline("账太薄：灾难线判级需要 ≥3 笔且跨度 ≥30 天")
    if ratio > args.cat_line + TOL:
        print("LAMP CATASTROPHIC — 自付卫生支出占家庭支付能力 %.1f%%，"
              "越过 %.0f%% 通识红线" % (ratio * 100.0,
                                        args.cat_line * 100.0))
        raise Gate("灾难性卫生支出")
    print("LAMP OK — 未越灾难线")
    return EXIT_OK


def cmd_progress(args):
    rows = load(args)
    as_of = resolve_as_of(args, rows)
    year = year_of(args, as_of)
    yr = require_year(rows, year)

    basis = args.basis
    if basis not in ("incatalog", "own", "total"):
        raise LedgerError("--basis %r 不认识（want incatalog/own/total）"
                          % basis)

    def amount(r):
        if basis == "total":
            return r.total
        if basis == "own":
            return r.own_eff[0]
        return r.in_catalog

    cat_filter = norm_category(args.category or "门诊", "--category")
    picked = [r for r in yr if r.category == cat_filter]

    head("起付线进度条", args.ledger, as_of, year, picked,
         "口径: %s · %s 统筹" % (
             {"incatalog": "目录内费用（total − 自费）",
              "own": "自付（目录内个人分担）",
              "total": "总费用"}[basis], cat_filter))
    print()
    n_assumed = sum(1 for r in picked
                    if basis == "incatalog" and r.in_catalog_assumed)
    if n_assumed:
        print("⚠ %d/%d 笔未拆目录外列：目录内费用按全额估算（assumed 上界）"
              % (n_assumed, len(picked)))
    if args.threshold is None:
        print("【各成员累计】（未给 --threshold：不发明政策，不判进度）")
        per = {}
        for r in picked:
            per.setdefault(r.member, [0.0, 0])
            per[r.member][0] += amount(r)
            per[r.member][1] += 1
        for m in sorted(per):
            print("  %-6s 累计 %s   （%d 笔）" % (m, money(per[m][0]),
                                                 per[m][1]))
        return EXIT_OK

    line = args.threshold
    if line <= 0:
        raise LedgerError("--threshold 必须为正")
    print("【起付线 %s / 成员各爬各的线】" % money(line))
    any_reached = False
    for m in sorted({r.member for r in picked}):
        mrows = [r for r in picked if r.member == m]
        cum = 0.0
        crossed = None
        for r in mrows:
            prev = cum
            cum += amount(r)
            if crossed is None and cum >= line - TOL:
                crossed = (r, prev)
        if cum >= line - TOL:
            any_reached = True
            msg = "REACHED"
            detail = ""
            if crossed:
                r, prev = crossed
                before = line - prev
                after = amount(r) - before
                detail = "（跨线笔 %s：%s 线前 %s / 线后 %s" % (
                    r.date.isoformat(), r.hospital, money(before),
                    money(after))
                if args.rate_after is not None:
                    detail += "，线后部分按 %.0f%% 统筹 = %s"
                    detail = detail % (args.rate_after * 100.0,
                                       money(after * args.rate_after))
                detail += "）"
            print("  %-6s %s   累计 %s / 线 %s   %s"
                  % (m, msg, money(cum), money(line), detail))
        else:
            print("  %-6s 差 %s   累计 %s / 线 %s   （%d 笔）"
                  % (m, money(line - cum), money(cum), money(line),
                     len(mrows)))
    if not any_reached:
        print("  ——全家无人到线：门诊统筹的折扣还一分没激活")
    return EXIT_OK


def cmd_deduce(args):
    rows = load(args)
    as_of = resolve_as_of(args, rows)
    year = year_of(args, as_of)
    yr = require_year(rows, year)

    head("个税大病抵扣凭证", args.ledger, as_of, year, yr)
    print()
    base = 0.0
    n_assumed = 0
    for r in yr:
        own, src = r.own_eff
        base += own
        if src == "assumed":
            n_assumed += 1
    line = args.deduct_line
    cap = args.deduct_cap
    if line <= 0 or cap <= 0:
        raise LedgerError("--deduct-line/--deduct-cap 必须为正")
    print("【政策口径】医保目录内自付累计，超过 %s 的部分在 %s 限额内据实扣除"
          "（个税大病医疗专项附加扣除，全国统一；--deduct-line/--deduct-cap "
          "可调——政策改了参数跟上）" % (money(line), money(cap)))
    if n_assumed:
        print("⚠ %d/%d 笔未拆自付列：按「个账+现金」全额计入基数"
              "（ASSUMED 上界——若其中有目录外自费，实际可抵会低于此数）"
              % (n_assumed, len(yr)))
    print("【%d 年度目录内自付累计】%s" % (year, money(base)))
    if args.tax_rate is not None:
        if not (0 < args.tax_rate < 1):
            raise LedgerError("--tax-rate 应在 (0,1) 区间")
    if base <= line:
        gap = line - base
        print("未达起抵线——本年无可抵扣%s。" %
              ("，还差 %s" % money(gap) if gap > 0 else "（恰好踩线，超线部分为 0）"))
        print("账本至少让你不用瞎猜：个税 App 里这一栏，"
              "有人填 0 白扔，有人瞎填上万。你的数字是 %s，见单据为证。"
              % money(base))
        return EXIT_OK
    over = round(base - line, 2)
    usable = min(over, cap)
    print("超过起抵线 %s → 超线部分 %s" % (money(line), money(over)))
    if over > cap + TOL:
        print("超线部分超过限额 %s，按限额计 → 可抵扣 %s" % (money(cap),
                                                            money(usable)))
    else:
        print("未超限额 → 可抵扣 %s" % money(usable))
    if args.tax_rate is not None:
        print("按 --tax-rate %.0f%% 折算省税 ≈ %s"
              % (args.tax_rate * 100.0, money(usable * args.tax_rate)))
    else:
        print("（未给 --tax-rate，不折算省税——不发明你的税率）")
    print("这就是去年那张没人替你保管的凭证：申报时填「%s」，"
          "金额以医保目录内自付累计 %s 为据。" % (money(usable), money(base)))
    return EXIT_OK


def cmd_claim(args):
    rows = load(args)
    as_of = resolve_as_of(args, rows)
    year = year_of(args, as_of)
    yr = require_year(rows, year)

    if args.all:
        picked = sorted(yr, key=lambda r: r.date)
        head("商业险拆单 · 全年", args.ledger, as_of, year, picked)
        print()
        print("【逐笔目录内自付】（百万医疗险常赔的正是这一列；"
              "只拆数，不构成理赔承诺）")
        print("  %-11s %-4s %-12s %12s %12s %8s" %
              ("日期", "成员", "医院", "自费(目录外)", "目录内自付", "来源"))
        for r in picked:
            own, src = r.own_eff
            print("  %-11s %-4s %-12s %12s %12s %8s" %
                  (r.date.isoformat(), r.member, r.hospital[:12],
                   money(r.cat_out) if r.cat_out is not None else "—",
                   money(own), {"stated": "声明", "derived": "反解",
                                "assumed": "ASSUMED"}[src]))
        n_assumed = sum(1 for r in picked if r.own_eff[1] == "assumed")
        if n_assumed:
            print("⚠ %d 笔 ASSUMED：未拆自付/自费列，按「个账+现金」全额作"
                  "目录内自付（上界）——理赔材料以此拆数前，先把结算单"
                  "两列抄齐" % n_assumed)
        return EXIT_OK

    if not args.date:
        raise LedgerError("claim 需要 --date YYYY-MM-DD（或 --all 全年拆单）")
    target = parse_date(args.date, "--date")
    matches = [r for r in yr if r.date == target]
    if not matches:
        raise LedgerError("%d 年 %s 查无此单（账本里没有这一天的结算）"
                          % (year, target.isoformat()))
    idx = (args.index or 1)
    if idx < 1 or idx > len(matches):
        raise LedgerError("--index %d 超出当日结算笔数 %d" % (idx,
                                                              len(matches)))
    r = matches[idx - 1]
    own, src = r.own_eff
    head("商业险拆单", args.ledger, as_of, year, [r])
    print()
    print("【结算单 %s · %s · %s】" % (r.date.isoformat(), r.member,
                                       r.hospital))
    print("  总费用 %s = 统筹 %s + 个账 %s + 现金 %s"
          % (money(r.total), money(r.pool), money(r.acct), money(r.cash)))
    print("  自付（目录内分担）%s / 自费（目录外）%s"
          % (money(r.own) if r.own is not None else "未拆",
             money(r.cat_out) if r.cat_out is not None else "未拆"))
    print()
    if src == "stated":
        print("  目录内自付 = %s（来源：账本声明列，已过交叉验证）" %
              money(own))
    elif src == "derived":
        print("  目录内自付 = 个账+现金 %s − 自费 %s = %s（反解）"
              % (money(r.pocket), money(r.cat_out), money(own)))
    else:
        print("  目录内自付 ≲ %s（ASSUMED：未拆列，按个账+现金全额作上界；"
              "若单据有目录外项，真实数低于此——先把两列抄齐再来拆）"
              % money(own))
    print()
    if r.cat_out is not None:
        print("  别混：自费（目录外）%s 不是理赔基数，保险公司赔的是"
              "「医保目录内自付」这一段——两个词抄错位，是拒赔的经典开场。"
              % money(r.cat_out))
    else:
        print("  自费列未拆：无从提示目录外金额——目录内自付按上界估计，"
              "理赔抄数前先把结算单两列抄齐。")
    print("  （本件只拆数，不构成理赔承诺；条款以保单为准）")
    return EXIT_OK


def cmd_family(args):
    rows = load(args)
    as_of = resolve_as_of(args, rows)
    year = year_of(args, as_of)
    yr = require_year(rows, year)
    s = sums(yr)

    head("家庭合并账", args.ledger, as_of, year, yr)
    print()
    print("【成员账 · %d】" % year)
    print("  %-6s %4s %12s %12s %12s %12s %10s" %
          ("成员", "笔数", "总费用", "统筹支付", "实掏", "个账消耗", "自费"))
    for m in sorted(s["by_member"], key=lambda k: -s["by_member"][k]["pocket"]):
        v = s["by_member"][m]
        print("  %-6s %4d %12s %12s %12s %12s %10s" %
              (m, v["n"], money(v["total"]), money(v["pool"]),
               money(v["pocket"]), money(v["acct"]),
               money(v["cat_out"]) if v["cat_out"] else "—"))
    fam_pocket = sum(v["pocket"] for v in s["by_member"].values())
    print()
    print("【全家实掏】%s   （Σ成员 = %s，恒等校验残差 %.4f）"
          % (money(s["pocket"]), money(fam_pocket),
             abs(fam_pocket - s["pocket"])))
    print("【个账消耗榜】" + (" · ".join(
        "%s %s" % (m, money(v["acct"]))
        for m, v in sorted(s["by_member"].items(), key=lambda kv: -kv[1]["acct"])
        if v["acct"] > 0) or "（全年无一笔动用个账）"))
    print("  共济时代「卡是谁的钱、账是谁的病」是两本账：本件按结算行上的"
          "成员记账，共济划扣以医保平台流水为准。")
    return EXIT_OK


def cmd_validate(args):
    rows = load(args)
    as_of = resolve_as_of(args, rows)
    head("账本体检", args.ledger, as_of, as_of.year, rows)
    print()
    worst = 0.0
    worst_line = None
    cross = 0
    for r in rows:
        resid = abs(r.total - (r.pool + r.acct + r.cash))
        if resid > worst:
            worst = resid
            worst_line = r.line
        if r.own is not None and r.cat_out is not None:
            cross += 1
        # 反解一致性：声明自付 == 个账+现金−自费
        if r.own is not None and r.cat_out is not None:
            derived = r.pocket - r.cat_out
            if abs(derived - r.own) > EPS:
                raise LedgerError("第 %d 行反解不一致: 声明自付 %.2f ≠ "
                                  "个账+现金−自费 %.2f"
                                  % (r.line, r.own, derived))
    print("【三支付恒等】%d 行全部通过，最大残差 %.2e%s"
          % (len(rows), worst,
             ("（第 %d 行，仍在容差内）" % worst_line) if worst > 0 else ""))
    print("【分担交叉验证】%d 行两列齐拆，自付+自费 = 个账+现金 全部成立"
          % cross)
    print("【反解一致性】声明自付 ≡ 个账+现金−自费，逐行通过")
    n_assumed = sum(1 for r in rows if r.own_eff[1] == "assumed")
    n_cat_assumed = sum(1 for r in rows if r.in_catalog_assumed)
    print("【披露】未拆自付列 %d 行（claim/deduce 按上界反解）、"
          "未拆自费列 %d 行（进度按全额估算）——抄齐两列，账本更锋利"
          % (n_assumed, n_cat_assumed))
    if args.as_of:
        print("【时间剪切】--as-of %s 之后的结算行不在本次视野内"
              % args.as_of)
    print("LAMP OK — 账本自洽")
    return EXIT_OK


# ---------------------------------------------------------------- 入口

def read_all(path, as_of):
    """保留给未来用途：原始读取（不做恒等校验）。"""
    try:
        return read_ledger(path, as_of)
    except LedgerError:
        return []


def build_parser():
    # --as-of/--year 是全局口径：主命令与子命令两个位置都收。
    # 子命令侧 default=SUPPRESS：该段未出现时不覆盖主段已解析的值
    sub_common = argparse.ArgumentParser(add_help=False)
    sub_common.add_argument("--as-of", dest="as_of",
                            default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub_common.add_argument("--year", default=argparse.SUPPRESS,
                            help=argparse.SUPPRESS)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--as-of", dest="as_of", default=None,
                        help="钉死回放日 YYYY-MM-DD（缺省=账本最大日期；"
                             "晚于它的结算行被剪切）")
    common.add_argument("--year", default=None,
                        help="统计年度（缺省=as-of 所在年份）")

    p = argparse.ArgumentParser(
        prog="true_pocket",
        description="实掏 · True Pocket — 医保结算单口袋账",
        parents=[common])
    p.add_argument("ledger", help="settlements.tsv 账本路径")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("report", parents=[sub_common],
                       help="年度总账 + 灾难线判级")
    r.add_argument("--income", type=float, default=None,
                   help="家庭年收入（灾难线分母；不给不判级）")
    r.add_argument("--cat-line", dest="cat_line", type=float,
                   default=DEFAULT_CAT_LINE,
                   help="灾难线，默认 0.40（WHO 通识）")
    r.set_defaults(fn=cmd_report)

    g = sub.add_parser("progress", parents=[sub_common],
                       help="门诊起付线进度条")
    g.add_argument("--threshold", type=float, default=None,
                   help="起付线（不给不发明政策，只出累计）")
    g.add_argument("--basis", default="incatalog",
                   choices=["incatalog", "own", "total"],
                   help="累计口径：incatalog=目录内费用（默认）/own=自付/"
                        "total=总费用")
    g.add_argument("--category", default=None,
                   help="只看某类型（门诊/OP 或 住院/IP；缺省=门诊——"
                        "门诊统筹起付线只按门诊累计，住院另有起付线）")
    g.add_argument("--rate-after", dest="rate_after", type=float,
                   default=None, help="线后统筹报销比例（教育性对照披露）")
    g.set_defaults(fn=cmd_progress)

    d = sub.add_parser("deduce", parents=[sub_common],
                       help="个税大病抵扣凭证")
    d.add_argument("--deduct-line", dest="deduct_line", type=float,
                   default=DEFAULT_DEDUCT_LINE,
                   help="起抵线，默认 15000（全国统一政策）")
    d.add_argument("--deduct-cap", dest="deduct_cap", type=float,
                   default=DEFAULT_DEDUCT_CAP, help="扣除限额，默认 80000")
    d.add_argument("--tax-rate", dest="tax_rate", type=float, default=None,
                   help="边际税率（0,1）——给了才折算省税")
    d.set_defaults(fn=cmd_deduce)

    c = sub.add_parser("claim", parents=[sub_common],
                       help="商业险拆单：目录内自付")
    c.add_argument("--date", default=None, help="结算日 YYYY-MM-DD")
    c.add_argument("--index", type=int, default=1,
                   help="同日第几笔（1-based，默认 1）")
    c.add_argument("--all", dest="all", action="store_true",
                   help="全年逐笔拆单表")
    c.set_defaults(fn=cmd_claim)

    f = sub.add_parser("family", parents=[sub_common], help="家庭合并账")
    f.set_defaults(fn=cmd_family)

    v = sub.add_parser("validate", parents=[sub_common], help="账本体检")
    v.set_defaults(fn=cmd_validate)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return EXIT_OK
    try:
        return args.fn(args)
    except LedgerError as e:
        print("LEDGER ERROR: %s" % e, file=sys.stderr)
        return EXIT_LEDGER
    except Decline as e:
        print("DECLINE: %s" % e, file=sys.stderr)
        return EXIT_DECLINE
    except Gate as e:
        print("GATE: %s" % e, file=sys.stderr)
        return EXIT_GATE


if __name__ == "__main__":
    sys.exit(main())
