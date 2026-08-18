#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""todo-rot — 承诺锈蚀 / TODO Rot

Every TODO comment is a promise made to the future. None of them expire.
todo-rot turns git history into a promise ledger:

  * scan      — working-tree sweep: every TODO/FIXME/HACK/XXX with a weight
  * ledger    — age every promise via the git event log, score its rot,
                flag zombies (older than 2x the project's promise half-life)
  * halflife  — survival view: how long do PAID promises actually take?
                who issues promises and never pays them back?
  * audit     — CI gate: fail if zombies / ancient promises exceed budget

Method in one line: replay `git log -p --unified=0` as a stream of
promise add/remove events; removed markers are "paid", their lifetimes
give the half-life, and unpaid promises older than 2x that are zombies.

Zero dependencies: Python 3.8+ standard library + a git binary.
MIT License (c) 2026
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Tuple

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Vocabulary: markers, weights, buckets

MARKER_WEIGHTS = {"TODO": 1, "XXX": 2, "HACK": 3, "FIXME": 4}
MARKER_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
ISSUE_RE = re.compile(r"#(\d+)")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
OWNER_RE = re.compile(r"\(([^)]{1,40})\)")

# age buckets, in days, upper bound exclusive; last is open-ended
BUCKETS: Tuple[Tuple[str, int], ...] = (
    ("FRESH", 30),
    ("AGING", 180),
    ("STALE", 365),
    ("ANCIENT", 1 << 30),
)

# a promise is a ZOMBIE when its age exceeds max(2 x half-life, this floor)
ZOMBIE_FLOOR_DAYS = 30

BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".tgz", ".bz2", ".xz", ".7z", ".jar", ".class", ".so", ".dylib",
    ".dll", ".exe", ".bin", ".woff", ".woff2", ".ttf", ".eot", ".mp3",
    ".mp4", ".mov", ".avi", ".sqlite", ".db", ".pyc", ".o", ".a", ".wasm",
}

SENTINEL = "\x1e"  # record separator between commits in `git log --format`
UNIT = "\x1f"      # field separator inside a commit header line

# ---------------------------------------------------------------------------
# Small pure helpers


def normalize_text(marker: str, text: str) -> str:
    """Canonical form used to pair the same promise across commits.

    Strips comment punctuation and the volatile extras (owner / issue /
    date) so `TODO(alice): fix x #12` and `TODO: fix x` still reconcile.
    """
    text = OWNER_RE.sub(" ", text)
    text = ISSUE_RE.sub(" ", text)
    text = DATE_RE.sub(" ", text)
    text = text.lstrip(" :/*#>=- \t")
    text = re.sub(r"\*/+$", "", text).rstrip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" .;!")
    return (marker + " " + text.lower())[:140]


def bucket_of(age_days: int) -> str:
    for name, upper in BUCKETS:
        if age_days < upper:
            return name
    return BUCKETS[-1][0]


def rot_score(weight: int, age_days: int) -> float:
    """Rust per year: a FIXME ages 4x faster than a TODO."""
    return round(weight * age_days / 365.0, 1)


def parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def zombie_threshold(half_life_days: Optional[float]) -> Optional[int]:
    """None when the project has never paid a promise (no half-life)."""
    if half_life_days is None:
        return None
    return max(int(2 * half_life_days), ZOMBIE_FLOOR_DAYS)


# ---------------------------------------------------------------------------
# Working-tree scan


@dataclass
class Hit:
    path: str
    line: int
    marker: str
    text: str          # raw text after the marker
    owner: str         # from TODO(alice) — "" when absent
    issue: str         # from #123 — "" when absent
    declared: str      # explicit YYYY-MM-DD in the text — "" when absent
    norm: str = ""     # filled by scan()

    def as_dict(self) -> Dict[str, object]:
        d = {
            "file": self.path,
            "line": self.line,
            "marker": self.marker,
            "text": self.text.strip(),
            "weight": MARKER_WEIGHTS[self.marker],
        }
        if self.owner:
            d["owner"] = self.owner
        if self.issue:
            d["issue"] = "#" + self.issue
        if self.declared:
            d["declared_date"] = self.declared
        return d


def looks_binary(path: str) -> bool:
    if os.path.splitext(path)[1].lower() in BINARY_EXT:
        return True
    try:
        with open(path, "rb") as fh:
            return b"\x00" in fh.read(8192)
    except OSError:
        return True


def scan_tree(root: str, excludes: Sequence[str]) -> List[Hit]:
    """Sweep the working tree for promise markers. Pure filesystem, no git."""
    hits: List[Hit] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d != ".git" and not _excluded(_rel(root, dirpath, d), excludes)
        )
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = _rel(root, dirpath, fn)
            if _excluded(rel, excludes) or looks_binary(full):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        m = MARKER_RE.search(line)
                        if not m:
                            continue
                        hits.append(_hit(rel, i, m.group(1), line[m.end():]))
            except OSError:
                continue
    return hits


def _hit(rel: str, line_no: int, marker: str, rest: str) -> Hit:
    owner = ""
    m = OWNER_RE.search(rest[:60])
    if m:
        owner = m.group(1).strip().rstrip(",")
    im = ISSUE_RE.search(rest)
    dm = DATE_RE.search(rest)
    text = re.sub(r"\s+", " ", rest).strip(" \t*/#-")
    return Hit(
        path=rel, line=line_no, marker=marker, text=text[:160],
        owner=owner, issue=im.group(1) if im else "",
        declared=dm.group(1) if dm else "",
        norm=normalize_text(marker, rest),
    )


def _rel(root: str, dirpath: str, name: str) -> str:
    return os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")


def _excluded(rel: str, excludes: Sequence[str]) -> bool:
    for ex in excludes:
        if rel == ex or rel.startswith(ex.rstrip("/") + "/"):
            return True
    return False


# ---------------------------------------------------------------------------
# git plumbing


def run_git(root: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", root, "--no-pager"] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise SystemExit("git error: %s" % proc.stderr.strip())
    return proc.stdout


def toplevel(root: str) -> Optional[str]:
    proc = subprocess.run(
        ["git", "-C", root, "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


@dataclass
class FileDiff:
    path: str
    status: str = "M"                   # M / A / D / R / C
    old_path: str = ""
    minus: List[str] = field(default_factory=list)  # raw '-' lines (no sign)
    plus: List[str] = field(default_factory=list)   # raw '+' lines (no sign)


@dataclass
class Commit:
    sha: str
    date: datetime
    author: str
    email: str
    files: List[FileDiff] = field(default_factory=list)


DIFF_HEAD = "diff --git "

def parse_log(out: str) -> List[Commit]:
    """Parse `git log --format=SENTINEL... -p --unified=0` output.

    Returns commits oldest-first (replay order).
    """
    commits: List[Commit] = []
    for record in out.split(SENTINEL):
        record = record.lstrip("\n")
        if not record.strip():
            continue
        head, _, diff = record.partition("\n")
        parts = head.split(UNIT)
        if len(parts) < 4:
            continue
        commits.append(Commit(sha=parts[0], date=parse_iso(parts[1]),
                              author=parts[2], email=parts[3],
                              files=parse_diff(diff)))
    commits.reverse()
    return commits


def parse_diff(diff: str) -> List[FileDiff]:
    files: List[FileDiff] = []
    cur: Optional[FileDiff] = None
    in_hunk = False
    for line in diff.split("\n"):
        if line.startswith(DIFF_HEAD):
            cur = FileDiff(path=_path_b(line))
            files.append(cur)
            in_hunk = False
        elif cur is None:
            continue
        elif line.startswith(("rename from ", "copy from ")):
            cur.old_path = line.split(" ", 2)[2]
        elif line.startswith(("rename to ", "copy to ")):
            cur.status = "R" if line.startswith("rename") else "C"
        elif line.startswith("deleted file mode"):
            cur.status = "D"
        elif line.startswith("new file mode"):
            cur.status = "A"
        elif line.startswith("@@"):
            in_hunk = True
        elif not in_hunk:
            continue
        elif line.startswith("+") and not line.startswith("+++"):
            cur.plus.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            cur.minus.append(line[1:])
    return files


def _path_b(head: str) -> str:
    """Extract the b/ path from `diff --git a/x b/y` (quoted forms tolerated)."""
    m = re.search(r" b/(.*)$", head)
    path = m.group(1) if m else head[len(DIFF_HEAD):]
    return path.strip('"').replace('\\"', '"')


def marker_events(lines: Sequence[str]) -> List[Tuple[str, str, str]]:
    """[(marker, norm, raw_line)] for every marker found in the diff lines."""
    events = []
    for raw in lines:
        m = MARKER_RE.search(raw)
        if m:
            events.append((m.group(1), normalize_text(m.group(1), raw[m.end():]), raw.strip()))
    return events


# ---------------------------------------------------------------------------
# The promise ledger (event replay)


@dataclass
class Promise:
    path: str
    marker: str
    norm: str
    text: str
    intro_date: datetime
    intro_commit: str
    author: str
    email: str

    @property
    def weight(self) -> int:
        return MARKER_WEIGHTS[self.marker]


@dataclass
class Paid:
    promise: Promise
    pay_date: datetime
    pay_commit: str
    lifetime_days: int


@dataclass
class Ledger:
    pending: Dict[str, List[Promise]] = field(default_factory=dict)
    paid: List[Paid] = field(default_factory=list)
    died: List[Tuple[Promise, datetime]] = field(default_factory=list)  # file deleted
    orphan_removals: int = 0    # marker removed with no known introduction
    moves: int = 0              # marker re-sited in the same commit

    def current(self, excludes: Sequence[str]) -> List[Promise]:
        out = []
        for path, plist in self.pending.items():
            if not _excluded(path, excludes):
                out.extend(plist)
        return out

    def half_life_days(self, excludes: Sequence[str]) -> Optional[float]:
        lifetimes = [p.lifetime_days for p in self.paid
                     if not _excluded(p.promise.path, excludes)]
        return statistics.median(lifetimes) if lifetimes else None


def build_ledger(root: str, excludes: Sequence[str],
                 as_of: Optional[date] = None) -> Ledger:
    fmt = SENTINEL + "%H" + UNIT + "%aI" + UNIT + "%an" + UNIT + "%ae"
    out = run_git(
        root, "-c", "core.quotepath=false", "log", "--format=" + fmt,
        "-p", "--unified=0", "--no-ext-diff", "-M",
    )
    led = Ledger()
    for commit in parse_log(out):
        if as_of is not None and commit.date.date() > as_of:
            continue
        _apply(led, commit)
    return led


def _apply(led: Ledger, commit: Commit) -> None:
    # renames first: promises follow the file (a pure `git mv` keeps its age)
    for fd in commit.files:
        if fd.status == "R" and fd.old_path:
            moved = led.pending.pop(fd.old_path, [])
            for p in moved:
                p.path = fd.path
            led.pending[fd.path] = moved
    # whole-file deletions: promises die with their context
    for fd in commit.files:
        if fd.status == "D":
            for p in led.pending.pop(fd.path, []):
                led.died.append((p, commit.date))
    removals: List[Tuple[str, str, str]] = []   # (path, norm, raw)
    additions: List[Tuple[str, str, str]] = []
    for fd in commit.files:
        if fd.status != "D":
            removals.extend((fd.path, n, r) for _, n, r in marker_events(fd.minus))
        additions.extend((fd.path, n, r) for _, n, r in marker_events(fd.plus))
    # same-commit re-site (text unchanged, file moved/rewritten): keep intro
    used_add: set = set()
    keep: List[Tuple[str, str, str]] = []
    for rem in removals:
        for i, add in enumerate(additions):
            if i not in used_add and add[1] == rem[1] and _resite(led, rem, add):
                used_add.add(i)
                led.moves += 1
                break
        else:
            keep.append(rem)
    # remaining removals = promises paid
    for path, norm, _raw in keep:
        queue = led.pending.get(path, [])
        for i, p in enumerate(queue):
            if p.norm == norm:
                queue.pop(i)
                led.paid.append(Paid(p, commit.date, commit.sha,
                                     (commit.date.date() - p.intro_date.date()).days))
                break
        else:
            led.orphan_removals += 1
    # remaining additions = new promises
    for i, (path, norm, raw) in enumerate(additions):
        if i in used_add:
            continue
        led.pending.setdefault(path, []).append(
            Promise(path=path, marker=norm.split(" ", 1)[0], norm=norm,
                    text=re.sub(r"\s+", " ", raw).strip()[:160],
                    intro_date=commit.date, intro_commit=commit.sha,
                    author=commit.author, email=commit.email))


def _resite(led: Ledger, rem: Tuple[str, str, str], add: Tuple[str, str, str]) -> bool:
    """Carry a promise's intro date to its new home; False if it had none."""
    old_path, norm, _ = rem
    new_path = add[0]
    queue = led.pending.get(old_path, [])
    for i, p in enumerate(queue):
        if p.norm == norm:
            p = queue.pop(i)
            p.path = new_path
            led.pending.setdefault(new_path, []).append(p)
            return True
    return False


# ---------------------------------------------------------------------------
# Joining history with the working tree


@dataclass
class Report:
    as_of: date
    promises: List[Dict[str, object]]
    half_life: Optional[float]
    paid: int
    died: int
    moves: int
    orphans: int
    per_author: List[Dict[str, object]]
    dropped: int = 0          # in history but not in working tree
    uncommitted: int = 0      # in working tree but not in history
    paid_lifetimes: List[int] = field(default_factory=list)

    @property
    def zombies(self) -> List[Dict[str, object]]:
        return [p for p in self.promises if p.get("zombie")]

    @property
    def total_rot(self) -> float:
        return round(sum(float(p["rot"]) for p in self.promises), 1)

    def summary(self) -> Dict[str, object]:
        by_bucket: Dict[str, int] = {name: 0 for name, _ in BUCKETS}
        for p in self.promises:
            by_bucket[str(p["bucket"])] += 1
        return {
            "as_of": self.as_of.isoformat(),
            "promises": len(self.promises),
            "by_bucket": by_bucket,
            "zombies": len(self.zombies),
            "total_rot": self.total_rot,
            "half_life_days": (
                None if self.half_life is None
                else round(self.half_life, 1)
            ),
            "paid_promises": self.paid,
            "died_with_file": self.died,
            "resited_moves": self.moves,
            "dropped_uncommitted_removals": self.dropped,
            "uncommitted_promises": self.uncommitted,
            "orphan_removals": self.orphans,
        }


def build_report(root: str, excludes: Sequence[str],
                 as_of: Optional[date] = None) -> Report:
    led = build_ledger(root, excludes, as_of)
    today = as_of or date.today()
    half = led.half_life_days(excludes)
    thresh = zombie_threshold(half)

    promises: List[Dict[str, object]] = []
    dropped = uncommitted = 0
    if as_of is not None:
        # pure historical replay: history is authoritative
        for p in led.current(excludes):
            promises.append(_promise_row(p, today, p.path, None, thresh))
    else:
        hits = scan_tree(root, excludes)
        used: set = set()
        current = led.current(excludes)
        matched = 0
        for p in current:
            for i, h in enumerate(hits):
                if i not in used and h.path == p.path and h.norm == p.norm:
                    used.add(i)
                    promises.append(_promise_row(p, today, p.path, h.line, thresh))
                    matched += 1
                    break
        dropped = len(current) - matched
        uncommitted = len(hits) - len(used)
    paid = [x for x in led.paid if not _excluded(x.promise.path, excludes)]
    return Report(
        as_of=today, promises=promises,
        dropped=dropped, uncommitted=uncommitted,
        half_life=half, paid=len(paid),
        paid_lifetimes=sorted(x.lifetime_days for x in paid),
        died=len([x for x in led.died if not _excluded(x[0].path, excludes)]),
        moves=led.moves, orphans=led.orphan_removals,
        per_author=_per_author(led, excludes, today),
    )


def _promise_row(p: Promise, today: date, path: str,
                 line: Optional[int], thresh: Optional[int]) -> Dict[str, object]:
    age = (today - p.intro_date.date()).days
    row: Dict[str, object] = {
        "file": path,
        "line": line if line is not None else "",
        "marker": p.marker,
        "text": p.text,
        "author": "%s <%s>" % (p.author, p.email),
        "intro_date": p.intro_date.date().isoformat(),
        "intro_commit": p.intro_commit[:10],
        "age_days": age,
        "bucket": bucket_of(age),
        "weight": p.weight,
        "rot": rot_score(p.weight, age),
    }
    if thresh is not None:
        row["zombie"] = age > thresh
    return row


def _per_author(led: Ledger, excludes: Sequence[str],
                today: date) -> List[Dict[str, object]]:
    stats: Dict[str, Dict[str, int]] = {}
    out = led.current(excludes)
    for p in out:
        s = stats.setdefault(p.author, {"issued": 0, "paid": 0, "outstanding": 0})
        s["issued"] += 1
        s["outstanding"] += 1
    for x in led.paid:
        if _excluded(x.promise.path, excludes):
            continue
        s = stats.setdefault(x.promise.author, {"issued": 0, "paid": 0, "outstanding": 0})
        s["issued"] += 1
        s["paid"] += 1
    rows = []
    for author, s in stats.items():
        rows.append({
            "author": author,
            "issued": s["issued"],
            "paid": s["paid"],
            "outstanding": s["outstanding"],
            "unpaid_rate": round(1.0 * s["outstanding"] / s["issued"], 3) if s["issued"] else 0.0,
        })
    rows.sort(key=lambda r: (-r["outstanding"], r["author"]))
    return rows


# ---------------------------------------------------------------------------
# Rendering


def _fmt_date(d: date) -> str:
    return d.isoformat()


def render_scan(hits: List[Hit]) -> str:
    counts = {m: 0 for m in MARKER_WEIGHTS}
    for h in hits:
        counts[h.marker] += 1
    total_weight = sum(MARKER_WEIGHTS[h.marker] for h in hits)
    out = ["todo-rot scan — %d promise markers, total weight %d" % (len(hits), total_weight), ""]
    for m in MARKER_WEIGHTS:
        if counts[m]:
            out.append("  %-5s x%-3d weight %d each" % (m, counts[m], MARKER_WEIGHTS[m]))
    out.append("")
    for h in hits:
        out.append("  %-5s %s:%d  %s" % (h.marker, h.path, h.line, h.text[:90]))
    out.append("")
    out.append("Ages unknown from the filesystem alone — run `ledger` to date each promise.")
    return "\n".join(out)


def render_ledger(r: Report, top: int) -> str:
    s = r.summary()
    L = ["todo-rot ledger — promises outstanding as of %s" % s["as_of"], ""]

    if not r.promises:
        L.append("  No outstanding promises. Every promise made has been paid. Rare.")
        L.append("")
        L.append(_footer_stats(s))
        return "\n".join(L)

    L.append("-- Promise book -----------------------------------------")
    for name, _ in BUCKETS:
        n = int(s["by_bucket"][name])
        if n:
            bar = "#" * min(n, 40)
            L.append("  %-8s %-40s %3d promises" % (name, bar, n))
    if s["zombies"]:
        L.append("  ZOMBIE   %3d promises older than 2x half-life — will never be paid" % s["zombies"])
    L.append("  total rust on the books: %.1f" % s["total_rot"])
    L.append("")

    L.append("-- Oldest unpaid (top %d by rust) -----------------------" % top)
    rows = sorted(r.promises, key=lambda p: (
        -float(p.get("rot", 0)), -int(p.get("age_days", 0)), str(p.get("file", ""))))
    for p in rows[:top]:
        flag = " ZOMBIE" if p.get("zombie") else ""
        line = ":%s" % p["line"] if p.get("line", "") != "" else ""
        L.append("  %6.1f rot  %-8s %4dd%s  %s%s" % (
            p.get("rot", 0), p.get("marker", "?"), p.get("age_days", 0), flag,
            p.get("file", "?"), line))
        L.append("           %s" % str(p.get("text", ""))[:100])
        L.append("           promised by %s at %s (%s)" % (
            str(p.get("author", "?")).split(" <")[0],
            p.get("intro_date", "?"), p.get("intro_commit", "?")))
    L.append("")
    L.append(_footer_stats(s))
    return "\n".join(L)


def _footer_stats(s: Dict[str, object]) -> str:
    hl = s["half_life_days"]
    hl_txt = ("%g days" % hl) if hl is not None else "unknown — no promise ever paid here"
    return "\n".join([
        "-- Promise economics -----------------------------------",
        "  half-life of a paid promise : %s" % hl_txt,
        "  paid so far                 : %d   died with their file: %d" % (s["paid_promises"], s["died_with_file"]),
        "  re-sited (kept their age)   : %d   orphan removals: %d" % (s["resited_moves"], s["orphan_removals"]),
        "  uncommitted promises        : %d   uncommitted removals: %d" % (s["uncommitted_promises"], s["dropped_uncommitted_removals"]),
    ])


def render_halflife(r: Report) -> str:
    s = r.summary()
    L = ["todo-rot halflife — the survival economics of promises", ""]
    if r.paid == 0:
        L.append("  No promise in this history has ever been paid.")
        L.append("  Half-life unknown — every outstanding promise is unbounded risk.")
    else:
        hl = r.half_life
        L.append("  paid promises    : %d" % r.paid)
        if hl is not None:
            L.append("  median lifetime  : %g days (the project half-life)" % round(hl, 1))
            L.append("  mean / max       : %g / %d days" % (
                round(sum(r.paid_lifetimes) / len(r.paid_lifetimes), 1),
                r.paid_lifetimes[-1]))
            L.append("  zombie threshold : older than %d days" % zombie_threshold(hl))
        L.append("  zombies on book  : %d" % s["zombies"])
    L.append("")
    if r.per_author:
        L.append("-- Per-author ledger (issued vs paid) --------------------")
        L.append("  %-20s %7s %7s %11s %7s" % ("author", "issued", "paid", "outstanding", "unpaid%"))
        for a in r.per_author:
            L.append("  %-20s %7d %7d %11d %6.0f%%" % (
                a["author"][:20], a["issued"], a["paid"], a["outstanding"], 100 * a["unpaid_rate"]))
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--as-of", help="pin 'today' (YYYY-MM-DD) for reproducible reports")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--exclude", action="append", default=[],
                        help="path prefix to skip (repeatable)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="todo_rot.py",
        description="todo-rot — 承诺锈蚀: age TODO/FIXME/HACK/XXX promises like debt.")
    sub = ap.add_subparsers(dest="cmd", metavar="{scan,ledger,halflife,audit}")

    p = sub.add_parser("scan", help="working-tree sweep, no git needed")
    _common(p)

    p = sub.add_parser("ledger", help="age every promise, score rot, flag zombies")
    _common(p)
    p.add_argument("--top", type=int, default=15)

    p = sub.add_parser("halflife", help="survival stats: paid lifetimes, per-author ledger")
    _common(p)

    p = sub.add_parser("audit", help="CI gate: fail when rot exceeds budget")
    _common(p)
    p.add_argument("--max-zombies", type=int, default=0)
    p.add_argument("--max-ancient", type=int, default=-1,
                   help="max ANCIENT promises allowed (-1 = unlimited)")
    p.add_argument("--max-rot", type=float, default=-1.0,
                   help="max total rust allowed (-1 = unlimited)")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2

    root = os.getcwd()
    as_of = date.fromisoformat(args.as_of) if args.as_of else None

    if args.cmd == "scan":
        hits = scan_tree(root, args.exclude)
        if args.format == "json":
            print(json.dumps({"root": root, "count": len(hits),
                              "markers": MARKER_WEIGHTS,
                              "hits": [h.as_dict() for h in hits]},
                             indent=2, ensure_ascii=False))
        else:
            print(render_scan(hits))
        return 0

    top = toplevel(root)
    if top is None:
        print("todo-rot: not a git repository (scan works without git)", file=sys.stderr)
        return 2
    root = top

    report = build_report(root, args.exclude, as_of)

    if args.cmd == "ledger":
        if args.format == "json":
            print(json.dumps({"summary": report.summary(),
                              "promises": sorted(
                                  report.promises,
                                  key=lambda p: (-float(p["rot"]), str(p["file"]))),
                              "per_author": report.per_author},
                             indent=2, ensure_ascii=False))
        else:
            print(render_ledger(report, args.top))
        return 0

    if args.cmd == "halflife":
        if args.format == "json":
            print(json.dumps({"summary": report.summary(),
                              "per_author": report.per_author},
                             indent=2, ensure_ascii=False))
        else:
            print(render_halflife(report))
        return 0

    # audit
    s = report.summary()
    breaches = []
    if len(report.zombies) > args.max_zombies:
        breaches.append("zombies %d > budget %d" % (len(report.zombies), args.max_zombies))
    if args.max_ancient >= 0 and int(s["by_bucket"]["ANCIENT"]) > args.max_ancient:
        breaches.append("ANCIENT %d > budget %d" % (s["by_bucket"]["ANCIENT"], args.max_ancient))
    if args.max_rot >= 0 and float(s["total_rot"]) > args.max_rot:
        breaches.append("total rot %.1f > budget %.1f" % (s["total_rot"], args.max_rot))
    if args.format == "json":
        print(json.dumps({"summary": s, "breaches": breaches,
                          "verdict": "FAIL" if breaches else "PASS"},
                         indent=2, ensure_ascii=False))
    else:
        for b in breaches:
            print("BUDGET BREACH: %s" % b)
        print("audit: %s (%d promises, %d zombies, rust %.1f)" % (
            "FAIL" if breaches else "PASS", s["promises"], s["zombies"], s["total_rot"]))
    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
