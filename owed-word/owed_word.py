#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""owed-word · 应承 —— 受托账:答应过别人的事,对一次账.

问题:答应发生在对话里,零成本、零记录。微信里回一句「包在我身上」,
这条消息三天后沉进聊天记录;表弟两个月后问「哥你上次说的师傅呢」,
你才发现自己从没动过。todo-rot 管「写给未来自己的支票」(代码 TODO),
iou 管欠钱——但「欠别人的话」没有任何账本:大脑把「我说了」直接误记
成「我在办了」,悬着的应承是关系里的暗债,它不产生利息,它产生尴尬。
最消耗关系的不是拒绝,是悬着的答应:对方不好意思催,你不好意思提,
两个人一起假装它不存在。

owed-word 把每一句应承记成一行(TSV:who/what/date/state/note),对同
一本账开四个命令:report 全量对账单(按人聚合——「你在谁那里悬着最多」,
见面前先看这一行)、next 该回话清单(按悬龄升序,行动文案只有两句:
办掉它,或回一句办不了)、settled 结案簿(办结率与拒绝占比——拒绝率
是这个账本的健康指标,不是污点)、validate 恒等式与双路径重放。

三条设计立场:
  * declined 是一等公民的结案:说出口的「不」是已结的账,比悬着的
    「好」干净一百倍。灯不判道德,只照悬着的;拒绝话术不是本件的事。
  * 有期限的应承只看期限(说过的「周三给你」是证词,due 当天恰线亮,
    宽容为零);没期限的才按悬龄计(第 15 天 AGING 预警,第 31 天
    STALE)。期限内外是正常等待,账本不吵没到期的债。
  * 阈值全是设计常数、无 -- 旗标——应承对账没有外部权威,给阈值
    开门就是给「把红灯调成绿灯」的冲动开门(与 cry-wolf 同款立场)。
    「改天聚聚」也一样会被悬龄点名——连「改天」都悬成了债。

零依赖:Python 3.8+ 标准库。无墙钟:缺省 as-of 锚定账本最大日期,
--as-of 钉死即逐字节可复现。

Exit codes:
  0  report produced   2  usage/账本缺失/坏行
  3  refusal: 空账     4  gate: OVERDUE/STALE/AGING 任一
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

PROG = "owed-word"
VERSION = "1.0.0"

HEADER = ["who", "what", "date", "state", "note"]

# state 词表:open = 悬着;did = 办了;declined = 明说办不了;
# returned = 对方收回。结案三态都不亮灯——已结的账不用照。
STATES = ["open", "did", "declined", "returned"]
STATE_ALIASES = {
    "open": "open", "悬着": "open", "未结": "open", "办着": "open",
    "did": "did", "办了": "did", "已办": "did", "办妥": "did",
    "declined": "declined", "办不了": "declined", "回绝": "declined",
    "婉拒": "declined", "没办成": "declined",
    "returned": "returned", "收回": "returned", "不用了": "returned",
    "撤销": "returned", "对方收回": "returned",
}

# 设计常数:应承对账没有外部权威,无常值旗标。
AGING_DAYS = 15   # 悬龄第 15 天起黄灯预警(恰线即亮)
STALE_DAYS = 30   # 悬龄第 31 天起红灯(30 天内仍属 AGING)

# note 内的键值:due = 答应时说过的期限;done = 结案日(可记可不记,
# 不记则办结周期如实披露「未记」)。
KV_RE = re.compile(r"(due|done):(\d{4}-\d{2}-\d{2})")

STATE_ZH = {"open": "悬着", "did": "办了", "declined": "办不了",
            "returned": "对方收回"}
LIGHT = {"OVERDUE": "🔴", "STALE": "🔴", "AGING": "🟡", "OK": "🟢",
         "DONE": "✅"}


# ---------------------------------------------------------------- 归一
def norm_state(s: str) -> str:
    n = unicodedata.normalize("NFKC", s).strip().lower()
    if n in STATE_ALIASES:
        return STATE_ALIASES[n]
    raise ValueError(
        f"未知状态「{s}」(词表:{'/'.join(STATES)},中文短名也收)")


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s: str, what: str = "日期") -> dt.date:
    if not DATE_RE.match(s):
        raise ValueError(f"坏{what}「{s}」——要 YYYY-MM-DD 补零格式,缺零拒绝")
    try:
        return dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        raise ValueError(f"坏{what}「{s}」——不是真实存在的日子(如 2026-02-30)")


def parse_note(note: str, lineno: int) -> Tuple[Optional[dt.date], Optional[dt.date]]:
    """note 里抠 due:/done: 键值;坏日期拒绝;未知 kv 当纯文本容忍."""
    due = done = None
    for m in KV_RE.finditer(note):
        key, raw = m.group(1), m.group(2)
        try:
            d = parse_date(raw, f"{key}日")
        except ValueError as e:
            raise ValueError(f"账本第 {lineno} 行:{e}")
        if key == "due":
            due = d
        else:
            done = d
    return due, done


# ---------------------------------------------------------------- 账本
class Entry:
    __slots__ = ("who", "what", "date", "state", "note", "due", "done", "line")

    def __init__(self, who, what, date, state, note, due, done, line):
        self.who, self.what, self.date, self.state = who, what, date, state
        self.note, self.due, self.done, self.line = note, due, done, line


def parse_tsv(path: str) -> List[Entry]:
    if not os.path.exists(path):
        raise SystemExitWith(2, f"{PROG}: 找不到账本 {path}")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    entries: List[Entry] = []
    seen_header = False
    seen_content = False
    for lineno, line in enumerate(raw.split("\n"), start=1):
        if line.endswith("\r"):
            line = line[:-1]
        if line.endswith("\t"):
            line = line.rstrip("\t")  # 行尾制表符容忍:表格粘贴的日常
        if not line.strip() or line.startswith("#"):
            continue
        seen_content = True
        cols = line.split("\t")
        if len(cols) > 5:
            raise SystemExitWith(2, f"账本第 {lineno} 行:列数 {len(cols)} > 5")
        cols += [""] * (5 - len(cols))
        if not seen_header:
            if [c.strip().lower() for c in cols[:2]] == ["who", "what"]:
                seen_header = True
                continue
            raise SystemExitWith(2, f"账本第 1 行须是表头 {'/'.join(HEADER)}(空行注释除外)")
        who = cols[0].strip()
        what = cols[1].strip()
        if not who:
            raise SystemExitWith(2, f"账本第 {lineno} 行:缺 who(你应承了谁)")
        if not what:
            raise SystemExitWith(2, f"账本第 {lineno} 行:缺 what(应承的事要写到能验收——「帮忙」没法结案)")
        if not cols[2].strip():
            raise SystemExitWith(2, f"账本第 {lineno} 行:缺答应日期")
        try:
            date = parse_date(cols[2].strip(), "答应日期")
        except ValueError as e:
            raise SystemExitWith(2, f"账本第 {lineno} 行:{e}")
        try:
            state = norm_state(cols[3]) if cols[3].strip() else "open"
        except ValueError as e:
            raise SystemExitWith(2, f"账本第 {lineno} 行:{e}")
        try:
            due, done = parse_note(cols[4], lineno)
        except ValueError as e:
            raise SystemExitWith(2, f"{e}")
        if state != "open" and done is None:
            # 结案日未记不拒——settled 里如实披露「未记」,不冒充
            pass
        if done is not None and done < date:
            raise SystemExitWith(
                2, f"账本第 {lineno} 行:结案日 {done} 早于答应日 {date}——时间倒转")
        if due is not None and due < date:
            raise SystemExitWith(
                2, f"账本第 {lineno} 行:期限 {due} 早于答应日 {date}——答应之前交不了卷")
        entries.append(Entry(who, what, date, state, cols[4].strip(),
                             due, done, lineno))
    if not seen_header:
        # 纯注释/空文件不算账坏——留给空账拒判(kin-ring 先例):
        # 对第一次打开的人,没有账本是「还没开始」,不是「账坏了」
        if not seen_content:
            raise SystemExitWith(3, "空账——一句应承都还没记(第一次打开,从今天那句开始)")
        raise SystemExitWith(2, "账本没有表头行")
    # 同 who+what+date 重复 = 手编重录
    seen: Dict[Tuple[str, str, str], int] = {}
    for e in entries:
        k = (e.who, e.what, e.date.isoformat())
        if k in seen:
            raise SystemExitWith(
                2, f"账本第 {e.line} 行:与第 {seen[k]} 行重复(同人对事同日)——同一句应承只记一次")
        seen[k] = e.line
    if not entries:
        raise SystemExitWith(3, "空账——一句应承都还没记(第一次打开,从今天那句开始)")
    return entries


class SystemExitWith(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg


# ---------------------------------------------------------------- 判灯
def judge(e: Entry, as_of: dt.date) -> str:
    """恰线语义:due 当天亮 OVERDUE(今天就是交卷日,宽容为零);
    悬龄第 15 天亮 AGING、第 31 天亮 STALE(30 天内仍属 AGING);
    有期限的行期限内不按悬龄吵——期限内是正常等待。"""
    if e.state != "open":
        return "DONE"
    if e.due is not None:
        return "OVERDUE" if as_of >= e.due else "OK"
    age = (as_of - e.date).days
    if age >= STALE_DAYS + 1:
        return "STALE"
    if age >= AGING_DAYS:
        return "AGING"
    return "OK"


def is_lit(state: str) -> bool:
    return state in ("OVERDUE", "STALE", "AGING")


def action_line(e: Entry, state: str, age: int = 0) -> str:
    if state == "OVERDUE":
        return (f"说过「{e.due.isoformat()} 前」——期限已到:办掉它,"
                f"或回一句办不了(说出口的「不」比悬着的「好」干净)")
    if state == "STALE":
        return (f"悬了 {age} 天没下文:要么这两天办掉,"
                f"要么回一句办不了——对方不好意思催,不等于对方忘了")
    return ""


def aging_action(days: int) -> str:
    return f"悬了 {days} 天,预警带内:排进本周,或现在就回一句进度"


# ---------------------------------------------------------------- 排版
def dw(s: str) -> int:
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return w


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dw(s))


def age_days(e: Entry, as_of: dt.date) -> int:
    return (as_of - e.date).days


# ---------------------------------------------------------------- 命令
def default_as_of(entries: List[Entry]) -> dt.date:
    return max(e.date for e in entries)


def collect(entries: List[Entry], as_of: dt.date):
    """返回 [(entry, state)] 全量;按人聚合的 open 计数."""
    judged = [(e, judge(e, as_of)) for e in entries]
    return judged


def load_judged(args):
    """载入 + as-of 剪切(答应日晚于 as-of 的行是后视行:当时还没答应,
    不能点亮过去的账;剪掉几笔如实披露)+ 逐行判灯."""
    entries = parse_tsv(args.ledger)
    as_of = parse_date(args.as_of, "as-of") if args.as_of else default_as_of(entries)
    clipped = [e for e in entries if e.date > as_of]
    live = [e for e in entries if e.date <= as_of]
    anchored = "" if args.as_of else "(未钉 as-of,缺省锚定账本最大答应日)"
    return entries, live, as_of, anchored, len(clipped)


def cmd_report(args) -> int:
    entries, live, as_of, anchored, clipped = load_judged(args)
    judged = collect(live, as_of)

    out = []
    out.append(f"应承 · Owed Word —— 受托对账单(as-of {as_of}){anchored}")
    if clipped:
        out.append(f"时间机器:剪掉 {clipped} 笔晚于 as-of 的后视行——当时还没答应,如实不隐去")
    out.append("")
    by_person: "OrderedDict[str, List[Tuple[Entry, str]]]" = OrderedDict()
    for e in live:
        by_person.setdefault(e.who, []).append((e, judge(e, as_of)))
    for who, rows in by_person.items():
        lit = sum(1 for _, s in rows if is_lit(s))
        out.append(f"{who}" + (f" —— 悬着 {lit} 件" if lit else ""))
        for e, st in rows:
            head = f"  {e.date.isoformat()} 答应「{e.what}」"
            if st == "OK":
                out.append(head)
                out.append(f"    🟢 未亮:悬龄 {age_days(e, as_of)} 天,正常等待中"
                           + (f"(期限 {e.due.isoformat()} 未到)" if e.due else ""))
            elif st == "DONE":
                out.append(head)
                tail = STATE_ZH[e.state]
                if e.done:
                    tail += f"({e.done.isoformat()} 结案,办结周期 {(e.done - e.date).days} 天)"
                else:
                    tail += "(结案日未记,周期不计)"
                out.append(f"    {LIGHT['DONE']} {tail}"
                           + ("——说出口的「不」是已结的账" if e.state == "declined" else ""))
            else:
                out.append(f"  {LIGHT[st]} {head}(L{e.line})")
                if st == "OVERDUE":
                    over = (as_of - e.due).days
                    when = "今天就是说过交卷的日子" if over == 0 else f"已过 {over} 天"
                    out.append(f"    期限 {e.due.isoformat()},{when}")
                elif st == "AGING":
                    out.append(f"    悬龄 {age_days(e, as_of)} 天")
                else:
                    out.append(f"    悬龄 {age_days(e, as_of)} 天,没有任何下文")
                if st == "AGING":
                    out.append(f"    ↳ {aging_action(age_days(e, as_of))}")
                else:
                    out.append(f"    ↳ {action_line(e, st, age_days(e, as_of))}")
        out.append("")
    lit_rows = [(e, s) for e, s in judged if is_lit(s)]
    n_over = sum(1 for _, s in lit_rows if s == "OVERDUE")
    n_stale = sum(1 for _, s in lit_rows if s == "STALE")
    n_aging = sum(1 for _, s in lit_rows if s == "AGING")
    n_open_ok = sum(1 for _, s in judged if s == "OK")
    n_settled = sum(1 for e in entries if e.state != "open")
    out.append(f"—— {len(live)} 句应承 · 悬着 {len(live) - n_settled}"
               f"(🔴{n_over + n_stale} 🟡{n_aging}) · 已结 {n_settled} · 未亮 {n_open_ok}")
    ranking = sorted(
        ((who, sum(1 for _, s in rows if is_lit(s))) for who, rows in by_person.items()),
        key=lambda x: (-x[1], x[0]))
    ranked = [(w, n) for w, n in ranking if n > 0]
    if ranked:
        out.append("  人排行(你在谁那里悬着最多——见面前先看这一行):"
                   + " · ".join(f"{w} {n} 件" for w, n in ranked))
    if lit_rows:
        out.append("账面带灯:有应承悬着没对过(exit 4)——next 看该回话清单")
    print("\n".join(out))
    return 4 if lit_rows else 0


def cmd_next(args) -> int:
    entries, live, as_of, anchored, clipped = load_judged(args)
    judged = collect(live, as_of)
    lit = [(e, s) for e, s in judged if is_lit(s)]

    out = []
    if not lit:
        print(f"应承 · 无灯(as-of {as_of}){anchored}——"
              f"{len(entries)} 句应承没有要回话的,今天不用还嘴上的债")
        return 0
    out.append(f"应承 · 该回话清单(as-of {as_of}){anchored}——期限债在前,悬龄债按悬龄降序")
    out.append("")

    def sort_key(pair):
        e, s = pair
        if s == "OVERDUE":
            return (0, 0, -(as_of - e.due).days, e.line)
        if s == "STALE":
            return (1, -(as_of - e.date).days, 0, e.line)
        return (2, -(as_of - e.date).days, 0, e.line)

    for e, s in sorted(lit, key=sort_key):
        label = {"OVERDUE": "期限债", "STALE": "悬账", "AGING": "预警"}[s]
        out.append(f"{LIGHT[s]} {e.who}·「{e.what}」({label},L{e.line})")
        if s == "OVERDUE":
            over = (as_of - e.due).days
            out.append(f"  ↳ {action_line(e, s)}" if over else
                       f"  ↳ 今天就是说过交卷的日子——今晚之前,办掉或回话")
        elif s == "AGING":
            out.append(f"  ↳ {aging_action(age_days(e, as_of))}")
        else:
            out.append(f"  ↳ {action_line(e, s, age_days(e, as_of))}")
    n_red = sum(1 for _, s in lit if s in ("OVERDUE", "STALE"))
    out.append(f"—— {len(lit)} 句要回话(🔴{n_red} 🟡{len(lit) - n_red})")
    print("\n".join(out))
    return 4


def cmd_settled(args) -> int:
    entries, live, as_of, anchored, clipped = load_judged(args)
    done_rows = [e for e in live if e.state != "open"]

    out = []
    out.append(f"应承 · 结案簿(as-of {as_of}){anchored}")
    out.append("")
    if not done_rows:
        print("\n".join(out) + "还没有结案——账本里全是悬着的答应")
        return 4 if any(is_lit(judge(e, as_of)) for e in entries) else 0
    for e in done_rows:
        tail = STATE_ZH[e.state]
        if e.done:
            tail += f",{e.done.isoformat()} 结案,周期 {(e.done - e.date).days} 天"
        else:
            tail += ",结案日未记(周期不计)"
        out.append(f"  ✅ {e.who}·「{e.what}」—— {tail}")
    n_did = sum(1 for e in done_rows if e.state == "did")
    n_dec = sum(1 for e in done_rows if e.state == "declined")
    n_ret = sum(1 for e in done_rows if e.state == "returned")
    n_cycle = [e for e in done_rows if e.done]
    cycles = [(e.done - e.date).days for e in n_cycle]
    out.append("")
    out.append(f"—— 已结 {len(done_rows)}:办了 {n_did} / 办不了 {n_dec} / 对方收回 {n_ret}"
               + (f" · 拒绝占比 {n_dec / len(done_rows):.1%}" if done_rows else ""))
    if cycles:
        out.append(f"  办结周期(有记结案日的 {len(cycles)} 笔):"
                   f"最短 {min(cycles)} 天,最长 {max(cycles)} 天,平均 {sum(cycles) / len(cycles):.1f} 天")
    out.append("拒绝占比是这本账的健康指标,不是污点——它量的是你敢说「不」的频率")
    lit = any(is_lit(judge(e, as_of)) for e in entries)
    if lit:
        out.append("账面仍有悬灯(exit 4)——settled 只看结案,催悬账请用 report/next")
    print("\n".join(out))
    return 4 if lit else 0


# ---------------------------------------------------------------- validate
def replay_from_text(path: str) -> List[Tuple[str, str, str, str]]:
    """路径B:从原始文本独立重放(who/what/date/state 四元组序列)."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    rows = []
    for lineno, line in enumerate(raw.split("\n"), start=1):
        if line.endswith("\r"):
            line = line[:-1]
        if line.rstrip("\t") == "" or line.startswith("#"):
            continue
        cols = line.rstrip("\t").split("\t")
        if len(cols) > 5:
            continue
        if [c.strip().lower() for c in cols[:2]] == ["who", "what"]:
            continue
        if len(cols) < 5:
            cols += [""] * (5 - len(cols))
        who, what, date, state = cols[0].strip(), cols[1].strip(), cols[2].strip(), cols[3].strip()
        if not who or not what or not DATE_RE.match(date):
            continue
        try:
            st = norm_state(state) if state else "open"
            parse_date(date)
        except ValueError:
            continue
        rows.append((who, what, date, st))
    return rows


def cmd_validate(args) -> int:
    entries = parse_tsv(args.ledger)
    problems: List[str] = []

    # 恒等式一:总行数 ≡ 四态计数之和(state 空间守恒)
    by_state = {s: 0 for s in STATES}
    for e in entries:
        by_state[e.state] += 1
    a_total = len(entries)
    b_total = sum(by_state.values())
    if a_total != b_total:
        problems.append(f"恒等式破坏:总行 {a_total} ≠ 四态计数和 {b_total}")

    # 恒等式二:双路径重放——解析层与文本层的四元组序列逐行全等
    path_b = replay_from_text(args.ledger)
    path_a = [(e.who, e.what, e.date.isoformat(), e.state) for e in entries]
    if path_a != path_b:
        for i, (x, y) in enumerate(zip(path_a, path_b)):
            if x != y:
                problems.append(f"重放第 {i + 1} 行漂移:解析层 {x} vs 文本层 {y}")
                break
        if len(path_a) != len(path_b):
            problems.append(f"重放行数不等:解析层 {len(path_a)} vs 文本层 {len(path_b)}")

    # 结案行(done:)只属于结案态的核查:open 行带 done: 视为账坏
    for e in entries:
        if e.state == "open" and e.done is not None:
            problems.append(f"第 {e.line} 行:open 状态却记了 done: 结案日——悬着的账不能预写结局")

    if problems:
        for p in problems:
            print(f"✗ {p}")
        print("validate:账本有问题(exit 2)")
        return 2
    print("validate:✓ 恒等式全绿")
    print(f"  总行 ≡ open {by_state['open']} + did {by_state['did']}"
          f" + declined {by_state['declined']} + returned {by_state['returned']}"
          f" = {b_total}(双路径重放逐行全等)")
    print(f"  悬着 {by_state['open']} 句,已结 {a_total - by_state['open']} 句,"
          f"行号可 grep 回账本")
    return 0


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=PROG, description="应承 · Owed Word —— 受托账:答应过别人的事,对一次账")
    ap.add_argument("--version", action="version", version=f"{PROG} {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("ledger", help="账本 TSV 路径")
        p.add_argument("--as-of", dest="as_of", default=None,
                       help="钉死对账基准日 YYYY-MM-DD(缺省锚定账本最大答应日,零墙钟)")

    add_common(sub.add_parser("report", help="全量对账单:按人聚合,悬着的先亮"))
    add_common(sub.add_parser("next", help="该回话清单:期限债在前,悬账按悬龄降序"))
    add_common(sub.add_parser("settled", help="结案簿:办结率、拒绝占比、办结周期"))
    p_v = sub.add_parser("validate", help="账本体检:恒等式 + 双路径重放")
    p_v.add_argument("ledger")
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        if args.cmd == "report":
            return cmd_report(args)
        if args.cmd == "next":
            return cmd_next(args)
        if args.cmd == "settled":
            return cmd_settled(args)
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
