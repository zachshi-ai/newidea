#!/usr/bin/env python3
"""
doc_drift — the doc-rot compiler / 文档漂移检测器.

Code has compilers and tests as gatekeepers; documentation has nothing.
Markdown rots silently — files get renamed, symbols move, examples stop
working — and nobody notices until a newcomer trips over it.

doc_drift gives docs a gatekeeper:

  1. Reference integrity — repo paths, local links and `path::Symbol`
     references found in markdown are verified to still exist.
  2. Freshness stamps — claims can carry `<!-- verified: YYYY-MM-DD; ttl: Nd -->`;
     an expired stamp means "nobody re-checked this claim lately" (WARN).

Exit codes are CI-friendly: 0 = docs consistent, 1 = drift found,
2 = usage error.

Zero dependencies: Python 3.8+ standard library only.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
import urllib.parse
from collections import namedtuple
from datetime import date, timedelta
from pathlib import Path

VERSION = "1.0.0"
PROG = "doc-drift"

# ------------------------------------------------------------------ tunables
DEFAULT_TTL_DAYS = 180                      # default freshness TTL for stamps
MARKDOWN_SUFFIXES = (".md", ".markdown")

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".idea", ".vscode",
}

# ------------------------------------------------------------------ patterns
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
LINK_RE = re.compile(r"\[([^\]]*)\]\(\s*([^)\s]+)[^)]*\)")
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
MULTI_SPAN_RE = re.compile(r"(?<!`)(`{2,})(.*?)\1(?!`)")
URL_RE = re.compile(r"(?:https?|ftp)://\S+|mailto:\S+|data:\S+")

# "some/dir/name.ext" — at least one slash, ends in a short extension.
SLASH_PATH_RE = re.compile(
    r"(?<![\w.~/@+-])(?:[\w.@+-]+/)+[\w.@+-]+\.[A-Za-z][A-Za-z0-9]{0,9}"
    r"(?![\w.@+-])")

# "name.ext" — bare filenames are trusted only inside code (higher precision).
BARE_FILE_RE = re.compile(
    r"(?<![\w.~/@+-])[\w.@+-]+\."
    r"(?:py|pyi|md|markdown|json|txt|sh|bash|zsh|fish|toml|yaml|yml|cfg|ini|"
    r"conf|js|jsx|ts|tsx|mjs|cjs|go|rs|rb|java|kt|c|h|cpp|hpp|cc|sql|proto|"
    r"html|htm|css|scss)\b",
    re.IGNORECASE)

# `path/to/file.py::symbol_name` inside a code span → symbol reference.
# The file part must end in an extension, so prose like `path::Symbol` stays prose.
SYMBOL_REF_RE = re.compile(
    r"^([\w.@+-]+(?:/[\w.@+-]+)*\.[A-Za-z0-9]{1,10})::(\w+)$")

# <!-- verified: 2026-08-16; ttl: 90d -->   (ttl optional, "fresh" is a synonym)
STAMP_RE = re.compile(
    r"<!--\s*(?:verified|fresh)\s*:\s*(\d{4}-\d{2}-\d{2})"
    r"(?:\s*[;,]\s*ttl\s*[:=]\s*(\d{1,5})\s*d?\s*)?\s*-->", re.IGNORECASE)

# <!-- dd:ignore: why this line is exempt -->  (works on any line)
IGNORE_RE = re.compile(r"<!--\s*dd:ignore(?::\s*([^>]*?))?\s*-->", re.IGNORECASE)

EXTERNAL_PREFIXES = ("http://", "https://", "ftp://", "mailto:", "data:", "tel:",
                     "#", "//")

Ref = namedtuple("Ref", "line kind value origin")   # kind: link|path|symbol


# ----------------------------------------------------------------- extraction
def strip_urls(text: str) -> str:
    return URL_RE.sub(" ", text)


def path_tokens(content: str):
    """File-ish tokens inside a chunk of code text (slash paths + bare names)."""
    cleaned = strip_urls(content)
    seen, out = set(), []
    for rx in (SLASH_PATH_RE, BARE_FILE_RE):
        for tok in rx.findall(cleaned):
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def parse_markdown(text: str):
    """Extract verifiable references from markdown text.

    Returns (refs, stamps): refs are Ref tuples to existence-check; stamps
    are (line, date_str, ttl_str_or_None) freshness claims.
    """
    refs, stamps = [], []
    in_fence = None           # fence marker char while inside a fence
    fence_exempt = False      # fence opened with "dd:ignore" in its info string
    for ln, line in enumerate(text.splitlines(), 1):
        fence = FENCE_OPEN_RE.match(line)
        if in_fence is not None:
            if fence and fence.group(1).startswith(in_fence):
                in_fence = None                       # fence closes
                fence_exempt = False
            elif not fence_exempt and not IGNORE_RE.search(line):
                for tok in path_tokens(line):
                    refs.append(Ref(ln, "path", tok, "fenced block"))
            continue
        if fence:
            in_fence = fence.group(1)[0]              # fence opens
            fence_exempt = "dd:ignore" in line[fence.end():].lower()
            continue
        if IGNORE_RE.search(line):
            continue

        for sm in STAMP_RE.finditer(line):
            stamps.append((ln, sm.group(1), sm.group(2)))

        # blank out code first (multi-backtick spans, then single) so markdown
        # links inside code are not parsed as links
        codes = []

        def _blank(rx):
            def repl(m):
                codes.append(m.group(2) if m.lastindex and m.lastindex >= 2
                             else m.group(1))
                return "\x00" * len(m.group(0))
            return repl

        blanked = MULTI_SPAN_RE.sub(_blank(MULTI_SPAN_RE), line)
        blanked = CODE_SPAN_RE.sub(_blank(CODE_SPAN_RE), blanked)

        links = []
        blanked = LINK_RE.sub(
            lambda m: (links.append(m.group(2)), " " * len(m.group(0)))[1], blanked)
        for target in links:
            if not target.lower().startswith(EXTERNAL_PREFIXES):
                refs.append(Ref(ln, "link", target, "link"))

        for content in codes:
            stripped = content.strip()
            sym = SYMBOL_REF_RE.match(stripped)
            if sym:
                refs.append(Ref(ln, "symbol", (sym.group(1), sym.group(2)), "code span"))
                continue
            for tok in path_tokens(content):
                refs.append(Ref(ln, "path", tok, "code span"))

        for tok in SLASH_PATH_RE.findall(strip_urls(blanked)):
            refs.append(Ref(ln, "path", tok, "prose"))
    return refs, stamps


# ------------------------------------------------------------------ verifying
def resolve_ref(value: str, bases):
    """First existing path among bases for value, or None."""
    v = value.split("#", 1)[0].split("?", 1)[0].strip()
    v = urllib.parse.unquote(v)
    if not v:
        return None, ""
    v = v.lstrip("/")                    # site-absolute links → repo-relative
    for base in bases:
        cand = base / v
        if cand.exists():
            return cand, v
    return None, v


def verify(md_file: Path, refs, stamps, root: Path, today: date, default_ttl: int):
    """Turn refs + stamps into issues. Returns (issues, refs_checked)."""
    issues = []
    bases = [md_file.parent, root]
    rel = _rel(md_file, root)
    seen = set()
    checked = 0

    for ref in refs:
        key = (ref.line, ref.kind, ref.value)
        if key in seen:
            continue
        seen.add(key)
        checked += 1
        if ref.kind == "link":
            found, v = resolve_ref(ref.value, bases)
            if not found and v:
                code = "missing-dir" if v.endswith("/") else "missing-file"
                issues.append(_issue(rel, ref.line, "ERROR", code, v,
                                     f"referenced in {ref.origin}"))
        elif ref.kind == "path":
            found, v = resolve_ref(ref.value, bases)
            if not found:
                issues.append(_issue(rel, ref.line, "ERROR", "missing-file", v,
                                     f"referenced in {ref.origin}"))
        else:                                       # symbol
            path_v, sym = ref.value
            found, v = resolve_ref(path_v, bases)
            if not found:
                issues.append(_issue(rel, ref.line, "ERROR", "missing-file", v,
                                     f"referenced in {ref.origin}"))
            else:
                body = found.read_text(encoding="utf-8", errors="replace")
                if not re.search(r"\b%s\b" % re.escape(sym), body):
                    issues.append(_issue(rel, ref.line, "ERROR", "missing-symbol",
                                          f"{v}::{sym}",
                                          f"symbol not found (from {ref.origin})"))

    for ln, date_str, ttl_str in stamps:
        checked += 1
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            issues.append(_issue(rel, ln, "ERROR", "invalid-stamp", date_str,
                                 "not a real calendar date"))
            continue
        if d > today:
            issues.append(_issue(rel, ln, "ERROR", "future-stamp", date_str,
                                 "verified date is in the future"))
            continue
        ttl = int(ttl_str) if ttl_str else default_ttl
        expiry = d + timedelta(days=ttl)
        if today > expiry:
            overdue = (today - expiry).days
            issues.append(_issue(rel, ln, "WARN", "stale", date_str,
                                 f"ttl {ttl}d expired {overdue}d ago"))
    return issues, checked


def _issue(file, line, severity, code, ref, note):
    return {"file": file, "line": line, "severity": severity, "code": code,
            "ref": str(ref), "note": note}


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# -------------------------------------------------------------------- scanning
def is_excluded(rel: Path, patterns) -> bool:
    s = str(rel)
    return any(fnmatch.fnmatch(s, pat)
               or any(fnmatch.fnmatch(part, pat) for part in rel.parts)
               for pat in patterns)


def collect_markdown(paths, root: Path, excludes):
    files = set()
    for p in paths:
        rp = Path(p).resolve()
        if rp.is_file():
            if rp.name.lower().endswith(MARKDOWN_SUFFIXES):
                files.add(rp)
        elif rp.is_dir():
            for dirpath, dirnames, filenames in os.walk(rp):
                rel_dir = Path(dirpath).relative_to(root)
                dirnames[:] = [d for d in sorted(dirnames)
                               if d not in SKIP_DIRS
                               and not is_excluded(rel_dir / d, excludes)]
                for fn in sorted(filenames):
                    if fn.lower().endswith(MARKDOWN_SUFFIXES):
                        f = Path(dirpath) / fn
                        if not is_excluded(f.relative_to(root), excludes):
                            files.add(f)
        else:
            raise FileNotFoundError(str(p))
    return sorted(files)


def run_scan(paths, excludes, today: date, default_ttl: int, root=None):
    """Scan markdown under paths. Returns a result dict (report/JSON ready)."""
    resolved = [Path(p).resolve() for p in paths]
    if root is None:
        try:
            root = Path(os.path.commonpath(resolved))
        except ValueError:
            root = Path.cwd().resolve()
    else:
        root = Path(root).resolve()

    files = collect_markdown(resolved, root, excludes)
    result = {
        "as_of": today.isoformat(),
        "root": str(root),
        "files_scanned": len(files),
        "files": [_rel(f, root) for f in files],
        "refs_checked": 0,
        "errors": 0,
        "warnings": 0,
        "issues": [],
    }
    for md in files:
        text = md.read_text(encoding="utf-8", errors="replace")
        refs, stamps = parse_markdown(text)
        issues, checked = verify(md, refs, stamps, root, today, default_ttl)
        result["refs_checked"] += checked
        result["issues"].extend(issues)
    result["errors"] = sum(1 for i in result["issues"] if i["severity"] == "ERROR")
    result["warnings"] = sum(1 for i in result["issues"] if i["severity"] == "WARN")
    return result


# -------------------------------------------------------------------- reports
def report_text(r: dict) -> str:
    lines = [
        "Doc Drift Report  (as of %s)" % r["as_of"],
        "=" * 48,
        "root    : %s" % r["root"],
        "files   : %d markdown scanned" % r["files_scanned"],
        "refs    : %d checked" % r["refs_checked"],
        "issues  : %d errors, %d warnings" % (r["errors"], r["warnings"]),
    ]
    by_file = {}
    for issue in r["issues"]:
        by_file.setdefault(issue["file"], []).append(issue)
    for f in sorted(by_file):
        lines.append("")
        lines.append(f)
        for i in sorted(by_file[f], key=lambda x: (x["line"], x["code"])):
            lines.append("%6d  %-5s  %-15s '%s'  %s"
                         % (i["line"], i["severity"], i["code"], i["ref"], i["note"]))
    lines.append("")
    lines.append("-" * 48)
    if r["errors"] or r["warnings"]:
        lines.append("verdict : DRIFT DETECTED — %d errors, %d warnings"
                     % (r["errors"], r["warnings"]))
    else:
        lines.append("verdict : docs consistent with code")
    return "\n".join(lines)


def report_json(r: dict) -> str:
    return json.dumps(r, ensure_ascii=False, indent=2, sort_keys=True)


# ------------------------------------------------------------------------ CLI
def build_parser():
    p = argparse.ArgumentParser(
        prog=PROG,
        description="doc_drift — the doc-rot compiler. Verifies that markdown "
                    "references (paths, links, path::Symbol) still exist and "
                    "freshness stamps have not expired.")
    p.add_argument("--version", action="version", version="%s %s" % (PROG, VERSION))
    sub = p.add_subparsers(dest="cmd")

    sc = sub.add_parser("scan", help="scan markdown for drift (default command)")
    sc.add_argument("paths", nargs="*", help="files/dirs to scan (default: .)")
    sc.add_argument("--json", action="store_true", help="machine-readable output")
    sc.add_argument("--ttl-days", type=int, default=DEFAULT_TTL_DAYS,
                    help="default TTL for stamps without one (default: %d)"
                         % DEFAULT_TTL_DAYS)
    sc.add_argument("--fail-on", choices=("error", "warn", "never"),
                    default="error",
                    help="exit 1 on errors (default) / on any issue / never")
    sc.add_argument("--exclude", action="append", default=[],
                    metavar="GLOB",
                    help="skip paths matching GLOB (a path part match counts; repeatable)")
    sc.add_argument("--today", metavar="YYYY-MM-DD",
                    help="override 'now' (for tests & reproducible reports)")

    st = sub.add_parser("stamp", help="print a freshness stamp to paste into a doc")
    st.add_argument("--date", metavar="YYYY-MM-DD", default=date.today().isoformat())
    st.add_argument("--ttl", type=int, default=DEFAULT_TTL_DAYS)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["scan"]
    args = build_parser().parse_args(argv)

    if args.cmd == "stamp":
        try:
            date.fromisoformat(args.date)
        except ValueError:
            print("error: --date must be YYYY-MM-DD", file=sys.stderr)
            return 2
        print("<!-- verified: %s; ttl: %dd -->" % (args.date, args.ttl))
        return 0

    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError:
        print("error: --today must be YYYY-MM-DD", file=sys.stderr)
        return 2

    paths = args.paths or ["."]
    try:
        result = run_scan(paths, args.exclude, today, args.ttl_days)
    except FileNotFoundError as e:
        print("error: no such path: %s" % e, file=sys.stderr)
        return 2

    print(report_json(result) if args.json else report_text(result))
    if args.fail_on == "error":
        return 1 if result["errors"] else 0
    if args.fail_on == "warn":
        return 1 if (result["errors"] or result["warnings"]) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
