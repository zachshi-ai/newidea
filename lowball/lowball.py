#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""低价签 · Lowball — 装修增项审计账本(zero-dependency CLI).

增项不是在结算时发生的,是签合同那一刻就注定的:低价签单是获客手段,
增项是盈利模式——他不是便宜,是分期收款。比价比的是合同价,决定真实
成本的是报价单的完整性:报价单里没有的东西,不是不花钱,是还没开始收。

本件把装修合同抄成两份可手编的 TSV(quote.tsv 报价单 + addons.tsv 增项
流水),对「便宜」开庭:

  audit    增项总账:四分类瀑布(升级/被动/量差/增利)+ 开口爆量 + 宰客单价
  gaps     漏项审计:对照行业常识清单审报价单覆盖,缺失项预估回收价,
           算出低价幻觉指数——「这份 9.3 万的全包,底价从来不是 9.3 万」
  prices   单价对账:增项单价 vs 常识区间,低于下沿 0.85x 是诱饵价,
           高于上沿 1.5x 是宰客价——同一个工地,两套价目表
  judge    签字前裁决一份报价单:漏项 + 幻觉指数 + 诱饵×开口杀局识别
  sign     签字门禁:工长递来的单子先过闸(区间定位/合同对照/分类口诀/
           推荐记账行),签字的手比脑子快,闸门替脑子争取三分钟
  validate 恒等式体检:行级 amount=qty×price、四类加总、开口挂靠

分类恒等式:结算 ≡ 合同 + upgrade + forced + drift + padded。
四种病四种药:升级是预算管理,被动是报价完整性,量差是开口风险,
增利是谈判依据——不分类的增项总额没有意义。

诚实条款:四分类是签字人当场自报的(当场分类本身就是皮肤游戏);
常识区间是先验不是行情,本地价格永远赢(--baselines 覆盖);它不连任何
平台、不猜本地报价、不回答「装修该花多少钱」,它只回答「这份便宜是
怎么炼成的」。签不签、忍不忍、换不换,人的决定。

用法:
  python3 lowball.py audit  examples/quote.tsv examples/addons.tsv
  python3 lowball.py gaps   examples/quote.tsv
  python3 lowball.py judge  examples/quote.tsv
  python3 lowball.py prices examples/quote.tsv examples/addons.tsv
  python3 lowball.py sign   examples/quote.tsv --item 墙面找平 --qty 96 --price 95 --unit 元/㎡
  python3 lowball.py validate examples/quote.tsv examples/addons.tsv

Exit codes: 0 OK · 1 RISKY(越黄线) · 2 账本损坏 · 3 THIN/拒答 · 4 红线
"""

import argparse
import os
import sys

# ---------------------------------------------------------------- 常识基线表
# 先验不是行情:典型一线城市 2026 常识区间,本地价格永远赢(--baselines 覆盖)。
# kind: universal=无条件必含(缺了开工后必回来收钱) conditional=需求触发才需要
# unit: pct=按合同小计比例审计/预估;其余按单价审计、按 typical×中位预估漏项
# typical=0 表示量不可预估(只做单价审计,不进漏项预估)
DEFAULT_BASELINES = [
    # key      aliases                    low    high  unit   cond          typical
    ("拆除",   "拆除|拆墙|切割",           60,    120,  "/㎡", "conditional", 42),
    ("砌墙",   "砌墙|新砌",                100,   160,  "/㎡", "conditional", 18),
    ("水电改造", "水电|水路|电路",          45,    90,   "/m",  "conditional", 280),
    ("防水",   "防水",                     45,    90,   "/㎡", "conditional", 14),
    ("闭水试验", "闭水|蓄水试验",           0,     500,  "/次", "conditional", 2),
    ("找平",   "找平|基层处理|石膏找平",   25,    60,   "/㎡", "conditional", 240),
    ("贴砖",   "贴砖|铺贴|瓦工",           55,    90,   "/㎡", "conditional", 0),
    ("乳胶漆", "乳胶漆|墙漆|油漆",         25,    45,   "/㎡", "conditional", 0),
    ("垃圾清运", "垃圾|渣土|清运",          1500,  3500, "/屋", "universal",   1),
    ("成品保护", "成品保护|保护膜",         600,   1800, "/屋", "universal",   1),
    ("管理费", "管理费",                   0.04,  0.08, "pct",   "universal",   1),
    ("税票",   "税票|税金|开票",           0.03,  0.06, "pct",   "universal",   1),
    ("开荒保洁", "保洁|开荒",              6,     10,   "/㎡", "universal",   89),
    ("搬运上楼", "搬运|上楼|材料运输",      0,     1000, "/屋", "universal",   1),
]

KINDS = ("upgrade", "forced", "drift", "padded")
KIND_LABEL = {
    "upgrade": "签字升级",
    "forced": "被动必做",
    "drift": "开口量差",
    "padded": "行业增利",
}
KIND_NOTE = {
    "upgrade": "你主动要的——预算内选择,无对错",
    "forced": "不做不行——报价单该有而没有的,现在用垄断价收",
    "drift": "单价没宰你,量爆炸了——开口合同把总量留白",
    "padded": "同行默认含,他单收——谈判与换人的依据",
}

BAIT = 0.85       # 单价 < 下沿×BAIT 视为诱饵价
KILL = 1.5        # 单价 > 上沿×KILL 视为宰客价
CAP = 0.30        # 增项率红线
CAP_WARN = 0.24   # 增项率黄线
HALLUCINATION = 0.15  # 低价幻觉指数红线
DRIFT_CAP = 1.5   # 开口爆量红线(final÷est)
UNIVERSAL_GATE = 2    # universal 漏项达到此数 → 红线
THIN_QUOTE = 5    # 报价单条目下限
THIN_ADDON = 3    # 增项笔数下限
EPS = 1e-6

EXIT_OK, EXIT_RISKY, EXIT_BROKEN, EXIT_THIN, EXIT_RED = 0, 1, 2, 3, 4


class Broken(Exception):
    """账本损坏——exit 2"""


# ---------------------------------------------------------------- 显示宽度
def dw(s):
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def pad(s, w, right=False):
    gap = w - dw(s)
    if gap <= 0:
        return s
    return " " * gap + s if right else s + " " * gap


def money(n):
    return "¥" + format(round(n), ",")


# ---------------------------------------------------------------- 解析
def read_tsv(path, cols):
    if not os.path.exists(path):
        raise Broken(f"账本不存在:{path}")
    rows = []
    with open(path, encoding="utf-8") as fh:
        header = None
        for ln, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if header is None:
                header = [p.strip() for p in parts]
                missing = [c for c in cols if c not in header]
                if missing:
                    raise Broken(f"{path}: 表头缺列 {missing}")
                continue
            if len(parts) < len(header):
                raise Broken(f"{path} 第 {ln} 行:列数不足(要 {len(header)} 列,得 {len(parts)})")
            rows.append((ln, dict(zip(header, [p.strip() for p in parts]))))
    if header is None:
        raise Broken(f"{path}: 空账本")
    return rows


def num(val, path, ln, field, allow_zero=False):
    try:
        x = float(val)
    except (TypeError, ValueError):
        raise Broken(f"{path} 第 {ln} 行:{field} 不是数字({val!r})")
    if x != x or x in (float("inf"), float("-inf")):
        raise Broken(f"{path} 第 {ln} 行:{field} 非法({val!r})")
    if x < 0 or (x == 0 and not allow_zero):
        raise Broken(f"{path} 第 {ln} 行:{field} 必须 > 0(得 {val!r})")
    return x


class Entry(object):
    def __init__(self, ln, name, qty, unit, price, amount, est, kind, note):
        self.ln, self.name, self.qty, self.unit = ln, name, qty, unit
        self.price, self.amount, self.est, self.kind, self.note = price, amount, est, kind, note
        # 单价类基线审计所用的名义单价:pct 行 = amount÷小计,普通行 = price
        self.audit_price = price


def parse_quote(path):
    rows = read_tsv(path, ["item", "qty", "unit", "unit_price", "amount", "est", "note"])
    out, seen = [], {}
    for ln, r in rows:
        name = r["item"]
        if not name:
            raise Broken(f"{path} 第 {ln} 行:item 为空")
        if name in seen:
            raise Broken(f"{path} 第 {ln} 行:条目重复「{name}」(首见第 {seen[name]} 行)")
        seen[name] = ln
        qty = num(r["qty"], path, ln, "qty")
        price = num(r["unit_price"], path, ln, "unit_price")
        amount = num(r["amount"], path, ln, "amount")
        if abs(qty * price - amount) > 0.01:
            raise Broken(f"{path} 第 {ln} 行:amount 不自洽 qty×price={qty*price:.2f} ≠ amount={amount:.2f}")
        est = r["est"].lower()
        if est not in ("open", "fixed"):
            raise Broken(f"{path} 第 {ln} 行:est 必须 open/fixed(得 {r['est']!r})")
        out.append(Entry(ln, name, qty, r["unit"], price, amount, est, None, r["note"]))
    return out


def parse_addons(path):
    rows = read_tsv(path, ["item", "kind", "qty", "unit", "unit_price", "amount", "note"])
    out = []
    for ln, r in rows:
        name = r["item"]
        if not name:
            raise Broken(f"{path} 第 {ln} 行:item 为空")
        kind = r["kind"].lower()
        if kind not in KINDS:
            raise Broken(f"{path} 第 {ln} 行:kind 必须 {'/'.join(KINDS)}(得 {r['kind']!r})")
        qty = num(r["qty"], path, ln, "qty")
        price = num(r["unit_price"], path, ln, "unit_price")
        amount = num(r["amount"], path, ln, "amount")
        if abs(qty * price - amount) > 0.01:
            raise Broken(f"{path} 第 {ln} 行:amount 不自洽 qty×price={qty*price:.2f} ≠ amount={amount:.2f}")
        out.append(Entry(ln, name, qty, r["unit"], price, amount, None, kind, r["note"]))
    return out


def parse_baselines(path):
    rows = read_tsv(path, ["key", "aliases", "low", "high", "unit", "cond", "typical"])
    out = []
    for ln, r in rows:
        low = num(r["low"], path, ln, "low", allow_zero=True)
        high = num(r["high"], path, ln, "high")
        if low > high:
            raise Broken(f"{path} 第 {ln} 行:low > high")
        typ = num(r["typical"], path, ln, "typical", allow_zero=True)
        cond = r["cond"]
        if cond not in ("universal", "conditional"):
            raise Broken(f"{path} 第 {ln} 行:cond 必须 universal/conditional")
        out.append({"key": r["key"], "aliases": [a for a in r["aliases"].split("|") if a],
                    "low": low, "high": high, "unit": r["unit"], "cond": cond, "typical": typ})
    return out or None


# ---------------------------------------------------------------- 基线匹配
def match_keys(name, baselines):
    hits = []
    for b in baselines:
        if any(a in name for a in b["aliases"]):
            hits.append(b)
    return hits


def pick_strongest(hits):
    """一个条目可能命中多个 key(如「防水(含闭水试验)」);取区间最窄者为主判。"""
    if not hits:
        return None
    return min(hits, key=lambda b: (b["high"] - b["low"]) / max(b["high"], EPS))


def audit_price_of(entry, quote_nonpct_total, baselines):
    """pct 行的名义审计单价 = amount ÷ 合同小计(除 pct 行);普通行 = unit_price。"""
    hits = match_keys(entry.name, baselines)
    b = pick_strongest(hits)
    if b is not None and b["unit"] == "pct" and quote_nonpct_total > 0:
        return entry.amount / quote_nonpct_total, b
    return entry.price, b


def quote_nonpct_sum(quote, baselines):
    total = 0.0
    for q in quote:
        b = pick_strongest(match_keys(q.name, baselines))
        if b is None or b["unit"] != "pct":
            total += q.amount
    return total


# ---------------------------------------------------------------- 漏项与幻觉
def coverage(quote, baselines):
    """返回 [(baseline, covered:bool, via:name)] —— 一个 key 被任一条目覆盖即 covered。"""
    out = []
    for b in baselines:
        via = None
        for q in quote:
            if any(a in q.name for a in b["aliases"]):
                via = q.name
                break
        out.append((b, via is not None, via))
    return out


def gap_estimate(b, quote_nonpct_total):
    """漏项中位预估:pct 按合同小计,其余按 typical×中位单价;typical=0 不可预估。"""
    mid = (b["low"] + b["high"]) / 2.0
    if b["unit"] == "pct":
        return mid * quote_nonpct_total
    if b["typical"] <= 0:
        return None
    return mid * b["typical"]


def gap_range(b, quote_nonpct_total):
    """(下沿预估, 上沿预估) 或 None。"""
    if b["unit"] == "pct":
        return b["low"] * quote_nonpct_total, b["high"] * quote_nonpct_total
    if b["typical"] <= 0:
        return None
    return b["low"] * b["typical"], b["high"] * b["typical"]


def bait_lines(quote, baselines):
    """诱饵条目:单价 < 下沿×BAIT。返回 [(entry, baseline, ratio)]。"""
    out = []
    nonpct = quote_nonpct_sum(quote, baselines)
    for q in quote:
        b = pick_strongest(match_keys(q.name, baselines))
        if b is None or b["unit"] == "pct" or b["low"] <= 0:
            continue
        ratio = q.price / b["low"]
        if q.price < b["low"] * BAIT:
            out.append((q, b, ratio))
    return out


def open_bait(quote, baselines):
    """诱饵×开口:低价单价 + 按实结算 = 标准杀局。"""
    return [(q, b, r) for q, b, r in bait_lines(quote, baselines) if q.est == "open"]


def kill_lines(addons, quote, baselines):
    """宰客增项:单价 > 上沿×KILL。返回 [(entry, baseline, multiple, audit_price)]。"""
    out = []
    nonpct = quote_nonpct_sum(quote, baselines)
    for a in addons:
        b = pick_strongest(match_keys(a.name, baselines))
        if b is None or b["unit"] == "pct" or b["high"] <= 0:
            continue
        ap, _ = audit_price_of(a, nonpct, baselines)
        if ap > b["high"] * KILL:
            out.append((a, b, ap / b["high"], ap))
    return out


def drift_pairs(addons, quote, baselines):
    """量差行挂靠报价单开口条目:条目名与开口条目命中同一基线 key,或互为
    前缀(无基线时);多候选取最长名。返回 [(addon, quote_entry, final_qty, ratio)];
    挂靠失败在调用处报 Broken。"""
    opens = [q for q in quote if q.est == "open"]
    out = []
    for a in addons:
        if a.kind != "drift":
            continue
        akeys = {b["key"] for b in match_keys(a.name, baselines)}
        cands = [q for q in opens
                 if akeys & {b["key"] for b in match_keys(q.name, baselines)}
                 or a.name.startswith(q.name) or q.name.startswith(a.name)]
        if not cands:
            raise Broken(f"addons 第 {a.ln} 行:量差「{a.name}」挂靠不到报价单里的开口条目"
                         f"(条目名须与开口条目同类,且该条目 est=open)")
        q = max(cands, key=lambda x: len(x.name))
        final = q.qty + a.qty
        out.append((a, q, final, final / q.qty))
    return out


# ---------------------------------------------------------------- 汇总
def classify_totals(addons):
    totals = {k: 0.0 for k in KINDS}
    counts = {k: 0 for k in KINDS}
    for a in addons:
        totals[a.kind] += a.amount
        counts[a.kind] += 1
    return totals, counts


def hallucination(quote, baselines):
    """低价幻觉指数 = 漏项中位预估 ÷ 合同小计。返回 (index, missing_rows, mid_total, lo, hi)。"""
    nonpct = quote_nonpct_sum(quote, baselines)
    cov = coverage(quote, baselines)
    missing = [(b, via) for b, covered, via in cov if not covered]
    mid_total = lo_total = hi_total = 0.0
    rows = []
    for b, _ in missing:
        mid = gap_estimate(b, nonpct)
        rng = gap_range(b, nonpct)
        if mid is not None:
            mid_total += mid
            lo_total += rng[0]
            hi_total += rng[1]
        rows.append((b, mid, rng))
    idx = mid_total / nonpct if nonpct > 0 else 0.0
    return idx, rows, mid_total, lo_total, hi_total, nonpct


# ---------------------------------------------------------------- 报告
HONEST = ("诚实条款:四分类是签字人当场自报的;常识区间是先验不是行情(--baselines 覆盖,本地价格永远赢);"
          "它不回答「装修该花多少钱」,只回答「这份便宜是怎么炼成的」——签不签,人的决定")


def cmd_audit(quote, addons, baselines, cap):
    nonpct = quote_nonpct_sum(quote, baselines)
    qtotal = sum(q.amount for q in quote)
    atotal = sum(a.amount for a in addons)
    if len(addons) < THIN_ADDON:
        print(f"THIN · 增项流水仅 {len(addons)} 笔(< {THIN_ADDON}),拒绝给增项结构下结论"
              f"——把签字的每一张单子记进来再开庭(exit 3)")
        return EXIT_THIN
    rate = atotal / qtotal
    totals, counts = classify_totals(addons)
    settlement = qtotal + atotal

    print(f"增项总账 · 合同 {money(qtotal)}({len(quote)} 条)· 账面增项 {money(atotal)}"
          f"({len(addons)} 笔)· 推定结算 {money(settlement)}")
    flag = "✗ 超红线" if rate > cap else ("▲ 越黄线" if rate > CAP_WARN else "✓ 线内")
    print(f"增项率 +{rate*100:.1f}%(红线 {cap*100:.0f}% / 黄线 {CAP_WARN*100:.0f}%){flag}")
    if rate > CAP_WARN:
        print(f"比价时看的那 {money(qtotal)},从来不是这份合同的价格")
    print()
    print("── 四分类瀑布(每一笔你都签过字,但性质完全不同)─" + "─" * 18)
    for k in KINDS:
        share = totals[k] / atotal if atotal else 0.0
        print(f"  {pad(KIND_LABEL[k], 10)}{pad(money(totals[k]), 11, True)}{pad(f'{share*100:.1f}%', 8, True)}"
              f"  {KIND_NOTE[k]}({counts[k]} 笔)")
    print()

    # 开口爆量
    pairs = drift_pairs(addons, quote, baselines)
    drift_red = []
    if pairs:
        print("── 开口爆量(按实结算 = 把预估写小,把总量留白)─" + "─" * 14)
        for a, q, final, ratio in pairs:
            mark = "✗" if ratio > DRIFT_CAP else "✓"
            if ratio > DRIFT_CAP:
                drift_red.append((q, final, ratio))
            print(f"  {q.name}:预估 {fmt_qty(q.qty)}{q.unit} → final {fmt_qty(final)}{q.unit} "
                  f"= {ratio:.2f}x(红线 {DRIFT_CAP}x){mark}")
            if ratio > DRIFT_CAP:
                final_amt = q.price * final
                print(f"    —— {money(q.price)}/{q.unit} 看着便宜,按 final 结算 = {money(final_amt)},"
                      f"比合同里那行 {money(q.amount)} 贵 {(final_amt/q.amount-1)*100:.0f}%:"
                      f"诱饵的本体是预估数,不是单价")
        print()

    # 宰客单价
    kills = kill_lines(addons, quote, baselines)
    if kills:
        print("── 宰客单价(增项价 vs 常识区间,上沿 1.5x = 进门后的第二张价目表)─" + "─" * 4)
        for a, b, mult, ap in kills:
            print(f"  {a.name} {money(ap)}{b['unit']} vs {fmt_range(b)} → {mult:.2f}x ✗")
        print()

    # 恒等式
    res = settlement - (qtotal + totals["upgrade"] + totals["forced"] + totals["drift"] + totals["padded"])
    print(f"── 分类恒等式:合同 + 四类 = 推定结算 ──")
    print(f"  {money(qtotal)} + {money(totals['upgrade'])} + {money(totals['forced'])}"
          f" + {money(totals['drift'])} + {money(totals['padded'])} = "
          f"{money(qtotal + sum(totals.values()))}(残差 {abs(res):.2f})")
    print()
    reds = []
    if rate > cap:
        reds.append(f"增项率 {rate*100:.1f}% 超红线 {cap*100:.0f}%")
    if kills:
        reds.append(f"宰客单价 {len(kills)} 笔")
    if drift_red:
        reds.append(f"开口爆量 {len(drift_red)} 笔")
    if reds:
        print(f"红线 ✗ exit 4 —— {' / '.join(reds)}")
        print(HONEST)
        return EXIT_RED
    if rate > CAP_WARN:
        print("黄线 ▲ exit 1 —— 未越红线,但增项结构值得在结算前对一次账")
        print(HONEST)
        return EXIT_RISKY
    print("绿 ✓ exit 0 —— 增项率与单价均在常识线内")
    print(HONEST)
    return EXIT_OK


def fmt_qty(q):
    return f"{q:g}"


def fmt_range(b):
    if b["unit"] == "pct":
        return f"{b['low']*100:.0f}–{b['high']*100:.0f}% 合同额"
    return f"{b['low']:g}–{b['high']:g} {b['unit']}"



def cmd_gaps(quote, baselines, gate_universal):
    if len(quote) < THIN_QUOTE:
        print(f"THIN · 报价单仅 {len(quote)} 条(< {THIN_QUOTE}),结构审计无意义——"
              f"这更像一张手写便条而不是报价单(exit 3)")
        return EXIT_THIN
    qtotal = sum(q.amount for q in quote)
    idx, rows, mid, lo, hi, nonpct = hallucination(quote, baselines)
    cov = coverage(quote, baselines)
    covmap = {b["key"]: via for b, covered, via in cov if covered}

    print(f"漏项审计 · 报价单 {len(quote)} 条 · 合同 {money(qtotal)} · 对照行业常识清单"
          f"({sum(1 for b in baselines if b['cond']=='universal')} universal + "
          f"{sum(1 for b in baselines if b['cond']=='conditional')} conditional)")
    uni = [(b, m, r) for b, m, r in rows if b["cond"] == "universal"]
    con = [(b, m, r) for b, m, r in rows if b["cond"] == "conditional"]
    missing_keys = {b["key"] for b, _, _ in rows}
    print()
    print("  无条件必含(universal)——缺了开工后必回来收钱:")
    for b in baselines:
        if b["cond"] != "universal":
            continue
        if b["key"] in missing_keys:
            rng = gap_range(b, nonpct)
            est = f"预估 {money(rng[0])}–{money(rng[1])}" if rng else "量不可预估,先电话问价"
            print(f"    ✗ {pad(b['key'], 10)}{est}")
        else:
            print(f"    ✓ {pad(b['key'], 10)}已报(词条:{covmap.get(b['key'], '')})")
    con_missing = [b for b in baselines if b["cond"] == "conditional" and b["key"] in missing_keys]
    con_have = [b for b in baselines if b["cond"] == "conditional" and b["key"] not in missing_keys
                and b["typical"] > 0]
    if con_missing:
        print("  条件触发(conditional)——若你家有此需求,缺失即漏项:")
        for b in con_missing:
            rng = gap_range(b, nonpct)
            est = f"预估 {money(rng[0])}–{money(rng[1])}" if rng else "量不可预估,先电话问价"
            print(f"    ✗ {pad(b['key'], 10)}{est}")
    if con_have:
        print("  条件触发已覆盖:" + " · ".join(b["key"] for b in con_have) + " ✓")
    print()

    # 诱饵×开口
    ob = open_bait(quote, baselines)
    if ob:
        print("  诱饵×开口(低价单价 + 按实结算 = 标准杀局):")
        for q, b, ratio in ob:
            print(f"    ✗ {q.name} {money(q.price)}{b['unit']} = 常识下沿 {ratio:.2f}x,且按实结算"
                  f"——诱饵的本体是预估数,不是单价")
        print()

    print(f"低价幻觉:合同 {money(qtotal)} + 漏项中位预估 {money(mid)}"
          f"(区间 {money(lo)}–{money(hi)})= 真实底价 {money(qtotal + mid)}")
    print(f"幻觉指数 {idx*100:.1f}%(红线 {HALLUCINATION*100:.0f}%)"
          f"——它统计的是「什么都没改、什么都没爆」也要付的钱,是增项的下界不是预测" if idx > 0 else
          "幻觉指数 0.0%——常识清单全覆盖")
    print()
    if len(uni) >= gate_universal or idx > HALLUCINATION:
        why = []
        if len(uni) >= gate_universal:
            why.append(f"universal 漏项 {len(uni)} 项 ≥ {gate_universal}")
        if idx > HALLUCINATION:
            why.append(f"幻觉指数 {idx*100:.1f}% > {HALLUCINATION*100:.0f}%")
        print(f"红线 ✗ exit 4 —— {';'.join(why)}:这份便宜是用还没写的字换的")
        return EXIT_RED
    if uni or idx > HALLUCINATION / 2:
        print("黄线 ▲ exit 1 —— 有缺失但未越线:对缺失项逐条问「含不含」,把答案写进合同再签")
        return EXIT_RISKY
    print("绿 ✓ exit 0 —— 常识清单覆盖完整")
    return EXIT_OK


def cmd_judge(quote, baselines, gate_universal):
    if len(quote) < THIN_QUOTE:
        print(f"THIN · 报价单仅 {len(quote)} 条(< {THIN_QUOTE}),不裁决便条(exit 3)")
        return EXIT_THIN
    qtotal = sum(q.amount for q in quote)
    idx, rows, mid, lo, hi, nonpct = hallucination(quote, baselines)
    uni_n = sum(1 for b, _, _ in rows if b["cond"] == "universal")
    con_n = sum(1 for b, _, _ in rows if b["cond"] == "conditional")
    ob = open_bait(quote, baselines)
    cov = coverage(quote, baselines)
    missing = {b["key"] for b, covered, via in cov if not covered}

    print(f"报价单裁决 · {len(quote)} 条 · 合同 {money(qtotal)}(签字之前跑一次,这是本件的灵魂命令)")
    print()
    print(f"  漏项:universal {uni_n} 项 / conditional {con_n} 项 → 漏项中位预估 {money(mid)}")
    if uni_n or con_n:
        for b, m, rng in rows:
            tag = "universal" if b["cond"] == "universal" else "conditional"
            rngs = f"(区间 {money(rng[0])}–{money(rng[1])})" if rng else ""
            print(f"    ✗ {pad(b['key'], 10)}[{pad(tag, 12)}]{rngs}")
    else:
        print("    ✓ 常识清单全覆盖")
    print()
    if ob:
        print("  诱饵×开口杀局:")
        for q, b, ratio in ob:
            print(f"    ✗ {q.name}:单价 {money(q.price)}{b['unit']} = 常识下沿 {ratio:.2f}x "
                  f"且 est=open——低价单价 + 量不可控,签单后每一米都是他的定价权")
        print()
    print(f"  低价幻觉指数 {idx*100:.1f}%(红线 {HALLUCINATION*100:.0f}%)"
          f" → 真实底价 {money(qtotal + mid)}(合同 + 漏项中位)")
    print()
    red = uni_n >= gate_universal or idx > HALLUCINATION or bool(ob)
    if red:
        reasons = []
        if uni_n >= gate_universal:
            reasons.append(f"universal 漏项 {uni_n} 项")
        if idx > HALLUCINATION:
            reasons.append(f"幻觉指数 {idx*100:.1f}%")
        if ob:
            reasons.append("诱饵×开口杀局")
        print(f"  裁决 ✗ 不签——{';'.join(reasons)}。这份便宜是用还没写的字换的:")
        print("    先让漏项进报价单、开口项写上「单价×封顶量」,把这两件事做完,再回来谈价格")
        print()
        print("  " + HONEST)
        return EXIT_RED
    if uni_n or idx > HALLUCINATION / 2:
        print("  裁决 ▲ 有条件签(exit 1)——把缺失项逐条问成书面条款再签")
        print("  " + HONEST)
        return EXIT_RISKY
    print("  裁决 ✓ 可以谈(exit 0)——常识清单覆盖完整、无诱饵×开口:这份单子的贵,是诚实的贵")
    print("  " + HONEST)
    return EXIT_OK


def cmd_prices(quote, addons, baselines):
    if len(addons) < THIN_ADDON:
        print(f"THIN · 增项流水仅 {len(addons)} 笔(< {THIN_ADDON}),单价对账无从谈起(exit 3)")
        return EXIT_THIN
    nonpct = quote_nonpct_sum(quote, baselines)
    print("单价对账 · 增项单价 vs 行业常识区间"
          f"(下沿 {BAIT}x 以下 = 诱饵价 · 上沿 {KILL}x 以上 = 宰客价——同一个工地,两套价目表)")
    print()
    rows = []
    for a in addons:
        b = pick_strongest(match_keys(a.name, baselines))
        if b is None:
            rows.append((a, None, None, None, None))
            continue
        ap, _ = audit_price_of(a, nonpct, baselines)
        if b["unit"] == "pct":
            rows.append((a, b, ap, "pct", None))
        else:
            rows.append((a, b, ap, "price", ap / b["low"] if b["low"] > 0 else None))
    kills = 0
    baits = 0
    for a, b, ap, mode, lo_ratio in rows:
        if b is None:
            print(f"  {pad(a.name, 22)}{pad(money(a.price) + '/' + a.unit, 14, True)}"
                  f"  无常识基线——自报单价,账本只登记不审计")
            continue
        if mode == "pct":
            pos = f"{fmt_range(b)} → {ap*100:.1f}%"
            if ap > b["high"]:
                mark = "▲ 上沿之上"
            elif ap > (b["low"] + b["high"]) / 2:
                mark = "△ 区间上半"
            else:
                mark = "✓ 区间内"
            print(f"  {pad(a.name, 22)}{pad(f'{ap*100:.1f}% 合同额', 14, True)}  {pad(pos, 24)}  {mark}")
            continue
        if ap > b["high"] * KILL:
            mark = f"✗ 宰客({ap/b['high']:.2f}x 上沿)"
            kills += 1
        elif ap < b["low"] * BAIT:
            mark = f"▲ 诱饵({lo_ratio:.2f}x 下沿)"
            baits += 1
        elif ap > b["high"]:
            mark = "△ 区间上段"
        elif ap < b["low"]:
            mark = "△ 区间下段(注意开口)"
        else:
            mark = "✓ 区间内"
        print(f"  {pad(a.name, 22)}{pad(money(ap) + b['unit'], 14, True)}"
              f"  {pad(fmt_range(b), 24)}  {mark}")
    print()
    if kills:
        print(f"红线 ✗ exit 4 —— {kills} 笔宰客单价:签单时的市场价,增项时的垄断价;"
              f"拿行业区间回去谈,或按 padded 记账攒谈判依据")
        return EXIT_RED
    if baits:
        print(f"黄线 ▲ exit 1 —— {baits} 笔诱饵价:单价便宜但若挂开口(est=open),量的定价权在他手里")
        return EXIT_RISKY
    print("绿 ✓ exit 0 —— 增项单价全部落在常识区间内")
    return EXIT_OK


def cmd_sign(quote, baselines, item, qty, price, unit):
    qtotal = sum(q.amount for q in quote)
    nonpct = quote_nonpct_sum(quote, baselines)
    fake = Entry(0, item, qty, unit or "项", price, qty * price, None, None, "")
    b = pick_strongest(match_keys(item, baselines))
    print(f"签字门禁 · 工长递来的单子,先过闸再签字(签字的手比脑子快,闸门替脑子争取三分钟)")
    print()
    print(f"  增项:{item} · {fmt_qty(qty)}{unit or ''} × {money(price)} = {money(qty*price)}")
    if b is None:
        print("  常识区间:无匹配基线——自报单价,账本只登记不审计")
        verdict, code = ("○ 无基线,自行斟酌(exit 0)", EXIT_OK)
    else:
        ap, b = audit_price_of(fake, nonpct, baselines)
        if b["unit"] == "pct":
            print(f"  常识区间:{b['low']*100:.0f}–{b['high']*100:.0f}% 合同额"
                  f"(本单小计 {money(nonpct)}):这 {money(price)} = {ap*100:.1f}%")
            over = ap > b["high"]
            baitflag = ap < b["low"]
        else:
            lo_r = ap / b["low"] if b["low"] > 0 else None
            hi_r = ap / b["high"]
            print(f"  常识区间:{fmt_range(b)} → 本单价 {money(ap)}{b['unit']}")
            over = ap > b["high"] * KILL
            baitflag = b["low"] > 0 and ap < b["low"] * BAIT
            if over:
                print(f"  判位:上沿 {hi_r:.2f}x ✗ 宰客价——进门后的第二张价目表")
            elif baitflag:
                print(f"  判位:下沿 {lo_r:.2f}x ▲ 低于常识——便宜得反常的单子要问量怎么算")
            elif ap > b["high"]:
                print(f"  判位:区间上段(上沿 {hi_r:.2f}x)△ 可谈")
            elif ap < b["low"]:
                print(f"  判位:区间下段 △ 若按实结算,警惕量爆炸")
            else:
                print(f"  判位:区间内 ✓")
        # 合同对照
        same = [q for q in quote if any(a in q.name for a in b["aliases"])]
        if same:
            q0 = same[0]
            print(f"  合同对照:报价单「{q0.name}」单价 {money(q0.price)}——"
                  f"本增项是其 {price/q0.price:.2f}x" if q0.price > 0 else f"  合同对照:报价单「{q0.name}」")
        else:
            print(f"  合同对照:报价单无同类条目(这正是它成为增项的原因——漏项的账,现在用他的价目表收)")
        # 开口挂靠
        drift_hint = ""
        opens = [q for q in quote if q.est == "open" and any(a in q.name for a in b["aliases"])]
        if opens:
            drift_hint = opens[0].name
        # 分类口诀
        print(f"  分类口诀:你不提他就不会做 → upgrade;你不签工程就停 → forced;"
              f"问三家公司两家含 → padded;报价单里的开口项长量 → drift"
              + (f"(提示:「{drift_hint}」是开口条目——若本笔是其量差,请记 kind=drift)" if drift_hint else ""))
        print(f"  推荐记账行(粘进 addons.tsv):")
        kind_guess = "forced"
        if drift_hint:
            kind_guess = "drift"
        elif over:
            kind_guess = "forced"
        print(f"    {item}\t{kind_guess}\t{fmt_qty(qty)}\t{unit or '项'}\t{price:g}\t{qty*price:.0f}\t"
              f"签字门禁:{('上沿%.2fx' % (ap/b['high'])) if over else '过闸'}")
        if over:
            verdict, code = (f"✗ 越线(exit 4)——单价超常识上沿 {KILL} 倍:不签,拿行业区间回去谈;"
                             f"签,是你知情的选择", EXIT_RED)
        elif baitflag:
            verdict, code = (f"▲ 黄灯(exit 1)——单价低于常识下沿:确认是否按实结算、预估量是多少再签",
                             EXIT_RISKY)
        else:
            verdict, code = ("✓ 过闸(exit 0)——单价在常识区间内,分类与记账行已给出", EXIT_OK)
    print()
    print("  " + verdict)
    print("  " + HONEST)
    return code


def cmd_validate(quote, addons, baselines):
    problems = []
    # 行级自洽已由解析层保证;这里审跨行恒等式与挂靠
    qtotal = sum(q.amount for q in quote)
    if addons:
        atotal = sum(a.amount for a in addons)
        totals, _ = classify_totals(addons)
        res = atotal - sum(totals.values())
        if abs(res) > EPS:
            problems.append(f"四类加总 {sum(totals.values()):.2f} ≠ 增项总额 {atotal:.2f}(残差 {res:.4f})")
        try:
            drift_pairs(addons, quote, baselines)
        except Broken as e:
            problems.append(str(e))
    else:
        atotal = 0.0
    # pct 行的审计单价 > 1 = 比例荒谬
    nonpct = quote_nonpct_sum(quote, baselines)
    for q in quote:
        b = pick_strongest(match_keys(q.name, baselines))
        if b is not None and b["unit"] == "pct" and nonpct > 0:
            r = q.amount / nonpct
            if r > 0.25:
                problems.append(f"「{q.name}」= 合同额 {r*100:.1f}%,常识上沿 25%——比例荒谬,核对是否记错")
    # open 条目存在性提示(不是错)
    opens = [q.name for q in quote if q.est == "open"]
    print(f"账本体检 · 合同 {money(qtotal)}({len(quote)} 条)· 增项 {money(atotal)}"
          f"({len(addons)} 笔)· 开口条目 {len(opens)} 条")
    if opens:
        print(f"  开口条目:{', '.join(opens)}——按实结算的量差请记 kind=drift 并以条目名开头挂靠")
    if addons:
        print(f"  恒等式:结算 = 合同 {money(qtotal)} + 增项 {money(atotal)} = {money(qtotal+atotal)}")
    if problems:
        print()
        for p in problems:
            print(f"  ✗ {p}")
        print(f"红线 ✗ exit 2 —— 账本损坏 {len(problems)} 处,先修账再开庭")
        return EXIT_BROKEN
    print("绿 ✓ exit 0 —— 行级自洽、四类加总、开口挂靠全部通过")
    return EXIT_OK


# ---------------------------------------------------------------- main
def load_baselines(args):
    if getattr(args, "baselines", None):
        return parse_baselines(args.baselines)
    return [{"key": k, "aliases": a.split("|"), "low": lo, "high": hi, "unit": u,
             "cond": c, "typical": t} for k, a, lo, hi, u, c, t in DEFAULT_BASELINES]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lowball", description="低价签 · Lowball——装修增项审计账本")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("audit", help="增项总账:四分类瀑布 + 开口爆量 + 宰客单价")
    p.add_argument("quote"); p.add_argument("addons")
    p.add_argument("--baselines"); p.add_argument("--cap", type=float, default=CAP)

    p = sub.add_parser("gaps", help="漏项审计 + 低价幻觉指数")
    p.add_argument("quote")
    p.add_argument("--baselines"); p.add_argument("--gate-universal", type=int, default=UNIVERSAL_GATE)

    p = sub.add_parser("judge", help="签字前裁决一份报价单")
    p.add_argument("quote")
    p.add_argument("--baselines"); p.add_argument("--gate-universal", type=int, default=UNIVERSAL_GATE)

    p = sub.add_parser("prices", help="单价对账:诱饵价与宰客价")
    p.add_argument("quote"); p.add_argument("addons")
    p.add_argument("--baselines")

    p = sub.add_parser("sign", help="签字门禁:单笔增项过闸")
    p.add_argument("quote")
    p.add_argument("--baselines")
    p.add_argument("--item", required=True)
    p.add_argument("--qty", type=float, required=True)
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--unit", default="项")

    p = sub.add_parser("validate", help="恒等式体检")
    p.add_argument("quote"); p.add_argument("addons")
    p.add_argument("--baselines")

    args = ap.parse_args(argv)
    try:
        baselines = load_baselines(args)
        if args.cmd in ("gaps", "judge", "sign"):
            quote = parse_quote(args.quote)
        else:
            quote = parse_quote(args.quote)
            addons = parse_addons(args.addons)
    except Broken as e:
        print(f"账本损坏(exit 2):{e}")
        return EXIT_BROKEN

    try:
        if args.cmd == "audit":
            return cmd_audit(quote, addons, baselines, args.cap)
        if args.cmd == "gaps":
            return cmd_gaps(quote, baselines, args.gate_universal)
        if args.cmd == "judge":
            return cmd_judge(quote, baselines, args.gate_universal)
        if args.cmd == "prices":
            return cmd_prices(quote, addons, baselines)
        if args.cmd == "sign":
            return cmd_sign(quote, baselines, args.item, args.qty, args.price, args.unit)
        if args.cmd == "validate":
            return cmd_validate(quote, addons, baselines)
    except Broken as e:
        print(f"账本损坏(exit 2):{e}")
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
