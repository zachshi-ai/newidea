#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper-shield · 纸盾 —— 备份的可用性账本.

问题：备份软件的绿色对勾是软件的自我表扬——它证明「任务跑过了」，
不证明「数据回得来」。备份的死亡是无声的：外接盘三个月没插上、
云订阅悄悄欠费、同步把误删也同步了；而三份「备份」可能全在同一块
NAS、同一个账号体系、同一间屋子里——冗余在纸面上，不在物理上。
「有备份」的错觉要在灾难当天才被拆穿，那通常是恢复的第一次彩排。

paper-shield 把「有备份」拆成可审计的三层，从两本可手编的 TSV
（目标账 + 事件账）确定性算出：

  * audit         按「内容范围」做 3-2-1 审计 + 三层信任分级，红灯 exit 4
  * fresh         逐目标新鲜度榜：FRESH / STALE / ROTTEN（静默断链）
  * simulate      灾难推演：simulate dead <介质>——它死了之后还剩什么、
                  最坏丢多少天（RPO）
  * drills        验证与演练史：verify / drill 是账本里唯二的硬通货
  * validate      两本账体检
  * terms         3-2-1 与 RPO 术语说明（建账参考）

三层信任：备份存在（backup 事件 → 新鲜度）→ 备份可信（verify 事件：
hash 校验 / 试读）→ 恢复可行（drill 事件：真还原过文件）。绿勾只覆盖
第一层；从未验证的备份是许愿，从未演练的恢复是首演。

诚实条款刻在实现里：账本只记你声称的事实，它不扫描磁盘——所以
verify / drill 才是唯一硬通货；无 cadence 或无事件不判新鲜度
（UNKNOWN）；事件日期在未来拒收；账本说不等于磁盘说。

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
「今天」默认真实当下，`--today` 钉死即逐字节可复现。

用法：
  python3 paper_shield.py audit targets.tsv events.tsv --today 2026-09-04
  python3 paper_shield.py fresh targets.tsv events.tsv
  python3 paper_shield.py simulate targets.tsv events.tsv dead disk
  python3 paper_shield.py drills targets.tsv events.tsv
  python3 paper_shield.py validate targets.tsv events.tsv
  python3 paper_shield.py terms

Exit codes:
  0  report produced（含绿灯）
  2  usage error / 账本缺失 / 坏行
  3  refusal: nothing to compute (空账本、指定介质不在账本中)
  4  gate: 任一内容域 ROTTEN / 从未验证 / 3-2-1 不达标
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import unicodedata
from typing import Dict, List, Optional, Tuple

PROG = "paper-shield"
VERSION = "1.0.0"

STALE_X = 1.0    # 距上次 backup > 1× 周期 → STALE
ROTTEN_X = 2.0   # 距上次 backup > 2× 周期 → ROTTEN（静默断链）

MIN_COPIES = 3   # 3-2-1：三份副本
MIN_MEDIA = 2    # 3-2-1：两种介质
OFFSITE_PLACES = ("offsite", "cloud")   # 火灾/盗窃/勒索软件够不着的存放地

EVENT_TYPES = ("backup", "verify", "drill")

DISCLAIMER = "账本只记你声称的事实，它不扫描磁盘——verify 与 drill 才是硬通货。"


class UsageError(Exception):
    """exit 2：参数或账本错误。"""


class Refusal(Exception):
    """exit 3：无可计算。"""


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def disp_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "FW" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - disp_width(text))


def padl(text: str, width: int) -> str:
    return " " * max(0, width - disp_width(text)) + text


def fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


# ---------------------------------------------------------------------------
# 账本解析
# ---------------------------------------------------------------------------

class Target:
    def __init__(self, name: str, scope: str, medium: str, place: str,
                 cadence: Optional[int], lineno: int):
        self.name = name
        self.scope = scope
        self.medium = medium
        self.place = place
        self.cadence = cadence
        self.lineno = lineno


class Event:
    def __init__(self, date: dt.date, target: str, kind: str, note: str, lineno: int):
        self.date = date
        self.target = target
        self.kind = kind
        self.note = note
        self.lineno = lineno


def load_targets(path: str) -> Dict[str, Target]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        raise UsageError(f"目标账不存在：{path}")
    targets: Dict[str, Target] = {}
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        if len(cols) < 5:
            raise UsageError(f"目标账第 {lineno} 行：需要至少 5 列"
                             f"（目标/内容域/介质/存放地/周期天），得到 {len(cols)} 列")
        name, scope, medium, place, cadence_text = cols[:5]
        if not name or not scope:
            raise UsageError(f"目标账第 {lineno} 行：目标名与内容域不能为空")
        if name in targets:
            raise UsageError(f"目标账第 {lineno} 行：目标「{name}」重复")
        if place not in ("home", "office", "offsite", "cloud"):
            raise UsageError(f"目标账第 {lineno} 行：存放地「{place}」须为 "
                             f"home / office / offsite / cloud")
        cadence: Optional[int] = None
        if cadence_text not in ("", "-"):
            try:
                cadence = int(cadence_text)
            except ValueError:
                raise UsageError(f"目标账第 {lineno} 行：周期「{cadence_text}」不是整数天数")
            if cadence <= 0:
                raise UsageError(f"目标账第 {lineno} 行：周期必须 > 0 天，得到 {cadence}")
        targets[name] = Target(name, scope, medium, place, cadence, lineno)
    if not targets:
        raise Refusal(f"目标账是空的：{path}")
    return targets


def load_events(path: str, targets: Dict[str, Target], today: dt.date) -> List[Event]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        raise UsageError(f"事件账不存在：{path}")
    events: List[Event] = []
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        if len(cols) < 3:
            raise UsageError(f"事件账第 {lineno} 行：需要至少 3 列（日期/目标/事件），得到 {len(cols)} 列")
        date_text, target, kind = cols[0], cols[1], cols[2]
        note = cols[3] if len(cols) > 3 else ""
        try:
            date = dt.datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            raise UsageError(f"事件账第 {lineno} 行：日期「{date_text}」不是 YYYY-MM-DD")
        if date > today:
            raise UsageError(f"事件账第 {lineno} 行：事件日期 {date_text} 在今天之后")
        if target not in targets:
            raise UsageError(f"事件账第 {lineno} 行：目标「{target}」不在目标账中")
        if kind not in EVENT_TYPES:
            raise UsageError(f"事件账第 {lineno} 行：事件「{kind}」须为 backup / verify / drill")
        events.append(Event(date, target, kind, note, lineno))
    if not events:
        raise Refusal(f"事件账是空的：{path}")
    events.sort(key=lambda e: (e.date, e.lineno))
    return events


# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------

def days_since(date: dt.date, today: dt.date) -> int:
    return (today - date).days


def latest_event(events: List[Event], target: str, kind: str,
                 excluded_targets: set = frozenset()) -> Optional[Event]:
    found = None
    for e in events:
        if e.target == target and e.kind == kind and target not in excluded_targets:
            found = e  # events 已按日期升序，取最后一个即最新
    return found


def freshness(last_backup: Optional[Event], target: Target,
              today: dt.date) -> Tuple[str, Optional[int]]:
    """返回 (档位, 距今天数)。UNKNOWN：无 cadence 或无 backup 事件，不判。"""
    if last_backup is None or target.cadence is None:
        return "UNKNOWN", (days_since(last_backup.date, today) if last_backup else None)
    d = days_since(last_backup.date, today)
    if d > ROTTEN_X * target.cadence:
        return "ROTTEN", d
    if d > STALE_X * target.cadence:
        return "STALE", d
    return "FRESH", d


def scope_targets(targets: Dict[str, Target], scope: str,
                  excluded_targets: set = frozenset()) -> List[Target]:
    return [t for t in targets.values()
            if t.scope == scope and t.name not in excluded_targets]


def audit_scope(targets: Dict[str, Target], events: List[Event], scope: str,
                today: dt.date, excluded_targets: set = frozenset()) -> dict:
    ts = scope_targets(targets, scope, excluded_targets)
    media = sorted({t.medium for t in ts})
    offsite = [t for t in ts if t.place in OFFSITE_PLACES]
    grades = []
    last_backup_days: Optional[int] = None
    never_backed: List[str] = []
    rotten_detail: Optional[str] = None
    for t in ts:
        lb = latest_event(events, t.name, "backup", excluded_targets)
        grade, d = freshness(lb, t, today)
        grades.append(grade)
        if d is not None and (last_backup_days is None or d < last_backup_days):
            last_backup_days = d
        if grade == "UNKNOWN" and lb is None:
            never_backed.append(t.name)
        if grade == "ROTTEN":
            rotten_detail = t.name
    if "ROTTEN" in grades:
        worst = "ROTTEN"
    elif "UNKNOWN" in grades:
        worst = "UNKNOWN"
    elif "STALE" in grades:
        worst = "STALE"
    else:
        worst = "FRESH"
    verified: List[str] = []
    never_verified: List[str] = []
    drilled = 0
    for t in ts:
        if latest_event(events, t.name, "verify", excluded_targets):
            verified.append(t.name)
        else:
            never_verified.append(t.name)
        if latest_event(events, t.name, "drill", excluded_targets):
            drilled += 1
    copies = len(ts)
    ok_321 = copies >= MIN_COPIES and len(media) >= MIN_MEDIA and len(offsite) >= 1
    unverified_any = len(never_verified) > 0
    unknown = [t.name for t, g in zip(ts, grades) if g == "UNKNOWN"]
    return {
        "scope": scope, "targets": ts, "copies": copies, "media": media,
        "offsite": len(offsite), "worst": worst, "worst_detail": rotten_detail,
        "last_backup_days": last_backup_days,
        "never_verified": never_verified, "verified": verified,
        "drilled": drilled, "ok_321": ok_321, "unverified_any": unverified_any,
        "never_backed": never_backed, "unknown": unknown,
    }


def red_reasons(a: dict) -> List[str]:
    reasons = []
    if a["worst"] == "ROTTEN":
        reasons.append(f"ROTTEN（{a['worst_detail']} 静默断链）")
    if a["unverified_any"]:
        reasons.append(f"从未验证（{'、'.join(a['never_verified'])}）")
    if not a["ok_321"]:
        lacks = []
        if a["copies"] < MIN_COPIES:
            lacks.append(f"副本 {a['copies']}<{MIN_COPIES}")
        if len(a["media"]) < MIN_MEDIA:
            lacks.append(f"介质 {len(a['media'])}<{MIN_MEDIA}")
        if a["offsite"] < 1:
            lacks.append("无异地")
        reasons.append("3-2-1 不达标（" + "、".join(lacks) + "）")
    return reasons


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

GRADE_MARK = {
    "FRESH": "· FRESH",
    "STALE": "△ STALE",
    "ROTTEN": "✗ ROTTEN（静默断链）",
    "UNKNOWN": "◌ UNKNOWN（无周期或无事件，不判）",
}


def cmd_audit(targets: Dict[str, Target], events: List[Event], today: dt.date) -> Tuple[str, int]:
    scopes = sorted({t.scope for t in targets.values()})
    lines = [f"纸盾审计 · {len(targets)} 个备份目标 · {len(scopes)} 个内容域"
             f" · {len(events)} 条事件", ""]
    lines.append("  内容域      副本  介质        异地  最新备份   从未验证           判定")
    reds = []
    for scope in scopes:
        a = audit_scope(targets, events, scope, today)
        reasons = red_reasons(a)
        verdict = "✗ RED（" + "；".join(reasons) + "）" if reasons else "· GREEN"
        if a["unknown"]:
            verdict += f"  ◌ UNKNOWN（无周期：{'、'.join(a['unknown'])}，不判新鲜度）"
        media_text = "/".join(a["media"])
        nv = "、".join(a["never_verified"]) if a["never_verified"] else "—"
        lb = f"{a['last_backup_days']} 天前" if a["last_backup_days"] is not None else "—"
        lines.append(f"  {pad(scope, 10)} {a['copies']:>2}    {pad(media_text, 15)}"
                     f" {a['offsite']:>2}    {padl(lb, 8)} {pad(nv, 16)}  {verdict}")
        if reasons:
            reds.append((scope, a, reasons))
    lines.append("")
    if not reds:
        lines.append("判定  GREEN —— 每个内容域都有人管。灾难不预约，账本每周看一眼。")
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines) + "\n", 0
    lines.append("判定  RED —— " + "、".join(s for s, _, _ in reds) + " 需要行动")
    lines.append("")
    for scope, a, reasons in reds:
        for r in reasons:
            if r.startswith("ROTTEN"):
                lines.append(f"  {scope} {r}——备份的死亡是无声的：它不会通知你，只有账本会。")
            elif r.startswith("从未验证"):
                lines.append(f"  {scope} {r}——绿勾证明任务跑过，不证明数据回得来；先 verify 一次。")
            else:
                lines.append(f"  {scope} {r}——冗余要在物理上成立，不在纸面上。")
        if a["never_backed"]:
            lines.append(f"  {scope} 这些目标从未有过 backup 事件：{'、'.join(a['never_backed'])}")
    lines.append("")
    lines.append("三层信任：backup 只证明存在，verify 才证明可信，drill 才证明可恢复。")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines) + "\n", 4


def cmd_fresh(targets: Dict[str, Target], events: List[Event], today: dt.date) -> Tuple[str, int]:
    lines = [f"新鲜度榜 · 按目标 · 今天 {today.isoformat()}", ""]
    order = sorted(targets.values(), key=lambda t: (t.scope, t.name))
    for t in order:
        lb = latest_event(events, t.name, "backup")
        grade, d = freshness(lb, t, today)
        if d is None:
            age_text = "无记录"
        else:
            age_text = f"{d} 天前（周期 {t.cadence}）" if t.cadence else f"{d} 天前"
        lines.append(f"  {pad(t.scope, 8)} {pad(t.name, 10)} {pad(t.place, 8)} {padl(age_text, 16)}"
                     f"  {GRADE_MARK[grade]}")
        lv = latest_event(events, t.name, "verify")
        ld = latest_event(events, t.name, "drill")
        extras = []
        extras.append("verify " + (f"{days_since(lv.date, today)} 天前" if lv else "从未"))
        extras.append("drill " + (f"{days_since(ld.date, today)} 天前" if ld else "从未"))
        lines.append(f"  {'':<18} {' / '.join(extras)}")
    lines.append("")
    lines.append("ROTTEN 的门槛是 2× 周期：错过一次是人祸，错过两次是断链——")
    lines.append("断链的备份不再是你以为的那份副本。")
    return "\n".join(lines) + "\n", 0


def cmd_simulate(targets: Dict[str, Target], events: List[Event], today: dt.date,
                 dead_medium: str) -> Tuple[str, int]:
    hit = [t.name for t in targets.values() if t.medium == dead_medium]
    if not hit:
        known = sorted({t.medium for t in targets.values()})
        raise Refusal(f"账本里没有介质「{dead_medium}」。现有的介质：{'、'.join(known)}")
    dead_set = set(hit)
    scopes = sorted({t.scope for t in targets.values()})
    lines = [f"灾难推演 · 「{dead_medium}」今天全灭（{len(hit)} 个目标："
             f"{'、'.join(sorted(dead_set))}）", ""]
    lost_scopes = []
    for scope in scopes:
        survivors = [t for t in scope_targets(targets, scope) if t.medium != dead_medium]
        if not survivors:
            lines.append(f"  {pad(scope, 8)} ✗ 全灭——这个内容域只活在 {dead_medium} 上。")
            lost_scopes.append(scope)
            continue
        # RPO：存活副本里「最新的 backup」距今天数——最新可信时点
        backups = [days_since(latest_event(events, t.name, "backup").date, today)
                   for t in survivors
                   if latest_event(events, t.name, "backup") is not None]
        if not backups:
            lines.append(f"  {pad(scope, 8)} ◌ 存活副本从未有过 backup 事件——纸面上的副本。")
            continue
        best_days = min(backups)
        medias = sorted({t.medium for t in survivors})
        offsite = sum(1 for t in survivors if t.place in OFFSITE_PLACES)
        never_v = [t.name for t in survivors
                   if not latest_event(events, t.name, "verify")]
        note = ""
        if never_v:
            note += f"（从未验证：{'、'.join(never_v)}）"
        lines.append(f"  {pad(scope, 8)} 剩 {len(survivors)} 份 · 介质 {'/'.join(medias)}"
                     f" · 异地 {offsite} · 最坏丢最近 {best_days} 天（RPO）{note}")
    lines.append("")
    if lost_scopes:
        lines.append(f"全灭名单：{'、'.join(lost_scopes)}——单点不叫备份，叫侥幸。")
    else:
        lines.append("没有内容域全灭：冗余在物理上成立。但注意 RPO——")
        lines.append("「剩几份」回答活不活得成，「丢多少天」回答疼不疼。")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines) + "\n", 0


def cmd_drills(targets: Dict[str, Target], events: List[Event], today: dt.date) -> Tuple[str, int]:
    lines = ["验证与演练史 · verify / drill 是账本里唯二的硬通货", ""]
    rows = []
    for t in sorted(targets.values(), key=lambda t: (t.scope, t.name)):
        lv = latest_event(events, t.name, "verify")
        ld = latest_event(events, t.name, "drill")
        nb = latest_event(events, t.name, "backup")
        n_events = sum(1 for e in events if e.target == t.name)
        rows.append((t, nb, lv, ld, n_events))
    for t, nb, lv, ld, n_events in rows:
        def age(e: Optional[Event]) -> str:
            return f"{days_since(e.date, today)} 天前" if e else "从未"
        lines.append(f"  {pad(t.scope, 8)} {pad(t.name, 12)} backup {padl(age(nb), 8)}"
                     f"  verify {padl(age(lv), 8)}  drill {padl(age(ld), 8)}  共 {n_events} 条")
    lines.append("")
    drills = sum(1 for _, _, _, ld, _ in rows if ld)
    if drills == 0:
        lines.append("整本账没有一次恢复演练：恢复流程的第一次彩排排在灾难当天。")
        lines.append("drill 不需要灾难——每月随手还原一个文件，盾就不再是纸糊的。")
    else:
        lines.append(f"{drills}/{len(rows)} 个目标演练过恢复。演练过的才算盾，没演练过的算愿望。")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines) + "\n", 0


def cmd_validate(targets: Dict[str, Target], events: List[Event]) -> Tuple[str, int]:
    lines = [f"两本账体检 · {len(targets)} 个目标 · {len(events)} 条事件", ""]
    scopes = sorted({t.scope for t in targets.values()})
    lines.append("  目标账：" + "、".join(
        f"{t.name}（{t.scope}/{t.medium}/{t.place}"
        f"{('/' + str(t.cadence) + 'd') if t.cadence else '/无周期'}）"
        for t in sorted(targets.values(), key=lambda t: t.name)))
    lines.append("")
    kinds: Dict[str, int] = {}
    for e in events:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    lines.append("  事件账：" + "、".join(f"{k} ×{kinds[k]}" for k in sorted(kinds)))
    lines.append("")
    lines.append("账本干净：日期合法且不在未来、事件类型合法、每个事件的目标都在目标账中、")
    lines.append("无重复目标、存放地合法。")
    return "\n".join(lines) + "\n", 0


def cmd_terms() -> Tuple[str, int]:
    lines = ["术语速查（建账参考）", ""]
    for term, text in [
        ("3-2-1", "3 份副本、2 种介质、1 份异地——冗余要在物理上成立，不在纸面上"),
        ("RPO", "Recovery Point Objective：灾难时最坏丢多少天的数据 = 今天 − 最新可信副本"),
        ("RTO", "Recovery Time Objective：多久能恢复可用——drill 的耗时记录是它的下界估计"),
        ("backup", "任务跑过了。绿勾只证明这一层——副本被写入了"),
        ("verify", "校验过：hash 比对或试读抽样。证明「这份副本还是活的」"),
        ("drill", "恢复演练：真还原过文件。证明「回得来」——没演练过的恢复是首演"),
        ("STALE", "距上次 backup 超过 1× 周期：人祸，该补一次了"),
        ("ROTTEN", "超过 2× 周期：静默断链——它已经不是你以为的那份副本"),
        ("异地", "offsite 或 cloud：火灾/盗窃/勒索软件够不着的地方；同屋的 NAS 不算"),
    ]:
        lines.append(f"  {pad(term, 8)} {text}")
    lines.append("")
    lines.append("勒索软件专门加密它能摸到的盘：直连的 NAS、挂载的网盘都可能一起走——")
    lines.append("异地副本的唯一标准是「灾难摸不到它」。")
    return "\n".join(lines) + "\n", 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description="paper-shield · 纸盾 —— 备份的可用性账本")
    p.add_argument("--version", action="version", version=f"{PROG} {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("targets", help="目标账 TSV：目标/内容域/介质/存放地/周期天")
        sp.add_argument("events", help="事件账 TSV：日期/目标/事件/备注")
        sp.add_argument("--today", default=None, help="钉死「今天」为 YYYY-MM-DD（默认真实当下）")

    common(sub.add_parser("audit", help="3-2-1 审计 + 三层信任分级"))
    common(sub.add_parser("fresh", help="逐目标新鲜度榜"))
    s = sub.add_parser("simulate", help="灾难推演：某介质全灭之后还剩什么")
    common(s)
    s.add_argument("scenario", help="固定填 dead")
    s.add_argument("medium", help="假设全灭的介质（如 disk）")
    common(sub.add_parser("drills", help="验证与演练史"))
    common(sub.add_parser("validate", help="两本账体检"))
    sub.add_parser("terms", help="3-2-1 与 RPO 术语速查")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "terms":
            text, code = cmd_terms()
            print(text, end="")
            return code
        today = dt.date.today() if not getattr(args, "today", None) \
            else dt.datetime.strptime(args.today, "%Y-%m-%d").date()
        targets = load_targets(args.targets)
        events = load_events(args.events, targets, today)
        if args.cmd == "audit":
            text, code = cmd_audit(targets, events, today)
        elif args.cmd == "fresh":
            text, code = cmd_fresh(targets, events, today)
        elif args.cmd == "simulate":
            if args.scenario != "dead":
                raise UsageError(f"未知推演场景「{args.scenario}」：目前只有 dead <介质>")
            text, code = cmd_simulate(targets, events, today, args.medium)
        elif args.cmd == "drills":
            text, code = cmd_drills(targets, events, today)
        elif args.cmd == "validate":
            text, code = cmd_validate(targets, events)
        else:  # pragma: no cover
            raise UsageError(f"未知子命令：{args.cmd}")
        print(text, end="")
        return code
    except UsageError as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 2
    except Refusal as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
