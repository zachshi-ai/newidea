#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ghost-login · 僵尸账号 —— 你的攻击面不是最强的密码，是忘得最干净的账号.

问题：账号只增不减——注册是 30 秒的事，注销永远「明天再说」。你的
真实攻击面 = 全部历史账号的总和，而记忆只覆盖活跃的最近三年。最危险
的不是你最好的那个密码，而是十年前注册、和别处共用同一个密码、绑着
主邮箱、你已彻底遗忘的僵尸账号：攻击者拖一个 2011 年的冷门站点，撞
库撞的是你 2026 年的主邮箱。密码管理器会回答「这个密码强不强」，
从不回答「这个账号还该不该存在」。

ghost-login 从一份密码库导出（TSV：账号 / 登录名 / 密码 / 密码设置日
/ 最近登录 / 敏感层）确定性算出每个账号的**僵尸分**（0-100，四因子
各 0-25，全部可审）：

  * age     密码多久没换过（越老越危险）
  * stale   你多久没用它登录过（「从不复登」单独记档）
  * reuse   多少账号与它共用同一密码——一破俱破的多米诺簇
  * sens    它守着什么（vital 25 / normal 12 / trivial 4）

三档判定：SOUND（<40，活着）/ MUSTY（40-59，受潮）/ ZOMBIE（≥60，
统计意义上你永远不会再来登录，但它还握着你的一份资料）。另有：
复用簇明细（vital 落在簇里时单独亮牌）、主邮箱暴露度（多少僵尸拿你
的身份根当找回通道）、最弱密码熵、以及 simulate drop N——先看注销
前 N 名僵尸的代价单，再动手。

零依赖：Python 3.8+ 标准库。账本留在本地，报告永不回显明文密码
（只显示 sha256 指纹前 8 位）。它回答的是账本问题：删不删、改不改，
是你的决定；但没有清单，清理永远不会开始。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import date as _date
from typing import Dict, List, Optional

TIERS = ("vital", "normal", "trivial")
SENS_SCORE = {"vital": 25, "normal": 12, "trivial": 4}

AGE_STEP_YEARS = 2.0        # every 2 years un-rotated -> +5, cap 25
AGE_STEP_SCORE = 5
STALE_PER_YEAR = 8          # every silent year -> +8, cap 25
STALE_CAP = 25
STALE_NEVER = 18            # no last-login on record: the 'never' floor
REUSE_PER_PEER = 8          # every extra account on the same password

SOUND_BELOW = 40
ZOMBIE_AT = 60

DAYS_PER_YEAR = 365.25
WEAK_BITS = 28.0
FAIR_BITS = 45.0
CHARSET = {"digits": 10, "lower": 26, "upper": 26, "other": 33}

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_GATE = 4


# ---------------------------------------------------------------------------
# vault parsing
# ---------------------------------------------------------------------------

class VaultError(ValueError):
    """A bad vault file; message carries the 1-based line number."""


@dataclass
class Account:
    name: str
    username: str
    password: str
    pw_set: str          # date the password was last set
    last_used: Optional[str]  # last login you made yourself; None = on record never
    tier: str            # vital | normal | trivial
    line: int

    @property
    def fingerprint(self) -> str:
        """The only form of the password allowed near a report."""
        return hashlib.sha256(self.password.encode("utf-8")).hexdigest()[:8]


def parse_iso(text: str, what: str, line: int) -> str:
    try:
        _date.fromisoformat(text)
    except ValueError:
        raise VaultError("line %d: bad %s %r (want YYYY-MM-DD)"
                         % (line, what, text))
    return text


def read_vault(path: str) -> List[Account]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw_lines = fh.read().splitlines()
    except OSError as exc:
        raise VaultError("cannot read vault file: %s" % exc)

    accounts: List[Account] = []
    saw_header = False
    for idx, raw in enumerate(raw_lines, start=1):
        line = raw.strip("\r").rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        if cols and cols[0] == "name":
            if saw_header or accounts:
                raise VaultError("line %d: duplicate header row" % idx)
            saw_header = True
            continue
        if len(cols) < 5:
            raise VaultError(
                "line %d: expected 5 tab-separated columns "
                "(name username password pw_set last_used [tier]), got %d"
                % (idx, len(cols)))
        name, username, password, pw_set, last_used = cols[:5]
        if not name:
            raise VaultError("line %d: empty account name" % idx)
        if not username:
            raise VaultError("line %d: empty username" % idx)
        if not password:
            raise VaultError("line %d: empty password (use the real export "
                             "value; the report only ever shows a fingerprint)"
                             % idx)
        parse_iso(pw_set, "pw_set date", idx)
        last: Optional[str] = None
        if last_used and last_used != "-":
            last = parse_iso(last_used, "last_used date", idx)
        tier = cols[5] if len(cols) > 5 and cols[5] else "normal"
        if tier not in TIERS:
            raise VaultError("line %d: tier must be one of %s, got %r"
                             % (idx, "/".join(TIERS), tier))
        for a in accounts:
            if a.name == name:
                raise VaultError("line %d: duplicate account %r "
                                 "(first seen on line %d)"
                                 % (idx, name, a.line))
        accounts.append(Account(name=name, username=username,
                                password=password, pw_set=pw_set,
                                last_used=last, tier=tier, line=idx))
    if not accounts:
        raise VaultError("no data rows found (lines starting with '#' are "
                         "comments; the first row may be a 'name' header)")
    return accounts


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def days_between(from_iso: str, to_iso: str) -> int:
    return (_date.fromisoformat(to_iso) - _date.fromisoformat(from_iso)).days


def entropy_bits(password: str) -> float:
    """Bits = length * log2(charset actually used). A common-sense yardstick,
    not a strength oracle — see METHODOLOGY §5."""
    if not password:
        return 0.0
    size = 0
    if any(c.isdigit() for c in password):
        size += CHARSET["digits"]
    if any(c.islower() for c in password):
        size += CHARSET["lower"]
    if any(c.isupper() for c in password):
        size += CHARSET["upper"]
    if any(not c.isalnum() for c in password):
        size += CHARSET["other"]
    return len(password) * math.log2(size)


def entropy_grade(bits: float) -> str:
    if bits < WEAK_BITS:
        return "weak"
    if bits < FAIR_BITS:
        return "fair"
    return "strong"


@dataclass
class Score:
    age: int
    stale: int
    reuse: int
    sens: int
    total: int
    cluster: int           # size of the password cluster (1 = unique)
    bits: float

    @property
    def grade(self) -> str:
        if self.total >= ZOMBIE_AT:
            return "ZOMBIE"
        if self.total >= SOUND_BELOW:
            return "MUSTY"
        return "SOUND"


def age_score_of(pw_set: str, as_of: str) -> int:
    years = days_between(pw_set, as_of) / DAYS_PER_YEAR
    if years <= 0:
        return 0
    return min(25, int(years // AGE_STEP_YEARS) * AGE_STEP_SCORE)


def stale_score_of(last_used: Optional[str], as_of: str) -> int:
    if last_used is None:
        return STALE_NEVER
    years = days_between(last_used, as_of) / DAYS_PER_YEAR
    if years <= 0:
        return 0
    return min(STALE_CAP, int(years * STALE_PER_YEAR))


def grade_counts(scored) -> Dict[str, int]:
    out = {"SOUND": 0, "MUSTY": 0, "ZOMBIE": 0}
    for _, sc in scored:
        out[sc.grade] += 1
    return out


@dataclass
class Surface:
    file: str
    as_of: str
    primary: str
    scored: List  # List[Tuple[Account, Score]] sorted by score desc
    clusters: List  # List[Tuple[password, List[Account]]] sorted by size desc
    never_logged: int

    @property
    def n_accounts(self) -> int:
        return len(self.scored)

    def count(self, grade: str) -> int:
        return sum(1 for _, sc in self.scored if sc.grade == grade)

    def by_tier(self, tier: str) -> int:
        return sum(1 for a, _ in self.scored if a.tier == tier)

    @property
    def n_reused(self) -> int:
        return sum(1 for a, sc in self.scored if sc.cluster > 1)

    @property
    def vital_clusters(self) -> List:
        out = []
        for pw, members in self.clusters:
            if len(members) > 1 and any(m.tier == "vital" for m in members):
                out.append((pw, members))
        return out

    @property
    def primary_exposure(self) -> int:
        return sum(1 for a, _ in self.scored if a.username == self.primary)

    @property
    def primary_zombies(self) -> int:
        return sum(1 for a, sc in self.scored
                   if a.username == self.primary and sc.grade == "ZOMBIE")

    @property
    def weakest(self):
        return min(self.scored, key=lambda p: p[1].bits)

    @property
    def mean_score(self) -> float:
        return sum(sc.total for _, sc in self.scored) / len(self.scored)

    def warnings_list(self) -> List[str]:
        out = []
        if self.never_logged:
            out.append("%d account(s) have no last-login on record — stale "
                       "factor set to the 'never' floor (%d)"
                       % (self.never_logged, STALE_NEVER))
        return out


def primary_of(accounts: List[Account], override: Optional[str]) -> str:
    if override:
        return override
    freq: Dict[str, int] = {}
    for a in accounts:
        freq[a.username] = freq.get(a.username, 0) + 1
    # most frequent; ties broken alphabetically for determinism
    return sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def compute_surface(accounts: List[Account], as_of: str,
                    primary: Optional[str] = None) -> Surface:
    clusters: Dict[str, List[Account]] = {}
    for a in accounts:
        clusters.setdefault(a.password, []).append(a)
    cluster_list = sorted(clusters.items(),
                          key=lambda kv: (-len(kv[1]), kv[0]))

    scored = []
    never = 0
    for a in accounts:
        size = len(clusters[a.password])
        age = age_score_of(a.pw_set, as_of)
        stale = stale_score_of(a.last_used, as_of)
        if a.last_used is None:
            never += 1
        reuse = min(25, REUSE_PER_PEER * (size - 1))
        sens = SENS_SCORE[a.tier]
        total = age + stale + reuse + sens
        scored.append((a, Score(age=age, stale=stale, reuse=reuse,
                                sens=sens, total=total, cluster=size,
                                bits=entropy_bits(a.password))))
    scored.sort(key=lambda p: (-p[1].total, p[0].name))
    return Surface(file="", as_of=as_of,
                   primary=primary_of(accounts, primary),
                   scored=scored, clusters=cluster_list, never_logged=never)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def years_text(days: int) -> str:
    return "%.1fy" % (days / DAYS_PER_YEAR)


def factor_text(a: Account, sc: Score, as_of: str) -> str:
    head = "set %s · " % a.pw_set[:4]
    if a.last_used is None:
        head += "never re-logged"
    else:
        head += "%s silent" % years_text(days_between(a.last_used, as_of))
    return ("%s · age %d · stale %d · reuse %d · sens %d"
            % (head, sc.age, sc.stale, sc.reuse, sc.sens))


def row_text(a: Account, sc: Score) -> str:
    return "  score %2d  %-12s %-7s %-7s  #%s  %s" % (
        sc.total, a.name[:12], a.tier, sc.grade, a.fingerprint, a.username)


def surface_text(path: str, s: Surface) -> str:
    gc = grade_counts(s.scored)
    weakest_acc, weakest_sc = s.weakest
    warns = s.warnings_list()
    lines = [
        "-- Ghost login report: %s  (as of %s)" % (path, s.as_of),
        "  accounts tracked       : %d  (%d vital / %d normal / %d trivial)"
        % (s.n_accounts, s.by_tier("vital"), s.by_tier("normal"),
           s.by_tier("trivial")),
        "  grades                 : %d SOUND · %d MUSTY · %d ZOMBIE"
        % (gc["SOUND"], gc["MUSTY"], gc["ZOMBIE"]),
        "  reuse clusters         : %d  (%d of %d accounts share a password)"
        % (len([1 for pw, m in s.clusters if len(m) > 1]),
           s.n_reused, s.n_accounts),
        "  vital in a cluster     : %s"
        % ("yes — %d cluster(s) hold a vital account"
           % len(s.vital_clusters) if s.vital_clusters else "no"),
        "  primary identity       : %s (%d accounts · %d zombie(s) behind it)"
        % (s.primary, s.primary_exposure, s.primary_zombies),
        "  weakest password       : %s  %.1f bits (%s)"
        % (weakest_acc.name[:12], weakest_sc.bits,
           entropy_grade(weakest_sc.bits)),
        "  mean score             : %.1f" % s.mean_score,
        "  warnings               : %s"
        % ("; ".join(warns) if warns else "none"),
        "",
    ]
    groups = [
        ("ZOMBIE — score >= %d: statistically, you are never logging in "
         "again" % ZOMBIE_AT, "ZOMBIE"),
        ("MUSTY — %d-%d: going stale, still within reach"
         % (SOUND_BELOW, ZOMBIE_AT - 1), "MUSTY"),
        ("SOUND — below %d" % SOUND_BELOW, "SOUND"),
    ]
    for title, grade in groups:
        members = [(a, sc) for a, sc in s.scored if sc.grade == grade]
        if members:
            lines.append("  %s" % title)
            for a, sc in members:
                lines.append(row_text(a, sc))
                lines.append("    %s" % factor_text(a, sc, s.as_of))
            lines.append("")
    lines.extend(verdict_lines(s))
    return "\n".join(lines) + "\n"


def verdict_lines(s: Surface) -> List[str]:
    zombies = [(a, sc) for a, sc in s.scored if sc.grade == "ZOMBIE"]
    lines: List[str] = []
    if not zombies:
        lines.append("No zombies: nothing here is statistically dead. The")
        lines.append("ledger's remaining questions are cluster ones — who")
        lines.append("shares a password with whom, and where your vital")
        lines.append("accounts sit inside those clusters.")
        if s.vital_clusters:
            lines.append("And the answer is: %d cluster(s) hold a vital "
                         "account. Deletion" % len(s.vital_clusters))
            lines.append("is not the fix there — one password change per "
                         "cluster is.")
        return lines
    lines.append("Your attack surface is not your strongest password; it is")
    lines.append("the account you remember least. %d account(s) here are "
                 "past the" % len(zombies))
    lines.append("zombie line: password set years ago, silence measured in "
                 "years,")
    if s.primary_zombies:
        lines.append("and your primary inbox (%s) is the recovery channel"
                     % s.primary)
        lines.append("for %d of them — crack a ghost, own the identity root."
                     % s.primary_zombies)
    if s.vital_clusters:
        lines.append("Worse: %d reuse cluster(s) hold a vital account — one "
                     "leaked" % len(s.vital_clusters))
        lines.append("database anywhere in the cluster cracks the vital one "
                     "too.")
    lines.append("Deletion clears zombies; only a password change breaks a "
                 "cluster.")
    lines.append("See 'simulate drop N' for the bill before you start.")
    return lines


def clusters_text(path: str, s: Surface) -> str:
    lines = ["-- Reuse clusters: %s  (as of %s)" % (path, s.as_of)]
    multi = [(pw, members) for pw, members in s.clusters if len(members) > 1]
    if not multi:
        lines.append("  none — every account runs on its own password.")
        return "\n".join(lines) + "\n"
    lines.append("  %d cluster(s); %d of %d accounts share a password."
                 % (len(multi), s.n_reused, s.n_accounts))
    lines.append("")
    for pw, members in sorted(multi, key=lambda kv: -len(kv[1])):
        mark = ""
        if any(m.tier == "vital" for m in members):
            mark = "  !! holds a vital account"
        lines.append("  cluster #%s  size %d%s"
                     % (hashlib.sha256(pw.encode("utf-8")).hexdigest()[:8],
                        len(members), mark))
        for m in sorted(members, key=lambda a: a.pw_set):
            lines.append("    %-12s %-7s set %s  %s"
                         % (m.name[:12], m.tier, m.pw_set, m.username))
        lines.append("    one leaked database anywhere above cracks every "
                     "account here;")
        if any(m.tier == "vital" for m in members):
            lines.append("    the fix is one password change (start from "
                         "the vital one).")
        else:
            lines.append("    the fix is one password change on any member "
                         "of the cluster.")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# simulation: drop the top-N zombies
# ---------------------------------------------------------------------------

def simulate_drop_text(path: str, s: Surface, n: int) -> str:
    zombies = [(a, sc) for a, sc in s.scored if sc.grade == "ZOMBIE"]
    lines = ["-- Simulation (drop %d): %s  (as of %s)"
             % (n, path, s.as_of)]
    if not zombies:
        lines.append("  nothing to drop — no account is past the zombie "
                     "line.")
        return "\n".join(lines) + "\n"
    if n == 0:
        lines.append("  nothing dropped — you asked for 0; the surface is "
                     "unchanged.")
        return "\n".join(lines) + "\n"
    count = min(n, len(zombies))
    if count < n:
        lines.append("  note: only %d zombie(s) exist; dropping all %d."
                     % (count, count))
    dropped = zombies[:count]
    rest = [(a, sc) for a, sc in s.scored if (a, sc) not in zombies[:count]]

    def summary(surface):
        gc = grade_counts(surface.scored)
        return (gc["ZOMBIE"], gc["MUSTY"], gc["SOUND"],
                len([1 for pw, m in surface.clusters if len(m) > 1]),
                max((len(m) for _, m in surface.clusters), default=0),
                surface.primary_exposure, surface.primary_zombies,
                surface.mean_score)

    rest_surface = Surface(file=s.file, as_of=s.as_of, primary=s.primary,
                           scored=rest,
                           clusters=_recluster(rest),
                           never_logged=sum(1 for a, _ in rest
                                            if a.last_used is None))
    z0, mu0, so0, c0, big0, pe0, pz0, m0 = summary(s)
    z1, mu1, so1, c1, big1, pe1, pz1, m1 = summary(rest_surface)
    lines.append("  dropped                : %s"
                 % ", ".join(sorted(a.name for a, _ in dropped)))
    lines.append("  grades                 : %d ZOMBIE · %d MUSTY · %d SOUND"
                 "  ->  %d ZOMBIE · %d MUSTY · %d SOUND"
                 % (z0, mu0, so0, z1, mu1, so1))
    lines.append("  reuse clusters         : %d -> %d   (largest %d -> %d)"
                 % (c0, c1, big0, big1))
    lines.append("  primary exposure       : %d accounts -> %d  "
                 "(zombies behind it %d -> %d)"
                 % (pe0, pe1, pz0, pz1))
    lines.append("  mean score             : %.1f -> %.1f" % (m0, m1))
    lines.append("")
    survivor_clusters = [(pw, m) for pw, m in rest_surface.clusters
                         if len(m) > 1]
    if survivor_clusters:
        survivors = sorted(m.name for _, m in survivor_clusters for m in m)
        lines.append("Deletion cleared %d zombie(s) — but %d cluster(s) "
                     "survived, holding: %s." % (count, len(survivor_clusters),
                                                 ", ".join(survivors)))
        lines.append("Zombies are removed by deletion; clusters only by a "
                     "password change.")
    else:
        lines.append("Deletion cleared %d zombie(s) and every reuse cluster "
                     "with them." % count)
    return "\n".join(lines) + "\n"


def _recluster(scored):
    clusters: Dict[str, List] = {}
    for a, _ in scored:
        clusters.setdefault(a.password, []).append(a)
    return sorted(clusters.items(), key=lambda kv: (-len(kv[1]), kv[0]))


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def surface_json(path: str, s: Surface) -> str:
    gc = grade_counts(s.scored)
    weakest_acc, weakest_sc = s.weakest
    doc = {
        "file": path,
        "as_of": s.as_of,
        "primary": s.primary,
        "n_accounts": s.n_accounts,
        "tiers": {t: s.by_tier(t) for t in TIERS},
        "grades": gc,
        "reuse_clusters": len([1 for pw, m in s.clusters if len(m) > 1]),
        "n_reused_accounts": s.n_reused,
        "vital_clusters": len(s.vital_clusters),
        "primary_exposure": s.primary_exposure,
        "primary_zombies": s.primary_zombies,
        "weakest_password": {
            "account": weakest_acc.name,
            "bits": round(weakest_sc.bits, 1),
            "grade": entropy_grade(weakest_sc.bits),
        },
        "mean_score": round(s.mean_score, 1),
        "warnings": s.warnings_list(),
        "accounts": [
            {
                "name": a.name,
                "username": a.username,
                "tier": a.tier,
                "grade": sc.grade,
                "score": sc.total,
                "factors": {"age": sc.age, "stale": sc.stale,
                            "reuse": sc.reuse, "sens": sc.sens},
                "cluster_size": sc.cluster,
                "password_fingerprint": a.fingerprint,
                "entropy_bits": round(sc.bits, 1),
                "entropy_grade": entropy_grade(sc.bits),
                "pw_set": a.pw_set,
                "last_used": a.last_used,
            }
            for a, sc in s.scored
        ],
        "verdict": " ".join(verdict_lines(s)),
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def validate_text(path: str, accounts: List[Account], as_of: str) -> str:
    never = sum(1 for a in accounts if a.last_used is None)
    tiers = {t: sum(1 for a in accounts if a.tier == t) for t in TIERS}
    future = [a for a in accounts if a.last_used and a.last_used > as_of]
    future += [a for a in accounts if a.pw_set > as_of]
    warns = []
    if never:
        warns.append("%d row(s) with no last-login date" % never)
    if future:
        warns.append("%d row(s) dated after as_of" % len(future))
    lines = [
        "-- Vault check: %s" % path,
        "  rows parsed           : %d  (%d vital / %d normal / %d trivial)"
        % (len(accounts), tiers["vital"], tiers["normal"], tiers["trivial"]),
        "  unique usernames      : %d" % len({a.username for a in accounts}),
        "  pw_set range          : %s .. %s"
        % (min(a.pw_set for a in accounts), max(a.pw_set for a in accounts)),
        "  as_of                 : %s" % as_of,
        "  warnings              : %s"
        % ("; ".join(warns) if warns else "none"),
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve_as_of(accounts: List[Account], today_arg: Optional[str]) -> str:
    if today_arg is not None:
        try:
            _date.fromisoformat(today_arg)
        except ValueError:
            raise VaultError("bad --today %r (want YYYY-MM-DD)" % today_arg)
        return today_arg
    dates = [a.pw_set for a in accounts] + \
            [a.last_used for a in accounts if a.last_used]
    return max(dates)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ghost_login.py",
        description="ghost-login · score every account by its zombie "
                    "factors: age, silence, reuse, sensitivity.")
    sub = parser.add_subparsers(dest="cmd")

    def add_common(p):
        p.add_argument("vault", help="TSV: name, username, password, pw_set, "
                                     "last_used, [tier]")
        p.add_argument("--today", default=None, metavar="YYYY-MM-DD",
                       help="override the clock (default: last vault date)")
        p.add_argument("--primary", default=None, metavar="EMAIL",
                       help="your primary identity (default: most frequent "
                            "username in the vault)")

    p_rep = sub.add_parser("report", help="zombie scores / grades / exposure")
    add_common(p_rep)
    p_rep.add_argument("--format", choices=("text", "json"), default="text")
    p_rep.add_argument("--fail-zombies", type=int, default=None, metavar="N",
                       help="exit 4 when ZOMBIE count >= N")

    p_clu = sub.add_parser("clusters", help="who shares a password with whom")
    add_common(p_clu)

    p_sim = sub.add_parser("simulate", help="bill before you start: drop N")
    add_common(p_sim)
    p_sim.add_argument("scenario", choices=("drop",))
    p_sim.add_argument("n", type=int, help="how many top zombies to drop")

    p_val = sub.add_parser("validate", help="parse check + vault warnings")
    add_common(p_val)

    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return EXIT_USAGE

    try:
        accounts = read_vault(args.vault)
        as_of = resolve_as_of(accounts, args.today)
    except VaultError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_INPUT

    if args.cmd == "validate":
        print(validate_text(args.vault, accounts, as_of), end="")
        return EXIT_OK

    surface = compute_surface(accounts, as_of, args.primary)
    surface.file = args.vault

    if args.cmd == "report":
        out = (surface_json(args.vault, surface) if args.format == "json"
               else surface_text(args.vault, surface))
        print(out, end="")
        if (args.fail_zombies is not None
                and surface.count("ZOMBIE") >= args.fail_zombies):
            print("gate: %d ZOMBIE >= --fail-zombies %d"
                  % (surface.count("ZOMBIE"), args.fail_zombies),
                  file=sys.stderr)
            return EXIT_GATE
        return EXIT_OK

    if args.cmd == "clusters":
        print(clusters_text(args.vault, surface), end="")
        return EXIT_OK

    # simulate drop
    if args.n < 0:
        print("error: drop count must be >= 0", file=sys.stderr)
        return EXIT_USAGE
    print(simulate_drop_text(args.vault, surface, args.n), end="")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
