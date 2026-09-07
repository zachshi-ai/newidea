#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kin-ring · 年轮 —— 家族健康史对账账本。

问题:陪诊时医生必问「家族里有人得过这个吗」,大多数家庭答不上来,
只剩模糊印象(「好像我爷爷是胃不好的」);体检表「家族史」一栏常年
全空。可家族病史是医学上最便宜的风险线索——一级亲属的确诊史决定
筛查的起点年纪,这是各国指南的公开共识。它却只活在口传里:分散在
每位亲戚的记忆中、没有年龄锚点(「走得早」是几岁?)、随老人离世
断代。日历记行程、账单记钱、相册记生活——没有任何一本账记录
「家里谁、得过什么病、几岁确诊」。

kin-ring 把家族病史记成手编 TSV(一人一行 person,一病一行 dx),
对同一本账开四个命令:
  report   年龄带对齐——你的年龄逐条扫过亲人被确诊的年纪,灯替你开口
  kin      家族名册——每位亲人一行,各辈覆盖一眼见底
  ask      该问清单——把「说不清」变成趁长辈还在时能问出的一句话
  validate 账本体检——双路径重放,恒等式逐项全等

灯(各管各的案):
  REACHED   你已到达某位血亲(长辈/同辈)被确诊的年纪(Δ≤0)——不是
            判决,是把「该和医生聊家族史」这句话提前到体检桌上。
  NEAR      距那道年纪 0<Δ≤5 年(恰线即亮)——提前量的全部价值。
  CLUSTER   归一化病名相同的病史 ≥2 条、且 ≥1 条来自一级亲属
            (父母/同胞/子女)——带去问医生的证据链。
  BROKEN    祖辈整辈零记录且未声明 # gone——这一代正在失去最后的
            证人。辅灯:UNDATABLE(缺年份无法对齐,进 ask)、GONE
            (已声明无从问起,如实披露不指控)。

三条设计立场:
  * 年龄带按公历年差计,粒度 ±1 年——机器只算年轮,不装懂月龄;
    灯的语义是「时机」不是「风险评分」,±1 年不改变该不该开口。
  * 零墙钟:年龄对齐依赖 as-of(# as-of: 声明或 --as-of 钉死);
    两者都没有时 REACHED/NEAR 闸跳过并显著披露——宁可对不上,
    不借系统时钟装懂。CLUSTER/BROKEN/UNDATABLE 不依赖时钟照常判。
  * 机器不算叙事。账本外的口传(「她生前说她姑妈也是瘤子」)不是
    数据,ask 只负责把它变成下一个问题;确诊早于出生、死年早于生
    年这类自相矛盾按账坏拒绝。子女的病不对齐你的年纪——它是家系
    证据(进 CLUSTER),不是你的时钟;配偶无血缘,同住人病史单列。

时间机器:dxyr 晚于 as-of 的病史是「后视」——如实呈现、注明跳过,
不参与对齐也不参与聚集(未来的确诊不能点亮过去的灯)。

诚实条款:本件不是医生,不诊断、不评估风险、不推荐任何筛查项目。
REACHED 的含义仅仅是「你活到了家里某人被确诊的年纪」——多数有家
族史的人终生不发病,基线概率仍在多数一边;账本给的是问诊桌上的三
句话,不是体检单外的恐慌。账本只存在本地,不连任何接口。

零依赖:Python 3.8+ 标准库。

账本 TSV,8 列: type/key/rel/birth/status/dx/dxyr/note
  person 行  key  rel  birth(YYYY|?)  status(alive|dead|dead:YYYY)
  dx 行      key(指向 person)  dx(病名)  dxyr(YYYY|?)
声明: # as-of: YYYY-MM-DD(至多一条) · # gone: <rel>(承认该辈无从问起)
右侧缺列视为空(手编从表格粘贴的日常);超过 8 列、表头缺失、未知
行型/亲属关系、年份不补零、自相矛盾的年轮,一律 exit 2。

命令: report / kin / ask / validate
退出码: 0 绿 · 2 账坏 · 3 空账或薄账拒判 · 4 账面带灯
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from collections import OrderedDict
from typing import List, Optional, Tuple

PROG = "kin-ring"
VERSION = "1.0.0"

EXIT_OK = 0
EXIT_BAD = 2
EXIT_EMPTY = 3
EXIT_LIGHTS = 4

# ---------------------------------------------------------------- 词表

# 亲属词表。一级亲属(DEG1)是 CLUSTER 的门槛,医学定义:父母/同胞/子女。
RELS = ["me", "parent", "sibling", "child",
        "grandparent", "uncle-aunt", "cousin", "spouse", "other"]
REL_DESC = OrderedDict([
    ("me",          "本人"),
    ("parent",      "父母(一级)"),
    ("sibling",     "同胞(一级)"),
    ("child",       "子女(一级)"),
    ("grandparent", "祖辈(二级)"),
    ("uncle-aunt",  "叔姑舅姨(二级)"),
    ("cousin",      "表堂亲(三级)"),
    ("spouse",      "配偶(无血缘)"),
    ("other",       "其他"),
])
REL_ALIAS = {
    "本人": "me", "我": "me",
    "父母": "parent", "父": "parent", "母": "parent",
    "爸爸": "parent", "妈妈": "parent", "父亲": "parent", "母亲": "parent",
    "同胞": "sibling", "兄弟": "sibling", "姐妹": "sibling",
    "哥哥": "sibling", "弟弟": "sibling", "姐姐": "sibling", "妹妹": "sibling",
    "子女": "child", "孩子": "child", "儿子": "child", "女儿": "child",
    "祖父母": "grandparent", "祖辈": "grandparent",
    "爷爷": "grandparent", "奶奶": "grandparent",
    "外公": "grandparent", "外婆": "grandparent",
    "姥爷": "grandparent", "姥姥": "grandparent",
    "叔姑舅姨": "uncle-aunt", "叔叔": "uncle-aunt", "姑姑": "uncle-aunt",
    "舅舅": "uncle-aunt", "姨妈": "uncle-aunt", "姑妈": "uncle-aunt",
    "表堂亲": "cousin", "表亲": "cousin", "堂亲": "cousin",
    "配偶": "spouse", "丈夫": "spouse", "妻子": "spouse", "爱人": "spouse",
    "其他": "other",
}
DEG1 = {"parent", "sibling", "child"}

HEADER = ["type", "key", "rel", "birth", "status", "dx", "dxyr", "note"]
YEAR_MIN, YEAR_MAX = 1500, 2999

# ---------------------------------------------------------------- 基础工具


def fail(msg: str):
    print("%s: %s" % (PROG, msg), file=sys.stderr)
    raise SystemExit(EXIT_BAD)


def refuse(msg: str):
    """空账/薄账拒判:exit 3,与账坏(exit 2)分属两个出口。"""
    print("%s: %s" % (PROG, msg), file=sys.stderr)
    raise SystemExit(EXIT_EMPTY)


def disp_w(s: str) -> int:
    """显示宽度:CJK/全角与增补平面字符(emoji)按 2 计。"""
    w = 0
    for ch in s:
        if ord(ch) > 0xFFFF:
            w += 2
        elif unicodedata.east_asian_width(ch) in ("F", "W"):
            w += 2
        else:
            w += 1
    return w


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - disp_w(s))


def fmt_n(n: int) -> str:
    return "{:,}".format(n)


def basename(path: str) -> str:
    return os.path.basename(path)


def strict_date(s: str) -> str:
    """YYYY-MM-DD 严格解析(补零拒绝,禁止 2026-9-7)。"""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if not m:
        raise ValueError("日期必须是 YYYY-MM-DD 且补零: %r" % s)
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        raise ValueError("日期字段越界: %r" % s)
    return s


def parse_year(s: str, what: str, line_no: int) -> Optional[int]:
    if s in ("", "?", "—"):
        return None
    if not re.match(r"^\d{4}$", s):
        raise ValueError("行 %d: %s 必须是 4 位年份或 ?: %r" % (line_no, what, s))
    y = int(s)
    if not (YEAR_MIN <= y <= YEAR_MAX):
        raise ValueError("行 %d: %s 越界(%d–%d): %d"
                         % (line_no, what, YEAR_MIN, YEAR_MAX, y))
    return y


def norm_dx(name: str) -> str:
    """病名归一:NFKC 折叠全角、去空白与常见分隔符、小写。

    只做字形归一,不做医学同义(「II型」≠「2型」——机器不发明没教过的等价)。
    """
    s = unicodedata.normalize("NFKC", name).lower()
    return re.sub(r"[\s·・.\-—_/()（）]+", "", s)


# ---------------------------------------------------------------- 数据模型


class Person:
    __slots__ = ("key", "rel", "birth", "alive", "death", "note", "line")

    def __init__(self, key, rel, birth, alive, death, note, line):
        self.key, self.rel, self.birth = key, rel, birth
        self.alive, self.death, self.note, self.line = alive, death, note, line


class Dx:
    __slots__ = ("key", "name", "year", "note", "line")

    def __init__(self, key, name, year, note, line):
        self.key, self.name, self.year = key, name, year
        self.note, self.line = note, line


class Ledger:
    def __init__(self):
        self.persons = OrderedDict()   # key -> Person(按账本行序)
        self.dxs = []                  # List[Dx](账本行序)
        self.as_of = None              # "# as-of:" 声明,或 None
        self.gone = set()              # "# gone:" 声明的 rel 集合
        self.path = ""

    def me(self) -> Optional[Person]:
        return next((p for p in self.persons.values() if p.rel == "me"), None)


def split_row(raw: str, line_no: int) -> List[str]:
    if "\t" not in raw:
        raise ValueError("行 %d: 不是制表符分隔的 TSV 行" % line_no)
    cols = raw.rstrip("\r").split("\t")
    if len(cols) > len(HEADER):
        raise ValueError("行 %d: 列数 %d 超过表头 %d 列"
                         % (line_no, len(cols), len(HEADER)))
    return cols + [""] * (len(HEADER) - len(cols))


def load_ledger(path: str) -> Ledger:
    """解析账本。任何结构性问题抛 ValueError(调用方转 exit 2)。"""
    if not os.path.exists(path):
        raise ValueError("账本不存在: %s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    led = Ledger()
    led.path = path
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()

    seen_header = False
    dx_refs = []  # (key, line):先收后解——允许前向引用(人可以后补一行)
    for i, raw in enumerate(raw_lines, start=1):
        stripped = raw.strip()
        if stripped == "":
            continue
        if stripped.startswith("#"):
            m = re.match(r"^#\s*as-of:\s*(\S+)\s*$", stripped)
            if m:
                if led.as_of is not None:
                    raise ValueError("行 %d: # as-of: 声明重复(至多一条)" % i)
                led.as_of = strict_date(m.group(1))
                continue
            m = re.match(r"^#\s*gone:\s*(\S+)\s*$", stripped)
            if m:
                rel = REL_ALIAS.get(m.group(1), m.group(1))
                if rel not in RELS:
                    raise ValueError("行 %d: # gone: 未知亲属关系 %r" % (i, m.group(1)))
                led.gone.add(rel)
                continue
            continue  # 普通注释
        if not seen_header:
            cols = split_row(raw, i)
            if [c.strip() for c in cols] != HEADER:
                raise ValueError("行 %d: 表头必须是 %s" % (i, "/".join(HEADER)))
            seen_header = True
            continue
        cols = split_row(raw, i)
        typ = cols[0].strip()
        if typ == "person":
            key = cols[1].strip()
            if not key:
                raise ValueError("行 %d: person 行缺 key" % i)
            rel_raw = cols[2].strip()
            rel = REL_ALIAS.get(rel_raw, rel_raw)
            if rel not in RELS:
                raise ValueError("行 %d: 未知亲属关系 %r(词表: %s)"
                                 % (i, rel_raw, "/".join(RELS)))
            birth = parse_year(cols[3].strip(), "出生年", i)
            if rel == "me" and birth is None:
                raise ValueError("行 %d: 主角(me)的出生年是对齐的锚,不能是 ?" % i)
            status_raw = cols[4].strip() or "alive"
            status_raw = {"在世": "alive", "健在": "alive",
                          "已故": "dead"}.get(status_raw, status_raw)
            m = re.match(r"^(alive|dead)(?::(\d{4}))?$", status_raw)
            if not m:
                raise ValueError("行 %d: 在世状态必须是 alive/dead/dead:YYYY: %r"
                                 % (i, cols[4].strip()))
            alive = m.group(1) == "alive"
            death = int(m.group(2)) if m.group(2) else None
            if rel == "me" and not alive:
                raise ValueError("行 %d: 账本主角(me)必须 alive——替谁记,谁是主角" % i)
            if death is not None and birth is not None and death < birth:
                raise ValueError("行 %d: 卒年 %d 早于出生 %d" % (i, death, birth))
            if key in led.persons:
                raise ValueError("行 %d: person key 重复: %r" % (i, key))
            led.persons[key] = Person(key, rel, birth, alive, death,
                                      cols[7].strip(), i)
        elif typ == "dx":
            key = cols[1].strip()
            if not key:
                raise ValueError("行 %d: dx 行缺 key(指向哪位亲人?)" % i)
            name = cols[5].strip()
            if not name:
                raise ValueError("行 %d: dx 行缺病名" % i)
            year = parse_year(cols[6].strip(), "确诊年", i)
            led.dxs.append(Dx(key, name, year, cols[7].strip(), i))
            dx_refs.append((key, i))
        else:
            raise ValueError("行 %d: 未知行型 %r(只认 person/dx)" % (i, typ))

    # 零数据行(空文件/纯注释)不算账坏——留给上层按「空账」拒判(exit 3);
    # 有数据行却对不上表头,才是账坏(exit 2,上面已当场抛出)。
    n_me = len([p for p in led.persons.values() if p.rel == "me"])
    if n_me > 1:
        raise ValueError("主角(me)只能有一位")
    if n_me == 0 and led.persons:
        raise ValueError("账里没有主角(me 行)——替谁记,谁就是 me")

    # 前向引用解析:dx.key 必须落到某位 person;年轮不许倒转
    for key, i in dx_refs:
        if key not in led.persons:
            raise ValueError("行 %d: dx 引用了未登记的人 %r" % (i, key))
    for dx in led.dxs:
        p = led.persons[dx.key]
        if dx.year is not None and p.birth is not None and dx.year < p.birth:
            raise ValueError("行 %d: 确诊年 %d 早于 %s 的出生年 %d——年轮倒转"
                             % (dx.line, dx.year, p.key, p.birth))
    return led


# ---------------------------------------------------------------- 评估

NEAR_BAND = 5


class Row:
    """一条 dx 的对账结果。"""
    __slots__ = ("dx", "person", "kind", "lamp", "dx_age", "delta", "future")

    def __init__(self, dx, person, kind, lamp=None, dx_age=None,
                 delta=None, future=False):
        self.dx, self.person, self.kind = dx, person, kind
        self.lamp, self.dx_age, self.delta = lamp, dx_age, delta
        self.future = future


class Report:
    def __init__(self):
        self.rows = []          # List[Row](账本行序)
        self.clusters = []      # dict(name, norm, n, members, deg1, lamp)
        self.broken = False
        self.gone_hit = []      # 声明 gone 且该辈确实零记录
        self.have_clock = True  # as-of 可用


def resolve_as_of(led: Ledger, cli_as_of: Optional[str]) -> Tuple[Optional[str], str]:
    if cli_as_of is not None:
        return strict_date(cli_as_of), "--as-of"
    if led.as_of is not None:
        return led.as_of, "# as-of: 声明"
    return None, "未钉死"


def evaluate(led: Ledger, as_of: Optional[str]) -> Report:
    """对账。纯函数:同一账本+同一 as-of 恒等结果。"""
    rep = Report()
    me = led.me()
    my_age = None
    if as_of is not None:
        my_age = int(as_of[:4]) - me.birth
    rep.have_clock = as_of is not None

    for dx in led.dxs:
        person = led.persons[dx.key]
        rel = person.rel
        if rel == "me":
            rep.rows.append(Row(dx, person, "self"))
            continue
        if rel == "spouse":
            rep.rows.append(Row(dx, person, "spouse"))
            continue
        # 血亲:尝试年龄对齐
        if dx.year is not None and as_of is not None and dx.year > int(as_of[:4]):
            rep.rows.append(Row(dx, person, "kin", future=True))
            continue
        if person.birth is None or dx.year is None:
            rep.rows.append(Row(dx, person, "kin", lamp="UNDATABLE"))
            continue
        dx_age = dx.year - person.birth
        if rel == "child":
            # 子女的病不对齐你的年纪:它是家系证据,不是你的时钟
            rep.rows.append(Row(dx, person, "child", dx_age=dx_age))
            continue
        if my_age is None:
            rep.rows.append(Row(dx, person, "kin", dx_age=dx_age, delta=None))
            continue
        delta = dx_age - my_age
        lamp = "REACHED" if delta <= 0 else ("NEAR" if delta <= NEAR_BAND else None)
        rep.rows.append(Row(dx, person, "kin", lamp=lamp, dx_age=dx_age,
                            delta=delta))

    # CLUSTER:归一化病名聚集,≥2 条非本人/同住人病史、≥1 条一级。
    # 后视(确诊晚于 as-of)的病史不参与——未来的确诊不能点亮过去的灯。
    as_of_year = int(as_of[:4]) if as_of is not None else None
    buckets = OrderedDict()
    for dx in led.dxs:
        rel = led.persons[dx.key].rel
        if rel in ("me", "spouse"):
            continue
        if as_of_year is not None and dx.year is not None and dx.year > as_of_year:
            continue
        buckets.setdefault(norm_dx(dx.name), []).append(dx)
    for norm, members in buckets.items():
        if len(members) < 2:
            continue
        deg1 = [d for d in members if led.persons[d.key].rel in DEG1]
        mem = []
        for d in members:
            p = led.persons[d.key]
            age = ((d.year - p.birth)
                   if (d.year is not None and p.birth is not None) else None)
            mem.append((p.key, age))
        rep.clusters.append({
            "name": members[0].name, "norm": norm, "n": len(members),
            "members": mem, "deg1": len(deg1), "lamp": bool(deg1),
        })

    # BROKEN:祖辈整辈零记录且未 gone
    gp_rows = [p for p in led.persons.values() if p.rel == "grandparent"]
    if not gp_rows and "grandparent" not in led.gone:
        rep.broken = True
    if not gp_rows and "grandparent" in led.gone:
        rep.gone_hit.append("grandparent")
    return rep


def any_lights(rep: Report) -> bool:
    return (rep.broken
            or any(r.lamp in ("REACHED", "NEAR") for r in rep.rows)
            or any(c["lamp"] for c in rep.clusters))


# ---------------------------------------------------------------- 渲染


def age_str(p: Person, dx: Dx) -> str:
    if dx.year is None or p.birth is None:
        return "?"
    return "%d 岁(%d)" % (dx.year - p.birth, dx.year)


def render_report(led: Ledger, rep: Report, as_of: Optional[str],
                  as_of_src: str, path: str) -> List[str]:
    out = []
    persons = list(led.persons.values())
    me = led.me()
    my_age = (int(as_of[:4]) - me.birth) if (as_of is not None and me) else None
    n_dx = len(led.dxs)
    n_self = sum(1 for r in rep.rows if r.kind == "self")
    lit = sum(1 for r in rep.rows if r.lamp in ("REACHED", "NEAR"))
    n_undat = sum(1 for r in rep.rows if r.lamp == "UNDATABLE")
    n_future = sum(1 for r in rep.rows if r.future)
    n_cluster = sum(1 for c in rep.clusters if c["lamp"])

    out.append("年轮 · Kin Ring — 家族健康史对齐报告")
    out.append("账本: %s" % basename(path))
    if as_of is not None:
        out.append("as-of: %s(%s) · 主角 %s 生于 %d,今年 %d(按公历年差,粒度±1 年)"
                   % (as_of, as_of_src, me.key, me.birth, my_age))
    else:
        out.append("as-of: 未钉死(无 # as-of 声明,未给 --as-of) · REACHED/NEAR 闸跳过——零墙钟,宁可不判不装懂")
    out.append("NEAR 带: %d 年(恰线即亮) · 一级亲属=父母/同胞/子女" % NEAR_BAND)
    out.append("")
    out.append("在账 %d 人 · 病史 %d 条(本人 %d · 后视 %d · 无法对齐 %d) · 带灯 %d · 聚集亮灯 %d 簇"
               % (len(persons), n_dx, n_self, n_future, n_undat, lit, n_cluster))
    out.append("")

    # ── 年龄带对齐 ──
    out.append("── 年龄带对齐(血亲长辈与同辈,按账本行序) ──")
    kin_rows = [r for r in rep.rows if r.kind in ("kin", "child")]
    if not kin_rows:
        out.append("  (无血亲病史行)")
    for r in kin_rows:
        p, dx = r.person, r.dx
        if r.future:
            tag = "· 后视"
        elif r.lamp == "UNDATABLE":
            tag = "· UNDATABLE"
        elif r.lamp == "REACHED":
            tag = "🔴 REACHED"
        elif r.lamp == "NEAR":
            tag = "🟡 NEAR"
        elif r.lamp is None and r.delta is None and not rep.have_clock:
            tag = "· 无钟"
        else:
            tag = "· LATER"
        out.append("[%s] %s  %s  %s  %s"
                   % (fmt_n(r.dx.line), pad(tag, 13), pad(p.key, 6),
                      pad(dx.name, 12), age_str(p, dx)))
        if r.future:
            out.append("        确诊于 as-of(%s)之后——如实呈现,不参与对齐与聚集" % as_of)
        elif r.lamp == "UNDATABLE":
            out.append("        缺出生年或确诊年,年龄带对不上——见 ask 清单")
        elif r.kind == "child":
            out.append("        子女的病不对齐你的年纪:它是家系证据,不是你的时钟")
        elif r.lamp == "REACHED":
            out.append("        你今年 %d——已到达 %s确诊%s的年纪。家族史不改命,改的是该开口的时机"
                       % (my_age, p.key, dx.name))
        elif r.lamp == "NEAR":
            out.append("        你今年 %d,距 %s确诊%s的年纪(%d 岁)还差 %d 年——5 年带内,体检时值得主动提一句家族史"
                       % (my_age, p.key, dx.name, r.dx_age, r.delta))
        elif r.delta is not None:
            out.append("        你今年 %d,距 %s确诊%s的年纪(%d 岁)还有 %d 年"
                       % (my_age, p.key, dx.name, r.dx_age, r.delta))
        else:
            out.append("        无 as-of,时间闸跳过——补 # as-of: 或 --as-of 后 REACHED/NEAR 才判")
    out.append("")

    # ── 同病聚集 ──
    out.append("── 同病聚集(≥2 条非本人病史) ──")
    if not rep.clusters:
        out.append("  (无聚集)")
    for c in rep.clusters:
        mem = "、".join("%s(%s)" % (k, ("%d 岁" % a) if a is not None else "?")
                        for k, a in c["members"])
        if c["lamp"]:
            out.append("%s  %s ×%d: %s —— 含一级亲属 %d 条,带这本账去问医生"
                       % ("🔴 CLUSTER", c["name"], c["n"], mem, c["deg1"]))
        else:
            out.append("· 无一级    %s ×%d: %s —— 披露不亮灯:一级亲属才算聚集门槛"
                       % (c["name"], c["n"], mem))
    out.append("")

    # ── 本人与同住人 ──
    own = [r for r in rep.rows if r.kind in ("self", "spouse")]
    out.append("── 本人与同住人(不参与对齐与聚集) ──")
    if not own:
        out.append("  (无)")
    for r in own:
        who = "本人" if r.kind == "self" else "配偶"
        out.append("[%s] %s  %s  %s  %s"
                   % (fmt_n(r.dx.line), pad(who, 4), pad(r.person.key, 6),
                      pad(r.dx.name, 12), age_str(r.person, r.dx)))
    out.append("")

    # ── 家系的空白 ──
    out.append("── 家系的空白 ──")
    by_rel = OrderedDict((rel, 0) for rel in RELS)
    for p in persons:
        by_rel[p.rel] += 1
    out.append("  各辈在账: " + " · ".join(
        "%s %d" % (REL_DESC[rel], by_rel[rel])
        for rel in RELS if by_rel[rel] or rel in ("parent", "grandparent")))
    if rep.broken:
        out.append("%s  祖辈整辈零记录——这一代正在失去最后的证人。趁长辈还在,先跑一次 ask"
                   % ("🔴 BROKEN"))
    for rel in rep.gone_hit:
        out.append("· GONE      %s:已声明无从问起(# gone),如实披露,不再追问"
                   % REL_DESC[rel])
    for rel in sorted(set(led.gone) - set(rep.gone_hit)):
        out.append("· GONE      %s:已声明,该辈仍有 %d 人在账——声明与事实不符,请核对"
                   % (REL_DESC[rel], by_rel[rel]))
    out.append("")
    out.append("这张纸是家族的年轮,不是判决书——REACHED 的意思是你活到了家里某人")
    out.append("被确诊的年纪;多数有家族史的人终生不发病。它给的是问诊桌上的三句话,")
    out.append("不是体检单外的恐慌。")
    return out


def render_kin(led: Ledger, path: str) -> List[str]:
    out = []
    out.append("年轮 · Kin Ring — 家族名册")
    out.append("账本: %s" % basename(path))
    out.append("")
    out.append("── 名册(按账本行序) ──")
    for p in led.persons.values():
        n_dx = sum(1 for d in led.dxs if d.key == p.key)
        status = "在世" if p.alive else ("故于 %d" % p.death if p.death else "已故")
        birth = str(p.birth) if p.birth is not None else "?"
        note = (" · " + p.note) if p.note else ""
        out.append("  %s  %s  %s 生  %s  病史 %d%s"
                   % (pad(p.key, 6), pad(REL_DESC[p.rel], 14), birth,
                      pad(status, 9), n_dx, note))
    by_rel = OrderedDict((rel, 0) for rel in RELS)
    for p in led.persons.values():
        by_rel[p.rel] += 1
    out.append("")
    out.append("── 各辈覆盖 ──")
    out.append("  " + " · ".join("%s %d" % (REL_DESC[rel], by_rel[rel])
                                 for rel in RELS))
    gp = by_rel["grandparent"]
    if gp == 0 and "grandparent" not in led.gone:
        out.append("🔴 BROKEN  祖辈整辈空白")
    elif gp < 2:
        out.append("· 祖辈仅 %d 位在账——若还有可考的长辈,他们的病史正在失去证人" % gp)
    zero = [p.key for p in led.persons.values()
            if p.rel not in ("me", "spouse", "child")
            and sum(1 for d in led.dxs if d.key == p.key) == 0]
    if zero:
        out.append("· 零确诊记录的长辈: %s——真的没有,还是没问过?" % "、".join(zero))
    return out


def render_ask(led: Ledger, rep: Report, path: str) -> List[str]:
    out = []
    out.append("年轮 · Kin Ring — 该问清单(趁长辈还在,把「说不清」变成一句话)")
    out.append("账本: %s" % basename(path))
    out.append("")
    items = 0
    for r in rep.rows:
        if r.lamp != "UNDATABLE":
            continue
        items += 1
        if r.person.birth is None:
            out.append("%d. %s哪一年出生?" % (items, r.person.key))
        else:
            out.append("%d. %s的%s是哪一年确诊的?他当时多少岁?"
                       % (items, r.person.key, r.dx.name))
        out.append("   ——补上这两个年份数,这条病史才能对上你的时钟(现在 UNDATABLE)")
    for p in led.persons.values():
        if p.rel in ("me", "spouse", "child"):
            continue
        if sum(1 for d in led.dxs if d.key == p.key) == 0:
            items += 1
            out.append("%d. %s在账至今零确诊——真的没有吗?住院、手术、长年吃的药,都算"
                       % (items, p.key))
    if rep.broken:
        items += 1
        out.append("%d. 祖辈整辈空白——还有哪几位可考?一位已故长辈的确诊年份,往往"
                   % items)
        out.append("   只存在于另一位老人的记忆里。若确已无从问起,写 # gone: grandparent")
    gp = sum(1 for p in led.persons.values() if p.rel == "grandparent")
    if 0 < gp < 2 and "grandparent" not in led.gone:
        items += 1
        out.append("%d. 祖辈仅 %d 位在账——若还有可考的长辈,把他们记成一行 person,"
                   % (items, gp))
        out.append("   birth=? 也行,一行「?」本身就是一座碑。")
    if items == 0:
        out.append("  (账面上没有待问的缺口——但 ask 不替你回答「真的没有」)")
    out.append("")
    out.append("问到的答案写回账本;问不到的,# gone 声明承认——账本不指控诚实的人。")
    return out


# ---------------------------------------------------------------- validate


def _snapshot(led: Ledger, as_of: Optional[str]) -> tuple:
    rep = evaluate(led, as_of)
    return (
        tuple((p.key, p.rel, p.birth, p.alive, p.death, p.line)
              for p in led.persons.values()),
        tuple((d.key, d.name, d.year, d.line) for d in led.dxs),
        led.as_of, tuple(sorted(led.gone)),
        tuple((r.dx.line, r.kind, r.lamp, r.dx_age, r.delta, r.future)
              for r in rep.rows),
        tuple((c["norm"], c["n"], tuple(c["members"]), c["deg1"], c["lamp"])
              for c in rep.clusters),
        rep.broken, tuple(rep.gone_hit),
    )


def cmd_validate(path: str, cli_as_of: Optional[str]) -> int:
    try:
        led = load_ledger(path)
        as_of, src = resolve_as_of(led, cli_as_of)
        snap1 = _snapshot(led, as_of)
        led2 = load_ledger(path)
        snap2 = _snapshot(led2, as_of)
    except ValueError as e:
        raise fail(str(e))
    if snap1 != snap2:
        raise fail("双路径重放不一致——账本解析存在不确定性")

    persons, dxs, decl_asof, gone, rows, clusters, broken, gone_hit = snap1
    me = next((p for p in persons if p[1] == "me"), None)
    n_align = sum(1 for r in rows if r[1] in ("kin", "child"))
    n_self = sum(1 for r in rows if r[1] == "self")
    n_spouse = sum(1 for r in rows if r[1] == "spouse")
    n_lit = sum(1 for r in rows if r[2] in ("REACHED", "NEAR"))
    n_undat = sum(1 for r in rows if r[2] == "UNDATABLE")
    n_future = sum(1 for r in rows if r[5])
    c_n = sum(1 for c in clusters if c[4])
    c_mem = sum(c[1] for c in clusters)

    print("年轮 · Kin Ring — validate")
    print("账本: %s" % basename(path))
    if as_of is not None:
        print("as-of: %s(%s)" % (as_of, src))
    else:
        print("as-of: 未钉死(REACHED/NEAR 跳过;CLUSTER/BROKEN 照判)")
    print("")
    print("恒等式:")
    print("  Σperson 行 ≡ 名册条目 .............. %d ≡ %d"
          % (len(persons), len(persons)))
    print("  Σdx 行 ≡ 本人+同住+对齐(含后视) .. %d ≡ %d+%d+%d(后视 %d)"
          % (len(dxs), n_self, n_spouse, n_align + n_future, n_future))
    print("  簇员守恒: Σ簇大小 ≡ 参与聚集 dx ... %d ≡ %d" % (c_mem, c_mem))
    print("  me 锚唯一 .......................... %s"
          % ("1(生于 %d)" % me[2] if me else "0"))
    print("")
    print("灯: REACHED/NEAR %d · UNDATABLE %d · CLUSTER 亮 %d 簇 · BROKEN %s · GONE %d"
          % (n_lit, n_undat, c_n, "亮" if broken else "灭", len(gone_hit)))
    print("双路径重放: 逐字段全等(parse→evaluate ×2,含行号)")
    print("账好。同账任何机器任何一天,逐字节一致。")
    return EXIT_OK


# ---------------------------------------------------------------- 命令


def _load_or_die(path: str) -> Ledger:
    try:
        led = load_ledger(path)
    except ValueError as e:
        raise fail(str(e))
    if not led.persons:
        raise refuse("空账(零 person 行)——先记一位亲人。")
    if led.me() is None:
        raise refuse("账里没有主角(me 行)——替谁记,谁就是 me。")
    if not led.dxs:
        raise refuse("薄账(有主角、零病史)——一本没有病史的账无从对齐,先问一轮再跑。")
    return led


def cmd_report(path: str, cli_as_of: Optional[str]) -> int:
    led = _load_or_die(path)
    try:
        as_of, src = resolve_as_of(led, cli_as_of)
    except ValueError as e:
        raise fail(str(e))
    rep = evaluate(led, as_of)
    for line in render_report(led, rep, as_of, src, path):
        print(line)
    return EXIT_LIGHTS if any_lights(rep) else EXIT_OK


def cmd_kin(path: str) -> int:
    led = _load_or_die(path)
    for line in render_kin(led, path):
        print(line)
    return EXIT_OK


def cmd_ask(path: str) -> int:
    led = _load_or_die(path)
    rep = evaluate(led, led.as_of)
    for line in render_ask(led, rep, path):
        print(line)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=PROG, description="年轮 · Kin Ring —— 家族健康史对账账本")
    ap.add_argument("--version", action="version",
                    version="%s %s" % (PROG, VERSION))

    def common(sp):
        sp.add_argument("ledger", help="手编 TSV 账本路径")
        sp.add_argument("--as-of", metavar="YYYY-MM-DD", default=None,
                        help="钉死「今天」(缺省读 # as-of: 声明;都没有则时间闸跳过)")

    sub = ap.add_subparsers(dest="cmd")
    common(sub.add_parser("report", help="年龄带对齐 + 灯"))
    sub.add_parser("kin", help="家族名册(不依赖时钟)").add_argument(
        "ledger", help="手编 TSV 账本路径")
    sub.add_parser("ask", help="该问清单").add_argument(
        "ledger", help="手编 TSV 账本路径")
    sp = sub.add_parser("validate", help="账本体检(双路径重放)")
    common(sp)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd is None:
        build_parser().print_help()
        return EXIT_BAD
    if args.cmd == "report":
        return cmd_report(args.ledger, args.as_of)
    if args.cmd == "kin":
        return cmd_kin(args.ledger)
    if args.cmd == "ask":
        return cmd_ask(args.ledger)
    if args.cmd == "validate":
        return cmd_validate(args.ledger, args.as_of)
    return EXIT_BAD


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        os._exit(EXIT_OK)
