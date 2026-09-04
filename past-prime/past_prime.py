#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""超役 · Past Prime

家电是家里唯一「买下来就在倒计时」的资产：判废年限官方早就写好了——
燃气热水器 8 年（GB 17905-2008 判废年限）、电热水器/洗衣机/吸油烟机 8 年、
电冰箱/空调 10 年（中国家用电器协会安全使用年限）——但从没有任何账单把
这个年限挂到每一台电器头上。超役的燃气具挂在离洗澡水一米的地方，是
一氧化碳事故的常客；装修那年同批进门的电器，会在同一年集体到站；而
「坏了再说」的人，每一次都在为突发的大额支出刷卡。记忆管不了十年后
的事，账本可以。

本件把全屋电器抄成一本可手编的服役账（TSV：一行一台），开出六本账：

  - report    全屋老龄化地图：OK / WATCH / DUE-SOON / OVERDUE 四档判级，
              涉燃气涉水涉电加热的「涉险台」单列红区（超役 exit 4）；
              退休潮（到站日 730 天内 ≥2 台聚簇）与购入批次（同年 ≥2 台）；
              退役史反哺个人节奏（≥3 台才出统计，否则 THIN）；
  - queue     退休时刻表：未来几年谁到站、每年预算多少；
  - fund      家电退休金：把 14 次财务事故变成一条预算线——
              未来 12 个月每月存多少（超役台走 12 个月快速通道）；
  - simulate  replace-all（今天全换 vs 按到站日排队：总额守恒，
              退休金不创造钱，只搬移钱在时间上的位置）/
              keep ITEM --years N（推迟不是豁免：到站日在日历上等你）；
  - energy    实测 kWh 折电费（无实测行 DECLINE，不发明你的用电量）；
  - validate  账本体检：判级完备 / 池构成 / 守恒 / 单调性 / 双算法。

零依赖（Python 3.8+ 标准库）。账本自锚定：缺省 as-of = 账本最大日期
（购入与退役里最晚的一天），`--as-of` 显式钉死后同一本账任何机器任何
一天逐字节一致。报告只打印 basename，不回显调用方路径。

诚实条款：判废年限是通识先验不是精确预言——gb17905 / assoc2020 / folk
三级来源逐台标注，--life 一句话翻案，说明书与铭牌永远赢，本地价格永远
赢（replace_cost 列 / --price CAT=元，先验中位只垫底并标 assumed）；
账本不下检修结论，超役燃气具的灯指向燃气公司安检与品牌售后，换与不换
永远是人的决定；没有购入日期的电器进 NEVER-DATED 点名——没有日期就不
装知道；先验表外的品类不猜寿命，要求 life_years 列或 --life 后才入图。

Exit codes: 0 绿 · 2 账本/参数损坏 · 3 样本太薄/无在役台 · 4 超役红灯
"""

import argparse
import datetime as dt
import os
import sys

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_THIN = 3
EXIT_RED = 4

EPS = 1e-9
WAVE_WINDOW_DAYS = 730      # 退休潮聚簇窗：到站日相距 ≤730 天算同一波
DUE_SOON_DAYS = 365         # DUE-SOON：剩余 ≤1 年
WATCH_DAYS = 730            # WATCH：剩余 ≤2 年
FAST_TRACK_MONTHS = 12      # 超役台入池的快速摊销期
CADENCE_MIN = 3             # 退役史个人节奏统计的最小样本
BURST_SHARE = 0.5           # 单年退役支出占全史 ≥50% 判「突击」
LIFE_MIN, LIFE_MAX = 1, 50  # 寿命 sanity 带宽（年）

# ------------------------------------------------------------------ priors
# life_years 判废/安全使用年限（年）；source：gb17905=GB 17905-2008《家用燃气
# 燃烧器具安全管理规则》判废年限 · assoc2020=中国家用电器协会《家用电器安全
# 使用年限》(2020) · folk=通识先验。cost=今日换新参考中位（元，只垫底）；
# new_kwh_month=新一级能效对照（kWh/月，通识，assumed）；safe=涉险台
# （涉燃气燃烧 / 储水电加热 / 贴身电加热——人身直接相关，超役单列红区）。
# 全部可被 --priors 文件 / --life / --price / --safe 覆盖：本地永远赢。
PRIORS = {
    "燃气热水器": dict(life=8, source="gb17905", cost=2500, new_kwh=None, safe=True),
    "电热水器":   dict(life=8, source="assoc2020", cost=2000, new_kwh=None, safe=True),
    "燃气灶":     dict(life=8, source="gb17905", cost=1100, new_kwh=None, safe=True),
    "电热毯":     dict(life=6, source="folk", cost=250, new_kwh=None, safe=True),
    "吸油烟机":   dict(life=8, source="assoc2020", cost=1900, new_kwh=None, safe=False),
    "洗衣机":     dict(life=8, source="assoc2020", cost=2400, new_kwh=None, safe=False),
    "干衣机":     dict(life=8, source="folk", cost=3000, new_kwh=None, safe=False),
    "洗碗机":     dict(life=8, source="folk", cost=4000, new_kwh=None, safe=False),
    "电冰箱":     dict(life=10, source="assoc2020", cost=3600, new_kwh=24, safe=False),
    "空调":       dict(life=10, source="assoc2020", cost=3200, new_kwh=None, safe=False),
    "电视":       dict(life=8, source="folk", cost=3500, new_kwh=None, safe=False),
    "微波炉":     dict(life=10, source="folk", cost=500, new_kwh=None, safe=False),
    "电饭煲":     dict(life=5, source="folk", cost=350, new_kwh=None, safe=False),
    "扫地机器人": dict(life=5, source="folk", cost=1800, new_kwh=None, safe=False),
    "净水机":     dict(life=8, source="folk", cost=2200, new_kwh=None, safe=False),
    "加湿器":     dict(life=5, source="folk", cost=300, new_kwh=None, safe=False),
}

# 中英别名归一（ canonical ← aliases ）
ALIASES = {
    "燃气热水器": ("gas_water_heater", "gas water heater", "燃气式热水器",
                  "热水器-燃气", "燃气热水器"),
    "电热水器": ("electric_water_heater", "electric water heater", "储水式电热水器",
                "电热水器"),
    "燃气灶": ("gas_stove", "gas stove", "燃气灶具", "灶具", "燃气灶"),
    "吸油烟机": ("range_hood", "range hood", "抽油烟机", "油烟机", "吸油烟机"),
    "电冰箱": ("fridge", "refrigerator", "冰箱", "冰柜", "电冰箱"),
    "洗衣机": ("washer", "washing_machine", "washing machine", "滚筒洗衣机",
              "波轮洗衣机", "洗衣机"),
    "干衣机": ("dryer", "clothes_dryer", "烘干机", "干衣机"),
    "洗碗机": ("dishwasher", "洗碗机"),
    "空调": ("ac", "air_conditioner", "air conditioner", "挂机", "柜机", "空调"),
    "电视": ("tv", "television", "电视机", "电视"),
    "微波炉": ("microwave", "微波炉"),
    "电饭煲": ("rice_cooker", "电饭锅", "电饭煲"),
    "扫地机器人": ("robot_vacuum", "robot vacuum", "扫地机", "扫地机器人"),
    "净水机": ("water_purifier", "净水器", "净水机"),
    "电热毯": ("electric_blanket", "电热毯"),
    "加湿器": ("humidifier", "加湿器"),
}

TIER_ORDER = {"OK": 0, "WATCH": 1, "DUE-SOON": 2, "OVERDUE": 3}
TIER_ZH = {"OK": "OK", "WATCH": "WATCH", "DUE-SOON": "DUE-SOON",
           "OVERDUE": "超役"}


class LedgerError(Exception):
    """账本/参数损坏：exit 2"""


class ThinError(Exception):
    """样本太薄/无在役台：exit 3"""


# ---------------------------------------------------------------- primitives
def parse_date(s, what="date"):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise LedgerError("bad %s %r (want YYYY-MM-DD)" % (what, s))


def add_years(d, n):
    """购入日 + n 年（日历口径：8 年就是日历上的第 8 个周年；2/29 落到 2/28）"""
    try:
        return d.replace(year=d.year + n)
    except ValueError:                      # 2/29 → 平年
        return d.replace(year=d.year + n, day=28)


def remaining_days(due, as_of):
    """双算法之一：timedelta 差"""
    return (due - as_of).days


def remaining_days_alt(due, as_of):
    """双算法之二：儒略日序数差（validate 用，与上者必须相等）"""
    return due.toordinal() - as_of.toordinal()


def tier_of(rem):
    if rem > WATCH_DAYS:
        return "OK"
    if rem > DUE_SOON_DAYS:
        return "WATCH"
    if rem > 0:
        return "DUE-SOON"
    return "OVERDUE"


def money(v):
    """¥1,162.50 / ¥26,800：有角分给角分，整数不带零头"""
    if abs(v - round(v)) < EPS:
        return "¥{:,.0f}".format(v)
    return "¥{:,.2f}".format(v)


def years_of(days):
    return days / 365.25


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    m = n // 2
    return xs[m] if n % 2 else (xs[m - 1] + xs[m]) / 2.0


def num(s):
    s = (s or "").strip()
    if not s:
        return None
    return float(s)


# ------------------------------------------------------------------ ledger
HEADER = ["item", "category", "buy_date", "price", "replace_cost",
          "retired_date", "kwh_month", "life_years", "note"]


def canon_category(raw):
    raw = (raw or "").strip().lower()
    if not raw:
        return ""
    for canon, aliases in ALIASES.items():
        if raw in (a.lower() for a in aliases) or raw == canon.lower():
            return canon
    return raw            # 先验表外原样返回（NEVER-PRIOR 点名，不猜）


def read_tsv(path):
    if not os.path.exists(path):
        raise LedgerError("ledger not found: %s" % os.path.basename(path))
    rows = []
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip() and
                 not ln.startswith("#")]
    if not lines:
        raise LedgerError("empty ledger")
    head = lines[0].split("\t")
    head = [h.strip().lstrip("\ufeff") for h in head]
    for ln in lines[1:]:
        cells = ln.split("\t")
        cells += [""] * (len(head) - len(cells))
        rows.append(dict(zip(head, [c.strip() for c in cells])))
    return rows


def load_ledger(path, as_of, life_over, safe_extra, price_over, priors_file):
    """返回 (active, retired, never_dated, never_prior, max_date, sources)"""
    priors = dict(PRIORS)
    for k, v in priors.items():
        priors[k] = dict(v)
    if priors_file:
        for r in read_tsv(priors_file):
            cat = canon_category(r.get("category", ""))
            if not cat:
                raise LedgerError("priors row without category")
            p = priors.setdefault(cat, dict(life=None, source="user",
                                            cost=None, new_kwh=None,
                                            safe=False))
            if r.get("life_years"):
                p["life"] = float(r["life_years"])
                p["source"] = "user"
            if r.get("replace_cost"):
                p["cost"] = float(r["replace_cost"])
            if r.get("new_kwh_month"):
                p["new_kwh"] = float(r["new_kwh_month"])
            if (r.get("safe") or "").strip().lower() in ("y", "yes", "1", "true"):
                p["safe"] = True
    for cat, y in life_over.items():
        priors.setdefault(cat, dict(life=None, source="user", cost=None,
                                    new_kwh=None, safe=False))
        priors[cat]["life"] = y
        priors[cat]["source"] = "user"
    for cat in safe_extra:
        priors.setdefault(cat, dict(life=None, source="user", cost=None,
                                    new_kwh=None, safe=False))
        priors[cat]["safe"] = True
    for cat, c in price_over.items():
        priors.setdefault(cat, dict(life=None, source="user", cost=None,
                                    new_kwh=None, safe=False))
        priors[cat]["cost"] = c
    price_pinned = set(price_over.keys())

    seen = set()
    active, retired, never_dated, never_prior = [], [], [], []
    max_date = None

    def bump(d):
        nonlocal max_date
        if d and (max_date is None or d > max_date):
            max_date = d

    for r in read_tsv(path):
        name = (r.get("item") or "").strip()
        if not name:
            raise LedgerError("row without item name")
        if name in seen:
            raise LedgerError("duplicate item %r" % name)
        seen.add(name)
        cat = canon_category(r.get("category"))
        buy = parse_date(r.get("buy_date"), "buy_date")
        retd = parse_date(r.get("retired_date"), "retired_date")
        bump(buy)
        bump(retd)
        life_col = num(r.get("life_years"))
        prior = priors.get(cat)
        if life_col is not None and not (LIFE_MIN <= life_col <= LIFE_MAX):
            raise LedgerError("%s: life_years %s out of sane range (%d..%d)"
                              % (name, life_col, LIFE_MIN, LIFE_MAX))
        it = dict(name=name, cat=cat, buy=buy, retd=retd,
                  price=num(r.get("price")),
                  cost_col=num(r.get("replace_cost")),
                  kwh=num(r.get("kwh_month")),
                  note=(r.get("note") or "").strip())
        if buy is None:
            it["safe"] = bool(prior and prior.get("safe")) or \
                cat in safe_extra
            never_dated.append(it)
            continue
        if buy > as_of:
            raise LedgerError("%s: buy_date %s is in the future of as-of %s"
                              % (name, buy.isoformat(), as_of.isoformat()))
        if retd:
            if retd < buy:
                raise LedgerError("%s: retired before buy" % name)
            if retd > as_of:
                raise LedgerError("%s: retired_date %s is in the future of "
                                  "as-of %s" % (name, retd.isoformat(),
                                                as_of.isoformat()))
            it["cost_out"] = it["cost_col"] if it["cost_col"] is not None \
                else (prior["cost"] if prior else None)
            retired.append(it)
            continue
        life = life_col
        source = "manual"
        if life is None:
            if prior and prior.get("life") is not None:
                life = prior["life"]
                source = prior["source"]
        if life is None:
            never_prior.append(it)
            continue
        it["life"] = life
        it["source"] = source
        it["safe"] = bool(prior and prior.get("safe")) or \
            cat in safe_extra
        it["due"] = add_years(buy, int(life))
        it["age_days"] = (as_of - buy).days
        it["rem"] = remaining_days(it["due"], as_of)
        it["tier"] = tier_of(it["rem"])
        if it["cost_col"] is not None:
            it["cost"] = it["cost_col"]
            it["cost_assumed"] = False
        elif prior and prior.get("cost") is not None:
            it["cost"] = prior["cost"]
            it["cost_assumed"] = cat not in price_pinned
        else:
            it["cost"] = None
            it["cost_assumed"] = True
        it["new_kwh"] = prior.get("new_kwh") if prior else None
        active.append(it)
    active.sort(key=lambda x: (x["rem"], x["name"]))
    retired.sort(key=lambda x: x["retd"])
    return active, retired, never_dated, never_prior, max_date, priors


def default_as_of(path):
    rows = read_tsv(path)
    mx = None
    for r in rows:
        for col in ("buy_date", "retired_date"):
            d = parse_date(r.get(col), col)
            if d and (mx is None or d > mx):
                mx = d
    if mx is None:
        raise LedgerError("ledger has no dated rows; pass --as-of")
    return mx


# --------------------------------------------------------------- judgement
def waves(active, window=WAVE_WINDOW_DAYS):
    """到站日 730 天内 ≥2 台 → 同一波退休潮；返回 (waves, singles)"""
    it = sorted([a for a in active if a.get("due")], key=lambda x: x["due"])
    out, i = [], 0
    while i < len(it):
        j = i
        while j + 1 < len(it) and (it[j + 1]["due"] - it[i]["due"]).days <= window:
            j += 1
        if j > i:
            out.append(it[i:j + 1])
            i = j + 1
        else:
            i += 1
    return out


def fund_pool(active):
    """未来 12 个月的池：所有 DUE-SOON 与 OVERDUE 台；超役台走快速通道"""
    pool = [a for a in active if a["tier"] in ("OVERDUE", "DUE-SOON")]
    fast = [a for a in pool if a["tier"] == "OVERDUE"]
    total = sum(a["cost"] or 0 for a in pool)
    return pool, fast, total


def monthly_split(total, months=12):
    """总额摊到月，分（fen）级最大余数法：Σ各月 == 总额，一分不差"""
    fen = int(round(total * 100))
    base, rem = divmod(fen, months)
    return [base + (1 if i < rem else 0) for i in range(months)]


def burst_year(retired):
    """单年退役支出占全史 ≥BURST_SHARE → 突击回放"""
    by_year = {}
    for r in retired:
        if r.get("cost_out"):
            by_year.setdefault(r["retd"].year, 0.0)
            by_year[r["retd"].year] += r["cost_out"]
    if not by_year:
        return None
    total = sum(by_year.values())
    year, amt = max(by_year.items(), key=lambda kv: kv[1])
    if total > 0 and amt / total >= BURST_SHARE and len(by_year) > 1:
        return dict(year=year, amount=amt, total=total,
                    share=amt / total, items=len(
                        [r for r in retired
                         if r["retd"].year == year and r.get("cost_out")]))
    return None


def as_of_line(as_of, explicit):
    if explicit:
        return "as-of: %s（--as-of 显式钉死）" % as_of.isoformat()
    return ("as-of: %s（缺省=账本最大日期；要看今天请显式 --as-of）"
            % as_of.isoformat())


def headline(active):
    cnt = {t: 0 for t in TIER_ORDER}
    for a in active:
        cnt[a["tier"]] += 1
    safe_over = [a for a in active
                 if a["tier"] == "OVERDUE" and a.get("safe")]
    return cnt, safe_over


# ----------------------------------------------------------------- reports
def cmd_report(args, st):
    active, retired, never_dated, never_prior = (st["active"], st["retired"],
                                                 st["never_dated"],
                                                 st["never_prior"])
    lines = []
    cnt, safe_over = headline(active)
    lines.append("超役 · Past Prime — 全屋电器服役账")
    lines.append("账本: %s    %s    在役 %d 台 · 已退役 %d 台"
                 % (os.path.basename(args.ledger), as_of_line(st["as_of"],
                                                             st["explicit"]),
                    len(active), len(retired)))
    lines.append("")
    if safe_over:
        lines.append("⚑ 红区 OVERDUE-SAFE ×%d —— 超役涉险电器（燃气燃烧 / 储水与贴身电加热）"
                     % len(safe_over))
        for a in safe_over:
            lines.append("  ⚑ %s  %s  超役 %d 天（判废 %g 年·%s）"
                         % (a["name"], a["cat"], -a["rem"], a["life"],
                            a["source"]))
        lines.append("  超役燃气具是一氧化碳事故的常客：约燃气公司安检或品牌售后，"
                     "换与不换是人的决定——账本不下检修结论")
        lines.append("")
    over = [a for a in active if a["tier"] == "OVERDUE"]
    if over:
        lines.append("⚑ 超役 %d 台（其中涉险 %d 台）—— 判废年限不是建议，是国家规则写好的"
                     % (len(over), len(safe_over)))
        lines.append("")
    lines.append("老龄化地图（按剩余寿命升序）")
    lines.append("  %-9s %-14s %-10s %-10s %6s %-14s %8s %10s"
                 % ("判级", "台名", "品类", "购入", "龄", "寿命·源", "剩余", "换新参考"))
    for a in active:
        cost = money(a["cost"]) if a["cost"] is not None else "—"
        if a["cost_assumed"] and a["cost"] is not None:
            cost += "*"
        lines.append("  %-9s %-14s %-10s %-10s %5.1fy %-14s %7dd %10s"
                     % (a["tier"], a["name"][:14], a["cat"][:10],
                        a["buy"].isoformat(), years_of(a["age_days"]),
                        "%gy·%s" % (a["life"], a["source"]),
                        a["rem"], cost))
    lines.append("  合计 %d 台：OVERDUE %d · DUE-SOON %d · WATCH %d · OK %d"
                 "（* = 换新参考为先验中位 assumed，--price CAT=元 翻案）"
                 % (len(active), cnt["OVERDUE"], cnt["DUE-SOON"],
                    cnt["WATCH"], cnt["OK"]))
    lines.append("")

    ws = waves(active)
    if ws:
        lines.append("⧗ 退休潮（到站日 %d 天内 ≥2 台聚簇）" % WAVE_WINDOW_DAYS)
        for i, w in enumerate(ws, 1):
            span = (w[-1]["due"] - w[0]["due"]).days
            safe_n = len([a for a in w if a.get("safe")])
            note = "，其中涉险 %d 台" % safe_n if safe_n else ""
            lines.append("  潮%s %s ~ %s（%d 天）%d 台到站%s"
                         % ("①②③④⑤⑥⑦⑧⑨⑩"[i - 1], w[0]["due"].isoformat(),
                            w[-1]["due"].isoformat(), span, len(w), note))
        lines.append("")

    by_year = {}
    for a in active:
        by_year.setdefault(a["buy"].year, []).append(a)
    batches = {y: v for y, v in by_year.items() if len(v) >= 2}
    if batches:
        lines.append("⧗ 购入批次（同年 ≥2 台）—— 同批购入，同批到站")
        for y in sorted(batches):
            v = batches[y]
            o = len([a for a in v if a["tier"] == "OVERDUE"])
            d = len([a for a in v if a["tier"] == "DUE-SOON"])
            stat = []
            if o:
                stat.append("%d 台已超役" % o)
            if d:
                stat.append("%d 台 DUE-SOON" % d)
            lines.append("  %d 批次 %d 台：%s"
                         % (y, len(v), "、".join(stat) if stat
                            else "全部在役期内"))
        lines.append("")

    if retired:
        lines.append("退役史（%d 台）" % len(retired))
        svcs = []
        for r in retired:
            svc = (r["retd"] - r["buy"]).days
            svcs.append(years_of(svc))
            out = money(r["cost_out"]) if r.get("cost_out") else "—"
            lines.append("  %-14s %s → %s   服役 %.1f 年   换新支出 %s（%d）"
                         % (r["name"][:14], r["buy"].isoformat(),
                            r["retd"].isoformat(), years_of(svc), out,
                            r["retd"].year))
        if len(svcs) >= CADENCE_MIN:
            lines.append("  个人节奏：中位服役 %.1f 年 —— 账本长起来，先验让位"
                         % median(svcs))
        else:
            lines.append("  个人节奏：THIN（<%d 台）——先验照用，统计拒答"
                         % CADENCE_MIN)
        b = burst_year(retired)
        if b:
            lines.append("  突击回放：%d 年退役支出 %s（%d 台），占全史 %.1f%%"
                         " —— 「坏了再说」的代价，是一年一次的财务事故"
                         % (b["year"], money(b["amount"]), b["items"],
                            b["share"] * 100))
        lines.append("")

    if never_dated:
        lines.append("NEVER-DATED（%d 台）—— 没有日期就不装知道，不入判级"
                     % len(never_dated))
        for a in never_dated:
            hint = "（涉险品类，优先考古这张）" if a.get("safe") else ""
            lines.append("  ? %s  %s%s" % (a["name"], a["cat"], hint))
        lines.append("  发票、电商订单、铭牌.serial 都记得它的生日")
        lines.append("")
    if never_prior:
        lines.append("NEVER-PRIOR（%d 台）—— 先验表外的品类不猜寿命，未判级不进地图"
                     % len(never_prior))
        for a in never_prior:
            lines.append("  ? %s  %s（life_years 列或 --life %s=年 翻案）"
                         % (a["name"], a["cat"], a["cat"]))
        lines.append("")

    if not active:
        lines.append("THIN: 在役 0 台——没有可判级的机器"
                     "（先抄台账，或 --as-of 钉回过去；"
                     "退役史与点名照出，算术不因薄账沉默）")
        print("\n".join(lines))
        return EXIT_THIN

    exit_code = EXIT_RED if cnt["OVERDUE"] else EXIT_OK
    if cnt["OVERDUE"]:
        lines.append("⚑ exit %d：超役 %d 台（涉险 %d）—— 先把燃气和储水加热的那几台办了"
                     % (exit_code, cnt["OVERDUE"], len(safe_over)))
    else:
        lines.append("exit %d：%s" % (exit_code,
                     "全部在役期内；最近到站 " + min(
                         active, key=lambda x: x["due"])["due"].isoformat()))
    print("\n".join(lines))
    return exit_code


def cmd_queue(args, st):
    active = st["active"]
    if not active:
        raise ThinError("在役 0 台——没有可排队的机器")
    due_items = sorted([a for a in active if a.get("due")],
                       key=lambda x: x["due"])
    overdue = [a for a in due_items if a["tier"] == "OVERDUE"]
    future = [a for a in due_items if a["tier"] != "OVERDUE"]
    horizon_end = add_years(st["as_of"], args.years)
    by_year = {}
    for a in future:
        if a["due"] <= horizon_end:
            by_year.setdefault(a["due"].year, []).append(a)
    beyond = [a for a in future if a["due"] > horizon_end]
    lines = []
    lines.append("退休时刻表（未来 %d 年）—— 账本: %s    %s"
                 % (args.years, os.path.basename(args.ledger),
                    as_of_line(st["as_of"], st["explicit"])))
    lines.append("")
    if overdue:
        amt = sum(a["cost"] or 0 for a in overdue)
        names = " · ".join("%s %s" % (a["name"], money(a["cost"])
                                      + ("*" if a["cost_assumed"] else ""))
                           for a in overdue)
        lines.append("  已到站（等待换新）：%s   立即预算 %s" % (names, money(amt)))
    total = sum(a["cost"] or 0 for a in overdue)
    for y in sorted(by_year):
        v = by_year[y]
        amt = sum(a["cost"] or 0 for a in v)
        total += amt
        names = " · ".join("%s %s" % (a["name"], money(a["cost"])
                                      + ("*" if a["cost_assumed"] else ""))
                           for a in v)
        lines.append("  %d: %s   年预算 %s" % (y, names, money(amt)))
    if not by_year:
        lines.append("  %d 年内无人到站" % args.years)
    lines.append("  horizon 合计 %s（%d 台）· 之外还有 %d 台更远"
                 % (money(total), len(overdue) +
                    sum(len(v) for v in by_year.values()), len(beyond)))
    allcost = sum(a["cost"] or 0 for a in due_items)
    lines.append("  全池 %s == 全部在役换新参考之和（守恒）" % money(allcost))
    print("\n".join(lines))
    return EXIT_OK


def cmd_fund(args, st):
    active = st["active"]
    if not active:
        raise ThinError("在役 0 台——没有可入池的机器")
    pool, fast, total = fund_pool(active)
    lines = []
    lines.append("家电退休金 —— 账本: %s    %s"
                 % (os.path.basename(args.ledger),
                    as_of_line(st["as_of"], st["explicit"])))
    lines.append("")
    if not pool:
        lines.append("未来 12 个月无人到站：本月退休金 ¥0（别停，池是给未来的）")
        print("\n".join(lines))
        return EXIT_OK
    per = monthly_split(total, FAST_TRACK_MONTHS)
    lines.append("未来 12 个月池 %s（%d 台，其中超役快速入池 %d 台）"
                 % (money(total), len(pool), len(fast)))
    lines.append("  → 每月存 %s（× 12 == 池，逐月 1 分尾差按最大余数法摊平）"
                 % (money(per[0] / 100.0)))
    lines.append("")
    if fast:
        fast_amt = sum(a["cost"] or 0 for a in fast)
        names = "、".join(a["name"] for a in fast)
        lines.append("快速通道（超役台不等你攒，先入池 %s）：%s"
                     % (money(fast_amt), names))
        lines.append("")
    lines.append("池构成（按到站日）")
    for a in pool:
        tag = "（快速通道）" if a["tier"] == "OVERDUE" else \
            "（%d 天后到站）" % a["rem"]
        lines.append("  · %s %s %s%s"
                     % (a["name"], money(a["cost"])
                        + ("*" if a["cost_assumed"] else ""), a["due"].isoformat(),
                        tag))
    allcost = sum(a["cost"] or 0 for a in active)
    lines.append("")
    lines.append("全池 %s（全部在役台）—— 退休金不创造钱，只把 14 次财务事故"
                 % money(allcost))
    lines.append("  变成一条预算线；fund 命令负责第一条线，queue 负责以后每一年")
    print("\n".join(lines))
    return EXIT_OK


def cmd_simulate(args, st):
    active = st["active"]
    if not active:
        raise ThinError("在役 0 台——没有可推演的机器")
    lines = ["simulate —— 账本: %s    %s"
             % (os.path.basename(args.ledger),
                as_of_line(st["as_of"], st["explicit"]))]
    lines.append("")
    if args.sim == "replace-all":
        total = sum(a["cost"] or 0 for a in active)
        pool, fast, p12 = fund_pool(active)
        lines.append("A. 今天全换：%d 台一次性 %s —— 安全清零，现金流一次到位"
                     % (len(active), money(total)))
        lines.append("B. 按到站日排队：同样 %d 台，还是 %s，只是摊在未来几年"
                     % (len(active), money(total)))
        lines.append("  守恒：A == B == 全池 %s —— 退休金不创造钱，"
                     "搬移的是钱在时间上的位置与你的心跳" % money(total))
        if pool:
            lines.append("  不换的话：池里的 %d 台（含超役 %d 台）将在 12 个月内"
                         "相继到站，风险留在原地" % (len(pool), len(fast)))
        lines.append("  退休金的意义：把 B 的散点装订成 fund 的一条月度线")
    else:
        target = None
        for a in active:
            if a["name"] == args.item:
                target = a
                break
        if target is None:
            raise LedgerError("no active item %r" % args.item)
        future = add_years(st["as_of"], args.years)
        age = years_of((future - target["buy"]).days)
        rem = remaining_days_alt(target["due"], future)
        lines.append("keep %s --years %d：到 %s，这台已 %.1f 岁"
                     % (target["name"], args.years, future.isoformat(), age))
        lines.append("  届时剩余 %d 天，判级 %s —— 推迟不是豁免，"
                     "到站日在日历上原地等你" % (rem, tier_of(rem)))
        if target.get("cost") is not None:
            lines.append("  推迟的 %s 不会打折：换新参考价按今日口径，"
                         "涨价与促销账本都不预测" % money(target["cost"]))
        if target.get("safe") and rem <= 0:
            lines.append("  ⚑ 涉险台再撑 %d 年：红区延长 %d 年，"
                         "安检的间隔账本建议问燃气公司" % (args.years, args.years))
    print("\n".join(lines))
    return EXIT_OK


def cmd_energy(args, st):
    active = [a for a in st["active"] if a.get("kwh") is not None]
    lines = ["energy —— 实测 kWh 折电费 —— 账本: %s    %s"
             % (os.path.basename(args.ledger),
                as_of_line(st["as_of"], st["explicit"]))]
    lines.append("")
    if not active:
        lines.append("DECLINE：账本没有一行实测 kWh——不发明你的用电量")
        lines.append("  电表读数 ÷ 月数抄进 kwh_month 列，本件才肯算这笔账")
        print("\n".join(lines))
        return EXIT_OK
    total_penalty = 0.0
    for a in active:
        cost_m = a["kwh"] * args.price_elec
        line = "  %s（%d 年机）%.0f kWh/月 → %s/月"
        if a.get("new_kwh"):
            penalty_m = (a["kwh"] - a["new_kwh"]) * args.price_elec
            total_penalty += penalty_m * 12
            lines.append(line % (a["name"], int(years_of(
                (st["as_of"] - a["buy"]).days)), a["kwh"], money(cost_m)))
            lines.append("      vs 新机对照 %g kWh/月（assumed 先验）→ 多付 %s/月 · 年化 %s"
                         % (a["new_kwh"], money(penalty_m),
                            money(penalty_m * 12)))
        else:
            lines.append(line % (a["name"], int(years_of(
                (st["as_of"] - a["buy"]).days)), a["kwh"], money(cost_m)))
            lines.append("      （该品类无新机对照先验，只折电费不判罚）")
    if total_penalty > 0:
        lines.append("")
        lines.append("超龄能效惩罚合计（assumed 口径）：年化 %s（五年 %s）"
                     % (money(total_penalty), money(total_penalty * 5)))
    lines.append("  换新省多少账本不承诺：先验是对照不是承诺，--priors 可翻案")
    print("\n".join(lines))
    return EXIT_OK


def cmd_validate(args, st):
    active, retired = st["active"], st["retired"]
    problems = []
    cnt, _ = headline(active)
    n = sum(cnt.values())
    if n != len(active):
        problems.append("判级不完备：Σ四档 %d != 在役 %d" % (n, len(active)))

    pool, fast, total = fund_pool(active)
    total2 = 0.0
    for a in active:
        if a["tier"] in ("OVERDUE", "DUE-SOON"):
            total2 += a["cost"] or 0
    if abs(total - total2) > 1e-6:
        problems.append("池构成双算法不一致：%.2f != %.2f" % (total, total2))

    due_items = [a for a in active if a.get("due")]
    allcost = sum(a["cost"] or 0 for a in due_items)
    horizon_end = add_years(st["as_of"], 999)
    q_total = sum(a["cost"] or 0 for a in due_items if a["due"] <= horizon_end)
    if abs(allcost - q_total) > 1e-6:
        problems.append("守恒破坏：全池 %.2f != queue 合计 %.2f" % (allcost, q_total))

    if pool:
        per = monthly_split(total, FAST_TRACK_MONTHS)
        if sum(per) != int(round(total * 100)):
            problems.append("月摊分配破坏：Σ逐月 %d != 池 %d 分"
                            % (sum(per), int(round(total * 100))))

    for a in due_items:
        if remaining_days(a["due"], st["as_of"]) != \
                remaining_days_alt(a["due"], st["as_of"]):
            problems.append("剩余天数双算法不一致：%s" % a["name"])
        due2 = add_years(a["buy"], int(a["life"]))
        if due2 != a["due"]:
            problems.append("到站日双算法不一致：%s" % a["name"])

    nxt = st["as_of"] + dt.timedelta(days=1)
    for a in due_items:
        t0 = TIER_ORDER[a["tier"]]
        t1 = TIER_ORDER[tier_of(remaining_days(a["due"], nxt))]
        if t1 < t0:
            problems.append("判级单调性破坏：%s %s→%s" % (a["name"], a["tier"],
                                                         tier_of(t1)))

    for r in retired:
        svc = (r["retd"] - r["buy"]).days
        if svc <= 0:
            problems.append("退役史非法：%s 服役 %d 天" % (r["name"], svc))

    ws = waves(active)
    covered = sum(len(w) for w in ws)
    singles = len(due_items) - covered
    if covered + singles != len(due_items):
        problems.append("退休潮聚簇不构成划分：%d+%d != %d"
                        % (covered, singles, len(due_items)))

    if problems:
        print("validate: %d problem(s)" % len(problems))
        for p in problems:
            print("  ✗ %s" % p)
        return EXIT_INPUT
    print("validate: OK")
    print("  Σ四档 = 在役 %d（OVERDUE %d · DUE-SOON %d · WATCH %d · OK %d）✓"
          % (len(active), cnt["OVERDUE"], cnt["DUE-SOON"], cnt["WATCH"],
             cnt["OK"]))
    print("  池构成双算法一致（%d 台 %s）✓" % (len(pool), money(total)))
    print("  守恒：全池 == queue 合计 %s ✓" % money(allcost))
    print("  月摊分配 Σ == 池（fen 级）✓" if pool else "  池空，月摊跳过 ✓")
    print("  剩余天数/到站日双算法一致 ✓")
    print("  判级单调（as-of+1 天不回绿）✓")
    print("  退役史 %d 台合法 ✓" % len(retired))
    print("  退休潮聚簇构成划分（%d 潮 + %d 单飞 = %d 台）✓"
          % (len(ws), singles, len(due_items)))
    return EXIT_OK


# -------------------------------------------------------------------- main
def parse_kv(specs, what):
    out = {}
    for spec in specs or []:
        if "=" not in spec:
            raise LedgerError("bad --%s %r (want CAT=VALUE)" % (what, spec))
        k, v = spec.split("=", 1)
        k = canon_category(k)
        try:
            out[k] = float(v)
        except ValueError:
            raise LedgerError("bad --%s value %r" % (what, v))
    return out


def build_parser():
    p = argparse.ArgumentParser(
        prog="past_prime",
        description="超役 · Past Prime — 全屋电器判废年限账本（零依赖 CLI）")
    p.add_argument("command",
                   choices=["report", "queue", "fund", "simulate",
                            "energy", "validate"])
    p.add_argument("ledger", help="全屋电器台账 TSV（一行一台）")
    p.add_argument("--as-of", dest="as_of", default=None,
                   help="锚定日期 YYYY-MM-DD（缺省=账本最大日期）")
    p.add_argument("--life", dest="life", action="append", default=[],
                   metavar="CAT=YEARS", help="覆盖品类判废年限（说明书永远赢）")
    p.add_argument("--safe", dest="safe", action="append", default=[],
                   metavar="CAT", help="把品类加进涉险名单（本地判断永远赢）")
    p.add_argument("--price", dest="price", action="append", default=[],
                   metavar="CAT=YUAN", help="覆盖品类换新参考中位（本地价格永远赢）")
    p.add_argument("--priors", dest="priors", default=None,
                   help="先验覆盖表 TSV（category/life_years/replace_cost/"
                        "new_kwh_month/safe）")
    p.add_argument("--years", type=int, default=6,
                   help="queue/simulate 视野年数（默认 6）")
    p.add_argument("--price-elec", dest="price_elec", type=float, default=0.55,
                   help="电价 元/kWh（energy 用，默认 0.55）")
    p.add_argument("sim", nargs="?", default=None,
                   choices=[None, "replace-all", "keep"],
                   help="simulate 子命令")
    p.add_argument("item", nargs="?", default=None,
                   help="simulate keep 的台名")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        if args.as_of:
            as_of = parse_date(args.as_of, "--as-of")
            explicit = True
        else:
            as_of = default_as_of(args.ledger)
            explicit = False
        life_over = {k: v for k, v in parse_kv(args.life, "life").items()}
        safe_extra = [canon_category(s) for s in (args.safe or [])]
        price_over = parse_kv(args.price, "price")
        active, retired, never_dated, never_prior, _max_date, _priors = \
            load_ledger(args.ledger, as_of, life_over, safe_extra,
                        price_over, args.priors)
        st = dict(active=active, retired=retired, never_dated=never_dated,
                  never_prior=never_prior, as_of=as_of, explicit=explicit)
        if args.command == "report":
            return cmd_report(args, st)
        if args.command == "queue":
            return cmd_queue(args, st)
        if args.command == "fund":
            return cmd_fund(args, st)
        if args.command == "simulate":
            if not args.sim:
                raise LedgerError("simulate needs replace-all | keep ITEM")
            if args.sim == "keep" and not args.item:
                raise LedgerError("simulate keep needs ITEM")
            return cmd_simulate(args, st)
        if args.command == "energy":
            return cmd_energy(args, st)
        if args.command == "validate":
            return cmd_validate(args, st)
        raise LedgerError("unknown command %r" % args.command)
    except LedgerError as e:
        print("ledger error: %s" % e, file=sys.stderr)
        return EXIT_INPUT
    except ThinError as e:
        print("THIN: %s" % e)
        return EXIT_THIN


if __name__ == "__main__":
    sys.exit(main())
