#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八分钱 · Eight Cents / 油电购车的话术翻译器。

电车销售递上话术:「一公里才八分钱,油车一公里六毛,一年省一万多。」
油车销售反击:「电池五六年一换八万块。」——两边的数字都是他们的算法:
八分钱 = 13.5kWh/100km × 家充谷价,100% 家充、只算电费;不含保险差价、
不含购置税、不含公共充电溢价、更不含「你家里有没有桩、一年跑多少公里」。
同一辆车两种算法,中间没有翻译。你在两个销售的对轰里拍板,拍完才发现
家里装不了充电桩。

本件把候选车与你的用车事实抄成两本手编账,用你的参数把两本账并排:

  report     油电总账——每车的营销口径 vs 你的真实口径(每公里解剖)+ 年成本
             + N 年总持有成本 TCO 并排 + 三盏灯
  breakeven  回本几何——落地差价靠年节省几个月追平,闭式解;追不平明说
  validate   恒等式与账本体检——每公里/年成本/加权电价/TCO/回本全双路径对拍

核心断言:**结论不属于车,属于你的桩和里程**。同一对车,家充 85%、年跑
18000 的家庭 3 年半回本;无桩、年跑 6000 的家庭 20 年追不平——车是同一对,
账是两本。「电车省不省」是个没有分母的问题,本件给分母。

诚实条款:营销口径 = 能耗 × 家充电价(100% 家充、只算能耗)是对营销话术
的通识还原,以你听到的原话为准;真实口径含能耗+保险摊+保养摊+车船税摊,
全款名义加总,不折现(钱的时间价值不建模);折旧不建模——二手车市场油电
争议极大,账本不猜,要算请把差额摊进 maint 自己翻案;电池更换风险不建模
(恐怖故事对恐怖故事,都拿数字说话:把 maint 填成摊销后的数,账本照算);
购置税留空按通识默认(油车 price/1.13×10% 计税、电车免征)——新能源购置税
2026-2027 处于减半过渡期,以办理日政策为准,purchase_tax 列随时翻案;
保险是报价不是估算,抄销售报价单;绿牌路权/限行是城市变量,不折价;
不荐车——报告输出的是账,买哪辆是人的决定。零墙钟:账本里没有日期,
不读时钟,同账任何机器任何一天逐字节一致。

账本(--dir 目录下两份 TSV):
  cars.tsv    name/type/price/energy100/insurance/maint/road_tax/purchase_tax/note
              一行一辆候选车。type = gas(油,energy100=油耗 L/100km)
                              | ev (电,energy100=电耗 kWh/100km)
              purchase_tax 留空 = 通识默认(见诚实条款),显式填了以填的为准
  usage.tsv   profile/key/value/note   一行一个参数,同名 profile 构成一份用车事实
              必需键: km_year(年里程) gas_price(油价元/L)
                      home_price(家充元/度) public_price(公充元/度)
                      home_share(家充占比 0..1)
              未知键 = 账坏(宁可拒绝,不静默忽略写错的参数名)
"""

import argparse
import os
import sys

EXIT_OK, EXIT_BAD, EXIT_EMPTY, EXIT_RED = 0, 2, 3, 4

CAR_COLS = ("name", "type", "price", "energy100", "insurance",
            "maint", "road_tax", "purchase_tax", "note")
USAGE_COLS = ("profile", "key", "value", "note")

USAGE_KEYS = ("km_year", "gas_price", "home_price", "public_price", "home_share")

TAX_DENOM = 1.13        # 购置税计税价 = 车价/(1+13% 增值税),通识口径
GAS_TAX_RATE = 0.10     # 燃油车购置税率,通识;--gas-tax-rate 翻案
YEARS = 6               # TCO 年限(一个换车周期),--years 翻案
PENNY_LINE = 1.5        # PENNY-MYTH:真实能耗单价 > 营销口径 × 1.5 亮,恰线不亮
INS_GAP_LINE = 25.0     # INSURANCE-GAP:年保费差 > 便宜车 × 25% 亮,恰线不亮
HOME_LINE = 0.6         # HOME-CHARGING:家充占比 ≥ 0.6 亮,恰线不亮
PAYBACK_CAP = 120       # BREAKEVEN-NEVER:回本 > 120 月亮,恰线不亮,--payback-cap 翻案


class LedgerBad(Exception):
    """账坏——宁可拒绝,不替你编账。"""


class Decline(Exception):
    """拒答——账太薄或输入不合,算术照出,判决不发。"""


# ---------------------------------------------------------------- 工具 ----

def parse_num(s, what):
    try:
        return float(s)
    except (TypeError, ValueError):
        raise LedgerBad(f"{what} 不是数字: {s!r}")


def fmt_money(v):
    return f"¥{v:,.2f}"


def fmt_perkm(v):
    return f"{v * 100:.1f} 分"


def disp_width(s):
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E7F else 1
    return w


def pad(s, width, align="left"):
    gap = width - disp_width(s)
    if gap <= 0:
        return s
    return s + " " * gap if align == "left" else " " * gap + s


def read_tsv(path, cols):
    """手编 TSV: tab 分列,# 注释,空行跳过,缺列 exit 2;文件可不存在 → []。"""
    if not os.path.exists(path):
        return []
    rows = []
    header = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if header is None:
                header = [p.strip() for p in parts]
                missing = [c for c in cols if c not in header]
                if missing:
                    raise LedgerBad(f"{os.path.basename(path)} 缺列: {'、'.join(missing)}")
                continue
            d = {name: (parts[i].strip() if i < len(parts) else "")
                 for i, name in enumerate(header)}
            rows.append(d)
    return rows


# ---------------------------------------------------------------- 载入 ----

def load_cars(ddir, gas_tax_rate=GAS_TAX_RATE):
    rows = read_tsv(os.path.join(ddir, "cars.tsv"), CAR_COLS)
    cars = []
    names = set()
    for i, r in enumerate(rows, 2):
        name = r.get("name") or ""
        if not name:
            raise LedgerBad(f"cars.tsv 第 {i} 行缺 name")
        if name in names:
            raise LedgerBad(f"cars.tsv 车名重复: {name!r}")
        names.add(name)
        ctype = r.get("type") or ""
        if ctype not in ("gas", "ev"):
            raise LedgerBad(f"cars.tsv {name} type 必须是 gas/ev: {ctype!r}")
        car = {
            "name": name, "type": ctype,
            "price": parse_num(r.get("price"), f"{name} 车价"),
            "energy100": parse_num(r.get("energy100"), f"{name} energy100"),
            "insurance": parse_num(r.get("insurance"), f"{name} 年保费"),
            "maint": parse_num(r.get("maint"), f"{name} 年保养"),
            "road_tax": parse_num(r.get("road_tax"), f"{name} 年车船税"),
            "purchase_tax_raw": (r.get("purchase_tax") or "").strip(),
            "note": r.get("note", ""),
        }
        if car["price"] <= 0:
            raise LedgerBad(f"{name} 车价必须 > 0: {car['price']}")
        if car["energy100"] <= 0:
            raise LedgerBad(f"{name} energy100 必须 > 0: {car['energy100']}")
        for k in ("insurance", "maint", "road_tax"):
            if car[k] < 0:
                raise LedgerBad(f"{name} {k} 不能为负: {car[k]}")
        if car["purchase_tax_raw"]:
            car["purchase_tax"] = parse_num(car["purchase_tax_raw"], f"{name} 购置税")
            car["tax_source"] = "你填的"
            if car["purchase_tax"] < 0:
                raise LedgerBad(f"{name} 购置税不能为负: {car['purchase_tax']}")
        else:
            if ctype == "gas":
                car["purchase_tax"] = car["price"] / TAX_DENOM * gas_tax_rate
                car["tax_source"] = f"通识默认 车价/{TAX_DENOM}×{gas_tax_rate:.0%}"
            else:
                car["purchase_tax"] = 0.0
                car["tax_source"] = "通识默认 0(免征)"
        cars.append(car)
    return cars


def load_usage(ddir):
    rows = read_tsv(os.path.join(ddir, "usage.tsv"), USAGE_COLS)
    profiles = {}
    order = []
    for i, r in enumerate(rows, 2):
        prof = r.get("profile") or ""
        key = r.get("key") or ""
        if not prof:
            raise LedgerBad(f"usage.tsv 第 {i} 行缺 profile")
        if not key:
            raise LedgerBad(f"usage.tsv 第 {i} 行缺 key")
        if key not in USAGE_KEYS:
            raise LedgerBad(f"usage.tsv 未知参数 {key!r}——"
                            f"认识的键: {'、'.join(USAGE_KEYS)}")
        if prof not in profiles:
            profiles[prof] = {}
            order.append(prof)
        if key in profiles[prof]:
            raise LedgerBad(f"usage.tsv {prof} 的 {key} 重复——同一参数一行就够")
        profiles[prof][key] = parse_num(r.get("value"), f"{prof}.{key}")
    for prof in order:
        p = profiles[prof]
        missing = [k for k in USAGE_KEYS if k not in p]
        if missing:
            raise LedgerBad(f"usage.tsv profile {prof} 缺参数: {'、'.join(missing)}——"
                            f"必需键: {'、'.join(USAGE_KEYS)}")
        if p["km_year"] <= 0:
            raise LedgerBad(f"{prof} km_year 必须 > 0: {p['km_year']}")
        for k in ("gas_price", "home_price", "public_price"):
            if p[k] <= 0:
                raise LedgerBad(f"{prof} {k} 必须 > 0: {p[k]}")
        if not (0 <= p["home_share"] <= 1):
            raise LedgerBad(f"{prof} home_share 必须在 0..1: {p['home_share']}")
    return profiles, order


def load_ledger(ddir, gas_tax_rate=GAS_TAX_RATE):
    return load_cars(ddir, gas_tax_rate), load_usage(ddir)


# ---------------------------------------------------------------- 算术 ----

def blended_price(prof):
    """加权电价 = 家充占比 × 家充价 + (1−占比) × 公充价。线性,分段可对拍。"""
    return prof["home_share"] * prof["home_price"] + (1 - prof["home_share"]) * prof["public_price"]


def energy_per_km(car, prof):
    if car["type"] == "gas":
        return car["energy100"] / 100 * prof["gas_price"]
    return car["energy100"] / 100 * blended_price(prof)


def marketing_per_km(car, prof):
    """营销口径:只算能耗,电车按 100% 家充——「八分钱」的由来。"""
    if car["type"] == "gas":
        return car["energy100"] / 100 * prof["gas_price"]
    return car["energy100"] / 100 * prof["home_price"]


def fixed_per_km(car, prof):
    return (car["insurance"] + car["maint"] + car["road_tax"]) / prof["km_year"]


def real_per_km(car, prof):
    return energy_per_km(car, prof) + fixed_per_km(car, prof)


def yearly_cost(car, prof):
    """年成本 = 固定(保险+保养+车船税) + 能耗×年里程。"""
    return car["insurance"] + car["maint"] + car["road_tax"] + \
        energy_per_km(car, prof) * prof["km_year"]


def upfront(car):
    return car["price"] + car["purchase_tax"]


def tco(car, prof, years):
    return upfront(car) + years * yearly_cost(car, prof)


def cost_breakdown(car, prof):
    """每公里真实口径的解剖(营销口径的差额全在这张表里)。"""
    return [
        ("能耗" + ("" if car["type"] == "gas"
                   else f"(家充 {prof['home_share']:.0%} 加权 {blended_price(prof):.2f} 元/度)"),
         energy_per_km(car, prof)),
        ("保险摊", car["insurance"] / prof["km_year"]),
        ("保养摊", car["maint"] / prof["km_year"]),
        ("车船税摊", car["road_tax"] / prof["km_year"]),
    ]


def yearly_gap(a, b, prof):
    """年成本差分解: a − b,正 = a 每年多花。"""
    return {
        "能耗": (energy_per_km(a, prof) - energy_per_km(b, prof)) * prof["km_year"],
        "保险": a["insurance"] - b["insurance"],
        "保养": a["maint"] - b["maint"],
        "车船税": a["road_tax"] - b["road_tax"],
    }


def payback(car_a, car_b, prof):
    """car_a 相对 car_b 的回本几何。

    返回 (D, S, months): D = upfront_a − upfront_b;S = 年省(yearly_b − yearly_a)。
    三态: D>0 且 S>0 → months = D/(S/12)(贵的靠省追平);
          D>0 且 S≤0 → None(贵又不省,追不平);
          D≤0 → a 落地不贵,S>0 时 months=0(第一天就省),S≤0 时 None
          (a 便宜但更费——追平的是对面,这本账里没有回本)。
    """
    d = upfront(car_a) - upfront(car_b)
    s = yearly_cost(car_b, prof) - yearly_cost(car_a, prof)
    if d <= 0:
        return d, s, (0.0 if s > 0 else None)
    if s <= 0:
        return d, s, None
    return d, s, d / (s / 12)


def payback_walk(d, s, cap_months):
    """第二算法: 逐月游走。返回追平月数或 None(超过 cap_months×10 还没平)。"""
    if d <= 0:
        return 0.0 if s > 0 else None
    if s <= 0:
        return None
    m = 0
    limit = int(cap_months * 10)
    while m <= limit:
        if d - s / 12 * m <= 0:
            return float(m)
        m += 1
    return None


def breakeven_km(pairs, prof, cap_months):
    """翻转里程阈值: 年里程低于多少时,回本超过 cap。

    年成本差是 km_year 的仿射函数: Δ(k) = ΔF + Δe·k,
    回本 > cap ⟺ Δ(k) < 12D/cap ⟺ k < (12D/cap − ΔF)/Δe(Δe<0 时成立)。
    返回闭式阈值,validate 用线性扫描对拍。
    """
    (a, b) = pairs
    d = upfront(a) - upfront(b)
    s_fixed = (b["insurance"] + b["maint"] + b["road_tax"]) - \
              (a["insurance"] + a["maint"] + a["road_tax"])
    e_diff = energy_per_km(a, prof) - energy_per_km(b, prof)
    if e_diff >= 0 or d <= 0:
        return None
    k_star = (12 * d / cap_months - s_fixed) / (-e_diff)
    return max(0.0, k_star)


# ---------------------------------------------------------------- 视图 ----

def _header(ddir):
    print(f"八分钱 · Eight Cents —— {os.path.basename(os.path.normpath(ddir))}")
    print("口径: 营销口径 = 能耗 × 家充电价(100% 家充、只算能耗) · "
          "真实口径 = 能耗 + (保险+保养+车船税)/年里程 · "
          "全款名义加总不折现 · 账本无日期,零墙钟")


def _profiles_line(prof):
    hs = prof["home_share"]
    hs_txt = f"家充 {hs:.0%}({prof['home_price']:.2f} 元/度)" if hs > 0 else "无家充桩"
    return (f"年 {prof['km_year']:,.0f} km · {hs_txt} · "
            f"公充 {prof['public_price']:.2f} 元/度 · 油 {prof['gas_price']:.2f} 元/L")


def _car_block(car, prof, indent="  "):
    """一辆车在一份用车事实下的完整账: 营销口径 vs 真实口径解剖。"""
    mkt = marketing_per_km(car, prof)
    real = real_per_km(car, prof)
    if car["type"] == "gas":
        mkt_label = f"每公里油钱 {fmt_perkm(mkt)}/km = {car['energy100']:g}L/100km × 油 {prof['gas_price']:.2f} 元/L"
    else:
        mkt_label = (f"每公里电费 {fmt_perkm(mkt)}/km = {car['energy100']:g}kWh/100km × "
                     f"家充 {prof['home_price']:.2f} 元/度,按 100% 家充、只算电——销售说的就是这句")
    print(f"{indent}营销口径(他的算法)  {mkt_label}")
    print(f"{indent}真实口径(你的算法)   {fmt_perkm(real)}/km")
    for label2, v in cost_breakdown(car, prof):
        print(f"{indent}  · {pad(label2, 30)}{fmt_perkm(v)}/km")
    ratio = real / mkt if mkt > 0 else float("inf")
    print(f"{indent}  真实是营销的 {ratio:.1f} 倍——"
          f"差额全是保险/保养/税的摊销,营销口径一样没算")
    y = yearly_cost(car, prof)
    fixed = car["insurance"] + car["maint"] + car["road_tax"]
    print(f"{indent}年成本 {fmt_money(y)} = 固定 {fmt_money(fixed)} "
          f"+ 能耗 {fmt_money(y - fixed)}")
    tax_txt = f"{fmt_money(car['purchase_tax'])}({car['tax_source']})"
    print(f"{indent}落地 {fmt_money(upfront(car))} = 车价 {fmt_money(car['price'])} "
          f"+ 购置税 {tax_txt}")
    if car["type"] == "ev" and not car["purchase_tax_raw"]:
        print(f"{indent}  ⚠ 购置税按免征默认——新能源购置税处于减半过渡期,"
              f"以办理日政策为准,purchase_tax 列翻案")
    return mkt, real


# ---------------------------------------------------------------- 命令 ----

def _resolve_profiles(profiles, order, want):
    if want:
        if want not in profiles:
            raise Decline(f"没有这个 profile: {want!r}——账上有: {'、'.join(order)}")
        return [(want, profiles[want])]
    if not order:
        raise Decline("usage.tsv 是空的——抄第一行用车事实"
                      "(profile/km_year/gas_price/home_price/public_price/home_share)")
    return [(p, profiles[p]) for p in order]


def cmd_report(args, cars, profiles, order):
    if not cars:
        raise Decline("cars.tsv 是空的——抄第一辆候选车进账"
                      "(name/type/price/energy100/insurance,一行一辆)")
    chosen = _resolve_profiles(profiles, order, args.profile)
    years = args.years
    red = False

    _header(args.dir)
    print()
    print("■ 用车事实")
    for p, prof in chosen:
        print(f"  {pad(p, 10)}{_profiles_line(prof)}")

    for p, prof in chosen:
        print()
        print(f"■■ profile {p} · {_profiles_line(prof)}")
        rows = []
        for car in cars:
            print()
            print(f"■ {car['name']} ({'油' if car['type'] == 'gas' else '电'})"
                  + (f"  {car['note']}" if car['note'] else ""))
            mkt, real = _car_block(car, prof)
            rows.append((car, mkt, real))
        if len(rows) >= 2:
            print()
            print(f"■ 两本账并排 @ {p}(TCO {years} 年,--years 翻案)")
            for car, mkt, real in rows:
                print(f"  {pad(car['name'], 12)} 真实 {fmt_perkm(real)}/km · "
                      f"年 {fmt_money(yearly_cost(car, prof))} · "
                      f"{years} 年 TCO {fmt_money(tco(car, prof, years))}")
            ranked_tco = sorted(rows, key=lambda r: tco(r[0], prof, years))
            best = ranked_tco[0]
            print(f"  {years} 年 TCO 最便宜: {best[0]['name']} "
                  f"{fmt_money(tco(best[0], prof, years))}")
            if len(ranked_tco) >= 2:
                second = ranked_tco[1]
                print(f"  次便宜 {second[0]['name']} 贵 "
                      f"{fmt_money(tco(second[0], prof, years) - tco(best[0], prof, years))}"
                      f"——差价怎么追平是 breakeven 的舞台,先看灯")

        # 灯
        lamps = []
        for car, mkt, real in rows:
            if car["type"] == "ev":
                ratio = blended_price(prof) / prof["home_price"]
                if ratio > args.penny_line:
                    lamps.append(("red", "PENNY-MYTH",
                                  f"{car['name']} 营销口径按 100% 家充 "
                                  f"{prof['home_price']:.2f} 元/度,你的加权电价 "
                                  f"{blended_price(prof):.2f} 元/度是它的 {ratio:.1f} 倍——"
                                  f"八分钱成立的前提是桩,你的公充占比让每公里电费先翻倍"
                                  f" (--penny-line {args.penny_line})"))
                    red = True
                if prof["home_share"] > args.home_line:
                    saved = (prof["public_price"] - prof["home_price"]) * \
                        car["energy100"] / 100 * prof["km_year"] * prof["home_share"]
                    lamps.append(("blue", "HOME-CHARGING",
                                  f"{car['name']} 家充 {prof['home_share']:.0%}:每度比公充省 "
                                  f"{prof['public_price'] - prof['home_price']:.2f} 元,这个桩一年替你省 "
                                  f"{fmt_money(saved)}——省钱的不是电车,是家充桩"
                                  f" (--home-line {args.home_line})"))
        if len(cars) >= 2:
            ins = sorted(cars, key=lambda c: c["insurance"])
            gap = (ins[-1]["insurance"] - ins[0]["insurance"]) / ins[0]["insurance"] * 100
            if gap > args.ins_gap_line:
                lamps.append(("yellow", "INSURANCE-GAP",
                              f"{ins[-1]['name']} 年保费 {fmt_money(ins[-1]['insurance'])} 比 "
                              f"{ins[0]['name']} {fmt_money(ins[0]['insurance'])} 贵 "
                              f"{gap:.1f}%({fmt_money(ins[-1]['insurance'] - ins[0]['insurance'])}/年)"
                              f"——电车保费贵是真实成本,报价为准,账本已摊进每公里"
                              f" (--ins-gap-line {args.ins_gap_line:g})"))
        # 回本红线(报告口径: 按 TCO 最便宜 vs 最贵两车)
        if len(cars) >= 2:
            ranked = sorted(cars, key=upfront)
            cheap, exp = ranked[0], ranked[-1]
            d, s, months = payback(exp, cheap, prof)
            if months is None:
                lamps.append(("red", "BREAKEVEN-NEVER",
                              f"{exp['name']} 落地多 {fmt_money(d)},每年却省不出钱"
                              f"(年省 {fmt_money(s)})——在你给的参数下追不平,"
                              f"不是电车不好,是这本账跑不出回本"
                              f" (--payback-cap {args.payback_cap:g})"))
                red = True
            elif months > args.payback_cap:
                lamps.append(("red", "BREAKEVEN-NEVER",
                              f"{exp['name']} 落地多 {fmt_money(d)},年省 {fmt_money(s)},"
                              f"要 {months / 12:.1f} 年才追平——超出 "
                              f"--payback-cap {args.payback_cap:g} 月。"
                              f"结论不属于车,属于你的桩和里程"))
                red = True
        if lamps:
            print("灯:")
            for kind, name, text in lamps:
                mark = {"red": "🔴", "yellow": "🟡", "blue": "🔵"}[kind]
                print(f"  {mark} {name}  {text}")
        else:
            print("灯: 无——两本账都在各自的算法里,没有话术溢价")
    print()
    print("下一步: breakeven(回本几何+逐年推演) · validate(恒等式体检)")
    return EXIT_RED if red else EXIT_OK


def cmd_breakeven(args, cars, profiles, order):
    if len(cars) < 2:
        raise Decline("breakeven 对拍的是两辆车——账上至少要有两行候选车")
    if args.pair:
        names = [n.strip() for n in args.pair.split(",")]
        if len(names) != 2:
            raise Decline("--pair 要两个车名,逗号分隔: --pair 车A,车B")
        by_name = {c["name"]: c for c in cars}
        for n in names:
            if n not in by_name:
                raise Decline(f"账上没有这辆车: {n!r}——账上有: {'、'.join(c['name'] for c in cars)}")
        pair = [by_name[names[0]], by_name[names[1]]]
    elif len(cars) == 2:
        pair = list(cars)
    else:
        raise Decline(f"账上有 {len(cars)} 辆车——breakeven 对拍两辆,"
                      f"用 --pair 车A,车B 挑两辆")
    chosen = _resolve_profiles(profiles, order, args.profile)
    red = False

    _header(args.dir)
    a, b = pair
    for p, prof in chosen:
        print()
        print(f"■ 回本几何 @ {p} · {_profiles_line(prof)}")
        # 统一叙述方向: 落地贵的那辆靠年节省追平自己多付的差价
        if upfront(a) >= upfront(b):
            exp, chp = a, b
        else:
            exp, chp = b, a
        d, s, months = payback(exp, chp, prof)
        dd, ss = d, s
        if dd == 0 and ss == 0:
            print(f"  {a['name']} 与 {b['name']} 落地同价、年成本同价——这两本账是同一本")
            continue
        if months == 0.0:
            print(f"  {chp['name']} 落地不多付、每年还省 {fmt_money(ss)}——"
                  f"回本不需要时间,从第一天就开始省")
            continue
        print(f"  贵的: {pad(exp['name'], 12)} 落地多 {fmt_money(dd)} "
              f"(车价+购置税,一次性)")
        gap = yearly_gap(exp, chp, prof)
        parts = " · ".join(
            (f"{'省' if -v > 0 else '多花'} {fmt_money(abs(v))}({k})"
             for k, v in gap.items() if abs(v) > 0.005))
        print(f"  每年省 {fmt_money(ss)}: {parts}")
        if months is None:
            print(f"  回本: 追不平——贵车每年反而多花 {fmt_money(-ss)},"
                  f"这笔差价不是投资是支出")
            red = True
        else:
            verdict = (f"{months:.1f} 个月 ≈ {months / 12:.1f} 年")
            inside = months <= args.payback_cap
            print(f"  回本: {verdict}(闭式 D/(S/12);逐月游走见 validate)"
                  + ("" if inside else
                     f" —— 超出 --payback-cap {args.payback_cap:g} 月,追不平"))
            if not inside:
                red = True
            print(f"  推演(--years {args.years}):")
            for y in range(1, args.years + 1):
                cum = dd - ss * y
                mark = " ← 反超" if cum <= 0 and (dd - ss * (y - 1)) > 0 else ""
                print(f"    第 {y:>2} 年: 贵车累计多花 {fmt_money(cum)}{mark}")
            k_star = breakeven_km((exp, chp), prof, args.payback_cap)
            if k_star is not None:
                print(f"  翻转里程: 年里程 < {k_star:,.0f} km 时回本超出 "
                      f"{args.payback_cap:g} 月——结论不属于车,属于你的桩和里程")
    print()
    print("诚实条款: 折旧/电池风险/绿牌路权不建模,贷款不建模(全款口径)——"
          "要算进账,把它们摊进 maint 或 purchase_tax,账本照算")
    return EXIT_RED if red else EXIT_OK


def cmd_validate(args, cars, profiles, order):
    if not cars:
        raise Decline("cars.tsv 是空的")
    if not order:
        raise Decline("usage.tsv 是空的")
    chosen = _resolve_profiles(profiles, order, args.profile)

    print(f"账本体检 —— {os.path.basename(os.path.normpath(args.dir))}")
    ok = True

    # 1) 每公里真实口径双路径: 分项加总 == 直接公式;年成本两路径互逆
    n = 0
    perkm_ok = True
    for p, prof in chosen:
        for car in cars:
            parts = sum(v for _, v in cost_breakdown(car, prof))
            if abs(parts - real_per_km(car, prof)) > 1e-9:
                perkm_ok = False
            if abs(real_per_km(car, prof) * prof["km_year"] - yearly_cost(car, prof)) > 1e-6:
                perkm_ok = False
            n += 1
    print(f"  每公里真实口径: 分项加总 == 直接公式,× km_year == 年成本 "
          f"({n} 车·profile) {'✓' if perkm_ok else '✗'}")
    ok = ok and perkm_ok

    # 2) 加权电价 == 分段对拍: 加权价×总电量 == 家充段 + 公充段
    blend_ok = True
    for p, prof in chosen:
        for car in cars:
            if car["type"] != "ev":
                continue
            kwh = car["energy100"] / 100 * prof["km_year"]
            seg = kwh * prof["home_share"] * prof["home_price"] + \
                kwh * (1 - prof["home_share"]) * prof["public_price"]
            whole = kwh * blended_price(prof)
            if abs(seg - whole) > 1e-6:
                blend_ok = False
    print(f"  加权电价: 加权价×总电量 == 家充段+公充段分段 "
          f"{'✓' if blend_ok else '✗'}")
    ok = ok and blend_ok

    # 3) TCO 双路径: 闭式 == 逐年累加
    tco_ok = True
    for p, prof in chosen:
        for car in cars:
            closed = tco(car, prof, args.years)
            walked = upfront(car)
            for y in range(1, args.years + 1):
                walked += yearly_cost(car, prof)
            if abs(closed - walked) > 1e-6:
                tco_ok = False
    print(f"  TCO {args.years} 年: 闭式 == 逐年累加 {'✓' if tco_ok else '✗'}")
    ok = ok and tco_ok

    # 4) 回本双路径: 闭式 == 逐月游走(含追平/追不平/第一天就省三态)
    pb_ok = True
    pb_n = 0
    for p, prof in chosen:
        for i in range(len(cars)):
            for j in range(len(cars)):
                if i == j:
                    continue
                d, s, months = payback(cars[i], cars[j], prof)
                walked = payback_walk(d, s, args.payback_cap)
                if (months is None) != (walked is None):
                    pb_ok = False
                elif months is not None and walked is not None and \
                        abs(months - walked) > 1.01:
                    pb_ok = False
                pb_n += 1
    print(f"  回本几何: 闭式 == 逐月游走 ({pb_n} 对·profile,含 0/恰 cap/追不平三态) "
          f"{'✓' if pb_ok else '✗'}")
    ok = ok and pb_ok

    # 5) 翻转里程阈值: 闭式反解 == 线性扫描
    k_ok = True
    k_n = 0
    if len(cars) >= 2:
        for p, prof in chosen:
            ranked = sorted(cars, key=upfront)
            k_star = breakeven_km((ranked[-1], ranked[0]), prof, args.payback_cap)
            if k_star is None:
                continue
            k_n += 1
            # 二分扫描: km 越大回本越短,找 payback 恰跨 cap 的最小里程
            lo, hi = 0.0, 500000.0
            for _ in range(60):
                mid = (lo + hi) / 2
                p2 = dict(prof)
                p2["km_year"] = mid
                d, s, m = payback(ranked[-1], ranked[0], p2)
                if m is None or m > args.payback_cap:
                    lo = mid
                else:
                    hi = mid
            if abs(hi - k_star) > max(1.0, k_star * 1e-3):
                k_ok = False
    print(f"  翻转里程阈值: 闭式反解 == 二分扫描 ({k_n} 对·profile) "
          f"{'✓' if k_ok else '✗'}")
    ok = ok and k_ok

    # 6) 购置税来源披露
    defaulted = [c for c in cars if not c["purchase_tax_raw"]]
    if defaulted:
        print("  购置税通识默认: " + "、".join(
            f"{c['name']} {fmt_money(c['purchase_tax'])}({c['tax_source']})"
            for c in defaulted))
        ev_def = [c for c in defaulted if c["type"] == "ev"]
        if ev_def:
            print("    ⚠ " + "、".join(c["name"] for c in ev_def)
                  + " 按免征默认——新能源购置税处于减半过渡期,以办理日政策为准,"
                  "purchase_tax 列翻案")

    if ok:
        print("\n体检 全部通过 ✓——账坏 exit 2 在载入层就已拦下"
              "(缺列/未知键/type 非枚举/负价格/能耗非正/km_year≤0/home_share 出界)")
        return EXIT_OK
    print("\n体检 未通过 ✗")
    return EXIT_BAD


# ---------------------------------------------------------------- main ----

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="八分钱 · Eight Cents — 油电购车的话术翻译器")
    ap.add_argument("--dir", default=".", help="账本目录(缺省当前目录)")
    ap.add_argument("--profile", default=None,
                    help="只算这个用车 profile(缺省全部逐个出账)")
    ap.add_argument("--years", type=int, default=YEARS,
                    help=f"TCO 年限 (缺省 {YEARS})")
    ap.add_argument("--penny-line", type=float, default=PENNY_LINE,
                    help=f"PENNY-MYTH 倍数线 (缺省 {PENNY_LINE})")
    ap.add_argument("--ins-gap-line", dest="ins_gap_line", type=float,
                    default=INS_GAP_LINE, help=f"保费差灯线%% (缺省 {INS_GAP_LINE:g})")
    ap.add_argument("--home-line", type=float, default=HOME_LINE,
                    help=f"HOME-CHARGING 家充占比线 (缺省 {HOME_LINE})")
    ap.add_argument("--payback-cap", dest="payback_cap", type=float,
                    default=PAYBACK_CAP, help=f"回本红线月 (缺省 {PAYBACK_CAP})")
    ap.add_argument("--gas-tax-rate", dest="gas_tax_rate", type=float,
                    default=GAS_TAX_RATE,
                    help=f"燃油购置税率 (缺省 {GAS_TAX_RATE:.0%})")
    ap.add_argument("--pair", default=None,
                    help="breakeven: 对拍的两辆车,逗号分隔")
    ap.add_argument("command", nargs="?", default="report",
                    choices=["report", "breakeven", "validate"])
    args = ap.parse_args(argv)

    try:
        cars, (profiles, order) = load_ledger(args.dir, args.gas_tax_rate)
        if args.command == "report":
            return cmd_report(args, cars, profiles, order)
        if args.command == "breakeven":
            return cmd_breakeven(args, cars, profiles, order)
        if args.command == "validate":
            return cmd_validate(args, cars, profiles, order)
    except LedgerBad as e:
        print(f"账坏: {e}", file=sys.stderr)
        return EXIT_BAD
    except Decline as e:
        print(f"拒答: {e}", file=sys.stderr)
        return EXIT_EMPTY
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
