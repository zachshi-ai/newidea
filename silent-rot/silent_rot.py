#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""暗蛀 · Silent Rot — 口腔治疗史账本

牙是身体里唯一「治疗只做加法」的器官：补过的牙不会变回原牙、根管杀死
的是神经本身、拔掉的就是没有——治疗阶梯（封闭 → 充填 → 根管 → 牙冠 →
拔除 → 种植）价格只升不降，而整段升级路几乎无痛：牙釉质没有神经，
「疼了才去」的直觉恰恰是「到根管了才去」。病历跟着医院走、牙跟着你走，
口腔是每个人身上唯一没有账本的资产。本件把每次口腔事件抄成一行手编
流水（日期/牙位/事件/费用/医嘱），从同一本账开出六本账：

  - report    全口总账：棘轮状态分布、观察挂起名单、五灯判级
              （WATCH-HOLD / SILENT / CARE-GAP / NO-CROWN / NEVER-SEEN）；
  - ratchet   治疗棘轮：每颗在册牙的升级链与累计造价，
              墙上挂「下一级价签牌」——不是预测，是价目表；
  - silent    无痛进展法庭：发现（found）→ 处理的拖延天数、跳级数、
              账面价差；仍在挂起的观察按跑表照示；
  - due       复查日历：洗牙/检查/观察复查/冠随访/种植随访按周期过闸，
              NEVER-SEEN 全口点名；
  - cost      口腔经济：年度分布、KEEP/FIX/REBUILD 瀑布（恒等式）、
              牙位造价排行、缺牙天数；
  - validate  账本体检：棘轮合法性（降级/复活/种植后事件拒绝）、
              恒等式、双算法重放一致。

诚实条款：它是账本不是牙医——价签是通识先验（--price 全覆盖，本地
价格永远赢），不诊断、不预测哪颗牙会坏；账面价差是「价目表 × 已发生
的时间线」，不是「早补就一定省下」的反事实断言；痛苦不定价。
全部本地计算、不连任何接口；as-of 缺省 = 账本最大日期，同一本账任何
机器任何一天逐字节一致。补不补、拔不拔，永远是人的决定。

Exit codes: 0 绿 · 2 账本损坏 · 3 样本太薄拒绝统计判级 · 4 红灯
"""

import argparse
import os
import sys
from datetime import date

EXIT_OK = 0
EXIT_LEDGER = 2
EXIT_DECLINE = 3
EXIT_GATE = 4

TOL = 1e-9

# ---------------------------------------------------------------- events

# 治疗棘轮：等级只升不降（同级重复合法：再充填/根管再治疗/换冠/分期种植）
TREAT_LEVEL = {
    "sealant": 1,
    "fill": 2,
    "rootcanal": 3,
    "crown": 4,
    "extract": 5,
    "implant": 6,
}

STATE_NAME = {
    0: "untracked",
    1: "sealed",
    2: "filled",
    3: "root-canaled",
    4: "crowned",
    5: "missing",
    6: "replaced",
}

# found 是浮动旗标：可在任何等级（<replaced）之后挂出，被治疗事件消化
FLAG_EVENT = "found"

# 全口护理事件：tooth 必须为空（scaling/fluoride），check 可空（全口）可值（单牙复查）
CARE_EVENTS = ("scaling", "check", "fluoride")

# 费用分类
COST_CLASS = {
    "scaling": "KEEP", "check": "KEEP", "fluoride": "KEEP", "found": "KEEP",
    "sealant": "FIX", "fill": "FIX",
    "rootcanal": "REBUILD", "crown": "REBUILD",
    "extract": "REBUILD", "implant": "REBUILD",
}

ALIASES = {
    "found": "found", "watch": "found", "发现": "found", "观察": "found",
    "fill": "fill", "filled": "fill", "补牙": "fill", "充填": "fill",
    "rootcanal": "rootcanal", "rct": "rootcanal", "根管": "rootcanal", "根管治疗": "rootcanal", "杀神经": "rootcanal",
    "crown": "crown", "牙冠": "crown", "戴冠": "crown",
    "extract": "extract", "extraction": "extract", "拔牙": "extract", "拔除": "extract", "拔": "extract",
    "implant": "implant", "种植": "implant", "种牙": "implant", "桥": "implant", "固定桥": "implant",
    "scaling": "scaling", "洗牙": "scaling", "洁治": "scaling", "洁牙": "scaling",
    "check": "check", "检查": "check", "体检": "check", "复查": "check",
    "fluoride": "fluoride", "涂氟": "fluoride", "氟": "fluoride",
    "sealant": "sealant", "窝沟封闭": "sealant", "封闭": "sealant",
}

# 通识价签（元）：阶梯入口与每一级的锚，--price 全覆盖，本地价格永远赢
DEFAULT_PRICEBOOK = {
    "sealant": 300.0,
    "fill": 320.0,
    "rootcanal": 1200.0,
    "crown": 3600.0,
    "extract": 800.0,
    "implant": 12000.0,
    "scaling": 300.0,
    "check": 50.0,
    "fluoride": 200.0,
}

DEFAULTS = dict(
    check_line=730,        # 2 年没有一次专业目光
    watch_line=365,        # 观察挂起超一年
    silent_line=365,       # 发现→处理拖延超一年
    crown_line=180,        # 根管后无冠超半年（牙体脆化易劈裂）
    scaling_interval=365,  # 洗牙周期（通识 6-12 月取 1 年）
    watch_review=90,       # 观察中的牙该有下次目光
    crown_review=365,      # 戴冠第一年随访
    implant_review=365,    # 种植体年检（种植体周围炎）
    due_soon=90,
)


class LedgerError(Exception):
    """账本坏了：语法/引用/棘轮违例，exit 2。"""


class Decline(Exception):
    """样本太薄：统计判级拒答，算术照出，exit 3。"""


class Gate(Exception):
    """门禁红灯：exit 4。"""


# ---------------------------------------------------------------- TSV

def read_tsv(path):
    if not os.path.exists(path):
        raise LedgerError("missing file: %s" % os.path.basename(path))
    rows = []
    header = None
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                continue
            cols = line.split("\t")
            if header is None:
                header = [c.strip().lower() for c in cols]
                continue
            if len(cols) != len(header):
                raise LedgerError(
                    "ledger line %d: expected %d columns, got %d"
                    % (lineno, len(header), len(cols)))
            row = dict(zip(header, [c.strip() for c in cols]))
            row["_line"] = lineno
            rows.append(row)
    if header is None:
        raise LedgerError("empty ledger (no header row)")
    return rows


def parse_date(val, lineno):
    try:
        parts = val.split("-")
        if len(parts) != 3:
            raise ValueError
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise LedgerError("ledger line %d: bad date %r (want YYYY-MM-DD)"
                          % (lineno, val))


def parse_cost(val, lineno):
    if val == "":
        return 0.0
    try:
        num = float(val)
    except ValueError:
        raise LedgerError("ledger line %d: bad cost %r" % (lineno, val))
    if num < 0:
        raise LedgerError("ledger line %d: cost must be >= 0, got %s"
                          % (lineno, val))
    return num


def normalize_tooth(val, lineno):
    """FDI 记法：恒牙 11-48（象限1-4 × 位1-8），乳牙 51-85（象限5-8 × 位1-5）。"""
    if val == "":
        return ""
    if not val.isdigit() or len(val) != 2:
        raise LedgerError("ledger line %d: bad tooth %r (want FDI like 16/36/54)"
                          % (lineno, val))
    quad, pos = int(val[0]), int(val[1])
    permanent = 1 <= quad <= 4 and 1 <= pos <= 8
    deciduous = 5 <= quad <= 8 and 1 <= pos <= 5
    if not (permanent or deciduous):
        raise LedgerError("ledger line %d: bad tooth %r (FDI 11-48 permanent, 51-85 deciduous)"
                          % (lineno, val))
    return val


def normalize_event(val, lineno):
    ev = ALIASES.get(val.strip().lower())
    if ev is None:
        raise LedgerError("ledger line %d: unknown event %r" % (lineno, val))
    return ev


def validate_event_scope(ev, tooth, lineno):
    needs_tooth = ev in TREAT_LEVEL or ev == FLAG_EVENT
    if needs_tooth and tooth == "":
        raise LedgerError("ledger line %d: event %s needs a tooth (FDI)"
                          % (lineno, ev))
    if ev in ("scaling", "fluoride") and tooth != "":
        raise LedgerError("ledger line %d: event %s is full-mouth, tooth must be empty"
                          % (lineno, ev))


# ---------------------------------------------------------------- replay

class Tooth(object):
    __slots__ = ("tooth", "level", "watch_since", "treat_count",
                 "extract_done", "total_cost", "events", "last_treat")

    def __init__(self, tooth):
        self.tooth = tooth
        self.level = 0
        self.watch_since = None     # 最近一次 found 日期（挂起观察）
        self.treat_count = 0
        self.extract_done = False
        self.total_cost = 0.0
        self.events = []            # (date, event, cost, note, lineno)
        self.last_treat = None

    @property
    def watch_open(self):
        return self.watch_since is not None

    @property
    def state(self):
        return STATE_NAME[self.level]

    def chain(self):
        parts = []
        for d, ev, _c, _n, _ln in self.events:
            parts.append("%s %s" % (d.isoformat(), ev))
        return " -> ".join(parts) if parts else "-"


def replay(rows, as_of, as_of_explicit):
    """按时间序（同日按行序）重放整本账，返回 (teeth, care) 。

    双算法恒等：全序游走（此处）与按牙分组重放（validate 用）必须一致。
    """
    teeth = {}
    care = {"scaling": [], "check": [], "fluoride": [], "all": []}
    total_cost = 0.0
    for row in sorted(rows, key=lambda r: (r["_date"], r["_line"])):
        d, ev, tooth = row["_date"], row["_event"], row["_tooth"]
        cost = row["_cost"]
        total_cost += cost
        if ev in CARE_EVENTS:
            # 单牙复查同样是专业目光：计入护理覆盖
            care[ev].append(d)
            care["all"].append(d)
        if tooth:
            t = teeth.setdefault(tooth, Tooth(tooth))
            t.events.append((d, ev, cost, row.get("note", ""), row["_line"]))
            t.total_cost += cost
            if ev in CARE_EVENTS:
                continue    # 单牙复查：记费用与就医史，不进状态机
            if ev == FLAG_EVENT:
                # 种植体不蛀牙：replaced 后的观察是账本错误
                if t.level >= TREAT_LEVEL["implant"]:
                    raise LedgerError(
                        "ledger line %d: tooth %s is replaced; no caries to watch"
                        % (row["_line"], tooth))
                t.watch_since = d
            else:
                lvl = TREAT_LEVEL[ev]
                if ev == "extract" and t.extract_done:
                    raise LedgerError(
                        "ledger line %d: tooth %s extracted twice"
                        % (row["_line"], tooth))
                if t.level >= TREAT_LEVEL["implant"]:
                    # 种植体不蛀牙：只允许追加手术（分期/返工），其余不存在
                    if ev != "implant":
                        raise LedgerError(
                            "ledger line %d: ratchet violation: tooth %s is %s, "
                            "no treatment exists on a replaced tooth"
                            % (row["_line"], tooth, t.state))
                if lvl < t.level - TOL:
                    raise LedgerError(
                        "ledger line %d: ratchet violation: %s on tooth %s "
                        "(now %s) — treatment only goes up"
                        % (row["_line"], ev, tooth, t.state))
                t.level = max(t.level, lvl)
                t.treat_count += 1
                t.last_treat = d
                if ev == "extract":
                    t.extract_done = True
                # 治疗事件消化挂起的观察
                if t.watch_since is not None and lvl >= TOL:
                    t.watch_since = None
        else:
            if ev in TREAT_LEVEL or ev == FLAG_EVENT:
                raise LedgerError(
                    "ledger line %d: event %s needs a tooth (FDI)"
                    % (row["_line"], ev))
    return teeth, care, total_cost


def replay_grouped(rows):
    """按牙分组的第二算法（validate 双算法核对用）。"""
    teeth = {}
    for row in sorted(rows, key=lambda r: (r["_date"], r["_line"])):
        tooth = row["_tooth"]
        if not tooth:
            continue
        teeth.setdefault(tooth, []).append(row)
    return teeth


def load_ledger(path, as_of, as_of_explicit):
    rows = read_tsv(path)
    if not rows:
        raise LedgerError("ledger has header but no event rows")
    out = []
    for row in rows:
        row["_date"] = parse_date(row.get("date", ""), row["_line"])
        row["_cost"] = parse_cost(row.get("cost", ""), row["_line"])
        row["_tooth"] = normalize_tooth(row.get("tooth", ""), row["_line"])
        row["_event"] = normalize_event(row.get("event", ""), row["_line"])
        validate_event_scope(row["_event"], row["_tooth"], row["_line"])
        out.append(row)
    if as_of_explicit:
        # 回放语义：as-of 是时间机器——它之后的事件还没发生，
        # 不进重放、不进费用（钉回 2022 年就看见 2022 年的嘴）
        out = [r for r in out if r["_date"] <= as_of]
        if not out:
            raise LedgerError("no rows at or before as-of %s"
                              % as_of.isoformat())
    max_date = max(r["_date"] for r in out)
    teeth, care, total_cost = replay(out, as_of, as_of_explicit)
    return out, teeth, care, total_cost, max_date


# ---------------------------------------------------------------- helpers

def display_width(text):
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def pad(text, width):
    gap = width - display_width(text)
    return text + " " * max(0, gap)


def money(x):
    return "¥%s" % format(round(x + 0.0, 2), ",.2f")


def days_between(a, b):
    return (b - a).days


def opt_date(d):
    return d.isoformat() if d else "-"


def price_of(pricebook, ev):
    return pricebook.get(ev, 0.0)


def next_rung_price(tooth, pricebook):
    """价签牌：当前等级的下一级要多少钱（不是预测，是价目表）。"""
    ladder = [0, 1, 2, 3, 4, 5, 6]
    if tooth.level >= 6:
        return None
    nxt = [lv for lv in ladder if lv > tooth.level]
    if not nxt:
        return None
    target = nxt[0]
    ev = {1: "sealant", 2: "fill", 3: "rootcanal",
          4: "crown", 5: "extract", 6: "implant"}[target]
    if target == 6 and tooth.level < 5:
        # 活牙直接走到种植不存在，缺牙才种植：价签给拔除+种植
        return pricebook.get("extract", 0) + pricebook.get("implant", 0)
    return pricebook.get(ev, 0)


def closed_loops(teeth, pricebook):
    """found → 处理 的闭环清单：拖延天数、跨级数、账面价差。"""
    loops = []
    for tooth in teeth.values():
        found_at = None
        base_level = 0
        for d, ev, cost, note, lineno in tooth.events:
            if ev == FLAG_EVENT:
                found_at = d
                base_level = tooth_level_before(tooth, d)
                continue
            if found_at is None:
                continue
            lvl = TREAT_LEVEL[ev]
            gap_days = days_between(found_at, d)
            if ev == "extract":
                price_gap = None   # 拔除是终点不是升级：价差语义不适用
            else:
                # 处理总价 = found 之后该牙全部治疗费用（根管后的冠是
                # 一套：处理链不闭环在中间级），含后续完成事件
                spent = sum(c for dd, e, c, n, l in tooth.events
                            if dd >= found_at and e in TREAT_LEVEL)
                price_gap = spent - price_of(pricebook, "fill")
            loops.append({
                "tooth": tooth.tooth, "found": found_at, "treated": d,
                "event": ev, "days": gap_days, "base_level": base_level,
                "level": lvl, "gap": price_gap,
            })
            found_at = None
    loops.sort(key=lambda x: (-x["days"], x["tooth"]))
    return loops


def tooth_level_before(tooth, d):
    lvl = 0
    for dd, ev, c, n, l in tooth.events:
        if dd >= d:
            break
        if ev in TREAT_LEVEL:
            lvl = max(lvl, TREAT_LEVEL[ev])
    return lvl


def pending_watches(teeth, as_of):
    pend = []
    for tooth in teeth.values():
        if tooth.watch_open:
            pend.append((tooth.tooth, tooth.watch_since,
                         days_between(tooth.watch_since, as_of)))
    pend.sort(key=lambda x: (-x[2], x[0]))
    return pend


def care_gaps(care, as_of, first_date):
    """护理覆盖（scaling∪check∪fluoride）上的空白审计。"""
    dates = sorted(set(care["all"]))
    gaps = []
    if dates:
        anchor = dates[0]
        if first_date < anchor:
            gaps.append((first_date, anchor,
                         days_between(first_date, anchor)))
        for prev, nxt in zip(dates, dates[1:]):
            gaps.append((prev, nxt, days_between(prev, nxt)))
        if dates[-1] < as_of:
            gaps.append((dates[-1], as_of, days_between(dates[-1], as_of)))
    else:
        gaps.append((first_date, as_of, days_between(first_date, as_of)))
    return gaps


def fmt_gap_price(gap):
    if gap is None:
        return "—"
    sign = "+" if gap > 0 else ("" if abs(gap) < TOL else "-")
    return "%s%s" % (sign, format(abs(gap), ",.0f"))


# ---------------------------------------------------------------- report

LIGHTS = ("WATCH-HOLD", "SILENT", "CARE-GAP", "NO-CROWN", "NEVER-SEEN")


def cmd_report(args, rows, teeth, care, total_cost, as_of, pricebook):
    lines = []
    lamps = []
    first_date = min(r["_date"] for r in rows)
    pend = pending_watches(teeth, as_of)
    loops = closed_loops(teeth, pricebook)
    gaps = care_gaps(care, as_of, first_date)

    in_mouth = [t for t in teeth.values() if t.level < TREAT_LEVEL["extract"]]
    gone = [t for t in teeth.values() if t.level >= TREAT_LEVEL["extract"]]
    dist = {}
    for t in teeth.values():
        dist[t.state] = dist.get(t.state, 0) + 1

    lines.append("== 暗蛀 · Silent Rot 全口总账 (as-of %s) ==" % as_of.isoformat())
    lines.append("在册牙 %d 颗 · 事件 %d 行 · 全史投入 %s" %
                 (len(teeth), len(rows), money(total_cost)))
    dist_str = " · ".join("%s %d" % (k, v)
                          for k, v in sorted(dist.items(),
                                             key=lambda kv: -kv[1]))
    lines.append("棘轮分布: %s" % (dist_str if dist else "无牙位记录"))
    lines.append("")

    lines.append("-- 观察挂起（found 之后人没有再出现）--")
    if pend:
        for tooth, since, hold in pend:
            mark = " ⚑超线" if hold > args.watch_line else ""
            lines.append("  %s  since %s  挂起 %d 天%s"
                         % (tooth, since.isoformat(), hold, mark))
            if hold > args.watch_line:
                lamps.append("WATCH-HOLD")
    else:
        lines.append("  无挂起观察")
    lines.append("")

    lines.append("-- 无痛进展闭环（发现 → 处理）--")
    if loops:
        for lp in loops:
            mark = " ⚑超线" if lp["days"] > args.silent_line else ""
            gap_s = ("价差 %s" % fmt_gap_price(lp["gap"])
                     if lp["gap"] is not None else "价差 —(拔除是终点)")
            skip_s = ("跨级 +%d" % (lp["level"] - lp["base_level"])
                      if lp["level"] - lp["base_level"] > 1 else "逐级")
            lines.append("  %s  %s → %s(%s)  拖延 %d 天  %s  %s%s"
                         % (lp["tooth"], lp["found"].isoformat(),
                            lp["treated"].isoformat(), lp["event"],
                            lp["days"], skip_s, gap_s, mark))
            if lp["days"] > args.silent_line:
                lamps.append("SILENT")
    else:
        lines.append("  无闭环")
    lines.append("")

    lines.append("-- 护理覆盖空白（scaling/check/fluoride）--")
    if care["all"]:
        lines.append("  护理事件 %d 次：最近 %s（距今 %d 天）" %
                     (len(care["all"]), max(care["all"]).isoformat(),
                      days_between(max(care["all"]), as_of)))
        for a, b, gap in gaps:
            if gap > args.check_line:
                lines.append("  ⚑ CARE-GAP  %s → %s  空白 %d 天"
                             % (a.isoformat(), b.isoformat(), gap))
                lamps.append("CARE-GAP")
    else:
        lines.append("  ⚑ NEVER-SEEN  全史无任何护理记录")
        lamps.append("NEVER-SEEN")
    lines.append("")

    lines.append("-- 根管后无冠随访 --")
    no_crown = []
    for t in teeth.values():
        rcs = [d for d, ev, c, n, ln in t.events if ev == "rootcanal"]
        if not rcs:
            continue
        last_rc = max(rcs)
        crowns_after = [d for d, ev, c, n, ln in t.events
                        if ev == "crown" and d > last_rc]
        if not crowns_after:
            wait = days_between(last_rc, as_of)
            if wait > args.crown_line:
                no_crown.append((t.tooth, last_rc, wait))
    if no_crown:
        for tooth, rc, wait in sorted(set(no_crown)):
            lines.append("  ⚑ NO-CROWN  %s  根管 %s 后 %d 天无冠"
                         "（牙体脆化易劈裂，劈了就是拔+种）"
                         % (tooth, rc.isoformat(), wait))
            lamps.append("NO-CROWN")
    else:
        lines.append("  无无冠根管牙")
    lines.append("")

    lamps = [l for l in lamps if l in LIGHTS]
    uniq = sorted(set(lamps))
    lines.append("-- 判级 --")
    if uniq:
        for l in uniq:
            lines.append("  ⚑ %s" % l)
        lines.append("灯 %d 盏：%s" %
                     (len(uniq), " / ".join(uniq)))
        follow = followup_debts(teeth, care, as_of, args)
        lines.append("随访欠账 %d 条（明细见 due）" % len(follow))
        raise Gate("\n".join(lines))
    lines.append("  全绿：无挂起超线观察、无超线拖延、无护理空白、无无冠根管")
    print("\n".join(lines))
    return EXIT_OK


def _later_event(events, after, ev):
    for d, e, c, n, ln in events:
        if e == ev and d > after:
            return d
    return None


def followup_debts(teeth, care, as_of, args):
    """due 口径的 OVERDUE 清单（report 只报数）。"""
    debts = []
    if care["scaling"]:
        due = max(care["scaling"]).toordinal() + args.scaling_interval
        if date.fromordinal(due) < as_of:
            debts.append("scaling")
    if care["check"]:
        due = max(care["check"]).toordinal() + args.check_line
        if date.fromordinal(due) < as_of:
            debts.append("check")
    for t in teeth.values():
        if t.watch_open:
            due = t.watch_since.toordinal() + args.watch_review
            if date.fromordinal(due) < as_of:
                debts.append("watch " + t.tooth)
        if t.level == 4 and t.last_treat:
            due = t.last_treat.toordinal() + args.crown_review
            if date.fromordinal(due) < as_of:
                debts.append("crown " + t.tooth)
        if t.level == 6 and t.last_treat:
            due = t.last_treat.toordinal() + args.implant_review
            if date.fromordinal(due) < as_of:
                debts.append("implant " + t.tooth)
    return debts


# ---------------------------------------------------------------- ratchet

def cmd_ratchet(args, rows, teeth, care, total_cost, as_of, pricebook):
    lines = []
    lines.append("== 治疗棘轮 (as-of %s) ==" % as_of.isoformat())
    lines.append("牙  等级           状态          累计造价      链")
    ordered = sorted(teeth.values(),
                     key=lambda t: (-t.level, -t.total_cost, t.tooth))
    for t in ordered:
        next_price = next_rung_price(t, pricebook)
        flag = " ⚑挂起" if t.watch_open else ""
        nxt = ("下一级价签 %s" % money(next_price)
               if next_price is not None else "终末级（无下一级）")
        lines.append("%s  %-2d %-12s  %-12s  %s%s" %
                     (t.tooth, t.level, t.state, money(t.total_cost),
                      nxt, flag))
        lines.append("    链: %s" % t.chain())
    lines.append("")
    lines.append("-- 价签牌（通识先验，--price 覆盖，本地价格永远赢）--")
    lines.append("  阶梯入口(充填) %s · 根管 %s · 牙冠 %s · 拔除 %s · 种植 %s" %
                 (money(pricebook["fill"]), money(pricebook["rootcanal"]),
                  money(pricebook["crown"]), money(pricebook["extract"]),
                  money(pricebook["implant"])))
    rebuild = sum(c for r in rows
                  if COST_CLASS.get(r["_event"]) == "REBUILD"
                  for c in [r["_cost"]])
    lines.append("全史重建类投入 %s —— 已锁定的不可逆总量" % money(rebuild))
    lines.append("价签牌是价目表不是预测：它不诊断哪颗牙会坏，"
                 "它把每一级的价签挂在墙上。")
    print("\n".join(lines))
    return EXIT_OK


# ---------------------------------------------------------------- silent

def cmd_silent(args, rows, teeth, care, total_cost, as_of, pricebook):
    loops = closed_loops(teeth, pricebook)
    pend = pending_watches(teeth, as_of)
    lines = []
    lines.append("== 无痛进展法庭 (as-of %s) ==" % as_of.isoformat())
    lines.append("")
    lines.append("-- 闭环：发现 → 处理 --")
    if loops:
        for lp in loops:
            span = lp["level"] - lp["base_level"]
            gap_s = fmt_gap_price(lp["gap"])
            lines.append(
                "  %s  %s 发现 → %s %s  拖延 %d 天  跨级+%d  账面价差 %s" %
                (lp["tooth"], lp["found"].isoformat(),
                 lp["treated"].isoformat(), lp["event"], lp["days"],
                 span, gap_s))
            if lp["gap"] is not None:
                lines.append(
                    "      （发现级处理价签 %s vs 实际 %s——"
                    "价目表×已发生的时间线，不是反事实断言）" %
                    (money(pricebook["fill"]),
                     money(pricebook["fill"] + lp["gap"])))
            else:
                lines.append("      （拔除是终点不是升级：当时就是拔的指征，"
                             "拖延的代价记在发作与误工里，账单看不见）")
    else:
        lines.append("  无闭环")
    lines.append("")
    lines.append("-- 挂起：还在跑的表 --")
    for tooth, since, hold in pend:
        lines.append("  %s  since %s  已挂 %d 天" %
                     (tooth, since.isoformat(), hold))
    lines.append("")
    red = [lp for lp in loops if lp["days"] > args.silent_line]
    if len(loops) < 2:
        if red:
            for lp in red:
                print("  ⚑ SILENT  %s 拖延 %d 天（> %d）"
                      % (lp["tooth"], lp["days"], args.silent_line))
        print("\n".join(lines))
        print("THIN: 闭环 %d 条——一条拖延是轶事，统计判级拒答（灯与逐条账照出）"
              % len(loops))
        if red:
            raise Gate("")
        return EXIT_DECLINE
    days = sorted(lp["days"] for lp in loops)
    med = days[len(days) // 2] if len(days) % 2 else (days[len(days)//2 - 1]
                                                     + days[len(days)//2]) / 2
    lines.append("-- 统计（%d 条闭环）--" % len(loops))
    lines.append("  拖延中位 %.0f 天 · 最长 %d 天 · 合计 %d 天" %
                 (med, max(days), sum(days)))
    print("\n".join(lines))
    if red:
        for lp in red:
            print("  ⚑ SILENT  %s 拖延 %d 天（> %d）"
                  % (lp["tooth"], lp["days"], args.silent_line))
        raise Gate("")
    return EXIT_OK


# ---------------------------------------------------------------- due

def due_items(teeth, care, as_of, args):
    items = []
    if care["scaling"]:
        last = max(care["scaling"])
        due = date.fromordinal(last.toordinal() + args.scaling_interval)
        items.append(("scaling 洗牙", "-", last, due,
                      args.scaling_interval))
    if care["check"]:
        last = max(care["check"])
        due = date.fromordinal(last.toordinal() + args.check_line)
        items.append(("check 口腔检查", "-", last, due, args.check_line))
    for t in sorted(teeth.values(), key=lambda x: x.tooth):
        if t.watch_open:
            due = date.fromordinal(t.watch_since.toordinal()
                                   + args.watch_review)
            items.append(("watch %s 观察复查" % t.tooth, t.tooth,
                          t.watch_since, due, args.watch_review))
        if t.level == 4 and t.last_treat:
            due = date.fromordinal(t.last_treat.toordinal()
                                   + args.crown_review)
            items.append(("crown %s 冠随访" % t.tooth, t.tooth,
                          t.last_treat, due, args.crown_review))
        if t.level == 6 and t.last_treat:
            due = date.fromordinal(t.last_treat.toordinal()
                                   + args.implant_review)
            items.append(("implant %s 种植年检" % t.tooth, t.tooth,
                          t.last_treat, due, args.implant_review))
        for d, ev, c, n, ln in t.events:
            if ev == "rootcanal":
                crown_after = _later_event(t.events, d, "crown")
                if crown_after is None:
                    due = date.fromordinal(d.toordinal() + args.crown_line)
                    items.append(("NO-CROWN %s 根管后冠修复" % t.tooth,
                                  t.tooth, d, due, args.crown_line))
    items.sort(key=lambda x: x[3])
    return items


def classify_due(due, as_of, due_soon):
    delta = days_between(as_of, due)
    if delta < 0:
        return "OVERDUE", -delta
    if delta == 0:
        return "DUE-TODAY", 0
    if delta <= due_soon:
        return "DUE-SOON", delta
    return "OK", delta


def cmd_due(args, rows, teeth, care, total_cost, as_of, pricebook):
    lines = []
    lines.append("== 复查日历 (as-of %s) ==" % as_of.isoformat())
    if not care["scaling"]:
        lines.append("  ⚑ NEVER-SEEN  全史无洗牙记录（没有记录不等于没洗过，"
                     "但等于没法管）")
    if not care["check"]:
        lines.append("  ⚑ NEVER-SEEN  全史无口腔检查记录")
    overdue = 0
    items = due_items(teeth, care, as_of, args)
    for name, tooth, anchor, due, _iv in items:
        status, delta = classify_due(due, as_of, args.due_soon)
        mark = {"OVERDUE": " ⚑", "DUE-TODAY": " ⚑"}.get(status, "")
        if status == "OVERDUE":
            overdue += 1
            lines.append("  %s  锚 %s  到期 %s  逾期 %d 天%s" %
                         (pad(name, 26), anchor.isoformat(), due.isoformat(),
                          delta, mark))
        elif status == "DUE-TODAY":
            overdue += 1
            lines.append("  %s  锚 %s  到期 %s  今天到期%s" %
                         (pad(name, 26), anchor.isoformat(), due.isoformat(),
                          mark))
        else:
            lines.append("  %s  锚 %s  到期 %s  还剩 %d 天  %s" %
                         (pad(name, 26), anchor.isoformat(), due.isoformat(),
                          delta, status))
    if not items:
        lines.append("  无任何周期项（账本里没有护理与随访锚点）")
    print("\n".join(lines))
    if overdue:
        raise Gate("")
    return EXIT_OK


# ---------------------------------------------------------------- cost

def cmd_cost(args, rows, teeth, care, total_cost, as_of, pricebook):
    lines = []
    lines.append("== 口腔经济 (as-of %s) ==" % as_of.isoformat())
    by_year = {}
    for r in rows:
        by_year.setdefault(r["_date"].year, 0.0)
        by_year[r["_date"].year] += r["_cost"]
    lines.append("-- 年度分布 --")
    for y in sorted(by_year):
        if by_year[y] > 0:
            lines.append("  %d  %s" % (y, money(by_year[y])))
    cls = {"KEEP": 0.0, "FIX": 0.0, "REBUILD": 0.0}
    for r in rows:
        k = COST_CLASS.get(r["_event"])
        if k:
            cls[k] += r["_cost"]
    lines.append("-- 分类瀑布 --")
    for k in ("KEEP", "FIX", "REBUILD"):
        lines.append("  %-8s %s" % (k, money(cls[k])))
    assert abs(sum(cls.values()) - total_cost) < TOL
    keep_fix = cls["KEEP"] + cls["FIX"]
    lines.append("恒等式 KEEP+FIX+REBUILD = 总额 %s ✓" % money(total_cost))
    if keep_fix > 0:
        lines.append("重建倍数 REBUILD ÷ (KEEP+FIX) = %.2fx —— "
                     "为「修回来」付的钱是「不让它坏」的 %.1f 倍" %
                     (cls["REBUILD"] / keep_fix,
                      cls["REBUILD"] / keep_fix))
    lines.append("")
    lines.append("-- 牙位造价排行 --")
    ranked = sorted(teeth.values(), key=lambda t: (-t.total_cost, t.tooth))
    for t in ranked:
        if t.total_cost <= 0:
            continue
        lines.append("  %s  %s  %s" %
                     (pad(t.tooth, 4), pad(money(t.total_cost), 12),
                      t.state))
    lines.append("")
    lines.append("-- 缺牙缺席账（拔除 → 替代重建之间的无牙天数）--")
    any_gap = False
    for t in ranked:
        ex = [d for d, ev, c, n, ln in t.events if ev == "extract"]
        im = [d for d, ev, c, n, ln in t.events if ev == "implant"]
        if ex:
            end = min(im) if im else as_of
            gap = days_between(max(ex), end)
            status = "已重建" if im else "至今缺席"
            lines.append("  %s  无牙 %d 天（%.1f 年）%s" %
                         (t.tooth, gap, gap / 365.25, status))
            any_gap = True
    if not any_gap:
        lines.append("  无拔除记录")
    print("\n".join(lines))
    return EXIT_OK


# ---------------------------------------------------------------- validate

def cmd_validate(args, rows, teeth, care, total_cost, as_of, pricebook):
    problems = []
    total_rows_cost = sum(r["_cost"] for r in rows)
    if abs(total_rows_cost - total_cost) > TOL:
        problems.append("cost identity broken")
    cls = {"KEEP": 0.0, "FIX": 0.0, "REBUILD": 0.0}
    for r in rows:
        k = COST_CLASS.get(r["_event"])
        if k:
            cls[k] += r["_cost"]
    if abs(sum(cls.values()) - total_cost) > TOL:
        problems.append("class waterfall identity broken")
    teeth_cost = sum(t.total_cost for t in teeth.values())
    care_cost = sum(r["_cost"] for r in rows if not r["_tooth"])
    if abs(teeth_cost + care_cost - total_cost) > TOL:
        problems.append("tooth+care split identity broken")
    grouped = replay_grouped(rows)
    if set(grouped) != set(teeth):
        problems.append("dual-algorithm tooth set mismatch")
    for tooth, grp in grouped.items():
        lvl = 0
        extract_done = False
        for row in sorted(grp, key=lambda r: (r["_date"], r["_line"])):
            ev = row["_event"]
            if ev == FLAG_EVENT:
                if lvl >= 6:
                    problems.append("line %d: watch on replaced tooth"
                                    % row["_line"])
                continue
            if ev in TREAT_LEVEL:
                l = TREAT_LEVEL[ev]
                if ev == "extract" and extract_done:
                    problems.append("line %d: double extract" % row["_line"])
                if lvl >= 6 and ev != "implant":
                    problems.append("line %d: treat on replaced"
                                    % row["_line"])
                if l < lvl - TOL:
                    problems.append("line %d: ratchet downgrade"
                                    % row["_line"])
                lvl = max(lvl, l)
                if ev == "extract":
                    extract_done = True
    if problems:
        print("validate: %d problem(s)" % len(problems))
        for p in problems:
            print("  ✗ %s" % p)
        raise LedgerError("validate failed")
    print("validate: OK")
    print("  Σ分类 = Σ牙位 + 全口 = 总额 %s ✓" % money(total_cost))
    print("  双算法重放一致（全序游走 == 按牙分组）✓")
    print("  棘轮合法：无降级、无复活、无种植后事件 ✓")
    return EXIT_OK


# ---------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(
        prog="silent_rot.py",
        description="暗蛀 · Silent Rot — 口腔治疗史账本（零依赖 CLI）")
    p.add_argument("--as-of", dest="as_of", default=None,
                   help="锚定日期 YYYY-MM-DD（缺省=账本最大日期）")
    p.add_argument("--check-line", type=int, default=DEFAULTS["check_line"],
                   help="护理空白红线（天，默认 730）")
    p.add_argument("--watch-line", type=int, default=DEFAULTS["watch_line"],
                   help="观察挂起红线（天，默认 365）")
    p.add_argument("--silent-line", type=int, default=DEFAULTS["silent_line"],
                   help="发现→处理拖延红线（天，默认 365）")
    p.add_argument("--crown-line", type=int, default=DEFAULTS["crown_line"],
                   help="根管后无冠红线（天，默认 180）")
    p.add_argument("--scaling-interval", type=int,
                   default=DEFAULTS["scaling_interval"],
                   help="洗牙周期（天，默认 365）")
    p.add_argument("--watch-review", type=int,
                   default=DEFAULTS["watch_review"],
                   help="观察复查周期（天，默认 90）")
    p.add_argument("--crown-review", type=int,
                   default=DEFAULTS["crown_review"],
                   help="冠随访周期（天，默认 365）")
    p.add_argument("--implant-review", type=int,
                   default=DEFAULTS["implant_review"],
                   help="种植随访周期（天，默认 365）")
    p.add_argument("--due-soon", type=int, default=DEFAULTS["due_soon"],
                   help="DUE-SOON 窗口（天，默认 90，含边界）")
    p.add_argument("--price", action="append", default=[], metavar="EV=NUM",
                   help="覆盖通识价签，如 --price fill=500（可重复）")
    p.add_argument("command",
                   choices=["report", "ratchet", "silent", "due", "cost",
                            "validate"])
    p.add_argument("ledger", help="口腔事件流水 TSV")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    as_of_explicit = args.as_of is not None
    as_of = None
    if as_of_explicit:
        try:
            parts = args.as_of.split("-")
            as_of = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            print("bad --as-of %r (want YYYY-MM-DD)" % args.as_of,
                  file=sys.stderr)
            return EXIT_LEDGER
    pricebook = dict(DEFAULT_PRICEBOOK)
    for spec in args.price:
        if "=" not in spec:
            print("bad --price %r (want EV=NUM)" % spec, file=sys.stderr)
            return EXIT_LEDGER
        k, _, v = spec.partition("=")
        if k not in DEFAULT_PRICEBOOK:
            print("unknown price key %r (want one of %s)"
                  % (k, ", ".join(sorted(DEFAULT_PRICEBOOK))), file=sys.stderr)
            return EXIT_LEDGER
        try:
            pricebook[k] = float(v)
        except ValueError:
            print("bad --price value %r" % v, file=sys.stderr)
            return EXIT_LEDGER
    try:
        rows, teeth, care, total_cost, max_date = load_ledger(
            args.ledger, as_of, as_of_explicit)
        if not as_of_explicit:
            as_of = max_date
        if args.command == "report":
            return cmd_report(args, rows, teeth, care, total_cost, as_of,
                              pricebook)
        if args.command == "ratchet":
            return cmd_ratchet(args, rows, teeth, care, total_cost, as_of,
                               pricebook)
        if args.command == "silent":
            return cmd_silent(args, rows, teeth, care, total_cost, as_of,
                              pricebook)
        if args.command == "due":
            return cmd_due(args, rows, teeth, care, total_cost, as_of,
                           pricebook)
        if args.command == "cost":
            return cmd_cost(args, rows, teeth, care, total_cost, as_of,
                            pricebook)
        if args.command == "validate":
            return cmd_validate(args, rows, teeth, care, total_cost, as_of,
                                pricebook)
        return EXIT_OK
    except LedgerError as e:
        print("ledger error: %s" % e, file=sys.stderr)
        return EXIT_LEDGER
    except Gate as e:
        if str(e):
            print(str(e))
        return EXIT_GATE


if __name__ == "__main__":
    sys.exit(main())
