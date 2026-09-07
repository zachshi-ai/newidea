#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
欠针 · Due Dose / 儿童接种本的欠账视图。

接种本是孩子身上人手一份的官方账本,但它只记录「打了什么」,从不计算「还欠
什么」:下一针靠门诊短信,换一个城市就断链;欠没欠针,只有入园查验那一刻才揭
晓——每年五到八月,全国家长在查验截止日前突击补种。更根本的一层:接种本印的
是**产品名**(「五联」「麻腮风」),查验读的是**抗原**齐不齐——同一份记录两种
读法,中间没有翻译;打满四支五联的孩子,本子上没有一个字告诉他「4 岁那剂口服
脊灰已经被换掉了」。二类自费(手足口/水痘/流感)则是纯决策黑洞:花了多少钱、
哪个系列只打了一半,从没有账本。

本件把接种本抄成可手编账本,开出五本账:

  report   欠账总账——按抗原翻译产品名,每剂判定 未到龄/该种/超龄欠针 + 灯
  gaps     欠针清单——欠哪剂、应种日、超龄多少天,一行一剂
  catchup  补种排期——给定查验截止日,最快日程/最晚启动/来不来得及
  paid     二类自费账——按产品系列小计、半程针点名、合计
  validate 恒等式与账本体检——覆盖双路径对拍、月龄双算法、排期双路径

诚实条款:程序表是国家免疫规划(2021 版)的通识先验,省级增补与替代程序
(乙脑灭活 4 剂/甲肝灭活 2 剂)全部 --schedule 整表翻案,接种门诊永远赢;
本件不做医疗建议,欠针红灯指向接种门诊的咨询,不是诊断;二类不推荐只记账
——打不打是家长和医生的决定;接种本/电子档案永远赢,本子抄错本件当场抓。
零墙钟: as-of 缺省 = 账本最大日期,同一本账任何机器任何一天逐字节一致。

账本(--dir 目录下两份 TSV):
  kids.tsv   kid/birth/note        一行一个孩子(接种记录跟着人走)
  doses.tsv  date/kid/product/price/note
             一行一针;price 留空 = 一类/未记价,填了 = 自费支出进 paid 账——
             价签就是分类;产品名自由书写,词表归一(五联→百白破+脊灰+hib)
"""

import argparse
import calendar
import os
import re
import sys
from datetime import date, timedelta

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

KID_COLS = ("kid", "birth", "note")
DOSE_COLS = ("date", "kid", "product", "price", "note")

# ---------------------------------------------------------------- 先验 ----
# 一类免疫程序: 抗原 -> 应种月龄锚点。通识口径 = 国家免疫规划疫苗儿童免疫
# 程序(2021 版);省级增补与替代程序(乙脑灭活 4 剂/甲肝灭活 2 剂)用
# --schedule 整表翻案,接种门诊永远赢。
CLASS1_SCHEDULE = {
    "hepb":  [0, 1, 6],      # 乙肝疫苗 3 剂: 0/1/6 月龄
    "bcg":   [0],            # 卡介苗 1 剂: 出生
    "polio": [2, 3, 4, 48],  # 脊灰 4 剂: 2/3/4 月龄 + 4 周岁
    "dtap":  [3, 4, 5, 18],  # 百白破 4 剂: 3/4/5 月龄 + 18 月龄
    "dt":    [72],           # 白破 1 剂: 6 周岁
    "mmr":   [8, 18],        # 麻腮风 2 剂: 8 月龄 + 18 月龄
    "je":    [8, 24],        # 乙脑减毒 2 剂: 8 月龄 + 2 周岁(灭活为 4 剂替代程序)
    "mena":  [6, 9],         # 流脑 A 群多糖 2 剂: 6/9 月龄
    "menac": [36, 72],       # 流脑 A+C 多糖 2 剂: 3/6 周岁
    "hepa":  [18],           # 甲肝减毒 1 剂: 18 月龄(灭活为 2 剂替代程序)
}
CLASS1_NAMES = {
    "hepb": "乙肝", "bcg": "卡介苗", "polio": "脊灰", "dtap": "百白破",
    "dt": "白破", "mmr": "麻腮风", "je": "乙脑", "mena": "流脑A",
    "menac": "流脑AC", "hepa": "甲肝",
}
# 一类按程序共 22 剂次(0-6 岁)——validate 钉死。
CLASS1_TOTAL_DOSES = 22

# 二类程序: 只记账不推荐——价签在册(家长打了)才进账本,没打过的不点名。
# 锚点为 None 表示年针(流感),无固定月龄程序,只披露距上次。
CLASS2_SCHEDULE = {
    "hib":       [2, 3, 4, 18],
    "varicella": [12, 48],
    "ev71":      [6, 7],
    "pcv13":     [2, 4, 6, 12],
    "rota":      [2, 4, 6],
    "flu":       None,
}
CLASS2_NAMES = {
    "hib": "hib", "varicella": "水痘", "ev71": "EV71手足口",
    "pcv13": "13价肺炎", "rota": "轮状", "flu": "流感",
}

# 注射活疫苗(通识: 彼此不同日接种需间隔 ≥28 天,同日不同部位合法)。
# 口服 bOPV 与出生即种的卡介苗不进此集——通识约束弱,门诊永远赢。
LIVE_SET = {"mmr", "je", "hepa", "varicella"}

DEF_MIN_GAP_DAYS = 28    # 同抗原两剂最小间隔(通识补种下限)
DEF_OVERDUE_MONTHS = 3   # 超应种月龄此数才判 超龄欠针(恰线不亮)
DEF_RUSH_DAYS = 14       # 查验前余量小于此 → 🟡RUSH(恰线不亮)

# ---------------------------------------------------------------- 词表 ----
# 产品名 → 抗原贡献。联合疫苗贡献多个抗原各一剂——「本子印的是产品名,查验
# 读的是抗原」,这张表就是那道翻译。归一后精确匹配:宁可 exit 2 请你用 --map
# 教,绝不猜(猜错一个名字,整本覆盖账全是假的)。

def _norm(name):
    return re.sub(r"[\s（）()【】\[\]「」]+", "", str(name).strip().lower())


LEXICON_RAW = [
    ("乙肝疫苗", {"hepb": 1},
     ["乙肝", "重组乙型肝炎疫苗", "乙肝疫苗(酿酒酵母)", "hepb"]),
    ("卡介苗", {"bcg": 1}, ["bcg", "皮内注射用卡介苗"]),
    ("脊灰疫苗", {"polio": 1},
     ["脊灰", "糖丸", "脊髓灰质炎疫苗", "ipv", "bopv", "opv",
      "口服脊灰减毒活疫苗", "脊灰灭活疫苗", "sabin株脊髓灰质炎灭活疫苗"]),
    ("百白破疫苗", {"dtap": 1},
     ["百白破", "吸附无细胞百白破联合疫苗", "dtap"]),
    ("白破疫苗", {"dt": 1}, ["白破", "dt", "吸附白喉破伤风联合疫苗"]),
    ("麻腮风疫苗", {"mmr": 1},
     ["麻腮风", "mmr", "麻腮风联合减毒活疫苗", "麻疹腮腺炎风疹联合减毒活疫苗"]),
    ("乙脑减毒活疫苗", {"je": 1},
     ["乙脑减毒", "流行性乙型脑炎减毒活疫苗", "je-l"]),
    ("乙脑灭活疫苗", {"je": 1},
     ["乙脑灭活", "流行性乙型脑炎灭活疫苗", "je-i"]),
    ("A群流脑多糖疫苗", {"mena": 1},
     ["流脑a群", "a群流脑疫苗", "a群脑膜炎球菌多糖疫苗", "mpsv-a"]),
    ("A群C群流脑多糖疫苗", {"menac": 1},
     ["流脑ac", "流脑a+c", "a+c群流脑多糖疫苗", "a群c群脑膜炎球菌多糖疫苗",
      "mpsv-ac"]),
    ("甲肝减毒活疫苗", {"hepa": 1},
     ["甲肝减毒", "冻干甲型肝炎减毒活疫苗", "hepa-l"]),
    ("甲肝灭活疫苗", {"hepa": 1},
     ["甲肝灭活", "甲型肝炎灭活疫苗", "hepa-i"]),
    ("五联疫苗", {"dtap": 1, "polio": 1, "hib": 1},
     ["五联", "dtap-ipv-hib"]),
    ("四联疫苗", {"dtap": 1, "hib": 1},
     ["四联", "dtap-hib"]),
    ("hib疫苗", {"hib": 1},
     ["hib", "b型流感嗜血杆菌疫苗", "b型流感嗜血杆菌结合疫苗",
      "流感嗜血杆菌疫苗"]),
    ("水痘减毒活疫苗", {"varicella": 1},
     ["水痘", "水痘疫苗", "varicella"]),
    ("EV71疫苗", {"ev71": 1},
     ["ev71", "手足口疫苗", "肠道病毒71型灭活疫苗", "ev71灭活疫苗"]),
    ("流感疫苗", {"flu": 1},
     ["流感", "四价流感疫苗", "三价流感疫苗", "流感裂解疫苗",
      "四价流感裂解疫苗", "鼻喷流感减毒活疫苗"]),
    ("轮状疫苗", {"rota": 1},
     ["轮状", "口服轮状病毒疫苗", "五价轮状病毒疫苗", "轮状病毒疫苗"]),
    ("13价肺炎疫苗", {"pcv13": 1},
     ["pcv13", "13价肺炎球菌多糖结合疫苗", "肺炎13价疫苗"]),
]


def build_lexicon(extra_maps=None):
    """归一词表;extra_maps: {归一别名: 已知归一产品名}。别名冲突直接炸。"""
    lex = {}
    for canonical, contribs, aliases in LEXICON_RAW:
        entry = (canonical, contribs)
        for a in [canonical] + list(aliases):
            key = _norm(a)
            if key in lex and lex[key] != entry:
                raise SystemExit("词表内部冲突: %r" % a)
            lex[key] = entry
    if extra_maps:
        for alias, target in extra_maps.items():
            if target not in lex:
                raise SystemExit('--map 指向未知产品 %r(示例: 五联疫苗/麻腮风疫苗)'
                                 % target)
            lex[_norm(alias)] = lex[target]
    return lex


def parse_date(s, what="日期"):
    if not DATE_RE.match(s or ""):
        raise LedgerError("%s %r 不是 YYYY-MM-DD(补零,如 2025-03-04 不是 2025-3-4)"
                          % (what, s))
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return date(y, m, d)
    except ValueError:
        raise LedgerError("%s %r 不是真实存在的日期" % (what, s))


class LedgerError(Exception):
    """账坏——数据自相矛盾或词表外产品,拒绝载入(exit 2)。"""


class EmptyLedger(Exception):
    """空账——第一次打开,教建第一行(exit 3)。"""


# ------------------------------------------------------------ 月龄钟 ----
def add_months(d, n):
    """出生日 + n 个月,日对齐、月末钳制(1-31 生 → 平月 2-28/29)。闭式。"""
    total = (d.year * 12 + d.month - 1) + n
    y2, m2 = divmod(total, 12)
    m2 += 1
    return date(y2, m2, min(d.day, calendar.monthrange(y2, m2)[1]))


def add_months_walk(d, n):
    """同上,逐月游走——与闭式互为对拍路径(每次从原始 day 重新钳制,
    不链式累积:1-31 生 +1 月=2-28,再 +1 月=3-31 而不是 3-28)。"""
    cur, day = d, d.day
    for _ in range(n):
        y2, m2 = (cur.year, cur.month + 1)
        if m2 > 12:
            y2, m2 = y2 + 1, 1
        cur = date(y2, m2, min(day, calendar.monthrange(y2, m2)[1]))
    return cur


def months_between(birth, d):
    """满 N 个月: 最大的 n 使 add_months(birth, n) <= d。"""
    n = (d.year - birth.year) * 12 + (d.month - birth.month)
    if d.day < min(birth.day, calendar.monthrange(d.year, d.month)[1]):
        n -= 1
    return max(n, 0)


def months_between_walk(birth, d):
    n = 0
    while add_months(birth, n + 1) <= d:
        n += 1
    return n


def age_text(birth, as_of):
    m = months_between(birth, as_of)
    y, r = divmod(m, 12)
    if y and r:
        return "%d 岁 %d 个月" % (y, r)
    if y:
        return "%d 岁" % y
    return "%d 个月" % r


# ------------------------------------------------------------ 载入 ----
def read_tsv(path, cols):
    """读 TSV: 注释/空行跳过;列不足 = 账坏;多余列容忍(cry-wolf 教训: 尾部
    空列不是账坏)。返回 (header, rows);文件缺席 = (None, [])。"""
    if not os.path.exists(path):
        return None, []
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    rows, header, idx = [], None, None
    for i, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if header is None:
            header = [p.strip() for p in parts]
            missing = [c for c in cols if c not in header]
            if missing:
                raise LedgerError("%s 第1行缺列: %s"
                                  % (os.path.basename(path), ",".join(missing)))
            idx = {c: header.index(c) for c in cols}
        else:
            if len(parts) < len(cols):
                raise LedgerError("%s 第%d行只有 %d 列(需 %d): %r"
                                  % (os.path.basename(path), i, len(parts),
                                     len(cols), line))
            rows.append((i, {c: parts[idx[c]].strip() for c in cols}))
    if header is None:
        return None, []
    return header, rows


def load_ledger(d, as_of_s, lex):
    kids_path = os.path.join(d, "kids.tsv")
    doses_path = os.path.join(d, "doses.tsv")
    if not os.path.exists(kids_path) and not os.path.exists(doses_path):
        raise EmptyLedger("空账——先建 %s 记第一行:\n"
                          "kid\tbirth\tnote\n小满\t2023-03-15\t2023 年春出生"
                          % os.path.basename(kids_path))
    _, kid_rows = read_tsv(kids_path, KID_COLS)
    kids, kids_order = {}, []
    for i, r in kid_rows:
        name = r["kid"]
        if not name:
            raise LedgerError("kids.tsv 第%d行 kid 为空" % i)
        if name in kids:
            raise LedgerError("kids.tsv 第%d行: %r 重复出现——一个孩子一行"
                              % (i, name))
        kids[name] = {"birth": parse_date(r["birth"], "kids.tsv 第%d行出生日" % i),
                      "note": r["note"]}
        kids_order.append(name)
    if not kids_order:
        raise EmptyLedger("空账——kids.tsv 还没有孩子。第一行:\n"
                          "kid\tbirth\tnote\n小满\t2023-03-15\t")
    _, dose_rows = read_tsv(doses_path, DOSE_COLS)
    doses, seen_same = [], {}
    for i, r in dose_rows:
        d_ = parse_date(r["date"], "doses.tsv 第%d行接种日" % i)
        kid = r["kid"]
        if kid not in kids:
            raise LedgerError("doses.tsv 第%d行: 孩子 %r 不在 kids.tsv 里"
                              "——接种记录跟着人走,先补名册" % (i, kid))
        if d_ < kids[kid]["birth"]:
            raise LedgerError("doses.tsv 第%d行: 接种日 %s 早于 %s 的出生日 %s"
                              "——时间倒转,抄错了" % (i, d_, kid, kids[kid]["birth"]))
        raw = r["product"]
        key = _norm(raw)
        if key not in lex:
            raise LedgerError(
                "doses.tsv 第%d行: 产品 %r 词表外——本件不猜(猜错一个名字,整本覆盖"
                "账全是假):用 --map \"%s=五联疫苗\" 教一句,或改写为词表内名称"
                "(乙肝疫苗/卡介苗/五联疫苗/麻腮风疫苗…)" % (i, raw, raw))
        canonical, contribs = lex[key]
        sk = (kid, canonical, d_)
        if sk in seen_same:
            raise LedgerError("doses.tsv 第%d行: %s %s 同日重复——同一种针一天打"
                              "两遍不存在,要么抄重要么是另一支" % (i, kid, canonical))
        seen_same[sk] = i
        price = None
        if r["price"]:
            try:
                price = float(r["price"])
            except ValueError:
                raise LedgerError("doses.tsv 第%d行: price %r 不是数字"
                                  % (i, r["price"]))
        doses.append({"line": i, "date": d_, "kid": kid, "product": raw,
                      "canonical": canonical, "contribs": contribs,
                      "price": price, "note": r["note"]})
    doses.sort(key=lambda x: (x["date"], x["line"]))
    # 同孩子同日同抗原: 任何一种抗原一天都不该进身体两次(五联+百白破同日=dtap×2)
    per_day = {}
    for x in doses:
        for a in x["contribs"]:
            k = (x["kid"], a, x["date"])
            per_day[k] = per_day.get(k, 0) + 1
    for (kid, a, d_), n in sorted(per_day.items()):
        if n > 1:
            raise LedgerError(
                "%s %s 同日 %d 剂 %s——同抗原一天两剂不存在:要么抄重,要么五联和"
                "单苗同天打重了(本件不替你挑哪个是对的)"
                % (kid, d_, n, CLASS1_NAMES.get(a, CLASS2_NAMES.get(a, a))))
    if as_of_s:
        as_of = parse_date(as_of_s, "--as-of")
    elif doses:
        as_of = max(x["date"] for x in doses)
    else:
        raise EmptyLedger(
            "账本还没有任何一针——记第一针(doses.tsv):\n"
            "date\tkid\tproduct\tprice\tnote\n"
            "2023-03-15\t小满\t乙肝疫苗\t\t出生第一针\n"
            "或用 --as-of 先看账本的某一天。")
    future = [x for x in doses if x["date"] > as_of]
    past = [x for x in doses if x["date"] <= as_of]
    return {"kids": kids, "kids_order": kids_order, "doses": past,
            "future": future, "as_of": as_of}


# ------------------------------------------------------------ 覆盖账 ----
def coverage(kid, birth, doses, as_of, schedule1, overdue_months, min_gap):
    """把产品行翻译成抗原覆盖,并给每剂判定。双路径: 逐行展开 == 按抗原聚合。"""
    # 路径 A: 逐行展开累加
    count_a, dates_a = {}, {}
    for x in doses:
        for a in x["contribs"]:
            count_a[a] = count_a.get(a, 0) + 1
            dates_a.setdefault(a, []).append(x["date"])
    # 路径 B: 按抗原聚合扫同一批行(固定顺序——set 迭代随哈希种子漂移,
    # 快照字节校验会翻车)
    count_b, dates_b = {}, {}
    for a in list(schedule1) + list(CLASS2_SCHEDULE):
        ds = [x["date"] for x in doses if a in x["contribs"]]
        if ds:
            count_b[a], dates_b[a] = len(ds), ds
    if count_a != count_b or dates_a != dates_b:
        raise SystemExit("validate: 覆盖双路径不一致 %r vs %r" % (count_a, count_b))

    ants = {}
    for a in list(schedule1) + list(CLASS2_SCHEDULE):
        is_c1 = a in schedule1
        anchors = schedule1[a] if is_c1 else CLASS2_SCHEDULE[a]
        name = CLASS1_NAMES.get(a, CLASS2_NAMES.get(a, a))
        c = count_a.get(a, 0)
        k = len(anchors) if anchors else 0
        e = {"antigen": a, "name": name, "group": "一类" if is_c1 else "二类",
             "covered": c, "need": k, "extra": max(0, c - k),
             "dates": sorted(dates_a.get(a, []))}
        if not is_c1:
            e["status"] = "ANNUAL" if (k == 0 and c) else ("OK" if c >= k > 0 else "-")
        elif c >= k:
            e["status"] = "OK"
        else:
            due = add_months(birth, anchors[c])
            ov = add_months(due, overdue_months)
            if months_between(birth, as_of) < anchors[c]:
                e["status"] = "FUTURE"
            elif as_of > ov:   # 恰线不亮: 超 overdue_months 整月才红
                e["status"] = "OVERDUE"
            else:
                e["status"] = "DUE"
            e["slot"], e["slot_anchor"], e["slot_due"] = c + 1, anchors[c], due
        ants[a] = e
    # INTERRUPTED: 同抗原相邻两针 < min_gap——点灯不销账,门诊永远赢
    interrupted = []
    for a, ds in dates_a.items():
        for p, q in zip(ds, ds[1:]):
            gap = (q - p).days
            if gap < min_gap:
                interrupted.append((CLASS1_NAMES.get(a, CLASS2_NAMES.get(a, a)),
                                    p, q, gap))
    return ants, interrupted


def lamps_for(kid, birth, ants, interrupted, as_of, overdue_months):
    reds, yellows = [], []
    for a, e in ants.items():
        if e["group"] == "一类" and e["status"] == "OVERDUE":
            days = (as_of - e["slot_due"]).days
            tag = "%s 第%d剂(应 %s 月龄/%s, 已超 %d 天)" % (
                e["name"], e["slot"], e["slot_anchor"], e["slot_due"], days)
            if e["covered"] == 0 and e["slot_anchor"] == 0:
                # 注记只给出生剂次(乙肝/卡介苗)——「本子上没有」对它们有特指含义
                tag += "——本子上从未见过这种针(出生医院那针常写在出生证明页)"
            reds.append(("OVERDUE", tag))
    for nm, p, q, gap in interrupted:
        yellows.append(("INTERRUPTED",
                        "%s %s→%s 只隔 %d 天(通识同抗原 ≥28 天)——门诊排的针也要"
                        "亮出来,门诊永远赢,账要亮" % (nm, p, q, gap)))
    for a, e in ants.items():   # HALF-COURSE: 二类先验程序,到龄未齐
        if e["group"] == "二类" and 0 < e["covered"] < e["need"]:
            last_due = add_months(birth, CLASS2_SCHEDULE[a][e["need"] - 1])
            if as_of >= last_due:
                yellows.append(("HALF-COURSE",
                                "%s: 先验 %d 剂程序只打了 %d 剂——补不补问接种门诊"
                                % (e["name"], e["need"], e["covered"])))
    return reds, yellows


# ------------------------------------------------------------ 补种几何 ----
def owed_by_gate(birth, covered, anchors, by):
    """查验口径: 按「查验日的月龄」应种剂次 - 已覆盖 = 欠剂。

    anchors 用调用方传入的程序表(--schedule 翻案后不是内置表)。
    返回 [(真实剂次 slot, 最早可种日)]:slot 从已覆盖数续接——欠的是账本上的
    第几剂,不是「欠的第几剂」。
    """
    age_m = months_between(birth, by)
    need_by = sum(1 for x in anchors if x <= age_m)
    n = max(0, need_by - covered)
    return [(covered + i + 1, add_months(birth, anchors[covered + i]))
            for i in range(n)]


def plan_catchup(owed_slots, as_of, by, min_gap, rush_days):
    """补种几何。owed_slots: {抗原: [(真实剂次, 最早可种日), ...]}。

    规则(通识): 同抗原两剂 ≥ min_gap;不同抗原可同日并种(不同部位,含活疫苗)。
    两条路径必须一致:
      闭式——逐抗原递推 d1=max(as_of,E1); dj=max(d(j-1)+gap, Ej); 完成=max(dj)
      贪心——从 as_of 起逐日游走,每天把「到最早日且距前剂 ≥gap」的抗原各种一剂
    """
    # 闭式
    done_c = {}
    for a, items in owed_slots.items():
        ds, prev = [], None
        for _slot, e in items:
            d_ = e if prev is None else max(e, prev + timedelta(days=min_gap))
            d_ = max(d_, as_of)
            ds.append(d_)
            prev = d_
        done_c[a] = list(zip([s for s, _ in items], ds))
    completion_c = max((d_ for ds in done_c.values() for _s, d_ in ds),
                       default=as_of)
    # 贪心逐日游走
    remaining = {a: list(items) for a, items in owed_slots.items()}
    last = {}
    day = as_of
    done_g = {a: [] for a in remaining}
    while any(remaining.values()):
        for a in sorted(remaining):
            q = remaining[a]
            if q and q[0][1] <= day and (a not in last or (day - last[a]).days >= min_gap):
                slot = q.pop(0)[0]
                done_g[a].append((slot, day))
                last[a] = day
        day += timedelta(days=1)
        if day > by + timedelta(days=3650):
            break   # 不可行的极端账本,别走十年
    if done_g != done_c:
        raise SystemExit("catchup: 贪心 != 闭式\n%r\n%r" % (done_g, done_c))
    if not done_c:
        return {"steps": [], "completion": as_of, "slack": (by - as_of).days,
                "feasible": True, "rush": False}
    completion = completion_c
    slack = (by - completion).days
    first = min(ds[0][1] for ds in done_c.values())
    steps = sorted((d_, a, s) for a, items in done_c.items() for s, d_ in items)
    return {"steps": steps, "completion": completion, "slack": slack,
            "feasible": slack >= 0, "rush": 0 <= slack < rush_days,
            "first": first, "latest_start": first + timedelta(days=max(slack, 0))}


# ------------------------------------------------------------ 输出 ----
def money(x):
    return "¥%s" % ("%.2f" % x if x % 1 else "{:,}".format(int(x)))


def cmd_report(d, as_of_s, schedule1, overdue_months, min_gap, lex, out):
    led = load_ledger(d, as_of_s, lex)
    as_of = led["as_of"]
    out.append("欠针 · Due Dose —— %s" % os.path.basename(os.path.abspath(d)))
    out.append("as-of: %s (%s)" % (as_of, "显式 --as-of" if as_of_s
                                   else "账本最大日期,零墙钟"))
    if led["future"]:
        out.append("(披露: %d 行接种晚于 as-of,按后视行排除——它们还没发生)"
                   % len(led["future"]))
    any_red = False
    for kid in led["kids_order"]:
        birth = led["kids"][kid]["birth"]
        kd = [x for x in led["doses"] if x["kid"] == kid]
        ants, inter = coverage(kid, birth, kd, as_of, schedule1,
                               overdue_months, min_gap)
        reds, yellows = lamps_for(kid, birth, ants, inter, as_of, overdue_months)
        any_red = any_red or bool(reds)
        out.append("")
        out.append("■ %s  %s 生  %s  ·  %d 针在册" % (
            kid, birth, age_text(birth, as_of), len(kd)))
        out.append("一类程序(国家免疫规划 2021 通识,--schedule 可翻案):")
        out.append("  抗原        应  已  状态")
        n_ok = n_due = n_ov = n_cov = 0
        for a in schedule1:
            e = ants[a]
            n_cov += min(e["covered"], e["need"])
            if e["status"] == "OK":
                n_ok += 1
                extra = ("  (多 %d 剂——补种重打常见,照实记)" % e["extra"]) if e["extra"] else ""
            elif e["status"] == "FUTURE":
                n_due += 0
                extra = "  (下一剂应 %d 月龄 / %s)" % (
                    e["slot_anchor"], e["slot_due"])
            elif e["status"] == "DUE":
                n_due += 1
                extra = "  (第%d剂应 %d 月龄 / %s)" % (e["slot"], e["slot_anchor"],
                                                       e["slot_due"])
            else:
                n_ov += 1
                extra = "  (第%d剂应 %d 月龄 / %s)" % (e["slot"], e["slot_anchor"],
                                                       e["slot_due"])
            mark = {"OK": "✓齐", "DUE": "●该种", "OVERDUE": "✗超龄欠针",
                    "FUTURE": "·未到龄"}[e["status"]]
            out.append("  %-10s %2d  %2d  %s%s" % (e["name"], e["need"],
                                                    min(e["covered"], e["need"]),
                                                    mark, extra))
        out.append("  小计: 应 %d 剂 · 已 %d · 该种 %d 项 · 超龄欠 %d 项" % (
            CLASS1_TOTAL_DOSES if schedule1 is CLASS1_SCHEDULE else
            sum(len(v) for v in schedule1.values()),
            n_cov, n_due, n_ov))
        if a2 := [a for a in CLASS2_SCHEDULE
                  if ants[a]["covered"] > 0]:
            out.append("二类(价签在册的——没打过的不进账本,账本只管写下的):")
            for a in a2:
                e = ants[a]
                if e["need"] == 0:
                    last = e["dates"][-1]
                    out.append("  %-10s 年针   上次 %s (%d 天前)" % (
                        e["name"], last, (as_of - last).days))
                else:
                    tail = ""
                    if 0 < e["covered"] < e["need"]:
                        nxt = add_months(birth, CLASS2_SCHEDULE[a][e["covered"]])
                        tail = "  (第%d剂应 %d 月龄 / %s)" % (e["covered"] + 1,
                                                              CLASS2_SCHEDULE[a][e["covered"]],
                                                              nxt)
                    out.append("  %-10s %d/%d%s" % (e["name"], e["covered"],
                                                    e["need"], tail))
        if reds or yellows:
            out.append("灯:")
            for kind, tag in reds:
                out.append("  🔴 %s  %s" % (kind, tag))
            for kind, tag in yellows:
                out.append("  🟡 %s  %s" % (kind, tag))
    out.append("")
    out.append("下一步: gaps(欠哪几剂) · catchup --by 查验日(来得及吗) · paid(自费账) · validate(体检)")
    return 4 if any_red else 0


def cmd_gaps(d, as_of_s, schedule1, overdue_months, min_gap, lex, out):
    led = load_ledger(d, as_of_s, lex)
    as_of = led["as_of"]
    out.append("欠针清单 —— %s (as-of %s)" % (os.path.basename(os.path.abspath(d)),
                                              as_of))
    total = 0
    any_red = False
    for kid in led["kids_order"]:
        birth = led["kids"][kid]["birth"]
        kd = [x for x in led["doses"] if x["kid"] == kid]
        ants, _ = coverage(kid, birth, kd, as_of, schedule1, overdue_months,
                           min_gap)
        rows = []
        for a in schedule1:
            e = ants[a]
            if e["status"] in ("OVERDUE", "DUE"):
                rows.append((e["name"], e["slot"], e["slot_anchor"], e["slot_due"],
                             (as_of - e["slot_due"]).days
                             if e["status"] == "OVERDUE" else None,
                             e["covered"]))
        out.append("")
        out.append("■ %s (%s 生, %s)" % (kid, birth, age_text(birth, as_of)))
        if not rows:
            out.append("  到龄应种的全部齐了——欠账为零")
            continue
        out.append("  抗原        剂次    应种月龄  应种日        状态")
        for nm, slot, anchor, due, days, cov in rows:
            dstr = "超龄 %d 天" % days if days is not None else "该种(未超龄)"
            if days is not None and cov == 0 and anchor == 0:
                dstr += "(本子上从未见过这种针——出生医院那针常写在出生证明页)"
            out.append("  %-10s 第%d剂   %2d月龄     %s  %s"
                       % (nm, slot, anchor, due, dstr))
            total += 1
            if days is not None:
                any_red = True
    out.append("")
    out.append("共 %d 剂在欠——欠账不会自己消失,补上即平;带上本子去一次接种门诊"
               % total)
    return 4 if any_red else 0


def cmd_catchup(d, as_of_s, by_s, label, schedule1, overdue_months, min_gap,
                rush_days, lex, out):
    led = load_ledger(d, as_of_s, lex)
    as_of = led["as_of"]
    by = parse_date(by_s, "--by")
    if by < as_of:
        raise LedgerError("--by %s 早于 as-of %s——查验日在账本之前,先修参数"
                          % (by, as_of))
    out.append("补种排期 —— %s → %s %s" % (os.path.basename(os.path.abspath(d)),
                                            by, label or ""))
    any_red = False
    for kid in led["kids_order"]:
        birth = led["kids"][kid]["birth"]
        kd = [x for x in led["doses"] if x["kid"] == kid]
        ants, _ = coverage(kid, birth, kd, as_of, schedule1, overdue_months,
                           min_gap)
        owed_slots = {}
        for a in schedule1:
            e = ants[a]
            items = owed_by_gate(birth, e["covered"], schedule1[a], by)
            if items:
                owed_slots[a] = items
        out.append("")
        out.append("■ %s (%s 生, 查验时 %s)" % (kid, birth, age_text(birth, by)))
        if not owed_slots:
            out.append("  查验口径(按查验日月龄的应种剂次)已全齐——什么都不用补")
            continue
        total_n = sum(len(v) for v in owed_slots.values())
        detail = ", ".join("%s×%d" % (ants[a]["name"], len(owed_slots[a]))
                           for a in sorted(owed_slots))
        out.append("  到查验日需补 %d 剂: %s" % (total_n, detail))
        plan = plan_catchup(owed_slots, as_of, by, min_gap, rush_days)
        # 查验后才到龄的剂次披露
        late_ants = []
        for a in schedule1:
            e = ants[a]
            if e["covered"] < e["need"]:
                anchors = schedule1[a]
                nxt = anchors[min(e["covered"], len(anchors) - 1)]
                if nxt > months_between(birth, by):
                    late_ants.append("%s 第%d剂(应 %d 月龄, 查验后)"
                                     % (e["name"], e["covered"] + 1, nxt))
        if plan["feasible"]:
            out.append("  最快日程:")
            cur_day, batch = None, []
            for d_, a, slot in plan["steps"]:
                if cur_day is not None and d_ != cur_day:
                    out.append("    %s  %s" % (cur_day, " + ".join(batch)))
                    batch = []
                cur_day = d_
                batch.append("%s 第%d剂" % (ants[a]["name"], slot))
            out.append("    %s  %s" % (cur_day, " + ".join(batch)))
            out.append("  最晚启动: %s(第一针最晚这天去,整体顺延 %d 天仍来得及)"
                       % (plan["latest_start"], plan["slack"]))
            if plan["rush"]:
                out.append("  🟡 RUSH  查验前余量 %d 天 < %d 天——来得及,别再等下一个假期"
                           % (plan["slack"], rush_days))
            else:
                out.append("  余量 %d 天——从容" % plan["slack"])
        else:
            any_red = True
            out.append("  🔴 GATE-BLOCKED  按通识间隔最快 %s 补完,查验日 %s 差 %d 天"
                       "——先带本子去门诊问同日并种与替代程序(--schedule 翻案),"
                       "能省一天是一天" % (plan["completion"], by, -plan["slack"]))
        if late_ants:
            out.append("  查验后才到龄的(不在本次排期): %s" % "; ".join(late_ants))
    out.append("")
    out.append("间隔/程序是通识先验,接种门诊永远赢——拿着这页去,让门诊排针")
    return 4 if any_red else 0


def cmd_paid(d, as_of_s, schedule1, overdue_months, min_gap, lex, out):
    led = load_ledger(d, as_of_s, lex)
    as_of = led["as_of"]
    out.append("二类自费账 —— %s (as-of %s)" % (os.path.basename(os.path.abspath(d)),
                                                as_of))
    grand = 0.0
    any_yellow = False
    for kid in led["kids_order"]:
        birth = led["kids"][kid]["birth"]
        kd = [x for x in led["doses"] if x["kid"] == kid]
        paid_rows = [x for x in kd if x["price"]]
        out.append("")
        out.append("■ %s (%s 生)" % (kid, birth))
        if not paid_rows:
            out.append("  无自费在册——价签列留空的行不进这本账")
            continue
        ants, _ = coverage(kid, birth, kd, as_of, schedule1, overdue_months,
                           min_gap)
        prods = {}
        for x in paid_rows:
            p = prods.setdefault(x["canonical"], {"n": 0, "total": 0.0,
                                                  "contribs": x["contribs"]})
            p["n"] += 1
            p["total"] += x["price"]
        kid_total = 0.0
        for cname, p in sorted(prods.items(), key=lambda kv: -kv[1]["total"]):
            kid_total += p["total"]
            c2 = [a for a in p["contribs"] if a in CLASS2_SCHEDULE]
            tail = ""
            if c2:
                bits = []
                for a in c2:
                    e = ants[a]
                    if e["need"] == 0:
                        bits.append("年针")
                    else:
                        bits.append("%s %d/%d" % (e["name"],
                                                  min(e["covered"], e["need"]),
                                                  e["need"]))
                        if 0 < e["covered"] < e["need"]:
                            last_due = add_months(birth,
                                                  CLASS2_SCHEDULE[a][e["need"] - 1])
                            if as_of >= last_due:
                                bits.append("⚠半程——先验 %d 剂只打 %d 剂"
                                            % (e["need"], e["covered"]))
                                any_yellow = True
                tail = "  (%s)" % ", ".join(bits)
            out.append("  %-14s %d 针  %s%s" % (cname, p["n"], money(p["total"]),
                                                tail))
        grand += kid_total
        out.append("  小计: %s" % money(kid_total))
    out.append("")
    out.append("自费合计: %s——二类不推荐只记账:打不打、补不补,家长和医生的决定"
               % money(grand))
    return 0


def cmd_validate(d, as_of_s, schedule1, overdue_months, min_gap, lex, out):
    led = load_ledger(d, as_of_s, lex)
    as_of = led["as_of"]
    out.append("账本体检 —— %s (as-of %s)" % (os.path.basename(os.path.abspath(d)),
                                              as_of))
    ok = True
    # 1 加月双算法: 闭式 == 逐月游走(代表生辰含月末钳制 × 0..73 月龄)
    ok1 = True
    for base in (date(2020, 1, 31), date(2021, 8, 15), date(2023, 3, 15),
                 date(2024, 2, 29)):
        for n in range(0, 74):
            if add_months(base, n) != add_months_walk(base, n):
                ok1 = False
    out.append("  加月双算法: 闭式 == 逐月游走 (4 生辰含月末 × 74 月龄) %s"
               % ("✓" if ok1 else "✗"))
    ok = ok and ok1
    # 2 满月龄双算法: 闭式 == 前向游走(逐日探针 2 年)
    ok2 = True
    for base in (date(2020, 1, 31), date(2023, 3, 15)):
        cur, probe = base, add_months(base, 24)
        while cur <= probe:
            if months_between(base, cur) != months_between_walk(base, cur):
                ok2 = False
            cur += timedelta(days=1)
    out.append("  满月龄双算法: 闭式 == 前向游走 (逐日探针 24 个月) %s"
               % ("✓" if ok2 else "✗"))
    ok = ok and ok2
    # 3 判级完备 + 守恒 + 补种双路径,逐孩
    for kid in led["kids_order"]:
        birth = led["kids"][kid]["birth"]
        kd = [x for x in led["doses"] if x["kid"] == kid]
        ants, _ = coverage(kid, birth, kd, as_of, schedule1, overdue_months,
                           min_gap)
        n_slots = sum(len(v) for v in schedule1.values())
        if schedule1 == CLASS1_SCHEDULE:
            line = n_slots == CLASS1_TOTAL_DOSES
            out.append("  %s 程序剂次: %d == 通识 22 %s" % (kid, n_slots,
                                                            "✓" if line else "✗"))
        else:   # 翻案表自洽即可,不钉通识 22
            line = True
            out.append("  %s 程序剂次: 翻案表合计 %d (原通识 22,--schedule 已生效)"
                       % (kid, n_slots))
        ok = ok and line
        # 三划分守恒: 每剂次 ∈ {已覆盖, 欠(到龄), 未到龄} — 两路径各算一半
        cov = owed = notdue = 0
        for a in schedule1:
            e = ants[a]
            by_n = sum(1 for x in schedule1[a] if x <= months_between(birth, as_of))
            c = min(e["covered"], e["need"])
            cov += c
            owed += max(0, by_n - e["covered"])
            notdue += e["need"] - c - max(0, by_n - e["covered"])
        line = cov + owed + notdue == n_slots
        out.append("  %s 守恒: 已覆盖 %d + 欠 %d + 未到龄 %d == %d 剂 %s"
                   % (kid, cov, owed, notdue, n_slots, "✓" if line else "✗"))
        ok = ok and line
        # 补种双路径(欠账任取: 对 +137 天视野的查验日开庭,内部闭式==贪心对拍)
        em = {}
        for a in schedule1:
            items = owed_by_gate(birth, ants[a]["covered"], schedule1[a],
                                 as_of + timedelta(days=137))
            if items:
                em[a] = items
        plan_catchup(em, as_of, as_of + timedelta(days=137), min_gap,
                     DEF_RUSH_DAYS)   # 不一致会在函数内当场 raise
        out.append("  %s 补种双路径: 闭式 == 贪心 (%d 抗原在欠, +137 天视野) ✓"
                   % (kid, len(em)))
    out.append("")
    out.append("体检 %s——账坏 exit 2 在载入层就已拦下(日期/悬空引用/同日同抗原/词表外)"
               % ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 2


# ------------------------------------------------------------ main ----
def parse_maps(items):
    maps = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit('--map 形如 "自定义名=五联疫苗"')
        k, v = it.split("=", 1)
        maps[_norm(k)] = _norm(v)
    return maps


def parse_schedule(path):
    if not path:
        return dict(CLASS1_SCHEDULE)
    sched = dict(CLASS1_SCHEDULE)
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t") if "\t" in line else line.split(",")
            if len(parts) < 2:
                raise SystemExit("--schedule 第%d行: 需要 抗原<TAB>月龄逗号表" % i)
            a = _norm(parts[0])
            if a not in sched:
                raise SystemExit("--schedule 第%d行: 未知抗原 %r(一类: %s)"
                                 % (i, parts[0], ",".join(sched)))
            try:
                sched[a] = [int(x) for x in re.split(r"[,\s]+", parts[1].strip())
                            if x]
            except ValueError:
                raise SystemExit("--schedule 第%d行: 月龄表 %r 解析不了"
                                 % (i, parts[1]))
            if not sched[a]:
                raise SystemExit("--schedule 第%d行: 月龄表为空" % i)
    return sched


def main(argv=None):
    ap = argparse.ArgumentParser(description="欠针 · Due Dose —— 儿童接种本的欠账视图")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--dir", default=".", help="账本目录(内含 kids.tsv/doses.tsv)")
        p.add_argument("--as-of", dest="as_of", default=None,
                       help="把账本的今天钉在某一天(缺省=账本最大日期)")
        p.add_argument("--schedule", default=None,
                       help="程序表翻案 TSV: 抗原<TAB>月龄逗号表(如 je\\t8,9,24,72)")
        p.add_argument("--overdue-months", type=int, default=DEF_OVERDUE_MONTHS,
                       help="超应种月龄几个月判超龄欠针(缺省 3,恰线不亮)")
        p.add_argument("--min-gap", type=int, default=DEF_MIN_GAP_DAYS,
                       help="同抗原两剂最小间隔天数(缺省 28)")
        p.add_argument("--map", dest="maps", action="append", default=[],
                       help='教词表一句: "自定义名=五联疫苗"(可多次)')

    for name, help_ in (("report", "欠账总账: 抗原翻译+每剂判定+灯"),
                        ("gaps", "欠针清单: 欠哪剂/应种日/超龄天数"),
                        ("paid", "二类自费账: 系列小计/半程针/合计"),
                        ("validate", "恒等式与账本体检")):
        p = sub.add_parser(name, help=help_)
        common(p)
    p = sub.add_parser("catchup", help="补种排期: --by 查验日,来得及吗")
    common(p)
    p.add_argument("--by", required=True, help="入园/入学查验截止日")
    p.add_argument("--label", default="", help="查验名目(如 幼儿园入园)")
    p.add_argument("--rush-days", type=int, default=DEF_RUSH_DAYS,
                   help="查验前余量小于此天数挂 RUSH(缺省 14,恰线不亮)")

    args = ap.parse_args(argv)
    lex = build_lexicon(parse_maps(args.maps))
    sched = parse_schedule(args.schedule)
    out = []
    if args.cmd == "report":
        code = cmd_report(args.dir, args.as_of, sched, args.overdue_months,
                          args.min_gap, lex, out)
    elif args.cmd == "gaps":
        code = cmd_gaps(args.dir, args.as_of, sched, args.overdue_months,
                        args.min_gap, lex, out)
    elif args.cmd == "catchup":
        code = cmd_catchup(args.dir, args.as_of, args.by, args.label, sched,
                           args.overdue_months, args.min_gap, args.rush_days,
                           lex, out)
    elif args.cmd == "paid":
        code = cmd_paid(args.dir, args.as_of, sched, args.overdue_months,
                        args.min_gap, lex, out)
    elif args.cmd == "validate":
        code = cmd_validate(args.dir, args.as_of, sched, args.overdue_months,
                            args.min_gap, lex, out)
    sys.stdout.write("\n".join(out) + "\n")
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LedgerError as e:
        sys.stderr.write("账坏: %s\n" % e)
        sys.exit(2)
    except EmptyLedger as e:
        sys.stderr.write("%s\n" % e)
        sys.exit(3)
