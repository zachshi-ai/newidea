#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""witching-hour — 危险时刻 / Witching Hour

Every bug has two timestamps: when it was WRITTEN and when it was found.
Tools only ever show you the second one. witching-hour blames the lines a
fix commit deleted back to the commit where they were BORN, buckets every
defect by the author's wall clock, and compares against how much code the
same hours produced. If 02:00-05:00 ships 5% of the lines but 15% of the
later-fixed ones, that window is a statistical witching hour.

  * scan    — full attribution: fix commits -> deleted lines -> birth
              commits -> hour-of-sin buckets with risk ratios
  * rhythm  — the coding clock: activity by wall-clock hour and weekday
              (no attribution, fast, answers "when do we actually code?")
  * birth   — line-by-line birth certificate of one file, with lines born
              inside the danger window flagged

Method in one line: `git diff` a fix commit to find the lines it deleted,
`git blame` the parent revision to find where those lines were born, and
count them in the hour their author's own wall clock showed.

Zero dependencies: Python 3.8+ standard library + a git binary.
MIT License (c) 2026
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Vocabulary

DEFAULT_FIX_PATTERN = r"(?i)\b(fix|bug|revert|hotfix|patch)\b|修复|修正|解了"
DEFAULT_BUCKET_HOURS = 3        # 3h windows: 00-03, 03-06, ... 8 rows
DEFAULT_DANGER_RR = 1.5         # a window is DANGER at >= 1.5x baseline risk
DEFAULT_MIN_BUCKET_LINES = 5    # defect lines needed before we judge a window
DEFAULT_MIN_TOTAL_LINES = 20    # below this the whole report says "insufficient"
DEFAULT_MAX_FIX_COMMITS = 300   # blame is expensive; cap the archaeology
DEFAULT_DANGER_START = 22       # birth subcommand: flag window 22:00..
DEFAULT_DANGER_END = 6          # ..06:00 (wraps midnight)

SENTINEL = "\x1e"  # between commits in `git log --format`
UNIT = "\x1f"      # between fields inside a commit header

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# ---------------------------------------------------------------------------
# Small pure helpers


def hour_of(iso: str) -> int:
    """Wall-clock hour from a strict ISO-8601 author date.

    `2026-03-14T02:47:00+08:00` -> 2: the hour the author's own clock
    showed, NOT the UTC hour. No timezone math, no mistakes.
    """
    return int(iso[11:13])


def weekday_of(iso: str) -> int:
    """0=Mon..6=Sun from the date part of the author's ISO date."""
    return date.fromisoformat(iso[:10]).weekday()


def bucket_label(bucket_hours: int) -> List[str]:
    """Window labels like ['00-03', '03-06', ...]; 24 % bucket_hours == 0."""
    if 24 % bucket_hours != 0:
        raise ValueError("bucket-hours must divide 24")
    return ["%02d-%02d" % (h, h + bucket_hours) for h in range(0, 24, bucket_hours)]


def bucket_index(hour: int, bucket_hours: int) -> int:
    return (hour // bucket_hours) if hour < 24 else 23 // bucket_hours


def in_danger_window(hour: int, start: int, end: int) -> bool:
    """True if hour is inside [start, end) treating a wrapping window."""
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def ratio_share(part: int, whole: int) -> float:
    return (part / whole) if whole else 0.0


# ---------------------------------------------------------------------------
# Git plumbing


def run_git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return proc.stdout.decode("utf-8", "replace")


def is_git_repo(repo: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--git-dir"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode == 0


@dataclass
class Commit:
    sha: str
    iso: str            # author date, strict ISO with original tz offset
    author: str
    subject: str
    churn: int = 0      # adds+dels from numstat (binary files skipped)

    @property
    def hour(self) -> int:
        return hour_of(self.iso)

    @property
    def weekday(self) -> int:
        return weekday_of(self.iso)


def load_log(repo: str) -> List[Commit]:
    """One `git log` call: newest-first commits with author ISO dates and
    per-commit churn. Merge commits are excluded everywhere in this tool:
    their timestamps re-state other people's work."""
    raw = run_git(
        repo, "log", "--no-merges", "-M", "--numstat",
        "--format=%x1e%H%x1f%aI%x1f%an%x1f%s",
    )
    commits: List[Commit] = []
    cur: Optional[Commit] = None
    for line in raw.split("\n"):
        if line.startswith(SENTINEL):
            sha, iso, author, subject = line[1:].split(UNIT, 3)
            cur = Commit(sha=sha, iso=iso, author=author, subject=subject)
            commits.append(cur)
        elif cur is not None and re.match(r"^\d+\t\d+\t.", line):
            adds, dels, _path = line.split("\t", 2)
            cur.churn += int(adds) + int(dels)
    return commits


def deleted_lines_by_file(repo: str, sha: str) -> Dict[str, List[int]]:
    """Old-file line numbers removed/changed by commit `sha`.

    Parses `git diff --unified=0 parent sha`: hunk headers carry the old
    ranges. `/dev/null` old side (pure additions) yields nothing — a line
    that never existed cannot be blamed.
    """
    try:
        raw = run_git(repo, "diff", "--unified=0", sha + "^", sha)
    except subprocess.CalledProcessError:
        return {}  # root commit has no parent: nothing to diff against
    return parse_hunks(raw)


def parse_hunks(diff_text: str) -> Dict[str, List[int]]:
    """Pure parser for `git diff --unified=0` output -> {old_path: [lines]}."""
    lines_by_file: Dict[str, List[int]] = {}
    old_path: Optional[str] = None
    for line in diff_text.split("\n"):
        if line.startswith("--- "):
            path = line[4:].split("\t")[0]
            if path == "/dev/null":
                old_path = None
            else:
                old_path = path[2:] if path.startswith("a/") else path
        elif line.startswith("@@ ") and old_path is not None:
            m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+", line)
            if not m:
                continue
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            if count > 0:  # `-l,0` marks a pure insertion point: no old lines
                lines_by_file.setdefault(old_path, []).extend(
                    range(start, start + count)
                )
    return lines_by_file


BLAME_HEADER_RE = re.compile(r"^([0-9a-f]{40}) (\d+) (\d+)(?: (\d+))?$")


def blame_lines(repo: str, rev: str, path: str) -> Dict[int, str]:
    """{line_number: birth_sha} for one file at one revision."""
    try:
        raw = run_git(repo, "blame", "--porcelain", rev, "--", path)
    except subprocess.CalledProcessError:
        return {}
    out: Dict[int, str] = {}
    for line in raw.split("\n"):
        m = BLAME_HEADER_RE.match(line)
        if m:
            out[int(m.group(3))] = m.group(1)
    return out


# ---------------------------------------------------------------------------
# Statistics


@dataclass
class BucketRow:
    window: str
    defect_lines: int
    work_lines: int
    defect_share: float
    work_share: float
    rr: Optional[float]      # None when the window has no work at all
    verdict: str             # DANGER / ok / low-n / -


def verdict_of(rr: Optional[float], defect_lines: int,
               min_bucket: int, danger_rr: float) -> str:
    if rr is None:
        return "-"
    if defect_lines < min_bucket:
        return "low-n"
    return "DANGER" if rr >= danger_rr else "ok"


def bucket_rows(defect_hours: Counter, work_hours: Counter,
                bucket_hours: int, min_bucket: int,
                danger_rr: float) -> List[BucketRow]:
    total_d = sum(defect_hours.values())
    total_w = sum(work_hours.values())
    rows: List[BucketRow] = []
    for i, label in enumerate(bucket_label(bucket_hours)):
        d = sum(defect_hours.get(h, 0) for h in range(i * bucket_hours,
                                                      (i + 1) * bucket_hours))
        w = sum(work_hours.get(h, 0) for h in range(i * bucket_hours,
                                                    (i + 1) * bucket_hours))
        d_share = ratio_share(d, total_d)
        w_share = ratio_share(w, total_w)
        rr = (d_share / w_share) if w_share > 0 else None
        rows.append(BucketRow(
            window=label, defect_lines=d, work_lines=w,
            defect_share=d_share, work_share=w_share, rr=rr,
            verdict=verdict_of(rr, d, min_bucket, danger_rr),
        ))
    return rows


# ---------------------------------------------------------------------------
# Scan: fix commits -> deleted lines -> birth commits -> hour buckets


@dataclass
class ScanResult:
    repo: str
    pattern: str
    commits_scanned: int
    first_date: str
    last_date: str
    fix_commits: int
    fix_skipped: int
    defect_lines: int
    unborn_lines: int            # deleted lines whose birth sha wasn't in the log
    buckets: List[BucketRow] = field(default_factory=list)
    defect_by_hour: Dict[int, int] = field(default_factory=dict)
    authors_of_defects: Dict[str, int] = field(default_factory=dict)
    insufficient: bool = False
    min_total: int = DEFAULT_MIN_TOTAL_LINES
    danger_rr: float = DEFAULT_DANGER_RR
    min_bucket: int = DEFAULT_MIN_BUCKET_LINES

    @property
    def top_hours(self) -> List[Dict[str, object]]:
        ranked = sorted(self.defect_by_hour.items(),
                        key=lambda kv: (-kv[1], kv[0]))[:3]
        return [{"hour": "%02d" % h, "defect_lines": n} for h, n in ranked]

    @property
    def danger_windows(self) -> List[str]:
        return [r.window for r in self.buckets if r.verdict == "DANGER"]


def scan_repo(repo: str, pattern: str = DEFAULT_FIX_PATTERN,
              bucket_hours: int = DEFAULT_BUCKET_HOURS,
              min_bucket: int = DEFAULT_MIN_BUCKET_LINES,
              min_total: int = DEFAULT_MIN_TOTAL_LINES,
              max_fix: int = DEFAULT_MAX_FIX_COMMITS,
              danger_rr: float = DEFAULT_DANGER_RR,
              author: Optional[str] = None) -> ScanResult:
    commits = load_log(repo)
    by_sha = {c.sha: c for c in commits}
    if author:
        commits = [c for c in commits if c.author == author]

    fix_re = re.compile(pattern)
    fixes = [c for c in commits if fix_re.search(c.subject)]
    fix_skipped = max(0, len(fixes) - max_fix)  # log is newest-first: keep newest
    fixes = fixes[:max_fix]

    defect_hours: Counter = Counter()
    defect_authors: Counter = Counter()
    unborn = 0
    blamed: Dict[Tuple[str, str], Dict[int, str]] = {}

    for fix in fixes:
        for old_path, line_nos in sorted(deleted_lines_by_file(repo, fix.sha).items()):
            key = (fix.sha + "^", old_path)
            if key not in blamed:
                blamed[key] = blame_lines(repo, fix.sha + "^", old_path)
            births = blamed[key]
            for ln in line_nos:
                birth_sha = births.get(ln)
                if birth_sha is None or birth_sha not in by_sha:
                    unborn += 1        # pre-history or boundary line: no birth record
                    continue
                birth = by_sha[birth_sha]
                defect_hours[birth.hour] += 1
                defect_authors[birth.author] += 1

    work_hours: Counter = Counter()
    for c in commits:
        work_hours[c.hour] += c.churn

    result = ScanResult(
        repo=repo,
        pattern=pattern,
        commits_scanned=len(commits),
        first_date=commits[-1].iso[:10] if commits else "-",
        last_date=commits[0].iso[:10] if commits else "-",
        fix_commits=len(fixes),
        fix_skipped=fix_skipped,
        defect_lines=sum(defect_hours.values()),
        unborn_lines=unborn,
        authors_of_defects=dict(defect_authors.most_common()),
        min_total=min_total,
        danger_rr=danger_rr,
        min_bucket=min_bucket,
    )
    result.insufficient = result.defect_lines < min_total
    result.buckets = bucket_rows(defect_hours, work_hours, bucket_hours,
                                 min_bucket, danger_rr)
    result.defect_by_hour = dict(defect_hours)
    return result


# ---------------------------------------------------------------------------
# Rendering


BAR_BLOCKS = "▁▂▃▄▅▆▇█"


def spark(counts: List[int], width: int = 24) -> str:
    mx = max(counts) if counts else 0
    if mx == 0:
        return ""
    return "".join(BAR_BLOCKS[min(len(BAR_BLOCKS) - 1,
                                  c * len(BAR_BLOCKS) // (mx + 1))]
                   for c in counts)


def render_scan(res: ScanResult) -> str:
    out = []
    out.append("-- Witching Hour scan: %s " % res.repo)
    out.append("  commits scanned        : %d   (%s .. %s)"
               % (res.commits_scanned, res.first_date, res.last_date))
    out.append("  fix pattern            : %s" % res.pattern)
    out.append("  fix commits matched    : %d%s"
               % (res.fix_commits,
                  "   (%d older skipped for --max-fix-commits)" % res.fix_skipped
                  if res.fix_skipped else ""))
    out.append("  defect lines attributed: %d   (%d unborn/boundary skipped)"
               % (res.defect_lines, res.unborn_lines))
    out.append("")
    if res.insufficient:
        out.append("  ! only %d defect lines attributed (< %d needed)." %
                   (res.defect_lines, res.min_total))
        out.append("  ! This report is anecdote, not statistics. Grow history")
        out.append("  ! or widen --fix-pattern before trusting any verdict below.")
        out.append("")
    out.append("-- Wall-clock windows ---------------------------------------")
    out.append("  window   defect  work     D%     W%     RR   verdict")
    for r in res.buckets:
        rr = "-" if r.rr is None else "%.2f" % r.rr
        out.append("  %s  %6d %6d  %5.1f  %5.1f  %5s   %s"
                   % (r.window, r.defect_lines, r.work_lines,
                      r.defect_share * 100, r.work_share * 100, rr,
                      "! " + r.verdict if r.verdict == "DANGER" else r.verdict))
    out.append("")
    out.append("-- Defect lines by birth hour --------------------------------")
    out.append("  " + spark([res.defect_by_hour.get(h, 0) for h in range(24)]))
    out.append("  " + "".join("^" if in_danger_window(
        h, DEFAULT_DANGER_START, DEFAULT_DANGER_END) else " " for h in range(24)))
    out.append("  " + "%-24s%s" % ("00", "23 witching zone (^)"))
    if res.top_hours:
        out.append("  top birth hours: " + ", ".join(
            "%s:xx %d lines" % (t["hour"], t["defect_lines"])
            for t in res.top_hours))
    if res.authors_of_defects:
        out.append("  authors of the buggy lines: " + ", ".join(
            "%s %d" % (a, n) for a, n in list(res.authors_of_defects.items())[:5]))
    out.append("")
    out.append("  RR = share of defect lines born in the window / share of all")
    out.append("  changed lines from the window. ! DANGER needs RR >= %.1f and"
               % res.danger_rr)
    out.append("  >= %d defect lines." % res.min_bucket)
    if res.danger_windows:
        out.append("")
        out.append("  --> %s: fewer lines, more bugs per line. That is your" %
                   " and ".join(res.danger_windows))
        out.append("  --> witching hour. Correlation, not causation — but a")
        out.append("  --> conversation worth having with the on-call calendar.")
    return "\n".join(out)


def render_rhythm(commits: List[Commit], metric: str = "commits") -> str:
    by_hour: Counter = Counter()
    by_day: Counter = Counter()
    lines_by_day: Counter = Counter()
    for c in commits:
        by_hour[c.hour] += 1 if metric == "commits" else c.churn
        by_day[c.weekday] += 1
        lines_by_day[c.weekday] += c.churn
    unit = "commits" if metric == "commits" else "changed lines"

    out = ["-- Coding clock by wall-clock hour (%s) ---------------" % unit]
    mx = max(by_hour.values()) if by_hour else 0
    for h in range(24):
        n = by_hour.get(h, 0)
        bar = "#" * int(30 * n / mx) if mx else ""
        marker = "  <- witching zone" if in_danger_window(
            h, DEFAULT_DANGER_START, DEFAULT_DANGER_END) and n else ""
        out.append("  %02d │%-30s %6d%s" % (h, bar, n, marker))
    out.append("")
    out.append("-- By weekday ------------------------------------------------")
    for d in range(7):
        out.append("  %s  commits %4d   changed lines %6d"
                   % (WEEKDAYS[d], by_day.get(d, 0), lines_by_day.get(d, 0)))
    weekend = sum(by_day.get(d, 0) for d in (5, 6))
    out.append("")
    out.append("  weekend commits: %d of %d (%.1f%%)"
               % (weekend, sum(by_day.values()) or 1,
                  ratio_share(weekend, sum(by_day.values())) * 100))
    return "\n".join(out)


def render_birth(repo: str, path: str, rev: str = "HEAD",
                 start: int = DEFAULT_DANGER_START,
                 end: int = DEFAULT_DANGER_END,
                 danger_only: bool = False) -> str:
    commits = {c.sha: c for c in load_log(repo)}
    births = blame_lines(repo, rev, path)
    out = ["-- Birth certificate: %s @ %s ------------------------------" % (path, rev)]
    flagged = 0
    shown = 0
    for ln in sorted(births):
        c = commits.get(births[ln])
        if c is None:
            continue
        danger = in_danger_window(c.hour, start, end)
        if danger:
            flagged += 1
        if danger_only and not danger:
            continue
        shown += 1
        out.append("  L%4d  %s %s  %-16s%s"
                   % (ln, c.iso[:10], c.iso[11:16], c.author,
                      "   <- witching hour" if danger else ""))
    out.append("")
    out.append("  %d line(s) shown, %d born inside %02d:00-%02d:00."
               % (shown, flagged, start, end))
    if flagged:
        out.append("  Those lines were written against the body's will.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# JSON serialisation


def scan_json(res: ScanResult) -> str:
    return json.dumps({
        "repo": res.repo,
        "pattern": res.pattern,
        "commits_scanned": res.commits_scanned,
        "range": [res.first_date, res.last_date],
        "fix_commits": res.fix_commits,
        "fix_skipped": res.fix_skipped,
        "defect_lines": res.defect_lines,
        "unborn_lines": res.unborn_lines,
        "insufficient": res.insufficient,
        "buckets": [{
            "window": r.window,
            "defect_lines": r.defect_lines,
            "work_lines": r.work_lines,
            "defect_share": round(r.defect_share, 4),
            "work_share": round(r.work_share, 4),
            "rr": None if r.rr is None else round(r.rr, 3),
            "verdict": r.verdict,
        } for r in res.buckets],
        "danger_windows": res.danger_windows,
        "top_hours": res.top_hours,
        "authors_of_defects": res.authors_of_defects,
    }, ensure_ascii=False, indent=2)


def rhythm_json(commits: List[Commit], metric: str = "commits") -> str:
    by_hour: Counter = Counter()
    by_day: Counter = Counter()
    for c in commits:
        by_hour[c.hour] += 1 if metric == "commits" else c.churn
        by_day[WEEKDAYS[c.weekday]] += 1
    return json.dumps({
        "commits": len(commits),
        "metric": metric,
        "by_hour": {"%02d" % h: by_hour.get(h, 0) for h in range(24)},
        "by_weekday": {d: by_day.get(d, 0) for d in WEEKDAYS},
    }, ensure_ascii=False, indent=2)


def birth_json(repo: str, path: str, rev: str,
               start: int, end: int) -> str:
    commits = {c.sha: c for c in load_log(repo)}
    births = blame_lines(repo, rev, path)
    rows = []
    for ln in sorted(births):
        c = commits.get(births[ln])
        if c is None:
            continue
        rows.append({
            "line": ln,
            "birth": c.iso,
            "author": c.author,
            "danger": in_danger_window(hour_of(c.iso), start, end),
        })
    return json.dumps({
        "path": path, "rev": rev,
        "danger_window": ["%02d:00" % start, "%02d:00" % end],
        "lines": rows,
        "danger_count": sum(1 for r in rows if r["danger"]),
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="witching_hour.py",
        description="危险时刻: when were your bugs actually born?")
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("scan", help="attribute defects to wall-clock windows")
    ps.add_argument("repo", nargs="?", default=".")
    ps.add_argument("--fix-pattern", default=DEFAULT_FIX_PATTERN)
    ps.add_argument("--bucket-hours", type=int, default=DEFAULT_BUCKET_HOURS)
    ps.add_argument("--min-bucket-lines", type=int, default=DEFAULT_MIN_BUCKET_LINES)
    ps.add_argument("--min-total-lines", type=int, default=DEFAULT_MIN_TOTAL_LINES)
    ps.add_argument("--max-fix-commits", type=int, default=DEFAULT_MAX_FIX_COMMITS)
    ps.add_argument("--danger-rr", type=float, default=DEFAULT_DANGER_RR)
    ps.add_argument("--author", default=None)
    ps.add_argument("--format", choices=("text", "json"), default="text")

    pr = sub.add_parser("rhythm", help="the coding clock (no attribution)")
    pr.add_argument("repo", nargs="?", default=".")
    pr.add_argument("--author", default=None)
    pr.add_argument("--metric", choices=("commits", "lines"), default="commits")
    pr.add_argument("--format", choices=("text", "json"), default="text")

    pb = sub.add_parser("birth", help="birth certificate of one file")
    pb.add_argument("repo", nargs="?", default=".")
    pb.add_argument("file")
    pb.add_argument("--rev", default="HEAD")
    pb.add_argument("--danger-start", type=int, default=DEFAULT_DANGER_START)
    pb.add_argument("--danger-end", type=int, default=DEFAULT_DANGER_END)
    pb.add_argument("--danger-only", action="store_true")
    pb.add_argument("--format", choices=("text", "json"), default="text")

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help(sys.stderr)
        return 2

    if not is_git_repo(args.repo):
        sys.stderr.write("not a git repository: %s\n" % args.repo)
        return 3

    if args.cmd == "scan":
        res = scan_repo(
            args.repo, pattern=args.fix_pattern,
            bucket_hours=args.bucket_hours,
            min_bucket=args.min_bucket_lines,
            min_total=args.min_total_lines,
            max_fix=args.max_fix_commits,
            danger_rr=args.danger_rr,
            author=args.author)
        print(scan_json(res) if args.format == "json" else render_scan(res))
    elif args.cmd == "rhythm":
        commits = load_log(args.repo)
        if args.author:
            commits = [c for c in commits if c.author == args.author]
        if args.format == "json":
            print(rhythm_json(commits, args.metric))
        else:
            print(render_rhythm(commits, args.metric))
    elif args.cmd == "birth":
        if args.format == "json":
            print(birth_json(args.repo, args.file, args.rev,
                             args.danger_start, args.danger_end))
        else:
            print(render_birth(args.repo, args.file, args.rev,
                               args.danger_start, args.danger_end,
                               args.danger_only))
    return 0


if __name__ == "__main__":
    sys.exit(main())
