#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""later-never · 稍后永不 —— 稍后读的「稍后」，统计意义上就是「永不」.

问题：收藏按钮是注意力唯一一张「只刷不还」的信用卡。点星那一刻
焦虑 -1（好像已经处理过了），代价全部延期：列表无声地涨到几百条，
没有任何账单、没有任何利息提示。而且收藏行为有系统性自欺——教程、
工具类文章收藏了从不读，却还在持续收藏：收集的是「理想自我」，
不是信息。日历工具从不回答三个结构性问题：

  1. 一篇收藏放多久，就统计上死透了？（消化半衰期 t½）
  2. 按当前节奏，这个列表清得完吗？（清空 ETA，含 ETA = never）
  3. 哪些收藏该批量归档、哪些类型从此别再收了？（手术单 + 配额）

later-never 从一本可手编的 TSV 账本（id / saved_at / title / tags /
read_at，read_at 空 = 未读）确定性回答：

  * audit          总览：坟场率、消化半衰期 t½、老化曲线、摄入/消化
                   速度、清空 ETA；--max-graveyard 可作闸门（超线 exit 4）
  * triage         归档手术单：R1 越老越死（age > 4×t½ 仍未读）、
                   R2 类型幻觉（age > 2×t½ 且所有 tag 读率 < 20%）；
                   只给名单，扔与不扔仍是人的决定
  * budget         清空目标反推：每周多读几篇、或每周少收几篇，
                   两个杠杆各差多少
  * mark           把一条未读标记为已读（喂 t½ 的样本就是这么来的）
  * import-pocket  从 Pocket 的 HTML 导出重建账本（只取 Read Later 段，
                   Read Archive 段默认丢弃：那是已结案的旧账）

零依赖：Python 3.8+ 标准库。不读墙钟——一切以 --today 锚定，
同账本任何一天跑，结果可复现。数据留在本地：你的阅读史
就是你好奇心的病历，本工具不上传、不登录、不同步。

Exit codes:
  0  report produced
  2  usage error / ledger missing / malformed line
  3  refusal: nothing to audit (empty ledger, no unread, ...)
  4  gate: --max-graveyard exceeded
"""

from __future__ import annotations

import argparse
import datetime as dt
import statistics
import sys
from html.parser import HTMLParser

PROG = "later-never"

# —— 刻度（全部可以在 METHODOLOGY.md 里找到为什么是这些数） ————
WEEKS_PER_MONTH = 52.0 / 12.0          # 4.333：月→周，不用 4
DEFAULT_TODAY = "2026-09-04"
DEFAULT_GRAVEYARD_DAYS = 180           # 坟场线：半年没碰 ≈ 心理上已放弃
DEFAULT_WINDOW_DAYS = 90               # 速度窗口：一个季度，够稳又不至于
                                        # 把去年的热情算进现在的你
MIN_READ_FOR_HALFLIFE = 5              # 中位数最少要 5 个样本，少于此拒绝
                                        # 报 t½（宁缺毋滥，不瞎算）
ILLUSION_MIN_SAVED = 10                # 类型判幻觉的最小样本：10 条起评
ILLUSION_MAX_READ_RATE = 0.20          # 读率 < 20% 且收了 ≥10 条 = 幻觉类型
FALLBACK_HALFLIFE_DAYS = 30            # t½ 样本不足时的退化刻度
AGING_BUCKETS = (30, 90, 180)          # 老化曲线分桶上界（天）


class LedgerError(Exception):
    """账本本身有问题：文件缺失 / 行格式坏 / 日期非法。exit 2。"""


class Refusal(Exception):
    """拒绝审计：不是账本坏了，是没东西可算。exit 3。"""


class Gate(Exception):
    """闸门：--max-graveyard 超线。exit 4。"""


# ————————————————————————— 账本模型 —————————————————————————

class Entry(object):
    __slots__ = ("eid", "saved_at", "title", "tags", "read_at")

    def __init__(self, eid, saved_at, title, tags, read_at):
        self.eid = eid
        self.saved_at = saved_at      # dt.date，必填
        self.title = title            # str
        self.tags = tuple(tags)       # tuple[str]，可空
        self.read_at = read_at        # dt.date 或 None（未读）

    @property
    def is_read(self):
        return self.read_at is not None

    @property
    def delay_days(self):
        """收藏 → 阅读的延迟；未读条目没有。"""
        if self.read_at is None:
            return None
        return (self.read_at - self.saved_at).days

    def age_days(self, today):
        return (today - self.saved_at).days


def parse_date(text, where):
    try:
        return dt.datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise LedgerError("%s: 日期不是 YYYY-MM-DD：%r" % (where, text))


def parse_tags(text):
    if not text.strip():
        return ()
    return tuple(t.strip() for t in text.split(";") if t.strip())


def parse_tsv_line(line, lineno):
    parts = line.split("\t")
    if len(parts) != 5:
        raise LedgerError(
            "第 %d 行：应为 5 列 (id/saved_at/title/tags/read_at)，实际 %d 列"
            % (lineno, len(parts)))
    eid, saved, title, tags, read = (p.strip() for p in parts)
    if not eid:
        raise LedgerError("第 %d 行：id 为空" % lineno)
    if "\n" in title or ";" in eid:
        raise LedgerError("第 %d 行：title 含换行或 id 含分号" % lineno)
    saved_at = parse_date(saved, "第 %d 行 saved_at" % lineno)
    read_at = parse_date(read, "第 %d 行 read_at" % lineno) if read else None
    if read_at is not None and read_at < saved_at:
        raise LedgerError("第 %d 行：read_at 早于 saved_at（还没收藏就读了？）" % lineno)
    return Entry(eid, saved_at, title, parse_tags(tags), read_at)


def load_library(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise LedgerError("打不开账本 %s：%s" % (path, exc))
    entries = []
    seen = set()
    header_seen = False
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        if not header_seen and line.split("\t")[0].strip().lower() == "id":
            header_seen = True
            continue
        entry = parse_tsv_line(line, lineno)
        if entry.eid in seen:
            raise LedgerError("第 %d 行：id 重复：%s" % (lineno, entry.eid))
        seen.add(entry.eid)
        entries.append(entry)
    return entries


def save_library(path, entries):
    rows = ["id\tsaved_at\ttitle\ttags\tread_at"]
    for e in entries:
        rows.append("\t".join((
            e.eid,
            e.saved_at.isoformat(),
            e.title.replace("\t", " "),
            ";".join(e.tags),
            e.read_at.isoformat() if e.read_at else "",
        )))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")


# ————————————————————————— 指标 —————————————————————————

def half_life(entries):
    """消化半衰期 t½：已读条目延迟的中位数（天）。

    样本 < MIN_READ_FOR_HALFLIFE 时返回 None——中位数是统计量，
    两个样本的中位数是噪音，不配叫半衰期。
    """
    delays = [e.delay_days for e in entries if e.is_read]
    if len(delays) < MIN_READ_FOR_HALFLIFE:
        return None
    return statistics.median(delays)


def graveyard_rate(entries, today, threshold=DEFAULT_GRAVEYARD_DAYS):
    """坟场率：收藏超 threshold 天仍未读的比例。"""
    if not entries:
        return 0.0
    dead = sum(1 for e in entries
               if not e.is_read and e.age_days(today) > threshold)
    return dead / len(entries)


def aging_curve(entries, today):
    """老化曲线：按收藏时长分桶，看各桶里「曾经被读过」的比例。

    读率随桶龄单调下降，就是「越放越不可能读」的经验证明。
    """
    bounds = (0,) + tuple(b + 1 for b in AGING_BUCKETS)
    labels = ["0–30 天", "31–90 天", "91–180 天", "180+ 天"]
    buckets = []
    for i, label in enumerate(labels):
        lo, hi = bounds[i], (bounds[i + 1] if i + 1 < len(bounds) else None)
        members = [e for e in entries
                   if e.age_days(today) >= lo
                   and (hi is None or e.age_days(today) < hi)]
        n = len(members)
        read = sum(1 for e in members if e.is_read)
        buckets.append({
            "label": label, "n": n, "read": read,
            "read_rate": (read / n) if n else None,
        })
    return buckets


def velocities(entries, today, window=DEFAULT_WINDOW_DAYS):
    """近 window 天的摄入 / 消化速度（篇/周）。

    消化按 read_at 落窗计——读的是哪天读的，不管它是什么时候收的。
    """
    cutoff = today - dt.timedelta(days=window)
    saved = sum(1 for e in entries if e.saved_at > cutoff)
    read = sum(1 for e in entries if e.is_read and e.read_at > cutoff)
    weeks = window / 7.0
    return {"save_per_week": saved / weeks,
            "read_per_week": read / weeks,
            "saved_n": saved, "read_n": read, "window": window}


def clear_eta(entries, today, window=DEFAULT_WINDOW_DAYS):
    """清空 ETA（周）。净消化 ≤ 0 → None（结构性永不清空）。"""
    vel = velocities(entries, today, window)
    backlog = sum(1 for e in entries if not e.is_read)
    net = vel["read_per_week"] - vel["save_per_week"]
    if net <= 0:
        return {"backlog": backlog, "net_per_week": net,
                "eta_weeks": None, "vel": vel}
    return {"backlog": backlog, "net_per_week": net,
            "eta_weeks": backlog / net, "vel": vel}


def tag_profile(entries, today, threshold=DEFAULT_GRAVEYARD_DAYS):
    """类型画像：每个 tag 的收藏量、读率、坟场率，以及幻觉标记。"""
    profile = {}
    for e in entries:
        for tag in e.tags:
            cell = profile.setdefault(tag, {"saved": 0, "read": 0, "dead": 0})
            cell["saved"] += 1
            if e.is_read:
                cell["read"] += 1
            elif e.age_days(today) > threshold:
                cell["dead"] += 1
    rows = []
    for tag, cell in profile.items():
        read_rate = cell["read"] / cell["saved"]
        illusion = (cell["saved"] >= ILLUSION_MIN_SAVED
                    and read_rate < ILLUSION_MAX_READ_RATE)
        rows.append({"tag": tag, "saved": cell["saved"],
                     "read": cell["read"], "read_rate": read_rate,
                     "dead": cell["dead"], "illusion": illusion})
    rows.sort(key=lambda r: (-r["saved"], r["tag"]))
    return rows


def _effective_halflife(t_half):
    """triage 用的刻度：t½ 缺失时退化到绝对阈值（并如实标注）。"""
    if t_half is None:
        return FALLBACK_HALFLIFE_DAYS, True
    return max(t_half, 1.0), False


def triage(entries, today, t_half):
    """归档手术单。R1 越老越死；R2 类型幻觉。返回 (groups, degraded)。"""
    scale, degraded = _effective_halflife(t_half)
    tag_read = {r["tag"]: (r["read_rate"], r["saved"])
                for r in tag_profile(entries, today)}
    unread = [e for e in entries if not e.is_read]

    def all_tags_illusion(e):
        if not e.tags:
            return False
        return all(tag_read.get(t, (1.0, 0))[0] < ILLUSION_MAX_READ_RATE
                   and tag_read.get(t, (1.0, 0))[1] >= ILLUSION_MIN_SAVED
                   for t in e.tags)

    r1 = [e for e in unread if e.age_days(today) > max(4 * scale, 30)]
    r2 = [e for e in unread
          if e not in r1
          and e.age_days(today) > max(2 * scale, 30)
          and all_tags_illusion(e)]
    return {"r1": r1, "r2": r2}, degraded


def budget(entries, today, months, window=DEFAULT_WINDOW_DAYS):
    """清空目标反推：两个杠杆各差多少。

    杠杆 A（多读）：保持摄入，消化需要提到 save + backlog/周数。
    杠杆 B（少收）：保持消化，摄入需要降到 read − backlog/周数；
    若算出负数，说明光停收都不够，必须加读。
    """
    if months <= 0:
        raise LedgerError("--months 必须为正")
    vel = velocities(entries, today, window)
    backlog = sum(1 for e in entries if not e.is_read)
    weeks = months * WEEKS_PER_MONTH
    drain = backlog / weeks                       # 每周净消化需求
    need_read = vel["save_per_week"] + drain
    cap_save = vel["read_per_week"] - drain
    return {"backlog": backlog, "months": months, "weeks": weeks,
            "drain_per_week": drain,
            "save_now": vel["save_per_week"],
            "read_now": vel["read_per_week"],
            "need_read": need_read, "cap_save": cap_save}


# ————————————————————————— Pocket 导入 —————————————————————————

class _PocketParser(HTMLParser):
    """解析 Pocket 官方导出的 RIL_export.html。

    结构：<h1>Read Later</h1> <ul><li><a href time_added tags>标题</a>…
    后面还有 <h1>Read Archive</h1> 的归档段。只收 Read Later 段。
    """

    def __init__(self):
        HTMLParser.__init__(self)
        self.section = None
        self.in_anchor = False
        self.anchor_attrs = None
        self.anchor_text = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.section = None          # 等文本决定是哪一段
        elif tag == "a" and self.section == "later":
            self.in_anchor = True
            self.anchor_attrs = dict(attrs)
            self.anchor_text = []

    def handle_data(self, data):
        if self.in_anchor:
            self.anchor_text.append(data)
        elif data.strip() == "Read Later":
            self.section = "later"
        elif data.strip() == "Read Archive":
            self.section = "archive"

    def handle_endtag(self, tag):
        if tag == "a" and self.in_anchor:
            self.in_anchor = False
            if self.section == "later" and self.anchor_attrs:
                self.rows.append((self.anchor_attrs, "".join(self.anchor_text)))


def import_pocket(html_path, include_archive=False):
    try:
        with open(html_path, "r", encoding="utf-8", errors="replace") as fh:
            html = fh.read()
    except OSError as exc:
        raise LedgerError("打不开导出文件 %s：%s" % (html_path, exc))
    parser = _PocketParser()
    parser.feed(html)
    entries = []
    seen = set()
    for seq, (attrs, text) in enumerate(parser.rows):
        ts = attrs.get("time_added", "")
        try:
            # 用 UTC 折算，不读本机时区：换台机器导入结果一致
            saved_at = dt.datetime.fromtimestamp(
                int(ts), dt.timezone.utc).date()
        except (ValueError, OverflowError, OSError):
            continue                      # 没有时间戳的条目进不了账本
        eid = "pk-%s-%d" % (saved_at.isoformat(), seq)
        while eid in seen:
            eid += "x"
        seen.add(eid)
        title = " ".join(text.split()) or attrs.get("href", "(无标题)"
                                                              ).strip()
        tags = parse_tags(attrs.get("tags", "").replace(",", ";"))
        entries.append(Entry(eid, saved_at, title, tags, None))
    return entries


# ————————————————————————— 报告 —————————————————————————

def _fmt_pct(x):
    return "—" if x is None else "%.0f%%" % (x * 100)


def _fmt_duration(weeks):
    if weeks < 1:
        return "%.1f 周" % weeks
    months = weeks / WEEKS_PER_MONTH
    if months < 24:
        return "%.1f 个月（%.0f 周）" % (months, weeks)
    return "%.0f 年（%.0f 个月）" % (months / 12, months)


def render_audit(entries, today, threshold, window):
    lines = []
    total = len(entries)
    read_n = sum(1 for e in entries if e.is_read)
    unread = total - read_n
    t_half = half_life(entries)
    eta = clear_eta(entries, today, window)

    lines.append("稍后读账本 · %d 条（已读 %d / 未读 %d）· 锚定 %s"
                 % (total, read_n, unread, today.isoformat()))
    lines.append("")

    g_rate = graveyard_rate(entries, today, threshold)
    lines.append("坟场率（收藏 >%d 天未读）: %.0f%%"
                 % (threshold, g_rate * 100))
    if t_half is None:
        lines.append("消化半衰期 t½      : 样本不足（已读 <%d 条不配算中位数），"
                     "先用 mark 记录阅读" % MIN_READ_FOR_HALFLIFE)
    else:
        lines.append("消化半衰期 t½      : %.1f 天 —— 收藏后 2×t½（%.0f 天）"
                     "没读，大概率永不" % (t_half, 2 * t_half))

    lines.append("")
    lines.append("老化曲线（老桶的读率是封棺定论；新桶的还没写完）：")
    for b in aging_curve(entries, today):
        lines.append("  %-9s n=%-4d 读率 %s"
                     % (b["label"], b["n"], _fmt_pct(b["read_rate"])))

    vel = eta["vel"]
    lines.append("")
    lines.append("近 %d 天速度：每周收 %.1f 篇 / 每周读 %.1f 篇（净 %+.1f）"
                 % (window, vel["save_per_week"], vel["read_per_week"],
                    vel["read_per_week"] - vel["save_per_week"]))
    if eta["eta_weeks"] is None:
        lines.append("清空 ETA           : ∞ —— 摄入 ≥ 消化，backlog（%d 条）"
                     "统计上永不清空；你不需要更努力地读，需要更少地收藏"
                     % eta["backlog"])
    else:
        lines.append("清空 ETA           : %s（backlog %d 条）"
                     % (_fmt_duration(eta["eta_weeks"]), eta["backlog"]))

    rows = tag_profile(entries, today, threshold)
    if rows:
        lines.append("")
        lines.append("类型画像（幻觉 = 收了 ≥%d 条且读率 <%d%%）："
                     % (ILLUSION_MIN_SAVED, ILLUSION_MAX_READ_RATE * 100))
        for r in rows:
            mark = "  ← 幻觉类型" if r["illusion"] else ""
            lines.append("  %-14s 收 %-3d 读 %-3d（%s）坟场 %d%s"
                         % (r["tag"], r["saved"], r["read"],
                            _fmt_pct(r["read_rate"]), r["dead"], mark))
    return "\n".join(lines), g_rate


def render_triage(entries, today, t_half):
    groups, degraded = triage(entries, today, t_half)
    lines = []
    if degraded:
        lines.append("（退化模式：t½ 样本不足，规则用绝对阈值 %d 天）"
                     % FALLBACK_HALFLIFE_DAYS)
    r1, r2 = groups["r1"], groups["r2"]
    if not r1 and not r2:
        lines.append("手术单是空的：没有条目满足归档规则。")
        return "\n".join(lines)
    lines.append("R1 · 越老越死（age > 4×t½ 仍未读，统计上已死透）：")
    for e in sorted(r1, key=lambda e: e.saved_at):
        lines.append("  [%s] %s（%s，%d 天）"
                     % (e.eid, e.title[:44], e.saved_at, e.age_days(today)))
    if r2:
        lines.append("")
        lines.append("R2 · 类型幻觉（age > 2×t½ 且所有 tag 读率 <20%）：")
        for e in sorted(r2, key=lambda e: e.saved_at):
            lines.append("  [%s] %s（%s，tags: %s）"
                         % (e.eid, e.title[:40], e.saved_at,
                            ";".join(e.tags) or "—"))
    cut = len(r1) + len(r2)
    lines.append("")
    lines.append("共 %d 条建议归档（占未读 %.0f%%）。归档不是删除："
                 % (cut, 100 * cut / max(1, sum(1 for e in entries
                                                if not e.is_read))))
    lines.append("在原工具里 archive（可搜索、不占视线）。扔与不扔，仍是你的决定。")
    return "\n".join(lines)


def render_budget(b):
    lines = []
    lines.append("目标：%d 个月内清空 %d 条 backlog（每周需净消化 %.1f 篇）"
                 % (b["months"], b["backlog"], b["drain_per_week"]))
    lines.append("")
    gap_read = b["need_read"] - b["read_now"]
    if gap_read <= 0.05:
        lines.append("杠杆 A · 多读：当前每周读 %.1f 篇已够，按现状 %d 个月内清空。"
                     % (b["read_now"], b["months"]))
    else:
        lines.append("杠杆 A · 多读：每周读 %.1f → %.1f 篇（+%.1f 篇/周，"
                     "摄入不变）" % (b["read_now"], b["need_read"], gap_read))
    lines.append("")
    if b["cap_save"] < 0:
        lines.append("杠杆 B · 少收：算出配额为负（%.1f）——即使从此零收藏，"
                     "以当前消化速度也清不完，必须同时加读。"
                     % b["cap_save"])
    else:
        lines.append("杠杆 B · 少收：每周收 %.1f → %.1f 篇（消化不变）；"
                     "超配额的收藏就是给未来的自己写借条。"
                     % (b["save_now"], b["cap_save"]))
    return "\n".join(lines)


# ————————————————————————— CLI —————————————————————————

def _add_today_arg(sp):
    sp.add_argument("--today", default=DEFAULT_TODAY,
                    help="锚定日期 YYYY-MM-DD（默认 %s，不读墙钟）"
                         % DEFAULT_TODAY)


def _load_or_refuse(path):
    entries = load_library(path)
    if not entries:
        raise Refusal("账本是空的：%s——先收藏点什么再谈审计" % path)
    return entries


def _parse_today(text):
    return parse_date(text, "--today")


def build_parser():
    ap = argparse.ArgumentParser(
        prog=PROG,
        description="稍后读的「稍后」，统计意义上就是「永不」。")
    sub = ap.add_subparsers(dest="cmd", metavar="command")

    p = sub.add_parser("audit", help="总览：坟场率 / t½ / 老化 / 速度 / ETA")
    p.add_argument("ledger")
    _add_today_arg(p)
    p.add_argument("--graveyard-days", type=int, default=DEFAULT_GRAVEYARD_DAYS)
    p.add_argument("--window", type=int, default=DEFAULT_WINDOW_DAYS)
    p.add_argument("--max-graveyard", type=float, default=None,
                   help="闸门：坟场率超过该比例则 exit 4")

    p = sub.add_parser("triage", help="归档手术单（只给名单，不删东西）")
    p.add_argument("ledger")
    _add_today_arg(p)

    p = sub.add_parser("budget", help="清空目标反推两个杠杆")
    p.add_argument("ledger")
    _add_today_arg(p)
    p.add_argument("--months", type=float, default=6.0)

    p = sub.add_parser("mark", help="把未读条目标记为已读")
    p.add_argument("ledger")
    p.add_argument("ids", nargs="+")
    _add_today_arg(p)
    p.add_argument("--when", default=None,
                   help="阅读日期 YYYY-MM-DD（默认同 --today）")

    p = sub.add_parser("import-pocket", help="从 Pocket HTML 导出重建账本")
    p.add_argument("html")
    p.add_argument("--out", required=True)

    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not args.cmd:
        build_parser().print_help()
        return 2
    try:
        if args.cmd == "audit":
            today = _parse_today(args.today)
            entries = _load_or_refuse(args.ledger)
            text, g_rate = render_audit(entries, today,
                                        args.graveyard_days, args.window)
            print(text)
            if args.max_graveyard is not None and g_rate > args.max_graveyard:
                raise Gate("坟场率 %.0f%% 超过闸门 %.0f%%"
                           % (g_rate * 100, args.max_graveyard * 100))
        elif args.cmd == "triage":
            today = _parse_today(args.today)
            entries = _load_or_refuse(args.ledger)
            if all(e.is_read for e in entries):
                raise Refusal("没有未读条目：全部已读，没什么可手术的")
            print(render_triage(entries, today, half_life(entries)))
        elif args.cmd == "budget":
            today = _parse_today(args.today)
            entries = _load_or_refuse(args.ledger)
            if all(e.is_read for e in entries):
                raise Refusal("没有未读条目：backlog 为 0，不需要预算")
            print(render_budget(budget(entries, today, args.months)))
        elif args.cmd == "mark":
            today = _parse_today(args.today)
            when = _parse_today(args.when) if args.when else today
            entries = _load_or_refuse(args.ledger)
            index = {e.eid: e for e in entries}
            for eid in args.ids:
                if eid not in index:
                    raise LedgerError("id 不存在：%s" % eid)
                if index[eid].is_read:
                    raise LedgerError("id %s 已是已读，不能重复 mark" % eid)
            for eid in args.ids:
                index[eid].read_at = when
            save_library(args.ledger, entries)
            print("已标记 %d 条为 %s 读完，账本已写回。"
                  % (len(args.ids), when.isoformat()))
        elif args.cmd == "import-pocket":
            entries = import_pocket(args.html)
            if not entries:
                raise Refusal("导出里没有可导入的 Read Later 条目")
            save_library(args.out, entries)
            print("导入 %d 条 → %s（全部为未读；mark 会逐步喂出你的 t½）"
                  % (len(entries), args.out))
        return 0
    except LedgerError as exc:
        print("%s: %s" % (PROG, exc), file=sys.stderr)
        return 2
    except Refusal as exc:
        print("%s: %s" % (PROG, exc), file=sys.stderr)
        return 3
    except Gate as exc:
        print("%s: %s" % (PROG, exc), file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
