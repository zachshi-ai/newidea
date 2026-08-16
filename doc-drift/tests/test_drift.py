"""
Automated acceptance tests for doc-drift.

Covers the published acceptance criteria — reference extraction, false-
positive guards, resolution bases, symbol checks, freshness stamps, exit
codes, JSON output, example sync, and a dogfood pass over this very
repository — using stdlib `unittest`, so the suite runs with
`python -m unittest` and no extras.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # doc-drift/
REPO = ROOT.parent                                     # newidea/
sys.path.insert(0, str(ROOT))

import doc_drift as dd  # noqa: E402

EX = ROOT / "examples"
DEMO = EX / "demo-repo"
TODAY = date(2026, 8, 16)


def kinds_refs(refs):
    return [(r.kind, r.value if r.kind != "symbol" else r.value, r.origin) for r in refs]


def build_repo(files):
    """Create a throwaway repo from {relative_path: content}; return its root."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp, root


def run_cli(args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = dd.main(args)
    return rc, out.getvalue()


# --------------------------------------------------------------- extraction
class ExtractionTests(unittest.TestCase):
    """Acceptance: references are extracted from prose, code spans and fences."""

    def extract(self, text):
        refs, stamps = dd.parse_markdown(text)
        return refs, stamps

    def test_prose_slash_path_found(self):
        refs, _ = self.extract("First read docs/guide.md carefully.")
        self.assertIn(("path", "docs/guide.md", "prose"), kinds_refs(refs))

    def test_code_span_slash_and_bare(self):
        refs, _ = self.extract("Run `src/a.py` with `config.toml` in place.")
        self.assertIn(("path", "src/a.py", "code span"), kinds_refs(refs))
        self.assertIn(("path", "config.toml", "code span"), kinds_refs(refs))

    def test_bare_filename_in_prose_ignored(self):
        refs, _ = self.extract("See config.toml for details.")
        self.assertEqual(refs, [])

    def test_fenced_block_paths(self):
        text = "```bash\npython3 src/live.py --config config.toml\n```\n"
        refs, _ = self.extract(text)
        self.assertIn(("path", "src/live.py", "fenced block"), kinds_refs(refs))
        self.assertIn(("path", "config.toml", "fenced block"), kinds_refs(refs))

    def test_links_local_vs_external(self):
        refs, _ = self.extract("[a](docs/x.md) [b](https://e.com/x.md) "
                               "[c](#anchor) [d](mailto:x@y.z) [e](//cdn.lib/a.js)")
        self.assertEqual([r.value for r in refs if r.kind == "link"], ["docs/x.md"])

    def test_link_target_kept_verbatim(self):
        refs, _ = self.extract("See [a](docs/x.md#sec?utm=1).")
        self.assertEqual(refs[0].value, "docs/x.md#sec?utm=1")

    def test_symbol_ref(self):
        refs, _ = self.extract("Entry point is `src/live.py::run_checks`.")
        self.assertIn(("symbol", ("src/live.py", "run_checks"), "code span"),
                      kinds_refs(refs))
        self.assertNotIn(("path", "src/live.py", "code span"), kinds_refs(refs))

    def test_symbol_requires_exact_span(self):
        refs, _ = self.extract("Entry `src/live.py :: run` spaced.")
        self.assertFalse(any(r.kind == "symbol" for r in refs))
        self.assertIn(("path", "src/live.py", "code span"), kinds_refs(refs))

    def test_markdown_link_inside_code_span_not_parsed(self):
        refs, _ = self.extract("Type `` `[x](gone.md)` `` literally.")
        self.assertFalse(any(r.kind == "link" for r in refs))

    def test_stamp_parsed_with_and_without_ttl(self):
        _, stamps = self.extract("<!-- verified: 2026-01-05; ttl: 90d -->\n"
                                 "<!-- fresh: 2026-02-01 -->")
        self.assertEqual(stamps, [(1, "2026-01-05", "90"), (2, "2026-02-01", None)])

    def test_dd_ignore_skips_line(self):
        refs, stamps = self.extract("`gone.py` <!-- dd:ignore: fixture -->")
        self.assertEqual((refs, stamps), ([], []))

    def test_stamp_not_recognized_inside_fence(self):
        text = "```html\n<!-- verified: 2026-01-01 -->\n```\n"
        _, stamps = self.extract(text)
        self.assertEqual(stamps, [])

    def test_fence_info_dd_ignore_exempts_block(self):
        text = "```text dd:ignore\nuses `gone.py` here\n```\n`live.py` stays\n"
        refs, _ = self.extract(text)
        self.assertEqual([r.value for r in refs], ["live.py"])

    def test_symbol_syntax_requires_extension(self):
        refs, _ = self.extract("Prose about `path::Symbol` and real `a.py::fn`.")
        symbols = [r.value for r in refs if r.kind == "symbol"]
        self.assertEqual(symbols, [("a.py", "fn")])


class FalsePositiveTests(unittest.TestCase):
    """Acceptance: known non-file tokens must not be flagged (precision first)."""

    def check_tokens(self, code):
        refs, _ = dd.parse_markdown("Use `%s` here." % code)
        return [r.value for r in refs]

    def test_urls_ignored(self):
        self.assertEqual(self.check_tokens("https://github.com/a/b.py"), [])

    def test_absolute_system_paths_ignored(self):
        self.assertEqual(self.check_tokens("/etc/hosts"), [])
        self.assertEqual(self.check_tokens("/usr/local/bin/tool"), [])

    def test_version_numbers_ignored(self):
        self.assertEqual(self.check_tokens("Python 3.12 or v1.2 or 16.4"), [])

    def test_domains_ignored(self):
        self.assertEqual(self.check_tokens("example.com"), [])

    def test_extensionless_directories_ignored(self):
        refs, _ = dd.parse_markdown("See docs/ for more.")
        self.assertEqual(refs, [])


# --------------------------------------------------------------- resolution
class ResolutionTests(unittest.TestCase):
    """Acceptance: paths resolve against the markdown's dir and the scan root."""

    def scan_repo(self, files):
        tmp, root = build_repo(files)
        self.addCleanup(tmp.cleanup)
        return root, dd.run_scan([str(root)], [], TODAY, dd.DEFAULT_TTL_DAYS)

    def test_resolves_md_dir_and_root(self):
        root, r = self.scan_repo({
            "root-file.txt": "",
            "sub/lib.py": "def good(): pass\n",
            "docs/c.md": "",
            "docs/a.md": "Back to [c](c.md), up to [root](../root-file.txt), "
                         "and `sub/lib.py` too.\n",
        })
        self.assertEqual(r["issues"], [])

    def test_missing_file_reported_with_line(self):
        root, r = self.scan_repo({"a.md": "line1\nline2 uses `gone.py` now\n"})
        self.assertEqual(len(r["issues"]), 1)
        i = r["issues"][0]
        self.assertEqual((i["line"], i["severity"], i["code"], i["ref"]),
                         (2, "ERROR", "missing-file", "gone.py"))

    def test_missing_dir_link(self):
        root, r = self.scan_repo({"a.md": "Go [there](nodir/).\n"})
        self.assertEqual(r["issues"][0]["code"], "missing-dir")

    def test_link_url_decoding(self):
        root, r = self.scan_repo({"my file.md": "", "a.md": "[x](my%20file.md)\n"})
        self.assertEqual(r["issues"], [])

    def test_site_absolute_link(self):
        root, r = self.scan_repo({"sub/b.md": "", "a.md": "[x](/sub/b.md)\n"})
        self.assertEqual(r["issues"], [])

    def test_symbol_hit_and_miss(self):
        root, r = self.scan_repo({
            "sub/lib.py": "def good(): pass\n",
            "a.md": "ok `sub/lib.py::good`; bad `sub/lib.py::nope`; "
                    "ghost `sub/ghost.py::x`\n",
        })
        codes = sorted((i["code"], i["ref"]) for i in r["issues"])
        self.assertEqual(codes, [("missing-file", "sub/ghost.py"),
                                 ("missing-symbol", "sub/lib.py::nope")])


# ------------------------------------------------------------------- stamps
class StampTests(unittest.TestCase):
    """Acceptance: freshness stamps expire deterministically."""

    def stamps_issues(self, md_text, default_ttl=dd.DEFAULT_TTL_DAYS):
        tmp, root = build_repo({"a.md": md_text})
        self.addCleanup(tmp.cleanup)
        r = dd.run_scan([str(root)], [], TODAY, default_ttl)
        return r["issues"]

    def test_default_ttl_fresh_then_stale(self):
        self.assertEqual(self.stamps_issues("<!-- verified: 2026-03-01 -->"), [])
        issues = self.stamps_issues("<!-- verified: 2026-02-01 -->")
        self.assertEqual(issues[0]["severity"], "WARN")
        self.assertEqual(issues[0]["code"], "stale")

    def test_per_stamp_ttl_overrides_default(self):
        # a stamped ttl of 10d expires 2026-08-11 even under a 180d default
        stamped = "<!-- verified: 2026-08-01; ttl: 10d -->"
        self.assertEqual(len(self.stamps_issues(stamped, default_ttl=180)), 1)
        # without a per-stamp ttl the default decides (180d → fresh, 10d → stale)
        plain = "<!-- verified: 2026-08-01 -->"
        self.assertEqual(self.stamps_issues(plain, default_ttl=180), [])
        self.assertEqual(len(self.stamps_issues(plain, default_ttl=10)), 1)

    def test_future_stamp_is_error(self):
        issues = self.stamps_issues("<!-- verified: 2026-12-01 -->")
        self.assertEqual((issues[0]["severity"], issues[0]["code"]),
                         ("ERROR", "future-stamp"))

    def test_impossible_date_is_error(self):
        issues = self.stamps_issues("<!-- verified: 2026-13-45 -->")
        self.assertEqual(issues[0]["code"], "invalid-stamp")

    def test_overdue_days_reported(self):
        # 2026-01-05 + 90d = 2026-04-05; TODAY is 133 days past that
        issues = self.stamps_issues("<!-- verified: 2026-01-05; ttl: 90d -->")
        self.assertIn("expired 133d ago", issues[0]["note"])


# ---------------------------------------------------------------- end-to-end
class EndToEndTests(unittest.TestCase):
    """Acceptance: CLI behaviour — exit codes, JSON, excludes, --today."""

    def setUp(self):
        self.tmp, self.root = build_repo({
            "good.md": "See [b](b.md) and `data.txt`.\n"
                       "<!-- verified: 2026-05-01; ttl: 90d -->\n",
            "b.md": "", "data.txt": "",
            "bad/gone.md": "Uses `missing.py`.\n",
        })
        self.addCleanup(self.tmp.cleanup)
        self.path = str(self.root)

    def test_fail_on_error_default(self):
        rc, out = run_cli(["scan", self.path, "--exclude", "bad",
                           "--today", "2026-08-16"])
        self.assertEqual(rc, 0)
        rc, out = run_cli(["scan", self.path, "--today", "2026-08-16"])
        self.assertEqual(rc, 1)
        self.assertIn("DRIFT DETECTED", out)

    def test_fail_on_warn_and_never(self):
        rc, _ = run_cli(["scan", self.path, "--exclude", "bad",
                         "--today", "2026-08-16", "--fail-on", "warn"])
        self.assertEqual(rc, 1)     # the stamp expired on 2026-07-30
        rc, _ = run_cli(["scan", self.path, "--today", "2026-08-16",
                         "--fail-on", "never"])
        self.assertEqual(rc, 0)

    def test_today_changes_verdict(self):
        rc, _ = run_cli(["scan", self.path, "--exclude", "bad",
                         "--today", "2026-07-01"])
        self.assertEqual(rc, 0)
        rc, _ = run_cli(["scan", self.path, "--exclude", "bad",
                         "--today", "2026-08-01"])
        self.assertEqual(rc, 0)
        rc, out = run_cli(["scan", self.path, "--exclude", "bad",
                           "--today", "2026-08-01", "--fail-on", "warn"])
        self.assertEqual(rc, 1)

    def test_exclude_glob_drops_file(self):
        rc, out = run_cli(["scan", self.path, "--exclude", "bad",
                           "--today", "2026-08-16"])
        self.assertNotIn("bad" + "/", out.replace(str(self.root), ""))
        self.assertNotIn("missing.py", out)

    def test_json_output_valid_and_complete(self):
        rc, out = run_cli(["scan", self.path, "--json", "--today", "2026-08-16"])
        r = json.loads(out)
        for key in ("as_of", "root", "files_scanned", "files", "refs_checked",
                    "errors", "warnings", "issues"):
            self.assertIn(key, r)
        self.assertEqual(r["as_of"], "2026-08-16")
        issue = r["issues"][0]
        for key in ("file", "line", "severity", "code", "ref", "note"):
            self.assertIn(key, issue)

    def test_missing_path_exit_2(self):
        rc, _ = run_cli(["scan", str(self.root / "nope")])
        self.assertEqual(rc, 2)

    def test_no_args_scans_cwd(self):
        rc, out = run_cli(["scan", "--today", "2026-08-16"])  # cwd = wherever
        self.assertIn(rc, (0, 1))
        self.assertIn("Doc Drift Report", out)


# ------------------------------------------------------------ examples sync
class ExamplesSyncTests(unittest.TestCase):
    """Acceptance: the committed demo-repo matches expected-report.txt, with
    hand-written counts so regeneration can never silently redefine truth."""

    def result(self):
        return dd.run_scan([str(DEMO)], [], TODAY, dd.DEFAULT_TTL_DAYS)

    def test_expected_report_matches(self):
        r = self.result()
        report = dd.report_text(r).replace(str(DEMO), "<root>") + "\n"
        self.assertEqual(report, (EX / "expected-report.txt").read_text())

    def test_planted_counts(self):
        r = self.result()
        self.assertEqual((r["files_scanned"], r["refs_checked"],
                          r["errors"], r["warnings"]), (2, 14, 6, 1))

    def test_every_issue_is_planted(self):
        r = self.result()
        got = {(i["file"], i["line"], i["code"]) for i in r["issues"]}
        self.assertEqual(got, {
            ("README.md", 6, "stale"),
            ("README.md", 15, "missing-file"),
            ("README.md", 16, "missing-file"),
            ("README.md", 17, "missing-file"),
            ("README.md", 18, "missing-symbol"),
            ("README.md", 20, "future-stamp"),
            ("docs/guide.md", 9, "missing-file"),
        })
        self.assertEqual(Counter(i["code"] for i in r["issues"]),
                         {"missing-file": 4, "missing-symbol": 1,
                          "future-stamp": 1, "stale": 1})


# ----------------------------------------------------------------------- CLI
class CliTests(unittest.TestCase):
    """Acceptance: the script runs standalone as a subprocess."""

    def run_py(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "doc_drift.py"), *args],
            capture_output=True, text=True)

    def test_version(self):
        p = self.run_py("--version")
        self.assertEqual(p.returncode, 0)
        self.assertIn("doc-drift %s" % dd.VERSION, p.stdout)

    def test_scan_demo_repo_subprocess(self):
        p = self.run_py("scan", str(DEMO), "--today", "2026-08-16")
        self.assertEqual(p.returncode, 1)
        self.assertIn("DRIFT DETECTED", p.stdout)

    def test_scan_json_subprocess(self):
        p = self.run_py("scan", str(DEMO), "--json", "--today", "2026-08-16")
        self.assertEqual(p.returncode, 1)
        json.loads(p.stdout)

    def test_stamp_command(self):
        p = self.run_py("stamp", "--date", "2026-08-16", "--ttl", "90")
        self.assertEqual(p.stdout.strip(), "<!-- verified: 2026-08-16; ttl: 90d -->")

    def test_bad_today_exits_2(self):
        p = self.run_py("scan", str(DEMO), "--today", "not-a-date")
        self.assertEqual(p.returncode, 2)


# ------------------------------------------------------------------- dogfood
class DogfoodTests(unittest.TestCase):
    """Acceptance: doc-drift keeps its own repository drift-free.

    demo-repo is excluded (it is a deliberately-broken fixture); gitweek is
    excluded while under construction (covered by its own acceptance suite).
    """

    def test_repo_docs_consistent(self):
        r = dd.run_scan([str(REPO)], ["demo-repo", "gitweek"], date.today(),
                        dd.DEFAULT_TTL_DAYS)
        self.assertEqual(
            r["errors"], 0,
            "doc drift in this repo — run: python3 doc_drift.py scan .. "
            "--exclude demo-repo --exclude gitweek\nissues: %s" % r["issues"])


if __name__ == "__main__":
    unittest.main()
