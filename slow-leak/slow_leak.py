#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slow-leak · 暗漏 —— 家庭三表账单异常侦探.

问题：账单不会说谎，但它会含糊。电/水/燃气以月为单位聚合到家门口，
直觉对「物理用量」没有任何审计能力：冬天的电费高是采暖还是坏冰箱？
夏天水费低是节水还是没回家？逐月 3% 的蠕升肉眼彻底无感，年底打开
总账才发现翻倍——漏电、漏水、漏气，全是慢漏，等发现就已经交了一年的
冤枉钱。而现有的账单 App 只会画柱状图，从不回答唯一要紧的问题：
**哪张表、从哪期开始、超出了什么基线、放任一年要多少**。

slow-leak 从一本可手编的月度账本（TSV：月份/表/用量）确定性算出：

  * check     最新账期三表体检：同比突变（SPIKE）与连涨蠕升（LEAK）双检测，红灯 exit 4
  * trend     单表全史：每期的用量、同比与状态标记
  * detect    全史扫描：历史上每一次突变与蠕升事件（修好的也记得）
  * floor     待机底座：各表历史最低月——你家拔不掉的那部分消耗
  * validate  账本体检
  * utilities 三表说明（单位与惯犯清单）

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
「今天」默认真实当下，`--today` 钉死即逐字节可复现。

用法：
  python3 slow_leak.py check ledger.tsv --today 2026-09-04
  python3 slow_leak.py trend ledger.tsv --utility electric
  python3 slow_leak.py detect ledger.tsv
  python3 slow_leak.py floor ledger.tsv
  python3 slow_leak.py validate ledger.tsv
  python3 slow_leak.py utilities

Exit codes:
  0  report produced（含绿灯）
  2  usage error / 账本缺失 / 坏行 / 未来账期
  3  refusal: nothing to compute (空账本、指定表不在账本中)
  4  gate: 任一表 SPIKE 或 LEAK
"""

from __future__ import annotations

import argparse
import datetime as dt
import statistics
import sys
from typing import Dict, List, Optional, Tuple

PROG = "slow-leak"
VERSION = "1.0.0"

# 缺省三表及其单位与惯犯清单（其他表名自由，按「单位」计）。
UTILITIES = {
    "electric": ("度", "坏冰箱启动器、老化热水器、24 小时插排、水泵"),
    "water": ("吨", "马桶水箱漏水、暗管渗漏、净水器排废、滴灌没关"),
    "gas": ("方", "热水器水垢、燃气泄漏（立即报修！）、采暖炉效率衰减"),
}

SPIKE_RATIO = 1.25    # 同比上涨超过 25% → SPIKE
DROP_RATIO = 0.75     # 同比下降超过 25% → DROP（提示，不判灯）
LEAK_RISES = 3        # 近 4 期至少 3 次环比上涨
LEAK_TOTAL = 1.20     # 且最新值 ≥ 4 期前的 1.2 倍
LEAK_WINDOW = 4       # 蠕升窗口长度
MIN_PERIODS = 4       # 少于 4 期 → THIN，不判灯


class UsageError(Exception):
    """exit 2：参数或账本错误。"""


class Refusal(Exception):
    """exit 3：无可计算。"""


class RedLight(Exception):
    """exit 4：判灯越线（任一表 SPIKE/LEAK）。携带报告文本。"""


# ---------------------------------------------------------------------------
# 账本解析
# ---------------------------------------------------------------------------

def parse_month(text: str, lineno: int) -> Tuple[int, int]:
    try:
        d = dt.datetime.strptime(text, "%Y-%m")
        return d.year, d.month
    except ValueError:
        raise UsageError(f"第 {lineno} 行：月份「{text}」不是 YYYY-MM")


def fmt_amount(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


class Row:
    def __init__(self, year: int, month: int, utility: str, amount: float, lineno: int):
        self.year = year
        self.month = month
        self.utility = utility
        self.amount = amount
        self.lineno = lineno

    @property
    def ym(self) -> Tuple[int, int]:
        return (self.year, self.month)

    @property
    def month_key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def load_ledger(path: str, current_ym: Tuple[int, int]) -> Dict[str, List[Row]]:
    """读月度账本，按表分组、按月份排序。坏行带行号 exit 2。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        raise UsageError(f"账本文件不存在：{path}")
    rows: List[Row] = []
    seen: set = set()
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        if len(cols) < 3:
            raise UsageError(f"第 {lineno} 行：需要至少 3 列（月份/表/用量），得到 {len(cols)} 列")
        year, month = parse_month(cols[0], lineno)
        if (year, month) > current_ym:
            raise UsageError(f"第 {lineno} 行：账期 {cols[0]} 在当前月之后")
        utility = cols[1]
        try:
            amount = float(cols[2])
        except ValueError:
            raise UsageError(f"第 {lineno} 行：用量「{cols[2]}」不是数字")
        if amount <= 0:
            raise UsageError(f"第 {lineno} 行：用量必须 > 0，得到 {amount}")
        key = ((year, month), utility)
        if key in seen:
            raise UsageError(f"第 {lineno} 行：{cols[0]} 的 {utility} 表重复记账")
        seen.add(key)
        rows.append(Row(year, month, utility, amount, lineno))
    if not rows:
        raise Refusal(f"账本是空的：{path}")
    grouped: Dict[str, List[Row]] = {}
    for r in rows:
        grouped.setdefault(r.utility, []).append(r)
    for util in grouped:
        grouped[util].sort(key=lambda r: r.ym)
    return grouped


# ---------------------------------------------------------------------------
# 检测器
# ---------------------------------------------------------------------------

def yoy_baseline(rows: List[Row], ym: Tuple[int, int]) -> Tuple[Optional[float], int]:
    """去年同期基线：去年同月与（若有）前年同月的中位数。n=0 表示无对照。"""
    values = [r.amount for r in rows if (r.year == ym[0] - 1 and r.month == ym[1])
              or (r.year == ym[0] - 2 and r.month == ym[1])]
    if not values:
        return None, 0
    return statistics.median(values), len(values)


def contiguous(rows: List[Row], count: int) -> bool:
    """最后 count 期是否月份连续（中间断月则蠕升检测不可信）。"""
    for prev, cur in zip(rows[-count:], rows[-count + 1:]):
        expected = (prev.year + 1, 1) if prev.month == 12 else (prev.year, prev.month + 1)
        if (cur.year, cur.month) != expected:
            return False
    return True


def leak_check(rows: List[Row]) -> Tuple[bool, Optional[str]]:
    """蠕升检测：近 4 期 ≥3 次环比上涨，且最新 ≥1.2× 窗口首期，
    且最新 ≥1.2× 去年同期——季节爬坡（冬采暖、夏空调）每年都涨一遍，
    纯环比会被它骗；同比对照是季节免疫的来源。无同期对照则不判。"""
    if len(rows) < LEAK_WINDOW:
        return False, None
    window = rows[-LEAK_WINDOW:]
    if not contiguous(rows, LEAK_WINDOW):
        return False, "断月"
    rises = sum(1 for a, b in zip(window, window[1:]) if b.amount > a.amount)
    if rises < LEAK_RISES:
        return False, None
    if window[-1].amount < LEAK_TOTAL * window[0].amount:
        return False, None
    base, n = yoy_baseline(rows, window[-1].ym)
    if base is None or window[-1].amount < LEAK_TOTAL * base:
        return False, None
    detail = f"{window[0].month_key}→{window[-1].month_key} 四期 " \
             f"{fmt_amount(window[0].amount)} → {fmt_amount(window[-1].amount)}（{LEAK_RISES} 次环比上涨）"
    return True, detail


def period_status(rows: List[Row], idx: int) -> dict:
    """第 idx 期的状态：spike / drop / leak / thin / no-baseline。"""
    cur = rows[idx]
    baseline, n = yoy_baseline(rows, cur.ym)
    out = {"spike": False, "drop": False, "leak": False, "thin": len(rows) < MIN_PERIODS,
           "baseline": baseline, "n": n, "ratio": None, "leak_detail": None}
    if baseline is not None and not out["thin"]:
        out["ratio"] = cur.amount / baseline
        if out["ratio"] > SPIKE_RATIO:
            out["spike"] = True
        elif out["ratio"] < DROP_RATIO:
            out["drop"] = True
    if not out["thin"]:
        leak, detail = leak_check(rows[:idx + 1])
        out["leak"] = leak
        out["leak_detail"] = detail
    return out


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def unit_of(utility: str) -> str:
    return UTILITIES.get(utility, ("单位", ""))[0]


def status_marks(st: dict) -> str:
    marks = []
    if st["thin"]:
        return "◌ THIN（不足 4 期，不判灯）"
    if st["spike"]:
        marks.append("⚡ SPIKE")
    if st["leak"]:
        marks.append("✗ LEAK")
    if st["drop"]:
        marks.append("▽ drop")
    return "  ".join(marks) if marks else "· NORMAL"


def cmd_check(ledger: Dict[str, List[Row]]) -> Tuple[str, int]:
    total_rows = sum(len(v) for v in ledger.values())
    latest_ym = max(r.ym for rows in ledger.values() for r in rows)
    lines = [f"暗漏体检 · 最新账期 {latest_ym[0]:04d}-{latest_ym[1]:02d}"
             f"（共 {total_rows} 期账，{len(ledger)} 张表）", ""]
    flagged = []
    for util in sorted(ledger):
        rows = ledger[util]
        st = period_status(rows, len(rows) - 1)
        cur = rows[-1]
        base_text = "无同期对照"
        if st["baseline"] is not None:
            base_text = (f"去年同期 {fmt_amount(st['baseline'])} → "
                         f"{(st['ratio'] - 1) * 100:+.1f}%")
        lines.append(f"  {util:<10s} {cur.month} 月 {fmt_amount(cur.amount):>5} {unit_of(util)}"
                     f"   {base_text}   {status_marks(st)}")
        if st["spike"] or st["leak"]:
            flagged.append((util, st, cur))
    if not flagged:
        lines.append("")
        lines.append("判定  GREEN —— 三表在轨。蠕升是慢性的，建议每月记账让基线继续变厚。")
        return "\n".join(lines) + "\n", 0
    lines.append("")
    names = "、".join(u for u, _, _ in flagged)
    lines.append(f"判定  RED —— {names} 在偷跑")
    lines.append("")
    suspects = []
    for util, st, cur in flagged:
        if st["spike"]:
            delta = cur.amount - st["baseline"]
            lines.append(f"  {util} SPIKE：比去年同期多 {fmt_amount(delta)} {unit_of(util)}"
                         f"（+{(st['ratio'] - 1) * 100:.1f}%，容忍线 +{(SPIKE_RATIO - 1) * 100:.0f}%），"
                         f"放任一年多 {fmt_amount(delta * 12)} {unit_of(util)}")
            suspects.append(util)
        if st["leak"]:
            lines.append(f"  {util} LEAK：{st['leak_detail']}"
                         f"——突变是事故（一次坏了），连涨是泄漏（有东西在偷跑）")
            if util not in suspects:
                suspects.append(util)
    lines.append("")
    lines.append("排查顺序：先想「家里最近添了什么」，再查惯犯：" +
                 "；".join(f"{u}（{UTILITIES[u][1]}）" if u in UTILITIES else u for u in dict.fromkeys(suspects)))
    return "\n".join(lines) + "\n", 4


def cmd_trend(ledger: Dict[str, List[Row]], utility: str) -> Tuple[str, int]:
    if utility not in ledger:
        raise Refusal(f"账本里没有「{utility}」这张表。现有的表：{'、'.join(sorted(ledger))}")
    rows = ledger[utility]
    lines = [f"{utility} 全史 · {len(rows)} 期 · {unit_of(utility)}", ""]
    lines.append(f"  账期        用量   同比       状态")
    events = 0
    for i, r in enumerate(rows):
        st = period_status(rows, i)
        marks = status_marks(st)
        if st["spike"] or st["leak"]:
            events += 1
        base = "    —"
        if st["baseline"] is not None and st["ratio"] is not None:
            base = f"{(st['ratio'] - 1) * 100:+6.1f}%"
        note = "（无同期对照）" if st["n"] == 0 and not st["thin"] else ""
        if st["thin"]:
            note = "（攒账期中）"
        lines.append(f"  {r.month_key}  {fmt_amount(r.amount):>6}   {base}  {marks}{note}")
    lines.append("")
    lines.append(f"全史异常 {events} 期。突变的锚是去年同期——季节是共变，同比才是对照。")
    return "\n".join(lines) + "\n", 0


def cmd_detect(ledger: Dict[str, List[Row]]) -> Tuple[str, int]:
    spikes, leaks, drops = [], [], []
    for util in sorted(ledger):
        rows = ledger[util]
        for i in range(len(rows)):
            st = period_status(rows, i)
            tag = f"  {util:<10s} {rows[i].month_key}  {fmt_amount(rows[i].amount)} {unit_of(util)}"
            if st["spike"]:
                spikes.append(f"{tag}  ⚡ SPIKE（同比 +{(st['ratio'] - 1) * 100:.1f}%）")
            if st["leak"]:
                leaks.append(f"{tag}  ✗ LEAK（{st['leak_detail']}）")
            if st["drop"]:
                drops.append(f"{tag}  ▽ 比去年同期低 {abs((st['ratio'] - 1) * 100):.1f}%"
                             f"——若同期没搬人没出差，查表具或习惯")
    lines = [f"全史异常扫描 · {sum(len(v) for v in ledger.values())} 期账", ""]
    lines.append(f"SPIKE（同比突变）：{len(spikes)} 次")
    lines.extend(spikes)
    lines.append("")
    lines.append(f"LEAK（连涨蠕升）：{len(leaks)} 次")
    lines.extend(leaks)
    if drops:
        lines.append("")
        lines.append(f"DROP（同比陡降，漂移提示）：{len(drops)} 次")
        lines.extend(drops)
    lines.append("")
    if not spikes and not leaks:
        lines.append("全史干净：没有一次突变或蠕升。")
    else:
        lines.append("突变年检一次就有；蠕升要靠连续记账才现形——这是账本变厚的意义。")
    return "\n".join(lines) + "\n", 0


def cmd_floor(ledger: Dict[str, List[Row]]) -> Tuple[str, int]:
    latest_ym = max(r.ym for rows in ledger.values() for r in rows)
    lines = ["待机底座 · 各表历史最低月", ""]
    lines.append("  底座是下界估计：最低月 ≈ 拔不掉的那部分（待机 + 最低生活流量），")
    lines.append("  不是纯待机——那个月你可能不在家。它回答的是「你的消耗有多少是地板」。")
    lines.append("")
    for util in sorted(ledger):
        rows = ledger[util]
        lo = min(rows, key=lambda r: r.amount)
        current = next((r for r in rows if r.ym == latest_ym), None)
        if current is not None and current.amount > 0:
            share = lo.amount / current.amount
            lines.append(f"  {util:<10s} 底座 {fmt_amount(lo.amount):>5} {unit_of(util)}"
                         f"（{lo.month_key}）  最新月 {fmt_amount(current.amount):>5}"
                         f" → 底座占 {share:.0%}")
        else:
            lines.append(f"  {util:<10s} 底座 {fmt_amount(lo.amount):>5} {unit_of(util)}"
                         f"（{lo.month_key}）  最新月无账")
    lines.append("")
    lines.append("底座突然变厚（最低月抬高）通常意味着新常驻负载：新电器、新住户、坏掉的东西。")
    lines.append("把 floor 每季度看一次：地板的高度，就是你家消费习惯的体温。")
    return "\n".join(lines) + "\n", 0


def cmd_validate(ledger: Dict[str, List[Row]]) -> Tuple[str, int]:
    total = sum(len(v) for v in ledger.values())
    lines = [f"账本体检 · {len(ledger)} 张表 · {total} 期账", ""]
    for util in sorted(ledger):
        rows = ledger[util]
        thin = "（THIN，不足 4 期）" if len(rows) < MIN_PERIODS else ""
        span = f"{rows[0].month_key} → {rows[-1].month_key}"
        lines.append(f"  {util:<10s} {len(rows):>3} 期  {span} {thin}")
    lines.append("")
    lines.append("账本干净：月份合法、无重复账期、无未来账期、用量均为正数。")
    return "\n".join(lines) + "\n", 0


def cmd_utilities() -> Tuple[str, int]:
    lines = ["缺省三表（表名自由，其他表按「单位」计）：", ""]
    for name, (unit, culprits) in UTILITIES.items():
        lines.append(f"  {name:<10s} 单位：{unit}")
        lines.append(f"              惯犯：{culprits}")
    lines.append("")
    lines.append("账本只记物理用量，不记金额：金额被价格变动污染，用量才是房子的心跳。")
    lines.append("燃气若因泄漏异常，先开窗报修，再记账。")
    return "\n".join(lines) + "\n", 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description="slow-leak · 暗漏 —— 家庭三表账单异常侦探")
    p.add_argument("--version", action="version", version=f"{PROG} {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("ledger", help="月度账本 TSV：月份/表/用量")
        sp.add_argument("--today", default=None, help="钉死「今天」为 YYYY-MM-DD（默认真实当下）")

    common(sub.add_parser("check", help="最新账期三表体检与判灯"))
    t = sub.add_parser("trend", help="单表全史趋势")
    common(t)
    t.add_argument("--utility", required=True, help="表名（如 electric）")
    common(sub.add_parser("detect", help="全史异常扫描"))
    common(sub.add_parser("floor", help="待机底座"))
    common(sub.add_parser("validate", help="账本体检"))
    sub.add_parser("utilities", help="三表说明")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "utilities":
            text, code = cmd_utilities()
            print(text, end="")
            return code
        today = dt.date.today() if not getattr(args, "today", None) else dt.datetime.strptime(args.today, "%Y-%m-%d").date()
        current_ym = (today.year, today.month)
        ledger = load_ledger(args.ledger, current_ym)
        if args.cmd == "check":
            text, code = cmd_check(ledger)
        elif args.cmd == "trend":
            text, code = cmd_trend(ledger, args.utility)
        elif args.cmd == "detect":
            text, code = cmd_detect(ledger)
        elif args.cmd == "floor":
            text, code = cmd_floor(ledger)
        elif args.cmd == "validate":
            text, code = cmd_validate(ledger)
        else:  # pragma: no cover
            raise UsageError(f"未知子命令：{args.cmd}")
        print(text, end="")
        return code
    except UsageError as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 2
    except Refusal as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 3
    except RedLight as e:
        print(str(e), end="")
        return 4


if __name__ == "__main__":
    sys.exit(main())
