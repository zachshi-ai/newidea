#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scapegoat · 替罪羊 —— 反复发作的触发器归因法庭.

问题：偏头痛、肠易激、荨麻疹、湿疹这类反复发作的老毛病，网络上人人都有
一份二十条起步的「忌口清单」。每次发作，直觉都会当场指认昨晚离得最近的
那样东西——「肯定是那杯红酒」，于是它进黑名单；三个月过去，发作照旧，
但没人宣布它无罪，因为你不吃它的日子你也在发作，而凭感觉归因的人从不看
基线。结果：清单越拉越长，生活越来越窄，真凶（往往是没有戏剧性的缺睡、
空腹、激素）在名单外面逍遥法外。单次巧合定罪 + 永不 + 平反，是触发器
归因里最流行的两种冤案。

scapegoat 把发作与暴露抄成一本可手编的日更账本（TSV：日期/是否发作/
当日暴露），用你自己的记录对每个嫌疑人开庭：

  * verdicts   全员审判台：判决阶梯、lift、归因发作，有定罪 → exit 4
  * judge      单人卷宗：2×2 表、恒等式、Fisher 单侧 p、Bonferroni 门槛
  * acquitted  平反名单：证据不支持定罪、可以解禁的嫌疑人
  * case       案发夜复盘：当晚谁在场、各自的清白/前科记录
  * simulate   反事实推演：完全避开某人，按账本至多少发几次
  * combo      组合作案排查：搭伙作案的线索（永不触发门禁）
  * validate   账本体检：覆盖率、无记录日、缺席条款

判决阶梯：✗ CONVICTED（定罪：lift ≥ 2 且 p < 0.05/k）> ▲ TENTATIVE
（嫌疑重大：过单人线、未过 Bonferroni）> ○ WATCHLIST（监视名单）>
◌ SUSPECT（在逃：任一臂不足 3 天，拒判）> ✓ ACQUITTED（平反：暴露
≥ 6 天且 lift ≤ 1.15）。「十个小嫌疑里总有一个像凶手」由 Bonferroni
挡住；「没受过考验的清白不算清白」由 6 天暴露门槛挡住。

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
「今天」默认真实当下，`--today` 钉死即逐字节可复现。

用法：
  python3 scapegoat.py verdicts diary.tsv --today 2026-08-24
  python3 scapegoat.py judge diary.tsv --trigger 缺睡
  python3 scapegoat.py acquitted diary.tsv
  python3 scapegoat.py case diary.tsv --date 2026-05-07
  python3 scapegoat.py simulate diary.tsv --avoid 缺睡 --months 3
  python3 scapegoat.py combo diary.tsv
  python3 scapegoat.py validate diary.tsv

Exit codes:
  0  report produced（含平反/绿灯）
  2  usage error / 账本缺失 / 坏行 / 未来日期 / 重复记账
  3  refusal: 全员在逃无法开庭 / 无案可审 / 指定嫌疑人或日期不在账本 /
     推演对象证据不足
  4  gate: 存在 CONVICTED 定罪
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import re
import sys
import unicodedata
from collections import Counter, namedtuple
from typing import Dict, List, Optional

PROG = "scapegoat"
VERSION = "1.0.0"

THIN_MIN = 3        # 任一臂（暴露/对照）不足 3 天 → 在逃，拒判
ACQ_MIN = 6         # 平反需要 ≥ 6 天暴露：没受过考验的清白不算清白
LIFT_CONVICT = 2.0  # 定罪的 lift 线
LIFT_ACQUIT = 1.15  # lift ≤ 1.15 → 证据不支持定罪
ALPHA = 0.05        # 家族错误率；Bonferroni 平分给 k 名受审者
COMBO_MIN = 5       # 组合作案排查需要的共暴露天数

CONVICTED = "CONVICTED"
TENTATIVE = "TENTATIVE"
WATCHLIST = "WATCHLIST"
SUSPECT = "SUSPECT"
ACQUITTED = "ACQUITTED"

VERDICT_LABEL = {
    CONVICTED: "✗ 定罪",
    TENTATIVE: "▲ 嫌疑重大",
    WATCHLIST: "○ 监视名单",
    SUSPECT: "◌ 在逃",
    ACQUITTED: "✓ 平反",
}
VERDICT_RANK = {CONVICTED: 0, TENTATIVE: 1, WATCHLIST: 2, SUSPECT: 3, ACQUITTED: 4}

Entry = namedtuple("Entry", "date attack triggers note line")


class LedgerError(Exception):
    """账本打不开或行级坏账，一律 exit 2。"""


def normalize(name: str) -> str:
    """嫌疑人名规范化：去首尾空白、小写、内部空白折叠。"""
    return re.sub(r"\s+", " ", name.strip().lower())


def parse_ledger(path: str, today: dt.date) -> List[Entry]:
    """解析日更账本：date / attack(0|1) / triggers(逗号分隔或 -) / note(可选)。"""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise LedgerError(f"账本打不开：{path}（{exc}）")
    entries: List[Entry] = []
    seen: Dict[str, int] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) >= 3 and cols[0].strip().lower() == "date":
            continue  # 表头
        if len(cols) not in (3, 4):
            raise LedgerError(
                f"第 {lineno} 行：需要 3-4 列（date/attack/triggers[/note]），"
                f"实得 {len(cols)} 列")
        date_s, attack_s, trig_s = (c.strip() for c in cols[:3])
        note = cols[3].strip() if len(cols) == 4 else ""
        try:
            day = dt.date.fromisoformat(date_s)
        except ValueError:
            raise LedgerError(f"第 {lineno} 行：日期不是 YYYY-MM-DD：{date_s!r}")
        if day > today:
            raise LedgerError(
                f"第 {lineno} 行：日期 {date_s} 在 --today {today} 之后——"
                f"日记不能预写")
        if attack_s not in ("0", "1"):
            raise LedgerError(
                f"第 {lineno} 行：attack 只允许 0/1，实得 {attack_s!r}")
        if date_s in seen:
            raise LedgerError(
                f"第 {lineno} 行：{date_s} 重复记账（首次在第 {seen[date_s]} 行）")
        seen[date_s] = lineno
        if trig_s in ("", "-"):
            triggers: List[str] = []
        else:
            triggers = []
            for tok in re.split(r"[,，、/]", trig_s):
                name = normalize(tok)
                if name and name not in triggers:
                    triggers.append(name)
        entries.append(Entry(day, attack_s == "1", tuple(triggers), note, lineno))
    return entries


def fisher_right(a_e: int, n_e: int, a_u: int, n_u: int) -> float:
    """Fisher 精确检验（单侧）：固定边际下 P(暴露臂发作 ≥ a_e)。

    超几何 N=n_e+n_u，K=a_e+a_u，抽 n_e 天。全整数组合数，无近似。
    """
    total_attacks = a_e + a_u
    days = n_e + n_u
    if a_e <= 0 or total_attacks == 0:
        return 1.0
    lo = max(0, n_e - (days - total_attacks))
    hi = min(n_e, total_attacks)
    denom = math.comb(days, n_e)
    acc = 0
    for x in range(max(lo, a_e), hi + 1):
        acc += math.comb(total_attacks, x) * math.comb(days - total_attacks, n_e - x)
    return acc / denom


def fmt_p(p: float) -> str:
    return f"{p:.2e}" if p < 0.001 else f"{p:.4f}"


def dw(s: str) -> int:
    """终端显示宽度：中日韩全角按 2 计。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s: str, w: int) -> str:
    return s + " " * max(0, w - dw(s))


def padl(s: str, w: int) -> str:
    return " " * max(0, w - dw(s)) + s


class Suspect:
    """一名嫌疑人的全部卷宗数据。"""

    def __init__(self, name: str):
        self.name = name
        self.e = 0            # 暴露天数
        self.a_e = 0          # 暴露日中的发作天数
        self.clean_presence = 0  # 在场又没作案的次数（E − a_e，平反的原料）
        self.u = 0            # 对照天数（记录在案但未暴露）
        self.a_u = 0          # 对照日中的发作天数

    @property
    def rate_e(self) -> float:
        return self.a_e / self.e if self.e else 0.0

    @property
    def rate_u(self) -> float:
        return self.a_u / self.u if self.u else 0.0

    @property
    def lift(self) -> Optional[float]:
        """暴露臂发作率 ÷ 对照臂发作率；双零（账本期内无发作）→ None。"""
        if self.rate_u == 0.0 and self.rate_e == 0.0:
            return None
        if self.rate_u == 0.0:
            return math.inf
        return self.rate_e / self.rate_u

    @property
    def attributable(self) -> float:
        """归因发作 = a_e − E×rate_u：不暴露它时这些天本可以不发作。"""
        if self.u == 0:
            return float(self.a_e)
        return self.a_e - self.e * self.rate_u


def build_suspects(entries: List[Entry]) -> Dict[str, Suspect]:
    suspects: Dict[str, Suspect] = {}
    recorded = len(entries)
    for entry in entries:
        for name in entry.triggers:
            if name not in suspects:
                suspects[name] = Suspect(name)
            suspects[name].e += 1
            if entry.attack:
                suspects[name].a_e += 1
            else:
                suspects[name].clean_presence += 1
    for suspect in suspects.values():
        suspect.u = recorded - suspect.e
        suspect.a_u = sum(e.attack for e in entries if suspect.name not in e.triggers)
    return suspects


def decide(suspect: Suspect, k: int):
    """判决阶梯。k = 受审人数（Bonferroni 的分母）。"""
    if suspect.e < THIN_MIN or suspect.u < THIN_MIN:
        return SUSPECT, (
            f"暴露 {suspect.e} 天 / 对照 {suspect.u} 天——任一臂满 {THIN_MIN} 天才开审；"
            f"现在的样本连巧合都算不上")
    if suspect.e >= ACQ_MIN and suspect.lift is not None and suspect.lift <= LIFT_ACQUIT:
        note = "证据不支持定罪"
        if suspect.lift < 0.85:
            note += "——它甚至带保护色，先别当成保护因素"
        return ACQUITTED, note
    if suspect.lift is not None and suspect.lift >= LIFT_CONVICT:
        gate = ALPHA / k
        if suspect.p < ALPHA / max(k, 1):
            return CONVICTED, (
                f"lift {suspect.lift:.2f} 达定罪线，p={fmt_p(suspect.p)} < "
                f"Bonferroni 门槛 {ALPHA:.2f}/{k}={gate:.4f}")
        if suspect.p < ALPHA:
            return TENTATIVE, (
                f"lift {suspect.lift:.2f} 达定罪线，p={fmt_p(suspect.p)} 过单人线 "
                f"{ALPHA:.2f}、未过 Bonferroni {gate:.4f}——十名嫌疑里总有一个像凶手")
        return WATCHLIST, (
            f"lift {suspect.lift:.2f} 达定罪线但 p={fmt_p(suspect.p)} 不显著——"
            f"更像巧合，进监视名单")
    if suspect.lift is not None and suspect.lift < 0.85:
        return WATCHLIST, (
            f"lift {suspect.lift:.2f} 偏无辜，但暴露不足 {ACQ_MIN} 天，"
            f"不够格平反——清白也需要证据")
    thin_note = "，样本也薄" if suspect.e < ACQ_MIN else ""
    lift_txt = f"{suspect.lift:.2f}" if suspect.lift is not None else "—"
    return WATCHLIST, f"lift {lift_txt} 未达定罪线 {LIFT_CONVICT:.1f}{thin_note}"


def prepare(entries: List[Entry]):
    """公共前置：嫌疑人、受审人数 k、逐人判决。"""
    suspects = build_suspects(entries)
    k = sum(
        1 for s in suspects.values()
        if s.e >= THIN_MIN and s.u >= THIN_MIN)
    for suspect in suspects.values():
        suspect.p = fisher_right(suspect.a_e, suspect.e, suspect.a_u, suspect.u)
        suspect.verdict, suspect.verdict_note = decide(suspect, k)
    return suspects, k


def sorted_suspects(suspects: Dict[str, Suspect]) -> List[Suspect]:
    return sorted(
        suspects.values(),
        key=lambda s: (VERDICT_RANK[s.verdict], -s.attributable, s.name))


def fmt_lift(suspect: Suspect) -> str:
    lift = suspect.lift
    if lift is None:
        return "—"
    if math.isinf(lift):
        return "∞"
    return f"{lift:.2f}"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


# ---------------------------------------------------------------- commands


def cmd_verdicts(args) -> int:
    today = _today(args)
    entries = parse_ledger(args.ledger, today)
    if not entries:
        print("账本是空的——先记几天，再来开庭。", file=sys.stderr)
        return 3
    recorded = len(entries)
    attacks = sum(e.attack for e in entries)
    first, last = entries[0].date, entries[-1].date
    if attacks == 0:
        print(
            f"记录 {recorded} 天，零发作——没有案子可审。", file=sys.stderr)
        print("发作没来，审判无从谈起；账本先攒着。", file=sys.stderr)
        return 3
    suspects, k = prepare(entries)
    empty_attacks = sum(1 for e in entries if e.attack and not e.triggers)
    rows = sorted_suspects(suspects)
    span = (last - first).days + 1
    print(
        f"替罪羊审判台 · 记录 {recorded} 天（{first} → {last}） · "
        f"发作 {attacks} 次 · 基线发作率 {pct(attacks / recorded)} · "
        f"嫌疑人 {len(rows)} 名（受审 {k} 名）")
    print()
    print(f"  {pad('判决', 14)}{pad('嫌疑人', 14)}{padl('暴露', 4)}"
          f"  {pad('在场/对照发作', 18)}{padl('lift', 5)}{padl('归因', 6)}  备注")
    for s in rows:
        rate_txt = (f"{s.a_e}/{s.e} vs {s.a_u}/{s.u}")
        print(f"  {pad(VERDICT_LABEL[s.verdict], 14)}{pad(s.name, 14)}"
              f"{padl(str(s.e), 4)}  {pad(rate_txt, 18)}{padl(fmt_lift(s), 5)}"
              f"{padl(f'{s.attributable:+.1f}', 6)}  {s.verdict_note}")
    print()
    share = empty_attacks / attacks
    print(
        f"无暴露发作 {empty_attacks}/{attacks}（{pct(share)}）——"
        f"名单之外的凶手在内（激素/天气/睡眠结构）：别把每次发作都赖给名单上的嫌疑人")
    convicted = [s for s in rows if s.verdict == CONVICTED]
    tentative = [s for s in rows if s.verdict == TENTATIVE]
    if convicted:
        names = "、".join(s.name for s in convicted)
        print(
            f"判定 RED —— {len(convicted)} 名定罪：{names}。"
            f"定罪必须有 Bonferroni 级证据，账本不因 lift 大就定人罪；"
            f"judge 看卷宗，simulate 试避开。")
        return 4
    if k == 0:
        print(
            "判定 REFUSE —— 没有任何嫌疑人攒够 3 天暴露与 3 天对照："
            "账本拒绝在空气里开庭。先照常生活，把暴露与发作都记下来。")
        return 3
    extra = f"，{len(tentative)} 名嫌疑重大待补证据" if tentative else ""
    print(f"判定 GREEN —— 无定罪{extra}。")
    return 0


def _find(entries: List[Entry], name: str) -> Optional[Suspect]:
    suspects, _ = prepare(entries)
    return suspects.get(normalize(name))


def cmd_judge(args) -> int:
    today = _today(args)
    entries = parse_ledger(args.ledger, today)
    recorded = len(entries)
    attacks = sum(e.attack for e in entries)
    if attacks == 0:
        print("账本期内零发作——没有案子可审，卷宗无从写起。", file=sys.stderr)
        return 3
    suspects, k = prepare(entries)
    key = normalize(args.trigger)
    if key not in suspects:
        print(
            f"账本里没有「{args.trigger}」的作案记录——它从未到庭，"
            f"没人能审判没到过案发现场的人。", file=sys.stderr)
        return 3
    s = suspects[key]
    print(f"卷宗 · {s.name}")
    print(
        f"案底：暴露 {s.e} 天 · 在场发作 {s.a_e} 次（{pct(s.rate_e)}）  ｜  "
        f"对照：{s.u} 天 · 发作 {s.a_u} 次（{pct(s.rate_u)}）")
    print(
        f"恒等式：{s.a_e} + {s.a_u} = {attacks} 次发作，账目吻合"
        f"（每个嫌疑人的两臂瓜分全部发作，一天不多一天不少）")
    lift_txt = fmt_lift(s)
    print(
        f"lift {lift_txt}（暴露 ÷ 对照发作率）  ｜  Fisher 单侧 p={fmt_p(s.p)}  ｜  "
        f"Bonferroni 门槛 {ALPHA:.2f}/{k}={ALPHA / k:.4f}（{k} 名受审）")
    print(f"判决 {VERDICT_LABEL[s.verdict]} —— {s.verdict_note}")
    if s.attributable > 0:
        print(
            f"归因发作 {s.attributable:.1f} 次：账本期内不暴露它，"
            f"理论上这些天本可以不发作（相关上限，不是因果承诺）。")
    elif s.verdict == ACQUITTED:
        print(
            f"在场未作案 {s.clean_presence} 次。冤案的成本是真实的——"
            f"这些日子你戒得毫无收益；是否解禁由你决定，账本只还清白。")
    else:
        print(f"归因发作 {s.attributable:+.1f} 次（负数是账面假象，别当成保护因素用）。")
    return 0


def cmd_acquitted(args) -> int:
    today = _today(args)
    entries = parse_ledger(args.ledger, today)
    attacks = sum(e.attack for e in entries)
    if attacks == 0:
        print("账本期内零发作——没有案子，也就没有冤案可平。", file=sys.stderr)
        return 3
    suspects, _ = prepare(entries)
    freed = sorted(
        (s for s in suspects.values() if s.verdict == ACQUITTED),
        key=lambda s: s.lift if s.lift is not None else 9)
    if not freed:
        print("没有可平反的嫌疑人——要么都定罪了，要么证据还不够开释。")
        return 0
    print(f"平反名单 · {len(freed)} 人")
    for s in freed:
        print(
            f"  {pad(s.name, 14)}暴露 {s.e} 天 · lift {fmt_lift(s)} · "
            f"在场未作案 {s.clean_presence} 次")
    print(
        "冤案的成本是真实的：这些日子你白戒了。是否解禁由你决定——"
        "账本只还清白，不发许可证。")
    return 0


def cmd_case(args) -> int:
    today = _today(args)
    entries = parse_ledger(args.ledger, today)
    attacks = sum(e.attack for e in entries)
    if attacks == 0:
        print("账本期内零发作——没有案发夜可复盘。", file=sys.stderr)
        return 3
    suspects, _ = prepare(entries)
    try:
        day = dt.date.fromisoformat(args.date)
    except ValueError:
        print(f"日期不是 YYYY-MM-DD：{args.date!r}", file=sys.stderr)
        return 2
    entry = next((e for e in entries if e.date == day), None)
    if entry is None:
        print(
            f"{args.date} 没有记录——无记录日不进分母，也没有案卷。"
            f"缺席的日子连不在场证明都算不上。", file=sys.stderr)
        return 3
    print(f"案发夜 · {entry.date}")
    if entry.attack:
        print("发作：是" + (f"（{entry.note}）" if entry.note else ""))
        if not entry.triggers:
            print(
                "当夜没有任何记录在案的暴露——这是无暴露发作，"
                "凶手在名单之外（激素/睡眠结构/天气），别硬指认。")
            return 0
        print(f"当日暴露：{'、'.join(entry.triggers)}")
        for name in entry.triggers:
            s = suspects[name]
            print(
                f"  {pad(name, 14)}在场发作率 {pct(s.rate_e)}（{s.a_e}/{s.e}）"
                f" vs 对照 {pct(s.rate_u)}  lift {fmt_lift(s)}  "
                f"{VERDICT_LABEL[s.verdict]}")
        guilty = [suspects[n] for n in entry.triggers
                  if suspects[n].verdict == CONVICTED]
        if guilty:
            print(f"本案可以结了：{'、'.join(s.name for s in guilty)}。")
        elif len(entry.triggers) == 1:
            s = suspects[entry.triggers[0]]
            print(
                f"{s.name} 又一次在场又没作案——"
                f"这已是它第 {s.clean_presence} 次清白在场，平反的原料在攒。")
        return 0
    print("发作：无。")
    if entry.triggers:
        print(
            f"当日暴露：{'、'.join(entry.triggers)}——这些暴露进入各自的"
            f"未发作分母，清白是这么一次一次攒出来的。")
    else:
        print("无发作、无暴露——这样的日子是基线的一部分，同样在账。")
    return 0


def cmd_simulate(args) -> int:
    today = _today(args)
    entries = parse_ledger(args.ledger, today)
    recorded = len(entries)
    attacks = sum(e.attack for e in entries)
    if attacks == 0:
        print("账本期内零发作——反事实无从折算。", file=sys.stderr)
        return 3
    suspects, _ = prepare(entries)
    key = normalize(args.avoid)
    if key not in suspects:
        print(
            f"账本里没有「{args.avoid}」的作案记录——避开一个从没到庭的"
            f"嫌疑人，手术对象不存在。", file=sys.stderr)
        return 3
    s = suspects[key]
    if s.verdict == SUSPECT:
        print(
            f"「{s.name}」的证据是 {s.e} 天暴露级别的——THIN 拒绝在空气里做手术。",
            file=sys.stderr)
        return 3
    if s.verdict == WATCHLIST:
        print(
            f"「{s.name}」还在监视名单——先攒暴露，监视名单不够开庭推演。",
            file=sys.stderr)
        return 3
    if s.verdict == ACQUITTED:
        print(
            f"「{s.name}」已平反——避开无辜者不会省下发作，"
            f"只会省下生活。", file=sys.stderr)
        return 3
    months = args.months
    saved = max(0.0, s.attributable / recorded * 30 * months)
    baseline_90 = attacks / recorded * 30 * months
    remaining = max(0.0, baseline_90 - saved)
    print(f"反事实推演 · 完全避开「{s.name}」 · 按 {months:g} 个月折算")
    print(
        f"账本期内归因发作 {s.attributable:.1f} 次 / {recorded} 个记录日 → "
        f"每 30 天 {s.attributable / recorded * 30:.1f} 次")
    print(
        f"当前基线 {pct(attacks / recorded)} → {months:g} 个月约 {baseline_90:.1f} 次；"
        f"避开后约 {remaining:.1f} 次 —— 账面至多少发 {saved:.1f} 次")
    print(
        "诚实条款：这是相关性的上限，不是因果的承诺——lift 里混着倒果为因"
        "（发作前兆让人翻旧账找原因）与混杂（缺睡的人也更爱喝酒）。"
        "避开与否，是你的决定。")
    return 0


def cmd_combo(args) -> int:
    today = _today(args)
    entries = parse_ledger(args.ledger, today)
    attacks = sum(e.attack for e in entries)
    if attacks == 0:
        print("账本期内零发作——没有案子，组合无从排查。", file=sys.stderr)
        return 3
    suspects, _ = prepare(entries)
    names = sorted(suspects)
    if len(names) < 2:
        print("嫌疑人不足 2 名——组合作案无从谈起。", file=sys.stderr)
        return 3
    co_days = {n: set() for n in names}
    for e in entries:
        for n in e.triggers:
            co_days[n].add(e.date)
    pairs = []
    thin_pairs = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            common = co_days[a] & co_days[b]
            if len(common) < COMBO_MIN:
                thin_pairs += 1
                continue
            a_d = sum(1 for e in entries
                      if e.date in common and e.attack)
            rest_days = len(entries) - len(common)
            a_r = attacks - a_d
            rate_d = a_d / len(common)
            rate_r = a_r / rest_days if rest_days else 0.0
            if rate_d == 0.0 and rate_r == 0.0:
                lift_txt = "—"
            elif rate_r == 0.0:
                lift_txt = "∞"
            else:
                lift_txt = f"{rate_d / rate_r:.2f}"
            pairs.append((rate_d / rate_r if rate_r else math.inf,
                          a, b, len(common), a_d, rate_d, rate_r, lift_txt))
    print(
        f"组合作案排查 · {len(names)} 名嫌疑人共 "
        f"{len(names) * (len(names) - 1) // 2} 对")
    if not pairs:
        print(
            f"没有一对共暴露满 {COMBO_MIN} 天——组合作案目前不可审，"
            f"先攒记录。真凶大概率单独作案，回到单人卷宗。")
        return 0
    pairs.sort(reverse=True)
    print(
        f"共暴露 ≥ {COMBO_MIN} 天的 {len(pairs)} 对开审，"
        f"其余 {thin_pairs} 对样本不足不判")
    for _, a, b, n, a_d, rate_d, rate_r, lift_txt in pairs:
        print(
            f"  {pad(f'{a} × {b}', 26)}共暴露 {n} 天 · 发作 {a_d} 次"
            f"（{pct(rate_d)}） vs 其余 {pct(rate_r)}  lift {lift_txt}  "
            f"线索（永不据此定罪）")
    print("组合线索永不触发门禁——搭伙作案的定罪，需要各自的证据。")
    return 0


def cmd_validate(args) -> int:
    today = _today(args)
    entries = parse_ledger(args.ledger, today)
    if not entries:
        print("账本是空的。", file=sys.stderr)
        return 3
    recorded = len(entries)
    first, last = entries[0].date, entries[-1].date
    span = (last - first).days + 1
    attacks = sum(e.attack for e in entries)
    empty_attacks = sum(1 for e in entries if e.attack and not e.triggers)
    slots = sum(len(e.triggers) for e in entries)
    suspects, k = prepare(entries)
    print(
        f"账本体检 · {recorded} 个记录日（{first} → {last}，跨度 {span} 天，"
        f"覆盖率 {pct(recorded / span)}）")
    print(
        f"发作 {attacks} 次（{pct(attacks / recorded) if recorded else '—'}），"
        f"其中无暴露发作 {empty_attacks} 次；嫌疑人 {len(suspects)} 名，"
        f"受审 {k} 名，暴露记录 {slots} 条")
    if suspects:
        top = sorted(suspects.values(), key=lambda s: (-s.e, s.name))[:5]
        print("  暴露最多：" + " · ".join(f"{s.name} {s.e} 天" for s in top))
    absent = span - recorded
    if absent > 0:
        print(
            f"缺席 {absent} 天——无记录日不进任何分母：账本只记你声称的事实，"
            f"缺席的周末不构成证据，也不构成不在场证明。")
    else:
        print("全程无缺席——每天都是证据（或不在场证明）。")
    return 0


def _today(args) -> dt.date:
    return dt.date.fromisoformat(args.today) if args.today else dt.date.today()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="替罪羊 —— 反复发作的触发器归因法庭")
    parser.add_argument("--version", action="version",
                        version=f"{PROG} {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func, helptext in (
            ("verdicts", cmd_verdicts, "全员审判台（有定罪 exit 4）"),
            ("judge", cmd_judge, "单人卷宗"),
            ("acquitted", cmd_acquitted, "平反名单"),
            ("case", cmd_case, "案发夜复盘"),
            ("simulate", cmd_simulate, "反事实：避开某人的推演"),
            ("combo", cmd_combo, "组合作案排查"),
            ("validate", cmd_validate, "账本体检")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("ledger", help="日更账本 TSV")
        p.add_argument("--today", help="钉死「今天」（YYYY-MM-DD，测试用）")
        if name == "judge":
            p.add_argument("--trigger", required=True, help="嫌疑人名")
        if name == "case":
            p.add_argument("--date", required=True, help="案发日期")
        if name == "simulate":
            p.add_argument("--avoid", required=True, help="要避开的嫌疑人")
            p.add_argument("--months", type=float, default=3.0,
                           help="折算月数（默认 3）")
        p.set_defaults(func=func)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LedgerError as exc:
        print(f"账本拒收：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
