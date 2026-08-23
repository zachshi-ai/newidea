"""Acceptance tests for midnight_oil.py — all criteria from README.

时间事实（测试的已知日期锚点，全部用 datetime 动态断言防止手算漂移）:
  2026-01-01 是周四; 2026-06-06 周六; 2026-06-07 周日; 2026-06-08 周一;
  2026-08-24 周一.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = [sys.executable, os.path.join(ROOT, "midnight_oil.py")]

sys.path.insert(0, ROOT)
import midnight_oil as mo  # noqa: E402


def mk(when, author="Alice Chen", email=None, sha=None):
    """造一个 Commit: when 为 ISO 字符串（带偏移，即作者本地墙钟）."""
    return mo.Commit(sha or hashlib.sha1(when.encode()).hexdigest()[:8],
                     mo.parse_stamp(when), author,
                     email or (author.split()[0].lower() + "@example.com"))


# ---------------------------------------------------------------- repo fixture

class GitRepo(unittest.TestCase):
    """真实临时 git 仓库: 日期与偏移全部钉死."""

    def setUp(self):
        self.path = tempfile.mkdtemp(prefix="mo-git-")
        self.addCleanup(shutil.rmtree, self.path, ignore_errors=True)
        self.git("init", "-q")

    def git(self, *args, env=None):
        proc = subprocess.run(["git", "-C", self.path] + list(args),
                              capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise AssertionError("git {}: {}".format(args, proc.stderr))
        return proc.stdout

    def commit(self, author, when, msg="work", committer_when=None):
        """when: '2026-06-06 23:40:00 +0800'（作者本地墙钟 + 偏移）."""
        name, email = author
        env = dict(os.environ,
                   GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                   GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email,
                   GIT_AUTHOR_DATE=when,
                   GIT_COMMITTER_DATE=committer_when or when)
        with open(os.path.join(self.path, "f.txt"), "a") as fh:
            fh.write(when + "\n")
        self.git("add", "-A", env=env)
        self.git("commit", "-q", "--allow-empty", "-m", msg, env=env)

    def commits(self, **kw):
        return mo.filter_commits(mo.load_commits(self.path), **kw)

    def run_cli(self, *args):
        return subprocess.run(CLI + list(args), cwd=self.path,
                              capture_output=True, text=True)


# ---------------------------------------------------------------- parsing

class TimeparseTests(unittest.TestCase):
    def test_iso_strict(self):
        dt = mo.parse_stamp("2026-06-06T23:40:00+08:00")
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute),
                         (2026, 6, 6, 23, 40))

    def test_space_format_with_offset(self):
        # %ad / 常见 git 输出的空格式; 库只承诺 %aI, 但兜底不吃灰
        dt = mo.parse_stamp("2026-06-06 23:40:00 +0800")
        self.assertEqual(dt.hour, 23)

    def test_naive_fallback(self):
        dt = mo.parse_stamp("2026-06-06T23:40:00")
        self.assertEqual(dt.hour, 23)

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            mo.parse_stamp("not a timestamp at all")

    def test_no_conversion_naive_tz(self):
        # 关键不变量: 解析结果不做任何时区换算, 钟点字段原样保留
        dt = mo.parse_stamp("2026-06-06T01:30:00+08:00")
        self.assertEqual(dt.hour, 1)
        self.assertEqual(dt.day, 6)

    def test_parse_log_fields(self):
        sep = mo.FIELD_SEP
        line = sep.join(["abc12345", "2026-06-06T23:40:00+08:00",
                         "Alice|Chen", "alice@example.com"])
        cs = mo.parse_log(line)
        self.assertEqual(len(cs), 1)
        self.assertEqual(cs[0].sha, "abc12345")
        self.assertEqual(cs[0].author, "Alice|Chen")  # 字段分隔符吃掉竖线名
        self.assertEqual(cs[0].late, True)

    def test_parse_log_skips_malformed(self):
        self.assertEqual(mo.parse_log("garbage line\n\nalso bad"), [])


# ---------------------------------------------------------------- signals

class SignalTests(unittest.TestCase):
    def test_late_boundaries(self):
        for h in (22, 23, 0, 1, 2, 3, 4):
            self.assertTrue(mo.is_late_hour(h), h)
        for h in (5, 12, 21):
            self.assertFalse(mo.is_late_hour(h), h)

    def test_weekend_known_dates(self):
        self.assertTrue(mo.is_weekend(date(2026, 6, 6)))   # 周六
        self.assertTrue(mo.is_weekend(date(2026, 6, 7)))   # 周日
        self.assertFalse(mo.is_weekend(date(2026, 6, 8)))  # 周一
        self.assertFalse(mo.is_weekend(date(2026, 1, 1)))  # 周四
        self.assertFalse(mo.is_weekend(date(2026, 8, 24)))  # 周一

    def test_commit_properties(self):
        c = mk("2026-06-06T23:40:00+08:00")
        self.assertTrue(c.late)
        self.assertTrue(c.weekend)
        self.assertEqual(c.day, date(2026, 6, 6))
        self.assertEqual(c.hour, 23)

    def test_daytime_weekday_is_clean(self):
        c = mk("2026-06-08T10:15:00+08:00")
        self.assertFalse(c.late)
        self.assertFalse(c.weekend)


# ---------------------------------------------------------------- streak

class StreakTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(mo.longest_streak([]), 0)

    def test_single_day(self):
        self.assertEqual(mo.longest_streak([date(2026, 6, 6)]), 1)

    def test_consecutive_run(self):
        days = [date(2026, 6, 1) + __import__("datetime").timedelta(days=i)
                for i in range(16)]
        self.assertEqual(mo.longest_streak(days), 16)

    def test_gap_resets(self):
        days = [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3),
                date(2026, 6, 10), date(2026, 6, 11)]
        self.assertEqual(mo.longest_streak(days), 3)

    def test_duplicate_days_count_once(self):
        days = [date(2026, 6, 1)] * 5 + [date(2026, 6, 2)] * 3
        self.assertEqual(mo.longest_streak(days), 2)

    def test_unsorted_input(self):
        days = [date(2026, 6, 2), date(2026, 6, 1), date(2026, 6, 3)]
        self.assertEqual(mo.longest_streak(days), 3)


# ---------------------------------------------------------------- profile

class ProfileTests(unittest.TestCase):
    def _p(self, whens, author="Bob Wu"):
        return mo.Profile(author, [mk(w) for w in whens])

    def test_ratios_and_histogram(self):
        whens = (["2026-06-01T10:00:00+08:00"] * 6 +
                 ["2026-06-06T23:30:00+08:00"] * 2 +   # 周六深夜
                 ["2026-06-07T01:00:00+08:00"] * 2)    # 周日凌晨
        p = self._p(whens)
        self.assertEqual(len(p.commits), 10)
        self.assertEqual(p.late_pct, 40.0)
        self.assertEqual(p.weekend_pct, 40.0)
        self.assertEqual(p.histogram[23], 2)
        self.assertEqual(p.histogram[1], 2)
        self.assertEqual(len(p.as_dict()["histogram"]), 24)

    def test_active_first_last(self):
        p = self._p(["2026-03-02T09:00:00+08:00",
                     "2026-04-09T11:00:00+08:00",
                     "2026-03-15T10:00:00+08:00"])
        self.assertEqual(p.first_day, date(2026, 3, 2))
        self.assertEqual(p.last_day, date(2026, 4, 9))
        self.assertEqual(len(p.days), 3)

    def test_flag_late_night(self):
        whens = ["2026-06-0{}T10:00:00+08:00".format(i)
                 for i in range(1, 6)]
        whens += ["2026-06-01T10:00:00+08:00",
                  "2026-06-02T10:00:00+08:00",
                  "2026-06-03T10:00:00+08:00"]
        whens += ["2026-06-01T23:30:00+08:00",
                  "2026-06-02T23:30:00+08:00"]
        p = self._p(whens)
        self.assertIn("LATE_NIGHT", p.flags())  # 2/10 = 20%

    def test_flag_weekends(self):
        whens = ["2026-06-{:02d}T10:00:00+08:00".format(d)
                 for d in (1, 2, 3, 4, 5, 8, 9)]  # 7 个工作日
        whens += ["2026-06-{:02d}T10:00:00+08:00".format(d)
                  for d in (6, 7, 13)]            # 3 个周末日
        p = self._p(whens)
        self.assertIn("WEEKENDS", p.flags())  # 3/10 = 30%

    def test_flag_no_break(self):
        from datetime import timedelta
        base = date(2026, 6, 1)
        whens = ["{}T10:00:00+08:00".format(
            (base + timedelta(days=i)).isoformat()) for i in range(14)]
        p = self._p(whens)
        self.assertEqual(p.longest_streak_days, 14)
        self.assertIn("NO_BREAK", p.flags())

    def test_flag_weekend_late_needs_three_days(self):
        p = self._p(["2026-06-06T23:00:00+08:00",
                     "2026-06-07T23:00:00+08:00",
                     "2026-06-08T09:00:00+08:00"])
        self.assertNotIn("WEEKEND_LATE", p.flags())  # 2 个周末深夜日
        p2 = self._p(["2026-06-06T23:00:00+08:00",
                      "2026-06-07T23:00:00+08:00",
                      "2026-06-13T23:00:00+08:00",
                      "2026-06-08T09:00:00+08:00"])
        self.assertIn("WEEKEND_LATE", p2.flags())  # 3 个周末深夜日

    def test_ratio_flags_need_ten_commits(self):
        p = self._p(["2026-06-06T23:00:00+08:00"])  # 100% 深夜但只有 1 个
        self.assertNotIn("LATE_NIGHT", p.flags())
        self.assertNotIn("WEEKENDS", p.flags())

    def test_levels(self):
        clean = self._p(["2026-06-0{}T10:00:00+08:00".format(i)
                         for i in (1, 2, 3)])
        self.assertEqual(clean.level(), "ok")
        one_flag = self._p(["2026-06-{:02d}T10:00:00+08:00".format(d)
                            for d in (1, 2, 3, 4, 5, 8, 9)] +
                           ["2026-06-{:02d}T10:00:00+08:00".format(d)
                            for d in (6, 7, 13)])  # weekend 3/10 = 30% -> 1 flag
        self.assertEqual(one_flag.level(), "watch")
        two = self._p(["2026-06-06T23:00:00+08:00"] * 3 +
                      ["2026-06-07T23:00:00+08:00"] * 3 +
                      ["2026-06-13T23:00:00+08:00"] * 3 +
                      ["2026-06-14T23:00:00+08:00"] * 3)  # late+weekend+late-weekend
        self.assertEqual(two.level(), "alert")

    def test_group_profiles_merges_same_name_and_sorts(self):
        cs = [mk("2026-06-01T10:00:00+08:00", "Bob Wu", "b1@x.com"),
              mk("2026-06-02T10:00:00+08:00", "Alice Chen"),
              mk("2026-06-03T10:00:00+08:00", "Bob Wu", "b2@x.com"),
              mk("2026-06-04T10:00:00+08:00", "Bob Wu", "b3@x.com")]
        profiles = mo.group_profiles(cs)
        self.assertEqual([p.name for p in profiles],
                         ["Bob Wu", "Alice Chen"])
        self.assertEqual(len(profiles[0].commits), 3)


# ---------------------------------------------------------------- trend

class TrendTests(unittest.TestCase):
    AS_OF = date(2026, 8, 24)

    def _mk(self, day, hour):
        return mk("{}T{:02d}:00:00+08:00".format(day.isoformat(), hour))

    def _months(self, months, hour):
        """3-4 月 (baseline) 各月上中下旬取 3+3 天 -> 12 个提交."""
        from datetime import timedelta
        base = date(2026, 3, 2)
        days = [base + timedelta(days=30 * (m - 3) + 7 * i)
                for m in months for i in range(6)]
        return [self._mk(d, hour) for d in days]

    def test_split_boundary_goes_to_baseline(self):
        cs = [mk("2026-05-25T10:00:00+08:00"),   # == cutoff -> baseline
              mk("2026-05-26T10:00:00+08:00")]   # cutoff+1 -> recent
        t = mo.split_trend(cs, 91, self.AS_OF)
        self.assertEqual(len(t.recent), 1)
        self.assertEqual(len(t.baseline), 1)

    def test_directions_worsening(self):
        from datetime import timedelta
        recent = [self._mk(self.AS_OF - timedelta(days=d), 23)
                  for d in range(1, 11)]          # 10 个深夜
        t = mo.split_trend(self._months((3, 4), 10) + recent, 91, self.AS_OF)
        self.assertEqual(t.directions()["late"], "WORSENING")
        self.assertEqual(t.recent_seg()["late_pct"], 100.0)
        self.assertEqual(t.baseline_seg()["late_pct"], 0.0)

    def test_directions_improving(self):
        from datetime import timedelta
        recent = [self._mk(self.AS_OF - timedelta(days=d), 10)
                  for d in range(1, 11)]
        t = mo.split_trend(self._months((3, 4), 23) + recent, 91, self.AS_OF)
        self.assertEqual(t.directions()["late"], "IMPROVING")

    def test_directions_stable(self):
        from datetime import timedelta
        recent = [self._mk(self.AS_OF - timedelta(days=d), 10)
                  for d in range(1, 11)]
        t = mo.split_trend(self._months((3, 4), 10) + recent, 91, self.AS_OF)
        self.assertEqual(t.directions()["late"], "STABLE")

    def test_directions_insufficient_sample(self):
        t = mo.split_trend([mk("2026-06-01T23:00:00+08:00")], 91,
                           self.AS_OF)
        self.assertEqual(t.directions()["late"], "INSUFFICIENT")
        self.assertEqual(t.directions()["weekend"], "INSUFFICIENT")

    def test_weekly_active_days_uses_own_span(self):
        # recent: 14 天窗内 4 个活跃日 -> 2.0/周
        # baseline: 70 天窗内 10 个活跃日 -> 1.0/周 (按各自跨度折算)
        from datetime import timedelta
        anchor = self.AS_OF - timedelta(days=14)
        recent_days = [anchor - timedelta(days=13), anchor - timedelta(days=7),
                       anchor - timedelta(days=1), anchor]
        end = self.AS_OF - timedelta(days=100)
        base_days = ([end - timedelta(days=7 * i) for i in range(9)] +
                     [end - timedelta(days=69)])   # 最老一天撑出 70 天跨度
        cs = [self._mk(d, 10) for d in recent_days + base_days]
        t = mo.split_trend(cs, 91, self.AS_OF)
        self.assertEqual(t.recent_seg()["weekly_active_days"], 2.0)
        self.assertEqual(t.baseline_seg()["weekly_active_days"], 1.0)


# ---------------------------------------------------------------- anonymize

class AnonymizeTests(unittest.TestCase):
    def test_stable_and_distinct(self):
        a, b = mo.anon_name("Alice Chen"), mo.anon_name("Alice Chen")
        self.assertEqual(a, b)
        self.assertNotEqual(a, mo.anon_name("Bob Wu"))
        self.assertTrue(a.startswith("anon-"))
        self.assertEqual(len(a), len("anon-") + 8)

    def test_as_dict_hides_real_name(self):
        p = mo.Profile("Alice Chen", [mk("2026-06-01T10:00:00+08:00")])
        d = p.as_dict(anonymize=True)
        self.assertNotIn("Alice", json.dumps(d))
        self.assertTrue(str(d["author"]).startswith("anon-"))


# ---------------------------------------------------------------- git integration

class GitIntegrationTests(GitRepo):
    def test_same_instant_two_wallclocks(self):
        # 同一绝对时刻: 北京墙钟已过午夜, 洛杉矶墙钟还是傍晚.
        # 工具读的是各作者自己墙上的钟 — 不做统一换算.
        self.commit(("Bei Jing", "bei@x.com"),
                    "2026-06-10 01:30:00 +0800")   # UTC 06-09 17:30
        self.commit(("LA Dev", "la@x.com"),
                    "2026-06-09 17:30:00 -0700")   # 同一 UTC 时刻
        cs = self.commits()
        by = {c.author: c for c in cs}
        self.assertTrue(by["Bei Jing"].late)    # 他当地 01:30
        self.assertFalse(by["LA Dev"].late)     # 他当地 17:30
        self.assertEqual(by["Bei Jing"].day, date(2026, 6, 10))
        self.assertEqual(by["LA Dev"].day, date(2026, 6, 9))

    def test_weekend_uses_author_local_date(self):
        # UTC 周日 20:00 = 北京周一凌晨 04:00: 按北京挂钟是周一(非周末)凌晨
        self.commit(("Zhou", "zhou@x.com"),
                    "2026-06-08 04:00:00 +0800")   # UTC 06-07 20:00 周日
        c = self.commits()[0]
        self.assertFalse(c.weekend)
        self.assertTrue(c.late)

    def test_author_date_wins_over_committer_date(self):
        # author 深夜 23:40, committer 次日白天: 我们量的是「写代码的时刻」
        self.commit(("Night Owl", "owl@x.com"),
                    "2026-06-10 23:40:00 +0800",
                    committer_when="2026-06-11 09:00:00 +0800")
        self.assertTrue(self.commits()[0].late)

    def test_author_filter(self):
        self.commit(("Alice Chen", "a@x.com"), "2026-06-01T10:00:00 +0800")
        self.commit(("Bob Wu", "b@x.com"), "2026-06-02 10:00:00 +0800")
        cs = self.commits(author="bob")
        self.assertEqual([c.author for c in cs], ["Bob Wu"])

    def test_exclude_author_by_name_or_email(self):
        self.commit(("Alice Chen", "a@x.com"), "2026-06-01 10:00:00 +0800")
        self.commit(("renovate[bot]", "bot@renovate"),
                    "2026-06-02 10:00:00 +0800")
        cs = self.commits(exclude_authors=["bot"])
        self.assertEqual([c.author for c in cs], ["Alice Chen"])
        cs2 = self.commits(exclude_authors=["a@x"])
        self.assertEqual([c.author for c in cs2], ["renovate[bot]"])

    def test_since_until_inclusive_bounds(self):
        self.commit(("A", "a@x.com"), "2026-06-01 10:00:00 +0800")
        self.commit(("A", "a@x.com"), "2026-06-05 10:00:00 +0800")
        self.commit(("A", "a@x.com"), "2026-06-10 10:00:00 +0800")
        cs = self.commits(since=date(2026, 6, 5), until=date(2026, 6, 10))
        self.assertEqual([c.day for c in cs],
                         [date(2026, 6, 5), date(2026, 6, 10)])

    def test_empty_repo(self):
        self.assertEqual(self.commits(), [])

    def test_profiles_from_real_repo(self):
        for i in range(4):
            self.commit(("Alice Chen", "a@x.com"),
                        "2026-06-0{} 10:00:00 +0800".format(i + 1))
        self.commit(("Alice Chen", "a@x.com"), "2026-06-06 23:00:00 +0800")
        r = mo.Report(self.path, self.commits(), date(2026, 8, 24))
        self.assertEqual(len(r.profiles), 1)
        self.assertEqual(r.summary()["commits"], 5)
        self.assertEqual(r.summary()["weekend_late_days"], 1)


# ---------------------------------------------------------------- render

class RenderTests(GitRepo):
    def test_scan_empty(self):
        r = mo.Report(self.path, [], date(2026, 8, 24))
        text = mo.render_scan(r)
        self.assertIn("no commits in range", text)
        self.assertEqual(r.level(), "empty")

    def test_scan_numbers_and_bars(self):
        cs = [mk("2026-06-0{}T10:00:00+08:00".format(i)) for i in (1, 2, 3)]
        cs += [mk("2026-06-06T23:00:00+08:00")]  # 周六深夜
        r = mo.Report(self.path, cs, date(2026, 8, 24))
        text = mo.render_scan(r)
        self.assertIn("commits         : 4", text)
        self.assertIn("late-night 22-05:  25.0%", text)
        self.assertIn("weekend         :  25.0%", text)
        self.assertIn("##", text)

    def test_authors_lists_flags_levels_hist(self):
        cs = [mk("2026-06-06T23:00:00+08:00", "Bob Wu"),
              mk("2026-06-07T23:00:00+08:00", "Bob Wu"),
              mk("2026-06-13T23:00:00+08:00", "Bob Wu"),
              mk("2026-06-14T23:00:00+08:00", "Bob Wu")] + \
             [mk("2026-06-0{}T10:00:00+08:00".format(i), "Alice Chen")
              for i in (1, 2, 3)]
        r = mo.Report(self.path, cs, date(2026, 8, 24))
        text = mo.render_authors(r)
        self.assertIn("Bob Wu", text)
        self.assertIn("WEEKEND_LATE", text)
        self.assertIn("am  ", text)
        self.assertIn("levels:", text)

    def test_trend_render_mentions_night_owl(self):
        cs = [mk("2026-06-01T10:00:00+08:00")]
        r = mo.Report(self.path, cs, date(2026, 8, 24))
        t = mo.split_trend(cs, 91, r.as_of)
        text = mo.render_trend(t, r)
        self.assertIn("night-owl defense", text)
        self.assertIn("INSUFFICIENT", text)


# ---------------------------------------------------------------- cli

class CliTests(GitRepo):
    def test_no_subcommand_exit_2(self):
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 2)

    def test_not_a_git_repo_exit_2(self):
        plain = tempfile.mkdtemp(prefix="mo-plain-")
        self.addCleanup(shutil.rmtree, plain, ignore_errors=True)
        proc = subprocess.run(CLI + ["scan"], cwd=plain,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a git repository", proc.stderr)

    def test_scan_text_and_json(self):
        self.commit(("Alice Chen", "a@x.com"), "2026-06-01 10:00:00 +0800")
        self.commit(("Alice Chen", "a@x.com"), "2026-06-06 23:30:00 +0800")
        proc = self.run_cli("scan", "--as-of", "2026-08-24")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Midnight oil", proc.stdout)
        proc = self.run_cli("scan", "--format", "json",
                            "--as-of", "2026-08-24")
        payload = json.loads(proc.stdout)
        for key in ("repo", "as_of", "commits", "authors", "late_pct",
                    "weekend_pct", "max_streak_days", "weekend_late_days",
                    "level"):
            self.assertIn(key, payload)
        self.assertEqual(payload["commits"], 2)
        self.assertEqual(payload["late_pct"], 50.0)

    def test_authors_json_schema(self):
        self.commit(("Alice Chen", "a@x.com"), "2026-06-01 10:00:00 +0800")
        proc = self.run_cli("authors", "--format", "json")
        payload = json.loads(proc.stdout)
        a = payload["authors"][0]
        for key in ("author", "commits", "late_pct", "weekend_pct",
                    "longest_streak_days", "weekend_late_days", "histogram",
                    "flags", "level"):
            self.assertIn(key, a)
        self.assertEqual(len(a["histogram"]), 24)

    def test_authors_anonymize(self):
        self.commit(("Alice Chen", "a@x.com"), "2026-06-01 10:00:00 +0800")
        proc = self.run_cli("authors", "--anonymize")
        self.assertNotIn("Alice", proc.stdout)
        self.assertIn("anon-", proc.stdout)

    def test_trend_window(self):
        self.commit(("A", "a@x.com"), "2026-08-20 10:00:00 +0800")
        proc = self.run_cli("trend", "--as-of", "2026-08-24",
                            "--window", "30", "--format", "json")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["window_days"], 30)
        self.assertEqual(payload["recent"]["commits"], 1)

    def test_audit_passes_within_budget(self):
        for i in range(4):
            self.commit(("A", "a@x.com"),
                        "2026-06-0{} 10:00:00 +0800".format(i + 1))
        proc = self.run_cli("audit", "--as-of", "2026-08-24")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Within health budget", proc.stdout)

    def test_audit_fails_over_budget(self):
        for d in range(1, 11):   # 10 个深夜提交 -> 100% >= 样本下限
            self.commit(("A", "a@x.com"),
                        "2026-06-{:02d} 23:30:00 +0800".format(d))
        proc = self.run_cli("audit", "--as-of", "2026-08-24",
                            "--max-late", "50")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("exceeds budget", proc.stdout)

    def test_audit_ratio_needs_ten_commits(self):
        # 与 per-author flag 同一纪律: 小样本不开比例罚单
        for i in range(5):       # 5 个深夜提交 -> 100% 但样本不足
            self.commit(("A", "a@x.com"),
                        "2026-06-0{} 23:30:00 +0800".format(i + 1))
        proc = self.run_cli("audit", "--as-of", "2026-08-24")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("Within health budget", proc.stdout)

    def test_audit_streak_per_author(self):
        from datetime import timedelta
        base = date(2026, 6, 1)
        for i in range(20):  # 20 天连轴转
            day = base + timedelta(days=i)
            self.commit(("A", "a@x.com"),
                        "{} 10:00:00 +0800".format(day.isoformat()))
        proc = self.run_cli("audit", "--as-of", "2026-08-24")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("streak 20d exceeds budget 14d", proc.stdout)

    def test_options_after_subcommand(self):
        self.commit(("Alice Chen", "a@x.com"), "2026-06-01 10:00:00 +0800")
        proc = self.run_cli("scan", "--author", "alice",
                            "--as-of", "2026-08-24", "--format", "json")
        self.assertEqual(json.loads(proc.stdout)["commits"], 1)


# ---------------------------------------------------------------- examples sync

class ExamplesSyncTests(unittest.TestCase):
    def test_examples_rebuild_matches_committed(self):
        proc = subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "examples", "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


# ---------------------------------------------------------------- dogfood

class DogfoodTests(unittest.TestCase):
    """工具出生的第一天就照镜子: 扫自己所在的 newidea 仓库."""

    def test_identity_authors_sum_equals_scan_total(self):
        proc = subprocess.run(
            CLI + ["scan", "--format", "json"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        summary = json.loads(proc.stdout)
        self.assertGreaterEqual(summary["commits"], 1)
        self.assertGreaterEqual(summary["authors"], 1)
        proc2 = subprocess.run(
            CLI + ["authors", "--format", "json"],
            cwd=ROOT, capture_output=True, text=True)
        authors = json.loads(proc2.stdout)["authors"]
        # 恒等式: 每人提交数之和 == 总提交数 (同一过滤口径)
        self.assertEqual(sum(a["commits"] for a in authors),
                         summary["commits"])


if __name__ == "__main__":
    unittest.main()
