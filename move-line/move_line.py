#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""move-line · 挪窝线 —— 续租还是搬家的无差异涨租率.

问题：涨租通知贴上门的那晚，唯一被展示的数字是涨幅——「+12%」，而
+12% 的直觉反应是愤怒。但「涨多少」从来不是决策变量，真正的题目是：
搬家的总成本和留下的总成本，哪边更低。搬家的一次性成本（中介费、
搬家公司、拆装、保洁、宽带、请假误工）散落且从没人列全；便宜的房子
往往更远，省下的租金被通勤时间吃掉多少没人算过；搬家费的回本期和你
打算再住的年数从不被对照——「省 300/月，回本 17 个月，可你只签一年」。
没有一条算出来的线，每次续租都是重新愤怒投票。

move-line 把现居与候选房源抄成可手编的账本（homes.tsv：住处/月租/
通勤/角色；move.tsv：搬家一次性成本），对涨租通知开庭：

  * cap          盲搬线：没有候选房源时的第一根标尺（搬家税月摊）
  * judge        裁决：房东报价 vs 忍价线（✓忍 / ◐掷币 / ✗挪，✗ exit 4）
  * compare      对账单：候选房源年净成本排行 + 陷阱灯 + 回本灯
  * toll         搬家税单：一次性成本明细 + 糊涂账护栏（漏项横幅）
  * sensitivity  敏感性：再住年数 × 通勤时薪 的忍价线矩阵
  * validate     账本体检：口径披露、漏项清点、盲搬线与实线

核心量：年净成本 = 月租×12 + 年通勤税（单程分钟×2×年通勤天数×时薪÷60）
+ 年搬家税（一次性成本 ÷ 预计再住年数）。忍价线 = 使「搬到最优候选」
与「留在现居」年净成本相等的涨幅；没有候选时退化为盲搬线 = 搬家税
月摊 ÷ 现租——它只量搬家税本身，不量市场。

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
本件不抓房源、不预测市场、不下决定——它只把愤怒翻译成算术。

用法：
  python3 move_line.py cap homes.tsv move.tsv
  python3 move_line.py judge homes.tsv move.tsv --offer 5040
  python3 move_line.py judge homes.tsv move.tsv --pct 8 --years 1
  python3 move_line.py compare homes.tsv move.tsv --offer 5040
  python3 move_line.py toll homes.tsv move.tsv
  python3 move_line.py sensitivity homes.tsv move.tsv --offer 5040
  python3 move_line.py validate homes.tsv move.tsv

Exit codes:
  0  report produced（含 ✓忍 / ◐掷币）
  2  usage error / 账本缺失 / 坏行 / 角色非法 / 现居缺失或重复
  3  refusal: 账本是空的 / 搬家税为 ¥0（「搬家是免费的？」）/ compare 无候选
  4  gate: ✗ 挪——涨幅越过忍价线，搬比忍便宜
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import namedtuple
from typing import List, Optional, Tuple

PROG = "move-line"
VERSION = "1.0.0"

TOL = 0.02            # 裁决误差带：涨幅与线相差 ±2.0 个百分点内 = 掷币
DEFAULT_WAGE = 60.0   # 通勤时间估值（元/小时）——参数不是真理，披露进每份报告
DEFAULT_DAYS = 230.0  # 年通勤天数
DEFAULT_YEARS = 3.0   # 预计再住年数（搬家税的摊销期）

RENEW = "RENEW"
TOSS = "TOSS"
MOVE = "MOVE"
VERDICT_LABEL = {RENEW: "✓ 忍", TOSS: "◐ 掷币", MOVE: "✗ 挪"}
VERDICT_MARK = {RENEW: "✓", TOSS: "◐", MOVE: "✗"}

Home = namedtuple("Home", "key name rent commute role note line")
Cost = namedtuple("Cost", "item amount note line")

# 糊涂账护栏：常见搬家成本清单。item 名含任一关键词即视为已记。
CHECKLIST = [
    ("中介费", ("中介",)),
    ("搬家运输", ("搬家", "搬运", "运输", "货拉拉", "面包车")),
    ("家具家电拆装", ("拆装", "家具", "家电", "空调", "安装")),
    ("宽带迁移", ("宽带", "网络", "wifi", "wi-fi", "移机")),
    ("换锁", ("换锁", "锁")),
    ("开荒保洁", ("保洁", "开荒", "清洁")),
    ("误工/请假", ("误工", "请假", "调休")),
    ("起租重叠/双租", ("重叠", "双租", "空置")),
    ("宠物安置", ("宠物", "猫", "狗", "托运")),
    ("修复与押金扣损", ("修复", "押金", "补墙", "打孔", "赔偿")),
]


class LedgerError(Exception):
    """账本打不开或行级坏账，一律 exit 2。"""


# ---------------------------------------------------------------- parsing


def normalize(name: str) -> str:
    """住处/品目名规范化：去首尾空白、小写、内部空白折叠。"""
    return re.sub(r"\s+", " ", name.strip().lower())


def _read_rows(path: str, what: str) -> List[Tuple[int, List[str]]]:
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise LedgerError(f"{what}账本打不开：{path}（{exc}）")
    rows: List[Tuple[int, List[str]]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rows.append((lineno, line.split("\t")))
    return rows


def parse_homes(path: str) -> List[Home]:
    """解析住处账本：name / rent / commute / role [/ note]。

    role ∈ current|candidate；恰好一个 current；名字规范化后不得重复。
    """
    homes: List[Home] = []
    seen = {}
    currents = 0
    for lineno, cols in _read_rows(path, "住处"):
        if len(cols) >= 4 and cols[0].strip().lower() == "name":
            continue  # 表头
        if len(cols) not in (4, 5):
            raise LedgerError(
                f"第 {lineno} 行：需要 4-5 列（name/rent/commute/role[/note]），"
                f"实得 {len(cols)} 列")
        name_s, rent_s, commute_s, role_s = (c.strip() for c in cols[:4])
        note = cols[4].strip() if len(cols) == 5 else ""
        if not name_s:
            raise LedgerError(f"第 {lineno} 行：住处名为空")
        try:
            rent = float(rent_s)
        except ValueError:
            raise LedgerError(f"第 {lineno} 行：月租不是数字：{rent_s!r}")
        if rent <= 0:
            raise LedgerError(f"第 {lineno} 行：月租必须 > 0，实得 {rent_s!r}")
        try:
            commute = float(commute_s)
        except ValueError:
            raise LedgerError(f"第 {lineno} 行：通勤分钟不是数字：{commute_s!r}")
        if commute < 0:
            raise LedgerError(f"第 {lineno} 行：通勤分钟不能为负：{commute_s!r}")
        role = role_s.lower()
        if role not in ("current", "candidate"):
            raise LedgerError(
                f"第 {lineno} 行：role 只允许 current/candidate，实得 {role_s!r}")
        key = normalize(name_s)
        if key in seen:
            raise LedgerError(
                f"第 {lineno} 行：住处「{name_s}」重复记账"
                f"（首次在第 {seen[key]} 行）")
        seen[key] = lineno
        if role == "current":
            currents += 1
        homes.append(Home(key, name_s, rent, commute, role, note, lineno))
    if homes and currents != 1:
        raise LedgerError(
            f"现居必须恰好一个，实得 {currents} 个——"
            f"没有现居就没有「涨」的基准，有两个就没法比")
    return homes


def parse_costs(path: str) -> List[Cost]:
    """解析搬家一次性成本账本：item / amount [/ note]。"""
    costs: List[Cost] = []
    for lineno, cols in _read_rows(path, "搬家成本"):
        if len(cols) >= 2 and cols[0].strip().lower() == "item":
            continue  # 表头
        if len(cols) not in (2, 3):
            raise LedgerError(
                f"第 {lineno} 行：需要 2-3 列（item/amount[/note]），"
                f"实得 {len(cols)} 列")
        item = cols[0].strip()
        amount_s = cols[1].strip()
        note = cols[2].strip() if len(cols) == 3 else ""
        if not item:
            raise LedgerError(f"第 {lineno} 行：成本项名为空")
        try:
            amount = float(amount_s)
        except ValueError:
            raise LedgerError(f"第 {lineno} 行：金额不是数字：{amount_s!r}")
        if amount < 0:
            raise LedgerError(
                f"第 {lineno} 行：金额不能为负（退款就别记了）：{amount_s!r}")
        costs.append(Cost(item, amount, note, lineno))
    return costs


# ---------------------------------------------------------------- math


def commute_tax(commute_min: float, wage: float, days: float) -> float:
    """年通勤税：单程分钟 ×2 × 天数 ÷60 × 时薪。"""
    return commute_min * 2 * days * wage / 60.0


def toll_total(costs: List[Cost]) -> float:
    return sum(c.amount for c in costs)


def toll_year(total: float, years: float) -> float:
    """年搬家税：一次性成本按预计再住年数直线摊销。"""
    return total / years


def annual_total(home: Home, wage: float, days: float,
                 toll_yr: float, mover: bool) -> float:
    """年净成本 = 年房租 + 年通勤税 +（搬家者的）年搬家税。"""
    base = home.rent * 12 + commute_tax(home.commute, wage, days)
    return base + (toll_yr if mover else 0.0)


def cand_line_rent(cand: Home, cur: Home, wage: float, days: float,
                   toll_yr: float) -> float:
    """无差异月租：搬到该候选与留在现居（按此月租续租）打平的租金。"""
    delta_tax = (commute_tax(cand.commute, wage, days)
                 - commute_tax(cur.commute, wage, days))
    return (cand.rent * 12 + delta_tax + toll_yr) / 12.0


def cand_line_pct(cand: Home, cur: Home, wage: float, days: float,
                  toll_yr: float) -> float:
    return cand_line_rent(cand, cur, wage, days, toll_yr) / cur.rent - 1.0


def real_line(homes: List[Home], cur: Home, wage: float, days: float,
              toll_yr: float) -> Optional[Tuple[float, float, str]]:
    """实线 = 最优候选的无差异涨幅；(pct, 月租, 候选名)。无候选 → None。"""
    best = None
    for home in homes:
        if home.role != "candidate":
            continue
        pct = cand_line_pct(home, cur, wage, days, toll_yr)
        if best is None or (pct, home.key) < (best[0], best[2]):
            best = (pct, cand_line_rent(home, cur, wage, days, toll_yr),
                    home.name)
    return best


def blind_line_pct(toll_yr: float, cur: Home) -> float:
    """盲搬线 = 搬家税月摊 ÷ 现租：只量搬家税本身，不量市场。"""
    return (toll_yr / 12.0) / cur.rent


def cap_rent(toll_yr: float, cur: Home) -> float:
    """同等条件替代房源的月租上限。"""
    return cur.rent - toll_yr / 12.0


def decide(pct: float, line: float) -> str:
    """裁决带：差 < −2pp 忍；±2pp 内掷币；> +2pp 挪。"""
    diff = pct - line
    if diff < -TOL:
        return RENEW
    if diff <= TOL:
        return TOSS
    return MOVE


def missing_checklist(costs: List[Cost]) -> List[str]:
    text = " ".join(normalize(c.item) for c in costs)
    out = []
    for label, keywords in CHECKLIST:
        if not any(k in text for k in keywords):
            out.append(label)
    return out


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


def pct_s(p: float) -> str:
    return f"{p * 100:+.1f}%"


def params_line(wage: float, days: float, years: float) -> str:
    return (f"通勤时薪 {yen(wage)}/时 · 年通勤 {days:g} 天 · "
            f"摊销 {years:g} 年 · 裁决带 ±{TOL * 100:.1f} 个点")


# ---------------------------------------------------------------- commands


def _load(args):
    homes = parse_homes(args.homes)
    if not homes:
        return homes, [], None, 0.0
    costs = parse_costs(args.move)
    cur = next(h for h in homes if h.role == "current")
    return homes, costs, cur, toll_total(costs)


def _require_toll(total: float) -> None:
    if total <= 0:
        raise Refusal(
            "搬家税合计 ¥0——搬家是免费的？中介、搬家公司、拆装、保洁"
            "总有一项要花钱：账本拒绝在没有搬家成本的宇宙里裁决"
            "（漏记的搬家税会把忍价线虚压到骗你搬家）")


class Refusal(Exception):
    """账本不足以出报告，exit 3。"""


def cmd_cap(args) -> int:
    homes, costs, cur, total = _load(args)
    if not homes:
        print("住处账本是空的——先抄进现居，再来定线。", file=sys.stderr)
        return 3
    _require_toll(total)
    toll_yr = toll_year(total, args.years)
    line = blind_line_pct(toll_yr, cur)
    n_cand = sum(1 for h in homes if h.role == "candidate")
    print(f"盲搬线 · 还没有候选房源时的第一根标尺 · {params_line(args.wage, args.days, args.years)}")
    print(
        f"  搬家税 {yen(total)} ÷ {args.years:g} 年 = {yen(toll_yr)}/年 = "
        f"{yen(toll_yr / 12)}/月——挪一次窝的月供")
    print(
        f"  同等条件替代房源的月租上限：{yen(cap_rent(toll_yr, cur))}"
        f"（现租 {yen(cur.rent)} − 搬家税月摊 {yen(toll_yr / 12)}）")
    print(
        f"  盲搬线 {pct_s(line)}——涨幅低于此，市场再差也该忍；"
        f"高于此，找到同通勤同品质的房就值得挪")
    if n_cand:
        print(
            f"  在册候选 {n_cand} 个：实线见 judge/compare——"
            f"盲搬线只量搬家税本身，不量市场")
    else:
        print("  在册候选 0 个：盲搬模式。cap 假设你能捡到上限价的同通勤房——"
              "先去看房，把候选抄进账本")
    return 0


def _offer_pct(args, cur: Home) -> float:
    if args.offer is not None and args.pct is not None:
        raise LedgerError("--offer 与 --pct 只给一个")
    if args.offer is not None:
        if args.offer <= 0:
            raise LedgerError(f"报价必须 > 0，实得 {args.offer}")
        return args.offer / cur.rent - 1.0
    if args.pct is None:
        raise LedgerError("需要 --offer 报价（元/月）或 --pct 涨幅（百分点）之一")
    return args.pct / 100.0


def cmd_judge(args) -> int:
    homes, costs, cur, total = _load(args)
    if not homes:
        print("住处账本是空的——没有现居，涨无从谈起。", file=sys.stderr)
        return 3
    _require_toll(total)
    try:
        pct = _offer_pct(args, cur)
    except LedgerError as exc:
        print(f"用法错误：{exc}", file=sys.stderr)
        return 2
    toll_yr = toll_year(total, args.years)
    real = real_line(homes, cur, args.wage, args.days, toll_yr)
    if real is not None:
        line, line_rent, basis_name = real
        basis = (f"实线 {pct_s(line)}（{yen(line_rent)}/月，"
                 f"由最优候选「{basis_name}」钉出）——"
                 f"涨幅超过它，搬就比忍便宜")
        others = [cand_line_pct(h, cur, args.wage, args.days, toll_yr)
                  for h in homes if h.role == "candidate" and h.name != basis_name]
        cand_txt = " · ".join(
            f"{h.name} {pct_s(cand_line_pct(h, cur, args.wage, args.days, toll_yr))}"
            for h in homes if h.role == "candidate")
        print(
            f"裁决 · 现租 {yen(cur.rent)} → 报价 {yen(cur.rent * (1 + pct))}"
            f"（{pct_s(pct)}） · {params_line(args.wage, args.days, args.years)}"
            f" · 搬家税 {yen(total)}")
        print(f"  {basis}")
        print(f"  候选实线：{cand_txt}")
        if line < 0:
            print("  实线为负：现居按 0% 涨已是净最贵——"
                  "谈判目标从「忍不忍」变成「少亏多少」")
    else:
        line = blind_line_pct(toll_yr, cur)
        print(
            f"裁决 · 现租 {yen(cur.rent)} → 报价 {yen(cur.rent * (1 + pct))}"
            f"（{pct_s(pct)}） · {params_line(args.wage, args.days, args.years)}"
            f" · 搬家税 {yen(total)}")
        print(
            f"  盲搬线 {pct_s(line)}（无候选在册：假设能捡到 "
            f"{yen(cap_rent(toll_yr, cur))}/月 的同通勤同品质房）——"
            f"涨幅超过它，搬就比忍便宜")
    verdict = decide(pct, line)
    diff_pts = (pct - line) * 100
    if verdict == MOVE:
        print(
            f"  裁决 {VERDICT_LABEL[MOVE]}——{pct_s(pct)} 越线 "
            f"{diff_pts:.1f} 个点：这份通知的每一个点都在替搬家出资")
        print(
            "  诚实条款：时薪是参数不是真理（--wage）；搬家税靠自报"
            "（漏项见 toll）；挪不挪，人的决定")
        return 4
    if verdict == TOSS:
        print(
            f"  裁决 {VERDICT_LABEL[TOSS]}——{pct_s(pct)} 与线只差 "
            f"{abs(diff_pts):.1f} 个点，落在 ±{TOL * 100:.1f} 个点的误差带里：")
        print(
            "    钱分不出胜负，用非钱因素收尾（采光/邻居/搬家疲劳）——"
            "或者先回答「为什么只打算住这么短」")
        return 0
    print(
        f"  裁决 {VERDICT_LABEL[RENEW]}——{pct_s(pct)} 在线 {pct_s(line)} 之内："
        f"搬家税吃不掉这份涨幅，忍是算术不是软弱")
    return 0


def cmd_compare(args) -> int:
    homes, costs, cur, total = _load(args)
    if not homes:
        print("住处账本是空的——无从对账。", file=sys.stderr)
        return 3
    _require_toll(total)
    cands = [h for h in homes if h.role == "candidate"]
    if not cands:
        print(
            "没有候选房源——compare 无从比起：先去看房，"
            "或用 cap 看盲搬线。", file=sys.stderr)
        return 3
    toll_yr = toll_year(total, args.years)
    if args.offer is not None:
        if args.offer <= 0:
            print(f"报价必须 > 0，实得 {args.offer}", file=sys.stderr)
            return 2
        base_rent = float(args.offer)
        base_note = f"现居按房东报价 {yen(base_rent)}/月"
        offer_pct = base_rent / cur.rent - 1.0
    else:
        base_rent = cur.rent
        base_note = f"现居按当前租 {yen(base_rent)}/月（给 --offer 换基准）"
        offer_pct = 0.0
    base_total = base_rent * 12 + commute_tax(cur.commute, args.wage, args.days)
    cur_old_total = annual_total(cur, args.wage, args.days, toll_yr, mover=False)

    print(
        f"搬家对账单 · 基准：{base_note} · {params_line(args.wage, args.days, args.years)}"
        f" · 搬家税 {yen(total)} → {yen(toll_yr)}/年")
    print()
    print(f"  {pad('#', 3)}{pad('住处', 16)}{padl('月租', 8)}{padl('年净成本', 10)}"
          f"{padl('月均', 8)}{padl('实线', 7)}  vs 基准")
    rows = sorted(cands, key=lambda h: (annual_total(h, args.wage, args.days,
                                                    toll_yr, mover=True), h.name))
    for i, h in enumerate(rows, 1):
        t = annual_total(h, args.wage, args.days, toll_yr, mover=True)
        saving_yr = base_total - t
        line_pct = cand_line_pct(h, cur, args.wage, args.days, toll_yr)
        if saving_yr > 0:
            payback = total / (saving_yr / 12)
            note = (f"省 {yen(saving_yr)}/年 · 回本 {payback:.1f} 个月"
                    f"（预计住 {args.years:g} 年）")
        else:
            note = f"不省反亏 {yen(-saving_yr)}/年 · 永不回本"
        print(f"  {pad(str(i), 3)}{pad(h.name, 16)}{padl(yen(h.rent), 8)}"
              f"{padl(yen(t), 10)}{padl(yen(t / 12), 8)}"
              f"{padl(pct_s(line_pct), 7)}  {note}")
    print(f"  {pad('—', 3)}{pad(cur.name + '·现居', 16)}{padl(yen(cur.rent), 8)}"
          f"{padl(yen(cur_old_total), 10)}{padl(yen(cur_old_total / 12), 8)}"
          f"{padl('—', 7)}  不涨的现居 {yen(cur_old_total)}"
          + (f"——搬家要赢的是涨价后的 {yen(base_total)}" if args.offer else ""))
    print()

    rents = sorted(h.rent for h in cands)
    totals = sorted(annual_total(h, args.wage, args.days, toll_yr, mover=True)
                    for h in cands)
    for h in cands:
        t = annual_total(h, args.wage, args.days, toll_yr, mover=True)
        saving_yr = base_total - t
        if h.rent == rents[0] and t == totals[-1] and len(cands) > 1:
            extra_tax = (commute_tax(h.commute, args.wage, args.days)
                         - commute_tax(cur.commute, args.wage, args.days))
            rent_gap = cur.rent - h.rent
            print(
                f"陷阱灯：{h.name} 月租最低、年净成本最贵——省下的租金 "
                f"{yen(rent_gap)}/月，代价是 {yen(extra_tax)}/年 通勤税"
                f"（多 {h.commute - cur.commute:g} 分钟 ×2 × {args.days:g} 天 × "
                f"{yen(args.wage)}/时）")
        if saving_yr > 0:
            payback = total / (saving_yr / 12)
            if payback > args.years * 12:
                print(
                    f"回本灯：{h.name} 回本 {payback:.1f} 个月 > 预计居住 "
                    f"{args.years:g} 年——住不满一轮，搬家费收不回来")
        elif args.offer:
            print(
                f"回本灯：{h.name} 对这份报价不省反亏——永不回本")
    real = real_line(homes, cur, args.wage, args.days, toll_yr)
    line_txt = pct_s(real[0]) if real else pct_s(blind_line_pct(toll_yr, cur))
    if args.offer:
        print(f"线在 {line_txt}——judge 看这份 {pct_s(offer_pct)} 的裁决")
    else:
        print(f"线在 {line_txt}——judge --offer 查具体报价的裁决")
    return 0


def cmd_toll(args) -> int:
    homes, costs, cur, total = _load(args)
    if not homes:
        print("住处账本是空的——搬家税单没有收件人。", file=sys.stderr)
        return 3
    if not costs:
        print(
            "搬家成本账本是空的——搬家是免费的？总得先记账，再谈裁决。",
            file=sys.stderr)
        return 3
    toll_yr = toll_year(total, args.years)
    print(f"搬家税单 · {len(costs)} 项 · {yen(total)}")
    for c in costs:
        print(f"  {pad(c.item, 22)}{padl(yen(c.amount), 8)}")
    share = toll_yr / 12 / cur.rent
    print(
        f"按再住 {args.years:g} 年摊：{yen(toll_yr)}/年 = {yen(toll_yr / 12)}/月 = "
        f"现租的 {share * 100:.1f}%——挪一次窝的月供")
    missing = missing_checklist(costs)
    if missing:
        print(f"糊涂账护栏：{len(missing)} 类常见成本不在账上——{' · '.join(missing)}")
        print(
            "搬家成本被低估是常态：每漏一项，忍价线就虚低一分，"
            "裁决就偏向一次不明智的忍")
    else:
        print("糊涂账护栏：十类常见成本全部在账——这是少数派，线因此站得住")
    print("（押金可退不算成本——只记拿不回来的部分；起租重叠按多付的日租金记）")
    return 0


def cmd_sensitivity(args) -> int:
    homes, costs, cur, total = _load(args)
    if not homes:
        print("住处账本是空的——矩阵没有行。", file=sys.stderr)
        return 3
    _require_toll(total)
    try:
        wages = [float(x) for x in str(args.wage_list).split(",") if x.strip()]
        years_list = [float(x) for x in str(args.year_list).split(",") if x.strip()]
    except ValueError:
        print("--wage-list / --year-list 需要逗号分隔的数字", file=sys.stderr)
        return 2
    if not wages or not years_list:
        print("--wage-list / --year-list 不能为空", file=sys.stderr)
        return 2
    offer_pct = None
    if args.offer is not None:
        if args.offer <= 0:
            print(f"报价必须 > 0，实得 {args.offer}", file=sys.stderr)
            return 2
        offer_pct = args.offer / cur.rent - 1.0
    elif args.pct is not None:
        offer_pct = args.pct / 100.0

    print(
        f"忍价线敏感性 · 行=再住年数 · 列=通勤时薪 · 每格=越线即挪的最小涨幅"
        + (f"（裁决对照 {pct_s(offer_pct)}）" if offer_pct is not None else ""))
    head = f"  {pad('年数＼时薪', 12)}"
    for w in wages:
        head += padl(f"{yen(w)}/时", 11)
    print(head)
    for y in years_list:
        toll_yr = toll_year(total, y)
        row = f"  {pad(f'{y:g} 年', 12)}"
        for w in wages:
            real = real_line(homes, cur, w, args.days, toll_yr)
            line = real[0] if real else blind_line_pct(toll_yr, cur)
            cell = pct_s(line)
            if offer_pct is not None:
                cell += f" {VERDICT_MARK[decide(offer_pct, line)]}"
            row += padl(cell, 11)
        print(row)
    if offer_pct is not None:
        print(
            "读法：住得越久线越低（搬家税摊薄）；时间越不值钱，远方越便宜——"
            "负线意思是现居按 0% 涨已是净最贵。")
        print(
            f"先回答「住多久」，再回答「忍不忍」：同一份 {pct_s(offer_pct)}，"
            f"在不同格子里是三个不同的裁决。")
    else:
        print("读法：住得越久线越低（搬家税摊薄）；给 --offer 看每格的裁决。")
    return 0


def cmd_validate(args) -> int:
    homes, costs, cur, total = _load(args)
    if not homes:
        print("住处账本是空的。", file=sys.stderr)
        return 3
    cands = [h for h in homes if h.role == "candidate"]
    toll_yr = toll_year(total, args.years) if total > 0 else 0.0
    print(
        f"账本体检 · 住处 {len(homes)} 个（现居 1 · 候选 {len(cands)}） · "
        f"搬家成本 {len(costs)} 项 {yen(total)}")
    print(
        f"  现居：{cur.name} {yen(cur.rent)}/月 · 通勤 {cur.commute:g} 分钟")
    print(f"  口径：{params_line(args.wage, args.days, args.years)}")
    if total <= 0:
        print(
            "  搬家税 ¥0——搬家是免费的？八成是没记：toll/compare/judge "
            "都会拒绝裁决，先抄账")
    else:
        blind = blind_line_pct(toll_yr, cur)
        print(
            f"  盲搬线 {pct_s(blind)}（搬家税 {yen(toll_yr / 12)}/月）"
            + (f" · 实线 {pct_s(real_line(homes, cur, args.wage, args.days, toll_yr)[0])}"
               f"（由 {real_line(homes, cur, args.wage, args.days, toll_yr)[2]} 钉出）"
               if real_line(homes, cur, args.wage, args.days, toll_yr) else
               " · 实线：无候选，盲搬模式"))
    missing = missing_checklist(costs)
    if missing:
        print(f"  糊涂账护栏：{len(missing)} 类常见成本不在账上"
              f"（{' · '.join(missing)}）")
    else:
        print("  糊涂账护栏：十类常见成本全部在账")
    if not cands:
        print("  候选 0 个：judge 走盲搬口径；先去看房，账本会跟着长")
    print("账本只记你抄进来的事实：不抓房源、不预测市场、不替你搬家。")
    return 0


# ---------------------------------------------------------------- cli


def _add_common(p) -> None:
    p.add_argument("homes", help="住处账本 TSV（name/rent/commute/role[/note]）")
    p.add_argument("move", help="搬家一次性成本账本 TSV（item/amount[/note]）")
    p.add_argument("--wage", type=float, default=DEFAULT_WAGE,
                   help="通勤时间估值（元/小时，默认 60）")
    p.add_argument("--days", type=float, default=DEFAULT_DAYS,
                   help="年通勤天数（默认 230）")
    p.add_argument("--years", type=float, default=DEFAULT_YEARS,
                   help="预计再住年数（默认 3）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="挪窝线 —— 续租还是搬家的无差异涨租率")
    parser.add_argument("--version", action="version",
                        version=f"{PROG} {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func, helptext in (
            ("cap", cmd_cap, "盲搬线：搬家税月摊与替代房源租金上限"),
            ("judge", cmd_judge, "裁决涨租通知（✗挪 exit 4）"),
            ("compare", cmd_compare, "候选房源对账单（陷阱灯/回本灯）"),
            ("toll", cmd_toll, "搬家税单 + 糊涂账护栏"),
            ("sensitivity", cmd_sensitivity, "年数×时薪的忍价线矩阵"),
            ("validate", cmd_validate, "账本体检")):
        p = sub.add_parser(name, help=helptext)
        _add_common(p)
        if name == "judge":
            p.add_argument("--offer", type=float, help="房东新报价（元/月）")
            p.add_argument("--pct", type=float, help="涨幅（百分点，如 12）")
        if name == "compare":
            p.add_argument("--offer", type=float,
                           help="以该报价为比较基准（元/月）")
        if name == "sensitivity":
            p.add_argument("--offer", type=float, help="对照报价（元/月）")
            p.add_argument("--pct", type=float, help="对照涨幅（百分点）")
            p.add_argument("--wage-list", default="30,60,120",
                           help="时薪网格（默认 30,60,120）")
            p.add_argument("--year-list", default="1,2,3,5",
                           help="年数网格（默认 1,2,3,5）")
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
        print(f"拒绝裁决：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
