#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
躺亏 · Dormant Loss / 存款利率的掉档账本。

定期存款的利率是有期限的:合同利率只在 [存入日, 到期日) 兑现,到期日之后,
钱一分不少,价格却由「银行的默认动作」接手——自动转存进的是转存日的挂牌价,
什么都不做则是活期。App 只推送「您的存单已到期」,从不翻译「从此这笔钱每年
少拿多少」;「自动转存」是银行的默认选项,不是你的决定。到期后的每一天,本
金纹丝不动,利息按活期蒸发,而活期利率低到损失毫无体感——这正是它安静的
原因。有人替你记贷款(redemption),没有人替你记存款。

本件把存单抄成可手编账本,开出五本账:

  report   掉档总账——每笔存单的当前执行利率/掉档深度/累计躺亏 + 四灯
  timeline 利率时间线——逐段展开 [合同 → 沉默=活期 → 转存 → 沉默 …] 与每段账
  calendar 到期日历——未来视野内的「私人降息日」+ 正在发生的降息
  decide   转存对拍——拿你抄来的真实报价,两世界(锁定 vs 继续躺)利息差
  validate 恒等式与账本体检——躺亏双算法、到期日几何双算法、利息对拍

核心抽象:**利率时间线是阶梯函数**。合同段之后的一切由 renewals 事件流重放
——沉默就是活期:账本只需要记「主动发生的事」(转存/取走),两段之间的空白
自动按活期补齐。你对存单的每一次沉默,银行都按最低价翻译,账本把这句翻译
写出来。躺亏锚定本笔原合同利率——账本不预测市场,只对比「这笔钱曾经值的
价格」,零外部先验。

诚实条款:活期利率(缺省 0.05%)与各灯线是通识先验,全部 -- 参数翻案,银行
挂牌永远赢;定期利息按月基(本金×年利率×月数/12,银行整期算法)、活期按天
基(本金×年利率×天数/365),躺亏统一天基,两种基的差异如实披露;不建模按季
结息滚存与靠档计息,realized 对拍容差兜底;不构成投资建议——红灯指向银行
柜台,钱放哪是人的决定;存款保险与风险不在建模范围,这是利率账不是风险账。
零墙钟: as-of 缺省 = 账本最大日期,同一本账任何机器任何一天逐字节一致。

账本(--dir 目录下两份 TSV,renewals 可不存在):
  deposits.tsv   bank/principal/rate/months/start/tag/note   一行一笔存单合同
                 tag 留空 = bank 名;同一银行多笔存单时用 tag 区分,全账唯一
                 realized(可选)= 抄 App 的到账利息合计,validate 激活利息对拍
  renewals.tsv   date/tag/kind/rate/term/note                一行一个主动事件
                 kind = renew(转存定期,rate+term 必填) | withdraw(取走结案)
                 renewals 的 date 早于到期日的 withdraw = 提前支取——通识口径
                 全程按活期重算(不建模靠档),提前支取税由账本看见
"""

import argparse
import calendar as _cal
import os
import re
import sys
from datetime import date, timedelta

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEPOSIT_COLS = ("bank", "principal", "rate", "months", "start", "tag", "note")
RENEWAL_COLS = ("date", "tag", "kind", "rate", "term", "note")

DEMAND_RATE = 0.05   # 活期通识年利率 %(大行 2026 上下挂牌口径),--demand-rate 翻案
RESET_LINE = 0.25    # 转存降档灯线 pp,掉档恰线不亮,--reset-line 翻案
PRIME_LINE = 2.0     # 老合同稀缺灯线 %,恰线不亮,--prime-line 翻案
RED_AMOUNT = 10000   # 躺活期本金红线(元,严格大于才亮),--red-amount 翻案
RED_YEARLY = 1000    # 当前年化躺亏红线(元/年,严格大于才亮),--red-yearly 翻案
CAL_MONTHS = 12      # 到期日历视野(月),--months 翻案
CAL_WINDOW = 30      # 到期决策窗口(天),--window 翻案
BASIS = 365          # 天基计息分母(通识,不建模 366 闰年口径)

EXIT_OK, EXIT_BAD, EXIT_EMPTY, EXIT_RED = 0, 2, 3, 4


class LedgerBad(Exception):
    """账坏——宁可拒绝,不替你编账。"""


class Decline(Exception):
    """拒答——账太薄或缺输入,算术照出,判决不发。"""


# ---------------------------------------------------------------- 几何 ----

def add_months(d, n):
    """原始 day + N 个日历月,对月对日,月末钳制;从原始 day 每次重算,不链式累积。"""
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, min(d.day, _cal.monthrange(y, m)[1]))


def add_months_walk(d, n):
    """第二算法: 前向逐月游走(每步都从原始 day 钳制)——与闭式对拍用。"""
    cur = d
    for _ in range(n):
        y, m = (cur.year + 1, 1) if cur.month == 12 else (cur.year, cur.month + 1)
        cur = date(y, m, min(d.day, _cal.monthrange(y, m)[1]))
    return cur


def parse_date(s, what):
    if not DATE_RE.match(s or ""):
        raise LedgerBad(f"{what} 日期不是 YYYY-MM-DD: {s!r}")
    try:
        return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        raise LedgerBad(f"{what} 日期不存在: {s!r}")


def parse_num(s, what):
    try:
        return float(s)
    except (TypeError, ValueError):
        raise LedgerBad(f"{what} 不是数字: {s!r}")


def parse_int(s, what, minimum=None):
    v = parse_num(s, what)
    iv = int(v)
    if iv != v:
        raise LedgerBad(f"{what} 必须是整数(月): {s!r}")
    if minimum is not None and iv <= minimum:
        raise LedgerBad(f"{what} 必须 > {minimum}: {iv}")
    return iv


def fmt_money(v):
    return f"¥{v:,.2f}"


def fmt_pct(v):
    return f"{v:.3f}%"


def disp_width(s):
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E7F else 1
    return w


def pad(s, width, align="left"):
    gap = width - disp_width(s)
    if gap <= 0:
        return s
    return s + " " * gap if align == "left" else " " * gap + s


# ---------------------------------------------------------------- 载入 ----

def read_tsv(path, cols):
    """手编 TSV: tab 分列,# 注释,空行跳过;缺列 exit 2。返回行字典列表(文件可不存在)。"""
    if not os.path.exists(path):
        return []
    rows = []
    header = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if header is None:
                header = [p.strip() for p in parts]
                missing = [c for c in cols if c not in header]
                if missing:
                    raise LedgerBad(f"{os.path.basename(path)} 缺列: {'、'.join(missing)}")
                continue
            d = {name: (parts[i].strip() if i < len(parts) else "")
                 for i, name in enumerate(header)}
            rows.append(d)
    return rows


def load_ledger(ddir):
    """载入 + 载入层校验(账坏全在这里拦下)。返回 (deposits, renews_by_tag)。

    校验: 缺列/坏日期/负或零本金/负利率/非整数月数/tag 重复/悬空 tag 引用/
    kind 枚举/renew 缺 rate·term/withdraw 带 rate·term/同 tag 同日多事件/
    事件早于存入日/存续期内转存/结案后再动/提前支取与转存同段矛盾。
    """
    dep_rows = read_tsv(os.path.join(ddir, "deposits.tsv"), DEPOSIT_COLS)
    ren_rows = read_tsv(os.path.join(ddir, "renewals.tsv"), RENEWAL_COLS)

    deposits = []
    tags = set()
    for i, r in enumerate(dep_rows, 2):
        if not r.get("bank"):
            raise LedgerBad(f"deposits.tsv 第 {i} 行缺 bank")
        tag = r.get("tag") or r["bank"]
        if tag in tags:
            raise LedgerBad(f"tag 重复: {tag!r}——同一银行多笔存单请用 tag 区分")
        tags.add(tag)
        rate = parse_num(r.get("rate"), f"{tag} 合同利率")
        if rate < 0 or rate > 100:
            raise LedgerBad(f"{tag} 合同利率须在 0..100: {rate}")
        dep = {
            "bank": r["bank"],
            "principal": parse_num(r.get("principal"), f"{tag} 本金"),
            "rate": rate,
            "months": parse_int(r.get("months"), f"{tag} 期限(月)", minimum=0),
            "start": parse_date(r.get("start"), f"{tag} 存入日"),
            "tag": tag,
            "realized": r.get("realized", ""),
            "note": r.get("note", ""),
        }
        if dep["principal"] <= 0:
            raise LedgerBad(f"{tag} 本金必须 > 0: {dep['principal']}")
        deposits.append(dep)

    renews = []
    seen = set()
    for i, r in enumerate(ren_rows, 2):
        tag = r.get("tag") or ""
        kind = r.get("kind") or ""
        if tag not in tags:
            raise LedgerBad(f"renewals.tsv 第 {i} 行引用不存在的存单 tag: {tag!r}")
        if kind not in ("renew", "withdraw"):
            raise LedgerBad(f"renewals.tsv 第 {i} 行 kind 必须是 renew/withdraw: {kind!r}")
        rn = {"date": parse_date(r.get("date"), f"{tag} 事件日"), "tag": tag,
              "kind": kind, "rate": None, "term": None, "note": r.get("note", "")}
        if kind == "renew":
            if not r.get("rate"):
                raise LedgerBad(f"renewals.tsv 第 {i} 行 renew 缺 rate(转存年利率)")
            if not r.get("term"):
                raise LedgerBad(f"renewals.tsv 第 {i} 行 renew 缺 term(转存期限/月)")
            rr = parse_num(r.get("rate"), f"{tag} 转存利率")
            if rr < 0 or rr > 100:
                raise LedgerBad(f"{tag} 转存利率须在 0..100: {rr}")
            rn["rate"], rn["term"] = rr, parse_int(r.get("term"), f"{tag} 转存期限", minimum=0)
        elif r.get("rate") or r.get("term"):
            raise LedgerBad(f"renewals.tsv 第 {i} 行 withdraw 不带 rate/term——取走就是取走")
        key = (tag, rn["date"])
        if key in seen:
            raise LedgerBad(f"{tag} 在 {rn['date']} 有多笔事件——同日二义,账本不替你挑")
        seen.add(key)
        renews.append(rn)

    renews.sort(key=lambda e: (e["tag"], e["date"], e["kind"]))
    by_tag = {}
    for rn in renews:
        by_tag.setdefault(rn["tag"], []).append(rn)

    # 逐 tag 全史行走(与 as-of 无关的一致性校验)
    by_dep = {d["tag"]: d for d in deposits}
    for tag, evs in by_tag.items():
        dep = by_dep[tag]
        maturity = add_months(dep["start"], dep["months"])
        cur_end = maturity
        closed = False
        for e in evs:
            if closed:
                raise LedgerBad(f"{tag} 已于 {cur_end if False else e['date']} 之前取走,"
                                f"{e['date']} 又有事件——取走的钱不能再动")
            if e["date"] < dep["start"]:
                raise LedgerBad(f"{tag} 在 {e['date']} 的事件早于存入日 {dep['start']}")
            if e["kind"] == "renew" and e["date"] < cur_end:
                raise LedgerBad(f"{tag} 在 {e['date']} 的转存落在存续期内(段起点 {cur_end})——"
                                f"存续期内不能转存,急用钱是提前支取(withdraw)")
            if e["kind"] == "withdraw":
                closed = True
            else:
                cur_end = add_months(e["date"], e["term"])
    return deposits, by_tag


# ---------------------------------------------------------------- 时间线 ----

def build_segments(dep, renews, as_of, demand_rate):
    """一笔存单的利率时间线(as-of 截断;as-of 之前未发生的事件是还没写下的未来)。

    段 = dict(t0, t1, rate, kind, label, months)
      kind: contract(合同) | gap(沉默=活期) | renew(转存定期) | early(提前支取=全程活期)
    返回 (segments, closed_at or None, early_bool);as_of <= start 返回空表。
    """
    start = dep["start"]
    maturity = add_months(start, dep["months"])
    if as_of < start:
        return [], None, False

    evs = [e for e in renews.get(dep["tag"], []) if e["date"] <= as_of]

    # 提前支取: 结算日早于到期日(载入层已保证它之前无存续期转存)
    for e in evs:
        if e["kind"] == "withdraw" and e["date"] < maturity:
            segs = [{"t0": start, "t1": e["date"], "rate": demand_rate,
                     "kind": "early", "label": "提前支取=活期", "months": None}]
            return segs, e["date"], True

    segs = [{"t0": start, "t1": min(maturity, as_of), "rate": dep["rate"],
             "kind": "contract", "label": "合同", "months": dep["months"]}]
    if as_of <= maturity:
        return segs, None, False

    t = maturity
    closed_at = None
    for e in evs:
        if closed_at is not None:
            break
        if e["kind"] == "withdraw":
            if e["date"] > t:
                segs.append({"t0": t, "t1": e["date"], "rate": demand_rate,
                             "kind": "gap", "label": "沉默=活期", "months": None})
            closed_at = e["date"]
            break
        # renew(date >= maturity 由载入层保证)
        if e["date"] > t:
            segs.append({"t0": t, "t1": e["date"], "rate": demand_rate,
                         "kind": "gap", "label": "沉默=活期", "months": None})
        seg_end = add_months(e["date"], e["term"])
        segs.append({"t0": e["date"], "t1": min(seg_end, as_of), "rate": e["rate"],
                     "kind": "renew", "label": f"转存{e['term']}月", "months": e["term"]})
        if as_of <= seg_end:
            return segs, closed_at, False
        t = seg_end
    if closed_at is None:
        segs.append({"t0": t, "t1": as_of, "rate": demand_rate,
                     "kind": "gap", "label": "沉默=活期", "months": None})
    return segs, closed_at, False


def seg_days(seg):
    return (seg["t1"] - seg["t0"]).days


def seg_interest(seg, principal):
    """段利息:定期段整期满按月基(银行算法),活期段与被截断段按天基。"""
    days = seg_days(seg)
    if days <= 0:
        return 0.0
    full = seg.get("months")
    if full is not None and seg["t1"] == add_months(seg["t0"], full):
        return principal * seg["rate"] / 100 * full / 12
    return principal * seg["rate"] / 100 * days / BASIS


def seg_loss(seg, principal, contract_rate):
    """段躺亏(统一天基): 锚 = 本笔原合同利率;合同段与利率反超段为 0。"""
    days = seg_days(seg)
    if days <= 0 or seg["kind"] == "contract":
        return 0.0
    drop = contract_rate - seg["rate"]
    if drop <= 0:
        return 0.0
    return principal * drop / 100 * days / BASIS


# ---------------------------------------------------------------- 视图 ----

def state_of(dep, segs, as_of, closed_at, early):
    """状态桶: INTACT / DEMAND / RENEWED / WITHDRAWN / WITHDRAWN-EARLY。"""
    if not segs:
        return "FUTURE"
    if early:
        return "WITHDRAWN-EARLY"
    if as_of <= add_months(dep["start"], dep["months"]):
        return "INTACT"
    if closed_at is not None:
        return "WITHDRAWN"
    last = segs[-1]
    if last["kind"] == "gap" and last["t1"] == as_of:
        return "DEMAND"
    if last["kind"] == "renew" and last["t1"] == as_of:
        return "RENEWED"
    return "WITHDRAWN"


def max_reset(dep, segs):
    best = None
    for s in segs:
        if s["kind"] == "renew":
            drop = dep["rate"] - s["rate"]
            if best is None or drop > best[0]:
                best = (drop, s)
    return best


def collect(deposits, renews, as_of, demand_rate, reset_line):
    """逐笔汇总(保持账本行序)。"""
    out = []
    for dep in deposits:
        segs, closed_at, early = build_segments(dep, renews, as_of, demand_rate)
        state = state_of(dep, segs, as_of, closed_at, early)
        last = segs[-1] if segs else None
        sleeping = state == "DEMAND"
        open_yearly = 0.0
        if sleeping:
            drop = dep["rate"] - last["rate"]
            if drop > 0:
                open_yearly = dep["principal"] * drop / 100
        out.append({
            "dep": dep, "segs": segs, "closed_at": closed_at, "early": early,
            "interest": sum(seg_interest(s, dep["principal"]) for s in segs),
            "loss": sum(seg_loss(s, dep["principal"], dep["rate"]) for s in segs),
            "state": state, "sleeping": sleeping, "open_loss_yearly": open_yearly,
        })
    return out


def ledger_max_date(deposits, renews):
    """as-of 缺省 = 账本最大日期(零墙钟)。空账拒答。"""
    ds = [d["start"] for d in deposits] + [e["date"] for evs in renews.values() for e in evs]
    if not ds:
        raise Decline("账本是空的——抄第一笔存单进 deposits.tsv"
                      "(bank/本金/利率/期限/存入日,一行一笔)")
    return max(ds)


def visible(deposits, as_of):
    """as-of 截断: start > as_of 的存单是还没写下的未来,排除并披露。"""
    return ([d for d in deposits if d["start"] <= as_of],
            [d for d in deposits if d["start"] > as_of])


def future_events(renews, as_of):
    out = []
    for tag in sorted(renews):
        for e in renews[tag]:
            if e["date"] > as_of:
                out.append(e)
    return out


# ---------------------------------------------------------------- 输出 ----

STATE_LABEL = {
    "INTACT": "在保", "DEMAND": "躺活期", "RENEWED": "转存存续",
    "WITHDRAWN": "已取走", "WITHDRAWN-EARLY": "提前支取",
}


def _header(ddir, as_of, explicit, demand_rate):
    print(f"躺亏 · Dormant Loss —— {os.path.basename(os.path.normpath(ddir))}")
    src = "账本最大日期,零墙钟" if not explicit else "--as-of 钉死"
    print(f"as-of: {as_of} ({src}) · 活期通识 {fmt_pct(demand_rate)} "
          f"(--demand-rate 可翻案) · 躺亏锚 = 本笔原合同利率,零外部先验")


def _disclose_future(future_deps, futs):
    if future_deps:
        print("  未来行(" + "、".join(f"{d['bank']}({d['start']})" for d in future_deps)
              + ")在 as-of 之后,排除不是账坏——还没写下的未来")
    if futs:
        print("  未来事件(" + "、".join(f"{e['tag']} {e['date']} {e['kind']}" for e in futs)
              + ")在 as-of 之后,排除不是账坏")


# ---------------------------------------------------------------- 命令 ----

def cmd_report(args, deposits, renews):
    as_of = args.as_of or ledger_max_date(deposits, renews)
    in_scope, future_deps = visible(deposits, as_of)
    if not in_scope:
        raise Decline("as-of 之前没有任何存单在账——Nothing to audit")
    rows = collect(in_scope, renews, as_of, args.demand_rate, args.reset_line)
    futs = future_events(renews, as_of)

    _header(args.dir, as_of, args.as_of is not None, args.demand_rate)
    print()
    print("■ 存单总账")
    print("  " + pad("存单", 10) + pad("本金", 10) + pad("合同%", 8) + pad("期限", 6)
          + pad("存入日", 11) + pad("到期日", 11) + pad("现执行%", 8)
          + pad("掉档", 7) + pad("累计躺亏", 12) + "状态")
    for r in rows:
        dep, last = r["dep"], (r["segs"][-1] if r["segs"] else None)
        cur_rate = last["rate"] if last else dep["rate"]
        drop = max(0.0, dep["rate"] - cur_rate)
        extra = ""
        if r["state"] == "DEMAND":
            extra = f"(静默{seg_days(last)}天)"
        elif r["state"] == "RENEWED" and max_reset(dep, r["segs"]):
            extra = "(降档存续)"
        elif r["state"] == "WITHDRAWN-EARLY":
            left = (add_months(dep["start"], dep["months"]) - r["closed_at"]).days
            extra = f"(差{left}天到期)"
        print("  " + pad(dep["bank"], 10) + pad(f"{dep['principal']:,.0f}", 10)
              + pad(fmt_pct(dep["rate"]), 8) + pad(f"{dep['months']}月", 6)
              + pad(str(dep["start"]), 11) + pad(str(add_months(dep["start"], dep["months"])), 11)
              + pad(fmt_pct(cur_rate), 8) + pad(f"{drop:.2f}pp", 7)
              + pad(fmt_money(r["loss"]), 12) + STATE_LABEL[r["state"]] + extra)
    sleeping = [r for r in rows if r["state"] == "DEMAND"]
    intact = [r for r in rows if r["state"] == "INTACT"]
    total_loss = sum(r["loss"] for r in rows)
    yearly = sum(r["open_loss_yearly"] for r in rows)
    sleeping_amt = sum(r["dep"]["principal"] for r in sleeping)
    print(f"  小计: 在账 {len(rows)} 笔 {sum(r['dep']['principal'] for r in rows):,.0f} 元 · "
          f"躺活期 {len(sleeping)} 笔 {sleeping_amt:,.0f} 元 · "
          f"在保 {len(intact)} 笔 {sum(r['dep']['principal'] for r in intact):,.0f} 元")
    print(f"  躺亏合计(到期至今): {fmt_money(total_loss)}   "
          f"当前年化速率: {fmt_money(yearly)}/年 = {fmt_money(yearly / BASIS)}/天")
    _disclose_future(future_deps, futs)

    lamps = []
    if sleeping and (sleeping_amt > args.red_amount or yearly > args.red_yearly):
        why = []
        if sleeping_amt > args.red_amount:
            why.append(f"躺活期 {sleeping_amt:,.0f} 元 > 线 {args.red_amount:,.0f}")
        if yearly > args.red_yearly:
            why.append(f"年化 {fmt_money(yearly)} > 线 {args.red_yearly:,.0f}")
        lamps.append(("red", "SLEEPING-DEMAND",
                      ";".join(why) + f" (--red-amount/--red-yearly)——沉默就是活期,"
                      f"每一天都在按 {fmt_pct(args.demand_rate)} 跑,decide --rate 对拍一下再决定"))
    resets = []
    for r in rows:
        if r["state"] in ("DEMAND", "RENEWED"):
            m = max_reset(r["dep"], r["segs"])
            if m and m[0] > args.reset_line:
                resets.append((r["dep"], m))
    if resets:
        detail = ";".join(f"{d['bank']} {s['t0']} 转存 {fmt_pct(s['rate'])} 比原合同 "
                          f"{fmt_pct(d['rate'])} 掉 {drop:.2f}pp"
                          for d, (drop, s) in resets)
        lamps.append(("yellow", "RESET-DOWN",
                      detail + "——「转存了」不等于「安全了」,转存价是银行的默认价不是你的价"))
    for r in rows:
        if r["state"] == "WITHDRAWN-EARLY":
            left = (add_months(r["dep"]["start"], r["dep"]["months"]) - r["closed_at"]).days
            lamps.append(("yellow", "EARLY-TAX",
                          f"{r['dep']['bank']} 提前 {left} 天取走,全程按活期重算——"
                          f"提前支取税 {fmt_money(r['loss'])} 躺账本看见"))
    primes = [r for r in intact if r["dep"]["rate"] > args.prime_line]
    if primes:
        detail = ";".join(f"{r['dep']['bank']} {fmt_pct(r['dep']['rate'])} 合同期内"
                          f"(到 {add_months(r['dep']['start'], r['dep']['months'])})"
                          for r in primes)
        lamps.append(("blue", "PRIME-HOLD",
                      detail + "——利率下行时代的老合同是稀缺资产,提前支取按活期,锁住它"))
    if lamps:
        print("灯:")
        for kind, name, text in lamps:
            mark = {"red": "🔴", "yellow": "🟡", "blue": "🔵"}[kind]
            print(f"  {mark} {name}  {text}")
    else:
        print("灯: 无——每一笔都在合同价上,或已体面结案")
    print()
    print("下一步: timeline(利率时间线) · calendar(到期日历) · "
          "decide --rate 报价(转存对拍) · validate(体检)")
    return EXIT_RED if any(k == "red" for k, _, _ in lamps) else EXIT_OK


def cmd_timeline(args, deposits, renews):
    as_of = args.as_of or ledger_max_date(deposits, renews)
    in_scope, future_deps = visible(deposits, as_of)
    if not in_scope:
        raise Decline("as-of 之前没有任何存单在账")
    rows = collect(in_scope, renews, as_of, args.demand_rate, args.reset_line)
    futs = future_events(renews, as_of)

    _header(args.dir, as_of, args.as_of is not None, args.demand_rate)
    print(f"利率时间线 · 沉默就是活期:事件之间的空白按 {fmt_pct(args.demand_rate)} 补齐")
    total_loss = 0.0
    for r in rows:
        dep = r["dep"]
        note = f"  {dep['note']}" if dep["note"] else ""
        print()
        print(f"■ {dep['bank']}  {dep['principal']:,.0f} 元 @{fmt_pct(dep['rate'])} × "
              f"{dep['months']}月 ({dep['start']} → "
              f"{add_months(dep['start'], dep['months'])}){note}")
        for s in r["segs"]:
            inter = seg_interest(s, dep["principal"])
            loss = seg_loss(s, dep["principal"], dep["rate"])
            total_loss += loss
            mark = f"  ←躺亏 {fmt_money(loss)}" if loss > 0.005 else ""
            print(f"  {s['t0']} .. {s['t1']}  {pad(fmt_pct(s['rate']), 8)} "
                  f"{pad(s['label'], 14)} {seg_days(s):>5} 天  利息 {fmt_money(inter)}{mark}")
        print(f"  小计: 利息 {fmt_money(r['interest'])} · 躺亏 {fmt_money(r['loss'])} "
              f"(锚 = 原合同 {fmt_pct(dep['rate'])},这笔钱曾经值的价格)")
    print()
    _disclose_future(future_deps, futs)
    print(f"全部存单躺亏合计: {fmt_money(total_loss)}——数字从这里开始,决定从银行柜台开始")
    return EXIT_OK


def cmd_calendar(args, deposits, renews):
    as_of = args.as_of or ledger_max_date(deposits, renews)
    in_scope, future_deps = visible(deposits, as_of)
    rows = collect(in_scope, renews, as_of, args.demand_rate, args.reset_line)
    horizon_end = add_months(as_of, args.months)

    _header(args.dir, as_of, args.as_of is not None, args.demand_rate)
    print(f"到期日历 · 视野 {args.months} 个月 → {horizon_end}")
    print(f"  每个到期日都是一笔钱的「私人降息日」:到期不办,银行替你选最低价"
          f"(沉默=活期 {fmt_pct(args.demand_rate)})")
    items = []
    for r in rows:
        dep = r["dep"]
        for s in r["segs"]:
            if s["kind"] in ("contract", "renew") and s.get("months"):
                due = add_months(s["t0"], s["months"])
                if as_of < due <= horizon_end:
                    items.append((due, dep, s))
    items.sort(key=lambda x: (x[0], x[1]["bank"]))
    if items:
        for due, dep, s in items:
            drop = dep["rate"] - args.demand_rate
            prime = " 🔵PRIME" if dep["rate"] > args.prime_line else ""
            print(f"  {due}  {pad(dep['bank'], 10)} {dep['principal']:>9,.0f} 元  "
                  f"{s['label']}到期  {fmt_pct(s['rate'])} → 无转存预告 → 活期 "
                  f"{fmt_pct(args.demand_rate)}(掉 {drop:.2f}pp){prime}")
    else:
        print("  视野内无到期——但这不等于无事发生(见下)")
    near = [it for it in items if 0 <= (it[0] - as_of).days <= args.window]
    if near:
        print(f"  决策窗口(未来 {args.window} 天):"
              + "、".join(f"{d['bank']} {due}" for due, d, _ in near)
              + " ——到期前办好转存或预约取,沉默从到期次日始")
    else:
        print(f"  决策窗口(未来 {args.window} 天):无到期。")
    sleeping = [r for r in rows if r["state"] == "DEMAND"]
    if sleeping:
        detail = "、".join(f"{r['dep']['bank']} {r['dep']['principal']:,.0f} 元 已躺 "
                          f"{seg_days(r['segs'][-1])} 天" for r in sleeping)
        yearly = sum(r["open_loss_yearly"] for r in sleeping)
        print(f"  正在发生的降息(无需等到期,现在就能办): {detail}")
        print(f"    ——这 {len(sleeping)} 笔合计年化 {fmt_money(yearly)},"
              f"日亏 {fmt_money(yearly / BASIS)};decide --rate 抄一个真实报价来对拍")
    _disclose_future(future_deps, future_events(renews, as_of))
    return EXIT_OK


def cmd_decide(args, deposits, renews):
    as_of = args.as_of or ledger_max_date(deposits, renews)
    in_scope, _ = visible(deposits, as_of)
    rows = collect(in_scope, renews, as_of, args.demand_rate, args.reset_line)
    if args.rate is None:
        raise Decline("decide 需要 --rate:抄银行 App/柜台的真实报价(%),账本不发明市场行情")
    if args.term <= 0:
        raise Decline("--term 必须 > 0(月)")
    sleeping = [r for r in rows if r["state"] == "DEMAND"]
    if not sleeping:
        raise Decline("没有躺活期的钱可对拍——decide 的对象是 DEMAND 段的本金")
    total_sleep = sum(r["dep"]["principal"] for r in sleeping)
    movable = total_sleep - args.liquid
    if movable <= 0:
        raise Decline(f"躺活期 {total_sleep:,.0f} 元全部留作活期"
                      f"(--liquid {args.liquid:,.0f})——没有可转存的钱")

    end = add_months(as_of, args.term)
    days = (end - as_of).days
    world_a = movable * args.rate / 100 * args.term / 12
    world_b = movable * args.demand_rate / 100 * days / BASIS
    diff = world_a - world_b

    _header(args.dir, as_of, args.as_of is not None, args.demand_rate)
    print(f"转存对拍 · 新报价 {fmt_pct(args.rate)} × {args.term} 月 (--rate/--term 可换)")
    print(f"  对象: 躺活期 {total_sleep:,.0f} 元 − 留活期 {args.liquid:,.0f} (--liquid) "
          f"= {movable:,.0f} 元")
    for r in sleeping:
        dep = r["dep"]
        print(f"    · {dep['bank']} {dep['principal']:,.0f} 元(原合同 {fmt_pct(dep['rate'])},"
              f"现按 {fmt_pct(args.demand_rate)},已躺 {seg_days(r['segs'][-1])} 天)")
    keep = [r for r in rows if r["state"] in ("INTACT", "RENEWED")]
    if keep:
        print("  排除: " + "、".join(f"{r['dep']['bank']} {fmt_pct(r['dep']['rate'])}"
                                    for r in keep) + " ——定期存续期内,提前支取按活期,别动")
    print(f"  世界 A: {as_of} 存 {args.term} 月 @{fmt_pct(args.rate)} → 到期 {end},"
          f"利息 {fmt_money(world_a)}(月基)")
    print(f"  世界 B: 继续躺活期同窗 {days} 天 → 利息 {fmt_money(world_b)}(天基)")
    print(f"  差额: {fmt_money(diff)}(每年 {fmt_money(diff * 12 / args.term)}"
          f" ——不动的代价是每天 {fmt_money(diff / days)})")
    print(f"  {end} 又是一个决策点——写进日历;沉默的每一天,银行都替你选最低价")
    return EXIT_OK


def cmd_validate(args, deposits, renews):
    as_of = args.as_of or ledger_max_date(deposits, renews)
    in_scope, future_deps = visible(deposits, as_of)
    if not in_scope:
        raise Decline("as-of 之前没有任何存单在账")
    rows = collect(in_scope, renews, as_of, args.demand_rate, args.reset_line)

    print(f"账本体检 —— {os.path.basename(os.path.normpath(args.dir))} (as-of {as_of})")
    ok = True

    # 1) 躺亏双算法: 分段闭式 == 逐日积分
    closed_total = sum(r["loss"] for r in rows)
    daily_total = 0.0
    n_seg_days = 0
    for r in rows:
        dep = r["dep"]
        for s in r["segs"]:
            d = seg_days(s)
            n_seg_days += d
            drop = dep["rate"] - s["rate"]
            if s["kind"] == "contract" or drop <= 0:
                continue
            for i in range(d):
                daily_total += dep["principal"] * drop / 100 / BASIS
    if abs(closed_total - daily_total) > 1e-6:
        print(f"  躺亏双算法: 分段闭式 {closed_total:.6f} != 逐日积分 {daily_total:.6f} ✗")
        ok = False
    else:
        print(f"  躺亏双算法: 分段闭式 == 逐日积分 ({len(rows)} 笔 · {n_seg_days} 段·日) ✓")

    # 2) 到期日几何: 闭式 == 逐月前向游走(全部存单与转存段)
    geom_n = 0
    geom_ok = True
    for dep in deposits:
        for n in (dep["months"],):
            if add_months(dep["start"], n) != add_months_walk(dep["start"], n):
                geom_ok = False
            geom_n += 1
    for evs in renews.values():
        for e in evs:
            if e["kind"] == "renew":
                if add_months(e["date"], e["term"]) != add_months_walk(e["date"], e["term"]):
                    geom_ok = False
                geom_n += 1
    print(f"  到期日几何: 对月对日+月末钳制,闭式 == 逐月游走 ({geom_n} 个期限, "
          f"含闰日起点 {sum(1 for d in deposits if d['start'].month == 2 and d['start'].day == 29)} 笔) "
          f"{'✓' if geom_ok else '✗'}")
    ok = ok and geom_ok

    # 3) 时间线连续: 段首尾相接(载入层已拦倒置/重叠, 此处复核 as-of 截断后仍连续)
    cont_ok = True
    for r in rows:
        prev = None
        for s in r["segs"]:
            if prev is not None and s["t0"] != prev["t1"]:
                cont_ok = False
            prev = s
    print(f"  时间线连续: 段首尾相接 ({sum(len(r['segs']) for r in rows)} 段) "
          f"{'✓' if cont_ok else '✗'}")
    ok = ok and cont_ok

    # 4) realized 利息对拍: 抄的到账利息 vs 时间线重放(容差 = max(1分, 应得×0.5%))
    checked = 0
    for r in rows:
        claimed = (r["dep"].get("realized") or "").strip()
        if claimed == "":
            continue
        checked += 1
        expect = r["interest"]
        got = parse_num(claimed, f"{r['dep']['tag']} realized")
        tol = max(0.01, abs(expect) * 0.005)
        if abs(expect - got) > tol:
            print(f"  {r['dep']['bank']} 利息对拍: 应得 {fmt_money(expect)} vs 抄账 "
                  f"{fmt_money(got)} (差 {abs(expect - got):,.2f} > 容差 {tol:,.2f}) "
                  f"✗ GHOST——抄错了,或有账本看不见的利息")
            ok = False
        else:
            print(f"  {r['dep']['bank']} 利息对拍: 应得 {fmt_money(expect)} vs 抄账 "
                  f"{fmt_money(got)} (差 {abs(expect - got):,.2f}) ✓")
    if checked == 0:
        print("  利息对拍: realized 列全空,跳过——抄 App 的到账利息可激活验钞")
    _disclose_future(future_deps, future_events(renews, as_of))

    if ok:
        print("\n体检 全部通过 ✓——账坏 exit 2 在载入层就已拦下"
              "(缺列/坏日期/悬空 tag/存续期转存/结案后再动/同日二义)")
        return EXIT_OK
    print("\n体检 未通过 ✗")
    return EXIT_BAD


# ---------------------------------------------------------------- main ----

def main(argv=None):
    ap = argparse.ArgumentParser(description="躺亏 · Dormant Loss — 存款利率的掉档账本")
    ap.add_argument("--dir", default=".", help="账本目录(缺省当前目录)")
    ap.add_argument("--as-of", dest="as_of", default=None,
                    help="钉死 as-of 日期(缺省=账本最大日期)")
    ap.add_argument("--demand-rate", type=float, default=DEMAND_RATE,
                    help="活期通识年利率%% (缺省 0.05)")
    ap.add_argument("--reset-line", type=float, default=RESET_LINE,
                    help="转存降档灯线 pp (缺省 0.25)")
    ap.add_argument("--prime-line", type=float, default=PRIME_LINE,
                    help="老合同稀缺灯线%% (缺省 2.0)")
    ap.add_argument("--red-amount", dest="red_amount", type=float, default=RED_AMOUNT,
                    help="躺活期本金红线元 (缺省 10000)")
    ap.add_argument("--red-yearly", dest="red_yearly", type=float, default=RED_YEARLY,
                    help="年化躺亏红线元 (缺省 1000)")
    ap.add_argument("--months", type=int, default=CAL_MONTHS,
                    help="calendar 视野月 (缺省 12)")
    ap.add_argument("--window", type=int, default=CAL_WINDOW,
                    help="决策窗口天 (缺省 30)")
    ap.add_argument("--rate", type=float, default=None, help="decide: 新报价年利率%%")
    ap.add_argument("--term", type=int, default=36, help="decide: 新存期限月 (缺省 36)")
    ap.add_argument("--liquid", type=float, default=0.0, help="decide: 留活期金额 (缺省 0)")
    ap.add_argument("command", nargs="?", default="report",
                    choices=["report", "timeline", "calendar", "decide", "validate"])
    args = ap.parse_args(argv)

    if args.as_of is not None:
        args.as_of = parse_date(args.as_of, "--as-of")

    try:
        deposits, renews = load_ledger(args.dir)
        if args.command == "report":
            return cmd_report(args, deposits, renews)
        if args.command == "timeline":
            return cmd_timeline(args, deposits, renews)
        if args.command == "calendar":
            return cmd_calendar(args, deposits, renews)
        if args.command == "decide":
            return cmd_decide(args, deposits, renews)
        if args.command == "validate":
            return cmd_validate(args, deposits, renews)
    except LedgerBad as e:
        print(f"账坏: {e}", file=sys.stderr)
        return EXIT_BAD
    except Decline as e:
        print(f"拒答: {e}", file=sys.stderr)
        return EXIT_EMPTY
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
