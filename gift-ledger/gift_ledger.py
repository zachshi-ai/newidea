#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gift-ledger · 人情账 —— 给随礼装上一本可对账的往来账本.

问题：随礼是人情社会里唯一「当场定生死、事后无对账」的支付：请帖
到手的那一晚，你要在 24 小时内拍出一个数——随少了失礼，随多了打乱
预算，而拍脑袋的全部依据只有两样：碎片记忆（「他上次随我来着……多
少来着？」）和焦虑。没有人手算得出这个数，因为它是一个四变量函数：
场合基线 × 关系层级 × 通胀年代 × 两人之间的历史余额——最后这个变量
是双向的，记忆只记得「他上次随多少」，从不记得「我上次随多少」。于
是同一份人情，有人十年只进不出，有人每次都多还一半，账在两颗心里
各记一版，直到某天对不齐，关系就散了。

gift-ledger 从一本可手编的往来账（TSV：日期 / 方向 / 对方 / 关系 /
场合 / 金额）确定性算出：

  * ledger    账本体检 + 关系/场合系数表
  * balance   单人对账：双向折算总额、净余额（你欠人情为正）、逐笔
  * suggest   请帖之夜的建议区间：场合基线 × 关系系数为骨架，对方
              当年同场合随礼经通胀折算成「对价锚」托底，未平的余额
              计入下限——大额旧账只还一半，剩下的明示「不是一张请
              帖能平的账」
  * book      全员余额排行 + 礼崩名单（只进不出超线 → exit 4）
  * inflation 从你自己的随礼史里算出年化通胀，校验你的折算假设
  * simulate  若今天随 X：余额怎么变、对方下次该回多少——抬价之前
              先看清你把谁推进了你的处境

核心公式：折算值 adj = 金额 × (1+通胀)^(间隔年数)；净余额 =
Σ adj(收进) − Σ adj(随出)，为正即你欠着人情。折算让 2019 年的 500
和 2026 年的 700 站上同一把尺——人情账第一次有了跨年代的可比性。

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
「今天」默认真实当下，`--as-of` 钉死即逐字节可复现。

用法：
  python3 gift_ledger.py ledger gifts.tsv --as-of 2026-09-04
  python3 gift_ledger.py balance gifts.tsv 表哥
  python3 gift_ledger.py suggest gifts.tsv 表妹 --occasion wedding
  python3 gift_ledger.py book gifts.tsv            # 有礼崩 → exit 4
  python3 gift_ledger.py inflation gifts.tsv
  python3 gift_ledger.py simulate gifts.tsv 老周 --amount 300

Exit codes:
  0  report produced（含 balanced / 提示）
  2  usage error / ledger missing / malformed row
  3  refusal: empty ledger / 查无此人 / 通胀样本不足
  4  gate: book 中存在礼崩关系（只进不出且超线）
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from typing import Dict, List, Optional

PROG = "gift-ledger"
VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# 系数表：先验，不是行情；一切可用 flags 覆盖。论证见 METHODOLOGY.md。
# ---------------------------------------------------------------------------

RELATIONS: Dict[str, tuple] = {
    "family": (1.5, "至亲：血缘/姻亲，随的是礼数"),
    "close-friend": (1.2, "挚友：随的是交情"),
    "friend": (1.0, "普通朋友：随的是基准"),
    "colleague": (0.7, "同事：随的是场面"),
    "distant": (0.5, "远亲/泛泛之交：随的是通知"),
}

OCCASIONS: Dict[str, tuple] = {
    "wedding": (1.0, "婚礼：人情市场的硬通货"),
    "funeral": (1.0, "白事：随的是吊唁，不通胀、不讲对价"),
    "baby": (0.6, "满月/百日"),
    "housewarming": (0.5, "乔迁"),
    "birthday": (0.4, "寿宴/整寿"),
    "illness": (0.4, "探病：随的是心意"),
}

DEFAULT_BASE = 600.0        # wedding × friend 在基准年的基线（元）
DEFAULT_INFLATION = 0.05    # 折算用的年化随礼通胀假设
DEFAULT_RED_YEARS = 3.0     # 礼崩判定：单向无往来年数
DEFAULT_RED_AMOUNT = 1000.0  # 礼崩判定：折算余额红线（元）

LEDGER_COLUMNS = ["date", "direction", "party", "relation", "occasion",
                  "amount", "note?"]


class UsageError(Exception):
    """exit 2：参数或账本错误。"""


class Refusal(Exception):
    """exit 3：无可计算（空账本 / 查无此人 / 样本不足）。"""


class GiftGate(Exception):
    """exit 4：礼崩名单非空。携带报告文本。"""


# ---------------------------------------------------------------------------
# 账本
# ---------------------------------------------------------------------------

class Event:
    __slots__ = ("date", "direction", "party", "relation", "occasion",
                 "amount", "raw", "lineno")

    def __init__(self, date: dt.date, direction: str, party: str,
                 relation: str, occasion: str, amount: float,
                 raw: List[str], lineno: int):
        self.date = date
        self.direction = direction
        self.party = party
        self.relation = relation
        self.occasion = occasion
        self.amount = amount
        self.raw = raw
        self.lineno = lineno


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def parse_date(text: str, where: str) -> dt.date:
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise UsageError("%s：日期应为 YYYY-MM-DD，得到 %r" % (where, text))


def parse_ledger(path: str) -> List[Event]:
    """TSV：date direction party relation occasion amount [note]。

    # 注释与空行忽略；首行以 date 开头的表头行跳过；坏行带行号 exit 2。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise UsageError("无法读取账本 %s: %s" % (path, exc))

    events: List[Event] = []
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip("\n").strip("\r")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        while cols and cols[-1] == "":
            cols.pop()
        where = "第 %d 行" % idx
        if cols and cols[0] == "date":
            continue  # 表头行
        if len(cols) < 6:
            raise UsageError("%s：至少需要 6 列（%s）"
                             % (where, " / ".join(LEDGER_COLUMNS[:6])))
        date = parse_date(cols[0], where)
        direction = cols[1]
        if direction not in ("in", "out"):
            raise UsageError("%s：direction 应为 in（收进）/ out（随出），得到 %r"
                             % (where, direction))
        party = cols[2]
        if not party:
            raise UsageError("%s：party 不能为空" % where)
        relation = cols[3]
        if relation not in RELATIONS:
            raise UsageError("%s：未知关系 %r（可选：%s）"
                             % (where, relation, " / ".join(RELATIONS)))
        occasion = cols[4]
        if occasion not in OCCASIONS:
            raise UsageError("%s：未知场合 %r（可选：%s）"
                             % (where, occasion, " / ".join(OCCASIONS)))
        if not _is_number(cols[5]):
            raise UsageError("%s：amount 应为正数，得到 %r" % (where, cols[5]))
        amount = float(cols[5])
        if amount <= 0:
            raise UsageError("%s：amount 必须为正——白事的香烛钱记 note 里" % where)
        events.append(Event(date, direction, party, relation, occasion,
                            amount, cols, idx))
    return events


def validate_calendar(events: List[Event], as_of: dt.date) -> None:
    for e in events:
        if e.date > as_of:
            raise UsageError("第 %d 行：日期(%s) 晚于基准日(%s)——未来的随礼不算随礼"
                             % (e.lineno, e.date, as_of))


def pick_party(events: List[Event], party: str) -> List[Event]:
    pool = [e for e in events if e.party == party]
    if not pool:
        known = "、".join(sorted({e.party for e in events}))
        raise Refusal("账本里查无此人：%r（有：%s）" % (party, known))
    return sorted(pool, key=lambda e: e.date)


# ---------------------------------------------------------------------------
# 核心算术：购买力折算 + 余额
# ---------------------------------------------------------------------------

def adjust(amount: float, date: dt.date, as_of: dt.date,
           inflation: float) -> float:
    """历史金额 → 基准日购买力。通胀率 0 时恒等。"""
    days = (as_of - date).days
    return amount * math.pow(1.0 + inflation, days / 365.25)


def balance_of(pool: List[Event], as_of: dt.date, inflation: float) -> float:
    """净余额 = Σ adj(in) − Σ adj(out)。为正 = 你欠着人情。"""
    total = 0.0
    for e in pool:
        adj = adjust(e.amount, e.date, as_of, inflation)
        total += adj if e.direction == "in" else -adj
    return total


def last_event_date(pool: List[Event], direction: Optional[str] = None) -> Optional[dt.date]:
    dates = [e.date for e in pool if direction is None or e.direction == direction]
    return max(dates) if dates else None


def first_event_date(pool: List[Event], direction: Optional[str] = None) -> Optional[dt.date]:
    dates = [e.date for e in pool if direction is None or e.direction == direction]
    return min(dates) if dates else None


def is_blackhole(pool: List[Event], as_of: dt.date, inflation: float,
                 red_years: float, red_amount: float) -> bool:
    """礼崩：① 他欠你（你净流出）超过红线；② 任何方向都已 ≥ red_years
    没有往来；③ 他从未随过你，或他的折算总流入不足你流出的一半。"""
    bal = balance_of(pool, as_of, inflation)
    if bal > -red_amount:
        return False
    last = last_event_date(pool)
    if last is None or (as_of - last).days < red_years * 365.25:
        return False
    inflow = sum(adjust(e.amount, e.date, as_of, inflation)
                 for e in pool if e.direction == "in")
    outflow = sum(adjust(e.amount, e.date, as_of, inflation)
                  for e in pool if e.direction == "out")
    return inflow < outflow / 2.0


# ---------------------------------------------------------------------------
# 建议区间
# ---------------------------------------------------------------------------

def baseline(base: float, relation: str, occasion: str) -> float:
    return base * RELATIONS[relation][0] * OCCASIONS[occasion][0]


def price_anchor(pool: List[Event], occasion: str, as_of: dt.date,
                 inflation: float) -> Optional[tuple]:
    """对价锚：对方最近一次同场合随给你的折算值。白事不通胀、不讲对价。"""
    if occasion == "funeral":
        return None
    cands = [e for e in pool
             if e.direction == "in" and e.occasion == occasion]
    if not cands:
        return None
    e = max(cands, key=lambda x: x.date)
    return (adjust(e.amount, e.date, as_of, inflation), e)


def suggest_band(pool: List[Event], relation: str, occasion: str,
                 as_of: dt.date, inflation: float, base: float) -> dict:
    """建议区间 [lower, upper]：

    B = 基线 × 关系系数 × 场合系数（今日场面骨架）
    anchor = 对方同场合随礼的今日对价（婚对婚的直接对价，通胀折算）
    D = 未平的人情余额（你欠着的部分，封顶 2B——大额旧账还一半）
    lower = max(0.8B, anchor, min(D, 2B))；upper = max(1.5B, 1.25×lower)
    """
    bal = balance_of(pool, as_of, inflation)
    d_owed = max(0.0, bal)
    b = baseline(base, relation, occasion)
    anchor_pair = price_anchor(pool, occasion, as_of, inflation)
    anchor = anchor_pair[0] if anchor_pair else 0.0
    lower = max(0.8 * b, anchor, min(d_owed, 2 * b))
    upper = max(1.5 * b, 1.25 * lower)
    return {
        "lower": lower, "upper": upper, "base": b, "anchor": anchor,
        "anchor_event": anchor_pair[1] if anchor_pair else None,
        "owed": d_owed, "balance": bal,
    }


def ceil10(x: float) -> int:
    return int(math.ceil(x / 10.0) * 10)


def floor10(x: float) -> int:
    return max(0, int(math.floor(x / 10.0) * 10))


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def money(x: float) -> str:
    return "%.0f" % x


def header(ledger: str, events: List[Event], as_of: dt.date,
           inflation: float) -> str:
    parties = sorted({e.party for e in events})
    return "\n".join([
        "人情账 · Gift Ledger — 随礼是支付，人情是余额 v%s" % VERSION,
        "账本 %s（%d 笔 / %d 人）  基准日 %s  折算通胀 %.1f%%" % (
            ledger, len(events), len(parties), as_of, inflation * 100),
        "",
    ])


def verdict_of(bal: float, pool: List[Event], as_of: dt.date,
               inflation: float) -> str:
    flow = sum(adjust(e.amount, e.date, as_of, inflation) for e in pool)
    band = max(200.0, 0.15 * flow)
    if abs(bal) < band:
        return "balanced"
    return "你欠人情" if bal > 0 else "他欠人情"


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def cmd_ledger(args) -> str:
    events = parse_ledger(args.ledger)
    if not events:
        raise Refusal("账本是空的：先记一笔（date/direction/party/relation/"
                      "occasion/amount）再来对账")
    validate_calendar(events, args.as_of)
    in_total = sum(adjust(e.amount, e.date, args.as_of, args.inflation)
                   for e in events if e.direction == "in")
    out_total = sum(adjust(e.amount, e.date, args.as_of, args.inflation)
                    for e in events if e.direction == "out")
    span = (min(e.date for e in events), max(e.date for e in events))
    rel_line = " · ".join("%s %.1f" % (k, v[0]) for k, v in RELATIONS.items())
    occ_line = " · ".join("%s %.1f" % (k, v[0]) for k, v in OCCASIONS.items())
    parts = [header(args.ledger, events, args.as_of, args.inflation)]
    parts.append("  笔数     %d 笔（in %d · out %d）" % (
        len(events),
        sum(1 for e in events if e.direction == "in"),
        sum(1 for e in events if e.direction == "out")))
    parts.append("  跨度     %s → %s" % span)
    parts.append("  今日值   收进 %s 元 · 随出 %s 元（折算到 %s 购买力）"
                 % (money(in_total), money(out_total), args.as_of))
    parts.append("  总余额   %s 元（正 = 人情市场整体欠你的）"
                 % money(in_total - out_total))
    parts.append("")
    parts.append("  关系系数（×基线）：%s" % rel_line)
    parts.append("  场合系数（×基线）：%s" % occ_line)
    parts.append("")
    parts.append("  基线 %s 元 = wedding × friend 的今日骨架，suggest --base 可整体校准，"
                 "--inflation 可换折算率。" % money(DEFAULT_BASE))
    return "\n".join(parts)


def cmd_balance(args) -> str:
    events = parse_ledger(args.ledger)
    if not events:
        raise Refusal("账本是空的：balance 需要至少一笔往来")
    validate_calendar(events, args.as_of)
    pool = pick_party(events, args.party)
    bal = balance_of(pool, args.as_of, args.inflation)
    in_total = sum(adjust(e.amount, e.date, args.as_of, args.inflation)
                   for e in pool if e.direction == "in")
    out_total = sum(adjust(e.amount, e.date, args.as_of, args.inflation)
                    for e in pool if e.direction == "out")
    v = verdict_of(bal, pool, args.as_of, args.inflation)
    latest_rel = pool[-1].relation
    parts = [header(args.ledger, events, args.as_of, args.inflation)]
    flags = [RELATIONS[latest_rel][1]]
    if is_blackhole(pool, args.as_of, args.inflation,
                    args.red_years, args.red_amount):
        flags.append("礼崩风险")
    parts.append("  %s   %s" % (args.party, " · ".join(flags)))
    parts.append("")
    parts.append("  他随给你（折算） %s 元   你随给他（折算） %s 元"
                 % (money(in_total), money(out_total)))
    parts.append("  净余额     %s 元（正 = 你欠着人情）" % money(bal))
    parts.append("  判定       %s" % v)
    parts.append("")
    gap_days = (args.as_of - max(e.date for e in pool)).days
    parts.append("  逐笔对账（折算到 %s）· 最近一次往来在 %d 天前："
                 % (args.as_of, gap_days))
    for e in pool:
        adj = adjust(e.amount, e.date, args.as_of, args.inflation)
        arrow = "收" if e.direction == "in" else "随"
        note = ("  # " + e.raw[6]) if len(e.raw) > 6 and e.raw[6] else ""
        parts.append("    %s  %s  %-14s %-8s %6s 元 → 今日值 %s 元%s"
                     % (e.date, arrow, e.party, e.occasion, money(e.amount),
                        money(adj), note))
    return "\n".join(parts)


def cmd_suggest(args) -> str:
    events = parse_ledger(args.ledger)
    if not events:
        raise Refusal("账本是空的：suggest 需要历史往来才能对价")
    validate_calendar(events, args.as_of)
    pool = pick_party(events, args.party)
    latest_rel = pool[-1].relation
    band = suggest_band(pool, latest_rel, args.occasion, args.as_of,
                        args.inflation, args.base)
    lower, upper = ceil10(band["lower"]), floor10(band["upper"])
    if lower > upper:
        lower = upper
    parts = [header(args.ledger, events, args.as_of, args.inflation)]
    parts.append("请帖场景：%s · 关系系数 %.1f（%s）  场合 %s（系数 %.1f）" % (
        args.party, RELATIONS[latest_rel][0],
        RELATIONS[latest_rel][1], args.occasion,
        OCCASIONS[args.occasion][0]))
    parts.append("")
    parts.append("  场面骨架   基线 %s × 关系 %.1f × 场合 %.1f = %s 元"
                 % (money(args.base), RELATIONS[pool[0].relation][0],
                    OCCASIONS[args.occasion][0], money(band["base"])))
    if band["anchor_event"] is not None:
        ae = band["anchor_event"]
        parts.append("  对价锚     %s 他随你 %s 元（%s %s）→ 今日对价 %s 元"
                     % (ae.date, money(ae.amount), ae.occasion,
                        "收" if ae.direction == "in" else "随",
                        money(band["anchor"])))
    else:
        parts.append("  对价锚     无——他从没随过你这个场合（%s）"
                     % ("白事不讲对价" if args.occasion == "funeral" else "按骨架走"))
    if band["owed"] > 0:
        capped = min(band["owed"], 2 * band["base"])
        parts.append("  未平余额   你欠着 %s 元，本次计入下限 %s 元%s"
                     % (money(band["owed"]), money(capped),
                        "（大额旧账只还一半，剩下的不是一张请帖能平的）"
                        if band["owed"] > 2 * band["base"] else ""))
    parts.append("")
    parts.append("  建议区间   %d – %d 元" % (lower, upper))
    if is_blackhole(pool, args.as_of, args.inflation,
                    args.red_years, args.red_amount):
        parts.append("")
        parts.append("  ⚠ 这段关系已是礼崩（只进不出超线）：先想清楚还 要不要 维持，")
        parts.append("    再想随多少——金额救不了方向。")
    return "\n".join(parts)


def cmd_book(args) -> str:
    events = parse_ledger(args.ledger)
    if not events:
        raise Refusal("账本是空的：book 需要至少一笔往来")
    validate_calendar(events, args.as_of)
    parties = sorted({e.party for e in events})
    rows = []
    holes = []
    for p in parties:
        pool = pick_party(events, p)
        bal = balance_of(pool, args.as_of, args.inflation)
        v = verdict_of(bal, pool, args.as_of, args.inflation)
        if is_blackhole(pool, args.as_of, args.inflation,
                        args.red_years, args.red_amount):
            holes.append((p, bal, v))
            v = "礼崩"
        rows.append((p, bal, v))
    rows.sort(key=lambda r: -r[1])
    parts = [header(args.ledger, events, args.as_of, args.inflation)]
    parts.append("全员余额排行（正 = 你欠他；最上方是你最该记着的人）")
    parts.append("")
    parts.append("  %-14s %10s  %-10s %s" % ("对方", "净余额", "判定", "备注"))
    for p, bal, v in rows:
        note = ""
        if v == "礼崩":
            pool = pick_party(events, p)
            last = last_event_date(pool)
            note = "自 %s 起再无往来" % last
        parts.append("  %-14s %10s  %-10s %s" % (p, money(bal), v, note))
    parts.append("")
    parts.append("  全账总余额 %s 元  ·  balanced %d · 你欠 %d · 他欠 %d · 礼崩 %d"
                 % (money(sum(r[1] for r in rows)),
                    sum(1 for r in rows if r[2] == "balanced"),
                    sum(1 for r in rows if r[2] == "你欠人情"),
                    sum(1 for r in rows if r[2] == "他欠人情"),
                    len(holes)))
    if holes:
        parts.append("")
        parts.append("  礼崩的意思：不是「该去讨债」，是这段关系只剩一个方向——")
        parts.append("  维持、降温还是了断，是人的决定；账本只拒绝假装没看见。")
        raise GiftGate("\n".join(parts))
    return "\n".join(parts)


def cmd_inflation(args) -> str:
    events = parse_ledger(args.ledger)
    if not events:
        raise Refusal("账本是空的：inflation 需要你的随礼史")
    validate_calendar(events, args.as_of)
    outs = [e for e in events if e.direction == "out"]
    if len(outs) < 4:
        raise Refusal("随出样本不足（%d 笔，至少 4 笔）——没法从自己的历史里"
                      "读出通胀" % len(outs))
    by_year: Dict[int, List[float]] = {}
    for e in outs:
        by_year.setdefault(e.date.year, []).append(e.amount)
    years = sorted(y for y, amounts in by_year.items() if len(amounts) >= 2)
    if len(years) < 2 or years[-1] == years[0]:
        raise Refusal("至少需要两个各含 2 笔随出的年份——样本太薄，先用假设值")
    medians = {y: sorted(by_year[y])[len(by_year[y]) // 2] for y in years}
    y0, y1 = years[0], years[-1]
    rate = math.pow(medians[y1] / medians[y0], 1.0 / (y1 - y0)) - 1.0
    parts = [header(args.ledger, events, args.as_of, args.inflation)]
    parts.append("你的随礼通胀（只看你随出的中位数）：")
    for y in years:
        parts.append("    %d   中位 %s 元（%d 笔）" % (y, money(medians[y]),
                                                    len(by_year[y])))
    parts.append("")
    parts.append("  自证年化   %.1f%%（%d → %d 年）" % (rate * 100, y0, y1))
    parts.append("  当前假设   %.1f%%（--inflation）" % (args.inflation * 100))
    if abs(rate - args.inflation) > 0.02:
        parts.append("  两者差超过 2 个点：重跑时建议 --inflation %.2f，"
                     "让折算长在你自己的历史上。" % rate)
    else:
        parts.append("  与假设基本一致——折算率站得住。")
    parts.append("")
    parts.append("  这是感受锚，不是 CPI：要和官方数据对比请自行带入，")
    parts.append("  随礼通胀常年跑赢 CPI——它随的是面子，不是篮子。")
    return "\n".join(parts)


def cmd_simulate(args) -> str:
    events = parse_ledger(args.ledger)
    if not events:
        raise Refusal("账本是空的：simulate 需要历史往来")
    if args.occasion not in OCCASIONS:
        raise UsageError("未知场合 %r（可选：%s）"
                         % (args.occasion, " / ".join(OCCASIONS)))
    validate_calendar(events, args.as_of)
    if args.amount <= 0:
        raise UsageError("--amount 必须为正")
    pool = pick_party(events, args.party)
    bal = balance_of(pool, args.as_of, args.inflation)
    new_bal = bal - args.amount
    band = suggest_band(pool, pool[-1].relation, args.occasion, args.as_of,
                        args.inflation, args.base)
    lower, upper = ceil10(band["lower"]), floor10(band["upper"])
    flow = sum(adjust(e.amount, e.date, args.as_of, args.inflation)
               for e in pool)
    parts = [header(args.ledger, events, args.as_of, args.inflation)]
    parts.append("若今天随 %s 元给 %s（%s）：" % (money(args.amount), args.party,
                                               args.occasion))
    parts.append("")
    even_note = ("（这次随完，账就平得差不多了）"
                 if abs(new_bal) < max(200.0, 0.15 * flow) else "")
    parts.append("  余额     %s 元 → %s 元 %s"
                 % (money(bal), money(new_bal), even_note))
    anchor_years = 2.0
    future_anchor = args.amount * math.pow(1.0 + args.inflation, anchor_years)
    parts.append("  传播     %g 年后他办同场合喜事，对价锚将变成 %s 元——"
                 % (anchor_years, money(future_anchor)))
    in_low = args.amount < lower
    if in_low and band["balance"] > 0:
        note = "低于下限：旧账仍在，别怪对方记仇"
    elif in_low:
        note = "低于区间下限：场面骨架要求更多"
    else:
        note = "在区间内"
    parts.append("  对照     本次建议区间 %d – %d 元，你的 %s 元——%s"
                 % (lower, upper, money(args.amount), note))
    parts.append("")
    parts.append("  随礼是会传染的定价：你抬的每一档，都是他下一次的起点。")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command")

    def add_common(sp):
        sp.add_argument("ledger")
        sp.add_argument("--as-of", default=None, dest="as_of",
                        help="基准日 YYYY-MM-DD，缺省今天（复现时务必钉死）")
        sp.add_argument("--inflation", type=float, default=DEFAULT_INFLATION,
                        help="折算年化通胀（缺省 %.2f）" % DEFAULT_INFLATION)

    def as_of_of(args) -> dt.date:
        if args.as_of:
            return parse_date(args.as_of, "--as-of")
        return dt.date.today()

    def attach(fn):
        def wrapped(args):
            args.as_of = as_of_of(args)
            if args.inflation <= -1.0:
                raise UsageError("--inflation 必须 > -1（购买力不能是负的）")
            return fn(args)
        return wrapped

    sp = sub.add_parser("ledger", help="账本体检 + 系数表")
    add_common(sp)
    sp.set_defaults(func=attach(cmd_ledger))

    sp = sub.add_parser("balance", help="单人对账：双向折算、净余额、逐笔")
    add_common(sp)
    sp.add_argument("party")
    sp.add_argument("--red-years", type=float, default=DEFAULT_RED_YEARS)
    sp.add_argument("--red-amount", type=float, default=DEFAULT_RED_AMOUNT)
    sp.set_defaults(func=attach(cmd_balance))

    sp = sub.add_parser("suggest", help="请帖之夜的建议区间")
    add_common(sp)
    sp.add_argument("party")
    sp.add_argument("--occasion", required=True,
                    help="场合（wedding/baby/housewarming/birthday/illness/funeral）")
    sp.add_argument("--base", type=float, default=DEFAULT_BASE,
                    help="基线（缺省 %.0f 元）" % DEFAULT_BASE)
    sp.add_argument("--red-years", type=float, default=DEFAULT_RED_YEARS)
    sp.add_argument("--red-amount", type=float, default=DEFAULT_RED_AMOUNT)
    sp.set_defaults(func=attach(cmd_suggest))

    sp = sub.add_parser("book", help="全员余额排行 + 礼崩名单（有礼崩 → exit 4）")
    add_common(sp)
    sp.add_argument("--red-years", type=float, default=DEFAULT_RED_YEARS)
    sp.add_argument("--red-amount", type=float, default=DEFAULT_RED_AMOUNT)
    sp.set_defaults(func=attach(cmd_book))

    sp = sub.add_parser("inflation", help="从你的随礼史自证通胀率")
    add_common(sp)
    sp.set_defaults(func=attach(cmd_inflation))

    sp = sub.add_parser("simulate", help="若今天随 X：余额与对价的传导")
    add_common(sp)
    sp.add_argument("party")
    sp.add_argument("--amount", type=float, required=True)
    sp.add_argument("--occasion", default="wedding")
    sp.add_argument("--base", type=float, default=DEFAULT_BASE)
    sp.set_defaults(func=attach(cmd_simulate))

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        text = args.func(args)
    except UsageError as exc:
        print("用法错误：%s" % exc, file=sys.stderr)
        return 2
    except Refusal as exc:
        print("拒算：%s" % exc, file=sys.stderr)
        return 3
    except GiftGate as exc:
        print(exc)
        return 4
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
