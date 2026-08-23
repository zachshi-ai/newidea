#!/usr/bin/env python3
"""midnight_oil.py — git 提交时间考古：把过劳从「感觉」变成「信号」.

Git 的 author date（如 2026-08-24T01:30:00+08:00）里的钟点就是作者当时
墙上钟的钟点——无需任何时区换算，就能知道「他几点在提交」。本工具用这一
事实从 git 历史确定性重建每人 / 全队的工作时间画像：深夜比例、周末比例、
最长无休 streak、周末深夜同现，以及「最近 N 天 vs 更早」的趋势对比——
绝对值不定罪，趋势才说话。

子命令:
  scan     仓库总览: 多少提交、多少深夜多少周末（无需参数）
  authors  每人画像: 24 小时直方图、flags、等级
  trend    自身对比: 最近 N 天 vs 更早（默认 91 天）
  audit    健康门禁: 深夜/周末/streak 超红线 exit 1（CI 用）

零依赖: Python 3.8+ 标准库 + git。纯本地运行，数据不出机器。
"""

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- signals

LATE_HOURS = frozenset([22, 23, 0, 1, 2, 3, 4])   # 22:00-04:59 作者本地钟点
LATE_PCT_FLAG = 15.0        # 深夜提交占比 >= 15% -> LATE_NIGHT
WEEKEND_PCT_FLAG = 20.0     # 周末提交占比 >= 20% -> WEEKENDS
STREAK_DAYS_FLAG = 14       # 最长连续无休 >= 14 天 -> NO_BREAK
WEEKEND_LATE_FLAG = 3       # 周末深夜同日 >= 3 次 -> WEEKEND_LATE

TREND_DELTA = 5.0           # 百分点差 >= 5 才算 WORSENING/IMPROVING
TREND_MIN_COMMITS = 10      # 每段至少 10 个提交才可判定

FLAG_LABELS = {
    "LATE_NIGHT": ">= {0:.0f}% of commits between 22:00 and 05:00 (local clock)".format(LATE_PCT_FLAG),
    "WEEKENDS": ">= {0:.0f}% of commits on Sat/Sun (local date)".format(WEEKEND_PCT_FLAG),
    "NO_BREAK": "longest streak of commit-days >= {0} without a day off".format(STREAK_DAYS_FLAG),
    "WEEKEND_LATE": ">= {0} distinct weekend days with late-night commits".format(WEEKEND_LATE_FLAG),
}


def is_late_hour(hour: int) -> bool:
    return hour in LATE_HOURS


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


# ---------------------------------------------------------------- parsing

class Commit:
    __slots__ = ("sha", "when", "author", "email")

    def __init__(self, sha: str, when: datetime, author: str, email: str):
        self.sha = sha
        self.when = when      # 作者本地墙钟时间（author date 原样，未换算）
        self.author = author
        self.email = email

    @property
    def day(self) -> date:
        return self.when.date()

    @property
    def hour(self) -> int:
        return self.when.hour

    @property
    def late(self) -> bool:
        return is_late_hour(self.hour)

    @property
    def weekend(self) -> bool:
        return is_weekend(self.day)


def parse_stamp(ts: str) -> datetime:
    """解析 git %aI 输出: 2026-08-24T01:30:00+08:00（含兜底格式）.

    返回的 datetime 刻意不换算时区——钟点与日期字段就是作者本地的墙钟。
    """
    try:
        return datetime.fromisoformat(ts.strip())
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts.strip(), fmt)
        except ValueError:
            continue
    raise ValueError("unparseable timestamp: {!r}".format(ts))


FIELD_SEP = "\x1f"


def parse_log(out: str) -> List[Commit]:
    """解析 `git log --format=%H%x1f%aI%x1f%an%x1f%ae` 的输出."""
    commits: List[Commit] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split(FIELD_SEP)
        if len(parts) != 4:
            continue
        sha, stamp, name, email = parts
        commits.append(Commit(sha.strip(), parse_stamp(stamp), name.strip(),
                              email.strip()))
    return commits


def run_git(root: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", root] + list(args),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("git {} failed: {}".format(
            " ".join(args[:2]), proc.stderr.strip()))
    return proc.stdout


def toplevel(root: str) -> Optional[str]:
    proc = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def load_commits(root: str) -> List[Commit]:
    out = run_git(root, "log", "--all",
                  "--format=%H{0}%aI{0}%an{0}%ae".format(FIELD_SEP))
    commits = parse_log(out)
    commits.sort(key=lambda c: (c.when, c.sha))
    return commits


def filter_commits(commits: Sequence[Commit],
                   author: Optional[str] = None,
                   exclude_authors: Sequence[str] = (),
                   since: Optional[date] = None,
                   until: Optional[date] = None) -> List[Commit]:
    """按作者（子串，大小写不敏感）与作者本地日期窗过滤."""
    def dropped(c: Commit) -> bool:
        if author and author.lower() not in c.author.lower():
            return True
        for x in exclude_authors:
            xl = x.lower()
            if xl and (xl in c.author.lower() or xl in c.email.lower()):
                return True
        return False

    return [c for c in commits
            if not dropped(c) and not (since and c.day < since)
            and not (until and c.day > until)]


# ---------------------------------------------------------------- metrics

def longest_streak(days: Sequence[date]) -> int:
    """最长连续提交天数（按作者本地日期去重后）."""
    if not days:
        return 0
    ordered = sorted(set(days))
    best = run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)
    return best


class Profile:
    """一名作者的工作时间画像."""

    def __init__(self, name: str, commits: Sequence[Commit]):
        self.name = name
        self.commits = list(commits)
        n = len(self.commits)
        self.late_n = sum(1 for c in self.commits if c.late)
        self.weekend_n = sum(1 for c in self.commits if c.weekend)
        self.histogram = Counter(c.hour for c in self.commits)
        days = [c.day for c in self.commits]
        self.days = set(days)
        self.longest_streak_days = longest_streak(days)
        self.weekend_late_days = sorted({c.day for c in self.commits
                                         if c.weekend and c.late})
        self.first_day = min(days) if days else None
        self.last_day = max(days) if days else None

    @property
    def late_pct(self) -> float:
        return 100.0 * self.late_n / len(self.commits) if self.commits else 0.0

    @property
    def weekend_pct(self) -> float:
        return (100.0 * self.weekend_n / len(self.commits)
                if self.commits else 0.0)

    def flags(self) -> List[str]:
        out = []
        if len(self.commits) >= 10:
            if self.late_pct >= LATE_PCT_FLAG:
                out.append("LATE_NIGHT")
            if self.weekend_pct >= WEEKEND_PCT_FLAG:
                out.append("WEEKENDS")
        if self.longest_streak_days >= STREAK_DAYS_FLAG:
            out.append("NO_BREAK")
        if len(self.weekend_late_days) >= WEEKEND_LATE_FLAG:
            out.append("WEEKEND_LATE")
        return out

    def level(self) -> str:
        n = len(self.flags())
        return "ok" if n == 0 else ("watch" if n == 1 else "alert")

    def as_dict(self, anonymize: bool = False) -> Dict[str, object]:
        return {
            "author": anon_name(self.name) if anonymize else self.name,
            "commits": len(self.commits),
            "first": self.first_day.isoformat() if self.first_day else None,
            "last": self.last_day.isoformat() if self.last_day else None,
            "active_days": len(self.days),
            "late_pct": round(self.late_pct, 1),
            "weekend_pct": round(self.weekend_pct, 1),
            "longest_streak_days": self.longest_streak_days,
            "weekend_late_days": [d.isoformat() for d in self.weekend_late_days],
            "histogram": [self.histogram.get(h, 0) for h in range(24)],
            "flags": self.flags(),
            "level": self.level(),
        }


def group_profiles(commits: Sequence[Commit]) -> List[Profile]:
    """按作者聚合（同名不同邮箱并到作者名），按提交量降序."""
    by_name: Dict[str, List[Commit]] = {}
    for c in commits:
        by_name.setdefault(c.author, []).append(c)
    profiles = [Profile(name, cs) for name, cs in by_name.items()]
    profiles.sort(key=lambda p: (-len(p.commits), p.name))
    return profiles


def anon_name(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return "anon-{}".format(digest)


# ---------------------------------------------------------------- trend

class Trend:
    """最近 N 天 vs 更早的自身对比——绝对值不定罪，趋势才说话."""

    def __init__(self, recent: Sequence[Commit], baseline: Sequence[Commit],
                 window_days: int, as_of: date):
        self.recent = list(recent)
        self.baseline = list(baseline)
        self.window_days = window_days
        self.as_of = as_of

    @staticmethod
    def _seg(commits: Sequence[Commit]) -> Dict[str, object]:
        n = len(commits)
        late = sum(1 for c in commits if c.late)
        weekend = sum(1 for c in commits if c.weekend)
        days = {c.day for c in commits}
        if commits:
            # 每段按自己的跨度折算（至少一周），两段才可比
            span = max((max(days) - min(days)).days + 1, 7)
            weekly = round(len(days) / (span / 7.0), 1)
        else:
            weekly = 0.0
        return {
            "commits": n,
            "late_pct": round(100.0 * late / n, 1) if n else 0.0,
            "weekend_pct": round(100.0 * weekend / n, 1) if n else 0.0,
            "active_days": len(days),
            "weekly_active_days": weekly,
        }

    def recent_seg(self) -> Dict[str, object]:
        return self._seg(self.recent)

    def baseline_seg(self) -> Dict[str, object]:
        return self._seg(self.baseline)

    @staticmethod
    def _direction(recent_pct: float, base_pct: float,
                   recent_n: int, base_n: int) -> str:
        if recent_n < TREND_MIN_COMMITS or base_n < TREND_MIN_COMMITS:
            return "INSUFFICIENT"
        delta = recent_pct - base_pct
        if delta >= TREND_DELTA:
            return "WORSENING"
        if delta <= -TREND_DELTA:
            return "IMPROVING"
        return "STABLE"

    def directions(self) -> Dict[str, str]:
        r, b = self.recent_seg(), self.baseline_seg()
        return {
            "late": self._direction(float(r["late_pct"]), float(b["late_pct"]),
                                    int(r["commits"]), int(b["commits"])),
            "weekend": self._direction(float(r["weekend_pct"]),
                                       float(b["weekend_pct"]),
                                       int(r["commits"]), int(b["commits"])),
        }

    def as_dict(self) -> Dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "window_days": self.window_days,
            "recent": self.recent_seg(),
            "baseline": self.baseline_seg(),
            "directions": self.directions(),
        }


def split_trend(commits: Sequence[Commit], window_days: int,
                as_of: date) -> Trend:
    cutoff = as_of - timedelta(days=window_days)
    recent = [c for c in commits if c.day > cutoff]
    baseline = [c for c in commits if c.day <= cutoff]
    return Trend(recent, baseline, window_days, as_of)


# ---------------------------------------------------------------- report

class Report:
    def __init__(self, root: str, commits: Sequence[Commit],
                 as_of: date, anonymize: bool = False):
        self.root = root
        self.commits = list(commits)
        self.as_of = as_of
        self.anonymize = anonymize
        self.profiles = group_profiles(self.commits)

    @property
    def late_pct(self) -> float:
        n = len(self.commits)
        return 100.0 * sum(1 for c in self.commits if c.late) / n if n else 0.0

    @property
    def weekend_pct(self) -> float:
        n = len(self.commits)
        return (100.0 * sum(1 for c in self.commits if c.weekend) / n
                if n else 0.0)

    @property
    def max_streak(self) -> int:
        return max((p.longest_streak_days for p in self.profiles), default=0)

    @property
    def weekend_late_count(self) -> int:
        return sum(len(p.weekend_late_days) for p in self.profiles)

    def level(self) -> str:
        levels = [p.level() for p in self.profiles]
        if any(l == "alert" for l in levels):
            return "alert"
        if any(l == "watch" for l in levels):
            return "watch"
        return "ok" if levels else "empty"

    def summary(self) -> Dict[str, object]:
        return {
            "repo": self.root,
            "as_of": self.as_of.isoformat(),
            "anonymized": self.anonymize,
            "commits": len(self.commits),
            "authors": len(self.profiles),
            "late_pct": round(self.late_pct, 1),
            "weekend_pct": round(self.weekend_pct, 1),
            "max_streak_days": self.max_streak,
            "weekend_late_days": self.weekend_late_count,
            "level": self.level(),
        }


# ---------------------------------------------------------------- render

def _bar(pct: float, width: int = 10) -> str:
    return "#" * min(width, int(round(pct / 10.0)))


def render_scan(r: Report) -> str:
    lines = [
        "-- Midnight oil -----------------------------------------",
        "  as of           : {}".format(r.as_of.isoformat()),
        "  commits         : {}".format(len(r.commits)),
        "  authors         : {}".format(len(r.profiles)),
        "  late-night 22-05: {:>5.1f}%  {}".format(r.late_pct, _bar(r.late_pct)),
        "  weekend         : {:>5.1f}%  {}".format(r.weekend_pct, _bar(r.weekend_pct)),
        "  longest streak  : {} commit-days without a break".format(r.max_streak),
        "  weekend late-night: {} distinct days".format(r.weekend_late_count),
    ]
    if not r.commits:
        lines.append("  (no commits in range — nothing to burn)")
    return "\n".join(lines)


def _hist_lines(hist: Counter) -> List[str]:
    """24 桶小时直方图，两行 00-11 / 12-23，峰值 8 格."""
    peak = max(hist.values(), default=0) or 1
    def cell(h: int) -> str:
        n = int(round(hist.get(h, 0) * 8 / peak))
        return "{:02d}:{}".format(h, "#" * n)
    return [
        "    am  " + " ".join(cell(h) for h in range(0, 12)),
        "    pm  " + " ".join(cell(h) for h in range(12, 24)),
    ]


def render_authors(r: Report) -> str:
    lines = ["-- Who is burning the midnight oil ----------------------"]
    if not r.profiles:
        lines.append("  (no commits in range)")
        return "\n".join(lines)
    for p in r.profiles:
        shown = anon_name(p.name) if r.anonymize else p.name
        lines.append("")
        lines.append("  {}  [{}]".format(shown, p.level().upper()))
        lines.append("    commits {:<6} active days {:<5} span {} -> {}".format(
            len(p.commits), len(p.days),
            p.first_day.isoformat() if p.first_day else "-",
            p.last_day.isoformat() if p.last_day else "-"))
        lines.append("    late-night {:>5.1f}%   weekend {:>5.1f}%   "
                     "streak {}d   weekend-late {}d".format(
                         p.late_pct, p.weekend_pct,
                         p.longest_streak_days, len(p.weekend_late_days)))
        lines.extend(_hist_lines(p.histogram))
        flags = p.flags()
        lines.append("    flags: {}".format(", ".join(flags) if flags else "none"))
    lines.append("")
    lines.append("  levels: {} ok / {} watch / {} alert".format(
        sum(1 for p in r.profiles if p.level() == "ok"),
        sum(1 for p in r.profiles if p.level() == "watch"),
        sum(1 for p in r.profiles if p.level() == "alert")))
    return "\n".join(lines)


def render_trend(t: Trend, r: Report) -> str:
    rseg, bseg = t.recent_seg(), t.baseline_seg()
    dirs = t.directions()
    lines = [
        "-- Recent vs baseline (the night-owl defense) -----------",
        "  as of {} ; recent window = {} days".format(
            t.as_of.isoformat(), t.window_days),
        "",
        "  {:<12} {:>10} {:>12}".format("segment", "commits", "late/weekend"),
        "  {:<12} {:>10} {:>12}".format(
            "recent", str(rseg["commits"]),
            "{:.1f}% / {:.1f}%".format(rseg["late_pct"], rseg["weekend_pct"])),
        "  {:<12} {:>10} {:>12}".format(
            "baseline", str(bseg["commits"]),
            "{:.1f}% / {:.1f}%".format(bseg["late_pct"], bseg["weekend_pct"])),
        "",
        "  late-night : {} (>= +{:.0f}pp = WORSENING)".format(
            dirs["late"], TREND_DELTA),
        "  weekend    : {}".format(dirs["weekend"]),
        "",
    ]
    verdict = "STABLE" if "WORSENING" not in dirs.values() else "WORSENING"
    lines.append("  overall    : {}".format(verdict))
    lines.append("  signals start conversations, not verdicts — "
                 "talk before you judge.")
    return "\n".join(lines)


# ---------------------------------------------------------------- audit

def audit_violations(r: Report, max_late: float, max_weekend: float,
                     max_streak: int) -> List[str]:
    out = []
    # 比例类检查与 per-author flag 同一纪律: 样本 <10 宁可沉默
    if len(r.commits) >= TREND_MIN_COMMITS and r.late_pct > max_late:
        out.append("late-night {:.1f}% exceeds budget {:.1f}%".format(
            r.late_pct, max_late))
    if len(r.commits) >= TREND_MIN_COMMITS and r.weekend_pct > max_weekend:
        out.append("weekend {:.1f}% exceeds budget {:.1f}%".format(
            r.weekend_pct, max_weekend))
    hot = [p for p in r.profiles if p.longest_streak_days >= max_streak]
    for p in hot:
        shown = anon_name(p.name) if r.anonymize else p.name
        out.append("{} streak {}d exceeds budget {}d".format(
            shown, p.longest_streak_days, max_streak))
    return out


# ---------------------------------------------------------------- cli

def _parse_day(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repo", nargs="?", default=".",
                        help="path inside the git repo (default: cwd)")
    parser.add_argument("--author", help="filter: substring of author name")
    parser.add_argument("--exclude-author", action="append", default=[],
                        help="drop authors matching substring (bots etc.), repeatable")
    parser.add_argument("--since", type=_parse_day,
                        help="author-local start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--until", type=_parse_day,
                        help="author-local end date YYYY-MM-DD (inclusive)")
    parser.add_argument("--as-of", type=_parse_day,
                        help="pin 'today' for reproducible reports")
    parser.add_argument("--anonymize", action="store_true",
                        help="replace author names with stable anon-<hash>")
    parser.add_argument("--format", choices=["text", "json"], default="text")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="midnight_oil.py",
        description="git 提交时间考古: measure late-night, weekend and "
                    "no-break signals from author-local commit clocks.")
    sub = ap.add_subparsers(dest="cmd", metavar="command")

    p = sub.add_parser("scan", help="one-glance repo overview")
    _common(p)

    p = sub.add_parser("authors", help="per-author work-hour profile + flags")
    _common(p)

    p = sub.add_parser("trend", help="recent N days vs earlier baseline")
    _common(p)
    p.add_argument("--window", type=int, default=91,
                   help="recent window in days (default 91 = 13 weeks)")

    p = sub.add_parser("audit", help="health gate: exit 1 over budget")
    _common(p)
    p.add_argument("--max-late", type=float, default=LATE_PCT_FLAG,
                   help="repo-wide late-night %% budget (default %(default)s)")
    p.add_argument("--max-weekend", type=float, default=WEEKEND_PCT_FLAG,
                   help="repo-wide weekend %% budget (default %(default)s)")
    p.add_argument("--max-streak", type=int, default=STREAK_DAYS_FLAG,
                   help="per-author streak budget in days (default %(default)s)")
    return ap


def _report(args: argparse.Namespace) -> Optional[Report]:
    top = toplevel(args.repo)
    if top is None:
        print("error: not a git repository: {}".format(args.repo),
              file=sys.stderr)
        return None
    commits = load_commits(top)
    commits = filter_commits(commits, author=args.author,
                             exclude_authors=args.exclude_author,
                             since=args.since, until=args.until)
    as_of = args.as_of or date.today()
    return Report(top, commits, as_of, anonymize=args.anonymize)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.cmd:
        build_parser().print_help()
        return 2
    if args.cmd == "scan":
        r = _report(args)
        if r is None:
            return 2
        print(json.dumps(r.summary(), ensure_ascii=False, sort_keys=True)
              if args.format == "json" else render_scan(r))
        return 0
    if args.cmd == "authors":
        r = _report(args)
        if r is None:
            return 2
        payload = {"summary": r.summary(),
                   "authors": [p.as_dict(anonymize=args.anonymize)
                               for p in r.profiles]}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True)
              if args.format == "json" else render_authors(r))
        return 0
    if args.cmd == "trend":
        r = _report(args)
        if r is None:
            return 2
        t = split_trend(r.commits, args.window, r.as_of)
        if args.format == "json":
            print(json.dumps(t.as_dict(), ensure_ascii=False, sort_keys=True))
        else:
            print(render_trend(t, r))
        return 0
    if args.cmd == "audit":
        r = _report(args)
        if r is None:
            return 2
        violations = audit_violations(r, args.max_late, args.max_weekend,
                                      args.max_streak)
        payload = dict(r.summary(), budget={
            "max_late_pct": args.max_late, "max_weekend_pct": args.max_weekend,
            "max_streak_days": args.max_streak}, violations=violations)
        if args.format == "json":
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            if violations:
                print("-- Health budget exceeded ------------------------------")
                for v in violations:
                    print("  ! {}".format(v))
                return 1
            print("-- Within health budget ---------------------------------")
            print("  late-night {:.1f}% / weekend {:.1f}% / "
                  "max streak {}d — all within budget".format(
                      r.late_pct, r.weekend_pct, r.max_streak))
        return 0 if not violations else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
