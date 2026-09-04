#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""life-tag · 生命价签 —— 把标价换算成生命小时.

问题：价格以「元」计价，你的劳动以「月」计价，单位不统一，消费决策只能靠
感觉。而唯一直觉可比的单位——名义时薪（月薪 ÷ 工作日 ÷ 8）——是系统性
高估：它假装通勤、下班恢复、工作开销不存在。

life-tag 把这三重「隐形税」拆开，算出真实时薪，再把每一笔消费换算成
「你要白上几天班」，并回答两个经典决策：
  hourly    名义时薪 vs 真实时薪：三重隐形税各吃掉多少（瀑布分解）
  tag       生命价签：一件东西 = 多少生命小时 / 白上几天班，过不过心跳线
  overtime  加班边际时薪 vs 平均真实时薪：这班值不值得加
  leverage  杠杆排行：涨薪 / 搬近 / 远程 / 降恢复 / 砍开销，谁最能提时薪
  profile   画像设置与查看

零依赖：Python 3.8+ 标准库，画像就是一份本地 JSON，不联网不上传。

用法：
  python3 life_tag.py profile set --gross 18000 --tax 0.15 --path p.json
  python3 life_tag.py hourly --path examples/metro_worker.json
  python3 life_tag.py tag 6999 --path examples/metro_worker.json
  python3 life_tag.py overtime 4 --mult 1.5 --path examples/metro_worker.json
  python3 life_tag.py leverage --commute-to 15 --raise 10 --path examples/metro_worker.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# ---------------------------------------------------------------------------
# 数据模型与常量

# 下班恢复系数默认值：每工作 1 小时，另有 0.25 小时因工作而报废
# （瘫着刷手机、缓神、不想做任何正经事的时间）。
DEFAULT_RECOVERY = 0.25
# 心跳线默认值：一次清醒时的完整自由日。超过它的购买，睡一觉再决定。
DEFAULT_PULSE = 8.0
# 杠杆排行里「远程」按每周 5 个工作日折算。
WORKWEEK_DAYS = 5

PROFILE_FIELDS = [
    # (key, 默认值, 说明)
    ("gross_monthly", None, "税前月薪"),
    ("tax_rate", None, "综合税负率（个税+五险一金占税前比例）"),
    ("workdays", 21.0, "月均工作日"),
    ("daily_hours", 8.0, "日均工时"),
    ("commute_min", 0.0, "单程通勤分钟"),
    ("commute_cost", 0.0, "月通勤开销（元）"),
    ("recovery_ratio", DEFAULT_RECOVERY, "下班恢复系数"),
    ("work_costs_extra", 0.0, "其他因工作产生的月开销（工作餐差价、着装等）"),
    ("pulse_line", DEFAULT_PULSE, "心跳线（生命小时），超过则建议睡一觉再决定"),
    ("currency", "¥", "货币符号"),
]

MIN = "min"


class ProfileError(Exception):
    """画像非法。message 说明哪个字段为什么不可接受。"""


def default_profile_path():
    return os.path.join(os.path.expanduser("~"), ".life_tag", "profile.json")


def blank_profile():
    return {key: default for key, default, _ in PROFILE_FIELDS}


def validate_profile(raw):
    """校验并补全画像字段，返回新 dict。宁可报错也不带病计算。"""
    p = blank_profile()
    for key, default, _ in PROFILE_FIELDS:
        if key in raw and raw[key] is not None:
            p[key] = raw[key]

    for key in ("gross_monthly", "tax_rate"):
        if p[key] is None:
            raise ProfileError("缺少必填字段 %s（%s）" % (
                key, dict((k, desc) for k, _, desc in PROFILE_FIELDS)[key]))
    for key in ("gross_monthly", "workdays", "daily_hours", "pulse_line"):
        if not isinstance(p[key], (int, float)) or p[key] <= 0:
            raise ProfileError("%s 必须是正数，当前 %r" % (key, p[key]))
    if not isinstance(p["tax_rate"], (int, float)) or not (0 <= p["tax_rate"] < 1):
        # 上限开区间：税率 100% = 白干，属于填错而不是真实世界
        raise ProfileError("tax_rate 必须在 [0, 1) 内，当前 %r" % p["tax_rate"])
    if not isinstance(p["recovery_ratio"], (int, float)) or not (
            0 <= p["recovery_ratio"] <= 1):
        raise ProfileError("recovery_ratio 必须在 [0, 1] 内，当前 %r"
                           % p["recovery_ratio"])
    # 恢复系数放宽到 1：睡一整天缓过来属于极端但真实存在，>1 视为填错
    if p["recovery_ratio"] > 1:
        raise ProfileError("recovery_ratio > 1：每工作 1 小时要超过 1 小时恢复？请复查")
    for key in ("commute_min", "commute_cost", "work_costs_extra"):
        if not isinstance(p[key], (int, float)) or p[key] < 0:
            raise ProfileError("%s 不能为负，当前 %r" % (key, p[key]))
    if not isinstance(p["commute_min"], (int, float)) or p["commute_min"] > 480:
        raise ProfileError("commute_min 单程超过 480 分钟（8 小时）：这不是通勤是出差")
    if not isinstance(p["currency"], str) or not p["currency"]:
        raise ProfileError("currency 必须是非空字符串")
    return p


def load_profile(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ProfileError("画像文件必须是 JSON 对象：%s" % path)
    return validate_profile(raw)


def save_profile(profile, path):
    p = validate_profile(profile)
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(p, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return p


# ---------------------------------------------------------------------------
# 核心计算：三重隐形税 → 真实时薪

def economics(p):
    """从画像推导全部经济量。返回 dict，键名见 METHODOLOGY.md。"""
    net_month = p["gross_monthly"] * (1.0 - p["tax_rate"])
    nominal_hours = p["workdays"] * p["daily_hours"]
    nominal = net_month / nominal_hours

    commute_hours = p["commute_min"] * 2.0 * p["workdays"] / 60.0
    recovery_hours = p["recovery_ratio"] * nominal_hours
    real_hours = nominal_hours + commute_hours + recovery_hours

    work_costs = p["commute_cost"] + p["work_costs_extra"]
    net_work = net_month - work_costs
    true = net_work / real_hours

    # 瀑布分解（顺序固定：恢复税 → 通勤税 → 开销税）。
    # 每步侵蚀额 = 上一步价格 − 这一步价格，三步之和与总侵蚀精确相抵。
    p1 = net_month / (nominal_hours + recovery_hours)      # 摊上恢复之后
    p2 = net_month / real_hours                            # 摊上通勤之后
    p3 = p2 - work_costs / real_hours                      # 扣掉开销，即 true
    recovery_tax = nominal - p1
    commute_tax = p1 - p2
    cost_tax = p2 - p3
    erosion = (nominal - true) / nominal if nominal else 0.0

    day_net = net_work / p["workdays"]   # 一个班次实际带回家的净钱
    return {
        "net_month": net_month,
        "work_costs": work_costs,
        "net_work": net_work,
        "nominal_hours": nominal_hours,
        "commute_hours": commute_hours,
        "recovery_hours": recovery_hours,
        "real_hours": real_hours,
        "nominal": nominal,
        "true": true,
        "ratio": true / nominal if nominal else 0.0,
        "erosion": erosion,
        "recovery_tax": recovery_tax,
        "commute_tax": commute_tax,
        "cost_tax": cost_tax,
        "day_net": day_net,
    }


# ---------------------------------------------------------------------------
# 生命价签

def price_tag(price, e, pulse_line):
    """把一笔标价换算成生命时间。

    hours   = price ÷ 真实时薪（你要用多少个被通勤和恢复摊薄过的小时来换）
    shifts  = price ÷ day_net（你要白上几天班，钱才属于这件东西）
    """
    hours = price / e["true"]
    shifts = price / e["day_net"]
    over_line = hours > pulse_line
    # 展示主单位：< 3 小时以分钟为主，> 200 小时以班次为主，其余以小时
    if hours < 3:
        unit = "minutes"
    elif hours > 200:
        unit = "shifts"
    else:
        unit = "hours"
    return {
        "hours": hours,
        "minutes": hours * 60.0,
        "shifts": shifts,
        "over_line": over_line,
        "unit": unit,
    }


# ---------------------------------------------------------------------------
# 加班决策

def overtime_math(hours_ot, mult, e):
    """加班边际时薪 = 名义净时薪 × 倍率。

    加班发生在通勤已发生、开销已摊销的时段：边际上每多加班 1 小时，
    只新增这 1 小时本身。所以即使 1 倍率（义务加班），边际时薪通常
    仍高于被三重税侵蚀过的平均真实时薪——这是本件的反直觉洞见。
    breakeven 是你下班时间的自我估价线：低于它，这班在算术上划算。
    """
    marginal = e["nominal"] * mult
    return {
        "hours": hours_ot,
        "mult": mult,
        "earn": marginal * hours_ot,
        "marginal": marginal,
        "avg_real": e["true"],
        "premium": marginal - e["true"],
        "breakeven": marginal,
        "worth_it": marginal > e["true"],
    }


# ---------------------------------------------------------------------------
# 杠杆排行：谁最能提高真实时薪

def _true_with(p, **overrides):
    merged = dict(p)
    merged.update(overrides)
    return economics(validate_profile(merged))["true"]


def leverage_moves(p, actions):
    """每个动作独立重算真实时薪（不做叠加——现实里你不会同时全做）。

    actions 支持的键（均为可选）：
      raise_pct      涨薪百分比（10 = +10%）
      commute_to     搬家/换岗后的单程通勤分钟
      remote_days    每周远程天数（远程日不通勤：时间与开销同步缩减）
      recovery_to    换一份不那么耗人的工作后的恢复系数
      cut_costs      每月砍掉的工作开销（元）
    """
    base = economics(p)["true"]
    moves = []

    if "raise_pct" in actions:
        gross2 = p["gross_monthly"] * (1.0 + actions["raise_pct"] / 100.0)
        t = _true_with(p, gross_monthly=gross2)
        moves.append(("涨薪 %+.1f%%" % actions["raise_pct"], t))

    if "commute_to" in actions:
        target = actions["commute_to"]
        cost2 = (p["commute_cost"] * target / p["commute_min"]
                 if p["commute_min"] > 0 else 0.0)
        t = _true_with(p, commute_min=target, commute_cost=cost2)
        moves.append(("单程通勤 → %g 分钟" % target, t))

    if "remote_days" in actions:
        days = actions["remote_days"]
        if not (0 <= days <= WORKWEEK_DAYS):
            raise ProfileError("remote_days 需在 [0, %d] 内" % WORKWEEK_DAYS)
        frac = 1.0 - days / WORKWEEK_DAYS
        t = _true_with(p,
                       commute_min=p["commute_min"] * frac,
                       commute_cost=p["commute_cost"] * frac)
        moves.append(("每周远程 %g 天" % days, t))

    if "recovery_to" in actions:
        t = _true_with(p, recovery_ratio=actions["recovery_to"])
        moves.append(("恢复系数 → %g" % actions["recovery_to"], t))

    if "cut_costs" in actions:
        extra2 = p["work_costs_extra"] - actions["cut_costs"]
        if extra2 < 0:
            extra2 = 0.0
        t = _true_with(p, work_costs_extra=extra2)
        moves.append(("砍 %g 元/月工作开销" % actions["cut_costs"], t))

    moves.sort(key=lambda item: item[1], reverse=True)
    return [{
        "label": label,
        "true": t,
        "delta": t - base,
        "delta_pct": (t - base) / base * 100.0 if base else 0.0,
    } for label, t in moves]


# ---------------------------------------------------------------------------
# 报告渲染（纯文本，供 CLI 与 dogfood 断言）

def _bar(value, width=24, scale=None):
    if scale is None or scale <= 0:
        scale = value if value > 0 else 1.0
    filled = int(round(value / scale * width)) if scale else 0
    return "█" * max(filled, 0) + "·" * max(width - max(filled, 0), 0)


def _money(p, value):
    return "%s%s" % (p["currency"], _num(value))


def _num(value):
    return format(round(value + 0.0, 2), ",.2f")


def render_hourly(p, e):
    lines = []
    lines.append("【时薪】名义时薪是幻觉，看看它被谁吃掉了")
    lines.append("")
    lines.append("  税后月入      %s（税前 %s × %.0f%%）" % (
        _money(p, e["net_month"]), _money(p, p["gross_monthly"]),
        (1 - p["tax_rate"]) * 100))
    lines.append("  名义时薪      %s / 时（%g 天 × %g 时 = %s 时）" % (
        _money(p, e["nominal"]), p["workdays"],
        p["daily_hours"], _num(e["nominal_hours"])))
    lines.append("")
    lines.append("  三重隐形税瀑布（顺序：恢复 → 通勤 → 开销）")
    for name, amount, note in (
        ("恢复税", e["recovery_tax"],
         "每工作 1 时报废 %g 时，摊薄 %s 时/月" % (
             p["recovery_ratio"], _num(e["recovery_hours"]))),
        ("通勤税", e["commute_tax"],
         "单程 %g 分钟 × 2 × %g 天 = %s 时/月" % (
             p["commute_min"], p["workdays"], _num(e["commute_hours"]))),
        ("开销税", e["cost_tax"],
         "通勤 %s + 其他 %s = %s/月" % (
             _money(p, p["commute_cost"]), _money(p, p["work_costs_extra"]),
             _money(p, e["work_costs"]))),
    ):
        lines.append("    %-4s −%s / 时   %s" % (name, _num(amount), note))
    lines.append("    ──────────────────────────────")
    lines.append("    合计侵蚀 −%s / 时（−%.1f%%）" % (
        _num(e["recovery_tax"] + e["commute_tax"] + e["cost_tax"]),
        e["erosion"] * 100))
    lines.append("")
    scale = e["nominal"]
    lines.append("  名义 %s %s" % (_money(p, e["nominal"]), _bar(e["nominal"], scale=scale)))
    lines.append("  真实 %s %s  ← 只有名义的 %.0f%%" % (
        _money(p, e["true"]), _bar(e["true"], scale=scale), e["ratio"] * 100))
    lines.append("")
    lines.append("  一个班次实际带回家 %s（税后月入扣全部工作开销 ÷ %g 天）" % (
        _money(p, e["day_net"]), p["workdays"]))
    lines.append("  结论：买任何东西前，先问它值不值几个班次。")
    return "\n".join(lines)


def render_tag(p, e, t, pulse_line, price):
    cur = p["currency"]
    lines = []
    lines.append("【生命价签】%s%s" % (cur, _num(price)))
    if t["unit"] == "minutes":
        lines.append("  = %.0f 分钟的命（%.1f 小时 × %s/时 真实时薪）" % (
            t["minutes"], t["hours"], _money(p, e["true"])))
    elif t["unit"] == "shifts":
        lines.append("  = 白上 %.1f 天班（%.0f 生命小时）" % (
            t["shifts"], t["hours"]))
    else:
        lines.append("  = %.1f 生命小时（%.0f 分钟）" % (t["hours"], t["minutes"]))
    lines.append("  或：%s（每班带回家 %s）" % (
        _shifts_text(t["shifts"]), _money(p, e["day_net"])))
    lines.append("")
    if t["over_line"]:
        lines.append("  ⚠ 超过心跳线（%g 生命小时 = 一次完整的自由日）" % pulse_line)
        lines.append("  建议：睡一觉。明早还想要，再买——欲望过夜存活率远低于 100%。")
    else:
        lines.append("  ✓ 心跳线以内（%g 小时）。买得起，也睡得着。" % pulse_line)
    return "\n".join(lines)


def _shifts_text(shifts):
    if shifts < 0.05:
        return "不足 0.05 个班次的净收入"
    return "%.1f 个班次的净收入" % shifts


def render_overtime(p, e, o):
    lines = []
    lines.append("【加班决策】%g 小时 × %g 倍率" % (o["hours"], o["mult"]))
    lines.append("  边际时薪      %s / 时（加班不新增通勤，按名义净时薪 × 倍率结算）" % (
        _money(p, o["marginal"])))
    lines.append("  平均真实时薪  %s / 时（被三重税侵蚀后的白昼均价）" % (
        _money(p, o["avg_real"])))
    lines.append("  这 %g 小时多换 %s（每小时溢价 %s）" % (
        o["hours"], _money(p, o["premium"] * o["hours"]),
        _money(p, o["premium"])))
    lines.append("")
    if o["worth_it"]:
        lines.append("  ✓ 算术上划算：即使 1 倍率，边际时薪也高于你的真实时薪——")
        lines.append("    通勤税和恢复税在白天已经付过了，加班时段不再重复征收。")
    else:
        lines.append("  ✗ 不划算：这份加班的边际时薪低于你被侵蚀后的真实时薪。")
    lines.append("  底线：只要你对下班 1 小时的自我估价低于 %s，这班就值得接。" % (
        _money(p, o["breakeven"])))
    return "\n".join(lines)


def render_leverage(p, base_true, moves):
    lines = []
    lines.append("【杠杆排行】谁最能提高你的真实时薪（各动作独立测算，不叠加）")
    lines.append("  当前真实时薪 %s / 时" % _money(p, base_true))
    if not moves:
        lines.append("  （未给出任何候选动作：试试 --raise 10 --commute-to 15 --remote 2）")
    for i, m in enumerate(moves, 1):
        sign = "+" if m["delta"] >= 0 else "−"
        arrow = " ← 最有效" if i == 1 and len(moves) > 1 else ""
        lines.append("  %d. %-28s %s%s%s（%+.1f%%）%s" % (
            i, m["label"], sign, p["currency"], _num(abs(m["delta"])),
            m["delta_pct"], arrow))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI

def _add_profile_args(sub):
    sub.add_argument("--path", default=default_profile_path(),
                     help="画像 JSON 路径（默认 ~/.life_tag/profile.json）")


def cmd_profile_set(args):
    raw = {}
    for key in ("gross", "tax", "workdays", "hours", "commute",
                "commute_cost", "recovery", "extra_costs", "pulse", "currency"):
        val = getattr(args, key, None)
        if val is not None:
            raw[{
                "gross": "gross_monthly", "tax": "tax_rate",
                "workdays": "workdays", "hours": "daily_hours",
                "commute": "commute_min", "commute_cost": "commute_cost",
                "recovery": "recovery_ratio", "extra_costs": "work_costs_extra",
                "pulse": "pulse_line", "currency": "currency",
            }[key]] = val
    existing = {}
    if os.path.exists(args.path):
        try:
            with open(args.path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except (ValueError, OSError):
            existing = {}
    existing.update(raw)
    p = save_profile(existing, args.path)
    print("画像已写入 %s" % args.path)
    print(render_hourly(p, economics(p)))
    return 0


def cmd_profile_show(args):
    p = load_profile(args.path)
    print(json.dumps(p, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_hourly(args):
    p = load_profile(args.path)
    print(render_hourly(p, economics(p)))
    return 0


def cmd_tag(args):
    if args.price <= 0:
        print("错误：价格必须是正数", file=sys.stderr)
        return 2
    p = load_profile(args.path)
    e = economics(p)
    line = args.line if args.line is not None else p["pulse_line"]
    t = price_tag(args.price, e, line)
    print(render_tag(p, e, t, line, args.price))
    return 0


def cmd_overtime(args):
    if args.hours <= 0:
        print("错误：加班小时数必须是正数", file=sys.stderr)
        return 2
    if args.mult <= 0:
        print("错误：倍率必须是正数", file=sys.stderr)
        return 2
    p = load_profile(args.path)
    o = overtime_math(args.hours, args.mult, economics(p))
    print(render_overtime(p, economics(p), o))
    return 0


def cmd_leverage(args):
    actions = {}
    if args.raise_pct is not None:
        actions["raise_pct"] = args.raise_pct
    if args.commute_to is not None:
        actions["commute_to"] = args.commute_to
    if args.remote is not None:
        actions["remote_days"] = args.remote
    if args.recovery_to is not None:
        actions["recovery_to"] = args.recovery_to
    if args.cut_costs is not None:
        actions["cut_costs"] = args.cut_costs
    p = load_profile(args.path)
    e = economics(p)
    moves = leverage_moves(p, actions)
    print(render_leverage(p, e["true"], moves))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="life_tag", description="生命价签 · Life Tag —— 把标价换算成生命小时")
    subs = ap.add_subparsers(dest="cmd")

    sp = subs.add_parser("profile", help="画像设置与查看")
    psubs = sp.add_subparsers(dest="profile_cmd")

    pset = psubs.add_parser("set", help="设置画像（未给出的字段沿用旧值或默认）")
    _add_profile_args(pset)
    pset.add_argument("--gross", type=float, help="税前月薪")
    pset.add_argument("--tax", type=float, help="综合税负率 0-1")
    pset.add_argument("--workdays", type=float, help="月均工作日")
    pset.add_argument("--hours", type=float, help="日均工时")
    pset.add_argument("--commute", type=float, help="单程通勤分钟")
    pset.add_argument("--commute-cost", dest="commute_cost", type=float,
                      help="月通勤开销")
    pset.add_argument("--recovery", type=float, help="下班恢复系数 0-1")
    pset.add_argument("--extra-costs", dest="extra_costs", type=float,
                      help="其他月度工作开销")
    pset.add_argument("--pulse", type=float, help="心跳线（生命小时）")
    pset.add_argument("--currency", type=str, help="货币符号")
    pset.set_defaults(func=cmd_profile_set)

    pshow = psubs.add_parser("show", help="查看画像")
    _add_profile_args(pshow)
    pshow.set_defaults(func=cmd_profile_show)

    hourly = subs.add_parser("hourly", help="名义时薪 vs 真实时薪：三重隐形税瀑布")
    _add_profile_args(hourly)
    hourly.set_defaults(func=cmd_hourly)

    tag = subs.add_parser("tag", help="生命价签：这件东西 = 多少生命小时 / 几天班")
    tag.add_argument("price", type=float, help="标价")
    tag.add_argument("--line", type=float, default=None,
                     help="心跳线覆盖（默认取画像值）")
    _add_profile_args(tag)
    tag.set_defaults(func=cmd_tag)

    ot = subs.add_parser("overtime", help="加班边际时薪 vs 平均真实时薪")
    ot.add_argument("hours", type=float, help="拟加班小时数")
    ot.add_argument("--mult", type=float, default=1.5, help="加班倍率（默认 1.5）")
    _add_profile_args(ot)
    ot.set_defaults(func=cmd_overtime)

    lev = subs.add_parser("leverage", help="杠杆排行：哪个动作最能提时薪")
    lev.add_argument("--raise", dest="raise_pct", type=float, default=None,
                     help="涨薪百分比")
    lev.add_argument("--commute-to", dest="commute_to", type=float, default=None,
                     help="目标单程通勤分钟")
    lev.add_argument("--remote", dest="remote", type=float, default=None,
                     help="每周远程天数")
    lev.add_argument("--recovery-to", dest="recovery_to", type=float, default=None,
                     help="目标恢复系数")
    lev.add_argument("--cut-costs", dest="cut_costs", type=float, default=None,
                     help="每月砍掉的工作开销")
    _add_profile_args(lev)
    lev.set_defaults(func=cmd_leverage)

    return ap


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        if getattr(args, "cmd", None) == "profile":
            # `profile` 后未跟子命令：打印 profile 自己的用法而不是总帮助
            parser._subparsers._group_actions[0].choices["profile"].print_help()
        else:
            parser.print_help()
        return 2
    try:
        return args.func(args)
    except ProfileError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        # 画像文件不存在 / 不是 JSON / JSON 不是对象，都算用户可修的错误
        print("错误：画像读取失败：%s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
