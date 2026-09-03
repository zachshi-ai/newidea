#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""续命账 · Repair Ledger — 把「修还是换」从感情决策变成账本决策.

家里的耐用品坏了,维修师傅报价 ¥600、宣称「再战三年」,新机 ¥3200——修吗?
多数人靠两种情绪回答:「舍不得」(修!)和「烦死了」(换!)。本件给这个
决策记一本账:

  * 真正可比的不是报价 vs 新机价,是**边际每使用年成本**:
    修理 ¥/服务年(经画饼系数折算) vs 新机 ¥/服务年。
  * **画饼系数**从你自己的维修历史学出来:师傅每次都宣称续命 N 年,
    账本记下实际续命,median(实际/宣称) 就是你家师傅的话可信几折。
  * **续命递减**:同一台机器修过三次,每次买到的实际寿命在缩短——
    第一次 1.7 年、第二次 0.8 年,师傅的「再战三年」请打折听。
  * **沉没护栏**:累计维修费(含本次报价)超过购价,继续修等于
    给废品站预付工资——直接判 SCRAP。

诚实条款:
  1. 「今天」可钉死:--as-of 钉住即逐字节可复现(样例全部钉同一日期)。
  2. 修不好的钱照记账:failed 维修 actual = 0,进画饼样本——
     「修不好也收钱」是这个市场最贵的一句话。
  3. 删失如实:修完还没再坏的维修不假装知道实际续命,标 ≥,不进中位数。
  4. 没有历史的新账本默认画饼系数 1.0:不惩罚新人,先信师傅,后见分晓。

Exit codes: 0 = FIX / 正常;2 = 数据或用法错误;3 = REPLACE(换新);4 = SCRAP(报废).
"""

import argparse
import json
import statistics
import sys
from datetime import date

DAYS_PER_YEAR = 365.25
DEFAULT_TOLERANCE = 1.0     # 修理边际成本最多允许贵到新机的几倍仍判 FIX
DEFAULT_SCRAP_RATIO = 1.0   # 累计维修(含本次报价)/ 购价 ≥ 此值 → SCRAP
VALID_OUTCOMES = ("fixed", "failed")

EXIT_FIX, EXIT_ERROR, EXIT_REPLACE, EXIT_SCRAP = 0, 2, 3, 4


class LedgerError(Exception):
    """数据或用法错误 → exit 2."""


# ---------------------------------------------------------------------------
# 账本加载与校验
# ---------------------------------------------------------------------------

def parse_date(text, what):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise LedgerError("%s 日期不合法: %r (需要 YYYY-MM-DD)" % (what, text))


def load_ledger(path):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raise LedgerError("账本不存在: %s" % path)
    except json.JSONDecodeError as exc:
        raise LedgerError("账本不是合法 JSON: %s (行 %d 列 %d)"
                          % (exc.msg, exc.lineno, exc.colno))
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise LedgerError("账本顶层应为 {\"items\": [...]} 或裸数组,收到 %s"
                          % type(items).__name__)
    seen_ids = set()
    for idx, entry in enumerate(items):
        _validate_item(entry, idx, seen_ids)
    return raw if isinstance(raw, dict) else {"items": raw}


def _require(entry, key, idx):
    if key not in entry:
        raise LedgerError("第 %d 件物品缺少字段 %r" % (idx + 1, key))
    return entry[key]


def _validate_item(entry, idx, seen_ids):
    if not isinstance(entry, dict):
        raise LedgerError("第 %d 件物品不是对象" % (idx + 1))
    item_id = _require(entry, "id", idx)
    _require(entry, "name", idx)
    if item_id in seen_ids:
        raise LedgerError("物品 id 重复: %r" % item_id)
    seen_ids.add(item_id)

    _require(entry, "purchased", idx)
    purchased = parse_date(entry.get("purchased"), "物品 %r 的 purchased" % item_id)
    _require(entry, "price", idx)
    price = entry.get("price")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0:
        raise LedgerError("物品 %r 的 price 必须是非负数字" % item_id)
    _require(entry, "expected_life_years", idx)
    life = entry.get("expected_life_years")
    if not isinstance(life, (int, float)) or isinstance(life, bool) or life <= 0:
        raise LedgerError("物品 %r 的 expected_life_years 必须为正数" % item_id)

    repairs = entry.get("repairs", [])
    if not isinstance(repairs, list):
        raise LedgerError("物品 %r 的 repairs 必须是数组" % item_id)
    prev_date = purchased
    for r_idx, rep in enumerate(repairs):
        _validate_repair(rep, item_id, r_idx, prev_date)
        prev_date = parse_date(rep["date"], "物品 %r 第 %d 笔维修" % (item_id, r_idx + 1))

    retired = entry.get("retired")
    if retired is not None:
        if not isinstance(retired, dict) or "date" not in retired:
            raise LedgerError("物品 %r 的 retired 需要 {\"date\": ..., \"salvage\": ...}" % item_id)
        retired_date = parse_date(retired["date"], "物品 %r 的 retired.date" % item_id)
        if retired_date < prev_date:
            raise LedgerError("物品 %r 的报废日早于最后一笔维修/购入日" % item_id)
        salvage = retired.get("salvage", 0)
        if not isinstance(salvage, (int, float)) or isinstance(salvage, bool) or salvage < 0:
            raise LedgerError("物品 %r 的 salvage 必须是非负数字" % item_id)


def _validate_repair(rep, item_id, r_idx, prev_date):
    if not isinstance(rep, dict):
        raise LedgerError("物品 %r 第 %d 笔维修不是对象" % (item_id, r_idx + 1))
    for key in ("date", "cost", "outcome", "claimed_years"):
        if key not in rep:
            raise LedgerError("物品 %r 第 %d 笔维修缺少字段 %r" % (item_id, r_idx + 1, key))
    when = parse_date(rep["date"], "物品 %r 第 %d 笔维修" % (item_id, r_idx + 1))
    if when < prev_date:
        raise LedgerError("物品 %r 的维修日期乱序或早于购入: %s" % (item_id, rep["date"]))
    cost = rep["cost"]
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
        raise LedgerError("物品 %r 第 %d 笔维修的 cost 必须是非负数字" % (item_id, r_idx + 1))
    if rep["outcome"] not in VALID_OUTCOMES:
        raise LedgerError("物品 %r 第 %d 笔维修的 outcome 必须是 %s 之一,收到 %r"
                          % (item_id, r_idx + 1, "/".join(VALID_OUTCOMES), rep["outcome"]))
    claimed = rep["claimed_years"]
    if not isinstance(claimed, (int, float)) or isinstance(claimed, bool) or claimed <= 0:
        raise LedgerError("物品 %r 第 %d 笔维修的 claimed_years 必须为正数"
                          % (item_id, r_idx + 1))


# ---------------------------------------------------------------------------
# 计算核心(纯函数,测试直接调用)
# ---------------------------------------------------------------------------

def years_between(start, end):
    return (end - start).days / DAYS_PER_YEAR


def service_years(item, as_of):
    """从购入到报废(或观察日)的服役年数."""
    end = parse_date(item["retired"]["date"], "retired") if item.get("retired") else as_of
    return max(years_between(parse_date(item["purchased"], "purchased"), end), 0.0)


def total_repair_cost(item):
    return float(sum(r["cost"] for r in item.get("repairs", [])))


def salvage_value(item):
    return float(item.get("retired", {}).get("salvage", 0))


def sunk_cost(item):
    return float(item["price"]) + total_repair_cost(item) - salvage_value(item)


def repair_trail(item, as_of):
    """每笔维修的 (claimed, actual, completed) — actual=None 表示删失(≥).

    fixed 的实际续命 = 到下一次故障/报废的间隔;还没等来下一次 → 删失样本,
    只有下界,不进中位数。failed 的钱照记账,actual = 0:承诺的续命一天没兑现。
    """
    repairs = sorted(item.get("repairs", []),
                     key=lambda r: parse_date(r["date"], "repair"))
    retired = item.get("retired")
    retired_date = parse_date(retired["date"], "retired") if retired else None
    trail = []
    for idx, rep in enumerate(repairs):
        when = parse_date(rep["date"], "repair")
        claimed = float(rep["claimed_years"])
        if rep["outcome"] == "failed":
            trail.append({"date": when, "claimed": claimed, "actual": 0.0,
                          "completed": True, "cost": float(rep["cost"]),
                          "symptom": rep.get("symptom", ""), "outcome": "failed"})
            continue
        next_event = None
        for later in repairs[idx + 1:]:
            next_event = parse_date(later["date"], "repair")
            break
        if retired_date is not None and (next_event is None or retired_date < next_event):
            next_event = retired_date
        if next_event is not None:
            trail.append({"date": when, "claimed": claimed,
                          "actual": years_between(when, next_event),
                          "completed": True, "cost": float(rep["cost"]),
                          "symptom": rep.get("symptom", ""), "outcome": "fixed"})
        else:
            trail.append({"date": when, "claimed": claimed,
                          "actual": years_between(when, as_of),
                          "completed": False, "cost": float(rep["cost"]),
                          "symptom": rep.get("symptom", ""), "outcome": "fixed"})
    return trail


def pie_factor(items, as_of):
    """全局画饼系数 = 所有已结维修 median(实际续命 / 宣称续命).

    没有已结样本 → 1.0(先信师傅,账本记下后见分晓)。
    """
    ratios = []
    for item in items:
        for step in repair_trail(item, as_of):
            if step["completed"]:
                ratios.append(step["actual"] / step["claimed"])
    if not ratios:
        return 1.0, 0
    return statistics.median(ratios), len(ratios)


def diminishing_trail(item, as_of):
    """该物品已结 fixed 维修的实际续命序列;严格递减 → 续命递减警示."""
    actuals = [s["actual"] for s in repair_trail(item, as_of)
               if s["completed"] and s["outcome"] == "fixed"]
    diminishing = len(actuals) >= 2 and all(b < a for a, b in zip(actuals, actuals[1:]))
    return actuals, diminishing


def judge(all_items, item, quote, claimed_years, new_price, new_life,
          as_of, tolerance=DEFAULT_TOLERANCE, scrap_ratio=DEFAULT_SCRAP_RATIO):
    """修还是换的三方裁决.

    credited = 宣称续命 × 画饼系数(师傅的话按你的历史打几折;
    系数取全家账本的中位兑现率 — 样本池大,单物品的波动不绑架判据)
    marginal_fix = 报价 / credited;marginal_new = 新机价 / 新机期望寿命
    FIX: marginal_fix ≤ tolerance × marginal_new
    SCRAP: 边际不占优 且 (累计维修 + 本次报价) / 购价 ≥ scrap_ratio
    REPLACE: 其余
    """
    factor, samples = pie_factor(all_items, as_of)
    credited = claimed_years * factor
    marginal_fix = quote / credited if credited > 0 else float("inf")
    marginal_new = new_price / new_life
    ratio = marginal_fix / marginal_new
    repair_ratio = ((total_repair_cost(item) + quote) / float(item["price"])
                    if item["price"] > 0 else None)
    if ratio <= tolerance:
        verdict = "FIX"
    elif repair_ratio is not None and repair_ratio >= scrap_ratio:
        verdict = "SCRAP"
    else:
        verdict = "REPLACE"
    return {
        "verdict": verdict, "pie_factor": factor, "pie_samples": samples,
        "credited_years": credited, "marginal_fix": marginal_fix,
        "marginal_new": marginal_new, "ratio": ratio,
        "repair_ratio": repair_ratio,
        "exit_code": {"FIX": EXIT_FIX, "REPLACE": EXIT_REPLACE,
                      "SCRAP": EXIT_SCRAP}[verdict],
    }


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def fmt_money(value):
    return ("¥%.0f" % value) if value == value else "—"


def fmt_ratio(value):
    return ("%.2f" % value) if value is not None else "—"


def trail_text(item, as_of):
    parts = []
    for step in repair_trail(item, as_of):
        if step["outcome"] == "failed":
            parts.append("0(failed)")
        else:
            prefix = "" if step["completed"] else "≥"
            parts.append("%s%.1f" % (prefix, step["actual"]))
    return " → ".join(parts) if parts else "无维修"


def cmd_report(args):
    raw = load_ledger(args.ledger)
    items = raw["items"]
    factor, samples = pie_factor(items, args.as_of)
    rows = []
    for item in items:
        years = service_years(item, args.as_of)
        sunk = sunk_cost(item)
        cpy = sunk / years if years > 0 else None
        pct = (total_repair_cost(item) / float(item["price"])
               if item["price"] > 0 else None)
        actuals, diminishing = diminishing_trail(item, args.as_of)
        rows.append({
            "id": item["id"], "name": item["name"], "service_years": round(years, 2),
            "sunk": round(sunk, 2), "cost_per_year": round(cpy, 2) if cpy else None,
            "repair_to_price": round(pct, 4) if pct is not None else None,
            "trail": trail_text(item, args.as_of),
            "diminishing": diminishing,
            "status": "retired" if item.get("retired") else "active",
        })
    rows.sort(key=lambda r: (-(r["cost_per_year"] if r["cost_per_year"] is not None else -1)))
    if args.format == "json":
        print(json.dumps({
            "as_of": args.as_of.isoformat(), "pie_factor": round(factor, 4),
            "pie_samples": samples, "items": rows,
        }, ensure_ascii=False, indent=2))
        return 0
    print("续命账 · Repair Ledger — 观察日 %s" % args.as_of.isoformat())
    if samples:
        print("画饼系数 %.2f(%d 笔已结维修的中位 实际/宣称;师傅说再战三年,按 %.1f 年听)"
              % (factor, samples, 3 * factor))
    else:
        print("画饼系数 1.00(尚无已结维修 — 先信师傅,账本记下后见分晓)")
    print()
    header = ("%-14s %-16s %6s %9s %9s %8s  %-26s %s"
              % ("ITEM", "名称", "服务年", "沉没", "每服务年", "维修占比", "续命实况", "状态"))
    print(header)
    print("-" * len(header.expandtabs()))
    for row in rows:
        trail = row["trail"]
        if row["diminishing"]:
            trail += " ▼递减"
        print("%-14s %-16s %6.1f %9s %9s %7s%%  %-26s %s" % (
            row["id"], row["name"][:16], row["service_years"],
            fmt_money(row["sunk"]),
            fmt_money(row["cost_per_year"]) if row["cost_per_year"] else "—",
            fmt_ratio(100 * row["repair_to_price"]) if row["repair_to_price"] is not None else "—",
            trail[:26], "已结案" if row["status"] == "retired" else "服役中"))
    return 0


def cmd_show(args):
    raw = load_ledger(args.ledger)
    items = raw["items"]
    item = _find_item(items, args.item)
    years = service_years(item, args.as_of)
    print("%s · %s — %s" % (item["id"], item["name"],
                             "已结案" if item.get("retired") else "服役中"))
    print("  购入 %s ¥%.0f(预期寿命 %.0f 年)→ 已服役 %.1f 年"
          % (item["purchased"], item["price"], item["expected_life_years"], years))
    if item.get("retired"):
        print("  报废 %s,回收 ¥%.0f" % (item["retired"]["date"], salvage_value(item)))
    print("  沉没 ¥%.0f(购价 + 维修 ¥%.0f − 回收)→ 每服务年 %s"
          % (sunk_cost(item), total_repair_cost(item),
             fmt_money(sunk_cost(item) / years) if years > 0 else "—"))
    trail = repair_trail(item, args.as_of)
    if not trail:
        print("  无维修记录")
        return 0
    print("  %-12s %-14s %7s %9s %9s %7s  %s"
          % ("日期", "症状", "费用", "宣称续命", "实际续命", "兑现率", "结果"))
    for step in trail:
        actual = ("%.1f" % step["actual"]) if step["completed"] else ("≥%.1f" % step["actual"])
        ratio = ("%.0f%%" % (100 * step["actual"] / step["claimed"])) if step["completed"] else "—"
        print("  %-12s %-14s %7s %9.1f %9s %7s  %s"
              % (step["date"].isoformat(), step["symptom"][:14],
                 fmt_money(step["cost"]), step["claimed"], actual, ratio,
                 "修好" if step["outcome"] == "fixed" else "没修好"))
    actuals, diminishing = diminishing_trail(item, args.as_of)
    if diminishing:
        print("  ▼ 续命递减:%s — 这台机器每次修理买到的寿命在缩短" %
              " → ".join("%.1f" % a for a in actuals))
    return 0


def cmd_history(args):
    raw = load_ledger(args.ledger)
    items = raw["items"]
    factor, samples = pie_factor(items, args.as_of)
    print("维修画饼考古 — 观察日 %s" % args.as_of.isoformat())
    print("  全局画饼系数 %.2f(%d 笔已结维修的中位 兑现率)" % (factor, samples))
    print()
    print("%-14s %-12s %-14s %7s %9s %9s %7s  %s"
          % ("ITEM", "日期", "症状", "费用", "宣称", "实际", "兑现率", "状态"))
    any_row = False
    for item in items:
        for step in repair_trail(item, args.as_of):
            any_row = True
            actual = ("%.1f" % step["actual"]) if step["completed"] else ("≥%.1f" % step["actual"])
            ratio = ("%.0f%%" % (100 * step["actual"] / step["claimed"])) if step["completed"] else "删失"
            print("%-14s %-12s %-14s %7s %9.1f %9s %7s  %s"
                  % (item["id"], step["date"].isoformat(), step["symptom"][:14],
                     fmt_money(step["cost"]), step["claimed"], actual, ratio,
                     "修好" if step["outcome"] == "fixed" else "没修好"))
    if not any_row:
        print("(账本里还没有维修记录)")
    return 0


def cmd_verdict(args):
    raw = load_ledger(args.ledger)
    items = raw["items"]
    item = _find_item(items, args.item)
    if item.get("retired"):
        raise LedgerError("物品 %r 已于 %s 结案;新机器请开新条目"
                          % (args.item, item["retired"]["date"]))
    for key, value in (("quote", args.quote), ("new-price", args.new_price),
                       ("new-life", args.new_life), ("claimed-years", args.claimed_years)):
        if value <= 0:
            raise LedgerError("--%s 必须为正数" % key)

    result = judge(items, item, args.quote, args.claimed_years, args.new_price,
                   args.new_life, args.as_of, args.tolerance, args.scrap_ratio)

    if args.format == "json":
        result.update(item=args.item, quote=args.quote,
                      claimed_years=args.claimed_years, new_price=args.new_price,
                      new_life=args.new_life, tolerance=args.tolerance)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return result["exit_code"]

    actuals, diminishing = diminishing_trail(item, args.as_of)
    print("裁决 · %s %s — %s" % (item["id"], item["name"], args.as_of.isoformat()))
    print("  本次报价 %s,师傅宣称再战 %.1f 年" % (fmt_money(args.quote), args.claimed_years))
    print("  画饼系数 %.2f → 诚实续命 %.1f 年"
          % (result["pie_factor"], result["credited_years"]))
    print("  修理边际 %s/服务年 vs 新机 %s/服务年(比值 %.2f,容忍度 %.2f)"
          % (fmt_money(result["marginal_fix"]), fmt_money(result["marginal_new"]),
             result["ratio"], args.tolerance))
    if result["repair_ratio"] is not None:
        print("  累计维修(含本次)%s = 购价的 %.0f%%"
              % (fmt_money(total_repair_cost(item) + args.quote), 100 * result["repair_ratio"]))
    if diminishing:
        print("  ▼ 续命递减警示:历次实际续命 %s — 师傅的承诺请再打一层折"
              % " → ".join("%.1f" % a for a in actuals))
    banner = {
        "FIX": ("修 FIX — 边际账划算,给师傅打电话",
                "修理边际成本低于新机,这笔钱买到的服务年更便宜"),
        "REPLACE": ("换新 REPLACE — 边际账不划算",
                    "同样一个服务年,新机更便宜;旧机的感情不进账本"),
        "SCRAP": ("报废 SCRAP — 别给废品站预付工资",
                  "累计维修费(含本次报价)已超过购价,继续修是在为一台该退休的机器分期"),
    }[result["verdict"]]
    print()
    print("判定:%s" % banner[0])
    print("      %s" % banner[1])
    return result["exit_code"]


def _find_item(items, needle):
    for item in items:
        if item["id"] == needle or item["name"] == needle:
            return item
    raise LedgerError("账本里没有物品 %r(可用 id 或精确名称)" % needle)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="repair_ledger.py",
        description="续命账 · Repair Ledger — 修还是换,由账本裁决")
    sub = parser.add_subparsers(dest="command")

    def add(name, help_text):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("ledger", help="账本 JSON 路径")
        sp.add_argument("--as-of", default=None,
                        help="观察日 YYYY-MM-DD,默认今天;钉死即逐字节可复现")
        return sp

    p_report = add("report", "全景账本:每件物品的每服务年成本与续命实况")
    p_report.add_argument("--format", choices=("text", "json"), default="text")

    p_show = add("show", "单物品档案:每笔维修的宣称 vs 实际续命")
    p_show.add_argument("item", help="物品 id 或精确名称")

    add("history", "维修画饼考古:全部维修的兑现率与全局画饼系数")

    p_verdict = add("verdict", "修还是换?输入报价与新机参数,拿走裁决")
    p_verdict.add_argument("item", help="物品 id 或精确名称")
    p_verdict.add_argument("--quote", type=float, required=True, help="本次维修报价")
    p_verdict.add_argument("--claimed-years", type=float, required=True,
                           help="师傅宣称的续命年数")
    p_verdict.add_argument("--new-price", type=float, required=True, help="新机价格")
    p_verdict.add_argument("--new-life", type=float, required=True, help="新机期望寿命(年)")
    p_verdict.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                           help="修理边际成本允许贵到新机的几倍仍判 FIX,默认 %.1f"
                                % DEFAULT_TOLERANCE)
    p_verdict.add_argument("--scrap-ratio", type=float, default=DEFAULT_SCRAP_RATIO,
                           help="累计维修(含本次)/购价 ≥ 此值判 SCRAP,默认 %.1f"
                                % DEFAULT_SCRAP_RATIO)
    p_verdict.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not getattr(args, "command", None):
        build_parser().print_help()
        return EXIT_ERROR
    if args.as_of:
        try:
            args.as_of = parse_date(args.as_of, "--as-of")
        except LedgerError as exc:
            print("错误:%s" % exc, file=sys.stderr)
            return EXIT_ERROR
    else:
        args.as_of = date.today()
    try:
        return {
            "report": cmd_report, "show": cmd_show,
            "history": cmd_history, "verdict": cmd_verdict,
        }[args.command](args)
    except LedgerError as exc:
        print("错误:%s" % exc, file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
