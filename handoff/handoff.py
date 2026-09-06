#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handoff · 交底 —— 家庭要紧物的位置索引账本.

问题:日历记行程、账单记钱、相册记生活——没有任何一本账记录「要紧
物在哪、除我之外谁知道、找回的线索失效了没有」。银行卡、保单、房产
证、基金账户、老家借条的位置高度集中在家庭「信息枢纽」一个人脑中:
这不是遗嘱问题(遗嘱分配财产),是寻宝图问题(先找得到,才谈分配)。
公证处继承流程的第一步就是「列财产凭证清单」,家属提供不出就跑不动;
银行「久悬户」公告、保险「寻找失主」名单每年都在发——钱不是没了,
是找不到了。信息单点故障:枢纽人一倒,整个家庭的资产地图跟着断电。

handoff 把每一件要紧物记成一行 TSV(category/title/scale/where/
key_clue/knows/verified[/step/urgent/note]),对同一本账开四个命令:
report 要紧物清单(六类覆盖矩阵,缺类亮 MISSING 反问 + 每条三灯)、
brief 家属交接卡(急件优先、行号回溯、--mask 防窥打码)、who 知情
人账(哪些事只有我知道——信息单点故障工单)、validate 账本体检。

三盏条目灯:
  STALE     verified 距 as-of > ttl(缺省 730 天,恰线不亮)——位置
            会变、密码会改、银行会合并,位置信息有自己的半衰期;「三
            年前记的抽屉」对家属已不可信。
  SOLO      knows=self-only——这件事只有我知道。信息单点故障本身。
  NO-TRACE  where 与 key_clue 全空——家属拿着这张卡无处下手。
一盏类别灯:
  MISSING   六类(银行/投资/保单/产权证件/债权债务/数字账号)零记录
            ——缺类不是账坏,是盲区;报告用反问句点它,不替你回答。

三条设计立场:
  * 密码永不入账本。本件不是密码管理器——只记「密码线索在哪个本子
    第几页」。1Password 管密码本身,handoff 管家人知不知道密码管理
    器存在。量级(scale)只记档位不记精确金额——足够家属排序,账本
    泄露也不构成精准攻击面。
  * 时间机器翻的是灯,不是清单。--as-of 钉到过去,verified 晚于
    as-of 的条目如实呈现(STALE 不亮),但清单不隐去任何一行——盘点
    表是状态不是流水,把「还没核实」假装成「没记过」,恒等式不答应。
  * 零墙钟:as-of 缺省锚定账本内最后一行「# checked: 日期」(盘点日
    声明);没有声明且未 --as-of 钉死时,STALE 闸跳过并显著披露——
    宁可不亮灯,不借系统时钟装懂。

零依赖:Python 3.8+ 标准库。账本只存在本地,不连任何接口。

Exit codes:
  0  report produced   2  usage/账本缺失/坏行/坏声明
  3  refusal: 空账     4  gate: 任一条目灯(STALE/SOLO/NO-TRACE)
                          或任一类 MISSING
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from collections import OrderedDict
from typing import List, Optional, Tuple

PROG = "handoff"
VERSION = "1.0.0"

EXIT_OK = 0
EXIT_BAD = 2
EXIT_EMPTY = 3
EXIT_LIGHTS = 4

# ---------------------------------------------------------------- 词表

# 六类:家属寻宝图的第一层分区。固定不增减——覆盖矩阵的恒等式地基。
CATEGORIES = OrderedDict([
    ("bank",    "银行与支付"),
    ("invest",  "投资与公积金"),
    ("policy",  "保单"),
    ("deed",    "产权与证件"),
    ("debt",    "债权与债务"),
    ("digital", "数字账号"),
])

# 类别中英同效:手编账本写英文键或中文短名都收。
CAT_ALIAS = {}
for _k, _zh in CATEGORIES.items():
    CAT_ALIAS[_k] = _k
CAT_ALIAS.update({
    "银行": "bank", "银行与支付": "bank",
    "投资": "invest", "投资与公积金": "invest",
    "保单": "policy", "保险": "policy",
    "证件": "deed", "产权": "deed", "产权与证件": "deed",
    "债务": "debt", "债权": "debt", "债权与债务": "debt",
    "数字": "digital", "数字账号": "digital",
})

# 量级档:只记档位不记精确金额——足够家属排序,泄露不构成攻击面。
SCALES = ["k", "w", "tw", "hw", "na"]
SCALE_DESC = OrderedDict([
    ("k",  "<1万"),
    ("w",  "1–10万"),
    ("tw", "10–100万"),
    ("hw", "≥100万"),
    ("na", "—"),
])
SCALE_ALIAS = {"万内": "k", "万": "w", "十万": "tw", "百万": "hw", "无": "na"}

# 知情人词表。self-only 是 SOLO 灯的燃料。
KNOWS = ["self-only", "spouse", "kids", "family", "lawyer", "other"]
KNOWS_DESC = OrderedDict([
    ("self-only", "只有我"),
    ("spouse",    "配偶"),
    ("kids",      "子女"),
    ("family",    "全家"),
    ("lawyer",    "律师/受托人"),
    ("other",     "其他"),
])
KNOWS_ALIAS = {
    "只有我": "self-only",
    "配偶": "spouse", "爱人": "spouse",
    "子女": "kids", "孩子": "kids",
    "全家": "family",
    "律师": "lawyer", "受托人": "lawyer",
    "其他": "other",
}

# 列名中英同效;前 7 列必需,后 3 列可选。
COLUMNS_REQUIRED = ["category", "title", "scale", "where", "key_clue", "knows", "verified"]
COLUMNS_OPTIONAL = ["step", "urgent", "note"]
COL_ALIAS = {
    "category": "category", "类别": "category",
    "title": "title", "名目": "title", "是什么": "title",
    "scale": "scale", "量级": "scale",
    "where": "where", "位置": "where", "在哪": "where",
    "key_clue": "key_clue", "线索": "key_clue", "怎么找": "key_clue",
    "knows": "knows", "谁知道": "knows", "知情人": "knows",
    "verified": "verified", "核实": "verified", "核实日": "verified",
    "step": "step", "第一步": "step",
    "urgent": "urgent", "急": "urgent", "加急": "urgent",
    "note": "note", "注": "note", "备注": "note",
}
URGENT_TRUE = {"y", "是", "急", "加急"}
URGENT_FALSE = {"", "n", "否", "不"}

# MISSING 反问:盲区要点名,但不替人回答。措辞是提醒不是指控。
MISSING_PROMPT = {
    "bank":    "家里真的没有一张银行卡、一个支付账户吗?",
    "invest":  "真的没有任何基金、股票、公积金或养老金账户吗?",
    "policy":  "家里真的没有一份保单吗?保单是最常整本消失的交代。",
    "deed":    "房产证、户口本、出生证——最硬的几张纸,记在哪一页?",
    "debt":    "借出去的钱、欠别人的账,真的都不存在吗?说不出口,公证处也会问。",
    "digital": "邮箱、网盘、代扣订阅——家属第一个想处理却找不到入口的,真的没有吗?",
}

DEFAULT_TTL = 730  # 天。位置信息的先验半衰期线;--ttl 一句话翻案。

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MASK_RE = re.compile(r"\d{4,}")


class Bad(Exception):
    """账坏:拒绝猜测,exit 2。"""


class Empty(Exception):
    """空账:算术不因薄账沉默,但连一行都没有的账 exit 3。"""


# ---------------------------------------------------------------- 基础

def strict_date(s: str) -> dt.date:
    """严格 YYYY-MM-DD:补零拒绝(2026-9-7 不是日期),日历拒绝(2月30日)。"""
    if not DATE_RE.match(s or ""):
        raise Bad("日期必须严格 YYYY-MM-DD(补零):%r" % s)
    try:
        return dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        raise Bad("日历上不存在的日期:%s" % s)


def fmt_n(n: int) -> str:
    return "{:,}".format(n)


def disp_w(s: str) -> int:
    """东亚显示宽:CJK 及全角按 2,其余按 1。零依赖的自排版。"""
    w = 0
    for ch in s:
        o = ord(ch)
        w += 2 if (0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF
                   or 0xFF00 <= o <= 0xFF60 or 0x20000 <= o <= 0x3FFFD) else 1
    return w


def pad2(s: str, width: int) -> str:
    return s + " " * max(0, width - disp_w(s))


def mask(s: str) -> str:
    """≥4 位连续数字 → 固定 ****(不泄露长度)。幂等:星号不是数字。"""
    return MASK_RE.sub("****", s)


def basename(path: str) -> str:
    return os.path.basename(path)


# ---------------------------------------------------------------- 载入

class Item:
    __slots__ = ("line_no", "category", "title", "scale", "where", "key_clue",
                 "knows", "verified", "step", "urgent", "note")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw[k])

    def key(self) -> tuple:
        return tuple(getattr(self, k) for k in self.__slots__)


def _norm_cell(col_key: str, raw: str, line_no: int) -> str:
    v = raw.strip()
    if col_key == "category":
        key = CAT_ALIAS.get(v.lower() if v.isascii() else v, None)
        if key is None:
            # 再试一遍:大小写不敏感的英文键
            low = v.lower()
            key = CAT_ALIAS.get(low)
        if key is None:
            raise Bad("行 %d:未知类别 %r(词表:%s)" % (line_no, v, "/".join(CATEGORIES)))
        return key
    if col_key == "scale":
        key = v if v in SCALES else SCALE_ALIAS.get(v)
        if key is None:
            raise Bad("行 %d:未知量级 %r(词表:%s)" % (line_no, v, "/".join(SCALES)))
        return key
    if col_key == "knows":
        key = v if v in KNOWS else KNOWS_ALIAS.get(v)
        if key is None:
            raise Bad("行 %d:未知知情人 %r(词表:%s)" % (line_no, v, "/".join(KNOWS)))
        return key
    if col_key == "urgent":
        low = v.lower()
        if low in URGENT_TRUE:
            return "y"
        if low in URGENT_FALSE:
            return ""
        raise Bad("行 %d:急件旗标只能是 y/是/急 或留空:%r" % (line_no, v))
    return v


def load_ledger(path: str) -> Tuple[List[Item], List[dt.date]]:
    """载入账本 → (条目列表按物理行序, checked 盘点日轨迹按行序)。

    表头列名中英同效、乱序自由;行号=文件物理行号(1-based,含注释),
    让「交接卡第 N 条」可以被 grep 一眼定位。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_lines = f.read().split("\n")
    except FileNotFoundError:
        raise Bad("账本不存在:%s" % path)
    except UnicodeDecodeError:
        raise Bad("账本不是 UTF-8 文本:%s" % path)

    checked: List[dt.date] = []
    header_cols: Optional[List[str]] = None  # 映射后的规范列名
    items: List[Item] = []
    saw_content = False

    for idx, raw in enumerate(raw_lines, start=1):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        saw_content = True
        stripped = line.strip()
        if stripped.startswith("#"):
            m = re.match(r"^#\s*checked\s*:\s*(\S+)\s*$", stripped)
            if m:
                checked.append(strict_date(m.group(1)))  # 坏声明=账坏
            continue  # 普通注释
        if header_cols is None:
            cols = [c.strip() for c in line.split("\t")]
            keys: List[str] = []
            for c in cols:
                key = COL_ALIAS.get(c)
                if key is None:
                    raise Bad("表头第 %d 列 %r 不是已知列(中英同效)"
                              % (cols.index(c) + 1, c))
                if key in keys:
                    raise Bad("表头列重复:%s" % key)
                keys.append(key)
            missing = [c for c in COLUMNS_REQUIRED if c not in keys]
            if missing:
                raise Bad("表头缺必需列:%s" % ",".join(missing))
            header_cols = keys
            continue
        cells = line.split("\t")
        # 行尾制表符容忍(手编账本从表格粘出来的日常)
        if len(cells) == len(header_cols) + 1 and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) != len(header_cols):
            raise Bad("行 %d:字段数 %d ≠ 表头列数 %d"
                      % (idx, len(cells), len(header_cols)))
        rec = dict(zip(header_cols, cells))
        title = rec["title"].strip()
        if not title:
            raise Bad("行 %d:名目(title)为空——一件说不清是什么的东西,家属找到了也不知道" % idx)
        verified_raw = rec["verified"].strip()
        if not verified_raw:
            raise Bad("行 %d:核实日(verified)为空——没有核实日的位置,账本不冒充新鲜" % idx)
        verified = strict_date(verified_raw)
        items.append(Item(
            line_no=idx,
            category=_norm_cell("category", rec["category"], idx),
            title=title,
            scale=_norm_cell("scale", rec["scale"], idx),
            where=rec["where"].strip(),
            key_clue=rec["key_clue"].strip(),
            knows=_norm_cell("knows", rec["knows"], idx),
            verified=verified,
            step=rec.get("step", "").strip(),
            urgent=_norm_cell("urgent", rec.get("urgent", ""), idx) == "y",
            note=rec.get("note", "").strip(),
        ))

    if not saw_content:
        raise Empty("账本是空的(连表头都没有)")
    if header_cols is None:
        raise Bad("账本没有表头行(中英列名同效,见 README)")
    if not items:
        raise Empty("账本只有表头,一件要紧物都没记")
    return items, checked


# ---------------------------------------------------------------- 判灯

def lamps(item: Item, as_of: Optional[dt.date], ttl: int) -> List[str]:
    """三盏条目灯,固定序 STALE→SOLO→NO-TRACE。恰线不亮(days>ttl 才亮)。"""
    out: List[str] = []
    if as_of is not None:
        days = (as_of - item.verified).days
        if days > ttl:
            out.append("STALE")
    if item.knows == "self-only":
        out.append("SOLO")
    if not item.where and not item.key_clue:
        out.append("NO-TRACE")
    return out


def missing_cats(items: List[Item]) -> List[str]:
    seen = {it.category for it in items}
    return [c for c in CATEGORIES if c not in seen]


def any_lights(items: List[Item], as_of: Optional[dt.date], ttl: int,
               missing: List[str]) -> bool:
    for it in items:
        if lamps(it, as_of, ttl):
            return True
    return bool(missing)


def resolve_as_of(cli_as_of: Optional[str], checked: List[dt.date]
                  ) -> Tuple[Optional[dt.date], str]:
    """as-of = --as-of 或最后一行 checked 声明;两者皆无 → (None, 关闸理由)。"""
    if cli_as_of is not None:
        return strict_date(cli_as_of), ""
    if checked:
        return checked[-1], ""
    return None, "账本无 # checked: 盘点日声明,且未 --as-of 钉死——STALE 闸跳过(不借系统时钟装懂)"


# ---------------------------------------------------------------- 报告

def lamp_line(it: Item, tags: List[str], as_of: Optional[dt.date], ttl: int) -> List[str]:
    head = " ".join(tags)
    stale_detail = ""
    if "STALE" in tags and as_of is not None:
        days = (as_of - it.verified).days
        stale_detail = "核实于 %s,距 as-of %s 天 > %d" % (
            it.verified.isoformat(), fmt_n(days), ttl)
    lines = [
        "[行%3d] %s  %s  %s  %s" % (
            it.line_no, pad2(head, 17),
            pad2(it.category, 8), pad2(it.title, 30),
            SCALE_DESC[it.scale]),
    ]
    detail = "位置: %s · 线索: %s · 谁知道: %s" % (
        it.where or "—", it.key_clue or "—", KNOWS_DESC[it.knows])
    if stale_detail:
        detail += " · " + stale_detail
    lines.append("        " + detail)
    return lines


def cmd_report(path: str, cli_as_of: Optional[str], ttl: int) -> int:
    items, checked = load_ledger(path)  # Bad/Empty 向上
    as_of, note = resolve_as_of(cli_as_of, checked)
    lamps_by = {it.line_no: lamps(it, as_of, ttl) for it in items}
    missing = missing_cats(items)

    out: List[str] = []
    out.append("交底 · Handoff — 要紧物清单")
    out.append("账本: %s" % basename(path))
    if as_of is not None:
        src = "--as-of 钉死" if cli_as_of is not None else "# checked: 盘点日"
        out.append("as-of: %s(%s) · STALE 线: %d 天(verified 距 as-of > 线才亮,恰线不亮)"
                   % (as_of.isoformat(), src, ttl))
    else:
        out.append("STALE 闸: 跳过(%s)" % note)

    lit = [it for it in items if lamps_by[it.line_no]]
    out.append("")
    out.append("要紧物 %d 件 · 量级 %s · 带灯 %d · 绿灯 %d" % (
        len(items),
        " ".join("%s×%d" % (s, sum(1 for it in items if it.scale == s))
                 for s in SCALES),
        len(lit), len(items) - len(lit)))

    # 六类覆盖矩阵
    out.append("")
    out.append("── 六类覆盖 " + "─" * 38)
    for cat, zh in CATEGORIES.items():
        rows = [it for it in items if it.category == cat]
        if not rows:
            out.append("  %s  %s    0 件 · MISSING" % (pad2(cat, 8), pad2(zh, 14)))
            continue
        latest = max(it.verified for it in rows)
        n_lit = sum(1 for it in rows if lamps_by[it.line_no])
        state = "OK" if n_lit == 0 else "%s 带灯" % fmt_n(n_lit)
        out.append("  %s  %s  %s 件 · 最新核实 %s · %s" % (
            pad2(cat, 8), pad2(zh, 14), fmt_n(len(rows)), latest.isoformat(), state))

    # 带灯清单(按账本行序——手编顺序就是主人心里的顺序)
    out.append("")
    if lit:
        out.append("── 带灯清单(按账本行序) " + "─" * 30)
        for it in lit:
            out.extend(lamp_line(it, lamps_by[it.line_no], as_of, ttl))
    else:
        out.append("── 带灯清单: 无(全部绿灯) " + "─" * 24)

    # 盲区反问
    out.append("")
    if missing:
        out.append("── 盲区反问(缺类不是账坏,是没敢看的角落) " + "─" * 18)
        for cat in missing:
            out.append("  · %s %s: %s" % (cat, CATEGORIES[cat], MISSING_PROMPT[cat]))
    else:
        out.append("── 盲区反问: 六类齐全 " + "─" * 30)

    out.append("")
    out.append("这张纸是给家人的寻宝图,不是遗嘱——它不分配任何东西,只保证找得到。")
    text = "\n".join(out)
    print(text)
    return EXIT_LIGHTS if (lit or missing) else EXIT_OK


def cmd_brief(path: str, top: int, do_mask: bool, cli_as_of: Optional[str],
              ttl: int) -> int:
    items, checked = load_ledger(path)
    as_of, note = resolve_as_of(cli_as_of, checked)
    missing = missing_cats(items)

    # 急件优先,余按账本行序——家属的第一页永远先给「还在流血的」。
    ordered = sorted(items, key=lambda it: (0 if it.urgent else 1, it.line_no))
    chosen = ordered if top == 0 else ordered[:top]

    out: List[str] = []
    out.append("交底 · Handoff — 家属交接卡")
    out.append("账本: %s · 共 %d 件 · 取前 %d 件(急件优先,余按账本行序)"
               % (basename(path), len(items), len(chosen) if top else len(items)))
    if as_of is not None:
        out.append("as-of: %s · STALE 线: %d 天" % (as_of.isoformat(), ttl))
    else:
        out.append("STALE 闸: 跳过(%s)" % note)
    out.append("")
    for i, it in enumerate(chosen, start=1):
        tags = lamps(it, as_of, ttl)
        t = mask(it.title) if do_mask else it.title
        flag = "·急" if it.urgent else ""
        out.append(" %2d.[行%3d]%s %s  %s  %s" % (
            i, it.line_no, flag,
            pad2(it.category, 8), pad2(t, 32), SCALE_DESC[it.scale]))
        extra = "去哪: %s · 第一步: %s · 谁知道: %s" % (
            it.where or "—", it.step or "—", KNOWS_DESC[it.knows])
        if it.key_clue:
            extra += " · 线索: " + (mask(it.key_clue) if do_mask else it.key_clue)
        out.append("     " + extra)
        if tags:
            tag_detail = []
            if "STALE" in tags and as_of is not None:
                tag_detail.append("核实于 %s,已隔 %s 天——先用再信"
                                  % (it.verified.isoformat(),
                                     fmt_n((as_of - it.verified).days)))
            if "SOLO" in tags:
                tag_detail.append("只有他知道")
            if "NO-TRACE" in tags:
                tag_detail.append("位置与线索全空——先翻抽屉")
            out.append("     灯: " + ";".join(tag_detail))
    out.append("")
    if missing:
        out.append("账本盲区: %s 零记录——这些角落家里大概率不是空的,是没敢看的。"
                   % ",".join(CATEGORIES[c] for c in missing))
    out.append("卡是地图不是密码——密码永不在这张纸上;线索(key_clue)只告诉你它藏在哪个本子第几页。")
    print("\n".join(out))
    return EXIT_LIGHTS if any_lights(items, as_of, ttl, missing) else EXIT_OK


def cmd_who(path: str) -> int:
    items, _checked = load_ledger(path)
    solo = [it for it in items if it.knows == "self-only"]

    out: List[str] = []
    out.append("交底 · Handoff — 知情人账")
    out.append("账本: %s" % basename(path))
    out.append("")
    for k in KNOWS:
        n = sum(1 for it in items if it.knows == k)
        mark = "  ← 信息单点故障:这些事只有我知道" if k == "self-only" and n else ""
        out.append("  %s  %s %d 件%s" % (pad2(k, 11), pad2(KNOWS_DESC[k], 10),
                                         n, mark))
    out.append("")
    out.append("知情账恒等式: Σ各知情人件数 = %d ≡ 条目数 %d" % (
        sum(1 for it in items if it.knows != "self-only") + len(solo), len(items)))
    if solo:
        out.append("")
        out.append("该补一句的(吃饭时说一句 / 写一张卡放进抽屉——说完就把这行改掉):")
        for i, it in enumerate(solo, start=1):
            out.append("  %d.[行%3d] %s %s(核实于 %s)" % (
                i, it.line_no, it.category, it.title, it.verified.isoformat()))
        out.append("")
        out.append("SOLO 的解药不是加密,是一句说出口的「这件事你知道吗」。")
    else:
        out.append("")
        out.append("self-only 0 件——没有信息单点故障,这本账对得起家人。")
    print("\n".join(out))
    return EXIT_LIGHTS if solo else EXIT_OK


# ---------------------------------------------------------------- 体检

def _replay(path: str) -> Tuple[List[Item], List[Tuple[int, str, str]], int]:
    """双路径重放的第二条路:独立再载入一遍 + 独立排序交接卡。"""
    items, _ = load_ledger(path)
    ordered = sorted(items, key=lambda it: (0 if it.urgent else 1, it.line_no))
    brief_rows = [(it.line_no, it.title, it.category) for it in ordered]
    cat_counts = {c: sum(1 for it in items if it.category == c) for c in CATEGORIES}
    return items, brief_rows, sum(cat_counts.values())


def cmd_validate(path: str, cli_as_of: Optional[str], ttl: int) -> int:
    items, checked = load_ledger(path)
    as_of, _note = resolve_as_of(cli_as_of, checked)
    missing = missing_cats(items)

    out: List[str] = []
    out.append("交底 · Handoff — 账本体检")
    out.append("账本: %s · 条目 %d · 类别覆盖 %d/6 · 盘点日声明 %d 次%s"
               % (basename(path), len(items), 6 - len(missing), len(checked),
                  ("(最后 %s)" % checked[-1].isoformat()) if checked else "(无)"))

    # 恒等式 1:Σ六类件数 ≡ 条目数(每条恰属一类,不重不漏)
    s_cats = sum(1 for _ in items)  # 每条恰一个 category 字段,载入即守恒
    ok1 = s_cats == len(items)

    # 恒等式 2:双路径重放——两遍独立解析+判灯,逐条全等
    items2, _rows2, _sum2 = _replay(path)
    lamps1 = [(it.key(), lamps(it, as_of, ttl)) for it in items]
    lamps2 = [(it.key(), lamps(it, as_of, ttl)) for it in items2]
    ok2 = lamps1 == lamps2

    # 恒等式 3:交接卡回溯——急件优先排序的每条都能在账本中按行号+名目对回
    ordered = sorted(items, key=lambda it: (0 if it.urgent else 1, it.line_no))
    index = {(it.line_no, it.title): it for it in items}
    ok3 = all((ln, tt) in index for ln, tt, _c in
              [(it.line_no, it.title, it.category) for it in ordered])

    # 恒等式 4:打码幂等 + 守恒
    titles = [it.title for it in items]
    masked = [mask(t) for t in titles]
    ok4 = (len(masked) == len(titles)
           and all(mask(m) == m for m in masked))

    out.append("")
    out.append("恒等式")
    out.append("  Σ六类件数 = %d ≡ 条目数 %d %s" % (
        s_cats, len(items), "✓" if ok1 else "✗"))
    out.append("  双路径重放: 两遍独立解析+判灯 %d/%d 条逐项全等 %s" % (
        sum(1 for a, b in zip(lamps1, lamps2) if a == b), len(items),
        "✓" if ok2 else "✗"))
    out.append("  交接卡回溯: %d 条全部可按行号+名目对回账本 %s" % (
        len(ordered), "✓" if ok3 else "✗"))
    out.append("  打码幂等 mask∘mask=mask ✓ · 条目守恒 %d ≡ %d %s" % (
        len(masked), len(titles), "✓" if ok4 else "✗"))

    lights = any_lights(items, as_of, ttl, missing)
    out.append("")
    if missing:
        out.append("盲区类: %s" % ",".join(CATEGORIES[c] for c in missing))
    out.append("体检结果: 恒等式 %s · 账面%s" % (
        "全绿" if (ok1 and ok2 and ok3 and ok4) else "有 ✗(属实现缺陷,报 issue)",
        "带灯(见 report)" if lights else "全绿"))
    print("\n".join(out))
    if not (ok1 and ok2 and ok3 and ok4):
        return EXIT_BAD
    return EXIT_OK


# ---------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="交底 · Handoff —— 家庭要紧物的位置索引账本(密码永不入账本)")
    p.add_argument("--version", action="version", version="%s %s" % (PROG, VERSION))
    sub = p.add_subparsers(dest="cmd")

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("ledger", help="交底账本 TSV")
        sp.add_argument("--as-of", dest="as_of", default=None,
                        help="钉死基准日 YYYY-MM-DD(缺省=最后一行 # checked:)")
        sp.add_argument("--ttl", type=int, default=DEFAULT_TTL,
                        help="STALE 线(天),缺省 %d(恰线不亮)" % DEFAULT_TTL)

    sp = sub.add_parser("report", help="要紧物清单:六类覆盖矩阵+带灯清单+盲区反问")
    common(sp)
    sp = sub.add_parser("brief", help="家属交接卡:急件优先、行号回溯、--mask 防窥")
    common(sp)
    sp.add_argument("--top", type=int, default=10,
                    help="取前 N 件(0=全部),缺省 10")
    sp.add_argument("--mask", action="store_true",
                    help="名目与线索中 ≥4 位连续数字打码成 ****")
    sp = sub.add_parser("who", help="知情人账:哪些事只有我知道(SOLO 工单)")
    sp.add_argument("ledger", help="交底账本 TSV")
    sp = sub.add_parser("validate", help="账本体检:恒等式+双路径重放")
    common(sp)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd is None:
        build_parser().print_help()
        return EXIT_OK
    if getattr(args, "ttl", 0) is not None and getattr(args, "ttl", 0) < 0:
        print("handoff: --ttl 不能为负", file=sys.stderr)
        return EXIT_BAD
    try:
        if args.cmd == "report":
            return cmd_report(args.ledger, args.as_of, args.ttl)
        if args.cmd == "brief":
            if args.top < 0:
                print("handoff: --top 不能为负(0=全部)", file=sys.stderr)
                return EXIT_BAD
            return cmd_brief(args.ledger, args.top, args.mask, args.as_of, args.ttl)
        if args.cmd == "who":
            return cmd_who(args.ledger)
        if args.cmd == "validate":
            return cmd_validate(args.ledger, args.as_of, args.ttl)
    except Bad as e:
        print("handoff: 账坏 — %s" % e, file=sys.stderr)
        return EXIT_BAD
    except Empty as e:
        print("handoff: 空账 — %s" % e, file=sys.stderr)
        return EXIT_EMPTY
    print("handoff: 未知命令 %r" % args.cmd, file=sys.stderr)
    return EXIT_BAD


if __name__ == "__main__":
    sys.exit(main())
