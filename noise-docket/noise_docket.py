#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""声讨 · Noise Docket —— 邻里噪音事件账本。

噪音事件发生即蒸发：日历记行程、相机记生活、账单记钱，
唯独没有一行记录「昨晚 23:47-00:31，楼上连续拖桌椅 44 分钟」。
到投诉那一刻，证据只剩情绪记忆，而情绪记忆在任何调解桌上都叫一面之词。

本件把每次噪音事件抄成一行可手编的账（TSV：日期/开始/时长/来源/强度/证据/备注），
从同一本账开出五本账：
  report   总量账 + 近窗判级（QUIET/NOTABLE/SEVERE/UNBEARABLE）+ 灯
  pattern  星期×时段热区 + 近窗前后半趋势 + 在场抽样披露
  verify   整改前后窗对比 —— 改善了多少，还是照旧
  letter   把账本渲染成一页克制的情况说明（只陈述事实，不含主观评价）
  validate 账本体检：语法、恒等式、双算法近窗重放

诚实条款：
  - 强度 1-5 是主观标尺，账本不做声学鉴定——它记的是频率×时段×时长
    这三样只有亲历者知道、也最难被否认的硬通货，letter 不上强度列；
  - 单方记录在任何调解桌上都是一方陈述，rec 列标注录音/录像的存在性，
    账本不检查文件；
  - 账本不是执法者：某时段噪声是否违法是警察与条例的事，它只把
    「事件落在法定禁止时段」这个事实摆出来；
  - 夜里的痛苦不按次数打折——夜间微觉醒让你对 3 次夜噪的痛苦可能
    超过白天 20 次，账本计数、不裁判痛苦；
  - 判级看近窗（默认 14 天），全史统计照出——账本陪伴整个周期：
    整改后判级回落，翻篇有依据；
  - 薄账分层：覆盖 < min-cover 天不出判级（DECLINE exit 3），
    但单次灯照出（一次 120 分钟的凌晨电钻不需要统计也能站住）。

零锚定：as-of 缺省 = 账本最大日期，--as-of 钉死逐字节可复现；
源码无任何系统时钟调用，同一本账任何机器任何一天输出一致。

口径通识先验（《中华人民共和国噪声污染防治法》2022-06-05 施行）：
  夜间 = 22:00-06:00；装修禁止时段 = 法定休息日/节假日全天 +
  工作日 12:00-14:00 与 20:00-次日 08:00（已交付住宅楼内）。
  全部参数可调，地方条例永远赢；法定调休节假日不自动识别，
  用 --holidays 显式补充。
"""

import argparse
import datetime
import sys

PROG = "noise_docket"

# ---------------------------------------------------------------- 时间与来源

SOURCE_ORDER = ["装修", "脚步", "拖动", "宠物", "音响", "棋牌", "人声", "机械", "其他"]

ALIASES = {
    "装修": "装修", "renovation": "装修", "电钻": "装修", "打孔": "装修",
    "冲击钻": "装修", "钻孔": "装修", "施工": "装修",
    "脚步": "脚步", "steps": "脚步", "跑跳": "脚步", "跑动": "脚步",
    "小孩跑": "脚步", "弹跳": "脚步", "球": "脚步",
    "拖动": "拖动", "furniture": "拖动", "桌椅": "拖动", "拖桌椅": "拖动",
    "挪家具": "拖动", "拖拉": "拖动",
    "宠物": "宠物", "pet": "宠物", "狗叫": "宠物", "猫跑": "宠物",
    "狗跑": "宠物", "猫叫": "宠物", "犬吠": "宠物",
    "音响": "音响", "music": "音响", "音乐": "音响", "电视": "音响",
    "唱歌": "音响", "ktv": "音响", "低音炮": "音响",
    "棋牌": "棋牌", "mahjong": "棋牌", "麻将": "棋牌",
    "人声": "人声", "voice": "人声", "喧哗": "人声", "争吵": "人声",
    "喊叫": "人声", "说话": "人声", "哭闹": "人声",
    "机械": "机械", "machine": "机械", "空调": "机械", "水泵": "机械",
    "电梯": "机械", "压缩机": "机械", "排风扇": "机械",
    "其他": "其他", "other": "其他",
}

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]

DEFAULTS = {
    "window": 14,
    "night_start": "22:00",
    "night_end": "06:00",
    "rest": "sat,sun",
    "quiet_line": 60,
    "severe_line": 180,
    "unbearable_line": 300,
    "night_line": 3,
    "night_cap": 5,
    "long_line": 90,
    "legal_line": 1,
    "min_cover": 14,
}


class LedgerError(Exception):
    """账本语法错误（exit 2）。"""


# ---------------------------------------------------------------- 解析

def parse_date(s):
    try:
        return datetime.datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise LedgerError("日期无法解析：%r（要 YYYY-MM-DD）" % s)


def parse_hhmm(s):
    s = s.strip()
    parts = s.split(":")
    if len(parts) != 2:
        raise LedgerError("时刻无法解析：%r（要 HH:MM）" % s)
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise LedgerError("时刻无法解析：%r（要 HH:MM）" % s)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise LedgerError("时刻越界：%r（00:00-23:59）" % s)
    return h * 60 + m


def canon_source(s):
    key = s.strip().lower()
    if key not in ALIASES:
        raise LedgerError("未知噪声来源：%r（可选：%s）" % (s, "、".join(SOURCE_ORDER)))
    return ALIASES[key]


def parse_strength(s):
    s = s.strip()
    if s in ("", "-"):
        return 0
    try:
        v = int(s)
    except ValueError:
        raise LedgerError("强度无法解析：%r（1-5 或留空）" % s)
    if not 1 <= v <= 5:
        raise LedgerError("强度越界：%r（1-5）" % s)
    return v


def parse_mins(s):
    s = s.strip()
    try:
        v = int(s)
    except ValueError:
        raise LedgerError("时长无法解析：%r（正整数分钟）" % s)
    if v <= 0:
        raise LedgerError("时长必须为正整数分钟：%r" % s)
    return v


def parse_ledger(text):
    """TSV → [Event]。列：date/start/mins/source/strength/rec/note。"""
    events = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    started = False
    for idx, raw in enumerate(lines, start=1):
        if raw.strip() == "" and not started:
            continue
        if raw.strip() == "":
            continue
        cols = raw.split("\t")
        if cols[0].strip().lower() == "date" and not started:
            started = True
            continue
        if len(cols) < 4:
            raise LedgerError("第 %d 行列数不足（至少 date/start/mins/source）" % idx)
        pad = list(cols) + [""] * (7 - len(cols))
        events.append({
            "line": idx,
            "date": parse_date(pad[0]),
            "start": parse_hhmm(pad[1]),
            "mins": parse_mins(pad[2]),
            "source": canon_source(pad[3]),
            "source_raw": pad[3].strip(),
            "strength": parse_strength(pad[4]),
            "rec": pad[5].strip(),
            "note": pad[6].strip(),
        })
    if not events:
        raise LedgerError("账本为空：至少需要一行事件")
    events.sort(key=lambda e: (e["date"], e["start"], e["line"]))
    return events


def load_ledger(path):
    with open(path, "r", encoding="utf-8") as f:
        return parse_ledger(f.read())


# ---------------------------------------------------------------- 参数

def rest_days(s):
    m = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
         "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    out = set()
    for tok in s.split(","):
        tok = tok.strip().lower()
        if tok in m:
            out.add(m[tok])
        elif tok:
            raise LedgerError("休息日无法解析：%r（如 sat,sun 或 六,日）" % tok)
    return out


class Params(object):
    def __init__(self, ns):
        self.window = ns.window
        self.night_start = ns.night_start
        self.night_end = ns.night_end
        self.rest = ns.rest
        self.holidays = ns.holidays
        self.quiet_line = ns.quiet_line
        self.severe_line = ns.severe_line
        self.unbearable_line = ns.unbearable_line
        self.night_line = ns.night_line
        self.night_cap = ns.night_cap
        self.long_line = ns.long_line
        self.legal_line = ns.legal_line
        self.min_cover = ns.min_cover
        self._night_start = parse_hhmm(self.night_start)
        self._night_end = parse_hhmm(self.night_end)
        self._rest = rest_days(self.rest)
        self._holidays = set()
        if self.holidays:
            for tok in self.holidays.split(","):
                if tok.strip():
                    self._holidays.add(parse_date(tok))

    def is_night(self, ev):
        return (ev["start"] >= self._night_start
                or ev["start"] < self._night_end) \
            if self._night_start > self._night_end \
            else self._night_start <= ev["start"] < self._night_end

    def is_rest_day(self, d):
        return d.weekday() in self._rest or d in self._holidays

    def is_offhours(self, ev):
        """法定禁止时段的装修作业（按开始时刻判定，跨午夜披露）。"""
        if ev["source"] != "装修":
            return False
        if self.is_rest_day(ev["date"]):
            return True
        s = ev["start"]
        return (720 <= s < 840) or s >= 1200 or s < 480

    def ends_next_day(self, ev):
        return ev["start"] + ev["mins"] > 1440


# ---------------------------------------------------------------- 统计

def hhmm(m):
    return "%02d:%02d" % (m // 60, m % 60)


def fmt_mins(v):
    return "%d 分钟（%d 小时 %d 分）" % (v, v // 60, v % 60)


def pct(a, b):
    return "%.1f%%" % (100.0 * a / b) if b else "—"


def clip(events, as_of):
    return [e for e in events if e["date"] <= as_of]


def window_bounds(first_day, as_of, p):
    w0 = as_of - datetime.timedelta(days=p.window - 1)
    if w0 < first_day:
        w0 = first_day
    return w0, as_of


def in_window(ev, w0, w1):
    return w0 <= ev["date"] <= w1


def stats(events, p=None):
    s = {
        "cnt": len(events),
        "mins": sum(e["mins"] for e in events),
        "night_cnt": 0,
        "night_mins": 0,
        "off_cnt": 0,
        "days": sorted(set(e["date"] for e in events)),
        "by_source": {},
        "by_weekday": {i: [0, 0] for i in range(7)},
        "by_bucket": {},
    }
    for e in events:
        src = e["source"]
        acc = s["by_source"].setdefault(src, [0, 0])
        acc[0] += 1
        acc[1] += e["mins"]
        if p is not None and p.is_night(e):
            s["night_cnt"] += 1
            s["night_mins"] += e["mins"]
        wd = e["date"].weekday()
        s["by_weekday"][wd][0] += 1
        s["by_weekday"][wd][1] += e["mins"]
        b = e["start"] // 60
        key = {(0, 6): "00-06", (6, 9): "06-09", (9, 12): "09-12",
               (12, 14): "12-14", (14, 19): "14-19",
               (19, 22): "19-22", (22, 24): "22-24"}[
            next(k for k in [(0, 6), (6, 9), (9, 12), (12, 14),
                             (14, 19), (19, 22), (22, 24)]
                 if k[0] <= b < k[1])]
        acc_b = s["by_bucket"].setdefault(key, [0, 0])
        acc_b[0] += 1
        acc_b[1] += e["mins"]
    return s


def build_stats(events, as_of, p):
    if not events:
        return None
    first_day = events[0]["date"]
    last_day = events[-1]["date"]
    if as_of < first_day:
        return None
    ev_all = clip(events, as_of)
    w0, w1 = window_bounds(first_day, as_of, p)
    ev_win = [e for e in ev_all if in_window(e, w0, w1)]
    all_s = stats(ev_all, p)
    win_s = stats(ev_win, p)
    cover_days = (as_of - first_day).days + 1
    lamps = []
    off_win = [e for e in ev_win if p.is_offhours(e)]
    if p.legal_line > 0 and len(off_win) >= p.legal_line:
        off_all = [e for e in ev_all if p.is_offhours(e)]
        lamps.append({
            "name": "OFF-HOURS", "lit": True,
            "text": "近窗禁令时段装修 %d 次（全史 %d 次）——法定禁令线一次也该有个说法"
                    % (len(off_win), len(off_all))})
    long_win = [e for e in ev_win if e["mins"] >= p.long_line and p.is_night(e)]
    if long_win:
        lamps.append({
            "name": "LONG-NIGHT", "lit": True,
            "text": "近窗夜间长单 %d 次（单次 ≥%d 分钟且落在夜间）"
                    % (len(long_win), p.long_line)})
    if not long_win:
        lamps.append({
            "name": "LONG-NIGHT", "lit": False,
            "text": "近窗无夜间长单（单次 ≥%d 分钟且落在夜间）" % p.long_line})
    if p.legal_line <= 0:
        lamps.insert(0, {
            "name": "OFF-HOURS", "lit": False,
            "text": "OFF-HOURS 灯已用 --legal-line 0 关闭"})
    # 近窗前后半趋势（分钟口径）
    half = p.window // 2
    h0_end = w0 + datetime.timedelta(days=half - 1)
    h1_start = h0_end + datetime.timedelta(days=1)
    front = [e for e in ev_win if e["date"] <= h0_end]
    back = [e for e in ev_win if e["date"] >= h1_start]
    fm, bm = sum(e["mins"] for e in front), sum(e["mins"] for e in back)
    if fm == 0 and bm == 0:
        trend = ("STABLE", "前后半窗均无事件")
    elif fm == 0:
        trend = ("ESCALATING", "前半窗 0 分钟 → 后半窗 %d 分钟 —— 新爆发" % bm)
    elif bm <= fm / 2.0:
        trend = ("IMPROVING", "前半窗 %d 分钟/%d 次 → 后半窗 %d 分钟/%d 次 —— 回落中"
                 % (fm, len(front), bm, len(back)))
    elif bm >= fm * 2.0:
        trend = ("ESCALATING", "前半窗 %d 分钟/%d 次 → 后半窗 %d 分钟/%d 次 —— 恶化中"
                 % (fm, len(front), bm, len(back)))
    else:
        trend = ("STABLE", "前半窗 %d 分钟/%d 次 → 后半窗 %d 分钟/%d 次 —— 平稳"
                 % (fm, len(front), bm, len(back)))
    # 判级
    thin = cover_days < p.min_cover
    reasons = []
    if thin:
        grade_name = "DECLINE"
    elif win_s["night_cnt"] >= p.night_cap or win_s["mins"] >= p.unbearable_line:
        grade_name = "UNBEARABLE"
        reasons.append("夜间 %d 次 ≥ %d 或累计 %d 分钟 ≥ %d"
                       % (win_s["night_cnt"], p.night_cap,
                          win_s["mins"], p.unbearable_line))
    elif win_s["night_cnt"] >= p.night_line or win_s["mins"] >= p.severe_line:
        grade_name = "SEVERE"
        if win_s["night_cnt"] >= p.night_line:
            reasons.append("近窗夜间 %d 次 ≥ %d" % (win_s["night_cnt"], p.night_line))
        if win_s["mins"] >= p.severe_line:
            reasons.append("近窗累计 %d 分钟 ≥ %d" % (win_s["mins"], p.severe_line))
    elif win_s["night_cnt"] >= 1 or win_s["mins"] >= p.quiet_line:
        grade_name = "NOTABLE"
    else:
        grade_name = "QUIET"
    return {
        "first_day": first_day, "last_day": last_day, "as_of": as_of,
        "cover_days": cover_days, "w0": w0, "w1": w1,
        "all": all_s, "win": win_s, "lamps": lamps, "trend": trend,
        "grade": grade_name, "reasons": reasons, "thin": thin,
        "off_win": off_win, "ev_all": ev_all, "ev_win": ev_win,
        "night_all": [e for e in ev_all if p.is_night(e)],
        "off_all": [e for e in ev_all if p.is_offhours(e)],
        "long_all": [e for e in ev_all if e["mins"] >= p.long_line and p.is_night(e)],
    }


def exit_code(st, p):
    if st is None:
        return 3
    if any(l["lit"] for l in st["lamps"]):
        return 4
    if st["thin"]:
        return 3
    if st["grade"] in ("SEVERE", "UNBEARABLE"):
        return 4
    return 0


GRADE_TEXT = {
    "UNBEARABLE": "UNBEARABLE —— 顶格红灯：不用再忍，也不用再解释，把账本递出去",
    "SEVERE": "SEVERE —— 越过红灯线：每一次求助都需要这份账本，现在就该出示",
    "NOTABLE": "NOTABLE —— 黄灯：记着，别让它在没有分母的记忆里发酵",
    "QUIET": "QUIET —— 绿灯：目前账面上的噪音在通识线以下",
    "DECLINE": "DECLINE —— 覆盖不足，判级拒绝：噪声不是几天的事，继续记",
}


# ---------------------------------------------------------------- 命令

def header(st, ledger_name):
    ln = ["声讨 · Noise Docket — 噪音事件账本"]
    if st is None:
        ln.append("账本 %s · as-of 早于账本首日，无账可放" % ledger_name)
        return "\n".join(ln)
    days = (st["last_day"] - st["first_day"]).days + 1
    ln.append("账本 %s · 覆盖 %s → %s（%d 天 · as-of %s）"
              % (ledger_name, st["first_day"], st["last_day"], days, st["as_of"]))
    return "\n".join(ln)


def render_totals(st, p):
    a = st["all"]
    out = []
    out.append("── 总量 ──")
    out.append("事件 %d 次 · 有噪日 %d/%d（%s）· 累计 %s"
               % (a["cnt"], len(a["days"]), st["cover_days"],
                  pct(len(a["days"]), st["cover_days"]), fmt_mins(a["mins"])))
    mx = max(st["ev_all"], key=lambda e: e["mins"])
    out.append("最长单次 %d 分钟（%s %s %s）"
               % (mx["mins"], mx["date"], hhmm(mx["start"]), mx["source"]))
    na = st["night_all"]
    out.append("夜间（%s-%s）%d 次 · %d 分钟 · 占 %s"
               % (p.night_start, p.night_end, len(na),
                  sum(e["mins"] for e in na), pct(sum(e["mins"] for e in na), a["mins"])))
    oa = st["off_all"]
    out.append("禁令时段装修 %d 次（法定休息日/节假日全天 · 工作日 12-14 时 · 20 时-次日 8 时）"
               % len(oa))
    la = st["long_all"]
    if la:
        out.append("夜间长单（单次 ≥%d 分钟）全史 %d 次，最长 %d 分钟"
                   % (p.long_line, len(la), max(e["mins"] for e in la)))
    return "\n".join(out)


def render_sources(st):
    a = st["all"]
    out = ["── 来源 ──"]
    total = a["mins"] or 1
    entries = [(k, v) for k, v in a["by_source"].items()]
    entries.sort(key=lambda kv: (-kv[1][0], -kv[1][1]))
    width = 24
    for name, (cnt, mins) in entries:
        bar = "█" * max(1, int(round(mins / float(total) * width)))
        out.append("%-3s %2d 次 %5d 分  %s %s"
                   % (name, cnt, mins, bar, pct(mins, a["mins"])))
    return "\n".join(out)


def render_grade(st, p):
    w = st["win"]
    out = ["── 近窗判级（%s → %s · %d 天）──" % (st["w0"], st["w1"], p.window)]
    out.append("近窗 %d 次 · %d 分钟 · 夜间 %d 次 · 禁令装修 %d 次"
               % (w["cnt"], w["mins"], w["night_cnt"], len(st["off_win"])))
    line = "判级 " + st["grade"]
    if st["reasons"]:
        line += "（" + "；".join(st["reasons"]) + "）"
    out.append(line)
    out.append(GRADE_TEXT[st["grade"]])
    if st["grade"] in ("NOTABLE", "SEVERE"):
        out.append("（UNBEARABLE 线：夜间 ≥%d 次或累计 ≥%d 分钟——还差 %d 分钟）"
                   % (p.night_cap, p.unbearable_line,
                      max(0, p.unbearable_line - w["mins"])))
    out.append("")
    out.append("── 灯与趋势 ──")
    for l in st["lamps"]:
        out.append("%s %s  %s" % ("●" if l["lit"] else "○", l["name"], l["text"]))
    out.append("趋势（近窗前后半）：%s" % st["trend"][1])
    if st["thin"]:
        out.append("薄账：覆盖 %d 天 < %d 天，判级拒绝（exit 3）；"
                   "单次灯照出——一次超线事件不需要统计也能站住"
                   % (st["cover_days"], p.min_cover))
    return "\n".join(out)


def cmd_report(args, p):
    events = load_ledger(args.ledger)
    as_of = parse_date(args.as_of) if args.as_of else events[-1]["date"]
    ev_all = clip(events, as_of)
    st = build_stats(ev_all, as_of, p)
    name = args.ledger.replace("\\", "/").split("/")[-1]
    print(header(st, name))
    if st is None:
        return 3
    print(render_totals(st, p))
    print("")
    print(render_sources(st))
    print("")
    print(render_grade(st, p))
    return exit_code(st, p)


def cmd_pattern(args, p):
    events = load_ledger(args.ledger)
    as_of = parse_date(args.as_of) if args.as_of else events[-1]["date"]
    ev_all = clip(events, as_of)
    st = build_stats(ev_all, as_of, p)
    name = args.ledger.replace("\\", "/").split("/")[-1]
    print(header(st, name))
    if st is None:
        return 3
    a = st["all"]
    print("")
    print("── 星期分布（全史）──")
    maxc = max([v[0] for v in a["by_weekday"].values()] + [1])
    for i, wd in enumerate(WEEKDAY_CN):
        cnt, mins = a["by_weekday"][i]
        bar = "▇" * int(round(cnt / float(maxc) * 20))
        print("%s  %2d 次 %5d 分  %s" % (wd, cnt, mins, bar))
    print("")
    print("── 时段分布（全史）──")
    bucket_order = ["00-06", "06-09", "09-12", "12-14", "14-19", "19-22", "22-24"]
    maxm = max([v[1] for v in a["by_bucket"].values()] + [1])
    for key in bucket_order:
        cnt, mins = a["by_bucket"].get(key, [0, 0])
        bar = "█" * int(round(mins / float(maxm) * 20))
        print("%s  %2d 次 %5d 分  %s" % (key, cnt, mins, bar))
    print("")
    print("── 类型 × 夜间交叉 ──")
    night_by_src = {}
    for e in clip(events, as_of):
        if p.is_night(e):
            acc = night_by_src.setdefault(e["source"], [0, 0])
            acc[0] += 1
            acc[1] += e["mins"]
    if night_by_src:
        for name2, (cnt, mins) in sorted(night_by_src.items(),
                                         key=lambda kv: (-kv[1][1], kv[0])):
            print("夜间 %-3s %2d 次 %5d 分" % (name2, cnt, mins))
    else:
        print("夜间无事件")
    print("")
    print("── 在场抽样披露 ──")
    print("账本只覆盖你在场的时刻：你不在场时（上班/外出）的噪音没有分母，")
    print("白天事件系统性缺席是记账姿势的属性，不是楼里的安静。")
    print("")
    print("── 近窗前后半趋势 ──")
    print("%s" % st["trend"][1])
    return exit_code(st, p)


def cmd_verify(args, p):
    events = load_ledger(args.ledger)
    as_of = parse_date(args.as_of) if args.as_of else events[-1]["date"]
    since = parse_date(args.since)
    name = args.ledger.replace("\\", "/").split("/")[-1]
    ev_all = clip(events, as_of)
    first_day = ev_all[0]["date"]
    label = args.label or ""
    print("声讨 · Noise Docket — 整改验证（%s）" % name)
    if as_of < first_day or since > as_of:
        print("标记日 %s 早于账本首日或晚于 as-of，无账可验" % since)
        return 3
    front = [e for e in ev_all if e["date"] < since]
    back = [e for e in ev_all if e["date"] >= since]
    fdays = ((since - datetime.timedelta(days=1) - first_day).days + 1) if front else 0
    bdays = (as_of - since).days + 1
    fmins = sum(e["mins"] for e in front)
    bmins = sum(e["mins"] for e in back)
    fnight = len([e for e in front if p.is_night(e)])
    bnight = len([e for e in back if p.is_night(e)])
    frate = fmins / float(fdays) if fdays else 0.0
    brate = bmins / float(bdays) if bdays else 0.0
    print("标记日 %s%s" % (since, ("（%s）" % label) if label else ""))
    print("前窗 %s → %s（%d 天）：%d 次 · %d 分钟 · 夜间 %d 次 · %.1f 分/天"
          % (first_day, since - datetime.timedelta(days=1), fdays,
             len(front), fmins, fnight, frate))
    print("后窗 %s → %s（%d 天）：%d 次 · %d 分钟 · 夜间 %d 次 · %.1f 分/天"
          % (since, as_of, bdays, len(back), bmins, bnight, brate))
    # 恒等式
    ok = (len(front) + len(back) == len(ev_all)
          and fmins + bmins == sum(e["mins"] for e in ev_all)
          and fnight + bnight == len([e for e in ev_all if p.is_night(e)]))
    print("恒等式：前窗 + 后窗 = 全史（次数/分钟/夜间）——%s"
          % ("通过（残差 0）" if ok else "失败"))
    if not front:
        print("标记日之前没有记录，无从对比（exit 3）")
        return 3
    if frate == 0:
        if brate == 0:
            print("前后窗均无分钟记录：无噪音可验（exit 0）")
            return 0
        print("判读 WORSE —— 前窗安静、后窗起噪（exit 4）")
        return 4
    delta = 1.0 - brate / frate
    pd = "%.1f%%" % (delta * 100)
    if bnight < fnight and bdays and bnight == 0:
        night_line = "夜间从 %d 次降到 0 次" % fnight
    elif bnight < fnight:
        night_line = "夜间 %d → %d 次" % (fnight, bnight)
    else:
        night_line = "夜间 %d → %d 次" % (fnight, bnight)
    if delta >= 0.40:
        verdict, code = "IMPROVED", 0
    elif delta <= -0.40:
        verdict, code = "WORSE", 4
    else:
        verdict, code = "UNCHANGED", 0
    print("分钟天率 %.1f → %.1f（变化 %s）· %s" % (frate, brate, pd, night_line))
    if code == 4:
        print("判读 WORSE —— 谈过之后反而更响：拿这页数字去升级（exit 4）")
    elif verdict == "IMPROVED":
        print("判读 IMPROVED —— 改善 %s：%s不是客气话，是账本上的台阶"
              % (pd, "「" + label + "」" if label else "整改"))
    else:
        print("判读 UNCHANGED —— 变化在噪声里：既没资格说改好了，也还没到升级线")
    if len(back) < 2:
        print("薄账提示：后窗仅 %d 次——继续记录几天，再完全信任这个结论" % len(back))
    return code


def cmd_letter(args, p):
    events = load_ledger(args.ledger)
    as_of = parse_date(args.as_of) if args.as_of else events[-1]["date"]
    ev_all = clip(events, as_of)
    if not ev_all:
        print("as-of %s 早于账本首日，无账可放（exit 3）" % as_of)
        return 3
    first_day, last_day = ev_all[0]["date"], ev_all[-1]["date"]
    since = parse_date(args.since) if args.since else first_day
    until = parse_date(args.until) if args.until else last_day
    ev = [e for e in ev_all if since <= e["date"] <= until]
    name = args.ledger.replace("\\", "/").split("/")[-1]
    st = build_stats(ev_all, as_of, p)
    code = exit_code(st, p) if st else 3
    s = stats(ev, p)
    days = (until - since).days + 1
    total = s["mins"]
    night = [e for e in ev if p.is_night(e)]
    off = [e for e in ev if p.is_offhours(e)]
    to = args.to
    out = []
    out.append("情况说明")
    out.append("")
    out.append("致：%s" % to)
    out.append("关于：%s 至 %s 期间噪声情况" % (since, until))
    out.append("")
    out.append("以下内容基于本人逐次记录（共 %d 次），具体时刻均可回溯核对：" % s["cnt"])
    out.append("")
    out.append("一、总体情况")
    out.append("- 记录期间：%s 至 %s（%d 天，其中 %d 天有噪声记录）"
               % (since, until, days, len(s["days"])))
    out.append("- 记录总数：%d 次，累计 %s" % (s["cnt"], fmt_mins(total)))
    out.append("- 夜间（%s-%s）记录：%d 次，占 %s"
               % (p.night_start, p.night_end, len(night),
                  pct(len(night), s["cnt"])))
    if ev:
        mx = max(ev, key=lambda e: e["mins"])
        out.append("- 单次最长：%d 分钟（%s %s，%s）"
                   % (mx["mins"], mx["date"], hhmm(mx["start"]), mx["source"]))
    out.append("")
    out.append("二、按来源（次数 · 累计分钟）")
    entries = sorted(s["by_source"].items(), key=lambda kv: (-kv[1][0], -kv[1][1]))
    for name2, (cnt, mins) in entries:
        out.append("- %s：%d 次（%d 分钟）" % (name2, cnt, mins))
    if off:
        out.append("")
        out.append("三、禁令时段记录（装修）")
        for e in off:
            wd = WEEKDAY_CN[e["date"].weekday()]
            out.append("- %s（%s %s）%s %d 分钟——法定禁止时段"
                       % (e["date"], "周" + wd, hhmm(e["start"]),
                          e["source"], e["mins"]))
        out.append("口径说明：夜间指 22:00 至 06:00；已交付住宅楼内装修禁止时段"
                   "通识口径为法定休息日/节假日全天及工作日 12:00-14:00、"
                   "20:00-次日 8:00；地方条例有更严规定的从其规定。")
    elif night:
        out.append("")
        out.append("三、夜间重点记录")
        for e in sorted(night, key=lambda e: (-e["mins"]))[:5]:
            out.append("- %s %s %s %d 分钟" % (e["date"], hhmm(e["start"]),
                                               e["source"], e["mins"]))
    if ev:
        out.append("")
        out.append("四、重点记录（按单次时长，前 %d 条）" % min(5, len(ev)))
        for i, e in enumerate(sorted(ev, key=lambda e: (-e["mins"]))[:5], start=1):
            mark = " [有录音/录像]" if e["rec"] and e["rec"] != "-" else ""
            out.append("%d. %s %s %s %d 分钟%s"
                       % (i, e["date"], hhmm(e["start"]), e["source"],
                          e["mins"], mark))
    out.append("")
    if st and st["thin"]:
        out.append("附注：记录尚在积累（覆盖 %d 天），以上为阶段性事实。" % st["cover_days"])
        out.append("")
    out.append("以上内容仅陈述个人记录到的事实，不含主观评价；"
               "相关时点的录音/录像材料可提供核对。")
    print("\n".join(out))
    print("")
    print("(底稿生成自账本 %s · as-of %s；诉求另行当面沟通——账本只出示事实)"
          % (name, as_of))
    return code


def cmd_validate(args, p):
    name = args.ledger.replace("\\", "/").split("/")[-1]
    print("声讨 · Noise Docket — 账本体检（%s）" % name)
    errors = []
    warns = []
    try:
        with open(args.ledger, "r", encoding="utf-8") as f:
            text = f.read()
        lines = text.replace("\r\n", "\n").split("\n")
        events = parse_ledger(text)
    except LedgerError as e:
        print("语法错误：%s" % e)
        return 2
    # 逐行重放语法（parse_ledger 已整体校验；这里补重复与重叠）
    seen = {}
    for e in events:
        key = (e["date"], e["start"], e["source"])
        if key in seen:
            warns.append("同日同时同源疑似重复记录：%s %s %s（第 %d/%d 行）"
                         % (e["date"], hhmm(e["start"]), e["source"],
                            seen[key], e["line"]))
        else:
            seen[key] = e["line"]
    by_day = {}
    for e in events:
        by_day.setdefault(e["date"], []).append(e)
    for d, evs in sorted(by_day.items()):
        evs = sorted(evs, key=lambda e: e["start"])
        for a, b in zip(evs, evs[1:]):
            if a["source"] == b["source"] and a["start"] + a["mins"] > b["start"]:
                warns.append("%s 同源事件时间重叠：%s %d 分钟 与 %s %d 分钟"
                             "（可能是同一次的分段记录）"
                             % (d, hhmm(a["start"]), a["mins"],
                                hhmm(b["start"]), b["mins"]))
    cross = [e for e in events if e["start"] + e["mins"] > 1440]
    # 恒等式
    total_mins = sum(e["mins"] for e in events)
    by_type = {}
    night_mins = day_mins = 0
    night_cnt = 0
    for e in events:
        by_type[e["source"]] = by_type.get(e["source"], 0) + e["mins"]
        if p.is_night(e):
            night_mins += e["mins"]
            night_cnt += 1
        else:
            day_mins += e["mins"]
    id1 = (sum(by_type.values()) == total_mins)
    id2 = (night_mins + day_mins == total_mins)
    # 近窗双算法：集合过滤 == 逐日游走
    as_of = events[-1]["date"]
    first_day = events[0]["date"]
    w0, w1 = window_bounds(first_day, as_of, p)
    v1 = sum(e["mins"] for e in events if in_window(e, w0, w1))
    v2 = 0
    cur = w0
    while cur <= w1:
        for e in by_day.get(cur, []):
            v2 += e["mins"]
        cur += datetime.timedelta(days=1)
    id3 = (v1 == v2)
    print("事件 %d 次 · 累计 %d 分钟 · 夜间 %d 次/%d 分钟"
          % (len(events), total_mins, night_cnt, night_mins))
    print("恒等式一（Σ来源 = 总分钟）：%s" % ("通过" if id1 else "失败"))
    print("恒等式二（夜间 + 日间 = 总分钟）：%s（夜间 %d + 日间 %d = %d）"
          % ("通过" if id2 else "失败", night_mins, day_mins, total_mins))
    print("恒等式三（近窗 %s → %s 双算法：集合过滤 == 逐日游走）：%s（%d == %d）"
          % (w0, w1, "通过" if id3 else "失败", v1, v2))
    if cross:
        print("跨午夜事件 %d 次（按开始日归属、开始时刻判夜间/禁令）：" % len(cross))
        for e in cross:
            print("  %s %s %d 分钟 → 结束于次日 %s" % (e["date"], hhmm(e["start"]),
                                                      e["mins"],
                                                      hhmm((e["start"] + e["mins"]) % 1440)))
    for w in warns:
        print("警告：%s" % w)
    if not (id1 and id2 and id3):
        print("体检失败（exit 2）")
        return 2
    print("账本体检通过%s" % ("（%d 条警告）" % len(warns) if warns else ""))
    return 0


# ---------------------------------------------------------------- 入口

def add_common(sp):
    sp.add_argument("ledger")
    sp.add_argument("--as-of", dest="as_of", default=None,
                    help="钉死回放终点（缺省 = 账本最大日期）")
    sp.add_argument("--window", type=int, default=DEFAULTS["window"])
    sp.add_argument("--night-start", dest="night_start",
                    default=DEFAULTS["night_start"])
    sp.add_argument("--night-end", dest="night_end", default=DEFAULTS["night_end"])
    sp.add_argument("--rest", default=DEFAULTS["rest"])
    sp.add_argument("--holidays", default="",
                    help="法定节假日补充，逗号分隔（不自动识别调休）")
    sp.add_argument("--quiet-line", dest="quiet_line", type=int,
                    default=DEFAULTS["quiet_line"])
    sp.add_argument("--severe-line", dest="severe_line", type=int,
                    default=DEFAULTS["severe_line"])
    sp.add_argument("--unbearable-line", dest="unbearable_line", type=int,
                    default=DEFAULTS["unbearable_line"])
    sp.add_argument("--night-line", dest="night_line", type=int,
                    default=DEFAULTS["night_line"])
    sp.add_argument("--night-cap", dest="night_cap", type=int,
                    default=DEFAULTS["night_cap"])
    sp.add_argument("--long-line", dest="long_line", type=int,
                    default=DEFAULTS["long_line"])
    sp.add_argument("--legal-line", dest="legal_line", type=int,
                    default=DEFAULTS["legal_line"])
    sp.add_argument("--min-cover", dest="min_cover", type=int,
                    default=DEFAULTS["min_cover"])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog=PROG, description="声讨 · Noise Docket")
    sub = ap.add_subparsers(dest="cmd")
    sp_report = sub.add_parser("report", help="总账 + 近窗判级 + 灯")
    add_common(sp_report)
    sp_pattern = sub.add_parser("pattern", help="星期×时段热区 + 趋势 + 抽样披露")
    add_common(sp_pattern)
    sp_verify = sub.add_parser("verify", help="整改前后窗对比")
    add_common(sp_verify)
    sp_verify.add_argument("--since", required=True, help="标记日（整改/调解发生日）")
    sp_verify.add_argument("--label", default="", help="标记说明（如：物业调解+隔音垫）")
    sp_letter = sub.add_parser("letter", help="情况说明底稿（只陈述事实）")
    add_common(sp_letter)
    sp_letter.add_argument("--to", default="物业服务中心")
    sp_letter.add_argument("--since", default=None)
    sp_letter.add_argument("--until", default=None)
    sp_validate = sub.add_parser("validate", help="账本体检")
    add_common(sp_validate)
    ns = ap.parse_args(argv)
    if not ns.cmd:
        ap.print_help()
        return 0
    try:
        p = Params(ns)
    except LedgerError as e:
        sys.stderr.write("参数错误：%s\n" % e)
        return 2
    try:
        if ns.cmd == "report":
            return cmd_report(ns, p)
        if ns.cmd == "pattern":
            return cmd_pattern(ns, p)
        if ns.cmd == "verify":
            return cmd_verify(ns, p)
        if ns.cmd == "letter":
            return cmd_letter(ns, p)
        if ns.cmd == "validate":
            return cmd_validate(ns, p)
    except LedgerError as e:
        sys.stderr.write("账本错误：%s\n" % e)
        return 2
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
