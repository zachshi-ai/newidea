#!/usr/bin/env python3
"""
churn_hotspot · 变更热点
=========================

Refactoring priority, computed instead of argued.

    Where should the NEXT refactor go? Not the biggest file, not the
    messiest one — the intersection of "changed often" x "expensive
    to change":

        HOTSPOT SCORE = churn (commits touching the file in the window)
                        x size (current line count)

Every edit to a file pays interest proportional to its size; churn tells
you how often that interest is being paid. The product finds where the
codebase bleeds the most — per period, deterministically, from git alone.

A time axis makes it actionable (window is split into two halves):

    PERSISTENT  hot in both halves   -> compounding debt, plan a dedicated
                                        refactor (this is your backlog #1)
    EMERGING    hot only recently    -> intervene NOW while it is cheap
    COOLING     hot only in the past -> do NOT spend budget here; the code
                                        is healing itself

Zero dependencies: Python 3.8+ standard library + the `git` binary.
Report output is in English; repo docs are bilingual (中文为主).

Usage:
    python3 churn_hotspot.py scan                    # top-N hotspot table
    python3 churn_hotspot.py scan --window 90        # last 90 days only
    python3 churn_hotspot.py trend                   # persistent/emerging/cooling
    python3 churn_hotspot.py file src/app.py         # one file, weekly histogram
    python3 churn_hotspot.py scan --format json      # machine-readable
    python3 churn_hotspot.py scan --fail-on red      # CI gate
"""

import argparse
import fnmatch
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Constants

DEFAULT_WINDOW = 180            # days; ~a quarter plus change
DEFAULT_TOP = 20                # rows shown by `scan`
DEFAULT_MIN_LINES = 1           # every existing file counts; raise via flag
MIN_HOT_CHURN = 3               # a hotspot must be edited REPEATEDLY:
                                # one giant commit is creation, not debt
RED_QUANTILE = 0.90             # score percentile for RED (small repos
AMBER_QUANTILE = 0.75           # degrade gracefully, see level_of)
ELIGIBLE_FOR_PERCENTILES = 5    # below this many hot files, no percentile
                                # theater: the worst eligible file is RED

WORSENING_NONE = "-"
TREND_PERSISTENT = "persistent"
TREND_EMERGING = "emerging"
TREND_COOLING = "cooling"
TREND_STABLE = "stable"

LEVEL_RED = "RED"
LEVEL_AMBER = "AMBER"
LEVEL_GREEN = "GREEN"

TREND_ADVICE = {
    TREND_PERSISTENT: "compounding debt — schedule a dedicated refactor",
    TREND_EMERGING: "act now while it is still cheap (tests, then split)",
    TREND_COOLING: "healing — do NOT spend refactor budget here",
    TREND_STABLE: "warm, not burning — keep an eye on it",
    WORSENING_NONE: "",
}

# Lockfiles, vendored trees and generated code churn for reasons that have
# nothing to do with design debt. Matched against basename, any path
# segment, or (for patterns with '/') the whole relative path.
DEFAULT_EXCLUDES = (
    # lockfiles / dependency manifests resolved to a digest
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "Podfile.lock", "Cartfile.resolved", "Gemfile.lock", "composer.lock",
    "Cargo.lock", "poetry.lock", "Pipfile.lock", "uv.lock", "go.sum",
    "flake.lock", "packages.lock.json", "*.csproj.generated.json",
    # vendored / third-party / build output directories
    "node_modules", "vendor", "vendors", "third_party", "thirdparty",
    "dist", "build", "out", "target", "deps", "_build",
    # generated code
    "*.min.js", "*.min.css", "*.map", "*.snap",
    "*_pb2.py", "*_pb.py", "*.pb.go", "*.pb.cc", "*.pb.h",
    "*.generated.*", "*.designer.cs", "*.g.dart", "*.g.py",
)

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
# %x1e<hash>%x1f<author date ISO>%x1e then one status line per file
GIT_LOG_FORMAT = RECORD_SEP + FIELD_SEP.join(("%H", "%aI"))
STATUS_RE = re.compile(r"^([MARDCT])\d*\t(.+?)(?:\t(.+))?$")

BINARY_SNIFF = 8192             # bytes checked for NUL

# ---------------------------------------------------------------------------
# Options


@dataclass
class Options:
    repo: str                        # path to the git working tree
    window: int = DEFAULT_WINDOW     # days of history considered
    as_of: Optional[str] = None      # pinned "today" for reproducibility
    min_lines: int = DEFAULT_MIN_LINES
    excludes: Tuple[str, ...] = DEFAULT_EXCLUDES
    top: int = DEFAULT_TOP

    @property
    def until(self) -> date:
        if self.as_of:
            return date.fromisoformat(self.as_of)
        return date.today()

    @property
    def since(self) -> date:
        return self.until - timedelta(days=self.window)

    @property
    def mid(self) -> date:
        """Half-way point: the window splits into old|recent halves."""
        return self.since + timedelta(days=self.window // 2)


# ---------------------------------------------------------------------------
# Git collection


@dataclass
class History:
    touches: Dict[str, List[date]] = field(default_factory=dict)
    renames: Dict[str, str] = field(default_factory=dict)   # old -> new

    def resolve(self, path: str) -> str:
        """Follow rename chains so pre-rename churn lands on the live path."""
        seen = 0
        while path in self.renames and seen < 64:
            path = self.renames[path]
            seen += 1
        return path


def run_git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false"] + list(args),
        cwd=repo, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("git {0} failed:\n{1}".format(
            " ".join(args[:2]), proc.stderr.strip()))
    return proc.stdout


def collect(repo: str, since: date, until: date) -> History:
    """One full `git log` pass -> per-path touch dates + rename map.

    Date filtering happens on OUR side, never via --since/--until:
    those prune the commit *walk* at the first out-of-window commit, so
    with interleaved dates (rebases, backports, imported history) they
    silently drop in-window commits.

    `--name-status` (with default rename detection) emits
    `R100<TAB>old<TAB>new` for renames, so history survives `git mv`
    and lands on the current path.
    """
    out = run_git(repo, "log", "--name-status", "-M",
                  "--pretty=format:" + GIT_LOG_FORMAT)
    hist = History()
    # NB: \x1e counts as a line boundary for str.splitlines(), so records
    # are split on it explicitly, never with splitlines().
    for record in out.split(RECORD_SEP):
        if not record:
            continue
        lines = record.split("\n")
        try:
            _h, iso = lines[0].split(FIELD_SEP, 1)
            when = date.fromisoformat(iso[:10])
        except ValueError:
            continue
        in_window = since <= when <= until
        for status_line in lines[1:]:
            m = STATUS_RE.match(status_line.strip())
            if not m:
                continue
            status, a, b = m.group(1), m.group(2), m.group(3)
            if b:                                 # R(old->new) or C(copy)
                if status == "R":
                    hist.renames[a] = b
                target = hist.resolve(b)
            else:
                target = hist.resolve(a)          # M / A / D alike
            if in_window:
                hist.touches.setdefault(target, []).append(when)
    return hist


# ---------------------------------------------------------------------------
# Working-tree measurement


def is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\x00" in fh.read(BINARY_SNIFF)
    except OSError:
        return True


def count_lines(path: str) -> int:
    with open(path, "rb") as fh:
        return sum(1 for _ in fh)


def excluded(rel: str, patterns: Tuple[str, ...]) -> bool:
    base = os.path.basename(rel)
    parts = rel.split(os.sep)
    for pat in patterns:
        pat = pat.strip()
        if not pat:
            continue
        if "/" in pat:
            if fnmatch.fnmatch(rel, pat):
                return True
        elif (fnmatch.fnmatch(base, pat)
                or any(fnmatch.fnmatch(seg, pat) for seg in parts)):
            return True
    return False


# ---------------------------------------------------------------------------
# Hotspot model


@dataclass
class Hotspot:
    path: str
    churn: int                       # commits touching it inside the window
    lines: int                       # current size
    old_churn: int                   # touches in the first window half
    recent_churn: int                # touches in the second half

    @property
    def score(self) -> int:
        return self.churn * self.lines

    @property
    def trend(self) -> str:
        old, recent = self.old_churn, self.recent_churn
        if old >= MIN_HOT_CHURN and recent >= MIN_HOT_CHURN:
            return TREND_PERSISTENT
        if recent >= MIN_HOT_CHURN and old <= 1:
            return TREND_EMERGING
        if old >= MIN_HOT_CHURN and recent <= 1:
            return TREND_COOLING
        if self.churn >= MIN_HOT_CHURN:
            return TREND_STABLE
        return WORSENING_NONE

    level: str = LEVEL_GREEN

    def as_dict(self, rank: int) -> dict:
        return {
            "rank": rank, "level": self.level, "path": self.path,
            "churn": self.churn, "lines": self.lines, "score": self.score,
            "trend": self.trend,
            "old_churn": self.old_churn, "recent_churn": self.recent_churn,
        }


def quantile(sorted_values: List[int], q: float) -> int:
    """Nearest-rank percentile on an ascending list."""
    if not sorted_values:
        return 0
    idx = max(0, math.ceil(q * len(sorted_values)) - 1)
    return sorted_values[min(idx, len(sorted_values) - 1)]


def assign_levels(hotspots: List[Hotspot]) -> None:
    """RED/AMBER must be earned by REPEATED edits, then sized by percentile.

    churn < MIN_HOT_CHURN means the file was written once and (mostly) left
    alone — creation, not debt — so it stays GREEN whatever its size.
    """
    eligible = [h for h in hotspots if h.churn >= MIN_HOT_CHURN]
    if not eligible:
        return
    if len(eligible) >= ELIGIBLE_FOR_PERCENTILES:
        scores = sorted(h.score for h in eligible)
        red_cut = quantile(scores, RED_QUANTILE)
        amber_cut = quantile(scores, AMBER_QUANTILE)
        for h in eligible:
            if h.score >= red_cut:
                h.level = LEVEL_RED
            elif h.score >= amber_cut:
                h.level = LEVEL_AMBER
    else:
        # Small repo: percentiles would be theater. The single worst
        # repeatedly-edited file is RED, the rest of them AMBER.
        ranked = sorted(eligible, key=lambda h: h.score, reverse=True)
        for i, h in enumerate(ranked):
            h.level = LEVEL_RED if i == 0 else LEVEL_AMBER


def build_hotspots(opts: Options) -> Tuple[List[Hotspot], int]:
    """Returns (hotspots sorted by score desc, count of excluded paths)."""
    hist = collect(opts.repo, opts.since, opts.until)
    out: List[Hotspot] = []
    skipped = 0
    for rel, dates in hist.touches.items():
        full = os.path.join(opts.repo, rel)
        if not os.path.isfile(full):       # deleted (and never renamed back)
            continue
        if excluded(rel, opts.excludes):
            skipped += 1
            continue
        if is_binary(full):
            continue
        lines = count_lines(full)
        if lines < opts.min_lines:
            continue
        churn = len(dates)
        old = sum(1 for d in dates if d < opts.mid)
        recent = churn - old
        out.append(Hotspot(path=rel, churn=churn, lines=lines,
                           old_churn=old, recent_churn=recent))
    out.sort(key=lambda h: (-h.score, h.path))
    assign_levels(out)
    return out, skipped


# ---------------------------------------------------------------------------
# Reports


def trunc(s: str, width: int) -> str:
    return s if len(s) <= width else s[: width - 1] + "…"


def scan_report_text(hotspots: List[Hotspot], opts: Options,
                     skipped: int) -> str:
    rows = hotspots[: opts.top]
    # A RED/AMBER below the top-N cut would make "Refactor first" point
    # at a row the table never shows — always surface levelled files.
    rows += [h for h in hotspots[opts.top:] if h.level != LEVEL_GREEN]
    max_score = max((h.score for h in rows), default=1) or 1
    path_w = max((len(h.path) for h in rows), default=20)
    path_w = min(max(path_w, 20), 48)
    lines = []
    lines.append("-- Hotspots --------------------------------------------------")
    lines.append("   window: {0}d ({1} .. {2})   measured: {3} files"
                 "   excluded: {4}".format(
                     opts.window, opts.since, opts.until, len(hotspots),
                     skipped))
    lines.append("")
    for i, h in enumerate(rows, 1):
        bar = "#" * max(1, round(28 * h.score / max_score))
        lines.append("{i:>3}  {level:<5}  {path}  churn {churn:>3}"
                     "  lines {lines:>5}  score {score:>7}  [{trend}]".format(
                         i=i, level=h.level, path=trunc(h.path, path_w),
                         churn=h.churn, lines=h.lines, score=h.score,
                         trend=h.trend if h.trend != WORSENING_NONE else "-"))
        lines.append("    {0}".format(bar))
    n_red = sum(1 for h in hotspots if h.level == LEVEL_RED)
    n_amber = sum(1 for h in hotspots if h.level == LEVEL_AMBER)
    n_green = len(hotspots) - n_red - n_amber
    lines.append("")
    lines.append("Summary: {0} RED / {1} AMBER / {2} GREEN".format(
        n_red, n_amber, n_green))
    first_reds = [h.path for h in hotspots if h.level == LEVEL_RED][:3]
    if first_reds:
        lines.append("Refactor first: {0}".format(", ".join(first_reds)))
    return "\n".join(lines)


def scan_report_json(hotspots: List[Hotspot], opts: Options,
                     skipped: int) -> str:
    payload = {
        "tool": "churn_hotspot", "version": __version__,
        "as_of": opts.until.isoformat(), "window_days": opts.window,
        "since": opts.since.isoformat(),
        "measured": len(hotspots), "excluded": skipped,
        "files": [h.as_dict(i) for i, h in enumerate(hotspots[: opts.top], 1)],
        "summary": {
            "red": sum(1 for h in hotspots if h.level == LEVEL_RED),
            "amber": sum(1 for h in hotspots if h.level == LEVEL_AMBER),
            "green": sum(1 for h in hotspots
                         if h.level == LEVEL_GREEN),
        },
    }
    return json.dumps(payload, indent=2, sort_keys=False)


def trend_report_text(hotspots: List[Hotspot], opts: Options) -> str:
    lines = []
    lines.append("-- Hotspot trends (halves: {0}..{1} | {1}..{2})".format(
        opts.since, opts.mid, opts.until))
    grouped: Dict[str, List[Hotspot]] = {}
    for h in hotspots:
        if h.trend != WORSENING_NONE:
            grouped.setdefault(h.trend, []).append(h)
    order = (TREND_PERSISTENT, TREND_EMERGING, TREND_COOLING, TREND_STABLE)
    icons = {TREND_PERSISTENT: "!!", TREND_EMERGING: ">>",
             TREND_COOLING: "<<", TREND_STABLE: "~~"}
    for key in order:
        group = grouped.get(key, [])
        lines.append("")
        lines.append("{0} {1} ({2}) — {3}".format(
            icons[key], key.upper(), len(group), TREND_ADVICE[key]))
        for h in group[: opts.top]:
            lines.append("     {0}  churn {1} (old {2} + recent {3})"
                         "  lines {4}  score {5}  {6}".format(
                             trunc(h.path, 44), h.churn, h.old_churn,
                             h.recent_churn, h.lines, h.score, h.level))
    if not grouped:
        lines.append("")
        lines.append("  no file reached churn >= {0} in either half —"
                     " no hotspots".format(MIN_HOT_CHURN))
    return "\n".join(lines)


def trend_report_json(hotspots: List[Hotspot], opts: Options) -> str:
    payload = {
        "tool": "churn_hotspot", "version": __version__,
        "as_of": opts.until.isoformat(), "window_days": opts.window,
        "halves": {"old": [opts.since.isoformat(), opts.mid.isoformat()],
                   "recent": [opts.mid.isoformat(), opts.until.isoformat()]},
        "groups": {
            key: [h.as_dict(i) for i, h in enumerate(group[: opts.top], 1)]
            for key, group in (
                (k, [h for h in hotspots if h.trend == k]) for k in
                (TREND_PERSISTENT, TREND_EMERGING, TREND_COOLING,
                 TREND_STABLE))
        },
    }
    return json.dumps(payload, indent=2, sort_keys=False)


def file_report(hotspots: List[Hotspot], opts: Options,
                target: str) -> Optional[str]:
    match = next((h for h in hotspots
                  if h.path == target or h.path.endswith("/" + target)), None)
    if match is None:
        return None
    rank = hotspots.index(match) + 1
    lines = []
    lines.append("-- {0} --".format(match.path))
    lines.append("   churn {0}   lines {1}   score {2}   level {3}"
                 "   rank #{4}/{5}".format(
                     match.churn, match.lines, match.score, match.level,
                     rank, len(hotspots)))
    lines.append("   halves: old {0} + recent {1} -> {2}".format(
        match.old_churn, match.recent_churn,
        match.trend if match.trend != WORSENING_NONE else "no signal"))
    hist = collect(opts.repo, opts.since, opts.until)
    dates = hist.touches.get(match.path, [])
    if dates:
        # weekly buckets across the window, oldest first
        weeks = max(1, opts.window // 7)
        buckets = [0] * weeks
        start = opts.since
        for d in dates:
            offset = (d - start).days
            if offset < 0:
                continue
            buckets[min(offset // 7, weeks - 1)] += 1
        peak = max(buckets)
        lines.append("")
        lines.append("   weekly touches (last {0} weeks):".format(weeks))
        for i, n in enumerate(buckets):
            week_start = start + timedelta(days=7 * i)
            bar = "#" * n if n else "·"
            lines.append("   {0}  {1:<{2}} {3}".format(
                week_start, bar, peak, n))
    return "\n".join(lines)


def file_report_json(hotspots: List[Hotspot], opts: Options,
                     target: str) -> Optional[str]:
    match = next((h for h in hotspots
                  if h.path == target or h.path.endswith("/" + target)), None)
    if match is None:
        return None
    payload = match.as_dict(hotspots.index(match) + 1)
    payload["total_measured"] = len(hotspots)
    payload["window_days"] = opts.window
    return json.dumps(payload, indent=2, sort_keys=False)


# ---------------------------------------------------------------------------
# CLI


VALUE_FLAGS = ("--window", "--top", "--min-lines", "--exclude",
               "--format", "--as-of", "--fail-on")
BOOL_FLAGS = ("--no-default-excludes",)


def reorder_common_flags(argv: List[str]) -> List[str]:
    """Move common flags to the front so the MAIN parser owns them.

    With argparse's parents=[common] trick, a subparser's defaults would
    silently overwrite values given before the subcommand
    (`--top 3 scan` -> 20). Reordering keeps "flags anywhere" semantics
    with one owning parser.
    """
    head: List[str] = []
    tail: List[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        name = tok.split("=", 1)[0]
        if name in VALUE_FLAGS:
            head.append(tok)
            if "=" not in tok and i + 1 < len(argv):
                head.append(argv[i + 1])
                i += 2
                continue
        elif name in BOOL_FLAGS:
            head.append(tok)
        else:
            tail.append(tok)
        i += 1
    return head + tail


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                        help="days of history to consider (default {0})"
                        .format(DEFAULT_WINDOW))
    common.add_argument("--top", type=int, default=DEFAULT_TOP,
                        help="rows per report (default {0})"
                        .format(DEFAULT_TOP))
    common.add_argument("--min-lines", type=int, default=DEFAULT_MIN_LINES,
                        help="ignore files smaller than this")
    common.add_argument("--exclude", action="append", default=[],
                        metavar="PAT",
                        help="extra exclude glob (repeatable)")
    common.add_argument("--no-default-excludes", action="store_true",
                        help="count lockfiles/vendored/generated code too")
    common.add_argument("--format", choices=("text", "json"),
                        default="text")
    common.add_argument("--as-of", metavar="YYYY-MM-DD",
                        help="pin 'today' for reproducible reports")
    common.add_argument("--fail-on", choices=("red", "amber"),
                        default="none",
                        help="exit 1 when any file reaches this level")

    p = argparse.ArgumentParser(
        prog="churn_hotspot",
        description="Refactoring priority from git churn x size.",
        parents=[common])
    sub = p.add_subparsers(dest="cmd")
    # Common flags are hoisted in front of the subcommand (see
    # reorder_common_flags), so subparsers must NOT carry them again.
    sub.add_parser("scan", help="top-N hotspot table (default command)")
    sub.add_parser("trend", help="persistent / emerging / cooling groups")
    f = sub.add_parser("file", help="one file profile")
    f.add_argument("target", help="path inside the repo")
    return p


def build_options(args: argparse.Namespace) -> Options:
    excludes: Tuple[str, ...] = DEFAULT_EXCLUDES
    if args.no_default_excludes:
        excludes = tuple(args.exclude)
    else:
        excludes = DEFAULT_EXCLUDES + tuple(args.exclude)
    return Options(
        repo=os.getcwd(),
        window=max(1, args.window),
        as_of=args.as_of,
        min_lines=args.min_lines,
        excludes=excludes,
        top=max(1, args.top),
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(
        reorder_common_flags(argv if argv is not None else sys.argv[1:]))
    opts = build_options(args)
    cmd = args.cmd or "scan"
    try:
        hotspots, skipped = build_hotspots(opts)
    except RuntimeError as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        return 2

    if cmd == "scan":
        if args.format == "json":
            print(scan_report_json(hotspots, opts, skipped))
        else:
            print(scan_report_text(hotspots, opts, skipped))
    elif cmd == "trend":
        if args.format == "json":
            print(trend_report_json(hotspots, opts))
        else:
            print(trend_report_text(hotspots, opts))
    elif cmd == "file":
        text = (file_report_json if args.format == "json"
                else file_report)(hotspots, opts, args.target)
        if text is None:
            print("error: no history for file: {0}".format(args.target),
                  file=sys.stderr)
            return 2
        print(text)

    if args.fail_on == "red":
        if any(h.level == LEVEL_RED for h in hotspots):
            return 1
    elif args.fail_on == "amber":
        if any(h.level in (LEVEL_RED, LEVEL_AMBER) for h in hotspots):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
