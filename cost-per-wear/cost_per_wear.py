#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cost-per-wear · 每穿成本 —— 衣服的真实价格在衣柜的出勤记录里.

问题：一件衣服的真实价格 = 吊牌价 ÷ 穿的次数，但没人算。购买决策在
试衣间 3 分钟完成，账单只显示吊牌价；于是贵而常穿的被骂「乱花钱」，
便宜而从不穿的在衣柜里吃灰。「没衣服穿」和「塞爆」并存——因为缺口
是结构性的（没有外套），采购却是冲动性的（第 8 件白 T）。

cost-per-wear 从衣柜清单 CSV 里算四本账：
  audit    CPW 账本：真实价格排行 / 衣柜坟场（沉睡资金）/ 品类堆积区 / 覆盖矩阵
  plan     剁手模拟器：想买清单逐条判「填补缺口」还是「第 N 件白 T」
  validate 衣柜清单格式体检

零依赖：Python 3.8+ 标准库。

用法：
  python3 cost_per_wear.py audit examples/wardrobe.csv
  python3 cost_per_wear.py audit examples/wardrobe.csv --orphan-alert 0.25
  python3 cost_per_wear.py plan examples/wardrobe.csv --want "外套:899,白T:79"
  python3 cost_per_wear.py validate examples/wardrobe.csv

退出码：0 正常；2 用法错误；3 文件/格式错误；4 门禁触发。

诚实条款：工具只看「买」与「穿」两件事的账，不评判审美，不替你断言
「该不该扔」——扔衣服永远是人的决定，这里只提供谁在吃灰的证据。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量与词表

class WardrobeError(Exception):
    """衣柜清单无法解析。"""


# 列名别名表（表头 normalize：去空白、小写）
ITEM_ALIASES = {"item", "name", "名称", "品名", "衣物", "单品", "描述"}
CATEGORY_ALIASES = {"category", "类别", "品类", "类", "类型"}
SEASON_ALIASES = {"season", "季节", "适用季节"}
PRICE_ALIASES = {"price", "价格", "吊牌价", "购入价", "实付", "cost", "amount", "金额"}
ACQUIRED_ALIASES = {"acquired", "acquired_date", "购买日期", "购入日期", "买入日期",
                    "date", "日期"}
WEARS_ALIASES = {"wears", "wear_count", "穿着次数", "次数", "times", "穿了"}
LAST_WORN_ALIASES = {"last_worn", "last_worn_date", "最后穿", "上次穿", "最近穿"}

SEASONS = ("春", "夏", "秋", "冬")
SEASON_TOKENS = {"春": "春", "夏": "夏", "秋": "秋", "冬": "冬",
                 "spring": "春", "summer": "夏", "autumn": "秋", "fall": "秋",
                 "winter": "冬", "all": "ALL", "全年": "ALL", "四季": "ALL",
                 "all-season": "ALL", "allseason": "ALL", "": "ALL"}

TODAY = date.today()          # 可被 --today 覆盖（测试与可复现性）
DEFAULT_ORPHAN_DAYS = 180     # 从未穿且购入超过 N 天 → 坟场（新衣豁免期）
DEFAULT_ASLEEP_DAYS = 365     # 上次穿着超过 N 天 → 长眠（哪怕穿过）
DEFAULT_DUP_THRESHOLD = 4     # 同品类数量 ≥ N → 堆积区
DEFAULT_GRAVEYARD_SHARE = 0.25  # 沉睡资金占总投入比例门禁

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d")


# ---------------------------------------------------------------------------
# 解析

def normalize_header(h: str) -> str:
    return re.sub(r"\s+", "", h).lower()


def parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    s = re.sub(r"[T ]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$", "", s)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_seasons(s: str):
    """'春秋' → {春,秋}；'all'/'全年' → ALL（覆盖全部四季）。"""
    s = (s or "").strip().lower()
    out = set()
    for token in re.split(r"[/、,，+\s]+", s):
        v = SEASON_TOKENS.get(token)
        if v == "ALL":
            return "ALL"
        if v:
            out.add(v)
            continue
        for ch in token:               # 「春秋」这类无分隔连写
            c = SEASON_TOKENS.get(ch)
            if c and c != "ALL":
                out.add(c)
    return out or "ALL"


def _find_column(headers, aliases):
    for i, h in enumerate(headers):
        if h in aliases:
            return i
    return -1


def _sniff_delimiter(sample: str) -> str:
    first = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {d: first.count(d) for d in (",", ";", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def read_wardrobe(path) -> dict:
    """读衣柜 CSV → {items, skipped, header_found}.

    item: {name, category(归一化前原文), cat(小写key), seasons, price,
           acquired, wears, last_worn}
    """
    p = Path(path)
    if not p.is_file():
        raise WardrobeError(f"file not found: {p}")
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gbk")
        except UnicodeDecodeError:
            raise WardrobeError(f"cannot decode {p} as utf-8 or gbk")

    delimiter = _sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    table = [row for row in reader if any((c or "").strip() for c in row)]
    if not table:
        raise WardrobeError(f"no rows in {p}")

    header_idx = -1
    idx = {}
    for i, row in enumerate(table[:20]):
        headers = [normalize_header(c) for c in row]
        ii = _find_column(headers, ITEM_ALIASES)
        ci = _find_column(headers, CATEGORY_ALIASES)
        pi = _find_column(headers, PRICE_ALIASES)
        wi = _find_column(headers, WEARS_ALIASES)
        if ii >= 0 and ci >= 0 and pi >= 0 and wi >= 0:
            header_idx = i
            idx = {"item": ii, "cat": ci, "season": _find_column(headers, SEASON_ALIASES),
                   "price": pi, "acquired": _find_column(headers, ACQUIRED_ALIASES),
                   "wears": wi, "last": _find_column(headers, LAST_WORN_ALIASES)}
            break
    if header_idx < 0:
        raise WardrobeError(
            f"cannot find header columns (need name/类别/价格/穿着次数) in {p}")

    def cell(row, key):
        i = idx[key]
        return row[i].strip() if i >= 0 and i < len(row) else ""

    items, skipped = [], 0
    for row in table[header_idx + 1:]:
        name = cell(row, "item")
        cat = cell(row, "cat")
        try:
            price = float(cell(row, "price").replace("¥", "").replace("￥", "")
                          .replace(",", ""))
            wears = int(float(cell(row, "wears")))
        except ValueError:
            skipped += 1
            continue
        if not name or not cat or price < 0 or wears < 0:
            skipped += 1
            continue
        items.append({
            "name": name,
            "category": cat,
            "cat": cat.strip().lower(),
            "seasons": parse_seasons(cell(row, "season")),
            "price": price,
            "acquired": parse_date(cell(row, "acquired")),
            "wears": wears,
            "last_worn": parse_date(cell(row, "last")),
        })
    if not items:
        raise WardrobeError(f"no usable rows in {p}")
    return {"items": items, "skipped": skipped}


# ---------------------------------------------------------------------------
# 账本

def cpw(price: float, wears: int):
    """每穿成本：穿过才定型；0 次是 ∞（未定型），返回 None。"""
    if wears <= 0:
        return None
    return round(price / wears, 2)


def audit(wardrobe, today=None, orphan_days=DEFAULT_ORPHAN_DAYS,
          asleep_days=DEFAULT_ASLEEP_DAYS, dup_threshold=DEFAULT_DUP_THRESHOLD) -> dict:
    today = today or TODAY
    items = wardrobe["items"]
    total_spend = sum(i["price"] for i in items)

    ranked, never_worn, asleep = [], [], []
    for pos, it in enumerate(items):
        r = dict(it)
        r["_pos"] = pos
        r["cpw"] = cpw(it["price"], it["wears"])
        if r["cpw"] is not None:
            ranked.append(r)
        else:
            age = (today - it["acquired"]).days if it["acquired"] else None
            if age is None or age >= orphan_days:
                never_worn.append({**r, "age_days": age})
        if it["last_worn"] and (today - it["last_worn"]).days >= asleep_days:
            asleep.append(r)
    ranked.sort(key=lambda r: (-r["cpw"], r["name"]))   # 最贵（每穿）在前

    # 沉睡资金 = 从未穿的 + 长眠的（两者重叠的不重复计）
    never_ids = {r["_pos"] for r in never_worn}
    sleeping = sum(r["price"] for r in never_worn) + \
        sum(r["price"] for r in asleep if r["_pos"] not in never_ids)

    # 品类堆积区
    cat_counts = {}
    for i in items:
        c = cat_counts.setdefault(i["cat"], {"category": i["category"], "count": 0,
                                             "spend": 0.0})
        c["count"] += 1
        c["spend"] += i["price"]
    hoarded = sorted((c for c in cat_counts.values() if c["count"] >= dup_threshold),
                     key=lambda c: (-c["count"], c["category"]))

    # 品类 × 季节覆盖矩阵
    matrix = {}
    for i in items:
        row = matrix.setdefault(i["cat"], {s: 0 for s in SEASONS})
        seasons = SEASONS if i["seasons"] == "ALL" else tuple(i["seasons"])
        for s in seasons:
            row[s] += 1

    graveyard_share = sleeping / total_spend if total_spend else 0.0
    return {
        "window": {
            "items": len(items),
            "skipped": wardrobe["skipped"],
            "total_spend": round(total_spend, 2),
            "today": today.isoformat(),
        },
        "cpw_board": [
            {"name": r["name"], "category": r["category"], "price": round(r["price"], 2),
             "wears": r["wears"], "cpw": r["cpw"]}
            for r in ranked[:15]
        ],
        "value_board": [
            {"name": r["name"], "category": r["category"], "cpw": r["cpw"]}
            for r in sorted(ranked, key=lambda r: (r["cpw"], r["name"]))[:5]
        ],
        "graveyard": {
            "never_worn": [
                {"name": r["name"], "category": r["category"],
                 "price": round(r["price"], 2),
                 "acquired": r["acquired"].isoformat() if r["acquired"] else None,
                 "age_days": r["age_days"]}
                for r in sorted(never_worn, key=lambda r: -r["price"])
            ],
            "asleep": [
                {"name": r["name"], "category": r["category"],
                 "price": round(r["price"], 2),
                 "last_worn": r["last_worn"].isoformat()}
                for r in sorted(asleep, key=lambda r: -r["price"])
            ],
            "sleeping_capital": round(sleeping, 2),
            "share": round(graveyard_share, 4),
        },
        "hoarded": [
            {"category": c["category"], "count": c["count"],
             "spend": round(c["spend"], 2)}
            for c in hoarded
        ],
        "coverage": matrix,
    }


# ---------------------------------------------------------------------------
# 剁手模拟器

def plan(wardrobe, wants, today=None, orphan_days=DEFAULT_ORPHAN_DAYS,
         dup_threshold=DEFAULT_DUP_THRESHOLD) -> list:
    """wants: [(品类, 价格)] → 逐条判定 accept(填补缺口) / reject。

    两道否决，按序检查：
      1) 堆积区：该品类已有 ≥ dup_threshold 件 → 再买就是第 N+1 件；
      2) 孤儿否决：该品类挂着一件从未穿的（超过豁免期）→ 先穿它。
    """
    items = wardrobe["items"]
    today = today or TODAY
    counts, orphans = {}, {}
    for i in items:
        counts[i["cat"]] = counts.get(i["cat"], 0) + 1
        if i["wears"] <= 0:
            age = (today - i["acquired"]).days if i["acquired"] else None
            if age is None or age >= orphan_days:
                orphans.setdefault(i["cat"], (i["name"], age))
    verdicts = []
    for cat, price in wants:
        key = cat.strip().lower()
        have = counts.get(key, 0)
        if have >= dup_threshold:
            verdicts.append({
                "want": cat, "price": round(price, 2), "verdict": "REJECT",
                "reason": f"第 {have + 1} 件（该品类已有 {have} 件，堆积区）",
            })
        elif key in orphans:
            name, age = orphans[key]
            age_s = f"{age} 天" if age is not None else "时间未知"
            verdicts.append({
                "want": cat, "price": round(price, 2), "verdict": "REJECT",
                "reason": f"该品类有从未穿过的「{name}」（{age_s}）——先穿它",
            })
        else:
            verdicts.append({
                "want": cat, "price": round(price, 2), "verdict": "ACCEPT",
                "reason": f"填补缺口（该品类现有 {have} 件）",
            })
    return verdicts


# ---------------------------------------------------------------------------
# 渲染

def _dwidth(s: str) -> int:
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def _ljust(s: str, width: int) -> str:
    return s + " " * max(width - _dwidth(s), 0)


def _clip(s: str, width: int) -> str:
    out, w = [], 0
    for ch in s:
        cw = 2 if ord(ch) > 0x2E7F else 1
        if w + cw > width:
            break
        out.append(ch)
        w += cw
    return "".join(out)


def render_text(rep) -> str:
    out = io.StringIO()
    w = rep["window"]
    print("-- Cost Per Wear · 每穿成本", file=out)
    print(
        f"   {w['items']} items · {w['skipped']} skipped · 总投入 {w['total_spend']:.2f}"
        f" · today {w['today']}",
        file=out,
    )
    print(file=out)
    board = rep["cpw_board"]
    if board:
        print("   最贵的衣服（吊牌价 ÷ 穿的次数）：", file=out)
        print(f"   {'name':<24} {'category':<10} {'price':>9} {'wears':>6} {'cpw':>9}",
              file=out)
        for r in board:
            print(f"   {_ljust(_clip(r['name'], 24), 24)} {_ljust(_clip(r['category'], 10), 10)}"
                  f" {r['price']:>9.2f} {r['wears']:>6} {r['cpw']:>9.2f}", file=out)
        print(file=out)
    if rep["value_board"]:
        print("   真正的便宜货（cpw 最低）：", file=out)
        for r in rep["value_board"]:
            print(f"     {_ljust(_clip(r['name'], 26), 28)} {r['cpw']:>8.2f}/穿", file=out)
        print(file=out)
    g = rep["graveyard"]
    if g["never_worn"] or g["asleep"]:
        print(f"   衣柜坟场：沉睡资金 {g['sleeping_capital']:.2f}（占总投入"
              f" {g['share'] * 100:.1f}%）", file=out)
        for r in g["never_worn"]:
            age = f"{r['age_days']}d" if r["age_days"] is not None else "age?"
            print(f"     never worn  {_ljust(_clip(r['name'], 24), 26)}"
                  f" {r['price']:>8.2f}  {age}", file=out)
        for r in g["asleep"]:
            print(f"     asleep      {_ljust(_clip(r['name'], 24), 26)}"
                  f" {r['price']:>8.2f}  last {r['last_worn']}", file=out)
        print(file=out)
    if rep["hoarded"]:
        print("   品类堆积区（同品类数量触顶）：", file=out)
        for h in rep["hoarded"]:
            print(f"     {_ljust(_clip(h['category'], 12), 14)} x{h['count']}"
                  f"  已投入 {h['spend']:.2f}", file=out)
        print(file=out)
    print("   品类 × 季节覆盖矩阵：", file=out)
    print(f"     {'category':<16} {'春':>3} {'夏':>3} {'秋':>3} {'冬':>3}", file=out)
    for cat in sorted(rep["coverage"]):
        row = rep["coverage"][cat]
        print(f"     {_ljust(_clip(cat, 16), 16)}"
              f" {row['春']:>3} {row['夏']:>3} {row['秋']:>3} {row['冬']:>3}", file=out)
    print(file=out)
    print(
        f"   沉睡资金 {g['sleeping_capital']:.2f} / 总投入 {w['total_spend']:.2f}。"
        f"  Next buy should fill a gap, not feed a pile. 扔与不扔，是你的决定。",
        file=out,
    )
    return out.getvalue()


def render_json(rep) -> str:
    return json.dumps(rep, ensure_ascii=False, indent=2)


def render_plan(verdicts, as_json=False) -> str:
    if as_json:
        return json.dumps({"plan": verdicts}, ensure_ascii=False, indent=2)
    out = io.StringIO()
    print("-- Cost Per Wear · 剁手模拟器", file=out)
    for v in verdicts:
        mark = "✓" if v["verdict"] == "ACCEPT" else "✗"
        print(f"   {mark} {v['verdict']:<7} {_ljust(_clip(v['want'], 12), 14)}"
              f" {v['price']:>9.2f}  {v['reason']}", file=out)
    rejects = sum(1 for v in verdicts if v["verdict"] == "REJECT")
    print(file=out)
    print(f"   {len(verdicts) - rejects} fill a gap, {rejects} feed a pile.", file=out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# CLI

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cost_per_wear",
        description="每穿成本 · Cost Per Wear —— 衣服的真实价格 = 吊牌价 ÷ 穿的次数",
    )
    sub = p.add_subparsers(dest="cmd")
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("csv", help="衣柜清单 CSV 路径")
    base.add_argument("--format", choices=["text", "json"], default="text")
    base.add_argument("--today", default=None, help="覆盖今天（YYYY-MM-DD），保证可复现")
    base.add_argument("--orphan-days", type=int, default=DEFAULT_ORPHAN_DAYS,
                      help="从未穿且购入超过 N 天 → 坟场（默认 180）")
    base.add_argument("--asleep-days", type=int, default=DEFAULT_ASLEEP_DAYS,
                      help="上次穿着超过 N 天 → 长眠（默认 365）")
    base.add_argument("--dup-threshold", type=int, default=DEFAULT_DUP_THRESHOLD,
                      help="同品类 ≥ N 件 → 堆积区（默认 4）")
    a = sub.add_parser("audit", parents=[base])
    a.add_argument("--orphan-alert", type=float, default=None,
                   help="沉睡资金占比超过该值则 exit 4（门禁）")
    pl = sub.add_parser("plan", parents=[base])
    pl.add_argument("--want", required=True,
                    help="想买清单，如 '外套:899,白T:79'（品类:价格，逗号分隔）")
    pl.add_argument("--strict", action="store_true",
                    help="任何一条 REJECT 则 exit 4")
    sub.add_parser("validate", parents=[base])
    return p


def parse_want(s: str):
    wants = []
    for part in re.split(r"[,，]", s):
        part = part.strip()
        if not part:
            continue
        if ":" not in part and "：" not in part:
            raise WardrobeError(f"--want 条目缺少价格: '{part}'（格式 品类:价格）")
        cat, price_s = re.split(r"[:：]", part, maxsplit=1)
        try:
            price = float(price_s.strip())
        except ValueError:
            raise WardrobeError(f"--want 价格不是数字: '{part}'")
        wants.append((cat.strip(), price))
    if not wants:
        raise WardrobeError("--want 为空")
    return wants


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.cmd:
        build_parser().print_help()
        return 2
    try:
        today = parse_date(args.today) if args.today else None
        if args.today and today is None:
            raise WardrobeError(f"--today 不是合法日期: '{args.today}'")
        wardrobe = read_wardrobe(args.csv)
        if args.cmd == "validate":
            print(f"ok: {len(wardrobe['items'])} items, {wardrobe['skipped']} skipped")
            return 0
        if args.cmd == "plan":
            wants = parse_want(args.want)
            verdicts = plan(wardrobe, wants, today=today,
                            dup_threshold=args.dup_threshold)
            print(render_plan(verdicts, as_json=args.format == "json"))
            if args.strict and any(v["verdict"] == "REJECT" for v in verdicts):
                print("strict mode: at least one REJECT", file=sys.stderr)
                return 4
            return 0
        rep = audit(wardrobe, today=today, orphan_days=args.orphan_days,
                    asleep_days=args.asleep_days, dup_threshold=args.dup_threshold)
        print(render_json(rep) if args.format == "json" else render_text(rep))
        if args.orphan_alert is not None and rep["graveyard"]["share"] > args.orphan_alert:
            print(
                f"orphan alert: sleeping share {rep['graveyard']['share'] * 100:.1f}%"
                f" > {args.orphan_alert * 100:.1f}%",
                file=sys.stderr,
            )
            return 4
        return 0
    except WardrobeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
