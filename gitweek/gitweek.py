#!/usr/bin/env python3
"""
gitweek — the invisible work archaeologist / 不可见工作考古学家.

Rebuild "what did I actually do last week" from git history across one or
many repos, and explicitly surfaces the *invisible work* (tests, docs,
refactors, chores) that weekly reports systematically forget.

Zero dependencies: Python 3.8+ stdlib + a normal `git` binary.
All data stays local; nothing leaves the machine.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

VERSION = "1.0.0"

# ---------------------------------------------------------------- tunables
WINDOW_DAYS = 7            # default report window: [as_of - 6, as_of], inclusive
DEFAULT_TOP_FILES = 3      # how many "hottest files" to show
INV_LIST_CAP = 8           # max invisible-work commits listed per category

VISIBLE_CATEGORIES = ("feat", "fix")            # the work weekly reports remember
CATEGORY_ORDER = ("feat", "fix", "perf", "refactor", "test",
                  "docs", "ci", "build", "chore", "style", "other")
INVISIBLE_CATEGORIES = ("perf", "refactor", "test", "docs",
                        "ci", "build", "chore", "style")   # the work they forget

CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore)"
    r"(\([^)]*\))?(!)?\s*:\s*(.*)", re.IGNORECASE)

# Ordered keyword fallback on the subject (lowercased). Specific before generic:
# "add tests for X" must hit `test`, not the generic `feat` keyword "add".
# Short/ambiguous English tokens are word-bounded so "decision" doesn't
# contain "ci" and "address" doesn't contain "add".
KEYWORD_RULES = [
    ("test",     r"\btests?\b|\bspecs?\b|测试|用例"),
    ("docs",     r"\bdocs?\b|\breadme\b|文档|注释"),
    ("fix",      r"\bfix\w*|\bbugs?\b|\bhotfix(es)?\b|\bpatch\w*|修复|崩溃"),
    ("ci",       r"\bci\b|\bjenkins\b|\bpipeline\b|流水线"),
    ("chore",    r"\bdeps?\b|\bdepend\w*|\bbump\w*|\bupgrad\w*|\bcleanup\b|"
                 r"\bclean[- ]up\b|依赖|升级|清理|杂务"),
    ("refactor", r"\brefactor\w*|\brename\w*|重构|重命名"),
    ("perf",     r"\bperf\w*|\boptimi\w*|性能|提速|优化"),
    ("feat",     r"\badds?\b|\badded\b|\bsupport\w*|\bfeature\w*|\bintro\w*|"
                 r"新增|实现|支持|引入"),
]
KEYWORD_RES = [(cat, re.compile(pat, re.IGNORECASE)) for cat, pat in KEYWORD_RULES]

# Ordered path fallback, applied when neither prefix nor keywords matched.
PATH_RULES = [
    ("test",  r"(^|/)(tests?|spec)/|[_.]test\.[a-z0-9]+$|test_[a-z0-9]+\.[a-z0-9]+$"),
    ("docs",  r"\.md$|(^|/)docs?/"),
    ("ci",    r"(^|/)\.github/(workflows|actions)/|(^|/)\.gitlab-ci|^Jenkinsfile$"),
    ("chore", r"package-lock\.json$|yarn\.lock$|pnpm-lock\.yaml$|poetry\.lock$|"
              r"Pipfile\.lock$|(^|/)requirements[a-z.-]*\.txt$|\.gitignore$"),
]

SHORTSTAT_RE = re.compile(
    r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

RS, US = "\x1e", "\x1f"    # record / unit separators for git log parsing


class GitweekError(Exception):
    """User-facing error: printed to stderr, exit code 1."""


# ---------------------------------------------------------------- data model
@dataclass
class Commit:
    hash: str
    short: str
    date: datetime          # commit date (when it landed, not author date)
    author: str
    email: str
    subject: str
    files: list = field(default_factory=list)   # [(path, ins, dels)]
    category: str = ""


@dataclass
class RepoResult:
    name: str
    path: str
    commits: list = field(default_factory=list)
    wip: dict = None        # {files, insertions, deletions, untracked}
    note: str = ""          # e.g. "idle", "no commits yet", error text


# ---------------------------------------------------------------- git plumbing
def run_git(repo, *args, check=True):
    """Run `git -C repo ...` and return stdout; raise GitweekError on failure."""
    cmd = ["git", "-C", str(repo), "-c", "core.quotepath=false"] + list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitweekError(f"git {' '.join(args[:2])} failed in {repo}: "
                           f"{proc.stderr.strip()}")
    return proc.stdout


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists() or path.name.endswith(".git")


def find_repos(paths, scan=False):
    """Resolve user-supplied paths into git repo paths.

    A path that is itself a repo is used directly. A non-repo path with
    --scan is treated as a workspace root and searched one level deep.
    """
    repos = []
    for p in paths:
        p = Path(p).expanduser().resolve()
        if not p.is_dir():
            raise GitweekError(f"not a directory: {p}")
        if is_git_repo(p):
            repos.append(p)
        elif scan:
            found = sorted(c for c in p.iterdir() if c.is_dir() and is_git_repo(c))
            if not found:
                raise GitweekError(f"no git repos found one level under {p}")
            repos.extend(found)
        else:
            raise GitweekError(
                f"not a git repo: {p} (use --scan to search it as a workspace root)")
    return repos


def repo_identity(repo) -> str:
    """Default author pattern = this repo's own configured identity."""
    name = run_git(repo, "config", "user.name", check=False).strip()
    email = run_git(repo, "config", "user.email", check=False).strip()
    if not name and not email:
        raise GitweekError(
            f"{repo.name}: no user.name/user.email configured — pass --author")
    parts = [re.escape(x) for x in (name, email) if x]
    return "|".join(parts)


def has_commits(repo) -> bool:
    return run_git(repo, "rev-parse", "-q", "--verify", "HEAD",
                   check=False).strip() != ""


def parse_log(text):
    """Parse `git log --numstat --pretty=format:RS...US...` output."""
    commits = []
    for record in text.split(RS):
        record = record.strip("\n")
        if not record.strip():
            continue
        lines = record.split("\n")
        h, short, cdate, an, ae, subject = (lines[0].split(US) + [""] * 6)[:6]
        when = datetime.fromisoformat(cdate) if cdate else datetime.min
        files = []
        for line in lines[1:]:
            m = re.match(r"^(\d+|-)\t(\d+|-)\t(.+)$", line)
            if m:
                ins = int(m.group(1)) if m.group(1).isdigit() else 0
                dels = int(m.group(2)) if m.group(2).isdigit() else 0
                files.append((m.group(3), ins, dels))
        commits.append(Commit(hash=h, short=short, date=when, author=an,
                              email=ae, subject=subject, files=files))
    return commits


def collect_repo(repo, since: date, until: date, author=None, no_status=False):
    """Return a RepoResult: my commits in [since, until] + uncommitted WIP."""
    name = repo.name
    if not has_commits(repo):
        return RepoResult(name=name, path=str(repo), note="no commits yet")

    pattern = author if author else repo_identity(repo)
    try:
        author_re = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise GitweekError(f"invalid author pattern {pattern!r}: {e}")
    # Ask git for a generous window, then filter precisely in Python so the
    # inclusive [since, until] range is timezone-proof and deterministic.
    # (Author matching also happens in Python: git's --author uses POSIX basic
    # regex, which has no alternation and can't express "name OR email".)
    wide_since = (since - timedelta(days=2)).isoformat()
    wide_until = (until + timedelta(days=2)).isoformat()
    out = run_git(
        repo, "log", "--all", "--no-merges", "--no-renames", "--numstat",
        "--date=iso-strict",
        "--pretty=format:" + RS + US.join(("%H", "%h", "%cI", "%an", "%ae", "%s")),
        f"--since={wide_since}", f"--until={wide_until}",
    )
    commits = [c for c in parse_log(out)
               if since <= c.date.date() <= until
               and author_re.search(f"{c.author} <{c.email}>")]
    for c in commits:
        c.category = classify(c.subject, [f for f, _, _ in c.files])
    commits.sort(key=lambda c: (c.date, c.hash))

    wip = None if no_status else collect_wip(repo)
    note = "idle" if not commits else ""
    return RepoResult(name=name, path=str(repo), commits=commits, wip=wip, note=note)


def collect_wip(repo):
    """Uncommitted work: staged+unstaged shortstat plus untracked files."""
    def shortstat(*args):
        m = SHORTSTAT_RE.search(run_git(repo, "diff", "--shortstat", *args))
        if not m:
            return (0, 0, 0)
        return tuple(int(x) if x else 0 for x in m.groups())

    f1, i1, d1 = shortstat()              # unstaged
    f2, i2, d2 = shortstat("--cached")    # staged
    untracked = sum(1 for l in run_git(repo, "status", "--porcelain").splitlines()
                    if l.startswith("??"))
    files, ins, dels = f1 + f2, i1 + i2, d1 + d2
    if files == 0 and untracked == 0:
        return None
    return {"files": files, "insertions": ins, "deletions": dels,
            "untracked": untracked}


# ---------------------------------------------------------------- classification
def classify(subject: str, files) -> str:
    """Deterministic 3-layer classification: prefix → keywords → file paths."""
    m = CONVENTIONAL_RE.match(subject.strip())
    if m:
        return m.group(1).lower()
    for cat, regex in KEYWORD_RES:
        if regex.search(subject):
            return cat
    for cat, pattern in PATH_RULES:
        if any(re.search(pattern, f, re.IGNORECASE) for f in files):
            return cat
    return "other"


# ---------------------------------------------------------------- window & stats
def default_window(as_of: date):
    return as_of - timedelta(days=WINDOW_DAYS - 1), as_of


def summarize(results):
    """Aggregate repos into global counts used by every output format."""
    commits = [c for r in results for c in r.commits]
    cat_counts = Counter(c.category for c in commits)
    classified = sum(n for cat, n in cat_counts.items() if cat != "other")
    invisible = sum(n for cat, n in cat_counts.items()
                    if cat in INVISIBLE_CATEGORIES)
    files = Counter()
    for c in commits:
        for path, ins, dels in c.files:
            churn = files[path]
            files[path] = (churn[0] + 1, churn[1] + ins, churn[2] + dels) \
                if churn else (1, ins, dels)
    days = Counter(c.date.date() for c in commits)
    return {
        "repos": results,
        "commits": commits,
        "total": len(commits),
        "insertions": sum(i for c in commits for _, i, _ in c.files),
        "deletions": sum(d for c in commits for _, _, d in c.files),
        "files_touched": len(files),
        "active_days": len(days),
        "by_day": days,
        "cat_counts": cat_counts,
        "invisible": invisible,
        "invisible_ratio": (invisible / classified) if classified else 0.0,
        "hot_files": sorted(files.items(), key=lambda kv: (-kv[1][0], kv[0])),
        "wip_repos": [r for r in results if r.wip],
        "active_repos": [r for r in results if r.commits],
        "idle_repos": [r for r in results if not r.commits],
        "noted_repos": [r for r in results if r.note],
    }


# ---------------------------------------------------------------- rendering
def _bar(count, max_count, width=10):
    if max_count == 0 or count == 0:
        return "·" * width
    return "█" * max(1, round(count / max_count * width))


def _fmt_wip(w):
    plural = "s" if w["files"] != 1 else ""
    s = f"{w['files']} file{plural} (+{w['insertions']}/-{w['deletions']})"
    if w["untracked"]:
        s += f", {w['untracked']} untracked"
    return s


def render_text(s, since, until, top=DEFAULT_TOP_FILES):
    L = []
    span = (until - since).days + 1
    L.append("gitweek — 不可见工作考古报告")
    L.append(f"Period : {since} .. {until} ({span} days)")
    idle_txt = f"{len(s['idle_repos'])} idle" if s["idle_repos"] else "0 idle"
    L.append(f"Repos  : {len(s['repos'])} scanned · {len(s['active_repos'])} "
             f"active · {idle_txt}")
    L.append("")
    L.append("── Overview " + "─" * 29)
    L.append(f"  commits         {s['total']}")
    L.append(f"  files touched   {s['files_touched']}")
    L.append(f"  insertions      +{s['insertions']}")
    L.append(f"  deletions       -{s['deletions']}")
    L.append(f"  active days     {s['active_days']}/{span}")
    if s["total"]:
        L.append(f"  invisible share {s['invisible_ratio']:.0%} of classified commits "
                 f"(test/docs/refactor/chore/...)")
    for r in s["noted_repos"]:
        L.append(f"  [{r.note}] {r.name}")
    L.append("")

    if not s["total"]:
        L.append("No commits in this window. Either you were on a well-earned")
        L.append("break, or your identity didn't match — try --author.")
        for r in s["repos"]:
            if r.wip:
                L.append(f"  WIP: {r.name}: {_fmt_wip(r.wip)}")
        return "\n".join(L)

    L.append("── Work shape " + "─" * 27)
    max_count = max(s["cat_counts"].values())
    total = s["total"]
    for cat in CATEGORY_ORDER:
        n = s["cat_counts"].get(cat, 0)
        if not n:
            continue
        mark = "  ← invisible" if cat in INVISIBLE_CATEGORIES else ""
        L.append(f"  {cat:<9} {_bar(n, max_count)} {n:>3} {n / total:>4.0%}{mark}")
    L.append("")

    L.append("── Invisible work — 别忘了写进周报 " + "─" * 8)
    inv_commits = [c for c in s["commits"] if c.category in INVISIBLE_CATEGORIES]
    if inv_commits:
        by_cat = {}
        for c in inv_commits:
            by_cat.setdefault(c.category, []).append(c)
        for cat in CATEGORY_ORDER:
            group = by_cat.get(cat)
            if not group:
                continue
            L.append(f"  {cat} ×{len(group)}")
            for c in group[:INV_LIST_CAP]:
                repo = _repo_of(s, c)
                L.append(f"    • {c.date:%m-%d}  {repo:<10} {c.short}  {c.subject}")
            if len(group) > INV_LIST_CAP:
                L.append(f"    ... and {len(group) - INV_LIST_CAP} more")
        classified = s["total"] - s["cat_counts"].get("other", 0)
        L.append(f"  → {s['invisible']}/{classified} classified commits "
                 f"({s['invisible_ratio']:.0%}) were maintenance work.")
    else:
        L.append("  (none this week)")
    L.append("")

    L.append("── Daily activity " + "─" * 23)
    for i in range(span):
        d = since + timedelta(days=i)
        n = s["by_day"].get(d, 0)
        L.append(f"  {WEEKDAY_NAMES[d.weekday()]} {d:%m-%d}  "
                 f"{_bar(n, max(s['by_day'].values()) if s['by_day'] else 0, 6)} {n}")
    L.append("")

    hot = s["hot_files"][:top]
    if hot:
        L.append(f"── Hottest files (top {len(hot)}) " + "─" * 13)
        for i, (path, (touches, ins, dels)) in enumerate(hot, 1):
            L.append(f"  {i}. {path}  ({touches} touches, +{ins}/-{dels})")
        L.append("")

    if s["wip_repos"]:
        L.append("── Work in progress (uncommitted) " + "─" * 6)
        for r in s["wip_repos"]:
            L.append(f"  {r.name}: {_fmt_wip(r.wip)}")
        L.append("")

    L.append("── All commits " + "─" * 27)
    for c in sorted(s["commits"], key=lambda c: (c.date, c.hash)):
        repo = _repo_of(s, c)
        L.append(f"  {c.date:%m-%d}  {repo:<10} {c.short}  [{c.category:<4}] {c.subject}")
    return "\n".join(L)


def _repo_of(s, commit):
    for r in s["repos"]:
        if any(c is commit or c.hash == commit.hash for c in r.commits):
            return r.name
    return "?"


def render_md(s, since, until):
    L = [f"# 周报草稿 · {since} – {until}", ""]
    L.append("> 由 gitweek 从 git 历史自动生成。请把「活动」改写成「成果」再提交，")
    L.append("> 尤其是下面那节「不可见工作」。")
    L.append("")
    if not s["total"]:
        L.append("本周窗口内没有匹配的提交。")
        return "\n".join(L)
    L.append("## 本周概览")
    L.append(f"- **{s['total']}** commits · **{s['active_days']}** 个活跃日 · "
             f"**{len(s['active_repos'])}** 个仓库")
    L.append(f"- 代码变更：**+{s['insertions']} / -{s['deletions']}**，"
             f"涉及 **{s['files_touched']}** 个文件")
    L.append(f"- 不可见工作占比：**{s['invisible_ratio']:.0%}**"
             f"（test/docs/refactor/chore…）")
    L.append("")
    L.append("## 主要成果（feat / fix）")
    for c in sorted(s["commits"], key=lambda c: (c.date, c.hash)):
        if c.category in VISIBLE_CATEGORIES:
            L.append(f"- `{_repo_of(s, c)}` {c.subject}")
    L.append("")
    L.append("## 不可见工作（容易忘掉的部分）")
    inv = [c for c in s["commits"] if c.category in INVISIBLE_CATEGORIES]
    if inv:
        for c in sorted(inv, key=lambda c: (c.category, c.date)):
            L.append(f"- `{_repo_of(s, c)}` {c.subject}")
        L.append("")
        L.append(f"> 本周 {s['invisible_ratio']:.0%} 的提交是维护性工作——"
                 f"测试、文档、重构、杂务。它们让系统活着，值得一行。")
    else:
        L.append("- 本周无维护性提交。")
    L.append("")
    if s["wip_repos"]:
        L.append("## 进行中（WIP）")
        for r in s["wip_repos"]:
            L.append(f"- `{r.name}`：{_fmt_wip(r.wip)} 未提交")
        L.append("")
    L.append("## 下周计划")
    L.append("- （手写）")
    L.append("")
    L.append("## 附录：提交明细")
    L.append("| 日期 | 仓库 | 类别 | 提交 |")
    L.append("|---|---|---|---|")
    for c in sorted(s["commits"], key=lambda c: (c.date, c.hash)):
        L.append(f"| {c.date:%m-%d} | {_repo_of(s, c)} | {c.category} | {c.subject} |")
    return "\n".join(L)


def render_json(s, since, until):
    def commit_json(c, repo_name):
        return {"hash": c.hash, "short": c.short, "date": c.date.isoformat(),
                "author": c.author, "subject": c.subject, "category": c.category,
                "repo": repo_name,
                "files": [{"path": p, "insertions": i, "deletions": d}
                          for p, i, d in c.files]}
    return json.dumps({
        "period": {"since": since.isoformat(), "until": until.isoformat()},
        "summary": {
            "repos": len(s["repos"]), "active_repos": len(s["active_repos"]),
            "commits": s["total"], "files_touched": s["files_touched"],
            "insertions": s["insertions"], "deletions": s["deletions"],
            "active_days": s["active_days"],
            "category_counts": dict(s["cat_counts"]),
            "invisible_commits": s["invisible"],
            "invisible_ratio": round(s["invisible_ratio"], 4),
        },
        "repos": [{
            "name": r.name, "path": r.path, "note": r.note,
            "wip": r.wip,
            "commits": [commit_json(c, r.name) for c in r.commits],
        } for r in s["repos"]],
        "hot_files": [{"path": p, "touches": t, "insertions": i, "deletions": d}
                      for p, (t, i, d) in s["hot_files"]],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- command
def cmd_report(paths, scan=False, author=None, since=None, until=None,
               fmt="text", as_of=None, top=DEFAULT_TOP_FILES, no_status=False):
    as_of = as_of or date.today()
    until = until or as_of
    since = since or default_window(until)[0]
    if since > until:
        raise GitweekError(f"--since ({since}) is after --until ({until})")

    repos = find_repos(paths, scan=scan)
    results, errors = [], []
    for repo in repos:
        try:
            results.append(collect_repo(repo, since, until,
                                        author=author, no_status=no_status))
        except GitweekError as e:
            errors.append(str(e))
    if not results:
        raise GitweekError("no repos could be scanned:\n  " + "\n  ".join(errors))

    s = summarize(results)
    if fmt == "text":
        out = render_text(s, since, until, top=top)
    elif fmt == "md":
        out = render_md(s, since, until)
    elif fmt == "json":
        out = render_json(s, since, until)
    else:
        raise GitweekError(f"unknown format: {fmt}")
    if errors:
        out += "\n\n[skipped] " + "\n[skipped] ".join(errors)
    return out


# ---------------------------------------------------------------- CLI
def _iso_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}, expected YYYY-MM-DD")


def build_parser():
    p = argparse.ArgumentParser(
        prog="gitweek",
        description="gitweek — 不可见工作考古学家：从 git 历史重建你的一周，"
                    "浮出周报最容易遗忘的维护性工作（test/docs/refactor/chore）。",
        epilog="examples:\n"
               "  gitweek report                          # 最近 7 天，当前仓库\n"
               "  gitweek report --scan -p ~/dev          # 工作区下所有仓库\n"
               "  gitweek report --since 2026-08-03 --format md   # 周报草稿\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"gitweek {VERSION}")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("report", help="rebuild a period of work from git history")
    r.add_argument("-p", "--path", action="append", default=[],
                   metavar="DIR", help="repo or workspace dir (repeatable, default: .)")
    r.add_argument("--scan", action="store_true",
                   help="treat non-repo PATH as workspace root; search 1 level deep")
    r.add_argument("--author", metavar="PATTERN",
                   help="author name/email pattern (default: each repo's own identity)")
    r.add_argument("--since", type=_iso_date, metavar="YYYY-MM-DD",
                   help=f"window start (default: until - {WINDOW_DAYS - 1} days)")
    r.add_argument("--until", type=_iso_date, metavar="YYYY-MM-DD",
                   help="window end, inclusive (default: today)")
    r.add_argument("--as-of", type=_iso_date, metavar="YYYY-MM-DD",
                   help="pretend today is this date (for deterministic output)")
    r.add_argument("--format", choices=("text", "md", "json"), default="text",
                   help="text: report · md: paste-ready weekly draft · json: machine")
    r.add_argument("--top", type=int, default=DEFAULT_TOP_FILES, metavar="N",
                   help=f"hottest files to show (default {DEFAULT_TOP_FILES})")
    r.add_argument("--no-status", action="store_true",
                   help="skip uncommitted-WIP detection")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd != "report":
        build_parser().print_help()
        return 2
    try:
        print(cmd_report(
            paths=args.path or ["."],
            scan=args.scan, author=args.author,
            since=args.since, until=args.until, fmt=args.format,
            as_of=args.as_of, top=args.top, no_status=args.no_status,
        ))
    except GitweekError as e:
        print(f"gitweek: error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
