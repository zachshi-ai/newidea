#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flat-split · 同檐 —— 合租分摊对账账本.

问题:微信 AA 只管单笔,长期共住的账没有账本。合租屋里的钱分三类:
每月的水电燃气网物业(按人头还是按表?「电费凭什么平摊」是每间合租
屋都吵过的架);垫付(「你先交一下网费」三个月后就说不清谁欠谁);
公共资产(我买的 3000 块洗衣机,室友搬走时白送不甘心、卖掉不值钱)。
所有这些只活在每个人的记忆里——而每个人的记忆都对自己有利。

flat-split 把合租记成四本手编账(household 名册区间 / bills 共同账
单 / meters 表读数 / assets 公共资产),对同一本账开四个命令:
report 逐月分摊总表(应付·垫付·净额 + 表损与垫付集中度判灯)、
settle 净额清算(整月几十笔转账压成一笔,Σ净额恒为零和)、assets 公
共资产台账(直线折旧 usage charge + 「走了的人白住了」GAP 审计)、
validate 账本体检(双路径重放 + 恒等式)。

三条设计立场:
  * 分摊规则没有天然正义:按人头有按人头的理(房间一样大),按表有
    按表的理(空调 24 小时开)。机器只执行账本里逐单声明的规则,规则
    之争要室友当面谈——账本不是法官,是会计。
  * 走掉的人的账必须当场结:资产 usage 是按月滚的应收,长期不记回
    收账,等室友搬走才想起来——那笔账永远收不回了(摊派只及在住
    者)。GAP 灯点名的就是这个:从入住到退租,一笔回收账都没有。
  * 全部阈值是通识先验且全部可翻案(表损容差 --loss-cap、折旧年限
    --years、集中度线 --skew-cap);没有先验的科目如实不判——没
    有先验就不判级,不装懂。

零依赖:Python 3.8+ 标准库。无墙钟:缺省 as-of 锚定账本最大日期,
`--as-of` 钉死即逐字节可复现——同账任何机器任何一天输出一致。

Exit codes:
  0  报告产出(无灯)   2  usage/账坏(坏行/悬空引用/抄表断裂)
  3  refusal: 还没开始记(无账单行)   4  gate: LOSS/SKEW/GAP 任一
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import decimal
import os
import re
import sys
import unicodedata
from decimal import Decimal as D
from typing import Dict, List, Optional, Tuple

PROG = "flat-split"
VERSION = "1.0.0"

Q2 = D("0.01")
D0 = D("0")

# ---------------------------------------------------------------- 先验
# 公共资产品类 → 折旧年限(年)。直线折旧的通识先验;账本 years 列
# 一句话翻案,未知品类如实 n/a 不判 GAP——本地知识赢,不发明没教过的。
BUILTIN_YEARS: Dict[str, int] = {
    "洗衣机": 8, "冰箱": 8, "空调": 8, "电视": 8, "热水器": 8,
    "沙发": 5, "床": 5, "衣柜": 5, "餐桌": 5, "书桌": 5, "书架": 5,
    "路由器": 4,
    "微波炉": 3, "电饭煲": 3, "热水壶": 3, "吸尘器": 3, "风扇": 3,
}

# 品类别名归一(手编账本的叫法五花八门,品类只有一个)
CATEGORY_ALIASES = {
    "电热水器": "热水器", "燃气热水器": "热水器",
    "电热水壶": "热水壶", "电水壶": "热水壶", "烧水壶": "热水壶",
    "桌子": "餐桌", "椅子": "餐桌", "柜子": "衣柜",
    "wifi": "路由器", "路由": "路由器",
    "洗衣机 ": "洗衣机",
}

# 按表科目的表损容差(公区+线路损耗占总增量的比例上限)。通识保守线,
# --loss-cap 一句话翻案;无先验的科目只摊派不判灯。
BUILTIN_LOSS_CAP: Dict[str, D] = {
    "electricity": D("0.08"),
    "water": D("0.12"),
    "gas": D("0.05"),
}

METER_CATS = {"electricity", "water", "gas"}
LOSS_CAP = D("0.08")     # --loss-cap 全局翻案值
SKEW_CAP = D("0.80")     # 月内 top1 垫付占比线(恰线不亮)
SKEW_MONTHS = 3          # 连续月数门槛(恰 3 个月亮)
SKEW_MIN_BILLS = 2       # 月内账单笔数门槛(单笔月不参与)

# ---------------------------------------------------------------- 归一
def norm(s: str) -> str:
    """名字归一:NFKC + 去全部空白 + 小写——手抄差异不分裂账本."""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s).lower()


def norm_cat(s: str) -> str:
    """科目归一:中文科目名 → 规范英文;查不到按通用归一返回(供资产匹配)."""
    n = norm(s)
    table = {
        "电": "electricity", "电费": "electricity", "electricity": "electricity",
        "电表": "electricity",
        "水": "water", "水费": "water", "water": "water", "水表": "water",
        "燃气": "gas", "煤气": "gas", "气": "gas", "气费": "gas",
        "gas": "gas", "燃气费": "gas",
        "网": "internet", "网费": "internet", "宽带": "internet",
        "internet": "internet", "网络": "internet",
        "物业": "property", "物业费": "property", "property": "property",
    }
    return table.get(n, n)


def norm_asset_cat(s: str) -> str:
    """资产品类归一:先通用归一,再查别名录."""
    n = norm(s)
    return CATEGORY_ALIASES.get(n, n)


# ---------------------------------------------------------------- 小工具
def money(d: D) -> str:
    return f"{d.quantize(Q2, rounding=decimal.ROUND_HALF_UP)}"


def pct(d: D) -> str:
    return f"{(d * 100).quantize(Q2, rounding=decimal.ROUND_HALF_UP)}%"


def parse_date(s: str, ctx: str) -> dt.date:
    s = s.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise BadLedger(f"{ctx}: 日期须为 YYYY-MM-DD 补零格式,得到「{s}」")
    try:
        return dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        raise BadLedger(f"{ctx}: 不是真实存在的日期「{s}」")


def parse_money(s: str, ctx: str, positive: bool = True) -> D:
    try:
        d = D(s.strip())
    except Exception:
        raise BadLedger(f"{ctx}: 金额不是合法数字「{s}」")
    if positive and d <= 0:
        raise BadLedger(f"{ctx}: 金额必须为正数,得到「{s}」")
    if not positive and d < 0:
        raise BadLedger(f"{ctx}: 金额不能为负,得到「{s}」")
    return d


class BadLedger(Exception):
    """账坏/用法错 → exit 2."""
    pass


class Refuse(Exception):
    """薄账分层:账还没开始记 → exit 3(不是账坏,是没开始)."""
    pass


def month_of(d: dt.date) -> Tuple[int, int]:
    return (d.year, d.month)


def month_add(ym: Tuple[int, int], k: int) -> Tuple[int, int]:
    y, m = ym[0], ym[1] - 1 + k
    return (y + m // 12, m % 12 + 1)


def month_str(ym: Tuple[int, int]) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def month_end(ym: Tuple[int, int]) -> dt.date:
    return dt.date(ym[0], ym[1], calendar.monthrange(ym[0], ym[1])[1])


def month_first(ym: Tuple[int, int]) -> dt.date:
    return dt.date(ym[0], ym[1], 1)


def month_range(a: Tuple[int, int], b: Tuple[int, int]) -> List[Tuple[int, int]]:
    """[a..b] 闭区间逐月,∅ 若 a>b."""
    out = []
    cur = a
    while cur <= b:
        out.append(cur)
        cur = month_add(cur, 1)
    return out


# ---------------------------------------------------------------- 账本载入
class Person:
    __slots__ = ("name", "room", "start", "end")

    def __init__(self, name, room, start, end):
        self.name, self.room, self.start, self.end = name, room, start, end

    def end_eff(self, as_of: dt.date) -> dt.date:
        return self.end if (self.end and self.end <= as_of) else as_of

    def departed(self, as_of: dt.date) -> bool:
        return bool(self.end) and self.end <= as_of

    def days_in(self, d0: dt.date, d1: dt.date, as_of: dt.date) -> int:
        """与 [d0,d1] 闭区间交集天数;未入住的区间(after as_of)不产生人日."""
        if self.start > as_of:
            return 0
        e = self.end_eff(as_of)
        lo, hi = max(self.start, d0), min(e, d1)
        return max(0, (hi - lo).days + 1)

    def active_in_month(self, ym: Tuple[int, int], as_of: dt.date) -> bool:
        if self.start > as_of:
            return False
        return (self.start <= month_end(ym)
                and self.end_eff_for_month(ym) >= month_first(ym))

    def end_eff_for_month(self, ym: Tuple[int, int]) -> dt.date:
        """月尺度在住判断:未退租(end 空或晚于月末)按月末算."""
        if self.end is None:
            return month_end(ym)
        return min(self.end, month_end(ym))


class Bill:
    __slots__ = ("date", "cat", "amount", "rule", "payer", "note", "line")

    def __init__(self, date, cat, amount, rule, payer, note, line):
        self.date, self.cat, self.amount = date, cat, amount
        self.rule, self.payer, self.note, self.line = rule, payer, note, line


class Ledger:
    def __init__(self, root: str):
        self.root = root
        self.basename = os.path.basename(os.path.abspath(root))
        self.people: List[Person] = []
        self.bills: List[Bill] = []
        self.meters: Dict[Tuple[str, str], Dict[dt.date, D]] = {}
        # meters[(cat_norm, room_norm)][date] = reading;room "_total" = 总表
        self.assets: Dict[str, dict] = {}
        self.person_by_norm: Dict[str, Person] = {}
        self.room_norms: Dict[str, str] = {}  # room_norm → 原名

    # ---------- TSV 基础 ----------
    def _rows(self, path: str, min_cols: int, ctx: str) -> Tuple[List[str], List[List[str]]]:
        """返回 (表头, 数据行[cells + lineno]).#注释与空行跳过;行尾制表符
        容忍(手编/粘贴日常);可选尾列(household 的 end、assets 的 years)
        常为空——行尾的空不是缺列,缺列以 min_cols 计."""
        if not os.path.exists(path):
            return None, []
        with open(path, encoding="utf-8") as f:
            text = f.read()
        header, data = None, []
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.rstrip("\t")          # 行尾制表符容忍
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            cells = line.split("\t")
            if header is None:
                header = cells
                continue
            if len(cells) < min_cols:
                raise BadLedger(f"{ctx} 第 {lineno} 行:缺列(至少 {min_cols} 列),"
                                f"得到 {len(cells)} 列")
            data.append(cells + [str(lineno)])
        return header, data

    # ---------- 各表 ----------
    def load(self):
        self._load_household()
        self._load_bills()
        self._load_meters()
        self._load_assets()

    def _load_household(self):
        path = os.path.join(self.root, "household.tsv")
        header, rows = self._rows(path, 3, "household")
        if header is None:
            raise BadLedger(f"缺 household.tsv(名册是账本的地基):{path}")
        spans: Dict[str, List[Tuple[dt.date, Optional[dt.date]]]] = {}
        for cells in rows:
            line = cells[-1]
            name = cells[0].strip()
            room = cells[1].strip()
            e = cells[3].strip() if len(cells) >= 5 else ""
            if not name or not room:
                raise BadLedger(f"household 第 {line} 行:person/room 不能为空")
            start = parse_date(cells[2], f"household 第 {line} 行 {name}")
            end = parse_date(e, f"household 第 {line} 行 {name}") if e else None
            if end and end < start:
                raise BadLedger(f"household 第 {line} 行:退租 {end} 早于入住 {start}")
            spans.setdefault(norm(name), []).append((start, end, line))
            self.room_norms.setdefault(norm(room), room)
            p = Person(name, room, start, end)
            if norm(name) in self.person_by_norm:
                # 同人多区间:允许(搬出去又搬回来),但不许重叠
                pass
            self.people.append(p)
            self.person_by_norm[norm(name)] = p
        for n, lst in spans.items():
            lst.sort()
            for (s1, e1, l1), (s2, _, l2) in zip(lst, lst[1:]):
                if e1 is None or (e1 and s2 <= e1):
                    raise BadLedger(
                        f"household:{lst[0]} 名下区间重叠(第 {l1} 行与第 {l2} 行)")

    def person(self, name: str, ctx: str) -> Person:
        p = self.person_by_norm.get(norm(name))
        if p is None:
            raise BadLedger(f"{ctx}: 人名「{name}」不在名册里(household.tsv)")
        return p

    def _load_bills(self):
        path = os.path.join(self.root, "bills.tsv")
        header, rows = self._rows(path, 5, "bills")
        if header is None or not rows:
            self.bills = []
            return
        for cells in rows:
            line = cells[-1]
            d, cat, amt, rule, payer = (c.strip() for c in cells[:5])
            note = ""
            date = parse_date(d, f"bills 第 {line} 行")
            amount = parse_money(amt, f"bills 第 {line} 行")
            rule = norm(rule)
            if rule not in ("per_head", "by_meter"):
                raise BadLedger(
                    f"bills 第 {line} 行:未知分摊规则「{rule}」(per_head | by_meter)")
            self.person(payer, f"bills 第 {line} 行 payer")
            cat_n = norm_cat(cat)
            if rule == "by_meter" and cat_n not in METER_CATS:
                raise BadLedger(
                    f"bills 第 {line} 行:科目「{cat}」无按表分摊先验"
                    f"(仅 电/水/燃气 支持 by_meter)")
            self.bills.append(Bill(date, cat_n, amount, rule, norm(payer), note, line))

    def _load_meters(self):
        path = os.path.join(self.root, "meters.tsv")
        header, rows = self._rows(path, 4, "meters")
        for cells in rows:
            line = cells[-1]
            d, cat, room, val = (c.strip() for c in cells[:4])
            date = parse_date(d, f"meters 第 {line} 行")
            reading = parse_money(val, f"meters 第 {line} 行", positive=False)
            cat_n = norm_cat(cat)
            if cat_n not in METER_CATS:
                raise BadLedger(f"meters 第 {line} 行:未知抄表科目「{cat}」")
            room_n = norm(room)
            if room_n != "_total" and room_n not in self.room_norms:
                raise BadLedger(f"meters 第 {line} 行:房间「{room}」不在名册里")
            key = (cat_n, room_n)
            slot = self.meters.setdefault(key, {})
            if date in slot:
                raise BadLedger(
                    f"meters 第 {line} 行:{cat} {room} 在 {date} 已有读数(重复抄表)")
            slot[date] = reading
        # 读数倒退 + 抄表日必须有总表
        for (cat_n, room_n), slot in self.meters.items():
            dates = sorted(slot)
            for d1, d2 in zip(dates, dates[1:]):
                if slot[d2] < slot[d1]:
                    raise BadLedger(
                        f"meters:{cat_n} {room_n} 读数倒退({d1} {slot[d1]} → {d2} {slot[d2]})")
        for (cat_n, room_n) in list(self.meters):
            if room_n == "_total":
                continue
            for d in self.meters[(cat_n, room_n)]:
                if (cat_n, "_total") not in self.meters or d not in self.meters[(cat_n, "_total")]:
                    raise BadLedger(
                        f"meters:{cat_n} {d} 的房间读数缺少同日总表(_total)读数")

    def meter_dates(self, cat: str) -> List[dt.date]:
        slot = self.meters.get((cat, "_total"), {})
        return sorted(slot)

    def _load_assets(self):
        path = os.path.join(self.root, "assets.tsv")
        header, rows = self._rows(path, 5, "assets")
        for cells in rows:
            line = cells[-1]
            d = cells[0].strip()
            name = cells[1].strip()
            cat = cells[2].strip()
            cost = cells[3].strip()
            funder = cells[4].strip()
            years = cells[5].strip() if len(cells) >= 7 else ""
            date = parse_date(d, f"assets 第 {line} 行")
            cost_d = parse_money(cost, f"assets 第 {line} 行")
            self.person(funder, f"assets 第 {line} 行 funder")
            y = None
            if years:
                if not re.fullmatch(r"\d+", years) or int(years) <= 0:
                    raise BadLedger(
                        f"assets 第 {line} 行:折旧年限须为正整数年,得到「{years}」")
                y = int(years)
            n = norm(name)
            a = self.assets.setdefault(n, {
                "name": name, "date": date, "cost": D0,
                "cat": norm_asset_cat(cat), "years": y,
                "funders": {}, "disposed": None, "line": line,
            })
            a["cost"] += cost_d
            a["funders"][norm(funder)] = a["funders"].get(norm(funder), D0) + cost_d
            if y and a["years"] is None:
                a["years"] = y
            if date < a["date"]:
                a["date"] = date

    # ---------- 尾注 ----------
    def max_date(self) -> Optional[dt.date]:
        ds = [b.date for b in self.bills]
        for slot in self.meters.values():
            ds.extend(slot)
        for a in self.assets.values():
            ds.append(a["date"])
            if a["disposed"]:
                ds.append(a["disposed"])
        for p in self.people:
            ds.append(p.start)
            if p.end:
                ds.append(p.end)
        return max(ds) if ds else None


# ---------------------------------------------------------------- 分摊
def allocate(led: Ledger, bill: Bill, as_of: dt.date) -> List[Tuple[str, D]]:
    """把一笔账单摊成 [(norm_name, 全精度金额)],Σ≡amount.

    per_head: bill 当月在住者按人日加权。
    by_meter: 上一个抄表日→本单日的段内,房间增量归房间(段内在住者按
    人日),公区损耗(总增量−Σ房间增量)按全员段内人日;空房间份额并入
    公区——空房走表说明有公共用途或漏损,不该由谁独担。
    """
    people = [p for p in led.people if p.start <= as_of]
    if bill.rule == "per_head":
        ym = month_of(bill.date)
        d0, d1 = month_first(ym), month_end(ym)
        weights = [(p, D(p.days_in(d0, d1, as_of))) for p in people]
        parts = weighted_split(led, bill, [w for _, w in weights],
                               [p for p, _ in weights])
        return merge_parts(parts, bill.amount)
    # by_meter
    dates = led.meter_dates(bill.cat)
    if bill.date not in dates:
        raise BadLedger(
            f"bills 第 {bill.line} 行:by_meter 账单日 {bill.date} 不是 "
            f"{bill.cat} 的抄表日(账本纪律:抄表那天记按表账单)")
    i = dates.index(bill.date)
    if i == 0:
        raise BadLedger(
            f"bills 第 {bill.line} 行:{bill.date} 是 {bill.cat} 首次抄表,"
            f"没有上一期读数,无法按段分摊")
    d0, d1 = dates[i - 1], dates[i]
    t0 = led.meters[(bill.cat, "_total")][d0]
    t1 = led.meters[(bill.cat, "_total")][d1]
    total = t1 - t0
    if total <= 0:
        raise BadLedger(
            f"bills 第 {bill.line} 行:{bill.cat} 总表增量 {total} 度非正,"
            f"无法按表分摊({d0} {t0} → {d1} {t1})")
    rooms = {}
    for (cat_n, room_n), slot in led.meters.items():
        if cat_n == bill.cat and room_n != "_total":
            if d0 not in slot or d1 not in slot:
                raise BadLedger(
                    f"bills 第 {bill.line} 行:房间 {room_n} 在 {d0}~{d1} 段"
                    f"读数不全(抄表断裂)——补读数或删该段账单")
            rooms[room_n] = slot[d1] - slot[d0]
    parts: List[Tuple[str, D]] = []       # (norm_name, 全精度金额)
    public = total                        # 度数:总增量 − 已归房间的增量
    for room_n, delta in sorted(rooms.items()):
        if delta == 0:
            continue
        share = bill.amount * delta / total
        occ = [p for p in people if norm(p.room) == room_n
               and p.days_in(d0, d1, as_of) > 0]
        if not occ:
            continue                      # 空房间度数留在公区(公共用途/漏损)
        public -= delta
        w = [D(p.days_in(d0, d1, as_of)) for p in occ]
        parts.extend(weighted_split(led, bill, w, occ, raw=share))
    if public < 0:
        public = D0                       # 房间增量>总增量:表不对,validate 会点名
    w = [D(p.days_in(d0, d1, as_of)) for p in people]
    if sum(w) == 0:
        raise BadLedger(
            f"bills 第 {bill.line} 行:公区损耗无人可摊(账单期内无人居住)")
    parts.extend(weighted_split(led, bill, w, people, raw=public * bill.amount / total))
    return merge_parts(parts, bill.amount)


def weighted_split(led, bill, weights, owners, raw=None) -> List[Tuple[str, D]]:
    """按人日加权;零权重者不参与(不稀释分母,也不留 0 元噪音行)."""
    pairs = [(o, w) for o, w in zip(owners, weights) if w > 0]
    tw = sum(w for _, w in pairs)
    if tw == 0:
        raise BadLedger(f"bills 第 {bill.line} 行:当月无人居住,账单无人可摊")
    amt = raw if raw is not None else bill.amount
    parts = [(norm(o.name), amt * w / tw) for o, w in pairs]
    return parts


def merge_parts(parts, amount: D) -> List[Tuple[str, D]]:
    """合并同人份额→逐人 quantize→尾差吃给(份额 desc, 名字 asc)第一人.

    恒等式 Σ(逐人) ≡ amount 钉到分——尾差必须有人吃,吃的人必须确定。
    """
    acc: Dict[str, D] = {}
    for n, v in parts:
        acc[n] = acc.get(n, D0) + v
    if not acc:
        raise BadLedger("internal: 分摊结果为空(份额无人可归)")
    order = sorted(acc, key=lambda n: (-acc[n], n))
    q = {n: acc[n].quantize(Q2, rounding=decimal.ROUND_HALF_UP) for n in acc}
    diff = (amount - sum(q.values())).quantize(Q2)
    if diff:
        q[order[0]] = (q[order[0]] + diff).quantize(Q2)
    return [(n, q[n]) for n in sorted(q)]


# ---------------------------------------------------------------- 资产
def asset_usage(led: Ledger, a: dict, as_of: dt.date):
    """→ (役月列表, 每月 usage charge 明细, 月折旧 | None, 累计应收, 寿命月数).

    役月 = 购置次月起至 as-of(或处置)前的完整自然月;as-of 当月不计
    (未满月不冤枉)。usage(m) = 月折旧 ÷ 当月在住人数——整月共同使用
    按人头均摊;月中出入的精确性由 bills 的人日摊派管,资产只按整月。
    """
    years = a["years"]
    if years is None:
        years = BUILTIN_YEARS.get(a["cat"])   # 品类先验垫底,账本列翻案
    if years is None:
        return [], {}, None, None, None
    life_m = years * 12
    monthly = a["cost"] / D(life_m)
    last = month_of(min(as_of, a["disposed"])) if a["disposed"] else month_of(as_of)
    months = month_range(month_add(month_of(a["date"]), 1), month_add(last, -1))
    usage = {}
    for ym in months:
        occ = [p for p in led.people if p.active_in_month(ym, as_of)]
        if occ:
            usage[ym] = monthly / D(len(occ))
    ar = sum(usage.values(), D0)
    return months, usage, monthly, ar, life_m


def asset_gaps(led: Ledger, a: dict, months, usage, as_of: dt.date):
    """「走了的人白住了」审计.

    役月 m 未覆盖 = 截至该月没有一笔回收账(bill.category==资产名)开始
    记账。回收账早于该月 = funder 在住户在住期间就在收,账在动,历史
    滚存视为结清;一笔回收账都没有、或第一笔回收账晚于该月 = 该月的
    usage 没人收过。departed 者名下未覆盖役月的 usage 就是收不回的钱
    ——摊派只及在住者,人走了就永远付不到了。
    → [(person, [(月份, 金额, funder_norm, 份额)], 合计按 funder 拆)]
    """
    recovers = [b for b in led.bills if b.cat == norm(a["name"])]
    first_recover = min((b.date for b in recovers), default=None)
    rows = []
    for p in led.people:
        if not p.departed(as_of):
            continue
        missed = [ym for ym in months
                  if p.active_in_month(ym, as_of) and ym in usage
                  and (first_recover is None or month_of(first_recover) > ym)]
        if not missed:
            continue
        total = sum((usage[ym] for ym in missed), D0)
        raw = [(fn, total * fc / a["cost"]) for fn, fc in
               sorted(a["funders"].items(), key=lambda kv: (-kv[1], kv[0]))]
        parts = [(fn, v.quantize(Q2, rounding=decimal.ROUND_HALF_UP))
                 for fn, v in raw]
        diff = (total - sum(v for _, v in parts)).quantize(Q2)
        if diff:
            parts[0] = (parts[0][0],
                        (parts[0][1] + diff).quantize(Q2))
        rows.append((p, missed, total, parts))
    return rows


# ---------------------------------------------------------------- 灯
def evaluate_gates(led: Ledger, as_of: dt.date,
                   loss_cap: Optional[D] = None,
                   skew_cap: D = SKEW_CAP) -> List[str]:
    """三盏灯各管各的案:LOSS 表损 / SKEW 垫付集中 / GAP 走人白住."""
    gates = []
    # LOSS: 逐段表损。--loss-cap 全局翻案;缺省按科目通识先验。
    caps = ({k: loss_cap for k in BUILTIN_LOSS_CAP} if loss_cap is not None
            else dict(BUILTIN_LOSS_CAP))
    for (cat_n, room_n), slot in sorted(led.meters.items()):
        if room_n != "_total":
            continue
        cap = caps.get(cat_n)
        if cap is None:
            continue
        dates = [d for d in sorted(slot) if d <= as_of]
        for d0, d1 in zip(dates, dates[1:]):
            total = slot[d1] - slot[d0]
            if total <= 0:
                continue
            rooms = sum(
                (s[d1] - s[d0]) for (c, r), s in led.meters.items()
                if c == cat_n and r != "_total")
            loss = (total - rooms) / total
            if loss > cap:
                gates.append(
                    f"🔴 LOSS {led.basename}/{cat_n} {month_str(month_of(d0))}→"
                    f"{month_str(month_of(d1))}:公区+损耗 {money(total - rooms)} 度"
                    f"({pct(loss)})超容差 {pct(cap)}——查漏、查私拉、查表")
    # SKEW: 连续月垫付集中
    by_month: Dict[Tuple[int, int], Dict[str, D]] = {}
    cnt: Dict[Tuple[int, int], int] = {}
    for b in led.bills:
        if b.date > as_of:
            continue
        ym = month_of(b.date)
        by_month.setdefault(ym, {})
        by_month[ym][b.payer] = by_month[ym].get(b.payer, D0) + b.amount
        cnt[ym] = cnt.get(ym, 0) + 1
    streak: Dict[str, List[Tuple[int, int]]] = {}
    for ym in sorted(by_month):
        if cnt[ym] < SKEW_MIN_BILLS:
            continue
        shares = by_month[ym]
        tot = sum(shares.values(), D0)
        top = sorted(shares.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if top[1] / tot > skew_cap:
            streak.setdefault(top[0], []).append(ym)
    for payer, months in streak.items():
        run, best = [], None
        for ym in months:
            if run and month_add(run[-1], 1) == ym:
                run.append(ym)
            else:
                run = [ym]
            if best is None or len(run) > len(best):
                best = run
        if best and len(best) >= SKEW_MONTHS:
            pname = next(p.name for p in led.people if norm(p.name) == payer)
            gates.append(
                f"🔴 SKEW {led.basename}/{pname}:{month_str(best[0])}起连续 "
                f"{len(best)} 个月垫付占比超 {pct(D(SKEW_CAP))}——不是谁坏,"
                f"是有人在替所有人垫钱,该收账了")
    # GAP
    for n in sorted(led.assets):
        a = led.assets[n]
        months, usage, _, _, _ = asset_usage(led, a, as_of)
        for p, missed, total, parts in asset_gaps(led, a, months, usage, as_of):
            gates.append(
                f"🔴 GAP {led.basename}/{p.name}×{a['name']}:在住 {len(missed)} 个役月"
                f"({month_str(missed[0])}~{month_str(missed[-1])})无一笔回收账,"
                f"{money(total)} 永远收不回了——摊派只及在住者")
    return gates


# ---------------------------------------------------------------- 视图
def monthly_report(led: Ledger, as_of: dt.date):
    """→ 按月分组 [(ym, [(bill, [(person, amt)])], 每人应付, 每人垫付)]."""
    out = []
    by_ym: Dict[Tuple[int, int], List[Bill]] = {}
    for b in led.bills:
        if b.date <= as_of:
            by_ym.setdefault(month_of(b.date), []).append(b)
    for ym in sorted(by_ym):
        bills = sorted(by_ym[ym], key=lambda b: (b.date, b.line))
        alloc, paid = {}, {}
        detail = []
        for b in bills:
            shares = allocate(led, b, as_of)
            detail.append((b, shares))
            for n, v in shares:
                alloc[n] = alloc.get(n, D0) + v
            paid[b.payer] = paid.get(b.payer, D0) + b.amount
        out.append((ym, detail, alloc, paid))
    return out


def settle_chain(net: Dict[str, D], led: Ledger) -> List[Tuple[str, str, D]]:
    """贪心最大债↔最大贷;同额按名字序——确定性是逐字节复现的前提."""
    name_of = {norm(p.name): p.name for p in led.people}
    cred = [(v, n) for n, v in net.items() if v > 0]
    debt = [(-v, n) for n, v in net.items() if v < 0]
    cred.sort(key=lambda t: (-t[0], t[1]))
    debt.sort(key=lambda t: (-t[0], t[1]))
    ci = di = 0
    moves = []
    while ci < len(cred) and di < len(debt):
        c_amt, c_n = cred[ci]
        d_amt, d_n = debt[di]
        x = min(c_amt, d_amt)
        moves.append((name_of.get(d_n, d_n), name_of.get(c_n, c_n), x))
        cred[ci] = (c_amt - x, c_n)
        debt[di] = (d_amt - x, d_n)
        if cred[ci][0] == 0:
            ci += 1
        if debt[di][0] == 0:
            di += 1
    return moves


def fmt_person(led, n: str) -> str:
    p = led.person_by_norm.get(n)
    return p.name if p else n


# ---------------------------------------------------------------- 命令
def load_ledger(root: str) -> Ledger:
    if not os.path.isdir(root):
        raise BadLedger(f"账本目录不存在:{root}")
    led = Ledger(root)
    led.load()
    if not led.bills:
        raise Refuse(
            f"这本账还没开始记(bills.tsv 无账单行)。\n"
            f"  账本目录 {led.basename}/ 下:bills.tsv 一行一笔共同账单\n"
            f"  date→category→amount→rule(per_head|by_meter)→payer")
    return led


def resolve_as_of(led: Ledger, as_of_arg: Optional[str]) -> dt.date:
    if as_of_arg:
        return parse_date(as_of_arg, "--as-of")
    d = led.max_date()
    if d is None:
        raise BadLedger("账本里没有任何日期,无法定 as-of")
    return d


def cmd_report(args) -> int:
    led = load_ledger(args.root)
    as_of = resolve_as_of(led, args.as_of)
    rows = monthly_report(led, as_of)
    people = [p for p in led.people if p.start <= as_of]
    names = sorted({norm(p.name) for p in people})
    L = []
    L.append(f"同檐 · Flat Split report — {led.basename}/")
    L.append(f"as-of {as_of}  名册 {len(people)} 人"
             f"(在住 {sum(1 for p in people if not p.departed(as_of))} 人)"
             f"  账单 {sum(len(d) for _, d, _, _ in rows)} 笔"
             f"  资产 {len(led.assets)} 项")
    L.append("")
    grand_alloc, grand_paid = {}, {}
    for ym, detail, alloc, paid in rows:
        total = sum(b.amount for b, _ in detail)
        L.append(f"── {month_str(ym)}  {len(detail)} 笔  ¥{money(total)}")
        L.append("    应付 " + "  ".join(
            f"{fmt_person(led, n)} {money(alloc.get(n, D0))}"
            for n in names if alloc.get(n, D0)))
        L.append("    垫付 " + "  ".join(
            f"{fmt_person(led, n)} {money(paid[n])}" for n in names if n in paid))
        for n, v in alloc.items():
            grand_alloc[n] = grand_alloc.get(n, D0) + v
        for n, v in paid.items():
            grand_paid[n] = grand_paid.get(n, D0) + v
    L.append("")
    L.append("── 全期合计")
    L.append("    应付 " + "  ".join(
        f"{fmt_person(led, n)} {money(grand_alloc.get(n, D0))}" for n in names
        if grand_alloc.get(n, D0)))
    L.append("    垫付 " + "  ".join(
        f"{fmt_person(led, n)} {money(grand_paid.get(n, D0))}" for n in names
        if n in grand_paid))
    net = {n: grand_paid.get(n, D0) - grand_alloc.get(n, D0) for n in
           set(grand_alloc) | set(grand_paid)}
    L.append("    净额 " + "  ".join(
        f"{fmt_person(led, n)} {'+' if net[n] >= 0 else ''}{money(net[n])}"
        for n in sorted(net)))
    L.append(f"    Σ应付 {money(sum(grand_alloc.values(), D0))} ≡ Σ垫付 "
             f"{money(sum(grand_paid.values(), D0))}  Σ净额 "
             f"{money(sum(net.values(), D0))}")
    # by_meter 段披露
    loss_rows = []
    for (cat_n, room_n), slot in sorted(led.meters.items()):
        if room_n != "_total":
            continue
        dates = [d for d in sorted(slot) if d <= as_of]
        for d0, d1 in zip(dates, dates[1:]):
            total = slot[d1] - slot[d0]
            rooms = sum((s[d1] - s[d0]) for (c, r), s in led.meters.items()
                        if c == cat_n and r != "_total")
            loss_rows.append((cat_n, d0, d1, total, rooms,
                              (total - rooms) / total if total > 0 else D0))
    if loss_rows:
        L.append("")
        L.append("── 按表段(公区+损耗占段内总增量)")
        for cat_n, d0, d1, total, rooms, loss in loss_rows:
            L.append(f"    {cat_n} {d0}→{d1}:总 {money(total)}  "
                     f"房间 Σ{money(rooms)}  公区 {pct(loss)}")
    gates = evaluate_gates(led, as_of, args.loss_cap, args.skew_cap)
    if gates:
        L.append("")
        L.append("── 灯")
        L.extend("    " + g for g in gates)
        L.append("")
        L.append("灯的意思是「拿着这本账去和室友当面聊」,不是指控;分摊规则"
                 "没有天然正义,机器只执行账本里声明的规则。")
        print("\n".join(L))
        return 4
    L.append("")
    L.append("三盏灯(表损 LOSS / 垫付集中 SKEW / 走人白住 GAP)此刻全灭。")
    print("\n".join(L))
    return 0


def cmd_settle(args) -> int:
    led = load_ledger(args.root)
    as_of = resolve_as_of(led, args.as_of)
    rows = monthly_report(led, as_of)
    if args.month:
        m = args.month.strip()
        if not re.fullmatch(r"\d{4}-\d{2}", m):
            raise BadLedger(f"--month 须为 YYYY-MM:{args.month}")
        rows = [r for r in rows if month_str(r[0]) == m]
        if not rows:
            raise BadLedger(f"{m} 没有账单(晚于 as-of 的账单不参与)")
    alloc, paid = {}, {}
    for _, detail, a, p in rows:
        for n, v in a.items():
            alloc[n] = alloc.get(n, D0) + v
        for n, v in p.items():
            paid[n] = paid.get(n, D0) + v
    net = {n: paid.get(n, D0) - alloc.get(n, D0)
           for n in set(alloc) | set(paid)}
    L = []
    scope = args.month if args.month else f"全期(截至 as-of {as_of})"
    L.append(f"同檐 · Flat Split settle — {led.basename}/  {scope}")
    L.append("")
    for n in sorted(net):
        v = net[n]
        tag = "应收" if v > 0 else ("应付" if v < 0 else "两清")
        L.append(f"  {fmt_person(led, n)}: {money(abs(v))} {tag}")
    L.append("")
    moves = settle_chain(net, led)
    if moves:
        L.append("最简转账链(贪心最大债↔最大贷;同额按名字序):")
        for d, c, x in moves:
            L.append(f"  {d} → {c}  ¥{money(x)}")
    else:
        L.append("全员两清,没有一笔转账。")
    zero = sum(net.values(), D0)
    L.append("")
    L.append(f"Σ净额 {money(zero)} —— 清算是零和:有人多收的,恰是别人多付的;"
             f"整月几十笔红包,压缩成 {len(moves)} 笔。")
    print("\n".join(L))
    return 0


def cmd_assets(args) -> int:
    led = load_ledger(args.root)
    as_of = resolve_as_of(led, args.as_of)
    L = []
    L.append(f"同檐 · Flat Split assets — {led.basename}/")
    L.append(f"as-of {as_of}")
    L.append("")
    gap_gates = []
    if not led.assets:
        L.append("没有公共资产(assets.tsv 缺失或为空)——合租屋的第一台"
                 "公共电器买回来之前,先想好它退役时怎么算。")
    for n in sorted(led.assets):
        a = led.assets[n]
        funders = " ".join(
            f"{fmt_person(led, fn)} {money(fc)}" for fn, fc in
            sorted(a["funders"].items(), key=lambda kv: (-kv[1], kv[0])))
        L.append(f"── {a['name']}(购置 {a['date']}  ¥{money(a['cost'])}"
                 f"  出资 {funders})")
        months, usage, monthly, ar, life_m = asset_usage(led, a, as_of)
        if monthly is None:
            L.append(f"    品类「{a['cat']}」无折旧先验:残值 n/a,不判 GAP"
                     f"(账本 years 列一句话,或 --years 翻案)")
            L.append("")
            continue
        served = len(months)
        residual = a["cost"] - monthly * D(served)
        note = ""
        if served > life_m:
            note = f"(已超先验寿命 {life_m} 个月,残值按 0 记不是还能卖这么多)"
        L.append(f"    折旧 {life_m // 12} 年直线:月 {money(monthly)} × 役月 "
                 f"{served} = {money(monthly * D(served))}  残值 ¥{money(max(residual, D0))}"
                 f"{' ' + note if note else ''}")
        if usage:
            last_ym = months[-1]
            occ = sum(1 for p in led.people if p.active_in_month(last_ym, as_of))
            L.append(f"    usage charge 最新月 {month_str(last_ym)}:每人 "
                     f"{money(usage[last_ym])}({occ} 人在住)——按月记一笔回收账"
                     f"(bills.category=「{a['name']}」)才算收过")
        else:
            first = month_add(month_of(a["date"]), 1)
            L.append(f"    役月未开始(usage 自 {month_str(first)} 起)——"
                     f"购置当月与 as-of 当月不计,未满月不冤枉")
        gaps = asset_gaps(led, a, months, usage, as_of)
        if gaps:
            L.append("    GAP 审计(走了的人,在住役月无一笔回收账):")
            for p, missed, total, parts in gaps:
                by_f = "  ".join(
                    f"{fmt_person(led, fn)} {money(v)}" for fn, v in parts)
                L.append(f"      ✗ {p.name}({month_str(missed[0])}~"
                         f"{month_str(missed[-1])} 共 {len(missed)} 月)"
                         f" ¥{money(total)} → {by_f}")
                gap_gates.append(
                    f"🔴 GAP {led.basename}/{p.name}×{a['name']}:在住 "
                    f"{len(missed)} 个役月({month_str(missed[0])}~"
                    f"{month_str(missed[-1])})无一笔回收账,{money(total)} "
                    f"永远收不回了——摊派只及在住者")
        L.append("")
    if gap_gates:
        L.append("── 灯")
        L.extend("    " + g for g in gap_gates)
        L.append("")
        L.append("GAP 的意思不是谁坏,是账动晚了:usage 是按月滚的应收,"
                 "等室友搬走才想起来记,那笔账永远收不回了。")
        print("\n".join(L))
        return 4
    if not any(g.startswith("🔴 GAP") for g in
               evaluate_gates(led, as_of, args.loss_cap, args.skew_cap)):
        L.append("GAP 审计干净:每个走了的人,在住的每个月都有回收账接住。")
    print("\n".join(L))
    return 0


def cmd_validate(args) -> int:
    led = load_ledger(args.root)
    as_of = resolve_as_of(led, args.as_of)
    L = []
    L.append(f"同檐 · Flat Split validate — {led.basename}/")
    L.append(f"as-of {as_of}")
    ok = True
    # ① 恒等式:Σ逐人应付 ≡ Σ账单(逐月+全期)
    rows = monthly_report(led, as_of)
    s_bills = sum(b.amount for b in led.bills if b.date <= as_of)
    s_alloc = sum(sum(a.values(), D0) for _, _, a, _ in rows)
    s_paid = sum(sum(p.values(), D0) for _, _, _, p in rows)
    L.append(f"  Σ逐人应付 {money(s_alloc)} ≡ Σ账单 {money(s_bills)} : "
             + ("✓" if s_alloc == s_bills else "✗ 不等!"))
    ok &= s_alloc == s_bills
    net = {}
    for _, _, a, p in rows:
        for n, v in a.items():
            net[n] = net.get(n, D0) - v
        for n, v in p.items():
            net[n] = net.get(n, D0) + v
    s_net = sum(net.values(), D0)
    L.append(f"  Σ净额 {money(s_net)} ≡ 0(清算零和): "
             + ("✓" if s_net == 0 else "✗ 不等!"))
    ok &= s_net == 0
    # ② 逐段抄表恒等式:Σ房间增量 + 公区 ≡ 总增量
    for (cat_n, room_n), slot in sorted(led.meters.items()):
        if room_n != "_total":
            continue
        dates = [d for d in sorted(slot) if d <= as_of]
        for d0, d1 in zip(dates, dates[1:]):
            total = slot[d1] - slot[d0]
            rooms = sum((s[d1] - s[d0]) for (c, r), s in led.meters.items()
                        if c == cat_n and r != "_total")
            good = rooms <= total
            L.append(f"  {cat_n} {d0}→{d1}:Σ房间 {money(rooms)} + 公区 "
                     f"{money(total - rooms)} ≡ 总 {money(total)} : "
                     + ("✓" if good else "✗ 房间增量超过总增量(表不对)"))
            ok &= good
    # ③ 残值恒等式:残值 ≡ cost − 月折旧×役月
    for n in sorted(led.assets):
        a = led.assets[n]
        months, usage, monthly, ar, life_m = asset_usage(led, a, as_of)
        if monthly is None:
            L.append(f"  {a['name']}:品类「{a['cat']}」无先验,残值 n/a(不装懂)")
            continue
        residual = a["cost"] - monthly * D(len(months))
        L.append(f"  {a['name']}:残值 {money(residual)} ≡ cost {money(a['cost'])}"
                 f" − 月折旧 {money(monthly)}×役月 {len(months)} : ✓")
    # ④ 双路径重放:路径A=allocate 管线;路径B=逐单独立重放
    b_alloc = {}
    for _, detail, _, _ in rows:
        for b, shares in detail:
            for n, v in shares:
                b_alloc[n] = b_alloc.get(n, D0) + v
    a_alloc = replay_simple(led, as_of)
    same = a_alloc == b_alloc
    L.append(f"  双路径重放(管线 vs 独立重放)逐人全等: "
             + ("✓" if same else "✗ 分歧!"))
    ok &= same
    if not same:
        for n in sorted(set(a_alloc) | set(b_alloc)):
            if a_alloc.get(n, D0) != b_alloc.get(n, D0):
                L.append(f"    {n}: {money(b_alloc.get(n, D0))} vs "
                         f"{money(a_alloc.get(n, D0))}")
    # ⑤ 名册/引用卫生(能走到这里说明载入已过;补账面口径)
    L.append("")
    L.append(("账本体检通过。" if ok else "账本体检发现不一致(见上)。"))
    print("\n".join(L))
    return 0 if ok else 2


def replay_simple(led: Ledger, as_of: dt.date) -> Dict[str, D]:
    """独立重放:不复用 allocate 的合并/尾差管线,朴素逐单逐人累加.

    与管线一致性就是恒等式本身——两条路径必须各自写完再对答案。
    """
    out: Dict[str, D] = {}
    for b in led.bills:
        if b.date > as_of:
            continue
        for n, v in _replay_one(led, b, as_of).items():
            out[n] = out.get(n, D0) + v
    return out


def _replay_one(led, b, as_of):
    people = [p for p in led.people if p.start <= as_of]
    if b.rule == "per_head":
        ym = month_of(b.date)
        ws = [(p, D(p.days_in(month_first(ym), month_end(ym), as_of)))
              for p in people if p.days_in(month_first(ym), month_end(ym), as_of) > 0]
        tw = sum(w for _, w in ws)
        if tw == 0:
            raise BadLedger(f"bills 第 {b.line} 行:无人可摊")
        got = {}
        for p, w in ws:
            got[norm(p.name)] = b.amount * w / tw
        return _close(got, b.amount)
    dates = led.meter_dates(b.cat)
    i = dates.index(b.date)
    d0, d1 = dates[i - 1], dates[i]
    total = led.meters[(b.cat, "_total")][d1] - led.meters[(b.cat, "_total")][d0]
    got: Dict[str, D] = {}
    public = total
    for (cat_n, room_n), slot in led.meters.items():
        if cat_n != b.cat or room_n == "_total":
            continue
        delta = slot[d1] - slot[d0]
        if delta == 0:
            continue
        occ = [p for p in people if norm(p.room) == room_n
               and p.days_in(d0, d1, as_of) > 0]
        if not occ:
            continue
        public -= delta
        share = b.amount * delta / total
        tw = sum(D(p.days_in(d0, d1, as_of)) for p in occ)
        for p in occ:
            got[norm(p.name)] = got.get(norm(p.name), D0) + \
                share * D(p.days_in(d0, d1, as_of)) / tw
    if public < 0:
        public = D0
    tw = sum(D(p.days_in(d0, d1, as_of)) for p in people
             if p.days_in(d0, d1, as_of) > 0)
    for p in people:
        dd = p.days_in(d0, d1, as_of)
        if dd <= 0:
            continue
        got[norm(p.name)] = got.get(norm(p.name), D0) + \
            (public * b.amount / total) * D(dd) / tw
    return _close(got, b.amount)


def _close(got: Dict[str, D], amount: D) -> Dict[str, D]:
    q = {n: v.quantize(Q2, rounding=decimal.ROUND_HALF_UP) for n, v in got.items()}
    diff = (amount - sum(q.values(), D0)).quantize(Q2)
    if diff:
        first = sorted(q, key=lambda n: (-got[n], n))[0]
        q[first] = (q[first] + diff).quantize(Q2)
    return q


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog=PROG,
        description="同檐 · Flat Split —— 合租分摊对账账本"
                    "(report/settle/assets/validate;账本=目录下四本 TSV)")
    ap.add_argument("--version", action="version", version=f"{PROG} {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_loss_cap(p):
        p.add_argument("--loss-cap", type=D, default=None,
                       help="表损容差(全局翻案;缺省分科目:电8%% 水12%% 气5%%)")
        p.add_argument("--skew-cap", type=D, default=SKEW_CAP,
                       help="垫付集中度线(缺省 0.80,恰线不亮)")

    for name, help_ in [("report", "逐月分摊总表+灯"),
                        ("settle", "净额清算(最简转账链)"),
                        ("assets", "公共资产台账+usage charge+GAP 审计"),
                        ("validate", "账本体检(恒等式+双路径重放)")]:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("root", nargs="?", default=".",
                        help="账本目录(内含 household/bills/meters/assets.tsv)")
        if name == "settle":
            sp.add_argument("--month", help="只清算某月 YYYY-MM(缺省全期)")
        if name in ("report", "assets", "validate", "settle"):
            sp.add_argument("--as-of", help="钉死对账基准日 YYYY-MM-DD"
                            "(缺省=账本最大日期;零墙钟)")
        if name in ("report", "assets"):
            add_loss_cap(sp)
        sp.set_defaults(func={"report": cmd_report, "settle": cmd_settle,
                              "assets": cmd_assets,
                              "validate": cmd_validate}[name])
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except BadLedger as e:
        print(f"{PROG}: 账坏——{e}", file=sys.stderr)
        return 2
    except Refuse as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
