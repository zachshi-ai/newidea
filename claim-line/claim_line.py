#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报险线 · Claim Line

报保险的标价是 ¥0——保险公司付的；它的真实价格写在你未来 2–5 年的续保单里：
无赔款优待（NCD）是一段攒出来的折扣，一次 own 赔案把它烧掉，再用同样多的
年份一档一档爬回来。这笔隐身账单没有人在出险当场替你算，于是小事报险的人
第二年对着跳涨的保费喊「莫名其妙」，大事自掏的人垫了几千块还以为自己精明。
民间只有一句常数口诀（「2000 以下别报」），但自费线从来不是常数，它是你
保费的函数——保费越高、折扣位越深的人，越报不起小险。

claim-line keeps that ledger by hand (two TSV files):

  report    — 历史审计：逐笔报险的真实价格定价单、已付隐身保费、
              恢复期尾款、冤案榜（OVERCLAIM）
  decide    — 出险当场裁决：自费线 = 再报一笔的边际隐身保费；
              CASH / CLAIM / TIE / CTP / OTHERS 五种活法摆上台面
  renewal   — 续保预演：下次续保将付多少、比无赔世界多付多少、
              尾款记在哪笔出险头上
  simulate  — 反事实沙盒：cash / claim / ctp / never-claim 四种活法的
              恢复期总账，恒 exit 0，沙盒不执法
  validate  — 账本体检：路径恒等式、边际可加恒等式、状态机自查、
              NCD 列与出险史对质

Method in one line: 自费线 = Σ(报险路径 NCD − 无赔路径 NCD) × 基准保费，
两条路径在恢复期结束处必然重合——重合之前的差，就是那笔报险的全价。

The three facts the folk wisdom misses:
  1. 第 1 次报险烧掉整段折扣（深折扣位上 ≈ 1.05× 基准保费），之后的报险
     只是固定加罚（每步 +0.25× 基准）——「反正今年已经出过险，小事就报吧」
     第一次有了算术依据；
  2. 反过来折扣在重新攒：等一年再报同一笔，隐身价翻倍——「等等再报」
     不是拖延，是在涨价之前锁定；
  3. 无责赔案根本不进你的账本（你的保险公司没付钱，就没有赔款记录）；
     小额财产损失走交强险（浮动独立于商业 NCD、幅度小一个量级）——
     对方的保险和交强险，是这本账里的两个免费出口。

Exit codes: 0 绿 · 2 账本损坏/用法错误 · 3 账太薄拒绝判级（算术照出）·
4 红灯（CASH / OVERCLAIM）

Zero dependencies: Python 3.8+ standard library. 全件无墙钟：缺省
as-of = 账本末日，--as-of 钉死，同一本账任何机器任何一天逐字节一致。
报告只打印 basename，本地计算不连任何接口。

MIT License (c) 2026
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

EXIT_OK = 0
EXIT_LEDGER = 2
EXIT_THIN = 3
EXIT_RED = 4

PROG = "claim-line"
VERSION = "1.0"
EPS = 1e-9

# ---------------------------------------------------------------- priors
# NCD 先验表（2020 商车综改行业示范口径，通识先验不是监管文本；
# --ncd-sur/--ncd-dis 整表可覆盖，你的保单/续保报价永远赢）。
DEFAULT_NCD_SUR = (1.00, 1.25, 1.50, 1.75, 2.00)   # 上年 own 赔案 1..5+ 次
DEFAULT_NCD_DIS = (0.85, 0.70, 0.60, 0.50)         # 连续无赔 1..4+ 年
# 交强险费率浮动（独立于商业 NCD；基准 950，--ctp-* 可调）
DEFAULT_CTP_DIS = (-0.10, -0.20, -0.30)            # 连续无有责事故 1..3+ 年
DEFAULT_CTP_SUR = (0.00, 0.10)                     # 上年 1 次 / 2+ 次有责
CTP_BASE_DEFAULT = 950.0
CTP_LIMIT_DEFAULT = 2000.0     # 交强有责财产损失赔偿限额
CTP_CLEAN_DEFAULT = 3          # 交强无账本，默认按满折位假设（最保守）

HEADER_POLICIES = ["start", "premium", "ncd", "note"]
HEADER_CLAIMS = ["date", "fault", "channel", "cost", "note"]
FAULTS = ("mine", "other")
CHANNELS = ("own", "ctp", "other", "cash")

CHANNEL_NAMES = {"own": "商业险", "ctp": "交强险",
                 "other": "对方保险", "cash": "自费"}
FAULT_NAMES = {"mine": "有责", "other": "无责"}

OVERCLAIM_LINE_DEFAULT = 3.0   # 全价 > 3× 维修费 → 冤案 OVERCLAIM
BAND_DEFAULT = 0.10            # 自费线 ±10% 掷币带
RECOVERY_CAP = 12              # 路径投影上限年数（远超恢复期，自检用）
BASE_WILD_RATIO = 1.15         # 隐含基准保费 max/min 超此 → WILD-BASE 横幅


class LedgerError(Exception):
    """exit 2"""


class ThinError(Exception):
    """exit 3"""


# ---------------------------------------------------------------- helpers

def fmt_money(v):
    return "{:,.2f}".format(v)


def fmt_pct(v, nd=1):
    return "{:.{}f}%".format(v * 100, nd)


def fmt_ratio(v):
    return "{:.2f}x".format(v)


def parse_num(text, field):
    try:
        return float(str(text).strip().replace(",", "").replace("¥", ""))
    except (TypeError, ValueError):
        raise LedgerError("bad {}: {!r}".format(field, text))


def parse_date(text, field):
    try:
        return date.fromisoformat(str(text).strip())
    except (TypeError, ValueError):
        raise LedgerError("bad {} (YYYY-MM-DD): {!r}".format(field, text))


def parse_ratio(text, field):
    """NCD 系数：0.70 或 70% 双写法。"""
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


def parse_floats(text, field, count):
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != count:
        raise LedgerError("--{}: expected {} comma-separated values, got {}"
                          .format(field, count, len(parts)))
    try:
        vals = tuple(float(p) for p in parts)
    except ValueError:
        raise LedgerError("bad --{}: {!r}".format(field, text))
    return vals


def add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:            # 2-29
        return d.replace(year=d.year + n, month=2, day=28)


def display_width(s):
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def pad(s, width):
    gap = width - display_width(s)
    return s + " " * max(gap, 1)


def print_row(cells):
    print("  " + "".join(pad(str(c), w) for c, w in cells))


def base_name(path):
    return os.path.basename(path)


# ---------------------------------------------------------------- engine

class SurDis:
    """一张 (加罚表, 折扣表) 费率浮动状态机。

    状态 = (clean, claims)：clean = 最近一次续保时已完成的连续无赔年数
    （封顶 dis 表深），claims = 当前保单年内已发生的 own 赔案数。
    一次续保的系数：claims≥1 → sur[claims]（封顶）；否则折扣表取
    「含刚结束这年在内的连续无赔年数」= clean+1（封顶）。
    """

    def __init__(self, sur, dis, name="NCD"):
        for a, b in zip(sur, sur[1:]):
            if b <= a:
                raise LedgerError("{} surcharge table must strictly "
                                  "increase: {}".format(name, sur))
        for a, b in zip(dis, dis[1:]):
            if b >= a:
                raise LedgerError("{} discount table must strictly "
                                  "decrease: {}".format(name, dis))
        self.sur = tuple(float(x) for x in sur)
        self.dis = tuple(float(x) for x in dis)
        self.name = name

    def lookup(self, clean, claims):
        if claims >= 1:
            return self.sur[min(claims, len(self.sur)) - 1]
        return self.dis[min(clean + 1, len(self.dis)) - 1]

    def rollover(self, state):
        """保单年滚动：本年 own 赔案 ≥1 → 连无赔清零；否则 +1（封顶）。"""
        clean, claims = state
        if claims >= 1:
            return (0, 0)
        return (min(clean + 1, len(self.dis)), 0)

    def project(self, state, horizon):
        out, st = [], state
        for _ in range(horizon):
            out.append(self.lookup(*st))
            st = self.rollover(st)
        return out

    def uplift_path(self, state):
        """现在多报一笔：未来各续保年 (报险路径 − 无赔路径) 的系数差，
        到两路径状态重合为止。返回 (per_year_diffs, horizon)，
        horizon = 有正差额的年数（恢复期）。"""
        st_clean, st_claim = state, (state[0], state[1] + 1)
        diffs = []
        for _ in range(RECOVERY_CAP):
            if st_clean == st_claim:
                break
            diffs.append(self.lookup(*st_claim) - self.lookup(*st_clean))
            st_clean, st_claim = self.rollover(st_clean), self.rollover(st_claim)
        while diffs and abs(diffs[-1]) < EPS:
            diffs.pop()
        return diffs, len(diffs)

    def hidden_bill(self, state, base):
        diffs, horizon = self.uplift_path(state)
        return sum(diffs) * base, diffs, horizon

    def reverse(self, coef):
        """NCD 系数 → 续保时点状态。1.0 有歧义（新保 / 上年 1 次），
        锚定语义取新保 (0, 0)。"""
        for i, v in enumerate(self.sur, 1):
            if abs(coef - v) < 1e-6:
                return (0, i)
        for i, v in enumerate(self.dis, 1):
            if abs(coef - v) < 1e-6:
                return (i, 0)
        if abs(coef - 1.0) < 1e-6:
            return (0, 0)
        raise LedgerError(
            "{} coefficient {!r} not in the table (sur {} / dis {}); "
            "leave it empty or use a table coefficient".format(
                self.name, coef,
                "/".join(str(x) for x in self.sur),
                "/".join(str(x) for x in self.dis)))


# ---------------------------------------------------------------- reading

def read_tsv(path, header, parser):
    if not os.path.exists(path):
        raise LedgerError("ledger file not found: {}".format(base_name(path)))
    rows, header_seen = [], False
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = [c.strip() for c in line.split("\t")]
            if not header_seen:
                if cells != header:
                    raise LedgerError("bad header at line {}: expected {}"
                                      .format(lineno, "|".join(header)))
                header_seen = True
                continue
            if len(cells) != len(header):
                raise LedgerError("line {}: expected {} columns, got {}"
                                  .format(lineno, len(header), len(cells)))
            row = dict(zip(header, cells))
            row["_line"] = lineno
            parser(row, lineno)
            rows.append(row)
    if not header_seen:
        raise LedgerError("missing header in ledger: {}".format(base_name(path)))
    return rows


def parse_policy_row(row, lineno):
    row["start"] = parse_date(row["start"], "start")
    row["premium"] = parse_num(row["premium"], "premium")
    if row["premium"] <= 0:
        raise LedgerError("line {}: premium must be positive".format(lineno))
    row["ncd"] = parse_ratio(row["ncd"], "ncd") if row["ncd"] else None


def parse_claim_row(row, lineno):
    row["date"] = parse_date(row["date"], "date")
    if row["fault"] not in FAULTS:
        raise LedgerError("line {}: unknown fault {!r} (mine|other)"
                          .format(lineno, row["fault"]))
    if row["channel"] not in CHANNELS:
        raise LedgerError("line {}: unknown channel {!r} (own|ctp|other|cash)"
                          .format(lineno, row["channel"]))
    row["cost"] = parse_num(row["cost"], "cost")
    if row["cost"] <= 0:
        raise LedgerError("line {}: cost must be positive".format(lineno))


def check_policies(policies):
    starts = [p["start"] for p in policies]
    for a, b in zip(starts, starts[1:]):
        gap = (b - a).days
        if gap <= 0:
            raise LedgerError("policy starts must strictly increase: "
                              "{} then {}".format(a, b))
        if gap < 300 or gap > 400:
            raise LedgerError("policy gap {}..{} is {} days — policies "
                              "renew annually (300-400d); fix the ledger"
                              .format(a, b, gap))


def scope_checks(policies, claims):
    first = policies[0]["start"]
    last_end = add_years(policies[-1]["start"], 1)
    for c in claims:
        if c["date"] < first:
            raise LedgerError("claim {} predates the first policy {} — "
                              "start the ledger at the first policy"
                              .format(c["date"], first))
        if c["date"] > last_end:
            raise LedgerError("claim {} is beyond the last policy year "
                              "(ends {}) — the ledger keeps no future"
                              .format(c["date"], last_end))


def default_asof(policies, claims):
    ds = [p["start"] for p in policies] + [c["date"] for c in claims]
    return max(ds)


def load_ledgers(args, need_claims=True):
    policies = read_tsv(args.policies, HEADER_POLICIES, parse_policy_row)
    claims = read_tsv(args.claims, HEADER_CLAIMS, parse_claim_row) \
        if need_claims else []
    asof = parse_date(args.as_of, "--as-of") if args.as_of \
        else default_asof(policies, claims)
    check_policies(policies)
    scope_checks(policies, claims)
    # --as-of 是截断语义：账针拨回过去，之后的行不可见（不是错误）
    claims = [c for c in claims if c["date"] <= asof]
    sur_dis = SurDis(parse_floats(args.ncd_sur, "ncd-sur", 5),
                     parse_floats(args.ncd_dis, "ncd-dis", 4), "NCD")
    ctp = SurDis(parse_floats(args.ctp_sur, "ctp-sur", 2),
                 parse_floats(args.ctp_dis, "ctp-dis", 3), "CTP")
    return policies, claims, asof, sur_dis, ctp


# ---------------------------------------------------------------- replay

def own_claims_in(claims, lo, hi, upto=None):
    return [c for c in claims
            if lo <= c["date"] < hi and c["channel"] == "own"
            and (upto is None or c["date"] <= upto)]


def anchor_clean(sur_dis, policies):
    anchor = policies[0]["ncd"]
    return sur_dis.reverse(anchor)[0] if anchor is not None else 0


def walk(policies, claims, sur_dis, with_own=True):
    """正向重放每个保单年。返回 years：
    {start, end, premium, ncd, base, own: [claim dict...]}。
    clean 世界 = 全部 own 赔案改自费重放。"""
    starts = [p["start"] for p in policies]
    ends = [add_years(s, 1) for s in starts]
    anchor = policies[0]["ncd"]
    clean = sur_dis.reverse(anchor)[0] if anchor is not None else 0
    years = []
    for i, pol in enumerate(policies):
        if i == 0:
            ncd = anchor if anchor is not None else 1.0   # 新保默认 1.00
        else:
            ended = len(own_claims_in(claims, starts[i - 1], starts[i])) \
                if with_own else 0
            ncd = sur_dis.lookup(clean, ended)
            clean = 0 if ended >= 1 else min(clean + 1, len(sur_dis.dis))
        own = own_claims_in(claims, starts[i], ends[i]) if with_own else []
        years.append({"start": pol["start"], "end": ends[i],
                      "premium": pol["premium"], "ncd": ncd,
                      "base": pol["premium"] / ncd, "own": own})
    return years


def current_state(policies, claims, sur_dis, asof):
    """as-of 时点 (clean, claims_ytd) 与所在保单年索引。"""
    starts = [p["start"] for p in policies]
    idx = max(i for i, s in enumerate(starts) if s <= asof)
    clean = anchor_clean(sur_dis, policies)
    for i in range(1, idx + 1):
        ended = len(own_claims_in(claims, starts[i - 1], starts[i]))
        clean = 0 if ended >= 1 else min(clean + 1, len(sur_dis.dis))
    ytd = len(own_claims_in(claims, starts[idx], add_years(starts[idx], 1),
                            upto=asof))
    return (clean, ytd), idx


def claim_state_before(policies, claims, sur_dis, j):
    """第 j 笔 own 赔案发生前的状态与所在保单年索引。"""
    starts = [p["start"] for p in policies]
    idx = max(i for i, s in enumerate(starts) if s <= claims[j]["date"])
    clean = anchor_clean(sur_dis, policies)
    for i in range(1, idx + 1):
        ended = len(own_claims_in(claims, starts[i - 1], starts[i]))
        clean = 0 if ended >= 1 else min(clean + 1, len(sur_dis.dis))
    before = sum(1 for c in own_claims_in(
        claims, starts[idx], add_years(starts[idx], 1))
        if c["date"] < claims[j]["date"])
    return (clean, before), idx


def realized_hidden(years, clean_years):
    """已付隐身保费 = Σ (实际 NCD − 无赔 NCD) × 基准，逐已续保年。
    无赔世界的保费 = 实际基准 × 无赔 NCD（基准取实际年：
    自主定价系数两个世界共享，这是披露假设，不是事实）。"""
    rows, total = [], 0.0
    for a, c in zip(years, clean_years):
        d = (a["ncd"] - c["ncd"]) * a["base"]
        rows.append({"start": a["start"], "ncd": a["ncd"],
                     "ncd_clean": c["ncd"], "base": a["base"], "delta": d,
                     "clean_premium": a["base"] * c["ncd"]})
        total += d
    return total, rows


def clean_premium_total(years, clean_years):
    return sum(a["base"] * c["ncd"] for a, c in zip(years, clean_years))


def years_upto(years, asof):
    """已发生的保单年（续保日 ≤ as-of）：回看历史时点时，未来的
    保费还没付过，不进「已付」账。"""
    return [y for y in years if y["start"] <= asof]


def tail_bill(sur_dis, base, policies, state, idx):
    """恢复期尾款：当前轨迹与「从未出险」路径到重合为止，未来续保年
    将多付的保费（基准按当前年，自主定价系数不变的披露假设）。"""
    ever = (min(anchor_clean(sur_dis, policies) + idx, len(sur_dis.dis)), 0)
    st_cur, st_ever = state, ever
    total, detail = 0.0, []
    for k in range(1, RECOVERY_CAP + 1):
        if st_cur == st_ever:
            break
        ncd_cur, ncd_ever = sur_dis.lookup(*st_cur), sur_dis.lookup(*st_ever)
        d = (ncd_cur - ncd_ever) * base
        total += d
        detail.append((add_years(policies[idx]["start"], k),
                       ncd_cur, ncd_ever, d))
        st_cur, st_ever = sur_dis.rollover(st_cur), sur_dis.rollover(st_ever)
    return total, detail


def full_prices(policies, claims, sur_dis, asof):
    """逐笔 own 赔案的全价（出险当时状态的边际隐身保费，基准取当年）。"""
    years = walk(policies, claims, sur_dis)
    out = []
    for j, c in enumerate(claims):
        if c["channel"] != "own":
            continue
        state, idx = claim_state_before(policies, claims, sur_dis, j)
        base = years[idx]["base"]
        bill, diffs, horizon = sur_dis.hidden_bill(state, base)
        out.append({"claim": c, "j": j, "state": state, "base": base,
                    "bill": bill, "diffs": diffs, "horizon": horizon})
    return out


# ---------------------------------------------------------------- commands

def cmd_report(args):
    policies, claims, asof, sur_dis, ctp = load_ledgers(args)
    print("报险线 · Claim Line —— 历史审计")
    print("账本: {} + {}   as-of {}{}".format(
        base_name(args.policies), base_name(args.claims), asof,
        "" if args.as_of else "（账本自锚定）"))
    years = walk(policies, claims, sur_dis)
    clean_years = walk(policies, claims, sur_dis, with_own=False)

    print()
    print("【保单年表】")
    print_row([("起始", 12), ("保费", 10), ("NCD", 9), ("基准", 10),
               ("own赔案", 8), ("其他通道", 8)])
    for y in years:
        others = sum(1 for c in claims
                     if y["start"] <= c["date"] < y["end"]
                     and c["channel"] != "own")
        print_row([(y["start"].isoformat(), 12),
                   (fmt_money(y["premium"]), 10),
                   ("{:.2f}".format(y["ncd"]), 9),
                   (fmt_money(y["base"]), 10),
                   (str(len(y["own"])), 8), (str(others), 8)])

    prices = full_prices(policies, claims, sur_dis, asof)
    print()
    print("【出险定价单 —— 每笔报险的真实价格】")
    if not prices:
        print("  账本至今没有 own 赔案——保持。")
    else:
        print_row([("日期", 12), ("责任", 6), ("通道", 10), ("金额", 11),
                   ("当时状态", 14), ("隐身保费", 12), ("全价/维修", 10)])
        for p in prices:
            c = p["claim"]
            if c["channel"] == "own":
                st = "连无赔{}·本年{}".format(p["state"][0], p["state"][1])
                ratio = fmt_ratio(p["bill"] / c["cost"])
                print_row([(c["date"].isoformat(), 12),
                           (FAULT_NAMES[c["fault"]], 6),
                           (CHANNEL_NAMES[c["channel"]], 10),
                           (fmt_money(c["cost"]), 11), (st, 14),
                           (fmt_money(p["bill"]), 12), (ratio, 10)])
        for c in claims:
            if c["channel"] != "own":
                note = "0——你的保险公司没付钱，不占赔款次数" \
                    if c["channel"] in ("other", "cash") \
                    else "走交强险，不占商业险赔款次数"
                print_row([(c["date"].isoformat(), 12),
                           (FAULT_NAMES[c["fault"]], 6),
                           (CHANNEL_NAMES[c["channel"]], 10),
                           (fmt_money(c["cost"]), 11), (note, 34)])

    total_actual = sum(y["premium"] for y in years_upto(years, asof))
    total_clean = clean_premium_total(years_upto(years, asof),
                                      years_upto(clean_years, asof))
    print()
    print("【已发生总账】")
    if len(policies) < 2:
        print("  DECLINE——账本不足两个保单年，还没有一次续保可比，")
        print("  已付隐身保费与冤案总账拒判（定价单照出）。算术不会装懂。")
        code = EXIT_THIN
    else:
        realized, rows = realized_hidden(years_upto(years, asof),
                                         years_upto(clean_years, asof))
        for r in rows:
            if abs(r["delta"]) > EPS:
                print("  {} 续保：实际 {:.2f} vs 无赔 {:.2f} × 基准 {} "
                      "= {}".format(r["start"], r["ncd"], r["ncd_clean"],
                                    fmt_money(r["base"]),
                                    fmt_money(r["delta"])))
        print("  实缴保费 {} = 无赔世界 {} + 已付隐身 {}".format(
            fmt_money(total_actual), fmt_money(total_clean),
            fmt_money(realized)))
        state, idx = current_state(policies, claims, sur_dis, asof)
        tail, detail = tail_bill(sur_dis, years[idx]["base"], policies,
                                 state, idx)
        if detail:
            print("  恢复期尾款 {}：".format(fmt_money(tail)))
            for d in detail:
                print("    {} 续保 {:.2f} vs {:.2f} → {}".format(
                    d[0], d[1], d[2], fmt_money(d[3])))
            print("  （账本外：按「年内不再出险」推演，随无赔年份逐年归零）")
        code = EXIT_OK

    if prices:
        print()
        print("【冤案榜】全价 > {}× 维修费的报险".format(
            args.overclaim_line))
        if len(policies) < 2:
            print("  DECLINE——还没发生过一次续保，冤案判级挂起")
            print("  （比值已在定价单里，算术照出）。")
        else:
            over = [p for p in prices if p["bill"] > p["claim"]["cost"]
                    * args.overclaim_line]
            if not over:
                print("  无——每一笔报险都值回全价。")
            else:
                for p in over:
                    print("  {} 的 {} 维修报了商业险：全价 {} = 维修费的 {} → "
                          "OVERCLAIM".format(
                              p["claim"]["date"],
                              fmt_money(p["claim"]["cost"]),
                              fmt_money(p["bill"]),
                              fmt_ratio(p["bill"] / p["claim"]["cost"])))
                if code == EXIT_OK:
                    code = EXIT_RED

    state, idx = current_state(policies, claims, sur_dis, asof)
    base = walk(policies, claims, sur_dis)[idx]["base"]
    line, diffs, horizon = sur_dis.hidden_bill(state, base)
    print()
    print("【当前自费线】状态 连无赔{} · 本年own赔案{}".format(state[0], state[1]))
    print("  再报一笔的隐身保费 = {}（{} × 基准 {}），恢复期 {} 年".format(
        fmt_money(line),
        "+".join("{:.2f}".format(d) for d in diffs), fmt_money(base),
        horizon))
    m2, _, _ = sur_dis.hidden_bill((state[0], state[1] + 1), base)
    if state[1] >= 1:
        print("  折扣已烧断：此后每笔加罚固定 {:.2f}× 基准 = {}".format(
            m2 / base, fmt_money(m2)))
        nxt = sur_dis.rollover(state)
        nxt_line = sur_dis.hidden_bill(nxt, base)[0]
        print("  但折扣在重新攒：等一年再报，隐身价 {} → {}（翻倍的话就是"
              "涨价前的最后窗口）".format(fmt_money(line),
                                     fmt_money(nxt_line)))
    else:
        print("  第 1 笔烧折扣最贵；此后的笔数按固定加罚计价（见边际表）")
    print("【边际表】从当前状态连报 1/2/3 笔的隐身保费：")
    cum, st = 0.0, state
    for k in (1, 2, 3):
        bill, _, _ = sur_dis.hidden_bill(st, base)
        cum += bill
        print("  第 {} 笔：{}（累计 {}）".format(k, fmt_money(bill),
                                              fmt_money(cum)))
        st = (st[0], st[1] + 1)
    return code


def cmd_decide(args):
    if args.base is not None:
        if args.base <= 0:
            raise LedgerError("--base must be positive")
        sur_dis = SurDis(parse_floats(args.ncd_sur, "ncd-sur", 5),
                         parse_floats(args.ncd_dis, "ncd-dis", 4), "NCD")
        ctp = SurDis(parse_floats(args.ctp_sur, "ctp-sur", 2),
                     parse_floats(args.ctp_dis, "ctp-dis", 3), "CTP")
        state = (args.clean, args.claims_ytd)
        base = args.base
        ctx = "手动模式 --base {} --clean {} --claims-ytd {}".format(
            fmt_money(base), state[0], state[1])
    else:
        if not os.path.exists(args.policies) or not os.path.exists(args.claims):
            raise ThinError(
                "no ledger and no --base — at the roadside use the manual "
                "court: decide COST --base <基准保费> --clean <连无赔年数> "
                "--claims-ytd <本年own赔案数>")
        policies, claims, asof, sur_dis, ctp = load_ledgers(args)
        state, idx = current_state(policies, claims, sur_dis, asof)
        base = walk(policies, claims, sur_dis)[idx]["base"]
        ctx = "账本 {} + {}，as-of {}".format(
            base_name(args.policies), base_name(args.claims), asof)

    cost = args.cost
    if cost <= 0:
        raise LedgerError("cost must be positive")
    print("报险线 · Claim Line —— 出险裁决")
    print(ctx)
    print()
    line, diffs, horizon = sur_dis.hidden_bill(state, base)
    eff_line = line + args.deductible
    print("维修/赔付金额 {}；当前状态 连无赔{} · 本年own赔案{}".format(
        fmt_money(cost), state[0], state[1]))

    if args.fault == "other":
        print()
        print("裁决 OTHERS——对方全责，走对方的保险：你的保单一分不动，")
        print("赔款记录在对方账上。别用自己的商业险代位追偿（那算你出险）。")
        return EXIT_OK

    print("自费线 = {}（{} × 基准 {}，恢复期 {} 年）{}".format(
        fmt_money(line), "+".join("{:.2f}".format(d) for d in diffs),
        fmt_money(base), horizon,
        "，+免赔额 {} = 实际线 {}".format(fmt_money(args.deductible),
                                    fmt_money(eff_line))
        if args.deductible else ""))

    if args.target == "other" and cost <= args.ctp_limit \
            and args.fault == "mine":
        ctp_bill, ctp_diffs, ctp_hz = ctp.hidden_bill(
            (args.ctp_clean, 0), args.ctp_base)
        options = [("CTP", ctp_bill), ("CASH", cost), ("CLAIM", eff_line)]
        options.sort(key=lambda o: o[1])
        print("交强险选项（财产损失限额 {}，浮动独立于商业 NCD）：".format(
            fmt_money(args.ctp_limit)))
        print("  走交强隐身 ≈ {}（{} × 交强基准 {}，按满折位假设）".format(
            fmt_money(ctp_bill), "+".join("{:.2f}".format(d)
                                          for d in ctp_diffs),
            fmt_money(args.ctp_base)))
        print("  自掏现金 {}；走商业险 {}（自费线）".format(
            fmt_money(cost), fmt_money(eff_line)))
        best = options[0]
        print()
        if best[0] == "CTP":
            print("裁决 CTP——走交强险：真实价格 {}，三者里最便宜；".format(
                fmt_money(ctp_bill)))
            print("交强的浮动与商业 NCD 是两本账，你的商业折扣原封不动。")
            return EXIT_OK
        elif best[0] == "CASH":
            print("裁决 CASH——自掏 {}: 连交强都不值得动（隐身 {} > 现金 {}）。"
                  .format(fmt_money(cost), fmt_money(ctp_bill),
                          fmt_money(cost)))
            return EXIT_RED
        else:
            print("裁决 CLAIM——走商业险：自费线 {} 已低于交强隐身 {} 与现金 {}。"
                  .format(fmt_money(eff_line), fmt_money(ctp_bill),
                          fmt_money(cost)))
            return EXIT_OK

    band = eff_line * args.band
    print()
    if cost < eff_line - band:
        print("裁决 CASH——自掏 {}: 报保险全价 {} 是维修费的 {}。".format(
            fmt_money(cost), fmt_money(eff_line),
            fmt_ratio(eff_line / cost)))
        print("标价 ¥0 的报保险，真实价格写在未来 {} 年的续保单里。".format(horizon))
        return EXIT_RED
    if cost > eff_line + band:
        print("裁决 CLAIM——走商业险：维修 {} 超过自费线 {}（+{} 带宽）。".format(
            fmt_money(cost), fmt_money(eff_line), fmt_pct(args.band, 0)))
        print("折扣再贵也贵不过大修——这正是保险存在的场合。")
        return EXIT_OK
    print("裁决 TIE ◐——{} 落在自费线 {} 的 ±{} 掷币带内：".format(
        fmt_money(cost), fmt_money(eff_line), fmt_pct(args.band, 0)))
    print("自费省下的是确定的保费涨幅，报险保住的是手里的现金——两样都真实，")
    print("按当月现金流自己拍板。")
    return EXIT_OK


def cmd_renewal(args):
    policies, claims, asof, sur_dis, ctp = load_ledgers(args)
    years = walk(policies, claims, sur_dis)
    state, idx = current_state(policies, claims, sur_dis, asof)
    base = years[idx]["base"]
    next_start = add_years(years[idx]["start"], 1)
    ncd_next = sur_dis.lookup(*state)
    prem_next = base * ncd_next
    print("报险线 · Claim Line —— 续保预演")
    print("账本: {} + {}   as-of {}{}".format(
        base_name(args.policies), base_name(args.claims), asof,
        "" if args.as_of else "（账本自锚定）"))
    print()
    print("下次续保 {}（推演「年内不再出险」）：".format(next_start))
    print("  NCD {:.2f} → 保费预估 {}".format(ncd_next, fmt_money(prem_next)))
    own_ytd = own_claims_in(claims, years[idx]["start"],
                            years[idx]["end"], upto=asof)
    if own_ytd:
        ncd_cf = sur_dis.lookup(state[0], 0)
        prem_cf = base * ncd_cf
        delta = prem_next - prem_cf
        print("  无赔反事实 {:.2f} → {}：本年 {} 笔 own 赔案让这次续保多付 {}".format(
            ncd_cf, fmt_money(prem_cf), len(own_ytd), fmt_money(delta)))
        for c in own_ytd:
            print("    ← {} {}（{}）".format(c["date"], fmt_money(c["cost"]),
                                            c.get("note") or "无备注"))
        if delta > prem_next * 0.25:
            print("  NCD-BURN——尾款占这次续保的 {}，这是已签约的账，".format(
                fmt_pct(delta / prem_next)))
            print("  唯一的安慰是它随无赔年份逐年归零。")
    else:
        print("  本保单年至今无 own 赔案：这次续保按无赔路径走，保持。")
    print()
    print("恢复期路线图（不再出险假设）：")
    st, ever = state, (min(anchor_clean(sur_dis, policies) + idx,
                           len(sur_dis.dis)), 0)
    for k in range(1, 7):
        d = add_years(years[idx]["start"], k)
        n1, n2 = sur_dis.lookup(*st), sur_dis.lookup(*ever)
        mark = "   ← 与从未出险重合" if st == ever else ""
        print("  {} 续保：{:.2f}（{}）   无赔世界 {:.2f}（{}）{}".format(
            d, n1, fmt_money(base * n1), n2, fmt_money(base * n2), mark))
        if st == ever:
            break
        st, ever = sur_dis.rollover(st), sur_dis.rollover(ever)
    return EXIT_OK


def cmd_simulate(args):
    policies, claims, asof, sur_dis, ctp = load_ledgers(args)
    state, idx = current_state(policies, claims, sur_dis, asof)
    base = walk(policies, claims, sur_dis)[idx]["base"]
    print("报险线 · Claim Line —— 反事实沙盒（恒 exit 0，沙盒不执法）")
    print("账本: {} + {}   as-of {}".format(
        base_name(args.policies), base_name(args.claims), asof))
    print("状态 连无赔{} · 本年own赔案{} · 基准 {}".format(
        state[0], state[1], fmt_money(base)))
    print()

    if args.mode == "never-claim":
        years = years_upto(walk(policies, claims, sur_dis), asof)
        clean_years = years_upto(
            walk(policies, claims, sur_dis, with_own=False), asof)
        realized, _ = realized_hidden(years, clean_years)
        own_cash = sum(c["cost"] for c in claims if c["channel"] == "own")
        print("never-claim——把账本里每一笔 own 报险改成自掏：")
        print("  实缴保费 - 无赔世界保费 = 已付隐身 {}".format(
            fmt_money(realized)))
        print("  当年报险省下的维修现金 = {}".format(fmt_money(own_cash)))
        net = realized - own_cash
        print("  净额 = {}：{}".format(
            fmt_money(abs(net)),
            "多交的保费已经超过省下的维修现金——报险吃的亏是真金白银"
            if net > 0 else "省下的维修现金还没有被保费追平（恢复期没走完，"
                            "尾款在续保单里排着队）"))
        print("  （恒等式：已付隐身 = 实缴 − 无赔，validate 逐位核对）")
        return EXIT_OK

    if args.cost is None or args.cost <= 0:
        raise LedgerError("simulate {} needs a positive --cost".format(args.mode))

    claim_bill, diffs, horizon = sur_dis.hidden_bill(state, base)
    claim_prem = [base * n for n in sur_dis.project(
        (state[0], state[1] + 1), horizon)]
    clean_prem = [base * n for n in sur_dis.project(state, horizon)]
    total_claim = sum(claim_prem) + args.deductible
    total_cash = args.cost + sum(clean_prem)
    print("维修金额 {}，恢复期 {} 年，两条路径的续保保费：".format(
        fmt_money(args.cost), horizon))
    print("  报险路径: " + " + ".join(fmt_money(x) for x in claim_prem) +
          " = {}（+免赔额 {}）".format(fmt_money(sum(claim_prem)),
                                   fmt_money(args.deductible)))
    print("  无赔路径: " + " + ".join(fmt_money(x) for x in clean_prem) +
          " = {}".format(fmt_money(sum(clean_prem))))

    if args.mode == "claim":
        diff = total_cash - total_claim
        print()
        print("claim——报商业险总账 {} vs 自掏 {}：{}".format(
            fmt_money(total_claim), fmt_money(total_cash),
            "报险便宜 {}——值".format(fmt_money(diff)) if diff > 0
            else "自掏便宜 {}".format(fmt_money(-diff))))
        return EXIT_OK
    if args.mode == "cash":
        diff = total_claim - total_cash
        print()
        print("cash——自掏 {} vs 报商业险总账 {}：{}".format(
            fmt_money(total_cash), fmt_money(total_claim),
            "自掏便宜 {}".format(fmt_money(diff)) if diff > 0
            else "报险便宜 {}".format(fmt_money(-diff))))
        return EXIT_OK
    if args.mode == "ctp":
        if args.target != "other" or args.cost > args.ctp_limit:
            raise LedgerError(
                "simulate ctp is for third-party property damage within "
                "the CTP limit ({}); got target={} cost={}".format(
                    fmt_money(args.ctp_limit), args.target,
                    fmt_money(args.cost)))
        ctp_bill = ctp.hidden_bill((args.ctp_clean, 0), args.ctp_base)[0]
        total_ctp = ctp_bill + sum(clean_prem)
        print("  交强路径: 隐身 {} + 无赔商业保费 = {}".format(
            fmt_money(ctp_bill), fmt_money(total_ctp)))
        print()
        best = min([("CTP", total_ctp), ("CASH", total_cash),
                    ("CLAIM", total_claim)], key=lambda o: o[1])
        print("三路径总账：交强 {} · 自掏 {} · 商业险 {}".format(
            fmt_money(total_ctp), fmt_money(total_cash),
            fmt_money(total_claim)))
        print("最便宜：{} {}".format(best[0], fmt_money(best[1])))
        return EXIT_OK
    raise LedgerError("unknown simulate mode {!r}".format(args.mode))


def cmd_validate(args):
    policies, claims, asof, sur_dis, ctp = load_ledgers(args)
    print("报险线 · Claim Line —— 账本体检")
    print("账本: {} + {}".format(base_name(args.policies),
                                 base_name(args.claims)))
    print()
    ok = True

    print("【状态机自查】")
    for tab in (sur_dis, ctp):
        print("  {} 加罚表 {} 严格递增、折扣表 {} 严格递减 ✓".format(
            tab.name, tab.sur, tab.dis))
    max_h = 0
    for clean in range(len(sur_dis.dis) + 1):
        for cl in range(len(sur_dis.sur) + 1):
            _, h = sur_dis.uplift_path((clean, cl))
            max_h = max(max_h, h)
    bound = len(sur_dis.dis) + len(sur_dis.sur) + 1
    print("  全状态网格恢复期 ≤ {}（实测 max {}，上界 {}）✓"
          .format(bound, max_h, bound))
    if max_h > bound:
        ok = False

    print("【两世界必平】")
    st0, B = (2, 0), 6000.0
    bill, _, hz = sur_dis.hidden_bill(st0, B)
    claim_prem = sum(B * n for n in sur_dis.project((st0[0], st0[1] + 1), hz))
    clean_prem = sum(B * n for n in sur_dis.project(st0, hz))
    gap = abs((claim_prem - clean_prem) - bill)
    print("  维修费恰 = 自费线 {} 时：报险总账 − 自掏总账 = {:.2e} ✓"
          .format(fmt_money(bill), gap))
    if gap > 1e-6:
        ok = False

    print("【边际可加】")
    st, total = st0, 0.0
    for k in range(1, 5):
        m = sur_dis.hidden_bill(st, B)[0]
        total += m
        st = (st[0], st[1] + 1)
    direct = 0.0
    clean_proj = sur_dis.project(st0, RECOVERY_CAP)
    claim_proj = sur_dis.project((st0[0], st0[1] + 4), RECOVERY_CAP)
    for a, b in zip(clean_proj, claim_proj):
        direct += (b - a) * B
    print("  连报 4 笔的边际之和 {} = 两路径直接作差 {}（{:.2e}）✓".format(
        fmt_money(total), fmt_money(direct), abs(total - direct)))
    if abs(total - direct) > 1e-6:
        ok = False

    years = walk(policies, claims, sur_dis)
    clean_years = walk(policies, claims, sur_dis, with_own=False)
    years_f = years_upto(years, asof)
    realized, _ = realized_hidden(years_f, years_upto(clean_years, asof))
    lhs = sum(y["premium"] for y in years_f)
    rhs = clean_premium_total(years_f, years_upto(clean_years, asof))
    print("【路径恒等式】实缴 {} − 无赔 {} = 已付隐身 {}（{:.2e}）✓".format(
        fmt_money(lhs), fmt_money(rhs), fmt_money(realized),
        abs(lhs - rhs - realized)))
    if abs(lhs - rhs - realized) > 1e-6:
        ok = False

    bases = [y["base"] for y in years]
    spread = max(bases) / min(bases)
    print("【基准保费】隐含基准 {}".format(" / ".join(fmt_money(b)
                                              for b in bases)) +
          (" → 一致 ✓" if spread <= 1.001 else
           " → WILD-BASE：max/min = {}，保费变动不只来自 NCD".format(
               fmt_ratio(spread))))
    if spread > BASE_WILD_RATIO:
        print("  保费跳变里混着自主定价系数/险种变更——本件按「基准不变」")
        print("  折算恢复期，判级前请知道这个假设在响。")

    mismatches = []
    for i, (y, pol) in enumerate(zip(years, policies)):
        if pol["ncd"] is not None and abs(pol["ncd"] - y["ncd"]) > 1e-6:
            mismatches.append((pol["start"], pol["ncd"], y["ncd"]))
    if mismatches:
        print("【NCD 对质】保单列与出险史重放不一致（保单永远赢，但账要亮出来）：")
        for s, given, replayed in mismatches:
            print("  {} 保单列 {:.2f} vs 重放 {:.2f}——这一年有赔案没记，"
                  "或系数另有来头".format(s, given, replayed))
    else:
        given = sum(1 for p in policies if p["ncd"] is not None)
        print("【NCD 对质】{} 个保单年给了 ncd 列，与出险史重放全部一致 ✓"
              .format(given))
    print()
    print("体检{}通过。账本只记你声称的事实：保费与赔款记录在保险公司 App 里，".format(
        "" if ok else "未"))
    print("抄一遍账本，就是对整段保险史的一次 verify。")
    return EXIT_OK if ok else EXIT_LEDGER


# ---------------------------------------------------------------- main

def add_common(ap, ledger=True):
    if ledger:
        ap.add_argument("--policies", default="policies.tsv")
        ap.add_argument("--claims", default="claims.tsv")
        ap.add_argument("--as-of", dest="as_of", default=None,
                        help="钉死 as-of（缺省 = 账本末日，账本自锚定）")
    ap.add_argument("--ncd-sur", default="1.0,1.25,1.5,1.75,2.0",
                    help="NCD 加罚表（上年 own 赔案 1..5+ 次，逗号分隔）")
    ap.add_argument("--ncd-dis", default="0.85,0.70,0.60,0.50",
                    help="NCD 折扣表（连续无赔 1..4+ 年，逗号分隔）")
    ap.add_argument("--ctp-sur", default="0.0,0.1",
                    help="交强浮动加罚表（上年有责 1/2+ 次）")
    ap.add_argument("--ctp-dis", default="-0.1,-0.2,-0.3",
                    help="交强浮动折扣表（连续无有责事故 1..3+ 年）")
    ap.add_argument("--ctp-base", type=float, default=CTP_BASE_DEFAULT)
    ap.add_argument("--ctp-limit", type=float, default=CTP_LIMIT_DEFAULT)
    ap.add_argument("--ctp-clean", type=int, default=CTP_CLEAN_DEFAULT,
                    help="交强无账本，假设的连续无有责年数（默认满折 3）")


def main(argv=None):
    ap = argparse.ArgumentParser(prog=PROG, description="报险线 · Claim Line")
    ap.add_argument("--version", action="version",
                    version="{} {}".format(PROG, VERSION))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_positional(p):
        p.add_argument("ledger", nargs="*", metavar="LEDGER",
                       help="policies.tsv claims.tsv（位置参数；"
                            "缺省用 --policies/--claims，再缺省当前目录）")

    p = sub.add_parser("report", help="历史审计：定价单/已付隐身/冤案榜")
    add_common(p)
    add_positional(p)
    p.add_argument("--overclaim-line", type=float,
                   default=OVERCLAIM_LINE_DEFAULT)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("decide", help="出险当场裁决：报还是自掏")
    p.add_argument("cost", type=float, help="维修/赔付金额")
    add_common(p)
    p.add_argument("--base", type=float, default=None,
                   help="手动模式：基准保费（无账本时用）")
    p.add_argument("--clean", type=int, default=3,
                   help="手动模式：连续无赔年数（默认 3）")
    p.add_argument("--claims-ytd", type=int, default=0,
                   help="手动模式：本保单年已有 own 赔案数")
    p.add_argument("--target", choices=("own", "other"), default="own",
                   help="修的是谁的车（默认 own；交强险只保对方）")
    p.add_argument("--fault", choices=("mine", "other"), default="mine")
    p.add_argument("--deductible", type=float, default=0.0,
                   help="商业险免赔额（加进报险一侧）")
    p.add_argument("--band", type=float, default=BAND_DEFAULT,
                   help="自费线掷币带（默认 ±0.10）")
    p.set_defaults(fn=cmd_decide)

    p = sub.add_parser("renewal", help="续保预演：下次续保多付多少、记谁头上")
    add_common(p)
    add_positional(p)
    p.set_defaults(fn=cmd_renewal)

    p = sub.add_parser(
        "simulate",
        help="反事实沙盒：cash/claim/ctp/never-claim（账本用 "
             "--policies/--claims 旗标给）")
    p.add_argument("mode", choices=("cash", "claim", "ctp", "never-claim"))
    p.add_argument("cost", type=float, nargs="?", default=None,
                   help="维修/赔付金额（cash/claim/ctp 必给；never-claim 不用）")
    add_common(p)
    p.add_argument("--deductible", type=float, default=0.0)
    p.add_argument("--target", choices=("own", "other"), default="other")
    p.set_defaults(fn=cmd_simulate)

    p = sub.add_parser("validate", help="账本体检：恒等式与状态机自查")
    add_common(p)
    add_positional(p)
    p.set_defaults(fn=cmd_validate)

    args = ap.parse_args(argv)
    if getattr(args, "ledger", None):
        if len(args.ledger) > 2:
            ap.error("ledger: at most two paths (policies claims)")
        args.policies = args.ledger[0]
        args.claims = args.ledger[1] if len(args.ledger) > 1 else "claims.tsv"
    try:
        return args.fn(args)
    except LedgerError as e:
        print("{}: ledger/usage error: {}".format(PROG, e), file=sys.stderr)
        return EXIT_LEDGER
    except ThinError as e:
        print("{}: too thin to grade: {}".format(PROG, e), file=sys.stderr)
        return EXIT_THIN


if __name__ == "__main__":
    sys.exit(main())
