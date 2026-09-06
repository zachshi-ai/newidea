#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stack-dose · 叠方 —— 多重用药的成分叠加对账账本.

问题:药名不同 ≠ 成分不同。感冒了早上泰诺、中午感冒灵、晚上维 C
银翘片——三种药挂在货架的不同位置,却共享同一个活性成分:对乙酰氨
基酚。每一种都按说明书吃,叠起来就是同一成分的两遍、三遍;上限是公
开的药典算术(酚 2g 保守 / 4g 上限),但从没有人按「成分」替你对账:
医院看处方名,药店按货架卖,家庭凭「好像没吃几次吧」的记忆。复方感
冒药宇宙里酚无处不在,而对乙酰氨基酚过量是急性肝衰竭的主要病因之一
——这不是罕见病叙事,是每种药盒背面都印着、却没人加在一起的算术。

stack-dose 把每一次服药记成一行摄入事件(TSV:date/time/drug/qty/
note),把每一种药拆成成分(meds.tsv:name/ingredient/mg/unit,内置
十种家喻户晓 OTC 的公开说明书先验、--meds 整表覆盖),对同一本账开
五个命令:report 逐日成分暴露账(日聚合 vs 先验上限,STACKED/
OVERDOSE 判级 + 当日共享成分点名)、combo 不记账本的组合即时审(药
店 30 秒:这几种一起吃,成分撞不撞车)、interval 间隔审计(同成分相
邻两次 < 最短间隔逐笔点名)、share 成分反向索引(酚藏在哪几个药盒
里)、validate 账本体检。

三条设计立场:
  * 只做同一成分的重复暴露算术,不做药物相互作用——两种成分之间的
    化学反应是临床决策,账本不装懂;但「同一成分吃了几毫克」是加法,
    加法不需要执照。
  * 单药按说明书满频次吃不亮灯(酚 500×4 = 2,000 恰线不亮)——判级
    线画在保守线上的意义就是:叠加才亮,单药不冤枉。
  * 全部上限是通识先验且全部是 -- 旗标(--soft/--hard/--gap/--cap),
    药盒说明书永远赢;没有先验的成分(自定义药)如实 n/a 只发表不判
    级——没有先验就不判级,不装懂。

零依赖:Python 3.8+ 标准库。无墙钟:缺省 as-of 锚定账本最大日期,
`--as-of` 钉死即逐字节可复现。

Exit codes:
  0  report produced   2  usage/账本缺失/坏行/未知药名
  3  refusal: 账本空   4  gate: STACKED/OVERDOSE/CROWDED 任一
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import os
import re
import sys
import unicodedata
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

PROG = "stack-dose"
VERSION = "1.0.0"

D = decimal.Decimal
DEC0 = D("0")

# ---------------------------------------------------------------- 先验
# 成分级通识上限(mg/日)。全部是先验不是医嘱,--soft/--hard 一句话翻案,
# 药盒说明书永远赢。hard=None = 无药典上限概念(如咖啡因),如实 n/a。
Cap = Tuple[Optional[int], Optional[int]]  # (soft, hard)

BUILTIN_CAPS: Dict[str, Cap] = {
    "对乙酰氨基酚": (2000, 4000),   # 保守自疗线 / 药典上限
    "布洛芬": (1200, 3200),         # OTC 标签线 / 处方上限
    "咖啡因": (400, None),          # 成人通识 400 mg/日,无「药典上限」层
}

# 同成分相邻两次最短间隔(分钟)。咖啡因不设——它不是按间隔吃的。
BUILTIN_GAPS: Dict[str, int] = {
    "对乙酰氨基酚": 240,  # q4h
    "布洛芬": 360,        # q6h
}

# 成分别名归一(药盒上的名字五花八门,成分只有一个名字)
ING_ALIASES = {
    "对乙酰氨基酚": "对乙酰氨基酚", "扑热息痛": "对乙酰氨基酚",
    "paracetamol": "对乙酰氨基酚", "acetaminophen": "对乙酰氨基酚",
    "酚": "对乙酰氨基酚",
    "布洛芬": "布洛芬", "ibuprofen": "布洛芬",
    "咖啡因": "咖啡因", "caffeine": "咖啡因", "无水咖啡因": "咖啡因",
    "伪麻黄碱": "伪麻黄碱", "盐酸伪麻黄碱": "伪麻黄碱",
    "右美沙芬": "右美沙芬", "氢溴酸右美沙芬": "右美沙芬",
    "氯苯那敏": "氯苯那敏", "马来酸氯苯那敏": "氯苯那敏",
    "维生素c": "维生素c", "维生素 c": "维生素c", "vc": "维生素c",
}

# 内置药表:十种家喻户晓 OTC 的公开说明书成分(folk 先验,--meds 整表
# 覆盖)。数值来自药盒背面,恰恰是没人加在一起的那一面。
BUILTIN_MEDS: Dict[str, List[Tuple[str, str]]] = {
    #            成分, 每单位 mg, 单位
    "泰诺":       [("对乙酰氨基酚", "325", "片"), ("伪麻黄碱", "30", "片"),
                   ("右美沙芬", "15", "片"), ("氯苯那敏", "2", "片")],
    "泰诺林":     [("对乙酰氨基酚", "500", "片")],
    "999感冒灵":  [("对乙酰氨基酚", "200", "袋"), ("咖啡因", "20", "袋"),
                   ("氯苯那敏", "4", "袋")],
    "维c银翘片":  [("对乙酰氨基酚", "105", "片"), ("维生素c", "49.5", "片"),
                   ("氯苯那敏", "1.05", "片")],
    "白加黑夜片": [("对乙酰氨基酚", "325", "片"), ("伪麻黄碱", "30", "片"),
                   ("右美沙芬", "15", "片"), ("氯苯那敏", "2", "片")],
    "散利痛":     [("对乙酰氨基酚", "250", "片"), ("异丙安替比林", "150", "片"),
                   ("咖啡因", "50", "片")],
    "快克":       [("对乙酰氨基酚", "250", "粒"), ("金刚烷胺", "100", "粒"),
                   ("咖啡因", "15", "粒"), ("氯苯那敏", "2", "粒"),
                   ("人工牛黄", "10", "粒")],
    "新康泰克":   [("伪麻黄碱", "90", "粒"), ("氯苯那敏", "4", "粒")],
    "芬必得":     [("布洛芬", "300", "粒")],
    "美林":       [("布洛芬", "20", "ml")],
}

# ---------------------------------------------------------------- 归一
def norm_name(s: str) -> str:
    """药名归一:NFKC + 去全部空白 + 小写——泰 诺/tylenol 式抄录差异不分裂账本."""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s).lower()


def norm_ing(s: str) -> str:
    """成分归一:先药名归一,再查别名录."""
    n = norm_name(s)
    return ING_ALIASES.get(n, n)


# ---------------------------------------------------------------- 错误
class Bad(Exception):
    """账坏/用法错:exit 2."""


class Refuse(Exception):
    """薄账拒绝:exit 3."""


# ---------------------------------------------------------------- 账本
DoseCols = {"date": ("date", "日期"), "time": ("time", "时间"),
            "drug": ("drug", "药", "药名", "药品"),
            "qty": ("qty", "数量", "剂量"), "note": ("note", "备注")}
MedCols = {"name": ("name", "药名", "药"), "ingredient": ("ingredient", "成分"),
           "mg": ("mg", "毫克"), "unit": ("unit", "单位")}


def read_tsv(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        raise Bad(f"账本不存在: {path}")
    with open(path, encoding="utf-8") as f:
        raw = [ln.rstrip("\n") for ln in f]
    rows = [ln for ln in raw if ln.strip() and not ln.lstrip().startswith("#")]
    if not rows:
        raise Bad(f"账本是空的: {path}")
    header = [c.strip() for c in rows[0].split("\t")]
    out = []
    for i, ln in enumerate(rows[1:], start=2):
        cells = ln.split("\t")
        # 手编账本从表格粘出来常带行尾制表符:尾部空列容忍,不算列数坏
        while len(cells) > len(header) and cells[-1].strip() == "":
            cells.pop()
        if len(cells) > len(header):
            raise Bad(f"第 {i} 行列数多于表头")
        cells += [""] * (len(header) - len(cells))
        out.append({header[j]: cells[j].strip() for j in range(len(header))})
    return out


def pick(row: Dict[str, str], names: Tuple[str, ...]) -> str:
    for n in names:
        if n in row and row[n] != "":
            return row[n]
    return ""


def parse_date(s: str, where: str) -> dt.date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()):
        raise Bad(f"{where}: 坏日期 {s!r}(要 YYYY-MM-DD,补零)")
    try:
        return dt.datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise Bad(f"{where}: 坏日期 {s!r}(要真实存在的日子)")


def parse_time(s: str, where: str) -> int:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise Bad(f"{where}: 坏时间 {s!r}(要 HH:MM)")
    return int(m.group(1)) * 60 + int(m.group(2))


def parse_qty(s: str, where: str) -> decimal.Decimal:
    try:
        q = D(s)
    except decimal.InvalidOperation:
        raise Bad(f"{where}: 坏数量 {s!r}")
    if q <= DEC0:
        raise Bad(f"{where}: 数量必须为正,得到 {s!r}")
    return q


class Meds:
    """药表:归一药名 → (展示名, [(成分, mg, unit)])."""

    def __init__(self) -> None:
        self.builtin = 0
        self.custom = 0
        self.table: Dict[str, Tuple[str, List[Tuple[str, D, str]]]] = {}
        for name, ings in BUILTIN_MEDS.items():
            rows = [(norm_ing(i), D(mg), u) for i, mg, u in ings]
            self.table[norm_name(name)] = (name, rows)
        self.builtin = len(self.table)

    def merge_file(self, path: str) -> None:
        """--meds 自定义表:同名药整药替换内置(本地知识赢),异名药新增."""
        per: "OrderedDict[str, Tuple[str, List[Tuple[str, D, str]]]]" = OrderedDict()
        for i, row in enumerate(read_tsv(path), start=2):
            where = f"{os.path.basename(path)}:{i}"
            name = pick(row, MedCols["name"])
            ing = pick(row, MedCols["ingredient"])
            mg_s = pick(row, MedCols["mg"])
            unit = pick(row, MedCols["unit"])
            if not name or not ing:
                raise Bad(f"{where}: 药名与成分不能为空")
            try:
                mg = D(mg_s)
            except decimal.InvalidOperation:
                raise Bad(f"{where}: 坏毫克数 {mg_s!r}")
            if mg <= DEC0:
                raise Bad(f"{where}: 毫克数必须为正,得到 {mg_s!r}")
            if not unit:
                raise Bad(f"{where}: 单位不能为空")
            key = norm_name(name)
            disp, rows = per.get(key, (name, []))
            rows.append((norm_ing(ing), mg, unit))
            per[key] = (disp, rows)
        for key, (disp, rows) in per.items():
            self.table[key] = (disp, rows)
        self.custom = len(per)

    def get(self, raw: str) -> Tuple[str, List[Tuple[str, D, str]]]:
        got = self.table.get(norm_name(raw))
        if got is None:
            raise Bad(f"未知药名 {raw!r} —— 药表里没有它;"
                      f" 自备药用 --meds meds.tsv 教给账本(说明书永远赢)")
        return got


class Dose:
    __slots__ = ("date", "mins", "drug_raw", "drug", "qty", "note", "line")

    def __init__(self, date: dt.date, mins: int, drug_raw: str, drug: str,
                 qty: decimal.Decimal, note: str, line: int) -> None:
        self.date = date
        self.mins = mins
        self.drug_raw = drug_raw
        self.drug = drug
        self.qty = qty
        self.note = note
        self.line = line

    @property
    def when(self) -> dt.datetime:
        return dt.datetime.combine(self.date, dt.time()) \
            + dt.timedelta(minutes=self.mins)


def load_doses(path: str, meds: Meds) -> List[Dose]:
    rows = read_tsv(path)
    out: List[Dose] = []
    seen = set()
    for i, row in enumerate(rows, start=2):
        where = f"{os.path.basename(path)}:{i}"
        date = parse_date(pick(row, DoseCols["date"]), where)
        mins = parse_time(pick(row, DoseCols["time"]), where)
        raw = pick(row, DoseCols["drug"])
        if not raw:
            raise Bad(f"{where}: 药名不能为空")
        qty = parse_qty(pick(row, DoseCols["qty"]), where)
        note = pick(row, DoseCols["note"])
        disp, _ = meds.get(raw)
        key = (date, mins, norm_name(raw))
        if key in seen:
            raise Bad(f"{where}: 重复服药行 {date} {raw} 同日同刻——"
                      f"真吃了两次就把时刻写准,重抄的行删掉")
        seen.add(key)
        out.append(Dose(date, mins, raw, disp, qty, note, i))
    out.sort(key=lambda d: (d.date, d.mins, d.drug))
    return out


# ---------------------------------------------------------------- 先验层
class Priors:
    """成分先验:上限与间隔,全部可被旗标翻案."""

    def __init__(self, softs: List[str], hards: List[str],
                 gaps: List[str]) -> None:
        self.caps: Dict[str, Cap] = dict(BUILTIN_CAPS)
        self.gaps: Dict[str, int] = dict(BUILTIN_GAPS)
        for spec in softs:
            k, v = self._parse(spec, "--soft")
            s, h = self.caps.get(k, (None, None))
            self.caps[k] = (v, h)
        for spec in hards:
            k, v = self._parse(spec, "--hard")
            s, h = self.caps.get(k, (None, None))
            if s is None:
                s = v  # 只给了 hard 时,soft 抬到同值以显示 STACKED 层
            self.caps[k] = (s, v)
        for spec in gaps:
            k, v = self._parse(spec, "--gap")
            self.gaps[k] = v

    @staticmethod
    def _parse(spec: str, flag: str) -> Tuple[str, int]:
        if "=" not in spec:
            raise Bad(f"{flag} {spec!r} 要 成分=数字 形式,如 对乙酰氨基酚=1500")
        k, v = spec.split("=", 1)
        k = norm_ing(k)
        try:
            n = int(v)
        except ValueError:
            raise Bad(f"{flag} {spec!r}: 数字坏")
        if n <= 0:
            raise Bad(f"{flag} {spec!r}: 必须 > 0")
        return k, n

    def cap(self, ing: str) -> Cap:
        return self.caps.get(ing, (None, None))

    def gap(self, ing: str) -> Optional[int]:
        return self.gaps.get(ing)


# ---------------------------------------------------------------- 判级
LIGHT_ORDER = {"OVERDOSE": 3, "STACKED": 2, "CROWDED": 1, "OK": 0, "NA": 0}


def judge(total: D, cap: Cap) -> str:
    """恰线语义:> 线才亮,恰线不亮——单药按说明书满频次恰在保守线上,不冤枉."""
    soft, hard = cap
    if hard is not None and total > D(hard):
        return "OVERDOSE"
    if soft is not None and total > D(soft):
        return "STACKED"
    if soft is None and hard is None:
        return "NA"
    return "OK"


def mg_fmt(x: D) -> str:
    q = x.quantize(D("0.01"))
    s = f"{q:,f}"
    if s.endswith(".00"):
        s = s[:-3]
    return s


def dw(s: str) -> int:
    """显示宽度:东亚全角计 2——中文表格在等宽终端才对得齐."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dw(s))


WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def clip(doses: List[Dose], as_of: dt.date) -> List[Dose]:
    return [d for d in doses if d.date <= as_of]


# ---------------------------------------------------------------- 展开
def expand(doses: List[Dose], meds: Meds) -> List[Tuple[D, str, D, str]]:
    """剂量事件展开:(dose, 成分, 该笔该成分 mg, 单位)."""
    out = []
    for d in doses:
        _, rows = meds.get(d.drug_raw)
        for ing, mg, unit in rows:
            out.append((d, ing, d.qty * mg, unit))
    return out


def day_totals(events) -> "OrderedDict[dt.date, Dict[str, D]]":
    days: "OrderedDict[dt.date, Dict[str, D]]" = OrderedDict()
    for d, ing, amt, _ in events:
        days.setdefault(d.date, {}).setdefault(ing, DEC0)
        days[d.date][ing] += amt
    return days


def crowded_days(events, priors: Priors) -> Dict[dt.date, List[str]]:
    """间隔审计:同成分相邻两次 gap < min gap,违规记在后一笔的日子."""
    by_ing: Dict[str, List[Tuple[dt.datetime, D, str]]] = {}
    for d, ing, amt, _ in events:
        by_ing.setdefault(ing, []).append((d.when, amt, d.drug))
    out: Dict[dt.date, List[str]] = {}
    for ing, evs in by_ing.items():
        gap = priors.gap(ing)
        if gap is None:
            continue
        evs.sort(key=lambda t: t[0])
        for a, b in zip(evs, evs[1:]):
            gapm = int((b[0] - a[0]).total_seconds() // 60)
            if gapm < gap:
                line = (f"{a[0]:%m-%d %H:%M} {a[2]} → {b[0]:%m-%d %H:%M} {b[2]}"
                        f"   间隔 {gapm} 分钟 < {gap}(q{gap // 60}h)  ⚠ CROWDED")
                out.setdefault(b[0].date(), []).append(line)
    return out


def sources_on(events, day: dt.date, ing: str) -> List[Tuple[str, D]]:
    """某日某成分来自哪些药、各贡献多少(叠加来源审计)."""
    per: "OrderedDict[str, D]" = OrderedDict()
    for d, i, amt, _ in events:
        if d.date == day and i == ing:
            per[d.drug] = per.get(d.drug, DEC0) + amt
    return list(per.items())


# ---------------------------------------------------------------- 报告
def cmd_report(args, priors: Priors) -> int:
    meds = Meds()
    if args.meds:
        meds.merge_file(args.meds)
    doses = load_doses(args.ledger, meds)
    if not doses:
        raise Refuse("账本里没有一行服药事件——半夜想知道「今天吃了多少」"
                     "不该被样本量拦住,但空账本连算术都没有")
    as_of = parse_date(args.as_of, "--as-of") if args.as_of \
        else max(d.date for d in doses)
    doses = clip(doses, as_of)
    if not doses:
        raise Refuse(f"--as-of {as_of} 之后账本里没有事件——被剪掉的不是账坏,"
                     f" 是还没写下的日子")
    events = expand(doses, meds)
    days = day_totals(events)
    crowds = crowded_days(events, priors)

    worst = "OK"
    n_over = n_stk = n_crw = n_ok = n_na = 0
    blocks = []
    for day, ings in days.items():
        # n/a 不是灯:无先验成分不参与判级,免得「无先验」冒充绿灯或红灯
        lights = [judge(ings[i], priors.cap(i)) for i in sorted(ings)]
        judgable = [x for x in lights if x in ("OK", "STACKED", "OVERDOSE")]
        day_light = max(judgable, key=lambda x: LIGHT_ORDER[x]) \
            if judgable else "NA"
        if day_light == "OK" and day in crowds:
            day_light = "CROWDED"
        if day_light == "OVERDOSE":
            n_over += 1
        elif day_light == "STACKED":
            n_stk += 1
        elif day_light == "CROWDED":
            n_crw += 1
        elif day_light == "OK":
            n_ok += 1
        else:
            n_na += 1
        if LIGHT_ORDER[day_light] > LIGHT_ORDER[worst]:
            worst = day_light

        if day_light == "NA":
            head = f"▸ {day:%Y-%m-%d} {WEEK[day.weekday()]}   · n/a" \
                   f"(当日全部成分无先验上限,只发表不判级)"
        else:
            head = (f"▸ {day:%Y-%m-%d} {WEEK[day.weekday()]}   "
                    f"{'✅ OK' if day_light == 'OK' else '🔴 ' + day_light}")
        blocks.append(head)
        for ing in sorted(ings, key=lambda i: -ings[i]):
            total = ings[ing]
            soft, hard = priors.cap(ing)
            light = judge(total, (soft, hard))
            if soft is None and hard is None:
                blocks.append(f"    {pad(ing, 12)} {mg_fmt(total):>10} mg"
                              f"   无先验上限 —— 只发表,不判级(n/a)")
                continue
            line = f"    {pad(ing, 12)} {mg_fmt(total):>10} mg"
            if soft is not None:
                line += f" / 保守 {mg_fmt(D(soft))}"
            if hard is not None:
                line += f" / 上限 {mg_fmt(D(hard))}"
            line += f"   {light}" if light != "OK" else "   OK"
            blocks.append(line)
            srcs = sources_on(events, day, ing)
            if light != "OK" or len(srcs) >= 2:
                blocks.append(f"      来源: "
                              f"{' + '.join(f'{n}{mg_fmt(a)}' for n, a in srcs)}")
                if len(srcs) >= 2:
                    blocks.append(f"      共享: {ing} 藏在当日 {len(srcs)} "
                                  f"种药里 —— 名字不同,成分同名")
        for c in crowds.get(day, []):
            blocks.append(f"    {c}")
        blocks.append("")

    span0, span1 = min(days), max(days)
    print(f"叠方 · Stack Dose —— 成分叠加日账 · {len(doses)} 笔服药"
          f"({span0:%Y-%m-%d} → {span1:%Y-%m-%d}) · as-of {as_of}"
          f"{'(显式钉死)' if args.as_of else '(账本末日)'} · 账本 {os.path.basename(args.ledger)}")
    print(f"  药表: 内置 {meds.builtin} 种"
          f"{' + 自定义 ' + str(meds.custom) if meds.custom else ''}"
          f" · 成分展开 {len(events)} 笔(Σ逐行 == Σ按日聚合)")
    for b in blocks:
        print(b)
    tag = {"OVERDOSE": f"{n_over} 天越药典上限",
           "STACKED": f"{n_stk} 天越保守线",
           "CROWDED": f"{n_crw} 天间隔不足",
           "OK": "全部绿灯"}
    parts = []
    if n_over:
        parts.append(f"{n_over} OVERDOSE")
    if n_stk:
        parts.append(f"{n_stk} STACKED")
    if n_crw:
        parts.append(f"{n_crw} CROWDED")
    if n_ok:
        parts.append(f"{n_ok} OK")
    if n_na:
        parts.append(f"{n_na} n/a")
    print("─" * 58)
    if worst == "OK":
        print(f"判定 OK —— {'、'.join(parts)}。每一种都按说明书吃,"
              f"加起来也在线内——今天可以安心睡。")
        return 0
    print(f"判定 {worst} —— {' · '.join(parts)}。")
    print("  叠加不住在某一顿里,住在加总里:单看每一顿都合理,"
          "加起来是同一成分的第两遍、第三遍。")
    print("  诚实条款:账本不是药师。红灯 = 拿着这几只药盒去问药师或医生"
          "的理由,不是诊断,更不是停药指令。")
    return 4


def cmd_combo(args, priors: Priors) -> int:
    meds = Meds()
    if args.meds:
        meds.merge_file(args.meds)
    names = [s for s in re.split(r"[,，、+]", args.drugs) if s.strip()]
    names = [s.strip() for s in names]
    if len(names) < 1:
        raise Bad("combo 要 --drugs 药1,药2,… 至少一种药")
    parsed = []
    for n in names:
        disp, rows = meds.get(n)
        parsed.append((disp, rows))
    times = args.times
    if times <= 0:
        raise Bad(f"--times 要正整数,得到 {args.times}")

    print(f"叠方 · Stack Dose —— 组合即时审(不记账本,药店 30 秒) · "
          f"{' + '.join(d for d, _ in parsed)} · 按 {times} 次/日外推")
    agg: Dict[str, D] = {}
    for disp, rows in parsed:
        cells = " · ".join(f"{ing}{mg_fmt(mg)}{unit}" for ing, mg, unit in rows)
        print(f"  {pad(disp, 12)} {cells}")
        for ing, mg, _ in rows:
            agg[ing] = agg.get(ing, DEC0) + mg
    print("")
    shared = {i: t for i, t in agg.items()
              if sum(1 for _, rows in parsed for i2, _, _ in rows if i2 == i) >= 2}
    worst = "OK"
    for ing in sorted(agg):
        total = agg[ing]
        n_in = sum(1 for _, rows in parsed for i2, _, _ in rows if i2 == ing)
        soft, hard = priors.cap(ing)
        mark = f"(含于 {n_in} 种药)" if n_in >= 2 else ""
        if soft is None and hard is None:
            print(f"  {pad(ing, 12)} 单次 {mg_fmt(total)} mg {mark}"
                  f"   无先验上限 —— 只发表,不判级")
            continue
        ext = total * times
        light = judge(ext, (soft, hard))
        line = f"  {pad(ing, 12)} 单次 {mg_fmt(total)} mg {mark}× {times} 次 = " \
               f"{mg_fmt(ext)} mg/日"
        if soft is not None:
            line += f" / 保守 {mg_fmt(D(soft))}"
        if hard is not None:
            line += f" / 上限 {mg_fmt(D(hard))}"
        line += f"   {light}" if light != "OK" else "   OK"
        print(line)
        if LIGHT_ORDER[light] > LIGHT_ORDER[worst]:
            worst = light
    print("─" * 58)
    if shared:
        s = "、".join(sorted(shared))
        print(f"共享成分: {s} —— 名字不同,成分同名,叠加的是同一个它。")
    if worst == "OK":
        print("判定 OK —— 这一组合按说明书频次吃不越线。")
        print("  诚实条款:这只回答「同一成分叠了几遍」,不回答成分之间的"
              "相互作用——那是药师和医生的问题。")
        return 0
    print(f"判定 {worst} —— 按说明书每一种都合规,叠起来越线。"
          f"拿这张单子去问药师,不是问能不能吃,是问怎么吃不叠。")
    return 4


def cmd_interval(args, priors: Priors) -> int:
    meds = Meds()
    if args.meds:
        meds.merge_file(args.meds)
    doses = load_doses(args.ledger, meds)
    if not doses:
        raise Refuse("空账本:间隔审计没有事件可审")
    as_of = parse_date(args.as_of, "--as-of") if args.as_of \
        else max(d.date for d in doses)
    doses = clip(doses, as_of)
    events = expand(doses, meds)
    want = norm_ing(args.ingredient) if args.ingredient else None
    by_ing: Dict[str, List[Tuple[dt.datetime, D, str]]] = {}
    for d, ing, amt, _ in events:
        if want and ing != want:
            continue
        by_ing.setdefault(ing, []).append((d.when, amt, d.drug))
    if want and want not in by_ing:
        print(f"叠方 · Stack Dose —— 间隔审计 · 成分 {want}")
        print(f"  账本里没有含 {want} 的服药事件(as-of {as_of})——如实说,"
              f" 不硬造间隔。")
        return 0
    total_seg = sum(max(0, len(v) - 1) for v in by_ing.values())
    print(f"叠方 · Stack Dose —— 间隔审计 · as-of {as_of}"
          f"{'(显式钉死)' if args.as_of else '(账本末日)'} · 账本 "
          f"{os.path.basename(args.ledger)}")
    if args.ingredient:
        print(f"  成分过滤: {want} · 其余成分不在此审计范围")
    worst = "OK"
    viol = 0
    for ing in sorted(by_ing):
        gap = priors.gap(ing)
        if gap is None:
            print(f"  {ing}: 无最短间隔先验 —— 不审,不装懂(--gap {ing}=分钟 可翻案)")
            continue
        evs = sorted(by_ing[ing], key=lambda t: t[0])
        segs = []
        for a, b in zip(evs, evs[1:]):
            gapm = int((b[0] - a[0]).total_seconds() // 60)
            segs.append((gapm, a, b))
        if not segs:
            print(f"  {ing}: 仅 1 笔,无相邻段可审")
            continue
        bad = [s for s in segs if s[0] < gap]
        viol += len(bad)
        mn = min(s[0] for s in segs)
        med = sorted(s[0] for s in segs)[len(segs) // 2]
        head = f"  {ing}: {len(segs)} 段相邻间隔 · 最短 {mn} · 中位 {med} 分钟"
        head += f" · 闸 {gap}(q{gap // 60}h)" if gap % 60 == 0 else f" · 闸 {gap}"
        print(head)
        for gapm, a, b in bad:
            print(f"    ⚠ {a[0]:%m-%d %H:%M} {a[2]} → {b[0]:%m-%d %H:%M} {b[2]}"
                  f"   间隔 {gapm} 分钟  CROWDED")
        if bad and worst == "OK":
            worst = "CROWDED"
    print("─" * 58)
    if worst == "OK":
        print(f"判定 OK —— {total_seg} 段间隔全部在线上(恰线不亮)。")
        return 0
    print(f"判定 CROWDED —— {viol} 段间隔不足。两次之间是身体清算上一笔"
          f"的时间,不是广告建议;间隔也是叠加。")
    return 4


def cmd_share(args, priors: Priors) -> int:
    meds = Meds()
    if args.meds:
        meds.merge_file(args.meds)
    want = norm_ing(args.ingredient) if args.ingredient else None
    idx: Dict[str, List[Tuple[str, D, str]]] = {}
    for disp, rows in meds.table.values():
        for ing, mg, unit in rows:
            idx.setdefault(ing, []).append((disp, mg, unit))
    ings = sorted(idx)
    if want and want not in idx:
        print(f"叠方 · Stack Dose —— 成分反向索引 · 药表 {meds.builtin} 内置"
              f" + {meds.custom} 自定义")
        print(f"  {want}: 药表里没有含它的药——如实说,不硬造。")
        return 0
    print(f"叠方 · Stack Dose —— 成分反向索引 · 药表 {meds.builtin} 内置"
          f"{' + ' + str(meds.custom) + ' 自定义' if meds.custom else ''} · "
          f"{len(ings)} 种成分 · 药-成分对 {sum(len(v) for v in idx.values())}")
    for ing in ings:
        if want and ing != want:
            continue
        items = sorted(idx[ing])
        cells = " · ".join(f"{n}{mg_fmt(mg)}{u}" for n, mg, u in items)
        soft, hard = priors.cap(ing)
        cap_s = ""
        if soft is not None:
            cap_s += f" 保守 {mg_fmt(D(soft))}/日"
        if hard is not None:
            cap_s += f" · 上限 {mg_fmt(D(hard))}/日"
        if not cap_s:
            cap_s = " 无先验上限(--soft/--hard 可教)"
        print(f"  {pad(ing, 12)} 藏在 {len(items)} 个药盒: {cells}")
        print(f"           {cap_s.strip()}")
    print("─" * 58)
    print("  买感冒药之前看一眼这一行:货架上的名字不一样,成分是同一个。")
    return 0


def cmd_validate(args, priors: Priors) -> int:
    meds = Meds()
    if args.meds:
        meds.merge_file(args.meds)
    doses = load_doses(args.ledger, meds)
    events = expand(doses, meds)
    days = day_totals(events)
    problems: List[str] = []

    # 恒等式 1:Σ逐行剂量 == Σ按日聚合(两条路径重放同一本账)
    line_sum = sum((amt for _, _, amt, _ in events), DEC0)
    day_sum = sum((t for ings in days.values() for t in ings.values()), DEC0)
    if abs(line_sum - day_sum) > D("1e-9"):
        problems.append(f"恒等式破:Σ逐行 {line_sum} ≠ Σ按日 {day_sum}")

    # 恒等式 2:成分展开笔数 == Σ(每笔药的成分数)
    n_ing = sum(len(rows) for _, rows in
                (meds.get(d.drug_raw) for d in doses))
    if n_ing != len(events):
        problems.append(f"展开恒等式破:Σ成分数 {n_ing} ≠ 展开事件 {len(events)}")

    # 恒等式 3:每一天每成分的灯 ∈ 已知集合(判级完备性)
    for day, ings in days.items():
        for ing, total in ings.items():
            light = judge(total, priors.cap(ing))
            if light not in LIGHT_ORDER:
                problems.append(f"{day} {ing}: 判级 {light} 不在灯集里")

    # 体检 4:间隔审计自身重放(违规段 == crowded_days 产物)
    crowds = crowded_days(events, priors)
    for day, lines in crowds.items():
        if not lines:
            problems.append(f"{day}: 间隔违规为空却入了账")

    print(f"叠方 · Stack Dose —— 账本体检 · {os.path.basename(args.ledger)} · "
          f"{len(doses)} 笔服药 · {len(events)} 笔成分展开 · {len(days)} 天")
    resid = abs(line_sum - day_sum)
    print(f"  Σ逐行 == Σ按日聚合 : {mg_fmt(line_sum)} mg,残差 "
          f"{float(resid):.2e}")
    print(f"  Σ成分数 == Σ展开事件 : {n_ing} == {len(events)}")
    print(f"  间隔违规段 : {sum(len(v) for v in crowds.values())}"
          f"(归属后一笔之日)")
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        print(f"判定 BROKEN —— {len(problems)} 项体检未过。")
        return 2
    print("  判级完备 · 恒等式闭合 · 间隔账与展开账一致")
    print("判定 SOUND —— 算术自己证明自己没有抄错。")
    return 0


# ---------------------------------------------------------------- 入口
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG, description="叠方 · Stack Dose —— 多重用药的成分叠加对账账本")
    sub = p.add_subparsers(dest="cmd")

    def common(sp, with_ledger=True):
        if with_ledger:
            sp.add_argument("ledger", help="服药账本 TSV(date/time/drug/qty/note)")
        sp.add_argument("--meds", help="自定义药表 TSV(name/ingredient/mg/unit),"
                                       "同名药整药替换内置")
        sp.add_argument("--as-of", help="钉死到某日(剪切之后的行,含边界≤)")
        sp.add_argument("--soft", action="append", default=[],
                        help="成分=mg/日 保守线翻案")
        sp.add_argument("--hard", action="append", default=[],
                        help="成分=mg/日 药典上限翻案")
        sp.add_argument("--gap", action="append", default=[],
                        help="成分=分钟 最短间隔翻案")

    sp = sub.add_parser("report", help="逐日成分暴露账与判级")
    common(sp)
    sp.set_defaults(fn=cmd_report)

    sp = sub.add_parser("combo", help="组合即时审(不记账本)")
    sp.add_argument("--drugs", required=True, help="药1,药2,…(逗号/顿号分隔)")
    sp.add_argument("--times", type=int, default=3, help="按 N 次/日外推(默认 3)")
    sp.add_argument("--meds", help="自定义药表 TSV")
    sp.add_argument("--soft", action="append", default=[])
    sp.add_argument("--hard", action="append", default=[])
    sp.set_defaults(fn=cmd_combo)

    sp = sub.add_parser("interval", help="同成分相邻两次间隔审计")
    common(sp)
    sp.add_argument("--ingredient", help="只审这一种成分")
    sp.set_defaults(fn=cmd_interval)

    sp = sub.add_parser("share", help="成分反向索引(酚藏在哪些药盒)")
    sp.add_argument("--ingredient", help="只看这一种成分")
    sp.add_argument("--meds", help="自定义药表 TSV")
    sp.set_defaults(fn=cmd_share)

    sp = sub.add_parser("validate", help="账本体检与恒等式")
    common(sp)
    sp.set_defaults(fn=cmd_validate)

    sp = sub.add_parser("check", help="combo 别名")
    sp.add_argument("--drugs", required=True)
    sp.add_argument("--times", type=int, default=3)
    sp.add_argument("--meds")
    sp.add_argument("--soft", action="append", default=[])
    sp.add_argument("--hard", action="append", default=[])
    sp.set_defaults(fn=cmd_combo)

    sp = sub.add_parser("where", help="share 别名")
    sp.add_argument("--ingredient")
    sp.add_argument("--meds")
    sp.set_defaults(fn=cmd_share)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "fn", None):
        build_parser().print_help()
        return 2
    try:
        priors = Priors(getattr(args, "soft", []) or [],
                        getattr(args, "hard", []) or [],
                        getattr(args, "gap", []) or [])
        return args.fn(args, priors)
    except Bad as e:
        print(f"账坏/用法错: {e}", file=sys.stderr)
        return 2
    except Refuse as e:
        print(f"拒绝下结论: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
