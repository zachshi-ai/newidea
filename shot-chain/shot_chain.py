#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot-chain · 针链 —— 宠物免疫/驱虫的对账账本.

问题:免疫不是一年一次的事件,是一条不能断的链。猫三联、犬联苗、
狂犬是年钟/三年钟,体外驱虫、心丝虫是月月钟——链的连续性决定免疫
是否有效,疫苗周期中断的代价不是「补一针」,而是按未免疫重新起链。
但疫苗本的持有人是医院,不是主人:免疫史散落在打过针的每一家医院
的系统里,换一家医院就死一次。日历记行程、账单记钱、相册记生活,
没有任何一本账记录「它、哪条链、末针哪天、断没断」。而有五个时刻
是别人向你要这本账的:换医院、搬家、寄养、托运、抓咬暴露。

shot-chain 把每一针记成一行接种事件(TSV:type/pet/item/date/note),
把六条免疫链的周期先验内置(公开常识,--cycle/--grace 一句话翻案,
兽医的程序永远赢),对同一本账开四个命令:report 全量对账单(每宠
每链一盏灯)、next 行动清单(只列要动手的,贴冰箱那一行)、brief
交接卡(寄养/托运/新兽医核对的一页纸)、validate 账本体检验证恒等式。

三条设计立场:
  * 账本管的不是「下一次怎么打」,是「这条链断没断」——幼年系列、
    加强程序、抗体检测是兽医的判断题;链断之后账本只说「下一针不
    是补一针」,不冒充兽医。
  * 周期全部是公开常识先验且全部可翻案(--cycle/--grace/--warn);
    狂犬宽容线为零——法规不讲宽容,证上的有效期印着,寄养机构照
    着念。没有先验的链(自定义)如实拒判——不发明没教过的链。
  * 零墙钟:缺省 as-of 锚定账本最大日期(如实披露),--as-of 钉死
    即逐字节可复现;同账任何机器任何一天输出一致。

零依赖:Python 3.8+ 标准库。

Exit codes:
  0  report produced   2  usage/账本缺失/坏行
  3  refusal: 空账     4  gate: BROKEN/DUE/MISSING 任一
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import unicodedata
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

PROG = "shot-chain"
VERSION = "1.0.0"

# ---------------------------------------------------------------- 词表
# 六条链:canonical 名、中文名、内置周期先验(天)、宽容线(天)。
# 全部是公开常识先验——宠物医院门口海报都印着的数字,不是医嘱;
# --cycle 链:天数 / --grace 链:天数 一句话翻案,兽医的程序永远赢。
Chain = Tuple[str, int, int]  # (中文名, cycle_days, grace_days)

CHAINS: Dict[str, Chain] = {
    "fvrcp":    ("猫三联",   1095, 60),   # WSAVA/AAHA 成年猫 3 年周期
    "core-dog": ("犬联苗",   1095, 60),   # 犬核心联苗 3 年周期
    "rabies":   ("狂犬",      365, 0),    # 城市年度法规;宽容为零
    "flea":     ("体外驱虫",   30, 15),   # 多数外用产品月月
    "worm":     ("体内驱虫",   90, 15),   # 成年每 3 个月通识
    "hw":       ("心丝虫",     30, 15),   # 蚊媒,月月
}

# 物种 → 适用链。物种与链矛盾是抄录错误(cat 记 core-dog),exit 2。
SPECIES_CHAINS: Dict[str, List[str]] = {
    "cat": ["fvrcp", "rabies", "flea", "worm"],
    "dog": ["core-dog", "rabies", "flea", "worm", "hw"],
}

SPECIES_ZH = {"cat": "猫", "dog": "狗"}

# 别名归一:词表上的名字五花八门,链只有一个名字。
ITEM_ALIASES = {
    "fvrcp": "fvrcp", "猫三联": "fvrcp", "三联": "fvrcp", "猫三联疫苗": "fvrcp",
    "core-dog": "core-dog", "犬联苗": "core-dog", "联苗": "core-dog",
    "四联": "core-dog", "六联": "core-dog", "八联": "core-dog",
    "犬四联": "core-dog", "犬六联": "core-dog", "犬八联": "core-dog",
    "dhpp": "core-dog", "dhlpp": "core-dog",
    "rabies": "rabies", "狂犬": "rabies", "狂犬疫苗": "rabies",
    "flea": "flea", "体外": "flea", "体外驱虫": "flea", "跳蚤": "flea", "蜱虫": "flea",
    "worm": "worm", "体内": "worm", "体内驱虫": "worm", "打虫": "worm",
    "肠道驱虫": "worm",
    "hw": "hw", "heartworm": "hw", "心丝虫": "hw", "心丝虫预防": "hw",
}

SPECIES_ALIASES = {
    "cat": "cat", "猫": "cat", "猫咪": "cat", "英短": "cat",
    "dog": "dog", "狗": "dog", "狗狗": "dog", "犬": "dog",
}

HEADER = ["type", "pet", "item", "date", "note"]

# ---------------------------------------------------------------- 归一
def norm_token(s: str) -> str:
    """词归一:NFKC + 去全部空白 + 小写——「猫 三联」式抄录差异不分裂账本."""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s).lower()


def norm_item(s: str) -> str:
    n = norm_token(s)
    if n in ITEM_ALIASES:
        return ITEM_ALIASES[n]
    raise ValueError(f"未知链「{s}」——不发明没教过的链(词表:{' '.join(CHAINS)})")


def norm_species(s: str) -> str:
    n = norm_token(s)
    if n in SPECIES_ALIASES:
        return SPECIES_ALIASES[n]
    raise ValueError(f"未知物种「{s}」(词表:cat/dog,中文短名也收)")


# ---------------------------------------------------------------- 日期
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s: str) -> dt.date:
    if not DATE_RE.match(s):
        raise ValueError(f"坏日期「{s}」——要 YYYY-MM-DD 补零格式,缺零拒绝")
    try:
        return dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        raise ValueError(f"坏日期「{s}」——不是真实存在的日子(如 2026-02-30)")


# ---------------------------------------------------------------- 账本
class Ledger:
    def __init__(self):
        self.pets: "OrderedDict[str, dict]" = OrderedDict()  # 名 → {species, line, note}
        self.shots: List[dict] = []  # {pet, item, date, note, line}

    @property
    def pet_names(self) -> List[str]:
        return list(self.pets.keys())


def parse_tsv(path: str) -> Ledger:
    """载入账本。行型:pet 行(登记)与 shot 行(接种)。

    手编从表格粘贴不拘小节:右侧缺列视为空;超过 5 列拒;
    行尾制表符容忍。shot 允许前向引用(先记针后登记宠)。
    """
    if not os.path.exists(path):
        raise SystemExitWith(2, f"{PROG}: 找不到账本 {path}")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    led = Ledger()
    lines = raw.split("\n")
    seen_header = False
    for lineno, line in enumerate(lines, start=1):
        if line.endswith("\r"):
            line = line[:-1]
        if line.endswith("\t"):
            line = line.rstrip("\t")  # 行尾制表符容忍:表格粘贴的日常
        if not line.strip():
            continue
        if line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) > 5:
            raise SystemExitWith(2, f"账本第 {lineno} 行:列数 {len(cols)} > 5")
        cols += [""] * (5 - len(cols))
        if not seen_header:
            if [c.strip().lower() for c in cols[:2]] == ["type", "pet"]:
                seen_header = True
                continue
            raise SystemExitWith(2, f"账本第 1 行须是表头 {'/'.join(HEADER)}(空行注释除外)")
        rtype = norm_token(cols[0])
        name = cols[1].strip()
        if rtype == "pet":
            if not name:
                raise SystemExitWith(2, f"账本第 {lineno} 行:pet 行缺名字")
            if name in led.pets:
                raise SystemExitWith(2, f"账本第 {lineno} 行:宠物「{name}」重复登记(首次在第 {led.pets[name]['line']} 行)")
            if not cols[2].strip():
                raise SystemExitWith(2, f"账本第 {lineno} 行:pet「{name}」缺物种(cat/dog)")
            try:
                species = norm_species(cols[2])
            except ValueError as e:
                raise SystemExitWith(2, f"账本第 {lineno} 行:{e}")
            led.pets[name] = {"species": species, "line": lineno, "note": cols[4].strip()}
        elif rtype == "shot":
            if not name:
                raise SystemExitWith(2, f"账本第 {lineno} 行:shot 行缺宠物名")
            if not cols[2].strip():
                raise SystemExitWith(2, f"账本第 {lineno} 行:shot「{name}」缺链(item)")
            try:
                item = norm_item(cols[2])
            except ValueError as e:
                raise SystemExitWith(2, f"账本第 {lineno} 行:{e}")
            if not cols[3].strip():
                raise SystemExitWith(2, f"账本第 {lineno} 行:shot「{name}/{item}」缺接种日期")
            try:
                date = parse_date(cols[3].strip())
            except ValueError as e:
                raise SystemExitWith(2, f"账本第 {lineno} 行:{e}")
            led.shots.append({"pet": name, "item": item, "date": date,
                              "note": cols[4].strip(), "line": lineno})
        else:
            raise SystemExitWith(2, f"账本第 {lineno} 行:未知行型「{cols[0].strip()}」(词表:pet/shot)")
    if not seen_header:
        raise SystemExitWith(2, "账本没有表头行")
    # 前向引用落地:shot 指向的宠必须(迟早)被登记
    for s in led.shots:
        if s["pet"] not in led.pets:
            raise SystemExitWith(2, f"账本第 {s['line']} 行:shot 指向未登记的宠物「{s['pet']}」")
    # 物种与链矛盾 = 抄录错误
    for s in led.shots:
        species = led.pets[s["pet"]]["species"]
        if s["item"] not in SPECIES_CHAINS[species]:
            raise SystemExitWith(
                2, f"账本第 {s['line']} 行:{SPECIES_ZH[species]}「{s['pet']}」不适用链"
                   f"「{CHAINS[s['item']][0]}」——物种与链矛盾,疑抄录错误")
    if not led.pets:
        raise SystemExitWith(3, f"{PROG}: 空账——没有 pet 行,无从对账(拒绝判空)")
    return led


class SystemExitWith(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg


# ---------------------------------------------------------------- 链引擎
def chains_for(species: str) -> List[str]:
    return SPECIES_CHAINS[species]


def eff_cycles(cycles: Dict[str, int], graces: Dict[str, int],
               warn: int) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    """先验 + 翻案合成。预警窗不超过周期的三分之一——月月钟不永远黄着."""
    if warn < 0:
        raise SystemExitWith(2, f"--warn: 预警窗须 ≥ 0,收到 {warn}")
    warn_eff = {}
    for item, (zh, cyc, grace) in CHAINS.items():
        cyc = cycles.get(item, cyc)
        warn_eff[item] = min(warn, max(1, cyc // 3))
    for item, v in cycles.items():
        if item not in CHAINS:
            raise SystemExitWith(2, f"--cycle: 未知链「{item}」")
        if v <= 0:
            raise SystemExitWith(2, f"--cycle: 周期须为正天数,收到 {v}")
    for item, v in graces.items():
        if item not in CHAINS:
            raise SystemExitWith(2, f"--grace: 未知链「{item}」")
        if v < 0:
            raise SystemExitWith(2, f"--grace: 宽容线须 ≥ 0,收到 {v}")
    return cycles, graces, warn_eff


def build_links(led: Ledger, cycles: Dict[str, int], graces: Dict[str, int],
                warn_eff: Dict[str, int], as_of: dt.date) -> Tuple[List[dict], int]:
    """每宠 × 适用链 → 一条 link(dict):灯、末针、到期日、断线日、行号.

    as-of 剪切:晚于 as-of 的针是「后视行」——时间机器看当时的世界,
    状态灯对它们不可见;剪掉几针如实披露,不假装没记过。
    """
    by_key: Dict[Tuple[str, str], List[dict]] = {}
    by_key_all: Dict[Tuple[str, str], List[dict]] = {}
    clipped = 0
    for s in led.shots:
        by_key_all.setdefault((s["pet"], s["item"]), []).append(s)
        if s["date"] > as_of:
            clipped += 1
            continue
        by_key.setdefault((s["pet"], s["item"]), []).append(s)

    links = []
    for name, pet in led.pets.items():
        for item in chains_for(pet["species"]):
            shots = sorted(by_key.get((name, item), []), key=lambda x: (x["date"], x["line"]))
            zh, cyc_d, grace_d = CHAINS[item]
            cyc = cycles.get(item, cyc_d)
            grace = graces.get(item, grace_d)
            link = {"pet": name, "species": pet["species"], "item": item,
                    "zh": zh, "cycle": cyc, "grace": grace,
                    "shots": shots, "n": len(shots)}
            if not shots:
                # 全时间零记录 = 领养盲区(MISSING,抬闸);
                # 剪切后零记录 = 第一针还没打(NOT-YET,不抬闸——
                # 时间机器看当时的世界,没打过的针不构成盲区指控)
                ever = [x for x in by_key_all.get((name, item), [])]
                if ever:
                    first = min(ever, key=lambda x: (x["date"], x["line"]))
                    link["state"] = "NOT-YET"
                    link["first"] = first
                else:
                    link["state"] = "MISSING"
                links.append(link)
                continue
            last = shots[-1]
            link["last"] = last
            due = last["date"] + dt.timedelta(days=cyc)
            dead = due + dt.timedelta(days=grace)
            warn_eff_d = warn_eff[item]
            link["due"], link["dead"] = due, dead
            link["warn_eff"] = warn_eff_d
            if as_of > dead:
                link["state"] = "BROKEN"
                link["over"] = (as_of - dead).days  # 断线已过天数
            elif (as_of - due).days >= 0:
                link["state"] = "DUE"  # 已到期、宽容内(恰线即亮)
                link["over"] = (as_of - due).days
                link["left"] = (dead - as_of).days
            elif (due - as_of).days <= warn_eff_d:
                link["state"] = "DUE"  # 预警窗内
                link["over"] = None
                link["left"] = (due - as_of).days
            else:
                link["state"] = "OK"
                link["left"] = (due - as_of).days
            links.append(link)
    return links, clipped


def default_as_of(led: Ledger) -> dt.date:
    if not led.shots:
        raise SystemExitWith(
            3, "薄账——只有登记、还没有任何一针,缺省锚定无从谈起:"
               "钉 --as-of 出全盲区对账单,或先记第一针")
    return max(s["date"] for s in led.shots)


LIGHT = {"BROKEN": "🔴", "DUE": "🟡", "MISSING": "🔴", "OK": "🟢", "NOT-YET": "⚪"}
LIGHT_ZH = {"BROKEN": "链断", "DUE": "该动手", "MISSING": "盲区", "OK": "OK",
            "NOT-YET": "未起链"}


def is_lit(link: dict) -> bool:
    return link["state"] in ("BROKEN", "DUE", "MISSING")


# ---------------------------------------------------------------- 排版
def dw(s: str) -> int:
    """显示宽度:全角 2、半角 1(对齐用)."""
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return w


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dw(s))


def action_line(link: dict) -> str:
    """一行动作指令:链断了说什么、到期了说什么、盲区说什么."""
    st = link["state"]
    item = link["item"]
    if st == "BROKEN":
        if item in ("fvrcp", "core-dog"):
            return "链已断——下一针不是补一针,是重新起链:约兽医(重新全套或先做抗体检测)"
        if item == "rabies":
            return ("链已断——狂犬是法定管理人畜共患病:逾期接种的它抓咬了人,"
                    "人要打疫苗、它要隔离观察;先约兽医重新接种")
        if item == "hw":
            return ("链已断——蚊媒月月钟,漏的不只是一次:补做前跟兽医确认"
                    "是否需要先做心丝虫抗原检测")
        return "链已断——立即补做;中断多轮先跟兽医确认要不要补检"
    if st == "DUE":
        if link.get("over") is not None:
            return f"已逾期 {link['over']} 天,宽容还剩 {link['left']} 天——窗口内补上,链不断"
        return f"距到期还剩 {link['left']} 天——预警窗已亮,提前约"
    if st == "MISSING":
        return ("零记录——不是账坏,是盲区(领养/捡回的免疫史跟着上一个主人失散了);"
                "带它验一次抗体,盲区就能变成实线")
    return ""


# ---------------------------------------------------------------- 命令
def cmd_report(args) -> int:
    led = parse_tsv(args.ledger)
    as_of = parse_date(args.as_of) if args.as_of else default_as_of(led)
    anchored = "" if args.as_of else "(未钉 as-of,缺省锚定账本末日)"
    cycles, graces, warn_eff = eff_cycles(args.cycle or {}, args.grace or {}, args.warn)
    links, clipped = build_links(led, cycles, graces, warn_eff, as_of)

    out = []
    out.append(f"针链 · Shot Chain —— 免疫对账单(as-of {as_of}){anchored}")
    if clipped:
        out.append(f"时间机器:剪掉晚于 as-of 的 {clipped} 针后视行——看当时的世界,如实不隐去")
    out.append("")
    lit = [l for l in links if is_lit(l)]
    for name, pet in led.pets.items():
        out.append(f"{name}({SPECIES_ZH[pet['species']]})"
                   + (f" —— {pet['note']}" if pet["note"] else ""))
        for l in [x for x in links if x["pet"] == name]:
            if l["state"] == "OK":
                out.append(f"  {pad(l['zh'], 10)}{LIGHT['OK']} OK    "
                           f"末针 {l['last']['date']} (L{l['last']['line']}) → 下次 {l['due']}"
                           f"(余 {l['left']} 天)")
            elif l["state"] == "DUE":
                if l.get("over") is not None:
                    body = f"末针 {l['last']['date']} (L{l['last']['line']}) → 到期 {l['due']},已逾期 {l['over']} 天,宽容至 {l['dead']}"
                else:
                    body = f"末针 {l['last']['date']} (L{l['last']['line']}) → 到期 {l['due']}(余 {l['left']} 天)"
                out.append(f"  {pad(l['zh'], 10)}{LIGHT['DUE']} DUE   " + body)
            elif l["state"] == "BROKEN":
                out.append(f"  {pad(l['zh'], 10)}{LIGHT['BROKEN']} BROKEN "
                           f"链断于 {l['dead']}(已过 {l['over']} 天)——"
                           f"末针 {l['last']['date']} (L{l['last']['line']})")
            elif l["state"] == "NOT-YET":
                out.append(f"  {pad(l['zh'], 10)}{LIGHT['NOT-YET']} 未起链 "
                           f"第一针 {l['first']['date']} (L{l['first']['line']}) 在 as-of 之后")
            else:  # MISSING
                out.append(f"  {pad(l['zh'], 10)}{LIGHT['MISSING']} MISSING 零记录——免疫史的盲区")
            act = action_line(l)
            if act and is_lit(l):
                out.append(f"  {pad('', 10)}↳ {act}")
        out.append("")
    nb = sum(1 for l in lit if l["state"] == "BROKEN")
    nm = sum(1 for l in lit if l["state"] == "MISSING")
    nd = sum(1 for l in lit if l["state"] == "DUE")
    nok = sum(1 for l in links if l["state"] == "OK")
    nny = sum(1 for l in links if l["state"] == "NOT-YET")
    out.append(f"—— {len(led.pets)} 宠 {len(led.shots)} 针 · {len(links)} 链 · "
               f"灯 🔴{nb + nm}(断{nb}/盲{nm}) 🟡{nd} 🟢{nok}"
               + (f" ⚪{nny}(时间机器下的未起链)" if nny else ""))
    if lit:
        out.append("账面带灯:免疫对账不完备(exit 4)——next 看行动清单,brief 出交接卡")
    print("\n".join(out))
    return 4 if lit else 0


def cmd_next(args) -> int:
    led = parse_tsv(args.ledger)
    as_of = parse_date(args.as_of) if args.as_of else default_as_of(led)
    anchored = "" if args.as_of else "(未钉 as-of,缺省锚定账本末日)"
    cycles, graces, warn_eff = eff_cycles(args.cycle or {}, args.grace or {}, args.warn)
    links, _ = build_links(led, cycles, graces, warn_eff, as_of)
    lit = [l for l in links if is_lit(l)]

    out = []
    if not lit:
        print(f"针链 · 针链无灯(as-of {as_of}){anchored}——"
              f"{len(led.pets)} 宠 {len(links)} 链全绿,今天没有要动手的针")
        return 0
    out.append(f"针链 · 行动清单(as-of {as_of}){anchored}——按截止日升序,贴冰箱的那一行")
    out.append("")

    def sort_key(l):
        # BROKEN 按断线日(早已断的排前),DUE 按宽容截止日,MISSING 无日殿后
        if l["state"] == "BROKEN":
            return (0, l["dead"], l["pet"], l["item"])
        if l["state"] == "DUE":
            return (1, l["dead"], l["pet"], l["item"])
        return (2, dt.date.max, l["pet"], l["item"])

    for l in sorted(lit, key=sort_key):
        if l["state"] == "BROKEN":
            head = f"{LIGHT['BROKEN']} {l['pet']}·{l['zh']}  断线 {l['dead']}(已过 {l['over']} 天)"
        elif l["state"] == "DUE":
            head = f"{LIGHT['DUE']} {l['pet']}·{l['zh']}  截止 {l['dead']}"
        else:
            head = f"{LIGHT['MISSING']} {l['pet']}·{l['zh']}  无日期可排"
        out.append(head)
        out.append(f"  ↳ {action_line(l)}")
        out.append(f"    (账本 L{l['last']['line'] if l['shots'] else led.pets[l['pet']]['line']})")
    out.append(f"—— {len(lit)} 链要动手(🔴{sum(1 for x in lit if x['state'] != 'DUE')} 🟡{sum(1 for x in lit if x['state'] == 'DUE')})")
    print("\n".join(out))
    return 4


def cmd_brief(args) -> int:
    led = parse_tsv(args.ledger)
    as_of = parse_date(args.as_of) if args.as_of else default_as_of(led)
    anchored = "" if args.as_of else "(未钉 as-of,缺省锚定账本末日)"
    cycles, graces, warn_eff = eff_cycles(args.cycle or {}, args.grace or {}, args.warn)
    links, _ = build_links(led, cycles, graces, warn_eff, as_of)

    out = []
    out.append(f"针链 · 交接卡(as-of {as_of}){anchored}")
    out.append("给寄养/托运/新兽医的一页纸:链的状态、末针在哪、下次何时,核对栏照抄即可")
    out.append("=" * 56)
    for name, pet in led.pets.items():
        out.append(f"{name}({SPECIES_ZH[pet['species']]})"
                   + (f" —— {pet['note']}" if pet["note"] else ""))
        for l in [x for x in links if x["pet"] == name]:
            if l["state"] == "OK":
                body = f"末针 {l['last']['date']} · 下次 {l['due']} · 有效"
            elif l["state"] == "DUE":
                if l.get("over") is not None:
                    body = f"末针 {l['last']['date']} · 已到期 {l['due']} · 宽容至 {l['dead']}"
                else:
                    body = f"末针 {l['last']['date']} · {l['due']} 到期(余 {l['left']} 天)"
            elif l["state"] == "BROKEN":
                body = f"链断于 {l['dead']} · 末针 {l['last']['date']} · 需重新起链"
            elif l["state"] == "NOT-YET":
                body = f"第一针 {l['first']['date']} 在 as-of 之后 · 当时未接种"
            else:
                body = "零记录 · 免疫史不明"
            out.append(f"  {pad(l['zh'], 10)}{LIGHT[l['state']]} {LIGHT_ZH[l['state']]}  {body}")
        out.append("")
    out.append("寄养/托运机构核对栏:")
    out.append("  □ 狂犬证在有效期(到期日横跨寄养期的,先补种再入住)")
    out.append("  □ 体外驱虫入住前 48h 已做")
    out.append("  □ 疫苗本/免疫证明复印件随行")
    out.append("  □ 本卡由主人照账本如实填写,机构照单核验")
    lit = [l for l in links if is_lit(l)]
    out.append(f"—— {len(links)} 链,亮灯 {len(lit)} 条" + ("(exit 4)" if lit else "(exit 0)"))
    print("\n".join(out))
    return 4 if lit else 0


# ---------------------------------------------------------------- validate
def replay_from_text(path: str) -> Dict[Tuple[str, str], List[Tuple[dt.date, int]]]:
    """路径B:从原始文本独立重放——不经过 parse_tsv 的产物,逐行累计.

    双路径重放的意义:解析层(路径A)与文本层(路径B)互为对照,
    任何一层对账本的理解发生了漂移,重放就会当场对不上。
    """
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    replay: Dict[Tuple[str, str], List[Tuple[dt.date, int]]] = {}
    species_by_name: Dict[str, str] = {}
    for lineno, line in enumerate(raw.split("\n"), start=1):
        if line.endswith("\r"):
            line = line[:-1]
        if line.rstrip("\t") == "" or line.startswith("#"):
            continue
        cols = line.rstrip("\t").split("\t")
        if len(cols) > 5 or seen_header_ok(cols):
            continue
        rtype = norm_token(cols[0])
        if rtype == "pet" and cols[1].strip() and cols[2].strip():
            try:
                species_by_name[cols[1].strip()] = norm_species(cols[2])
            except ValueError:
                pass
        elif rtype == "shot" and cols[1].strip() and cols[2].strip() and DATE_RE.match(cols[3].strip()):
            try:
                item = norm_item(cols[2])
                replay.setdefault((cols[1].strip(), item), []).append(
                    (parse_date(cols[3].strip()), lineno))
            except (ValueError, SystemExitWith):
                pass
    return replay


def seen_header_ok(cols) -> bool:
    if not cols:
        return False
    return [c.strip().lower() for c in cols[:2]] == ["type", "pet"]


def cmd_validate(args) -> int:
    led = parse_tsv(args.ledger)
    problems: List[str] = []

    # 恒等式一:Σ 账本 shot 行 ≡ Σ 各宠各(非空)链针数 —— 逐行守恒
    # 双路径重放:路径A = 解析层聚合;路径B = 文本层独立重放
    a_total = len(led.shots)
    path_a: Dict[Tuple[str, str], List[dict]] = {}
    for s in led.shots:
        path_a.setdefault((s["pet"], s["item"]), []).append(s)
    path_b = replay_from_text(args.ledger)
    b_total = sum(len(v) for v in path_b.values())
    if a_total != b_total:
        problems.append(f"恒等式破坏:Σshot 行 {a_total} ≠ 文本重放 {b_total}")

    keys_a = set(path_a)
    keys_b = set(path_b)
    if keys_a != keys_b:
        only_a = keys_a - keys_b
        only_b = keys_b - keys_a
        problems.append(f"重放键漂移:解析层独有 {sorted(only_a)},文本层独有 {sorted(only_b)}")

    # 逐宠逐链:针数、末针日期、末针行号——三字段全等
    for k in sorted(keys_a & keys_b):
        sa = sorted(path_a[k], key=lambda x: (x["date"], x["line"]))
        sb = sorted(path_b[k], key=lambda x: (x[0], x[1]))
        if len(sa) != len(sb):
            problems.append(f"重放针数不等:{k[0]}/{k[1]} 解析层 {len(sa)} vs 文本层 {len(sb)}")
            continue
        last_a, last_b = sa[-1], sb[-1]
        if (last_a["date"], last_a["line"]) != (last_b[0], last_b[1]):
            problems.append(f"重放末针漂移:{k[0]}/{k[1]} "
                            f"解析层 {last_a['date']}(L{last_a['line']}) vs "
                            f"文本层 {last_b[0]}(L{last_b[1]})")

    # 恒等式二:非空链数 + MISSING 数 ≡ 宠数 × 各自适用链数 —— 链空间守恒
    non_empty = len(keys_a)
    missing = 0
    for name, pet in led.pets.items():
        for item in chains_for(pet["species"]):
            if (name, item) not in path_a:
                missing += 1
    space = sum(len(chains_for(p["species"])) for p in led.pets.values())
    if non_empty + missing != space:
        problems.append(f"恒等式破坏:非空链 {non_empty} + 盲区 {missing} ≠ 链空间 {space}")

    if problems:
        for p in problems:
            print(f"✗ {p}")
        print("validate:账本有问题(exit 2)")
        return 2
    print("validate:✓ 恒等式全绿")
    print(f"  Σshot 行 ≡ Σ各宠各链针数 = {a_total}(双路径重放逐宠逐链三字段全等)")
    print(f"  非空链 {non_empty} + 盲区 {missing} ≡ 链空间 {space}({len(led.pets)} 宠)")
    for name, pet in led.pets.items():
        n_i = sum(1 for k in path_a if k[0] == name)
        print(f"  {name}({SPECIES_ZH[pet['species']]}):{n_i} 条链有针,"
              f"{len(chains_for(pet['species'])) - n_i} 条盲区")
    print("  末针归属:解析层与文本层逐行号全等,可 grep 回账本")
    return 0


# ---------------------------------------------------------------- CLI
def parse_kv_list(pairs: Optional[List[str]], flag: str) -> Dict[str, int]:
    """--cycle rabies:1095 --cycle flea:30 → dict;坏形拒绝."""
    out: Dict[str, int] = {}
    for p in pairs or []:
        if ":" not in p:
            raise SystemExitWith(2, f"{flag}: 要「链:天数」形如 rabies:1095,收到「{p}」")
        k, v = p.split(":", 1)
        k = norm_token(k)
        if k not in CHAINS:
            raise SystemExitWith(2, f"{flag}: 未知链「{k}」(词表:{' '.join(CHAINS)})")
        if not re.match(r"^\d+$", v.strip()):
            raise SystemExitWith(2, f"{flag}: 天数须为非负整数,收到「{v}」")
        out[k] = int(v)
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=PROG, description="针链 · Shot Chain —— 宠物免疫/驱虫的对账账本")
    ap.add_argument("--version", action="version", version=f"{PROG} {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p, with_ledger=True):
        if with_ledger:
            p.add_argument("ledger", help="账本 TSV 路径")
        p.add_argument("--as-of", dest="as_of", default=None,
                       help="钉死对账基准日 YYYY-MM-DD(缺省锚定账本末日,零墙钟)")
        p.add_argument("--cycle", action="append", default=None, metavar="链:天数",
                       help="翻案某链周期,如 --cycle rabies:1095(海外三年)")
        p.add_argument("--grace", action="append", default=None, metavar="链:天数",
                       help="翻案某链宽容线,如 --grace rabies:0")
        p.add_argument("--warn", type=int, default=30,
                       help="预警窗天数(缺省 30;不超过周期 1/3 自动收敛)")

    add_common(sub.add_parser("report", help="全量对账单:每宠每链一盏灯"))
    add_common(sub.add_parser("next", help="行动清单:只列要动手的,贴冰箱那行"))
    add_common(sub.add_parser("brief", help="交接卡:寄养/托运/新兽医的一页纸"))
    p_v = sub.add_parser("validate", help="账本体检:恒等式 + 双路径重放")
    p_v.add_argument("ledger")

    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if getattr(args, "cycle", None) or getattr(args, "grace", None):
        try:
            args.cycle = parse_kv_list(args.cycle, "--cycle")
            args.grace = parse_kv_list(args.grace, "--grace")
        except SystemExitWith as e:
            print(e.msg, file=sys.stderr)
            return e.code
    else:
        args.cycle = {}
        args.grace = {}
    try:
        if args.cmd == "report":
            return cmd_report(args)
        if args.cmd == "next":
            return cmd_next(args)
        if args.cmd == "brief":
            return cmd_brief(args)
        if args.cmd == "validate":
            return cmd_validate(args)
        ap.error(f"未知命令 {args.cmd}")
    except SystemExitWith as e:
        print(e.msg, file=sys.stderr)
        return e.code
    except ValueError as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
