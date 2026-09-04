# -*- coding: utf-8 -*-
"""Acceptance tests for year-like-a-day · 度年如日.

Every acceptance criterion in README.md is pinned here as a test:
ledger parsing guards (future rows refused, unknown categories not
guessed, duplicate firsts are corruption), the density identities
(Σ months == Σ categories == total, density == total ÷ covered days),
the median-month baseline and its burst immunity, grey-streak
recomputation across month boundaries, the remembered-month floor,
the double-signal greying gate and the single-signal absolute desert,
THIN refusal floors, the simulate counterfactual with its conservation
identity and pinned floor, and byte-reproducibility under a pinned
--today.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import year_like_a_day as yd  # noqa: E402

TODAY = "2026-08-31"

HEADER = "date\tcategory\tnote\tpeople\n"


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = yd.main(argv)
    return code, out.getvalue(), err.getvalue()


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def ledger(self, rows, name="firsts.tsv"):
        return self.write(name, HEADER + "".join(r + "\n" for r in rows))

    def row(self, day, category="place", note="第一次", people=""):
        cells = [day, category, note]
        if people:
            cells.append(people)
        return "\t".join(cells)

    def spaced(self, start, count, step, category="place", prefix="第一次"):
        """Rows every `step` days from `start` (ISO dates)."""
        from datetime import timedelta
        d0 = date.fromisoformat(start)
        return [self.row((d0 + timedelta(days=i * step)).isoformat(), category,
                         "%s #%d" % (prefix, i + 1))
                for i in range(count)]

    def sample(self):
        """The demo ledger, inline (same facts as examples/firsts.tsv)."""
        rows = [
            ("2026-01-01", "event",  "元旦第一次看海上日出", ""),
            ("2026-01-10", "place",  "第一次去市图书馆新馆", ""),
            ("2026-01-17", "person", "经老周介绍认识阿芳", "阿芳"),
            ("2026-01-24", "skill",  "第一次上陶艺课，拉了个歪杯子", ""),
            ("2026-01-31", "food",   "第一次吃酸汤牛肉", ""),
            ("2026-02-08", "person", "生日局认识阿芳的朋友小柯", "阿芳、小柯"),
            ("2026-04-12", "place",  "第一次去老周的新房子", "老周"),
            ("2026-05-01", "place",  "第一次到泉州（和阿芳）", "阿芳"),
            ("2026-05-02", "place",  "第一次看蟳埔簪花围", "阿芳"),
            ("2026-05-03", "food",   "第一次吃面线糊配油条", "阿芳"),
            ("2026-05-05", "event",  "第一次看高甲戏", "阿芳"),
            ("2026-05-07", "place",  "第一次到东山岛环岛", "阿芳"),
            ("2026-05-09", "food",   "第一次喝单丛鸭屎香", "阿芳"),
            ("2026-05-12", "skill",  "第一次浮潜", "阿芳"),
            ("2026-05-30", "skill",  "第一次自己补自行车胎", ""),
            ("2026-07-05", "event",  "第一次看露天话剧", "老周"),
        ]
        return self.ledger(["\t".join([d, c, n] + ([p] if p else []))
                            for d, c, n, p in rows])


class TestParsing(TmpCase):
    def test_missing_header_exit_2(self):
        path = self.write("x.tsv", "2026-01-01\tplace\tno header yet\n")
        code, _, err = run_main(["--today", TODAY, "report", path])
        self.assertEqual(code, 2)
        self.assertIn("header", err)

    def test_wrong_header_columns_exit_2(self):
        path = self.write("x.tsv", "date\twhen\twhat\n2026-01-01\tplace\tx\n")
        code, _, _ = run_main(["--today", TODAY, "report", path])
        self.assertEqual(code, 2)

    def test_bad_date_format_exit_2(self):
        path = self.ledger([self.row("2026/01/02")])
        code, _, err = run_main(["--today", TODAY, "report", path])
        self.assertEqual(code, 2)
        self.assertIn("bad date", err)

    def test_future_first_refused_exit_2(self):
        path = self.ledger([self.row("2026-09-01", note="明天的初事")])
        code, _, err = run_main(["--today", TODAY, "report", path])
        self.assertEqual(code, 2)
        self.assertIn("future", err)

    def test_unknown_category_refused_not_guessed(self):
        path = self.ledger([self.row("2026-01-01", category="adventure")])
        code, _, err = run_main(["--today", TODAY, "report", path])
        self.assertEqual(code, 2)
        self.assertIn("category must be one of", err)

    def test_category_casefolded(self):
        path = self.ledger([self.row("2026-01-01", category="PLACE")] +
                           self.spaced("2026-01-02", 6, 10))
        code, out, _ = run_main(["--today", TODAY, "sources", path])
        self.assertEqual(code, 0)
        self.assertIn("place", out)

    def test_empty_note_exit_2(self):
        path = self.ledger([self.row("2026-01-01", note="  ")])
        code, _, err = run_main(["--today", TODAY, "report", path])
        self.assertEqual(code, 2)
        self.assertIn("note", err)

    def test_too_few_columns_exit_2(self):
        path = self.ledger(["2026-01-01\tplace"])
        code, _, _ = run_main(["--today", TODAY, "report", path])
        self.assertEqual(code, 2)

    def test_duplicate_first_is_corruption_exit_2(self):
        path = self.ledger([self.row("2026-01-01", note="第一次潜水"),
                            self.row("2026-01-01", note="第一次潜水")])
        code, _, err = run_main(["--today", TODAY, "report", path])
        self.assertEqual(code, 2)
        self.assertIn("duplicate", err)

    def test_same_day_two_different_firsts_allowed(self):
        path = self.ledger([self.row("2026-01-01", category="food", note="第一次潜水"),
                            self.row("2026-01-01", category="place", note="第一次潜水")] +
                           self.spaced("2026-01-02", 6, 10))
        code, _, _ = run_main(["--today", TODAY, "validate", path])
        self.assertEqual(code, 0)

    def test_comments_and_blank_lines_skipped(self):
        path = self.ledger(["# a comment", "", self.row("2026-01-01")] +
                           self.spaced("2026-01-02", 6, 10))
        code, _, _ = run_main(["--today", TODAY, "validate", path])
        self.assertEqual(code, 0)

    def test_rows_sorted_by_date(self):
        path = self.ledger([self.row("2026-03-01"), self.row("2026-01-01"),
                            self.row("2026-02-01")])
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        days = [f.day for f in firsts]
        self.assertEqual(days, sorted(days))

    def test_people_split_on_separators_and_deduped(self):
        people = yd.split_people("阿芳、 阿芳 ,老周;小柯/&大刘")
        self.assertEqual(people, ["阿芳", "老周", "小柯", "大刘"])

    def test_three_column_row_has_no_people(self):
        path = self.ledger([self.row("2026-01-01")] + self.spaced("2026-01-02", 6, 10))
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        self.assertEqual(firsts[0].people, [])


class TestCoreMath(TmpCase):
    def test_coverage_runs_to_today_not_last_first(self):
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        start, end, covered = yd.coverage(firsts, date.fromisoformat(TODAY))
        self.assertEqual((start.isoformat(), end.isoformat(), covered),
                         ("2026-01-01", "2026-08-31", 243))

    def test_density_identity_exact(self):
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        _, _, covered = yd.coverage(firsts, date.fromisoformat(TODAY))
        self.assertAlmostEqual(len(firsts) / covered, 16 / 243)
        self.assertAlmostEqual(16 / 243, 0.06584362139917695)

    def test_month_table_clips_and_counts(self):
        firsts = [yd.First(date(2026, 1, 1), "place", "a", [], 2),
                  yd.First(date(2026, 1, 31), "place", "b", [], 3),
                  yd.First(date(2026, 2, 20), "place", "c", [], 4)]
        months = yd.month_table(firsts, date(2026, 1, 1), date(2026, 2, 25))
        self.assertEqual(months["2026-01"], [2, 31])
        self.assertEqual(months["2026-02"], [1, 25])

    def test_baseline_is_median_month_density(self):
        # Jan 5/31 = .16129, Feb 1/28 = .03571, Mar 0, Apr 1/30 = .03333,
        # May 8/31 = .25806, Jun 0, Jul 1/31 = .03226, Aug 0
        # → median(.0, .0, .0, .03226, .03333, .03571, .16129, .25806)
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        months = yd.month_table(firsts, date(2026, 1, 1), date(2026, 8, 31))
        self.assertAlmostEqual(yd.baseline_density(months), (1 / 31 + 1 / 30) / 2)

    def test_baseline_immune_to_burst_month(self):
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        before = yd.baseline_density(yd.month_table(firsts, date(2026, 1, 1), date(2026, 8, 31)))
        # a 20-first burst month raises the mean, not the median
        burst = [yd.First(date(2026, 6, d), "place", "b%d" % d, [], 100 + d)
                 for d in range(1, 21)]
        months = yd.month_table(firsts + burst, date(2026, 1, 1), date(2026, 8, 31))
        after = yd.baseline_density(months)
        self.assertAlmostEqual(after, (1 / 30 + 1 / 28) / 2)  # middle pair shifts one notch
        self.assertLess(after - before, 0.002)               # but the baseline barely moves
        self.assertLess(after, 0.6667 / 4)                   # and never becomes the burst

    def test_window_density_30_60_90(self):
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        today = date.fromisoformat(TODAY)
        self.assertAlmostEqual(yd.window_density(firsts, today, 30), 0.0)
        self.assertAlmostEqual(yd.window_density(firsts, today, 60), 1 / 60)
        self.assertAlmostEqual(yd.window_density(firsts, today, 90), 1 / 90)

    def test_streaks_recomputed_across_month_boundary(self):
        firsts = [yd.First(date(2026, 1, 31), "place", "a", [], 1),
                  yd.First(date(2026, 3, 2), "place", "b", [], 2)]
        streaks = yd.grey_streaks(firsts, date(2026, 1, 31), date(2026, 3, 5))
        self.assertEqual(streaks, [(date(2026, 2, 1), date(2026, 3, 1), 29),
                                   (date(2026, 3, 3), date(2026, 3, 5), 3)])

    def test_coverage_start_day_is_never_grey(self):
        firsts = [yd.First(date(2026, 1, 1), "place", "a", [], 1),
                  yd.First(date(2026, 1, 5), "place", "b", [], 2)]
        streaks = yd.grey_streaks(firsts, date(2026, 1, 1), date(2026, 1, 5))
        self.assertEqual(streaks, [(date(2026, 1, 2), date(2026, 1, 4), 3)])

    def test_current_streak_counts_when_today_is_grey(self):
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        streaks = yd.grey_streaks(firsts, date(2026, 1, 1), date(2026, 8, 31))
        self.assertEqual(streaks[-1], (date(2026, 7, 6), date(2026, 8, 31), 57))

    def test_current_streak_zero_when_today_has_a_first(self):
        rows = self.spaced("2026-06-01", 10, 3)  # firsts 6/1..6/28, today included
        path = self.ledger(rows)
        firsts = yd.read_ledger(path, date(2026, 6, 28))
        streaks = yd.grey_streaks(firsts, date(2026, 6, 1), date(2026, 6, 28))
        self.assertEqual(streaks[-1], (date(2026, 6, 26), date(2026, 6, 27), 2))
        self.assertNotEqual(streaks[-1][1], date(2026, 6, 28))  # today is not grey

    def test_sample_streak_list_exact(self):
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        streaks = yd.grey_streaks(firsts, date(2026, 1, 1), date(2026, 8, 31))
        big = [(a.isoformat(), b.isoformat(), n) for a, b, n in streaks if n >= 14]
        self.assertEqual(big, [
            ("2026-02-09", "2026-04-11", 62),
            ("2026-04-13", "2026-04-30", 18),
            ("2026-05-13", "2026-05-29", 17),
            ("2026-05-31", "2026-07-04", 35),
            ("2026-07-06", "2026-08-31", 57),
        ])

    def test_remembered_floor_is_ceil_of_personal_pace(self):
        self.assertEqual(yd.remembered_floor(16, 243), 2)   # ceil(1.9753)
        self.assertEqual(yd.remembered_floor(5, 200), 1)    # ceil(0.75)
        self.assertEqual(yd.remembered_floor(60, 120), 15)  # ceil(15.0)

    def test_category_stats_days_since_and_never(self):
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        today = date.fromisoformat(TODAY)
        cats = dict((c, (n, last, since))
                    for c, n, last, since in yd.category_stats(firsts, today, firsts[0].day))
        self.assertEqual(cats["place"], (5, date(2026, 5, 7), 116))
        self.assertEqual(cats["person"], (2, date(2026, 2, 8), 204))
        self.assertEqual(cats["media"], (0, None, 243))

    def test_suppliers_counted_and_sorted(self):
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        self.assertEqual(yd.supplier_counts(firsts),
                         [("阿芳", 9), ("老周", 2), ("小柯", 1)])

    def test_consumer_vs_growth_partition(self):
        path = self.sample()
        firsts = yd.read_ledger(path, date.fromisoformat(TODAY))
        counts = {}
        for f in firsts:
            counts[f.category] = counts.get(f.category, 0) + 1
        consumer = sum(counts.get(c, 0) for c in yd.CONSUMER)
        growth = sum(counts.get(c, 0) for c in yd.GROWTH)
        self.assertEqual((consumer, growth), (3, 13))
        self.assertEqual(consumer + growth, len(firsts))  # other/media untouched


class TestGate(TmpCase):
    def gate_path(self, rows, today=TODAY):
        path = self.ledger(rows)
        code, out, _ = run_main(["--today", today, "gate", path])
        return code, out

    def test_healthy_ledger_passes_exit_0(self):
        rows = self.spaced("2026-03-01", 20, 4)  # last 2026-05-16, today +1d
        code, out = self.gate_path(rows, today="2026-05-17")
        self.assertEqual(code, 0)
        self.assertIn("VERDICT: no greying signal", out)

    def test_streak_over_cap_alone_is_not_a_breach(self):
        # weekly firsts then a 30-day silence: streak signal YES, density ok
        rows = self.spaced("2026-01-04", 12, 7)  # last 2026-03-22
        code, out = self.gate_path(rows, today="2026-04-21")
        self.assertEqual(code, 0)
        self.assertIn("streak over cap YES", out)
        self.assertIn("density collapse no", out)
        self.assertIn("VERDICT: no greying signal", out)

    def test_double_signal_greying_exit_4(self):
        code, out, _ = run_main(["--today", TODAY, "gate", self.sample()])
        self.assertEqual(code, 4)
        self.assertIn("density collapse YES", out)
        self.assertIn("streak over cap YES", out)
        self.assertIn("RED LINE  climate greying", out)
        self.assertNotIn("absolute desert", out)  # 57 < 60: desert stays shut

    def test_absolute_desert_single_signal_exit_4(self):
        # steady weekly history, then silence long enough that the recent
        # window is empty AND the streak alone crosses the desert cap
        rows = self.spaced("2026-01-04", 12, 7)  # last 2026-03-22
        code, out = self.gate_path(rows, today="2026-05-21")  # 60-day streak
        self.assertEqual(code, 4)
        self.assertIn("RED LINE  absolute desert", out)

    def test_collapse_threshold_is_adjustable(self):
        # weekly history + a 30-day tail: collapse off at 0.5, forced on at 100
        rows = self.spaced("2026-01-04", 12, 7)
        path = self.ledger(rows)
        code, _, _ = run_main(["--today", "2026-04-21", "gate", path])
        self.assertEqual(code, 0)
        code, out, _ = run_main(["--today", "2026-04-21", "gate", path,
                                 "--collapse-ratio", "100.0"])
        self.assertEqual(code, 4)
        self.assertIn("RED LINE  climate greying", out)

    def test_streak_cap_adjustable(self):
        rows = self.spaced("2026-01-04", 12, 7)
        path = self.ledger(rows)
        code, out, _ = run_main(["--today", "2026-04-21", "gate", path,
                                 "--streak-cap", "365", "--desert-cap", "365"])
        self.assertEqual(code, 0)
        self.assertIn("signals: density ok · streak ok · no desert", out)

    def test_report_carries_the_same_gate(self):
        code, out, _ = run_main(["--today", TODAY, "report", self.sample()])
        self.assertEqual(code, 4)
        self.assertIn("RED LINE  climate greying", out)


class TestThin(TmpCase):
    def test_short_coverage_exit_3(self):
        rows = self.spaced("2026-08-01", 5, 2)  # 9 days covered
        path = self.ledger(rows)
        for cmd in (["report"], ["months"], ["streaks"], ["sources"],
                    ["simulate"], ["gate"]):
            code, _, err = run_main(["--today", TODAY, cmd[0], path])
            self.assertEqual(code, 3, cmd)
            self.assertIn("too thin", err)

    def test_few_firsts_exit_3(self):
        rows = self.spaced("2026-01-01", 4, 20)  # 61 days, 4 firsts
        path = self.ledger(rows)
        code, _, err = run_main(["--today", TODAY, "report", path])
        self.assertEqual(code, 3)
        self.assertIn("below the floor", err)

    def test_today_needs_five_firsts_only(self):
        rows = self.spaced("2026-08-01", 4, 2)
        path = self.ledger(rows)
        code, _, err = run_main(["--today", TODAY, "today", path])
        self.assertEqual(code, 3)

    def test_validate_never_refuses(self):
        rows = self.spaced("2026-08-01", 2, 2)
        path = self.ledger(rows)
        code, out, _ = run_main(["--today", TODAY, "validate", path])
        self.assertEqual(code, 0)
        self.assertIn("THIN", out)


class TestSimulate(TmpCase):
    def test_conservation_identity_on_sample(self):
        code, out, _ = run_main(["--today", TODAY, "simulate", self.sample()])
        self.assertEqual(code, 0)
        self.assertIn("inserted 27 synthetic first(s)", out)
        self.assertIn("(conservation: 16 + 27 = 43)", out)
        self.assertIn("43 == 16 + 27 (exact)", out)

    def test_every_one_fills_every_grey_day(self):
        rows = self.spaced("2026-04-01", 6, 12)  # five 11-day streaks, 61-day cover
        path = self.ledger(rows)
        code, out, _ = run_main(["--today", "2026-05-31", "simulate", path,
                                 "--every", "1"])
        self.assertEqual(code, 0)
        self.assertIn("inserted 55 synthetic first(s)", out)
        self.assertIn("longest grey streak: 11 → 0 day(s)", out)
        self.assertIn("(conservation: 6 + 55 = 61)", out)

    def test_inserts_land_inside_streaks_at_every_n_days(self):
        firsts = [yd.First(date(2026, 6, 1), "place", "a", [], 1),
                  yd.First(date(2026, 6, 21), "place", "b", [], 2)]
        # the streak runs 6/2 → 6/20; streak day 7 and day 14 are 6/8 and 6/15
        inserts = yd.simulate_inserts(firsts, date(2026, 6, 1), date(2026, 6, 25), 7)
        self.assertEqual(inserts, [date(2026, 6, 8), date(2026, 6, 15)])

    def test_remembered_months_only_improve_under_pinned_floor(self):
        code, out, _ = run_main(["--today", TODAY, "simulate", self.sample()])
        self.assertIn("remembered months: 2 → 8 of 8", out)
        self.assertIn("floor pinned at 2/month", out)

    def test_everyThirty_fewer_inserts(self):
        code, out, _ = run_main(["--today", TODAY, "simulate", self.sample(),
                                 "--every", "30"])
        self.assertIn("inserted 4 synthetic first(s)", out)  # 62d→2, 57d→1, 35d→1

    def test_every_below_one_exit_2(self):
        code, _, err = run_main(["--today", TODAY, "simulate", self.sample(),
                                 "--every", "0"])
        self.assertEqual(code, 2)
        self.assertIn("--every must be >= 1", err)


class TestReports(TmpCase):
    def test_report_numbers_on_sample(self):
        code, out, _ = run_main(["--today", TODAY, "report", self.sample()])
        self.assertEqual(code, 4)
        self.assertIn("16 first(s) over 243 day(s)", out)
        self.assertIn("0.0658 firsts/day", out)
        self.assertIn("annualized 24.0/year", out)
        self.assertIn("baseline (median month): 0.0328", out)
        self.assertIn("longest 62 day(s)", out)
        self.assertIn("current 57 day(s)", out)
        self.assertIn("remembered months: 2 of 8 at or above the floor of 2",
                      out)
        self.assertIn("top supplier: 阿芳 was there for 9 of 16 firsts (56.2%)",
                      out)

    def test_months_live_blur_and_pages(self):
        code, out, _ = run_main(["--today", TODAY, "months", self.sample()])
        self.assertEqual(code, 0)
        self.assertIn("2026-01   5  0.1613/day  LIVE   #####", out)
        self.assertIn("2026-05   8  0.2581/day  LIVE   ########", out)
        self.assertIn("2026-03   0  0.0000/day  BLUR", out)
        self.assertIn("the calendar turned 8 pages; memory bound 2 of them.",
                      out)

    def test_streaks_min_filter_and_current_marker(self):
        code, out, _ = run_main(["--today", TODAY, "streaks", self.sample()])
        self.assertIn("2026-07-06 → 2026-08-31  57 day(s)  ← current", out)
        self.assertIn("grey days total: 227 of 243 (93.4%)", out)
        code, out, _ = run_main(["--today", TODAY, "streaks", self.sample(),
                                 "--min", "100"])
        self.assertIn("(none", out)

    def test_sources_hungriest_tried_and_untouched_split(self):
        code, out, _ = run_main(["--today", TODAY, "sources", self.sample()])
        self.assertIn("hungriest tried category: person (人) — 204 day(s)",
                      out)
        self.assertIn("untouched categories: media, other", out)
        self.assertIn("last 2026-05-07, 116 day(s) ago", out)
        self.assertIn("never in this ledger", out)

    def test_today_brief_and_gate(self):
        code, out, _ = run_main(["--today", TODAY, "today", self.sample()])
        self.assertEqual(code, 4)
        self.assertIn("last first: 2026-07-05 (事件: 第一次看露天话剧) — 57 day(s) ago",
                      out)
        self.assertIn("you are standing in one", out)

    def test_validate_identities_and_disclosures(self):
        code, out, _ = run_main(["--today", TODAY, "validate", self.sample()])
        self.assertEqual(code, 0)
        self.assertIn("16 == 16 == 16", out)
        self.assertIn("16 ÷ 243 = 0.065843621", out)
        self.assertIn("rows without people: 5", out)
        self.assertIn("categories present: event, food, person, place, skill",
                      out)
        self.assertIn("suppliers named: 阿芳, 老周, 小柯", out)


class TestReproducibility(TmpCase):
    def test_pinned_today_is_byte_identical(self):
        path = self.sample()
        outs = []
        for _ in range(2):
            code, out, _ = run_main(["--today", TODAY, "report", path])
            outs.append(out)
        self.assertEqual(outs[0], outs[1])

    def test_different_today_changes_coverage(self):
        path = self.sample()
        _, out_a, _ = run_main(["--today", "2026-08-31", "report", path])
        _, out_b, _ = run_main(["--today", "2026-07-31", "report", path])
        self.assertIn("243 day(s)", out_a)
        self.assertIn("212 day(s)", out_b)


if __name__ == "__main__":
    unittest.main()
