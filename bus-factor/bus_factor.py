#!/usr/bin/env python3
"""
bus-factor · 知识单点风险账本
==============================

Measure how concentrated the knowledge of your codebase is — file by file,
module by module — directly from git history.

    WHO actually knows this file? What happens if they leave tomorrow?

Core metrics (deterministic, recomputable from `git log --numstat`):

  * share       per-author fraction of added lines (co-authors included)
  * TF          truck factor: fewest authors whose shares sum to >= 50%
  * guardian    the single author holding >= 80% of a file (or of a module)
  * risk        RED  = TF 1 file with real size (knowledge lives in ONE head)
                AMBER= TF 2, GREEN = TF >= 3
  * blast radius  what breaks, in files and lines, if one person leaves

Zero dependencies: Python 3.8+ standard library + the `git` binary.
Report output is in English; this doc block and the repo docs are bilingual.

Usage:
    python3 bus_factor.py scan                      # repo-level risk report
    python3 bus_factor.py scan --format json        # machine-readable
    python3 bus_factor.py file src/auth.py          # one file, all authors
    python3 bus_factor.py module src/billing        # directory aggregate
    python3 bus_factor.py guardians                 # who solely guards what
    python3 bus_factor.py radius "alice"            # simulate alice leaving
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Constants

GUARDIAN_SHARE = 0.80          # a single author holding >= 80% "solely guards"
CRITICAL_SHARE = 0.50          # >= 50% share makes you the critical author
TF_THRESHOLD = 0.50            # truck-factor coverage rule (Avelino-style)
DEFAULT_MIN_LINES = 30         # files below this size are excluded from risk

# Commit authors matching these substrings are bots and are ignored by
# default (pass --include-bots to count them anyway).
BOT_MARKERS = (
    "[bot]", "dependabot", "renovate", "greenkeeper", "codecov",
    "github-actions", "semantic-release", "copilot", "gerrit",
    "noreply@github.com",
)

FIELD_SEP = "\x1f"             # unit separator between commit fields
RECORD_SEP = "\x1e"            # record separator between commits
GIT_LOG_FORMAT = RECORD_SEP + FIELD_SEP.join(("%H", "%an", "%ae", "%aI", "%B"))

NUMSTAT_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t(.+)$")
COAUTHOR_RE = re.compile(r"^Co-Authored-By:\s*(.+?)\s*<([^>]+)>\s*$", re.M)

RISK_RED = "RED"
RISK_AMBER = "AMBER"
RISK_GREEN = "GREEN"

# ---------------------------------------------------------------------------
# Data model


@dataclass
class Commit:
    hash: str
    name: str
    email: str
    date: str                      # ISO-8601 author date
    body: str                      # full message (subject + body)
    files: List[Tuple[int, int, str]] = field(default_factory=list)
    # files: (added_lines_or_-1, deleted_lines_or_-1, path)
    # -1 means binary ("-" in numstat), 0 lines counted.


@dataclass
class FileStat:
    path: str
    added: Counter = field(default_factory=Counter)    # author key -> lines
    touches: Counter = field(default_factory=Counter)  # author key -> commits
    lines: int = 0                                    # current file size

    @property
    def total_added(self) -> int:
        return sum(self.added.values())

    @property
    def n_authors(self) -> int:
        return len(self.added)


@dataclass
class Author:
    key: str                                   # normalized key (email lower)
    display: str                               # most common name variant
    emails: set = field(default_factory=set)


class AuthorRegistry:
    """Normalizes git identities: one key per email (lower-cased)."""

    def __init__(self) -> None:
        self._authors: Dict[str, Author] = {}
        self._names: Dict[str, Counter] = {}

    def key_of(self, name: str, email: str) -> str:
        return (email or name).strip().lower()

    def register(self, name: str, email: str) -> str:
        key = self.key_of(name, email)
        if key not in self._authors:
            self._authors[key] = Author(key=key, display=name.strip())
            self._names[key] = Counter()
        if name.strip():
            self._names[key][name.strip()] += 1
        if email.strip():
            self._authors[key].emails.add(email.strip().lower())
        return key

    def resolve(self, query: str) -> Optional[str]:
        """Map a CLI author query to a key, in three passes:
        exact key/name, then substring in the email (so a surname like
        'chen' hits chen@x.dev before any 'Alice Chen' display name),
        then substring in the display name."""
        q = query.strip().lower()
        for key, author in self._authors.items():
            if q == key or q == author.display.lower():
                return key
        for key in self._authors:
            if q in key:
                return key
        for key, author in self._authors.items():
            if q in author.display.lower():
                return key
        return None

    def display(self, key: str) -> str:
        author = self._authors.get(key)
        if not author:
            return key
        counts = self._names.get(key)
        if counts:
            return counts.most_common(1)[0][0]
        return author.display

    def keys(self) -> List[str]:
        return sorted(self._authors)


def is_bot(name: str, email: str) -> bool:
    blob = "{0} {1}".format(name, email).lower()
    return any(marker in blob for marker in BOT_MARKERS)


# ---------------------------------------------------------------------------
# git plumbing

def run_git(args: List[str], cwd: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false"] + args,
        cwd=cwd, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("git {0} failed: {1}".format(
            " ".join(args[:2]), proc.stderr.strip()))
    return proc.stdout


def git_repo_root(path: str) -> Optional[str]:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=path,
        capture_output=True, text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def git_current_branch(path: str) -> str:
    try:
        return run_git(["rev-parse", "--abbrev-ref", "HEAD"], path).strip()
    except RuntimeError:
        return "?"


def git_log_commits(path: str, since: Optional[str] = None,
                    include_merges: bool = False) -> List[Commit]:
    args = ["log", "--numstat", "--format=" + GIT_LOG_FORMAT]
    if not include_merges:
        args.append("--no-merges")
    if since:
        args.append("--since=" + since)
    out = run_git(args, path)
    return parse_git_log(out)


def git_live_files(path: str) -> List[str]:
    return [f for f in run_git(["ls-files"], path).splitlines() if f]


def git_rename_map(path: str) -> Dict[str, str]:
    """old_path -> new_path across all rename commits (git mv history).

    Without this, `git mv src/lib.py src/v2/lib.py` orphans the file's
    pre-move history: the old path no longer matches a live file and the
    knowledge vanishes. Applied transitively in resolve_path()."""
    out = run_git(["log", "-M", "--diff-filter=R", "--name-status",
                   "--format=" + RECORD_SEP + "%H"], path)
    mapping: Dict[str, str] = {}
    for record in out.split(RECORD_SEP):
        for line in record.splitlines():
            if line.startswith("R"):
                parts = line.split("\t")
                if len(parts) == 3:
                    mapping[parts[1].strip()] = parts[2].strip()
    return mapping


def resolve_path(path: str, renames: Dict[str, str]) -> str:
    """Follow the rename chain to a file's current (final) path."""
    seen = set()
    while path in renames and path not in seen:
        seen.add(path)
        path = renames[path]
    return path


# ---------------------------------------------------------------------------
# Parsing


def expand_rename(path: str) -> str:
    """Normalize a numstat path: `src/{old => new}.py` -> `src/new.py`,
    `old.py => new.py` -> `new.py`."""
    if "{" in path and "}" in path:
        pre, rest = path.split("{", 1)
        mid, post = rest.split("}", 1)
        if " => " in mid:
            mid = mid.split(" => ", 1)[1]
        return pre + mid + post
    if " => " in path:
        return path.rsplit(" => ", 1)[1]
    return path


def parse_git_log(text: str) -> List[Commit]:
    """Parse `git log --numstat --format=<GIT_LOG_FORMAT>` output.
    Record separator \\x1e precedes each commit; fields split by \\x1f;
    numstat lines follow the message body."""
    commits: List[Commit] = []
    # Split on record separator; first chunk before the first sep is empty.
    for record in text.split(RECORD_SEP):
        if not record.strip("\n"):
            continue
        parts = record.split(FIELD_SEP, 4)
        if len(parts) != 5:
            continue
        commit = Commit(hash=parts[0], name=parts[1], email=parts[2],
                        date=parts[3], body=parts[4])
        for line in commit.body.splitlines()[1:]:
            m = NUMSTAT_RE.match(line)
            if m:
                added_s, _deleted_s, path = m.groups()
                added = -1 if added_s == "-" else int(added_s)
                commit.files.append((added, -1, expand_rename(path.strip())))
        # keep the message text but drop trailing numstat noise for coauthor scan
        commits.append(commit)
    return commits


def commit_message_body(commit: Commit) -> str:
    """The commit message with numstat lines stripped (for coauthor scan)."""
    lines = commit.body.splitlines()
    kept = [ln for ln in lines if not NUMSTAT_RE.match(ln)]
    return "\n".join(kept)


def count_file_lines(abs_path) -> int:
    try:
        with open(abs_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return 0
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


# ---------------------------------------------------------------------------
# Metric core (pure functions — the part tests can pin down exactly)


def shares(added: Dict[str, int]) -> Dict[str, float]:
    total = sum(added.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in added.items() if v > 0}


def truck_factor(share: Dict[str, float],
                 threshold: float = TF_THRESHOLD) -> int:
    """Fewest authors whose cumulative share reaches `threshold`.
    Empty contribution -> 0."""
    if not share:
        return 0
    cum = 0.0
    for rank, s in enumerate(sorted(share.values(), reverse=True), start=1):
        cum += s
        if cum >= threshold - 1e-9:
            return rank
    return len(share)  # float rounding guard


def hhi(share: Dict[str, float]) -> float:
    """Herfindahl-Hirschman concentration: sum of squared shares, 0..1."""
    return sum(s * s for s in share.values())


def effective_authors(share: Dict[str, float]) -> float:
    """1 / HHI — 'how many full authors does this knowledge equal'."""
    h = hhi(share)
    return 1.0 / h if h > 0 else 0.0


def guardian_of(share: Dict[str, float],
                threshold: float = GUARDIAN_SHARE) -> Optional[str]:
    """The single author holding >= threshold of a file, if any."""
    if not share:
        return None
    key, top = sorted(share.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return key if top >= threshold - 1e-9 else None


def critical_authors(share: Dict[str, float],
                     threshold: float = CRITICAL_SHARE) -> List[str]:
    """Authors holding >= 50% each — losing any of them hurts coverage."""
    return sorted(k for k, s in share.items() if s >= threshold - 1e-9)


def risk_level(tf: int) -> str:
    if tf <= 1:
        return RISK_RED
    if tf == 2:
        return RISK_AMBER
    return RISK_GREEN


# ---------------------------------------------------------------------------
# Collection


@dataclass
class Options:
    repo: str = "."
    window_days: Optional[int] = None   # e.g. 365 -> only last year of commits
    as_of: date = None                  # pinned "today" (tests / reports)
    min_lines: int = DEFAULT_MIN_LINES
    include_bots: bool = False
    use_coauthored: bool = True
    include_deleted: bool = False

    def since_arg(self) -> Optional[str]:
        if not self.window_days:
            return None
        base = self.as_of or date.today()
        return (base - timedelta(days=self.window_days)).isoformat()


class RepoStats:
    def __init__(self, root: str, branch: str, commits_scanned: int,
                 live: List[str], files: Dict[str, FileStat],
                 registry: AuthorRegistry, bots_ignored: int) -> None:
        self.root = root
        self.branch = branch
        self.commits_scanned = commits_scanned
        self.live = live
        self.files = files                      # path -> FileStat (live only)
        self.registry = registry
        self.bots_ignored = bots_ignored

    # -- views ----------------------------------------------------------

    def measured(self, min_lines: int) -> List[FileStat]:
        return [fs for fs in self.files.values()
                if fs.lines >= min_lines and fs.total_added > 0]

    def author_keys(self, include_bots: bool, min_lines: int) -> List[str]:
        keys = set()
        for fs in self.measured(min_lines):
            keys.update(fs.added)
        return sorted(keys)

    def risk_files(self, min_lines: int) -> List[Tuple[str, Dict[str, float], str]]:
        """[(FileStat, shares, risk)] for measured files, risk-sorted."""
        rows = []
        for fs in self.measured(min_lines):
            sh = shares(fs.added)
            rows.append((fs, sh, risk_level(truck_factor(sh))))
        order = {RISK_RED: 0, RISK_AMBER: 1, RISK_GREEN: 2}
        rows.sort(key=lambda r: (order[r[2]], -r[0].lines, r[0].path))
        return rows

    def guardians(self, min_lines: int) -> Dict[str, List[FileStat]]:
        """author key -> files they solely guard (>= 80% share)."""
        out: Dict[str, List[FileStat]] = {}
        for fs in self.measured(min_lines):
            g = guardian_of(shares(fs.added))
            if g:
                out.setdefault(g, []).append(fs)
        for fl in out.values():
            fl.sort(key=lambda f: (-f.lines, f.path))
        return out

    def blast_radius(self, author_key: str) -> Dict[str, object]:
        """Consequence if one author leaves tomorrow, over measured files."""
        critical, guarded, handoff = [], [], []
        for fs in self.files.values():
            sh = shares(fs.added)
            if author_key not in sh:
                continue
            if sh[author_key] >= GUARDIAN_SHARE - 1e-9:
                guarded.append(fs)
                if fs.n_authors == 1:
                    handoff.append(fs)
            if sh[author_key] >= CRITICAL_SHARE - 1e-9:
                critical.append(fs)
        info = lambda fl: {"files": len(fl), "lines": sum(f.lines for f in fl)}  # noqa: E731
        return {
            "author": author_key,
            "critical": info(critical),
            "guarded": info(guarded),
            "handoff": info(handoff),   # guarded AND no second author at all
            "critical_files": [f.path for f in
                               sorted(critical, key=lambda f: -f.lines)],
            "guarded_files": [f.path for f in
                              sorted(guarded, key=lambda f: -f.lines)],
            "handoff_files": [f.path for f in
                              sorted(handoff, key=lambda f: -f.lines)],
        }


def collect(opts: Options) -> RepoStats:
    root = git_repo_root(opts.repo)
    if root is None:
        raise RuntimeError("not a git repository: {0}".format(opts.repo))

    commits = git_log_commits(root, since=opts.since_arg())
    live = git_live_files(root)
    live_set = set(live)
    renames = git_rename_map(root)

    registry = AuthorRegistry()
    files: Dict[str, FileStat] = {}
    bots_ignored = 0
    seen_bots = set()

    for commit in commits:
        if is_bot(commit.name, commit.email):
            bots_ignored += 1
            seen_bots.add(registry.key_of(commit.name, commit.email))
            if not opts.include_bots:
                continue
        authors = [registry.register(commit.name, commit.email)]
        if opts.use_coauthored:
            for name, email in COAUTHOR_RE.findall(commit_message_body(commit)):
                if is_bot(name, email):
                    continue
                authors.append(registry.register(name, email))
        # order-stable dedup: set() iteration varies with PYTHONHASHSEED,
        # which would make ties in reports differ across processes
        uniq = []
        for ak in authors:
            if ak not in uniq:
                uniq.append(ak)
        for added, _deleted, path in commit.files:
            path = resolve_path(expand_rename(path), renames)
            if not opts.include_deleted and path not in live_set:
                continue
            fs = files.setdefault(path, FileStat(path=path))
            for ak in uniq:
                fs.touches[ak] += 1
                if added > 0:               # -1 = binary, count as touch only
                    fs.added[ak] += added

    if opts.include_bots:
        bots_ignored = len(seen_bots)

    for path in files:
        if path in live_set:
            files[path].lines = count_file_lines(os.path.join(root, path))

    branch = git_current_branch(root)
    return RepoStats(root=root, branch=branch, commits_scanned=len(commits),
                     live=live, files=files, registry=registry,
                     bots_ignored=bots_ignored)


# ---------------------------------------------------------------------------
# Rendering

def fmt_pct(x: float) -> str:
    return "{0:.0f}%".format(x * 100)


def fmt_lines(n: int) -> str:
    return "{0:,}".format(n)


def author_table_line(fs: FileStat, sh: Dict[str, float], reg: AuthorRegistry,
                      max_authors: int = 3) -> str:
    ranked = sorted(sh.items(), key=lambda kv: (-kv[1], kv[0]))[:max_authors]
    parts = ["{0} {1}".format(reg.display(k), fmt_pct(v)) for k, v in ranked]
    extra = len(sh) - len(parts)
    if extra > 0:
        parts.append("+{0}".format(extra))
    return ", ".join(parts)


def scan_report_text(stats: RepoStats, opts: Options, top: int = 10) -> str:
    reg = stats.registry
    rows = stats.risk_files(opts.min_lines)
    counts = {RISK_RED: 0, RISK_AMBER: 0, RISK_GREEN: 0}
    line_sum = {RISK_RED: 0, RISK_AMBER: 0, RISK_GREEN: 0}
    for fs, _sh, risk in rows:
        counts[risk] += 1
        line_sum[risk] += fs.lines
    measured_lines = sum(fs.lines for fs in stats.measured(opts.min_lines))
    humans = stats.author_keys(opts.include_bots, opts.min_lines)

    out = []
    out.append("bus-factor v{0} — knowledge concentration report".format(
        __version__))
    out.append("Repo    : {0} (branch {1})".format(stats.root, stats.branch))
    window = ("last {0} days".format(opts.window_days)
              if opts.window_days else "all history")
    out.append("Window  : {0} · {1} commits · as of {2}".format(
        window, stats.commits_scanned,
        (opts.as_of or date.today()).isoformat()))
    out.append("Files   : {0} tracked · {1} measured (>= {2} lines)".format(
        len(stats.live), len(rows), opts.min_lines))
    out.append("Authors : {0}{1}".format(
        len(humans),
        " ({0} bot commits ignored)".format(stats.bots_ignored)
        if stats.bots_ignored and not opts.include_bots else ""))
    out.append("")

    out.append("-- Risk --------------------------------------------------")
    bar = lambda n: "#" * min(n, 30)  # noqa: E731
    for risk, label in ((RISK_RED, "single-owner knowledge"),
                        (RISK_AMBER, "two authors"),
                        (RISK_GREEN, "healthy spread")):
        out.append("  {0:<6} {1:<5} {2:>7} lines  {3:>3} {4}".format(
            risk, bar(counts[risk]), fmt_lines(line_sum[risk]),
            counts[risk], label))
    red_pct = (line_sum[RISK_RED] / measured_lines * 100
               if measured_lines else 0.0)
    out.append("  --> {0:.0f}% of measured lines are RED "
               "(knowledge in exactly one head)".format(red_pct))
    out.append("")

    guards = stats.guardians(opts.min_lines)
    if guards:
        out.append("-- Sole guardians (>= {0} share) ".format(
            fmt_pct(GUARDIAN_SHARE)).ljust(58, "-"))
        ranked = sorted(guards.items(),
                        key=lambda kv: -sum(f.lines for f in kv[1]))
        for key, fl in ranked[:top]:
            total = sum(f.lines for f in fl)
            names = ", ".join(f.path for f in fl[:3])
            more = "" if len(fl) <= 3 else ", +{0} more".format(len(fl) - 3)
            out.append("  {0:<18} {1:>4} files {2:>8} lines".format(
                reg.display(key), len(fl), fmt_lines(total)))
            out.append("      {0}{1}".format(names, more))
        out.append("")

    red_rows = [(fs, sh) for fs, sh, risk in rows if risk == RISK_RED]
    if red_rows:
        out.append("-- RED files (fix these first) ".ljust(58, "-"))
        out.append("  {0:<44} {1:>7} {2:>3}  LEAD".format(
            "PATH", "LINES", "TF"))
        for fs, sh in red_rows[:top]:
            out.append("  {0:<44} {1:>7} {2:>3}  {3}".format(
                fs.path[:44], fmt_lines(fs.lines), truck_factor(sh),
                author_table_line(fs, sh, reg)))
        out.append("")

    if not rows:
        out.append("No measured files (>= {0} lines). "
                   "Nothing to assess.".format(opts.min_lines))
        out.append("")
    out.append("Rule of thumb: TF 1 = RED, TF 2 = AMBER, TF >= 3 = GREEN. "
               "Grow a second author via pairing or review, not rewrites.")
    return "\n".join(out)


def scan_report_md(stats: RepoStats, opts: Options, top: int = 10) -> str:
    reg = stats.registry
    rows = stats.risk_files(opts.min_lines)
    out = ["# bus-factor report", ""]
    out.append("* as of {0}, branch `{1}`, {2} commits".format(
        (opts.as_of or date.today()).isoformat(), stats.branch,
        stats.commits_scanned))
    out.append("* measured: {0} files with >= {1} lines".format(
        len(rows), opts.min_lines))
    out.append("")
    out.append("| Risk | Files | Lines | Meaning |")
    out.append("|---|---|---|---|")
    for risk, meaning in ((RISK_RED, "single-owner knowledge"),
                          (RISK_AMBER, "two authors"),
                          (RISK_GREEN, "healthy spread")):
        fl = [fs for fs, _s, r in rows if r == risk]
        out.append("| {0} | {1} | {2} | {3} |".format(
            risk, len(fl), fmt_lines(sum(f.lines for f in fl)), meaning))
    red = [(fs, sh) for fs, sh, r in rows if r == RISK_RED][:top]
    if red:
        out.append("")
        out.append("## RED files")
        out.append("")
        out.append("| Path | Lines | TF | Authors |")
        out.append("|---|---|---|---|")
        for fs, sh in red:
            out.append("| `{0}` | {1} | {2} | {3} |".format(
                fs.path, fs.lines, truck_factor(sh),
                author_table_line(fs, sh, reg)))
    guards = stats.guardians(opts.min_lines)
    if guards:
        out.append("")
        out.append("## Sole guardians")
        out.append("")
        for key, fl in sorted(guards.items(),
                              key=lambda kv: -sum(f.lines for f in kv[1])):
            out.append("* **{0}** guards {1} files ({2} lines): {3}".format(
                reg.display(key), len(fl),
                fmt_lines(sum(f.lines for f in fl)),
                ", ".join("`{0}`".format(f.path) for f in fl[:5])))
    return "\n".join(out) + "\n"


def scan_report_json(stats: RepoStats, opts: Options) -> str:
    rows = stats.risk_files(opts.min_lines)
    payload = {
        "version": __version__,
        "repo": stats.root,
        "branch": stats.branch,
        "as_of": (opts.as_of or date.today()).isoformat(),
        "window_days": opts.window_days,
        "commits_scanned": stats.commits_scanned,
        "bots_ignored": stats.bots_ignored,
        "min_lines": opts.min_lines,
        "files_tracked": len(stats.live),
        "files_measured": len(rows),
        "lines_measured": sum(fs.lines for fs in stats.measured(opts.min_lines)),
        "authors": [stats.registry.display(k) for k in
                    stats.author_keys(opts.include_bots, opts.min_lines)],
        "summary": {},
        "files": [],
        "guardians": {},
    }
    for risk in (RISK_RED, RISK_AMBER, RISK_GREEN):
        fl = [fs for fs, _s, r in rows if r == risk]
        payload["summary"][risk] = {
            "files": len(fl), "lines": sum(f.lines for f in fl)}
    for fs, sh, risk in rows:
        payload["files"].append({
            "path": fs.path,
            "lines": fs.lines,
            "tf": truck_factor(sh),
            "hhi": round(hhi(sh), 4),
            "effective_authors": round(effective_authors(sh), 2),
            "guardian": (stats.registry.display(guardian_of(sh))
                         if guardian_of(sh) else None),
            "risk": risk,
            "shares": {stats.registry.display(k): round(v, 4)
                       for k, v in sorted(sh.items(), key=lambda kv: (-kv[1], kv[0]))},
        })
    for key, fl in stats.guardians(opts.min_lines).items():
        payload["guardians"][stats.registry.display(key)] = [
            {"path": f.path, "lines": f.lines} for f in fl]
    return json.dumps(payload, indent=2, sort_keys=False)


def file_report(stats: RepoStats, path: str, opts: Options,
                fmt: str = "text") -> str:
    reg = stats.registry
    fs = stats.files.get(path)
    if fs is None:
        return ""                     # caller decides exit code
    sh = shares(fs.added)
    if fmt == "json":
        return json.dumps({
            "path": fs.path, "lines": fs.lines,
            "total_added": fs.total_added,
            "tf": truck_factor(sh), "hhi": round(hhi(sh), 4),
            "guardian": (reg.display(guardian_of(sh))
                         if guardian_of(sh) else None),
            "risk": risk_level(truck_factor(sh)),
            "authors": [{"name": reg.display(k), "share": round(v, 4),
                         "added": fs.added[k], "commits": fs.touches[k]}
                        for k, v in sorted(sh.items(), key=lambda kv: (-kv[1], kv[0]))],
        }, indent=2)
    out = ["bus-factor file — {0}".format(fs.path),
           "Lines {0} · added(lines, weighted) {1} · authors {2}".format(
               fs.lines, fs.total_added, fs.n_authors),
           "TF {0} · HHI {1:.3f} · effective authors {2:.2f} · risk {3}".format(
               truck_factor(sh), hhi(sh), effective_authors(sh),
               risk_level(truck_factor(sh))),
           "",
           "  {0:<20} {1:>7} {2:>8} {3:>8}  ROLE".format(
               "AUTHOR", "SHARE", "ADDED", "COMMITS")]
    for k, v in sorted(sh.items(), key=lambda kv: (-kv[1], kv[0])):
        role = []
        if v >= GUARDIAN_SHARE - 1e-9:
            role.append("guardian")
        if v >= CRITICAL_SHARE - 1e-9:
            role.append("critical")
        out.append("  {0:<20} {1:>7} {2:>8} {3:>8}  {4}".format(
            reg.display(k)[:20], fmt_pct(v), fs.added[k], fs.touches[k],
            ", ".join(role)))
    return "\n".join(out)


def module_report(stats: RepoStats, module: str, opts: Options,
                  fmt: str = "text") -> str:
    reg = stats.registry
    prefix = module.rstrip("/") + "/"
    agg: Counter = Counter()
    n_files = 0
    n_lines = 0
    for fs in stats.measured(opts.min_lines):
        if not fs.path.startswith(prefix):
            continue
        n_files += 1
        n_lines += fs.lines
        agg.update(fs.added)
    sh = shares(agg)
    tf = truck_factor(sh)
    guard = guardian_of(sh)
    if fmt == "json":
        return json.dumps({
            "module": module, "files": n_files, "lines": n_lines,
            "tf": tf, "hhi": round(hhi(sh), 4),
            "guardian": reg.display(guard) if guard else None,
            "risk": risk_level(tf),
            "shares": {reg.display(k): round(v, 4)
                       for k, v in sorted(sh.items(), key=lambda kv: (-kv[1], kv[0]))},
        }, indent=2)
    out = ["bus-factor module — {0}".format(module),
           "Files {0} · lines {1} · authors {2}".format(
               n_files, fmt_lines(n_lines), len(sh)),
           "TF {0} · HHI {1:.3f} · risk {2}{3}".format(
               tf, hhi(sh), risk_level(tf),
               " · guardian {0}".format(reg.display(guard)) if guard else ""),
           ""]
    for k, v in sorted(sh.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append("  {0:<20} {1:>7}".format(reg.display(k)[:20], fmt_pct(v)))
    if n_files == 0:
        out.append("  (no measured files under this prefix)")
    return "\n".join(out)


def guardians_report(stats: RepoStats, opts: Options,
                     fmt: str = "text") -> str:
    reg = stats.registry
    guards = stats.guardians(opts.min_lines)
    if fmt == "json":
        return json.dumps({
            "guardians": [
                {"author": reg.display(k),
                 "files": [{"path": f.path, "lines": f.lines,
                            "handoff": f.n_authors == 1} for f in fl]}
                for k, fl in sorted(
                    guards.items(),
                    key=lambda kv: -sum(f.lines for f in kv[1]))]}, indent=2)
    if not guards:
        return ("bus-factor guardians — no sole guardians "
                "(no single author holds >= {0} of any measured file)".format(
                    fmt_pct(GUARDIAN_SHARE)))
    out = ["bus-factor guardians — {0} authors solely guard "
           "{1} files".format(
               len(guards), sum(len(fl) for fl in guards.values())),
           ""]
    for key, fl in sorted(guards.items(),
                          key=lambda kv: -sum(f.lines for f in kv[1])):
        out.append("{0} — {1} files, {2} lines".format(
            reg.display(key), len(fl), fmt_lines(sum(f.lines for f in fl))))
        for f in fl:
            handoff = "  <-- NO second author, write handoff docs" \
                if f.n_authors == 1 else ""
            out.append("    {0:<50} {1:>7} lines{2}".format(
                f.path[:50], fmt_lines(f.lines), handoff))
    return "\n".join(out)


def radius_report(stats: RepoStats, author_query: str, opts: Options,
                  fmt: str = "text") -> Optional[str]:
    reg = stats.registry
    key = reg.resolve(author_query)
    if key is None:
        return None
    radius = stats.blast_radius(key)
    if fmt == "json":
        payload = dict(radius)
        payload["author"] = reg.display(key)
        payload["handoff_files"] = radius["handoff_files"]
        return json.dumps(payload, indent=2)
    out = ["bus-factor blast radius — if {0} leaves tomorrow".format(
        reg.display(key)),
           "",
           "  critical (share >= {0}): {1} files, {2} lines".format(
               fmt_pct(CRITICAL_SHARE), radius["critical"]["files"],
               fmt_lines(radius["critical"]["lines"])),
           "  guarded  (share >= {0}): {1} files, {2} lines".format(
               fmt_pct(GUARDIAN_SHARE), radius["guarded"]["files"],
               fmt_lines(radius["guarded"]["lines"])),
           "  handoff  (guarded, zero other authors): {0} files, {1} lines"
               .format(radius["handoff"]["files"],
                       fmt_lines(radius["handoff"]["lines"])),
           ""]
    if radius["handoff_files"]:
        out.append("  Handoff checklist — nobody else ever touched these:")
        for p in radius["handoff_files"][:20]:
            out.append("    {0}".format(p))
    elif radius["guarded_files"]:
        out.append("  No orphaned files: every guarded file has at least "
                   "one other contributor.")
    if radius["critical_files"]:
        out.append("")
        out.append("  Critical files (their knowledge covers >= 50%):")
        for p in radius["critical_files"][:20]:
            out.append("    {0}".format(p))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI

def parse_args(argv: List[str]) -> argparse.Namespace:
    # Common flags live on a shared parent parser so they work both before
    # and after the subcommand (`scan --as-of X` == `--as-of X scan`).
    # SUPPRESS keeps an unspecified sub-level flag from clobbering the
    # top-level value; real defaults are injected via set_defaults below.
    common = argparse.ArgumentParser(add_help=False,
                                     argument_default=argparse.SUPPRESS)
    common.add_argument("-p", "--path", help="repository path "
                        "(default: current directory)")
    common.add_argument("--window", type=int, metavar="DAYS",
                        help="only consider commits from the last DAYS days "
                             "(default: all history)")
    common.add_argument("--as-of", metavar="YYYY-MM-DD",
                        help="pin 'today' for deterministic reports/tests")
    common.add_argument("--min-lines", type=int,
                        help="files smaller than this are excluded from risk "
                             "(default {0})".format(DEFAULT_MIN_LINES))
    common.add_argument("--include-bots", action="store_true",
                        help="count bot authors (dependabot etc.) instead of "
                             "ignoring them")
    common.add_argument("--no-coauthored", action="store_true",
                        help="ignore Co-Authored-By trailers (pair-"
                             "programming credit off)")
    common.add_argument("--include-deleted", action="store_true",
                        help="also score files that no longer exist "
                             "(archaeology)")
    common.add_argument("--format", choices=("text", "md", "json"),
                        help="output format (default text)")

    p = argparse.ArgumentParser(
        prog="bus_factor.py",
        parents=[common],
        description="Measure knowledge concentration (bus factor) from git "
                    "history. Who solely guards which file — and what breaks "
                    "if they leave.")
    p.add_argument("--version", action="version",
                   version="bus-factor " + __version__)
    sub = p.add_subparsers(dest="cmd")

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[common], help=help_text)

    sp = add("scan", "repo-level risk report")
    sp.add_argument("--top", type=int, default=10,
                    help="max files listed per section (default 10)")
    sp.add_argument("--fail-on", choices=("red", "amber", "none"),
                    default="none",
                    help="exit 1 when risk at/above this level exists "
                         "(for CI)")

    sp = add("file", "per-author breakdown for one file")
    sp.add_argument("target", help="repo-relative file path")

    sp = add("module", "aggregate one directory")
    sp.add_argument("target", help="directory prefix, e.g. src/billing")

    add("guardians", "who solely guards which files")

    sp = add("radius", "what breaks if one author leaves")
    sp.add_argument("author", help="name or email (substring match ok)")

    return p.parse_args(argv)


# Defaults are applied in main() rather than via set_defaults():
# argparse propagates parser-level defaults into every subparser, which
# would silently clobber values given before the subcommand (e.g. the -p
# in `-p /repo scan`). With SUPPRESS everywhere, a flag simply never
# appears unless the user (or the subcommand) actually passed it.
CLI_DEFAULTS = {
    "path": ".",
    "window": None,
    "as_of": None,
    "min_lines": DEFAULT_MIN_LINES,
    "include_bots": False,
    "no_coauthored": False,
    "include_deleted": False,
    "format": "text",
}


def apply_cli_defaults(args: argparse.Namespace) -> argparse.Namespace:
    for key, value in CLI_DEFAULTS.items():
        if not hasattr(args, key):
            setattr(args, key, value)
    return args


def build_options(args: argparse.Namespace) -> Options:
    as_of = None
    if args.as_of:
        try:
            as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
        except ValueError:
            raise SystemExit("error: --as-of must be YYYY-MM-DD, got {0!r}"
                             .format(args.as_of))
    return Options(repo=args.path, window_days=args.window, as_of=as_of,
                   min_lines=args.min_lines, include_bots=args.include_bots,
                   use_coauthored=not args.no_coauthored,
                   include_deleted=args.include_deleted)


def main(argv: List[str] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    apply_cli_defaults(args)
    cmd = args.cmd or "scan"
    opts = build_options(args)
    try:
        stats = collect(opts)
    except RuntimeError as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        return 2

    if cmd == "scan":
        if args.format == "json":
            print(scan_report_json(stats, opts))
        elif args.format == "md":
            print(scan_report_md(stats, opts, top=args.top))
        else:
            print(scan_report_text(stats, opts, top=args.top))
        if getattr(args, "fail_on", "none") == "red":
            if any(r == RISK_RED for _fs, _s, r in
                   stats.risk_files(opts.min_lines)):
                return 1
        elif getattr(args, "fail_on", "none") == "amber":
            if any(r in (RISK_RED, RISK_AMBER) for _fs, _s, r in
                   stats.risk_files(opts.min_lines)):
                return 1
        return 0

    if cmd == "file":
        text = file_report(stats, args.target, opts, fmt=args.format)
        if not text:
            print("error: no history for file: {0}".format(args.target),
                  file=sys.stderr)
            return 2
        print(text)
        return 0

    if cmd == "module":
        print(module_report(stats, args.target, opts, fmt=args.format))
        return 0

    if cmd == "guardians":
        print(guardians_report(stats, opts, fmt=args.format))
        return 0

    if cmd == "radius":
        text = radius_report(stats, args.author, opts, fmt=args.format)
        if text is None:
            print("error: author not found: {0}".format(args.author),
                  file=sys.stderr)
            return 2
        print(text)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
