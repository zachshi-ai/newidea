#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rebrew · 复现那杯 —— 手冲咖啡参数实验台.

问题：手冲爱好者每次微调参数，偶尔冲出惊艳的一杯却无法复现。
缺两块数据：(1) 过程噪声（同配方重复冲的评分波动，即"手抖幅度"）；
(2) 每个旋钮的效应方向。没有 (1)，所有"我发现 X 更好喝"都可能是噪声。

rebrew 从 TSV 冲煮日志里把这两块算出来：
  analyze   完整报告：总览 / 复现半径 / 旋钮排行 / 分组均值 / 最小可检测效应
  suggest   下一步建议：先复现 / 先降方差 / 散开探索 / 单因素实验计划
  validate  日志格式体检

零依赖：Python 3.8+ 标准库。

用法：
  python3 rebrew.py analyze examples/realistic.tsv
  python3 rebrew.py suggest examples/realistic.tsv [--bean "Ethiopia Chelbesa"]
  python3 rebrew.py validate examples/realistic.tsv
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# 数据模型与常量

REQUIRED_COLUMNS = [
    "date", "bean", "dose_g", "water_g", "temp_c", "grind", "time_s",
    "rating", "notes",
]
NUMERIC_COLUMNS = ["dose_g", "water_g", "temp_c", "grind", "time_s", "rating"]
# 可操控变量（旋钮）。time_s 是过程结果，单独归类。
KNOB_ATTRS = ["temp_c", "grind", "dose_g", "water_g", "ratio"]
PROCESS_ATTRS = ["time_s"]

# 10 分制下的高噪声判定线：σ̂ ≥ 1.5 分时，单因素实验的分辨力太差，
# 先练一致性（固定手法/计时）比调参更有价值。详见 METHODOLOGY.md。
NOISE_CEILING = 1.5
# 最小可检测效应（双样本、每组 n 杯、80% power、α=0.05 的近似）：
#   MDE ≈ (z_{α/2} + z_{β}) · σ · √(2/n) ≈ 2.8 · σ · √(2/n)
MDE_COEFF = 2.8


class ParseError(Exception):
    """日志解析失败。message 汇总所有坏行，便于一次报全。"""


class Pour(object):
    __slots__ = REQUIRED_COLUMNS + ["ratio", "lineno"]

    def __init__(self, **kwargs):
        for key in REQUIRED_COLUMNS:
            setattr(self, key, kwargs[key])
        # dose=0 由 parse_pours 拦截；构造期给 None 而不是除零
        self.ratio = (self.water_g / self.dose_g) if self.dose_g else None
        self.lineno = kwargs["lineno"]

    def fingerprint(self):
        """同配方指纹：豆 + 剂量 + 水量 + 水温 + 研磨。time_s 是过程结果，不入指纹。"""
        return (self.bean, self.dose_g, self.water_g, self.temp_c, self.grind)


# ---------------------------------------------------------------------------
# 解析

def _to_float(value, lineno, column):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("第 %d 行 %s=%r 不是数字" % (lineno, column, value))
    return number


def parse_pours(text):
    """解析 TSV 文本为 Pour 列表。坏行汇总后一次抛 ParseError。"""
    lines = text.splitlines()
    # 前导注释/空行之后的第一行才是表头
    start = 0
    while start < len(lines) and (
            not lines[start].strip() or lines[start].lstrip().startswith("#")):
        start += 1
    lines = lines[start:]
    if not lines:
        raise ParseError("日志为空")
    header = [c.strip() for c in lines[0].split("\t")]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ParseError("表头缺少列: %s" % ", ".join(missing))
    index = {c: i for i, c in enumerate(header)}

    pours, errors = [], []
    for lineno, raw in enumerate(lines[1:], start=2):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cells = raw.split("\t")
        row = {c: cells[index[c]].strip() if index[c] < len(cells) else ""
               for c in header}
        try:
            pour = Pour(
                lineno=lineno,
                date=row["date"],
                bean=row["bean"],
                dose_g=_to_float(row["dose_g"], lineno, "dose_g"),
                water_g=_to_float(row["water_g"], lineno, "water_g"),
                temp_c=_to_float(row["temp_c"], lineno, "temp_c"),
                grind=_to_float(row["grind"], lineno, "grind"),
                time_s=_to_float(row["time_s"], lineno, "time_s"),
                rating=_to_float(row["rating"], lineno, "rating"),
                notes=row.get("notes", ""),
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if pour.dose_g <= 0 or pour.water_g <= 0:
            errors.append("第 %d 行: dose_g/water_g 必须为正" % lineno)
            continue
        if not (0 <= pour.rating <= 10):
            errors.append("第 %d 行 rating=%s 超出 0~10" % (lineno, row["rating"]))
            continue
        if not pour.date or not pour.bean:
            errors.append("第 %d 行: date/bean 不能为空" % lineno)
            continue
        pours.append(pour)
    if errors:
        raise ParseError("\n".join(errors))
    if not pours:
        raise ParseError("日志里没有有效冲煮记录")
    return pours


def read_pours(path):
    with open(path, encoding="utf-8") as fh:
        return parse_pours(fh.read())


def format_pour(pour):
    """一行人类可读的配方快照。"""
    return "%s · %g/%g(1:%.1f)/%g°C/研磨%g/%gs" % (
        pour.date, pour.dose_g, pour.water_g, pour.ratio,
        pour.temp_c, pour.grind, pour.time_s)


# ---------------------------------------------------------------------------
# 统计（自写，可单测）

def mean(xs):
    return sum(xs) / len(xs)


def sample_stdev(xs):
    """样本标准差（n-1 分母）。n < 2 时无定义，返回 None。"""
    n = len(xs)
    if n < 2:
        return None
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def pearson(xs, ys):
    """Pearson 相关系数。n < 2 或任一侧无变化时返回 None。"""
    n = len(xs)
    if n < 2:
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    ssx = sum(v * v for v in dx)
    ssy = sum(v * v for v in dy)
    if ssx == 0 or ssy == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / math.sqrt(ssx * ssy)


def rms(xs):
    """均方根，用于汇总多组标准差为一个过程噪声估计。"""
    return math.sqrt(sum(x * x for x in xs) / len(xs))


# ---------------------------------------------------------------------------
# 分析

def dominant_bean(pours):
    """记录数最多的豆。多豆混日志时，参数效应只有在同豆域内才可比。"""
    return Counter(p.bean for p in pours).most_common(1)[0][0]


def select_domain(pours, bean=None):
    chosen = bean or dominant_bean(pours)
    domain = [p for p in pours if p.bean == chosen]
    return chosen, domain


def reproducibility(pours):
    """复现半径：同配方指纹组的评分波动。

    返回 (重复组列表[(fingerprint, ratings)], sigma 或 None)。
    sigma = 各组样本标准差的均方根；没有任何 n≥2 的组时为 None——
    诚实地承认"测不了"，而不是假装能算。
    """
    groups = defaultdict(list)
    for p in pours:
        groups[p.fingerprint()].append(p.rating)
    repeated = sorted(
        ((fp, rs) for fp, rs in groups.items() if len(rs) >= 2),
        key=lambda item: (-len(item[1]), item[0]))
    if not repeated:
        return [], None
    sigma = rms([sample_stdev(rs) for _, rs in repeated])
    return repeated, sigma


def knob_ranking(pours, attrs=KNOB_ATTRS):
    """旋钮排行：每个变量与评分的 Pearson r，按 |r| 降序。

    无变化的变量 r 为 None，垫底。
    """
    stats = []
    ratings = [p.rating for p in pours]
    for attr in attrs:
        values = [getattr(p, attr) for p in pours]
        r = pearson(values, ratings)
        levels = sorted(set(values))
        stats.append({"attr": attr, "r": r, "n": len(values),
                      "levels": levels})
    stats.sort(key=lambda s: (s["r"] is None, -(abs(s["r"]) if s["r"] is not None else 0), s["attr"]))
    return stats


def group_means(pours, attr):
    """某变量按取值分组的评分均值，按取值升序。"""
    groups = defaultdict(list)
    for p in pours:
        groups[getattr(p, attr)].append(p.rating)
    return sorted((value, mean(rs), len(rs)) for value, rs in groups.items())


def mde(sigma, n_per_group):
    """最小可检测效应：每组 n 杯重复下，多大的均值差异才值得相信。"""
    if sigma is None or n_per_group < 1:
        return None
    return MDE_COEFF * sigma * math.sqrt(2.0 / n_per_group)


def best_fingerprint(pours):
    """评分均值最高的配方指纹（并列时取杯数多者）。"""
    groups = defaultdict(list)
    for p in pours:
        groups[p.fingerprint()].append(p)
    return max(groups.items(),
               key=lambda item: (mean([p.rating for p in item[1]]), len(item[1])))


def best_pour(pours):
    return max(pours, key=lambda p: (p.rating, p.date))


# ---------------------------------------------------------------------------
# 建议：先复现 → 先降方差 → 散开探索 → 单因素实验

def _step(levels):
    """参数的历史最小相邻步长；只有一个取值时返回 None。"""
    if len(levels) < 2:
        return None
    ordered = sorted(levels)
    diffs = [b - a for a, b in zip(ordered, ordered[1:])]
    return min(d for d in diffs if d > 0)


def suggest(pours):
    """返回 dict(kind=..., message=..., plan=[...])。

    kind ∈ reproduce / stabilize / explore / experiment。
    """
    if not pours:
        return {"kind": "reproduce",
                "message": "日志为空：先记录你的下一次冲煮。",
                "plan": []}

    repeated, sigma = reproducibility(pours)
    fp, cups = best_fingerprint(pours)
    fp_text = "%g/%g/%g°C/研磨%g" % (fp[1], fp[2], fp[3], fp[4])

    # 1) 没有同配方重复 → 过程噪声测不了，一切"发现"都无法与手抖区分。
    if sigma is None:
        return {
            "kind": "reproduce",
            "message": ("复现半径还测不出来：日志里没有任何同配方重复冲。"
                        "在谈参数之前，先用当前最高分配方原样复冲，量出你的手抖幅度。"),
            "plan": ["锁定 %s（%s），原样复冲 2~3 次，评分如实记录（哪怕失望）"
                     % (fp_text, cups[0].bean)],
        }

    # 2) 噪声太大 → 单因素实验分辨不出参数效应，先练一致性。
    if sigma >= NOISE_CEILING:
        return {
            "kind": "stabilize",
            "message": ("过程噪声 σ̂ ≈ %.2f 分已超过 %.1f 分的实验线：现在的调参都是抽奖。"
                        "先降方差——固定注水手法与计时，同配方连冲，直到 σ̂ 降下来。"
                        % (sigma, NOISE_CEILING)),
            "plan": ["同配方重复组 %d 组，σ̂ ≈ %.2f 分；评分差小于 %.2f 的对比都是手抖"
                     % (len(repeated), sigma, sigma),
                     "锁定 %s，原样复冲 3 次，目标是把组内波动压到 ±%.1f 分内"
                     % (fp_text, NOISE_CEILING)],
        }

    # 3) 噪声可测且够小 → 看旋钮。全部变量都没动过 → 先散开探索。
    ranking = knob_ranking(pours)
    movable = [s for s in ranking if len(s["levels"]) >= 2]
    if not movable:
        return {
            "kind": "explore",
            "message": ("过程噪声 σ̂ ≈ %.2f 分，实验条件已具备——但日志里只有一种配方，"
                        "参数空间还没散开。" % sigma),
            "plan": ["以 %s 为中心，每次只动一个旋钮：水温 ±2°C 或研磨 ±2 档，各冲 2 杯"
                     % fp_text],
        }

    # 4) 单因素实验：锁最优配方，动最相关旋钮 ±1 步长。
    top = movable[0]
    levels = top["levels"]
    center = max(levels, key=lambda v: mean([p.rating for p in pours
                                             if getattr(p, top["attr"]) == v]))
    step = _step(levels)
    r_text = ("r=%+.2f" % top["r"]) if top["r"] is not None else "r=?"
    low, high = center - step, center + step
    plan = [
        "锁定 %s，其余一切不变" % fp_text,
        "只动 %s：%g 与 %g 各冲 2 杯（当前最优 %g，步长 %g）"
        % (top["attr"], low, high, center, step),
        "判读：两组均值差 ≥ %.2f 分（每组 2 杯的 MDE）才下结论；否则维持原判"
        % mde(sigma, 2),
    ]
    return {
        "kind": "experiment",
        "message": ("过程噪声 σ̂ ≈ %.2f 分，实验条件具备。最相关旋钮是 %s（%s，%d 个取值）。"
                    % (sigma, top["attr"], r_text, len(levels))),
        "plan": plan,
    }


# ---------------------------------------------------------------------------
# 报告



# 旋钮的可读名与单位（报告用）
ATTR_LABEL = {
    "temp_c": "水温", "grind": "研磨", "dose_g": "粉量",
    "water_g": "水量", "ratio": "粉水比", "time_s": "总时间",
}
ATTR_UNIT = {
    "temp_c": "°C", "grind": " 档", "dose_g": "g",
    "water_g": "g", "ratio": "", "time_s": "s",
}


def _fmt_level(attr, value):
    return "%g%s" % (value, ATTR_UNIT.get(attr, ""))


def build_report(pours, bean=None):
    """组装 analyze 的文本报告。"""
    chosen, domain = select_domain(pours, bean)
    lines = []
    lines.append("复现那杯 · Rebrew 分析报告")
    lines.append("=" * 46)
    note = "" if bean else "（自动取记录最多的豆，参数效应须在同豆域内比较）"
    lines.append("数据：%d 条冲煮记录，主豆：%s %d 条 %s"
                 % (len(pours), chosen, len(domain), note))
    dates = sorted(p.date for p in pours)
    lines.append("日期：%s ~ %s" % (dates[0], dates[-1]))

    best = best_pour(domain)
    lines.append("")
    lines.append("【总览】")
    ratings = [p.rating for p in domain]
    lines.append("评分均值 %.2f / 10（最低 %.1f，最高 %.1f）"
                 % (mean(ratings), min(ratings), max(ratings)))
    lines.append("最好一杯 %.1f 分：%s" % (best.rating, format_pour(best)))

    lines.append("")
    lines.append("【复现半径】你的手抖幅度")
    repeated, sigma = reproducibility(domain)
    if sigma is None:
        lines.append("同配方重复组：0 组——测不出来，不假装能算。")
        lines.append("→ 先用同一配方复冲 2~3 次，把过程噪声量出来。")
    else:
        lines.append("同配方重复组 %d 组；过程噪声 σ̂ ≈ %.2f 分（10 分制）"
                     % (len(repeated), sigma))
        lines.append("→ 评分差小于 %.2f 的对比都可能是手抖，不是参数。" % sigma)

    lines.append("")
    lines.append("【旋钮排行】哪些变量真的在动评分")
    ranking = knob_ranking(domain)
    for i, stat in enumerate(ranking, 1):
        r = stat["r"]
        r_text = ("r=%+.2f" % r) if r is not None else "r=—（该变量没动过）"
        marker = ("  ← 最相关"
                  if i == 1 and r is not None and abs(r) >= 0.3 else "")
        lines.append("%2d. %-8s %s（%d 杯，%d 个取值）%s"
                     % (i, ATTR_LABEL.get(stat["attr"], stat["attr"]),
                        r_text, stat["n"], len(stat["levels"]), marker))
    top_r = ranking[0]["r"]
    if top_r is None or abs(top_r) < 0.3:
        lines.append("    → 没有变量与评分强相关（|r|<0.3）："
                     "要么效应被噪声淹没，要么参数空间还没碰到有效区间")
    for stat in knob_ranking(domain, PROCESS_ATTRS):
        r = stat["r"]
        if r is not None:
            lines.append("    过程变量 %s：r=%+.2f（time_s 是结果不是旋钮，相关≠因果）"
                         % (ATTR_LABEL.get(stat["attr"], stat["attr"]), r))

    lines.append("")
    lines.append("【分组均值】")
    for stat in ranking[:3]:
        lines.append("· %s：" % ATTR_LABEL.get(stat["attr"], stat["attr"]))
        for value, m, n in group_means(domain, stat["attr"]):
            lines.append("    %-8s → %.2f 分（%d 杯）"
                         % (_fmt_level(stat["attr"], value), m, n))

    lines.append("")
    lines.append("【最小可检测效应】均值差多大才值得相信")
    if sigma is None:
        lines.append("先测出 σ̂ 才能算（见【复现半径】）。")
    else:
        for n_cups in (2, 3):
            lines.append("每组 %d 杯重复：差异 ≥ %.2f 分（近似 2.8σ√(2/n)）"
                         % (n_cups, mde(sigma, n_cups)))

    lines.append("")
    lines.append("【下一步】运行 python3 rebrew.py suggest 查看具体实验计划")
    return "\n".join(lines)


def build_suggestion_text(result):
    kind_names = {
        "reproduce": "先复现（Reproduce）",
        "stabilize": "先降方差（Stabilize）",
        "explore": "散开探索（Explore）",
        "experiment": "单因素实验（Experiment）",
    }
    lines = ["复现那杯 · 下一步建议", "=" * 24,
             "阶段：%s" % kind_names.get(result["kind"], result["kind"]), "",
             result["message"], ""]
    if result["plan"]:
        lines.append("计划：")
        lines.extend("  %d. %s" % (i, step)
                     for i, step in enumerate(result["plan"], 1))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI

def _load(path):
    try:
        return read_pours(path)
    except ParseError as exc:
        print("日志解析失败：\n%s" % exc, file=sys.stderr)
        raise SystemExit(2)
    except OSError as exc:
        print("无法读取 %s：%s" % (path, exc), file=sys.stderr)
        raise SystemExit(2)


def cmd_analyze(args):
    pours = _load(args.tsv)
    chosen, domain = select_domain(pours, args.bean)
    if not domain:
        print("没有豆名为 %r 的记录" % args.bean, file=sys.stderr)
        return 1
    print(build_report(pours, args.bean))
    return 0


def cmd_suggest(args):
    pours = _load(args.tsv)
    chosen, domain = select_domain(pours, args.bean)
    if not domain:
        print("没有豆名为 %r 的记录" % args.bean, file=sys.stderr)
        return 1
    print(build_suggestion_text(suggest(domain)))
    return 0


def cmd_validate(args):
    try:
        pours = read_pours(args.tsv)
    except ParseError as exc:
        print("✗ 日志有问题：\n%s" % exc)
        return 1
    except OSError as exc:
        print("✗ 无法读取 %s：%s" % (args.tsv, exc))
        return 1
    beans = Counter(p.bean for p in pours)
    print("✓ %d 条记录有效（%s）" % (len(pours),
                                 "、".join("%s×%d" % kv for kv in beans.most_common())))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="rebrew", description="复现那杯：手冲咖啡参数实验台")
    sub = parser.add_subparsers(dest="command", metavar="{analyze,suggest,validate}")

    p_an = sub.add_parser("analyze", help="完整分析报告")
    p_an.add_argument("tsv")
    p_an.add_argument("--bean", default=None, help="限定分析域的豆（默认取记录最多的豆）")
    p_an.set_defaults(func=cmd_analyze)

    p_sg = sub.add_parser("suggest", help="下一步实验建议")
    p_sg.add_argument("tsv")
    p_sg.add_argument("--bean", default=None)
    p_sg.set_defaults(func=cmd_suggest)

    p_vd = sub.add_parser("validate", help="日志格式体检")
    p_vd.add_argument("tsv")
    p_vd.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
