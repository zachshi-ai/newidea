#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""float-loan · 无息贷款 —— 垫资报销管道账本.

问题：垫出去的钱没有账本。出差垫机票酒店、垫采购、垫团建，报销走
流程动辄一个月，垫款散落在发票袋、聊天记录和记忆里——「管道里有
多少钱、哪笔最老、该去催哪笔」没有人答得上来。公司的 DSO（应收账款
周期）有整个财务部门盯着，你自己的应收账款连一行记录都没有：每一笔
没回的垫款，都是你给公司的无息贷款——利率为零、期限不定、没有合同、
无人感谢。更没人记的是那笔真正的损失：被财务驳回、超标自担的垫款，
报销叙事把它悄悄吞了。

float-loan 把每笔垫付记成一行（TSV：日期/事项/金额/回款/品类[/备注]），
回款列三态：留空 = 在途；0 = 自担（被拒/超标，真·贴钱）；日期 = 回款日。
对同一本账开五本账：

  * pipeline   在途管道：余额、逐笔账龄、超催办线标记（有超龄 → exit 4）
  * stats      总账：回款+在途+自担=总垫付（恒等式）、周期分布 P50/P90、
               回款速率与排空预测、品类贡献分解（加总恒等）
  * float      浮存金：逐笔金额×年化÷365×持有天数，贡献分解加总恒等；
               自担不入浮存——它不是占款，是损失
  * nudge      催办单：超过催办线（自己回款史的 P90）的在途逐笔点名
               （回款 <3 笔 → 催办线无法标定，exit 3）
  * validate   账本体检：三态计数、口径披露、催办线标定状态

催办线只用你自己的历史标定：财务流程的快慢是公司的参数，你的 P90
才是「多慢算不正常」的个人基线——超过它，这不是慢，是忘了。

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
「今天」默认真实当下，`--today` 钉死即逐字节可复现。

用法：
  python3 float_loan.py pipeline floats.tsv --today 2026-09-04
  python3 float_loan.py stats floats.tsv --today 2026-09-04
  python3 float_loan.py float floats.tsv --apr 3.0 --today 2026-09-04
  python3 float_loan.py nudge floats.tsv --today 2026-09-04
  python3 float_loan.py validate floats.tsv --today 2026-09-04

Exit codes:
  0  report produced（含管道空/无超龄）
  2  usage error / 账本缺失 / 坏行 / 未来日期 / 回款早于垫付 / 金额非法
  3  refusal: 账本是空的 / 催办线无法标定（回款 <3 笔）
  4  gate: 存在超过催办线的在途垫款（pipeline / nudge）
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import unicodedata
from collections import OrderedDict, namedtuple
from typing import Dict, List, Optional

PROG = "float-loan"
VERSION = "1.0.0"

THIN_REPAID = 3     # 回款样本不足 3 笔 → 催办线无法标定
DEFAULT_APR = 3.0   # 浮存金年化机会成本（%）：参数不是真理，披露进报告

OUTSTANDING = "OUTSTANDING"
REPAID = "REPAID"
EATEN = "EATEN"

STATE_LABEL = {OUTSTANDING: "在途", REPAID: "回款", EATEN: "自担"}

Row = namedtuple("Row", "date item amount category state repaid note line")


class LedgerError(Exception):
    """账本打不开或行级坏账，一律 exit 2。"""


class Refusal(Exception):
    """账本不足以出报告，exit 3。"""


def normalize(name: str) -> str:
    """品类名规范化：去首尾空白、小写、内部空白折叠；'-' 记 other。"""
    name = re.sub(r"\s+", " ", name.strip().lower())
    return name if name and name != "-" else "other"


def parse_ledger(path: str, today: dt.date) -> List[Row]:
    """解析垫付账本：date/item/amount/repaid[/category[/note]]。

    repaid 三态：留空 = 在途；0 = 自担；YYYY-MM-DD = 回款日（须 ≥ 垫付日
    且 ≤ today）。同一日多笔垫付合法——垫付不是日记，是事件流。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise LedgerError(f"账本打不开：{path}（{exc}）")
    rows: List[Row] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) >= 4 and cols[0].strip().lower() == "date":
            continue  # 表头
        if len(cols) not in (4, 5, 6):
            raise LedgerError(
                f"第 {lineno} 行：需要 4-6 列"
                f"（date/item/amount/repaid[/category[/note]]），"
                f"实得 {len(cols)} 列")
        date_s, item, amount_s, repaid_s = (c.strip() for c in cols[:4])
        category = normalize(cols[4]) if len(cols) >= 5 else "other"
        note = cols[5].strip() if len(cols) == 6 else ""
        if not item:
            raise LedgerError(f"第 {lineno} 行：事项为空")
        try:
            day = dt.date.fromisoformat(date_s)
        except ValueError:
            raise LedgerError(
                f"第 {lineno} 行：日期不是 YYYY-MM-DD：{date_s!r}")
        if day > today:
            raise LedgerError(
                f"第 {lineno} 行：日期 {date_s} 在 --today {today} 之后——"
                f"垫付不能预记")
        try:
            amount = float(amount_s)
        except ValueError:
            raise LedgerError(
                f"第 {lineno} 行：金额不是数字：{amount_s!r}")
        if amount <= 0:
            raise LedgerError(
                f"第 {lineno} 行：金额必须 > 0，实得 {amount_s!r}")
        if repaid_s in ("", "-"):
            state, repaid = OUTSTANDING, None
        elif repaid_s == "0":
            state, repaid = EATEN, None
        else:
            try:
                repaid = dt.date.fromisoformat(repaid_s)
            except ValueError:
                raise LedgerError(
                    f"第 {lineno} 行：回款列只允许 空/0/YYYY-MM-DD，"
                    f"实得 {repaid_s!r}")
            if repaid < day:
                raise LedgerError(
                    f"第 {lineno} 行：回款 {repaid_s} 早于垫付 {date_s}——"
                    f"时间不允许倒流")
            if repaid > today:
                raise LedgerError(
                    f"第 {lineno} 行：回款 {repaid_s} 在 --today {today} 之后——"
                    f"到账不能预记")
            state = REPAID
        rows.append(Row(day, item, amount, category, state, repaid, note,
                        lineno))
    return rows


# ---------------------------------------------------------------- math


def percentile(sorted_vals: List[float], q: float) -> float:
    """线性插值分位数（numpy 默认口径）：pos = (n−1)×q。空表 → 0。"""
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def split(rows: List[Row]):
    """三态拆分。"""
    outstanding = [r for r in rows if r.state == OUTSTANDING]
    repaid = [r for r in rows if r.state == REPAID]
    eaten = [r for r in rows if r.state == EATEN]
    return outstanding, repaid, eaten


def cycles(repaid: List[Row]) -> List[float]:
    """回款周期（天），按垫付日到回款日。"""
    return [(r.repaid - r.date).days for r in repaid]


def nudge_line(repaid: List[Row]) -> Optional[float]:
    """催办线 = 自己回款周期的 P90；样本不足 → None。"""
    cs = sorted(cycles(repaid))
    if len(cs) < THIN_REPAID:
        return None
    return percentile(cs, 0.9)


def float_cost(row: Row, today: dt.date, apr: float) -> float:
    """单笔浮存金 = 金额 × 年化/365 × 持有天数（在途持到今天，回款持到
    回款日）；自担不入浮存。"""
    if row.state == EATEN:
        return 0.0
    end = today if row.state == OUTSTANDING else row.repaid
    days = (end - row.date).days
    return row.amount * (apr / 100.0) / 365.0 * days


def throughput(repaid: List[Row]) -> Optional[float]:
    """回款速率（元/天）= 回款总额 ÷（首笔垫付 → 末笔回款 的窗口）。"""
    if len(repaid) < THIN_REPAID:
        return None
    start = min(r.date for r in repaid)
    end = max(r.repaid for r in repaid)
    days = (end - start).days
    if days <= 0:
        return None
    return sum(r.amount for r in repaid) / days


# ---------------------------------------------------------------- fmt


def dw(s: str) -> int:
    """终端显示宽度：中日韩全角按 2 计。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s: str, w: int) -> str:
    return s + " " * max(0, w - dw(s))


def padl(s: str, w: int) -> str:
    return " " * max(0, w - dw(s)) + s


def yen(x: float) -> str:
    return f"¥{x:,.0f}"


def yen2(x: float) -> str:
    return f"¥{x:,.2f}"


def _today(args) -> dt.date:
    return dt.date.fromisoformat(args.today) if args.today else dt.date.today()


def _load(args) -> List[Row]:
    rows = parse_ledger(args.ledger, _today(args))
    if not rows:
        raise Refusal("账本是空的——先记第一笔垫付，管道才有入口。")
    return rows


# ---------------------------------------------------------------- commands


def cmd_pipeline(args) -> int:
    today = _today(args)
    rows = _load(args)
    outstanding, repaid, eaten = split(rows)
    if not outstanding:
        print(
            f"管道空 · 记录 {len(rows)} 笔垫付：回款 {len(repaid)} 笔 "
            f"{yen(sum(r.amount for r in repaid))}，自担 {len(eaten)} 笔"
            f"（{yen(sum(r.amount for r in eaten))}）——无息贷款余额 ¥0")
        return 0
    line = nudge_line(repaid)
    total = sum(r.amount for r in outstanding)
    oldest = max((today - r.date).days for r in outstanding)
    print(
        f"在途管道 · {len(outstanding)} 笔 {yen(total)}"
        f"（垫付 {len(rows)} 笔 · 回款 {len(repaid)} · 自担 {len(eaten)}）"
        f" · 最老 {oldest} 天")
    if line is None:
        print(
            f"  催办线：未标定（回款 {len(repaid)} 笔 < {THIN_REPAID} 笔）——"
            f"先攒回款样本，账龄仅供排序")
    else:
        print(
            f"  催办线 {line:.1f} 天（自己回款史的 P90）——超过它，"
            f"这不是慢，是忘了")
    print()
    print(f"  {padl('#', 3)}  {pad('事项', 20)}{pad('品类', 10)}"
          f"{padl('金额', 9)}{padl('账龄', 6)}  状态")
    for i, r in enumerate(sorted(outstanding,
                                 key=lambda r: (r.date, r.line)), 1):
        age = (today - r.date).days
        if line is not None and age > line:
            mark = f"✗ 超催办线 {age - line:.0f} 天"
        else:
            mark = "○ 线内"
        print(f"  {padl(str(i), 3)}  {pad(r.item, 20)}{pad(r.category, 10)}"
              f"{padl(yen(r.amount), 9)}{padl(f'{age}天', 6)}  {mark}")
    print()
    stale = [r for r in outstanding
             if line is not None and (today - r.date).days > line]
    if stale:
        names = "、".join(r.item for r in stale)
        print(
            f"判定 RED —— {len(stale)} 笔超催办线（{names}）："
            f"{yen(sum(r.amount for r in stale))} 在被遗忘。"
            f"nudge 看催办单。")
        return 4
    print(f"判定 GREEN —— 无超龄在途（利率是 ¥0，遗忘才是成本）。")
    return 0


def cmd_stats(args) -> int:
    today = _today(args)
    rows = _load(args)
    outstanding, repaid, eaten = split(rows)
    total = sum(r.amount for r in rows)
    out_sum = sum(r.amount for r in outstanding)
    rep_sum = sum(r.amount for r in repaid)
    eat_sum = sum(r.amount for r in eaten)
    print(
        f"垫付总账 · {len(rows)} 笔 {yen(total)}"
        f"（{rows[0].date} → {max(r.date for r in rows)}） · "
        f"--today {today}")
    print(
        f"  回款 {yen(rep_sum)}（{len(repaid)} 笔） + 在途 {yen(out_sum)}"
        f"（{len(outstanding)} 笔） + 自担 {yen(eat_sum)}"
        f"（{len(eaten)} 笔） = {yen(total)}")
    print(
        f"  恒等式核验：三态之和 = 总垫付，残差 "
        f"{abs(rep_sum + out_sum + eat_sum - total):.6f}"
        f"——一笔不多，一笔不少")
    cs = sorted(cycles(repaid))
    if cs:
        p50 = percentile(cs, 0.5)
        p90 = percentile(cs, 0.9)
        thin = "（样本薄，仅供排序）" if len(cs) < THIN_REPAID else ""
        print(
            f"  回款周期：P50 {p50:.1f} 天 · P90 {p90:.1f} 天 · "
            f"最慢 {max(cs):.0f} 天 · 最快 {min(cs):.0f} 天{thin}")
    else:
        print("  回款周期：还没有回款样本——催办线无从标定")
    rate = throughput(repaid)
    if rate is not None and outstanding:
        drain = out_sum / rate
        print(
            f"  回款速率 {yen(rate)}/天（回款 {yen(rep_sum)} ÷ 回款窗口）"
            f" → 按此速率排空在途约 {drain:.0f} 天")
    elif outstanding:
        print("  回款速率：样本不足，排空预测不出——先攒回款")
    if eaten:
        worst = max(eaten, key=lambda r: r.amount)
        print(
            f"  自担 {yen(eat_sum)}——这是真·贴钱：{worst.item} "
            f"{yen(worst.amount)} 被财务的「不符合规定」吃掉，"
            f"报销叙事从不给它立碑")
    print()
    print("  品类贡献（按垫付额，加总恒等）：")
    cats: Dict[str, float] = OrderedDict()
    for r in rows:
        cats[r.category] = cats.get(r.category, 0.0) + r.amount
    for name, amount in sorted(cats.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {pad(name, 14)}{padl(yen(amount), 10)}"
              f"  {amount / total * 100:.1f}%")
    print(f"    {'—' * 6} 加总 {yen(sum(cats.values()))} = 总垫付 "
          f"{yen(total)}（残差 {abs(sum(cats.values()) - total):.6f}）")
    return 0


def cmd_float(args) -> int:
    today = _today(args)
    rows = _load(args)
    outstanding, repaid, eaten = split(rows)
    apr = args.apr
    daily = apr / 100.0 / 365.0
    costs = [(r, float_cost(r, today, apr)) for r in rows]
    total = sum(c for _, c in costs)
    out_sum = sum(r.amount for r in outstanding)
    print(
        f"浮存金账 · 年化 {apr:g}%（--apr 可调：余额宝 3 / 理财 4 / "
        f"信用卡 18） · --today {today}")
    print(
        f"  在途 {yen(out_sum)} 是你借给公司的无息贷款本金；"
        f"按机会成本折算，账本期内你已贴出 {yen2(total)} 利息")
    if eaten:
        print(
            f"  自担 {yen(sum(r.amount for r in eaten))} 不入浮存——"
            f"它不是占款，是损失，利率算不出被驳回的钱")
    print()
    print(f"  {padl('#', 3)}  {pad('事项', 20)}{padl('金额', 9)}"
          f"{padl('持有', 7)}{padl('浮存金', 10)}")
    for i, (r, c) in enumerate(costs, 1):
        if r.state == EATEN:
            hold, cost_txt = "—", "—（自担）"
        else:
            end = today if r.state == OUTSTANDING else r.repaid
            hold = f"{(end - r.date).days}天"
            cost_txt = yen2(c)
        print(f"  {padl(str(i), 3)}  {pad(r.item, 20)}"
              f"{padl(yen(r.amount), 9)}{padl(hold, 7)}{padl(cost_txt, 10)}")
    print(f"  {'—' * 6} 加总 {yen2(sum(c for _, c in costs))}（残差 "
          f"{abs(total - sum(c for _, c in costs)):.8f}）")
    print(
        "诚实条款：利率是参数不是真理——浮存金 "
        f"{yen2(total)} 看着是小钱，但这本账的真正成本不是年化利率，"
        "是在途本金从生活费里消失而你毫无察觉。利息记账，遗忘才是灾难。")
    return 0


def cmd_nudge(args) -> int:
    today = _today(args)
    rows = _load(args)
    outstanding, repaid, _ = split(rows)
    line = nudge_line(repaid)
    if line is None:
        print(
            f"催办线无法标定：回款 {len(repaid)} 笔 < {THIN_REPAID} 笔——"
            f"没有你自己的周期史，「多慢算不正常」就还是感觉不是线。",
            file=sys.stderr)
        return 3
    stale = [r for r in outstanding if (today - r.date).days > line]
    if not stale:
        print(
            f"催办单 · 催办线 {line:.1f} 天（P90） · 在途 "
            f"{len(outstanding)} 笔全部线内——无单可开，等下一笔老化")
        return 0
    print(
        f"催办单 · 催办线 {line:.1f} 天（自己回款史的 P90，"
        f"{len(repaid)} 笔标定） · {len(stale)} 笔超线")
    for r in sorted(stale, key=lambda r: (r.date, r.line)):
        age = (today - r.date).days
        print(
            f"  ✗ {pad(r.item, 20)}{padl(yen(r.amount), 9)}"
            f"  已 {age} 天，超线 {age - line:.0f} 天（垫付 {r.date}）")
    print(
        f"合计 {yen(sum(r.amount for r in stale))} 在被遗忘——"
        f"催办不是撕破脸，是替财务想起他们自己的流程")
    return 4


def cmd_validate(args) -> int:
    today = _today(args)
    rows = _load(args)
    outstanding, repaid, eaten = split(rows)
    line = nudge_line(repaid)
    span = (max(r.date for r in rows) - min(r.date for r in rows)).days + 1
    print(
        f"账本体检 · {len(rows)} 笔垫付（{rows[0].date} → "
        f"{max(r.date for r in rows)}，跨度 {span} 天） · --today {today}")
    print(
        f"  三态：在途 {len(outstanding)} 笔 {yen(sum(r.amount for r in outstanding))}"
        f" · 回款 {len(repaid)} 笔 {yen(sum(r.amount for r in repaid))}"
        f" · 自担 {len(eaten)} 笔 {yen(sum(r.amount for r in eaten))}")
    if line is None:
        print(
            f"  催办线：未标定（回款 <{THIN_REPAID} 笔）——"
            f"nudge 拒绝开工，pipeline 只按账龄排序")
    else:
        print(f"  催办线 {line:.1f} 天（P90，{len(repaid)} 笔回款标定）")
    cats = sorted({r.category for r in rows})
    print(f"  品类 {len(cats)} 个：{' · '.join(cats)}")
    print(
        "账本只记你垫出去的钱：不连财务系统、不猜报销流程、"
        "不替你催——催办单开着，发不发消息是人的决定。")
    return 0


# ---------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="无息贷款 —— 垫资报销管道账本")
    parser.add_argument("--version", action="version",
                        version=f"{PROG} {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func, helptext in (
            ("pipeline", cmd_pipeline, "在途管道（有超龄 exit 4）"),
            ("stats", cmd_stats, "总账：三态恒等式 + 周期分布 + 品类分解"),
            ("float", cmd_float, "浮存金：占款的机会成本"),
            ("nudge", cmd_nudge, "催办单：超催办线逐笔点名"),
            ("validate", cmd_validate, "账本体检")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("ledger", help="垫付账本 TSV")
        p.add_argument("--today", help="钉死「今天」（YYYY-MM-DD，测试用）")
        if name == "float":
            p.add_argument("--apr", type=float, default=DEFAULT_APR,
                           help="浮存金年化 %%（默认 3.0）")
        p.set_defaults(func=func)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LedgerError as exc:
        print(f"账本拒收：{exc}", file=sys.stderr)
        return 2
    except Refusal as exc:
        print(f"拒绝出账：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
