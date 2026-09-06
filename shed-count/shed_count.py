#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""秋毫 · Shed Count

掉发是唯一「每天照镜子、却看不见月尺度变化」的身体信号：头发以每天
几十根的速率脱落，任何肉眼与任何镜子都对月尺度渐变彻底失明——地漏里
那一撮毛引发的焦虑没有分母（比什么时候？多多少？），而生理性脱发
50–100 根/天的先验从未被逐日对过账。皮肤科门诊问「掉多久了、有没有
变稀」，病人凭感觉答；米诺地尔宣称 3–4 个月起效、非那雄胺 6 个月评估，
「你家起没起效」只有干预前后同口径的速率对比能回答；停药反弹、秋季
换发季背不背锅，同样没有账本。数一数这次洗头掉了多少根（60 秒计数
试验同源的皮肤科真实协议），是唯一便宜、客观、可重复的度量，却从没
有人把它记成一本账。

本件把每次洗头的掉发计数抄成一本可手编的事件流账（TSV：日期/口径/
根数/干预事件/备注），开出五本账：

  - report        总账：全期/近90天/近30天三个观测窗的间隔归一速率
                  （根/天），绝对判级（OK ≤ 生理先验线 < SHED ≤ 急性线
                  < FLOOD）叠相对判级（对比你自己头 90 天的中位基线），
                  干预事件时间线，红灯指向就诊线索（exit 4）；
  - rate          速率明细：逐行间隔归一（根/天 = 根数 ÷ 距上次同口径
                  天数）、GAP 断记剔除（间隔超线的那几天没有观测，
                  不进分母——账本只对观测到的天数发言）、秋季窗签；
  - intervention  干预对账：每次 start/stop 开庭——起效潜伏窗先验
                  （米诺地尔 90 天、非那雄胺 180 天……通识先验可调）
                  之外才开 after 窗，before/after 同口径速率对比出
                  RESPONDING / NO-CHANGE / WORSE；停药单开反弹庭
                  （REBOUND）；联合用药窗标 CONFOUNDED——功劳不记
                  给单一药物；治疗没在窗内全程在场判 VOID——算术照
                  出，判决作废；
  - season        月历账：逐月归一速率，秋季换发季（通识先验 9–11 月，
                  可调）逐行标注，有跨年同月才出同比——季节背不背锅
                  让账本说话；
  - validate      账本体检：间隔双算法（timedelta == 儒略日序数）、
                  池化双算法、观测窗分解恒等、GAP 剔除完备、口径门
                  （wash 与 comb 六十秒采样永不混算）、别名幂等、
                  判级边界恰线行为、as-of 确定性。

诚实条款：洗头计数是「洗走的那部分毛」的样本，不是全头清点——判级
先验只是通识垫底，真正可比的是你自己的前后与基线；账本不是皮肤科医
生，不鉴别 AGA 与休止期脱发，不下药，红灯的灯文指向就诊；开始、停
止、复诊永远是人和医生的决定，账本只拒绝让「感觉」继续独裁。

零依赖（Python 3.8+ 标准库）。账本自锚定：缺省 as-of = 账本最大日期，
--as-of 显式钉死后同一本账任何机器任何一天逐字节一致；报告只打印
basename，源码无系统时钟。

Exit codes: 0 绿 · 2 账本/参数损坏 · 3 样本太薄/统计拒绝 · 4 超生理线红灯
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

# ------------------------------------------------------------ 通识先验
# 全部是通识先验（folk），不是事实断言；--shed-line 等一律可翻案，
# 医嘱永远赢，本地永远赢。生理性脱发 50–100 根/天（folk），洗头计数
# 只是「洗走的那部分」，绝对线垫底，前后与基线才是主判据。
SHED_LINE = 100.0        # 归一后根/天：> 此线亮 SHED（恰在线上=OK 宁可少亮灯）
FLOOD_LINE = 200.0       # > 此线亮 FLOOD（急性休止期脱发量级，灯文=就诊线索）
ELEVATE_LINE = 1.5       # 近窗速率 > 基线 × 此线 → ELEVATED（相对自己的过去）
GAP_CAP_DAYS = 45        # 同口径相邻间隔超此天数：那几天没有观测，剔除分母
BASE_WINDOW_DAYS = 90    # 个人基线窗：账本头 90 天的中位对率
WIN_LONG_DAYS = 90       # report 长窗
WIN_SHORT_DAYS = 30      # report 短窗（判级面）
SPAN_DAYS = 90           # 干预庭 before/after 窗宽
RESPOND_LINE = 0.30      # drop = 1 − after/before ≥ 此线 → RESPONDING（含边界）
WORSE_LINE = 0.15        # rise = after/before − 1 > 此线 → WORSE（恰线不亮）
REBOUND_LINE = 0.15      # 停药后 rise > 此线 → REBOUND（恰线不亮）
REBOUND_LAG_DAYS = 90    # 停药反弹观察窗的起算延迟（folk）
SEASON_MONTHS = (9, 10, 11)  # 秋季换发季（folk）：逐行标注，不豁免判级
MIN_BASE_PAIRS = 3       # 个人基线的最少对数（少于此不装知道基线）

# 起效潜伏窗先验（天，folk）：宣称评估窗——潜伏期内不进 after 窗，
# 「3 个月见效」的账要从第 90 天后才算。--lag T=D 一句话翻案。
LAG_PRIORS = {
    "minoxidil": 90,         # 米诺地尔：3–4 个月评估（folk）
    "finasteride": 180,      # 非那雄胺：6 个月评估（folk）
    "dutasteride": 180,      # 度他雄胺（folk）
    "spironolactone": 180,   # 螺内酯（folk）
    "prp": 90,               # 富血小板血浆（folk）
    "transplant": 270,       # 植发：9 个月+（folk）
    "supplement": 180,       # 口服补剂（folk）
}

# 中英别名归一（canonical ← aliases）
KIND_ALIASES = {
    "wash": ("wash", "洗头", "洗发", "shampoo", "洗"),
    "comb": ("comb", "梳头", "60秒", "60s", "六十秒", "梳"),
}
VERB_ALIASES = {
    "start": ("start", "begin", "开始", "用", "用上", "上"),
    "stop": ("stop", "停", "停用", "停药"),
}
DRUG_ALIASES = {
    "minoxidil": ("minoxidil", "米诺地尔", "米诺", "落健", "蔓迪"),
    "finasteride": ("finasteride", "非那雄胺", "非那", "保法止"),
    "dutasteride": ("dutasteride", "度他雄胺"),
    "spironolactone": ("spironolactone", "螺内酯"),
    "prp": ("prp", "富血小板血浆"),
    "transplant": ("transplant", "植发", "hair_transplant"),
    "supplement": ("supplement", "补剂", "口服补剂"),
}

VERDICT_ZH = {
    "RESPONDING": "响应",
    "NO-CHANGE": "无变化",
    "WORSE": "更差",
    "REBOUND": "反弹",
    "VOID": "判决作废",
    "INSUFFICIENT-WINDOW": "窗内样本不足",
    "LAG-UNKNOWN": "潜伏窗未知",
}


class LedgerError(Exception):
    """账本/参数损坏：exit 2"""


class ThinError(Exception):
    """样本太薄/统计拒绝：exit 3"""


# ------------------------------------------------------------ primitives
def parse_date(s, what="date"):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise LedgerError("bad %s %r (want YYYY-MM-DD)" % (what, s))


def parse_int(s, what="count"):
    s = (s or "").strip()
    if not s:
        return None
    try:
        v = int(s)
    except ValueError:
        raise LedgerError("bad %s %r (want integer)" % (what, s))
    return v


def num(s):
    s = (s or "").strip()
    if not s:
        return None
    return float(s)


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    m = n // 2
    return xs[m] if n % 2 else (xs[m - 1] + xs[m]) / 2.0


def canon(raw, table, what):
    """别名归一：canonical ← aliases；表外原样返回（不猜）。"""
    raw = (raw or "").strip().lower()
    if not raw:
        return ""
    for canon_name, aliases in table.items():
        if raw in (a.lower() for a in aliases) or raw == canon_name.lower():
            return canon_name
    return raw


def canon_kind(raw):
    return canon(raw, KIND_ALIASES, "kind")


def gap_days(d2, d1):
    """双算法之一：timedelta 差"""
    return (d2 - d1).days


def gap_days_alt(d2, d1):
    """双算法之二：儒略日序数差（validate 用，与上者必须相等）"""
    return d2.toordinal() - d1.toordinal()


def pct(v):
    return "%.1f%%" % (v * 100.0)


def rate_s(v):
    return "%.1f" % v


# ------------------------------------------------------------ ledger
HEADER = ["date", "kind", "count", "event", "note"]


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


def parse_event(raw):
    """'start minoxidil' / 'start-minoxidil' / '开始米诺地尔' → (verb, drug)。

    空格/连字符优先切分；独词时按最长动词前缀剥离。表外动词 exit 2，
    表外药名原样保留（潜伏窗未知，不装知道）。
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    low = raw.lower()
    for sep in (" ", "-", "_"):
        if sep in low:
            head, tail = low.split(sep, 1)
            verb = canon(head, VERB_ALIASES, "verb")
            if verb in VERB_ALIASES and head == head.strip():
                return verb, canon(tail.strip(), DRUG_ALIASES, "drug")
    for verb_canon, aliases in VERB_ALIASES.items():
        for a in sorted(aliases, key=len, reverse=True):
            if low.startswith(a.lower()) and len(low) > len(a):
                drug = raw[len(a):].strip().lower()
                drug = canon(drug, DRUG_ALIASES, "drug")
                return verb_canon, drug
    raise LedgerError("bad event %r (want '<verb> <treatment>', "
                      "verb in start/stop)" % raw)


def load_ledger(path, as_of):
    """返回 dict：kinds（wash/comb 行）、events、pairs、min/max 日期。

    规则：同一 (日期, 口径) 重复 exit 2；根数须为非负整数；日期晚于
    as-of 的行是「还没写下的未来」——截断回放直接排除（不是透视，
    也不是账坏）。
    """
    kinds = {"wash": [], "comb": []}
    other_kinds = {}
    events = []
    seen = set()
    for r in read_tsv(path):
        d = parse_date(r.get("date"), "date")
        if d is None:
            raise LedgerError("row without date")
        if d > as_of:
            continue                     # 截断回放：未来行不入账
        kind_raw = (r.get("kind") or "").strip()
        cnt = parse_int(r.get("count"), "count")
        kind = canon_kind(kind_raw)
        has_data = bool(kind_raw)
        if cnt is not None and cnt < 0:
            raise LedgerError("%s: negative count %d"
                              % (d.isoformat(), cnt))
        if has_data:
            if kind not in kinds:
                # 表外口径原样收集，绝不混进 wash/comb 的任何统计（口径门）
                other_kinds.setdefault(kind, []).append(d)
            else:
                if cnt is None:
                    raise LedgerError("%s: kind %s needs count"
                                      % (d.isoformat(), kind))
                if cnt < 0:
                    raise LedgerError("%s: negative count %d"
                                      % (d.isoformat(), cnt))
                key = (d, kind)
                if key in seen:
                    raise LedgerError("duplicate %s row on %s"
                                      % (kind, d.isoformat()))
                seen.add(key)
                kinds[kind].append(dict(date=d, count=cnt,
                                        note=(r.get("note") or "").strip()))
        ev_raw = (r.get("event") or "").strip()
        if ev_raw:
            verb, drug = parse_event(ev_raw)
            if verb not in VERB_ALIASES:
                raise LedgerError("bad event verb in %r" % ev_raw)
            events.append(dict(date=d, verb=verb, drug=drug,
                               note=(r.get("note") or "").strip()))
        if not has_data and cnt is not None:
            raise LedgerError("row %s has count without kind" % d.isoformat())
        if not has_data and not ev_raw:
            raise LedgerError("row %s has neither kind/count nor event"
                              % d.isoformat())
    for k in kinds:
        kinds[k].sort(key=lambda it: it["date"])
    events.sort(key=lambda ev: (ev["date"], ev["verb"], ev["drug"]))

    all_dates = [it["date"] for k in kinds for it in kinds[k]] + \
                [ev["date"] for ev in events] + \
                [d for ds in other_kinds.values() for d in ds]
    max_date = max(all_dates) if all_dates else None
    min_date = min(all_dates) if all_dates else None
    return dict(kinds=kinds, other_kinds=other_kinds, events=events,
                min_date=min_date, max_date=max_date, as_of=as_of)


def build_pairs(rows, gap_cap):
    """同口径相邻配对：rate = count / gap；gap > cap 打 GAP 签并从一切
    池中剔除（那几天没有观测，分母只收观测到的天数）。首行无对。"""
    pairs = []
    for i in range(1, len(rows)):
        prev, cur = rows[i - 1], rows[i]
        gap = gap_days(cur["date"], prev["date"])
        if gap <= 0:
            raise LedgerError("non-increasing %s dates near %s"
                              % ("row", cur["date"].isoformat()))
        tags = []
        if gap > gap_cap:
            tags.append("GAP")
        if cur["date"].month in SEASON_MONTHS:
            tags.append("SEASON")
        pairs.append(dict(date=cur["date"], count=cur["count"],
                          prev=prev["date"], gap=gap,
                          rate=cur["count"] / float(gap), tags=tags))
    return pairs


def pool(pairs, lo=None, hi=None):
    """观测窗池化：Σ根数 / Σ观测天数（GAP 对剔除）。窗按对所属的洗头
    日计：lo ≤ date ≤ hi。返回 (counts, days, rate, n_pairs)。"""
    cs = ds = 0
    n = 0
    for p in pairs:
        if "GAP" in p["tags"]:
            continue
        if lo is not None and p["date"] < lo:
            continue
        if hi is not None and p["date"] > hi:
            continue
        cs += p["count"]
        ds += p["gap"]
        n += 1
    rate = (cs / float(ds)) if ds else None
    return dict(counts=cs, days=ds, rate=rate, n=n)


def pool_alt(pairs, lo=None, hi=None):
    """双算法之二：先过滤再一次求和（validate 用，与 pool 必须相等）。"""
    sel = [p for p in pairs if "GAP" not in p["tags"]
           and (lo is None or p["date"] >= lo)
           and (hi is None or p["date"] <= hi)]
    cs = sum(p["count"] for p in sel)
    ds = sum(p["gap"] for p in sel)
    rate = (cs / float(ds)) if ds else None
    return dict(counts=cs, days=ds, rate=rate, n=len(sel))


def window_bounds(as_of, days):
    return as_of - dt.timedelta(days=days - 1), as_of


def abs_tier(rate):
    """绝对判级：> FLOOD → FLOOD；> SHED → SHED；否则 OK（恰线=OK）。"""
    if rate is None:
        return None
    if rate > FLOOD_LINE + EPS:
        return "FLOOD"
    if rate > SHED_LINE + EPS:
        return "SHED"
    return "OK"


def baseline_of(pairs, min_date, window_days, min_pairs=3):
    """个人基线：账本头 window_days 天内的中位对率（GAP 对剔除）。
    少于 min_pairs 个对 → None（不装知道自己的基线）。"""
    hi = min_date + dt.timedelta(days=window_days - 1)
    rates = [p["rate"] for p in pairs
             if "GAP" not in p["tags"] and p["date"] <= hi]
    if len(rates) < min_pairs:
        return None
    return median(rates)


def lag_of(drug, overrides):
    if drug in overrides:
        return overrides[drug]
    return LAG_PRIORS.get(drug)


# ------------------------------------------------------------ commands
def _windows(ld, pairs, gap_cap):
    as_of = ld["as_of"]
    lo_s, _ = window_bounds(as_of, WIN_SHORT_DAYS)
    lo_l, _ = window_bounds(as_of, WIN_LONG_DAYS)
    full = pool(pairs)
    long_w = pool(pairs, lo=lo_l)
    short_w = pool(pairs, lo=lo_s)
    base = baseline_of(pairs, ld["min_date"], BASE_WINDOW_DAYS)
    return dict(full=full, long=long_w, short=short_w, base=base,
                short_lo=lo_s, long_lo=lo_l)


def cmd_report(path, args):
    ld = load_ledger(path, args.as_of)
    pairs = build_pairs(ld["kinds"]["wash"], args.gap_cap)
    w = _windows(ld, pairs, args.gap_cap)
    name = os.path.basename(path)

    out = []
    out.append("秋毫 · Shed Count — %s" % name)
    out.append("as-of %s（缺省=账本最大日期）" % ld["as_of"].isoformat())
    span = (ld["max_date"] - ld["min_date"]).days + 1 \
        if ld["min_date"] else 0
    obs = w["full"]["days"]
    cov = (obs / float(span)) if span else 0.0
    out.append("跨度 %d 天 · 观测 %d 天（覆盖率 %s）· wash 对 %d · comb 行 %d "
               "· 干预事件 %d"
               % (span, obs, pct(cov), len(pairs),
                  len(ld["kinds"]["comb"]), len(ld["events"])))
    out.append("")
    out.append("── 速率（根/天，间隔归一，GAP 剔除）")
    rows = [("全期", w["full"]), ("近%dd" % WIN_LONG_DAYS, w["long"]),
            ("近%dd" % WIN_SHORT_DAYS, w["short"])]
    for label, p in rows:
        if p["rate"] is None:
            out.append("  %-8s 观测 0 天 — 统计拒绝（DECLINE）" % label)
            thin_stats = True
            continue
        out.append("  %-8s %s 根/天（%d 根 / %d 观测天，%d 对）"
                   % (label, rate_s(p["rate"]), p["counts"], p["days"],
                      p["n"]))
    if w["base"] is not None:
        base = w["base"]
        out.append("  基线     %s 根/天（账本头 %d 天中位对率）"
                   % (rate_s(base), BASE_WINDOW_DAYS))
        rel = "ELEVATED（>基线×%.2f）" % ELEVATE_LINE \
            if w["short"]["rate"] and w["short"]["rate"] > base * ELEVATE_LINE + EPS \
            else "相对基线平稳（≤基线×%.2f）" % ELEVATE_LINE
        if w["short"]["rate"]:
            out.append("  相对判级 %s — 近窗/基线 = %s"
                       % (rel, "%.2f" % (w["short"]["rate"] / base)))
    else:
        out.append("  基线     不足 %d 对 — 不装知道自己的基线"
                   % MIN_BASE_PAIRS)
    out.append("")
    out.append("── 判级（绝对先验线：OK ≤ %.0f < SHED ≤ %.0f < FLOOD；"
               "洗头计数是样本，绝对线只是通识垫底）"
               % (SHED_LINE, FLOOD_LINE))
    tiers = {}
    thin_stats = False
    for label, p in rows:
        t = abs_tier(p["rate"])
        tiers[label] = t
        if p["rate"] is None:
            thin_stats = True
            continue
        out.append("  %-8s %-6s %s 根/天" % (label, t, rate_s(p["rate"])))
    red_tier = tiers["近%dd" % WIN_SHORT_DAYS]
    out.append("")
    out.append("── 干预事件时间线")
    if not ld["events"]:
        out.append("  （无）")
    for ev in ld["events"]:
        lag = lag_of(ev["drug"], args.lag)
        if ev["verb"] == "start":
            lag_s = "%dd" % lag if lag is not None else "未知（--lag 可翻案）"
            out.append("  %s %-5s %-14s 起效潜伏窗 %s%s"
                       % (ev["date"].isoformat(),
                          {"start": "开始", "stop": "停用"}[ev["verb"]],
                          ev["drug"], lag_s,
                          (" · " + ev["note"]) if ev["note"] else ""))
        else:
            out.append("  %s %-5s %-14s 反弹延迟 %dd%s"
                       % (ev["date"].isoformat(), "停用", ev["drug"],
                          REBOUND_LAG_DAYS,
                          (" · " + ev["note"]) if ev["note"] else ""))
    out.append("")
    out.append("── 近30天现状")
    if red_tier == "FLOOD":
        out.append("  FLOOD %s 根/天 — 超急性线（>%.0f）：急性休止期脱发量级，"
                   "灯文指向皮肤科就诊" % (rate_s(w["short"]["rate"]),
                                          FLOOD_LINE))
    elif red_tier == "SHED":
        out.append("  SHED %s 根/天 — 超生理先验线（>%.0f）：把这张纸带去"
                   "下一次就诊，账本不鉴别 AGA 与休止期脱发"
                   % (rate_s(w["short"]["rate"]), SHED_LINE))
    elif red_tier == "OK":
        out.append("  OK %s 根/天 — 生理先验线内" % rate_s(w["short"]["rate"]))
    else:
        out.append("  统计拒绝（DECLINE）— 近窗观测不足")
    out.append("  换不换药、停不停药、约不约诊，永远是人和医生的决定。")
    text = "\n".join(out)
    print(text)
    if red_tier in ("SHED", "FLOOD"):
        return EXIT_RED
    if thin_stats:
        return EXIT_THIN
    return EXIT_OK


def cmd_rate(path, args):
    ld = load_ledger(path, args.as_of)
    name = os.path.basename(path)
    out = ["秋毫 · Shed Count rate — %s" % name,
           "as-of %s · GAP 线 %dd（间隔超线剔除，那几天没有观测）"
           % (ld["as_of"].isoformat(), args.gap_cap)]
    thin = False
    for kind in ("wash", "comb"):
        rows = ld["kinds"][kind]
        pairs = build_pairs(rows, args.gap_cap)
        out.append("")
        out.append("── %s（%d 行，%d 对）" % (kind, len(rows), len(pairs)))
        if not rows:
            out.append("  （无）")
            continue
        out.append("  date        count  gap  根/天   tags")
        for p in pairs:
            out.append("  %s  %5d  %4d  %6s   %s"
                       % (p["date"].isoformat(), p["count"], p["gap"],
                          rate_s(p["rate"]), "/".join(p["tags"])))
        w = _windows(ld, pairs, args.gap_cap)
        for label, key in (("全期", "full"),
                           ("近%dd" % WIN_LONG_DAYS, "long"),
                           ("近%dd" % WIN_SHORT_DAYS, "short")):
            p = w[key]
            if p["rate"] is None:
                out.append("  %-8s 池化 — 观测 0 天（DECLINE）" % label)
                thin = True
                continue
            out.append("  %-8s 池化 %s 根/天（%d 根 / %d 天，%d 对）"
                       % (label, rate_s(p["rate"]), p["counts"],
                          p["days"], p["n"]))
        if kind == "wash":
            base = w["base"]
            if base is not None:
                out.append("  基线 %s 根/天（头 %d 天中位对率）"
                           % (rate_s(base), BASE_WINDOW_DAYS))
            else:
                out.append("  基线 不足样本 — DECLINE")
                thin = True
    if ld["other_kinds"]:
        out.append("")
        out.append("── 表外口径（点名，不入任何统计——没有先验就不换算）")
        for k in sorted(ld["other_kinds"]):
            ds = ld["other_kinds"][k]
            out.append("  %s × %d 行（%s …）" % (k, len(ds),
                                                 ds[0].isoformat()))
    print("\n".join(out))
    if not ld["kinds"]["wash"] or \
            len(build_pairs(ld["kinds"]["wash"], args.gap_cap)) == 0:
        return EXIT_THIN
    return EXIT_THIN if thin else EXIT_OK


def cmd_intervention(path, args):
    ld = load_ledger(path, args.as_of)
    pairs = build_pairs(ld["kinds"]["wash"], args.gap_cap)
    name = os.path.basename(path)
    out = ["秋毫 · Shed Count intervention — %s" % name,
           "as-of %s · 窗宽 %dd · 起效潜伏窗为先验（folk），--lag 可翻案"
           % (ld["as_of"].isoformat(), SPAN_DAYS)]
    if not ld["events"]:
        print("\n".join(out + ["", "（账本里没有干预事件）"]))
        return EXIT_OK

    def in_span(ev_date, lo, hi):
        return lo <= ev_date <= hi

    thin_any = False
    verdicts = []
    for ev in ld["events"]:
        d = ev["date"]
        lag = lag_of(ev["drug"], args.lag)
        flags = []
        verdict = None
        detail = ""
        if ev["verb"] == "start":
            out.append("")
            out.append("── %s 开始 %s" % (d.isoformat(), ev["drug"]))
            if lag is None:
                flags.append("LAG-UNKNOWN")
            else:
                b_lo = d - dt.timedelta(days=SPAN_DAYS)
                b_hi = d - dt.timedelta(days=1)
                a_lo = d + dt.timedelta(days=lag)
                a_hi = a_lo + dt.timedelta(days=SPAN_DAYS - 1)
                before = pool(pairs, lo=b_lo, hi=b_hi)
                after = pool(pairs, lo=a_lo, hi=a_hi)
                # 同药事件窗内越场：before 里有同药 start（基线不干净）
                # 或 after 里有同药 stop（药没全程在场）→ 判决作废
                for other in ld["events"]:
                    if other is ev:
                        continue
                    if other["drug"] == ev["drug"]:
                        if other["verb"] == "start" and \
                                in_span(other["date"], b_lo, b_hi):
                            flags.append("VOID before 窗含同药 start（基线不干净）")
                        if other["verb"] == "stop" and \
                                in_span(other["date"], d, a_hi):
                            flags.append("VOID after 窗含同药 stop（药未全程在场）")
                    else:
                        # 混杂判定覆盖 before 窗 ∪ [事件日, after 窗尾]——
                        # 联合用药常在潜伏期内开始，只扫两个窗会漏掉它
                        if in_span(other["date"], b_lo, b_hi) or \
                                in_span(other["date"], d, a_hi):
                            flags.append("CONFOUNDED 窗含 %s %s"
                                         % (other["verb"], other["drug"]))
                out.append("  before %s..%s：%s 根/天（%d 根/%d 天，%d 对）"
                           % (b_lo.isoformat(), b_hi.isoformat(),
                              rate_s(before["rate"]) if before["rate"]
                              else "—", before["counts"], before["days"],
                              before["n"]))
                out.append("  after  %s..%s：%s 根/天（%d 根/%d 天，%d 对）"
                           "  潜伏窗 %dd"
                           % (a_lo.isoformat(), a_hi.isoformat(),
                              rate_s(after["rate"]) if after["rate"]
                              else "—", after["counts"], after["days"],
                              after["n"], lag))
                if before["n"] < 2 or after["n"] < 2:
                    verdict = "INSUFFICIENT-WINDOW"
                    thin_any = True
                elif before["rate"] is None or after["rate"] is None:
                    verdict = "INSUFFICIENT-WINDOW"
                    thin_any = True
                else:
                    drop = 1.0 - after["rate"] / before["rate"]
                    rise = after["rate"] / before["rate"] - 1.0
                    if drop >= RESPOND_LINE - EPS:
                        verdict = "RESPONDING"
                    elif rise > WORSE_LINE + EPS:
                        verdict = "WORSE"
                    else:
                        verdict = "NO-CHANGE"
                    detail = "drop %s（响应线 %.0f%% / 恶化线 %.0f%%）" \
                        % (pct(drop), RESPOND_LINE * 100,
                           WORSE_LINE * 100)
        else:  # stop
            out.append("")
            out.append("── %s 停用 %s（反弹庭）" % (d.isoformat(), ev["drug"]))
            b_lo = d - dt.timedelta(days=SPAN_DAYS)
            b_hi = d - dt.timedelta(days=1)
            a_lo = d + dt.timedelta(days=REBOUND_LAG_DAYS)
            a_hi = a_lo + dt.timedelta(days=SPAN_DAYS - 1)
            before = pool(pairs, lo=b_lo, hi=b_hi)
            after = pool(pairs, lo=a_lo, hi=a_hi)
            for other in ld["events"]:
                if other is ev:
                    continue
                if other["drug"] == ev["drug"] and other["verb"] == "start" \
                        and in_span(other["date"], d, a_hi):
                    flags.append("VOID after 窗含同药 start（已复用，反弹不可读）")
                elif other["drug"] != ev["drug"] and \
                        (in_span(other["date"], b_lo, b_hi) or
                         in_span(other["date"], d, a_hi)):
                    flags.append("CONFOUNDED 窗含 %s %s"
                                 % (other["verb"], other["drug"]))
            out.append("  on-treatment %s..%s：%s 根/天（%d 根/%d 天，%d 对）"
                       % (b_lo.isoformat(), b_hi.isoformat(),
                          rate_s(before["rate"]) if before["rate"] else "—",
                          before["counts"], before["days"], before["n"]))
            out.append("  after        %s..%s：%s 根/天（%d 根/%d 天，%d 对）"
                       "  延迟 %dd"
                       % (a_lo.isoformat(), a_hi.isoformat(),
                          rate_s(after["rate"]) if after["rate"] else "—",
                          after["counts"], after["days"], after["n"],
                          REBOUND_LAG_DAYS))
            if before["n"] < 2 or after["n"] < 2 or \
                    before["rate"] is None or after["rate"] is None:
                verdict = "INSUFFICIENT-WINDOW"
                thin_any = True
            else:
                rise = after["rate"] / before["rate"] - 1.0
                verdict = "REBOUND" if rise > REBOUND_LINE + EPS \
                    else "NO-CHANGE"
                detail = "rise %s（反弹线 %.0f%%，恰线不亮）" \
                    % (pct(rise), REBOUND_LINE * 100)
        if flags:
            verdict = "VOID" if any(f.startswith("VOID") for f in flags) \
                else verdict
            if any(f.startswith("LAG-UNKNOWN") for f in flags) and \
                    verdict not in ("VOID",):
                verdict = verdict or "LAG-UNKNOWN"
        verdicts.append(verdict)
        tag_s = ("　".join(flags)) if flags else ""
        if verdict == "VOID":
            line = "  判决 VOID — " + "；".join(
                f.split(" ", 1)[1] if " " in f else f for f in flags
                if f.startswith("VOID"))
            out.append(line)
            conf = [f for f in flags if f.startswith("CONFOUNDED")]
            if conf:
                out.append("  " + "；".join(conf))
        else:
            out.append("  判决 %s（%s）%s"
                       % (verdict, VERDICT_ZH.get(verdict, ""),
                          (detail + ("　" + tag_s if tag_s else ""))
                          if detail else tag_s))
    print("\n".join(out))
    if any(v == "VOID" for v in verdicts):
        return EXIT_OK          # VOID 是诚实，不是账坏；算术照出
    if thin_any:
        return EXIT_THIN
    return EXIT_OK


def cmd_season(path, args):
    ld = load_ledger(path, args.as_of)
    pairs = build_pairs(ld["kinds"]["wash"], args.gap_cap)
    name = os.path.basename(path)
    out = ["秋毫 · Shed Count season — %s" % name,
           "as-of %s · 秋季换发季先验=%s（--season-months 可翻案；"
           "标注不豁免判级）" % (ld["as_of"].isoformat(),
                                "/".join(str(m) for m in SEASON_MONTHS))]
    months = {}
    for p in pairs:
        if "GAP" in p["tags"]:
            continue
        months.setdefault((p["date"].year, p["date"].month), []).append(p)
    keys = sorted(months)
    if len(keys) < 2:
        print("\n".join(out + ["", "统计拒绝（DECLINE）— 不足两个自然月"]))
        return EXIT_THIN
    out.append("")
    out.append("  年-月   根/天     根数/观测天  对数  季节签")
    for k in keys:
        p = pool(months[k])
        tag = "SEASON" if k[1] in SEASON_MONTHS else ""
        out.append("  %d-%02d  %7s   %5d/%5d   %3d   %s"
                   % (k[0], k[1], rate_s(p["rate"]), p["counts"],
                      p["days"], p["n"], tag))
    out.append("")
    by_month = {}
    for k in keys:
        by_month.setdefault(k[1], []).append(k)
    yoy_any = False
    for m in sorted(by_month):
        ys = sorted(k[0] for k in by_month[m])
        if len(ys) < 2:
            continue
        a = pool(months[(ys[0], m)])
        b = pool(months[(ys[-1], m)])
        d = b["rate"] / a["rate"] - 1.0
        out.append("  同月同比 %02d 月：%d %s → %d %s（%s%s）"
                   % (m, ys[0], rate_s(a["rate"]), ys[-1],
                      rate_s(b["rate"]),
                      "+" if d >= 0 else "", pct(d)))
        yoy_any = True
    if not yoy_any:
        out.append("  跨年同月不足 — 无同比（季节背不背锅，满一年再开庭）")
    print("\n".join(out))
    return EXIT_OK


def cmd_validate(path, args):
    ld = load_ledger(path, args.as_of)
    name = os.path.basename(path)
    out = ["秋毫 · Shed Count validate — %s" % name,
           "as-of %s" % ld["as_of"].isoformat()]
    fails = []
    ok = lambda label: out.append("  ✓ %s" % label)
    bad = lambda label: (fails.append(label), out.append("  ✗ %s" % label))

    pairs = build_pairs(ld["kinds"]["wash"], args.gap_cap)

    # 1 间隔双算法：timedelta == 儒略日序数
    try:
        for p in pairs:
            assert gap_days(p["date"], p["prev"]) == \
                gap_days_alt(p["date"], p["prev"])
        ok("间隔双算法 timedelta==ordinal × %d 对" % len(pairs))
    except AssertionError:
        bad("间隔双算法不一致")

    # 2 池化双算法：逐对累加 == 过滤一次求和
    try:
        for lo, hi in ((None, None), (ld["as_of"] - dt.timedelta(days=89),
                                      ld["as_of"]),
                       (ld["as_of"] - dt.timedelta(days=29),
                        ld["as_of"])):
            a = pool(pairs, lo=lo, hi=hi)
            b = pool_alt(pairs, lo=lo, hi=hi)
            assert a["counts"] == b["counts"] and a["days"] == b["days"]
            assert (a["rate"] is None) == (b["rate"] is None)
            if a["rate"] is not None:
                assert abs(a["rate"] - b["rate"]) < 1e-12
        ok("池化双算法 累加==过滤求和 × 3 窗")
    except AssertionError:
        bad("池化双算法不一致")

    # 3 窗分解恒等：全期池 == Σ入池对；且 Σ全部对根数 == Σ第2行起根数
    #   （配对完整性——GAP 对不进池，但其根数仍属于配对完整性恒等式）
    try:
        inc = [p for p in pairs if "GAP" not in p["tags"]]
        assert sum(p["count"] for p in inc) == pool(pairs)["counts"]
        assert sum(p["count"] for p in pairs) == \
            sum(r["count"] for r in ld["kinds"]["wash"][1:])
        ok("窗分解恒等 池==Σ入池对；配对完整 Σ对==Σ行（GAP 只出池不出账）")
    except AssertionError:
        bad("窗分解恒等不成立")

    # 4 GAP 剔除完备：入池对 gap ≤ cap；被剔对全部 > cap
    try:
        cap = args.gap_cap
        assert all(p["gap"] <= cap for p in pairs if "GAP" not in p["tags"])
        assert all(p["gap"] > cap for p in pairs if "GAP" in p["tags"])
        ok("GAP 剔除完备（含边界：恰 %dd 入池）" % cap)
    except AssertionError:
        bad("GAP 剔除不完备")

    # 5 口径门：每行数据恰好落入一个口径桶（wash/comb/表外），不重不漏；
    #   表外口径永不进入 wash/comb 统计（没有先验就不换算）
    try:
        raw_rows = read_tsv(path)
        data_rows = [r for r in raw_rows if (r.get("kind") or "").strip()]
        bucketed = len(ld["kinds"]["wash"]) + len(ld["kinds"]["comb"]) + \
            sum(len(v) for v in ld["other_kinds"].values())
        assert bucketed == len(data_rows)
        for r in data_rows:
            k = canon_kind(r.get("kind"))
            assert (k in ld["kinds"]) or (k in ld["other_kinds"])
        cp = build_pairs(ld["kinds"]["comb"], args.gap_cap)
        ok("口径门 %d 数据行不重不漏（wash %d + comb %d + 表外 %d）；"
           "comb %d 对独立统计，永不混算"
           % (len(data_rows), len(ld["kinds"]["wash"]),
              len(ld["kinds"]["comb"]),
              sum(len(v) for v in ld["other_kinds"].values()), len(cp)))
    except AssertionError:
        bad("口径门被击穿")

    # 6 别名幂等：canon(canon(x)) == canon(x)
    try:
        for raw_k in ("wash", "洗头", "洗发", "60秒", "comb"):
            assert canon_kind(canon_kind(raw_k)) == canon_kind(raw_k)
        for raw_e in ("start minoxidil", "开始米诺地尔", "停非那雄胺"):
            v, dg = parse_event(raw_e)
            v2, dg2 = parse_event("%s %s" % (v, dg))
            assert (v, dg) == (v2, dg2)
        ok("别名归一幂等（口径/动词/药名）")
    except (AssertionError, LedgerError):
        bad("别名归一不幂等")

    # 7 事件完备：动词合法、药名入表或点名
    try:
        unknown = [e for e in ld["events"] if e["drug"] not in LAG_PRIORS]
        assert all(e["verb"] in VERB_ALIASES for e in ld["events"])
        ok("事件完备 %d 起（%s）"
           % (len(ld["events"]),
              ("表外药名点名: " + ",".join(e["drug"] for e in unknown))
              if unknown else "全部药名在先验表内"))
    except AssertionError:
        bad("事件动词损坏")

    # 8 判级恰线行为（先验线由参数钉死）
    try:
        assert abs_tier(SHED_LINE) == "OK"          # 恰线=OK 宁可少亮灯
        assert abs_tier(SHED_LINE + 1e-6) == "SHED"
        assert abs_tier(FLOOD_LINE) == "SHED"
        assert abs_tier(FLOOD_LINE + 1e-6) == "FLOOD"
        ok("判级恰线：恰 %.0f=OK · 恰 %.0f=SHED（宁可少亮灯）"
           % (SHED_LINE, FLOOD_LINE))
    except AssertionError:
        bad("判级恰线行为损坏")

    # 9 as-of 确定性：账本最大日期与 +1 天同一本账读数一致
    try:
        ld2 = load_ledger(path, ld["max_date"] + dt.timedelta(days=1))
        p2 = build_pairs(ld2["kinds"]["wash"], args.gap_cap)
        assert [(p["date"], p["count"], p["gap"]) for p in pairs] == \
            [(p["date"], p["count"], p["gap"]) for p in p2]
        ok("as-of 确定性：max 与 max+1 读数逐字节同源")
    except AssertionError:
        bad("as-of 确定性破坏")

    # 10 观测覆盖率 ≤ 1
    try:
        span = (ld["max_date"] - ld["min_date"]).days + 1
        assert pool(pairs)["days"] <= span
        ok("分母守恒 观测天 %d ≤ 跨度 %d" % (pool(pairs)["days"], span))
    except (AssertionError, TypeError):
        bad("分母守恒不成立")

    print("\n".join(out))
    if fails:
        raise LedgerError("validate failed: %s" % "; ".join(fails))
    return EXIT_OK


# ------------------------------------------------------------ main
def build_parser():
    p = argparse.ArgumentParser(
        prog="shed_count", description="秋毫 · Shed Count — 脱发对账账本")
    p.add_argument("command",
                   choices=["report", "rate", "intervention", "season",
                            "validate"])
    p.add_argument("ledger", help="TSV 账本路径")
    p.add_argument("--as-of", type=parse_date, default=None,
                   help="截断回放日（缺省=账本最大日期）")
    p.add_argument("--shed-line", type=float, default=SHED_LINE)
    p.add_argument("--flood-line", type=float, default=FLOOD_LINE)
    p.add_argument("--elevate-line", type=float, default=ELEVATE_LINE)
    p.add_argument("--gap-cap", type=int, default=GAP_CAP_DAYS)
    p.add_argument("--base-window", type=int, default=BASE_WINDOW_DAYS)
    p.add_argument("--respond-line", type=float, default=RESPOND_LINE)
    p.add_argument("--worse-line", type=float, default=WORSE_LINE)
    p.add_argument("--rebound-line", type=float, default=REBOUND_LINE)
    p.add_argument("--rebound-lag", type=int, default=REBOUND_LAG_DAYS)
    p.add_argument("--lag", action="append", default=[],
                   metavar="DRUG=DAYS", help="起效潜伏窗翻案，可重复")
    p.add_argument("--season-months", default=",".join(
        str(m) for m in SEASON_MONTHS))
    return p


def apply_overrides(args):
    global SHED_LINE, FLOOD_LINE, ELEVATE_LINE, GAP_CAP_DAYS, \
        BASE_WINDOW_DAYS, RESPOND_LINE, WORSE_LINE, REBOUND_LINE, \
        REBOUND_LAG_DAYS, SEASON_MONTHS
    SHED_LINE = args.shed_line
    FLOOD_LINE = args.flood_line
    ELEVATE_LINE = args.elevate_line
    GAP_CAP_DAYS = args.gap_cap
    BASE_WINDOW_DAYS = args.base_window
    RESPOND_LINE = args.respond_line
    WORSE_LINE = args.worse_line
    REBOUND_LINE = args.rebound_line
    REBOUND_LAG_DAYS = args.rebound_lag
    try:
        SEASON_MONTHS = tuple(int(x) for x in
                              args.season_months.split(",") if x.strip())
    except ValueError:
        raise LedgerError("bad --season-months %r" % args.season_months)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        apply_overrides(args)
        lags = {}
        for spec in args.lag:
            if "=" not in spec:
                raise LedgerError("bad --lag %r (want DRUG=DAYS)" % spec)
            k, v = spec.split("=", 1)
            try:
                lags[canon(k, DRUG_ALIASES, "drug").strip()] = int(v)
            except ValueError:
                raise LedgerError("bad --lag %r (want integer days)" % spec)
        args.lag = lags
        if args.as_of is None:
            # 缺省锚定：账本最大日期（零系统时钟）
            probe = load_ledger(args.ledger, dt.date.max)
            if probe["max_date"] is None:
                raise ThinError("empty ledger")
            args.as_of = probe["max_date"]
        if args.command == "report":
            return cmd_report(args.ledger, args)
        if args.command == "rate":
            return cmd_rate(args.ledger, args)
        if args.command == "intervention":
            return cmd_intervention(args.ledger, args)
        if args.command == "season":
            return cmd_season(args.ledger, args)
        if args.command == "validate":
            return cmd_validate(args.ledger, args)
    except LedgerError as e:
        print("账坏： %s" % e, file=sys.stderr)
        return EXIT_INPUT
    except ThinError as e:
        print("too thin: %s" % e, file=sys.stderr)
        return EXIT_THIN
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
