#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""alarm-fatigue — 警报疲劳 / Alarm Fatigue

A flaky test is not a broken test — it is a false alarm. And every false
alarm taxes the only currency a CI suite has: whether people still look
when the light goes red. alarm-fatigue reads the patch trail flaky tests
leave behind in git history ("fix flaky" subjects, skips smuggled into
diffs, retries wired around assertions, test-only adjustment commits) and
turns it into an alarm credit score per test file. A test that never
cried wolf keeps its 100; one that was muted, retried and re-patched
slides into the deaf zone — where its red is background noise, not a fire.

  * audit    — suite-wide alarm credit ledger: per-test patch history,
               credit score and grade, plus the graveyard of removed tests
  * explain  — one test file's full patch timeline with a running credit

Method in one line: `git log --name-status` to find every commit that
touched a test file, classify each touch by its heaviest signal —
mute (skip/xfail added) > focus (.only added) > retry > signal (flaky
vocabulary in the subject) > solo (test-only commit) — and charge it to
that file's credit.

Credit is not blame: fixing a flaky test properly also costs credit,
because the consumers of a red light only remember that it cried wolf.

Zero dependencies: Python 3.8+ standard library + a git binary.
MIT License (c) 2026
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Dict, List, Optional, Set, Tuple

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Vocabulary

SENTINEL = "\x1e"  # between commits in `git log --format`
UNIT = "\x1f"      # between fields inside a commit header

# Signals, heaviest first. The heaviest hit classifies the patch event;
# the others ride along as tags (they inform, they don't double-charge).
SIGNAL_ORDER: Tuple[str, ...] = ("mute", "focus", "retry", "signal", "solo")
PENALTY: Dict[str, int] = {
    "mute": 30,    # skip/xfail added: the alarm stays on the wall, battery gone
    "focus": 25,   # .only/fit added: one alarm armed, every sibling silenced
    "retry": 20,   # retries wired around the assertion instead of fixing it
    "signal": 10,  # flaky vocabulary in the subject: a documented false alarm
    "solo": 5,     # test-only commit: almost certainly tuning the test to pass
}
BURST_PENALTY = 10        # N patches inside a short window and it still flakes
DEFAULT_BURST_WINDOW = 14  # days
DEFAULT_BURST_MIN = 3      # patches inside the window to call it a burst
DEFAULT_MAX_DIFF_COMMITS = 500  # `git show` budget; beyond it, message-only

GRADES: Tuple[Tuple[int, str], ...] = (
    (80, "trusted"),   # every red is a fire
    (60, "shaky"),     # people rerun once before reading
    (40, "habitual"),  # people rerun without reading
    (0, "deaf"),       # nobody looks at this red anymore
)
GRADE_TAGS = {
    "trusted": "OK trusted",
    "shaky": "~ shaky",
    "habitual": "~~ habitual",
    "deaf": "!! DEAF",
}

# Test files by basename. A directory named tests/ is NOT enough: helpers
# (conftest.py, testdata/*, utils) live there and must not be graded.
TEST_FILE_PATTERNS: Tuple[str, ...] = (
    r"^test_.+\.py$",                       r".+_test\.py$",      # python
    r".+_test\.go$",                                              # go
    r"^test_.+\.[ch]$", r".+_test\.[ch]$",                        # c
    r".+_test\.(cc|cpp)$", r"^test_.+\.(cc|cpp)$",                # c++
    r".+Tests?\.java$", r".+Tests?\.kt$",                         # jvm
    r".+\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$",                 # js/ts
    r".+_spec\.(ts|js)$",                                          # js/ts (rspec style)
    r".+_spec\.rb$", r".+_test\.exs$",                            # ruby/elixir
    r".+Tests?\.swift$",                                          # swift
    r"^test_.+\.rs$", r".+_test\.rs$",                            # rust
)

# Flaky vocabulary: the patch subject admits the alarm misfired. Words like
# plain "retry" or "skip" are deliberately absent — they have honest uses
# outside test land; a bare word would smear real work as false alarms.
DEFAULT_SIGNAL_REGEX = (
    r"(?i)"
    r"\bflak(?:y|e|iness)\b"
    r"|\bstabiliz\w+\b"
    r"|\bintermittent\b"
    r"|\bunstable\b"
    r"|\brerun\w*\b"
    r"|\bretr(?:y|ies)\b.*\btest\b"
    r"|\btest\b.*\bretr(?:y|ies)\b"
    r"|\bfix (?:the |this )?test\b"
    r"|\btest fix\b"
    r"|偶现|随机失败|飘了|修测试|重跑"
)

# Diff-level marks: detected on ADDED lines only. Removing a skip is a
# repair (the alarm is re-armed) and must never be charged.
MUTE_LINE_PATTERNS: Tuple[str, ...] = (
    r"@unittest\.skip", r"@pytest\.mark\.skip", r"@pytest\.mark\.xfail",
    r"\bskipTest\s*\(", r"@Disabled\b", r"@Ignore\b", r"\bt\.Skip\s*\(",
    r"\bit\.skip\b", r"\btest\.skip\b", r"\btest\.todo\b",
    r"\bxit\s*\(", r"\bxdescribe\s*\(", r"\bxtest\s*\(",
    r"\bdescribe\.skip\b",
)
FOCUS_LINE_PATTERNS: Tuple[str, ...] = (
    r"\.only\s*\(", r"\bfit\s*\(", r"\bfdescribe\s*\(", r"\bfcontext\s*\(",
    r"focus:\s*true",
)
RETRY_LINE_PATTERNS: Tuple[str, ...] = (
    r"\bflaky\s*\(", r"\bretries\s*[:=]\s*\d", r"@pytest\.mark\.flaky",
    r"@retry\b", r"\bmaxRetries\b", r"\bretryCount\b", r"\brerunFailures\b",
    r"pytest_rerun", r"\.retry\s*\(",
)


# ---------------------------------------------------------------------------
# Small pure helpers


def is_test_path(path: str, extra_globs: List[str] = ()) -> bool:
    """True for files that ARE tests — by basename pattern or user glob."""
    base = os.path.basename(path)
    for pat in TEST_FILE_PATTERNS:
        if re.search(pat, base):
            return True
    for glob in extra_globs:
        if fnmatch.fnmatch(path, glob):
            return True
    return False


def classify_added_lines(added: List[str]) -> Set[str]:
    """Diff marks on added lines. One patch can carry several marks."""
    marks: Set[str] = set()
    for line in added:
        for mark, pats in (("mute", MUTE_LINE_PATTERNS),
                           ("focus", FOCUS_LINE_PATTERNS),
                           ("retry", RETRY_LINE_PATTERNS)):
            if any(re.search(p, line) for p in pats):
                marks.add(mark)
    return marks


def heaviest(hits: Set[str]) -> str:
    """The heaviest hit classifies the event; ties impossible (ordered)."""
    for kind in SIGNAL_ORDER:
        if kind in hits:
            return kind
    raise ValueError("no signal in %r" % (hits,))


def grade_of(credit: int) -> str:
    for floor, name in GRADES:
        if credit >= floor:
            return name
    return "deaf"


def credit_of(event_kinds: List[str], burst: bool) -> int:
    """Start at 100, charge each event once (by kind), burst on top."""
    score = 100 - sum(PENALTY[k] for k in event_kinds)
    if burst:
        score -= BURST_PENALTY
    return max(0, score)


def burst_window(event_days: List[str], window: int,
                 minimum: int) -> Optional[Tuple[str, str]]:
    """Earliest span of `minimum` patches that fit inside `window` days."""
    days = sorted(d[:10] for d in event_days)
    for i, start in enumerate(days):
        end_i = i
        while (end_i < len(days)
               and (date.fromisoformat(days[end_i])
                    - date.fromisoformat(start)).days <= window):
            end_i += 1
        if end_i - i >= minimum:
            return (start, days[end_i - 1])
    return None


def added_lines_of(patch: str) -> List[str]:
    """`+` lines of a unified diff, file headers stripped."""
    out = []
    for line in patch.split("\n"):
        if line.startswith("+++") or line.startswith("+"):
            if not line.startswith("+++"):
                out.append(line[1:])
    return out


# ---------------------------------------------------------------------------
# Git plumbing


def run_git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo] + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return proc.stdout.decode("utf-8", "replace")


def is_git_repo(repo: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--git-dir"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return proc.returncode == 0


@dataclass
class Commit:
    sha: str
    iso: str            # author date, strict ISO with original tz offset
    author: str
    subject: str
    files: List[Tuple[str, str]] = field(default_factory=list)  # (status, path)

    @property
    def day(self) -> str:
        return self.iso[:10]


def load_history(repo: str) -> List[Commit]:
    """All non-merge commits, oldest first, with name-status file lists.

    Merge commits are invisible here on purpose: the patches they merge
    already exist as real commits with real authors and real subjects —
    counting both would double-charge every branch-merged flaky fix.
    """
    try:
        raw = run_git(
            repo, "log", "--no-merges", "--name-status",
            "--format=%x1e%H%x1f%aI%x1f%an%x1f%s",
        )
    except subprocess.CalledProcessError:
        return []  # a repo with no commits yet has no alarms to grade
    commits: List[Commit] = []
    cur: Optional[Commit] = None
    for line in raw.split("\n"):
        if line.startswith(SENTINEL):
            fields = line[1:].split(UNIT, 3)
            while len(fields) < 4:      # empty subject leaves a dangling UNIT
                fields.append("")
            sha, iso, author, subject = fields
            cur = Commit(sha=sha, iso=iso, author=author, subject=subject)
            commits.append(cur)
        elif line.strip() and cur is not None:
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0][:1] in ("R", "C"):
                # rename/copy: the old path dies, the new path is touched
                cur.files.append(("D", parts[1]))
                cur.files.append(("M", parts[2]))
            elif len(parts) >= 2:
                cur.files.append((parts[0][0], parts[1]))
    commits.reverse()  # oldest first: timelines and running credits read forward
    return commits


# ---------------------------------------------------------------------------
# Analysis


@dataclass
class PatchEvent:
    sha: str
    iso: str
    author: str
    subject: str
    kind: str                       # heaviest signal
    tags: List[str]                 # every signal that fired, heaviest first

    @property
    def day(self) -> str:
        return self.iso[:10]


@dataclass
class FileReport:
    path: str
    events: List[PatchEvent] = field(default_factory=list)
    burst: Optional[Tuple[str, str]] = None   # (first, last) day of the span
    deleted: Optional[str] = None             # day of death (last D status)
    last_seen: Optional[str] = None           # last day any commit touched it

    @property
    def credit(self) -> int:
        return credit_of([e.kind for e in self.events],
                         self.burst is not None)

    @property
    def grade(self) -> str:
        return grade_of(self.credit)

    @property
    def signal_counts(self) -> Counter:
        return Counter(e.kind for e in self.events)

    @property
    def first_patch(self) -> Optional[str]:
        return self.events[0].day if self.events else None

    @property
    def last_patch(self) -> Optional[str]:
        return self.events[-1].day if self.events else None


@dataclass
class AuditResult:
    repo: str
    commits_scanned: int
    first_day: Optional[str]
    last_day: Optional[str]
    files: List[FileReport]                 # alive tests, worst credit first
    graveyard: List[FileReport]             # tests deleted before our eyes
    diff_budget_hit: bool                   # diff scan was capped
    max_diff_commits: int = DEFAULT_MAX_DIFF_COMMITS

    @property
    def alive_files(self) -> List[FileReport]:
        return self.files

    def to_json(self) -> dict:
        alive = self.files
        patched = [f for f in alive if f.events]
        deaf = [f for f in alive if f.grade == "deaf"]
        return {
            "repo": self.repo,
            "window": {"first": self.first_day, "last": self.last_day,
                       "commits": self.commits_scanned},
            "suite": {
                "test_files": len(alive),
                "patched": len(patched),
                "patch_ratio": round(len(patched) / len(alive), 3) if alive else 0.0,
                "total_patch_events": sum(len(f.events) for f in alive),
                "median_credit": (median([f.credit for f in alive])
                                  if alive else None),
                "deaf": len(deaf),
            },
            "files": [{
                "path": f.path,
                "credit": f.credit,
                "grade": f.grade,
                "patches": len(f.events),
                "burst": bool(f.burst),
                "signals": dict(sorted(f.signal_counts.items())),
                "first_patch": f.first_patch,
                "last_patch": f.last_patch,
            } for f in alive],
            "graveyard": [{
                "path": f.path,
                "deleted": f.deleted,
                "credit_at_death": f.credit,
                "patches_before_death": len(f.events),
            } for f in self.graveyard],
            "notes": (["diff scan capped at %d commits: mute/focus/retry "
                       "beyond the cap went undetected"
                       % self.max_diff_commits]
                      if self.diff_budget_hit else []),
        }


def analyze(repo: str, signal_regex: str = DEFAULT_SIGNAL_REGEX,
            test_globs: Optional[List[str]] = None,
            burst_window_days: int = DEFAULT_BURST_WINDOW,
            burst_min: int = DEFAULT_BURST_MIN,
            max_diff_commits: int = DEFAULT_MAX_DIFF_COMMITS,
            since: Optional[str] = None,
            until: Optional[str] = None) -> AuditResult:
    signal_re = re.compile(signal_regex)
    test_globs = test_globs or []
    commits = load_history(repo)
    if not commits:
        return AuditResult(repo=repo, commits_scanned=0, first_day=None,
                           last_day=None, files=[], graveyard=[],
                           diff_budget_hit=False,
                           max_diff_commits=max_diff_commits)

    # since/until filter PATCHES, never discovery: a file keeps its row
    # (and its life dates) even when its repairs fall outside the window —
    # that is exactly how a stale repair "repays" into credit.
    def day_in_window(day: str) -> bool:
        if since and day < since:
            return False
        if until and day > until:
            return False
        return True

    # Diff inspection is the only expensive step: budget it, newest first.
    touching = [c for c in commits if day_in_window(c.day)
                and any(is_test_path(p, test_globs) for _, p in c.files)]
    keep = max(0, len(touching) - max_diff_commits)
    diffable = {c.sha for c in touching[keep:]}
    budget_hit = len(touching) > max_diff_commits

    reports: Dict[str, FileReport] = {}
    for c in commits:  # oldest first: the timeline reads forward
        test_paths = {p for _, p in c.files if is_test_path(p, test_globs)}
        if not test_paths:
            continue
        solo = all(is_test_path(p, test_globs) for _, p in c.files)
        msg_hit = "signal" if signal_re.search(c.subject) else None
        for path in sorted(test_paths):
            report = reports.setdefault(path, FileReport(path=path))
            report.last_seen = c.day
            status = {s for s, p in c.files if p == path}
            if "D" in status and not ({"M", "A"} & status):
                report.deleted = c.day  # last word was a deletion
            if "A" in status:
                continue  # a test being BORN is not a patch: TDD is clean
            if "M" not in status and not ({"R", "C"} & status):
                continue
            if not day_in_window(c.day):
                continue  # birth/death still booked; patches outside decay
            hits: Set[str] = set()
            if msg_hit:
                hits.add("signal")
            if solo:
                hits.add("solo")
            if c.sha in diffable:
                patch = run_git(repo, "show", "--format=", "--unified=0",
                                c.sha, "--", path)
                hits |= classify_added_lines(added_lines_of(patch))
            if hits:
                report.events.append(PatchEvent(
                    sha=c.sha, iso=c.iso, author=c.author, subject=c.subject,
                    kind=heaviest(hits),
                    tags=[k for k in SIGNAL_ORDER if k in hits],
                ))

    for report in reports.values():
        # Deletions can hide inside merge commits (folder reorganisations),
        # which this pass never opens: any "alive" file missing from the
        # working tree is a vanished alarm and belongs in the graveyard.
        if report.deleted is None and not os.path.exists(
                os.path.join(repo, report.path)):
            report.deleted = report.last_seen or report.first_patch
    for report in reports.values():
        if report.events and not report.deleted:
            report.burst = burst_window([e.iso for e in report.events],
                                        burst_window_days, burst_min)

    alive = sorted((r for r in reports.values() if not r.deleted),
                   key=lambda r: (r.credit, -len(r.events), r.path))
    dead = sorted((r for r in reports.values() if r.deleted),
                  key=lambda r: r.deleted or "")
    window_commits = [c for c in commits if day_in_window(c.day)]
    return AuditResult(
        repo=repo, commits_scanned=len(window_commits),
        first_day=window_commits[0].day if window_commits else None,
        last_day=window_commits[-1].day if window_commits else None,
        files=alive, graveyard=dead, diff_budget_hit=budget_hit,
        max_diff_commits=max_diff_commits,
    )


# ---------------------------------------------------------------------------
# Reports


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


def render_audit(result: AuditResult, top: int = 15) -> str:
    suite = result.to_json()["suite"]
    lines = []
    lines.append("-- Alarm Fatigue audit: %s" % result.repo)
    lines.append("  window                 : %s .. %s"
                 % (result.first_day or "-", result.last_day or "-"))
    lines.append("  commits scanned        : %d (non-merge)"
                 % result.commits_scanned)
    lines.append("  test files alive       : %d" % suite["test_files"])
    lines.append("  patched at least once  : %d (%.1f%%)"
                 % (suite["patched"], 100.0 * suite["patch_ratio"]))
    lines.append("  total patch events     : %d"
                 % suite["total_patch_events"])
    if suite["median_credit"] is not None:
        lines.append("  suite alarm credit     : %d (median of alive tests)"
                     % suite["median_credit"])
    if suite["deaf"]:
        lines.append("  deaf alarms            : %d   <- red, but nobody looks"
                     % suite["deaf"])
    for note in result.to_json()["notes"]:
        lines.append("  ! %s" % note)
    lines.append("")
    lines.append("  credit: 100 every red is a fire · <40 nobody believes "
                 "the red anymore")
    lines.append("")

    shown = result.files[:top]
    if shown:
        width = max([22] + [len(f.path) for f in shown])
        lines.append("  %-*s  %6s  %-11s  %7s  %-10s  %s"
                     % (width, "file", "credit", "grade", "patches",
                        "last", "signals"))
        for f in shown:
            counts = f.signal_counts
            sig = " · ".join(
                ["%s x%d" % (k, counts[k]) for k in SIGNAL_ORDER if k in counts]
                + (["burst"] if f.burst else [])) or "-"
            lines.append("  %-*s  %6d  %-11s  %7d  %-10s  %s"
                         % (width, f.path, f.credit, GRADE_TAGS[f.grade],
                            len(f.events), f.last_patch or "-", sig))
        hidden = len(result.files) - len(shown)
        if hidden > 0:
            lines.append("  … and %d more (raise --top)" % hidden)
    else:
        lines.append("  (no test files seen — nothing to grade)")

    if result.graveyard:
        lines.append("")
        lines.append("  graveyard (alarms removed, not fixed):")
        for f in result.graveyard:
            lines.append("    %-40s  deleted %s · credit at death %d"
                         % (_clip(f.path, 40), f.deleted, f.credit))
    lines.append("")
    if suite["deaf"]:
        lines.append("  %d alarm(s) in the deaf zone: when they burn for "
                     "real, nobody will look." % suite["deaf"])
    return "\n".join(lines)


def render_explain(report: FileReport, repo: str,
                   burst_min: int = DEFAULT_BURST_MIN,
                   burst_window_days: int = DEFAULT_BURST_WINDOW) -> str:
    lines = []
    lines.append("-- Alarm Fatigue explain: %s (%s)"
                 % (report.path, repo))
    for idx, e in enumerate(timeline_rows(report, burst_min,
                                          burst_window_days)):
        if e["kind"] == "burst":
            lines.append("  * burst: %d patches in the %dd window (%s .. %s)"
                         "  -%d  -> %d"
                         % (burst_min, burst_window_days,
                            report.burst[0], report.burst[1],
                            e["penalty"], e["running_credit"]))
            continue
        tags = " + ".join(e["tags"])
        lines.append("  %s  %-12s %s  %-34s  %-11s -%d  -> %d"
                     % (e["date"], _clip(e["author"], 12), e["sha"][:7],
                        _clip(e["subject"], 34), tags, e["penalty"],
                        e["running_credit"]))
    if not report.events:
        lines.append("  (never patched — this alarm never cried wolf)")
    lines.append("")
    if report.deleted:
        lines.append("  final: credit %d · deleted %s · %d patch attempt(s) "
                     "before removal" % (report.credit, report.deleted,
                                         len(report.events)))
    else:
        tails = {
            "deaf": "%d attempt(s) later, nobody believes this red anymore",
            "habitual": "%d attempt(s) and counting — reruns without reading",
            "shaky": "%d attempt(s) — rerun once before believing it",
            "trusted": "%d attempt(s), quiet since — the alarm mostly holds",
        }
        lines.append("  final: credit %d · %s · first patched %s · %s"
                     % (report.credit, report.grade.upper(),
                        report.first_patch or "-",
                        tails[report.grade] % len(report.events)))
    return "\n".join(lines)


def timeline_rows(report: FileReport, burst_min: int,
                  burst_window_days: int) -> List[dict]:
    """Timeline rows with a running credit, burst charged right after the
    `burst_min`-th patch (matches the text rendering; totals always land
    on report.credit)."""
    rows: List[dict] = []
    running = 100
    burst_shown = False
    for idx, e in enumerate(report.events):
        if report.burst and not burst_shown and idx + 1 >= burst_min:
            running -= BURST_PENALTY
            burst_shown = True
            rows.append({"kind": "burst", "penalty": BURST_PENALTY,
                         "running_credit": running})
        running -= PENALTY[e.kind]
        rows.append({
            "kind": e.kind, "date": e.day, "author": e.author,
            "sha": e.sha, "subject": e.subject, "tags": e.tags,
            "penalty": PENALTY[e.kind], "running_credit": running,
        })
    return rows


# ---------------------------------------------------------------------------
# CLI


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="alarm_fatigue.py",
        description="Alarm Fatigue: the alarm credit ledger of a test suite.",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_audit = sub.add_parser(
        "audit", help="suite-wide alarm credit ledger")
    p_audit.add_argument("repo", nargs="?", default=".",
                         help="git repository to audit (default: cwd)")
    _common(p_audit)
    p_audit.add_argument("--top", type=int, default=15,
                         help="rows to show in the table (default 15)")
    p_audit.add_argument("--fail-under", type=int, default=None, metavar="CREDIT",
                         help="exit 4 if suite median credit < CREDIT")

    p_explain = sub.add_parser(
        "explain", help="one test file's patch timeline")
    p_explain.add_argument("file", help="test file path inside the repo")
    p_explain.add_argument("repo", nargs="?", default=".",
                           help="git repository (default: cwd)")
    _common(p_explain)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_usage(sys.stderr)
        return 2
    if not is_git_repo(args.repo):
        print("alarm-fatigue: not a git repository: %s" % args.repo,
              file=sys.stderr)
        return 3

    if args.cmd == "audit":
        result = analyze(
            args.repo, signal_regex=args.signal_regex,
            test_globs=args.test_glob, burst_window_days=args.burst_window,
            burst_min=args.burst_min, max_diff_commits=args.max_diff_commits,
            since=args.since, until=args.until)
        if args.format == "json":
            print(json.dumps(result.to_json(), indent=2, ensure_ascii=False))
        else:
            print(render_audit(result, top=args.top))
        if args.fail_under is not None:
            m = result.to_json()["suite"]["median_credit"]
            if m is None or m < args.fail_under:
                print("alarm-fatigue: suite median credit %s < %d"
                      % (m, args.fail_under), file=sys.stderr)
                return 4
        return 0

    # explain
    result = analyze(
        args.repo, signal_regex=args.signal_regex,
        test_globs=args.test_glob, burst_window_days=args.burst_window,
        burst_min=args.burst_min, max_diff_commits=args.max_diff_commits,
        since=args.since, until=args.until)
    target = next((f for f in result.files + result.graveyard
                   if f.path == args.file
                   or f.path.endswith("/" + args.file)), None)
    if target is None:
        print("alarm-fatigue: no history for test file: %s" % args.file,
              file=sys.stderr)
        return 3
    if args.format == "json":
        data = result.to_json()
        data["file"] = target.path
        data["timeline"] = timeline_rows(target, args.burst_min,
                                         args.burst_window)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(render_explain(target, args.repo, burst_min=args.burst_min,
                             burst_window_days=args.burst_window))
    return 0


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                   help="only count patches on/after this author date")
    p.add_argument("--until", default=None, metavar="YYYY-MM-DD",
                   help="only count patches on/before this author date")
    p.add_argument("--test-glob", action="append", default=[],
                   metavar="GLOB",
                   help="extra test-file glob (repeatable), e.g. 'qa/*.py'")
    p.add_argument("--signal-regex", default=DEFAULT_SIGNAL_REGEX,
                   help="regex of flaky vocabulary in subjects")
    p.add_argument("--burst-window", type=int, default=DEFAULT_BURST_WINDOW,
                   help="days a patch burst may span (default %d)"
                        % DEFAULT_BURST_WINDOW)
    p.add_argument("--burst-min", type=int, default=DEFAULT_BURST_MIN,
                   help="patches inside the window to call a burst (default %d)"
                        % DEFAULT_BURST_MIN)
    p.add_argument("--max-diff-commits", type=int,
                   default=DEFAULT_MAX_DIFF_COMMITS,
                   help="commits to diff-scan, newest first (default %d)"
                        % DEFAULT_MAX_DIFF_COMMITS)
    p.add_argument("--format", choices=("text", "json"), default="text")


if __name__ == "__main__":
    sys.exit(main())
