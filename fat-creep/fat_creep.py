#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缓胖 · Fat Creep

你每天看它，所以你看不见它胖。缓发型肥胖是月尺度的蠕涨（家猫超重率 50%+，
兽医界头号营养疾病），每天低头看永远「看起来正常」——除非有一本把月尺度
显出来的账。本件把毛孩子的三本没人记的账合在一起：

  - 体重蠕涨：全期速率（% 体重/月）判级 CREEP / STEADY，近 90 天窗
    只做加速预警不进判级——蠕涨以全期为准，回头看才看得见；
  - 免疫日历：狂犬年免、猫三联年免、体外驱虫月免、体内驱虫三月免……
    品目周期是常识先验，医院说的永远赢（--interval 覆盖）；
    账本里从没出现的品目亮 NEVER-SEEN——没有记录不等于没有打，
    但等于没法管；
  - 铲屎官年账：开销分类年化，「吃穷了」多半是幻觉——医疗才是大头；
  - 减肥投影：按安全速率（默认每周 1% 体重）从当前到目标的日期，
    --deadline 催出来的猛减会被拦下——猫肝脂沉积症等不起，
    本件不鼓励更瘦，它拦猛减。

零依赖（Python 3.8+ 标准库），账本自锚定：缺省 as-of = 两本账最大日期，
--as-of 钉死；同一本账任何机器任何一天跑出的结果逐字节一致。
报告只打印账本 basename，绝不回显调用方路径。

Exit codes: 0 绿 · 2 账本损坏 · 3 样本太薄拒绝判级 · 4 红灯
"""

import argparse
import datetime
import math
import os
import re
import sys

EXIT_OK = 0
EXIT_LEDGER = 2
EXIT_THIN = 3
EXIT_RED = 4

# ---- 判级先验（全部可调） ----
CREEP_LINE = 1.0        # 蠕涨红线：% 体重/月（全期口径）
WARN90_LINE = 1.0       # 近 90 天窗加速预警线（不进判级不进 exit）
THIN_MIN_N = 3          # 称重 < 3 次 → 判级拒绝
THIN_SPAN = 60          # 称重跨度 < 60 天 → 判级拒绝
COST_THIN_DAYS = 30     # 开销覆盖 < 30 天 → 年化/月化拒绝
DUE_SOON = 14           # 剩余 ≤ 14 天 → DUE-SOON
JUMP_PCT = 10.0         # 相邻称重单日跳变 > 10% → 账坏（数学不可能）
UNIT_PCT = 50.0         # 偏离该宠中位 > 50% → 疑似 kg/lb 混录
DIET_RATE = 1.0         # 减肥安全速率默认：每周 1% 体重
DIET_MAX = 2.0          # 减肥硬红线：每周 > 2% 体重 exit 4（猫肝脂风险）
DAYS_PER_MONTH = 30.0

# ---- 护理品目周期表（常识先验，--interval 品目=天数 覆盖，医院说的永远赢） ----
# species: cat/dog/both —— 用于 NEVER-SEEN 的物种感知点名
# 只管预防医疗：疫苗/驱虫/体检。美容是消费不是医疗，走 cost 行。
CARE_ITEMS = {
    "vaccine_rabies": ("狂犬疫苗", "both", 365, ["狂犬", "狂犬疫苗", "狂犬针", "rabies"]),
    "vaccine_fvrhc": ("猫三联", "cat", 365, ["猫三联", "三联", "猫疫苗", "妙三多", "fvrhc"]),
    "vaccine_dhpp": ("犬四联/八联", "dog", 365, ["犬四联", "四联", "八联", "六联", "犬疫苗", "狗疫苗", "卫佳", "dhpp"]),
    "deworm_ext": ("体外驱虫", "both", 30, ["体外驱虫", "外驱", "体外", "滴剂", "大宠爱", "福来恩", "deworm_ext", "flea"]),
    "deworm_int": ("体内驱虫", "both", 90, ["体内驱虫", "内驱", "体内", "打虫", "驱虫药", "拜宠清", "犬心保", "deworm_int"]),
    "checkup": ("体检", "both", 365, ["体检", "年检", "健康检查", "checkup", "check-up"]),
}

# ---- 开销分类关键词（按序命中；处方优先于粮——处方是医疗不是伙食） ----
COST_RULES = [
    ("medical", ["处方", "住院", "手术", "门诊", "治疗", "化验", "拍片", "b超", "B超", "输液", "绝育", "疫苗", "驱虫", "体检", "挂号"]),
    ("groom", ["洗澡", "美容", "剪毛", "修毛", "groom"]),
    ("supply", ["猫砂", "尿垫", "尿片", "玩具", "牵引", "胸背", "项圈", "笼", "碗", "梳", "猫抓板", "猫窝", "狗窝", "用品"]),
    ("food", ["粮", "罐头", "冻干", "零食", "肉条", "主食", "营养膏", "羊奶粉", "鸡胸", "food"]),
]


def norm(s):
    """归一：小写、折叠空白与常见标点（中英别名共用一个归一键）。"""
    s = (s or "").strip().lower()
    s = re.sub(r"[\s\-_/·.,，。：:；;（）()【】\[\]#'!？?！]+", "", s)
    return s


# 归一键 → 品目 key（构建一次）
_ALIAS = {}
for _k, (_zh, _sp, _d, _al) in CARE_ITEMS.items():
    for _a in _al + [_zh]:
        _ALIAS[norm(_a)] = _k
    _ALIAS[norm(_k)] = _k

_KIND_ALIAS = {"care": "care", "护理": "care", "免疫": "care",
               "cost": "cost", "开销": "cost", "花费": "cost", "spend": "cost",
               "weight": "weight", "称重": "weight", "体重": "weight", "w": "weight"}


class LedgerError(Exception):
    """账本损坏：exit 2"""


class ThinError(Exception):
    """样本太薄：exit 3（统计判级拒绝；算术事实照常出账）"""


# ---------------- display width（CJK 感知对齐） ----------------

def dw(s):
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def pad(s, width, align="left"):
    s = str(s)
    fill = max(0, width - dw(s))
    return s + " " * fill if align == "left" else " " * fill + s


# ---------------- TSV 解析 ----------------

def read_tsv(path, need_cols):
    if not os.path.exists(path):
        raise LedgerError("file not found: %s" % os.path.basename(path))
    rows, header = [], None
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if header is None:
                header = [c.strip().lower() for c in line.split("\t")]
                missing = [c for c in need_cols if c not in header]
                if missing:
                    raise LedgerError("bad header in %s: missing %s" % (os.path.basename(path), missing))
                continue
            cells = line.split("\t")
            if len(cells) < len(header):
                cells += [""] * (len(header) - len(cells))
            rows.append((lineno, dict(zip(header, [c.strip() for c in cells]))))
    if header is None:
        raise LedgerError("empty ledger: %s" % os.path.basename(path))
    return rows


def parse_date(s, path, lineno):
    s = (s or "").strip()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
    if not m:
        raise LedgerError("bad date %r at %s:%d" % (s, os.path.basename(path), lineno))
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise LedgerError("impossible date %r at %s:%d" % (s, os.path.basename(path), lineno))


def parse_float(s, path, lineno, field):
    try:
        return float(s)
    except (TypeError, ValueError):
        raise LedgerError("bad %s %r at %s:%d" % (field, s, os.path.basename(path), lineno))


def match_item(raw):
    """care 品目归一；未命中返回 None（validate 报错，其他命令当作自由文本跳过）。"""
    n = norm(raw)
    if not n:
        return None
    if n in _ALIAS:
        return _ALIAS[n]
    for alias_key, key in _ALIAS.items():
        if alias_key and alias_key in n:
            return key
    return None


def cost_cat(raw_item):
    """开销分类：cost 行按关键词序命中（处方优先于粮——处方是医疗不是伙食）。"""
    text = raw_item or ""
    for cat, words in COST_RULES:
        for w in words:
            if w in text:
                return cat
    return "other"


# ---------------- 账本载入 ----------------

def load_weights(path, as_of, keep_future=False):
    rows = read_tsv(path, ["date", "pet", "weight_kg"])
    out = []
    for lineno, r in rows:
        d = parse_date(r["date"], path, lineno)
        if as_of is not None and d > as_of and not keep_future:
            continue  # as-of 剪切
        w = parse_float(r["weight_kg"], path, lineno, "weight_kg")
        if w <= 0:
            raise LedgerError("non-positive weight %r at %s:%d" % (r["weight_kg"], os.path.basename(path), lineno))
        pet = r["pet"]
        if not pet:
            raise LedgerError("empty pet at %s:%d" % (os.path.basename(path), lineno))
        out.append((d, pet, w))
    return out


def load_events(path, as_of, keep_future=False):
    rows = read_tsv(path, ["date", "pet", "kind", "item"])
    care, cost = [], []
    for lineno, r in rows:
        d = parse_date(r["date"], path, lineno)
        if as_of is not None and d > as_of and not keep_future:
            continue
        kind = _KIND_ALIAS.get(norm(r["kind"]))
        if kind is None:
            raise LedgerError("unknown kind %r at %s:%d (care/cost/weight)" % (r["kind"], os.path.basename(path), lineno))
        pet = r["pet"]
        if not pet:
            raise LedgerError("empty pet at %s:%d" % (os.path.basename(path), lineno))
        raw_item = r["item"]
        amt = None
        if r.get("amount"):
            amt = parse_float(r["amount"], path, lineno, "amount")
            if amt < 0:
                raise LedgerError("negative amount at %s:%d" % (os.path.basename(path), lineno))
        if kind == "care":
            key = match_item(raw_item)
            if key is None:
                raise LedgerError("unknown care item %r at %s:%d (add it to --interval or use kind=cost)" % (raw_item, os.path.basename(path), lineno))
            care.append((d, pet, key, amt))
        elif kind == "cost":
            cost.append((d, pet, cost_cat(raw_item), amt if amt is not None else 0.0))
        # kind == weight 允许写进 events（容错），忽略
    return care, cost


def ledger_as_of(args, wpath, epath):
    if args.as_of:
        return parse_date(args.as_of, "args", 0)
    latest = None
    for path in (wpath, epath):
        for lineno, r in read_tsv(path, []):
            d = parse_date(r.get("date", ""), path, lineno)
            if latest is None or d > latest:
                latest = d
    if latest is None:
        raise LedgerError("both ledgers empty")
    return latest


# ---------------- 体重蠕涨 ----------------

def pet_weight_stats(weights, pet, as_of):
    ws = sorted((d, w) for d, p, w in weights if p == pet)
    return ws


def rate_of(pairs):
    """首尾窗速率：(末−首)/跨度天数×30 → (kg/月, %最新体重/月)。"""
    d0, w0 = pairs[0]
    d1, w1 = pairs[-1]
    span = (d1 - d0).days
    if span <= 0:
        return 0.0, 0.0, span
    kg_mo = (w1 - w0) / span * DAYS_PER_MONTH
    pct = kg_mo / w1 * 100 if w1 else 0.0
    return kg_mo, pct, span


def creep_rows(weights, as_of, creep_line=CREEP_LINE):
    """每宠：(pet, latest_d, latest_w, n, span, kg_mo, pct, pct90, verdict, decline_reason)"""
    pets = sorted({p for _, p, _ in weights})
    rows = []
    for pet in pets:
        ws = pet_weight_stats(weights, pet, as_of)
        if not ws:
            continue
        d_last, w_last = ws[-1]
        kg_mo, pct, span = rate_of(ws)
        pct90 = None
        win = [(d, w) for d, w in ws if d > as_of - datetime.timedelta(days=90)]
        if len(win) >= 2 and (win[-1][0] - win[0][0]).days > 0:
            pct90 = rate_of(win)[1]
        reason = None
        if len(ws) < THIN_MIN_N or span < THIN_SPAN:
            reason = "thin(<%d obs or <%dd)" % (THIN_MIN_N, THIN_SPAN)
            verdict = "DECLINE"
        elif pct > creep_line:
            verdict = "CREEP"
        else:
            verdict = "STEADY"
        rows.append(dict(pet=pet, d=d_last, w=w_last, n=len(ws), span=span,
                         kg_mo=kg_mo, pct=pct, pct90=pct90, verdict=verdict, reason=reason))
    return rows


def cmd_trend(args):
    as_of = ledger_as_of(args, args.weights, args.events)
    weights = load_weights(args.weights, as_of)
    if not weights:
        raise ThinError("no weight rows on or before as-of")
    line = CREEP_LINE if args.creep_line is None else args.creep_line
    rows = creep_rows(weights, as_of, creep_line=line)
    if args.pet:
        rows = [r for r in rows if r["pet"] == args.pet]
    print("== fat-creep trend (weights) ==")
    print("ledger: %s + %s" % (os.path.basename(args.weights), os.path.basename(args.events)))
    print("as-of: %s%s | creep line: %.1f%%/mo | verdict uses FULL span; 90d is acceleration preview only" % (
        as_of.isoformat(), " (pinned)" if args.as_of else " (ledger-anchored)", line))
    hdr = ["pet", "latest(kg)", "as-of-d", "n", "span_d", "kg/mo", "%/mo", "90d-%/mo", "verdict"]
    print(pad(hdr[0], 10) + pad(hdr[1], 11) + pad(hdr[2], 8) + pad(hdr[3], 4) + pad(hdr[4], 7) +
          pad(hdr[5], 8) + pad(hdr[6], 7) + pad(hdr[7], 10) + hdr[8])
    red = False
    thin = False
    for r in rows:
        print(pad(r["pet"], 10) + pad("%s %s" % (("%.2f" % r["w"]), r["d"].strftime("%m-%d")), 11) +
              pad((as_of - r["d"]).days, 8) + pad(r["n"], 4) + pad(r["span"], 7) +
              pad("%+.4f" % r["kg_mo"], 8) + pad("%+.2f" % r["pct"], 7) +
              pad("n/a" if r["pct90"] is None else "%+.2f" % r["pct90"], 10) +
              (r["verdict"] if r["reason"] is None else "%s (%s)" % (r["verdict"], r["reason"])))
        if r["verdict"] == "CREEP":
            red = True
        if r["verdict"] == "DECLINE":
            thin = True
    if thin:
        print("NOTE: DECLINE = statistics refused (thin ledger). Raw rate still printed; arithmetic is not gated.")
    creeped = [r["pet"] for r in rows if r["verdict"] == "CREEP"]
    if creeped:
        print("RED: %s is creeping at full-span rate. You look at it every day; the month-scale needs this ledger." % ", ".join(creeped))
        return EXIT_RED
    return EXIT_OK


# ---------------- 免疫日历 ----------------

def infer_species(care):
    """物种 = 该宠 care 品目的物种证据并集；无记录 → unknown。"""
    ev = {}
    for d, pet, key, amt in care:
        ev.setdefault(pet, set()).add(key)
    out = {}
    for pet, keys in ev.items():
        sp = set()
        for k in keys:
            s = CARE_ITEMS[k][1]
            if s != "both":
                sp.add(s)
        out[pet] = sp.pop() if len(sp) == 1 else ("mixed" if len(sp) > 1 else "unknown")
    return out


def due_rows(care, intervals, as_of):
    """每宠每品目：last, next, remaining, status ∈ OVERDUE/DUE-TODAY/DUE-SOON/OK。"""
    last = {}
    for d, pet, key, amt in care:
        cur = last.get((pet, key))
        if cur is None or d > cur:
            last[(pet, key)] = d
    species = infer_species(care)
    rows = []
    for (pet, key), d_last in sorted(last.items()):
        days = intervals.get(key, CARE_ITEMS[key][2])
        nxt = d_last + datetime.timedelta(days=days)
        rem = (nxt - as_of).days
        if rem < 0:
            st = "OVERDUE"
        elif rem == 0:
            st = "DUE-TODAY"
        elif rem <= DUE_SOON:
            st = "DUE-SOON"
        else:
            st = "OK"
        rows.append(dict(pet=pet, key=key, zh=CARE_ITEMS[key][0], last=d_last,
                         days=days, next=nxt, rem=rem, status=st))
    # NEVER-SEEN：账本里有该宠 care 记录、但该宠从未出现过的同物种品目
    pets = sorted({p for _, p, _, _ in care})
    seen_keys = {}
    for d, pet, key, amt in care:
        seen_keys.setdefault(pet, set()).add(key)
    for pet in pets:
        sp = species.get(pet, "unknown")
        for key, (_zh, item_sp, _d, _al) in sorted(CARE_ITEMS.items()):
            if item_sp != "both" and sp not in (item_sp, "mixed"):
                continue
            if key not in seen_keys.get(pet, set()):
                rows.append(dict(pet=pet, key=key, zh=CARE_ITEMS[key][0], last=None,
                                 days=intervals.get(key, CARE_ITEMS[key][2]), next=None,
                                 rem=None, status="NEVER-SEEN"))
    return rows


def cmd_due(args):
    as_of = ledger_as_of(args, args.weights, args.events)
    care, _cost = load_events(args.events, as_of)
    if not care:
        raise ThinError("no care rows (vaccine/deworm/checkup) in events ledger")
    intervals = {}
    for spec in args.interval or []:
        if "=" not in spec:
            raise LedgerError("bad --interval %r (want 品目=天数, e.g. 体外驱虫=45)" % spec)
        name, _, num = spec.partition("=")
        key = match_item(name)
        if key is None:
            raise LedgerError("unknown item in --interval %r" % spec)
        intervals[key] = parse_float(num, "args", 0, "interval")
    rows = due_rows(care, intervals, as_of)
    if args.pet:
        rows = [r for r in rows if r["pet"] == args.pet]
    print("== fat-creep due (immunization calendar) ==")
    print("ledger: %s + %s" % (os.path.basename(args.weights), os.path.basename(args.events)))
    print("as-of: %s%s | due-soon window: <=%dd | intervals are common-sense priors; the clinic wins (--interval)" % (
        as_of.isoformat(), " (pinned)" if args.as_of else " (ledger-anchored)", DUE_SOON))
    print(pad("pet", 10) + pad("item", 14) + pad("last", 12) + pad("interval", 9) +
          pad("next", 12) + pad("remain_d", 9) + "status")
    red = False
    never = []
    for r in rows:
        print(pad(r["pet"], 10) + pad(r["zh"], 14) +
              pad(r["last"].isoformat() if r["last"] else "-", 12) +
              pad(r["days"], 9) + pad(r["next"].isoformat() if r["next"] else "-", 12) +
              pad(r["rem"] if r["rem"] is not None else "-", 9) + r["status"])
        if r["status"] == "OVERDUE":
            red = True
        if r["status"] == "NEVER-SEEN":
            never.append((r["pet"], r["zh"]))
    if never:
        print("NEVER-SEEN: %s — no record means unmanaged, not un-injected. Fill in what actually happened." %
              "; ".join("%s/%s" % (p, z) for p, z in never))
    overdue = [(r["pet"], r["zh"], r["next"]) for r in rows if r["status"] == "OVERDUE"]
    if overdue:
        print("RED: overdue shots: %s" % "; ".join("%s %s since %s" % (p, z, n.isoformat()) for p, z, n in overdue))
        return EXIT_RED
    return EXIT_OK


# ---------------- 铲屎官年账 ----------------

def cmd_cost(args):
    as_of = ledger_as_of(args, args.weights, args.events)
    care, cost = load_events(args.events, as_of)
    # care 行金额也进开销账（一行两用，不双记）
    entries = [(d, pet, "medical", amt)
               for d, pet, key, amt in care if amt is not None]
    entries += [(d, pet, cat, amt) for d, pet, cat, amt in cost]
    if not entries:
        raise ThinError("no cost rows (and no care rows with amount) in events ledger")
    pets = sorted({p for _, p, _, _ in entries})
    if args.pet:
        pets = [p for p in pets if p == args.pet]
        if not pets:
            raise LedgerError("no cost rows for pet %r" % args.pet)
    total_all = 0.0
    yearly_sum = 0.0
    thin_any = False
    print("== fat-creep cost (the human's annual bill) ==")
    print("ledger: %s + %s" % (os.path.basename(args.weights), os.path.basename(args.events)))
    print("as-of: %s%s | care rows with amount count as spend too (one row, two books, no double-entry)" % (
        as_of.isoformat(), " (pinned)" if args.as_of else " (ledger-anchored)"))
    others = 0
    for d, pet, cat, amt in entries:
        if cat == "other":
            others += 1
    for pet in pets:
        rows = sorted(e for e in entries if e[1] == pet)
        total = sum(a for _, _, _, a in rows)
        first_d = rows[0][0]
        cov = (as_of - first_d).days + 1
        cats = {}
        for d, p, cat, amt in rows:
            cats[cat] = cats.get(cat, 0.0) + amt
        print("\n[%s] total %.2f | first spend %s | coverage %dd" % (pet, total, first_d.isoformat(), cov))
        for cat in ("food", "medical", "supply", "groom", "other"):
            if cat in cats:
                print("  %-8s %10.2f  %5.1f%%" % (cat, cats[cat], cats[cat] / total * 100))
        resid = abs(sum(cats.values()) - total)
        if resid > 1e-9:
            raise LedgerError("category identity broken for %s (residual %g)" % (pet, resid))
        if cov < COST_THIN_DAYS:
            thin_any = True
            print("  DECLINE yearly: coverage %dd < %dd — total still printed, annualization refused." % (cov, COST_THIN_DAYS))
        else:
            monthly = total / cov * DAYS_PER_MONTH
            yearly = monthly * 12
            yearly_sum += round(yearly, 2)
            med = cats.get("medical", 0.0) / total * 100
            top = max(cats, key=lambda c: cats[c])
            print("  monthly %.2f | yearly %.2f | top category: %s (%.1f%%)" % (monthly, yearly, top, cats[top] / total * 100))
            if top == "medical":
                print('  "吃穷了" is a myth: vet care, not food, is the biggest line. Budget for the clinic, not just the bowl.')
        total_all += total
    if others:
        print("UNCATEGORIZED: %d row(s) fell into 'other' — the taxonomy is your skin in the game." % others)
    if len(pets) > 1:
        print("\nALL PETS total %.2f | yearly(sum of pets) %.2f" % (total_all, yearly_sum))
    if thin_any:
        print("THIN: annualization refused for at least one pet (<%dd coverage)." % COST_THIN_DAYS)
        return EXIT_THIN
    return EXIT_OK


# ---------------- 减肥投影 ----------------

def cmd_diet(args):
    as_of = ledger_as_of(args, args.weights, args.events)
    weights = load_weights(args.weights, as_of)
    if not args.pet or args.target is None:
        raise LedgerError("diet needs --pet and --target (kg)")
    ws = pet_weight_stats(weights, args.pet, as_of)
    if not ws:
        raise LedgerError("no weight rows for pet %r" % args.pet)
    cur_d, cur = ws[-1]
    if args.target <= 0:
        raise LedgerError("target must be positive")
    if args.target >= cur:
        print("== fat-creep diet ==")
        print("target %.2f >= current %.2f: nothing to lose, nothing to project." % (args.target, cur))
        return EXIT_OK
    rate = DIET_RATE if args.rate is None else args.rate
    excess = cur - args.target
    wk_grams = cur * rate / 100.0
    raw_weeks = excess / wk_grams
    weeks = int(math.ceil(raw_weeks - 1e-9))
    arrive = as_of + datetime.timedelta(days=weeks * 7)
    print("== fat-creep diet (safe-projection, not a challenge) ==")
    print("pet: %s | current %.2f (%s) | target %.2f | excess %.2f kg" % (args.pet, cur, cur_d.isoformat(), args.target, excess))
    print("safe rate: %.2f%%/wk (= %.4f kg/wk at current weight; prior, adjustable; clinic wins)" % (rate, wk_grams))
    print("projection: %.2f raw-weeks -> %d weeks -> arrive %s" % (raw_weeks, weeks, arrive.isoformat()))
    red = False
    if args.deadline:
        ddl = parse_date(args.deadline, "args", 0)
        days = (ddl - as_of).days
        if days <= 0:
            raise LedgerError("deadline must be after as-of")
        need = excess / (days / 7.0)
        need_pct = need / cur * 100
        print("deadline %s: %dd = %.2f weeks -> needed %.4f kg/wk = %.2f%%/wk" % (ddl.isoformat(), days, days / 7.0, need, need_pct))
        if need_pct > DIET_MAX:
            print("RED: %.2f%%/wk exceeds the %.1f%%/wk hard line. A %d-week job squeezed into %d weeks burns more "
                  "than fat — feline hepatic lipidosis does not negotiate. Move the deadline or shrink the target."
                  % (need_pct, DIET_MAX, weeks, days / 7.0))
            red = True
        else:
            print("OK: needed rate within the hard line (ceil'd plan still fits).")
    print("This tool does not push for thinner; it blocks crash-dieting. Cats must never fast.")
    if red:
        return EXIT_RED
    return EXIT_OK


# ---------------- validate ----------------

def cmd_validate(args):
    as_of = ledger_as_of(args, args.weights, args.events)
    problems = []
    suspects = []
    weights = load_weights(args.weights, as_of, keep_future=True)
    by_pet = {}
    for d, pet, w in weights:
        by_pet.setdefault(pet, []).append((d, w))
    for d, pet, w in weights:
        if d > as_of:
            problems.append("future weight row %s %s (after as-of)" % (pet, d.isoformat()))
    for pet, ws in sorted(by_pet.items()):
        ws.sort()
        med = sorted(w for _, w in ws)[len(ws) // 2]
        for d, w in ws:
            if med and abs(w - med) / med * 100 > UNIT_PCT:
                suspects.append("%s %s %.2f vs median %.2f" % (pet, d.isoformat(), w, med))
        for (d0, w0), (d1, w1) in zip(ws, ws[1:]):
            if d1 == d0:
                problems.append("%s duplicate weight date %s" % (pet, d0.isoformat()))
            elif w0 > 0 and abs(w1 - w0) / w0 * 100 > JUMP_PCT + 1e-9:
                problems.append("%s weight jump %s %.2f -> %s %.2f (%+.1f%%/day, mathematically impossible)" %
                                (pet, d0.isoformat(), w0, d1.isoformat(), w1, (w1 - w0) / w0 * 100))
    care, cost = load_events(args.events, as_of, keep_future=True)
    for d, pet, key, amt in care:
        if d > as_of:
            problems.append("future care row %s %s (after as-of)" % (pet, d.isoformat()))
    for d, pet, cat, amt in cost:
        if d > as_of:
            problems.append("future cost row %s %s (after as-of)" % (pet, d.isoformat()))
    print("== fat-creep validate ==")
    print("ledger: %s + %s | as-of: %s" % (os.path.basename(args.weights), os.path.basename(args.events), as_of.isoformat()))
    for p in problems:
        print("BROKEN: %s" % p)
    for s in suspects:
        print("SUSPECT-UNIT: %s (kg/lb mixup? fix the row, not the code)" % s)
    if not problems and not suspects:
        print("clean: dates, weights, kinds, items, amounts all pass.")
        return EXIT_OK
    if problems:
        return EXIT_LEDGER
    return EXIT_LEDGER


# ---------------- report ----------------

def cmd_report(args):
    as_of = ledger_as_of(args, args.weights, args.events)
    weights = load_weights(args.weights, as_of)
    care, cost = load_events(args.events, as_of)
    rows = creep_rows(weights, as_of)
    if args.pet:
        rows = [r for r in rows if r["pet"] == args.pet]
    print("== fat-creep report ==")
    print("ledger: %s + %s" % (os.path.basename(args.weights), os.path.basename(args.events)))
    print("as-of: %s%s" % (as_of.isoformat(), " (pinned)" if args.as_of else " (ledger-anchored)"))
    if not weights:
        raise ThinError("no weight rows on or before as-of")
    if not care and not cost:
        raise ThinError("no events rows on or before as-of")
    intervals = {}
    for spec in args.interval or []:
        if "=" not in spec:
            raise LedgerError("bad --interval %r" % spec)
        name, _, num = spec.partition("=")
        key = match_item(name)
        if key is None:
            raise LedgerError("unknown item in --interval %r" % spec)
        intervals[key] = parse_float(num, "args", 0, "interval")
    dues = due_rows(care, intervals, as_of) if care else []
    red = False
    for r in rows:
        od = [d for d in dues if d["pet"] == r["pet"] and d["status"] == "OVERDUE"]
        soon = [d for d in dues if d["pet"] == r["pet"] and d["status"] in ("DUE-SOON", "DUE-TODAY")]
        never = [d for d in dues if d["pet"] == r["pet"] and d["status"] == "NEVER-SEEN"]
        print("\n[%s] latest %.2f kg (%s, %dd ago) | n=%d span=%dd" % (
            r["pet"], r["w"], r["d"].isoformat(), (as_of - r["d"]).days, r["n"], r["span"]))
        print("  creep: %+.4f kg/mo = %+.2f%%/mo (90d %s) -> %s%s" % (
            r["kg_mo"], r["pct"], "n/a" if r["pct90"] is None else "%+.2f%%" % r["pct90"],
            r["verdict"], "" if r["reason"] is None else " (%s)" % r["reason"]))
        if od:
            red = True
            print("  due RED: %s" % "; ".join("%s since %s" % (d["zh"], d["next"].isoformat()) for d in od))
        if soon:
            print("  due soon: %s" % "; ".join("%s at %s (%dd)" % (d["zh"], d["next"].isoformat(), d["rem"]) for d in soon))
        if never:
            print("  never seen: %s (no record = unmanaged, not un-injected)" % ", ".join(d["zh"] for d in never))
        if r["verdict"] == "CREEP":
            red = True
        es = [e for e in cost if e[1] == r["pet"]] + [(d, p, "medical", a)
                                                     for d, p, k, a in care if p == r["pet"] and a is not None]
        if es:
            es.sort()
            total = sum(a for _, _, _, a in es)
            cov = (as_of - es[0][0]).days + 1
            if cov >= COST_THIN_DAYS:
                monthly = total / cov * DAYS_PER_MONTH
                print("  spend: %.2f total / %dd -> monthly %.2f, yearly %.2f" % (total, cov, monthly, monthly * 12))
            else:
                print("  spend: %.2f total / %dd (too thin to annualize)" % (total, cov))
    if red:
        print("\nRED present: see CREEP/OVERDUE lines above.")
        return EXIT_RED
    print("\nno red lights: nothing overdue, nobody creeping (thin ledgers still DECLINE, honestly).")
    return EXIT_OK


# ---------------- main ----------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="fat_creep.py", description="缓胖 · Fat Creep — pet health ledger (weights / immunization / spend)")
    ap.add_argument("--as-of", dest="as_of", default=None, help="pin the anchor date (default: ledger-anchored = max date in both ledgers)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("weights", help="weights.tsv (date/pet/weight_kg/note)")
        p.add_argument("events", help="events.tsv (date/pet/kind/item/amount/note)")
        p.add_argument("--pet", default=None, help="filter to one pet")
        p.add_argument("--as-of", dest="as_of_sub", default=None, help="pin the anchor date (works before or after the subcommand)")
        return p

    p = add("report", "overview: latest weights, creep verdicts, due shots, spend")
    p.add_argument("--interval", action="append", default=None, metavar="品目=天数", help="override item interval, clinic wins")
    p = add("trend", "weight creep verdicts (full span + 90d preview)")
    p.add_argument("--creep-line", type=float, default=None, help="creep red line %%/mo (default %.1f)" % CREEP_LINE)
    p = add("due", "immunization calendar with OVERDUE/DUE-SOON/NEVER-SEEN")
    p.add_argument("--interval", action="append", default=None, metavar="品目=天数", help="override item interval, clinic wins")
    add("cost", "annualized spend with category identity")
    p = add("diet", "safe weight-loss projection; blocks crash-dieting")
    p.add_argument("--target", type=float, default=None, help="target weight kg (required)")
    p.add_argument("--rate", type=float, default=None, help="safe rate %%/wk (default %.1f)" % DIET_RATE)
    p.add_argument("--deadline", default=None, help="pin a target date; needed rate over %.1f%%/wk exits 4" % DIET_MAX)
    add("validate", "ledger integrity: dates, jumps, unit mixups, unknown kinds")

    args = ap.parse_args(argv)
    if getattr(args, "as_of_sub", None):
        args.as_of = args.as_of_sub
    try:
        if args.cmd == "report":
            return cmd_report(args)
        if args.cmd == "trend":
            return cmd_trend(args)
        if args.cmd == "due":
            return cmd_due(args)
        if args.cmd == "cost":
            return cmd_cost(args)
        if args.cmd == "diet":
            return cmd_diet(args)
        if args.cmd == "validate":
            return cmd_validate(args)
    except LedgerError as e:
        print("LEDGER BROKEN: %s" % e, file=sys.stderr)
        return EXIT_LEDGER
    except ThinError as e:
        print("STATISTICS REFUSED: %s (arithmetic outputs above are not gated)" % e, file=sys.stderr)
        return EXIT_THIN
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
